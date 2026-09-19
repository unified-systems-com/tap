"""Build a scenario's grid through the service layer, import its documents through the public
``grift_import`` surface, and assert the three things the playground exists to confirm:

(a) exactly the expected rows and edges exist afterwards, each with the expected liveness and
    version, and a replaced node's spine name is the envelope's;
(b) nothing else was written or changed — every other entity keeps its liveness and version,
    no unexpected entity appears, and a refused or failed batch leaves no batch row;
(c) the records: the event-count delta over the run is exactly the model's (a purge takes a
    row's events with it, so a delta may be negative), every event recorded during the run is
    attributed to a batch this run committed and every typed row names the batch that last
    wrote it, and each import result reports the expected success, batch states, issue codes
    with paths, warnings, resolved refs and — where the scenario spot-checks them — counts.

The second pass (Issue# 613 - tap) added the three-truths discipline: persisted state (rows,
versions, spine, dimensions, typed fields, edge endpoints), the API report (result shape and
counts) and provenance (events and their batch attribution) are each compared, and a
scenario passes only when all three agree. Generated ids are symbolic: a minted ref id is
checked for UUID version and distinctness only, and a failed batch's provisional mappings are
never taken as proof of a row. The caller's document is proven unchanged by the import.

Everything is observed through the public surface (``tap_grid.grift``, ``tap_grid.services``)
and the models; nothing here imports the pipeline. The snapshot and event-delta helpers are the
cascade corpus's (``tap_grid.cascade_corpus.runner``) — one home, not a copy.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from django.test import override_settings

from tap_grid.batch_corpus import model_oracle
from tap_grid.batch_corpus.loader import Scenario
from tap_grid.cascade_corpus.runner import BuildError, event_counts, event_delta, snapshot
from tap_grid.grift import grift_import
from tap_grid.grift.retired import RetiredCollisionError, strip_retired_types
from tap_grid.models import Batch, BatchEvent, BatchStatus, Edge, Entity
from tap_grid.services import create_edge, create_node, delete_edge_by_entity, delete_node, get_node

__all__ = ["BuildError", "Built", "Observed", "build", "check", "run"]


@dataclass
class Built:
    """Name → entity id, for every name the runner has an id for (grid rows, `id` names, batch
    names and phantoms up front; `ref` names once an import has reported what they became)."""

    ids: dict[str, uuid.UUID]
    initial: dict[uuid.UUID, tuple[bool, int]] = field(default_factory=dict)

    def ref_of(self, entity_id: uuid.UUID | str) -> str:
        key = uuid.UUID(str(entity_id))
        for name, eid in self.ids.items():
            if eid == key:
                return name
        return str(entity_id)


@dataclass
class Observed:
    """One import's result, reduced to what the checker compares."""

    success: bool
    errors: list[tuple[str, str]]
    warnings: list[str]
    imported: dict[str, int]  # batch id → errors_count
    skipped: set[str]
    resolved: dict[str, dict[str, str]]  # batch id → {ref: entity_id}
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # batch id → (nodes, edges) imported
    #: the caller's document after the call, compared with the copy taken before it
    document_mutated: bool = False


def build(scenario: Scenario) -> Built:
    ids: dict[str, uuid.UUID] = {}
    grid = scenario.grid
    for n in grid["nodes"]:
        result = create_node(n["type"], dict(n["props"]))
        if not result.success or result.entity_id is None:
            raise BuildError(f"{scenario.id}: could not create grid node {n['name']}: {result.errors}")
        ids[n["name"]] = uuid.UUID(str(result.entity_id))
    entities = {n["name"]: Entity.objects.get(pk=ids[n["name"]]) for n in grid["nodes"]}
    for e in grid["edges"]:
        edge = create_edge(entities[e["from"]], entities[e["to"]], e["type"])
        ids[e["name"]] = uuid.UUID(str(edge.entity_id))
    edge_names = {e["name"] for e in grid["edges"]}
    for name in grid.get("tombstoned", ()):
        result = (delete_edge_by_entity if name in edge_names else delete_node)(ids[name], reason="operator")
        if not result.success:
            raise BuildError(f"{scenario.id}: could not tombstone {name}: {result.errors}")
    for name in grid.get("cascaded", ()):
        result = delete_node(ids[name], reason="operator", cascade="contained")
        if not result.success:
            raise BuildError(f"{scenario.id}: could not cascade from {name}: {result.errors}")
    for name in scenario.raw.get("phantoms", ()):
        ids[name] = uuid.uuid7()
    for imp in scenario.imports:
        for b in imp["batches"]:
            ids.setdefault(b["name"], uuid.uuid7())
            for obj in list(b.get("nodes", ())) + list(b.get("edges", ())):
                if "id" in obj:
                    ids.setdefault(obj["id"], uuid.uuid7())
    return Built(ids, snapshot())


