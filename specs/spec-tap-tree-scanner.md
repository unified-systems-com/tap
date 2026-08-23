# Tree-Scanner Substrate

## Philosophy

TAP has a handful of build-time **tree-scanners** — they read the first-party source with
Python's `ast` module and flag things: ungated privileged sinks (`authz_coverage`), direct
ORM writes outside the service layer (`direct_write_coverage`), malformed log-site tokens
(`logging`), plugin-dependency mismatches (`plugin_deps`), ungated service-gateway
functions (`service_gateway`).

They all do the same low-level work — walk the files, parse each one, figure out a
decorator's name, track which function or class you're currently inside — and today each
one re-rolls that work by hand. `_decorator_name` is written **twice** already, with two
different return types; the scope-stack walk got copy-pasted from one scanner into another;
there are five separate "for each `.py`, parse it" loops.

This spec says: that low-level work lives in **one** place, and scanners build on it.

The reason to bother isn't tidiness — it's correctness. When two security guards each carry
their own decorator-resolution and the two drift apart, one of them is quietly wrong, and
"quietly wrong" in a guard means a gap that still shows green. One shared substrate is one
place to get it right, and every scanner inherits the fix.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Parse Layer | Every tree-scanner parses through the same shared primitives. |
| 2. | No Drift | Decorator / scope / call-name resolution is written once, not per scanner. |
| 3. | Pre-Boot, No Deps | Stdlib `ast` only; runs before Django is loaded. |
| 4. | Safe To Consolidate | Migrating a scanner onto the substrate does not change what it flags. |

## Design notes (honest — not a fresh survey)

