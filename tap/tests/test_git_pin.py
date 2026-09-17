"""tap.git_pin — does a git source's tag still name the commit it pins? (tap#512, epic tap#493).

No test here touches the network: every forge answer comes through the ``runner`` seam, fed
real ``git ls-remote`` output shapes captured 2026-09-17 (a lightweight tag prints one line;
an annotated tag prints the tag object and, only when asked for explicitly, the peeled
``^{}`` commit line).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tap.git_pin import (
    TAG_MATCHES,
    TAG_MISSING,
    TAG_MOVED,
    TAG_NOT_OBSERVABLE,
    TagCheck,
    check_pin,
    check_profiles,
    is_commit_sha,
    peeled_commit,
    resolve_tag,
)

URL = "https://forge.example/org/tap-plugin-widget"
COMMIT = "3356301e676094523943f2bbb055be501a6b42d6"
TAG_OBJECT = "04c663dfb76c036fff7b616dae4439aa3d093f01"
OTHER = "7f08d0780d7468590507df2a5562fe730d76e8c8"

LIGHTWEIGHT = f"{COMMIT}\trefs/tags/v1.0.0\n"
ANNOTATED = f"{TAG_OBJECT}\trefs/tags/v1.0.0\n{COMMIT}\trefs/tags/v1.0.0^{{}}\n"


class _Answer:
    """A stand-in ``git ls-remote``: records each call, returns a canned result."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, "env": env, "timeout": timeout})
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


def _answer(stdout: str = "", returncode: int = 0, stderr: str = "") -> _Answer:
    return _Answer(stdout, returncode, stderr)


class TestPeeling:
    def test_lightweight_tag_is_its_own_commit(self) -> None:
        assert peeled_commit(LIGHTWEIGHT, "v1.0.0") == COMMIT

    def test_annotated_tag_resolves_to_the_peeled_commit_not_the_tag_object(self) -> None:
        assert peeled_commit(ANNOTATED, "v1.0.0") == COMMIT

    def test_a_prefix_sibling_tag_is_not_mistaken_for_the_tag(self) -> None:
        output = f"{OTHER}\trefs/tags/v1.0.0-rc1\n{OTHER}\trefs/tags/v1.0.0-rc1^{{}}\n"
        assert peeled_commit(output, "v1.0.0") is None

    def test_both_patterns_are_requested_so_git_prints_the_peeled_line(self) -> None:
        runner = _answer(ANNOTATED)
        resolve_tag(URL, "v1.0.0", runner=runner)
        args = runner.calls[0]["args"]
        assert args[-2:] == ["refs/tags/v1.0.0", "refs/tags/v1.0.0^{}"]


