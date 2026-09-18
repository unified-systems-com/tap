"""The identity declaration sentinel (``req-grid-entity-natural-key``).

Every model declares how one of its rows is *found again* from a source's facts:

- ``NATURAL_KEY = ("<field>", …)`` names the constituting properties — the source's
  stable identifiers first; a name only where the source offers nothing better; never
  a dimension value, never a timestamp. The search over those fields is generated
  from the declaration (``req-grid-entity-natural-key-12``).
- ``NATURAL_KEY = KEYLESS`` (with a ``NATURAL_KEY_REASON``) says this type observes no
  source object at all — a batch, a job, a schedule fire — so there is nothing to
  correlate. Declared on purpose, and it must say why.
- ``None`` means *nobody has declared yet*. It is a guard failure, never a synonym
  for keyless: three states, not two.

Two things this module deliberately is **not**:

- It is not identity. ``Entity.id`` is always an assigned UUIDv7. A content-derived id
  cannot coexist with a terminal tombstone (the retired object returns, recomputes
  the same id, and every write addresses the tombstone), so ids are assigned and rows
  are found by lookup.
- It is not a hash. An earlier draft derived a UUIDv8 over SHA-256 of a canonical key
  document into the placeholder column on ``Entity``; that was withdrawn on 2026-09-17 —
  tombstoning forced lookup-by-facts, not hash-of-facts, and no two-key precedent
  stores a hashed non-id key. That column is now a **text placeholder**
  that nothing reads or writes until its named consumer arrives (a per-type composed,
  readable identifier for cross-type search; see the requirement).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

__all__ = ["KEYLESS", "AmbiguousIdentity", "Keyless", "constituting_properties", "identity_lock_key"]


class Keyless:
    """Sentinel: this entity type observes no source object.

    Distinct from "nobody has declared a key yet". Activity and registration types —
    a batch, a collection job, an elevation, a schedule fire — record something *we*
    did; there is no external thing for a later run to recognise, so there is nothing
    for a search to find. Declaring ``NATURAL_KEY = KEYLESS`` says that on purpose,
    and requires a reason alongside it.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return "KEYLESS"


KEYLESS: Final[Keyless] = Keyless()


class AmbiguousIdentity(LookupError):
    """More than one live row matched a type's declared constituting properties.

    The search never selects (``req-grid-entity-natural-key-12``): picking the first
    match would silently merge two observations, and minting a third would silently
    fork one. Until perspectives exist, two live rows sharing declared values is a
    defect — either two rows that should be one, or a declaration too thin to tell
    two source objects apart — and it is surfaced as one, naming the candidates.
    """

    def __init__(self, entity_type: str, properties: dict[str, object], candidates: list[object]) -> None:
        self.entity_type = entity_type
        self.properties = dict(properties)
        self.candidates = list(candidates)
        shown = ", ".join(str(c) for c in self.candidates[:10])
        more = "" if len(self.candidates) <= 10 else f" (+{len(self.candidates) - 10} more)"
        super().__init__(
            f"{entity_type}: {len(self.candidates)} live rows match {self.properties!r}: {shown}{more}. "
            "A search never selects — this is two rows that should be one, or a NATURAL_KEY "
            "declaration too thin to tell two source objects apart."
        )


def constituting_properties(declared: tuple[str, ...], payload: Mapping[str, object]) -> dict[str, object]:
    """The declared constituting values as a node payload carries them.

    An absent field is ``None`` — a hole — which ``find_existing`` answers with "not found"
    rather than a match on nothing. This is the one place a payload is read against the
    declaration, so the search and the lock (:func:`identity_lock_key`) see the same values.
    """
    return {name: payload.get(name) for name in declared}


def identity_lock_key(entity_type: str, properties: Mapping[str, object]) -> str | None:
    """The one string two writers resolving the same source object both lock on.

    Derived from the type and the declared values, canonically serialised, so the lock key
    is a function of the declaration and never authored a second time (``req-grid-entity-
    natural-key-13``). ``None`` when any value is a hole: nothing can be found by a hole, so
    there is nothing for two writers to serialise on.
    """
    if any(value is None or value == "" for value in properties.values()):
        return None
    return f"{entity_type}\x1f" + json.dumps(properties, sort_keys=True, separators=(",", ":"), default=str)
