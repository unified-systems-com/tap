"""The `.dockerignore` guard bites on each defect it names (`req-cicd-image-context-3`/`-4`).

`lint_dockerignore` is exercised on seeded text so every defect is proven to fail, naming itself, and the
committed file is proven to conform. `-5` is checked by reading the bind mount that the lanes run from.
"""

from __future__ import annotations

import pytest

from tap.guards.base import REPO_ROOT
from tap.guards.dockerignore import _tree_paths, lint_dockerignore

REASONS = {"req-cicd-image-context-reason-1"}
PATHS = ["tap/tests/fixtures/sbom/merge/sbom.cdx.json", "tap/tests/fixtures/sbom/README.md", "Dockerfile"]
GOOD = (
    "# Fixture SBOMs name vulnerable software on purpose.\n"
    "# spec: req-cicd-image-context-reason-1\n"
    "tap/tests/fixtures/sbom/\n"
)


@pytest.mark.spec("req-cicd-image-context-4")
def test_conforming_file_passes():
    assert lint_dockerignore(GOOD, REASONS, PATHS) == []


@pytest.mark.spec("req-cicd-image-context-4")
@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("tap/tests/fixtures/sbom/\n", "has no reason comment line"),
        ("# spec: req-cicd-image-context-reason-1\ntap/tests/fixtures/sbom/\n", "no reason sentence"),
        ("# Fixture SBOMs.\ntap/tests/fixtures/sbom/\n", "does not end its comment lines"),
        (
            "# Fixture SBOMs.\n# spec: req-cicd-image-context-reason-9\ntap/tests/fixtures/sbom/\n",
            "names no row of the Reason Register",
        ),
        (
            "# Fixture SBOMs.\n# spec: req-cicd-image-context-1\ntap/tests/fixtures/sbom/\n",
            "names no row of the Reason Register",
        ),
        (GOOD.replace("sbom/\n", "sbom/ # why\n"), "'#' on pattern line"),
        (GOOD + "\n# Nothing here.\n# spec: req-cicd-image-context-reason-1\nno/such/path/\n", "matches no path"),
        (GOOD + "\n# Reinclude.\n# spec: req-cicd-image-context-reason-1\n!no/such/path\n", "matches no path"),
    ],
    ids=[
        "no-reason",
        "no-reason-sentence",
        "no-spec-line",
        "unknown-row",
        "non-reason-row",
        "trailing-hash",
        "stale",
        "stale-negation",
    ],
)
def test_each_defect_fails_naming_itself(text, needle):
    defects = lint_dockerignore(text, REASONS, PATHS)
    assert any(needle in d for d in defects), defects


@pytest.mark.spec("req-cicd-image-context-4")
@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("tap/tests/fixtures/sbom/", "tap/tests/fixtures/sbom/merge/sbom.cdx.json", True),
        ("tap/tests/fixtures/sbom", "tap/tests/fixtures/sbom/README.md", True),
        ("/Dockerfile", "Dockerfile", True),
        ("**/*.cdx.json", "tap/tests/fixtures/sbom/merge/sbom.cdx.json", True),
        ("*.cdx.json", "tap/tests/fixtures/sbom/merge/sbom.cdx.json", False),
        ("tap/tests", "tap/tests_other/x", False),
    ],
)
def test_pattern_matching_follows_docker(pattern, path, expected):
    from tap.guards.dockerignore import _pattern_regex

    assert bool(_pattern_regex(pattern).match(path)) is expected


@pytest.mark.spec("req-cicd-image-context-1")
def test_committed_file_conforms_and_excludes_the_probe_sbom():
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert lint_dockerignore(text, REASONS, _tree_paths()) == []
    first_block = text.split("\n\n")[0].splitlines()
    assert first_block[-2] == "# spec: req-cicd-image-context-reason-1"
    assert first_block[-1] == "tap/tests/fixtures/sbom/"


@pytest.mark.spec("req-cicd-image-context-5")
def test_sbom_fixtures_are_read_from_the_checkout_not_the_image():
    """The excluded fixtures are tracked in the tree the lanes bind-mount over /app."""
    assert (REPO_ROOT / "tap/tests/fixtures/sbom/merge/sbom.cdx.json").is_file()
