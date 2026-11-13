from typing import Any

from django.db import migrations


def _type_defaults(entity_type: str, edge_type: str | None) -> dict[str, str]:
    """The declared defaults the row's type stamps today: an edge type's for an edge row, the model's
    otherwise. A type that is no longer installed has none."""
    if edge_type is not None:
        from tap_grid.constraints import get_edge_default_dimensions

        return dict(get_edge_default_dimensions(edge_type))
    from tap_grid.registry import get_model_class

    try:
        return dict(getattr(get_model_class(entity_type), "DEFAULT_DIMENSIONS", {}))
    except KeyError:
        return {}


def _declared_id(key: str) -> str | None:
    from tap_grid.dimension_names import declared

    try:
        return declared(key).id
    except LookupError:
        return None


def forwards(apps: Any, schema_editor: Any) -> None:
    """Re-key every row's dimensions by dimension node id, each value {"v", "src"} (unified-systems-com/tap#711).

    WORKAROUND(unified-systems-com/tap#1188): names resolve through the static vocabulary read from
    the installed seed documents (tap_grid.dimension_vocabulary), not through Dimension rows, which
    boot seeds only after migrate. `src` is `default` when the value equals what the row's type
    declares as its default for that key today, else `declared` (aws-build Q48b). A key no seed
    declares stops the migration before anything is rewritten, listing each such key and the types
    carrying it (aws-build Q50a): dimensions are declared, never minted (Q48a). Two names of one
    renamed dimension on one row merge when their values agree and stop the migration, naming the row,
    when they differ.

    Upgrade order (aws-build Q59 D7): install and migrate the aws_core release that renames its keys
    (Q56) and computing_core's seed before this one, or this stops on the old names.
    """
    Entity = apps.get_model("tap_grid", "Entity")
    Edge = apps.get_model("tap_grid", "Edge")
    alias = schema_editor.connection.alias
    edge_types = dict(Edge.objects.using(alias).values_list("entity_id", "edge_type"))

    undeclared: dict[str, set[str]] = {}
    collisions: list[str] = []
    rewrites: list[tuple[Any, dict[str, dict[str, str]]]] = []
    rows = Entity.objects.using(alias).exclude(dimensions={}).values_list("id", "entity_type", "dimensions")
    for entity_id, entity_type, dims in rows.iterator(chunk_size=2000):
        if not isinstance(dims, dict) or not dims:
            continue
        edge_type = edge_types.get(entity_id)
        defaults = _type_defaults(entity_type, edge_type)
        new: dict[str, dict[str, str]] = {}
        for key, value in dims.items():
            if isinstance(value, dict) and "v" in value:
                new[key] = value  # already re-keyed (a re-run, or a row written by new code)
                continue
            dim_id = _declared_id(key)
            if dim_id is None:
                undeclared.setdefault(key, set()).add(edge_type or entity_type)
                continue
            src = "default" if defaults.get(key) == value else "declared"
            entry = {"v": str(value), "src": src}
            if dim_id in new:
                # Two legacy names for one renamed dimension (aws-build Q56) on one row: equal values
                # are one fact, kept once (declared wins over default); differing values would lose one.
                if new[dim_id]["v"] != entry["v"]:
                    collisions.append(f"{entity_id}: {key!r} = {value!r} vs {new[dim_id]['v']!r}")
                    continue
                if entry["src"] == "declared":
                    new[dim_id] = entry
                continue
            new[dim_id] = entry
        if new != dims:
            rewrites.append((entity_id, new))

    if collisions:
        raise RuntimeError(
            "rows hold two names of one dimension with different values; reconcile them before migrating "
            "(nothing is written): " + "; ".join(collisions)
        )
    if undeclared:
        listed = "; ".join(f"{key!r} on {', '.join(sorted(types))}" for key, types in sorted(undeclared.items()))
        raise RuntimeError(
            "dimension keys with no declared Dimension node (seed them in their plugin's or core's "
            f"dimension.grift.json; nothing is minted): {listed}"
        )
    for entity_id, new in rewrites:
        Entity.objects.using(alias).filter(pk=entity_id).update(dimensions=new)


def backwards(apps: Any, schema_editor: Any) -> None:
    """Back to name keys and plain string values. A uuid no seed declares keeps its uuid key. If two
    stored keys of one row would land on one name, the reversal refuses, naming them, before writing."""
    from tap_grid.dimension_names import name_of

    Entity = apps.get_model("tap_grid", "Entity")
    alias = schema_editor.connection.alias
    rows = Entity.objects.using(alias).exclude(dimensions={}).values_list("id", "dimensions")
    rewrites: list[tuple[Any, dict[str, Any]]] = []
    collisions: list[str] = []
    for entity_id, dims in rows.iterator(chunk_size=2000):
        if not isinstance(dims, dict):
            continue
        old: dict[str, Any] = {}
        for key, value in dims.items():
            name = name_of(key) or key
            if name in old:
                collisions.append(f"{entity_id}: {name!r}")
                continue
            old[name] = value.get("v") if isinstance(value, dict) else value
        if old != dims:
            rewrites.append((entity_id, old))
    if collisions:
        # Two stored keys would become one name: a rollback that silently dropped one is lossy.
        raise RuntimeError(
            "cannot reverse 0012: these rows hold two dimension keys that map to one name: " + "; ".join(collisions)
        )
    for entity_id, old in rewrites:
        Entity.objects.using(alias).filter(pk=entity_id).update(dimensions=old)


class Migration(migrations.Migration):
    """Entities reference dimensions by node id, with provenance (req-grid-dimension-reference)."""

    dependencies = [
        ("tap_grid", "0011_dimension_knobs"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
