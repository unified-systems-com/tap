# Governance Records

Durable public records of decisions taken under
[`GOVERNANCE.md`](../../GOVERNANCE.md). The subject is *who decided what, under
which authority* — not how the code works and not how the team works.

`GOVERNANCE.md` describes the mechanisms; this directory is where their exercise
is written down. That split matters: the document is a stable contract, and a
record of a single decision is not. Amending the contract requires the Steward's
agreement; filing a record does not.

## What gets recorded here

- **Appointments** — an independent reviewer under Disputes, or a successor
  Philosopher King for Now.
- **Dispute determinations** — matters escalated to the oversight body, including
  who recused.
- **Conduct determinations** — that a decision was reached and by whom. See the
  confidentiality boundary below.
- **Ownership handoffs** — a named part of the system handed to a new owner under
  Subsidiarity, or returned.
- **Sabbaticals** — a PKFN stepping back for a defined period, the acting deputy
  named for it, and the end date.
- **Continuity events** — a resignation, a declaration that the role is vacant, or
  an invocation of the dormancy backstop.
- **Steward transfers** — stewardship passing to a successor Steward, to a
  foundation, or to a fork blessed as the continuation.
- **Reconciliations** — where a decision was shown to depart from the stated
  philosophy and was reversed, explained, or the philosophy amended, per the
  eventual-consistency clause.

Doctrine does not live here. A rule that binds future decisions belongs in
`GOVERNANCE.md` or in specification canon; this directory records that a decision
was made, not what the project now requires.

## What a record contains

Every record states, at minimum:

- the **date**,
- **what was decided**,
- **who took part**, and
- **who recused**, and from what.

## Confidentiality

Some matters are public in fact but not in substance. Where confidentiality is
owed to a reporter under [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md), the
record states that a decision was taken and by whom, and says nothing further.
The existence of the process is always public; the contents of a report are not.

## Filing convention

`docs/governance/<YYYY-MM-DD>-<short-slug>.md`, matching the convention used by
[`docs/aar/`](../aar/).

Records are not removed and are not rewritten. A record that turns out to be
wrong or incomplete is corrected by filing a new record that references it — the
git history of this directory is part of what makes the mechanism checkable.

## Neighbors

Three corpora under `docs/` answer three different questions:

- **`docs/governance/`** (here) — *who decided, and under what authority?*
- **[`docs/aar/`](../aar/)** — *did we work well?* Retrospectives on the
  development process.
- **[`docs/postmortems/`](../postmortems/)** — *did the system behave well?*
  Defects in TAP itself.

## Current state

Empty. No decision requiring a record under `GOVERNANCE.md` has been taken yet.
That is the honest state of a young project, and it is visible here rather than
asserted somewhere else.
