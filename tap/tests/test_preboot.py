"""Unit tests for the settings-free pre-boot stage (tap/preboot.py).

These test the pre-Django kernel directly — variable resolution, the plain-JSON
profile reader, uv-install arg building + idempotency, entry-point discovery +
identity check, and the static coherence guard. No Django DB is needed; the one
test that touches settings only reads INSTALLED_APPS to keep the build-baked
transition set honest.

Spec: specs/spec-tap-boot-v0.md (req-boot-preboot, req-boot-install-section,
req-boot-variable-resolution, req-boot-snapshot).
"""

from __future__ import annotations

import subprocess

import pytest

from tap import preboot
from tap.boot_naming import RECORD_SUFFIX
from tap.jsonfiles import instance_id

_SHIPPED_PROFILE_IDS = sorted(instance_id(p, role="boot") for p in preboot._boot_dir().glob(f"*{RECORD_SUFFIX}"))


def _tracked_boot_ids() -> set[str] | None:
    """Profile ids of the git-TRACKED boot/*.boot.json files, or None when git can't answer.

    The boot/ glob sees staged records too — a live session migrated per
    req-boot-bootstrap-samsite-rehome legitimately stages the samsite record into
    boot/ (uncommitted), so "what does the REPO ship" is a question only git can
    answer. In a worktree session the container has no resolvable .git (the gitdir
    pointer targets an unmounted host path) — return None and let the caller skip
    the repo-shipping assertion rather than false-alarm on the documented flow.
    """
    boot_dir = preboot._boot_dir()
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.boot.json"],
            cwd=boot_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return {line.rsplit("/", 1)[-1].removesuffix(".boot.json") for line in result.stdout.splitlines() if line.strip()}


# --- Variable resolution (req-boot-variable-resolution) ----------------------


def testenv_var_name_mapping() -> None:
    assert preboot.env_var_name("install", "snapshot_before_migrate") == ("TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE")


def testresolve_var_precedence_env_over_profile_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    section = {"snapshot_before_migrate": True}
    # default wins when neither env nor profile present
    monkeypatch.delenv("TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE", raising=False)
    r = preboot.resolve_var("install", "missing_key", profile_section=section, default=False, is_bool=True)
    assert (r.value, r.source) == (False, "default")
    # profile wins over default
    r = preboot.resolve_var("install", "snapshot_before_migrate", profile_section=section, default=False, is_bool=True)
    assert (r.value, r.source) == (True, "profile")
    # env wins over profile
    monkeypatch.setenv("TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE", "false")
    r = preboot.resolve_var("install", "snapshot_before_migrate", profile_section=section, default=False, is_bool=True)
    assert (r.value, r.source) == (False, "env")


def testresolve_var_empty_env_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # docker-compose materializes an unmapped ${VAR:-} as "" — must NOT read as False.
    monkeypatch.setenv("TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE", "")
    r = preboot.resolve_var("install", "snapshot_before_migrate", profile_section={}, default=True, is_bool=True)
    assert (r.value, r.source) == (True, "default")


