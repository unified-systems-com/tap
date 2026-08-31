# Sourced helper — the local-execution consent check (req-dev-localexec-reconsent).
#
# Every hook in this directory sources this and calls tap_consent_gate before doing
# anything. It answers one question: is the code about to run on this machine still
# the code the human agreed to run?
#
# THE ASYMMETRY THAT MAKES THIS WORK: the agreed-to hash lives in LOCAL GIT CONFIG
# (tap.hooksConsentHash), not in the repository. A malicious commit can change the
# hooks, but it cannot change what you consented to — there is nothing in-repo to
# forge. So a repo-side change can only ever produce a MISMATCH.
#
# WHAT THIS DOES NOT DO, stated plainly (req-sec-honest-risk): a local self-check is
# defeatable by editing the checker, because the edited copy is what runs next. That
# regress does not terminate locally and no hash chain fixes it. It terminates
# OUT OF BAND — every path in the hashed set (.githooks/, .claude/, scripts/hooks/)
# is code-owned in .github/CODEOWNERS, and the coverage guard that asserts so runs in
# CI, off this machine. In-repo loud, out-of-band block; the same argument
# docs/doc-dev-validation-meta-integrity.md makes for the guard system itself.
#
# Spec: specs/spec-dev-local-execution.md

# Deterministic hash over path+content of everything here that can execute locally.
# git hash-object reads the WORKING TREE, not the index — what executes, not what is
# staged — and needs no interpreter beyond git itself (there is no .venv in a session
# worktree; see .githooks/precommit_secret_scan.py for the same constraint).
# TAP-KNOWN-DUPE(localexec-consent-hash): scripts/hooks-install computes this same
# digest with its own inline copy. It CANNOT source this file: the installer runs
# automatically from spawn-session.sh, so sourcing the surface it is about to ask the
# user to approve would execute that surface pre-consent — top-level commands in this
# file would run during an ordinary spawn even when the user declines. That is the
# defect this boundary exists to prevent, so the two copies must stay byte-equivalent
# in BEHAVIOUR and are checked against each other by tap/guards/localexec_consent.py.
#
# Covers mode as well as content: `git hash-object` digests the blob only, so without
# the mode byte a commit could clear the executable bit on pre-commit — silently
# disabling the secret scan — without moving the hash. Symlinks are included for the
# same reason (a symlinked hook still executes).
tap_localexec_hash() {
    {
        find .githooks scripts/hooks \( -type f -o -type l \) 2>/dev/null
        [ -e .claude/settings.json ] && echo .claude/settings.json
        [ -e scripts/hooks-install ] && echo scripts/hooks-install
    } | LC_ALL=C sort | while IFS= read -r f; do
        if [ -L "$f" ]; then _m=120000
        elif [ -x "$f" ]; then _m=100755
        else _m=100644
        fi
        printf '%s %s %s\n' "$_m" "$(git hash-object "$f" 2>/dev/null)" "$f"
    done | git hash-object --stdin
}

# Prints the alarm and returns 1 on mismatch; returns 0 when consent is current or
# when hooks were never installed through scripts/hooks-install (nothing was agreed,
# so there is nothing to have changed — hooks-install is what starts the contract).
tap_consent_gate() {
    _agreed="$(git config --get tap.hooksConsentHash 2>/dev/null || true)"
    _live="$(tap_localexec_hash)"

    if [ -z "$_agreed" ]; then
        # FAIL CLOSED. Hooks are running (this file only executes when they are), so
        # something armed them without recording consent — the pre-2026-08-28 silent
        # `git config core.hooksPath .githooks` in spawn-session.sh. Treating "no record"
        # as "nothing to check" would grandfather exactly the population this exists to
        # protect: every clone armed under the old behaviour, permanently unalarmed.
        cat >&2 <<'MIGRATE'

################################################################################
##   HOOKS ARE ARMED ON THIS CLONE, BUT YOU NEVER APPROVED THEM               ##
################################################################################

Something set core.hooksPath without recording your consent — almost certainly a
spawn from before 2026-08-28, which armed hooks silently.

The hooks below are running on your machine right now. They run as you, on
ordinary git commands, with your full access.

  Read them:     .githooks/
  Then approve:  scripts/hooks-install
  Or turn off:   scripts/hooks-install --uninstall

Until you choose, hooks that CERTIFY on your behalf stay off (sign with
`git commit -s`). Hooks that PROTECT you keep running.
################################################################################

MIGRATE
        return 1
    fi

    [ "$_live" != "$_agreed" ] || return 0

    cat >&2 <<'BANNER'

################################################################################
##                                                                            ##
##   STOP — THE CODE THIS REPO RUNS ON YOUR MACHINE HAS CHANGED               ##
##                                                                            ##
################################################################################

You approved a specific version of this repository's hooks. What is on disk now
is NOT that version.

This should almost never happen. These files are designed to sit still: the
config is a pointer, the logic is a small script, and both are code-owned. A
change here is either something you did on purpose, or something that arrived in
a commit you have not read.

WHAT THESE FILES CAN DO IF YOU ACCEPT THEM
  They run automatically, as you, on ordinary git commands — commit, checkout,
  merge, rebase. They are shell and Python, not a sandbox. Whatever your account
  can do, they can do: read any file you can read (SSH keys, cloud credentials,
  browser profiles), reach the network, and alter what your commits contain. A
  hostile version of these files would not need to announce itself.

BANNER
    printf '  approved: %s\n  on disk:  %s\n\n' "$_agreed" "$_live" >&2

    _changed="$(git diff --name-only -- .githooks .claude/settings.json scripts/hooks 2>/dev/null)"
    if [ -n "$_changed" ]; then
        printf 'UNCOMMITTED CHANGES IN YOUR WORKING TREE\n%s\n\n' \
            "$(printf '%s\n' "$_changed" | sed 's/^/  /')" >&2
    fi

    cat >&2 <<'BANNER'
WHAT TO DO
  1. Look at what actually changed:
         git log -p --  .githooks .claude/settings.json scripts/hooks
     Read the diff. If it arrived in someone else's commit, read who wrote it and
     which PR reviewed it.
  2. If you are satisfied, re-approve deliberately:
         scripts/hooks-install
  3. If you are not, turn them off and lose nothing that matters:
         scripts/hooks-install --uninstall
     CI re-checks sign-off and secret leaks either way.

Until you choose, hooks that CERTIFY on your behalf stay off (your DCO sign-off
will not be applied automatically — use `git commit -s`). Hooks that PROTECT you
keep running, because switching those off is what an attacker would want.
################################################################################

BANNER
    return 1
}
