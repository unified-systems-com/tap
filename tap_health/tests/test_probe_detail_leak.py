"""Probe `detail` must never carry a raw exception message — tap#546.

req-tap-health-exposure-6 / req-tap-health-service-3 (spec-tap-health-v0.md).

Sibling of `test_report_projection.py`, and load-bearing for the same reason: it
asserts what does **not** escape. The projection test guards the boundary between
the rich report and the coarse scorecard; these guard the boundary *upstream* of
both — what a probe is allowed to put into `detail` in the first place.

Why upstream rather than at a projection: since `req-tap-health-exposure-6` the
image `HEALTHCHECK` runs `manage.py health --set readiness` every 120s, and Docker
concatenates each run's stdout into `State.Health.Log`, where `docker inspect` and
any container-state-scraping monitoring agent reads it. The CLI is a trusted
surface and deliberately prints `full()` — the spawn gate and every human
debugging a boot depend on that, so narrowing the CLI's projection is not the fix.
Bounding what the probe *puts in* `detail` is: it fixes every sink at once (the
Health.Log entry, the CI log the spawn gate writes, and any future authorized API)
rather than one of them.

Two tests, two jobs:

* `test_*_detail_is_bounded_*` — behaviour. A probe fails with an exception whose
  message carries a canary standing in for credential material; the canary must
  not appear anywhere in what the health check emits, while the probe must remain
  identifiable (name + stable `code`), because a health check whose failure says
  nothing is the defect `req-tap-health-exposure-6` chose `readiness` to avoid.
* `test_no_probe_passes_a_caught_exception_*` — enforcement. `str(exc)` is the
  convenient thing to reach for in a new probe, so the rule is checked rather than
  agreed. The guard carries a positive control: a detector that cannot fire is
  itself a presence test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tap_health.results import HealthReport, ProbeOutcome, exception_detail

# Stands in for anything that must not sit in container metadata: a host, a role,
# a DSN fragment. Deliberately not spelled like a credential — the point is that
# NOTHING from an exception message escapes, not that a pattern is filtered.
_LEAK_CANARY = "canary-3f9c1d-must-not-escape"
_LEAKY_MESSAGE = (
    'connection to server at "db" (172.18.0.2), port 5432 failed: '
    f'FATAL: role "{_LEAK_CANARY}" does not exist'
)


class _CanaryError(Exception):
    """An exception whose *message* must never reach a probe's `detail`."""


def _boom(*args: object, **kwargs: object) -> object:
    raise _CanaryError(_LEAKY_MESSAGE)


# --- behaviour: the canary does not escape, the probe stays identifiable -------


@pytest.mark.spec("req-tap-health-exposure-6")
def test_exception_detail_keeps_the_type_and_drops_the_message():
    # The one derivation every probe routes through (remedy 1: derive once).
    detail = exception_detail(_CanaryError(_LEAKY_MESSAGE))
    assert detail == "_CanaryError"
    assert _LEAK_CANARY not in detail


# No `django_db` on the next three: each patches the backend call to raise before
# any database work happens, so the test needs no database — and patching
# `connection.cursor` under `django_db` would race the fixture teardown that
# releases the test's savepoint through that very method.
@pytest.mark.spec("req-tap-health-exposure-6")
def test_db_probe_detail_is_bounded_when_the_connection_fails(monkeypatch):
    from tap_health.probes import probe_db
    from tap_health.results import ProbeStatus

    monkeypatch.setattr("django.db.connection.cursor", _boom)
    result = probe_db()

    assert result.status is ProbeStatus.UNHEALTHY
    # Still useful: the operator learns WHICH probe failed and why, by code.
    assert result.code == "db.query_failed"
    assert result.detail == "_CanaryError"
    assert _LEAK_CANARY not in json.dumps([result.detail, result.context])


