# Root-Of-Trust Protection — Guarding The Guards

## Philosophy

**DRAFT (2026-08-11)** — authored from the sam-dev research session on gittuf, org-config defense,
and hardware-key practice; requirements are `Proposed` and unbuilt. This spec is the center of
gravity for **protecting the security gates themselves** — the rulesets, workflows, guard
machinery, reviewer configuration, and org settings that everything else trusts — against
compromise of a maintainer's machine or account.

The layered model this spec completes: **AI reviewers** (spec-cicd-ai-review.md) are the everyday
out-of-band watchers detecting compromised developers pushing malicious updates; **rulesets + the
gate** enforce; and this spec answers *who watches the watchers* — how a compromised laptop is
prevented from, or caught, silently disabling the guards at the org/repo level.

Three facts anchor the design (all verified 2026-08-11):

- **The current trust chain reduces to one credential on one laptop.** `notgeorge` is the sole
  member and sole owner of `unified-systems-com`; the daily `gh` token carries classic `repo`
  scope, which includes repository administration — this laptop can edit the `main` rulesets
  today. This is the exact exposure: the Nx "s1ngularity" attack (2025-08) harvested `gh` tokens
  from 1,079 developer machines and used them to mutate repo state at scale.
- **GitHub has no second-person gate on configuration.** No mechanism — on any plan — makes
  ruleset/branch-protection *editing* require N approvals or a second factor. Sudo mode gates four
  account actions (keys, tokens, apps, email), not config; API calls with a live token never see
  it. The delegated-bypass family gates *bypassing at push time*, not *editing the rules*. The only
  hierarchy above an org owner is an enterprise ruleset — and a solo maintainer is the enterprise
  owner too. Prevention must therefore be **structural** (the credential is absent), and everything
  else is **detection**.
- **The signing world has inverted.** The old maximal practice — hardware-sign every commit — is
  now the documented anti-pattern for GitHub-merged flows: squash/web merges are signed by
  *GitHub's* web-flow key, rebases drop signatures, and the canonical critiques (Lorenc; the kernel
  guide) show a per-commit signature proves key possession, not intent. The field's shape is
  **two-tier**: identity-bound/platform-attested everyday layer, and an **offline hardware-key
  threshold root** used rarely, for the rules themselves. Sigstore is the living precedent —
  keyless everyday signing under a 3-of-5 offline-YubiKey TUF root whose ceremonies run as public
  GitHub PRs. This spec adopts that shape: **AI reviewers and provenance for every change; offline
  ceremony keys for changes to the gates.**

The doctrine:

> Everyday development needs no personal signing ritual — it needs hijack-resistant credentials,
> independent AI review, and platform attestation. The **root** — the small set of surfaces that
> define what "green" means — is guarded structurally (no root credential on any daily machine),
> watched from outside the laptop's trust domain, evidenced forge-independently (gittuf), and
> changed only through a **ceremony**: offline hardware keys, a published intent, a threshold that
> today is "only George's ceremony keys" and is built to widen to "+2 keyholders" without redesign.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | No Root Credential On The Laptop | Daily machines hold only least-privilege credentials structurally unable to alter the gates. |
| 2. | Tampering Is Loud, Off-Laptop | Guard changes emit real-time signals to infrastructure outside the laptop's trust domain. |
| 3. | Forge-Independent Evidence | Repository policy and history are verifiable without trusting GitHub (gittuf), advisory-first. |
| 4. | Ceremony For Gate Changes | Changes to the gates ride offline hardware keys under a published, threshold-ready ceremony. |
| 5. | Solo-Operable, Multi-Party-Ready | Every control works for one person today and widens to +2 keyholders/reviewers without redesign. |
| 6. | Track The Wave | gittuf's trajectory and forge-governance practice are tracked in the standing prior-art ledger. |

## Prior Art (the standing ledger — `req-cicd-rot-prior-art`)

Last swept: **2026-08-11** (three-agent research sweep, sam-dev session). Update triggers: gittuf
stage/release milestones (esp. 1.0 or OpenSSF graduation); any forge announcing native gittuf/RSL
support; SLSA Source Track tooling movement; GitHub shipping approval-gated config changes; any
in-the-wild protection-tampering incident.

