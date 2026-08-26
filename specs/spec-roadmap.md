# TAP Roadmap System

## Philosophy

Specs answer *what* the system does and *why*, at the engineering layer. They do not say *which* engineering work matters next, *when*, or *why this and not that*. That is a different layer — demand and intent — and until now it has lived in one ad hoc `strategy.md` file with no conventions, no stable references, and no way for an engineering/code thread to consume "the target" without reading the whole narrative.

This spec defines the roadmap system: a thin, demand-driven layer that sits *above* specs. It captures the progression of work, why that progression, the timeline, and the fence around each piece of work — in a form a human or an LLM thread can read and stay on target, because the target is written down.

The roadmap system is deliberately minimal. It exists to focus development (right now: the Sam demo) while keeping later targets visible, not to be a complete strategy taxonomy. Its shape emerges from satisfying a real demand signal, the same way every other part of TAP does. New structure is added only when a demand requires it; everything else is a named future seam, not built.

Markdown for all roadmap docs for now. The grid is the eventual home; we are not there yet, and pretending otherwise would be the exact overbuilding this system is meant to prevent.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Demand-Driven Shape | The roadmap layer grows only when a demand requires it. One `step` primitive, not a strat/tac hierarchy, until something concretely needs more. |
| 2. | Thread-Consumable | An engineering/code thread can read the roadmap — or a single step — and know the target, the timeline, and the fence, without loading the whole history. |
| 3. | Single-Source Timeline | One authoritative place per fact. The top-level timeline table mirrors per-step targets; there is never a second source of truth for a date. |
| 4. | One-Directional Linkage | Demand (step) → design (spec) → contract (req) references flow one way. The engineering layer never depends upward on the roadmap. |
| 5. | Canonical Then Mirrored | Conventions settle here first. AGENTS.md / memory mirror them only once proven through real use, not before. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-roadmap-location | [Roadmaps Live in `plan/`](#roadmaps-live-in-plan) | In Force | Top-level `plan/` dir; demand/intent layer above specs |
| req-roadmap-naming | [Roadmap and Step Naming](#roadmap-and-step-naming) | In Force | `road-` file prefix; `step-<roadmap>-<name>` referenceable ID |
| req-roadmap-primitive | [Single `step` Primitive](#single-step-primitive) | In Force | strat/tac split is a named future seam, not built |
| req-roadmap-structure | [Roadmap File Structure](#roadmap-file-structure) | In Force | Doctrine + step index + per-step blocks |
| req-roadmap-step-block | [Step Header Block](#step-header-block) | In Force | The four rail fields a thread reads to stay on target |
| req-roadmap-status | [Outcome Status Vocabulary](#outcome-status-vocabulary) | In Force | Steps judged by outcome, not by shipped output |
| req-roadmap-dates-in-tracker | [Dates Live in the Tracker](#dates-live-in-the-tracker) | In Force | Milestones are the single source of truth for when; the roadmap carries no dates |
| req-roadmap-linkage | [One-Directional Spec Linkage](#one-directional-spec-linkage) | In Force | Steps cite req/spec; specs never cite up |
| req-roadmap-consumability | [Thread Discoverability](#thread-discoverability) | In Force | CLAUDE.md / AGENTS.md navigation pointer |
| req-roadmap-doctrine | [Doctrine Ownership](#doctrine-ownership) | In Force | Lives in the single roadmap until a second one demands a split |

### Roadmaps Live in `plan/`
----
RID: `req-roadmap-location`
Status: `In Force`

All roadmaps live under a top-level `plan/` directory. The roadmap layer is the demand/intent layer that sits above the spec layer: a roadmap says which work matters, in what order, by when, and why; specs say how that work is designed.

This spec is cross-cutting (it governs a system that spans every app), so the spec itself lives at the repo-root `specs/` level, consistent with the spec file-location convention. The roadmap *content* it governs lives in `plan/`.

Markdown only for now. The grid is the eventual home and is captured as a future seam, not built.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-location-1 | Top-level plan/ exists | In Force | A `plan/` directory exists at the repo root. | |
| req-roadmap-location-2 | Demand layer separation | In Force | Roadmap content states which/when/why; it does not redefine spec-level how. | |

### Roadmap and Step Naming
----
RID: `req-roadmap-naming`
Status: `In Force`

- **Roadmap files:** `plan/road-<scope>.md` — kebab-case, `road-` **prefix** marks the file as a roadmap (e.g. `plan/road-products.md`). `road-` is a file prefix only, like `spec-`. It is **not** a referenceable ID; a roadmap is cited by filename.
- **Companion docs:** `plan/` may also hold non-roadmap demand-layer companions — e.g. the standing product / go-to-market map (`plan/product-map.md`): the stable *shape* (what we sell, to whom, how it's packaged) a roadmap references but that carries no steps or timeline of its own. Companions use plain descriptive names; the `road-` prefix is reserved for roadmaps.
- **Steps:** `step-<roadmap>-<name>` is the referenceable ID (e.g. `step-rampart-sam-demo`), the roadmap-layer analogue of a `req-` ID. The parent roadmap is embedded in the ID for free at-a-glance traceability, mirroring the `req-<app>-<spec>-<feature>` house style.

Moving a **tracked** file into `plan/` uses `git mv` so its history follows the rename — the docs system derives `last-edited`/`version` from `git log`, so a plain move would orphan that history. Moving an **untracked** file uses a plain `mv`: `git mv` fails on a file git does not track, and there is no history to preserve.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-naming-1 | Roadmap filenames follow pattern | In Force | Every **roadmap** file in `plan/` matches `road-<scope>.md`; `plan/` may also hold non-roadmap demand-layer companion docs (e.g. `product-map.md`). | |
| req-roadmap-naming-2 | Step IDs follow pattern | In Force | Every step ID matches `step-<roadmap>-<name>` and embeds its parent roadmap. | |

### Single `step` Primitive
----
RID: `req-roadmap-primitive`
Status: `In Force`

The roadmap layer has exactly one referenceable primitive: the **step**. A roadmap is an ordered collection of steps plus the narrative of why that progression.

An earlier draft of this system proposed a two-level strategy/tactic split (`strat-` / `tac-`). It was dropped because nothing yet demands it: the current demand is a single consumable progression toward the Sam demo. The two-level split is a **named future seam** — when a single step grows enough internal sub-actions that it needs its own file with its own sub-steps, that is the demand signal to introduce the second level. Until then it is not built.

Steps are ordered but may overlap; concurrency is expressed by the timeline table, not by step ordering.

#### Future

If/when the strat/tac split is demanded, it is introduced as a sub-step convention inside a step file, not as a parallel ID namespace, and this requirement is updated rather than a new system invented.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-primitive-1 | One primitive | In Force | The roadmap layer defines only `step`; no `strat-`/`tac-` IDs exist. | |
| req-roadmap-primitive-2 | Seam named not built | In Force | The two-level split is documented as a future seam with an explicit demand trigger. | |

### Roadmap File Structure
----
RID: `req-roadmap-structure`
Status: `In Force`

A roadmap file has three top-level parts, in order:

1. **Doctrine** — cross-cutting standing guidance: the strategic rule, priority order, red/green flags, and AI-thread instructions. This is the stable part a thread reads to know how to judge whether work is on-path. See [Doctrine Ownership](#doctrine-ownership) for why it currently lives here.
2. **Step index** — the quick-glance list of every step with its status. It carries **no dates**; see [Dates Live in the Tracker](#dates-live-in-the-tracker).
3. **Steps** — the per-step blocks, each with the header defined in [Step Header Block](#step-header-block) followed by as much narrative as the step needs.

The section boundary between Doctrine and the rest is kept clean enough that extracting Doctrine into its own meta-doc later is a single cut, not a rewrite.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-structure-1 | Three parts in order | In Force | A roadmap file contains Doctrine, then the step index, then Steps. | |

### Step Header Block
----
RID: `req-roadmap-step-block`
Status: `In Force`

Every step opens with a fixed header so a thread can read one step and know the fence without reading the rest of the roadmap:

```
### step-<roadmap>-<name>
Status: <Proposed | Active | Achieved | Abandoned | Superseded>
Tracking:    link to the milestone that carries this step's date
Objective:   one sentence — the outcome, not the activity
Done-Test:   the observable signal it worked (an outcome, never "delivered")
Non-Goals:   the fence — what this step explicitly refuses
```

The four rail fields a thread reads to stay on target are **Status, Tracking, Done-Test, Non-Goals**. `Objective` orients; `Done-Test` and `Non-Goals` are the guardrails that prevent scope sprawl and rabbit holes — this is the structural cure, moved one layer up, for the autonomy-sprawl failure mode (no definition-of-done + no scope fence ⇒ drift).

A step may optionally carry `Implements:` / `Depends-on:` lines per [One-Directional Spec Linkage](#one-directional-spec-linkage).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-step-block-1 | Header present | In Force | Every step carries Status, Tracking, Objective, Done-Test, Non-Goals. | |
| req-roadmap-step-block-2 | Done-Test is an outcome | In Force | Done-Test states an observable outcome, not "work completed" or "demo delivered". | |

### Outcome Status Vocabulary
----
RID: `req-roadmap-status`
Status: `In Force`

Steps use a format that parallels the spec status model but a vocabulary that does **not**: a step is judged by an outcome, not by whether work shipped, so engineering's `Implemented` / `Verified` terminal states are wrong here. The whole point of the layer is to refuse "we did the work" as a success state.

| Step States |  |
| --- | --- |
| Implemented | A step we are considering but have not committed to. |
| Active | Committed and being worked toward. |
| Achieved | The Done-Test outcome was observed. |
| Abandoned | Dropped on purpose; record why. |
| Superseded | Replaced by another step; link the successor. |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-status-1 | Outcome vocabulary used | In Force | Steps use the five step-states, not the engineering spec states. | |
| req-roadmap-status-2 | Terminal states recorded | In Force | Abandoned records a reason; Superseded links the successor step. | |

### Dates Live in the Tracker
----
RID: `req-roadmap-dates-in-tracker`
Status: `In Force`

**A milestone in the product repo is the single source of truth for when.** The roadmap carries no
dates — not in a step header, not in an index table.

This supersedes the original design, in which a per-step `Timeline Target` was authoritative and a
top-level Timeline Table mirrored it in the same edit. That arrangement was correct while markdown was
the only surface; once execution tracking moved to a tracker with real milestones, keeping dates in
both places made the roadmap a second, silently-decaying copy of a fact the tracker already owns. A
date that moves is a routine event; a document that has to be edited every time one moves will drift.

What the roadmap keeps is what a tracker cannot express: the **fence** — the outcome, the observable
Done-Test, and the explicit refusals — plus the ordering of steps and their outcome status. A step
points at its milestone with a `Tracking:` line; the milestone answers *when*, the step answers *what
counts as done*.

Ordering is not a date and stays here: steps are ordered but may overlap, and concurrency is expressed
by the work itself rather than by step sequence.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-dates-in-tracker-1 | No dates in the roadmap | In Force | No step header or index row carries a date or date-like target. | |
| req-roadmap-dates-in-tracker-2 | Every step points at its tracking | In Force | A step carries a `Tracking:` line naming its milestone, or states that no milestone exists yet. | |
| req-roadmap-dates-in-tracker-3 | Index carries status, not dates | In Force | The step index lists steps with status only. | |

### One-Directional Spec Linkage
----
RID: `req-roadmap-linkage`
Status: `In Force`

References flow one way: demand → design → contract. A step MAY cite the specs/requirements it depends on or triggers, via `Implements:` / `Depends-on:` lines listing `spec-`/`req-` references. Specs and requirements MUST NOT cite upward into steps.

This keeps the engineering layer independent and reusable and prevents circular drift, the same one-directional discipline as docs-derive-from-specs. It is also the eventual roadmap↔engineering connection: a forward-reference convention reserved now, with no linkage machinery built until drift is a real problem.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-linkage-1 | One-directional only | In Force | Steps may reference specs/reqs; no spec/req references a step ID. | |

### Thread Discoverability
----
RID: `req-roadmap-consumability`
Status: `In Force`

A roadmap that no thread's context loads is inert. The mechanism that makes it consumable is a navigation pointer in `CLAUDE.md` and `AGENTS.md`: the on-path authority is the relevant `plan/road-*.md`, and a thread reads the relevant step's fence (Objective / Done-Test / Non-Goals) before planning work.

The navigation pointer is a stable fact and is added when the first roadmap lands. The roadmap *format conventions* in this spec are **not** mirrored into AGENTS.md or memory until they are proven through real use (writing and using the first roadmap's steps). This spec is their canonical home; AGENTS.md/memory carry only the navigation pointer until the conventions settle — the spec-before-mirroring discipline.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-consumability-1 | Navigation pointer exists | In Force | CLAUDE.md and AGENTS.md point threads at `plan/road-*.md` as on-path authority. | |
| req-roadmap-consumability-2 | Conventions not prematurely mirrored | In Force | The format conventions live only here until proven, then mirror. | |

### Doctrine Ownership
----
RID: `req-roadmap-doctrine`
Status: `In Force`

Cross-cutting doctrine (strategic rule, priority order, red/green flags, AI-thread instructions) currently lives inside the single roadmap as its first section, because there is exactly one roadmap and one consumer — extracting a `plan/plan.md` meta-doc now would be the premature abstraction this system exists to prevent.

The named trigger to extract Doctrine into its own meta-doc: a **second roadmap** is created (`plan/road-<other>.md`), or an engineering thread needs the doctrine without a specific roadmap's content. Until a trigger fires, doctrine stays in place behind a clean section boundary so the future extraction is a single cut.

#### Future

When extracted, `plan/plan.md` becomes the roadmap-system meta-doc (the analogue of `spec.md` for specs), and this spec's structure requirement is updated to point Doctrine there.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-roadmap-doctrine-1 | Doctrine in roadmap for now | In Force | Doctrine lives in the single roadmap behind a clean section boundary. | |
| req-roadmap-doctrine-2 | Extraction trigger named | In Force | The condition that triggers a meta-doc split is written down. | |

## Trial Run

The first roadmap through this system is `plan/road-products.md`, created from the existing `strategy.md`. Sequencing (canonical-first, per the architecture rules):

1. This spec lands first as the meta-spec and is reviewed.
2. `plan/` is created; `git mv strategy.md plan/road-products.md`.
3. The file is restructured into Doctrine + Timeline Table + per-step blocks. The Sam step is rescoped per the fork-and-reproduce decision (clone Sam's repo into our own AWS account, boto3-simplified collector, static/edge topology — not VPC/subnet, not live prod credentials).
4. `CLAUDE.md` and `AGENTS.md` gain the navigation pointer.
5. Lessons from the trial fold back into this spec; requirements move `Proposed` → `Implemented` → `Verified` as the trial proves them.

### Outcome (executed 2026-05-17)

The trial ran the same session. `plan/road-products.md` now conforms; CLAUDE.md and AGENTS.md carry the navigation pointer. Requirements and acceptance criteria advanced `Proposed → Implemented` (applied and verifiable by inspection). `Verified` is intentionally not used: a doc convention has no automated test surface, so there is nothing to link a `@pytest.mark.spec` to — revisit only if a lint pass is later added, mirroring the "add only if drift becomes a real problem" stance in `spec-docs.md`.

Lessons folded back:

- **`req-roadmap-naming` git-mv rule is tracked-file-only — resolved.** `strategy.md` was never committed (untracked), so a plain `mv` was correct and lost no history; `git mv` would have failed. The requirement text was amended to state the conditional rule: tracked source → `git mv`; untracked source → plain `mv`.
- **"Current Working Milestone" was redundant and was dropped.** Once steps carry `Status: Active`, the Active step *is* the current milestone. Keeping a separate section would have created a second source of truth — the same principle now carried by `req-roadmap-dates-in-tracker`. Recorded so the pattern (status replaces prose-state) generalizes.
- **Pilot-partner scouting was folded into `step-rampart-first-paid-assessment`, not minted as its own step**, applying `req-roadmap-primitive`: no new primitive until it needs its own fence.

Open for the fresh-eyes pass: whether ACID rows should stay `Implemented` or drop back pending a future lint surface.

## Status Vocabulary

This spec's own requirements use the standard TAP spec states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.

Roadmap **steps** use the distinct outcome vocabulary defined in [Outcome Status Vocabulary](#outcome-status-vocabulary): `Proposed`, `Active`, `Achieved`, `Abandoned`, `Superseded`.
