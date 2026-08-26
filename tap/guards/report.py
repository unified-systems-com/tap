"""Generated Validation Map — the guards and declared surfaces describe themselves.

TAP-IMPLEMENTS: req-dev-validation-map@f6d80e37142a/ba46e4886a7b (derivation) — the generated
    Map is read off the guard set here; the hand-maintained table it replaced is retired.

This is the source-of-truth inversion: instead of a hand-maintained prose table in
`spec-dev-validation.md`, the live guard set *is* the record for guarded surfaces,
and `tap.guards.surfaces.DECLARED_SURFACES` carries the negative space (behavioral
suites, gates, manual/deferred procedures). `render_map_markdown()` derives the Map
table from both, so the committed table cannot drift from the code — a meta-test
(`test_spec_map_in_sync`) asserts the spec block equals this output, and
`manage.py guards --sync-map` regenerates it.

`build_report()` additionally enumerates every registered `Guard` with the metadata
each carries (slug, map_row, rid, cadence, status, description, defining module) and,
optionally, a live `check()` pass/fail — so `manage.py guards --check` shows measured
status, not a typed-in claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from tap.guards.base import REPO_ROOT, Guard, defined_requirement_rids
from tap.guards.callsite import CallsiteRatchet
from tap.guards.discovery import discover_guards
from tap.guards.surfaces import DECLARED_SURFACES
from tap.ratchet import read_baseline_set
from tap.source_scan import CallsiteIdentity

# Markers delimiting the generated Map block inside spec-dev-validation.md. The text
# between them is owned by `render_map_markdown()`; edits belong in the guards /
# DECLARED_SURFACES, then `manage.py guards --sync-map`.
MAP_BEGIN = "<!-- BEGIN GENERATED MAP — manage.py guards --sync-map -->"
MAP_END = "<!-- END GENERATED MAP -->"


@dataclass(frozen=True)
class GuardRow:
    """One guard, as it describes itself. `passed`/`error` are None unless checks ran."""

    slug: str
    map_row: str
    rid: str
    cadence: str
    status: str
    module: str
    description: str
    rid_resolves: bool
    passed: bool | None
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "map_row": self.map_row,
            "rid": self.rid,
            "cadence": self.cadence,
            "status": self.status,
            "module": self.module,
            "rid_resolves": self.rid_resolves,
            "passed": self.passed,
            "error": self.error,
            "description": self.description,
        }


def build_report(*, run_checks: bool = False) -> list[GuardRow]:
    """Every registered guard as a `GuardRow`, sorted by slug.

    Args:
        run_checks: when True, run each guard's `check()` and record whether it
            passed (and the assertion message if not). Some checks are slow
            (collection-completeness forks pytest; mypy runs the type checker), so
            this is opt-in.
    """
    defined = defined_requirement_rids()
    rows: list[GuardRow] = []
    for guard in discover_guards():
        passed: bool | None = None
        error: str | None = None
        if run_checks:
            try:
                guard.check()
                passed = True
            except AssertionError as exc:
                passed = False
                error = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        rows.append(
            GuardRow(
                slug=guard.slug,
                map_row=guard.map_row,
                rid=guard.rid,
                cadence=guard.cadence,
                status=guard.status,
                module=type(guard).__module__,
                description=guard.description,
                rid_resolves=guard.rid in defined,
                passed=passed,
                error=error,
            )
        )
    return sorted(rows, key=lambda r: r.slug)


@dataclass(frozen=True)
class MapRow:
    """One Validation Map inventory row (a guarded surface or a declared surface)."""

    surface: str
    rid: str
    cadence: str
    status: str
    enforced_by: str


def _guard_map_rows() -> list[MapRow]:
    """Guards grouped by `map_row` — one inventory row per surface.

    Several guards can protect one surface (three log-site guards, two collection
    guards); they share rid/cadence/status, so the group collapses to a single row
    whose "Enforced by" lists each defining module.
    """
    by_surface: dict[str, list[Guard]] = {}
    for guard in discover_guards():
        by_surface.setdefault(guard.map_row, []).append(guard)

    rows: list[MapRow] = []
    for surface, guards in by_surface.items():
        first = guards[0]
        modules = sorted({f"`{type(g).__module__}`" for g in guards})
        rows.append(
            MapRow(
                surface=surface,
                rid=first.rid,
                cadence=first.cadence,
                status=first.status,
                enforced_by=", ".join(modules) + " (via `tap/tests/test_guards.py`)",
            )
        )
    return rows


def map_rows() -> list[MapRow]:
    """The full Map: guarded surfaces (from the guards) ∪ declared surfaces, sorted by name."""
    rows = _guard_map_rows()
    rows += [
        MapRow(
            surface=s.surface,
            rid=s.rid,
            cadence=s.cadence,
            status=s.status,
            enforced_by=s.enforced_by,
        )
        for s in DECLARED_SURFACES
    ]
    return sorted(rows, key=lambda r: r.surface.lower())


def render_map_markdown() -> str:
    """The generated Map table, wrapped in the BEGIN/END markers (no trailing newline)."""
    header = "| Surface | Requirement | Cadence | Status | Enforced by |\n" "| --- | --- | --- | --- | --- |"
    lines = [f"| {r.surface} | `{r.rid}` | {r.cadence} | {r.status} | {r.enforced_by} |" for r in map_rows()]
    return "\n".join([MAP_BEGIN, "", header, *lines, "", MAP_END])


# --- SARIF export (spec-tap-callsite-identity) -------------------------------
#
# A *view* over the callsite ratchets' per-occurrence findings, not a canonical
# store: `manage.py guards --sarif` renders it on demand. Only `CallsiteRatchet`
# guards feed it — they are the ones that carry per-offense addressability
# (`collect()` yields one `CallsiteIdentity` per physical offense). Aggregate/
# string-only guards (mypy) and plain structural guards have no per-offense stream
# and are deliberately absent from this surface; that omission is honest, not a gap
# (`spec-tap-callsite-identity`, Scope). Baselined debt is emitted as a *suppressed*
# result so the SARIF carries the full known-debt inventory, matching how GitHub code
# scanning distinguishes an active alert from an accepted one.

_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json"
_SARIF_VERSION = "2.1.0"
_TOOL_NAME = "TAP Guards"
_TOOL_INFORMATION_URI = "https://example.invalid/tap/spec-tap-callsite-identity"
#: Fingerprint namespace — matches the anchor/occurrence_key model, so a conformant
#: TAP finding correlates across runs (and drops into GitHub code scanning) unchanged.
_FINGERPRINT_KEY = "tapCallsite/v1"


def _split_anchor(anchor: str) -> tuple[str, str, str]:
    """`path::qualname::construct` → its three parts (qualname/construct empty if absent).

    The anchor's first field is already the repo-relative POSIX path, and qualname
    uses `.` while the path uses `/`, so a plain `::` split is unambiguous. A
    malformed anchor degrades gracefully rather than raising in an export path.
    """
    parts = anchor.split("::")
    if len(parts) >= 3:
        return parts[0], parts[1], "::".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], "", ""


def _sarif_result(
    *, identity: CallsiteIdentity, rule_id: str, rule_index: int, surface: str, suppressed: bool, baseline_display: str
) -> dict[str, object]:
    """One SARIF result per physical offense, mapped per the spec's field table."""
    anchor_path, qualname, construct = _split_anchor(identity.anchor)
    try:
        uri = identity.location.path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        uri = identity.location.path.as_posix()

    physical: dict[str, object] = {
        "artifactLocation": {"uri": uri},
        "region": {"startLine": identity.location.lineno},
    }
    location: dict[str, object] = {"physicalLocation": physical}
    if qualname:
        location["logicalLocations"] = [{"fullyQualifiedName": qualname, "kind": "function"}]

    detail = f"`{construct}` in `{qualname or '<module>'}`"
    result: dict[str, object] = {
        "ruleId": rule_id,
        "ruleIndex": rule_index,
        "level": "error",
        "message": {"text": f"{surface}: {detail}."},
        "locations": [location],
        # The discriminator is part of the fingerprint (e.g. `…#<hash>~2`), so two
        # offenses at one anchor do NOT dedupe into a single result.
        "partialFingerprints": {_FINGERPRINT_KEY: identity.occurrence_key},
        "properties": {"anchor": identity.anchor, "suppressed": suppressed},
    }
    if suppressed:
        # Baselined debt: an accepted, tracked finding — not an active alert.
        result["suppressions"] = [{"kind": "external", "justification": f"Baselined debt in {baseline_display}."}]
    return result


