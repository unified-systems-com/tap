# Governance

If it wasn't obvious already: we're making this all up as we go.

This document describes the present state of affairs. It derives from existing
best practices — subsidiarity, recusal, dormancy backstops — and includes some
new parts like what happens when the person currently making most of the
decisions starts getting worn down and needs a break.

The world has changed. It's changing faster than ever, particularly when it
comes to software development, operational systems, and their impacts. It makes
sense that the old models of management don't fit the way they used to.

This is an in-flight attempt to find something better suited to the moment.

If you have opinions and ideas, please share them.

## Roles

### Project Steward

The Project Steward is **Unified Systems LLC**, acting through a written
resolution of its sole member or through a successor governance process
expressly authorized by such a resolution.

The Steward holds legal authority: licensing and any future license migration
(bounded by the terms in `CONTRIBUTING.md`), custody of the project's assets —
the `unified-systems-com` organization, package and registry namespaces,
domains, and signing material — and appointment to the leadership role below.

The Steward does not direct day-to-day technical work. The Steward is a
different person from the day-to-day leadership, which is deliberate: it means
the constraints on relicensing in `CONTRIBUTING.md` are enforced by someone
other than the person who would typically be in a position to want them
relaxed.

That separation is real for licensing and weaker for conduct. The leadership of
Unified Systems LLC and the Philosopher King for Now are married. It means the
relicensing constraints are held by someone with no reason to relax them, and it
means the two are not independent of one another where a matter concerns the
maintainer. See "Disputes" for what follows from that.

### Philosopher King for Now

Technical direction, specification canon, and code of conduct enforcement rest
with one person, the **Philosopher King for Now** (PKFN). Other projects call
this role the BDFL — Benevolent Dictator for Life. The difference is deliberate
because benevolence, like hope, is not a strategy.

The PKFN is appointed by, and serves at the pleasure of, the Steward.

George Chamales is presently the PKFN.

**The basis is philosophical.** Authority rests on a stated philosophy that
directs how the project should be built and managed — not on ownership,
seniority, good intentions, force of will, or knowing the most about the code.
The PKFN is expected to publish and operate in line with their philosophy. The
current operational philosophy is the *Way of the Grid* (`wog/`), itself a work
in progress; the architectural rules descending from it are demonstrated in the
specifications.

That basis for leadership is arguable, correctable, and transferable. This is
the essential point. A successor is not required to adopt this philosophy. They
are required to have one, to publish it, and to be held to it in the same way.

**The expectation is eventual consistency.** Judgment takes effect only once it
has been written down where it can be inspected — as a specification
requirement, a guard, or a test. See "How a decision becomes binding" below. A
ruler obliged to publish their reasoning before it binds anyone is limited in a
way that a benevolent dictator is not. Add to that the expectation for that
reasoning to cohere to a consistent philosophy and you've got 'em coming and
going. That bounding is essential to avoid scope creep.

Consistency is required to converge, not to be instantaneous. Anyone may
protest that a decision departed from the stated philosophy — no competing
philosophy is needed to raise the objection. The PKFN must then explain the
reasoning, reverse the decision, or amend the philosophy. None of that is free.
All are on the record and visible in the history. Silence and indecisiveness
are unacceptable: a contradiction left standing and unreconciled is one type of
failure this clause exists to catch.

**The tenure is bounded.** "For Now" is not modesty; it is a removability
clause, and the conditions under which it fires are stated in "Continuity"
below. The role anticipates its own end rather than requiring an escape to be
improvised during a crisis. You can take a shot at the king. It must be clear
how that shot can land. Also, let's be real, the BDFL concept was created by
people who are still alive and may not have been in a position to fully
recognize the strategic implications of a life sentence.

### Contributors and delegated sessions

Work produced under a person's delegation is that person's work and that
person's responsibility. Contributors decide within the scope of the work they
take on. They do not need permission to exercise their judgment; see
"Subsidiarity" below.

The clearest example today is this one: TAP is developed with substantial help
from AI coding agents working autonomously in isolated session worktrees. They
are real subordinate bodies under the subsidiarity rule, and the line governing
them is that **competence devolves and accountability does not.** An agent may
decide within its scope. It may not set canon, advance `main` outside the gate,
certify the Developer Certificate of Origin, or widen its own mandate.

### Plugin maintainers

Plugins live in their own repositories with their own tests, releases, and
manifests. As plugins acquire maintainers other than the core project, those
maintainers hold decision authority over their plugin, bounded by the
interfaces and posture requirements core enforces globally.

## How a decision becomes binding

Specifications are the canonical source of truth. A decision that has not been
written where it can be inspected is not yet a decision — it is an intention,
and it binds nobody. Unbounded reasoning is an anti-pattern in the age of AI.

