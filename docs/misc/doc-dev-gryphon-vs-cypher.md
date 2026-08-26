---
spec: ../../tap_grid/specs/spec-grid-traversal-language.md
audience: [llm, developer]
covers:
  - ../../tap_grid/specs/spec-grid-traversal-language.md
  - req-grid-traversal-lang-cypher-divergence
  - req-grid-traversal-lang-cypher-credit
  - ../../tap_grid/specs/spec-grid-node.md
  - ../../plugins/gryphon_playground/specs/spec-gridkin-v0.md
update-triggers:
  - A new Gryphon capability ships that Cypher has no equivalent for (add a credit-ledger row)
  - A Gryphon feature is given semantics that deliberately differ from Cypher's (add a divergence-ledger row)
  - A capability listed here as planned/deferred ships, changes status, or is dropped
  - openCypher / Neo4j changes a behavior this doc contrasts against, making a row stale
  - A deliberate-subset omission (a Cypher feature Gryphon chooses not to have) is decided or reversed
assumes:
  - Reader has skimmed spec-grid-traversal-language.md (the language surface) — this doc is the Cypher-relationship lens on it, not a re-spec
  - Reader knows Cypher / openCypher at a working level (this is a contrast doc, not a Cypher tutorial)
provides: |
  The running tab of how Gryphon relates to Cypher, in three ledgers: where Gryphon
  goes BEYOND Cypher (the "why not just use Cypher?" answer), where it DELIBERATELY
  DIVERGES (the gotchas an engineer arriving from Neo4j will trip on), and where it
  is a DELIBERATE SUBSET (Cypher features intentionally absent, so a gap reads as a
  choice not as debt). The credit ledger is also a forward differentiation roadmap:
  planned/deferred capabilities are listed with status.
---

# Gryphon vs Cypher — Divergences, Credits, and Deliberate Subset

Spec (owning): [spec-grid-traversal-language.md](../../tap_grid/specs/spec-grid-traversal-language.md)
Requirements: `req-grid-traversal-lang-cypher-divergence` (divergence ledger), `req-grid-traversal-lang-cypher-credit` (credit ledger)

## Why This Doc Exists

Gryphon is Cypher-*familiar*, not Cypher-*compatible* — "a language narrow enough to compile
safely into TAP-controlled execution plans" (the language spec's Philosophy). That relationship
needs a single, maintained surface for three reasons:

1. **The "why not just use Cypher / Neo4j?" question will come up** — in positioning, in
   early-adopter conversations, and the first time someone proposes adopting an off-the-shelf
   graph database. The credit ledger below *is* the answer, tracked as it accrues rather than
   reconstructed under pressure.
2. **Divergences are gotchas.** An engineer arriving from Neo4j brings muscle memory. Where
   Gryphon's surface looks like Cypher but means something else (`=~`), that is a load-bearing
   surprise; it belongs in one discoverable place, not scattered across feature backgrounds.
3. **A subset that isn't written down reads as debt.** Gryphon omits Cypher's write clauses and
   most of its function library *on purpose*. Recording those as deliberate choices keeps a future
   reader (or reviewer, or customer) from mistaking a design boundary for an unfinished one.

This doc is a **catalogue, not the authority.** Each owning feature requirement remains the source
of truth for *why*; the ledgers here summarize and link. When a row and its owning requirement
disagree, the requirement wins and this doc is stale — fix it (`req-docs-drift-conventions`).

---

## Ledger A — Where Gryphon Goes BEYOND Cypher (the credit ledger)

**The unifying theme: Cypher models present-state; Gryphon models observation and provenance as
first-class.** Almost every net-new capability sits on that one axis. That sentence is the
differentiator — the rest of this section is its evidence.