def _document(scenario: Scenario, imp: dict[str, Any], built: Built) -> dict[str, Any]:
    batches = []
    for b in imp["batches"]:
        refs = {n["ref"] for n in b.get("nodes", ()) if "ref" in n}
        nodes = []
        for n in b.get("nodes", ()):
            envelope: dict[str, Any] = {"entity_type": n["type"], "dimensions": dict(n.get("dimensions") or {})}
            envelope["ref" if "ref" in n else "entity_id"] = n["ref"] if "ref" in n else str(built.ids[n["id"]])
            spine_name = n.get("name") or n["props"].get("name")
            if spine_name:
                envelope["name"] = spine_name
            if n.get("expected_version") is not None:
                envelope["entity_expected_version"] = n["expected_version"]
            nodes.append({"entity": envelope, "node": dict(n["props"])})
        edges = []
        for e in b.get("edges", ()):
            envelope = {"entity_type": "edge", "dimensions": {}}
            envelope["ref" if "ref" in e else "entity_id"] = e["ref"] if "ref" in e else str(built.ids[e["id"]])
            if e.get("expected_version") is not None:
                envelope["entity_expected_version"] = e["expected_version"]
            payload: dict[str, Any] = {"edge_type": e["type"], "properties": dict(e.get("properties") or {})}
            for side in ("from", "to"):
                if f"{side}_ref" in e:
                    payload[f"{side}_ref"] = e[f"{side}_ref"]
                elif e[side] in refs:
                    payload[f"{side}_ref"] = e[side]
                else:
                    payload[f"{side}_entity_id"] = str(built.ids[e[side]])
            edges.append({"entity": envelope, "edge": payload})
        container: dict[str, Any] = {
            "batch_entity": {
                "entity_id": str(built.ids[b["name"]]),
                "entity_type": "batch",
                "name": b["name"],
                "dimensions": {},
            },
            "batch_node": {
                "name": b["name"],
                "description": "",
                "description_json": None,
                "source": "batch_corpus",
                "metadata": {},
            },
            "nodes": nodes,
            "edges": edges,
        }
        for section in ("deletes", "purges"):
            block = b.get(section)
            if block is None:
                continue
            out: dict[str, Any] = {k: v for k, v in block.items() if k not in ("edges", "nodes")}
            for sub in ("edges", "nodes"):
                out[sub] = [
                    {
                        "entity_id": str(built.ids[t["id"]]),
                        "entity_type": t["type"],
                        "reason": t["reason"],
                        **(
                            {"entity_expected_version": t["expected_version"]}
                            if t.get("expected_version") is not None
                            else {}
                        ),
                    }
                    for t in block.get(sub, ())
                ]
            container[section] = out
        batches.append(container)
    return {"metadata": {"grift_version": "0"}, "_reserved": {}, "batches": batches}


def _import(scenario: Scenario, imp: dict[str, Any], built: Built) -> Observed:
    document = _document(scenario, imp, built)
    if imp.get("seed_boundary"):
        try:
            document, _stripped = strip_retired_types(document)
        except RetiredCollisionError:
            return Observed(False, [("retired_collision", "$")], [], {}, set(), {})
    sent = copy.deepcopy(document)
    result = grift_import(  # TAP-AUTHZ-COV: corpus runner under the test harness's actor; grift_import gates itself
        document, dangling_edge_mode=imp.get("dangling_edge_mode", "strict")
    )
    observed = Observed(
        success=result.success,
        errors=[(i.code, i.path) for i in result.errors],
        warnings=[i.code for i in result.warnings],
        imported={b.batch_entity_id: b.errors_count for b in result.imported_batches},
        skipped={b.batch_entity_id for b in result.skipped_batches},
        resolved={b.batch_entity_id: dict(b.resolved_refs) for b in result.imported_batches if b.errors_count == 0},
        counts={b.batch_entity_id: (b.nodes_imported, b.edges_imported) for b in result.imported_batches},
        document_mutated=document != sent,
    )
    for refs in observed.resolved.values():
        for ref, entity_id in refs.items():
            built.ids.setdefault(ref, uuid.UUID(entity_id))
    return observed


