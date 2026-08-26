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
and written rationale — and weak in three places that most often kill projects at our exact stage:
**intake control**, **discoverability**, and **succession**. The intake gap is the highest-leverage
of the three, costs an afternoon, and is the single strongest correlate of survival in the peer
data. The process apparatus is not over-built for one
person, which was the obvious critique and does not survive contact with the evidence; but it is
**fragmented**, and fragmentation is the dominant documented barrier for newcomers. The single
largest strategic finding is not a gap in our practice at all: there is no machine-readable
convention anywhere for a project's roadmap, status, or capabilities, and that unclaimed space
sits directly adjacent to what TAP is for.

---

## The peer set: what alive-and-above-water actually looks like

Twenty projects measured directly (stars, open issues, open PRs, release cadence, top-committer
share, intake policy) on 2026-08-25/26. The closest structural peers are **Ghostty** (Hashimoto,
64% of commits, 60k stars), **esbuild** (Wallace, 91% solo), **htmx** (Gross, 49%), **marimo**,
**Typst**, and **Helix**. Funded contrasts: Astral, Zed, Bun.

### The strongest correlation in the dataset

Projects whose written policy **pre-authorizes closing** unsolicited pull requests sit at
**0–110 open PRs**. Projects without one sit at **450–5,161**. This does not track stars, funding,
or headcount: Ghostty at 60k stars has 102 open PRs; Bun at 96k stars, funded and heavily
automated, has 5,161 — 83% of them from its own agent.

The mechanism is a sentence, not a bot. Ghostty: pull requests "should be associated with a
previously accepted issue," and "pull requests are NOT a place to discuss feature design." Zed:
"we tend to only merge about half the PRs that are submitted," plus a three-open-PR cap per
author. llama.cpp: new contributors limited to one open PR; duplicates "closed without review."
tldraw turned pull requests off entirely while keeping issues open, on the reasoning that "an open
pull request represents a commitment from maintainers… for that commitment to remain meaningful,
we need to be more selective."

**Issue-before-PR is now the near-universal convention of the era** — llama.cpp, Ghostty, Cline,
marimo, Zed, Ollama and htmx all require or strongly prefer it. Per-author PR caps are new and
spreading; GitHub shipped org-level PR limits in August 2026.

The two failure modes are equally clear: **policy without an enforcement gate** (Ollama publishes
an excellent three-tier issue taxonomy and runs zero triage automation — 2,423 issues, 1,373 PRs)
and **automation without policy** (Bun).

### Nobody publishes a roadmap. Nobody posts maturity disclaimers.

