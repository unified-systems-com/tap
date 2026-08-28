---
name: build-domain-vocabulary
description: Decide WHICH base models and edges a new domain needs, before building any of them. Use when entering a space TAP has not modelled yet (a new product, initiative, or plugin covering an unfamiliar domain) — it gathers existing concept dictionaries, tests them against real-world failure, and produces a justified node/edge corpus that add-model and add-edge then build.
allowed-tools: Read Write Edit WebSearch WebFetch Task Bash(scripts/dc *) Bash(gh *) Bash(grep *) Bash(find *) Bash(ls *) Bash(mkdir *) Glob Grep
argument-hint: <domain-name> [owning-plugin-slug]
---

# Build a Domain Vocabulary

You are deciding **what pieces belong on the board** before anyone builds one. This is the most
consequential hour of a new initiative: a grid can only ever answer questions its vocabulary can
express, and a missing concept is not a bug you fix later — it is a question the product silently
cannot answer, for as long as it exists.

This skill sits **above** [`add-model`](../add-model/SKILL.md) and [`add-edge`](../add-edge/SKILL.md)
on the emergence ladder. Those build a type; this decides which types are worth building. It runs
**once per domain**, then again — cheaply — whenever the domain moves under us.

## The principle: gather, then invent

Almost every domain worth modelling has already been catalogued by someone. Standards bodies argue
for years about which nouns matter. Platform vendors publish their entire object model as an API.
Attackers and incident responders discover, expensively, which relationships were load-bearing.
Query tools and infrastructure-as-code providers publish table and resource lists that are entity
dictionaries wearing a different hat.

**Speaking the vocabulary the field already speaks is worth more than a cleaner private one.** It
makes our graph legible to newcomers, comparable to other tools, and defensible in a review. Invent
only where nobody has been, and say so explicitly when you do.

The corollary that keeps this honest: **do not adopt a dictionary wholesale either.** Committee
models over-abstract, platform models include everything the vendor happens to expose, and incident
lore overweights the dramatic. Gather widely; accept narrowly.

---

## Step 0 — Name the domain and its boundary

Write one sentence for each, before searching:

- **In scope.** The domain as the product's problem statement defines it.
- **Out of scope.** The adjacent domain everyone will confuse it with. Name it explicitly, because
  half the dictionaries you find will be about the neighbour.
- **The first real use case.** Vocabulary is tiered by demand; without a use case there is no
  principled stopping point and you will model forever.

## Step 1 — Inventory what already exists

**Query the running instance, not the source tree.** What is registered is the truth; what is in a
file may not be installed.

```bash
scripts/dc exec -T web uv run python manage.py shell -c "
from tap_grid.registry import list_entity_types
print('\n'.join(sorted(list_entity_types())))"
ls <plugin>/tap_plugin/<slug>/edges/          # edge definitions ship as files
```

Three separations matter, and getting them wrong wastes the whole pass:

1. **Domain types vs platform/meta types.** `batch`, `collector`, `collection_job`, `schedule`,
   `dimension`, `keystone`, and the web/viz types (`page`, `panel`, `search`, `projection`, …) are
   TAP's own furniture. They are never domain vocabulary and must never be re-invented per domain.
2. **What the estate already owns.** Another plugin may already hold a concept you need — the
   `*_core` substrate plugins exist exactly for this. Reuse beats invention; a second definition of
   the same concept is the derive-a-fact-twice anti-pattern wearing a graph costume.
3. **What the spine gives you free.** Entities carry `dimensions` (scoping) and **field-level history
   and provenance** automatically. "When did this change", "who observed it", and "what did it look
   like before" are answered by the grid, not by nodes you invent. Modelling a `change_event` type
   is usually a sign you have not read the history system.

## Step 2 — Gather from independent directions

Run these as **parallel research agents**; they are slow, and independent, and their disagreements
are the most informative output of the whole exercise. Each direction is biased in a *different*
way, which is precisely why you need all of them.

| Direction | What you gather | The bias it corrects | The bias it has |
| --- | --- | --- | --- |
| **Adversarial / incident corpus** | Every documented failure in the domain; for each, the entities and relationships its story *requires* to be representable | Committee models miss what actually breaks | Overweights the dramatic and the recent |
| **Standards and schemas** | Formal models, ontologies, control catalogues, taxonomies — with their entity *and* relationship lists | Gives industry-standard names and interoperability | Over-abstracts; lags reality by years |
| **Platform and tooling models** | The systems' own object models: API resource lists, GraphQL type lists, webhook/event taxonomies, IaC provider resources, query-tool table lists, existing graph schemas | Tells you what is actually *observable* | Includes everything the vendor exposes, most of which does not matter |
| **The field's people** | Researchers, maintainers, labs, working groups — and how to follow each | Vocabulary drifts; this is how you hear first | Not a source of concepts directly; a source of future ones |

