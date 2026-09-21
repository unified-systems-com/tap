"""Provider interface, config model, and self-test result types (req-tap-auth-providers).

A provider implementation is a small object exposing four operations:

    validate_config(config)            -> list[SelfTestResult]   (offline shape checks)
    resolve_secrets(config)            -> dict[str, str]         (secret material, in memory)
    self_test(config, secrets, live=)  -> list[SelfTestResult]   (offline + optional live)
    build_allauth_settings(config, secrets) -> dict              (one allauth APPS entry)

plus the per-login seams the social adapter drives (``evaluate_access``,
``profile_snapshot``) and two facts about where the provider rides in allauth
(``allauth_provider``, ``callback_url``).

The abstraction is **"produce one allauth APPS entry"**, not "be OIDC". That
distinction was latent while ``google_oidc`` was the only implementation and the
wiring could hardcode the ``openid_connect`` engine; ``github_oauth`` is plain
OAuth 2.0 (GitHub publishes no OpenID discovery document for user login), rides
allauth's ``github`` provider, and made the seam real (req-tap-auth-github-oauth).

Self-tests are a first-class investment (req-tap-auth-providers): IdPs break the
same way collector upstreams do (credential rotation, discovery-document drift,
tenant/domain changes), and a standard, code-free probe surface lets an operator
(or the future healer) ask "what is wrong with auth right now" the same way the
CollectorBase self-tests do. Results carry a status, a human message, and a docs
link; checks are split into offline (shape/secret-presence/local derivations)
and live (network/IdP reachability) phases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider operation failed in a way that is not a self-test result —
    e.g. a secret cannot be resolved at all, or config is structurally unusable
    for building settings. Self-tests REPORT problems; this is raised when an
    operation cannot proceed."""