@pytest.mark.spec("req-tap-health-exposure-6")
def test_cache_probe_detail_is_bounded_when_the_backend_fails(monkeypatch):
    from tap_health.probes import probe_cache
    from tap_health.results import ProbeStatus

    monkeypatch.setattr("django.core.cache.cache.set", _boom)
    result = probe_cache()

    assert result.status is ProbeStatus.UNHEALTHY
    assert result.code == "cache.unavailable"
    # Pin the identity of the exception that was caught: without this the canary
    # assertion below would also pass if some OTHER exception had been raised.
    assert result.detail == "_CanaryError"
    assert _LEAK_CANARY not in json.dumps([result.detail, result.context])


@pytest.mark.django_db
@pytest.mark.spec("req-tap-health-exposure-6")
def test_migrations_probe_detail_is_bounded_when_the_check_fails(monkeypatch):
    from tap_health.probes import probe_migrations
    from tap_health.results import ProbeStatus

    monkeypatch.setattr(
        "django.db.migrations.executor.MigrationExecutor.migration_plan",
        _boom,
    )
    result = probe_migrations()

    assert result.status is ProbeStatus.UNHEALTHY
    assert result.code == "migrations.check_failed"
    assert result.detail == "_CanaryError"
    assert _LEAK_CANARY not in json.dumps([result.detail, result.context])


@pytest.mark.spec("req-tap-health-exposure-6")
def test_queue_probe_detail_is_bounded_when_introspection_fails(monkeypatch):
    from django.db import DEFAULT_DB_ALIAS, connections

    from tap_health.probes import probe_queue
    from tap_health.results import ProbeStatus

    monkeypatch.setattr(
        connections[DEFAULT_DB_ALIAS].introspection,
        "table_names",
        _boom,
    )
    result = probe_queue()

    # `unknown`, never `unhealthy` — the non-critical rule is untouched here.
    assert result.status is ProbeStatus.UNKNOWN
    assert result.code == "queue.indeterminate"
    assert result.detail == "_CanaryError"
    assert _LEAK_CANARY not in json.dumps([result.detail, result.context])


@pytest.mark.spec("req-tap-health-exposure-6")
def test_service_isolation_detail_is_bounded_when_a_probe_raises():
    # The runner's own catch-all is the broadest path of the lot: it produces the
    # `detail` for ANY probe that raises, including one this repo did not write.
    from tap_health.registry import HealthProbe
    from tap_health.service import PROBE_RAISED_CODE, _run_one

    outcome = _run_one(
        HealthProbe(
            name="canary",
            probe=_boom,
            sets=("readiness",),
            group="core",
            critical=True,
        )
    )

    assert outcome.result.code == PROBE_RAISED_CODE
    assert outcome.result.detail == "probe raised: _CanaryError"
    assert _LEAK_CANARY not in json.dumps([outcome.result.detail, outcome.result.context])


@pytest.mark.spec("req-tap-health-exposure-6")
def test_canary_would_escape_the_full_projection_if_a_probe_leaked_it():
    # Positive control for the tests above: proves `full()` does NOT strip a leaked
    # message, so the assertions there are earned by the probe, not by the
    # projection. This is exactly why the fix had to land upstream of `full()`.
    from tap_health.results import ProbeResult

    leaked = ProbeResult.unhealthy("db.query_failed", detail=_LEAKY_MESSAGE)
    report = HealthReport(outcomes=(ProbeOutcome("db", "core", True, leaked),), selection="readiness")
    assert _LEAK_CANARY in json.dumps(report.full())


