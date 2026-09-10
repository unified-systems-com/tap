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
