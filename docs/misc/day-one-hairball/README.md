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
| build-git-serious | [build-git-serious.md](build-git-serious.md) | The vocabulary becomes types: six `github_core` models + eleven new edges, first self-collection, the credential seam rebuilt mid-flight; bypass observability as a transport property |

*(other sessions: add your row)*

## Read this first

The single most important finding of the day is that **no measurement taken with the
`github_core` collector PAT can support a claim about what a *read-only* credential sees** —
and the reason is subtler than the one this README carried for most of the night.

The first version said the token "reports `admin: true` on every repository tested", implying
it is over-privileged. **That inference was wrong**, corrected by cleanup-git-serious and
verified here: the `permissions` block on `GET /repos/{o}/{r}` reports **the authenticated
user's role**, not the token's granted scopes, so it reads `admin: true` for any user-attached
token whose holder is an admin. The token is in fact refused inside its own declared scope —
`403 Resource not accessible by personal access token` on `/actions/secrets` and
`/actions/variables`, while `/actions/runners`, `/rulesets` and `/collaborators` return 200.

What survives is stronger and more useful: **a user-attached PAT can never demonstrate that a
read-level grant suffices, because some surfaces answer to the token's grants and others to
the holder's inherited role.** Only a GitHub App — which has no role to inherit — can validate
a least-privilege claim. Every "read-only credential" conclusion reached today rests on a
credential that cannot support one.

Two related corrections belong beside it. The envelope's `data.repos` is a **collection
filter, not a security boundary** — it never constrained what the credential could reach, though
its description reads like a scope statement. And the envelope's "read-only" description was
typed by hand and never verified, so the underlying failure is **an unverified claim written
into a durable artefact, indistinguishable to the next reader from a checked one.** Every other tangle in this directory is a variation on that, including several
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
