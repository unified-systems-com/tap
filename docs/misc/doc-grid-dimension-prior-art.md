---
spec: ../../tap_grid/specs/spec-grid-dimension.md
audience: [developer, llm]
covers:
  - ../../tap_grid/specs/spec-grid-dimension.md
  - req-grid-dimension-em
  - req-grid-dimension-dc
  - req-grid-dimension-dn
  - req-grid-dimension-node-identity
  - req-grid-dimension-no-edges
  - req-grid-dimension-reference
  - req-grid-dimension-lifecycle
  - req-grid-dimension-tabled
  - ../../tap_grid/specs/spec-grid-node.md
update-triggers:
  - The dcom trial concludes — record what the storage shape and the provenance map actually cost
  - The provisional provenance map shape changes or is dropped (req-grid-dimension-reference)
  - Someone wants to put a structured (non-string) value in a dimension — that is the signal for the second map
  - A dimension-to-dimension edge type is proposed, which means replacing INBOUND_EDGES = [] with a map
  - A dimension key grammar validator is built (today nothing validates the dotted grammar)
  - A surveyed system changes a behavior this doc contrasts against, making a row stale
assumes:
  - Reader has read spec-grid-dimension.md (the requirement surface) — this doc is the reasoning behind the 2026-09-20 redesign, not a re-spec
  - Reader knows what a TAP Entity, Edge and dimension map are at a working level
provides: |
  The reasoning record behind the 2026-09-20 dimension redesign: a dimension becomes a node
  with an assigned uuid, nothing draws an edge to it, entities reference it by id, and its
  history carries deprecation. Nine prior-art sweeps (Kubernetes, OpenTelemetry, OCSF,
  Palantir Foundry, STIX, Terraform, Neo4j, Cartography, AWS/Prometheus/Wikidata/Dublin Core)
  supply the evidence. Records what TAP got right independently, what the defects are, what
  was deliberately tabled and why, and the negative results of the search. DESIGN ONLY — no
  code exists for any of it.
---

# Dimensions as Nodes — Prior Art and the Reasoning Behind the Redesign

Owning spec: [spec-grid-dimension.md](../../tap_grid/specs/spec-grid-dimension.md)

## What this is

On 2026-09-20 the dimension model was redesigned. This doc is the *thinking*, preserved so
that a cold reader — human or AI helper — can reconstruct **why** rather than only **what**.
The **what** lives in the spec as requirements; everything here is the argument that produced
them.

Nothing described here is built. There is no code, no migration, and no scheduled work beyond
a single trial: `dcom` goes first, alone.

### Honesty about method

Three classes of statement appear below, and they are labelled where it matters:

| Label | Meaning |
| --- | --- |
| **Verified** | Read from the primary source — this repo's tree at the cited path, or the surveyed project's own published documentation/artifact |
| **Inferred** | A conclusion drawn from verified facts, not itself stated by any source |
| **Not verified** | Believed, useful, and *not* checked against a primary source — treat as a lead |

Two negative results are worth stating up front, because their absence shaped the argument:

