"""The deploy security posture gate — derived from Django, promoted by TAP.

`req-tap-auth-boot-7` says this gate MUST run before serving a deploy boot. Until
2026-09-16 it did neither reliably (tap#272):

- It lived inside `apply_auth_boot_section`, behind `if profile.has_auth`, so it ran
  for exactly one of the five shipped profiles. What it checks — `SECRET_KEY`,
  `ALLOWED_HOSTS`, cookie transport — is not auth configuration; `SECRET_KEY` signs
  every `signing.dumps` and `ALLOWED_HOSTS` is Host-header defence. A deployment
  running `core` with `DEBUG=false` got none of it.
- It could not pass. Two of the five settings it required were assigned nowhere in
  the codebase and had no environment variable behind them, so a correctly
  configured deployment aborted on values no operator could set.

Either alone would have been caught. Together they cancelled: the gate was
unsatisfiable, but almost nothing reached it, so nothing ever failed and nobody
discovered it was broken. The one profile that did reach it aborted on the cookie
flags — which read as "that profile is not ready" rather than "the gate is broken".

**Derived, not re-implemented.** `spec-tap-auth-v0.md:565` always said this gate
"runs (or echoes) `manage.py check --deploy` and treats the relevant findings as
boot failures". It did not; it hand-rolled five checks beside Django's. Django's own
deployment checks cover those five and more, are maintained upstream, and gain new
ones as the framework learns. So the list of *what is wrong* comes from Django and
the list of *what is fatal* is TAP's — the derive-a-fact-once split.

**Django is the source of findings, not the whole of them.** Three checks are TAP's own
because Django structurally cannot make them: a `SECRET_KEY` that is long, random and
published in our own repository, a database password that is (tap#463), and an
`ALLOWED_HOSTS` wildcard (`W020` tests only for emptiness). Deriving from Django is right;
assuming Django covers everything the hand-rolled gate covered was not, and cost a
Host-header defence until review caught it.

**Why the fatal set is explicit and small.** Django's deployment checks are Warnings.
Promoting "every warning" would make the gate unpassable again the first time Django
adds a check — the same class of failure this module exists to fix, reintroduced by
its fix. So the promoted set is named below, and a deploy warning outside it is
reported and does not abort. Widening it is a deliberate edit with a reason, never a
framework upgrade's side effect.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

from tap.dev_credentials import matches_dev_stack_digest

if TYPE_CHECKING:
    from collections.abc import Callable

    Echo = Callable[[str], None]

logger = logging.getLogger(__name__)


# Django deployment checks promoted from Warning to boot-fatal. Each is one of the
# five the hand-rolled gate asserted, so this preserves the intended posture exactly
# while sourcing the finding from Django.
#
# NOT promoted, deliberately, and each for a reason rather than by omission:
#   security.W004 (HSTS), W021 (HSTS preload)  — meaningful only once TLS is terminated
#                                                in front of us; req-tap-serving-proxy.
#   security.W008 (SSL redirect)               — wrong for a plaintext-on-trusted-network
#                                                deployment, and redundant behind a proxy
#                                                that already redirects.
#   security.W019 (X_FRAME_OPTIONS), W006,
#   W007, W022 (referrer policy)               — real hardening, no demand signal yet;
#                                                promote when someone needs them, with
#                                                a test, not as a sweep.
# The ids below were established by SPOILING each setting and reading which check
# actually fired — not from memory. The first pass had the session and CSRF ids
# transposed (W010/W012 instead of W012/W016), and the tests caught it. Verify the
# same way before adding one.
FATAL_DEPLOY_CHECKS: frozenset[str] = frozenset(
    {
        "security.W009",  # SECRET_KEY has insufficient entropy / length
        "security.W012",  # SESSION_COOKIE_SECURE is not True
        "security.W016",  # CSRF_COOKIE_SECURE is not True
        "security.W018",  # DEBUG is True in deployment
        "security.W020",  # ALLOWED_HOSTS is empty
    }
)


class DeployPostureError(Exception):
    """The deployment posture is unsafe to serve. Aborts boot."""


def _no_usable_allowed_hosts() -> bool:
    """Whether `ALLOWED_HOSTS` names no host at all once blanks are dropped.

    Django's `security.W020` tests the LIST for emptiness, and `bool([""])` is true — so
    `ALLOWED_HOSTS=` on the documented env path yields `[""]`, which W020 accepts. The
    deleted gate filtered blanks first (`[h for h in hosts if h]`) and then refused an
    empty result, so it caught this and the replacement did not.

    Not a Host-header bypass — Django rejects real Host values against `[""]` at request
    time. It is a false declaration, which is the reason to refuse it: the gate would
    report the posture OK for an instance that can serve no host at all.
    """
    return not [h for h in (settings.ALLOWED_HOSTS or []) if h.strip()]


def _wildcard_allowed_hosts() -> bool:
    """Whether `ALLOWED_HOSTS` admits any Host header.

    TAP's own check, because Django's does not cover it: `security.W020` fires only when
    the list is EMPTY. Verified on the pinned Django — with `ALLOWED_HOSTS = ["*"]` and
    everything else deployable, the checks that fire are W004, W008 and `tap_grid.E001`;
    W020 is not among them.

    The hand-rolled gate this module replaced refused `"*" in hosts` explicitly, so
    sourcing findings from Django alone silently dropped a Host-header defence — the
    replacement looked equivalent and was not. `ALLOWED_HOSTS=*` is reachable from the
    documented env path, which splits on commas, so the wildcard is one character away.
    """
    return "*" in [h for h in (settings.ALLOWED_HOSTS or []) if h]


def _shipped_dev_secret_in_use() -> bool:
    """Whether `SECRET_KEY` is the value the development compose stack sets.

    Kept as TAP's own check because Django cannot know it. `security.W009` catches a
    key that is too short or too uniform; it cannot catch a key that is long, random,
    and published in our own repository. A value that is present and public passes every
    check that asks whether a secret key is configured, which is the
    presence-is-not-correctness shape at its purest.

    NOT dead code after tap#463, and the reason is worth stating: removing the SETTINGS
    DEFAULT closed the path where an operator INHERITS the published key by configuring
    nothing (`tap/settings.py` now refuses to start with `SECRET_KEY` unset, so the
    `not key` half this function used to carry is unreachable and gone). It did not close
    the path where an operator COPIES `docker-compose.yml` — the development stack still
    declares its own key there, because it is what makes a fresh clone run. This check is
    the guard on that second path.

    Compared by DIGEST (`settings.DEV_STACK_SIGNING_FINGERPRINT`): recognising the value
    never requires holding it, and holding it put a credential-shaped literal in a public
    repository. `tap/dev_credentials.py` carries the reasoning and the constant-time
    comparison both gates share.
    """
    return matches_dev_stack_digest(settings.SECRET_KEY, settings.DEV_STACK_SIGNING_FINGERPRINT)


def _shipped_dev_db_password_in_use() -> bool:
    """Whether any database alias authenticates with the development stack's password.

    The same shape as the secret key, for the credential the 2026-09-15 incident review
    kept finding next to it: `docker-compose.yml` publishes 5432 to the host and the dev
    password is a literal in a public repository. `tap/settings.py` no longer falls back to
    it (there is no `DATABASE_URL` default at all), so this covers the copy-the-compose-file
    path, not the configure-nothing one.

    Checked across EVERY alias rather than `default` alone: `search_readonly` carries its
    own credential, and a deployment that rotated one and not the other is exactly the
    half-done state a per-alias check catches and a `default`-only check reports as clean.

    Compared by digest, for the reasons in `tap/dev_credentials.py`.
    """
    return any(
        matches_dev_stack_digest(db.get("PASSWORD"), settings.DEV_STACK_DATABASE_FINGERPRINT)
        for db in (settings.DATABASES or {}).values()
    )


def check_deploy_posture(echo: Echo) -> None:
    """Refuse to serve a deployment whose security posture is unsafe.

    Runs for EVERY profile (and for no profile at all), gated only on
    `settings.DEPLOY_POSTURE_ENFORCED` — because what it checks is a property of the
    deployment, not of any profile's auth section. Raises `DeployPostureError`; the
    caller turns that into a boot abort.
    """
    if not settings.DEPLOY_POSTURE_ENFORCED:
        # Not a pass and not a failure — the gate does not apply to this boot. Said
        # out loud so "the gate was silent" is never read as "the gate was satisfied"
        # (three states, not two).
        logger.info("[220d] deploy posture: enforcement off — development boot, gate not applicable")
        echo("Posture phase: enforcement off (development boot); deploy posture gate not applicable.")
        return

    from django.core.checks.registry import registry

    problems: list[str] = []
    if _shipped_dev_secret_in_use():
        problems.append("SECRET_KEY is the value the development compose stack sets")
    if _shipped_dev_db_password_in_use():
        problems.append("a database alias authenticates with the development stack's password")
    if _wildcard_allowed_hosts():
        problems.append("ALLOWED_HOSTS contains '*' — any Host header is accepted")
    if _no_usable_allowed_hosts():
        problems.append("ALLOWED_HOSTS names no host (blank entries only)")

    advisory: list[str] = []
    for message in registry.run_checks(include_deployment_checks=True):
        check_id = message.id or ""
        if check_id in FATAL_DEPLOY_CHECKS:
            problems.append(f"{check_id}: {message.msg.splitlines()[0]}")
        elif message.is_serious() or check_id.startswith("security."):
            advisory.append(f"{check_id}: {message.msg.splitlines()[0]}")

    for note in advisory:
        logger.info("[0611] deploy posture advisory: %s", note)
        echo(f"  [posture] advisory (not fatal): {note}")

    if problems:
        logger.error("[3ca6] deploy posture FAILED: %s", "; ".join(problems))
        raise DeployPostureError("deploy security posture check failed: " + "; ".join(problems))

    echo(f"Posture phase: deploy security posture OK ({len(FATAL_DEPLOY_CHECKS)} promoted checks clear).")
