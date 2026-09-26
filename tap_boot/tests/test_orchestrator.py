"""run_boot orchestration: auth → population, pre-resolution, on_failure (req-boot-phases/population).

These are fresh-test-DB integration tests — pytest-django builds the DB and the
session `sync_auth` baseline runs first; each `run_boot` then converges it again.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from django.core.management.base import BaseCommand

from tap.plugin_testing import requires_plugins
from tap_auth.actors import BOOTLOADER
from tap_auth.models import Capability
from tap_boot.orchestrator import BootError, run_boot
from tap_boot.profile import BootProfile, FireCollectorStep, RequiredSecret, SeedPluginStep

# A real registered collector key, fired with no credentials in these tests by mocking
# the fire op. These are boot-ORCHESTRATOR tests (FireCollectorStep mechanics), not
# domain tests, so the key points at the NEUTRAL grid_fixtures canary collector — the
# test-fixtures plugin present in every profile that runs the core suite (core_dev /
# test_all) — NOT a third-party domain plugin. Pre-resolution only checks the in-memory
# collector registry (get_collector; see orchestrator._resolve_steps — ZERO grid
# mutation), so a registered key is all that's needed; no grid node, no fedramp install.
# Registered as scope:key = plugin-slug:key (register_collector scope is the plugin slug
# since the 2026-07-02 collector-identity refactor).
_TEST_COLLECTOR = "grid_fixtures:canary"


def _profile(*steps, on_failure="abort", collector_preflight=None, required_secrets=()) -> BootProfile:
    return BootProfile(
        profile_id="test",
        version=1,
        description="test",
        on_failure=on_failure,
        steps=tuple(steps),
        collector_preflight=collector_preflight,
        required_secrets=tuple(required_secrets),
    )


class _FakeJob:
    def __init__(
        self, status: str = "successful", summary: str = "ok", self_test: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self.summary = summary
        self.self_test = self_test or {}
        self.entity_id = None


_FAILING_SELF_TEST = {
    "checks": [
        {"code": "SECRET_VALID", "status": "pass", "message": "secret resolves"},
        {"code": "API_REACHABLE", "status": "fail", "message": "/rate_limit failed: status=401 body=Bad credentials"},
    ]
}


def _mode_aware_fire(self_test_ok: bool = True, full_ok: bool = True):
    """A fake fire_collector_and_await distinguishing preflight from real fires.

    The preflight (req-boot-obs-preflight) self-tests via run_mode="self_test_only"
    before any fire; a failing job carries the persisted self-test checks the
    abort-detail path reads (req-boot-obs-abort-detail).
    """
    calls: list[dict[str, Any]] = []

    def fake_fire(collector, **kwargs):
        calls.append(kwargs)
        if kwargs["run_mode"] == "self_test_only":
            if self_test_ok:
                return True, _FakeJob(summary="ready")
            return False, _FakeJob(status="FAILED", summary="self-test failed", self_test=_FAILING_SELF_TEST)
        if full_ok:
            return True, _FakeJob()
        return False, _FakeJob(status="FAILED", summary="boom", self_test=_FAILING_SELF_TEST)

    return fake_fire, calls


@pytest.mark.django_db
def test_auth_only_standup_syncs_auth():
    run_boot(None)
    assert Capability.objects.exists()
    from django.contrib.auth import get_user_model

    assert get_user_model().objects.filter(tap_builtin_key=BOOTLOADER).exists()


@requires_plugins("validation_sample")  # seeds the fixture's GRIFT bundle — needs it installed
@pytest.mark.django_db
def test_seed_population_runs_and_is_idempotent():
    from tap_grid.models import Entity

    profile = _profile(SeedPluginStep(plugin="validation_sample", enabled=True))
    run_boot(profile)
    after_first = Entity.objects.count()
    assert after_first > 0
    # Re-applying converges declared state without error (req-boot-idempotent).
    run_boot(profile)
    assert Entity.objects.count() == after_first


@requires_plugins("validation_sample")  # the fixture is the valid seed alongside the unknown one
@pytest.mark.django_db
def test_unknown_plugin_aborts_before_any_seed():
    from tap_grid.models import Entity

    profile = _profile(
        SeedPluginStep(plugin="validation_sample", enabled=True),
        SeedPluginStep(plugin="nonexistent_plugin", enabled=True),
    )
    with pytest.raises(BootError, match="No TAP plugin with slug 'nonexistent_plugin'"):
        run_boot(profile)
    # Pre-resolution fails before ANY seed step runs (collector-node reconcile is a
    # phase prelude, not a step) — so validation_sample was NOT seeded. Proof: seeding
    # it now still adds new entities.
    after_abort = Entity.objects.count()
    run_boot(_profile(SeedPluginStep(plugin="validation_sample", enabled=True)))
    assert Entity.objects.count() > after_abort


@pytest.mark.django_db
def test_unknown_collector_key_aborts_before_reconcile():
    from tap_cares.models import Collector

    before = Collector.objects.count()
    profile = _profile(FireCollectorStep(key="plugins.nope:missing", enabled=True))
    with pytest.raises(BootError, match="unknown collector key"):
        run_boot(profile)
    # Pre-resolution validates collector keys against the in-memory registry and
    # aborts BEFORE reconcile_collector_nodes() runs — so no Collector grid node
    # was created/updated (req-boot-population-4, the P1 mutation-ordering fix).
    assert Collector.objects.count() == before


@requires_plugins("validation_sample")  # needs a GRIFT-bearing plugin installed to reach the bundle check
@pytest.mark.django_db
def test_unknown_bundle_name_aborts():
    # A typo'd bundle must fail loud, not become a green boot with missing data.
    profile = _profile(SeedPluginStep(plugin="validation_sample", enabled=True, bundle="no-such-bundle"))
    with pytest.raises(BootError, match="unknown bundle"):
        run_boot(profile)


@pytest.mark.django_db
def test_disabled_unknown_key_does_not_abort():
    # A disabled step is never resolved, so a bogus key behind enabled:false is fine.
    profile = _profile(FireCollectorStep(key="plugins.nope:missing", enabled=False))
    run_boot(profile)  # no raise


@pytest.mark.django_db
def test_fire_collector_step_success(monkeypatch):
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True, run_mode="full")))
    # Preflight self-test first (req-boot-obs-preflight-1), then the real fire.
    assert [c["run_mode"] for c in calls] == ["self_test_only", "full"]
    # No per-step timeout declared -> bootloader default (90s) for the fire;
    # the preflight uses its own await bound, not the step's.
    assert calls[1]["timeout_seconds"] == 90.0


@pytest.mark.django_db
def test_fire_collector_step_uses_declared_timeout(monkeypatch):
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True, timeout_seconds=222)))
    assert calls[1]["run_mode"] == "full"
    assert calls[1]["timeout_seconds"] == 222


@pytest.mark.django_db
def test_fire_collector_abort_on_fire_failure(monkeypatch):
    # Preflight passes; the real fire fails — the abort carries the failing checks.
    fake_fire, calls = _mode_aware_fire(self_test_ok=True, full_ok=False)
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    profile = _profile(
        FireCollectorStep(key=_TEST_COLLECTOR, enabled=True),
        FireCollectorStep(key=_TEST_COLLECTOR, enabled=True),
        on_failure="abort",
    )
    with pytest.raises(BootError, match="on_failure=abort") as excinfo:
        run_boot(profile)
    # 1 preflight (unique key) + 1 fire; stopped after the first fire failure.
    assert [c["run_mode"] for c in calls] == ["self_test_only", "full"]
    # Abort detail names the step and the failing checks (req-boot-obs-abort-detail).
    detail = excinfo.value.detail
    assert detail["failed_step"] == f"fire-collector:{_TEST_COLLECTOR}"
    assert detail["failing_checks"][0]["code"] == "API_REACHABLE"
    assert detail["failing_checks"][0]["collector"] == _TEST_COLLECTOR
    assert "401" in detail["failing_checks"][0]["message"]


@pytest.mark.django_db
def test_fire_collector_continue_collects_all_failures(monkeypatch):
    fake_fire, calls = _mode_aware_fire(self_test_ok=True, full_ok=False)
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    profile = _profile(
        FireCollectorStep(key=_TEST_COLLECTOR, enabled=True),
        FireCollectorStep(key=_TEST_COLLECTOR, enabled=True),
        on_failure="continue",
    )
    with pytest.raises(BootError, match="2 failed step"):
        run_boot(profile)
    # 1 preflight + both fires attempted under on_failure=continue.
    assert [c["run_mode"] for c in calls] == ["self_test_only", "full", "full"]


@pytest.mark.django_db
def test_preflight_failure_aborts_before_any_seed(monkeypatch):
    # The batch verdict fires BEFORE the first seed-plugin step mutates the grid
    # (req-boot-obs-preflight-1/-2): a dead credential costs seconds, not minutes.
    fake_fire, calls = _mode_aware_fire(self_test_ok=False)
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    seeded: list[str] = []

    def _fake_seed(config: Any, **kw: Any) -> list[Any]:
        seeded.append(config.slug)
        return []

    monkeypatch.setattr("tap_plugins.seeding.seed_plugin", _fake_seed)
    profile = _profile(
        SeedPluginStep(plugin="grid_fixtures", enabled=True),
        FireCollectorStep(key=_TEST_COLLECTOR, enabled=True),
        on_failure="abort",
    )
    with pytest.raises(BootError, match="Collector preflight failed") as excinfo:
        run_boot(profile)
    assert seeded == []  # no seed ran
    assert [c["run_mode"] for c in calls] == ["self_test_only"]
    assert excinfo.value.detail["failed_step"] == "preflight"
    assert excinfo.value.detail["failing_checks"][0]["code"] == "API_REACHABLE"


@pytest.mark.django_db
def test_preflight_failure_under_continue_skips_the_fire(monkeypatch):
    # An unready collector's fire step is skipped, not fired (req-boot-obs-preflight-5).
    fake_fire, calls = _mode_aware_fire(self_test_ok=False)
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    profile = _profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True), on_failure="continue")
    with pytest.raises(BootError, match="1 failed step"):
        run_boot(profile)
    assert [c["run_mode"] for c in calls] == ["self_test_only"]  # never fired full


@pytest.mark.django_db
def test_preflight_disabled_by_env_is_loud(monkeypatch, caplog):
    monkeypatch.setenv("TAP_BOOT_POPULATION__COLLECTOR_PREFLIGHT", "false")
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    with caplog.at_level(logging.WARNING):
        run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True)))
    assert [c["run_mode"] for c in calls] == ["full"]  # no self-test ran
    assert any("preflight DISABLED" in r.getMessage() for r in caplog.records)  # req-boot-obs-preflight-4


@pytest.mark.django_db
def test_preflight_disabled_by_profile_field(monkeypatch):
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True), collector_preflight=False))
    assert [c["run_mode"] for c in calls] == ["full"]


@pytest.mark.django_db
def test_failing_checks_echoed(monkeypatch):
    # The check detail — not just the summary — reaches the operator's output
    # (req-boot-obs-abort-detail-1).
    fake_fire, _calls = _mode_aware_fire(self_test_ok=False)
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    lines: list[str] = []
    with pytest.raises(BootError):
        run_boot(_profile(FireCollectorStep(key=_TEST_COLLECTOR, enabled=True)), echo=lines.append)
    assert any("check API_REACHABLE" in line and "401" in line for line in lines)


@pytest.mark.django_db
def test_echo_receives_progress_lines():
    lines: list[str] = []
    run_boot(None, echo=lines.append)
    assert any("Auth phase" in line for line in lines)
    assert any("auth-only standup complete" in line for line in lines)


class TestBootInvocationSelfCheck:
    """run_boot *detects* out-of-band invocation without blocking it (a tripwire).

    Boot mints the capability system, so it runs *before* any gate exists and cannot be
    capability-gated (the un-gateable-layer variant of spec-service-layer-boundary). The
    confirmed-positive context check walks for a live boot-`BaseCommand` frame (a stable
    Django API, not a forgeable caller flag). But it is deliberately a detection, not a
    wall: a hard fail would brick every boot on any heuristic drift while barely
    inconveniencing a real in-process attacker, so an out-of-band call emits a
    `security`-tagged Flaw (handling `observe_continue`) for incident-response routing
    and boot *proceeds*. `TAP_TEST_MODE` carves the test runner (which drives run_boot
    directly and repeatedly); the whole rest of this suite relies on that carve. These
    tests flip it off to exercise the real production path on both sides — the
    out-of-band tripwire, and the clean allowed-command path.
    """

    @pytest.mark.django_db
    def test_out_of_band_call_flaws_and_proceeds(self, settings, caplog):
        # With the test-runner carve disabled, a bare import-and-call — the exact shape
        # of app or plugin code invoking boot out of band — has no boot-command frame.
        # It must NOT brick boot: a security Flaw is recorded and the standup completes.
        settings.TAP_TEST_MODE = False
        with caplog.at_level(logging.WARNING):
            run_boot(None)

        flaw_records = [r for r in caplog.records if getattr(r, "message_code", None) == "FLAW"]
        assert flaw_records, "expected a FLAW record for the out-of-band boot invocation"
        payload = flaw_records[0].message_data
        assert payload["invariant_id"] == "boot_invoked_out_of_band"
        assert "security" in payload["flaw_tags"]
        assert payload["handling"] == "observe_continue"
        # Detection is a tripwire, not a wall — boot still ran to completion.
        assert Capability.objects.exists()

    @pytest.mark.django_db
    def test_allowed_boot_command_frame_emits_no_flaw(self, settings, caplog):
        settings.TAP_TEST_MODE = False

        class _StandInBootCommand(BaseCommand):
            def run(self) -> None:
                run_boot(None)

        # The check keys on the command class's module, not the file the call sits in:
        # make this stand-in present as the real `manage.py boot` command to the stack
        # walk, exactly as Django leaves the command bound as `self` during execute().
        _StandInBootCommand.__module__ = "tap_boot.management.commands.boot"
        with caplog.at_level(logging.WARNING):
            _StandInBootCommand().run()

        flaw_records = [r for r in caplog.records if getattr(r, "message_code", None) == "FLAW"]
        assert not flaw_records, "an allowed boot command must not trip the tripwire"
        assert Capability.objects.exists()


_PAT_ENTRY = RequiredSecret(scope="github_core", key="collector", kind="github_pat", note="read-only PAT")


class _FakeSecret:
    def __init__(self, kind: str) -> None:
        self.kind = kind


def _secret_step(**kwargs: Any) -> FireCollectorStep:
    return FireCollectorStep(key=_TEST_COLLECTOR, enabled=True, secrets=("github_core:collector",), **kwargs)


@pytest.mark.django_db
def test_missing_required_secret_aborts_offline_before_any_live_call(monkeypatch):
    # The offline lane (req-boot-obs-preflight-6 / req-boot-required-secrets-5):
    # an absent declared secret fails the batch verdict before seeding AND before
    # any live self-test network call for the blocked collector.
    from tap_cares.exceptions import SecretNotFoundError

    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)

    def missing(ref):
        raise SecretNotFoundError(f"no secret for {ref.qualified!r}")

    monkeypatch.setattr("tap_cares.secrets.resolve_secret", missing)
    seeded: list[str] = []

    def _fake_seed(config: Any, **kw: Any) -> list[Any]:
        seeded.append(config.slug)
        return []

    monkeypatch.setattr("tap_plugins.seeding.seed_plugin", _fake_seed)
    profile = _profile(
        SeedPluginStep(plugin="grid_fixtures", enabled=True),
        _secret_step(),
        required_secrets=[_PAT_ENTRY],
    )
    with pytest.raises(BootError, match="required secret") as excinfo:
        run_boot(profile)
    assert seeded == []  # aborted before any seed mutated
    assert calls == []  # the blocked collector's live self-test never ran
    missing_entry = excinfo.value.detail["missing_secrets"][0]
    assert missing_entry["ref"] == "github_core:collector"
    assert missing_entry["kind"] == "github_pat"
    assert missing_entry["problem"] == "missing"
    assert "read-only PAT" in missing_entry["note"]


@pytest.mark.django_db
def test_kind_mismatched_secret_fails_offline(monkeypatch):
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    monkeypatch.setattr("tap_cares.secrets.resolve_secret", lambda ref: _FakeSecret(kind="aws_static_access_key"))
    profile = _profile(_secret_step(), required_secrets=[_PAT_ENTRY])
    with pytest.raises(BootError, match="missing/mismatched") as excinfo:
        run_boot(profile)
    assert calls == []
    problem = excinfo.value.detail["missing_secrets"][0]["problem"]
    assert "kind mismatch" in problem and "aws_static_access_key" in problem


@pytest.mark.django_db
def test_present_matching_secret_proceeds_to_live_lane(monkeypatch):
    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)
    monkeypatch.setattr("tap_cares.secrets.resolve_secret", lambda ref: _FakeSecret(kind="github_pat"))
    run_boot(_profile(_secret_step(), required_secrets=[_PAT_ENTRY]))
    # Offline check passed; live self-test then real fire both ran.
    assert [c["run_mode"] for c in calls] == ["self_test_only", "full"]


@pytest.mark.django_db
def test_missing_secret_under_continue_skips_the_fire(monkeypatch):
    from tap_cares.exceptions import SecretNotFoundError

    fake_fire, calls = _mode_aware_fire()
    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", fake_fire)

    def missing(ref):
        raise SecretNotFoundError("absent")

    monkeypatch.setattr("tap_cares.secrets.resolve_secret", missing)
    profile = _profile(_secret_step(), required_secrets=[_PAT_ENTRY], on_failure="continue")
    with pytest.raises(BootError, match="1 failed step"):
        run_boot(profile)
    assert calls == []  # neither self-tested nor fired (req-boot-obs-preflight-5)
