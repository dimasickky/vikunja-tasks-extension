# Changelog

## [3.25.0] — 2026-05-28

### Added

- **`count_tasks_per_bucket`** — новая функция: подсчёт задач по каждому бакету проекта.
  Возвращает per-bucket breakdown (total/done/pending) и project-level totals в одном вызове.
  Принимает `project_name` или `project_id`. Источник — kanban view snapshot (те же данные
  что и `list_project_buckets`).

### Changed

- **`list_project_buckets`** — теперь возвращает `task_count` в каждом объекте бакета.
  Summary строка обновлена: показывает количество задач рядом с названием бакета.
- **`BucketNavItem`** (models_return.py) — добавлено поле `task_count: int = 0`.
- **skeleton** — `buckets_per_project` теперь включает `task_count` per bucket.
  Classifier может отвечать на aggregation-запросы из skeleton без API-вызовов
  (kernel invariant I-CLASSIFIER-AGGREGATION-PREFERS-SKELETON).
- **system_prompt** — исправлено misleading guidance про `list_buckets` + `task_count`.
  Теперь направляет LLM на `count_tasks_per_bucket` для counting-запросов.
- **`search_vikunja_users`** — исправлен `chain_callable=False` → `chain_callable=True`.
  Функция была недоступна в цепочках (assign_task after search).

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
- **Skeleton — flat `buckets` list** — added top-level `buckets` key to skeleton response so kernel the platform autofill can find `bucket_id` by name. Previously buckets were only nested inside `active_projects[i]["buckets"]`, which the kernel's `section.get("buckets")` lookup never found.
- **Skeleton — all projects** — removed `:5` cap on bucket fetch. Bridge now reads from DB (fast), so fetching all active projects is safe at 30s TTL.
- **`_bridge_error_msg`** — no longer returns `"prefix: None"` when bridge detail is absent; returns just the prefix instead.

## [3.21.0] — 2026-05-20

### Fixed
- **Skeleton — buckets per project** — kanban buckets now fetched and included for up to 5 active projects on every skeleton tick. Classifier previously had no bucket data → sent wrong `bucket_id` to bridge → Vikunja 400 errors.
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

### Backend (the backend service)
- Added `DELETE /v1/projects/{project_id}/views/{view_id}/buckets/{bucket_id}` route.

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
- **`id_projection` on compound-name write handlers** — added `id_projection="task_id"` to `update_task`, `complete_task`, `uncomplete_task`, `delete_task`. Per SDK docs, compound-name write/destructive handlers must declare `id_projection` so the kernel can build proper $REF chain context and audit records. These handlers had `task_id` in params but no projection declared.

---

## [3.15.0] — 2026-05-18

### Added
- **`rename_bucket(project_id, bucket_id, title, limit?)`** — rename a kanban column or update its WIP limit. New bridge endpoint `POST /v1/projects/{id}/views/{view_id}/buckets/{bucket_id}` added to the backend service to proxy Vikunja's `PUT /api/v1/projects/{id}/views/{vid}/buckets/{bid}`.

---

## [3.14.0] — 2026-05-18

### Added
- **`get_named_bucket_tasks(project_name, bucket_name)`** — compound single-call handler: resolves project name and bucket name to IDs, returns ONLY the tasks of that specific bucket. Eliminates the "LLM writes all buckets to a note" class of bugs.
- **`get_bucket_tasks(project_id, bucket_id)`** — targeted retrieval by integer IDs. Returns tasks from one bucket only.
- **`list_project_buckets(project_id)`** — lightweight bucket navigation: names and IDs, no task data. Use before `move_to_bucket` or `create_task` when bucket_id is unknown.
- **`_get_kanban_view_id()`** — shared helper to find kanban view, deduplicates logic across all bucket handlers.
- **`_match_by_name()`** — shared case-insensitive name matcher (exact → prefix → contains) used by compound handlers.

### Fixed
- **`on_event` format** — both `panels.py` and `panels_editor.py` now use correct `tasks.task.created` format (app_id prefix required per SDK docs: "kernel prepends app_id automatically"). Confirmed via SDK source `extensions/client.py:145`.
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
- **`get_task(task_id)`** — fetch full task details (title, description, done, due date, priority, assignees, labels). Bridge endpoint was always there, now exposed.
- **`list_labels()`** — list all labels with label_id and title. Enables label resolution by name before `add_label`. Bridge endpoint was always there, now exposed.

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

