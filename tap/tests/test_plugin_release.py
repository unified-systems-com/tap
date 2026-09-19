"""Unit tests for tap.plugin_release (req-dev-workspace-release, tap#513).

Pure-function coverage of tag normalization + the consuming-profile adopt: no git, network,
or Django. The forge lookup is the one impure edge, so it enters through a stub resolver —
the same seam shape `tap.git_pin` uses for its subprocess. The live push/tag steps live in
scripts/release-plugin.sh.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tap.git_pin import TAG_MATCHES, TAG_MISSING, TAG_NOT_OBSERVABLE, TagCheck
from tap.plugin_release import (
    PluginReleaseError,
    ProfileBump,
    bump_profiles,
    find_consumers,
    normalize_tag,
)

#: What the stub forge says a tag names, unless a test says otherwise.
SHA = "a" * 40
OTHER_SHA = "b" * 40


class _resolver:
    """A stub forge: every tag resolves to *commit* with *state*, recording the calls it saw."""

    def __init__(self, commit: str = SHA, state: str = TAG_MATCHES, detail: str = "") -> None:
        self.commit = commit
        self.state = state
        self.detail = detail
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, tag: str) -> TagCheck:
        self.calls.append((url, tag))
        observed = self.commit if self.state == TAG_MATCHES else None
        return TagCheck(self.state, observed=observed, detail=self.detail)


def _write_profile(boot_dir: Path, name: str, plugins: list[dict[str, Any]]) -> Path:
    path = boot_dir / f"{name}.boot.json"
    path.write_text(
        json.dumps({"version": 1, "description": name, "install": {"plugins": plugins}}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _git(slug: str, rev: str, *, note: str | None = None, commit: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "slug": slug,
        "enabled": True,
        "source": {
            "type": "git",
            "url": f"https://github.com/unified-systems-com/tap-plugin-{slug.replace('_', '-')}",
            "rev": rev,
            "credential": "github-plugins-ro",
        },
    }
    if commit is not None:
        entry["source"]["commit"] = commit
    if note is not None:
        entry["note"] = note
    return entry


def _editable(slug: str) -> dict[str, Any]:
    return {"slug": slug, "enabled": True, "source": {"type": "editable", "path": f"plugins/{slug}"}}


# --------------------------------------------------------------------------- normalize_tag


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.2.0", "v0.2.0"),
        ("v0.2.0", "v0.2.0"),
        ("1.10.3", "v1.10.3"),
        ("0.2.0-rc1", "v0.2.0-rc1"),
        ("v2.0.0+build.5", "v2.0.0+build.5"),
    ],
)
def test_normalize_tag_accepts_and_canonicalizes(raw: str, expected: str) -> None:
    assert normalize_tag(raw) == expected


@pytest.mark.parametrize("raw", ["0.2", "v0", "1.2.3.4", "latest", "", "v0.2.0 ", "0.2.0a"])
def test_normalize_tag_rejects_malformed(raw: str) -> None:
    with pytest.raises(PluginReleaseError):
        normalize_tag(raw)


# --------------------------------------------------------------------------- bump_profiles


def test_bumps_only_the_named_slug_in_git_entries(tmp_path: Path) -> None:
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0"), _git("fedramp_20x_ksi", "v0.2.0")])
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())

    assert [b.old_rev for b in bumps] == ["v0.1.0"]
    written = json.loads((tmp_path / "samsite.boot.json").read_text())
    by_slug = {p["slug"]: p for p in written["install"]["plugins"]}
    assert by_slug["compliance_core"]["source"]["rev"] == "v0.2.0"
    assert by_slug["fedramp_20x_ksi"]["source"]["rev"] == "v0.2.0"  # untouched
    assert "commit" not in by_slug["fedramp_20x_ksi"]["source"]  # and not pinned by someone else's adopt


def test_writes_the_resolved_commit_beside_the_rev(tmp_path: Path) -> None:
    """The point of tap#513: the pair moves together, and the SHA comes from the forge."""
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    resolve = _resolver()
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=resolve)

    source = json.loads((tmp_path / "samsite.boot.json").read_text())["install"]["plugins"][0]["source"]
    assert (source["rev"], source["commit"]) == ("v0.2.0", SHA)
    assert bumps[0].new_commit == SHA
    assert bumps[0].old_commit is None  # was unpinned: a fill-in, not a move
    assert resolve.calls == [(source["url"], "v0.2.0")]


