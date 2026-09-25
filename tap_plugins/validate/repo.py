"""Repository-scope conformance checks — the plugin's SHELL, not its package.

Implements req-tap-plugin-validate-repo from spec-tap-plugin-validation.md.

Every other check in this package reads the *package*: the manifest, the declared surfaces,
the layout, the boot record. A plugin repository also carries a **shell** nothing checked at
all: the CI caller that invokes core's reusable lane, the pin on that caller, and the
CODEOWNERS file that names a human. Those are stated by the plugin standard and were
previously transcribed by hand from a prose skill once per repository, on creation day, with
nothing re-applying them afterwards — which is why four generations of the CI caller are live
across the fleet and no repository has a CODEOWNERS at all.

These checks ask a PROPERTY of the repository ("does this satisfy the standard?"), never the
stability of an artefact ("does this still match the template it was generated from?"). The
distinction decides the pin check in particular: a caller pinned to a full commit SHA that is
not the newest SHA is CONFORMANT — moving it forward is a dependency-update job, not a
conformance one. What fails is a pin that is not a pin: a tag or a branch.

Repo scope is **opt-in** (``validate_plugin(..., repo_scope=True)``, ``--repo``). The reusable
per-repo CI runs ``validate_plugin --strict`` on the repository root, so turning these checks
on by default would red every plugin repository's lane before anything had been measured or
repaired. Measure first (req-tap-plugin-validate-repo-5).
"""

from __future__ import annotations

import re
from pathlib import Path

from tap_plugins.validate.service import CheckResult, ValidationResult

#: Every reusable workflow core publishes lives under this prefix. The pin rule is about the
#: prefix, not about one file: `plugin-release-sbom.yml` decides what gets attested and signed,
#: so an unpinned call of it is the same defect as an unpinned `plugin-ci.yml`.
REUSABLE_PREFIX = "unified-systems-com/tap/.github/workflows/"

#: The reusable workflow a plugin repository's own CI is a thin caller of
#: (req-tap-plugin-extdev-repo-ci).
REUSABLE_CALLER = REUSABLE_PREFIX + "plugin-ci.yml"

#: The three paths GitHub itself recognises a CODEOWNERS file at, in its own precedence order.
CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")

#: The push/PR lane: the admission gate (conformance + boot-and-test) every plugin must have.
CI_WORKFLOW = ".github/workflows/ci.yml"

#: The scheduled lane that probes the ceiling of the declared `requires_tap` range against
#: core `main` — C2's instrument, not its gate.
NIGHTLY_WORKFLOW = ".github/workflows/nightly.yml"

_WORKFLOW_DIR = ".github/workflows"
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*[\"']?(?P<ref>[^\s\"'#]+)")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def run_repo_checks(repo_root: Path, result: ValidationResult) -> None:
    """Append the repository-scope checks to *result*.

    TAP-IMPLEMENTS: req-tap-plugin-validate-repo@b0b187d2d33a/77709e9ce6b2 (derivation) — the
        repository-scope check set is dispatched here, opt-in, against the repository root the
        caller names.
    """
    _check_codeowners(repo_root, result)
    _check_workflows(repo_root, result)
    _check_caller_pin(repo_root, result)


# ---------------------------------------------------------------------------
# CODEOWNERS
# ---------------------------------------------------------------------------


def _codeowners_rules(text: str) -> list[str]:
    """Return the rule lines of a CODEOWNERS file — a pattern followed by at least one owner.

    A file of nothing but comments claims ownership and provides none, which is why presence
    alone is not the test.
    """
    rules: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) >= 2 and any(f.startswith("@") or "@" in f for f in fields[1:]):
            rules.append(line)
    return rules


