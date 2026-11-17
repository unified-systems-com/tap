"""System checks for the file store: an unknown backend fails startup by name (`req-tap-files-interface-3`)."""

from __future__ import annotations

from typing import Any

from django.core.checks import Error, register


@register()
def check_backend(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    from tap_files.store import ACCEPTED_BACKENDS, configured_backend

    backend = configured_backend()
    if backend not in ACCEPTED_BACKENDS:
        return [
            Error(
                f"TAP_FILES_BACKEND is {backend!r}; the only accepted value is {ACCEPTED_BACKENDS[0]!r}",
                hint="Unset TAP_FILES_BACKEND, or set it to 'local'.",
                id="tap_files.E001",
            )
        ]
    return []
