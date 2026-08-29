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

import logging
import subprocess
from pathlib import Path

import pytest

from tap import preboot
from tap.boot_naming import RECORD_SUFFIX
from tap.jsonfiles import instance_id
from tap.plugin_identity import dist_names_for_slug

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
    """req-tap-plugin-arch-identity-2: the ``<slug>-tap`` suffix leads; the prefix is legacy."""
    assert preboot.dist_name_for_slug("widget") == "widget-tap"
    assert preboot.dist_name_for_slug("aws_core") == "aws-core-tap"
    assert preboot.dist_name_for_slug("git_serious") == "git-serious-tap"
    assert dist_names_for_slug("aws_core") == ("aws-core-tap", "tap-plugin-aws-core")


def test_installed_plugin_dist_name_prefers_new_convention(monkeypatch: pytest.MonkeyPatch) -> None:
    both = {"aws-core-tap", "tap-plugin-aws-core"}
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object() if name in both else None)
    assert preboot._installed_plugin_dist_name("aws_core") == "aws-core-tap"
    monkeypatch.setattr(
        preboot, "_installed_distribution", lambda name: object() if name.startswith("tap-plugin-") else None
    )
    assert preboot._installed_plugin_dist_name("aws_core") == "tap-plugin-aws-core"
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: None)
    assert preboot._installed_plugin_dist_name("aws_core") is None


UV_PIP_PREFIX = ["uv", "pip", "install", "--python", str(preboot._VENV_DIR)]


def test_uv_install_args_git() -> None:
    entry = {"slug": "widget", "source": {"type": "git", "url": "https://x/y.git", "rev": "abc123"}}
    args = preboot._uv_install_args(entry)
    # Bare direct-URL requirement: the distribution name comes from the checkout's own
    # pyproject, so pre-boot never guesses which naming convention the plugin carries.
    assert args == [*UV_PIP_PREFIX, "git+https://x/y.git@abc123"]


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
    assert args[8] == "fedramp-20x-ksi-tap==0.1.1"


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
        "fedramp-20x-ksi-tap==0.1.1",
    ]


def test_uv_install_args_wheelhouse_requests_the_convention_the_wheel_carries(tmp_path: Path) -> None:
    """Transition (req-tap-plugin-arch-identity-2): a wheelhouse holding a legacy-named wheel
    is asked for that name; one holding the new name — or both — gets the new name."""
    entry = {"slug": "fedramp_20x_ksi", "source": {"type": "wheelhouse", "dir": str(tmp_path), "version": "0.1.1"}}
    assert preboot._uv_install_args(entry)[-1] == "fedramp-20x-ksi-tap==0.1.1"  # empty dir: preferred, fails loud
    (tmp_path / "tap_plugin_fedramp_20x_ksi-0.1.1-py3-none-any.whl").write_bytes(b"")
    assert preboot._uv_install_args(entry)[-1] == "tap-plugin-fedramp-20x-ksi==0.1.1"
    # A NEW-convention wheel at a DIFFERENT version must not steal the pick (Copilot, PR #180).
    (tmp_path / "fedramp_20x_ksi_tap-0.1.0-py3-none-any.whl").write_bytes(b"")
    assert preboot._uv_install_args(entry)[-1] == "tap-plugin-fedramp-20x-ksi==0.1.1"
    (tmp_path / "fedramp_20x_ksi_tap-0.1.1-py3-none-any.whl").write_bytes(b"")
    assert preboot._uv_install_args(entry)[-1] == "fedramp-20x-ksi-tap==0.1.1"


