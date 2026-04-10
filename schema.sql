-- Paperclip Native Port — SQLite Schema
-- Faithfully ported from Paperclip's Drizzle ORM schema (PostgreSQL)
-- Source: github.com/paperclipai/paperclip/packages/db/src/schema/

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name TEXT NOT NULL,
    mission TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL,
    description TEXT,
    level TEXT NOT NULL DEFAULT 'task' CHECK (level IN ('company', 'team', 'agent', 'task')),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'achieved', 'cancelled')),
    parent_id TEXT REFERENCES goals(id),
    owner_agent_id TEXT REFERENCES agents(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'general',
    title TEXT,
    department TEXT,
    reports_to TEXT REFERENCES agents(id),
    default_model TEXT DEFAULT 'sonnet',
    fallback_model TEXT DEFAULT 'haiku',
    emergency_model TEXT DEFAULT 'haiku',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'terminated')),
    pause_reason TEXT,
    paused_at TEXT,
    budget_monthly_cents INTEGER DEFAULT 0,
    spent_monthly_cents INTEGER DEFAULT 0,
    max_iterations_per_session INTEGER DEFAULT 15,
    last_heartbeat_at TEXT,
    capabilities TEXT,
    permissions TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    goal_id TEXT REFERENCES goals(id),
    status TEXT DEFAULT 'active',
    path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    issue_number INTEGER NOT NULL,
    identifier TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'assigned', 'in_progress', 'in_review', 'done', 'blocked', 'cancelled', 'wont_fix')),
    priority TEXT NOT NULL DEFAULT 'P2' CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
    assignee_agent_id TEXT REFERENCES agents(id),
    reporter TEXT DEFAULT 'COO',
    goal_id TEXT REFERENCES goals(id),
    project_id TEXT REFERENCES projects(id),
    parent_id TEXT REFERENCES issues(id),
    origin_kind TEXT DEFAULT 'manual' CHECK (origin_kind IN ('manual', 'delegation', 'routine_execution')),
    origin_id TEXT,
    request_depth INTEGER DEFAULT 0,
    billing_code TEXT,
    execution_locked_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS issues_company_number ON issues(company_id, issue_number);

CREATE TABLE IF NOT EXISTS issue_comments (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    author_agent_id TEXT REFERENCES agents(id),
    author_user TEXT,
    body TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS issue_read_states (
    issue_id TEXT NOT NULL REFERENCES issues(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    read_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (issue_id, agent_id)
);

CREATE TABLE IF NOT EXISTS issue_work_products (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    file_path TEXT NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_policies (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('company', 'agent', 'project')),
    scope_id TEXT NOT NULL,
    metric TEXT DEFAULT 'iterations',
    window_kind TEXT NOT NULL DEFAULT 'session' CHECK (window_kind IN ('session', 'daily', 'monthly')),
    amount INTEGER DEFAULT 0,
    warn_percent INTEGER DEFAULT 80,
    hard_stop_enabled INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cost_events (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    agent_id TEXT REFERENCES agents(id),
    issue_id TEXT REFERENCES issues(id),
    project_id TEXT REFERENCES projects(id),
    goal_id TEXT REFERENCES goals(id),
    session_id TEXT,
    model TEXT NOT NULL DEFAULT 'unknown',
    provider TEXT NOT NULL DEFAULT 'anthropic',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_cents INTEGER DEFAULT 0,
    billing_code TEXT,
    occurred_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_incidents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    policy_id TEXT REFERENCES budget_policies(id),
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    threshold_type TEXT NOT NULL CHECK (threshold_type IN ('warn', 'hard_stop')),
    amount_limit INTEGER NOT NULL,
    amount_observed INTEGER NOT NULL,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS heartbeat_runs (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    status TEXT DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out')),
    started_at TEXT,
    finished_at TEXT,
    session_id TEXT,
    exit_code INTEGER,
    error TEXT,
    stdout_excerpt TEXT,
    usage_input_tokens INTEGER,
    usage_output_tokens INTEGER,
    usage_cost_cents INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_config_revisions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    source TEXT DEFAULT 'patch' CHECK (source IN ('patch', 'rollback', 'import')),
    rolled_back_from_revision_id TEXT,
    changed_keys TEXT,
    before_config TEXT NOT NULL,
    after_config TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    type TEXT NOT NULL CHECK (type IN ('hire_agent', 'budget_change', 'strategy', 'promotion', 'deployment')),
    description TEXT NOT NULL,
    requested_by TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    decision_note TEXT,
    decided_by TEXT,
    decided_at TEXT,
    payload TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS communication_paths (
    from_agent_id TEXT NOT NULL REFERENCES agents(id),
    to_agent_id TEXT NOT NULL REFERENCES agents(id),
    PRIMARY KEY (from_agent_id, to_agent_id)
);

-- Routines — scheduled/triggered recurring work (Source: Paperclip v2 research)
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER DEFAULT 1,
    schedule TEXT,  -- cron expression (e.g., "0 9 * * 1-5" for weekdays at 9am)
    issue_template_title TEXT,
    issue_template_description TEXT,
    issue_template_priority TEXT DEFAULT 'P2',
    issue_template_goal_id TEXT REFERENCES goals(id),
    assignee_agent_id TEXT REFERENCES agents(id),
    skip_if_active INTEGER DEFAULT 1,  -- don't create new issue if one from this routine is still open
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Partial unique index: only one open issue per routine (skip_if_active enforcement)
CREATE UNIQUE INDEX IF NOT EXISTS routines_one_active_issue
    ON issues(company_id, origin_kind, origin_id)
    WHERE origin_kind = 'routine_execution'
      AND origin_id IS NOT NULL
      AND status IN ('open', 'assigned', 'in_progress', 'in_review', 'blocked');

CREATE TABLE IF NOT EXISTS routine_runs (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    routine_id TEXT NOT NULL REFERENCES routines(id),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'skipped', 'failed')),
    skip_reason TEXT,
    issue_id TEXT REFERENCES issues(id),  -- the issue created by this run (if any)
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Agent wakeup requests — event-driven heartbeats (Source: Paperclip v2 research)
CREATE TABLE IF NOT EXISTS agent_wakeup_requests (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    company_id TEXT NOT NULL REFERENCES companies(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    reason TEXT NOT NULL,  -- 'blocker_done', 'children_done', 'manual', 'routine_trigger'
    source_issue_id TEXT REFERENCES issues(id),
    idempotency_key TEXT,  -- prevent duplicate wakeups
    coalesced_count INTEGER DEFAULT 1,  -- how many wakeups merged into this one
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'expired')),
    created_at TEXT DEFAULT (datetime('now')),
    delivered_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS wakeup_idempotency
    ON agent_wakeup_requests(idempotency_key)
    WHERE idempotency_key IS NOT NULL AND status = 'pending';
