"""The one same-origin row-URL rule shared by the Table and Chart panels.

A ``row_url_template`` is a same-origin path whose ``{alias}`` placeholders fill from one row of the bound
Search (``req-web-stdpanel-table-rows-5``; the Chart panel's ``click`` reuses it, ``req-web-panels-chart-click``).
Both panels validate with the same pattern and fill with the same function, so there is exactly one place where
"what counts as a safe link" is decided.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

# A path, never `//host` or `/\host`, and no whitespace, control characters or backslashes anywhere: a browser
# strips tab/CR/LF and reads a backslash as `/` when it parses a URL, so `/<TAB>/host` becomes `//host`.
# `(?![\s\S])` is a true end of string (`$` also matches before a final newline), in both Python's and
# ECMAScript's regex dialects.
ROW_URL_TEMPLATE_PATTERN = r"^/(?![/\\])[^\\\x00-\x20\x7f]*(?![\s\S])"

# JSON Schema fragment for a `row_url_template` property.
ROW_URL_TEMPLATE_SCHEMA: dict[str, Any] = {"type": "string", "minLength": 2, "pattern": ROW_URL_TEMPLATE_PATTERN}

_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")


def is_same_origin_template(template: Any) -> bool:
    """True when ``template`` is a string that passes the same-origin path rule."""
    return (
        isinstance(template, str) and len(template) >= 2 and re.search(ROW_URL_TEMPLATE_PATTERN, template) is not None
    )


def placeholders(template: str) -> list[str]:
    """The ``{alias}`` names of ``template``, in order of first appearance."""
    return list(dict.fromkeys(_PLACEHOLDER.findall(template)))


def fill_row_url(template: str | None, row: dict[str, Any]) -> str | None:
    """The URL for ``row``, or None when there is no template, it is unsafe, or a placeholder has no value.

    Each ``{alias}`` takes the row's value URL-encoded as one path segment or query value (nothing it contains
    can change the URL's shape). A placeholder whose value is absent or empty leaves the row with no link: a
    half-built URL is worse than none. The same-origin rule is applied again here because a grift-seeded
    config reaches this code unvalidated.
    """
    if not template or not is_same_origin_template(template):
        return None
    values = {alias: row.get(alias) for alias in placeholders(template)}
    if any(v is None or v == "" for v in values.values()):
        return None
    url = template
    for alias, value in values.items():
        url = url.replace("{" + alias + "}", quote(str(value), safe=""))
    return url