@pytest.mark.spec("req-boot-bootstrap-install-commit-pin")
class TestCheckPin:
    @pytest.mark.parametrize("output", [LIGHTWEIGHT, ANNOTATED], ids=["lightweight", "annotated"])
    def test_matches(self, output: str) -> None:
        assert check_pin(URL, "v1.0.0", COMMIT, runner=_answer(output)) == TagCheck(TAG_MATCHES, observed=COMMIT)

    def test_moved(self) -> None:
        result = check_pin(URL, "v1.0.0", OTHER, runner=_answer(ANNOTATED))
        assert (result.state, result.observed) == (TAG_MOVED, COMMIT)

    def test_missing(self) -> None:
        assert check_pin(URL, "v1.0.0", COMMIT, runner=_answer("")).state == TAG_MISSING

    def test_a_forge_error_is_not_observable_never_missing(self) -> None:
        result = check_pin(URL, "v1.0.0", COMMIT, runner=_answer("", 128, "fatal: could not resolve host"))
        assert result.state == TAG_NOT_OBSERVABLE
        assert "could not resolve host" in result.detail

    def test_a_timeout_is_not_observable(self) -> None:
        def runner(args: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(args, timeout)

        assert check_pin(URL, "v1.0.0", COMMIT, runner=runner).state == TAG_NOT_OBSERVABLE

    def test_no_git_binary_is_not_observable(self) -> None:
        def runner(args: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("git")

        assert check_pin(URL, "v1.0.0", COMMIT, runner=runner).state == TAG_NOT_OBSERVABLE

    def test_a_sha_rev_needs_no_forge(self) -> None:
        runner = _answer("should not be called")
        assert check_pin(URL, COMMIT, COMMIT, runner=runner).state == TAG_MATCHES
        assert check_pin(URL, OTHER, COMMIT, runner=runner).state == TAG_MOVED
        assert runner.calls == []

    def test_prompts_are_forbidden_and_credentials_ride_askpass_not_argv(self) -> None:
        runner = _answer(LIGHTWEIGHT)
        check_pin(URL, "v1.0.0", COMMIT, credential=("x-access-token", "s3cr3t-token"), runner=runner)
        call = runner.calls[0]
        assert call["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert call["env"]["TAP_GIT_PASSWORD"] == "s3cr3t-token"
        assert "GIT_ASKPASS" in call["env"]
        assert not any("s3cr3t-token" in a for a in call["args"])

    def test_the_real_runner_runs_outside_any_repository(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """A mounted session worktree's .git points at a host path; git must not discover it."""
        seen: dict[str, Any] = {}

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            seen.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, LIGHTWEIGHT, "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.chdir(tmp_path)
        resolve_tag(URL, "v1.0.0")
        assert seen["cwd"] == tempfile.gettempdir()


def test_commit_sha_shape() -> None:
    assert is_commit_sha(COMMIT)
    assert not is_commit_sha(COMMIT.upper())
    assert not is_commit_sha(COMMIT[:12])
    assert not is_commit_sha(None)


@pytest.mark.spec("req-boot-bootstrap-install-commit-pin")
class TestCheckProfiles:
    def _profile(self, tmp_path: Path, source: dict[str, Any]) -> Path:
        path = tmp_path / "x.boot.json"
        entry = {"slug": "widget", "enabled": True, "source": {"type": "git", "url": URL, **source}}
        path.write_text(json.dumps({"install": {"plugins": [entry]}}))
        return path

    def test_a_matching_pair_passes(self, tmp_path: Path) -> None:
        path = self._profile(tmp_path, {"rev": "v1.0.0", "commit": COMMIT})
        code, _ = check_profiles([path], checker=lambda u, r, c: TagCheck(TAG_MATCHES, observed=c))
        assert code == 0

    @pytest.mark.parametrize("state", [TAG_MOVED, TAG_MISSING])
    def test_a_disagreeing_pair_fails(self, tmp_path: Path, state: str) -> None:
        path = self._profile(tmp_path, {"rev": "v1.0.0", "commit": COMMIT})
        code, lines = check_profiles([path], checker=lambda u, r, c: TagCheck(state, detail="d"))
        assert code == 1
        assert lines[0].startswith("FAIL")

    def test_an_unpinned_source_fails(self, tmp_path: Path) -> None:
        path = self._profile(tmp_path, {"rev": "v1.0.0"})
        code, lines = check_profiles([path], checker=lambda u, r, c: pytest.fail("no commit, no forge call"))
        assert code == 1
        assert "no commit" in lines[0]

    def test_unobservable_is_its_own_exit_code(self, tmp_path: Path) -> None:
        path = self._profile(tmp_path, {"rev": "v1.0.0", "commit": COMMIT})
        code, _ = check_profiles([path], checker=lambda u, r, c: TagCheck(TAG_NOT_OBSERVABLE, detail="offline"))
        assert code == 2


def test_every_committed_git_source_pins_a_commit() -> None:
    """Offline half of the author-time check: tap's own profiles all carry a well-formed commit."""
    repo = Path(__file__).resolve().parents[2]
    for path in sorted((repo / "boot").glob("*.boot.json")):
        for entry in (json.loads(path.read_text()).get("install") or {}).get("plugins", []):
            source = entry.get("source") or {}
            if source.get("type") == "git":
                assert is_commit_sha(source.get("commit")), f"{path.name}: {entry['slug']} has no commit"