def test_replaces_the_previous_tags_commit(tmp_path: Path) -> None:
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0", commit=OTHER_SHA)])
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    source = json.loads((tmp_path / "samsite.boot.json").read_text())["install"]["plugins"][0]["source"]
    assert (source["rev"], source["commit"]) == ("v0.2.0", SHA)
    assert bumps[0].old_commit == OTHER_SHA


def test_bumps_across_multiple_profiles(tmp_path: Path) -> None:
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    _write_profile(tmp_path, "operator_sso", [_git("compliance_core", "v0.1.0")])
    resolve = _resolver()
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=resolve)
    assert {b.path.name for b in bumps} == {"samsite.boot.json", "operator_sso.boot.json"}
    for name in ("samsite", "operator_sso"):
        source = json.loads((tmp_path / f"{name}.boot.json").read_text())["install"]["plugins"][0]["source"]
        assert (source["rev"], source["commit"]) == ("v0.2.0", SHA)
    assert len(resolve.calls) == 1, "one lookup per distinct URL, not per profile"


def test_already_adopted_is_a_noop(tmp_path: Path) -> None:
    """Same tag AND same commit: nothing to do."""
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.2.0", commit=SHA)])
    assert bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver()) == []


def test_same_tag_without_a_commit_is_filled_in(tmp_path: Path) -> None:
    """A pre-tap#512 profile already at the tag still needs its SHA, or the pins gate fails."""
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.2.0")])
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    assert [(b.old_rev, b.new_rev, b.new_commit) for b in bumps] == [("v0.2.0", "v0.2.0", SHA)]
    source = json.loads((tmp_path / "samsite.boot.json").read_text())["install"]["plugins"][0]["source"]
    assert source["commit"] == SHA


def test_a_moved_tag_refuses_rather_than_re_pinning(tmp_path: Path) -> None:
    """Already at the tag, but the forge now names a different commit: a human decides."""
    path = _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.2.0", commit=OTHER_SHA)])
    before = path.read_text()
    with pytest.raises(PluginReleaseError, match="MOVED"):
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    assert path.read_text() == before


@pytest.mark.parametrize(
    "state,detail",
    [(TAG_MISSING, "no tag 'v0.2.0' at …"), (TAG_NOT_OBSERVABLE, "git ls-remote timed out after 10s")],
)
def test_an_unresolvable_tag_refuses_and_writes_nothing(tmp_path: Path, state: str, detail: str) -> None:
    path = _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    before = path.read_text()
    with pytest.raises(PluginReleaseError, match=state):
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver(state=state, detail=detail))
    assert path.read_text() == before


def test_a_refusal_never_echoes_a_credential_bearing_url(tmp_path: Path) -> None:
    """The refusal message reaches stderr and CI logs (Codex on PR 552).

    The MALFORMED-url branch is exactly where a credential hides: the accepted shapes forbid
    userinfo, so anything carrying `user:token@` is a url that failed validation — the one
    the error is about. Same rule as tap.preboot on a refused source.
    """
    entry = _git("compliance_core", "v0.1.0")
    entry["source"]["url"] = "https://user:s3cr3t-token@forge.example/repo"
    _write_profile(tmp_path, "samsite", [entry])

    def rejecting(url: str, tag: str) -> TagCheck:
        raise ValueError("git source url must be https:// or ssh:// with no userinfo")

    with pytest.raises(PluginReleaseError) as excinfo:
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=rejecting)
    message = str(excinfo.value)
    assert "s3cr3t-token" not in message
    assert "user:" not in message
    assert "https://forge.example/repo" in message  # still identifies WHICH source


def test_an_unresolvable_url_is_redacted_too(tmp_path: Path) -> None:
    """The missing/not_observable branch prints the source as well — redact it the same way."""
    entry = _git("compliance_core", "v0.1.0")
    entry["source"]["url"] = "https://tok3n@forge.example/repo"
    _write_profile(tmp_path, "samsite", [entry])
    with pytest.raises(PluginReleaseError) as excinfo:
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver(state=TAG_MISSING))
    assert "tok3n" not in str(excinfo.value)


