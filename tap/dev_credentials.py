"""Recognising the development stack's own credentials, without carrying them.

The deployment gates have to answer one question — *is the value this instance is
configured with the value the development compose stack ships?* — and answering it never
requires the value itself. So the application stores a **SHA-256 digest** and compares
against that.

**Why a digest rather than the value.** Two reasons, and the second is the one that keeps
it that way:

1.  The repository stops containing the credential at all. A constant holding a known
    development password is still a credential-shaped literal in a public repository: it
    is what every secrets scanner is built to find, and — correctly — cannot be
    distinguished by a scanner from one that matters. `# noqa: S105` silenced ruff and did
    nothing to Codacy's secrets engine, which is a different tool: a comment that reads as
    a suppression while the required check stays red is the presence-is-not-correctness
    shape aimed at ourselves.
2.  A digest cannot be *used*. A literal can be copied out of settings and into a
    deployment; a digest can only ever be compared against.

**Do not "simplify" this back to a literal.** Doing so reopens both the scanner finding
and the exposure, and the comparison would look identical at the call site — which is
exactly why the reason is recorded here rather than in a commit message nobody re-reads.

**SHA-256 specifically**, not a cheaper hash. This runs inside a FIPS-mode artifact where
every cryptographic provider and algorithm must be an approved one (`req-fips-crypto-bom`
fails closed on an unclassified provider). "It is only a marker, MD5 is fine" is precisely
the reasoning that gate exists to refuse, and SHA-256 costs nothing here — it hashes a
handful of bytes, once, at boot.

The comparison is constant-time. The values involved are published, so no timing oracle is
at stake today; it is the right habit on a path that compares secret-valued configuration,
and it says so to the next reader who copies this function somewhere it matters.

Stdlib only, no Django import: `tap/settings.py` holds the digests and this decides what
they mean, so both `tap_boot.posture` and `tap_grid.checks` ask one function rather than
each growing its own comparison (derive a fact once — the shared mechanic lives DOWN in
`tap/`, never sideways between apps).

Spec: `specs/spec-tap-serving.md` — `req-tap-serving-fail-closed`.
"""

from __future__ import annotations

import hashlib
import hmac


def matches_dev_stack_digest(value: str | None, digest: str) -> bool:
    """Whether `value` is the development-stack value `digest` was taken from.

    Args:
        value: The configured credential, or None/empty when nothing is configured.
        digest: Lowercase hex SHA-256 of the development stack's value.

    Returns:
        True when the configured value IS the development stack's. An absent or empty
        value returns False rather than raising: "nothing is configured" is a different
        finding, made where the setting is read (`tap/settings.py` refuses to finish
        importing without one), and reporting it here as "the dev value is in use" would
        name the wrong problem.
    """
    if not value:
        return False
    return hmac.compare_digest(hashlib.sha256(value.encode("utf-8")).hexdigest(), digest)
