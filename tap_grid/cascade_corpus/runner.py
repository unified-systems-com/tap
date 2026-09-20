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
from tap_grid.cascade_corpus.model_oracle import RESERVED_KEYS
from tap_grid.models import Batch, BatchEvent, BatchEventType, Entity
from tap_grid.services import create_edge, create_node, delete_edge_by_entity, delete_node


class BuildError(RuntimeError):
    """The fixture could not be built or read back; the scenario cannot be judged (a raise, not an
    assert: this module is not a test tree, and an assert vanishes under -O)."""


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
        if not result.success or result.entity_id is None:
            raise BuildError(f"{scenario.id}: could not create node {ref}: {result.errors}")
        node_ids[ref] = uuid.UUID(str(result.entity_id))
    entities = {ref: Entity.objects.get(pk=eid) for ref, eid in node_ids.items()}
    edge_ids: dict[str, uuid.UUID] = {}
    for ref, a, b, edge_type in scenario.graph.edges:
        edge = create_edge(entities[a], entities[b], edge_type)
        edge_ids[ref] = uuid.UUID(str(edge.entity_id))
    for ref in sorted(scenario.graph.pre_retired):
        result = delete_node(node_ids[ref], reason="resolved")
        if not result.success:
            raise BuildError(f"{scenario.id}: could not pre-retire {ref}: {result.errors}")
    for ref in sorted(scenario.graph.pre_retired_edges):
        result = delete_edge_by_entity(edge_ids[ref], reason="resolved")
        if not result.success:
            raise BuildError(f"{scenario.id}: could not pre-retire edge {ref}: {result.errors}")
    return Built(node_ids, edge_ids)


def snapshot(*, exclude_batches: bool = False) -> dict[uuid.UUID, tuple[bool, int]]:
    rows = Entity.objects.exclude(entity_type="batch") if exclude_batches else Entity.objects.all()
    return {row.pk: (row.deleted_at is not None, row.version) for row in rows}


