#!/usr/bin/env python3
"""
Paperclip Native Port — SQLite service layer for Claude Code CLI.
Faithfully ports Paperclip's PostgreSQL backend to SQLite.
Source: github.com/paperclipai/paperclip

Usage:
    python scripts/paperclip.py <service> <action> [args]

Services: init, issue, budget, agent, goal, approve, config
"""

import sqlite3
import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# DB and schema paths — configurable via env vars for portability.
# Default: co-located with this script in engines/paperclip/state/
DB_PATH = Path(os.environ.get(
    "PAPERCLIP_DB",
    str(Path(__file__).parent / "state" / "paperclip.db")
))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db

def uid():
    import secrets
    return secrets.token_hex(16)

def now():
    return datetime.now(tz=__import__('datetime').timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ═══════════════════════════════════════════════════════════════════════════════
# INIT — Create database + seed data
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript(SCHEMA_PATH.read_text())

    # Check if already seeded
    row = db.execute("SELECT COUNT(*) as c FROM companies").fetchone()
    if row["c"] > 0:
        print("Database already initialized.")
        return

    company_id = uid()
    db.execute("INSERT INTO companies (id, name, mission) VALUES (?, ?, ?)",
               (company_id, "Easy Ecommerce Group",
                "Build EEG into the go-to DTC ecommerce agency — measured by client count, revenue, and retention."))

    # Goals (G1-G5)
    goals = [
        ("G1", "Client Acquisition", "company", "Grow the client base through outreach, referrals, and portfolio showcasing."),
        ("G2", "Revenue Growth", "company", "Increase revenue per client and total monthly revenue."),
        ("G3", "Client Retention", "company", "Keep clients happy through quality delivery and proactive communication."),
        ("G4", "Operational Excellence", "company", "Build the systems that make the agency run efficiently and at high quality."),
        ("G5", "Product Development", "company", "Build revenue-generating products beyond agency work."),
    ]
    goal_ids = {}
    for gkey, title, level, desc in goals:
        gid = uid()
        goal_ids[gkey] = gid
        db.execute("INSERT INTO goals (id, company_id, title, description, level, status) VALUES (?, ?, ?, ?, ?, 'active')",
                   (gid, company_id, f"{gkey}: {title}", desc, level))

    # Agents (all 14)
    agents_data = [
        ("Morgan", "morgan", "Chief of Staff", "Strategy", "Operations", None, "opus", 10),
        ("Atlas", "atlas", "Architecture Advisor", "Architecture", "Consultants", "morgan", "opus", 8),
        ("Sage", "sage", "Business Strategy Advisor", "Strategy", "Consultants", "morgan", "opus", 8),
        ("Pixel", "pixel", "UX Design Advisor", "Visual Quality", "Design", None, "opus", 12),
        ("Nova", "nova", "Engineering Lead", "Implementation", "Build", None, "sonnet", 15),
        ("Sentinel", "sentinel", "QA Lead", "Verification", "QA", None, "sonnet", 12),
        ("Scout", "scout", "Research Lead", "Research", "Research", None, "opus", 10),
        ("Metric", "metric", "Performance Reviewer", "Reviews", "Strategy", "morgan", "sonnet", 6),
        ("Relay", "relay", "Executive Assistant", "Doc Maintenance", "Operations", "morgan", "haiku", 8),
        ("Sterling", "sterling", "Client Operations", "Client Relations", "Operations", None, "opus", 8),
        ("Quill", "quill", "Copywriter", "Copy", "Content", None, "sonnet", 10),
        ("Banner", "banner", "Hero Designer", "Hero Sections", "Design", "pixel", "opus", 12),
        ("Index", "index", "SEO Specialist", "SEO", "Content", "scout", "sonnet", 8),
        ("Freud", "freud", "Conversion Psychologist", "Conversion", "Content", None, "sonnet", 8),
    ]

    agent_ids = {}
    # First pass: create all agents without reports_to
    for name, key, role, title, dept, _, model, max_iter in agents_data:
        aid = uid()
        agent_ids[key] = aid
        db.execute("""INSERT INTO agents (id, company_id, name, name_key, role, title, department,
                      default_model, max_iterations_per_session) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (aid, company_id, name, key, role, title, dept, model, max_iter))

    # Second pass: set reports_to
    for name, key, role, title, dept, reports_to, model, max_iter in agents_data:
        if reports_to and reports_to in agent_ids:
            db.execute("UPDATE agents SET reports_to = ? WHERE name_key = ?",
                       (agent_ids[reports_to], key))

    # Operator agent (the system itself, configurable via PAPERCLIP_OPERATOR_* env vars)
    # Default is "Operator" — co-founder skill installs override these to "COO" via env vars.
    operator_name = os.environ.get("PAPERCLIP_OPERATOR_NAME", "Operator")
    operator_key = os.environ.get("PAPERCLIP_OPERATOR_KEY", "operator")
    operator_title = os.environ.get("PAPERCLIP_OPERATOR_TITLE", "Operator")
    operator_dept = os.environ.get("PAPERCLIP_OPERATOR_DEPT", "Executive")
    coo_id = uid()
    agent_ids[operator_key] = coo_id
    db.execute("""INSERT INTO agents (id, company_id, name, name_key, role, title, department,
                  default_model, max_iterations_per_session) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (coo_id, company_id, operator_name, operator_key, "executive", operator_title, operator_dept, "opus", 50))

    # Communication paths (operator can delegate to all team agents)
    for key, aid in agent_ids.items():
        if key != operator_key:
            db.execute("INSERT INTO communication_paths (from_agent_id, to_agent_id) VALUES (?, ?)",
                       (coo_id, aid))
    # Pixel -> Banner, Scout -> Index
    db.execute("INSERT INTO communication_paths (from_agent_id, to_agent_id) VALUES (?, ?)",
               (agent_ids["pixel"], agent_ids["banner"]))
    db.execute("INSERT INTO communication_paths (from_agent_id, to_agent_id) VALUES (?, ?)",
               (agent_ids["scout"], agent_ids["index"]))

    # Budget policies (per-agent iteration caps)
    for name, key, role, title, dept, _, model, max_iter in agents_data:
        db.execute("""INSERT INTO budget_policies (id, company_id, scope_type, scope_id, metric,
                      window_kind, amount, warn_percent, hard_stop_enabled)
                      VALUES (?, ?, 'agent', ?, 'iterations', 'session', ?, 80, 1)""",
                   (uid(), company_id, agent_ids[key], max_iter))

    db.commit()
    print(f"Database initialized: {DB_PATH}")
    print(f"  Company: Easy Ecommerce Group")
    print(f"  Goals: {len(goals)}")
    print(f"  Agents: {len(agents_data) + 1}")
    print(f"  Budget policies: {len(agents_data)}")
    print(f"  Communication paths: {len(agent_ids) - 1 + 2}")

# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

VALID_TRANSITIONS = {
    "open": ["assigned", "wont_fix"],
    "assigned": ["in_progress", "open"],
    "in_progress": ["in_review", "blocked"],
    "in_review": ["done", "in_progress"],
    "blocked": ["in_progress"],
    "done": [],
    "cancelled": [],
    "wont_fix": [],
}

def get_company_id(db):
    row = db.execute("SELECT id FROM companies LIMIT 1").fetchone()
    return row["id"] if row else None

def resolve_agent(db, name):
    row = db.execute("SELECT id, name FROM agents WHERE name_key = ? OR name = ? COLLATE NOCASE",
                     (name.lower(), name)).fetchone()
    return row if row else None

def cmd_issue(args):
    if not args:
        args = ["list"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "list":
        query = "SELECT i.identifier, i.title, i.status, i.priority, a.name as assignee, i.updated_at FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id LEFT JOIN goals g ON i.goal_id = g.id WHERE i.company_id = ?"
        params = [company_id]
        # Parse filters
        i = 1
        while i < len(args):
            if args[i] == "--status" and i + 1 < len(args):
                query += " AND i.status = ?"
                params.append(args[i + 1])
                i += 2
            elif args[i] == "--assignee" and i + 1 < len(args):
                query += " AND a.name = ? COLLATE NOCASE"
                params.append(args[i + 1])
                i += 2
            elif args[i] == "--priority" and i + 1 < len(args):
                query += " AND i.priority = ?"
                params.append(args[i + 1])
                i += 2
            elif args[i] == "--goal" and i + 1 < len(args):
                query += " AND g.title LIKE ?"
                params.append(f"{args[i+1]}%")
                i += 2
            else:
                i += 1
        query += " ORDER BY i.priority, i.updated_at DESC"
        rows = db.execute(query, params).fetchall()
        if not rows:
            print("No issues found.")
            return
        print(f"{'ID':<12} {'Title':<35} {'Status':<13} {'Pri':<4} {'Assignee':<12} {'Updated':<20}")
        print("-" * 96)
        for r in rows:
            print(f"{r['identifier']:<12} {(r['title'] or '')[:34]:<35} {r['status']:<13} {r['priority']:<4} {(r['assignee'] or 'none'):<12} {(r['updated_at'] or '')[:19]:<20}")

    elif action == "create":
        title = args[1] if len(args) > 1 else "Untitled"
        assignee = priority = goal_key = project = billing = parent_ref = None
        i = 2
        while i < len(args):
            if args[i] == "--assignee" and i + 1 < len(args): assignee = args[i + 1]; i += 2
            elif args[i] == "--priority" and i + 1 < len(args): priority = args[i + 1]; i += 2
            elif args[i] == "--goal" and i + 1 < len(args): goal_key = args[i + 1]; i += 2
            elif args[i] == "--project" and i + 1 < len(args): project = args[i + 1]; i += 2
            elif args[i] == "--billing" and i + 1 < len(args): billing = args[i + 1]; i += 2
            elif args[i] == "--origin" and i + 1 < len(args): origin = args[i + 1]; i += 2
            elif args[i] == "--depth" and i + 1 < len(args): depth = int(args[i + 1]); i += 2
            elif args[i] == "--parent" and i + 1 < len(args): parent_ref = args[i + 1]; i += 2
            else: i += 1

        assignee_id = None
        if assignee:
            agent = resolve_agent(db, assignee)
            if agent: assignee_id = agent["id"]

        goal_id = None
        if goal_key:
            grow = db.execute("SELECT id FROM goals WHERE title LIKE ? AND company_id = ?", (f"{goal_key}%", company_id)).fetchone()
            if grow: goal_id = grow["id"]

        # Resolve parent issue by identifier (e.g. EEG-005)
        parent_id = None
        if parent_ref:
            prow = db.execute("SELECT id FROM issues WHERE identifier = ? AND company_id = ?", (parent_ref, company_id)).fetchone()
            if prow: parent_id = prow["id"]

        origin = locals().get("origin", "manual")
        depth = locals().get("depth", 0)

        # Atomic issue creation with retry on UNIQUE collision.
        # issues_company_number is a UNIQUE index on (company_id, issue_number),
        # so concurrent MAX+1 collisions fail the INSERT and we retry with fresh MAX.
        import time
        max_retries = 10
        issue_id = uid()
        num = None
        identifier = None
        for attempt in range(max_retries):
            try:
                row = db.execute("SELECT COALESCE(MAX(issue_number), 0) + 1 as next_num FROM issues WHERE company_id = ?", (company_id,)).fetchone()
                num = row["next_num"]
                identifier = f"EEG-{num:03d}"
                db.execute("""INSERT INTO issues (id, company_id, issue_number, identifier, title, status, priority,
                              assignee_agent_id, goal_id, parent_id, billing_code, origin_kind, request_depth)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (issue_id, company_id, num, identifier, title,
                            "assigned" if assignee_id else "open",
                            priority or "P2", assignee_id, goal_id, parent_id, billing or "internal", origin, depth))
                db.commit()
                break
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e) and attempt < max_retries - 1:
                    # Another process got this number — wait briefly and retry
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        print(f"Created {identifier}: {title}")
        if assignee: print(f"  Assigned to: {assignee}")
        print(f"  Priority: {priority or 'P2'}")

    elif action == "checkout":
        if len(args) < 3:
            print("Usage: issue checkout <identifier> <agent_name>")
            return
        identifier, agent_name = args[1], args[2]
        agent = resolve_agent(db, agent_name)
        if not agent:
            print(f"CONFLICT: Agent '{agent_name}' not found")
            return

        # Atomic checkout — single UPDATE with WHERE clause (Paperclip pattern)
        result = db.execute("""UPDATE issues SET assignee_agent_id = ?, status = 'in_progress',
                              started_at = ?, execution_locked_at = ?, updated_at = ?
                              WHERE identifier = ? AND status IN ('open', 'assigned', 'blocked')
                              AND (assignee_agent_id IS NULL OR assignee_agent_id = ?)""",
                           (agent["id"], now(), now(), now(), identifier, agent["id"]))
        db.commit()
        if result.rowcount == 0:
            row = db.execute("SELECT i.status, a.name as assignee FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id WHERE i.identifier = ?", (identifier,)).fetchone()
            if row:
                print(f"CONFLICT: {identifier} is {row['status']}, assigned to {row['assignee'] or 'nobody'}. Cannot checkout.")
            else:
                print(f"CONFLICT: {identifier} not found.")
        else:
            print(f"OK: {agent['name']} checked out {identifier}")

    elif action == "complete":
        if len(args) < 2:
            print("Usage: issue complete <identifier> [--output 'summary']")
            return
        identifier = args[1]
        output = ""
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args): output = args[idx + 1]

        result = db.execute("""UPDATE issues SET status = 'in_review', completed_at = ?, updated_at = ?
                              WHERE identifier = ? AND status IN ('in_progress', 'assigned')""",
                           (now(), now(), identifier))
        db.commit()
        if result.rowcount > 0:
            if output:
                issue_row = db.execute("SELECT id FROM issues WHERE identifier = ?", (identifier,)).fetchone()
                if issue_row:
                    db.execute("INSERT INTO issue_comments (id, company_id, issue_id, author_user, body) VALUES (?, ?, ?, 'agent', ?)",
                               (uid(), company_id, issue_row["id"], f"Task completed. Output: {output[:500]}"))
                    db.commit()
            print(f"OK: {identifier} → in_review")
        else:
            print(f"CONFLICT: {identifier} not in a completable state")

    elif action == "update":
        if len(args) < 4 or args[2] != "--status":
            print("Usage: issue update <identifier> --status <new_status>")
            return
        identifier, new_status = args[1], args[3]
        row = db.execute("SELECT status FROM issues WHERE identifier = ?", (identifier,)).fetchone()
        if not row:
            print(f"NOT FOUND: {identifier}")
            return
        old_status = row["status"]
        if new_status not in VALID_TRANSITIONS.get(old_status, []):
            print(f"INVALID TRANSITION: {old_status} → {new_status}. Allowed: {VALID_TRANSITIONS.get(old_status, [])}")
            return
        db.execute("UPDATE issues SET status = ?, updated_at = ? WHERE identifier = ?",
                   (new_status, now(), identifier))
        db.commit()
        print(f"OK: {identifier} {old_status} → {new_status}")

    elif action == "comment":
        if len(args) < 4:
            print("Usage: issue comment <identifier> <author> <body>")
            return
        identifier, author, body = args[1], args[2], " ".join(args[3:])
        issue_row = db.execute("SELECT id FROM issues WHERE identifier = ?", (identifier,)).fetchone()
        if not issue_row:
            print(f"NOT FOUND: {identifier}")
            return
        db.execute("INSERT INTO issue_comments (id, company_id, issue_id, author_user, body) VALUES (?, ?, ?, ?, ?)",
                   (uid(), company_id, issue_row["id"], author, body))
        db.commit()
        print(f"OK: Comment added to {identifier}")

    elif action == "view":
        if len(args) < 2:
            print("Usage: issue view <identifier>")
            return
        identifier = args[1]
        row = db.execute("""SELECT i.*, a.name as assignee_name, g.title as goal_title
                           FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id
                           LEFT JOIN goals g ON i.goal_id = g.id WHERE i.identifier = ?""", (identifier,)).fetchone()
        if not row:
            print(f"NOT FOUND: {identifier}")
            return
        print(f"{'='*60}")
        print(f"  {row['identifier']}: {row['title']}")
        print(f"  Status: {row['status']}  Priority: {row['priority']}")
        print(f"  Assignee: {row['assignee_name'] or 'unassigned'}")
        print(f"  Goal: {row['goal_title'] or 'unlinked'}")
        print(f"  Origin: {row['origin_kind']}  Depth: {row['request_depth']}")
        print(f"  Billing: {row['billing_code'] or 'none'}")
        print(f"  Created: {row['created_at']}  Updated: {row['updated_at']}")
        print(f"{'='*60}")
        comments = db.execute("SELECT author_user, body, created_at FROM issue_comments WHERE issue_id = ? ORDER BY created_at", (row["id"],)).fetchall()
        if comments:
            print("  Comments:")
            for c in comments:
                print(f"    [{c['created_at'][:16]}] {c['author_user']}: {c['body'][:100]}")
        products = db.execute("SELECT file_path, description FROM issue_work_products WHERE issue_id = ?", (row["id"],)).fetchall()
        if products:
            print("  Work Products:")
            for p in products:
                print(f"    - {p['file_path']}")

    elif action == "kanban":
        statuses = ["open", "assigned", "in_progress", "in_review", "blocked", "done"]
        for s in statuses:
            rows = db.execute("SELECT i.identifier, i.priority, a.name as assignee FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id WHERE i.status = ? AND i.company_id = ? ORDER BY i.priority", (s, company_id)).fetchall()
            print(f"\n  {s.upper()} ({len(rows)})")
            print(f"  {'-'*30}")
            for r in rows:
                print(f"  {r['identifier']} {r['priority']} {r['assignee'] or ''}")

    else:
        print(f"Unknown issue action: {action}")
        print("Valid actions: list, create, checkout, update, comment, view, complete, kanban")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# BUDGET SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_budget(args):
    if not args:
        args = ["status"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "status":
        agent_filter = None
        if "--agent" in args:
            idx = args.index("--agent")
            if idx + 1 < len(args): agent_filter = args[idx + 1]

        # Auto-detect current session from latest cost event if env var not set
        session_id = os.environ.get("SESSION_ID")
        if not session_id:
            latest = db.execute("SELECT session_id FROM cost_events ORDER BY occurred_at DESC LIMIT 1").fetchone()
            session_id = latest["session_id"] if latest else "no-session"

        query = """SELECT a.name, a.name_key, bp.amount as cap,
                   COUNT(ce.id) as used, a.status as agent_status
                   FROM agents a
                   LEFT JOIN budget_policies bp ON bp.scope_id = a.id AND bp.scope_type = 'agent' AND bp.is_active = 1
                   LEFT JOIN cost_events ce ON ce.agent_id = a.id AND ce.session_id = ?
                   WHERE a.company_id = ? AND a.name_key != 'coo'"""
        params = [session_id, company_id]
        if agent_filter:
            query += " AND (a.name = ? COLLATE NOCASE OR a.name_key = ?)"
            params.extend([agent_filter, agent_filter.lower()])
        query += " GROUP BY a.id ORDER BY a.name"

        rows = db.execute(query, params).fetchall()
        total_used = sum(r["used"] for r in rows)
        print(f"\n  Budget Status (session: {session_id[:8]})")
        print(f"  Session total: {total_used}/15")
        print(f"\n  {'Agent':<12} {'Used':<6} {'Cap':<6} {'%':<6} {'Status':<10}")
        print(f"  {'-'*40}")
        for r in rows:
            cap = r["cap"] or 15
            used = r["used"]
            pct = int(used / cap * 100) if cap > 0 else 0
            status = "BLOCKED" if pct >= 100 else "WARNING" if pct >= 80 else "ok"
            if r["agent_status"] == "paused": status = "PAUSED"
            print(f"  {r['name']:<12} {used:<6} {cap:<6} {pct:<5}% {status:<10}")

    elif action == "check":
        if len(args) < 2:
            print("ok")
            return
        agent_name = args[1]
        session_id = os.environ.get("SESSION_ID", "current")
        agent = resolve_agent(db, agent_name)
        if not agent:
            print("ok")
            return
        # Check if agent is paused/terminated
        status_row = db.execute("SELECT status, pause_reason FROM agents WHERE id = ?", (agent["id"],)).fetchone()
        if status_row and status_row["status"] == "paused":
            print(f"paused:{status_row['pause_reason'] or 'no reason given'}")
            return
        if status_row and status_row["status"] == "terminated":
            print("terminated")
            return
        policy = db.execute("SELECT amount FROM budget_policies WHERE scope_id = ? AND scope_type = 'agent' AND is_active = 1", (agent["id"],)).fetchone()
        cap = policy["amount"] if policy else 15
        used = db.execute("SELECT COUNT(*) as c FROM cost_events WHERE agent_id = ? AND session_id = ?", (agent["id"], session_id)).fetchone()["c"]
        pct = int(used / cap * 100) if cap > 0 else 0
        if pct >= 100:
            print("blocked")
        elif pct >= 80:
            print(f"warn:{used}/{cap}")
        else:
            print("ok")

    elif action == "log":
        if len(args) < 4:
            print("Usage: budget log <agent> <model> <session_id> [--tokens-in X] [--tokens-out Y]")
            return
        agent_name, model, session_id = args[1], args[2], args[3]
        tokens_in = tokens_out = cost = 0
        i = 4
        while i < len(args):
            if args[i] == "--tokens-in" and i + 1 < len(args): tokens_in = int(args[i + 1]); i += 2
            elif args[i] == "--tokens-out" and i + 1 < len(args): tokens_out = int(args[i + 1]); i += 2
            elif args[i] == "--cost" and i + 1 < len(args): cost = int(args[i + 1]); i += 2
            else: i += 1

        agent = resolve_agent(db, agent_name)
        agent_id = agent["id"] if agent else None
        db.execute("""INSERT INTO cost_events (id, company_id, agent_id, session_id, model, input_tokens, output_tokens, cost_cents)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (uid(), company_id, agent_id, session_id, model, tokens_in, tokens_out, cost))
        db.commit()
        print(f"OK: Logged {model} delegation for {agent_name}")

    elif action == "reset":
        if len(args) < 2:
            print("Usage: budget reset <agent>")
            return
        agent = resolve_agent(db, args[1])
        if not agent:
            print(f"NOT FOUND: {args[1]}")
            return
        session_id = os.environ.get("SESSION_ID", "current")
        db.execute("DELETE FROM cost_events WHERE agent_id = ? AND session_id = ?", (agent["id"], session_id))
        db.commit()
        print(f"OK: Budget reset for {agent['name']}")

    else:
        print(f"Unknown budget action: {action}")
        print("Valid actions: status, check, log, reset")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_agent(args):
    if not args:
        args = ["list"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "list" or action == "status":
        name_filter = args[1] if len(args) > 1 and not args[1].startswith("--") else None
        query = """SELECT a.name, a.role, a.department, a.status, a.default_model,
                   a.last_heartbeat_at, m.name as manager
                   FROM agents a LEFT JOIN agents m ON a.reports_to = m.id
                   WHERE a.company_id = ? AND a.name_key != 'coo'"""
        params = [company_id]
        if name_filter:
            query += " AND (a.name = ? COLLATE NOCASE OR a.name_key = ?)"
            params.extend([name_filter, name_filter.lower()])
        query += " ORDER BY a.department, a.name"

        rows = db.execute(query, params).fetchall()
        print(f"\n  {'Agent':<12} {'Role':<25} {'Dept':<12} {'Model':<8} {'Status':<8} {'Manager':<10}")
        print(f"  {'-'*75}")
        for r in rows:
            print(f"  {r['name']:<12} {(r['role'] or '')[:24]:<25} {(r['department'] or ''):<12} {r['default_model']:<8} {r['status']:<8} {r['manager'] or '—':<10}")

    elif action == "pause":
        if len(args) < 2:
            print("Usage: agent pause <name> --reason 'text'")
            return
        reason = ""
        if "--reason" in args:
            idx = args.index("--reason")
            if idx + 1 < len(args): reason = args[idx + 1]
        db.execute("UPDATE agents SET status = 'paused', pause_reason = ?, paused_at = ? WHERE name = ? COLLATE NOCASE OR name_key = ?",
                   (reason, now(), args[1], args[1].lower()))
        db.commit()
        print(f"OK: {args[1]} paused. Reason: {reason}")

    elif action == "resume":
        if len(args) < 2:
            print("Usage: agent resume <name>")
            return
        db.execute("UPDATE agents SET status = 'active', pause_reason = NULL, paused_at = NULL WHERE name = ? COLLATE NOCASE OR name_key = ?",
                   (args[1], args[1].lower()))
        db.commit()
        print(f"OK: {args[1]} resumed")

    elif action == "heartbeat":
        if len(args) < 2:
            print("Usage: agent heartbeat <name>")
            return
        db.execute("UPDATE agents SET last_heartbeat_at = ? WHERE name = ? COLLATE NOCASE OR name_key = ?",
                   (now(), args[1], args[1].lower()))
        db.commit()
        print(f"OK: Heartbeat recorded for {args[1]}")

    elif action == "heartbeat-run":
        if len(args) < 3:
            print("Usage: agent heartbeat-run <agent> <status> [--session <id>] [--exit <n>]")
            print("  status: queued|running|succeeded|failed|cancelled|timed_out")
            return
        agent_name = args[1]
        status = args[2]
        if status not in ("queued", "running", "succeeded", "failed", "cancelled", "timed_out"):
            print(f"Invalid status '{status}'")
            return
        session_id = None
        exit_code = None
        in_tok = out_tok = cost_cents = None
        started_at = None
        i = 3
        while i < len(args):
            if args[i] == "--session" and i + 1 < len(args): session_id = args[i + 1]; i += 2
            elif args[i] == "--exit" and i + 1 < len(args): exit_code = int(args[i + 1]); i += 2
            elif args[i] == "--in-tok" and i + 1 < len(args): in_tok = int(args[i + 1]); i += 2
            elif args[i] == "--out-tok" and i + 1 < len(args): out_tok = int(args[i + 1]); i += 2
            elif args[i] == "--cost-cents" and i + 1 < len(args): cost_cents = int(args[i + 1]); i += 2
            elif args[i] == "--started" and i + 1 < len(args): started_at = args[i + 1]; i += 2
            else: i += 1
        agent = resolve_agent(db, agent_name)
        if not agent:
            print(f"CONFLICT: Agent '{agent_name}' not found")
            return
        finished_at = now() if status in ("succeeded", "failed", "cancelled", "timed_out") else None
        db.execute("""INSERT INTO heartbeat_runs
                      (id, company_id, agent_id, status, started_at, finished_at, session_id,
                       exit_code, usage_input_tokens, usage_output_tokens, usage_cost_cents)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (uid(), company_id, agent["id"], status, started_at or now(), finished_at,
                    session_id, exit_code, in_tok, out_tok, cost_cents))
        db.commit()
        print(f"OK: heartbeat_run recorded for {agent_name} (status={status})")

    else:
        print(f"Unknown agent action: {action}")
        print("Valid actions: list, status, pause, resume, heartbeat, heartbeat-run")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# GOAL SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_goal(args):
    if not args:
        args = ["tree"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "tree":
        rows = db.execute("""SELECT g.*, a.name as owner_name,
                            (SELECT COUNT(*) FROM issues WHERE goal_id = g.id AND status NOT IN ('done','cancelled','wont_fix')) as open_issues
                            FROM goals g LEFT JOIN agents a ON g.owner_agent_id = a.id
                            WHERE g.company_id = ? ORDER BY g.level, g.title""", (company_id,)).fetchall()
        for r in rows:
            indent = {"company": "", "team": "  ", "agent": "    ", "task": "      "}.get(r["level"], "")
            status_icon = {"active": "+", "achieved": "✓", "planned": "○", "cancelled": "×"}.get(r["status"], "?")
            issues_note = f" ({r['open_issues']} open)" if r["open_issues"] > 0 else ""
            print(f"{indent}[{status_icon}] {r['title']} ({r['level']}){issues_note}")

    elif action == "create":
        if len(args) < 2:
            print("Usage: goal create <title> --level X [--parent Y]")
            return
        title = args[1]
        level = "task"
        parent_id = None
        i = 2
        while i < len(args):
            if args[i] == "--level" and i + 1 < len(args): level = args[i + 1]; i += 2
            elif args[i] == "--parent" and i + 1 < len(args):
                parent = db.execute("SELECT id FROM goals WHERE title LIKE ?", (f"%{args[i+1]}%",)).fetchone()
                if parent: parent_id = parent["id"]
                i += 2
            else: i += 1
        db.execute("INSERT INTO goals (id, company_id, title, level, status, parent_id) VALUES (?, ?, ?, ?, 'active', ?)",
                   (uid(), company_id, title, level, parent_id))
        db.commit()
        print(f"OK: Goal created: {title} ({level})")

    else:
        print(f"Unknown goal action: {action}")
        print("Valid actions: tree, create")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_approve(args):
    if not args:
        args = ["list"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "list":
        pending = db.execute("SELECT * FROM approvals WHERE company_id = ? AND status = 'pending' ORDER BY created_at", (company_id,)).fetchall()
        recent = db.execute("SELECT * FROM approvals WHERE company_id = ? AND status != 'pending' ORDER BY decided_at DESC LIMIT 5", (company_id,)).fetchall()
        print(f"\n  Pending Approvals ({len(pending)})")
        if pending:
            for p in pending:
                print(f"    [{p['id'][:8]}] {p['type']}: {p['description']} (by {p['requested_by']}, {p['created_at'][:10]})")
        else:
            print("    None")
        if recent:
            print(f"\n  Recent Decisions")
            for r in recent:
                print(f"    [{r['status'].upper()}] {r['type']}: {r['description']} — {r['decision_note'] or 'no note'}")

    elif action == "request":
        if len(args) < 2:
            print("Usage: approve request <description> --type <type>")
            return
        desc = args[1]
        atype = "strategy"
        if "--type" in args:
            idx = args.index("--type")
            if idx + 1 < len(args): atype = args[idx + 1]
        operator_name = os.environ.get("PAPERCLIP_OPERATOR_NAME", "Operator")
        db.execute("INSERT INTO approvals (id, company_id, type, description, requested_by) VALUES (?, ?, ?, ?, ?)",
                   (uid(), company_id, atype, desc, operator_name))
        db.commit()
        print(f"OK: Approval requested: [{atype}] {desc}")

    elif action in ("accept", "approve"):
        if len(args) < 2:
            print("Usage: approve accept <id_prefix> [--note 'reason']")
            return
        note = ""
        if "--note" in args:
            idx = args.index("--note")
            if idx + 1 < len(args): note = args[idx + 1]
        result = db.execute("UPDATE approvals SET status = 'approved', decided_by = 'CEO', decided_at = ?, decision_note = ? WHERE id LIKE ? AND status = 'pending'",
                           (now(), note, f"{args[1]}%"))
        db.commit()
        print(f"OK: Approved ({result.rowcount} item(s))" if result.rowcount > 0 else "NOT FOUND: No pending approval matching that ID")

    elif action == "reject":
        if len(args) < 2:
            print("Usage: approve reject <id_prefix> [--note 'reason']")
            return
        note = ""
        if "--note" in args:
            idx = args.index("--note")
            if idx + 1 < len(args): note = args[idx + 1]
        result = db.execute("UPDATE approvals SET status = 'rejected', decided_by = 'CEO', decided_at = ?, decision_note = ? WHERE id LIKE ? AND status = 'pending'",
                           (now(), note, f"{args[1]}%"))
        db.commit()
        print(f"OK: Rejected ({result.rowcount} item(s))" if result.rowcount > 0 else "NOT FOUND")

    elif action == "check":
        # Used by hooks: is there an UNUSED approved entry for this action type?
        # Approvals are one-time-use — once the decision_note contains [USED], a new approval is needed.
        if len(args) < 2:
            print("ok")
            return
        atype = args[1]
        row = db.execute("""SELECT id FROM approvals
                           WHERE type = ? AND status = 'approved' AND company_id = ?
                           AND (decision_note IS NULL OR decision_note NOT LIKE '%[USED]%')
                           ORDER BY decided_at LIMIT 1""",
                        (atype, company_id)).fetchone()
        if row:
            print("approved")
        else:
            pending = db.execute("SELECT COUNT(*) as c FROM approvals WHERE type = ? AND status = 'pending' AND company_id = ?",
                                (atype, company_id)).fetchone()
            if pending["c"] > 0:
                print("pending")
            else:
                print("none")

    elif action == "consume":
        # Mark the oldest unused approved entry as used by appending [USED] to decision_note
        if len(args) < 2:
            print("ok")
            return
        atype = args[1]
        result = db.execute("""UPDATE approvals
                              SET decision_note = COALESCE(decision_note, '') || ' [USED]'
                              WHERE id = (
                                SELECT id FROM approvals
                                WHERE type = ? AND status = 'approved' AND company_id = ?
                                AND (decision_note IS NULL OR decision_note NOT LIKE '%[USED]%')
                                ORDER BY decided_at LIMIT 1
                              )""",
                           (atype, company_id))
        db.commit()
        if result.rowcount > 0:
            print("consumed")
        else:
            print("none")

    else:
        print(f"Unknown approve action: {action}")
        print("Valid actions: list, request, accept, reject, check, consume")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_config(args):
    if not args:
        args = ["history"]
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "history":
        agent_name = args[1] if len(args) > 1 else None
        query = "SELECT r.*, a.name as agent_name FROM agent_config_revisions r JOIN agents a ON r.agent_id = a.id WHERE r.company_id = ?"
        params = [company_id]
        if agent_name:
            query += " AND (a.name = ? COLLATE NOCASE OR a.name_key = ?)"
            params.extend([agent_name, agent_name.lower()])
        query += " ORDER BY r.created_at DESC LIMIT 20"
        rows = db.execute(query, params).fetchall()
        for r in rows:
            print(f"  [{r['created_at'][:16]}] {r['agent_name']} — {r['source']} — changed: {r['changed_keys']}")

    elif action == "revision":
        if len(args) < 2:
            print("Usage: config revision <agent> --before '{}' --after '{}' --changed 'key1,key2'")
            return
        agent = resolve_agent(db, args[1])
        if not agent:
            print(f"NOT FOUND: {args[1]}")
            return
        before = after = changed = ""
        i = 2
        while i < len(args):
            if args[i] == "--before" and i + 1 < len(args): before = args[i + 1]; i += 2
            elif args[i] == "--after" and i + 1 < len(args): after = args[i + 1]; i += 2
            elif args[i] == "--changed" and i + 1 < len(args): changed = args[i + 1]; i += 2
            else: i += 1
        db.execute("""INSERT INTO agent_config_revisions (id, company_id, agent_id, before_config, after_config, changed_keys)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                   (uid(), company_id, agent["id"], before or "{}", after or "{}", changed))
        db.commit()
        print(f"OK: Config revision logged for {agent['name']}")

    else:
        print(f"Unknown config action: {action}")
        print("Valid actions: history, revision")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# BRIEFING SERVICE — One-shot CEO dashboard
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_briefing(args):
    db = get_db()
    company_id = get_company_id(db)
    # Auto-detect session from latest activity if env var not set
    session_id = os.environ.get("SESSION_ID")
    if not session_id:
        latest = db.execute("SELECT session_id FROM cost_events ORDER BY occurred_at DESC LIMIT 1").fetchone()
        session_id = latest["session_id"] if latest else "no-session"

    print("=" * 60)
    print("  CO-FOUNDER BRIEFING")
    print("=" * 60)

    # P1 Issues
    p1s = db.execute("""SELECT i.identifier, i.title, a.name as assignee, i.status
                        FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id
                        WHERE i.priority = 'P1' AND i.status NOT IN ('done','cancelled','wont_fix')
                        AND i.company_id = ?""", (company_id,)).fetchall()
    print(f"\n  URGENT (P1): {len(p1s)}")
    for p in p1s:
        print(f"    {p['identifier']} {p['title'][:40]} [{p['status']}] -> {p['assignee'] or 'unassigned'}")

    # Pending approvals
    approvals = db.execute("SELECT type, description FROM approvals WHERE status = 'pending' AND company_id = ?", (company_id,)).fetchall()
    print(f"\n  PENDING APPROVALS: {len(approvals)}")
    for a in approvals:
        print(f"    [{a['type']}] {a['description'][:50]}")

    # Budget warnings
    warnings = db.execute("""SELECT sub.name, sub.cap, sub.used FROM (
                            SELECT a.name, bp.amount as cap,
                            (SELECT COUNT(*) FROM cost_events WHERE agent_id = a.id AND session_id = ?) as used
                            FROM agents a
                            JOIN budget_policies bp ON bp.scope_id = a.id AND bp.scope_type = 'agent'
                            WHERE a.company_id = ? AND a.name_key != 'coo' AND bp.amount > 0
                            ) sub WHERE sub.used >= (sub.cap * 80 / 100)""",
                          (session_id, company_id)).fetchall()
    print(f"\n  BUDGET WARNINGS: {len(warnings)}")
    for w in warnings:
        print(f"    {w['name']}: {w['used']}/{w['cap']}")

    # Issue summary
    total = db.execute("SELECT COUNT(*) as c FROM issues WHERE company_id = ?", (company_id,)).fetchone()["c"]
    open_count = db.execute("SELECT COUNT(*) as c FROM issues WHERE status NOT IN ('done','cancelled','wont_fix') AND company_id = ?", (company_id,)).fetchone()["c"]
    in_progress = db.execute("SELECT COUNT(*) as c FROM issues WHERE status = 'in_progress' AND company_id = ?", (company_id,)).fetchone()["c"]
    in_review = db.execute("SELECT COUNT(*) as c FROM issues WHERE status = 'in_review' AND company_id = ?", (company_id,)).fetchone()["c"]
    done = db.execute("SELECT COUNT(*) as c FROM issues WHERE status = 'done' AND company_id = ?", (company_id,)).fetchone()["c"]

    print(f"\n  ISSUES: {total} total | {open_count} open | {in_progress} in progress | {in_review} in review | {done} done")

    # Stale agents (no heartbeat in 30+ min)
    stale_cutoff = (datetime.now(tz=__import__('datetime').timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = db.execute("""SELECT name, last_heartbeat_at FROM agents
                         WHERE last_heartbeat_at IS NOT NULL AND last_heartbeat_at < ?
                         AND status = 'active' AND company_id = ? AND name_key != 'coo'""",
                      (stale_cutoff, company_id)).fetchall()
    if stale:
        print(f"\n  STALE AGENTS: {len(stale)}")
        for s in stale:
            print(f"    {s['name']} — last heartbeat: {s['last_heartbeat_at'][:16]}")

    # Paused agents
    paused = db.execute("SELECT name, pause_reason FROM agents WHERE status = 'paused' AND company_id = ?", (company_id,)).fetchall()
    if paused:
        print(f"\n  PAUSED AGENTS: {len(paused)}")
        for p in paused:
            print(f"    {p['name']}: {p['pause_reason'] or 'no reason'}")

    # Goal progress
    print(f"\n  GOALS:")
    goals = db.execute("""SELECT g.title, g.status,
                         (SELECT COUNT(*) FROM issues WHERE goal_id = g.id AND status = 'done') as done_count,
                         (SELECT COUNT(*) FROM issues WHERE goal_id = g.id) as total_count
                         FROM goals g WHERE g.level = 'company' AND g.company_id = ?""", (company_id,)).fetchall()
    for g in goals:
        pct = int(g['done_count'] / g['total_count'] * 100) if g['total_count'] > 0 else 0
        bar = f"{g['done_count']}/{g['total_count']}" if g['total_count'] > 0 else "no tasks"
        print(f"    [{g['status'][:3]}] {g['title'][:40]} — {bar} ({pct}%)")

    # Session delegations
    session_count = db.execute("SELECT COUNT(*) as c FROM cost_events WHERE session_id = ?", (session_id,)).fetchone()["c"]
    print(f"\n  SESSION: {session_count}/15 delegations used")
    print("=" * 60)

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — Briefing Data Pipeline v1
# Emits structured data for the dashboard briefing template:
#   - Day context (weekday, Shabbos countdown)
#   - Trend deltas (via daily snapshot diff)
#   - Activity since last snapshot (git commits + cost_events)
#   - Money summary (parsed from financials.md)
# ═══════════════════════════════════════════════════════════════════════════════

# Briefings dir is configurable via PAPERCLIP_BRIEFINGS_DIR env var.
# Default: co-founder skill convention (briefings are co-founder owned).
# Standalone Paperclip installs should set this env var.
# WORKSPACE_ROOT: engines/paperclip/paperclip.py → engines/paperclip/ → engines/ → workspace root
WORKSPACE_ROOT = Path(__file__).parent.parent.parent

BRIEFINGS_DIR = Path(os.environ.get(
    "PAPERCLIP_BRIEFINGS_DIR",
    str(WORKSPACE_ROOT / "projects" / "co-founder" / "state" / "briefings")
))
# Financials path is configurable via PAPERCLIP_FINANCIALS_PATH env var.
# Default falls back to the co-founder skill convention so existing installs keep working;
# standalone Paperclip installs should set the env var (or get "missing" status).
FINANCIALS_PATH = Path(os.environ.get(
    "PAPERCLIP_FINANCIALS_PATH",
    str(WORKSPACE_ROOT / "projects" / "co-founder" / "financials.md")
))

def _shabbos_countdown():
    # Friday = 4 in Python (Mon=0). Sundown approx — just count days to Friday.
    today = datetime.now()
    days = (4 - today.weekday()) % 7
    if days == 0 and today.hour >= 18:
        days = 7
    return days

def _load_prior_snapshot():
    if not BRIEFINGS_DIR.exists():
        return None
    snaps = sorted(BRIEFINGS_DIR.glob("*.json"))
    if not snaps:
        return None
    try:
        return json.loads(snaps[-1].read_text())
    except Exception:
        return None

def _save_snapshot(data):
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    (BRIEFINGS_DIR / f"{today}.json").write_text(json.dumps(data, indent=2))

def _parse_financials():
    if not FINANCIALS_PATH.exists():
        return {"active_clients": 0, "raw_path": str(FINANCIALS_PATH), "status": "missing"}
    text = FINANCIALS_PATH.read_text(encoding="utf-8", errors="replace")
    # Count client rows (skip "(none yet)" placeholder)
    active = 0
    in_table = False
    for line in text.splitlines():
        if "Active Client Engagements" in line:
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if in_table and line.startswith("|") and "---" not in line and "Client" not in line:
            if "(none yet)" not in line and line.count("|") >= 3:
                active += 1
    return {"active_clients": active, "raw_path": str(FINANCIALS_PATH), "status": "ok"}

def _git_activity_since(iso_ts):
    import subprocess
    try:
        since = iso_ts or "1 day ago"
        out = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline"],
            capture_output=True, text=True, cwd=str(WORKSPACE_ROOT),
            timeout=5,
        )
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        return {"commits": len(lines), "sample": lines[:3]}
    except Exception as e:
        return {"commits": 0, "sample": [], "error": str(e)}

def cmd_dashboard(args):
    """Emit briefing data as JSON for any consumer (skill, dashboard, monitoring)."""
    db = get_db()
    company_id = get_company_id(db)

    # Core counts
    total_issues = db.execute("SELECT COUNT(*) c FROM issues WHERE company_id=?", (company_id,)).fetchone()["c"]
    open_issues = db.execute("SELECT COUNT(*) c FROM issues WHERE status NOT IN ('done','cancelled','wont_fix') AND company_id=?", (company_id,)).fetchone()["c"]
    p1 = db.execute("SELECT COUNT(*) c FROM issues WHERE priority='P1' AND status NOT IN ('done','cancelled','wont_fix') AND company_id=?", (company_id,)).fetchone()["c"]
    approvals = db.execute("SELECT COUNT(*) c FROM approvals WHERE status='pending' AND company_id=?", (company_id,)).fetchone()["c"]
    agents_active = db.execute("SELECT COUNT(*) c FROM agents WHERE status='active' AND company_id=?", (company_id,)).fetchone()["c"]

    prior = _load_prior_snapshot()
    def delta(key, cur):
        if not prior or key not in prior:
            return None
        return cur - prior[key]

    prior_ts = prior.get("timestamp") if prior else None
    activity = _git_activity_since(prior_ts)
    money = _parse_financials()

    today = datetime.now()
    data = {
        "schema_version": "1.0",
        "timestamp": now(),
        "date": today.strftime("%Y-%m-%d"),
        "weekday": today.strftime("%A"),
        "shabbos_in_days": _shabbos_countdown(),
        "issues_total": total_issues,
        "issues_open": open_issues,
        "p1": p1,
        "approvals_pending": approvals,
        "agents_active": agents_active,
        "deltas": {
            "issues_total": delta("issues_total", total_issues),
            "issues_open": delta("issues_open", open_issues),
            "p1": delta("p1", p1),
        },
        "activity_since_last": activity,
        "money": money,
    }

    print(json.dumps(data, indent=2))
    _save_snapshot(data)

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTINES — Scheduled/triggered recurring work (Source: Paperclip v2)
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_routine(args):
    """Manage routines: create, list, run, enable, disable"""
    if not args:
        print("Usage: paperclip.py routine <create|list|run|enable|disable>")
        return
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "list":
        rows = db.execute("""SELECT r.id, r.name, r.schedule, r.enabled,
                            r.assignee_agent_id, a.name as agent_name,
                            (SELECT COUNT(*) FROM routine_runs WHERE routine_id = r.id) as run_count,
                            (SELECT MAX(created_at) FROM routine_runs WHERE routine_id = r.id) as last_run
                            FROM routines r LEFT JOIN agents a ON r.assignee_agent_id = a.id
                            WHERE r.company_id = ?""", (company_id,)).fetchall()
        if not rows:
            print("No routines configured.")
            return
        print(f"{'Name':<25} {'Schedule':<20} {'Agent':<12} {'Runs':<6} {'Last Run':<20} {'Active'}")
        print("-" * 100)
        for r in rows:
            active = "YES" if r['enabled'] else "no"
            print(f"{r['name'][:24]:<25} {(r['schedule'] or 'manual'):<20} {(r['agent_name'] or 'none'):<12} {r['run_count']:<6} {(r['last_run'] or 'never')[:19]:<20} {active}")

    elif action == "create":
        if len(args) < 2:
            print("Usage: routine create <name> [--schedule '<cron>'] [--agent <name>] [--title '<issue title>'] [--priority P1|P2|P3|P4]")
            return
        name = args[1]
        schedule = None
        agent_key = None
        title = f"Routine: {name}"
        priority = "P2"
        i = 2
        while i < len(args):
            if args[i] == "--schedule" and i + 1 < len(args):
                schedule = args[i + 1]; i += 2
            elif args[i] == "--agent" and i + 1 < len(args):
                agent_key = args[i + 1]; i += 2
            elif args[i] == "--title" and i + 1 < len(args):
                title = args[i + 1]; i += 2
            elif args[i] == "--priority" and i + 1 < len(args):
                priority = args[i + 1]; i += 2
            else:
                i += 1

        agent_id = None
        if agent_key:
            row = db.execute("SELECT id FROM agents WHERE name_key = ? AND company_id = ?", (agent_key.lower(), company_id)).fetchone()
            if row:
                agent_id = row['id']

        rid = uid()
        db.execute("""INSERT INTO routines (id, company_id, name, schedule, issue_template_title,
                      issue_template_priority, assignee_agent_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                   (rid, company_id, name, schedule, title, priority, agent_id))
        db.commit()
        print(f"OK: Routine '{name}' created (id: {rid[:8]})")

    elif action == "run":
        if len(args) < 2:
            print("Usage: routine run <name>")
            return
        name = args[1]
        routine = db.execute("SELECT * FROM routines WHERE name = ? AND company_id = ?", (name, company_id)).fetchone()
        if not routine:
            print(f"Routine '{name}' not found.")
            return
        if not routine['enabled']:
            print(f"Routine '{name}' is disabled.")
            return

        # Check skip_if_active
        if routine['skip_if_active']:
            active = db.execute("""SELECT identifier FROM issues
                                  WHERE origin_kind = 'routine_execution' AND origin_id = ?
                                  AND status IN ('open', 'assigned', 'in_progress', 'in_review', 'blocked')
                                  AND company_id = ?""", (routine['id'], company_id)).fetchone()
            if active:
                run_id = uid()
                db.execute("INSERT INTO routine_runs (id, company_id, routine_id, status, skip_reason) VALUES (?, ?, ?, 'skipped', ?)",
                           (run_id, company_id, routine['id'], f"Active issue {active['identifier']} still open"))
                db.commit()
                print(f"SKIPPED: Active issue {active['identifier']} still open for this routine.")
                return

        # Create the issue
        run_id = uid()
        counter_path = Path(__file__).parent.parent.parent / "shared" / "state" / "issues" if not (Path(__file__).parent / "state" / "issues").exists() else Path(__file__).parent / "state" / "issues"
        # Use the existing issue creation logic
        max_num = db.execute("SELECT MAX(issue_number) as m FROM issues WHERE company_id = ?", (company_id,)).fetchone()["m"] or 0
        new_num = max_num + 1
        prefix = db.execute("SELECT UPPER(SUBSTR(name, 1, 3)) as p FROM companies WHERE id = ?", (company_id,)).fetchone()["p"]
        identifier = f"{prefix}-{new_num:03d}"
        issue_id = uid()

        db.execute("""INSERT INTO issues (id, company_id, issue_number, identifier, title, description,
                      priority, assignee_agent_id, origin_kind, origin_id)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'routine_execution', ?)""",
                   (issue_id, company_id, new_num, identifier,
                    routine['issue_template_title'] or f"Routine: {routine['name']}",
                    routine['issue_template_description'],
                    routine['issue_template_priority'] or 'P2',
                    routine['assignee_agent_id'],
                    routine['id']))

        db.execute("INSERT INTO routine_runs (id, company_id, routine_id, status, issue_id, started_at) VALUES (?, ?, ?, 'completed', ?, ?)",
                   (run_id, company_id, routine['id'], issue_id, now()))
        db.commit()
        print(f"OK: Routine '{name}' fired → created {identifier}")

    elif action in ("enable", "disable"):
        if len(args) < 2:
            print(f"Usage: routine {action} <name>")
            return
        val = 1 if action == "enable" else 0
        db.execute("UPDATE routines SET enabled = ?, updated_at = ? WHERE name = ? AND company_id = ?",
                   (val, now(), args[1], company_id))
        db.commit()
        print(f"OK: Routine '{args[1]}' {action}d")

    else:
        print(f"Unknown routine action: {action}")


def cmd_wakeup(args):
    """Manage wakeup requests: list, create, deliver"""
    if not args:
        print("Usage: paperclip.py wakeup <list|create|deliver>")
        return
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "list":
        rows = db.execute("""SELECT w.id, a.name as agent_name, w.reason, w.source_issue_id,
                            w.coalesced_count, w.status, w.created_at
                            FROM agent_wakeup_requests w JOIN agents a ON w.agent_id = a.id
                            WHERE w.company_id = ? ORDER BY w.created_at DESC LIMIT 20""",
                          (company_id,)).fetchall()
        if not rows:
            print("No wakeup requests.")
            return
        print(f"{'Agent':<12} {'Reason':<20} {'Count':<6} {'Status':<10} {'Created'}")
        print("-" * 80)
        for w in rows:
            print(f"{w['agent_name']:<12} {w['reason']:<20} {w['coalesced_count']:<6} {w['status']:<10} {w['created_at'][:19]}")

    elif action == "create":
        if len(args) < 3:
            print("Usage: wakeup create <agent_name> <reason> [--issue <issue_id>]")
            return
        agent_name = args[1]
        reason = args[2]
        issue_id = None
        if "--issue" in args:
            idx = args.index("--issue")
            if idx + 1 < len(args):
                issue_id = args[idx + 1]

        agent = db.execute("SELECT id FROM agents WHERE name_key = ? AND company_id = ?",
                          (agent_name.lower(), company_id)).fetchone()
        if not agent:
            print(f"Agent '{agent_name}' not found.")
            return

        # Idempotency: check if same agent+reason+issue already pending
        idem_key = f"{agent['id']}:{reason}:{issue_id or 'none'}"
        existing = db.execute("SELECT id, coalesced_count FROM agent_wakeup_requests WHERE idempotency_key = ? AND status = 'pending'",
                             (idem_key,)).fetchone()
        if existing:
            db.execute("UPDATE agent_wakeup_requests SET coalesced_count = coalesced_count + 1 WHERE id = ?",
                       (existing['id'],))
            db.commit()
            print(f"OK: Coalesced into existing wakeup (count: {existing['coalesced_count'] + 1})")
            return

        wid = uid()
        db.execute("""INSERT INTO agent_wakeup_requests (id, company_id, agent_id, reason, source_issue_id, idempotency_key)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (wid, company_id, agent['id'], reason, issue_id, idem_key))
        db.commit()
        print(f"OK: Wakeup request created for {agent_name} (reason: {reason})")

    elif action == "deliver":
        # Mark all pending wakeups as delivered
        pending = db.execute("SELECT COUNT(*) as c FROM agent_wakeup_requests WHERE status = 'pending' AND company_id = ?",
                            (company_id,)).fetchone()["c"]
        if pending == 0:
            print("No pending wakeup requests.")
            return
        db.execute("UPDATE agent_wakeup_requests SET status = 'delivered', delivered_at = ? WHERE status = 'pending' AND company_id = ?",
                   (now(), company_id))
        db.commit()
        print(f"OK: Delivered {pending} wakeup request(s)")

    else:
        print(f"Unknown wakeup action: {action}")


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRA QUERY COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_query(args):
    """Additional query commands: search, workload, progress, stale"""
    if not args:
        print("Usage: paperclip.py query <search|workload|progress|stale|monthly>")
        return
    action = args[0]
    db = get_db()
    company_id = get_company_id(db)

    if action == "search":
        if len(args) < 2:
            print("Usage: query search <keyword>")
            return
        keyword = args[1]
        rows = db.execute("""SELECT i.identifier, i.title, i.status, a.name as assignee
                            FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id
                            WHERE (i.title LIKE ? OR i.description LIKE ?) AND i.company_id = ?""",
                         (f"%{keyword}%", f"%{keyword}%", company_id)).fetchall()
        print(f"  Search results for '{keyword}': {len(rows)}")
        for r in rows:
            print(f"    {r['identifier']} {r['title'][:40]} [{r['status']}] -> {r['assignee'] or 'none'}")

    elif action == "workload":
        rows = db.execute("""SELECT a.name, COUNT(i.id) as issue_count,
                            SUM(CASE WHEN i.status = 'in_progress' THEN 1 ELSE 0 END) as active,
                            SUM(CASE WHEN i.status IN ('open','assigned') THEN 1 ELSE 0 END) as queued
                            FROM agents a LEFT JOIN issues i ON i.assignee_agent_id = a.id AND i.status NOT IN ('done','cancelled','wont_fix')
                            WHERE a.company_id = ? AND a.name_key != 'coo'
                            GROUP BY a.id ORDER BY issue_count DESC""", (company_id,)).fetchall()
        print(f"\n  {'Agent':<12} {'Total':<8} {'Active':<8} {'Queued':<8}")
        print(f"  {'-'*36}")
        for r in rows:
            print(f"  {r['name']:<12} {r['issue_count']:<8} {r['active'] or 0:<8} {r['queued'] or 0:<8}")

    elif action == "progress":
        rows = db.execute("""SELECT g.title,
                            (SELECT COUNT(*) FROM issues WHERE goal_id = g.id) as total,
                            (SELECT COUNT(*) FROM issues WHERE goal_id = g.id AND status = 'done') as done,
                            (SELECT COUNT(*) FROM issues WHERE goal_id = g.id AND status NOT IN ('done','cancelled','wont_fix')) as open_count
                            FROM goals g WHERE g.level = 'company' AND g.company_id = ?""", (company_id,)).fetchall()
        for r in rows:
            pct = int(r['done'] / r['total'] * 100) if r['total'] > 0 else 0
            bar_full = int(pct / 5)
            bar = '#' * bar_full + '.' * (20 - bar_full)
            print(f"  {r['title'][:35]:<35} [{bar}] {pct}% ({r['done']}/{r['total']})")

    elif action == "stale":
        cutoff = (datetime.now(tz=__import__('datetime').timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agents = db.execute("""SELECT name, last_heartbeat_at FROM agents
                              WHERE last_heartbeat_at IS NOT NULL AND last_heartbeat_at < ?
                              AND status = 'active' AND company_id = ?""",
                           (cutoff, company_id)).fetchall()
        issues = db.execute("""SELECT i.identifier, i.title, a.name as assignee, i.updated_at
                              FROM issues i LEFT JOIN agents a ON i.assignee_agent_id = a.id
                              WHERE i.status = 'in_progress' AND i.updated_at < ? AND i.company_id = ?""",
                           (cutoff, company_id)).fetchall()
        print(f"  Stale agents (no heartbeat >30min): {len(agents)}")
        for a in agents:
            print(f"    {a['name']} — last: {a['last_heartbeat_at'][:16]}")
        print(f"  Stale issues (in_progress >30min): {len(issues)}")
        for i in issues:
            print(f"    {i['identifier']} {i['title'][:30]} -> {i['assignee'] or 'none'}")

    elif action == "monthly":
        rows = db.execute("""SELECT a.name,
                            COUNT(ce.id) as delegations,
                            SUM(ce.input_tokens) as total_in,
                            SUM(ce.output_tokens) as total_out,
                            SUM(ce.cost_cents) as total_cost
                            FROM cost_events ce
                            JOIN agents a ON ce.agent_id = a.id
                            WHERE ce.occurred_at >= date('now', '-30 days')
                            GROUP BY a.id ORDER BY delegations DESC""", ()).fetchall()
        print(f"\n  {'Agent':<12} {'Delegations':<14} {'Tokens In':<12} {'Tokens Out':<12} {'Cost':<10}")
        print(f"  {'-'*58}")
        for r in rows:
            cost_str = f"${(r['total_cost'] or 0)/100:.2f}"
            print(f"  {r['name']:<12} {r['delegations']:<14} {r['total_in'] or 0:<12} {r['total_out'] or 0:<12} {cost_str:<10}")
        if not rows:
            print("  No cost data yet. Data accumulates as agents are delegated to.")

    else:
        print(f"Unknown query action: {action}")
        print("Valid actions: search, workload, progress, stale, monthly")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: paperclip.py <service> <action> [args]")
        print("Services: init, briefing, dashboard, issue, budget, agent, goal, approve, config, query, routine, wakeup")
        sys.exit(1)

    service = sys.argv[1]
    args = sys.argv[2:]

    try:
        if service == "init":
            cmd_init()
        elif service == "briefing":
            cmd_briefing(args)
        elif service == "dashboard":
            cmd_dashboard(args)
        elif service == "issue":
            cmd_issue(args)
        elif service == "budget":
            cmd_budget(args)
        elif service == "agent":
            cmd_agent(args)
        elif service == "goal":
            cmd_goal(args)
        elif service == "approve":
            cmd_approve(args)
        elif service == "config":
            cmd_config(args)
        elif service == "query":
            cmd_query(args)
        elif service == "routine":
            cmd_routine(args)
        elif service == "wakeup":
            cmd_wakeup(args)
        else:
            print(f"Unknown service: {service}")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
