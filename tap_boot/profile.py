"""Boot-profile loading, schema validation, and parsing.

TAP-IMPLEMENTS: req-boot-profile@34f12de6a606/28dd5b575542 (derivation) — profile resolution,
    schema validation and parsing into the runtime model happen here.

TAP-IMPLEMENTS: req-boot-required-secrets@ac62eedc2788/28dd5b575542 (derivation) — the
    declared-secret-requirements model and its Rule A resolution live here.

The bootloader owns profile handling (req-boot-app): this module resolves a
profile id to its `boot/<id>.boot.json` file, validates it against the boot-profile
JSON Schema (shape only — semantic pre-resolution of plugin/collector keys
happens in the population phase, req-boot-population-4), and parses it into a
typed `BootProfile`. The richer app-owned multi-section composition is deferred
(req-boot-sections); v0 reads the single `population` section directly.

Spec: specs/spec-tap-boot-v0.md (req-boot-profile).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

from tap.boot_naming import profile_path, step_enabled
from tap.jsonfiles import JsonFileError, discover_json_files, instance_id, load_json_file

# Declared public surface. tap_boot.profile is the boot-profile *contract* (the
# schema types + loaders) that the boot commands and orchestrator consume — a small,
# legitimately-public API. Declared explicitly and frozen by the Family-B public-surface
# ceiling ratchet (tap/guards/public_surface.py); `_parse` and friends stay sealed.
__all__ = [
    "BootProfileError",
    "SeedPluginStep",
    "FireCollectorStep",
    "RequiredSecret",
    "BootProfile",
    "PopulationStep",
    "DEFAULT_ON_FAILURE",
    "boot_dir",
    "profile_ids",
    "profile_install_slugs",
    "installable_profile_ids",
    "load_profile",
]

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "boot.schema.json"

# Profile-level default when the population section omits `on_failure`. Abort is
# the safe default: a half-populated standup should fail loud, not look healthy.
DEFAULT_ON_FAILURE = "abort"


class BootProfileError(Exception):
    """Raised when a profile cannot be found, read, or validated."""


@dataclass(frozen=True)
class SeedPluginStep:
    """A `seed-plugin` population step (req-boot-population-2)."""

    plugin: str
    enabled: bool
    bundle: str | None = None
    note: str = ""

    type: str = "seed-plugin"


@dataclass(frozen=True)
class RequiredSecret:
    """One declared secret requirement (req-boot-required-secrets-1).

    Exactly the envelope identity — scope/key/kind — plus the least-privilege
    `note`. References only, never values (req-boot-secrets).
    """

    scope: str
    key: str
    kind: str
    note: str

    @property
    def ref(self) -> str:
        """The bare ``scope:key`` form population steps reference this entry by."""
        return f"{self.scope}:{self.key}"


@dataclass(frozen=True)
class FireCollectorStep:
    """A `fire-collector` population step (req-boot-population-2)."""

    key: str
    enabled: bool
    run_mode: str = "full"
    # Seconds to await this collector's job to a terminal state. None ⇒ the
    # bootloader's default (DEFAULT_COLLECTOR_TIMEOUT_SECONDS). Slow collectors
    # (a full cloud pull) declare a higher value here.
    timeout_seconds: int | None = None
    note: str = ""
    # Bare "scope:key" references into the profile's required_secrets manifest
    # (req-boot-required-secrets-2). Strings, not objects, by design.
    secrets: tuple[str, ...] = ()

    type: str = "fire-collector"


PopulationStep = SeedPluginStep | FireCollectorStep


@dataclass(frozen=True)
class BootProfile:
    profile_id: str
    version: int
    description: str
    on_failure: str
    steps: tuple[PopulationStep, ...]
    # Raw `population.collector_preflight` value, when the profile declares one.
    # None = not declared; the orchestrator resolves the effective value via the
    # boot-variable ladder (env > profile > default true, req-boot-obs-preflight-4).
    collector_preflight: bool | None = None
    # Raw auth section (req-tap-auth-boot). tap_auth owns its schema fragment and
    # validates it strictly in the boot auth phase; the bootloader only carries it.
    auth: dict[str, Any] | None = None
    # Deployment-context classification, orthogonal to the plugin set. None = unclassified.
    # Fail-closed guards (e.g. the dev-passkey import gate, req-tap-auth-passkey-dev-bootstrap-4)
    # allowlist off an EXPLICIT value; it only tightens, never the DEBUG posture selector.
    profile_kind: str | None = None
    # Declared secret requirements (req-boot-required-secrets). Kept coherent with
    # the steps' `secrets` refs by _validate_secret_coherence at load.
    required_secrets: tuple[RequiredSecret, ...] = ()

    @property
    def has_population(self) -> bool:
        return bool(self.steps)

    @property
    def has_auth(self) -> bool:
        return bool(self.auth)

    @property
    def enabled_steps(self) -> tuple[PopulationStep, ...]:
        return tuple(s for s in self.steps if s.enabled)


def boot_dir() -> Path:
    """Top-level ``boot/`` directory holding profile data files."""
    return Path(settings.BASE_DIR) / "boot"


def profile_ids() -> list[str]:
    return [instance_id(p, role="boot") for p in discover_json_files(boot_dir(), role="boot")]


def profile_install_slugs(profile_id: str) -> frozenset[str]:
    """The enabled ``install.plugins[].slug`` set a profile brings into the stack.

    Read from ``boot/<id>.boot.json`` schema-validated (the parsed ``BootProfile``
    models *population* steps, not *install* steps; validating here too closes the
    raw-read divergence a spawn-supplied unvalidated profile could hit). This is the atom of install-awareness:
    a profile only resolves/boots in a stack that already has all these plugins.
    """
    raw = load_json_file(profile_path(boot_dir(), profile_id), schema=_SCHEMA_PATH)
    plugins = raw.get("install", {}).get("plugins", [])
    return frozenset(p["slug"] for p in plugins if step_enabled(p))


def installable_profile_ids(installed: Collection[str]) -> list[str]:
    """Shipped profile ids whose install plugins are all present in ``installed``.

    The single install-awareness point shared by every promote surface that resolves
    profiles: the pytest ``ProfileResolutionGuard``, the cold-boot gate's
    ``profiles:resolve`` step, and the promote's own "is this the full stack?" check
    (``"test_all" in installable_profile_ids(...)``). A focused session holds a plugin
    subset (``core_dev`` = just ``grid_fixtures``), so a profile that installs an absent
    plugin (``samsite`` → ``administrivia``/…) is not installable here; the all-plugins
    CI lane installs the full ``test_all`` union and owns full-set truth
    (``req-dev-validation-all-plugins-lane``). Keeping the filter in one place stops the
    surfaces from drifting apart.
    """
    have = set(installed)
    return [pid for pid in profile_ids() if profile_install_slugs(pid) <= have]


def load_profile(profile_id: str) -> BootProfile:
    """Load, schema-validate, and parse ``boot/<profile_id>.boot.json``.

    Raises `BootProfileError` (loud, machine-readable) on a missing file, unreadable
    JSON, or schema-validation failure — never returns a malformed profile.
    """
    path = profile_path(boot_dir(), profile_id)
    if not path.is_file():
        available = ", ".join(profile_ids()) or "(none)"
        raise BootProfileError(f"Boot profile '{profile_id}' not found at {path}. Available: {available}.")

    try:
        data = load_json_file(path, schema=_SCHEMA_PATH)
    except JsonFileError as exc:
        raise BootProfileError(f"Boot profile '{profile_id}': {exc}") from exc

    return _parse(profile_id, data)


def _parse(profile_id: str, data: dict[str, Any]) -> BootProfile:
    population = data.get("population") or {}
    steps: list[PopulationStep] = []
    for raw in population.get("steps", []):
        if raw["type"] == "seed-plugin":
            steps.append(
                SeedPluginStep(
                    plugin=raw["plugin"],
                    enabled=raw["enabled"],
                    bundle=raw.get("bundle"),
                    note=raw.get("note", ""),
                )
            )
        else:  # schema's oneOf guarantees the only other type is fire-collector
            steps.append(
                FireCollectorStep(
                    key=raw["key"],
                    enabled=raw["enabled"],
                    run_mode=raw.get("run_mode", "full"),
                    timeout_seconds=raw.get("timeout_seconds"),
                    note=raw.get("note", ""),
                    secrets=tuple(raw.get("secrets", [])),
                )
            )

    profile = BootProfile(
        profile_id=profile_id,
        version=data["version"],
        description=data.get("description", ""),
        on_failure=population.get("on_failure", DEFAULT_ON_FAILURE),
        steps=tuple(steps),
        collector_preflight=population.get("collector_preflight"),
        auth=data.get("auth"),
        profile_kind=data.get("profile_kind"),
        required_secrets=tuple(
            RequiredSecret(scope=e["scope"], key=e["key"], kind=e["kind"], note=e["note"])
            for e in data.get("required_secrets", [])
        ),
    )
    _validate_secret_coherence(profile)
    return profile


def _validate_secret_coherence(profile: BootProfile) -> None:
    """The two fail-loud rules keeping the dual declaration a checksum, not a drift point.

    Rule A (req-boot-required-secrets-3): every ENABLED step's secret ref resolves to a
    ``required_secrets`` entry. Enabled-scoped deliberately: rule B forces removing the
    entry when its last consuming step is disabled, so the disabled step's dangling ref
    must not itself invalidate the profile — re-enabling the step is what re-demands the
    entry (and fails loud until it is restored).

    Rule B (req-boot-required-secrets-4): every entry is referenced by ≥1 enabled step —
    a stale entry (nothing enabled consumes it) invalidates the profile, so disabling a
    step mechanically drops its requirement.
    """
    declared = {entry.ref for entry in profile.required_secrets}
    if len(declared) != len(profile.required_secrets):
        dupes = sorted(
            {e.ref for e in profile.required_secrets if sum(x.ref == e.ref for x in profile.required_secrets) > 1}
        )
        raise BootProfileError(
            f"Boot profile '{profile.profile_id}': duplicate required_secrets entr(y/ies): {', '.join(dupes)}."
        )

    referenced: set[str] = set()
    for step in profile.enabled_steps:
        refs = getattr(step, "secrets", ())
        for ref in refs:
            referenced.add(ref)
            if ref not in declared:
                raise BootProfileError(
                    f"Boot profile '{profile.profile_id}': step '{_step_name(step)}' references secret "
                    f"'{ref}' but required_secrets declares no such entry (req-boot-required-secrets-3). "
                    "Add the entry (scope/key/kind + least-privilege note)."
                )

    stale = sorted(declared - referenced)
    if stale:
        raise BootProfileError(
            f"Boot profile '{profile.profile_id}': required_secrets entr(y/ies) referenced by no enabled "
            f"step: {', '.join(stale)} (req-boot-required-secrets-4). Remove the stale entr(y/ies) — "
            "disabling a step drops its requirement."
        )


def _step_name(step: PopulationStep) -> str:
    if isinstance(step, FireCollectorStep):
        return f"fire-collector:{step.key}"
    return f"seed-plugin:{step.plugin}"
