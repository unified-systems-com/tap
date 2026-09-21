"""Dev-passkey import-encapsulation guard — the zero-proof-of-possession bind stays in the shell.

`import_dev_admin` creates an admin and binds a WebAuthn credential with **no ceremony, no
attestation, and no challenge-response** — nothing proves the caller holds the private key.
Its entire trust basis is two guards (`spec-tap-auth-passkey-v0.md`
`req-tap-auth-passkey-dev-bootstrap`): the record's integrity, and the `dev_local` allowlist
that now runs *inside* the function (`req-…-dev-bootstrap-15`).

That makes the call safe. It does not make it safe *everywhere*. A gated call reachable from
a web view, an API router, a background task, or a plugin would be a privilege-escalation
surface on any dev instance — and dev instances hold real `~/tap-secrets` cloud credentials.
The affordance is deliberately shell-only: `manage.py` access already *is* the root of trust,
so a management command grants an attacker nothing they lack. A view does not.

This guard therefore fails the build if `import_dev_admin` is imported by any module outside
a small allowlist. It is the review-time layer of a three-layer defence — runtime
(`-15`, the gate inside the function), review-time (this, `-16`), and build-time
(`req-tap-auth-passkey-slim-install-7`, the dev-only commands shipping in a `dev` extra a
production build never installs). None is load-bearing alone; none is scaffolding for the
others.

Scope is deliberately **name-level**, not module-level: `dev_record` also exports harmless
public-record builders (`build_record_for_user`) that `export_dev_passkey` legitimately
imports. Precision over breadth — flag the dangerous name, and the module handle that would
reach it by attribute (`dev_record.import_dev_admin`).

DIY AST, stdlib-only, pre-boot — same shape as the other tree-scanners. Hard lint: no
baseline. There is no legitimate existing offender to grandfather.
"""

from __future__ import annotations

import ast

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots, iter_parsed_sources

# The module that defines the dangerous affordance, and the names that ARE it.
_DEV_RECORD_MODULE = "tap_auth.passkey.dev_record"
_DEV_RECORD_PARENT = "tap_auth.passkey"
_DEV_RECORD_ATTR = "dev_record"
_DANGEROUS_NAMES = frozenset({"import_dev_admin"})

# Repo-relative paths permitted to import the bind. Files, or directory prefixes ending "/".
#   * dev_record.py itself defines it;
#   * the two management commands are the shell root-of-trust surface;
#   * the test corpus must exercise the real function (and, since `-15`, exercises the real
#     gate along with it — a test can no longer route around the allowlist).
_ALLOWED = (
    "tap_auth/passkey/dev_record.py",
    "tap_auth/management/commands/enroll_admin.py",
    "tap_auth/management/commands/bootstrap_dev_passkey.py",
    "tap_auth/tests/",
)


def _is_allowed(rel: str) -> bool:
    return any(rel == entry or (entry.endswith("/") and rel.startswith(entry)) for entry in _ALLOWED)


def _offending_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Every import in `tree` that hands the caller `import_dev_admin`, by name or by module.

    Three reachable shapes:
      ``from tap_auth.passkey.dev_record import import_dev_admin``  → the name, directly
      ``import tap_auth.passkey.dev_record``                        → a module handle
      ``from tap_auth.passkey import dev_record``                   → a module handle

    A relative import (`level > 0`) can only occur inside `tap_auth.passkey` itself, which is
    the allowed internal case and is caught by the path allowlist anyway.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _DEV_RECORD_MODULE:
                    found.append((node.lineno, f"import {_DEV_RECORD_MODULE}"))
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if node.module == _DEV_RECORD_MODULE:
                for alias in node.names:
                    if alias.name in _DANGEROUS_NAMES:
                        found.append((node.lineno, f"from {_DEV_RECORD_MODULE} import {alias.name}"))
            elif node.module == _DEV_RECORD_PARENT:
                for alias in node.names:
                    if alias.name == _DEV_RECORD_ATTR:
                        found.append((node.lineno, f"from {_DEV_RECORD_PARENT} import {_DEV_RECORD_ATTR}"))
    return found


class DevPasskeyImportGuard(Guard):
    slug = "dev-passkey-import-encapsulation"
    map_row = "Dev passkey import stays shell-only"
    rid = "req-tap-auth-passkey-dev-bootstrap"
    description = (
        "`import_dev_admin` binds an admin credential with zero proof-of-possession. It is gated "
        "(dev_local allowlist, asserted inside the function), but a gated call reachable from a "
        "view, API router, task, or plugin would still be a privilege-escalation surface on a dev "
        "instance holding real cloud secrets. This guard fails the build if any module outside "
        "dev_record itself, the two sanctioned management commands, and the test corpus imports "
        "that name — or imports the module handle that would reach it by attribute."
    )

    def check(self) -> None:
        offenders: list[str] = []
        for parsed in iter_parsed_sources(first_party_source_roots(REPO_ROOT)):
            rel = parsed.path.relative_to(REPO_ROOT).as_posix()
            if _is_allowed(rel):
                continue
            for lineno, what in _offending_imports(parsed.tree):
                offenders.append(f"{rel}:{lineno} `{what}`")

        assert not offenders, (
            "Dev-passkey import-encapsulation violation(s): a module outside the sanctioned shell "
            "surface imports `import_dev_admin`, which binds an admin credential with no "
            "proof-of-possession (spec-tap-auth-passkey-v0.md req-tap-auth-passkey-dev-bootstrap-16). "
            "`manage.py` access is already the root of trust; a view is not. Drive the replay through "
            "`manage.py bootstrap_dev_passkey --import` instead.\n  - " + "\n  - ".join(sorted(offenders))
        )
