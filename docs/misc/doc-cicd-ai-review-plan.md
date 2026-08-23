---
spec: ../../specs/spec-cicd-ai-review.md
audience: [developer, llm]
covers:
  - ../../specs/spec-cicd-ai-review.md
  - req-cicd-ai-review-ensemble
  - req-cicd-ai-review-gate
  - req-cicd-ai-review-graduation
update-triggers:
  - A reviewer-vendor security incident or materially changed offering (mirror the spec ledger's triggers)
  - The Phase-2 observation window produces data contradicting the roster or thresholds here
  - The blocking flip (Phase 3) lands — update phase statuses
assumes:
  - The PR promote flow (promote-to-main.sh → PR → `gate` required check → auto-merge) is the road to main
provides: |
  The reasoning record behind spec-cicd-ai-review.md — how the roster was arrived at, including the
  2026-08-12 roster that was later overturned and why. The security framing (what AI review defends
  against and honestly doesn't), how reviewers wire into the existing gate/auto-merge machinery, the
  phased rollout, and the key research findings with sources. For what to actually install, read
  doc-cicd-reviewer-rollout-plan.md; for current canon, read the spec.
---

# AI Reviewer Ensemble — Integration Plan

Companion plan to [spec-cicd-ai-review.md](../../specs/spec-cicd-ai-review.md) (2026-08-11,
sam-dev research session; three-agent sweep of CodeRabbit, the OpenAI/Anthropic review offerings,
and the best-practices landscape). Sibling plan: [doc-cicd-root-of-trust-plan.md](doc-cicd-root-of-trust-plan.md)
(who watches these watchers).

> ## ⚠️ The roster below was overturned on 2026-08-13
>
> **This document is kept as the reasoning record, not as the plan.** The current roster is
> **Copilot code review + Codex via `openai/codex-action`**, with **Codacy + SonarQube Cloud** as
> read-only security observability. The executable plan is
> [doc-cicd-reviewer-rollout-plan.md](doc-cicd-reviewer-rollout-plan.md); current canon is the spec.
>
> **What overturned it:** a sweep of every candidate's actual GitHub App permissions
> (`gh api /apps/<slug> --jq '.permissions'`) rather than its marketing. CodeRabbit's App requests
> `contents: write`; so do Greptile, Cursor, Graphite, Sourcery, Trunk, Devin, Ellipsis, DeepSource,
> Snyk, Socket, CodeAnt, Pixeebot and Reviewbot. The Codex *cloud* connector — the seat recommended
> below — wants `contents: write` **plus `workflows: write` plus `actions: write`**, the broadest
> grant surveyed. Only `codacy-production`, `sonarqubecloud` and `difflens` came back
> `contents: read`.
>
> **Three conclusions worth carrying, because each reverses something argued below:**
>
> 1. **The permission question dominates the quality question.** Every seat below was chosen on
>    review quality and model independence, with the trust cost noted as a column. It turned out to
>    be the filter, not a column — and it eliminated nearly the entire market in one pass.
> 2. **"Runs on vendor infrastructure" was the wrong safety property.** It is argued below as the
>    strongest form of least privilege. It is not: vendor infra bought "no TAP secret at risk" by
>    handing the vendor a write key to every repo in the org. A read-only job in our own CI holding
>    one rotatable API key is strictly smaller. `req-cicd-ai-review-ensemble-4` was rewritten from
>    "No CI-Resident Reviewer" to "No Reviewer Holds Code Write" for exactly this reason.
> 3. **Marketing is not evidence, and neither is reputation.** One command against GitHub's own
>    registry contradicted several vendors' positioning. That check is now canon for *any* App on
>    the org (`req-cicd-ai-review-least-privilege-4`), not just reviewers.
>
> Also settled on the way: Korbit's vendor is dead, and `gemini-code-assist` sunset 2026-07-17 —
> two candidates that failed for reasons no permission check would have caught.
>
> Everything below this line is the 2026-08-12 record, unedited except for this banner.

## Recommendation *(superseded 2026-08-13 — see banner)*

**Decided 2026-08-12.** Run **two** AI reviewers on every code-bearing PR to `main`:
**CodeRabbit** (free full Pro on public repos — summaries, walkthroughs, hygiene, bundled scanners)
as the daily-life seat, and **OpenAI Codex cloud review** (~$20/mo) as the independence leg, because
TAP is authored by Claude and the most important reviewer is a non-Anthropic model. Both run on
vendor infrastructure; **nothing runs inside TAP's CI**. The malicious-change lens — the #1 job — is
carried as *configuration on both seats* (CodeRabbit `path_instructions`, Codex `AGENTS.md` review
rules) rather than by a third specialist agent. Start both *advisory* — comments only. After a
~2-week observation window, graduate only the *security-severity* verdicts into a blocking required
check built in the same fail-closed pattern as the existing `gate` job — never by letting a bot's
"Approve" count as a review. Estimated cost: **$20/month, total**. Build time: about a day for the
advisory phase.

Two decisions worth carrying forward, because both reverse an earlier draft of this plan:

1. **CodeRabbit is not the independence leg.** Its planning layer is built on Claude. A product's
   brand is not its model family — independence has to be verified at the model stack, not the logo.
   Codex is the only seat that discharges the non-Anthropic requirement.
2. **The dedicated CI-resident security reviewer is deferred, not seated.** See below.

## What this defends against — and what it honestly doesn't

The #1 job is the **smuggled-compromise threat**: a compromised laptop (George's) or a compromised
future contributor slipping a subtle malicious change — a weakened check, a backdoored auth path, a
poisoned build script — into a plausible-looking PR. This is the xz-utils class of attack. Hygiene
(smells, nits, correctness) is job #2 and comes mostly free from the same reviewers.

The research is encouraging but sobering. Production systems exist at real scale — Cloudflare runs
a multi-model reviewer ensemble on 131,000 reviews a month at about $1 each, with actual
merge-blocking authority; Datadog's LLM screens every PR for malicious intent at a 0.03%
false-positive rate. But the best adversarial study (PRWeaver, Aug 2026) found that a malicious
change *fused into a plausible carrier PR with a cover-story description* drops detection to a
floor of roughly 29% even for strong models. And no standards body counts AI review as a "second
person" — SLSA's two-party rule means two *humans*.

> **The honest claim** is therefore: an *additional detection layer plus a forced second look* —
> several independent sets of eyes that make smuggling *loud and evidence-bearing* — not a
> replacement for a second human. That's still a big upgrade over zero reviewers, which is the
> current state.

> **The residual that trumps everything:** the GitHub account is admin. A compromised machine
> holding those credentials can today ride the ruleset's admin bypass, and could always alter the
> rulesets themselves. The AI gate raises the cost from "silent smuggle" to "visibly defeat or
> disable the reviewers," which leaves evidence — but the root controls are account-level:
> passkeys/2FA on GitHub, and landing the already-planned **emptying of the admin bypass list** in
> the same wave as the blocking flip. The two changes belong together. (Now owned by
> [spec-cicd-root-of-trust.md](../../specs/spec-cicd-root-of-trust.md).)

## The roster: two seats, two lenses, two vendors *(superseded 2026-08-13 — see banner)*

The one rule the literature agrees on: **the author model must not be the only reviewer family**.
Models miss their own errors ~64% of the time, and same-family review inflates pass rates 9–17
points. Since Claude writes nearly all TAP code, the non-Anthropic seat matters most. A second
caveat worth internalizing: frontier models share training data, so nominal reviewers ≈ ~1.5
*effective* independent opinions — which is why the roster diversifies by *lens* (hygiene and
summaries vs. independent correctness) as well as vendor, and why a third seat buys less than it
costs in triage attention for a solo maintainer.

Independent validation arrived while this plan was being decided: **Greptile shipped "Model
Inversion"**, which detects the authoring agent from commit trails and branch prefixes and routes
review to the opposing model family — this plan's central rule, productized, on measured grounds
(Claude Opus caught 62% of high-severity bugs in GPT-authored code but only 53.7% in its own; GPT
60% vs 50.5%). We are not out on a limb here.

| Seat | Service | Role | Cost | Trust cost |
| --- | --- | --- | --- | --- |
| **CodeRabbit** — *the daily-life seat* | GitHub App, free full Pro on public repos (permanent, no application) | PR summaries and walkthroughs, hygiene, 40+ bundled static tools (semgrep, gitleaks), plus malicious-change instructions via `path_instructions`. Advisory always. **Not the independence leg** — its planning layer runs on Claude. | $0 | The higher of the two — a third-party App with broad repo grants and a real 2025 compromise history (below). Installed org-wide by design — see "The org is the policy boundary". |
| **OpenAI Codex** — *the independence leg* | Codex cloud auto-review (`@codex review`), ChatGPT Plus account | A genuinely non-Anthropic frontier model reviewing Claude-authored code. P0/P1-focused by design, so it stays quiet. Tunable via the `AGENTS.md` review-rules section TAP already maintains; `@codex security review` variant on demand. | $20/mo (Plus) | Lowest available — runs on OpenAI infra, no secrets in our workflows. **Provisioning note:** cloud review ships with the *subscription*, not the API key; the API tier has no cloud features, so this seat is an account to create, not a secret to wire. |

**Deferred, not eliminated — the dedicated CI-resident security reviewer.** An earlier draft seated
`anthropics/claude-code-security-review` as a third reviewer. It is now deferred, and the reasoning
is the most important thing in this plan: that action runs **inside TAP's CI, holding an API key,
parsing attacker-controlled PR content**. That is precisely the capability combination behind
CVE-2025-59536 (code execution via PR-borne prompt injection) and CVE-2026-21852 (API-key
exfiltration) — both fixed in `claude-code-action` v1.0.94, and the security-review action still
self-declares "not hardened against prompt injection." Since the whole point of this programme is
defending against smuggled compromise, adding an in-pipeline agent that executes on attacker text to
do it is a net-negative trade at v0 scale. The lens itself is not lost: it moves into
`path_instructions` and `AGENTS.md`, executing on vendor infrastructure instead of ours. Revisit
only if Phase 2 shows the specialist catching a class the two seats miss.

Also evaluated and *parked*: **Greptile** (whole-codebase context, ~82% seeded-bug catch, ~50% more
bugs than CodeRabbit, free for Apache-2.0 projects, native Model Inversion) — passed over because it
is measurably the noisiest reviewer, 11 false positives against CodeRabbit's 2 on a 50-PR benchmark,
and noise is the failure mode that would sink the daily-life goal for a solo maintainer. It is the
first swap-in if depth beats quiet in practice; watch its 50-review/month ceiling against TAP's
measured ~44 merged PRs per 30 days. Anthropic's managed **Claude Code Review** (strong
verification-pass design, Team/Enterprise plan, ~$15–25 per review) and **GitHub Copilot code
review** (comments only; GitHub itself won't let it satisfy review requirements) remain parked. A
Cloudflare-style self-built coordinator is the eventual leading-edge upgrade if reviewer volume ever
justifies it — deliberate overbuild-avoidance for now.

## Why CodeRabbit still makes the cut, eyes open *(superseded 2026-08-13 — it did not; see banner)*

In January 2025, researchers at Kudelski Security achieved remote code execution on CodeRabbit's
production servers *through a pull request* — they submitted a PR containing a malicious Rubocop
linter config, which CodeRabbit's tooling executed. The haul included the private key to
CodeRabbit's GitHub App, which would have let an attacker mint write-capable tokens for roughly a
million installed repositories. CodeRabbit fixed it within days and rebuilt tool execution inside
isolated sandboxes ("tools in jail"), and has since passed SOC 2 Type II.

That incident is the single best illustration of this plan's central doctrine: **the reviewer is
also an attack surface.** Every documented AI-reviewer compromise — CodeRabbit's RCE, the Claude
Action leaking its API key via shell commands hidden in a PR *title*, Copilot Chat's CamoLeak
exfiltration, the GhostCommit attack hiding instructions inside a PNG — required the reviewer to
hold write access, secrets, tools, or network egress. So every seat in the roster is configured
down to *read and comment, nothing else*, and the vendor-App residual is bounded: the install is
bounded by the org boundary, the approval workflow is off, and the `main` ruleset's required checks
apply to Apps too. A CodeRabbit-side compromise then degrades to "wrong comments," which the
ensemble absorbs.

## The org is the policy boundary

`unified-systems-com` exists to house purely TAP systems — all open source, all needing the same
level of protection. That is a deliberate architectural choice, and it decides how reviewers get
installed: **org-wide, across all repositories, present and future.** The goal is an org-wide floor
for security and review, applied everywhere by design.

This reverses the instinct to enumerate repositories, and the reasoning is worth stating because the
instinct is a good one *in a different situation*. A selected-repo allowlist bounds a grant when an
org is heterogeneous — when some future repo might hold something that shouldn't be in scope. In a
single-purpose org it does the opposite: it becomes a drift generator. Every new plugin repo would
sit below the floor until someone remembered a click, and nothing would signal the omission. "Every
repo in this org is reviewed" is a checkable invariant; "the repos someone remembered" is not.

Two things keep that honest:

- **Homogeneity is the invariant.** If something ever needs a different protection level, it belongs
  in a *different org* — never as an in-org exception. One exception turns the floor from an
  invariant into a convention, and the checkability goes with it.
- **Record the grant.** Org-wide install means a vendor-side key compromise reaches every repo in
  the org, so what the App is permitted to do matters more, not less. Read the permission list at
  install time and record it. An App requesting `administration` reaches branch protection and
  rulesets — that is a root-of-trust decision, not a reflex-accept.

The same reasoning applies to configuration. Copying one security instruction into fifteen
repositories violates derive-a-fact-once and produces fifteen silently diverging copies, so the
generic lens belongs in CodeRabbit's **org-level** settings, with `inheritance: true` in the core
repo's `.coderabbit.yaml` merging TAP-specific paths on top. The catch is that org settings live in
a vendor dashboard rather than in git — unversioned and silently changeable — which makes it an
external-configuration-ratchet case: commit the intended configuration and check the live state
against it.

## How it wires into the existing machinery

The seam already exists. Every change to `main` now rides a pull request: `promote-to-main.sh`
opens the PR, the server-side `gate` check (the aggregator job in `product-lines.yml`) must go
green, and auto-merge lands it. Two integration facts fall out of the research:

- **Bot approvals are the wrong mechanism.** GitHub reviews have a formal "Approve / Request
  changes" state that branch protection can require — but no vendor endorses their bot filling
  that slot, and GitHub's own Copilot can't. The right mechanism is the one TAP already trusts: a
  **required status check** — a named CI job the ruleset insists must pass — whose pass/fail logic
  we own.
- **Both vendors' managed reviews are advisory by design** and emit machine-readable verdicts
  precisely so you can build your own gate. Codex's action supports a structured `output-schema`;
  Claude's products emit severity JSON. The blocking gate is therefore a small TAP-owned
  `ai-review` aggregator job — a sibling of `gate` — that parses those verdicts and **fails
  closed**: a missing or unparseable verdict is red, a skip is red unless the change tier
  justifies it (docs-tier PRs are exempt, same as the boot gates), and only security-class
  findings at high/critical severity block. Hygiene never blocks.

**Auto-merge compatibility:** auto-merge waits for all required checks, so adding `ai-review` to
the ruleset simply holds the merge a few extra minutes while reviews complete. The promote
script's existing 60-minute PR wait absorbs that. Reviewer-service outage becomes a shipping
dependency — the break-glass is the existing loud skip-hatch, never a quiet reviewer-disable.

Reviewer workflows follow the already-canonical hardening (`req-cicd-runner-least-privilege`):
SHA-pinned actions, read-only tokens, plain `pull_request` triggers (never `pull_request_target`,
the classic GitHub Actions foot-gun that hands fork PRs your secrets), and PR content treated as
untrusted input to the model. One TAP-specific policy from the GhostCommit lesson: **an
unreviewable file is a finding, not a skip** — a PR adding binary blobs or images in code paths
gets flagged by the reviewers rather than silently passed over. TAP has almost no legitimate
binary churn, so this costs nearly nothing.

## Rollout *(superseded 2026-08-13 — see doc-cicd-reviewer-rollout-plan.md)*

1. **Phase 0 — land the spec, provision the one account** (~half a day; specs-tier PR). Review and
   promote `specs/spec-cicd-ai-review.md`. Provision **ChatGPT Plus** for Codex — that is the only
   purchase, and note it is an *account*, not a credential: cloud review comes with the
   subscription, and no API key enters the repo. CodeRabbit needs no account (free Pro is automatic
   on public repos). With no reviewer secrets to wire, this phase no longer needs `/manage-secret`.
2. **Phase 1 — two advisory reviewers, org-wide** (~a day of wiring). Install the CodeRabbit App on
   **all repositories** in `unified-systems-com` — the floor applies everywhere by design, and the
   plugin repos arguably need the malicious-change lens more than core does, since they ship as
   separately released wheels that install into TAP without the change ever touching the core repo.
   Record the permission grant at install. Commit `.coderabbit.yaml` — chill profile,
   malicious-change `path_instructions`, near-empty path filters, approval workflow off — and put
   the generic lens in the **org-level** configuration so new repos inherit it without a copied
   file. Enable Codex cloud auto-review on core (its usage bills against a ChatGPT plan, so it
   extends outward as volume justifies) and add the review-rules section to `AGENTS.md`, carrying
   the same malicious-change instructions. Exempt docs-tier PRs so the volume stays triageable.
   Nothing blocks; every code-bearing PR now gets independent commentary, and **no new code runs in
   TAP's CI**.
3. **Phase 2 — observe and calibrate** (~2 weeks / ~20 PRs, passive). Track finding volume,
   false-positive rate, and latency per reviewer; tune the noise knobs (profiles, filters, "what
   NOT to flag" instructions). Optionally seed a deliberate bug or two to spot-check detection.
   OpenSSF's warning is the calibration target: robots over-inflate severity, so thresholds get
   set against *our* risk, not the reviewer's enthusiasm.
4. **Phase 3 — flip the security slice to blocking** (~a day, one deliberate wave). Build the
   `ai-review` fail-closed aggregator, add it to the `main-required-checks` ruleset, add its
   Validation Map row — and **re-decide the CI-residency question first**, because the obvious
   gating path (moving Codex to `openai/codex-action` with structured output) puts a reviewer back
   inside our CI holding a key, undoing the property Phase 1 was designed around. Evaluate parsing
   the cloud review's already-posted verdict as the no-new-surface alternative before reaching for
   the action. Then —
   and **empty the admin bypass list in the same wave**, since the gate is advisory-in-fact for a
   compromised admin laptop until then. Document the break-glass path.
5. **Phase 4 — leading edge, demand-gated** (later, each on its own trigger). *(Plugin-repo rollout
   moved into Phase 1 — it is org-wide from the start, not a later expansion.)* An
   install-coverage drift check: verify every non-archived repo in the org still carries the
   reviewer floor, so a new repo cannot sit silently below it. Structured
   verdict ledger — retained verdict JSON per PR SHA, monitored by the internal security AI
   alongside the `CONCERN` stream; eventually verdicts on the grid, TAP observing its own supply
   chain. Watch the open research gap: *cross-PR evidence linking* (multi-PR distributed attacks
   are the hole nobody ships a defense for — being early here is a genuine leading-edge position).

## Named gaps (recorded in the spec, not implied closed)

- **Not a SLSA two-person review.** The claim is "detection control + forced second look," a
  self-defined control, documented as such.
- **Correlated votes:** shared training data means an error class common to frontier models
  passes all reviewers.
- **Multi-PR distributed attacks:** ~29% detection floor for plausible-carrier changes; partially
  mitigated by per-PR review (never batched — batching collapses detection 3×) and small diffs.
- **Build scripts and binaries** — the actual xz vector — partially covered by the
  unreviewable-file rule and CI-config-aware prompts; not closed.
- **Prompt-injected false approval:** mitigated by sanitization, ensemble redundancy, and
  fail-closed parsing; not eliminated.
- **Admin compromise trumps the gate** (see spec-cicd-root-of-trust.md); **reviewer outage**
  becomes a shipping dependency, accepted with the loud break-glass.

## Key sources

- Cloudflare — [AI code review at scale](https://blog.cloudflare.com/ai-code-review/) (the reference ensemble architecture)
- Datadog — [Detecting malicious PRs with LLMs](https://www.datadoghq.com/blog/engineering/malicious-pull-requests/)
- PRWeaver — [adversarial eval of AI reviewers](https://arxiv.org/html/2608.02693) · "Nine Judges, Two Effective Votes" — [correlated-error panels](https://arxiv.org/pdf/2605.29800)
- Kudelski Security — [the CodeRabbit RCE](https://kudelskisecurity.com/research/how-we-exploited-coderabbit-from-a-simple-pr-to-rce-and-write-access-on-1m-repositories/) · GhostCommit — [image-borne prompt injection](https://asset-group.github.io/disclosures/ghostcommit/)
- CodeRabbit — [configuration reference](https://docs.coderabbit.ai/reference/configuration) · [why review needs model independence](https://www.coderabbit.ai/blog/code-review-needs-independence)
- OpenAI — [codex-action](https://github.com/openai/codex-action) + Codex cloud GitHub integration docs · Anthropic — [claude-code-security-review](https://github.com/anthropics/claude-code-security-review), [claude-code-action security model](https://github.com/anthropics/claude-code-action/blob/main/docs/security.md)
- OpenSSF — [Securing Open Source in the Age of AI](https://openssf.org/wp-content/uploads/2026/05/Securing-Open-Source-in-the-Age-of-AI.pdf) · SLSA — [Source Track two-party requirements](https://slsa.dev/spec/v1.2/source-requirements)

The durable, maintained canon is the Prior Art ledger in
[spec-cicd-ai-review.md](../../specs/spec-cicd-ai-review.md); this doc is the point-in-time plan
and reasoning record.