- **SDK 5.0.1** — bumped `imperal-sdk` to `5.0.1` (Federal Typed Return Contract, additive).
- **`data_model=` migration** — all 39 `@chat.function` handlers now declare typed return DTOs via `data_model=` (handlers_crud, handlers_search, handlers_connection, handlers_structure, handlers_collab, handlers_organize). Enables `$REF` path validation and classifier envelope `return_fields`.
- **`tool_name=`** remains in `ChatExtension(...)` — still a required positional arg in SDK 5.0.1 (slated for removal in 5.1.0).

---

## [3.10.0] — 2026-05-15

### Changed

- **SDK 5.0.0 migration** — bumped `imperal-sdk` to `5.0.0`. Removed unused `system_prompt=` kwarg and `SYSTEM_PROMPT` variable (no-op in 5.0.0). Removed unused `pathlib.Path` import. Manifest rebuilt — `tool_tasks_chat` orchestrator-tool entry removed (V25 compliance, `I-LOADER-REJECTS-LEGACY-LLM-ROUTER`).

---

## [3.9.4] — 2026-05-15

### Fixed

- **V18**: removed `from __future__ import annotations` from `app.py` — was co-located with `NoParams(BaseModel)`, risking silent Pydantic validation failures.
- **id_projection**: added `id_projection="task_id"` to `update_comment` handler — kernel was unable to resolve the resource ID in chain steps.
- **system_prompt**: added explicit pagination warning — `list_my_tasks`/`filter_tasks` return max 50 items per page; LLM must use `list_buckets` to count all tasks in a project.

### Changed

- SDK bumped `4.2.10 → 4.2.16` — picks up `ui.Link` render fix (4.2.11), long-running ops primitives `ctx.background_task` / `ctx.deliver_chat_message` (4.2.12), `@chat.function(background=True)` (4.2.13), schema.json fix (4.2.14), placeholder-args guard I-PARAMS-NO-PLACEHOLDER-VALUES (4.2.15), hallucinated tool name logging (4.2.16).

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

- **[I-MAGIC-UX] 4 raw exception leaks in `handlers_connection.py`** — `f"Connect/Disconnect/Status failed: {e}"` replaced with `log.error(...)` + safe `ActionResult.error(..., retryable=True)`.
- **[V18] `from __future__ import annotations` removed** from all 6 handler files that define Pydantic `BaseModel` param classes (`handlers_connection.py`, `handlers_crud.py`, `handlers_organize.py`, `handlers_search.py`, `handlers_structure.py`, `handlers_collab.py`).
- **[Cleanup] Duplicate `NoParams` class removed** from `handlers_connection.py` — was shadowing the imported `NoParams` from `app.py`.
- **[Logging] `import logging` + `log` added** to `handlers_connection.py`.
- **[Skeleton] `skeleton_alert_tasks` restored** using `@ext.tool` (correct per docs.imperal.io and kernel source). MANIFEST-SKELETON-1 validator bug reported to the team.
- **[Skeleton] `"error": str(e)` removed** from degraded skeleton return (zero-values only per SDK contract).
- **[Backend] `the backend service/routes_provision.py`** — 2 raw exception leaks in `HTTPException` 500 responses replaced with generic messages + `log.error(...)`. Service restarted.

---

## [3.8.0] — 2026-05-08

### Added

- **`search_vikunja_users` chat.function** — LLM can now discover who is assignable before calling `assign_task`. Returns username, Vikunja ID, and connected status for each user. Empty query lists all known users on the instance.

### Fixed

- **`assign_task` — two-tier user resolution** — Bridge `_resolve_vikunja_user_id` now falls back to Vikunja API (`GET /api/v1/users?s=`) when the assignee is not found in `vikunja_connections`. Users with a Vikunja account who haven't connected their Imperal account (e.g. Ignat) can now be assigned tasks.
- **`GET /v1/users` bridge endpoint** — same two-tier logic; empty `s` lists all connected users on the same Vikunja instance. Results include `connected: bool` field.

---

## [3.7.0] — 2026-05-07

### Fixed