This is the project's oldest working rule and the real check on concentrated
authority. It also makes governance auditable: because decisions are recorded
as requirements with stable identifiers, it is possible to see at *which level*
a decision was taken, and to argue if it was the right one.

## Subsidiarity

Decisions belong to whoever is closest to the work and competent to make them.
*Subsidiarity* cuts both ways: the core does not make decisions that belong at
the edges, and the core is obliged to provide the edges the assistance they
need to decide well. Specifications, guards, and plugin tooling are some of the
ways that obligation gets paid.

You do not need permission to decide inside your own scope. What you get in
exchange is that you own the result. A decision made further from the work than
it needed to be is a defect, not diligence — nobody likes a micro-manager.

That ownership is what legitimizes the use of AI agents. Hand as much of your
work to an AI as you like; most of this project is built that way. The work is
still yours — its correctness, its licensing, its DCO sign-off, its tone.
Autonomous coding agents are the worked example, under "Contributors and
delegated sessions" above.

The same rule lets ownership move. The PKFN, plugin maintainer, or other owner
may hand a named part of the system to someone better placed to hold it, who
then decides within it without asking. Handoffs are recorded in
`docs/governance/` and can be undone the same way.

## Disputes

Ordinary technical disagreement is resolved by the PKFN. That is what the role
is for, and being overruled is a normal outcome rather than a grievance.

Everything else — disputes about the decisions or conduct of the maintainer
role itself, and conduct reports generally — goes to the **oversight body**:
the leadership of Unified Systems LLC together with the PKFN. The LLC's
internal composition may change without changing this document; whoever leads
it at the time holds that seat.

**Recusal.** Anyone on the oversight body with a stake in a matter recuses from
it. Recusal is expected and implies no wrongdoing — a maintainer whose own
decision is under review recuses as a matter of course.

Because the two members of the oversight body are married, recusal alone does
not leave an impartial body where a matter concerns the maintainer. In those
matters the independent reviewer below is the mechanism rather than a fallback.

**Replacement.** The remaining members do not simply decide alone. They select
an **independent reviewer** — someone who is neither part of Unified Systems
LLC's leadership nor a maintainer of this project, and who holds no material
stake in the outcome — and name that person in the record of the decision. The
same mechanism resolves a deadlock: where the body cannot reach agreement, it
appoints an independent reviewer whose determination settles the matter.

Where every member is recused, the Steward still makes the appointment, because
someone must hold the power to appoint — but takes no part in the decision
itself.

The appointment is public; the matter need not be. Where the dispute is a
conduct report, the confidentiality owed to the reporter under
`CODE_OF_CONDUCT.md` governs what is said about the substance.

No independent reviewer has been identified in advance, and naming one now would
be premature: this project has no contributors yet, and the body has never met
about a dispute that has never happened. The commitment is to find one when a
matter requires it, and to name them publicly when it does.

Independently of all of the above, GitHub's own abuse reporting and Terms of
Service apply to this repository and are not within this project's control.
Anyone uncomfortable raising a matter internally may use that channel.

## Records

Decisions taken under this document are recorded publicly in
`docs/governance/`, dated, and not removed. A record states what was decided,
who took part, and who recused. Where confidentiality is owed — a conduct
report under `CODE_OF_CONDUCT.md`, most obviously — the record states that a
decision was taken and by whom, and says nothing further about the substance.

This is the same rule the project applies everywhere else: a decision that is
not written where it can be inspected is not yet a decision.

## Continuity

Authority of the PKFN under this document rests on three conditions together:
the **philosophy** guiding development of the system, the **capacity** to be
accountable for it, and the **willingness** to be. A stated philosophy alone is
not sufficient — an autonomous agent can hold one and apply it faithfully and
still not answer for it, which is why agents hold delegated competence but
never standing.

Two conditions can lapse, and each has its own relief valve, because one is
known from the inside and the other is visible from the outside.

**Willingness — declared.** The PKFN may resign the role at any time, in
writing, to the Steward. This is expected to happen eventually — on a long
enough timeline everyone's survival rate drops to zero. Resignation is not
treated as abandonment, and does not necessarily reflect failure of the person
or the role; a maintainer who has stopped wanting the work but stays nominally
in place is the worst outcome for everyone, so let's not do that.

Resignation is whole, because the role is not divisible. The Steward does not
direct technical work, so a partial handback would park authority with someone
who has neither the mandate nor the capacity to exercise it. This is also what
"competence devolves and accountability does not" already requires: the work
can be devolved, responsibility for it cannot.

The work, by design, is entirely divisible. A PKFN who no longer wants part of
the job delegates it to whatever level is competent to hold it, and remains
accountable for the whole — subsidiarity applies, requiring no one's
permission. When delegation stops being enough, the remedy is resignation.

