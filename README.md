# Paperclip — SQLite Control Plane Engine

A lightweight, SQLite-backed control plane for managing autonomous agent operations. Tracks issues, budgets, agents, goals, approvals, and routines through a single Python CLI.

Ported from [paperclipai/paperclip](https://github.com/paperclipai/paperclip) (Node.js + PostgreSQL) to Python + SQLite for zero-dependency local use.

## Quick Start

```bash
# Initialize the database
python paperclip.py init

# Create an issue
python paperclip.py issue create "Build the homepage" --priority high

# Check the briefing
python paperclip.py briefing

# Get dashboard data (JSON)
python paperclip.py dashboard

# Check budget status
python paperclip.py budget status
```

## Services

| Service | Commands | Purpose |
|---|---|---|
| `init` | `init` | Create database + seed initial data |
| `briefing` | `briefing` | Human-readable status report |
| `dashboard` | `dashboard` | JSON data for briefing consumers (schema v1.0) |
| `issue` | `create`, `list`, `update`, `kanban`, `show` | Task management with status workflow |
| `budget` | `status`, `check <agent>`, `reset` | Per-agent budget caps with auto-pause |
| `agent` | `list`, `status <name>`, `pause`, `resume` | Agent lifecycle management |
| `goal` | `tree`, `create`, `link` | Goal hierarchy with issue linkage |
| `approve` | `list`, `request`, `accept`, `reject`, `check`, `consume` | Approval workflow with consume markers |
| `config` | `get`, `set` | Key-value configuration |
| `query` | `search`, `workload`, `progress`, `stale`, `monthly` | Advanced queries |

## Configuration

All paths are configurable via environment variables:

| Env var | Default | Purpose |
|---|---|---|
| `PAPERCLIP_DB` | `state/paperclip.db` (next to this script) | Database location |
| `PAPERCLIP_OPERATOR_NAME` | `Operator` | System operator agent display name |
| `PAPERCLIP_OPERATOR_KEY` | `operator` | System operator agent key |
| `PAPERCLIP_OPERATOR_TITLE` | `Operator` | System operator title |
| `PAPERCLIP_OPERATOR_DEPT` | `Executive` | System operator department |
| `PAPERCLIP_FINANCIALS_PATH` | `projects/co-founder/financials.md` | Path to financials markdown |
| `PAPERCLIP_BRIEFINGS_DIR` | `projects/co-founder/state/briefings` | Directory for daily snapshots |

## Dashboard JSON Schema (v1.0)

The `dashboard` command emits JSON conforming to `shared/contracts/briefing-provider-v1.md`. Any consumer can read this output without knowing it comes from Paperclip.

## Dependencies

- Python 3.10+
- SQLite3 (built into Python)
- No external packages required

## File structure

```
engines/paperclip/
├── paperclip.py     # Main CLI (all services)
├── schema.sql       # SQLite schema
├── README.md        # This file
├── state/
│   └── paperclip.db # The database
└── hooks/           # Paperclip-owned hooks (to be populated)
```

## Origin

Faithfully ports Paperclip's PostgreSQL backend patterns to SQLite:
- Goal ancestry chain
- Atomic task checkout
- Budget enforcement with auto-pause
- Heartbeat tracking
- Org chart with reports_to
- Approval workflow with consume markers
- Config versioning

See `shared/contracts/briefing-provider-v1.md` for the consumer contract.
