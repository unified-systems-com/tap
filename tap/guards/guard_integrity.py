"""Guard-system integrity guard — the guards that guard the guards.

The rest of the harness protects TAP; this protects the harness. It is the in-repo
"loud" layer of `req-dev-validation-meta-integrity` (`spec-dev-validation.md`): it makes
two tampering moves fail fast rather than pass unnoticed.

1. **A guard was removed or renamed.** `guard_manifest.txt` is a committed floor of the
   guards that MUST exist; this asserts every manifest slug is still discovered. Removing
   a guard fails until its slug leaves the manifest — and the manifest is machinery
   (owned in `.github/CODEOWNERS`), so that removal is a reviewed act. This is independent
   of `test_spec_map_in_sync` (which also makes a removal loud), so a guard cannot be
   dropped even if the Map meta-test is itself the thing being disabled.

2. **A guard's `check()` was neutered to a no-op.** The Map row is unchanged when someone
   turns a `check()` into `pass` / `return` / `...` / `assert True`, so `test_spec_map_in_sync`
   cannot see it. This asserts no discovered guard has a trivial no-op body — the highest-value,
   non-redundant check here.

Ratchets neutered via `measure()` returning an empty set are NOT caught here, and do not
need to be: emptying `measure()` makes every baseline entry *stale*, which the ratchet's
own stale-entry tooth (`tap.ratchet.ratchet_ceiling`) already fails on. So triviality is
checked on `check()`, where the hard-lint guards (which have no baseline safety net) live.

This is defense-in-depth, not a wall: it makes tampering loud in-repo. Only the out-of-band
anchor (branch protection + required check + CODEOWNERS, `-2`) actually *blocks* — see the
named limits in the spec. The regress is honest: this guard is itself machinery, so weakening
*it* is a CODEOWNERS-gated change.

DIY AST + `inspect`, stdlib-only. Hard lint: no baseline.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import ClassVar

from tap.guards.base import Guard
from tap.ratchet import read_baseline_set

_MANIFEST_PATH = Path(__file__).resolve().parent / "guard_manifest.txt"


def _check_is_trivial(guard_cls: type[Guard]) -> bool:
    """True if `guard_cls.check` has a no-op body: only `pass` / `return [const]` / `...` /
    `assert True` (optionally after a docstring). A single *call*, a `raise`, a loop, or any
    multi-statement body does real work and is not trivial. Reads the resolved method, so a
    ratchet that inherits `CeilingRatchet.check` is measured on that (non-trivial) body."""
    try:
        source = textwrap.dedent(inspect.getsource(guard_cls.check))
    except OSError, TypeError:
        return False  # cannot read source — do not flag (these are first-party files)
    try:
        func = ast.parse(source).body[0]
    except SyntaxError, IndexError:
        return False
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False

    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # drop a leading docstring
    if not body:
        return True  # docstring-only / empty
    if len(body) != 1:
        return False  # more than one statement → does something

    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Return) and (stmt.value is None or isinstance(stmt.value, ast.Constant)):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
        return True
    if isinstance(stmt, ast.Assert) and isinstance(stmt.test, ast.Constant) and bool(stmt.test.value):
        return True
    return False


class GuardIntegrityGuard(Guard):
    slug = "guard-integrity"
    map_row = "Guard-system integrity"
    rid = "req-dev-validation-meta-integrity-3"
    description = (
        "Protects the harness itself: fails if a guard named in the committed floor "
        "(guard_manifest.txt) is no longer discovered (a removal/rename), or if any discovered "
        "guard's check() has been neutered to a no-op (pass/return/.../assert True) — which the "
        "Map-sync meta-test cannot see because the guard's row is unchanged. The in-repo loud "
        "layer of the meta-integrity contract; blocking is the out-of-band CODEOWNERS + branch "
        "protection layer."
    )
    manifest_path: ClassVar[Path] = _MANIFEST_PATH

    def check(self) -> None:
        from tap.guards import discover_guards

        guards = discover_guards()
        discovered = {g.slug for g in guards}
        manifest = read_baseline_set(self.manifest_path)

        missing = sorted(manifest - discovered)
        neutered = sorted(g.slug for g in guards if _check_is_trivial(type(g)))

        problems: list[str] = []
        if missing:
            problems.append(
                f"{len(missing)} manifest guard(s) no longer discovered (removed or renamed): "
                f"{', '.join(missing)}. If intentional, remove the slug(s) from "
                f"tap/guards/guard_manifest.txt — a CODEOWNERS-gated machinery change."
            )
        if neutered:
            problems.append(
                f"{len(neutered)} guard(s) have a trivial no-op check() (pass / return / ... / "
                f"assert True) — a disabled guard: {', '.join(neutered)}. Restore the real check."
            )

        assert not problems, (
            "Guard-system integrity violation(s) (spec-dev-validation.md "
            "req-dev-validation-meta-integrity-3):\n  - " + "\n  - ".join(problems)
        )
