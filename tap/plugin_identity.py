"""Plugin identity conventions — the three facts that name a plugin.

**This module must never import anything but the standard library.** It exists so the
plugin CONFORMANCE gate can answer "what should this plugin be called?" without dragging
in a runtime.

These constants used to live in `tap.preboot`, which is the right home conceptually but
the wrong one mechanically: importing `tap.preboot` pulls in `tap.plugin_source_auth` →
`tap.runtime_secrets` → `tap.registry` → Django. `tap_plugins.validate` needs only these
three symbols, and it runs in the per-repo CI conformance job on a bare runner with
`--with jsonschema --with packaging` and no Django installed — so one incidental import
edge turned "validate this plugin's layout" into `ModuleNotFoundError: No module named
'django'`, reported against the PLUGIN rather than against core.

That failure was invisible for as long as the workflow that would have caught it was
itself broken (it had never compiled). The Django-free property is now enforced by
`tap/tests/test_plugin_identity.py`, which imports the structure-validation path in a
subprocess with Django blocked, rather than merely asserted in a comment.

`tap.preboot` re-exports all three, so its public surface is unchanged.
"""

from __future__ import annotations

__all__ = [
    "NAMESPACE_PACKAGE",
    "TAP_PLUGINS_ENTRY_POINT_GROUP",
    "dist_name_for_slug",
]

# The entry-point group every package-mode plugin advertises itself under.
TAP_PLUGINS_ENTRY_POINT_GROUP = "tap.plugins"

# PEP 420 native namespace all package-mode plugins import under: tap_plugin.<slug>
# (singular, to avoid the plural `tap_plugins` management app). The conformance gate
# asserts every plugin's AppConfig lives here. See req-tap-plugin-arch-identity-3.
NAMESPACE_PACKAGE = "tap_plugin"


def dist_name_for_slug(slug: str) -> str:
    """Distribution name convention: ``tap-plugin-<slug>`` (PEP 503 normalized)."""
    return "tap-plugin-" + slug.replace("_", "-")
