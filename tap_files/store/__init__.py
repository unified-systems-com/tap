"""The file store's entry point: whether it is enabled, and the one backend instance.

`specs/spec-tap-file-store.md`, `req-tap-files-root` and `req-tap-files-interface`. The only reader of
the `TAP_FILES_ROOT` setting outside `tap/settings.py` (guard: files-root-resolution). Callers outside
this package reach the store through the gateway (tap#1209), never by building a path.
"""

from __future__ import annotations

from pathlib import Path

from tap_files.store.errors import FileStoreNotEnabled
from tap_files.store.local import LocalBackend

ACCEPTED_BACKENDS = ("local",)


def configured_root() -> Path | None:
    """The configured store root, or ``None`` when the file store is not enabled."""
    from django.conf import settings

    raw = getattr(settings, "TAP_FILES_ROOT", "") or ""
    return Path(raw) if raw else None


def configured_backend() -> str:
    from django.conf import settings

    return str(getattr(settings, "TAP_FILES_BACKEND", "local") or "local")


def get_store() -> LocalBackend:
    """The store's backend, or :class:`FileStoreNotEnabled` when no root is configured.

    TAP-IMPLEMENTS: req-tap-files-root@1c946c69db7b/4d9645409e81 (derivation) — enabled exactly when the
        setting is set; unset raises one clear error and touches no path.
    """
    root = configured_root()
    if root is None:
        raise FileStoreNotEnabled("the file store is not enabled on this instance (TAP_FILES_ROOT is unset)")
    backend = configured_backend()
    if backend not in ACCEPTED_BACKENDS:
        raise FileStoreNotEnabled(f"TAP_FILES_BACKEND is {backend!r}; the only accepted value is 'local'")
    return LocalBackend(root)


__all__ = ["ACCEPTED_BACKENDS", "FileStoreNotEnabled", "configured_backend", "configured_root", "get_store"]
