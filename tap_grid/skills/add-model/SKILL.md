---
name: add-model
description: Add a new TAP-managed BaseModel to an existing plugin or app. Use when extending an existing plugin or app with a new entity type (e.g. adding Evidence to fedramp_20x_ksi).
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(scripts/uuid7 *) Bash(grep *) Bash(find *) Bash(ls *) Bash(mkdir *) Glob Grep
argument-hint: <plugin_or_app_slug> <model_class_name>
---

# Add a New BaseModel

You are adding a new TAP-managed entity type to an existing plugin or app. The model becomes a typed BaseModel subclass, gets an Entity-spine row per instance, and is reachable through the service layer, GRIFT, and the edge system.

## Authoritative Sources (read these first; do not guess from memory)

- **[`tap_grid/specs/spec-grid-entity.md`](../../specs/spec-grid-entity.md)** — BaseModel contract, dual schema requirement, dimensions, display metadata, validation hooks. This is canonical; everything below is operational summary.
- **[`tap_grid/specs/spec-grid-node.md`](../../specs/spec-grid-node.md)** — node display projection (Entity.name as subordinate of model name), revision counter, tombstone delete.
- **[`tap_grid/specs/spec-grid-icon.md`](../../specs/spec-grid-icon.md)** — icon key format, SVG requirements.
- **[`tap_grid/specs/spec-grid-history.md`](../../specs/spec-grid-history.md)** — django-simple-history is on BaseModel; concrete subclasses get history tables automatically.
- **[`tap_grid/specs/spec-grid-hotlink.md`](../../specs/spec-grid-hotlink.md)** — read this if your model carries references to other entities inside a JSON field.
- **[`tap_plugins/specs/spec-tap-plugin-manifest-v0.md`](../../../tap_plugins/specs/spec-tap-plugin-manifest-v0.md)** — manifest registration (where the model gets wired in).

If a spec contradicts a pattern in code, flag it to the user — do not silently work around it.

## Step 1: Confirm the Shape With the User

Before writing code, gather:

1. **Plugin or app slug** (e.g. `fedramp_20x_ksi`, `tap_grid`).
2. **Model class name** (PascalCase) and **`ENTITY_TYPE` slug** (snake_case). These usually match. If not, justify.
3. **Display metadata**: `ENTITY_NAME` (human-readable), `ENTITY_DESCRIPTION` (1-2 sentences), `ENTITY_ICON` (kebab-case key).
4. **Dimensions** — what `DEFAULT_DIMENSIONS` should new instances carry? Dimension-less BaseModels are a design red flag; require justification before allowing one.
5. **Fields** — name, type, defaults, required-on-create. For each non-trivial field, confirm whether it appears in `FIELD_CRUD_SCHEMA`, `FIELD_VALIDATION_SCHEMA`, or both, and what JSON Schema it validates against.
5a. **Who else already holds each fact?** For every field, ask whether some other node type on the grid already carries that exact value. Search by fact, not by type or field name — `aws_iam_oidc_provider.url` and `oidc_issuer.issuer_url` are the same string under different names, in different plugins, with nothing keeping them consistent. If a substrate (`*_core`) already holds the fact, **traverse to it instead of copying it**; if a genuine boundary forces the duplicate, tag every site `TAP-KNOWN-DUPE(<group-id>)` and add the group row to `specs/spec-tap-known-dupes.md` in the same change. The [`build-domain-vocabulary`](../build-domain-vocabulary/SKILL.md) skill's Step 1 has the search commands.
6. **`get_name()` strategy** — what's the canonical display name expression? (Entity.name is auto-synced from this; see `req-grid-node-display`.)
7. **Hotlink-bearing JSON fields** — does any field hold IDs that should map to graph edges? If yes, plan the `HOTLINKS` declaration alongside the field. Any edge you introduce here MUST follow the edge-naming discipline in the [`add-edge`](../add-edge/SKILL.md) skill: name the specific mechanical relationship, never a bare/philosophical verb (`PROTECTS`, `DEPENDS_ON`) and never a generic containment/`CONTAINS` edge that conflates several relationships — one edge, one relationship.
8. **Identity — how is one of these found again?** (`req-grid-entity-natural-key`.) Either the constituting properties, `NATURAL_KEY = ("<field>", …)` — the source's *stable* identifiers first (a numeric id, an ARN, an oid); a name only where the source offers nothing better; never a dimension value, never a timestamp — or `NATURAL_KEY = KEYLESS` with a one-sentence `NATURAL_KEY_REASON` for a type that observes no source object (a run, a fire, a registration). Leaving it undeclared fails `test_no_core_type_is_undeclared`; "keyless by default" is not a state.
9. **Containment — does this node contain children that must retire with it?** `CONTAINMENT_EDGES = ("<EDGE_TYPE>", …)` names the edge types cascade follows (`req-grid-service-delete-cascade`); every one must also appear in `OUTBOUND_EDGES`, which stays the permission declaration and carries no delete semantics. Undeclared means reference: never followed. Work the **delete tree** out explicitly before writing the tuple — see "Designing the delete tree" below.

