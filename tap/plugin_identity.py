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

`tap.preboot` re-exports the original three, so its public surface is unchanged.
"""

from __future__ import annotations

import importlib.metadata
import re
from collections.abc import Callable

__all__ = [
    "DIST_SUFFIX",
    "SLUG_ALPHABET_PATTERN",
    "LEGACY_DIST_PREFIX",
    "NAMESPACE_PACKAGE",
    "TAP_PLUGINS_ENTRY_POINT_GROUP",
    "dist_name_for_slug",
    "dist_names_for_slug",
    "installed_plugin_dist_name",
    "is_plugin_dist_name",
    "legacy_dist_name_for_slug",
    "normalized_dist_name",
    "valid_slug",
]

# The plugin slug alphabet. Lowercase, digits and underscore only — the intersection
# of what a Python identifier segment allows (``tap_plugin.<slug>`` must import) and
# what folds cleanly to a PEP 503 distribution name (``<slug>-tap``, ``_`` → ``-``).
#
# TAP-KNOWN-DUPE(plugin-slug-alphabet): the partner is the ``pattern`` on
# ``install.plugins[].slug`` in ``tap_boot/schemas/boot.schema.json``. JSON Schema is
# static data and cannot read a Python constant, and the pre-Django reader
# (``tap.preboot``) cannot run a schema — so the alphabet is spelled in exactly these
# two places and nowhere else. Changing one means changing the other.
SLUG_ALPHABET_PATTERN = r"[a-z0-9_]+"
_SLUG_RE = re.compile(rf"\A{SLUG_ALPHABET_PATTERN}\Z")


def valid_slug(slug: object) -> bool:
    """True if *slug* is a well-formed plugin slug.

    The alphabet used to be asserted in a comment ("slug alphabet is [a-z0-9_]") while
    nothing checked it, and the value flowed from a boot profile into subprocess
    argument lists, log records and distribution-name derivation unvalidated. A
    declaration that exists but is not enforced is the defect.
    """
    return isinstance(slug, str) and _SLUG_RE.match(slug) is not None


# The entry-point group every package-mode plugin advertises itself under.
TAP_PLUGINS_ENTRY_POINT_GROUP = "tap.plugins"

# PEP 420 native namespace all package-mode plugins import under: tap_plugin.<slug>
# (singular, to avoid the plural `tap_plugins` management app). The conformance gate
# asserts every plugin's AppConfig lives here. See req-tap-plugin-arch-identity-3.
NAMESPACE_PACKAGE = "tap_plugin"


# Distribution-name convention (req-tap-plugin-arch-identity-2). Since 2026-08-26 the
# convention is the ``<slug>-tap`` SUFFIX (``git-serious-tap``, ``aws-core-tap``): TAP is the
# base layer, not the over-arching capability, so the name reads as the adjective it is
# ("for TAP") — the Maven ``<name>-maven-plugin`` shape. The original ``tap-plugin-<slug>``
# PREFIX is LEGACY: still accepted by every gate (installed plugins keep booting) but
# deprecated, and retired by the rename wave (tap#147) once the existing distributions
# have moved. The slug and the import namespace never change — only distributions and
# repos carry the convention.
DIST_SUFFIX = "-tap"
LEGACY_DIST_PREFIX = "tap-plugin-"


def _dashed(slug: str) -> str:
    return slug.replace("_", "-")


def dist_name_for_slug(slug: str) -> str:
    """The preferred distribution name for a slug: ``<slug-dashed>-tap`` (PEP 503 form)."""
    return _dashed(slug) + DIST_SUFFIX


def legacy_dist_name_for_slug(slug: str) -> str:
    """The deprecated pre-2026-08-26 distribution name: ``tap-plugin-<slug-dashed>``."""
    return LEGACY_DIST_PREFIX + _dashed(slug)


def dist_names_for_slug(slug: str) -> tuple[str, str]:
    """Every distribution name a slug may be installed under, preferred first.

    The one derivation of "which distributions can carry this slug": the pre-boot gates,
    the author-time validator, the plugin report, and the release SBOM lane all resolve
    through this tuple rather than re-deriving the convention.
    """
    return (dist_name_for_slug(slug), legacy_dist_name_for_slug(slug))


def normalized_dist_name(name: str) -> str:
    """PEP 503 normalization — the form under which names collide on an index."""
    return re.sub(r"[-_.]+", "-", name).lower()


def slug_for_dist_name(name: str) -> str | None:
    """The slug a plugin-shaped distribution (or repository) name carries, or None.

    The inverse of `dist_names_for_slug`, and the one derivation of "which plugin is this
    repo": `git-serious-tap` -> `git_serious`, `tap-plugin-github-core` -> `github_core`.
    Names that carry neither convention — `tap` itself, `tapestry`, `my-tap-plugin` — yield
    None, so a roster built on this cannot admit the core repo or a stranger. The nightly
    skew detector calls this from a checkout rather than restating the suffix/prefix in jq
    (tap#309: the jq restatement rostered `tap-plugin-*` only, and every `*-tap` repo was
    invisible to it).
    """
    normalized = normalized_dist_name(name)
    if normalized.endswith(DIST_SUFFIX) and len(normalized) > len(DIST_SUFFIX):
        body = normalized[: -len(DIST_SUFFIX)]
    elif normalized.startswith(LEGACY_DIST_PREFIX) and len(normalized) > len(LEGACY_DIST_PREFIX):
        body = normalized[len(LEGACY_DIST_PREFIX) :]
    else:
        return None
    slug = body.replace("-", "_")
    return slug if valid_slug(slug) else None


def is_plugin_dist_name(name: str) -> bool:
    """True if ``name`` carries either plugin-distribution convention (PEP 503-compared).

    The reservation the release lane enforces: a non-plugin distribution can never mint a
    plugin-shaped identity, under the new suffix OR the legacy prefix.
    """
    normalized = normalized_dist_name(name)
    return normalized.endswith(DIST_SUFFIX) or normalized.startswith(LEGACY_DIST_PREFIX)


def _is_installed(dist_name: str) -> bool:
    try:
        importlib.metadata.distribution(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def installed_plugin_dist_name(slug: str, *, is_installed: Callable[[str], bool] | None = None) -> str | None:
    """The distribution name a slug is actually installed under, or None if it is not.

    Preferred convention first, legacy second — the one place that loop lives. ``is_installed``
    is injectable so pre-boot can route through its own distribution lookup (and tests can
    fake it); the default asks ``importlib.metadata``.
    """
    check = is_installed or _is_installed
    for name in dist_names_for_slug(slug):
        if check(name):
            return name
    return None
