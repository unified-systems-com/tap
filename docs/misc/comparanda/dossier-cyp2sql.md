# Dossier — cyp2sql ("Reagan")

Clone: `22679a42d7afa1aaae744f48d72f78caa39ccb05` (master), read 2026-07-04. License: Apache-2.0 (`LICENSE:1-3`).
Repo: https://github.com/ocrawford555/cyp2sql — clone at `undefined/cyp2sql` (disposable; all `file:line` anchors are at the clone SHA).
Successor: https://github.com/DTG-FRESCO/cyp2sql — clone at `undefined/cyp2sql-dtg`, SHA `85be7ec34e015edbe7de830f67e25ca96f296b16`, read for lineage (the primary repo's final commit `22679a4` points at it: "this tool has been redevloped and now exists in a new repository", `README.md:5`).
Protocol: `docs/misc/doc-gryphon-comparative-eval-protocol.md` §4.4. **Lens E primary.**

## Snapshot

A University of Cambridge Part II (undergraduate dissertation) project by Oliver
Crawford (`README.md:9-14`; `Reagan_Main_V4.java:27`, ojc37@cam.ac.uk): a Java tool
that (1) migrates a Neo4j dump into a co-designed Postgres schema — a `nodes`
catch-all table, per-label node tables, an `edges` table plus per-reltype `e$TYPE`
tables, an adjacency-list table (`adjList_from`, array-valued `rightnode`), and an
optional precomputed transitive-closure table `tClosure` with a `depth` column
(`InsertSchema.java:174,210,264,331`; `SingleVarRel.java:113-120`;
`SingleVarAdjList.java:49`) — and (2) transpiles Cypher **to SQL text** executed
over JDBC, with a built-in differential evaluation against a live Neo4j
(`Reagan_Main_V4.java:320-343`). 112 commits, one author, Oct 2016 → Sep 2017,
then abandoned in favor of a ground-up redevelopment with a DTG supervisor
(43 commits, +Lucian Carata, dead by 2017-08-31 — `git shortlog -sn HEAD`,
`git log -1 --format=%ci` in each clone).

It is in the study as the **purest-class cousin with the least architecture** —
same bet as Gryphon (Cypher-family → trusted relational substrate, differential
validation) executed with *no* logical IR, string-typed everything, and dispatch
by substring sniffing. Where Cytosm shows an IR failing for want of semantics,
cyp2sql shows what the *absence* of any IR does: it is a natural experiment in
exactly the bug classes Gryphon's ladder was built against, several of which
appear here in their original, uncontained form. Its history then runs the
experiment twice: the author rewrote the whole system, and the rewrite's diff
shows precisely which diseases a rewrite cures and which it conserves.

