# Grid Reconciliation: Tombstoning, Scope, and Falsifiability — Design

Captured 2026-09-14/15 from a one-case-at-a-time walk-through between George and the
double-tap-git-serious session, converged with demo-dev's reliability work. **This is a design
document, not a spec.** It records rulings as rulings and open questions as open, so that the spec
carved out of it can be marked Proposed only for what is actually settled. **The spec pass has now
happened** (2026-09-15): `tap_grid/specs/spec-grid-reconcile.md` (new — `req-grid-reconcile-terminology`,
`-observation-lifetime`, `-evidence`, `-candidates`, `-falsifier`, `-verb`, `-hysteresis`),
`req-grid-entity-natural-key` in `spec-grid-entity.md`, and `req-grid-service-delete-reason` /
`req-grid-service-delete-cascade` in `spec-grid-service-delete.md`. Where this document and a
requirement disagree, the requirement wins; this one keeps the reasoning and the rejected
alternatives. Sections marked **RULED** carry
the date and are not re-litigated here; sections marked **OPEN** are the remaining design work, in
every section ruled 2026-09-15 except the falsifier's mechanics, which are proposed below with the open implementation questions named.

Companion reading, in order: `tap#140` (grid mutability — the core epic), github-core#14
(reconciliation — the seven absence shapes per type), github-core#15 (visibility assessment),
github-core#131 / PR# 129 (reliability: gather → confirm → process; degrade per layer; degradation
is never absence), the staged-collection joint proposal (comment on github-core#136), and the three
briefings *Here There Be Elephants*, *The Keys, Not the Code*, *The Walk-Down*.

## Terminology, before "life" is used again

The review's first recommendation, and it is a fair one: three things in the first draft sometimes
meant the same word. They have different lifetimes, and a permission gap ends one without ending
the others.

| Term | Means | Lifetime ends when |
| --- | --- | --- |
| **source object** | the thing in GitHub | GitHub deletes it (which we may never observe) |
| **source incarnation** | a particular existence of it under a reused name | the source itself issues a new identifier for a new thing under the old name |
| **observation lifetime** | *our* record of observing it, from first sight to retirement | we drop it from observation (deleted, private, transferred, withdrawn from scope) |
| **Entity id** | the row and the observation lifetime — assigned uuid7 | never reused; a tombstone is terminal |
| **natural key** | derived correlation handle for the source object, invariant across dimensions | only when its key *document* is redefined (a recorded migration) |
| **perspective** | which observer, from where — carried in dimensions | future work; see the deferral note |
| **scope** | what one run's credential was permitted to weigh in on | per run; the `collection_scope` node |
| **record version** | `Entity.version`, a monotonic counter over canonical mutations | never; it only increments |

The load-bearing consequence: **a returning row is a new observation lifetime, not a new source
incarnation**, unless source evidence actually establishes the latter. A permission gap is not a
rebirth of the repository.

## The problem, stated once

The collector is additive-only. Every run upserts what it found; nothing compares "what I found"
against "what is on the grid." A deleted repository, a removed workflow, a decommissioned runner
stays on the grid indefinitely, looking exactly as live as a real one, and every collection makes
the grid a less trustworthy answer to "what does this account have." git-serious observes a system
that changes constantly, so an additive-only view is wrong about the thing the product exists to
show.

The naive fix — delete what this run did not see — is wrong in the opposite direction: "not found"
also means a failed call, a narrowed credential, a truncated page, a rate limit, a plan boundary.
GitHub is a transient, incomplete, untrustworthy dependency, and absence of evidence must never
render as evidence of absence. Everything below is the discipline that lets a run retire a node
only when it has *earned* the right to.

## Root of trust, then the tree — RULED 2026-09-14

**Any token we are given is a valid starting point** — an org App, a personal App, a single-repository
fine-grained PAT. The collection always **starts at the root of the tree** (platform → account →
repositories → per-repository surfaces → derivations) regardless of the credential's shape; the
credential decides *how far in we can see*, and every step records whether it could introspect.
Landed: github-core#139 (the combined credential kind accepts a repos-only scope), #140 (a
repos-only list is resolved before the loop), #141 (the run records what its credential may reach).

**Abort only when something named by configuration cannot be found:** the org in owner mode (404
*or* 403 — either means the run's premise is wrong; "there's likely a config issue that needs to be
dealt with"), a listed repository in repos-only mode (404 — which GitHub also answers for a private
repository the credential may not see; the message says so and never claims "does not exist").
Everything else that cannot be read is a recorded fact at that step, never an abort.

## Staged collection — RULED 2026-09-14 (jointly with demo-dev)

A *tier* is a named set of surfaces; a tier is complete iff every surface gather in it completed
**and** its own surfaces completed; the Confirm gate writes one verdict per tier at the tier's end,
before the next tier starts. (Tier completeness describes *the tier*; it is **not** the falsifier's
gate — that prerequisite is read per parent, see *The prerequisite is per parent* below.) Tiers are depth in the containment tree: T0 credential + scope
(single-flight acquired here) → T1 the account, once, first → T2 the repository listing, its own
cheap query, count-checked against the account's reported repository counts → T3a account-declared
surfaces → T3b repository-declared surfaces (the heavy GraphQL, adaptive pages) → T4 executed
surfaces (never tombstoned on absence) → T5 cross-repository derivations (re-derived, not falsified).
Falsify T2 → T3a → T3b outer-in, each only if its own listing for that parent completed and the
parent tier completed. Full table with every manifest source placed: the joint proposal on
github-core#136; lands in reliability 1b.

**The descent table is hardcoded for now.** (parent type, containment edge, child type, tier) is a
table in github_core's collection manifest that the fan-out walks; call order is derived from it,
never authored in `run()`. The meta-graph over models and edges — one `containment` bit per edge
type in the registry, from which the same table could be *derived* — is the make-it-right pass
(cousin of `docs/misc/grid-native-paths-notes.md`), explicitly deferred.

## The scope statement — RULED 2026-09-14; building as github-core#145

