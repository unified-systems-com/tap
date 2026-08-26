---
spec: ../../specs/spec-tap-requirement-traceability.md
audience: [developer, llm]
covers:
  - ../../specs/spec-tap-requirement-traceability.md
  - ../../specs/spec-req-template.md
update-triggers:
  - A decision is made on adopting a type field or an evidence declaration — record it here
  - The Status vocabulary in spec-req-template.md changes
  - The evidence report's categories change
provides: |
  Prior-art sweep on how established systems categorize requirements for evidence/coverage
  purposes — the taxonomy question raised by TAP having 506 requirements declared built with no
  code evidence. Covers the four orthogonal axes, the convergent three-way type split, why
  doctrine's terminal status is "Active" rather than "Implemented", and the design rules that
  keep an evidence declaration from rotting. PRE-DECISION.
---

# Requirement Categories — Prior Art

**Status: pre-decision.** Written 2026-08-13 after the Wave 3 measurement found **506 of 517**
requirements declared `Implemented` carry no code evidence — and that faulting them would
contradict `req-tap-traceability-scope-1` (claims are opt-in). That tension is a symptom of a
missing category: TAP's corpus mixes *build-this* requirements with *standing-doctrine* ones and
gives them the same status vocabulary.

## The headline: TAP's numbers are not anomalous, and the fix is mostly a relabel

**NIST SP 800-53 Rev 5's own ratio is worse.** Parsed from the published OSCAL catalog: **613 of
1,014 non-withdrawn controls (60%) are `implementation-level: organization`**, and **108 have no
`TEST` assessment method at all** — every `-1` policy-and-procedures control, the whole
awareness-training family. NIST does not treat that as a defect; it treats it as a fact that must
be *visible in the model*. CIS says it outright: *"The guidance items in the Benchmarks are called
**recommendations and not requirements**."*

**The single most actionable finding.** Python's PEP 1, verbatim:

> *"Some Informational and Process PEPs may also have a status of **'Active' if they are never
> meant to be completed**."*

Doctrine's terminal state is **in force**, not **done**. TAP's ~506 requirements are very likely
*mis-stated* rather than *unevidenced* — a standing filter marked `Implemented` is answering the
wrong question, because it will never be "completed." Relabelling them dissolves most of the
apparent gap **without changing a single requirement**, and it makes the remaining
actionable-but-unevidenced set a real, small worklist.

## Four orthogonal axes — and every failure is a conflation of two

| Axis | Question | Vocabularies |
| --- | --- | --- |
| **KIND** | what property does it constrain? | 29148 Type (6 values) · RTEMS functional/non-functional (25) · ISO 25010 (9 quality characteristics) |
| **LEVEL** | at what abstraction does it live? | BRS/StRS/SyRS/SRS · DO-178C system/HLR/LLR · OpenFastTrace artifact types (`feat`→`req`→`dsn`→`impl`) |
| **STRENGTH** | how binding is it? | RFC 2119 MUST/SHOULD/MAY · IETF Required/Recommended/Elective · FedRAMP's `force` enum |
| **EVIDENCE MODE** | what would prove it? | Test/Analysis/Inspection/Demonstration · NIST Examine/Interview/Test · CIS Automated/Manual · OFT `Needs:` |

**The axis TAP hit is EVIDENCE MODE**, and the standards mostly leave it implicit. Worse, they
conflate it with KIND — 29148:2018 lists six requirement types *and* a contradictory 13-section
document outline in the same edition, and deleted "Design Constraints" as a type while keeping it
as a document section.

**The theoretical reason KIND is the wrong lever**, from Glinz's RE'07 demolition of the
functional/non-functional split: *"the **representation** of a requirement (**not its kind**)
determines the way in which we can verify that the system satisfies a requirement"* — the same
requirement is non-functional stated qualitatively and functional stated operationally. That is
why CSF writes every subcategory in passive-outcome voice, PCI writes every testing procedure with
one of three verbs, and ISO defines *requirement* as *"objectively verifiable criteria."*

## The three-way type split, invented four times independently

| Concept | Python | Java | Ethereum | IETF |
| --- | --- | --- | --- | --- |
| Normative, implement it | **Standards Track** | **Feature** | **Standards Track** | **Standards Track** |
| **Binding, but not code** | **Process** | **Process** | **Meta** | **Best Current Practice** |
| Non-binding guidance | **Informational** | **Informational** | **Informational** | **Informational** |
| Living / in force | status **Active** | state **Active** | status **Living** | (BCP: no ladder) |

