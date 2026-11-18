"""Dimension names at the edges of the grid (req-grid-dimension-names).

Every surface that reads ``Entity.dimensions`` — a Gryphon ``n.dimensions["k"]`` predicate, an
export selection, a node's read envelope — speaks dimension **names** (``tap.cloud``). Storage keys
the map by the dimension node's uuid, each value an object ``{"v": …, "src": …}``
(``req-grid-dimension-reference``, unified-systems-com/tap#711). This module is the one place a name
becomes a storage key and a stored map becomes a name-keyed view.

A name resolves only to a **live** Dimension node, never minted on demand (George, 2026-11-12,
aws-build Q48a); a name carried by two live nodes is an error naming both. Resolution reads the
live vocabulary (:mod:`tap_grid.live_dimensions`, unified-systems-com/tap#1188): the per-process
table of Dimension rows, checked current once per scope, never a query per dimension per write.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from tap_grid.live_dimensions import LiveDimension, vocabulary

# The stored shape of Entity.dimensions: uuid keys, {"v", "src"} values (unified-systems-com/tap#711).
STORAGE_IS_NAME_KEYED = False


class UnknownDimension(LookupError):
    """A dimension name or id with no live Dimension node. Nodes are declared, never minted."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"no live Dimension node is declared for {name!r}; dimensions are declared (seeded), never created on demand"
        )
        self.name = name


class AmbiguousDimension(LookupError):
    """A dimension name carried by more than one live Dimension node (Dimension.name is not unique in
    the database; writes refuse a second one, ``DuplicateDimensionName``)."""

    def __init__(self, name: str, ids: list[uuid.UUID]) -> None:
        listed = ", ".join(str(i) for i in ids)
        super().__init__(f"dimension name {name!r} is declared by {len(ids)} Dimension nodes: {listed}")
        self.name = name
        self.ids = ids


def _as_uuid(text: str) -> str | None:
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError):
        return None


def declared(name_or_id: str) -> LiveDimension:
    """The live dimension for a name or a node id.

    A uuid must be a live node's id; a name must be carried by exactly one live node.
    """
    table = vocabulary()
    as_id = _as_uuid(name_or_id)
    if as_id is not None:
        found = table.by_id.get(as_id)
        if found is None:
            raise UnknownDimension(name_or_id)
        return found
    ids = table.by_name.get(name_or_id, ())
    if not ids:
        raise UnknownDimension(name_or_id)
    if len(ids) > 1:
        raise AmbiguousDimension(name_or_id, [uuid.UUID(i) for i in ids])
    return table.by_id[ids[0]]


def resolve(name: str) -> uuid.UUID:
    """The uuid of the one live Dimension node for ``name`` (a name or an id)."""
    return uuid.UUID(declared(name).id)


def name_of(dimension_id: str) -> str | None:
    """The name of a live dimension node id, or ``None`` when no live node has that id."""
    found = vocabulary().by_id.get(_as_uuid(dimension_id) or "")
    return found.name if found is not None else None


def storage_key(name: str) -> str:
    """The key under which dimension ``name`` is stored: its live node's uuid."""
    return declared(name).id


def containment(name: str, value: str) -> dict[str, Any]:
    """The JSON-containment fragment that matches rows carrying ``name`` = ``value``."""
    return {storage_key(name): {"v": value}}


def view(stored: Mapping[str, Any] | None) -> dict[str, Any]:
    """A stored dimensions map as ``{name: value}``, for surfaces that present it.

    A key with no live node (a retired dimension's) is shown as itself. A plain string value (a row
    the data migration has not reached) is shown as is. A new dict, so a caller mutating the view
    never mutates the row.
    """
    shown: dict[str, Any] = {}
    if not stored:
        return shown
    live = vocabulary().by_id  # once per map, not once per key
    for key, entry in stored.items():
        found = live.get(_as_uuid(key) or "")
        label = found.name if found is not None else key
        shown[label] = entry.get("v") if isinstance(entry, Mapping) else entry
    return shown