What a run was **allowed to weigh in on** is a node: `collection_scope`, one per run, on the
**operation** side of dcom. It is perceived-true-at-a-time — an App's grants can be narrowed in a
settings page and nothing tells the collector — so it is immutable history, never re-derived, and
its sequence over time answers "when did we stop being able to see X." It points at the run
(`collection_job`) and at the installation configuration it read, and records the three inputs it
was derived from (our manifest's required permissions, their granted permissions, their plan) so a
change in verdict is attributable to *we asked for more* versus *they granted less*.

Carries: `selection` (the installation's repository selection — `all` / the exact `selected` ids /
`unknown`; a PAT of either kind is `unknown` until measured; a `total_count` that disagrees with
the walk is `complete: false`), `visibility` (github-core#15's per-type reachable / degraded /
unreachable / unknown — a declared, empty seam until #15 lands), and `tiers` (1b's per-tier
verdict, per-surface detail nested, closed reason vocabulary:
`complete · truncated · forbidden · errored · filter_unverified · count_mismatch ·
prerequisite_incomplete · not_attempted` — a declared, empty seam until 1b lands). The falsifier
reads this node, through the service layer; never the run's results JSON.

**A scope statement is a completeness statement, not "the run succeeded" — added 2026-09-15.** The
closest applicable research is Darari et al. on completeness statements for RDF/SPARQL: an explicit
statement that a particular *relation*, under a particular *filter*, for a particular *subject*, is
complete — which is what makes it sound to answer a negative query from incomplete data. "The run
finished" is not that claim. So each surface's entry names the relation (`OWNS_REPO` from this
account), the filter (this installation's selection; `type=all`), the parent it is about, and the
interval it covers, alongside the five evidence attributes. That is the object a falsifier reads
before it trusts a missing item, and it is also what a Player-3 reader needs in order to phrase an
honest negative answer.

## What a tombstone means — RULED 2026-09-14

**DROPPED_FROM_OBSERVATION, under scope S. Never "deleted."** If we can't see it, it's dead to us:
deleted, made private, and transferred to another org all receive the same tombstone, because from
this instance's vantage they are the same fact. **Narrowing out of an installation's selection is a
separate case with separate evidence** — see *Withdrawal is not absence*, below. The word on the node,
in the event, and on every page is *unobserved*, so that a repository that merely went private is
never rendered as deleted. This is a documented gap, and documented behavior with known gaps is
sufficient at this stage.

**Five evidence attributes, not one word — RULED 2026-09-15.** "Complete" was carrying five
distinct claims, and finishing pagination proves only the first two. Kubernetes promises a
consistent paginated snapshot anchored by a collection `resourceVersion`; GitHub's pagination
documents cursors and traversal and makes no such promise, so rows can move across a cursor
boundary mid-walk and two equal-sized sets can hold different members. Each surface therefore
records, separately:

| Attribute | The claim | How it is established |
| --- | --- | --- |
| `scope_authorized` | this credential was permitted to ask | the scope statement × the manifest's permission triple |
| `enumeration_complete` | the walk reached the end of the chain, uncapped | the client's own verdict, plus the positive control on any filter |
| `source_consistent` | the rows came from one coherent source snapshot | **only** where the source promises it; otherwise `unknown` |
| `observation_interval` | between when and when the surface was read | first and last request timestamps |
| `admitted` | the gather passed Confirm and reached a shaper | the Confirm gate |
| `applied` | the observations derived from it were **shaped and committed** | the write batch's result |

`admitted` deliberately stops short of persistence, so it cannot stand alone: a shaping failure, a
rejected batch or an unresolved endpoint leaves a surface that "passed Confirm" and landed nothing.
**A surface whose observations did not commit is not reconcilable** — either observations and
removals commit together, or a retirement requires `applied` plus the freshness fence. An unchanged
successful observation counts as applied: a no-op upsert is still an observation, and by the
re-observation-is-not-change ruling it may not bump `Entity.version` — which is precisely why the
fence, and not the version, is what protects the decision.

A count check against the parent's reported total stays as a **rejection** control — a mismatch
refuses the verdict — but its success is not proof of snapshot consistency. Where
`source_consistent` is `unknown`, the type's absence policy must say what substitutes: for a
repository, the **direct probe** (an independent second observation of that identity), which is the
evidence-strength ladder doing the work a clock would otherwise be asked to do.

**Deletes only after a complete listing at the granularity of the decision.** Completeness is per
surface, not per run: the org listing can fail while repo A's workflow listing completed, and A's
unobserved workflows may be dropped while repositories may not — **provided the prerequisite is read
per parent, not per tier** (see the falsifier section). Per-object positive checks — a
direct probe answering not-found under a scope that would have seen it, the commit that removed a
file, a deletion event — are complete by being one response. Cascades inherit the parent's
completeness. A partial listing is no evidence. A complete listing whose count disagrees with the
parent's reported count is complete-and-wrong: record it, tombstone nothing.

**Candidates are the fan-out from the parent node**: `account → OWNS_REPO → repository`, minus what
this run observed, minus anything outside the installation's selection. No per-node observation
stamps; the topology is the record of what the grid last believed. The same traversal serves the
descent, the falsification pass, and the cascade.

**Withdrawal is not absence — RULED 2026-09-15, resolving a contradiction in the first draft.** The
draft said both that narrowing-out-of-selection *"receives the same tombstone"* and that candidates
are *"minus anything outside the installation's selection"* — the same input, opposite outcomes, one
retiring the row and the other leaving it live forever. Both halves were right for the case that
produced them and wrong as a single rule. The discriminator is **whether this perspective ever
observed the thing**:

| Case | Evidence | Outcome |
| --- | --- | --- |
| Observed under this perspective, now outside the selection | the **scope statement** (the selection shrank) — not a listing | End the observation. Tombstone, reason `scope_withdrawn`. |
| Never observed, outside the selection | none needed | Not a candidate. Nothing to end. |

These are different verdicts because they rest on different evidence. A withdrawal is proven by
comparing this run's `collection_scope.selection` against the previous one; it is not, and must not
be presented as, absence from a complete listing. Collapsing them was what produced the
contradiction.

**A withdrawal is not a shortcut around the machinery.** It routes through the same authority check,
the same freshness fence, the same cascade and the same audit record as any other retirement; only
the licensing evidence differs. And one trap to close explicitly: **an unknown selection must never
read as a shrunken one.** A run whose `selection.kind` is `unknown` — any PAT, per the
collection-scope contract — has no comparable predecessor claim and therefore withdraws nothing;
only a `selected` set compared against a previous `selected` set can establish that a member left.

**Where it lands.** The spine already has it: `Entity.deleted_at` (`req-grid-service-delete-tombstone`,
Implemented) with `.live()` / `.tombstoned()` managers, edge cascade at either endpoint, the delete
recorded in history as the object's final lifecycle event, patch/replace on a tombstoned entity a
conflict. The verdict's structured record goes in `BatchEvent.metadata` (a JSONField, already the
home of GRIFT's imperative-removal reasons); the one-line human reason goes in simple-history's
`history_change_reason`, which nothing in `tap_grid` sets today. **The one core change:
`delete_node()` gains an additive parameter that forwards a reason and metadata into both.** The
GRIFT importer's stance already matches: it never infers deletion from absence; removals are
imperative and reason-carrying.

## Resurrection — RULED OUT 2026-09-15

Considered at length and decided against: a tombstone is terminal, there is no restore verb, and
there will not be one. Every shipped system that tried to make the same name mean the same thing
across a deletion either built a Recycle Bin (Active Directory, a decade after tombstones) or grew
zombies (Cassandra, Kafka, AD's lingering objects); every system that made a returning name a new
thing with a new id got to stop thinking about it (Kubernetes' UID rule, AD's objectGUID, Datomic,
the OR-Set). A returning name is a **new node**. Continuity across lives, if anyone ever wants it
for historical search, is a query over tombstoned nodes sharing a natural key — not a mechanism.
Prior art: the *Lingering Objects* briefing.

## Identity — RULED 2026-09-15

The collision that made resurrection look necessary was a symptom of one choice: every node id in
github_core, git_core and aws_core is `uuid5(namespace, "<type>:<natural key>")`. That makes
identity a pure function of GitHub's facts — stateless collectors, idempotent upserts,
coordination-free cross-plugin references — and a pure function cannot express *lifetime*. For
anything with a lifecycle, uuid5 was a shortcut around one indexed lookup per type per run, and
the cost of the shortcut was every design problem in this document's first draft (and the earlier
hash-token fallout: change how a key is computed and every id on the grid churns).

**The rule (George, 2026-09-15): every entity id is a pure assigned uuid7. There is no `derived`
identity kind.** The earlier exception — uuid5 ids for content and immutable events — is withdrawn,
because it creates a dead end the review found: collect repository R and run 42; lose visibility to
R; the cascade tombstones run 42; regain visibility while run 42 is still inside GitHub's retention
window. Run 42's id is `uuid5("…github_actions_run:acme/widget#42")`, so it still addresses a
terminal tombstone — and neither patching that id nor re-minting it is legal. No deletion and no id
reuse are needed to produce the conflict; a permission gap and a retention window suffice. The same
exception also produced a flat contradiction in this document's first draft (`Entity.id` "never
derived" against "for derived types the natural key equals the id") and made perspective-local rows
impossible for exactly those types.

**Every place that used a uuid5 today is a candidate for a natural key plus a key document**, which
is where the coordination-free property actually belongs: a commit's oid, `(stable repository id,
run id)` for a run — **not** `full_name#42`, which would churn every run's key on a repository
rename, in violation of the stable-identifier rule below —
the platform's host. Two collectors holding the same facts still land on the same natural key with
no coordination — the only thing uuid5-as-an-id was buying — while the row, its lifetime and its
perspective stay the grid's to assign. Minted at first sight; thereafter found by
**lookup-or-mint** via `resolve(natural_key, dimensional_scope)` over live rows. A tombstoned row
is not found, so a returning key mints a new row with a new id: the "new life" falls out of the
lookup, with no machinery at all.

