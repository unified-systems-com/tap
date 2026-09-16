"""Pre-boot refuses source strings that are not safe to put into ``uv pip install`` (tap#492).

SonarCloud ``pythonsecurity:S6350`` traced three boot-profile strings into the argument list
``tap.preboot._run_install`` executes: git ``url``, git ``rev`` and wheelhouse ``version``.
Slugs and paths were already checked; these were not.

What was probed before writing this (tap-web image, uv 0.12.14, git 2.55, marker files):
hostile revs (``--upload-pack=…``, ``-c``, ``--output=…``) did NOT execute, because uv
prefixes every rev inside the refspecs it builds — so the rev check is defence in depth.
``git+http://`` and ``git+file://`` were accepted and ``file://`` INSTALLED, bypassing the
source-path allowlist — those two are the live gaps.

The accepted shapes are spelled twice — TAP-KNOWN-DUPE(boot-source-input-patterns) — and
the first class here is what makes that duplicate safe.
"""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tap.preboot import (
    GIT_SOURCE_REV_PATTERN,
    GIT_SOURCE_URL_PATTERN,
    WHEELHOUSE_VERSION_PATTERN,
    PrebootError,
    _install_plugin_specs,
)

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "tap_boot" / "schemas" / "boot.schema.json"

_SOURCE_ONE_OF = ("install", "properties", "plugins", "items", "properties", "source", "oneOf")
# (oneOf index, field, Python constant) — the three pairs of the known-dupe group.
PAIRS = [
    pytest.param(0, "url", GIT_SOURCE_URL_PATTERN, id="git.url"),
    pytest.param(0, "rev", GIT_SOURCE_REV_PATTERN, id="git.rev"),
    pytest.param(3, "version", WHEELHOUSE_VERSION_PATTERN, id="wheelhouse.version"),
]


def _source_branch(index: int) -> dict[str, Any]:
    node: Any = json.loads(SCHEMA.read_text())["properties"]
    for key in (*_SOURCE_ONE_OF, index):
        node = node[key]
    assert isinstance(node, dict)
    return node


def _git(url: str = "https://github.com/org/tap-plugin-x", rev: str = "v1.2.3", **extra: Any) -> dict[str, Any]:
    return {"slug": "widget", "enabled": True, "source": {"type": "git", "url": url, "rev": rev}, **extra}


def _wheelhouse(version: str) -> dict[str, Any]:
    source = {"type": "wheelhouse", "dir": "wheelhouse", "version": version}
    return {"slug": "widget", "enabled": True, "source": source}


def _specs(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return _install_plugin_specs({"install": {"plugins": list(entries)}})


class TestTheTwoSpellingsAgree:
    """TAP-KNOWN-DUPE(boot-source-input-patterns) — the reason this duplicate is tolerable."""

    @pytest.mark.parametrize(("index", "field", "constant"), PAIRS)
    def test_schema_pattern_matches_the_python_constant(self, index, field, constant) -> None:
        branch = _source_branch(index)
        assert branch["properties"]["type"]["const"] in {"git", "wheelhouse"}
        assert branch["properties"][field]["pattern"] == f"^{constant}$"


class TestGitUrl:
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("https://github.com/unified-systems-com/tap-plugin-aws-core", id="github"),
            pytest.param("https://codeberg.org/someone/tap-plugin-x.git", id="another-forge"),
            pytest.param("https://git.internal.example:8443/group/sub/tap-plugin-x", id="self-hosted-port"),
            pytest.param("ssh://git@gitlab.example.com/group/tap-plugin-x.git", id="ssh-with-user"),
            pytest.param("ssh://forge.example/tap-plugin-x", id="ssh-no-user"),
        ],
    )
    def test_https_and_ssh_on_any_host_pass(self, url) -> None:
        assert [e["slug"] for e in _specs(_git(url=url))] == ["widget"]

    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("http://github.com/org/x", id="plaintext-http"),
            pytest.param("file:///tmp/r", id="file-bypasses-path-allowlist"),
            pytest.param("ext::sh -c touch% /tmp/pwned", id="ext-transport"),
            pytest.param("git://github.com/org/x", id="git-protocol"),
            pytest.param("github.com/org/x", id="schemeless"),
            pytest.param("git@github.com:org/x.git", id="scp-style"),
            pytest.param("HTTPS://github.com/org/x", id="uppercase-scheme-fails-closed"),
            pytest.param("https://", id="no-host"),
            pytest.param("ssh://-oProxyCommand=touch%20pwned/x", id="dash-host"),
            pytest.param("ssh://-l@host/x", id="dash-user"),
            pytest.param("https://github.com/org/x y", id="space"),
            pytest.param("https://github.com/org/x\n", id="trailing-newline"),
            pytest.param("https://github.com/org/x\x00", id="nul"),
            pytest.param("", id="empty"),
        ],
    )
    def test_everything_else_aborts(self, url) -> None:
        with pytest.raises(PrebootError, match=r"source\.url"):
            _specs(_git(url=url))

    def test_a_rejected_url_is_not_echoed_whole(self) -> None:
        """The message reaches the log stream; a malformed URL may still carry a token."""
        with pytest.raises(PrebootError) as excinfo:
            _specs(_git(url="http://user:s3cr3t-token@forge.example/x"))
        assert "s3cr3t-token" not in str(excinfo.value)
        assert "'http'" in str(excinfo.value)

    @pytest.mark.parametrize("value", [None, 7, ["https://x/y"]], ids=["missing", "int", "list"])
    def test_non_string_aborts(self, value) -> None:
        entry = _git()
        if value is None:
            del entry["source"]["url"]
        else:
            entry["source"]["url"] = value
        with pytest.raises(PrebootError, match=r"source\.url"):
            _specs(entry)


