# Changelog

## [3.1.0] — 2026-05-04

### SDK 4.1.0 federal compliance pass

- **`requirements.txt`**: pin bumped `imperal-sdk==4.0.1` → `imperal-sdk==4.1.0`. Worker venv уже на 4.1.0 (last-install-wins from sibling extensions); now declared explicitly. Restores hard-equality pin invariant.
- **`app.py`**: добавлен публичный `NoParams(BaseModel)` для no-arg @chat.function handlers (V17 compliance). Унифицирован с тремя ранее раздельными `_NoParams` в `handlers_search.py`, `handlers_structure.py`, `handlers_connection.py` — теперь один класс на module scope в `app.py`, импортируемый везде.
- **`app.py`**: `_imperal_id(ctx)` → `imperal_id_of(ctx)` — public API, без underscore-prefix (cross-module use). Обновлены импорты в `handlers_crud.py` и `skeleton.py`.
- **`app.py`** — `tool_tasks_chat` ChatExtension wrapper: description дополнен инструкцией «pass user message verbatim as `message`» согласно federal Runtime Invariant **I-CHAT-FUNCTION-VERBATIM-PARAMS** (2026-05-02).
- **`skeleton.py`** — `skeleton_refresh_tasks(ctx, **_)` → `(ctx)` и `skeleton_alert_tasks(ctx, old, new, **kwargs)` → `(ctx, old, new)`. Универсальный `**kwargs`-sink убран — federal V22 lifecycle сигнатуры строго типизированы (после kernel-side фикса I-EXT-SYSTEM-TASK-NO-MESSAGE-KWARG защитный sink не нужен).

### Improved

- **`handlers_organize.py`**: descriptions для `assign_task`, `unassign_task`, `add_label`, `remove_label`, `set_due_date`, `set_priority`, `move_to_project`, `move_to_bucket` дополнены — явно указано, что все ID являются integer'ами и где их брать (через `list_buckets`/`list_projects`/etc.). Pydantic `Field(description=...)` для каждого ID-параметра тоже расширен. Закрывает класс ошибок «LLM передал UUID/имя вместо integer ID».
- **`system_prompt.txt`**: добавлена секция `## ID conventions (CRITICAL — read before any tool call)` — строгое правило «все Vikunja ID = positive integers, никогда не UUID/name/slug». Перечислены все ID-поля (task_id, parent_task_id, project_id, bucket_id, label_id, comment_id, assignee_vikunja_user_id, vikunja_user_id) и стандартный flow «list_* → integer ID → write call».

### Cleanup

- Удалены dead imports `is_no_connection_error` (`handlers_organize.py`, `handlers_collab.py`, `handlers_search.py`, `handlers_structure.py` — нигде не использовался) и `Optional` (`handlers_organize.py` — нигде не использовался).
- Удалены три Nextcloud conflicted-copy файла из репо: `handlers_collab (conflicted copy 2026-05-04 013552).py`, `handlers_crud (conflicted copy 2026-05-03 210133).py`, `panels_editor (conflicted copy 2026-05-03 213503).py`. Добавлен gitignore-паттерн `* (conflicted copy *)*`.

---

## [3.0.1] — 2026-05-04

### Added

- **`handlers_collab.py` — `update_comment`**: новый `@chat.function` для редактирования текста существующего комментария (`action_type="write"`). Вызывает `POST /v1/tasks/{task_id}/comments/{comment_id}` на bridge.
- **`handlers_collab.py` — `delete_comment`**: новый `@chat.function` для удаления комментария (`action_type="destructive"`). Вызывает `DELETE /v1/tasks/{task_id}/comments/{comment_id}` на bridge.

### Fixed

- **`panels_task.py` — subtask actions**: выполненные subtask'и теперь показывают кнопку Delete (раньше `actions=[]` скрывал её для done-задач). Complete скрывается только для выполненных.
- **`panels_task.py` — comment actions**: каждый комментарий теперь имеет кнопку Delete с подтверждением (`ui.Call("delete_comment", ...)`).

