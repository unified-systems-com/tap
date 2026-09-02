"""The plugin slug alphabet is enforced, and its two spellings agree.

`tap/preboot.py` used to carry the alphabet in a COMMENT — "slug alphabet is
[a-z0-9_]" — while nothing checked it, and the value flowed straight from a boot
profile into subprocess argument lists, log records and distribution-name
derivation. SonarCloud's taint analysis traced every finding in that file to one
source: the `json.load` of the profile, carried by `slug`.

Pre-boot cannot use the JSON Schema (it runs before Django exists,
req-boot-preboot-1), and JSON Schema cannot read a Python constant, so the
alphabet is spelled in exactly two places — TAP-KNOWN-DUPE(plugin-slug-alphabet).
The first test here is what makes that duplicate safe: the pair is checked rather
than merely documented.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tap.plugin_identity import SLUG_ALPHABET_PATTERN, valid_slug
from tap.preboot import PrebootError, _install_plugin_specs, _population_seed_slugs

SCHEMA = Path(__file__).resolve().parents[2] / "tap_boot" / "schemas" / "boot.schema.json"

# Every field in boot.schema.json that carries a bare plugin slug. Deliberately
# EXCLUDES fips_waivers[].plugin: its contract also admits an fnmatch glob and a
# `dist:<name>` form, so the alphabet would break documented behaviour there. A field
# named for a slug is not necessarily a slug.
SLUG_SCHEMA_PATHS = [
    ("install", "properties", "plugins", "items", "properties", "slug"),
    ("population", "properties", "steps", "items", "oneOf", 0, "properties", "plugin"),
]


def _schema_node(path: tuple[object, ...]) -> dict[str, Any]:
    node: Any = json.loads(SCHEMA.read_text())["properties"]
    for key in path:
        node = node[key]
    assert isinstance(node, dict)
    return node


class TestTheTwoSpellingsAgree:
    """TAP-KNOWN-DUPE(plugin-slug-alphabet) — the reason this duplicate is tolerable."""

    @pytest.mark.parametrize("path", SLUG_SCHEMA_PATHS, ids=lambda p: p[0])
    def test_schema_pattern_matches_the_python_constant(self, path) -> None:
        assert _schema_node(path)["pattern"] == f"^{SLUG_ALPHABET_PATTERN}$"

    def test_the_paths_actually_resolve(self) -> None:
        """Scope check: a lookup that found nothing would pass every test above."""
        assert len(SLUG_SCHEMA_PATHS) == 2
        for path in SLUG_SCHEMA_PATHS:
            assert "pattern" in _schema_node(path)

    def test_fips_waiver_plugin_is_left_unconstrained_on_purpose(self) -> None:
        """Pins the exclusion, so re-adding it is a deliberate act and not a tidy-up."""
        node = json.loads(SCHEMA.read_text())["properties"]["fips_waivers"]["items"]
        assert "pattern" not in node["properties"]["plugin"]


class TestValidSlug:
    @pytest.mark.parametrize("slug", ["grid_fixtures", "aws_core", "a", "a1", "x_9_y"])
    def test_accepts_real_slugs(self, slug) -> None:
        assert valid_slug(slug)

    @pytest.mark.parametrize(
        "slug",
        [
            pytest.param("has-dash", id="dash"),
            pytest.param("Upper", id="uppercase"),
            pytest.param("with space", id="space"),
            pytest.param("dots.here", id="dot"),
            pytest.param("", id="empty"),
            pytest.param("../etc/passwd", id="traversal"),
            pytest.param("ok\nFORGED", id="newline"),
            pytest.param("ok\rFORGED", id="carriage-return"),
            pytest.param("ok\n", id="trailing-newline"),
            pytest.param(None, id="none"),
            pytest.param(123, id="not-a-string"),
        ],
    )
    def test_rejects_everything_else(self, slug) -> None:
        assert not valid_slug(slug)

    def test_trailing_newline_is_rejected(self) -> None:
        r"""Guards the `$`-vs-`\Z` trap: Python's `$` matches before a trailing newline,
        so a `$`-anchored pattern would accept exactly the injection payload."""
        assert not valid_slug("grid_fixtures\n")


class TestPrebootFailsClosed:
    def test_install_slug_with_a_newline_aborts(self) -> None:
        profile = {"install": {"plugins": [{"slug": "ok\n2026-01-01 CRITICAL forged", "enabled": True}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _install_plugin_specs(profile)

    def test_population_slug_with_a_newline_aborts(self) -> None:
        profile = {"population": {"steps": [{"type": "seed-plugin", "plugin": "ok\nforged", "enabled": True}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _population_seed_slugs(profile)

    def test_a_disabled_entry_is_validated_too(self) -> None:
        """A bad slug parked behind `enabled: false` must not wait to be discovered
        by whoever flips it on."""
        profile = {"install": {"plugins": [{"slug": "Bad-Slug", "enabled": False}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _install_plugin_specs(profile)

    def test_well_formed_profiles_are_unaffected(self) -> None:
        """Positive control: without this, deleting the readers would pass the suite."""
        install = {"install": {"plugins": [{"slug": "grid_fixtures", "enabled": True}]}}
        population = {"population": {"steps": [{"type": "seed-plugin", "plugin": "grid_fixtures", "enabled": True}]}}
        assert [e["slug"] for e in _install_plugin_specs(install)] == ["grid_fixtures"]
        assert _population_seed_slugs(population) == ["grid_fixtures"]


class TestShippedProfilesConform:
    def test_every_slug_in_every_committed_boot_profile_is_valid(self) -> None:
        """The change must not have outlawed a profile TAP actually ships."""
        boot_dir = Path(__file__).resolve().parents[2] / "boot"
        profiles = sorted(boot_dir.glob("*.boot.json"))
        assert profiles, "no boot profiles found — this test would pass vacuously"
        for path in profiles:
            profile = json.loads(path.read_text())
            _install_plugin_specs(profile)
            _population_seed_slugs(profile)


class TestSourcePathsAreAllowlisted:
    """`pythonsecurity:S6549` — the profile's source paths reach the filesystem.

    Every path-bearing source (`wheelhouse.dir`, `path.path`, `editable.path`) becomes a
    path `uv pip install` reads code from, so the value chooses WHICH WHEELS GET
    INSTALLED. It must resolve under REPO_ROOT or an allowed wheelhouse mount; everything
    else is refused.

    ALLOW BY EXCEPTION, after a denylist lost twice. The first version rejected `..`
    only, and review found a symlink escapes without one. The second added mount-root and
    secrets-store exclusions, and review found `/opt` passing on its own. The good set is
    two entries; the bad set is unbounded.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("../../etc", id="relative-traversal"),
            pytest.param("/run/../etc", id="absolute-traversal"),
            pytest.param("/", id="root"),
            pytest.param("/etc", id="outside-everything"),
            pytest.param("/run", id="mount-parent-of-the-allowed-root"),
            pytest.param("/opt", id="mount-root-not-allowed-at-all"),
            pytest.param("/run/tap-secrets", id="the-secrets-store"),
            pytest.param("", id="empty"),
        ],
    )
    def test_paths_outside_the_allowlist_abort(self, raw: str) -> None:
        profile = {
            "install": {
                "plugins": [
                    {"slug": "ok", "enabled": True, "source": {"type": "wheelhouse", "dir": raw, "version": "1"}}
                ]
            }
        }
        with pytest.raises(PrebootError):
            _install_plugin_specs(profile)

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("/run/tap-wheelhouse", id="the-mounted-wheelhouse"),
            pytest.param("/run/tap-wheelhouse/sub", id="below-it"),
            pytest.param("wheelhouse", id="repo-relative"),
            pytest.param("tap_plugins/tests/fixtures/validation_sample", id="the-one-real-shipped-path"),
        ],
    )
    def test_allowlisted_paths_pass(self, raw: str) -> None:
        """Positive control. Without it, refusing everything would satisfy every
        assertion above while making pre-boot unable to install anything."""
        profile = {
            "install": {
                "plugins": [
                    {"slug": "ok", "enabled": True, "source": {"type": "wheelhouse", "dir": raw, "version": "1"}}
                ]
            }
        }
        assert len(_install_plugin_specs(profile)) == 1

    def test_a_symlink_out_of_the_repo_is_refused(self) -> None:
        """`.resolve()` follows symlinks, so containment is checked against the real
        target — a repo-relative path with no `..` still cannot escape."""
        import os

        from tap.preboot import REPO_ROOT

        link = REPO_ROOT / "_tmp_escape_link"
        try:
            os.symlink("/etc", link)
        except OSError:
            pytest.skip("cannot create a symlink in the repo root here")
        try:
            profile = {
                "install": {
                    "plugins": [{"slug": "ok", "enabled": True, "source": {"type": "path", "path": "_tmp_escape_link"}}]
                }
            }
            with pytest.raises(PrebootError):
                _install_plugin_specs(profile)
        finally:
            link.unlink(missing_ok=True)

    def test_every_shipped_profile_still_loads(self) -> None:
        """The allowlist must not have outlawed a source TAP actually ships."""
        boot_dir = Path(__file__).resolve().parents[2] / "boot"
        profiles = sorted(boot_dir.glob("*.boot.json"))
        assert profiles, "no boot profiles found — this test would pass vacuously"
        for path in profiles:
            _install_plugin_specs(json.loads(path.read_text()))


