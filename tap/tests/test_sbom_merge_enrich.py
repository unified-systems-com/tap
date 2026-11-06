"""Merge and enrichment of scanner output into the next SBOM revision (req-cicd-sbom-18, -20).

The inputs are real, trimmed data (see `fixtures/sbom/merge/README.md`): a two-component probe SBOM, Grype's native
JSON for it, the CISA KEV catalog and two CVE records. `scripts/sbom/merge_enrich.py` reads a fixed `scan-inputs/`
directory, so each test stages the fixtures into a temporary working directory.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_merge_enrich", _REPO_ROOT / "scripts" / "sbom" / "merge_enrich.py")
assert _spec is not None and _spec.loader is not None
me = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(me)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sbom" / "merge"
KEV_GHSA = "GHSA-jfh8-c2jp-5v3q"
KEV_CVE = "CVE-2021-44228"
PLAIN_GHSA = "GHSA-p6xc-xr62-6r2g"
PLAIN_CVE = "CVE-2021-45105"


class Run:
    """One staged working directory and the result of `main()` in it."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        self.dir = tmp_path / "scan-inputs"
        shutil.copytree(FIXTURES, self.dir, ignore=shutil.ignore_patterns("README.md"))
        monkeypatch.chdir(tmp_path)
        self.capsys = capsys

    def read(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text())

    def write(self, name: str, value: Any) -> None:
        (self.dir / name).write_text(json.dumps(value))

    def go(self) -> tuple[int, dict[str, Any] | None, str]:
        code = me.main()
        captured = self.capsys.readouterr()
        return code, (json.loads(captured.out) if captured.out else None), captured.err


@pytest.fixture(name="run")
def _run(tmp_path, monkeypatch, capsys) -> Run:
    return Run(tmp_path, monkeypatch, capsys)


def _entry(doc: dict[str, Any], vulnerability_id: str) -> dict[str, Any]:
    matches = [e for e in doc["vulnerabilities"] if e["id"] == vulnerability_id]
    assert len(matches) == 1, [e["id"] for e in doc["vulnerabilities"]]
    found: dict[str, Any] = matches[0]
    return found


def _props(entry: dict[str, Any]) -> dict[str, str]:
    return {p["name"]: p["value"] for p in entry["properties"]}


def _meta_props(doc: dict[str, Any]) -> dict[str, str]:
    return {p["name"]: p["value"] for p in doc["metadata"]["properties"]}


@pytest.mark.spec("req-cicd-sbom-20-3")
@pytest.mark.spec("req-cicd-sbom-20-12")
@pytest.mark.spec("req-cicd-sbom-18-13")
def test_the_next_revision_keeps_the_serial_and_adds_one_to_the_version(run):
    code, doc, _err = run.go()
    base = run.read("sbom.cdx.json")
    assert code == 0 and doc is not None
    assert doc["serialNumber"] == base["serialNumber"]
    assert doc["version"] == base["version"] + 1 == 2
    assert doc["components"] == base["components"]  # the components are unchanged
    assert doc["metadata"]["timestamp"] == "2026-10-16T06:00:00Z"


@pytest.mark.spec("req-cicd-sbom-18-1")
@pytest.mark.spec("req-cicd-sbom-18-9")
def test_findings_are_joined_by_purl_and_point_at_the_sboms_own_refs(run):
    base = run.read("sbom.cdx.json")
    for component in base["components"]:
        component["bom-ref"] = "renamed-" + component["bom-ref"]  # Grype's refs would not survive either
    run.write("sbom.cdx.json", base)
    _code, doc, _err = run.go()
    assert doc is not None
    log4j_ref = next(c["bom-ref"] for c in base["components"] if c["name"] == "log4j-core")
    assert [a["ref"] for a in _entry(doc, KEV_CVE)["affects"]] == [log4j_ref]


@pytest.mark.spec("req-cicd-sbom-18-1")
@pytest.mark.spec("req-cicd-sbom-18-13")
def test_a_scanner_component_that_is_not_in_the_sbom_fails_the_stage(run):
    grype = run.read("grype.json")
    grype["matches"][0]["artifact"]["purl"] = "pkg:maven/example/not-in-the-sbom@1.0"
    grype["matches"][0]["artifact"]["name"] = "not-in-the-sbom"
    run.write("grype.json", grype)
    code, doc, err = run.go()
    assert code == 2 and doc is None
    assert "not in the SBOM" in err


@pytest.mark.spec("req-cicd-sbom-18-2")
def test_every_entry_names_the_scanner_and_its_version(run):
    _code, doc, _err = run.go()
    assert doc is not None
    for entry in doc["vulnerabilities"]:
        assert entry["tools"]["components"] == [{"type": "application", "name": "grype", "version": "0.120.1"}]
    assert {c["name"] for c in doc["metadata"]["tools"]["components"]} >= {"grype"}


