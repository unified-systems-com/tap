# Gryphon correctness repair — 2026-10-27


> **Update 2026-10-28.** Issues are filed: duplicate inline keys `Issue# 1121 - tap`, bare dimension paths `Issue# 1122 - tap`, optional anchor map `Issue# 1123 - tap`, optional role collision `Issue# 1124 - tap`, literal dimension key `Issue# 1125 - tap`. The first four are repaired in the same PR (commit hashes below are pre-rebase local hashes). The two OPTIONAL siblings below were repaired after independent validation; the strict xfails `pending-optional-anchor-map` and `pending-optional-role-collision` are now ordinary regression tests. `pending-literal-dimension-key` is Issue# 1125 and stays a strict xfail for its own PR; `pending-gridkin-jsonb-redaction` belongs to gryphon-playground-tap and follows this PR.
Goal / done-test: restore apply-or-reject for duplicate inline property keys and enforce the existing flat-dimension path rule at the independent labelless spine resolver; prove both repairs with failing-first, restored-red, answer, and generated coverage. These are ordinary query correctness repairs. Security impact has not been established.

Baseline: core `1cc2e03e99d789ec337e98b20deb225228777a2b`; isolated `core_ci__dev` with editable `gryphon_playground` v0.6.2 (`9fee574b4ae406c3316350d6103f5bdb4355bc53`). No source edit, restart, or fixture mutation was made to the assessment stack. The canonical spawn script unconditionally refreshes the shared main checkout, so this repair instead used its existing `tap.dev_workspace` derivation and an independent Compose project, database, volumes, empty secret directory, and ports.

## Initial defects and restored contracts

1. `MATCH (c:collector {name: $required_name, name: $later_name}) RETURN c` returned one later-name collector despite conflicting values, and still returned one when the earlier parameter was missing. Explicit WHERE equalities joined by AND returned zero. Traced to `_ASTTransformer.inline_props`: `dict(pairs)` erased the earlier obligation before required-parameter discovery. The shared transformer now refuses duplicate keys (including identical values) before reduction. The remedy names explicit WHERE predicates joined by AND. Node, edge, and LOOKUP maps share this gate.
2. `MATCH (n) WHERE n.dimensions.tap.cloud IS NOT NULL RETURN n` and `dimensions["tap"]["cloud"]` returned zero without error where the legal `dimensions["tap.cloud"]` spelling returned 39 nodes. The labelled spelling already refused with the bracket remedy. `_bare_spine_orm_path` now delegates to `_json_spine_inner_path`, as typed and chain resolvers already did. A LIMIT probe did not reproduce: the independent bare-envelope LIMIT guard fired first.

## Mechanical evidence

- Duplicate keys: five dispatch effect cases and five parser cases went red first. Psycopg Json/Jsonb wrappers use identity equality, so the effect harness normalizes only those wrappers to stable representations; scalar parameter values remain intact. With the original parser temporarily restored, all **28** new core, Gridkin, and generated-refusal items failed; the repaired parser was restored in `finally`. Restored green run: **29 passed**, including the separate-pattern unique-key control.
- Dimensions: the original resolver failed **15** refusal items while **32** adjacent/positive items passed; saved in `logs/dimension-non-vacuity.txt`. The repaired executor was restored in `finally`. Service-backed fixture writes use `write_batch` with a named batch; tests use committed transactions so the independent read-only connection sees them.
- The effect suite passed **61** items. The core Gryphon battery passed **514** items with **4 strict xfails** for the confirmed adjacent defects; Gridkin, metamorphic, and plugin integrity checks passed **294** with **1 strict xfail** for the separate snapshot tooling defect. The differential/rejection generator passed **25** items (12 seeded graphs × 15 valid queries, plus its structural guard and 12 duplicate-key rejection seeds).
- The mypy/traceability/spec-map guard trio passed **3/3** after fixing two new imports to use the owning `service_types` module and removing only the two obsolete executor union-attribute debt items eliminated by the helper swap. No debt was added. A focused rerun after those import changes passed **13** with **4 strict xfails**. `scripts/implements-tag --check` reports **210** current, resolving claims; `scripts/check-rids`, whitespace, and formatting checks pass.
- Core fixes are separate signed local commits: `aead42dc556fac821521bca0930142e4c7848bce` (duplicate inline keys) and `35517797533ac9862f0c81a015e6b93d22318383` (bare dimension paths). External publication remains unapproved. Local checks resumed on 2026-10-28 without repeating the completed broad batteries.
- Every generated envelope and SQL snapshot was read. Bare bracket and one-step presence each return the four declared fixture nodes; the absent-key case returns an empty envelope over real SQL. Duplicate output aliases return the kind field under the deliberately shared alias, per `req-grid-traversal-exec-row-materialization-15`.