This is internal plumbing, so this isn't an external prior-art pass. The substrate is the
Python standard library `ast` module (the `NodeVisitor` pattern). Richer options exist and
are deliberately **not** adopted: `libcst` (lossless CST, aimed at rewriting), `astroid`
(pylint's inference engine), and `Semgrep` (external pattern engine). Stdlib `ast` is enough
for "find and flag," adds no dependency, and runs pre-boot — the same reasoning
`authz_coverage.py` already records for choosing an in-house scanner over Semgrep.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-tree-scanner-substrate | [Shared Scan Substrate](#shared-scan-substrate) | Proposed | The parse/decorator/scope primitives live in one module (`tap/source_scan.py`) |
| req-tap-tree-scanner-single-shape | [Scanners Compose It, Don't Re-Roll](#scanners-compose-it-dont-re-roll) | Proposed | A scanner builds on the substrate; it doesn't re-implement parsing |
| req-tap-tree-scanner-preboot | [Pre-Boot, Dependency-Free](#pre-boot-dependency-free) | Proposed | Stdlib `ast` only; runs pre-boot, registry-independent |
| req-tap-tree-scanner-consolidation | [Consolidation Worklist](#consolidation-worklist) | Proposed | The current duplication, and the rule that migrations don't change what a scanner flags |

---

### Shared Scan Substrate
----
RID: `req-tap-tree-scanner-substrate`
Status: `Proposed`

The shared parsing primitives live in `tap/source_scan.py` — already the home of
`first_party_source_roots()`, `CallSite`, and `CallsiteIdentity`. This adds the parsing
mechanics that scanners currently hand-roll:

- **A file/parse driver** — walk the first-party `.py` files, parse each once, hand back
  `(path, tree)`. One loop, not five.
- **Decorator resolution** — turn a decorator node (`@x`, `@x(...)`, `@a.b.c`) into its
  name, and a `has_decorator(node, names)` helper. This replaces the two `_decorator_name`
  functions (in `authz_coverage.py` and `service_gateway.py`, which return `str | None` and
  `str` respectively).
- **Call-name resolution** — the called function's name from a `Call` node (`foo(...)`,
  `x.foo(...)`). This replaces `authz_coverage.py`'s `_call_name`.
- **A scope-stack visitor base** — a `NodeVisitor` subclass that tracks the enclosing
  `def`/`class` qualname as it walks, so a scanner overrides `visit_Call` and just reads the
  current qualname. This replaces the copy-pasted scope walks (`authz_coverage` →
  `direct_write_coverage`); the callsite anchors (`spec-tap-callsite-identity.md`) already
  need this same walk.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-tree-scanner-substrate-1 | One Home | Proposed | The shared parse/decorator/call-name/scope primitives live in `tap/source_scan.py`. | |
| req-tap-tree-scanner-substrate-2 | The Four Mechanics | Proposed | The substrate provides a parse driver, decorator resolution, call-name resolution, and a scope-stack visitor base. | |

---

### Scanners Compose It, Don't Re-Roll
----
RID: `req-tap-tree-scanner-single-shape`
Status: `Proposed`

A tree-scanner builds on the substrate instead of re-implementing parsing. A scanner
overrides the shared visitor and reads the shared helpers; it does not call `ast.parse`
itself, write its own `_decorator_name`, or re-derive an enclosing-scope walk. Adding a new
scanner means composing the primitives, not copying another scanner's boilerplate.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-tree-scanner-single-shape-1 | No Re-Rolling | Proposed | No tree-scanner carries its own parse loop, decorator resolver, or scope walk once the substrate exists. | |
| req-tap-tree-scanner-single-shape-2 | New Scanners Compose | Proposed | A new scanner is written by composing the substrate's primitives. | |

---

### Pre-Boot, Dependency-Free
----
RID: `req-tap-tree-scanner-preboot`
Status: `Proposed`

The substrate uses only the standard library `ast` module — no `import-linter`, `libcst`,
`astroid`, or `Semgrep` — and runs **pre-boot**, independent of Django's app registry, the
same as `first_party_source_roots()` and `discover_guards()`. That is what lets the scanners
run inside the pre-boot gate and at pytest collection time, before settings and apps load.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-tree-scanner-preboot-1 | Stdlib Only | Proposed | The substrate adds no third-party dependency; it uses stdlib `ast`. | |
| req-tap-tree-scanner-preboot-2 | Runs Pre-Boot | Proposed | The substrate runs before `django.setup()`, independent of the app registry. | |

---

### Consolidation Worklist
----
RID: `req-tap-tree-scanner-consolidation`
Status: `Proposed`

This records the current duplication and the one rule that governs removing it: a migration
must not change what a scanner flags.

#### The worklist
Migrate onto the substrate:

- `tap/authz_coverage.py` — `_AuthzVisitor` (scope walk), `_decorator_name`, `_call_name`.
- `tap/direct_write_coverage.py` — `_DirectWriteVisitor` (scope walk copied from authz).
- `tap/logging.py` — the log-site scanner's file/parse loop.
- `tap/plugin_deps.py` — its parse loop.
- `tap_grid/guards/service_gateway.py` — its own `_decorator_name`, its `tree.body` loop.

Duplication to remove: two `_decorator_name` implementations, one copy-pasted scope walk,
five separate parse loops.

Consolidated onto the substrate since the worklist was recorded:

- Exclusion sets + out-of-scope predicates (landed 2026-08-22): `DEFAULT_EXCLUDE_DIRS` /
  `is_excluded_dir()` / `default_out_of_scope()` in `tap/source_scan.py` replace six
  hand-copied `_EXCLUDE_DIRS` variants (secret-leak, secret-pattern, known-dupes,
  secrets-root, record-site, the JSON naming scanner — whose variant was missing
  `tap_secrets`) and three copy-pasted tests/migrations predicates (authz, direct-write,
  credential-bind; authz adopted the standard migrations skip, verified no-op).
  `iter_parsed_sources` honors the shared set. Set-diff per
  req-tap-tree-scanner-consolidation-2: zero differences across 2,871 captured rows —
  flagged sets AND walked sets identical.

- ORM write-shape vocabulary (landed 2026-08-22): `MANAGER_WRITES` / `TERMINAL_WRITES` /
  `orm_write_target()` in `tap/source_scan.py` — one write-shape grammar for
  `tap/direct_write_coverage.py` and `tap_auth/credential_bind_coverage.py`, which had
  drifted (`update_or_create` in one, `aupdate_or_create` in neither); consumers keep
  their own model-resolution. Verified behavior-preserving by set-diff per
  req-tap-tree-scanner-consolidation-2 — with the one *intended* vocabulary change
  (the two `*_or_create` additions) confirmed to flag nothing new on the current tree.

#### Behavior preservation (the load-bearing rule)
A migration MUST NOT change what any scanner flags. The check is the scanner's
**flagged/measured set before == after** — not merely "the tests pass." These are security
guards: one that silently flags *fewer* things still passes its own tests while quietly
weakening a boundary. So the migration is verified by snapshotting each scanner's output set
on the pre-refactor tree, refactoring, and asserting the sets are identical — alongside the
guard suite staying green and `black`/`ruff`/`mypy` clean.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-tree-scanner-consolidation-1 | Worklist Recorded | Proposed | The scanners to migrate and the duplication to remove are named. | |
| req-tap-tree-scanner-consolidation-2 | Behavior-Preserving | Proposed | Each migration leaves the scanner's flagged set identical (before == after), verified by set-diff, not only by a green suite. | |
| req-tap-tree-scanner-consolidation-3 | Duplication Removed | Proposed | After migration there is one decorator resolver, one scope walk, and one parse driver. | |

---

## Relationship To Other Specs

- **`spec-tap-callsite-identity.md`** — the finding-identity layer (anchor / location /
  discriminator) sits *on top of* this parse layer; both live in `tap/source_scan.py`.
- **`spec-dev-validation.md`** — owns the guard harness; most tree-scanners are guards run
  via `tap/tests/test_guards.py`.
- **`spec-service-layer-boundary.md`** — its reusable boundary guard is a tree-scanner and
  is built on this substrate (`req-service-boundary-guard`).
- **`spec-tap-logging.md`** — the log-site scanner is one of the tree-scanners on this
  substrate.

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
