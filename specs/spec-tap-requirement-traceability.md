# Requirement Traceability — Implementation Ownership

## Philosophy

TAP's specifications and its code are already connected by `req-*` citations — thousands of them.
But those citations are **narrative, not ownership**. Measured across the tree: of 1,919 RID
mentions in `.py` files, 71% sit in docstrings and 28% in comments as explanatory
cross-references — *"related to req-X"* — and 1% in code identifiers. That is a many-to-many
explanatory relation, and it cannot answer the one question that matters for a single-source-of-
truth codebase:

> **Which function *is* the authoritative implementation of this requirement?**

`req-docs-rid-integrity` closed the first half of the gap: every citation now resolves to a
requirement that exists. This spec closes the second: a small, deliberate set of citations are
promoted from *mention* to **claim** — a `TAP-IMPLEMENTS` tag asserting that this function is where
a requirement's fact is derived, and that no other function may derive it.

The demand signal is concrete. A duplication audit found 18 instances of the same fact derived in
more than one place, six of them on security surfaces. Four carried a docstring in which the author
*admitted the copy while making it* — "Mirrors tap.settings", "identical contract to
tap.plugin_source_auth". Awareness was never the gap. The gap is that nothing made the ownership of
a fact structural, so a second derivation cost nothing to add and nothing pointed at its partner.

Three properties follow from that diagnosis, and they shape every requirement below:

- **A claim is scarce.** This is not a coverage program. The regulated-traceability field is
  unanimous that broad tracing decays into ceremony, and SQLite's corpus shows why: 60–90% coverage
  where a human deliberately targeted it, 0–20% everywhere else. TAP tags the requirements where a
  *canonical derivation* actually matters, and leaves the rest alone.
- **A claim can go stale, and must say so.** ASPICE 4.0 states the principle directly:
  *"Traceability alone, e.g., the existence of links, does not necessarily mean that the information
  is consistent."* A link that merely exists is the failure mode, not the goal.
