"""Shared pytest fixtures / patches for tasks tests.

Patches ``imperal_sdk.testing.MockContext`` so every ``MockContext()`` call
in the test suite gets a working ``ctx.secrets`` (needed by app.py's
``_auth_headers`` -> ``_bridge_key``) — mirroring what the real kernel
attaches in production after ``ext.secret("vikunja_bridge_key")`` is
configured in Developer Portal -> Secrets. Without this, every bridge call
in a test would raise AttributeError before ever reaching the mocked HTTP
layer. Same pattern as wp-site-connector/tests/conftest.py.

Also makes sure VIKUNJA_BRIDGE_URL is set before app.py is imported by any
test module — app.py raises RuntimeError from _bridge_url() otherwise.
"""
import os

os.environ.setdefault("VIKUNJA_BRIDGE_URL", "https://bridge.test")

import imperal_sdk.testing as _testing_mod
from imperal_sdk.testing import MockContext as _RealMockContext, MockSecretStore


def _mock_context_with_secrets(*args, **kwargs):
    ctx = _RealMockContext(*args, **kwargs)
    ctx.secrets = MockSecretStore({"vikunja_bridge_key": "test-key"})
    return ctx


_testing_mod.MockContext = _mock_context_with_secrets
