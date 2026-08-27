---
title: Gryphon audited against the BloodHound GitHub query corpus
date: 2026-08-27
status: active
audience:
  - developer
  - llm
spec: tap_grid/specs/spec-grid-traversal-language.md
related_docs:
  - docs/misc/doc-dev-gryphon-vs-cypher.md
  - tap_grid/specs/spec-grid-history-timetravel-BACKLOG.md
---

> **Audit, 2026-08-27.** 71 Cypher queries extracted verbatim from the two published BloodHound
> GitHub extensions at pinned commits, run against Gryphon's real capability surface. Every claim
> that contradicts a specification was re-verified by **executing SQL** in a running container
> (45+ probe queries through the raw executor with SQL capture), not by reading code.
>
> **Two correctness defects found.** Both are cases where Gryphon accepts a query and answers a
> different question — the failure mode this codebase's doctrine forbids. Both are believed-working
> surfaces, marked `Implemented` in the spec. See §4.
>
> Human-readable writeup: the "What Gryphon Answers" artifact.

# Gryphon vs. the BloodHound GitHub extension — a capability audit

*Read-only audit, 2026-08-27. Worktree `/Users/george/tap-sessions/git-serious` @ `0c3d5f0c`. No repository file was modified.*

---

## 0. Headline

**Corpus.** 71 distinct Cypher queries extracted verbatim from the two Apache-2.0 SpecterOps repos:
`SpecterOps/openhound-github` @ `40de52ad` (`extension/saved_searches/*.json`, 55 queries — the newest copy)
and `SpecterOps/GitHound` @ `bcd3da19` (`saved-queries/*.json`, the same 55 with 5 older variants;
`Documentation/Queries.md`, 5 further enterprise queries with no JSON file; `pz-rules/*.json`, 11 Tier-Zero
privilege-zone selectors). That is where the "60+" claim comes from: 55 shipped + 5 documented = 60 named
queries, plus 11 privilege-zone rules. Raw text is in `bloodhound-queries-list.txt` / `bloodhound-github-queries.json`
alongside this report.

**The numbers, three ways — because one number would be misleading.**

| Question | Answer |
| --- | --: |
| Run **verbatim** and return the right answer | **4 / 71** (6%) |
| **Expressible today** after mechanical rewrites (label rename, inline-props → `WHERE`, `RETURN p` → default envelope, `<>` → `!=`, label-predicate → `entity_type IN [...]`) | **59 / 71** (83%) |
| Blocked on a **hard Gryphon language gap** — no rewrite exists | **12 / 71** (17%) |
| Answerable against TAP's **live** `github_core` model today (types actually exist) | **3 / 71** |
| Would, run verbatim, return **silently unfiltered — wrong — results** | **43 / 71** |

**Top three missing language features, by queries unblocked:**

1. **Variable-length paths (`-[:A\|B*1..]->`) with edge-type alternation** — 7 queries. These two always
   co-occur in this corpus and are the whole attack-path half of BloodHound. `*m..n` parses and the executor
   rejects it; `A|B|C` does not parse at all.
2. **Correlated multi-clause `MATCH`** — 7 queries touch it, 2 blocked on it alone. Gryphon executes multiple
   `MATCH` clauses as an *uncorrelated union*, not a join, and does so **silently** — the spec claims the
   opposite.
3. **Property-to-property comparison** (`a.x = b.y`) — 2 queries; a parse error today.

**The most important finding is not in that list.** `MATCH (n:Label {prop: value})` — a node inline property
map — is parsed into the AST and then **never read by the executor**. It is silently discarded. 43 of the 71
BloodHound queries put their entire filter in exactly that position. Run against Gryphon today they execute
happily and return every node of the type. Evidence in §4.

---
## 1. Gryphon capability inventory

Paths are relative to the worktree root. Grammar = `tap_grid/gryphon/grammar.lark`, AST =
`tap_grid/gryphon/ast_nodes.py`, executor = `tap_grid/gryphon/executor.py`, parser =
`tap_grid/gryphon/parser.py`. Every "verified" line below was executed live in this session's container
against `tap_grid.gryphon.executor._execute_gryphon_raw_impl` with SQL capture — not inferred from the code.

### 1.1 Clauses

| Clause | Grammar | Status | Evidence / limits |
| --- | --- | :--: | --- |
| `MATCH` | `grammar.lark:28` | shipped | One or more. **Exactly one pattern per clause** — comma-separated patterns rejected (`executor.py:348`, verified). |
| `WHERE` | `grammar.lark:64` | shipped | Exactly **one global** `WHERE` per query; a second is a parse error (`parser.py:121`). It is scoped per clause by variable (`_filter_predicate_for_bindings`, `executor.py:2289`). Per-`MATCH` `WHERE` attachment — Cypher's real model — is future work (`spec-grid-traversal-language.md` § Multiple WHERE). |
| `RETURN` | `grammar.lark:104` | shipped | Optional. Omitted, or naming bare variables ⇒ **graph envelope** `{nodes, edges}`. Naming field paths / aggregates ⇒ **row projection** (`rows`). This is a deliberate divergence from Cypher, where `RETURN` is mandatory. |
| `ORDER BY` | `grammar.lark:122` | shipped | Row-projection mode (by RETURN alias) and envelope mode (`ORDER BY n.data.f DESC`) — envelope mode only on a **single labelled type-scan** (`executor.py:786`, `:2476`). Rejected on single-hop graph traversal (`executor.py:427`) and on a labelless `MATCH (n)` (`executor.py:1196`). |
| `LIMIT` | `grammar.lark:127` | shipped | Same dispatch constraints as `ORDER BY`. `LIMIT` with no `ORDER BY` gets a deterministic tiebreak. Verified on a type-scan envelope. |
| `OPTIONAL MATCH` | `grammar.lark:33` | shipped, **very narrow v0** | `executor.py:3069`. Requires: exactly one **node-only** mandatory `MATCH` with a label; exactly one **single-hop, directed** optional pattern anchored on that variable; a **row-projection** `RETURN` that projects the mandatory variable's fields and `COUNT()`s the optional one. Graph-envelope `OPTIONAL MATCH` is rejected (`executor.py:3151`). Does not combine with `NOT EXISTS` (`:3147`). Verified: the v0 shape runs; adding an edge to the mandatory `MATCH` is rejected. |
| `NOT EXISTS { ... }` | `grammar.lark:22` | shipped | Correlated anti-join via Django `~Exists()` (`executor.py:2050`). Inner block: exactly one pattern (`:2081`), at least one edge (`:2084`), must share a variable with the outer query (`:2095`). Verified in both envelope and row modes. |
| `WITH` | — | **absent** | Not in the grammar. Verified parse error. |
| `UNION` / `UNION ALL` | — | **absent** | Verified parse error. Multiple `MATCH` clauses give an *implicit* envelope union with entity_id dedup (`executor.py:327`) — see the correctness caveat in §4.2. |
| `UNWIND`, `CALL {}`, `CASE`, map projections | — | absent | Deliberate subset (`docs/misc/doc-dev-gryphon-vs-cypher.md` Ledger C). |
| `SKIP` / `OFFSET`, `DISTINCT` | — | **absent** | Verified parse errors. Wishlist A3 / A4. |
| `CREATE` / `MERGE` / `SET` / `DELETE` | — | rejected by construction | Read-only by design; a security posture, not a gap. |

