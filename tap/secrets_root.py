"""The settings-free canonical lookup of the TAP secrets root.

req-tap-cares-secrets-root-resolution (tap_cares/specs/spec-tap-cares-secrets.md):
``TAP_SECRETS_ROOT`` has exactly two canonical lookups, one per world. Inside
Django it is ``settings.TAP_SECRETS_ROOT`` — settings.py's normal env-projection
style, carrying the container-mount default. Outside Django (pre-boot, the
stage-0 host tools, mid-settings-import moments) it is this module: the env-var
name and the read live here, and **nothing else** — no default. Each
settings-free caller applies its own documented unset-policy at its own edge:
preboot proceeds with "no credential store", the auth providers raise, and
boot_pointer falls back to its GnuPG-style host default (``~/tap-secrets``,
whose literal lives only there).

Stdlib-only and import-safe (the ``tap/runtime_secrets.py`` discipline): safe to
import from preboot, from ``python3 -m tap.boot_pointer`` on a bare host, and
during settings initialization.
"""

from __future__ import annotations

import os
from pathlib import Path

# TAP-KNOWN-DUPE(secrets-root): the in-Django partner lookup is settings.TAP_SECRETS_ROOT
# (tap/settings.py, house env-projection style with the container-mount default) — this side
# exists because settings-free callers cannot import settings
# (req-tap-cares-secrets-root-resolution). Editing this means putting eyes on the partner.
ENV_VAR = "TAP_SECRETS_ROOT"


def resolve() -> Path | None:
    """The secrets root from the environment, or None when unset/empty.

    TAP-IMPLEMENTS: req-tap-cares-secrets-root-resolution@734ab0234c10/f37d20dd40dc (derivation) — the
        one place the environment is consulted for the secrets root. Five entry points
        previously each decided where to look, so a credential could resolve from a
        different directory depending on which one you came in through.

    No default on purpose: the supervised-runtime default (the container mount
    path) belongs to settings.py's env projection, and the host-tool default
    (``~/tap-secrets``) belongs to boot_pointer. A None here means the calling
    context must decide what "no store" means for it.
    """
    raw = os.environ.get(ENV_VAR)
    return Path(raw) if raw else None