**The distinction TAP most needs is Process vs Informational**, and PEP 1 draws it precisely:

> *"Informational PEPs do not necessarily represent a Python community consensus or
> recommendation, so **users and implementers are free to ignore Informational PEPs**…"*
> *"Process PEPs are like Standards Track PEPs but apply to areas other than the Python language
> itself… **unlike Informational PEPs, they are more than recommendations, and users are typically
> not free to ignore them**."*

TAP's standing filters — the security posture, the AI-integration posture, FIPS doctrine — are
**Process/BCP**, not Informational. They *are* binding; they just aren't code. Conflating "not
implementable" with "not binding" would be the wrong simplification.

Why BCP has no maturity ladder, from RFC 2026: the staged standards track *"[is] not well suited
to the phased roll-in nature… and instead generally only make sense for **full and immediate
instantiation**."* Doctrine is in force or it isn't.

**The counter-examples are instructive too.** Rust RFCs and Kubernetes KEPs have **no type field
at all** — because they put doctrine in a *different repository* (`kubernetes/community`) or
different artifacts (the Rust Reference, team charters). Every project that carries long-lived
doctrine *in the same corpus* as feature proposals invented a type field and a living status.
There is no third option in the sample. TAP carries both in `specs/`, so TAP needs the field.

## Type taxonomy or per-item declaration? Neither, cleanly

**Per-item declaration** — OpenFastTrace's `Needs: impl, utest` (omit it entirely and the item
*"terminates a chain of items"*), Doorstop's `derived` / `normative` booleans. Local, reviewable
in the diff, no central schema. Fails by drifting across 1,100 hand-maintained declarations.

**Type taxonomy** — RTEMS derives the validation method *from* the type (`performance-runtime` →
runtime measurement; `design-group` → Doxygen check; everything else → inspection). One decision
covers many items. Fails because the taxonomy contradicts itself as it grows, and because KIND
doesn't predict verifiability.

**Where the still-growing tools converged: type-conditional policy declared centrally, plus
per-item escape hatches.** Sphinx-Needs explicitly *replaced* its per-item filter approach with
JSON-Schema rules that `select` by type **and tags** — so "type=req AND tags contains doctrine →
no link requirement" is one central rule, not 500 declarations.

## The four design rules that keep it from rotting

**1. The declaration must be load-bearing in BOTH directions.** OpenFastTrace's `Unwanted` status
fires when an item covers something *that didn't ask for coverage*; Doorstop warns when a
non-normative item *has* links. Flip the flag and something breaks immediately.

> **A flag that only ever *removes* a check is a flag nobody maintains.**

And it is enforceable: across NIST's published catalog, **0 of 3,707 `assessment-for` links point
at a `guidance` part**. The obligation/guidance split is a checkable graph property, and NIST
checks it.

**2. The escape hatch must cost more than the normal path.** DO-178C: a requirement with no parent
must be *fed to the safety assessment process*, independently reviewed by a different discipline,
and QA-audited. CIS: `Manual` is excluded from the score **but the tool is required to disclose
it to the user**. Nobody in the survey lets an item declare itself out of scope for free.

**3. Type is authored; status is derived.** PEP 12's template hardcodes `Status: Draft` and makes
`Type` a choose-one. NIST's 108 no-TEST controls are *derivable from the evidence model*, never
separately declared. Declare what a human knows and a machine can't infer (is this doctrine?);
derive everything a machine can compute (is there evidence? is it stale?).

**4. Never publish a single coverage number.** CIS computes `(Score/Max)*100` where `Max` is
*"recommendations that could pass or fail"* — Manual sits in **neither** numerator nor denominator,
and the manual tail is reported separately and mandatorily. CIS-CAT keeps **four distinct reasons
for "no result"** apart: `Manual` · `Not Checked` · `Not Applicable` · `Not Selected`.

> **"Not covered" is at least four different facts, and collapsing them is what makes the metric
> meaningless.**

## Two traps worth knowing

