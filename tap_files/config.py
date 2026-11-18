"""Whether the file store is enabled, where its root is, and which backend serves it.

`specs/spec-tap-file-store.md`, `req-tap-files-root`. The only reader of the `TAP_FILES_ROOT` setting
outside `tap/settings.py` (guard: files-root-resolution). Reading it hands out no backend: code that
only needs to know where the store lives, such as the plugin data directory's overlap check and the
backend setting's system check, reads it here and never imports the store (guard: files-backend-reach).
"""

from __future__ import annotations

from pathlib import Path

ACCEPTED_BACKENDS = ("local",)


def configured_root() -> Path | None:
    """The configured store root, or ``None`` when the file store is not enabled."""
    from django.conf import settings

    raw = getattr(settings, "TAP_FILES_ROOT", "") or ""
    return Path(raw) if raw else None


def configured_backend() -> str:
    from django.conf import settings

    return str(getattr(settings, "TAP_FILES_BACKEND", "local") or "local")


__all__ = ["ACCEPTED_BACKENDS", "configured_backend", "configured_root"]
