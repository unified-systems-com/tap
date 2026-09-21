"""Implementation-claim shape guard — `req-tap-traceability-claim`.

TAP-IMPLEMENTS: req-tap-traceability-claim@5b3a517c247e/d0ab55728c49 (enforcement) — the guard
    that fails malformed and near-miss claims closed.

A line that attempts the claim grammar and misses is a **failure**, not a line to skip.

This is the lesson clippy's safety-comment lint learned the hard way: `// SAFTEY:` reports
"no safety comment here" and the typo survives review, because a misspelled tag fails
*open*. Roughly 60% of real-world failures in tag conventions are shape, not staleness. A
convention whose typos silently do nothing is a convention that silently does nothing.

Hard lint, no baseline: the tree carried zero claims when this landed, so there is no debt
to grandfather and no reason to permit a malformed one.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class ImplementsShapeGuard(Guard):
    slug = "implements-claim-shape"
    map_row = "Implementation claim shape"
    rid = "req-tap-traceability-claim"
    description = (
        "A malformed implementation claim fails open — it reads as 'no claim here', so the "
        "requirement silently loses its declared owner and nobody is told."
    )

    def check(self) -> None:
        from tap.spec_trace import malformed_claims

        offenders = malformed_claims(REPO_ROOT)
        assert not offenders, (
            "Malformed implementation claim(s). The grammar is "
            "`TAP-" + "IMPLEMENTS: <rid>@<hash> (<role>) — <reason>`; mint the line with "
            "`scripts/implements-tag <rid> [role]` rather than hand-writing it:\n  "
            + "\n  ".join(f"{m.where(REPO_ROOT)}  |  {m.text}" for m in offenders)
        )
