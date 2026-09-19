"""The manifest's ``[falsifiers]`` table: parsed like ``[searches]``, owned types only, registered
at ``ready()`` into ``tap_grid.falsifiers``; and validate_plugin's two checks — every row imports
and subclasses ``Falsifier``, and every containment target the plugin owns has a row (coverage is
a WARNING, promoted by ``--strict``; req-grid-reconcile-falsifier-2). Issue# 644 - tap.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tap_grid.falsifiers import Falsifier, registered_falsifiers, unregister_falsifier
from tap_plugins.manifest import PluginManifestError, load_manifest
from tap_plugins.tests.test_validate_service import _MIN_TOML, _make_plugin, _named_check
from tap_plugins.validate.service import ValidationResult, _check_falsifier_classes, _check_falsifier_coverage

FAKE_MODULE = "tap_plugin_test_falsifiers"


class _Good(Falsifier):
    pass


class _NotAFalsifier:
    pass


@pytest.fixture(autouse=True)
def fake_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A module the class paths resolve to, without a real plugin on the path."""
    module = types.ModuleType(FAKE_MODULE)
    module.Good = _Good  # type: ignore[attr-defined]
    module.NotAFalsifier = _NotAFalsifier  # type: ignore[attr-defined]

    class Parent:
        ENTITY_TYPE = "test_plugin__parent"
        CONTAINMENT_EDGES = ("HOLDS__test_plugin",)

    class Child:
        ENTITY_TYPE = "test_plugin__child"

    class Loner:
        ENTITY_TYPE = "test_plugin__loner"

    module.Parent, module.Child, module.Loner = Parent, Child, Loner  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    yield module
    for entity_type in ("test_plugin__child", "test_plugin__parent"):
        unregister_falsifier(entity_type)


MODELS = f"""
[models]
test_plugin__parent = "{FAKE_MODULE}.Parent"
test_plugin__child = "{FAKE_MODULE}.Child"
test_plugin__loner = "{FAKE_MODULE}.Loner"
"""


def _edge(slug: str, targets: list[str] | None) -> str:
    body: dict[str, Any] = {"slug": slug, "name": slug, "description": f"fixture edge {slug}"}
    if targets is not None:
        body["targets"] = targets
    return json.dumps(body)


def _plugin(tmp_path: Path, *, falsifiers: str = "", targets: list[str] | None | str = "child") -> Path:
    edge_targets: list[str] | None = ["test_plugin__child"] if targets == "child" else targets  # type: ignore[assignment]
    toml = _MIN_TOML + MODELS + '[edges]\nHOLDS__test_plugin = "edges/HOLDS.edge.json"\n' + falsifiers
    files = {"edges/HOLDS.edge.json": _edge("HOLDS__test_plugin", edge_targets), "models/__init__.py": ""}
    return _make_plugin(tmp_path, toml=toml, extra_files=files)


def _result(plugin_dir: Path) -> ValidationResult:
    return ValidationResult(ok=True, level="loads", plugin_path=str(plugin_dir), strict=False)


@pytest.mark.spec("req-tap-plugin-manifest-v0-falsifiers-1")
@pytest.mark.spec("req-tap-plugin-manifest-v0-falsifiers-2")
class TestParse:
    def test_rows_parse_for_owned_types(self, tmp_path: Path) -> None:
        manifest = load_manifest(
            _plugin(tmp_path, falsifiers=f'[falsifiers]\ntest_plugin__child = "{FAKE_MODULE}.Good"\n')
        )
        [entry] = manifest.falsifiers
        assert (entry.entity_type, entry.class_path) == ("test_plugin__child", f"{FAKE_MODULE}.Good")

    def test_absent_table_is_empty(self, tmp_path: Path) -> None:
        assert load_manifest(_plugin(tmp_path)).falsifiers == []

    def test_a_row_for_a_type_the_plugin_does_not_own_is_a_manifest_error(self, tmp_path: Path) -> None:
        with pytest.raises(PluginManifestError, match="does not declare in \\[models\\]"):
            load_manifest(_plugin(tmp_path, falsifiers=f'[falsifiers]\ngithub_core__repo = "{FAKE_MODULE}.Good"\n'))

    def test_a_non_string_path_is_a_manifest_error(self, tmp_path: Path) -> None:
        with pytest.raises(PluginManifestError, match="non-empty string class path"):
            load_manifest(_plugin(tmp_path, falsifiers="[falsifiers]\ntest_plugin__child = 3\n"))

    def test_a_non_table_is_a_manifest_error(self, tmp_path: Path) -> None:
        toml = _MIN_TOML + 'falsifiers = "nope"\n' + MODELS
        plugin = _make_plugin(tmp_path, toml=toml, extra_files={"models/__init__.py": ""})
        with pytest.raises(PluginManifestError, match="must be a table"):
            load_manifest(plugin)


