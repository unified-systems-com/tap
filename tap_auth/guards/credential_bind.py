"""Credential-bind provenance guard — every identity bind names why it is safe.

`WebAuthnCredential` and `WebAuthnUserHandle` writes are the identity-binding surface of
the auth system — the most privileged writes in the codebase, and off the Entity spine, so
the direct-write lint cannot see them and they had no Validation Map row (an invisible gap,
`req-dev-validation-map`). This guard closes that: it fails the build unless every
class-level write to either model carries an inline `# TAP-CRED-BIND: <provenance>` tag with
a provenance valid for that model.

The invariant is **containment + local verifiability**, the pattern the prior-art survey
endorsed for "Y is only safe if X happened upstream" (`spec-dev-validation.md` Prior Art):
we cannot statically prove proof-of-possession (interprocedural), so we keep the set of
binding sites small, closed, and each locally auditable to its named provenance —
`pop-ceremony` (a `verify_registration_response` in the same function) or `dev-profile-gate`
(an `assert_dev_import_allowed` in the same function) for a credential; `pre-registration-handle`
or `dev-profile-gate` for a handle. A public-key credential can therefore never be bound under
a weaker handle provenance. This is the credential-surface twin of the dev-passkey import
guard, and operationalizes finding #8: state the positive safety reason, not an excuse.

DIY AST + tokenize, stdlib-only, pre-boot. Hard lint: no baseline — every current bind is
legitimately taggable, and there is no legitimate untagged offender to grandfather.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots
from tap_auth.credential_bind_coverage import _PROVENANCE_BY_MODEL, _TAG, scan_credential_binds


class CredentialBindProvenanceGuard(Guard):
    slug = "credential-bind-provenance"
    map_row = "Credential-bind provenance"
    rid = "req-tap-auth-credential-bind-provenance"
    description = (
        "WebAuthnCredential/WebAuthnUserHandle writes are the identity-binding surface — the most "
        "privileged writes in the codebase, off the Entity spine so the direct-write lint ignores "
        "them. This fails the build unless every such write carries an inline `# TAP-CRED-BIND: "
        "<provenance>` tag valid for that model, so a public-key credential can only be bound via a "
        "proof-of-possession ceremony or the dev-profile-gated import, never a weaker provenance — "
        "and a new untagged bind (the regression shape) fails at authoring time."
    )

    def check(self) -> None:
        result = scan_credential_binds(first_party_source_roots(REPO_ROOT))

        def _rel(path: object, lineno: int) -> str:
            return f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}"  # type: ignore[attr-defined]

        problems: list[str] = []
        for site in result.untagged:
            problems.append(
                f"{_rel(site.path, site.lineno)}: {site.model}.{site.op} in `{site.qualname}` has no "
                f"`# {_TAG}: <provenance>` tag — name why this identity bind is safe."
            )
        for site in result.invalid_provenance:
            allowed = ", ".join(sorted(_PROVENANCE_BY_MODEL[site.model]))
            got = site.provenance or "<malformed>"
            problems.append(
                f"{_rel(site.path, site.lineno)}: {site.model}.{site.op} tagged `{got}`, not valid for "
                f"{site.model} (allowed: {allowed})."
            )
        for tag in result.orphan_tags:
            problems.append(f"{_rel(tag.path, tag.lineno)}: `# {_TAG}` tag on no identity-bind write (stale).")

        assert not problems, (
            "Credential-bind provenance violation(s): an identity bind lacks a valid, model-appropriate "
            "`# TAP-CRED-BIND` provenance tag (spec-tap-auth-v0.md req-tap-auth-credential-bind-provenance). "
            "A public-key credential may be bound only by `pop-ceremony` (a verified WebAuthn ceremony) or "
            "`dev-profile-gate` (the dev_local-gated replay).\n  - " + "\n  - ".join(problems)
        )
