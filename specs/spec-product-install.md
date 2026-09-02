# Product Install Skill

## Philosophy

Samsite's install fetched one fixed target, so its entire configuration was a credential. A product
that pulls *your* system — git-serious observing your organization, zizmor auditing what it collected
— has a step samsite never needed: a bounded conversation that dials in **what to pull** and **what
to show**, whose answers must land somewhere durable. This spec defines the `install-product` skill,
the sub-skill of the create-product tree (tap#205, `plan/product-map.md`'s "adjacent sub-skills")
that takes an operator from a pointer to a running, configured, verified instance — with an AI
assistant driving, since anyone running these products has one.

Three rules shape it:

1. **Compose, do not duplicate.** Download is the bootstrap pointer (`req-boot-bootstrap-command`);
   host prep and the spawn are `/get-started`; credential gaps are `/provision-secrets` and the
   product's own minting skills (github_core's `create-github-app`); failures are
   `/diagnose-failed-session-spawn`. The install skill orchestrates those; it re-implements none
   of them. One path for everyone (`req-boot-app`): the maintainer installs the same way a stranger does.
2. **Dial-in answers are configuration, not conversation.** Every answer the operator gives becomes a
   durable, machine-legible artifact the instance reads — never a fact that lives only in the chat.
   Presentation answers become an operator-owned GRIFT bundle; collection scope rides the channel
   collectors actually read (the credential envelope today; the collector-configuration channel when
   tap#308 lands).
3. **The product declares its questions.** Which questions to ask is the product's knowledge, shipped
   beside its boot record as data the skill renders — not prose the skill improvises. The first
   product (git-serious) sets the pattern; the first question is fixed by decision.

Provenance: *decided* marks George's rulings of 2026-09-02; everything else is *documented* from the
specs cited.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Pointer To Running | One skill invocation takes an operator from a `--from` pointer to a healthy, populated instance with the URL in hand. |
| 2 | Dial In, Durably | The operator's choices about what to pull and what to show are written as configuration the instance reads and the operator can keep, edit and version. |
| 3 | Product-Agnostic Skill, Product-Owned Questions | One skill serves every product; each product ships its own record choices, secrets and dial-in questions as data. |
| 4 | The Failure Output Is The Setup Guide | Every gap (host, record, credential, dial-in) is named by the machinery that checks it, and the skill routes the operator from the gap to the fix. |
| 5 | Intent Is On The Grid | The first thing an operator says — what this instance is for — becomes the grid's foundational keystone, so every later human and agent reads the intent before the data. |
| 6 | The Friction Log Is The Deliverable | Every question asked, every failure and its fix, is recorded so a first outside install teaches us something (git-serious-tap#8). |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-product-install-skill | [The Install Skill](#the-install-skill) | Proposed | `tap/skills/install-product`; orchestrates existing skills; one path for everyone |
| req-product-install-records | [Records Offered From The Artifact](#records-offered-from-the-artifact) | Proposed | Reads `[[boot.records]]`, descriptions and `required_secrets` without booting; explicit default |
| req-product-install-keystone | [The Intent Keystone](#the-intent-keystone) | Proposed | Asked first; written as the oldest keystone with prose intent, structured context, its schema, and install provenance |
| req-product-install-dial-in | [The Dial-In Step](#the-dial-in-step) | Proposed | Product-declared question set; bounded batches; answers written as durable configuration |
| req-product-install-dial-in-home | [Where Answers Live](#where-answers-live) | Proposed | Presentation → operator-owned GRIFT bundle; scope → the collector's channel; never the shipped GRIFT |
| req-product-install-credentials | [Credential Hand-Off](#credential-hand-off) | Proposed | Preflight names the gap; provisioning and minting skills close it; no secret value ever in chat |
| req-product-install-verify | [Verify, Then Hand Over](#verify-then-hand-over) | Proposed | Healthy, preflight ok, collectors fired with counts, the dial-in visible on the landing page, URL + attach command |
| req-product-install-friction | [The Friction Log](#the-friction-log) | Proposed | Machine-readable + human-readable record of the install, opt-in to share |
| req-product-install-lights-out | [Lights-Out Install](#lights-out-install) | Backlog | No tap clone: one env var + published images, once `req-boot-bootstrap-command` lands |

### The Install Skill
----
RID: `req-product-install-skill`

Status: `Proposed`

`/install-product <pointer>` lives at `tap/skills/install-product/SKILL.md` (the create-product tree's
home for now, tap#205). It is **product-agnostic**: the pointer names the product (`git+https://…/git-serious-tap@vX#<record>`
or the same without `#<record>`), and everything product-specific is read from the artifact
(`req-product-install-records`, `req-product-install-dial-in`). It runs, in order: host readiness and
spawn (delegating to `/get-started`); record choice; dial-in; spawn with the pointer; credential
hand-off on preflight gaps; verification; hand-over. It never introduces a second install path — the
commands it runs are the ones the README prints for a human.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-skill-1 | One Invocation | Proposed | `/install-product <pointer>` on a prepared host reaches a healthy instance without the operator typing a command the skill did not print first. | |
| req-product-install-skill-2 | Composes, Does Not Copy | Proposed | The skill delegates host prep, provisioning and diagnosis to the existing skills by invocation; no step of theirs is restated in its body. | Skills reference by path (`req-tap-plugin-arch-skills-4`). |
| req-product-install-skill-3 | Product-Agnostic | Proposed | The same skill installs git-serious and zizmor with no product name in its body; every product-specific fact comes from the artifact. | |

### Records Offered From The Artifact
----
RID: `req-product-install-records`

Status: `Proposed`

Before anything boots, the skill fetches the artifact's manifest and in-package records (the stage-0
mechanism of `req-boot-bootstrap-stage0`, reading `[[boot.records]]` and `boot/*.boot.json`) and
presents the choice: each record's name, its `description`, what it installs, whether it fires
collectors, and what `required_secrets` it declares. A record with no secrets (zizmor's corpus record)
is presented as the zero-credential path. The product's declared default record
(`req-boot-bootstrap-default-record`) is offered first; a pointer that names a record skips the
choice.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-records-1 | Read Without Booting | Proposed | The record list, descriptions and `required_secrets` are shown before any container starts. | |
| req-product-install-records-2 | Zero-Credential Path Named | Proposed | A record whose `required_secrets` is empty is labelled as needing no credential; the operator can choose it first and upgrade later. | zizmor's corpus record is the first instance. |

### The Intent Keystone
----
RID: `req-product-install-keystone`

Status: `Proposed`

*Decided* (George, 2026-09-02): creating a keystone is part of the standard install. Before the
skill asks anything about the product, it asks the operator what this instance and its grid are
**for** — the intent — and explains what a keystone is and that every later human and agent will
read it first (`CLAUDE.md`'s instance-context convention; `spec-grid-keystone.md`). The answers
become the grid's **foundational keystone** (`req-grid-keystone-model`):

- `name` — the instance's name (the session label by default).
- `description` — the operator's intent in their own words, lightly edited with them: what this
  instance observes, who it is for, and what they hope to learn or decide from it. The
  guaranteed-readable entry (`req-grid-keystone-model`), so it must be prose, not a form.
- `context_json` — structured context chosen for install: `purpose` (the intent, one line),
  `subject` (the system observed — account or organization, repositories in scope), `audience`
  (who uses this instance), `environment` (personal / team / evaluation / production), `product`
  and `record` and `pointer` (what was installed, at what version, from where), `installed_at`,
  `installed_by` (`install-product` plus the operator's handle), and free `notes`.
- `context_schema_json` — the JSON Schema for that shape, with a `description` per property, so the
  context documents itself (`req-grid-keystone-self-describing`; validation fails loud on a mismatch,
  `req-grid-keystone-validation`).

**It must be the oldest keystone.** Read order is oldest-first by entity creation
(`req-grid-keystone-multiplicity`), and the operator's intent is the frame every later keystone
layers on. Products ship no keystone today; when one does, the operator's must still come first, so
the skill creates it **before population seeds any product bundle** — through the service layer once
the instance is migrated and authenticated, or as the first population step of a derived record — and
the implementation says which. Later dial-in answers may reference it; v0 defines no keystone edges
(`req-grid-keystone-edges`), so the link is by convention, not by edge.

The keystone is the one install artifact that is *not* configuration: nothing reads it to behave
differently. It exists so that the next person, or the next agent, attaching to this grid can answer
"what is this, what is it for, where did the data come from" without asking anyone.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-keystone-1 | Asked First | Proposed | The intent conversation is the first thing the skill asks, before the record choice's consequences and before any product question. | |
| req-product-install-keystone-2 | Foundational | Proposed | After install, `MATCH (k:keystone) RETURN k ORDER BY k.created_at ASC` returns the operator's intent keystone first, before any keystone a product bundle may seed. | The oldest read is the intent. |
| req-product-install-keystone-3 | Self-Describing And Valid | Proposed | The keystone's `context_json` validates against its `context_schema_json`, every property carries a `description`, and `description` is non-empty prose. | Fail loud on a mismatch. |
| req-product-install-keystone-4 | Provenance Recorded | Proposed | The context names the product, record, pointer and version installed, when, and by which skill and operator. | Where the data came from. |

### The Dial-In Step
----
RID: `req-product-install-dial-in`

Status: `Proposed`

The product ships a **question manifest** beside each record it applies to —
`tap_plugin/<slug>/boot/<record>.dial-in.json`, JSON-schema'd in core — declaring the questions the
skill asks, each with: a key, the prompt, the answer type (an entity of a named type on the grid, a
free string, a choice, a set of repositories), whether it is asked before or after first collection
(a workflow cannot be chosen before workflows exist), and **where the answer lands**
(`req-product-install-dial-in-home`). The skill asks in bounded batches (at most four per batch),
records each answer with its provenance, and never asks a question the manifest does not declare.

Batch zero is not the product's: it is the intent conversation of `req-product-install-keystone`,
asked before any product question. The product's question set then follows; its first question is
*decided* (George, 2026-09-02):

1. **Which workflow to highlight as the landing page graph.** Asked after first collection, answered
   as a `github_workflow` entity chosen from what was collected, landing as the landing page's search
   parameter in the operator's bundle.
2. Which account or organization, and all repositories or a named subset — collection scope, asked
   before first collection, landing on the collector's configuration channel.
3. Later, as products grow: how the landing visualization should look; which operational principles
   apply; a scanner's persona. Each arrives as a new entry in the product's question manifest, never
   as skill prose.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-dial-in-1 | Manifest-Driven | Proposed | Every question the skill asks corresponds to an entry in the product's question manifest, validated against the core schema. | The product declares; the skill renders. |
| req-product-install-dial-in-2 | Ordered By Data | Proposed | A question whose answer is an entity of a collected type is asked only after the collection that produces it has run. | The featured workflow needs workflows. |
| req-product-install-dial-in-3 | Bounded Batches | Proposed | No batch exceeds four questions; a product with more asks in ordered batches. | |

### Where Answers Live
----
RID: `req-product-install-dial-in-home`

Status: `Proposed`

Two homes, by what reads the answer:

- **Presentation answers** (the featured workflow, layout preferences) become an **operator-owned
  GRIFT bundle** — `<session>/boot/<record>.overrides.grift.json`, a batch with its own id and name
  (`<product> operator overrides v0.1.0`), seeded *after* the product's shipped bundles so its
  entities and edges override by upsert, and version-bumped when an answer changes
  (`req-tap-plugin-arch-iterative-dev`). The product's landing GRIFT takes the featured workflow as a
  page variable / search parameter; the bundle sets it. The operator can read, edit and keep the
  bundle — it is the "software as a sophisticated beanbag" promise made concrete — and the skill
  **never edits shipped GRIFT**, which the next release would overwrite.
- **Collection scope** (account, repositories) lands on the channel the collector reads: today the
  credential envelope's `data` (`owner`, `repos` — github_core's contract); when the
  collector-configuration channel lands (tap#308) the skill writes there instead and the envelope
  goes back to holding only the credential. The question manifest names the home, so the migration
  is a manifest change, not a skill change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-dial-in-home-1 | Overrides Bundle Seeded | Proposed | After dial-in, an operator-owned bundle exists with its own batch id, seeds after the product's bundles, and the landing page reflects the featured workflow. | |
| req-product-install-dial-in-home-2 | Shipped GRIFT Untouched | Proposed | No file under the installed plugin's `grift/` differs from the artifact after install. | |
| req-product-install-dial-in-home-3 | Scope Reaches The Collector | Proposed | The account and repository scope the operator chose is what the collector's next run reads. | Envelope today; tap#308's channel later. |

### Credential Hand-Off
----
RID: `req-product-install-credentials`

Status: `Proposed`

The skill does not know how to mint anything. When the boot preflight (`req-boot-obs-preflight`)
reports a missing or dead secret, the skill hands the exact gap — scope, key, kind, note — to
`/provision-secrets`, which routes to the kind's canonical docs and the product's minting skill
(github_core's `create-github-app` for the read-only App). The preflight is the verifier
(both lanes); the skill re-runs it, never a hand-rolled check. No secret value is ever printed,
echoed or pasted in the conversation; the operator places it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-credentials-1 | Gap From The Preflight | Proposed | The credential step starts from the preflight's `missing_secrets` entries, never from the skill's own guess. | |
| req-product-install-credentials-2 | Verified By The Preflight | Proposed | After placement, the offline and live lanes both read `ok` in the boot record before the skill proceeds. | |

### Verify, Then Hand Over
----
RID: `req-product-install-verify`

Status: `Proposed`

Install is done when the skill has *observed*, not assumed: the instance is healthy
(`manage.py health`), every preflight entry is `ok`, every fire-collector step reports counts in the
boot record, the operator's dial-in choice is visible on the landing page (the featured workflow
renders), and the operator has the URL, the credentials file location and the attach command. The
skill ends by pointing at `logs/boot/latest.boot-record.json` as the evidence.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-verify-1 | Observed, Not Assumed | Proposed | The skill's "done" reads health, preflight and collector counts from the boot record and the health command, and renders the landing page once (drive-browser or an HTTP fetch of the page variable) before declaring success. | Presence is not correctness. |
| req-product-install-verify-2 | Hand-Over Complete | Proposed | The final message carries the URL, the `.dev-credentials` path, the attach command, and the boot record path. | |

### The Friction Log
----
RID: `req-product-install-friction`

Status: `Proposed`

Every install writes `logs/install/<timestamp>.friction.json` (machine-readable: each question, each
answer's provenance, each failure with its diagnosis and fix, wall-clock per step) and a rendered
`friction.md` beside it. Sharing is opt-in: the skill offers to open an issue on the product repo
with the log attached, minus anything the secrets scanner flags. This is git-serious-tap#8's stated
deliverable — "the friction log is the deliverable" — and the input to the next round of the
question manifest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-friction-1 | Log Written | Proposed | After any install attempt, successful or not, both files exist and the JSON validates against its schema. | |
| req-product-install-friction-2 | Opt-In Share, Scanned | Proposed | The share step runs the secrets scanner over the log and refuses to attach a log with a finding. | |

### Lights-Out Install
----
RID: `req-product-install-lights-out`

Status: `Backlog`

The no-clone path: `TAP_BOOT_FROM=<pointer>` plus the published images stands an instance up with no
tap checkout (`req-boot-bootstrap-command-3`), and the dial-in runs against it over the API. Blocked
on `req-boot-bootstrap-command` (Proposed) and on a boot-record-less way to place the overrides
bundle. For the friends milestone the install starts with the tap clone; for everyone it must not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-product-install-lights-out-1 | No Clone | Backlog | An operator with Docker and one environment variable reaches a healthy, dialed-in instance without a tap checkout. | |

## Consumers

| Product | Records | First dial-in questions | Status |
| --- | --- | --- | --- |
| git-serious (`git-serious-tap`, git-serious-tap#8) | self / your-org | featured workflow; account + repository scope | First consumer; blocked on git-serious-tap#33 for the live record |
| zizmor (`zizmor-tap`, tap#302) | corpus (no credential) / live | persona (later); inherits git-serious's scope answers when installed with it | Second consumer; corpus record is the zero-credential proof |

## Non-goals

No new secrets mechanism (the envelope, the preflight and `/provision-secrets` stay the only path).
No editing of shipped GRIFT. Not a replacement for `/get-started` — it delegates to it. Not a
marketplace or update mechanism (records pin versions; "upgrade" is a new spawn from a new pointer).
