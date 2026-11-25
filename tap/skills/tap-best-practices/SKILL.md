---
name: tap-best-practices
description: The module-by-module guard rails for building on TAP — nodes and edges, dimensions and tags, layouts, tables, collectors and secrets, projects and plugins, specs and PRs. Read the sections for the modules you are touching before you start, check each group as you go, and finish by reviewing what you did and proposing additions to this skill. Use before building or changing a view, a table, a bundle, a spec or a plugin, and whenever you are about to invent something the platform may already have.
allowed-tools: Read Grep Glob
argument-hint: "[module or task, default: all]"
---

# TAP best practices

The shared defaults every piece of TAP work starts from are the thirteen in
[AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap), and that list stays the single
copy of them. This skill does not repeat it. It holds what is specific to one module or one kind of work, grouped
so you can read only the parts you need, and it is where a lesson from a review lands first, before it is
promoted into a spec.

## How to use it

1. Name the modules you will touch (`tap_grid`, `tap_viz`, `tap_web`, `tap_cares`, `tap_plugins`, `tap_boot`, or
   the process around them) and read those sections.
2. Work. When you are about to build something bespoke, ask the test from
   [`tap-conformance-audit`](../tap-conformance-audit/SKILL.md): **does TAP already have a native form for this?**
   A graph edge, a typed field, a dimension, a Search entity, a natural layout, a core helper, a Gryphon
   predicate. If it does, use it. If it does not, that is a demand signal for the owning plugin, not licence to
   build it in place.