def event_batches_since(event_pks_before: set[uuid.UUID]) -> set[str]:
    """The batch entity ids carried by every event recorded since ``event_pks_before`` was taken."""
    new = BatchEvent.objects.exclude(pk__in=event_pks_before).values_list("batch__entity_id", flat=True)
    return {str(b) for b in new}


def run(scenario: Scenario, built: Built) -> list[str]:
    """Import every document in order and return the list of failures (empty means it holds)."""
    events_before = event_counts()
    event_pks_before = set(BatchEvent.objects.values_list("pk", flat=True))
    with override_settings(DEBUG=scenario.debug):
        observed = [_import(scenario, imp, built) for imp in scenario.imports]
    return check(
        scenario,
        built,
        observed,
        snapshot(),
        event_delta(events_before, event_counts()),
        event_batches=event_batches_since(event_pks_before),
    )


def check(
    scenario: Scenario,
    built: Built,
    observed: list[Observed],
    after: dict[uuid.UUID, tuple[bool, int]],
    delta: dict[tuple[uuid.UUID, str], int],
    event_batches: set[str] | None = None,
) -> list[str]:
    """The three assertions, over the observed import results and the before/after grid.

    ``event_batches`` — the batch ids every event recorded during the run carries — is checked
    against the batches the model committed when given (the provenance truth); the checker's
    own negatives call without it.

    TAP-IMPLEMENTS: req-grid-batch-corpus-runner@955aec5a48c4/1aaf876a77b6 (derivation) — the one
        place a scenario's expectation is compared with what the grid and the import results say.
    """
    failures: list[str] = []
    model = scenario.oracle
    before = built.initial
    # A batch row is judged by the batch's FINAL state: a batch that failed in one import and was
    # retried in a later one has a row afterwards, which the earlier import's check must not read
    # as a rollback that left residue.
    final_state = {name: state for imp in model.imports for name, state in imp.batches.items()}
    for i, (want, got) in enumerate(zip(model.imports, observed, strict=True)):
        failures.extend(f"import {i}: {f}" for f in _check_import(want, got, built, final_state))
        if got.document_mutated:
            failures.append(f"import {i}: the caller's document was changed by the import")
        for bname, counts in (scenario.expected["imports"][i].get("counts") or {}).items():
            reported = got.counts.get(str(built.ids[bname]), (0, 0))
            if reported != (counts["nodes"], counts["edges"]):
                failures.append(f"import {i}: batch {bname} reported counts {reported}, expected {counts}")
    failures.extend(_check_symbolic_ids(scenario, built))
    if event_batches is not None:
        committed = {
            str(built.ids[name]) for imp in model.imports for name, state in imp.batches.items() if state == "committed"
        }
        stray = sorted(event_batches - committed)
        if stray:
            failures.append(f"events were recorded under batches this run did not commit: {stray}")

    accounted: set[uuid.UUID] = set()
    for name, row in model.rows.items():
        eid = built.ids.get(name)
        if eid is None:
            failures.append(f"{name} should exist but no import reported an id for it")
            continue
        accounted.add(eid)
        state = after.get(eid)
        if state is None:
            failures.append(f"{name} should exist and has no row")
            continue
        if state[0] == row.live:
            failures.append(f"{name} should be {'live' if row.live else 'tombstoned'} and is not")
        if state[1] != row.version:
            failures.append(f"{name} version {state[1]}, expected {row.version}")
        if row.kind == model_oracle.BATCH:
            if getattr(Batch.all_objects.filter(entity_id=eid).first(), "status", None) != BatchStatus.CLOSED:
                failures.append(f"batch {name} should be committed and closed")
            continue
        failures.extend(_check_row(scenario, built, name, row, eid))
    absent = (scenario.universe - set(model.rows)) | model.purged
    for name in sorted(absent):
        eid = built.ids.get(name)
        if eid is not None and eid in after:
            failures.append(f"{name} should have no row and has one: {after[eid]}")
    purged = {built.ids[name] for name in model.purged if name in built.ids}
    for eid, state in before.items():
        if eid not in accounted and eid not in purged and after.get(eid) != state:
            failures.append(f"{built.ref_of(eid)} must be untouched: before={state} after={after.get(eid)}")
    unexpected = sorted(built.ref_of(eid) for eid in set(after) - set(before) - accounted)
    if unexpected:
        failures.append(f"unexpected new entities: {unexpected}")
    expected_delta = {
        (built.ids[name], event_type): n for (name, event_type), n in model.event_delta().items() if name in built.ids
    }
    if delta != expected_delta:
        failures.append(f"events recorded {_describe(delta, built)}, expected {_describe(expected_delta, built)}")
    return failures


