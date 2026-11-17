"""The file store's backend instance, built from the configured root (`tap_files.config`).

`specs/spec-tap-file-store.md`, `req-tap-files-root` and `req-tap-files-interface`. Only the gateway
(`tap_files.services`), boot's initialisation and recovery, and the check command import this package
(`req-tap-files-gateway-5`, guard: files-backend-reach); everything else calls the gateway.
"""

from __future__ import annotations

from tap_files.config import ACCEPTED_BACKENDS, configured_backend, configured_root
from tap_files.store.errors import FileStoreNotEnabled
from tap_files.store.local import LocalBackend


def get_store() -> LocalBackend:
    """The store's backend, or :class:`FileStoreNotEnabled` when no root is configured.

    TAP-IMPLEMENTS: req-tap-files-root@5d8973c4f0c3/4d9645409e81 (derivation) — enabled exactly when the
        setting is set; unset raises one clear error and touches no path.
    """
    root = configured_root()
    if root is None:
        raise FileStoreNotEnabled("the file store is not enabled on this instance (TAP_FILES_ROOT is unset)")
    backend = configured_backend()
    if backend not in ACCEPTED_BACKENDS:
        raise FileStoreNotEnabled(f"TAP_FILES_BACKEND is {backend!r}; the only accepted value is 'local'")
    return LocalBackend(root)


__all__ = ["FileStoreNotEnabled", "get_store"]