def _run_reconcile(scenario: Scenario, built: Built) -> list[str]:
    """The reconcile verb on a run built from the scenario (Issue# 662 - tap), through the same
    surfaces the collector runtime uses: a committed write batch that observed the target and
    `observed`; a lifecycle batch with a completeness statement for the target's containment
    surface and the candidate record derived from it; a fake source per node type that answers
    `dropped` as gone and the rest as present; authority armed the way the harness arms it.
    The snapshot is taken after that setup and excludes batch rows (the verb stores its record
    on the lifecycle batch), so what moved is exactly what the verb retired."""
    import dataclasses
    from types import SimpleNamespace

    from django.utils import timezone

    from tap_grid.batch import close_batch, create_batch
    from tap_grid.candidates import record_candidates
    from tap_grid.cascade_corpus.model_oracle import surface_edge_type
    from tap_grid.completeness import record_completeness
    from tap_grid.context import set_batch_id
    from tap_grid.falsifier_testing import FakeSource, FakeSourceFalsifier, arm_run_for_tests
    from tap_grid.falsifiers import register_falsifier, unregister_falsifier
    from tap_grid.services import patch_node, reconcile

    target_id = built.node_ids[scenario.target]
    edge_type = surface_edge_type(scenario.graph, scenario.target)
    write = create_batch(source="corpus.reconcile.write")
    set_batch_id(str(write.entity_id))
    try:
        for ref in (scenario.target, *scenario.observed):
            result = patch_node(built.node_ids[ref], {"name": ref})
            if not result.success:
                raise BuildError(f"{scenario.id}: could not observe {ref}: {result.errors}")
    finally:
        set_batch_id(None)
    close_batch(write)
    now = timezone.now().isoformat()
    surface = {
        "relation": "corpus.children",
        "edge_type": edge_type,
        "filter": None,
        "subject": str(target_id),
        "interval": {"first": now, "last": now},
        "scope_authorized": True,
        "enumeration_complete": True,
        "source_consistent": "unknown",
        "source_promise": None,
        "filter_control": None,
        "count_observed": None,
        "count_reported": None,
        "admitted": True,
        "applied_batches": [str(write.entity_id)],
        "reasons": {"source_consistent": "the corpus source makes no snapshot promise"},
    }
    run_batch = create_batch(source="corpus.reconcile.run")
    record_completeness(run_batch, [surface], produced_batches=[str(write.entity_id)])
    with override_settings(TAP_CASCADE_MAX_CLOSURE=scenario.cap):  # derivation reads the cap too
        record_candidates(run_batch, produced_batches=[str(write.entity_id)])
    run_batch.refresh_from_db()
    arm_run_for_tests(run_batch, authority=True, budget=scenario.budget, collector="corpus")

    candidate = scenario.oracle.candidate
    assert candidate is not None
    source = FakeSource()
    source.holds(built.node_ids[candidate], f"src-{candidate}", owner=str(target_id), name=candidate)
    if candidate in scenario.dropped:
        source.dropped(built.node_ids[candidate])
    else:
        source.present(built.node_ids[candidate])
    types = sorted(set(scenario.graph.node_type.values()))
    for entity_type in types:
        register_falsifier(entity_type, FakeSourceFalsifier(source))
    try:
        before = snapshot(exclude_batches=True)
        events_before = event_counts()
        with override_settings(TAP_CASCADE_MAX_CLOSURE=scenario.cap):
            record = reconcile(run_batch.entity_id)
    finally:
        for entity_type in types:
            unregister_falsifier(entity_type)
    after = snapshot(exclude_batches=True)
    delta = event_delta(events_before, event_counts())

    failures: list[str] = []
    entries = record["entries"]
    if len(entries) != 1 or entries[0]["entity_id"] != str(built.node_ids[candidate]):
        return [
            f"expected one entry for candidate {candidate!r}, got {[built.ref_of(e['entity_id']) for e in entries]}"
        ]
    entry = entries[0]
    outcome = scenario.expected["outcome"]
    if outcome == "contradicted":
        want = scenario.expected["contradiction"]
        if entry["outcome"] != "contradicted":
            failures.append(f"entry outcome {entry['outcome']!r}, expected 'contradicted'")
        got = entry.get("contradiction") or {}
        if got.get("kind") != want["kind"]:
            failures.append(f"contradiction kind {got.get('kind')!r}, expected {want['kind']!r}")
        want_ids = sorted(str(built.node_ids[r]) for r in want["observed_descendants"])
        if sorted(got.get("observed_descendants") or []) != want_ids:
            failures.append(
                f"observed_descendants {[built.ref_of(i) for i in got.get('observed_descendants') or []]}, "
                f"expected {sorted(want['observed_descendants'])}"
            )
        if record["calls"]:
            failures.append(f"a contradicted candidate must not be probed; falsifiers called: {record['calls']}")
    elif outcome == "not_applicable":
        applied = entry.get("applied") or {}
        if applied.get("outcome") != "not_applicable":
            failures.append(f"applied outcome {applied.get('outcome')!r}, expected 'not_applicable'")
    elif outcome == "applied":
        applied = entry.get("applied") or {}
        if applied.get("outcome") != "applied":
            return [f"applied outcome {applied.get('outcome')!r} ({applied.get('error')}), expected 'applied'"]
        view = dataclasses.replace(
            scenario, target=candidate, cascade="contained", reason=scenario.oracle.root_reason, metadata={}
        )
        return check(view, built, SimpleNamespace(success=True, errors=[]), before, after, delta, {})
    else:
        return [f"unsupported reconcile outcome {outcome!r}"]
    if after != before:
        failures.append(f"nothing may retire, but these entities changed: {_diff(before, after, built)}")
    if delta:
        failures.append(f"nothing may retire, but events were recorded: {describe(delta, built)}")
    return failures


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
    event = latest_event_or_none(entity_id, event_type)
    if event is None:
        raise BuildError(f"no {event_type} event on {entity_id}")
    return event


