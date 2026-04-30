# Changelog

## [2.0.11] — 2026-04-30

### Fixed

- **`panels_board.py`** — lazy import of `render_task_detail` moved inside the function body. Module-level `from panels_task import render_task_detail` caused `NameError: name 'ext' is not defined` in the Developer Portal validator because `panels_task.py` was loaded before `ext` was initialized in the validator's import context.

---

## [2.0.10] — 2026-04-30

### Fixed

- **Architecture** — merged `__panel__task` (second `slot="center"` panel) into `__panel__board`. Platform supports one center panel per extension; having two caused the board to open in the right chat sidebar instead of the center column.
- **`panels_task.py`** — removed `@ext.panel` decorator, renamed `task_detail` → `render_task_detail` (plain async function called by `panels_board`).
- **`panels_board.py`** — added `task_id`, `mode` routing; all `ui.Call("__panel__task", ...)` → `ui.Call("__panel__board", ...)`.
- **`panels.py`** — `ui.Call("__panel__task", mode="new")` → `ui.Call("__panel__board", mode="new")`.
- **`imperal.json`** — removed `__panel__task` tool entry; updated `__panel__board` description.

---

## [2.0.9] — 2026-04-30

### Fixed

- **`panels_board.py`** — `_task_card` returns `ui.ListItem` instead of `ui.Card`. SDK pattern: inside `ui.List`, items must be `ListItem` nodes, not nested `Card` nodes. Previous `Card→List→Card` nesting caused task items to be invisible (only bucket title was shown). Now each task renders as a `ListItem` with `title`, `subtitle` (due date + priority badge), icon (`Circle`/`CheckCircle2`), and `on_click` to open task detail.
- **`panels_board.py`** — Kanban columns Stack: `wrap=False` → `wrap=True` so columns wrap to next row in narrow panels instead of overflowing.

---

## [2.0.8] — 2026-04-30

### Added

- **`handlers_structure.py`** — new `list_projects` chat function. Returns all active (non-archived) projects with `project_id` + `title`. Exposes `api_get` import that was missing from the module (import added: `api_get`). This was the missing building block that forced the LLM to hallucinate project lookups as SQL subqueries.

### Fixed

- **`system_prompt.txt`** — added **Project lookup rule**: LLM must call `list_projects` first when user asks for tasks by project name, then pass the numeric `project_id` to `filter_tasks`. Added **Vikunja filter syntax** section explicitly listing valid operators/fields/time helpers and forbidding SQL-style subqueries (`select`, `from`, `where` — these produce errors). Fixes hallucination observed on prod: `project_id = '(select id from projects where title ~ '%webhostmost tasks%')'`.

---

## [2.0.7] — 2026-04-30

### Fixed

- **`panels.py` + `panels_board.py` + `panels_task.py`** — `ui.Stack(direction="horizontal")` → `ui.Stack(direction="h")` and the same for `"vertical"` → `"v"` across 11 occurrences. SDK contract (`imperal_sdk/ui/layout.py:Stack`) accepts `direction` ∈ `{"h", "v"}` only — anything else falls back to the default `"v"`. Result before this fix: every "row of buttons / row of bucket columns / row of action chips" rendered as a vertical stack instead. The most visible casualty was `panels_board._render_project_board` — Kanban columns piled vertically one under another instead of forming the actual board ("уебищный формат" To-Do (12) / Doing (0) / — / Done (4) на проде).

---

## [2.0.6] — 2026-04-30

### Fixed

- **All `handlers_*.py`** — `ActionResult.success(message=...)` → `ActionResult.success(summary=...)` in 17 places across `handlers_search.py`, `handlers_crud.py`, `handlers_structure.py`, `handlers_collab.py`, `handlers_organize.py`. The SDK's `ActionResult.success` signature is `(data, summary, *, ui=None, refresh_panels=None)` — `message` was never a valid kwarg, and SDK 3.0.0+ enforces strict kwargs (frozen Pydantic v2 models with `extra="forbid"`), so every chat-side call into list_my_tasks / filter_tasks / create_task / update_task / complete_task / delete_task / project CRUD / label CRUD / comment CRUD / assignee + label attach/detach died with `TypeError: ActionResult.success() got an unexpected keyword argument 'message'`. `connect_vikunja*` and `disconnect_vikunja` were already correct (used `summary=`); only the post-connect handlers were broken.

---

## [2.0.5] — 2026-04-30

### Fixed

- **`panels_board.py`** — switch project Kanban fetch from `/v1/projects/{pid}/views/{vid}/buckets` to `/v1/projects/{pid}/views/{vid}/tasks`. Vikunja v0.21+ split these: `/buckets` returns columns with `tasks=null`, while `/tasks` returns the same columns shape but with each bucket's `tasks` field populated. Result before this fix: clicking on a project showed the Kanban frame with column titles, but every column was empty even when tasks existed.

### Backend (the backend service, deployed separately on the backend host)

