"""A reference model of the GRIFT import path, independent of the importer and the ORM.

Pure Python over a scenario's declared grid and documents — no Django, no database. The
rules are restated from the specs (``spec-grid-import-grift.md``, ``spec-grift-v0.md`` and
the gate in ``spec-grid-entity.md``), not read from the importer, so the two can disagree:

- preflight is one pass over the whole file and writes nothing; any hard error refuses the
  file (``req-grid-import-grift-preflight-1``, ``-2``);
- refs resolve before preflight reads an id: a ref reused in a batch or an endpoint naming a
  ref of another batch refuses the file (``req-grid-import-grift-identity-3``);
- a batch id is the import identity: a seen batch is skipped, and its declared removals
  warn (``req-grid-import-grift-identity-1``, ``req-grid-import-grift-removals-2``);
- an id that exists — live or tombstoned — routes to replace, else to create; a replace of a
  tombstone fails its batch (the tombstone is terminal), a replace bumps the version once and
  syncs the envelope's spine name without a second bump (``req-grid-import-grift-batch``);
- a ref node resolves inside its batch's transaction through the type's declared search: zero
  live matches assigns, one returns, more than one fails the batch; an undeclared type fails
  the batch; two refs of one batch that describe one source object fail the batch — whether
  both find one row or both would mint it (``req-grid-entity-natural-key-9``, ``-13``; the
  latter is the Issue# 602 - tap ruling);
- a declared ``entity_expected_version`` is enforced atomically; declared on a missing row it
  is a conflict with actual null (``req-grift-concurrency-version-4``, ``-7``);
- a dangling endpoint — neither a node of the file nor a **live** row of the grid; a tombstoned
  row is dangling, because no live edge may point at a tombstone
  (``req-grid-service-delete-tombstone-7``, ruled 2026-09-18) — refuses the file in strict mode
  and skips the edge with a warning in permissive mode (``req-grid-import-grift-dangling-1``);
- removals run after the upserts, edges before nodes, deletes before purges; a missing or
  tombstoned target follows the section's policy, a type mismatch never does; a tombstone
  delete bumps once and records two events (the pipeline's and the bundle-reason one), ends
  the node's live incident edges without an event, and a purge removes the row, its touching
  edges and every event of theirs, leaving one summary event on the batch entity
  (``req-grid-import-grift-removals``, ``req-grid-import-grift-removal-preflight``);
- each batch is its own transaction: a failed batch writes nothing and the batches after it
  still run (``req-grid-import-grift-batch``); a committed batch's entity is live at version
  ``COMMITTED_BATCH_VERSION``; a batch's reported counts are what it committed — a rolled-back
  batch imported nothing (Issue# 607 - tap);
- the envelope is authoritative for the spine: a create takes the envelope's dimensions (the
  model's defaults when it declares none), a replace applies the envelope's dimensions when the
  scenario declares them — an explicit empty map clears them (Issue# 608 - tap); the typed row — node
  or edge, live or tombstoned — carries the batch that last wrote its content, and a delete
  records its batch on its event, never on that stamp (``req-grid-import-grift-provenance-1``);
- an edge's endpoints are the resolved ids of the names it was declared between, in every
  batch and after every re-send (the reference-rewriting family);
- a page's ``layout`` panel-ids must equal the hotlink values of its live ``USES_PANEL`` edges
  once the batch's own upserts and deletes are applied — the post-batch graph, not the graph
  the batch found (Issue# 351 - tap); a mismatch fails the batch at the page's path;
- a grid node listed under ``cascaded`` is deleted with ``cascade="contained"``: the closure
  along ``PG_NESTS__grid_fixtures`` edges retires with one delete event per node, and every
  live edge touching the closure ends with one unlink event (``spec-grid-service-delete.md``).
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: The declaration table the corpus relies on, restated from the models (never imported
#: from them: test_batch_corpus_oracle.py proves it against the registry). Keyed types name
#: their constituting properties; undeclared types have no search and are never keyless.
KEYED: dict[str, tuple[str, ...]] = {"panel": ("slug",), "page": ("slug",)}
UNDECLARED: frozenset[str] = frozenset(
    {"grid_fixtures__node", "grid_fixtures__hub", "grid_fixtures__leaf", "grid_fixtures__cycle_node"}
)
#: Types retired by ruling (`retire_entity_type`); the seeding boundary strips them, the importer
#: does not know them.
RETIRED: frozenset[str] = frozenset({"landing_page"})
#: The containment edge a `cascaded` grid node cascades along (the cascade corpus's fixture
#: declaration, applied by the test before the build).
NESTS = "PG_NESTS__grid_fixtures"
NESTS_OWNER = "grid_fixtures__node"
USES_PANEL = "USES_PANEL"
EDGE = "edge"
BATCH = "batch"
#: A committed batch's Entity.version: the spine row (1), the Batch row's own first save (2) and
#: close_batch (3). Pinned as a known answer: a change here is a change in what a batch writes.
COMMITTED_BATCH_VERSION = 3

HARD_CODES = frozenset(
    {
        "duplicate_entity_id",
        "duplicate_batch_id",
        "unknown_entity_type",
        "entity_type_mismatch",
        "envelope_payload_name_mismatch",
        "dangling_edge",
        "execution_failed",
        "duplicate_removal_target",
        "entity_id_in_upsert_and_removal",
        "removal_target_missing",
        "removal_target_tombstoned",
        "removal_entity_type_mismatch",
        "grift_purge_refused_production",
        "entity_version_conflict",
        "duplicate_ref",
        "unknown_ref",
        "identity_ambiguous",
        "identity_undeclared",
        "retired_collision",
    }
)


class ModelError(ValueError):
    """The scenario asks the model something it cannot answer (a name misused)."""


@dataclass
class Row:
    name: str
    kind: str  # node | edge | batch
    type: str
    live: bool = True
    version: int = 1
    key: tuple[Any, ...] | None = None
    ends: tuple[str, str] | None = None
    spine_name: str | None = None
    #: Entity.dimensions when the scenario declared them (None: the model's defaults, unasserted)
    dims: dict[str, str] | None = None
    #: the batch that last wrote the row's CONTENT through an import (a create or a replace, of a
    #: node or an edge): the typed row's `batch_id`. A delete records its batch on its event and
    #: never moves this stamp (observed on the running pipeline, PR# 637 - tap review).
    last_batch: str | None = None
    #: the last full payload written (create or replace), for `expected.fields` spot checks
    props: dict[str, Any] | None = None
    #: an edge's `properties.hotlink.value`, for the page hotlink rule
    hotlink: str | None = None
    #: an edge's edge_type (the row's `type` is the entity type, `edge`)
    edge_type: str | None = None
    events: Counter[str] = field(default_factory=Counter)
    #: (event type, batch name) → count, for every event an IMPORT of this scenario recorded on
    #: the row: the provenance truth is which batch caused each event, not that some batch did
    #: (Codex, PR# 637 - tap). Grid-build events are not here; they precede the run.
    by_batch: Counter[tuple[str, str]] = field(default_factory=Counter)

    def type_is(self, edge_type: str) -> bool:
        return self.edge_type == edge_type


@dataclass
class ImportOutcome:
    success: bool
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    batches: dict[str, str] = field(default_factory=dict)
    resolves: dict[str, str] = field(default_factory=dict)
    #: per batch name: (nodes_imported, edges_imported) the result must report — what committed
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class Outcome:
    imports: list[ImportOutcome]
    rows: dict[str, Row]
    initial_events: dict[str, Counter[str]]
    alias: dict[str, str]
    purged: set[str]

    def canon(self, name: str) -> str:
        return self.alias.get(name, name)

    def event_delta(self) -> dict[tuple[str, str], int]:
        """Per (row name, event type): the count the run must add — negative for a purged row."""
        delta: dict[tuple[str, str], int] = {}
        names = set(self.rows) | set(self.initial_events)
        for name in names:
            after = self.rows[name].events if name in self.rows else Counter()
            before = self.initial_events.get(name, Counter())
            for event_type in set(after) | set(before):
                n = after.get(event_type, 0) - before.get(event_type, 0)
                if n:
                    delta[(name, event_type)] = n
        return delta

    def added_events(self) -> dict[tuple[str, str, str], int]:
        """Per (row name, event type, batch name): the events the imports must have recorded."""
        return {
            (name, event_type, batch): n
            for name, row in self.rows.items()
            for (event_type, batch), n in row.by_batch.items()
        }

    def live(self) -> dict[str, int]:
        return {r.name: r.version for r in self.rows.values() if r.kind != BATCH and r.live}

    def tombstoned(self) -> dict[str, int]:
        return {r.name: r.version for r in self.rows.values() if r.kind != BATCH and not r.live}


@dataclass
class _State:
    rows: dict[str, Row] = field(default_factory=dict)
    alias: dict[str, str] = field(default_factory=dict)
    purged: set[str] = field(default_factory=set)

    def canon(self, name: str) -> str:
        return self.alias.get(name, name)

    def row(self, name: str) -> Row | None:
        return self.rows.get(self.canon(name))


@dataclass
class _Target:
    name: str
    type: str
    kind: str  # edge | node
    section: str  # deletes | purges
    path: str
    expected_version: int | None


class _BatchFailed(Exception):
    def __init__(self, errors: list[tuple[str, str]]) -> None:
        super().__init__(errors)
        self.errors = errors


def constituting(entity_type: str, props: dict[str, Any]) -> tuple[Any, ...] | None:
    """The declared values that key a source object, or None when a value is missing or blank
    (nothing to search on: the row is assigned)."""
    fields = KEYED.get(entity_type)
    if fields is None:
        return None
    values = tuple(props.get(f) for f in fields)
    if any(v is None or (isinstance(v, str) and not v.strip()) for v in values):
        return None
    return values


def _name(obj: dict[str, Any]) -> str:
    return str(obj["id"] if "id" in obj else obj["ref"])


def _spine_name(node: dict[str, Any]) -> str | None:
    name = node.get("name") or node["props"].get("name")
    return str(name) if name else None


def build_grid(grid: dict[str, Any]) -> _State:
    state = _State()
    for n in grid["nodes"]:
        if n["name"] in state.rows:
            raise ModelError(f"grid node {n['name']!r} declared twice")
        state.rows[n["name"]] = Row(
            n["name"],
            "node",
            n["type"],
            key=constituting(n["type"], n["props"]),
            spine_name=n["props"].get("name"),
            props=dict(n["props"]),
        )
        state.rows[n["name"]].events["create"] = 1
    for e in grid["edges"]:
        if e["name"] in state.rows:
            raise ModelError(f"grid edge {e['name']!r} reuses a name")
        state.rows[e["name"]] = Row(
            e["name"], "edge", EDGE, ends=(e["from"], e["to"]), hotlink=_hotlink(e), edge_type=e["type"]
        )
        state.rows[e["name"]].events["link"] = 1
    for name in grid.get("tombstoned", ()):
        row = state.rows[name]
        if row.kind == "edge":
            _end_edge(row, event=True)
        else:
            _tombstone_node(state, row, events=1)
    for name in grid.get("cascaded", ()):
        _cascade(state, state.rows[name])
    return state


def _hotlink(obj: dict[str, Any]) -> str | None:
    value = ((obj.get("properties") or {}).get("hotlink") or {}).get("value")
    return str(value) if value is not None else None


def _cascade(state: _State, root: Row) -> None:
    """``delete_node(root, cascade="contained")``: the closure along NESTS edges retires, one
    delete event per node; every live edge touching the closure ends with one unlink event."""
    if not root.live:
        raise ModelError(f"cascaded {root.name!r} is already tombstoned")
    closure = {root.name}
    frontier = [root.name]
    while frontier:
        here = frontier.pop()
        for e in state.rows.values():
            if e.kind == "edge" and e.live and e.ends and e.ends[0] == here and e.type_is(NESTS):
                child = state.rows[e.ends[1]]
                if child.live and child.name not in closure:
                    closure.add(child.name)
                    frontier.append(child.name)
    for e in list(state.rows.values()):
        if e.kind == "edge" and e.live and e.ends and set(e.ends) & closure:
            _end_edge(e, event=True)
    for name in closure:
        row = state.rows[name]
        row.live = False
        row.version += 1
        row.events["delete"] += 1


def _end_edge(row: Row, *, event: bool, batch: str | None = None) -> None:
    row.live = False
    row.version += 1
    if event:
        _record(row, "unlink", batch)


def _tombstone_node(state: _State, row: Row, *, events: int, batch: str | None = None) -> None:
    row.live = False
    row.version += 1
    _record(row, "delete", batch, events)
    for other in state.rows.values():
        if other.kind == "edge" and other.live and other.ends is not None and row.name in other.ends:
            _end_edge(other, event=False)


def run(scenario: dict[str, Any]) -> Outcome:
    """The outcome of building ``grid`` and importing every document of ``imports`` in order.

    TAP-IMPLEMENTS: req-grid-batch-corpus-oracle@a296672473bc/602361839350 (derivation) — the one
        restatement of the import rules the corpus checks every hand answer against; nothing
        here reads the importer.
    """
    state = build_grid(scenario["grid"])
    initial = {name: Counter(row.events) for name, row in state.rows.items()}
    debug = bool((scenario.get("settings") or {}).get("debug", False))
    outcomes = [_import(state, imp, debug=debug) for imp in scenario["imports"]]
    return Outcome(outcomes, state.rows, initial, dict(state.alias), set(state.purged))


# --------------------------------------------------------------------------- preflight


def _import(state: _State, imp: dict[str, Any], *, debug: bool) -> ImportOutcome:
    batches = [copy.deepcopy(b) for b in imp["batches"]]
    mode = imp.get("dangling_edge_mode", "strict")
    out = ImportOutcome(success=True, batches={b["name"]: "refused" for b in batches})

    if imp.get("seed_boundary"):
        collision = _strip_retired(state, batches)
        if collision:
            out.errors.append(("retired_collision", "$"))
            out.success = False
            return out

    _refs_pass(batches, out)
    if out.errors:
        out.success = False
        return out

    all_ids: set[str] = set()
    all_batch: set[str] = set()
    file_node_ids: set[str] = set()
    to_import: list[int] = []
    targets_by_batch: dict[int, list[_Target]] = {}
    for bi, b in enumerate(batches):
        bp = f"$.batches[{bi}]"
        bref = b["name"]
        if bref in all_batch:
            out.errors.append(("duplicate_batch_id", f"{bp}.batch_entity.entity_id"))
            continue
        all_batch.add(bref)
        if bref in all_ids:
            out.errors.append(("duplicate_entity_id", f"{bp}.batch_entity.entity_id"))
            continue
        all_ids.add(bref)
        for j, n in enumerate(b.get("nodes", ())):
            np = f"{bp}.nodes[{j}]"
            name = _name(n)
            if "id" in n:
                if name in all_ids:
                    out.errors.append(("duplicate_entity_id", f"{np}.entity.entity_id"))
                    continue
                all_ids.add(name)
            file_node_ids.add(name)
            if n["type"] not in KEYED and n["type"] not in UNDECLARED:
                out.errors.append(("unknown_entity_type", f"{np}.node"))
            envelope_name, payload_name = n.get("name"), n["props"].get("name")
            if envelope_name and payload_name and envelope_name.strip() != payload_name.strip():
                out.errors.append(("envelope_payload_name_mismatch", f"{np}.entity.name"))
        for j, e in enumerate(b.get("edges", ())):
            name = _name(e)
            if "id" in e:
                if name in all_ids:
                    out.errors.append(("duplicate_entity_id", f"{bp}.edges[{j}].entity.entity_id"))
                    continue
                all_ids.add(name)
        targets = []
        for t in _targets(b, bp):
            # File-level (state-free) sanity: the sub-array is part of the declaration.
            if (t.kind == "edge") != (t.type == EDGE):
                out.errors.append(("removal_entity_type_mismatch", f"{t.path}.entity_type"))
                continue
            targets.append(t)
        seen: dict[str, _Target] = {}
        for t in targets:
            if t.name in seen:
                out.errors.append(("duplicate_removal_target", f"{t.path}.entity_id"))
                continue
            seen[t.name] = t
        if any(t.section == "purges" for t in targets) and not debug:
            out.errors.append(("grift_purge_refused_production", f"{bp}.purges"))
        targets_by_batch[bi] = targets
        existing = state.rows.get(bref)
        if existing is not None and existing.kind == BATCH:
            out.batches[bref] = "skipped"
            if targets:
                out.warnings.append("skipped_batch_had_removals")
        elif existing is not None:
            out.errors.append(("entity_type_mismatch", f"{bp}.batch_entity.entity_id"))
        else:
            to_import.append(bi)

    skipped_edges: set[tuple[int, int]] = set()
    for bi in to_import:
        b = batches[bi]
        for j, e in enumerate(b.get("edges", ())):
            for side in ("from", "to"):
                endpoint = e.get(side)
                if endpoint is None:
                    continue  # a from_ref/to_ref endpoint names a node ref of this batch
                grid_row = state.row(endpoint)
                if endpoint in file_node_ids or (grid_row is not None and grid_row.live):
                    continue
                if mode == "strict":
                    out.errors.append(("dangling_edge", f"$.batches[{bi}].edges[{j}].edge.{side}_entity_id"))
                else:
                    skipped_edges.add((bi, j))

    for bi in to_import:
        b = batches[bi]
        for j, n in enumerate(b.get("nodes", ())):
            row = state.row(_name(n)) if "id" in n else None
            if row is not None and row.type != n["type"]:
                out.errors.append(("entity_type_mismatch", f"$.batches[{bi}].nodes[{j}].entity.entity_type"))
        for j, e in enumerate(b.get("edges", ())):
            row = state.row(_name(e)) if "id" in e else None
            if row is not None and row.kind != "edge":
                out.errors.append(("entity_type_mismatch", f"$.batches[{bi}].edges[{j}].entity.entity_type"))

    seen_targets: dict[str, _Target] = {}
    for bi in to_import:
        for t in targets_by_batch[bi]:
            prior = seen_targets.get(t.name)
            if prior is not None and prior is not t:
                out.errors.append(("duplicate_removal_target", f"{t.path}.entity_id"))
            else:
                seen_targets[t.name] = t
    for name in sorted(seen_targets.keys() & all_ids):
        out.errors.append(("entity_id_in_upsert_and_removal", f"{seen_targets[name].path}.entity_id"))

    if any(code in HARD_CODES for code, _ in out.errors):
        out.success = False
        return out

    for bi in to_import:
        working = copy.deepcopy(state)
        bname = batches[bi]["name"]
        try:
            resolves = _execute(working, batches[bi], bi, skipped_edges, targets_by_batch[bi], out.warnings)
        except _BatchFailed as failed:
            out.errors.extend(failed.errors)
            out.batches[bname] = "failed"
            out.counts[bname] = (0, 0)  # rolled back: nothing was imported (Issue# 607 - tap)
            continue
        state.rows, state.alias, state.purged = working.rows, working.alias, working.purged
        out.resolves.update(resolves)
        out.batches[bname] = "committed"
        skipped_here = sum(1 for (b, _j) in skipped_edges if b == bi)
        out.counts[bname] = (len(batches[bi].get("nodes", ())), len(batches[bi].get("edges", ())) - skipped_here)
    for bname, state_name in out.batches.items():
        out.counts.setdefault(bname, (0, 0))
        if state_name in ("skipped", "refused"):
            out.counts[bname] = (0, 0)
    out.success = not any(code in HARD_CODES for code, _ in out.errors)
    return out


def _strip_retired(state: _State, batches: list[dict[str, Any]]) -> bool:
    """Drop retired-type nodes and the edges touching them, in place; True on a collision."""
    retained = {_name(n) for b in batches for n in b.get("nodes", ()) if n["type"] not in RETIRED}
    for b in batches:
        stripped = {_name(n) for n in b.get("nodes", ()) if n["type"] in RETIRED}
        for name in stripped:
            live_row = state.row(name)
            if name in retained or (live_row is not None and live_row.live):
                return True
        b["nodes"] = [n for n in b.get("nodes", ()) if _name(n) not in stripped]
        b["edges"] = [
            e
            for e in b.get("edges", ())
            if not ({e.get("from"), e.get("to"), e.get("from_ref"), e.get("to_ref")} & stripped)
        ]
    return False


def _refs_pass(batches: list[dict[str, Any]], out: ImportOutcome) -> None:
    for bi, b in enumerate(batches):
        bp = f"$.batches[{bi}]"
        seen: set[str] = set()
        node_refs: set[str] = set()
        for j, n in enumerate(b.get("nodes", ())):
            if "ref" not in n:
                continue
            if n["ref"] in seen:
                out.errors.append(("duplicate_ref", f"{bp}.nodes[{j}].entity.ref"))
                continue
            seen.add(n["ref"])
            node_refs.add(n["ref"])
        for j, e in enumerate(b.get("edges", ())):
            if "ref" in e:
                if e["ref"] in seen:
                    out.errors.append(("duplicate_ref", f"{bp}.edges[{j}].entity.ref"))
                else:
                    seen.add(e["ref"])
            for key in ("from_ref", "to_ref"):
                if key in e and e[key] not in node_refs:
                    out.errors.append(("unknown_ref", f"{bp}.edges[{j}].edge.{key}"))


def _targets(b: dict[str, Any], bp: str) -> list[_Target]:
    out: list[_Target] = []
    for section in ("deletes", "purges"):
        block = b.get(section)
        if block is None:
            continue
        for sub, kind in (("edges", "edge"), ("nodes", "node")):
            for k, t in enumerate(block.get(sub, ())):
                out.append(
                    _Target(t["id"], t["type"], kind, section, f"{bp}.{section}.{sub}[{k}]", t.get("expected_version"))
                )
    return out


# --------------------------------------------------------------------------- execution


def _execute(
    w: _State,
    b: dict[str, Any],
    bi: int,
    skipped_edges: set[tuple[int, int]],
    targets: list[_Target],
    warnings: list[str],
) -> dict[str, str]:
    bp = f"$.batches[{bi}]"
    bref = b["name"]
    batch_row = Row(bref, BATCH, BATCH, version=COMMITTED_BATCH_VERSION)
    w.rows[bref] = batch_row
    nodes = list(b.get("nodes", ()))
    edges = list(b.get("edges", ()))

    resolves = _resolve_refs(w, nodes, bp)
    _refuse_cross_addressing(w, b, nodes, edges, targets, bp)

    for j, n in enumerate(nodes):
        if n.get("expected_version") is not None and w.row(_name(n)) is None:
            raise _BatchFailed([("entity_version_conflict", f"{bp}.nodes[{j}].entity.entity_expected_version")])
    for j, e in enumerate(edges):
        if (bi, j) in skipped_edges:
            continue
        if e.get("expected_version") is not None and w.row(_name(e)) is None:
            raise _BatchFailed([("entity_version_conflict", f"{bp}.edges[{j}].entity.entity_expected_version")])

    written_pages: list[tuple[str, str]] = []
    for j, n in enumerate(nodes):
        name = w.canon(_name(n))
        row = w.rows.get(name)
        declared_dims = dict(n["dimensions"]) if "dimensions" in n else None
        if n["type"] == "page":
            written_pages.append((name, f"{bp}.nodes[{j}]"))
        if row is None:
            w.rows[name] = Row(
                name,
                "node",
                n["type"],
                key=constituting(n["type"], n["props"]),
                spine_name=_spine_name(n),
                dims=declared_dims or None,  # {} on a create: the model's defaults, unasserted
                last_batch=bref,
                props=dict(n["props"]),
            )
            _record(w.rows[name], "create", bref)
            continue
        _replace(row, n.get("expected_version"), f"{bp}.nodes[{j}]", bref)
        row.key = constituting(n["type"], n["props"])
        row.last_batch = bref
        row.props = dict(n["props"])
        if declared_dims is not None:
            row.dims = declared_dims
        if n.get("name") or n["props"].get("name"):
            row.spine_name = _spine_name(n)
    for j, e in enumerate(edges):
        if (bi, j) in skipped_edges:
            warnings.append("dangling_edge")
            continue
        name = w.canon(_name(e))
        row = w.rows.get(name)
        ends = (w.canon(e.get("from") or e["from_ref"]), w.canon(e.get("to") or e["to_ref"]))
        if row is None:
            w.rows[name] = Row(name, "edge", EDGE, ends=ends, hotlink=_hotlink(e), edge_type=e["type"], last_batch=bref)
            _record(w.rows[name], "link", bref)
            continue
        _replace(row, e.get("expected_version"), f"{bp}.edges[{j}]", bref)
        row.ends, row.hotlink, row.last_batch = ends, _hotlink(e), bref

    plan_deletes, plan_purges = _lock_targets(w, b, targets, warnings)
    for t in plan_deletes:
        row = w.rows[w.canon(t.name)]
        if t.expected_version is not None and t.expected_version != row.version:
            raise _BatchFailed([("entity_version_conflict", t.path)])
        if t.kind == "edge":
            _end_edge(row, event=True, batch=bref)
            _record(row, "unlink", bref)  # the bundle-reason event beside the pipeline's
        else:
            _tombstone_node(w, row, events=2, batch=bref)
    for t in plan_purges:
        row = w.rows[w.canon(t.name)]
        if t.expected_version is not None and t.expected_version != row.version:
            raise _BatchFailed([("entity_version_conflict", t.path)])
        gone = {row.name}
        if row.kind == "node":
            gone |= {o.name for o in w.rows.values() if o.kind == "edge" and o.ends and row.name in o.ends}
        for name in gone:
            del w.rows[name]
            w.purged.add(name)
        _record(batch_row, "unlink" if t.kind == "edge" else "delete", bref)
    for name, path in written_pages:
        _check_page_hotlinks(w, w.rows[name], path)
    return resolves


def _layout_panel_ids(layout: Any) -> set[str]:
    """Every `panel-id` under `columns.*.rows.*` of a page layout (the `page-panels` hotlink)."""
    out: set[str] = set()
    for column in (layout or {}).get("columns", {}).values():
        for row in (column or {}).get("rows", {}).values():
            if isinstance(row, dict) and row.get("panel-id") is not None:
                out.add(str(row["panel-id"]))
    return out


def _check_page_hotlinks(w: _State, page: Row, path: str) -> None:
    """The `page-panels` exact hotlink over the post-batch graph: the layout's panel-ids and the
    hotlink values of the page's live USES_PANEL edges are one set (Issue# 351 - tap)."""
    declared = _layout_panel_ids((page.props or {}).get("layout"))
    linked = {
        e.hotlink
        for e in w.rows.values()
        if e.kind == "edge" and e.live and e.ends and e.ends[0] == page.name and e.edge_type == USES_PANEL
    }
    if declared != {h for h in linked if h is not None}:
        raise _BatchFailed([("execution_failed", path)])