---

## [2.0.20] — 2026-04-30

### Fixed / Improved

- **`handlers_structure.py` — `list_buckets`**: now returns tasks embedded per bucket (already available from the `/tasks` bridge endpoint — was being stripped before). Response shape: `{buckets: [{bucket_id, title, limit, task_count, tasks: [{task_id, title, done, priority, due_date}]}]}`. LLM can answer "what's in bucket X" from a single `list_buckets` call without chaining `filter_tasks`.
- **`system_prompt.txt`**: updated bucket rule — LLM now knows `list_buckets` returns tasks and must NOT use `filter_tasks` to filter by bucket (Vikunja filter syntax does not support `bucket_id`). Added explicit `bucket_id` NOT-a-filter-field note to the filter fields list.
- **`list_buckets` function description**: updated to reflect that it returns tasks per bucket.

---

## [2.0.18] — 2026-04-30

### Fixed

- **`handlers_structure.py` + `panels_task.py`** — `list_buckets` chat function and bucket selector in the create-task form both used the `/buckets` Vikunja endpoint, which requires a PAT scope not included in the PAT minted by the standard connect flow. Both now use the `/tasks` endpoint (returns buckets with embedded tasks under the tasks PAT scope) and strip out the task lists, keeping only bucket id/title/limit. Fixes "No Vikunja connected" error when the user asks about buckets in chat, and restores the bucket dropdown in the create-task form.
- **`panels_editor.py`** — task cards reverted from nested Stack+Button layout (introduced in 2.0.16) back to `ui.ListItem`. The nested horizontal Stack with a circle button caused text overlap in kanban columns. The complete action remains accessible in the task detail view.
- **`imperal.json`** — version synced from stale 2.0.15 to 2.0.18.

---

## [2.0.14] — 2026-04-30

### Fixed

- **`panels.py` + `panels_editor.py` + `panels_task.py`** — every `ui.Call("__panel__editor", ...)` now passes a `note_id` kwarg. Frontend `isCenterOverlay()` requires both `pid==='editor'` **and** `!!p.note_id` to route the panel into the center column; without `note_id` the panel rendered in the chat/right area instead. Mapping: board views → `note_id="board"`, project board view → `note_id=str(project_id)`, task detail → `note_id=str(tid)`, new task form → `note_id="new"`. Handler signature accepts `note_id` via `**kwargs` and discards it (it's a routing hint, not domain data). Closes the last gap in the center-slot rollout that 2.0.10–2.0.13 chipped away at.

---

## [2.0.13] — 2026-04-30

### Fixed

- **`panels.py`** — added `auto_action = ui.Call("__panel__editor")` to the sidebar panel so the center slot is claimed immediately when the sidebar loads (when no project is active). Without `auto_action` the first `ui.Call("__panel__editor")` from a sidebar click opened in the chat/right area instead of the center column. Mirrors the notes sidebar pattern (notes uses the same `auto_action = ui.Call("__panel__editor")` to seed its center slot).

---

## [2.0.12] — 2026-04-30

### Fixed

- **Architecture** — renamed `__panel__board` → `__panel__editor` to match the platform center-slot naming convention used by `notes` and `sql-db` (both expose their center panel as `__panel__editor`). The platform's center-slot router appears to recognize `editor` specifically; `board` was opening in the chat/right area for some clients.
- **File rename** — `panels_board.py` → `panels_editor.py`.
- **Decorator** — `@ext.panel("board", ...)` → `@ext.panel("editor", ...)`.
- **Call sites** — `ui.Call("__panel__board", ...)` → `ui.Call("__panel__editor", ...)` in `panels.py`, `panels_task.py`, `handlers_connection.py`.
- **`imperal.json`** — tool entry renamed `__panel__board` → `__panel__editor`.
- **`main.py`** — purge list updated for the rename.

---

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
