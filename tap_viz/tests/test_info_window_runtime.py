"""Core JS names no plugin's route (req-viz-info-window-row-link-2, tap#425, tap#996).

A plugin's page is the plugin's to declare — on its panel instance (`row_url_template`), its badge
set (`info_window.row_url_template`) or its nav rules — never a string literal in tap_viz / tap_web
JavaScript. On 2026-09-10 `info-window.js` was found carrying a hardcoded `/fedramp-ksi/finding`
route that no consumer used, and `panel-table.js` a map of eight. The ruling was that such a line is
an error, not a shortcut: this test fails on any absolute path literal in core static JS that is not
a core route, EXCEPT the entries listed below, which may only ever be removed (ratchet down;
tap#425 tracks the legacy map's migration to declared templates).

Rescued 2026-10-08 off an unpromoted session branch, and two things had moved under it. The RID it
originally cited — an info-window "contents" requirement, third clause — no longer exists; that
requirement was split, and `req-viz-info-window-row-link-2` is its successor for this invariant.
(The dead id is named in `tap#996` rather than here, because the `rid-reference-integrity` guard
resolves EVERY `req-…` token in the tree, including one quoted only to say it is gone.) That requirement also
means the fedramp-ksi fallback is no longer UNDOCUMENTED as the original docstring said: canon now
requires only that "a configured template always wins over the pre-existing `finding_id` fallback",
which acknowledges the fallback without removing it. `tap#996` tracks the removal.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE_JS = [*(REPO / "tap_viz" / "static").rglob("*.js"), *(REPO / "tap_web" / "static").rglob("*.js")]

# Routes core itself owns. Anything else that starts with "/" is a plugin's.
CORE_PREFIXES = ("/object/", "/static/", "/api/", "/panel/", "/auth/", "/__", "/favicon")

# The pre-ruling map in panel-table.js (PER_TYPE_DETAIL_URL). Every entry here must still be present
# — delete the line here when you delete it there — and nothing may be added.
LEGACY_BASELINE: frozenset[str] = frozenset(
    {
        "/samsite/finding/",
        "/samsite/indicator/",
        "/samsite/component/",
        "/samsite/artifacts/ksi-signal?ksi_signal_entity_id=",
        "/samsite/artifacts/vdr-report?vdr_report_entity_id=",
        "/administrivia/batch?batch_entity_id=",
        "/samsite/artifacts/ssp?oscal_ssp_artifact_entity_id=",
        "/samsite/artifacts/poam?oscal_poam_artifact_entity_id=",
        "/samsite/artifacts/iiw?iiw_artifact_entity_id=",
        "/samsite/artifact/",
    }
)

# A violation found 2026-10-08 while rescuing this guard off an unpromoted session branch, tracked by
# `tap#996`. DELIBERATELY NOT in LEGACY_BASELINE: that set's own comment says nothing may ever be
# added to it, and folding this in would quietly convert a live defect into frozen history.
#
# `info-window.js` hardcodes fedramp-ksi's finding route as a SILENT FALLBACK — any badge set whose
# rows carry `finding_id` and which declares no `info_window.row_url_template` links to that
# plugin's page by omission. It is the exact line this guard was written to delete; the feature
# (`row_url_template`) landed on main and the guard did not, so the line outlived its replacement.
#
# It cannot be deleted unilaterally: fedramp-20x-ksi-tap appears not to declare a template, so it
# relies on the fallback. The migration order is in `tap#996`. When step 3 lands, delete this
# constant — `test_info_window_runtime_carries_no_route_at_all` then enforces the real invariant.
PENDING_MIGRATION: frozenset[str] = frozenset(
    {"/fedramp-ksi/finding?entity_id=${encodeURIComponent(r.finding_id)}"}
)

_LITERAL = re.compile(r"""(["'`])(/[A-Za-z0-9_\-][^"'`\s]*)\1""")


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$|(?<=\s)//(?!/)[^\n]*$", "", source, flags=re.M)


def _plugin_routes(source: str) -> set[str]:
    found: set[str] = set()
    for _, path in _LITERAL.findall(_strip_comments(source)):
        if path.startswith(CORE_PREFIXES) or path.startswith("//"):
            continue
        if "." in path.rsplit("/", 1)[-1] and "?" not in path:  # a file (x.svg, x.js), not a route
            continue
        found.add(path)
    return found


def test_core_js_names_no_plugin_route_beyond_the_shrinking_baseline() -> None:
    seen: dict[str, set[str]] = {}
    for js in CORE_JS:
        routes = _plugin_routes(js.read_text(encoding="utf-8"))
        if routes:
            seen[str(js.relative_to(REPO))] = routes
    all_routes = set().union(*seen.values()) if seen else set()
    new = all_routes - LEGACY_BASELINE - PENDING_MIGRATION
    assert (
        not new
    ), f"plugin route(s) hardcoded in core JS — declare them on the consumer instead: {sorted(new)} in {seen}"
    gone = LEGACY_BASELINE - all_routes
    assert (
        not gone
    ), f"baseline entries no longer in core JS — delete them from LEGACY_BASELINE (ratchet down): {sorted(gone)}"


def test_info_window_runtime_carries_no_route_at_all() -> None:
    """The real invariant, currently held open by one tracked violation (`tap#996`).

    When `info-window.js:204-207` goes — step 3 of that issue's migration — delete
    `PENDING_MIGRATION` and this asserts against the empty set, which is the state the guard exists
    to hold. Until then it asserts the violation set has not GROWN, which is the most this can
    honestly claim while the fallback is still shipped.
    """
    source = (REPO / "tap_viz" / "static" / "tap_viz" / "js" / "runtime" / "info-window.js").read_text(encoding="utf-8")
    assert _plugin_routes(source) == set(PENDING_MIGRATION)
