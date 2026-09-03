"""A throwaway git repository for behavioural tests of the host-runnable commit checks.

Registered under the fixture name `repo` (import `throwaway_repo` to register it; the name differs
from the fixture's so a test parameter called `repo` never shadows a module-level name).

Shared by `test_check_dco.py` and `test_check_issue_link.py` (and any later commit-trailer gate):
both run the REAL shipped script against a fresh repository, never the session repo, so the
assertions cover the artifact end to end, exit code included. One copy of the fixture, so the
two suites cannot drift apart in how they build history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

AUTHOR_NAME = "Ada Lovelace"
AUTHOR_EMAIL = "ada@example.com"

#: The environment every git call and every script run gets: a fixed identity, and NO access to
#: the developer's own git config or hooks (core.hooksPath=.githooks auto-stamps a trailer, and an
#: "unsigned" commit must actually be unsigned for the negative cases to mean anything).
def _env(repo: Path, **extra: str) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(repo),
        "GIT_AUTHOR_NAME": AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        **extra,
    }


def git(repo: Path, *args: str, **env: str) -> str:
    """Run a git command in `repo`, returning stdout (raises on failure)."""
    result = subprocess.run(  # noqa: S603 # nosec B603 - fixed argv (`git` + the test's literal arguments), test fixture
        ["git", *args], cwd=repo, env=_env(repo, **env), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture(name="repo")
def throwaway_repo(tmp_path: Path) -> Path:
    """A throwaway repo with one base commit; the tag `base` is the checks' base ref."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", AUTHOR_NAME)
    git(tmp_path, "config", "user.email", AUTHOR_EMAIL)
    (tmp_path / "f.txt").write_text("base\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base", "--no-verify")
    git(tmp_path, "tag", "base")
    return tmp_path


def commit(repo: Path, message: str, *, signed: bool = False, author: str | None = None) -> str:
    """Add a commit; returns its full sha. `author` (`Name <email>`) overrides the author identity."""
    (repo / "f.txt").write_text(message)
    git(repo, "add", "-A")
    args = ["commit", "-q", "-m", message, "--no-verify"]
    if signed:
        args.append("-s")
    env: dict[str, str] = {}
    if author is not None:
        name, _, email = author.partition(" <")
        env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email.rstrip(">")}
    git(repo, *args, **env)
    return git(repo, "rev-parse", "HEAD")


def run_script(repo: Path, argv: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    """Run one of the host-runnable checks against the throwaway repo, base ref `base`."""
    # check=False on purpose: the exit code IS the verdict under test.
    return subprocess.run(  # noqa: S603 # nosec B603 - fixed argv (the shipped script + literal args), test fixture
        [*argv, "base"], cwd=repo, env=_env(repo, **env), capture_output=True, text=True, check=False
    )
