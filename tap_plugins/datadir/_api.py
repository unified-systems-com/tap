"""The accessor, the boot gate and the load hook for plugin data directories.

`tap_plugins/specs/spec-tap-plugin-data-directory.md`. A plugin learns its directory from one
function, :func:`data_dir`, which creates nothing. Boot decides and provisions (:func:`run_gate`),
refusing loudly; a process that loads a declaring plugin (:func:`on_plugin_loaded`) takes the
plugin's shared lock and provisions too, but never raises, because refusing at ``django.setup()``
would crash-loop the instance and take away the tools an operator needs to diagnose it
(`req-tap-cares-secrets-resilient-load`). The accessor independently refuses at the moment a plugin
asks, which covers a process started without boot.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

from tap_plugins.datadir import _lock, _placement, _provision
from tap_plugins.datadir._placement import PluginDataDirectoryError

logger = logging.getLogger(__name__)


def _declaration(slug: str) -> Any:
    declared = _placement.declared_directories()
    if slug not in declared:
        raise PluginDataDirectoryError(f"no installed plugin with slug {slug!r} declares a [data_directory] table")
    return declared[slug][0]


def _resolve(slug: str) -> _placement.Placement:
    _provision.check_slug(slug)
    placement = _placement.place(slug, _declaration(slug).durability)
    if placement.root is None:
        raise PluginDataDirectoryError(placement.refusal)
    return placement


def data_dir(slug: str) -> Path:
    """The canonical real path of plugin *slug*'s data directory.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-accessor@d47b8d5352b3/dd3fee3491c4 (surface) — the only way a
        plugin learns where its directory is; plugins ask, they do not derive.

    Raises :class:`PluginDataDirectoryError` when the slug is invalid (before any filesystem call),
    when no installed plugin with that slug declares a directory, when a configured volume fails
    its test, or when the directory has not been provisioned. Creates nothing. One canonical
    spelling matters for SQLite, which treats two path names for one database as two databases.
    """
    placement = _resolve(slug)
    path = placement.path
    assert path is not None  # nosec B101 — a placement with a root has a path
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PluginDataDirectoryError(
            f"the data directory for plugin {slug!r} has not been provisioned at {path}; boot provisions it"
        ) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PluginDataDirectoryError(f"the data directory for plugin {slug!r} at {path} {_provision.describe(path)}")
    return path.resolve(strict=True)


def data_dir_is_ephemeral(slug: str) -> bool:
    """Whether plugin *slug*'s directory is under the ephemeral root, lost when the container is recreated."""
    return _resolve(slug).ephemeral


def on_plugin_loaded(slug: str, declaration: Any, plugin_version: str) -> None:
    """Take the plugin's shared lock and provision its directory; log, never raise.

    Called from :meth:`TapPluginConfig.ready` for a plugin that declares a directory. Taking the
    lock first is what makes a process starting during a purge wait for it and then find a fresh,
    empty directory rather than a half-deleted one.
    """
    try:
        placement = _placement.place(slug, declaration.durability)
        if placement.root is None:
            logger.warning("[7998] plugin data: %s not provisioned at load: %s", slug, placement.refusal)
            return
        if placement.ephemeral:
            placement.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _lock.hold_shared(placement.root, slug)
        _provision.provision(placement.root, slug, declaration, plugin_version, ephemeral=placement.ephemeral)
    except Exception as exc:  # noqa: BLE001 — a load must never fail here; boot and the accessor refuse.
        logger.warning("[3cb4] plugin data: %s not provisioned at load: %s", slug, exc)


class PluginDataGateError(Exception):
    """The mount gate refused boot. The message names the root, the check and, where one caused it, the plugin."""


def run_gate(say: Any = None) -> list[dict[str, Any]]:
    """The boot step: apply the mount gate, provision every declared directory, prove execution.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-mount-gate@eecebe74cbaa/accb35658547 (enforcement) — the
        standup refuses here when what the plugins need and what the instance provides disagree.

    Raises :class:`PluginDataGateError` on the first refusal. A configured volume that is unusable
    aborts whoever is installed; a ``"state"`` declaration with no volume aborts naming the plugin;
    a cache with no volume goes under the ephemeral root, and never because an enabled volume failed.
    Returns one record per provisioned directory.
    """
    echo = say or (lambda _msg: None)
    verdict = _placement.volume_verdict(fresh=True)
    root = _placement.volume_root()
    if verdict is not None and not verdict.usable:
        raise PluginDataGateError(_placement.volume_refusal(root, verdict))
    declared = _placement.declared_directories()
    if verdict is None:
        echo("Plugin data volume: not enabled (TAP_PLUGIN_DATA_ROOT unset).")
    else:
        echo(f"Plugin data volume: {root} is a mounted, writable volume.")
    records: list[dict[str, Any]] = []
    for slug, (declaration, plugin_version) in declared.items():
        placement = _placement.place(slug, declaration.durability)
        if placement.root is None:
            raise PluginDataGateError(placement.refusal)
        if placement.ephemeral:
            placement.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _lock.hold_shared(placement.root, slug)
        try:
            path = _provision.provision(
                placement.root, slug, declaration, plugin_version, ephemeral=placement.ephemeral
            )
        except PluginDataDirectoryError as exc:
            raise PluginDataGateError(f"plugin {slug!r}: {exc}") from exc
        if declaration.executes:
            failure = _provision.prove_execution(path)
            if failure:
                raise PluginDataGateError(
                    f"plugin {slug!r} declares executes = true, and programs cannot run from {path}: {failure}"
                )
        where = "ephemeral" if placement.ephemeral else "volume"
        echo(f"  {slug}: {declaration.durability} directory at {path} ({where}).")
        logger.info("[d1e9] plugin data: provisioned %s at %s (%s, %s)", slug, path, declaration.durability, where)
        records.append({"slug": slug, "path": str(path), "durability": declaration.durability, "location": where})
    return records


__all__ = ["PluginDataGateError", "data_dir", "data_dir_is_ephemeral", "on_plugin_loaded", "run_gate"]
