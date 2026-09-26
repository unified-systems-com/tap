"""tap_boot unit tests for shipped-profile resolution.

The per-commit assertion that *every* shipped `boot/*.boot.json` resolves against
the live registries now lives in `tap_boot/guards/profile_resolution.py`
(`ProfileResolutionGuard`), discovered and run by the validation harness (and by
the pre-boot gate directly). These two tests stay here as tap_boot's own unit
coverage: one that the house profiles exist at all (so the guard covers something),
and one that validates the validator — the rot class it exists to catch actually
fails resolution.

See `spec-dev-validation.md` `req-dev-validation-smoke-gate` for the surface, and
the guard module's docstring for the 2026-07-02 samsite break that motivated it.

Registry-only (no DB): the resolve preflight mutates nothing.
"""

from __future__ import annotations

import pytest

from tap_boot.orchestrator import BootError, check_profile
from tap_boot.profile import BootProfile, FireCollectorStep, profile_ids


def test_shipped_profiles_discovered():
    """The house profiles are present, so the guard is non-empty.

    samsite is deliberately absent: its record re-homed into tap-plugin-samsite
    (req-boot-bootstrap-samsite-rehome) and its resolve coverage now lives in that
    plugin's shipped suite (test_boot_record_resolves), run by plugin CI.
    """
    ids = set(profile_ids())
    assert "core_ci" in ids, f"expected the core_ci profile; found {sorted(ids)}"


def test_guard_has_teeth_rotted_collector_key_fails():
    """The rot the guard exists to catch actually fails it (validate the validator).

    Reproduces the samsite break class: a well-formed profile whose
    fire-collector key uses the stale module-path scope instead of the
    registered `scope:key`. It parses fine but must not resolve.
    """
    rotted = BootProfile(
        profile_id="_teeth_check",
        version=1,
        description="synthetic rotted profile",
        on_failure="abort",
        steps=(
            FireCollectorStep(
                key="tap_plugin.fedramp_20x_ksi.collectors.ksi_catalog:ksi-catalog",
                enabled=True,
            ),
        ),
    )
    with pytest.raises(BootError):
        check_profile(rotted)
