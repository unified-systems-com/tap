"""Tests for requirement evidence and derived status (`req-tap-traceability-status`).

The gate under test is narrow on purpose: `Verified` requires two independent evidence
classes, and *nothing else fails*. A requirement with no claim at all is not a defect —
claims are opt-in (`req-tap-traceability-scope-1`) — so these tests pin both the firing and
the deliberate non-firing. The second half matters as much as the first: a guard that
over-fires would quietly convert a targeted convention into a coverage program.
"""

from __future__ import annotations

from pathlib import Path

from tap.spec_trace import (
    EVIDENCE_BEGIN,
    EVIDENCE_END,
    claimed_doctrine,
    collect_evidence,
    disputed,
    doctrine,
    invalid_claims,
    render_evidence_markdown,
    under_declared,
    unearned_verified,
    unevidenced_built,
)

_TOKEN = "TAP-" + "IMPLEMENTS"


def _spec(status: str) -> str:
    return f"""\
### Alpha
----
RID: `req-example-alpha`
Status: `{status}`

Alpha derives a fact exactly once.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | --- | --- |
| req-example-alpha-1 | First | {status} | A testable condition. |
"""


def _tree(tmp_path: Path, *, status: str, claim: bool = False, test: bool = False) -> Path:
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "specs" / "spec-example.md").write_text(_spec(status), encoding="utf-8")
    pkg = tmp_path / "tap"
    pkg.mkdir(parents=True, exist_ok=True)

    source = ""
    if claim:
        from tap.spec_trace import CODE_HASH_PLACEHOLDER, load_corpus

        digest = load_corpus(tmp_path).requirements["req-example-alpha"].content_hash
        source += (
            f'def derive():\n    """Derives it.\n\n'
            f"    {_TOKEN}: req-example-alpha@{digest}/{CODE_HASH_PLACEHOLDER} (derivation) — the one place."
            f'\n    """\n\n\n'
        )
    if test:
        source += 'import pytest\n\n\n@pytest.mark.spec("req-example-alpha-1")\ndef test_it():\n    pass\n'
    (pkg / "mod.py").write_text(source or "x = 1\n", encoding="utf-8")
    return tmp_path


# --- derived status ------------------------------------------------------------------