def _record(row: Row, event_type: str, batch: str | None, n: int = 1) -> None:
    """One event of ``event_type`` on ``row``; attributed to ``batch`` when an import recorded it."""
    row.events[event_type] += n
    if batch is not None:
        row.by_batch[(event_type, batch)] += n


def _replace(row: Row, expected_version: int | None, path: str, batch: str) -> None:
    if not row.live:
        raise _BatchFailed([("execution_failed", path)])
    if expected_version is not None and expected_version != row.version:
        raise _BatchFailed([("entity_version_conflict", path)])
    row.version += 1
    _record(row, "update", batch)


def _resolve_refs(w: _State, nodes: list[dict[str, Any]], bp: str) -> dict[str, str]:
    resolves: dict[str, str] = {}
    taken: set[str] = set()
    keys_seen: set[tuple[str, tuple[Any, ...]]] = set()  # the identity key is (type, values), never values alone
    for j, n in enumerate(nodes):
        if "ref" not in n:
            continue
        path = f"{bp}.nodes[{j}].entity.ref"
        ref = n["ref"]
        if n["type"] in UNDECLARED:
            raise _BatchFailed([("identity_undeclared", path)])
        key = constituting(n["type"], n["props"])
        if key is None:
            _assign(w, ref)
            continue
        matches = [r for r in w.rows.values() if r.kind == "node" and r.type == n["type"] and r.live and r.key == key]
        if len(matches) > 1:
            raise _BatchFailed([("identity_ambiguous", path)])
        if len(matches) == 1:
            found = matches[0].name
            if found in taken:
                raise _BatchFailed([("duplicate_entity_id", path)])
            taken.add(found)
            if found != ref:
                w.alias[ref] = found
                resolves[ref] = found
            continue
        if (n["type"], key) in keys_seen:
            raise _BatchFailed([("duplicate_entity_id", path)])  # Issue# 602 - tap: one source object, two refs
        keys_seen.add((n["type"], key))
        _assign(w, ref)
    return resolves


