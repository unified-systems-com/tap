"""TAP Web validation utilities.

Provides slug and layout validators for Page objects.
All validators raise dedicated exception types from tap_web.exceptions.
"""

from __future__ import annotations

import re

import jsonschema

from tap_web.exceptions import (
    PageLayoutValidationError,
    PageSlugValidationError,
)

# ---------------------------------------------------------------------------
# Page slug validation (req-web-page-slug-sanitize.sec)
# ---------------------------------------------------------------------------

_SLUG_UPPERCASE_RE = re.compile(r"[A-Z]")
_SLUG_REPEATED_SLASH_RE = re.compile(r"//")
_SLUG_DOT_SEGMENT_RE = re.compile(r"(^|/)\.\.?(/|$)")


def validate_page_slug(slug: str, reserved_prefixes: list[str] | None = None) -> None:
    """Validate a Page slug against all security and formatting rules.

    Args:
        slug: The slug value to validate. Must start with /.
        reserved_prefixes: Prefix strings that are blocked (e.g. ["/admin"]).
            If a slug equals or starts with "<prefix>/" it is rejected.

    Raises:
        PageSlugValidationError: If any rule is violated.
    """
    if not slug.startswith("/"):
        raise PageSlugValidationError("Slug must start with '/'.")

    if slug == "/":
        raise PageSlugValidationError("Slug '/' is reserved for the root URL and cannot be used for Page objects.")

    if _SLUG_UPPERCASE_RE.search(slug):
        raise PageSlugValidationError("Slug must be lowercase.")

    if _SLUG_REPEATED_SLASH_RE.search(slug):
        raise PageSlugValidationError("Slug must not contain repeated slashes (//).")

    if slug.endswith("/"):
        raise PageSlugValidationError("Slug must not end with a trailing slash.")

    if _SLUG_DOT_SEGMENT_RE.search(slug):
        raise PageSlugValidationError(
            "Slug must not contain dot-segments (/./ or /../) or standalone . and .. segments."
        )

    if reserved_prefixes:
        for prefix in reserved_prefixes:
            if slug == prefix or slug.startswith(prefix + "/"):
                raise PageSlugValidationError(f"Slug '{slug}' is blocked by reserved prefix '{prefix}'.")


# ---------------------------------------------------------------------------
# Page layout validation (req-web-page-layout-sanitize.sec)
# ---------------------------------------------------------------------------

# JSON Schema from spec-web-page.md (req-web-page-layout-sanitize.sec)
_LAYOUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["columns"],
    "properties": {
        "full_bleed": {
            "type": "boolean",
            "description": (
                "When true, the page renders full viewport width (no centered "
                "max-width container). For dashboard/graph pages that want the "
                "canvas edge-to-edge; text/form pages omit it and stay centered."
            ),
        },
        "columns": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"pattern": "^col-[1-9][0-9]*(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$"},
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["width", "rows"],
                "properties": {
                    "width": {
                        "type": "string",
                        "enum": [
                            "auto",
                            "1fr",
                            "2fr",
                            "3fr",
                            "4fr",
                            "5fr",
                            "6fr",
                            "7fr",
                            "8fr",
                            "9fr",
                            "10fr",
                            "11fr",
                            "12fr",
                        ],
                    },
                    "tags": {
                        "type": "object",
                        "propertyNames": {"pattern": "^[a-z][a-z0-9-]*$"},
                        "additionalProperties": {
                            "type": "string",
                            "pattern": "^[a-z][a-z0-9-]*$",
                        },
                    },
                    "rows": {
                        "type": "object",
                        "minProperties": 1,
                        "propertyNames": {"pattern": "^row-[1-9][0-9]*(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$"},
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["panel-id"],
                            "properties": {
                                "panel-id": {
                                    "type": "string",
                                    "pattern": "^[a-z][a-z0-9-]*$",
                                },
                                "row_span": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "default": 1,
                                },
                                "col_span": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "default": 1,
                                },
                                "height": {
                                    "type": "string",
                                    "enum": [
                                        "auto",
                                        "25vh",
                                        "33vh",
                                        "40vh",
                                        "50vh",
                                        "60vh",
                                        "66vh",
                                        "75vh",
                                        "80vh",
                                        "90vh",
                                        "100vh",
                                        "1fr",
                                        "2fr",
                                        "3fr",
                                        "4fr",
                                        "5fr",
                                        "6fr",
                                        "7fr",
                                        "8fr",
                                        "9fr",
                                        "10fr",
                                        "11fr",
                                        "12fr",
                                    ],
                                },
                                "tags": {
                                    "type": "object",
                                    "propertyNames": {"pattern": "^[a-z][a-z0-9-]*$"},
                                    "additionalProperties": {
                                        "type": "string",
                                        "pattern": "^[a-z][a-z0-9-]*$",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def validate_page_layout(layout: dict) -> None:
    """Validate a Page layout dict against the canonical JSON Schema.

    Args:
        layout: The layout JSONField value to validate.

    Raises:
        PageLayoutValidationError: If the layout fails schema validation.
    """
    try:
        jsonschema.validate(instance=layout, schema=_LAYOUT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise PageLayoutValidationError(f"Invalid page layout: {exc.message}") from exc
