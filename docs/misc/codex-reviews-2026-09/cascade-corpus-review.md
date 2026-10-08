# Cascade confirmation corpus review

Reviewed 2026-09-18 at commit `5b361005`, following the earlier `27e412d5` draft. Scope: #578 / PR #582. Review only; no implementation changes. The current artifact is core `tap_grid/cascade_corpus`, borrowing Gridkin's approach rather than residing in the playground plugin.

**Recommendation: keep this design and finish the checker before growing the scenario count.** There are now 70 JSON scenarios in six families (depth 12, loops 14, blocks 10, limits 14, records 13, undeclared 7), plus four Python timing cases. These are scenario counts, not independently verified passing-test counts.

## What Claude got right

- Small, named, readable graphs with explicit expected retirement sets. A reader can reason about a diamond, loop, or reference boundary without understanding the implementation.
- Checking what must survive is as important as checking what retires. The runner checks unaffected entities' liveness/version and exact event-count deltas, so extra work is observable.
- Schema validation and agreement between authored answers and a memory-only model catch fixture mistakes before database execution.
- Good selection of known failure shapes: self-loops near the cap, shared descendants, edge-ending deduplication, blocked descendants, inbound references, mixed edge types, and type-local containment declarations.
- The newer undeclared family is worthwhile: an edge that looks structurally relevant must still be ignored when its source type does not declare containment.
- Recent commit `4fb170e6` closes earlier review gaps: expected retirements now require exactly one version increment; edge events now require cascade root and inherited metadata. Those concerns should not remain listed as unfixed.
- The late-child test now distinguishes the child from its incident edge: the late node survives while the edge ends with its retired endpoint. Recording this distinction is much better than hand-waving about concurrent traversal.

## Fix now: trustworthiness of the evidence

### 1. Two orders do not identify every legitimate discoverer