Inclusion score (§2.2): relational-lowering relevance **maximal** (literal
Cypher→SQL-text transpiler + schema migration); source availability/readability
**high** (Apache-2.0, ~5.8k LOC of plain Java); history richness **medium** —
112 + 43 commits with an unusually honest message stream ("Messed around with how
WHERE is represented, still needs fixing though with OR", `cf01cc1`) but no issue
tracker activity; semantics documentation **low** — the README's output-module
caveat (`README.md:33-34`) is the only semantics writeup, and it is a confession.
Verdict: deep, Lens E and Lens H both rich; Lens T is a single (instructive)
artifact.

## Lens E — Execution ★ PRIMARY

### Bottom-turtle Q1 — Is there a logical-plan IR? **No — and its absence is directly generative of the top two bug classes.**

There is exactly one representation between Cypher text and SQL text:
`DecodedQuery`, a clause bundle (`MatchClause` + `ReturnClause` + `OrderClause` +
`WhereClause` + skip/limit ints + the walker's flag bag)
(`clauseObjects/DecodedQuery.java:9-28`). It is a *record*, not a plan: no
operators, no scoping, no algebra, no place to hang an invariant.

Three design facts define the bottom turtle:

1. **The real parser is unused for structure.** An ANTLR parser generated from
   the openCypher grammar exists (`parsing_lexing/`, `README.md:24-26`), but the
   walker only harvests coarse flags and raw substrings — `hasCount` is "the
   RETURN text contains `count`" (`CypherWalker.java:66-77`), clause boundaries
   are found by `tokenList.indexOf("match"|"where"|"return")` and `subList`
   arithmetic (`CypherTranslator.java:24-71`), and the walker switches on
   hard-coded parent-rule indices 23/24/25/26 (`CypherWalker.java:42-59`).
   The parse tree is thrown away where it matters most.
2. **WHERE is destroyed as a structure at decode time.** `extractWhere` splits
   the raw lowercased WHERE string on `" and "`/`" or "`
   (`CypherTranslator.java:476-494`), recognizes exactly six comparison
   operators by substring test (`:505-523`), and then **folds each predicate
   back into the matched node's/relationship's inline-property JSON** as a
   sentinel-token string — `eq#v#qe`, `ne#v#en`, `lt#v#tl`, `gt#v#tg`,
   `le#v#el`, `ge#v#eg`, multi-predicates chained with `~and~`/`~or~`
   (`CypherTranslator.java:552-588`; decoded back out in
   `TranslateUtils.getProperWhereValue:111-140`). After decode, *the query has
   no WHERE clause* — it has decorated pattern properties, and the lowering
   re-derives boolean structure by substring-matching property names against
   the component strings (`TranslateUtils.java:40-51` —
   `x.contains(entry.getKey())`, so a property whose name is a substring of
   another mis-associates its AND/OR; components are HashMap keys, so duplicate
   predicates collide, `WhereClause.java:11-12`).
3. **Cross-binding predicates are inexpressible.** Because a predicate must be
   filed under one node's property bag, `a.x = b.y` has nowhere to live; only
   `binding.prop <op> literal` survives decode. NOT, parentheses, IS NULL, and
   every operator beyond the six fall through *silently* (see Q4).

What an IR would have bought them is visible in the failure record: the WHERE
representation was born already broken for OR (`cf01cc1`, message: "still needs
fixing though with OR"), churned through five fix commits (`80f43b3`, `d7eb967`
"Major refactor on how WHERE is converted", `a58aae9`, `985ed84`), and was the
headline item of the eventual full rewrite (successor commit `691ec72` "MAJOR
refactor to how WHERE clause dealt with - much more general now" — 13 files,
+257/−247, touching **every** lowering path: `MultipleRel`, `NoRels`,
`SQLTranslate`, `ShortestPath`, `SingleVarAdjList`, `TranslateUtils`, `WithSQL`,
`CypherTranslator`). That diffstat is the cost, in files, of an invariant smeared
per-path instead of held at a choke point. Verdict for Gryphon's question "is a
thin transpiler fine without an IR?": at *this* complexity (boolean structure,
multi-hop, aggregation) — no. The moment the language grew past
`prop = literal`, the string-typed representation collapsed, and the fix
required a rewrite.

### Bottom-turtle Q2 — Dispatch shape: many special-case paths, at two levels, plus a dead one

**Level 1 — the driver routes on raw query text.** Before any parsing:
`line.contains(" foreach ")` → ForEach path, `" with "` → WITH path,
`"allshortestpaths"` / `"shortestpath"` / `"iterate"` likewise
(`Reagan_Main_V4.java:297-309`), and UNION is handled by *string-splitting the
query* on `" union all "` / `" union "` (`Reagan_Main_V4.java:540-561`). The
WITH lowering is a string rewrite — `line.replace("with", "return")` — which
replaces **any** occurrence of the substring, not the keyword
(`Reagan_Main_V4.java:456,483`). Any identifier or literal containing these
substrings misroutes the whole query.

**Level 2 — `SQLTranslate.translateRead` routes on IR shape**
(`SQLTranslate.java:37-50`): no relationships → `NoRels`; exactly one
variable-length relationship → **one of two entirely different lowerings chosen
by CLI flag** (`-tc` → `SingleVarRel`, transitive-closure table + `CREATE TEMP
VIEW`s; default → `SingleVarAdjList`, unrolled per-depth CTE chain over the
adjacency array with `unnest`); everything else → `MultipleRel`. A GROUP BY is
bolted on afterward only when `hasCount && items>1` (`SQLTranslate.java:48-49`),
with an in-code confession: *"Note - not entirely sure logic is correct for this
method, needs more testing"* (`SQLTranslate.java:238-241`).

**The dead path.** `SingleVarRelExtended` (depth > 5 var-length) is disabled by
a commented-out call site (`SingleVarRel.java:35-38`) and is left in the tree
**unfinished**: its final SELECT emits the literal string `"SELECT "` and
returns (`SingleVarRelExtended.java:57-60`), and its join clause compares a
table alias to a column (`n1 = e1.idl`, `:42-47`). An abandoned executor path,
syntactically broken, kept compiled and one comment away from dispatch.

**Did history have a "we unified the executor" refactor?** Not inside this
repo — the unification *was the successor project*. The DTG rewrite renamed
`clauseObjects` → `intermediate_rep` (the IR became a named concept), introduced
`AbstractConversion`/`AbstractTranslation` superclasses over the conversion and
lowering families (`cyp2sql-dtg/src/main/java/query_translation/sql/
conversion_types/AbstractConversion.java`, `utilities_sql/AbstractTranslation.java`),
made WHERE first-class (`CypWhere` with `bracketing` and `boolOp` fields —
`cyp2sql-dtg .../intermediate_rep/CypWhere.java:26-68`), added an exceptions
package (`DQInvalidException`, `ConversionSQLException`; commit `d11280d` "More
sensible exceptions added"), and grew NOT / IN-list / ANY / sum-avg aggregates
(`99e12fb`, `57a25cb`, `e151251`, `a196fcc`). **And yet**: the sentinel-token
value channel survived the rewrite verbatim (`cyp2sql-dtg .../TranslateUtils.java:127`
still mints `eq#…#qe`), and so did the count-based validation
(`cyp2sql-dtg .../C2SMain.java:355`). A rewrite conserves whatever the
validation net does not reject — their net checked cardinality, so the
representation disease and the proxy oracle both crossed the rewrite intact.

### Bottom-turtle Q3 — Where are invariants enforced? **Nowhere central; mostly nowhere.**

- **Parameterization: none.** Every literal is inlined into SQL text; string
  values are quoted by *stripping* single quotes rather than escaping them
  (`TranslateUtils.java:137`, `v.replace("'", "")` — silently corrupts data
  containing apostrophes), while the schema-load layer uses a different policy
  (`'`→`''`, `SchemaTranslate.java` `performPreProcessFile`, the
  `line.replace("'", "''")` pass). Two quoting regimes at two layers, neither a
  choke point.
- **Case: destroyed globally.** The whole WHERE clause is lowercased at decode
  (`CypherTranslator.java:472`) and every literal value again at fold-in
  (`:563-583`), so `name = "Alice"` compiles to `name = 'alice'` — a silent
  wrong answer on case-sensitive data. It was "fixed" in October 2016
  (`8a09f4a` "Fixed capital letter issue") **on the comparator side**: the
  Neo4j driver lowercases its own output before diffing
  (`CypherDriver.java:80,95`). The invariant was never restored; the oracle was
  bent to match the bug.
- **Read-only: no such concept.** CREATE/DELETE translate to INSERT/DELETE SQL
  (`SQLTranslate.translateInsert/translateDelete:65-206`), and *read* queries
  emit DDL — `CREATE TEMP VIEW` for var-length and WITH lowerings
  (`SingleVarRel.java:114,130`; `SQLWith.java:17`) — so the executor must pass
  arbitrary statements and re-discriminates them by *prefix sniffing* the
  generated SQL (`Reagan_Main_V4.executeSQL:507-527`: startsWith
  `CREATE`/`INSERT`/`DELETE` else select). One string channel for reads,
  writes, and DDL.
- **Result normalization: the one shared tail, and it has its own bug.**
  ORDER BY / OFFSET / LIMIT are appended uniformly after dispatch
  (`SQLTranslate.java:52-59`) — the only choke point in the system — but
  `obtainOrderByClause` fabricates table aliases by *counting order items*
  (`n0` + a counter incremented once per ORDER BY item,
  `SQLTranslate.java:219-230`), so `ORDER BY a.x, a.y` emits `n01.x, n02.y`,
  and the count branch hardcodes `count(n01)` (`:224`). Even the choke point
  resolves bindings by positional arithmetic instead of by name.
- Alias/binding resolution generally is positional arithmetic over the pattern:
  CTEs are named `a,b,c…` by relationship index with columns `a1/a2`
  (`MultipleRel.java:15,38-44`), aggregation picks its argument by
  `posInClause == 1 ? "a1" : "a2"` (`MultipleRel.java:228-250` — correct only
  for two-node patterns, `break`s after the first aggregate), and return items
  map to `n0<k>` via seen-so-far counters (`MultipleRel.java:252-286`,
  `SQLTranslate.obtainGroupByClause:245-271`). Every path re-derives this
  arithmetic independently.
- The lowering even reads **schema metadata files from disk mid-lowering** —
  `meta_tables.txt` on every label lookup (`TranslateUtils.getLabelType:161-190`,
  substring-matched: `line.contains(type)`), `meta.txt` to expand a bare node
  into GROUP BY columns (`SQLTranslate.java:260-266`) — and contains a
  **dataset-conditional hack in the lowering itself**: property `name` is
  emitted as an `ARRAY[…]` literal iff the database name starts with `"opus"`
  (`TranslateUtils.java:31-32`). Special-case dispatch rot in its terminal form.

### Bottom-turtle Q4 — Where does fail-closed live? **Loud on syntax, silent on semantics.**

Parse-*shape* errors do throw: `RELATIONSHIP STRUCTURE IS INVALID`
(`CypherTranslator.java:379`), `WHERE CLAUSE MALFORMED` when a predicate's
binding matches no node/rel (`:549`), `RETURN/ORDER CLAUSE MALFORMED`
(`:660,693`), empty MATCH/RETURN (`SQLTranslate.java:34-35`). But *semantic*
acceptance-then-ignoring — the exact envelope-WHERE bug shape — occurs at six
distinct sites:

1. **WHERE components with any unrecognized operator are silently dropped**:
   the six `clause.contains(" = ")`-style branches have no else; a component
   matching none of them simply vanishes from the query
   (`CypherTranslator.java:499-524`). `WHERE n.age >= 21 OR n.vip` loses the
   second disjunct with no error.
2. **OPTIONAL MATCH is parsed to a flag that is never consumed** — `hasOptional`
   is set (`CypherWalker.java:33-36`) and used exactly once, in a `println`
   (`:107`); the query lowers as a plain inner MATCH. Silent semantics change,
   zero alarm.
3. **Variable-length edge-type constraints are discarded at parse**:
   `extractVarRel` returns `CypRel(id=null, type=null, …)` regardless of what
   was written (`CypherTranslator.java:590-607`), and both var-length lowerings
   traverse type-agnostic structures (`tClosure` / `adjList_from` carry no type
   filter — `SingleVarRel.getStepView:113-120`, `SingleVarAdjList.java:49`).
   `-[:KNOWS*1..3]->` silently matches paths through *any* relationship type.
4. **Direction is computed and never used in the adjacency-list path**:
   `SingleVarAdjList.translate` derives `direction` (`:16-29`) and then never
   references it — a left-pointing var-length query lowers identically to a
   right-pointing one. (The `-tc` path does branch on direction,
   `SingleVarRel.java:44-52` — the two user-selectable strategies disagree on
   semantics.)
5. **Unbounded `[*]` is silently rewritten to `*1..100`** — in-code comment
   "hack that deals with arbitrary long paths"
   (`CypherTranslator.java:593-595`).
6. **CREATE assumes exactly two nodes** — `translateInsertNodes` loops
   `for (int i = 0; i < 2; i++)` (`SQLTranslate.java:123`); a one- or
   three-node CREATE emits wrong SQL without complaint.

Nothing structural prevents any of this: acceptance is decided by what a path
happens to read from the clause bundle, and the bundle cannot know whether its
fields were consumed. This is the strongest single argument in the corpus for
Gryphon's apply-or-reject dispatch rule being *load-bearing architecture* rather
than hygiene.

### The join/traversal lowering (k-hop, var-length, OPTIONAL, aggregation)

- **k-hop**: one CTE per relationship — `WITH a AS (SELECT n1.id AS a1, n2.id
  AS a2, e1.* FROM <label-table> n1 INNER JOIN e$TYPE e1 ON n1.id=e1.idl INNER
  JOIN <label-table> n2 ON e1.idr=n2.id [WHERE pushed predicates]), b AS (…)`,
  then an outer SELECT over a comma cross-join of `nodes n0k` tables plus the
  CTEs, correlated by an equality chain `a.a2 = b.b1 AND …`
  (`MultipleRel.java:34-98,335-351,380-493`). Alphabet-indexed CTE names cap
  patterns at 26 relationships (`MultipleRel.java:13-15`).
- **Undirected edges**: `UNION ALL` of both directions *inside* the CTE
  (`MultipleRel.java:73-89`) — clean, and the one place the lowering is
  genuinely compositional.
- **Predicate placement**: inline props, label predicates, and folded WHERE
  fragments are pushed into each CTE leg (`obtainWhereInWithClause`,
  `MultipleRel.java:111-174`); labels on the catch-all table are matched with
  `label LIKE '%<name>%'` over a comma-joined label string
  (`TranslateUtils.genLabelLike:149-159`) — substring semantics, so label
  `actor` matches a node labeled `benefactor`. Documented drop/mis-scope bugs:
  the silent WHERE-component drop (Q4.1) and the whole `cf01cc1`→`691ec72`
  WHERE arc (Lens H).
- **Var-length**: two rival strategies, user-selected (Q2). `-tc`: temp views
  over a precomputed `tClosure(idl,idr,depth)` bounded by
  `depth BETWEEN low AND high` (`SingleVarRel.java:113-120`). Default: an
  unrolled chain of per-depth CTEs over `adjList_from` with
  `unnest(rightnode)`, UNION-ALL-ing layers `low..high`
  (`SingleVarAdjList.java:34-65`). Both drop the edge-type constraint; the
  default drops direction.
- **OPTIONAL MATCH**: not lowered at all (Q4.2). No LEFT JOIN ever appears —
  the COUNT-inflation trap Gryphon footgunned is unreachable here because the
  feature is silently absent rather than present-and-wrong.
- **Aggregation**: `count`→`count()`, `collect`→`array_agg` (commit `5b05c0c`),
  with argument selection by clause position (`a1`/`a2`,
  `MultipleRel.java:228-250`) and GROUP BY synthesized by re-reading `meta.txt`
  for a bare node's column list (`SQLTranslate.java:260-266`) under the
  confessed-uncertain logic (`:238-241`).
- **shortestPath**: unrolled BFS CTEs carrying `Depth`, `Path` arrays, and
  `Start` (`SQLShortestPath.java:12-77`); termination rests on the syntactic
  depth bound, not on cycle checks against `Path`.

### Row-inflation defenses

The multi-hop anti-duplication guard is an inequality chain between *adjacent*
hop endpoints — `a.a1 != b.b2 AND …` — plus an add-on for repeated bindings
marked, in the code, **"EXPERIMENTAL LOGIC!"** (`MultipleRel.java:453-487`).
This is node-uniqueness, not Cypher's relationship-uniqueness: it
simultaneously *over*-restricts (legitimate node-revisiting paths are dropped)
and *under*-restricts (duplicate edges between non-adjacent hops survive), and
it only relates hop *i* to hop *i+1*. Cypher's actual no-repeated-edge
semantics is not implemented anywhere. The multi-rel fix cluster (six commits,
Lens H) is largely the churn of this arithmetic. For DISTINCT, dedup is the
SELECT-level keyword only (`MultipleRel.java:203`). Aggregates ride the same
cross-join, so any correlation slip inflates counts — with only the
cardinality-differential (Lens T) standing between the slip and a green run.

### NULL / 3VL

**Absent as a concept.** No `IS NULL` surface, no null-literal semantics, no
3VL reasoning anywhere in the lowering (no null token appears in
`CypherTranslator`'s operator handling, `:499-524`). Instead the *comparison
harness makes nulls invisible*: the Neo4j writer skips values whose string is
`"null"` (`CypherDriver.java:80-81`) and the Postgres writer skips SQL NULLs
(`DbUtil.java:102`). The README names "treatment of NULL" as a known
output-comparison caveat and moves on (`README.md:33`). Net: the entire null
bug class was defined out of observability rather than handled — the polar
opposite of Gryphon's specified 2VL/3VL boundary + TLP probe
(`doc-gryphon-testing-philosophy.md` §The frontier).

### Type handling

Column types are *inferred from the data* at schema-migration time by
`Integer.parseInt` attempts over observed values
(`PerformWork.java:116,184,235,256`; `mono_time` special-cased to BIGINT,
`InsertSchema.java:266`). The query side then quotes **every** literal as a
string (`TranslateUtils.java:137`) and defers to Postgres's implicit coercion
of unknown-typed literals. Consequences: a column that happened to contain one
non-numeric value becomes TEXT, and every numeric comparison against it
silently goes lexicographic (`'9' > '30'`); a numeric column keeps working by
coercion until the day it doesn't. Row-dependent schema + coerce-everything is
the exact posture Gryphon's schema-as-oracle rejection
(`req-grid-traversal-lang-type-strictness`) exists to foreclose.

### Determinism / ordering

ORDER BY is appended only when the query asked for it; `SKIP`/`LIMIT` are
emitted as bare `OFFSET`/`LIMIT` with no ordering guarantee
(`SQLTranslate.java:55-58`) — nondeterministic pagination. No NULLS
FIRST/LAST, no tiebreaks. The differential harness sidesteps the whole issue by
comparing row *counts* (Lens T), and the README lists "differences in ways that
sorting occurs" as a reason file-diffs can't be trusted (`README.md:33`).
Gryphon treating LIMIT-without-ORDER-BY as the one deliberate, documented
oracle skip is the disciplined version of what is here an unexamined hole.

### ★ Transferable to Gryphon

1. **Predicate-conservation as a structural invariant.** Their #1 bug shape —
   accepted-then-ignored WHERE material (Q4.1, plus the whole fold-into-props
   arc) — is the parser-level twin of envelope-WHERE. The transferable move is
   a *conservation check at one choke point*: every predicate leaf in the AST
   must be consumed by exactly one lowering site or the query rejects.
   Gryphon's dispatch collapse made single-hop apply-or-reject; a predicate
   ledger makes the property global and future-proof (OPP-1).
2. **Consumed-or-reject for every AST attribute.** `hasOptional` never read;
   `direction` computed then dropped; var-rel `type` discarded at parse. The
   generalization: any parsed attribute a lowering path does not consume is a
   loud rejection, mechanically enforced, not a per-path courtesy (OPP-2).
3. **One lowering per construct — rivals must replace, not fork.** The
   CLI-selected tclosure/adjList pair quietly disagrees on direction semantics
   (Q4.4). When Gryphon's variable-length seam (E1) grows, alternative
   strategies must supersede through the same corpus + oracle, never ship as a
   parallel path (OPP-3).
4. **Anti-lesson in normalization**: never bend the comparator to the
   translator (case-folding, null-skipping). Gryphon's identity-based envelope
   comparison already embodies the fix — hold that line.

## Lens T — Testing

- **Oracle model: a true differential oracle with a proxy comparison
  relation.** Every query in the corpus runs on both Neo4j (Bolt driver) and
  Postgres, and the harness *does* hard-fail the run on divergence
  (`translationFail` → `System.exit(1)`, `Reagan_Main_V4.java:362-368`) — the
  right instinct, seven years before it was fashionable. But the relation is
  `numResultsNeo != numResultsPost` — **row-count equality**
  (`Reagan_Main_V4.java:334`) — with full content equality applied *only* to
  `count(…)` queries via file diff (`:338-343`). A translation returning the
  right number of wrong rows is green. This is Gryphon's SQL-scrape
  false-green (`doc-gryphon-testing-philosophy.md` §4) in cardinality form,
  and the README states the proxy choice openly: exact output comparison "is
  not wholly accurate due to … encoding differences, differences in ways that
  sorting occurs, treatment of NULL. Thus, the files also contain an indicator
  … how many records were returned. This is a quick way of checking"
  (`README.md:33-34`).
- **The comparator is bent to known translator bugs**: Neo4j output lowercased
  (`CypherDriver.java:80,95`) because the translator destroys case
  (`CypherTranslator.java:472,563`); nulls skipped on both sides
  (`CypherDriver.java:81`, `DbUtil.java:102`). The oracle was made to agree
  with the defect instead of the defect being fixed — the precise inversion of
  the Gridkin oracle-assertion requirement's "never trust a captured oracle you
  didn't read" (`spec-gridkin-v0.md`, gryphon_playground plugin repo).
- **Failure amnesty**: queries whose SQL errors are added to a `denyList` and
  skipped for the rest of the evaluation (`Reagan_Main_V4.java:67,289,326`) —
  crashes don't fail the campaign, they shrink it.
- **The harness can silently shrink its own corpus**: query files are
  shuffled by inserting lines into a `TreeMap<Integer,String>` keyed by
  `r.nextInt(1000)` — key collisions overwrite queries
  (`Reagan_Main_V4.java:184-205`). No count-conservation check downstream.
- **Regression capture: zero.** A JUnit harness existed in October 2016
  (`851f8ef`, `8e0b2ea` "JUnit running on Cypher and PG output",
  `src/test/java/main_area/Cyp2SQLTest.java` added) and is gone at HEAD (no
  `*Test*.java` in the tree — `find` at clone SHA). The successor's entire
  test suite is one method that re-runs the differential corpus
  (`cyp2sql-dtg .../C2SBenchmarkTest.java:48-66`). None of the ~38 fix commits
  pins its bug with a test.
- No fuzzing, no metamorphic checks, no shrinking, no coverage gates, no TCK
  usage (the grammar is openCypher's, `README.md:25`, but no TCK scenarios).
- **★ Transferable to Gryphon**: nothing to import — every rung here is one
  Gryphon already has in stronger form (identity-compared model oracle vs
  count proxy; regression-locking scenarios vs none; loud-on-divergence is
  shared). What transfers is the *negative print*: (a) a differential harness
  with a proxy relation converges the system to "right cardinality," not
  "right answer" — cited as external validation of principle #4 (check the
  answer, not the artifact); (b) comparator normalization is where silent
  divergence goes to hide — Gryphon's envelope-identity comparison should
  stay free of any "tolerance" transforms. One candidate gap-check: their
  corpus-shrink bug argues for asserting scenario-count conservation through
  any Gridkin corpus transformation — but the coverage ledger's bidirectional
  drift guard (the Gridkin TCK-coverage ledger requirement) already plays that role
  (recorded as reject-with-reason, OPP-6).

## Lens H — History

**Scale**: 112 commits, 1 author (Oliver Crawford), 2016-10-04 → 2017-09-10
(`git log --reverse --format=%ci | head -1`; `git log -1 --format=%ci`); no
issues/PR trail. Successor: 43 commits, 2 authors (Crawford 40, Lucian
Carata 3), public history 2017-08-02 → 2017-08-31 — four weeks (final commit
`85be7ec` "reorganize repo for github push" suggests earlier offline
development), and then it too stopped. 38/112 primary commits (34%) mention
fix/bug/issue/problem (`git log --grep`, `-i -E`).

### Bug taxonomy (class → count → representative)

| Class | ~Count | Representative commits |
| --- | :---: | --- |
| WHERE representation / conversion | 5 | `cf01cc1` (introduces sentinel encoding, confesses OR broken), `80f43b3`, `d7eb967` "Major refactor on how WHERE is converted", `a58aae9`, `985ed84` |
| Multi-relationship join chain (correlation/inflation) | 6 | `760dcc9`, `6f0efce`, `01c5698`, `919d4de`, `105f5eb`, `f7bc658` |
| Aggregation / WITH / GROUP BY / COUNT | 3 | `f7bc658` "Bug fixes for WITH, multiple rels, GROUP BY, COUNT", `5b05c0c`, `e041ccc` |
| Var-length strategy churn | 3 | `5f10499`, `03f3a4e` "Changed how transitive closure dealt with", `e1c4046` (adds the rival adjacency-list lowering) |
| Schema conversion / delimiters / labels | 4 | `3186e22`, `1f81d14`, `aaed759`, `653fc99` |
| Output-comparison / encoding / case | 3 | `8a09f4a` "Fixed capital letter issue" (fixed in the comparator), `f523984`, `aaed759` |
| Relationship direction | 2 | `ff676a8` "Fixed bug with direction of relationship", `760dcc9` |

The two dominant classes — predicate handling and multi-hop join correlation —
are exactly Gryphon's two ledger hotspots (predicate-lowering,
multi-hop join/row inflation, per `gryphon-findings-ledger`). On a system with
no IR and no per-path tests, they consumed roughly a third of all development
motion.

### Turning-point commits

- **`cf01cc1` (Nov 2016) — the original sin, self-documented.** The
  sentinel-token WHERE encoding lands with "still needs fixing though with OR"
  in the message. It was never fully fixed in this repo; `git log -S 'eq#'`
  shows the encoding's whole life (`cf01cc1` → `417f2b0`), and it survives in
  the successor at HEAD (`cyp2sql-dtg .../TranslateUtils.java:127`).
- **`d7eb967` (Dec 2016) "Major refactor on how WHERE is converted"** — the
  first attempt to pay the debt touches 4 lowering files + translator and
  still keeps the string encoding. Refactor-within-the-representation did not
  cure the class; three more WHERE fix commits follow.
- **`e1c4046` (Feb 2017) — dispatch growth by accretion.** The faster
  adjacency-list var-length lowering is added *alongside* the transitive-
  closure one behind a CLI flag rather than replacing it, forking semantics
  (direction handling differs — Lens E Q4.4) for the sake of a dissertation
  performance comparison. The fork is still there at HEAD
  (`SQLTranslate.java:39-44`).
- **`21f69a9`/`22679a4` (Sep 2017) — abandonment as the refactor.** "Temp
  change to README - major changes to come Sept 2017!" then "Update README.md
  and link to new repo." The unification Gryphon did *inside* its executor
  (single-hop collapse, −389 lines) this project could only do by starting
  over — and the successor's `691ec72` diffstat (13 files, every lowering
  path) records why: with invariants smeared per-path, the smallest honest
  fix *is* a rewrite.
- **The rewrite conserved the untested diseases.** Sentinel encoding and
  count-proxy validation crossed into the successor unchanged
  (`cyp2sql-dtg .../TranslateUtils.java:127`, `.../C2SMain.java:355`), while
  everything the author *knew* was wrong (WHERE structure, exceptions,
  missing operators) got fixed. A rewrite fixes what its author can name and
  conserves what the validation net silently accepts — Gryphon's model
  oracle + snapshot corpus is precisely the net that would have caught both
  survivors.

### Design-doc / RFC trail

None in-repo (the dissertation itself is not committed; the successor carries
LaTeX docs, `c910f70`, `46f0480`). Reasoning survives only in commit messages
and in-code confessions ("EXPERIMENTAL LOGIC!", "not entirely sure logic is
correct", "hack that deals with arbitrary long paths") — which are, to their
credit, unusually honest.

### Lifecycle lesson

A one-person, no-IR, no-regression-test transpiler hit its complexity ceiling
inside 12 months: the representation chosen in month 2 (`cf01cc1`) dictated a
full rewrite by month 11, and the rewrite — supervised, four weeks of public
history — also stopped. The contrast object is Gryphon's own history: the same two bug
classes arrived, but a committed corpus + independent oracle made the
structural fix (dispatch collapse) *safe to perform in place* rather than
requiring abandonment.

### ★ Predicted Gryphon hotspots

Their bleeding maps onto ours with almost no translation: (1) predicate
lowering — already Gryphon's top ledger hotspot; their record predicts the
*next* variant is accepted-but-unconsumed input on new paths, arguing for the
conservation invariant (OPP-1/OPP-2) before the next capability lands;
(2) multi-hop correlation/row-inflation — theirs came from positional alias
arithmetic; Gryphon's chain builder centralizes this today, so the risk
concentrates at the E1 variable-length seam where a *second* strategy would be
tempting (OPP-3); (3) aggregation scope arithmetic (their `a1/a2`-by-position
and GROUP-BY-from-metafile) predicts bugs wherever aggregation takes a path
distinct from the chain lowering.

## Net read

The biggest thing to steal is not a technique but a proof: cyp2sql is the
control group for every architectural bet Gryphon made. Same problem, same
substrate, no logical IR, dispatch by substring, invariants per-path, proxy
oracle — and the result was 34% of all commits spent re-fixing two bug classes
(predicates, multi-hop correlation) until the only remaining fix was a rewrite
that itself conserved the two diseases its count-based net couldn't see. The
transferable, structural move is **conservation invariants at one choke
point** — every predicate leaf and every parsed attribute is consumed or the
query rejects — which generalizes the single-hop collapse's apply-or-reject
rule to the whole executor and would have foreclosed all six of their silent-
ignore sites. The thing to avoid is equally sharp: never let the comparator
absorb a translator infidelity (their lowercasing/null-skipping laundered real
bugs into green runs), and never ship a rival lowering for the same construct
behind a flag. Credits: Gryphon's read-only-by-construction surface (their
read path emits DDL and shares one string channel with writes), ORM
parameterization (their quote-stripped inline literals), schema-as-oracle type
rejection (their infer-INT-from-data + quote-everything coercion), the
specified 2VL/3VL null boundary (their null class was defined out of
observability), and an identity-compared model oracle (their row-count proxy)
— five whole bug families that are expressible in cyp2sql and structurally
inexpressible in Gryphon today.