**Two keys on the spine — RULED 2026-09-15 (prior art: the *Surrogate and Glue* briefing).**
`Entity.id` is the row and the life: uuid7, minted at first sight, what every edge, FK, export and
history row points at, never derived. `Entity.natural_key` is the glue: derived, stored beside it,
plainly indexed, and **deliberately NOT unique** (George, 2026-09-15). Its whole job is to be *the
same across dimensions* — that is the correlation handle. Putting a perspective into the key would
give a network scanner's `host:443` and an onboard agent's `host:443` different keys and destroy
the one thing it exists for. Multiple live rows sharing a key is therefore the **intended** state,
not a violation to constrain against.

Lookup is `resolve(natural_key, dimensional_scope)`: the key selects the thing, the dimensions
narrow to the row for this observer.

**`resolve` has a deterministic contract — RULED 2026-09-15.** "Multiple matches are an application
concern" is not specifiable, and the identity switch needs a rule before it lands:

| Live rows of this type with this key | Behaviour |
| --- | --- |
| zero | mint a new row — first sight, or a return after retirement |
| exactly one | return it; the observation upserts onto it |
| more than one | **fail explicitly** (`AmbiguousIdentity`), naming the key and the rows |

**And lookup does not match on dimensions in the first slice** — it matches `(entity_type,
natural_key)` among live rows, full stop. The reason is this document's own evidence: dimension
values vary by *collection path*, not only by observer. The account node is minted once per
repository and carries whichever repository was walked last, so dimension-*equality* lookup would
miss its own previous write and dimension-*containment* lookup would match rows it should not. That
is a sequential defect, with no concurrency required. When perspectives exist, `resolve` gains an
identity-scope argument and the multiple-match case becomes the ordinary multi-perspective case;
until then more than one live row per key is a defect and is surfaced as one.

One correction to how the deferral was first justified: **it is a practical choice, not a
consequence of key invariance.** A dimension-invariant key is perfectly compatible with composite
uniqueness on `(natural_key, identity_scope)`. What blocks the constraint is that `identity_scope`
cannot be defined correctly today, because the dimension vocabulary mixes perspective, facet and
locator (evidence below). The honest claim is "we cannot define the scope yet", not "invariance
forbids the constraint". So the first
slice ships **one nullable column and one non-unique index**, no partial unique constraint, no
`identity_scope` column, no reserved perspective dimension.

**What that gives up, stated plainly.** Deterministic ids provided *implicit* uniqueness — same
facts, same id, same row, upsert by construction. Assigned ids plus lookup lose it: two concurrent
writers can both find nothing and both mint. Reliability's per-collector single-flight serialises
the common case (one collector, one run), and two *different* collectors are two perspectives
anyway, so the residual window is narrow — but it is real, and it is an app-level concern until
within-dimension uniqueness lands. Backfill should still *report* two live rows computing one key in
one dimension: not a blocker, but a latent bug worth seeing.

**Evidence that dimensions cannot carry identity today** (read from the 8010 grid, 2026-09-15):
the `unified-systems-com` account node carries `github.repo: zizmor-tap` — the last repository in
the walk — because the account is minted once per repository and last-write-wins
(`collector.py:1667`, *"owner+repo carried even on account"*). `github_app` rows have three
different dimension shapes depending on which code path minted them first (`Dependabot` repo-scoped;
`codacy-production` and `git-serious-exploratory` platform-only). `github_ruleset` deliberately omits
`github.repo` because an org ruleset governs many repositories. `github_workflow` uses it
constitutively — three workflows named "AI review" in three repositories. One key, three behaviours,
decided by code path. And none of the five keys github_core stamps names a *perspective* in the
sense the design means: `github.platform` is the only candidate. **The glue is never the identity:** nothing keys
on `natural_key` but lookup and correlation; every system in the record that stayed sane kept that
line, and every pain story — ours included — is the glue being used as the surrogate.

**Every model declares how its natural key is produced**, as class metadata beside `ENTITY_TYPE`:
the *key document* — the constituting properties (STIX 2.1's "ID contributing properties"),
canonicalized with RFC 8785 and hashed. **The fully-qualified type is a member of the document,
not a hidden namespace input** (George, 2026-09-15):

```
natural_key = uuid5(TAP_NATURAL_KEY_NAMESPACE,
                    JCS({"type": "<fully-qualified entity or edge type>", …constituting properties}))
```

One namespace for the whole grid, with the type inside the canonical JSON. The alternative — a
per-type namespace and no type in the document — hides an input: two authors could share a
namespace by accident and the collision would be silent and unauditable. With the type in the
document the key is fully determined by bytes a human can read, and a validator can compare
documents across types. Type names are already namespaced (`github_core__github_repository`), so
nothing further is needed to separate plugins.

RFC 8785 fixes serialization, not semantics. The key recipe must therefore also declare its
**normalization** before canonicalization: string versus number for ids (GitHub's numeric ids exceed
IEEE-754 safe integers, so they are strings), absent versus null, case folding, array ordering, and
Unicode form. And a **recipe version**, so a later change to a key document is a recorded migration
rather than silent churn. The recipe is the model's — a PURL under the package namespace, an ARN under
AWS's, a GitHub numeric id under github_core's, an oid straight through — and the slot is uniform.
**Constituting properties are the source's stable identifiers wherever it provides one**: a
repository keyed on its numeric id is renamed and transferred three times and remains one row with
three values of `full_name` in its field history — no alias, no chain. A name is a constituting
property only when the source offers nothing better (a ref, a secret, a check context), and then a
rename is a new node by design, which is what git itself says a branch rename is. Changing a key document later is a recorded migration under a `natural_key_version` — **not "one
column rewrite," which the review correctly called false.** No `id` moves, because nothing points
at the key; but every **edge** key derived from that node's key must be recomputed, which can merge
formerly distinct edge keys and must fail loudly rather than pick a winner, and any key-based
resolution pointer has to be repaired. Whether history preserves the old key and version, and how
correlation crosses versions, is part of that migration's design. (Verify before relying on it: whether GitHub keeps a workflow's numeric id when
its YAML file is renamed; if not, a workflow rename is honestly a new node.)

