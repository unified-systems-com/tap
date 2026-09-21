# Claude Code in this repository

**[`AGENTS.md`](AGENTS.md) is the canonical agent guide — read it first.** It holds everything about
this repository: the rules, the specs to read, the commands, the workflow, the review contract. This
file holds only what is specific to driving TAP *with Claude Code*, because Codex, Cursor and Copilot
read AGENTS.md and none of them can use what is below.

## Skills

TAP ships 23 repo skills. Each is a packaged procedure for work this repo does often, and invoking
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

Claude prepares commits; it never certifies the DCO. See AGENTS.md § Contribution & Security Policy —
the `Signed-off-by` trailer is a named human's legal certification, and an automated system must not
be the party that signs it.
