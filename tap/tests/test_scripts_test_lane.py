"""The argument handling of `scripts/test` (tap#1092): which lane args the promote lane builds.

Spec: specs/spec-dev-validation.md (req-dev-validation-suite-tiers-6, -7).

`scripts/test` needs a live stack to run for real. These tests run the REAL script in a throwaway git
repo whose `scripts/dc` is a stub that prints the argv it was handed, so what is asserted is the exact
lane the script would have started — not the script's text.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 — fixed argv: bash + the script under test, in a temp repo
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None, reason="needs bash and git")


@pytest.fixture()
def lane(tmp_path: Path):
    """A temp repo with the real scripts/test, a stub scripts/dc, and origin/main at the first commit."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "test", tmp_path / "scripts" / "test")
    dc = tmp_path / "scripts" / "dc"
    dc.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ " $* " == *" tap.impacted_plugins "* ]]; then cat >/dev/null; printf "%s\\n" ${IMPACTED:-}; exit 0; fi\n'
        'printf "DC:"; printf " %s" "$@"; printf "\\n"\n'
    )
    for f in (tmp_path / "scripts" / "test", dc):
        f.chmod(0o755)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True
        )  # nosec B603 B607  # nosemgrep  # noqa: S603 S607

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")

    def run(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603  # nosemgrep  # noqa: S603
            [str(BASH), "scripts/test", *args],
            cwd=tmp_path,
            env={**env, **(extra_env or {})},
            text=True,
            capture_output=True,
            check=False,
        )

    def touch(rel: str) -> None:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n")

    return run, touch


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_promote_lane_off_the_executor_footprint_runs_no_plugin_suite(lane) -> None:
    run, touch = lane
    touch("tap_web/x.py")
    out = run("--fast-relevant")
    assert out.returncode == 0, out.stderr
    assert "--no-plugins" in out.stdout and "--only" not in out.stdout
    assert "--exclude gryphon_playground" in out.stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_promote_lane_on_the_executor_footprint_runs_only_the_corpus(lane) -> None:
    run, touch = lane
    touch("tap_grid/gryphon/x.py")
    out = run("--fast-relevant")
    assert out.returncode == 0, out.stderr
    assert "--only gryphon_playground" in out.stdout and "--require gryphon_playground" in out.stdout
    assert "--no-plugins" not in out.stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_plugins_flag_adds_named_suites_to_the_scoped_lane(lane) -> None:
    run, touch = lane
    touch("tap_web/x.py")
    out = run("--fast-relevant", "--plugins", "rampart_20x_playground,aws_core")
    assert out.returncode == 0, out.stderr
    assert "--only rampart_20x_playground --only aws_core" in out.stdout
    assert "--no-plugins" not in out.stdout
    eq = run("--fast-relevant", "--plugins=aws_core")
    assert "--only aws_core" in eq.stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_plugins_flag_is_refused_outside_the_promote_lane(lane) -> None:
    run, _ = lane
    out = run("--fast", "--plugins", "aws_core")
    assert out.returncode == 2 and "--fast-relevant only" in out.stderr


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_jobs_cap_and_reuse_db_are_read_host_side(lane) -> None:
    run, touch = lane
    touch("tap_web/x.py")
    assert "-n 3" in run("--fast-relevant", extra_env={"TAP_TEST_JOBS": "3"}).stdout
    assert "-n 0" in run("--fast-relevant", extra_env={"TAP_TEST_JOBS": "0"}).stdout  # serial: no per-worker DB build
    assert "--reuse-db" in run("--fast-relevant", extra_env={"TAP_TEST_REUSE_DB": "1"}).stdout
    assert "--reuse-db" not in run("--fast-relevant").stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_stop_asks_the_container_to_stop_the_lock_holder(lane) -> None:
    run, _ = lane
    out = run("--stop")
    assert out.returncode == 0 and "tap.pytest_lock stop" in out.stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_a_focused_run_goes_through_the_lock(lane) -> None:
    run, _ = lane
    out = run("tap/tests/test_x.py")
    assert "tap.pytest_lock run --" in out.stdout and "tap/tests/test_x.py" in out.stdout


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_no_core_with_plugins_runs_just_those_suites(lane) -> None:
    run, touch = lane
    touch("tap_web/x.py")
    out = run("--fast-relevant", "--no-core", "--plugins", "rampart_20x_playground")
    assert out.returncode == 0, out.stderr
    assert "--no-core" in out.stdout and "--only rampart_20x_playground" in out.stdout
    flipped = run("--fast-relevant", "--plugins=rampart_20x_playground", "--no-core")
    assert "--no-core" in flipped.stdout and "--only rampart_20x_playground" in flipped.stdout
    refused = run("--fast", "--no-core")
    assert refused.returncode == 2 and "--fast-relevant only" in refused.stderr


@pytest.mark.spec("req-dev-validation-suite-tiers-6")
def test_no_core_without_plugins_is_refused_not_an_empty_green_lane(lane) -> None:
    run, touch = lane
    touch("tap_web/x.py")
    out = run("--fast-relevant", "--no-core")
    assert out.returncode == 2 and "--no-core needs at least one plugin suite" in out.stderr
    assert "DC:" not in out.stdout  # it never reached the container


@pytest.mark.spec("req-dev-validation-suite-tiers-8")
def test_plugins_auto_runs_the_impacted_suites_alongside_named_ones(lane) -> None:
    run, touch = lane
    touch("tap_grid/x.py")
    out = run("--fast-relevant", "--plugins", "auto,named_core", extra_env={"IMPACTED": "a_core b_core"})
    assert out.returncode == 0, out.stderr
    for slug in ("named_core", "a_core", "b_core"):
        assert f"--only {slug}" in out.stdout
    # nothing reached and nothing named: the empty lane is refused with --no-core, a plain scoped lane without
    none = run("--fast-relevant", "--no-core", "--plugins", "auto")
    assert none.returncode == 2
    plain = run("--fast-relevant", "--plugins", "auto")
    assert plain.returncode == 0 and "--only" not in plain.stdout.replace("--only gryphon_playground", "")