- **`routes_tasks.py`** — `/v1/tasks/all` now forwards to Vikunja `/api/v1/tasks` (not `/api/v1/tasks/all`, which was removed in Vikunja v0.21+ and returned `400 Invalid model`). Bridge route name unchanged for extension compatibility.
- **`routes_projects.py`** — added `GET /v1/projects/{pid}/views/{vid}/tasks` route, forwards to Vikunja's `/api/v1/projects/{pid}/views/{vid}/tasks`. Companion to the `panels_board.py` switch above.

---

## [2.0.4] — 2026-04-30

### Fixed

- **`panels.py` + `panels_task.py`** — every `ui.ListItem(...)` now passes the required `id` positional. `ui.ListItem` from `imperal_sdk.ui.data` has `id: str` as the first required arg; calling it without `id` raised `TypeError: ListItem() missing 1 required positional argument: 'id'` and broke the entire `__panel__sidebar` render path right after a successful Vikunja connect — visible in the worker as an infinite spinner on the left sidebar. IDs added: `smart_today` / `smart_upcoming` / `smart_overdue` for the smart-views card, `project_{pid}` for projects, `comment_{id}` for task comments.

### Backend (the backend service, deployed separately on the backend host)

- **`routes_connection.py:_mint_pat`** — payload now includes `expires_at` (now + 10 years, RFC3339). Vikunja v0.20+ requires this field on PAT creation; without it Vikunja returns `412 {"code":2002,"message":"Invalid Data","invalid_fields":["expires_at: non zero value required"]}`, which surfaced to users as `Vikunja PAT mint failed (HTTP 412)`.
- **`routes_connection.py:connect`** — post-mint user lookup (`_fetch_self`) now uses the JWT we already obtained from `/api/v1/login` instead of the freshly minted PAT. `/api/v1/user` is not in any PAT permission scope on Vikunja, so probing it with the PAT always returned 401 ("The token is not accepted by Vikunja"). The PAT itself is fine; the validation step was the bug.

---

## [2.0.3] — 2026-04-30

### Fixed

- **`panels.py`** — wrap the connect form inputs in `ui.Form(action=..., submit_label=...)` so that the URL / username / password / PAT fields actually get bundled into the chat-function call. Before this, `ui.Input` nodes were siblings of a `ui.Button(on_click=ui.Call("connect_vikunja"))` — `ui.Input` only attaches `param_name` for *Form* collection (per `imperal_sdk.ui.input_components.Form` docstring: "Form container — collects child input values and submits as one action"); without a Form parent the Button submitted with empty params, so the handler always saw `base_url=""` and returned `Vikunja URL is required`. The view-toggle button ("I have a token" / "Use username + password") stays outside the Form because it's a panel re-render, not a submit. Same wiring will need to be applied to any other panel that uses Inputs as a multi-field form (none today).

---

## [2.0.2] — 2026-04-29

### Fixed

- **`panels.py`** — drop `confirm=` kwarg from the Disconnect `ui.Button`. The parameter was never part of `imperal_sdk.ui.Button` (silently ignored on prod since 2.0.0), and the new V14 validator hard-fails on it. Disconnect now fires immediately on click — same effective behavior as today, just no fake-confirmation string in the props payload. Followup: wire a real `ui.Dialog`-based confirm flow once the frontend Dialog rendering contract has a reference implementation in another extension.

---

## [2.0.1] — 2026-04-29

### Changed

- **`requirements.txt`** — bump `imperal-sdk==3.0.0` → `==3.4.1`. Pulls in the LLM-FU-1/FU-2 stack (gpt-5 / o-series `max_completion_tokens` rename + `temperature` drop) so chains routed through reasoning models stop falling over to `anthropic/haiku`.
- **`app.py`** — `ChatExtension(model="claude-haiku-4-5-20251001")` removed (deprecated since SDK 3.3.0, hard-error in SDK 4.0). LLM model resolution now flows through kernel ctx-injection (`ctx._llm_configs`). Mirrors the cleanup done in sql-db 1.4.2 and notes 2.5.2.

### Compatibility

- 3.4.0 panel-slot whitelist already met — `panels.py` `slot="left"`, `panels_board.py` and `panels_task.py` `slot="center"`.

---

## [2.0.0] — 2026-04-27

**Breaking — Bring-Your-Own Vikunja.** Each user now connects their own Vikunja instance via the tasks panel; their data lives in their Vikunja, not in our shared instance. The shared `md-node1` Vikunja becomes an internal/dogfood-only tool. The `the backend service` backend was refactored from a shared-instance broker into a per-user connection manager (encrypted PAT storage + per-call resolve).

### Why

The shared-instance model meant we held tasks data for every user, which is at odds with our positioning ("Webbee speaks to your tools — your data stays with you"). BYO is the federal-grade posture for an integrations-layer product: encrypted PAT at rest in `the backend service`, plaintext in worker RAM only for the single HTTP request that needs it, revokable from the user's own Vikunja UI at any time. It also unblocks the multi-provider future (Linear, Trello, Asana drop into bridge alongside the Vikunja adapter without touching the extension).

### Backend (the backend service v1.0.0, the backend host)