**Edges — RULED 2026-09-15: assigned ids, optional natural keys, declared discriminators.** An
edge's `id` is a pure uuid7 like a node's; an edge *may* declare a natural key — its key document is
`{type, source_key, target_key, …discriminators}`, canonicalized and hashed the same way.

**The edge type is a member of the document (George, 2026-09-15), and it is what prevents the
obvious collision:** without it, `USES_ACTION{declared_ref: "v1"}` and any other edge type that
happens to discriminate on a `v1`-valued property between the same two nodes would hash to the same
key. The type is in the document for the same reason it is on nodes — it is an input a reader can
see, rather than a namespace chosen out of band. Note the asymmetry this creates with the spine:
every edge spine row carries `entity_type = "edge"`, with the semantic type on `tap_edge`, so the
*key document* is the only place the edge's real type participates in its identity. That is one more
reason it cannot be left implicit.

**Declare the unit of meaning before the discriminators.** The coexistence test does not finish an
identity definition. Two steps can both use `checkout@v4`, and `{source, target, declared_ref}`
deliberately collapses them — correct if the edge means *"this job uses this action at this ref,"*
wrong if it means *"this step invokes this action."* Decide which relationship the type asserts,
then choose discriminators that distinguish every occurrence that assertion intends to keep apart.
`USES_ACTION` today means the former and carries `step_indexes` as an attribute, which is coherent.

**The binding invariant.** An edge key built from *endpoint natural keys* describes a relationship
between correlated things; it does **not** say which endpoint *life* or which perspective the edge
belongs to. Local edges bind to endpoint **entity ids**. Lookup must never return an edge attached
to the wrong endpoint life merely because the endpoint keys match.

Then the discriminator test: **a property is in the key only if two edges that differ in it can be
true at the same time.** `USES_ACTION` already does this
(`declared_ref` is in its id, because a job can use `checkout@v3` in step 1 and `@v4` in step 4 at
once); `OWNS_REPO`'s `permission` is not, because `admin` and `write` cannot coexist on one pair — it
is state with field history. A discriminator changing is a fact ending and another beginning
(end + mint, per github-core#119), not a rename, so aliases never enter; a key-*definition* change is
the same column-rewrite migration as for nodes. A natural key does not make an edge unique, any
more than it does a node: the key is a correlation handle and carries no constraint (see Identity). **An edge type may declare no natural key** — then identical edges with
identical properties between the same two nodes are possible, a corner case someone will hit
eventually; the spine permits it and application logic decides what it means. Property graphs are
multigraphs; RDF is not; we are the former with an opt-in constraint.

**Aliases and redirects — deferred, shape agreed.** When a former key must stay findable — an
operator asserting that two nodes are one thing, a key-document migration a peer deployment has not
made — it is one JSON column on the spine, `{former_key: reason}`, with `reason` a closed vocabulary
(`renamed · key_definition_changed · merged · asserted`), plus the `BaseModel` hook that fills it.
OpenCTI's `stix_ids` and Wikidata's redirects are the precedents. Not built until someone needs it.

**Perspectives — the thing this was missing.** A network scanner sees `host:443` closed; an onboard
agent sees it open. With one natural key and different dimensions they are two live rows the grid
*knows are the same object*, each carrying its own observation — which is the prerequisite for
reasoning about disagreement, not the disagreement itself.

**Different vantages are not automatically contradictions — RULED 2026-09-15.** That example is in
fact the wrong one: an onboard agent observing a listening socket and an external scan failing to
connect are both accurate, because they measure *different propositions* — "a process is bound" and
"it is reachable from here." Nmap says as much in its own documentation: port states describe how
the port was observed, not an intrinsic property. Calling that pair a contradiction would
manufacture findings out of correct data.

So `CONTRADICTED` is derived only after a **comparison contract** is satisfied: same subject
identity, same observed property, comparable conditions, and overlapping validity intervals. W3C
SOSA/SSN supplies the vocabulary this needs and TAP should borrow its distinctions without adopting
RDF — *feature of interest* (the thing), *observed property* (what was measured), *sensor* and
*procedure* (who measured it and how), *result*, and crucially two times: **phenomenon time** (when
the world was that way) and **result time** (when the observation was made). Two rows disagree only
when feature and property match and the phenomenon times overlap; differing sensor or procedure is
the ordinary case and is preserved, never reconciled. Both observations are kept regardless: the
Belnap *Both* value applies to one proposition with positive and negative evidence, not to two
propositions that happen to share a subject. Presenting the object as seen by A and by B
is a view; reconciling them into one answer is a policy, never the storage layer's job. The set that makes the grid cohere, in George's framing (2026-09-15): **who — FLIP; what —
natural key; when — history; where — dimensions and originating grid.** One refinement on *when*,
from the review: history records when **TAP changed its record**, which is not the same as when the
fact was **true at the source** — a delayed collection or a late webhook describes an earlier source
state. That is bitemporality, `spec-grid-history.md` already recognises the distinction, and the
observation interval on each surface plus SOSA's phenomenon-versus-result time are where the source
side of it lives. Claiming that a historical query reconstructs what was true in the source requires
both clocks, not one. Once those four are on the
spine, the reader can supply the *why* themselves — which is the job a security graph exists to
leave to the human. Aliases, eventually, keep *what* stable across a rename.

**Lives (George, 2026-09-15).** Once *what* is a stored key, "the lives of X" is one query — every
row sharing X's natural key — partitioned along three axes, each a different column on the spine:
**past lives** (rows tombstoned over time — history; what resurrection would have been, as a query
instead of a mechanism), **multiple lives** (the same thing observed by different deployments —
`originating_grid_id`), and **alternate lives** (the same thing seen from different perspectives on
one grid — dimensions; where two observers disagree, the *Both* value). One key, three axes, no
merging: the grid never has to decide which life is real, only show which is being asked about.

**Impact of the switch in github_core (measured 2026-09-15 on main):** 52 mint call sites across 34
identity functions in `collector.py` become lookup-or-mint; 16 test files assert against derived
ids; zero of 27 models declare a unique constraint today, so the natural-key indexes are the real
work. Existing rows keep their ids (a uuid5 value is a valid uuid), lookup
finds them by key, only nodes first seen after the change get uuid7. One external dependent,
zizmor, moves from minting to `resolve`. One flag for reliability 1b: its byte-identical-replay
acceptance criterion must compare batches modulo ids for first-seen entities — preserving endpoint
bindings, multiplicity and lifetimes, never by stripping ids. **This is not "no migration" and not
"GRIFT unchanged"** — see *What this actually costs* for the real list; the summary here is only
about what does **not** change, which is existing ids. GRIFT's `entity_id` reference syntax is
unchanged —
nodes are still identified by `entity_id`; the collector resolves before it emits.

**Consequence settled by the record (Kubernetes):** a new life does not inherit the old life's
edges. Dependents of a recreated owner are re-derived by the run that sees the new owner, never
re-attached across the tombstone.

## Cascade across permission boundaries — RULED 2026-09-15

Two states, not a taxonomy.

- **Default: a cascade that hits a permission issue is cancelled.** The reconciler gathers the
  contained closure first, checks the actor's authority over every entity type in it, and on any
  refusal writes **nothing** — the parent stays live too — recording the refusal with the blocking
  types named. Fail-safe: the transaction rolls back rather than producing a partial subtree.
  Collect, check, then write or don't (Django admin's `get_deleted_objects` shape).
