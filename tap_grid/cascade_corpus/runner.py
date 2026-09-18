"""Build a scenario's graph through the service layer, run its operation, and assert
the three things the corpus exists to confirm:

(a) every node and edge the expectation names is tombstoned;
(b) nothing else changed — every other entity in the grid keeps its liveness AND its
    version, so an extra tombstone, an extra edge ending or a stray version bump is a
    failure, not a footnote;
(c) the records: one delete event per retired node and one unlink event per retired
    edge (in a contained cascade), carrying the reason, the node it was a consequence of
    and the root; on refusal, no new event, no surviving batch row, and the expected code.

Everything is observed through the public surface (``tap_grid.services``) and the
models; nothing here imports the pipeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.test import override_settings

from tap_grid.cascade_corpus.loader import Scenario
from tap_grid.models import Batch, BatchEvent, BatchEventType, Entity
from tap_grid.services import create_edge, create_node, delete_node


@dataclass
class Built:
    node_ids: dict[str, uuid.UUID]
    edge_ids: dict[str, uuid.UUID]

    def ref_of(self, entity_id: uuid.UUID | str) -> str:
        key = uuid.UUID(str(entity_id))
        for ref, eid in list(self.node_ids.items()) + list(self.edge_ids.items()):
            if eid == key:
                return ref
        return str(entity_id)


def apply_declarations(scenario: Scenario, monkeypatch: Any) -> None:
    """Set CONTAINMENT_EDGES and INTERNAL_ONLY on the fixture model classes for this scenario."""
    from tap_grid.registry import get_model_class

    for entity_type in sorted(set(scenario.graph.node_type.values())):
        model = get_model_class(entity_type)
        monkeypatch.setattr(
            model, "CONTAINMENT_EDGES", tuple(scenario.graph.containment.get(entity_type, ())), raising=False
        )
        monkeypatch.setattr(model, "INTERNAL_ONLY", entity_type in scenario.graph.blocked_types, raising=False)


def build(scenario: Scenario) -> Built:
    node_ids: dict[str, uuid.UUID] = {}
    for ref, entity_type in scenario.graph.node_type.items():
        result = create_node(entity_type, {"name": ref})
        assert result.success, f"{scenario.id}: could not create node {ref}: {result.errors}"
        assert result.entity_id is not None
        node_ids[ref] = uuid.UUID(str(result.entity_id))
    entities = {ref: Entity.objects.get(pk=eid) for ref, eid in node_ids.items()}
    edge_ids: dict[str, uuid.UUID] = {}
    for ref, a, b, edge_type in scenario.graph.edges:
        edge = create_edge(entities[a], entities[b], edge_type)
        edge_ids[ref] = uuid.UUID(str(edge.entity_id))
    for ref in sorted(scenario.graph.pre_retired):
        result = delete_node(node_ids[ref], reason="resolved")
        assert result.success, f"{scenario.id}: could not pre-retire {ref}: {result.errors}"
    return Built(node_ids, edge_ids)


def snapshot() -> dict[uuid.UUID, tuple[bool, int]]:
    return {row.pk: (row.deleted_at is not None, row.version) for row in Entity.objects.all()}


def run(scenario: Scenario, built: Built) -> list[str]:
    """Run the operation and return the list of failures (empty means the scenario holds)."""
    before = snapshot()
    events_before = BatchEvent.objects.count()
    with override_settings(TAP_CASCADE_MAX_CLOSURE=scenario.cap):
        result = delete_node(
            built.node_ids[scenario.target],
            reason=scenario.reason,
            metadata=scenario.metadata or None,
            cascade=scenario.cascade,  # type: ignore[arg-type]  # invalid values are the point of some scenarios
        )
    after = snapshot()
    failures: list[str] = []
    expected = scenario.expected

    if expected["outcome"] == "refused":
        if result.success:
            failures.append("expected a refusal, got success")
        else:
            code = result.errors[0].code if result.errors else None
            if code != expected.get("error_code"):
                failures.append(
                    f"error_code: expected {expected.get('error_code')!r}, got {code!r} ({result.errors[0].message if result.errors else ''})"
                )
        if after != before:
            failures.append(f"a refusal must change nothing, but these entities changed: {_diff(before, after, built)}")
        if BatchEvent.objects.count() != events_before:
            failures.append("a refusal must record no event")
        if result.batch_id and Batch.objects.filter(entity_id=result.batch_id).exists():
            failures.append("a refusal must leave no batch row")
        return failures

    if not result.success:
        failures.append(f"expected success, got {[(e.code, e.message) for e in result.errors]}")
        return failures

    want_nodes = {built.node_ids[r] for r in expected["retired_nodes"]}
    want_edges = {built.edge_ids[r] for r in expected["retired_edges"]}
    want = want_nodes | want_edges
    # (a) everything expected is tombstoned
    for eid in want:
        if not after[eid][0]:
            failures.append(f"{built.ref_of(eid)} should be tombstoned and is live")
    # (b) nothing else changed, liveness or version
    for eid, state in before.items():
        if eid in want:
            continue
        if after[eid] != state:
            failures.append(f"{built.ref_of(eid)} must be untouched: before={state} after={after[eid]}")
    # the operation's own batch and the pre-retired nodes are outside the "untouched" set only
    # if they are new entities — a new Batch entity for this write is the one legitimate addition
    new_ids = set(after) - set(before)
    unexpected_new = [eid for eid in new_ids if not Entity.objects.filter(pk=eid, entity_type="batch").exists()]
    if unexpected_new:
        failures.append(f"unexpected new entities: {unexpected_new}")
    # (c) the records
    contained = scenario.cascade == "contained"
    for ref in expected["retired_nodes"]:
        events = list(
            BatchEvent.objects.filter(
                entity_id=built.node_ids[ref], event_type=BatchEventType.DELETE, batch_id=result.batch_id
            )
        )
        spot = (expected.get("events") or {}).get(ref, {})
        want_count = spot.get("count", 1)
        if len(events) != want_count:
            failures.append(f"{ref}: expected {want_count} delete event(s) in this batch, found {len(events)}")
            continue
        if not events:
            continue
        meta = events[0].metadata or {}
        model_reason, model_parent = scenario.oracle.node_events[ref]
        if meta.get("reason") != model_reason:
            failures.append(f"{ref}: reason {meta.get('reason')!r}, expected {model_reason!r}")
        if model_parent is not None:
            if meta.get("consequence_of") != str(built.node_ids[model_parent]):
                failures.append(
                    f"{ref}: consequence_of {built.ref_of(meta.get('consequence_of') or uuid.UUID(int=0))!r}, expected {model_parent!r}"
                )
            if meta.get("cascade_root") != str(built.node_ids[scenario.target]):
                failures.append(f"{ref}: cascade_root is not the target")
            for k, v in scenario.metadata.items():
                if meta.get(k) != v:
                    failures.append(f"{ref}: inherited metadata {k}={meta.get(k)!r}, expected {v!r}")
    for ref in expected["retired_edges"]:
        events = list(
            BatchEvent.objects.filter(
                entity_id=built.edge_ids[ref], event_type=BatchEventType.UNLINK, batch_id=result.batch_id
            )
        )
        want_count = (expected.get("events") or {}).get(ref, {}).get("count", 1 if contained else 0)
        if len(events) != want_count:
            failures.append(f"{ref}: expected {want_count} unlink event(s), found {len(events)}")
            continue
        if events and contained:
            meta = events[0].metadata or {}
            _, model_parent = scenario.oracle.edge_events[ref]
            if meta.get("reason") != "cascaded":
                failures.append(f"{ref}: edge event reason {meta.get('reason')!r}, expected 'cascaded'")
            if meta.get("consequence_of") != str(built.node_ids[model_parent]):
                failures.append(
                    f"{ref}: edge consequence_of {built.ref_of(meta.get('consequence_of') or uuid.UUID(int=0))!r}, expected {model_parent!r}"
                )
    # no event on anything that was not retired
    retired_refs = set(expected["retired_nodes"]) | set(expected["retired_edges"])
    for ref, eid in list(built.node_ids.items()) + list(built.edge_ids.items()):
        if ref in retired_refs or ref in scenario.graph.pre_retired:
            continue
        stray = BatchEvent.objects.filter(entity_id=eid, batch_id=result.batch_id).count()
        if stray:
            failures.append(f"{ref}: {stray} event(s) recorded on an entity this operation must not touch")
    return failures


def _diff(before: dict[uuid.UUID, Any], after: dict[uuid.UUID, Any], built: Built) -> list[str]:
    changed = [built.ref_of(eid) for eid in before if after.get(eid) != before[eid]]
    return changed + [f"new:{built.ref_of(eid)}" for eid in set(after) - set(before)]
