---
spec: ../../specs/spec-tap-known-dupes.md
audience: [developer, llm]
covers:
  - ../../specs/spec-tap-known-dupes.md
  - ../../specs/spec-cicd-ai-review.md
update-triggers:
  - A decision is made on any option below — record it and mark the option chosen/rejected
  - A reviewer vendor ships named duplication detection, or a seated reviewer adds repo indexing
  - GitClear publishes a new annual report (the duplication trend numbers here go stale yearly)
  - The duplicates-session backlog (18 findings) closes out — re-measure and re-assess
assumes:
  - The duplicates session's findings and the TAP-KNOWN-DUPE convention (landed on main 2026-08-11/12)
  - The AI-reviewer ensemble plan (doc-cicd-ai-review-plan.md) is the adjacent, security-framed wave
provides: |
  Research synthesis and options analysis for defending against AI-authored code duplication and
  capability re-implementation. Covers the empirical evidence on how AI duplication actually
  behaves, why standard duplication tooling misses it, what AI reviewers can and cannot do here
  (with vendor-by-vendor findings), and a layered set of candidate controls ranked by
  leverage-per-effort. PRE-DECISION — options, not commitments.
---

# Duplication Defense — Research Synthesis and Options

**Status: pre-decision.** Written 2026-08-12 from a three-agent research sweep (duplicates-session
findings; AI-reviewer duplication capability; root-cause prevention practice). Nothing here is
decided. The purpose is to put the evidence and the option space on the table.

Companion: [doc-cicd-ai-review-plan.md](doc-cicd-ai-review-plan.md) — the same reviewer stack seen
through the security lens. This doc is the code-quality lens on the same machinery, and the two
must stay consistent about what the reviewers are and are not asked to do.

*(Note: `specs/spec-tap-known-dupes.md` and `tap/guards/known_dupes.py` landed on main after the
sam-dev worktree branched; paths above resolve on main.)*

---

## 1. The observed failure mode is not the one the industry writes about

The duplicates session produced 18 findings (9 fact-derivation, 9 code-clone), 6 of them on
security surfaces, concentrated in `tap/` bootstrap-secrets, `tap_auth/`, and `tap_grid/` read
paths. The pattern worth building around is this one:

**Four separate sites carry a docstring in which the AI author admits the duplication while
committing it:**

| Site | Admission |
| --- | --- |
| `tap/plugin_testing.py` | *"Mirrors tap.settings"* |
| `tap_auth/actors.py` | *"mirrors tap_auth.sync"* |
| `tap/boot_pointer.py` | *"identical contract to tap.plugin_source_auth"* |
| `tap_auth/credential_bind_coverage.py` | *"mirrors the authz scanner"* |

This inverts the standard diagnosis. The industry framing — and most of the tooling built around
it — assumes the agent *didn't know* the capability existed. Here the agent found the original,
understood it was duplicating, wrote the fact down in a durable comment, and shipped anyway.

The consequence for control design is direct: **discovery-side investment (repo maps, RAG,
capability catalogs, better skills) addresses a case that is not the observed one.** The observed
case needs a *forcing function* at authoring time, and a reviewer that treats "mirrors X" as a
defect signal rather than helpful documentation.

Secondary root causes the session named, all consistent with that reading:

- **No durable "persisted-actual" state** — in-process registries grew as caches of "what loaded,"
  so each consumer re-derived from whichever source was nearest.
- **Assumed import boundaries that don't exist** — the "must be stdlib-minimal" rationale for one
  duplicate was disproven by an existing import of the very module it claimed it couldn't touch.
- **Helpers too small to feel worth a home** — except several were *identity* or *authorization*
  formats (`scope:key` feeding a uuid5 collector identity), not display strings.
- **Unfinished consolidations** — two findings are the un-migrated edges of a shared substrate
  (`ScopeStackVisitor`) that was built specifically to kill per-scanner copy-paste.

---

## 2. What the empirical evidence says (and why it changes tool selection)

### AI duplication is semantic, not textual

Two 2026 studies appear to contradict each other and resolve into one finding:

- [**A Large-Scale Empirical Study of AI-Generated Code**](https://arxiv.org/html/2603.27130v2) —
  19,816 AI files vs 36,467 matched human files. AI code has *less* textual duplication:
  duplicated lines **18.69% (AI) vs 25.89% (human)**; cross-file duplication **17.20% vs 24.52%**.
- [**More Code, Less Reuse**](https://arxiv.org/abs/2601.21276) (MSR '26) — 3,858 Python PRs,
  CodeSage-Large embeddings targeting Type-4 (semantic) clones. AI redundancy **0.2867 vs human
  0.1532 — 1.87x higher, p<0.001**.

Both hold. **AI does not copy your text; it re-derives your logic in different words.** The first
paper's own reading of its low number: human cross-file duplication reflects *systematic reuse*,
whereas "AI-generated code is more often produced independently for each task." Low textual
duplication is here a *symptom of non-reuse*, not evidence of good factoring.

Two corollaries that matter operationally:

- MSR '26 found **LOC and cyclomatic complexity statistically indistinguishable** between AI and
  human PRs. Redundancy was the only differentiator. **Line-count and complexity ratchets are blind
  to this.**
- The same paper found reviewers expressed **more neutral/positive sentiment toward AI PRs** —
  less anger, disgust, surprise. "Surface-level plausibility of AI code masks redundancy, leading
  to the silent accumulation of technical debt." For a solo maintainer there is no second reader to
  correct that bias — the strongest available argument for *mechanical* over *discipline-based*
  controls.

### The clone-type taxonomy is the whole tool-selection axis

| Type | Definition | Detected by |
| --- | --- | --- |
| **Type-1** | identical modulo whitespace/comments | jscpd, PMD CPD, Sonar |
| **Type-2** | identical structure, renamed identifiers | Sonar, PMD (Java/C++ only — **not Python**) |
| **Type-3** | near-miss; statements added/removed/reordered | `similarity-py` (TSED), NiCad |
| **Type-4** | semantically equivalent, syntactically unrelated | **nothing production-grade** |

The best research Type-4 detector ([Oreo](https://arxiv.org/pdf/1806.05837)) tops out at **0.49
average recall** — that is the honest ceiling. TAP's mix spans the range: the fact-derivation
findings are Type-4; several clone findings (`_read_json`, `_ASKPASS_SCRIPT`, the AST-identical
serializers) are Type-1/2 and *are* catchable cheaply.

### Trend data (GitClear, 623M changed lines, 2023–2026)

[The Maintainability Gap 2026](https://www.gitclear.com/the_ai_code_quality_maintainability_gap):
block duplication **40.3 → 73.0** per M changed lines (+81%, highest on record); copy/paste share
**9.4% (2022) → 15.7% (2026 H1)**; **moved (refactored) lines 21% → 3.8%**; **cross-file function
calls 343 → 223 per 1k changed lines (−35%)**; legacy maintenance **−74%**.

The −35% cross-file-call number is the money stat: new AI code increasingly stands isolated rather
than wiring into what exists. The −74% legacy-maintenance and 3.8% moved-lines numbers say
something structural: **opportunistic in-passing cleanup is near-extinct.** A boy-scout rule that
depends on a human noticing while passing through does not survive when the agent is the one
passing through.

*Caveats carried honestly: GitClear sells code-quality tooling; it measures within-commit
duplication only (under-counts); its headline "4x growth in clones" is not supported by its own
published percentages (12.3%/8.3% ≈ 1.48x) — cite the underlying figures, not the multiple.*

---

## 3. What AI reviewers can and cannot do here

The single most important vendor finding: **duplication detection is white space in this market.**
Of 13 tools examined, exactly one ships it as a named, documented review agent.

### CodeRabbit does not index your repository — by design

Per [its own docs](https://docs.coderabbit.ai/integrations/knowledge-base), the knowledge base
draws on past PRs, linked issues, guideline files, and web search — **not code**. There is no
repository-indexing or embeddings page. Instead each review clones the repo into a throwaway
microVM where the agent greps and runs ast-grep queries. Their stated rationale:

> "A pre-built index goes stale the moment the repo moves, and similarity search surfaces code that
> *looks like* the change while missing the code that structurally *depends on* it."

That is a deliberate move *away from* the exact retrieval mode that finds duplication. Similarity
search is the right primitive for "does this already exist"; dependency structure is the right
primitive for "what breaks." CodeRabbit chose the latter. Its Code Graph Analysis is a
dependency/call graph — it cannot cluster functions by behavior. And **none of its 50+ bundled
tools is a clone detector** (no jscpd, no PMD-CPD, no Simian; PMD is present for linting only).

**Conclusion: CodeRabbit is the weakest reviewer surveyed for this specific job** — and it was
subsequently **rejected from the roster entirely** (2026-08-13, on `contents: write`; see
[doc-cicd-reviewer-rollout-plan.md](doc-cicd-reviewer-rollout-plan.md)). The analysis is kept
because the *finding* generalizes — reviewers that clone-and-grep instead of indexing cannot do
this job, which is true of the seated roster too. The knobs below no longer apply to TAP:

| Knob | Why |
| --- | --- |
| `reviews.pre_merge_checks.custom_checks` | 10,000 chars of instructions; `mode: error` actually **blocks** — the only gate-shaped knob in the product |
| `reviews.path_instructions` | 20,000 chars, glob-scoped — e.g. stricter reuse rules on `tap_grid/**` |
| `knowledge_base.code_guidelines` | Auto-reads `CLAUDE.md`/`AGENTS.md` with **zero config** — TAP's CLAUDE.md is already feeding it |
| `knowledge_base.learnings` | Replying "we already have this in `tap_grid/services`" compounds into a durable learning — the one mechanism that improves with use |

### Claude Code already ships a `reuse` finding category

The strongest finding in the reviewer research: `/code-review` reports "correctness bugs **and
reuse**, simplification, and efficiency cleanups," and the shipped review prompt confirms `reuse`
is a real structured finding category with dedicated cleanup angles in its fan-out.

**The operational catch, verbatim from that prompt:** *"Correctness bugs always outrank cleanup,
altitude, and conventions findings when the output cap forces a cut."* Reuse findings are the first
thing dropped on a large PR. Mitigations: run at `high`/`max` effort, or run **`/simplify`**, which
is cleanup-only and therefore has no correctness findings to crowd it out.

Two gaps worth knowing: Anthropic's own `pr-review-comprehensive.yml` example has five focus areas
(quality, security, performance, testing, docs) — **no reuse area**; and the official `code-review`
plugin fans out five agents, none of which asks "does this already exist," with a false-positive
filter that drops general quality issues *"unless explicitly required in CLAUDE.md."* **Both
reference prompts would miss re-implementation unless CLAUDE.md names reuse explicitly.**

### `REVIEW.md` is the highest-leverage config surface

The managed Claude Code Review product reads `CLAUDE.md` (violations flagged as **nits** — lowest
severity) and `REVIEW.md`, which is *"injected into the system prompt of every agent in the review
pipeline as the highest-priority instruction block."* The docs explicitly support escalating
CLAUDE.md violations from nit to Important, and setting a **verification bar** (e.g. "behavior
claims need a `file:line` citation, not an inference from naming").

A reuse rule in `REVIEW.md`, promoted to Important, requiring a `file:line` citation of the
existing implementation, is the single highest-leverage configuration change available. The
citation requirement is what converts "this looks duplicated" into a falsifiable finding and kills
the hallucinated-helper failure mode. *(Note: local `/code-review` does not read `REVIEW.md` —
only `CLAUDE.md`. Put reuse guidance in both.)*

### Cross-model review is measurably better — new grounds for the multi-vendor stack

[Greptile's model-inversion data](https://www.greptile.com/blog/model-inversion): **models are
worse at reviewing their own output.** Claude reviewing Claude: **53.7% recall**; Claude reviewing
GPT: **62.0%**. GPT on GPT: 50.5%; GPT on Claude: 60.0%.

TAP is ~95% Claude-authored, so a Claude-only reviewer runs in its weakest configuration. This is
an independent, quantitative justification for the multi-vendor stack planned on security grounds
(now Copilot + Codex, with the non-Anthropic seat carrying the weight) — **~8 points of recall, not coverage hand-waving.**

### The one vendor that ships this by name

**Baz** (baz.ai) ships `code-dedup-and-conventions`: *"Detects duplicated logic and enforces
existing team patterns and conventions… Encourages reuse and clearer abstractions."* It indexes
with **embeddings in a vector DB for similarity search** (Voyage AI code models) — the right
primitive. Its plugin also **fails closed**: if it can't reach the index it *"stops, names the
symbols whose consumers it couldn't check, and withholds the merge verdict rather than implying
coverage it doesn't have"* — a posture worth stealing regardless of vendor. $30/active dev.

Caveats: every published example is small-grain (a duplicated fixture, a duplicated dataclass), and
their own guidance says to avoid large architectural suggestions — so TAP's "rebuilt a subsystem"
case is **unproven, not disproven**. Community footprint is near-zero (1,119 installs; zero HN
hits).

### Corrections to common priors

- **Qodo's `/find_similar_component` is retired** (docs 301-redirect; absent from Qodo 2.0).
- **Cursor Bugbot's duplication claim is misattributed** — it belongs to Cursor the IDE, not the PR bot.
- **"Graphite Diamond" no longer exists** (renamed Graphite Agent; Graphite acquired by Cursor Dec 2025); two hostile benchmarks put its recall at 6–7.5%.
- **Greptile** has the best-shaped architecture (embeds generated docstrings, not code) but **zero duplication rules in its docs**, poor user reports, and documented billing disputes with OSS-approved maintainers.
- **Sourcegraph has no PR reviewer** (Cody Free/Pro discontinued 2025; the review action archived Feb 2026).
- **Marketing-vs-docs drift is the dominant failure mode in this category.** Panto's "scans the entire repository" appears only in a blog, contradicted by its own docs, its zero-retention guarantee, *and* its own showcase PR. **Read the docs, not the landing page.**

### The negative result that frames everything

Targeted searches for any user report of any tool catching a real re-implementation returned
**zero hits**. Practitioners name the gap precisely — *"exact duplicate code is already pointed out
by Sonar; [reviewers are still needed for] detecting duplicate functionality"* — and one plausible
explanation for why no vendor ships it: *"the token costs to load that state for every PR make the
margins impossible right now."*

---

## 4. The counter-argument to buying a reviewer for this

The most rigorous 2026 practitioner source on AI-generated-code guardrails
([Codesai, April 2026](https://codesai.com/posts/2026/04/minimal-architecture-constrainsts-in-agentic-world))
evaluated three options and **explicitly rejected agent review** for this class of problem:

- **Documentation / agent skills** — "probabilistic, context-heavy, susceptible to drift"
- **Agent reviews** — "non-deterministic, expensive (double token cost), unreliable"
- **Linters** — "equally effective but less readable than tests"

They chose deterministic architecture *tests* — "deterministic, cost-effective, zero token cost,
instant local feedback" — enforcing exactly three rules. Stated motive: **reviewer cognitive
fatigue under high AI-generated volume.**

[Martin Fowler's harness-engineering framing](https://martinfowler.com/articles/harness-engineering.html)
reconciles this with the pro-reviewer camp: controls split into **computational** (deterministic,
fast, cheap: linters, type checkers, structural analysis, tests) and **inferential** (semantic,
slow, probabilistic: AI review, LLM judges). Distribute cheap checks early, expensive checks late.

**Applied here: reviewers are the second layer, not the root-cause fix.** They are worth having —
the reuse category is real, cross-model review measurably helps — but the load-bearing controls for
this failure mode are deterministic and live in the repo.

One more piece of guidance worth carrying, from the
[Architecture Fitness Function pattern](https://aipatternbook.com/architecture-fitness-function):
**include the fitness functions in the verification commands the agent runs after changes**, not
just in CI. Otherwise the agent only learns it was wrong after a human runs CI, by which point
dependent changes have accumulated. That is what turns a fitness function from a *gate* into a
*guide*.

---

## 5. Why the discovery layer needs a forcing function

Two measured findings that should govern any investment in discoverability:

- **[CodeCompass](https://arxiv.org/abs/2602.20048)** (258 trials, production FastAPI repo):
  **58% of trials with code-graph access made zero tool calls.** The authors: *"the bottleneck
  isn't capability but behavioral alignment. Agents required explicit prompt engineering to
  consistently leverage structural context over lexical heuristics."*
- **[Evaluating AGENTS.md](https://arxiv.org/html/2602.11988v1)** (138 instances, 12 Python repos,
  4 agents): tools **named** in the context file were used **1.6x per instance vs <0.01x when
  unnamed** — a ~160x swing. Developer-written context files gave **+4%** task success;
  LLM-generated ones **−2%**; both cost **+20%** more. **Directory maps and structural overviews
  "do not meaningfully reduce" time to find relevant files** — generated `ARCHITECTURE.md` is
  measured *not* to help.

Combined: **name the discovery surface explicitly, then make the step deterministic rather than
advisory.** A registry nobody queries does not exist.

This matters for TAP because the discovery surface already exists (service-layer discovery
registry, capability registries, typed skills) — but is inconsistently pointed at. Of the authoring
skills (`add-model`, `add-edge`, `build-collector`, `new-plugin`, `add-page`, `add-panel`,
`build-gryphon-capability`), only **two** carry a "check what already exists first" step.
`add-panel` is the exemplar — it asks *"Standard or custom? Could this be one of the tap_web
standard panel types? If yes, prefer that"* and points at the standard-panels spec before
authoring. The others go straight to "here's how to build one."

Anthropic's own best-practices doc contains nearly the exact prompt needed, and the subagent
framing is right because discovery is context-**expensive** (reads many files) while its output is
**small** (a list of what exists):

> "Use subagents to investigate how our authentication system handles token refresh, **and whether
> we have any existing OAuth utilities I should reuse.**"

And their forcing-function ladder, which is what the 58% finding demands you climb:

| Mechanism | Nature |
| --- | --- |
| CLAUDE.md instruction | **Advisory** (Anthropic's own word) |
| Skill | Model-invoked, on-demand, still discretionary |
| `/goal` condition | Re-evaluated by a separate evaluator each turn |
| **Stop / PreToolUse hook** | **Deterministic** — blocks the turn or the write |

> "Use hooks for actions that must happen every time with zero exceptions. Unlike CLAUDE.md
> instructions which are advisory, hooks are deterministic and guarantee the action happens."

**"Did you search for an existing implementation?" is a hook, not a paragraph.**

The best published prompt template is a real shipping skill in Google's own repo —
`google-gemini/gemini-cli`, `.gemini/skills/review-duplication/SKILL.md`. Its two load-bearing
steps are directly portable: **a hardcoded "where would this live" map** (which makes the search
tractable instead of a blind repo-wide sweep — TAP has this map: `tap_grid` services, `tap/`, the
plugin layout) and **a requirement that findings cite the file path and symbol** of the existing
implementation.

---

## 6. Candidate controls, ranked by leverage-per-effort

Pre-decision. Each is an option, not a commitment.

### Tier A — cheap, deterministic, matched to the *observed* failure mode

1. **The "mirrors X" admission guard.** A guard that flags docstrings/comments containing admission
   phrases (`mirrors`, `identical contract to`, `same as`, `copy of`, `duplicates`) unless the site
   carries a `TAP-KNOWN-DUPE(<id>)` tag. Catches TAP's *actual, observed, four-times-repeated*
   failure mode; near-zero false positives; plugs into the existing distributed guard harness. **No
   industry precedent — this is TAP-specific and comes straight from the corpus.**
2. **Persist the AST-hash clone detector the session already built.** The clone sweep used
   normalized AST-body SHA1 (docstrings stripped, 5+ statement lines) across 442 first-party files
   and found 9 real clones — then was thrown away. TAP has a ratchet harness with 14 ratchets
   already. This is Type-1/2 detection, deterministic, and already proven on this codebase.

   **Known blind spot, measured 2026-08-12:** that sweep hashed *function bodies* and compared
   *function names*, so **module-scope derivations were invisible to it**. It missed `REPO_ROOT`
   being derived five independent times in `tap/` (ledger finding H10) — arguably the purest
   instance of the anti-pattern in the tree — because a bare module-level constant assignment is
   neither a def nor a body. Any detector built from that sweep must scan module-scope assignments
   as a first-class case, not only `FunctionDef` nodes. A general lesson for detector selection:
   *the unit the detector hashes silently defines the class of duplication it can never see.*
3. **Registry raises on duplicate key.** The highest value-per-character control in the research:
   convert capability re-implementation from silent last-writer-wins into a boot failure. Composes
   with TAP's fail-closed posture. Related: entry-point name collisions are **not** detected by
   Python packaging — a boot-time collision check is ~10 lines and directly relevant to a plugin
   system.
4. **Reuse clause in CLAUDE.md + `REVIEW.md`.** The only way an instruction-driven reviewer surfaces
   duplication at all. Cheap — Copilot reads `.github/copilot-instructions.md` and Codex reads its
   workflow prompt, so the clause lands in both without a new file.

### Tier B — structural enforcement (deterministic, moderate effort)

5. **import-linter.** TAP's standing "avoid `tap_*` app interdependencies; push shared mechanics
   *down*, never sideways" rule is *literally* a layers contract plus independence contracts —
   currently enforced by discipline alone. v2.13 (Jul 2026), production/stable. Use
   `unmatched_ignore_imports_alerting = "error"` so the exception list can't rot. **Known limit:**
   it is a static import-graph tool — a plugin system's dynamic loading is exactly what it
   under-reports.
6. **Positive obligations ("required" rules).** dependency-cruiser has them; no Python tool does.
   *"Every module matching `plugins/*/collectors/*.py` must import `CollectorBase`"* is ~20 lines of
   AST walking and directly attacks re-implementation — a new collector bypassing the canonical base
   fails CI.
7. **Single-implementation guards, run both ways.** Static (AST: classes whose bases resolve to the
   canonical ABC must match a frozen allowlist) **and** runtime (`__subclasses__()` equals an
   expected set). Static catches a parallel file; runtime catches aliasing the base to dodge the
   static check. This is the same "guards check local structure, not interprocedural preconditions"
   trap TAP already learned once.
8. **ruff TID251 banned-api** for "use the wrapper, not the raw thing." Already in TAP's ruff, zero
   new tooling. **Hole to know:** [re-exports are not detected](https://github.com/astral-sh/ruff/issues/16692)
   — an `__init__.py` re-export launders the banned symbol past the rule.
9. **Semgrep custom rules** where the thing to ban is a *call shape* rather than an import (e.g.
   ORM `.objects.create/update/delete` outside migrations and `_impl` modules). Semgrep **cannot**
   express "this reimplements X" — but it converts "find unknown duplication" into "forbid known
   reimplementation," and TAP already has the list of invariants written.

### Tier C — reviewers (inferential, ongoing cost)

10. **`/simplify` or `/code-review high`** on PRs, chosen deliberately over the default because
    reuse findings are the first cut under the output cap.
11. **A TAP `review-duplication` skill** modeled on the gemini-cli one, with the "where would this
    live" map filled in with TAP's actual layout, delegating to subagents across four search
    vectors (structural similarity, naming conventions, comments/docs, architectural fit) and
    requiring `file:path` + symbol in every finding.
12. ~~**CodeRabbit `pre_merge_checks.custom_checks`**~~ — **dead option** as of 2026-08-13:
    CodeRabbit is off the roster. The gate-shaped equivalent on the current roster is a reuse rule
    in the Codex prompt feeding the planned `ai-review` aggregator.
13. ~~**Trial Baz**~~ — **blocked on permissions** as of 2026-08-13: `baz-app` requests
    `contents: write`, which `req-cicd-ai-review-ensemble-4` rejects outright. It remains the only
    vendor shipping duplication detection by name and fails closed correctly, so it is the standing
    reopen candidate the day that grant narrows — verify with `gh api /apps/baz-app`.

### Tier D — cadence and measurement

14. **A scheduled duplicate-detector agent.** GitHub's published pattern
    ([Continuous Simplicity](https://github.github.com/gh-aw/blog/2026-01-13-meet-the-workflows-continuous-simplicity/))
    runs daily, scoped to **recently-changed code**, files issues only for duplication spanning
    **>10 lines or appearing in ≥3 locations**, and **caps output at 3 issues per run** "to prevent
    overwhelming developers." Merge rates 79–83%. **All three design decisions are worth stealing
    wholesale** — without the cap, a dedupe agent on a large AI-authored codebase buries you on day
    one. This is also the replacement for the dead boy-scout rule.
15. **Measure it.** GitClear's two best metrics — **percentage of moved/refactored lines** and
    **cross-file function calls per 1k changed lines** — are computable from TAP's own git history,
    against a ~95% AI-authored baseline. Nobody has published solo-maintainer data on whether *any*
    discoverability or review layer reduces duplicate implementations; every existing study measures
    task success, tokens, tool calls, or retrieval accuracy. TAP could have the first real numbers.

---

## 6b. Tested and rejected: RID-reference timing as a duplication signal

**Hypothesis (George, 2026-08-12):** because a capability should be implemented once, there should
be a small time delta between a RID being authored in a spec and referenced in code; a large delta
or a late second cluster of references would indicate re-implementation. RIDs are deterministic
strings, so this would be a very cheap shortcut versus semantic clone detection.

**Verdict: fails, for structural reasons that generalize beyond the sample.** Tested against 15
multi-site duplicate groups (43 sites) over 1,392 commits, with a control baseline of 475
code-cited RIDs.

| Finding | Number |
| --- | --- |
| RIDs authored in specs | 1,493 (**only 475 = 32% ever cited in code**) |
| Spec-birth → first code reference, same day | **75%**; same *commit* **40%** |
| Duplicate groups whose two sites were born the same day | **8 of 15** (4 in the *same commit*) |
| Median intro span across duplicate groups | **2.9 days** |
| Median gap between *legitimate* repeat references to one RID | 2.0 days (p75 = **38 days**) |
| Duplicate groups where both sites cite the same RID locally (±25 lines) | **2 of 15** |

Three independent reasons it cannot work:

1. **No dynamic range.** TAP authors spec and implementation together — 75% same day, 40% same
   commit. The birth→first-reference axis has almost nothing to detect an anomaly *in*.
2. **The signal points the wrong way.** Clones are a **simultaneity** phenomenon, not a latency
   one: they are copy-pasted within a single authoring sitting. Every duplicate sits at or below
   the 68th percentile of legitimate later references — the duplicates occupy the *early* end.
   A pure temporal rule (span > 14d) flags 78 RIDs and catches **zero** known duplicates.
3. **RID citations are narrative, not ownership.** Of 1,919 RID mentions in `.py` files, **71% are
   in docstrings, 28% in comments, 1% in code identifiers**; median 2 distinct RIDs per citing
   file (max 93). Citing a RID means "related to," not "is." A many-to-many explanatory relation
   cannot serve as a fingerprint — a structural property of the convention, not a sampling
   accident.

The structural variant (same RID in two files that don't import each other) also fails: **~2%
precision at 13% recall**, and its logic is **inverted** — the *fixes* created the co-citation that
didn't exist before (the D1 collapse minted `req-grid-table-classification.sec`, now cited in exactly
the two files that share the collapsed source). **RID co-citation marks a correctly-collapsed
single source, not a duplicate.**

Also worth recording: the predicted false-positive class was wrong. Security/logging/doctrine RIDs
(`req-sec-…`, `req-tap-logging-*`) are **small and tight** (median 2–3 files, 0-day spans). The
real noise is the big architectural specs — `req-tap-auth-policy` alone spans 23 files and
generates 253 pairs; five RIDs generate 663 of 2,397 total pairs. A prefix exclusion built from
the predicted classes would exclude the wrong RIDs and keep all the real noise.

### What the analysis found instead

**Spec-level duplication is the real and more valuable signal.** Where duplicate sites cite
*different* RIDs, those requirements are themselves duplicates. Finding D1 (the HIGH-severity
grid-tables divergence) had two requirement families across three specs owned by three different
apps, each independently stating a fact about the same table set — and they had already diverged.
**The code divergence was licensed by the requirements.** Same shape in D3 and D5.

Measured: TF-IDF cosine over 1,027 RID prose sections, controlling for same-spec vocabulary
overlap. Cross-spec duplicate pairs land in the **top 0.5–1.6%** of all cross-spec pairs
(D3/S1 at 0.215 = 99.9th percentile; D1 at 0.120 = 99.5th). Real ranking signal; not a gate
(a 0.10 threshold surfaces ~5,000 pairs). Honest caveat: much of the cosine is topical ("both
about boot"), so it generates leads, not findings.

### Three things worth building instead

1. **An `IMPLEMENTS:` ownership tag — make the fingerprint exist by construction.** The entire
   failure traces to RIDs being narrative. Add one narrow tag meaning *ownership*, on the single
   function that IS the authoritative derivation of a requirement's fact:
   ```python
   def grid_table_names() -> frozenset[str]:
       """IMPLEMENTS: req-grid-table-classification.sec — the one derivation of 'which tables are grid tables'."""
   ```
   The guard is then trivial and near-100% precision: **two `IMPLEMENTS:` for the same RID in
   different modules, without a `TAP-KNOWN-DUPE(...)` tag, is a finding.** Exact complement to the
   shipped known-dupes guard, and the same shape as the `[<hex>]` log-site tokens and callsite
   ratchets — TAP has the muscle, the baseline machinery, and the review culture already. Ratchets
   in over the 475 code-cited RIDs rather than all 1,493. Cheap now, expensive to retrofit.
2. **A cross-spec requirement-similarity review queue** (~30 lines, no runtime cost): top-50
   cross-spec RID pairs by cosine, regenerated on spec edits, reviewed like a ratchet report. It
   found the highest-severity item in the inventory. Its output is directly actionable *in the
   canon* — the fix for spec-level duplication is a spec change.
3. **Use a code-clone detector for code clones.** RIDs contribute nothing there; the AST-hash
   approach already found the C-family.

**Bonus finding worth its own thread:** 1,018 of 1,493 RIDs (**68%**) never reach code at all, and
the two duplicate sites citing *zero* RIDs are the same file (`tap_grid/registry.py`, home of both
D7 and C8). A "spec'd but unimplemented / code with no spec anchor" report is a different and
probably higher-yield use of the same extraction pipeline.

*Limits: n=15 groups, one codebase, ~6 months, one primary author. Recall figures carry wide
intervals. The mechanism generalizes better than the numbers — 99%-prose citation and same-commit
clone birth are structural properties of the convention and the authoring mode.*

## 6c. Market sweep — tools beyond diff review (2026-08-12)

Swept for architecture-conformance, spec-conformance, test-quality, refactoring, code-health, and
multi-agent orchestration offerings, weighted toward OSS-free tiers (TAP's repos are public).

**Headline: the spec-conformance category has largely evaporated.** **Tessl** — the spec-driven
development company — has fully pivoted to agent-skills management; its complete docs index
contains **no page** on spec-driven development, spec files, spec registries, or spec-code drift,
and its "spec registry" is now a *skills* registry. **No commercial product verifies "does this
code do what this requirement says."** The market splits into deterministic traceability (does the
link exist) and LLM gap-analysis (does an agent think it's implemented), with nothing bridging
them. **This is the strategic opening for TAP** — see §6d.

**Short-list for TAP's profile** (solo, AI-authored, spec-rich, public repos, strong guard harness):

| Tool | Adds what a diff reviewer cannot | Cost |
| --- | --- | --- |
| **import-linter** (+ **Tach**) | A *proof* on every commit that layering holds. Custom contract types subclass `Contract` and receive the full Grimp import graph → bespoke invariants emit violation counts the ratchet harness already consumes. Tach adds **symbol-level `[[interfaces]]`** — the only way to express "the service layer is the only mutation path." Use `exhaustive = true` so a new app can't escape the model. | Free (BSD-2 / MIT) |
| **gh-aw multi-lens review** | The only route to a reviewer that knows what `req-fips-crypto-bom` means. **Graduated out of GitHub Next into the main GitHub org** (MIT, 4.9k stars). Agent job runs read-only; safe-outputs handlers execute privileged actions; threat-detection on by default. Its own `pr-code-quality-reviewer.md` is a working MIT coordinator with **KEEP/HARDEN/DROP** triage; `test-quality-sentinel.md` is a deterministic test rubric. Public-repo runners are free → cost is tokens only. **Pin above 0.71.3** (retired billing-bug releases). | ~$5–10/mo tokens |
| **Mutation testing** (`cosmic-ray`) | The honest answer to "do my AI-written tests test anything" — a surviving mutant *is* a test that passes on broken code. Deterministic, ratchetable, no vendor. Nightly/per-app, not per-PR. | Free (MIT) |
| **CodeScene Community** | **Change coupling** — detects apps that are *behaviourally* coupled because they co-change, even with no import between them. Exactly the sideways-dependency smell that survives a clean import-linter run; nothing else measures it. Code Health is the only metric here with peer-reviewed validation. | Free for OSS |
| **StrictDoc** | Implements almost exactly TAP's model already — see §6d. | Free (Apache-2.0) |

**Do NOT add another generic diff reviewer** (Greptile, Cursor Bugbot, Baz, Bito, Graphite):
marginal signal near zero over the seated reviewers; **all have moved to consumption billing
within ~a year**, and a 95%-AI-authored codebase is precisely the workload that model bills
hardest. Since 2026-08-13 there is a harder objection: **every one of them requests
`contents: write`**, which the roster rejects outright (`req-cicd-ai-review-ensemble-4`). Baz
(`baz-app`) included — so the duplication-detection recommendation below is blocked on permissions,
not on merit.

**Corrections to earlier notes in this doc:**
- **CodeRabbit OSS tier is two SKUs.** The *Free* plan is PR-summarization only; the separate
  *Open Source* plan grants **Pro+ features on unlimited public repos, no card, no application** —
  but reviews run on "a separate rate-limit tier that varies with the project's community and
  popularity": **1–10 PR reviews/hour, 100–300 files per review.** A newer project may land at the
  bottom of that band.
- **Greptile billing dispute: documented change, under-evidenced allegations.** The
  2026-03-05 move to $30/dev + 50 reviews then $1/review is fully documented and Wayback-bracketed;
  the OSS program is architecturally a **100%-off coupon on a billing account, not a free plan**
  (which fails differently — a coupon that doesn't cover a *new* line item still invoices), and
  credits are **charged to the PR author**, so drive-by contributors consume the maintainer's
  allowance. The billing-failure allegations are plausible and match the coupon architecture, but
  rest on one pseudonymous advocacy site (17 HN points, no invoices or screenshots).

**Vendor overclaiming found:** CodeScene's "6x more accurate than SonarQube" misattributes a number
that belongs to Microsoft's Maintainability Index, on one metric, against Sonar's worst config —
and in the same Java-only benchmark a naive "is this file >275 lines" rule **ties Code Health on
AUC**. "Kiro has native drift detection" is asserted by listicles (including one published by a
competitor) and is **absent from Kiro's own docs**. GitClear's research is the most *relevant* and
the least *auditable* (dataset size published; methodology, sampling and controls are not).

**The Cloudflare lesson worth internalizing:** the strongest form of confidence in this market is
not an LLM judge — it is **execution**. Cloudflare's coordinator reads source to verify uncertain
findings; Anthropic's ultrareview reproduces them; Greptile's sandbox runs the branch. Text-only
voting between agents is the weakest tier. **If TAP builds a reconciler, it must read the code
before keeping an uncertain finding.** Their production numbers: 131,246 reviews / 30 days, ~1.2
findings per review (deliberately low), median **$0.98/review**, 85.7% prompt-cache hit rate, 0.6%
break-glass. Notably they run an **AGENTS.md freshness reviewer** — a spec-drift lens in
production.

## 6d. The spec-conformance opening

Three findings from the sweep converge on the same conclusion: **the review dimension TAP is
uniquely positioned for is the one the market abandoned.**

- **StrictDoc already designed the tag.** Its source traceability uses in-code markers —
  `@relation(REQ-1, scope=function)` with scopes `file` / `class` / `function` /
  `range_start`–`range_end` / `line`, enabled by
  `project_features=['REQUIREMENT_TO_SOURCE_TRACEABILITY']`. That is the `IMPLEMENTS:` proposal,
  already built and Apache-2.0. **Recommendation is not to migrate** (moving an existing spec
  corpus to `.sdoc` is a large low-reward change) but to steal its two deterministic checks: every
  `req-*` cited in code exists in a spec, and every requirement has ≥1 implementing citation.
- **Spec Kit's `/speckit.converge` supplies the output contract.** Widely miscovered:
  `/speckit.analyze` never touches code (it is a cross-document audit of spec/plan/tasks against
  each other). `converge` is the code-facing one, classifying each requirement's gap as
  **`missing`** (absent from code entirely), **`partial`** (exists but does not fully satisfy), or
  **`contradicts`** (code conflicts with stated intent), with CRITICAL/HIGH/MEDIUM/LOW severity.
  That three-way taxonomy is the reusable artifact — adopt it as the output shape of a TAP
  spec-conformance lens. (No CI mode is documented; it assumes the spec/plan/tasks triple.)
- **A 2026 position paper describes TAP's architecture.** [The Spec Growth Engine
  (arXiv 2606.27045)](https://arxiv.org/abs/2606.27045) proposes a machine-readable spec graph with
  contract/design separation, a context assembler scoping agents to an ownership path, and **a
  drift gate making spec-code divergence a blocking merge condition.** No implementation published.
  Useful as design validation and as a citable defense of the approach.

**Also worth a look for TAP specifically:** [CrossHair](https://github.com/pschanely/CrossHair) —
symbolic execution + SMT solver finding counterexamples to Python contracts. The only tool found
that *actually proves* code matches a spec. Narrow (function-level contracts), but a real fit for
the Gryphon executor's null-semantics invariants, which are already expressed as precise rules.

**And the meta-strategy worth stealing from Tessl's remaining good idea:** mine your own PR-review
history for *recurring agent mistakes*, then convert each into a rule (always-on instruction), a
skill (procedural workflow), a verifier (structural check), or a refactor plus enforcement rule.
For a 95%-agent-authored codebase, "make each repeated mistake structurally impossible" is the
right compounding loop, and it runs as a scheduled gh-aw workflow.

## 7. Open questions for the discussion

- **How much of Tier A/B before any Tier C?** The evidence says deterministic controls carry this
  class and reviewers are the second layer — but reviewers are already being adopted for security
  reasons, so their marginal cost here is a config change, not a new vendor.
- **Does the `TAP-KNOWN-DUPE` convention need an enforcement partner?** Today it validates tags that
  exist (≥2 sites, ≥1 spec mention). Nothing forces an *untagged* duplicate to acquire a tag. The
  admission guard (A1) and the AST-hash ratchet (A2) are the two candidate partners.
- **Is a hook too aggressive?** The forcing-function ladder says hooks are the only deterministic
  rung, but a PreToolUse hook on every write would be heavy-handed. A Stop hook that checks whether
  a search happened before new-file creation is the lighter variant.
- **Skills consistency:** should the five authoring skills lacking a "check what exists" step get
  one, modeled on `add-panel`? Cheap, but per the AGENTS.md evidence, skills remain *discretionary*
  — this improves the odds without guaranteeing the behavior.
- **Backlog sequencing:** 14 of the 18 duplicates findings remain open, several on security
  surfaces (S1 askpass/token duplication, S2 passkey origin, S3 `_read_json`). Do those close first
  as individual collapse PRs (the session's recommendation, one at a time, discussed first), or does
  the tooling land first so the closures are verified by it?

---

## Key sources

**Empirical:** [GitClear Maintainability Gap 2026](https://www.gitclear.com/the_ai_code_quality_maintainability_gap) · [More Code, Less Reuse (MSR '26)](https://arxiv.org/abs/2601.21276) · [Large-Scale Empirical Study of AI-Generated Code](https://arxiv.org/html/2603.27130v2) · [Code Copycat Conundrum](https://arxiv.org/abs/2504.12608) · [Oreo (Type-4 ceiling)](https://arxiv.org/pdf/1806.05837)

**Discoverability + forcing functions:** [CodeCompass](https://arxiv.org/abs/2602.20048) · [Evaluating AGENTS.md](https://arxiv.org/html/2602.11988v1) · [Claude Code best practices](https://code.claude.com/docs/en/best-practices) · [gemini-cli review-duplication skill](https://github.com/google-gemini/gemini-cli)

**Enforcement:** [Codesai architectural guardrails](https://codesai.com/posts/2026/04/minimal-architecture-constrainsts-in-agentic-world) · [Harness Engineering](https://martinfowler.com/articles/harness-engineering.html) · [Architecture Fitness Function](https://aipatternbook.com/architecture-fitness-function) · [import-linter contracts](https://import-linter.readthedocs.io/en/stable/contract_types/) · [ruff TID251](https://docs.astral.sh/ruff/rules/banned-api/) · [ArchUnit FreezingArchRule](https://deepwiki.com/TNG/ArchUnit/2.3.2-freezing-architecture-rules)

**Reviewers:** [CodeRabbit knowledge base](https://docs.coderabbit.ai/integrations/knowledge-base) · [CodeRabbit configuration](https://docs.coderabbit.ai/reference/configuration) · [Claude Code review](https://code.claude.com/docs/en/code-review) · [Baz agents](https://baz.ai/docs/agents/baz-agents) · [Greptile model inversion](https://www.greptile.com/blog/model-inversion) · [GitHub: reviewing agent PRs](https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/) · [GitHub Continuous Simplicity](https://github.github.com/gh-aw/blog/2026-01-13-meet-the-workflows-continuous-simplicity/)
