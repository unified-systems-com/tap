"""The specs tier's narrowing is measured, and the measurement is checked (req-dev-validation-product-line-lanes-7).

These tests run the recorder for real, in a child pytest over a throwaway repository, because
the property that matters is attribution: a read during collection, in a test, and in a
session fixture that only its first requester triggers must each land on the right file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tap import lane_run
from tap.spec_read_audit import LIST_PATH, is_spec_path, listed, main

REPO = Path(__file__).resolve().parents[2]


def test_a_spec_path_is_a_specs_directory_inside_the_repository() -> None:
    assert is_spec_path("/app/specs/spec-x.md", "/app")
    assert is_spec_path("/app/tap_grid/specs/spec-y.md", "/app")
    assert is_spec_path("/app/specs", "/app")
    assert not is_spec_path("/tmp/t/repo/specs/spec-x.md", "/app"), "a test's own temporary specs/ is not ours"
    assert not is_spec_path("/app/tap/specs_tier.py", "/app")
    assert not is_spec_path("/application/specs/x.md", "/app")


def _run_recorder(tmp_path: Path, conftest_reads_at_import: bool = False) -> dict[str, list[str]]:
    root = tmp_path / "repo"
    (root / "specs").mkdir(parents=True)
    (root / "specs" / "spec-a.md").write_text("| req-a |\n")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (root / "conftest.py").write_text(
        "import pytest\n"
        "from pathlib import Path\n"
        + ("ROWS = (Path(__file__).parent / 'specs' / 'spec-a.md').read_text()\n" if conftest_reads_at_import else "")
        +
        "@pytest.fixture(scope='session')\n"
        "def spec_rows():\n"
        "    return (Path(__file__).parent / 'specs' / 'spec-a.md').read_text()\n"
    )
    (root / "test_collects.py").write_text(
        "from pathlib import Path\n"
        "ROWS = (Path(__file__).parent / 'specs' / 'spec-a.md').read_text().splitlines()\n"
        "def test_rows():\n    assert ROWS\n"
    )
    (root / "test_reads.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_walks():\n    assert os.listdir(Path(__file__).parent / 'specs')\n"
    )
    (root / "test_fixture_first.py").write_text("def test_one(spec_rows):\n    assert spec_rows\n")
    (root / "test_fixture_second.py").write_text("def test_two(spec_rows):\n    assert spec_rows\n")
    (root / "test_clean.py").write_text("def test_nothing():\n    assert open(__file__).read()\n")
    out = tmp_path / "out"
    env = {**os.environ, "TAP_SPEC_READ_AUDIT": str(out), "PYTHONPATH": str(REPO)}
    env.pop("PYTEST_XDIST_WORKER", None)
    proc = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — a child pytest over a throwaway repo IS the test; argv list of sys.executable and fixed strings, no shell  # nosec B603  # noqa: S603
        [sys.executable, "-m", "pytest", "-p", "tap.spec_read_audit", "-p", "no:cacheprovider", "-q", "-n0",
         "-p", "no:django", "--rootdir", str(root), "-c", str(root / "pyproject.toml"), str(root)],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    record: dict[str, list[str]] = json.loads((out / "spec-readers-main.json").read_text())
    return record


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_reads_are_charged_to_the_module_the_test_and_every_fixture_requester(tmp_path: Path) -> None:
    record = _run_recorder(tmp_path)
    assert record["unattributed"] == [], "pytest walking specs/ is not a read"
    assert record["readers"] == sorted(
        ["test_collects.py", "test_reads.py", "test_fixture_first.py", "test_fixture_second.py"]
    ), "the second requester of a session fixture never triggers its setup, and must still be charged"


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_a_conftest_reading_a_spec_at_import_is_caught_and_refuses_the_check(tmp_path: Path) -> None:
    """A read no test can be charged with is the hole a narrowed lane would fall through."""
    record = _run_recorder(tmp_path, conftest_reads_at_import=True)
    assert record["unattributed"] == ["specs/spec-a.md"]
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "spec-readers-main.json").write_text(json.dumps(record))
    lst = tmp_path / "list.txt"
    lst.write_text("".join(f"{f}\n" for f in record["readers"]))
    assert main(["--check", str(rec), "--list", str(lst)]) == 1


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_the_check_fails_on_an_unlisted_reader_and_only_notes_a_stale_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "spec-readers-gw0.json").write_text(json.dumps({"readers": ["tap/tests/test_a.py"], "unattributed": []}))
    (rec / "spec-readers-gw1.json").write_text(json.dumps({"readers": ["tap/tests/test_b.py"], "unattributed": []}))
    lst = tmp_path / "list.txt"
    lst.write_text("# header\ntap/tests/test_a.py\ntap/tests/test_gone.py\n")
    assert main(["--check", str(rec), "--list", str(lst)]) == 1
    err = capsys.readouterr().err
    assert "tap/tests/test_b.py" in err and "test_gone.py" in err
    assert main(["--write", str(rec), "--list", str(lst)]) == 0
    assert listed(lst) == ["tap/tests/test_a.py", "tap/tests/test_b.py"]
    assert main(["--check", str(rec), "--list", str(lst)]) == 0
    with pytest.raises(SystemExit):
        main(["--check", str(tmp_path / "empty"), "--list", str(lst)])  # no recording is no verdict


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_the_committed_list_names_only_existing_core_test_files() -> None:
    named = listed(LIST_PATH)
    assert named and named == sorted(named)
    assert all((REPO / f).is_file() and Path(f).name.startswith("test_") for f in named)
    assert "tap/tests/test_guards.py" in named


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_core_files_narrows_the_walk_and_refuses_a_missing_file(tmp_path: Path) -> None:
    (tmp_path / "tap" / "tests").mkdir(parents=True)
    (tmp_path / "tap" / "tests" / "test_a.py").write_text("")
    lst = tmp_path / "list.txt"
    lst.write_text("# c\ntap/tests/test_a.py\n")
    assert lane_run.core_files(tmp_path, lst) == [str(tmp_path / "tap/tests/test_a.py")]
    lst.write_text("tap/tests/test_a.py\ntap/tests/test_gone.py\n")
    assert "test_gone.py" in str(lane_run.core_files(tmp_path, lst))
    lst.write_text("# only a comment\n")
    assert "names no files" in str(lane_run.core_files(tmp_path, lst))
    (tmp_path.parent / "outside.py").write_text("")
    lst.write_text("../outside.py\n")
    assert "outside" in str(lane_run.core_files(tmp_path, lst)), "an entry that climbs out of the root is refused"
    lst.write_text(f"{tmp_path.parent / 'outside.py'}\n")
    assert "outside" in str(lane_run.core_files(tmp_path, lst)), "so is an absolute path elsewhere"
    assert "not a file inside" in str(lane_run.core_files(tmp_path, tmp_path.parent / "outside.py"))