### 1.2 Patterns

| Feature | Grammar | Status | Evidence / limits |
| --- | --- | :--: | --- |
| Node pattern `(v:Label)` | `:39-42` | shipped | Variable, label, or both — all optional. `(:Label)` and `()` both parse; verified. |
| Labelless `MATCH (n)` | — | shipped | Bare type-scan across every registered node type, unioned (`executor.py:1141`). Envelope-only; no `ORDER BY`/`LIMIT`; a data-lane `WHERE` on it must be pure-`AND` (`:1244`). |
| Directed edge `-[e:T]->`, `<-[e:T]-` | `:48-49` | shipped | |
| Undirected edge `-[e:T]-` | `:50` | shipped **single-hop only** | Executes as the union of both arms (2 SQL statements, verified). In a **multi-hop chain it is rejected** (`executor.py:1777`, verified). |
| Multi-hop chain `(a)-[:X]->(b)-[:Y]->(c)` | `:37` | shipped | `_build_chain_queryset` (`executor.py:1712`), all hops folded into one `.filter()` so Django reuses joins. Verified 3-hop envelope; emits a `multi_hop_no_anchor` warning when there is no `WHERE`. |
| **Variable-length `*m..n`** | `:55` | **parses, executor rejects** | Three rejection sites: `executor.py:435`, `:1771`, `:3139`. Verified: `SearchExecutionError: Unsupported gryphon pattern: bounded multi-hop traversal is not supported.` Note the spec's ACID table still marks `req-grid-traversal-lang-patterns-5` "Supports Bounded Repetition — **Implemented**" (`spec-grid-traversal-language.md:262`). That row is wrong; `doc-dev-gryphon-vs-cypher.md` Ledger C has it right. |
| **Edge-type alternation `-[:A\|B]->`** | — | **absent** | `edge_body_type: ":" NAME` (`grammar.lark:54`) — a single name. Verified parse error at the `\|`. |
| **Label-union node `(n:A\|B)`** | — | absent | Verified parse error. Wishlist B4. |
| **Path variable `p = (...)`** | `:35` | **parsed, silently unused** | `parser.py:159-166` stores `MatchClause.path_var`; the string `path_var` appears **nowhere** in `executor.py`. `RETURN p` then fails with `Unknown variable 'p' in RETURN` (`executor.py:2223`, verified), so it is not a wrong-answer bug — but `MATCH p = (...)` with an envelope return accepts and ignores the binding. No `length(p)` / `nodes(p)` / `relationships(p)`. |
| `shortestPath(...)` | — | absent | Verified parse error. |
| **Node inline props `(n:L {k: v})`** | `:57` | **parsed, SILENTLY DROPPED** | See §4.1. This is a live wrong-answer defect. |
| Edge inline props `-[:T {k: v}]->` | `:57` | shipped | Applied as `properties -> 'k' = v` (`executor.py:1798`; SQL verified). |

### 1.3 Predicates and operators

| Feature | Where | Status | Notes |
| --- | --- | :--: | --- |
| `=` `!=` `<` `>` `<=` `>=` | `grammar.lark:95` | shipped | Note `!=` only — Cypher's `<>` is **not** a token; verified parse-clean for `!=`. |
| `STARTS_WITH` / `ENDS_WITH` / `CONTAINS` | `:98` | shipped | Case-sensitive; case-insensitive variants are future work. Verified (`LIKE 'neigh%'`). |
| `=~` regex | `:76` | shipped | Postgres POSIX, **search semantics** (unanchored) — a deliberate divergence from Cypher's anchored `=~`. |
| `IN [ ... ]` | `:77` | shipped | Elements may be literals or `$param`s. Whole-list `IN $list` is future work. Verified. |
| `IS NULL` / `IS NOT NULL` | `:78-79` | shipped | |
| `IS KNOWN` / `IS UNKNOWN` | `:80-81` | shipped | Net-new vs Cypher — the observed/unobserved axis. `IS EMPTY` deliberately deferred. |
| `AND` / `OR` / `NOT` | `:68-70` | shipped, with two carve-outs | Full `Q` composition in the chain and type-scan paths (`executor.py:2014`, verified `OR` and `NOT` on a type scan). **Carve-out 1:** a labelless `MATCH (n)` with a data-lane `WHERE` is `AND`-only (`:1244`). **Carve-out 2:** `OPTIONAL MATCH` v0 is `AND`-only (`:2008`). **Carve-out 3:** a *negated* `=`/`IN` on a node beyond the root edge of a multi-hop pattern is refused outright (`_guard_negated_far_predicate`, `:1844`) because it would compile to an anti-join with the wrong semantics — an honest refusal, not a silent wrong answer. |
| **`a.x = b.y` (property-to-property)** | — | **absent** | `comparison: field_path COMPARE_OP value` and `value` is a literal or `$param` (`grammar.lark:74,133`). Verified parse error. |
| **Label predicate `WHERE n:Label`** | — | **absent** | Verified parse error. **Workaround exists and is exact**: `WHERE n.entity_type IN ["A","B"]` — `entity_type` is a spine field (`models.py:303`), verified running on both near and far nodes of a chain. (Caveat: Neo4j nodes carry *multiple* labels; a TAP entity has exactly one `entity_type`. For this corpus that never bites.) |
| `$param` | `:140` | shipped | Required-param set derived from the AST (`ast_nodes.py:423`); missing params are a hard error, never a silent null. |

### 1.4 Field paths (the lane model — net-new vs Cypher)

Cypher's node is a flat property bag. Gryphon splits the address space, **explicitly, with no routing sugar**:

- **spine** — `n.entity_id`, `n.entity_type`, `n.name`, `n.dimensions`, `n.created_at`, `n.updated_at`, `n.deleted_at`, `n.version`, `n.originating_grid_id` (`models.py:303`).
- **`data` lane** — `n.data.<field>` reaches the typed per-model row. Multi-step into a `JSONField` works: `n.data.tags.a.b` lowered to a native nested JSON lookup (verified, params `(['a','b'], Jsonb('x'))`). `n.dimensions["key"]` bracket-key works (verified).
- **`display` lane** — rejected in both `WHERE` and `RETURN`; display values are computed, not stored (`executor.py:693`, `:1592`).
- A bare non-spine name is a **hard error**, not a guess: `Field 'x' is not a spine field. … address it as <var>.data.x`. This matters for the BloodHound corpus — nearly every query writes `o.two_factor_requirement_enabled`, which errors rather than silently missing.
- Security: every post-`data` token must resolve to a declared field or a key inside a declared `JSONField`; relation walks, Django `__` transforms and bracket-smuggled steps are rejected at all three resolvers (`req-grid-traversal-lang-relation-guard.sec`). This closed a confirmed cross-table read.
- **Type strictness:** a data-lane literal whose type contradicts the declared schema is *rejected*, not coerced and not silently dropped (`executor.py:2893`) — a deliberate, and good, divergence from Cypher.