@pytest.mark.spec("req-cicd-sbom-18-3")
def test_a_ghsa_finding_with_a_cve_alias_is_one_entry_keyed_by_the_cve(run):
    _code, doc, _err = run.go()
    assert doc is not None
    assert sorted(e["id"] for e in doc["vulnerabilities"]) == [KEV_CVE, PLAIN_CVE]
    entry = _entry(doc, KEV_CVE)
    assert [r["id"] for r in entry["references"]] == [KEV_GHSA]  # the GHSA is kept as an alias


@pytest.mark.spec("req-cicd-sbom-18-3")
def test_the_same_finding_reported_twice_is_one_entry(run):
    grype = run.read("grype.json")
    grype["matches"].append(copy.deepcopy(grype["matches"][0]))
    run.write("grype.json", grype)
    _code, doc, _err = run.go()
    assert doc is not None
    assert len(doc["vulnerabilities"]) == 2


@pytest.mark.spec("req-cicd-sbom-18-5")
@pytest.mark.spec("req-cicd-sbom-18-7")
def test_kev_is_matched_over_every_alias_and_lands_on_the_cve_entry(run):
    _code, doc, _err = run.go()
    assert doc is not None
    listed = _entry(doc, KEV_CVE)
    props = _props(listed)
    assert props["tap:kev:listed"] == "true"
    assert props["tap:kev:matched-id"] == KEV_CVE
    assert props["tap:kev:source"] == "catalog"
    assert props["tap:kev:catalog-version"] == "2026.10.14"
    assert props["tap:kev:date-released"].startswith("2026-10-14")
    assert props["tap:kev:fetched-at"] == "2026-10-16T05:58:00Z"
    assert props["tap:kev:date-added"] == "2021-12-10"
    assert props["tap:kev:due-date"] == "2021-12-24"
    assert props["tap:kev:ransomware-use"] == "Known"
    assert "remediation" in props["tap:kev:required-action"] or "updates" in props["tap:kev:required-action"]
    assert {
        "source": {"name": "CISA KEV Catalog"},
        "score": 1,
        "method": "other",
        "justification": "Listed in CISA KEV",
    } in listed["ratings"]
    plain = _entry(doc, PLAIN_CVE)
    assert _props(plain)["tap:kev:listed"] == "false"  # read and not listed is false, not unknown


@pytest.mark.spec("req-cicd-sbom-18-4")
def test_every_enrichment_fact_carries_its_source_and_time(run):
    _code, doc, _err = run.go()
    assert doc is not None
    props = _props(_entry(doc, KEV_CVE))
    assert props["tap:cve-record:status"] == "observed"
    assert props["tap:cve-record:id"] == KEV_CVE
    assert props["tap:cve-record:fetched-at"] == "2026-10-16T05:58:30Z"
    assert props["tap:ssvc:exploitation"] == "active"
    assert props["tap:ssvc:automatable"] == "yes"
    assert props["tap:ssvc:technical-impact"] == "total"
    assert props["tap:ssvc:assessed-at"].startswith("2025-02-04")
    ssvc = [r for r in _entry(doc, KEV_CVE)["ratings"] if r.get("method") == "SSVC"]
    assert len(ssvc) == 1 and ssvc[0]["source"] == {"name": "CISA-ADP"}
    cvss = [r for r in _entry(doc, KEV_CVE)["ratings"] if r.get("method") == "CVSSv31"]
    assert {r["source"]["name"] for r in cvss} >= {"CISA-ADP"}
    assert _entry(doc, KEV_CVE)["cwes"] == [20, 400, 502, 917]
    assert _props(_entry(doc, KEV_CVE))["tap:epss:percentile"] == "1"


@pytest.mark.spec("req-cicd-sbom-18-6")
@pytest.mark.spec("req-cicd-sbom-18-12")
def test_a_source_that_could_not_be_read_is_not_observed_never_false(run):
    (run.dir / "kev.json").unlink()
    (run.dir / "cve.json").write_text("not json")
    _code, doc, _err = run.go()
    assert doc is not None
    assert _meta_props(doc)["tap:kev:status"] == "not-observed"
    assert _meta_props(doc)["tap:cve-records:status"] == "not-observed"
    plain = _props(_entry(doc, PLAIN_CVE))
    assert plain["tap:kev:listed"] == "not-observed"
    assert plain["tap:cve-record:status"] == "not-observed"
    assert not [r for r in _entry(doc, PLAIN_CVE)["ratings"] if r.get("method") == "SSVC"]
    # The scanner's own KEV data still counts when the catalog is unreadable: never a miss.
    assert _props(_entry(doc, KEV_CVE))["tap:kev:listed"] == "true"
    assert _props(_entry(doc, KEV_CVE))["tap:kev:source"] == "grype"


