# AI-Reviewer Ensemble For Pull Requests

## Philosophy

**DRAFT (2026-08-11, roster rebuilt 2026-08-13, re-architected for contributor coverage 2026-08-20)** — authored from the sam-dev research session on AI
PR review; requirements are `Proposed` and unbuilt. The v0 roster was rebuilt from scratch on
2026-08-13 against verified GitHub App permission grants; the run sheet for standing it up is
[doc-cicd-reviewer-rollout-plan.md](../docs/misc/doc-cicd-reviewer-rollout-plan.md). This spec is the center of gravity for **automated AI review of changes to
TAP's repositories**: which AI reviewers run, what they are trusted to do, how their verdicts gate
(or don't gate) a merge, and how the fast-moving prior art is tracked over time.

The demand is real and stated plainly: a solo maintainer cannot keep up with the influx of changes,
and the classic answer — multi-human review — is not available. The emerging industry answer is an
**ensemble of independent AI reviewers** standing in for the second (and third) pair of eyes.
Production evidence now exists at scale (Cloudflare: 130k+ reviews/month, ~$1/review median, with
actual merge-blocking authority; Datadog: LLM malicious-PR detection fleet-wide), and the major
vendors ship first-party review products. TAP adopts the pattern early and deliberately.

The **priority order is explicit**: the #1 job is defending the codebase against **subtle malicious
changes smuggled in through a compromised maintainer machine or compromised major contributor** —
the xz-utils class of attack. Hygiene (code smells, correctness nits, style) is the #2 job and
comes largely for free from the same reviewers, but every architectural decision here is judged
against the security job first.

Four doctrine points shape everything below:

> **1. The reviewer is also an attack surface.** Every documented compromise of an AI review system
> (CodeRabbit RCE via a linter config in a PR; Claude Action key leak via bash in a PR title;
> CamoLeak; GhostCommit) required the reviewer to hold write privileges, secrets, tool access, or
> network egress. A read-only, no-tool, egress-blocked reviewer degrades under prompt injection to
> "wrong verdict" — which the ensemble absorbs — instead of "compromised pipeline." Least privilege
> applies to the watcher exactly as to the watched (`req-cicd-runner-least-privilege`, the
> trust-delta doctrine).

> **2. An AI verdict gates through a TAP-owned, fail-closed check — never through a bot "approval."**
> GitHub's own flagship (Copilot code review) cannot satisfy required-review rules, and no standards
> body accepts AI review as a two-person rule (SLSA L4 requires trusted *persons*). The blocking
> mechanism is the one TAP already trusts: a required status check whose pass/fail logic we own —
> the `gate` aggregator pattern — parsing machine-readable verdicts, red on absence.

> **3. Honesty about what this is.** Multiple AI reviewers are an **additional detection control and
> a forced second look**, not a substitute second human. The known gaps (multi-PR distributed
> attacks, build-script/binary channels, correlated model errors, admin-account compromise) are
> named in this spec per `req-sec-honest-risk`, not implied closed.

> **4. The maintainer is not special.** (George, 2026-08-21: "I'm not special — build all of our
> processes to support outsiders, and the way to do that is to treat me like an outsider.") Every
> process is the outsider's process; the maintainer's flow differs from a contributor's by zero
> steps, which exercises the contributor-era machinery daily and eliminates the special-path
> bypass class outright — a compromised maintainer session IS an untrusted contributor. **A
> maintainer-only affordance in any design is a defect, not a convenience.** This is the
> generator behind identity-raises-scrutiny (`req-cicd-ai-review-untrusted-content-6`), the org
> floor's homogeneity, two-account review, and the emptying of bypass lists.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Independent Eyes On Every PR | ≥2 AI reviewers from different vendors review every code-bearing PR to main. |
| 2. | Security First | The ensemble is tuned, prompted, and gated for malicious-change detection above hygiene. |
| 3. | Reviewer Least Privilege | Reviewers read and comment; they hold no write path, no secrets, no egress, no tools they don't need. |
| 4. | TAP Owns The Gate | Blocking is a fail-closed TAP-owned required check over machine-readable verdicts, never a delegated bot approval. |
| 5. | Advisory Then Blocking | Reviewers start advisory; only measured, calibrated, security-severity findings graduate to blocking. |
| 6. | Track The Wave | The prior-art ledger below is maintained as the field moves; TAP stays at the leading edge on purpose. |

## Prior Art (the standing ledger — `req-cicd-ai-review-prior-art`)

Last swept: **2026-08-20** (fork-coverage sweep — Cursor/Grok/DiffLens/Copilot-fork verification,
which re-architected the Codex seat; built on the 2026-08-13 permission sweep, the 2026-08-12
model-stack/pricing/CVE sweep and the 2026-08-11 three-agent sweep). Update
triggers: any reviewer vendor incident; a new first-party review product; a major eval/benchmark
result on malicious-change detection; SLSA/OpenSSF movement on AI review as a control; **any change
to a seated App's permission set**.

**The permission sweep (2026-08-13) — the finding that decided the roster.** Every candidate's
GitHub App was queried directly against the registry rather than read from vendor marketing:

```bash
gh api /apps/<slug> --jq '.permissions'
```

The result eliminated nearly the entire market on one criterion — **write access to code**:

| Verdict | Apps |
| --- | --- |
| `contents: read` | `codacy-production`, `sonarqubecloud`, `difflens` |
| `contents: write` | `coderabbitai`, `greptile-apps`, `chatgpt-codex-connector`, `cursor`, `baz-app`, `graphite-app`, `sourcery-ai`, `trunk-io`, `devin-ai-integration`, `ellipsis-dev`, `deepsource-io`, `snyk-io`, `socket-security`, `codeant-ai`, `pixeebot`, `reviewbot` |
| Dead / sunset | `korbit-ai` (vendor dead), `gemini-code-assist` (sunset 2026-07-17) |

Two corrections to earlier entries in this ledger, recorded rather than silently overwritten:

- **CodeRabbit's App does not request `administration`.** An earlier draft of this ledger implied it
  did. The actual grant is `contents`/`checks`/`issues`/`pull_requests`/`statuses: write` and
  `actions`/`discussions`/`members`/`metadata: read`. The disqualifier is `contents: write` alone —
  which is precisely the grant the Kudelski RCE converted into write access across ~1M repositories.
- **`chatgpt-codex-connector` (the Codex *cloud* GitHub integration) requests `contents: write`
  plus `workflows: write` plus `actions: write`** — the broadest grant of any candidate, and the
  reason the Codex seat is taken via `openai/codex-action` in TAP's own CI under a permissions block
  we author, rather than via the subscription's App.

**The fork-coverage sweep (2026-08-20) — the finding that re-architected the Codex seat.** The
goal was restated plainly: two AI reviewers at the GitHub side covering BOTH maintainer PRs and
inbound contributor (fork) PRs. Verified findings:

- **The repo-secret + `openai/codex-action` single-stage design goes dark on exactly the
  contributor PRs**: GitHub withholds repository secrets from fork-PR `pull_request` runs, and
  codex-action fails the job for authors without write access (verified in its
  `checkActorPermissions.ts`).
- **Cursor Bugbot** is functionally the closest product on the market (vendor infra, official
  fork-PR support, usage-priced ~$1.00–1.50/review since June 2026) but there is NO Bugbot-scoped
  App: it rides the single `cursor` App, live-verified requesting `contents: write` +
  `workflows: write` + `actions: write` + `administration: read` — the broadest grant yet
  surveyed, because the same App serves Cursor Cloud Agents. Rejected on the hard filter; reopen
  condition: Cursor ships a review-scoped App. Model stack: in-house Composer 2.5 primary with an
  undisclosed frontier mix — non-Anthropic probable, not provable.
- **xAI/Grok ships no GitHub review product at all** — no GitHub App exists (a dozen candidate
  slugs 404 against the registry). The credible Grok routes run in OUR CI against `api.x.ai` with
  an `XAI_API_KEY` (API data: 30-day encrypted retention, no training on API traffic; xAI's
  public record includes two leaked-API-key incidents ⇒ restricted, spend-capped key discipline).
- **Correction, recorded rather than silently overwritten: DiffLens is not an AI reviewer.** The
  earlier "parked as first swap-in" entry was wrong — it is a dormant (2022-era) AST-based
  semantic diff *viewer* for TS/JS/CSS with no LLM anywhere in it. Its benign grant is a
  byproduct of not being a reviewer. Struck from the shelf.
- **Copilot's fork gap is structural, not provisioning**: automatic review fires only when the PR
  *author* has Copilot access, and billing charges the author's quota — repo owners cannot spend
  credits on contributor PRs (GitHub-acknowledged, unresolved). Even fully provisioned, Copilot
  covers maintainer/bot PRs only.

The conclusion the sweep forces: **the intersection of (AI reviewer ∧ no `contents: write` ∧
fork-PR coverage) is EMPTY in the App market.** The only architecture that meets the goal under
the hard filter is TAP-owned — the two-stage `workflow_run` design now defined in
`req-cicd-ai-review-ensemble-5` — which also seats a second vendor (Grok) in the same harness at
trivial marginal cost.

**Methodology import source (2026-08-20): Trail of Bits.** Their public `trailofbits/skills`
marketplace (CC BY-SA 4.0; ~6.7k stars, actively maintained; announced Jan 2026) is the strongest
published body of security-review agent methodology, researched when the harness went own-built:
`differential-review` (risk-score → blame/regression → blast-radius → adversarial pass over a
diff), `fp-check` (gated devil's-advocate verification before a finding ships),
`vulnerability-triage-brocards` (severity calibration), `agentic-actions-auditor` (nine attack
vectors for AI-agents-in-CI workflows — to be run against our own harness), and `second-opinion`
(multi-model findings presented side by side, never merged — independent convergence with this
spec's ensemble stance). Their published practice: ~20% of engagement bugs surfaced by AI with
every finding human-validated before delivery; their prompt-injection research
(Copilot exploitation, prompt-injection-to-RCE) is the attacker-side justification for the
diff-as-data two-stage split. **License handling:** ToB-derived
prompt/methodology text lives in the separate prompts repo (`req-cicd-ai-review-harness-repo`)
under its own declared license (CC BY-SA 4.0, attributed), never in an Apache-2.0 tree;
`semgrep-rules` and Buttercup are AGPL-3.0 — run `p/trailofbits` as an external ruleset /
separate service only, never vendored.

**The injection pre-screen sweep (2026-08-20).** Small dedicated injection-classifier models are
real and CI-runnable on CPU: **PIGuard** (MIT, ACL 2025, ~184M — trained specifically against the
trigger-word false-positive mode that PR diffs hit hardest), **Llama Prompt Guard 2 86M** (the
evals leader, purpose-built for screening untrusted third-party content, 512-token chunked
scanning — but gated under the non-OSI Llama Community License), ProtectAI's Apache-2.0 DeBERTa
(archived, unmaintained). Rebuff is archived; Lakera is a SaaS runtime dependency and out.
Sobering context that shapes the design: guard-model evasion research demonstrates up to 100%
bypass; the GitInject study of real attacks on AI-agent GitHub workflows validated NO classifier
as sufficient (structural mitigations + human review carried the weight); and at TAP's PR volume
the base rate makes most alarms false — so the pre-screen is a cost-raiser and routing signal,
never a gate. No reviewer vendor ships an ML injection pre-screen on PR content: this niche is
unoccupied, and the Unified AI Review harness would be early. Shortlist and design consequences:
run sheet.

**First-party as a permission strategy.** GitHub Copilot code review is not a third-party App at
all: automatic review is turned on by an org *ruleset*, so there is no new standing grant and no
vendor holding an App private key. That property — not its review quality — is why it takes the
daily-life seat. Its known cost is that it reads custom instructions from the *head* branch (a PR
can influence its own review) and that it cannot approve, request changes, or satisfy a required
review — the negative result that cements the required-check gating pattern below.

**Production ensembles.** Cloudflare's orchestrator is the reference architecture: up to seven
specialized reviewers across model families (Claude, GPT, Kimi), a coordinator model that dedups,
re-verifies uncertain findings against source, and applies a strict approval rubric; 131k
reviews/30 days, median $0.98/review, 0.6% human break-glass rate
(blog.cloudflare.com/ai-code-review). Datadog's BewAIre reviews every PR for benign/malicious with
>99.3% accuracy and 0.03% FP after months of shadow-mode curation — "curated datasets beat newer
models" (datadoghq.com/blog/engineering/malicious-pull-requests). Google (Critique ML) and Meta
(MetaMateCR) frame AI review as productivity, not a security gate.

**Reviewer independence.** CodeRabbit's "code review needs independence": models fail to catch
their own errors ~64.5% of the time (self-correction blind spot); same-family testing inflates pass
rates 9–17 points (homogenization trap). The load-bearing caveat: "Nine Judges, Two Effective
Votes" (arxiv 2605.29800) — correlated training data means N nominal reviewers ≈ far fewer
effective votes. Author-model ≠ reviewer-model is the single most consistently argued rule; since
Claude authors nearly all TAP code, a non-Anthropic reviewer is mandatory, and 2–3 vendors should
be counted as ~1.5 independent opinions, not 3. **The rule is now productized** (2026-08-12
verification): Greptile's experimental *Model Inversion* detects the authoring agent from commit
trails/branch prefixes and routes review to the opposing family (Claude Opus 4.7 ↔ GPT 5.5), on
measured grounds — Claude Opus caught 62% of high-severity bugs in GPT-authored code vs 53.7% in its
own; GPT caught 60% in Claude-authored code vs 50.5% in its own, because "the types of bugs a model
introduces most often are the same types it's more likely to miss during review"
(greptile.com/blog/model-inversion). Independent convergence on this spec's central rule.
**Corollary that decides seats, not just vendors:** a product's *brand* is not its model family —
CodeRabbit's planning layer is built on Claude (plus a post-trained NVIDIA Nemotron router), so
seating CodeRabbit does NOT discharge the non-Anthropic requirement. Independence must be verified
at the model stack, not the logo.

**Adversarial evals.** PRWeaver (arxiv 2608.02693, Aug 2026): 208 execution-validated attacks vs
production reviewers — monolithic malicious PRs caught 42–79%; fused into a plausible carrier PR
with a cover-story description, detection floor ~29%; batched review of many PRs collapses
detection to 16–22% (⇒ review per-PR, never batched); auditors often localize the risky line but
fail to name the planted capability. SecVulEval: best model 23.8% F1 on statement-level CVE ground
truth. xz retrospectives: the payload lived in build scripts + binary test fixtures — surfaces
diff-review barely sees; no credible claim standard AI review would have caught it.

**Attacks on reviewers.** CodeRabbit RCE (disclosed 2025-01, published 2025-08, Kudelski): a PR's
`.rubocop.yml` executed attacker Ruby on CodeRabbit prod, leaking the GitHub App private key ⇒
mintable write tokens for ~1M repos; fixed in days (tools now sandboxed, "tools in jail"), but the
structural risk is unchanged and is exactly one permission: **`contents: write`**, which the App
still requests. (It does *not* request `administration` — see the permission sweep above.) An App
private key sitting in a vendor's environment is a write path to every repo it is installed on,
however well the vendor sandboxes its tools. Claude Code Action —
**CVE-2025-59536** (arbitrary code execution via prompt injection embedded in PR content; bash in a
PR *title* executed by the agent) and **CVE-2026-21852** (Anthropic API-key exfiltration by the same
vector); reported by RyotaK of GMO Flatt Security, fixed in four days, hardened through spring 2026,
fixes in `claude-code-action` v1.0.94; `claude-code-security-review` self-declares "not hardened
against prompt injection." That pair is the direct evidence behind
`req-cicd-ai-review-ensemble-4` — a reviewer that both parses attacker-controlled text and holds a
key inside our pipeline is the highest-consequence configuration in the field. CamoLeak (CVSS 9.6):
hidden markdown comments prompt-injected Copilot Chat into secret exfiltration via GitHub's Camo
proxy. GhostCommit (2026): malicious instructions rendered as text *inside a PNG* referenced from
AGENTS.md — text reviewers pass it, a later vision-capable agent executes it; CodeRabbit's default
config excludes images ⇒ the blind spot is the vector. CSA's framing: an AI agent in CI "combines
the attack surface of an untrusted text interpreter with the privilege level of a trusted pipeline
actor."

**Vendor offerings (as researched 2026-08).**
- *Greptile*: whole-codebase context (vector-indexed) rather than diff-local; experimental **Model
  Inversion** (above); ~82% seeded-bug catch and ~50% more bugs than CodeRabbit on a 50-PR
  head-to-head, at the cost of measurably higher noise (11 FPs vs CodeRabbit's 2 on that benchmark);
  $30/seat (50 reviews/mo, then $1/review), free general tier since 2026-06 (50 reviews/mo) and a
  free Developer plan for qualified MIT/Apache/GPL open source — **TAP is Apache-2.0 and public, so
  it qualifies**; GitHub + GitLab only; SOC 2 Type II all tiers; no training on customer code. The
  50-review/month ceiling is the open question against TAP's measured ~44 merged PRs/30d.
- *CodeRabbit* — **rejected 2026-08-13 on `contents: write`.** Full Pro free on public repos
  (permanent, no application); **planning layer built on Claude** plus a post-trained NVIDIA
  Nemotron routing model ⇒ NOT vendor-independent from TAP's authoring model either; paid reference
  $24–30/seat/mo; GitHub App (org/user install, scopable to selected repos); summary + inline
  comments; can formally Approve only behind `reviews.request_changes_workflow` (off by default;
  not endorsed as a required-review substitute); `.coderabbit.yaml` — `profile`
  quiet/chill/assertive, `path_filters`, `path_instructions` (≤20k chars, the security-instruction
  hook), `auto_review`, 60+ bundled tools incl. semgrep + gitleaks; SOC 2 Type II; code shared with
  OpenAI/Anthropic for review, no training on customer code. Two independent disqualifiers, and the
  permission one is the hard filter.
- *OpenAI Codex*: `@codex review` / auto-review toggle via the Codex cloud GitHub integration
  (ChatGPT-plan billed; Free tier excluded — **Plus at $20/mo is the entry point that includes
  GitHub code review**; Pro 5x $100/mo since 2026-04). **Gotcha that constrains the wiring: the API
  tier carries no cloud features at all** — GitHub code review and Slack come with the
  *subscription*, not the key, so the seat is provisioned as an account, not a secret; posts a real
  GitHub review, P0/P1-focused;
  `@codex security review` variant; `AGENTS.md` "Code Review Rules" section tunes it; cloud sandbox
  runs the agent phase network-off with secrets stripped. **The cloud path is rejected on
  permissions:** its `chatgpt-codex-connector` App requests `contents: write` + `workflows: write` +
  `actions: write` (the broadest grant surveyed). `openai/codex-action@v1` runs in *your*
  CI (API-key billed), sandbox modes read-only/workspace-write, structured `output-schema` verdicts
  ⇒ first-party supported required-check gating, under a `permissions:` block GitHub enforces and we
  author. The action's own example already splits the model job (`contents: read`) from the
  comment-posting job (`pull-requests: write`, no model).
- *Anthropic*: `anthropics/claude-code-action` (interactive @claude / automation mode; API key,
  subscription OAuth token, OIDC federation, or Bedrock/Vertex; the most detailed vendor
  prompt-injection hardening — content sanitization, untrusted-ref discipline, base-branch config
  restoration). `anthropics/claude-code-security-review` — security-only semantic diff review,
  confidence-filtered, advisory by default, self-declares "not hardened against prompt injection."
  Managed *Claude Code Review* (Team/Enterprise research preview): specialist-agent fleet on
  Anthropic infra, verification pass filters FPs, ~$15–25/review, deliberately-neutral check run
  plus a documented recipe for building your own blocking check from its severity JSON.
- *GitHub Copilot code review*: comments only; cannot approve/request-changes/satisfy required
  reviews — the negative result that cements the required-check gating pattern. **First-party, so
  there is no App to install and no standing third-party grant** — turned on by an org ruleset
  ("Automatically request Copilot code review", with "Review new pushes" and Balanced effort).
  Requires a Copilot Pro licence or higher for automatic review ($10/mo); public repos are exempt
  from the usage-based billing introduced 2026-06-01, so the per-review cost here is zero. GitHub's
  complimentary-Pro programme for verified open-source maintainers is real but **not pursued** — it
  is aimed at maintainers of established projects and TAP does not clear that bar today. Reads repository custom instructions from `.github/copilot-instructions.md` **on the
  head branch**.
- *Codacy* (`codacy-production`, verified `contents: read`): SAST, SCA, secrets detection and
  duplication analysis as a GitHub App; free and unlimited for public repositories, no time limit;
  optional `.codacy.yml` at the repo root (defining it makes the UI's ignored-files settings stop
  applying). Security *observability*, not a reviewer — it produces findings, not verdicts.
- *SonarQube Cloud* (`sonarqubecloud`, verified `contents: read`): rules, vulnerabilities and a
  quality gate; free plan covers unlimited public projects. **Python is supported by Automatic
  Analysis**, so it needs no workflow, no `SONAR_TOKEN` and no `sonar-project.properties` — the
  cheapest seat to stand up. Known limits: no coverage import, no monorepo support, no non-main
  branch analysis (PR analysis does work), no analysis logs. Coverage would require CI-based
  analysis and therefore a secret.

**Standards.** SLSA Source Track L4 = two or more trusted *persons*; AI does not count (a "Trusted
Robot" policy-exception seam exists; L1–3 are the honest solo-maintainer target). OpenSSF
"Securing Open Source in the Age of AI" (2026-05): AI review has "reached acceptable quality to
accelerate security outcomes for constrained maintainers"; robots over-inflate severity; publish an
AI policy; threat-model first. OWASP LLM Top 10 / Agentic Top 10 supply the reviewer-threat
vocabulary. Linux kernel: AI must not `Signed-off-by` (DCO is human-only — mirrors TAP's DCO
stance). Ghostty/curl wave: AI-assisted-and-human-filtered welcome, unfiltered AI slop banned; no
serious OSS project yet *mandates* an AI review pass — TAP doing so is ahead of published practice.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-ai-review-ensemble | [Independent Reviewer Ensemble](#independent-reviewer-ensemble) | Proposed | ≥2 vendors; author-model ≠ reviewer-model — a non-Anthropic reviewer is mandatory while Claude authors; no seat holds `contents: write` |
| req-cicd-ai-review-least-privilege | [Reviewer Least Privilege](#reviewer-least-privilege) | Proposed | Read + comment only; verify every App grant with `gh api /apps/<slug>` before install; per-reviewer trust-delta named |
| req-cicd-ai-review-harness-repo | [Harness Repository And License Boundary](#harness-repository-and-license-boundary) | Proposed | Two dedicated org repos — Apache-2.0 machinery, separately-versioned prompts repo with its own license(s) — pulled together at pinned SHAs; consumers call via SHA-pinned shims; third-party methodology only as reviewed vendored snapshots |
| req-cicd-ai-review-untrusted-content | [PR Content Is Untrusted Input](#pr-content-is-untrusted-input) | Proposed | Injection-aware config; unreviewable binaries/images are findings; per-PR review unit; the security lens sits on the base-branch seat |
| req-cicd-ai-review-gate | [TAP-Owned Fail-Closed Gate](#tap-owned-fail-closed-gate) | Proposed | Blocking = required check over machine-readable verdicts (the `gate` pattern); never a bot approval |
| req-cicd-ai-review-graduation | [Advisory Then Blocking](#advisory-then-blocking) | Proposed | Phase 1 advisory; graduate only measured, security-severity findings to blocking |
| req-cicd-ai-review-verdict-ledger | [Verdict Ledger](#verdict-ledger) | Proposed | Machine-legible review verdicts retained as an audit trail; named AI consumer per `req-ai-name-the-consumer` |
| req-cicd-ai-review-prior-art | [Maintain The Prior-Art Ledger](#maintain-the-prior-art-ledger) | Proposed | The ledger above is standing canon with named update triggers |
| req-cicd-ai-review-honest-limits | [Name What This Does Not Do](#name-what-this-does-not-do) | Proposed | Not SLSA two-person; correlated votes; multi-PR/build-script/binary gaps; admin-compromise residual |

---

### Independent Reviewer Ensemble
----
RID: `req-cicd-ai-review-ensemble`
Status: `Proposed`

Every code-bearing PR targeting `main` receives review from **at least two AI reviewers from
different vendors**, chosen so that the reviewer set is independent of the authoring model.

#### Implementation

- **Author-model ≠ reviewer-model is the non-negotiable rule.** TAP is authored overwhelmingly by
  Claude (the beanbag); therefore at least one reviewer MUST be non-Anthropic (Codex/GPT family).
  This is the strongest-evidenced ensemble rule (self-correction blind spot; homogenization trap).
- **The hard filter is `contents: write`.** No reviewer holds a write path to code. This is not a
  preference to be traded against review quality — it is the property that makes a steered or
  compromised reviewer degrade to "wrong comment" instead of "compromised repository", and it
  eliminated nearly the entire market (see the permission sweep in the ledger above).
- **v0 roster (REBUILT 2026-08-13; RE-ARCHITECTED 2026-08-20 — two reviewing seats in one
  TAP-owned two-stage harness on every PR, Copilot on maintainer PRs, two security-observability
  seats):**
  1. **GitHub Copilot code review** — **UNPARKED 2026-08-20** (org ruleset live; the org's Copilot
     billing API now reports `plan_type: business`). The daily-life hygiene seat on maintainer and
     bot PRs. **It does not and cannot cover contributor PRs**: automatic review fires only when
     the PR *author* has Copilot access and bills the author's quota (structural,
     GitHub-acknowledged, unresolved) — so it counts toward the ensemble on maintainer PRs only.
  2. **OpenAI Codex (GPT family) — via the two-stage `workflow_run` harness**, not
     `openai/codex-action`: the action's own actor-permission check rejects fork authors, so the
     privileged stage calls the OpenAI API directly (`req-cicd-ai-review-ensemble-5`). The
     harness machinery is hosted in the dedicated harness repo and consumed through SHA-pinned
     shims (`req-cicd-ai-review-harness-repo`). The independence leg
     (`req-cicd-ai-review-ensemble-2`). Billed as API usage on a restricted, spend-capped key.
  3. **xAI Grok — the second seat, in the SAME two-stage harness** (same diff artifact, separate
     `XAI_API_KEY`), seated 2026-08-20 because the harness makes a second vendor nearly free and
     no installable vendor clears the hard filter. Together with Codex this puts two independent
     non-Anthropic reviewers on EVERY PR including forks — `req-cicd-ai-review-ensemble-1` is met
     when the harness lands. Key discipline stricter than usual given xAI's two public
     leaked-API-key incidents: restricted key, hard spend cap, rotate on doubt.
  4. **Codacy** and **SonarQube Cloud** — security *observability*, not reviewers. Third-party Apps,
     both verified `contents: read`, both fork-covering. They produce findings (SAST, SCA, secrets,
     rules), not verdicts, and they do not count toward `req-cicd-ai-review-ensemble-1`.
- **This roster reverses `req-cicd-ai-review-ensemble-4`, deliberately.** The 2026-08-12 roster was
  all-vendor-infrastructure specifically so that no reviewer executed in TAP's CI holding a TAP
  secret. The permission sweep showed that property was unpurchasable: every vendor offering it
  wanted `contents: write` in exchange. Given the choice between *a third party holding a write key
  to every repo* and *a read-only job in our own CI holding one API key we can rotate*, the second
  is the smaller surface — the blast radius of the first is the whole org, the second is one
  OpenAI bill. The CVE-2025-59536 / CVE-2026-21852 concern that motivated ensemble-4 is answered by
  configuration rather than by absence: `safety-strategy: read-only`, `permissions: {}` at the
  workflow top level, `persist-credentials: false`, and the model job holding no write scope at all.
  See the amended criterion below.
- **The malicious-change lens is CONFIGURATION ON EVERY SEAT, not a third agent.** A dedicated
  security reviewer (`anthropics/claude-code-security-review`) remains **deferred, not eliminated**,
  but the reason has narrowed. It is no longer "no reviewer runs in our CI" — Codex now does. It is
  that the action self-declares "not hardened against prompt injection", it is same-family with the
  authoring model so it adds correlated rather than independent judgement, and a third seat costs
  triage attention a solo maintainer does not have. CVE-2025-59536 and CVE-2026-21852 (fixed in
  `claude-code-action` v1.0.94) are the reason any such seat would be configured per
  `req-cicd-ai-review-ensemble-5` rather than the reason to refuse it. Revisit if the Phase-2
  observation window shows a dedicated lens catching a class the seated reviewers miss.
- **Count votes honestly.** Until the harness lands, the built reality is Copilot on
  maintainer/bot PRs and **nothing on fork PRs** — `req-cicd-ai-review-ensemble-1` is **not met**;
  see the named exception in its acceptance criteria. When the two-stage harness lands, every PR
  (forks included) gets Codex + Grok, and maintainer PRs get Copilot as a third eye. Correlated
  errors still apply: two vendors ≈ 1.5 effective independent opinions, not 2.
- **Alternatives on the shelf, all now blocked by the hard filter.** *Greptile* (whole-codebase
  context; its experimental **Model Inversion** auto-detects the authoring agent from commit
  trails/branch prefixes and routes review to the opposing family — this spec's independence rule,
  productized; free for Apache-2.0 OSS) was the strongest technical alternative and is out on
  `contents: write`, not on noise. *CodeRabbit* likewise. *Cursor Bugbot* joined them 2026-08-20
  with the broadest grant yet surveyed (see the fork-coverage sweep); its reopen condition is a
  review-scoped App. `difflens` was struck from the shelf the same day — not an AI reviewer at all
  (see the sweep's correction). Reopening any rejected vendor requires a fresh
  `gh api /apps/<slug>` showing the grant has actually narrowed.
- Both reviewers' instructions MUST explicitly target the malicious-change class:
  instruction-like content in diffs/comments, capability-adding changes with cover-story
  descriptions, CI/build-script modifications, dependency/lockfile edits, encoded/obfuscated blobs.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-ensemble-1 | Two Vendors Minimum | Proposed | Every code-bearing PR to main is reviewed by ≥2 AI reviewers from different vendors. | **NOT MET as of 2026-08-20** — nothing reviews fork PRs yet, and Copilot covers maintainer/bot PRs only (structural author-pays rule). Named rather than quietly relaxed. Closure path: the two-stage harness seats Codex + Grok on every PR including forks. Docs-tier PRs MAY be exempt (change-tier). |
| req-cicd-ai-review-ensemble-2 | Non-Author Vendor | Proposed | While Claude is the primary authoring model, ≥1 reviewer is non-Anthropic. | The independence leg. |
| req-cicd-ai-review-ensemble-3 | Malicious-Change Lens | Proposed | EVERY seated reviewer runs explicit malicious-change/smuggling instructions, not generic review prompts. | The #1-with-a-bullet job; carried by config on both seats, not by a specialist agent. |
| req-cicd-ai-review-ensemble-4 | No Reviewer Holds Code Write | Proposed | No seated reviewer — App or action — holds `contents: write` or any other write path to code. Verified per seat with `gh api /apps/<slug>` (Apps) or an explicit `permissions:` block (actions) before install. | **Amended 2026-08-13**, replacing "No CI-Resident Reviewer At v0". The original forbade CI residency as a proxy for this property; the permission sweep showed the proxy inverted — the all-vendor rosters all required `contents: write`, while a CI-resident action can be pinned read-only. The reasoning is preserved in `doc-cicd-ai-review-plan.md`. |
| req-cicd-ai-review-ensemble-5 | CI-Resident Reviewers Are Hardened (Two-Stage Fork Coverage) | Proposed | CI-resident review runs as a two-stage design. Stage 1, UNPRIVILEGED (`pull_request`): no secrets, workflow-level `permissions: {}`, `persist-credentials: false`; it only computes the PR diff and uploads it as a size-capped artifact. Stage 2, PRIVILEGED (`workflow_run`, base-repo context): holds the vendor API keys; NEVER checks out, builds, or executes PR content — the diff and PR metadata are consumed as data only; its prompt comes from the base/default branch; it resolves PR identity from the `workflow_run` event and GitHub API, never from artifact contents; the model job holds no write scope, and the comment-posting job (`pull-requests: write`) runs no model. All actions SHA-pinned. | **Amended 2026-08-20**, replacing the single-stage `pull_request` shape: GitHub withholds repo secrets from fork `pull_request` runs, so single-stage structurally cannot review contributor PRs. The forbidden thing was never `workflow_run` itself but privileged execution of PR-controlled content (`req-cicd-ai-review-least-privilege-3`); this shape is GitHub's own recommended pattern for privileged processing of untrusted PRs. Answers CVE-2025-59536 / CVE-2026-21852 plus the artifact-poisoning class (forged PR number in an artifact re-targeting a review). |
| req-cicd-ai-review-ensemble-6 | Seats Fail Loud | Proposed | A seat that produces no verdict — rate limit, quota/token exhaustion, API outage, timeout, malformed response — surfaces as a visible failure: a red job on the run and an explicit absence marker where the verdict would have appeared. Never a silent skip. | Advisory phase included — an unnoticed dead reviewer is the it-was-on-but-unread failure. In the blocking phase this is `req-cicd-ai-review-gate-2` fail-closed. |

---

### Reviewer Least Privilege
----
RID: `req-cicd-ai-review-least-privilege`
Status: `Proposed`

A reviewer **reads the PR and posts comments/verdicts — nothing else.** Every documented reviewer
compromise exploited privileges beyond that. This is `req-cicd-runner-least-privilege` applied to
the reviewer class, plus the trust-delta doctrine applied to third-party reviewer *apps*.

#### Implementation

- **Strongest form first: verify the grant before installing anything.** `gh api /apps/<slug> --jq
  '.permissions'` against GitHub's own registry, not the vendor's marketing, and the install
  consent screen as the authoritative check at install time. That one command caught every problem
  in the roster rebuild — including a vendor whose App wanted `contents: write` + `workflows: write`
  + `actions: write` while being sold as a read-only reviewer. An App that requests write access to
  code is rejected; there is no configuration that takes it back, because the grant lives on the
  vendor's key and not in our repository.
- **Prefer, in order: (1) first-party mechanisms with no standing grant** — Copilot review is an org
  ruleset, not an App, so there is nothing to compromise on a vendor's side; **(2) a read-only job in
  our own CI**, where the permission block is ours, versioned, reviewable and enforced by GitHub;
  **(3) a third-party App verified `contents: read`.** The 2026-08-12 ordering put "runs on vendor
  infrastructure" above all three. That was wrong, and the permission sweep is why: vendor infra
  bought us "no TAP secret at risk" only by handing the vendor a write key to every repo in the org.
  A rotatable API key in our CI is the strictly smaller loss. **Named residual:** an action in our
  CI does parse attacker-controlled PR content next to a secret — bounded by
  `req-cicd-ai-review-ensemble-5`'s hardening and by that secret being a single-vendor API key with
  no repository access, not by absence.
- **CI-resident reviewers (in our CI):** the two-stage shape of `req-cicd-ai-review-ensemble-5` —
  an unprivileged `pull_request` stage that captures the diff, and a privileged `workflow_run`
  stage that runs base-branch code exclusively and never executes PR content; `permissions:`
  read-only plus `pull-requests: write` solely for the comment step; SHA-pinned per
  `req-cicd-runner-least-privilege-4`; API keys as repo secrets, reachable only by the privileged
  stage. (GitHub withholding secrets from fork `pull_request` runs is exactly why the privileged
  stage exists.)
- **App-based reviewers (vendor infra) install ORG-WIDE, on purpose.** `unified-systems-com` exists
  to house purely TAP systems — all open source, all at one protection level — so the org boundary
  *is* the policy boundary and the reviewer floor applies to every repo in it, present and future.
  A hand-maintained selected-repo allowlist is **rejected** here: in a homogeneous org it is not a
  tighter control but a drift generator, since each new plugin repo would sit silently below the
  floor until someone remembered a click, and the omission is invisible. "Every repo in this org is
  reviewed" is checkable; "the repos someone remembered" is not.
- The invariant that keeps this honest: **org homogeneity**. Anything that ever needs a different
  protection level belongs in a *different org*, never as an in-org exception. Admitting one
  exception converts the floor from an invariant into a convention.
- No bot's formal Approve / Request-changes state is ever load-bearing. Each app's permission grant
  is **recorded at install time** and reviewed like `tap-renovate`'s — an App requesting
  `administration` reaches the root-of-trust surface (`spec-cicd-root-of-trust.md`) and is a
  decision, not a reflex-accept. The standing verification query lives in the run sheet's checklist:
  `gh api /orgs/unified-systems-com/installations` should show `contents: read` for every reviewer
  App, write only for TAP's own automation (`tap-renovate`, `tap-release-please`), and
  `administration` nowhere.
- Prefer **org-level reviewer configuration** over per-repo files where the vendor supports it.
  Copying one security instruction into 15 repos violates derive-a-fact-once and yields 15 silently
  diverging copies. Where that org configuration lives in a vendor dashboard rather than in git, it
  is an **external-configuration-ratchet** case (`req-cicd-rot-config-ratchet`): commit the intended
  configuration and check the live state against it. Sonar's "automatically import new repositories"
  and the org-wide Copilot ruleset are the same floor property applied to their seats.
- The named residuals, now that no seat holds code write:
  - **Vendor-side compromise of a `contents: read` App is org-wide source disclosure, not
    modification.** TAP is entirely public and Apache-2.0, so the disclosure loss is approximately
    zero — which is a real reason this roster is affordable here and would not be elsewhere. It is
    still a foothold for reconnaissance, and re-reviewed on any vendor incident.
  - **The CI-resident harness holds two API keys (OpenAI, xAI).** Compromise is vendor billing
    abuse, not repository access. They are repo secrets exposed only to the privileged stage —
    which runs base-branch code only and never executes PR content — hard spend-capped at the
    vendor, and rotatable in minutes. The named delta vs the retired single-stage design: the keys
    are now present in runs *triggered by* fork activity, and the boundary holding them apart from
    attacker code is the two-stage split itself (`req-cicd-ai-review-ensemble-5`), which is why its
    constraints are load-bearing rather than stylistic.
  - **A compromised seat can still lie.** Every seat can be steered into a soft review; none can act
    on it. That is the trade this roster makes deliberately.
- Reviewers never hold or mint credentials beyond their own vendor key; reviewer workflows carry no
  other repo secrets.
- **Critical plumbing is code-owned** (2026-08-20; **made real 2026-08-21**). The CODEOWNERS
  mechanism (contract: `spec-dev-validation.md` § guard-system meta-integrity) extends across the
  reviewer surface: `.github/**`, build/exec plumbing (`Dockerfile*`, `docker/`,
  `docker-compose*.yml`, `.githooks/`), the gate/promote scripts, and BOTH harness repos carry
  CODEOWNERS. **A CODEOWNERS file binds nothing by itself** — PR #99 (2026-08-21) proved it: a
  PR editing reviewer configuration auto-merged with zero human review while all three AI
  reviewers flagged it, because no ruleset required code-owner review. The enforcement is
  **two-account review**: `@criticalsec` (George's second account, write access, approvals-only,
  NEVER authenticated on the dev laptop) is co-owner on every owned path, and the ruleset
  requires code-owner review with required-approvals 0 — ordinary PRs auto-merge untouched;
  owned-path PRs block until the second account approves, since the authoring account cannot
  approve its own PRs. The approvals-0 + code-owner-review interplay is verified empirically
  (a blocked owned-path PR and an auto-merged clean PR), never assumed.
  **Second live finding (PR #101, 2026-08-21): a correct rule with a bypassed actor is no rule.**
  The freshly-saved PR/code-owner requirement was silently swallowed by the ruleset's standing
  `RepositoryRole: admin, bypass_mode: always` entry — the owned-path PR merged with zero
  approvals again. The bypass list on `main-required-checks` is now **EMPTY** (verified
  `bypass_actors: []`), which also makes the `gate` check genuinely required for admins for the
  first time and retires the direct-push bootstrap hatch on tap. Break-glass is deliberate and
  loud: the org owner can edit the ruleset itself, an audit-logged act — a fire axe behind
  glass, not a propped-open door.
- **Org-wide is the named end state: protection-by-declaration.** One org-level rule (require-PR
  + code-owner review, approvals 0, dismiss-stale, empty bypass) over all repos, where **a repo
  is protected exactly by declaring a CODEOWNERS file** — adding the file auto-enrolls a new
  repo with no ruleset edit, and the drift check reduces to one query ("which repos lack a
  CODEOWNERS"), run in the external-configuration-ratchet pattern. Two preconditions gate the
  flip, both named: (1) GitHub bundles code-owner review inside require-PR, which applies to
  every targeted repo unconditionally — so (2) `release-plugin.sh`'s direct pushes to plugin
  repo mains must first become PR-based (endorsed 2026-08-21; radar item). Until then the
  per-repo rulesets on tap and both harness repos are the floor. Standing posture: inbound suggestions to
  "improve" build plumbing get the heaviest scrutiny in the review — plumbing is where one change
  defeats every other control, and reviewer prompts already flag such diffs as findings
  (`req-cicd-ai-review-untrusted-content-5`).
- **Plumbing is static by SOP; inbound plumbing PRs are anomalies.** The org's `.github`
  repository (org-wide defaults: SECURITY.md, PVR config) and every repo's `.github/**` change
  rarely, and only from maintainer sessions — nobody issues PRs against them as standard
  operating procedure. GitHub cannot prevent a PR from being *opened*, so the gate is layered:
  two-account code-owner review blocks the merge until the second account approves (see the
  code-owned bullet above — a CODEOWNERS file without the ruleset is a no-op), reviewer prompts
  flag the diff as a finding in its own right (`req-cicd-ai-review-untrusted-content-5`), and an
  unsolicited third-party PR touching plumbing is treated as a probe — reviewed under that
  assumption and escalated out-of-band (`req-cicd-ai-review-untrusted-content-7`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-least-privilege-1 | Read And Comment Only | Proposed | No reviewer holds a write path to code, a shared secret store, or unnecessary tool/network access. | |
| req-cicd-ai-review-least-privilege-2 | Org-Wide Install Floor | Proposed | Reviewer apps are installed across ALL repositories in `unified-systems-com` so every repo inherits the same floor; grants recorded at install, trust-delta named. | The org is single-purpose (all TAP, all public, one protection level). A per-repo allowlist would generate silent drift below the floor. Homogeneity is the invariant: differing protection needs go in a different org. |
| req-cicd-ai-review-least-privilege-3 | No Privileged Execution Of PR Content | Proposed | Reviewer workflows never combine `pull_request_target`/`workflow_run` with untrusted checkout — a privileged (secret-holding) stage never checks out, builds, or executes anything the PR controls; PR content crosses into privileged context only as data (a size-capped diff artifact, API-fetched metadata). | GitHub pwn-request class. Clarified 2026-08-20: the two-stage design (`req-cicd-ai-review-ensemble-5`) complies — the trigger was never the hazard; privileged execution of PR content is. |
| req-cicd-ai-review-least-privilege-4 | Verify The Grant Before Installing | Proposed | Every GitHub App is checked with `gh api /apps/<slug> --jq '.permissions'` before install, the consent screen is read at install, and the observed grant is recorded. An App requesting write access to code is rejected outright. | Generalizes past reviewers: this is now the rule for ANY App on `unified-systems-com`. The command is what caught every problem in the 2026-08-13 rebuild. |
| req-cicd-ai-review-least-privilege-5 | Plumbing Is Code-Owned (Two-Account Review) | Proposed | CODEOWNERS covers CI/build plumbing (`.github/**`, Dockerfiles, compose files, `.githooks/`, gate/promote scripts) in every org repo including both harness repos, with `@criticalsec` as second-account co-owner and code-owner review REQUIRED in the ruleset (approvals 0, so unowned paths keep auto-merging); the second account never authenticates on the dev laptop; policy-data carve-outs (ratchet baselines) stay per `spec-dev-validation.md`. | A no-op without the ruleset — demonstrated live by PR #99 (2026-08-21), which auto-merged reviewer-config edits unwitnessed. Enforcement pending the ruleset flip + empirical verification pair. |

---

### Harness Repository And License Boundary
----
RID: `req-cicd-ai-review-harness-repo`
Status: `Proposed`

The harness machinery is **wholly independent of its prompts** — implemented as **two dedicated
repositories in `unified-systems-com`**: **`unified-ai-review`** (machinery) and
**`unified-ai-review-prompts`** (prompts). Named 2026-08-20; the **Unified** brand on these
public, reusable surfaces is deliberate. Consumed by every org repo through thin shim workflows.
Decided 2026-08-20 (the two-repo split the same day, from in-flight review): the machinery/prompt
split is what lets others maintain their own prompt lists, and the prompts repo is also where
non-Apache licenses live.

#### Implementation

- **The machinery repo (Apache-2.0).** Reusable workflows (`workflow_call`) and the
  capture/review scripts. It contains NO prompt content and no third-party-derived text — wholly
  ours, wholly reusable. Its contract with prompts is a **standard directory layout** it pulls
  prompt lists into and reads from.
- **The prompts repo (its own license(s), declared inside it).** Prompt lists in the standard
  layout, organized as **named prompt packs** — `security` is pack #1, deliberately not the only
  or the last: code-quality, best-practices, and standards packs ride the same mechanism
  (backlogged on the radar). Tracked, versioned, and swapped **independently of the machinery**.
  Trail-of-Bits-derived material lives here under CC BY-SA 4.0 with attribution, alongside our
  own prompts under our terms. (Creative Commons itself recommends against CC licenses for
  software; the CC license holds prose/prompts, never code.)
- **The machinery pulls prompts at a PINNED ref into the standard location.** The consumer's shim
  (base-branch, PR-immune) declares the prompts repo + full commit SHA as workflow inputs; the
  privileged stage fetches exactly that ref. A prompt change is a pin bump — a deliberate,
  reviewed change. This is the narrow, sanctioned exception to no-run-time-fetch: **pinned by
  SHA, from an org-owned repo, reviewed at every bump — never a floating ref, never a
  third-party source.**
- **Third-party methodology still enters ONLY as a vendored snapshot** in the prompts repo,
  pinned at a reviewed commit. A live fetch would put the vendor's repo inside the reviewer's
  trust boundary (the poisoned-release gap applied to reviewer content); a pinned,
  read-at-import snapshot is the same discipline as SHA-pinned actions.
- **Consumers carry thin shims, pinned by SHA — both pins.** Each org repo (TAP and plugins
  alike — the org floor of `req-cicd-ai-review-least-privilege-2` applies) holds two shim
  workflows: stage-1 capture on `pull_request` and stage-2 review on `workflow_run`, calling the
  machinery by **full commit SHA** and naming the prompts pin, per
  `req-cicd-runner-least-privilege-4`. Both harness repos are in the org, get the same shims,
  and are reviewed by the harness themselves.
- **Config immunity gets strictly stronger.** Prompts and machinery live in repositories that no
  PR-under-review can touch at all — an upgrade over base-branch immunity
  (`req-cicd-ai-review-untrusted-content-4`). Within the two repos,
  reviewer-config-edits-are-findings (`req-cicd-ai-review-untrusted-content-5`) applies to their
  own PRs.
- **Bring-your-own-prompts is the interface.** Any consumer points their shim at their OWN
  prompts repo and ref; the machinery's contract is the standard layout, not our content.
  External consumers inherit Share-Alike only if they build on our CC BY-SA prompt files.
- **Harness credentials (`/manage-secret` reviewed: OpenAI and xAI, both 2026-08-20).**
  `OPENAI_API_KEY` and `XAI_API_KEY` are **GitHub Actions repository secrets** on consuming
  repos — deliberately OUTSIDE the tap-cares envelope system: they never enter the container,
  `~/tap-secrets`, or any boot profile, so no TAP scope/kind/health-probe exists for them.
  Consumer: the privileged stage's model jobs only. Least-privilege shape: a dedicated project
  (OpenAI) / team (xAI) at the vendor, a HARD spend cap, restricted to model inference; minted
  and set by George (`gh secret set`), the value never passing through an agent session.
  Rotation: re-mint at the vendor and re-set the repo secret — nothing else ever holds the
  value. Detectability: both shapes are pattern-covered in `tap/credential_patterns.py`
  (`openai-api-key`: `sk-(proj|svcacct|admin)-` + 40-char floor; `xai-api-key`: `xai-` + 40-char
  alphanumeric floor), with detected/near-miss tests in `tap/tests/test_credential_patterns.py`.
- **Sequencing (center-of-gravity discipline):** milestone 1 is the minimal two-seat harness plus
  a minimal prompts repo reviewing real TAP PRs; the Trail-of-Bits-adapted prompt phases (run
  sheet import queue) are iteration 2, not a precondition.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-harness-repo-1 | Machinery/Prompt Separation | Proposed | The machinery repo contains no prompt content; prompts load only from the prompts repo's standard layout at a pinned ref; either repo can change without touching the other. | The property that makes bring-your-own-prompts real. |
| req-cicd-ai-review-harness-repo-2 | No Live Third-Party Content | Proposed | Third-party review methodology/prompts enter only as vendored snapshots pinned at a reviewed commit; run-time fetches are limited to org-owned repos at full-SHA pins. | Trusting a vendor at a read hash, never at HEAD. |
| req-cicd-ai-review-harness-repo-3 | Shims Pin By SHA | Proposed | Every consumer shim pins the machinery AND the prompts ref by full commit SHA; bumps are deliberate reviewed changes. | `req-cicd-runner-least-privilege-4` applied cross-repo. |
| req-cicd-ai-review-harness-repo-4 | Licenses Live In The Prompts Repo | Proposed | The machinery repo is Apache-2.0 with no foreign-licensed text; the prompts repo declares its own license(s) internally (CC BY-SA 4.0 with attribution for ToB-derived files); no Share-Alike text enters any Apache-2.0 tree. | License boundary = repo boundary. |

---

### PR Content Is Untrusted Input
----
RID: `req-cicd-ai-review-untrusted-content`
Status: `Proposed`

Everything a PR controls — title, body, comments, commit messages, code comments, file contents,
images, tool configs — is **untrusted input to the reviewer**. Injection is assumed possible; the
design absorbs a steered verdict rather than pretending to prevent steering.

#### Implementation

- Prefer reviewer configurations that sanitize PR-derived content (claude-code-action's stripping
  of HTML comments/invisible characters/alt-text is the current best-in-class; Cloudflare's
  boundary-tag stripping is the pattern).
- **An unreviewable file is a finding, not a skip** (the GhostCommit lesson): a PR adding or
  modifying binary blobs, images in code paths, or opaque encoded content gets flagged by policy —
  reviewer prompts say so explicitly. TAP has little legitimate binary churn; the FP cost is low.
  **And the screen is deterministic, not just prompted** (2026-08-20): the harness detects
  binary/image additions mechanically (git's binary markers in the diff stat plus an extension
  screen) and posts the finding regardless of what any model says — LLM attention is a lens, not
  a control, and this particular check costs a few lines of shell.
- **Per-PR review unit, never batched** (PRWeaver: batching collapses detection 3×). TAP's
  one-PR-per-promote flow already satisfies this; keep it true.
- **PR metadata is an input, split by trust.** The privileged stage feeds the model two labeled
  buckets: **trusted facts fetched server-side from the GitHub API** — author login, author
  association (owner / member / contributor / first-time contributor), account age, changed-file
  list, target branch — and **untrusted attacker-controlled text** — title, body, commit
  messages, the diff itself. The prompt names the buckets so provenance survives into the model's
  reasoning. The standing rule: **identity may raise scrutiny, never lower it.** "First-time
  contributor, young account, touching `.github/**`" sharpens review; "author is the maintainer"
  must not soften it, because the compromised-maintainer machine is this spec's #1 threat.
- **Injection pre-screen, before the seats (2026-08-20).** The harness runs a cheap dedicated
  detection pass over the PR's text and diff BEFORE the model seats: a small vendored
  injection-classifier model (shortlist researched 2026-08-20, PIGuard/MIT first — see the run
  sheet; pinned per `req-cicd-ai-review-harness-repo-2`, CPU-class so it runs even when seats
  are down) plus
  deterministic indicator checks — hidden HTML comments, invisible/bidi characters, image
  alt-text payloads, instruction-like imperatives aimed at reader-agents. A hit does not
  suppress the review — the seats still run, forewarned by the flag — it escalates
  (`req-cicd-ai-review-untrusted-content-7`).
- **Injection is a finding with an out-of-band response path.** A malicious input aimed at the
  reviewers is not an ordinary review finding to be argued down in the PR thread the attacker
  controls: it fails the run red and raises a signal outside the PR conversation, loudly.
- Injection degrades to "wrong verdict": the gate (`req-cicd-ai-review-gate`) fails closed on a
  *missing* verdict, and a forged *approving* verdict from one reviewer still faces the other
  reviewers and the human — which is why approve-the-backdoor is named, not solved, in
  `req-cicd-ai-review-honest-limits`. **This is the whole control, and it is structural rather than
  contractual**: because no reviewer holds `contents: write` (`req-cicd-ai-review-ensemble-4`), the
  blast radius of a successful injection is a wrong comment, enforced by GitHub rather than promised
  by a vendor. Defence-in-depth on top of that would cost more than the risk it removes.

**Two seat-specific injection findings (2026-08-13), recorded because they shape the design and are
deliberately not engineered around:**

- **A PR can influence its own Copilot review.** Copilot reads `.github/copilot-instructions.md`
  from the *head* branch, so a PR editing that file changes the instructions used to review it.
  Real, and accepted: it buys an attacker a softer comment, not a write, and Copilot is the hygiene
  seat rather than the security one. Two things bound it — the security lens lives on the seat that
  is immune (below), and **any edit to reviewer configuration is itself a prompt-level finding** on
  every seat (`.github/copilot-instructions.md`, `.github/instructions/**`, `.github/workflows/**`,
  `AGENTS.md`, `CLAUDE.md`). A PR editing these is editing its own review, and must say so out loud.
- **The harness seats are structurally immune to the same trick**, because their prompt lives in
  the workflow file on the base/default branch — both the `pull_request` stage and the
  `workflow_run` stage run base-branch workflow definitions, so the PR under review cannot edit
  the instructions being applied to it. **This is why the malicious-change lens belongs
  in the workflow prompt rather than in a checked-out file**: it costs nothing and lands the
  security job on the seat that happens to be un-steerable. A checked-out `AGENTS.md` or
  instructions file would forfeit that property for no gain.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-untrusted-content-1 | Sanitizing Configs | Proposed | Reviewer configs enable available content-sanitization and injection mitigations. | |
| req-cicd-ai-review-untrusted-content-2 | Unreviewable = Finding | Proposed | Binary/image/opaque additions in code paths are flagged findings, not silent skips — detected deterministically by the harness (diff binary markers + extension screen), with the finding posted independently of model output. | GhostCommit. Deterministic since 2026-08-20: screening for images is cheap; model attention is not a control. |
| req-cicd-ai-review-untrusted-content-3 | Per-PR Unit | Proposed | Review scope is one PR; no batched multi-PR review mode is adopted. | PRWeaver. |
| req-cicd-ai-review-untrusted-content-4 | Base-Branch Instructions For The Security Seat | Proposed | The seat carrying the malicious-change lens reads its instructions from a location the PR under review cannot edit — the base/default-branch workflow file, not a checked-out file. | Copilot reads head-branch instructions; the harness seats do not. Put the security job on the immune seats. The harness repo (`req-cicd-ai-review-harness-repo`) strengthens this further: instructions live in a repo the PR under review cannot touch at all. |
| req-cicd-ai-review-untrusted-content-5 | Reviewer-Config Edits Are Findings | Proposed | Every seat's instructions flag any diff touching reviewer or CI configuration as a finding in its own right. | A PR editing its own review must be visible even when the edit looks benign. |
| req-cicd-ai-review-untrusted-content-6 | Identity Raises Scrutiny, Never Lowers It | Proposed | Reviewer prompts consume author/PR metadata as trust-labeled input; heightened-scrutiny rules key off identity signals, but no identity signal relaxes review depth or severity. | Compromised maintainer = threat #1; a trusted-author shortcut would blind the control exactly where it matters most. |
| req-cicd-ai-review-untrusted-content-7 | Injection Attempts Escalate Out-Of-Band | Proposed | Detected injection indicators — from the pre-screen or reported by a seat — fail the run red AND raise a signal outside the PR conversation (a security-labeled alert to the maintainer; a verdict-ledger CONCERN record), never only a PR comment the attacker can argue with. | Malicious inputs get a response path outside the standard PR flow, loud and clear. |

---

### TAP-Owned Fail-Closed Gate
----
RID: `req-cicd-ai-review-gate`
Status: `Proposed`

When AI review becomes blocking, the mechanism is a **TAP-owned required status check** — an
aggregator job in the `gate` pattern that parses machine-readable reviewer verdicts and fails
closed — **never** a bot Approve satisfying a required-review rule.

#### Implementation

- An `ai-review` aggregator (product-lines.yml sibling of `gate`, or its own workflow with a
  hand-named stable job) consumes structured verdicts: codex-action `output-schema` JSON is the
  primary contract, since that seat already runs in our CI and can emit a schema-validated verdict
  directly. Copilot review stays advisory — it posts comments with no machine verdict contract and
  cannot satisfy a required review by GitHub's own design. Codacy and Sonar expose their own status
  checks, which can be required independently of this aggregator if their signal proves worth
  blocking on; they are not verdict sources for it.
- **Fail-closed semantics mirror `gate`:** missing verdict = red; skipped = red unless the change
  tier justifies it (docs-tier exempt via `scripts/change-tier`, same as the boot gates); severity
  ≥ the blocking threshold = red. `if: always()` aggregator so a skip cannot become a false green.
- Blocking threshold: **security-class findings at high/critical**; hygiene findings never block.
- Wired into the `main-required-checks` ruleset beside `gate`; composes with the promote flow's
  auto-merge (auto-merge waits on required checks). **The admin bypass on that ruleset was
  emptied 2026-08-21** (forced by the PR #101 finding — an always-bypass had made every rule,
  `gate` included, advisory-in-fact for an admin laptop, which is exactly the
  compromised-machine path). Remaining bypass surface: org-owner ruleset edits, audit-logged.
- Break-glass: the skip-hatch is the existing loud, documented one (direct push / bypass telemetry
  in `promote-to-main.sh`), never a quiet reviewer-disable. Reviewer-service outage → re-run
  affordance + documented human-review fallback, recorded in the PR.
- This is a validation surface: the implementing change adds its **Validation Map row**
  (`req-dev-validation-map`) — the honest guard-status discipline applies to AI checks too.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-gate-1 | Required Check, Not Approval | Proposed | Blocking rides a TAP-owned required status check; no bot approval is load-bearing for merge. | |
| req-cicd-ai-review-gate-2 | Fail Closed | Proposed | Missing/unparseable verdicts and unjustified skips are red, tier-gated like the boot gates. | |
| req-cicd-ai-review-gate-3 | Security Blocks, Hygiene Advises | Proposed | Only security-class findings above the calibrated threshold block; hygiene never does. | |
| req-cicd-ai-review-gate-4 | Loud Break-Glass | Proposed | Bypass/outage paths are the existing loud documented ones; verdictless merges are visible anomalies. | |

---

### Advisory Then Blocking
----
RID: `req-cicd-ai-review-graduation`
Status: `Proposed`

Reviewers land **advisory-first**; blocking authority is granted only after a measured observation
window, and only to the security-severity slice.

#### Implementation

- Phase 1: all reviewers comment-only on every PR to main. No merge behavior changes.
- Observation window (~2 weeks / ~20 PRs): track finding volume, FP rate, latency, and at least
  informal seeded-bug spot checks. OpenSSF's warning is the calibration target: robots over-inflate
  severity — tune thresholds against *our* risk, not the reviewer's.
- Phase 2 flip: the `ai-review` gate (`req-cicd-ai-review-gate`) goes required in the same wave as
  the ruleset bypass-emptying. The flip is a deliberate, recorded decision referencing the
  observation data.
- Noise is managed in config (Copilot review effort and draft-PR exclusion; Codex severity labels
  with critical/high reserved for security-class findings; "what NOT to flag" instructions on both
  seats — formatting, import order and docstring style are already gated by black/ruff/mypy;
  Codacy/Sonar exclusion lists once we know what is actually noisy), not by ignoring reviewers — an
  ignored advisory layer is worse than none (the it-was-on-but-unread failure).
- **A filtered path is a silent path.** Exclusion lists never grow to cover `uv.lock`,
  `tap/guards/baselines/**`, vendored minified JS, or anything under `.github/` — those are exactly
  the files worth smuggling through, and "generated file" is a costume a weakened control can wear.
  Derived output with a committed generator and no smuggling value (e.g. `tailwind.css`) is the only
  legitimate exclusion.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-graduation-1 | Advisory First | Proposed | Reviewers run comment-only through a defined observation window before any blocking. | |
| req-cicd-ai-review-graduation-2 | Measured Flip | Proposed | The blocking flip cites observed volume/FP/latency data and flips only the security slice. | |

---

### Verdict Ledger
----
RID: `req-cicd-ai-review-verdict-ledger`
Status: `Proposed`

Every AI review produces a **machine-legible verdict record** that is retained and queryable — the
audit trail that makes "this merge was reviewed, by whom, concluding what" a fact, and a
merge-without-verdict a visible anomaly.

#### Implementation

- v0 is cheap: the verdicts already live on the PR (comments, check runs, action artifacts);
  the requirement is that structured verdict JSON (reviewer, model, severity, findings, PR SHA) is
  emitted and retained (action artifacts / check-run output), not just prose comments.
- **The record shape is the confidence-calibration seam** (radar item, 2026-08-20): each finding
  carries a stable id plus seat, model, severity, and PR SHA — the join keys that let a future
  contributor compute per-seat, per-severity precision against maintainer accept/dismiss
  dispositions as pure analysis over retained records. Costs nothing now; enables the seam
  without machinery redesign later.
- **Named AI consumer** (`req-ai-name-the-consumer`): the internal security AI — the same consumer
  as the `CONCERN` stream — monitors verdict records for trends: rising severity, verdictless
  merges, reviewer-disable events. George is the human consumer of the same record at review time.
- Future (demand-gated, named not built): verdicts land on the grid as TAP-managed nodes — the
  system observing its own supply chain with the same machinery it points at customer
  infrastructure. Do not build ahead of the read-only `tap_ai` surface.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-verdict-ledger-1 | Structured Verdicts Retained | Proposed | Each review emits structured verdict data tied to the PR SHA, retained beyond the PR conversation. | |
| req-cicd-ai-review-verdict-ledger-2 | Named Consumer | Proposed | The verdict stream names its AI consumer (internal security AI) and supports its queries. | |

---

### Maintain The Prior-Art Ledger
----
RID: `req-cicd-ai-review-prior-art`
Status: `Proposed`

The **Prior Art section of this spec is standing canon**, maintained over time — the record of
where the leading edge is and where TAP sits relative to it.

#### Implementation

- Update triggers (any of): a reviewer-vendor security incident; a new or materially changed
  first-party review product (OpenAI/Anthropic/GitHub/CodeRabbit); a significant benchmark or
  adversarial-eval result on malicious-change detection; SLSA/OpenSSF/OWASP movement on AI review
  as a recognized control; TAP's own observation-window data contradicting a ledger claim.
- Each sweep stamps its date at the ledger head. Entries carry enough source identity to re-find
  (org + title/venue); dead links are pruned, claims re-verified on major decisions.
- The re-evaluation posture mirrors the hardened-base-image landscape doc: alternatives (e.g. the
  managed Claude Code Review product, Copilot review, a Cloudflare-style self-built coordinator)
  are **parked, not eliminated**, with named reopen conditions.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-prior-art-1 | Triggered Updates | Proposed | The ledger is updated on the named triggers, date-stamped per sweep. | |

---

### Name What This Does Not Do
----
RID: `req-cicd-ai-review-honest-limits`
Status: `Proposed`

Per `req-sec-honest-risk`, the gaps this control does **not** close are stated where the control is
defined:

- **Not a SLSA two-person review.** AI reviewers are not "trusted persons"; TAP's claim is
  "additional detection control + forced second look for a solo maintainer," documented as a
  self-defined control. SLSA L1–3 remain the honest target; L4 is out of reach solo.
- **Correlated votes.** 2–3 vendors ≈ ~1.5 effective independent opinions; a class of error shared
  across frontier models passes all reviewers.
- **Multi-PR distributed attacks.** Detection floor ~29% for plausible-carrier attacks even with
  strong models; cross-PR evidence linking is an open research gap nobody ships. Partial mitigation:
  per-PR review + small diffs + the human's own memory.
- **Build-script / binary channels** (the actual xz vector). Partially mitigated by the
  unreviewable-file rule and CI-config-aware prompts; not closed.
- **Prompt-injected false approval — including correlated steering of BOTH seats.** A single
  injection payload rides the same diff into every model, so vendor diversity reduces but does
  not break the correlation: a clever injection that green-lights a malicious change on all
  seats at once is possible, and fail-closed catches *absent* verdicts, not forged ones. Bounded,
  not closed: no seat can act on a steered verdict (no write path), the verdicts feed a human
  merge decision rather than replacing it, and the deterministic layers — the binary/image
  screen, CODEOWNERS on plumbing, actionlint/zizmor when landed — read no prompts and cannot be
  injected. The honest statement: against a sufficiently clever injection, the AI seats degrade
  to zero added detection, and the system falls back to exactly the controls TAP had before them.
- **Advisory findings gate nothing — demonstrated on ourselves.** PR #99 (2026-08-21) modified
  reviewer configuration (the shim's model selection, the Copilot instructions) and auto-merged
  with zero human review while Copilot, the Codex seat, and the Grok seat each independently
  flagged "this PR edits its own review path." Detection worked; nothing consumed it. This is
  the worst-case shape the spec exists to prevent, executed benignly by our own pipeline. The
  response is two-account code-owner review on plumbing paths
  (`req-cicd-ai-review-least-privilege-5`), which converts those merges into a deliberate
  second-account human act; the ai-review gate's Phase-2 graduation remains the general answer.
  Residual even then: a hostile change subtle enough to survive the human's actual read, and
  compromise of the admin account itself (below).
- **Admin-account compromise trumps the gate — now via ruleset edits, not standing bypass.** The
  always-bypass for repo admins on `main-required-checks` was removed 2026-08-21 after PR #101
  demonstrated it swallowing the fresh code-owner requirement (and, by implication, `gate`
  itself, all along). What remains: a compromised ORG-OWNER account can edit or disable the
  ruleset — a loud, audit-logged act rather than a silent exemption. The gate makes malicious
  merges *loud and evidence-bearing*, not impossible; the root controls are account-level
  (passkeys/2FA on both GitHub accounts) — same calibration as guard meta-integrity
  (`req-dev-validation-meta-integrity`).
- **Reviewer availability.** A required external reviewer adds an outage mode to shipping; accepted
  with the loud break-glass (`req-cicd-ai-review-gate-4`).
- **Nothing reviews fork PRs today, and Copilot never will.** As of 2026-08-20 the built reality
  is Copilot on maintainer/bot PRs (its fork gap is structural author-pays billing, not
  configuration) and no reviewer at all on contributor PRs. `req-cicd-ai-review-ensemble-1` is
  unmet until the two-stage harness lands Codex + Grok on every PR; until then a wrong review is
  uncontradicted and a fork PR is unreviewed. This is the most significant open gap in the spec
  and should not be read past.
- **The injection pre-screen raises attacker cost; it is not a wall.** Published evasion research
  beats every guard-model class (up to 100% bypass with adversarial perturbations), and at TAP's
  PR volume the false-positive base rate means most pre-screen alarms will be false — which is
  exactly why a hit flags, routes, and escalates but never blocks or suppresses the review, and
  why the zero-FP deterministic layer (stripping/flagging hidden comments and invisible Unicode)
  sits in front of the classifier.
- **The two-stage harness's safety is a set of maintained invariants, not a GitHub default.** The
  pwn-request class is excluded by construction (privileged context never executes PR content),
  but a future edit that adds a checkout to the privileged stage, unpacks an artifact, or trusts
  a PR number read from artifact contents silently reopens it. Reviewer-config edits being
  findings (`req-cicd-ai-review-untrusted-content-5`) is the standing watch on exactly this.
- **Vendor provisioning is a live dependency, and it moves faster than this spec.** Between
  2026-04-22 and 2026-08-07 GitHub paused self-serve Copilot Business for Team orgs, replaced
  premium requests with AI Credits (2026-06-01), and shipped review effort levels — three changes
  that each invalidated part of a plan written against then-current docs. The permission sweep is
  durable; provisioning detail is not, and must be re-verified at the moment of install rather than
  trusted from a run sheet.
- **A PR can soften its own Copilot review**, because Copilot reads instructions from the head
  branch. Bounded, not closed: the security lens sits on the base-branch seat
  (`req-cicd-ai-review-untrusted-content-4`) and reviewer-config edits are findings
  (`-untrusted-content-5`). Trusting GitHub's team with the underlying fix is the deliberate default.
- **Deterministic checks on `.github/**` are missing.** The deleted CodeRabbit seat bundled
  `actionlint` and `zizmor`; nothing in the current roster replaces them, so the
  highest-consequence surface in the repository is now covered by LLM judgement alone. Both run
  without a third-party App and clear the hard filter trivially — queued, not built. Tracked in the
  run sheet's Step 0 gap table.
- **Codacy and Sonar see the source of every repo in the org.** Accepted because every repo is
  already public; it would not be accepted in an org holding anything private, which is the same
  homogeneity invariant `req-cicd-ai-review-least-privilege-2` depends on.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-ai-review-honest-limits-1 | Gaps Stated | Proposed | The above limits remain stated in this spec and are re-checked when the ledger updates. | |

---

## Radar — Named Deferrals (2026-08-20)

Backlogged on George's direction during in-flight spec review. On the radar, deliberately not
built; each names its watch trigger:

- **Grid-representation review with blast-radius-scoped tools.** A coming use case (months, not
  weeks): reviewers assessing a change against the grid/TAP analogy representation of the
  system, not just the raw diff. v0 reviewers are deliberately NO-TOOL — the injection-surface
  argument — so when tools arrive they arrive **blast-radius-scoped**: each tool grant sized to
  the change under review, never a general capability. Expect the ecosystem to ship power-tools
  for this analysis class sooner rather than later; evaluate them under the same hard filter and
  trust-delta discipline as reviewer vendors. Watch triggers: `tap_ai` read surfaces maturing;
  any vendor shipping scoped review tools.
- **Author-model-aware reviewer routing.** If the model family that authored a change would also
  be its reviewer, slot a different model into that seat — Greptile's Model Inversion (prior-art
  ledger), self-hosted in the harness. The cheap authorship signal already exists in the tree:
  `Co-Authored-By` trailers. Watch trigger: a second authoring model joining the workflow, or a
  seat's model family drifting toward the authoring family.
- **Write-block tripwire.** A reviewer/agent job attempting a write its token denies (a 403 on a
  write API) is itself high-signal — either malicious steering or an agent innocently off the
  rails — and currently vanishes into job logs. Investigate detectability (org audit-log
  streaming; wrapping the comment job's API surface; runner egress logs) and raise denials as a
  first-class alert if a detection point exists. Cheap-edge candidate the moment one does.
- **Standard prompt packs beyond security.** The prompts repo's pack mechanism
  (`req-cicd-ai-review-harness-repo`) is the delivery vehicle for code-quality, best-practices,
  and standards-conformance review — security is the first use case, not the only or the last.
  Backlogged until the security pack has run through the observation window; packs then land as
  additions to the prompts repo, no machinery change. Watch trigger: the first hygiene want that
  black/ruff/mypy and Copilot do not already cover.
- **PR-based plugin releases.** `release-plugin.sh` currently pushes version bumps and tags
  directly to plugin repo mains — the last sanctioned direct-push flow in the org, and the
  named precondition blocking the org-wide protection-by-declaration flip (above). Endorsed
  2026-08-21 ("we shouldn't be direct pushing to plugins anyways" — doctrine point 4 applied to
  the release path): rework the script to open a release PR per plugin, gated like any other
  change. Watch trigger: the next plugin release, or the org-wide flip being wanted first.
- **Practicable reviewer confidence.** Self-reported model confidence is not trustworthy —
  verbalized confidence is poorly calibrated and overconfidence is the documented norm — and API
  logprobs do not map cleanly onto long-form review judgments, so a "confidence: 85%" line in a
  review narrative would be decoration, not information. The practicable substitutes, in order:
  **cross-seat agreement** (both vendors independently flag it), **devil's-advocate survival**
  (the fp-check-style gate a finding must pass before posting), and **empirical calibration** —
  track per-seat, per-severity precision against George's accept/dismiss decisions during the
  observation window (`req-cicd-ai-review-graduation`) and report *measured* precision ("this
  seat's high-severity findings have been right 7 of 9 times") instead of model-claimed
  confidence. **Recorded as a future SEAM, deliberately left open for someone clever to pick
  up** (an outside contributor included — the harness repos are public and reusable): the
  verdict ledger carries the join keys from day one
  (`req-cicd-ai-review-verdict-ledger-1`) so calibration can be built later as pure analysis
  over existing records, no machinery redesign. Watch trigger: vendors exposing calibrated
  verdict scores with published calibration data — or anyone showing up with a calibration PR.

## Relationship To Other Specs

- **[spec-cicd-hardening.md](spec-cicd-hardening.md)** — the parent pipeline doctrine; this spec is
  a new enforcement layer beside `req-cicd-branch-protection` (the gate rides the same ruleset and
  the same bypass-emptying wave) and inherits `req-cicd-runner-least-privilege`.
- **[spec-cicd-root-of-trust.md](spec-cicd-root-of-trust.md)** — who watches these watchers: the
  reviewer/gate configuration is guard surface protected by that spec's two-account structure,
  tamper telemetry, and ceremonies; its blocking-flip wave and this spec's are one wave.
- **[spec-security-posture.md](spec-security-posture.md)** — cheap-edge + honest-risk doctrine;
  `req-cicd-ai-review-honest-limits` is `req-sec-honest-risk` applied here; the trust-delta
  doctrine governs the third-party reviewer apps.
- **[spec-ai-integration.md](spec-ai-integration.md)** — AI reviewers are Player-3 actors on the
  development pipeline; the verdict ledger names its AI consumer per `req-ai-name-the-consumer`.
- **[spec-dev-validation.md](spec-dev-validation.md)** — the blocking gate is a validation surface
  requiring its Validation Map row in the implementing change.
- **[spec-dev-multisession.md](spec-dev-multisession.md)** — the promote/PR flow the reviewers
  attach to; per-PR review assumes that flow's one-PR-per-promote shape.

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