Zero of twenty repositories carry a `ROADMAP.md`. Direction lives in version-numbered milestones,
an ordinal dateless table in the README (Ghostty's is six rows), essays (htmx has ~60), or nowhere
at all.

And only one of twenty carries a maturity badge. **No "alpha," no "YMMV," no SLA language
anywhere.** Expectations are set by intake mechanics and by honest capacity statements — and
crucially, those statements are about *review*, not about stability:

- esbuild: "This tool is primarily built by me. For some people this is fine, but for others this
  means esbuild is not a suitable tool for their organization" — and the site adds "That's ok with
  me."
- Zed: "we tend to only merge about half the PRs that are submitted."
- Ghostty: PRs not preceded by an accepted issue are unlikely to be merged.

### Publish non-goals, not plans

Every long-lived project in the set has an explicit exclusion list. esbuild names five non-goals in
its FAQ and states an endgame ("I will consider esbuild to be relatively complete"). marimo's
CONTRIBUTING carries the best sentence in the study: **"marimo is an intentionally designed
project. We put just as much thought into the features we exclude as the ones we include."**

### Deflect features into an extension surface

htmx's move is the cheapest scope defense available: "we will often suggest that you implement it
as an extension… Even if we don't end up supporting it officially, you can publish it yourself and
we can link to it." It converts a review obligation into someone else's repository while keeping
the contributor's goodwill.

### Versioning policy instead of chasing 1.0

esbuild, ruff, uv, ty and llama.cpp all stayed pre-1.0 for years under production load with no
drama, because they wrote down what they would break. uv's formulation is the model: care taken
over backwards-incompatible changes is "proportional to the expected real-world impact, not a
function of arbitrary version numbering policies."

### The AI-slop wave, and where the line got drawn

The convergent principle, stated best by LLVM: a contribution should "provide more value to the
project than the review time required," and unreviewed LLM output is an **"extractive
contribution"** that shifts effort from implementor to reviewer. The Linux kernel's rule
(2025-12-23) is that **"AI agents MUST NOT add Signed-off-by tags. Only humans can legally certify
the DCO"** — which is, word for word in substance, the rule already in our CONTRIBUTING. QEMU
declines anything believed to derive from AI-generated content outright. Typst's guide simply says
"Do not vibecode the change!"

Ghostty went furthest: an `AI_POLICY.md` requiring disclosure of all AI usage, backed by a public
**denouncement list** shared with other projects, and a **vouch system** where first-timers must
open a request "in your own words, not written by AI" or have their PR auto-closed. His stated
reason: "AI has unfortunately made it so we can no longer trust-by-default." He extracted the
mechanism into a standalone, forge-agnostic tool.

The pattern underneath is worth naming precisely: **AI is gated outside the trust boundary and
embraced inside it.** Thirteen of nineteen repos ship agent instruction files, and the projects
clamping hardest on AI contributions are the same ones investing most in AI-legibility for their
own maintainers. Ghostty's policy literally says "AI is Welcome Here" while auto-closing unvouched
pull requests.

A novel artifact class appeared: **tripwires in agent instruction files.** Ghostty's `AGENTS.md`
instructs agents never to open issues or PRs and, if asked, to write a file declaring themselves "a
sad, dumb little AI driver with no real skills." Zed requires agents editing source to prepend a
marker to the README that only the human author may remove. These make unreviewed agent output
self-identifying.

### Permission to close intake

curl ended its six-year bug bounty in January 2026 — 87 confirmed vulnerabilities, over $100k paid,
confirmation rate collapsed from >15% to <5% under AI slop — then paused vulnerability reporting
entirely for a month. Stenberg's verdict: "possibly our best project decision in a long while,"
with "virtually no downsides," and the maintainers "felt a sense of relief… It felt like the good
old days again. The *fun* days." Jazzband is sunsetting after a decade, explicitly triggered by
what it called the slopocalypse: "an organization that gives push access to everyone who joins
simply can't operate safely anymore."

### The cautionary case that should concentrate the mind

**aider**: 48,000 stars, the highest-profile solo AI-coding project of the era. Last release August
2025, last commit May 2026, 62% single-author, no governance document, no succession path, no
triage automation. It simply stopped, nothing in its structure caught it, and continuity migrated
to a fork.

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

### No intake gate — the highest-leverage gap in the review

Our CONTRIBUTING asks that "for anything larger than a small fix, open an issue first so we can
agree," and promises "a first response within about a week." That is a *request* and a *promise*,
which is the wrong pairing. What the peer data says works is a **pre-authorized right to close**
and an honest statement of review capacity.

We currently have the obligation without the escape valve. Every project in the study that sits
under ~110 open pull requests has written down that unsolicited work may be closed unreviewed;
every project without that sentence is drowning. It is the difference between 102 and 5,161, and
it does not correlate with anything else.

Three things we already have make this cheaper for us than for most: an existing issue-first
preference to harden, an AI policy to hang it from, and — most importantly — **a plugin system**.
htmx's extension deflection is the cheapest scope defense in open source, and we are structurally
built for it. "Try it as a plugin; if it works we'll link to it" converts a review obligation into
someone else's repository while keeping the contributor's goodwill. Our CONTRIBUTING does not say
this anywhere.

### The alpha/YMMV posture is not how peers set expectations

This one contradicts a decision made deliberately in the strategy. Our posture leans hard on
"alpha / preview / YMMV / just make it work," and the README carries an "Early access" paragraph.

**Only one of twenty projects studied posts a maturity disclaimer at all.** Expectations are set by
intake mechanics, and the honest sentence that does the work is about *review capacity*, not
product stability — esbuild's "this tool is primarily built by me… for others this means esbuild is
not a suitable tool for their organization," Zed's "we merge about half."

The distinction matters because the two statements defend against different failures. "Alpha"
lowers expectations about *quality*, which is not actually our exposure — the system works and is
used daily. What we cannot absorb is *review and support load*, and a maturity badge does nothing
about that. The peer-proven move is to keep shipping and say plainly what we can and cannot
promise to look at.

This does not invalidate the alpha posture as an internal build rule (perfection is not the goal,
ship and learn). It says the *external* expression of it should be a capacity statement rather than
a quality disclaimer.

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

Staying 0.x is normal and defensible — esbuild, ruff, uv, ty and llama.cpp all did it for years
under production load. The peer-proven fix is not to chase 1.0 or even to state what would trigger
it, but to **write down what we will break and how much care we take**, in uv's formulation:
proportional to real-world impact rather than to version numbering. A written versioning policy
does the work an evaluator wants 1.0 to do.

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

### Release signing — worth doing, but **not for the reason usually given**

I initially filed this as the top regret item on the standard argument: signatures cannot be
applied retroactively, and 97.4% of small projects score zero on signed releases. The retrofit
argument holds. **The security argument does not, and the correction matters more than the
original point.**

Provenance attests **build** integrity, not **source** integrity. Every provenance control would
have passed cleanly through the xz backdoor by construction: Jia Tan was the legitimate release
manager, so the PGP signature was valid, and Sigstore would have signed the backdoor with a
verifiable OIDC identity. This is not hypothetical — the keyv/cacheable compromise of August 2026
(444 packages, over 2 billion monthly installs) shipped malware **with valid provenance signed by
GitHub Actions**, because the source it built from was already trojanized. npm's own documentation
concedes it "does not guarantee the package has no malicious code." xz scored **8/10 on
Scorecard's Signed-Releases check** while shipping a signed backdoor.

Adoption reflects this: on PyPI, only ~20% of uploads use trusted publishing and ~17% carry
attestations, and neither pip nor npm verifies by default.

**The real reason to do it is credential deletion.** Trusted publishing removes the long-lived
publish token — and that credential class is what actually fires. Filippo Valsorda's root-cause
survey of roughly twenty real compromises breaks down as: **phishing 5, unsafe `pull_request_target`
/ `issue_comment` triggers 5, long-lived credential exfiltration 5+, and social control-handoff (the
xz shape) only 2–3.** The story everyone optimizes around is the rarest category.

Which reorders our defensive priorities:

1. **Phishing-resistant 2FA — passkeys or WebAuthn, not TOTP** — on the forge and registry
   accounts, and on anything upstream of them. TOTP was enabled and defeated in the chalk/debug
   compromise.
2. **Never use `pull_request_target` or `issue_comment` triggers.** *Verified 2026-08-25: our
   workflows use neither.*
3. **Trusted publishing when we hit PyPI** — for the token deletion.
4. **Then** signing, for consumers who want to verify, not for the score.

### A published SLA we may not be able to honor

SECURITY.md commits to **acknowledgment within 7 days and initial assessment within 14 days**.
That is an obligation we have published to strangers, solo, with no backup.

The counter-model is Nick Wellnhofer's, written as he stepped away from libxml2 after years of
unpaid security triage: reports are made public immediately and fixed whenever maintainers have
time, with **no deadlines**. His broader verdict is worth sitting with, because it names the
mechanism precisely — *"all the 'best practices' like OpenSSF Scorecards are just an attempt by
big tech companies to guilt trip OSS maintainers and make them work for free."* He stepped down
from libxml2 in September 2025; libxslt is unlikely to be maintained again.

**A policy that bounds your workload is a security control for the maintainer.** Ours currently
bounds the reporter's expectations upward instead. Worth a deliberate decision before adoption
makes it load-bearing, not after.

### AI crawlers, which arrive before slop does

If we stand up anything self-hosted — a docs site, a public demo instance, a landing page — this
lands first and costs real money. SourceHut's maintainer reported spending **20–100% of his week**
mitigating LLM crawlers that ignore robots.txt and hammer expensive endpoints from tens of
thousands of residential IPs. GNOME measured 81,000 requests in two and a half hours with **only 3%
passing proof-of-work**. Read the Docs cut traffic from 800GB/day to 200GB/day by blocking AI
crawlers, saving about **$1,500 a month**.

Not a reason to avoid a docs site. A reason to put Anubis or equivalent in front of it on day one
rather than after the bill.

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

## Action register

Consolidated from all six research passes, grouped by the surface being changed. "Before friends"
means before the first outside person runs it (`step-products-git-serious-self`, 2026-08-30).

### CONTRIBUTING.md — the highest-leverage file in the set

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| C1 | **Add a pre-authorized right to close.** State that unsolicited PRs, or PRs without an accepted issue, may be closed unreviewed. | The strongest survival correlate found: projects with this sentence sit at 0–110 open PRs, those without at 450–5,161. Independent of stars, funding, headcount. | 30 min | **Before friends** |
| C2 | **Harden issue-before-PR from a request to a rule.** Currently "open an issue first so we can agree." | Near-universal convention now — llama.cpp, Ghostty, Cline, marimo, Zed, Ollama, htmx. | 10 min | Before friends |
| C3 | **Add the plugin-deflection sentence:** "try it as a plugin; if it works we'll link to it." | htmx's move, the cheapest scope defense in open source — converts a review obligation into someone else's repo while keeping goodwill. We are structurally built for it and say nothing. | 15 min | Before friends |
| C4 | **Replace the "first response within about a week" promise with a capacity statement about *review*.** | We currently pair a request with a promise — backwards. Peers set expectations with honest review capacity ("we merge about half"), not response SLAs. | 15 min | Before friends |
| C5 | Consider a per-author open-PR cap (Zed uses 3; llama.cpp uses 1 for new contributors). | New and spreading; GitHub shipped org-level PR limits Aug 2026. | 10 min | When volume appears |
| — | *AI-Assisted Contributions section — no change.* | Already ahead of ~88% of popular repos, and its DCO-certification clause matches the Linux kernel's rule verbatim in substance. | — | — |

### SECURITY.md

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| S1 | **Revisit the 7-day ack / 14-day assessment SLA.** | A published obligation to strangers, solo, with no backup. Wellnhofer's counter-model — public immediately, fixed when there is time, *no deadlines* — is what a maintainer who burned out on exactly this now recommends. A policy that bounds your workload is a security control for the maintainer. | Decision | Before public alpha |
| S2 | **Add an AI-report clause: require a working PoC in our test format, and a short human-written preamble.** | The only cross-project consensus on slop. Tomcat reports it "very effective." | 20 min | Before public alpha |
| S3 | Add a canary sentence addressed to AI tools (Django's asks the reporter to close with an unrelated fact). | One sentence; catches unedited pipeline output. | 5 min | With S2 |
| — | *Never attach money to unsolicited reports.* | curl's natural experiment is the strongest causal evidence in the field — removing the bounty restored report quality within weeks. We have no bounty; keep it that way. | — | Standing |

### README.md

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| R1 | **Replace the "Early access" quality disclaimer with a review-capacity statement.** | Only 1 of 20 peers posts a maturity badge. Expectations are set by intake mechanics, and the honest sentence is about review, not stability — esbuild's "primarily built by me… for others this means it is not a suitable tool for their organization." "Alpha" defends against the wrong failure: our exposure is review load, not quality. | 20 min | Before friends |
| R2 | **Write a versioning policy** — what we will break and how much care we take — instead of stating what triggers 1.0. | esbuild, ruff, uv, ty and llama.cpp all stayed pre-1.0 for years under production load by writing this down. uv's formulation: care proportional to real-world impact, not to version numbering. | 30 min | Before public alpha |
| R3 | **Add a project-level non-goals list.** | Every long-lived project in the peer set has an explicit exclusion list. marimo: "we put just as much thought into the features we exclude as the ones we include." | 30 min | Before public alpha |

### plan/road-products.md

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| P1 | **Fill in the trigger for paid support** (left deliberately blank in the moat section). | "Low expenses" unqualified becomes indefinite unpaid labour — the documented path to walking away mid-obligation. Decide by condition, not by exhaustion. | Decision | Soon |
| P2 | **Add the sequencing rule to doctrine: audience before money, always.** No case in the dataset of money arriving before an audience. Corollary: do not build the funding surface before the users — an empty sponsors page earns $0 and reads as a negative signal. | 15 min | Anytime |
| P3 | Record the licence decision: **stay Apache 2.0, keep the DCO**, and why. | Prevents re-litigation, and the DCO's inability to relicense is a credible public commitment worth stating rather than leaving implicit. | 15 min | Anytime |

### plan/product-map.md

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| M1 | **Record the paid-boundary rule before anything is built: gate on organizational scale, never on safety.** Safe — multi-tenancy, HA, audit retention, compliance reporting, delegated admin, SLA, hosting. Never — auth, basic RBAC, encryption, logging, security patches. Fatal — removing what was already free. | MinIO's specific sin was removing LDAP/OIDC login: gating authentication by deletion. Repository now archived. Our own security posture independently requires the same line. | 20 min | Before any paid surface exists |
| M2 | **Add the ecosystem-seeding playbook** — plugin tutorial, cookiecutter, demo plugin, curated catalog with tiers, promotion ladder from community repo into the org. | Exactly what NetBox did: solo-authored core, first third-party plugin 3 months after the API, now 164 plugins from 114 owners, no bounties. Weekend-scale, repeated. | 30 min | Before public alpha |
| M3 | Strengthen the distribution section: **never take custody of plugin distribution.** | Every ecosystem-control disaster came from the vendor holding the only channel — Nagios 2014, WordPress 2024, ownCloud 2016. Use PyPI. | 10 min | Anytime |

### Repository and org surfaces

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| G1 | **Succession artifacts: credential/asset inventory, named GitHub account successor, from-scratch build path.** | Best-evidenced risk in the review — 89% of 36,000+ projects lost their core team, 70% within three years, 27% replaced. GOVERNANCE.md already promises Steward custody of exactly these assets, so this is a spec-to-implementation gap. Under the moat framing it is also the *evidence* for the continuity claim. | 2–3h | **Now** |
| G2 | **Repo topics, homepage, Discussions enabled, a real channel.** | The strategy is adoption-first and there is currently no path by which a stranger finds this. Topics are GitHub's own search mechanism and cost nothing. README promises a Discord that does not exist. | <1h | **Before friends** |
| G3 | **Register the trademark; publish a stable conformance-style policy before any dispute.** | Highest-leverage cheap action available. Valkey — LF-governed, AWS+Google-backed — cannot call itself "Redis-compatible." That is trademark achieving what SSPL failed to. Define compliance objectively, never amend to target a party, don't plan on litigating. | Legal | Soon |
| G4 | **Passkey/WebAuthn on forge and registry accounts; trusted publishing at first PyPI push.** | Phishing and long-lived tokens are the actual root causes (5 and 5+ of ~20 real compromises); the xz-style social takeover is the rarest at 2–3. TOTP was enabled and defeated in the chalk/debug compromise. Take trusted publishing for the *token deletion*, not the provenance. | 1h | Now / at first publish |
| G5 | Decide signing posture for the previews explicitly. | The supply-chain trigger already fired. Provenance attests build integrity, not source integrity — keyv shipped malware with valid GitHub Actions provenance — so sign for consumers, not for the score. | Decision | Before distributing images |
| G6 | Bot mitigation in front of anything self-hosted. | SourceHut spent 20–100% of a week on LLM crawlers; Read the Docs saved ~$1,500/month by blocking them. | 1h | Day any public site goes up |
| G7 | OSPS Baseline Level 1 badge. | OpenSSF's only tier explicitly scoped to "any number of maintainers" — the certification that is not a lie at n=1. | 2–4h | Opportunistic |

### Agent-facing surfaces

| # | Action | Why | Cost | When |
| --- | --- | --- | --- | --- |
| A1 | **Trim narrative from CLAUDE.md and AGENTS.md; keep imperatives.** | Instructions get followed; repository overviews and architecture narrative measurably do not, while costing 20%+ inference overhead and 2–4 extra steps per task. | 1h | Anytime |
| A2 | **One entry-point document that routes a newcomer through the fragmentation.** | The dominant documented newcomer barrier is scattered information, not missing information. 133 specs, two strategy docs, 17 skills, a three-tier philosophy corpus — invisible from inside. | 2h | Before public alpha |
| A3 | Machine-legible deprecation metadata. | LLMs demonstrably generate deprecated APIs (measured across 28,125 prompts, seven models). A deprecation notice that exists only as prose is invisible to a growing class of consumers. | Design | First deprecation |
| A4 | Consider an agent tripwire in AGENTS.md. | Novel artifact class — Ghostty instructs agents never to open PRs and to self-identify if asked; Zed requires a README marker only a human may remove. Makes unreviewed agent output visible. | 15 min | Opportunistic |

### Deliberately not recommended

| Not doing | Why |
| --- | --- |
| OpenSSF Gold | Three criteria arithmetically require other humans. |
| Scorecard aggregate as a target | Headcount-confounded; a flawless solo repo caps at ~7–8. Its own Code-Review check correlates *positively* with vulnerabilities across 145k npm packages. |
| CHAOSS dashboards | No published evidence any metric predicts survival; bus factor flags ~65% of all projects. |
| A numbered RFC process | Solves a consent problem we do not have. Rust's own registry has 58 PRs open since before 2023. |
| `llms.txt` | 97% receive zero requests; AI crawlers never probe for them; Astro removed theirs after measuring ~1,000× more MCP traffic. |
| Stale bots | Measurably reduce active contributors. |
| "good first issue" curation | Newcomer merge rates fell 61.9% → 42.2%; curation typically costs more than doing the work. |
| A plugin marketplace revenue cut | Dead everywhere. Odoo is the only confirmed rev-share and has 8,000+ employees. |
| Donations as a revenue line | Median sponsorship earnings are **$0**; $13/month conditional on having any sponsor. Plausible raised $30 in six months and quit. |
| Marketplace listings as a funding plan | ~$1,000/month ceiling; converts demand rather than creating it; commit-drawdown excludes self-hosted-sold-as-support on two of three clouds. |
| Restrictive relicensing | No case with public numbers shows revenue moving upward. |

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