def _refuse_cross_addressing(
    w: _State,
    b: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    targets: list[_Target],
    bp: str,
) -> None:
    """A ref that resolved to a row this batch also addresses by explicit id is the same
    duplicate the id path refuses, and one that resolved to a removal target of this batch is
    the same upsert-versus-removal overlap — both judged against the RESOLVED id, so the
    addressing syntax cannot turn a collision into last-write-wins or create-then-delete
    (Issue# 606 - tap, Codex; FHIR's "identities that overlap after resolution")."""
    by_id = {_name(o) for o in list(nodes) + list(edges) if "id" in o}
    removed = {t.name for t in targets}
    for j, n in enumerate(nodes):
        if "ref" not in n or n["ref"] not in w.alias:
            continue
        found = w.alias[n["ref"]]
        path = f"{bp}.nodes[{j}].entity.ref"
        if found in by_id:
            raise _BatchFailed([("duplicate_entity_id", path)])
        if found in removed:
            raise _BatchFailed([("entity_id_in_upsert_and_removal", path)])


def _assign(w: _State, ref: str) -> None:
    if ref in w.alias:
        del w.alias[ref]
    if ref in w.rows:
        raise ModelError(
            f"ref {ref!r} is assigned a new row but {ref!r} already names one; a re-sent source object that "
            "does not find its row must carry a new name"
        )


def _lock_targets(
    w: _State, b: dict[str, Any], targets: list[_Target], warnings: list[str]
) -> tuple[list[_Target], list[_Target]]:
    hard: list[tuple[str, str]] = []
    deletes: list[_Target] = []
    purges: list[_Target] = []
    for t in targets:
        section = b[t.section]
        on_missing = section.get("on_missing") or "error"
        on_tombstoned = section.get("on_tombstoned") or "ignore"
        row = w.row(t.name)
        if row is None:
            if on_missing == "error":
                hard.append(("removal_target_missing", t.path))
            elif on_missing == "warn":
                warnings.append("removal_target_missing_warned")
            continue
        if row.type != t.type:
            hard.append(("removal_entity_type_mismatch", t.path))
            continue
        if t.section == "deletes" and not row.live:
            if on_tombstoned == "error":
                hard.append(("removal_target_tombstoned", t.path))
            elif on_tombstoned == "warn":
                warnings.append("removal_target_tombstoned_warned")
            continue
        (deletes if t.section == "deletes" else purges).append(t)
    if hard:
        raise _BatchFailed(hard)
    return deletes, purges