@pytest.mark.parametrize(
    "raw,expected", [("true", True), ("1", True), ("on", True), ("false", False), ("no", False), ("0", False)]
)
def test_bool_coercion(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv("TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE", raw)
    r = preboot.resolve_var("install", "snapshot_before_migrate", profile_section=None, default=None, is_bool=True)
    assert r.value is expected


# --- Install arg building + idempotency (req-boot-install-section, -preboot-3) --


def test_dist_name_for_slug() -> None:
    assert preboot.dist_name_for_slug("widget") == "tap-plugin-widget"
    assert preboot.dist_name_for_slug("aws_core") == "tap-plugin-aws-core"


UV_PIP_PREFIX = ["uv", "pip", "install", "--python", str(preboot._VENV_DIR)]


def test_uv_install_args_git() -> None:
    entry = {"slug": "widget", "source": {"type": "git", "url": "https://x/y.git", "rev": "abc123"}}
    args = preboot._uv_install_args(entry)
    assert args == [*UV_PIP_PREFIX, "tap-plugin-widget @ git+https://x/y.git@abc123"]


def test_uv_install_args_editable() -> None:
    entry = {"slug": "widget", "source": {"type": "editable", "path": "plugins/widget"}}
    args = preboot._uv_install_args(entry)
    assert args[:6] == [*UV_PIP_PREFIX, "--editable"]
    assert args[6].endswith("plugins/widget")


def test_uv_install_args_wheelhouse_relative_dir() -> None:
    entry = {
        "slug": "fedramp_20x_ksi",
        "source": {"type": "wheelhouse", "dir": "wheelhouse", "version": "0.1.1"},
    }
    args = preboot._uv_install_args(entry)
    assert args[:7] == [*UV_PIP_PREFIX, "--no-index", "--find-links"]
    assert args[7].endswith("/wheelhouse")  # resolved under the repo root
    assert args[8] == "tap-plugin-fedramp-20x-ksi==0.1.1"


def test_uv_install_args_wheelhouse_absolute_dir_used_as_is() -> None:
    entry = {
        "slug": "fedramp_20x_ksi",
        "source": {"type": "wheelhouse", "dir": "/run/tap-wheelhouse", "version": "0.1.1"},
    }
    args = preboot._uv_install_args(entry)
    assert args == [
        *UV_PIP_PREFIX,
        "--no-index",
        "--find-links",
        "/run/tap-wheelhouse",
        "tap-plugin-fedramp-20x-ksi==0.1.1",
    ]


def test_uv_install_args_unknown_source_raises() -> None:
    entry = {"slug": "x", "source": {"type": "svn"}}
    with pytest.raises(preboot.PrebootError):
        preboot._uv_install_args(entry)


# --- Profile reading (req-boot-install-section-2) ----------------------------


def test_read_profile_missing_raises() -> None:
    with pytest.raises(preboot.PrebootError):
        preboot._read_profile("does-not-exist-profile")


def test_read_plugin_owned_install_profile(tmp_path) -> None:
    # req-tap-plugin-arch-layout-6: a plugin may ship its own standalone boot profile that
    # is read as a plain file, NOT resolved through boot/ by id. Synthetic here so the
    # test stays decoupled from any specific plugin's records (the former genericom
    # example was deleted with that plugin).
    import json

    profile = {
        "version": 1,
        "description": "synthetic plugin-owned standalone profile",
        "install": {
            "plugins": [{"slug": "widget", "enabled": True, "source": {"type": "editable", "path": "plugins/widget"}}]
        },
    }
    path = tmp_path / "widget.boot.json"
    path.write_text(json.dumps(profile), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    entries = preboot._install_plugin_specs(loaded)
    assert [e["slug"] for e in entries] == ["widget"]
    assert entries[0]["source"]["type"] == "editable"


def test_install_plugin_specs_filters_disabled() -> None:
    profile = {
        "install": {
            "plugins": [
                {"slug": "a", "enabled": True, "source": {"type": "path", "path": "p"}},
                {"slug": "b", "enabled": False, "source": {"type": "path", "path": "p"}},
            ]
        }
    }
    assert [e["slug"] for e in preboot._install_plugin_specs(profile)] == ["a"]


def test_population_seed_slugs_filters_type_and_enabled() -> None:
    profile = {
        "population": {
            "steps": [
                {"type": "seed-plugin", "plugin": "a", "enabled": True},
                {"type": "seed-plugin", "plugin": "b", "enabled": False},
                {"type": "fire-collector", "key": "k", "enabled": True},
            ]
        }
    }
    assert preboot._population_seed_slugs(profile) == ["a"]


# --- Entry-point discovery identity check (req-boot-preboot) ------------------


def test_resolve_tap_plugins_identity_mismatch_raises() -> None:
    entries = [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]
    # discovered has a DIFFERENT key than the declared slug
    with pytest.raises(preboot.PrebootError, match="identity mismatch"):
        preboot._resolve_tap_plugins(entries, {"other": "other.apps.OtherConfig"})


def test_resolve_tap_plugins_happy() -> None:
    entries = [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]
    got = preboot._resolve_tap_plugins(entries, {"genericom": "tap_plugin.genericom.apps.GenericomConfig"})
    assert got == ["tap_plugin.genericom.apps.GenericomConfig"]


# --- Conformance gate (req-tap-plugin-arch-identity-5) ----------------------------


def test_namespace_segment() -> None:
    assert preboot._namespace_segment("tap_plugin.genericom.apps.GenericomConfig") == ("tap_plugin", "genericom")
    # A top-level (non-namespaced) AppConfig has the wrong shape.
    assert preboot._namespace_segment("genericom.apps.GenericomConfig") == ("genericom", "apps")


def _conformance_entries() -> list[dict[str, object]]:
    return [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]


def test_conformance_gate_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: entry["slug"])
    discovered = {"genericom": "tap_plugin.genericom.apps.GenericomConfig"}
    preboot._conformance_gate(_conformance_entries(), discovered)  # no raise


def test_conformance_gate_missing_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: None)
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: entry["slug"])
    discovered = {"genericom": "tap_plugin.genericom.apps.GenericomConfig"}
    with pytest.raises(preboot.PrebootError, match="no installed distribution"):
        preboot._conformance_gate(_conformance_entries(), discovered)


