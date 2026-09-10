"""Does a PR's AI review carry findings nobody answered?

Host-runnable, stdlib-only leaf (the ``tap/secret_naming.py`` shape): this must
answer on a bare CI runner and on a developer's laptop, before any virtualenv
exists, so it imports nothing outside the standard library and knows nothing about
Django.

**Why the decision lives here and not in the shell that fetches it.** The fetching
is `gh api` + `jq`; the DECIDING is this module. Keeping the verdict in shell put it
somewhere the test suite could not reach — the container the lanes run in has no
`jq`, so shell-level tests skip in the one place they are executed, which is the
"evicted plugin tests silently dead" shape. Splitting it means the rule that
actually blocks a merge is covered by tests that run everywhere (tap#390; the same
argument as tap#389 for the tier classifier).

The rule, and why each part of it:

* A FINDING is a line matching ``## high``, ``## medium``, ``merge-blocker``, or
  ``SEAT ABSENT``. The first three are the unified reviewer's own severity and
  verdict vocabulary. ``SEAT ABSENT`` means a seat produced *no* verdict (rate
  limit, outage) — counted as unanswered by construction, because a missing verdict
  read as a clean one is precisely the failure this exists to prevent.
* ANSWERED means a later non-bot comment exists on the PR. The triage discipline
  (req-dev-multisession-push-workflow) already requires a written dismissal, so the
  artefact exists whenever the work was done. It deliberately does NOT try to match
  an answer to a specific finding: that is a text-similarity guess, and a wrong
  guess in the permissive direction is the bug.
* The unified reviewer EDITS ITS COMMENT IN PLACE on rerun, so an answer must
  postdate the newest reviewer artefact. If the review changed after the reply, the
  reply no longer covers it and the gate re-blocks. Intended, not accidental.
* NO REVIEW AT ALL is UNKNOWN, and unknown blocks. Absence of evidence is never
  evidence of absence (the three-state rule).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

#: A reviewer artefact matching any of these is a finding that wants an answer.
#:
#: The grouping is explicit and load-bearing. `^` binds to the alternative it sits in,
#: not to the whole pattern, so `^## (high|medium)|merge-blocker|...` means "a line
#: STARTING with `## high`/`## medium`" OR "`merge-blocker` ANYWHERE" — which is the
#: intent, but only by accident of precedence. Written that way the next person to add
#: a fourth alternative inherits a trap, in the one expression that decides whether a
#: merge is blocked. `(?:...)` states it instead (SonarCloud S5850).
#:
#: The two halves are deliberately different: the severity headings are markdown
#: headings and must be at the start of a line, while `merge-blocker` and
#: `SEAT ABSENT` appear mid-sentence in a verdict line or inside a blockquote.
FINDING_RE = re.compile(r"(?:^## (?:high|medium))|merge-blocker|SEAT ABSENT", re.MULTILINE)

#: GitHub marks bot logins with this suffix; the unified reviewer also carries a marker.
_BOT_SUFFIX = "[bot]"
_UNIFIED_MARKER = "<!-- unified-ai-review -->"

EXIT_OK = 0
EXIT_UNANSWERED = 3


def _login(item: dict[str, Any]) -> str:
    return str((item.get("user") or {}).get("login") or "")


def _is_bot(item: dict[str, Any]) -> bool:
    return _login(item).endswith(_BOT_SUFFIX)


def reviewer_bodies(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Every (timestamp, body) a finding can hide in: review summaries + bot comments."""
    out: list[tuple[str, str]] = []
    for r in reviews:
        body = str(r.get("body") or "")
        if body:
            out.append((str(r.get("submitted_at") or ""), body))
    for c in comments:
        body = str(c.get("body") or "")
        if not body:
            continue
        if _is_bot(c) or _UNIFIED_MARKER in body:
            out.append((str(c.get("updated_at") or c.get("created_at") or ""), body))
    return out


def findings(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> list[str]:
    """The finding lines, deduplicated, in the order first seen."""
    seen: set[str] = set()
    found: list[str] = []
    for _at, body in reviewer_bodies(reviews, comments):
        for line in body.splitlines():
            if FINDING_RE.search(line) and line.strip() not in seen:
                seen.add(line.strip())
                found.append(line.strip())
    return found


def newest_reviewer_at(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> str:
    """The newest timestamp on any reviewer artefact — used only to detect 'a review exists'."""
    return max((at for at, _b in reviewer_bodies(reviews, comments)), default="")


def newest_finding_at(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> str:
    """The newest timestamp on an artefact that actually CARRIES a finding.

    An answer must postdate this, not the newest artefact of any kind. The difference
    is not academic: Sonar and Codacy post clean "quality gate passed" comments long
    after a review, and measuring against those would silently un-answer a finding
    somebody had already addressed — a gate that re-blocks for no reason is a gate
    people learn to override.
    """
    return max((at for at, body in reviewer_bodies(reviews, comments) if FINDING_RE.search(body)), default="")


def has_answer_after(comments: list[dict[str, Any]], at: str) -> bool:
    """A non-bot comment created after *at* — the written answer the discipline requires."""
    return any(not _is_bot(c) and str(c.get("created_at") or "") > at for c in comments)


def verdict(reviews: list[dict[str, Any]], comments: list[dict[str, Any]]) -> tuple[int, list[str], str]:
    """Return (exit_code, finding_lines, message)."""
    if not newest_reviewer_at(reviews, comments):
        return EXIT_UNANSWERED, [], "no AI review has arrived yet — the verdict is UNKNOWN, not clean."
    found = findings(reviews, comments)
    if found and not has_answer_after(comments, newest_finding_at(reviews, comments)):
        return EXIT_UNANSWERED, found, "unanswered AI-review findings — answer each on the PR before merging:"
    return EXIT_OK, [], ""


def _load(path: str) -> list[dict[str, Any]]:
    """Read one JSON array, validated AT THE SINK.

    The two paths come from argparse and are written by `scripts/pr-review-triage`
    into a `mktemp -d`, so they are not user input in the web sense. This is still
    the one place a caller-supplied string becomes a file read, so it is checked
    here: a real, existing regular file whose name ends in `.json`, resolved before
    it is opened. Anything else is refused by name rather than read — the same
    sink-validation shape the lane runner uses for its argv.
    """
    candidate = Path(path).resolve()
    if candidate.suffix != ".json":
        raise ValueError(f"refusing to read a non-JSON path: {path!r}")
    if not candidate.is_file():
        raise ValueError(f"not a readable file: {path!r}")
    with candidate.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--pr", default="?", help="PR number, for the message only")
    parser.add_argument("--reviews", required=True, help="JSON file: the PR's reviews array")
    parser.add_argument("--comments", required=True, help="JSON file: the PR's issue-comments array")
    args = parser.parse_args(argv)

    code, found, message = verdict(_load(args.reviews), _load(args.comments))
    if code != EXIT_OK:
        print(f"PR #{args.pr}: {message}", file=sys.stderr)
        for line in found:
            print(f"  {line}", file=sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
