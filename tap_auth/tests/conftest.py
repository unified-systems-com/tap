"""tap_auth test wiring: the URLConf follows ``TAP_AUTH_PROVIDERS`` (tap#1258).

``tap_auth.urls`` reads ``TAP_AUTH_PROVIDERS`` when it is IMPORTED: the device-flow routes
(``device_login`` / ``device_start`` / ``device_poll``) are mounted only when a provider entry
declares device flow (``tap_auth.views_device.device_urlpatterns``, req-sec-cheap-edges-2). A
process imports the URLConf once. So when a worker's FIRST URL resolution happened inside a test
that had set a device-flow provider through the ``settings`` fixture (test_device_views,
test_device_flow), the worker kept that test's routes for the rest of the run, and the
route-inventory test (test_allauth_url_surface) later failed on three names it had never ruled
on. Whether that happened depended only on how xdist dealt the files out, which is why it showed
up in one ``-n 4`` run of tap_grid + tap_auth and not in the next.

Reproduced serially: ``pytest -n0 tap_auth/tests/test_device_views.py
tap_auth/tests/test_device_flow.py tap_auth/tests/test_allauth_url_surface.py::
test_auth_url_inventory_is_exactly_the_declared_set`` failed with exactly those three names
extra. It is unrelated to how the test database was built: the inventory test touches no
database.

The fix keeps the production rule (routes appear at boot or not at all) and stops a test's
settings outliving the test: whenever ``TAP_AUTH_PROVIDERS`` changes (set or restored by the
``settings`` fixture or ``override_settings``), the cached URLConf is dropped, so the next
resolution builds it from the settings in force — the same way Django's own test signals clear the
URL caches when ``ROOT_URLCONF`` changes.
"""

from __future__ import annotations

import sys
from typing import Any

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.urls import clear_url_caches
from django.urls.converters import REGISTERED_CONVERTERS, get_converters


@receiver(setting_changed, dispatch_uid="tap_auth.tests.urlconf_follows_providers")
def _urlconf_follows_providers(*, setting: str, **_kwargs: Any) -> None:
    if setting != "TAP_AUTH_PROVIDERS":
        return
    clear_url_caches()
    for module in (str(settings.ROOT_URLCONF), "tap_auth.urls"):
        sys.modules.pop(module, None)
    # Re-importing tap_auth.urls registers its path converter again, which Django refuses.
    REGISTERED_CONVERTERS.pop("invite_id", None)
    get_converters.cache_clear()  # type: ignore[attr-defined]  # an lru_cache; the stubs say plain callable
