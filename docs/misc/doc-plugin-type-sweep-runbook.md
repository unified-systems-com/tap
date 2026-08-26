---
title: Plugin Type-Ownership Rename Sweep — Runbook & Rename Map
spec: tap_plugins/specs/spec-tap-plugin-type-ownership-v0.md
audience:
  - llm
  - developer
status: executed
---

# Plugin Type-Ownership Rename Sweep — Runbook & Rename Map

> **EXECUTED 2026-07-02.** The sweep landed: all 6 producer plugins + `samsite`
> cross-refs renamed to `<slug>__<name>` (node) / `<NAME>__<slug>` (edge), table
> renames migrated, `req-tap-plugin-type-node-prefix` / `-edge-suffix` /
> `-collision-loud` marked Implemented, and the fail-CI affix guard
> (`tap_plugins.guards.type_ownership`) added. Beyond the map below, execution
> surfaced reference classes the prep under-counted: edge-JSON `sources`/`targets`
> endpoint arrays; collector-manifest `source_entity_type`/`target_entity_type`
> keys; cross-*producer* refs (github→aws), not just samsite; core-test refs
> (`tap_grid`/`tap_api` gryphon + observation tests use `computing_core__network_interface`
> / `lotr__character`); constraint-test error-message substrings; gridkin SQL-snapshot
> oracles; the collector-manifest slug schema `pattern`; and a `by_entity_type`
> dict-key assertion. **Not** renamed (a separate namespace): dimension VALUES —
> the `compliance` dimension keeps the bare `"boundary"`. The runbook below is
> retained as the historical rename map.

Prep for the deferred `<slug>__<name>` / `<NAME>__<slug>` sweep
(`spec-tap-plugin-type-ownership-v0`, `req-tap-plugin-type-node-prefix` / `-edge-suffix`, both `Proposed`).
Staged now so the sweep is *execution, not design* when it runs. **Run it last-session-standing**
— its body is a wide string-reference rewrite that collides catastrophically with any concurrent
edit to tests/fixtures/GRIFT/queries.

## What this is (and isn't)

- **Is:** a wide, shallow rewrite — plugin node/edge *type values* → their `<slug>__`/`__<slug>` form,
  the backing table renames, and the same substitution in every *string reference* (test corpora,
  GRIFT/fixture/expected JSON, Gryphon query strings, cross-plugin edge endpoints, docs). Per the
  spec, string references are the *dominant* cost, not the model files.
- **Is not** a data migration. *"No data migration semantics beyond table renames; dev resets
  freely."* Table renames are auto-generated Django migrations; the DB is reset in dev.
- **Is safe if validated.** A renamed type with a stale reference **fails loudly** in the suite
  (gridkin corpus, model oracle, gryphon suite, plugin tests). The full-suite gate turns "touched
  everything" into "proved everything."

## Target rules

- **Node types + tables:** `<slug>__<name>` (`req-tap-plugin-type-node-prefix`).
- **Edge types:** `<NAME>__<slug>` (`req-tap-plugin-type-edge-suffix`).
- **Delimiter is `__`** (locked 2026-06-26). Core/platform types stay **bare** —
  `entity, edge, batch, keystone, dimension, search` + core edges — and plugins must not use them.
- **Convergence:** post-sweep, `ENTITY_TYPE == db_table == <slug>__<name>` for every plugin type.
  They diverge today (see `computing_core`/`lotr` below).
- **Verbose-explicit is accepted** (`req-tap-plugin-type-verbose-doctrine`) — long qualified names over
  a resolution layer.

## Scope

| Plugin | Node types | Edge types | Action |
| --- | ---: | ---: | --- |
| `grid_fixtures` | 4 | 4 | **Done** (proof lineage — `a40419ee` on `gryphon_playground`, inherited on extraction). |
| `aws_core` | 41 | 23 | Sweep — uniform `aws_` prefix, clean. |
| `github_core` | 9 | 10 | Sweep — uniform `github_` prefix. |
| `computing_core` | 11 | 10 | Sweep — **bare `ENTITY_TYPE`s** (highest generic-collision risk). |
| `lotr` | 9 | 12 | Sweep — bare `ENTITY_TYPE`, prefixed table (diverged). **`plugin-untangle` fully landed** (`origin/main` `19409711`): core suites migrated off lotr onto `grid_fixtures`, last residual severed (`d7a0b032`), lotr now install-only → **zero core ripple**; a clean per-plugin rename like the others. |
| `fedramp_20x_ksi` | 14 | 13 | Sweep — multi-prefix + bare types, all verbatim-prepended (no strip). |
| `sigstore_core` | 2 | 5 | Sweep — two prefixes (`sigstore_`, `rekor_`). |
| `administrivia`, `genericom`, `roscale`, `samsite` | 0 | 0 | No types. **But `samsite` *consumes* others' types by string** → update refs (see Ripple). |

