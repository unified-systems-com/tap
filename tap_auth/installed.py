"""tap_auth-owned declaration of the django-allauth INSTALLED_APPS entries.

Django's app registry is flat and frozen during ``django.setup()`` (before any
``AppConfig.ready()`` runs), so allauth's apps MUST be listed in
``settings.INSTALLED_APPS`` — no app can append other apps. But tap_auth can own
the *declaration* and the ordering rationale; ``tap/settings.py`` just spreads
``ALLAUTH_APPS`` into the list. This is the django-oscar "framework exports its
app-list, project assembles it" pattern, applied to the tap_auth integration app
(which owns the adapter, providers, policy, and URL includes; allauth stays a
peer engine, and tap_web owns the templates).

IMPORTANT: this module is imported at settings-build time, BEFORE the app
registry exists. Keep it a bare list constant — no Django model imports, no
``django.conf.settings`` access at module top — or it hits the settings-import
re-entrancy class encountered elsewhere in tap_auth.

Ordering note (enforced by where settings spreads this): allauth must come AFTER
the tap apps so tap_web wins template resolution (APP_DIRS first-match-wins) and
overrides allauth's defaults.

One allauth provider app per TAP provider TYPE, not per configured provider: the
``openid_connect`` engine backs every ``google_oidc`` provider (each addressed by
a stable ``provider_id`` natural key) and the ``github`` engine backs
``github_oauth`` (req-tap-auth-github-oauth). Both are listed unconditionally.
They must be: this list is built at settings-import time from a static constant,
while the CONFIGURED providers come from the boot profile — so gating an entry on
"is one configured" would mean a profile that adds a GitHub provider silently gets
no routes and no provider registration, which surfaces as a 404 at
``/auth/github/login/`` rather than as a configuration error. An installed
provider app with no app configured registers nothing and costs nothing.
"""

from __future__ import annotations

ALLAUTH_APPS: list[str] = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "allauth.socialaccount.providers.github",
]
