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
def check_search_readonly_password_is_not_the_dev_default(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Refuse to run outside DEBUG while the search-readonly password is the default.

    Fail-closed by design: this returns an `Error`, not a `Warning`, so `migrate`
    and every other management command abort rather than provisioning the role with
    a published password. A warning here would scroll past in boot output, which is
    exactly how the value would reach production in the first place.

    No-ops under DEBUG, so local development and the test suite are unaffected.
    """
    if settings.DEBUG:
        return []
    if settings.SEARCH_READONLY_PASSWORD != settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD:
        return []
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
