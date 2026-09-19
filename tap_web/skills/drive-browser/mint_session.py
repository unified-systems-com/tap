"""Mint a Django DB session for a user and print ``SESSIONKEY=<key>``.

Reaches auth-walled pages without the Google OIDC login flow: create a real
server-side session bound to an existing user, then inject its key as the
browser's ``sessionid`` cookie (``drive.py --session``).

Run inside the web container, reading this file on stdin::

    scripts/dc exec -T web uv run python manage.py shell < tap_web/skills/drive-browser/mint_session.py

Pick the user with the ``TAP_DRIVE_USER`` env var (default ``admin``)::

    scripts/dc exec -T -e TAP_DRIVE_USER=tap_viewer web uv run python manage.py shell < .../mint_session.py

DEV ONLY. This bypasses interactive auth by construction — never wire it into a
non-local deployment. It **self-enforces** that: it refuses to run unless
``settings.DEBUG`` is True, so it is inert against any hardened system. The
backend name below must match one of ``settings.AUTHENTICATION_BACKENDS`` (TAP
uses ``tap_auth.auth_backends.TapModelBackend``).
"""

import os
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model

# Fail closed unless this is a dev system. Bypassing interactive auth against a
# hardened deployment must be impossible, not merely discouraged. Since tap#463 DEBUG
# defaults FALSE and the development compose stack opts in explicitly (see
# tap/settings.py and docker-compose.yml), which makes it a stronger dev-mode signal
# than it was: a deployment now has to go out of its way to look like a dev box.
if not settings.DEBUG:
    raise SystemExit(
        "mint_session.py refuses to run: settings.DEBUG is False, so this is not "
        "a dev system. This tool bypasses interactive auth and is DEV ONLY."
    )

username = os.environ.get("TAP_DRIVE_USER", "admin")
user = get_user_model().objects.get(username=username)

store = import_module(settings.SESSION_ENGINE).SessionStore()
store["_auth_user_id"] = str(user.pk)
store["_auth_user_backend"] = "tap_auth.auth_backends.TapModelBackend"
store["_auth_user_hash"] = user.get_session_auth_hash()
store.create()

print("SESSIONKEY=" + store.session_key)