- **[P0] `assign_task` — task_name auto-resolve + id_projection** — Added `task_name: Optional[str]` to `AssignTaskParams`. When `task_id=0` and `task_name` is provided, the extension searches for the task automatically instead of failing with Pydantic validation error. Previously, LLM passed `task_name` (non-existent field) causing "missing required field task_id". Added `id_projection="task_id"` so kernel chain dispatch can inject task_id from prior steps.
- **[P1] `unassign_task` — added `id_projection="task_id"`** — same missing projection fixed.
- **[P1] Bridge `_resolve_vikunja_user_id` — tenant isolation** — user lookup now scoped to same `base_url` as requester. Previously searched all vikunja_connections globally — could return users from different Vikunja instances in multi-tenant deployments.
- **[P1] Bridge `connect` / `connect_with_pat` — old PAT revoked on reconnect** — `_revoke_existing_connection()` now called before `save_connection()`. Previously, the old PAT became an orphan in the user's Vikunja on every reconnect.

### Changed

- **`skeleton_refresh_tasks` — parallel API calls via `asyncio.gather`** — 5 sequential API calls (today/overdue/upcoming/recent/projects) replaced with a single `asyncio.gather`. Skeleton refresh is ~5x faster.
- **`panels_task.py` split** — 501-line god file split into 3 modules: `_task_checklist.py` (TipTap checklist parser + toggle helpers), `_task_create_form.py` (create form renderer), `panels_task.py` (task detail + edit form, now ~200 lines).
- **SDK bumped `4.1.2 → 4.1.3`** — pure refactor release, no API changes.

---

## [3.6.0] — 2026-05-07

### Changed

- **`assign_task` now accepts name or email** — `assignee_query: str` replaces `assignee_vikunja_user_id: int`. The bridge resolves the name/email to a Vikunja user ID via `/api/v1/users?s=query`. No more asking the user for a numeric ID.
- Bridge `POST /v1/tasks/{id}/assign` extended with `assignee_query` field; response includes `_resolved_user_id` and `_resolved_username` for subsequent unassign calls.
- Bridge `GET /v1/users` endpoint added for user lookup.

---

## [3.5.0] — 2026-05-05

### Changed

- **SDK upgraded to `imperal-sdk==4.1.2`** — picks up Pydantic feedback-loop (4.1.0), narration schema tightening (4.1.1), and `id_projection` chain dispatch (4.1.2).
- **`id_projection` added to all compound-named chain functions** — fixes kernel chain-step target projection:
  - `handlers_organize.py`: `add_label`, `remove_label`, `set_due_date`, `set_priority`, `move_to_project`, `move_to_bucket` → all `id_projection="task_id"`
  - `handlers_crud.py`: `create_task` → `id_projection="project_id"` (chains from create_project); `create_subtask` → `id_projection="parent_task_id"`; `toggle_checklist_item` → `id_projection="task_id"`
  - `handlers_collab.py`: `add_comment`, `mention_user` → `id_projection="task_id"`

---

## [3.4.0] — 2026-05-04

### Changed — task description editor

- **`panels_task.py`** — task detail panel description edit form switched from a single-line `ui.Input` to `ui.RichEditor` (SDK 4.1.0 TipTap WYSIWYG component, same TipTap engine Vikunja stores descriptions with). Round-trips HTML faithfully: paragraphs, headings, lists, bold/italic, code blocks, links — all preserved end-to-end (Vikunja → bridge → extension panel → bridge → Vikunja). The rendered `ui.Html(...)` preview above the editor was already correct; only the edit affordance was the regression. TipTap `taskList` nodes inside description continue to be stripped from the rendered preview and surfaced as a separate interactive Checklist card via `toggle_checklist_item`; whatever taskList items the user keeps when editing in the rich editor are saved back verbatim.
- **No bridge changes.** Description payload to Vikunja is identical (HTML body in `description` field).

---

## [3.3.0] — 2026-05-04

### Added — kanban subtask grouping (UI-side)

- **`panels_editor.py`** — kanban board and smart views (today / upcoming / overdue) now hide subtasks from the main card list and surface them inside a collapsible "↳ Subtasks (done/total)" section at the bottom of each bucket. Implementation:
  - `_collect_child_task_ids(all_tasks)` — single global pass over every bucket's tasks, builds a set of task ids that appear as `related_tasks.subtask` of another task. A subtask sitting in a different bucket than its parent (Vikunja allows that) is still hidden from top-level rendering.
  - `_split_top_and_children(tasks, child_ids)` — partitions a bucket's tasks into top-level cards and children.
  - `_subtasks_section(children)` — renders the collapsed `ui.Section(collapsible=True)` with each child as a normal `_task_card` (kept clickable; opens task detail).
  - Bucket-card title counter changed to `(N top-level)` so the header number matches what's visible. Total-with-children count is shown inside the collapsible section title.
