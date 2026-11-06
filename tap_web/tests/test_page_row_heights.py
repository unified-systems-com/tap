"""Row-height resolution for page layouts.

Covers:
  req-web-page-row-heights — an `Nfr` row divides the space remaining in a container
  with a definite height; off a full_bleed page there is none, so it falls back to its
  intrinsic height rather than clipping to a share of zero (tap#416).
"""

from __future__ import annotations

from typing import Any

import pytest

from tap_web.views import _process_layout


def _layout(height: str) -> dict[str, Any]:
    return {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"height": height, "panel-id": "detail"}}}}}


def _row(height: str, *, full_bleed: bool) -> dict[str, Any]:
    cols = _process_layout(_layout(height), {"detail": "panel-x"}, None, None, full_bleed=full_bleed)
    rows: list[dict[str, Any]] = cols[0]["rows"]
    return rows[0]


class TestUnboundedFr:
    """The flag the template reads. Derived once in the view, never re-spelled in a condition."""

    def test_an_fr_row_off_a_full_bleed_page_is_unbounded(self):
        # The blank-page case: body is `min-h-full`, so the grid's height is indefinite,
        # the row's share of it is zero, and clipping it hides the panel entirely.
        assert _row("1fr", full_bleed=False)["unbounded_fr"] is True

    def test_an_fr_row_on_a_full_bleed_page_is_bounded(self):
        assert _row("1fr", full_bleed=True)["unbounded_fr"] is False

    @pytest.mark.parametrize("height", ["2fr", "10fr"])
    def test_any_fr_multiple_is_treated_alike(self, height):
        assert _row(height, full_bleed=False)["unbounded_fr"] is True

    @pytest.mark.parametrize("height", ["auto", "60vh", "75vh"])
    def test_a_definite_height_is_never_unbounded(self, height):
        # `vh` is definite on any page — the repository page's 60vh graph is why.
        assert _row(height, full_bleed=False)["unbounded_fr"] is False
        assert _row(height, full_bleed=True)["unbounded_fr"] is False

    def test_a_row_with_no_declared_height_defaults_to_auto_and_is_bounded(self):
        cols = _process_layout(
            {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "detail"}}}}},
            {"detail": "panel-x"},
            None,
            None,
            full_bleed=False,
        )
        row = cols[0]["rows"][0]
        assert row["height"] == "auto"
        assert row["unbounded_fr"] is False


class TestEveryRowHeightResolvesToSomething:
    """The guard: no combination may produce a row that both has no height and clips.

    That pair is what rendered four pages blank for eight days — the panel was fetched,
    rendered and in the DOM, clipped to a box of zero height by its own overflow.
    """

    @pytest.mark.parametrize("height", ["auto", "1fr", "2fr", "60vh"])
    @pytest.mark.parametrize("full_bleed", [True, False])
    def test_a_row_is_never_both_zero_height_and_clipping(self, height, full_bleed):
        row = _row(height, full_bleed=full_bleed)
        # The template clips (overflow-y: auto) exactly when the row is NOT rendered at
        # intrinsic height. Intrinsic height is `auto` or an unbounded fr.
        intrinsic = row["height"] == "auto" or row["unbounded_fr"]
        clips = not intrinsic
        # A clipping row must have a height that does not depend on an indefinite parent.
        assert not clips or ("vh" in row["height"] or full_bleed)


def _fill_layout(*, bands: int = 1, full_bleed: bool = False) -> dict[str, Any]:
    cols: dict[str, Any] = {
        "col-1": {"width": "12fr", "band": 1, "rows": {"row-1": {"panel-id": "a"}}},
    }
    if bands > 1:
        cols["col-2"] = {"width": "12fr", "band": 2, "rows": {"row-1": {"panel-id": "b", "height": "fill"}}}
    else:
        cols["col-1"]["rows"]["row-2"] = {"panel-id": "b", "height": "fill"}
    layout: dict[str, Any] = {"columns": cols}
    if full_bleed:
        layout["full_bleed"] = True
    return layout


