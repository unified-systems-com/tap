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
| dogfood-git-serious | [dogfood-git-serious.md](dogfood-git-serious.md) | Operational-view framing; overlay prior-art survey; the `github.observation` layer defect; timestamp/coordinate semantics (tap#194) |

*(other sessions: add your row)*

## Read this first

The single most important finding of the day is in the bypass section of
`model-git-serious.md`: **a credential in the secret store labelled "Read-only GitHub PAT"
reports `admin: true` on every repository tested.** Any conclusion anyone reached today
about "what a read-only credential can see" that was measured with it is unsound. That
includes conclusions in the other write-ups here.

The description was not inherited from anywhere — a session typed it into the envelope and
never checked it. So the underlying failure is not a mislabelled secret but **an unverified
claim written into a durable artefact, indistinguishable to the next reader from a checked
one.** Every other tangle in this directory is a variation on that, including several
authored by the sessions writing these files. Read accordingly: prefer the lines that say
how a claim was established over the lines that state it confidently.

## The process lesson, which is worth more than any finding here

Corrections ran in **both** directions all day, and in every case the correction came from
reading the *evidence* rather than the *framing* — someone going back to what was actually
measured instead of to what the previous sentence asserted. Not one session caught its own
error. That is the argument for the multi-session shape, and it is the thing to carry
forward.

It is explicitly **not** a scoreboard, and these files should not be read as one. The
errors were not comparable quantities: some were local overclaims that the next reader
would have challenged anyway, while one was directional — an unverified "read-only" typed
into an envelope, which invalidated the central comparison of a day's experiments from the
first probe. Counting them together measures the wrong axis. What generalises is the
reading habit, not who used it more often.
