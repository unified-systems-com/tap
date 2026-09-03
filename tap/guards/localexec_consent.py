"""Local-execution consent-hash parity guard — `req-tap-known-dupes`.

The consent digest (`tap_localexec_hash`) is deliberately written twice:

* ``.githooks/_consent_check.sh`` — sourced by the hooks, which only run once armed.
* ``scripts/hooks-install`` — the installer, which ``spawn-session.sh`` invokes
  AUTOMATICALLY.

The installer cannot source the hook helper, and that is the whole point of the
duplication rather than an accident of it: sourcing the surface the user is about to
be asked to approve would execute that surface *before* consent, so top-level commands
placed in `_consent_check.sh` would run during an ordinary spawn even when the user
declines. "Nothing runs until you agree" is the claim the installer makes; sourcing the
thing under review would make it a lie.

The cost of that boundary is two copies that can drift apart silently — and a drift is
not cosmetic. If the installer records a digest over a different file set than the hooks
verify, consent is recorded against one thing and checked against another, and the whole
mechanism reads as working while protecting nothing. This guard compares the two function
bodies with comments and whitespace normalised away, so an edit to one that is not
mirrored in the other fails the build loudly.

Raises explicitly rather than asserting (`req-dev-validation-*`, tracked in #179, and
the non-test Bandit B101 policy recorded in `.codacy.yaml`): a bare ``assert`` is removed
under ``python -O``, which would turn this guard into a function that inspects the tree
and returns successfully — it would not error, it would *pass*. A fail-open in a guard
whose subject is a fail-open would be a poor joke.

Spec: specs/spec-dev-local-execution.md (req-dev-localexec-reconsent) and
specs/spec-tap-known-dupes.md (the `localexec-consent-hash` group).
"""

from __future__ import annotations

import re

from tap.guards.base import REPO_ROOT, Guard

_SITES = (
    ".githooks/_consent_check.sh",
    "scripts/hooks-install",
)

_FUNC = re.compile(r"^tap_localexec_hash\s*\(\s*\)\s*\{(?P<body>.*?)^\}", re.MULTILINE | re.DOTALL)


def _normalised_body(text: str) -> str | None:
    """The function body with comments, blank lines and indentation removed.

    Returns None when the function is absent, which the caller reports as its own
    failure — a missing copy is a worse defect than a drifted one.
    """
    match = _FUNC.search(text)
    if match is None:
        return None
    lines = []
    for raw in match.group("body").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(re.sub(r"\s+", " ", stripped))
    return "\n".join(lines)


class LocalExecConsentHashParityGuard(Guard):
    slug = "localexec-consent-hash-parity"
    map_row = "Local-execution consent hash (known-dupe parity)"
    rid = "req-tap-known-dupes"
    description = (
        "The consent digest is written twice because the installer must not source the "
        "hook surface it is asking the user to approve. Silent drift between the two "
        "would record consent over one file set and verify another, leaving the "
        "mechanism looking correct while protecting nothing."
    )

    def check(self) -> None:
        bodies: dict[str, str | None] = {}
        for site in _SITES:
            path = REPO_ROOT / site
            if not path.exists():
                raise AssertionError(
                    f"{site} is missing — it is one of two required copies of "
                    f"tap_localexec_hash (TAP-KNOWN-DUPE(localexec-consent-hash))."
                )
            bodies[site] = _normalised_body(path.read_text(encoding="utf-8"))

        missing = [site for site, body in bodies.items() if body is None]
        if missing:
            raise AssertionError(
                "tap_localexec_hash is not defined in: "
                + ", ".join(missing)
                + ". Both copies must exist — the installer cannot source the hook "
                "helper without executing the un-approved surface "
                "(req-dev-localexec-reconsent)."
            )

        if len(set(bodies.values())) != 1:
            raise AssertionError(
                "The two copies of tap_localexec_hash have DRIFTED "
                "(TAP-KNOWN-DUPE(localexec-consent-hash)).\n"
                f"  {_SITES[0]}\n  {_SITES[1]}\n"
                "Consent would be recorded over one file set and verified against "
                "another, so the check would pass while covering the wrong thing. "
                "Mirror the edit into both; they cannot share one function because the "
                "installer runs automatically from spawn-session.sh and must not source "
                "the surface it is asking the user to approve."
            )