- **No bridge changes.** Vikunja still stores subtasks as plain tasks linked via `task_relations`; the visual nesting is purely client-side, so it works regardless of the Vikunja version, the per-view `show_subtasks` toggle, or whether the user brings an external Vikunja instance.

---

## [3.2.1] — 2026-05-04

### Bridge (`/home/the backend service/routes_tasks.py`) — rollback of v3.2.0 kanban fix

- **`create_subtask` — reverted Step 4** (`POST /api/v1/tasks/{child_id}` with `bucket_id: 0`). The call was confirmed to be a silent no-op against Vikunja's `task_buckets` join table — the API echoes `bucket_id: 0` back in the response but the `task_buckets` row (keyed per `project_view_id`) stays untouched, so the subtask still renders on the kanban board.
- **Investigation summary** — Vikunja's REST API has no path to detach a task from all buckets:
  - `Task.bucket_id` is a virtual response field; the canonical store is the `task_buckets` join table (keyed per `project_view_id`). The `POST /tasks/{id}` bucket-update path requires the new `bucket_id` to belong to the same view, so `0` is silently rejected.
  - There is no `DELETE /projects/{p}/views/{v}/buckets/{b}/tasks/{t}` endpoint.
  - The `Task` model has no `is_subtask` / `hide_on_board` flag.
  - The view-level `bucket_configuration_mode=filter` could in theory exclude subtasks via a filter query, but switching modes wipes all manual bucket assignments — a destructive global change to the user's board.
  - Direct `DELETE FROM task_buckets WHERE task_id=…` against the Vikunja DB does correctly remove the card from the kanban view (verified end-to-end on `tasks.webhostmost.com`: subtask 1226 disappeared from `GET /projects/32/views/176/tasks` and Vikunja did not re-create the row), but the bridge BYO model gives only API access to a user's Vikunja, not DB. Implementing this would break the BYO contract for users who bring an external Vikunja instance.
- **Decision** — accept this as a documented Vikunja-side limitation rather than ship a fake fix. The bridge `create_subtask` docstring now records the full investigation so the next person doesn't re-discover it.
- **End-user workaround** — in Vikunja UI, drag the subtask card off the board or move it to a hidden bucket. This UX is Vikunja-side and not exposed via API.
- Bridge restarted; `/health` returns 200.

### Extension

- **`app.py`** — version bumped to `3.2.1`. Manifest rebuilt via `imperal build .`.

---

## [3.2.0] — 2026-05-04

### Added

- **`handlers_search.py` — `find_task(query)` chat function (read-only).** Searches tasks by title substring via Vikunja `s=` query parameter and returns matching tasks with their integer `task_id`, `project_id`, `done`, `due_date`, `priority`. Closes the "LLM fabricated task_id because the user referred to a task by name" failure mode — system_prompt now mandates `find_task` FIRST whenever an integer task_id is unknown. V16/V17 compliant (`FindTaskParams` is a module-scope BaseModel with detailed Field description).
- **`handlers_crud.py` — `uncomplete_task(task_id)` chat function** (`action_type="write"`, `chain_callable=True`, `effects=["update:task"]`, `event="task.uncompleted"`). Inverse of `complete_task` — POSTs `{done: false, percent_done: 0.0}` to bridge. Closes "accidentally completed a task and can't reopen it from chat".
- **`panels_task.py` — Reopen UI buttons.** Parent task action bar now renders a "Reopen" button (`ui.Call("uncomplete_task", task_id=...)`) instead of "Complete" when the task is `done=true`. Subtask action row now also includes a "Reopen" button (`RotateCcw` icon) before the existing "Delete" button for completed subtasks.

### Changed

- **`system_prompt.txt`** — new "Task name → task_id resolution (REQUIRED)" rule under `## Tool selection`. The LLM must call `find_task(query=...)` before any task-targeted write tool when only the task title is known. Also documents `uncomplete_task` under `## Subtasks`.
- **`skeleton.py`** — `@ext.skeleton("tasks")` TTL reduced from `300` to `30`. Investigated the canonical SDK invalidation API first: `imperal_sdk/skeleton/client.py:25` (`SkeletonClient`) is documented read-only with invariants `I-SKELETON-PROTOCOL-READ-ONLY` and `I-NO-SKELETON-PUT`; the only writer is the kernel `the platform` activity on its tick. Sibling extensions (`notes`, `sql-db`) do not invalidate skeletons either (sql-db invalidates only its local `ctx.cache` schema snapshot). With no SDK invalidation API available, lowering TTL is the canonical option to close the LLM-context staleness window without breaking SDK contract. Panels are already real-time (fetch fresh via `api_get` + `refresh_panels` field on `ActionResult.data`); the 30s TTL affects only LLM-context counters/`recent_tasks`.

