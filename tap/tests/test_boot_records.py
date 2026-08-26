"""Boot-record integrity guard + unit tests (spec-tap-boot-bootstrap).

The load-bearing test is ``test_repo_boot_records_are_coherent``: it fails CI closed if any
shipped boot record's content drifts from its declared ``sha256`` in the package
``tap-plugin.toml``, or if the manifest and the ``boot/*.boot.json`` files disagree in either
direction (``req-boot-bootstrap-record-version`` / ``req-boot-bootstrap-discovery-4``). The
rest exercise the derivation (``tap/boot_records.py``) on synthetic fixtures.

Pure filesystem + stdlib — no Django, no DB.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tap import boot_records


def test_repo_boot_records_are_coherent() -> None:
    """Every shipped record's declared digest matches its content, both directions coherent."""
    problems = boot_records.check(boot_records.REPO_ROOT)
    assert problems == [], "boot-record integrity drift:\n" + "\n".join(problems)


# --- fixtures ---------------------------------------------------------------


def _make_plugin(
    root: Path, slug: str, records: dict[str, dict[str, object]], *, declare: dict[str, str] | None
) -> Path:
    """Create plugins/<slug>/tap_plugin/<slug>/boot/*.boot.json + a tap-plugin.toml.

    ``records`` maps record name -> record JSON body. ``declare`` maps record name ->
    the sha256 string to write into ``[[boot.records]]`` (None omits the whole table).
    """
    boot_dir = root / "plugins" / slug / "tap_plugin" / slug / "boot"
    boot_dir.mkdir(parents=True)
    for name, body in records.items():
        (boot_dir / f"{name}{boot_records.RECORD_SUFFIX}").write_text(json.dumps(body), encoding="utf-8")
    toml_path = boot_dir.parent / "tap-plugin.toml"
    lines = [f'slug = "{slug}"\n']
    if declare is not None:
        for name, sha in declare.items():
            lines += ["\n[[boot.records]]\n", f'name = "{name}"\n', 'description = "d"\n', f'sha256 = "{sha}"\n']
    toml_path.write_text("".join(lines), encoding="utf-8")
    return toml_path


