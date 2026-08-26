---
spec: ../../specs/spec-cicd-root-of-trust.md
audience: [developer, llm]
covers:
  - ../../specs/spec-cicd-root-of-trust.md
  - req-cicd-rot-two-account
  - req-cicd-rot-gittuf
  - req-cicd-rot-ceremony
update-triggers:
  - gittuf stage/release milestones (1.0, OpenSSF graduation) or a forge announcing native support
  - GitHub ships approval-gated config editing (watch the delegated-bypass family)
  - Any wave of the sequence below lands — update tier statuses
  - The org gains a second maintainer/keyholder
assumes:
  - Solo-maintainer org (unified-systems-com); the PR promote flow is the road to main
  - The AI-reviewer ensemble (doc-cicd-ai-review-plan.md) is the everyday detection layer
provides: |
  The plan and reasoning record behind spec-cicd-root-of-trust.md: the measured current exposure,
  why prevention must be structural on GitHub (no second-person gate on config exists), the
  four-tier architecture (two-account split, off-laptop tripwires, gittuf advisory, hardware-key
  ceremonies), the per-commit-signing reassessment, and the honest limits — with sources.
---

# Root-of-Trust Protection — Plan

Companion plan to [spec-cicd-root-of-trust.md](../../specs/spec-cicd-root-of-trust.md)
(2026-08-11, sam-dev research session; three-agent sweep of gittuf, GitHub org-config defense, and
hardware-key/ceremony practice). Sibling plan:
[doc-cicd-ai-review-plan.md](doc-cicd-ai-review-plan.md) — the AI reviewers are the everyday
watchers; this plan answers who watches them.

## Recommendation

The research confirms the intuited shape: the field has moved from "hardware-sign every commit" to
a **two-tier trust model** — hardened everyday credentials + AI review + platform attestation for
routine changes, and **offline hardware keys used only in rare, published ceremonies** for changes
to the gates themselves. Concretely: (1) create a **break-glass owner account** and demote the
daily account to member, so no laptop credential can touch rulesets at all — this is the only real
*prevention* GitHub offers, because nothing on any plan makes ruleset editing require a second
person; (2) point **org webhooks** at an off-laptop endpoint so any guard change alarms in real
time (free, any plan); (3) adopt **gittuf advisory-first** — forge-independent verification of who
may change what, with its root held by the ceremony keys at 2-of-3; (4) buy **three dedicated
FIDO2 keys**, used for nothing else, with a Sigstore-style PR-based ceremony for every gate
change. Total recurring cost: about one extra Team seat ($4/mo) and ~$150 of hardware.

## The measured starting point (verified 2026-08-11)

`notgeorge` is the **sole member and sole owner** of `unified-systems-com`, and the daily `gh` CLI
token carries classic `repo` scope — which includes repository administration. **This laptop can
edit the `main` rulesets today.** The org is on the Team plan (good — org-level rulesets are
available) with 2FA required.

This isn't hypothetical exposure. The Nx "s1ngularity" attack (August 2025) put malware on
developer machines that harvested exactly these credentials — `gh` CLI tokens and AI-tool keys
from 1,079 laptops — then used the stolen tokens to mutate repository state across 400+ orgs. And
the tj-actions compromise showed what one stolen credential does to trusted refs: every version
tag retargeted to malicious commits, 23,000 downstream repos exposed.

