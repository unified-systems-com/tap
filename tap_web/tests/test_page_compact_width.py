"""Compact column width: a capped column that packs at the start of its band.

Covers:
  req-web-page-compact-width — `compact` is a column `width` (a track capped at 16rem that shrinks on a narrow
  viewport), so small panels such as stat cards sit side by side with room for more.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest

from tap.pytest_harness import make_admin_client
from tap_grid.models import Edge
from tap_web.exceptions import PageLayoutValidationError
from tap_web.models import Page, Panel
from tap_web.validation import validate_page_layout


def _col(width: str, panel: str, **extra: Any) -> dict[str, Any]:
    return {"width": width, "rows": {"row-1": {"panel-id": panel, **extra}}}


def _make_page(layout: dict[str, Any], slug: str) -> Page:
    page = cast(Page, Page.objects.create(name="Compact", slug=slug, layout=layout))
    for panel_id in ("a", "b", "c"):
        panel = cast(
            Panel,
            Panel.objects.create(
                slug=f"p-{panel_id}", name=panel_id, description="", view="tap_web/panel_error.html", config={}
            ),
        )
        Edge.objects.create(
            from_entity=page.entity,
            to_entity=panel.entity,
            edge_type="USES_PANEL",
            properties={"hotlink": {"model": "page", "spec": "page-panels", "value": panel_id}},
        )
    return page


def _tracks(html: str) -> list[str]:
    return re.findall(r"grid-template-columns: ([^;]+);", html)


@pytest.mark.spec("req-web-page-compact-width-1")
class TestValidation:
    def test_compact_is_an_accepted_column_width(self):
        validate_page_layout({"columns": {"col-1": _col("compact", "a"), "col-2": _col("1fr", "b")}})

    @pytest.mark.parametrize("width", ["narrow", "16rem", "Compact", "13fr", "", None])
    def test_an_unlisted_width_is_still_rejected(self, width):
        with pytest.raises(PageLayoutValidationError):
            validate_page_layout({"columns": {"col-1": _col(cast(str, width), "a")}})

    def test_compact_is_not_a_row_height(self):
        with pytest.raises(PageLayoutValidationError):
            validate_page_layout({"columns": {"col-1": _col("1fr", "a", height="compact")}})


@pytest.mark.django_db
class TestRender:
    @pytest.mark.spec("req-web-page-compact-width-2")
    def test_compact_columns_render_as_capped_tracks_beside_other_widths(self):
        layout = {"columns": {"col-1": _col("compact", "a"), "col-2": _col("compact", "b"), "col-3": _col("1fr", "c")}}
        _make_page(layout, "/compact")
        html = make_admin_client().get("/compact").content.decode()
        assert _tracks(html) == ["minmax(0, 16rem) minmax(0, 16rem) 1fr"]

    @pytest.mark.spec("req-web-page-compact-width-3")
    def test_existing_widths_render_unchanged(self):
        layout = {"columns": {"col-1": _col("auto", "a"), "col-2": _col("3fr", "b"), "col-3": _col("12fr", "c")}}
        _make_page(layout, "/plainwidths")
        html = make_admin_client().get("/plainwidths").content.decode()
        assert _tracks(html) == ["auto 3fr 12fr"]
