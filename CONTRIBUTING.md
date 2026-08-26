# Contributing to TAP / Rampart

**Project steward:** Unified Systems LLC.  
**Baseline license:** Apache License, Version 2.0.

This project uses the Developer Certificate of Origin, Version 1.1 (DCO), rather than a Contributor License Agreement. By intentionally submitting a contribution for inclusion in the project, you agree to the contribution terms below.

## How to Contribute

Contributions arrive as GitHub pull requests. For anything larger than a small fix, open an issue first so we can agree on direction before you invest the work. Development setup is one command — see "Get it running" in the README.

To report a security vulnerability, do not open a public issue or pull request; follow `SECURITY.md`.

## What to Expect

This is a small project. Expect a first response to an issue or pull request within about a week. If it goes quiet for longer than that, say so on the thread — a nudge is welcome and is not rude. How decisions get made, and what to do if you disagree with one, is in `GOVERNANCE.md`.

## Specifications Come First

Behavior in TAP is defined by specifications in `specs/` and `<app>/specs/`, not by the code that happens to implement it. A requirement carries an identifier, a status, and — once it claims to be built — machine-checked evidence that it is.

This is enforced. Adding a requirement without accounting for it, or flipping one to `Implemented` without evidence, fails the gate and blocks your push. The happy path is short: write the requirement with `Status: Proposed`, build it, mark the tests that prove it with `@pytest.mark.spec("<rid>")`, and flip the status in the change that lands the evidence.

Read `docs/doc-dev-spec-driven-contribution.md` before your first substantive change. It covers the failure modes, the `scripts/implements-tag` minting flow, and what to do with a requirement that legitimately maps to no code.

## Tests and Code Quality

Changes that add or modify behavior must include tests for that behavior; bug fixes should include a regression test. The full suite (`scripts/test`) must pass. Code must come back clean from the formatters, linters, and type checker (`black`, `ruff`, `mypy`) — warnings are fixed, not accumulated, and any suppression (`# noqa`, `# type: ignore`) carries a justification on the line. CI enforces all of this on every merge to `main`.

## Commit Messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`.

This is functional, not stylistic. Pull requests land as merge commits, so your individual commit messages survive into `main` — and `release-please` reads them to decide the next version number and to write `CHANGELOG.md`. A commit called `fixed the thing` produces no changelog entry and no version bump.

