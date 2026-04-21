# Tasks — Imperal Kanban Manager

**Trello-class task manager inside Imperal Platform.** Powered by Vikunja v2.2.2 with the database-backed HA storage. AI-augmented for breakdown, planning, and estimation.

**Slogan:** _«Kanban бесплатный. Плати только за AI-работу.»_

---

## Features

- **Projects (boards)** with nesting, colors, favorites
- **Tasks** — title, description, due/start dates, priority, percent done, assignees
- **Kanban buckets** — drag-to-bucket emulation via "Move to →" dropdown
- **Labels** with colors, attach/detach on tasks
- **Comments** with @mentions
- **Smart views** — Today, Upcoming (7d), Overdue
- **✨ AI** — breakdown, duration estimation, day planning, semantic search, project summary

---

## Monetization — Rule M1

> **Free = deterministic via panel. Paid = LLM parsing or autonomous trigger.**

| Surface | Billing |
|---------|---------|
| Extension panel clicks (CRUD, organize, filters) | **FREE** |
| Webbee chat commands (LLM parses intent) | per-function (see pricing) |
| Automation triggers | per-function |
| ✨ AI tools (breakdown, plan_my_day, etc.) | always billable, regardless of surface |

Implementation — `@ext.panel` duplicates ensure free-in-panel for deterministic ops while `@chat.function` fires billing for chat/automation paths.

---

## Architecture

```
tasks ext (the backend host)  ──▶  the backend service (the backend host:8102)  ──▶  Vikunja :3456
                                     │                                      │
                                     └──── the database (vikunja_db) ◀────────────┘
```

Upstream service (Vikunja) and bridge co-located on the backend host. Data in the database EU master with async slaves in US/IN/SG. Extension communicates with bridge via x-api-key; bridge mints per-request HS256 JWT to act on behalf of the user.

**UX stays inside Imperal Panel** — no external redirects, Vikunja web UI is admin-only.

---

## Secrets (set in Developer Portal)

- `VIKUNJA_BRIDGE_URL` — bridge endpoint (e.g. `http://REDACTED_HOST:8102`)
- `VIKUNJA_BRIDGE_KEY` — API key for extension → bridge

---

## License

LGPL-3.0 (same as other Dimasickky extensions: sql-db, notes).

---

## Links

- **Developer:** [dimasickky](https://github.com/dimasickky)
- **Repo:** [vikunja-tasks-extension](https://github.com/dimasickky/vikunja-tasks-extension)
- **Upstream:** [Vikunja](https://vikunja.io)
- **Platform:** [Imperal Cloud](https://panel.imperal.io)