@pytest.mark.spec("req-tap-plugin-manifest-v0-falsifiers-3")
class TestRegistration:
    def test_ready_registers_each_row_into_the_grid_registry(self, tmp_path: Path) -> None:
        from tap_plugins.base import TapPluginConfig

        manifest = load_manifest(
            _plugin(tmp_path, falsifiers=f'[falsifiers]\ntest_plugin__child = "{FAKE_MODULE}.Good"\n')
        )
        config = TapPluginConfig.__new__(TapPluginConfig)
        config._manifest = manifest
        TapPluginConfig._register_falsifiers_from_manifest(config)
        registered = registered_falsifiers()
        assert isinstance(registered["test_plugin__child"], _Good)
        assert registered["test_plugin__child"].entity_type == "test_plugin__child"


@pytest.mark.spec("req-grid-reconcile-falsifier-2")
@pytest.mark.spec("req-tap-plugin-manifest-v0-falsifiers-4")
@pytest.mark.spec("req-tap-plugin-validate-codepaths-5")
class TestValidateChecks:
    def test_classes_check_passes_a_falsifier_subclass(self, tmp_path: Path) -> None:
        plugin = _plugin(tmp_path, falsifiers=f'[falsifiers]\ntest_plugin__child = "{FAKE_MODULE}.Good"\n')
        result = _result(plugin)
        _check_falsifier_classes(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-classes")
        assert check.status == "pass" and any("test_plugin__child" in m.text for m in check.messages)

    def test_classes_check_fails_a_non_subclass_and_a_bad_import(self, tmp_path: Path) -> None:
        plugin = _plugin(
            tmp_path,
            falsifiers=f'[falsifiers]\ntest_plugin__child = "{FAKE_MODULE}.NotAFalsifier"\n'
            f'test_plugin__parent = "{FAKE_MODULE}.Missing"\n',
        )
        result = _result(plugin)
        _check_falsifier_classes(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-classes")
        assert check.status == "fail"
        texts = " ".join(m.text for m in check.messages)
        assert "not a tap_grid.falsifiers.Falsifier subclass" in texts and "Cannot import" in texts

    def test_coverage_warns_per_uncovered_containment_target(self, tmp_path: Path) -> None:
        plugin = _plugin(tmp_path)
        result = _result(plugin)
        _check_falsifier_coverage(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-coverage")
        warnings = [m for m in check.messages if m.severity == "warning"]
        assert [m.path for m in warnings] == ["test_plugin__child"], "the child is a target; parent and loner are not"
        assert "never be retired" in warnings[0].text
        assert check.status == "warn" and result.ok, "a ratchet: warnings are not failures by default"

    def test_coverage_is_silent_when_the_target_has_a_row(self, tmp_path: Path) -> None:
        plugin = _plugin(tmp_path, falsifiers=f'[falsifiers]\ntest_plugin__child = "{FAKE_MODULE}.Good"\n')
        result = _result(plugin)
        _check_falsifier_coverage(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-coverage")
        assert check.status == "pass" and not [m for m in check.messages if m.severity == "warning"]

    def test_a_wildcard_containment_edge_makes_every_owned_model_reconcilable(self, tmp_path: Path) -> None:
        plugin = _plugin(tmp_path, targets=None)
        result = _result(plugin)
        _check_falsifier_coverage(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-coverage")
        assert sorted(m.path or "" for m in check.messages if m.severity == "warning") == [
            "test_plugin__child",
            "test_plugin__loner",
            "test_plugin__parent",
        ]

    def test_no_containment_means_not_applicable(self, tmp_path: Path) -> None:
        toml = _MIN_TOML + f'[models]\ntest_plugin__loner = "{FAKE_MODULE}.Loner"\n'
        plugin = _make_plugin(tmp_path, toml=toml, extra_files={"models/__init__.py": ""})
        result = _result(plugin)
        _check_falsifier_coverage(load_manifest(plugin), result)
        check = _named_check(result, "falsifier-coverage")
        assert check.status == "pass" and any("not applicable" in m.text for m in check.messages)

    def test_strict_promotes_the_coverage_warning(self, tmp_path: Path) -> None:
        from tap_plugins.validate.service import validate_plugin

        plugin = _plugin(tmp_path)
        lenient = validate_plugin(plugin, level="loads")
        strict = validate_plugin(plugin, level="loads", strict=True)
        assert _named_check(lenient, "falsifier-coverage").status == "warn"
        assert _named_check(strict, "falsifier-coverage").status == "fail" and not strict.ok
