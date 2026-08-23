"""Secrets-root resolution single-source guard — `req-tap-cares-secrets-root-resolution`.

The `TAP_SECRETS_ROOT` env var has exactly two canonical lookups (settings.py
inside Django; `tap/secrets_root.py` outside), and each directory literal lives
exactly once (the container mount default in settings.py; the host home default
in boot_pointer). The 2026-08 derive-the-same-fact-twice audit found five inline
restatements of this resolution; this guard keeps the count at its floor so a
sixth cannot creep back in. Scan-style sibling of `secret_leak` (filesystem walk,
no git dependency); needles are assembled by concatenation so this module never
matches its own scan.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import is_excluded_dir

_ENV_NAME = "TAP_SECRETS" + "_ROOT"
# The common restatement forms of an env-var READ (drift prevention, not an
# adversarial scanner — an evasion via indirection is a review problem).
_ENV_READ_NEEDLES = (
    f'environ.get("{_ENV_NAME}"',
    f'environ["{_ENV_NAME}"]',
    f'getenv("{_ENV_NAME}"',
)
_CONTAINER_LITERAL = "/run/" + "tap-secrets"
_HOME_CONSTRUCTION = 'Path.home() / "' + "tap-secrets" + '"'

# path (repo-relative, POSIX) -> the needles it is sanctioned to contain.
_ALLOWED: dict[str, tuple[str, ...]] = {
    "tap/settings.py": (*_ENV_READ_NEEDLES, _CONTAINER_LITERAL),
    "tap/boot_pointer.py": (_HOME_CONSTRUCTION,),
}


def _python_files() -> list[str]:
    rels: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if is_excluded_dir(rel):
            continue
        if "tests" in parts:
            continue
        if path.is_file():
            rels.append(path.relative_to(REPO_ROOT).as_posix())
    return rels


class SecretsRootResolutionGuard(Guard):
    slug = "secrets-root-resolution"
    map_row = "Secrets-root resolution single source"
    rid = "req-tap-cares-secrets-root-resolution"
    description = (
        "Where credentials are read from must not be re-derived per entry point: the secrets-root env var "
        "is read in exactly two canonical places (settings.py in Django, tap/secrets_root.py outside) and "
        "each directory literal lives exactly once. This scans every non-test Python file for restatements "
        "so a divergent resolution path fails the build instead of drifting silently."
    )

    def check(self) -> None:
        needles = (*_ENV_READ_NEEDLES, _CONTAINER_LITERAL, _HOME_CONSTRUCTION)
        own_path = "tap/guards/secrets_root_resolution.py"
        violations: list[str] = []
        for rel in _python_files():
            if rel == own_path:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            allowed = _ALLOWED.get(rel, ())
            for needle in needles:
                if needle in text and needle not in allowed:
                    violations.append(f"{rel}: {needle!r}")
        assert not violations, (
            f"Secrets-root resolution restated outside the canonical homes ({len(violations)}):\n  "
            + "\n  ".join(violations)
            + "\n\nUse settings.TAP_SECRETS_ROOT inside Django or tap.secrets_root.resolve() outside "
            "(req-tap-cares-secrets-root-resolution)."
        )