def test_canonical_digest_is_reformat_stable(tmp_path: Path) -> None:
    """Key order + whitespace do not move the digest; content does."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text('{"x": 1, "y": 2}', encoding="utf-8")
    b.write_text('{\n  "y": 2,\n  "x": 1\n}', encoding="utf-8")
    assert boot_records.canonical_digest(a) == boot_records.canonical_digest(b)
    c = tmp_path / "c.json"
    c.write_text('{"x": 1, "y": 3}', encoding="utf-8")
    assert boot_records.canonical_digest(c) != boot_records.canonical_digest(a)


def test_check_clean_when_declared_matches(tmp_path: Path) -> None:
    body = {"version": 1, "install": {"plugins": []}}
    digest = boot_records.canonical_digest(_write_tmp_record(tmp_path, body))
    _make_plugin(tmp_path, "foo", {"only": body}, declare={"only": digest})
    assert boot_records.check(tmp_path) == []


def _write_tmp_record(tmp_path: Path, body: dict[str, object]) -> Path:
    p = tmp_path / "scratch.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_check_flags_digest_drift(tmp_path: Path) -> None:
    body = {"version": 1, "note": "orig"}
    _make_plugin(tmp_path, "foo", {"r": body}, declare={"r": "0" * 64})
    problems = boot_records.check(tmp_path)
    assert any("content changed" in p and "foo" in p for p in problems)


def test_check_flags_empty_digest(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "foo", {"r": {"a": 1}}, declare={"r": ""})
    problems = boot_records.check(tmp_path)
    assert any("empty sha256" in p for p in problems)


def test_check_flags_undeclared_record(tmp_path: Path) -> None:
    """A record file with no [[boot.records]] entry fails closed."""
    _make_plugin(tmp_path, "foo", {"r": {"a": 1}}, declare={})
    problems = boot_records.check(tmp_path)
    assert any("no [[boot.records]] entry" in p for p in problems)


def test_check_flags_orphan_declaration(tmp_path: Path) -> None:
    """A [[boot.records]] entry with no matching file fails closed."""
    boot_dir = tmp_path / "plugins" / "foo" / "tap_plugin" / "foo" / "boot"
    boot_dir.mkdir(parents=True)
    (boot_dir / f"real{boot_records.RECORD_SUFFIX}").write_text('{"a": 1}', encoding="utf-8")
    digest = boot_records.canonical_digest(boot_dir / f"real{boot_records.RECORD_SUFFIX}")
    (boot_dir.parent / "tap-plugin.toml").write_text(
        'slug = "foo"\n'
        f'\n[[boot.records]]\nname = "real"\ndescription = "d"\nsha256 = "{digest}"\n'
        '\n[[boot.records]]\nname = "ghost"\ndescription = "d"\nsha256 = "0000"\n',
        encoding="utf-8",
    )
    problems = boot_records.check(tmp_path)
    assert any("no 'boot/ghost" in p for p in problems)


def test_refresh_populates_and_then_checks_clean(tmp_path: Path) -> None:
    body = {"version": 1, "install": {"plugins": [{"slug": "x"}]}}
    _make_plugin(tmp_path, "foo", {"playground": body, "soak": body}, declare={"playground": "", "soak": ""})
    changed = boot_records.refresh(tmp_path)
    assert len(changed) == 1
    assert boot_records.check(tmp_path) == []
    # Idempotent: a second refresh changes nothing.
    assert boot_records.refresh(tmp_path) == []


def _make_dev_plugin(
    root: Path, slug: str, records: dict[str, dict[str, object]], *, declare: dict[str, str] | None
) -> Path:
    """Like _make_plugin but under _dev-plugins/<slug>/ — a plugin-workspace dev checkout."""
    boot_dir = root / "_dev-plugins" / slug / "tap_plugin" / slug / "boot"
    boot_dir.mkdir(parents=True)
    for name, body in records.items():
        (boot_dir / f"{name}{boot_records.RECORD_SUFFIX}").write_text(json.dumps(body), encoding="utf-8")
    toml_path = boot_dir.parent / "tap-plugin.toml"
    lines = [f'slug = "{slug}"\n']
    if declare is not None:
        for name, sha in declare.items():
            lines += ["\n[[boot.records]]\n", f'name = "{name}"\n', 'description = "d"\n', f'sha256 = "{sha}"\n']
    toml_path.write_text("".join(lines), encoding="utf-8")
    return toml_path


def test_dev_plugins_checkout_is_discovered_and_refreshable(tmp_path: Path) -> None:
    """The fork-cutover flow: an adopter edits their _dev-plugins checkout's in-package
    record and MUST be able to run the digest derivation against it — the toml says
    'never hand-edit' and points at this tool, so invisibility was a contradiction."""
    body = {"version": 1, "install": {"plugins": [{"slug": "samsite"}]}}
    toml_path = _make_dev_plugin(tmp_path, "samsite", {"samsite": body}, declare={"samsite": ""})

    # Discovered alongside the monorepo layout, refresh rewrites the checkout's toml.
    assert [m.slug for m in boot_records.discover(tmp_path)] == ["samsite"]
    assert boot_records.refresh(tmp_path) == [toml_path]
    assert boot_records.check(tmp_path) == []

    # Drift in the checkout is flagged, same as a shipped record.
    record = tmp_path / "_dev-plugins" / "samsite" / "tap_plugin" / "samsite" / "boot" / "samsite.boot.json"
    record.write_text(json.dumps({**body, "description": "edited"}), encoding="utf-8")
    assert any("content changed" in p for p in boot_records.check(tmp_path))


def test_both_layouts_discovered_together(tmp_path: Path) -> None:
    body: dict[str, object] = {"version": 1}
    _make_plugin(tmp_path, "shipped", {"a": body}, declare={"a": ""})
    _make_dev_plugin(tmp_path, "checkout", {"b": body}, declare={"b": ""})
    assert sorted(m.slug for m in boot_records.discover(tmp_path)) == ["checkout", "shipped"]
    assert len(boot_records.refresh(tmp_path)) == 2


def test_no_dev_plugins_dir_behaves_identically(tmp_path: Path) -> None:
    """A worktree without _dev-plugins (every CI checkout) is unaffected by the sweep."""
    body: dict[str, object] = {"version": 1}
    _make_plugin(tmp_path, "only", {"a": body}, declare={"a": ""})
    assert [m.slug for m in boot_records.discover(tmp_path)] == ["only"]
    assert len(boot_records.refresh(tmp_path)) == 1
    assert boot_records.check(tmp_path) == []


class TestDeclaredRecordDigests:
    """The shared declared-digest parse — one semantics for all three gates.

    Before the collapse the three copies disagreed on duplicate names
    (first-wins / last-wins / error), letting the stage-0 integrity gate and the
    in-repo guard verify against different declarations. Strictest wins.
    """

    def test_extracts_name_to_sha_map(self) -> None:
        manifest = {"boot": {"records": [{"name": "a", "sha256": "d1"}, {"name": "b", "sha256": "d2"}]}}
        assert boot_records.declared_record_digests(manifest) == {"a": "d1", "b": "d2"}

    def test_absent_or_empty_table_is_empty(self) -> None:
        assert boot_records.declared_record_digests({}) == {}
        assert boot_records.declared_record_digests({"boot": {}}) == {}
        assert boot_records.declared_record_digests({"boot": {"records": []}}) == {}

    def test_empty_sha_preserved_for_caller(self) -> None:
        """Empty digest = structural pass, integrity failure — the CALLER's call."""
        manifest = {"boot": {"records": [{"name": "a"}]}}
        assert boot_records.declared_record_digests(manifest) == {"a": ""}

    def test_duplicate_name_is_hard_error(self) -> None:
        manifest = {"boot": {"records": [{"name": "a", "sha256": "d1"}, {"name": "a", "sha256": "d2"}]}}
        with pytest.raises(boot_records.BootRecordManifestError, match="duplicate boot record name 'a'"):
            boot_records.declared_record_digests(manifest)

    def test_non_string_sha_is_hard_error(self) -> None:
        manifest = {"boot": {"records": [{"name": "a", "sha256": 123}]}}
        with pytest.raises(boot_records.BootRecordManifestError, match="sha256 must be a string"):
            boot_records.declared_record_digests(manifest)

    def test_missing_name_is_hard_error(self) -> None:
        manifest = {"boot": {"records": [{"sha256": "d1"}]}}
        with pytest.raises(boot_records.BootRecordManifestError, match="non-empty string 'name'"):
            boot_records.declared_record_digests(manifest)
