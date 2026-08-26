# Refactor recipe — extract `grid_fixtures`, make `gryphon_playground` a leaf

Shovel-ready recipe (not authoritative spec). Goal: extract the generic graph-node
vocabulary that currently lives inside `gryphon_playground` into a new, neutral,
non-load-bearing plugin **`grid_fixtures`** (`tap_plugin.grid_fixtures`), so that:

1. **`gryphon_playground` becomes a pure leaf** — nothing outside it imports its
   vocabulary. It keeps the Gridkin corpus + harness and simply *depends on*
   `grid_fixtures`. It can then be dropped from any profile without redding the core
   suites. ("It's literally a playground.")
2. The neutral vocabulary is reusable by the **core `tap_grid`/`tap_api` suites**,
   which today reach for `tap_plugin.lotr` — enabling a later, separable pass that
   frees `lotr` from the critical path too (Phase B, optional).

Versioning is git; do not store dates in the body.

---

## The one locked decision

**Plugin name = `grid_fixtures`** (confirmed by George). Derived identity chain
(all four MUST agree — gate-enforced, `req-tap-plugin-arch-identity`):

| facet | value |
|---|---|
| slug | `grid_fixtures` |
| distribution | `tap-plugin-grid-fixtures` (PEP 503: `_`→`-`, `tap-plugin-` prefix) |
| import namespace | `tap_plugin.grid_fixtures` (PEP 420 native; NO `tap_plugin/__init__.py`) |
| entry-point key | `grid_fixtures` (== slug) |

---

## HARD coordination gate — do not start until this is true

`gryphon_playground` is **being converted to package-mode right now in another
session** (from directory-mode `plugins/gryphon_playground/` + build-baked, to
`tap_plugin.gryphon_playground` like every other plugin). This recipe operates on
the **post-conversion** shape and must NOT re-do the package-mode conversion.

**Before starting, verify on a fresh `main`:**

```bash
git fetch origin && git log --oneline -3 origin/main
# gryphon_playground is package-mode:
test -d plugins/gryphon_playground/tap_plugin/gryphon_playground && echo "PKG-MODE OK"
# it is no longer build-baked / no longer a settings.py INSTALLED_APPS literal:
grep -n "gryphon_playground" tap/settings.py tap/preboot.py   # expect: NOT in INSTALLED_APPS literal, NOT in BUILD_BAKED_PLUGIN_SLUGS
# and it is installed from a profile's install section:
grep -n "gryphon_playground" boot/*.boot.json
```

If any check fails, **stop** — the conversion hasn't landed. Coordinate; do not race
files that are actively churning in the other session.

> Note on paths in this doc: where a path reads `plugins/gryphon_playground/…`, after
> the package-mode conversion the models/apps live under
> `plugins/gryphon_playground/tap_plugin/gryphon_playground/…` (the `lotr` layout).
> Confirm the real layout with `find plugins/gryphon_playground -maxdepth 4 -type f`
> at kickoff and adjust the move source accordingly. The corpus dirs
> (`expected/ scenarios/ fixtures/ gridkin/ edges/`) stay in the plugin root or move
> with it per the conversion — leave them where the conversion put them.

---

## Design: what moves, what stays

**`grid_fixtures` owns ONLY the vocabulary** — nothing else:

- 4 node models: `PgNode`, `PgHub`, `PgLeaf`, `PgCycleNode`
  (`models/pg_node.py`, `pg_hub.py`, `pg_leaf.py`, `pg_cycle_node.py`)
- 4 edge definitions: `PG_LINKS`, `PG_NESTS`, `PG_LOOPS`, `PG_OPTIONAL`
  (`edges/*.edge.json`)
- Its own migrations for those 4 tables.

**`gryphon_playground` keeps** the Gridkin corpus (`expected/` `scenarios/`
`fixtures/`), the harness (`gridkin/` — loader, model_oracle, coverage, fuzz,
metamorphic, findings ledger), its tests, docs, skills — and gains a **declared
dependency on `grid_fixtures`**. The Gridkin TCK still runs at promote (the full
`scripts/test` lane); `grid_fixtures` is not "load-bearing" in the sense that
matters — nothing *outside its consumers* reaches into `gryphon_playground`.

Why split vocabulary from corpus: the vocabulary is what both the core suites and
the playground need; the corpus is playground-only. Keeping the corpus in the
playground is what lets the playground stay optional while the vocabulary it shares
lives one level down.

---

## Surface measurement (real counts, from `session/validation` at doc time)

- **238 files** contain the token `gryphon_playground__` (the entity-type / edge
  namespace). Breakdown: `expected/` 184, `scenarios/` 26, `fixtures/` 16, `models/`
  4, `gridkin/` harness 1, plugin misc 3 — **plus 3 cross-plugin files** (below).
- **Cross-plugin leaks (the load-bearing part):**
  - `tap_grid/tests/test_gryphon.py` — ~40 refs, a **real** core-suite dependency on
    the vocabulary (parses `MATCH (n:gryphon_playground__pg_node) …`).
  - `tap_grid/gryphon/ast_nodes.py`, `tap_grid/gryphon/executor.py` — all refs are
    **docstring example queries** (cosmetic; repoint for doc accuracy, not runtime).