def test_wheelhouse_dist_name_ignores_non_matching_and_malformed_files(tmp_path: Path) -> None:
    """Only a wheel whose PEP 427 project segment is one of the slug's names counts; other
    wheels, non-wheels, and a bare filename with no version segment are ignored."""
    for name in (
        "requests-2.32.0-py3-none-any.whl",
        "fedramp_20x_ksi_tap.whl",
        "fedramp_20x_ksi_tap-0.1.1.tar.gz",
        "notes.txt",
    ):
        (tmp_path / name).write_bytes(b"")
    assert (
        preboot._wheelhouse_dist_name(tmp_path, "fedramp_20x_ksi", "0.1.0") == "fedramp-20x-ksi-tap"
    )  # preferred, nothing matched
    assert preboot._wheelhouse_dist_name(tmp_path / "missing", "fedramp_20x_ksi", "0.1.0") == "fedramp-20x-ksi-tap"
    (tmp_path / "tap_plugin_fedramp_20x_ksi-0.1.0-py3-none-any.whl").write_bytes(b"")
    assert preboot._wheelhouse_dist_name(tmp_path, "fedramp_20x_ksi", "0.1.0") == "tap-plugin-fedramp-20x-ksi"
    assert preboot._wheelhouse_dist_name(tmp_path, "fedramp_20x_ksi", "9.9.9") == "fedramp-20x-ksi-tap"  # wrong version


def test_uv_install_args_unknown_source_raises() -> None:
    entry = {"slug": "x", "source": {"type": "svn"}}
    with pytest.raises(preboot.PrebootError):
        preboot._uv_install_args(entry)


# --- Profile reading (req-boot-install-section-2) ----------------------------


def test_read_profile_missing_raises() -> None:
    with pytest.raises(preboot.PrebootError) as excinfo:
        preboot._read_profile("does-not-exist-profile")
    message = str(excinfo.value)
    # Reads the real repo boot/ dir, so the shipped baseline must be enumerated.
    assert "Available in boot/:" in message
    assert "core_dev" in message
    # The rehomed-profile road (req-boot-bootstrap-samsite-rehome): a profile absent
    # from core may ship in its plugin repo — the error must teach the pointer form.
    assert "--from" in message


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


def test_install_plugins_preflights_credentials_before_installing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install loop must not start when a declared credential is unsatisfiable
    (req-tap-plugin-arch-source-secret-7). `_run_install` is a tripwire: reaching it means
    the first plugin was already being pulled before the second one's missing credential
    was discovered — the failure mode the preflight exists to end."""
    empty_store = tmp_path / "secrets"
    empty_store.mkdir()
    monkeypatch.setattr(preboot, "_secrets_root", lambda: empty_store)
    monkeypatch.setattr(
        preboot,
        "_run_install",
        lambda *a, **k: pytest.fail("an install ran despite an unsatisfiable credential"),
    )
    entries = [
        {
            "slug": slug,
            "enabled": True,
            "source": {"type": "git", "url": f"https://example.invalid/{slug}", "rev": "v1", "credential": cred},
        }
        for slug, cred in (("a", "org-a-ro"), ("b", "org-b-ro"))
    ]

    with pytest.raises(preboot.PrebootError) as excinfo:
        preboot._install_plugins(entries, "someprofile")

    message = str(excinfo.value)
    assert "org-a-ro" in message and "org-b-ro" in message  # BOTH, in one verdict
    assert "someprofile" in message


def test_install_plugins_is_unaffected_when_no_credential_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public git source declares nothing, so the preflight is a no-op and the install
    proceeds — the preflight must not invent a requirement (req-tap-plugin-arch-source-secret-5)."""
    monkeypatch.setattr(preboot, "_secrets_root", lambda: tmp_path / "absent")
    monkeypatch.setattr(preboot, "_is_satisfied", lambda entry: False)
    ran: list[str] = []

    class _Ok:
        returncode = 0
        stderr = ""

    def _record_install(args: list[str], cred: object) -> _Ok:
        ran.append(args[-1])
        return _Ok()

    monkeypatch.setattr(preboot, "_run_install", _record_install)
    entry = {"slug": "a", "enabled": True, "source": {"type": "git", "url": "https://example.invalid/a", "rev": "v1"}}

    preboot._install_plugins([entry], "someprofile")

    assert len(ran) == 1


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
    with pytest.raises(preboot.PrebootError, match="no installed distribution") as excinfo:
        preboot._conformance_gate(_conformance_entries(), discovered)
    # The message names both conventions so an operator sees exactly what would have passed.
    assert "genericom-tap" in str(excinfo.value) and "tap-plugin-genericom" in str(excinfo.value)


