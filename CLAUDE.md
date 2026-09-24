# Claude Code in this repository

**[`AGENTS.md`](AGENTS.md) is the canonical agent guide — read it first.** It holds everything about
this repository: the rules, the specs to read, the commands, the workflow, the review contract. This
file holds only what is specific to driving TAP *with Claude Code*, because Codex, Cursor and Copilot
read AGENTS.md and none of them can use what is below.

## Skills

TAP ships 26 repo skills. Each is a packaged procedure for work this repo does often, and invoking
one is cheaper and more correct than re-deriving the steps. Canonical location is `<app>/skills/`;
`wire-skills` symlinks them into `.claude/skills/` at spawn (only `get-started` is committed there,
so the rest are per-clone).

| When you are… | Skill |
| --- | --- |
| Adding a model, edge, page, panel, or collector | `add-model`, `add-edge`, `add-page`, `add-panel`, `build-collector` |
| Entering a domain TAP has not modelled | `build-domain-vocabulary` |
| Creating or specifying a plugin | `new-plugin`, `create-plugin-spec`, `unified-systems-plugin-conventions` |
| Hitting a Gryphon defect — wrong rows, dropped clause, crash | `gryphon-defect-response` — run it FIRST; it routes to the two below |
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
- **Claude never hand-writes a `Signed-off-by` for a person.** The trailer comes from the hook or
  `git commit -s`, never typed into a commit message by Claude. And a trailer naming someone other
  than the committer is still worth raising: the hook cannot produce one, so its presence means
  something else did.
- **Claude never presents unreviewed work as certified.** The hook running is not a signal that
  anyone has read the diff. Say what was verified and how, so the human signing has what they need to
  actually certify it.

`AGENTS.md` § Contribution & Security Policy already said this, which is what makes the old wording
here an outlier rather than a stricter-but-compatible rule. It states that the trailer is *"applied
by `.githooks/prepare-commit-msg` if you have installed the hooks"* and — in the same breath —
**"Leave the trailer in place"**, alongside the prohibition this section keeps: *"You must not
certify the DCO … Prepare the commit if asked; never be the party that certifies it."* Two canon
files agreed; `CLAUDE.md` was the one out of step.

The hook itself is worth having read once (`.githooks/prepare-commit-msg`): it is gated behind
`tap_consent_gate`, so it does nothing until a human deliberately installs it
(`scripts/hooks-install`, `req-dev-localexec-consent`); it exempts merge commits; and it refuses to
stamp at all if the local-execution surface has changed since the human approved it
(`req-dev-localexec-reconsent`) — certification must not be automated under code nobody has read.

**What the hook does NOT give you, stated because an earlier draft of this section got it wrong.**
It stamps whatever `git config user.name` / `user.email` say. Those are locally mutable and
unauthenticated — they can name anyone. So the trailer is not evidence of identity, and this
section must never be read as licence to suppress a warning about a misattributed one.

That is not a weakness in the argument; it *is* the argument. Precisely because the trailer is
mechanical and proves nothing on its own, the certification cannot be the trailer — it has to be the
human's act of reviewing and submitting, which is what `CONTRIBUTING.md` says and what the DCO has
always meant. A trailer that could authenticate anybody would make the review redundant; one that
cannot is why the review is the whole thing.

Ruled 2026-09-22 by George against the text of `CONTRIBUTING.md` (lines 139, 141, 163), `AGENTS.md`
(lines 251, 254), and the hook itself.

**Do not take that sentence as the authority.** A "Ruled by <name>" line living in the agent prompt
is an assertion a later session cannot check, and an earlier draft tried to fix that by citing the
pull request carrying this very change — which was circular, since it claimed an approval that had
not happened yet. The citations above are the authority: they name files and line numbers in canon
that anyone can open. If this section and those files ever disagree, **the files win and this
section is the bug** — the same rule the skills obey against their specs.