def _check_codeowners(repo_root: Path, result: ValidationResult) -> None:
    """Does the repository name a human owner?  A WARNING when absent, deliberately.

    Commandment C4 of the plugin standard ("every plugin names a human owner") is
    **deliberately unmet** for now: CODEOWNERS is optional under the current policy, to be set once
    a plugin is sensitive enough to warrant the forced-review step it brings. So an absent file is reported and
    not failed, and this check must not be "fixed" into an error without that ruling changing.

    A file that EXISTS is held to correctness rather than presence: one with no rule line names
    nobody while looking like it does, and that is a failure under either ruling.
    """
    check = CheckResult(id="repo-codeowners", name="Repository names a human owner (CODEOWNERS)")
    found = [rel for rel in CODEOWNERS_LOCATIONS if (repo_root / rel).is_file()]

    if not found:
        check.warn(
            "no CODEOWNERS file at "
            + ", ".join(CODEOWNERS_LOCATIONS)
            + " — nothing names a human reviewer for this plugin, so a change to it can merge "
            "with no owner in the loop (plugin standard C4). Optional in the current ruling: "
            "set one once the plugin is sensitive enough to warrant the forced review"
        )
        result.checks.append(check)
        return

    check.details = {"locations": found}
    for rel in found:
        rules = _codeowners_rules((repo_root / rel).read_text(encoding="utf-8", errors="replace"))
        if not rules:
            check.fail(
                f"{rel} exists but declares no owner rule (a pattern followed by at least one "
                "@owner) — an empty CODEOWNERS reads as ownership and enforces none",
                path=rel,
            )
        else:
            check.info(f"{rel} declares {len(rules)} owner rule(s)", path=rel)
    result.checks.append(check)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def _check_workflows(repo_root: Path, result: ValidationResult) -> None:
    """Do the two lanes the standard names actually exist in this repository?

    ``ci.yml`` is the admission gate — conformance plus boot-and-test against the declared
    floor — so its absence is a failure: nothing proves this plugin loads, and a repository
    with no lane is green by having no lane at all.

    ``nightly.yml`` probes the CEILING of the declared ``requires_tap`` range against core
    ``main``, which is what keeps that range honest. **The per-repo lane is the only thing that
    BOOTS the plugin against ``main``**: core's own ``nightly-plugins.yml`` discovers every
    plugin repository at run time, but what it runs there is the conformance gate
    (``validate_plugin --strict``) — no boot, no plugin test suite. So a repository without a
    ``nightly.yml`` is not unwatched, and it is also not covered: nothing stands the plugin up
    against tomorrow's core.

    Two drafts of this message were wrong in opposite directions, which is why it is spelled out
    here. The first said "nothing probes core `main`", ignoring the central conformance sweep.
    The second leaned on that sweep hard enough to read as reassurance, and the central lane is
    the half that is shrinking, not the half to lean on.

    A WARNING rather than a failure only because the fleet is not repaired yet — eight
    repositories have no ``nightly.yml`` today. **This is a ratchet: it becomes a failure once
    they carry one**, the same measure-first-then-enforce shape as the repo scope being opt-in.
    What is still genuinely unruled is not whether the lane should exist but who receives its
    red when the plugin author cannot fix it (``tap#367``), which a nightly-shape check would
    settle by requiring the owner-issue job.
    """
    check = CheckResult(id="repo-workflows", name="Repository carries the CI lanes the standard names")
    present: list[str] = []

    for rel, missing in (
        (CI_WORKFLOW, "fail"),
        (NIGHTLY_WORKFLOW, "warn"),
    ):
        if (repo_root / rel).is_file():
            present.append(rel)
            continue
        if missing == "fail":
            check.fail(
                f"no {rel} — this repository calls no CI lane, so nothing proves the plugin is "
                "well-formed or that it boots against the core it claims "
                "(req-tap-plugin-extdev-repo-ci)",
                path=rel,
            )
        else:
            check.warn(
                f"no {rel} — nothing boots this plugin against core `main` on a clock, so the upper "
                "bound of its declared requires_tap range is only tested by an adopter (plugin "
                "standard C2). Core's nightly-plugins.yml does discover this repository, but what "
                "it runs there is the conformance gate only — no boot, no test suite. A warning "
                "rather than a failure while the fleet is unrepaired; it ratchets to a failure once "
                "every plugin repository carries this lane",
                path=rel,
            )

    check.details = {"present": present}
    if present:
        check.info("lanes present: " + ", ".join(present))
    result.checks.append(check)


# ---------------------------------------------------------------------------
# The caller pin
# ---------------------------------------------------------------------------


