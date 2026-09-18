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


def apply_containment(scenario: Scenario, monkeypatch: Any) -> None:
    """Set CONTAINMENT_EDGES on the fixture model classes for this scenario (before the build)."""
    from tap_grid.registry import get_model_class

    for entity_type in sorted(set(scenario.graph.node_type.values())):
        model = get_model_class(entity_type)
        monkeypatch.setattr(
            model, "CONTAINMENT_EDGES", tuple(scenario.graph.containment.get(entity_type, ())), raising=False
        )
        monkeypatch.setattr(model, "INTERNAL_ONLY", False, raising=False)


def apply_blocks(scenario: Scenario, monkeypatch: Any) -> None:
    """Set INTERNAL_ONLY on the blocked types AFTER the graph exists: the public create
    path refuses an internal-only type too, and the block under test is the delete's."""
    from tap_grid.registry import get_model_class

    for entity_type in sorted(scenario.graph.blocked_types):
        monkeypatch.setattr(get_model_class(entity_type), "INTERNAL_ONLY", True, raising=False)


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


def event_counts() -> dict[tuple[uuid.UUID, str], int]:
    """Per (entity, event type) counts. The test harness runs every write of a test under one
    ambient batch, so events are compared as DELTAS, never by batch membership."""
    counts: dict[tuple[uuid.UUID, str], int] = {}
    for entity_id, event_type in BatchEvent.objects.values_list("entity_id", "event_type"):
        counts[(entity_id, event_type)] = counts.get((entity_id, event_type), 0) + 1
    return counts


def event_delta(
    before: dict[tuple[uuid.UUID, str], int], after: dict[tuple[uuid.UUID, str], int]
) -> dict[tuple[uuid.UUID, str], int]:
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys if after.get(k, 0) != before.get(k, 0)}


def latest_event(entity_id: uuid.UUID, event_type: str) -> BatchEvent:
    event = BatchEvent.objects.filter(entity_id=entity_id, event_type=event_type).order_by("-timestamp", "-pk").first()
    assert event is not None
    return event


def describe(delta: dict[tuple[uuid.UUID, str], int], built: Built) -> str:
    items = sorted(delta.items(), key=lambda kv: built.ref_of(kv[0][0]))
    return ", ".join(f"{built.ref_of(eid)}:{etype}x{n}" for (eid, etype), n in items) or "nothing"


def run(scenario: Scenario, built: Built) -> list[str]:
    """Run the operation and return the list of failures (empty means the scenario holds)."""
    before = snapshot()
    events_before = event_counts()
    batches_before = dict(Batch.objects.values_list("entity_id", "status"))
    with override_settings(TAP_CASCADE_MAX_CLOSURE=scenario.cap):
        result = delete_node(
            built.node_ids[scenario.target],
            reason=scenario.reason,
            metadata=scenario.metadata or None,
            cascade=scenario.cascade,  # type: ignore[arg-type]  # invalid values are the point of some scenarios
        )
    after = snapshot()
    delta = event_delta(events_before, event_counts())
    return check(scenario, built, result, before, after, delta, batches_before)


