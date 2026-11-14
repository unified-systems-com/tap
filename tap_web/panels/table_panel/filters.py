"""Table filter bar, views and group-by choices (req-web-stdpanel-table-filters).

The URL is the state: ``?f.<field>=<value>`` (repeatable) for an enum filter,
``?f.<field>=<text>`` for a contains filter, ``?f.<field>.min=`` / ``.max=`` for a
range, and ``?group=<field>`` for the group-by choice. A blank value is absent.

Projection rows are the search's whole result, so filtering them here is exact and
every chip's count is a true total over the rows the other filters leave (facets).
Node rows are a page; their filters reach the Search as inputs when it declares
them (``tap_grid.search.inputs_from_query``) and otherwise narrow the loaded page.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import dataclasses
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

FILTER_PREFIX = "f."
GROUP_PARAM = "group"
EMPTY_LABEL = "(none)"
DEFAULT_MAX_CHIPS = 12


@dataclass
class Chip:
    label: str
    value: str
    count: int
    active: bool
    href: str


@dataclass
class FilterView:
    field: str
    label: str
    kind: str
    chips: list[Chip] = dataclasses.field(default_factory=list)
    hidden_chips: int = 0
    text: str = ""
    low: str = ""
    high: str = ""
    clear_href: str = ""
    active: bool = False
    hidden_params: list[tuple[str, str]] = dataclasses.field(default_factory=list)


@dataclass
class ViewTab:
    label: str
    href: str
    active: bool


@dataclass
class GroupChoice:
    label: str
    href: str
    active: bool


def get_path(row: Mapping[str, Any], path: str) -> Any:
    """``a.b`` reads ``row["a"]["b"]``; a missing level is ``None``."""
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(cell_text(v) for v in value)
    return str(value)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values(params: Any, key: str) -> list[str]:
    getlist = getattr(params, "getlist", None)
    raw = getlist(key) if getlist else ([params[key]] if key in params else [])
    return [v for v in (str(x).strip() for x in raw) if v]


@dataclass
class Selection:
    """The active filters read from the URL, by field."""

    enums: dict[str, set[str]] = dataclasses.field(default_factory=dict)
    texts: dict[str, str] = dataclasses.field(default_factory=dict)
    ranges: dict[str, tuple[float | None, float | None]] = dataclasses.field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.enums or self.texts or self.ranges)


def read_selection(specs: list[dict[str, Any]], params: Any) -> Selection:
    sel = Selection()
    for spec in specs:
        name, kind = spec["field"], spec.get("kind", "enum")
        key = FILTER_PREFIX + name
        if kind == "enum":
            values = set(_values(params, key))
            if values:
                sel.enums[name] = values
        elif kind == "text":
            texts = _values(params, key)
            if texts:
                sel.texts[name] = texts[-1].lower()
        else:
            low = next(iter(_values(params, key + ".min")), "")
            high = next(iter(_values(params, key + ".max")), "")
            bounds = (_number(low), _number(high))
            if bounds != (None, None):
                sel.ranges[name] = bounds
    return sel


def _matches(row: Mapping[str, Any], sel: Selection, skip: str | None = None) -> bool:
    for name, values in sel.enums.items():
        if name != skip and (cell_text(get_path(row, name)) or EMPTY_LABEL) not in values:
            return False
    for name, term in sel.texts.items():
        if name != skip and term not in cell_text(get_path(row, name)).lower():
            return False
    for name, (low, high) in sel.ranges.items():
        if name == skip:
            continue
        number = _number(get_path(row, name))
        if number is None or (low is not None and number < low) or (high is not None and number > high):
            return False
    return True


def apply_selection(rows: list[dict[str, Any]], sel: Selection) -> list[dict[str, Any]]:
    """The rows every active filter keeps.

    TAP-IMPLEMENTS: req-web-stdpanel-table-filters@800bf9319b3e/8ad75b50086a (derivation) — the one
        definition of which rows a filter bar keeps: enum values OR within a field, fields AND
        together, text is a case-insensitive contains, range is inclusive on a number.
    """
    if sel.is_empty():
        return rows
    return [row for row in rows if _matches(row, sel)]


def _href(params: Any, *, drop: tuple[str, ...] = (), add: list[tuple[str, str]] | None = None) -> str:
    """``?query`` relative to the page: the current parameters minus ``drop`` keys plus ``add``."""
    items: list[tuple[str, str]] = []
    lists = params.lists() if hasattr(params, "lists") else ((k, [v]) for k, v in dict(params).items())
    for key, values in lists:
        if key in drop or key in ("offset",):
            continue
        items.extend((key, v) for v in values)
    items.extend(add or [])
    query = urlencode(items)
    return f"?{query}" if query else "?"


def _filter_keys(specs: list[dict[str, Any]]) -> tuple[str, ...]:
    keys: list[str] = []
    for spec in specs:
        key = FILTER_PREFIX + spec["field"]
        keys.extend((key, key + ".min", key + ".max"))
    return tuple(keys)


def build_bar(
    rows: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    views: list[dict[str, Any]],
    group_choices: list[str],
    group_field: str | None,
    params: Any,
    labels: Mapping[str, str],
) -> dict[str, Any]:
    """Everything the filter bar renders, with chip counts faceted over the other filters."""
    sel = read_selection(specs, params)
    out: list[FilterView] = []
    for spec in specs:
        name, kind = spec["field"], spec.get("kind", "enum")
        key = FILTER_PREFIX + name
        view = FilterView(field=name, label=spec.get("label") or labels.get(name) or name, kind=kind)
        view.clear_href = _href(params, drop=(key, key + ".min", key + ".max"))
        view.hidden_params = [
            (k, v)
            for k, vs in (params.lists() if hasattr(params, "lists") else ((k, [v]) for k, v in dict(params).items()))
            for v in vs
            if k not in (key, key + ".min", key + ".max", "offset")
        ]
        if kind == "enum":
            selected = sel.enums.get(name, set())
            view.active = bool(selected)
            counts = Counter(cell_text(get_path(r, name)) or EMPTY_LABEL for r in rows if _matches(r, sel, skip=name))
            for value in selected:
                counts.setdefault(value, 0)
            if not selected and len(counts) < 2:
                continue
            declared = {v: i for i, v in enumerate(spec.get("order") or [])}
            ordered = sorted(
                counts.items(),
                key=lambda kv: (kv[0] not in selected, declared.get(kv[0], len(declared)), -kv[1], kv[0].lower()),
            )
            limit = spec.get("max_chips", DEFAULT_MAX_CHIPS)
            shown = [kv for i, kv in enumerate(ordered) if i < limit or kv[0] in selected]
            view.hidden_chips = len(ordered) - len(shown)
            others = [(key, v) for v in sorted(selected)]
            for value, count in shown:
                active = value in selected
                toggled = [(k, v) for k, v in others if v != value] if active else [*others, (key, value)]
                view.chips.append(
                    Chip(label=value, value=value, count=count, active=active, href=_href(params, drop=(key,), add=toggled))
                )
        elif kind == "text":
            view.text = next(iter(_values(params, key)), "")
            view.active = bool(view.text)
        else:
            view.low = next(iter(_values(params, key + ".min")), "")
            view.high = next(iter(_values(params, key + ".max")), "")
            view.active = name in sel.ranges
        out.append(view)

    filter_keys = _filter_keys(specs)
    tabs: list[ViewTab] = []
    if views:
        current = {k: set(v) for k, v in sel.enums.items()}
        all_active = sel.is_empty()
        tabs.append(ViewTab(label="All", href=_href(params, drop=(*filter_keys, GROUP_PARAM)), active=all_active))
        for v in views:
            add = [(FILTER_PREFIX + f, value) for f, values in v["filters"].items() for value in values]
            if v.get("group_by"):
                add.append((GROUP_PARAM, v["group_by"]))
            want = {f: set(values) for f, values in v["filters"].items()}
            tabs.append(
                ViewTab(
                    label=v["label"],
                    href=_href(params, drop=(*filter_keys, GROUP_PARAM), add=add),
                    active=not sel.texts and not sel.ranges and current == want,
                )
            )

    choices: list[GroupChoice] = []
    if group_choices:
        choices.append(GroupChoice(label="None", href=_href(params, drop=(GROUP_PARAM,), add=[(GROUP_PARAM, "none")]), active=group_field is None))
        for name in group_choices:
            choices.append(
                GroupChoice(
                    label=labels.get(name) or name,
                    href=_href(params, drop=(GROUP_PARAM,), add=[(GROUP_PARAM, name)]),
                    active=group_field == name,
                )
            )

    return {
        "filters": out,
        "views": tabs,
        "group_choices": choices,
        "active": not sel.is_empty(),
        "clear_all_href": _href(params, drop=filter_keys),
    }


def resolve_group(config_group: dict[str, Any] | None, params: Any) -> dict[str, Any] | None:
    """The group-by spec for this render: the URL's ``group`` choice when it is one of ``choices``."""
    if not config_group:
        return None
    choices = config_group.get("choices") or []
    wanted = next(iter(_values(params, GROUP_PARAM)), "")
    if wanted == "none" and choices:
        return None
    if not wanted and choices and config_group.get("initial") == "none":
        return None
    if wanted and wanted in choices:
        if wanted == config_group.get("field") and config_group.get("mode", "prefix") == "prefix":
            return config_group
        return {"field": wanted, "mode": "value"}
    return config_group