| Capability | Status | Owning req | The Cypher gap (one line) |
| --- | :---: | --- | --- |
| `IS KNOWN` / `IS UNKNOWN` | **shipped** | `req-grid-traversal-lang-observation` | Cypher has only `IS NULL` / `IS NOT NULL` — a storage question; Gryphon asks the observational one (observed vs unobserved) directly. |
| `x-tap-absence` declared field-absence semantics | **shipped** (substrate) | `req-grid-node-observation` (`spec-grid-node.md`) | Cypher property graphs have no declared absence vocabulary; null is undifferentiated. TAP fields *declare* what their null means, and it is discoverable in the schema. |
| Dimension / perspective scoping in field paths | **shipped / evolving** | `req-grid-traversal-lang-envelope-paths` (`-7`, JSON-typed spine multi-step) | Cypher has no native multi-perspective scoping; dimension membership is just another property to filter, not a first-class partitioning axis. |
| Spine / `data` / `display` lane split in field paths | **shipped / evolving** | `req-grid-traversal-lang-envelope-paths` | Cypher's node is a flat property bag; it has no question for "spine metadata vs typed-model field vs computed-for-render value," so the lane-prefix path shape is structurally net-new. |
| `IS EMPTY` (container-scoped observed-empty, `empty_is_meaningful`-driven) | planned (deferred) | `req-grid-traversal-lang-observation-6` | Cypher has no observed-empty concept distinct from null; `""`/`[]`/`{}` are just values. |
| Known-unknown vs unknown-unknown split (FLIP look-aside) | planned (deferred) | `req-grid-node-observation` (Phase-2) | Cypher collapses all absence into one null; TAP can distinguish "asserted absent" from "never observed" via FLIP. |
| `IS NOT_APPLICABLE` (extended-FLIP applicability axis) | Phase 2 | `req-grid-node-observation` (Phase-2) | Codd's A-mark. Cypher null cannot say "this field does not apply to this entity" as distinct from "unknown." |
| Provenance-in-query (FLIP-aware predicates) | future | — | Cypher has no field-level provenance to query against at all. |

Notes on the credit ledger:

- **"Shipped" means the executor lowers it today** and a Gridkin scenario pins it. **"Planned /
  deferred"** means designed-but-not-built — the discriminator often already ships in the schema
  (e.g. `empty_is_meaningful`) and only the executor lowering remains. **"Phase 2 / future"** means
  the design exists but the substrate (extended FLIP) is not yet built.
- The deferred/planned rows are deliberately listed: this ledger doubles as a **forward
  differentiation roadmap**, not just a record of the past.
- Read-only-by-construction (next section) is *also* arguably a credit — it is the property that
  lets Gryphon be safely embedded in stored search objects, panel configs, and (future) untrusted
  satellite callers in a way a read-write Cypher string cannot. It is filed under "deliberate
  subset" because the *mechanism* is an omission, but its security value is a genuine advantage.

---

## Ledger B — Where Gryphon DELIBERATELY DIVERGES (the gotcha ledger)

Same surface as Cypher, **different meaning**. These are the ones that bite an engineer who assumes
Cypher semantics.

