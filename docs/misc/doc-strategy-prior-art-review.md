---
spec: ../../plan/road-products.md
audience: [developer, llm]
covers:
  - ../../plan/road-products.md
  - ../../plan/product-map.md
  - ../../CONTRIBUTING.md
  - ../../GOVERNANCE.md
assumes:
  - Reader knows the 2026-08-25 strategy overhaul — road-products.md, product-map.md, and the Unified Systems board.
update-triggers:
  - A recommendation below is acted on — strike it here and record the decision in the owning doc
  - A cited study is superseded, or a claim marked "unevidenced" gains evidence
  - The first external contributor arrives — several findings here are predicated on there being none
---

# Prior-art review: our strategy and tactical system, judged against post-AI open source

**Date:** 2026-08-25. **Question asked:** how does what we have built hold up against best
practice for open source, adjusted for solo development in the post-AI world — measured against
projects that are alive and above water now, not against the governance canon of large
foundations.

**Method.** Four parallel research passes: post-LLM solo/small-team OSS practice; new maintainer
problems created by AI; agent-legibility conventions; and which of the traditional governance
canon is load-bearing versus ceremonial at n=1. Findings below carry their evidence quality
explicitly, because a substantial fraction of what circulates as open-source best practice turns
out to be folklore, and some of it is measurably wrong.

---

## The verdict in one paragraph

We are unusually strong where the field is weak — machine enforcement, agent-legible surfaces,
and written rationale — and weak in the two places that most often kill projects at our exact
stage: **discoverability** and **succession**. The process apparatus is not over-built for one
person, which was the obvious critique and does not survive contact with the evidence; but it is
**fragmented**, and fragmentation is the dominant documented barrier for newcomers. The single
largest strategic finding is not a gap in our practice at all: there is no machine-readable
convention anywhere for a project's roadmap, status, or capabilities, and that unclaimed space
sits directly adjacent to what TAP is for.

---

## What we are doing right

### Enforcement over exhortation

The strongest single result across the agent-legibility literature: **instruction files are
suggestion; hooks and CI are enforcement.** A factorial study over 1,650 Claude Code sessions
(16,050 observations) found *no* detectable effect from any structural property of instruction
files — size, ordering, architecture sections, internal contradictions — with affirmative-null
Bayes factors for several. What it did find is **within-session compliance decay of roughly 5.6%
per additional unit of work generated**, replicated across two codebases and two models.

Our 41 guards, the ratchets, the conformance gate, and the required status checks are the layer
that survives that decay. This is the most valuable thing we have built and it is rare: an
analysis of 2,303 real context files found only **14.8% encode any security constraint** and
14.5% any performance constraint. The field optimized for making agents *functional*, not safe.

*Observed in this very session:* the "don't build anything yet" instruction was violated twice,
both times late in a long session, both times recovered only because a human intervened. That is
the decay curve, not a character flaw, and it is the argument for machine enforcement stated in
miniature.

### Publishing intentions, not dates

Removing dates from the roadmap and pushing them to milestones — done hours before this review —
lands exactly on the reference pattern. Rust's own postmortem retiring its annual roadmap RFCs
(RFC 3614) names three causes of failure: goals with no assigned owner, no mechanism for tracking
progress, and **no owner for the roadmap's own upkeep**. Our split addresses the second and third
directly: the board tracks progress, and the roadmap no longer contains a decaying fact that must
be hand-maintained.

curl's `docs/ROADMAP.md` is the solo reference implementation: 17 lines, explicitly
non-binding, personally owned.

### Skills as a product surface

Shipping skills is the genuine 2026 convention, and we are early rather than late. The format was
released as an open standard in December 2025; 40+ clients support it, and 649 official skills
from 54 vendor teams now exist — Microsoft, Google, Stripe, Supabase, Cloudflare, MongoDB,
Datadog. The load-bearing mechanic is **progressive disclosure**: ~100 tokens per skill at
discovery, full body only on activation. That is the answer to the context-cost problem that sinks
both instruction-file bloat and large MCP tool surfaces.