**gittuf** (gittuf.dev; NYU Secure Systems Lab pedigree — the TUF/in-toto lab; lead: Aditya Sirish
A Yelgundhalli, now Bloomberg; NDSS 2025 distinguished paper). TUF-style trust metadata in git refs
(`refs/gittuf/*`): an append-only signed **Reference State Log** records every ref update; **root
of trust** metadata carries owner keys + threshold, and root changes require a threshold of the
*previous* root's keys — a self-exempting change is structurally impossible without key compromise;
path-based delegations can put `.github/workflows/*`/guard paths under stricter thresholds than the
rest of the tree; PR approvals become in-toto attestations bound to the resulting *tree*, so
GitHub's squash/merge commits still verify. Verification is client-side and forge-independent —
the forge needs zero support. Status: OpenSSF **incubating** (2025-06; sandbox 2024-01), pre-1.0
beta (v0.15.0, 2026-06-30; ~monthly cadence), one fixed CVE (2026-44544, policy rollback), a
hosted GitHub App, healthy activity but **commit concentration in ~2 people and zero evidenced
production adopters beyond its own repo** (dogfooding candidly "Phase 1" — automation signs on
maintainers' behalf). SLSA v1.2 names gittuf as a way to satisfy source requirements, but SLSA's
own `source-tool` (forge-attestation approach) competes for the standard slot. Honest premise
assessment: *"becomes the standard for the forge-skeptic tier" is a reasonable bet on the lab's
TUF/in-toto track record; "becomes the default" is not yet supported* — hence advisory-first.
Known edges: RSL/rebase sharp edges (issue #705), forge fork\* attack detected only out-of-band,
FIDO2 `sk-` SSH signing plausible but undocumented (spike before relying on it).

**Org-config defense (GitHub, as of 2026-08).** Fine-grained PATs gate ruleset/branch-protection
edits behind the **Administration** permission — a daily token omitting it is structurally unable
to touch the gates (the strongest native prevent, any plan). Classic `repo` scope (what `gh auth
login` mints) carries full repo-admin power; `cli/cli#13032` (scoped auth) is open. The
**two-account pattern** (break-glass owner, passkey-only, never on the daily machine; daily
account demoted to member) is established community/industry hardening practice, not first-party
doctrine; one-free-account ToS ⇒ the second account takes a paid seat. **Org webhooks fire on
`repository_ruleset`, `branch_protection_rule`, `branch_protection_configuration`, `organization`/
`membership`, `integration_installation` on any plan** — the free real-time tamper channel; webhook
deletion is itself audit-logged. Ruleset **history** (GA 2025-02) gives full diff + restore. Org
audit log: 180-day UI export on all plans; **API + streaming are Enterprise-only**. Enforcement
watchers: OpenSSF **Allstar** (App; can auto-revert branch-protection drift), **safe-settings**
(org config-as-code with webhook-driven revert + scheduled reconciliation; self-hosted Probot —
host it off-laptop), **Scorecard/scorecard-monitor** (scheduled drift reports). Foundation-scale
prior art: Kubernetes **peribolos** (org config in a reviewed repo, reconciled by automation),
Eclipse **Otterdog** (committers PR config, staff apply — an organizational second-person gate),
Apache `.asf.yaml`. SLSA source track states the frame plainly: the forge and its admins are
inside the TCB; L4's "two trusted persons" has a Trusted-Robot policy-exception seam but AIs do
not count today. Incidents: tj-actions (stolen bot PAT retargeted all version tags, 23k repos);
Nx s1ngularity (harvested `gh`/AI-tool creds → mass repo-state mutation). No public incident yet
of silent ruleset-disable — anticipated TTP (Splunk ships detections), not yet cataloged.

**Hardware keys + ceremonies.** Per-commit signing critique is canonical (Lorenc "Should You Sign
Git Commits?"; kernel maintainer guide: sign *tags*, one tip signature covers the hash chain;
GitHub web-flow signs squash/web merges with GitHub's key — a "maintainer-signed main" policy
degrades to forge trust under normal GitHub flows). What hardware keys still buy: non-exfiltration
(attacker's signing capability ends with access), forensic partition, rate-limiting to human tempo.
Touch = presence, not content — no trusted display on any token. **Ceremony practice:** Sigstore
root = 5 keyholders, 3-of-5 offline YubiKeys, signing events run as public GitHub PRs with a
dedicated *rehearsal repo*; RSTUF codifies offline-root/online-daily split; DNSSEC KSK ceremonies
are the archetype (published script, witnesses, artifact trail). Threshold math: with N keys and
threshold T, N−T is the loss budget — 2-of-3 tolerates one lost key; FIDO2 keys are
non-backupable by design (redundancy = enroll multiple tokens). Biometrics: FIDO2 treats
fingerprint and PIN+touch as equivalent user verification; YubiKey Bio is FIDO-only (no
OpenPGP/PIV); the honest case for bio on a rarely-used ceremony key is forgotten-PIN lockout
avoidance, not a stronger bar. Daily-credential reality: OAuth/token abuse bypasses passkeys once
minted; prompt-injection credential theft against coding agents is demonstrated — daily hardening
(passkey login, keyring-stored descoped tokens) is where the everyday marginal dollar goes.
**The combined model — AI everyday reviewers + rare human hardware ceremony for gate changes — has
no single published precedent**; the halves are established separately (agent-governance approval
layers; Sigstore/gittuf two-tier roots). TAP naming it in canon is a deliberate leading-edge
position.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-rot-two-account | [Two-Account Structure](#two-account-structure) | Proposed | Break-glass owner (passkey-only, never on daily machines); daily account demoted — the prevention floor |
| req-cicd-rot-daily-credential | [Daily Credential Least Privilege](#daily-credential-least-privilege) | Proposed | Fine-grained PAT without Administration for `gh`; passkey login; keyring storage |
| req-cicd-rot-tamper-telemetry | [Off-Laptop Tamper Telemetry](#off-laptop-tamper-telemetry) | Proposed | Org webhooks on ruleset/protection/app/membership events → off-laptop endpoint + heartbeat |
| req-cicd-rot-config-ratchet | [External Configuration Ratchet](#external-configuration-ratchet) | Proposed | Read-only drift watcher vs a committed baseline, running outside the laptop's trust domain |
| req-cicd-rot-gittuf | [gittuf Advisory Layer](#gittuf-advisory-layer) | Proposed | Forge-independent policy + RSL verification, advisory-first, with named graduation triggers |
| req-cicd-rot-ceremony | [Gate-Change Ceremony](#gate-change-ceremony) | Proposed | Offline hardware keys, threshold-ready (2-of-3), published PR-based ceremony, +2-keyholder seam |
| req-cicd-rot-signing-posture | [Everyday Signing Posture](#everyday-signing-posture) | Proposed | No per-commit signing mandate; tags/root metadata signed; the reassessment recorded |
| req-cicd-rot-prior-art | [Maintain The Prior-Art Ledger](#maintain-the-prior-art-ledger) | Proposed | gittuf trajectory + forge-governance practice tracked with named triggers |
| req-cicd-rot-honest-limits | [Name What This Does Not Do](#name-what-this-does-not-do) | Proposed | Browser-session residual, fork\* attack, solo self-approval degeneracy, Enterprise tier parked |

---

### Two-Account Structure
----
RID: `req-cicd-rot-two-account`
Status: `Proposed`

The org-owner credential is **structurally absent from daily machines**. A dedicated break-glass
owner account holds org ownership; the daily account is demoted to the least privilege that
day-to-day development actually needs.

#### Implementation

- Create a second account (paid Team seat, ~$4/mo — the ToS-clean route) as **sole org owner**:
  passkey/security-key-only 2FA, credentials never entered on a daily machine (separate device, or
  at minimum a separate browser profile used only for ceremonies), recovery codes stored offline
  with the ceremony keys (`req-cicd-rot-ceremony`).
- Demote `notgeorge` to org **member** with repo write/maintain — sufficient for the entire promote
  flow (PR create, auto-merge arm, CI dispatch ride repo write, not admin). Everything the owner
  does — ruleset edits, App installs, org settings, member changes, the bootstrap/skip-hatch direct
  push — becomes a deliberate break-glass act on the owner account.
- Sequencing: this lands in the **same wave** as emptying the `main-required-checks` admin bypass
  and the AI-review blocking flip (spec-cicd-ai-review.md) — the three changes are one posture.
- Widening seam: future contributors are members; additional owners (if ever) are additional
  break-glass accounts, never daily identities.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-two-account-1 | Owner Off The Laptop | Proposed | No daily machine holds org-owner credentials (CLI token, browser session, or keychain entry). | The prevention floor. |
| req-cicd-rot-two-account-2 | Daily Is A Member | Proposed | The daily account holds member + repo write/maintain, not admin; the promote flow works unchanged. | Verified against the PR road. |
| req-cicd-rot-two-account-3 | Break-Glass Is Deliberate | Proposed | Owner-account use is rare, purposeful, and leaves the audit/webhook trail (`req-cicd-rot-tamper-telemetry`). | |

---

### Daily Credential Least Privilege
----
RID: `req-cicd-rot-daily-credential`
Status: `Proposed`

The daily machine's GitHub credentials are hijack-resistant and least-privilege: a compromised
laptop yields tokens that **cannot** alter the gates.

#### Implementation

- Replace the classic-scoped `gh` OAuth token (today: `repo` = full repo-admin) with a
  **fine-grained PAT omitting the Administration and Organization-administration permissions**
  (contents/PRs/issues/actions as needed), keyring-stored, expiry-bounded. This is the single
  strongest native lever: ruleset/protection endpoints are structurally unreachable.
- Passkey login on both accounts; secure-2FA-methods-only org setting.
- Known residuals, named: the browser session cookie (mitigated by `req-cicd-rot-two-account` — the
  browser account is a member, not owner); minted-token abuse bypasses passkeys (why scoping and
  expiry matter more than login strength); AI-agent credential theft via prompt injection is a
  demonstrated class — the descoped token bounds its blast radius.
- Re-verify after any `gh auth` refresh: `gh auth status` scope check joins the session-spawn
  habits (the existing token-descope pattern).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-daily-credential-1 | No Administration Permission | Proposed | Daily tokens cannot reach ruleset/branch-protection/org-settings endpoints (verified by a refused call). | Test the refusal, not the docs. |
| req-cicd-rot-daily-credential-2 | Hijack-Resistant Auth | Proposed | Passkey login; tokens keyring-stored with bounded expiry; scopes re-verified on re-auth. | |

---

### Off-Laptop Tamper Telemetry
----
RID: `req-cicd-rot-tamper-telemetry`
Status: `Proposed`

Changes to the guards emit **real-time signals to infrastructure outside the laptop's trust
domain**. Detection is the cheap edge available where prevention isn't (`req-sec-concern-gaps`
reasoning, applied to the forge).

#### Implementation

- An **org webhook** — available on every plan — subscribed to: `repository_ruleset`,
  `branch_protection_rule`, `branch_protection_configuration`, `organization`, `membership`,
  `integration_installation` (reviewer/bot App installs are guard surface too), delivering to an
  off-laptop endpoint (small Lambda/Worker → email/push; TAP already operates AWS).
- **Heartbeat closes the silent-deletion hole:** the receiver expects a periodic probe event and
  alerts on silence; webhook deletion is itself audit-logged and costs the attacker a loud step.
- Signals are machine-legible and named-consumer (`req-ai-name-the-consumer`): the internal
  security AI — the same consumer as the `CONCERN` stream and the AI-review verdict ledger —
  triages guard-change events against expected ceremonies (`req-cicd-rot-ceremony`): a guard
  change *without* a matching published ceremony intent is the alarm condition.
- The 180-day org audit log (UI export, Team plan) is the forensic backstop; ruleset history
  provides diff + one-click restore for recovery.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-tamper-telemetry-1 | Real-Time Guard Events | Proposed | Ruleset/protection/App/membership changes reach an off-laptop endpoint within minutes. | Verify empirically per event type. |
| req-cicd-rot-tamper-telemetry-2 | Heartbeat | Proposed | The channel alerts on its own silence; deletion of the channel is a detectable event. | |
| req-cicd-rot-tamper-telemetry-3 | Ceremony Correlation | Proposed | A guard-change event with no matching ceremony intent is routed as an alarm, not a log line. | The named AI consumer's job. |

---

### External Configuration Ratchet
----
RID: `req-cicd-rot-config-ratchet`
Status: `Proposed`

A **read-only watcher running outside the laptop's trust domain** periodically reads the org/repo
security configuration and diffs it against a **committed baseline** — the polling complement to
the event-driven telemetry (events can be missed; state cannot).

#### Implementation

- v0: a scheduled job on off-laptop infrastructure (Lambda cron / the samsite box) holding a
  **read-only** fine-grained PAT, reading rulesets (repo + org), branch protections, org owner and
  member lists, App installations, and default workflow permissions; diffing against a baseline
  file committed to the repo; alerting loudly on drift. The baseline change itself rides a PR —
  config-as-code in the reviewed tree, the peribolos/Otterdog pattern scaled down.
- The ratchet alerts on its own failure to run (a dead watcher is an alarm, not silence).
- Deliberately **detect-and-restore, not auto-enforce** in v0: with ruleset history's one-click
  restore, a human (or later the security AI proposing) reverts; auto-revert (Allstar/safe-settings
  style) is a named future once trust in the baseline mechanics is established.
- Future, demand-gated (named, not built): the ratchet becomes a **TAP collector** — the org's
  security configuration lands on the grid as typed nodes, Rampart assessing its own supply chain
  with the same machinery it points at customer infrastructure. The dogfooding story is real, but
  it waits for demand; v0 is a boring script.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-config-ratchet-1 | Off-Laptop, Read-Only | Proposed | The watcher runs outside the daily machine's trust domain with a token that can only read. | |
| req-cicd-rot-config-ratchet-2 | Committed Baseline | Proposed | Expected configuration is a reviewed, committed artifact; drift = alert; baseline changes ride PRs. | |
| req-cicd-rot-config-ratchet-3 | Watcher Watches Itself | Proposed | A missed run raises an alert; the ratchet's silence is loud. | |

---

### gittuf Advisory Layer
----
RID: `req-cicd-rot-gittuf`
Status: `Proposed`

TAP adopts **gittuf as a forge-independent evidence layer, advisory-first**: policy and ref history
verifiable without trusting GitHub, with named triggers for graduating toward load-bearing — a
deliberate early position on the premise that gittuf (or its model) standardizes as it exits
incubation.

#### Implementation

- **Init**: root of trust with the ceremony keys (`req-cicd-rot-ceremony`) at threshold 2-of-3;
  policy protecting `git:refs/heads/main` and — at the stricter root/policy tier — the guard paths
  (`.github/workflows/*`, guard/ratchet machinery, CODEOWNERS, this spec family). Path delegations
  are exactly the machinery for "the gates get a higher bar than the tree."
- **Verify**: `gittuf verify-ref main` runs (a) in CI as a non-required advisory check, and (b) on
  the off-laptop ratchet infrastructure — the independent verifier is the point; CI on the forge
  being distrusted is fast feedback, not the anchor. The gittuf GitHub App's PR-approval
  attestations (tree-bound, so squash merges verify) are evaluated in the same phase.
- **Spike first, before relying on it**: FIDO2 `sk-ssh-ed25519` signing through gittuf's SSH path
  (undocumented), RSL behavior under the real promote flow (merge commits, the occasional rebase),
  and the day-to-day `rsl record` ergonomics (transport vs hook).
- **Graduation triggers** (advisory → load-bearing, each a deliberate recorded decision): gittuf
  1.0 / OpenSSF graduation; a named production adopter cohort; the App or forge-native RSL support
  maturing past "Phase 1 automation-signed"; TAP gaining +2 keyholders (threshold verification
  becomes real multi-party). Exit trigger honestly held open too: if `slsa-source-tool`'s
  forge-attestation track wins the standard slot, the evidence layer pivots there — the ceremony
  and account structure above are unaffected (they are gittuf-independent by design).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-gittuf-1 | Advisory Verification Live | Proposed | gittuf policy + RSL exist for the core repo; verify-ref runs in CI and off-laptop, non-blocking. | |
| req-cicd-rot-gittuf-2 | Root Under Ceremony Keys | Proposed | gittuf root metadata is held by the ceremony keys at threshold; root changes are ceremonies. | |
| req-cicd-rot-gittuf-3 | Named Graduation Triggers | Proposed | Advisory→load-bearing (and exit) conditions are recorded and re-checked on ledger updates. | |

---

### Gate-Change Ceremony
----
RID: `req-cicd-rot-ceremony`
Status: `Proposed`

Changes to **the gates** — rulesets/org settings, guard machinery paths, reviewer-App
configuration, gittuf root/policy metadata — happen only through a **ceremony**: a published
intent, executed with offline hardware keys kept solely for this purpose, leaving a public
artifact trail. This is the Sigstore root-signing model scaled to one person, with the +2 seam
built in.

#### Implementation

- **Keys**: 3 dedicated FIDO2 hardware keys, threshold 2-of-3 — George holds all three initially
  (two in separate physical locations, one ceremony-carry), used for *nothing else* (not daily
  2FA, not SSH). N−T=1 is the loss budget; FIDO2 keys are non-backupable by design, so redundancy
  is the extra enrolled token. Biometric (YubiKey Bio) is acceptable-not-required: FIDO2 treats
  bio and PIN+touch as equivalent verification; bio's honest value on a four-times-a-year key is
  forgotten-PIN lockout avoidance. Note YubiKey Bio is FIDO-only — if the gittuf spike lands on
  GPG rather than `sk-` SSH keys, the hardware choice revisits.
- **Ceremony shape** (Sigstore's PR-based form, scaled down): a ceremony is (1) a published intent
  — a PR describing the gate change before it happens; (2) execution from the break-glass account
  and/or ceremony-key signatures (gittuf root/policy changes carry the threshold signatures
  natively); (3) the artifact trail — the merged PR, the webhook/audit events it explains, and the
  telemetry correlation (`req-cicd-rot-tamper-telemetry-3`: guard change without ceremony intent =
  alarm). (4) A rehearsal before the first real ceremony, Sigstore-style.
- **The +2 seam**: the roster and threshold live in gittuf root metadata and this spec; adding
  keyholders 2 and 3 (trusted collaborators, eventually) changes the roster via a root ceremony —
  no redesign. Until then, the honest framing: the threshold defends against key loss and casual
  key theft, not against George-under-duress — multi-*party* security starts when the parties do.
- Account recovery codes for the break-glass owner are stored with the offline keys — the ceremony
  vault is one place, not three.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-ceremony-1 | Dedicated Offline Keys | Proposed | Ceremony keys exist, single-purpose, threshold 2-of-3, stored per the loss-budget design. | |
| req-cicd-rot-ceremony-2 | Published Intent | Proposed | Every gate change is preceded by a ceremony-intent PR; unexplained guard changes are alarms. | |
| req-cicd-rot-ceremony-3 | Rehearsed | Proposed | The ceremony (incl. a key-loss recovery drill) is rehearsed before it is load-bearing. | Sigstore's rehearsal-repo lesson. |
| req-cicd-rot-ceremony-4 | Widening Without Redesign | Proposed | Adding keyholders is a roster/threshold ceremony, not an architecture change. | |

---

### Everyday Signing Posture
----
RID: `req-cicd-rot-signing-posture`
Status: `Proposed`

TAP **does not mandate per-commit signing** for daily development. The reassessment of the old
maximal practice is recorded here so the decision is a choice, not a gap.

#### Implementation

- Rationale (the reassessment): GitHub squash/web merges are signed by GitHub's web-flow key —
  a "maintainer-signed main" policy degrades to forge trust under the normal flow; rebases drop
  signatures; a signature from a compromised laptop is the attacker's signature (possession, not
  intent); the kernel's own practice is tags-over-commits, since one tip signature covers the hash
  chain. The everyday marginal dollar goes to credential hardening
  (`req-cicd-rot-daily-credential`), AI review (spec-cicd-ai-review.md), and provenance.
- What **is** signed: release tags (composing with `req-cicd-supply-chain-provenance` and the
  existing SLSA image attestations), gittuf RSL entries/attestations as that layer matures, and
  root metadata at ceremonies. DCO's human-only sign-off discipline (kernel-aligned) is unchanged.
- Revisit trigger: if contributor count grows such that impersonation-in-the-forge becomes a real
  surface, per-commit SSH signing with vigilant mode reopens as a *contributor-identity* control —
  distinct from the root-protection problem this spec owns.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-signing-posture-1 | Decision Recorded | Proposed | The no-per-commit-mandate stance and its rationale stay recorded here with the revisit trigger. | |
| req-cicd-rot-signing-posture-2 | Roots And Tags Signed | Proposed | Release tags and gittuf root/policy metadata carry signatures; daily commits need not. | |

---

### Maintain The Prior-Art Ledger
----
RID: `req-cicd-rot-prior-art`
Status: `Proposed`

The Prior Art section is **standing canon**, maintained on the named triggers (ledger head), with
each sweep date-stamped — same discipline as spec-cicd-ai-review.md's ledger; the two specs' sweeps
naturally run together.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-prior-art-1 | Triggered Updates | Proposed | The ledger updates on the named triggers, date-stamped per sweep. | |

---

### Name What This Does Not Do
----
RID: `req-cicd-rot-honest-limits`
Status: `Proposed`

Per `req-sec-honest-risk`:

- **The browser-session residual.** Descoping the CLI token doesn't descope a logged-in browser;
  the two-account structure reduces the browser to member power, but a member session still writes
  code — which is the AI reviewers' watch, not this spec's.
- **Solo self-approval degeneracy.** Config-as-code + ceremonies convert silent drift into loud,
  evidenced acts — but one person still approves their own ceremony. Real multi-party security
  begins at +2 keyholders; until then the claim is tamper-*evidence* with structural prevention of
  the *silent* path, not two-person control. AI reviewers do not count as SLSA trusted persons.
- **The forge fork\* attack.** A malicious forge can serve different RSL/ref views to different
  verifiers; gittuf detects this only via out-of-band comparison (the off-laptop verifier plus the
  laptop is exactly two vantage points — thin, named).
- **Enterprise tier parked.** Enterprise rulesets are the only GitHub construct above org owners,
  but a solo maintainer owns the enterprise too — the marginal value over
  two-account + Team + telemetry + ratchet is thin at ~5× the cost. Reopen triggers: +2
  maintainers, customer compliance demanding audit-log streaming/IP allow-lists, or GitHub
  shipping approval-gated config editing (watch the delegated-bypass family's evolution).
- **Physical coercion / duress** and a compromise of the ceremony vault location are out of scope;
  2-of-3 with keys in one person's custody defends loss and casual theft, not a targeted physical
  adversary.
- **gittuf youth.** Pre-1.0, ~2-maintainer concentration, no production adopters: why it is
  evidence, not enforcement, until the graduation triggers fire.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-rot-honest-limits-1 | Gaps Stated | Proposed | The above limits remain stated here and are re-checked when the ledger updates. | |

---

## Relationship To Other Specs

- **[spec-cicd-ai-review.md](spec-cicd-ai-review.md)** — the everyday-watcher layer this spec
  guards; the AI-review blocking flip, the ruleset bypass-emptying, and `req-cicd-rot-two-account`
  land as one wave; the verdict ledger and the tamper telemetry share the same named AI consumer.
- **[spec-cicd-hardening.md](spec-cicd-hardening.md)** — the parent pipeline doctrine;
  `req-cicd-branch-protection`'s bypass-emptying endgame and `req-cicd-supply-chain-provenance`'s
  signing wave compose here; guard meta-integrity's "tamper-blocking half" (spec-dev-validation
  `req-dev-validation-meta-integrity-2`) is delivered by this spec's structure.
- **[spec-security-posture.md](spec-security-posture.md)** — the doctrine home: this spec closes
  the named open edge "admin can bypass branch protection; trust reduces to the admin set" as far
  as structure allows, and names what remains.
- **[spec-ai-integration.md](spec-ai-integration.md)** — telemetry/ceremony-correlation signals
  are machine-legible with a named AI consumer (the internal security AI).
- **[plan/road-rampart.md](../plan/road-rampart.md)** — the roadmap's standing supply-chain
  trigger ("the moment someone outside sets up an instance…") is the demand signal that pulls the
  Sigstore/TUF boot-pointer ladder; this spec is the development-side sibling of that ladder.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Deprecated | No longer part of the current architecture. |
