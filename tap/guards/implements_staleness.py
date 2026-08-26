"""Implementation-claim staleness guard — `req-tap-traceability-staleness`.

TAP-IMPLEMENTS: req-tap-traceability-staleness@1f23dca53252/a8d60a460163 (enforcement) —
    the guard that fails Outdated claims until re-verified and re-stamped.

A claim carries a content hash of the requirement it claims. When the requirement's text
changes, every claim still carrying the old hash is `Outdated`: the implementation has to
be re-read against the new wording, then re-stamped.

This is the check that separates a live claim from a link that merely exists. ASPICE 4.0
states the principle plainly — *"Traceability alone, e.g., the existence of links, does not
necessarily mean that the information is consistent"* — and SQLite demonstrates the
mechanism at scale, where requirement identity *is* the hash of the requirement text and
971 marks carry zero drift. Without it, the other guards can prove a claim is unique and
well-formed and resolves, and still never prove it is **true**.

The friction is deliberately in the review — deciding whether the change invalidates the
implementation — not in the mechanics: `scripts/implements-tag --resync` re-stamps.

Hard lint, no baseline: a stale claim is always actionable, and the fix is one command.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class ImplementsStalenessGuard(Guard):
    slug = "implements-claim-staleness"
    map_row = "Implementation claim staleness"
    rid = "req-tap-traceability-staleness"
    description = (
        "A claim whose requirement was reworded underneath it still reads as sound while "
        "asserting conformance to text nobody re-checked — a link that exists but is not true."
    )

    def check(self) -> None:
        from tap.spec_trace import stale_claims

        offenders = stale_claims(REPO_ROOT)
        assert not offenders, (
            "Implementation claim(s) are Outdated — the requirement changed after the claim was "
            "made. Re-read the implementation against the new wording, then re-stamp with "
            "`scripts/implements-tag --resync <path>`:\n  "
            + "\n  ".join(
                f"{c.where(REPO_ROOT)} -> {c.rid} claims @{c.recorded_hash}, requirement is now @{expected}"
                for c, expected in offenders
            )
        )