**Capacity — observed.** The Steward observes whether the role is being
exercised — whether decisions are being made and the project is moving forward.
This is not a judgment about the person's health, circumstances, or worth. If
the role is not being exercised, the Steward may declare it vacant.

If the Steward is also unavailable, there is no one left to observe, so a
dormancy backstop applies: where there has been no response from either party
to a governance-level request for **90 days** and no merge to `main` for **180
days**, the project is dormant, and the continuity provisions below take effect
without further declaration. The thresholds are deliberately long and
deliberately objective, so that invoking them is an observation rather than a
coup.

Capacity is not only about absence. A project can ship steadily while the
person holding it is running on empty. Where that is what is happening,
declaring the role vacant is the wrong instrument — that's what sabbaticals are
for.

## Sabbatical

The usual way open-source maintainers end is not incapacity but attrition —
worn down by sustained conflict, or by carrying too much alone for too long.
That failure arrives disguised as a willingness failure: the maintainer resigns
when what they needed was relief. Projects with no option short of resignation
have improvised one under pressure, or failed to, and lost the maintainer
either way.

So the option is stated in advance. The PKFN may step back for a defined period
without resigning, and owes no one a justification for it. This is not a
partial handback of the role. It is the role continuing, held by someone else,
for a stated time.

To take a sabbatical, the PKFN names an acting deputy and an end date, in
writing, to the Steward. Where the PKFN is not in a position to, the Steward
may do both. Sabbaticals, their deputies, and their end dates are recorded
under "Records" above.

An acting deputy holds the role and exercises it — deciding, setting canon, and
amending specifications as the work requires. What a deputy may not do is
change the terms on which they hold it: amend this document, replace the
published philosophy, extend their own appointment, or name a successor. The
PKFN's seat on the oversight body is treated as recused for the duration rather
than passed to the deputy, and the provisions in "Disputes" above cover the
gap. The appointment lapses on its end date unless extended the same way it was
made.

The role is being kept, not redefined. This is the rule that stops an agent
widening its own mandate, applied one level up.

A sabbatical that keeps being extended is a signal rather than a solution.
Where the role has been held by a deputy longer than it has been exercised, the
Steward should consider whether succession is the honest solution.

## Succession

Either the willingness or capacity valve leaves the role vacant, and what
follows is the same in both cases. The Steward selects the next PKFN and is
expected to consult contributors and plugin maintainers before doing so.

A successor must have a demonstrated record of work in this project. The role
is not a seat that can be handed to a stranger on the strength of enthusiasm —
a maintainer under pressure to hand off is a target, and an appointment made
quickly and quietly is how that pressure pays off. The vacancy and the
appointment are recorded under "Records" above before the appointment takes
effect.

The successor receives the role whole and decides for themselves how to
delegate it; arrangements made by the previous PKFN bind nobody.

## Stewardship

The Steward may step down. That is not resignation from a role — it is a
transfer of property. The organization, the namespaces, the domains, and the
signing material move, or the project has nothing to continue with.

What is not at stake is the license. `CONTRIBUTING.md` already binds that: no
entity, the Steward included, holds a special relicensing right, contributions
are certified under the DCO rather than assigned, and any migration is confined
to OSI-approved licenses with public notice. The exposure here is custody, not
licensing.

This document cannot bind the Steward's ownership of the assets, and pretending
otherwise would be decoration. What it requires is that the move be visible
before it happens.

- Stewardship passes to a successor Steward or to a foundation — whichever
  better preserves the project's ability to continue under the same terms — or
  to a fork blessed as the continuation. A successor Steward keeps the current
  structure and its risks; a foundation is bound by a charter and cannot be
  acquired, at the cost of control.
- A transfer is conditioned on the receiving Steward accepting these provisions,
  including this one. A project that can be handed over once and never handed on
  is trapped rather than stewarded.
- The PKFN is consulted first, and contributors and plugin maintainers are told
  before the transfer takes effect, not after.
- The transfer is recorded under "Records" above.
- The Steward does not dissolve without transferring or releasing the assets. An
  expired domain and an orphaned organization are the worst version of this.

Advance notice is the whole mechanism. The Apache License already lets anyone
fork at any time, for any reason — but it protects what has already been
published, not work that has not happened yet, and a fork needs enough warning
to get organized before the name changes hands. Notice is the only thing this
document can actually give it.

The internal affairs of Unified Systems LLC — its membership, and what happens
on a member's death or departure — are governed by its operating agreement, not
by this document. That agreement is expected not to contradict these
provisions.

## Amending this document

Changes to this document are made by the PKFN with the Steward's agreement, and
ride the same pull request and review process as any other change.
