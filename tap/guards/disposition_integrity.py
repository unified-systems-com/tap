"""Coverage-disposition integrity guard — `req-tap-traceability-disposition`.

TAP-IMPLEMENTS: req-tap-traceability-disposition@54d4185ba383/64bc21c1ab91 (enforcement) —
    the guard that fails malformed, contradicted and derived-bucket markers.

A `Trace:` marker asserts that a requirement legitimately maps to no code. This guard is
what keeps that assertion checkable: a near-miss spelling, an unknown category, a missing
mandatory payload, a `non-python` payload naming a file that does not exist, a marker on a
derived bucket (doctrine/disputed), or a marker on a requirement that carries evidence
anyway — each fails, loudly, with the site named.

The evidence contradiction is the load-bearing half: marking a requirement excluded must
cost the ability to claim it, or the marker becomes a flag that only ever removes a check —
and a flag that only ever removes a check is a flag nobody maintains (the doctrine-claim
lesson, OpenFastTrace's `Unwanted` defect).

Hard lint, no baseline: the corpus carried zero markers when this landed.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class DispositionIntegrityGuard(Guard):
    slug = "disposition-integrity"
    map_row = "Coverage-disposition integrity"
    rid = "req-tap-traceability-disposition"
    description = (
        "A malformed or contradicted `Trace:` exclusion reads as a legitimate reason a "
        "requirement has no code mapping — the accounting then reports a gap as closed "
        "when nothing checked the closure."
    )

    def check(self) -> None:
        from tap.spec_trace import contradicted_dispositions, load_corpus

        corpus = load_corpus(REPO_ROOT)
        problems = list(corpus.trace_problems)
        problems += [
            f"{e.rid} — carries a `Trace:` exclusion AND evidence "
            f"(implementation={'yes' if e.implemented_by else 'no'}, verified-criteria={len(e.verified_acids)}); "
            "an excluded requirement cannot carry evidence — remove whichever side is wrong"
            for e in contradicted_dispositions(REPO_ROOT)
        ]
        assert not problems, (
            "Coverage-disposition defect(s). The grammar is `Trace: `<category>` — <target/reason>` "
            "beside the Status: line; categories: process | narrative | non-python <path> | "
            "external <name> (see req-tap-traceability-disposition):\n  " + "\n  ".join(problems)
        )
