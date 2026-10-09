#!/usr/bin/env python3
"""The ONE derivation of "is this pull request authored by one of the maintainer's session accounts?"

Three checks enforce conventions that exist only to keep the maintainer's own agent sessions on
the open-a-pr procedure: the `[via <session>]` title (`scripts/check-pr-title`), the issue-link
trailer (`scripts/check-issue-link`) and the promote marker (`scripts/check-pr-opened-by`). An
outside contributor has never heard of a session, a promote or a qualified trailer, and must not
have their pull request go red on them (req-dev-multisession-session-author-scope). So all three
ask this module the same question, and it is answered here once.

What it does NOT govern: the DCO. Sign-off is a legal certification every contributor makes, so
`scripts/check-dco` keeps its own, narrower exemption (approved bots only, `scripts/pr_bot_identity.py`).

THE AUTHORITY, and why it mirrors the bot exemption. The only thing a contributor cannot set is
GitHub's view of who opened the pull request: `github.event.pull_request.user.{id,type}`. The
NUMERIC id plus the type is the identity, matched against the declared list
`tap/tap.pr-session-authors.json` (schema `tap/schemas/pr-session-authors.schema.json`). Titles,
commit author text and logins are never consulted: an outsider who types `[via x]` into a title,
or sets their git author to the maintainer's name, is still an outsider.

THREE ANSWERS, never two:
  SESSION  the authenticated author is a listed session account — the conventions apply.
  OUTSIDE  a well-formed authenticated identity that is not listed — the conventions do not apply.
  UNKNOWN  identity arguments were passed but the id is missing or malformed. Callers treat this
           as SESSION (enforce): a workflow wiring mistake must surface as a red, never quietly
           exempt everyone.
Where no identity is passed at all (a local promote gate, which only the maintainer runs), the
callers enforce; that path never reaches here.

Stdlib-only and host-runnable (`tap/host_syntax_floor.py`), like `scripts/pr_bot_identity.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SESSION_AUTHORS_PATH = Path(__file__).resolve().parent.parent / "tap" / "tap.pr-session-authors.json"
SESSION_TYPE = "User"

SESSION = "session"
OUTSIDE = "outside"
UNKNOWN = "unknown"


class SessionAuthorsError(Exception):
    """The session-author list is missing or malformed: a configuration error, never a silent pass."""


def load_session_authors(path: Path = SESSION_AUTHORS_PATH) -> dict[int, str]:
    """Return {numeric id: recorded login}, shape-checked (stdlib, fail-closed).

    The schema is the full contract and is enforced by test; this reader asserts the load-bearing
    shape (a non-empty `authors` list of objects with a positive integer `id`, type `User` and a
    login), so a malformed file can never silently exempt the maintainer's own sessions.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SessionAuthorsError(f"cannot read session-author list {path}: {exc}") from exc
    entries = data.get("authors") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise SessionAuthorsError(f"{path}: expected an object with a non-empty `authors` list")
    authors: dict[int, str] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SessionAuthorsError(f"{path}: authors[{i}] is not an object")
        ident, kind, login = entry.get("id"), entry.get("type"), entry.get("login")
        if not isinstance(ident, int) or isinstance(ident, bool) or ident < 1:
            raise SessionAuthorsError(f"{path}: authors[{i}].id must be a positive integer, got {ident!r}")
        if kind != SESSION_TYPE:
            raise SessionAuthorsError(f"{path}: authors[{i}].type must be {SESSION_TYPE!r}, got {kind!r}")
        if not isinstance(login, str) or not login:
            raise SessionAuthorsError(f"{path}: authors[{i}].login must be a non-empty string")
        if ident in authors:
            raise SessionAuthorsError(f"{path}: author id {ident} is listed twice")
        authors[ident] = login
    return authors


def classify(author_id: str, author_type: str, login: str, authors: dict[int, str]) -> tuple[str, str]:
    """Classify the AUTHENTICATED author as SESSION, OUTSIDE or UNKNOWN; return (verdict, reason)."""
    who = login or "<no login>"
    if not author_id:
        return UNKNOWN, f"pull request by {who}: no authenticated author id passed — session conventions enforced"
    try:
        ident = int(author_id)
    except ValueError:
        return (
            UNKNOWN,
            f"pull request by {who}: author id {author_id!r} is not an integer — session conventions enforced",
        )
    if ident < 1:
        return UNKNOWN, f"pull request by {who}: author id {ident} is not a GitHub id — session conventions enforced"
    if ident in authors and author_type == SESSION_TYPE:
        return SESSION, f"pull request by session account {authors[ident]} (id {ident}) — session conventions apply"
    return (
        OUTSIDE,
        f"pull request by {who} (id {ident}, type {author_type or '?'}) is not a session account — "
        "session conventions do not apply to outside contributors",
    )


def decide(argv: list[str], path: Path = SESSION_AUTHORS_PATH) -> tuple[str, str]:
    """Parse `--pr-author-id/--pr-author-type/--pr-author` from argv and classify.

    Returns (SESSION|OUTSIDE|UNKNOWN, reason). With no identity flags at all, returns SESSION:
    no pull request exists (a local promote), and only the maintainer runs that path.
    Raises SessionAuthorsError on a malformed list.
    """
    values = {"--pr-author-id": "", "--pr-author-type": "", "--pr-author": ""}
    for flag in values:
        if flag in argv:
            i = argv.index(flag)
            values[flag] = argv[i + 1].strip() if i + 1 < len(argv) else ""
    if not any(values.values()):
        return SESSION, "no pull-request identity (local run) — session conventions enforced"
    return classify(
        values["--pr-author-id"], values["--pr-author-type"], values["--pr-author"], load_session_authors(path)
    )


def main(argv: list[str]) -> int:
    try:
        verdict, reason = decide(argv)
    except SessionAuthorsError as exc:
        print(f"pr_session_identity: {exc}", file=sys.stderr)
        return 2
    print(f"{verdict}: {reason}")
    return 0 if verdict == OUTSIDE else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