- **A claim needs a consumer that visibly breaks.** Every durable tag convention in the wild — the
  kernel's `Fixes:`, Conventional Commits, Gerrit's `Change-Id`, SPDX — earned its accuracy from a
  consumer that broke or omitted when the tag was wrong. Inert tags rot. The consumer here is
  derived status (`spec-dev-validation.md`'s generated-Map discipline, pointed at the spec corpus).

## Definition of Done

**Every requirement in the tap + plugins corpus is either bi-directionally mapped or documented
excluded.** Mapped means it carries evidence — an implementation claim and/or a test-cited
acceptance criterion. Excluded means it carries a machine-readable disposition from a closed
vocabulary saying *why* no code mapping exists (`req-tap-traceability-disposition`). A
requirement whose own status declares it future work or withdrawn is accounted by that status
(the unbuilt and retired buckets) — until the moment it claims to be done, when the mapping or
exclusion falls due. Everything else is **Unaccounted** — a counted, ratcheting-to-zero gap
(`req-tap-traceability-accounting`), and that count is the project's progress bar.

This is a total *accounting* program, deliberately not a total *claims* program, and the two
principles compose rather than conflict: scarcity (`req-tap-traceability-scope`) governs **which
bucket** a requirement lands in — not everything deserves a claim, and most requirements will
resolve to a test citation or a documented exclusion — while the Definition of Done demands only
that every requirement **lands in exactly one bucket**. The field's evidence says the uncited
fraction of a requirements corpus is uninterpretable until the legitimately-code-free
requirements are marked (Doorstop `derived: true`, OpenFastTrace `Needs:`, clang's `na`); this
section is that marker's mandate.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Fact, One Derivation | A requirement's authoritative implementation is declared, machine-checked, and unique. |
| 2. | Scarce And Targeted | Claims are made where a canonical derivation matters, never as a coverage sweep. |
| 3. | Stale Claims Are Loud | A claim whose requirement changed underneath it fails, rather than reading as sound. |
| 4. | Declared Duplicates, Never Silent Ones | A second derivation is possible only as a documented, reviewed act. |
| 5. | Minted, Not Typed | The tag is emitted by a tool; hand-authoring an identifier is how conventions rot. |

## Prior Art

The traceability field has solved most of this, and TAP borrows deliberately rather than inventing.

**OpenFastTrace** supplies the defect vocabulary this spec adopts wholesale — `Duplicate`,
`Orphaned`, `Unwanted`, `Outdated`, `Predated` — and the insight that a link needs a *staleness
state*, not just existence. Notably it names copy-paste propagation twice in that vocabulary
("copy-paste error", "copy-paste error likely"), which is precisely the hazard a tag that travels
with copied code creates.

**SQLite** demonstrates content-hash staleness at scale: requirement identity *is* the hash of the
requirement text, so editing a requirement mechanically orphans every reference to it — 971 marks
in the shipped tree, zero drift. TAP takes the mechanism but not the identity model: readable slugs
are kept (ISO 26262 8-6.4.2.5 a's stable-identifier property, and 1,800+ existing citations depend
on them) and the hash moves into the *claim*. SQLite's affordability tricks are copied directly:
the tool emits the tag pre-hashed, and evidence from a single class is not treated as verification.

**StrictDoc** already models this exact semantic for Python — `@relation(REQ-1, scope=function,
role=Implementation)` — including the `role` field that distinguishes *this is THE implementation*
from *this merely relates*. Its docstring-over-comment choice for Python is independently the right
one here: `ast.get_docstring()` reads it without importing, while comments require `tokenize` and
share a line that other tools rewrite.

**LOBSTER** (BMW) contributes two rules adopted below: store the link once and derive the reverse
(duplicated links are how matrices rot), and make the escape hatch's payload a mandatory reason
rather than a bare flag.

**Rust's `// SAFETY:` + clippy** supplies the enforcement lessons: ship the inverse lint alongside
the lint (`unnecessary_safety_comment` shipped with `undocumented_unsafe_blocks`), and lint for
near-miss spellings, because a misspelled tag fails *open* — `// SAFTEY:` reports "no comment" and
the typo goes unnoticed. Roughly 60% of real-world failures in that ecosystem are shape, not
staleness.

**Within TAP**, this is the complement of `req-tap-known-dupes`: that convention declares a
duplicate that must exist; this one declares the original that must not be duplicated. They compose
directly — see `req-tap-traceability-uniqueness`.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-traceability-claim | [The Implementation Claim](#the-implementation-claim) | Implemented | `TAP-IMPLEMENTS:` in the docstring of the one function that derives a requirement's fact |
| req-tap-traceability-roles | [Role Vocabulary](#role-vocabulary) | Implemented | A closed set — a requirement is often realized at several layers, all legitimately |
| req-tap-traceability-uniqueness | [One Claim Per Role](#one-claim-per-role) | Implemented | Duplicate claims fail unless every site carries a `TAP-KNOWN-DUPE` group |
| req-tap-traceability-staleness | [Claims Detect Requirement Change](#claims-detect-requirement-change) | Implemented | Content hash of the requirement; a changed requirement orphans its claims |
| req-tap-traceability-code-staleness | [Claims Detect Code Change](#claims-detect-code-change) | Implemented | Content hash of the claimed scope's AST; a semantically edited scope orphans its claims — the code end of the link, fingerprinted like the spec end |
| req-tap-traceability-minting | [Minted, Not Typed](#minted-not-typed) | Implemented | `scripts/implements-tag` emits the complete pre-hashed line |
| req-tap-traceability-scope | [Scarce And Targeted](#scarce-and-targeted) | Implemented | Claims are opt-in per requirement; a missing claim is never, by itself, a defect — the disposition system accounts for the rest |
| req-tap-traceability-disposition | [Coverage Disposition](#coverage-disposition) | Implemented | A `Trace:` line beside `Status:` for requirements that legitimately map to no code — closed vocabulary, excluded from the content hash, contradicted by evidence |
| req-tap-traceability-accounting | [Full-Corpus Accounting](#full-corpus-accounting) | Implemented | Every requirement in exactly one bucket — mapped, excluded, doctrine, disputed, unbuilt, retired, or Unaccounted; Unaccounted is baselined and ratchets to zero, fail-closed for new requirements and for status flips to `Implemented` |
| req-tap-traceability-fragments | [Per-Spec Fragments](#per-spec-fragments) | Implemented | One generated file per spec; no committed aggregates — concurrent triage merges cleanly |
| req-tap-traceability-acid-floor | [Testability Floor](#testability-floor) | Implemented | A built requirement carries at least one acceptance criterion — zero-ACID canon is Verified-unreachable and strands its tests; debt baselined, shrink-only |
| req-tap-traceability-status | [Status Follows Evidence](#status-follows-evidence) | Implemented | A generated evidence report; `Verified` requires two independent evidence classes |
| req-tap-traceability-disputed | [The Disputed Status](#the-disputed-status) | Implemented | A fourth status bucket for spec-versus-implementation disagreement — claims are pointers, never resolution; every entry pairs with a review-ledger row |

---

### The Implementation Claim
----
RID: `req-tap-traceability-claim`

Status: `Implemented`

A **claim** is a tag in the docstring of the single function that is the authoritative derivation of
a requirement's fact:

```python
def grid_tables() -> set[str]:
    """Every table the grid owns.

    TAP-IMPLEMENTS: req-example-alpha@a3f9c1d2e5b7/0f9e8d7c6b5a (derivation) — the read backstop
        and the search-role grant both read this; neither may re-derive the set.
    """
```

Grammar: `TAP-IMPLEMENTS: <rid>@<spec-hash>/<code-hash> (<role>) — <reason>`. The claim
fingerprints **both ends of the link**: the requirement's text (`req-tap-traceability-staleness`)
and the claimed scope's code (`req-tap-traceability-code-staleness`), each verified together at
stamp time.

#### Implementation

- **Docstring, parsed from source.** `ast.get_docstring()` reads it without importing the module,
  which keeps the scanner pre-boot-safe. The claim is **never** read from `obj.__doc__` at runtime:
  `python -OO` discards docstrings, and `functools.wraps` copies them, so a wrapper would silently
  inherit its wrapped function's claim.
- **The token is namespaced.** `IMPLEMENTS` alone means *interface conformance* to every human and
  model trained on JSDoc, Java or TypeScript; every surveyed traceability tool kept a tool-specific
  token for exactly this reason. `TAP-IMPLEMENTS` also distinguishes a claim from the ~1,800
  pre-existing prose RID citations, which must never be mistaken for one.
- **Em-dash before the reason**, matching `TAP-KNOWN-DUPE`, `TAP-CRED-BIND` and `guard-allow`.
- **Near-misses fail closed.** A malformed variant — wrong case, `TAP-IMPLEMENT:`, a missing `@`,
  an unparseable role — is a *failure*, not a silently-ignored line. A tag convention whose typos
  fail open is a tag convention that quietly does nothing.
- The scanner's needle is assembled by string concatenation so the scanner module and its tests
  never match their own source (the `known_dupes.py` idiom).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-claim-1 | Claim grammar | Implemented | A claim is `TAP-IMPLEMENTS: <rid>@<spec-hash>/<code-hash> (<role>) — <reason>` in a function, class or module docstring. | The single-hash form is malformed — it fails closed, never parses as a claim without a code fingerprint. |
| req-tap-traceability-claim-2 | Parsed from source | Implemented | Claims are read via `ast.get_docstring()` from source, never from `__doc__` at runtime. | `-OO` and `functools.wraps` both corrupt the runtime reading. |
| req-tap-traceability-claim-3 | Near-misses fail closed | Implemented | A malformed claim fails the shape guard rather than being skipped. | ~60% of real-world tag failures are shape, not staleness. |

---

### Role Vocabulary
----
RID: `req-tap-traceability-roles`

Status: `Implemented`

A claim names a **role** from a closed vocabulary. Uniqueness is scoped per `(requirement, role)`,
because a requirement is frequently realized at more than one layer, all legitimately.

| Role | Means |
| --- | --- |
| `derivation` | The one place the requirement's *fact* is computed. The default and the common case. |
| `enforcement` | The guard, check or constraint that makes the requirement hold. |
| `surface` | The API, view or CLI through which the requirement is exposed. |

#### Implementation

- The vocabulary is **closed and validated**, following `TAP-CRED-BIND`'s provenance model: an
  unrecognized role fails rather than passing as free text.
- Scoping uniqueness to a role is a deliberate correction to strict single-claim uniqueness. In a
  layered architecture one requirement is often realized by a service function *and* a guard *and*
  an endpoint; a global one-claim rule would manufacture false failures and push legitimate cases
  into the duplicate escape hatch, corroding its meaning.
- OpenFastTrace and LOBSTER both assume *many* code sites per requirement; only StrictDoc's
  `role=Implementation` expresses "this is THE one." The role field is how that distinction is kept
  without over-constraining.
- Start narrow. Adding a role later is cheap; removing one after claims exist is not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-roles-1 | Closed vocabulary | Implemented | A claim's role is one of `derivation`, `enforcement`, `surface`; anything else fails. | Free-text roles cannot be reasoned about. |
| req-tap-traceability-roles-2 | Role scopes uniqueness | Implemented | Uniqueness is evaluated per `(requirement, role)`, not per requirement. | Prevents false failures in a layered architecture. |

---

### One Claim Per Role
----
RID: `req-tap-traceability-uniqueness`

Status: `Implemented`

**Two claims naming the same `(requirement, role)` is a defect** — that is the anti-pattern this
spec exists to make structural. It fails unless *every* site in the group also carries a
`TAP-KNOWN-DUPE(<group-id>)` tag.

#### Implementation

- The escape hatch is not new machinery: it is the existing `req-tap-known-dupes` convention, whose
  guard independently requires every group to have **≥2 code sites and ≥1 spec mention**. So a
  permitted duplicate derivation is, by composition, one that is *documented in a spec* — "duplicate
  with an explanation" comes free, and neither guard has to grow an escape vocabulary of its own.
- Uniqueness keys on `(module, rid, role)`, deduplicated **within** a module. Conditional
  definitions (`if sys.version_info >= …:`) otherwise manufacture false duplicates — a failure mode
  mypy's ignore-tracking has a decade of open issues about.
- **Copy-paste propagation is the hazard this targets.** A tag travels with the code it is attached
  to, so duplicating a tagged function duplicates its claim. Clippy's original safety-comment
  request anticipated exactly this and never implemented it; OpenFastTrace names it twice in its
  status vocabulary. A uniqueness check is the countermeasure, and it is the reason this guard is
  worth more than the referential-integrity one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-uniqueness-1 | Duplicate claims fail | Implemented | Two claims for one `(requirement, role)` in different modules fail the uniqueness guard. | The `Duplicate` defect. |
| req-tap-traceability-uniqueness-2 | Documented duplicates pass | Implemented | The failure clears when every site in the group carries a `TAP-KNOWN-DUPE(<group>)` tag, which is itself spec-documented. | Composition, not a second escape hatch. |
| req-tap-traceability-uniqueness-3 | Within-module dedup | Implemented | Multiple claims for one `(rid, role)` inside a single module are one claim, not a duplicate. | Conditional definitions. |

---

### Claims Detect Requirement Change
----
RID: `req-tap-traceability-staleness`

Status: `Implemented`

A claim carries a **content hash of the requirement it claims**. When the requirement's text
changes, every claim still carrying the old hash reports `Outdated` — the implementation must be
re-verified against the new text, then re-stamped.

#### Implementation

- The hash is `semantic_hash` (SHA-256, 12 hex) over the requirement's normalized body:
  whitespace-collapsed, with the `Status:` line, the `Trace:` line, and any **generated block**
  (`BEGIN/END GENERATED` markers) **excluded** — all three are machine-moved metadata on their own
  lifecycles, and hashing any of them would churn claims for changes with no requirement-meaning
  (status advances, bulk triage, and every `--sync-*` regeneration respectively; the last was
  found live 2026-08-21, when a sibling session's Map sync ceremonially drifted the Map claim).
- **SHA-256, never MD5.** SQLite's scheme uses MD5; TAP runs FIPS-mode default-ON, where
  `hashlib.md5()` raises `UnsupportedDigestmodError`. The house digest already exists and is
  FIPS-clean.
- The hash lives in the **claim**, not in the RID. Baking a revision into the identifier is
  OpenFastTrace's model and works when adopted from day one; TAP has 1,800+ citations and a spec
  corpus keyed on readable slugs, so the identifier stays stable and only claim sites carry the
  hash — of which there are few by construction.
- Re-stamping is one command (`req-tap-traceability-minting`). The friction is deliberately in the
  *review* — deciding whether the change invalidates the implementation — not in the mechanics.

**Named residual.** The hash covers the whole requirement body, so a typo fix or a reworded sentence
invalidates claims exactly as a semantic change does. That is the accepted cost of the aggressive
setting: precision over churn, chosen because everything is in version control and re-stamping is
cheap. If the churn proves worse than the signal, the narrower variant is to hash only the
acceptance-criteria table — meaning lives there, narrative does not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-staleness-1 | Changed requirement orphans claims | Implemented | Editing a requirement's body makes every claim carrying the prior hash report `Outdated`. | The ASPICE "existence is not consistency" principle. |
| req-tap-traceability-staleness-2 | Status and reflow do not churn | Implemented | A status change or pure whitespace reflow leaves the hash unchanged. | |
| req-tap-traceability-staleness-3 | FIPS-clean digest | Implemented | The hash is SHA-256 via `semantic_hash`; MD5 is never used. | `hashlib.md5()` raises under `TAP_FIPS=1`. |

---

### Claims Detect Code Change
----
RID: `req-tap-traceability-code-staleness`

Status: `Implemented`

A claim also carries a **content hash of the code it sits on**. When the claimed scope is
semantically edited, every claim still stamped with the old hash reports `Drifted` — the code must
be re-verified against the requirement, then re-stamped.

This is the inverse direction of `req-tap-traceability-staleness`, and without it the whole
convention has a blind side: rewrite a claimed function so it no longer does what the requirement
says, and every spec-side check stays green, because the spec never moved. The claim asserts "this
scope was verified against this text" — fingerprinting both ends is what makes that assertion
un-fakeable over time. Doorstop is the prior art: its links carry a SHA-256 of the linked item at
last review, and a changed item makes the link *suspect* until a human re-reviews and re-stamps.

#### Implementation

- **The digest is the callsite-identity recipe** (`req-tap-callsite-identity-discriminator`):
  `semantic_hash` over a positions-stripped `ast.dump` of the claimed scope — function, class or
  module, whatever owns the docstring. Formatting, comments and pure moves never churn the digest;
  any semantic edit does. `black` waves and file reorganizations cost nothing.
- **Every docstring in the subtree is excluded from the digest**, not just the claimed scope's own.
  The claim line lives *inside* a docstring, so hashing docstrings would make stamping the hash
  change the hash (a fixpoint problem — the mirror of excluding the `Status:` line from the spec
  hash), and a nested claim's re-stamp would cascade-churn every enclosing claim.
- **Minting emits a placeholder** (`------------`) in the code-hash position. The code hash can
  only be computed from the claim's *actual* placement, which the mint tool cannot know; the flow
  is paste, then `scripts/implements-tag --resync <path>`, which stamps the digest from where the
  claim really landed. An unstamped claim is well-formed but **fails this guard**, so the second
  step cannot be forgotten — placeholder-then-resync keeps "minted, not typed" honest without
  asking the author to hand-type a qualname.
- The guard is a hard lint, no baseline: a drifted claim is always actionable, and the fix is one
  command. `--check` reports the two states distinctly (`DRIFTED` vs `UNSTAMPED`) because the
  operator action differs in emphasis: one is a re-verification, the other an unfinished mint.

**Named residuals.** The hash detects edits **to the claimed scope only** — behavior drifting in a
callee, or the requirement violated elsewhere entirely, never touches the claimed AST and stays
green; the test-cited-ACID evidence class remains the behavioral check. Docstring-only edits do not
churn (documentation, not behavior — accepted). A *module*-level claim churns on any semantic edit
anywhere in the module; deliberate, and the same aggressive-precision bet as hashing the whole
requirement body: if the whole module is the derivation, any edit to it deserves the re-read, and
re-stamping is cheap.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-code-staleness-1 | Changed code orphans claims | Implemented | A semantic edit to a claimed scope makes every claim stamped with the prior code hash report `Drifted`. | The code end of the ASPICE "existence is not consistency" principle. |
| req-tap-traceability-code-staleness-2 | Cosmetic edits do not churn | Implemented | Formatting, comments, docstring edits and pure moves leave the code hash unchanged. | Positions-stripped AST, docstrings excluded. |
| req-tap-traceability-code-staleness-3 | Placeholder fails closed | Implemented | A claim carrying the mint placeholder parses but fails the code-staleness guard until `--resync` stamps it. | The forgettable second step, made unforgettable. |
| req-tap-traceability-code-staleness-4 | Re-stamp is self-stable | Implemented | Stamping or re-stamping a claim never changes the code hash being stamped. | Docstrings are outside the digest, so the write is a fixpoint. |

---

### Minted, Not Typed
----
RID: `req-tap-traceability-minting`

Status: `Implemented`

Trace: `non-python` — scripts/implements-tag

`scripts/implements-tag` emits the complete, pre-hashed claim line. **A claim is never hand-typed.**

#### Implementation

- The shape is `scripts/log-site-id`'s exactly: bash plus inline stdlib `python3`, anchored at the
  git toplevel, bare copy-pasteable output, a header naming its RID and spec.
- Modes: emit a claim for a RID and role (spec hash current, code hash as the mint placeholder —
  see `req-tap-traceability-code-staleness-3`); `--check` to list malformed, dangling, stale,
  drifted and unstamped claims; `--resync` to re-stamp both hashes after a reviewed spec or code
  change.
- Advertised in the **Developer token tools** block of both `CLAUDE.md` and `AGENTS.md`, alongside
  `scripts/uuid7` and `scripts/log-site-id`. This is not decoration: the AGENTS.md evaluation
  measured tools *named* in the context file being used 1.6 times per instance versus under 0.01
  when unnamed.
- The rationale is Gerrit's `Change-Id`, which essentially never rots and draws no complaints
  because a hook mints it — versus the kernel's hand-typed `Fixes:`, which a bot has been correcting
  daily since 2013.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-minting-1 | Tool emits the complete line | Implemented | `scripts/implements-tag <rid> [role]` prints a full claim with the current spec hash and the code-hash placeholder. | |
| req-tap-traceability-minting-2 | Re-stamp is one command | Implemented | `--resync` updates a claim's spec and code hashes after review — stale, drifted and unstamped alike. | Friction belongs in the review, not the mechanics. |
| req-tap-traceability-minting-3 | Advertised to agents | Implemented | The tool is listed in the developer-token-tools block of `CLAUDE.md` and `AGENTS.md`. | Named tools get used; unnamed ones do not. |

---

### Scarce And Targeted
----
RID: `req-tap-traceability-scope`

Status: `Implemented`

**Claims are opt-in per requirement. The absence of a claim is never, by itself, a defect.** This is
deliberately not a coverage program.

#### Implementation

- The initial target set is requirements that designate a **canonical derivation of a fact** —
  where a second implementation would be a real defect rather than a style question. The seed set is
  the collapses the duplication audit already proved: the grid-table classification, the
  secrets-root resolution, and the caller-context requirement. Tagging those locks in fixes that
  have already shipped.
- Security-surface, FIPS and service-boundary requirements are the natural next tranche.
- Rationale: SQLite's corpus measures 60–90% coverage on documents where a human deliberately built
  evidence, and 0–20% everywhere else — coverage does not accrete from ordinary work. A uniform
  thin layer is a worse position than a deep one where it matters. The regulated-traceability
  literature agrees from the other direction: mandated broad tracing is the thing that decays into
  ceremony, and assessors explicitly discourage tracing below the unit level.
- **The "needs no code" marker was deliberately deferred here** ("until a denominator exists there
  is nothing for it to correct") — and the deferral expired on 2026-08-20, when the Definition of
  Done declared the denominator to be the whole corpus. The marker is now specified as
  `req-tap-traceability-disposition`, and the denominator's accounting as
  `req-tap-traceability-accounting`. Scarcity survives the pivot intact: what those add is total
  *accounting*, never total *claiming* — a claim remains one valid disposition among several, and
  faulting a requirement for lacking one specifically remains wrong (`req-tap-traceability-scope-1`
  is unchanged). What becomes a defect, ratcheted rather than absolute, is a requirement with *no*
  disposition at all.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-scope-1 | Absence is not a defect | Implemented | No guard fails because a requirement lacks a claim. | Opt-in by construction; the accounting ratchet faults a missing *disposition*, never a missing claim specifically. |
| req-tap-traceability-scope-2 | Seed set is the proven collapses | Implemented | The first claims are placed on the single-source functions the duplication audit created. | Locks in already-shipped fixes. |

---

### Coverage Disposition
----
RID: `req-tap-traceability-disposition`

Status: `Implemented`

A requirement that legitimately maps to no code carries a **`Trace:` line beside `Status:`** in
its requirement block — on the line after `Status:`, separated by one blank line (the same blank
line that separates `RID:` from `Status:`), e.g. ``Trace: `non-python` — docker/entrypoint.sh``.
(Inline on purpose: the field regexes are line-anchored, so a block example whose lines begin
with `RID:` or `Trace:` parses as a requirement heading or a live marker — the former truncated
this section's ACID table once, before this sentence was written.)

Grammar: ``Trace: `<category>` — <target/reason>``. This is the field's "needs no code" marker
(Doorstop `derived: true`, OpenFastTrace per-item `Needs:`, clang's `na` / `na lib`), placed
spec-side so it travels with the requirement and is read by the one corpus parser.

#### The vocabulary

| Category | Means | Payload |
| --- | --- | --- |
| `process` | Governance or process — conformed to by humans and workflow, not code (DCO policy, release procedure, review rules). | Optional reason. |
| `narrative` | Goal-level or umbrella statement — the checkable substance lives in its ACIDs or child requirements, which carry their own dispositions. | Optional reason. |
| `non-python` | Implemented in a surface the claim scanner cannot read — shell, workflows, Dockerfiles, templates, GRIFT seed data. | **Mandatory**: the implementing file's repo-relative path. |
| `external` | Implemented outside this repo — an evicted plugin, org configuration, GitHub settings. | **Mandatory**: the repo, plugin slug, or system name. |

Four buckets are **derived, never hand-marked** — a `Trace:` line on any of them is a defect:
doctrine (`Status: In Force`), disputed (`Status: Disputed`), archival location, and **mapped**
(evidence exists). Marking what the system already knows would create two sources for one fact.

#### Implementation

- **The closed vocabulary fails closed** — an unknown category, or a missing mandatory payload, is
  a parse failure, not free text (the `TAP-CRED-BIND` provenance model, same as claim roles). A
  near-miss line (`Trace :`, `Traced:`) must fail loudly, not be skipped — the claim-shape lesson
  applies verbatim.
- **The `Trace:` line is excluded from the requirement content hash**, exactly as the `Status:`
  line is and for the same reason: it is metadata *about* the requirement on its own lifecycle.
  **Sequencing constraint, load-bearing:** this exclusion must land in the parser *before* any
  bulk marker application — otherwise adding dispositions across the corpus churns every existing
  claim's spec hash.
- **An excluded requirement cannot carry evidence.** A claim or test-cited ACID on a
  `Trace:`-marked requirement is a contradiction and fails — the `claimed_doctrine` lesson: a flag
  that only ever removes a check is a flag nobody maintains, so marking a requirement excluded
  must cost the ability to claim it. Resolving the contradiction means removing whichever side is
  wrong, and both edits are review-visible.
- **The two-line form** (tap#312): `RID:`, `Status:` and `Trace:` are each separated by ONE blank
  line. Every field regex is line-anchored, so the parser never cared — but Markdown joins
  adjacent lines into a paragraph, and an adjacent pair renders as `RID: req-example-thing Status: Proposed`
  on one line on GitHub and in every editor preview. The form is hash-neutral (`-2` above:
  `Status:`/`Trace:` are stripped before hashing), so applying it never orphans a claim.
  An adjacent pair is reported by the parser with file, line and RID through the same problem
  channel as a near-miss, and `scripts/spec-two-line-metadata` applies the form mechanically
  and idempotently — in core and, from a plain clone, in every evicted plugin repo's `specs/`.
- **The payload discipline is LOBSTER's**: where the category names a thing (the implementing
  file, the external system), naming it is mandatory — an exclusion whose target cannot be pointed
  at is an assertion nothing can check. `non-python` payloads are candidate promotion targets: if
  their count grows large, extending the claim grammar to `#`-comment surfaces is the follow-on
  (measured first, built only on demand).
- **Every category's payload is mandatory, and the reasons are published** (ruled 2026-08-23,
  raised by the PR #114 AI-review pass): an exclusion must explain itself where it stands, so
  `process` and `narrative` payloads — the why-not-code and the where-the-substance-lives — are
  as mandatory as the pointable ones. The generated **Exclusions Ledger** (in the Accounting
  Report below) republishes every excluded requirement's category and reason verbatim, with a
  per-RID flag for zero-ACID exempt entries — the audit surface answering "why does this
  requirement map to no code" without opening its spec. Practice preceded the rule: all 94
  markers already carried reasons when this became mandatory, so the ratchet cost nothing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-disposition-1 | Closed vocabulary, fail-closed | Implemented | A `Trace:` category outside the vocabulary, a near-miss spelling, or a missing mandatory payload fails the parse. | |
| req-tap-traceability-disposition-2 | Hash-neutral | Implemented | Adding, editing or removing a `Trace:` line leaves the requirement's content hash unchanged. | Must precede bulk triage. |
| req-tap-traceability-disposition-3 | Exclusion contradicts evidence | Implemented | A requirement carrying both a `Trace:` line and any evidence (claim or test-cited ACID) fails. | Marking excluded costs the ability to claim. |
| req-tap-traceability-disposition-4 | Derived buckets reject markers | Implemented | A `Trace:` line on a doctrine, disputed, or archival requirement fails. | One source per fact. |
| req-tap-traceability-disposition-5 | Reasons mandatory and published | Implemented | Every category requires a payload, and the generated Exclusions Ledger lists every excluded requirement's category and reason verbatim, flagging zero-ACID exempt entries per-RID. | Explainability surface; ruled 2026-08-23. |
| req-tap-traceability-disposition-6 | Two-line metadata layout | Implemented | A `Status:` line directly under `RID:`, or a `Trace:` line directly under `Status:`, is a parse problem reported with file, line and RID; the fields are separated by one blank line so Markdown renders each on its own line. | tap#312. Guard: `requirement-block-layout`; sweep: `scripts/spec-two-line-metadata`; hash-neutral by `-2`. |

---

### Full-Corpus Accounting
----
RID: `req-tap-traceability-accounting`

Status: `Implemented`

A generated accounting places **every requirement in the corpus in exactly one bucket** — mapped,
excluded (by category), doctrine, disputed, unbuilt, retired, or **Unaccounted** — and the
Unaccounted count is a baselined ratchet that trends to zero.

This is the Definition of Done made mechanical. The evidence report
(`req-tap-traceability-status`) deliberately lists only requirements that carry evidence; this
accounting is the complement, with a denominator. The two stay separate surfaces: one is read for
contradictions, the other for progress.

#### Implementation

- **The buckets are disjoint and total** by construction — the disposition rules
  (`req-tap-traceability-disposition`) already make evidence, exclusion, doctrine and disputed
  mutually exclusive, so bucketing is a derivation, never a judgment call.
- **Unbuilt and retired derive from status**, never from a marker: a requirement declaring itself
  future or in-flight work (`Proposed`, `Backlog`, `In Development`, `Approved for Development`,
  `Refactoring`) or withdrawn (`Deprecated`, `Deprecating`, `Retired`) has, by its own account,
  nothing settled to map — the status IS
  the documented disposition, and hand-marking it would create two sources for one fact. A
  `Trace:` marker on an unbuilt requirement stays legal (a process requirement carries its
  exclusion from birth, so its later status flip needs no triage); doctrine and disputed still
  reject markers.
- **The load-bearing consequence — done is where the DoD is enforced.** Flipping a requirement to
  `Implemented` without evidence or a `Trace:` exclusion moves it out of unbuilt and INTO
  Unaccounted, where the ratchet fails it as a new entry. Claiming done costs a mapping or a
  documented exclusion, mechanically, from the moment this landed.
- **A status outside every vocabulary lands in Unaccounted deliberately** (`Partial`, `Open`, a
  missing `Status:` line) — status drift is triage work, and the count is what surfaces it.
- **Unaccounted ratchets, fail-closed for new requirements**: the existing debt is grandfathered
  in a committed baseline (the referenced-RID pattern — 92→16 by batches), but a requirement
  *added* without a disposition fails immediately. The gap drains; it never grows.
- The headline is the Unaccounted count, per-spec sub-counts drive the triage batching, and the
  report says in as many words that a grandfathered entry is debt, not license.
- **The committed surface is per-spec fragments, never a monolithic report**
  (`req-tap-traceability-fragments`): the corpus-wide render with headline totals derives on
  demand (`guards --accounting`, the burndown dashboard) and is not committed anywhere.
- Plugins corpus: the same machinery ships in the core wheel and each plugin repo drains its own
  count against its own specs (the two-mains model). Sequenced after core proves the model.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-accounting-1 | Every requirement, one bucket | Implemented | The accounting assigns each corpus requirement exactly one of: mapped, excluded, doctrine, disputed, unbuilt, retired, Unaccounted. | Disjoint and total, derived not judged. |
| req-tap-traceability-accounting-4 | Done is enforced at the flip | Implemented | A requirement moving to `Implemented` with neither evidence nor a `Trace:` exclusion becomes a new Unaccounted entry and fails the ratchet. | The DoD as a standing gate, not a triage artifact. |
| req-tap-traceability-accounting-2 | Unaccounted ratchets to zero | Implemented | The Unaccounted set is baselined; an entry leaving the set cannot return, and a new requirement without a disposition fails. | Fail-closed for new, grandfathered for old. |
| req-tap-traceability-accounting-3 | Progress is visible | Implemented | Per-spec accounting is committed as drift-tested fragments (`specs/traceability/`); the corpus-wide table with sub-counts derives on demand (`guards --accounting`, the burndown dashboard). | The consumer that keeps triage honest; committed form per `req-tap-traceability-fragments`. |

---


### Per-Spec Fragments
----
RID: `req-tap-traceability-fragments`

Status: `Implemented`

The committed traceability artifacts are **per-spec fragments** — one generated file per spec
that defines requirements (a requirement-less spec, e.g. a template, renders nothing) at
`specs/traceability/<spec-stem>.md` carrying only that spec's facts: bucket counts, its payable
zero-ACID count, its Exclusions Ledger rows (reason verbatim), and its evidence rows. **No
aggregate totals are committed anywhere.**

Both facts exist to make concurrent triage mergeable (three generated-block conflicts in one day,
2026-08-24, all in the materialization while the per-requirement data merged cleanly every time):
disjoint specs → disjoint files → clean merges; a committed total is rewritten by every session
and is therefore a guaranteed same-line conflict between ANY two concurrent branches. A fragment
conflict means two sessions triaged the SAME spec — a true overlap git should surface. Corpus-wide
renders (headline totals, the full ledger and evidence tables) derive on demand: `guards
--accounting` / `--evidence` stdout, the Requirement Burndown Dashboard issue, and the drift
guard at check time.

#### Implementation

- `render_traceability_fragments` derives every fragment from the corpus in one pass; fragment
  filenames are the spec stem minus `spec-` and a name collision fails loudly (one-to-one, never
  two specs merged into one file).
- `sync_traceability_fragments` (behind `guards --sync-accounting` / `--sync-evidence`, one
  idempotent artifact under both historical flag names) writes only fragments whose content
  changed and removes orphans whose spec was deleted or renamed — a triage batch's diff touches
  only its own specs' files.
- `fragment_drift` is the enforcement: every rendered fragment committed byte-exact, no stale
  content, no orphans. The drift test reds the gate until the sync runs on the merged tree.
- The eventual grid representation supersedes this file layout entirely (requirements as nodes,
  reports as panels); the fragments are the transitional committed form, deliberately minimal —
  the parsed data model is the investment that transfers, not the file format.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-fragments-1 | One File Per Spec | Implemented | Every spec with requirements renders exactly one fragment; filename collisions fail loudly. | |
| req-tap-traceability-fragments-2 | No Committed Aggregates | Implemented | No spec surface or fragment carries the aggregate-render markers (machine-checked, BEGIN and END families, legacy included); headline numbers derive on demand only. Hand-authored markerless prose resembling an aggregate is review's domain, not machine detection's. | The guaranteed-conflict killer, scoped to what a machine can honestly enforce. |
| req-tap-traceability-fragments-3 | Minimal Sync | Implemented | The sync rewrites only changed fragments and removes orphans; untouched specs' files stay byte-identical. | |
| req-tap-traceability-fragments-4 | Fragment Drift Fails | Implemented | A stale, missing, or orphan fragment fails the drift test until re-synced on the merged tree. | |

### Testability Floor
----
RID: `req-tap-traceability-acid-floor`

Status: `Implemented`

**A requirement declared built carries at least one acceptance criterion.** A zero-ACID built
requirement is untestable by construction: markers cite ACIDs, so it has no attachment point for
test evidence — `Verified` is structurally unreachable for it, and the tests that already
exercise its behavior are stranded with nothing to cite.

#### Implementation

- Measured when this landed (2026-08-22): **166 of 536 built requirements (30%)** sat below the
  floor — whole specs authored prose-only (`spec-tap-cares-secrets` 18/18, `spec-grid-import-grift`
  14/14, most of `spec-fips`), an authoring-style split between spec generations rather than a
  decision. The gap also bends claims scarcity: for zero-ACID requirements a claim is the *only*
  mapping, so claims drift from "canonical derivations" toward "whatever could not be test-cited."
- **The ratchet** (`tap/guards/baselines/zero_acid_rids.txt`): grandfathered debt, shrink-only,
  fail-closed for a requirement newly declared built without an ACID — the Unaccounted
  discipline pointed at testability.
- **Backfill uses the tests as the distillation source**: a built requirement's existing tests
  name its testable criteria, so authoring the ACID table is the backwards test walk inverted
  (test → criterion → ACID row), not blank-page work. Adding a table churns the requirement's
  content hash — claimed requirements need a resync pass at the end of each backfill batch.
- The accounting report carries the zero-ACID count in its headline and a per-spec column, so
  the debt is visible where triage batches are picked.
- **Documented-excluded requirements are exempt** (ruled 2026-08-23). The floor exists to make
  `Verified` reachable; a requirement carrying a `Trace:` disposition has opted out of that game
  with a validated reason. A pytest marker can never cite a non-python, external, process, or
  narrative fact, so counting those requirements is unpayable noise that pads the baseline
  forever, not debt that drains. The exemption keys off the disposition's *presence* — the
  disposition-integrity guard already validates its honesty, so this is one derivation, not a
  second judgment. **Named deferral:** non-python code (the viz JavaScript runtime foremost)
  still deserves test evidence someday — a mechanism for citing ACIDs from non-pytest test
  surfaces (a JS harness, a shell-test convention) is future work, tracked here so the exemption
  is not mistaken for a decision that JS never gets tested. That JavaScript ain't gonna test
  itself.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-acid-floor-1 | Zero-ACID set ratchets to zero | Implemented | The zero-ACID built set is baselined; an entry leaving cannot return, and a requirement newly declared built without an ACID fails. | Fail-closed for new, grandfathered for old. |
| req-tap-traceability-acid-floor-2 | Debt is visible | Implemented | The accounting report carries the zero-ACID count in its headline and per-spec table. | Where batches are picked. |
| req-tap-traceability-acid-floor-3 | Excluded requirements exempt | Implemented | A requirement carrying a validated `Trace:` disposition is not counted by the zero-ACID measure; the floor applies only to requirements still playing for `Verified`. | Exemption keys off disposition presence; JS-testability deferral named above. |

---

### Status Follows Evidence
----
RID: `req-tap-traceability-status`

Status: `Implemented`

A generated report shows every requirement's **declared** status beside the status its
**evidence** supports. And one status is gated: **`Verified` requires two independent evidence
classes** — an implementation claim *and* at least one acceptance criterion cited by a test.

#### Implementation

- **Two evidence classes**, deliberately: a requirement evidenced only by its own implementation
  is not verified. The implementation is the thing under test, not a check on it. SQLite renders
  a requirement green only at 2+ independent classes for the same reason, and grades evidence
  across four of them.
- The committed consumer is the per-spec fragments' Evidence sections
  (`specs/traceability/<spec>.md`, synced by `manage.py guards --sync-evidence`), with the
  per-fragment drift test asserting each committed copy equals what the tree produces — the
  Validation Map's discipline, pointed at the requirement corpus; the corpus-wide report derives
  on demand (`guards --evidence`). **That drift test is what makes this a consumer rather than an
  optional dashboard**: every durable tag convention in the wild earned its accuracy from
  something that visibly breaks when the tag is wrong, and inert tags rot.
- It lists only requirements that *carry* evidence, plus the contradictions — not all ~1,100 rows.
  A report nobody can read is a report nobody reads.

**What is deliberately not gated.** A requirement declared `Implemented` with no evidence does
**not** fail. Claims are opt-in and scarce (`req-tap-traceability-scope`), so faulting their
absence would contradict the convention and turn a targeted tool into a coverage program. That
number is reported as context — how much of the corpus has been deliberately targeted — and the
report says so in as many words. Similarly, evidence on a requirement still declared `Proposed`
is surfaced but never failed: a requirement can be partly built, and doctrine requirements are
cited as guidance rather than implemented.

What *is* gated is the strongest assertion the vocabulary offers. `Verified` was unused across
the entire corpus when this landed — zero occurrences — so the gate starts at a zero baseline,
fails closed from day one, carries no debt, and makes the terminal state earnable for the first
time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-status-1 | Verified needs two classes | Implemented | A requirement declared `Verified` without both an implementation claim and a verified acceptance criterion fails. | Zero baseline; `Verified` was unused when this landed. |
| req-tap-traceability-status-2 | Report is generated and drift-tested | Implemented | Evidence rows are committed in the per-spec fragments by `manage.py guards --sync-evidence`, and the fragment drift test fails when any committed copy drifts. | The consumer that keeps the convention honest. |
| req-tap-traceability-status-3 | Missing claims are context, not defects | Implemented | No check fails because a requirement lacks a claim; the count is reported as targeting context. | Preserves `req-tap-traceability-scope-1`. |

---

### The Disputed Status
----
RID: `req-tap-traceability-disputed`

Status: `Implemented`

`Disputed` marks a requirement whose spec text and implementation **disagree**, where a human
has not yet ruled which is right. It is the state where "code exists" and "requirement
satisfied" have come apart — which is exactly why it fits none of the existing buckets, whose
shared function is to collapse those two questions into one.

#### Implementation

- **A fourth bucket, disjoint from built, unbuilt, and doctrine** (`DISPUTED_STATUSES` in
  `tap/spec_trace.py`). Each existing bucket's machinery is wrong for a dispute: the built
  bucket would blend a claimless dispute into awaiting-evidence debt and read a claimed one as
  satisfied; the unbuilt bucket treats attached evidence as an anomaly, when a dispute *should*
  carry a pointer to the contested code; the doctrine bucket rejects claims outright, erasing
  that pointer.
- **Claims are pointers, never resolution.** A claim on a `Disputed` requirement validates
  (unlike doctrine) and the report shows it — that is how a reader finds the disputing
  implementation — but no amount of evidence exits the status. The only exits are a human
  ruling that edits the **spec** (the content hash changes, every claim reports `Outdated`,
  the implementation is re-read against the new text) or the **code** (the re-stamp-after-review
  ceremony). Both exits force the re-read; the staleness machinery
  (`req-tap-traceability-staleness`) already implements the resolution workflow.
- **Every `Disputed` requirement pairs with a record**: a row in the requirement-review ledger
  (`docs/misc/doc-tap-requirement-review-ledger.md`) and a `Requirement Review Needed` section
  in the owning spec naming the code site and the disagreement. A dispute with no record is a
  label, not a dispute.
- The evidence report carries a dedicated `Disputed` section and a headline count. The count is
  the one number that matters for this bucket, and it should trend to zero. Statuses outside
  the four buckets are invisible to every derived count — for a status whose entire purpose is
  visibility, falling into the invisible pile is the failure mode this bucket exists to avoid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-disputed-1 | Own bucket, own count | Implemented | A `Disputed` requirement appears in none of the built/unbuilt/doctrine coverage counts; the report carries a dedicated section and headline count. | Visibility is the point. |
| req-tap-traceability-disputed-2 | Claims are pointers, never resolution | Implemented | A claim on a `Disputed` requirement validates and is listed, but no evidence exits the status — only a human ruling that edits spec or code does. | Both exits force a re-read via the staleness hash. |
| req-tap-traceability-disputed-3 | Ledger pairing | Implemented | Every `Disputed` requirement has a row in the requirement-review ledger and a section in the owning spec naming the code site and the disagreement. | The record is the dispute; process-checked in review, not guard-enforced yet. |

## Evidence (committed form: per-spec fragments)

Per-spec evidence rows live in the committed fragments at `specs/traceability/<spec>.md`
(synced by `manage.py guards --sync-evidence`); the corpus-wide report derives on demand via
`manage.py guards --evidence`. No aggregate is committed — a committed total is a guaranteed
merge conflict between any two concurrent triage branches (`req-tap-traceability-fragments`).

## Accounting (committed form: per-spec fragments)

Per-spec accounting rows and the Exclusions Ledger live in the committed fragments at
`specs/traceability/<spec>.md` (synced by `manage.py guards --sync-accounting`); the corpus-wide
report with headline totals derives on demand via `manage.py guards --accounting`, and the
Requirement Burndown Dashboard issue republishes it after each landing. No aggregate is
committed (`req-tap-traceability-fragments`).

## Relationship To Other Specs

- **`spec-docs.md`** (`req-docs-rid-integrity`) — the first half: every citation resolves. This spec
  promotes a chosen few of those citations from mention to claim, and reuses its parser
  (`tap.spec_trace`) and its reserved `req-example-*` placeholder namespace.
- **`spec-tap-known-dupes.md`** (`req-tap-known-dupes`) — the exact complement, and the escape hatch
  for `req-tap-traceability-uniqueness`. That convention declares a duplicate that must exist; this
  one declares an original that must not be duplicated.
- **`spec-dev-validation.md`** — the guards join the harness and the generated Validation Map; the
  derived-status report follows its generated-artifact-is-the-system-of-record pattern.
- **`spec-tap-testing.md`** (`req-tap-test-spec-linkage`) — the verification half. `@pytest.mark.spec`
  links a test to an acceptance criterion; a claim links a function to a requirement. Derived status
  needs both, and treats a requirement evidenced only by its own implementation as unverified.
- **`spec-sphinx-capability-docs.md`** (`req-sphinx-docs-capability-blocks`) — **superseded by this
  spec.** That requirement proposed a `:implements:` field inside Sphinx-Needs capability blocks; it
  was never built, and two docstring conventions for one relationship would be precisely the
  duplication this work exists to prevent.
- **`spec-tap-callsite-identity.md`** — the anchor/discriminator model the guards' baselines follow:
  keys are structural, never line numbers.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
