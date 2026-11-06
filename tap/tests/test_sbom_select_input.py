"""Selecting the SBOM revision a rescan starts from (req-cicd-sbom-20-10, -22).

The verification results are shaped like the real `gh attestation verify --format json` output for the tap-web digest
(a list of `{attestation, verificationResult}` items; the statement holds `predicateType`, `subject` and the CycloneDX
document as `predicate`; the transparency-log time is in `attestation.bundle.verificationMaterial.tlogEntries`), with
the predicate cut down to the small fixture document so the tests stay light.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sbom_select_input", _REPO_ROOT / "scripts" / "sbom" / "select_input.py")
assert _spec is not None and _spec.loader is not None
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sbom" / "merge" / "sbom.cdx.json"
DIGEST = "sha256:" + "a" * 64
IMAGE = "unified-systems-com/tap-web"


def _item(version: int, *, serial: str | None = None, time: int = 1000, digest: str = DIGEST) -> dict[str, Any]:
    document = json.loads(FIXTURE.read_text())
    document["version"] = version
    if serial is not None:
        document["serialNumber"] = serial
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": f"ghcr.io/{IMAGE}", "digest": {"sha256": digest.removeprefix("sha256:")}}],
        "predicateType": "https://cyclonedx.org/bom",
        "predicate": document,
    }
    # The signed payload carries the predicate as written (indented, as Syft writes it), not canonical JSON.
    prefix = json.dumps({k: v for k, v in statement.items() if k != "predicate"}, separators=(",", ":"))[:-1]
    payload = prefix + ',"predicate":' + json.dumps(document, indent=2) + "}"
    return {
        "attestation": {
            "bundle": {
                "dsseEnvelope": {"payload": base64.b64encode(payload.encode()).decode()},
                "verificationMaterial": {"tlogEntries": [{"integratedTime": str(time)}]},
            }
        },
        "verificationResult": {"statement": statement},
    }


WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "sbom-vulnerability-evidence.yml"


@pytest.mark.spec("req-cicd-sbom-22-8")
def test_the_workflow_verifies_each_signer_with_the_entrys_exact_identity_and_pin():
    text = WORKFLOW.read_text()
    assert 'gh attestation verify "oci://ghcr.io/${IMAGE}@${DIGEST}"' in text
    assert '--cert-identity "https://github.com/${repository}/${workflow_path}@${ref}"' in text
    assert "--predicate-type https://cyclonedx.org/bom" in text
    assert '--signer-digest "$signer_digest"' in text
    assert '[ "$signer_digest" = "-" ] ||' in text  # a transitional entry has no digest pin


@pytest.mark.spec("req-cicd-sbom-22-8")
def test_this_module_never_starts_a_process():
    source = (_REPO_ROOT / "scripts" / "sbom" / "select_input.py").read_text()
    assert "import subprocess" not in source and "os.system" not in source


@pytest.mark.spec("req-cicd-sbom-22-7")
def test_plan_prints_the_validated_list_as_tab_separated_lines(capsys):
    assert sel.main(["plan"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "tap-publish-images-transitional\tunified-systems-com/tap\t.github/workflows/publish-images.yml\trefs/heads/main\t-",
        "tap-sbom-evidence-5736329d\tunified-systems-com/tap\t.github/workflows/sbom-vulnerability-evidence.yml\t"
        "5736329dff506c952b5567260dd82c51adab5d74\t5736329dff506c952b5567260dd82c51adab5d74",
        "tap-sbom-evidence-e9841198\tunified-systems-com/tap\t.github/workflows/sbom-vulnerability-evidence.yml\t"
        "e9841198ba7535f4eef79247dd5fb2520b6e1da9\te9841198ba7535f4eef79247dd5fb2520b6e1da9",
    ]


@pytest.mark.spec("req-cicd-sbom-22-1")
def test_plan_fails_closed_on_a_bad_trust_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sel, "TRUSTED_SIGNERS", tmp_path / "absent.json")
    assert sel.main(["plan"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.spec("req-cicd-sbom-20-10")
@pytest.mark.spec("req-cicd-sbom-20-4")
def test_the_highest_version_wins_then_the_later_signature_then_the_digest():
    serial = "urn:uuid:5b0a6d1e-9c1f-4d9a-8d42-0a7f3c0f1e11"
    found = sel.candidates_from([_item(1), _item(3), _item(2)], DIGEST, "s1")
    assert sel.choose(found)["version"] == 3
    tied = sel.candidates_from([_item(2, time=1000), _item(2, time=2000)], DIGEST, "s1")
    assert sel.choose(tied)["integrated_time"] == 2000
    assert {c["serial"] for c in found} == {serial}


@pytest.mark.spec("req-cicd-sbom-20-10")
def test_revisions_that_disagree_on_serial_number_stop_the_run():
    mixed = sel.candidates_from([_item(1), _item(2, serial="urn:uuid:other")], DIGEST, "s1")
    with pytest.raises(sel.SelectionError, match="disagree on serialNumber"):
        sel.choose(mixed)


@pytest.mark.spec("req-cicd-sbom-22-2")
def test_a_verified_attestation_for_another_subject_digest_is_refused():
    with pytest.raises(sel.SelectionError, match="different subject digest"):
        sel.candidates_from([_item(1, digest="sha256:" + "c" * 64)], DIGEST, "s1")


@pytest.mark.spec("req-cicd-sbom-22-1")
def test_no_verified_attestation_is_a_failure_never_an_empty_pass():
    with pytest.raises(sel.SelectionError, match="no attestation verified"):
        sel.choose([])


@pytest.mark.spec("req-cicd-sbom-22-7")
def test_the_committed_trust_list_validates_and_has_one_transitional_entry():
    signers = sel.load_signers()
    assert [s["id"] for s in signers] == [
        "tap-publish-images-transitional",
        "tap-sbom-evidence-5736329d",
        "tap-sbom-evidence-e9841198",
    ]
    assert signers[0]["signer_digest"] is None and signers[0]["transitional"] is True
    assert signers[1]["signer_digest"] == signers[1]["ref"] == "5736329dff506c952b5567260dd82c51adab5d74"


def _write_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]) -> None:
    path = tmp_path / "list.json"
    path.write_text(json.dumps(document))
    monkeypatch.setattr(sel, "TRUSTED_SIGNERS", path)


@pytest.mark.spec("req-cicd-sbom-22-1")
@pytest.mark.spec("req-cicd-sbom-22-7")
def test_an_empty_or_malformed_trust_list_fails_the_load(tmp_path, monkeypatch):
    good = json.loads(sel.TRUSTED_SIGNERS.read_text())
    empty = copy.deepcopy(good)
    empty["signers"] = []
    _write_list(tmp_path, monkeypatch, empty)
    with pytest.raises(sel.SelectionError):
        sel.load_signers()
    unpinned = copy.deepcopy(good)
    unpinned["signers"][0]["transitional"] = False
    _write_list(tmp_path, monkeypatch, unpinned)
    with pytest.raises(sel.SelectionError):  # no digest pin and not marked transitional
        sel.load_signers()
    extra = copy.deepcopy(good)
    extra["signers"][0]["surprise"] = 1
    _write_list(tmp_path, monkeypatch, extra)
    with pytest.raises(sel.SelectionError):
        sel.load_signers()
    monkeypatch.setattr(sel, "TRUSTED_SIGNERS", tmp_path / "absent.json")
    with pytest.raises(sel.SelectionError):
        sel.load_signers()


@pytest.mark.spec("req-cicd-sbom-22-7")
def test_a_pinned_entry_needs_a_forty_hex_digest(tmp_path, monkeypatch):
    good = json.loads(sel.TRUSTED_SIGNERS.read_text())
    pinned = copy.deepcopy(good)
    pinned["signers"][0].update(signer_digest="b" * 40, transitional=False)
    _write_list(tmp_path, monkeypatch, pinned)
    assert sel.load_signers()[0]["signer_digest"] == "b" * 40
    pinned["signers"][0]["signer_digest"] = "main"
    _write_list(tmp_path, monkeypatch, pinned)
    with pytest.raises(sel.SelectionError):
        sel.load_signers()


@pytest.mark.spec("req-cicd-sbom-20-10")
def test_main_stages_the_highest_verified_revision_and_its_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE", IMAGE)
    monkeypatch.setenv("DIGEST", DIGEST)
    monkeypatch.setattr(sel, "read_verified", lambda signer_id: [_item(1), _item(2)])
    assert sel.main() == 0
    staged = (tmp_path / "scan-inputs" / "sbom.cdx.json").read_bytes()
    meta = json.loads((tmp_path / "scan-inputs" / "meta.json").read_text())
    assert json.loads(staged)["version"] == 2
    assert meta["input_version"] == 2
    assert meta["input_content_digest"] == "sha256:" + hashlib.sha256(staged).hexdigest()  # what merge_enrich digests
    assert staged != sel.canonical(json.loads(staged))  # the bytes are the signed ones, indentation and all
    assert b'\n  "' in staged
    assert meta["input_signer"] == "tap-publish-images-transitional"
    assert meta["input_attestation_digest"].startswith("sha256:")


@pytest.mark.spec("req-cicd-sbom-22-1")
def test_main_fails_closed_when_nothing_verifies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE", IMAGE)
    monkeypatch.setenv("DIGEST", DIGEST)
    monkeypatch.setattr(sel, "read_verified", lambda signer_id: [])
    assert sel.main() == 2
    assert not (tmp_path / "scan-inputs" / "sbom.cdx.json").exists()


@pytest.mark.spec("req-cicd-sbom-17-2")
@pytest.mark.parametrize(
    ("image", "digest"),
    [
        ("unified-systems-com/tap-web;rm -rf /", DIGEST),
        ("../etc/passwd", DIGEST),
        ("UPPER/case", DIGEST),
        (IMAGE, "latest"),
        (IMAGE, "sha256:short"),
        (IMAGE, DIGEST + "0"),
        ("", ""),
    ],
)
def test_an_image_or_digest_that_is_not_the_expected_shape_is_refused(tmp_path, monkeypatch, image, digest):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE", image)
    monkeypatch.setenv("DIGEST", digest)
    monkeypatch.setattr(sel, "read_verified", lambda signer_id: pytest.fail("nothing may be read for a bad image"))
    assert sel.main() == 2


@pytest.mark.spec("req-cicd-sbom-20-12")
def test_the_content_digest_is_over_the_signed_predicate_bytes_not_a_reserialization():
    item = _item(2)
    signed = sel.signed_predicate_bytes(item, item["verificationResult"]["statement"]["predicate"])
    found = sel.candidates_from([item], DIGEST, "s1")[0]
    assert found["content_digest"] == hashlib.sha256(signed).hexdigest()
    assert found["content_digest"] != hashlib.sha256(sel.canonical(json.loads(signed))).hexdigest()


@pytest.mark.spec("req-cicd-sbom-22-2")
def test_a_payload_that_does_not_match_the_verified_statement_stops_the_run():
    item = _item(2)
    other = copy.deepcopy(item)
    other["verificationResult"]["statement"]["predicate"]["version"] = 99
    with pytest.raises(sel.SelectionError, match="not the document verification returned"):
        sel.signed_predicate_bytes(item, other["verificationResult"]["statement"]["predicate"])
    broken = copy.deepcopy(item)
    broken["attestation"]["bundle"]["dsseEnvelope"]["payload"] = "!!!not base64!!!"
    with pytest.raises(sel.SelectionError, match="cannot cut"):
        sel.signed_predicate_bytes(broken, item["verificationResult"]["statement"]["predicate"])
