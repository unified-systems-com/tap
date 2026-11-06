"""SBOM field-completeness check (req-cicd-sbom-32) - pure-function and CLI tests.

The fixture `fixtures/sbom/tap-web-trimmed.cdx.json` is 14 components cut with `jq` from the attested tap-web
arm64 CycloneDX 1.7 document (Syft 1.51.0): the operating-system entry, three apk packages with an `upstream=`
qualifier, three without, two pypi, two npm (one library twice), the generic FIPS provider and the github-type
uv/uvx entries. Every seeded defect below deletes ONE field from a deep copy of it, so a pass is not vacuous
(req-cicd-sbom-32-9).
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_completeness", _REPO_ROOT / "scripts" / "sbom" / "completeness.py")
assert _spec is not None and _spec.loader is not None
comp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(comp)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sbom" / "tap-web-trimmed.cdx.json"


@pytest.fixture(name="doc")
def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(name="rules")
def _rules() -> dict[str, Any]:
    loaded: dict[str, Any] = comp.load_rules()
    return loaded


def _first(doc: dict[str, Any], prefix: str, *, with_upstream: bool | None = None) -> dict[str, Any]:
    for component in doc["components"]:
        purl = component.get("purl") or ""
        if not purl.startswith(prefix):
            continue
        if with_upstream is not None and ("upstream=" in purl) != with_upstream:
            continue
        found: dict[str, Any] = component
        return found
    raise AssertionError(f"no component with prefix {prefix}")


def _drop_qualifier(component: dict[str, Any], key: str) -> None:
    base, _, query = component["purl"].partition("?")
    kept = [pair for pair in query.split("&") if not pair.startswith(f"{key}=")]
    component["purl"] = base + ("?" + "&".join(kept) if kept else "")


def _property(doc: dict[str, Any], name: str) -> str | None:
    for prop in doc["metadata"].get("properties", []):
        if prop["name"] == name:
            return str(prop["value"])
    return None


@pytest.mark.spec("req-cicd-sbom-32-9")
def test_the_real_shape_document_is_complete(doc, rules):
    result = comp.check_completeness(doc, rules)
    assert result["verdict"] == "complete", result["counts"]
    assert result["components"] == 14


DEFECTS: dict[str, Callable[[dict[str, Any]], object]] = {
    "purl": lambda d: _first(d, "pkg:pypi").pop("purl"),
    "purl-qualifier:arch": lambda d: _drop_qualifier(_first(d, "pkg:apk"), "arch"),
    "purl-qualifier:distro": lambda d: _drop_qualifier(_first(d, "pkg:apk"), "distro"),
    "purl-qualifier:upstream": lambda d: _drop_qualifier(_first(d, "pkg:apk", with_upstream=True), "upstream"),
    "cpe": lambda d: _first(d, "pkg:pypi").pop("cpe"),
    "origin-package": lambda d: _first(d, "pkg:apk").__setitem__(
        "properties", [p for p in _first(d, "pkg:apk")["properties"] if p["name"] != "syft:metadata:originPackage"]
    ),
}


@pytest.mark.spec("req-cicd-sbom-32-3")
@pytest.mark.spec("req-cicd-sbom-32-9")
@pytest.mark.parametrize("gap_class", sorted(DEFECTS))
def test_each_deleted_field_is_thin_and_names_its_class(gap_class, doc, rules):
    broken = copy.deepcopy(doc)
    DEFECTS[gap_class](broken)
    result = comp.check_completeness(broken, rules)
    if gap_class == "purl":
        # A component with no purl is not in a ruled ecosystem: it surfaces as unruled (req-cicd-sbom-32-11).
        assert result["verdict"] == "thin"
        assert "unruled-ecosystem" in result["counts"]
        return
    assert result["verdict"] == "thin"
    assert list(result["counts"]) == [gap_class]
    assert result["counts"][gap_class] == 1


@pytest.mark.spec("req-cicd-sbom-32-4")
def test_upstream_is_required_only_when_the_origin_differs(doc, rules):
    same = _first(doc, "pkg:apk", with_upstream=False)
    origin = next(p["value"] for p in same["properties"] if p["name"] == "syft:metadata:originPackage")
    assert origin == same["name"]  # the fixture's no-upstream packages are exactly the origin == name ones
    assert comp.check_completeness(doc, rules)["verdict"] == "complete"
    differing = _first(doc, "pkg:apk", with_upstream=True)
    origin = next(p["value"] for p in differing["properties"] if p["name"] == "syft:metadata:originPackage")
    assert origin != differing["name"]
    # An origin that differs without the qualifier is a gap; the same package with equal origin is not.
    broken = copy.deepcopy(doc)
    _drop_qualifier(_first(broken, "pkg:apk", with_upstream=True), "upstream")
    assert comp.check_completeness(broken, rules)["counts"] == {"purl-qualifier:upstream": 1}


@pytest.mark.spec("req-cicd-sbom-32-5")
def test_exactly_one_operating_system_component_with_name_and_version(doc, rules):
    none = copy.deepcopy(doc)
    none["components"] = [c for c in none["components"] if c["type"] != "operating-system"]
    assert comp.check_completeness(none, rules)["counts"] == {"os-component": 1}
    two = copy.deepcopy(doc)
    two["components"].append(copy.deepcopy(next(c for c in two["components"] if c["type"] == "operating-system")))
    assert comp.check_completeness(two, rules)["counts"] == {"os-component": 1}
    no_version = copy.deepcopy(doc)
    next(c for c in no_version["components"] if c["type"] == "operating-system").pop("version")
    assert comp.check_completeness(no_version, rules)["counts"] == {"os-component": 1}


@pytest.mark.spec("req-cicd-sbom-32-11")
def test_a_component_without_a_rule_is_thin_never_passed(doc, rules):
    maven = copy.deepcopy(doc)
    maven["components"].append(
        {"type": "library", "name": "log4j-core", "version": "2.14.1", "purl": "pkg:maven/org.apache/log4j-core@2.14.1"}
    )
    result = comp.check_completeness(maven, rules)
    assert result["verdict"] == "thin"
    assert result["counts"] == {"unruled-ecosystem": 1}
    assert "maven" in result["examples"]["unruled-ecosystem"][0]
    no_purl = copy.deepcopy(doc)
    no_purl["components"].append({"type": "file", "name": "blob", "version": "1"})
    assert comp.check_completeness(no_purl, rules)["counts"] == {"unruled-ecosystem": 1}


@pytest.mark.spec("req-cicd-sbom-32-7")
def test_candidates_are_reported_and_never_required(doc, rules):
    result = comp.check_completeness(doc, rules)
    assert result["candidates"] > 0
    stripped = copy.deepcopy(doc)
    for component in stripped["components"]:
        component["properties"] = [p for p in component.get("properties", []) if p["name"] != "syft:cpe23"]
    after = comp.check_completeness(stripped, rules)
    assert after["verdict"] == "complete"
    assert after["candidates"] == 0


@pytest.mark.spec("req-cicd-sbom-32-3")
def test_no_components_is_thin(rules):
    result = comp.check_completeness({"components": []}, rules)
    assert result["verdict"] == "thin"
    assert "no-components" in result["counts"]


@pytest.mark.spec("req-cicd-sbom-32-8")
@pytest.mark.spec("req-cicd-sbom-32-10")
def test_the_verdict_and_the_coverage_limit_are_in_every_annotated_document(doc, rules):
    annotated = comp.annotate(copy.deepcopy(doc), comp.check_completeness(doc, rules))
    assert _property(annotated, "tap:completeness") == "complete"
    assert "Does not cover whether every package in the image is listed" in (
        _property(annotated, "tap:completeness:coverage") or ""
    )
    # Re-annotating replaces, never duplicates.
    again = comp.annotate(annotated, {"verdict": "not-observable", "reason": "test"})
    names = [p["name"] for p in again["metadata"]["properties"]]
    assert names.count("tap:completeness") == 1
    assert _property(again, "tap:completeness") == "not-observable"
    assert _property(again, "tap:completeness:reason") == "test"
    assert _property(again, "tap:completeness:coverage") is not None


@pytest.mark.spec("req-cicd-sbom-32-2")
def test_rules_that_do_not_validate_fail_the_load(tmp_path, rules):
    bad = copy.deepcopy(rules)
    bad["ecosystems"]["apk"]["require"].append("made-up-requirement")
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(comp.RulesError):
        comp.load_rules(path)
    missing = copy.deepcopy(rules)
    del missing["ecosystems"]["apk"]["_description"]
    path.write_text(json.dumps(missing))
    with pytest.raises(comp.RulesError):
        comp.load_rules(path)
    extra = copy.deepcopy(rules)
    extra["surprise"] = 1
    path.write_text(json.dumps(extra))
    with pytest.raises(comp.RulesError):
        comp.load_rules(path)


@pytest.mark.spec("req-cicd-sbom-32-2")
def test_the_committed_rules_validate(rules):
    assert rules["format"] == comp.RULES_FORMAT


def _run_cli(monkeypatch, capsys, text: str, *args: str) -> tuple[int, str, str]:
    """Run main() with `text` on stdin; return (exit code, stdout, stderr)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    code = comp.main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.spec("req-cicd-sbom-32-6")
