"""Plugin data directories: a sub-grid working directory per plugin, owned by core.

`tap_plugins/specs/spec-tap-plugin-data-directory.md`. A plugin declares ``[data_directory]`` in its
manifest; core provisions ``<root>/<slug>/`` on the mounted plugin data volume or, for a cache with
no volume enabled, under an ephemeral root; the plugin asks :func:`tap_plugins.data_dir` for the
path and uses ordinary file calls inside it; core reports what is there and deletes nothing unless
an operator purges it.

Plugins import the accessor from ``tap_plugins`` itself; everything else here is core's.
"""

from tap_plugins.datadir._api import PluginDataGateError, data_dir, data_dir_is_ephemeral, on_plugin_loaded, run_gate
from tap_plugins.datadir._placement import PluginDataDirectoryError

__all__ = [
    "PluginDataDirectoryError",
    "PluginDataGateError",
    "data_dir",
    "data_dir_is_ephemeral",
    "on_plugin_loaded",
    "run_gate",
]
