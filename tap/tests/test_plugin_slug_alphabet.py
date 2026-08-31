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


def _schema_node(path):
    node = json.loads(SCHEMA.read_text())["properties"]
    for key in path:
        node = node[key]
    return node


class TestTheTwoSpellingsAgree:
    """TAP-KNOWN-DUPE(plugin-slug-alphabet) — the reason this duplicate is tolerable."""

    @pytest.mark.parametrize("path", SLUG_SCHEMA_PATHS, ids=lambda p: p[0])
    def test_schema_pattern_matches_the_python_constant(self, path):
        assert _schema_node(path)["pattern"] == f"^{SLUG_ALPHABET_PATTERN}$"

    def test_the_paths_actually_resolve(self):
        """Scope check: a lookup that found nothing would pass every test above."""
        assert len(SLUG_SCHEMA_PATHS) == 2
        for path in SLUG_SCHEMA_PATHS:
            assert "pattern" in _schema_node(path)

    def test_fips_waiver_plugin_is_left_unconstrained_on_purpose(self):
        """Pins the exclusion, so re-adding it is a deliberate act and not a tidy-up."""
        node = json.loads(SCHEMA.read_text())["properties"]["fips_waivers"]["items"]
        assert "pattern" not in node["properties"]["plugin"]


class TestValidSlug:
    @pytest.mark.parametrize("slug", ["grid_fixtures", "aws_core", "a", "a1", "x_9_y"])
    def test_accepts_real_slugs(self, slug):
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
    def test_rejects_everything_else(self, slug):
        assert not valid_slug(slug)

    def test_trailing_newline_is_rejected(self):
        r"""Guards the `$`-vs-`\Z` trap: Python's `$` matches before a trailing newline,
        so a `$`-anchored pattern would accept exactly the injection payload."""
        assert not valid_slug("grid_fixtures\n")


class TestPrebootFailsClosed:
    def test_install_slug_with_a_newline_aborts(self):
        profile = {"install": {"plugins": [{"slug": "ok\n2026-01-01 CRITICAL forged", "enabled": True}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _install_plugin_specs(profile)

    def test_population_slug_with_a_newline_aborts(self):
        profile = {"population": {"steps": [{"type": "seed-plugin", "plugin": "ok\nforged", "enabled": True}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _population_seed_slugs(profile)

    def test_a_disabled_entry_is_validated_too(self):
        """A bad slug parked behind `enabled: false` must not wait to be discovered
        by whoever flips it on."""
        profile = {"install": {"plugins": [{"slug": "Bad-Slug", "enabled": False}]}}
        with pytest.raises(PrebootError, match="not a valid plugin slug"):
            _install_plugin_specs(profile)

    def test_well_formed_profiles_are_unaffected(self):
        """Positive control: without this, deleting the readers would pass the suite."""
        install = {"install": {"plugins": [{"slug": "grid_fixtures", "enabled": True}]}}
        population = {"population": {"steps": [{"type": "seed-plugin", "plugin": "grid_fixtures", "enabled": True}]}}
        assert [e["slug"] for e in _install_plugin_specs(install)] == ["grid_fixtures"]
        assert _population_seed_slugs(population) == ["grid_fixtures"]


class TestShippedProfilesConform:
    def test_every_slug_in_every_committed_boot_profile_is_valid(self):
        """The change must not have outlawed a profile TAP actually ships."""
        boot_dir = Path(__file__).resolve().parents[2] / "boot"
        profiles = sorted(boot_dir.glob("*.boot.json"))
        assert profiles, "no boot profiles found — this test would pass vacuously"
        for path in profiles:
            profile = json.loads(path.read_text())
            _install_plugin_specs(profile)
            _population_seed_slugs(profile)
