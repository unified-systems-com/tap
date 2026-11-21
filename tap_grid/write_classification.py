"""Changed, or re-observed unchanged: the one comparison an update-shaped write is classified by.

The write pipeline takes an object's stored values before it applies a payload and compares them,
field by field, with the values after it. FLIP, the history decision, the version counter and the
batch's record of the operation all read that one result; none re-derives it
(req-grid-flip-change rule 1, req-grid-history-reobservation rule 5).
"""

import copy
from dataclasses import dataclass
from typing import Any

from tap_grid.flip import _get_service_writeable_fields, is_flip_enabled

#: The fields the grid manages on every typed row. They are outside FLIP (req-grid-flip-default-3)
#: and outside the comparison (req-grid-flip-change rule 7). This is the one place the list is
#: kept; a test fails when a field is added to ``BaseModel`` without being listed here.
SYSTEM_MANAGED_FIELDS: frozenset[str] = frozenset({"entity", "batch_id", "flip_map"})


@dataclass(frozen=True)
class WriteClassification:
    """What one update-shaped operation did to the object it named.

    Attributes:
        changed_fields: Service-writeable fields whose stored value differs after the write.
        first_asserted: Fields the payload named that had no FLIP entry and whose value did not move.
        spine_changed: A spine value differs: the derived name or natural key, or a value the caller
            writes itself in this batch (the GRIFT envelope's name and dimensions).
    """

    changed_fields: frozenset[str]
    first_asserted: frozenset[str]
    spine_changed: bool

    @property
    def changed(self) -> bool:
        """True when the operation is a change; False when it re-observed the object unchanged."""
        return bool(self.changed_fields or self.first_asserted or self.spine_changed)

    @property
    def stamped(self) -> list[str]:
        """The fields whose FLIP entry moves to the writing batch."""
        return sorted(self.changed_fields | self.first_asserted)


def compared_fields(model_cls: type) -> frozenset[str]:
    """The fields a write is compared over: the service-writeable surface, system-managed fields excluded."""
    return frozenset(_get_service_writeable_fields(model_cls)) - SYSTEM_MANAGED_FIELDS


def _stored(instance: Any, field_name: str) -> Any:
    """A field's value as it is compared: a relation by id, anything else by value."""
    try:
        model_field = instance._meta.get_field(field_name)
    except Exception:  # noqa: BLE001 — a schema property with no model field compares by attribute
        return getattr(instance, field_name, None)
    if getattr(model_field, "is_relation", False) and hasattr(model_field, "attname"):
        return getattr(instance, model_field.attname)
    return getattr(instance, field_name)


@dataclass(frozen=True)
class Snapshot:
    """An object's compared values, its derived spine values and its FLIP keys, taken before a payload is applied."""

    values: dict[str, Any]
    name: str
    derived_key: Any
    flip_keys: frozenset[str]


def snapshot(instance: Any, named: frozenset[str] = frozenset()) -> Snapshot:
    """Take the stored state an update-shaped write will be compared against.

    ``named`` is what the payload names. A type that publishes no schema for the verb accepts
    fields outside ``compared_fields``; they are compared too, so a write is never dropped as
    unchanged because the field it moved was not on the published surface.
    """
    return Snapshot(
        values={name: copy.deepcopy(_stored(instance, name)) for name in compared_fields(type(instance)) | named},
        name=instance.get_name(),
        derived_key=instance.derive_natural_key(),
        flip_keys=frozenset(instance.flip_map or {}),
    )


def values_equal(left: Any, right: Any) -> bool:
    """Equality by JSON value, type-sensitive (req-grid-flip-change rule 6).

    ``True`` and ``1`` differ, so ``[False]`` and ``[0]`` do; ``{}`` and ``{"k": None}`` differ; the
    order of an object's keys does not matter and the order of a list does. An integer and a float
    are one JSON number, so ``1`` equals ``1.0``.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(values_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(values_equal(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, (dict, list, tuple)) or isinstance(right, (dict, list, tuple)):
        return False
    return bool(left == right)


def classify(
    instance: Any, before: Snapshot, named: frozenset[str], *, caller_spine_change: bool = False
) -> WriteClassification:
    """Compare an instance, after its payload was applied and validated, with its snapshot.

    Args:
        instance: The object with the payload applied and its values cleaned to their stored types.
        before: The snapshot taken before the payload was applied.
        named: The fields the payload named, including a field reset from an explicit null.
        caller_spine_change: The caller writes a spine value itself in this batch and it differs.

    Returns:
        The classification every later step of the operation reads.

    TAP-IMPLEMENTS: req-grid-flip-change@eb97028976dd/3c9970e2a6c7 (derivation) — the one
        stored-versus-written comparison, and the stamped set it yields: changed fields, plus
        named fields asserted for the first time.
    TAP-IMPLEMENTS: req-grid-history-reobservation@a375d6cd586c/3c9970e2a6c7 (derivation) — the one
        place an update-shaped operation is ruled changed or re-observed unchanged; the save, the
        version, FLIP and the batch's record all read this result.
    """
    fields = frozenset(before.values)
    changed = frozenset(name for name in fields if not values_equal(before.values[name], _stored(instance, name)))
    first_asserted: frozenset[str] = frozenset()
    if is_flip_enabled(type(instance)):
        # A named field with no entry yet is asserted for the first time, although its value did
        # not move: a null nobody had looked at becomes a null a source asserted (rule 4).
        first_asserted = frozenset(name for name in (named & fields) - changed if name not in before.flip_keys)
    spine_changed = (
        caller_spine_change or instance.get_name() != before.name or instance.derive_natural_key() != before.derived_key
    )
    return WriteClassification(changed_fields=changed, first_asserted=first_asserted, spine_changed=spine_changed)
