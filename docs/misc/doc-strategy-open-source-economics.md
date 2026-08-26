---
spec: ../../plan/road-products.md
audience: [developer, llm]
covers:
  - ../../plan/road-products.md
  - ../../plan/product-map.md
  - doc-strategy-prior-art-review.md
assumes:
  - Reader knows the 2026-08-25 strategy overhaul and the "no moat in the technology" posture.
update-triggers:
  - A monetization decision is made — record it in road-products.md and strike the option here
  - A cited price point or ARR figure is superseded
  - The first paying relationship exists — several findings here are predicated on there being none
---

# Open-source economics for a platform play: what pays, what doesn't, and what the numbers actually say

**Date:** 2026-08-25. **Question asked:** what funding mechanisms exist for a solo/small-team open
platform aiming at enterprise use; what does sponsorship really look like; has anyone used cloud
marketplaces as a funding channel for free software; and what are the success stories and failure
modes.

**Method.** Five research passes: cloud-marketplace mechanics and precedent; solo-maintainer funding
mechanisms; platform/plugin-ecosystem economics; license strategy and fork outcomes; and post-2023
open-product monetization with real price points. Numbers below are marked by provenance, because
this field is unusually contaminated: valuations are disclosed, revenue is not, and most circulating
ARR figures for open-source companies are third-party analyst estimates that say so in their own
footnotes.

---

## The finding that reorganizes everything

The working thesis was that post-AI economics differ from the WordPress era because ecosystem
seeding and time-to-revenue were both slow then and are fast now. **The evidence splits that thesis
in half, and the expensive half does not survive.**

**Time to adoption collapsed — confirmed, dramatically.** Every one of these was created in 2023 and
verified by GitHub API in August 2026: Ollama 179,437 stars; Langflow 153,686; Dify 153,524; Open
WebUI 149,927. WordPress-era projects took a decade to reach comparable mindshare.

**Time to revenue did not compress at all.** Same cohort, three years on: **no disclosed ARR for Open
WebUI, LiteLLM, Dify, or Langflow.** What the AI era actually compressed was *time to exit* —
Continue.dev acquired by Cursor, Langflow through DataStax into IBM.

**And the window closes at both ends.** Flowise — 55,391 stars, named enterprise logos including AWS,
Priceline, Accenture and Deloitte, a live three-tier SaaS at $35 and $65 per month — **shut down**.
Code freeze 2026-07-29, repository archived 2026-08-10. Their stated reason: developers moved to
coding agents and "the typical rigid workflow low-code approach quickly hits the limit." Adoption,
enterprise logos, and working paid tiers, dead in under three and a half years.

So the correction is not "monetization got faster." It is that **you can now reach a hundred thousand
stars in eighteen months, and the category underneath you can evaporate in eighteen months too.**
Fast adoption bought this cohort nothing on the monetization axis, and cost them runway before the
ground moved.

---

## What actually monetizes for a very small team, ranked

1. **Paid features under copyleft or fair-source.** The highest revenue-per-hour documented anywhere.
   Sidekiq's Mike Perham published the pivot precisely: selling *commercial licenses* at $50 produced
   **33 sales, $1,650 over nine months — "Result: failure."** Selling a genuinely separate, better
   product (Sidekiq Pro) produced **$7,500 in the first quarter, $85,000 in 2013, $175,000 in 2014**,
   solo, no employees, no marketing. **People do not pay to be un-restricted; they pay for something
   more.**

2. **Managed hosting for the long tail.** Ghost: **$11,055,673 ARR, 30,557 customers, 40+ staff, zero
   VC, MIT-licensed, pure hosting** — roughly $276k ARR per employee, published live on their own
   dashboard. Plausible: $1M ARR in three years with four people, bootstrapped. Coolify's ratio is the
   instructive one — 61,000 stars converted to **3,641 paying cloud customers (~17:1)** but only **314
   sponsors (0.5%)**. Hosting outperformed sponsorship by roughly twelve to one on the same audience.

3. **Per-seat self-host licence with support bundled in.** This is the enterprise path, and the
   audited evidence is unambiguous — see below.

4. **A partner company that sells support for you.** The curl/wolfSSL model works, and took
   **twenty-one years** and someone else's sales organisation.

5. **Productized support tiers with published prices.** Chatwoot documents this openly: on-prem
   support went $20/mo → $49/mo after margin analysis → a **$299 / $499 / $999+ ladder**. Viable, but
   it is a second product with its own margin maths.

6. **Bespoke enterprise support contracts sold by the maintainer — the trap.** See below.

7. **Sponsorship and donations — not a business.** Plausible tried donations and raised **$30 in six
   months** before abandoning it for paid SaaS. core-js is the floor case: ~250 hours a month on a
   package used by most of the web, peak recurring ~$2,500/mo collapsing to **~$400/month — under $2
   an hour** — and $400 of that came from *another open-source project*, not from the corporations
   depending on it.

