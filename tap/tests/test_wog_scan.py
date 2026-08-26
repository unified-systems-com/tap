"""Unit tests for the WOG corpus parser (`specs/spec-wog.md`).

The guard meta-tests in `test_guards.py` only assert that the corpus parses to
something non-empty, which is too weak to catch the failure mode this file exists
for: an entry silently *disappearing* from the parse. That is not a loud failure —
a dropped entry is uncitable and never shape-checked, and every guard still passes.

The regression case is real. `_parse` originally required a blank line above every
title, so the first entry in a tier file — which sits directly under the file's own
`=` header rule — was discarded without complaint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.guards._wog_scan import TIER_FILES, WOG_DIR, _parse, entries

HEADER = "Way of the Grid - Test\n======================"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wog-test.txt"
    path.write_text(f"{HEADER}\n{body}", encoding="utf-8")
    return path


@pytest.mark.spec("req-wog-entry-shape-1")
def test_first_entry_directly_under_the_file_header_is_parsed(tmp_path):
    """The regression: an entry abutting the `=` header rule must not be dropped."""
    parsed = _parse(_write(tmp_path, "Vision\n------\nall visionaries are mad\n"), "apocrypha")

    assert [e.name for e in parsed] == ["Vision"]
    assert parsed[0].body == "all visionaries are mad"


def test_every_tier_file_on_the_live_tree_yields_its_first_entry():
    """Same invariant against the real corpus, so a future header change is caught here."""
    for filename, tier in TIER_FILES.items():
        path = WOG_DIR / filename
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        # Skip the file's own title and its `=` rule, then take the first line with content:
        # that is the first entry's title, whether or not a blank line separates it.
        first_title = next(line.rstrip() for line in lines[2:] if line.strip())
        names = [e.name for e in _parse(path, tier)]
        assert first_title in names, f"{filename}: first entry {first_title!r} missing from {names}"


@pytest.mark.spec("req-wog-entry-shape-1")
def test_a_body_line_above_a_shorter_dash_rule_is_not_a_title(tmp_path):
    """The length rule is what separates a title from prose that happens to precede dashes."""
    parsed = _parse(_write(tmp_path, "Real\n----\nprose continues\n--\nmore body\n"), "settled")

    assert [e.name for e in parsed] == ["Real"]


@pytest.mark.spec("req-wog-entry-shape-1")
def test_a_mis_underlined_entry_still_parses_so_the_shape_guard_can_fail_it(tmp_path):
    """Detection stays lenient on purpose: a malformed entry must be visible, not vanish."""
    parsed = _parse(_write(tmp_path, "Real\n----\nbody\n\nWrong\n--\nbody\n"), "settled")

    names = [e.name for e in parsed]
    assert names == ["Real", "Wrong"], "a mis-underlined entry must reach wog-entry-shape, not disappear"


@pytest.mark.spec("req-wog-tiers-1")
def test_entries_carry_the_tier_of_the_file_they_live_in():
    """Status is read from location and nowhere else, so a promotion is a move."""
    by_tier = {e.name: e.tier for e in entries()}

    assert by_tier, "no WOG entries parsed"
    assert set(by_tier.values()) <= set(TIER_FILES.values())
