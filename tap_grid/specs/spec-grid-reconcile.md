# Grid Reconciliation Specification

## Philosophy

A collector is additive-only until something tells it otherwise. Every run upserts what it found and nothing compares "what I found" against "what is on the grid", so a deleted repository, a removed workflow or a decommissioned runner stays on the spine indefinitely, looking exactly as live as a real one. Left alone, every collection makes the grid a *less* trustworthy answer to "what does this account have" — which is fatal for a product whose value is that its picture is true.

The naive fix is worse than the disease. "Not found" also means a failed call, a narrowed credential, a truncated page, a rate limit, a plan boundary or a source that changed while we were reading it. Absence of evidence must never render as evidence of absence, so this specification is almost entirely about the discipline that lets a run *earn* the right to retire something — and about recording, in a form another process can read, exactly how far that right extends.

Three things are deliberately kept apart throughout: **the source object** (the thing in the observed system), **our record of it** (a row on the spine), and **our observation of it** (what one run, holding one credential, was able to see). They have different lifetimes. Losing permission ends an observation without ending the source object. An immutable event can become unobservable and later observable again without becoming a different event.

Design record: [`docs/misc/doc-grid-reconcile-design.md`](../../docs/misc/doc-grid-reconcile-design.md). The independent review that shaped it is tracked as `tap#458` (re-anchored 2026-09-15, since the design document moved 21 commits under the review's line citations); the review transcript itself is deliberately not carried in `docs/` — a review is not canon, and a spec should cite the ruling rather than the argument. Core epic: `tap#140`. First plugin consumer: `github-core#14`.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Truthful | The grid stops asserting the existence of things it can no longer observe. |
| 2. | Evidenced | Nothing is retired without evidence that also names its own limits. |
| 3. | Attributable | Every retirement records who decided, when, under what scope, and why. |
| 4. | Durable | History survives retirement; a thing that returns is a new observation lifetime rather than a contradiction. |
| 5. | Reusable | The contract is collector-agnostic — `github_core` is the first customer, `aws_core` the second. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-reconcile-terminology | [Reconciliation Vocabulary](#reconciliation-vocabulary) | In Force | Source object vs observation lifetime vs entity id vs natural key vs scope; a permission gap is not a rebirth |
| req-grid-reconcile-observation-lifetime | [Retirement Ends An Observation, Not A Thing](#retirement-ends-an-observation-not-a-thing) | Proposed | `DROPPED_FROM_OBSERVATION` under a named scope; terminal; never rendered as "deleted" |
| req-grid-reconcile-evidence | [Evidence Is Six Attributes, Not One Word](#evidence-is-six-attributes-not-one-word) | Proposed | Scope, enumeration, source consistency, interval, admission, application — recorded per surface as a completeness statement |
| req-grid-reconcile-candidates | [Candidate Derivation And Prerequisites](#candidate-derivation-and-prerequisites) | Proposed | Fan-out from the parent; prerequisite read per parent; withdrawal is not absence |
| req-grid-reconcile-falsifier | [Per-Type Falsifiers And Their Verdicts](#per-type-falsifiers-and-their-verdicts) | Proposed | Manifest-registered probe; five verdicts; probe compares identity and owner, not HTTP status; no falsifier means not reconcilable |
| req-grid-reconcile-verb | [Service-Owned Reconciliation](#service-owned-reconciliation) | Proposed | One `reconcile` verb, run-config authority default off, budget, fence against stale verdicts |
| req-grid-reconcile-hysteresis | [No Time-Based Hysteresis](#no-time-based-hysteresis) | Proposed | The completeness gate is the hysteresis; corroboration is a second *independent* observation, not a clock |
| req-grid-reconcile-breaker | [Bulk-Absence Circuit Breaker](#bulk-absence-circuit-breaker) | Proposed | A run that would retire an implausible share of what it observed stops before writing, defers rather than discards, and quarantines for an operator |
| req-grid-reconcile-absence-states | [Absence Has Three States On Every Surface](#absence-has-three-states-on-every-surface) | Proposed | Retired, not-seen-this-run and not-observable are distinct wherever absence is rendered; a credential that could not look never reads as gone |

---

### Reconciliation Vocabulary
----
RID: `req-grid-reconcile-terminology`

Status: `In Force`

Reconciliation work must distinguish seven terms that the first design draft sometimes collapsed into the word "life". They have different lifetimes, and conflating any two of them produces either a lost record or a false claim.

| Term | Means | Its lifetime ends when |
| --- | --- | --- |
| source object | the thing in the observed system | the source deletes it — which this instance may never observe |
| source incarnation | a particular existence of it under a reused name | the source issues a new identifier for a new thing under an old name |
| observation lifetime | *our* record of observing it, first sight to retirement | we drop it from observation |
| entity id | the row and the observation lifetime — an assigned UUIDv7 | never; ids are not reused and a tombstone is terminal |
| natural key | derived correlation handle for the source object, invariant across dimensions | only when its key *document* is redefined (a recorded migration) |
| perspective | which observer, from where — carried in dimensions | future work |
| scope | what one run's credential was permitted to weigh in on | per run |

#### Status Details
Standing doctrine, in force from the moment reconciliation work begins. It is conformed to by specs, requirements, code comments and findings copy rather than implemented.

#### Implementation
The load-bearing consequence, stated once: **a returning row is a new observation lifetime, not a new source incarnation**, unless source evidence actually establishes the latter. A permission gap is not a rebirth of the repository. Copy that a reader sees — a page, a finding, an API response, a run record — says *unobserved*, never *deleted*, unless the source itself furnished evidence of deletion.

#### Development
The review's sharpest single finding was that "the thing", "our record of the thing" and "our current observation of the thing" were used interchangeably in the design's first draft, which is what produced the terminal-tombstone dead end that `req-grid-entity-natural-key` now resolves.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-terminology-1 | Unobserved, not deleted | Proposed | No user-facing surface renders a retired observation as "deleted" unless the retirement's evidence strength is a positive deletion record. | Copy review, not a unit test. |
| req-grid-reconcile-terminology-2 | Returning rows are new lifetimes | Proposed | A source object that becomes observable again after retirement produces a new entity id with the same natural key; no code path patches or re-mints a tombstoned id. | Exercised by the returning-repository acceptance case. |

#### Future
When perspectives are built, this table gains the distinction between an observer and a vantage, and the dimension vocabulary is expected to need a cleanup pass first (see `req-grid-reconcile-candidates`' Future).

---

### Retirement Ends An Observation, Not A Thing
----
RID: `req-grid-reconcile-observation-lifetime`

Status: `Proposed`

Retiring a node records **`DROPPED_FROM_OBSERVATION`, under a named scope**. Deleted at the source, made private and lost to a narrowed credential are, from this instance's vantage, the same fact: we can no longer observe it. The grid says exactly that and no more.

**A transfer is not in that list — RULED 2026-09-15.** An earlier draft grouped "transferred to another owner" with the three above, which contradicted both the `RELOCATED` verdict and the natural-key requirement's stable-id rule, and would have licensed tombstoning and cascading a subtree that had just been observed under its new owner. The design's own mechanics settle it: `RELOCATED` fires **only when the probe succeeded and returned a different owner**, which means the object is still observable — so it ends *this* owner's relationship and retires nothing (`req-grid-reconcile-falsifier-7`), while the row itself survives transfer as one row with a history of names (`req-grid-entity-natural-key`). A transfer that moves the object beyond this credential's reach does not reach `RELOCATED` at all: it presents as a probe that answers not-found, forbidden or errored, and is handled like any other loss of observation, under the evidence rules that govern those.

#### Status Details
Proposed. The spine primitive already exists — `Entity.deleted_at` with `.live()` / `.tombstoned()` managers per `req-grid-entity-tombstone-managers`, and service-layer tombstoning per `req-grid-service-delete-tombstone`. What is new is the reason, the scope reference and the prohibition on the word "deleted".

#### Implementation
A retirement is a tombstone through the service layer, carrying:

- **the reason**, from a closed vocabulary: `dropped_from_observation` · `scope_withdrawn` · `cascaded` · `resolved`;
- **the evidence strength** that licensed it: `positive_record` (the source recorded the deletion — a commit that removed a file, a deletion event) · `direct_probe` (an independent read of that identity answered not-found) · `complete_listing` (absent from an enumeration whose evidence attributes permit the inference);
- **a reference to the scope statement** the decision was made under, so a later reversal is attributable to *the world changed* versus *our credential changed*;
- **the run** that decided it.

Those land per `req-grid-service-delete-reason`. A tombstone is **terminal**: there is no restore verb, and a source object that becomes observable again is a new observation lifetime under the same natural key (`req-grid-entity-natural-key`).

#### Development
Ruled 2026-09-15 after the alternative — a resurrection verb with per-type rules for when identity continues — was designed and rejected. Every shipped system that tried to make one name mean one thing across a deletion either built a recycle bin at great cost or grew zombie rows; the systems that made a returning name a new thing with a new id stopped having the problem. The corrected prior-art reading is in the design document's *Prior-art corrections* section: notably, FHIR does permit a deleted resource to return, so the claim that nobody ships resurrection is false — the argument for terminality here is cost and clarity, not universality.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-observation-lifetime-1 | Reason is mandatory | Proposed | A retirement written by the reconciliation pass and lacking a reason from the closed vocabulary is refused by the service layer. | |
| req-grid-reconcile-observation-lifetime-2 | Scope is referenced | Proposed | Every retirement's record names the scope statement it was decided under. | |
| req-grid-reconcile-observation-lifetime-3 | Terminal | Proposed | No service verb clears `deleted_at`; a write addressed to a tombstoned entity is refused, not absorbed. | Existing conflict behaviour, asserted here so it is not weakened. |

#### Future
Aliases — a `{former_key: reason}` record that keeps a former natural key findable after a key-document migration or an operator assertion — are designed and deferred. Sweeping shared nodes that lose their last inbound edge is reference counting and is deliberately *not* part of retirement (see `req-grid-reconcile-candidates`).

---

### Evidence Is Six Attributes, Not One Word
----
RID: `req-grid-reconcile-evidence`

Status: `Proposed`

"Complete" was carrying six distinct claims, and finishing pagination establishes only the first two. Each observed surface records them separately, and together they form a **completeness statement** about a particular relation, filter, subject and interval — not a statement that a run succeeded.

#### Status Details
Proposed. Partially anticipated in the plugin layer: `github_core`'s reliability work records a per-surface `complete` flag and an `INCOMPLETE_SURFACES` structure. This requirement is the core-side contract those satisfy, and it splits the single flag.

#### Implementation

| Attribute | The claim | Established by |
| --- | --- | --- |
| `scope_authorized` | this credential was permitted to ask | the run's scope statement × the source's declared permission for that surface |
| `enumeration_complete` | the walk reached the end of the chain and was not capped | the client's own verdict, plus a positive control on any filter (a deliberately bogus filter value must change the result, or the filter is being ignored and an empty answer is worthless) |
| `source_consistent` | the rows came from one coherent source snapshot | **only** where the source promises it; otherwise `unknown` |
| `observation_interval` | between which two instants the surface was read | first and last request timestamps |
| `admitted` | the gather passed its completeness gate and reached processing | the admission step |
| `applied` | the observations derived from it were shaped and **committed** | the write batch's result |

`admitted` stops short of persistence and therefore cannot license a retirement on its own: a shaping failure, a rejected batch or an unresolved endpoint leaves a surface that passed the gate and landed nothing. A surface whose observations did not commit is **not reconcilable**. Either observations and removals commit together, or a retirement requires `applied` together with the freshness fence of `req-grid-reconcile-verb`. An unchanged successful observation counts as applied — a no-op upsert is still an observation, and it may legitimately not bump `Entity.version`, which is why the fence rather than the version protects the decision.

`source_consistent` is `unknown` for most sources and must not be inferred from the other four. Finishing pagination proves the client followed the protocol; a count check against a parent's reported total checks cardinality. Neither proves that every row belongs to one snapshot — equal-sized sets can hold different members, and rows can move across a cursor boundary mid-walk. A count check is therefore retained as a **rejection** control (a mismatch refuses the verdict) and is never treated as proof of consistency.

Where `source_consistent` is `unknown`, the entity type's absence policy must name what substitutes. For a type with a stable addressable identity the substitute is the **direct probe**: an independent second observation of that identity, which is a different kind of evidence rather than a repetition of the same kind.

#### Development
The distinction was the review's second finding and is easy to under-rate. Kubernetes promises a consistent paginated snapshot anchored by a collection `resourceVersion`; GitHub documents cursors and traversal and makes no equivalent promise. Treating "the walk finished" as "the set is coherent" would have let a mid-walk change present as a deletion. The applicable research on making incomplete data answer negative queries soundly is the completeness-statement literature (Darari et al., 2014), which is why the recorded object names relation, filter, subject and interval rather than a boolean.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-evidence-1 | Six attributes recorded per surface | Proposed | Every listing surface a run touches records all six attributes, with a reason where an attribute is negative or unknown. | |
| req-grid-reconcile-evidence-2 | Consistency is never inferred | Proposed | No code path sets `source_consistent: true` from `enumeration_complete` or from a matching count. | |
| req-grid-reconcile-evidence-3 | Count mismatch refuses | Proposed | A complete enumeration whose count disagrees with the parent's reported total asserts nothing about absence; the verdict is refused and the disagreement recorded. | |
| req-grid-reconcile-evidence-4 | Filter positive control | Proposed | A surface depending on a source-side filter records the result of a bogus-value control; a control that fails marks the surface's enumeration not-complete. | |
| req-grid-reconcile-evidence-5 | Completeness statement shape | Proposed | The recorded statement names the relation, the filter, the subject and the interval, not merely a boolean. | |
| req-grid-reconcile-evidence-6 | Applied is distinct from admitted | Proposed | A surface whose observations were admitted but whose write batch failed is not reconcilable; no retirement is derived from it. | |
| req-grid-reconcile-evidence-7 | Unchanged observations count | Proposed | A re-observation that changes no field still marks its surface `applied`, even where `Entity.version` does not move. | Interacts with re-observation-is-not-change. |

#### Future
Bitemporality: these attributes carry the *source* side of time (when the world was that way), which `spec-grid-history.md` distinguishes from the record side (when TAP changed its record). Claiming that a historical query reconstructs source truth requires both clocks; only the record clock exists today.

---

### Candidate Derivation And Prerequisites
----
RID: `req-grid-reconcile-candidates`

Status: `Proposed`

A candidate for retirement is derived by **fan-out from the parent node**, minus what this run observed, minus anything the run's scope says it was never permitted to see. The topology is the record of what the grid last believed; no per-node observation stamp is required.

#### Status Details
Proposed. Resolves two contradictions present in the design's first draft, both recorded in the design document.

#### Implementation
For a parent P and a containment relation R declared in the collector's descent table, the candidate set is:

```
children(P, R) in the grid   −   observed(this run, P, R)   −   outside_scope(this run)
```

**The prerequisite is read per parent, not per tier.** A parent's completeness establishes two different facts, needed for two different decisions: that *the set of parents is complete* (required to judge whether a **parent** is gone) and that *this parent exists and is observable* (required to falsify **its children**). Only the first needs the sibling set. If P was observed successfully this run and P's R-surface enumeration completed, P's children may be falsified whatever happened to the enumeration that lists P's siblings — P's existence is established by direct observation, not by that listing. A tier-wide gate would let one flaky parent listing veto every sibling's children, which is both wrong and expensive.

The **ordering** rule survives for a different reason: children must never be falsified after their parent has been judged gone, because that is cascade's job on cascade's evidence. Traversal remains outer-in.

**Withdrawal is not absence.** Scope narrowing and absence-from-a-listing rest on different evidence and must not share a rule:

| Case | Evidence | Outcome |
| --- | --- | --- |
| Observed under this perspective, now outside the credential's scope | the **scope statement** — this run's compared with the previous | end the observation; reason `scope_withdrawn` |
| Never observed, outside scope | none needed | not a candidate; nothing to end |

Presenting a withdrawal as absence-from-a-complete-listing would claim evidence that was never obtained.

**Shared nodes are out of scope for retirement.** A node reached only by a *reference* relation is never a candidate. Whether a shared node that has lost its last inbound edge is ever swept is reference counting — a different problem, deliberately excluded (`tap#140`).

#### Development
The first contradiction had narrowing-out-of-scope both receiving "the same tombstone" and being subtracted from the candidate set — the same input, opposite outcomes. Each half was correct for the case that produced it: the first from the ruling that an unobservable thing is dead to us, the second from the rule that a credential must not retire what it was never allowed to see. The second contradiction had completeness described as "per surface, not per run" in one place and gated on the parent *tier* in another.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-candidates-1 | Fan-out derivation | Proposed | Candidates are derived from declared containment relations in the grid minus the run's observed set; no per-node stamp is read. | |
| req-grid-reconcile-candidates-2 | Prerequisite per parent | Proposed | A failed sibling-listing for parent Q does not prevent falsification of parent P's children when P was observed and P's child surface completed. | Directly from the review's acceptance cases. |
| req-grid-reconcile-candidates-3 | Ordering preserved | Proposed | Children are never falsified after their parent has been retired; a retired parent's children are handled by cascade. | |
| req-grid-reconcile-candidates-4 | Withdrawal distinguished | Proposed | A previously observed child excluded by a narrowed scope is retired with reason `scope_withdrawn`; a never-observed out-of-scope child is not a candidate. | |
| req-grid-reconcile-candidates-5 | References excluded | Proposed | A node reachable from the parent only by a reference relation never appears in a candidate set. | |

#### Future
Perspectives. When a grid holds observations from more than one observer, the candidate set must be scoped to the observing perspective so one observer's pass cannot retire another's rows. That work is blocked on a dimension-vocabulary cleanup: the dimension keys in use today mix perspective, facet and locator, and at least one is applied inconsistently by code path — evidence recorded in the design document.

---

### Per-Type Falsifiers And Their Verdicts
----
RID: `req-grid-reconcile-falsifier`

Status: `Proposed`

Falsifiability is declared and implemented **per entity type**, in the same shape collection already uses: a manifest-declared registration and a per-type implementation. A type with no falsifier is **not reconcilable** — its unobserved nodes are recorded as not-re-observed and never retired.

#### Status Details
Proposed. Shape agreed 2026-09-14; mechanics agreed 2026-09-15.

#### Implementation
**Registration.** A plugin declares a `[falsifiers]` table beside `[models]` and `[edges]` in its plugin manifest, mapping entity type to a dotted path:

```toml
[falsifiers]
github_core__github_repository = "tap_plugin.github_core.reconcile.repository.RepositoryFalsifier"
```

The callable implements `batch_falsify(candidates, context) -> list[Verdict]`; a base class supplies a batch-over-singular default. Batch is the interface rather than an optimisation — one aliased query for fifty candidates instead of fifty round trips. Facts about which evidence strengths a type can reach belong on the **model's** declaration, not in the manifest, so the manifest remains a pure load table. Plugin validation lists every model lacking a falsifier row, the same ratchet shape as domain-article coverage.

**Verdicts.** Five values, and none of them is a field on the observed node:

| Verdict | Meaning | Written where |
| --- | --- | --- |
| `DROPPED_FROM_OBSERVATION` | listing and probe agree it is gone from view | the tombstone, its batch-event metadata, its history reason, and one run-record entry |
| `PRESENT_AT_PROBE` | absent from the listing; the probe found the **same source identity under the same owner** | one run-record entry only; the node is re-observed from the probe payload as ordinary collection |
| `RELOCATED` | the probe found the same source identity under a **different owner or name** | a rename updates the locator and retires nothing; a transfer out of the observed scope ends *this* owner's relationship |
| `UNDETERMINED(reason)` | the probe could not answer — `forbidden` · `errored` · `rate_limited` · `budget` · `scope_unknown` | one run-record entry only |
| `REIDENTIFIED` | it exists under a new identity | one run-record entry only; nothing is retired until aliases exist |

**A successful probe does not establish continued membership.** HTTP success is not the verdict: the falsifier compares the **stable source identity** and the **current owner or containing scope** returned by the probe against the candidate's. Four outcomes, not one:

| Probe found | Meaning | Outcome |
| --- | --- | --- |
| same source id, same owner, new name | renamed — a locator update | update the name; the natural key rests on the stable identifier and does not move, so this needs no alias machinery and must not be deferred with aliases |
| same source id, different owner | transferred out of the observed scope | end *this* owner's relationship; the object itself is not retired |
| different source id at the same address | a different object now occupies the address | end the old observation; the new object is a new row |
| same source id, same owner | genuinely present; listing and probe disagree | retire nothing; record the disagreement |

Only the last is `PRESENT_AT_PROBE`. It is the one verdict whose subject is *this system* rather than the observed one, and it must not claim a collector defect: the object may have been created between the listing and the probe, **or** access to it may have been restored in that window. The record therefore states a disjunction. A source creation time at or after the surface's `observation_interval` start rules timing *in*; a creation time before it rules nothing out, because restored access explains it equally well, so the cause is `indeterminate`. **Frequency does not classify cause** — a rising rate on a surface is grounds to investigate that surface, never evidence of which branch of the disjunction occurred.

Nothing on a live node records "a falsifier examined me and let me live". Such a field would be a third node state with no defined consequence and no expiry, which is how a third state becomes a dumping ground.

**Edges.** Two families, and only one is a probe. Edges derived from declared content are falsified by **re-deriving from the parent declaration** — an edge whose source content is gone is ended, not left standing. Edges that record an observed relationship are falsified by the listing that produced them.

**Proof.** Every falsifier ships four cases against a fake source: present, dropped, forbidden, reidentified.

#### Development
Verdicts began as a boolean and were widened deliberately. A two-valued falsifier re-imports the two-state lie at the most expensive point in the system, and `PRESENT_AT_PROBE` in particular was first specified with an unsupportable claim attached ("the collector missed something — a defect"), which the review corrected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-falsifier-1 | No falsifier, no retirement | Proposed | A candidate of a type with no registered falsifier is recorded as not-re-observed and is never retired. | |
| req-grid-reconcile-falsifier-2 | Coverage is visible | Proposed | Plugin validation reports every model of a reconcilable kind that declares no falsifier. | Ratchet, not a gate, initially. |
| req-grid-reconcile-falsifier-3 | Verdicts have one home each | Proposed | `DROPPED_FROM_OBSERVATION` tombstones the **entity**. The scope-ending half of `RELOCATED` retires the **ownership edge** and leaves the entity live. `PRESENT_AT_PROBE`, `UNDETERMINED` and `REIDENTIFIED` write run records only. | Clarified 2026-09-15: "write to the entity" read as though a transfer could tombstone the row. |
| req-grid-reconcile-falsifier-4 | Present-at-probe claims no defect | Proposed | A `PRESENT_AT_PROBE` record states the disjunction and names a cause of `created_after_listing_started` or `indeterminate`; it never asserts a collector defect, and frequency is not used to classify cause. | Review acceptance case: object appears between listing and probe. |
| req-grid-reconcile-falsifier-7 | Probe compares identity and owner | Proposed | A probe returning success for a candidate under a different owner ends that owner's relationship rather than recording presence; one returning a different source identity at the same address retires the old observation. | Otherwise a transferred object stays attached to its former owner. |
| req-grid-reconcile-falsifier-8 | Rename is a locator update | Proposed | A probe returning the same source identity under a new name updates the name and retires nothing; no alias machinery is required. | |
| req-grid-reconcile-falsifier-5 | Derived edges re-derive | Proposed | An edge derived from declared content is ended by re-derivation when its source content is gone, not by a probe. | |
| req-grid-reconcile-falsifier-9 | Transfer retires nothing and cascades nothing | Proposed | A candidate whose probe returns the same source identity under a different owner retires the ownership edge only: the entity stays live, its contained children stay live, and no cascade runs — asserted on a parent with children rather than on a leaf. | Directly from the review's transfer finding; the failure it guards is a subtree tombstoned after being observed under its new owner. |
| req-grid-reconcile-falsifier-6 | Four proof cases | Proposed | Each registered falsifier has tests for present, dropped, forbidden and reidentified against a fake source. | |

#### Future
`REIDENTIFIED` currently records and does nothing. When aliases exist it becomes a migration: the new identity is adopted and the former natural key stays findable.

---

### Service-Owned Reconciliation
----
RID: `req-grid-reconcile-verb`

Status: `Proposed`

Reconciliation is **one service-layer verb**. A collector supplies evidence; it never decides, and it never calls a delete verb.

#### Status Details
Proposed. Depends on `req-grid-service-delete-reason` and `req-grid-service-delete-cascade` for the write side, and on collector run configuration for authority.

#### Implementation
`reconcile(run, scope_statement)` is called once, as a run's final phase. It walks the declared descent outer-in; for each parent it checks the per-parent prerequisite, derives candidates, invokes the registered falsifier with the run's credential context, and applies each verdict through the delete verb with reason, metadata and cascade. There is deliberately **no per-tier public entry point**: an API a caller can invoke per tier is an API a caller can invoke out of order, and ordering is a rule.

**Withdrawal takes the same path.** A retirement licensed by a narrowed scope rather than by a listing routes through the same authority check, freshness fence, cascade and audit record; only its evidence differs. And an **unknown** scope must never read as a narrowed one: a run that cannot enumerate what its credential may reach has no comparable predecessor claim and withdraws nothing. Only a declared selection compared against a previous declared selection establishes that a member left.

**Authority** comes from the collector's run configuration — reconciliation is a capability distinct from read, enabled per install and **off by default**, so additive-only remains the behaviour until an operator turns it on.

**Budget.** A maximum number of falsifier calls per run, declared beside the authority, with its default supplied by the collector's own configuration because the sensible number depends on the source's economics rather than on TAP. Exhaustion yields `UNDETERMINED(budget)` for every remaining candidate plus one warning naming how many were left. A pass never half-finishes, and never fails a run.

**Atomicity and staleness.** Resolution and creation are one service-owned transaction: two writers can otherwise both find no live row and both mint, and with a deliberately non-unique natural key (`req-grid-entity-natural-key`) the database does not break the tie. A verdict is validated at application time against a **fence** — a reconciliation generation — because `Entity.version` cannot be relied upon for this: an unchanged re-observation deliberately may not bump it, so optimistic concurrency alone would let a stale absence verdict survive a newer successful observation. The run that produced an observed set owns it; topology records what the grid last believed, not what this run saw.

#### Development
Constraint from `tap#140`: reconcile authority is its own capability. The collector/decider split is the same one that keeps collectors network-blind and replayable in the plugin reliability work — a collector that could retire rows would have to be trusted as well as correct.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-verb-1 | Collectors never retire | Proposed | No collector code path calls a delete or purge verb; a test walks collector modules and fails if one does. | Mechanical, CI. |
| req-grid-reconcile-verb-2 | Off by default | Proposed | With no reconciliation authority configured, a run retires nothing and says so. | |
| req-grid-reconcile-verb-3 | Budget bounds the pass | Proposed | With the budget exhausted, remaining candidates are `UNDETERMINED(budget)`, the run succeeds, and the shortfall is recorded. | |
| req-grid-reconcile-verb-4 | Stale verdicts rejected | Proposed | A verdict from an older generation applied after a newer successful observation is rejected, including when `Entity.version` did not change. | Review acceptance case. |
| req-grid-reconcile-verb-5 | Resolution is atomic | Proposed | Two concurrent resolutions of the same absent key yield one live identity in the intended scope, or a recorded conflict; no edge is left pointing at a losing identity. | Review acceptance case. |
| req-grid-reconcile-verb-6 | Ordering enforced | Proposed | There is no public per-tier entry point; the walk is outer-in within the verb. | |
| req-grid-reconcile-verb-7 | Unknown scope withdraws nothing | Proposed | A run whose scope enumeration is unknown produces no `scope_withdrawn` retirement. | Review acceptance case: selection shrinks. |
| req-grid-reconcile-verb-8 | Withdrawal is not privileged | Proposed | A `scope_withdrawn` retirement passes the same authority, freshness, cascade and audit path as any other. | |

#### Future
Scoped authority — restricting an actor's reconciliation to named entity types or dimensions rather than the present all-or-nothing — is backlogged.

---

### No Time-Based Hysteresis
----
RID: `req-grid-reconcile-hysteresis`

Status: `Proposed`

There is no retention window. A retirement is licensed by evidence, not by elapsed time, and the completeness gate *is* the hysteresis.

#### Status Details
Proposed. Ruled 2026-09-15, then narrowed the same day when `req-grid-reconcile-evidence` established that a completed enumeration is not a consistent snapshot.

#### Implementation
A retention window — delete what has not been seen for N days — is absence of evidence with a timer attached. It establishes nothing about the source; it establishes that the collector has not said otherwise for a while, and it fails in both directions at once: a genuinely removed object stays live for the window, and a real object is retired when the collector was merely broken for the window, with no record distinguishing the two. It is what a system settles for when it has no completeness signal.

Under evidence that permits the inference, one observation suffices: a candidate absent from an enumeration whose attributes license absence is dropped from observation *now*, and waiting adds only staleness. A count check that reconciles is part of that evidence but is not sufficient on its own — where the surface cannot establish source consistency, the corroborating probe must establish that the **identity** is gone rather than merely unlisted (`req-grid-reconcile-falsifier`). Where the enumeration cannot license absence on its own — `source_consistent: unknown`, which is the common case — the corroboration required is a **second independent observation** of a different kind (the direct probe), not a repetition of the same observation after a delay. Verdicts carry their evidence strength for the record, never as a threshold to be accumulated.

#### Development
The field's common practice is the opposite: inventory and directory systems use retention windows (measured in days) because their collectors cannot report completeness. The choice here is only available because the evidence contract exists; if a type's evidence can never license absence, the correct answer is that the type is not reconcilable, not that a clock decides.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-hysteresis-1 | No elapsed-time threshold | Proposed | No code path retires a node on the basis of time since last observation. | |
| req-grid-reconcile-hysteresis-2 | Probe corroboration where required | Proposed | For a type whose enumeration cannot establish source consistency, a retirement requires a direct probe in addition to the enumeration. | |
| req-grid-reconcile-hysteresis-3 | Strength recorded, not thresholded | Proposed | Evidence strength is recorded on the retirement and is not accumulated across runs to reach a threshold. | |

#### Future
If a source is ever found whose enumeration is snapshot-consistent, its types may retire on the enumeration alone, and this requirement's second criterion becomes conditional on the source rather than universal.

---

### Bulk-Absence Circuit Breaker
----
RID: `req-grid-reconcile-breaker`

Status: `Proposed`

**Per parent.** A parent whose verdicts would retire an implausible share of what the run observed for it **stops before applying any retirement or other graph mutation for that parent's subtree**, records why in the run record, and waits for an operator. Healthy parents in the same run apply normally — the quarantine is scoped to the parent that tripped, never to the whole run, because a run that walks two hundred repositories should not have one bad credential block the other hundred and ninety-nine. Nothing already applied is rolled back; the trip prevents the tripped parent's writes rather than reversing anyone else's.

#### Status Details
Proposed, for the phase where retirement authority is first switched on. The budget in `req-grid-reconcile-verb` bounds how many falsifier calls a run may make; this bounds how much of the graph one run may retire. They are different limits: a run can stay well inside its probe budget and still convict everything it looked at, because the failure that produces mass absence — a credential that lost a scope, a source that returned an empty listing, a collector pointed at the wrong account — makes every probe answer cheaply and consistently wrong.

#### Implementation
**The shape, and the failure it is for.** Every system that ships an absence sweep eventually ships this, and the ones that did not are the cautionary tales. HashiCorp deprecated `terraform refresh` for exactly this scenario: *"If you have misconfigured credentials for one or more providers, Terraform may be misled into thinking that all of the managed objects have been deleted, causing it to remove all of the tracked objects without any confirmation prompt."* The same shape reached production in Backstage, where an ambiguous entity read by an orphan sweep as parentless deleted the live record.

**Evaluated per parent, not per run.** The denominator is the observed set of **one parent under the run's scope statement**, and every parent is evaluated independently. A run-wide denominator is not sufficient and is the evasion this requirement exists to close: a run that walks two hundred repositories and loses its credential for one of them would divide that one catastrophe by the whole run's observed set and stay comfortably under any threshold. `reconcile` already walks the declared descent outer-in, checking a prerequisite per parent, so the per-parent observed set is the quantity it already has in hand. One tripped parent quarantines its own subtree's retirements; healthy parents in the same run are unaffected and apply normally.

**Two dimensions, because either alone is wrong.** The breaker trips when the retiring **share** of what the run observed exceeds a threshold **and** the absolute number of retirements reaches a floor. Both are needed: a bare count cannot tell a small scope's ordinary churn from a large scope's catastrophe, and a bare share cannot tell them apart either — three objects observed with two retired and three thousand observed with two thousand retired are the *same* 67% share, and only the second is implausible. The share catches the credential failure; the floor keeps a three-object scope from tripping on ordinary churn. DataHub's default is a 75% relative change and it stacks two further breakers beneath it: one for a source that reported a failure, and one for a source that produced no metadata at all, *"a fail-safe mechanism to prevent the accidental deletion of all entities"*. Microsoft Entra ships the same control as an export-deletion threshold, defaulting to 500, which *"stops before deleting any object"* and quarantines the job for an administrator to allow or reject.

**Deferral, not discard — this is the part worth copying exactly.** When DataHub trips, it carries the previous run's state forward so the retirement is applied by the next *successful* run rather than being forgotten. A breaker that drops the verdicts converts one loud failure into a silent one: the next run sees a smaller delta and the absence is never noticed again. So a tripped run preserves its verdicts, marked unapplied, and the operator either releases them or a later complete run supersedes them.

**Quarantine is an operator decision, not a retry.** A tripped run does not retry itself on the next schedule, because the condition that tripped it is usually still true, and a loop of tripped runs reads as noise. It waits, visibly, with the scope and the share recorded.

**The default is on.** A breaker that must be enabled is absent on every instance nobody configured, which is every new instance. The threshold is operator-tunable; the breaker's existence is not.

#### Development
The defaults worth arguing about are the share and whether an empty observed set is special. It is: a scope that observed nothing at all cannot license retiring everything it previously believed, and that is a distinct case from a partial read — DataHub treats it separately for that reason.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-breaker-1 | Share and floor together | Proposed | The breaker trips only when the retiring share of the observed set exceeds the threshold **and** the retirement count reaches the floor. A fixture retiring two of three passes (same share, below the floor); two thousand of three thousand trips; and a fixture above the floor but below the share threshold passes, so neither dimension alone decides. | Corrected on review (Codex on #549): the original examples were both 67% and could not be distinguished by share alone. |
| req-grid-reconcile-breaker-6 | Evaluated per parent | Proposed | The share is computed against one parent's observed set under the run's scope statement, and each parent is judged independently: a fixture where one parent would retire its whole subtree while two hundred others are healthy trips for that parent and applies the rest. A run-wide denominator fails this test. | Codex on #549: a localized catastrophe divided by a run-wide observed set evades any global threshold. |
| req-grid-reconcile-breaker-7 | The run record is written, the graph is not | Proposed | A tripped parent writes its run-record entry naming the scope, the share and the count, and mutates no entity or edge. | Resolves the "stops before writing anything" ambiguity (Codex on #549). |
| req-grid-reconcile-breaker-2 | An empty observation never licenses retirement | Proposed | A scope whose run observed nothing retires nothing, regardless of the threshold, and records the reason. | The credential-lost-a-scope case. |
| req-grid-reconcile-breaker-3 | Deferral, not discard | Proposed | A tripped run preserves its verdicts as unapplied; a later complete run can supersede them, and nothing is silently dropped. | The failure mode a discarding breaker creates. |
| req-grid-reconcile-breaker-4 | Quarantine, not retry | Proposed | A tripped run does not re-attempt on its next schedule; it waits for an operator decision, with scope and share recorded. | |
| req-grid-reconcile-breaker-5 | On by default | Proposed | The breaker applies with no configuration; only its threshold is tunable, and a test asserts a fresh instance is protected. | |

---

### Absence Has Three States On Every Surface
----
RID: `req-grid-reconcile-absence-states`

Status: `Proposed`

**Retired**, **not seen by this run**, and **not observable by this credential** are three different facts, and no surface may collapse them into two.

#### Status Details
Proposed. The verdict vocabulary in `req-grid-reconcile-falsifier` already distinguishes them at the moment of *decision* — that is what `UNDETERMINED(forbidden | errored | rate_limited | budget | scope_unknown)` is for. This requirement carries the distinction outward to every place absence is *rendered*: run records, reports, panels, the read path, and anything an AI helper reads. A verdict that is honest inside the engine and lossy on the way out has not helped.

#### Implementation
**The naming already exists in the field.** AWS Config enumerates configuration-item status as `OK`, `ResourceDiscovered`, `ResourceNotRecorded`, `ResourceDeleted` and `ResourceDeletedNotRecorded` — deletion and observability factored **orthogonally**, so "we did not record this" can never be read as "this is gone". That factoring is the requirement; the names here stay ours.

**Why it is a correctness rule rather than a presentation preference.** This is the standing `presence-is-not-correctness` rule applied to absence: a `bypass_actors` field missing from an API response once rendered as "nobody can bypass", produced by a credential that simply could not look. Absence of evidence must never render as evidence of absence. A tombstone means TAP observed the object leave; a blank means TAP did not look, or could not.

**What it forbids concretely.** A node that is live but unobserved by this run is not rendered as retired. A scope the run could not read contributes no absence at all, and says so. A report that lists "retired this run" alongside "unobserved this run" labels which is which. A count of absent objects is never a count of retirements.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-reconcile-absence-states-1 | Three states, never two | Proposed | Retired, unobserved-this-run and not-observable are distinct in the run record and in every surface derived from it; a test asserts all three appear for a fixture that produces one of each. | |
| req-grid-reconcile-absence-states-2 | A credential that could not look reports nothing gone | Proposed | A scope whose read was forbidden or errored contributes no absence and renders as not-observable, never as retired or as zero. | Directly the `bypass_actors` failure. |
| req-grid-reconcile-absence-states-3 | Counts are labelled | Proposed | No surface reports a single "absent" total; retirements and unobserved rows are counted separately. | |

---

## Cross-References

- `tap_grid/specs/spec-grid-entity.md` — `req-grid-entity-natural-key` (assigned ids, derived keys, the key document), `req-grid-entity-tombstone-managers` (where tombstone state lives), `req-grid-entity-cascade` (edge-directed cascade).
- `tap_grid/specs/spec-grid-service-delete.md` — `req-grid-service-delete-tombstone` (the existing tombstone contract), `req-grid-service-delete-reason` (reason and metadata), `req-grid-service-delete-cascade` (contained-subtree cascade and its authority).
- `tap_grid/specs/spec-grid-history.md` — the record clock, which `req-grid-reconcile-evidence` distinguishes from the source clock.
- `tap_grid/specs/spec-grid-import-grift.md` — `req-grid-import-grift-removals`: the importer does not infer deletion from absence, and removals are imperative and reason-carrying. Reconciliation produces removal targets; it does not change that stance.