> **The core finding on GitHub's limits:** there is *no mechanism on any plan* that makes editing
> a ruleset, branch protection, or org setting require a second person or a second factor. "Sudo
> mode" re-prompts for four account actions (new keys, tokens, app authorizations, email) — and
> API calls with a live token never see it at all. The delegated-bypass features gate *bypassing
> rules at push time*, not *editing the rules*. The only thing that sits above an org owner is an
> enterprise-level ruleset — and a solo maintainer would own the enterprise too. Conclusion:
> **prevention must be structural** (the credential simply isn't there), and everything else is
> detection.

## The four tiers

### Tier 1 — Structural prevention: the two-account split
*~half a day + one Team seat (~$4/mo) · the single biggest win*

Create a second account as **sole org owner**: passkey-only sign-in, never logged in on the daily
laptop (separate device, or at minimum a dedicated browser profile used only for ceremonies),
recovery codes stored offline with the ceremony keys. Demote `notgeorge` to **member with repo
write** — the entire promote flow (PR create, auto-merge, CI dispatch) runs on write permissions,
not admin. Then replace the daily `gh` token with a **fine-grained PAT that omits the
"Administration" permission** — the ruleset and branch-protection API endpoints become
structurally unreachable from this machine, verified by an actual refused call. Malware on the
laptop can then still write code (that's what the AI reviewers watch) but *cannot silently
disable the watchers*.

This lands in the **same wave** as two changes already planned: emptying the ruleset's admin
bypass list and flipping the AI-review gate to blocking. The three together are one posture; any
one alone leaves a hole.

### Tier 2 — Loud detection: off-laptop tripwires
*~a day · effectively free (a tiny Lambda/Worker)*

An **org webhook** — available on every plan — fires in real time on exactly the events that
matter: `repository_ruleset` (created/edited/deleted), `branch_protection_rule`,
`organization`/`membership` changes, and `integration_installation` (someone installing or
removing an App — the reviewer bots are guard surface too). Point it at a small endpoint *off the
laptop* (TAP already operates AWS) that pushes an alert. A **heartbeat** closes the
silent-deletion hole: the receiver alarms if the channel goes quiet, and deleting the webhook is
itself an audit-log event.

Beside the event stream, a **configuration ratchet**: a scheduled job on off-laptop
infrastructure with a *read-only* token that diffs live rulesets, protections, the owner list,
and App installs against a baseline file committed to the repo — the Kubernetes/Eclipse "org
config as reviewed code" pattern scaled down. Events can be missed; state cannot. (Future,
demand-gated: this becomes a TAP collector — Rampart assessing its own org with the same
machinery it points at customers. For now, a boring script.)

### Tier 3 — Forge-independent evidence: gittuf, advisory-first
*~2 days incl. spikes · $0*

gittuf stores TUF-style policy *inside git refs*: a signed, append-only log of every ref update
(the Reference State Log), plus a root of trust whose changes require a threshold of the
*previous* root's keys — so a policy change that exempts itself is structurally impossible
without key compromise. Path rules can hold `.github/workflows/*` and the guard machinery to a
stricter threshold than the rest of the tree, and PR approvals bind to the resulting *tree*, so
GitHub's squash merges still verify. Verification is client-side — GitHub needs no support and
gets no veto.

**Adopt it advisory:** init the root under the ceremony keys (2-of-3), run
`gittuf verify-ref main` in CI as a non-required check *and* on the off-laptop watcher (the
independent vantage point is the point), and keep GitHub rulesets as the enforcement layer. Spike
first: FIDO2 SSH-key signing is plausible but undocumented, and the log has known sharp edges
around rebases. Graduation to load-bearing waits on named triggers: gittuf 1.0 / OpenSSF
graduation, real production adopters, or TAP gaining co-keyholders.

Honest premise check on "gittuf becomes a standard": it's OpenSSF *incubating* (June 2025),
pre-1.0 (v0.15.0, June 2026, ~monthly cadence), ~2 dominant committers, **zero production
adopters found beyond its own repo** — but it comes from the NYU Secure Systems Lab, whose last
two designs (TUF, in-toto) both became standards; SLSA v1.2 names it; and its design fits this
exact threat model better than anything else that exists. Early-but-advisory is the right bet;
note SLSA's own `source-tool` (a forge-attestation approach) competes for the standard slot, so
the exit ramp is named too — the account structure and ceremonies are gittuf-independent by
design.

### Tier 4 — Ceremony: offline keys for gate changes
*~$150 hardware + a rehearsal afternoon*

Three dedicated FIDO2 hardware keys, threshold **2-of-3**, used for *nothing else* — not daily
2FA, not SSH. George holds all three initially: two in separate physical locations, one for
ceremonies. The 2-of-3 math gives a loss budget of one key (FIDO2 keys are non-backupable by
design — redundancy *is* the extra token), and the roster widens to "+2 trusted keyholders" later
via a root ceremony, no redesign. On biometrics: FIDO2 treats fingerprint and PIN+touch as
equivalent verification — the honest case for a YubiKey Bio on a four-times-a-year key is that
you can't forget a fingerprint like a PIN (PIN lockout wipes the credential). Worth it for that
alone; note the Bio line is FIDO-only, so if the gittuf spike lands on GPG instead of SSH keys,
revisit the hardware pick.

A **ceremony** is the Sigstore root-signing model scaled to one person — their 3-of-5 root
ceremonies now run as public GitHub PRs, with a dedicated rehearsal repo. Scaled down: (1) a
published *intent PR* describing the gate change before it happens; (2) execution from the
break-glass account, with ceremony-key signatures on gittuf root/policy changes; (3) the artifact
trail — the tier-2 telemetry correlates every guard-change event against a ceremony intent, and
**a guard change with no matching intent is the alarm condition**; (4) rehearse once, including a
lost-key recovery drill, before any of it is load-bearing.

## The signing reassessment

The old maximal practice — YubiKey-sign every commit — is now a documented anti-pattern for
GitHub-merged workflows, and the spec records the reassessment so it's a decision rather than a
gap:

- GitHub signs squash and web-UI merges with *its own* web-flow key, and rebase-merge drops
  signatures entirely — so a "commits on main are maintainer-signed" policy silently degrades
  into trusting GitHub again.
- A signature from a compromised laptop is the attacker's signature: it proves key possession at
  a moment, not intent. Touch proves presence, not content — no token has a trusted display. This
  critique is canonical (Dan Lorenc, the kernel maintainer guide — the kernel signs *tags*, since
  one tip signature covers the whole hash chain).
- What per-commit hardware signing still buys — non-exfiltratable keys, forensic partitioning
  after an incident — is real but modest, and the everyday marginal dollar goes further on
  credential hardening, AI review, and provenance.

**What does get signed:** release tags (composing with the SLSA image attestations already live),
gittuf's log entries and root metadata at ceremonies. Per-commit signing reopens later as a
contributor-*identity* control if the contributor count grows — a different problem from root
protection.

Worth naming: the full combined model here — AI reviewers as the everyday watchers, hardware
ceremonies over the watchers — has **no published precedent as a whole**. The halves are
established (agent approval-layer governance; Sigstore/gittuf two-tier roots). TAP writing it
into canon is a deliberate leading-edge position, same as the reviewer ensemble.

## What this stack does and doesn't close

| Attack path from a compromised laptop | Before | After |
| --- | --- | --- |
| Edit/delete rulesets via CLI token | Open (classic `repo` scope) | **Blocked** — no Administration permission on any laptop credential |
| Edit rulesets via logged-in browser | Open (owner session) | **Blocked** — browser account is a member; owner lives off-laptop |
| Smuggle malicious code in a PR | Open | Watched — AI reviewer ensemble + gate (companion plan) |
| Install/remove a reviewer App, add a member | Silent | Loud — webhook alarm + ceremony correlation |
| Forge-side tampering (GitHub itself) | Invisible | Evidenced — gittuf verification off-forge (advisory) |
| Compromise of the break-glass account itself | — | Passkey-only + never on daily machines; residual, named |
| George under duress / ceremony-vault burglary | — | **Out of scope**, named — 2-of-3 in one person's custody defends loss and casual theft, not a targeted physical adversary |

> **The solo degeneracy, stated plainly:** until there are +2 keyholders, George approves his own
> ceremonies. The stack converts silent tampering into structural blocks and loud, evidenced acts
> — genuine tamper-*prevention* on the credential paths and tamper-*evidence* everywhere else —
> but real multi-party control begins when the parties exist. AI reviewers don't count as SLSA
> "trusted persons"; SLSA L1–3 is the honest target, with the L4 seam ready. Enterprise-tier
> GitHub (the only construct above org owners) is parked: at ~5× the cost it adds little while a
> solo maintainer would own the enterprise too — reopen at +2 maintainers or customer compliance
> demands.

## Suggested sequence

1. **Now (with the AI-review Phase 0):** promote both spec drafts; order 3 hardware keys.
2. **Wave 1 (half a day):** break-glass owner account + demote daily + fine-grained PAT — plus
   empty the ruleset admin bypass. The prevention floor, done.
3. **Wave 2 (a day):** org webhook + off-laptop receiver + heartbeat; baseline file + ratchet cron.
4. **Wave 3 (two days, unhurried):** gittuf spikes → advisory root init under ceremony keys →
   `verify-ref` in CI and on the watcher; first ceremony rehearsal.

## Key sources

- gittuf — [design document](https://github.com/gittuf/gittuf/blob/main/docs/design-document.md) · [NDSS 2025 paper](https://ssl.engineering.nyu.edu/papers/yelgundhalli_gittuf_ndss_2025.pdf) · [dogfood status](https://github.com/gittuf/gittuf/blob/main/docs/dogfood.md) · [GitHub App](https://github.com/gittuf/github-app)
- SLSA — [Source Track requirements](https://slsa.dev/spec/v1.2/source-requirements) (the forge is in the TCB; two *persons* at L4)
- GitHub — [fine-grained PAT permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) · [webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads) · [sudo mode's actual coverage](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/sudo-mode)
- Sigstore — [root-signing (PR-based ceremonies)](https://github.com/sigstore/root-signing) · [threat model (3-of-5 offline root)](https://docs.sigstore.dev/about/threat-model/)
- Incidents — [Nx s1ngularity postmortem](https://nx.dev/blog/s1ngularity-postmortem) · [tj-actions (Wiz)](https://www.wiz.io/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)
- Signing critique — [Lorenc, "Should You Sign Git Commits?"](https://dlorenc.medium.com/should-you-sign-git-commits-f068b07e1b1f) · [kernel maintainer PGP guide](https://www.kernel.org/doc/html/latest/process/maintainer-pgp-guide.html)
- Config-as-code prior art — [peribolos](https://docs.prow.k8s.io/docs/components/cli-tools/peribolos/) · [Otterdog](https://github.com/eclipse-csi/otterdog) · [safe-settings](https://github.com/github-community-projects/safe-settings) · [Allstar](https://github.com/ossf/allstar)

The durable, maintained canon is the Prior Art ledger in
[spec-cicd-root-of-trust.md](../../specs/spec-cicd-root-of-trust.md); this doc is the
point-in-time plan and reasoning record.