Notes that save a pass:

- **An existing graph model of your exact domain is gold.** Look for one deliberately before
  anything else — someone may have published node and edge kind lists you can diff against directly.
- **Event taxonomies are entity dictionaries in disguise.** A list of "things that can happen"
  names the things they happen to.
- **IaC provider resources and query-tool tables are curated observability lists** — someone already
  decided which objects are worth reading and writing.
- **Pin what you read.** Record each source's version and date. That pin is what makes the update
  pass (Step 9) possible; without it you can only re-do the whole survey.

## Step 3 — Converge, then argue

- **A concept named by three or more independent sources is almost certainly required.** Adopt it
  and use the common name.
- **A concept named by exactly one source is a question, not an answer.** Interrogate it: is it real
  and under-appreciated, or an artefact of that source's purpose?
- **A concept the incidents demand but no standard names is the most valuable thing you will find.**
  It is where the field's formal models have not caught up with its failures. Model it, and say in
  the corpus that you are ahead of the standards there.

## Step 4 — Node, field, or edge property? (the discipline)

**Over-modelling is as harmful as under-modelling.** Every unnecessary node type is a join a human
and an agent must understand forever. Apply these tests, and record which one decided each call:

- **Does anything need to point at it?** If nothing ever forms an edge to the thing, it is a field.
  This is the strongest single test.
- **Does it have identity that persists across observations?** A thing you can name, re-find, and
  watch change is a node. A value that only makes sense inside its parent is a field.
- **Is the fact about the *relationship* rather than either end?** Then it is an edge property. Pin
  posture, granted permission, and which job references a secret all belong on edges.
- **Would you ever want it without its parent?** If not, field.

**The adjudication rule — shape is not severity.** An edge that merely records *that* a relationship
exists will produce confident nonsense in any view that scores risk. Edges must carry the properties
that let a reader distinguish *this shape exists* from *this shape is dangerous*. When you propose an
edge, propose its properties in the same breath, and justify each by the question it settles. A bare
line between two boxes is rarely worth drawing.

## Step 5 — Neutral or vendor-specific?

Mark every concept. The test is concrete, not aesthetic: **could a structurally different
implementation of the same domain populate this type?** Find a genuinely different second instance
of the domain and try to map it — not a competitor that copied the leader, but something that solves
the same problem a different way. Concepts that survive belong in a neutral `*_core` substrate;
those that do not are vendor vocabulary and should say so in their name.

Do the marking now even if the extraction happens later. Renaming a slug after it has shipped is the
expensive move; deciding its home on paper is free.

## Step 6 — Tier by demand

Every concept gets a tier tied to a real milestone — the first use case, the next one, later.
**Demand is the base case.** Without it, the survey's own momentum will carry you into modelling the
whole domain, which is the failure this discipline exists to prevent.

## Step 7 — Write the corpus document

The corpus is the deliverable, not a pile of research. It lives **with the vocabulary's owner** — the
plugin's `specs/` — because it is the specification of what that plugin models. The raw research
reports live with the *product* that commissioned them.

Required contents:

1. **Node inventory.** slug | neutral? | tier | status (exists / proposed / new) | **justification —
   which sources or incidents demand it**.
2. **Edge inventory.** Same, plus source → target and **the properties it carries, each with the
   question it settles**.
3. **Rejected candidates, with reasons.** As valuable as the accepted list: it stops the next person
   re-litigating, and it is the record that the question was asked.
4. **Source register.** Every dictionary consulted: name, version, date, URL, machine-readable
   artifact if any, and verdict (adopt / align / reference / ignore).

Provenance per concept is not bookkeeping — it is what makes Step 9 possible. When a standard
publishes a new revision you need to know, in one query, which of your types it touches.

## Step 8 — Build

Hand each accepted concept to [`add-model`](../add-model/SKILL.md) and
[`add-edge`](../add-edge/SKILL.md), tier by tier. Do not batch the whole corpus into one change; the
first few will teach you something the corpus got wrong.

