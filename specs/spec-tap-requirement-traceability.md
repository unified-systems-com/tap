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
its requirement block — directly under the `Status:` line, e.g.
``Trace: `non-python` — docker/entrypoint.sh``.

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
- Plugins corpus: the same machinery ships in the core wheel and each plugin repo drains its own
  count against its own specs (the two-mains model). Sequenced after core proves the model.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-traceability-accounting-1 | Every requirement, one bucket | Implemented | The accounting assigns each corpus requirement exactly one of: mapped, excluded, doctrine, disputed, unbuilt, retired, Unaccounted. | Disjoint and total, derived not judged. |
| req-tap-traceability-accounting-4 | Done is enforced at the flip | Implemented | A requirement moving to `Implemented` with neither evidence nor a `Trace:` exclusion becomes a new Unaccounted entry and fails the ratchet. | The DoD as a standing gate, not a triage artifact. |
| req-tap-traceability-accounting-2 | Unaccounted ratchets to zero | Implemented | The Unaccounted set is baselined; an entry leaving the set cannot return, and a new requirement without a disposition fails. | Fail-closed for new, grandfathered for old. |
| req-tap-traceability-accounting-3 | Progress is visible | Implemented | The accounting is generated, committed, and drift-tested, with per-spec sub-counts. | The consumer that keeps triage honest. |

---

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
- The report is generated into this spec between `BEGIN/END GENERATED EVIDENCE` markers by
  `manage.py guards --sync-evidence`, with a drift test asserting the committed copy equals what
  the tree produces — the Validation Map's discipline, pointed at the requirement corpus. **That
  drift test is what makes this a consumer rather than an optional dashboard**: every durable tag
  convention in the wild earned its accuracy from something that visibly breaks when the tag is
  wrong, and inert tags rot.
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
| req-tap-traceability-status-2 | Report is generated and drift-tested | Implemented | The evidence report is regenerated by `manage.py guards --sync-evidence` and a test fails when the committed copy drifts. | The consumer that keeps the convention honest. |
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

## Evidence Report

Generated — do not hand-edit. Regenerate with `manage.py guards --sync-evidence`.

<!-- BEGIN GENERATED EVIDENCE — manage.py guards --sync-evidence -->

**1152** requirements · **20** standing doctrine · **0** disputed · **202** carry evidence · **11** carry both classes · **352** declared built with none.