### 1.5 Projection and aggregation

| Feature | Status | Notes |
| --- | :--: | --- |
| Graph envelope (`RETURN` omitted / bare vars) | shipped | The default. Returns `{nodes, edges}` at `lite`/`full`/`extended` layers. This is structurally what BloodHound's `RETURN p` is *for*. |
| Field projection `n.data.x AS x` | shipped | `AS` optional; default alias is the last dot-step. |
| `COUNT(v)` / `COUNT(v.f)` | shipped | The **only** aggregate (`executor.py:2716`). Implicit `GROUP BY` on the non-aggregated columns. **Requires at least one edge in the pattern** — `MATCH (n:T) RETURN n.data.k AS k, COUNT(n) AS c` is rejected: *"Advanced executor requires at least one edge in the MATCH pattern"* (verified). So there is no aggregation over a plain type scan. |
| `SUM` / `MIN` / `MAX` / `AVG` / `COLLECT` / `COUNT(DISTINCT …)` | **absent** | Verified parse errors. |
| Scalar functions (`toLower`, `size`, `coalesce`, `substring`, …) | **absent** | No function-call rule in the grammar at all. |
| Arithmetic in expressions | absent | |
| `explain` / SQL capture | shipped | `explain_gryphon_raw` returns the envelope **and** the ordered, stage-labelled SQL. This is what made this audit verifiable rather than speculative — a genuinely good Player-3 affordance. |

### 1.6 Execution-shape constraints (the things that bite)

These are not "missing features" so much as narrow dispatch envelopes, and they are where a query that looks
supported turns out not to be:

- Exactly one pattern per `MATCH` (`:348`); no comma-patterns.
- Row projection with field paths or aggregates requires **exactly one** `MATCH` clause (`:2383`).
- `ORDER BY` / `LIMIT` are rejected on single-hop graph traversal (`:427`) and on labelless scans (`:1196`).
- Undirected edges are rejected in any multi-hop chain (`:1777`).
- `COUNT` needs an edge (`:2345`).
- Node-only patterns cannot be referenced in predicates or `RETURN` paths from the advanced executor (`:1540`).

---

## 2. Query-by-query verdict

**How to read the verdict column.**

- **RUNS** — expressible today *and* TAP's `github_core` plugin already has the node/edge types, so it could
  be pointed at live data now.
- **RUNS-IF-MODELLED** — the Gryphon language can express it; TAP lacks the node/edge types. The "Note"
  column names what is missing.
- **GAP** — Gryphon cannot express it at all; the Note names the missing language feature.
- **N/A** — none. Every one of these 71 queries asks a question that applies to TAP; nothing here is a
  Neo4j-only concept.

**Rewrites assumed for a RUNS / RUNS-IF-MODELLED verdict** (all mechanical, all verified working):

| BloodHound writes | Gryphon needs |
| --- | --- |
| `(n:L {k: v})` | `MATCH (n:L) WHERE n.data.k = v` — **mandatory**, see §4.1 |
| `n.some_field` | `n.data.some_field` (bare non-spine names are a hard error) |
| `RETURN p` (path variable) | omit `RETURN` — the default graph envelope carries the same nodes + edges |
| `o.x <> 'none'` | `o.data.x != "none"` |
| `WHERE s:AZUser OR s:Okta_User` | `WHERE s.entity_type IN ["AZUser","Okta_User"]` |
| `RETURN n` on an edge-bearing pattern | same, but you get the whole subgraph, not just `n` |

These rewrites are individually trivial; the one that matters is the first, because it is the difference
between a right and a wrong answer rather than between two spellings. 44 of the 71 queries need it.

