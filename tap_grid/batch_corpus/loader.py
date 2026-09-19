"""Load, validate and oracle-check the batch playground's scenario files.

A scenario is refused at load — before any database work — when it does not fit the schema,
when a name does not resolve, when it uses a type the reference model does not declare, or
when the hand-authored expectation disagrees with the model. The disagreement message names
both sides: either the author or the model is wrong, and a reader can tell which from the spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tap.jsonfiles import load_schema, validate_json
from tap_grid.batch_corpus import model_oracle

CORPUS_DIR = Path(__file__).resolve().parent / "scenarios"
SCHEMA_PATH = Path(__file__).resolve().parent / "batch.schema.json"
_SCHEMA: dict[str, Any] = load_schema(SCHEMA_PATH)
_ROLE = ".batch.json"


class CorpusError(ValueError):
    """A scenario file the corpus refuses to run."""


@dataclass(frozen=True)
class Scenario:
    family: str
    name: str
    covers: tuple[str, ...]
    tags: tuple[str, ...]
    pending: str | None
    raw: dict[str, Any]
    oracle: model_oracle.Outcome
    #: every node, edge and phantom name the scenario mentions (batch names and aliases excluded)
    universe: frozenset[str]
    source: str = field(compare=False)

    @property
    def id(self) -> str:
        return f"{self.family}::{self.name}"

    @property
    def debug(self) -> bool:
        return bool((self.raw.get("settings") or {}).get("debug", False))

    @property
    def expected(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.raw["expected"])

    @property
    def grid(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.raw["grid"])

    @property
    def imports(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.raw["imports"])


def _names(raw: dict[str, Any], where: str) -> tuple[set[str], set[str], set[str]]:
    """(node/edge names, batch names, phantom names), with the naming rules enforced."""
    grid = raw["grid"]
    grid_names = [n["name"] for n in grid["nodes"]] + [e["name"] for e in grid["edges"]]
    if len(set(grid_names)) != len(grid_names):
        raise CorpusError(f"{where}: a grid name is used twice")
    grid_nodes = {n["name"] for n in grid["nodes"]}
    for e in grid["edges"]:
        for end in ("from", "to"):
            if e[end] not in grid_nodes:
                raise CorpusError(f"{where}: grid edge {e['name']!r} {end}={e[end]!r} names no grid node")
    for name in grid.get("tombstoned", ()):
        if name not in grid_names:
            raise CorpusError(f"{where}: tombstoned {name!r} names no grid node or edge")
    for name in grid.get("cascaded", ()):
        if name not in grid_nodes:
            raise CorpusError(f"{where}: cascaded {name!r} names no grid node")
    doc_names: set[str] = set()
    batch_names: set[str] = set()
    phantoms = set(raw.get("phantoms", ()))
    for imp in raw["imports"]:
        for b in imp["batches"]:
            batch_names.add(b["name"])
            batch_refs = {n["ref"] for n in b.get("nodes", ()) if "ref" in n}
            for n in b.get("nodes", ()):
                if n["type"] not in set(model_oracle.KEYED) | model_oracle.UNDECLARED | model_oracle.RETIRED:
                    raise CorpusError(f"{where}: node type {n['type']!r} is not in the oracle's declaration table")
                doc_names.add(n["id"] if "id" in n else n["ref"])
            for e in b.get("edges", ()):
                doc_names.add(e["id"] if "id" in e else e["ref"])
                for side in ("from", "to"):
                    if (side in e) == (f"{side}_ref" in e):
                        raise CorpusError(
                            f"{where}: edge {e.get('id') or e.get('ref')!r} needs exactly one of {side} / {side}_ref"
                        )
                    if (
                        f"{side}_ref" in e
                        and e[f"{side}_ref"] not in batch_refs
                        and e[f"{side}_ref"] not in doc_names | grid_nodes
                    ):
                        raise CorpusError(f"{where}: {side}_ref={e[f'{side}_ref']!r} names nothing in the scenario")
    endpoints_and_targets: set[str] = set()
    known_ids: set[str] = set(grid_names) | phantoms
    for imp in raw["imports"]:
        refs_of_import = {n["ref"] for b in imp["batches"] for n in b.get("nodes", ()) if "ref" in n}
        for b in imp["batches"]:
            batch_refs = {n["ref"] for n in b.get("nodes", ()) if "ref" in n}
            for e in b.get("edges", ()):
                endpoints_and_targets |= {e[s] for s in ("from", "to") if s in e}
                for side in ("from", "to"):
                    name = e.get(side)
                    if name in refs_of_import - batch_refs and name not in known_ids:
                        raise CorpusError(
                            f"{where}: edge {e.get('id') or e.get('ref')!r} {side}={name!r} names a ref of another "
                            "batch of the same import — not expressible: refs are batch-local and an assigned id "
                            "is not known until the import returns; address it by id or send it in a later import"
                        )
        for b in imp["batches"]:
            known_ids |= {o["id"] for o in list(b.get("nodes", ())) + list(b.get("edges", ())) if "id" in o}
            known_ids |= {n["ref"] for n in b.get("nodes", ()) if "ref" in n}
            for section in ("deletes", "purges"):
                for sub in ("edges", "nodes"):
                    endpoints_and_targets |= {t["id"] for t in (b.get(section) or {}).get(sub, ())}
    known = set(grid_names) | doc_names | phantoms
    unknown = sorted(endpoints_and_targets - known)
    if unknown:
        raise CorpusError(f"{where}: {unknown} are named as endpoints or targets but declared nowhere; list phantoms")
    if batch_names & (set(grid_names) | doc_names | phantoms):
        raise CorpusError(f"{where}: a batch name reuses a node, edge or phantom name")
    return set(grid_names) | doc_names, batch_names, phantoms


def _check_against_oracle(raw: dict[str, Any], where: str) -> tuple[model_oracle.Outcome, frozenset[str]]:
    nodes_and_edges, batch_names, phantoms = _names(raw, where)
    try:
        model = model_oracle.run(raw)
    except model_oracle.ModelError as exc:
        raise CorpusError(f"{where}: {exc}") from exc
    expected = raw["expected"]
    disagreements: list[str] = []
    if len(expected["imports"]) != len(model.imports):
        raise CorpusError(
            f"{where}: expected.imports has {len(expected['imports'])} entries for {len(model.imports)} imports"
        )
    for i, (hand, got) in enumerate(zip(expected["imports"], model.imports, strict=True)):
        if hand["success"] != got.success:
            disagreements.append(f"imports[{i}].success: author says {hand['success']}, model says {got.success}")
        if hand["batches"] != got.batches:
            disagreements.append(f"imports[{i}].batches: author says {hand['batches']}, model says {got.batches}")
        hand_errors = sorted((e["code"], e["path"]) for e in hand["errors"])
        if hand_errors != sorted(got.errors):
            disagreements.append(f"imports[{i}].errors: author says {hand_errors}, model says {sorted(got.errors)}")
        if "warnings" in hand and sorted(hand["warnings"]) != sorted(got.warnings):
            disagreements.append(
                f"imports[{i}].warnings: author says {sorted(hand['warnings'])}, model says {sorted(got.warnings)}"
            )
    universe = frozenset((nodes_and_edges | phantoms) - set(model.alias))
    for key, got_rows in (("live", model.live()), ("tombstoned", model.tombstoned())):
        if expected[key] != got_rows:
            disagreements.append(f"{key}: author says {expected[key]}, model says {got_rows}")
    absent = sorted(universe - set(model.live()) - set(model.tombstoned()))
    if sorted(expected["absent"]) != absent:
        disagreements.append(f"absent: author says {sorted(expected['absent'])}, model says {absent}")
    resolves = {ref: found for imp in model.imports for ref, found in imp.resolves.items()}
    if (expected.get("resolves") or {}) != resolves:
        disagreements.append(f"resolves: author says {expected.get('resolves') or {}}, model says {resolves}")
    for name, dims in (expected.get("dimensions") or {}).items():
        row = model.rows.get(model.canon(name))
        got_dims = row.dims if row is not None else None
        if got_dims != dims:
            disagreements.append(f"dimensions[{name}]: author says {dims}, model says {got_dims}")
    for name, fields in (expected.get("fields") or {}).items():
        row = model.rows.get(model.canon(name))
        # A field the last payload omitted is the model's default, which the reference model does not
        # know: the runner alone judges it against the typed row. Every field the payload carried must agree.
        got_fields = {k: (row.props or {}).get(k, fields[k]) for k in fields} if row is not None else None
        if got_fields != fields:
            disagreements.append(f"fields[{name}]: author says {fields}, model says {got_fields}")
    for i, hand in enumerate(expected["imports"]):
        for bname, counts in (hand.get("counts") or {}).items():
            got_counts = model.imports[i].counts.get(bname)
            if got_counts != (counts["nodes"], counts["edges"]):
                disagreements.append(f"imports[{i}].counts[{bname}]: author says {counts}, model says {got_counts}")
    delta = model.event_delta()
    for name, spots in (expected.get("events") or {}).items():
        if name not in universe and name not in batch_names:
            disagreements.append(f"events[{name}]: names nothing")
            continue
        for event_type, n in spots.items():
            got_n = delta.get((model.canon(name), event_type), 0)
            if got_n != n:
                disagreements.append(f"events[{name}].{event_type}: author says {n}, model says {got_n}")
    if disagreements:
        raise CorpusError(
            f"{where}: the hand-authored expectation and the reference model disagree — " + "; ".join(disagreements)
        )
    return model, universe


def load_file(path: Path) -> list[Scenario]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_json(raw, _SCHEMA, source=path)
    out: list[Scenario] = []
    for i, s in enumerate(raw["scenarios"]):
        where = f"{path.name} scenarios[{i}] ({s.get('name', '?')})"
        oracle, universe = _check_against_oracle(s, where)
        out.append(
            Scenario(
                family=raw["family"],
                name=s["name"],
                covers=tuple(s["covers"]),
                tags=tuple(s.get("tags", ())),
                pending=s.get("pending"),
                raw=s,
                oracle=oracle,
                universe=universe,
                source=str(path),
            )
        )
    return out


def load_corpus(directory: Path = CORPUS_DIR) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for path in sorted(directory.glob(f"*{_ROLE}")):
        scenarios.extend(load_file(path))
    names = [s.id for s in scenarios]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise CorpusError(f"duplicate scenario ids: {dupes}")
    return scenarios
