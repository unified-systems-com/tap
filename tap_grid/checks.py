"""tap_grid system checks — deployment-configuration guards.

req-grid-search-readonly-role.sec. The search-readonly role's password has a
dev-only default so `docker compose up` works out of the box. That convenience is
load-bearing for onboarding and worth keeping — but `tap_boot.orchestrator`
PROVISIONS the Postgres role with whatever the setting resolves to, on every boot,
so a deployment that never sets `TAP_SEARCH_READONLY_PASSWORD` ends up with a live
database login whose password is a literal in a public repository, on a port
`docker-compose.yml` publishes to the host.

The role is least-privilege (SELECT on grid tables + spine), so the exposure is
read access to grid contents rather than takeover. That is still not a default
anyone should reach production with.

This is the fourth instance of one shape found during the #123 Sonar triage: a
value that is *documented* as dev-only, with nothing enforcing it. The others were
`Invitation.public_id` ("the log-safe lookup handle", unchecked on the way in), the
plugin slug alphabet (asserted in a comment while flowing into subprocess argv),
and the FIPS provider's source (a "validated CMVP #4282" claim over an unverified
download). Documentation is not a control.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security)
def check_secret_key_is_not_the_dev_default(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Refuse to run outside DEBUG while SECRET_KEY is the development stack's key.

    Same shape as the search-readonly guard below, for a worse secret: SECRET_KEY
    signs session cookies and CSRF tokens, so a known value means forged sessions for
    any user. The value is a literal in a PUBLIC repository.

    `tap_boot.posture.check_deploy_posture` also covers this, and since tap#272 that gate
    runs for every profile — but it runs at BOOT. This runs on every management command,
    which is the reason to keep both for now: `docker/entrypoint.sh` runs `createcachetable`
    and `migrate` before boot, so a misconfigured deployment mutates its schema before the
    boot gate gets a word in. The two are not a derive-twice pair by accident; both read
    `settings.DEV_STACK_SECRET_KEY` rather than re-typing it.

    Empty is no longer reachable here: `tap/settings.py` refuses to finish importing with
    `SECRET_KEY` unset or blank (req-tap-serving-fail-closed), so the only way to be wrong
    is to be the development stack's value. The old empty branch was removed rather than
    left as a check that can never fire.
    """
    if settings.DEBUG:
        return []
    if settings.SECRET_KEY != settings.DEV_STACK_SECRET_KEY:
        return []
    return [
        Error(
            "SECRET_KEY is still the development stack's key while DEBUG is off. It signs "
            "session cookies and CSRF tokens, so a known value lets an attacker forge a "
            "session for any user — and the value is a literal in a public repository.",
            hint=(
                "Set SECRET_KEY to a generated secret in the deployment environment. "
                "Django's own security.W009 additionally wants 50+ characters with at "
                "least 5 distinct ones."
            ),
            id="tap_grid.E003",
        )
    ]


@register(Tags.security)
def check_search_readonly_password_is_not_the_dev_default(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Refuse to run outside DEBUG while the search-readonly password is the default.

    Fail-closed by design: this returns an `Error`, not a `Warning`, so every
    management command aborts — including `manage.py boot`, whose grid-infra phase
    (`tap_boot.orchestrator._phase_grid_infra`) is what actually provisions the role.
    A warning would scroll past in boot output, which is exactly how the value would
    reach production in the first place.

    No-ops under DEBUG, so local development and the test suite are unaffected.
    """
    if settings.DEBUG:
        return []
    password = settings.SEARCH_READONLY_PASSWORD
    # EMPTY IS NOT "NOT THE DEFAULT". Setting TAP_SEARCH_READONLY_PASSWORD="" satisfies a
    # bare inequality against the dev default while provisioning the role with NO password,
    # which is strictly worse than the published one. The first version of this check tested
    # only inequality and let that through — the deploy-posture gate two modules away
    # (tap_boot/posture.py::check_deploy_posture) already guards SECRET_KEY with
    # `not settings.SECRET_KEY or ...`, and this should have matched it.
    if password and password != settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD:
        return []
    if not password:
        return [
            Error(
                "TAP_SEARCH_READONLY_PASSWORD is empty while DEBUG is off. tap_boot provisions "
                "the Postgres search-readonly role with this value at every boot, so this "
                "deployment would create a database login with no password at all.",
                hint=(
                    "Set TAP_SEARCH_READONLY_PASSWORD to a generated secret. Unsetting it falls "
                    "back to the published dev default, which this check also refuses — the "
                    "value has to be a real one."
                ),
                id="tap_grid.E002",
            )
        ]
    return [
        Error(
            "TAP_SEARCH_READONLY_PASSWORD is still the dev-only default while DEBUG is off. "
            "tap_boot provisions the Postgres search-readonly role with this value at every "
            "boot, so this deployment would expose a database login whose password is a "
            "literal in a public repository.",
            hint=(
                "Set TAP_SEARCH_READONLY_PASSWORD to a generated secret in the deployment "
                "environment. It does not need to be memorable or rotated on a schedule — it "
                "is the credential for a least-privilege read-only role — it only needs to "
                "not be the published default."
            ),
            id="tap_grid.E001",
        )
    ]