---

## Support: what it bears, and why it is not a business at n=2

**The published price bands are remarkably consistent across unrelated vendors:**

| Band | What it buys | Examples |
| --- | --- | --- |
| **$1k–$3k/yr** | Self-serve. Email only, multi-day response, no named human. | Sidekiq Pro $995/yr; Zabbix Silver ~€2,940/yr; wolfSSL Basic $2,600 |
| **$7k–$25k/yr** | **A named engineer and an SLA — a human contractually on the hook.** | Icinga from €15,000; authentik Enterprise Plus from $20,000; Metabase Enterprise from $20,000; Grafana **$25,000 minimum commitment**; Nextcloud €7,129–€20,475 at its 100-user floor |
| **$28k–$50k+/yr** | 24×7 and long-tail version support. | wolfSSL Premium $28,500 / 24×7 $50,000 |

**The €15k–$25k/year floor recurs across vendors with nothing else in common.** That is the market's
price for contractual human attention, and it is the number to reason from.

**But four independent sources converge on support being the wrong primary line for one or two
people.**

**The audited number.** GitLab's FY2026 10-K (year ended 2026-01-31, total revenue $955.2M):
subscription self-managed **59%**, SaaS **32%**, licence self-managed **7%**, and **professional
services and other: 2%**. Support does not appear as a line item at all — it is *bundled into the
subscription*. At near-billion scale, services is a rounding error.

**The maintainer who measured it.** Perham, in the same post as the numbers above: *"I could fill the
Sidekiq website with boring whitepaper case studies and sell 24/7 support but… ugh."*

**The founder who walked up to it and refused.** Keygen's Zeke Gabrielse took ~1 year to his first
paying customer and five years to full-time, and **declined deals upwards of $100k/year** because
enterprise contracts demanded custom features, isolated infrastructure and long sales cycles. He
describes selling support and consulting to enterprises as *"the hardest route, imo."*

**The structural objection.** Support revenue rewards a product that is hard to configure. And
large buyers run three-bid procurement with heavy vendor diligence — "there's a difference between
Mongo Inc and the two freelancers."

**curl is not the counter-example it appears to be.** Stenberg does *not* sell support himself. It
took twenty-one years from first release to a full-time curl income, and the mechanism was joining a
company that already had an enterprise sales motion — wolfSSL handles contracts, billing and
procurement while he does engineering. His own framing: *"curl has reached this level of success
entirely without anyone offering commercial services around it."*

**The synthesis, which is counterintuitive and audited:** the instinct is that enterprises who
self-host won't buy hosting, so sell them support. GitLab's filing says otherwise — self-managed is
66% of revenue, but sold as a **per-seat subscription with support included**, not as a support
contract. So: **licence per seat and bundle the support; do not sell support as a separate SKU.**
Bespoke support contracts are the thing that consumes a two-person team.

---

## Third-party plugin economies: the seeding insight is true and does not unlock what we hoped

**Cheap generation created a plugin commons, not a plugin economy.** The comparison is stark:

| Ecosystem | Artifacts | Third-party revenue |
| --- | --- | --- |
| MCP official registry | **12,251 servers from 8,551 publishers in ~18 months** | **$0** — no payment rail exists |
| n8n community nodes | 12,522 npm packages | **$0** |
| WordPress.org | 66,480 plugins | Large, but **entirely off-platform** |
| Atlassian Marketplace | 6,000 apps, 2,000 vendors | **$6B lifetime** |

Atlassian has two orders of magnitude fewer artifacts and infinitely more money. **Artifact count and
third-party revenue are uncorrelated** — arguably anti-correlated, since free generation produces
spam-shaped supply (one MCP publisher ships 375 servers single-handedly).

The pre-AI control case settles it: **Home Assistant has 672,517 active installs, thirteen years,
thousands of integrations, and zero paid third-party plugins.** Install base plus a plugin API was
never sufficient.

**The four preconditions for third-party money**, derived from what separates Atlassian and WordPress
from Jenkins, Home Assistant and MCP:

1. **A payment rail the buyer already uses.** Atlassian's real innovation is procurement — licensing
   tied to the host's seat tier, on the same invoice, so the buyer never makes a separate purchase
   decision.
2. **A buyer who is not the builder.** Every dead ecosystem sells to engineers who build rather than
   buy. Every live one sells to someone whose job is not building.
3. **A problem the buyer would otherwise pay a person to solve.**
4. **Credible platform self-restraint.**

**Precondition 2 cuts our own products in half.** git-serious sells to platform engineers, who build.
Compliance and 20x sell to people who do not build and who currently pay consultants. If a
third-party plugin economy ever forms around TAP, the evidence says it forms on the compliance side.

**Two hard constraints on the "unequivocally open + for-profit plugins" model:**