In a controlled evaluation (500 trials, 25 tasks × 4 difficulty tiers), a skill matched an MCP
server on correctness (0.833 vs 0.834) at **one tenth the cost and one fifth the latency**, and
MCP tool-fidelity collapsed to 0.33 on the hardest tier — agents abandoned the server and fell
back to bash.

The git-serious plan to ship an AI install-and-config skill set is therefore not a novelty; it is
the convention the serious vendors converged on. **Laravel Boost is the model worth stealing**:
its installer detects which packages an application actually uses and assembles only the relevant
guidelines, and third-party packages can ship their own guidelines that get picked up
automatically. That maps onto the TAP plugin model almost exactly — a plugin shipping its own
skills, composed at boot by the same mechanism that composes everything else.

### An AI-contribution policy

Only **118 of 1,000 popular repositories** have any AI policy. Among those that do, 51% require
disclosure and 74% require a human in the loop. Ours requires that no automated system may certify
the DCO, and that the named human signer reviewed the work "sufficiently to explain it, maintain
it, and take responsibility."

The governing insight is that **cheaper generation does not mean cheaper review**. For a solo
maintainer, review capacity is the binding constraint on the whole project, and this policy is the
only lever that protects it. We are ahead of the field here.

### Written rationale, and the discipline of rejected alternatives

Roughly half of repositories that adopt architecture decision records write between one and five
and then stop. The modal adoption is the template file and silence. Our specs carry rationale as a
matter of course — the WOG spec, the sizing doctrine, the reconcile constraints — and the
`Why:`/rejected-alternative habit appears throughout.

The rule worth adopting explicitly, because it solves both the abandonment failure and the
perennial "is this decision worth recording" question: **write a record only when there was a real
alternative you rejected. No rejected alternative means it was a commit message.**

Note the inversion that makes this cheaper for us than for a team. The standard objection to
design documentation is that its cost is paid by the author and its benefit accrues to future
maintainers. Solo, that misalignment collapses — you *are* the future maintainer — and AI has
taken the writing cost to near zero.

### Treating the maintainer as an outsider

The maintainer deliberately using the contributor path is a strong practice and rarer than it
sounds. It proves the mechanical half completely: the gate fires, DCO trailers land, CODEOWNERS
holds, required checks block, the two-account setup makes review real rather than nominal.

Its structural limit is worth stating plainly, because it is the half the friends preview exists
to buy: it cannot test **comprehension**. Someone who wrote the conventions never needs the
document that explains them, so a gap in CONTRIBUTING costs the author nothing and costs a
stranger the contribution.

---

## What we are doing wrong, or are exposed on

### No discovery surface, for an adoption-first strategy

The strategy's stated center of gravity is gaining users and feedback. The repository has **one
star, zero forks, zero watchers, no topics, no homepage, no documentation site, and Discussions
disabled**. GitHub topics are the platform's own search mechanism and cost nothing. There is
currently no path by which a stranger finds this project.

This is the sharpest contradiction between what the strategy says and what exists.

A related finding worth absorbing before anyone invests in AI-visibility tactics: LLM referral
traffic is **0.15–0.25% of total web traffic**, and model recommendation is strongly biased toward
libraries that existed in training data. Across eight models, only 32–39 distinct Python libraries
were used at all; Polars saw zero usage despite outgrowing pandas. **A new library is invisible to
the weights, and no amount of documentation polish changes that.** The leverage is entirely in
being good when an agent is already working in the repo — which is what skills and enforced rules
buy — not in recommendation you cannot measure.

### Fragmentation, which is the newcomer barrier that actually shows up in studies

The dominant documented barrier for newcomers is not missing documentation but **information
scattered across many sources**, and dense, inconsistently structured onboarding material
producing cognitive overload, errors, and abandonment.

