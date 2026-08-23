"""Best-effort runtime caller identity for detective (CONCERN) security signals.

Answers one question — "which plugin, if any, is on the call stack right now?" —
so a subsystem can emit a `CONCERN` (`spec-security-posture.md`, `req-sec-concern-gaps`)
when a plugin does something it should not, e.g. resolving another scope's secret.

It is a **detective** aid, never preventive, and deliberately **best-effort**:
package-mode plugins import under `tap_plugin.<slug>`, so a plugin's own code
carries its slug on the stack — but a determined plugin running arbitrary Python
can launder a call through a non-plugin module to erase that frame. That is an
accepted limitation: a missed detection is a missed tripwire, not a broken
invariant, so the module-path fragility that has bitten *durable-identity* code is
low-stakes here (we never derive a persistent key from this — only a log signal).

Stdlib only, no Django, no app imports, so it is safe to call from anywhere.
"""

from __future__ import annotations

import sys

from tap.plugin_identity import NAMESPACE_PACKAGE

# The PEP 420 namespace every package-mode plugin imports under: `tap_plugin.<slug>`.
# ONE home: tap.plugin_identity.NAMESPACE_PACKAGE — tap/preboot.py re-exports it and
# tap/plugin_deps.py aliases it, so this is that same constant, not a copy. Used here
# only for a best-effort stack read, never for identity derivation.
_PLUGIN_NAMESPACE = NAMESPACE_PACKAGE


def calling_plugin_slug() -> str | None:
    """Return the slug of the nearest plugin on the call stack, or ``None``.

    Walks outward from this function's caller and returns the ``<slug>`` of the
    first frame whose module is under ``tap_plugin.<slug>``. Returns ``None`` when
    no plugin frame is present (a framework/core/test caller), which a tripwire
    reads as "not a plugin call" — no signal.

    Best-effort by construction (see module docstring): stack-based and evadable.
    Uses ``sys._getframe`` (CPython) for a cheap walk that reads no source lines.
    """
    frame: object | None = sys._getframe(1)  # this function's caller
    while frame is not None:
        module = frame.f_globals.get("__name__", "")  # type: ignore[attr-defined]
        slug = _slug_from_module(module)
        if slug is not None:
            return slug
        frame = frame.f_back  # type: ignore[attr-defined]
    return None


def _slug_from_module(module: str) -> str | None:
    """Extract ``<slug>`` from a ``tap_plugin.<slug>...`` module name, else ``None``."""
    prefix = f"{_PLUGIN_NAMESPACE}."
    if not module.startswith(prefix):
        return None
    slug = module[len(prefix) :].split(".", 1)[0]
    return slug or None


__all__ = ["calling_plugin_slug"]
