---
spec: ../../specs/spec-req-template.md
audience: [developer, llm]
covers:
  - ../../specs/spec-req-template.md
  - ../../specs/spec-docs.md
update-triggers:
  - A decision is made on any design question in §5 or §6 — record it and mark the option chosen
  - The RID convention changes (tag syntax, revision scheme, status derivation)
  - OpenFastTrace, StrictDoc or Doorstop materially change their code-side link model
  - The measured numbers in §1 are re-run (they date this doc)
assumes:
  - TAP's spec system: markdown specs, RIDs (`req-<app>-<spec>-<feature>`), ACIDs, Status vocabulary
  - The duplicates-session findings and the TAP-KNOWN-DUPE convention
provides: |
  Prior-art sweep and design analysis for adding rigor to TAP's requirement-ID system: the
  measured current state, what the requirements-traceability field has already built (OpenFastTrace,
  Doorstop, StrictDoc, SQLite, LOBSTER, the regulated standards), what the evidence settles about
  tag design, and the open design questions. PRE-DECISION.
---

# Requirement Traceability — Prior Art and Design Analysis

**Status: pre-decision.** Written 2026-08-12 from a five-agent research sweep. Companion:
[doc-dev-duplication-defense.md](doc-dev-duplication-defense.md) §6b, which holds the empirical
test that started this thread (RID-reference timing as a duplication signal — rejected, with the
`IMPLEMENTS:` ownership tag proposed in its place).

The trigger: RID citations in TAP code are **narrative, not ownership**. Of 1,919 RID mentions in
`.py` files, 71% sit in docstrings and 28% in comments as explanatory cross-references — "related
to req-X" — with only 1% in code identifiers. A many-to-many explanatory relation cannot answer
"which function *is* the authoritative implementation of this requirement," which is the question
both duplication detection and honest status reporting need.

---

## 1. Measured starting point (2026-08-12, `main` @ af84175a)

| Measure | Value |
| --- | --- |
| RIDs authored in specs (canonical `RID:` declarations) | **1,493** |
| …ever cited in a Python file | **475 (32%)** |
| RIDs carrying a `Status:` line | 1,054 |
| Marked `Implemented` | 492 — **306 of those (62%) have zero Python references** |
| Marked `Proposed` | 375 — **89 of those (24%) are cited in code anyway** |
| Marked `Verified` | **0 — the terminal state is unused; the lifecycle never completes** |
| Status vocabulary drift | `Backlog` (91), `Partially Implemented` (10) vs `Partial` (1), `Open` (1), `Deferred` (1) |
| Prose RID references in `.py` (the pre-existing namespace) | **1,803 hits** |

Two honest caveats. The reference scan is Python-only — requirements implemented in shell,
workflows, templates, or GRIFT seed data show as uncited. And some `Proposed`-but-cited cases are
legitimate: the `req-sec-*` doctrine requirements are *cited as guidance*, not implemented. So this
is **not** 306 false claims; it is **306 claims nothing can check**, which is the actual defect —
the status field asserts something no mechanism confirms.

**The 68% uncited figure is normal, and the panic is misplaced:**

| System | Tracked IDs | No code/test reference |
| --- | --- | --- |
| Kubernetes (KEPs vs feature gates) | 646 | **82.2%** |
| CPython (all PEPs vs source) | 735 | **81.6%** |
| SQLite testable statements | ~2,270 | ~74% |
| Clang C++ DRs | 3,174 | 70.6% |
| **TAP specs** | 1,493 | **68%** |
| CPython, Final Standards-Track only | 308 | 61.7% |
| libc++ WG21 papers | 1,856 | 30.8% |
| Rust RFCs (resolved) | 509 | 21% |
| DO-178C / ISO 26262 / IEC 62304 | all | 0% — *mandated, not achieved* |

