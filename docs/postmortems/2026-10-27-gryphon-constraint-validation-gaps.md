---
tags: [application-bug, silent-failure, dev-tooling]
failure_class: predicate-conservation-gap
surfaces: [gryphon-parser, gryphon-bare-spine-resolver]
fix_commits:
  - aead42dc556fac821521bca0930142e4c7848bce
  - 35517797533ac9862f0c81a015e6b93d22318383
---

# Gryphon accepted queries that bypassed their authored constraints

Two ordinary correctness defects were found while exercising the running instance's canonical read path. Security impact was not established. The repairs and their verification ran in a separate core_ci playground; the assessment instance was unchanged.

An inline node map with two conflicting `name` entries returned one later-name collector where the explicit two-predicate WHERE form returned zero. Omitting the earlier parameter still returned one. The shared parser reduced `dict(pairs)` before validation and required-input collection, erasing the earlier obligation. Duplicate inline keys now reject at parse time, including on edge and LOOKUP maps; the message names explicit WHERE predicates joined with AND.

A labelless query for `dimensions.tap.cloud` returned zero without error while `dimensions["tap.cloud"]` found 39 nodes. Labelled queries already rejected the nested spelling. The previous repair had counted two resolvers and missed the independent Entity-spine resolver, which joined the path itself. That third resolver now uses the same flat-key validator. Legal one-step keys, absent-key answers, and ordinary nested data JSON retain their contracts.

Both failures escaped because an invariant was stated globally but conserved only along selected paths. One lost syntax before the AST existed; the other bypassed a shared guard during lowering. The shape sweep enumerated adjacent sites once, pinned clean neighbours, and recorded confirmed siblings as strict expected failures without repairing them recursively. The [repair checkpoint](../misc/gryphon-query-defect-repair-2026-10-27.md) carries exact reproductions, counts, prior art, test results, and the local issue drafts.

The new regressions failed before repair and failed again when each original implementation was temporarily restored. Full core, Gridkin, metamorphic, generated differential/rejection, and type/traceability checks passed with only the explicitly registered sibling xfails. Named service batches created all new graph fixtures.

## What Paladin would need

Detection needs independent query-equivalence checks: an inline constraint versus its explicit WHERE spelling, and the same invalid dimension path across labelled and bare dispatch. A clean empty response alone is not a health signal. Required-input discovery should also be checked before any destructive reduction of authored constraints.

Safe remediation is to refuse the invalid stored query with its named remedy and escalate the engine defect with the query, fixture identity, counts, and core revision. Paladin should not rewrite query intent or mutate graph data to make a wrong answer appear plausible. Deploying the reviewed engine repair and replaying the captured checks restores the read contract; autonomous engine modification is not specified.
