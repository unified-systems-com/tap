"""GitHub OAuth 2.0 provider (req-tap-auth-github-oauth).

The second concrete provider type, and the one that made the provider registry a
registry rather than a dict with one entry.

**GitHub is not an OIDC provider for user login.**
``https://github.com/.well-known/openid-configuration`` returns 404; the issuer
that does answer (``token.actions.githubusercontent.com``) is Actions *workload*
identity, not human sign-in. GitHub user auth is plain OAuth 2.0, so this provider
rides allauth's ``github`` provider rather than ``openid_connect``. That is the
whole reason the provider abstraction is "produce one allauth APPS entry" and not
"be OIDC" — see ``tap_auth/providers/base.py``.

Identity: the GitHub **numeric user id**, never the login
---------------------------------------------------------
``ExternalIdentity`` keys on ``(provider_id, subject)``. A GitHub *login* is
renameable and, once released, claimable by someone else — so keying on it would
make a rename look like a new person and a recycled handle inherit a stranger's
account and grants. The numeric id is immutable and never reissued, and allauth's
``GitHubProvider.extract_uid`` already returns ``str(data["id"])``, so the durable
subject lands on the spine without TAP doing anything clever. This module's job is
to make sure the *policy* does not quietly reintroduce the login as a gate either.
It does not: **no clause here authorizes on a login.** An earlier revision carried an
``allowed_logins`` clause and an ``owner_only`` that accepted an owner-login match;
both admitted whoever currently holds a handle rather than a durable account, so a
renamed-and-re-registered login was a way in. They are gone
(unified-systems-com/tap#687). A login is display and log vocabulary only — see
``profile_snapshot``.

Verified email: re-expressed, not dropped
------------------------------------------
google_oidc requires a provider-asserted verified email as the precondition for
access, because its gate IS the domain of that email. GitHub's gate is not derived
from email at all, so the requirement moves rather than disappearing:

  - Access does **not** require a verified email. Refusing a login whose GitHub
    account has no verified address would deny an explicitly allowlisted numeric id
    for a reason unrelated to the policy that admitted it.
  - Trusting an email DOES require verification. GitHub's ``/user`` ``email`` field
    is **self-asserted** — the account holder types it in — so it is never promoted
    to ``AccessDecision.verified_email``. Only addresses GitHub itself marks
    verified (from ``/user/emails``, which allauth fetches when
    ``SOCIALACCOUNT_QUERY_EMAIL`` is on and hands over as
    ``SocialLogin.email_addresses``) are eligible. This is load-bearing, not
    fastidious: ``AccessDecision.verified_email`` becomes ``User.email``, and
    ``User.email`` keys the ``TAP_AUTH_INITIAL_GRANTS`` role map — so an
    attacker-typed profile email matching an initial-admin entry would be an
    unauthenticated grant of ``tap_admin``.

No extra API call is made here: allauth already performs the ``/user/emails``
fetch, and re-fetching it would be a second derivation of the same fact.

Config fields (under the provider entry's type-specific ``config``)
--------------------------------------------------------------------
    allowed_user_ids list[int]  GitHub numeric user ids permitted. Rename-proof, and
                                the only way to name an account in committed config.
    owner_only       bool       "Only the account that created this instance." The
                                value is DERIVED at boot from the environment
                                (``TAP_AUTH_INSTANCE_OWNER``), never authored here,
                                so a Codespaces-style single-operator instance can
                                declare the intent without hardcoding an account.
                                It resolves against the owner's NUMERIC id; an owner
                                supplied as a login alone is unresolvable and FAILs
                                the offline self-test.

At least one of the two must be present — there is no "any GitHub account"
login, mirroring google_oidc's required ``allowed_domains``. They are a UNION: a
login satisfying any configured clause is admitted.

Deliberately NOT implemented (named, so their absence is not mistaken for coverage)
-----------------------------------------------------------------------------------
    allowed_orgs     GitHub org membership is absent from ``/user``; enforcing it
                     needs the ``read:org`` scope and a separate API call, and
                     org membership can be private. Declaring the knob without
                     enforcing it would be a policy that exists and is false.
    server_url       GitHub Enterprise Server. allauth's ``GitHubOAuth2Adapter``
                     reads ``GITHUB_URL`` from ``SOCIALACCOUNT_PROVIDERS`` at CLASS
                     DEFINITION time, so it is process-global and not expressible
                     per APPS entry — a real change, not a config line.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests
from django.conf import settings

from tap_auth.errors import AccountNotAllowlisted, PolicyUnresolvable, SubjectUnusable
from tap_auth.providers.base import (
    VERIFIED_EMAILS_CLAIM,
    AccessDecision,
    ProfileSnapshot,
    ProviderConfig,
    ProviderError,
    SelfTestPhase,
    SelfTestResult,
    SelfTestStatus,
)
from tap_auth.providers.secrets import resolve_oauth_client_secret, secret_exists

PROVIDER_TYPE = "github_oauth"
ALLAUTH_PROVIDER = "github"
DOCS_URL = "spec-tap-auth-v0 § req-tap-auth-github-oauth"

#: allauth routes the OAuth2 ``github`` provider at ONE fixed path — the callback
#: is not parameterized by ``provider_id`` the way the openid_connect routes are
#: (``allauth/socialaccount/providers/oauth2/urls.py`` builds
#: ``<slug>/login/callback/``). This is the path a GitHub OAuth App registers.
CALLBACK_PATH = "/auth/github/login/callback/"

#: GitHub's OAuth 2.0 code-exchange endpoint. Probed by the live self-test with a
#: deliberately invalid authorization code; see ``_credentials_check``. Named for
#: what it is rather than what it returns: a constant whose NAME carries 'token'
#: trips Bandit B105 (hardcoded-password-string is name-based), and a URL does not
#: need to borrow the word to be legible.
OAUTH_EXCHANGE_URL = "https://github.com/login/oauth/access_token"

#: The scope allauth requests for this provider (``GitHubProvider.get_default_scope``
#: when ``SOCIALACCOUNT_QUERY_EMAIL`` is on). GitHub OAuth Apps do not pre-declare
#: scopes — the authorization request carries them — so this is documentation for
#: the operator, not configuration.
REQUESTED_SCOPE = "user:email"

#: The deliberately-invalid authorization code the live self-test presents. It can
#: never be a real code (real codes are opaque 20-char hex), so the probe cannot
#: consume a live grant or mint a session.
_SELFTEST_INVALID_CODE = "tap-auth-selftest-not-a-real-code"

#: GitHub's answer when client_id+client_secret are a real, live OAuth App and only
#: the CODE was wrong. This is the PASS signal: reaching "your code is bad" proves
#: the credentials got that far.
_ERR_BAD_CODE = "bad_verification_code"

#: GitHub's answer when the credential pair is wrong (verified 2026-09-20 against a
#: real client_id with a wrong secret: HTTP 200, this body). An unknown client_id
#: answers HTTP 404 ``{"error": "Not Found"}`` instead.
_ERR_INCORRECT_CLIENT = "incorrect_client_credentials"


def _result(check: str, status: SelfTestStatus, phase: SelfTestPhase, message: str) -> SelfTestResult:
    return SelfTestResult(check=check, status=status, phase=phase, message=message, docs_url=DOCS_URL)


def _normalized_ids(raw: Any) -> list[str]:
    """Numeric ids as strings — the form ``ExternalIdentity.subject`` stores and the
    form allauth's ``extract_uid`` produces, so the comparison never crosses a type
    boundary. A non-numeric entry is dropped here and reported by validate_config."""
    return [str(v).strip() for v in (raw or []) if str(v).strip().isdigit()]


def instance_owner() -> tuple[str, str]:
    """The account that owns this instance, as ``(login, user_id)``; ``("", "")`` when
    undeclared.

    Only the ``user_id`` authorizes. The ``login`` is returned for diagnostics —
    so a self-test can say "you gave me a handle, I need the numeric id" instead of
    the uselessly blank "resolves to nothing" — and is never compared against a
    claim. An owner known only by handle is an owner who cannot be identified after
    a rename, which is the whole reason identity keys on the id.

    Read from ``settings.TAP_AUTH_INSTANCE_OWNER`` — a mapping with optional
    ``login`` / ``user_id`` keys, populated at boot from the environment. This is
    the seam a Codespaces-style standup fills in (`Issue# 99 - git-serious-tap`):
    the boot profile declares the INTENT (``owner_only: true``) and the environment
    supplies the VALUE, so a profile never hardcodes a person's handle.

    The derivation itself is not implemented here and this returns empty until
    something populates the setting. That is why ``evaluate_access`` denies on an
    unresolved owner instead of falling through: a declared policy with no value is
    the presence-not-correctness shape, and the safe reading of "no owner known" is
    "nobody", never "everybody".
    """
    raw = getattr(settings, "TAP_AUTH_INSTANCE_OWNER", None) or {}
    if not isinstance(raw, Mapping):
        return "", ""
    login = str(raw.get("login") or "").strip().lower()
    user_id = str(raw.get("user_id") or "").strip()
    return login, (user_id if user_id.isdigit() else "")


class GitHubOAuthProvider:
    """github_oauth provider implementation (see module docstring)."""

    type = PROVIDER_TYPE
    allauth_provider = ALLAUTH_PROVIDER

    # -- config helpers ----------------------------------------------------

    def _allowed_user_ids(self, config: ProviderConfig) -> Sequence[str]:
        return _normalized_ids(config.config.get("allowed_user_ids"))

    def _owner_only(self, config: ProviderConfig) -> bool:
        return bool(config.config.get("owner_only", False))

    def callback_url(self, config: ProviderConfig) -> str | None:
        """The one callback URL a GitHub OAuth App registers.

        Unlike the openid_connect routes, this path carries no ``provider_id`` —
        allauth's OAuth2 URL builder emits a single ``github/login/callback/`` per
        provider class. Two github_oauth providers on one instance therefore share
        one route and allauth raises ``MultipleObjectsReturned`` at login time;
        ``validate_config`` refuses that configuration at boot instead.
        """
        base = getattr(settings, "TAP_BASE_URL", "") or ""
        if not base:
            return None
        return f"{base.rstrip('/')}{CALLBACK_PATH}"

    # -- interface ---------------------------------------------------------

    def validate_config(self, config: ProviderConfig) -> list[SelfTestResult]:
        results: list[SelfTestResult] = []
        off = SelfTestPhase.OFFLINE

        if config.type != self.type:
            return [_result("type", SelfTestStatus.FAIL, off, f"expected type '{self.type}', got '{config.type}'")]

        results.append(self._policy_check(config))
        results.append(self._owner_check(config))
        results.append(self._id_shape_check(config))
        results.append(self._singleton_check(config))
        results.append(self._base_url_check(config))
        return results

    def _policy_check(self, config: ProviderConfig) -> SelfTestResult:
        """There is no 'any GitHub account' login (the google_oidc allowed_domains rule)."""
        off = SelfTestPhase.OFFLINE
        ids = self._allowed_user_ids(config)
        owner_only = self._owner_only(config)
        if not (ids or owner_only):
            return _result(
                "access_policy",
                SelfTestStatus.FAIL,
                off,
                "github_oauth requires an access policy — set allowed_user_ids and/or "
                "owner_only. There is no 'any GitHub account' login: GitHub sign-up is open "
                "to the world, so an unset policy would publish this instance.",
            )
        clauses = [name for name, present in (("allowed_user_ids", ids), ("owner_only", owner_only)) if present]
        return _result("access_policy", SelfTestStatus.PASS, off, f"clauses: {', '.join(clauses)}")

    def _owner_check(self, config: ProviderConfig) -> SelfTestResult:
        """owner_only is declared; is there actually an owner to enforce it against?"""
        off = SelfTestPhase.OFFLINE
        if not self._owner_only(config):
            return _result("owner_only", SelfTestStatus.SKIP, off, "not declared")
        login, user_id = instance_owner()
        if user_id:
            return _result("owner_only", SelfTestStatus.PASS, off, f"owner resolved: id={user_id}")
        detail = (
            f"TAP_AUTH_INSTANCE_OWNER carries login={login!r} but no user_id. A login is not an "
            "owner: it can be renamed by its holder and re-registered by someone else, so "
            "matching it would admit whoever holds the handle at login time. Supply the numeric "
            "user_id (GET /users/<login> → .id)."
            if login
            else "TAP_AUTH_INSTANCE_OWNER resolves to nothing — the policy exists and has no value to enforce."
        )
        return _result(
            "owner_only",
            SelfTestStatus.FAIL,
            off,
            f"owner_only is declared but no owner id is resolvable. {detail} Logins fall through "
            "it closed (policy_unresolvable), so this is a misconfiguration, not a working lock.",
        )

    def _id_shape_check(self, config: ProviderConfig) -> SelfTestResult:
        """A non-numeric allowed_user_ids entry is silently dropped by the matcher —
        surface it, or an operator who typed a login there believes it is enforced."""
        off = SelfTestPhase.OFFLINE
        raw = config.config.get("allowed_user_ids") or []
        bad = [str(v) for v in raw if not str(v).strip().isdigit()]
        if bad:
            return _result(
                "allowed_user_ids",
                SelfTestStatus.FAIL,
                off,
                f"non-numeric entries are not GitHub user ids and match nothing: {bad}. "
                "A login cannot be allowlisted at all — resolve it to its numeric id "
                "(GET /users/<login> → .id) and put that here.",
            )
        return _result("allowed_user_ids", SelfTestStatus.PASS, off, f"{len(raw)} numeric id(s)")

    def _singleton_check(self, config: ProviderConfig) -> SelfTestResult:
        """allauth routes every github app at one fixed path, so a second github_oauth
        provider is unreachable-by-construction: ``get_app`` raises
        ``MultipleObjectsReturned`` mid-login. Fail at boot, where it is legible."""
        off = SelfTestPhase.OFFLINE
        configured = getattr(settings, "TAP_AUTH_PROVIDERS", []) or []
        siblings = [
            str(raw.get("id"))
            for raw in configured
            if isinstance(raw, Mapping) and raw.get("type") == self.type and str(raw.get("id")) != config.id
        ]
        if siblings:
            return _result(
                "single_github_provider",
                SelfTestStatus.FAIL,
                off,
                f"another github_oauth provider is configured ({', '.join(siblings)}). allauth "
                f"routes all github apps at {CALLBACK_PATH} with no provider_id, so a second one "
                "makes every GitHub login fail at the callback. Configure exactly one.",
            )
        return _result("single_github_provider", SelfTestStatus.PASS, off, "exactly one github_oauth provider")

    def _base_url_check(self, config: ProviderConfig) -> SelfTestResult:
        off = SelfTestPhase.OFFLINE
        callback = self.callback_url(config)
        if callback is None:
            return _result(
                "tap_base_url",
                SelfTestStatus.FAIL,
                off,
                "TAP_BASE_URL is required to derive the OAuth callback URL for an external provider.",
            )
        return _result("tap_base_url", SelfTestStatus.PASS, off, f"callback: {callback}")

    def resolve_secrets(self, config: ProviderConfig) -> dict[str, str]:
        return resolve_oauth_client_secret(config.secret_key)

    # -- the security core -------------------------------------------------

    def evaluate_access(self, config: ProviderConfig, claims: Mapping[str, Any]) -> AccessDecision:
        """Decide whether this GitHub account may log in. Pure, claim-only.

        Order (each fails closed with a distinct reason code):
          1. A usable durable subject — the numeric ``id``. Absent ⇒ ``subject_unusable``:
             there is nothing stable to key an ``ExternalIdentity`` on, and falling back
             to the login would make identity renameable.
          2. The union of the configured clauses (``allowed_user_ids`` /
             ``owner_only``). No clause matches ⇒ ``account_not_allowlisted``. A
             declared-but-unresolvable ``owner_only`` that is the ONLY clause ⇒
             ``policy_unresolvable`` — a misconfiguration stated as such, never a
             silent allow.

        **Every clause compares numeric ids.** The login is read only to be logged.
        A clause that matched a handle would authorize whoever holds it at login
        time, which is the same renameable-and-recyclable value identity refuses to
        key on — see the module docstring.

        Note what is deliberately NOT a gate here: a verified email. See the module
        docstring — GitHub's policy is not email-derived, so requiring one would deny
        an explicitly allowlisted id for an unrelated reason. Email is still only
        ever *trusted* when GitHub itself verified it, which is what the
        ``verified_email`` on the returned decision means.
        """
        subject = str(claims.get("id") or "").strip()
        login = str(claims.get("login") or "").strip().lower()
        verified_email = self._verified_email(claims)

        if not subject.isdigit():
            return AccessDecision(
                allowed=False,
                reason=SubjectUnusable.reason,
                user_message="Your identity provider did not return a usable account identifier.",
                log_detail=f"github /user returned id={claims.get('id')!r} (expected a numeric user id)",
                matched_rule="subject",
            )

        allowed_ids = set(self._allowed_user_ids(config))
        owner_only = self._owner_only(config)
        _owner_login, owner_id = instance_owner()

        if subject in allowed_ids:
            return self._allow(verified_email, "allowed_user_ids")
        if owner_only and owner_id and subject == owner_id:
            return self._allow(verified_email, "owner_only")

        if owner_only and not owner_id and not allowed_ids:
            # The ONLY declared clause cannot be resolved: say that, rather than
            # reporting "not on the allowlist" for a list that was never computed.
            return AccessDecision(
                allowed=False,
                reason=PolicyUnresolvable.reason,
                user_message="This deployment's sign-in policy is incomplete. An administrator must finish setup.",
                log_detail="owner_only is the only clause and TAP_AUTH_INSTANCE_OWNER resolved to no numeric user_id",
                verified_email=verified_email,
                matched_rule="owner_only",
            )

        return AccessDecision(
            allowed=False,
            reason=AccountNotAllowlisted.reason,
            user_message=(
                "You authenticated with GitHub correctly, but your account is not on this "
                "deployment's allowlist. An administrator must add you."
            ),
            log_detail=(
                f"no clause matched: id={subject} login={login or '<none>'} "
                f"(allowed_user_ids={len(allowed_ids)}, owner_only={owner_only})"
            ),
            verified_email=verified_email,
            matched_rule="allowed_user_ids,owner_only",
        )

    def _allow(self, verified_email: str, rule: str) -> AccessDecision:
        return AccessDecision(
            allowed=True,
            verified_email=verified_email,
            matched_rule=rule,
        )

    def _verified_email(self, claims: Mapping[str, Any]) -> str:
        """The first address GITHUB marks verified, or "".

        Never ``claims["email"]``: GitHub's ``/user`` email is typed in by the account
        holder and carries no verification assertion. The verified set is injected by
        the social adapter under ``VERIFIED_EMAILS_CLAIM`` from
        ``SocialLogin.email_addresses`` — the list allauth built from ``/user/emails``.
        """
        addresses = claims.get(VERIFIED_EMAILS_CLAIM) or []
        if isinstance(addresses, str) or not isinstance(addresses, Sequence):
            return ""
        for address in addresses:
            text = str(address).strip().lower()
            if "@" in text:
                return text
        return ""

    def profile_snapshot(self, config: ProviderConfig, claims: Mapping[str, Any]) -> ProfileSnapshot:
        """GitHub's display-only vocabulary. GitHub has ONE free-text ``name``, not a
        given/family split, so first/last stay empty rather than being guessed by
        splitting on whitespace — a guess that is wrong for most of the world's names
        and would be stored as if asserted. ``hosted_domain`` has no GitHub analogue."""
        return ProfileSnapshot(
            display_name=str(claims.get("name") or claims.get("login") or ""),
            avatar_url=str(claims.get("avatar_url") or ""),
        )

    # -- self-tests --------------------------------------------------------

    def self_test(self, config: ProviderConfig, secrets: Mapping[str, str], *, live: bool) -> list[SelfTestResult]:
        results = self.validate_config(config)
        off = SelfTestPhase.OFFLINE

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
            results.append(_result("secret", SelfTestStatus.PASS, off, f"client_id …{secrets['client_id'][-6:]}"))

        results.append(self._credentials_check(secrets, live=live))
        return results

    def _credentials_check(self, secrets: Mapping[str, str], *, live: bool) -> SelfTestResult:
        """The live check: are these client credentials a real, live GitHub OAuth App?

        An OAuth 2.0 provider has no discovery document, so the google_oidc live check
        has no analogue — and "GET api.github.com answers" would be a check that can
        only fail when GitHub itself is down, i.e. a green light for a misconfigured
        app. That is the false-green shape this repo keeps finding.

        What CAN fail here is the credential pair. Presenting it at the token endpoint
        with a deliberately invalid authorization code makes GitHub adjudicate the
        credentials before it ever looks at the code:

          - ``bad_verification_code``      → the app is real and live (PASS: the request
                                             got past credential validation).
          - ``incorrect_client_credentials`` → wrong id/secret (FAIL). Verified against
                                             the live endpoint 2026-09-20.
          - HTTP 404 ``Not Found``        → no such client_id (FAIL). Same probe.
          - anything else                 → WARN with the raw code echoed. An unrecognised
                                             answer is not evidence of health, and calling
                                             it PASS would be the lie this check exists
                                             to prevent.

        No side effects: the code is syntactically impossible as a real grant, so
        nothing is consumed and no session is minted. The client secret goes to
        GitHub's own token endpoint — the one place it is meant to go — and is never
        logged.
        """
        live_phase = SelfTestPhase.LIVE
        if not live:
            return _result(
                "client_credentials", SelfTestStatus.SKIP, live_phase, f"live check skipped ({OAUTH_EXCHANGE_URL})"
            )
        client_id = secrets.get("client_id") or ""
        client_secret = secrets.get("client_secret") or ""
        if not client_id or not client_secret:
            return _result(
                "client_credentials",
                SelfTestStatus.FAIL,
                live_phase,
                "cannot probe the token endpoint: client_id/client_secret were not resolved",
            )
        try:
            resp = requests.post(
                OAUTH_EXCHANGE_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": _SELFTEST_INVALID_CODE,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            return _result(
                "client_credentials",
                SelfTestStatus.FAIL,
                live_phase,
                f"could not reach {OAUTH_EXCHANGE_URL}: {exc}",
            )

        try:
            body = resp.json()
        except ValueError:
            return _result(
                "client_credentials",
                SelfTestStatus.WARN,
                live_phase,
                f"{OAUTH_EXCHANGE_URL} returned HTTP {resp.status_code} with a non-JSON body; "
                "cannot confirm or refute the credentials",
            )
        error = str(body.get("error") or "") if isinstance(body, Mapping) else ""

        if error == _ERR_BAD_CODE:
            return _result(
                "client_credentials",
                SelfTestStatus.PASS,
                live_phase,
                "GitHub accepted the client credentials and rejected only the probe code "
                "(bad_verification_code) — the OAuth App is real and live.",
            )
        if error == _ERR_INCORRECT_CLIENT or resp.status_code == 404:
            return _result(
                "client_credentials",
                SelfTestStatus.FAIL,
                live_phase,
                f"GitHub rejected the client credentials (HTTP {resp.status_code}, error={error or 'Not Found'}). "
                f"Check the OAuth App's Client ID/secret in the auth:<key> secret.",
            )
        return _result(
            "client_credentials",
            SelfTestStatus.WARN,
            live_phase,
            f"unrecognised answer from {OAUTH_EXCHANGE_URL} (HTTP {resp.status_code}, error={error or '<none>'}); "
            "treating as inconclusive rather than healthy.",
        )

    # -- allauth wiring ----------------------------------------------------

    def build_allauth_settings(self, config: ProviderConfig, secrets: Mapping[str, str]) -> dict[str, Any]:
        """One allauth APPS entry for the ``github`` provider.

        The key set is exactly what allauth's ``_build_apps_from_settings`` copies onto
        a ``SocialApp`` (``name``, ``provider_id``, ``client_id``, ``secret``, ``key``,
        ``settings``); anything else is dropped silently, so nothing else is emitted.
        ``provider_id`` is carried even though GitHub's routes are not parameterized by
        it, because ``Provider.sub_id`` is ``app.provider_id or app.provider`` — it is
        what ``SocialAccount.provider`` is stamped with, and therefore what the social
        adapter passes to ``get_provider_config`` to find this provider's TAP policy.
        Omitting it would stamp the account ``"github"`` and the policy lookup would
        miss.
        """
        if not secrets.get("client_id") or not secrets.get("client_secret"):
            raise ProviderError(f"cannot build allauth settings for {config.id}: secret not resolved")
        return {
            "provider_id": config.id,
            "name": config.display_name,
            "client_id": secrets["client_id"],
            "secret": secrets["client_secret"],
            "settings": {},
        }
