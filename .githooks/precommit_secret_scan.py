"""Staged-content secret scan for `.githooks/pre-commit` — `req-tap-cares-secrets-precommit`.

Refuses a commit that would put credential material into the repository. Runs against
**staged blobs** (`git show :<path>`), not the working tree, so it sees exactly what is
about to be committed — including the case where a file was staged and then edited.

**Stdlib only, on purpose.** Dependencies live in the container; there is no `.venv` in
a session worktree, so anything importing a third-party package would make the hook fail
or silently skip on a normal developer machine. :mod:`tap.credential_patterns` and
:mod:`tap.secret_naming` are Django-free and dependency-free precisely so this hook can
use them directly; that floor is machine-checked by
``test_stage0_credential_machinery_is_stdlib_only``, which walks this file's imports.

Two of the three leak checks run here:

1. **Staged `*.secret.json`** — the filename rule, which needs no parsing.
2. **Credential shapes** — `tap.credential_patterns`, the full pattern set.

The third — the *envelope-content* scan (`tap.runtime_secrets.scan_paths_for_secret_leaks`,
which catches a secret renamed to dodge the suffix) — is deliberately NOT run here: it
imports `tap.jsonfiles`, which imports `jsonschema`, which is not present on the host.
It remains enforced by the `secret-leak` CI guard. This omission is stated rather than
hidden, because a hook that quietly covers less than it appears to is the failure this
whole requirement exists to fix.

This hook is bypassable (`git commit --no-verify`) and is therefore NOT the enforcement
boundary — the CI guards are. It is the cheap early catch that keeps a credential out of
a commit object in the first place, which matters because history rewriting is the only
remedy once one lands.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tap.credential_patterns import format_matches, scan_text  # noqa: E402  (path set above)
from tap.secret_naming import SECRET_EXAMPLE_SUFFIX, SECRET_SUFFIX  # noqa: E402  (path set above)


def _staged_paths() -> list[str]:
    """Repo-relative paths staged for commit (added / copied / modified)."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def _staged_blob(path: str) -> str | None:
    """The staged content of ``path``, or None if it is binary/unreadable."""
    result = subprocess.run(["git", "show", f":{path}"], capture_output=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary blob — out of scope for this layer


def main() -> int:
    """Scan staged content; return 1 (blocking the commit) on any finding."""
    problems: list[str] = []

    for path in _staged_paths():
        name = Path(path).name
        if name.endswith(SECRET_SUFFIX) and not name.endswith(SECRET_EXAMPLE_SUFFIX):
            problems.append(f"  {path} — staged *.secret.json (a real secret file)")
            continue
        blob = _staged_blob(path)
        if blob is None:
            continue
        matches = scan_text(blob, path=path)
        if matches:
            problems.append(format_matches(matches))

    if not problems:
        return 0

    sys.stderr.write(
        "\nCOMMIT REFUSED — credential material found in staged content:\n\n"
        + "\n".join(problems)
        + "\n\nTreat any real match as COMPROMISED: rotate it first, then unstage the file.\n"
        "Secrets belong only in the mounted *.secret.json store (off-grid, gitignored).\n"
        "A doc example or test vector that must show a real-looking token may carry the\n"
        "`TAP-CREDENTIAL-OK` marker on the same line.\n\n"
        "This hook is a convenience, not the authority — the CI guards are. Bypassing it\n"
        "with --no-verify only defers the failure to the promote gate.\n"
        "(spec-tap-cares-secrets.md req-tap-cares-secrets-precommit)\n\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
