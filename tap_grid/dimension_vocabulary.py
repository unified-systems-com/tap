"""The declared dimension vocabulary, read from seed documents (req-grid-dimension-reference-8).

WORKAROUND(unified-systems-com/tap#1188): a dimension name resolves to its node's uuid through a
static table built from every installed plugin's and core's GRIFT seed documents, with no database.
Plugin Dimension nodes reach a grid only through boot's seed-plugin step, which runs after
``migrate`` and only for plugins a profile seeds, so a lookup against Dimension rows would find
nothing during the data migration and before boot. Reading the declarations from the seed files
gives the same answer without that ordering problem (George, 2026-11-12, aws-build Q54 D1). A
stored uuid may therefore exist briefly before its node row lands. Nothing is ever minted: a name
that no seed declares is unknown (Q48a).

The table is built once, lazily, after every app is ready (plugin manifests load in their
``ready()``), and never touched per write.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CORE_SEED = Path(__file__).resolve().parent / "data" / "dimensions.grift.json"


@dataclass(frozen=True)
class DeclaredDimension:
    """One Dimension node as a seed document declares it."""

    id: str
    name: str
    values: tuple[str, ...] | None
    usable_in_keys: bool
    source: str

    def accepts(self, value: str) -> bool:
        """Any string for an open dimension; a listed one for a bounded dimension (Q47)."""
        return self.values is None or value in self.values


@dataclass(frozen=True)
class Vocabulary:
    by_id: dict[str, DeclaredDimension]
    by_name: dict[str, tuple[str, ...]]  # name -> every distinct id declaring it


_lock = threading.Lock()
_table: Vocabulary | None = None


def _dimension_nodes(document: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Each Dimension node with its seed batch's id (a UUIDv7, so later batches sort later)."""
    for batch in document.get("batches") or []:
        batch_id = str((batch.get("batch_entity") or {}).get("entity_id") or "")
        for node in batch.get("nodes") or []:
            entity = node.get("entity") or {}
            if entity.get("entity_type") == "dimension":
                yield batch_id, node


def _declared(node: dict[str, Any], source: str) -> DeclaredDimension | None:
    entity = node.get("entity") or {}
    payload = node.get("node") or {}
    name = payload.get("name") or entity.get("name")
    try:
        ident = str(uuid.UUID(str(entity.get("entity_id"))))
    except ValueError:
        logger.warning("[d1c4] dimension seed %s: a node has no valid entity_id; skipped", source)
        return None
    if not isinstance(name, str) or not name:
        logger.warning("[d1c5] dimension seed %s: node %s has no name; skipped", source, ident)
        return None
    values = payload.get("values")
    return DeclaredDimension(
        id=ident,
        name=name,
        values=tuple(values) if isinstance(values, list) else None,
        usable_in_keys=bool(payload.get("usable_in_keys", False)),
        source=source,
    )


def _seed_files() -> Iterator[tuple[str, Path]]:
    yield ("tap_grid", CORE_SEED)
    from django.apps import apps

    from tap_plugins.base import TapPluginConfig

    for config in apps.get_app_configs():
        if not isinstance(config, TapPluginConfig) or config.manifest is None:
            continue
        manifest = config.manifest
        for entry in manifest.grift:
            yield (f"{manifest.slug}:{entry.path}", Path(manifest.plugin_root) / entry.path)


def build(files: Iterable[tuple[str, Path]] | None = None) -> Vocabulary:
    """Read every seed document and index its Dimension nodes by id and by name.

    A node keeps its uuid when it is renamed or moves to another plugin's seed (George, 2026-11-12,
    aws-build Q56: ``tap.cloud`` became ``tap.computing.cloud`` and moved from aws_core's seed to
    computing_core's). So one id declared under two names is one dimension, not a duplicate: its
    current name is the one from the latest seed batch (batch ids are UUIDv7, ordered by time), and
    every name it was declared under still resolves to it while both seeds are installed. Two
    different ids under one name remain ambiguous.
    """
    latest: dict[str, tuple[str, DeclaredDimension]] = {}
    names: dict[str, list[str]] = {}
    for source, path in files if files is not None else _seed_files():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("[d1c6] dimension seed %s unreadable (%s); skipped", source, error)
            continue
        for batch_id, node in _dimension_nodes(document):
            declared = _declared(node, source)
            if declared is None:
                continue
            seen = latest.get(declared.id)
            if seen is None or batch_id > seen[0]:
                latest[declared.id] = (batch_id, declared)
            ids = names.setdefault(declared.name, [])
            if declared.id not in ids:
                ids.append(declared.id)
    by_id = {ident: declared for ident, (_batch, declared) in latest.items()}
    return Vocabulary(by_id=by_id, by_name={name: tuple(ids) for name, ids in names.items()})


def vocabulary() -> Vocabulary:
    """The table, built once on first use after the app registry is ready."""
    global _table
    if _table is None:
        with _lock:
            if _table is None:
                _table = build()
    return _table


def reset(table: Vocabulary | None = None) -> None:
    """Replace (or drop, to rebuild on next use) the table. For tests and plugin reloads."""
    global _table
    with _lock:
        _table = table