Our surface: 133 specs, a 317-line CLAUDE.md, a 208-line AGENTS.md, 132-line architecture.md, 17
skills, two strategy documents, a philosophy corpus in three tiers, plus `docs/` and `docs/misc/`.
Every piece is individually justified. The aggregate is the failure mode, and it is invisible from
inside because the author holds the whole map.

There is a second, measurable cost specific to the agent path. Instructions are followed;
**repository overviews and architecture narrative are not, while still costing 20%+ inference
overhead** and 2–4 extra steps per task. A meaningful fraction of CLAUDE.md and AGENTS.md is
narrative rather than imperative, and that fraction is a pure tax.

### The roadmap is 20× the reference implementation

curl's roadmap is 17 lines. Ours is 344, plus a 292-line product map. Much of it is genuinely
load-bearing doctrine rather than roadmap — but no external reader will make that distinction, and
the volume itself signals process weight that may not match a project a stranger is deciding
whether to try.

### Version signal versus adopter checklist

The OpenSSF adopter guide — the closest thing to a canonical evaluation checklist — instructs
evaluators to treat a `0` version prefix as an instability signal and to verify the presence of
more than one maintainer. Two of its five checks are structurally against us right now.

Staying 0.x is normal and defensible (React Native, three.js, FastAPI, Neovim all do it), but the
cost lands precisely at the moment we are trying to convert an evaluator. The cheap fix is not to
fake 1.0; it is to **say in the README what would trigger it**, which converts a red flag into a
legible plan.

---

## What is missing

### Succession artifacts — the best-evidenced risk in the entire review

Across 36,000+ projects: **89% lost their core development team at least once; 70% of those losses
occurred within the first three years; only 27% attracted a replacement.** We are inside that
window.

The mitigation is not a metric. Bus factor is 1, will remain 1, and the metric flags roughly 65%
of all GitHub projects anyway — worse, the authorship substrate it is computed from is being
eroded by AI-generated commits. The mitigation is three artifacts that cost a few hours once:

1. **A credential and asset inventory** — org, registry namespaces, domains, signing material.
   GOVERNANCE.md already claims Steward custody of exactly these, which makes this a
   spec-to-implementation gap rather than a new idea.
2. **A named GitHub account successor** — the only mechanism in the entire ecosystem built for the
   case where the maintainer dies. It covers repositories but *not* the registry accounts that
   publish from them, and no package registry has an equivalent.
3. **A documented from-scratch build path** — the recurring mundane failure is build archaeology:
   a CI service that no longer exists, a tool version that lived on one laptop.

One consequence reframes the adopter strategy: **the replacement maintainer is almost always an
existing user**, and the documented barriers are time and difficulty getting push access. The
early-adopter path is also the succession path.

### Release signing, which is the one thing that cannot be retrofitted

Every consumer who pins an unsigned artifact stays unable to verify it forever. Across 3,248
research-software repositories, **97.4% score zero on signed releases** — it is the most commonly
skipped and least recoverable practice.

We have sigstore signing scheduled as a public-alpha gate, which is defensible. Worth noting that
the standing supply-chain trigger — first non-George user — has already fired, and that the
friends preview will distribute unsigned images to real people.

### A community channel that exists

The README promises a Discord that does not exist, and Discussions are disabled. At early-adopter
stage, **time-to-first-response is the sales funnel**, and there is currently nowhere for a
response to happen except issues.

### Machine-legible deprecation

LLMs demonstrably generate deprecated APIs — measured across 28,125 completion prompts and seven
models. A deprecation notice that exists only as human prose in a changelog is invisible to a
large and growing class of consumers. For a project whose stated posture is building for the third
player, this is a cheap edge we have not taken.

### OSPS Baseline Level 1

OpenSSF now publishes a security tier **explicitly scoped to "any number of maintainers"** —
MUST-only, security-only, roughly 20 controls, badged through the same system as the Best
Practices badge we already hold. Unlike Gold (three criteria arithmetically impossible for one
person) this is a certification path that is not a lie. A disciplined repo already meets nearly
all of it.

---

## The unclaimed space

