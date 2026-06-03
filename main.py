"""tasks · BYO Vikunja kanban manager (each user connects their own). (build v3.30.0 — users/members → sdl.EntityList)."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in (
    "app", "models_return",
    "handlers_connection",
    "handlers_crud", "handlers_organize", "handlers_structure",
    "handlers_search", "handlers_collab", "handlers_ai",
    "skeleton",
    "panels", "panels_editor", "panels_task",
    "_task_checklist", "_task_create_form",
)]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers_connection  # noqa: F401  # connect / disconnect / status
import handlers_crud        # noqa: F401
import handlers_organize    # noqa: F401
import handlers_structure   # noqa: F401
import handlers_search      # noqa: F401
import handlers_collab      # noqa: F401
import handlers_ai          # noqa: F401
import skeleton             # noqa: F401
import panels               # noqa: F401  # @ext.panel("sidebar") — connect-first UX
import panels_editor         # noqa: F401  # @ext.panel("editor") — center (board + task detail)
