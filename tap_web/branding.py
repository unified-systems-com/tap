"""Site branding at request time: the instance name and the SVG glyph (req-boot-web-branding).

``tap_web.boot`` reads the profile settings-free; this module is the Django-side half. It turns
the resolved pointer (``glyph.plugin`` + ``glyph.path``) into a sanitised inline SVG for the
header mark, and decides the display name. Both the page chrome (``context_processors.branding``)
and the boot's web phase (``verify_glyph``) call the same functions, so what boot warns about is
exactly what the header would fail to render.

An unusable glyph is cosmetic: it logs a warning naming plugin and path and the instance renders
its text name. Nothing here raises into a request or a boot (req-boot-web-branding-6).

The sanitiser is an ALLOW-list over the parsed tree (never a regex over text), and the markup it
returns is re-serialised from that tree, so nothing the parser did not understand reaches a page.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET  # nosemgrep  # nosec B405 - DOCTYPE/ENTITY refused before parsing; see sanitize_svg

from django.conf import settings
from django.utils.safestring import SafeString, mark_safe

from tap_web.boot import _profile_path, branding_for_profile, branding_from_section, glyph_pointer_problem

logger = logging.getLogger(__name__)

SVG_NS = "http://www.w3.org/2000/svg"
MAX_GLYPH_BYTES = 64 * 1024
DEFAULT_NAME = "TAP"
GLYPH_CSS_CLASS = "tap-brand-glyph"

# Drawing elements only. Everything that can run code, load something, restyle the page or embed
# foreign content (script, foreignObject, style, image, use, a, animate, set, iframe ...) is absent.
_ALLOWED_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "defs",
        "title",
        "desc",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
    }
)
_NAMED_REJECTIONS = frozenset({"script", "foreignObject", "style"})
_FORBIDDEN_VALUE_FRAGMENTS = ("javascript:", "data:", "http:", "https:", "//", "@import", "expression(")


class UnsafeGlyphError(ValueError):
    """The SVG is not acceptable as an inline site glyph (the message names why)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _check_attribute(element: str, name: str, value: str) -> None:
    if name.startswith("{"):
        raise UnsafeGlyphError(f"<{element}> has a namespaced attribute {name!r}")
    lowered_name = name.lower()
    if lowered_name.startswith("on"):
        raise UnsafeGlyphError(f"<{element}> has an event-handler attribute {name!r}")
    lowered = value.strip().lower()
    if lowered_name in {"href", "src"} and not lowered.startswith("#"):
        raise UnsafeGlyphError(f"<{element}> has an external reference in {name!r}")
    for fragment in _FORBIDDEN_VALUE_FRAGMENTS:
        if fragment in lowered:
            raise UnsafeGlyphError(f"<{element}> attribute {name!r} contains {fragment!r}")
    # url(...) may only point at a fragment of this same document.
    rest = lowered
    while "url(" in rest:
        rest = rest.split("url(", 1)[1].lstrip(" '\"")
        if not rest.startswith("#"):
            raise UnsafeGlyphError(f"<{element}> attribute {name!r} has a non-local url()")


def sanitize_svg(text: str, *, label: str) -> SafeString:
    """Return ``text`` as inline-safe markup for the header mark, or raise ``UnsafeGlyphError``.

    No script, foreignObject, style element, event-handler attribute or external reference; the
    root gets ``role="img"`` and the instance name as its accessible label
    (req-web-chrome-branding-glyph).
    """
    lowered = text.lower()
    # Expat expands internal entities, so a DOCTYPE is refused outright (entity bombs, XXE).
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise UnsafeGlyphError("a DOCTYPE or ENTITY declaration is not allowed")
    try:
        root = ET.fromstring(text)  # nosemgrep  # nosec B314 - DOCTYPE/ENTITY refused above, so no entity expansion
    except ET.ParseError as exc:
        raise UnsafeGlyphError(f"not well-formed XML: {exc}") from exc
    if root.tag != f"{{{SVG_NS}}}svg":
        raise UnsafeGlyphError("the root element is not an SVG <svg>")
    for element in root.iter():
        if not isinstance(element.tag, str):  # comments / processing instructions
            raise UnsafeGlyphError("comments and processing instructions are not allowed")
        local = _local(element.tag)
        if local in _NAMED_REJECTIONS:
            raise UnsafeGlyphError(f"<{local}> is not allowed")
        if not element.tag.startswith(f"{{{SVG_NS}}}") or local not in _ALLOWED_ELEMENTS:
            raise UnsafeGlyphError(f"<{local}> is not an allowed SVG element")
        for name, value in element.attrib.items():
            _check_attribute(local, name, value)
    for stale in ("role", "aria-label", "aria-hidden", "class", "width", "height", "focusable"):
        root.attrib.pop(stale, None)
    root.set("role", "img")
    root.set("aria-label", label)
    root.set("class", GLYPH_CSS_CLASS)
    root.set("focusable", "false")
    ET.register_namespace("", SVG_NS)
    return mark_safe(ET.tostring(root, encoding="unicode"))  # noqa: S308  # nosemgrep  # nosec B703 B308 - rebuilt from the allow-listed tree above


