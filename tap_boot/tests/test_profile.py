"""Boot-profile load / schema-validate / parse (req-boot-profile)."""

from __future__ import annotations

import json

import pytest

from tap_boot.profile import (
    BootProfileError,
    FireCollectorStep,
    SeedPluginStep,
    load_profile,
)


def _write(boot_dir, profile_id: str, data: dict[str, object]) -> None:
    (boot_dir / f"{profile_id}.boot.json").write_text(json.dumps(data))


@pytest.fixture
def boot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("tap_boot.profile.boot_dir", lambda: tmp_path)
    return tmp_path


# The real-samsite-profile parse test moved with the record: the samsite profile
# re-homed into tap-plugin-samsite (req-boot-bootstrap-samsite-rehome), and its
# parse/resolve coverage now lives in that plugin's shipped suite
# (tap_plugin/samsite/tests/test_boot_record_resolves.py). Mixed seed+fire
# parsing stays covered here synthetically (the fixture-driven tests below), and
# on a real shipped file by test_test_all_profile_is_seed_only.


def test_test_all_profile_is_seed_only():
    profile = load_profile("test_all")
    assert all(isinstance(s, SeedPluginStep) for s in profile.steps)
    assert profile.has_population


def test_missing_profile_raises(boot_dir):
    _write(boot_dir, "present", {"population": {"steps": []}})
    with pytest.raises(BootProfileError, match="not found") as excinfo:
        load_profile("does-not-exist")
    message = str(excinfo.value)
    assert "Available in boot/: present" in message
    # The rehomed-profile road (req-boot-bootstrap-samsite-rehome): a profile absent
    # from core may ship in its plugin repo — the error must teach the pointer form.
    assert "--from" in message


def test_enabled_steps_filters_disabled(boot_dir):
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "population": {
                "steps": [
                    {"type": "seed-plugin", "plugin": "a", "enabled": True},
                    {"type": "seed-plugin", "plugin": "b", "enabled": False},
                ]
            },
        },
    )
    profile = load_profile("p")
    assert len(profile.steps) == 2
    assert [s.plugin for s in profile.enabled_steps if isinstance(s, SeedPluginStep)] == ["a"]


def test_on_failure_defaults_to_abort(boot_dir):
    _write(boot_dir, "p", {"version": 1, "population": {"steps": []}})
    assert load_profile("p").on_failure == "abort"


def test_collector_preflight_parses_and_defaults_to_undeclared(boot_dir):
    # Undeclared -> None (the orchestrator's variable ladder then defaults it true,
    # req-boot-obs-preflight-4); a declared false parses through.
    _write(boot_dir, "p", {"version": 1, "population": {"steps": []}})
    assert load_profile("p").collector_preflight is None
    _write(boot_dir, "q", {"version": 1, "population": {"collector_preflight": False, "steps": []}})
    assert load_profile("q").collector_preflight is False


def test_no_population_is_auth_only(boot_dir):
    _write(boot_dir, "p", {"version": 1})
    profile = load_profile("p")
    assert not profile.has_population
    assert profile.steps == ()


def test_schema_rejects_unknown_field(boot_dir):
    _write(
        boot_dir,
        "bad",
        {
            "version": 1,
            "population": {"steps": [{"type": "seed-plugin", "plugin": "a", "enabled": True, "bogus": 1}]},
        },
    )
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")


def test_schema_rejects_wrong_version(boot_dir):
    _write(boot_dir, "bad", {"version": 0, "population": {"steps": []}})
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")


def test_schema_rejects_bad_step_type(boot_dir):
    _write(
        boot_dir,
        "bad",
        {"version": 1, "population": {"steps": [{"type": "frobnicate", "enabled": True}]}},
    )
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")


def test_required_secrets_parse_with_step_refs(boot_dir):
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "required_secrets": [
                {"scope": "github_core", "key": "collector", "kind": "github_pat", "note": "read-only PAT"}
            ],
            "population": {
                "steps": [
                    {
                        "type": "fire-collector",
                        "key": "github_core:github_core",
                        "enabled": True,
                        "secrets": ["github_core:collector"],
                    }
                ]
            },
        },
    )
    profile = load_profile("p")
    assert profile.required_secrets[0].ref == "github_core:collector"
    assert profile.required_secrets[0].kind == "github_pat"
    step = profile.steps[0]
    assert isinstance(step, FireCollectorStep)
    assert step.secrets == ("github_core:collector",)


def test_unresolved_step_secret_ref_fails_loud(boot_dir):
    # Rule A (req-boot-required-secrets-3): an enabled step's ref must resolve.
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "population": {
                "steps": [
                    {"type": "fire-collector", "key": "x:y", "enabled": True, "secrets": ["github_core:collector"]}
                ]
            },
        },
    )
    with pytest.raises(BootProfileError, match="declares no such entry"):
        load_profile("p")


def test_stale_required_secret_entry_fails_loud(boot_dir):
    # Rule B (req-boot-required-secrets-4): an entry no enabled step references is stale.
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "required_secrets": [
                {"scope": "github_core", "key": "collector", "kind": "github_pat", "note": "read-only PAT"}
            ],
            "population": {"steps": []},
        },
    )
    with pytest.raises(BootProfileError, match="referenced by no enabled"):
        load_profile("p")


def test_disabled_step_ref_with_entry_removed_is_valid(boot_dir):
    # The rules compose: disabling a step drops its requirement (rule B forces the
    # entry's removal), and the disabled step's dangling ref must NOT invalidate the
    # profile — rule A is enabled-scoped. Re-enabling fails loud until the entry returns.
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "population": {
                "steps": [
                    {"type": "fire-collector", "key": "x:y", "enabled": False, "secrets": ["github_core:collector"]}
                ]
            },
        },
    )
    load_profile("p")  # no raise


def test_duplicate_required_secret_entries_fail_loud(boot_dir):
    entry = {"scope": "github_core", "key": "collector", "kind": "github_pat", "note": "read-only PAT"}
    _write(
        boot_dir,
        "p",
        {
            "version": 1,
            "required_secrets": [entry, dict(entry)],
            "population": {
                "steps": [
                    {"type": "fire-collector", "key": "x:y", "enabled": True, "secrets": ["github_core:collector"]}
                ]
            },
        },
    )
    with pytest.raises(BootProfileError, match="duplicate required_secrets"):
        load_profile("p")


def test_schema_rejects_required_secret_missing_note(boot_dir):
    # note is load-bearing guidance for the provisioning flow — schema-required.
    _write(
        boot_dir,
        "bad",
        {
            "version": 1,
            "required_secrets": [{"scope": "github_core", "key": "collector", "kind": "github_pat"}],
            "population": {
                "steps": [
                    {"type": "fire-collector", "key": "x:y", "enabled": True, "secrets": ["github_core:collector"]}
                ]
            },
        },
    )
    with pytest.raises(BootProfileError, match="schema"):
        load_profile("bad")
