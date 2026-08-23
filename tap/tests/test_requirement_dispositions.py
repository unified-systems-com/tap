"""Tests for coverage dispositions and full-corpus accounting
(`req-tap-traceability-disposition`, `req-tap-traceability-accounting`).

Every detector is exercised against a synthetic tree carrying a deliberate violation it
must reject — a guard that cannot fail is a false green. The synthetic spec builds its
`Trace:` lines directly; this module is not a convention module because dispositions live
in specs, not Python, so nothing here can be mistaken for a live marker.
"""

from __future__ import annotations

from pathlib import Path

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


def test_payload_is_optional_for_process_and_narrative(tmp_path: Path) -> None:
    tree = _tree(tmp_path, trace="Trace: `narrative`")
    corpus = load_corpus(tree)
    assert corpus.trace_problems == ()
    disposition = corpus.requirements["req-example-alpha"].disposition
    assert disposition is not None
    assert disposition.payload is None


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
    assert accounting(_tree(tmp_path, trace="Trace: `process`"))["req-example-alpha"] == "excluded"
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
    assert unaccounted_rids(_tree(tmp_path, trace="Trace: `process`")) == set()


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
    rendered = render_accounting_markdown(_tree(tmp_path, trace="Trace: `process`"))
    assert "**0 Unaccounted**" in rendered
    assert "`specs/spec-example.md`" in rendered


def test_committed_accounting_is_in_sync() -> None:
    """The committed block equals what the tree produces now.

    The consumer that keeps triage honest (`req-tap-traceability-accounting-3`): change a
    disposition, a claim, or a status anywhere in the corpus and this fails until the
    block is re-synced.

    Fix: `manage.py guards --sync-accounting`, then commit the regenerated block.
    """
    from tap.guards.base import REPO_ROOT

    spec = REPO_ROOT / "specs" / "spec-tap-requirement-traceability.md"
    text = spec.read_text(encoding="utf-8")
    _, rest = text.split(ACCOUNTING_BEGIN, 1)
    body, _ = rest.split(ACCOUNTING_END, 1)
    committed = ACCOUNTING_BEGIN + body + ACCOUNTING_END

    assert committed == render_accounting_markdown(REPO_ROOT), (
        "The committed accounting has drifted from the tree. Regenerate it with "
        "`manage.py guards --sync-accounting` and commit the result."
    )
