"""run_boot orchestration: auth → population, pre-resolution, on_failure (req-boot-phases/population).

These are fresh-test-DB integration tests — pytest-django builds the DB and the
session `sync_auth` baseline runs first; each `run_boot` then converges it again.
"""

from __future__ import annotations

import logging
from pathlib import Path
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
# core_ci) — NOT a third-party domain plugin. Pre-resolution only checks the in-memory
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


@pytest.mark.spec("req-boot-profile-6")
@pytest.mark.django_db
def test_step_less_profile_reconciles_collector_nodes_and_fires_none(monkeypatch):
    # core_dev's shape: plugins installed, no population steps. Its collectors must still
    # reach the grid, or nothing can run them from there (tap#1010).
    from tap_cares.models import Collector

    def no_fire(*args, **kwargs):
        raise AssertionError("a step-less profile must fire no collector")

    monkeypatch.setattr("tap_cares.services.fire_collector_and_await", no_fire)
    lines: list[str] = []
    run_boot(_profile(), echo=lines.append)
    assert Collector.objects.filter(collector_registry=_TEST_COLLECTOR).exists()
    assert any("standup complete" in line and "auth-only" not in line for line in lines)


@pytest.mark.spec("req-boot-profile-6")
@pytest.mark.django_db
def test_allow_empty_standup_writes_no_collector_node():
    from tap_cares.models import Collector

    before = Collector.objects.count()
    run_boot(None)
    assert Collector.objects.count() == before


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


@pytest.mark.spec("req-boot-phases-5")
@pytest.mark.django_db
class TestCoreVocabulary:
    """aws-build Q63: every boot imports core's dimension vocabulary first, once per grid."""

    CORE = {"tap.meta", "tap.graph", "tap_cares"}

    def _core_rows(self) -> set[str]:
        from tap_grid.models import Dimension

        return set(Dimension.objects.live().filter(name__in=self.CORE).values_list("name", flat=True))  # type: ignore[misc]

    def test_a_fresh_boot_leaves_core_dimension_rows(self) -> None:
        run_boot(None)
        assert self._core_rows() == self.CORE

    def test_a_re_boot_does_not_re_import(self) -> None:
        from tap_grid.models import Batch, Dimension

        run_boot(None)
        dimensions, batches = Dimension.objects.count(), Batch.objects.count()
        lines: list[str] = []
        run_boot(None, echo=lines.append)
        assert (Dimension.objects.count(), Batch.objects.count()) == (dimensions, batches)
        assert any("Core vocabulary:" in line and "already present" in line for line in lines)

    def test_it_runs_before_any_population_step(self, monkeypatch) -> None:
        import tap_boot.orchestrator as orchestrator

        order: list[str] = []
        real = orchestrator._phase_core_vocabulary

        def core(say: Any) -> None:
            order.append("core")
            real(say)

        def population(*args: Any, **kwargs: Any) -> None:
            order.append("population")

        monkeypatch.setattr(orchestrator, "_phase_core_vocabulary", core)
        monkeypatch.setattr(orchestrator, "_phase_population", population)
        run_boot(_profile(SeedPluginStep(plugin="grid_fixtures", enabled=True)))
        assert order == ["core", "population"]

    def test_a_plugin_seed_stamped_tap_meta_still_imports(self) -> None:
        import uuid

        from tap_grid.grift import grift_import

        run_boot(None)
        node_id = str(uuid.uuid7())
        doc = {
            "metadata": {"grift_version": "0"},
            "_reserved": {},
            "batches": [
                {
                    "batch_entity": {"entity_id": str(uuid.uuid7()), "entity_type": "batch", "name": "plugin seed", "dimensions": {}},
                    "batch_node": {"source": "plugins.example", "name": "plugin seed", "description": "d"},
                    "nodes": [
                        {
                            "entity": {"entity_id": node_id, "entity_type": "dimension", "name": "tap.test.plugin-key", "dimensions": {"tap.meta": "dimension"}},
                            "node": {"name": "tap.test.plugin-key", "description": "d"},
                        }
                    ],
                    "edges": [],
                }
            ],
        }
        result = grift_import(doc)
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]


_FIXTURES = Path(__file__).resolve().parents[2] / "tap_plugins" / "tests" / "fixtures"
_FIXTURE_PLUGIN_ROOT = _FIXTURES / "validation_sample" / "tap_plugin" / "validation_sample"
_FIXTURE_DIMENSION_BATCH = "01a1d2db-fead-711e-9523-152c4218b1e2"
_CORE_TAP_META_ID = "01a1d14c-d80b-725d-8002-eb0b3e272f1d"  # tap_grid/data/dimensions.grift.json
_FIXTURE_DIMENSION = "01a1d2db-fead-711e-9523-152d3ea4555d"  # tap.fixture