def test_conformance_gate_wrong_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: entry["slug"])
    # A top-level (non-namespaced) AppConfig — the MVP's old shape — must fail closed.
    discovered = {"genericom": "genericom.apps.GenericomConfig"}
    with pytest.raises(preboot.PrebootError, match="namespace"):
        preboot._conformance_gate(_conformance_entries(), discovered)


def test_conformance_gate_manifest_slug_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: "impostor")
    discovered = {"genericom": "tap_plugin.genericom.apps.GenericomConfig"}
    with pytest.raises(preboot.PrebootError, match="manifest slug"):
        preboot._conformance_gate(_conformance_entries(), discovered)


# --- Compatibility-floor gate (req-tap-plugin-extdev-compat-floor) ----------------


def _compat_entries() -> list[dict[str, object]]:
    return [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]


def test_requires_tap_gate_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_path_for", lambda entry, dist: "unused")
    monkeypatch.setattr(preboot, "_read_manifest_requires_tap", lambda path: ">=0.1,<0.2")
    monkeypatch.setattr("tap.core_version.core_tap_version", lambda: "0.1.0")
    preboot._requires_tap_gate(_compat_entries())  # no raise


def test_requires_tap_gate_violated_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_path_for", lambda entry, dist: "unused")
    monkeypatch.setattr(preboot, "_read_manifest_requires_tap", lambda path: ">=0.5")
    monkeypatch.setattr("tap.core_version.core_tap_version", lambda: "0.1.0")
    with pytest.raises(preboot.PrebootError, match="requires TAP >=0.5 but the running core is 0.1.0"):
        preboot._requires_tap_gate(_compat_entries())


def test_requires_tap_gate_absent_is_allowed_and_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_path_for", lambda entry, dist: "unused")
    monkeypatch.setattr(preboot, "_read_manifest_requires_tap", lambda path: None)

    # A floor-less profile must never even resolve the core version — prove laziness.
    def _boom() -> str:
        raise AssertionError("core_tap_version must not be called when no plugin declares a floor")

    monkeypatch.setattr("tap.core_version.core_tap_version", _boom)
    preboot._requires_tap_gate(_compat_entries())  # no raise, no core-version resolution


def test_requires_tap_gate_unresolvable_core_with_floor_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap.core_version import CoreVersionError

    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object())
    monkeypatch.setattr(preboot, "_manifest_path_for", lambda entry, dist: "unused")
    monkeypatch.setattr(preboot, "_read_manifest_requires_tap", lambda path: ">=0.1")

    def _unresolvable() -> str:
        raise CoreVersionError("no version")

    monkeypatch.setattr("tap.core_version.core_tap_version", _unresolvable)
    with pytest.raises(preboot.PrebootError, match="running core version cannot be determined"):
        preboot._requires_tap_gate(_compat_entries())


# --- Install reconciliation guard (req-boot-install-section-5) ----------------


def test_reconciliation_guard_happy() -> None:
    # Installed set exactly equals the declared+enabled set → no raise.
    entries = [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]
    preboot._reconciliation_guard(entries, {"genericom": "tap_plugin.genericom.apps.GenericomConfig"})


def test_reconciliation_guard_undeclared_extra_fails() -> None:
    # A package-mode plugin installed on disk but not in the profile's `install` set.
    entries = [{"slug": "genericom", "source": {"type": "path", "path": "p"}}]
    discovered = {
        "genericom": "tap_plugin.genericom.apps.GenericomConfig",
        "rogue": "tap_plugin.rogue.apps.RogueConfig",
    }
    with pytest.raises(preboot.PrebootError, match="reconciliation"):
        preboot._reconciliation_guard(entries, discovered)


def test_reconciliation_guard_installed_but_disabled_fails() -> None:
    # _install_plugin_specs drops disabled entries, so a disabled-but-still-installed
    # plugin surfaces here as an undeclared extra (venv/profile drift), and fails closed.
    entries: list[dict[str, object]] = []
    with pytest.raises(preboot.PrebootError, match="reconciliation"):
        preboot._reconciliation_guard(entries, {"genericom": "tap_plugin.genericom.apps.GenericomConfig"})