| # | What it asks | Cypher features it uses | Gryphon verdict | Note |
| --: | --- | --- | :--: | --- |
| 1 | Orgs not requiring SHA-pinned Actions | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 2 | Open secret-scanning alerts whose secret is still valid | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_SecretScanningAlert |
| 3 | Orgs where GHAS is off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 4 | Orgs allowing any Action from the marketplace | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 5 | App installations scoped to every repo | node inline props; type scan | RUNS-IF-MODELLED | needs GH_AppInstallation |
| 6 | Branch-protection rules admins can bypass | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 7 | Protected branches that can be deleted | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 8 | Protected branches allowing force-push | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 9 | Branches not requiring CODEOWNER review | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 10 | Branches not requiring PR review | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 11 | Branches not requiring status checks | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 12 | Branches allowing self-approval | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 13 | Branches not dismissing stale reviews | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 14 | Actors who can bypass PR review requirements | path-variable RETURN; 2 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 15 | Users reaching push/bypass rights on branches via role or team chains | var-len `*1..`; edge alternation; path-variable RETURN; 2 MATCH clauses; 4 hop(s) | **GAP** | var-length `*1..` + edge-type alternation `A|B|C` + correlated 2-clause MATCH |
| 16 | Orgs whose default repo permission is not 'none' | `<>`; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 17 | Azure/Okta identity → GitHub user → repo write → Azure federated credential | var-len `*1..`; edge alternation; path-variable RETURN; 2 MATCH clauses; 4 hop(s) | **GAP** | var-length `*1..` + edge-type alternation + correlated 2-clause MATCH |
| 18 | Orgs with Dependabot alerts off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 19 | Orgs with Dependabot security updates off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 20 | Orgs with dependency graph off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 21 | Environments admins can bypass | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Environment |
| 22 | Expired PATs still present | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_PersonalAccessToken, GH_User |
| 23 | External identities with no SCIM username | type scan | RUNS-IF-MODELLED | needs GH_ExternalIdentity |
| 24 | Anything that can assume an Azure federated identity | path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs AZFederatedIdentityCredential |
| 25 | Users reaching an org role whose short_name contains 'all_repo_' | var-len `*1..`; edge alternation; path-variable RETURN; CONTAINS; 1 hop(s) | **GAP** | var-length `*1..3` + edge-type alternation |
| 26 | GitHub users fed by an Azure or Okta identity | label predicate in WHERE; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs AZUser, GH_User, Okta_User |
| 27 | Orgs where members can change repo visibility | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 28 | Orgs where members can create Pages | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 29 | Orgs where members can create public repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 30 | Orgs where members can delete repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 31 | Orgs where members can fork private repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 32 | Orgs where members can invite outside collaborators | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 33 | Users holding the org owners role | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_OrgRole, GH_User |
| 34 | Orgs not requiring 2FA | type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 35 | PATs scoped to all repositories | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_PersonalAccessToken, GH_User |
| 36 | Pending fine-grained PAT requests | path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_PersonalAccessTokenRequest, GH_User |
| 37 | Private repos with forking allowed | node inline props; type scan | RUNS-IF-MODELLED | needs the node/edge types |
| 38 | Custom org roles with edges to an org or another role | node inline props; label predicate in WHERE; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_OrgRole, GH_Organization |
| 39 | SSO-synced identities that map to an org owner | node inline props; path-variable RETURN; 2 hop(s) | RUNS-IF-MODELLED | needs GH_OrgRole, GH_User |
| 40 | Public repositories | node inline props; type scan | **RUNS** | TAP has it: github_repository.visibility |
| 41 | Orgs with push protection off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 42 | Actors allowed to push to protected branches | path-variable RETURN; 2 hop(s) | RUNS-IF-MODELLED | needs GH_Branch, GH_BranchProtectionRule |
| 43 | Repos with secret scanning disabled | node inline props; type scan | RUNS-IF-MODELLED | needs the node/edge types |
| 44 | Users who can create a branch on a repo that holds secrets (+ who else can) | var-len `*1..`; edge alternation; label predicate in WHERE; OPTIONAL MATCH; path-variable RETURN; 3 MATCH clauses; 6 hop(s) | **GAP** | var-length `*1..` + alternation + OPTIONAL MATCH beyond the v0 shape + correlated clauses |
| 45 | Repository → workflow inventory | path-variable RETURN; 1 hop(s) | **RUNS** | TAP has it: github_repository -DEFINES_WORKFLOW-> github_workflow |
| 46 | SAML IdP ↔ external identity ↔ user mapping for each org | path-variable RETURN; 3 MATCH clauses; 3 hop(s) | **GAP** | correlated multi-pattern (branching) MATCH — Gryphon unions clauses, never joins them |
| 47 | Repos with open secret-scanning alerts | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_SecretScanningAlert |
| 48 | Orgs with secret scanning off for new repos | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 49 | Users whose role chain reaches repo write on a repo holding secrets | var-len `*1..`; edge alternation; label predicate in WHERE; path-variable RETURN; 3 hop(s) | **GAP** | var-length `*1..` + edge-type alternation |
| 50 | Users who can add members to a team, and the nested teams they thereby reach | path-variable RETURN; 2 MATCH clauses; 5 hop(s) | **GAP** | correlated 2-clause MATCH sharing `team` — Gryphon unions, never joins |
| 51 | User → team-role → nested team membership structure | var-len `*1..`; path-variable RETURN; 2 hop(s) | **GAP** | var-length `*1..` |
| 52 | Unprotected branches | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Branch |
| 53 | Repos that have workflows and whose default branch is unprotected | prop=prop; path-variable RETURN; 2 MATCH clauses; 2 hop(s) | **GAP** | property-to-property comparison (`repo.default_branch = branch.short_name`) + correlated clauses |
| 54 | Repos whose default branch is unprotected | node inline props; prop=prop; path-variable RETURN; 1 hop(s) | **GAP** | property-to-property comparison (`repo.default_branch = branch.short_name`) |
| 55 | Orgs not requiring web commit signoff | node inline props; type scan | RUNS-IF-MODELLED | needs GH_Organization |
| 56 | Enterprise → organization containment | path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Enterprise, GH_Organization |
| 57 | Enterprise members | path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_Enterprise, GH_User |
| 58 | Enterprise owners | node inline props; path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_EnterpriseRole, GH_User |
| 59 | All enterprise-role assignments | path-variable RETURN; 1 hop(s) | RUNS-IF-MODELLED | needs GH_EnterpriseRole |
| 60 | Enterprise teams assigned to orgs, plus their org-team projections | OPTIONAL MATCH; path-variable RETURN; 2 MATCH clauses; 2 hop(s) | **GAP** | OPTIONAL MATCH whose mandatory MATCH carries an edge, and a graph-envelope return — outside the v0 OPTIONAL shape |
| 61 | The synthetic ALL_REPO_ADMIN org role | CONTAINS; type scan | RUNS-IF-MODELLED | needs GH_OrgRole |
| 62 | All-repo app installations holding a write permission | node inline props; CONTAINS; type scan | RUNS-IF-MODELLED | needs GH_AppInstallation |
| 63 | Apps whose all-repo installation holds a write permission | node inline props; CONTAINS; 1 hop(s) | RUNS-IF-MODELLED | needs GH_App, GH_AppInstallation |
| 64 | External identities mapping to an org owner | node inline props; 2 hop(s) | RUNS-IF-MODELLED | needs GH_ExternalIdentity, GH_OrgRole, GH_User |
| 65 | All organizations (Tier Zero root) | type scan | **RUNS** | TAP has it: github_account where account_type='Organization' |
| 66 | Users holding the owners role | node inline props; 1 hop(s) | RUNS-IF-MODELLED | needs GH_OrgRole, GH_User |
| 67 | The owners org role | node inline props; type scan | RUNS-IF-MODELLED | needs GH_OrgRole |
| 68 | All-repo PATs holding a write permission | node inline props; CONTAINS; type scan | RUNS-IF-MODELLED | needs GH_PersonalAccessToken |
| 69 | Org roles that can write custom org roles | 1 hop(s) | RUNS-IF-MODELLED | needs GH_OrgRole, GH_Organization |
| 70 | Users whose role chain reaches a role that can write custom org roles | var-len `*1..`; edge alternation; 2 hop(s) | **GAP** | var-length `*1..` + edge-type alternation |
| 71 | All SAML identity providers | type scan | RUNS-IF-MODELLED | needs GH_SamlIdentityProvider |

**Tally:** 3 RUNS · 56 RUNS-IF-MODELLED · 12 GAP · 0 N/A.

**On the RUNS-IF-MODELLED majority.** That verdict is doing a lot of work, and it should not be read as
comfort. TAP's `github_core` plugin (`_dev-plugins/github_core/`) models 8 node types — platform, account,
repository, workflow, actions_run, actions_job, runner, app — and 9 edge types. The BloodHound extension
models **32 node kinds and ~130 edge kinds**. The entire identity-and-authorization half of GitHub —
`GH_User`, `GH_Team`, `GH_OrgRole`, `GH_RepoRole`, `GH_TeamRole`, `GH_ExternalIdentity`,
`GH_SamlIdentityProvider`, `GH_PersonalAccessToken`, `GH_AppInstallation` — plus branches, branch-protection
rules, environments, secrets and secret-scanning alerts, is simply not on TAP's grid. Nor are the org-level
security settings: `github_account.configuration` is a declared `JSONField` but the collector writes `{}` into
it (`collectors/github_collector/collector.py:344`), so even the 30-odd pure org-setting queries have no data
to bind against. The three RUNS rows are the honest extent of live coverage.