- **The marketplace cut is dead.** Not one company in the research set monetizes via a plugin marketplace
  cut. Odoo is the only confirmed revenue-share (30% commission) and it has 8,000+ employees. Everyone
  else — WordPress, Grafana, Backstage, NetBox, Nextcloud, Home Assistant — runs a **free directory**.
  A directory is a distribution and credibility asset, not a revenue line.
- **No genuinely-open platform has a third-party paid plugin economy.** Every fast-growing AI-era
  platform with a real business has left OSI-open (n8n, Dify, Open WebUI, Directus). The ones that
  stayed open — Cline, Kilo, Coolify, Ollama, Home Assistant — monetize hosting, tokens, hardware or
  sponsorship, or were acquired. The combination we want has **no precedent**, which does not make it
  impossible but does mean being first rather than following.

**What seeding an ecosystem actually costs, though, is genuinely cheap — and NetBox is the direct
analogue.** Effectively solo-authored core (10,888 commits versus 700 for the next contributor);
plugin API shipped four years after open-sourcing; first genuine third-party plugin **three months
after the API existed**; today **164 plugins from 114 distinct owners**. What it took: a plugin
tutorial, a cookiecutter, a demo plugin, a curated catalog with tiers, and a promotion ladder from
community repo into the official org. No bounties — no bounty programme anywhere in the research set
worked. That is weekend-scale investment repeated over years, and it is the one part a two-person team
can copy verbatim.

**The one thing to refuse: do not take custody of plugin distribution.** Every ecosystem-control
disaster came from the vendor holding the only channel and then being tempted to use it — Nagios
seizing the plugins domain (2014), WordPress force-pushing a fork of Advanced Custom Fields to
millions of installs (2024), ownCloud (2016). In each case the community rebuilt elsewhere within
weeks; in ownCloud's case, *profitably* within six months. Use PyPI.

---

## Cloud marketplaces: nobody has done this, and the reason matters

**No open-source project monetizes itself through a cloud marketplace, and nobody has written about
the idea.** That is a real gap — with a caveat that weakens it considerably.

**The path exists and is cheap.** AWS explicitly names *Individuals* as a supported seller type. A
free listing needs only a public profile — **no tax interview, no bank account, no KYC, 0% fee**, with
AWS naming open source specifically. Then a **"Premium support" professional-services listing**
requires only that it support "at least one public product in AWS Marketplace" — *our own free listing
satisfies that* — and transacts via private offer at a **0.5% fee** (cut from 2.5% in June 2026).

**The procurement thesis holds, and the evidence is buyer-side.** A platform engineer at a large
company: either a one-to-two month procurement process involving compliance, finance and security
questionnaires — "OR I can go to the AWS marketplace, click a button… because AWS is already an
approved vendor." Another: "infosec are happy because it's got the AWS checkmark beside it."

**Three constraints kill it as a revenue plan.**

- **Committed-spend drawdown mostly does not apply to us.** Google excludes professional services *and*
  non-GCP-hosted software. Azure requires the licence be used exclusively in Azure — hybrid or on-prem
  is ineligible. AWS publishes nothing; the independent estimate is a 25% cap. For self-hosted software
  sold as support, "they'll pay from committed budget" is a story, not a mechanism.
- **The ceiling for small sellers is about $1,000/month.** One of only two sellers with published
  numbers reported receiving $362 against $1,000 expected. The "$1bn club" floor is roughly $500M ARR;
  no bootstrapped company appears, out of 43,154 listings.
- **A marketplace converts demand; it does not create it.** AWS provides sellers no impression or
  click metrics at all. Corey Quinn, asked whether he had ever discovered anything through it: *"Only
  as a procurement vehicle; never discovered anything through it."* It is a **procurement credential,
  not a billboard.**

**Operational warnings.** There is **no delisting** — AWS does not terminate marketplace accounts,
products cannot be removed, listings cannot be transferred between seller accounts. Use a dedicated
AWS account. That also explains the absent failure literature: people who regretted it have no exit
and no post-mortem to write, so "nobody has written about it" is weaker evidence of opportunity than
it looks. Azure retired Docker container offers in January 2024 (new listings must be Kubernetes
Applications with Helm, CNAB and AKS), and both Azure and Google require a legal entity rather than an
individual.

**Three channels now gate on the same word.** AWS free listings require "production-ready software"
and "a defined customer support process"; Google requires "production-ready (not alpha or beta)" and
"enterprise-ready… a defined sales motion, customer support." **The alpha posture is a listing
blocker.**

**Adjacent and worth watching:** the Open Source Maintenance Fee (WiX, now Polly) is the purest form
of the procurement thesis minus the cloud — it attacks the barrier directly, because the problem was
never that companies won't pay, it's that they can't route a donation through purchasing.

---