- **New endpoints** — `POST /v1/connect` (login → mint PAT → encrypt → store), `POST /v1/connect/with-pat` (advanced: paste an existing token), `DELETE /v1/connect` (revoke remote + delete local row), `GET /v1/connection` (status, never echoes the PAT).
- **New table** — `vikunja_connections`: `imperal_id` PK + `base_url` + `username` + `vikunja_user_id` (in their instance) + `pat_encrypted` (Fernet ciphertext) + `pat_token_id` (for revoke) + `agency_id` + timestamps. Migration `001_byo_connections.sql`.
- **New module** — `pat.py` (Fernet encrypt/decrypt). Key in `/home/the backend service/.env` as `the encryption key`. Plaintext PAT only ever lives in stack-local handler frames.
- **`vikunja_client.call_as_user`** — per-call: load connection → decrypt PAT → call user's `base_url` with `Authorization: Bearer {pat}`. No more shared-instance JWT minting.
- **Deprecated** — `routes_provision.py` (shared-instance auto-provisioning) is no longer mounted in `app.py`. File kept for 30-day decom window.
- **Bridge bumped 0.4.0 → 1.0.0** to mark the BYO contract.

### Extension (this commit)

- **New** — `handlers_connection.py` with chat functions `connect_vikunja`, `connect_vikunja_with_pat`, `disconnect_vikunja`, `get_connection_status`.
- **`panels.py`** rewritten — connect-first UX: empty/connect/error/connected/broken states. Empty state shows the connect form + "What is Vikunja?" help (vikunja.io self-host link, try.vikunja.io hosted link). Connected state shows smart views + projects + footer with disconnect button.
- **`panels_board.py`, `panels_task.py`, `skeleton.py`** — gracefully handle the bridge's HTTP 412 "no connection" response: render a "Connect your Vikunja in the sidebar" empty state instead of crashing or returning zero counts.
- **`app.py`** — dropped `on_install` (auto-provisioning) and `on_uninstall` (cascade delete). Added `is_no_connection_error(resp)` helper for 412 detection. Added `require_imperal_id(ctx)` fail-loud helper.
- **All handler files (`handlers_crud/_organize/_search/_structure/_collab.py`)** — Russian `ActionResult.error` strings flipped to English (workspace UI policy 2026-04-27). New `_bridge_error_msg(resp, default_prefix)` helper surfaces the bridge's 412 "Connect your Vikunja first" specifically rather than a generic CRUD error.
- **`system_prompt.txt`** rewritten with BYO context — "if no connection, ask user to connect via the panel; never request password in chat".
- **`imperal.json`** — version 2.0.0, top-level tool description mentions BYO, `signals` add `connection.created`/`connection.deleted`.
- **`main.py`** — purge list updated for `handlers_connection`.

### Removed

- Shared-instance auto-provisioning. `imperal_id → vikunja_user_id` mapping (`vikunja_accounts` table) is no longer the routing source. The legacy table stays in the DB schema for the 30-day decom window; new code path doesn't read or write it.
- `on_install` / `on_uninstall` lifecycle hooks. There's nothing to provision (each user connects on demand) and nothing to cascade-delete (their data lives in their Vikunja).

### Operational notes

- **Required env on the backend host** — `the encryption key` in `/home/the backend service/.env`. Generate once via `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Bridge will refuse to start (or the first /v1/connect will fail loudly) without it.
- **Migration** — apply `001_byo_connections.sql` before restarting bridge. Existing `vikunja_accounts` data is left untouched.
- **Bridge restart** is required to pick up the new code. Old code keeps running on shared instance until restart.
- **Existing prod users on shared instance** — there is no automatic data migration. Provide an export tool / amnesty period before decommissioning the shared instance.

---

## [1.1.0] — 2026-04-27

SDK migration: `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0` (Identity Contract Unification, W1).

### Why

SDK 3.0.0 deletes `imperal_sdk.auth.user.User`, makes `User`/`UserContext` frozen Pydantic v2 models with `extra="forbid"`, and renames `.id` → `.imperal_id` on user objects. `ctx.user.id` raises `AttributeError` on 3.x with no alias. Production worker venv was upgraded to 3.0.0 — any 2.x-pinned extension breaks on identity reads.

### Changed

- **`app.py`** — `_imperal_id(ctx)` reads `ctx.user.imperal_id` instead of `ctx.user.id`.
- **`requirements.txt`** — `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0`. Equality pin retained as the workspace invariant.

### Not changed

- All other Python source, manifest, system_prompt, panels, handlers — byte-for-byte identical to 1.0.2.

---

## [1.0.2] — 2026-04-26

Pin bump only: `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Also corrects a pre-existing version drift between `app.py` (which still read `1.0.0`) and `imperal.json` (which read `1.0.1`); both now read `1.0.2`.

### Why

`imperal-sdk` 2.0.1 supersedes the rolled-back 2.0.0 with the v1.6.2 contract restored plus two kernel-internal ICNLI Action Authority hotfixes (`chat/guards.py` destructive `BLOCK` → `ESCALATE`, `core/intent.action_plan.args` JSON-encoded string for OpenAI strict mode). The SDK API surface remains identical to 1.6.2. Per the team's release note: *"v1.6.2 extensions upgrade by pin bump only."*

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
