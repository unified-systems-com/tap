"""Google Workspace OIDC provider (req-tap-auth-google-oidc).

The first concrete external provider type. Backed by allauth's ``openid_connect``
provider (each TAP provider is one OIDC app addressed by its stable
``provider_id``). The security-critical login decisions — verified email,
``hd``-claim domain enforcement, ``allowed_emails`` pin, linking-disabled — live
in the TAP social adapter (req-tap-auth-external-identity), NOT here: this module
owns *configuration*, *secret resolution*, *self-tests*, and *allauth settings*.

Config fields (under the provider entry's type-specific ``config``):
    allowed_domains       list[str]  REQUIRED — Workspace domains permitted to log
                                     in (enforced via the returned ``hd`` claim).
                                     No "any Google account" escape hatch.
    allowed_emails        list[str]  OPTIONAL — narrow to specific verified emails
                                     within allowed_domains (e.g. a single operator).
    email_domain_fallback bool       OFF by default — match the verified-email
                                     domain when no ``hd`` is returned (consumer
                                     accounts). Customer/Workspace providers leave
                                     this off and require a returned ``hd``.
    server_url            str        OIDC issuer; defaults to Google.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests
from django.conf import settings

from tap_auth.errors import DomainNotAllowed
from tap_auth.providers.base import (
    AccessDecision,
    ProviderConfig,
    ProviderError,
    SelfTestPhase,
    SelfTestResult,
    SelfTestStatus,
)
from tap_auth.providers.secrets import resolve_oidc_client_secret, secret_exists

PROVIDER_TYPE = "google_oidc"
DEFAULT_SERVER_URL = "https://accounts.google.com"
DISCOVERY_PATH = "/.well-known/openid-configuration"
DOCS_URL = "spec-tap-auth-v0 § req-tap-auth-google-oidc"

_REQUIRED_DISCOVERY_KEYS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")


def _result(check: str, status: SelfTestStatus, phase: SelfTestPhase, message: str) -> SelfTestResult:
    return SelfTestResult(check=check, status=status, phase=phase, message=message, docs_url=DOCS_URL)


def _truthy(value: Any) -> bool:
    """OIDC claims may carry ``email_verified`` as a JSON bool or a string
    ('true'/'false'); normalize both. Anything else is treated as not-verified."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