def test_no_evidence_derives_unevidenced(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Implemented")
    assert collect_evidence(tree)["req-example-alpha"].derived == "Unevidenced"


def test_claim_alone_derives_implemented_not_verified(tmp_path: Path) -> None:
    """One class is not verification — the implementation is the thing under test."""
    tree = _tree(tmp_path, status="Implemented", claim=True)
    evidence = collect_evidence(tree)["req-example-alpha"]
    assert evidence.derived == "Implemented"
    assert evidence.classes == 1


def test_test_alone_derives_tested(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Implemented", test=True)
    evidence = collect_evidence(tree)["req-example-alpha"]
    assert evidence.derived == "Tested"
    assert evidence.classes == 1


def test_both_classes_derive_verified(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Implemented", claim=True, test=True)
    evidence = collect_evidence(tree)["req-example-alpha"]
    assert evidence.derived == "Verified"
    assert evidence.classes == 2


# --- the gate ------------------------------------------------------------------------


def test_verified_without_evidence_fires(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Verified")
    assert [e.rid for e in unearned_verified(tree)] == ["req-example-alpha"]


def test_verified_with_only_one_class_fires(tmp_path: Path) -> None:
    """The whole point of the gate: a claim alone does not earn `Verified`."""
    tree = _tree(tmp_path, status="Verified", claim=True)
    assert [e.rid for e in unearned_verified(tree)] == ["req-example-alpha"]


def test_verified_with_both_classes_passes(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Verified", claim=True, test=True)
    assert unearned_verified(tree) == []


def test_implemented_without_evidence_does_not_fire(tmp_path: Path) -> None:
    """Deliberate non-firing: claims are opt-in, so their absence is never a defect."""
    tree = _tree(tmp_path, status="Implemented")
    assert unearned_verified(tree) == []
    assert [e.rid for e in unevidenced_built(tree)] == ["req-example-alpha"]


def test_evidence_on_a_proposed_requirement_is_reported_not_failed(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Proposed", test=True)
    assert [e.rid for e in under_declared(tree)] == ["req-example-alpha"]
    assert unearned_verified(tree) == []


# --- standing doctrine ---------------------------------------------------------------


def test_doctrine_is_in_neither_coverage_bucket(tmp_path: Path) -> None:
    """In force is neither built nor unbuilt — counting it as built was the miscount."""
    tree = _tree(tmp_path, status="In Force")
    assert [e.rid for e in doctrine(tree)] == ["req-example-alpha"]
    assert unevidenced_built(tree) == []
    assert under_declared(tree) == []
    assert unearned_verified(tree) == []


def test_claiming_doctrine_is_a_defect(tmp_path: Path) -> None:
    """The inverse check: a flag that only ever REMOVES a check is a flag nobody maintains.

    Doctrine is conformed to, not implemented. Without this, marking a requirement `In Force`
    would be a free way to make it disappear from every report — which is exactly how such a
    marker decays into decoration (OpenFastTrace's `Unwanted`; NIST's 0-of-3707).
    """
    tree = _tree(tmp_path, status="In Force", claim=True)
    assert [e.rid for e in claimed_doctrine(tree)] == ["req-example-alpha"]

    problems = invalid_claims(tree)
    assert len(problems) == 1
    assert "standing doctrine" in problems[0][1]


def test_doctrine_without_a_claim_is_clean(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="In Force", test=True)
    assert claimed_doctrine(tree) == []
    assert invalid_claims(tree) == []


# --- disputed (`req-tap-traceability-disputed`) --------------------------------------


def test_disputed_is_in_no_coverage_bucket(tmp_path: Path) -> None:
    """Disputed is where "code exists" and "requirement satisfied" come apart.

    Built would blend a claimless dispute into awaiting-evidence debt; unbuilt would treat
    its evidence as an anomaly; doctrine would reject its claims. Fourth bucket, own list.
    """
    tree = _tree(tmp_path, status="Disputed")
    assert [e.rid for e in disputed(tree)] == ["req-example-alpha"]
    assert unevidenced_built(tree) == []
    assert under_declared(tree) == []
    assert doctrine(tree) == []
    assert unearned_verified(tree) == []


def test_claiming_disputed_is_a_pointer_not_a_defect(tmp_path: Path) -> None:
    """Unlike doctrine, a claim on a disputed requirement must validate — it is how a
    reader finds the contested implementation. But it never resolves the dispute: the
    requirement stays in the disputed list with the claim attached.
    """
    tree = _tree(tmp_path, status="Disputed", claim=True)
    assert invalid_claims(tree) == []
    entries = disputed(tree)
    assert [e.rid for e in entries] == ["req-example-alpha"]
    assert entries[0].implemented_by  # the pointer survives
    assert unevidenced_built(tree) == []  # and still feeds no coverage bucket


def test_disputed_with_full_evidence_stays_disputed(tmp_path: Path) -> None:
    """Both evidence classes present and it still exits nothing — only a human ruling
    (a spec edit or a code re-stamp) leaves the status.
    """
    tree = _tree(tmp_path, status="Disputed", claim=True, test=True)
    assert [e.rid for e in disputed(tree)] == ["req-example-alpha"]
    assert unearned_verified(tree) == []
    assert under_declared(tree) == []


def test_report_renders_disputed_section(tmp_path: Path) -> None:
    rendered = render_evidence_markdown(_tree(tmp_path, status="Disputed", claim=True))
    assert "**1** disputed" in rendered
    assert "**Disputed**" in rendered
    assert "`req-example-alpha`" in rendered


# --- the report ----------------------------------------------------------------------


def test_report_is_bounded_by_its_markers(tmp_path: Path) -> None:
    rendered = render_evidence_markdown(_tree(tmp_path, status="Implemented", claim=True))
    assert rendered.startswith(EVIDENCE_BEGIN)
    assert rendered.rstrip().endswith(EVIDENCE_END)


def test_committed_report_is_in_sync() -> None:
    """The committed block equals what the tree produces now.

    This is what makes the report a *consumer* of the claims rather than a dashboard
    someone could forget to regenerate: change the evidence and this fails until the block
    is re-synced. Every durable tag convention earned its accuracy from something that
    visibly breaks when the tag is wrong (`req-tap-traceability-status-2`).

    Fix: `manage.py guards --sync-evidence`, then commit the regenerated block.
    """
    from tap.guards.base import REPO_ROOT

    spec = REPO_ROOT / "specs" / "spec-tap-requirement-traceability.md"
    text = spec.read_text(encoding="utf-8")
    _, rest = text.split(EVIDENCE_BEGIN, 1)
    body, _ = rest.split(EVIDENCE_END, 1)
    committed = EVIDENCE_BEGIN + body + EVIDENCE_END

    assert committed == render_evidence_markdown(REPO_ROOT), (
        "The committed evidence report has drifted from the tree. Regenerate it with "
        "`manage.py guards --sync-evidence` and commit the result."
    )


def test_report_lists_evidenced_requirements_only(tmp_path: Path) -> None:
    """Compact by design — a report nobody can read is a report nobody reads."""
    tree = _tree(tmp_path, status="Implemented", claim=True)
    (tree / "specs" / "spec-other.md").write_text(
        "### Beta\n----\nRID: `req-example-beta`\nStatus: `Implemented`\n\nUnevidenced.\n",
        encoding="utf-8",
    )
    rendered = render_evidence_markdown(tree)
    assert "req-example-alpha" in rendered
    assert "| `req-example-beta` |" not in rendered