[Issue #586](https://github.com/unified-systems-com/tap/issues/586). `tap_grid/cascade_corpus/loader.py:106` runs forward and reverse order; `_parent_options` unions their event parents. Consider R → {A,B,C}, with A, B and C all containing X. The two runs choose A and C. B is also a legitimate first discoverer, but the checker rejects it.

I executed the exact committed pure-Python oracle in the project's Python container with A/B/C, reversed, and B/A/C orderings. Retirement sets agreed; the allowed set was A/C while the third run chose B. This is a reproduced checker false failure, not a demonstrated production deletion defect.

Add all six root-order permutations as a checker regression. Compute legitimate discoverers from the graph/traversal contract or exhaust the relevant small permutations. Do not merely admit all ancestors: an ancestor that cannot discover X first is still wrong. Also narrow or fulfill the spec's stronger assertion that all order-dependent outcomes are rejected—comparing two orders does not establish that.

### 2. An expected defect must not excuse any failure

[Issue #587](https://github.com/unified-systems-com/tap/issues/587). Whole-test strict xfail marks cover fixture construction, worker exceptions, timeouts and deadlock assertions as well as the intended replay mismatch. `strict=True` makes an unexpected pass fail; it does not verify why a test failed.

Keep unexpected setup/worker/cleanup failures as hard failures. Recognize the specific known behavioral mismatch separately, with a negative control proving that an unrelated worker exception is not accepted as an expected failure.

The timing helper also observes any other backend waiting on any lock, rather than identifying the intended writer and holder. The same-root and shared-child tests use only a start barrier: that starts the writers together but does not force the vulnerable overlap. Capture worker backend IDs and establish the actual blocking relationship; guarantee release/join in cleanup. Until then, the spec overstates deterministic interleaving and the promise that a deadlock fails the suite.

### 3. Finish provenance assertions and test the checker negatively

[Issue #588](https://github.com/unified-systems-com/tap/issues/588).

The updated runner still does not inspect root event metadata, or `root_reason` on descendant/edge events. It also compares every input metadata key verbatim on descendants, while production deliberately replaces reserved keys (`reason`, `consequence_of`, `cascade_root`, `root_reason`). Add a metadata fixture distinguishing authoritative generated fields from inherited contextual fields.

Use a handful of deliberately corrupted observations to prove the checker rejects missing/wrong root_reason, missing root context, duplicate events, double version bumps and collateral retirement. This can be a small ordinary test module; no mutation-testing dependency is needed. Exact retirement counts alone do not certify provenance.

## Add now: a small, discriminating next set

1. **Three-way convergence with permutations:** the reproduced A/B/C → X case, plus a cross-edge between same-depth retired nodes.
2. **An already-retired containment edge between live nodes:** a retired bridge must not be followed, although both endpoints are live. Current pre-retired support names nodes, not standalone edges.
3. **Multiple relationships between the same endpoints:** distinct allowed containment types plus a reference relationship. Count the child once; end each distinct live edge once. Respect the platform's edge uniqueness contract when constructing this.
4. **Full provenance:** root context, child/edge root_reason, scope/run/evidence context, and reserved-key replacement. Include absent versus invalid/empty reason as distinct inputs.
5. **Late injected failure:** after one branch has actually been written, fail a later mutation or audit recording and prove all affected rows/events roll back. A preflight refusal cannot substitute for this.
6. **One independent operation-batch test:** run outside the ambient fixture batch and check normal success/refusal lifecycle and attribution. The current event-delta strategy is good for the ambient test harness but does not establish independent batch behavior.
7. **A realistic mixed-domain miniature:** a post/comment subtree with shared authors, tags and places. Retire the subtree and incident relationships; preserve shared referenced entities and another unrelated thread. This exercises several rules together without requiring a large dataset.

Some of these properties may already have individual service tests. Reuse that evidence and add only the missing composition or checker assertion; do not duplicate every unit test in JSON to increase the count.

## Prior art and what to borrow

| Source | Where it has landed | Useful adaptation for TAP |
|---|---|---|
| [openCypher TCK](https://opencypher.org/resources/) | Behavior described as features/scenarios with prerequisites, inputs and expected outputs. | Strong support for the chosen readable, data-driven corpus shape. Add observable postconditions, not just successful calls. It is language conformance, not TAP containment semantics; do not transplant DELETE/DETACH outcomes wholesale. |
| [Django deletion regression tests](https://github.com/django/django/blob/main/tests/delete/tests.py) | Mixed protection/cascade paths, indirect diamonds, inheritance, deletion order and large related sets. | Combine blocking and reachability through multiple paths. Its `test_restrict_path_cascade_indirect_diamond` is a useful topology source. Django's hard-delete and RESTRICT semantics differ from TAP's policy—borrow graph shapes, derive TAP answers. |
| [Kubernetes garbage-collector tests](https://github.com/kubernetes/kubernetes/blob/master/pkg/controller/garbagecollector/garbagecollector_test.go) | Owner/dependent event processing, missing owners, conflicting data, orphan failures and concurrent dependent updates. | Extend timing cases toward edge insertion/removal, stale observations and shared dependents. Kubernetes ownership/liveness rules are not TAP's first-parent cascade rule; importing its expected deletions would be wrong. |
| [LDBC SNB Interactive v2 workload](https://ldbcouncil.org/ldbc_snb_docs/workload-interactive-v2.pdf) and [deep-delete paper](https://ldbcouncil.org/docs/papers/ldbc-snb-interactive-v2-tpctc2023-preprint.pdf) | Explicit recursive deletion of posts/comments, forums and personal content amid a richer social graph. | Best match for a realistic second corpus: nested owned content surrounded by shared references. Start with a tiny adapted fixture; reserve full generated datasets and transactional workload benchmarking for later. The documentation labels Interactive v2 WIP. |
| [SQLite testing](https://www.sqlite.org/testing.html) | Independent harnesses, injected failures, boundary tests and mutation testing supplement ordinary known-answer cases. | Borrow late-failure rollback tests and negative controls for the checker now. No need to reproduce SQLite's crash/fuzz infrastructure in this pass. |
| [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) | Action sequences checked against a model, with minimized failing examples. | Later, test create/link/retire/repeat sequences and promote discovered failures to readable committed scenarios. This is a method recommendation, not a proposal to add a dependency now. |
| [NetworkX Graph Atlas](https://networkx.org/documentation/stable/reference/generated/networkx.generators.atlas.graph_atlas_g.html) | A finite collection of small graph structures, up to seven nodes. | Inspiration for bounded exhaustive coverage. The atlas uses simple undirected graphs, so it is not a drop-in corpus for TAP's directed, typed, potentially looping relationships. A stdlib enumerator of the 512 directed single-type graphs on three labeled nodes, including loops, would be a better first fit. |

## Defer deliberately

- Full LDBC imports, benchmark throughput, giant fan-out graphs and long-running concurrent workloads.
- General state-machine/property-based infrastructure and automatic shrinking. First make authored counterexamples easy to retain.
- Moving the corpus into the playground plugin or making a universal corpus framework. Its present core location is reasonable for this pass.
- Broad reparenting/snapshot semantics changes. Current behavior can be documented honestly while that contract is decided separately; fixing test synchronization does not require fixing every production race.
- A fully different mathematical oracle. The present model is independent of Django but follows the production BFS/control-flow shape closely, so shared reasoning mistakes remain possible. A set-based reachability fixed point would strengthen independence later. Correct the current claim that the model knows nothing about queues: it explicitly maintains one.

## Validation and limits

Inspected the current runner, schema, loader, model, all family inventories and timing tests; compared changes since the earlier draft. Ran the memory-only order reproducer using the project interpreter. Did not rerun the database suite while Claude's work was active, and make no independent green-suite claim. Upstream research used primary documentation and source tests; individual openCypher delete feature downloads were unavailable, so the comparison uses its published TCK design rather than pretending to have exhaustively audited those files.

GitHub access recovered after the earlier approval/usage block; findings #586, #587 and #588 were filed against the corpus work.
