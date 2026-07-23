# Changelog

## [3.38.0] — 2026-07-23

### Added
Ten UI/UX improvements to the panel, all built directly on existing
`@chat.function` handlers (no new backend endpoints):

- **Assignees on task detail** — assign/unassign right from the panel
  (`ListItem` + `Avatar`, unassign inline, assign via search input).
- **Labels on task detail** — attach/detach existing labels, pick from
  the full label list via `ui.Select`.
- **Attachments on task detail** — upload (`ui.FileUpload`), list, and
  delete files directly on a task.
- **Live-notifications toggle** in the sidebar footer — one button that
  calls `enable_task_notifications` / `disable_task_notifications`
  depending on current state (read from the extension's own store).
- **Drag-and-drop** on the Kanban board — drag a task card onto a
  bucket's drop-zone to call `move_to_bucket` (same pattern as notes'
  folder drag-and-drop). `MoveToBucketParams.task_id` now also accepts
  the bare `id` alias the frontend injects on drop.
- **Searchable lists** — board columns and smart views (`today`,
  `upcoming`, `overdue`) are now `ui.List(searchable=True)`.
- **Assignee avatars** on task cards.
- **Overdue highlighting** — task cards past due (and not done) get a
  red "OVERDUE" badge and a warning icon.
- **Bulk delete** — multi-select + bulk delete on board columns and
  smart-view lists (`ui.List(selectable=True, bulk_actions=[...])`,
  wired to `delete_tasks`, which now also accepts the `message_ids`
  alias the frontend's bulk-select injects).
- **Project members** in the board header — small avatar row fetched
  from `/v1/projects/{id}/users`.

## [3.37.1] — 2026-07-21

### Fixed
- **`enable_task_notifications` was completely broken end-to-end** — caught by
  live smoke-testing right after the 3.37.0 deploy, before any real user hit
  it. Two independent issues, both now fixed:
  1. HTTP method mismatch between the extension (`POST /v1/webhooks`) and
     `vikunja-bridge`'s route (`PUT`) — a plain wiring bug, 405 on every call.
  2. **Architectural dead end**: the *user-level* Vikunja webhook endpoint
     (`PUT /user/settings/webhooks`) that 3.37.0 targeted lives entirely
     outside Vikunja's own API-token permission system — its route
     registration puts the whole `/user/...` group beyond
     `CollectRoutesForAPITokenUsage`'s reach, so literally no Personal
     Access Token can ever call it, regardless of granted scopes. This
     bridge only ever holds a PAT (never a full login JWT, by design), so
     no scope change could have fixed this.
  **Redesigned onto *project-level* webhooks** (`/projects/{id}/webhooks`),
  which DO live under the plain, token-permitted routes group. Trade-off:
  `enable_task_notifications` now fans out — it registers one webhook per
  project the user currently owns (all sharing the same opaque token +
  secret), instead of one whole-account registration. The user still only
  sees ONE toggle; new projects created after enabling aren't auto-covered
  until disable+re-enable (documented as a known v1 limitation).
- Confirmed via live testing (not just unit-level) that `tasks_attachments`
  scope IS honored by the PAT the connect flow already mints — the
  attachment feature itself needed no permission fix, only the notification
  redesign above.

### Backend (vikunja-bridge, coordinated change, not in this repo)
- v1.2.0 — `routes_webhooks.py` rewritten for per-project registration
  (`/v1/webhooks/projects/{project_id}[/{webhook_id}]`, method fixed to
  POST for create). `routes_connection.py`'s PAT-minting fallback scope
  list gained a `"webhooks"` group.

## [3.37.0] — 2026-07-21

### Added
- **Task attachments** (`upload_task_attachment`, `list_task_attachments`,
  `delete_task_attachment`) — attach files/photos directly to a task.
  Vikunja itself stores the bytes (`task_attachments_enabled=true`, 20MB
  cap per its own `/info`); the extension and `vikunja-bridge` are a pure
  multipart passthrough — no file ever touches our disk or database.
  Mirrors the notes extension's `upload_attachment`/`delete_attachment`
  pattern, adapted for Vikunja's `files` (plural) field and numeric
  attachment IDs. Download is intentionally not a chat.function (binary
  content doesn't round-trip through chat usefully) — same call notes made.
- **Live Vikunja notifications** (`enable_task_notifications`,
  `disable_task_notifications`, `get_notification_status`) — one toggle
  registers a *user-level* Vikunja webhook (fires for every project on the
  user's own instance, not per-project) pointed at a new
  `@ext.webhook("vikunja_events")` receiver. Notification-worthy events
  (assigned, comment, due-date reminder — a fixed v1 set, not yet user-
  configurable) are forwarded to `ctx.notify(...)`, routed through the
  platform's existing bell/telegram/email preferences — nothing new to
  configure there. Identity resolution uses an opaque per-registration
  token embedded in the target URL plus an HMAC secret (`X-Vikunja-
  Signature`, verified constant-time) — same two-collection reverse-index
  pattern github-connector's webhook uses, adapted for BYO Vikunja (no
  shared-installation cross-user leakage to guard against here, since each
  webhook registration is already scoped to one user's own instance).

### Backend (vikunja-bridge, coordinated change, not in this repo)
- v1.1.0 — new `routes_attachments.py` (multipart proxy to Vikunja's task
  attachment endpoints) and `routes_webhooks.py` (proxies user-level
  webhook registration; does NOT receive deliveries — those go straight
  from Vikunja to the extension's own public webhook URL).

## [3.36.0] — 2026-07-19

### Fixed
- **Every Vikunja HTTP 412 was misreported as "No Vikunja connected"**
  (`is_no_connection_error()` matched on bare `http_status == 412`).
  Vikunja itself returns 412 for generic precondition failures too — e.g.
  deleting a kanban view's last bucket — so a real, unrelated Vikunja error
  was being relabeled as a lost connection, sending users on pointless
  reconnect attempts. The bridge (`vikunja-bridge`, coordinated change, not
  in this repo) now tags its own "no working connection" 412s with
  `{"code": "no_connection", ...}`; a passthrough of Vikunja's own error
  never carries that code. `is_no_connection_error()` now matches on that
  `code`, not on the status alone — genuine Vikunja error detail (e.g. "a
  kanban view must keep at least one bucket") now reaches the user via
  `_bridge_error_msg()` instead of being swallowed by the connection-lost
  message.
- `delete_bucket`: pre-checks the project's bucket count before calling
  Vikunja, returning a clean `TASKS_LAST_BUCKET` error up front instead of
  hitting Vikunja's 412 and re-deriving the same fact from its error detail.

### Changed
- Bumped `imperal-sdk` pin `5.9.11` → `5.9.12` (5.9.10 file_sinks manifest
  contract, 5.9.11 `ui.FileUpload` widget, 5.9.12 internal shared-httpx-pool
  refactor for gateway-facing clients — none of this extension's code paths
  use `ctx.http` differently or declare file sinks, so this is a pure pin
  bump; no source changes needed for the bump itself).
- New app-declared error code `TASKS_LAST_BUCKET` in `error_codes.py`.

## [3.35.0] — 2026-07-18

### Changed
- **display_name**: renamed from generic "Tasks" to explicit "Vikunja Tasks
  Connector" — the old generic name was getting confused with/reverting to
  a different generic "Tasks" app in the catalog.
- Bumped `imperal-sdk` pin `5.9.9` → `5.9.11` (no breaking changes affect
  this extension — module imports verified clean under the new pin).
- Every `ActionResult.error(...)` call site (88 total across
  handlers_ai.py, handlers_collab.py, handlers_connection.py,
  handlers_crud.py, handlers_organize.py, handlers_search.py,
  handlers_structure.py) now carries a structured `code=` (SDK 5.9.7+,
  validator rule V32): platform taxonomy codes where they fit
  (`VALIDATION_MISSING_FIELD`, `PERMISSION_DENIED`, `INTERNAL`), plus a
  small new app-declared set in `error_codes.py` for Vikunja-specific
  failures the platform taxonomy doesn't cover (`TASKS_BRIDGE_ERROR`,
  `TASKS_CONNECT_FAILED`, `TASKS_PROJECT_NOT_FOUND`, `TASKS_TASK_NOT_FOUND`,
  `TASKS_TASK_AMBIGUOUS`, `TASKS_BUCKET_NOT_FOUND`,
  `TASKS_CHECKLIST_ITEM_NOT_FOUND`, `TASKS_KANBAN_VIEW_MISSING`).
- No behavior change for users — this is diagnosability-only (plus the
  display name fix above).

All handler modules import clean under the new pin; pyflakes clean on
every edited file (0 undefined names).

## [3.34.4] — 2026-07-18

### Fixed

- README slogan translated from Russian to English, for consistency with the platform's
  English-first documentation.
- Replaced leftover Russian example values (`'вафоя'`, `'гидроцефалище2'`) with English
  placeholders in `task_titles` description on `DeleteTasksParams`. Cosmetic only.

## [3.34.3] — 2026-07-17

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.9` (picks up upstream fixes for
  structured error codes, provider tool-name length checks, and declared-capabilities
  enforcement). No functional or behavioral changes.

## [3.34.2] — 2026-07-15

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.6` (picks up upstream fixes for
  app-scoped secret manifest validation and panel metadata roundtrip parity). No functional or
  behavioral changes.

## [3.34.1] — 2026-07-07

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.3` (fixes an intermittent `ctx.cache.set()`
  size-guard bug on large cache entries). No functional or behavioral changes.

## [3.34.0] — 2026-07-01

### Changed

- **Backend credentials are now managed as an encrypted secret.** The backend API key is declared as
  an app-scoped `@ext.secret` and read from encrypted secret storage at runtime instead of a plaintext
  environment variable — set it once in the Developer Portal → Secrets tab. No value ever lives in the
  source. Rebuilt against the latest platform SDK.

## [3.33.2] — 2026-06-16

### Changed

- Maintenance release — rebuilt against the latest platform SDK. No functional or behavioral changes.

## [3.33.1] — 2026-06-11

### Changed

- Maintenance release — rebuilt against the latest platform SDK. No functional or behavioral changes.

## [3.33.0] — 2026-06-05

### Changed

- **`list_projects` now returns ALL projects with `is_archived` / `is_favorite` flags** (was:
  archived projects silently dropped, so "show my archived/favorited projects" was unanswerable).
  `ProjectItem` gained the two boolean fields so the assistant can filter by them. Summary still
  reports active count. Project progress (% complete) is intentionally NOT added — Vikunja's project
  object carries no counts and computing them needs a per-bucket count fan-out the live view already
  does; answer "% complete" from the existing board data.

## [3.32.0] — 2026-06-05

### Fixed

- **Task list reads now carry `assignees` (data-gap fix).** The slim `TaskItem` previously
  exposed only `id/title/is_done/priority/due_at/project_id` — it had **no `assignees`** field,
  so EVERY list/search read (`list_project_tasks`, `list_my_tasks`, `find_task`,
  `get_bucket_tasks`, `list_overdue/today/upcoming`, `filter_tasks`) was structurally incapable
  of answering "who is assigned to the tasks?". Given an assignee-less list, the assistant fell
  back to dumping titles and fabricating a "(with assignees)" framing. `assignees` is now
  populated on every task list item from the Vikunja list payload (the task list response
  already embeds the full `assignees` array — no backend change needed).

### Changed

- **`TaskItem` enriched** with `bucket_id`, `percent_done`, `assignees`, `labels` (mirrors the
  fields `get_task`/`TaskEntity` already returned). This also closes the `find_task` contract gap
  (its description + params promised `bucket_id`, which the slim model never carried). `description`
  is intentionally kept OFF the slim list item (HTML body would bloat large lists) — use `get_task`.
- New helpers `vikunja_assignees()` / `vikunja_labels()` in `models_return.py`; the three identical
  `_task_entry` builders (`handlers_search.py`, two in `handlers_structure.py`) now populate the
  new fields via these helpers (DRY).

## [3.31.0] — 2026-06-03

### Changed

- **SDL: all task / project / subtask list reads now return real `sdl.EntityList[…]`**
  (`items=[...]`, `total=N`), completing the entity-list migration started in
  3.30.0 (users/members). Affected returns: `TaskListResult`, `FindTaskResult`, `GetBucketTasksResult`,
  `ListProjectTasksResult` → `sdl.EntityList[TaskItem]`; `ListProjectsResult` → `sdl.EntityList[ProjectItem]`;
  `ListSubtasksResult` → `sdl.EntityList[SubtaskItem]`. Coordinates (`query`, `project_id`, `bucket_id`,
  `bucket_title`, `project_title`, `task_id`) are kept as additive typed fields on the subclasses.
- **List items are now serialized to plain dicts** in the result payload (was: raw `TaskItem` /
  `ProjectItem` / `SubtaskItem` objects, which did not serialize cleanly). Each item now serializes as a
  canonical entity (`id`/`title`/`kind` + facets).
- **Why:** the platform recognizes cross-turn references ("delete these", "the second one") and builds
  proactive multi-item offers ONLY from results it recognizes as a typed entity list. Task reads previously
  used a legacy shape, so tasks were invisible to anaphora/proactive flows while other extensions worked. They
  now behave like the rest of the platform.

### Fixed

- **`delete_tasks`: the bulk-delete target now reliably maps to `task_ids`.** Bulk delete now consistently
  targets the right set of tasks, even when other ID fields are present in the request.

### Notes

- Pure extension-side change; the backend wire contract is unchanged.
- `system_prompt.txt`: the counting caveat now references `"total: 50"` (the entity-list `total` field) instead
  of the removed `count` key.

## [3.30.0] — 2026-06-03

### Changed

- **SDL: `search_vikunja_users` + `list_project_members` now return real `sdl.EntityList[UserEntity]`**,
  replacing the legacy `{users: List[Any]}` wrappers. New `UserEntity` (`id`=Vikunja user id, `title`=username,
  `kind="user"`, `connected` flag). Result data is now `{"items": [...], "total": n}` (+ `project_id` for
  members). This lets the platform resolve users as typed entities, enabling by-name routing and cross-turn
  references over user lists. Pure extension-side; backend wire contract unchanged.

## [3.29.0] — 2026-06-03

### Added

- **`list_project_members`** — lists the members of a specific project (owner + user/team
  shares) via the backend (instance-agnostic and BYO-correct). Accepts `project_id` or
  `project_name` (auto-resolved). Replaces the
  former semi-workaround of routing "who is on project X" to the instance-wide
  `search_vikunja_users(query="")`.

### Changed

- **system_prompt** — team-membership routing now distinguishes project-scoped from
  instance-wide: a named project → `list_project_members(project_name=...)`; a general
  "who is available" with no project → `search_vikunja_users(query="")`.

## [3.28.0] — 2026-06-02

### Added

- **`list_upcoming`** — lists tasks due in the next 7 days (`done = false && due_date >= now
  && due_date < now+7d`), sorted by due date. Mirrors `list_overdue` / `list_today`. Gives the
  planner a named tool for "задачи на ближайшие 7 дней" instead of hand-writing Vikunja date
  filter syntax.

### Changed

- **system_prompt** — added routing rules: (1) "team members / участники / кто в команде /
  members of project X" → `search_vikunja_users(query="")` (NOT `count_tasks_per_bucket`, and
  do not silently write the answer into a note); (2) due-date views — overdue → `list_overdue`,
  today → `list_today`, next 7 days → `list_upcoming`.

## [3.27.0] — 2026-05-31

### Changed

- **SDL migration (SDK 5.2.0).** Entity-read functions now return typed SDL entities instead of plain dicts.
  `get_task` → `TaskEntity`, `get_project` → `ProjectEntity`, bucket lists → `BucketEntity`,
  task list items → `TaskItem` (slim SDL entity). All entities carry canonical `id`/`title`/`kind`
  fields read directly by the platform — enables correct cross-turn context ("in the same project").
- **SDK bump** `5.0.3` → `5.2.0`.
- `models_return` added to `main.py` hot-reload purge list.

## [3.26.0] — 2026-05-29

### Added

- **`delete_tasks`** — bulk delete function. Accepts `task_titles: List[str]` (auto-resolved
  to IDs via search) and/or `task_ids: List[int]`. Optional `project_name`/`project_id` to
  narrow title search. Returns per-task results with deleted/failed counts.

### Changed

- **system_prompt** — added explicit rule: ask the user (in their language) when project,
  task name, or bucket is missing or ambiguous. Never infer context from previous messages.
  Added bulk delete guidance: use `delete_tasks` for 2+ tasks, not multiple `delete_task` calls.

## [3.25.9] — 2026-05-29

### Fixed

- **ImportError: cannot import name 'api_get' from 'app'** — sys.modules pollution between
  extensions. Moved `fetch_all_pages` helper to `app.py` (loaded first, clean namespace).
  Removed all cross-handler imports (`handlers_crud→handlers_structure`,
  `handlers_structure→handlers_search`). Bucket name resolution in `create_task` inlined
  without any handler imports. All handlers now only import from `app.py` and `models_return.py`.

## [3.25.8] — 2026-05-29

### Fixed

- **skeleton** — switched bucket fetch from `/views/{id}/tasks` (Vikunja 50-task hardlimit)
  to `/views/{id}/bucket_counts` (SQL-based, exact). Skeleton now contains accurate
  `task_count` per bucket — classifier gets correct data without extra API calls.

## [3.25.7] — 2026-05-29

### Fixed

- **`create_task`** — added `bucket_name: Optional[str]` param. When caller passes a bucket
  name (e.g. "Social Media"), the handler resolves it to `bucket_id` via the kanban view
  before creating the task. Previously the planner passed `bucket_name` but the
  param was silently ignored (unknown field), causing all tasks to land in the default bucket.
- **Backend `bucket_counts`** — added explicit `int()` cast for `task_count` and `done_count`.
  The aggregate count could come back as a string, causing a TypeError in
  `count_tasks_per_bucket` (`int - str`).

## [3.25.6] — 2026-05-29

### Fixed

- **Priority coercion** — `CreateTaskParams` and `UpdateTaskParams` now accept `priority`
  as string (`"5"`) and coerce to int before Pydantic validation. Prevents
  validation errors when priority arrives as a quoted number.
- **Double assignment** — updated `create_task` description to explicitly state that
  the `assignee` param handles assignment internally; the assistant must not add a
  separate `assign_task` step.
- **Autopagination** — `list_my_tasks`, `filter_tasks`, `list_project_tasks` now
  automatically paginate through all pages (up to 1000 tasks) when called with default
  `page=1`. Vikunja hard-caps at 50 per request; previously only the first page was
  returned. Explicit `page=2+` calls still return that specific page only.
- **Date guidance** — system_prompt now explicitly instructs LLM to convert relative
  dates to full ISO 8601 before calling tools, current year is 2026, bare dates are
  forbidden.
- **`ListProjectTasksResult`** — renamed `tasks_on_page` → `total_count` since listing
  now returns all tasks, not just one page.

## [3.25.5] — 2026-05-29

### Fixed

- **Backend `create_task` / `update_task`** — normalize bare date strings (`"2026-05-30"`)
  to full ISO 8601 (`"2026-05-30T00:00:00Z"`) before sending to Vikunja. Vikunja rejects
  date-only values with 400 "Invalid model provided". LLMs frequently omit the time part.
- **`CreateTaskParams.priority` description** — fixed `"5=urgent"` → correct scale
  `"0=none, 1=low, 2=medium, 3=high, 4=urgent, 5=critical"` to match system_prompt
  and prevent LLM from passing wrong values.

## [3.25.4] — 2026-05-29

### Fixed

- **`list_project_tasks`** — renamed response field `count` → `tasks_on_page` to prevent
  LLM from confusing the page count with the total. Summary now explicitly says
  "showing N on this page" and directs to `count_tasks_per_bucket` for true total.

## [3.25.3] — 2026-05-29

### Fixed

- **`count_tasks_per_bucket`** — rewrote to use new backend SQL endpoint
  `GET /v1/projects/{id}/views/{vid}/bucket_counts` instead of embedded tasks
  from the Vikunja REST API. Vikunja caps REST responses at 50 tasks per request
  regardless of `per_page`; the SQL path queries `task_buckets` + `tasks` directly,
  returning exact counts with no pagination limits. Confirmed 187 tasks on a test
  project vs the previous capped result.
- **Backend** — added a `bucket_counts` endpoint that returns exact per-bucket counts,
  with a connection ownership check.

## [3.25.2] — 2026-05-28

### Fixed

- **`list_project_buckets`, `count_tasks_per_bucket`, skeleton** — switched bucket
  fetch from `/views/{id}/buckets` to `/views/{id}/tasks`. The `/buckets` endpoint
  returns `tasks=null`; only `/tasks` returns embedded task data, making `task_count`
  always 0 before this fix.
- **`create_bucket`** — kept on `/buckets` endpoint (write path, not affected).

## [3.25.1] — 2026-05-28

### Changed

- Bump `imperal-sdk` pin: `5.0.2` → `5.0.3` (docs-only SDK release, no API changes).

## [3.25.0] — 2026-05-28

### Added

- **`count_tasks_per_bucket`** — new function: count tasks in every kanban bucket for a
  project. Returns per-bucket breakdown (total/done/pending) and project-level totals in a
  single kanban view fetch — no N+1 calls. Accepts `project_name` or `project_id`.

### Changed

- **`list_project_buckets`** — now returns `task_count` per bucket in the response.
  Summary line updated to show task count alongside each bucket name.
- **`BucketNavItem`** (models_return.py) — added `task_count: int = 0` field.
- **skeleton** — `buckets_per_project` now includes `task_count` per bucket, enabling
  the platform to serve aggregation queries from cached context without extra API calls.
- **system_prompt** — fixed misleading counting guidance (was pointing to non-existent
  `list_buckets` + `task_count`). Now directs LLM to `count_tasks_per_bucket`.
- **`search_vikunja_users`** — fixed `chain_callable=False` → `True`; function was
  silently blocked from chain dispatch (broke assign-after-search flows).

## [3.24.0] — 2026-05-27

### Changed — фундаментальный рефакторинг bucket-функций

Убраны дублирующие функции, классификатор теперь имеет один чёткий путь на каждый интент:

- **Удалена `list_buckets`** — дублировала `get_bucket_tasks`, путала классификатор
- **Удалена `get_named_bucket_tasks`** — слита в `get_bucket_tasks`
- **`get_bucket_tasks`** — теперь принимает `bucket_name` ИЛИ `bucket_id`, `project_name` ИЛИ `project_id`. Если проект не указан — ищет по всем проектам. Один интент, одна функция.
- **`list_project_buckets`** — описание переписано: явно говорит "только для просмотра структуры бакетов, НЕ для задач"

---

## [3.23.0] — 2026-05-27

### Added
- **`create_task`** — новые поля `project_name` (резолвит по имени вместо `project_id`) и `assignee` (email/имя — автоматически назначает после создания задачи одним вызовом).
- **`list_project_tasks(project_name)`** — все задачи проекта по названию; ранее можно было только через глобальный фильтр.
- **`get_project(project_name)`** — детали проекта (title, description, hex_color, is_archived) по имени или ID.
- **`resolve_project_id`** — shared helper в `app.py` для case-insensitive резолва project_name → project_id (exact → startswith → contains).

### Fixed
- **`list_project_buckets` / `list_buckets`** — теперь принимают `project_name` вместо обязательного `project_id`. Фиксирует `no_orchestrator_registered:tasks` при запросах вида "какие бакеты в проекте webhostmost tasks".
- **`move_to_bucket`** — добавлены `bucket_name` + `project_name`; больше не требует числовой `bucket_id` — резолвит по имени бакета.
- **`move_to_project`** — добавлен `project_name` вместо обязательного `project_id`.

### Changed
- SDK бамп `imperal-sdk==5.0.1` → `5.0.2`.

---

## [3.22.0] — 2026-05-23

### Fixed
- **Skeleton — flat `buckets` list** — added a top-level `buckets` key to the skeleton response so the platform's chain autofill can find `bucket_id` by name. Previously buckets were only nested inside `active_projects[i]["buckets"]`, which the top-level lookup never found.
- **Skeleton — all projects** — removed `:5` cap on bucket fetch. Backend now reads from DB (fast), so fetching all active projects is safe at 30s TTL.
- **`_bridge_error_msg`** — no longer returns `"prefix: None"` when backend detail is absent; returns just the prefix instead.

## [3.21.0] — 2026-05-20

### Fixed
- **Skeleton — buckets per project** — kanban buckets now fetched and included for up to 5 active projects on every skeleton tick. Classifier previously had no bucket data → sent wrong `bucket_id` to backend → Vikunja 400 errors.
- **Skeleton — `bucket_id` + `assignees` in recent tasks** — each recent task now carries its current bucket and assignee usernames.
- **Skeleton — team members** — `team_members` list (username + connected) now included; helps classifier resolve assignee names without guessing.
- **Skeleton — `asyncio.gather` resilience** — added `return_exceptions=True` to all gather calls including new bucket/views fetches; a single failing project view call no longer drops the entire skeleton tick.

---

## [3.20.0] — 2026-05-19

### Fixed
- **`assign_task` loop bug** — removed "prefer find_task first" from description that
  taught the AI to search instead of assigning. Now explicitly instructs: call
  `assign_task` directly with `task_name`, no pre-search needed.
- **`assign_task` — new `bucket_name` param** for disambiguation when multiple tasks
  share the same title. When provided, the handler resolves the bucket via the
  project's kanban view and filters candidate tasks to that column before assigning.

## [3.19.0] — 2026-05-19

### Added
- **`create_bucket`** — chat function to create a new kanban column in a project
  (`action_type=write`, `chain_callable=True`, optional WIP limit).
- **`delete_bucket`** — chat function to delete a kanban column; tasks are moved
  to the project default column (`action_type=destructive`, `chain_callable=True`).
- **Board UI — `+ Column` button** in project board header; opens inline create-column form.
- **Board UI — per-column actions**: ✎ Rename and ✕ Delete buttons on every column header.
- **Board UI — `+ Task` per column**: quick-add button at the top of each column
  that pre-selects the column in the task creation form.
- **Task create form — bucket pre-selection**: column selector now pre-fills
  when `bucket_id` is passed via panel navigation.

### Backend
- Added a route to delete a kanban column (bucket) from a project view.

## [3.18.0] — 2026-05-18

### Added
- **`ai_breakdown_task(task_id, count=5, context?)` — AI task breakdown** — new `handlers_ai.py`. Fetches parent task title + description, calls `ctx.ai.complete()` with a structured planning prompt, parses the numbered list response, and creates each title as a real Vikunja subtask via `POST /v1/tasks/{id}/subtasks`. Returns `AiBreakdownResult` with list of `{task_id, title}` created subtasks. Partial success supported — reports how many failed without aborting the whole call. `system_prompt.txt` rule added: triggers on "break this task", "разбей задачу", "create a plan for", "что нужно сделать чтобы".

---

## [3.17.0] — 2026-05-18

### Fixed
- **`system_prompt.txt` — create_task bucket resolution** — `create_task` section now instructs LLM to call `list_project_buckets` (lightweight, names+IDs only) instead of `list_buckets` (full board with all tasks). `list_buckets` with 13+ buckets produces a huge payload that causes LLM to lose track of bucket IDs, resulting in `bucket_id` validation errors on create.

---

## [3.16.0] — 2026-05-18

### Fixed
- **`id_projection` on compound-name write handlers** — added `id_projection="task_id"` to `update_task`, `complete_task`, `uncomplete_task`, `delete_task`. Compound-name write/destructive handlers must declare `id_projection` so the platform can build proper multi-step chain context and audit records. These handlers had `task_id` in params but no projection declared.

---

## [3.15.0] — 2026-05-18

### Added
- **`rename_bucket(project_id, bucket_id, title, limit?)`** — rename a kanban column or update its WIP limit. A new backend endpoint was added to proxy Vikunja's bucket-update API.

---

## [3.14.0] — 2026-05-18

### Added
- **`get_named_bucket_tasks(project_name, bucket_name)`** — compound single-call handler: resolves project name and bucket name to IDs, returns ONLY the tasks of that specific bucket. Eliminates the "LLM writes all buckets to a note" class of bugs.
- **`get_bucket_tasks(project_id, bucket_id)`** — targeted retrieval by integer IDs. Returns tasks from one bucket only.
- **`list_project_buckets(project_id)`** — lightweight bucket navigation: names and IDs, no task data. Use before `move_to_bucket` or `create_task` when bucket_id is unknown.
- **`_get_kanban_view_id()`** — shared helper to find kanban view, deduplicates logic across all bucket handlers.
- **`_match_by_name()`** — shared case-insensitive name matcher (exact → prefix → contains) used by compound handlers.

### Fixed
- **`on_event` format** — both `panels.py` and `panels_editor.py` now use the correct `tasks.task.created` format (the app_id prefix is required; the platform prepends `app_id` automatically).
- **`system_prompt.txt`** — `get_named_bucket_tasks` is now the primary bucket lookup pattern. `list_buckets` relegated to "full board overview only" use case.

---

## [3.13.0] — 2026-05-17

### Fixed
- **`panels_editor.py` `_find_kanban_view`** — same `view_kind == "kanban"` string comparison bug now also fixed in the board panel (supports both `"kanban"` and `4`). Board panel was silently showing "No kanban view found" on Vikunja v0.21+.
- **`on_event` refresh strings** — both `panels.py` and `panels_editor.py` now use the correct `tasks.` app-id prefix (e.g. `tasks.task.created` instead of `task.created`). Without the prefix SSE-based panel auto-refresh never fired.
- **Sidebar on_event** — added `tasks.task.uncompleted` event so reopening a task refreshes the sidebar.
- **Board on_event** — added `tasks.task.uncompleted`, `tasks.task.mentioned`, `tasks.project.archived` events.
- **`CommentItem` DTO** — added `created: Optional[str]` field that `list_comments` was already returning but DTO wasn't declaring.
- **`handlers_connection.py` trailing slash** — `base_url` now stripped with `.rstrip("/")` in both `connect_vikunja` and `connect_vikunja_with_pat`. Previously `https://vikunja.example.com/` would produce double-slash paths like `/v1//tasks`.
- **`main.py` purge list** — added `_task_checklist` and `_task_create_form` to hot-reload purge list. Previously editing these sub-modules required a full worker restart for changes to take effect.

---

## [3.12.0] — 2026-05-17

### Added
- **`get_task(task_id)`** — fetch full task details (title, description, done, due date, priority, assignees, labels). Backend endpoint was always there, now exposed.
- **`list_labels()`** — list all labels with label_id and title. Enables label resolution by name before `add_label`. Backend endpoint was always there, now exposed.

### Fixed
- **`view_kind` comparison** — `list_buckets` now handles both string `"kanban"` (older Vikunja) and integer `4` (Vikunja v0.21+). Previously always returned "No kanban view found" on newer Vikunja versions.
- **`list_buckets` error message** — actionable: shows available view types and tells user to add a Board view in Vikunja.
- **`list_buckets` description** — now explicitly states "REQUIRES project_id — call list_projects() first".
- **`filter_tasks` default filter** — removed silent `"done = false"` default. No filter now returns all tasks. Documented that `bucket_id` is not a valid filter field.
- **`assign_task` auto-resolve** — when resolving task by name, now returns error if multiple tasks match instead of silently taking the first.
- **`UpdateTaskResult` fields** — `done`, `priority`, `percent_done` are now Optional with defaults (were required).
- **`CreateTaskResult.bucket_id`** — changed from `int = 0` to `Optional[int] = None` (0 was ambiguous).
- **`AssignResult.assignee_vikunja_user_id`** — changed from `Any` to `Optional[int] = None`.

### Changed
- **`system_prompt.txt`** — full rewrite: added anti-hallucination rule, explicit 2-step bucket chain pattern, label lookup pattern, assign guidance with `search_vikunja_users`, `get_task` and `list_labels` documented.
- **`list_projects` description** — now says "ALWAYS call this first when user refers to a project by name".
- **`DeleteLabelParams.label_id`** description — "Integer label ID from list_labels response. Never a name."

---

## [3.11.0] — 2026-05-17

### Changed

- **SDK 5.0.1** — bumped `imperal-sdk` to `5.0.1` (typed return contract, additive).
- **`data_model=` migration** — all 39 `@chat.function` handlers now declare typed return DTOs via `data_model=` (handlers_crud, handlers_search, handlers_connection, handlers_structure, handlers_collab, handlers_organize). Enables `$REF` path validation and classifier envelope `return_fields`.
- **`tool_name=`** remains in `ChatExtension(...)` — still a required positional arg in SDK 5.0.1 (slated for removal in 5.1.0).

---

## [3.10.0] — 2026-05-15

### Changed

- **SDK 5.0.0 migration** — bumped `imperal-sdk` to `5.0.0`. Removed unused `system_prompt=` kwarg and `SYSTEM_PROMPT` variable (no-op in 5.0.0). Removed unused `pathlib.Path` import. Manifest rebuilt — the legacy `tool_tasks_chat` orchestrator-tool entry was removed (no longer supported in SDK 5.0.0).

---

## [3.9.4] — 2026-05-15

### Fixed

- removed `from __future__ import annotations` from `app.py` — it was co-located with `NoParams(BaseModel)`, risking silent Pydantic validation failures.
- **id_projection**: added `id_projection="task_id"` to `update_comment` handler — the platform was unable to resolve the resource ID in chain steps.
- **system_prompt**: added explicit pagination warning — `list_my_tasks`/`filter_tasks` return max 50 items per page; LLM must use `list_buckets` to count all tasks in a project.

### Changed

- SDK bumped `4.2.10 → 4.2.16` — picks up `ui.Link` render fix (4.2.11), long-running ops primitives `ctx.background_task` / `ctx.deliver_chat_message` (4.2.12), `@chat.function(background=True)` (4.2.13), schema.json fix (4.2.14), a placeholder-args guard (4.2.15), and hallucinated tool name logging (4.2.16).

---

## [3.9.3] — 2026-05-13

### Changed

- SDK bumped `4.2.6 → 4.2.10` — picks up OAuth callback infrastructure + `ctx.webhook_url()` (4.2.7), `SecretDecl` in Manifest schema (4.2.8/4.2.9), and `chain_callable=True` default for read handlers (4.2.10). Read handlers (`list_my_tasks`, `find_task`, `filter_tasks`, `get_connection_status`, etc.) now dispatch typed directly.

---

## [3.9.2] — 2026-05-13

### Changed

- SDK bumped `4.2.1 → 4.2.6` — picks up EXT-SECRETS-V1 (unconditional Secrets panel in right slot), validator synthetic-tool fix (4.2.5), and `ui.Password` primitive (4.2.6).
- **Connect form**: password field switched from `ui.Input` to `ui.Password` — input is now masked while typing.

---

## [3.9.1] — 2026-05-12

### Changed

- SDK bumped `4.2.0 → 4.2.1` — fixes MANIFEST-SKELETON-1 false positive on `@ext.tool("skeleton_alert_*")`.

---

## [3.9.0] — 2026-05-11

### Changed

- **SDK bumped `4.1.3 → 4.2.0`** — no behavioral changes for this extension.

### Fixed

- **4 raw exception leaks in `handlers_connection.py`** — `f"Connect/Disconnect/Status failed: {e}"` replaced with `log.error(...)` + safe `ActionResult.error(..., retryable=True)` so internal error details are no longer surfaced to users.
- **`from __future__ import annotations` removed** from all 6 handler files that define Pydantic `BaseModel` param classes (`handlers_connection.py`, `handlers_crud.py`, `handlers_organize.py`, `handlers_search.py`, `handlers_structure.py`, `handlers_collab.py`).
- **[Cleanup] Duplicate `NoParams` class removed** from `handlers_connection.py` — was shadowing the imported `NoParams` from `app.py`.
- **[Logging] `import logging` + `log` added** to `handlers_connection.py`.
- **[Skeleton] `skeleton_alert_tasks` restored** using `@ext.tool`. A false-positive in one manifest validator was reported upstream.
- **[Skeleton] `"error": str(e)` removed** from degraded skeleton return (zero-values only).
- **[Backend] provisioning route** — 2 raw exception leaks in 500 responses replaced with generic messages + internal logging. Service restarted.

---

## [3.8.0] — 2026-05-08

### Added

- **`search_vikunja_users` chat.function** — LLM can now discover who is assignable before calling `assign_task`. Returns username, Vikunja ID, and connected status for each user. Empty query lists all known users on the instance.

### Fixed

- **`assign_task` — two-tier user resolution** — the backend now falls back to the Vikunja user-search API when the assignee is not found among connected users. Users with a Vikunja account who haven't connected their Imperal account can now be assigned tasks.
- **`GET /v1/users` backend endpoint** — same two-tier logic; an empty query lists all connected users on the same Vikunja instance. Results include a `connected: bool` field.

---

## [3.7.0] — 2026-05-07

### Fixed

- **[P0] `assign_task` — task_name auto-resolve + id_projection** — Added `task_name: Optional[str]` to `AssignTaskParams`. When `task_id=0` and `task_name` is provided, the extension searches for the task automatically instead of failing with Pydantic validation error. Previously, LLM passed `task_name` (non-existent field) causing "missing required field task_id". Added `id_projection="task_id"` so multi-step chain dispatch can inject task_id from prior steps.
- **[P1] `unassign_task` — added `id_projection="task_id"`** — same missing projection fixed.
- **[P1] Backend — tenant isolation on user lookup** — user lookup is now scoped to the same Vikunja instance as the requester. Previously it searched all connections globally — could return users from different Vikunja instances in multi-tenant deployments.
- **[P1] Backend `connect` / `connect_with_pat` — old token revoked on reconnect** — the previous access token is now revoked before storing the new one. Previously, the old token became an orphan in the user's Vikunja on every reconnect.

### Changed

- **`skeleton_refresh_tasks` — parallel API calls via `asyncio.gather`** — 5 sequential API calls (today/overdue/upcoming/recent/projects) replaced with a single `asyncio.gather`. Skeleton refresh is ~5x faster.
- **`panels_task.py` split** — 501-line god file split into 3 modules: `_task_checklist.py` (TipTap checklist parser + toggle helpers), `_task_create_form.py` (create form renderer), `panels_task.py` (task detail + edit form, now ~200 lines).
- **SDK bumped `4.1.2 → 4.1.3`** — pure refactor release, no API changes.

---

## [3.6.0] — 2026-05-07

### Changed

- **`assign_task` now accepts name or email** — `assignee_query: str` replaces `assignee_vikunja_user_id: int`. The backend resolves the name/email to a Vikunja user ID. No more asking the user for a numeric ID.
- Backend assign endpoint extended with an `assignee_query` field; the response includes `_resolved_user_id` and `_resolved_username` for subsequent unassign calls.
- Backend user-lookup endpoint added.

---

## [3.5.0] — 2026-05-05

### Changed

- **SDK upgraded to `imperal-sdk==4.1.2`** — picks up Pydantic feedback-loop (4.1.0), narration schema tightening (4.1.1), and `id_projection` chain dispatch (4.1.2).
- **`id_projection` added to all compound-named chain functions** — fixes multi-step chain target projection:
  - `handlers_organize.py`: `add_label`, `remove_label`, `set_due_date`, `set_priority`, `move_to_project`, `move_to_bucket` → all `id_projection="task_id"`
  - `handlers_crud.py`: `create_task` → `id_projection="project_id"` (chains from create_project); `create_subtask` → `id_projection="parent_task_id"`; `toggle_checklist_item` → `id_projection="task_id"`
  - `handlers_collab.py`: `add_comment`, `mention_user` → `id_projection="task_id"`

---

## [3.4.0] — 2026-05-04

### Changed — task description editor

- **`panels_task.py`** — task detail panel description edit form switched from a single-line `ui.Input` to `ui.RichEditor` (SDK 4.1.0 TipTap WYSIWYG component, same TipTap engine Vikunja stores descriptions with). Round-trips HTML faithfully: paragraphs, headings, lists, bold/italic, code blocks, links — all preserved end-to-end (Vikunja → backend → extension panel → backend → Vikunja). The rendered `ui.Html(...)` preview above the editor was already correct; only the edit affordance was the regression. TipTap `taskList` nodes inside description continue to be stripped from the rendered preview and surfaced as a separate interactive Checklist card via `toggle_checklist_item`; whatever taskList items the user keeps when editing in the rich editor are saved back verbatim.
- **No backend changes.** Description payload to Vikunja is identical (HTML body in `description` field).

---

## [3.3.0] — 2026-05-04

### Added — kanban subtask grouping (UI-side)

- **`panels_editor.py`** — kanban board and smart views (today / upcoming / overdue) now hide subtasks from the main card list and surface them inside a collapsible "↳ Subtasks (done/total)" section at the bottom of each bucket. Implementation:
  - `_collect_child_task_ids(all_tasks)` — single global pass over every bucket's tasks, builds a set of task ids that appear as `related_tasks.subtask` of another task. A subtask sitting in a different bucket than its parent (Vikunja allows that) is still hidden from top-level rendering.
  - `_split_top_and_children(tasks, child_ids)` — partitions a bucket's tasks into top-level cards and children.
  - `_subtasks_section(children)` — renders the collapsed `ui.Section(collapsible=True)` with each child as a normal `_task_card` (kept clickable; opens task detail).
  - Bucket-card title counter changed to `(N top-level)` so the header number matches what's visible. Total-with-children count is shown inside the collapsible section title.
- **No backend changes.** Vikunja still stores subtasks as plain tasks linked via `task_relations`; the visual nesting is purely client-side, so it works regardless of the Vikunja version, the per-view `show_subtasks` toggle, or whether the user brings an external Vikunja instance.

---

## [3.2.1] — 2026-05-04

### Backend — rollback of v3.2.0 kanban fix

- **`create_subtask` — reverted Step 4** (the attempt to detach the new subtask from the board by setting `bucket_id: 0`). The call was confirmed to be a silent no-op — the API echoes `bucket_id: 0` back in the response but the underlying board assignment stays untouched, so the subtask still renders on the kanban board.
- **Investigation summary** — Vikunja's REST API has no path to detach a task from all buckets:
  - `bucket_id` is a virtual response field; the canonical store is a per-view board-assignment table. The bucket-update path requires the new `bucket_id` to belong to the same view, so `0` is silently rejected.
  - There is no API endpoint to remove a single task from a bucket.
  - The task model has no `is_subtask` / `hide_on_board` flag.
  - Switching the view to a filter-based bucket configuration could in theory exclude subtasks, but it wipes all manual bucket assignments — a destructive global change to the user's board.
  - A direct database delete of the board-assignment row does correctly remove the card from the kanban view (verified end-to-end), but the BYO model gives only API access to a user's Vikunja, not database access. Implementing this would break the BYO contract for users who bring an external Vikunja instance.
- **Decision** — accept this as a documented Vikunja-side limitation rather than ship a fake fix. The backend `create_subtask` docstring now records the full investigation so the next person doesn't re-discover it.
- **End-user workaround** — in the Vikunja UI, drag the subtask card off the board or move it to a hidden bucket. This UX is Vikunja-side and not exposed via API.
- Backend restarted; health check passes.

### Extension

- **`app.py`** — version bumped to `3.2.1`. Manifest rebuilt.

---

## [3.2.0] — 2026-05-04

### Added

- **`handlers_search.py` — `find_task(query)` chat function (read-only).** Searches tasks by title substring via Vikunja `s=` query parameter and returns matching tasks with their integer `task_id`, `project_id`, `done`, `due_date`, `priority`. Closes the "LLM fabricated task_id because the user referred to a task by name" failure mode — system_prompt now mandates `find_task` FIRST whenever an integer task_id is unknown. `FindTaskParams` is a module-scope BaseModel with a detailed Field description.
- **`handlers_crud.py` — `uncomplete_task(task_id)` chat function** (`action_type="write"`, `chain_callable=True`, `effects=["update:task"]`, `event="task.uncompleted"`). Inverse of `complete_task` — POSTs `{done: false, percent_done: 0.0}` to backend. Closes "accidentally completed a task and can't reopen it from chat".
- **`panels_task.py` — Reopen UI buttons.** Parent task action bar now renders a "Reopen" button (`ui.Call("uncomplete_task", task_id=...)`) instead of "Complete" when the task is `done=true`. Subtask action row now also includes a "Reopen" button (`RotateCcw` icon) before the existing "Delete" button for completed subtasks.

### Changed

- **`system_prompt.txt`** — new "Task name → task_id resolution (REQUIRED)" rule under `## Tool selection`. The LLM must call `find_task(query=...)` before any task-targeted write tool when only the task title is known. Also documents `uncomplete_task` under `## Subtasks`.
- **`skeleton.py`** — `@ext.skeleton("tasks")` TTL reduced from `300` to `30`. The skeleton/context API is read-only for extensions — there is no way for an extension to actively invalidate cached context, and sibling extensions (`notes`, `sql-db`) don't either. Lowering the TTL is therefore the supported way to close the context-staleness window. Panels are already real-time (they fetch fresh data and request a panel refresh); the 30s TTL affects only the cached context counters / `recent_tasks`.

### Backend

- **`create_subtask`** — added Step 4: after creating the child task and linking the parent→child relation, the backend now attempts to detach the subtask from the kanban board (`bucket_id: 0`). Vikunja auto-places every new task into the project's default bucket; subtasks should be link-only — visible inside parent task detail, not as a separate kanban card. The detach call is non-fatal (the relation matters more). The handler now re-fetches the freshly updated child task before returning so the response carries up-to-date `related_tasks` and a cleared `bucket_id`. Service restarted; health check passes.
- **Caveat:** complete subtask hiding on kanban also depends on Vikunja's per-view `show_subtasks` toggle. The backend fix removes bucket binding, which works on Vikunja versions and views without that toggle.

---

## [3.1.0] — 2026-05-04

### SDK 4.1.0 compliance pass

- **`requirements.txt`** — pin bumped `imperal-sdk==4.0.1` → `imperal-sdk==4.1.0`. Worker venv was already on 4.1.0 (last-install-wins from sibling extensions); now declared explicitly. Restores the hard-equality pin invariant.
- **`app.py`** — added a public `NoParams(BaseModel)` for no-arg `@chat.function` handlers. Replaces three previously separate `_NoParams` classes in `handlers_search.py`, `handlers_structure.py`, `handlers_connection.py` — now a single module-scope class in `app.py`, imported everywhere.
- **`app.py`** — renamed `_imperal_id(ctx)` → `imperal_id_of(ctx)` (public cross-module API; underscore prefix removed). Imports updated in `handlers_crud.py`, `skeleton.py`, `panels.py`, `panels_editor.py`, `panels_task.py`.
- **`app.py`** — chat wrapper description extended to instruct the assistant to pass the user message verbatim.
- **`skeleton.py`** — `skeleton_refresh_tasks(ctx, **_)` → `(ctx)` and `skeleton_alert_tasks(ctx, old, new, **kwargs)` → `(ctx, old, new)`. Universal `**kwargs` sinks removed — lifecycle signatures must be strictly typed; after a corresponding platform fix, the defensive sinks are no longer needed.

### Improved

- **`handlers_organize.py`** — descriptions for `assign_task`, `unassign_task`, `add_label`, `remove_label`, `set_due_date`, `set_priority`, `move_to_project`, `move_to_bucket` extended to state explicitly that all IDs are integers and where to obtain them (via `list_buckets` / `list_projects` / etc.). The Pydantic `Field(description=...)` for every ID parameter is also expanded. Closes the failure class "LLM passed a UUID or name where an integer ID was required".
- **`system_prompt.txt`** — new `## ID conventions (CRITICAL — read before any tool call)` section. Strict rule: all Vikunja IDs are positive integers, never UUID / name / slug. Lists every ID field (`task_id`, `parent_task_id`, `project_id`, `bucket_id`, `label_id`, `comment_id`, `assignee_vikunja_user_id`, `vikunja_user_id`) and the standard `list_*` → integer ID → write call flow.

### Cleanup

- Removed dead imports: `is_no_connection_error` from `handlers_organize.py`, `handlers_collab.py`, `handlers_search.py`, `handlers_structure.py` (unused), and `Optional` from `handlers_organize.py` (unused).
- Removed three Nextcloud conflicted-copy files from the repo: `handlers_collab (conflicted copy 2026-05-04 013552).py`, `handlers_crud (conflicted copy 2026-05-03 210133).py`, `panels_editor (conflicted copy 2026-05-03 213503).py`. Added `*conflicted copy*` ignore pattern to `.gitignore`.

---

## [3.0.1] — 2026-05-04

### Added

- **`handlers_collab.py` — `update_comment`**: новый `@chat.function` для редактирования текста существующего комментария (`action_type="write"`). Вызывает `POST /v1/tasks/{task_id}/comments/{comment_id}` на backend.
- **`handlers_collab.py` — `delete_comment`**: новый `@chat.function` для удаления комментария (`action_type="destructive"`). Вызывает `DELETE /v1/tasks/{task_id}/comments/{comment_id}` на backend.

### Fixed

- **`panels_task.py` — subtask actions**: выполненные subtask'и теперь показывают кнопку Delete (раньше `actions=[]` скрывал её для done-задач). Complete скрывается только для выполненных.
- **`panels_task.py` — comment actions**: каждый комментарий теперь имеет кнопку Delete с подтверждением (`ui.Call("delete_comment", ...)`).

---

## [2.0.20] — 2026-04-30

### Fixed / Improved

- **`handlers_structure.py` — `list_buckets`**: now returns tasks embedded per bucket (already available from the `/tasks` backend endpoint — was being stripped before). Response shape: `{buckets: [{bucket_id, title, limit, task_count, tasks: [{task_id, title, done, priority, due_date}]}]}`. LLM can answer "what's in bucket X" from a single `list_buckets` call without chaining `filter_tasks`.
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

- **`system_prompt.txt`** — added **Project lookup rule**: LLM must call `list_projects` first when user asks for tasks by project name, then pass the numeric `project_id` to `filter_tasks`. Added **Vikunja filter syntax** section explicitly listing valid operators/fields/time helpers and forbidding SQL-style subqueries (`select`, `from`, `where` — these produce errors). Fixes an observed hallucination where the model emitted a SQL subquery in place of a numeric `project_id`.

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

### Backend (deployed separately)

- **Task listing** — the backend's task-list route now forwards to Vikunja's current tasks endpoint (the older `/tasks/all` endpoint was removed in Vikunja v0.21+ and returned `400 Invalid model`). The backend route name is unchanged for extension compatibility.
- **Project views** — added a backend route to fetch the tasks of a project's view. Companion to the `panels_board.py` switch above.

---

## [2.0.4] — 2026-04-30

### Fixed

- **`panels.py` + `panels_task.py`** — every `ui.ListItem(...)` now passes the required `id` positional. `ui.ListItem` from `imperal_sdk.ui.data` has `id: str` as the first required arg; calling it without `id` raised `TypeError: ListItem() missing 1 required positional argument: 'id'` and broke the entire `__panel__sidebar` render path right after a successful Vikunja connect — visible in the worker as an infinite spinner on the left sidebar. IDs added: `smart_today` / `smart_upcoming` / `smart_overdue` for the smart-views card, `project_{pid}` for projects, `comment_{id}` for task comments.

### Backend (deployed separately)

- **Token minting** — the create-token payload now includes an expiry timestamp. Vikunja v0.20+ requires this field on token creation; without it the request failed, surfacing to users as a token-mint error.
- **Connect flow** — the post-mint user lookup now uses the session token already obtained from login instead of the freshly minted access token. The user-info endpoint is not in the access token's permission scope, so probing it with that token always failed. The token itself is fine; the validation step was the bug.

---

## [2.0.3] — 2026-04-30

### Fixed

- **`panels.py`** — wrap the connect form inputs in `ui.Form(action=..., submit_label=...)` so that the URL / username / password / PAT fields actually get bundled into the chat-function call. Before this, `ui.Input` nodes were siblings of a `ui.Button(on_click=ui.Call("connect_vikunja"))` — `ui.Input` only attaches `param_name` for *Form* collection (per `imperal_sdk.ui.input_components.Form` docstring: "Form container — collects child input values and submits as one action"); without a Form parent the Button submitted with empty params, so the handler always saw `base_url=""` and returned `Vikunja URL is required`. The view-toggle button ("I have a token" / "Use username + password") stays outside the Form because it's a panel re-render, not a submit. Same wiring will need to be applied to any other panel that uses Inputs as a multi-field form (none today).

---

## [2.0.2] — 2026-04-29

### Fixed

- **`panels.py`** — drop `confirm=` kwarg from the Disconnect `ui.Button`. The parameter was never part of `imperal_sdk.ui.Button` (silently ignored since 2.0.0), and a newer manifest validator hard-fails on it. Disconnect now fires immediately on click — same effective behavior as before, just no fake-confirmation string in the props payload. Followup: wire a real `ui.Dialog`-based confirm flow once the frontend Dialog rendering contract has a reference implementation in another extension.

---

## [2.0.1] — 2026-04-29

### Changed

- **`requirements.txt`** — bump `imperal-sdk==3.0.0` → `==3.4.1`. Pulls in the LLM-FU-1/FU-2 stack (gpt-5 / o-series `max_completion_tokens` rename + `temperature` drop) so chains routed through reasoning models stop falling over to `anthropic/haiku`.
- **`app.py`** — `ChatExtension(model="claude-haiku-4-5-20251001")` removed (deprecated since SDK 3.3.0, hard-error in SDK 4.0). LLM model resolution now flows through platform context injection (`ctx._llm_configs`). Mirrors the cleanup done in sql-db 1.4.2 and notes 2.5.2.

### Compatibility

- 3.4.0 panel-slot whitelist already met — `panels.py` `slot="left"`, `panels_board.py` and `panels_task.py` `slot="center"`.

---

## [2.0.0] — 2026-04-27

**Breaking — Bring-Your-Own Vikunja.** Each user now connects their own Vikunja instance via the tasks panel; their data lives in their Vikunja, not in a shared instance. The backend was refactored from a shared-instance broker into a per-user connection manager (encrypted access-token storage + per-call resolve).

### Why

The shared-instance model meant we held tasks data for every user, which is at odds with our positioning ("Webbee speaks to your tools — your data stays with you"). BYO is the right posture for an integrations-layer product: the access token is encrypted at rest in the backend, held in memory only for the single HTTP request that needs it, and revokable from the user's own Vikunja UI at any time. It also unblocks the multi-provider future (Linear, Trello, Asana can drop into the backend alongside the Vikunja adapter without touching the extension).

### Backend

- **New endpoints** — connect (login → mint access token → encrypt → store), connect-with-token (advanced: paste an existing token), disconnect (revoke remote + delete local record), connection status (never echoes the token).
- **New storage** — a per-user connection record: `imperal_id` + Vikunja base URL + username + Vikunja user id + the encrypted access token + a token id for revoke + timestamps.
- **New module** — token encrypt/decrypt. The encryption key is supplied via an environment variable. The plaintext token only ever lives in a single request's stack frame.
- **Per-call resolution** — load connection → decrypt token → call the user's Vikunja with it. No more shared-instance token minting.
- **Deprecated** — the shared-instance auto-provisioning route is no longer mounted. File kept for a decommission window.
- **Backend bumped to 1.0.0** to mark the BYO contract.

### Extension (this commit)

- **New** — `handlers_connection.py` with chat functions `connect_vikunja`, `connect_vikunja_with_pat`, `disconnect_vikunja`, `get_connection_status`.
- **`panels.py`** rewritten — connect-first UX: empty/connect/error/connected/broken states. Empty state shows the connect form + "What is Vikunja?" help (vikunja.io self-host link, try.vikunja.io hosted link). Connected state shows smart views + projects + footer with disconnect button.
- **`panels_board.py`, `panels_task.py`, `skeleton.py`** — gracefully handle the backend's "no connection" response: render a "Connect your Vikunja in the sidebar" empty state instead of crashing or returning zero counts.
- **`app.py`** — dropped `on_install` (auto-provisioning) and `on_uninstall` (cascade delete). Added `is_no_connection_error(resp)` helper for 412 detection. Added `require_imperal_id(ctx)` fail-loud helper.
- **All handler files (`handlers_crud/_organize/_search/_structure/_collab.py`)** — Russian `ActionResult.error` strings flipped to English. New `_bridge_error_msg(resp, default_prefix)` helper surfaces the backend's "Connect your Vikunja first" message specifically rather than a generic CRUD error.
- **`system_prompt.txt`** rewritten with BYO context — "if no connection, ask user to connect via the panel; never request password in chat".
- **`imperal.json`** — version 2.0.0, top-level tool description mentions BYO, `signals` add `connection.created`/`connection.deleted`.
- **`main.py`** — purge list updated for `handlers_connection`.

### Removed

- Shared-instance auto-provisioning. The old `imperal_id → vikunja_user_id` mapping is no longer the routing source. The legacy data is retained for a decommission window; the new code path doesn't read or write it.
- `on_install` / `on_uninstall` lifecycle hooks. There's nothing to provision (each user connects on demand) and nothing to cascade-delete (their data lives in their Vikunja).

### Operational notes

- **Required env** — the backend needs the token-encryption key supplied via an environment variable, or it will refuse to start (or the first connect attempt will fail loudly).
- **Migration** — apply the new connections-table migration before restarting the backend. Existing legacy data is left untouched.
- **Backend restart** is required to pick up the new code.
- **Existing users on the shared instance** — there is no automatic data migration. Provide an export tool / amnesty period before decommissioning the shared instance.

---

## [1.1.0] — 2026-04-27

SDK migration: `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0` (Identity Contract Unification, W1).

### Why

SDK 3.0.0 removes the old user class, makes `User`/`UserContext` frozen Pydantic v2 models with `extra="forbid"`, and renames `.id` → `.imperal_id` on user objects. `ctx.user.id` raises `AttributeError` on 3.x with no alias, so any 2.x-pinned extension breaks on identity reads once the runtime moves to 3.0.0.

### Changed

- **`app.py`** — `_imperal_id(ctx)` reads `ctx.user.imperal_id` instead of `ctx.user.id`.
- **`requirements.txt`** — `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0`. Equality pin retained as the workspace invariant.

### Not changed

- All other Python source, manifest, system_prompt, panels, handlers — byte-for-byte identical to 1.0.2.

---

## [1.0.2] — 2026-04-26

Pin bump only: `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Also corrects a pre-existing version drift between `app.py` (which still read `1.0.0`) and `imperal.json` (which read `1.0.1`); both now read `1.0.2`.

### Why

`imperal-sdk` 2.0.1 supersedes the rolled-back 2.0.0 with the v1.6.2 contract restored plus two internal runtime hotfixes. The SDK API surface remains identical to 1.6.2, so v1.6.2 extensions upgrade by pin bump only.

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
- Backend HTTP client via `VIKUNJA_BRIDGE_URL` + `VIKUNJA_BRIDGE_KEY` env.
- `@ext.on_install` / `@ext.on_uninstall` — auto-provision + cascade delete via backend.
- Health check through backend `/health`.
- System prompt guiding LLM tool selection.

## [1.0.0] — TBD

Initial Marketplace release:
- 20 deterministic chat functions + 20 `@ext.panel` FREE duplicates.
- 5 AI-powered functions (breakdown, plan_my_day, estimate_duration, search_tasks, summarize_project).
- Skeleton tools (refresh_tasks, alert_tasks).
- 4 panel surfaces (sidebar, board, task detail, list view).
- DUI Kanban board with 4 view kinds (Kanban / List / Calendar / Gantt).
- Automation signals (21 events: task.*, project.*, label.*).
