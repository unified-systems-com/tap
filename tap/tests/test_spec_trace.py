"""Tests for the specification parser and RID citation scanner (`req-docs-rid-integrity`).

Every detector here is exercised against a synthetic tree with a *deliberate* violation it
must reject. A guard that cannot fail is a false green — the failure mode that let pytest's
own `--strict` deprecation silently revert for two major versions, and the same shape as
TAP's evicted-plugin-tests scar.

The precision cases are not hypothetical: each one is a phantom citation this scanner
actually produced against the live tree before the pattern was tightened.
"""

from __future__ import annotations

from pathlib import Path

from tap.spec_trace import (
    citation_key,
    dangling_citations,
    load_corpus,
    unresolvable_markers,
)

_SPEC = """\
# Example Spec

| RID | Name | Status |
| --- | --- | --- |
| req-example-alpha | Alpha | Implemented |

### Alpha
----
RID: `req-example-alpha`
Status: `Implemented`

Alpha does a thing.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | --- | --- |
| req-example-alpha-1 | First | Implemented | A testable condition. |
| req-example-alpha-2 | Second | Proposed | Another one. |

#### Future

Nothing yet.

### Beta
----
RID: `req-example-beta.sec`
Status: `Proposed`

The security facet.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | --- | --- |
| req-example-beta.sec-1 | Facet criterion | Proposed | Dotted parent, dotted child. |
"""


def _tree(tmp_path: Path, *, python: str = "", doc: str = "") -> Path:
    """A minimal synthetic repo: one spec, one first-party module, one living doc."""
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "specs" / "spec-example.md").write_text(_SPEC, encoding="utf-8")
    (tmp_path / "tap").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tap" / "sample.py").write_text(python or "x = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "doc-example.md").write_text(doc or "# Doc\n", encoding="utf-8")
    return tmp_path


# --- parsing -------------------------------------------------------------------------


def test_dotted_rid_survives_the_parse(tmp_path: Path) -> None:
    """The bug this parser replaced truncated `req-example-x.sec` to its stem — 30 RIDs, silently."""
    corpus = load_corpus(_tree(tmp_path))
    assert "req-example-beta.sec" in corpus.requirements
    assert "req-example-beta" not in corpus.defined


def test_acids_associate_with_their_parent(tmp_path: Path) -> None:
    """ACID tables live under a level-4 heading *inside* the requirement's own section."""
    corpus = load_corpus(_tree(tmp_path))
    assert corpus.requirements["req-example-alpha"].acids == (
        "req-example-alpha-1",
        "req-example-alpha-2",
    )
    assert corpus.parent_of("req-example-beta.sec-1") == "req-example-beta.sec"


def test_status_is_read_per_requirement(tmp_path: Path) -> None:
    corpus = load_corpus(_tree(tmp_path))
    assert corpus.requirements["req-example-alpha"].status == "Implemented"
    assert corpus.requirements["req-example-beta.sec"].status == "Proposed"


def test_content_hash_ignores_status_and_reflow(tmp_path: Path) -> None:
    """Status moves on its own lifecycle and whitespace is not meaning — neither may churn a claim."""
    before = load_corpus(_tree(tmp_path)).requirements["req-example-alpha"].content_hash

    spec = tmp_path / "specs" / "spec-example.md"
    spec.write_text(
        spec.read_text(encoding="utf-8")
        .replace("RID: `req-example-alpha`\nStatus: `Implemented`", "RID: `req-example-alpha`\nStatus: `Verified`")
        .replace("Alpha does a thing.", "Alpha  does a\nthing."),
        encoding="utf-8",
    )
    assert load_corpus(tmp_path).requirements["req-example-alpha"].content_hash == before


def test_content_hash_changes_when_meaning_changes(tmp_path: Path) -> None:
    before = load_corpus(_tree(tmp_path)).requirements["req-example-alpha"].content_hash
    spec = tmp_path / "specs" / "spec-example.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("A testable condition.", "A materially different condition."),
        encoding="utf-8",
    )
    assert load_corpus(tmp_path).requirements["req-example-alpha"].content_hash != before


# --- citation scanning precision -----------------------------------------------------


def test_dangling_citation_is_detected(tmp_path: Path) -> None:
    """The detector must fire — this is the guard's whole job.

    Note the token is deliberately NOT in the reserved `req-example*` namespace: that
    namespace is skipped by design, so using it here would pass for the wrong reason.
    """
    tree = _tree(tmp_path, python='"""Relates to req-absent-thing."""\n')
    dangling = dangling_citations(tree)
    assert [c.token for c in dangling] == ["req-absent-thing"]
    assert citation_key(dangling[0], tree) == "tap/sample.py::req-absent-thing"


def test_resolvable_citation_is_not_flagged(tmp_path: Path) -> None:
    tree = _tree(tmp_path, python='"""Implements req-example-alpha-1 exactly."""\n')
    assert dangling_citations(tree) == []


def test_hyphen_prefixed_word_is_not_a_citation(tmp_path: Path) -> None:
    """A `spec-req-<name>.md` filename must not yield a phantom citation — a bare \\b fires after `-`."""
    tree = _tree(tmp_path, doc="See spec-req-template.md for the shape.\n")
    assert dangling_citations(tree) == []


def test_line_wrapped_citation_is_not_captured_as_its_stem(tmp_path: Path) -> None:
    """Prose wraps mid-token; the truncated stem is not a citation anyone made."""
    tree = _tree(tmp_path, doc="The rule is req-example-alpha-\n1 in the table above.\n")
    assert [c.token for c in dangling_citations(tree)] == []


def test_placeholder_namespace_is_skipped(tmp_path: Path) -> None:
    """Docs *about* the convention name RIDs that do not exist; those must not become debt."""
    tree = _tree(tmp_path, doc="Mint one with `scripts/implements-tag req-example-name`.\n")
    assert dangling_citations(tree) == []


def test_archival_corpora_are_excluded(tmp_path: Path) -> None:
    """A retired RID in an after-action report is a record, not drift (req-docs-rid-integrity-3)."""
    tree = _tree(tmp_path)
    aar = tree / "docs" / "aar"
    aar.mkdir(parents=True)
    (aar / "2026-01-01-postmortem.md").write_text("We shipped req-example-retired.\n", encoding="utf-8")
    assert dangling_citations(tree) == []


def test_string_literals_are_not_citations(tmp_path: Path) -> None:
    """A RID inside an arbitrary string is data — a guard's own `rid` field, an error message."""
    tree = _tree(tmp_path, python='rid = "req-absent-thing"\n')
    assert dangling_citations(tree) == []


# --- spec markers --------------------------------------------------------------------


def test_unresolvable_spec_marker_is_detected(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        python='import pytest\n\n\n@pytest.mark.spec("req-absent-thing-9")\ndef test_thing():\n    pass\n',
    )
    assert [m.token for m in unresolvable_markers(tree)] == ["req-absent-thing-9"]


def test_resolvable_spec_marker_passes(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        python='import pytest\n\n\n@pytest.mark.spec("req-example-alpha-1")\ndef test_thing():\n    pass\n',
    )
    assert unresolvable_markers(tree) == []
