"""`scripts/pr-via`: the `[via <session>]` PR-title suffix, derived, never hand-typed.

A session worktree names itself from `.env.local`'s `COMPOSE_PROJECT_NAME`. A worktree nested
inside one (a side branch or a sub-agent's checkout) has no `.env.local`, and names the spawning
session followed by its own name, `<session>.<worktree>` (George, 2026-11-25). Each case runs the
real script inside a throwaway git repository.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pr-via"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _via(cwd: Path) -> str:
    out = subprocess.run(["bash", str(SCRIPT)], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _session(path: Path, label: str) -> Path:
    (path / ".env.local").write_text(f"COMPOSE_PROJECT_NAME=tap_{label}\n", encoding="utf-8")
    return path


def test_a_session_worktree_names_its_session(tmp_path: Path) -> None:
    root = _session(_repo(tmp_path / "hard-things"), "hard-things")
    assert _via(root) == "[via hard-things]"


def test_a_nested_worktree_names_the_spawning_session_then_itself(tmp_path: Path) -> None:
    session = _session(_repo(tmp_path / "hard-things"), "hard-things")
    nested = _repo(session / ".wtrepin")
    assert _via(nested) == "[via hard-things.wtrepin]"


def test_a_nested_worktree_already_named_for_its_session_is_not_doubled(tmp_path: Path) -> None:
    session = _session(_repo(tmp_path / "hard-things"), "hard-things")
    nested = _repo(session / "hard-things.pr-via")
    assert _via(nested) == "[via hard-things.pr-via]"


def test_a_worktree_with_no_session_above_it_falls_back_to_its_name(tmp_path: Path) -> None:
    alone = _repo(tmp_path / "scratch-checkout")
    assert _via(alone) == "[via scratch-checkout]"