def check(
    scenario: Scenario,
    built: Built,
    result: Any,
    before: dict[uuid.UUID, tuple[bool, int]],
    after: dict[uuid.UUID, tuple[bool, int]],
    delta: dict[tuple[uuid.UUID, str], int],
    batches_before: dict[Any, Any],
) -> list[str]:
    """The three assertions, over an observed before/after and the operation's result."""
    failures: list[str] = []
    expected = scenario.expected
    spots: dict[str, Any] = expected.get("events") or {}

    if expected["outcome"] == "refused":
        if result.success:
            failures.append("expected a refusal, got success")
        else:
            code = result.errors[0].code if result.errors else None
            if code != expected.get("error_code"):
                message = result.errors[0].message if result.errors else ""
                failures.append(f"error_code: expected {expected.get('error_code')!r}, got {code!r} ({message})")
        if after != before:
            failures.append(f"a refusal must change nothing, but these entities changed: {_diff(before, after, built)}")
        if delta:
            failures.append(f"a refusal must record no event; recorded {describe(delta, built)}")
        if dict(Batch.objects.values_list("entity_id", "status")) != batches_before:
            failures.append("a refusal must leave every batch row as it was")
        return failures

    if not result.success:
        failures.append(f"expected success, got {[(e.code, e.message) for e in result.errors]}")
        return failures

    want_nodes = {built.node_ids[r] for r in expected["retired_nodes"]}
    want_edges = {built.edge_ids[r] for r in expected["retired_edges"]}
    want = want_nodes | want_edges
    # (a) everything expected is tombstoned, and its version moved exactly once (Codex on
    # PR# 582 - tap: a double write with a correct event count must still be caught)
    for eid in want:
        if not after[eid][0]:
            failures.append(f"{built.ref_of(eid)} should be tombstoned and is live")
        elif after[eid][1] != before[eid][1] + 1:
            failures.append(
                f"{built.ref_of(eid)} version {before[eid][1]} -> {after[eid][1]}: a retirement bumps exactly once"
            )
    # (b) nothing else changed — liveness or version — and nothing new appeared
    for eid, state in before.items():
        if eid not in want and after[eid] != state:
            failures.append(f"{built.ref_of(eid)} must be untouched: before={state} after={after[eid]}")
    unexpected_new = sorted(str(eid) for eid in set(after) - set(before))
    if unexpected_new:
        failures.append(f"unexpected new entities: {unexpected_new}")
    # (c) the records, as deltas: exactly the expected events on exactly the retired refs
    contained = scenario.cascade == "contained"
    expected_delta: dict[tuple[uuid.UUID, str], int] = {}
    for ref in expected["retired_nodes"]:
        n = spots.get(ref, {}).get("count", 1)
        if n:
            expected_delta[(built.node_ids[ref], BatchEventType.DELETE)] = n
    for ref in expected["retired_edges"]:
        n = spots.get(ref, {}).get("count", 1 if contained else 0)
        if n:
            expected_delta[(built.edge_ids[ref], BatchEventType.UNLINK)] = n
    if delta != expected_delta:
        failures.append(f"events recorded {describe(delta, built)}, expected {describe(expected_delta, built)}")
    for ref in expected["retired_nodes"]:
        if not spots.get(ref, {}).get("count", 1):
            continue
        meta = latest_event(built.node_ids[ref], BatchEventType.DELETE).metadata or {}
        model_reason, model_parent = scenario.oracle.node_events[ref]
        if meta.get("reason") != model_reason:
            failures.append(f"{ref}: reason {meta.get('reason')!r}, expected {model_reason!r}")
        if model_parent is not None:
            options = scenario.parent_options.get(ref, frozenset())
            allowed = {str(built.node_ids[p]) for p in options}
            if meta.get("consequence_of") not in allowed:
                got = built.ref_of(meta.get("consequence_of") or uuid.UUID(int=0))
                failures.append(f"{ref}: consequence_of {got!r}, expected one of {sorted(options)}")
            if meta.get("cascade_root") != str(built.node_ids[scenario.target]):
                failures.append(f"{ref}: cascade_root is not the target")
            for k, v in scenario.metadata.items():
                if meta.get(k) != v:
                    failures.append(f"{ref}: inherited metadata {k}={meta.get(k)!r}, expected {v!r}")
    if contained:
        for ref in expected["retired_edges"]:
            if not spots.get(ref, {}).get("count", 1):
                continue
            meta = latest_event(built.edge_ids[ref], BatchEventType.UNLINK).metadata or {}
            if meta.get("reason") != "cascaded":
                failures.append(f"{ref}: edge event reason {meta.get('reason')!r}, expected 'cascaded'")
            options = scenario.parent_options.get(ref, frozenset())
            allowed = {str(built.node_ids[p]) for p in options}
            if meta.get("consequence_of") not in allowed:
                got = built.ref_of(meta.get("consequence_of") or uuid.UUID(int=0))
                failures.append(f"{ref}: edge consequence_of {got!r}, expected one of {sorted(options)}")
            if meta.get("cascade_root") != str(built.node_ids[scenario.target]):
                failures.append(f"{ref}: edge cascade_root is not the target")
            for k, v in scenario.metadata.items():
                if meta.get(k) != v:
                    failures.append(f"{ref}: edge inherited metadata {k}={meta.get(k)!r}, expected {v!r}")
    return failures


def _diff(before: dict[uuid.UUID, Any], after: dict[uuid.UUID, Any], built: Built) -> list[str]:
    changed = [built.ref_of(eid) for eid in before if after.get(eid) != before[eid]]
    return changed + [f"new:{built.ref_of(eid)}" for eid in set(after) - set(before)]
