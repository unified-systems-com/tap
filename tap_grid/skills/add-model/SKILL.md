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
6. **`get_name()` strategy** — what's the canonical display name expression? (Entity.name is auto-synced from this; see `req-grid-node-display`.)
7. **Hotlink-bearing JSON fields** — does any field hold IDs that should map to graph edges? If yes, plan the `HOTLINKS` declaration alongside the field. Any edge you introduce here MUST follow the edge-naming discipline in the [`add-edge`](../add-edge/SKILL.md) skill: name the specific mechanical relationship, never a bare/philosophical verb (`PROTECTS`, `DEPENDS_ON`) and never a generic containment/`CONTAINS` edge that conflates several relationships — one edge, one relationship.

Write down the agreed shape before generating code; it becomes the spec section in Step 6.

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
- **Storing a denormalized display-name field.** Use `get_name()` and let the BaseModel save pipeline keep `Entity.name` in sync.
- **Writing migrations that mix data and schema changes.** Keep them separate; data migrations get their own file.
