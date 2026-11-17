"""TAP's plugin system.

The plugin data directory accessor is exported here, because it is the one name a plugin calls:
``tap_plugins.data_dir(slug)`` (`tap_plugins/specs/spec-tap-plugin-data-directory.md`,
`req-tap-plugin-datadir-accessor`). It is resolved lazily so that importing this package, which
Django does for every process, loads nothing until a plugin asks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def data_dir(slug: str) -> Path:
    """The canonical real path of plugin *slug*'s data directory; see :mod:`tap_plugins.datadir`."""
    from tap_plugins.datadir import data_dir as _data_dir

    return _data_dir(slug)


def data_dir_is_ephemeral(slug: str) -> bool:
    """Whether plugin *slug*'s directory is lost when the container is recreated."""
    from tap_plugins.datadir import data_dir_is_ephemeral as _is_ephemeral

    return _is_ephemeral(slug)


def __getattr__(name: str) -> Any:
    if name == "PluginDataDirectoryError":
        from tap_plugins.datadir import PluginDataDirectoryError

        return PluginDataDirectoryError
    raise AttributeError(f"module 'tap_plugins' has no attribute {name!r}")


__all__ = ["PluginDataDirectoryError", "data_dir", "data_dir_is_ephemeral"]