class TestGitRev:
    @pytest.mark.parametrize(
        "rev",
        ["v0.3.1", "0123456789abcdef0123456789abcdef01234567", "abc123", "refs/tags/v1", "release/2026-09"],
    )
    def test_tags_shas_and_refs_pass(self, rev) -> None:
        assert _specs(_git(rev=rev))

    @pytest.mark.parametrize(
        "rev",
        [
            pytest.param("--upload-pack=touch /tmp/pwned", id="long-option"),
            pytest.param("-c", id="short-option"),
            pytest.param("v1 --upload-pack=x", id="space"),
            pytest.param("v1\t", id="tab"),
            pytest.param("v1\n", id="trailing-newline"),
            pytest.param("v1\x7f", id="del"),
            pytest.param("", id="empty"),
        ],
    )
    def test_option_shaped_or_spaced_revs_abort(self, rev) -> None:
        with pytest.raises(PrebootError, match=r"source\.rev"):
            _specs(_git(rev=rev))


class TestWheelhouseVersion:
    @pytest.mark.parametrize("version", ["0.1.0", "1.0.0rc1", "2!1.0", "1.0+local.7", "1.0.post1.dev2"])
    def test_pep440_versions_pass(self, version) -> None:
        assert _specs(_wheelhouse(version))

    @pytest.mark.parametrize(
        "version",
        [
            pytest.param("1.0; python_version>'3'", id="marker"),
            pytest.param("1.0,>=0", id="widened-specifier"),
            pytest.param("1.0 --index-url https://evil", id="space"),
            pytest.param("-1.0", id="leading-dash"),
            pytest.param("", id="empty"),
        ],
    )
    def test_anything_that_could_widen_the_pin_aborts(self, version) -> None:
        with pytest.raises(PrebootError, match=r"source\.version"):
            _specs(_wheelhouse(version))


class TestScope:
    def test_a_disabled_entry_is_validated_too(self) -> None:
        with pytest.raises(PrebootError, match=r"source\.url"):
            _specs(_git(url="file:///tmp/r", enabled=False))

    def test_editable_and_path_sources_are_not_url_checked(self) -> None:
        """Positive control on scope: the check must not reach source types with no url/rev."""
        editable = {"slug": "widget", "enabled": True, "source": {"type": "editable", "path": "plugins/widget"}}
        assert _specs(editable)


class TestShippedProfilesConform:
    def test_every_committed_boot_profile_passes_preboot_and_the_schema(self) -> None:
        """The change must not outlaw a profile TAP actually ships — on either spelling."""
        profiles = sorted((REPO / "boot").glob("*.boot.json"))
        assert profiles, "no boot profiles found — this test would pass vacuously"
        schema = json.loads(SCHEMA.read_text())
        git_sources = 0
        for path in profiles:
            profile = json.loads(path.read_text())
            _install_plugin_specs(profile)
            jsonschema.validate(profile, schema)
            git_sources += sum(
                1 for p in (profile.get("install") or {}).get("plugins", []) if p["source"]["type"] == "git"
            )
        assert git_sources, "no git sources in shipped profiles — the url/rev checks were never exercised"