def test_conformance_gate_accepts_legacy_distribution_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """req-tap-plugin-arch-identity-2 transition: a plugin still installed under the deprecated
    ``tap-plugin-<slug>`` name boots, and the gate says so at WARNING so the rename is visible."""
    monkeypatch.setattr(
        preboot, "_installed_distribution", lambda name: object() if name.startswith("tap-plugin-") else None
    )
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: entry["slug"])
    discovered = {"genericom": "tap_plugin.genericom.apps.GenericomConfig"}
    with caplog.at_level(logging.WARNING, logger="tap.preboot"):
        preboot._conformance_gate(_conformance_entries(), discovered)  # no raise
    assert any("deprecated distribution name 'tap-plugin-genericom'" in r.getMessage() for r in caplog.records)


def test_conformance_gate_new_convention_is_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(preboot, "_installed_distribution", lambda name: object() if name.endswith("-tap") else None)
    monkeypatch.setattr(preboot, "_manifest_slug", lambda entry, dist: entry["slug"])
    discovered = {"genericom": "tap_plugin.genericom.apps.GenericomConfig"}
    with caplog.at_level(logging.WARNING, logger="tap.preboot"):
        preboot._conformance_gate(_conformance_entries(), discovered)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


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


class TestWheelhouseDigestPin:
    """A wheelhouse source pins a coordinate; the digest pins the bytes.

    Spec: specs/spec-tap-boot-v0.md (req-tap-plugin-arch-sources-6). The git arm is
    content-addressed by its rev; these cover the offline arm, which is the one an
    airgapped operator relies on and which had no content check at all.
    """

    @staticmethod
    def _wheelhouse(tmp_path, body: bytes = b"wheel-bytes"):
        (tmp_path / "demo_tap-1.2.3-py3-none-any.whl").write_bytes(body)
        return {
            "slug": "demo",
            "source": {"type": "wheelhouse", "dir": str(tmp_path), "version": "1.2.3"},
        }

    def test_matching_digest_passes(self, tmp_path):
        import hashlib

        entry = self._wheelhouse(tmp_path)
        entry["source"]["sha256"] = hashlib.sha256(b"wheel-bytes").hexdigest()
        preboot._verify_wheelhouse_digest(entry)  # no raise

    def test_mismatched_digest_is_fatal(self, tmp_path):
        entry = self._wheelhouse(tmp_path)
        entry["source"]["sha256"] = "00" * 32
        with pytest.raises(preboot.PrebootError, match="does not match the declared"):
            preboot._verify_wheelhouse_digest(entry)

    def test_swapped_bytes_at_the_same_version_are_caught(self, tmp_path):
        """The actual attack: same coordinate, different content."""
        import hashlib

        entry = self._wheelhouse(tmp_path, body=b"honest")
        entry["source"]["sha256"] = hashlib.sha256(b"honest").hexdigest()
        (tmp_path / "demo_tap-1.2.3-py3-none-any.whl").write_bytes(b"swapped")
        with pytest.raises(preboot.PrebootError):
            preboot._verify_wheelhouse_digest(entry)

    def test_absent_digest_warns_and_proceeds(self, tmp_path, caplog):
        """Optional today so existing records boot; the absence must be visible, not silent."""
        entry = self._wheelhouse(tmp_path)
        with caplog.at_level(logging.WARNING):
            preboot._verify_wheelhouse_digest(entry)
        assert "declares no sha256" in caplog.text

    def test_missing_wheel_defers_to_uv(self, tmp_path):
        """Not-found must stay uv's error, not become a second divergent path."""
        entry = {
            "slug": "demo",
            "source": {"type": "wheelhouse", "dir": str(tmp_path), "version": "9.9.9", "sha256": "00" * 32},
        }
        preboot._verify_wheelhouse_digest(entry)  # no raise