Write down the agreed shape before generating code; it becomes the spec section in Step 6.

### Designing the delete tree

`delete_node(x, cascade="contained")` retires `x` and then walks **only** the edge types each model lists in `CONTAINMENT_EDGES`, breadth-first, retiring every live far node it reaches and ending every edge incident to a retired node. The declaration is per model: a child type contains its own children only if *it* declares so. Draw the tree before you declare it — one line per edge type — and ask, for each outgoing edge type:

- **Does the far node exist only as a part of this one?** A workflow's jobs, a repository's rulesets, a forum's posts: ending the parent ends them. That is containment. A repository's *owner*, a job's *runner*, a post's *author*: they exist on their own and other things point at them. That is a reference — the edge ends when the near node retires (the endpoint rule), the far node stays.
- **Could the far node have a second live parent?** A node with two containing parents retires with the **first** parent that cascades (`req-grid-service-delete-cascade`, ruled). If that would be wrong — a shared account reached from two repositories must not retire because one repository disappears — it is not containment, whatever the edge is called. Shared things stay off `CONTAINMENT_EDGES`.
- **Does the chain stop where you think it stops?** Containment is followed only through types that declare it. If `repository` contains `workflow` and `workflow` declares nothing, a cascade from the repository retires the workflow and *stops*: the workflow's jobs stay live with their edges ended by the endpoint rule. Declare each level, or accept the stop on purpose.
- **Is the edge type spelled exactly as its definition?** `CONTAINMENT_EDGES` must be a subset of `OUTBOUND_EDGES` (guarded at class creation), and every slug in both must resolve to a defined edge — a `.edge.json` in this plugin's manifest, a declared dependency's, or a core edge. A renamed definition leaves both declarations reading as valid while the cascade follows an edge nothing will ever carry; the boot-time check `tap_grid.E004` refuses the stack and `validate_plugin`'s `edge-declarations` check fails the plugin, so run the validator after any edge rename (Issue# 583 - tap).
- **Does identity depend on a fact the model does not carry?** A cascade is only as good as the
  node it starts from being the node you meant. If the natural key rests on something computed
  in a collector's id recipe — a host, a case fold, a normalized form — the generated search
  cannot filter it and a second spelling mints a second node behind an unchanged edge, which
  strands a row where nothing will look for it. **Put the fact in a column and key on the
  column.** Ruled by George 2026-09-20 on `tap-plugin-github-core#164` and `#165`, which were
  exactly this twice: a platform host that lived only in the id, and a secret name the recipe
  upper-cased while the stored field kept GitHub's spelling. Adding a column is cheap; if it
  buys precision at the cost of a little more data it is worth it. Keep the reported value
  beside the canonical one when they differ — what was reported and what the thing IS are two
  facts, and only one of them is identity. A node's DIMENSIONS are not an escape hatch here:
  the generated search ignores them on purpose, because dimension values vary by collection
  path, so a dimension filter would fail to find a row's own previous write
  (`req-grid-entity-natural-key-10`).
- **How big can the closure get?** One contained cascade may discover at most `TAP_CASCADE_MAX_CLOSURE` nodes (default 5000), root included, shared children counted once; over the cap the whole cascade is refused and nothing is written. A type whose subtree can exceed that is a design question, not a settings question.

The cascade confirmation corpus (`tap_grid/cascade_corpus/`, `spec-grid-cascade-corpus.md`) holds seventy-odd worked examples — chains, diamonds, cycles, references at each depth, blocked branches, undeclared levels — with the exact retired sets each produces. When a declaration is not obvious, find the scenario that matches your shape and read its `note`.

## Step 2: Create the Model File

Create `<plugin_or_app>/models/<model_slug>.py`. Required class members (see `spec-grid-entity.md` for the full contract):