3. Finish with the [review step](#last-step-review-and-propose-changes-to-this-skill). It is required.

## How rules are marked

Each rule carries where its authority comes from, because a rule you cannot check is an assertion:

- **canon** names the spec, requirement or AGENTS.md item that holds it.
- **ruling** is an owner decision made in conversation and not yet written into canon. It states the date and
  the decider. It is a prompt to promote it into a spec, and until it is promoted nobody else can verify it, so
  the review step lists every ruling that is still unpromoted.
- **observed** is a defect found in real work, with the date, kept so the next person recognizes it.

Each group also says what enforces its rules: **guard** (a check that exists), **audit** (found by
`tap-conformance-audit`), **candidate** (a mechanical check that could exist and does not), or **none** (judgement
only). Rules with a candidate are the backlog for guard rails.

---

## tap_grid — nodes, edges, identity, data

### Nodes and edges

- **Use released, standard types everywhere.** A picture is drawn from node and edge types an installed plugin
  declares; a type that is missing is a finding filed against the plugin that owns the concept, and the view
  waits for the release. *canon (spec-grid-edge, plugin type ownership); ruling George 2026-10-14 ("standard
  nodes and edges everywhere").* Guard: `validate_plugin`. Candidate: a check that every type a bundle uses is
  declared by the plugin version its boot record pins.
- **Check the pin before you use a new type.** A type merged to a plugin's main is not in the release the demo
  record pins; the record pins by peeled SHA and the type is usable only after a release and a re-pin.
  *observed 2026-10-14 (aws-core-tap#97, `aws_core` v0.6.0 against main).* Candidate.
- **Name edges `<ACTION>_<OBJECT>`.** A plain mechanical verb and the destination noun; no modal prefix (`HAS_`,
  `IS_`, `CAN_`), no trailing preposition (`_FROM` after an object is the data-reversal marker). *canon
  `req-tap-plugin-edge-naming`.* Guard: `validate_plugin`.
- **Do not mint flow edges to make a picture.** Draw from the official edges. A flow, a session, a reachability
  (anything with a sender, a thing that happens and a receiver) is a compound edge, not an ad hoc binary edge;
  anything else that is missing is recorded and discussed first. *ruling George 2026-10-14; canon in the
  playground v0 spec (`req-rampart-20x-playground-page-landing-2`) and `req-grid-edge-compound`.* Candidate.
- **Compound edges are official; plain edges for everything else.** A relationship with something in the middle
  is a middle-node type per kind, owned by the plugin that owns the concept and declared with `COMPOUND_EDGE`;
  its role edges are `<KIND>_SOURCE` (the initiator), `<KIND>_DESTINATION`, optional `<KIND>_CARRIER`, and
  `TRAVERSES_COMPONENT` for path pieces, the one exception to `<ACTION>_<OBJECT>`. Default every other
  relationship to a plain edge. *rulings George 2026-10-14 and 2026-11-20 (aws-build Q118/Q119); canon
  `req-grid-edge-compound` in `tap_grid/specs/spec-grid-edge.md`.*
- **Model the thing apart from where it lives.** A secret or key is its own node, separate from the file, process
  or cloud resource that holds it, so the grid can show where it lives and moves. A certificate is a file that
  holds a key, not a type. *ruling George 2026-10-14; the `secret` and `asymmetric_key` types are proposed, not
  built.*

### Identity and observation

- **Key identity on stable columns and record null for unobserved.** AGENTS.md items 4 and 5. Guard: the
  `NATURAL_KEY`-or-`KEYLESS` requirement. Audit: catalogue entries 10 and 11.
- **Runs: a run node, plus a `run_id` field on what the run mints.** A run (a scanner pass, an evaluation run)
  is its own node holding the run's information, with no edges to its results. Every node the run *mints*
  carries `run_id`: the run node's entity id, a plain indexed UUID field, written once and part of the
  `NATURAL_KEY`. It is not a foreign key, because there are none between typed node tables
  (`tap_grid/specs/spec-grid-service-delete.md`, "Cascade First"), and like core's batch pointers it is a plain id
  (`spec-grid-entity.md`, `req-grid-history-reobservation`). It is not a dimension either: dimensions gather
  diverse types from different plugins into one bucket, and a run's output sits in one or a few house tables.
  Nor is it an edge per result, because thousands of edges to one run node make a super-node. A persistent node
  that many runs re-observe never carries `run_id`. Re-stamping it would hide earlier runs in history or write
  a history row every run, so core's `last_observed_batch_id` answers which run last saw it. "Every run that
  saw X" comes from the per-run nodes keyed on (X, run). A one-value-per-row classifier within one table, such
  as an algorithm, is a key field too, not a dimension. The convention is canon in
  `tap_cares/specs/spec-tap-cares-run.md`. Once the tap_cares run helper (`open_run` and `RunMixin`) is built,
  plugins use it rather than building run nodes by hand; both are Proposed, so until then plugins follow the
  convention by hand. *owner ruling 2026-11-25 (regscale session, Q39).* Candidate: flag an edge type
  whose source is a run node and whose targets are minted per run, and a `run_id` written to a node that a later
  batch re-observes.

### Dimensions and tags

- **Use a tag only where the node type has a real tagging system.** AWS resources do; most others do not. Never
  invent a tagging system on a type that lacks one. Everything else is a dimension. *ruling George 2026-10-14.*
  Candidate: flag a `layout:*` or other tag on a type whose model has no `tags` field.
- **Membership and marking are dimensions.** What a view shows, what an inventory row belongs to, whether data is
  designed, observed or real are dimension values, not entity-type lists copied into queries. Dimensions are
  nodes (`tap_grid/specs/spec-grid-dimension.md`), so a new value needs its node in the dictionary bundle.
  *canon for dimension nodes; ruling George 2026-10-14 for view membership.*
- **Order and arrangement come from typed fields first.** If the model has a field that says it (a zone, a
  boolean, an enum), use the field; a tag or dimension carries an arrangement only when no field does. *canon
  AGENTS.md item 7; audit entry 4.*

### Bundles and mock data

- **Ship bundles exported from a grid, or commit the generator.** A committed bundle with no producer in the tree
  is a finding; a generator uses a keyed id registry, never position, and a test that regenerates it. *canon
  AGENTS.md item 10; audit entry 6.* Candidate.
- **IDs are real UUID7s.** A fabricated id is a real version-7 UUID; never hand-typed, and never keyed by name.
  *canon (`tap_grid/specs/spec-grift-seed-ids-real-uuid7.md`).* Candidate.
- **Designed data carries `dcom: design`** and is never presented as collected. The framing lives in the patter, not
  on the page. *canon `req-rampart-20x-playground-mock-inventory`; ruling George 2026-10-14 (no mock label on
  pages).*
- **A batch description is honest** about what produced it (captured snapshot, designed, collected).

---

## tap_viz — layouts and projections

Start with [`create-layout`](../../../tap_viz/skills/create-layout/SKILL.md); it configures the runtime and holds
the procedure. These are the guard rails around it.

### Placement and nesting

- **No node ids and no edge ids in a layout.** A layout selects by type, dimension or Gryphon relationship. The only
  ids allowed are permanent entity ids referenced as that entity (a layout or elevation reference in a bundle).
  *canon (audit entries 1–3); ruling George 2026-10-14.* Guard: audit. Candidate: grep for UUID literals in
  projection JavaScript.
- **Take containment from a Gryphon relationship.** `projectNested` accepts relationships as Gryphon patterns. A
  helper that walks `cy.edges()` and matches edge-type strings re-derives what a relationship already says.
  Accepted for now, to be baked into node and edge definitions later. *ruling George 2026-10-14; observed
  2026-10-14 in the playground landing layout.*
- **Do not state a relationship twice.** The same relation in a layout's relationships and again as a separate
  Search is two sources of truth. Accepted for now for the same reason. *observed 2026-10-14.*
- **Order by data, never by label.** Matching a name or label to decide order, grouping or behaviour is a bug when a
  typed field, dimension or tag carries the same fact. *canon audit entry 4.*
- **Role-to-position maps do not belong in layout code.** A constant mapping a role to a column or a type to an
  order is a hidden map; put the column and order on the nodes (dimension values for types without tags). *canon
  audit entry 1; observed 2026-10-14.*
- **Group by what the node says it is.** Zone copies are the same tier in different `availability_zone` values; do
  not group on a tag whose job is ordering. *observed 2026-10-14.*

### Runtimes

- **Use the tap_viz runtimes** (nested projection, stack, icon node, chrome, arrangements, align-distribute)
  rather than a copy. A general helper (walk descendants, move a subtree, stretch a box) goes into
  `tap_viz/static/tap_viz/js/runtime/`. *canon AGENTS.md items 2 and 8; audit entry 5.*
- **An icon node is the top-most representation of a thing** and is terminal: what it contains is not drawn.
  Stacks collapse identical things and show a count; the count must equal the number of members. *canon
  `spec-viz-icon-node`, `spec-viz-stack`.*
- **Type names in a layout are configuration; positions are not.** A list of entity types to render as icons is
  fine. A table of coordinates or ranks keyed by id or role is not.

---

## tap_web — tables, panels, pages

### Tables

- **One table is one Gryphon Search and one existing table panel.** The query lives on a Search entity, never as an
  inline string in a panel. *canon AGENTS.md item 11, audit entry 5.*
- **Every column is read from the grid.** A column is a field of the node, a property of a related node, or a value
  computed by a query. A value typed into a row for the table's sake is a gap in the model, not a column.
  *ruling George 2026-10-14.*
- **Derived values are computed, never stored.** Counts, sums, findings per row and the like are Gryphon aggregates
  (COUNT, MIN and MAX; SUM, AVG and UNION are not available and a SUM or AVG is refused by name) with the panel's
  JavaScript as the fallback. A derived value
  is not written onto an entity. *canon `spec-grid-gryphon-multihop-aggregation`; ruling George 2026-10-14.*
- **Several small tables beat one wide one.** Similar things share a table with the columns that apply to them;
  other things get their own, so no column is overloaded. *ruling George 2026-10-14.*
- **Do not copy a type-to-label map into each panel.** Names for entity types come from the type's registered name,
  or from one shared definition. *observed 2026-10-14 (the same map pasted into three panels).* Candidate: find
  identical `labels` maps across panels.
- **No column the types cannot fill.** If the model holds no such field, leave the column out and record the gap.
  *observed 2026-10-14.*

### Pages, text and charts

- **Page text never explains that the data is a mock.** Titles, descriptions that render, and header tooltips
  describe the thing, not the exercise. *ruling George 2026-10-14.* Candidate: grep rendered panel and page text
  for `mock`.
- **Build the page with `add-page`, `add-panel` and `design-page`.** A panel type used by more than one project
  belongs in `tap_web`, through a reviewed PR (AGENTS.md item 2).
- **Charts and stat cards are a platform capability first.** The chart panel (`chart`) and the Stat Cards panel
  (`stat-cards`) are in `tap_web`, configured as JSON from a Search; a chart is an ECharts option on the Panel
  node, with `series_by`, `hierarchy`, `types` and `color_map` for what a plain dataset cannot do. When a view
  needs a shared piece that does not exist, build it in `tap_web` before a page depends on it. *observed
  2026-10-14; `req-web-stdpanel-statcards`, `req-web-panels-chart-config`.*

---

## tap_cares — collectors, schedules, secrets

- **Write a collector only when the maintainer has asked, with the request on record.** Use `build-collector`; a
  collector that touches a sensitive system needs a sensitivity review and a live trial before it ships. *canon
  AGENTS.md item 9; observed 2026-10-14 (aws-core-tap#97 left the collector out for this reason).*
- **A collector scope is the plugin slug,** which survives a module rename.
- **Read secrets through `tap_cares`,** never by opening the file, and never show a value, a file's contents or a
  private-key fingerprint anywhere in a bundle or a page. *canon `spec-tap-cares-secrets`
  (`req-tap-cares-secrets-scope-3`).*

## tap_plugins — projects and plugins

- **A project is data.** Bundles, Searches, Pages, panel configs, dimensions, layout hints; Python only as a
  collector when asked; JavaScript only as a layout written through `create-layout`. A model class or a
  `migrations/` body in a project means it is declaring vocabulary that belongs in a vocabulary plugin. *canon
  AGENTS.md item 1; audit entry 17.*
- **`depends_on` names every plugin whose types the bundles seed,** with the note saying which. A boot record pins
  every plugin it installs by tag and peeled commit.
- **A gap goes to the owning plugin as an issue, then the project waits for the release.** Do not work around it in
  the project. *canon AGENTS.md item 2; ruling George (fabricate designed data from released types, fix plugin
  gaps as they are found).*
- **Do not use `fedramp_20x_ksi` types for findings for now;** use `compliance_core`, and call out the duplication
  between them. *ruling George 2026-10-14.*

## tap_boot — records

- **A record pins by tag and peeled SHA,** and its description says what is installed and what is deliberately
  absent. After a release bump, refresh the record's digest.

---

## Specs and process

- **Read the spec first and change it in the same change as the code.** AGENTS.md item 13.
- **A spec says what was read, what was run and what is designed.** Use provenance markers, name the method behind
  each claim, and mark every requirement Proposed until it is built. *canon AGENTS.md item 12.*
- **Cite a requirement, an issue or a PR, never a session.** A "ruled by" line or a private question number is not
  checkable by the next reader. When a ruling lands in a spec, cite the spec. *canon audit entry 14; observed
  2026-10-14.*
- **Ask before building beyond one small change.** For anything larger, propose, get the owner's word, then build.
- **Open a PR through the repository's process.** `open-a-pr` for tap; a plugin repository has no promote, so the
  owner of the change runs the guards and the lane themselves. A supporting thread never pushes.
- **Never hand-write a `Signed-off-by`.** The installed hook stamps it where it runs.
- **Report outcomes faithfully.** Say what was verified and how; a check that did not run is not a pass.

---

## Last step: review and propose changes to this skill

A task using this skill is not finished until this step is written. Re-read what you did and list:

1. **Rules you broke or nearly broke,** with the section and what stopped you, or what did not.
2. **Rules that were missing:** a lesson from this work that no section holds. Write it as a proposed rule with its
   module, its group, its authority marker (canon, ruling or observed), the evidence, and the enforcement it could
   have (guard, audit, candidate or none).
3. **Rules that were wrong, vague or contradicted by a spec:** the rule, the evidence and the corrected wording.
   Where a spec disagrees, the spec wins and this file is the bug.
4. **Rulings now in canon:** the rule and the spec that now holds it, so the ruling marker can become a canon
   citation.
5. **Guard candidates worth building:** the mechanical check, how it would detect the case, and the rule it would
   enforce.

Write these as a **proposed diff** to this file and give it to the owner. Do not apply it: the owner approves
changes to the catalogue of rules, so a skill that rewrote itself as it went would drift the way the work it
checks does.

## What this skill is deliberately not

Not a replacement for the AGENTS.md list, which stays the single copy of the shared defaults. Not an audit; for a
sweep of what already landed use [`tap-conformance-audit`](../tap-conformance-audit/SKILL.md). Not a gate: nothing
runs it automatically, and a rule marked *none* or *candidate* is enforced only by someone reading this.
