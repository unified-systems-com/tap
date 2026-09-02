"""Requirement-block metadata layout guard — `req-tap-traceability-disposition-6` (tap#312).

A requirement block's metadata fields (`RID:`, `Status:`, `Trace:`) are line-anchored for
the parser but paragraph-joined by Markdown: an adjacent `RID:`/`Status:` pair renders as
`RID: req-example-thing Status: Proposed` — ONE line — on GitHub and in every editor preview. The
two-line form separates the fields with one blank line, and this guard is what keeps the
rendered shape from regressing: the corpus parser reports every adjacent pair (file, line
and RID) through the same problem channel a `Trace:` near-miss uses, and this guard fails
on any such entry.

The form is hash-neutral (`_normalize` strips `Status:`/`Trace:` before hashing), so
applying it never orphans a claim; `scripts/spec-two-line-metadata` applies it mechanically
and idempotently, in core and in every evicted plugin repo's `specs/`.

Hard lint, no baseline: the corpus was swept in the same change this landed.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class RequirementBlockLayoutGuard(Guard):
    slug = "requirement-block-layout"
    map_row = "Requirement-block metadata layout (two-line form)"
    rid = "req-tap-traceability-disposition"
    description = (
        "An adjacent `RID:`/`Status:` or `Status:`/`Trace:` pair parses fine but renders "
        "as one Markdown line, so every requirement's metadata reads as a single run-on "
        "field on GitHub — the shape regresses silently because no parser ever cared."
    )

    def check(self) -> None:
        from tap.spec_trace import ADJACENCY_PROBLEM_PHRASE, load_corpus

        problems = [p for p in load_corpus(REPO_ROOT).trace_problems if ADJACENCY_PROBLEM_PHRASE in p]
        if not problems:
            return
        # Raised explicitly rather than asserted (the non-test Bandit B101 policy in
        # `.codacy.yaml`): a bare `assert` vanishes under `python -O`, which would turn a
        # guard into a function that inspects the tree and passes.
        raise AssertionError(
            "Requirement metadata rendered on one line. `RID:`, `Status:` and `Trace:` are separated "
            "by one blank line each (req-tap-traceability-disposition-6); run "
            "`scripts/spec-two-line-metadata .` to apply the form:\n  " + "\n  ".join(problems)
        )