```python
"""<Model> — <one-line description>."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class <Model>(BaseModel):
    """<Docstring: what the model represents and why it's distinct from siblings.>

    Spec: <plugin>/specs/<spec-name>.md
    """

    ENTITY_TYPE: ClassVar[str] = "<slug>"
    ENTITY_NAME: ClassVar[str] = "<Display Name>"
    ENTITY_DESCRIPTION: ClassVar[str] = "<1-2 sentence description>"
    ENTITY_ICON: ClassVar[str] = "<kebab-case-icon-key>"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"<key>": "<value>"}

    # Identity: how one of these is found again (req-grid-entity-natural-key).
    # Stable source identifiers first; or KEYLESS + NATURAL_KEY_REASON for a type
    # that observes no source object. Undeclared fails the guard.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("<stable_id_field>",)

    # Containment: edge types whose far nodes retire with this one
    # (req-grid-service-delete-cascade). Must be a subset of OUTBOUND_EDGES.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ()

    # FIELD_CRUD_SCHEMA: what the API accepts on create/update.
    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        # ...
    }

    # FIELD_VALIDATION_SCHEMA: what the model validates before save.
    # Often duplicates CRUD_SCHEMA; can be stricter (e.g. enums, regex).
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        # ...
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    # Optional: HOTLINKS for JSON fields that reference other entities.
    # See spec-grid-hotlink.md.
    # HOTLINKS: ClassVar[list[dict]] = [...]

    name = models.CharField(max_length=255, blank=True, default="")
    # ... other fields ...

    class Meta(BaseModel.Meta):
        db_table = "<table_name>"

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.get_name()
```

### Field gotchas

- **Reserved names**: `instance_type` is reserved by django-simple-history. Other Django/HistoricalRecords reserved names: `history`, `history_user`, `history_date`, `history_change_reason`, `history_type`. Avoid them.
- **Nullable fields**: prefer `blank=True, default=""` for strings, `null=True` for nullable foreign keys / numbers. The dual schema must reflect nullability; see `spec-grid-entity.md` § "Nullable field handling."
- **Indexes**: add `db_index=True` on fields you'll filter by; Django creates the index in the migration automatically.
- **JSON fields**: use `JSONField(default=dict, blank=True)` and validate with a `jsonschema` entry in `FIELD_VALIDATION_SCHEMA`.

### `get_name()` is the source of truth

Per `req-grid-node-display`, `Entity.name` is a subordinate projection of `get_name()` and gets re-synced on every save. Don't store a separate canonical-display name; derive it from your fields in `get_name()`.

If the model has a `name` field, it must explicitly override `get_name()` (usually `return self.name or ""`). Do not rely on `__str__()` or the presence of a `name` field; inherited `BaseModel.get_name()` returns `""`, and the save pipeline will project that empty value onto `Entity.name`.

## Step 3: Re-export From `models/__init__.py`

Add the model to the package's re-export so `from <plugin>.models import <Model>` works:

```python
from .<model_slug> import <Model>

__all__ = [
    # ...existing exports...
    "<Model>",
]
```

## Step 4: Register in the Plugin Manifest

Edit `<plugin>/tap-plugin.toml`. Under `[models]`, add the dotted path:

```toml
[models]
<entity_slug> = "<plugin_dotted_path>.models.<model_slug>.<Model>"
```

The `entity_slug` key on the left **must** equal the model's `ENTITY_TYPE`. Any mismatch surfaces as a manifest validation error.

For first-party apps (e.g. `tap_grid`, `tap_viz`), models are typically auto-registered via the registry; check existing app conventions before adding manifest entries.

## Step 5: Make and Apply Migrations

```bash
scripts/dc exec web uv run python manage.py makemigrations <plugin_or_app>
scripts/dc exec web uv run python manage.py migrate
```

Review the generated migration before applying. Confirm:

- The `<entity_slug>` table is created.
- A `historical<entity_slug>` table is created (django-simple-history).
- Indexes match what your `db_index=True` fields requested.

## Step 6: Update or Add the Spec

Specs are authoritative. Either:

- Add a new requirement to an existing plugin spec (e.g. a new section in `spec-<plugin>-v0.md` or a sibling `spec-<plugin>-<model>.md`), OR
- Author a fresh spec file if the model introduces a new domain concept.

The requirement should:

- Have a stable RID (`req-<plugin>-<model>`).
- List ACIDs covering field schema, dimensions, display metadata, history, and any model-specific invariants.
- Set Status: `In Development` while you build, then flip to `Implemented` after Step 9 passes.

