"""Per-profile boot-resolution guard — `req-dev-validation-smoke-gate` + `spec-tap-boot-v0.md`.

Every shipped `boot/*.boot.json` profile's enabled steps must resolve against the
live registries: each `seed-plugin` slug/bundle and each `fire-collector` `scope:key`
names something actually registered. A rotted key is well-formed JSON, so the
schema-parse tests can't catch it — this resolves the *values*, the layer that
rotted in the 2026-07-02 samsite break (module-path→slug fire-collector drift that
silently broke the live-demo profile while `base` stayed green).

`check_profile` runs the zero-mutation resolve preflight (no DB write), so this is a
structural guard, not a ratchet. It also runs inside the pre-boot gate per profile;
here it fires per-commit across every shipped profile, before any spawn.
"""

from __future__ import annotations

from tap.guards.base import Guard


class ProfileResolutionGuard(Guard):
    slug = "per-profile-boot-resolution"
    map_row = "Per-profile boot resolution"
    rid = "req-dev-validation-smoke-gate"
    cadence = "Per-commit (`pytest`) + pre-push (`cold_boot_gate`)"
    status = "CI-guarded + Gate-guarded"
    description = (
        "A fire-collector key or seed-plugin slug that has drifted from what's registered makes a boot "
        "profile abort at resolution — the samsite live-demo break, invisible to schema-parse tests "
        "because rotted JSON is still well-formed. This resolves every shipped profile's enabled steps "
        "against the live registries (zero-mutation), so the rot fails in CI instead of at the next spawn."
    )

    def check(self) -> None:
        from tap.plugin_testing import installed_plugin_slugs
        from tap_boot.orchestrator import BootError, check_profile
        from tap_boot.profile import installable_profile_ids, load_profile, profile_ids

        assert profile_ids(), "no shipped boot profiles discovered — the guard would cover nothing"

        # Install-aware via the shared filter: a focused session holds a plugin subset
        # (core_dev = just grid_fixtures), so a profile referencing an absent plugin
        # (samsite → administrivia/…) is SKIPPED here, not failed — the all-plugins CI
        # lane resolves the full set and owns full-set truth. The `needs <= installed`
        # logic lives once in tap_boot.profile.installable_profile_ids so this guard, the
        # cold-boot gate, and the promote's full-stack check cannot drift apart.
        failures: list[str] = []
        for profile_id in installable_profile_ids(installed_plugin_slugs()):
            try:
                check_profile(load_profile(profile_id))
            except BootError as exc:
                failures.append(f"  {profile_id}: {exc}")

        assert not failures, (
            "Shipped boot profile(s) do not resolve against the registries — a fire-collector key or "
            "seed-plugin slug/bundle has drifted from what is registered (the module-path→slug rot "
            "class). Fix the profile in boot/<id>.boot.json:\n" + "\n".join(failures)
        )