**Each concept also owes a domain article** (`specs/spec-domain-articles.md`): a markdown file at
`<plugin>/domain/<concept>.md` saying what the concept *is in the world*, its natural key and why,
what it deliberately excludes, whether it is forge-neutral, and — the expensive part — which
credential and permission populate it and what is not observable at all. The corpus is the
*aggregate* justification; the article is the individual case, and it is what a future maintainer or
an AI assistant reads instead of the vendor's API reference.

The corpus feeds the articles almost line for line: a concept's justification row becomes its Prior
Art, its neutral marking becomes its Neutrality section, and the rejected-candidates table becomes
the Boundaries section of whatever concept absorbed each rejection. Write them while the corpus
research is still in hand — reconstructing "why is this a field and not a node" six months later
costs far more than recording it now.

A ratchet enforces the link: every registered type needs an article, and every `FIELD_CRUD_SCHEMA`
key needs a paragraph in it, so an article cannot drift from its model.

## Step 9 — Record the update seam

**Domains move.** This is not a hypothetical: compliance catalogues are revised constantly, cloud
providers add services continuously, and attack technique appears faster than any standard absorbs
it. A vocabulary built once and never revisited is wrong within a year, quietly.

For now, record — do not build — the following in the corpus's source register: for each adopted
source, the machine-readable artifact (schema URL, git repo, changelog feed, API), its cadence, and
where the "what changed" signal appears.

**The shape this takes when it is built** (named here so it is designed rather than improvised):

- **A ledger, not auto-generation.** A scheduled job re-reads the pinned sources, diffs against the
  recorded versions, and **opens a proposal** — an issue or a PR — for a human or an agent to judge.
  It must never mutate the vocabulary automatically. Precedent: the AWS service-detection ledger.
- **A coverage delta.** A generated burn-down of what the domain contains versus what we model, so
  the gap is a number that moves rather than a feeling. Precedent: the aws_core coverage delta.
- **The strongest form: the catalogue becomes grid data.** Where a source publishes a machine-
  readable catalogue, a collector can land it on the grid as nodes — then "what changed in the
  standard" is a graph query with history, not a diff someone remembers to run. Precedent: the
  FedRAMP KSI catalogue collector.

---

## Failure modes

- **Adopting a dictionary wholesale.** The platform's API exposes hundreds of resources; almost none
  of them matter to your problem. Gather widely, accept narrowly.
- **Modelling the platform's furniture as domain vocabulary.** If TAP already has the concept
  (batch, schedule, history), you are duplicating the substrate.
- **Bare edges.** Relationships with no properties look tidy and produce views that cannot tell safe
  from dangerous. See Step 4.
- **Surveying without a use case.** There is no natural stopping point; you will model the world.
- **Skipping the incident direction** because it is unpleasant reading. It is the only direction that
  tells you which relationships were load-bearing when something actually failed.
- **Not pinning sources.** Without versions and dates, the next update pass is a full re-survey.
- **Treating the corpus as final.** It is a dated artefact with a maintenance obligation. Say so in
  the document.

## Tips and tricks

*Append to this section as the method is exercised in new domains. Each entry: the observation, and
the domain that taught it.*

- **Query the running instance for the current vocabulary; never trust the source tree.** A type can
  exist in a file and not be installed. (git-serious, 2026-08)
- **Look for an existing graph model of your exact domain first.** If one exists, its node and edge
  lists convert a survey into a diff. (git-serious, 2026-08)
- **The product is the first consumer that can see the platform's defaults from the outside.**
  Surveying a domain surfaces defects in the substrate that the substrate's own tests cannot see.
  (git-serious, 2026-08)
- **A second, structurally different implementation is the cheapest neutrality test available** —
  cheaper than debating naming. (git-serious, 2026-08: the Linux kernel against a forge-shaped model)
- **Documentation gives you the rule; only a call gives you the failure shape.** A CI/CD corpus's
  three most valuable observability facts were all *correctly documented* — bypass actors need write
  access, the token-inventory endpoints are app-only, the GraphQL API carries no pipeline executions.
  Reading was not the mistake. What no page stated was what a refused caller actually *receives*:
  HTTP 200 with the field silently absent rather than an error, which makes absence read as "nobody
  can bypass" instead of "we could not look." Probing also surfaced an undocumented 403 on a
  neighbouring endpoint, and falsified the team's *own* conclusion about which credential was
  strictly better. Budget for probing — not because the docs lie, but because they describe the
  permitted path and you need the denied one. (git-serious, 2026-08)
