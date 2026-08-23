"""Credential-pattern leak guard — `req-tap-cares-secrets-credential-patterns`.

TAP-IMPLEMENTS: req-tap-cares-secrets-credential-patterns@6aa934d37ba7/8913d0f20022 (enforcement)
    — the pattern scan that fails raw credential material outside JSON surfaces.

The second half of source-control push-protection. Its sibling
`tap/guards/secret_leak.py` walks `*.json` for TAP's *secret envelope* — structural,
exact, and blind to anything that is not JSON. This one walks **every text file** for
credential shapes that identify themselves (`github_pat_…`, `AKIA…`, a PEM armor
header), so a token pasted into a `.py`, `.md`, `.sh`, `.yml` or `.env` — or a GitHub
App signing key dropped in as a `.pem` — is caught too. Neither `.gitignore`
(which globs `*.secret.json`) nor the envelope scan sees any of those.

The two guards are deliberately separate rather than merged: they have different
failure modes and different remedies. An envelope hit means "a TAP secret file is in
the tree, remove it"; a pattern hit means "a live credential is in a source file,
rotate it and rewrite the commit". Merging them would blur that in the failure output,
which is the moment it matters most.

Scan logic lives in :mod:`tap.credential_patterns` (import-safe, Django-free, shared
with `.githooks/pre-commit`); this is the enforcement surface — a filesystem walk,
matching the sibling scanners.
"""

from __future__ import annotations

from tap.credential_patterns import format_matches, scan_paths
from tap.guards.base import REPO_ROOT, Guard

# Dirs never walked. Superset of the envelope guard's list: this one reads *every*
# file rather than only `*.json`, so build/coverage output that can legitimately embed
# opaque high-entropy strings is excluded too. `tap_secrets` is the live off-grid
# mount (a gitignored symlink to the host store) and must never be scanned.
_EXCLUDE_DIRS = frozenset(
    {
        ".claude",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "htmlcov",
        "node_modules",
        "tap_secrets",
        "vendor",
    }
)


def _repo_text_files() -> list[str]:
    """Every candidate file in the tree, excluding vendored/cache dirs and the secrets mount.

    Binary files are not filtered here — `scan_paths` skips whatever fails to decode as
    UTF-8, which keeps the exclusion rule in one place instead of two.
    """
    rels: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if any(part in _EXCLUDE_DIRS for part in rel.parts):
            continue
        rels.append(str(rel))
    return rels


class SecretPatternGuard(Guard):
    slug = "secret-pattern"
    map_row = "Credential pattern leak guard"
    rid = "req-tap-cares-secrets-credential-patterns"
    description = (
        "The envelope leak guard reads only *.json, so a raw token pasted into a .py/.md/.sh/.yml/.env — or a "
        "PEM private key such as a GitHub App signing key — enters source control unseen by it and by "
        ".gitignore. This walks every text file for self-identifying credential shapes and fails the build, so "
        "a credential is caught before the repository is ever published."
    )

    def check(self) -> None:
        matches = scan_paths(REPO_ROOT, _repo_text_files())
        assert not matches, (
            f"Credential-shaped material found in the repository tree ({len(matches)}):\n"
            + format_matches(matches)
            + "\n\nTreat any real match as COMPROMISED: rotate the credential first, then remove it from the "
            "tree — and remember the commit still carries it, so rewriting history is required before this "
            "repository is ever made public. Secrets belong only in the mounted *.secret.json store (off-grid, "
            "gitignored). A documentation example or test vector that must show a real-looking token may carry "
            "the `TAP-CREDENTIAL-OK` marker on the same line (spec-tap-cares-secrets.md "
            "req-tap-cares-secrets-credential-patterns)."
        )
