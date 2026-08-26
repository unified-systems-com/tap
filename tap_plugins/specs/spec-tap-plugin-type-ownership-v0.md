# Plugin Type Ownership & Namespacing v0 Specification

## Philosophy

A TAP plugin contributes **types** — node types (each a `BaseModel` with its own table) and edge types (relationship labels). Today those type identifiers live in a flat global namespace, and two failure modes have already bitten or can bite:

- **Edges merge silently.** Duplicate edge-type registrations union their source/target constraints (`req-grid-registry-3b`). That is intentional for *co-extension* (two plugins legitimately extending one shared edge) but it silently absorbs *homonym collisions* — two plugins independently using the same slug for unrelated relationships. This actually happened: `tap_cares` and `github_core` both registered `HAS_JOB`; the registry unioned `collector→collection_job` with `github_actions_run→github_actions_job`. It was caught by luck (an order-dependent test) and fixed by renaming both.
- **Nodes hard-block.** Node types hard-fail on duplicate slug (`EntityType.slug` is `unique=True`; `register_entity_type` raises `ImproperlyConfigured`). That is *safe* (loud, never silent) but *strict*: when a `salesforce` plugin wants its own platform-specific `user` node and `computing_core` already owns `user`, the system **refuses to boot** until someone renames. That is the "force one author to rename (awful)" outcome the platform explicitly rejects elsewhere (`spec-tap-logging.md`).

Both are the same underlying gap: **plugin-contributed type identifiers have no owner**, so the platform cannot tell *intended sharing* from *accidental collision*, and it resolves the ambiguity badly in both directions (silent-merge for edges, boot-block for nodes).

The core doctrine is:

> Every plugin-contributed type is owned by exactly one plugin, and its identifier carries that ownership. Ownership rides **inside the identifier string** — which already flows through every callsite, GRIFT bundle, query, table, and provenance record — so no owner argument is ever added at a usage site. Collisions become impossible by construction; what remains is a *loud* convention lint, never a silent merge or a boot-block.

### The verbose-names doctrine

This design deliberately accepts long, fully-qualified, "awkward" identifiers everywhere (`HAS_COLLECTION_JOB__tap_cares`, `salesforce__user`). Short, terse, DRY-on-identifier naming was an optimization for the **human** writing and re-reading code. When the primary author and reader is an AI that does not fatigue at verbosity, the *cost* side of that trade falls to ~zero while the *benefit* side stays full: unambiguous, self-describing, collision-proof, greppable identifiers with **no short-name→qualified resolution layer** to build or maintain. The research below is explicit on this point — the systems that added short-name resolution *to spare humans typing* (Kubernetes) are exactly the ones left with unsolved collision soft-spots. Verbose-and-explicit is strictly safer; it was only ever avoided for human comfort, and that constraint no longer binds.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Owned Types | Every plugin-contributed node/edge type is owned by exactly one plugin. |
| 2. | Zero Callsite Burden | Ownership lives in the identifier string; no owner argument at any usage/creation site. |
| 3. | Collisions Impossible | Qualified identifiers cannot collide; the owner-name space is unique by construction. |
| 4. | Loud, Not Silent | Convention violations are a loud lint; never a silent merge, never a boot-block. |
| 5. | Reuse Preferred, Forking Allowed | Cross-plugin reuse of a canonical type is encouraged (soft nudge); a plugin may still own a private same-named type. |

## Roadmap Alignment

This supports `plan/road-rampart.md` `step-rampart-first-paying-customer`, whose critical path includes the **plugin refactor** ("complete the refactor… to include the backend config and systems necessary to host the existing samsite plugin set"). Formalizing plugin-declared ownership is a plugin-refactor concern; this spec is the design the refactor inherits. It is **not** a near-term task — v0 instances run fine on the renamed `HAS_JOB` edges and the existing node guard. This records a decided direction so the refactor does not re-litigate it.

## Prior Art

A multi-source research pass (24 sources, adversarially verified) surveyed how plugin-extensible and graph/data systems handle owner-namespacing of identifiers. The findings shaped this design:

- **RDF/Turtle CURIEs & Kubernetes GVK** — the "declare once, use short, resolve by context" camp. Ergonomic at the callsite, but the *resolution layer* is where the complexity and the unsolved problems live. Kubernetes — the poster child for short-name resolution — has an **unsolved** short-name collision problem: same-short-name kinds across API groups resolve *silently*, and the declare-once alias fix was **proposed but never shipped** (k8s issues #20293, #102378). TAP deliberately skips this camp: no resolution layer means none of its unsolved failure modes.
- **Kubernetes core-group-is-empty** — the core API group is the empty string; only non-core groups are qualified. TAP adopts this: core/platform types stay unqualified (the default namespace), only plugin types carry an owner (`req-tap-plugin-type-core-default`).
- **Drupal rejected structured owner-namespacing** — switching identifiers to a dotted owner form "broke routing, tables, and params," and maintainers ultimately chose **visible failure over enforcement** (drupal #1862600). This is the direct cautionary tale: `entity_type`/`edge_type` flow through tables, queries, GRIFT, provenance, and viz — the same "routing/tables/params" surface. The lesson: keep the qualified identifier a **flat opaque string** (`req-tap-plugin-type-flat-string`), never a parsed structured field, and make collisions *visible* rather than enforced-away.
- **WordPress `register_post_type`** — no uniqueness check at all; pure prefix convention; duplicates silently overwrite. Confirms that mature ecosystems land on *convention + visible failure*, not structured namespace fields.
- **Maven `groupId:artifactId`, Clojure namespaced keywords (`:ns/kw`), Java FQNs** — the "fully-qualified identity is the name" camp. Explicit, verbose, **no resolution layer**. This is the camp TAP joins, with the owner as a slug affix rather than a prefix-colon.

The net the research endorses: a flat fully-qualified identifier, owner inferred from an already-unique source, collisions made loud — not a structured field, not silent merge, not short-name resolution.

## The Traction Point: Plugin Slug Uniqueness

The whole scheme grounds out on an identifier that is **already unique by construction**: the plugin slug. `TapPluginConfig.__init__` sets `self.label = data["slug"]` (`tap_plugins/base.py`), and `label` is Django's app-registry key — `AppConfig.populate()` hard-fails at startup if two apps share a label. So two plugins with the same slug cannot coexist. Every existing slug is `[a-z_]+` with no embedded `__`, so it is safe to affix with a `__` delimiter. **The owner-name space is collision-free for free**, inherited from Django's app-label enforcement; no new uniqueness machinery is introduced. The qualified-identifier uniqueness therefore reduces entirely to slug uniqueness, which already holds.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-type-owner-identity | [Owner Is The Plugin Slug](#owner-is-the-plugin-slug) | Proposed | Owner = unique plugin slug; qualified id unique by inheritance |
| req-tap-plugin-type-flat-string | [Flat-String Identity](#flat-string-identity) | Proposed | Qualified id stays a flat opaque string, never a parsed field |
| req-tap-plugin-type-node-prefix | [Node/Table Owner Prefix](#nodetable-owner-prefix) | Implemented | Plugin node types + tables: `<slug>__<name>` |
| req-tap-plugin-type-edge-suffix | [Edge Owner Suffix](#edge-owner-suffix) | Implemented | Plugin edge types: `<NAME>__<slug>` |
| req-tap-plugin-type-core-default | [Core Is The Default Namespace](#core-is-the-default-namespace) | Proposed | Core/platform types stay unqualified |
| req-tap-plugin-type-reuse | [Reuse By Qualified Reference](#reuse-by-qualified-reference) | Proposed | Reuse = reference the owner's full name; soft nudge to prefer it |
| req-tap-plugin-type-collision-loud | [Collisions Are Loud, Not Silent](#collisions-are-loud-not-silent) | Implemented | Replace silent-merge + boot-block with namespacing + loud lint |
| req-tap-plugin-type-db-affordance | [DB-Level Plugin Affordance](#db-level-plugin-affordance) | Proposed | `<slug>__*` tables enable per-plugin DB ops; schema upgrade path |
| req-tap-plugin-type-display-strip | [Display Strips The Owner](#display-strips-the-owner) | Proposed | Human surfaces strip the owner affix; code/queries use full names |
| req-tap-plugin-type-verbose-doctrine | [Verbose-Explicit Naming Doctrine](#verbose-explicit-naming-doctrine) | Proposed | Long qualified names are accepted; no resolution layer |

---

### Owner Is The Plugin Slug
----
RID: `req-tap-plugin-type-owner-identity`
Status: `Proposed`

Every plugin-contributed type identifier carries its owning plugin's slug. Because slugs are already unique (Django app-label enforcement, see Traction Point), qualified type identifiers are unique by inheritance — collisions reduce to slug collisions, which cannot occur.

#### Implementation

- The owner token is the plugin `slug` (== Django app `label`), not the module path (`self.name`) and not a new identifier.
- The delimiter is `__` (double underscore); slugs and type names are `[a-z_]+`/`[A-Z_]+` and contain no `__`, so the split point is unambiguous (rightmost/leftmost `__` per placement rule).
- No owner argument is added to any service signature, GRIFT field, or callsite — the owner is *in the identifier string* the callsite already passes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-owner-identity-1 | Slug Is Owner | Proposed | The owner token is the plugin slug; qualified ids inherit slug uniqueness. | |
| req-tap-plugin-type-owner-identity-2 | No Callsite Argument | Proposed | No usage/creation site gains an owner parameter. | |

---

### Flat-String Identity
----
RID: `req-tap-plugin-type-flat-string`
Status: `Proposed`

A qualified type identifier is a **single flat opaque string** end to end. It is never decomposed into structured fields that routing, tables, queries, or params depend on.

#### Implementation

- `entity_type` / `edge_type` remain plain strings; `salesforce__user` is one value, not `{owner, name}`.
- Parsing the owner out (for display-strip or lint) is a *read-time convenience*, never a stored structural split.
- This directly avoids the Drupal failure mode (structured owner-namespacing "broke routing/tables/params"); a longer flat string changes nothing downstream except length.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-flat-string-1 | Opaque String | Proposed | Qualified identifiers stay flat strings; no stored structured decomposition. | |

---

### Node/Table Owner Prefix
----
RID: `req-tap-plugin-type-node-prefix`
Status: `Implemented`

A plugin node type — and its backing table — is named `<slug>__<name>` (owner **prefix**).

#### Implementation

- `entity_type` slug: `salesforce__user`, `salesforce__account`.
- `db_table`: `salesforce__user` (the table carries the same prefix).
- **Why prefix, not suffix:** nodes have *per-type tables*, and the dominant grouping for a table is *by owner* (DB grants, RLS, backup/restore, observability). Owner-first naming makes "everything plugin X owns" a `LIKE '<slug>__%'` prefix match — index-friendly and the basis for `req-tap-plugin-type-db-affordance`. This is a *structural* justification (nodes have tables), not a visual one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-node-prefix-1 | Node Prefix | Implemented | Plugin node types are `<slug>__<name>`. | |
| req-tap-plugin-type-node-prefix-2 | Table Prefix | Implemented | The backing table carries the same `<slug>__` prefix. | |

---

### Edge Owner Suffix
----
RID: `req-tap-plugin-type-edge-suffix`
Status: `Implemented`

A plugin edge type is named `<NAME>__<slug>` (owner **suffix**).

#### Implementation

- `edge_type`: `HAS_COLLECTION_JOB__tap_cares`, `OPPORTUNITY_LINK__salesforce`.
- **Why suffix, not prefix:** edges are *column values* in the single shared `tap_edge` table — they have no per-type table, so the DB-affordance reason for owner-first does not apply. The dominant way an edge is read is *as a relationship* ("A —OPPORTUNITY_LINK→ B"), so the relationship name leads and the owner trails. Display-strip drops the trailing `__<slug>`.
- The placement difference from nodes (prefix vs suffix) follows the rule **"put the slug where the dominant grouping wants to lead"** — owner-first for things you group by owner (tables), relationship-first for things you read as a relationship (edges). It is reinforced by, but not justified by, the existing case convention (`HAS_JOB` upper = edge, `user` lower = node) and the field separation (`edge_type` vs `entity_type`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-edge-suffix-1 | Edge Suffix | Implemented | Plugin edge types are `<NAME>__<slug>`. | |

---

### Core Is The Default Namespace
----
RID: `req-tap-plugin-type-core-default`
Status: `Proposed`

Core/platform types are **unqualified** — the default namespace. Only plugin-contributed types carry an owner affix.

#### Implementation

- Core types stay bare: `entity`, `edge`, `batch`, `keystone`, `dimension`, `search`, and core edges like `PRODUCED_BATCH`.
- This mirrors Kubernetes' empty core API group: the common case stays clean, and a present owner affix reliably signals "plugin-owned."
- Core types are owned by `tap_grid`/core; they are exempt from the affix rather than carrying a `tap_grid__`/`tap__` prefix, to keep the platform surface terse.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-core-default-1 | Core Unqualified | Proposed | Core/platform types are bare; only plugin types are affixed. | |

---

### Reuse By Qualified Reference
----
RID: `req-tap-plugin-type-reuse`
Status: `Proposed`

Cross-plugin reuse of a canonical type is done by **referencing the owner's fully-qualified name** — the same rule for nodes and edges. Reuse is *encouraged* by a soft nudge, but a plugin may still own a private same-named type.

#### Implementation

- To reuse `computing_core`'s person type, a plugin references `computing_core__user` — it does not redeclare it.
- To own a distinct platform-specific type, a plugin declares its own `<slug>__user` — legitimate and collision-free (the Salesforce case).
- A lint/validation **nudges** (does not block) when a plugin declares a type whose unqualified name matches an existing canonical type ("`computing_core__user` already exists — reuse it, or confirm you want a distinct `salesforce__user`?"). This preserves the healthy reuse pressure the old node hard-raise provided, without the boot-block.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-reuse-1 | Reuse By Full Name | Proposed | Reuse references the owner's fully-qualified name; no redeclaration. | |
| req-tap-plugin-type-reuse-2 | Forking Allowed | Proposed | A plugin may own a private same-named type without a boot-block. | |
| req-tap-plugin-type-reuse-3 | Reuse Nudge | Proposed | A lint nudges (does not block) toward reusing an existing canonical type. | |

---

### Collisions Are Loud, Not Silent
----
RID: `req-tap-plugin-type-collision-loud`
Status: `Implemented`

Owner-namespacing makes true collisions impossible; what remains — a *convention* violation (a forgotten affix, two plugins claiming the same qualified name) — is surfaced **loudly** by a dev-validation lint, never resolved silently.

#### Implementation

- This **replaces** the two current bad resolutions: the edge registry's silent merge (`req-grid-registry-3b`) becomes harmless once names are qualified (only identical qualified names ever merge, which by construction is intentional co-extension); the node registry's hard boot-block becomes unnecessary (namespacing removes the collision).
- The remaining enforcement is **detection**: a lint that flags (a) a plugin type missing its owner affix, and (b) any qualified name claimed by two plugins. Loud at validation/CI time, the platform's standing posture (`spec-tap-logging.md`: visible failure over forced coordination; the research's "warn, not silent-merge").
- The merge mechanism itself does **not** need to change for safety — qualification makes it safe. The lint is what turns *convention* into *reliability* (a forgotten affix can't silently re-open the hole).
- **Implemented (2026-07-02)** as a **fail-CI** guard, `tap_plugins.guards.type_ownership.PluginTypeOwnershipGuard` (the harness guard set, per-commit via `tap/tests/test_guards.py`). It reads every in-repo plugin's `tap-plugin.toml` and asserts each `[models]`/`[editors]` key carries the `<slug>__` prefix, each `[edges]` key the `__<slug>` suffix, and no qualified name is claimed by two plugins. No warn phase was needed: the `<slug>__<name>` sweep landed atomically, so the guard went straight to fail-CI on a fully-qualified tree.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-collision-loud-1 | No Silent Merge | Implemented | Qualification makes merge safe; unrelated types never silently union. | |
| req-tap-plugin-type-collision-loud-2 | No Boot-Block | Implemented | Node collisions are removed by namespacing, not by refusing to boot. | |
| req-tap-plugin-type-collision-loud-3 | Loud Lint | Implemented | A dev-validation lint loudly flags missing affixes and duplicate qualified names. | |

---

### DB-Level Plugin Affordance
----
RID: `req-tap-plugin-type-db-affordance`
Status: `Proposed`

`<slug>__*` table naming unlocks per-plugin database-level operations that only nodes (which have tables) can have.

#### Implementation

- Prefix-named tables make "all of plugin X's tables" a `LIKE '<slug>__%'` match — the basis for per-plugin `GRANT`s, row-level-security policies, backup/restore-by-plugin, and observability.
- This is the *light* form of per-plugin DB isolation. The *native Postgres* form is **schemas** (`salesforce.user`, `GRANT ... ON SCHEMA salesforce`); prefixed tables in `public` get ~80% of the affordance with zero schema-management overhead. Schemas are the heavier upgrade path if per-plugin DB boundaries ever become a hard security requirement (Paladin-operator territory). v0 uses prefixed tables; the schema path is noted, not taken.
- Edges, being column values in one shared table, get none of this — which is *why* the node/edge placement differs.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-db-affordance-1 | Prefix Enables DB Ops | Proposed | `<slug>__` table naming supports per-plugin grants/RLS/backups by name pattern. | |
| req-tap-plugin-type-db-affordance-2 | Schema Upgrade Path | Proposed | Postgres schemas are the documented heavier alternative; not taken in v0. | |

---

### Display Strips The Owner
----
RID: `req-tap-plugin-type-display-strip`
Status: `Proposed`

Human-facing surfaces strip the owner affix for readability; code, queries, GRIFT, and storage use the full qualified name.

#### Implementation

- Viz/panels/admin display `user` / `HAS_COLLECTION_JOB`, not the affixed form, by stripping the leading `<slug>__` (nodes) or trailing `__<slug>` (edges) — a localized read-time concern, the only runtime code the scheme adds beyond the lint.
- Query authoring, GRIFT bundles, provenance, and `db_table` use the **full** qualified name — no short-name resolution. Verbosity at authoring time is the accepted trade (`req-tap-plugin-type-verbose-doctrine`).
- Where ambiguity could mislead a human (two plugins' stripped names collide on screen), display may re-qualify; the stored identity is always the full name.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-display-strip-1 | Strip For Display | Proposed | Human surfaces strip the owner affix; storage/queries use full names. | |

---

### Verbose-Explicit Naming Doctrine
----
RID: `req-tap-plugin-type-verbose-doctrine`
Status: `Proposed`

TAP accepts long, fully-qualified identifiers everywhere and builds **no** short-name→qualified resolution layer. Terse naming was a human-ergonomic optimization that no longer binds when code is authored and read primarily by AI.

#### Implementation

- No `@prefix`/import/alias/short-name machinery — the qualified name *is* the name at every authoring site.
- The benefit (unambiguous, self-describing, collision-proof, greppable, no resolution layer to maintain) is kept in full; the cost (typing/reading length) is borne by tooling/AI, where it is negligible.
- This is the deliberate divergence from the CURIE/K8s camp, justified by the research: short-name resolution is exactly where those systems retain unsolved collision problems.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-type-verbose-doctrine-1 | No Resolution Layer | Proposed | No short-name resolution; full qualified names at all authoring sites. | |

---

## Implementation Sequencing (Guidance)

This lands with the **plugin refactor**, and is sequenced **before plugin repo extraction** — a global type rename is dramatically cheaper in the monorepo than across N extracted repos. When it does:

1. ~~Decide~~ **Locked 2026-06-26:** delimiter is `__`; core-default exemptions stay bare (`entity, edge, batch, keystone, dimension, search` + core edges); lint strictness is **warn-now, fail-CI once the sweep completes** (so the half-swept intermediate state does not red-gate itself — `req-tap-plugin-type-collision-loud`).
2. Add owner-affixing to plugin type registration (node prefix, edge suffix), inferring the owner from the registering plugin's slug — authors write the affixed name in manifests/JSON (no auto-resolution; the written name is the real name). Note: because v0 keeps the written name == the real name, the registry needs **no new inference logic** — it registers the opaque affixed string as-is.
3. Mechanical rename sweep of existing plugin node types + tables (`<slug>__name`) and plugin edge types (`NAME__<slug>`). Core types stay bare. No data migration semantics beyond table renames; dev resets freely (as the `HAS_JOB` rename already demonstrated). **See the cost model below — the dominant cost is string references, not model files.** **Staged runbook + full per-plugin rename map: `docs/misc/doc-plugin-type-sweep-runbook.md`** (run last-session-standing). Naming decisions ratified there 2026-07-02: **verbatim prepend `<slug>__<name>` everywhere, no prefix stripping** (so `aws_account` → `aws_core__aws_account`, `fedramp` bare types prepended, `sigstore_`/`rekor_` kept); the apparent redundancy is invisible on human surfaces once `req-tap-plugin-type-display-strip` drops the leading affix.
4. Add the display-strip at viz/panels/admin and the dev-validation lint.
5. Relax the node hard-raise to the reuse nudge; leave the edge merge in place (now safe).

### Sweep cost model & proof-plugin selection (2026-06-26)

A pre-sweep survey of the candidate plugins produced a correction worth recording so it is not rediscovered: **the rename's dominant cost is *string references* to the type slugs, not the plugin's own model files.** A plugin's `ENTITY_TYPE` / `db_table` / edge-`slug` edits are a handful of files; the real ripple is everywhere the bare slug appears *as a string* — test corpora, GRIFT/fixture/expected-result data, Gryphon query strings, doc examples, and cross-plugin edge endpoints.

Consequences for sequencing:

- **Rank candidate plugins by string-reference count, not module-import count.** `grep -rn '<slug-tokens>'` repo-wide is the selection tool; an import-count proxy is misleading (it under-counts the data/corpus references that dominate).
- **The corpus/example plugins are the *highest*-ripple and sweep LAST, not first.** `lotr` is the constraint/edge/validation test corpus (~20 core test modules); `gryphon_playground` is the Gryphon query corpus *and* the engine's canonical example vocabulary (~80 self-contained fixture/expected/scenario JSON files + 43 executed-query refs in `tap_grid/tests/test_gryphon.py` + ~17 docstring/error-hint examples in `tap_grid/gryphon/executor.py`/`ast_nodes.py`). The genuinely isolated plugins (`genericom`, `administrivia`) are grift-only and have **no** node/edge type surface to rename, so they cannot serve as the proof.
- **Context-aware rewriting, not a blind sed.** The same token means different things in different places — e.g. `pg_node` is simultaneously a type-slug *value*, a Python module path (`models/pg_node.py`), a `db_table` component, and (as `PgNode`) a class name. Only the type-slug *value* / manifest key / edge-endpoint / query-string / data-`type` occurrences are rewritten; module paths, filenames, class names, and the `db_table` *prefix* delimiter (`<slug>_<name>` → `<slug>__<name>` is a single→double-underscore change, not a slug re-prepend) must be left alone or handled distinctly.
- **Display-strip interacts with `expected`-result corpora.** Until `req-tap-plugin-type-display-strip` is implemented, query results return the raw affixed `entity_type`, so fixtures and `expected/*.expected.json` rename together uniformly and stay green. Once display-strip lands, some occurrences want the stripped form and some the full form — so a corpus-heavy plugin renamed *before* display-strip is the simpler ordering.

**Chosen proof plugin: `gryphon_playground`.** It is the right *first proof* despite its corpus size because it is **functionally self-contained** — the ~17 core-engine references are docstring examples + one error-hint string (cosmetic; a stale example is a doc nit, not a bug), with **no functional coupling** (no `entity_type ==` branch, no model import, no registry hardcode), so a rename **cannot break the live boot or the engine**. Its full functional ripple is bounded: its own files (4 node types + tables, 4 edge types, manifest, ~80 corpus JSON, plugin tests, one table-rename migration) + the 2 core Gryphon test files. It exercises both the node-prefix and edge-suffix surfaces. The proof produces the reusable template for the remaining plugins; the cross-plugin-edge plugins (`sigstore_core`, `aws_core`, `github_core`, `fedramp_20x_ksi`, `samsite`) follow, with `lotr`/`gryphon_playground`-class corpus updates handled with the display-strip ordering above.

## Backlog

- Postgres **schemas** as the native per-plugin DB boundary (`req-tap-plugin-type-db-affordance` heavier path), if/when per-plugin DB isolation becomes a hard security requirement.
- Auto-affix inference at registration (the research's "infer owner at registration") — deliberately **not** v0, because if the runtime name is auto-affixed while authors write the bare name, a short-name→qualified resolution problem is reintroduced — the exact complexity this design avoids. v0 keeps the written name == the real name.
- A first-class plugin-dependency model (declared `[dependencies]`, named narrow contracts, versioning, detectable breakage) — the broader home for cross-plugin reuse/ownership (`spec-tap-testing.md` already backlogs this). Type ownership here is one input to it.

## Relationship To Other Specs

- **`spec-grid-registry.md`** (`req-grid-registry-3b`, and the edge-homonym future-seam note) — this spec is the decided resolution of that seam. The merge behavior stays; qualification makes it safe.
- **`spec-tap-plugin-manifest-v0.md` / `spec-tap-plugin-load-lifecycle-v0.md`** — own where plugin types are declared/registered; the owner-affix is applied in that registration path.
- **`spec-tap-plugin-validation.md`** — the natural home for the collision/affix lint (`req-tap-plugin-type-collision-loud`).
- **`spec-tap-testing.md`** — the backlogged plugin-dependency model that subsumes cross-plugin reuse.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
