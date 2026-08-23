"""Source-control secret-leak guard — `req-tap-cares-secrets-leak-guard`.

TAP-IMPLEMENTS: req-tap-cares-secrets-leak-guard@eba03dbd5e01/b54181788977 (enforcement) —
    the guard that fails secret-shaped files and secret-bearing JSON in the tree.

Push-protection beyond `.gitignore`: a real secret must never enter the repo,
whether committed as a `*.secret.json` (ignore bypassed via `git add -f`) or renamed
to dodge the suffix. The scan logic lives in `tap.runtime_secrets`; this is the
enforcement surface — a filesystem walk (no git dependency, runs in-container like
the sibling scanners), excluding vendored/cache dirs and the live `tap_secrets`
mount. The pure-scan unit tests stay in `tap/tests/test_secret_leak_scan.py`.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard

# Dirs never walked: vendored/cache trees plus `tap_secrets`, the live off-grid
# secrets mount (a gitignored symlink to the host store).
_EXCLUDE_DIRS = frozenset(
    {".venv", "node_modules", "__pycache__", ".git", ".claude", ".mypy_cache", ".pytest_cache", "vendor", "tap_secrets"}
)


def _repo_json_files() -> list[str]:
    rels: list[str] = []
    for path in REPO_ROOT.rglob("*.json"):
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.is_file():
            rels.append(str(path.relative_to(REPO_ROOT)))
    return rels


class SecretLeakGuard(Guard):
    slug = "secret-leak"
    map_row = "Secret leak guard"
    rid = "req-tap-cares-secrets-leak-guard"
    description = (
        "A real credential committed as a *.secret.json (ignore bypassed with -f) or renamed to dodge the "
        "suffix would leak into source control — .gitignore alone can't stop it. This walks the tree for "
        "secret envelopes and fails the commit, so a leaked credential is caught before it lands."
    )

    def check(self) -> None:
        from tap.runtime_secrets import scan_paths_for_secret_leaks

        leaks = scan_paths_for_secret_leaks(REPO_ROOT, _repo_json_files())
        assert not leaks, (
            f"Secret material found in the repository tree ({len(leaks)}):\n  "
            + "\n  ".join(f"{leak.path} — {leak.reason}" for leak in leaks)
            + "\n\nSecrets live only in the mounted *.secret.json store (off-grid, gitignored). Remove the "
            "file and rotate the credential (treat it as compromised). A non-secret placeholder may use the "
            "*.secret.example.json suffix (spec-tap-cares-secrets.md req-tap-cares-secrets-leak-guard)."
        )