class TestMalformedSourceFailsClosed:
    """A `source` that is not an object must abort, not skip the path check.

    Raised by Copilot on PR #280 against the validation added in the same PR. With
    `source: []`, `"dir" in source` is False and the path check is silently skipped;
    with `source: "..."` it becomes a SUBSTRING test and then raises TypeError on
    subscript. Pre-boot reads the profile without a schema by design, so an unexpected
    shape has to fail closed here — "cannot tell" is refused, not just "known bad".
    """

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param([], id="list"),
            pytest.param("../../etc", id="string"),
            pytest.param(7, id="number"),
            pytest.param(True, id="bool"),
        ],
    )
    def test_non_object_source_aborts(self, source: Any) -> None:
        profile = {"install": {"plugins": [{"slug": "ok", "enabled": True, "source": source}]}}
        with pytest.raises(PrebootError, match="expected an object"):
            _install_plugin_specs(profile)

    def test_absent_source_is_still_allowed(self) -> None:
        """Positive control: `source` is optional, and its absence is not malformed."""
        profile = {"install": {"plugins": [{"slug": "ok", "enabled": True}]}}
        assert len(_install_plugin_specs(profile)) == 1

    def test_a_symlinked_relative_path_cannot_escape(self, tmp_path: Any) -> None:
        """The `..` check alone was not enough — a symlink has no `..` in it.

        Raised by both Codacy and Copilot on PR #280: the relative branch returned
        early after only rejecting `..`, leaving the function's own stated rule ("a
        relative one stays under the repo") unverified.
        """
        import os

        from tap.preboot import REPO_ROOT

        link = REPO_ROOT / "_tmp_escape_link"
        try:
            os.symlink("/etc", link)
        except OSError:
            pytest.skip("cannot create a symlink in the repo root here")
        try:
            profile = {
                "install": {
                    "plugins": [{"slug": "ok", "enabled": True, "source": {"type": "path", "path": "_tmp_escape_link"}}]
                }
            }
            with pytest.raises(PrebootError):
                _install_plugin_specs(profile)
        finally:
            link.unlink(missing_ok=True)
