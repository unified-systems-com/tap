"""The file store's boot step: the mount gate, initialisation, then recovery (`req-tap-files-mount-gate`).

|                          | no installed plugin requires the store | a plugin requires it      |
| store not enabled        | boots                                  | aborts, naming the plugin |
| store enabled, usable    | boots                                  | boots                     |
| store enabled, broken    | aborts                                 | aborts                    |

The "a plugin requires it" column arrives with the `[file_store]` manifest table (tap#1209). A
configured store is never optional: an operator who configured a volume and did not get one must
hear about it. "Usable" is the one mount test the plugin data directory also uses.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tap.volume_mount import check_volume

logger = logging.getLogger(__name__)


class FileStoreGateError(Exception):
    """Boot must not continue: the message names the root and the failed check."""


def run_gate(say: Any = None) -> dict[str, Any]:
    """Gate, initialise and recover the store; raise :class:`FileStoreGateError` to abort boot.

    TAP-IMPLEMENTS: req-tap-files-mount-gate@74744dced61b/877821a9b2a6 (enforcement) — the standup refuses
        here when a configured store is not a mounted, writable volume or holds foreign content.
    """
    from tap_files.store import configured_root, get_store
    from tap_files.store.errors import StoreRootRefused
    from tap_plugins.datadir._placement import volume_root as plugin_data_root

    echo = say or (lambda _msg: None)
    root = configured_root()
    if root is None:
        echo("File store: not enabled (TAP_FILES_ROOT unset).")
        return {"enabled": False}
    other = plugin_data_root()
    if other is not None:
        mine, theirs = os.path.realpath(root), os.path.realpath(other)
        if mine == theirs or mine.startswith(theirs + os.sep) or theirs.startswith(mine + os.sep):
            raise FileStoreGateError(
                f"file store root {root} and plugin data root {other} are the same directory or one "
                "contains the other; they must be separate volumes"
            )
    verdict = check_volume(root)
    if not verdict.usable:
        raise FileStoreGateError(f"file store root {root} failed the mount test ({verdict.check}): {verdict.reason}")
    store = get_store()
    try:
        state = store.initialise()
    except StoreRootRefused as exc:
        raise FileStoreGateError(str(exc)) from exc
    actions = store.recover()
    for action in actions:
        logger.warning("[2983] files: boot recovery: %s", action)
    echo(f"File store: {root} is a mounted, writable volume ({state}); recovery made {len(actions)} change(s).")
    return {"enabled": True, "state": state, "recovered": actions}


__all__ = ["FileStoreGateError", "run_gate"]
