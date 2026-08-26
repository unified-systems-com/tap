"""Base classes for TAP's development-time guards.

A *guard* is a build/CI-time check that asserts a structural invariant about the
source tree — every test file is collected, no secret-shaped file exists, every
privileged sink is gated, a ratcheting baseline hasn't regressed. Guards have **no
runtime consumer**: a booted TAP instance never queries them, so — unlike
collectors or node-types — they are deliberately NOT in a runtime registry and do
not register in `AppConfig.ready()`. Their only "registry" is subclass enumeration
evaluated at test time (`all_guards()`), which vanishes when the test process exits.

The base earns its place for two reasons, not persistence:

1. **Findability.** `all_guards()` enumerates every `Guard`, so a meta-test can run
   them uniformly *and* assert each declares a ``rid`` that resolves to a real
   requirement in some spec — the mechanical close on the "a guard emerged without
   being accounted for" failure (`spec-dev-validation.md` `req-dev-validation-map`).
   The inventory in the Validation Map is *generated* from the guard set (plus the
   declared non-guard surfaces in `tap.guards.surfaces`), so it can never drift from
   the code; the guard→requirement link is the authored, reviewed edge.
2. **Shared ratchet mechanics.** `CeilingRatchet` wraps the compare-and-report in
   `tap.ratchet` for the per-commit set-based ratchets, so a subclass writes only
   its bespoke `measure()`. The floor direction (`tap.ratchet.ratchet_floor`) has
   only a script-invoked consumer today (the ~10-15 min Gryphon branch-coverage
   run, which cannot measure in-process), so it stays a bare function the script
   calls — no `FloorRatchet` Guard subclass until a per-commit floor exists.

A concrete guard declares a non-empty ``slug`` (its stable id), ``map_row`` (the
human-readable surface name shown in the generated Map), ``rid`` (the requirement it
enforces — machine-checked to resolve), and ``cadence`` (when it runs), and
implements ``check()``. Base classes leave ``slug`` empty and are not enumerated.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import ClassVar

from tap.ratchet import ratchet_ceiling, read_baseline_set
from tap.spec_trace import load_corpus

# tap/guards/base.py → parents[2] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Every concrete Guard subclass, in definition order. Populated at import time
# (see tap/guards/__init__.py, which imports the guard modules); consumed only by
# tests. Not a runtime registry.
_GUARDS: list[type[Guard]] = []


class Guard(abc.ABC):
    """A development-time structural check. Subclasses implement `check()`."""

    #: Stable id (also the pytest parametrize id). Concrete guards MUST set it.
    slug: ClassVar[str] = ""
    #: Human-readable surface name shown in the generated Validation Map.
    map_row: ClassVar[str] = ""
    #: The requirement this guard enforces (e.g. "req-tap-auth-policy-9"). Required;
    #: machine-checked to resolve to a real requirement in some spec (the authored,
    #: reviewed edge that replaces the hand-maintained Map row).
    rid: ClassVar[str] = ""
    #: When the guard runs, in the Map's cadence vocabulary (e.g. "Per-commit (`pytest`)").
    cadence: ClassVar[str] = "Per-commit (`pytest`)"
    #: Honest guard-status label (Map vocabulary). Every harness guard runs per-commit
    #: via `tap/tests/test_guards.py`, so the default is CI-guarded; a guard that is
    #: *also* enforced elsewhere (e.g. the pre-push gate) may say so.
    status: ClassVar[str] = "CI-guarded"
    #: Why this guard exists — the failure it prevents, in the author's words. Required
    #: (enforced by the meta-test): a guard that cannot say why it is here is dead weight.
    #: A first-class field, not just a docstring, so the whole guard set is self-describing.
    description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Only concrete guards declare a slug in their own body; base classes
        # (Ratchet, CeilingRatchet, …) leave it empty and are not enumerated.
        if cls.__dict__.get("slug"):
            _GUARDS.append(cls)

    @abc.abstractmethod
    def check(self) -> None:
        """Assert the invariant; raise AssertionError (or a subclass) on violation."""


class CeilingRatchet(Guard):
    """A ceiling-to-zero ratchet: `measure()` must not grow past the baseline set."""

    #: Committed baseline file (line-per-entry; blanks/`#`-comments ignored).
    baseline_path: ClassVar[Path]
    #: Surface-specific guidance shown when a NEW item appears (the right fix first).
    new_hint: ClassVar[str] = ""

    @abc.abstractmethod
    def measure(self) -> set[str]:
        """Return the freshly measured set of flagged items (bespoke per surface)."""

    def check(self) -> None:
        ratchet_ceiling(
            current=self.measure(),
            baseline=read_baseline_set(self.baseline_path),
            surface=self.map_row,
            baseline_path=self.baseline_path,
            new_hint=self.new_hint,
        )


def all_guards() -> list[Guard]:
    """Every registered concrete guard, instantiated. Import-time cheap; `check()` does the work."""
    return [cls() for cls in _GUARDS]


def defined_requirement_rids() -> set[str]:
    """Every requirement RID *defined* across the specs (RID: heading or table-row cell).

    Used by the completeness meta-test to assert each guard's `rid` resolves — so a
    guard cannot ship pointing at a requirement that does not exist.

    A requirement is *defined* (not merely referenced) where it appears as an `RID:`
    heading line or as the first cell of a Markdown table row (the acceptance-criteria
    and requirements tables). Inline `(`req-...`)` references do NOT define it — that
    distinction is the whole point: the Map used to reference RIDs that were never
    actually specified (e.g. `req-dev-validation-mypy-ratchet`).

    The parse itself lives in `tap.spec_trace` (`req-docs-rid-integrity`), which owns the
    structured model — requirements, their ACIDs, statuses and content hashes. This stays
    the stable entry point its existing callers use, but derives its answer from that one
    parser instead of keeping a second regex pair that could drift from it.
    """
    return set(load_corpus(REPO_ROOT).defined)