## Ratified rule (decisions closed 2026-07-02)

**One rule, no exceptions: verbatim prepend.** Every plugin type becomes `<slug>__<current_name>`
with the existing name kept *unchanged* — no prefix stripping anywhere. Edges become
`<NAME>__<slug>`.

This is what all three ratified decisions reduce to:

1. **Prefix policy → KEEP the full name** (not strip). `aws_account` → `aws_core__aws_account`,
   `github_repository` → `github_core__github_repository`. Redundant-looking but collision-proof and
   preserves the exact current token verbatim; matches the *verbose-explicit accepted* doctrine
   (`req-tap-plugin-type-verbose-doctrine`).
2. **`sigstore_core` two prefixes → KEEP.** `sigstore_ca` → `sigstore_core__sigstore_ca`,
   `rekor_log_entry` → `sigstore_core__rekor_log_entry` (the `rekor_` vendor distinction survives).
3. **`fedramp_20x_ksi` bare types → all fedramp-owned, prepend.** `evidence` →
   `fedramp_20x_ksi__evidence`, `finding` → `fedramp_20x_ksi__finding`, etc. None promoted to core.

Consequences of the uniform rule:
- **`computing_core` bare `ENTITY_TYPE`s** (`user`, `file`, `program`, …) simply prepend →
   `computing_core__user`; nothing to strip (the exact collision case the spec cites, now namespaced).
- **The one historical exception is `grid_fixtures`**, already landed on the *stripped* form
   (`pg_node` → `grid_fixtures__node`, not `…__pg_node`) via the proof lineage `a40419ee`. It is
   promoted and stays as-is; the fleet policy going forward is keep/verbatim-prepend. New plugins
   follow the keep rule.

## Rename map

### `aws_core` — verbatim prepend `aws_core__`
`aws_account → aws_core__aws_account`, `aws_ec2_instance → aws_core__aws_ec2_instance`,
`aws_iam_role → aws_core__aws_iam_role`, … (all 41 mechanically; `ENTITY_TYPE == db_table` already, so
one substitution covers both). Edges: `<NAME> → <NAME>__aws_core` (`CONTAINS → CONTAINS__aws_core`,
`PROTECTS → PROTECTS__aws_core`, …).

### `github_core` — verbatim prepend `github_core__`
`github_repository → github_core__github_repository`,
`github_actions_run → github_core__github_actions_run`, …
`oidc_issuer` (no `github_` prefix) → `github_core__oidc_issuer`. Edges → `<NAME>__github_core`.

### `computing_core` — bare `ENTITY_TYPE`, prepend `computing_core__` (HIGH RISK)
`ENTITY_TYPE` is **bare** (`user`, `file`, `program`, `port`, `ip_address`, `network_interface`,
`tcp_connection`, `public_key`, `private_key`, `web_host`, `web_document`) while `db_table` is
`computing_*`. Both converge → `computing_core__user`, `computing_core__file`, … Edges → `<NAME>__computing_core`.

### `lotr` — bare `ENTITY_TYPE`, `lotr_` table; converge to `lotr__`
`ENTITY_TYPE` bare (`character`, `realm`, `race`, `faction`, `location`, `citadel`, `artifact`,
`sentinel`, `wanderer`), `db_table` `lotr_character`. Both → `lotr__character`, … Edges → `<NAME>__lotr`.
**Ripple now minimal — core fully severed.** `plugin-untangle` landed (`origin/main` `19409711`,
merge `70c500c4`) and moved lotr's fixture role onto `grid_fixtures`: core suites no longer create
lotr types (`_make_wanderer` returns `grid_fixtures__unconstrained`), and its follow-up `d7a0b032`
("sever the last load-bearing lotr dependencies") migrated the final residual — the
`test_table_panel` icon-enrichment test and the `tap_viz` / `test_flaws` / `test_models` illustrative
refs. Verified zero `get_app_config("lotr")` / `/static/lotr/` references remain in `tap_web`/`tap_grid`
core tests. So lotr's sweep is now **purely its own** files — model `ENTITY_TYPE`/`db_table`, edge
JSON, manifest, and `plugins/lotr/tests/*` — with no core ripple. It's a clean per-plugin rename like
the others, no longer a special case.

