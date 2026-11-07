"""Config schema of the HTML panel (`req-web-panels-html-config`): where the markup comes from and how far it may use the vocabulary."""

from __future__ import annotations

from typing import Any

import jsonschema

from tap_web.panels.html import sanitize

HTML_PANEL_CONFIG_SCHEMA: dict[str, Any] = {
    "description": (
        "Config of an html panel: where the markup comes from and which features of the closed HTML vocabulary it may use. "
        "Exactly one of html and field. The markup is cleaned on every render; the settings below can only narrow what the "
        "vocabulary allows. Script, style, forms, frames, SVG and MathML cannot be enabled."
    ),
    "type": "object",
    "additionalProperties": False,
    "oneOf": [{"required": ["html"]}, {"required": ["field"]}],
    "properties": {
        "html": {
            "description": "The markup, written in the config.",
            "type": "string",
            "maxLength": sanitize.MAX_BYTES_CEILING,
        },
        "field": {
            "description": "The row field of the bound Search that holds the markup.",
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
        },
        "row": {"description": "Index of the row to read with field. Default 0.", "type": "integer", "minimum": 0},
        "features": {
            "description": "Features allowed, from the vocabulary; text is always on. Default: every feature but images.",
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "enum": sorted(sanitize.FEATURES)},
        },
        "classes": {
            "description": "Style classes that survive, from the panel's list. Default: all of them.",
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "enum": sorted(sanitize.CLASSES)},
        },
        "link_schemes": {
            "description": "URL schemes a link may use besides paths on this site. Default: http, https and mailto.",
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(sanitize.SCHEMES)},
        },
        "link_hosts": {
            "description": "Host names an http or https link may point at. Default: any host.",
            "type": "array",
            "maxItems": 50,
            "items": {"type": "string", "pattern": sanitize.HOST_RE.pattern},
        },
        "image_prefixes": {
            "description": "Path prefixes on this site an image may come from. Default: /static/.",
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "pattern": sanitize.PATH_PREFIX_RE.pattern},
        },
        "max_bytes": {
            "description": "Largest document accepted, in bytes.",
            "type": "integer",
            "minimum": 1,
            "maximum": sanitize.MAX_BYTES_CEILING,
        },
        "hide_header": {"description": "True hides the panel header bar.", "type": "boolean"},
    },
}


def validate_config(config: Any) -> str | None:
    """The reason ``config`` is invalid, or None when it is valid."""
    try:
        jsonschema.validate(config, HTML_PANEL_CONFIG_SCHEMA)
        sanitize.Policy.from_config(config)
    except jsonschema.ValidationError as exc:
        return str(exc.message)
    except ValueError as exc:
        return str(exc)
    return None