- 4 node models, 4 edge json files, 4 `[models]` + 4 `[edges]` manifest entries.

---

## The mechanical rename (this is the "search and replace a name" core)

Apply these substitutions across the **corpus + harness + the 3 cross-plugin files**
(NOT blindly repo-wide — the `gryphon_playground` *plugin identity* stays):

| find | replace | yields |
|---|---|---|
| `gryphon_playground__pg_` | `grid_fixtures__` | `grid_fixtures__node` / `__hub` / `__leaf` / `__cycle_node` (drops vestigial `pg_` AND swaps namespace in one pass) |
| `__gryphon_playground` (edge namespace suffix) | `__grid_fixtures` | `PG_LINKS__grid_fixtures`, `PG_NESTS__grid_fixtures`, … |
| model import path `…gryphon_playground.models.pg_` | `…grid_fixtures.models.pg_` | `tap_plugin.grid_fixtures.models.pg_node.PgNode` |

Keep unchanged: Python class names (`PgNode` etc. — internal, renaming = pure churn),
edge type *labels* (`PG_LINKS` — only the `__namespace` suffix moves).

Suggested command (scoped, dry-run first):

```bash
# 1) preview the exact file set (corpus + harness + the 3 leak files)
grep -rl "gryphon_playground__" plugins/gryphon_playground tap_grid/tests/test_gryphon.py \
  tap_grid/gryphon/ast_nodes.py tap_grid/gryphon/executor.py

# 2) apply (order matters: pg_ substitution first, then the edge-suffix one)
#    review each hunk; do NOT run against the whole repo.
```

`db_table` values move with the models (they become `grid_fixtures__node`, etc.);
because the tables move to a new app this is a fresh migration in `grid_fixtures`,
not an `AlterModelTable` — see step 5. No production data exists on these fixture
tables, so no data migration is required (note this in the migration if desired).

---

## Phase A — free `gryphon_playground` (the primary goal)

1. **Scaffold `plugins/grid_fixtures/`** mirroring the `lotr` package-mode layout:
   - `pyproject.toml` (copy `plugins/lotr/pyproject.toml`; set name
     `tap-plugin-grid-fixtures`, description, `dependencies = []`, entry point
     `grid_fixtures = "tap_plugin.grid_fixtures.apps:GridFixturesConfig"`,
     `only-include = ["tap_plugin/grid_fixtures"]`, keep the monorepo `root = "../.."`
     + `fallback_version` transition artifact).
   - `plugins/grid_fixtures/__init__.py` (empty).
   - `plugins/grid_fixtures/tap_plugin/grid_fixtures/__init__.py`, `apps.py`
     (`class GridFixturesConfig(TapPluginConfig): pass`).
   - `tap_plugin/grid_fixtures/tap-plugin.toml` — slug `grid_fixtures`, `[models]`
     with the 4 `grid_fixtures__*` entries pointing at the moved model paths,
     `[edges]` with the 4 `*__grid_fixtures` edge files. (No `[grift]` unless you want
     seed data — the core suites create fixtures via the service layer, so a grift
     seed is optional; add one only if a profile needs pre-seeded fixture nodes.)
   - `NO tap_plugin/__init__.py` anywhere (PEP 420 namespace — same as lotr).

2. **Move the 4 models** from `gryphon_playground` → `grid_fixtures`
   (`git mv` the 4 `models/pg_*.py` + the `edges/PG_*.edge.json`). Apply the rename
   table to their `ENTITY_TYPE`, `db_table`, and edge namespaces. Delete the moved
   entries from `gryphon_playground`'s `tap-plugin.toml` `[models]`/`[edges]`.

3. **Declare the dependency.** `gryphon_playground` now depends on `grid_fixtures`.
   Follow the plugin-dependency convention as implemented at the time
   (`req-tap-plugin-arch-dependencies` — Tier-0/1/2 declare-now-resolver-deferred). At
   minimum: add `grid_fixtures` to `gryphon_playground`'s pyproject `dependencies`
   (distribution `tap-plugin-grid-fixtures`) and/or its tap-plugin.toml dependency
   declaration; ensure `grid_fixtures` installs **before** `gryphon_playground` in
   every profile that installs the playground (install order = dependency order, as
   samsite already does with roscale/sigstore_core).

4. **Apply the rename** across the corpus + harness + `test_gryphon.py` + the two
   engine docstrings (the mechanical section above).

5. **Migrations.** `makemigrations grid_fixtures` (creates the 4 fixture tables under
   the new app) and `makemigrations gryphon_playground` (drops the 4 moved tables /
   reflects the removed models). Run in the container. Verify
   `manage.py makemigrations --check` is clean afterward.