@pytest.mark.spec("req-boot-phases-5")
@pytest.mark.spec("req-tap-plugin-manifest-v0-grift-11")
@pytest.mark.django_db
class TestPluginDimensionVocabulary:
    """unified-systems-com/tap#1188 (aws-build Q67c): the vocabulary phase imports every installed
    plugin's `[grift] dimension` bundle after core's, whether or not the profile seeds the plugin."""

    @pytest.fixture
    def installed(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        """The validation_sample fixture plugin as an installed plugin no profile seeds."""
        from types import SimpleNamespace

        import tap_plugins.seeding as seeding
        from tap_plugins.manifest import load_manifest

        real = seeding.all_tap_plugins()

        def _is_sample(config: Any) -> bool:
            manifest = getattr(config, "manifest", None)
            return manifest is not None and manifest.slug == "validation_sample"

        if any(_is_sample(c) for c in real):
            # core_ci installs validation_sample for real: the test database's own vocabulary
            # import (the same import_dimension_vocabulary boot runs) already holds its rows.
            present = next(c for c in real if _is_sample(c))
            monkeypatch.setattr(present, "really_installed", True, raising=False)
            return present
        added = SimpleNamespace(
            manifest=load_manifest(_FIXTURE_PLUGIN_ROOT), name="validation_sample", really_installed=False
        )
        monkeypatch.setattr(seeding, "all_tap_plugins", lambda: [*real, added])
        return added

    def _fixture_rows(self) -> list[str]:
        from tap_grid.models import Dimension

        return list(Dimension.objects.filter(entity_id=_FIXTURE_DIMENSION).values_list("name", flat=True))  # type: ignore[misc]

    def test_core_comes_first_then_plugins_in_installed_apps_order(self, installed: Any) -> None:
        from tap_plugins.seeding import all_tap_plugins, dimension_bundles

        bundles = dimension_bundles()
        assert bundles[0].slug == "tap_grid"
        declaring = [c.manifest for c in all_tap_plugins() if c.manifest is not None]
        expected = [m.slug for m in declaring if any(e.name == "dimension" for e in m.grift)]
        assert [b.slug for b in bundles[1:]] == expected
        # Last when the test adds it; wherever INSTALLED_APPS puts it when core_ci installs it.
        assert "validation_sample" in [b.slug for b in bundles[1:]]

    def test_a_plugin_installed_but_not_seeded_gets_its_dimension_rows(self, installed: Any) -> None:
        from tap_grid.dimension_names import resolve

        if not installed.really_installed:
            # Only provable where the test database did not already import it (the plugin is
            # installed only for this test); under core_ci the harness import got there first.
            assert self._fixture_rows() == []
        run_boot(None)  # an auth-only standup: no profile, no seed-plugin step at all
        assert self._fixture_rows() == ["tap.fixture"]
        assert str(resolve("tap.fixture")) == _FIXTURE_DIMENSION

    def test_boot_is_idempotent_on_re_run(self, installed: Any) -> None:
        from tap_grid.models import Batch, Dimension

        run_boot(None)
        counts = (Dimension.all_objects.count(), Batch.all_objects.count())
        lines: list[str] = []
        run_boot(None, echo=lines.append)
        assert (Dimension.all_objects.count(), Batch.all_objects.count()) == counts
        assert any("Core vocabulary:" in line and "nothing written" in line for line in lines), lines

    def test_the_plugins_own_seed_step_skips_the_bundle_already_imported(self, installed: Any) -> None:
        from tap_plugins.seeding import seed_plugin

        run_boot(None)
        outcomes = seed_plugin(installed, actor=None, bundle_name="dimension")
        assert [o.ok for o in outcomes] == [True]
        result = outcomes[0].result
        assert result is not None
        assert [b.batch_entity_id for b in result.skipped_batches] == [_FIXTURE_DIMENSION_BATCH]
        assert self._fixture_rows() == ["tap.fixture"]

    @pytest.mark.parametrize(
        "breakage", ["unreadable", "an-edge", "another-type", "a-bad-node", "a-retirement", "batches-not-a-list", "a-core-id"]
    )
    def test_a_failing_bundle_aborts_the_boot_naming_it(
        self, installed: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, breakage: str
    ) -> None:
        import json

        import tap_plugins.seeding as seeding

        document = json.loads((_FIXTURE_PLUGIN_ROOT / "grift" / "dimension.grift.json").read_text(encoding="utf-8"))
        batch = document["batches"][0]
        batch["batch_entity"]["entity_id"] = "01a1d2db-fead-711e-9523-0000000000aa"  # unseen
        bad = tmp_path / "dimension.grift.json"
        if breakage == "unreadable":
            bad.write_text("{ not json", encoding="utf-8")
        else:
            if breakage == "an-edge":
                batch["edges"] = [{"entity": {}, "edge": {}}]
            elif breakage == "another-type":
                batch["nodes"][0]["entity"]["entity_type"] = "grid_fixtures__node"
            elif breakage == "batches-not-a-list":
                document["batches"] = 1  # valid JSON, malformed GRIFT: a named failure, not a TypeError
            elif breakage == "a-core-id":
                # Reusing core's `tap.meta` id would rename it grid-wide: core's ids are core's (Q85a).
                batch["nodes"][0]["entity"]["entity_id"] = _CORE_TAP_META_ID
            elif breakage == "a-retirement":
                # A node-level retirement is a removal: refused before import, so nothing is retired.
                batch["nodes"][0]["retirement"] = {
                    "retired_at": "2026-01-01T00:00:00Z",
                    "batch_id": batch["batch_entity"]["entity_id"],
                }
            else:
                batch["nodes"][0]["node"]["values"] = "not-a-list"
            bad.write_text(json.dumps(document), encoding="utf-8")
        real = seeding.dimension_bundles
        broken = seeding.DimensionBundle("validation_sample", "validation_sample/dimension (broken)", bad)
        monkeypatch.setattr(seeding, "dimension_bundles", lambda: [*real()[:-1], broken])
        with pytest.raises(BootError, match=r"validation_sample/dimension \(broken\)") as raised:
            run_boot(None)
        if breakage == "a-core-id":
            assert "redeclares core's Dimension 'tap.meta'" in str(raised.value)
            from tap_grid.models import Dimension

            # Refused before import: core's row keeps its name.
            names = Dimension.all_objects.filter(entity_id=_CORE_TAP_META_ID).values_list("name", flat=True)  # type: ignore[misc]
            assert list(names) in ([], ["tap.meta"])

