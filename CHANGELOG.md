# Changelog

## [2.0.0] — 2026-04-24

**BREAKING · SDK v2.0.0 / Webbee Single Voice migration.**

Full rebuild on the v2.0 class-based tool surface. No ChatExtension, no
per-extension system prompt — Webbee Narrator composes all user-facing
prose kernel-side from typed output schemas. All 25 business operations
preserved; wire contract with vikunja-bridge (api-server:8102) unchanged.

### Added
- **`schemas.py`** — 25 Pydantic output schemas, one per tool. Every
  schema carries `ok: bool = True` + `error: str | None = None` base
  plus domain fields. Errors flow through the schema instead of
  raising, so the Narrator composes a single response across success
  and failure branches.
- **`tools.py` · `TasksExtension(Extension)`** — class-based tool host
  with 25 `@sdk_ext.tool` methods. Direct-arg signatures (no Pydantic
  params wrapper), explicit `ctx` after `self`, typed returns.
- **`cost_credits=1`** on destructive tools (`delete_task`,
  `delete_project`, `delete_label`) — triggers the pre-ACK confirmation
  gate regardless of user's default confirmation setting.
- **`@ext.skeleton("tasks", alert=True, ttl=300)`** — modernised from
  raw `@ext.tool("skeleton_refresh_tasks")` to the v1.6 convention-
  based decorator. Kernel auto-derives the section from the decorator.

### Removed
- **`ChatExtension`** + `tool_tasks_chat` entry orchestrator — v2 does
  not run per-extension LLM loops.
- **`_system_prompt` + `system_prompt.txt`** (I-LOADER-REJECT-SYSTEM-PROMPT).
- **`@chat.function` + `ActionResult.success/.error`** envelope — every
  handler replaced by `@sdk_ext.tool` with typed output_schema.
- **`action_type="read|write|destructive"`** kwarg — coarse signal
  moved to the Navigation classifier; destructive gating now via
  `cost_credits`.
- **`event="task.created" / "project.created" / etc.`** kwarg — event
  publishing is kernel-side in v2; extensions only return data.
- **`handlers_crud.py`, `handlers_organize.py`, `handlers_structure.py`,
  `handlers_search.py`, `handlers_collab.py`** — collapsed into
  `tools.py` + `schemas.py`.

### Changed
- **`capabilities`** — was `[]`, now explicit `["tasks:read", "tasks:write"]`
  at construction time (avoids the loader `["*"]` wildcard fallback).
- **Scope naming** — `tasks.read` → `tasks:read` (colon canonical),
  applied across tools, manifest, and skeleton.
- **`imperal.json`** — `sdk_version: "2.0.0"`, legacy
  `tool_tasks_chat` and broadcast `signals[]` list removed; the
  declarative alert flag on the `tasks` skeleton section is now
  authoritative.
- **`requirements.txt`** — `imperal-sdk>=2.0.0,<3.0.0`.

### Preserved
- `panels.py` (sidebar / left), `panels_board.py` (board / center),
  `panels_task.py` (task detail / center) — `@ext.panel` decorators
  unchanged, import path from `app` preserved.
- vikunja-bridge wire contract (paths, `imperal_id` in body for
  mutations / query params for reads, response shapes).
- `on_install` provisioning + `on_uninstall` cascade delete — same
  `/v1/provision` and `/v1/account` bridge calls.

### Migration
Developer Portal redeploy from `sdk-v2-migration` branch. On-install
provisioning is idempotent so existing users keep their Vikunja UID
across the redeploy. Rollback: checkout tag `v1.0.0` + reinstall SDK
`imperal-sdk==1.6.2` in the worker venv.

---

## [Unreleased]

### Added
- Extension scaffold (main.py, app.py, imperal.json, requirements.txt).
- Bridge HTTP client via `VIKUNJA_BRIDGE_URL` + `VIKUNJA_BRIDGE_KEY` env.
- `@ext.on_install` / `@ext.on_uninstall` — auto-provision + cascade delete via bridge.
- Health check through bridge `/health`.
- System prompt guiding LLM tool selection.

## [1.0.0] — TBD

Initial Marketplace release:
- 20 deterministic chat functions + 20 `@ext.panel` FREE duplicates.
- 5 AI-powered functions (breakdown, plan_my_day, estimate_duration, search_tasks, summarize_project).
- Skeleton tools (refresh_tasks, alert_tasks).
- 4 panel surfaces (sidebar, board, task detail, list view).
- DUI Kanban board with 4 view kinds (Kanban / List / Calendar / Gantt).
- Automation signals (21 events: task.*, project.*, label.*).
