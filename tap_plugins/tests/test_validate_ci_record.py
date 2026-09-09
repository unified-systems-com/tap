"""The `ci` boot record check (req-boot-bootstrap-ci-record; wired by req-tap-plugin-extdev-repo-ci).

A plugin without an in-package CI record has its suite run by nobody, so the record's ABSENCE is a
warning and, under --strict (the conformance gate), a failure. Presence is held to correctness:
declared with a matching digest, closed over depends_on + self, credential-free, aborting on a
half-boot. The retired repo-root form is accepted through ``ci_record=`` as a deprecation road.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

from tap_plugins.validate.service import CheckResult, ValidationResult, validate_plugin

_MIN_TOML = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "test_plugin"\nname = "T"\n'


def _make_plugin(tmp_path: Path, *, toml: str, extra_files: dict[str, str] | None = None) -> Path:
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "tap-plugin.toml").write_text(textwrap.dedent(toml))
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "apps.py").write_text(
        "from tap_plugins.base import TapPluginConfig\n\n\nclass TestPluginConfig(TapPluginConfig):\n    pass\n"
    )
    for rel_path, content in (extra_files or {}).items():
        full = plugin_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return plugin_dir


def _check(result: ValidationResult) -> CheckResult:
    matches = [c for c in result.checks if c.id == "ci-record"]
    assert len(matches) == 1
    return matches[0]


def _record(
    *,
    slugs: list[str],
    on_failure: str | None = "abort",
    secrets: bool = False,
    credential: bool = False,
    description: str = "the test stack",
) -> str:
    plugins = []
    for slug in slugs:
        source: dict[str, object] = {"type": "git", "url": f"https://example.invalid/{slug}", "rev": "v1"}
        if credential:
            source["credential"] = {"scope": "x", "key": "y"}
        plugins.append({"slug": slug, "enabled": True, "source": source})
    data: dict[str, object] = {"version": 1, "description": description, "install": {"plugins": plugins}}
    if on_failure is not None:
        data["population"] = {"on_failure": on_failure, "steps": []}
    else:
        data["population"] = {"steps": []}
    if secrets:
        data["required_secrets"] = [{"scope": "x", "key": "y", "kind": "github"}]
    return json.dumps(data)


def _digest(record_text: str) -> str:
    canon = json.dumps(json.loads(record_text), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _declared(record_text: str, *, digest: str | None = None) -> str:
    return (
        _MIN_TOML
        + '[[boot.records]]\nname = "ci"\ndescription = "the test stack"\nsha256 = "'
        + (digest or _digest(record_text))
        + '"\n'
    )


class TestAbsence:
    def test_absent_warns_and_strict_fails(self, tmp_path: Path) -> None:
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML)
        result = validate_plugin(plugin)
        check = _check(result)
        assert check.status == "warn"
        assert "req-boot-bootstrap-ci-record-6" in check.messages[0].text
        assert result.ok is True
        strict = validate_plugin(plugin, strict=True)
        assert _check(strict).status == "fail"
        assert strict.ok is False

    def test_legacy_record_is_a_deprecation_notice_not_a_failure(self, tmp_path: Path) -> None:
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML)
        legacy = tmp_path / "ci" / "nightly.boot.json"
        legacy.parent.mkdir()
        legacy.write_text(_record(slugs=["test_plugin"]))
        result = validate_plugin(plugin, strict=True, ci_record=legacy)
        check = _check(result)
        assert check.status == "pass", [m.text for m in check.messages]
        assert any("retired" in m.text for m in check.messages)

    def test_legacy_record_missing_file_fails(self, tmp_path: Path) -> None:
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML)
        result = validate_plugin(plugin, ci_record=tmp_path / "ci" / "nope.json")
        assert _check(result).status == "fail"


class TestPresence:
    def test_declared_coherent_record_passes_strict(self, tmp_path: Path) -> None:
        record = _record(slugs=["test_plugin"])
        plugin = _make_plugin(tmp_path, toml=_declared(record), extra_files={"boot/ci.boot.json": record})
        result = validate_plugin(plugin, strict=True)
        assert _check(result).status == "pass", [m.text for m in _check(result).messages]

    def test_undeclared_record_fails(self, tmp_path: Path) -> None:
        record = _record(slugs=["test_plugin"])
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML, extra_files={"boot/ci.boot.json": record})
        check = _check(validate_plugin(plugin))
        assert check.status == "fail"
        assert "not declared" in check.messages[0].text

    def test_stale_digest_fails(self, tmp_path: Path) -> None:
        record = _record(slugs=["test_plugin"])
        plugin = _make_plugin(
            tmp_path, toml=_declared(record, digest="0" * 64), extra_files={"boot/ci.boot.json": record}
        )
        check = _check(validate_plugin(plugin))
        assert check.status == "fail"
        assert "does not match" in check.messages[0].text

    def test_missing_self_fails(self, tmp_path: Path) -> None:
        record = _record(slugs=["other"])
        plugin = _make_plugin(tmp_path, toml=_declared(record), extra_files={"boot/ci.boot.json": record})
        texts = [m.text for m in _check(validate_plugin(plugin)).messages if m.severity == "error"]
        assert any("does not install 'test_plugin' itself" in t for t in texts)

    def test_missing_declared_dependency_fails_and_extra_is_informational(self, tmp_path: Path) -> None:
        toml = _MIN_TOML + 'depends_on = [{ slug = "dep_a" }]\n'
        record = _record(slugs=["test_plugin", "transitive_b"])
        toml = toml + '[[boot.records]]\nname = "ci"\ndescription = "d"\nsha256 = "' + _digest(record) + '"\n'
        plugin = _make_plugin(tmp_path, toml=toml, extra_files={"boot/ci.boot.json": record})
        check = _check(validate_plugin(plugin))
        errors = [m.text for m in check.messages if m.severity == "error"]
        infos = [m.text for m in check.messages if m.severity == "info"]
        assert any("declared dependency 'dep_a'" in t for t in errors)
        assert any("transitive_b" in t and "assumed transitive" in t for t in infos)

    def test_credentials_and_secrets_fail(self, tmp_path: Path) -> None:
        record = _record(slugs=["test_plugin"], secrets=True, credential=True)
        plugin = _make_plugin(tmp_path, toml=_declared(record), extra_files={"boot/ci.boot.json": record})
        errors = [m.text for m in _check(validate_plugin(plugin)).messages if m.severity == "error"]
        assert any("required_secrets" in t for t in errors)
        assert any("source credential" in t for t in errors)

    def test_on_failure_must_abort(self, tmp_path: Path) -> None:
        record = _record(slugs=["test_plugin"], on_failure=None)
        plugin = _make_plugin(tmp_path, toml=_declared(record), extra_files={"boot/ci.boot.json": record})
        errors = [m.text for m in _check(validate_plugin(plugin)).messages if m.severity == "error"]
        assert any("on_failure" in t for t in errors)


class TestCoreVersionOverride:
    """The reusable CI validates from the workflow's tooling but checks the floor against the harness."""

    def test_explicit_core_version_decides_the_floor_check(self, tmp_path: Path) -> None:
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML + 'requires_tap = ">=0.1.4,<0.1.5"\n')
        satisfied = validate_plugin(plugin, core_version="0.1.4")
        assert [c for c in satisfied.checks if c.id == "requires-tap"][0].status == "pass"
        unsatisfied = validate_plugin(plugin, core_version="0.9.0")
        assert [c for c in unsatisfied.checks if c.id == "requires-tap"][0].status == "fail"