@pytest.mark.django_db
@pytest.mark.spec("req-tap-health-exposure-6")
def test_healthcheck_stdout_carries_no_exception_message(monkeypatch, capsys):
    """End-to-end over the exact argv the image `HEALTHCHECK` runs.

    The HEALTHCHECK runs WITHOUT `--json`, so `_write_human` — not the JSON dump —
    is the code path that writes the CLI's **stdout**, which Docker persists into
    `State.Health.Log`.

    Scope, stated precisely because the name would otherwise claim more than the
    test proves: this asserts the CLI's stdout projection only. It deliberately
    does NOT assert on stderr. The probes' own `logger.warning(..., exc)` lines
    reach stderr, Docker captures stderr into `Health.Log` too, and that path is
    still open — tap#681, and pinned by the test below. Asserting on stderr here
    would either fail for a reason this change is not responsible for, or pass
    only because pytest's capture does not see a handler bound to the real stderr
    at dictConfig time — a pass for the wrong reason.
    """
    from django.core.management import call_command

    monkeypatch.setattr("django.db.connection.cursor", _boom)
    with pytest.raises(SystemExit):
        call_command("health", "--set", "readiness")

    emitted = capsys.readouterr().out
    # Vacuity guard: prove the output was actually observed before trusting an
    # absence in it, and that the check stayed USEFUL — the failing probe is still
    # named, with its stable code.
    assert "db" in emitted
    assert "db.query_failed" in emitted
    assert _LEAK_CANARY not in emitted


@pytest.mark.django_db
@pytest.mark.spec("req-tap-health-exposure-6")
def test_known_gap_probe_logging_still_carries_the_exception_message(monkeypatch, caplog):
    """Pin the gap this change does NOT close, so it stays observable — tap#681.

    Bounding `detail` fixes the probe result. It does not touch the probe's log
    line, which still carries the full exception; `tap/logging.py` binds the one
    console handler to stderr, and Docker captures stderr into `State.Health.Log`
    alongside stdout. Recording that as prose in a spec is how a known gap becomes
    a forgotten one, so it is recorded as an assertion instead.

    This test is expected to FAIL when tap#681 lands. That is the point: whoever
    fixes the log path is forced back here to retire the pin, rather than leaving
    a spec paragraph claiming a gap that no longer exists.
    """
    import logging

    from tap_health.probes import probe_db

    monkeypatch.setattr("django.db.connection.cursor", _boom)
    with caplog.at_level(logging.WARNING, logger="tap_health.probes"):
        probe_db()

    assert any(_LEAK_CANARY in record.getMessage() for record in caplog.records), (
        "The probe log line no longer carries the exception message. If tap#681 was "
        "fixed, delete this pin and the 'Known gap' paragraph in spec-tap-health-v0.md."
    )


# --- enforcement: no probe may hand a caught exception to a ProbeResult --------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_WRAPPER = "exception_detail"


def _probe_source_files() -> list[Path]:
    """Every first-party module that constructs a `ProbeResult`.

    Discovered rather than listed, so a probe module added later is covered on the
    day it lands — the reintroduction this guard exists to stop.
    """
    files: list[Path] = []
    for app_dir in sorted(_REPO_ROOT.glob("tap_*")):
        if not app_dir.is_dir():
            continue
        for path in sorted(app_dir.rglob("*.py")):
            if "tests" in path.parts:
                continue
            if "ProbeResult" in path.read_text(encoding="utf-8"):
                files.append(path)
    return files


def _sanctioned_reference_ids(handler: ast.ExceptHandler) -> set[int]:
    """`id()`s of Name nodes sitting in a context where touching `exc` is allowed.

    Three sanctioned contexts, and no others:

    * `exception_detail(exc)` — the single authored derivation of a bounded detail.
    * `logger.<level>(..., exc)` — the application log is a trusted sink and the
      full exception is what an operator debugging a boot actually needs. (That
      this ALSO reaches stderr, and so `State.Health.Log`, is the separate gap
      tracked as tap#681 — a logging decision, not a probe-detail one.)
    * `raise … from exc` / `raise exc` — re-raising does not project anything.
    """
    sanctioned: set[int] = set()

    def mark(node: ast.AST) -> None:
        sanctioned.update(id(n) for n in ast.walk(node) if isinstance(n, ast.Name))

    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == _ALLOWED_WRAPPER:
                mark(node)
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "logger":
                mark(node)
        elif isinstance(node, ast.Raise):
            for part in (node.exc, node.cause):
                if part is not None:
                    mark(part)
    return sanctioned


