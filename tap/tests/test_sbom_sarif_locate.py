"""SBOM-sourced SARIF gets a location before upload (req-cicd-security-scanning-5, tap#294).

Grype scanning a CycloneDX document emits results with an empty artifact location, which
Code Scanning rejects wholesale. `scripts/sbom/sarif_locate.py` stamps each result with the
supplemental manifest that declared the component, at that component's entry line. These
tests pin the stamping semantics against synthetic SARIF and the REAL manifests.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_sarif_locate", _REPO_ROOT / "scripts" / "sbom" / "sarif_locate.py")
assert _spec is not None and _spec.loader is not None
locate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(locate_mod)

_WEB_MANIFEST = _REPO_ROOT / "docker" / "sbom-supplemental.json"
_DB_MANIFEST = _REPO_ROOT / "docker" / "postgres" / "sbom-supplemental.json"


def _grype_result(rule_id: str, *, locations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The shape Grype 0.118 emits for an SBOM scan: one location, empty uri, 1:1 region."""
    if locations is None:
        locations = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": ""},
                    "region": {"startLine": 1, "startColumn": 1, "endLine": 1, "endColumn": 1},
                }
            }
        ]
    return {"ruleId": rule_id, "level": "error", "message": {"text": "x"}, "locations": locations}


def _sarif(*results: dict[str, Any]) -> dict[str, Any]:
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "grype"}}, "results": list(results)}]}


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_real_manifests_yield_a_line_per_declared_component() -> None:
    """Every component the real manifests declare resolves to the line of its `"name"` entry."""
    for manifest in (_WEB_MANIFEST, _DB_MANIFEST):
        declared = {c["name"] for c in json.loads(manifest.read_text(encoding="utf-8"))["components"]}
        lines = locate_mod.declaration_lines(manifest)
        assert set(lines) == declared, manifest
        text = manifest.read_text(encoding="utf-8").splitlines()
        for name, n in lines.items():
            assert f'"name": "{name}"' in text[n - 1], (manifest, name, n)


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_empty_location_is_stamped_with_manifest_and_component_line() -> None:
    lines = locate_mod.declaration_lines(_WEB_MANIFEST)
    doc = _sarif(_grype_result("CVE-2024-6119-openssl-fips-provider"), _grype_result("GHSA-xxxx-uv"))
    stamped, unresolved = locate_mod.locate(doc, "docker/sbom-supplemental.json", lines)
    assert (stamped, unresolved) == (2, 0)
    first, second = doc["runs"][0]["results"]
    loc = first["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"] == {"uri": "docker/sbom-supplemental.json", "uriBaseId": "%SRCROOT%"}
    assert loc["region"] == {"startLine": lines["openssl-fips-provider"]}
    assert second["locations"][0]["physicalLocation"]["region"] == {"startLine": lines["uv"]}


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_result_without_locations_gets_one() -> None:
    doc = _sarif(_grype_result("CVE-1-uvx", locations=[]))
    stamped, _ = locate_mod.locate(doc, "docker/sbom-supplemental.json", {"uvx": 7})
    assert stamped == 1
    assert doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"] == {"startLine": 7}


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_unknown_component_still_lands_on_the_manifest_at_line_one() -> None:
    """A rule id naming nothing we declared is counted, not dropped: the upload must still succeed."""
    doc = _sarif(_grype_result("CVE-1-something-else"))
    stamped, unresolved = locate_mod.locate(doc, "docker/sbom-supplemental.json", {"uv": 3})
    assert (stamped, unresolved) == (1, 1)
    loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "docker/sbom-supplemental.json"
    assert loc["region"] == {"startLine": 1}


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_existing_location_is_left_alone() -> None:
    located = [{"physicalLocation": {"artifactLocation": {"uri": "some/file.txt"}, "region": {"startLine": 9}}}]
    doc = _sarif(_grype_result("CVE-1-uv", locations=located))
    before = copy.deepcopy(doc)
    assert locate_mod.locate(doc, "docker/sbom-supplemental.json", {"uv": 3}) == (0, 0)
    assert doc == before


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_longest_declared_name_wins() -> None:
    doc = _sarif(_grype_result("CVE-1-foo-uv"))
    locate_mod.locate(doc, "m.json", {"uv": 3, "foo-uv": 5})
    assert doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"] == {"startLine": 5}


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_cli_rewrites_in_place_per_image(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The image key maps to the manifest that built the scanned document — tap-db is the
    postgres manifest, not the web one — and the file is rewritten in place."""
    path = tmp_path / "results.sarif"
    path.write_text(json.dumps(_sarif(_grype_result("CVE-1-openssl-fips-provider"))), encoding="utf-8")
    assert locate_mod.main(["--image", "tap-db", "--sarif", str(path)]) == 0
    out = json.loads(path.read_text(encoding="utf-8"))
    loc = out["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "docker/postgres/sbom-supplemental.json"
    assert loc["region"]["startLine"] == locate_mod.declaration_lines(_DB_MANIFEST)["openssl-fips-provider"]
    assert "1 of 1 result(s) located on docker/postgres/sbom-supplemental.json" in capsys.readouterr().out


@pytest.mark.spec("req-cicd-security-scanning-5")
def test_cli_refuses_a_non_sarif_document(tmp_path: Path) -> None:
    path = tmp_path / "not.sarif"
    path.write_text('{"bomFormat": "CycloneDX"}', encoding="utf-8")
    assert locate_mod.main(["--image", "tap-web", "--sarif", str(path)]) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"bomFormat": "CycloneDX"}, "must not rewrite on refusal"
