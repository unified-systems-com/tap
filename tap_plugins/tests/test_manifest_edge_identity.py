"""An edge definition file may carry an ``identity`` member, and both load and validate read it.

Spec: ``req-tap-plugin-manifest-v0-edge-identity`` in
``tap_plugins/specs/spec-tap-plugin-manifest-v0.md``; the declaration's own rules are
``req-grid-edge-identity-declaration`` in ``tap_grid/specs/spec-grid-edge.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tap_plugins.manifest import EdgeEntry, PluginManifestError, _load_edge_file
from tap_plugins.validate.service import ValidationResult, _check_edge_files

SPEC_1 = pytest.mark.spec("req-tap-plugin-manifest-v0-edge-identity-1")
SPEC_2 = pytest.mark.spec("req-tap-plugin-manifest-v0-edge-identity-2")

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"scope": {"type": "string", "enum": ["runtime", "test"]}}}
SCOPE = {"path": "scope", "description": "The dependency scope; in the key because two can hold at once."}


def _definition(**extra: Any) -> dict[str, Any]:
    return {
        "slug": "DEPENDS_ON",
        "name": "Depends on",
        "description": "A package depends on another package.",
        "sources": ["package"],
        "targets": ["package"],
        **extra,
    }


def _load(tmp_path: Path, data: dict[str, Any]) -> EdgeEntry:
    edge_file = tmp_path / "edges" / "depends_on.edge.json"
    edge_file.parent.mkdir(parents=True, exist_ok=True)
    edge_file.write_text(json.dumps(data))
    return _load_edge_file("DEPENDS_ON", "edges/depends_on.edge.json", edge_file, tmp_path / "tap-plugin.toml")


class TestTheLoaderReadsIt:
    @SPEC_1
    def test_a_declaration_rides_the_edge_entry(self, tmp_path: Path) -> None:
        entry = _load(tmp_path, _definition(property_schema=SCHEMA, identity={"discriminators": [SCOPE]}))
        assert entry.identity == {"discriminators": [SCOPE]}

    @SPEC_1
    def test_the_member_is_optional(self, tmp_path: Path) -> None:
        assert _load(tmp_path, _definition()).identity is None

    @SPEC_1
    @pytest.mark.parametrize(
        "identity",
        [
            {"discriminators": [], "keyless": {"reason": "both"}},
            {},
            {"discriminators": ["scope"]},
            {"discriminators": [{"path": "scope"}]},
            {"keyless": {}},
            {"keyless": {"reason": ""}},
            {"discriminators": [], "extra": 1},
        ],
    )
    def test_the_schema_refuses_a_malformed_declaration(self, tmp_path: Path, identity: Any) -> None:
        with pytest.raises(PluginManifestError):
            _load(tmp_path, _definition(property_schema=SCHEMA, identity=identity))


def _validate(entry: EdgeEntry) -> ValidationResult:
    result = ValidationResult(ok=True, level="full", plugin_path="/plugin", strict=False)
    _check_edge_files(SimpleNamespace(edges=[entry]), result)
    return result


class TestValidatePluginSeesWhatBootWouldRefuse:
    @SPEC_2
    def test_a_discriminator_the_property_schema_does_not_declare_fails(self, tmp_path: Path) -> None:
        bad = {"path": "priority", "description": "x"}
        entry = _load(tmp_path, _definition(property_schema=SCHEMA, identity={"discriminators": [bad]}))
        (check,) = _validate(entry).checks
        assert check.status == "fail"
        assert any("priority" in m.text for m in check.messages)

    @SPEC_2
    def test_discriminators_with_no_property_schema_fail(self, tmp_path: Path) -> None:
        entry = _load(tmp_path, _definition(identity={"discriminators": [SCOPE]}))
        (check,) = _validate(entry).checks
        assert check.status == "fail"

    @SPEC_2
    def test_a_sound_declaration_passes(self, tmp_path: Path) -> None:
        entry = _load(tmp_path, _definition(property_schema=SCHEMA, identity={"discriminators": [SCOPE]}))
        (check,) = _validate(entry).checks
        assert check.status == "pass"