**But the number is uninterpretable until requirements that legitimately need no code are marked.**
Every mature system has that marker — Doorstop `derived: true`, OpenFastTrace per-item
`Needs: impl, utest`, clang `na` / `na lib` / `na abi`. Without it a gap and a
never-meant-to-touch-code requirement are indistinguishable. Rust confirms from the other side: its
~80 RFCs with no tracking issue are overwhelmingly process/governance RFCs. TAP's doctrine and
posture requirements are exactly this shape.

---

## 2. Prior art — the field

**This is one of the oldest formalized disciplines in software engineering**, driven by regulated
industries. The vocabulary TAP would be adopting already exists: trace link *types*
(implements / verifies / refines / derives-from / covers), *coverage* vs *satisfaction* (does a
link exist vs is the link any good), and forward/backward traceability.

**Correction worth carrying: vendor traceability claims are consistently stronger than the
normative text behind them.** "ISO 26262 mandates bidirectional traceability" is repeated by LDRA,
MathWorks and most tool marketing — but the phrase appears in ISO 26262 **exactly once, as an
informative NOTE** (Part 6 §7.4.2), and Part 6 §4.2 states verbatim that notes *"shall not be
interpreted as a requirement itself."* The phrase is **Automotive SPICE** vocabulary; ASPICE is
what suppliers are actually graded on.

What ISO 26262 *normatively* requires, and both items are directly relevant:

- **8-6.4.2.5 a)** — safety requirements shall have *"a unique identification remaining unchanged
  throughout the safety lifecycle."* **TAP's deterministic `req-<app>-<spec>-<feature>` slugs
  already satisfy this**, and it is an argument against ever changing the ID format.
- **8-9.4.2.2 b)** — each test case shall reference **the version** of the work product verified.
  An independent arrival at OpenFastTrace's revision integers, from a completely different
  tradition.

**Granularity: the regulated standards sit at the COARSE end, and assessors enforce that.** VDA
Automotive SPICE Guidelines 2.0 carry rating rules that *forbid downrating coarse links* —
`[TAC.RL.1]` protects cluster-level rather than atomic-element traceability; `[SWE.3.RL.1]`
protects mapping a software unit to a *cluster* of routines. The allowed-granularity list bottoms
out at "software unit"; **there is no file, function, or line level in it.** ASPICE 4.0 retargets
SWE.3 to detailed design explicitly because *"the term 'software unit' may be interpreted as the
implementation of the unit in source code. This interpretation is not intended."* Assessor-facing
guidance is blunt: *"Tracing at too fine a level (e.g., individual lines of code) adds unnecessary
detail without improving assessment value."* The one peer-reviewed case study traced to
**implementation file** granularity.

**ASPICE 4.0 formally blesses the comment-tag approach** — information item 13-51 names "naming
conventions" and "editorial references" as acceptable link mechanisms. And its recurring warning is
the strongest external support for adding a staleness state: *"Traceability alone, e.g., the
existence of links, does not necessarily mean that the information is consistent."* DOORS' *suspect*
flag, Simulink's *unresolved*, and OFT's revision integers are three implementations of that one
idea.