class SelfTestStatus(StrEnum):
    """Outcome of a single self-test check (req-tap-auth-providers)."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


class SelfTestPhase(StrEnum):
    """Which phase a check belongs to. OFFLINE = shape/secret/local derivation
    (no network); LIVE = network/IdP reachability (req-tap-auth-providers-5)."""

    OFFLINE = "offline"
    LIVE = "live"


@dataclass(frozen=True)
class SelfTestResult:
    """One self-test check outcome."""

    check: str
    status: SelfTestStatus
    phase: SelfTestPhase
    message: str
    docs_url: str | None = None

    @property
    def ok(self) -> bool:
        """True when this check does not block boot (pass/warn/skip). FAIL is
        the only blocking status (req-tap-auth-providers: boot fails on any
        provider `fail`; `warn` continues with clear logs)."""
        return self.status is not SelfTestStatus.FAIL


@dataclass(frozen=True)
class AccessDecision:
    """The outcome of a provider's per-login access evaluation (the security
    core — req-tap-auth-google-oidc). Pure data: the provider decides, the
    adapter enforces (raises / logs / provisions). Deliberately claim-only so it
    is trivially unit-testable with synthetic claims — no network, no DB.

    ``reason`` is a stable login-denial reason code (matches the
    ``tap_auth.errors`` LoginDenied codes) when ``allowed`` is False.
    ``log_detail`` is internal; ``user_message`` is the safe hint shown to the
    turned-away user.

    Field ownership, stated because it was implicit while one provider existed:

    - ``verified_email`` and ``matched_rule`` are **provider-neutral**. A provider
      sets ``verified_email`` only for an email the IdP ITSELF asserts as verified
      — never a self-asserted profile field. Downstream code treats a non-empty
      value as trustworthy (it becomes ``User.email``, which keys the
      ``TAP_AUTH_INITIAL_GRANTS`` role map), so filling it from an unverified
      claim would be a privilege-escalation path, not a cosmetic slip.
    - ``matched_rule`` names the policy clause that decided — ``allowed_domains``,
      ``owner_only`` — for the structured security log, so the
      log says WHICH rule fired without knowing the provider's vocabulary.
    - ``hd`` and ``matched_domain`` are **google_oidc vocabulary** (the hosted-domain
      claim). Other providers leave them None; a consumer must not read them as
      "the thing that matched" — that is ``matched_rule``.
    """

    allowed: bool
    reason: str | None = None
    user_message: str = ""
    log_detail: str = ""
    hd: str | None = None
    matched_domain: str | None = None
    verified_email: str | None = None
    matched_rule: str | None = None


#: Reserved claims key under which the social adapter injects the email addresses
#: the IdP itself asserts as verified (lowercased, primary first).
#:
#: An OIDC provider carries verification INSIDE the token (``email_verified``), so
#: google_oidc reads it straight off the claims. A plain-OAuth2 provider may not:
#: GitHub's ``/user`` ``email`` field is a self-asserted profile field, and the
#: verified set arrives from a separate ``/user/emails`` call that allauth makes
#: and then strips out of ``extra_data`` (it becomes ``SocialLogin.email_addresses``
#: instead). Rather than have each provider re-fetch what allauth already fetched,
#: the adapter normalizes that list into the claims under this one namespaced key.
#: The ``tap:`` prefix is a NAMESPACE, not a defence: a JSON object key may be any
#: string, so a hostile upstream CAN put this key in its own payload. What makes
#: the channel safe is that the adapter writes it UNCONDITIONALLY on every login
#: (empty list when nothing is verified), overwriting anything `extra_data`
#: carried. Do not make that write conditional (tap#701).
VERIFIED_EMAILS_CLAIM = "tap:verified_emails"


@dataclass(frozen=True)
class ProfileSnapshot:
    """The display-only profile a provider reads out of its own claim vocabulary.

    Profile extraction used to live in the social adapter as literal Google claim
    names (``picture``, ``given_name``, ``family_name``, ``hd``). That is correct
    for exactly one provider: GitHub answers with ``avatar_url`` and a single
    ``name``, so a GitHub login through the un-generalised adapter produced a user
    with no avatar and no name — silently, because every field is optional.

    Everything here is cosmetic. Nothing on this snapshot may be used for an access
    decision or as an identity key; the decision is ``evaluate_access`` and the
    identity key is ``(provider_id, subject)``.
    """

    display_name: str = ""
    first_name: str = ""
    last_name: str = ""
    avatar_url: str = ""
    hosted_domain: str = ""


@dataclass(frozen=True)
class ProviderConfig:
    """A single provider entry from the boot auth config (req-tap-auth-providers).

    Common fields are explicit; provider-type-specific settings (e.g. a
    google_oidc provider's ``allowed_domains``) live in ``config`` and are
    interpreted by the concrete provider. ``secret`` is the *key* of the
    ``auth``-scoped ``*.secret.json`` holding the client credentials — a
    reference, never the secret value (req-tap-auth-providers-3). It defaults to
    the provider ``id`` (the convention: secret basename == provider id).
    """

    id: str
    type: str
    display_name: str
    secret: str = ""
    critical_for_boot: bool = True
    auto_provision: bool = True
    config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def secret_key(self) -> str:
        """The secret key to resolve (defaults to the provider id)."""
        return self.secret or self.id

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProviderConfig:
        """Build a ProviderConfig from a boot-config dict. Raises ProviderError
        on a missing required field (id/type/display_name) so a malformed static
        config fails loudly rather than silently producing a half-built provider."""
        missing = [k for k in ("id", "type", "display_name") if not raw.get(k)]
        if missing:
            raise ProviderError(f"provider config missing required field(s): {', '.join(missing)}")
        known = {"id", "type", "display_name", "secret", "critical_for_boot", "auto_provision"}
        return cls(
            id=str(raw["id"]),
            type=str(raw["type"]),
            display_name=str(raw["display_name"]),
            secret=str(raw.get("secret", "")),
            critical_for_boot=bool(raw.get("critical_for_boot", True)),
            auto_provision=bool(raw.get("auto_provision", True)),
            config={k: v for k, v in raw.items() if k not in known},
        )


class Provider(Protocol):
    """The common provider interface (req-tap-auth-providers-4). A concrete
    provider is a stateless object; all state arrives via ``config``/``secrets``."""

    #: The TAP provider-type name, as written in a boot profile's ``type`` field.
    type: str

    #: The allauth provider the APPS entry is filed under — the outer key of
    #: ``SOCIALACCOUNT_PROVIDERS`` (``openid_connect`` for google_oidc, ``github``
    #: for github_oauth). Declared here because the wiring used to hardcode
    #: ``openid_connect``: a second provider type filed under that key would have
    #: been handed to allauth's OIDC engine and failed on a missing ``server_url``.
    allauth_provider: str

    def callback_url(self, config: ProviderConfig) -> str | None:
        """The redirect URI this provider registers with its IdP, derived from
        ``TAP_BASE_URL`` (req-tap-auth-providers-7). None when ``TAP_BASE_URL`` is
        unset — ``validate_config`` turns that into a FAIL. The SHAPE is
        provider-specific: allauth routes openid_connect apps per ``provider_id``
        and OAuth2 apps at one fixed path per provider, so only the provider can
        state its own callback."""
        ...

    def validate_config(self, config: ProviderConfig) -> list[SelfTestResult]:
        """Offline structural validation of a provider config (no network, no
        secrets). Returns one result per check."""
        ...

    def resolve_secrets(self, config: ProviderConfig) -> dict[str, str]:
        """Resolve the provider's secret material into memory (never persisted).
        Raises ProviderError if the secret cannot be resolved/validated."""
        ...

    def evaluate_access(self, config: ProviderConfig, claims: Mapping[str, Any]) -> AccessDecision:
        """Decide whether the IdP-asserted ``claims`` are permitted to log in to
        this deployment under ``config`` (verified email, domain, allowlist). Pure
        and side-effect-free — the adapter enforces the decision."""
        ...

    def profile_snapshot(self, config: ProviderConfig, claims: Mapping[str, Any]) -> ProfileSnapshot:
        """Read the display-only profile out of this provider's claim vocabulary.
        Pure and cosmetic — never an input to an access decision (see
        ``ProfileSnapshot``)."""
        ...

    def self_test(self, config: ProviderConfig, secrets: Mapping[str, str], *, live: bool) -> list[SelfTestResult]:
        """Run offline checks always; when ``live`` is True also run network/IdP
        reachability checks. Never raises for an expected failure — returns a
        FAIL result instead."""
        ...

    def build_allauth_settings(self, config: ProviderConfig, secrets: Mapping[str, str]) -> dict[str, Any]:
        """Build the allauth provider ``APPS`` entry for this provider."""
        ...