### `fedramp_20x_ksi` — KEEP names, prepend `fedramp_20x_ksi__` (do NOT strip)
Multi-prefix + bare, and stripping collides (`vdr_finding`→`finding` == bare `finding`). So prepend
the whole current name: `compliance_artifact → fedramp_20x_ksi__compliance_artifact`,
`ksi_signal → fedramp_20x_ksi__ksi_signal`, `vdr_finding → fedramp_20x_ksi__vdr_finding`,
`finding → fedramp_20x_ksi__finding`, `evidence → fedramp_20x_ksi__evidence`, … Edges → `<NAME>__fedramp_20x_ksi`.

### `sigstore_core` — verbatim prepend `sigstore_core__` (ratified: keep)
Two prefixes, both kept: `sigstore_ca → sigstore_core__sigstore_ca`,
`rekor_log_entry → sigstore_core__rekor_log_entry`. Edges → `<NAME>__sigstore_core`.

## Collision hotspots (why the sweep matters, not just tidiness)

| Bare identifier | Owned by | Today | After |
| --- | --- | --- | --- |
| `CONTAINS` (edge) | `aws_core` **and** `lotr` | **collide** — same edge type on the grid | `CONTAINS__aws_core` / `CONTAINS__lotr` |
| `PROTECTS` (edge) | `aws_core` **and** `lotr` | **collide** | `PROTECTS__aws_core` / `PROTECTS__lotr` |
| `user`, `file`, `program`, `port` (node) | `computing_core` (bare) | one slug-rename away from colliding with any plugin's `user` | `computing_core__*` |
| `finding`, `evidence` (node) | `fedramp_20x_ksi` (bare) | squat core-ish namespace | `fedramp_20x_ksi__*` |

## Cross-plugin reference ripple

The sweep is **not** cleanly per-plugin: `samsite` (grift-only) consumes `aws_core` / `github_core` /
`sigstore_core` / `roscale` node + edge types **by string** in its GRIFT/fixtures. Renaming those
producers requires updating `samsite`'s references **in the same atomic sweep**. Same for any
cross-plugin edge endpoint and any core-suite reference. `grid_fixtures` consumers (`gryphon_playground`
corpus, `tap_grid/tests/test_gryphon.py`) are already on the new names.

## Context-aware rewrite (NOT a blind sed)

The same token means different things; rewrite **only**:
- `ENTITY_TYPE` / edge `slug` **values**, `db_table` values, `tap-plugin.toml` type/edge keys
- edge-endpoint type references, GRIFT/fixture/expected `type` fields, Gryphon query strings, data
Leave **untouched**: Python module paths + filenames (`models/pg_node.py`), class names (`PgNode`),
and the `db_table` single→double-underscore is a *delimiter* change, not a slug re-prepend.

## Runbook (last session standing)

1. **Confirm you're solo** — `plugin-untangle` **already landed** (`origin/main` `3ada9642`); the remaining gate is `validation-creation` closed/promoted. Then merge fresh `origin/main` into this session and confirm it's synced.
2. **Decisions already ratified** (2026-07-02, above): verbatim prepend `<slug>__<name>` everywhere, no strip. No ratification step remains — apply the map as written.
3. **Per producer plugin, in order** (leaves → `samsite`-consumed → `lotr` last): apply the map to model files (`ENTITY_TYPE` + `Meta.db_table` + edge JSON `slug`), then sweep every string reference (its tests, fixtures, GRIFT, expected JSON) **plus** every cross-plugin consumer's reference.
4. **Regenerate migrations** (`makemigrations` → table renames) and **reset the dev DB**.
5. **Full suite** (`scripts/test`) — the corpus is the net; a missed reference fails loudly. Iterate until green.
6. **Flip the lint** `warn-now → fail-CI` (`req-tap-plugin-type-collision-loud`) — the completion signal + anti-regression latch; and set `req-tap-plugin-type-node-prefix`/`-edge-suffix` → `Implemented`.
7. **One atomic promote.** Announce so the other sessions resync from swept `main`.

## Sizing

Wide but mechanical: ~90 node types + ~77 edge types across 6 plugins, dominated by string-reference
substitution the suite validates. With this map pre-built and decisions ratified, it's an evening's
execute-and-validate, not a design marathon — provided it runs uncontended.