def _exception_leaks(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (exception name, lineno) for each unsanctioned use of a caught exception.

    The rule constrains the **source**, not the sink: inside an `except … as exc`
    handler of a module that builds probe results, a reference to `exc` is a
    finding unless it sits in one of the sanctioned contexts above.

    Phrasing it this way rather than as "an exception reaching a `ProbeResult(...)`
    call" is deliberate, and closes two bypasses an AI-review seat raised on
    `PR# 682 - tap`: `detail = str(exc)` followed by `detail=detail` (the value
    launders through a local), and a module-aliased `PR.unhealthy(…)` (the call no
    longer spells `ProbeResult`). Both evade a sink-matching rule; neither evades
    this one, because the exception's *message* is never derived at all.
    """
    findings: list[tuple[str, int]] = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name:
            continue
        sanctioned = _sanctioned_reference_ids(handler)
        for sub in ast.walk(handler):
            if isinstance(sub, ast.Name) and sub.id == handler.name and id(sub) not in sanctioned:
                findings.append((handler.name, sub.lineno))
    return findings


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_leak_detector_fires_on_a_known_bad_shape():
    # Positive control. A guard that cannot fire proves nothing about the files it
    # scans; this pins the detector before it is trusted below.
    bad = ast.parse(
        """
try:
    go()
except Exception as exc:
    ProbeResult.unhealthy("x.failed", detail=str(exc))
"""
    )
    assert _exception_leaks(bad), "detector failed to flag detail=str(exc)"

    also_bad = ast.parse(
        """
try:
    go()
except Exception as exc:
    ProbeResult.unknown("x.failed", detail=f"broke: {exc}")
"""
    )
    assert _exception_leaks(also_bad), "detector failed to flag an f-string interpolation"

    # The two bypasses an AI-review seat raised on PR# 682 - tap. Both defeat a
    # rule that matches the ProbeResult call; neither defeats a rule that forbids
    # deriving the message at all.
    laundered_through_a_local = ast.parse(
        """
try:
    go()
except Exception as exc:
    message = str(exc)
    ProbeResult.unhealthy("x.failed", detail=message)
"""
    )
    assert _exception_leaks(laundered_through_a_local), "detector failed to flag a local alias"

    module_aliased_call = ast.parse(
        """
try:
    go()
except Exception as exc:
    PR.unhealthy("x.failed", detail=str(exc))
"""
    )
    assert _exception_leaks(module_aliased_call), "detector failed to flag an aliased ProbeResult"

    # `context` is projected by `full()` exactly as `detail` is.
    leaked_via_context = ast.parse(
        """
try:
    go()
except Exception as exc:
    ProbeResult.unhealthy("x.failed", context={"error": str(exc)})
"""
    )
    assert _exception_leaks(leaked_via_context), "detector failed to flag a leak through context"

    good = ast.parse(
        """
try:
    go()
except Exception as exc:
    logger.warning("[1a2b] x failed: %s", exc)
    raise RuntimeError("wrapped") from exc
"""
    )
    assert not _exception_leaks(good), "detector flagged a sanctioned logger/raise use"

    wrapped = ast.parse(
        """
try:
    go()
except Exception as exc:
    ProbeResult.unhealthy("x.failed", detail=exception_detail(exc))
"""
    )
    assert not _exception_leaks(wrapped), "detector flagged the sanctioned wrapper"


@pytest.mark.spec("req-tap-health-exposure-6")
def test_no_probe_passes_a_caught_exception_into_a_probe_result():
    scanned = _probe_source_files()
    assert scanned, "found no ProbeResult-constructing modules to scan"

    offenders: list[str] = []
    for path in scanned:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, lineno in _exception_leaks(tree):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} passes `{name}` into a ProbeResult")

    assert not offenders, (
        "A caught exception's message must not be derived in a probe module — it rides "
        "every projection of the result, including the 120s HEALTHCHECK entry in "
        "State.Health.Log (tap#546). Use detail=exception_detail(exc) for the bounded "
        "type name; pass the exception itself only to logger.<level>(...) or `raise ... "
        "from exc`. Offenders:\n  " + "\n  ".join(offenders)
    )
