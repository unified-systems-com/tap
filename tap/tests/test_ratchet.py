"""Unit tests for the shared ratchet core (`tap.ratchet`).

The compare-and-report is now load-bearing for every migrated ratchet, so its two
directions are tested directly: a ceiling fails on a NEW item and on a STALE
baseline entry (and only passes when they match); a floor fails on regression,
reports on improvement, and is silent exactly at the floor.
"""

from __future__ import annotations

import pytest

from tap.ratchet import RatchetError, ratchet_ceiling, ratchet_floor, read_baseline_set

_HINT = "fix it"


def _ceiling(current, baseline):
    ratchet_ceiling(current=set(current), baseline=set(baseline), surface="test", baseline_path="b.txt", new_hint=_HINT)


def test_ceiling_passes_when_equal():
    _ceiling({"a", "b"}, {"a", "b"})  # no raise


def test_ceiling_fails_on_new_item():
    with pytest.raises(RatchetError, match="new item"):
        _ceiling({"a", "b", "c"}, {"a", "b"})


def test_ceiling_fails_on_stale_entry():
    with pytest.raises(RatchetError, match="ratchets toward zero"):
        _ceiling({"a"}, {"a", "b"})


def test_ceiling_empty_both_passes():
    _ceiling(set(), set())  # strict, clean


def test_floor_passes_at_floor():
    assert ratchet_floor(current=73.0, floor=73, surface="t", baseline_path="b") is None


def test_floor_fails_below():
    with pytest.raises(RatchetError, match="regressed below"):
        ratchet_floor(current=72.9, floor=73, surface="t", baseline_path="b")


def test_floor_reports_improvement():
    msg = ratchet_floor(current=75.4, floor=73, surface="t", baseline_path="b")
    assert msg is not None and "bump the floor" in msg.lower()


def test_floor_lock_gains_raises_on_improvement():
    with pytest.raises(RatchetError, match="lock the gain"):
        ratchet_floor(current=75.0, floor=73, surface="t", baseline_path="b", lock_gains=True)


def test_read_baseline_set_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "base.txt"
    p.write_text("# a comment\n\nfoo.py:10\n  bar.py:20  \n# another\n")
    assert read_baseline_set(p) == {"foo.py:10", "bar.py:20"}


def test_read_baseline_set_missing_is_empty(tmp_path):
    assert read_baseline_set(tmp_path / "nope.txt") == set()


# ---------------------------------------------------------------------------
# Baseline-entry hygiene — req-dev-validation-ratchet-harness-5
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-dev-validation-ratchet-harness-5")
def test_out_of_repo_tripwire_is_separator_agnostic(tmp_path):
    """Backslash and drive-letter entries trip identically to POSIX ones — a committed
    baseline is POSIX by convention, so a foreign separator is at best noise and at
    worst a tripwire dodge (AI-review finding on PR #105, closed here)."""
    from tap.ratchet import _out_of_repo_reason

    assert _out_of_repo_reason("C:\\tap_secrets\\x.json") == "absolute path"
    assert _out_of_repo_reason("..\\x\\y.py::tok") == "path escapes the repo (`..`)"
    assert _out_of_repo_reason("tap\\..\\..\\etc\\passwd") == "path escapes the repo (`..`)"
    assert "tap_secrets" in (_out_of_repo_reason("tap_secrets\\a.secret.json") or "")
    # benign entries stay benign
    assert _out_of_repo_reason("tap/foo.py::req-x") is None
    assert _out_of_repo_reason("req-some-rid") is None


def test_read_baseline_rejects_out_of_repo_entries(tmp_path):
    """The positive control: each escape shape fails the read outright."""
    for bad in (
        "/Users/someone/tap-sessions/x/tap/foo.py::qualname::Model.op",
        "../outside/foo.py:err:1",
        "tap_secrets/github/collector.secret.json",
        "plugins/x/vendor/schema.json",
    ):
        p = tmp_path / "baseline.txt"
        p.write_text(f"# header\n{bad}\n", encoding="utf-8")
        with pytest.raises(RatchetError, match="baseline hygiene"):
            read_baseline_set(p)


@pytest.mark.spec("req-dev-validation-ratchet-harness-5")
def test_read_baseline_accepts_repo_paths_and_non_path_entries(tmp_path):
    p = tmp_path / "baseline.txt"
    p.write_text(
        "tap/guards/mypy.py:attr-defined:2\n"
        "tap_web/page.py::build_url_id::Entity.create#abc123def456\n"
        "req-boot-abort-signal\n"
        "tap_grid/gryphon/coverage-baseline.json\n",
        encoding="utf-8",
    )
    assert len(read_baseline_set(p)) == 4
