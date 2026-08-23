---
name: build-gryphon-capability
description: Add a new capability (clause, predicate, operator) to the Gryphon graph query language. Use when extending Gryphon's grammar/AST/executor — e.g. a new WHERE operator, a new clause like SKIP, a new aggregate.
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(grep *) Bash(find *) Bash(ls *) Bash(git *) Glob Grep
argument-hint: <feature-name>
---

# Build a New Gryphon Capability

> **Consult the commandments first.** [`docs/doc-gryphon-commandments.md`](../../../docs/doc-gryphon-commandments.md) is the standing doctrine for Gryphon work — read the relevant MUST/SHOULD commandments (esp. §I Execution, §II Semantics, §IV Testing) before you extend the grammar/executor, and check the Forthcoming section in case your feature is a trigger that promotes a forthcoming commandment. GRY-PROC-6 ("a capability ships as one full cycle") *is* this skill. This skill cites commandment IDs at the steps they govern; it does not restate them — the commandments are the law, this is the procedure.
>
> **Five gates bracket the work.** (1) The **entry gate** — the Agent pre-flight checklist (commandments § *Agent pre-flight checklist*): the 8 questions it asks (which commandment IDs, what demand-shape, which spec owns it, what parsed facts are applied-or-rejected, which rung, what independent oracle, what prior art, which ledger moves) — run it before scoping. (2) The **[Independent LLM Review Gate](#independent-llm-review-gate)** — after the spec (Step 2), a *different* LLM sanity-checks the spec + plan before the human sees them and before any code. (3) The **[Plan Review & Approval Gate](#plan-review--approval-gate)** — present the plan (and the independent review's findings) and get the user's explicit sign-off *before any code*. (4) The **[Independent LLM Code Review Gate](#independent-llm-code-review-gate)** — after the code is written and the suites are green (Step 10), a *different* LLM stress-tests the *implementation* (it may execute code in a verified-isolated sandbox) before the branch is handed off. (5) The **exit gate** — the [Merge-readiness gate](#merge-readiness-gate-definition-of-done) before the branch is validation-ready. Steps are numbered sequence; gates are hard stops. **The two LLM-review gates are the same principle at two checkpoints** — an objective third-party model reviews the *design* (gate 2) and then the *implementation* (gate 4). And after the feature ships, a closing **[Post-Ship Retrospective](#post-ship-retrospective--the-self-improvement-step)** step turns the cycle's lessons into durable updates (a third *exit-interview* checkpoint for the same independent model) — the loop by which this skill improves itself.

You are extending Gryphon — TAP's canonical graph query language and the read path
that all graph-shaped queries route through. A Gryphon capability touches four
artifacts in a fixed order (grammar -> AST -> parser -> executor) and ships under
a validation contract (a spec requirement, Gridkin scenarios with oracle
expecteds, openCypher-TCK-mined corner cases, and `test_gryphon.py` tests).

This skill is the end-to-end process, distilled from the ORDER BY / LIMIT,
IN-list, and OPTIONAL MATCH features. Follow it in order. Each feature is **one
commit** — the full cycle (spec + grammar + AST + parser + executor + scenarios +
tests) lands together, never as a follow-up.

**Two modes.** The main path (Steps 1–10) builds a **new capability**. If instead a **wrong answer,
silent drop, or crash was found in an existing feature**, use [Bug-fix mode](#bug-fix-mode--a-gryphon-wrong-answer-was-found)
first (`GRY-TEST-7` — a Gryphon wrong-answer is never normalized).

## Authoritative Sources (read these first; do not guess from memory)

- **[`docs/misc/doc-dev-gryphon-wishlist.md`](../../../docs/misc/doc-dev-gryphon-wishlist.md)** —
  the prioritized wishlist (organized by demand-shape, not Cypher's TOC) and the
  validation contract. Read the bucket for your feature. Trust `git log` over its
  "Implementation Status" section if they disagree.
- **[`tap_grid/specs/spec-grid-traversal-language.md`](../../specs/spec-grid-traversal-language.md)** —
  the language surface: clause shape, predicate semantics, field paths, params,
  returns. Home for predicate-power requirements.
- **[`tap_grid/specs/spec-grid-traversal-execution.md`](../../specs/spec-grid-traversal-execution.md)** —
  the execution pipeline, compiler strategy, the SQL-capture seam, and the **lowering
  ladder** (`req-grid-traversal-exec-lowering`) — the rung discipline Step 6 must obey.
- **[`tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md`](../../specs/spec-grid-gryphon-multihop-aggregation.md)** —
  the extension clauses (multi-hop, NOT EXISTS, COUNT, ORDER BY, LIMIT, OPTIONAL
  MATCH). Home for new extension-clause requirements.
- **[`plugins/gryphon_playground/specs/spec-gridkin-v0.md`](../../../plugins/gryphon_playground/specs/spec-gridkin-v0.md)** —
  the Gridkin scenario format, runner contract, and oracle discipline.

If a spec contradicts the code, flag it to the user — do not silently work around it.

## Quick recipes — low-effort shapes

Most capabilities are 🟢 Low / 🟡 Medium and follow one of a handful of shapes. This matrix is the
fast path — the touch-points for the common small features — so you don't re-read the whole epic for
a one-operator add. Every recipe still runs Steps 1–10 and faces the merge gate; this just tells you
*where the edits land*.

| Shape | Grammar | AST | Executor | Watch-out |
| --- | --- | --- | --- | --- |
| New comparison **operator** (`field op value`) | extend the op terminal | extend `Comparison.op` `Literal` (no new leaf) | op→lookup entry in `_comparison_to_q` | lightest case — **no walker audit** (Step 4) |
| Simple **clause** (`SKIP`, `DISTINCT`) | new `_KW` terminal in the `clause`/`return` rule | field on `GryphonAST` / return clause | apply in the row-projection path (`qs[n:]`, `.distinct()`) | reject a duplicate at parse time (`GRY-LANG-4`) |
| **Scalar function** (`coalesce`, `size`, `toLower`) | a `function_call` rule | a `FunctionCall` node | map to the Django `Func` in projection/predicate | one fn at a time, on demand (H2) |
| **Simple aggregate** (`SUM`/`MIN`/`MAX`/`AVG`) | extend `aggregate_call` | reuse `AggregateReturnItem` | add to the `_compute_rows` annotation map (parallel to `COUNT`) | alias mandatory; groups implicitly |
| **Positive `EXISTS { }`** | mirror the `NOT EXISTS` rule | mirror the node | sign-flip `~Exists()` → `Exists()` on the anti-join path | reuses existing correlated-subquery machinery |
| **New `Predicate` leaf** (different shape, e.g. `IN`-list) | new rule | new dataclass in the `Predicate` union | **audit every walker** — `_flatten_conjunction`, `_apply_comparison`, `_apply_typescan_predicate`, `_filter_predicate_for_bindings`, `_collect_params_from_predicate` | the heavy case — a missed walker silently drops the leaf |

## Step 1: Orient and Scope

> **⚠️ Reachability is NOT this skill's work.** Variable-length paths (`-[*n..m]-`) and
> `shortestPath` are 🔴 Very-High and do **not** run through this capability skill. Reachability is
> planned via grid-native **named paths** — their own spec/design track
> ([`grid-native-paths-notes.md`](../../../docs/misc/grid-native-paths-notes.md)); `shortestPath` /
> centrality belong to the analytics-backend track
> ([`doc-gryphon-networkx-opportunity.md`](../../../docs/misc/doc-gryphon-networkx-opportunity.md)).
> If the request is reachability-shaped, **stop and route it to the right track**. Today `*n..m`
> correctly parses-then-rejects — keep it that way; do not "just add" a recursive CTE here.

0. **Confirm it's a build, not a non-need (structural-credit check).** Before scoping,
   check whether TAP's *typed data model already answers the request* — a recurring
   pattern is that a "missing Cypher feature" is a feature Gryphon doesn't need because
   the model answers it structurally (export → the grift envelope; schema description →
   the entity/type endpoints; `labels()`/`type()`/`keys()` → `entity_type` + `dimensions`
   + `edge_type` on the spine; reachability → named paths). Consult
   [`doc-dev-gryphon-vs-cypher.md`](../../../docs/misc/doc-dev-gryphon-vs-cypher.md)
   (Ledger A credits) and [`doc-gryphon-feature-demand.md`](../../../docs/misc/doc-gryphon-feature-demand.md)
   (§3.6, §7). If the model already answers it, the "feature" is documentation of an
   existing credit, not a build — stop here.
1. **Source-check the current behavior before trusting any doc claim (`GRY-PROC-2`).** Docs drift;
   a claim that a shape is "shipped" / "rejected" / "parses" is a *hypothesis* until confirmed
   against the code. Check **grammar** (`grammar.lark`), **executor** (`executor.py` — does it
   *apply* or *reject*?), **tests** (`test_gryphon.py`), and **Gridkin status** before scoping.
   The scar: bounded `*1..3` was once documented as "shipped" but the executor
   *parses-then-rejects* it — a source-check caught the overclaim. Verify, don't inherit.
2. **Priority comes from feature-demand; shape comes from the wishlist.** When they conflict,
   [`doc-gryphon-feature-demand.md`](../../../docs/misc/doc-gryphon-feature-demand.md) is the
   **sequencing authority** — it is newer and re-sequenced (`WITH` first, `COLLECT` before the
   numeric aggregates, `UNWIND` promoted, `CALL` omitted, reachability via named paths) — and its
   §2 **Difficulty** rating tells you what to brace for (a 🔴 Very-High feature is not a
   single-cycle capability; re-scope or escalate). The
   [wishlist](../../../docs/misc/doc-dev-gryphon-wishlist.md) supplies the **implementation shape**
   (the bucket's *What / How it touches the executor / validation contract size*). Read the
   feature's row in feature-demand §2, then its bucket in the wishlist.
3. **Scope v0 tight.** Implement the demand-shape and nothing wider. The wishlist
   and the existing extension specs model this: ship the shape a real dashboard
   needs, reject everything else *with a clear error*, and name each rejected
   shape as a `Future` bullet. A silently-ignored construct is a bug; a clearly
   rejected one is a contract.
4. Decide which spec owns the requirement: language-surface predicates ->
   `spec-grid-traversal-language.md`; extension clauses -> the multihop-aggregation
   spec.
5. Note the openCypher TCK feature folder you will mine in **Step 8** (e.g.
   `tck/features/clauses/optional-match/`).

State the agreed v0 scope before writing code — it becomes the spec requirement.

## Step 2: Spec First

The spec requirement is written **before** any grammar, AST, or executor code — the
v0 scope agreed in Step 1 *is* this requirement. The spec is the canonical source of
truth; the implementation is downstream of it, never the reverse. Writing the
requirement first also forces the scope to be concrete before code makes it
accidentally concrete.

### Which spec owns it

- A new predicate, operator, or field-path capability — something that extends what a
  `WHERE` clause or a projection can *say* — belongs in
  `spec-grid-traversal-language.md`.
- A new clause or a new execution shape — `ORDER BY`, `LIMIT`, `OPTIONAL MATCH`, an
  aggregate — belongs in `spec-grid-gryphon-multihop-aggregation.md`.

If unsure, find the nearest sibling capability and put the new requirement where it
lives.

### The requirement, part by part

This is the trodden path: almost every Gryphon capability is a rung-1 feature (pure
ORM lowering — see Step 6) and follows exactly these six steps.

1. **Requirements-table row.** Add a row to the owning spec's `## Requirements`
   table — the `RID` (`req-grid-traversal-lang-<x>` for the language spec,
   `req-grid-gryphon-<x>` for the multihop-aggregation spec), a linked name, a
   `Status`, and a one-line Notes summary.

2. **The requirement section — match the owning spec's local conventions.** Do not
   invent a section the sibling requirements do not use. The multihop-aggregation
   spec uses `Implementation` / `Development` / `Acceptance Criteria` / `Future`.
   The language spec uses `Background` / `Implementation` / `Examples` /
   `Acceptance Criteria` / `Future`, sometimes with a `Status Details` subsection.
   Read a neighbouring requirement in the same file and mirror its shape.

3. **`Implementation`** states three things concretely: the grammar addition (the
   rule, in grammar syntax), the AST shape (the new dataclass(es)), and **which
   executor path the feature lands in and which lowering rung it uses**. State the
   rung explicitly *even when it is rung 1* — "lowers to rung 1: ORM `QuerySet`
   composition" is one sentence, and it turns the lowering choice into a reviewed,
   recorded fact rather than a silent default. Per `req-grid-traversal-exec-lowering`,
   rung 1 is the expectation; saying so out loud is the cheap half of keeping it the
   expectation.

4. **The scope rationale** — `Development` in the multihop-aggregation spec,
   `Background` in the language spec — explains *why the v0 scope is what it is*:
   what was deliberately left out, and what demand signal would pull it in. This is
   where Step 1's scoping decision is written down, so a future reader cannot mistake
   a deliberate omission for an oversight.

5. **`Acceptance Criteria`** — an ACID table with **one ACID per testable behavior,
   including every rejection case**. If the executor rejects an out-of-scope shape
   with an error (Step 6), there is an ACID for that rejection. The ACID table is
   what the Gridkin `covers` arrays and the `test_gryphon.py` tests trace back to.

6. **`Future`** — a bullet list naming **every** deferred shape, so the v0 boundary
   is legible. If the feature was previously a bullet under another requirement's
   `Future`, update that bullet to point at the new RID rather than leaving a
   now-stale "this is future work" note.

### When the feature needs a rung above 1

Most do not — rung 1 is the default and covers essentially every foreseeable
capability. But if Step 6 will lower to rung 2 or higher — a `Func`/`Expression`
subclass, a `RawSQL` fragment, a hand-written SQL template, a stored function — that
escalation is surfaced to the user *before* building (Step 6), and it puts extra
weight on this requirement:

- **State the rung and justify it in the spec text itself.** The requirement must say
  which rung the feature lowers to and why each lower rung cannot express the query.
  This justification is spec prose, not a PR comment — it is the durable record of an
  architectural decision.
- **Rung 4 (a hand-written SQL template):** document the per-construct lowering rule —
  which gryphon shape compiles to which SQL shape — so the emitted raw SQL is
  auditable from the spec, per the `req-grid-traversal-exec-lowering` Future note.
- **Rung 5 (a stored function):** the function is its own first-class tracked artifact
  and gets its **own** spec requirement plus a migration — it is not a footnote on the
  capability's requirement. Check the rung-5 preconditions in
  `req-grid-traversal-exec-lowering` (cross-query reuse, tracked-artifact management,
  explicit cost acceptance).
- Confirm the requirement records that the five rung invariants
  (`req-grid-traversal-exec-lowering`) still hold at the chosen rung.

### When the feature reconciles an existing requirement

Not every feature adds a new RID. A capability sometimes closes the gap on a
requirement that already *claims* the behavior — the executor was simply behind
the spec. The OR / NOT combinators feature is the worked example: the
capability-docs slice found that `req-grid-traversal-lang-combinators` was
`Implemented` and claimed AND / OR / NOT, but the executor ran only AND.

When that is the shape, Step 2 **updates the existing requirement** instead of
adding a Requirements-table row:

- Do not mint a new RID. Bring the requirement's Implementation prose and ACID
  statuses into line with what the feature now actually delivers — so the spec
  stops overclaiming.
- The capability block for the affordance is *updated*, not created — typically
  dropping a now-false `:limitations:` line (see Step 6).

The capability-docs gap report (`spec-sphinx-capability-docs.md`,
`req-sphinx-docs-gap-tracking`) is the clean way to surface these: a block whose
`:status:` / `:limitations:` disagree with its `:implements:` requirement is
exactly this case.

## Independent LLM Review Gate

**STOP — a mandatory second opinion, before the human sign-off and before any code.** After the spec
requirement is written (Step 2) and the implementation plan is drafted, but **before** the [Plan
Review & Approval Gate](#plan-review--approval-gate) and **before any grammar / AST / parser /
executor code**, the spec + plan **MUST** be sanity-checked by an **objective third-party LLM — a
*different* model than the one doing the work.** Gryphon is the load-bearing read path; an important
feature landing wrong is expensive, and an author cannot see their own framing blind spots. This gate
is the human-process analog of the zero-shared-code model oracle (`GRY-TEST-2`) and the
authoring-independent-check discipline (`GRY-TEST-9`): a second independent reasoner catches the class
of error a self-review structurally cannot, and cross-checking a convention against an outside view is
the same instinct as `GRY-PROC-1` (prior art before invention).

**Why it is its own gate, not part of the human review.** The human approves; the independent LLM
*stress-tests*. They catch different things — the human owns product intent and scope authority; the
independent model owns "is this design actually sound, complete, and internally consistent." Running
the model review *first* means the human signs off already holding the second opinion, not instead of
it.

**How to run it:**

1. **Pick an independent reviewer.** **Codex is the current standard** third-party reviewer; the
   binding principle is *independence*, not a specific tool — any capable objective LLM that is **not**
   the model authoring the feature qualifies. (If the human is already running one on the side, use
   that response.)
2. **Hand it the two artifacts** exactly as the Plan Review Gate presents them: the **spec
   requirement** (RID + owning spec + the full Acceptance-Criteria table, including every rejection
   ACID) and the **implementation plan in your own words** (what-it-is / what-it-is-not with every
   rejected shape named; how-built with the grammar rule, AST node(s), executor dispatch path and
   **lowering rung**; how-tested mapped to the merge gate).
3. **Ask it to challenge, not rubber-stamp.** Direct it at the load-bearing choices: is the v0 scope
   boundary right; is the lowering rung the lowest that expresses the query; is the rejection set
   complete (every out-of-scope shape has an error, none silently dropped); are the null / determinism
   / JSON / envelope semantics sound; does anything in the plan contradict the commandments. A review
   that only says "looks good" has not been pointed hard enough — re-prompt it at the risky seams.
4. **Reconcile every material finding.** Surface the reviewer's response to the user (summarized or
   verbatim). For each material concern, either **fix it** (revise the spec / plan and, if the spec
   text changed, re-run this gate on the delta) or **record why it was declined** with a reason. A
   disagreement between the two models is a signal to slow down, not to average.

**Clearing the gate.** It clears only when (a) an independent-LLM review has actually been **run and
recorded**, and (b) its material findings are each **addressed or explicitly dispositioned**. A clean
review still must be run and its outcome noted — **skipping it is not permitted for a capability
build** (Steps 1–10), nor for a [bug-fix](#bug-fix-mode--a-gryphon-wrong-answer-was-found) that
changes semantics. Like the human gate, a rushed "skip the second opinion" does not clear it; hold the
line even if asked to hurry — the friction is the feature.

## Plan Review & Approval Gate

**STOP — a hard control, not a courtesy.** After the spec requirement is written (Step 2), the plan is
drafted, and the [Independent LLM Review Gate](#independent-llm-review-gate) has been run and its
findings reconciled, and **before any grammar / AST / parser / executor code** (Step 3+), present
*both* the **spec** and an **implementation plan** to the user and obtain **explicit, deliberate
approval of each**. Gryphon is the load-bearing read path; a feature landing wrong is expensive, so
this review is required and un-waivable-by-default.

**What "approval" means here — and what it does not.** Approval is a specific, affirmative sign-off on
the spec *and* the plan ("the spec looks right and the plan is approved — proceed"). It is **not**:

- silence, or moving on to another topic;
- a blanket, up-front "just build it / knock it out" issued *before* the spec and plan exist;
- a vague "go ahead" that does not indicate the spec and plan were actually read.

If all you have is a casual or pre-emptive "go," **do not treat the gate as cleared.** Say so plainly:
present the spec and the plan, note that this is a deliberate review control, and ask the user to
review and give an explicit sign-off on both. Hold this line even if asked to hurry — the friction is
the feature. (The user retains final authority: an *explicit, informed* "I've read the spec and plan,
approved" clears the gate. An assumed or hand-waved one does not.)

**Present these three artifacts:**

0. **The independent LLM review's findings** (from the [Independent LLM Review Gate](#independent-llm-review-gate)) — summarized or verbatim, with each material concern's disposition (fixed → what changed, or declined → why). The user signs off holding the second opinion, not instead of it.
1. **The spec requirement** (the Step 2 output) — the RID, its owning spec, and the Acceptance-Criteria
   (ACID) table, including every rejection ACID. Link it so the user can read it in place.
2. **The implementation plan, in your own words** (not a paste of the spec) — three parts:
   - **What it is, and what it is not.** Plain-language: what the feature will do, and an explicit
     statement of what it will **not** do — every rejected/deferred shape from the Step 1 in/out
     boundary named (e.g. DISTINCT: "`RETURN DISTINCT` over field projections; **not** `count(DISTINCT …)`,
     **not** envelope-mode DISTINCT"). A reader who never opens the spec should understand the scope.
   - **How it will be built.** The code approach in brief: the grammar rule, the AST node(s), which
     executor dispatch path and **lowering rung**, and the concrete touch-points (lean on the
     [Quick-recipes matrix](#quick-recipes--low-effort-shapes)).
   - **How it will be tested.** The validation plan mapped to the
     [Merge-readiness gate](#merge-readiness-gate-definition-of-done): which Gridkin scenarios (and
     their hand-authored oracle), the rejection tests (one per rejected shape), the path-coverage /
     no-`WHERE` test if it scans, the TCK folder to mine, and whether the fuzzer/TLP applies (row 10).

Revise and re-present on any feedback until the user explicitly approves **both** the spec and the
plan. Only then proceed to Step 3.

## Step 3: Grammar (`tap_grid/gryphon/grammar.lark`)

- Add the rule(s). New top-level clauses join the `clause` alternation; new
  predicate forms extend `comparison`.
- Keyword terminals are underscore-prefixed (`_ORDER_KW: /ORDER/i`) so lark
  discards them from the parse tree — the transformer then receives only data
  tokens. A non-underscore inline regex (`/null/i`) is **kept** as a child.
- Gryphon strings are **double-quoted** (`ESCAPED_STRING`); single quotes do not
  parse. Write `["a", "b"]`, never `['a', 'b']`.

## Step 4: AST (`tap_grid/gryphon/ast_nodes.py`)

- Add frozen dataclasses for the new nodes.
- If you add a clause: add a field to `GryphonAST` (default `None`/`()` so existing
  construction sites keep working) and extend `required_params()` to walk it for
  `$param` references.
- If you add a predicate leaf: add it to the `Predicate` union **and** handle it in
  `_collect_params_from_predicate`. Then audit every predicate walker in the
  executor (Step 5) — a new leaf type that a walker does not recognize is silently
  dropped.
- If you add a predicate **operator** rather than a leaf — a new comparison operator
  like `STARTS_WITH` — **extend the `Comparison.op` `Literal`** instead of adding a
  leaf. This is the lightest case: `Comparison` is already handled by every walker,
  so the only touch-points are the parser's operator normalization (Step 5) and
  `_comparison_to_q`'s op→lookup map (Step 6) — no walker audit. Reach for a new leaf
  only when the node carries a genuinely different shape (e.g. `InComparison`'s list
  value); a same-shape `field op value` predicate is an operator, not a leaf.

## Step 5: Parser (`tap_grid/gryphon/parser.py`)

- Add a transformer method per new rule; collect new clauses in `start()`.
- **Reject duplicate single-clauses at parse time** (`Only one ORDER BY ...`) — do
  not silently keep the first, which is the documented multiple-WHERE footgun.
- **`@v_args(inline=True)` token gotcha.** The transformer runs under
  `@v_args(inline=True)`. A rule whose grammar body is a bare inline regex
  alias (`value: /null/i -> null_val`) passes the matched token as a child, so the
  method **must** accept it: `def null_val(self, _token): ...`. Omitting the arg is
  the Finding-G class of bug — it parses fine in isolation and crashes only when
  that literal is used. Methods for underscore-prefixed terminals take no token.

## Step 6: Executor (`tap_grid/gryphon/executor.py`)

- **Lower to the lowest rung of the lowering ladder** (`req-grid-traversal-exec-lowering`
  in the execution spec) that expresses the query. The executor is rung 1 — ORM
  `QuerySet` composition — throughout, and staying there is the default and the
  expectation. Climbing (a `Func`/`Expression` subclass, `RawSQL`, a hand-written SQL
  template, a stored function) is a deliberate escalation, never a convenience: justify
  it in the spec requirement and the PR, and confirm the five rung invariants still hold
  at the new rung — read-only alias, bind-parameterized values, dimension scoping,
  canonical-envelope normalization, capture-seam visibility. If a feature appears to need
  a rung above 1, that is a design signal — surface it to the user before building it,
  do not quietly reach for raw SQL.
- Identify the dispatch path(s): the simple `_execute_ast` (type scan,
  hub-and-spoke, edge-type scan), the advanced `_execute_advanced` (multi-hop,
  NOT EXISTS, COUNT), or a new dedicated path. A genuinely new shape (e.g. OPTIONAL
  MATCH) gets its own `_execute_<feature>` and an early route in
  `execute_gryphon_raw`, wrapped in a `gryphon_stage("<label>")`.
- Apply the feature in **every** path that can reach it. ORDER BY / LIMIT had to
  land in both the type-scan projection and the aggregation path; a new predicate
  leaf must be handled in `_predicate_to_q` (the WHERE-tree-to-`Q` compiler),
  `_comparison_to_q`, `_flatten_conjunction` (the OPTIONAL MATCH AND-only split),
  and `_filter_predicate_for_bindings`, plus `_collect_params_from_predicate` in
  `ast_nodes.py`.
- **Reject out-of-scope shapes with a clear, actionable error** that names the
  supported form. Never silently ignore a clause. (`GRY-ARCH-3` apply-or-reject —
  an accepted-but-unused parsed fact is a silent-wrong-answer bug.)
- **Read variable scope from the AST / `bindings`, never opportunistically** (`GRY-SEM-6`).
  A predicate or projection resolves a variable through `_build_var_bindings` /
  `_filter_predicate_for_bindings`, not by grabbing whatever binding happens to sit in
  executor state — opportunistic name lookup is how a predicate silently binds to the
  wrong variable (the far-node-binding class).
- **Package results through the canonical shapes only** (`GRY-ARCH-11`). Emit the grift
  graph envelope (`{nodes, edges}` + spine / `data` / `display` lanes) or the row-projection
  shape — never a caller-specific result shape grown inside the executor. A consumer that
  needs a different view builds it outside Gryphon.
- **Keep the emitted SQL deterministic** (`GRY-ARCH-9`). Append a unique tiebreaker
  (`entity_id` / the group-by columns) to any `ORDER BY`; sort `pk__in` lists.
  Non-deterministic SQL makes the Gridkin snapshot flap.

### Capability block

A load-bearing affordance gets a `.. tap:capability::` block in a docstring at
its closest code anchor — per `spec-sphinx-capability-docs.md`
(`req-sphinx-docs-capability-blocks`). For a Gryphon feature:

- Author the block — or, for a reconciled requirement (Step 2), **update** the
  existing one — at the feature's anchor: the executor dispatch function, the
  AST node, whichever code site owns the claim.
- Carry the required metadata (`id`, `status`, `audience`, `affordance`,
  `implements`), a one-line affordance description, a worked `Example::` literal
  block, and a `:limitations:` line for any material caveat. Directive option
  values stay single-line within the 120-character limit.
- `covered-by` and the `Example::` query are sourced from the Gridkin scenario
  authored in Step 7 — fill them in once that scenario exists.
- A feature that reconciles an existing requirement updates that requirement's
  block: drop a now-false `:limitations:` line, refresh the body and example.
  The OR / NOT feature did exactly this to `cap-grid-gryphon-where`.

## Step 7: Gridkin Scenarios + Oracle Discipline

Author scenarios in `plugins/gryphon_playground/scenarios/<feature>.gridkin.json`
against a Tier-1 fixture. Use the `pg_*` / `PG_*` playground vocabulary only.

The **oracle discipline** is the point of Gridkin — do it exactly:

1. Hand-author the expected envelope JSON files by **computing the result yourself
   from the fixture data**, before running the executor. The expected file is an
   oracle, not a capture.
2. Run the runner in **assert mode** and read *every* failure:
   ```bash
   scripts/dc exec web uv run pytest plugins/gryphon_playground/tap_plugin/gryphon_playground/tests/test_gridkin.py -k <feature>
   ```
   A scenario whose only failure is `SQL: expected file missing` has a
   **content-correct** envelope. A scenario reporting `ENVELOPE MISMATCH` does not
   — fix your oracle (or the executor) and re-run. Do not proceed past Step 7.2
   until every failure is missing-SQL only.
3. Only then regenerate the SQL snapshots:
   ```bash
   scripts/dc exec -e GRIDKIN_UPDATE_SNAPSHOTS=1 web uv run pytest \
     plugins/gryphon_playground/tap_plugin/gryphon_playground/tests/test_gridkin.py -k <feature>
   ```
   Update mode rewrites the envelope files into canonical (indent-2) form and
   generates the `.sql.txt` snapshots.
4. **Eyeball every generated `.sql.txt`.** Confirm the JOINs, predicates, GROUP BY,
   ORDER BY, and LIMIT are what the query means — this is the second independent
   correctness check beyond the envelope oracle.

Pitfall: `git diff` does **not** show untracked files, so it cannot confirm an
oracle survived snapshot regeneration. Verify correctness in step 7.2 (assert mode,
before the files are tracked), never by diffing after update mode.

Every scenario needs a non-empty `covers` array of the RIDs/ACIDs it exercises;
the loader rejects a scenario file without it.

## Step 8: Mine the openCypher TCK

The TCK is a scenario **mine**, never a source. Per the wishlist's TCK workflow and
`feedback_borrow_from_oss_prior_art` (inspire, never copy):

1. Read the TCK feature folder for the corner-case *intents* — "what historically
   broke graph engines here" (empty list, single element, ties, NULL membership,
   zero-match rows, the WHERE filter-placement gotcha).
2. Author Gridkin scenarios in TAP vocabulary covering each retained intent. Skip
   Cypher-specific quirks that are not Gryphon's contract.
3. Set the scenario's `inspired_by` to the TCK folder path — an attribution
   breadcrumb. **No TCK query text, graph data, or expected results are copied** —
   everything is re-authored in `pg_*` vocabulary against hand-built fixtures.

## Step 9: `test_gryphon.py` Tests

Add to `tap_grid/tests/test_gryphon.py`:

- A **parser** test class — pure AST assertions, no DB: the feature parses,
  variants parse, duplicates/bad forms raise `GryphonParseError`.
- An **executor** test class (`@pytest.mark.django_db(transaction=True,
  databases=["default", "search_readonly"])`) — the **rejection cases** Gridkin
  cannot express (every out-of-scope shape from Step 1 raising
  `SearchExecutionError`), a positive smoke test, **and any corner that needs
  crafted data a shared Tier-1 fixture does not have** — e.g. a needle containing
  `LIKE` metacharacters — where the row is built inline rather than forcing a whole
  new fixture. Gridkin owns fixture-shaped breadth; `test_gryphon.py` owns crafted
  corners and error paths.
- For a feature that **scans or unions a set** (a type scan, bare `MATCH (n)`, a
  multi-clause union), add a test that asserts the result does *not* include what
  it must exclude — a no-`WHERE` or count-based assertion. Gridkin scenarios that
  all carry a `WHERE` can pass even when the scan is **too wide**: the filter
  incidentally hides the over-inclusion. Bare `MATCH (n)`'s edge-inclusion bug slid
  past all five of its filtered Gridkin scenarios and was caught only by a
  no-`WHERE` union test.
- If the feature **removes a rejection** (makes a previously-unsupported shape
  legal), grep `test_gryphon.py` for the existing test that asserts the old
  rejection — it will now fail. Delete it (the new behavior is covered by the
  feature's own tests) or repurpose it to assert the new behavior. This is the
  test-side of reconciliation (Step 2): the typeless edge scan had to delete
  `test_edge_type_scan_requires_typed_edge`.

Executor tests that scan a typed model (e.g. `MATCH (c:character)`) must create the
**backing model rows** (`Character.objects.create(...)`), not just `Entity` rows —
a type scan queries the typed model.

## Step 10: Lint, Test, Commit

```bash
scripts/dc exec web uv run black tap_grid/gryphon/ tap_grid/tests/test_gryphon.py
scripts/dc exec web uv run ruff check --fix tap_grid/gryphon/ tap_grid/tests/test_gryphon.py
```

Run the two suites **separately** — running them together hits a pre-existing
test-isolation quirk (transaction-mode DB reuse) that errors out unrelated tests:

```bash
scripts/dc exec web uv run pytest tap_grid/tests/test_gryphon.py -q
scripts/dc exec web uv run pytest plugins/gryphon_playground/tap_plugin/gryphon_playground/tests/ -q
```

**Hardening tools — run when the feature warrants (merge-gate rows 7 & 10):**

```bash
scripts/gryphon-coverage-ratchet   # executor branch/stage-coverage gate — a new dispatch branch must not drop below the floor (row 7)
scripts/gryphon-findings           # findings ledger — check no open finding touches your path; append a row if you fix one
scripts/gryphon-fuzz-campaign      # differential property fuzzer / TLP — REQUIRED only if the feature adds/changes predicate, null, or multiplicity semantics (row 10); a long soak is /gryphon-fuzz-soak
```

A 🟢 Low feature that adds no predicate/null surface (e.g. `SKIP`, `DISTINCT`) records "N/A — no new
predicate/null surface" for row 10 rather than running the fuzzer; it still runs the coverage ratchet.

Then flip the spec requirement Status to `Implemented`, and follow the doc-spec
sync rules in [`specs/spec-docs.md`](../../../specs/spec-docs.md) if any doc
references the RIDs you changed (`grep -r <RID> docs/`).

Commit the whole cycle as **one commit**. Keep terminal output ASCII-only.

## Independent LLM Code Review Gate

**STOP — the second mandatory second opinion: on the *code*, after it is written and green, before the
branch is handed off.** The [Independent LLM Review Gate](#independent-llm-review-gate) stress-tests the
*spec + plan*; this gate stress-tests the *implementation*. They are the same principle — an objective
third-party model, a *different* one than wrote the code — at two checkpoints, and they catch different
failure classes: the spec review cannot see an over-deletion, a lost error message, or a silently-dropped
branch, because none of those exist yet when it runs. The code is where the implementation defects live,
so the code gets its own independent reviewer (`GRY-TEST-2`, `GRY-TEST-9`).

**When it runs.** After Step 10 (lint clean, both suites green) and **before the branch is
validation-ready** (before the Merge-readiness gate). The reviewer inspects a *complete, green* change —
not a work-in-progress — so its findings are about real defects, not unfinished edges. Material findings
are folded back into the **same** commit (amend, not a follow-up), preserving `GRY-PROC-6`.

**The review packet — hand the reviewer everything it needs to inspect, without making it hunt.**
1. The **full diff** of the cycle, with **deletions called out explicitly** — a list of every function /
   class / block *removed*, so the reviewer scrutinizes removals as hard as additions (this is where the
   expensive bugs hide).
2. The **owning spec requirement** (RID + ACID table) and the relevant **commandments**, so the reviewer
   checks code against contract, not vibes.
3. The **local validation results** — which suites ran, pass/fail counts, and the byte-identical /
   snapshot-churn evidence if the change claims parity.
4. The **before/after set of defined symbols** in each touched module, so a removed-but-still-referenced
   symbol is trivially spotted.

**The standard review rubric — what the reviewer checks (a living checklist; every new lesson appends a
row).** Stated as failure modes we have actually hit, phrased so the reviewer *hunts* for each:
- **Over-deletion / collateral damage.** For every removed symbol: is it truly dead, or does a live
  caller remain? Was the deletion by-name, or did a line-range / block edit sweep up an interleaved
  helper it shouldn't have? *(Scar: a `sed` line-range delete removed three still-live bare-scan helpers;
  the module still parsed — a `NameError` is runtime-only — and only one suite exercised the path.)*
- **Silent-drop / apply-or-reject** (`GRY-ARCH-3`). Does every parsed construct still get applied or
  explicitly rejected? Did the change introduce a path that parses a clause then ignores it?
- **Circular parity evidence.** If the change claims "byte-identical" / "pure refactor," is the proof
  non-circular? Regenerated snapshots that overwrite expected results can *mask* a behavior change — the
  real proof is zero result-envelope diffs under the *old* expecteds, not green after a regen.
- **Preserved error-message / rejection contracts.** Did a refactor that re-routes a path drop or alter a
  rejection message a test or a user workaround depends on? *(Scar: routing RETURN projection through the
  WHERE path lost the display-lane "use the `extended` return layer" hint.)*
- **Single-suite coverage gaps.** Is any changed dispatch path covered by only *one* suite (e.g. Gridkin
  but not `test_gryphon`, or vice-versa)? Name it — a path with one net under it is one refactor away from
  a silent regression.
- **Rung discipline** (`GRY-ARCH-2/6`). Did the change stay at the claimed lowering rung? No smuggled
  `RawSQL` / hand-rolled IR where ORM composition suffices.
- **Null & determinism semantics** (`GRY-SEM-2`, `GRY-ARCH-9`). Null 2VL/3VL boundary preserved where
  touched; emitted SQL still deterministic (sorted `pk__in`, tiebroken `ORDER BY`).
- **Spec ↔ code alignment.** Does the code enforce every ACID, including the rejection ACIDs? Does any
  ACID claim a behavior the code doesn't deliver (overclaim)?
- Findings come back **categorized** — blocker / should-fix / nit — and **adversarial** (the reviewer is
  told to *find what's wrong*, defaulting to skeptical; a review that only says "looks good" was not
  pointed hard enough).

**Execution posture — arbitrary code, in a verified-isolated, disposable sandbox only.** Unlike the
spec-review gate (pure reasoning), this reviewer **MAY execute code** — run the suites, probe Gryphon
queries, write throwaway scratch scripts — because *observing* actual behavior catches wrong-answers that
reading cannot, and Gryphon's whole contract is "does it return the right rows." This is an independent
third oracle in the review loop (`GRY-TEST-1`, "check the answer not the artifact"). Execution is
permitted **only inside a sandbox verified to satisfy every precondition below** — an unverified
"playground" that quietly shares the real DB or secrets defeats the entire control, so verify *before*
granting execution, and **fall back to static-inspection-only if any precondition cannot be met**:

- **Disposable scratch DB**, seeded only with playground / Gridkin fixtures — **no production data, no
  real customer or plugin data.**
- **No secrets mounted.** In particular the shared `~/tap-secrets` mount MUST NOT be exposed — it is
  shared host state wired into every session; a reviewer with it holds every session's credentials.
- **No write access to any git remote** — no push credentials in the sandbox.
- **Restricted network egress** — no path to exfiltrate, and no reaching external services with ambient
  credentials.
- **Isolated, ephemeral stack** — own `COMPOSE_PROJECT_NAME` / ports / DB volume (the multisession
  worktree pattern), torn down after the review.

**Tree integrity — the reviewer inspects and executes in the sandbox; it does not edit the authoritative
source.** All execution happens in the disposable sandbox above, never as edits to the working tree under
review. The reviewer **MUST report whether it modified any file in the working tree** — the expected,
correct answer is *none*. If it did modify code (it should not have), it **documents exactly what and
why**, and those edits are treated as findings to be reviewed and either adopted deliberately or reverted
— never silently inherited. Before dispatching to the reviewer, record the cycle's commit SHA so drift is
detectable.

**Re-entry verification — confirm a clean, unchanged tree before hand-off.** When the authoring agent
returns to the same environment after the review, it **verifies the working tree is clean and matches what
it authored-and-reconciled**: `git status` is clean (no stray edits a reviewer or a sandbox process left
behind), and the cycle diff is byte-identical to the recorded pre-review SHA (`git diff <sha>` empty
outside the deliberately-folded-in fixes). Only a tree that matches is handed to the Merge-readiness gate.
**Any unexplained drift is a hard stop** — investigate its origin before proceeding; an unexpectedly
mutated tree is exactly the tamper / collateral-edit class this discipline exists to catch (the
tree-integrity sibling of the over-deletion scar above).

**Residual risks, named (not implied away).** Arbitrary-code-by-an-external-LLM is a real surface; sandbox
isolation *bounds* the blast radius, it does not eliminate the risk — if isolation is imperfect (an
accidentally-mounted secret, a shared host path, a reachable network service) the blast radius grows to
whatever leaks, which is why the preconditions are verified first, not assumed. Sending the diff to an
external LLM also *publishes* it (the code leaves the machine); acceptable here because the code is
repo-bound anyway, but it is a disclosure, not a private operation. These are the edges deliberately left
open in exchange for the independent-oracle value; a machine-enforced sandbox harness (and an automated
clean-tree check) are named future candidates, not built guarantees.

**Reconcile + clear.** Surface the reviewer's findings to the user (summarized or verbatim). For each
material finding: **fix it** (fold into the same commit; re-run the suites; if the fix changes semantics,
the spec-stage review may need a re-touch) or **record why it was declined**. The gate clears only when an
independent code review has actually been **run and recorded**, its material findings are each **addressed
or dispositioned**, the reviewer's tree-modification report is **recorded (expected: none)**, and re-entry
verification shows a **clean, unchanged tree**. Skipping it is not permitted for a capability build or for
a bug-fix that changes code — a rushed "skip the code review" does not clear it; hold the line even if
asked to hurry.

## Merge-readiness gate (definition of done)

A Gryphon capability is **done** — a *validation-ready branch* — only when every row below is
green. This is `GRY-PROC-6` ("one full cycle") expanded into a checklist; it defines *what must be
true of the feature*, not *how the promote happens*. **The promote mechanism** (which session runs
the full lane, what push flow advances `origin/main`) is owned by the multisession promote process
(`spec-dev-multisession.md` + the dev-validation gate) — do **not** bake a push flow into a Gryphon
feature. Hand off a validation-ready branch; let the promote process take it.

| # | Validation layer | Pass criterion | Commandment |
| :--: | --- | --- | --- |
| 1 | Spec requirement + ACID table | every behavior incl. **every rejection** has an ACID; Status→`Implemented` only once the rest is green | `GRY-PROC-6` |
| 2 | Parser tests | feature + variants parse; duplicate/malformed forms raise `GryphonParseError` | `GRY-LANG-4` |
| 3 | Executor rejection tests | every out-of-scope shape raises `SearchExecutionError` — one per rejection ACID | `GRY-ARCH-3` |
| 4 | Gridkin scenarios, **hand-authored** oracle | expecteds computed from the fixture by hand, verified in **assert mode before** snapshotting — never captured | `GRY-TEST-1/2/6` |
| 5 | Model-oracle agreement | scenario passes the zero-shared-code oracle, or a **loud** `OracleUnmodeled` skip — never a silent pass | `GRY-TEST-2/4` |
| 6 | SQL snapshot eyeballed | JOINs / predicates / GROUP BY / ORDER BY / LIMIT mean what the query means; SQL deterministic (sorted `pk__in`, tiebroken `ORDER BY`) | `GRY-TEST-1`, `GRY-ARCH-9` |
| 7 | Path coverage, not intent | every dispatch path that reaches the feature is exercised (`scripts/gryphon-coverage-ratchet`); a scan/union gets a **no-`WHERE`/count** over-inclusion test | `GRY-TEST-3` |
| 8 | TCK corners re-authored | corner intents mined; `inspired_by` set; **nothing copied** | `GRY-PROC-7` |
| 9 | Semantics pinned where touched | null behavior stated + pinned; data-lane type-strictness; scope read from AST; canonical envelope only | `GRY-SEM-1/2/6`, `GRY-ARCH-11` |
| 10 | Fuzzer / TLP extended — **conditional** | required **only if** the feature adds/changes predicate, null, or multiplicity semantics (`scripts/gryphon-fuzz-campaign` / `/gryphon-fuzz-soak`); otherwise record "N/A — no new predicate/null surface" in the spec | `GRY-TEST-8` |
| 11 | Docs synced | capability block authored/updated; RIDs grepped in `docs/` and updated; divergence/credit ledgers updated if the feature diverges from or exceeds Cypher | `GRY-PROC-4`, `GRY-LANG-2` |
| 12 | One commit, full cycle | spec + grammar + AST + parser + executor + scenarios + tests in a single coherent commit | `GRY-PROC-6` |
| 13 | Independent **spec** review recorded | the plan-stage [Independent LLM Review Gate](#independent-llm-review-gate) was run and its material findings addressed-or-dispositioned | `GRY-TEST-9` |
| 14 | Independent **code** review recorded + clean tree | the post-code [Independent LLM Code Review Gate](#independent-llm-code-review-gate) was run against the rubric, its material findings addressed-or-dispositioned, the reviewer's tree-modification report recorded (expected: none), and re-entry verification shows a clean, unchanged tree | `GRY-TEST-9` |

Green-on-all = validation-ready. A `review-time` enforcement on a row means "no automated guard yet"
— a **machine-enforced merge gate is a named candidate**, not built ahead of demand (name the gap;
do not imply completeness).

**Experimental validation lane (not a gate until promoted).** Once the Gridkin AI-QC
requirement (gryphon_playground plugin repo's spec) is implemented, a Gryphon feature MAY opt
selected Gridkin scenarios into AI Query Compiler QC: an independent AICompilerArtifact is
executed in a disposable read-only fixture DB and compared by canonical result, not SQL shape.
Treat AI QC disagreement as a diagnostic finding that enters that spec's AI-QC-investigation
workflow; it never replaces Gryphon's answer or regenerates expected envelopes. Until the AI QC signal is explicitly promoted, this lane is optional/experimental
and does not add a merge-readiness row.

## Post-Ship Retrospective — the self-improvement step

**The closing bookend of the cycle: once the feature has shipped, the *process* learns from it.** After
the branch cleared the [Merge-readiness gate](#merge-readiness-gate-definition-of-done) and the promote
process carried it (or it is validation-ready and handed off), run a deliberate retrospective on the path
just taken. This is not optional polish — it is the mechanism by which this skill improves itself. Every
scar in this skill (the over-deletion rubric row, the circular-parity check, the lost-error-message
lesson) exists because a prior cycle hit it and *carried it forward*. Without this step the lesson
evaporates and the next feature re-learns it the expensive way.

**Reflect on the path — name what actually happened, don't sand it smooth.** Walk the cycle end to end:
- **What surprised us / what went wrong.** Every wrong-answer, over-deletion, lost contract, circular
  proof, coverage gap, spec overclaim, doc that misled, or process friction hit this cycle — stated
  plainly. A retrospective that finds nothing to improve was not pointed hard enough (the same instinct
  as an adversarial review).
- **What went *right* that should be reinforced.** A discipline that caught a bug (which suite, which
  gate) is a signal worth strengthening, not just a pass.

**Map each lesson to the durable artifact that must carry it — and say where it lands.** A lesson not
written into a durable artifact has not been carried forward; it is a TODO that will be re-learned. The
usual landing spots:
- **This skill** — a new rubric row, a new Common-Mistake, a step clarification (the most common home).
- **The commandments** (`docs/doc-gryphon-commandments.md`) — if the lesson is doctrine-level, a new or
  promoted `GRY-*` rule.
- **A spec / requirement** — a missing ACID, an overclaim to correct, a `Future` bullet to add.
- **Plugin docs** — a how-to that misled, a wishlist / feature-demand row, a doc-spec `update-trigger`.
- **The validation system** — a new Gridkin scenario class, a coverage-gate row, a fuzzer axis, a
  findings-ledger row.
- **Memory** — a durable cross-session lesson.
- **Associated processes** — the promote / merge flow, the multisession discipline, this skill's own gates.

**The third-party exit interview.** Apply the independence principle one last time — now to the *process*.
An objective third-party LLM (Codex is the standard; the principle is *independence*) is walked through
the path taken and asked: *"what in the plugin documentation, specifications, requirements, or process
would you change to prevent the problems we hit and carry the lessons forward?"* The same outside view
that catches spec blind spots (gate 2) and implementation blind spots (gate 4) catches *process* blind
spots the author cannot see. Its suggestions feed the change-list below alongside the author's own.

**Write it up, then apply it.** Produce a short retrospective note (the repo already uses `docs/aar/` for
sprint closeouts) capturing three things: the **path**, the **lessons** (author's + exit-interview's), and
a concrete **change-list** — each lesson mapped to the artifact it updates and its state (applied /
queued-with-tracking-location / deferred-with-reason). Then **fold the updates in**: the rubric rows, the
commandment, the spec, the doc, the memory. Docs/spec/skill/process updates are eligible for the
docs-only promote path; anything touching code re-enters the full cycle.

**Done.** The cycle is truly closed when the retrospective is written and every change-list item is
applied or explicitly queued. Ship → reflect → update the process → the next feature starts from a better
baseline. That loop is the point.

## Bug-fix mode — a Gryphon wrong-answer was found

The main path (Steps 1–10) builds a *new capability*. A **wrong answer, silent drop, or crash in an
existing feature** takes a different path (`GRY-TEST-7` — a Gryphon wrong-answer is never normalized,
never worked around in callers, never filed as an accepted "known limitation"):

1. **Notify the user.** Surface it explicitly; do not bury it or reshape callers around it.
2. **Reproduce first, in the validation system — before any fix.** Write a *failing* Gridkin scenario
   (hand-authored oracle) and/or a `test_gryphon.py` case, and/or a fuzz replay that exhibits the
   wrong answer. If you cannot reproduce it, you cannot claim to have fixed it.
3. **Log it.** `scripts/gryphon-findings` (the findings ledger); if it is a coverage/limitation,
   also the wishlist § Known Issues.
4. **Fix at the source** — executor/parser, not callers. Prefer making the bug *structurally
   impossible* (collapse a path, tighten a type, fail-closed) over a spot patch (`GRY-ARCH-4`).
5. **Lock it.** The failing test from step 2 now passes and stays. If it was an oracle-vs-executor
   divergence, confirm the model oracle now agrees (`GRY-TEST-2`).
6. **Append the findings-ledger row**, and if the fix changes documented behavior, run the doc-sync
   (`grep -r <RID> docs/`, `GRY-PROC-4`).

A bug-fix still ships as **one coherent commit** and still faces the
[Merge-readiness gate](#merge-readiness-gate-definition-of-done) — rows 4–7 especially (the failing-
then-passing scenario, oracle agreement, eyeballed SQL, coverage). A fix that **changes semantics**
(not a narrow, obviously-correct patch) also runs the
[Independent LLM Review Gate](#independent-llm-review-gate) on the fix approach before it lands — the
same authoring-independent second opinion an important capability gets. And any fix that **changes
code** faces the [Independent LLM Code Review Gate](#independent-llm-code-review-gate) once green — the
over-deletion / lost-rejection-message / silent-drop rubric applies to a fix diff exactly as it does to
a capability diff, and re-entry still verifies a clean, unchanged tree. And once the fix ships, it earns
a [Post-Ship Retrospective](#post-ship-retrospective--the-self-improvement-step) like any cycle — a bug is
the richest lesson source, so ask what durable artifact (rubric, commandment, spec, doc, scenario class)
should carry it forward.

## Common Mistakes (do not commit any of these)

- **Capturing the oracle instead of authoring it.** Running update-snapshots first
  and committing whatever the executor produced cannot catch a systematic
  executor bug — a consistent COUNT inflation produces consistent expecteds that
  all pass on rerun. Hand-compute, then verify in assert mode (Step 7.2).
- **Single-quoted strings in a query.** Gryphon strings are double-quoted.
- **A new `Predicate` leaf that a walker silently drops.** Adding to the union is
  not enough — audit `_flatten_conjunction`, `_apply_comparison`,
  `_apply_typescan_predicate`, `_filter_predicate_for_bindings`,
  `_collect_params_from_predicate`.
- **A transformer method missing the `@v_args(inline=True)` token argument** for an
  inline-regex value rule (the `null_val` bug).
- **Silently ignoring an out-of-scope clause** instead of raising a clear error.
- **Non-deterministic emitted SQL** — no tiebreaker on ORDER BY, unsorted `pk__in`.
- **Climbing the lowering ladder when a lower rung expresses the query** — reaching for
  `RawSQL` or a hand-written SQL template where an ORM `QuerySet` or a `Func` subclass
  would do. Each rung up sheds an ORM-provided guarantee you must then re-earn by hand
  (`req-grid-traversal-exec-lowering`).
- **Copying TCK query text, data, or expecteds.** Inspire from the corner-case
  intent; re-author everything in TAP vocabulary.
- **A scenario file with no `covers` array** — the loader rejects it.
- **Shipping the executor change without the spec requirement and Gridkin
  scenarios in the same commit.**
