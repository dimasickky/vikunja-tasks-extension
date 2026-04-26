# Changelog

## [1.0.2] — 2026-04-26

Pin bump only: `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Also corrects a pre-existing version drift between `app.py` (which still read `1.0.0`) and `imperal.json` (which read `1.0.1`); both now read `1.0.2`.

### Why

`imperal-sdk` 2.0.1 supersedes the rolled-back 2.0.0 with the v1.6.2 contract restored plus two kernel-internal ICNLI Action Authority hotfixes (`chat/guards.py` destructive `BLOCK` → `ESCALATE`, `core/intent.action_plan.args` JSON-encoded string for OpenAI strict mode). The SDK API surface remains identical to 1.6.2. Per Valentin's release note: *"v1.6.2 extensions upgrade by pin bump only."*

### Changed

- **`requirements.txt`** — `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Equality pin retained as the workspace invariant.
- **`app.py`** — `Extension("tasks", version="1.0.0")` → `version="1.0.2"`. Brings the runtime-reported version in line with `imperal.json`.

### Not changed

- All extension logic — handlers, panels, system_prompt, manifest tool definitions — identical to 1.0.1.

## [1.0.1] — 2026-04-25

Pin `imperal-sdk==1.6.2` after rolling back the v2.0.0 / SDK v2.0 / Webbee Single Voice rebuild. Code unchanged from 1.0.0; only the SDK constraint moves from a git-URL `v1.5.16` pin to the PyPI `==1.6.2` pin matching the production runtime. The v2.0 work is preserved on the `sdk-v2-migration` branch (and tagged `pre-1.6.2-rebuild-2026-04-25` on main pre-reset).

### Changed

- **`requirements.txt`** — `imperal-sdk @ git+https://github.com/imperalcloud/imperal-sdk.git@v1.5.16` → `imperal-sdk==1.6.2`. Hard PyPI pin is required because PyPI `imperal-sdk==2.0.0` is immutable and resolver picks it without an explicit constraint.

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
