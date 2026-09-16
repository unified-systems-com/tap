"""Derived natural keys — the single derivation (``req-grid-entity-natural-key``).

A natural key answers *"is this the same source object?"*. It is derived, stored on
``Entity.natural_key``, invariant across dimensions, and deliberately **not** unique:
correlation is the point, so a uniqueness constraint would defeat the feature.

Three things this module is deliberately *not*:

- It is **not** identity. ``Entity.id`` is always an assigned UUIDv7. Nothing keys on
  a natural key; it is a lookup and correlation handle only.
- It is **not** supplied by callers. The service layer derives it from the model's
  declared key document, so a collector cannot forge one
  (``req-grid-entity-natural-key-2``). The GRIFT import envelope is
  ``additionalProperties: false`` and omits the field, which enforces that for free.
- It is **not** versioned separately. A key document is part of the model definition,
  so redefining one is a model change and lands as a Django migration
  (``req-grid-entity-natural-key-8``). Per-row attribution, when it is wanted, comes
  from BaseModel versioning — ``unified-systems-com/tap#475``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, Final

__all__ = [
    "KEYLESS",
    "Keyless",
    "NaturalKeyError",
    "TAP_NATURAL_KEY_NAMESPACE",
    "canonicalize",
    "key_document",
]

# The namespace every natural key is derived under. Changing this value invalidates
# every stored key in every grid, so it is a module constant rather than a setting:
# a deployment must not be able to make its keys incomparable with anyone else's.
TAP_NATURAL_KEY_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "natural-key.tap")


class Keyless:
    """Sentinel: this entity type observes no source object.

    Distinct from "nobody has declared a key yet". Activity and registration types —
    a batch, a collection job, an elevation, a schedule fire — record something *we*
    did; there is no external thing for a later run to recognise, so there is nothing
    for a key to correlate. Declaring ``NATURAL_KEY = KEYLESS`` says that on purpose,
    and requires a reason alongside it.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return "KEYLESS"


KEYLESS: Final[Keyless] = Keyless()


class NaturalKeyError(Exception):
    """A key document could not be built from a declaration that should have worked.

    Raised for programming errors — a constituting property that does not exist on
    the model, or a value outside the permitted domain. A *missing* value is not an
    error: see :func:`key_document`, which returns ``None``.
    """


def canonicalize(document: Mapping[str, str | int]) -> str:
    """Serialize a key document to its one canonical form.

    ``sort_keys`` plus compact separators plus ``ensure_ascii=False``, matching the
    in-house precedent at ``tap/boot_records.py``.

    **Why this and not RFC 8785 (JCS).** Ruled 2026-09-15. JCS and this form differ in
    exactly two places: number serialization (JCS mandates ECMAScript
    ``Number::toString``) and object-key ordering for characters outside the BMP (JCS
    orders by UTF-16 code unit, Python by code point). :func:`key_document` forbids
    the inputs that could reach either difference — no floats, and ASCII property
    names — so this form is *provably* equivalent to JCS over the domain we permit,
    rather than assumed equivalent over one we do not. That is cheaper than taking a
    dependency to handle cases we reject anyway.

    If a key document ever genuinely needs a value outside that domain, the escape
    hatch is a versioned key derivation (``tap#475``), not a quiet widening here:
    changing what this function accepts changes every key it has ever produced.
    """
    return json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check_property_name(name: str) -> None:
    if not name.isascii():
        raise NaturalKeyError(
            f"constituting property name {name!r} is not ASCII; key ordering would "
            "diverge from RFC 8785 outside the BMP, which is the constraint "
            "canonicalize() rests on"
        )


def _check_value(name: str, value: object) -> None:
    # bool is checked first and explicitly: in Python `bool` is a subclass of `int`,
    # so an isinstance(value, int) test admits True/False silently, and `True` and
    # `1` would then canonicalize differently while meaning the same thing.
    if isinstance(value, bool):
        raise NaturalKeyError(
            f"constituting property {name!r} is a bool; a boolean cannot constitute "
            "identity (it partitions the world in two, it does not name a thing)"
        )
    if isinstance(value, float):
        raise NaturalKeyError(
            f"constituting property {name!r} is a float; identity must not rest on "
            "float equality, and JCS number serialization is the one case where this "
            "module's canonical form diverges. Use a string."
        )
    if not isinstance(value, (str, int)):
        raise NaturalKeyError(
            f"constituting property {name!r} is {type(value).__name__}; only str and "
            "int may constitute a natural key"
        )


def key_document(
    entity_type: str,
    properties: Mapping[str, Any],
) -> dict[str, str | int] | None:
    """Build the key document for ``entity_type`` from ``properties``.

    The fully-qualified ``entity_type`` is a member of the document, not a hidden
    namespace: two types whose constituting values happen to coincide must produce
    different keys, and a reader of the document should be able to see why
    (``req-grid-entity-natural-key-4``).

    Returns ``None`` when any constituting value is absent — ``None`` or an empty
    string. That is a **data** condition, not a bug: a repository whose payload
    carried no stable id genuinely cannot be correlated, and the honest record is a
    null key rather than a key derived from a hole. Raises
    :class:`NaturalKeyError` for a value in the wrong *domain*, which is a bug.
    """
    document: dict[str, str | int] = {"type": entity_type}
    for name in sorted(properties):
        _check_property_name(name)
        value = properties[name]
        if value is None or value == "":
            return None
        _check_value(name, value)
        document[name] = value
    return document


def natural_key(entity_type: str, properties: Mapping[str, Any]) -> uuid.UUID | None:
    """The natural key for ``entity_type`` and its constituting ``properties``.

    ``uuid5`` over the canonicalized key document. Deterministic, reproducible by
    anyone holding the same document, and unchanged by anything not *in* the document
    — which is what makes it invariant across dimensions
    (``req-grid-entity-natural-key-3``).
    """
    document = key_document(entity_type, properties)
    if document is None:
        return None
    return uuid.uuid5(TAP_NATURAL_KEY_NAMESPACE, canonicalize(document))