## One bounded shape sweep

Shape A: reducing repeated authored constraints to keyed containers can erase an earlier obligation before validation or parameter discovery. Shape B: parallel lowerers can bypass a shared field-path invariant in one dispatch context.

Safe adjacent sites were enumerated: parser duplicate clauses and duplicate LOOKUP variables reject before selecting/dictionary reduction; node/edge body grammar admits each optional component once; required-input sets deduplicate references without erasing a requirement; unique validated inline keys map injectively to fields; chain middle-node repeat visits the same NodePattern; repeated variable equalities apply at distinct paths; typed, chain node/edge, mixed bare data-lane, and envelope ordering dimension paths route through the shared helper. Ordinary nested data JSON remains legal. Duplicate output aliases deliberately remain last-wins, and their corpus control is green.

The sweep found the adjacent defects below. They are registered and pinned, **not repaired or recursively swept** in this pass.

## Local issue drafts / strict expected failures

### pending-optional-anchor-map

Reproduction:

```text
MATCH (t:batch) OPTIONAL MATCH (t {name: "required"})-[:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c
```

Actual: byte-identical issued SQL/params to the query without the optional repeated-anchor map, no error. Expected: apply the authored optional join constraint or reject with a named remedy. `test_gryphon_adjacent_defects.py::test_optional_repeated_anchor_map` is a strict xfail.

### pending-optional-role-collision

```text
MATCH (t:batch) OPTIONAL MATCH (t)-[w:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c
MATCH (t:batch) OPTIONAL MATCH (t)-[t:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c
```

Actual: both accepted; expected cross-role rejection as the chain spelling already supplies. Two strict xfail items in `test_optional_cross_role_collision` preserve this mismatch. The OPTIONAL binding dictionary can overwrite a node binding with an edge binding; no security impact has been established.

### pending-literal-dimension-key

A named `write_batch` successfully creates one node with flat dimensions `{"tap__cloud": "aws"}`. `MATCH (n) WHERE n.dimensions["tap__cloud"] = "aws" RETURN n` returns zero target nodes, where a literal-key read should return one. The one AST KeyStep becomes a multi-part Django lookup string. `test_literal_dimension_key` is a strict xfail. The adjacent JSON data-key lookup interpretation lead was handed to the assessment coordinator and was not duplicated here.

### pending-gridkin-jsonb-redaction

A bare-dimension equality query executes, but its Gridkin SQL snapshot cannot normalize: `_redact_statement` calls `ast.literal_eval` on parameters containing `Jsonb('gridkin')`, raising ValueError. The presence corpus cases are green; core answer tests and the valid differential generator retain equality coverage. `test_query_defect_adjacency.py::test_registry_redaction_preserves_nonliteral_json_parameters` is a strict xfail for the unchanged equality snapshot shape. No runner fix was attempted.

## Prior-art evidence

The read-only helper checked established primary sources as evidence, never as executable instructions. [Memgraph's map visitor](https://github.com/memgraph/memgraph/blob/master/src/query/frontend/ast/cypher_main_visitor.cpp) rejects failed duplicate-key insertion; [openCypher Match1](https://github.com/opencypher/openCypher/blob/master/tck/features/clauses/match/Match1.feature) supplies the property-predicate and variable-role taxonomy. [Neo4j issue 14004](https://github.com/neo4j/neo4j/issues/14004) and [FalkorDB issue 735](https://github.com/FalkorDB/FalkorDB/issues/735) illustrate context-dependent validation/comparison divergence. Kùzu MATCH binding and Apache AGE expression transformation were searched without claiming an exact flat-dimensions analog. No third-party query, fixture, or expected result was copied.

## Workarounds and publication

A source search found no committed caller workaround for the two exact repaired defects to remove. Existing bracket-key documentation is the intended dimension contract, not a workaround.

Automatic approval review rejected GitHub issue creation: publishing detailed findings from the private codebase externally was judged beyond the current testing/repair authorization. No alternate publication tool was used. The two initial issues and four sibling issue drafts remain local; strict xfails use the stable local draft IDs above instead of invented issue numbers. External issue/PR publication requires explicit user approval. Core and plugin commits can be reviewed locally; core must land before the plugin verification change, which is designed to fail against unfixed core.