def _make_fill_page(layout: dict[str, Any], slug: str):
    from tap_grid.models import Edge
    from tap_web.models import Page, Panel

    page = Page.objects.create(name="Fill", slug=f"/{slug}", layout=layout)
    for panel_id in ("a", "b"):
        panel = Panel.objects.create(
            slug=f"p-{panel_id}-{slug}", name=panel_id, description="", view="tap_web/panel_error.html", config={}
        )
        Edge.objects.create(
            from_entity=page.entity,
            to_entity=panel.entity,
            edge_type="USES_PANEL",
            properties={"hotlink": {"model": "page", "spec": "page-panels", "value": panel_id}},
        )
    return page


class TestFillValidation:
    @pytest.mark.spec("req-web-page-row-heights-1")
    def test_fill_is_accepted(self):
        from tap_web.validation import validate_page_layout

        validate_page_layout(_layout("fill"))

    @pytest.mark.spec("req-web-page-row-heights-1")
    @pytest.mark.parametrize("bad", ["calc(100vh - 8rem)", "fill2", "Fill", "0", "100%", ""])
    def test_other_values_are_still_rejected(self, bad):
        from tap_web.exceptions import PageLayoutValidationError
        from tap_web.validation import validate_page_layout

        with pytest.raises(PageLayoutValidationError):
            validate_page_layout(_layout(bad))


class TestFillProcessing:
    @pytest.mark.spec("req-web-page-row-heights-2")
    @pytest.mark.parametrize("full_bleed", [True, False])
    def test_a_fill_row_is_bounded_on_any_page(self, full_bleed):
        row = _row("fill", full_bleed=full_bleed)
        assert row["is_fill"] is True
        assert row["unbounded_fr"] is False

    @pytest.mark.spec("req-web-page-row-heights-2")
    @pytest.mark.parametrize("height", ["auto", "1fr", "60vh"])
    def test_other_rows_are_not_fill(self, height):
        assert _row(height, full_bleed=True)["is_fill"] is False


@pytest.mark.django_db
class TestFillRender:
    @pytest.mark.spec("req-web-page-row-heights-3")
    @pytest.mark.parametrize("bands", [1, 2])
    def test_the_page_is_a_viewport_column(self, bands):
        from tap.pytest_harness import make_admin_client

        _make_fill_page(_fill_layout(bands=bands), f"fill{bands}")
        html = make_admin_client().get(f"/fill{bands}").content.decode()
        assert '<body class="h-full flex flex-col">' in html
        assert '<main class="flex flex-col flex-1 min-h-0">' in html
        assert "flex-1 min-h-0 max-w-[1700px] mx-auto" in html
        assert "flex: 1 1 0; min-height: var(--tap-fill-min, 24rem); overflow-y: auto;" in html

    @pytest.mark.spec("req-web-page-row-heights-3")
    def test_a_page_without_fill_renders_as_before(self):
        from tap.pytest_harness import make_admin_client

        layout = _fill_layout()
        layout["columns"]["col-1"]["rows"]["row-2"]["height"] = "60vh"
        _make_fill_page(layout, "nofill")
        html = make_admin_client().get("/nofill").content.decode()
        assert '<body class="min-h-full flex flex-col">' in html
        assert "tap-fill-min" not in html

    @pytest.mark.spec("req-web-page-row-heights-3")
    def test_a_full_bleed_fill_page_drops_the_max_width(self):
        from tap.pytest_harness import make_admin_client

        _make_fill_page(_fill_layout(full_bleed=True), "fillbleed")
        html = make_admin_client().get("/fillbleed").content.decode()
        assert "max-w-[1700px]" not in html

    @pytest.mark.spec("req-web-page-row-heights-4")
    def test_only_the_fill_band_grows(self):
        import re

        from tap.pytest_harness import make_admin_client

        _make_fill_page(_fill_layout(bands=2), "fillbands")
        html = make_admin_client().get("/fillbands").content.decode()
        grids = re.findall(r'<div class="tap-page-grid"[^>]*?style="([^"]*)"', html)
        assert len(grids) == 2
        assert "flex: 0 0 auto;" in grids[0] and "min-height: 0;" in grids[0]
        assert "flex: 1 1 0;" in grids[1] and "var(--tap-fill-min, 24rem)" in grids[1]
        assert 'class="tap-page-bands" style="display: flex; flex-direction: column; gap: 1rem; flex: 1 1 0; min-height: 0;"' in html
