"""The cold-boot gate's known-broken manifest is real, found, and well-formed.

Guards the honesty mechanism itself (req-dev-validation-known-broken): if the
gate's default manifest path is wrong, `_load_known_broken` silently treats the
missing file as strict/empty — so a stale entry would never be caught and the
manifest would ratchet nothing. That exact bug (a `parents[2]` off-by-one)
existed on build; this test makes it non-silent.

Pure (no DB): filesystem + parse only.
"""

from __future__ import annotations

import pytest

from tap_boot.management.commands.cold_boot_gate import KNOWN_BROKEN_PATH, Command

_VALID_STEP_IDS = {
    "schema:migrate",
    "schema:makemigrations",
    "profiles:resolve",
    "seed:boot-profile",
    "collector:cycle",
    "health",
}


def test_default_manifest_path_exists():
    """The default path resolves to a real committed file (catches the wrong-parent bug)."""
    assert KNOWN_BROKEN_PATH.exists(), (
        f"known-broken manifest not found at the gate's default path {KNOWN_BROKEN_PATH}. "
        f"A wrong path silently degrades the gate to strict mode and defeats the ratchet."
    )


def test_manifest_loads_and_is_well_formed():
    """The committed manifest parses and every entry is a valid {step, reason}."""
    broken = Command()._load_known_broken(KNOWN_BROKEN_PATH)
    assert isinstance(broken, dict)
    for step_id, reason in broken.items():
        assert step_id in _VALID_STEP_IDS, f"unknown gate step id in manifest: {step_id!r}"
        assert reason, f"manifest entry for {step_id!r} has an empty reason"


def test_missing_entry_fields_fail(tmp_path):
    """A malformed entry (missing step/reason) is rejected (req-dev-validation-known-broken-3)."""
    from django.core.management.base import CommandError

    bad = tmp_path / "bad.json"
    bad.write_text('{"entries": [{"step": "health"}]}')  # missing reason
    with pytest.raises(CommandError):
        Command()._load_known_broken(bad)


def test_gate_refuses_to_run_without_a_profile(monkeypatch):
    """No --profile and no TAP_BOOT_PROFILE is a loud refusal, never a guessed profile."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    monkeypatch.delenv("TAP_BOOT_PROFILE", raising=False)
    with pytest.raises(CommandError, match="needs a boot profile"):
        call_command("cold_boot_gate", profile="")


def test_skip_if_not_installable_keys_on_the_named_profile(monkeypatch):
    """--skip-if-not-installable asks about the profile the gate would boot, and names it."""
    import io

    from django.core.management import call_command

    asked: list[str] = []

    def not_installable(profile_id: str) -> bool:
        asked.append(profile_id)
        return False

    monkeypatch.setattr(Command, "_profile_installable", staticmethod(not_installable))
    out = io.StringIO()
    call_command("cold_boot_gate", "--profile", "core_ci", "--skip-if-not-installable", stdout=out)
    assert asked == ["core_ci"]
    assert "SKIPPED" in out.getvalue() and "`core_ci`" in out.getvalue()


def test_the_zero_plugin_profile_is_installable_everywhere():
    """The predicate is the shared install-awareness filter: `core` installs nothing, so it always passes."""
    assert Command._profile_installable("core")


def test_an_unknown_profile_is_refused_even_when_skipping_is_allowed():
    """--skip-if-not-installable must not turn a typo'd profile into a green skip."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="no boot profile 'does-not-exist'"):
        call_command("cold_boot_gate", "--profile", "does-not-exist", "--skip-if-not-installable")