### Bridge (`/home/the backend service/routes_tasks.py`)

- **`create_subtask`** — added Step 4: after creating the child task and linking the parent→child relation, the bridge now POSTs `/api/v1/tasks/{child_id}` with `bucket_id: 0` to detach the subtask from the kanban board. Vikunja auto-places every new task into the project's default bucket; subtasks must be link-only — visible inside parent task detail, not as a separate kanban card. The detach call is wrapped in try/except (non-fatal — the relation matters more). The handler now re-fetches the freshly updated child task before returning so the response carries up-to-date `related_tasks` and a cleared `bucket_id`. Backup at `/home/the backend service/routes_tasks.py.bak.pre-3.2.0`. Service restarted; `/health` returns 200.
- **Caveat:** complete subtask hiding on kanban also depends on Vikunja's per-view `show_subtasks` toggle. The bridge fix removes bucket binding, which works on Vikunja versions and views without that toggle.

---

## [3.1.0] — 2026-05-04

### SDK 4.1.0 federal compliance pass

- **`requirements.txt`** — pin bumped `imperal-sdk==4.0.1` → `imperal-sdk==4.1.0`. Worker venv was already on 4.1.0 (last-install-wins from sibling extensions); now declared explicitly. Restores the hard-equality pin invariant.
- **`app.py`** — added a public `NoParams(BaseModel)` for no-arg `@chat.function` handlers (V17 compliance). Replaces three previously separate `_NoParams` classes in `handlers_search.py`, `handlers_structure.py`, `handlers_connection.py` — now a single module-scope class in `app.py`, imported everywhere.
- **`app.py`** — renamed `_imperal_id(ctx)` → `imperal_id_of(ctx)` (public cross-module API; underscore prefix removed). Imports updated in `handlers_crud.py`, `skeleton.py`, `panels.py`, `panels_editor.py`, `panels_task.py`.
- **`app.py`** — `tool_tasks_chat` ChatExtension wrapper description extended to instruct the LLM to "pass user message verbatim as `message`", per federal Runtime Invariant `I-CHAT-FUNCTION-VERBATIM-PARAMS` (2026-05-02).
- **`skeleton.py`** — `skeleton_refresh_tasks(ctx, **_)` → `(ctx)` and `skeleton_alert_tasks(ctx, old, new, **kwargs)` → `(ctx, old, new)`. Universal `**kwargs` sinks removed — federal V22 requires strictly typed lifecycle signatures; after the kernel-side fix for `I-EXT-SYSTEM-TASK-NO-MESSAGE-KWARG`, the defensive sinks are no longer needed.

### Improved

- **`handlers_organize.py`** — descriptions for `assign_task`, `unassign_task`, `add_label`, `remove_label`, `set_due_date`, `set_priority`, `move_to_project`, `move_to_bucket` extended to state explicitly that all IDs are integers and where to obtain them (via `list_buckets` / `list_projects` / etc.). The Pydantic `Field(description=...)` for every ID parameter is also expanded. Closes the failure class "LLM passed a UUID or name where an integer ID was required".
- **`system_prompt.txt`** — new `## ID conventions (CRITICAL — read before any tool call)` section. Strict rule: all Vikunja IDs are positive integers, never UUID / name / slug. Lists every ID field (`task_id`, `parent_task_id`, `project_id`, `bucket_id`, `label_id`, `comment_id`, `assignee_vikunja_user_id`, `vikunja_user_id`) and the standard `list_*` → integer ID → write call flow.

### Cleanup

- Removed dead imports: `is_no_connection_error` from `handlers_organize.py`, `handlers_collab.py`, `handlers_search.py`, `handlers_structure.py` (unused), and `Optional` from `handlers_organize.py` (unused).
- Removed three Nextcloud conflicted-copy files from the repo: `handlers_collab (conflicted copy 2026-05-04 013552).py`, `handlers_crud (conflicted copy 2026-05-03 210133).py`, `panels_editor (conflicted copy 2026-05-03 213503).py`. Added `*conflicted copy*` ignore pattern to `.gitignore`.

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