@pytest.mark.spec("req-cicd-sbom-18-6")
def test_a_catalog_without_its_version_stamp_is_not_trusted(run):
    catalog = run.read("kev.json")
    del catalog["catalogVersion"]
    run.write("kev.json", catalog)
    _code, doc, _err = run.go()
    assert doc is not None
    assert _meta_props(doc)["tap:kev:status"] == "not-observed"


@pytest.mark.spec("req-cicd-sbom-18-10")
def test_a_revision_recomputes_its_facts_from_this_scans_sources(run):
    _code, first, _err = run.go()
    assert first is not None
    run.write("sbom.cdx.json", first)
    record = run.read("cve.json")
    adp = record[KEV_CVE]["containers"]["adp"][0]
    for metric in adp["metrics"]:
        other = metric.get("other")
        if other and other.get("type") == "ssvc":
            other["content"]["options"][0] = {"Exploitation": "none"}
    run.write("cve.json", record)
    code, second, _err = run.go()
    assert code == 0 and second is not None
    assert _props(_entry(second, KEV_CVE))["tap:ssvc:exploitation"] == "none"  # not copied forward from revision 2
    assert second["version"] == 3


@pytest.mark.spec("req-cicd-sbom-18-8")
@pytest.mark.spec("req-cicd-sbom-18-11")
def test_the_merge_makes_no_network_call():
    source = (_REPO_ROOT / "scripts" / "sbom" / "merge_enrich.py").read_text()
    for forbidden in ("urllib", "http.client", "socket", "requests", "subprocess"):
        assert forbidden not in source


@pytest.mark.spec("req-cicd-sbom-20-9")
def test_the_revision_names_the_digest_of_the_document_it_was_made_from(run):
    _code, doc, _err = run.go()
    assert doc is not None
    props = _meta_props(doc)
    digest = hashlib.sha256((run.dir / "sbom.cdx.json").read_bytes()).hexdigest()
    assert props["tap:revision:previous-content-digest"] == f"sha256:{digest}"
    assert props["tap:revision:input-attestation"].startswith("sha256:000")
    assert props["tap:source:grype:sha256"] == hashlib.sha256((run.dir / "grype.json").read_bytes()).hexdigest()
    assert props["tap:scan:grype-db-built"] == "2026-10-15T06:30:36Z"


@pytest.mark.spec("req-cicd-sbom-20-11")
@pytest.mark.spec("req-cicd-sbom-18-13")
def test_a_scan_with_the_same_facts_publishes_nothing(run):
    _code, first, _err = run.go()
    assert first is not None
    run.write("sbom.cdx.json", first)
    meta = run.read("meta.json")
    meta["scan_time"] = "2026-10-17T06:00:00Z"
    meta["kev"]["fetched_at"] = "2026-10-17T05:58:00Z"
    run.write("meta.json", meta)
    grype = run.read("grype.json")
    grype["descriptor"]["db"]["built"] = "2026-10-17T06:30:36Z"
    grype["matches"][0]["vulnerability"]["epss"][0]["epss"] = 0.5  # EPSS moves daily and is not a fact for this test
    run.write("grype.json", grype)
    code, doc, err = run.go()
    assert code == 3 and doc is None
    assert "unchanged" in err


@pytest.mark.spec("req-cicd-sbom-20-11")
def test_a_changed_fact_publishes_the_next_revision(run):
    _code, first, _err = run.go()
    assert first is not None
    run.write("sbom.cdx.json", first)
    grype = run.read("grype.json")
    grype["matches"][1]["vulnerability"]["fix"] = {"versions": ["2.17.1"], "state": "fixed"}
    run.write("grype.json", grype)
    code, doc, _err = run.go()
    assert code == 0 and doc is not None
    assert doc["version"] == 3
    assert _props(_entry(doc, PLAIN_CVE))["tap:fix:state"] == "fixed"


@pytest.mark.spec("req-cicd-sbom-20-11")
def test_the_first_scan_publishes_even_when_it_finds_nothing(run):
    grype = run.read("grype.json")
    grype["matches"] = []
    run.write("grype.json", grype)
    code, doc, _err = run.go()
    assert code == 0 and doc is not None
    assert doc["vulnerabilities"] == []  # scanned clean is a recorded fact on the first scan


