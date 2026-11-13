"""Dimension names at the edges of the grid (req-grid-dimension-names).

Every surface that reads ``Entity.dimensions`` — a Gryphon ``n.dimensions["k"]`` predicate, an
export selection, a node's read envelope — speaks dimension **names** (``tap.cloud``). Storage is
moving from name keys to dimension-node uuids (``{<uuid>: {"v": …, "src": …}}``,
``req-grid-dimension-reference``, unified-systems-com/tap#711). This module is the one place a
name becomes a storage key and a stored map becomes a name-keyed view, so that move changes this
module and nothing at the surfaces.

Today the map is still name-keyed (``STORAGE_IS_NAME_KEYED``), so :func:`storage_key` is the name
itself and :func:`view` is a copy: routing a reader through here changes no result and runs no
query. The strict rule — a name resolves only to a **declared** Dimension node, never minted on
demand (George, 2026-11-12, aws-build Q48a), and a name carried by two nodes is an error naming
both — is :func:`resolve`, which the storage flip switches every path onto. It is not consulted on
the name-keyed shape, because plugins' Dimension nodes are not all seeded yet; refusing an
unseeded name before the flip would break reads that work today.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

# The stored shape of Entity.dimensions. True until the storage flip (unified-systems-com/tap#711)
# lands: keys are dimension names and values are plain strings.
STORAGE_IS_NAME_KEYED = True


class UnknownDimension(LookupError):
    """A dimension name with no declared Dimension node. Nodes are declared, never minted."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"no Dimension node is named {name!r}; dimensions are declared (seeded), never created on demand"
        )
        self.name = name


class AmbiguousDimension(LookupError):
    """A dimension name carried by more than one Dimension node (Dimension.name is not unique)."""

    def __init__(self, name: str, ids: list[uuid.UUID]) -> None:
        listed = ", ".join(str(i) for i in ids)
        super().__init__(f"dimension name {name!r} is carried by {len(ids)} Dimension nodes: {listed}")
        self.name = name
        self.ids = ids


def resolve(name: str) -> uuid.UUID:
    """The uuid of the one declared Dimension node named ``name``.

    Raises :class:`UnknownDimension` when no node carries the name and :class:`AmbiguousDimension`
    when several do. Live nodes only: a retired dimension resolves to nothing.
    """
    from tap_grid.models import Dimension

    # live() is typed against BaseModel, so django-stubs cannot see Dimension.name.
    live = Dimension.objects.live().filter(name=name)  # type: ignore[misc]
    ids = list(live.order_by("entity_id").values_list("entity_id", flat=True))
    if not ids:
        raise UnknownDimension(name)
    if len(ids) > 1:
        raise AmbiguousDimension(name, ids)
    return ids[0]


def storage_key(name: str) -> str:
    """The key under which dimension ``name`` is stored in ``Entity.dimensions``.

    On the name-keyed shape this is ``name`` itself, with no lookup. After the storage flip it is
    the declared node's uuid (:func:`resolve`), and an unknown or ambiguous name is refused.
    """
    if STORAGE_IS_NAME_KEYED:
        return name
    return str(resolve(name))  # pragma: no cover - switched on by the storage flip


def containment(name: str, value: str) -> dict[str, Any]:
    """The JSON-containment fragment that matches rows carrying ``name`` = ``value``."""
    if STORAGE_IS_NAME_KEYED:
        return {storage_key(name): value}
    return {storage_key(name): {"v": value}}  # pragma: no cover - switched on by the storage flip


def view(stored: Mapping[str, Any] | None) -> dict[str, Any]:
    """A stored dimensions map as ``{name: value}``, for surfaces that present it.

    A copy, so a caller mutating the view never mutates the row. On the name-keyed shape the
    stored map already is the view.
    """
    if STORAGE_IS_NAME_KEYED:
        return dict(stored or {})
    raise NotImplementedError("the uuid-keyed view lands with the storage flip")  # pragma: no cover