| Surface | Cypher behavior | Gryphon behavior | Owning req |
| --- | --- | --- | --- |
| `=~` regex match | Full-string **anchored** (implicit `^...$`) | **Search / substring** (matches anywhere; anchor explicitly with `^...$`) — same shape as `grep` / Postgres `~` | `req-grid-traversal-lang-regex` (`-2`) |
| `RETURN` omitted | Syntax error — `RETURN` is mandatory | Legal — returns a **graph envelope** `{nodes, edges}`; explicit `RETURN` signals row-projection mode | `req-grid-traversal-lang-returns` (`-1`) |
| Per-`MATCH` `WHERE` attachment | `WHERE` attaches to its preceding `MATCH` and filters that clause | v0 has a **single global `WHERE`** scoped per bound variable across all `MATCH` clauses; per-`MATCH` attachment is future work | `req-grid-traversal-lang-shape` (Multiple-WHERE section) |
| Three-valued logic (3VL) | Full 3VL across all combinators ([Francis et al. §NULL](https://arxiv.org/abs/1802.09984)) | Gryphon does **not claim full 3VL**. A **null literal** operand (`x = null`, `x STARTS_WITH null`) short-circuits to a genuine `FALSE` — the two-valued "unobserved operand" rule; a **null field** vs a non-null literal follows the backend's SQL 3VL (drops from the positive filter). Guarantee: NULL inputs neither crash nor silently match, no more | `req-grid-traversal-lang-regex` (`-6`), `req-grid-traversal-lang-is-null` |
| Cross-type predicate (`severity_score = "10"`, `IN ["10"]`, `STARTS_WITH` on a number) | Silently **false / null** → row drops (schema-optional graph can't know the type) | **Rejected** with `SearchExecutionError` — TAP's data lane is typed, the declared schema is the type oracle, and a wrong-typed literal is an authoring bug surfaced rather than coerced (the ORM would mis-coerce `"10"`→`10`) or silently dropped | `req-grid-traversal-lang-type-strictness` |

Strictness reaches only as far as the schema declares a concrete type: a JSON field whose schema is a
bare `{"type": "object"}` is a declared **open blob**, so its sub-paths (`n.data.tags.zone`) stay
coercion-tolerant until the schema gains real `properties` — a named open edge in `spec-security-posture.md`.

When you add a divergence, add the row here **and** make sure the owning requirement's Background
explains *why* — the row points at it.

---

## Ledger C — DELIBERATE SUBSET (Cypher features intentionally absent)

These are Cypher capabilities Gryphon **chooses not to have** (yet, or ever). A gap here is a
design boundary, not unfinished work.

| Cypher feature | Gryphon status | Why omitted |
| --- | :---: | --- |
| Write clauses (`CREATE` / `MERGE` / `SET` / `DELETE` / `REMOVE`) | **rejected at parse time** | Gryphon is read-only by construction; all graph mutation goes through the typed service layer (the canonical-path architecture rule). This is a security posture, not a missing feature — and it is what lets a Gryphon string be safely stored and (future) accepted from untrusted satellite callers. |
| `WITH` (pipelined query composition) | future | Needs stage-scoping semantics; arrives with per-`MATCH` `WHERE` attachment. Tracked in the wishlist. |
| `UNWIND`, list / pattern comprehensions | not built | No demand signal yet. |
| `CALL { }` subqueries | not built | No demand signal yet. |
| `CASE` expressions, map projections | not built | No demand signal yet. |
| The ~150-function standard library | partial | Gryphon implements operators on demand-shape (`STARTS_WITH`/`CONTAINS`/`=~`/aggregates), not a broad function library. "Gryphon over ORM" pulls functions in when a real query reaches for one. |
| Variable-length paths in full generality | not built (parses, rejected) | Bounded repetition (`*1..3`) **parses but the executor rejects it** — fail-closed, not shipped (`executor.py:412` / `:1652` raise `SearchExecutionError`; `model_oracle.py` marks it `OracleUnmodeled`; rejection pinned by `test_gryphon.py`). The grammar carries `hop_range` as a deliberate half-built foothold (the language anticipates the shape; the executor surfaces its absence). Full Cypher path-predicate generality and `shortestPath` are also future work. Tracked as wishlist **E1** (`wait-for-signal`). |
| `NOT IN` as a distinct surface | expressible | Today `NOT (... IN ...)` where the executor path supports `NOT`; a dedicated surface is a Future bullet. |

The subset shrinks on **demand signal**, not on Cypher-parity ambition. The governing rule
(wishlist, `feedback_gryphon_over_orm`): a plugin reaching for raw ORM *is* the demand signal that
Gryphon should grow — features are organized by demand-shape, not by Cypher's table of contents.

---

## On Pulling In openCypher TCK Scenarios

The natural follow-on question: should we import the openCypher TCK's Gherkin scenarios? **No — we
mine, we never port**, and that discipline is already formalized:

- **The requirement:** the TCK-inspiration requirement of `spec-gridkin-v0.md` (gryphon_playground plugin repo) — Implemented.
- **The lifecycle binding:** `req-grid-traversal-lang-tck-mining` (the language spec) — every
  language extension runs the mining pass.
- **The coverage ledger:** the TCK-coverage requirement of `spec-gridkin-v0.md` — a corpus-wide,
  machine-checked record (`scenarios/gryphon_playground.tck-coverage.json`) of per-folder coverage: covered (derived),
  `gaps` (what we still owe, each tagged test/feature/unknown), and `excluded` (Cypher-specific
  intents deliberately dropped). The drift guard bidirectionally ties ledger folders to scenario cites.
- **The operational steps:** the `build-gryphon-capability` skill, Step 8.
- **The rationale:** `doc-dev-gryphon-wishlist.md` §7 — "TCK as scenario inspiration (never as
  scenario source)."

Why mine-not-port, in one line: the TCK's value is the *corner-case taxonomy* ("these shapes
historically broke real engines") — the queries themselves are downstream of that knowledge and
encode Cypher semantics Gryphon deliberately diverges from (Ledgers B and C). A mined scenario sets
`inspired_by` to the TCK source folder (the attribution breadcrumb); no TCK query text, graph data,
or expected results are ever copied. Full mechanical TCK adoption is reconsidered only if Gryphon's
surface ever grows to where ~70%+ of the TCK translates *and* there is external demand for a
Cypher-subset compatibility claim — until then, mine-only.

---

## Related

- [spec-grid-traversal-language.md](../../tap_grid/specs/spec-grid-traversal-language.md) — the language surface (owning spec).
- [spec-grid-node.md](../../tap_grid/specs/spec-grid-node.md) — the field-observation convention (`req-grid-node-observation`) that the credit ledger's observation axis rests on.
- [doc-dev-gryphon-wishlist.md](doc-dev-gryphon-wishlist.md) — demand-shape feature roadmap and the validation contract; the forward-looking companion to this backward-looking ledger.
- [spec-gridkin-v0.md](../../plugins/gryphon_playground/specs/spec-gridkin-v0.md) — Gridkin format and the TCK-inspiration requirement.
