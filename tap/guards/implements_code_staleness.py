"""Implementation-claim code staleness guard — `req-tap-traceability-code-staleness`.

TAP-IMPLEMENTS: req-tap-traceability-code-staleness@edce7b8f372e/4685f95c180c (enforcement) —
    the guard that fails Drifted and Unstamped claims until re-verified and re-stamped.

The inverse direction of `implements_staleness`: a claim also carries a fingerprint of the
**code it sits on** — `semantic_hash` over the claimed scope's positions-stripped AST, all
docstrings excluded. When the scope is semantically edited, the claim reports `Drifted`:
the code has to be re-verified against the requirement, then re-stamped. This is Doorstop's
link-fingerprint model applied to the code end of the link; without it, rewriting a claimed
function so it no longer does what the requirement says leaves every spec-side check green.

Formatting, comments, docstring edits and pure moves never churn the digest (the
callsite-identity recipe); any semantic edit does. A claim still carrying the mint
placeholder (`------------`) is `Unstamped` and fails here too — minting emits the
placeholder because the code hash can only be computed from the claim's actual placement,
and this guard is what makes forgetting the `--resync` impossible.

The friction is deliberately in the review — deciding whether the code change broke the
requirement — not in the mechanics: `scripts/implements-tag --resync` re-stamps.

Hard lint, no baseline: a drifted claim is always actionable, and the fix is one command.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class ImplementsCodeStalenessGuard(Guard):
    slug = "implements-claim-code-staleness"
    map_row = "Implementation claim code staleness"
    rid = "req-tap-traceability-code-staleness"
    description = (
        "A claimed function rewritten out from under its claim still reads as the verified "
        "implementation — the spec did not change, so every spec-side check stays green while "
        "the code no longer does what the requirement says."
    )

    def check(self) -> None:
        from tap.spec_trace import drifted_claims

        offenders = drifted_claims(REPO_ROOT)
        assert not offenders, (
            "Implementation claim(s) whose code moved under them. Re-verify each scope against "
            "its requirement, then re-stamp with `scripts/implements-tag --resync <path>`:\n  "
            + "\n  ".join(
                (
                    f"{c.where(REPO_ROOT)} -> {c.rid} is unstamped (minted, never resynced); scope is @{c.code_hash}"
                    if c.unstamped
                    else f"{c.where(REPO_ROOT)} -> {c.rid} stamped code @{c.recorded_code_hash}, "
                    f"scope is now @{c.code_hash}"
                )
                for c in offenders
            )
        )
