# Claude Code in this repository

**[`AGENTS.md`](AGENTS.md) is the canonical agent guide — read it first.** It holds everything about
this repository: the rules, the specs to read, the commands, the workflow, the review contract. This
file holds only what is specific to driving TAP *with Claude Code*, because Codex, Cursor and Copilot
read AGENTS.md and none of them can use what is below.

## Skills

TAP ships 24 repo skills. Each is a packaged procedure for work this repo does often, and invoking
one is cheaper and more correct than re-deriving the steps. Canonical location is `<app>/skills/`;
`wire-skills` symlinks them into `.claude/skills/` at spawn (only `get-started` is committed there,
so the rest are per-clone).

| When you are… | Skill |
| --- | --- |
| Adding a model, edge, page, panel, or collector | `add-model`, `add-edge`, `add-page`, `add-panel`, `build-collector` |
| Entering a domain TAP has not modelled | `build-domain-vocabulary` |
| Creating or specifying a plugin | `new-plugin`, `create-plugin-spec`, `unified-systems-plugin-conventions` |
| Extending or fixing Gryphon | `build-gryphon-capability`, `gryphon-fix-bug` |
| Working on requirements or traceability | `triage-requirements`, `resolve-traceability-conflict` |
| Touching architecture.md | `update-architecture` |
| Standing up, diagnosing, or opening a session | `get-started`, `diagnose-failed-session-spawn`, `launch-ui` |
| Handling secrets or credentials | `manage-secret`, `provision-secrets` |
| Opening a PR | `open-a-pr` — run it BEFORE `gh pr create`; the lane it names is the one CI runs |
| Finishing a PR | `close-out-pr` |
| Touching OpenSSL / FIPS pins | `bump-openssl-fips` |
| Rebuilding Tailwind after a template class change | `tailwind-rebuild` |
| Verifying rendered behavior in a real browser | `drive-browser` |

A skill is the procedure; the spec it cites is the canon. When they disagree, the spec wins and the
skill is the bug.

## The `.claude/` surface

`.claude/` is **local execution**: it runs on a developer's machine, so it is code-owned and installed
by an explicit human decision — cloning must never execute (`specs/spec-dev-local-execution.md`,
`req-dev-localexec-consent`; CODEOWNERS enforces the ownership). `.gitignore` admits only
`.claude/settings.json` and the one committed skill symlink; everything else there is per-developer
state and stays untracked.

Adding a surface under `.claude/`, `.githooks/`, or `scripts/hooks/` without its CODEOWNERS rule is a
defect.

## Attribution

Claude prepares commits; the named human certifies them. `CONTRIBUTING.md` § Sign-Off draws the line
in the one place it actually falls, and it is not where a reader of the old wording here would guess:

> Your tooling may apply the `Signed-off-by` trailer automatically (for example via `git commit -s`
> or a commit hook); **the certification is your act of submitting the contribution after personal
> review, not the mechanical addition of the trailer.**

So the repo's installed `prepare-commit-msg` hook stamping `Signed-off-by` onto a commit Claude
prepared is **expected behaviour, not a violation** — it applies the trailer from the developer's own
`git config`, and CONTRIBUTING ships that hook for exactly this purpose. Claude does not need to
strip it, work around it, or flag it each time. The earlier wording here ("it never certifies the
DCO … an automated system must not be the party that signs it") conflated the trailer with the
certification and made routine, sanctioned tooling read as a defect.

What does not change, because CONTRIBUTING § AI-Assisted Contributions states it plainly:

- **An automated system must not certify the DCO.** The certification is the human's act of reviewing
  the contribution and submitting it — in practice, reviewing the PR and merging it. It is not
  something Claude can perform, and a commit that has been stamped but not reviewed is not certified
  no matter what its trailer says.
- **Claude never hand-writes a `Signed-off-by` for a person.** The trailer comes from the developer's
  own git identity via the hook or `-s`, never typed into a commit message by Claude, and never for
  an identity that is not the committer's own.
- **Claude never presents unreviewed work as certified.** The hook running is not a signal that
  anyone has read the diff. Say what was verified and how, so the human signing has what they need to
  actually certify it.

`AGENTS.md` § Contribution & Security Policy already said this, which is what makes the old wording
here an outlier rather than a stricter-but-compatible rule. It states that the trailer is *"applied
by `.githooks/prepare-commit-msg` if you have installed the hooks"* and — in the same breath —
**"Leave the trailer in place"**, alongside the prohibition this section keeps: *"You must not
certify the DCO … Prepare the commit if asked; never be the party that certifies it."* Two canon
files agreed; `CLAUDE.md` was the one out of step.

The hook itself is worth having read once, because the guarantees are in it rather than in prose
about it (`.githooks/prepare-commit-msg`): it is gated behind `tap_consent_gate` so it does nothing
until a human deliberately installs it (`scripts/hooks-install`, `req-dev-localexec-consent`); it
reads `git config user.name` / `user.email` and can therefore only ever stamp the committer's OWN
identity; it exempts merge commits; and it refuses to stamp at all if the local-execution surface
has changed since the human approved it (`req-dev-localexec-reconsent`) — certification must not be
automated under code nobody has read.

Ruled 2026-09-22 by George, against the text of `CONTRIBUTING.md` (lines 139, 141, 163), `AGENTS.md`
(lines 251, 254), and the hook itself.
