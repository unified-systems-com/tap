"""Changed, or re-observed unchanged: the one comparison an update-shaped write is classified by.

The write pipeline takes an object's stored values before it applies a payload and compares them,
field by field, with the values after it. FLIP, the history decision, the version counter and the
batch's record of the operation all read that one result; none re-derives it
(req-grid-flip-change rule 1, req-grid-history-reobservation rule 5).
"""

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from tap_grid.flip import _get_service_writeable_fields, is_flip_enabled

#: The fields the grid manages on every typed row. They are outside FLIP (req-grid-flip-default-3)
#: and outside the comparison (req-grid-flip-change rule 7). This is the one place the list is
#: kept; a test fails when a field is added to ``BaseModel`` without being listed here.
#: The spine copies are here (req-grid-entity-spine-copies rule 14): the database writes them, so a
#: write whose only effect on a row is a changed copy is not a change to that row.
SYSTEM_MANAGED_FIELDS: frozenset[str] = frozenset({"entity", "flip_map", "spine_deleted_at", "spine_dimensions"})


@dataclass(frozen=True)
class WriteClassification:
    """What one update-shaped operation did to the object it named.

    Attributes:
        changed_fields: Fields whose stored value differs after the write. Every stored field of the
            row is compared, so a value the model's write hook set counts, though only the
            service-writeable ones earn a FLIP entry.
        flip_fields: The fields FLIP tracks for this write: the service-writeable surface and
            whatever the payload named.
        first_asserted: Fields the payload named that had no FLIP entry and whose value did not move.
        spine_changed: A spine value differs: the derived name or natural key, or a value the caller
            writes itself in this batch (the GRIFT envelope's name and dimensions).
    """

    changed_fields: frozenset[str]
    first_asserted: frozenset[str]
    spine_changed: bool
    flip_fields: frozenset[str] = frozenset()

    @property
    def changed(self) -> bool:
        """True when the operation is a change; False when it re-observed the object unchanged."""
        return bool(self.changed_fields or self.first_asserted or self.spine_changed)

    @property
    def stamped(self) -> list[str]:
        """The fields whose FLIP entry moves to the writing batch."""
        return sorted((self.changed_fields & self.flip_fields) | self.first_asserted)


def compared_fields(model_cls: type) -> frozenset[str]:
    """The fields a write is compared over: the service-writeable surface, system-managed fields excluded."""
    return frozenset(_get_service_writeable_fields(model_cls)) - SYSTEM_MANAGED_FIELDS


