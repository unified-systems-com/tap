"""Implementation-claim integrity guard — `req-tap-traceability-roles`.

TAP-IMPLEMENTS: req-tap-traceability-roles@b5cafbafd29e/039a6c207f5a (enforcement) — the
    guard that fails unresolvable requirements and out-of-vocabulary roles.

A claim must name a requirement that exists and a role from the closed vocabulary
(`derivation` / `enforcement` / `surface`).

The role is what makes uniqueness workable: a requirement is frequently realized at more
than one layer — a service function *and* a guard *and* an endpoint — all legitimately.
Scoping uniqueness per `(requirement, role)` avoids manufacturing false duplicates and
keeps the known-dupe escape hatch meaningful. A free-text role would defeat that, so the
vocabulary is closed and validated, following `TAP-CRED-BIND`'s provenance model.

Hard lint, no baseline: a claim naming a nonexistent requirement or an unrecognized role
is never correct.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class ImplementsIntegrityGuard(Guard):
    slug = "implements-claim-integrity"
    map_row = "Implementation claim integrity"
    rid = "req-tap-traceability-roles"
    description = (
        "A claim naming a requirement that does not exist, or a role outside the closed "
        "vocabulary, asserts ownership of nothing while reading as a sound declaration."
    )

    def check(self) -> None:
        from tap.spec_trace import invalid_claims

        offenders = invalid_claims(REPO_ROOT)
        assert not offenders, (
            "Implementation claim(s) that do not resolve — correct the requirement id or the "
            "role, or add the requirement to a spec:\n  "
            + "\n  ".join(f"{c.where(REPO_ROOT)} -> {c.rid} — {why}" for c, why in offenders)
        )
