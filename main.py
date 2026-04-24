"""tasks v2.0.0 · Vikunja-backed kanban + project manager.

SDK v2.0.0 / Webbee Single Voice — class-based tool surface, no ChatExtension,
no per-extension system prompt. Webbee Narrator composes all user-facing prose
from the typed output schemas in ``schemas.py``.
"""
from __future__ import annotations

import os
import sys

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

for _m in [
    k for k in list(sys.modules)
    if k in (
        "app", "tools", "schemas",
        "skeleton",
        "panels", "panels_board", "panels_task",
    )
]:
    del sys.modules[_m]

from app import ext  # noqa: F401,E402  (loader discovers this)

import skeleton      # noqa: F401,E402
import panels        # noqa: F401,E402  (sidebar — left slot)
import panels_board  # noqa: F401,E402  (board — center default)
import panels_task   # noqa: F401,E402  (task detail — center)
