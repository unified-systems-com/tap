"""Unit coverage for the credential-shape scanner — `req-tap-cares-secrets-credential-patterns`.

The whole-tree enforcement walk is `tap/guards/secret_pattern.py::SecretPatternGuard`,
run via `tap/tests/test_guards.py`; this file pins the pure scan behaviour.

**Every synthetic token here is assembled at runtime rather than written as a literal.**
This file is itself inside the tree the guard walks, so a literal `github_pat_…` in a
test would be a real match and would fail the guard it is testing. Concatenation keeps
the source text clean while the scanner still sees a fully-formed token — which also
demonstrates the property under test: the patterns match *shapes*, not source lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.credential_patterns import (
    ALLOW_MARKER,
    CREDENTIAL_PATTERNS,
    format_matches,
    scan_paths,
    scan_text,
)

# Assembled so no literal credential shape appears in this file (see module docstring).
FAKE_GITHUB_PAT = "github_pat_" + "1A" * 22
FAKE_GITHUB_CLASSIC = "ghp_" + "b2" * 20
FAKE_AWS_KEY_ID = "AKIA" + "Q7ZX" * 4
FAKE_SLACK = "xox" + "b-" + "1234567890-abcdefghij"
FAKE_GOOGLE = "AIza" + "C3" * 17 + "x"
FAKE_PEM_HEADER = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
FAKE_OPENAI = "sk-" + "proj-" + "Ab1" * 15
FAKE_XAI = "xai-" + "Zx9" * 15


class TestPatternDetection:
    """Each supported credential shape is recognized."""

    @pytest.mark.parametrize(
        ("token", "expected_pattern"),
        [
            (FAKE_GITHUB_PAT, "github-fine-grained-pat"),
            (FAKE_GITHUB_CLASSIC, "github-token"),
            (FAKE_AWS_KEY_ID, "aws-access-key-id"),
            (FAKE_SLACK, "slack-token"),
            (FAKE_GOOGLE, "google-api-key"),
            (FAKE_PEM_HEADER, "private-key-block"),
            (FAKE_OPENAI, "openai-api-key"),
            (FAKE_XAI, "xai-api-key"),
        ],
    )
    def test_shape_is_detected(self, token: str, expected_pattern: str) -> None:
        matches = scan_text(f"token = {token}\n")
        assert matches, f"{expected_pattern} not detected"
        assert matches[0].pattern == expected_pattern

    def test_detects_inside_any_file_type(self) -> None:
        """The point of this guard: shapes are found in prose and shell, not just JSON."""
        markdown = f"Paste your token:\n\n    export TOKEN={FAKE_GITHUB_PAT}\n"
        assert len(scan_text(markdown)) == 1

    def test_reports_line_number(self) -> None:
        matches = scan_text(f"line one\nline two\nkey={FAKE_AWS_KEY_ID}\n")
        assert matches[0].line == 3

    def test_multiple_matches_on_separate_lines(self) -> None:
        matches = scan_text(f"a={FAKE_GITHUB_PAT}\nb={FAKE_AWS_KEY_ID}\n")
        assert {m.pattern for m in matches} == {"github-fine-grained-pat", "aws-access-key-id"}


class TestFalsePositiveResistance:
    """Prose that *names* a credential kind must not match — the hard-zero precondition."""

    @pytest.mark.parametrize(
        "text",
        [
            'GITHUB_PAT_KIND = "github_pat"',  # the real constant in tap/plugin_source_auth.py
            "The credential kind is github_pat, a fine-grained PAT.",
            "Set an AKIA-style access key id in the profile.",
            "See the ghp_ prefix used by classic tokens.",
            "-----BEGIN CERTIFICATE-----",  # public material, not a private key
            "-----BEGIN PUBLIC KEY-----",
            "Restricted sk-proj- style keys are minted per project.",
            "the xai- prefix marks Grok reviewer-seat keys",
            "uses: tarmojussila/xai-code-review",  # action name, not a key
        ],
    )
    def test_prose_does_not_match(self, text: str) -> None:
        assert scan_text(text) == []

    def test_short_lookalike_does_not_match(self) -> None:
        """Length floors matter: a truncated shape is not a credential."""
        assert scan_text("github_pat_tooshort") == []
        assert scan_text("AKIA123") == []
        assert scan_text("sk-proj-tooshort") == []
        assert scan_text("xai-tooshort") == []

    def test_high_entropy_identifier_does_not_match(self) -> None:
        """The FP class that made entropy scanning unusable here (13/13 on real history)."""
        assert scan_text('"OriginAccessControlId": "E2QWRUHAPOMQZL"') == []
        assert scan_text('monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "s3cret-pw-xyz")') == []


class TestExemptionMarker:
    """The narrow, review-visible escape hatch."""

    def test_marked_line_is_skipped(self) -> None:
        assert scan_text(f"example = {FAKE_GITHUB_PAT}  # {ALLOW_MARKER}") == []

    def test_marker_does_not_leak_to_other_lines(self) -> None:
        text = f"safe = 1  # {ALLOW_MARKER}\nunsafe = {FAKE_GITHUB_PAT}\n"
        matches = scan_text(text)
        assert len(matches) == 1
        assert matches[0].line == 2


class TestMasking:
    """Failure output is itself a disclosure surface (req-...-credential-patterns-4)."""

    def test_excerpt_masks_the_body(self) -> None:
        excerpt = scan_text(f"t={FAKE_GITHUB_PAT}")[0].excerpt
        assert FAKE_GITHUB_PAT not in excerpt
        assert excerpt.startswith("github_pat")
        assert "masked" in excerpt

    def test_format_matches_never_prints_the_token(self) -> None:
        rendered = format_matches(scan_text(f"t={FAKE_GITHUB_PAT}", path="x.py"))
        assert FAKE_GITHUB_PAT not in rendered
        assert "x.py:1" in rendered


class TestScanPaths:
    """The path-walking wrapper both the guard and the pre-commit hook use."""

    def test_finds_match_in_file(self, tmp_path: Path) -> None:
        (tmp_path / "notes.md").write_text(f"token {FAKE_GITHUB_PAT}\n", encoding="utf-8")
        matches = scan_paths(tmp_path, ["notes.md"])
        assert len(matches) == 1
        assert matches[0].path == "notes.md"

    def test_binary_file_is_skipped_not_raised(self, tmp_path: Path) -> None:
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
        assert scan_paths(tmp_path, ["blob.bin"]) == []

    def test_missing_file_is_skipped_not_raised(self, tmp_path: Path) -> None:
        assert scan_paths(tmp_path, ["does-not-exist.txt"]) == []

    def test_clean_file_yields_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text('GITHUB_PAT_KIND = "github_pat"\n', encoding="utf-8")
        assert scan_paths(tmp_path, ["clean.py"]) == []


def test_every_pattern_has_a_description() -> None:
    """A pattern that cannot say what it detects is dead weight (mirrors the Guard rule)."""
    for pattern in CREDENTIAL_PATTERNS:
        assert pattern.name and pattern.description, f"pattern {pattern.name!r} is undocumented"
