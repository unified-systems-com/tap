"""Typed authorization errors (req-tap-auth-policy-3).

`tap_auth.policy.authorize()` raises these on denial/error. Edge layers (API,
web) translate them to 403 or appropriate user-facing pages. They form one
taxonomy shared by service-boundary denials and (later) AuthN-edge login
denials, so attribution is consistent everywhere.

Note: the defect-class `unguarded_operation` error (the on-by-default backstop
for an operation that committed without an authorize() decision) is a *separate*
category — a code-level flaw, not an authorization denial — and lands with the
enforcement backstop. It is the first concrete `code` Flaw under
spec-tap-flaw-v0; see req-tap-auth-policy On By Default.
"""

from __future__ import annotations


class AuthzError(Exception):
    """Base class for all tap_auth authorization errors.

    Carries a stable machine-readable ``reason`` code so callers and logs can
    branch on the denial kind without string-matching the message.
    """

    reason: str = "authz_error"

    def __init__(self, message: str = "", *, reason: str | None = None) -> None:
        if reason is not None:
            self.reason = reason
        super().__init__(message or self.reason)


class MissingActor(AuthzError):
    """No named actor on the CallerContext at a point that requires one.

    The no-`User=None` contract (req-tap-auth-actor-model): a public service
    operation must be attributable to a named actor.
    """

    reason = "missing_actor"


class InactiveActor(AuthzError):
    """The actor exists but is inactive/deactivated — treated as a denial."""

    reason = "inactive_actor"


class UnknownCapability(AuthzError):
    """A capability name not present in the canonical registry was requested.

    Fails closed at runtime (req-tap-auth-capabilities-6): an unknown capability
    is a programming error, never an implicit allow.
    """

    reason = "unknown_capability"


class CapabilityDenied(AuthzError):
    """The actor is named and active but lacks the required capability."""

    reason = "capability_denied"


class ActorKindNotAllowed(AuthzError):
    """The actor's kind is not permitted for this operation."""

    reason = "actor_kind_not_allowed"


class LoginDenied(AuthzError):
    """An AuthN-edge login denial (req-tap-auth-google-oidc / external-identity).

    The user authenticated correctly with the IdP but is not permitted to log in
    to THIS deployment. Part of the same taxonomy as service-boundary denials so
    AuthN-edge and AuthZ-boundary denials share one set of stable ``reason``
    codes. Carries an optional ``user_message`` — a specific, safe hint the login
    surface shows the user (distinct from the internal log message), since a
    correctly-authenticated user turned away deserves to know *why* (wrong
    deployment vs not-allowlisted vs linking-disabled) rather than an opaque fail.
    """

    reason = "login_denied"

    def __init__(self, message: str = "", *, reason: str | None = None, user_message: str = "") -> None:
        self.user_message = user_message
        super().__init__(message, reason=reason)


class EmailNotVerified(LoginDenied):
    """The IdP did not assert a verified email (`email_verified` is not true)."""

    reason = "email_not_verified"


class DomainNotAllowed(LoginDenied):
    """The verified account's hosted domain is not in the provider's allowed_domains."""

    reason = "domain_not_allowed"


class AccountNotAllowlisted(LoginDenied):
    """The account is in an allowed domain but not in the provider's allowed_emails."""

    reason = "account_not_allowlisted"


class SubjectUnusable(LoginDenied):
    """The IdP answered without the durable subject this provider keys identity on.

    Distinct from every policy denial: nothing about the ACCOUNT was refused — the
    upstream response was unusable, so there is no stable key to write an
    ``ExternalIdentity`` against. Failing closed here is the alternative to keying
    identity on whatever mutable field happens to be present (a GitHub ``login``,
    an email), which is exactly the substitution `req-tap-auth-email-not-identity`
    forbids (req-tap-auth-github-oauth).
    """

    reason = "subject_unusable"


class PolicyUnresolvable(LoginDenied):
    """A configured access policy could not be resolved to a concrete value.

    The ``owner_only`` case (req-tap-auth-github-oauth): the provider declares
    "only the account that owns this instance may log in", and the owner is derived
    from the environment at boot rather than authored in the profile. When that
    derivation produced nothing, the policy is DECLARED but has no value to enforce
    — a presence-not-correctness shape. It denies rather than degrading to
    allow-anyone, and says so with its own code so an operator can tell a
    misconfiguration from a refusal.
    """

    reason = "policy_unresolvable"


class IdentityLinkingDisabled(LoginDenied):
    """A second provider presented the same email as an existing TAP user; v1
    disables account linking, so the login is refused (req-tap-auth-external-identity)."""

    reason = "identity_linking_disabled"


class UnguardedOperation(Exception):
    """A mutation or read reached its commit/return point with NO authorize()
    decision recorded — a code-level defect, NOT an authorization denial.

    This is the on-by-default backstop (req-tap-auth-policy On By Default): the
    system is structurally enforced so a developer who forgets to gate an
    operation gets a loud, distinct failure rather than a silent open door. It is
    deliberately separate from the AuthzError taxonomy because it is an internal
    wiring flaw (a 500-class defect), not a 403 denial — conflating them would
    hide a real bug behind a routine denial log.

    It is the first concrete Flaw under spec-tap-flaw-v0 (flaw_tags=[security]).
    Raising it is paired with `tap.flaws.report_service_layer_bypass`, which emits
    the structured Flaw — class-aware by the offending callsite: `code` when the
    bypass is in first-party TAP, `app` when it is in a plugin (a plugin that must
    route through the service layer). The distinct error type still fails the
    operation closed; the Flaw carries the blame domain + callsite for routing.

    Behavior is the same in every mode — the operation fails closed (does not
    commit / does not return data). `TAP_TEST_MODE` only raises the volume by
    surfacing the unguarded callsite for CI; production fails closed and logs.
    """

    def __init__(self, message: str, *, callsite: str = "") -> None:
        self.callsite = callsite
        super().__init__(message)