If the model affects existing requirements (changes a behavior, deprecates a field), update those requirements' Status and notes — spec drift is a bug.

## Step 7: Add an Icon (if `ENTITY_ICON` is set)

Drop the SVG at `<plugin>/static/<plugin>/icons/<icon-key>.svg`. Read [`spec-grid-icon.md`](../../specs/spec-grid-icon.md) for size, viewBox, and color requirements (TAP convention is `currentColor`; vendor brand colors require explicit justification).

If an existing icon fits, the new model can share an icon key — that's acceptable and idiomatic.

**AWS service models (`aws_core`):** do not hand-author the SVG. Run the `get-aws-icons` skill (`plugins/aws_core/skills/get-aws-icons/`) for the model's `ENTITY_ICON` key — it sources the official AWS Architecture icon (downloaded on demand to tmp, never committed) and installs it normalized to the existing 80×80 branded `aws_core` convention. The "vendor brand colors require explicit justification" clause above is satisfied for AWS service icons by recognizability plus consistency with their 30+ peers; the icon-spec's 24×24/`currentColor` line is a known, separate drift.

## Step 8: Tests

Add tests that exercise behavior, not implementation. Minimum coverage:

- **Create-via-service-layer**: the model can be created through `create_node()` with valid input.
- **Validation**: required fields are enforced; field schemas reject invalid input.
- **Display projection**: `Entity.name` is set correctly after create and re-synced after save (per `req-grid-node-display`).
- **Dimensions**: `DEFAULT_DIMENSIONS` is applied to new instances.

Place tests in `<plugin>/tests/test_<model_slug>.py`. Use the service layer for setup; reach for direct ORM only when intentionally testing model-level behavior (per CLAUDE.md "Testing Framework").

## Step 9: Verify and Sync

```bash
# Run the new model's tests.
scripts/dc exec web uv run pytest <plugin>/tests/test_<model_slug>.py -v

# Run the plugin's full test suite.
scripts/dc exec web uv run pytest <plugin>/tests/ -v

# Type-check and lint.
scripts/dc exec web uv run mypy <plugin>/
scripts/dc exec web uv run ruff check <plugin>/
```

Once green:

- Flip the spec requirement Status from `In Development` → `Implemented`.
- Update the spec's requirement-status table at the top of the file to match.
- If docs reference any RIDs you changed, follow the doc-spec sync rules in [`specs/spec-docs.md`](../../../specs/spec-docs.md).

## Common Mistakes (do not commit any of these)

- **Skipping the spec.** Per CLAUDE.md feedback, new components must be driven by a spec. If none exists, draft one before coding.
- **Using direct ORM writes in tests** for service-layer behavior. Use the service layer; reserve ORM-only tests for explicitly model-level behavior.
- **Forgetting `Meta(BaseModel.Meta)`.** Without it, you'll lose the inherited `abstract = False` / db conventions.
- **Adding `HistoricalRecords` directly to the new model.** Don't — it's already on the abstract `BaseModel` (`inherit=True`); concrete subclasses get history tables automatically.
- **Leaving `NATURAL_KEY` undeclared, or declaring it from a name, a dimension value or a timestamp.** Undeclared fails the guard; a name-keyed type churns on rename; a dimension value is a collection-path artefact; a timestamp is never identity. `KEYLESS` with a reason is the honest declaration for a type that observes no source thing.
- **Putting cascade semantics on `OUTBOUND_EDGES`.** That declaration is edge *permission*. Containment is `CONTAINMENT_EDGES`, a dedicated tuple; a guard fails if it names an edge `OUTBOUND_EDGES` does not permit.
- **Storing a denormalized display-name field.** Use `get_name()` and let the BaseModel save pipeline keep `Entity.name` in sync.
- **Re-modelling a concept a substrate already owns.** A vendor-side record and a neutral thing are two nodes linked by an edge, not one node doing both jobs and not two nodes each holding the same fact. The settled pattern: `github_core__github_repository` (settings/hosting facts) `HOSTS_REPOSITORY` → `git_core__git_repository` (the neutral thing) — the type is neutral, the key is per-observer, and each shared fact lives on exactly one side.
- **A field that restates another field on the same model.** `name` set to the same value as `full_name`, or `default_branch` beside a `default_ref` that is the same fact with a prefix. Derive one from the other, or drop one — two writable copies drift the first time only one of them is updated.
- **Writing migrations that mix data and schema changes.** Keep them separate; data migrations get their own file.
