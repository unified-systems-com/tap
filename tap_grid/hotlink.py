"""TAP Hotlink System — formalizes embedded reference ↔ edge synchronization.

Models declare HOTLINKS to describe where identifiers live inside their fields
and how those identifiers map onto graph edges. The service layer uses these
declarations to validate graph consistency when saving a node.

Design:
  - HOTLINKS is authoritative on the model. Edges carry instance participation
    data (properties.hotlink) but do not redefine contract semantics.
  - Validation runs only when the instance has an existing entity_id (Option A:
    first-save skip). New instances have no edges yet, so comparison is deferred.
  - The selector system is pluggable; v1 supports 'simple_path' only.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured, ValidationError

if TYPE_CHECKING:
    from tap_grid.models import BaseModel


# ---------------------------------------------------------------------------
# Hotlink definition schema (req-grid-hotlink-model)
# ---------------------------------------------------------------------------

_HOTLINK_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "field",
        "selector_type",
        "selector",
        "edge_direction",
        "edge_type",
        "mode",
    }
)

_VALID_SELECTOR_TYPES: frozenset[str] = frozenset({"simple_path", "scalar"})
_VALID_EDGE_DIRECTIONS: frozenset[str] = frozenset({"outbound", "inbound"})
_VALID_MODES: frozenset[str] = frozenset({"exists", "unique", "exact"})

# The shape of an edge's `properties.hotlink` participation payload
# (req-grid-hotlink-edge-data). Owned HERE, next to the machinery that writes
# and consumes it — edge-type property schemas must NOT redeclare it
# (req-grid-edge-schema-required-5, spec-grid-edge.md): one shape, one owner.
# `value` is deliberately just "string": exact/unique-mode validation already
# checks it against the real model field content, which is stricter than any
# pattern could be.
EDGE_HOTLINK_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["model", "spec", "value"],
    "properties": {
        "model": {
            "type": "string",
            "description": "Registered model name whose HOTLINKS declaration this edge participates in.",
        },
        "spec": {
            "type": "string",
            "description": "The HOTLINKS entry name on that model this edge mirrors.",
        },
        "value": {
            "type": "string",
            "description": "The extracted identifier this edge asserts; checked against the field by hotlink validation.",
        },
    },
}


def validate_edge_hotlink_payload(edge_type: str, payload: Any) -> None:
    """Validate an edge's `properties.hotlink` payload against the system schema.

    The system-owned half of edge property validation
    (req-grid-edge-schema-required-5): called by
    `tap_grid.constraints.validate_edge_properties` for every edge write that
    carries a `hotlink` key, regardless of edge type. Semantic validation
    (does the value actually mirror the field?) remains `validate_hotlinks`;
    this is the cheap structural gate in front of it.

    Raises:
        EdgePropertyValidationError: when the payload is not the declared shape.
    """
    import jsonschema

    from tap.jsonfiles import jsonschema_validate
    from tap_grid.exceptions import EdgePropertyValidationError

    try:
        jsonschema_validate(payload, EDGE_HOTLINK_PAYLOAD_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise EdgePropertyValidationError(
            f"Edge type '{edge_type}' hotlink payload failed the system schema "
            f"(req-grid-hotlink-edge-data): {exc.message}"
        ) from exc


def _check_hotlinks(cls: type) -> None:
    """Enforce HOTLINKS startup invariants at class-definition time.

    Called from BaseModel.__init_subclass__ when a subclass declares HOTLINKS
    in its own class body. Checks performed:
      1. HOTLINKS is a list.
      2. Each entry is a dict with all required keys.
      3. 'name' is a non-empty string and is unique within the list.
      4. 'selector_type' is a supported value.
      5. 'edge_direction' is a supported value.
      6. 'mode' is a supported value.

    Raises:
        ImproperlyConfigured: On any violation.
    """
    hotlinks: list = cls.__dict__.get("HOTLINKS", [])

    if not isinstance(hotlinks, list):
        raise ImproperlyConfigured(f"{cls.__name__}.HOTLINKS must be a list, got {type(hotlinks).__name__}.")

    seen_names: set[str] = set()

    for i, defn in enumerate(hotlinks):
        prefix = f"{cls.__name__}.HOTLINKS[{i}]"

        if not isinstance(defn, dict):
            raise ImproperlyConfigured(f"{prefix}: each entry must be a dict, got {type(defn).__name__}.")

        missing = _HOTLINK_REQUIRED_KEYS - set(defn.keys())
        if missing:
            raise ImproperlyConfigured(f"{prefix}: missing required keys: {sorted(missing)}.")

        name = defn["name"]
        if not isinstance(name, str) or not name:
            raise ImproperlyConfigured(f"{prefix}: 'name' must be a non-empty string.")
        if name in seen_names:
            raise ImproperlyConfigured(f"{prefix}: duplicate hotlink name {name!r}.")
        seen_names.add(name)

        selector_type = defn["selector_type"]
        if selector_type not in _VALID_SELECTOR_TYPES:
            raise ImproperlyConfigured(
                f"{prefix}: 'selector_type' {selector_type!r} is not supported. "
                f"Valid values: {sorted(_VALID_SELECTOR_TYPES)}."
            )

        edge_direction = defn["edge_direction"]
        if edge_direction not in _VALID_EDGE_DIRECTIONS:
            raise ImproperlyConfigured(
                f"{prefix}: 'edge_direction' {edge_direction!r} is not supported. "
                f"Valid values: {sorted(_VALID_EDGE_DIRECTIONS)}."
            )

        mode = defn["mode"]
        if mode not in _VALID_MODES:
            raise ImproperlyConfigured(
                f"{prefix}: 'mode' {mode!r} is not supported. " f"Valid values: {sorted(_VALID_MODES)}."
            )


# ---------------------------------------------------------------------------
# Selector backends (req-grid-hotlink-selector)
# ---------------------------------------------------------------------------


def _simple_path_extract(value: Any, selector: str) -> set[str]:
    """Extract identifiers using a TAP simple-path selector.

    Traverses structured JSON via a dot-separated path. A '*' segment fans out
    over all values of a dict or all items of a list. Leaf values are coerced
    to strings. Non-traversable nodes and missing keys are silently skipped.

    Example:
        selector "columns.*.rows.*.panel-id" applied to:
        {"columns": {"col-1": {"rows": {"row-1": {"panel-id": "main"}}}}}
        → {"main"}

    Args:
        value: The JSON field value to traverse.
        selector: Dot-separated path expression; '*' is a wildcard fan-out.

    Returns:
        Set of string identifier values found at leaf positions.
    """
    segments = selector.split(".")
    current: list[Any] = [value]

    for segment in segments:
        next_level: list[Any] = []
        for node in current:
            if segment == "*":
                if isinstance(node, dict):
                    next_level.extend(node.values())
                elif isinstance(node, list):
                    next_level.extend(node)
                # non-traversable nodes silently dropped
            else:
                if isinstance(node, dict) and segment in node:
                    next_level.append(node[segment])
                # missing keys silently dropped
        current = next_level

    result: set[str] = set()
    for leaf in current:
        if leaf is not None:
            result.add(str(leaf))
    return result


def _scalar_extract(value: Any, selector: str) -> set[str]:
    """Extract the single identifier carried directly by a scalar field.

    For a field whose value *is* the identifier (e.g. a URL or id stored in a
    CharField), the identifier set is just that value. ``simple_path`` cannot
    serve this case — it traverses JSON structure and yields nothing for a bare
    scalar — yet scalar identifier fields are the common hotlink shape. An empty
    or null value yields the empty set (no reference, hence no expected edge).
    The ``selector`` argument is unused for this backend (conventionally "").
    """
    if value is None or value == "":
        return set()
    return {str(value)}


def extract_identifiers(field_value: Any, selector_type: str, selector: str) -> set[str]:
    """Extract identifiers from a field value using the given selector backend.

    Args:
        field_value: The model field value to inspect.
        selector_type: Backend identifier. ``simple_path`` traverses structured
            JSON; ``scalar`` returns the field's own value as the sole identifier.
        selector: Backend-specific selector expression.

    Returns:
        Set of string identifier values.

    Raises:
        ValueError: If selector_type is not a recognized backend.
    """
    if selector_type == "simple_path":
        return _simple_path_extract(field_value, selector)
    if selector_type == "scalar":
        return _scalar_extract(field_value, selector)
    raise ValueError(f"Unsupported selector_type: {selector_type!r}")


# ---------------------------------------------------------------------------
# Hotlink validation (req-grid-hotlink-validation)
# ---------------------------------------------------------------------------


def validate_hotlinks(instance: BaseModel) -> None:
    """Validate hotlink consistency for a model instance.

    For each hotlink definition declared on the model class:
      1. Extracts identifiers from the declared field using the selector.
      2. Queries the corresponding edges, filtering by hotlink.model and hotlink.spec.
      3. Compares extracted identifiers to edge hotlink.value using the declared mode.

    Skips validation when instance.entity_id is None (first-save / unsaved instance).
    Edges and the node are not yet synchronised at that point (Option A).

    Deferred mode (req-grid-hotlink-deferred): when the deferred-hotlink-check
    queue is active for this execution context (set up by write_batch), append
    (model_cls, entity_id) and return without validating. The batch's pre-commit
    consistency phase drains the queue after every node and edge has landed,
    re-runs validate_hotlinks() against the now-current edge set, and attributes
    failures back to the originating per-op WriteResult.

    Args:
        instance: The BaseModel subclass instance to validate.

    Raises:
        ValidationError: If any hotlink definition's consistency check fails
            (inline mode only — deferred mode raises during the drain, not here).
    """
    from tap_grid.caller_context import enqueue_deferred_hotlink_check, is_deferring_hotlinks
    from tap_grid.models import Edge

    hotlinks: list[dict] = getattr(instance.__class__, "HOTLINKS", [])
    if not hotlinks:
        return

    # Deferred mode: enqueue the instance (whether or not entity_id is set yet)
    # and return. The pipeline assigns entity_id during save, so by the time
    # the drain runs the instance carries its final id and validate_hotlinks
    # called on the same instance will see the current edge set.
    if is_deferring_hotlinks():
        enqueue_deferred_hotlink_check(instance)
        return

    # Option A: skip on first save — no edges exist yet to compare against.
    if instance.entity_id is None:
        return

    entity_type_slug: str = instance.__class__.ENTITY_TYPE
    errors: dict[str, list[str]] = {}

    for defn in hotlinks:
        name: str = defn["name"]
        field: str = defn["field"]
        selector_type: str = defn["selector_type"]
        selector: str = defn["selector"]
        edge_direction: str = defn["edge_direction"]
        edge_type: str = defn["edge_type"]
        mode: str = defn["mode"]

        # Extract identifiers from the node field.
        field_value = getattr(instance, field, None)
        extracted: set[str] = extract_identifiers(field_value, selector_type, selector)

        # Query the edge set in the declared direction.
        if edge_direction == "outbound":
            edge_qs = Edge.objects.filter(
                from_entity_id=instance.entity_id,
                edge_type=edge_type,
            )
        else:  # inbound
            edge_qs = Edge.objects.filter(
                to_entity_id=instance.entity_id,
                edge_type=edge_type,
            )

        # Collect hotlink.value counts from edges that participate in this definition.
        edge_value_counts: Counter[str] = Counter()
        for edge in edge_qs:
            hotlink_data = (edge.properties or {}).get("hotlink", {})
            if hotlink_data.get("model") == entity_type_slug and hotlink_data.get("spec") == name:
                v = hotlink_data.get("value")
                if v is not None:
                    edge_value_counts[str(v)] += 1

        edge_values: set[str] = set(edge_value_counts.keys())

        # Apply the declared validation mode.
        if mode == "exact":
            if extracted != edge_values:
                parts: list[str] = []
                missing_edges = extracted - edge_values
                extra_edges = edge_values - extracted
                if missing_edges:
                    parts.append(f"missing edges for: {sorted(missing_edges)}")
                if extra_edges:
                    parts.append(f"extra edges with no matching reference: {sorted(extra_edges)}")
                errors.setdefault(field, []).append(f"Hotlink '{name}' ({mode}): {'; '.join(parts)}.")

        elif mode == "exists":
            missing = extracted - edge_values
            if missing:
                errors.setdefault(field, []).append(
                    f"Hotlink '{name}' ({mode}): no edge found for identifiers: {sorted(missing)}."
                )

        elif mode == "unique":
            missing = extracted - edge_values
            duplicates = {v for v, count in edge_value_counts.items() if count > 1 and v in extracted}
            parts = []
            if missing:
                parts.append(f"no edge found for: {sorted(missing)}")
            if duplicates:
                parts.append(f"multiple edges found for: {sorted(duplicates)}")
            if parts:
                errors.setdefault(field, []).append(f"Hotlink '{name}' ({mode}): {'; '.join(parts)}.")

    if errors:
        raise ValidationError(errors)
