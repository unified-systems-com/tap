"""Tests for coverage dispositions and full-corpus accounting
(`req-tap-traceability-disposition`, `req-tap-traceability-accounting`).

Every detector is exercised against a synthetic tree carrying a deliberate violation it
must reject — a guard that cannot fail is a false green. The synthetic spec builds its
`Trace:` lines directly; this module is not a convention module because dispositions live
in specs, not Python, so nothing here can be mistaken for a live marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.spec_trace import (
    ACCOUNTING_BEGIN,
    ACCOUNTING_END,
    CODE_HASH_PLACEHOLDER,
    accounting,
    bucket_of,
    collect_evidence,
    contradicted_dispositions,
    load_corpus,
    render_accounting_markdown,
    stale_claims,
    unaccounted_rids,
)

_TOKEN = "TAP-" + "IMPLEMENTS"


def _spec(status: str = "Implemented", trace: str = "") -> str:
    trace_line = f"{trace}\n" if trace else ""
    return f"""\
### Alpha
----
RID: `req-example-alpha`
Status: `{status}`
{trace_line}
Alpha derives a fact exactly once.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | --- | --- |
| req-example-alpha-1 | First | {status} | A testable condition. |
"""


def _tree(tmp_path: Path, *, status: str = "Implemented", trace: str = "", module: str = "") -> Path:
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "specs" / "spec-example.md").write_text(_spec(status, trace), encoding="utf-8")
    pkg = tmp_path / "tap"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod.py").write_text(module or "x = 1\n", encoding="utf-8")
    return tmp_path


def _claim_module(tree: Path) -> str:
    digest = load_corpus(tree).requirements["req-example-alpha"].content_hash
    return (
        f'def derive():\n    """Derives it.\n\n'
        f"    {_TOKEN}: req-example-alpha@{digest}/{CODE_HASH_PLACEHOLDER} (derivation) — the one place."
        f'\n    """\n'
    )


# --- parsing and validation ----------------------------------------------------------