- **`cascade_force` is a capability that overrides the permission system.** Granted deliberately,
  assignable to a collector actor, it lets the caller cascade through refusals. Direct precedent:
  Active Directory's `ADS_RIGHT_DS_DELETE_TREE` — "you can delete the object and any child objects
  **regardless of the protections on the child objects**" — a separate grantable right, not a
  per-case rule set. The permissive alternative (PostgreSQL's referential actions bypassing row
  security, Salesforce's cascade bypassing sharing) makes the declaration confer the authority; we
  make a capability confer it.

Because a forced cascade is an override of the authorization system, **its use is recorded**: the
`BatchEvent.metadata` for every node and edge in a forced subtree carries `forced: true` beside the
reason, so "this subtree was retired by force, by this actor, under this run" is queryable rather
than inferable. AI actors hold neither capability in v0 (read-only, per `spec-ai-integration.md`).

**Backlogged:** scoped cascades — restricting a given actor's cascade authority to certain entity
types or dimensions, rather than the present all-or-force. Not needed for the first slice.

## Known unknowns: shadow nodes — RULED 2026-09-15 · DEFERRED, not a first-slice prerequisite

The natural key is what separates two shapes the elephants briefing could only describe: an
*absence-of-evidence* record ("there may be something here and I cannot tell") and a **known
unknown** ("there is definitely a thing with this key; here is what I could read, and what I could
not"). With perspectives on the spine, the second becomes a node.

- **Keyed shadow — a real node of the real type, with nulls and a reason.** The weak perspective
  can see a handle but not the content: a ruleset's bypass actors come back as `actor_id` +
  `actor_type` to anyone who can read the ruleset, and resolving the id to a name needs another
  grant; a repository's `security_and_analysis` block is admin-only; a member's second factor is
  owner-only. Mint the node under that perspective, fill what was seen, null what was refused with
  a typed reason. When a stronger perspective runs, it mints the same key with the fields filled —
  two lives, one key, and "naming the shadow" is literal.
- **Counted shadow — a generic `shadow` node of the container.** The weak perspective sees only
  that N exist (`total_private_repos: 10`; a `bypassActors { totalCount }` with no nodes). No
  per-item key, so no per-item node; instead one core-typed `shadow` keyed on `(container, of_type)`
  carrying an `of` object — `{type, count, known: {…}, unknown: […], reason, would_resolve}` — the
  elephants briefing's negative node, verbatim, with an address. It sits on the board under its
  parent by the ordinary containment edge. When a stronger perspective enumerates the ten, the real
  nodes appear on *their* dimension; the counted shadow on the weak perspective **stays**, because
  it is still true from where that credential stands, and "shadow count equals named count" is the
  positive control — a mismatch is a *consistency check*, not proof the populations match (the count
  was taken at one moment and the enumeration at another). Resolution is by **replacement on a
  stronger dimension, never mutation** of the shadow (BloodHound's `Base` node — not ServiceNow's
  reclassify-in-place), so the record of what a limited credential saw is never erased.

**Skolemization: what it does and does not license — RULED 2026-09-15.** Skolemization is the right
precedent, for exactly one of the two steps, and the first draft cited it for both. In RDF 1.1 §3.5
it is the act of replacing a blank node — "something exists here and I cannot name it" — with a
fresh, stable identifier, preserving the existential claim so it can be referenced and merged.

- **Minting a shadow *is* skolemization.** We hold an existential claim ("ten repositories exist
  under this account that this credential cannot list") and we give it a stable name: a node with
  its own natural key, derived from the container and the `of_type`. That is precisely the
  operation, and it is why the shadow can carry edges and be queried at all.
- **Resolving a shadow to a named thing is *not* skolemization.** A Skolem identifier is a fresh
  name for an anonymous resource; it does not discover *which* real-world resource the blank node
  denoted. Deciding that this later-enumerated repository is one of the ten is **entity
  resolution**, and it needs its own evidence — matching scope, overlapping observation intervals,
  and a cardinality that adds up. Skolemization licenses the naming; it licenses nothing about the
  identification.

The practical consequences, both of which the first draft got wrong: a **cardinality claim cannot
carry a singular `resolved_to: <natural key>`** — ten unknown members do not resolve to one
discovered repository — so an aggregate's relationship to its discovered members is a separate
assessment referencing both pieces of evidence, not a forward pointer. And a **stronger perspective
must not write the weaker one's resolution**, because that makes the weak observer appear to have
asserted knowledge it never had; the assessment is its own statement, attributed to whoever made it.
Singular `resolved_to` remains correct only for a **keyed** shadow, where a real key was observed
all along and no skolemization was involved.

**Why a generic type, not a mostly-null instance of the real type:** `MATCH (r:github_repository)`
must not count ten shadows as repositories. `of.type` is what lets a query say "shadows of
repositories under this org" without the shadow being one.

**Two consequences for existing machinery.** The falsifier's fan-out skips shadows — they are a
perspective's statement, never tombstone candidates; a shadow is retired only when the perspective
that made it re-runs and no longer sees the count.

And the **endpoint question is answered by a dedicated edge type, not a validator exception**
(revised 2026-09-15). The first draft proposed letting `OWNS_REPO` accept a
`shadow{of.type: github_repository}` whenever the inner type satisfied the constraint. That passes
a type check without making the target a repository with repository fields, so every existing
traversal over `OWNS_REPO` would silently become a union it was not written for — a semantic change
dressed as a permissive branch. Instead a counted shadow hangs off its container by its **own** edge
type, whose declared target *is* `shadow`. No type-unsafety, no union for every query contract to
absorb, and **no change to tap#397** — the note left on that issue is withdrawn.

**Resolution, ruled (George, 2026-09-15): replacement, never mutation — because changing
`entity_type` on the spine is forbidden.** When the thing a shadow stood for becomes known, the
real node is minted under its own natural key. **For a keyed shadow only** — where a real key was
observed all along — the shadow's `of` object gains `resolved_to: <that natural key>` and its edges
are re-pointed
to the real node. Two cases share that mechanism: the *same* perspective gains sight (a credential
upgraded) → write `resolved_to`, re-point, tombstone the shadow with reason `resolved`; a
**different** perspective sees the thing → **write nothing on the shadow.** A stronger observer must
not author the weaker one's resolution, because that makes the weak observer appear to have asserted
knowledge it never had; the correspondence is a separate assessment, attributed to whoever made it,
referencing both pieces of evidence. And a **counted** shadow never takes a singular `resolved_to`
at all — a cardinality claim does not resolve to one member. Either way the real node's lives query finds
its **past shadowy life** by the forward link — the aliases mechanism, arriving early and pointing
the other way. One mechanical note: edge ids are `uuid5(type, source, target)` today, so
"re-point" is end-the-old-edge + mint-the-new-edge in one transaction with the same reason, not an
in-place update; nothing has needed to re-point an edge before, and this is the first customer.

Prior art: RDF blank nodes and skolemization; BloodHound's `Base` node ("used when a node type is
unknown … retained as it may have edges linked to/from it"); Terraform's `(known after apply)`;
git's promisor objects; ServiceNow's Unclassed Hardware (the in-place alternative, not chosen).

## Cascade — RULED 2026-09-15

A repository going dark with its workflows, runs and secrets left standing as live nodes is not a
tombstone. When a node is dropped from observation, the cascade **follows containment edges down
and tombstones everything it reaches; reference edges are ended and their targets left alone.**

1. **Containment versus reference.** The spine already tombstones every edge at either endpoint of
   a tombstoned node, so reference edges — a ruleset protecting this repo and nineteen others, an
   App enabled on it, an action its workflows use, a commit a fork also observes, zizmor's finding
   pointing at a workflow — die for free and their far nodes stay. The only new machinery is
   following containment edges to child nodes. **Cascade never retires anything it reaches by a
   reference edge.** A shared node that loses an edge stays live and unreferenced; whether
   unreferenced shared nodes are ever swept is reference counting — the garbage-collector class of
   problem — and is deliberately its own design, not part of cascade (see the open list).
2. **Executed children are tombstoned too.** "Executed facts are never tombstoned on absence"
   protects the *falsifier* from reading a retention window as a deletion; cascade is not inference
   from absence but a consequence of the container going dark. If the repository cannot be
   observed, neither can its runs; leaving them live claims otherwise. The whole subtree drops,
   declared and executed alike — nodes and edges — with provenance *consequence of <parent> dropped
   from observation under scope S* and the parent's completeness as evidence. Kubernetes
   garbage-collects dependents of a deleted owner the same way.
3. **The containment edges are the descent table.** The same manifest rows — (parent type,
   containment edge, child type, tier) — that collection walks down and the falsifier fans out along
   are what cascade follows. One declaration, three uses. For github_core: `OWNS_REPO`,
   `HOSTS_REPOSITORY`, `DEFINES_WORKFLOW`, `DEFINES_JOB`, `DECLARES_ENVIRONMENT`, `DEFINES_SECRET`,
   `EXECUTES_WORKFLOW`, `RUNS_JOB`, `UPLOADS_ARTIFACT`, `STORES_CACHE`, `PUBLISHES_RELEASE`,
   `OPENS_PULL_REQUEST` and the ref edge are containment; `PROTECTS_REPOSITORY`,
   `ENABLED_ON_REPOSITORY`, `USES_ACTION`, `OBSERVES_COMMIT` are references. **Undeclared is not
   followed** — the fail-closed default ruled because of tap#397, on cascade's own evaluator, never
   sharing the edge-permission union's permissive branch. Lifting these rows onto the model
   definitions (a `containment` bit on `OUTBOUND_EDGES`) is the later refactor, with the meta-graph.
4. **One subtree, one transaction, one reason.** Top-down from the parent, atomic, idempotent
   (already-tombstoned children skipped), every node and edge in the batch carrying the same run,
   scope and reason in `BatchEvent.metadata`. The child tier's falsifier does not run for a parent
   that is gone.
5. **Descent rows, not queries.** The table is `(parent type, containment edge type, child type,
   tier)` — three facts, no logic — so it cannot drift from the edges' declared endpoints and so
   cascade never rides the search engine (Gryphon runs under the read-only search role, which
   cannot see a new table until the next boot, tap#431; its semantics are still moving). The
   reconciler walks edges through the service layer's own read path. Rendering each row as a
   generated Gryphon query — "show me what would cascade" — is a view, backlogged as an idea
   (tap issue under tap#140). Not Django FK cascade: there are no foreign keys between typed nodes
   (relationships are edges on the spine) and tombstoning never calls `.delete()`, so `on_delete`
   would never fire; `delete_node()` already tombstones every edge at either endpoint.
6. **A service-layer verb, not collector code.** `delete_node()` gains `cascade="contained"`
   (reading the declared containment edges) beside the reason parameter. An operator's imperative
   GRIFT delete of a repository and the falsifier's verdict take the identical path and produce the
   identical subtree. A new life inherits none of it; the next run re-derives the children under
   the new node.

## Falsifier — RULED in shape 2026-09-14; mechanics PROPOSED 2026-09-15

Per-type **falsifiability**, standardized the way collection is: a manifest-declared easy path and
a per-type fix-up. Three parties, three jobs:

- **The model declares the contract** — whether this type is reconcilable at all and which
  evidence strengths it can reach (a workflow has a positive record: the commit that removed the
  file; a repository has a direct probe; some types only ever have the listing).
- **The plugin supplies the probe** — a registered capability, `[falsifiers]` in `tap-plugin.toml`
  beside `[models]` and `[edges]`: entity type → the callable implementing
  `batch_falsify(candidates, context) → verdicts`. Batch is the interface (one aliased GraphQL
  query for fifty repositories rather than fifty REST calls); the default implementation loops a
  singular probe. A type with no row is **not reconcilable**: its nodes are marked
  not-re-observed and never retired, and `validate_plugin --strict` lists it — the same ratchet
  shape as the domain-article coverage guard.
- **The service layer applies the verdict.** One verb, `reconcile(run, scope_node)`, called as the
  run's final phase. It reads the descent table and the scope node's `tiers`, computes candidates
  per tier outer-in (fan-out from the parent minus observed minus outside the selection), invokes
  the registered falsifier with the run's credential context, and applies each verdict through
  `delete_node(reason, metadata, cascade="contained")`. **The collector never calls
  `delete_node`.** The falsifier's prerequisite is read **per parent, not per tier** — see below.

**The prerequisite is per parent — RULED 2026-09-15, resolving the second contradiction.** The first
draft said both that completeness is *"per surface, not per run"* (so repo A's workflows may be
falsified when A's workflow listing completed even though the org listing failed) and that the
falsifier runs *"only for a tier whose parent tier completed"* (so a failed org listing vetoes
every repository's workflows). Opposite outcomes, and the second is expensive: one flaky org listing
would veto falsification for all twenty-four repositories, including the twenty-three whose
workflow listings were perfect.

The resolution is to notice that a parent's completeness establishes **two different facts**, needed
for two different decisions:

1. *That the set of parents is complete* — required to decide whether a **parent** is gone.
2. *That this parent exists and is observable* — required to falsify **its children**.

Only (1) needs the sibling set. For (2), if repo A was fetched successfully this run, is in the
observed set, and its workflow listing completed, then A's existence is established by **direct
observation**, not by the listing — so its children can be falsified whatever happened to the org
listing. The prerequisite is therefore: *this parent was observed this run, and this child surface
for this parent completed.*

The tier **ordering** still holds, for a different reason: children must never be falsified after
the parent has been judged gone, because that is cascade's job on cascade's evidence. Ordering
outer-in survives; the tier-wide gate does not.

**Authority** comes from the run config (tap#142; constraint 4 of tap#140: reconcile authority is
its own capability): `reconcile: true` per install, **default off**, so additive-only remains the
behaviour until an operator turns it on. **Budget** lives beside it — a maximum number of
falsifier calls per run; exhaustion yields `UNDETERMINED(budget)` for the remainder and a warning,
never a half-finished pass that starves the next collection of rate limit.

**Verdicts are not booleans.** Four values, and none of them is a field on the observed node:

- `DROPPED_FROM_OBSERVATION` — with its evidence strength (positive record · direct probe ·
  complete listing) recorded, not thresholded.
- `PRESENT_AT_PROBE` — the candidate was absent from the listing and the probe answered. **HTTP
  success is not the verdict**: the probe compares **stable source identity and current
  owner/scope**, because a 200 on the old address covers four different facts.

  | What the probe found | Meaning | Outcome |
  | --- | --- | --- |
  | same source id, same owner, new name | **renamed** — a locator update | update the name; the key is on the stable id and does not move. Needs no alias machinery, so this case must *not* be deferred along with aliases. |
  | same source id, **different owner** | **transferred out** of the observed account | this account's ownership observation ends. Without the owner comparison a transferred repository stays attached to its old owner forever — the bug a bare 200 would cause. |
  | **different source id**, same name | a different object now at the old address | the old observation ends; the new object is a new row. |
  | same source id, same owner | genuinely present; listing and probe disagree | no retirement; record the disagreement. |

  Only the last row is `PRESENT_AT_PROBE` proper. The earlier name `CONFIRMED_PRESENT` carried the
  claim "the collector missed something — a defect", which is unsound twice over: the object may
  have been created between listing and probe, **or** access to it may have been restored in that
  window. So the record states a disjunction. A creation time at or after the interval's start rules
  timing *in*; a creation time before it rules nothing out, because restored access explains it
  equally well. And **frequency does not classify cause** — a rising rate on a surface is a reason
  to investigate it, never evidence of what went wrong.
- `UNDETERMINED` — typed reason from the closed vocabulary: probe forbidden, errored,
  rate-limited, budget, selection unknown.
- `REIDENTIFIED` — a 301: the thing exists under a new identity. An alias, handled as a migration,
  never as a tombstone plus an orphan.

**Where a verdict lives.** A verdict is the falsifier's return value, consumed by `reconcile` and
then persisted in exactly two places: the run's structured records (one entry per verdict, with the
reason, the evidence strength and the scope) and — for `DROPPED_FROM_OBSERVATION` only —
`BatchEvent.metadata` plus the history reason on the tombstone itself. `PRESENT_AT_PROBE` writes no
field anywhere: the node is simply re-observed from the probe's payload like any other observation,
and the *record* carries the disjunction. Nothing on a live node ever says "a falsifier looked at
me and let me live" — that would be a third state on the node, and the one thing worse than no
verdict is a verdict nobody can act on.

**Edges come in two families and only one is a probe.** Edges derived from content —
`USES_ACTION`, `REFERENCES_SECRET`, `CALLS_WORKFLOW` — are falsified by re-deriving from the
parent declaration (github-core#119's reassessment rule: declared facts re-derive on change,
executed facts never; an edge whose source content is gone is ended, not left standing). Observed
relationships — `ENABLED_ON_REPOSITORY` — are falsified by the listing that produced them.

**Proof.** Every falsifier ships four cases through the fake-GitHub harness reliability 1b builds —
present, dropped, forbidden, reidentified — and the fixtures org carries a known answer for a
deleted repository's whole contained subtree.

**Not yet ruled (the remaining implementation questions):** the exact `[falsifiers]` row shape;
whether `reconcile` is one verb or a verb per tier; where the budget default lives and its number;
and the repository falsifier's exact use of `collection_scope.selection` for a selected-scope App.

## Hysteresis — RULED 2026-09-15: there is none; the completeness gate is the hysteresis

A retention window (BloodHound Enterprise: delete what has not been seen for 7 days; Active
Directory's tombstone lifetime; Cassandra's grace period) is absence of evidence with a timer on it.
It does not establish that anything is gone; it establishes that the collector has not said
otherwise for a while — and both failure modes are live at once: a deleted object stays "live" for
the window, and a real object vanishes if the collector was merely broken for the window, with no
record of which is happening. It is what a system settles for when it has no completeness signal.
We built one.

Under proven completeness, one strike *is* the evidence: a repository absent from a listing that
walked to the end, passed its positive control, and reconciled to the account's reported count —
**and, where the surface cannot establish source consistency, corroborated by a direct probe that
confirms the identity is gone rather than merely unlisted** — is
dropped from observation *now*. A second identical run adds nothing a first complete one did not;
waiting adds only staleness. The only legitimate reason to withhold a verdict is that the evidence
was not complete, and that case is already handled — the falsifier does not run. So: no clock, no
strike count, no "pending" state on the node. A verdict carries its evidence strength (positive
record · direct probe · complete listing) for the record, not as a threshold.

## The narrowest slice, when the collector is reliable

Repository-level tombstoning with the full contained subtree cascading (rule 3's table), in this order once reliability 1b has merged: (1) the identity
switch in github_core — declarations, natural-key indexes, lookup-or-mint, zizmor's `resolve` —
because everything after it depends on a returning key being a new node; (2) `delete_node` reason
+ metadata parameter, core; (3) `collection_scope` carrying `selection` (github-core#145, merged);
(4) the repository falsifier reading it — fan-out from the account, minus observed, minus outside
the selection, only under a complete listing — as the first registered falsifier; (5) the fixtures
org's known answers. Then workflows (Shape A: git-provable), then the rest per shape, then
collector_core → aws.

**Explicitly NOT prerequisites for the first slice (George, 2026-09-15, agreeing with the review's
recommendation 6):** perspective *comparison* and the derivation of `CONTRADICTED`; shadow nodes,
keyed or counted, and their resolution; aliases; and federation / cross-deployment correlation.
Each is designed above and each is future work. They must not silently become gates on retiring one
repository's observation. The design sections for them are marked DEFERRED.

**No carve-out.** An `identity_scope` column and a reserved perspective dimension were both
proposed and both withdrawn (2026-09-15): the natural key must be dimension-invariant, so there is
nothing for a uniqueness constraint to partition on, and the dimension vocabulary could not carry
one correctly today in any case. The spine change is one nullable column and one non-unique
index.

## What this actually costs — corrected 2026-09-15

Three claims in the first draft were wrong, all three verified against the code during the review.
They do not invalidate the approach; they belong in the build plan.

- **"One core change" / "no data migration" — false.** The spine gains `natural_key` (nullable), and
  `Entity` has no such field today (`tap_grid/models.py`). Then: a backfill per type as each
  recipe is declared; a report — not a silent winner — where two live rows in one dimension compute
  one key; index creation; and `SPINE_FIELD_NAMES` is a **closed tuple with a drift-guard test**
  (`tap_grid/tests/test_entity_spine.py`), so it changes in the same commit or CI reds.
- **"GRIFT unchanged" — false.** `entity_id` reference *syntax* is unchanged; the interchange
  contract is not. The entity envelope is `additionalProperties: false`
  (`tap_grid/schemas/grift-document.schema.json`) and `SPINE_FIELD_NAMES` drives serialization
  (`tap_grid/grift/subgraph.py`). Transporting a peer's natural key — which the deferred federation
  case needs — is a schema change. Whether keys are **transported or re-derived at import**, and
  how recipe versions travel, is an open decision, not a no-op.
- **Atomic resolve is a write.** Two processes can both find no live row and both mint. Reliability's
  per-collector single-flight does not serialise two different collectors or another plugin, and
  with no unique constraint (see Identity) nothing at the database level breaks the tie. Resolve and
  create belong in one service-owned transaction; the residual is an application-level concern until
  within-dimension uniqueness exists. Say so rather than implying the constraint is doing work it
  is not.
- **A stale absence verdict can be applied after newer presence.** And `Entity.version` will not
  save it: by the re-observation-is-not-change ruling (tap#322) an unchanged re-observation
  deliberately may **not** bump the version, so optimistic concurrency cannot detect that a newer
  successful observation intervened. The reconcile pass needs its own **fence** — a generation
  validated at application time — plus defined stale-run rejection and crash recovery. The observed
  set must be owned by the run that produced it; topology records what the grid last believed, not
  what this run saw.
- **Containment integrity is not implied by a containment bit.** Define the behaviour for a cycle, a
  child with two containing parents, and a cross-perspective edge. One case is concrete and nasty:
  a repository transferred between accounts while the **old** account is mid-reconcile — the old
  account's cascade must not retire a subtree the new account has just observed. Gather the closure
  before ending the edges needed to discover it, and validate at application time against
  concurrent change.
- **Replay tests must not be weakened to accommodate assigned ids.** Comparing two fresh runs
  modulo a consistent bijection of generated ids is legitimate; retrying the *same* persisted batch
  must preserve its identity mapping. The comparison has to hold endpoint bindings, multiplicity,
  natural keys and lifetimes — stripping ids wholesale would hide exactly the broken-edge and
  duplicate-creation bugs this change can introduce.

## Prior-art corrections — 2026-09-15

The companion briefings (*Lingering Objects*, *Surrogate and Glue*) drew conclusions wider than
their evidence. The narrow versions, which are what this design rests on:

| Claim as written | Correction |
| --- | --- |
| STIX "mandates" v5 for observables, v4 for domain objects | These are **SHOULD** recommendations with exceptions. The Process SCO uses v4, and an IP address is not an immutable identity for the machine using it. The split is a useful convention, not an immutability theorem. |
| "Nobody ships resurrection except at great expense" | **FHIR explicitly permits a deleted resource to return.** This does not argue for adding restore to TAP; it does mean the universal claim was false. |
| "Resource ids (`i-…`, ARNs) are never reused" | Overbroad. A name-derived ARN can recur after recreation; it is the unique user/role **id** that distinguishes incarnations. Identifier reuse semantics are per resource type and must be declared per type. |
| RFC 9562 "walks away from" v5 | It does not deprecate v5, and it standardises no single SHA-256 v8 recipe. It does say a newer name-hash scheme belongs in v8 rather than masquerading as v5. Declare algorithm and namespace; a hash confers no authenticity. |
| Cassandra's grace period grouped with inventory hysteresis | Different problems. Tombstone **retention after an accepted delete** protects replicas from reviving it; inventory hysteresis is **waiting before declaring** observed absence. |
| OR-Set cited as precedent for safe reconciliation | An OR-Set also defines which additions a removal has observed and how concurrent operations merge. uuid7 plus tombstones confers none of those causal guarantees. Analogy, not proof. |
| RFC 8785 as the canonicalization answer | JCS fixes serialization; it decides no semantics. See the normalization requirements in Identity. |
| ServiceNow / Salesforce behavioural anecdotes | Not load-bearing for anything here; treated as illustration, not evidence. |

The durable document should carry primary links beside each claim; the HTML briefings mostly name
sources without them.

## Acceptance cases — adopted 2026-09-15

The review's fifteen cases become the implementation spec's test list verbatim, and the first slice
must pass the subset that does not depend on deferred work: repository invisible then visible again
with the same historical run ids; two writers concurrently resolving the same absent key; an older
absence verdict arriving after newer unchanged presence; pagination completing while membership
changes; an object appearing between listing and probe; selection shrinking; parent listing failing
while a child surface completes; a repository transfer observed while the old account reconciles;
two identical action invocations; an endpoint key recipe changing; a cascade graph containing a
cycle or a shared child; and crash/retry around the GRIFT commit. The perspective, shadow, alias and
federation cases are deferred with their designs.

## Build notes — skills to update when this lands

The authoring skills are where a new type's identity decision gets made on purpose instead of by
default, so each of these grows a step the day the corresponding piece ships (George, 2026-09-15):

- **`add-model`** — the identity declaration: the key document's constituting properties (stable server ids first; a name only when the source offers
  nothing better), and the `natural_key` recipe (PURL / ARN / canonical JSON under the type's
  namespace). Whether the type is reconcilable and which evidence strengths its falsifier can reach.
  Whether its nodes may be *keyed shadows* (which fields may be null-with-reason under a weak
  perspective).
- **`add-edge`** — assigned id; whether the edge declares a natural key at all; the discriminator
  test ("can two edges differing in this property coexist between the same pair?"); the
  **containment bit** — is this a containment edge the descent table, the fan-out and the cascade
  follow, or a reference edge (fail-closed: unset means reference); and whether a `shadow` is an
  whether a counted shadow of this child type needs its own edge type (a `shadow` is never an
  admissible endpoint of an ordinary edge by its inner type — that proposal was withdrawn).
- **`build-collector`** — the descent-table rows the collector's surfaces add; the `[falsifiers]`
  row per reconcilable type; emitting keyed shadows (fill what was seen, null what was refused,
  typed reason) and counted shadows (one `shadow` per container × of_type with its `of` object);
  lookup-or-mint through `resolve()` instead of minting ids; the run-config `reconcile` and budget
  knobs the collector honours.
- **`new-plugin`** — the `[falsifiers]` table beside `[models]` and `[edges]` in `tap-plugin.toml`,
  and the validator's new ratchets (every model declares identity; every assigned model has its
  index; every reconcilable type has a falsifier row). No partial unique index — the natural key
  carries no uniqueness constraint in the first slice.
- **`build-domain-vocabulary`** — the domain article's *Identity* and *Falsifiability* sections
  (what constitutes this thing; how its absence is proven; what a shadow of it looks like).

Presence-is-not-correctness applies to the skills too: a skill that describes the declaration
without the validator refusing its absence is a checklist, not a gate.

## Still open outside this doc

The `refs` page cap (100 per repository; branch tombstoning unavailable for large repositories
until paged — documented gap versus lift in 1b); which spec owns the tier requirement (the
reliability spec, our lean); the meta-graph derivation of the descent table; **sweeping unreferenced shared nodes** (actions, Apps, rulesets, commits that lose their last
edge — reference counting, the garbage-collector class; cascade deliberately leaves them live);
Kubernetes' *background* propagation (tombstone the parent now, sweep dependents asynchronously
under the same reason) as the escape hatch if a cascade ever spans an org rather than a repo; and one
question the prior-art search raised that has no owner yet — **tombstone lifetime for consumers**: every
replicated system keeps a tombstone long enough for every reader to see it, and every one has a
zombie story about getting that wrong. Irrelevant with one instance; load-bearing the day a second
instance, an export, or a federation reads the grid.
