"""SBOM generation lane — pure-function tests (spec-cicd-sbom.md).

scripts/sbom/generate.py's orchestration (docker + syft) runs only in the
publish pipeline; everything decision-bearing — supplemental loading/schema,
injection into both formats, conformance minimum-elements, canaries, vendored
schema validation — is a pure function tested here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_generate", _REPO_ROOT / "scripts" / "sbom" / "generate.py")
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

WEB_SUPPLEMENTAL = _REPO_ROOT / "docker" / "sbom-supplemental.json"
DB_SUPPLEMENTAL = _REPO_ROOT / "docker" / "postgres" / "sbom-supplemental.json"


def _minimal_cdx(components: list[dict[str, object]]) -> dict[str, object]:
    """A minimal-but-conformant CycloneDX 1.6 document, as syft would emit."""
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
        "components": components,
        "dependencies": [{"ref": components[0]["bom-ref"]}] if components else [],
    }


def _component(name: str, version: str = "1.0", **extra: object) -> dict[str, object]:
    return {
        "type": "library",
        "bom-ref": f"pkg:{name}",
        "name": name,
        "version": version,
        "purl": f"pkg:generic/{name}@{version}",
        **extra,
    }


def _web_base_components() -> list[dict[str, object]]:
    return [
        _component("tap", "0.1.3"),
        _component("django", "6.0.8"),
        _component("openssl", "3.6.3"),
        # The js-vendor lockfile closure (req-cicd-sbom-13): canaried so a
        # silently-dropped package-lock seam reds the publish.
        _component("htmx.org", "2.0.4"),
        _component("echarts", "6.1.0"),
        _component("tabulator-tables", "6.3.0"),
        _component("cytoscape", "3.30.4"),
    ]


FAKE_HASHES = {"openssl-fips-provider": "a" * 64, "uv": "b" * 64, "uvx": "c" * 64}


# --- supplemental manifests -------------------------------------------------


@pytest.mark.parametrize("path", [WEB_SUPPLEMENTAL, DB_SUPPLEMENTAL], ids=["web", "db"])
@pytest.mark.spec("req-cicd-sbom-3-1")
def test_committed_supplemental_manifests_validate(path: Path) -> None:
    manifest = gen.load_supplemental(path)
    assert manifest["format"] == "tap-sbom-supplemental/1"


def test_web_supplemental_declares_the_three_components() -> None:
    names = [c["name"] for c in gen.load_supplemental(WEB_SUPPLEMENTAL)["components"]]
    assert names == ["openssl-fips-provider", "uv", "uvx"]


@pytest.mark.spec("req-cicd-sbom-3-2")
def test_supplemental_schema_rejects_missing_required_field(tmp_path: Path) -> None:
    import jsonschema

    broken = json.loads(WEB_SUPPLEMENTAL.read_text())
    del broken["components"][0]["license"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(broken))
    with pytest.raises(jsonschema.ValidationError):
        gen.load_supplemental(bad)


# --- injection + schema validation ------------------------------------------


@pytest.mark.spec("req-cicd-sbom-3-3")
def test_injected_cdx_schema_validates_and_carries_hashes() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components()), supplemental, FAKE_HASHES, coverage="test coverage")
    gen.validate_schema(doc, "cyclonedx")
    injected = {
        c["name"]: c
        for c in doc["components"]
        if any(p.get("name") == "tap:supplemental" for p in c.get("properties", []))
    }
    assert set(injected) == {"openssl-fips-provider", "uv", "uvx"}
    assert injected["uv"]["hashes"] == [{"alg": "SHA-256", "content": "b" * 64}]
    assert any(p["name"] == "tap:coverage" for p in doc["metadata"]["properties"])


@pytest.mark.spec("req-cicd-sbom-3-3")
def test_injected_spdx_schema_validates_with_describes_edges() -> None:
    supplemental = gen.load_supplemental(DB_SUPPLEMENTAL)
    base = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "tap-db",
        "documentNamespace": "https://example.invalid/tap-db",
        "creationInfo": {"created": "2026-08-20T00:00:00Z", "creators": ["Tool: syft-1.51.0"]},
        "packages": [],
    }
    doc = gen.inject_spdx(base, supplemental, FAKE_HASHES)
    gen.validate_schema(doc, "spdx")
    assert doc["packages"][0]["SPDXID"] == "SPDXRef-TapSupplemental-openssl-fips-provider"
    assert doc["relationships"][0]["relationshipType"] == "DESCRIBES"


# --- conformance (req-cicd-sbom-11) ------------------------------------------


@pytest.mark.spec("req-cicd-sbom-11-1")
def test_minimum_elements_pass_on_conformant_doc() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components()), supplemental, FAKE_HASHES, coverage="x")
    assert gen.check_minimum_elements(doc) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("serialNumber"), "serialNumber"),
        (lambda d: d["metadata"].pop("timestamp"), "timestamp"),
        (lambda d: d.pop("dependencies"), "dependency relationships"),
        (lambda d: d["metadata"].pop("properties"), "tap:coverage"),
        (lambda d: d["components"][0].pop("version"), "missing name or version"),
    ],
)
@pytest.mark.spec("req-cicd-sbom-11-1")
def test_minimum_elements_fail_closed(mutate, expected: str) -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components()), supplemental, FAKE_HASHES, coverage="x")
    mutate(doc)
    problems = gen.check_minimum_elements(doc)
    assert any(expected in p for p in problems), problems


@pytest.mark.spec("req-cicd-sbom-11-2")
def test_purl_flood_detected() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    bare: list[dict[str, object]] = [
        {"type": "library", "bom-ref": f"b{i}", "name": f"c{i}", "version": "1"} for i in range(7)
    ]
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components() + bare), supplemental, FAKE_HASHES, coverage="x")
    assert any("lack purl/CPE" in p for p in gen.check_minimum_elements(doc))


# --- canaries (req-cicd-sbom-7) ----------------------------------------------


@pytest.mark.spec("req-cicd-sbom-12-6")
def test_source_built_derivation_from_real_config() -> None:
    """Derived, never declared: the real pyproject + lock name the set. The
    motivating FIPS members must be present with the right reasons."""
    root = Path(__file__).resolve().parents[2]
    sb = gen.derive_source_built(root / "pyproject.toml", root / "uv.lock")
    assert "no-binary-package" in sb["cryptography"]
    assert "sdist-only" in sb["psycopg-c"]


@pytest.mark.spec("req-cicd-sbom-12-6")
def test_source_built_derivation_synthetic(tmp_path: Path) -> None:
    py = tmp_path / "pyproject.toml"
    py.write_text('[tool.uv]\nno-binary-package = ["Some.Forced_Pkg"]\n', encoding="utf-8")
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "wheely"\n[package.sdist]\nurl = "x"\n[[package.wheels]]\nurl = "y"\n'
        '[[package]]\nname = "sdist-only-pkg"\n[package.sdist]\nurl = "x"\n',
        encoding="utf-8",
    )
    sb = gen.derive_source_built(py, lock)
    assert set(sb) == {"some-forced-pkg", "sdist-only-pkg"}  # PEP 503-normalized; wheely excluded


@pytest.mark.spec("req-cicd-sbom-12-6")
def test_source_built_marking_and_absence_fails_closed() -> None:
    cdx = _minimal_cdx([_component("cryptography", "46.0.0")])
    spdx = {"packages": [{"SPDXID": "x", "name": "cryptography"}]}
    problems = gen.mark_source_built(cdx, spdx, {"cryptography": "forced", "ghost-pkg": "sdist-only"})
    components = cdx["components"]
    assert isinstance(components, list)
    comp = components[0]
    marks = {p["name"]: p["value"] for p in comp.get("properties", [])}
    assert marks.get("tap:source-built") == "true" and marks.get("tap:source-built-reason") == "forced"
    assert "tap:source-built" in spdx["packages"][0].get("comment", "")
    assert len(problems) == 1 and "ghost-pkg" in problems[0]


@pytest.mark.spec("req-cicd-sbom-13-1")
def test_js_closure_libraries_are_web_canaries() -> None:
    """A dropped package-lock seam must red the publish, never shrink the SBOM."""
    required = set(gen.CANARIES["tap-web"]["required"])
    assert {"htmx.org", "echarts", "tabulator-tables", "cytoscape"} <= required


@pytest.mark.spec("req-cicd-sbom-13-2")
def test_js_declaration_is_exact_pinned_with_integrity() -> None:
    """package.json holds exact pins; every lock resolution carries an integrity hash."""
    import json as _json
    import re as _re

    root = Path(__file__).resolve().parents[2]
    manifest = _json.loads((root / "package.json").read_text(encoding="utf-8"))
    for name, version in manifest["dependencies"].items():
        assert _re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), f"{name} is not exact-pinned: {version!r}"
    lock = _json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    resolved = {k: v for k, v in lock["packages"].items() if k}
    assert resolved, "lock has no resolved packages"
    for name, entry in resolved.items():
        assert entry.get("integrity", "").startswith("sha"), f"{name} lacks an integrity hash"


@pytest.mark.spec("req-cicd-sbom-7-1")
def test_canaries_pass_on_honest_web_doc() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components()), supplemental, FAKE_HASHES, coverage="x")
    assert gen.check_canaries(doc, "tap-web", supplemental) == []


@pytest.mark.spec("req-cicd-sbom-7-2")
def test_dropped_supplemental_component_is_a_red() -> None:  # every declared entry is a canary
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = _minimal_cdx(_web_base_components())  # no injection performed
    problems = gen.check_canaries(doc, "tap-web", supplemental)
    assert any("openssl-fips-provider" in p for p in problems)


@pytest.mark.spec("req-cicd-sbom-7-3")
def test_missing_tap_itself_is_a_red() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(
        _minimal_cdx([_component("django", "6.0.8"), _component("openssl", "3.6.3")]),
        supplemental,
        FAKE_HASHES,
        coverage="x",
    )
    assert any("tap" == p.split(": ")[-1] for p in gen.check_canaries(doc, "tap-web", supplemental))


@pytest.mark.spec("req-cicd-sbom-7-4")
def test_phantom_name_is_a_red() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(
        _minimal_cdx(_web_base_components() + [_component("my-test-package")]), supplemental, FAKE_HASHES, coverage="x"
    )
    assert any("forbidden phantom" in p for p in gen.check_canaries(doc, "tap-web", supplemental))


@pytest.mark.spec("req-cicd-sbom-7-4")
def test_forbidden_location_is_a_red() -> None:
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    smuggled = _component("sneaky")
    smuggled["evidence"] = {"occurrences": [{"location": "/opt/uv-cache-seed/archive-v0/x/METADATA"}]}
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components() + [smuggled]), supplemental, FAKE_HASHES, coverage="x")
    assert any("forbidden /opt/uv-cache-seed" in p for p in gen.check_canaries(doc, "tap-web", supplemental))


@pytest.mark.spec("req-cicd-sbom-11-3")
def test_minimum_elements_accepts_legacy_tools_array() -> None:
    """CycloneDX also serializes metadata.tools as a legacy array — no AttributeError."""
    supplemental = gen.load_supplemental(WEB_SUPPLEMENTAL)
    doc = gen.inject_cdx(_minimal_cdx(_web_base_components()), supplemental, FAKE_HASHES, coverage="x")
    doc["metadata"]["tools"] = [{"name": "syft", "version": "1.51.0"}]
    assert not any("metadata.tools" in p for p in gen.check_minimum_elements(doc))