@pytest.mark.spec("req-cicd-sbom-17-3")
@pytest.mark.parametrize("missing", ["sbom.cdx.json", "grype.json", "meta.json"])
def test_a_missing_required_input_fails_the_stage(run, missing):
    (run.dir / missing).unlink()
    code, doc, err = run.go()
    assert code == 2 and doc is None
    assert "could not run" in err


@pytest.mark.spec("req-cicd-sbom-18-2")
def test_the_summary_cannot_be_used_to_inject_markup(run):
    base = run.read("sbom.cdx.json")
    base["serialNumber"] = "urn:uuid:x |\n\n### SBOM merge: `changed`"
    run.write("sbom.cdx.json", base)
    _code, _doc, err = run.go()
    assert [line for line in err.splitlines() if line.startswith("#")] == ["### SBOM merge: `changed`"]


@pytest.mark.spec("req-cicd-sbom-18-14")
def test_an_entry_carries_published_title_description_and_record_urls(run):
    _code, doc, _err = run.go()
    assert doc is not None
    entry = _entry(doc, KEV_CVE)
    assert entry["published"] == "2021-12-10T00:00:00.000Z"
    assert entry["updated"].startswith("2025-")
    assert entry["description"].startswith("Apache Log4j2 2.0-beta9 through 2.15.0")
    assert _props(entry)["tap:title"].startswith("Apache Log4j2 JNDI features do not protect")
    assert {"title": "CVE Record", "url": f"https://www.cve.org/CVERecord?id={KEV_CVE}"} in entry["advisories"]
    assert {"title": "GitHub Advisory", "url": f"https://github.com/advisories/{KEV_GHSA}"} in entry["advisories"]
    assert _props(entry)["tap:ghsa:status"] == "observed"


@pytest.mark.spec("req-cicd-sbom-18-14")
def test_the_scanners_own_description_wins_over_the_record_and_the_advisory(run):
    grype = run.read("grype.json")
    grype["matches"][0]["vulnerability"]["description"] = "the scanner's words"
    run.write("grype.json", grype)
    _code, doc, _err = run.go()
    assert doc is not None
    assert _entry(doc, KEV_CVE)["description"] == "the scanner's words"


@pytest.mark.spec("req-cicd-sbom-18-14")
@pytest.mark.spec("req-cicd-sbom-18-15")
def test_a_ghsa_only_entry_is_filled_from_the_advisory(run):
    grype = run.read("grype.json")
    for match in grype["matches"]:
        match["relatedVulnerabilities"] = []  # no CVE alias: only the GitHub advisory can describe it
    run.write("grype.json", grype)
    _code, doc, _err = run.go()
    assert doc is not None
    entry = _entry(doc, PLAIN_GHSA)
    props = _props(entry)
    assert entry["published"] == "2021-12-18T18:00:07Z"
    assert entry["description"] and props["tap:title"].startswith(
        "Apache Log4j2 vulnerable to Improper Input Validation"
    )
    assert entry["advisories"] == [{"title": "GitHub Advisory", "url": f"https://github.com/advisories/{PLAIN_GHSA}"}]
    assert "tap:cve-record:status" not in props  # there is no CVE id to look up


@pytest.mark.spec("req-cicd-sbom-18-15")
def test_advisories_that_could_not_be_read_are_not_observed_and_the_record_still_fills_the_entry(run):
    (run.dir / "ghsa.json").unlink()
    _code, doc, _err = run.go()
    assert doc is not None
    assert _meta_props(doc)["tap:ghsa-advisories:status"] == "not-observed"
    entry = _entry(doc, KEV_CVE)
    assert _props(entry)["tap:ghsa:status"] == "not-observed"
    assert entry["published"] == "2021-12-10T00:00:00.000Z"  # from the CVE record
    assert all(a["title"] != "GitHub Advisory" for a in entry["advisories"])


@pytest.mark.spec("req-cicd-sbom-18-16")
@pytest.mark.spec("req-cicd-sbom-20-11")
def test_a_touched_record_alone_does_not_publish_but_a_new_published_date_does(run):
    _code, first, _err = run.go()
    assert first is not None
    run.write("sbom.cdx.json", first)
    records = run.read("cve.json")
    records[KEV_CVE]["cveMetadata"]["dateUpdated"] = "2026-10-19T00:00:00.000Z"
    run.write("cve.json", records)
    code, doc, _err = run.go()
    assert code == 3 and doc is None  # `updated` moves without the facts moving
    records[KEV_CVE]["cveMetadata"]["datePublished"] = "2021-12-11T00:00:00.000Z"
    run.write("cve.json", records)
    code, doc, _err = run.go()
    assert code == 0 and doc is not None
    assert _entry(doc, KEV_CVE)["published"] == "2021-12-11T00:00:00.000Z"
