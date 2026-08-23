"""GRIFT envelope parsing — write-path counterpart to subgraph serializers.

The serializers in ``tap_grid.grift.subgraph`` emit canonical envelopes
per ``spec-grift-envelope``. This module is the symmetric **parse**
direction: an envelope arriving on a write path is split into the two
canonical write payloads — Entity-spine fields and BaseModel-row
fields — with the structural invariants of the envelope validated
before dispatch.

The intended caller is any future API entrypoint that accepts the
envelope shape as a write payload (a graph-write HTTP endpoint, a
service-layer wrapper that mirrors read shape on the write side, etc.).
No such caller exists in v0; this module ships as the foundation
``spec-grift-envelope § req-grift-envelope-validation`` describes, so
when the first envelope-shaped write API lands it has a canonical
parse-and-split function rather than re-invented validation logic.

Per spec-grift-envelope on validation:

- Required top-level spine fields must be present.
- ``data`` must be present and be a dict.
- Denormalized mirrors (``entity_id``, ``name``) inside ``data`` must
  equal their top-level values when both are present
  (``req-grift-envelope-denorm-3``).
- ``display`` is discarded on write — rendering metadata is read-only.
- Unknown future top-level lanes (e.g. ``provenance``, ``history``)
  are discarded on write today; they are not authoritative on the
  write path.

The split returned does **not** apply the writes itself. It hands the
caller two dicts the service layer can route through ``create_node`` /
``patch_node`` / ``create_edge`` / ``patch_edge`` (or any other
service-layer verb) without further envelope-shape awareness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Top-level spine fields the envelope must carry on the write path. These
# correspond to the Entity-row fields the service layer can set during
# create/patch. Audit timestamps and `version` are managed by the framework
# and are excluded — the caller cannot set them via the write path even if
# they're present at the read-shape top level.
_SPINE_WRITABLE_FIELDS: frozenset[str] = frozenset(
    {"entity_id", "entity_type", "name", "dimensions", "originating_grid_id"}
)

# Spine fields that are mandatory in any envelope (read or write). An
# envelope missing these is structurally invalid.
_SPINE_REQUIRED_FIELDS: frozenset[str] = frozenset({"entity_id", "entity_type"})

# Top-level fields that are framework-managed and discarded on write.
_SPINE_DISCARDED_ON_WRITE: frozenset[str] = frozenset({"created_at", "updated_at", "deleted_at", "version"})

# Top-level lanes that exist but are discarded on write. `display` is
# rendering metadata; future lanes (provenance, history, perspectives) are
# similarly read-only on the write path until/unless a spec promotes them.
_DISCARDED_LANES: frozenset[str] = frozenset({"display", "provenance", "history", "perspectives"})

# Fields inside `data` that are denormalized mirrors of top-level values.
# When both sides are present, they must agree (req-grift-envelope-denorm-3).
_MIRRORED_FIELDS: frozenset[str] = frozenset({"entity_id", "name"})


class EnvelopeValidationError(ValueError):
    """An envelope arrived on a write path with a structural violation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SplitPayload:
    """The two write payloads produced by parsing an envelope.

    Attributes:
        entity_payload: Entity-spine fields the service layer can set on
            create/patch (entity_id, entity_type, name, dimensions,
            originating_grid_id when applicable). Framework-managed
            timestamps and version are excluded.
        model_payload: BaseModel-row fields the service layer can set on
            the per-model row. Denormalized mirrors (entity_id, name) are
            removed before return — the caller routes them through the
            entity_payload, not the model_payload, to avoid duplicate
            sourcing.
        discarded_lanes: Top-level lanes present in the envelope but
            discarded on the write path. Surfaced for observability so a
            caller can log "you sent display data; it was ignored."
    """

    entity_payload: dict[str, Any] = field(default_factory=dict)
    model_payload: dict[str, Any] = field(default_factory=dict)
    discarded_lanes: tuple[str, ...] = ()


def parse_envelope_for_write(env: dict[str, Any]) -> SplitPayload:
    """Split an envelope into Entity / BaseModel write payloads.

    TAP-IMPLEMENTS: req-grift-envelope-validation@e5bea30bacdf/4765a95f6f3f (derivation) — the spec names
        this function as the canonical implementation; any future envelope-shaped write API
        routes through it rather than reinventing the validate-and-split logic.

    Validates the envelope structure per spec-grift-envelope §
    Envelope Validation (req-grift-envelope-validation):

    - Required top-level spine fields are present.
    - ``data`` is present and is a dict.
    - Denormalized mirrors inside ``data`` equal their top-level values.
    - ``display`` and unknown lanes are discarded.

    Args:
        env: The envelope dict (the per-member shape from a subgraph
            response, or a caller-constructed equivalent).

    Returns:
        SplitPayload with the two write payloads and a record of
        discarded read-only lanes.

    Raises:
        EnvelopeValidationError: when a structural invariant is violated.
            ``code`` carries a stable machine-readable identifier; the
            message describes the violation.
    """
    if not isinstance(env, dict):
        logger.warning(
            "[fc69] envelope must be a dict, got %s",
            type(env).__name__,
        )
        raise EnvelopeValidationError(
            "envelope_not_dict",
            f"Envelope must be a dict, got {type(env).__name__}.",
        )

    missing = _SPINE_REQUIRED_FIELDS - env.keys()
    if missing:
        logger.warning(
            "[651f] envelope missing required spine fields: %s",
            sorted(missing),
        )
        raise EnvelopeValidationError(
            "spine_field_missing",
            f"Envelope missing required spine fields: {sorted(missing)}.",
        )

    data = env.get("data")
    if data is None:
        logger.warning(
            "[aaee] envelope missing required `data` lane",
        )
        raise EnvelopeValidationError(
            "data_lane_missing",
            "Envelope must include a `data` lane on the write path.",
        )
    if not isinstance(data, dict):
        raise EnvelopeValidationError(
            "data_lane_not_dict",
            f"Envelope `data` lane must be a dict, got {type(data).__name__}.",
        )

    # Mirror equality: when entity_id / name are present at both the top and
    # inside data, they must agree (req-grift-envelope-denorm-3).
    for field_name in _MIRRORED_FIELDS:
        top_value = env.get(field_name)
        data_value = data.get(field_name)
        if data_value is None or top_value is None:
            continue
        if top_value != data_value:
            logger.warning(
                "[9aaa] envelope mirror mismatch on %s: top=%r data=%r",
                field_name,
                top_value,
                data_value,
            )
            raise EnvelopeValidationError(
                "mirror_mismatch",
                f"Envelope mirror mismatch on {field_name!r}: "
                f"top-level={top_value!r}, data={data_value!r}. Top-level is "
                f"canonical; the values must agree.",
            )

    # Build the entity payload from the top-level spine.
    entity_payload: dict[str, Any] = {key: env[key] for key in _SPINE_WRITABLE_FIELDS if key in env}

    # Build the model payload from data, with denormalized mirrors removed
    # (they flow through entity_payload).
    model_payload: dict[str, Any] = {key: value for key, value in data.items() if key not in _MIRRORED_FIELDS}

    discarded = tuple(lane for lane in _DISCARDED_LANES if lane in env)

    return SplitPayload(
        entity_payload=entity_payload,
        model_payload=model_payload,
        discarded_lanes=discarded,
    )