def _check_row(scenario: Scenario, built: Built, name: str, row: model_oracle.Row, eid: uuid.UUID) -> list[str]:
    """One row's persisted truth beyond liveness and version: spine name, dimensions, edge
    endpoints, typed fields and the batch stamped on the typed row."""
    failures: list[str] = []
    entity = Entity.objects.get(pk=eid)
    if row.spine_name is not None and entity.name != row.spine_name:
        failures.append(f"{name} spine name {entity.name!r}, expected {row.spine_name!r}")
    if row.dims is not None and (entity.dimensions or {}) != row.dims:
        failures.append(f"{name} dimensions {entity.dimensions!r}, expected {row.dims!r}")
    if row.kind == "edge" and row.ends is not None:
        edge = cast(Edge | None, Edge.all_objects.filter(entity_id=eid).first())
        want_ends = (built.ids.get(row.ends[0]), built.ids.get(row.ends[1]))
        got_ends = (edge.from_entity_id, edge.to_entity_id) if edge else None
        if got_ends != want_ends:
            failures.append(f"{name} endpoints {tuple(map(built.ref_of, got_ends or ()))}, expected {row.ends}")
        return failures
    if not row.live:
        return failures
    typed = get_node(eid)
    for field_name, value in (scenario.expected.get("fields") or {}).get(name, {}).items():
        got_value = getattr(typed, field_name, None)
        if got_value != value:
            failures.append(f"{name}.{field_name} is {got_value!r}, expected {value!r}")
    if row.last_batch is not None and typed.batch_id != str(built.ids[row.last_batch]):
        failures.append(f"{name} is stamped with batch {built.ref_of(typed.batch_id)}, expected {row.last_batch}")
    return failures


def _check_symbolic_ids(scenario: Scenario, built: Built) -> list[str]:
    """A minted id is a UUIDv7 distinct from every other id the scenario knows — nothing more is
    ever asserted about its value."""
    failures: list[str] = []
    minted = [ref for ref in scenario.universe if ref in built.ids and ref not in scenario.oracle.alias]
    for name in minted:
        if built.ids[name].version != 7:
            failures.append(f"{name} was minted as a UUID version {built.ids[name].version}, expected 7")
    own = {name: eid for name, eid in built.ids.items() if name not in scenario.oracle.alias}
    if len(set(own.values())) != len(own):
        failures.append("two names that are not aliases of one row share one entity id")
    return failures


def _check_import(
    want: model_oracle.ImportOutcome, got: Observed, built: Built, final_state: dict[str, str]
) -> list[str]:
    failures: list[str] = []
    if want.success != got.success:
        failures.append(f"success {got.success}, expected {want.success} (errors: {got.errors})")
    if sorted(want.errors) != sorted(got.errors):
        failures.append(f"errors {sorted(got.errors)}, expected {sorted(want.errors)}")
    if sorted(want.warnings) != sorted(got.warnings):
        failures.append(f"warnings {sorted(got.warnings)}, expected {sorted(want.warnings)}")
    for name, state in want.batches.items():
        bid = str(built.ids[name])
        has_row = Batch.all_objects.filter(entity_id=bid).exists()
        row_expected = final_state[name] in ("committed", "skipped")
        if state == "committed" and (got.imported.get(bid) != 0 or not has_row):
            failures.append(f"batch {name} should be committed: reported errors={got.imported.get(bid)}, row={has_row}")
        if state == "failed" and (not got.imported.get(bid) or has_row != row_expected):
            failures.append(
                f"batch {name} should have failed with no row: reported errors={got.imported.get(bid)}, row={has_row}"
            )
        if state == "skipped" and (bid not in got.skipped or bid in got.imported):
            failures.append(f"batch {name} should have been skipped")
        if state == "refused" and (bid in got.imported or bid in got.skipped or has_row != row_expected):
            failures.append(f"batch {name} should not have run")
    for ref, found in want.resolves.items():
        reported = {r: e for refs in got.resolved.values() for r, e in refs.items()}.get(ref)
        if reported != str(built.ids[found]):
            failures.append(
                f"ref {ref} should have resolved to {found}, reported {built.ref_of(reported) if reported else None}"
            )
    return failures


def _describe(delta: dict[tuple[uuid.UUID, str], int], built: Built) -> str:
    items = sorted(delta.items(), key=lambda kv: (built.ref_of(kv[0][0]), kv[0][1]))
    return ", ".join(f"{built.ref_of(eid)}:{etype}x{n}" for (eid, etype), n in items) or "nothing"
