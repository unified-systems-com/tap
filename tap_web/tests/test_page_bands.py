"""Page layout bands: full-width content under side-by-side columns.

Covers:
  req-web-page-bands — an optional integer `band` (>= 1, default 1) on a column groups
  columns into horizontal bands; each band is its own grid, bands stack top to bottom.
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
from tap_web.views import _process_layout


def _col(width: str, panel: str, **extra: Any) -> dict[str, Any]:
    return {"width": width, "rows": {"row-1": {"panel-id": panel}}, **extra}


def _banded() -> dict[str, Any]:
    return {
        "columns": {
            "col-1": _col("1fr", "a", band=1),
            "col-2": _col("2fr", "b", band=1),
            "col-3": _col("12fr", "c", band=2),
        }
    }


def _unbanded() -> dict[str, Any]:
    return {"columns": {"col-1": _col("1fr", "a"), "col-2": _col("2fr", "b")}}


def _make_page(layout: dict[str, Any], slug: str) -> Page:
    page = cast(Page, Page.objects.create(name="Bands", slug=slug, layout=layout))
    for panel_id in ("a", "b", "c"):
        if f'"{panel_id}"' not in str(layout).replace("'", '"'):
            continue
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


def _grids(html: str) -> list[str]:
    return re.findall(r'<div class="tap-page-grid[^>]*>', html)


@pytest.mark.spec("req-web-page-bands-1")
class TestValidation:
    @pytest.mark.parametrize("band", [1, 2, 7])
    def test_a_positive_integer_band_is_accepted(self, band):
        validate_page_layout({"columns": {"col-1": _col("1fr", "a", band=band)}})

    @pytest.mark.parametrize("band", ["1", 1.5, 0, -1, True, False, None, [1]])
    def test_anything_else_is_rejected(self, band):
        with pytest.raises(PageLayoutValidationError):
            validate_page_layout({"columns": {"col-1": _col("1fr", "a", band=band)}})

    def test_band_is_optional(self):
        validate_page_layout(_unbanded())


class TestProcessLayout:
    @pytest.mark.spec("req-web-page-bands-3")
    def test_columns_order_by_band_then_number(self):
        layout = {
            "columns": {
                "col-1": _col("1fr", "a", band=2),
                "col-2": _col("1fr", "b", band=1),
                "col-3": _col("1fr", "c", band=1),
            }
        }
        cols = _process_layout(layout, {}, None, None)
        assert [(c["key"], c["band"]) for c in cols] == [("col-2", 1), ("col-3", 1), ("col-1", 2)]

    def test_band_defaults_to_one(self):
        assert {c["band"] for c in _process_layout(_unbanded(), {}, None, None)} == {1}

    def _fr_layout(self, second_band: bool) -> dict[str, Any]:
        cols: dict[str, Any] = {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "a", "height": "2fr"}}}}
        if second_band:
            cols["col-2"] = _col("1fr", "b", band=2)
        return {"columns": cols}

    @pytest.mark.spec("req-web-page-bands-5")
    def test_nfr_row_keeps_its_height_inside_a_band(self):
        row = _process_layout(self._fr_layout(True), {}, None, None, full_bleed=False)[0]["rows"][0]
        assert row["height"] == "2fr"

    def test_a_single_band_page_keeps_fr_semantics(self):
        bounded = _process_layout(self._fr_layout(False), {}, None, None, full_bleed=True)[0]["rows"][0]
        assert bounded["unbounded_fr"] is False

    @pytest.mark.spec("req-web-page-bands-5")
    def test_several_bands_have_no_definite_height_so_fr_rows_stay_intrinsic(self):
        # Bands stack in normal flow: an fr row would get a share of nothing and clip.
        row = _process_layout(self._fr_layout(True), {}, None, None, full_bleed=True)[0]["rows"][0]
        assert row["unbounded_fr"] is True


@pytest.mark.django_db
class TestRender:
    @pytest.mark.spec("req-web-page-bands-2")
    def test_two_bands_render_two_grids_in_order(self):
        _make_page(_banded(), "/banded")
        html = make_admin_client().get("/banded").content.decode()
        grids = _grids(html)
        assert len(grids) == 2
        assert "grid-template-columns: 1fr 2fr;" in grids[0]
        assert "grid-template-columns: 12fr;" in grids[1]
        first, second = (html.index(g) for g in grids)
        assert first < second
        # Each panel is mounted in its own band's grid.
        assert html.index("/panel/p-b") < second < html.index("/panel/p-c")

    @pytest.mark.spec("req-web-page-bands-4")
    def test_a_page_without_band_renders_one_grid_as_before(self):
        _make_page(_unbanded(), "/plain")
        html = make_admin_client().get("/plain").content.decode()
        grids = _grids(html)
        assert len(grids) == 1
        assert grids[0] == (
            '<div class="tap-page-grid h-full"\n'
            '     style="display: grid; grid-template-columns: 1fr 2fr; gap: 1rem; min-height: 0;">'
        )
        assert html.count('class="tap-col"') == 2

    @pytest.mark.spec("req-web-page-bands-5")
    def test_a_multi_band_page_does_not_force_full_height(self):
        _make_page(_banded(), "/banded2")
        grids = _grids(make_admin_client().get("/banded2").content.decode())
        assert all("h-full" not in g for g in grids)
        assert re.findall(r'data-band="(\d+)"', "".join(grids)) == ["1", "2"]