@pytest.mark.spec("req-cicd-sbom-32-8")
def test_cli_exit_codes_and_summary(monkeypatch, capsys, tmp_path, doc):
    code, out, err = _run_cli(monkeypatch, capsys, json.dumps(doc), "--annotate")
    assert code == 0
    assert _property(json.loads(out), "tap:completeness") == "complete"
    assert "SBOM completeness: `complete`" in err

    broken = copy.deepcopy(doc)
    _first(broken, "pkg:pypi").pop("cpe")
    code, out, err = _run_cli(monkeypatch, capsys, json.dumps(broken), "--annotate")
    assert code == 1
    assert _property(json.loads(out), "tap:completeness") == "thin"
    assert "`cpe`" in err  # the gap class is listed in the job summary

    code, out, err = _run_cli(monkeypatch, capsys, "not json at all")
    assert code == 2
    assert "could not run" in err

    badrules = tmp_path / "rules.json"
    badrules.write_text("{}")
    monkeypatch.setattr(comp, "DEFAULT_RULES", badrules)
    code, out, err = _run_cli(monkeypatch, capsys, json.dumps(doc), "--annotate")
    assert code == 2
    assert _property(json.loads(out), "tap:completeness") == "not-observable"


@pytest.mark.spec("req-cicd-sbom-32-8")
@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["components"].append("not an object"),
        lambda d: d["components"][1].__setitem__("properties", [None]),
        lambda d: d["components"][1].__setitem__("properties", "nope"),
        lambda d: d.__setitem__("metadata", ["not", "an", "object"]),
        lambda d: d.__setitem__("components", {"not": "a list"}),
    ],
    ids=[
        "string-component",
        "null-property",
        "properties-not-a-list",
        "metadata-not-an-object",
        "components-not-a-list",
    ],
)
def test_a_malformed_document_is_not_observable_and_never_complete(mutate, monkeypatch, capsys, doc):
    broken = copy.deepcopy(doc)
    mutate(broken)
    code, _out, _err = _run_cli(monkeypatch, capsys, json.dumps(broken), "--annotate")
    assert code == 2