def stored_fields(model_cls: type) -> frozenset[str]:
    """Every column the typed row stores, system-managed fields excluded.

    A write is unchanged only when none of these moved, so a value a model's write hook derives
    (``BaseModel.prepare_for_write``) is never lost to a skipped save, whether or not it is on
    the service-writeable surface.
    """
    meta = getattr(model_cls, "_meta", None)
    names = {field.name for field in meta.concrete_fields} if meta is not None else set()
    return frozenset(names) - SYSTEM_MANAGED_FIELDS


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
        values={
            name: copy.deepcopy(_stored(instance, name))
            for name in compared_fields(type(instance)) | stored_fields(type(instance)) | named
        },
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

    TAP-IMPLEMENTS: req-grid-flip-change@e20cc3805533/8a9b44fc800c (derivation) — the one
        stored-versus-written comparison, and the stamped set it yields: changed fields, plus
        named fields asserted for the first time.
    TAP-IMPLEMENTS: req-grid-history-reobservation@c613b5f23bfe/8a9b44fc800c (derivation) — the one
        place an update-shaped operation is ruled changed or re-observed unchanged; the save, the
        version, FLIP and the batch's record all read this result.
    """
    fields = frozenset(before.values)
    changed = frozenset(name for name in fields if not values_equal(before.values[name], _stored(instance, name)))
    flip_fields = (compared_fields(type(instance)) | named) & fields
    first_asserted: frozenset[str] = frozenset()
    if is_flip_enabled(type(instance)):
        # A named field with no entry yet is asserted for the first time, although its value did
        # not move: a null nobody had looked at becomes a null a source asserted (rule 4).
        first_asserted = frozenset(name for name in (named & fields) - changed if name not in before.flip_keys)
    spine_changed = (
        caller_spine_change or instance.get_name() != before.name or instance.derive_natural_key() != before.derived_key
    )
    return WriteClassification(
        changed_fields=changed, first_asserted=first_asserted, spine_changed=spine_changed, flip_fields=flip_fields
    )


def _refuse_keyed_dimension_change(entity_type: str, persisted: dict[str, Any], expected: dict[str, Any]) -> None:
    """A replace never re-keys a row: a keyed dimension's stored value stays (``req-grid-entity-natural-key-31``,
    unified-systems-com/tap#1186). Changing it, removing it, or adding it to a row stored without one raises
    ``ServiceConstraintError``."""
    from tap_grid.natural_key import constituting_properties, keyed_dimension_entries
    from tap_grid.registry import get_model_class

    try:
        model = get_model_class(entity_type)
    except KeyError:
        return
    entries = keyed_dimension_entries(model)
    if not entries:
        return
    before = constituting_properties(entries, {}, persisted)
    after = constituting_properties(entries, {}, expected)
    # Any difference, including a value arriving on a row stored without one: a keyed row acquires its
    # identity at create, never later (PR# 1356 - tap review, round 2).
    moved = [entry for entry in entries if before[entry] != after[entry]]
    if moved:
        from tap_grid.exceptions import ServiceConstraintError

        detail = ", ".join(f"{entry}: {before[entry]!r} -> {after[entry]!r}" for entry in moved)
        raise ServiceConstraintError(
            f"{entity_type}: a keyed dimension is fixed once written and a replace cannot change it ({detail}); "
            "a different value is a different row (req-grid-entity-natural-key-31)."
        )


def spine_delta(intent: dict[str, Any] | None) -> dict[str, Any]:
    """The spine values a caller's intent would change on the stored row: ``name``, ``dimensions``, or neither.

    The intent is the GRIFT envelope of a node the import replaces. It is read from one definition
    in two places: by the write pipeline, under the target's row lock, to classify the operation
    (req-grid-history-reobservation rule 2), and by the importer's post-pass that writes the
    values, in the same transaction and so under the same lock.
    """
    if not intent:
        return {}
    envelope_name = intent.get("envelope_name")
    # The envelope is authoritative for the caller's values on a replace, an empty one included:
    # {} clears them (Issue# 608 - tap; aws-build Q46b). The type's defaults are re-merged under
    # it, src default, as a create builds them, so a collector's run never wipes them (aws-build
    # Q59 D6; req-grid-dimension-reference-7).
    from tap_grid.models import Entity

    # Read the persisted spine values to decide whether anything needs to
    # change. A no-op update should not bump updated_at.
    try:
        persisted = Entity.objects.values("name", "dimensions").get(pk=uuid.UUID(str(intent["entity_id"])))
    except Entity.DoesNotExist:
        return {}
    stored_dims = intent_dimensions(intent, persisted["dimensions"] or {})

    _refuse_keyed_dimension_change(intent.get("entity_type") or "", persisted["dimensions"] or {}, stored_dims)

    delta: dict[str, Any] = {}
    if envelope_name is not None and envelope_name != persisted["name"]:
        delta["name"] = envelope_name
    if stored_dims != (persisted["dimensions"] or {}):
        delta["dimensions"] = dict(stored_dims)
    return delta


def intent_dimensions(intent: dict[str, Any], persisted: dict[str, Any]) -> dict[str, Any]:
    """The dimension map a replaced node's GRIFT envelope leaves on its spine row, given the stored map.

    The one place the importer's expected map is built, read by :func:`spine_delta` to classify the
    write and decide the post-pass, and by ``BaseModel.save`` for the history row the replace writes
    (req-grid-entity-spine-copies rule 12). Built where every stored map is
    (``dimension_map.settle``): the type's defaults, the envelope over them, and the grid's own
    derived entries (the ``tap.time`` dimension) carried from the stored map. An envelope never
    carries those, so leaving them out would make every re-import of a row that has one differ from
    the spine, be classified changed, and have the post-pass strip the entry it just compared against.
    """
    from tap_grid.dimension_map import settle
    from tap_grid.registry import get_model_class

    try:
        type_defaults = dict(getattr(get_model_class(intent.get("entity_type") or ""), "DEFAULT_DIMENSIONS", {}) or {})
    except KeyError:
        type_defaults = {}
    return dict(settle(type_defaults, intent.get("envelope_dims") or {}, persisted=persisted))