The types in use are `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, and `chore`. Scope is the app or subsystem (`feat(grid):`, `docs(governance):`, `ci(cicd):`). A breaking change carries `!` after the type and an explanation in the body.

Write the body for someone who was not there. The summary line says what changed; the body says **why**, what you considered instead, and anything that would surprise a reader six months from now. That is the part nobody can reconstruct from the diff.

## Pull Requests

**The title describes the change, not the mechanism that produced it.** `promote: session-x → main`, `merge branch`, and `AI session updates` are all titles that tell a reviewer nothing about what they are approving. Say what actually changes: `feat(cicd): reusable release lane accepts non-plugin dists`. If the pull request carries several unrelated things, the title names the largest and the body enumerates the rest.

**The body declares everything in the diff.** A pull request that quietly contains a contract change, a new spec section, or a security-relevant edit — under a body that mentions none of them — is worse than one with no body at all, because the reviewer believes they have been told. If you cannot summarize the change without a list, use a list.

The template checklist is not decoration; each line is a thing a reviewer would otherwise have to verify by hand. Session promotes are the one exception to writing the body by hand: `scripts/promote-to-main.sh` derives it from the diff on every push via `scripts/promote-pr-body`, so it cannot drift from what it declares. The title is still yours to write.

Every pull request gets an automated review shortly after it opens. Whoever opened it is expected to read that feedback — including suppressed findings — and either act on it or dismiss it consciously before calling the work done. `scripts/pr-review-triage <pr>` collects it.

## Licensing of Contributions

This project is licensed under the Apache License, Version 2.0. See `LICENSE`.

By intentionally submitting a contribution for inclusion in the project, you license the contribution:

1. under the Apache License, Version 2.0; and
2. effective upon adoption, under any later **permissive** license approved by the Open Source Initiative (OSI) that the project adopts, to all recipients of the work.

"Permissive" means a license that, like Apache 2.0, does not condition distribution or modification on releasing source code or on licensing derivative works under the same or another specified license.

The second grant runs to everyone who receives the work. No entity, including the project steward, receives a special relicensing right. The project will never distribute your contribution under a proprietary, source-available, or copyleft license.

The Project Steward is Unified Systems LLC, acting through a written resolution of its sole member or through a successor governance process expressly authorized by such a resolution.

The project adopts a license migration only after written approval by the Project Steward, confirmation that the target license is OSI-approved at the time of migration, written compatibility and transition analysis, public notice explaining the reason for the migration, identification of the project versions and contributions affected, preservation of all previously granted Apache 2.0 rights, and no migration to a proprietary, source-available, non-OSI-approved, or copyleft license.

The public notice must be posted in this repository at least 30 days in advance and followed by an update to the `LICENSE` file. Until that happens, Apache 2.0 is the project's sole license.

No copyright assignment is required. Copyright remains with the applicable rights holder, to the extent copyright exists.

## Why the Prospective License Grant Exists

Software development and copyright law are changing rapidly. AI-assisted development makes authorship, ownership, and even the identity of the party whose consent would be needed increasingly uncertain. Apache 2.0 does not contain an "or any later version" mechanism, and a DCO-only project may not be able to identify, locate, and obtain new signatures from every applicable rights holder after years of contributions.

The prospective grant preserves the project's ability to respond responsibly to changes in law, technology, and open-source practice while keeping every permitted migration inside a narrow boundary: permissive, OSI-approved licenses materially similar in downstream effect to Apache 2.0. The project has no plan or obligation to migrate; it will decide if and when the question ever arises, through the written approval, compatibility-analysis, public-notice, and `LICENSE`-update mechanism above.

## Sign-Off

Every commit must include a `Signed-off-by` line certifying the Developer Certificate of Origin, Version 1.1. See `DCO`.

```text
Signed-off-by: Your Name <your.email@example.com>
```

Use `git commit -s` to add the trailer. Your sign-off certifies that one of the provenance paths stated in the DCO applies and that you have authority to submit the contribution. The sign-off does not by itself establish that you authored every element of the contribution.

Your tooling may apply the `Signed-off-by` trailer automatically (for example via `git commit -s` or a commit hook); the certification is your act of submitting the contribution after personal review, not the mechanical addition of the trailer.

Commits authored by automated dependency-update tooling (for example, Renovate) are exempt from the sign-off requirement; a maintainer reviews and certifies them at merge, normally by squash-merging with their own sign-off.

If you have already pushed a commit without a sign-off, you may certify it retroactively with a **remediation commit** rather than rewriting history — useful when others may have pulled your branch. Add a later commit, itself signed off, whose message contains one line per commit being certified:

```text
I, Your Name <your.email@example.com>, hereby add my Signed-off-by to this commit: <commit sha>
```

The identity you declare must be your own and must match the author of the commit you are certifying: this form lets you certify your own earlier work, not anyone else's.

## Employer and Organizational Authority

If your employer or another organization may own or control rights in your contribution, you must obtain authorization before submitting it. Your DCO sign-off certifies that you are authorized to submit the contribution on behalf of the applicable rights holder.

The project may request written employer or organizational authorization before accepting a substantial contribution.

## AI-Assisted Contributions

AI-assisted contributions are welcome.

An automated system must not certify the DCO. A contribution and commit may be prepared using AI-assisted tools, but the named human signer must personally review the contribution and deliberately authorize the `Signed-off-by` certification. The signer is the accountable certifying contributor, not necessarily the author of every element.

By signing off, you confirm that you have reviewed the contribution sufficiently to explain it, maintain it, and take responsibility for submitting it, and that you have no reason to believe it contains third-party material that cannot lawfully be included under the project's contribution terms. You should also ensure that your AI tool's terms do not restrict use of its output in a manner inconsistent with those terms.

Significant AI assistance may be disclosed in the commit message or pull request description, for example:

```text
Assisted-by: <agent>:<model>
```

Disclosure is encouraged but not required during the initial project phase.