6. **Profiles.** Add `grid_fixtures` to the `install` section of every profile that
   installs `gryphon_playground` (dev/full profile — and `base`, since the population
   seeds it if you add a grift seed), listed **before** `gryphon_playground`. Because
   `test_gryphon.py` (a core suite) now imports `grid_fixtures`, it must be
   editable-installed in the **test venv** — i.e. `grid_fixtures` belongs in the
   base/dev install set the same way `lotr` does today (`base.boot.json` calls lotr
   "load-bearing test-fixture vocabulary the core suites import"). `grid_fixtures`
   inherits exactly that role; `gryphon_playground` sheds it.

7. **Verify.** In the container, rebuilt image:
   - `manage.py makemigrations --check` clean.
   - Preboot coherence passes for every shipped profile (`base`, `operator_sso`,
     `samsite`, dev) — the 2026-07-02 `base`-break class.
   - Full suite green: `scripts/test` (includes the Gridkin lane). Expect the Gridkin
     corpus (201-ish scenarios) + `tap_grid/tests/test_gryphon.py` to pass against the
     new `grid_fixtures__*` types.
   - `scripts/test --fast` still green (it `--ignore`s `plugins/gryphon_playground` —
     confirm nothing core now hard-imports the playground at collection time; if it
     does, that's a residual leak to fix).

**Done-test for Phase A:** removing `gryphon_playground` from a profile's install (and
from the test venv) leaves the **core** suites green — only the Gridkin lane drops.
Nothing under `tap_grid/`, `tap_api/`, `tap_web/`, `tap_viz/` imports
`tap_plugin.gryphon_playground` or references `gryphon_playground__*`.

---

## Phase B — free `lotr` (OPTIONAL, separable, do only if Phase A is green)

Goal: `lotr` never on the critical path. Migrate the core suites' fixture vocabulary
from `lotr`'s `Character` to `grid_fixtures`' node types, then drop `lotr` from the
default install.

- **~19 core-test files** import `tap_plugin.lotr` as a fixture (measured):
  `tap_api/tests/{test_edges,test_searches}.py`,
  `tap_grid/tests/{test_batch_integration,test_dimensions,test_flip,test_grift,`
  `test_grift_subgraph,test_gryphon,test_history,test_icon,test_models,test_occ,`
  `test_purge,test_search_module,test_search_orm,test_service_schemas,test_services,`
  `test_validation}.py`, `tap_viz/tests/test_models.py`,
  `tap_web/tests/{test_synthetic,test_table_panel,test_views}.py`,
  `tap/tests/test_flaws.py`.
  Map `Character`→`PgNode` (`grid_fixtures__node`), field `bio`→`description`,
  entity type `"character"`→`"grid_fixtures__node"`. `PgNode` is a strict superset of
  `Character` for test purposes (all scalar types + JSON `tags` + history + arbitrary
  topology), so the migration is field-for-field.
- Then drop the `lotr` `install` + `seed-plugin` entries from `base.boot.json` (leave
  it available for a profile that wants the Middle-earth demo vocabulary).

**Named residual — FULL `lotr` removal is blocked** (out of scope for this pass;
record, don't fix): `lotr` is referenced in **non-test** code —
`tap_grid/icon.py`, `tap_web/models.py`, and `tap_web/migrations/0001_initial.py`
(baked into a migration). Plus the plugin-validation tooling
(`tap_plugins/validate_plugin/*`, `import_plugin_grift`) uses `lotr` as its example
target. Retiring `lotr` entirely means repointing those and is a separate job. Phase
B only makes `lotr` *non-critical-path for the test suites*, matching George's
"disentangle so it's never critical path" over "delete it."

---

## Named open edges / residuals

- **Docstring drift:** the two engine files (`ast_nodes.py`, `executor.py`) carry
  example queries in `gryphon_playground__pg_node` vocabulary. Repointing them to
  `grid_fixtures__node` is cosmetic but keeps docs honest; a doc-drift check could
  otherwise flag them.
- **`--fast` lane collection:** `scripts/test --fast` `--ignore`s the playground; if
  any core test still imports the playground module at collection, `--fast` will
  either miss coverage or error. Phase A step 7 must confirm the playground is fully
  leaf.
- **db_table move on a live instance:** these are test/dev fixture tables; a real
  instance carrying `gryphon_playground__pg_*` data would need a data migration. None
  exists today — note it in the migration.
- **Validation Map:** add/adjust rows if the extraction changes which suite owns the
  Gridkin lane (`spec-dev-validation.md` is the center of gravity — a new validation
  surface requires a Map row in the same change).

---

## Pre-promote checklist

- [ ] Started from a `main` where the `gryphon_playground` package-mode conversion has
      landed (the HARD gate).
- [ ] `grid_fixtures` scaffolded, 4 models + 4 edges moved, dependency declared.
- [ ] Rename applied to corpus + harness + `test_gryphon.py` + engine docstrings.
- [ ] `makemigrations --check` clean; preboot coherence passes for all shipped profiles.
- [ ] `scripts/test` (full, incl. Gridkin) green; `scripts/test --fast` green.
- [ ] Image rebuilt + preboot verified before promote (the 2026-07-02 lesson).
- [ ] (If Phase B done) core suites green with `lotr` dropped from `base` install.
- [ ] Promote via `scripts/promote-to-main.sh` (atomic dual-refspec push).
