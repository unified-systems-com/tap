"""Plugin release SBOM lane — pure-function tests (req-cicd-sbom-10).

Orchestration (build + syft over the wheel) runs in the reusable release
workflow; the decision-bearing pieces — identity gate, minimum-elements-lite,
the slug→dist convention — are pure functions tested here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "sbom_plugin_release", _REPO_ROOT / "scripts" / "sbom" / "plugin_release.py"
)
assert _spec is not None and _spec.loader is not None
plug = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plug)


def _wheel_cdx(name: str, version: str) -> dict[str, object]:
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:3e671687-395b-41f5-a30f-a58921a69b79",
        "version": 1,
        "metadata": {
            "timestamp": "2026-08-20T00:00:00Z",
            "tools": {"components": [{"type": "application", "name": "syft", "version": "1.51.0"}]},
        },
        "components": [
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{name}@{version}",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            }
        ],
    }


def test_slug_to_dist_convention() -> None:
    assert plug.dist_name_for("aws_core") == "tap-plugin-aws-core"
    assert plug.dist_name_for("samsite") == "tap-plugin-samsite"


@pytest.mark.spec("req-cicd-sbom-10-1")
def test_identity_gate_passes_on_matching_wheel() -> None:
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    assert plug.check_plugin_identity(doc, "aws_core", "0.4.1") == []


@pytest.mark.spec("req-cicd-sbom-10-1")
def test_identity_gate_catches_version_mismatch() -> None:
    """Tag says 0.4.2, wheel built 0.4.1 (e.g. shallow checkout broke hatch-vcs)."""
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    problems = plug.check_plugin_identity(doc, "aws_core", "0.4.2")
    assert any("version mismatch" in p for p in problems)


@pytest.mark.spec("req-cicd-sbom-10-2")
def test_identity_gate_catches_absent_plugin_component() -> None:
    doc = _wheel_cdx("something-else", "1.0")
    problems = plug.check_plugin_identity(doc, "aws_core", "0.4.1")
    assert any("ABSENT" in p for p in problems)


@pytest.mark.spec("req-cicd-sbom-10-2")
def test_identity_gate_catches_phantoms() -> None:
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    components = doc["components"]
    assert isinstance(components, list)
    components.append({"type": "library", "bom-ref": "x", "name": "my-test-package", "version": "1.0"})
    problems = plug.check_plugin_identity(doc, "aws_core", "0.4.1")
    assert any("phantom" in p for p in problems)


@pytest.mark.spec("req-cicd-sbom-10-3")
def test_minimum_elements_lite_exempts_dependency_graph() -> None:
    """A wheel declares requirements; it does not resolve them — no graph required."""
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    plug.inject_coverage(doc, "test coverage")
    assert plug.check_minimum_elements_wheel(doc) == []


@pytest.mark.spec("req-cicd-sbom-10-3")
def test_minimum_elements_lite_still_fails_closed_on_structure() -> None:
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    plug.inject_coverage(doc, "x")
    meta = doc["metadata"]
    assert isinstance(meta, dict)
    del meta["timestamp"]
    assert any("timestamp" in p for p in plug.check_minimum_elements_wheel(doc))


def test_injected_coverage_survives_schema_validation() -> None:
    doc = _wheel_cdx("tap-plugin-aws-core", "0.4.1")
    plug.inject_coverage(doc, "coverage statement")
    plug._gen.validate_schema(doc, "cyclonedx")