@pytest.mark.spec("req-cicd-sbom-32-3")
def test_nested_components_are_checked(doc, rules):
    nested = copy.deepcopy(doc)
    _first(nested, "pkg:pypi")["components"] = [{"type": "library", "name": "inner", "version": "1"}]
    result = comp.check_completeness(nested, rules)
    assert result["verdict"] == "thin"
    assert result["counts"] == {"unruled-ecosystem": 1}
    assert result["components"] == 15


@pytest.mark.spec("req-cicd-sbom-32-6")
def test_summary_text_from_the_document_cannot_inject_markup(doc, rules):
    hostile = copy.deepcopy(doc)
    hostile["components"].append(
        {
            "type": "library",
            "name": "x |\n\n### SBOM completeness: `complete`\n[click](http://example.invalid)",
            "version": "1",
        }
    )
    text = comp.summary_markdown(comp.check_completeness(hostile, rules))
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings == ["### SBOM completeness: `thin`"]
    assert "[click]" not in text
    assert "\n\n### SBOM completeness: `complete`" not in text


def _with_attributes(doc: dict[str, Any]) -> dict[str, Any]:
    """The fixture as image generation now writes it: every pypi component with a license and an architecture."""
    done = copy.deepcopy(doc)
    for component in done["components"]:
        if component.get("purl", "").startswith("pkg:pypi/"):
            component["licenses"] = [{"expression": "MIT"}]
            component.setdefault("properties", []).append({"name": "tap:architecture", "value": "noarch"})
    return done


def _declare_unknown(component: dict[str, Any]) -> None:
    props = component.setdefault("properties", [])
    for field in ("licenses", "architecture"):
        props += [
            {"name": f"tap:{field}:status", "value": "not-observed"},
            {"name": f"tap:{field}:reason", "value": "no matching wheel in the image's cache seed"},
        ]


