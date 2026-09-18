"""Load, validate and oracle-check the corpus scenario files.

A scenario is refused at load — before any database work — when it does not fit the
schema, when a ref does not resolve, when its outcome would depend on the order the
walk meets siblings (a block and an overflow both reachable), or when the hand-authored
expectation disagrees with the reference model. The disagreement message names both sides: either the author or the model is
wrong, and a reader can tell which from the spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tap.jsonfiles import load_schema, validate_json
from tap_grid.cascade_corpus import model_oracle

CORPUS_DIR = Path(__file__).resolve().parent / "scenarios"
SCHEMA_PATH = Path(__file__).resolve().parent / "cascade.schema.json"
_SCHEMA: dict[str, Any] = load_schema(SCHEMA_PATH)


class CorpusError(ValueError):
    """A scenario file the corpus refuses to run."""


@dataclass(frozen=True)
class Scenario:
    family: str
    name: str
    covers: tuple[str, ...]
    tags: tuple[str, ...]
    pending: str | None
    graph: model_oracle.Graph
    verb: str
    target: str
    cascade: str
    reason: str | None
    metadata: dict[str, Any]
    cap: int
    expected: dict[str, Any]
    oracle: model_oracle.Outcome
    #: ref → the parents a cascaded node or ended edge may legitimately name as
    #: consequence_of. More than one only where the graph itself is ambiguous: a shared
    #: child is discovered by whichever containing parent the database returned first,
    #: and an edge between two retired nodes ends with whichever endpoint retired first.
    source: str = field(compare=False)

    @property
    def id(self) -> str:
        return f"{self.family}::{self.name}"


def _graph(raw: dict[str, Any], where: str) -> model_oracle.Graph:
    node_type = {n["ref"]: n["type"] for n in raw["nodes"]}
    if len(node_type) != len(raw["nodes"]):
        raise CorpusError(f"{where}: duplicate node ref")
    edge_refs = [e["ref"] for e in raw["edges"]]
    if len(set(edge_refs)) != len(edge_refs) or set(edge_refs) & set(node_type):
        raise CorpusError(f"{where}: edge refs must be unique and distinct from node refs")
    for e in raw["edges"]:
        for end in ("from", "to"):
            if e[end] not in node_type:
                raise CorpusError(f"{where}: edge {e['ref']!r} {end}={e[end]!r} names no node")
    for ref in raw.get("pre_retired", []):
        if ref not in node_type and ref not in edge_refs:
            raise CorpusError(f"{where}: pre_retired {ref!r} names no node or edge")
    return model_oracle.Graph(
        node_type=node_type,
        edges=tuple((e["ref"], e["from"], e["to"], e["type"]) for e in raw["edges"]),
        containment={t: tuple(v) for t, v in (raw.get("containment") or {}).items()},
        blocked_types=frozenset(raw.get("blocked_types") or ()),
        pre_retired=frozenset(r for r in raw.get("pre_retired") or () if r in node_type),
        pre_retired_edges=frozenset(r for r in raw.get("pre_retired") or () if r in edge_refs),
    )


def _check_against_oracle(scenario_raw: dict[str, Any], graph: model_oracle.Graph, where: str) -> model_oracle.Outcome:
    op = scenario_raw["operation"]
    if op["target"] not in graph.node_type:
        raise CorpusError(f"{where}: operation target {op['target']!r} names no node")
    universe = set(graph.node_type) | {e[0] for e in graph.edges}
    bad_keys = sorted(k for k in (scenario_raw["expected"].get("events") or {}) if k not in universe)
    if bad_keys:
        raise CorpusError(f"{where}: expected.events names unknown refs {bad_keys}")
    try:
        model = model_oracle.cascade(
            graph, op["target"], mode=op.get("cascade", "none"), reason=op.get("reason"), cap=op.get("cap", 5000)
        )
    except model_oracle.AmbiguousScenario as exc:
        raise CorpusError(
            f"{where}: the outcome depends on sibling order — {exc}; construct the scenario so it does not"
        ) from exc
    expected = scenario_raw["expected"]
    for key in ("retired_nodes", "retired_edges"):
        allowed = set(graph.node_type) if key == "retired_nodes" else {e[0] for e in graph.edges}
        unknown = [r for r in expected[key] if r not in allowed]
        if unknown:
            raise CorpusError(f"{where}: expected.{key} names unknown refs {unknown}")
    disagreements: list[str] = []
    if expected["outcome"] != model.outcome:
        disagreements.append(f"outcome: author says {expected['outcome']!r}, model says {model.outcome!r}")
    if expected.get("error_code") != model.error_code:
        disagreements.append(f"error_code: author says {expected.get('error_code')!r}, model says {model.error_code!r}")
    if sorted(expected["retired_nodes"]) != sorted(model.retired_nodes):
        disagreements.append(
            f"retired_nodes: author says {sorted(expected['retired_nodes'])}, model says {sorted(model.retired_nodes)}"
        )
    if sorted(expected["retired_edges"]) != sorted(model.retired_edges):
        disagreements.append(
            f"retired_edges: author says {sorted(expected['retired_edges'])}, model says {sorted(model.retired_edges)}"
        )
    for ref, spot in (expected.get("events") or {}).items():
        if "reason" in spot:
            model_reason = model.node_reason.get(ref, "cascaded" if ref in model.edge_parents else None)
            if model_reason != spot["reason"]:
                disagreements.append(
                    f"events[{ref}].reason: author says {spot['reason']!r}, model says {model_reason!r}"
                )
        if "consequence_of" in spot:
            options = model.node_parents.get(ref) or model.edge_parents.get(ref) or frozenset()
            if spot["consequence_of"] not in options:
                disagreements.append(
                    f"events[{ref}].consequence_of: author says {spot['consequence_of']!r}, model allows {sorted(options)}"
                )
    if disagreements:
        raise CorpusError(
            f"{where}: the hand-authored expectation and the reference model disagree — " + "; ".join(disagreements)
        )
    return model


def load_file(path: Path) -> list[Scenario]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_json(raw, _SCHEMA, source=path)
    out: list[Scenario] = []
    for i, s in enumerate(raw["scenarios"]):
        where = f"{path.name} scenarios[{i}] ({s.get('name', '?')})"
        graph = _graph(s["graph"], where)
        oracle = _check_against_oracle(s, graph, where)
        op = s["operation"]
        out.append(
            Scenario(
                family=raw["family"],
                name=s["name"],
                covers=tuple(s["covers"]),
                tags=tuple(s.get("tags", ())),
                pending=s.get("pending"),
                graph=graph,
                verb=op.get("verb", "delete_node"),
                target=op["target"],
                cascade=op.get("cascade", "none"),
                reason=op.get("reason"),
                metadata=dict(op.get("metadata") or {}),
                cap=int(op.get("cap", 5000)),
                expected=s["expected"],
                oracle=oracle,
                source=str(path),
            )
        )
    return out


def load_corpus(directory: Path = CORPUS_DIR) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for path in sorted(directory.glob("*.cascade.json")):
        scenarios.extend(load_file(path))
    names = [s.id for s in scenarios]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise CorpusError(f"duplicate scenario ids: {dupes}")
    return scenarios
