"""Tests for tap_cares.collectors.run_with_ceiling.

TAP-IMPLEMENTS: req-tap-cares-collector-call-ceiling@83395eb1af71/b8a037c306e2 (enforcement) — the
    normal return, the callable's own exception, the ceiling actually returning control before the
    hang resolves, the zero-ceiling short-circuit, and the abandoned thread's name/daemon status
    are each asserted here.
"""

import threading
import time

import pytest

from tap_cares.collectors import CeilingExceeded, run_with_ceiling


def test_returns_result_within_ceiling():
    assert run_with_ceiling(lambda: 42, ceiling=5.0) == 42


def test_reraises_the_callables_own_exception():
    def _boom():
        raise ValueError("upstream said no")

    with pytest.raises(ValueError, match="upstream said no"):
        run_with_ceiling(_boom, ceiling=5.0)


def test_raises_ceiling_exceeded_and_returns_control_promptly():
    still_blocked = threading.Event()

    def _hang():
        still_blocked.wait(timeout=5.0)  # outlives the ceiling below on purpose
        return "should never be observed by the caller"

    started = time.monotonic()
    with pytest.raises(CeilingExceeded):
        run_with_ceiling(_hang, ceiling=0.05)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, "the caller must regain control at the ceiling, not wait for the thread"
    still_blocked.set()  # let the abandoned thread finish so it doesn't outlive the test


def test_non_positive_ceiling_raises_immediately_without_calling():
    calls = []
    with pytest.raises(CeilingExceeded, match="deadline passed"):
        run_with_ceiling(lambda: calls.append(1), ceiling=0.0)
    assert calls == [], "a ceiling of zero must never invoke the callable"


def test_abandoned_thread_carries_the_caller_supplied_name():
    still_blocked = threading.Event()

    def _hang():
        still_blocked.wait(timeout=5.0)

    with pytest.raises(CeilingExceeded):
        run_with_ceiling(_hang, ceiling=0.05, name="my-caller")

    named = [t for t in threading.enumerate() if t.name == "my-caller"]
    assert named and all(t.daemon for t in named)
    still_blocked.set()