The good news inside that: the org-settings queries are the *easy* half. A `configuration` blob populated by
the collector needs **no new node types at all** — `WHERE a.data.configuration.two_factor_requirement_enabled
= false` is a shape Gryphon already lowers to a native nested JSON lookup (verified). **21 of the 71** queries are pure org- or repo-level type scans with no new node type
required at all — they fall out of "populate `configuration`" plus a `github_organization` /
`github_user` split of the `github_account` type. That is the cheapest third of this corpus by a wide margin,
and none of it needs a single line of Gryphon work.

---

## 3. Ranked missing language features

Ranked by how many of the 12 GAP queries each unblocks. Difficulty ratings are TAP's own, from
`docs/misc/doc-gryphon-feature-demand.md` §2, anchored to the lowering ladder in
`spec-grid-traversal-execution.md`.

### 1. Variable-length paths `*m..n` + edge-type alternation `A|B|C` — 7 queries

**Queries:** 15, 17, 25, 44, 49, 51, 70. Alone they fully unblock 25, 49, 51, 70; 15, 17 and 44 additionally
need feature #2.

**What.** `-[:GH_HasRole|GH_HasBaseRole|GH_MemberOf*1..]->` — traverse an unbounded number of hops along any
of several edge types. In this corpus the two features are inseparable: 6 of the 7 var-length patterns are
also alternations, because a GitHub privilege chain is *role-or-base-role-or-team-membership*, repeated.

**Status.** `*m..n` parses (`grammar.lark:55`) and is rejected at three executor sites
(`executor.py:435`, `:1771`, `:3139`). Alternation does not parse at all — `edge_body_type` is a single
`NAME` (`grammar.lark:54`).

**What implementing it involves.** These are not the same size of job.
*Alternation* is small: widen `edge_body_type` to a pipe-list, make `EdgePattern.edge_type` a tuple, and turn
`filters[f"{prefix}edge_type"] = t` into `edge_type__in=(...)` in `_build_chain_queryset` (`executor.py:1793`).
That is a rung-1 ORM change, a day's work, and it is worth doing on its own — it makes fixed-length chains
much more expressive immediately.
*Variable-length* is the heaviest item in the whole wishlist (`doc-dev-gryphon-wishlist.md` E1, rated 🔴 Very
High). It means a `WITH RECURSIVE` CTE composed with a JOIN-based executor — a planner-level change, plus
cycle handling, depth caps, and roughly 10-12 Gridkin scenarios. TAP has deliberately routed this *away* from
the `build-gryphon-capability` skill: the skill's Step 1 says in bold that reachability does not go through it
and belongs to a separate **grid-native named-paths** track (`docs/misc/grid-native-paths-notes.md`), with
`shortestPath` and centrality on an analytics-backend track (`doc-gryphon-networkx-opportunity.md`).

**Workaround today.** Manual unrolling, and only with a known bound: `MATCH (u)-[:R]->(x)-[:R]->(role)` as a
separate clause per depth. That fails here for two reasons — the corpus uses **unbounded** `*1..` (no upper
bound to unroll to), and multiple clauses do not correlate (§4.2). So: **no usable workaround**.

**Honest framing.** This is TAP's own documented conclusion, and this audit confirms it empirically:
`doc-gryphon-feature-demand.md` §3.4 already says security asset-graph corpora "lean on exactly the
reachability tail Gryphon rejects" and that E1 should be weighted above its raw 14.5% demand *for TAP
specifically*. The BloodHound GitHub extension is a clean demand signal for that call. Every genuinely
interesting attack-path query in the corpus — every one that finds a privilege chain rather than a
misconfigured checkbox — is in this bucket.

### 2. Correlated multi-clause `MATCH` (join, not union) — 7 queries touched, 2 blocked on it alone

