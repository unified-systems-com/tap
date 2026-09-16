"""Persistent database connections are opt-in, and the opt-in is the server's to make.

`CONN_MAX_AGE` is safe only where the number of processes/threads that can hold a
connection is bounded — the ceiling is (holders x aliases) against `max_connections`.
Under `runserver` (thread-per-request, no cap) that precondition does not hold, and a
hardcoded 600 took the demo-dev stack to 100/100 connections and wedged the collector
with it (tap#460, tap#471).

These tests pin the three properties that keep it from coming back: the default is 0,
both aliases move together, and nothing reads `DEBUG` to decide it.

Spec: `specs/spec-tap-serving.md` req-tap-serving-conn-max-age.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings

from tap.db_aliases import SEARCH_READONLY

_ALIASES = ("default", SEARCH_READONLY)


@pytest.mark.spec("req-tap-serving-conn-max-age-1")
def test_default_closes_connections_at_request_end() -> None:
    """With nothing set, every alias closes its connection at request end."""
    # The suite runs without TAP_DB_CONN_MAX_AGE set, so this is the shipped default.
    assert settings.TAP_DB_CONN_MAX_AGE == 0
    for alias in _ALIASES:
        assert settings.DATABASES[alias]["CONN_MAX_AGE"] == 0, alias


@pytest.mark.spec("req-tap-serving-conn-max-age-1")
def test_both_aliases_move_together_when_raised() -> None:
    """Raising the lever raises it for every alias — one lever, no second copy to drift.

    `search_readonly` spreads `DATABASES["default"]`, so this is structural rather than
    a value that has to be kept in step by hand. Re-imports settings under a patched
    environment because the value is read at import time.
    """
    import tap.settings as tap_settings

    with mock.patch.dict(os.environ, {"TAP_DB_CONN_MAX_AGE": "600"}):
        reloaded = importlib.reload(tap_settings)
        try:
            assert reloaded.TAP_DB_CONN_MAX_AGE == 600
            for alias in _ALIASES:
                assert reloaded.DATABASES[alias]["CONN_MAX_AGE"] == 600, alias
        finally:
            # Restore the module to the ambient environment for every later test.
            importlib.reload(tap_settings)


@pytest.mark.spec("req-tap-serving-conn-max-age-2")
def test_connection_lifetime_is_not_derived_from_debug() -> None:
    """No code path sets connection lifetime from DEBUG.

    `DEBUG` governs error presentation only (req-tap-serving-debug-scope). Static serving
    was already implicitly coupled to it, which is why `DEBUG=false` unstyles the site
    rather than hardening it; routing a second unrelated behaviour through the same flag
    is how that trap gets rebuilt one layer up. Asserted against the source because the
    coupling this forbids is one someone would add later, not one present today.
    """
    source = Path(settings.BASE_DIR, "tap", "settings.py").read_text()
    conn_lines = [
        line
        for line in source.splitlines()
        if "conn_max_age" in line.lower() and not line.lstrip().startswith("#")
    ]
    assert conn_lines, "expected the connection-lifetime assignment to be present"
    assert not any("DEBUG" in line for line in conn_lines), conn_lines


@pytest.mark.spec("req-tap-serving-conn-max-age-3")
def test_the_precondition_is_recorded_beside_the_setting() -> None:
    """The comment states WHY, not just what — so the next reader inherits the reason.

    A bare `conn_max_age=600` reads as a tuning constant. What it actually is, is a claim
    that the holders are bounded; the value was wrong because the claim was never written
    down and so was never checked against the server in front of it.
    """
    source = Path(settings.BASE_DIR, "tap", "settings.py").read_text()
    head = source.split("TAP_DB_CONN_MAX_AGE =")[0]
    assert "BOUNDED" in head
    assert "runserver" in head
