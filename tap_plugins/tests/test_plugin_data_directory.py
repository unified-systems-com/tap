"""Plugin data directories (`tap_plugins/specs/spec-tap-plugin-data-directory.md`).

Every acceptance criterion of the Proposed requirements has a test here marked with its id, except
the in-use lock's cross-process criteria, which are in ``test_plugin_data_lock.py``.

The one seam: ``tap.volume_mount.root_device``. A temporary directory sits on the same device as
``/``, so every test that wants a "mounted" volume replaces the root device with one no real
directory has; the not-mounted tests point it back at the temporary directory's own device.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tap import volume_mount
from tap.jsonfiles import load_json_file, validate_json
from tap.logging_signals import ABORT_MESSAGE_CODE
from tap_plugins.datadir import (
    PluginDataDirectoryError,
    PluginDataGateError,
    _facts,
    _lock,
    _placement,
    _provision,
    _purge,
    _report,
    data_dir,
    data_dir_is_ephemeral,
    run_gate,
)
from tap_plugins.datadir.health import probe_plugin_data
from tap_plugins.manifest import DataDirectoryDeclaration, PluginManifestError, load_manifest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = _REPO / "tap_plugins" / "specs" / "spec-tap-plugin-data-directory.md"
_MOUNT = "/var/lib/tap/" + "plugin-data"


def _decl(durability: str = "cache", *, executes: bool = False, max_bytes: int = 4096) -> DataDirectoryDeclaration:
    return DataDirectoryDeclaration(
        purpose="Fixture data for a test.", durability=durability, max_bytes=max_bytes, executes=executes
    )


@pytest.fixture
def pd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any) -> Any:
    """A temporary volume and ephemeral root, a controllable set of declaring plugins, no ambient state."""
    volume = tmp_path / "volume"
    volume.mkdir()
    ephemeral = tmp_path / "home" / "ephemeral"
    monkeypatch.setattr(_placement, "EPHEMERAL_ROOT", ephemeral)
    monkeypatch.setattr(volume_mount, "root_device", lambda: -1)
    settings.TAP_PLUGIN_DATA_ROOT = ""
    settings.TAP_FILES_ROOT = ""
    declared: dict[str, tuple[DataDirectoryDeclaration, str]] = {}
    monkeypatch.setattr(_placement, "declared_directories", lambda: dict(sorted(declared.items())))
    _placement.reset_verdicts()
    _lock.release_all()

    def declare(slug: str, durability: str = "cache", **kwargs: Any) -> DataDirectoryDeclaration:
        declaration = _decl(durability, **kwargs)
        declared[slug] = (declaration, "1.2.3")
        return declaration

    def enable() -> Path:
        settings.TAP_PLUGIN_DATA_ROOT = str(volume)
        _placement.reset_verdicts()
        return volume

    yield SimpleNamespace(volume=volume, ephemeral=ephemeral, declared=declared, declare=declare, enable=enable)
    _placement.reset_verdicts()
    _lock.release_all()


def _snapshot(path: Path) -> dict[str, tuple[bytes, int, int]]:
    """Every entry under *path*: content (files), mtime and ctime, so "nothing changed" is testable."""
    found: dict[str, tuple[bytes, int, int]] = {}
    for entry in sorted(path.rglob("*")):
        st = entry.lstat()
        body = entry.read_bytes() if entry.is_file() and not entry.is_symlink() else b""
        found[entry.relative_to(path).as_posix()] = (body, st.st_mtime_ns, st.st_ctime_ns)
    return found


# --------------------------------------------------------------------------- scope


@pytest.mark.django_db
@pytest.mark.spec("req-tap-plugin-datadir-scope-1")
def test_provisioning_reporting_and_purging_write_nothing_to_the_grid(pd: Any, django_assert_num_queries: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    with django_assert_num_queries(0):
        run_gate()
        _report.plugin_section("alpha", pd.declared["alpha"][0])
        _report.instance_section({"alpha"})
        _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    from tap_grid.models import EntityType

    slugs = set(EntityType.objects.values_list("slug", flat=True))
    assert not {s for s in slugs if "data_dir" in s or "plugin_data" in s}, slugs


@pytest.mark.spec("req-tap-plugin-datadir-scope-2")
def test_the_gate_refuses_a_root_that_overlaps_the_file_store(pd: Any, settings: Any, tmp_path: Path) -> None:
    pd.enable()
    for files_root in (pd.volume, pd.volume / "files", tmp_path):
        if not files_root.exists():
            files_root.mkdir()
        settings.TAP_FILES_ROOT = str(files_root)
        _placement.reset_verdicts()
        with pytest.raises(PluginDataGateError, match="file store root"):
            run_gate()
    elsewhere = tmp_path.parent / f"{tmp_path.name}-files"
    elsewhere.mkdir()
    settings.TAP_FILES_ROOT = str(elsewhere)
    _placement.reset_verdicts()
    run_gate()


# --------------------------------------------------------------------------- root


@pytest.mark.spec("req-tap-plugin-datadir-root-1")
def test_the_root_is_one_setting_with_no_default() -> None:
    from django.conf import settings

    from tap.guards.discovery import discover_guards

    text = (_REPO / "tap" / "settings.py").read_text(encoding="utf-8")
    assert 'TAP_PLUGIN_DATA_ROOT = os.environ.get("TAP_PLUGIN_DATA_ROOT") or ""' in text
    # Unset reads as empty, never as a path: the expression is evaluated exactly as settings does.
    environ: dict[str, str] = {}
    assert (environ.get("TAP_PLUGIN_DATA_ROOT") or "") == ""
    assert isinstance(settings.TAP_PLUGIN_DATA_ROOT, str)
    next(g for g in discover_guards() if g.slug == "plugin-data-root-resolution").check()


def _compose_web(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "  web:")
    except StopIteration:
        return []
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    ") and not line.lstrip().startswith("#"):
            break
        block.append(line.strip())
    return block


@pytest.mark.spec("req-tap-plugin-datadir-root-2")
def test_every_compose_file_with_web_mounts_the_volume_and_sets_the_variable() -> None:
    base = _compose_web(_REPO / "docker-compose.yml")
    assert f"- plugin_data:{_MOUNT}" in base, base
    assert f"TAP_PLUGIN_DATA_ROOT: {_MOUNT}" in base, base
    assert "  plugin_data:" in (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    # The overlays merge into the base service (CI, build) or define another service
    # (Codespaces' devbox); none may drop or repoint the volume or the variable.
    for overlay in sorted(_REPO.glob("docker-compose.*.yml")):
        web = _compose_web(overlay)
        text = "\n".join(web)
        assert "TAP_PLUGIN_DATA_ROOT" not in text, overlay.name
        assert "plugin_data" not in text, overlay.name
        assert not any(line.startswith(("volumes: !override", "environment: !override")) for line in web)


@pytest.mark.spec("req-tap-plugin-datadir-root-3")
def test_the_image_prepares_the_mount_path_for_the_runtime_user() -> None:
    dockerfile = (_REPO / "Dockerfile").read_text(encoding="utf-8")
    prepare = next(
        line for line in dockerfile.split("\nRUN ") if line.startswith("mkdir -p /app/.venv") and _MOUNT in line
    )
    assert "chown -R nonroot:0" in prepare and prepare.count(_MOUNT) == 3, prepare
    assert "g+rwX" in prepare, prepare


@pytest.mark.spec("req-tap-plugin-datadir-root-4")
def test_core_never_creates_the_volume_root(pd: Any, settings: Any, tmp_path: Path) -> None:
    missing = tmp_path / "not-mounted"
    settings.TAP_PLUGIN_DATA_ROOT = str(missing)
    _placement.reset_verdicts()
    pd.declare("alpha")
    with pytest.raises(PluginDataGateError, match="does not exist"):
        run_gate()
    with pytest.raises(PluginDataDirectoryError, match="does not exist"):
        data_dir("alpha")
    assert not missing.exists()


@pytest.mark.spec("req-tap-plugin-datadir-root-5")
def test_the_ephemeral_root_is_one_constant_off_the_volume() -> None:
    source = Path(_placement.__file__).read_text(encoding="utf-8")
    assignment = next(line for line in source.splitlines() if line.startswith("EPHEMERAL_ROOT = "))
    assert assignment == 'EPHEMERAL_ROOT = Path.home() / ".local" / "share" / "tap" / "plugin-data-ephemeral"'
    assert source.count("EPHEMERAL_ROOT = ") == 1 and "environ" not in source
    root = Path.home() / ".local" / "share" / "tap" / "plugin-data-ephemeral"
    assert root.is_absolute() and not root.is_relative_to(_MOUNT)


# --------------------------------------------------------------------------- manifest

_BASE = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "acme"\nname = "Acme"\n'
_TABLE = '[data_directory]\npurpose = "Datasets."\ndurability = "cache"\nmax_bytes = 1024\n'


def _load(tmp_path: Path, body: str) -> Any:
    (tmp_path / "tap-plugin.toml").write_text(_BASE + body, encoding="utf-8")
    return load_manifest(tmp_path)


@pytest.mark.spec("req-tap-plugin-datadir-manifest-1")
def test_no_table_parses_with_no_directory(tmp_path: Path) -> None:
    assert _load(tmp_path, "").data_directory is None
    declared = _load(tmp_path, _TABLE).data_directory
    assert declared == DataDirectoryDeclaration("Datasets.", "cache", 1024, False)


@pytest.mark.spec("req-tap-plugin-datadir-manifest-2")
@pytest.mark.parametrize("key", ["purpose", "durability", "max_bytes"])
def test_each_required_key_is_named_when_missing(tmp_path: Path, key: str) -> None:
    body = "\n".join(line for line in _TABLE.splitlines() if not line.startswith(key)) + "\n"
    with pytest.raises(PluginManifestError, match=f"data_directory.{key} is required"):
        _load(tmp_path, body)


@pytest.mark.spec("req-tap-plugin-datadir-manifest-3")
@pytest.mark.parametrize("value", ['"ephemeral"', '"Cache"', '""', "1"])
def test_durability_is_cache_or_state(tmp_path: Path, value: str) -> None:
    with pytest.raises(PluginManifestError, match="durability must be one of"):
        _load(tmp_path, _TABLE.replace('"cache"', value))
    assert _load(tmp_path, _TABLE.replace('"cache"', '"state"')).data_directory.durability == "state"


@pytest.mark.spec("req-tap-plugin-datadir-manifest-4")
@pytest.mark.parametrize("value", ["0", "-5", "1.5", '"1024"', "true", "false"])
def test_max_bytes_is_a_positive_integer(tmp_path: Path, value: str) -> None:
    with pytest.raises(PluginManifestError, match="max_bytes must be a positive integer"):
        _load(tmp_path, _TABLE.replace("1024", value))


@pytest.mark.spec("req-tap-plugin-datadir-manifest-5")
def test_an_unknown_key_is_named(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="unknown keys \\['quota'\\]"):
        _load(tmp_path, _TABLE + "quota = 5\n")


@pytest.mark.spec("req-tap-plugin-datadir-manifest-7")
@pytest.mark.parametrize("value", ['"yes"', "1", "0"])
def test_executes_is_a_boolean(tmp_path: Path, value: str) -> None:
    assert _load(tmp_path, _TABLE).data_directory.executes is False
    assert _load(tmp_path, _TABLE + "executes = true\n").data_directory.executes is True
    with pytest.raises(PluginManifestError, match="executes must be a boolean"):
        _load(tmp_path, _TABLE + f"executes = {value}\n")


@pytest.mark.spec("req-tap-plugin-datadir-manifest-6")
def test_validate_plugin_reports_the_declaration_and_an_undeclared_caller(tmp_path: Path) -> None:
    from tap_plugins.validate.service import ValidationResult, _check_data_directory

    declared = _load(tmp_path, _TABLE)
    result = ValidationResult(ok=True, level="structure", plugin_path=str(tmp_path), strict=False)
    _check_data_directory(tmp_path, declared, result)
    check = result.checks[-1]
    assert check.status == "pass"
    assert check.details == {
        "declared": True,
        "durability": "cache",
        "purpose": "Datasets.",
        "max_bytes": 1024,
        "executes": False,
    }

    (tmp_path / "work.py").write_text("import tap_plugins\n\nROOT = tap_plugins.data_dir('acme')\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("from tap_plugins import data_dir as where\nwhere('acme')\n", encoding="utf-8")
    undeclared = _load(tmp_path, "")
    result = ValidationResult(ok=True, level="structure", plugin_path=str(tmp_path), strict=False)
    _check_data_directory(tmp_path, undeclared, result)
    check = result.checks[-1]
    assert check.status == "fail"
    assert sorted(str(m.path) for m in check.messages) == ["other.py", "work.py"]


# --------------------------------------------------------------------------- provisioning


@pytest.mark.spec("req-tap-plugin-datadir-provision-1")
def test_each_declared_directory_is_created_private(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    pd.declare("beta", "state")
    old = os.umask(0o002)
    try:
        run_gate()
    finally:
        os.umask(old)
    for slug in ("alpha", "beta"):
        st = (pd.volume / slug).lstat()
        assert stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
        assert stat.S_IMODE(st.st_mode) == 0o700


@pytest.mark.spec("req-tap-plugin-datadir-provision-2")
def test_a_second_boot_changes_nothing_unless_the_declaration_changed(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    (pd.volume / "alpha" / "data.db").write_bytes(b"plugin bytes")
    before = _snapshot(pd.volume / "alpha")
    _placement.reset_verdicts()
    run_gate()
    assert _snapshot(pd.volume / "alpha") == before

    pd.declare("alpha", max_bytes=8192)
    run_gate()
    after = _snapshot(pd.volume / "alpha")
    changed = {name for name in after if after[name] != before.get(name)}
    assert changed == {_provision.DESCRIPTION_FILENAME}, changed
    described = _provision.read_description(pd.volume / "alpha")
    assert described and described["max_bytes"] == 8192


@pytest.mark.spec("req-tap-plugin-datadir-provision-8")
def test_a_loose_mode_is_reset_and_logged(pd: Any, caplog: pytest.LogCaptureFixture) -> None:
    pd.enable()
    (pd.volume / "alpha").mkdir()
    (pd.volume / "alpha" / "data.db").write_bytes(b"kept")
    (pd.volume / "alpha").chmod(0o777)
    pd.declare("alpha")
    caplog.set_level(logging.WARNING, logger="tap_plugins.datadir._provision")
    run_gate()
    assert stat.S_IMODE((pd.volume / "alpha").stat().st_mode) == 0o700
    assert (pd.volume / "alpha" / "data.db").read_bytes() == b"kept"
    resets = [r for r in caplog.records if "reset" in r.getMessage()]
    assert len(resets) == 1 and "0777" in resets[0].getMessage() and "alpha" in resets[0].getMessage()
    caplog.clear()
    run_gate()
    assert not [r for r in caplog.records if "reset" in r.getMessage()]


@pytest.mark.spec("req-tap-plugin-datadir-provision-3")
def test_a_symbolic_link_is_refused_and_its_target_untouched(pd: Any, tmp_path: Path) -> None:
    pd.enable()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (pd.volume / "alpha").symlink_to(target)
    pd.declare("alpha")
    with pytest.raises(PluginDataGateError, match=r"alpha.*symbolic link"):
        run_gate()
    assert list(target.iterdir()) == []


@pytest.mark.spec("req-tap-plugin-datadir-provision-4")
def test_a_directory_owned_by_someone_else_is_refused_without_chown(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    (pd.volume / "alpha").mkdir(mode=0o700)
    pd.declare("alpha")
    real = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real + 1)
    chowned: list[Any] = []
    monkeypatch.setattr(os, "chown", lambda *a, **k: chowned.append(a))
    with pytest.raises(PluginDataGateError, match="owned by uid"):
        run_gate()
    assert chowned == []


@pytest.mark.spec("req-tap-plugin-datadir-provision-5")
def test_the_description_file_validates_and_agrees_with_the_manifest(pd: Any) -> None:
    pd.enable()
    declaration = pd.declare("alpha", "state", executes=True, max_bytes=777)
    run_gate()
    data = load_json_file(pd.volume / "alpha" / _provision.DESCRIPTION_FILENAME, schema=_provision.DESCRIPTION_SCHEMA)
    assert data["slug"] == "alpha"
    assert (data["durability"], data["purpose"], data["max_bytes"], data["executes"]) == (
        declaration.durability,
        declaration.purpose,
        declaration.max_bytes,
        declaration.executes,
    )
    assert data["location"] == "volume" and data["created_by_plugin_version"] == "1.2.3"


@pytest.mark.spec("req-tap-plugin-datadir-provision-6")
def test_the_cache_tag_follows_durability(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha", "cache")
    run_gate()
    tag = pd.volume / "alpha" / "CACHEDIR.TAG"
    assert tag.read_bytes()[:43] == b"Signature: 8a477f597d28d172789f06886806bc55"
    tag.unlink()
    run_gate()
    assert tag.read_bytes()[:43] == b"Signature: 8a477f597d28d172789f06886806bc55"
    pd.declare("alpha", "state")
    run_gate()
    assert not tag.exists()


@pytest.mark.spec("req-tap-plugin-datadir-provision-7")
def test_an_undeclared_plugin_gets_nothing(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    assert sorted(p.name for p in pd.volume.iterdir() if not p.name.startswith(".tap-")) == ["alpha"]


# --------------------------------------------------------------------------- mount gate


@pytest.mark.django_db
@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-1")
def test_state_without_a_volume_aborts_boot_naming_the_plugin(pd: Any, caplog: pytest.LogCaptureFixture) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    pd.declare("ledger", "state")
    caplog.set_level(logging.ERROR)
    with pytest.raises(CommandError, match="ledger"):
        call_command("boot", "--allow-empty")
    aborts = [r for r in caplog.records if getattr(r, "message_code", None) == ABORT_MESSAGE_CODE]
    assert len(aborts) == 1 and "ledger" in aborts[0].getMessage()


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-2")
def test_a_cache_without_a_volume_boots_ephemeral(pd: Any) -> None:
    pd.declare("alpha", "cache")
    records = run_gate()
    assert records == [
        {"slug": "alpha", "path": str(pd.ephemeral / "alpha"), "durability": "cache", "location": "ephemeral"}
    ]
    assert data_dir_is_ephemeral("alpha") is True
    assert _report.plugin_section("alpha", pd.declared["alpha"][0])["location"] == "ephemeral"
    described = _provision.read_description(pd.ephemeral / "alpha")
    assert described is not None and described["location"] == "ephemeral"


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-3")
def test_a_configured_root_on_the_root_device_aborts_whoever_is_installed(
    pd: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pd.enable()
    monkeypatch.setattr(volume_mount, "root_device", lambda: os.stat(pd.volume).st_dev)
    _placement.reset_verdicts()
    with pytest.raises(PluginDataGateError, match="not a mounted volume"):
        run_gate()
    pd.declare("alpha")
    with pytest.raises(PluginDataGateError, match="not a mounted volume"):
        run_gate()


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes through any mode")
@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-4")
def test_an_unwritable_root_aborts_with_the_os_error(pd: Any) -> None:
    pd.enable()
    pd.volume.chmod(0o500)
    try:
        with pytest.raises(PluginDataGateError, match="not writable: PermissionError"):
            run_gate()
    finally:
        pd.volume.chmod(0o700)


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-5")
def test_nothing_needed_nothing_required(pd: Any) -> None:
    assert run_gate() == []


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-6")
def test_boot_health_report_and_accessor_share_one_decision(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    real = volume_mount.check_volume

    def counting(root: Path) -> Any:
        calls.append(root)
        return real(root)

    monkeypatch.setattr(_placement, "check_volume", counting)
    pd.enable()
    pd.declare("alpha")
    run_gate()
    probe_plugin_data()
    _placement.reset_verdicts()
    _report.instance_section({"alpha"})
    _placement.reset_verdicts()
    data_dir("alpha")
    assert calls == [pd.volume] * 4
    import inspect

    for module in (_placement, _report, _purge, _facts, _provision):
        assert "st_dev == root_device" not in inspect.getsource(module)


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-7")
def test_a_failed_volume_provisions_nothing_ephemeral(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    monkeypatch.setattr(volume_mount, "root_device", lambda: os.stat(pd.volume).st_dev)
    _placement.reset_verdicts()
    pd.declare("alpha", "cache")
    with pytest.raises(PluginDataGateError):
        run_gate()
    assert not pd.ephemeral.exists()


@pytest.mark.spec("req-tap-plugin-datadir-mount-gate-8")
def test_execution_is_proven_at_boot(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    pd.declare("runner", executes=True)
    run_gate()
    assert not [p for p in (pd.volume / "runner").iterdir() if p.name.startswith(_provision.EXEC_PROBE_PREFIX)]

    def noexec(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", noexec)
    with pytest.raises(PluginDataGateError, match=r"runner.*executes = true.*PermissionError"):
        run_gate()
    assert not [p for p in (pd.volume / "runner").iterdir() if p.name.startswith(_provision.EXEC_PROBE_PREFIX)]


# --------------------------------------------------------------------------- accessor


@pytest.mark.spec("req-tap-plugin-datadir-accessor-1")
def test_the_accessor_returns_the_canonical_path(pd: Any, tmp_path: Path, settings: Any) -> None:
    link = tmp_path / "volume-link"
    link.symlink_to(pd.volume)
    settings.TAP_PLUGIN_DATA_ROOT = str(pd.volume)
    pd.declare("alpha")
    run_gate()
    first, second = data_dir("alpha"), data_dir("alpha")
    assert first == second == (pd.volume / "alpha").resolve()
    import tap_plugins

    assert tap_plugins.data_dir("alpha") == first


@pytest.mark.spec("req-tap-plugin-datadir-accessor-2")
def test_an_undeclared_or_unknown_plugin_is_refused(pd: Any) -> None:
    pd.enable()
    for slug in ("installed_without_table", "not_installed"):
        with pytest.raises(PluginDataDirectoryError, match="declares a \\[data_directory\\]"):
            data_dir(slug)
        assert not (pd.volume / slug).exists()


@pytest.mark.spec("req-tap-plugin-datadir-accessor-3")
@pytest.mark.parametrize("slug", ["a/b", "../x", "a.b", "Alpha", ""])
def test_an_invalid_slug_is_refused_before_any_filesystem_call(
    pd: Any, slug: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def touched(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an invalid slug got past the slug check")

    # The slug check is the first thing the accessor does; everything that reaches the
    # filesystem or the install set comes after it.
    monkeypatch.setattr(_placement, "volume_verdict", touched)
    monkeypatch.setattr(_placement, "declared_directories", touched)
    with pytest.raises(PluginDataDirectoryError, match="not a valid plugin slug"):
        data_dir(slug)


@pytest.mark.spec("req-tap-plugin-datadir-accessor-4")
def test_an_unusable_root_is_refused_with_the_gate_reason(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    monkeypatch.setattr(volume_mount, "root_device", lambda: os.stat(pd.volume).st_dev)
    _placement.reset_verdicts()
    with pytest.raises(PluginDataGateError) as gate:
        run_gate()
    with pytest.raises(PluginDataDirectoryError) as accessor:
        data_dir("alpha")
    assert str(accessor.value) == str(gate.value)


@pytest.mark.spec("req-tap-plugin-datadir-accessor-5")
def test_the_accessor_never_creates(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    pd.declare("alpha")
    made: list[Any] = []
    real_mkdir = os.mkdir

    def recording_mkdir(*args: Any, **kwargs: Any) -> None:
        made.append(args)
        real_mkdir(*args, **kwargs)

    monkeypatch.setattr(os, "mkdir", recording_mkdir)
    with pytest.raises(PluginDataDirectoryError, match="has not been provisioned"):
        data_dir("alpha")
    assert made == [] and not (pd.volume / "alpha").exists()


# --------------------------------------------------------------------------- sharing


@pytest.mark.spec("req-tap-plugin-datadir-sharing-1")
def test_the_authoring_guidance_states_both_halves() -> None:
    text = (_REPO / "tap_plugins" / "skills" / "new-plugin" / "SKILL.md").read_text(encoding="utf-8")
    assert "through that plugin's interface, never its files" in text
    assert "only the owning plugin" in text and "writes its directory" in text


# --------------------------------------------------------------------------- lifecycle (single process)


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-1")
def test_no_boot_load_probe_or_report_deletes_anything(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    (pd.volume / "alpha" / "keep.bin").write_bytes(b"x" * 100)
    (pd.volume / "orphan_one").mkdir()
    (pd.volume / "orphan_one" / "keep.txt").write_text("mine")
    (pd.volume / "stray.txt").write_text("not a directory")
    before = _snapshot(pd.volume)
    del pd.declared["alpha"]
    run_gate()
    from tap_plugins.datadir import on_plugin_loaded

    on_plugin_loaded("alpha", _decl(), "9.9.9")
    probe_plugin_data()
    _report.instance_section(set())
    _report.plugin_section("alpha", _decl())
    after = _snapshot(pd.volume)
    lost = set(before) - set(after)
    assert not lost, lost
    for name, (body, *_times) in before.items():
        if not name.startswith(".tap-") and "/.tap-" not in name:
            assert after[name][0] == body, name


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-2")
def test_a_removed_plugin_leaves_its_directory_as_an_orphan(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    (pd.volume / "alpha" / "state.db").write_bytes(b"\x00\x01\x02")

    def digest() -> str:
        h = hashlib.sha256()
        for entry in sorted((pd.volume / "alpha").rglob("*")):
            h.update(entry.name.encode() + (entry.read_bytes() if entry.is_file() else b""))
        return h.hexdigest()

    before = digest()
    del pd.declared["alpha"]
    _placement.reset_verdicts()
    run_gate()
    assert digest() == before
    assert _report.instance_section(set())["orphans"] == ["alpha"]


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-3")
def test_purge_needs_its_confirmations(pd: Any) -> None:
    pd.enable()
    pd.declare("cachey", "cache")
    pd.declare("stately", "state")
    run_gate()
    with pytest.raises(_purge.PurgeRefused, match="--yes"):
        _purge.purge(_purge.plan("cachey"), confirm=False, confirm_state=False)
    with pytest.raises(_purge.PurgeRefused, match="--delete-state"):
        _purge.purge(_purge.plan("stately"), confirm=True, confirm_state=False)
    assert (pd.volume / "cachey").is_dir() and (pd.volume / "stately").is_dir()
    # An orphan whose description is missing is treated as state.
    (pd.volume / "unknown_orphan").mkdir()
    with pytest.raises(_purge.PurgeRefused, match="--delete-state"):
        _purge.purge(_purge.plan("unknown_orphan"), confirm=True, confirm_state=False)
    _purge.purge(_purge.plan("stately"), confirm=True, confirm_state=True)
    assert not (pd.volume / "stately").exists()


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-4")
def test_purge_stays_inside_and_refuses_a_linked_top(pd: Any, tmp_path: Path) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    outside = tmp_path / "outside.txt"
    outside.write_text("precious")
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "inner.txt").write_text("also precious")
    (pd.volume / "alpha" / "link-to-file").symlink_to(outside)
    (pd.volume / "alpha" / "nested").mkdir()
    (pd.volume / "alpha" / "nested" / "link-to-dir").symlink_to(outside_dir)
    _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    assert not (pd.volume / "alpha").exists()
    assert outside.read_text() == "precious" and (outside_dir / "inner.txt").read_text() == "also precious"

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "file").write_text("keep")
    (pd.volume / "beta").symlink_to(elsewhere)
    with pytest.raises(_purge.PurgeRefused, match="symbolic link"):
        _purge.plan("beta")
    assert (elsewhere / "file").read_text() == "keep"


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-7")
def test_purge_proceeds_when_unused_and_does_not_refuse_itself(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()  # this process now holds alpha's lock shared, as a loaded plugin would
    _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    assert not (pd.volume / "alpha").exists()
    (pd.volume / "gone_plugin").mkdir()
    (pd.volume / "gone_plugin" / _provision.DESCRIPTION_FILENAME).write_text(
        json.dumps(_provision.description_for("gone_plugin", _decl(), "1.0", ephemeral=False))
    )
    _purge.purge(_purge.plan("gone_plugin"), confirm=True, confirm_state=False)
    assert not (pd.volume / "gone_plugin").exists()


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-11")
def test_the_lock_file_outlives_purge(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    lock = _lock.lock_path(pd.volume, "alpha")
    inode = lock.stat().st_ino
    _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    assert lock.stat().st_ino == inode
    classified = _report.instance_section({"alpha"})
    assert ".tap-locks" not in classified["orphans"] + classified["strays"]


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-12")
def test_the_lock_module_uses_flock_only() -> None:
    from tap.guards.discovery import discover_guards

    next(g for g in discover_guards() if g.slug == "plugin-data-flock-only").check()


@pytest.mark.django_db
@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-13")
def test_a_partial_purge_says_what_it_removed(
    pd: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    pd.enable()
    pd.declare("alpha", "cache")
    run_gate()
    for i in range(5):
        (pd.volume / "alpha" / f"f{i}").write_bytes(b"x" * 10)
    real_unlink = os.unlink
    calls = {"n": 0}

    def failing_second_unlink(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(5, "Input/output error")
        real_unlink(*args, **kwargs)

    monkeypatch.setattr(os, "unlink", failing_second_unlink)
    caplog.set_level(logging.WARNING, logger="tap_plugins.datadir._purge")
    with pytest.raises(CommandError) as raised:
        call_command("plugin_data", "purge", "alpha", "--yes")
    message = str(raised.value)
    assert message.startswith("Partially deleted: 1 entries") and "Nothing deleted" not in message
    records = [r for r in caplog.records if "purged alpha" in r.getMessage()]
    assert len(records) == 1 and records[0].__dict__["message_data"]["outcome"].startswith("incomplete")
    assert (pd.volume / "alpha").is_dir()

    calls["n"] = 1  # the next unlink is the second call: it fails before anything is removed
    with pytest.raises(CommandError, match="^Nothing deleted"):
        call_command("plugin_data", "purge", "alpha", "--yes")


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-5")
def test_a_purge_is_logged_once_with_actor_slug_and_counts(pd: Any, caplog: pytest.LogCaptureFixture) -> None:
    pd.enable()
    pd.declare("alpha", "state")
    run_gate()
    (pd.volume / "alpha" / "blob").write_bytes(b"y" * 5000)
    caplog.set_level(logging.WARNING, logger="tap_plugins.datadir._purge")
    removed = _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=True)
    records = [r for r in caplog.records if "purged alpha" in r.getMessage()]
    assert len(records) == 1
    data = records[0].__dict__["message_data"]
    assert data["slug"] == "alpha" and data["durability"] == "state"
    assert data["actor"] and f"uid {os.geteuid()}" in data["actor"]
    assert data["bytes_removed"] == removed["bytes"] > 0
    assert data["entries_removed"] == removed["entries"] == 2  # the blob and the description file


# --------------------------------------------------------------------------- report


@pytest.mark.spec("req-tap-plugin-datadir-report-1")
def test_the_declaration_appears_exactly(pd: Any) -> None:
    pd.enable()
    declaration = pd.declare("alpha", "state", max_bytes=123456, executes=True)
    run_gate()
    section = _report.plugin_section("alpha", declaration)
    assert (section["purpose"], section["durability"], section["max_bytes"], section["executes"]) == (
        declaration.purpose,
        "state",
        123456,
        True,
    )
    assert _report.plugin_section("other", None) == {"declared": False}


@pytest.mark.spec("req-tap-plugin-datadir-report-2")
def test_every_measurement_carries_its_time_and_completeness(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    measured = _report.plugin_section("alpha", pd.declared["alpha"][0])["measurement"]
    assert measured["available"] and measured["complete"] is True
    assert measured["measured_at"].endswith("Z") and measured["duration_ms"] >= 0


@pytest.mark.spec("req-tap-plugin-datadir-report-3")
def test_links_are_measured_by_their_own_size(pd: Any, tmp_path: Path) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(1024 * 1024))
    before = _facts.measure(pd.volume / "alpha")["allocated_bytes"]
    (pd.volume / "alpha" / "big-link").symlink_to(big)
    after = _facts.measure(pd.volume / "alpha")["allocated_bytes"]
    assert after - before < 64 * 1024, (before, after)


@pytest.mark.spec("req-tap-plugin-datadir-report-4")
def test_the_listing_is_cut_at_the_cap(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    for i in range(_facts.LISTING_CAP + 10):
        (pd.volume / "alpha" / f"f{i:03d}").write_text("x")
    listing = _report.plugin_section("alpha", pd.declared["alpha"][0])["listing"]
    assert len(listing["entries"]) == _facts.LISTING_CAP and listing["cut"] is True
    # Bounded: no more than cap + 1 names are read, however many there are.
    read: list[str] = []
    real_scandir = os.scandir

    class Counting:
        def __init__(self, target: Any) -> None:
            self._it = real_scandir(target)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: Any) -> None:
            self._it.close()

        def __iter__(self) -> Any:
            for entry in self._it:
                read.append(entry.name)
                yield entry

    monkeypatch.setattr(os, "scandir", Counting)
    _facts.listing(pd.volume / "alpha")
    assert len(read) == _facts.LISTING_CAP + 1
    assert {e["kind"] for e in listing["entries"]} <= {"file", "directory", "link", "other"}


@pytest.mark.spec("req-tap-plugin-datadir-report-5")
def test_orphans_and_strays_are_listed(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    (pd.volume / "left_behind").mkdir()
    (pd.volume / "notes.txt").write_text("stray")
    (pd.volume / "Not-A-Slug").mkdir()
    section = _report.instance_section({"alpha"})
    assert section["orphans"] == ["left_behind"]
    assert section["strays"] == ["Not-A-Slug", "notes.txt"]


@pytest.mark.django_db
@pytest.mark.spec("req-tap-plugin-datadir-report-6")
def test_the_schema_carries_the_facts_at_a_higher_version(pd: Any) -> None:
    from tap_plugins.report import SCHEMA_PATH, SCHEMA_VERSION, build_report

    assert SCHEMA_VERSION > 1
    pd.enable()
    declaration = pd.declare("alpha", "cache", executes=True)
    run_gate()
    report = build_report()  # validates against the published schema before returning
    assert report["schema_version"] == SCHEMA_VERSION
    record: dict[str, Any] = {
        "slug": "alpha",
        "name": "Alpha",
        "distribution": "alpha-tap",
        "version": None,
        "commit": None,
        "source": "unknown",
        "mode": "package",
        "app_config": "x.Y",
        "load_health": {"loaded": True, "manifest_valid": True, "detail": ""},
        "surfaces": {k: {"declared": 0, "loaded": None} for k in ("models", "edges", "editors", "searches", "grift")},
        "dependencies": {
            "depends_on": [],
            "required_by": [],
            "observed_imports": [],
            "undeclared_imports": [],
            "declared_detail": [],
        },
        "data_directory": _report.plugin_section("alpha", declaration),
    }
    validate_json(
        {
            "schema_version": SCHEMA_VERSION,
            "plugin_count": 1,
            "plugins": [record],
            "plugin_data": _report.instance_section({"alpha"}),
        },
        SCHEMA_PATH,
    )


@pytest.mark.spec("req-tap-plugin-datadir-report-8")
def test_ephemeral_is_said(pd: Any) -> None:
    pd.declare("alpha", "cache")
    run_gate()
    assert _report.plugin_section("alpha", pd.declared["alpha"][0])["location"] == "ephemeral"
    instance = _report.instance_section({"alpha"})
    assert instance["volume_enabled"] is False and instance["ephemeral_root"] == str(pd.ephemeral)


@pytest.mark.spec("req-tap-plugin-datadir-report-9")
def test_undeclared_executables_are_shown_and_left_alone(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha", executes=False)
    run_gate()
    tool = pd.volume / "alpha" / "bin" / "tool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    section = _report.plugin_section("alpha", pd.declared["alpha"][0])
    assert section["executables"] == ["bin/tool"]
    assert stat.S_IMODE(tool.stat().st_mode) == 0o755


@pytest.mark.spec("req-tap-plugin-datadir-report-7")
def test_a_walk_respects_its_budget(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    for i in range(300):
        (pd.volume / "alpha" / f"n{i}").write_text("x")
    measured = _facts.measure(pd.volume / "alpha", budget_s=0.0)
    assert measured["complete"] is False
    assert measured["duration_ms"] < 1000
    assert measured["entry_count"] < 300


# --------------------------------------------------------------------------- health


@pytest.mark.spec("req-tap-plugin-datadir-health-1")
def test_healthy_when_unused(pd: Any) -> None:
    result = probe_plugin_data()
    assert result.status == "healthy", result


@pytest.mark.spec("req-tap-plugin-datadir-health-5")
def test_ephemeral_caches_are_healthy(pd: Any) -> None:
    pd.declare("alpha", "cache")
    run_gate()
    result = probe_plugin_data()
    assert result.status == "healthy", result
    assert result.context["ephemeral"] == ["alpha"]


@pytest.mark.spec("req-tap-plugin-datadir-health-2")
def test_an_unmounted_volume_is_unhealthy_with_the_reason(pd: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    monkeypatch.setattr(volume_mount, "root_device", lambda: os.stat(pd.volume).st_dev)
    result = probe_plugin_data()
    assert result.status == "unhealthy" and "not a mounted volume" in (result.detail or "")


@pytest.mark.spec("req-tap-plugin-datadir-health-3")
def test_each_bad_directory_is_named(pd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pd.enable()
    for slug in ("missing_one", "linked_one", "unwritable_one", "fine_one"):
        pd.declare(slug)
    run_gate()
    import shutil

    shutil.rmtree(pd.volume / "missing_one")
    shutil.rmtree(pd.volume / "linked_one")
    (pd.volume / "linked_one").symlink_to(tmp_path)
    real_probe = volume_mount.write_probe
    monkeypatch.setattr(
        volume_mount,
        "write_probe",
        lambda p: "PermissionError: denied" if p.name == "unwritable_one" else real_probe(p),
    )
    result = probe_plugin_data()
    assert result.status == "unhealthy"
    assert sorted(result.context["bad"]) == ["linked_one", "missing_one", "unwritable_one"]

    shutil.rmtree(pd.volume / "fine_one")
    (pd.volume / "fine_one").mkdir(mode=0o700)
    real = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real + 1)
    assert "fine_one" in probe_plugin_data().context["bad"]


@pytest.mark.spec("req-tap-plugin-datadir-health-4")
def test_orphans_do_not_fail_it(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha")
    run_gate()
    (pd.volume / "orphaned").mkdir()
    result = probe_plugin_data()
    assert result.status == "healthy", result
    assert result.context["orphans"] == ["orphaned"]


# --------------------------------------------------------------------------- backup facts and non-goals


@pytest.mark.spec("req-tap-plugin-datadir-backup-facts-1")
def test_durability_is_recoverable_from_the_description_file_alone(pd: Any) -> None:
    pd.enable()
    pd.declare("alpha", "cache")
    pd.declare("beta", "state")
    run_gate()
    for slug, durability in (("alpha", "cache"), ("beta", "state")):
        raw = json.loads((pd.volume / slug / ".tap-plugin-dir.json").read_text(encoding="utf-8"))
        assert raw["durability"] == durability


@pytest.mark.spec("req-tap-plugin-datadir-nongoals-1")
def test_the_non_goals_are_listed_with_their_homes() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    section = text.split("### v0 Non-Goals", 1)[1].split("#### Acceptance Criteria", 1)[0]
    for omission in (
        "No grid representation",
        "No mediation of file I/O",
        "No isolation between plugins",
        "No automatic cleanup",
        "No size enforcement",
        "No remote storage",
        "No backup or restore",
        "No more than one directory",
        "No sharing of one plugin data volume",
    ):
        assert omission in section, omission
    for backlog in ("Shared Helpers", "Using The Declared Size", "Free-Space Floor"):
        assert f"### {backlog}" in text
    assert "Both are Backlog requirements above" in section
