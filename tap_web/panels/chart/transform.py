"""Rows -> ECharts option for the Chart panel (req-web-panels-chart-data, -series-by, -hierarchy).

Everything here is pure: rows and config in, a JSON-safe option out, so it is tested without a browser.
The option is data; nothing here produces or accepts code.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from tap_web.panels.chart.config import HIERARCHICAL_TYPES, _series_list
from tap_web.panels.row_url import fill_row_url

DEFAULT_NULL_TEXT = "not observed"
DEFAULT_BLANK_TEXT = "(empty)"
MAX_FULL_LABELS = 12


@dataclass
class Built:
    """The result of building a chart: the option and the stated gaps."""

    option: dict[str, Any]
    notices: list[str] = field(default_factory=list)


def to_number(value: Any) -> float | int | None:
    """A finite number from a number or numeric text, else None (a bool is not a number)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return int(d) if d == d.to_integral_value() and abs(d) < 10**15 else float(d)


def to_instant(value: Any) -> str | None:
    """A UTC ISO-8601 instant ('...Z') from a datetime / date / text, else None. Naive means UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def jsonable(value: Any) -> Any:
    """Make one row value JSON-safe: instants as ISO text, decimals as numbers, the rest as text."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return to_number(value)
    if isinstance(value, datetime | date):
        return to_instant(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def coerce_rows(rows: list[dict[str, Any]], types: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """JSON-safe copies of ``rows`` with each typed field coerced; unparseable values become null and are counted."""
    bad: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        new = {k: jsonable(v) for k, v in row.items()}
        for name, kind in types.items():
            if name not in row or row[name] is None or row[name] == "":
                continue
            if kind == "number":
                new[name] = to_number(row[name])
            elif kind == "time":
                new[name] = to_instant(row[name])
            else:
                new[name] = str(row[name])
            if new[name] is None:
                bad[name] = bad.get(name, 0) + 1
        out.append(new)
    notices = [
        f"{n} value{'s' if n != 1 else ''} in `{name}` could not be read as {types[name]} and "
        f"{'are' if n != 1 else 'is'} drawn as a gap."
        for name, n in bad.items()
    ]
    return out, notices


def _sort_key(value: Any) -> tuple[int, Any]:
    n = to_number(value)
    if n is not None:
        return (0, n)
    return (1, str(value))


def sort_and_limit(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Apply ``sort`` then ``limit`` (and the ``max_rows`` cap); say what was cut."""
    notices: list[str] = []
    spec = config.get("sort")
    if spec:
        name, reverse = spec["field"], spec.get("order", "desc") == "desc"
        present = [r for r in rows if r.get(name) is not None]
        absent = [r for r in rows if r.get(name) is None]
        # Mixed number/text keys never compare: numbers sort before text.
        present.sort(key=lambda r: _sort_key(r[name]), reverse=reverse)
        rows = present + absent
    cut = 0
    for cap in (config.get("limit"), config["max_rows"]):
        if cap is not None and len(rows) > cap:
            cut += len(rows) - cap
            rows = rows[:cap]
    if cut:
        notices.append(f"{cut} more row{'s' if cut != 1 else ''} not drawn.")
    return rows, notices


def _label(value: Any, config: dict[str, Any]) -> str:
    if value is None:
        return str(config.get("null_text", DEFAULT_NULL_TEXT))
    if value == "":
        return str(config.get("blank_text", DEFAULT_BLANK_TEXT))
    return str(value)


def _axis_type(option: dict[str, Any], key: str) -> str | None:
    axis = option.get(key)
    if isinstance(axis, list):
        axis = axis[0] if axis else None
    return axis.get("type") if isinstance(axis, dict) else None


def category_fields(option: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """Row fields drawn as labels: declared `category`, a series' `itemName`, or the field on a category axis."""
    found = [f for f, kind in (config.get("types") or {}).items() if kind == "category"]
    for series in _series_list(option):
        enc = series.get("encode")
        if not isinstance(enc, dict):
            continue
        for axis in ("x", "y"):
            if _axis_type(option, f"{axis}Axis") == "category" and isinstance(enc.get(axis), str):
                found.append(enc[axis])
        if isinstance(enc.get("itemName"), str):
            found.append(enc["itemName"])
    return list(dict.fromkeys(found))


def label_category_fields(
    rows: list[dict[str, Any]], option: dict[str, Any], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Rows with null / empty label fields replaced by `null_text` / `blank_text`, so an axis, legend or tooltip
    names the unobserved bucket instead of drawing it nameless. Numeric fields keep their gaps."""
    fields = category_fields(option, config)
    if not fields:
        return rows
    return [{**r, **{f: _label(r[f], config) for f in fields if f in r and r[f] in (None, "")}} for r in rows]


def set_label_interval(option: dict[str, Any], counts: dict[str, int]) -> None:
    """Show every label on a category axis of up to 12 categories unless the config sets an interval."""
    for key, axis_name in (("xAxis", "x"), ("yAxis", "y")):
        axis = option.get(key)
        if not isinstance(axis, dict) or axis.get("type") != "category" or "data" in axis:
            continue
        for series in _series_list(option):
            enc = series.get("encode")
            field = enc.get(axis_name) if isinstance(enc, dict) else None
            if isinstance(field, str) and field in counts and counts[field] <= MAX_FULL_LABELS:
                label = axis.setdefault("axisLabel", {})
                if isinstance(label, dict):
                    label.setdefault("interval", 0)
                break


CLICKABLE_TYPES: tuple[str, ...] = ("bar", "scatter")
URL_KEY = "_url"


def click_template(config: dict[str, Any]) -> str | None:
    """The ``click.row_url_template`` of the config, or None."""
    click = config.get("click")
    return click.get("row_url_template") if isinstance(click, dict) else None


def row_urls(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[str | None]:
    """Each row's click-through URL (``fill_row_url``: encoded values, same-origin only), None where there is none."""
    template = click_template(config)
    return [fill_row_url(template, row) for row in rows]


def mark_clickable(option: dict[str, Any]) -> None:
    """Give bar and scatter series the pointer cursor (a series' own ``cursor`` is kept)."""
    for series in _series_list(option):
        if series.get("type") in CLICKABLE_TYPES:
            series.setdefault("cursor", "pointer")


def deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """``partial`` over ``base``: objects merge key by key, anything else replaces (``base`` is changed)."""
    for key, value in partial.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def pivot(rows: list[dict[str, Any]], option: dict[str, Any], config: dict[str, Any]) -> Built:
    """``series_by``: one series per distinct ``series`` value over a shared ``category`` axis."""
    spec = config["series_by"]
    cat_f, ser_f, val_f = spec["category"], spec["series"], spec["value"]
    fill = spec.get("fill", 0)
    time_axis = (cat_f in (config.get("types") or {}) and config["types"][cat_f] == "time") or "time" in (
        _axis_type(option, "xAxis"),
        _axis_type(option, "yAxis"),
    )
    categories: dict[Any, int] = {}
    series_names: dict[str, int] = {}
    cells: dict[tuple[Any, str], float] = {}
    unusable = 0
    cat_urls: dict[Any, str] = {}
    click_tpl = click_template(config)
    for row in rows:
        cat = row.get(cat_f)
        url = fill_row_url(click_tpl, {cat_f: cat})
        cat = cat if time_axis and cat is not None else _label(cat, config)
        if url:
            cat_urls.setdefault(cat, url)
        name = _label(row.get(ser_f), config)
        categories.setdefault(cat, len(categories))
        series_names.setdefault(name, len(series_names))
        n = to_number(row.get(val_f))
        if n is None:
            unusable += 1
            continue
        cells[(cat, name)] = cells.get((cat, name), 0) + n
    cats = sorted(categories, key=str) if time_axis else list(categories)
    listed = [s for s in spec.get("order", []) if s in series_names]
    names = listed + [s for s in series_names if s not in listed]

    dims = [cat_f]
    for i in range(len(names)):
        dim = f"series_{i}"
        while dim in dims:
            dim += "_"
        dims.append(dim)
    source = []
    for cat in cats:
        entry: dict[str, Any] = {cat_f: cat}
        if cat in cat_urls:
            entry[URL_KEY] = cat_urls[cat]
        for dim, name in zip(dims[1:], names, strict=True):
            entry[dim] = cells.get((cat, name), fill)
        source.append(entry)

    category_on_y = _axis_type(option, "yAxis") in ("category", "time") and _axis_type(option, "xAxis") not in (
        "category",
        "time",
    )
    cat_axis, val_axis = ("y", "x") if category_on_y else ("x", "y")
    template = _series_list(option)[0]
    out = copy.deepcopy(option)
    overrides = spec.get("overrides") or {}
    out["series"] = [
        {
            **deep_merge(copy.deepcopy(template), overrides.get(name, {})),
            "name": name,
            "encode": {**template.get("encode", {}), cat_axis: cat_f, val_axis: dim},
        }
        for dim, name in zip(dims[1:], names, strict=True)
    ]
    out["dataset"] = {"dimensions": dims, "source": source}
    if cat_urls:
        mark_clickable(out)
    set_label_interval(out, {cat_f: len(cats)})
    notices = []
    if unusable:
        notices.append(
            f"{unusable} row{'s' if unusable != 1 else ''} had no numeric `{val_f}` and {'are' if unusable != 1 else 'is'} not drawn."
        )
    return Built(out, notices)


def build_tree(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """``hierarchy``: rows -> nested ``{name, children | value}``; also the count of rows with no usable value."""
    spec = config["hierarchy"]
    path, val_f = spec["path"], spec.get("value")
    root: dict[str, Any] = {}
    unusable = 0
    for row in rows:
        n = 1 if val_f is None else to_number(row.get(val_f))
        if n is None:
            unusable += 1
            continue
        node = root
        for depth, name_f in enumerate(path):
            key = _label(row.get(name_f), config)
            child = node.setdefault(key, {"": 0} if depth == len(path) - 1 else {})
            node = child
        node[""] = node.get("", 0) + n

    def render(level: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for name, sub in level.items():
            if name == "":
                continue
            kids = [k for k in sub if k != ""]
            out.append({"name": name, "children": render(sub)} if kids else {"name": name, "value": sub.get("", 0)})
        return out

    return render(root), unusable


def build_option(rows: list[dict[str, Any]], config: dict[str, Any]) -> Built:
    """Rows (already coerced, sorted, capped) and config -> the final option the browser draws."""
    option = copy.deepcopy(config["option"])
    if config.get("series_by"):
        return pivot(rows, option, config)
    if config.get("hierarchy"):
        tree, unusable = build_tree(rows, config)
        for series in _series_list(option):
            if series.get("type") in HIERARCHICAL_TYPES and "data" not in series:
                series["data"] = tree
        notices = []
        if unusable:
            notices.append(
                f"{unusable} row{'s' if unusable != 1 else ''} had no numeric value and {'are' if unusable != 1 else 'is'} not drawn."
            )
        return Built(option, notices)
    labelled = label_category_fields(rows, option, config)
    dims: list[str] = []
    for row in rows:
        dims.extend(k for k in row if k not in dims)
    urls = row_urls(rows, config)
    source = [{**row, URL_KEY: url} if url else row for row, url in zip(labelled, urls, strict=True)]
    option["dataset"] = {"dimensions": dims, "source": source}
    if any(urls):
        mark_clickable(option)
    set_label_interval(option, {f: len({r.get(f) for r in labelled}) for f in category_fields(option, config)})
    return Built(option)
