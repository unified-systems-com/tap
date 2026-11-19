from typing import Any

from django.apps import AppConfig

_PLAIN = {"type": "object", "properties": {}, "additionalProperties": False}


class TapFilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_files"
    verbose_name = "TAP Files"
    # Top-level URL prefix this app mounts, reserved against Page slugs (req-tap-auth-app-4).
    reserved_url_prefixes: list[str] = ["/files"]

    # The grid file's edges (specs/spec-tap-file-store.md, req-tap-files-directory and
    # req-tap-files-format-record). The two containment edges are internal-only, written by the
    # holding helper alone; FILE_CONTENTS is an ordinary edge a plugin writes in its own batch, its
    # targets left open so the plugin points it at a type core does not know.
    edge_types: list[dict[str, Any]] = [
        {
            "slug": "CONTAINS_TAP_DIRECTORY",
            "internal_only": True,
            "sources": [{"type": "tap_directory"}],
            "targets": [{"type": "tap_directory"}],
            "property_schema": _PLAIN,
            "identity": {"discriminators": []},
        },
        {
            "slug": "CONTAINS_TAP_FILE",
            "internal_only": True,
            "sources": [{"type": "tap_directory"}],
            "targets": [{"type": "tap_file"}],
            "property_schema": _PLAIN,
            "identity": {"discriminators": []},
        },
        # WORKAROUND(unified-systems-com/tap#1237): the grid cannot refuse a FILE_CONTENTS edge from a
        # non-tap_file, a second one out of one file, or one whose sha256 is not the file's; the check
        # reports them (req-tap-files-check-10), and the holding helper drops a replaced file's edge.
        {
            "slug": "FILE_CONTENTS",
            "sources": [{"type": "tap_file"}],
            "property_schema": {
                "type": "object",
                "properties": {"sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
                "required": ["sha256"],
                "additionalProperties": False,
            },
            "identity": {"discriminators": []},
        },
    ]

    def ready(self) -> None:
        # Registration only: the backend setting is checked by Django's system checks, so a wrong
        # value fails startup with a named error (req-tap-files-interface-3) without crash-looping
        # inside ready().
        from tap_files import checks  # noqa: F401
        from tap_plugins.base import register_edge_types_from_list

        register_edge_types_from_list(self.edge_types)
