"""Verified-status evidence guard — `req-tap-traceability-status`.

TAP-IMPLEMENTS: req-tap-traceability-status@c380067ae093/c6faa57a297b (enforcement) — the
    gate on the vocabulary's strongest assertion: Verified needs two evidence classes.

A requirement declaring `Verified` must carry **two independent evidence classes**: an
implementation claim, and at least one acceptance criterion cited by a test.

One class is not verification. A requirement evidenced only by its own implementation has
the thing under test asserting it works — the claim, not a check on it. SQLite grades
evidence across four classes and renders a requirement green only at two or more, for
exactly this reason.

**What this guard deliberately does NOT do** is fault a requirement for lacking a claim.
Claims are opt-in and scarce by design (`req-tap-traceability-scope-1`); faulting their
absence would contradict the convention and quietly convert a targeted tool into a coverage
program. 506 requirements are declared built with no evidence at all, and that is reported
as context, not failed.

What it gates is the strongest assertion the status vocabulary offers. `Verified` was unused
across the whole corpus when this landed — zero occurrences — so the gate opens at a zero
baseline, fails closed from the first day, carries no debt, and makes the terminal state
earnable for the first time.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class VerifiedEvidenceGuard(Guard):
    slug = "verified-requires-evidence"
    map_row = "Verified-status evidence"
    rid = "req-tap-traceability-status"
    description = (
        "`Verified` is the strongest claim the status vocabulary makes; asserting it without "
        "both an implementation and a test that cites a criterion makes the lifecycle a story."
    )

    def check(self) -> None:
        from tap.spec_trace import unearned_verified

        offenders = unearned_verified(REPO_ROOT)
        assert not offenders, (
            "Requirement(s) declare `Verified` without two independent evidence classes. Add "
            "the missing evidence — an implementation claim (`scripts/implements-tag <rid>`) or "
            "a test citing one of its acceptance criteria (`@pytest.mark.spec`) — or move the "
            "status back to what the evidence supports:\n  "
            + "\n  ".join(
                f"{e.rid}: {e.classes} evidence class(es) "
                f"(implementation={'yes' if e.implemented_by else 'no'}, "
                f"verified-criteria={len(e.verified_acids)})"
                for e in offenders
            )
        )