def test_valid_disposition_is_parsed(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `process` — humans conform, code does not")
    corpus = load_corpus(tree)
    assert corpus.trace_problems == ()
    disposition = corpus.requirements["req-example-alpha"].disposition
    assert disposition is not None
    assert disposition.category == "process"
    assert disposition.payload == "humans conform, code does not"


def test_payload_is_mandatory_for_every_category(tmp_path: Path) -> None:
    """A bare marker publishes an empty explanation — reasons are mandatory everywhere
    (req-tap-traceability-disposition-5; previously optional for process/narrative)."""
    for category in ("process", "narrative", "non-python", "external"):
        tree = _tree(tmp_path / category, trace=f"Trace: `{category}`")
        corpus = load_corpus(tree)
        assert corpus.trace_problems, f"bare `{category}` marker must fail the parse"
        assert corpus.requirements["req-example-alpha"].disposition is None


def test_unknown_category_fails_closed(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `invented` — nope")
    problems = load_corpus(tree).trace_problems
    assert len(problems) == 1
    assert "'invented'" in problems[0]


def test_near_miss_fails_closed(tmp_path: Path) -> None:
    """A misspelled marker must FAIL, not read as 'no marker here' — the SAFTEY: hole."""
    tree = _tree(tmp_path, trace="Traced: `process` — typo")
    problems = load_corpus(tree).trace_problems
    assert len(problems) == 1
    assert "misses" in problems[0]


def test_mandatory_payload_is_enforced(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `non-python`")
    problems = load_corpus(tree).trace_problems
    assert len(problems) == 1
    assert "requires a payload" in problems[0]


def test_nonexistent_non_python_target_fails(tmp_path: Path) -> None:
    """An exclusion whose target cannot be pointed at is an assertion nothing can check."""
    tree = _tree(tmp_path, trace="Trace: `non-python` — scripts/does-not-exist")
    problems = load_corpus(tree).trace_problems
    assert len(problems) == 1
    assert "does not exist" in problems[0]


def test_existing_non_python_target_passes(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `non-python` — tap/mod.py")
    assert load_corpus(tree).trace_problems == ()


def test_marker_on_doctrine_fails(tmp_path: Path) -> None:
    """Derived buckets reject hand-written markers — one source per fact."""
    tree = _tree(tmp_path, status="In Force", trace="Trace: `process` — redundant")
    problems = load_corpus(tree).trace_problems
    assert len(problems) == 1
    assert "derived" in problems[0]


def test_marker_on_disputed_fails(tmp_path: Path) -> None:
    tree = _tree(tmp_path, status="Disputed", trace="Trace: `process` — redundant")
    assert len(load_corpus(tree).trace_problems) == 1


def test_two_markers_on_one_requirement_fail(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `process`\nTrace: `narrative`")
    problems = load_corpus(tree).trace_problems
    assert any("one disposition" in p for p in problems)


# --- hash neutrality (`req-tap-traceability-disposition-2`) --------------------------


def test_adding_a_marker_does_not_change_the_content_hash(tmp_path: Path) -> None:
    """THE sequencing property: bulk triage must never churn a claim's spec hash."""
    bare = load_corpus(_tree(tmp_path)).requirements["req-example-alpha"].content_hash
    marked = (
        load_corpus(_tree(tmp_path, trace="Trace: `process` — a reason")).requirements["req-example-alpha"].content_hash
    )
    assert bare == marked


def test_generated_block_content_does_not_change_the_content_hash(tmp_path: Path) -> None:
    """A generated block is machine-moved metadata: regenerating it (any session, any sync)
    must never drift a claim on the enclosing requirement — the Map-block lesson."""
    tree = _tree(tmp_path)
    spec = tree / "specs" / "spec-example.md"
    block = "\n<!-- BEGIN GENERATED MAP — manage.py guards --sync-map -->\n| row one |\n<!-- END GENERATED MAP -->\n"
    base = spec.read_text(encoding="utf-8").replace(
        "Alpha derives a fact exactly once.", "Alpha derives a fact exactly once.\n" + block
    )
    spec.write_text(base, encoding="utf-8")
    with_one_row = load_corpus(tree).requirements["req-example-alpha"].content_hash

    spec.write_text(base.replace("| row one |", "| row one |\n| row two |"), encoding="utf-8")
    with_two_rows = load_corpus(tree).requirements["req-example-alpha"].content_hash
    assert with_one_row == with_two_rows

    bare = load_corpus(_tree(tmp_path)).requirements["req-example-alpha"].content_hash
    assert with_one_row == bare  # the whole block is outside the hash, not merely stable


def test_adding_a_marker_does_not_stale_claims(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree / "tap" / "mod.py").write_text(_claim_module(tree), encoding="utf-8")
    assert stale_claims(tree) == []

    spec = tree / "specs" / "spec-example.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "Status: `Implemented`\n", "Status: `Implemented`\nTrace: `process`\n"
        ),
        encoding="utf-8",
    )
    # The marker itself is a (contradicted) defect on a claimed requirement — but it must
    # not ALSO orphan the claim: the two defects are independent, and hash churn here is
    # what would make bulk triage impossible.
    assert stale_claims(tree) == []


# --- evidence contradiction (`req-tap-traceability-disposition-3`) -------------------


def test_marker_with_evidence_is_contradicted(tmp_path: Path) -> None:
    """Marking a requirement excluded costs the ability to claim it."""
    tree = _tree(tmp_path, trace="Trace: `process` — but claimed anyway")
    (tree / "tap" / "mod.py").write_text(_claim_module(tree), encoding="utf-8")
    contradicted = contradicted_dispositions(tree)
    assert [e.rid for e in contradicted] == ["req-example-alpha"]


def test_marker_without_evidence_is_not_contradicted(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `process` — honest exclusion")
    assert contradicted_dispositions(tree) == []


# --- accounting (`req-tap-traceability-accounting`) ----------------------------------


def test_every_requirement_gets_exactly_one_bucket(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    buckets = accounting(tree)
    corpus = load_corpus(tree)
    assert set(buckets) == set(corpus.requirements)
    assert all(
        b in {"mapped", "excluded", "doctrine", "disputed", "unbuilt", "retired", "unaccounted"}
        for b in buckets.values()
    )


def test_buckets_derive_from_status_evidence_and_marker(tmp_path: Path) -> None:
    assert accounting(_tree(tmp_path))["req-example-alpha"] == "unaccounted"
    assert accounting(_tree(tmp_path, status="In Force"))["req-example-alpha"] == "doctrine"
    assert accounting(_tree(tmp_path, status="Disputed"))["req-example-alpha"] == "disputed"
    assert accounting(_tree(tmp_path, trace="Trace: `process` — a reason"))["req-example-alpha"] == "excluded"
    assert accounting(_tree(tmp_path, status="Proposed"))["req-example-alpha"] == "unbuilt"
    assert accounting(_tree(tmp_path, status="Backlog"))["req-example-alpha"] == "unbuilt"
    assert accounting(_tree(tmp_path, status="Deprecated"))["req-example-alpha"] == "retired"

    tree = _tree(tmp_path)
    (tree / "tap" / "mod.py").write_text(_claim_module(tree), encoding="utf-8")
    assert accounting(tree)["req-example-alpha"] == "mapped"


def test_flipping_to_implemented_without_evidence_enters_unaccounted(tmp_path: Path) -> None:
    """THE enforcement property: claiming done is where the DoD bites.

    An unbuilt requirement is accounted by its own status; the moment it declares
    `Implemented` with neither evidence nor an exclusion, it becomes a new Unaccounted
    entry — which the ratchet fails, because new entries are never grandfathered.
    """
    tree = _tree(tmp_path, status="Proposed")
    assert unaccounted_rids(tree) == set()

    spec = tree / "specs" / "spec-example.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("`Proposed`", "`Implemented`"), encoding="utf-8")
    assert unaccounted_rids(tree) == {"req-example-alpha"}


def test_marker_placed_at_birth_survives_the_flip(tmp_path: Path) -> None:
    """A process requirement carries its exclusion from birth — flipping its status later
    needs no triage, because the marker outranks the unbuilt derivation."""
    tree = _tree(tmp_path, status="Proposed", trace="Trace: `process` — humans conform")
    assert accounting(tree)["req-example-alpha"] == "excluded"
    assert load_corpus(tree).trace_problems == ()

    spec = tree / "specs" / "spec-example.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("`Proposed`", "`Implemented`"), encoding="utf-8")
    assert accounting(tree)["req-example-alpha"] == "excluded"


def test_unaccounted_rids_is_the_ratchet_measure(tmp_path: Path) -> None:
    assert unaccounted_rids(_tree(tmp_path)) == {"req-example-alpha"}
    assert unaccounted_rids(_tree(tmp_path, trace="Trace: `process` — a reason")) == set()


def test_bucket_of_is_total_for_odd_statuses(tmp_path: Path) -> None:
    """A status outside every vocabulary still buckets — Unaccounted, never a crash."""
    tree = _tree(tmp_path, status="Partially Implemented")
    corpus = load_corpus(tree)
    evidence = collect_evidence(tree)
    assert bucket_of(corpus.requirements["req-example-alpha"], evidence["req-example-alpha"]) == "unaccounted"


# --- the report ----------------------------------------------------------------------


def test_report_is_bounded_by_its_markers(tmp_path: Path) -> None:
    rendered = render_accounting_markdown(_tree(tmp_path))
    assert rendered.startswith(ACCOUNTING_BEGIN)
    assert rendered.rstrip().endswith(ACCOUNTING_END)


def test_report_carries_the_unaccounted_headline_and_per_spec_rows(tmp_path: Path) -> None:
    rendered = render_accounting_markdown(_tree(tmp_path, trace="Trace: `process` — a reason"))
    assert "**0 Unaccounted**" in rendered
    assert "`specs/spec-example.md`" in rendered


@pytest.mark.spec("req-tap-traceability-fragments-4")
def test_committed_fragments_are_in_sync() -> None:
    """Every committed per-spec fragment equals what the tree renders now.

    The consumer that keeps triage honest after the fragmentation
    (`req-tap-traceability-fragments`): change a disposition, a claim, or a status in
    any spec and that spec's fragment goes stale until re-synced. Per-spec on purpose —
    disjoint triage branches touch disjoint files, and no aggregate is committed
    anywhere (a committed total is a guaranteed cross-branch merge conflict).

    Fix: `manage.py guards --sync-accounting` (or --sync-evidence; same artifact),
    then commit the changed fragments.
    """
    from tap.guards.base import REPO_ROOT
    from tap.spec_trace import fragment_drift

    assert fragment_drift(REPO_ROOT) == [], (
        "Committed traceability fragments drifted from the tree. Regenerate with "
        "`manage.py guards --sync-accounting` and commit the changed fragments."
    )


@pytest.mark.spec("req-tap-traceability-fragments-4")
def test_headerless_stranger_in_fragment_dir_is_drift(tmp_path: Path) -> None:
    """A file in the fragment directory that is NOT a rendered fragment fails drift
    even without the generated header — stripping the first line must not hide a
    counterfeit or stale report (the PR #122 Codex-seat bypass)."""
    from tap.spec_trace import TRACEABILITY_DIR, fragment_drift, sync_traceability_fragments

    tree = _acidless_tree(tmp_path)
    sync_traceability_fragments(tree)
    assert fragment_drift(tree) == []
    stranger = tree / TRACEABILITY_DIR / "counterfeit.md"
    stranger.write_text("totally innocent prose, no header at all\n", encoding="utf-8")
    problems = fragment_drift(tree)
    assert any("counterfeit.md" in p_ for p_ in problems)


# --- zero-ACID floor: payable vs exempt (`req-tap-traceability-acid-floor-3`) --------


def _acidless_spec(status: str, trace: str) -> str:
    trace_line = f"{trace}\n" if trace else ""
    return f"""\
### Beta
----
RID: `req-example-beta`
Status: `{status}`
{trace_line}
Beta is built but authored prose-only — no acceptance criteria.
"""


def _acidless_tree(tmp_path: Path, *, status: str = "Implemented", trace: str = "") -> Path:
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "specs" / "spec-example.md").write_text(_acidless_spec(status, trace), encoding="utf-8")
    pkg = tmp_path / "tap"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_zero_acid_floor_counts_undispositioned_built(tmp_path: Path) -> None:
    """A built requirement with no ACIDs and no disposition is payable debt — the
    floor ratchet's measure (req-tap-traceability-acid-floor-1)."""
    from tap.spec_trace import zero_acid_built

    tree = _acidless_tree(tmp_path)
    assert zero_acid_built(tree) == {"req-example-beta"}


def test_zero_acid_floor_exempts_documented_excluded(tmp_path: Path) -> None:
    """A documented-excluded requirement leaves the ratchet's measure but stays
    visible as exempt (req-tap-traceability-acid-floor-3) — exempt-and-counted,
    never exempt-and-vanished."""
    from tap.spec_trace import _zero_acid_kind, load_corpus, zero_acid_built

    tree = _acidless_tree(tmp_path, trace="Trace: `process` — humans hold this line, code cannot")
    assert zero_acid_built(tree) == set()
    req = load_corpus(tree).requirements["req-example-beta"]
    assert _zero_acid_kind(req) == "exempt"


def test_accounting_report_agrees_with_ratchet_measure(tmp_path: Path) -> None:
    """The report's payable headline number IS the ratchet's measure — one predicate,
    two consumers (the PR #114 Codex finding: they derived it separately and disagreed)."""
    from tap.spec_trace import zero_acid_built

    tree = _acidless_tree(tmp_path)
    report = render_accounting_markdown(tree)
    payable = len(zero_acid_built(tree))
    assert f"**{payable}** built with zero ACIDs (payable" in report


def test_exclusions_ledger_publishes_reason_verbatim(tmp_path: Path) -> None:
    """The Exclusions Ledger lists the excluded requirement's category and reason,
    flagging zero-ACID exempt rows (req-tap-traceability-disposition-5)."""
    tree = _acidless_tree(tmp_path, trace="Trace: `process` — humans hold this line, code cannot")
    report = render_accounting_markdown(tree)
    assert "### Exclusions Ledger" in report
    assert "| `req-example-beta` | process | ⚠ | humans hold this line, code cannot |" in report


def test_headline_carries_both_zero_acid_numbers(tmp_path: Path) -> None:
    """The headline publishes payable AND exempt counts — exempt-and-counted,
    never exempt-and-vanished (the PR #114 visibility resolution)."""
    tree = _acidless_tree(tmp_path, trace="Trace: `process` — humans hold this line, code cannot")
    report = render_accounting_markdown(tree)
    assert "**0** built with zero ACIDs (payable" in report
    assert "**1** zero-ACID among the excluded (exempt" in report


def test_per_spec_column_counts_payable_only(tmp_path: Path) -> None:
    """The per-spec 0-ACID column is the payable count — an exempt requirement in
    the same spec must not inflate it."""
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    two = (
        _acidless_spec("Implemented", "")
        + "\n"
        + _acidless_spec("Implemented", "")
        .replace("req-example-beta", "req-example-gamma")
        .replace("### Beta", "### Gamma")
        .replace("Status: `Implemented`\n", "Status: `Implemented`\nTrace: `process` — humans hold this line\n", 1)
    )
    (tmp_path / "specs" / "spec-example.md").write_text(two, encoding="utf-8")
    pkg = tmp_path / "tap"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")

    report = render_accounting_markdown(tmp_path)
    for line in report.splitlines():
        if line.startswith("| `specs/spec-example.md`"):
            assert line.rstrip().endswith("| 1 |"), line
            break
    else:  # pragma: no cover
        raise AssertionError("per-spec row missing")


def test_ledger_escapes_pipes_in_the_reason(tmp_path: Path) -> None:
    """A payload CAN contain `|` (unlike a newline, which the grammar forbids) —
    the ledger must escape it or the Markdown table shears."""
    tree = _acidless_tree(tmp_path, trace="Trace: `process` — either A | or B holds")
    report = render_accounting_markdown(tree)
    assert "| either A \\| or B holds |" in report


@pytest.mark.spec("req-tap-traceability-fragments-1")
def test_fragment_name_collision_fails_loudly(tmp_path: Path) -> None:
    """Two specs whose stems collide must abort the render, never merge silently."""
    import pytest as _pytest

    from tap.spec_trace import render_traceability_fragments

    tree = _acidless_tree(tmp_path)
    (tree / "tap_x" / "specs").mkdir(parents=True)
    (tree / "tap_x" / "specs" / "spec-example.md").write_text(
        _acidless_spec("Implemented", "").replace("req-example-beta", "req-example-delta"), encoding="utf-8"
    )
    with _pytest.raises(ValueError, match="collision"):
        render_traceability_fragments(tree)


@pytest.mark.spec("req-tap-traceability-fragments-3")
def test_sync_preserves_unchanged_fragments_and_removes_orphans(tmp_path: Path) -> None:
    """Minimal sync: an unchanged fragment's mtime survives; a generated orphan is
    removed; both halves of fragments-3 in one temporary tree."""
    from tap.spec_trace import FRAGMENT_HEADER, TRACEABILITY_DIR, sync_traceability_fragments

    tree = _acidless_tree(tmp_path)
    written, deleted = sync_traceability_fragments(tree)
    assert written and not deleted

    frag = tree / TRACEABILITY_DIR / written[0]
    stamp = 946684800.0  # fixed epoch: any rewrite would move mtime forward
    import os

    os.utime(frag, (stamp, stamp))
    orphan = tree / TRACEABILITY_DIR / "old-deleted-spec.md"
    orphan.write_text(FRAGMENT_HEADER + "\nstale generated leftovers\n", encoding="utf-8")

    written2, deleted2 = sync_traceability_fragments(tree)
    assert written2 == []
    assert deleted2 == ["old-deleted-spec.md"]
    assert not orphan.exists()
    assert frag.stat().st_mtime == stamp
