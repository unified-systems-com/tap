"""Restate a format ``"0"`` GRIFT document at format ``"1"``, changing nothing but its header.

``req-grift-header-versions`` rule 12: the base-model release (Issue# 1288 - tap) moves every committed
document in core and in the plugin repositories to ``"1"``. A ``"0"`` document states no versions and
is read as the spine and every type it carries at version 1 (rule 11), so that is what its restated
header says: ``spine_version`` 1 and a ``type_versions`` entry of 1 for every type the document carries
or names, listed by the exporter's own header builder (:func:`tap_grid.grift.upgrade.build_header` with
``unversioned=True``). An import then carries each record from version 1 through the declared links, as
it would have read the ``"0"`` document, and a document that already states ``"1"`` is left alone.

Byte for byte: only the text of the top-level ``metadata`` value is replaced. Every other byte of the
file (the records, their key order, the whitespace, the escapes) is the file's own. The keys the
header already held keep their place; ``spine_version`` and ``type_versions`` follow them.

A document that names a type no installed model or edge definition registers is refused, naming the
types: its version cannot be known to be 1 on this grid, and an import would refuse it anyway.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tap_grid.grift.upgrade import UNVERSIONED_FORMAT, VERSIONED_FORMAT, build_header, installed_version

_WHITESPACE = " \t\n\r"


class RestampRefused(ValueError):
    """The document cannot be restated; the message says why."""


@dataclass
class RestampResult:
    """What restating one document did, or would do."""

    path: Path | None
    text: str
    header: dict[str, Any] = field(default_factory=dict)
    changed: bool = False
    note: str = ""


def _skip(text: str, at: int) -> int:
    while at < len(text) and text[at] in _WHITESPACE:
        at += 1
    return at


def metadata_span(text: str) -> tuple[int, int]:
    """Where the top-level ``metadata`` value starts and ends in ``text``.

    Walks the top-level object with the standard library's own scanners, so a ``"metadata"`` that
    appears inside a record is never mistaken for the header.
    """
    decoder = json.JSONDecoder()
    at = _skip(text, 0)
    if at >= len(text) or text[at] != "{":
        raise RestampRefused("the document is not a JSON object")
    at = _skip(text, at + 1)
    while at < len(text) and text[at] != "}":
        if text[at] != '"':
            raise RestampRefused(f"expected a key at offset {at}")
        key, at = json.decoder.scanstring(text, at + 1)  # type: ignore[attr-defined]
        at = _skip(text, at)
        if text[at] != ":":
            raise RestampRefused(f"expected ':' at offset {at}")
        start = _skip(text, at + 1)
        _value, end = decoder.raw_decode(text, start)
        if key == "metadata":
            return start, end
        at = _skip(text, end)
        if at < len(text) and text[at] == ",":
            at = _skip(text, at + 1)
    raise RestampRefused("the document has no top-level metadata")


def _render(header: dict[str, Any], original: str, text: str, start: int) -> str:
    """The new header in the style of the old one: one line if it was one line, else indented."""
    if "\n" not in original:
        return json.dumps(header, ensure_ascii=False)
    line_start = text.rfind("\n", 0, start) + 1
    indent = len(text[line_start:start]) - len(text[line_start:start].lstrip(" "))
    inner = next(
        (len(line) - len(line.lstrip(" ")) for line in original.splitlines()[1:] if line.strip()), indent + 2
    )
    step = max(inner - indent, 1)
    rendered = json.dumps(header, indent=step, ensure_ascii="\\u" in original)
    return rendered.replace("\n", "\n" + " " * indent)


def restamp_text(text: str, *, path: Path | None = None) -> RestampResult:
    """Restate one document's text at format ``"1"``. Raises :class:`RestampRefused` with the reason."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise RestampRefused(f"not JSON: {error}") from error
    metadata = document.get("metadata") if isinstance(document, dict) else None
    if not isinstance(metadata, dict):
        raise RestampRefused("the document has no metadata object")
    if not isinstance(document.get("batches"), list):
        raise RestampRefused("the document has no batches list; it is not a GRIFT batch document")
    stated = metadata.get("grift_version")
    if stated == VERSIONED_FORMAT:
        return RestampResult(path, text, note=f'already at grift_version "{VERSIONED_FORMAT}"')
    if stated != UNVERSIONED_FORMAT:
        raise RestampRefused(f'grift_version {stated!r} is neither "{UNVERSIONED_FORMAT}" nor "{VERSIONED_FORMAT}"')

    header = build_header(document, unversioned=True)
    unknown = sorted(slug for slug in header["type_versions"] if installed_version(slug) is None)
    if unknown:
        raise RestampRefused(
            f"the document names {', '.join(unknown)}, which no installed model or edge type registers; install "
            "the plugin that owns it and run again"
        )
    merged = {**metadata, **header}
    start, end = metadata_span(text)
    rewritten = text[:start] + _render(merged, text[start:end], text, start) + text[end:]
    return RestampResult(path, rewritten, header=merged, changed=True)


def restamp_path(path: Path, *, out: Path | None = None, write: bool = True) -> RestampResult:
    """Restate the document at ``path``, writing it to ``out`` (default: in place) unless ``write`` is False."""
    result = restamp_text(path.read_text(encoding="utf-8"), path=path)
    if result.changed and write:
        (out or path).write_text(result.text, encoding="utf-8")
    return result


def documents_under(root: Path) -> list[Path]:
    """The GRIFT documents a directory holds: every ``*.grift.json`` beneath it, in path order."""
    return sorted(p for p in root.rglob("*.grift.json") if p.is_file())
