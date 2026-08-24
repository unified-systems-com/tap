"""Tests for the shared fallback-resolution banner partial.

Covers req-web-panel-entity-resolution-template: the canonical banner at
`tap_web/templates/tap_web/partials/fallback_banner.html` renders the four
facts the spec requires — auto-resolved (not deep-linked), which URL var
overrides the fallback, the fallback's plain-English intent, and the picked
entity_id — and renders nothing at all when the resolution was a deep link.

No DB required — pure template rendering through Django's template engine.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string

_PARTIAL = "tap_web/partials/fallback_banner.html"

_FALLBACK_CONTEXT = {
    "used_fallback": True,
    "fallback_description": "Latest oscal_ssp by fetched_at",
    "var_name": "ssp_eid",
    "entity_id": "0198f00d-aaaa-bbbb-cccc-1234567890ab",
}


@pytest.mark.spec("req-web-panel-entity-resolution-template-2")
def test_banner_renders_description_when_fallback_used() -> None:
    """used_fallback=True renders a visible banner carrying the description."""
    html = render_to_string(_PARTIAL, _FALLBACK_CONTEXT)
    assert "tap-fallback-banner" in html
    assert "Latest oscal_ssp by fetched_at" in html
    # Neutral lead when the consumer supplies none.
    assert "auto-selected" in html


@pytest.mark.spec("req-web-panel-entity-resolution-template-3")
def test_banner_identifies_override_path() -> None:
    """The banner names the URL var and shows a copyable pin URL for it."""
    html = render_to_string(_PARTIAL, _FALLBACK_CONTEXT)
    assert "ssp_eid" in html
    # The pin hint pairs the var with the picked id so the user can bookmark.
    assert "?ssp_eid=0198f00d-aaaa-bbbb-cccc-1234567890ab" in html


@pytest.mark.spec("req-web-panel-entity-resolution-template-1")
def test_banner_carries_picked_entity_id() -> None:
    """The propagated entity_id reaches the rendered banner unchanged."""
    html = render_to_string(_PARTIAL, _FALLBACK_CONTEXT)
    assert "0198f00d-aaaa-bbbb-cccc-1234567890ab" in html


@pytest.mark.spec("req-web-panel-entity-resolution-template-2")
def test_banner_absent_for_deep_link() -> None:
    """A deep-linked resolution (used_fallback falsy) renders no banner."""
    html = render_to_string(_PARTIAL, {**_FALLBACK_CONTEXT, "used_fallback": False})
    assert "tap-fallback-banner" not in html


def test_consumer_lead_overrides_neutral_default() -> None:
    """A consumer-supplied fallback_lead replaces the neutral lead sentence."""
    html = render_to_string(_PARTIAL, {**_FALLBACK_CONTEXT, "fallback_lead": "Showing the latest batch."})
    assert "Showing the latest batch." in html
    assert "auto-selected" not in html