There is **no machine-readable convention for a project's roadmap, status, or capabilities.**
Every existing standard covers security posture (OpenSSF Security Insights, Scorecard),
composition (SBOM), or provenance (SLSA). Capability and intent remain prose in a README.

The two closest things in the wild are Stripe's `.well-known/skills/index.json`, which is a
capability catalog by accident of being a skills index, and MCP's `tools/list`, which is a
capability catalog by accident of being a protocol. Neither was designed for the question.

We spent today building exactly this — an initiative/line/product taxonomy, a composition
hierarchy, a fence with observable done-tests, sizes, and status — in markdown and a GitHub board.
And the platform this all serves is a queryable graph of systems whose stated thesis is that the
grid should hold what a system is and what state it is in.

Recorded as an observation, not a proposal. It is the kind of thing that should emerge from having
done it manually twice, which is exactly where we are on the first instance.

---

## Recommendations, with triggers

Ordered by regret if skipped, not by effort.

| # | Action | Cost | Trigger |
| --- | --- | --- | --- |
| 1 | Succession artifacts: credential inventory, named GitHub successor, from-scratch build path | 2–3h once | **Now.** Best-evidenced risk; we are in the danger window |
| 2 | Repo topics, homepage, Discussions on, a real channel | <1h | **Before the friends preview.** The strategy is adoption-first and has no funnel |
| 3 | Decide signing posture for the previews, explicitly | decision | **Before distributing images.** The supply-chain trigger already fired |
| 4 | State in the README what would trigger 1.0 | 20 min | Before public alpha; converts an evaluator red flag into a plan |
| 5 | Trim narrative from CLAUDE.md / AGENTS.md; keep imperatives | 1h | Measured 20% inference tax on the narrative half |
| 6 | One entry-point document that routes a newcomer through the fragmentation | 2h | Before public alpha |
| 7 | OSPS Baseline Level 1 badge | 2–4h | Opportunistic; the honest certification for n=1 |
| 8 | Machine-legible deprecation metadata | design | When the first deprecation ships |

Deliberately **not** recommended, with reasons: OpenSSF Gold (three criteria require other
humans), Scorecard aggregate as a target (headcount-confounded; a flawless solo repo caps around
7–8), CHAOSS dashboards (no published evidence any metric predicts survival), a numbered RFC
process (solves a consent problem we do not have; Rust's own registry has 58 PRs open since before
2023), `llms.txt` (97% receive zero requests; AI crawlers never probe for them), stale bots
(measurably reduce active contributors), and "good first issue" curation (newcomer merge rates
fell from 61.9% to 42.2%, and curation typically costs more maintainer time than doing the work).

---

## Evidence quality

Claims above are marked by strength in the source research. The most important cautions:

- **Badge status has never been shown to correlate with security or survival.** No peer-reviewed
  study exists. The badge is a forcing function, not a measurement.
- **Scorecard's own Code-Review check had a *positive* — that is, worse — association with
  vulnerability outcomes** across 145k npm packages. Read the findings, ignore the number.
- **Dependency pinning is unsettled** — the two best papers on it directly disagree. The
  split-the-difference position is to pin GitHub Actions by SHA (tag mutation is a live attack
  class) and not to pin application dependencies beyond a lockfile.
- **ADR value is widely held and weakly evidenced.** The one before/after study is two teams over
  three months. The claim that decision records help agents specifically rests on a single 2026
  exploratory paper.
- **Public roadmaps affecting adoption is anecdote only.** The risk argument (an adopter asking
  "is this alive") is stronger than the demand argument.
- **Issue templates improving report quality is folklore** — no supporting study found.

The load-bearing critique of the entire measurement canon is not that it is gamed; it is
**construct validity**. These instruments are dominated by a headcount and maturity confound, so a
solo project is measured largely on team size while a large project earns credit for structure
regardless of code quality. Knowing that is what makes it possible to take the seven or eight
checks that map to real attack primitives and decline the rest without guilt.