- **Neither credential dominates — check both directions before recommending one.** The same survey
  found one credential type uniquely sees the exemption list and the other uniquely sees the grant
  inventory. "Use the App, it's strictly better" would have been wrong and would have shipped a
  silent gap. (git-serious, 2026-08)
- **Absence is not a finding until you know it is observable.** A blank "who can bypass this control"
  cell reads as *nobody can* — the most reassuring possible message — when it may mean *we were not
  allowed to look*. Any edge or view whose population depends on a permission owes its reader three
  states: none / some / not-observable. (git-serious, 2026-08)
- **Where one concept is really two, say so in prose — the slug cannot be fixed later.** A job as
  *declared* and a job as *run* are different objects; the existing slug had already claimed the
  obvious name, and slugs are identity and are never renamed. The distinction then survives only in
  a dimension and in the domain article, so both articles must state it explicitly or the next
  reader conflates them exactly as the rest of the field does. (git-serious, 2026-08)

### On feeds and living taxonomies

- **Verify a feed emits entries, not merely that it responds.** Two canonical feeds in this domain
  return a valid, well-formed, *empty* document — which is indistinguishable from "nothing has
  happened" until you check the entry count. A third publishes no releases at all, so its release
  feed can never fire. Test every feed for content before recording it as a watch. (git-serious,
  2026-08)
- **When a standard is frozen and a tool ships weekly, the tool is the living taxonomy.** A control
  list unchanged for four years sat beside an analyser whose rule set is revised continuously; the
  analyser's rules — not the standard — are where new observable conditions actually appear. Follow
  the thing that moves. (git-serious, 2026-08)
- **An unmaintained catalogue is worth noting as a gap in the field.** Where the domain's incident
  register has been abandoned, nobody is keeping score — which is both a research hazard and, for a
  product in that domain, a vacancy. (git-serious, 2026-08)

### On gathering standards

- **Poll the sources, not the maps.** The best cross-standard crosswalk in the field was itself one
  to three versions stale on *every* source it pinned. A map of the dictionaries is a convenience,
  never the authority. (git-serious, 2026-08)
- **A standard can revise mid-survey.** One foundational field list was superseded a month before the
  pass that surveyed it. Date every claim, and record the version you read — otherwise the corpus
  cannot tell "we chose this" from "this is what it said back then". (git-serious, 2026-08)
- **Look for the standards' own edge properties before designing yours.** The field had already
  standardised lifecycle scope, completeness, confidence, grant timestamps, justification, and
  enforcement level as properties *on relationships* — which is independent confirmation that bare
  edges are a mistake, arrived at by people who never met each other. (git-serious, 2026-08)
- **An empty space in a major schema is a finding, not a dead end.** Discovering that a large
  security schema has *no* vocabulary for your domain tells you the naming territory is unclaimed —
  which is strategic information, and worth reporting as loudly as a match. (git-serious, 2026-08)

### On the people pass specifically

- **Machine-readable governance files beat human-maintained rosters.** A project's steering-committee
  or MAINTAINERS file, versioned in git with a visible last-commit date, tracked personnel movement
  that university pages and one project's own maintainer file had missed by two years. Prefer a file
  you can diff over a page someone remembers to edit. (git-serious, 2026-08)
- **Publication databases are authoritative for output and unreliable for affiliation.** Use them for
  "what did they publish"; use a person's own site for "where are they now". Assuming otherwise put a
  researcher at an institution they had publicly left. (git-serious, 2026-08)
- **Follow funded centres as a unit, not their members individually.** A single multi-institution
  research programme's feed covered seven principal investigators at once; following each separately
  would have been seven watches for the same stream. (git-serious, 2026-08)
- **Some primary sources refuse automated fetch.** Name them as gaps in the report rather than
  substituting an inference — an honest "could not verify" is worth more than a confident guess a
  later reader cannot distinguish from a checked fact. (git-serious, 2026-08)
- **The venue can move.** A field's most on-topic conference relocated to a different host event, and
  the old host's programme was the only place that fact was visible. Verify a venue from *both* ends
  before treating its calendar as stable. (git-serious, 2026-08)

## References

- [`add-model`](../add-model/SKILL.md), [`add-edge`](../add-edge/SKILL.md) — what this skill feeds.
- [`build-collector`](../build-collector/SKILL.md) — how the vocabulary gets populated.
- `tap_grid/specs/spec-grid-node.md`, `spec-grid-edge.md` — the contracts a concept must satisfy.
- The owning product's `docs/` — where the raw research reports behind a corpus live.
