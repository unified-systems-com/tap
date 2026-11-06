from typing import Any

from django.conf import settings
from django.http import HttpRequest

from tap_web.branding import current_branding


def branding(request: HttpRequest | None) -> dict[str, Any]:
    brand = current_branding()
    return {
        "product_name": brand.name,
        # Sanitised inline SVG for the header mark, and the static path the favicon link serves;
        # both None when no usable glyph is configured (req-web-chrome-branding-glyph-fallback).
        "brand_glyph": brand.glyph.markup if brand.glyph else None,
        "brand_glyph_static": brand.glyph.static_path if brand.glyph else None,
        "session_label": getattr(settings, "TAP_SESSION_LABEL", ""),
    }