- **No primary-vendor cardinality post-mortem was found.** The supernode objection — the one
  that makes every surveyed graph system refuse to model keys as nodes — is argued from
  vendor *guidance* (Neo4j's modelling advice) and from the structural shape of the problem,
  not from any vendor's published incident write-up. Nobody surveyed has published "we made
  our tags nodes and here is the bill." The objection is sound on arithmetic; it is not
  backed by a war story.
- **One sweep could not reach GitHub** and worked from the published package artifact
  instead. Its numbers are therefore counts over a release, not over the repository at HEAD.
  Where that matters it is flagged inline.

---

## Part 1 — What TAP already got right, independently

Before the defects, the convergences. These are places where TAP arrived at the same answer as
a mature system without having looked, which is the strongest available signal that the answer
is load-bearing rather than arbitrary.

### Caller-wins merge

TAP's `req-grid-dimension-dc` merge rule is: defaults form the base, caller-supplied keys are
merged on top, explicit wins on collision. **Verified** in `tap_grid/models.py`
(`BaseModel.save()` auto-creation path) and re-applied on the prespecified-entity-id path in
the service layer.

OpenTelemetry's Resource merge specification says the same thing in different words: if a key
exists on both resources, the value of the *updating* resource must be picked. Two systems, no
contact, one rule. That rule is not a coin-flip — it is the only choice that makes defaults
useful, because a defaults-win rule would make a default impossible to override and therefore
impossible to declare safely.

### Dimensions are not edges

The spec's rule of thumb — if representing a collection would need a bajillion edges across
most entity types, it is a dimension, not an edge — is the same boundary Neo4j draws in its
modelling guidance. Neo4j's promotion test: promote a value to a node when you **traverse
through it** or **anchor on it**; leave it as a property otherwise. Its worked counter-example
is 200 million people with gender modelled as a node, producing roughly 100 million
relationships onto a handful of nodes. Neo4j names "each attribute split into its own node" as
an extreme to avoid.

TAP's original spec reached this by feel — the `Background` section records the author's
instinct that a dimension-as-node-plus-edges design "would result in a ton of edges, which
would choke up the database". That instinct was correct, and it is the instinct the redesign
must not discard. See Part 3.

### The value describes the observation, not the thing

The `dcom` axis descriptions (**verified** in
`_dev-plugins/dcom/tap_plugin/dcom/grift/dimensions.grift.json`) say a pipeline's *definition*
is configuration and each *run* of it is an operation — the label attaches to the kind of fact,
not to the subject. This is the same discipline that keeps OpenTelemetry's semantic
conventions coherent, and it is the property that makes staleness reasoning possible: only
facts derived from configuration can go stale, because only configuration changes.

---

## Part 2 — The defects

### D1. The vocabulary has no identity of its own

Today a dimension key is a **string in a JSON map**. Its identity *is* its spelling. Rename it
and every entity carrying it is silently wrong; there is no object to version, deprecate, or
point at.

This is the exact failure Dublin Core hit. Unable to change `dc:creator` without breaking every
consumer, it minted a parallel namespace; both namespaces have now been live and supported
"indefinitely" since 2008. The same shape, at industrial scale, is `javax` → `jakarta`: a
namespace-change-only release, roughly three years of ecosystem work, zero new functionality
delivered. **Not verified** as to exact dates; the shape is what matters.

The remedy every survivor converged on is the same: **separate the identifier from the
label**. Palantir Foundry is the clearest statement of it — a property carries a RID that is
*not editable* beside a Name that is *fully editable*, and when a shared property type is
adopted, the local property's id and API name deliberately **stay unchanged** so downstream
consumers do not break. Foundry also keeps a **Usage back-index** on shared property types, so
the blast radius of a change is a query rather than a guess.

TAP already has this rule, written down, for entities: CLAUDE.md's ruling that entity ids are
**assigned** (UUIDv7 at first sight), never derived from a hash of the thing's facts. The
vocabulary simply never had it applied.

### D2. The declared grammar is not enforced, and is already violated

`req-grid-dimension-em` declares the JSON shape: flat object, namespaced keys separated by `.`,
lower case, string values.

**Verified:** three live dimension keys are undotted, violating the spec's own stated grammar —
`tap_cares` (`tap_cares/models.py`), `compliance` (`compliance_core`), and `dcom` itself.
**Verified:** nothing validates the grammar anywhere in `tap_grid/` — no regex, no
reserved-key check, no validator. The grammar is documentary.

This is the presence-is-not-correctness pattern in its purest form: a *declared* constraint
that no gate tests, so the declaration reads as enforcement to anyone who greps for it.

Every surveyed system that cared about key quality made the check **structural** rather than
documentary:

- **OCSF** ships a `dictionary.json` of 968 attributes plus a metaschema with
  `additionalProperties: false` and `required: [caption, description, type]`; the compiler
  **fails closed** on an undeclared key.
- **Prometheus** strips `__`-prefixed labels in the pipeline. The reservation is enforced by
  the code path, not by a style guide.
- **Kubernetes** reserves `kubernetes.io/` and maintains a well-known-keys registry which its
  own documentation describes as serving "both as a reference to the values and as a
  coordination point for assigning values" — the registry is the coordination mechanism, not
  a list of suggestions.

And the counter-example, which is the strongest single number in this doc: **NCBI BioSample**.
6.6 million records, metadata *mandatory*, no structural validation. Result (arXiv:1708.01286):
**15% of fields used names absent from the data dictionary**, and **only 27% of Boolean values
were valid**. Mandating a field without validating it produces a field that is present and
wrong — which is worse than absent, because nobody goes looking for the thing the record says
is handled.

**Cartography** is the closest prior art TAP has — a graph of infrastructure assembled by
independent collector modules, which is structurally TAP's problem. Its written rule is to add
a description to every property. **Verified** (from the published package artifact; this is the
sweep that could not reach GitHub): **10,417 of 16,056 property declarations carry a
description — 64.9%**. The rule is real, the compliance is two-thirds, and the reason is that
the docs build *renders the gap* rather than failing on it. A gap that renders is a gap that
ships.

### D3. Provenance is unrecoverable

When a dimension appears on an entity, nothing records **how it got there** — declared by the
caller, applied from `DEFAULT_DIMENSIONS`, or derived by some later process. `req-grid-dimension-dc`
merges all three into one flat map and the merge is lossy.

HashiCorp named this root cause explicitly for Terraform's `default_tags`: "there is no
property that indicates whether a tag was created globally or at a resource level." The
downstream consequence is that there is still no way to *exclude* a single resource from a
default tag — you cannot subtract what you cannot distinguish. That is the whole argument for
storing provenance, and it is why the redesign stores it even though nothing reads it yet.

### D4. Custom keys have no extension story

TAP has no convention for "this key is mine, not core's". The instinct is a prefix. The
instinct is wrong, and two independent sources say so:

- **STIX 2.1** deprecated its entire custom-property section — the `x_` prefix convention —
  and replaced it with a first-class **Extension Definition object**. A prefix became an
  object.
- **RFC 6648** independently deprecates `X-` prefixes across protocol design and tells
  designers to build a registry instead.

The convergence is not about prefixes being ugly. It is that a prefix carries no metadata: it
cannot say who owns the key, what it means, when it was introduced, or what replaced it. An
object can.

---

## Part 3 — The rulings, and the argument for each

Ruled by George, 2026-09-20. These are decisions, not proposals.

### R1. A dimension is a node

**The deciding argument is transference.** A dimension's meaning must move between grid
entities, batches and plugins. The grid already moves nodes — that is what GRIFT is for. A
registry would need a second distribution mechanism invented beside it, and that mechanism
would have to solve, from scratch, every problem the node path already solves: identity,
import, provenance, history, cross-plugin visibility.

This is the derive-a-fact-once rule applied to *mechanism* rather than to data: not "don't
copy the fact" but "don't build the second pipe."

Note what this does **not** overturn. The original spec's `Background` section rejected
dimension-as-node **because of the edges** — "it would result in a ton of edges". R2 removes
the edges. With the edges gone, the objection that produced the JSON-map design no longer
applies, and the design can change without contradicting the reasoning that produced it. The
spec even anticipated this: "we'll introduce the concept of a dimension node because it's
going to come in handy much sooner than I think."

### R2. Nothing draws an edge to a dimension node

This is the load-bearing ruling. It is what stops the dimension node becoming a supernode —
the objection that made every surveyed system refuse to model keys as nodes, and the objection
TAP's own author raised in 2 above.

Implemented as `INBOUND_EDGES: ClassVar[list] = []` on the `Dimension` model, with
`OUTBOUND_EDGES = []` alongside it for now.

**Why an empty list is absolute, verified in the tree:**

- `tap_grid/constraints.py` `validate_edge()` runs a **Permission Union** — its docstring:
  an edge is allowed if EITHER node OR edge type constraints permit it, *"unless explicitly
  blocked by the node"*.
- **Phase 1** of that function checks `_is_explicitly_blocked_outbound` /
  `_is_explicitly_blocked_inbound` and raises `InvalidEdgeError` before any permission union
  is computed. The comment on that phase reads: "these always fail, edge constraints can't
  override".
- `_is_explicitly_blocked_inbound` returns True exactly when `constraints.inbound == {}`.
- `_parse_constraint_list([])` iterates zero entries and returns `{}`.

So `INBOUND_EDGES = []` → `{}` → Phase-1 block → **a wildcard edge type cannot override it**.
The declaration is structural, not documentary. This is the D2 lesson applied to the redesign's
own central rule: it is enforced by a code path, in the way Prometheus's `__` stripping is,
rather than written in a style guide the way TAP's dotted grammar is.

**Two things that could have broken this, checked:**

- **Batch membership is not an edge.** **Verified:** `batch_id` is stamped on typed rows
  (`tap_grid/batch.py`; `batch_counts` queries `n.data.batch_id`), and the core edge type
  `PRODUCED_BATCH` targets `batch`, not `dimension`. GRIFT can therefore import dimension
  nodes into a batch with inbound edges blocked.
- **No edge type in the tree names `dimension` as a source or target.** **Verified** by
  grepping every `"type": "dimension"` occurrence across the core apps and `_dev-plugins/` —
  zero hits.

**One check that proves nothing, recorded so nobody cites it.** Querying the live session grid
returned "0 inbound edges, 0 outbound edges" on the four dimension nodes. That grid also has
**0 edges in total**, so the result is vacuous — it is consistent with the rule and equally
consistent with its opposite. Absence of evidence is not evidence of absence; the static grep
above is the evidence, and the runtime query is not.

### R3. Entities reference dimensions by assigned id, not by dotted name

The dotted name becomes a **mutable label on the node**. Identity moves to a UUIDv7 assigned
at first sight.

This is CLAUDE.md's existing entity-id ruling applied to the vocabulary, and it is Foundry's
RID-beside-Name split arrived at from a different direction. It is the direct cure for D1: a
rename becomes an edit to one node's `name` field, not a migration across every entity that
ever carried the key.

`Dimension` is already declared `KEYLESS` with the reason *"authored, not observed: a dimension
is vocabulary TAP declares, and its identity arrives in the GRIFT document that declares it"*
(**verified**, `tap_grid/models.py`). Assigned identity is what that declaration already
implies; R3 makes the storage shape honour it.

### R4. Dimension nodes carry history

They are spine nodes, so they get versioning for free. **Verified:** `tap_grid/history.py`
states that all concrete `BaseModel` subclasses automatically get history tracking via the
`HistoricalRecords` manager on the abstract `BaseModel`.

This is the deprecation machinery **OpenTelemetry had to hand-build**. Its `http.method` →
`http.request.method` rename required inventing a **schema file format** plus a dual-emit
opt-in (`OTEL_SEMCONV_STABILITY_OPT_IN=http/dup`) so consumers could migrate. OCSF likewise
built a `@deprecated` annotation carrying `superseded_by`, and — worth noting for TAP's
three-state discipline — `superseded_by` may be an explicit **empty array** meaning "removed
with no successor". Three states, not two: *has a successor* / *deliberately has none* /
*nothing said*.

TAP gets the timeline as a property of the node being a node. The spec must be precise about
one boundary, though, and Part 4 states it.

### R5. Dimension provenance is stored — PROVISIONAL

The map becomes `{"<dimension-node-uuid>": {"v": "configuration", "src": "declared"}}`, where
`src` is one of `declared` | `default` | `derived`.

The argument is D3: HashiCorp named the missing property, and the missing property is why
`default_tags` still cannot be excluded per-resource. Storing it now costs one nested key;
retrofitting it costs a migration over every entity on the grid. That is the security-posture
asymmetry — cheap now, expensive later — applied to a data shape.

It is marked **PROVISIONAL** deliberately. Nothing reads `src` yet. If the dcom trial shows
nobody needs it, dropping a key nothing reads is cheap; that is the right way round.

**This ruling amends an Implemented requirement, and the spec must say so.**
`req-grid-dimension-em` declares "Flat Object — use a flat JSON object, not nested namespace
objects" and "Value Types — allow values to be `string`". A nested provenance object violates
both. **Verified** in the same direction from the code: `DEFAULT_DIMENSIONS` is typed
`ClassVar[dict[str, str]]` on every declaring model. This is a real conflict, not a wording
nit, and it is why the new requirement carries an explicit amendment note rather than quietly
contradicting the old one.

One thing that survives the change: the GIN index on `dimensions` supports JSONB containment
(`@>`), and containment is recursive, so `@> '{"<uuid>": {"v": "configuration"}}'` still
matches. The Accessible goal is not lost. **Inferred** from Postgres containment semantics —
not measured against this schema.

### R6. Storage is key id + string value

The entity stores the **key node's uuid** and a **plain string value** — not value-node ids.

The reason is that value nodes only work for **closed** value sets. `dcom` has exactly three
values, so value nodes are natural there. But an **open** key — a forge hostname, say — cannot
have a node per value without minting a node for every string anyone ever observes, which is
precisely the "each attribute split into its own node" extreme Neo4j names. And two storage
shapes, one for closed keys and one for open, would be worse than one shape: every reader,
every query, every migration would have to branch.

Closed-key value nodes therefore survive as the **published expansion** — the dictionary
entry a human or an AI helper reads to learn what `configuration` means — and not as the
storage form.

**The honest cost, which the spec should carry:** `dcom` ships four nodes today (**verified**,
and the live grid holds exactly these four and nothing else: `dcom`, `dcom.design`,
`dcom.configuration`, `dcom.operation`). Under R6 an entity stores the *axis* node's uuid and
the string `"configuration"`. The node named `dcom.configuration` is then never referenced by
any stored value — so the string `"configuration"` and the node name `dcom.configuration` are
two copies of one fact, exactly the shape derive-a-fact-once exists to prevent. The
justification is that the second copy is *published documentation*, not a second authority, and
that the alternative (two storage shapes) is worse. It is a real cost, accepted knowingly, and
it is the first thing the dcom trial should be asked about.

### R7. The delimiter stays `.`

George's preference, explicitly ruled. Two costs, recorded:

1. **Namespace-prefix search becomes two-phase.** With names on nodes and ids on entities, "all
   entities under `dcom.*`" is no longer one JSONB prefix query: resolve names to ids, then
   query the id set.
2. **The dot is overloaded.** The dot in `git.host` is a namespace separator; the dot in
   `github.com` — a plausible *value* for that key — is part of a hostname. Same character,
   two meanings, adjacent in the same record.

Neither is load-bearing **while the id carries identity**, which is the whole point of R3. If
identity ever leaks back onto the name, both costs become sharp. OpenTelemetry's own naming
rule — *"Names SHOULD NOT coincide with namespaces"* — is the guardrail for the class of
problem cost 2 belongs to, and is worth adopting if the dotted grammar is ever enforced.

### R8. The third dcom value is `operation`, not `observation`

The plugin on disk is already correct (**verified**: the four nodes are `dcom`, `dcom.design`,
`dcom.configuration`, `dcom.operation`).

The reasoning matters more than the word. "Observation" describes **how we came to know a
fact** — collected, declared, inferred. That is a *different axis* from design/configuration/
operation, which describes **what kind of fact it is**. A configuration fact can be observed or
declared; an operation fact can be collected or reported. Squeezing "observation" onto the dcom
axis would collapse two orthogonal questions into one slot, and the collapse is irreversible
once data carries it.

If an observation axis is wanted, it is a second key — and the dimension map is a map precisely
so that an entity can carry both.

### R9. Collectors hardcode dimension guids

George's ruling: *"If you know enough to want to stamp a dimension you've got pre-existing
knowledge so use the guid."*

No name lookup at write time. A collector that is stamping `dcom.configuration` already knows,
at authoring time, which axis and which value it means; resolving that through a name at run
time adds a lookup, a failure mode, and — worse — a dependency on the *current* spelling, which
R3 just made mutable. Hardcoding the guid is what makes the name safe to rename.

The trade is legibility: a hardcoded uuid in collector source says nothing to a reader. The
mitigation is a comment naming the dimension beside the guid, which is documentation of a fact
the guid already fixes — acceptable, because the guid remains the authority and the comment
cannot silently become the authority.

### R10. dcom goes first, alone

Everything else in the vocabulary stays exactly as it is. `tap_cares`, `compliance`, `tap.meta`,
`tap.graph` — untouched.

The case for a small trial is strong here because **the cost of being wrong is currently near
zero**. **Verified:** the live grid holds exactly four `Dimension` rows, all of them dcom's. No
other plugin ships dimension nodes. George's assessment: *"Nobody is using them for anything
right now."* There will never be a cheaper moment to change the shape, and there will never be
a cheaper moment to discover the shape is wrong.

**The tension this ruling has with R3/R6, which is not resolved.** A trial scoped to one axis
works cleanly for a *vocabulary*. It does not work cleanly for a *storage shape*, because the
entity `dimensions` map is one column shared by every key: "dcom moves, nothing else does"
means uuid-keys and name-keys in the same object, with values that are sometimes strings and
sometimes objects. Every reader would branch — which is the same two-shapes objection R6 uses
to reject value nodes, arriving from the other direction.

Sharper still: `Dimension` declares `DEFAULT_DIMENSIONS = {"tap.meta": "dimension"}`, so a
dimension node's own dimensions would reference the uuid of the `tap.meta` dimension node,
which is itself a `Dimension` that must therefore exist before any dimension node can be
created — including itself.

This is recorded as an **open question** on `req-grid-dimension-reference` in the spec, with
three candidate resolutions and none ruled, and it is why that requirement alone is `Proposed`
rather than `Approved for Development`. It does not invalidate R10; it means the *behaviour*
trial and the *shape* migration may not be scopeable to the same boundary.

Wikidata is the scale argument on the other side of the same coin: roughly 97 million items
against roughly **10,000** properties, with property creation gated behind a week of public
discussion. The vocabulary is meant to be small, slow-moving, and deliberate; a trial of one
axis is the right granularity for a thing that should only ever grow by tens.

---

## Part 4 — The history boundary, stated precisely

R4 gives dimension nodes history. It is worth being exact about what that history answers,
because the natural reading is wrong.

| Question | Answered by | Read |
| --- | --- | --- |
| What did this key mean in March? When was it renamed? When was it deprecated, and what replaced it? | The **dimension node's** history | One node's timeline |
| Did *this entity* carry that key in March? When did it gain it, and who put it there? | The **entity's** history | That entity's timeline |

The node's history is **the key's life**. Whether a given entity ever carried it is the
**entity's** history — a separate read, against a different object.

Conflating them is how a deprecation looks like it has been handled when it has not: the node
says "deprecated 2026-03-01, superseded by X" and every reader concludes the entities moved,
because the reassuring record exists. Nothing in the node's timeline says anything at all about
any entity. Two reads, always.

---

## Part 5 — Deliberately tabled

These are **decisions to defer**, recorded with reasoning, not omissions.

### T1. No mandate

Dimensions are not made mandatory.

The evidence is BioSample, quoted in D2: 6.6 million records, mandatory metadata, no structural
validation, and the result was 15% of fields using undeclared names and 27% of Booleans valid.
Mandating presence without validating correctness manufactures exactly the failure TAP's
presence-is-not-correctness filter names — a declaration that exists and is false, which is
worse than a missing one.

**AWS** makes the same split visible in product form: Tag Policies explicitly **cannot** enforce
that a tag exists — their documentation states the capability does not enforce missing tag keys
— so presence enforcement has to live in a *separate* SCP that denies the create call. Two
mechanisms, because presence and correctness are two problems.

Note that `req-grid-dimension-dc`'s own `Future` section currently argues *toward* a stricter
world where a dimension-less type is a design error. T1 does not delete that ambition; it
declines to act on it before there is a validator, because a mandate without a validator is the
BioSample outcome.

### T2. No general-purpose delete-by-dimension

Instead: **custom per-case deletion functions** ("Option D"), with AWS account teardown as the
first canonical example.

**Kubernetes separates selection from deletion authority deliberately.** Labels select;
`ownerReferences` govern cascading deletion. They are different mechanisms on purpose, because
a label is a *view* over a set and a view is not a mandate to destroy its members. A
delete-by-label primitive turns every accidentally-broad selector into a data-loss event, and
selectors are broad by nature — that is what they are for.

TAP already has a containment story that mirrors this: `CONTAINMENT_EDGES` is a dedicated
declaration for cascade, explicitly *not* a flag inside `OUTBOUND_EDGES`, which is edge
permission only. Deletion authority is already modelled apart from permission; delete-by-
dimension would reintroduce the conflation from the other side.

### T3. No namespace reservation needed

Core's dimension nodes land at boot, and a plugin cannot overwrite an existing node. First-mover
occupancy replaces a reserved prefix.

**What makes this work is the immutability of an existing node — structural — not the prefix —
documentary.** That distinction is the entire lesson of D2 and of Prometheus's `__` handling.
Kubernetes reserves `kubernetes.io/` *and* maintains the well-known-keys registry as a
coordination point; TAP gets the coordination point for free because the node *is* the
registry entry, and gets the reservation for free because the node already exists.

The corollary worth watching: this holds only as long as "a plugin cannot overwrite an existing
node" is true and enforced. If that ever becomes a soft rule, T3 silently becomes false and
nothing will announce it.

### T4. The second map — raised and parked

Kubernetes splits **labels** (indexed, selectable, constrained) from **annotations**
(arbitrary, not indexed, not selectable). One key grammar, two stores, differing on whether the
value is indexed. The split exists because people inevitably want to attach load-bearing data
that is not a search key, and forcing that into the selectable store either bloats the index or
corrupts the grammar.

TAP may need the same split. It does not need it yet.

**The signal to watch for is the first time someone wants to put something structured — an
object, a list, a blob — in a dimension value.** That request is the second map asking to be
born. Note the awkwardness it will arrive with: R5 already puts a nested object in the map, so
the "values are strings" line is no longer clean, and the argument will be harder to hear than
it would have been. Watch for the *intent* (a value that is data rather than a label), not for
the *shape*.

Related but distinct: `spec-grid-dimension-pocket-BACKLOG.md` proposes draft "pocket
dimensions" as sparse overlays on canonical state. That is a different concept wearing the same
word — an isolation mechanism, not a vocabulary — and nothing in this redesign advances or
blocks it.

---

## Part 6 — Future consideration: dimension-to-dimension edges

George asked for this to be recorded explicitly.

R2 blocks all edges. But the useful relationships between *dimensions themselves* are real and
foreseeable:

- **broader / narrower** — an axis and its values, or a coarse key and a finer one
- **successor-after-rename** — OCSF's `superseded_by`, as a graph edge rather than a field
- **axis-grouping-its-values** — the relationship `dcom` already has to its three values,
  currently derived from the dotted name

There is a property here worth naming, because it is what makes the blanket block safe to
adopt today:

> `INBOUND_EDGES = []` opens later by **replacing the empty list with a map** naming one edge
> type and one source type. That opens exactly one door and no others.

The block is not a wall that must be demolished; it is a default-deny list that admits entries
one at a time. Contrast the reverse ordering — ship permissive, restrict later — which cannot
be done at all once edges exist, because restricting means deleting other people's data. This
is the security-posture asymmetry exactly: over-restriction relaxes cheaply, omission retrofits
expensively.

The reason not to open it now is that the dotted name already carries the axis-to-value
relationship (dcom's own GRIFT batch says so in as many words: *"No edges — the hierarchy is
derived from the dotted name … parent/child edges would be a second copy of a fact the name
already carries"*). An edge that duplicates a fact the name carries is a second copy to keep in
sync, and R3 has just made the name mutable, which makes the sync question sharper rather than
softer. The edge becomes worth building when it carries a fact the name **cannot** — a
rename successor being the obvious first one.

---

## Appendix — Sources, and what each contributed

| System | Contribution | Confidence |
| --- | --- | --- |
| **Kubernetes** | Selection vs deletion authority kept apart (labels vs `ownerReferences`) → T2. Labels vs annotations = one grammar, two stores → T4. Reserved `kubernetes.io/` + well-known-keys registry as "coordination point" → D2, T3. | Verified from published docs |
| **OpenTelemetry** | Resource merge rule identical to TAP's caller-wins → Part 1. `http.method` → `http.request.method` needing a schema-file format + `OTEL_SEMCONV_STABILITY_OPT_IN=http/dup` → R4. Four requirement levels (Required / Conditionally Required / Recommended / Opt-In). "Names SHOULD NOT coincide with namespaces" → R7. | Verified from published specs |
| **OCSF** | `dictionary.json`, 968 attributes; metaschema `additionalProperties: false`, `required: [caption, description, type]`; compiler fails closed on undeclared keys → D2. `@deprecated` + `superseded_by`, which may be an explicit empty array = "removed, no successor" → R4, three-state discipline. | Verified from published schema |
| **Palantir Foundry** | Non-editable RID beside fully-editable Name; shared property types carry a Usage back-index; on adoption the local id and API name deliberately do not change → D1, R3. | Verified from published docs |
| **STIX 2.1** | The whole `x_`-prefix custom-property section is **Deprecated**, replaced by a first-class Extension Definition object → D4. | Verified from published spec |
| **RFC 6648** | Independently deprecates `X-` prefixes; tells designers to build a registry instead → D4. | Verified |
| **Terraform `default_tags`** | HashiCorp's KB names the root cause: "there is no property that indicates whether a tag was created globally or at a resource level"; still no per-resource exclusion → D3, R5. | Verified from vendor KB |
| **Neo4j** | Promotion test (traverse through it / anchor on it); low cardinality against a large population → supernode, worked case 200M people × gender ≈ 100M relationships; "each attribute split into its own node" named as an extreme → Part 1, R2, R6. | Verified from vendor guidance — **not** an incident report |
| **Cartography** | Closest structural analogue (graph of infra from independent collectors). 10,417 / 16,056 property declarations carry a description = **64.9%** against a written rule requiring one, because the docs build renders the gap rather than failing → D2. Ontology layer namespaces derived keys as `_ont_<field>`. Introspection keeps a **tuple** of descriptions when modules disagree rather than picking one — a three-state instinct worth stealing. | Verified from the published package artifact (GitHub unreachable for that sweep) |
| **AWS Tag Policies** | Cannot enforce that a tag exists — presence enforcement lives in a separate SCP denying the create call → T1. | Verified from published docs |
| **Prometheus** | `__`-prefixed labels stripped in the pipeline: structural reservation, not documentary → D2, T3. `*_info` metric idiom keeps mutable version strings off the data. | Verified from published docs |
| **Wikidata** | ~97M items against ~10,000 properties; property creation gated behind a week of public discussion → R10. | Verified from published stats |
| **Dublin Core** | Could not change `dc:creator`; minted a parallel namespace; both live and supported "indefinitely" since 2008 → D1. | Verified |
| **javax → jakarta** | Namespace-change-only release, roughly three years, zero new functionality → D1. | Not verified as to exact dates; shape is the point |
| **NCBI BioSample** (arXiv:1708.01286) | 6.6M records, mandatory metadata, no structural validation → 15% of fields used undeclared names, 27% of Boolean values valid → D2, T1. | Verified from the cited paper |
