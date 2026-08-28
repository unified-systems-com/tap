# Day One Hairball

Working notes from 2026-08-27, written at end of day so tomorrow's untangling starts from
a record rather than from reconstruction. **Not a spec, not a doc-system doc** — a set of
first-person session write-ups, deliberately unreconciled. Where two accounts disagree,
that disagreement is information; do not smooth it away before reading both.

## Convention

One file per session, named for the session: `<session-name>.md`. Say what you did, what
you believe is true, what you are *unsure* is true, and what you left running or half-done.
Flag anything you asserted during the day and later found to be wrong — a corrected claim
that nobody records will be re-trusted tomorrow.

## Index

| Session | File | Scope |
| --- | --- | --- |
| model-git-serious | [model-git-serious.md](model-git-serious.md) | Domain-article layer + guard; the bypass_actors investigation |
| bypass-git-serious | [bypass-git-serious.md](bypass-git-serious.md) | Ruleset version history + the 12-day bypass window; github_ruleset collection; org security floor + plugin-repo parity |

| git-serious | [git-serious.md](git-serious.md) | The original session: problem framing, vocabulary corpus, org scope + GraphQL, the GitHub App |

*(other sessions: add your row)*

## Read this first

The single most important finding of the day is in the bypass section of
`model-git-serious.md`: **a credential in the secret store labelled "Read-only GitHub PAT"
reports `admin: true` on every repository tested.** Any conclusion anyone reached today
about "what a read-only credential can see" that was measured with it is unsound. That
includes conclusions in the other write-ups here.