@dataclass(frozen=True)
class Glyph:
    """A usable glyph: sanitised inline markup, and the static path the favicon link serves."""

    markup: SafeString
    static_path: str  # "<plugin>/<path>", the argument to {% static %}


@dataclass(frozen=True)
class Branding:
    name: str
    glyph: Glyph | None


def _glyph_file(plugin: str, path: str) -> Path:
    """The glyph file inside ``plugin``'s static directory (``<app>/static/<plugin>/<path>``)."""
    from django.apps import apps

    try:
        app_path = Path(apps.get_app_config(plugin).path)
    except LookupError as exc:
        raise UnsafeGlyphError(f"plugin {plugin!r} is not installed") from exc
    base = (app_path / "static" / plugin).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        raise UnsafeGlyphError("the glyph path leaves the plugin's static directory")
    if not target.is_file():
        raise UnsafeGlyphError(f"no such file in {plugin}'s static directory")
    if target.stat().st_size > MAX_GLYPH_BYTES:
        raise UnsafeGlyphError(f"larger than {MAX_GLYPH_BYTES} bytes")
    return target


def load_glyph(plugin: str | None, path: str | None, *, label: str) -> Glyph | None:
    """Load and sanitise the glyph, or None. A bad glyph logs a warning and returns None, never raises.

    A missing plugin, missing file, wrong type or unsafe content is a warning naming plugin and
    path; the caller renders the text name (req-boot-web-branding-6).
    """
    if plugin is None and path is None:
        return None
    try:
        if plugin is None or path is None:
            raise UnsafeGlyphError("glyph plugin and path must be set together")
        problem = glyph_pointer_problem(plugin, path)
        if problem:
            raise UnsafeGlyphError(problem)
        text = _glyph_file(plugin, path).read_text(encoding="utf-8")
        return Glyph(markup=sanitize_svg(text, label=label), static_path=f"{plugin}/{path}")
    except (UnsafeGlyphError, OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "[5b1c] site glyph unusable (plugin=%s path=%s): %s; rendering the text name", plugin, path, exc
        )
        return None


def verify_glyph(section: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Boot's post-population check of a profile's glyph. ``(ok, message)``; never raises, never aborts.

    The message is None when no glyph is declared (nothing to say)."""
    resolved = branding_from_section(section)
    if resolved["glyph_plugin"] is None and resolved["glyph_path"] is None:
        return True, None
    glyph = load_glyph(resolved["glyph_plugin"], resolved["glyph_path"], label=resolved["name"] or DEFAULT_NAME)
    where = f"{resolved['glyph_plugin']}:{resolved['glyph_path']}"
    if glyph is None:
        return False, f"Site glyph {where}: unusable (warning logged); the header shows the text name."
    return True, f"Site glyph: {where}."


# One slot: the profile, environment and glyph file rarely change, so the common request is a
# couple of stat calls. The key carries everything the result depends on.
_lock = threading.Lock()
_slot: tuple[tuple[Any, ...], Branding] | None = None


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def current_branding() -> Branding:
    """The instance's name and glyph now. Name order: ``TAP_BOOT_WEB__BRANDING__NAME``, profile name,
    ``TAP_PRODUCT_NAME``, ``TAP`` (req-boot-web-branding-7)."""
    global _slot
    profile_id = os.environ.get("TAP_BOOT_PROFILE", "").strip()
    profile_stat = _stat_key(_profile_path(profile_id)) if profile_id else None
    env_key = tuple(
        os.environ.get(f"TAP_BOOT_WEB__BRANDING__{k}") for k in ("NAME", "GLYPH_PLUGIN", "GLYPH_PATH")
    )
    fallback = getattr(settings, "TAP_PRODUCT_NAME", None) or DEFAULT_NAME
    key = (profile_id, profile_stat, env_key, fallback)
    with _lock:
        if _slot is not None and _slot[0][:4] == key:
            cached_files = _slot[0][4]
            if cached_files == _glyph_stat(_slot[1]):
                return _slot[1]
    resolved = branding_for_profile(profile_id) if profile_id else branding_from_section(None)
    name = resolved["name"] or fallback
    glyph = load_glyph(resolved["glyph_plugin"], resolved["glyph_path"], label=name)
    result = Branding(name=name, glyph=glyph)
    with _lock:
        _slot = ((*key, _glyph_stat(result)), result)
    return result


def _glyph_stat(branding: Branding) -> tuple[int, int] | None:
    if branding.glyph is None:
        return None
    plugin, _, rel = branding.glyph.static_path.partition("/")
    try:
        from django.apps import apps

        return _stat_key(Path(apps.get_app_config(plugin).path) / "static" / plugin / rel)
    except LookupError:
        return None