@pytest.mark.spec("req-cicd-sbom-33-7")
def test_missing_attributes_are_reported_at_intake_and_do_not_make_it_thin(doc, rules):
    result = comp.check_completeness(doc, rules)  # a legacy revision: pypi components without license or architecture
    assert result["verdict"] == "complete"
    assert result["attribute_gaps"] == {"architecture": 2, "licenses": 2}
    assert result["attributes_enforced"] is False
    assert "reported and not enforced" in comp.summary_markdown(result)


@pytest.mark.spec("req-cicd-sbom-33-7")
@pytest.mark.spec("req-cicd-sbom-33-8")
def test_enforced_missing_attributes_are_thin(doc, rules):
    result = comp.check_completeness(doc, rules, enforce_attributes=True)
    assert result["verdict"] == "thin"
    assert result["counts"] == {"architecture": 2, "licenses": 2}


@pytest.mark.spec("req-cicd-sbom-33-7")
def test_a_document_with_the_attributes_is_complete_even_when_enforced(doc, rules):
    result = comp.check_completeness(_with_attributes(doc), rules, enforce_attributes=True)
    assert result["verdict"] == "complete" and result["attribute_gaps"] == {}


@pytest.mark.spec("req-cicd-sbom-33-5")
@pytest.mark.spec("req-cicd-sbom-33-7")
def test_declared_unknown_counts_but_passes_within_the_limit(doc, rules):
    document = _with_attributes(doc)
    pypi = [c for c in document["components"] if c.get("purl", "").startswith("pkg:pypi/")]
    pypi[0].pop("licenses")
    pypi[0]["properties"] = [p for p in pypi[0]["properties"] if p["name"] != "tap:architecture"]
    _declare_unknown(pypi[0])
    result = comp.check_completeness(document, rules, enforce_attributes=True)
    assert result["verdict"] == "complete"
    assert result["declared_unknown"] == {"pypi": {"architecture": 1, "licenses": 1}}


@pytest.mark.spec("req-cicd-sbom-33-8")
def test_too_many_declared_unknowns_is_thin_so_a_vanished_seed_is_loud(doc, rules):
    limited = copy.deepcopy(rules)
    limited["ecosystems"]["pypi"]["declared_unknown_limit"] = 1
    document = _with_attributes(doc)
    for component in document["components"]:
        if component.get("purl", "").startswith("pkg:pypi/"):
            component.pop("licenses")
            component["properties"] = [p for p in component["properties"] if p["name"] != "tap:architecture"]
            _declare_unknown(component)
    result = comp.check_completeness(document, limited, enforce_attributes=True)
    assert result["verdict"] == "thin"
    assert "declared-unknown-over-limit" in result["counts"]


@pytest.mark.spec("req-cicd-sbom-33-5")
def test_an_unknown_without_a_reason_is_a_gap_not_a_declaration(doc, rules):
    document = _with_attributes(doc)
    pypi = next(c for c in document["components"] if c.get("purl", "").startswith("pkg:pypi/"))
    pypi.pop("licenses")
    pypi["properties"].append({"name": "tap:licenses:status", "value": "not-observed"})  # no reason
    result = comp.check_completeness(document, rules, enforce_attributes=True)
    assert result["counts"] == {"licenses": 1}


@pytest.mark.spec("req-cicd-sbom-32-12")
def test_go_modules_need_a_purl_and_a_cpe(doc, rules):
    document = copy.deepcopy(doc)
    module = {
        "type": "library",
        "name": "golang.org/x/sys",
        "version": "v0.1.0",
        "purl": "pkg:golang/golang.org/x/sys@v0.1.0",
        "cpe": "cpe:2.3:a:golang:sys:v0.1.0:*:*:*:*:*:*:*",
    }
    document["components"].append(module)
    assert comp.check_completeness(document, rules)["verdict"] == "complete"
    module.pop("cpe")
    assert comp.check_completeness(document, rules)["counts"] == {"cpe": 1}


@pytest.mark.spec("req-cicd-sbom-33-7")
def test_the_enforce_flag_is_the_only_difference_on_the_command_line(monkeypatch, capsys, doc):
    code, _out, err = _run_cli(monkeypatch, capsys, json.dumps(doc))
    assert code == 0 and "reported and not enforced" in err
    code, _out, err = _run_cli(monkeypatch, capsys, json.dumps(doc), "--enforce-attributes")
    assert code == 1 and "`licenses`" in err