def test_a_refusal_leaves_earlier_profiles_untouched(tmp_path: Path) -> None:
    """All-or-nothing: the plan is built before the first write, so a late refusal rolls nothing back."""
    good = _write_profile(tmp_path, "aaa_first", [_git("compliance_core", "v0.1.0")])
    bad = _write_profile(tmp_path, "zzz_last", [_git("compliance_core", "v0.2.0", commit=OTHER_SHA)])
    before = (good.read_text(), bad.read_text())
    with pytest.raises(PluginReleaseError):
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    assert (good.read_text(), bad.read_text()) == before


def test_editable_entry_is_not_bumped(tmp_path: Path) -> None:
    _write_profile(tmp_path, "test_all", [_editable("compliance_core")])
    resolve = _resolver()
    assert bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=resolve) == []
    written = json.loads((tmp_path / "test_all.boot.json").read_text())
    assert written["install"]["plugins"][0]["source"] == {"type": "editable", "path": "plugins/compliance_core"}
    assert resolve.calls == [], "no git source, so no forge lookup"


def test_refreshes_tag_in_note_prose(tmp_path: Path) -> None:
    note = "Git-sourced from its own repo at v0.1.0 via the github-plugins-ro PAT."
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0", note=note)])
    bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    written = json.loads((tmp_path / "samsite.boot.json").read_text())
    assert "at v0.2.0 via" in written["install"]["plugins"][0]["note"]
    assert "v0.1.0" not in written["install"]["plugins"][0]["note"]


def test_note_refresh_does_not_touch_unrelated_versions(tmp_path: Path) -> None:
    # Only the entry's own old rev token is swapped; a different version mentioned in prose stays.
    note = "Pinned at v0.1.0; compatible with core v0.1.5."
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0", note=note)])
    bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())
    written = json.loads((tmp_path / "samsite.boot.json").read_text())
    assert "core v0.1.5" in written["install"]["plugins"][0]["note"]
    assert "Pinned at v0.2.0;" in written["install"]["plugins"][0]["note"]


def test_dry_run_reports_the_commit_but_does_not_write(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    before = path.read_text()
    bumps = bump_profiles(tmp_path, "compliance_core", "v0.2.0", dry_run=True, resolver=_resolver())
    assert bumps == [
        ProfileBump(
            path=path,
            slug="compliance_core",
            old_rev="v0.1.0",
            new_rev="v0.2.0",
            new_commit=SHA,
            old_commit=None,
        )
    ]
    assert path.read_text() == before  # untouched on disk


def test_dry_run_still_consults_the_forge(tmp_path: Path) -> None:
    """A dry run that skipped the lookup would report a SHA it had not verified."""
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    with pytest.raises(PluginReleaseError, match=TAG_NOT_OBSERVABLE):
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", dry_run=True, resolver=_resolver(state=TAG_NOT_OBSERVABLE))


def test_no_consumer_returns_empty(tmp_path: Path) -> None:
    _write_profile(tmp_path, "samsite", [_git("other_plugin", "v0.1.0")])
    resolve = _resolver()
    assert bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=resolve) == []
    assert resolve.calls == [], "nothing to adopt, so no forge lookup"


def test_malformed_profile_raises(tmp_path: Path) -> None:
    (tmp_path / "broken.boot.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PluginReleaseError, match="cannot read boot profile"):
        bump_profiles(tmp_path, "compliance_core", "v0.2.0", resolver=_resolver())


# --------------------------------------------------------------------------- find_consumers


def test_find_consumers_lists_only_git_sourced(tmp_path: Path) -> None:
    _write_profile(tmp_path, "samsite", [_git("compliance_core", "v0.1.0")])
    _write_profile(tmp_path, "test_all", [_editable("compliance_core")])
    _write_profile(tmp_path, "soak", [_git("other", "v0.1.0")])
    consumers = find_consumers(tmp_path, "compliance_core")
    assert [p.name for p in consumers] == ["samsite.boot.json"]