## Time to first dollar, and where attention comes from

Consistent across every documented case: **9–18 months to first real dollar, and three years to $1M
ARR at the very best.** Plausible monetized from day one ($64 MRR at month zero, 100 paying
subscribers at day 364, $1M ARR at ~3 years). Keygen took ~1 year to first customer and five years to
full-time. Sidekiq took eight months from open-sourcing to Sidekiq Pro. Coolify took ~18 months to
full-time. **Nothing in the AI-era cohort beats Plausible's pre-AI curve.**

**On channels, a warning that contradicts instinct.** Hacker News was Plausible's largest traffic
source by volume (43.6K visitors) and its **worst by conversion quality**; Google search converted
best, with trial-to-paid at 33.5%. Keygen's founder puts it bluntly: Product Hunt, Indie Hackers and
Hacker News generate *"dopamine boosters"* rather than paying customers for B2B products.

**Open-startup transparency does not drive adoption, and the movement is receding.** Plausible's own
`/open` dashboard now returns 404, and it never appeared among their signup drivers. openstartuplist
is stale since 2020; Baremetrics' list is a husk; Documenso's "open startup" page publishes users and
stars but **no revenue**. Only Buffer ($26.1M ARR, salaries published by name) and Ghost remain live —
and both were at scale before transparency became their brand. Treat it as content marketing.

---

## What this means for us

**The moat framing survives this research intact and is reinforced by it.** Fork cost collapsed
alongside plugin cost — Cline to Roo Code took four months, Roo to Kilo five, and by May 2026 Roo was
archived with a billing address in its README while Kilo was acquired. A full fork-chain lifecycle in
nineteen months. There is no defending code.

**The monetization options that fit, in order of evidence:**

1. **Paid features, not paid permission.** If money ever needs to flow, Sidekiq's data says build a
   separate better thing rather than restricting the free thing. Our enterprise-control surface — SSO,
   RBAC, audit retention, compliance artifacts, air-gap — is the line the market consistently accepts,
   and we already built the auth and boot layer where it would live.
2. **Per-seat self-host licence with support bundled**, if enterprise adoption arrives. The €15k–$25k
   band is what a named human and an SLA costs.
3. **A free AWS listing as a procurement credential**, once "production-ready" is honestly claimable —
   on a dedicated AWS account, treated as a closing instrument rather than a discovery channel.

**What to stop planning for:** a plugin marketplace cut (dead everywhere), donations as a revenue line
($30 in six months for Plausible; $400/month for core-js at 250 hours), marketplace drawdown for
self-hosted software (excluded by policy on two of three clouds), and third-party plugin sales funding
core development (no case exists).

**What to actually do about the ecosystem:** copy NetBox. Tutorial, cookiecutter, demo plugin, curated
catalog with tiers, promotion ladder. Keep distribution on PyPI and never take custody of it. Expect
third parties to arrive months after the machinery is genuinely easy, not because they were paid.

**And the open question this leaves:** whether the plugin ecosystem is a *product* strategy or a
*continuity* strategy. The evidence says it will not fund us. But an ecosystem of people whose own
work depends on the platform continuing to exist is exactly the succession asset the moat framing
identified — the replacement maintainer is nearly always an existing user. That may be its real value.

---

## Evidence quality

**Verified from primary sources:** Ghost's live ARR dashboard; Buffer's live dashboard; GitLab's
FY2026 10-K on SEC EDGAR; Plausible's dated founder posts; Perham's published Sidekiq numbers;
core-js's maintainer post; all support price points (published pricing pages); Flowise's own shutdown
notice; AWS/Azure/GCP marketplace documentation and fee schedules; GitHub API counts for stars,
plugins and registry entries.

**Analyst estimates, not disclosures — treat as directional:** all 2025–26 ARR figures for n8n
($40M+), PostHog ($57.5M), Supabase ($170M) and Grafana ($425M) trace to Sacra, which labels them
estimates. n8n's cloud/enterprise/OEM revenue split is the same source with undisclosed methodology.

**Explicitly unreliable:** Runa Capital's ROSS Index and the OSSCAR Index measure GitHub stars and
downloads only, despite being presented as open-source-company rankings. Coolify's ARR (including any
range derived from its founder-stated customer count). Dub's "$10M payouts" is payment volume flowing
through the platform, not revenue. An earlier claim in this session that Anthropic's skills ecosystem
had "649 official skills from 54 vendor teams" **could not be substantiated** and should not be used.

**Could not be closed:** support attach rates — what fraction of self-hosted users buy support. No
credible figure exists anywhere; treat any number offered as invented. Also open: Nabu Casa's revenue
and subscriber count (never disclosed), Automattic's annual revenue (never disclosed), and whether any
platform has published an honest "our plugin ecosystem never materialized" retrospective — none was
found, which is itself a survivorship-bias warning over everything above.
