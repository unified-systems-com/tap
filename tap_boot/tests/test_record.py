"""Durable boot record (req-boot-obs-record, spec-tap-boot-observability.md).

Fresh-test-DB integration tests around `BootRecord`: written every run (success
AND abort), incremental/abort-safe, schema-described, never load-bearing.
`run_boot` is driven directly with an explicit scratch `base_dir` — the test
runner's normal boots stay record-free via `maybe_boot_record`'s TAP_TEST_MODE
carve, which is also pinned here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tap_boot.orchestrator import BootError, run_boot
from tap_boot.profile import BootProfile, FireCollectorStep
from tap_boot.record import BootRecord, NullBootRecord, maybe_boot_record

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "boot-record.schema.json"
_TEST_COLLECTOR = "grid_fixtures:canary"


def _profile(*steps, on_failure="abort") -> BootProfile:
    return BootProfile(profile_id="test", version=1, description="test", on_failure=on_failure, steps=tuple(steps))


class _FakeJob:
    def __init__(
        self, status: str = "SUCCESSFUL", summary: str = "ok", self_test: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self.summary = summary
        self.self_test = self_test or {}
        self.entity_id = None


def _validate(record: BootRecord) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(record.path.read_text())
    jsonschema.validate(data, json.loads(_SCHEMA_PATH.read_text()))
    return data


@pytest.mark.django_db
def test_success_run_writes_validating_record(tmp_path, monkeypatch):
    def fake_fire(collector, **kwargs):
        return True, _FakeJob(summary="collected 3 nodes")

    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    record = BootRecord("test", base_dir=tmp_path)
    run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True)), record=record)

    data = _validate(record)  # req-boot-obs-record-4: the schema describes reality
    assert data["outcome"] == "ok"
    assert data["profile"] == "test"
    assert data["finished_at"] is not None
    assert [p["phase"] for p in data["phases"]] == ["auth", "grid_infra", "population", "web"]
    assert all(p["status"] == "ok" for p in data["phases"])
    # Preflight entry then the fire entry, in execution order.
    assert [(s["type"], s["status"]) for s in data["steps"]] == [("preflight", "ok"), ("fire-collector", "ok")]
    # The variable resolution is recorded with provenance (req-boot-obs-record-3).
    assert {"section": "population", "key": "collector_preflight", "value": True, "source": "default"} in data[
        "variables"
    ]
    # The latest pointer carries the same run (req-boot-obs-record: stable pointer).
    latest = json.loads((tmp_path / "logs" / "boot" / "latest.boot-record.json").read_text())
    assert latest["run_id"] == data["run_id"]


@pytest.mark.django_db
def test_aborted_run_still_leaves_the_record(tmp_path, monkeypatch):
    failing = {"checks": [{"code": "API_REACHABLE", "status": "fail", "message": "status=401"}]}

    def fake_fire(collector, **kwargs):
        return False, _FakeJob(status="FAILED", summary="auth failed", self_test=failing)

    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    record = BootRecord("test", base_dir=tmp_path)
    with pytest.raises(BootError):
        run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True)), record=record)

    data = _validate(record)  # req-boot-obs-record-1/-2: abort leaves the evidence
    assert data["outcome"] == "aborted"
    assert data["abort"]["domain"] == "boot"
    assert data["abort"]["failed_step"] == "preflight"
    assert data["abort"]["failing_checks"][0]["code"] == "API_REACHABLE"
    population = [p for p in data["phases"] if p["phase"] == "population"][0]
    assert population["status"] == "failed"
    assert data["steps"][-1]["failing_checks"][0]["message"] == "status=401"


@pytest.mark.django_db
def test_record_write_failure_never_breaks_boot(tmp_path):
    # base_dir under a FILE ⇒ every mkdir/write fails; the record disables itself
    # and boot proceeds — observability must never take the standup down.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("occupied")
    record = BootRecord("test", base_dir=blocker)
    record.record_step({"type": "preflight", "status": "ok"})
    with record.phase("auth"):
        pass
    record.finish_ok()  # no raise, nothing written
    assert not record.path.exists()


def test_maybe_boot_record_is_null_under_test_mode(settings):
    # The test runner's repeated boots must not litter the worktree's logs/boot/.
    settings.TAP_TEST_MODE = True
    assert isinstance(maybe_boot_record("x"), NullBootRecord)
    assert not isinstance(maybe_boot_record("x"), BootRecord)