class GoogleOidcProvider:
    """google_oidc provider implementation (see module docstring)."""

    type = PROVIDER_TYPE

    # -- config helpers ----------------------------------------------------

    def _server_url(self, config: ProviderConfig) -> str:
        return str(config.config.get("server_url") or DEFAULT_SERVER_URL).rstrip("/")

    def _allowed_domains(self, config: ProviderConfig) -> Sequence[str]:
        raw = config.config.get("allowed_domains") or []
        return [str(d).strip().lower() for d in raw if str(d).strip()]

    def callback_url(self, config: ProviderConfig) -> str | None:
        """Derive the OIDC callback URL from TAP_BASE_URL (req-tap-auth-providers-7).
        Returns None if TAP_BASE_URL is unset (a FAIL is raised at validate time)."""
        base = getattr(settings, "TAP_BASE_URL", "") or ""
        if not base:
            return None
        return f"{base.rstrip('/')}/auth/oidc/{config.id}/login/callback/"

    # -- interface ---------------------------------------------------------

    def validate_config(self, config: ProviderConfig) -> list[SelfTestResult]:
        results: list[SelfTestResult] = []
        off = SelfTestPhase.OFFLINE

        if config.type != self.type:
            results.append(
                _result("type", SelfTestStatus.FAIL, off, f"expected type '{self.type}', got '{config.type}'")
            )
            return results

        domains = self._allowed_domains(config)
        if not domains:
            results.append(
                _result(
                    "allowed_domains",
                    SelfTestStatus.FAIL,
                    off,
                    "google_oidc requires a non-empty allowed_domains — there is no "
                    "'any Google account' login. List the Workspace domain(s) explicitly.",
                )
            )
        else:
            results.append(
                _result("allowed_domains", SelfTestStatus.PASS, off, f"{len(domains)} domain(s): {', '.join(domains)}")
            )

        emails = config.config.get("allowed_emails") or []
        if emails:
            bad = [e for e in emails if "@" not in str(e)]
            if bad:
                results.append(_result("allowed_emails", SelfTestStatus.WARN, off, f"entries without '@': {bad}"))
            else:
                results.append(
                    _result(
                        "allowed_emails",
                        SelfTestStatus.PASS,
                        off,
                        f"pinned to {len(emails)} account(s) within allowed_domains",
                    )
                )

        if not isinstance(config.config.get("email_domain_fallback", False), bool):
            results.append(_result("email_domain_fallback", SelfTestStatus.FAIL, off, "must be a boolean"))

        if self.callback_url(config) is None:
            results.append(
                _result(
                    "tap_base_url",
                    SelfTestStatus.FAIL,
                    off,
                    "TAP_BASE_URL is required to derive the OIDC callback URL for an external provider.",
                )
            )
        else:
            results.append(_result("tap_base_url", SelfTestStatus.PASS, off, f"callback: {self.callback_url(config)}"))

        return results

    def resolve_secrets(self, config: ProviderConfig) -> dict[str, str]:
        return resolve_oidc_client_secret(config.secret_key)

    def evaluate_access(self, config: ProviderConfig, claims: Mapping[str, Any]) -> AccessDecision:
        """The security core (req-tap-auth-google-oidc). Pure, claim-only.

        Order of checks (each fails closed with a distinct reason code):
          1. email present + ``email_verified`` true — a verified email is the
             precondition for everything else.
          2. domain: enforced via the RETURNED ``hd`` claim (the trustworthy
             hosted-domain assertion). Email-domain fallback applies ONLY when the
             provider opted in (off by default for Workspace/customer providers),
             and even then ``email_verified`` is still required. A login with no
             ``hd`` and no fallback is denied — no silent email-domain matching.
          3. allowed_emails: when configured, the verified email must be on the
             list. Narrows WITHIN allowed_domains, never widens; enforced on every
             login (email is mutable, so this is not a one-time provisioning gate).
        """
        email = str(claims.get("email") or "").strip().lower()
        verified = _truthy(claims.get("email_verified"))
        hd = claims.get("hd")
        hd_norm = str(hd).strip().lower() if hd else None

        if not email or not verified:
            return AccessDecision(
                allowed=False,
                reason="email_not_verified",
                user_message="Your identity provider did not confirm a verified email address.",
                log_detail=f"email_verified={claims.get('email_verified')!r} email_present={bool(email)}",
                hd=hd_norm,
            )

        allowed_domains = set(self._allowed_domains(config))
        fallback = bool(config.config.get("email_domain_fallback", False))

        if hd_norm:
            matched = hd_norm
        elif fallback:
            matched = email.split("@")[-1]
        else:
            return AccessDecision(
                allowed=False,
                reason=DomainNotAllowed.reason,
                user_message="Your account's domain is not permitted on this deployment.",
                log_detail="no hd claim returned and email-domain fallback is disabled",
                verified_email=email,
            )

        if matched not in allowed_domains:
            return AccessDecision(
                allowed=False,
                reason=DomainNotAllowed.reason,
                user_message="Your account's domain is not permitted on this deployment.",
                log_detail=f"domain {matched!r} not in allowed_domains {sorted(allowed_domains)}",
                hd=hd_norm,
                matched_domain=matched,
                verified_email=email,
            )

        allowed_emails = {str(e).strip().lower() for e in (config.config.get("allowed_emails") or [])}
        if allowed_emails and email not in allowed_emails:
            return AccessDecision(
                allowed=False,
                reason="account_not_allowlisted",
                user_message=(
                    "You authenticated correctly and your domain is allowed, but your "
                    "account is not on this deployment's allowlist. An administrator must add you."
                ),
                log_detail=f"email not in allowed_emails ({len(allowed_emails)} entr(ies))",
                hd=hd_norm,
                matched_domain=matched,
                verified_email=email,
            )

        return AccessDecision(
            allowed=True,
            hd=hd_norm,
            matched_domain=matched,
            verified_email=email,
        )

    def self_test(self, config: ProviderConfig, secrets: Mapping[str, str], *, live: bool) -> list[SelfTestResult]:
        results = self.validate_config(config)
        off = SelfTestPhase.OFFLINE

        # Secret presence + shape (offline).
        if not secret_exists(config.secret_key):
            results.append(
                _result(
                    "secret",
                    SelfTestStatus.FAIL,
                    off,
                    f"no auth:{config.secret_key} secret file found under TAP_SECRETS_ROOT",
                )
            )
        elif not secrets.get("client_id") or not secrets.get("client_secret"):
            results.append(
                _result("secret", SelfTestStatus.FAIL, off, "resolved secret is missing client_id/client_secret")
            )
        else:
            results.append(_result("secret", SelfTestStatus.PASS, off, f"client_id …{secrets['client_id'][-14:]}"))

        # Live discovery-document check.
        results.append(self._discovery_check(config, live=live))
        return results

    def _discovery_check(self, config: ProviderConfig, *, live: bool) -> SelfTestResult:
        live_phase = SelfTestPhase.LIVE
        url = self._server_url(config) + DISCOVERY_PATH
        if not live:
            return _result("discovery", SelfTestStatus.SKIP, live_phase, f"live check skipped ({url})")
        try:
            resp = requests.get(url, timeout=10)
        except requests.RequestException as exc:
            return _result("discovery", SelfTestStatus.FAIL, live_phase, f"could not reach {url}: {exc}")
        if resp.status_code != 200:
            return _result("discovery", SelfTestStatus.FAIL, live_phase, f"{url} returned HTTP {resp.status_code}")
        try:
            doc = resp.json()
        except ValueError:
            return _result("discovery", SelfTestStatus.FAIL, live_phase, f"{url} did not return JSON")
        missing = [k for k in _REQUIRED_DISCOVERY_KEYS if k not in doc]
        if missing:
            return _result("discovery", SelfTestStatus.FAIL, live_phase, f"discovery doc missing keys: {missing}")
        return _result("discovery", SelfTestStatus.PASS, live_phase, f"issuer {doc.get('issuer')} reachable")

    def build_allauth_settings(self, config: ProviderConfig, secrets: Mapping[str, str]) -> dict[str, Any]:
        if not secrets.get("client_id") or not secrets.get("client_secret"):
            raise ProviderError(f"cannot build allauth settings for {config.id}: secret not resolved")
        return {
            "provider_id": config.id,
            "name": config.display_name,
            "client_id": secrets["client_id"],
            "secret": secrets["client_secret"],
            "settings": {"server_url": self._server_url(config)},
        }
