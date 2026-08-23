"""Test settings — inherits from tap.settings and overrides only what tests need.

Used by pytest via the `DJANGO_SETTINGS_MODULE = "tap.test_settings"` line in
`pyproject.toml`'s `[tool.pytest.ini_options]`. The container entrypoint and
management commands continue to default to `tap.settings`.

Per `tap_cares/specs/spec-tap-cares-task-backend.md`
`req-tap-cares-task-backend-test-settings`: tests use `ImmediateBackend` for
`TASKS["default"]["BACKEND"]` so synchronous-completion semantics are
preserved. Existing tests that rely on `run_collection` reaching a terminal
state before returning continue to work without modification.

Per `specs/spec-tap-logging.md` `req-tap-logging-config-location-3`:
`test_settings.py` may override individual logger entries. Here we flip
`propagate` to True on every configured logger so pytest's `caplog` fixture
(which attaches its handler to the root logger) can capture records that
production has configured as `propagate=False`.
"""

from __future__ import annotations

import copy
import os

from tap.db_aliases import SEARCH_READONLY
from tap.settings import *  # noqa: F401, F403
from tap.settings import DATABASES as _DATABASES
from tap.settings import LOGGING as _LOGGING

# Optional pre-migrated template DB (req: eliminate the per-worker xdist test-DB
# creation race + speed up setup). When TAP_TEST_DB_TEMPLATE names a fully-migrated
# template database, Django's PostgreSQL backend creates each worker's test DB with
# `CREATE DATABASE ... WITH TEMPLATE <template>` — an atomic clone of the complete
# schema — instead of migrating from zero per worker. This removes the class of
# flake where a freshly-created worker DB was missing a late-migration table (e.g.
# tap_capability) under concurrent creation, and makes setup a fast clone. The
# search_readonly alias is a TEST.MIRROR of default, so it inherits the cloned DB;
# only default needs the TEMPLATE. Opt-in: unset → unchanged migrate-from-zero.
_test_db_template = os.environ.get("TAP_TEST_DB_TEMPLATE")
if _test_db_template:
    _DATABASES["default"].setdefault("TEST", {})["TEMPLATE"] = _test_db_template

# Package-mode plugins load under pytest via tap.settings itself: pytest runs Django
# directly (never the pre-boot stage), so TAP_PLUGINS is unset and settings falls back
# to entry-point discovery — loading exactly the package-mode plugins editable-installed
# in the venv (e.g. fedramp_20x_ksi under the samsite profile). No plugin-loading logic
# is needed here. See tap/settings.py TAP_PLUGINS_APPS.

# This process IS the test runner (req-tap-auth-actor-model). The only signal
# that gates creation of test-only built-ins such as the tap_test actor.
TAP_TEST_MODE = True

# The least-privilege search role (req-grid-search-readonly-role.sec) is provisioned at boot in
# dev/prod, where the search_readonly connection authenticates as it. The test runner does not
# run boot, so the suite keeps search_readonly on the app role — the whole corpus does not run
# as the restricted role (which would red every read if a grant were missing). The role's grants
# are validated authentically by tap_grid/tests/test_search_role.py via SET ROLE, so grant-
# completeness assurance does not depend on flipping the suite. USER/PASSWORD revert to the app
# role; the read-only session flag + resource GUCs (OPTIONS) and TEST.MIRROR are preserved.
DATABASES[SEARCH_READONLY] = {  # noqa: F405
    **DATABASES[SEARCH_READONLY],  # noqa: F405
    "USER": DATABASES["default"]["USER"],  # noqa: F405
    "PASSWORD": DATABASES["default"]["PASSWORD"],  # noqa: F405
}

TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
    },
}

# Cache: local-memory in tests (no DatabaseCache table to provision; tests need
# no cross-process / hot-swap survival). Production uses DatabaseCache — see
# tap.settings CACHES and the no-external-cache posture.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

LOGGING = copy.deepcopy(_LOGGING)
for _entry in LOGGING.get("loggers", {}).values():
    _entry["propagate"] = True
del _entry

# Passkey ceremony tests need a deterministic RP-ID + exact origin; the vendored
# virtual authenticator signs for this exact origin (req-tap-auth-passkey-webauthn-7).
TAP_PASSKEY_RP_ID = "localhost"
TAP_PASSKEY_ORIGIN = "http://localhost:8090"
