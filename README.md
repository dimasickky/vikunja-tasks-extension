# Tasks — Imperal Kanban Manager

**Trello-class task manager inside Imperal Platform.** Powered by Vikunja, with AI augmentation for breakdown, planning, and estimation.

**Slogan:** _"Kanban is free. Only pay for the AI work."_

---

## Features

- **Projects (boards)** with nesting, colors, favorites
- **Tasks** — title, description, due/start dates, priority, percent done, assignees
- **Kanban buckets** — drag-to-bucket emulation via "Move to →" dropdown
- **Labels** with colors, attach/detach on tasks
- **Comments** with @mentions
- **Attachments** — attach files/photos to tasks (Vikunja stores them, 20MB cap)
- **Live notifications** — get pinged in Imperal (bell/telegram) when assigned or commented on, via a webhook auto-registered on your own Vikunja
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
Tasks extension  ──▶  backend API  ──▶  Vikunja
```

The extension talks to a backend API, which in turn talks to a Vikunja instance on
the user's behalf. The extension authenticates to the backend with an API key; the
backend holds the per-user credentials needed to act against Vikunja.

**UX stays inside Imperal Panel** — no external redirects; the Vikunja web UI is not used by end users.

---

## Secrets (set in Developer Portal)

- `VIKUNJA_BRIDGE_URL` — backend API endpoint (e.g. `http://your-backend-host:PORT`)
- `VIKUNJA_BRIDGE_KEY` — API key for the extension → backend

---

## License

LGPL-3.0 (same as other Dimasickky extensions: sql-db, notes).

---

## Links

- **Developer:** [dimasickky](https://github.com/dimasickky)
- **Repo:** [vikunja-tasks-extension](https://github.com/dimasickky/vikunja-tasks-extension)
- **Upstream:** [Vikunja](https://vikunja.io)
- **Platform:** [Imperal Cloud](https://panel.imperal.io)
