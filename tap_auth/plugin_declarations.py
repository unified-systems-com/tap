"""Locate the authorization files installed plugins declare (req-tap-auth-plugin-declarations).

A plugin may ship two files beside its ``tap-plugin.toml``, in the package root
``tap_plugin/<slug>/``:

- ``<slug>.capabilities.json``: capabilities named ``<slug>.<action>``, same schema as
  ``tap_auth/tap_auth.capabilities.json``.
- ``<slug>.roles.json``: human roles named ``<slug>.<role>`` that bundle only the plugin's
  own capabilities, same schema as ``tap_auth/tap_auth.roles.json``.

This module only finds the files. ``tap_auth.capabilities`` and ``tap_auth.roles`` load and
confine them. It reads ``settings.INSTALLED_APPS`` and asks the import system where each
``tap_plugin.<slug>`` package lives; it never imports plugin code, so it is safe at the
import time of the registries, after settings are configured and before the app registry
is ready.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from tap.plugin_identity import NAMESPACE_PACKAGE, valid_slug

CAPABILITIES_SUFFIX = ".capabilities.json"
ROLES_SUFFIX = ".roles.json"


@dataclass(frozen=True)
class PluginAuthFiles:
    """The authorization files one installed plugin declares; a path is None when absent."""

    slug: str
    capabilities_path: Path | None
    roles_path: Path | None


def installed_plugin_slugs() -> tuple[str, ...]:
    """The slugs of the ``tap_plugin.<slug>`` apps in ``INSTALLED_APPS``, in install order.

    An entry may be the package (``tap_plugin.aws_core``) or its AppConfig path
    (``tap_plugin.aws_core.apps.AwsCoreConfig``); both name the slug in the second segment.
    """
    slugs: list[str] = []
    for entry in settings.INSTALLED_APPS:
        parts = entry.split(".")
        if len(parts) < 2 or parts[0] != NAMESPACE_PACKAGE:
            continue
        slug = parts[1]
        if not valid_slug(slug):
            raise ImproperlyConfigured(f"INSTALLED_APPS entry '{entry}' does not name a valid plugin slug")
        if slug not in slugs:
            slugs.append(slug)
    return tuple(slugs)


def _package_dir(slug: str) -> Path:
    """Filesystem directory of the installed ``tap_plugin.<slug>`` package.

    Fails loud when the package cannot be located: an installed app whose directory is
    unknown would otherwise drop its declarations without a word.
    """
    spec = importlib.util.find_spec(f"{NAMESPACE_PACKAGE}.{slug}")
    locations = list(spec.submodule_search_locations or []) if spec is not None else []
    if len(locations) != 1:
        raise ImproperlyConfigured(
            f"plugin '{slug}' is in INSTALLED_APPS but its package directory could not be located "
            f"(found {len(locations)} locations); its authorization files cannot be read"
        )
    return Path(locations[0])


def plugin_auth_files() -> tuple[PluginAuthFiles, ...]:
    """The declaration files of every installed plugin that ships at least one of them."""
    found: list[PluginAuthFiles] = []
    for slug in installed_plugin_slugs():
        package = _package_dir(slug)
        capabilities = package / f"{slug}{CAPABILITIES_SUFFIX}"
        roles = package / f"{slug}{ROLES_SUFFIX}"
        entry = PluginAuthFiles(
            slug=slug,
            capabilities_path=capabilities if capabilities.is_file() else None,
            roles_path=roles if roles.is_file() else None,
        )
        if entry.capabilities_path is not None or entry.roles_path is not None:
            found.append(entry)
    return tuple(found)