# --- Static coherence guard (req-boot-install-section-3) ----------------------


def test_static_coherence_guard_passes_for_build_baked(monkeypatch: pytest.MonkeyPatch) -> None:
    # A build-baked slug seeded in population, absent from `install`, must pass.
    # BUILD_BAKED_PLUGIN_SLUGS is empty as of 2026-07-02 (initial plugin migration
    # complete — gryphon_playground, the last build-baked plugin, went package-mode),
    # so there is no real build-baked slug to exercise the branch with. Monkeypatch a
    # synthetic one in to keep the guard's "build-baked counts as available" path
    # covered against a future re-introduced build-baked plugin.
    monkeypatch.setattr(preboot, "BUILD_BAKED_PLUGIN_SLUGS", frozenset({"synthetic_build_baked"}))
    profile = {"population": {"steps": [{"type": "seed-plugin", "plugin": "synthetic_build_baked", "enabled": True}]}}
    preboot._static_coherence_guard(profile, install_slugs=set())  # no raise


def test_static_coherence_guard_passes_for_installed() -> None:
    profile = {"population": {"steps": [{"type": "seed-plugin", "plugin": "genericom", "enabled": True}]}}
    preboot._static_coherence_guard(profile, install_slugs={"genericom"})  # no raise


def test_static_coherence_guard_fails_for_unknown() -> None:
    profile = {"population": {"steps": [{"type": "seed-plugin", "plugin": "typo_plugin", "enabled": True}]}}
    with pytest.raises(preboot.PrebootError, match="static coherence guard"):
        preboot._static_coherence_guard(profile, install_slugs={"genericom"})


# --- Build-baked transition set stays honest against settings ----------------


def test_build_baked_matches_installed_apps() -> None:
    """BUILD_BAKED_PLUGIN_SLUGS must equal the plugins hardcoded in INSTALLED_APPS.

    Keeps the transition constant from silently drifting as plugins migrate to
    package-mode (a stale entry would make the coherence guard wave through an
    uninstalled slug). genericom is package-mode, so it is intentionally absent.
    """
    from django.conf import settings

    hardcoded = {
        app.split(".")[1] for app in settings.INSTALLED_APPS if app.startswith("plugins.") and app.endswith("Config")
    }
    assert preboot.BUILD_BAKED_PLUGIN_SLUGS == hardcoded


# --- Every SHIPPED profile is coherent (guards profile↔migration drift) -------


def test_shipped_profiles_exist() -> None:
    """Sanity: the enumeration found the real boot/ profiles (not an empty glob).

    samsite is deliberately absent from the TRACKED set: its record ships inside
    tap-plugin-samsite (req-boot-bootstrap-samsite-rehome); the plugin's own suite
    covers it. The negative assert consults git, not the glob — a migrated live
    session legitimately STAGES the samsite record into boot/ (uncommitted), and
    that documented flow must not red the suite. Where git cannot answer (worktree
    sessions in-container), the repo-shipping half is skipped; CI's real-clone
    checkout enforces it.
    """
    assert "test_all" in _SHIPPED_PROFILE_IDS
    tracked = _tracked_boot_ids()
    if tracked is None:
        pytest.skip("git unavailable — cannot distinguish staged from tracked boot records")
    assert "samsite" not in tracked


@pytest.mark.parametrize("profile_id", _SHIPPED_PROFILE_IDS)
def test_shipped_profile_is_coherent(profile_id: str) -> None:
    """Every real boot/<id>.boot.json passes the static coherence guard.

    This is the test that would have caught the `base` regression: after the
    package-mode migration, plugins the profile seeds are no longer build-baked,
    so a profile that seeds them without an `install` entry fatally aborts
    pre-boot at spawn time. The unit tests above exercise the guard with
    synthetic profiles and `test_profile.py` load/parses the real ones, but
    nothing crossed the two — so profile↔migration drift shipped and only
    surfaced on a fresh spawn elsewhere. Mirror exactly what `run_preboot` feeds
    the guard (parse the `install` section → slugs → guard), reading the real
    shipped profile, without touching the venv.
    """
    profile = preboot._read_profile(profile_id)
    install_slugs = {e["slug"] for e in preboot._install_plugin_specs(profile)}
    # Raises PrebootError if a seeded plugin is neither installed nor build-baked.
    preboot._static_coherence_guard(profile, install_slugs)