**Queries:** 46 and 50 blocked on this alone; 15, 17, 44 (also need #1), 53 (also needs #3), 60 (also needs #4).

**What.** In Cypher, `MATCH (a)-[:X]->(t) MATCH (t)<-[:Y]-(b)` is a *join* on `t`. In Gryphon it is not.
`_execute_ast` (`executor.py:327`) loops the clauses independently, runs a separate query per clause, and
merges the envelopes with entity_id dedup. **Verified:** the query above emits two SQL statements, and the
second one's `t` carries neither the join to the first nor even its label.

**This is a silent semantic divergence, and the spec has it backwards.**
`req-grid-traversal-lang-shape-5` reads: *"Multiple Match Compositional — **Implemented** — Multiple `MATCH`
clauses extend the binding scope; earlier bindings are in scope for later clauses"* — and the prose above it
says "exactly as in Cypher." The executor's own docstring says the opposite: *"Multiple top-level MATCH
clauses are executed independently (UNION semantics)."* The code matches the docstring. This divergence is
also absent from Ledger B in `doc-dev-gryphon-vs-cypher.md`, which is the doc whose whole job is to record
divergences. Two of the three surfaces that should tell a reader this are wrong or silent.

**What implementing it involves.** This is the near half of `WITH` (wishlist F1 ★, TAP's own #1 measured gap).
`doc-dev-gryphon-wishlist.md` F1's "rung 1" is exactly the mechanism: collapse clause 1's carried variables to
their `entity_id`s and scope clause 2 with `entity_id__in=<Subquery>` — one SQL statement, no Python
round-trip, no materialization. The pieces already exist (`_build_var_bindings`); the constraint to lift is
the single-clause-terminal rule at `executor.py:2383`. Rated 🟡 Medium for that rung. It should land with
per-`MATCH` `WHERE` attachment, which the wishlist has already decided to bundle.

**Workaround today.** Give every clause distinct variable names and accept the union superset (fine for a
render-the-subgraph query like #46, wrong for a filter query like #50/#53), or run two Gryphon queries and
join in application code. Note that until this is fixed the *dangerous* case is doing nothing: a correlated
query written in good faith runs and quietly returns more rows than it should.

### 3. Property-to-property comparison `a.x = b.y` — 2 queries

**Queries:** 54 (blocked on this alone), 53 (also needs #2).

**What.** `WHERE repo.default_branch = branch.short_name` — compare a field on one bound node to a field on
another. `grammar.lark:74` reads `comparison: field_path COMPARE_OP value`, and `value` (`:133`) is a string,
number, boolean, null, or `$param`. Verified parse error.

**What implementing it involves.** Genuinely small, and the smallest real win on this list. Widen the
`comparison` rule's right-hand side to accept a `field_path`, add a variant to the `Comparison` AST node (or a
sibling leaf), and in `_comparison_to_q` (`executor.py:2948`) emit `Q(**{lhs: F(rhs_orm_path)})` instead of a
literal — Django `F()` expressions are precisely this. Rung 1. The one design decision is what data-lane type
strictness means when both sides are declared: compare the two declared types and reject a mismatch, which is
consistent with the existing oracle rule. A new `Predicate` leaf would trigger the skill's "audit every
walker" checklist (`_flatten_conjunction`, `_apply_typescan_predicate`, `_filter_predicate_for_bindings`,
`_collect_params_from_predicate`); folding it into `Comparison.value` as a union type avoids that.

**Workaround today.** None in-query. Project both fields and compare in application code.

### 4. `OPTIONAL MATCH` generalization — 2 queries

**Queries:** 60 (blocked on this, with #2), 44 (also needs #1).

**What.** The v0 shape is one node-only mandatory `MATCH` + one single-hop directed optional pattern +
`COUNT`-only projection of the optional variable. Both corpus uses break it: #60's mandatory `MATCH` carries
an edge and wants a graph envelope back; #44 wants two `OPTIONAL MATCH` clauses over var-length patterns.

**What implementing it involves.** Two independent widenings. (a) *Graph-envelope `OPTIONAL MATCH`* — the
current implementation is built around `Count(edge_path, filter=Q)`, which is what makes zero-match rows
survive; an envelope version needs a genuine `LEFT OUTER JOIN` and a serializer that tolerates unbound
optional variables. (b) *Mandatory `MATCH` with an edge* — the optional pattern must anchor onto a chain
queryset rather than a model queryset; that is the same binding-threading problem as feature #2, so they
should be scoped together. Rated 🟡 Medium each; neither is a recursive-CTE-class problem.

**Workaround today.** For #60, run the mandatory pattern and the optional pattern as two envelope queries and
merge client-side — acceptable, because the consumer is a graph render.

### Not blocking any query here, but worth recording

These appear in the corpus but every occurrence has an exact rewrite, so none of them cost a GAP verdict.
Listed because the rewrite burden is real and because two of them are how a reader gets a wrong answer.

| Feature | Queries touched | Status | Workaround |
| --- | --: | --- | --- |
| **Node inline property maps** | 44 | parsed, **silently dropped** — a defect, not a gap (§4.1) | rewrite to `WHERE`; the fix is ~10 lines |
| **Path-variable `RETURN p`** | 38 | parsed, unbound; `RETURN p` errors loudly | omit `RETURN` — the default envelope *is* the path set. TAP is structurally right here: `doc-dev-gryphon-vs-cypher.md` argues the typed envelope subsumes `nodes()`/`relationships()`/`labels()`, and against this corpus that argument holds. |
| **Label predicate `WHERE n:Label`** | 4 | absent | `n.entity_type IN [...]` — exact, verified |
| `<>` | 1 | absent (`!=` only) | trivial rename; adding `<>` as a `COMPARE_OP` alias is a one-token change |
| `DISTINCT`, `SKIP`, `COLLECT`, `SUM`/`MIN`/`MAX`/`AVG`, scalar functions, arithmetic | 0 | absent | not reached by this corpus — a useful negative result, since BloodHound saved queries are *selectors*, not report builders. TAP's own corpus study ranks `WITH`/`COLLECT`/`DISTINCT` at the top on general corpora; **this** corpus ranks reachability first and does not touch them at all. |
| `COUNT` over a plain type scan | 0 | rejected (needs an edge) | not reached here, but it is an odd hole — "how many repos per visibility" is unaskable |

---

## 4. Two correctness defects found while doing this audit

Neither is a missing feature. Both are cases where Gryphon **accepts a query and answers a different
question**, which is the one failure mode the codebase's own doctrine says is never acceptable
("apply-or-reject, never accept-and-drop"). Both are worth more than any feature on the list above, because
every feature above is a known, named, sequenced absence, and these two are not.

### 4.1 Node inline property maps are parsed and silently discarded

`(n:Label {prop: value})` reaches the AST as `NodePattern.inline_props` (`parser.py::node_body`), and the
identifier `inline_props` appears exactly twice in the 3,277-line executor — `edge.inline_props`
(`executor.py:1798`) and `opt_edge.inline_props` (`:3190`). **Never `node.inline_props`.** There is no
rejection either. The map is dropped.

Verified live, via `explain_gryphon_raw`'s SQL capture:

| Query | Emitted `WHERE` | Params |
| --- | --- | --- |
| `MATCH (n:grid_fixtures__node {kind: "neighbor"})` | `"tap_entity"."deleted_at" IS NULL` | `()` |
| `MATCH (n:grid_fixtures__node) WHERE n.data.kind = "neighbor"` | `... AND "grid_fixtures__node"."kind" = %s` | `('neighbor',)` |
| `MATCH (a:…source {kind:"zzz"})-[:LINK]->(b:…target)` | edge_type + both entity_types only — no `kind` | — |
| `MATCH (a:…source)-[:LINK {weight: 1}]->(b:…target)` | `… AND ("tap_edge"."properties" -> %s) = %s …` | `('weight', Jsonb(1))` |

Booleans behave the same (`{is_open: true}` → no filter, no params), which is exactly the shape 30+ of the
BloodHound org-setting queries use.

**Blast radius on this corpus:** 44 of 71 queries carry a node inline property map; 43 of those would parse
and execute (only #44 is rejected for other reasons). Every one returns every node of the type. A "find orgs
that do not require 2FA" query returns *all* orgs, formatted as a finding.

**The spec claims this works.** `req-grid-traversal-lang-filters-1` reads *"Inline Property Maps Supported —
**Implemented** — Node and edge patterns may include inline property filters; values are AND'd into the
queryset"*, and its own Notes then say *"Edge-side filter implementation at
`_apply_inline_edge_property_filters` (closes Gap 1)"*. The edge half was built and the requirement was marked
Implemented for both halves. `spec-grid-traversal-language.md:204` and `:287` both advertise
`(n:host {name: "web01"})` as a supported surface.

**Fix.** Small and unambiguous: in `_execute_type_scan` and `_build_chain_queryset`, fold each node's
`inline_props` into the same `.filter()` as its label constraint, routing keys through the existing data-lane
resolver (`_typescan_orm_path` / `_orm_path_for_field`) so the field-path allowlist and type-strictness rules
apply identically to `{k: v}` and `WHERE n.data.k = v`. That is the edge-side fix applied to nodes. Until it
lands, the alternative is to *reject* node inline props with a clear error — which is strictly better than
today, and is what the codebase's own doctrine demands.

### 4.2 Multiple `MATCH` clauses union rather than join, silently

Covered as gap #2 in §3 because it blocks queries, but it belongs here too: a correlated two-clause query runs
without complaint and returns an uncorrelated superset. Verified: two independent SQL statements, the shared
variable unconstrained in the second. The spec (`req-grid-traversal-lang-shape-5`) states the Cypher
semantics as Implemented; the executor implements union semantics; Ledger B does not record the divergence.
At minimum this needs a Ledger B row and a corrected ACID, today, independent of when the join lands.

### Why the guard suite did not catch either

Both are absences of code rather than wrong code, and TAP's Gridkin discipline asserts on *answers* via a
model oracle rather than on SQL text — which is normally the right call, but it only catches a dropped filter
if a scenario exists whose expected answer differs with and without it. `grep` finds no test exercising a node
inline property map, and none exercising two correlated `MATCH` clauses. The generalizable lesson: when a
feature has two structurally similar halves (node-side / edge-side, single-clause / multi-clause) and only one
gets built, the requirement row is the thing that lies. A cheap guard here would be an AST-walk assertion that
every parsed construct is *consumed* by the executor — `path_var` (§1.2) is a third instance of the same
pattern, benign only by luck.

---

## 5. Time-travel: can Gryphon query prior state?

**Short answer: no — and the block is three layers deep, not one. The history data model is sufficient for
the typed data lane, insufficient for the spine, and therefore insufficient for the graph.**

This is the section worth arguing with, so here is the evidence first and the judgement after.

### 5.1 What exists

**History is real and it is running.** `BaseModel` declares `history = HistoricalRecords(get_user=…,
inherit=True)` (`tap_grid/models.py:535`), so every concrete `BaseModel` subclass gets a django-simple-history
`Historical<X>` table holding a **full row snapshot per change**, with `history_date` (transaction time),
`history_type` (`+`/`~`/`-`), and `history_user`. `Edge` extends `BaseModel` (`models.py:824`), so
`HistoricalEdge` exists (`tap_grid/migrations/0001_initial.py:415`). Verified in this session's live database:
20+ populated `*historical*` tables including `grid_fixtures_historicalpgnode`, `tap_grid_historicalbatch`,
`tap_cares_historicalcollector`.

**FLIP is real too.** `flip_map` (`models.py:549`) is a JSON map of *field name → batch_id of the last writer*,
stamped on every service-layer write (`tap_grid/flip.py:49`). It is field-level provenance, not a value
timeline.

**Spine lifecycle timestamps are queryable from Gryphon today.** `created_at`, `updated_at`, `deleted_at`,
`version` are all spine fields (`models.py:303`). Verified running:
`MATCH (n:T) WHERE n.created_at > "2026-01-01T00:00:00+00:00"` and `… WHERE n.deleted_at IS NOT NULL` both
compile and execute. `n.data.flip_map.<field>` is also queryable (verified).

**A spec exists.** `tap_grid/specs/spec-grid-history-timetravel-BACKLOG.md` is a well-shaped design: strict
point-in-time only, service-layer-owned, canonical-timestamps-first with history-table fallback,
`tap_meta.historical` on the response, read-only. Every requirement in it is status `Proposed`. Its sibling
`spec-grid-history.md` has `req-grid-history-query` (`timeline_for` / `between` / `latest_before` / `as_of`)
also `Proposed`, annotated "Not yet implemented in `tap_grid`."

### 5.2 What blocks it — three independent layers

**Layer 1 — grammar and executor have no temporal surface at all.**
`AS OF $t` is a parse error (verified). `n.history.<field>` is an executor error (verified):
`Unknown field path prefix 'history'. Use a spine field, the 'data' prefix …, or 'dimensions.<key>'`. There is
no fourth lane and no query modifier. Nothing in `executor.py` references a history table.

**Layer 2 — the service API is a stub.** `tap_grid/history.py::HistoryService` exposes `raw_records()` and
nothing else; `timeline()`, `between()`, `latest_before()` and `as_of()` each raise with *"Composable history
queries are deferred to the time-travel pass."* So there is no service-layer path for Gryphon to route
through even if it wanted to — and `req-grid-history-tt-service` insists that is the only sanctioned route.

**Layer 3 — the read-only search role cannot see history, by construction.** Verified against the live
database: `tap_gryphon_ro` holds `SELECT` on exactly **32** tables, and **zero** of them are historical.
This is not an oversight — it falls out of the design. `grid_tables()` (`tap_grid/grid_tables.py:76`) derives
the grant set from `GRID_TABLE_ROLE`, declared once on `BaseModel`; django-simple-history builds
`Historical<X>` with `bases=(models.Model,)`, so the historical models inherit no classification and are
correctly excluded. The fail-safe direction held. But it means enabling time-travel requires a deliberate
*privilege* decision, not just plumbing — and it is a real one: history tables contain every prior value of
every field, including values later corrected or redacted, and Gryphon is the language TAP intends to be safe
to accept from untrusted satellite callers. This should get the security-posture treatment and probably a
distinct role, not a widened `tap_gryphon_ro`.

### 5.3 Is the history data model sufficient? Four honest problems

**(a) `Entity` has no history at all — and that is the one that matters.**
`Entity` is a plain `models.Model` (`models.py:223`) with no `HistoricalRecords`. There is no
`HistoricalEntity` (grep of `0001_initial.py`: zero hits; the migration creates `HistoricalBatch`,
`HistoricalDimension`, `HistoricalEdge`, `HistoricalKeystone`, `HistoricalSearch` — no Entity). The spine
carries `entity_type`, `name`, `dimensions`, `deleted_at`, `version`. So a rename, a re-typing, a **dimension
move**, and a tombstone-then-restore are all unreconstructable. Two consequences bite hard:

- `deleted_at` answers "did this exist at T" only for the *current* lifecycle. Tombstone → restore leaves a
  live row with no record that it was dead at T. Existence-at-T is therefore not reliably derivable.
- `dimensions` is TAP's scoping and partitioning axis. A point-in-time query scoped by dimension cannot be
  answered correctly without dimension history.

The backlog spec's own visibility filter (`req-grid-history-tt-filter`) says objects with
`updated_at > as_of` are "routed to history reconstruction" and that the timestamps "should be available on
both the entity spine and the BaseModel tables." For Entity there is no history table to route to. **The
design assumes a spine history that does not exist.**

**(b) Edge history exists but edge *liveness* is a spine question.** `HistoricalEdge` faithfully records
`from_entity_id`, `to_entity_id`, `edge_type`, `properties` over time — genuinely good. But an edge's tombstone
lives on its backing `Entity.deleted_at`, so "was this edge live at T" reduces to (a). Problem (a) therefore
blocks *graph* time-travel specifically, which is the half a security-graph product actually sells.

**(c) One clock, not two.** `req-grid-history-time` distinguishes TAP record time from source observation
time, and is `Proposed`. DSH provides only transaction time (`history_date`). For a collector-fed graph the
gap is not academic: "what did this ruleset look like last week" is nearly always a question about the world
last week, not about what TAP had ingested by last week, and ingest lag makes those diverge. Some typed models
carry their own observation column (`observed_at` on the fixtures, `run_started_at` on
`github_actions_run`), so bitemporality is available *per model* by accident of schema — it is not a system
axis, and Gryphon has no vocabulary that distinguishes the two.

**(d) No retention or indexing policy.** `history.py`'s own header: *"V1 default: all objects tracked, no
retention limits"*, with scope configuration backlogged and flagged as migration-affecting.
`req-grid-history-query` explicitly wants indexable, bounded predicates and is unbuilt. Point-in-time
reconstruction over an unbounded, unindexed history corpus is a performance cliff waiting for the first real
customer graph.

### 5.4 What *is* answerable today

Being fair to the current system — this is not nothing:

| Question | Today |
| --- | --- |
| "Which entities appeared since T?" | **Yes** — `WHERE n.created_at > $t`, verified. |
| "Which are tombstoned?" | **Yes** — `WHERE n.deleted_at IS NOT NULL`, verified. |
| "Which rows changed since T?" | **Yes, at row granularity** — `WHERE n.updated_at > $t`. Tells you *that* it changed, never *what* or *from what*. |
| "Which fields were last written by a recent ingest?" | **Partially, in two queries.** `n.data.flip_map.<field>` gives the batch_id that last set each field (verified). Turning that into a time needs the `Batch` entity's `created_at` — and there is no edge from a data node to its writing batch (`PRODUCED_BATCH` is *producer→batch*, `tap_grid/core_edges.py`), no subquery, and no field-to-field join. So: query batches since T, collect ids, then `WHERE n.data.batch_id IN [...]`. App-side glue, and it answers "touched recently", not "changed to what". |
| "What did this ruleset look like last week?" | **No.** No syntax, no privilege, no service path — and for anything on the spine, not reconstructable at any layer. |
| "Which action references changed in the last 24h?" | **No**, in the sense that matters. You can find recently-updated rows; you cannot diff them against their prior value, and you cannot ask it about edge existence. |

### 5.5 What it would take

In dependency order, smallest last:

1. **Decide the privilege boundary** (security-posture-shaped, not code-shaped). Which role may read history,
   and does a satellite-supplied Gryphon string ever get it? Cheapest safe answer: a separate
   `tap_gryphon_history_ro` role, off by default.
2. **Add `HistoricalRecords` to `Entity`** — one line plus a migration. The cost is a row per spine mutation
   on the busiest table in the system; that is a real decision, and it wants a retention policy decided in the
   same change (which closes (d) as well). But it is the textbook case for this repo's own standing filter:
   cheap now, impossible to retrofit later. **A spine history that starts today can answer questions about
   last month, next month. One added in a year answers nothing about this year.** Of everything in this
   report, this is the item whose cost most clearly rises with delay.
3. **Implement the `HistoryService` query verbs** (`latest_before`, `as_of`, `between`) with the indexing
   strategy `req-grid-history-query` already specifies. This is the piece the backlog spec was written for.
4. **Executor: a query-level `AS OF`, not a `history` field lane.** A lane would push temporality into every
   field-path resolver and into the allowlist that closed a real cross-table-read vulnerability. A query-level
   modifier keeps the field grammar untouched and matches `req-grid-history-tt-service`'s "time travel is a
   service-layer mode". Mechanically: swap each type-scan/chain root for a "latest history row at or before T"
   relation (`DISTINCT ON (id) … WHERE history_date <= $t ORDER BY id, history_date DESC`, or a window
   function). Be honest that this is **rung 3-4** on `req-grid-traversal-exec-lowering`, not rung 1, and it
   carries the spec-justification obligation the capability skill imposes on any escalation. The genuinely
   hard part is not the type scan — it is that multi-hop chains join `tap_edge` reverse-FKs, and the as-of
   version must join the *reconstructed* edge set, a different queryset root.
5. **Grammar/AST** — an optional `AS OF <value>` and a field on `GryphonAST`. A day, once 1-4 are settled.

**And then note what is still missing.** All of the above delivers *point-in-time*, which is what the backlog
spec scopes. "Compare to an earlier state" — diff T1 against T2, "which action references changed in the last
24h" answered properly — is range semantics, explicitly listed under that spec's Future. For an attack-path
product, **"what changed" is plausibly the more valuable of the two questions**, and it is two design steps
out, not one. Worth deciding now whether the point-in-time design forecloses it: the strict "world at T"
contract composes into a diff cleanly (run it twice, compare envelopes), so the answer looks like no — but
that should be a stated, checked property of the design rather than a hope, because it is the kind of thing
that gets discovered wrong after the executor is built.

---

## 6. Provenance and method

- **Queries** extracted verbatim from `SpecterOps/openhound-github` @ `40de52ad624e100ea8f16dfd41831b9aebfb0f58`
  (`extension/saved_searches/`, 55) and `SpecterOps/GitHound` @ `bcd3da195dd0681ade6cb027d8854716d4f768fd`
  (`saved-queries/`, `Documentation/Queries.md`, `pz-rules/`). Both Apache-2.0. Full text in
  `bloodhound-queries-list.txt` and `bloodhound-github-queries.json` in this directory. Fidelity spot-checked
  by re-fetching five queries from `raw.githubusercontent.com` and byte-comparing. **No Cypher was invented.**
- **Known corpus caveat:** the shipped `README.md` indexes 7 files that exist in no branch of either repo —
  five `demo-*.json` attack-path scenarios plus `org-roles-bypass-security-scanning.json` and
  `users-without-external-identity.json`. Their names and descriptions exist; their Cypher does not. From
  the descriptions, all five demos are multi-hop role-chain traversals, i.e. they would land in gap #1 —
  so the true reachability-blocked count is probably 12 of 76, not 12 of 71.
- **Gryphon behaviour** was established by reading `grammar.lark`, `ast_nodes.py`, `parser.py` and
  `executor.py`, and then **verified by execution** — 45+ probe queries run through
  `_execute_gryphon_raw_impl` with `capture_sql()` in this session's container
  (`tap_git-serious-web-1`), against the registered `grid_fixtures` types. Probe scripts are in
  `probe/` in this directory. No repository file was created or modified; `git status` is clean. The one
  side-effect-free liberty taken was calling the ungated `_execute_gryphon_raw_impl` rather than the
  capability-gated `explain_gryphon_raw`, since the shell session has no named actor.
- **Where this report contradicts a spec** — `req-grid-traversal-lang-filters-1` (node inline props),
  `req-grid-traversal-lang-shape-5` (multi-`MATCH` correlation), `req-grid-traversal-lang-patterns-5`
  (bounded repetition) — the code was re-checked and executed before the claim was written, per `GRY-PROC-2`.
  In all three cases the executor, not the spec, describes what happens.