def _iter_uses(text: str) -> list[tuple[int, str]]:
    """Every ``uses:`` reference in a workflow file, as ``(line number, reference)``.

    Line-based on purpose: PyYAML is a test-tier dependency, and the ``structure`` level must
    run in a bare checkout with nothing but core installed. Comment lines are skipped so a
    commented-out or merely discussed pin is not read as a live one.
    """
    found: list[tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("#"):
            continue
        match = _USES_RE.match(raw)
        if match:
            found.append((lineno, match.group("ref")))
    return found


def _check_caller_pin(repo_root: Path, result: ValidationResult) -> None:
    """Is every call of a core-published reusable workflow pinned by a full commit SHA?

    ``@<ref>`` on a reusable workflow decides which of core's code runs in this repository, and
    a tag or branch is re-pointable by whoever controls it: a name is not a pin (plugin standard
    C7, req-tap-plugin-extdev-repo-ci-9). A 40-character commit SHA is; whether it is the NEWEST
    SHA is a different question this check deliberately does not ask.

    The rule covers EVERY workflow under ``REUSABLE_PREFIX``, not just ``plugin-ci.yml``. The
    first version checked only the CI caller and therefore missed
    ``plugin-release-sbom.yml@main`` sitting beside it in the same repository — the release-side
    workflow that produces the SBOM and the attestations, where an unpinned call matters more
    rather than less. ``tap#376``'s done-test says the same thing: no plugin repository
    references a ``@main`` reusable workflow at all.

    A repository whose ``ci.yml`` calls ``plugin-ci.yml`` nowhere fails: the alternative is a
    hand-rolled lane, which is the drift the reusable workflow exists to remove.
    """
    check = CheckResult(
        id="repo-ci-caller-pin",
        name="Callers of core's reusable workflows are pinned by commit SHA, not by a name",
    )
    workflow_dir = repo_root / _WORKFLOW_DIR
    if not workflow_dir.is_dir():
        check.fail(
            f"no {_WORKFLOW_DIR}/ — there is no caller of core's reusable workflows to pin "
            "(req-tap-plugin-extdev-repo-ci)",
            path=_WORKFLOW_DIR,
        )
        result.checks.append(check)
        return

    callers: list[dict[str, object]] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        rel = path.relative_to(repo_root).as_posix()
        for lineno, ref in _iter_uses(path.read_text(encoding="utf-8", errors="replace")):
            target, _, pin = ref.partition("@")
            if not target.startswith(REUSABLE_PREFIX):
                continue
            workflow = target[len(REUSABLE_PREFIX) :]
            callers.append({"file": rel, "line": lineno, "workflow": workflow, "ref": pin})
            if not pin:
                check.fail(
                    f"{rel}:{lineno} calls {workflow} with no ref at all — an unpinned `uses:` "
                    "resolves to whatever the default branch holds at run time",
                    path=rel,
                )
            elif not _FULL_SHA_RE.match(pin):
                check.fail(
                    f"{rel}:{lineno} pins {workflow} to `{pin}`, which is a name, not a pin — a "
                    "tag or branch is re-pointable, so core's code that runs here is not the "
                    "code this repository reviewed. Use the 40-character commit SHA (plugin "
                    "standard C7, req-tap-plugin-extdev-repo-ci-9, tap#376)",
                    path=rel,
                )

    check.details = {"callers": callers}
    ci_callers = [c for c in callers if c["file"] == CI_WORKFLOW and c["workflow"] == "plugin-ci.yml"]
    if not ci_callers and (repo_root / CI_WORKFLOW).is_file():
        check.fail(
            f"{CI_WORKFLOW} does not call {REUSABLE_CALLER} — a hand-rolled lane is the drift "
            "the reusable workflow exists to remove, and it does not gain a check on the day "
            "core ships one",
            path=CI_WORKFLOW,
        )
    if callers:
        distinct = sorted({str(c["ref"]) for c in callers if c["ref"]})
        check.info(
            f"{len(callers)} call(s) of {len({c['workflow'] for c in callers})} core workflow(s) "
            f"across {len({c['file'] for c in callers})} file(s), pinned to {len(distinct)} "
            "distinct ref(s): " + ", ".join(r[:12] for r in distinct)
        )
    result.checks.append(check)
