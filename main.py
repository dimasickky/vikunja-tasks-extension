"""tasks v2.0.0 · BYO Vikunja kanban manager (each user connects their own)."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
for _m in [k for k in sys.modules if k in (
    "app",
    "handlers_connection",
    "handlers_crud", "handlers_organize", "handlers_structure",
    "handlers_search", "handlers_collab",
    "skeleton",
    "panels", "panels_board", "panels_task",
)]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401

import handlers_connection  # noqa: F401  # connect / disconnect / status
import handlers_crud        # noqa: F401
import handlers_organize    # noqa: F401
import handlers_structure   # noqa: F401
import handlers_search      # noqa: F401
import handlers_collab      # noqa: F401
import skeleton             # noqa: F401
import panels               # noqa: F401  # @ext.panel("sidebar") — connect-first UX
import panels_board         # noqa: F401  # @ext.panel("board") — center default
import panels_task          # noqa: F401  # @ext.panel("task") — center detail
