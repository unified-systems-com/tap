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

from typing import Final

__all__ = ["KEYLESS", "Keyless"]


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
