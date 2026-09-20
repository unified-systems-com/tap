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


@pytest.mark.django_db
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


@pytest.mark.django_db
@pytest.mark.spec("req-tap-health-exposure-6")
def test_cache_probe_detail_is_bounded_when_the_backend_fails(monkeypatch):
    from tap_health.probes import probe_cache
    from tap_health.results import ProbeStatus

    monkeypatch.setattr("django.core.cache.cache.set", _boom)
    result = probe_cache()

    assert result.status is ProbeStatus.UNHEALTHY
    assert result.code == "cache.unavailable"
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
    assert _LEAK_CANARY not in json.dumps([result.detail, result.context])


@pytest.mark.django_db
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
    is the code path whose output Docker persists into `State.Health.Log`. This
    exercises that path.
    """
    from django.core.management import call_command

    monkeypatch.setattr("django.db.connection.cursor", _boom)
    with pytest.raises(SystemExit):
        call_command("health", "--set", "readiness")

    out = capsys.readouterr()
    emitted = out.out + out.err
    assert _LEAK_CANARY not in emitted
    # The check must stay useful: the failing probe is still named, with its code.
    assert "db" in emitted
    assert "db.query_failed" in emitted


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


def _exception_leaks(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (exception name, lineno) for each caught exception handed to a ProbeResult.

    A reference is permitted only inside an `exception_detail(...)` call, which is
    the single authored derivation of a bounded `detail`.
    """
    findings: list[tuple[str, int]] = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name:
            continue
        for node in ast.walk(handler):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "ProbeResult":
                continue
            wrapped: set[int] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == _ALLOWED_WRAPPER:
                    wrapped.update(id(inner) for inner in ast.walk(sub) if isinstance(inner, ast.Name))
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == handler.name and id(sub) not in wrapped:
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

    good = ast.parse(
        """
try:
    go()
except Exception as exc:
    ProbeResult.unhealthy("x.failed", detail=exception_detail(exc))
"""
    )
    assert not _exception_leaks(good), "detector flagged the sanctioned wrapper"


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
        "A caught exception's message must not reach a probe `detail` — it rides every "
        "projection, including the 120s HEALTHCHECK entry in State.Health.Log (tap#546). "
        "Wrap it: detail=exception_detail(exc). Offenders:\n  " + "\n  ".join(offenders)
    )
