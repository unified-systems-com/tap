#!/usr/bin/env python3
"""The ONE derivation of "is this pull request authored by an approved bot?" (the shared bot exemption).

Two contribution gates exempt bot pull requests: `scripts/check-issue-link` (a dependency bump
names no issue) and `scripts/check-dco` (an automated system must not certify the DCO — a
maintainer certifies at squash-merge instead). Both exemptions answer the SAME question, so it is
derived here once and never re-decided: a second copy is a second place to be wrong, and the way
this exemption goes wrong is silent.

WHY IT IS NOT A STRING MATCH — read this before "simplifying" it back.
`scripts/check-dco` used to exempt a commit whose git author matched
`(renovate|dependabot|github-actions)\\[bot\\]` (tap#335). Git author name and email are
contributor-controlled text: `git -c user.name='renovate[bot]' -c
user.email='renovate[bot]@users.noreply.github.com' commit` produced a commit that the DCO gate
waved through. The DCO is a certification that a HUMAN has the right to contribute the code, so a
bypass does not merely skip a CI step — it puts a claim in the record that a person certified work
they never saw. The same hole was found in `scripts/check-issue-link` by the Codex and Grok review
seats on tap PR# 328 and closed there; this module is that fix, shared.

THE AUTHORITY. The only thing a contributor cannot set is GitHub's own view of who opened the pull
request: `github.event.pull_request.user.{id,type}`, which the `dco` job passes through. The
NUMERIC account id is the identity — a login is a mutable, reassignable string (tap#342) — and the
type must be `Bot`. The id must appear in the declared allowlist `tap/tap.pr-bots.json` (schema
`tap/schemas/pr-bots.schema.json`), every entry of which was verified against GitHub's
`/users/<login>` response on the date it records. The login rides along for diagnostics only.

WHERE IT CANNOT DECIDE. Nothing outside a pull-request event has an authenticated author: a local
promote gate has no PR yet, and a `merge_group` event carries no `pull_request.user`. Both pass
nothing here, and nothing is exempt there — fail-closed, deliberately, in both directions. That is
not a weakened local lane: since the `dco` job is required through the `gate` aggregator
(tap#353), the authoritative verdict is the server's, and the local lane is strictly stricter than
it. The practical consequence, named rather than discovered: an unsigned bot commit carried into a
HUMAN's branch is now a red, because the human's PR is not the bot's PR. Bot changes land on the
bot's own pull request.

Stdlib-only and host-runnable: `scripts/check-dco` is bash and invokes this file as a CLI under
bare `python3` (so it obeys `tap/host_syntax_floor.py`), while `scripts/check-issue-link` imports
it. Note that check-dco needs no interpreter at all on the path where nothing is exempt — the
python3 call happens only when CI passes an identity.

Spec: specs/spec-cicd-hardening.md (req-cicd-dco-signoff, req-cicd-issue-link).

Usage (CLI):
    scripts/pr_bot_identity.py --pr-author-id <n> --pr-author-type <Bot|User> --pr-author <login>

    Prints a one-line reason and exits: 0 exempt, 1 not exempt, 2 the allowlist is malformed
    (a configuration error is never a silent pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: The declared allowlist of approved pull-request bot IDENTITIES (numeric id + type Bot), read
#: relative to this file so an ad-hoc run and CI consult the same file. Commit author strings and
#: logins are never consulted for authorization.
APPROVED_BOTS_PATH = Path(__file__).resolve().parent.parent / "tap" / "tap.pr-bots.json"
#: The only account type that can be exempt.
BOT_TYPE = "Bot"


class AllowlistError(Exception):
    """The approved-bots file is missing or malformed: a configuration error, never a silent pass."""


def load_approved_bots(path: Path = APPROVED_BOTS_PATH) -> dict[int, str]:
    """Return {numeric id: recorded login} from the allowlist, shape-checked (stdlib, fail-closed).

    The schema (`tap/schemas/pr-bots.schema.json`) is the full contract and is enforced by test;
    this reader asserts the load-bearing shape — an object with an `approved` list of objects
    carrying a positive integer `id`, `type == "Bot"` and a string `login` — so a malformed file
    can never widen the exemption.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AllowlistError(f"cannot read approved-bots allowlist {path}: {exc}") from exc
    entries = data.get("approved") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise AllowlistError(f"{path}: expected an object with an `approved` list")
    approved: dict[int, str] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AllowlistError(f"{path}: approved[{i}] is not an object")
        ident, kind, login = entry.get("id"), entry.get("type"), entry.get("login")
        if not isinstance(ident, int) or isinstance(ident, bool) or ident < 1:
            raise AllowlistError(f"{path}: approved[{i}].id must be a positive integer, got {ident!r}")
        if kind != BOT_TYPE:
            raise AllowlistError(f"{path}: approved[{i}].type must be {BOT_TYPE!r}, got {kind!r}")
        if not isinstance(login, str) or not login:
            raise AllowlistError(f"{path}: approved[{i}].login must be a non-empty string")
        if ident in approved:
            raise AllowlistError(f"{path}: approved id {ident} is listed twice")
        approved[ident] = login
    return approved


def exempt_author(author_id: str, author_type: str, login: str, approved: dict[int, str]) -> tuple[bool, str]:
    """Decide the exemption from the AUTHENTICATED identity; return (exempt, one-line reason).

    Authorization is `id in approved and type == "Bot"`. The login only shapes the message —
    a matching login with the wrong id, or a matching id with the wrong type, is not exempt.
    """
    who = login or "<no login>"
    if not author_id:
        return False, f"pull request by {who}: no authenticated author id passed — not a bot exemption"
    try:
        ident = int(author_id)
    except ValueError:
        return False, f"pull request by {who}: author id {author_id!r} is not an integer — not a bot exemption"
    if ident not in approved:
        return False, f"pull request by {who} (id {ident}, type {author_type or '?'}) is not an approved bot identity"
    if author_type != BOT_TYPE:
        return False, f"pull request by {who}: id {ident} is approved but type is {author_type!r}, not {BOT_TYPE!r}"
    recorded = approved[ident]
    note = "" if login == recorded else f" (login now {who!r}; approved as {recorded!r})"
    return (
        True,
        f"pull request authored by approved bot {recorded} (id {ident}){note}; a maintainer certifies it at merge.",
    )


def decide(argv: list[str]) -> tuple[int, str]:
    """CLI decision: (exit code, one-line reason). 0 exempt, 1 not exempt, 2 malformed allowlist."""
    identity = {"--pr-author": "", "--pr-author-id": "", "--pr-author-type": ""}
    args = list(argv)
    for flag in list(identity):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                return 2, f"pr_bot_identity: {flag} needs a value"
            identity[flag] = args[i + 1].strip()
            del args[i : i + 2]
    if args:
        return 2, f"pr_bot_identity: unexpected argument(s): {' '.join(args)}"
    try:
        approved = load_approved_bots()
    except AllowlistError as exc:
        return 2, f"pr_bot_identity: {exc}"
    exempt, reason = exempt_author(
        identity["--pr-author-id"], identity["--pr-author-type"], identity["--pr-author"], approved
    )
    return (0 if exempt else 1), reason


def main(argv: list[str]) -> int:
    code, reason = decide(argv)
    print(reason, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
