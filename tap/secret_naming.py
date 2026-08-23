"""How a secret file is recognised by name — the suffixes, spelled once.

TAP-IMPLEMENTS: req-tap-cares-secrets-files@9d010480f227/4e34811fd55f (derivation) — the one spelling
of the `*.secret.json` suffix and its non-secret `*.secret.example.json` counterpart;
every loader, leak scanner and stage-0 host tool reads them from here.

**Stdlib only, and it must stay that way.** Three callers with different runtime floors
share these two strings:

* ``tap.boot_pointer`` runs under bare ``python3`` during spawn, before the container
  (and therefore any venv) exists;
* ``.githooks/precommit_secret_scan.py`` runs on the developer's host, where there is no
  ``.venv`` in a session worktree at all;
* ``tap.runtime_secrets`` runs inside Django and reaches ``jsonschema`` via
  ``tap.jsonfiles`` — which is exactly why those two could not simply import each other.

The stdlib-only floor is machine-checked: ``test_stage0_credential_machinery_is_stdlib_only``
walks the transitive import graph of the host-runnable modules, so an import added here
that needs a venv package fails that test rather than breaking spawn or the pre-commit
hook on someone's laptop.

The example suffix is a strict extension of the secret suffix, so anything matching on
``SECRET_SUFFIX`` must exclude ``SECRET_EXAMPLE_SUFFIX`` to avoid treating a checked-in
template as a real credential.
"""

from __future__ import annotations

from typing import Final

SECRET_SUFFIX: Final[str] = ".secret.json"

# Explicit, non-secret template suffix. A `<key>.secret.example.json` is a
# committed placeholder, never a credential.
SECRET_EXAMPLE_SUFFIX: Final[str] = ".secret.example.json"
