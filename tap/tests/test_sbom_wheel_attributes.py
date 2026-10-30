"""License and architecture for the locked Python components (req-cicd-sbom-33).

The fixtures are real. `wheel-seed-records.txt` is what `SEED_SCRIPT` printed inside the local
`ghcr.io/unified-systems-com/tap-web:latest` image on 2026-10-19: the WHEEL and METADATA headers of all 73 wheels in its
cache seed. `locked-pypi.txt` is the 71 pypi `name-version` keys of the attested tap-web revision 1 (PEP 503 name).
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "sbom_wheel_attributes", _REPO_ROOT / "scripts" / "sbom" / "wheel_attributes.py"
)
assert _spec is not None and _spec.loader is not None
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sbom"
SEED = (FIXTURES / "wheel-seed-records.txt").read_text()


@pytest.fixture(name="attributes")
def _attributes() -> dict[tuple[str, str], dict[str, Any]]:
    built: dict[tuple[str, str], dict[str, Any]] = wa.attributes_by_component(wa.parse_seed_records(SEED))
    return built


@pytest.fixture(name="cdx")
def _cdx() -> dict[str, Any]:
    document: dict[str, Any] = json.loads((FIXTURES / "tap-web-trimmed.cdx.json").read_text())
    return document


def _by_name(cdx: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in cdx["components"] if c["name"] == name)
    return found


def _props(component: dict[str, Any]) -> dict[str, str]:
    return {p["name"]: p["value"] for p in component.get("properties") or []}


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_the_real_seed_parses_to_seventy_three_wheels_with_tags_and_licenses():
    records = wa.parse_seed_records(SEED)
    assert len(records) == 73
    pydantic = next(r for r in records if r["name"] == "pydantic_core")
    assert pydantic["version"] == "2.46.4"
    assert "cp314-cp314-manylinux_2_17_aarch64" in pydantic["tags"]
    assert pydantic["expression"] == "MIT"


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_the_join_matches_sixty_eight_of_the_seventy_one_locked_components(attributes):
    locked = (FIXTURES / "locked-pypi.txt").read_text().split()
    assert len(locked) == 71
    matched: list[str] = []
    unmatched: list[str] = []
    for key in locked:
        name, _, version = key.rpartition("-")
        (matched if (name.replace("_", "-"), version) in attributes else unmatched).append(key)
    assert len(matched) == 68
    assert sorted(unmatched) == ["colorama-0.4.6", "tap-0.3.0", "tzdata-2026.3"]


@pytest.mark.spec("req-cicd-sbom-33-3")
@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["py3-none-any"], "noarch"),
        (["py2-none-any"], "noarch"),
        (["cp314-abi3-linux_aarch64"], "aarch64"),
        (["cp314-cp314-manylinux_2_17_aarch64", "cp314-cp314-manylinux2014_aarch64"], "aarch64"),
        (["cp313-cp313-manylinux_2_28_x86_64"], "x86_64"),
        (["cp313-cp313-macosx_11_0_arm64"], "aarch64"),
        (["cp313-cp313-win_amd64"], "x86_64"),
        (["cp313-cp313-win32"], None),
        ([], None),
    ],
)
def test_architecture_comes_from_the_platform_tag(tags, expected):
    assert wa.machine_from_tags(tags) == expected


@pytest.mark.spec("req-cicd-sbom-33-2")
def test_licenses_prefer_the_expression_then_the_license_text_then_the_classifier():
    base: dict[str, Any] = {"expression": None, "license": None, "classifiers": []}
    assert wa.license_choice({**base, "expression": "Apache-2.0 OR BSD-3-Clause"}) == (
        [{"expression": "Apache-2.0 OR BSD-3-Clause"}],
        "expression",
    )
    assert wa.license_choice({**base, "license": "MIT License"}) == ([{"license": {"name": "MIT License"}}], "license")
    assert wa.license_choice({**base, "classifiers": ["OSI Approved :: BSD License"]}) == (
        [{"license": {"name": "BSD License"}}],
        "classifier",
    )
    assert wa.license_choice({**base, "license": "UNKNOWN"}) is None
    assert wa.license_choice(base) is None


@pytest.mark.spec("req-cicd-sbom-33-2")
def test_four_real_wheels_have_only_a_classifier(attributes):
    choices = [wa.license_choice(r) for r in attributes.values()]
    sources = [choice[1] for choice in choices if choice is not None]
    assert sources.count("classifier") == 4
    assert all(wa.license_choice(r) is not None for r in attributes.values())


@pytest.mark.spec("req-cicd-sbom-33-1")
@pytest.mark.spec("req-cicd-sbom-33-4")
def test_applying_adds_attributes_without_changing_any_component_or_purl(cdx, attributes):
    before = copy.deepcopy(cdx)
    counts = wa.apply_to_cyclonedx(cdx, attributes)
    assert counts["pypi"] == 2 and counts["matched"] == 2
    assert len(cdx["components"]) == len(before["components"])
    for old, new in zip(before["components"], cdx["components"], strict=True):
        for field in ("name", "version", "purl", "cpe", "bom-ref", "type"):
            assert new.get(field) == old.get(field)


@pytest.mark.spec("req-cicd-sbom-33-2")
@pytest.mark.spec("req-cicd-sbom-33-3")
def test_a_matched_component_gets_a_license_and_an_architecture(cdx, attributes):
    wa.apply_to_cyclonedx(cdx, attributes)
    annotated = _by_name(cdx, "annotated-types")
    assert annotated["licenses"] == [{"expression": "MIT"}]
    props = _props(annotated)
    assert props["tap:license:source"] == "expression"
    assert props["tap:architecture"] == "noarch"
    assert props["tap:python:wheel-tag"] == "py3-none-any"
    assert "tap:licenses:status" not in props and "tap:architecture:status" not in props


@pytest.mark.spec("req-cicd-sbom-33-5")
def test_a_component_with_no_wheel_is_declared_unknown_never_silent(cdx, attributes):
    _by_name(cdx, "asgiref")["version"] = "0.0.0-not-in-the-seed"
    counts = wa.apply_to_cyclonedx(cdx, attributes)
    assert counts["licenses_unknown"] == 1 and counts["architecture_unknown"] == 1
    unknown = _by_name(cdx, "asgiref")
    props = _props(unknown)
    assert "licenses" not in unknown
    assert props["tap:licenses:status"] == "not-observed" and props["tap:licenses:reason"]
    assert props["tap:architecture:status"] == "not-observed" and props["tap:architecture:reason"]
    assert "tap:architecture" not in props


@pytest.mark.spec("req-cicd-sbom-33-5")
def test_applying_twice_replaces_earlier_attributes(cdx, attributes):
    wa.apply_to_cyclonedx(cdx, attributes)
    wa.apply_to_cyclonedx(cdx, attributes)
    names = [p["name"] for p in _by_name(cdx, "annotated-types")["properties"]]
    assert names.count("tap:architecture") == 1 and names.count("tap:license:source") == 1


@pytest.mark.spec("req-cicd-sbom-33-6")
def test_spdx_gets_the_expression_or_noassertion(attributes):
    def package(name: str, version: str) -> dict[str, Any]:
        return {
            "name": name,
            "versionInfo": version,
            "licenseDeclared": "NOASSERTION",
            "externalRefs": [{"referenceType": "purl", "referenceLocator": f"pkg:pypi/{name}@{version}"}],
        }

    spdx = {
        "packages": [
            package("annotated-types", "0.8.0"),
            package("not-in-the-seed", "1.0"),
            {"name": "openssl", "versionInfo": "3", "licenseDeclared": "Apache-2.0", "externalRefs": []},
        ]
    }
    wa.apply_to_spdx(spdx, attributes)
    declared = {p["name"]: p["licenseDeclared"] for p in spdx["packages"]}
    assert declared == {"annotated-types": "MIT", "not-in-the-seed": "NOASSERTION", "openssl": "Apache-2.0"}


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_only_pypi_components_are_touched(cdx, attributes):
    before = copy.deepcopy([c for c in cdx["components"] if not c.get("purl", "").startswith("pkg:pypi/")])
    wa.apply_to_cyclonedx(cdx, attributes)
    after = [c for c in cdx["components"] if not c.get("purl", "").startswith("pkg:pypi/")]
    assert after == before


def _write_dist(root: Path, rel: str, *, wheel: str | None, metadata: str | None) -> None:
    dist = root / rel
    dist.mkdir(parents=True)
    if wheel is not None:
        (dist / "WHEEL").write_text(wheel)
    if metadata is not None:
        (dist / "METADATA").write_text(metadata)


def _sample_seed(root: Path) -> None:
    _write_dist(
        root,
        "abc123/pydantic_core-2.46.4.dist-info",
        wheel="Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp314-cp314-manylinux_2_17_aarch64\nTag: cp314-cp314-manylinux2014_aarch64\n",
        metadata="Metadata-Version: 2.4\nName: pydantic_core\nLicense-Expression: MIT\nClassifier: Programming Language :: Python\n\nLicense: not-a-header (body)\n",
    )
    _write_dist(
        root,
        "def456/Idna-3.10.dist-info",
        wheel="Root-Is-Purelib: true\nTag: py3-none-any\n",
        metadata="Name: idna\nLicense: " + "x" * 300 + "\nClassifier: License :: OSI Approved :: BSD License\n",
    )
    _write_dist(root, "def456/nowheel-1.0.dist-info", wheel=None, metadata="License: Apache-2.0\n")
    _write_dist(root, "top-0.1.dist-info", wheel="Tag: py3-none-any\n", metadata=None)
    _write_dist(root, "a/b/c/too_deep-9.9.dist-info", wheel="Tag: py3-none-any\n", metadata="License: MIT\n")


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_the_tree_reader_prints_exactly_what_the_in_image_script_printed(tmp_path):
    """The script is the reference; the reader replaces running it, so it must print the same bytes."""
    import subprocess

    _sample_seed(tmp_path)
    script = wa.SEED_SCRIPT.replace(wa.SEED_DIR, str(tmp_path))
    shell = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — the reference script IS the oracle; argv list, no shell metacharacters from input  # nosec B603 B607  # noqa: S603, S607
        ["sh", "-c", script], check=True, capture_output=True, text=True
    ).stdout
    assert wa.seed_text_from_tree(tmp_path) == shell
    assert "@@ pydantic_core-2.46.4.dist-info" in shell and "too_deep" not in shell


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_a_missing_seed_directory_prints_nothing(tmp_path):
    assert wa.seed_text_from_tree(tmp_path / "absent") == ""
    assert wa.parse_seed_records(wa.seed_text_from_tree(tmp_path / "absent")) == []


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_a_link_in_the_copied_seed_is_never_followed(tmp_path):
    """`docker cp` copies links as links and the image is untrusted: a WHEEL, METADATA or dist-info linked to a runner
    path must not be read, or runner bytes could reach the SBOM."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("Tag: host-secret\nLicense: host-secret\n")
    _write_dist(outside, "real-9.9.dist-info", wheel="Tag: host-dist\n", metadata="License: host-dist\n")
    seed = tmp_path / "seed"
    _write_dist(seed, "h/ok-1.0.dist-info", wheel="Tag: py3-none-any\n", metadata="License: MIT\n")
    _write_dist(seed, "h/linked_files-2.0.dist-info", wheel=None, metadata=None)
    (seed / "h" / "linked_files-2.0.dist-info" / "WHEEL").symlink_to(outside / "secret")
    (seed / "h" / "linked_files-2.0.dist-info" / "METADATA").symlink_to(outside / "secret")
    (seed / "h" / "linked_dir-3.0.dist-info").symlink_to(outside / "real-9.9.dist-info", target_is_directory=True)
    text = wa.seed_text_from_tree(seed)
    assert "host-" not in text
    assert "@@ ok-1.0.dist-info" in text and "License: MIT" in text
    assert "linked_dir" not in text


@pytest.mark.spec("req-cicd-sbom-33-1")
def test_no_seed_file_is_read_whole(tmp_path):
    """An untrusted image can ship a huge METADATA. Reading is bounded: a very long line costs one chunk of memory and
    the lines after it still parse; a file of endless header lines stops at the line cap."""
    seed = tmp_path / "seed"
    long_line = "X-Padding: " + "p" * 3_000_000
    _write_dist(
        seed,
        "h/big-1.0.dist-info",
        wheel="Tag: py3-none-any\n",
        metadata=long_line + "\nLicense: MIT\n",
    )
    _write_dist(
        seed,
        "h/endless-2.0.dist-info",
        wheel="Tag: py3-none-any\n",
        metadata="License: A\n" * (wa._SEED_MAX_LINES + 500),
    )
    text = wa.seed_text_from_tree(seed)
    big = text.split("@@ endless-2.0.dist-info")[0]
    assert "License: MIT" in big and "ppp" not in text
    endless = text.split("@@ endless-2.0.dist-info")[1]
    assert endless.count("License: A") == wa._SEED_MAX_LINES
