"""tap_web health probe — the operator's landing page resolves (req-web-page-landing-13).

The machine affordance for "what is the landing page, and is it right?": one
structured line in the readiness report every agent and gate already polls,
instead of a bespoke command. Derives from `resolve_landing`, the same function
the root route and the boot verification use (req-web-page-landing-12).

Process boundary, stated honestly: a fresh ``manage.py health`` process reads the
boot profile the RUNNING web worker may not have loaded yet (an edited profile
before a restart). This report describes its own effective configuration; the
shared code proves the derivation is the same, not that the running server agrees.

Registered from ``tap_web``'s ``ready()`` (readiness set, group ``tap_web``,
``critical=False``): a wrong landing page is loud, never a reason to call the
instance unfit to act on the grid.
"""

from __future__ import annotations

import logging

from tap_health.results import ProbeResult

logger = logging.getLogger(__name__)


def probe_web_landing() -> ProbeResult:
    """Healthy when the configured landing pair resolves to a live page at the asserted slug.

    Otherwise ``unhealthy`` with a stable code naming the state — ``web.landing.undeclared``,
    ``web.landing.malformed`` (not a UUID / no leading slash: distinct from a valid id whose
    target is gone), ``web.landing.missing`` (no live page has the id, or it is another type),
    ``web.landing.slug_mismatch`` (drift since boot). ``context`` carries entity_id,
    asserted_slug, live_slug, page_name, found_entity_type and per-key source — nulls where
    unobservable, never omitted.
    """
    from tap_web.page import resolve_landing

    landing = resolve_landing()
    context = landing.context()
    if landing.ok:
        return ProbeResult.healthy(detail=landing.describe(), context=context)
    return ProbeResult.unhealthy(f"web.landing.{landing.state}", detail=landing.describe(), context=context)