**Sustainability evidence (peer-reviewed).** Maro, Steghöfer & Staron, *Journal of Systems and
Software* (2018) — tertiary review plus an automotive-supplier case study. Of 22 identified
challenges, **six remained unsolved**, led by manual link creation/maintenance and traceability
being perceived as overhead. A separate industry study ([arXiv 2504.15427](https://arxiv.org/abs/2504.15427))
measures *"several weeks each year on manually validating requirements traceability."*

Two findings from that paper matter enormously here:

1. ***"The creators of the links are often not the ones using them"*** — named as the motivational
   root cause of trace rot. **This structurally does not apply to a solo maintainer.** The single
   most-cited reason traceability fails in industry is absent from TAP's situation, which is a
   genuine argument that this is more tractable here than the literature's pessimism implies.
2. ***"The most reliable assessment method is still manual checking"*** — you can cheaply verify
   that links *exist*, not that they are *good*. The coverage-vs-satisfaction gap, confirmed
   empirically.

---

## 3. Prior art — the tools

### OpenFastTrace — closest prior art by a distance

ID format `artifact-type~name~revision` (`req~html5-exporter~1`); in-code tag
`// [impl->dsn~validate-authentication-request~1]`. `oft trace` exits 0/1/2 for CI. **The status
vocabulary is the thing to steal:**

| Status | Meaning |
| --- | --- |
| `Duplicate` / `Ambiguous` | two items share an ID — *flagged as a copy-paste error* |
| `Orphaned` | claims to cover a requirement that does not exist |
| `Unwanted` | covers something needing no coverage — *"copy-paste error likely"* |
| **`Outdated`** | **covers an older revision — the spec changed, the claim did not** |
| `Predated` | covers a newer revision than exists — likely typo |

The **revision integer is a manual, cheap, in-band staleness handle**: bump when the *meaning*
changes and every claim still pointing at the old revision reports `Outdated` immediately. Manual
is the feature — it does not churn on typo fixes. It is also the only tool of the three doing the
code leg properly (Tag Importer, ~30 languages, typed defects, CI exit code).

### SQLite — the strongest staleness mechanism found anywhere

**Requirement IDs are the MD5 hash of the requirement text** (`R-02748-19096`), so requirements are
*inherently immutable*: any edit produces a different requirement. Three checks fall out —
ID-must-match-text (`scan_test_cases.tcl` recomputes and errors on mismatch), stale-evidence
detection (*"the requirement text has changed but the evidence text did not"*), and
**duplicate-requirement detection for free**, since identical normalized text collides on hash.
Verified: 971 marks in the 3.50.2 tree quote the requirement text alongside the ID and **all 971
hash correctly — zero drift**.

Two affordability tricks worth copying regardless of the ID scheme:

- **The traceability report emits the paste-ready comment pre-hashed** — nobody types an ID or
  retypes the text. (Same lesson as Gerrit's `Change-Id`; same shape as TAP's `scripts/log-site-id`.)
- **Evidence is graded across four classes, and a requirement renders green only at 2+ independent
  classes, orange at exactly one.** *A requirement cited only by its implementation is not
  considered verified.* This is the principled basis for splitting `IMPLEMENTS` from `VERIFIES` —
  the implementation claiming itself does not count.

**The coverage distribution is the strategic lesson**: 80.5% on `rtree.in`, 72.9% on
`lang_select.in` — and **flat 0%** on `optoverview.in` and `datatype3.in`. 60–90% wherever a human
deliberately built an evidence-driven test file, 0–20% everywhere else. **Coverage does not accrete
from ordinary testing.** For scale: 155.8 KSLOC of C, 51,445 TCL test cases, ~1,100 evidence marks
— a thin, deliberately-targeted layer, not a property of the suite.

**And the reframe:** SQLite abandoned "requirements precede implementation" and redefined a
requirement as *"a testable statement of truth about the behavior of the system,"* extracted from
documentation that had to exist anyway. That is why they can afford thousands and why the marks are
cheap.

### StrictDoc — chose docstrings for Python, and models the exact semantic

```python
def bar(self):
    """
    @relation(REQ-1, scope=function)
    """
```

Scopes: `file`, `class`, `function`, `range_start`/`range_end`, `line` — with **file/class/function
markers in the docstring** and `#` comments reserved for line/range scopes that have no docstring.
A considered endorsement of the docstring choice for Python.

Critically it has **roles**: `@relation(REQ-1, scope=function, role=Implementation)` — the only
surveyed mechanism expressing *"this is THE implementation; others merely relate."* That is TAP's
semantic, already modeled. Its error messages are the standard to copy: `file:line:col` plus
structured `title` / `hint` / **`example` of the correct form**, and a uniqueness error naming
*both* colliding sites.

### Doorstop — content fingerprints

Links carry a SHA-256 of the parent at last review; *"the link fingerprint is used by Doorstop to
detect when a parent item is changed."* The automated version of OFT's revision integer, requiring
a `doorstop review` verb to re-stamp. Its `ref` resolution is a documented anti-pattern worth
knowing: greps for a keyword and, if found in multiple places, **the first found wins** — silent
first-match-wins on an ambiguous reference is exactly what a duplicate guard exists to prevent.

### LOBSTER (BMW) — two rules worth adopting verbatim

`# lobster-trace: something.example` / `# lobster-exclude: a very good reason is here`.

1. *"Tracing links are only ever added to artefacts lower in the tracing hierarchy… The generated
   report will show bi-directional traceability, computed from the uni-directional annotations."*
   **Store the link once, derive the reverse.** Duplicated links are how matrices rot.
2. **The escape hatch's payload is a mandatory reason**, not a bare flag — consistent with TAP's
   FIPS-waiver and `guard-allow` house style.

It also shows why decorators are fragile: `--parse-decorator` matches **literal dotted names**, so
`@implements`, `@tap.implements`, and `from tap import implements as impl` are three different
strings and an alias **silently misses** (fail-open).

### Not applicable

**Sphinx-Needs has no source-code annotation feature at all** — docs↔docs and docs↔test-results
only. **Doxygen `\xrefitem`** collects but does not validate: no duplicate, orphan, or referential
integrity checking. Doxygen gives the report; OFT gives the gate, and the gate is the harder half.

---

## 4. What the evidence settles about tag design

### Docstring, not decorator, not comment

| | Docstring | Decorator | Comment |
| --- | --- | --- | --- |
| AST-parseable without importing | **yes** (`ast.get_docstring()`) | only by literal dotted-name match — **aliasing fails open** | **no** — `ast` discards comments |
| Runtime cost / import coupling | none | one call per def; adds an import edge from every tagged module | none |
| Shares a line with other tools | no | no | **yes** — `noqa`, `type: ignore`, isort, coverage, with a *documented required ordering* |
| Can be rewritten by another tool | no | no | **yes** — `ruff --fix` |
| Prior art for exactly this | **StrictDoc, for Python** | LOBSTER `--parse-decorator` | LOBSTER, StrictDoc line scopes |

PEP 698 (`@override`) is Python's own answer to "a decorator asserting something a checker
verifies," and it **rejected runtime enforcement** (performance, complexity, unreliability), sets
`__override__` best-effort, and carries a documented **ordering hazard** (must follow
`functools.lru_cache`, precede `@property`/`@staticmethod`/`@classmethod`) — a recurring paper cut
in a Django codebase.

Two traps if docstring: read **source**, never `obj.__doc__` — `python -OO` discards docstrings, and
`functools.wraps` copies them, so a wrapper would silently inherit the claim.

### Ship the inverse lint with the lint

Clippy shipped `unnecessary_safety_comment` alongside `undocumented_unsafe_blocks`; mypy shipped
`unused-ignore` alongside `type: ignore`. Every "you must tag" rule needs a "you tagged something
that needs no tag" partner, or it drifts in the other direction.

### Lint for near-misses — typos fail OPEN

`// SAFTEY: Trust me.` reports "no safety comment" without noticing the misspelling (open clippy
issue). Go measured **98 build constraints silently ignored** from placement rules. flake8
documents that `# noqa E731` (no colon) silently degrades to a *blanket* suppression. **~60% of
real-world failures are shape, not staleness.**

### Mint it, never type it

Gerrit's `Change-Id` essentially never rots and draws no complaints — because a commit hook mints
it. The kernel ships `git log -1 --pretty=fixes` so `Fixes:` is never hand-typed. SQLite's report
emits the comment pre-hashed. **TAP already has this house pattern** (`scripts/log-site-id`,
`scripts/uuid7`).

### Namespace the token

`IMPLEMENTS:` already means *interface conformance* to every human and model trained on
JSDoc/Java/TypeScript. Every surveyed traceability tool kept a tool-specific token (`lobster-trace:`,
`@relation(`, `[impl->`). PHPUnit hit a real collision where phpDocumentor's `@uses` triggered its
deprecation warnings. And **TAP's `.py` files already contain 1,803 prose RID references** — the
authoritative claim must be unmistakably distinct from them.

### Redundancy is the staleness checker

`Fixes: 54a4f0239f2e ("KVM: MMU: make kvm_mmu_zap_page() return the number of pages it actually
freed")` carries the SHA **and** the subject, so a mismatch is mechanically detectable. A bare ID
cannot rot loudly. OFT's revision integer, Doorstop's SHA-256, and the kernel's subject-redundancy
are three independent designs of one idea.

### Uniqueness keys and scope

- Key on **`(module, req_id)`**, deduped within a module — conditional definitions
  (`if sys.version_info >= ...`) otherwise manufacture false duplicates (a decade of open mypy
  issues from exactly this).
- **Scope uniqueness to a role.** OFT and LOBSTER both assume *many* code sites per requirement;
  only StrictDoc's `role=Implementation` expresses one-authoritative. In a layered architecture a
  requirement is often realized by a service function *plus* a model *plus* a guard — all
  legitimate. `(requirement, role)` is far cheaper to design in now than to retrofit.

### Registries worth copying outright

**rustc error codes** — one per line in a central file; **duplicates fatal**; every code must have
a doc file; **every code must actually be emitted by the compiler** (the orphan check in the hard
direction); two named grandfathering allowlists; retired codes never deleted or reused, marked
*"no longer emitted."* **pylint's `MessageIdStore`** enforces a strict 1:1 msgid↔symbol mapping and
solves renames with `old_names` aliases plus `DeletedMessageError`, so a once-valid ID can never
silently vanish *or* be reused. **Design the retired-ID story now** — a split/merged/renamed
requirement is the likeliest source of a future dangling claim, and ReCite measured **869 stale
function references in Linux v6.18-rc1** from exactly this cause.

### Calibrations

- **"Everyone follows it" and "a machine can prove it" are years apart.** Rust's `// SAFETY:` was
  near-universal in std by Feb 2021; turning the *lint* on for std is still an open experiment in
  Aug 2026 — **332 files, +3,197/−674**. rust-lang/rust does not even use the clippy lint; it uses
  a homegrown string-matching scanner in `tidy` scoped to `core` only, whose blind spots
  (`unsafe impl`, `#[unsafe(...)]`) were filed as a bug on 2026-08-11. **Prefer AST over regex.**
- **Budget for permanent repair.** A bot has mailed LKML daily since 2013 when `Fixes:` tags do not
  match their targets, and still emits multiple malformed-tag reports per week.
- **Structured tags are the tractable case.** Ratol & Robillard (ASE 2017): *"more than half of the
  total number of identifiers had fragile comments after renaming"* — but *"in the case of
  semi-structured comments… text-replacement based approaches typically work much better."* A
  stable slug sits on the right side of that line; a code identifier does not.
- **Copy-paste propagation is the failure mode everyone names and nobody catches.** The original
  clippy request anticipated it (*"would also raise a warning if that comment is copied verbatim"*)
  — never implemented. OFT names it twice in its status vocabulary. **A duplicate guard is the
  countermeasure, and this is the strongest validation of the instinct.**

### The governance gate

**Every durable tag has a consumer that visibly breaks or visibly omits.** `Fixes:` earned its
accuracy from stable-tree backporting; Conventional Commits from the changelog; SPDX from license
compliance; `Change-Id` from re-association across rebases. **Inert tags rot, always.** Name the
consumer before the syntax.

For TAP the natural consumer is **derived status**: if `TAP-IMPLEMENTS:` is what makes a
requirement's status read `Implemented` on a published surface — and `VERIFIES:` on its ACIDs is
what makes it read `Verified` — the tag has teeth, `Verified` becomes reachable for the first time,
and the 306 unverifiable claims become a worklist. This is the same "generated Map is the system of
record" inversion already applied to the Validation Map, pointed at the spec corpus.

---

## 5. Candidate design

Assembled from the above; **not decided**.

```python
def grid_table_names() -> frozenset[str]:
    """TAP-IMPLEMENTS: req-grid-table-classification.sec@2 ("Grid table classification")

    The one derivation of "which tables are grid tables".
    """
```

- **Stable slug, revision outside the ID.** Keep `req-<app>-<spec>-<feature>` as the identity (ISO
  26262 8-6.4.2.5 a's stable-identifier property, and 1,803 prose references + spec cross-refs +
  docs depend on it). Carry the revision **only at claim sites**, of which there are few by
  construction. OFT bakes revision into the ID because it had no installed base; TAP does.
- **Title redundancy** catches renames with **zero discipline**; the **revision integer** catches
  meaning changes with a manual bump. They compose — use both.
- **Hash the ACID table, not the whole requirement.** TAP's template separates narrative prose from
  the ACID table of "concrete, testable conditions." Hashing only the ACIDs gives SQLite's
  automatic staleness guarantee at a fraction of the churn, because meaning lives in the ACIDs and
  typo fixes live in the prose. Use it as a **warn** (prompt to review); the revision bump is the
  hard signal.
- **The ACID-diff prompt.** A guard can read a PR's spec diff and ask: *"this edits `req-example-x`'s
  acceptance criteria but does not bump its revision — intentional?"* That converts "remember to
  bump" into a prompt at the moment of forgetting.
- **Four checks, ratcheted independently:** shape (fail closed on near-misses) → referential
  integrity (the RID exists) → uniqueness per `(requirement, role)` → staleness (`Outdated` /
  claim on a retired RID).
- **A `needs: none` / `derived` marker** for doctrine and process requirements, so coverage means
  something.
- **`scripts/implements-tag req-example-name`** emitting the full line pre-filled from the spec.
- **Escape hatch with a mandatory reason**, plus a path-scoped waiver for migrations, vendored
  plugins, and generated code.
- **Errors carry `file:line:col`, name both colliding sites, and include a worked example.**
- **A test that asserts the guard fires** — a fixture with a deliberate duplicate it must reject.
  (pytest's `--strict` silently un-deprecated itself for two majors; TAP has the
  evicted-plugin-tests scar already.)

---

## 5b. Backfill technique — commit co-occurrence

For the rollout problem "which function implements this already-shipped requirement," the
cheapest candidate generator is **the commit that authored the RID**: list the `.py` files
that commit touched, and the implementation is almost always among them.

This is measured, not assumed. The RID-timing analysis (§6b of
[doc-dev-duplication-defense.md](doc-dev-duplication-defense.md)) found:

| Measure | Value |
| --- | --- |
| RIDs whose first spec commit **is** their first code commit | **40%** |
| RIDs whose spec and first code reference land the same day | **75%** |
| Median spec-birth → first code reference | **0.02 days** |

**Note the inversion.** Co-occurrence *failed* as a duplication signal for exactly the
reason it *succeeds* here: spec and implementation are authored together, so the timing
axis has no dynamic range to separate a duplicate from an original — but that same tight
coupling makes "what else was in this commit" a high-precision shortlist for backfill. The
same measurement answers one question badly and the other well.

Practical shape: for each RID in the seed set, `git log -S'RID: \`<rid>\`' --reverse` gives
the authoring commit; `git show --name-only` gives the candidate files; the human (or a
review agent) picks the authoritative derivation and mints the tag. Widen from same-commit
to same-day for the ~35% that straddle.

Three honest limits: it produces **candidates, not answers** (a commit may touch many
files); it cannot help the 68% of RIDs never referenced in code, where there may be no
implementation to find; and it depends on per-commit granularity surviving — TAP's promote
flow uses merge commits rather than squash, so the signal is intact today, but squash-merging
feature branches would collapse it.

## 6. Open design questions

- **Granularity — the sharpest open question.** The candidate above is function-level.
  ISO 26262/ASPICE bottom out at *software unit*, assessors actively protect coarse links, and
  sub-unit tracing is called "cost without benefit"; the one peer-reviewed case study traced to
  *implementation file*. But TAP's goal is not assessment coverage — it is identifying the
  **authoritative derivation of a fact**, which is inherently function-shaped, and which was where
  every duplicate finding lived. Likely resolution: function-level tags on the **small subset of
  requirements that designate a canonical derivation**, not across all 1,493 — consistent with
  SQLite's targeted 80%/0% distribution and with "target the tracing, don't spread it."
- **Which requirements get traced at all?** SQLite's evidence says a uniform 32% is a worse
  position than 85% on the security-posture/FIPS/service-boundary requirements and 5% elsewhere.
  What is the target set?
- **Does `VERIFIES:` land in the same wave as `TAP-IMPLEMENTS:`, or after?** SQLite's two-classes
  rule argues they belong together — an implementation citing itself is not verification.
- **Is derived status a report, a ratchet, or a gate?** It is the tag's consumer, so it must be at
  least *published and looked at*. Whether a status regression can red CI is a separate decision.
- **Retired-ID story** — `old_names`-style aliases, or hard failure on a dangling claim?
- **Adoption ratchet** — changed-lines-only (Chromium's model, no baseline file) vs a committed
  baseline vs per-app targets (SPARK's level model). Blanket-exempt generated/vendored code on day
  one either way.

---

## Key sources

**Tools:** [OpenFastTrace](https://github.com/itsallcode/openfasttrace) · [StrictDoc](https://github.com/strictdoc-project/strictdoc) · [Doorstop](https://github.com/doorstop-dev/doorstop) · [LOBSTER (BMW)](https://github.com/bmw-software-engineering/lobster) · [SQLite requirements](https://www.sqlite.org/requirements.html)

**Conventions + enforcement:** [Rust std safety-comment policy](https://std-dev-guide.rust-lang.org/policy/safety-comments.html) · [clippy `undocumented_unsafe_blocks`](https://rust-lang.github.io/rust-clippy/master/#undocumented_unsafe_blocks) · [RFC 3842 Safety Tags](https://github.com/rust-lang/rfcs/pull/3842) · [Annotating and Auditing Unsafe Rust (arXiv 2504.21312)](https://arxiv.org/abs/2504.21312) · [PHPUnit code coverage](https://docs.phpunit.de/en/11.5/code-coverage.html) · [mypy error codes](https://mypy.readthedocs.io/en/stable/error_codes.html) · [ruff RUF100](https://docs.astral.sh/ruff/rules/unused-noqa/) · [kernel submitting-patches](https://docs.kernel.org/process/submitting-patches.html) · [Gerrit Change-Id](https://gerrit-review.googlesource.com/Documentation/user-changeid.html) · [PEP 698](https://peps.python.org/pep-0698/)

**Research:** Maro, Steghöfer & Staron, *JSS* 2018 (traceability challenges) · [Ratol & Robillard, ASE 2017 (fragile comments)](https://www.cs.mcgill.ca/~martin/papers/ase2017.pdf) · [ReCite (arXiv 2608.03734)](https://arxiv.org/abs/2608.03734) · [traceability validation burden (arXiv 2504.15427)](https://arxiv.org/abs/2504.15427)

**Standards:** ISO 26262 Part 6 / Part 8 (8-6.4.2.5 a, 8-6.4.3.2, 8-9.4.2.2 b) · VDA Automotive SPICE Guidelines 2.0 (`[TAC.RL.1]`, `[SWE.3.RL.1]`) · ASPICE 4.0 information item 13-51