def render_sarif(guards: list[Guard] | None = None) -> dict[str, object]:
    """A SARIF 2.1.0 log of the callsite ratchets' per-occurrence findings.

    Iterates the `CallsiteRatchet` guards, emitting one rule each and one result per
    `collect()` occurrence. A finding whose baseline key is in the committed baseline
    is emitted *suppressed* (accepted debt); a finding not in the baseline is an
    active `error`. Returns a plain dict the caller serializes (the command
    `json.dumps`-es it). `guards` is injectable for testing; it defaults to the full
    discovered set.
    """
    pool = discover_guards() if guards is None else guards
    callsite_guards = [g for g in pool if isinstance(g, CallsiteRatchet)]

    rules: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for index, guard in enumerate(callsite_guards):
        rules.append(
            {
                "id": guard.slug,
                "name": guard.map_row,
                "shortDescription": {"text": guard.map_row},
                "fullDescription": {"text": guard.description},
                "defaultConfiguration": {"level": "error"},
                "properties": {"rid": guard.rid, "remediationUnit": guard.remediation_unit.value},
            }
        )
        baseline = read_baseline_set(guard.baseline_path)
        try:
            baseline_display = guard.baseline_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            baseline_display = guard.baseline_path.as_posix()
        for identity in guard.collect():
            suppressed = guard.baseline_key(identity) in baseline
            results.append(
                _sarif_result(
                    identity=identity,
                    rule_id=guard.slug,
                    rule_index=index,
                    surface=guard.map_row,
                    suppressed=suppressed,
                    baseline_display=baseline_display,
                )
            )

    return {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": _TOOL_NAME,
                        "informationUri": _TOOL_INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