Separate facts, deliberately not blended into one percentage. **Doctrine** is outside the coverage question — in force now, never "completed", expecting conformance rather than an implementation. **Disputed** marks a spec-versus-implementation disagreement awaiting a human ruling — its claims are pointers to the contested code, never resolution, and the count should trend to zero. **Declared built with none** is context, not a defect list: claims are opt-in and scarce by design (`req-tap-traceability-scope`), so it measures how much of the corpus has been deliberately targeted, not how much is wrong. Collapsing these into a single coverage score is what makes such a score meaningless.

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-boot-app` | Implemented | Implemented | `<module>`, `<module>` | — |
| `req-boot-bootstrap-pointer-grammar` | Proposed | Implemented | `parse_pointer` | — |
| `req-boot-bootstrap-record-version` | In Development | Implemented | `<module>` | — |
| `req-boot-phases` | Implemented | Implemented | `<module>` | — |
| `req-boot-profile` | Implemented | Implemented | `<module>` | — |
| `req-boot-required-secrets` | Implemented | Implemented | `<module>` | — |
| `req-boot-search-role` | Implemented | Implemented | `<module>` | — |
| `req-cicd-dco-signoff` | — | Tested | — | `req-cicd-dco-signoff-2`, `req-cicd-dco-signoff-3`, `req-cicd-dco-signoff-4` |
| `req-cicd-runner-least-privilege` | Implemented | Implemented | `<module>` | — |
| `req-cicd-sbom-10` | Implemented | Tested | — | `req-cicd-sbom-10-1`, `req-cicd-sbom-10-2`, `req-cicd-sbom-10-3` |
| `req-cicd-sbom-11` | Implemented | Tested | — | `req-cicd-sbom-11-1`, `req-cicd-sbom-11-2`, `req-cicd-sbom-11-3` |
| `req-cicd-sbom-12` | In Development | Tested | — | `req-cicd-sbom-12-1`, `req-cicd-sbom-12-2`, `req-cicd-sbom-12-3`, `req-cicd-sbom-12-4`, `req-cicd-sbom-12-5` |
| `req-cicd-sbom-13` | Implemented | Tested | — | `req-cicd-sbom-13-1`, `req-cicd-sbom-13-2` |
| `req-cicd-sbom-3` | Implemented | Tested | — | `req-cicd-sbom-3-1`, `req-cicd-sbom-3-2`, `req-cicd-sbom-3-3` |
| `req-cicd-sbom-7` | Implemented | Tested | — | `req-cicd-sbom-7-1`, `req-cicd-sbom-7-2`, `req-cicd-sbom-7-3`, `req-cicd-sbom-7-4` |
| `req-dev-validation-collection-complete` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-known-broken` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-map` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-mypy-ratchet` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-ratchet-harness` | Implemented | Verified | `<module>` | `req-dev-validation-ratchet-harness-5` |
| `req-dev-validation-real-backend` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-smoke-gate` | Implemented | Implemented | `<module>` | — |
| `req-docs-rid-integrity` | Implemented | Implemented | `<module>`, `<module>` | — |
| `req-fips-crypto-bom` | Implemented | Tested | — | `req-fips-crypto-bom-1`, `req-fips-crypto-bom-2` |
| `req-fips-crypto-bom-ci` | Implemented | Tested | — | `req-fips-crypto-bom-ci-1` |
| `req-fips-crypto-bom-conformance` | Implemented | Tested | — | `req-fips-crypto-bom-conformance-3` |
| `req-fips-crypto-bom-jvm` | Implemented | Tested | — | `req-fips-crypto-bom-jvm-1`, `req-fips-crypto-bom-jvm-2` |
| `req-fips-crypto-bom-source` | Implemented | Tested | — | `req-fips-crypto-bom-source-1`, `req-fips-crypto-bom-source-2`, `req-fips-crypto-bom-source-3` |
| `req-fips-crypto-bom-system-gate` | Implemented | Tested | — | `req-fips-crypto-bom-system-gate-2`, `req-fips-crypto-bom-system-gate-3` |
| `req-fips-crypto-bom-waivers` | Implemented | Tested | — | `req-fips-crypto-bom-waivers-1`, `req-fips-crypto-bom-waivers-2` |
| `req-grid-edge-schema-required` | Proposed | Implemented | `validate_edge_properties` | — |
| `req-grid-entity-base` | Implemented | Tested | — | `req-grid-entity-base-4` |
| `req-grid-entity-crud` | Implemented | Tested | — | `req-grid-entity-crud-2` |
| `req-grid-entity-internal` | Implemented | Tested | — | `req-grid-entity-internal-2` |
| `req-grid-entity-resolve` | Implemented | Tested | — | `req-grid-entity-resolve-2`, `req-grid-entity-resolve-3`, `req-grid-entity-resolve-4` |
| `req-grid-entity-spine` | Implemented | Tested | — | `req-grid-entity-spine-4` |
| `req-grid-entity-type` | Implemented | Tested | — | `req-grid-entity-type-2`, `req-grid-entity-type-3` |
| `req-grid-entity-validation` | Implemented | Tested | — | `req-grid-entity-validation-10`, `req-grid-entity-validation-11`, `req-grid-entity-validation-12`, `req-grid-entity-validation-14`, `req-grid-entity-validation-15`, `req-grid-entity-validation-6`, `req-grid-entity-validation-7`, `req-grid-entity-validation-8`, `req-grid-entity-validation-9` |
| `req-grid-gryphon-count` | Implemented | Implemented | `_compute_rows` | — |
| `req-grid-gryphon-limit` | Implemented | Tested | — | `req-grid-gryphon-limit-1`, `req-grid-gryphon-limit-2`, `req-grid-gryphon-limit-3` |
| `req-grid-gryphon-multihop` | Implemented | Implemented | `_build_chain_queryset` | — |
| `req-grid-gryphon-multihop-envelope` | Implemented | Implemented | `_build_chain_queryset` | — |
| `req-grid-gryphon-not-exists` | Implemented | Implemented | `_apply_not_exists` | — |
| `req-grid-gryphon-optional-match` | Implemented | Implemented | `_execute_optional_match` | — |
| `req-grid-gryphon-order-by` | Implemented | Implemented | `_resolve_order_cols` | — |
| `req-grid-gryphon-order-by-envelope` | Implemented | Implemented | `_apply_order_limit_typescan_envelope` | — |
| `req-grid-gryphon-rows` | Implemented | Implemented | `_compute_rows` | — |
| `req-grid-import-grift-batch` | Implemented | Implemented | `_execute_grift_batch` | — |
| `req-grid-import-grift-batch-scoped-sweep` | Implemented | Implemented | `_run_batch_scoped_sweep` | — |
| `req-grid-import-grift-dangling` | Implemented | Tested | — | `req-grid-import-grift-dangling-1` |
| `req-grid-import-grift-force-reimport` | Implemented | Tested | — | `req-grid-import-grift-force-reimport-1` |
| `req-grid-import-grift-identity` | Implemented | Tested | — | `req-grid-import-grift-identity-1`, `req-grid-import-grift-identity-2` |
| `req-grid-import-grift-preflight` | Implemented | Implemented | `_run_preflight` | — |
| `req-grid-import-grift-provenance` | Implemented | Tested | — | `req-grid-import-grift-provenance-1` |
| `req-grid-import-grift-removal-preflight` | Verified | Verified | `_validate_removal_section` | `req-grid-import-grift-removal-preflight-1` |
| `req-grid-import-grift-removals` | Implemented | Tested | — | `req-grid-import-grift-removals-1`, `req-grid-import-grift-removals-2` |
| `req-grid-import-grift-results` | Implemented | Implemented | `GriftImportResult` | — |
| `req-grid-import-grift-scope` | Implemented | Implemented | `<module>` | — |
| `req-grid-import-grift-sweep-purge` | Implemented | Implemented | `_apply_sweep_purge` | — |
| `req-grid-keystone-validation` | Implemented | Implemented | `Keystone.validate` | — |
| `req-grid-search-obj` | Implemented | Tested | — | `req-grid-search-obj-1`, `req-grid-search-obj-2`, `req-grid-search-obj-3`, `req-grid-search-obj-4`, `req-grid-search-obj-5`, `req-grid-search-obj-6`, `req-grid-search-obj-7`, `req-grid-search-obj-8`, `req-grid-search-obj-9` |
| `req-grid-search-orm` | Implemented | Tested | — | `req-grid-search-orm-2`, `req-grid-search-orm-3`, `req-grid-search-orm-4`, `req-grid-search-orm-8`, `req-grid-search-orm-9` |
| `req-grid-service-batch-all` | Implemented | Tested | — | `req-grid-service-batch-all-1` |
| `req-grid-service-batch-diag` | Implemented | Tested | — | `req-grid-service-batch-diag-1` |
| `req-grid-service-batch-dryrun` | Implemented | Tested | — | `req-grid-service-batch-dryrun-3` |
| `req-grid-service-batch-event` | Implemented | Tested | — | `req-grid-service-batch-event-2`, `req-grid-service-batch-event-6` |
| `req-grid-service-batch-infra` | Implemented | Tested | — | `req-grid-service-batch-infra-1` |
| `req-grid-service-batch-metadata` | Implemented | Tested | — | `req-grid-service-batch-metadata-3` |
| `req-grid-service-batch-model` | Implemented | Tested | — | `req-grid-service-batch-model-3` |
| `req-grid-service-batch-tx` | Implemented | Tested | — | `req-grid-service-batch-tx-1` |
| `req-grid-service-delete-baseline` | Implemented | Tested | — | `req-grid-service-delete-baseline-1`, `req-grid-service-delete-baseline-2`, `req-grid-service-delete-baseline-3` |
| `req-grid-service-delete-scope` | Implemented | Tested | — | `req-grid-service-delete-scope-2` |
| `req-grid-service-pipeline-context` | Implemented | Implemented | `require_caller_context` | — |
| `req-grid-service-purge` | Implemented | Tested | — | `req-grid-service-purge-1`, `req-grid-service-purge-2`, `req-grid-service-purge-3`, `req-grid-service-purge-4`, `req-grid-service-purge-6`, `req-grid-service-purge-7` |
| `req-grid-service-write-observation` | Implemented | Tested | — | `req-grid-service-write-observation-2` |
| `req-grid-service-write-occ` | Implemented | Tested | — | `req-grid-service-write-occ-2` |
| `req-grid-service-write-patch` | Implemented | Tested | — | `req-grid-service-write-patch-1`, `req-grid-service-write-patch-4` |
| `req-grid-service-write-payloads` | Implemented | Tested | — | `req-grid-service-write-payloads-2` |
| `req-grid-service-write-schema-cleanup` | Implemented | Tested | — | `req-grid-service-write-schema-cleanup-3` |
| `req-grid-service-write-surface` | Implemented | Tested | — | `req-grid-service-write-surface-1`, `req-grid-service-write-surface-3` |
| `req-grid-table-classification.sec` | Verified | Verified | `classified_models` | `req-grid-table-classification.sec-6` |
| `req-grid-traversal-exec-pipeline` | Implemented | Tested | — | `req-grid-traversal-exec-pipeline-4` |
| `req-grid-traversal-exec-row-materialization` | Implemented | Implemented | `materialize_rows` | — |
| `req-grid-traversal-exec-scope.sec` | Implemented | Tested | — | `req-grid-traversal-exec-scope.sec-3`, `req-grid-traversal-exec-scope.sec-4` |
| `req-grid-traversal-exec-sql-capture` | Implemented | Implemented | `explain_gryphon_raw` | — |
| `req-grid-traversal-lang-bare-match` | Implemented | Implemented | `_execute_bare_type_scan` | — |
| `req-grid-traversal-lang-combinators` | Implemented | Implemented | `_apply_predicate_to_qs` | — |
| `req-grid-traversal-lang-envelope-paths` | In Development | Implemented | `_resolve_orm_path` | — |
| `req-grid-traversal-lang-filters` | Implemented | Implemented | `_apply_predicate_to_qs` | — |
| `req-grid-traversal-lang-in` | Implemented | Implemented | `InComparison` | — |
| `req-grid-traversal-lang-is-null` | Implemented | Implemented | `IsNullComparison` | — |
| `req-grid-traversal-lang-observation` | Implemented | Implemented | `ObservationComparison` | — |
| `req-grid-traversal-lang-params` | Implemented | Implemented | `GryphonAST.required_params` | — |
| `req-grid-traversal-lang-patterns` | Implemented | Implemented | `_execute_type_scan` | — |
| `req-grid-traversal-lang-regex` | Implemented | Implemented | `_comparison_to_q` | — |
| `req-grid-traversal-lang-returns` | Implemented | Implemented | `_is_graph_envelope_return` | — |
| `req-grid-traversal-lang-shape` | Implemented | Tested | — | `req-grid-traversal-lang-shape-6` |
| `req-grid-traversal-lang-storage` | Implemented | Tested | — | `req-grid-traversal-lang-storage-3` |
| `req-grid-traversal-lang-string-match` | Implemented | Implemented | `_comparison_to_q` | — |
| `req-grift-envelope-validation` | In Development | Implemented | `parse_envelope_for_write` | — |
| `req-service-boundary-guard` | Proposed | Implemented | `<module>` | — |
| `req-tap-auth-passkey-dev-bootstrap` | Implemented | Tested | — | `req-tap-auth-passkey-dev-bootstrap-1`, `req-tap-auth-passkey-dev-bootstrap-10`, `req-tap-auth-passkey-dev-bootstrap-11`, `req-tap-auth-passkey-dev-bootstrap-13`, `req-tap-auth-passkey-dev-bootstrap-14`, `req-tap-auth-passkey-dev-bootstrap-15`, `req-tap-auth-passkey-dev-bootstrap-3`, `req-tap-auth-passkey-dev-bootstrap-4`, `req-tap-auth-passkey-dev-bootstrap-6`, `req-tap-auth-passkey-dev-bootstrap-7`, `req-tap-auth-passkey-dev-bootstrap-8`, `req-tap-auth-passkey-dev-bootstrap-9` |
| `req-tap-auth-passkey-enrollment` | Proposed | Tested | — | `req-tap-auth-passkey-enrollment-1`, `req-tap-auth-passkey-enrollment-2`, `req-tap-auth-passkey-enrollment-3`, `req-tap-auth-passkey-enrollment-6`, `req-tap-auth-passkey-enrollment-8` |
| `req-tap-auth-passkey-genesis` | Proposed | Tested | — | `req-tap-auth-passkey-genesis-3`, `req-tap-auth-passkey-genesis-4` |
| `req-tap-auth-passkey-rollout` | Proposed | Tested | — | `req-tap-auth-passkey-rollout-2` |
| `req-tap-auth-passkey-webauthn` | Proposed | Tested | — | `req-tap-auth-passkey-webauthn-10`, `req-tap-auth-passkey-webauthn-11`, `req-tap-auth-passkey-webauthn-13`, `req-tap-auth-passkey-webauthn-3`, `req-tap-auth-passkey-webauthn-7`, `req-tap-auth-passkey-webauthn-8` |
| `req-tap-cares-scheduler-cron` | Implemented | Implemented | `Schedule.validate` | — |
| `req-tap-cares-scheduler-fire-model` | Implemented | Implemented | `ScheduleFire` | — |
| `req-tap-cares-scheduler-model` | Implemented | Implemented | `Schedule` | — |
| `req-tap-cares-scheduler-tick` | Implemented | Implemented | `scheduler_tick` | — |
| `req-tap-cares-secrets-credential-patterns` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-files` | Verified | Verified | `<module>` | `req-tap-cares-secrets-files-1`, `req-tap-cares-secrets-files-2` |
| `req-tap-cares-secrets-leak-guard` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-redaction` | Verified | Verified | `<module>` | `req-tap-cares-secrets-redaction-1`, `req-tap-cares-secrets-redaction-2` |
| `req-tap-cares-secrets-registry` | Verified | Verified | `<module>` | `req-tap-cares-secrets-registry-1` |
| `req-tap-cares-secrets-resilient-load` | Verified | Verified | `<module>` | `req-tap-cares-secrets-resilient-load-1`, `req-tap-cares-secrets-resilient-load-2`, `req-tap-cares-secrets-resilient-load-3` |
| `req-tap-cares-secrets-root-resolution` | Verified | Verified | `resolve` | `req-tap-cares-secrets-root-resolution-1`, `req-tap-cares-secrets-root-resolution-2` |
| `req-tap-cares-secrets-rotation` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-shape` | Implemented | Tested | — | `req-tap-cares-secrets-shape-1`, `req-tap-cares-secrets-shape-2`, `req-tap-cares-secrets-shape-3`, `req-tap-cares-secrets-shape-4` |
| `req-tap-cares-secrets-size-guard` | Verified | Verified | `load_secret_envelope` | `req-tap-cares-secrets-size-guard-1` |
| `req-tap-cares-secrets-store-shape` | Implemented | Verified | `report_stray_store_files` | `req-tap-cares-secrets-store-shape-1`, `req-tap-cares-secrets-store-shape-2`, `req-tap-cares-secrets-store-shape-3` |
| `req-tap-health-bootcheck` | Implemented | Tested | — | `req-tap-health-bootcheck-1`, `req-tap-health-bootcheck-2`, `req-tap-health-bootcheck-3`, `req-tap-health-bootcheck-4` |
| `req-tap-health-exposure` | Implemented | Tested | — | `req-tap-health-exposure-2`, `req-tap-health-exposure-3` |
| `req-tap-health-probe-registry` | Implemented | Tested | — | `req-tap-health-probe-registry-1`, `req-tap-health-probe-registry-5`, `req-tap-health-probe-registry-6`, `req-tap-health-probe-registry-8` |
| `req-tap-health-probes` | Implemented | Tested | — | `req-tap-health-probes-3`, `req-tap-health-probes-7`, `req-tap-health-probes-8`, `req-tap-health-probes-9` |
| `req-tap-health-selection` | Implemented | Tested | — | `req-tap-health-selection-1`, `req-tap-health-selection-2`, `req-tap-health-selection-3`, `req-tap-health-selection-4`, `req-tap-health-selection-5` |
| `req-tap-health-service` | Implemented | Tested | — | `req-tap-health-service-3`, `req-tap-health-service-5` |
| `req-tap-json-discovery` | Implemented | Implemented | `discover_json_files` | — |
| `req-tap-json-loader` | Implemented | Implemented | `<module>` | — |
| `req-tap-json-naming` | Implemented | Implemented | `<module>` | — |
| `req-tap-json-scanner` | Implemented | Implemented | `scan_json_files` | — |
| `req-tap-known-dupes` | Implemented | Implemented | `<module>` | — |
| `req-tap-logging-config-location` | Proposed | Implemented | `build_logging_config` | — |
| `req-tap-plugin-arch-source-secret` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-load-v0-ready-chain` | Implemented | Tested | — | `req-tap-plugin-load-v0-ready-chain-1`, `req-tap-plugin-load-v0-ready-chain-2` |
| `req-tap-plugin-manifest-v0-edge-file` | Implemented | Implemented | `_load_edge_file` | — |
| `req-tap-plugin-manifest-v0-edges` | Implemented | Implemented | `_parse_edges` | — |
| `req-tap-plugin-manifest-v0-editors` | Implemented | Implemented | `_parse_editors` | — |
| `req-tap-plugin-manifest-v0-file` | Implemented | Implemented | `load_manifest` | — |
| `req-tap-plugin-manifest-v0-grift` | Implemented | Implemented | `_parse_grift` | — |
| `req-tap-plugin-manifest-v0-models` | Implemented | Implemented | `_parse_models` | — |
| `req-tap-plugin-manifest-v0-searches` | Implemented | Implemented | `_parse_searches` | — |
| `req-tap-plugin-manifest-v0-top` | Implemented | Implemented | `PluginManifest` | — |
| `req-tap-plugin-manifest-v0-validation` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-validate-cli` | Implemented | Implemented | `main` | — |
| `req-tap-plugin-validate-codepaths` | Implemented | Implemented | `_check_manifest_parse` | — |
| `req-tap-plugin-validate-compat` | Implemented | Implemented | `_check_requires_tap` | — |
| `req-tap-plugin-validate-deps` | Implemented | Implemented | `_check_declared_dependencies` | — |
| `req-tap-plugin-validate-exit` | Implemented | Implemented | `main` | — |
| `req-tap-plugin-validate-help` | Implemented | Implemented | `_build_parser` | — |
| `req-tap-plugin-validate-home` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-validate-identity` | Implemented | Implemented | `_check_identity_coherence` | — |
| `req-tap-plugin-validate-levels` | Implemented | Implemented | `validate_plugin` | — |
| `req-tap-plugin-validate-loads` | Implemented | Implemented | `_run_loads_checks` | — |
| `req-tap-plugin-validate-mgmt` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-validate-output` | Implemented | Implemented | `ValidationResult` | — |
| `req-tap-plugin-validate-runs` | Implemented | Implemented | `_run_runs_checks` | — |
| `req-tap-plugin-validate-schema` | Implemented | Implemented | `ValidationResult.to_json` | — |
| `req-tap-plugin-validate-scope` | Implemented | Implemented | `validate_plugin` | — |
| `req-tap-plugin-validate-strict` | Implemented | Implemented | `validate_plugin` | — |
| `req-tap-traceability-accounting` | Implemented | Implemented | `<module>`, `bucket_of`, `render_accounting_markdown` | — |
| `req-tap-traceability-acid-floor` | Implemented | Implemented | `<module>` | — |
| `req-tap-traceability-claim` | Implemented | Implemented | `<module>`, `collect_claims` | — |
| `req-tap-traceability-code-staleness` | Implemented | Implemented | `<module>`, `code_hash_of` | — |
| `req-tap-traceability-disposition` | Implemented | Implemented | `<module>`, `_parse_disposition` | — |
| `req-tap-traceability-disputed` | Implemented | Implemented | `disputed` | — |
| `req-tap-traceability-roles` | Implemented | Implemented | `<module>` | — |
| `req-tap-traceability-staleness` | Implemented | Implemented | `<module>`, `stale_claims` | — |
| `req-tap-traceability-status` | Implemented | Implemented | `<module>`, `collect_evidence`, `render_evidence_markdown` | — |
| `req-tap-traceability-uniqueness` | Implemented | Implemented | `<module>`, `duplicate_claim_groups` | — |
| `req-tap-tree-scanner-substrate` | Proposed | Implemented | `<module>` | — |
| `req-viz-arrangement-definition` | Implemented | Implemented | `Arrangement` | — |
| `req-viz-arrangement-layout-hotlink` | Implemented | Implemented | `Layout` | — |
| `req-viz-arrangement-model` | Implemented | Implemented | `Arrangement` | — |
| `req-viz-layout-artifact` | Implemented | Implemented | `Layout` | — |
| `req-viz-layout-dual-mode` | Implemented | Implemented | `Layout` | — |
| `req-viz-projection-artifact` | Implemented | Implemented | `Projection` | — |
| `req-viz-projection-entity-structure` | Implemented | Implemented | `Projection` | — |
| `req-web-nav-auto-parent` | Implemented | Implemented | `build_breadcrumb` | — |
| `req-web-nav-chrome-read-free` | Implemented | Implemented | `breadcrumb` | — |
| `req-web-nav-index-endpoint` | Implemented | Implemented | `nav_index_view` | — |
| `req-web-nav-page-discoverable` | Implemented | Implemented | `Page` | — |
| `req-web-nav-page-weight` | Implemented | Implemented | `Page` | — |
| `req-web-page-dim` | Implemented | Implemented | `<module>` | — |
| `req-web-panel-entity-resolution-config` | Implemented | Tested | — | `req-web-panel-entity-resolution-config-1`, `req-web-panel-entity-resolution-config-2`, `req-web-panel-entity-resolution-config-3` |
| `req-web-panel-entity-resolution-empty-state` | Implemented | Tested | — | `req-web-panel-entity-resolution-empty-state-1`, `req-web-panel-entity-resolution-empty-state-3` |
| `req-web-panel-entity-resolution-errors` | Implemented | Tested | — | `req-web-panel-entity-resolution-errors-1`, `req-web-panel-entity-resolution-errors-2` |
| `req-web-panel-entity-resolution-helper` | Implemented | Verified | `<module>` | `req-web-panel-entity-resolution-helper-2`, `req-web-panel-entity-resolution-helper-3`, `req-web-panel-entity-resolution-helper-4` |
| `req-web-panel-entity-resolution-multi` | Implemented | Tested | — | `req-web-panel-entity-resolution-multi-1` |
| `req-web-panel-entity-resolution-order` | Implemented | Tested | — | `req-web-panel-entity-resolution-order-1`, `req-web-panel-entity-resolution-order-2`, `req-web-panel-entity-resolution-order-3` |
| `req-web-panel-entity-resolution-result-shape` | Implemented | Implemented | `EntityResolution` | — |
| `req-web-panel-entity-resolution-template` | Implemented | Tested | — | `req-web-panel-entity-resolution-template-1`, `req-web-panel-entity-resolution-template-2`, `req-web-panel-entity-resolution-template-3` |
| `req-web-panel-entity-resolution-tests` | Implemented | Tested | — | `req-web-panel-entity-resolution-tests-2` |
| `req-web-panel-obj` | Implemented | Tested | — | `req-web-panel-obj-4` |
| `req-web-render-missingpan` | Implemented | Implemented | `_panel_error` | — |
| `req-web-render-panel` | Implemented | Implemented | `panel_view` | — |
| `req-web-render-panel-edit` | Implemented | Implemented | `panel_edit_view` | — |
| `req-web-render-process` | Implemented | Implemented | `_render_page` | — |
| `req-web-rendering-pagesan.sec` | Implemented | Implemented | `_render_page` | — |
| `req-web-rendering-panelsan.sec` | Implemented | Implemented | `panel_view` | — |
| `req-web-rendering-resolution` | Implemented | Implemented | `page_view` | — |
| `req-web-rendering-slashpage` | Implemented | Implemented | `landing_view` | — |

**Disputed** — the spec and the implementation disagree; each entry pairs with a row in the requirement-review ledger and a section in its owning spec (`req-tap-traceability-disputed`):

None.

**Declared unbuilt, but evidence exists** — reported, never failed; a requirement can be partly built, and a doctrine requirement is cited as guidance:

| Requirement | Declared | Derived |
| --- | --- | --- |
| `req-boot-bootstrap-pointer-grammar` | Proposed | Implemented |
| `req-boot-bootstrap-record-version` | In Development | Implemented |
| `req-cicd-sbom-12` | In Development | Tested |
| `req-grid-edge-schema-required` | Proposed | Implemented |
| `req-grid-traversal-lang-envelope-paths` | In Development | Implemented |
| `req-grift-envelope-validation` | In Development | Implemented |
| `req-service-boundary-guard` | Proposed | Implemented |
| `req-tap-auth-passkey-enrollment` | Proposed | Tested |
| `req-tap-auth-passkey-genesis` | Proposed | Tested |
| `req-tap-auth-passkey-rollout` | Proposed | Tested |
| `req-tap-auth-passkey-webauthn` | Proposed | Tested |
| `req-tap-logging-config-location` | Proposed | Implemented |
| `req-tap-tree-scanner-substrate` | Proposed | Implemented |

**Declared `Verified` without two evidence classes** — this one fails (`req-tap-traceability-status`):

None.

<!-- END GENERATED EVIDENCE -->

## Accounting Report

Generated — do not hand-edit. Regenerate with `manage.py guards --sync-accounting`.

<!-- BEGIN GENERATED ACCOUNTING — manage.py guards --sync-accounting -->

**1152** requirements · **202** mapped · **94** excluded (external 13, narrative 6, non-python 63, process 12) · **20** doctrine · **0** disputed · **561** unbuilt · **16** retired · **259 Unaccounted** · **96** built with zero ACIDs (payable — the floor ratchet's measure) · **46** zero-ACID among the excluded (exempt per `req-tap-traceability-acid-floor-3`; unpayable until a non-pytest evidence mechanism exists — flagged per-RID in the Exclusions Ledger below).

The Unaccounted count is the Definition of Done's progress bar: it only moves down (the committed baseline grandfathers existing debt; a new requirement without a disposition fails immediately). A grandfathered entry is debt, not license — every Unaccounted requirement still needs a mapping or a documented exclusion. **Unbuilt** and **retired** derive from status — a requirement declaring itself future work or withdrawn has, by its own account, nothing to map; the moment one flips to `Implemented` without evidence or an exclusion it becomes a NEW Unaccounted entry and the ratchet fails, so claiming done is where the Definition of Done is enforced.

| Spec | Reqs | Mapped | Excluded | Doctrine | Disputed | Unbuilt | Retired | Unaccounted | 0-ACID (payable) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tap_plugins/specs/spec-tap-plugin-architecture.md` | 27 | 1 | 0 | 0 | 0 | 14 | 0 | 12 | 0 |
| `specs/spec-tap-boot-v0.md` | 22 | 5 | 1 | 0 | 0 | 8 | 0 | 8 | 0 |
| `tap_auth/specs/spec-tap-auth-v0.md` | 20 | 0 | 0 | 0 | 0 | 12 | 0 | 8 | 0 |
| `tap_grid/specs/spec-grift-v0.md` | 11 | 0 | 0 | 0 | 0 | 2 | 1 | 8 | 8 |
| `tap_cares/specs/spec-tap-cares-scheduler.md` | 12 | 4 | 0 | 0 | 0 | 1 | 0 | 7 | 11 |
| `tap_cares/specs/spec-tap-cares-task-backend.md` | 11 | 0 | 3 | 0 | 0 | 1 | 0 | 7 | 7 |
| `tap_grid/specs/spec-grid-edge.md` | 9 | 1 | 0 | 0 | 0 | 1 | 0 | 7 | 2 |
| `tap_grid/specs/spec-grift-subgraph.md` | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| `tap_viz/specs/spec-viz-align-distribute.md` | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| `tap_web/specs/spec-web-batch-viewer-v0.md` | 8 | 0 | 0 | 0 | 0 | 1 | 0 | 7 | 5 |
| `tap_web/specs/spec-web-page.md` | 12 | 1 | 0 | 0 | 0 | 4 | 0 | 7 | 0 |
| `tap_web/specs/spec-web-viewer.md` | 8 | 0 | 0 | 0 | 0 | 1 | 0 | 7 | 0 |
| `specs/spec-dev-multisession-diagnose.md` | 7 | 0 | 0 | 0 | 0 | 1 | 0 | 6 | 0 |
| `tap_grid/specs/spec-grid-registry.md` | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 3 |
| `tap_viz/specs/spec-viz-status-badge-info.md` | 7 | 0 | 0 | 0 | 0 | 1 | 0 | 6 | 6 |
| `tap_cares/specs/spec-tap-cares-collector.md` | 20 | 0 | 0 | 0 | 0 | 15 | 0 | 5 | 5 |
| `tap_grid/specs/spec-grid-flip.md` | 6 | 0 | 0 | 0 | 0 | 1 | 0 | 5 | 0 |
| `tap_grid/specs/spec-grid-hotlink.md` | 6 | 0 | 0 | 0 | 0 | 1 | 0 | 5 | 0 |
| `tap_grid/specs/spec-grid-keystone.md` | 7 | 1 | 0 | 0 | 0 | 1 | 0 | 5 | 6 |
| `tap_grid/specs/spec-grid-search.md` | 9 | 2 | 0 | 0 | 0 | 2 | 0 | 5 | 0 |
| `tap_grid/specs/spec-grid-traversal-language.md` | 20 | 14 | 0 | 0 | 0 | 1 | 0 | 5 | 3 |
| `tap_viz/specs/spec-viz-badges.md` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 1 |
| `tap_viz/specs/spec-viz-elevation.md` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 2 |
| `tap_viz/specs/spec-viz-panel.md` | 14 | 0 | 0 | 1 | 0 | 6 | 2 | 5 | 0 |
| `tap_web/specs/spec-web-editor.md` | 9 | 0 | 0 | 0 | 0 | 4 | 0 | 5 | 0 |
| `tap_web/specs/spec-web-panel-sequence-navigation-v0.md` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 |
| `tap_web/specs/spec-web-tailwind-pipeline.md` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 |
| `tap_web/specs/spec-web-time-display.md` | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 |
| `specs/spec-tap-boot-observability.md` | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| `tap_grid/specs/spec-grid-icon.md` | 5 | 0 | 0 | 0 | 0 | 1 | 0 | 4 | 0 |
| `tap_grid/specs/spec-grid-node.md` | 5 | 0 | 0 | 0 | 0 | 1 | 0 | 4 | 1 |
| `tap_web/specs/spec-web-panels-chart.md` | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| `specs/spec-dev-playwright-refresh.md` | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `specs/spec-dev-plugin-workspace.md` | 7 | 0 | 0 | 0 | 0 | 4 | 0 | 3 | 0 |
| `tap_grid/specs/spec-grid-dimension.md` | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 |
| `tap_grid/specs/spec-grid-service-delete.md` | 7 | 3 | 0 | 0 | 0 | 1 | 0 | 3 | 0 |
| `tap_grid/specs/spec-grid-service-errors.md` | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `tap_grid/specs/spec-grid-service-read.md` | 4 | 0 | 0 | 0 | 0 | 1 | 0 | 3 | 0 |
| `tap_grid/specs/spec-grid-service-write.md` | 10 | 6 | 0 | 0 | 0 | 1 | 0 | 3 | 0 |
| `tap_grid/specs/spec-grid-service.md` | 9 | 1 | 0 | 0 | 0 | 5 | 0 | 3 | 0 |
| `tap_plugins/specs/spec-tap-plugin-type-ownership-v0.md` | 10 | 0 | 0 | 0 | 0 | 7 | 0 | 3 | 0 |
| `tap_web/specs/spec-web-panel-security.md` | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `tap_web/specs/spec-web-panels-standard.md` | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `specs/spec-dev-multisession-teardown.md` | 3 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 0 |
| `specs/spec-rampart-demo-anwar.md` | 9 | 0 | 0 | 0 | 0 | 7 | 0 | 2 | 0 |
| `specs/spec-tap-json-files.md` | 7 | 4 | 0 | 0 | 0 | 1 | 0 | 2 | 0 |
| `specs/spec-tap-testing.md` | 9 | 0 | 0 | 0 | 0 | 7 | 0 | 2 | 0 |
| `tap_cares/specs/spec-tap-cares-secrets.md` | 22 | 11 | 6 | 0 | 0 | 3 | 0 | 2 | 4 |
| `tap_grid/specs/spec-grid-entity.md` | 16 | 7 | 0 | 0 | 0 | 6 | 1 | 2 | 0 |
| `tap_grid/specs/spec-grid-import-grift.md` | 17 | 12 | 0 | 0 | 0 | 3 | 0 | 2 | 4 |
| `tap_grid/specs/spec-grid-security.md` | 7 | 1 | 0 | 0 | 0 | 4 | 0 | 2 | 0 |
| `tap_grid/specs/spec-grid-service-batch.md` | 11 | 8 | 0 | 0 | 0 | 1 | 0 | 2 | 0 |
| `tap_grid/specs/spec-grid-traversal-execution.md` | 10 | 4 | 0 | 0 | 0 | 4 | 0 | 2 | 0 |
| `tap_web/specs/spec-web-panel.md` | 6 | 1 | 0 | 0 | 0 | 3 | 0 | 2 | 2 |
| `specs/spec-cicd-hardening.md` | 14 | 2 | 7 | 0 | 0 | 4 | 0 | 1 | 0 |
| `specs/spec-dev-multisession.md` | 15 | 0 | 10 | 0 | 0 | 4 | 0 | 1 | 0 |
| `specs/spec-tap-boot-bootstrap.md` | 10 | 2 | 0 | 0 | 0 | 7 | 0 | 1 | 0 |
| `specs/spec-tap-logging.md` | 18 | 1 | 0 | 0 | 0 | 16 | 0 | 1 | 0 |
| `specs/spec-tap-plugin-validation-distribution.md` | 6 | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 0 |
| `specs/spec-tap-requirement-traceability.md` | 12 | 10 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| `tap_cares/specs/spec-tap-cares-v0.md` | 14 | 0 | 0 | 0 | 0 | 13 | 0 | 1 | 1 |
| `tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md` | 11 | 9 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |
| `tap_grid/specs/spec-grid-history.md` | 5 | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 0 |
| `tap_plugins/specs/spec-tap-plugin-load-lifecycle-v0.md` | 10 | 1 | 0 | 0 | 0 | 8 | 0 | 1 | 0 |
| `tap_plugins/specs/spec-tap-plugin-manifest-v0.md` | 12 | 9 | 0 | 0 | 0 | 2 | 0 | 1 | 1 |
| `tap_plugins/specs/spec-tap-plugin-testing.md` | 5 | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 0 |
| `tap_web/specs/spec-web-panels-standard-table.md` | 8 | 0 | 0 | 0 | 0 | 7 | 0 | 1 | 0 |
| `specs/spec-ai-integration.md` | 9 | 0 | 0 | 5 | 0 | 4 | 0 | 0 | 0 |
| `specs/spec-cicd-ai-review.md` | 9 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 |
| `specs/spec-cicd-root-of-trust.md` | 9 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 |
| `specs/spec-cicd-sbom.md` | 15 | 6 | 5 | 0 | 0 | 4 | 0 | 0 | 0 |
| `specs/spec-dev-boot-collectors.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `specs/spec-dev-multisession-onboarding-doc.md` | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| `specs/spec-dev-multisession-smoketest.md` | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| `specs/spec-dev-playwright-refresh-doc.md` | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| `specs/spec-dev-validation.md` | 15 | 7 | 2 | 0 | 0 | 6 | 0 | 0 | 0 |
| `specs/spec-docs.md` | 11 | 1 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| `specs/spec-fips.md` | 7 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `specs/spec-req-template.md` | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| `specs/spec-roadmap.md` | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 |
| `specs/spec-security-posture-corpus.md` | 12 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 |
| `specs/spec-security-posture.md` | 5 | 0 | 0 | 4 | 0 | 1 | 0 | 0 | 0 |
| `specs/spec-service-layer-boundary.md` | 9 | 1 | 0 | 0 | 0 | 8 | 0 | 0 | 0 |
| `specs/spec-sphinx-capability-docs.md` | 8 | 0 | 1 | 0 | 0 | 7 | 0 | 0 | 0 |
| `specs/spec-tap-callsite-identity.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `specs/spec-tap-flaw-v0.md` | 9 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 |
| `specs/spec-tap-health-v0.md` | 10 | 6 | 0 | 0 | 0 | 2 | 2 | 0 | 0 |
| `specs/spec-tap-known-dupes.md` | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `specs/spec-tap-package-security-v0-BACKLOG.md` | 12 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 |
| `specs/spec-tap-plugin-dependency-resolution.md` | 12 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 |
| `specs/spec-tap-settings.md` | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `specs/spec-tap-static-assets.md` | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| `specs/spec-tap-tree-scanner.md` | 4 | 1 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| `specs/spec.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_auth/specs/spec-tap-auth-passkey-v0.md` | 11 | 5 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_auth/specs/spec-tap-auth-user-management-v0.md` | 12 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 |
| `tap_cares/specs/spec-tap-cares-administrivia.md` | 13 | 0 | 11 | 0 | 0 | 2 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-aliases-BACKLOG.md` | 5 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-dimension-pocket-BACKLOG.md` | 13 | 0 | 0 | 0 | 0 | 13 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-dual-existence.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-history-timetravel-BACKLOG.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-perspective-BACKLOG.md` | 5 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-sqlite-portability-BACKLOG.md` | 10 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-user-BACKLOG.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-user-context-BACKLOG.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-user-saml-BACKLOG.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grid-uuid-selection.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grift-envelope.md` | 9 | 1 | 0 | 0 | 0 | 8 | 0 | 0 | 0 |
| `tap_grid/specs/spec-grift-seed-ids-real-uuid7.md` | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| `tap_plugins/specs/spec-disclosure-flags-v0.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_plugins/specs/spec-tap-plugin-external-development.md` | 5 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| `tap_plugins/specs/spec-tap-plugin-lifecycle-v1.md` | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `tap_plugins/specs/spec-tap-plugin-validation.md` | 17 | 16 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `tap_viz/specs/spec-viz-arrangement.md` | 10 | 3 | 6 | 0 | 0 | 1 | 0 | 0 | 3 |
| `tap_viz/specs/spec-viz-label-sizing-BACKLOG.md` | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| `tap_viz/specs/spec-viz-layouts.md` | 11 | 2 | 7 | 0 | 0 | 1 | 1 | 0 | 1 |
| `tap_viz/specs/spec-viz-nested-projection.md` | 12 | 0 | 9 | 0 | 0 | 3 | 0 | 0 | 0 |
| `tap_viz/specs/spec-viz-nesting.md` | 8 | 0 | 0 | 0 | 0 | 5 | 3 | 0 | 0 |
| `tap_viz/specs/spec-viz-projection.md` | 15 | 2 | 7 | 0 | 0 | 2 | 4 | 0 | 1 |
| `tap_viz/specs/spec-viz-shadows.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_viz/specs/spec-viz-stack.md` | 14 | 0 | 12 | 0 | 0 | 2 | 0 | 0 | 0 |
| `tap_viz/specs/spec-viz-system.md` | 9 | 0 | 0 | 0 | 0 | 8 | 1 | 0 | 0 |
| `tap_web/specs/spec-web-chrome.md` | 13 | 0 | 0 | 0 | 0 | 13 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-navigation.md` | 13 | 5 | 5 | 0 | 0 | 2 | 1 | 0 | 0 |
| `tap_web/specs/spec-web-panel-client-state.md` | 14 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-panel-data-export.md` | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-panel-entity-resolution-v0.md` | 10 | 9 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-panels-standard-flip.md` | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-panels-standard-history.md` | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| `tap_web/specs/spec-web-rendering.md` | 14 | 8 | 1 | 0 | 0 | 5 | 0 | 0 | 3 |

### Exclusions Ledger

Every documented exclusion, reason verbatim from its `Trace:` line. ⚠ marks a
zero-ACID exempt requirement (counted above; unpayable until non-pytest evidence exists).

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-boot-spawn-bridge` | non-python |  | scripts/spawn-session.sh |
| `req-cicd-base-image-sourcing` | non-python |  | docker/postgres/Dockerfile |
| `req-cicd-branch-protection` | external |  | GitHub repository rulesets (protect-default-branches, main-required-checks) |
| `req-cicd-build-once-artifact` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-dep-automation` | non-python | ⚠ | renovate.json5 |
| `req-cicd-product-releases` | non-python |  | .github/workflows/release-please.yml |
| `req-cicd-release-artifacts` | process |  | org release convention; the mechanical tag parsing is |
| `req-cicd-sbom-1` | non-python | ⚠ | scripts/sbom/generate.py |
| `req-cicd-sbom-2` | non-python | ⚠ | scripts/sbom/generate.py |
| `req-cicd-sbom-4` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-sbom-5` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-sbom-6` | non-python | ⚠ | scripts/sbom/generate.py |
| `req-cicd-supply-chain-provenance` | non-python |  | .github/workflows/publish-images.yml |
| `req-dev-multisession-admin-bootstrap` | non-python |  | scripts/spawn-session.sh |
| `req-dev-multisession-ci-gate` | non-python |  | .github/workflows/product-lines.yml |
| `req-dev-multisession-compose-parameterized` | non-python |  | docker-compose.yml |
| `req-dev-multisession-env-cascade` | non-python |  | scripts/dc |
| `req-dev-multisession-host-readiness` | non-python |  | scripts/spawn-session.sh |
| `req-dev-multisession-port-registry` | non-python | ⚠ | scripts/spawn-session.sh |
| `req-dev-multisession-promote-all-script` | non-python |  | scripts/promote-all-sessions.sh |
| `req-dev-multisession-promote-script` | non-python |  | scripts/promote-to-main.sh |
| `req-dev-multisession-push-workflow` | process |  | the branch-and-promote discipline developers follow; scripts automate steps, the rule is the requirement |
| `req-dev-multisession-spawn-script` | non-python |  | scripts/spawn-session.sh |
| `req-dev-validation-lean-boot` | non-python |  | scripts/gate-lean |
| `req-dev-validation-promote-hook` | non-python |  | scripts/promote-to-main.sh |
| `req-sphinx-docs-capability-blocks` | process |  | an authoring convention for docstring capability blocks; conformance is editorial, no code derives or enforces it |
| `req-tap-cares-administrivia-collector-detail` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-collector-table` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-fire-history` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-homepage` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-htmx-trigger` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-ksi-path` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-manual-run` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-ownership` | process |  | repo-layout and naming convention (CARES specs file under `tap_cares/specs/`, operator pages host in the Administrivia plugin); conformance is authoring discipline, and the execution contracts it restates are owned by spec-tap-cares-collector.md |
| `req-tap-cares-administrivia-run-observability` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-schedule-detail` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-administrivia-schedule-table` | external |  | administrivia plugin (evicted; its panels and shipped tests cite this RID) |
| `req-tap-cares-secrets-consumer-kinds` | narrative | ⚠ | the mechanics-vs-kinds ownership split; each side's substance is specified elsewhere |
| `req-tap-cares-secrets-cross-scope-concern` | narrative | ⚠ | documents a deliberately deferred control; nothing derives it until the least-privilege work lands |
| `req-tap-cares-secrets-history-audit` | process | ⚠ | a completed, human-triaged pre-publication audit; the record is the artifact |
| `req-tap-cares-secrets-precommit` | non-python | ⚠ | .githooks/precommit_secret_scan.py |
| `req-tap-cares-secrets-scope` | narrative | ⚠ | the umbrella statement; the checkable substance lives in the sibling requirements |
| `req-tap-cares-secrets-validation` | narrative | ⚠ | a deliberate non-centralization ruling; consumers own kind-specific validation |
| `req-tap-cares-task-backend-deployment` | non-python | ⚠ | docker/entrypoint.sh |
| `req-tap-cares-task-backend-huey-removal` | process | ⚠ | a completed removal plan; the commit history is the record |
| `req-tap-cares-task-backend-migration-plan` | process | ⚠ | the executed two-commit landing plan; history is the record |
| `req-tap-traceability-minting` | non-python |  | scripts/implements-tag |
| `req-viz-arrangement-anchor` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-arrangement-distribution` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-arrangement-execution` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-arrangement-members` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-arrangement-positioning` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-arrangement-span` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/arrangement.js |
| `req-viz-layout-capabilities` | narrative | ⚠ | an allowance, not a mechanism: nothing derives or enforces "layouts may do all scene work"; the runtime simply does not restrict, and the enforceable pieces (context shape, serial execution, warnings) live in the sibling requirements |
| `req-viz-layout-execution` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-lotr-example` | external | ⚠ | lotr plugin (evicted; the worked saga-stage layout example lives there) |
| `req-viz-layout-module-contract` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-runtime-context` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-runtime-modules` | process | ⚠ | a path-namespace authoring convention (projections/ for executables, runtime/ for shared utilities); conformance is editorial, imports are authored per-module |
| `req-viz-layout-warnings-errors` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-nested-projection-bounded-layer` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-container-size-from-children` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-container-visual` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-dimension-match` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-natural-layouts` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-natural-sizing` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-no-leaf-compression` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-runtime-api` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-nested-projection-two-pass` | non-python |  | tap_viz/static/tap_viz/js/runtime/nested-projection.js |
| `req-viz-projection-elevation-invariants` | process |  | the entry-asserts-state authoring contract for elevation layouts; there is no exit hook to enforce, each layout author conforms at entry |
| `req-viz-projection-incremental-loading` | process | ⚠ | a v0 placement decision (follow-up fetch lives inside tap layouts, no separate elevation-level search contract); guidance for layout authors, no core mechanism |
| `req-viz-projection-layout-runtime` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-lock-nodes` | non-python |  | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-lotr-monolith` | external | ⚠ | lotr plugin (evicted; the worked monolithic projection lives in its grift bundle) |
| `req-viz-projection-min-zoom` | non-python |  | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-self-contained` | narrative | ⚠ | a design principle (projections depend on no model-level display hints); the substance is distributed across the searches/elevations/layout machinery of the sibling requirements |
| `req-viz-stack-count-chip` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-count-disclosure` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-count-format` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-depth` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-direction` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-edge-collapse` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-idempotent` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-min-collapse` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-name` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-noninteractive` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-primitive` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-viz-stack-proxy-collapse` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/stack.js |
| `req-web-nav-breadcrumb-header` | non-python |  | tap_web/templates/tap_web/base.html |
| `req-web-nav-chrome-budget` | process |  | change-control on the header's enumerated element budget; additions require a spec revision, conformance is review discipline |
| `req-web-nav-no-hamburger` | process |  | a standing design prohibition; code cannot demonstrate an absence, review discipline holds the line |
| `req-web-nav-segment-interactions` | non-python |  | tap_web/static/tap_web/js/breadcrumb.js |
| `req-web-nav-user-menu` | non-python |  | tap_web/templates/tap_web/base.html |
| `req-web-render-flash` | non-python |  | tap_web/templates/tap_web/base.html |

<!-- END GENERATED ACCOUNTING -->

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