def latest_event_or_none(entity_id: uuid.UUID, event_type: str) -> BatchEvent | None:
    return BatchEvent.objects.filter(entity_id=entity_id, event_type=event_type).order_by("-timestamp", "-pk").first()


def describe(delta: dict[tuple[uuid.UUID, str], int], built: Built) -> str:
    items = sorted(delta.items(), key=lambda kv: built.ref_of(kv[0][0]))
    return ", ".join(f"{built.ref_of(eid)}:{etype}x{n}" for (eid, etype), n in items) or "nothing"


def run(scenario: Scenario, built: Built) -> list[str]:
    """Run the operation and return the list of failures (empty means the scenario holds)."""
    if scenario.verb == "reconcile":
        return _run_reconcile(scenario, built)
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
    model = scenario.oracle
    target_id = str(built.node_ids[scenario.target])
    inherited = {k: v for k, v in scenario.metadata.items() if k not in RESERVED_KEYS}
    for ref in expected["retired_nodes"]:
        if not spots.get(ref, {}).get("count", 1):
            continue
        event = latest_event_or_none(built.node_ids[ref], BatchEventType.DELETE)
        if event is None:
            failures.append(f"{ref}: no delete event to inspect")
            continue
        meta = event.metadata or {}
        if meta.get("reason") != model.node_reason[ref]:
            failures.append(f"{ref}: reason {meta.get('reason')!r}, expected {model.node_reason[ref]!r}")
        for k, v in inherited.items():
            if meta.get(k) != v:
                failures.append(f"{ref}: inherited metadata {k}={meta.get(k)!r}, expected {v!r}")
        if ref == scenario.target:
            continue
        # A cascaded record's reserved keys are the walk's own, never an inherited value.
        options = model.node_parents.get(ref, frozenset())
        if meta.get("consequence_of") not in {str(built.node_ids[p]) for p in options}:
            got = built.ref_of(meta.get("consequence_of") or uuid.UUID(int=0))
            failures.append(f"{ref}: consequence_of {got!r}, expected one of {sorted(options)}")
        if meta.get("cascade_root") != target_id:
            failures.append(f"{ref}: cascade_root {meta.get('cascade_root')!r} is not the target")
        if meta.get("root_reason") != model.root_reason:
            failures.append(f"{ref}: root_reason {meta.get('root_reason')!r}, expected {model.root_reason!r}")
    if contained:
        for ref in expected["retired_edges"]:
            if not spots.get(ref, {}).get("count", 1):
                continue
            event = latest_event_or_none(built.edge_ids[ref], BatchEventType.UNLINK)
            if event is None:
                failures.append(f"{ref}: no unlink event to inspect")
                continue
            meta = event.metadata or {}
            if meta.get("reason") != "cascaded":
                failures.append(f"{ref}: edge event reason {meta.get('reason')!r}, expected 'cascaded'")
            options = model.edge_parents.get(ref, frozenset())
            if meta.get("consequence_of") not in {str(built.node_ids[p]) for p in options}:
                got = built.ref_of(meta.get("consequence_of") or uuid.UUID(int=0))
                failures.append(f"{ref}: edge consequence_of {got!r}, expected one of {sorted(options)}")
            if meta.get("cascade_root") != target_id:
                failures.append(f"{ref}: edge cascade_root {meta.get('cascade_root')!r} is not the target")
            if meta.get("root_reason") != model.root_reason:
                failures.append(f"{ref}: edge root_reason {meta.get('root_reason')!r}, expected {model.root_reason!r}")
            for k, v in inherited.items():
                if meta.get(k) != v:
                    failures.append(f"{ref}: edge inherited metadata {k}={meta.get(k)!r}, expected {v!r}")
    return failures


def _diff(before: dict[uuid.UUID, Any], after: dict[uuid.UUID, Any], built: Built) -> list[str]:
    changed = [built.ref_of(eid) for eid in before if after.get(eid) != before[eid]]
    return changed + [f"new:{built.ref_of(eid)}" for eid in set(after) - set(before)]