**The `must` inversion.** ISO Directives Table 7: `must` marks an **external constraint** —
something the document does *not* require (a law of nature, national law). RFC 2119: `MUST` is the
*strongest obligation*. Exact inverses. Any vocabulary mixing both conventions makes `must`
ambiguous.

**"Derived requirement" means opposite things in different standards.** ISO 29148 and NIST:
*"deduced or inferred… the next higher level requirement is referred to as a 'parent'"* — i.e. a
**child**. DO-178C and ARP4754A: *"not directly traceable to higher level requirements"* — i.e. an
**orphan**. If TAP adopts the word, it must say which sense.

## What this implies for TAP (not decided)

1. **Relabel before building anything.** Doctrine requirements marked `Implemented` should carry a
   status meaning *in force* (`Active` / `Living`). This is the cheapest and highest-yield move,
   and it shrinks the 506 to something interpretable.
2. **Add a type field with the four-times-proven vocabulary** — the actionable/doctrine/
   informational split, with TAP's standing filters as the *binding-but-not-code* middle, not as
   guidance.
3. **If an evidence declaration lands, make it bidirectional**: a claim pointing at a doctrine
   requirement must be a *defect* (`Unwanted`), not merely unremarkable. `spec-tap-requirement-
   traceability.md` already names this inverse check; the research says it is the thing that keeps
   the marker alive.
4. **Split the evidence report's "no evidence" bucket** into at least: doctrine (none expected) ·
   actionable-and-missing · actionable-and-stale · out of scope. The report currently reports one
   number with prose context; the field's verdict is that the prose is not enough.
5. **Keep KIND and STRENGTH in separate fields** (PEP's `Type` + `Topic`; rmtoo's `Type:` +
   `Class:`). Don't overload one field with domain and bindingness.

## Sources

**Standards:** ISO/IEC/IEEE 29148:2018 §5.2.4–5.2.8, §5.4 · ISO/IEC/IEEE 12207:2017 · [ISO/IEC Directives Part 2](https://www.iso.org/sites/directives/current/part2/index.xhtml) · INCOSE GtWR v4.0 · DO-178C / ARP4754A (paywalled; via [AFuzion](https://afuzion.com/avionics-software-requirements-in-do-178c/), [Parasoft](https://www.parasoft.com/learning-center/do-178c/requirements-traceability/))

**Process taxonomies:** [PEP 1](https://peps.python.org/pep-0001/) · [RFC 2026](https://www.rfc-editor.org/rfc/rfc2026) · [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) / [8174](https://www.rfc-editor.org/rfc/rfc8174) · [JEP 1](https://openjdk.org/jeps/1) / [JEP 2](https://openjdk.org/jeps/2) · [EIP-1](https://eips.ethereum.org/EIPS/eip-1) · [Swift Evolution](https://github.com/swiftlang/swift-evolution/blob/main/process.md) · [Kubernetes KEP process](https://github.com/kubernetes/enhancements/blob/master/keps/sig-architecture/0000-kep-process/README.md)

**Tooling:** [OpenFastTrace user guide](https://github.com/itsallcode/openfasttrace/blob/main/doc/user_guide.md) · [Doorstop item reference](https://github.com/doorstop-dev/doorstop/blob/develop/docs/reference/item.md) + [validation](https://doorstop.readthedocs.io/en/latest/cli/validation.html) · [Sphinx-Needs schema validation](https://sphinx-needs.readthedocs.io/en/latest/schema/index.html) · [StrictDoc user guide](https://strictdoc.readthedocs.io/en/stable/sphinx/strictdoc_01_user_guide.html) · [RTEMS spec items](https://docs.rtems.org/docs/main/eng/req/items.html) · [BMW LOBSTER](https://github.com/bmw-software-engineering/lobster)

**Compliance:** [SP 800-53r5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf) · [SP 800-53Ar5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53Ar5.pdf) · [OSCAL catalog content](https://github.com/usnistgov/oscal-content) · [NISTIR 8011 Vol.1](https://nvlpubs.nist.gov/nistpubs/ir/2017/nist.ir.8011-1.pdf) · [CSF 2.0](https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf) · [CIS scoring change](https://www.cisecurity.org/insights/blog/changes-to-cis-benchmark-assessment-recommendation-scoring) · [FedRAMP RFC-0006](https://www.fedramp.gov/rfcs/0006/)

**Theory:** Glinz, *On Non-Functional Requirements*, RE'07
