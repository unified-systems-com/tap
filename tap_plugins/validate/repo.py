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
from typing import Any

from tap_plugins.validate.service import CheckResult, ValidationResult

#: Every reusable workflow core publishes lives under this prefix. The pin rule is about the
#: prefix, not about one file: `plugin-release-sbom.yml` decides what gets attested and signed,
#: so an unpinned call of it is the same defect as an unpinned `plugin-ci.yml`.
REUSABLE_PREFIX = "unified-systems-com/tap/.github/workflows/"

#: The reusable workflow a plugin repository's own CI is a thin caller of
#: (req-tap-plugin-extdev-repo-ci).
REUSABLE_CALLER = REUSABLE_PREFIX + "plugin-ci.yml"

#: The reusable NIGHTLY core publishes (`tap#367`). A repository calling this inherits the
#: ceiling probe AND the owner-issue job, so the nightly-shape rules below are satisfied by
#: construction — there is no per-repo script left to get wrong, which is the entire point of
#: the file. A repository still calling `plugin-ci.yml` directly from its nightly is the older,
#: hand-written shape and is checked line by line.
REUSABLE_NIGHTLY = REUSABLE_PREFIX + "plugin-nightly.yml"

#: The three paths GitHub recognises a CODEOWNERS file at, in GitHub's documented precedence
#: order: the FIRST of these that exists is the one consulted and the others are ignored. The
#: order is taken from GitHub's documentation, not verified by this checker, which is why the
#: check reports an ignored-but-ruleless file rather than failing on it.
CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

#: The push/PR lane: the admission gate (conformance + boot-and-test) every plugin must have.
CI_WORKFLOW = ".github/workflows/ci.yml"

#: The scheduled lane that probes the ceiling of the declared `requires_tap` range against
#: core `main` — C2's instrument, not its gate.
NIGHTLY_WORKFLOW = ".github/workflows/nightly.yml"

_WORKFLOW_DIR = ".github/workflows"
#: A ``uses`` KEY at the start of its line, quoted or bare, plain or as a list item. Anchored on
#: purpose: a pattern that matches ``uses:`` anywhere on the line also matches inside a `run:`
#: script, and the same scan feeds the PRESENCE proof, where over-reporting is fail-open rather
#: than safe.
_USES_KEY_RE = re.compile(r"""^(?P<indent>\s*)(?:-\s*)?['"]?uses['"]?\s*:\s*['"]?(?P<ref>[^\s'"#]+)""")

#: Any ``key:`` at the start of its line — used to track indentation structure.
_KEY_RE = re.compile(r"""^(?P<indent>\s*)(?:-\s*)?['"]?(?P<key>[A-Za-z_][\w.-]*)['"]?\s*:(?P<rest>.*)$""")

#: A value that opens a block scalar, whose indented body is text and not YAML keys.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*\s*(?:#.*)?$")

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def run_repo_checks(repo_root: Path, result: ValidationResult) -> None:
    """Append the repository-scope checks to *result*.

    TAP-IMPLEMENTS: req-tap-plugin-validate-repo@a228692fed0c/1d18780864fb (derivation) — the
        repository-scope check set is dispatched here, opt-in, against the repository root the
        caller names.
    """
    _check_codeowners(repo_root, result)
    _check_workflows(repo_root, result)
    _check_caller_pin(repo_root, result)
    _check_caller_permissions(repo_root, result)
    _check_nightly_shape(repo_root, result)
    _check_waiver_ledger(repo_root, result)


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
        if len(fields) >= 2 and any(_is_owner(f) for f in fields[1:]):
            rules.append(line)
    return rules


def _is_owner(token: str) -> bool:
    """Is *token* something GitHub would resolve to an owner?

    A bare ``@`` is not, and neither is ``@`` with nothing after it: an earlier version accepted
    any token CONTAINING ``@``, so the rule ``* @`` counted as ownership while GitHub resolves it
    to nobody. The test for a check whose whole point is "presence is not correctness" cannot
    itself accept a syntactically present non-owner.

    Three forms resolve: ``@user``, ``@org/team`` and a bare email address.
    """
    if token.startswith("@"):
        handle = token[1:]
        if not handle or handle.startswith("/") or handle.endswith("/"):
            return False
        # @org/team — both halves must be non-empty; @user — no slash at all.
        return all(part for part in handle.split("/")) and handle.count("/") <= 1
    local, sep, domain = token.partition("@")
    return bool(sep and local and "." in domain)


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

    with_rules = {
        rel: _codeowners_rules((repo_root / rel).read_text(encoding="utf-8", errors="replace")) for rel in found
    }
    effective = found[0]  # CODEOWNERS_LOCATIONS is in GitHub's precedence order.
    check.details = {
        "locations": found,
        "effective": effective,
        "with_rules": [rel for rel, rules in with_rules.items() if rules],
    }

    if not with_rules[effective]:
        # The file GitHub consults names nobody. A populated file at a LOWER-precedence path does
        # not rescue it — that file is ignored — so this fails even when another location has
        # rules, which is the opposite of the ignored-file case below.
        others = [rel for rel, rules in with_rules.items() if rules]
        detail = (
            " (the rules in " + ", ".join(others) + " sit at a path GitHub ignores once this one exists)"
            if others
            else ""
        )
        check.fail(
            f"{effective} is the CODEOWNERS GitHub consults and it declares no owner rule — a "
            f"pattern followed by at least one resolvable @owner{detail}. A CODEOWNERS with no "
            "rule reads as ownership and enforces none",
            path=effective,
        )
        for rel, rules in with_rules.items():
            if rules:
                check.info(f"{rel} declares {len(rules)} owner rule(s), but is not the effective file", path=rel)
        result.checks.append(check)
        return

    if any(with_rules.values()):
        for rel, rules in with_rules.items():
            if rules:
                check.info(f"{rel} declares {len(rules)} owner rule(s)", path=rel)
            else:
                # GitHub consults ONE of the three locations, by a precedence this check does not
                # resolve offline. So a ruleless file beside a populated one is reported and not
                # failed: it may be the file GitHub ignores, and failing on it would reject a
                # repository whose ownership is in fact enforced.
                check.warn(
                    f"{rel} declares no owner rule. It sits at a path GitHub ignores while "
                    f"{effective} exists, so ownership is enforced — but a ruleless CODEOWNERS "
                    "left in the tree reads as ownership to every human who opens it. Delete it",
                    path=rel,
                )
    else:
        check.fail(
            "a CODEOWNERS file is present at "
            + ", ".join(found)
            + " but NO location declares an owner rule (a pattern followed by at least one "
            "@owner) — a CODEOWNERS with no rule reads as ownership and enforces none, whichever "
            "of them GitHub consults",
            path=found[0],
        )
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


def _job_uses_from_yaml(text: str) -> list[tuple[int, str]] | None:
    """Every ``jobs.<id>.uses`` with its line number, parsed as YAML. ``None`` if unavailable.

    Parsing beats pattern-matching here and the reason is not elegance: a lexical scan has to
    enumerate the spellings YAML allows, and each draft of this scanner was defeated by one it had
    not enumerated — a quoted key, then a value inside ``run:``, then a flow mapping. The set of
    legal spellings is the parser's job to know.

    ``compose`` rather than ``safe_load`` because the finding has to name a line, and a loaded
    dict has no positions. Composing builds the node tree with ``start_mark`` intact and executes
    no tags, so an untrusted workflow file still cannot construct a Python object.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised by the fallback test
        return None

    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        # A file that is not YAML has no job-level calls to find; the caller's other checks
        # (and the workflow's own CI) are where malformed YAML is someone's problem.
        return []
    if root is None or not isinstance(root, yaml.MappingNode):
        return []

    def _mapping_get(node: object, key: str) -> Any:
        if not isinstance(node, yaml.MappingNode):
            return None
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
                return value_node
        return None

    jobs = _mapping_get(root, "jobs")
    if not isinstance(jobs, yaml.MappingNode):
        return []

    found: list[tuple[int, str]] = []
    for _job_id, job in jobs.value:
        uses = _mapping_get(job, "uses")
        if isinstance(uses, yaml.ScalarNode) and uses.value:
            found.append((uses.start_mark.line + 1, str(uses.value).strip()))
    return found


def _job_permissions(text: str, lineno: int) -> dict[str, str] | None:
    """The job-level ``permissions:`` mapping of the job whose ``uses:`` sits at *lineno*.

    ``None`` when it cannot be determined (no parser, or the job declares no block). A job that
    declares nothing inherits the workflow default, which is NOT the same as granting nothing —
    so the two states are kept distinct rather than collapsed into an empty dict.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - the fallback path has its own test
        return None
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.MappingNode):
        return None

    def _get(node: object, key: str) -> Any:
        if not isinstance(node, yaml.MappingNode):
            return None
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                return v
        return None

    jobs = _get(root, "jobs")
    if not isinstance(jobs, yaml.MappingNode):
        return None
    for _job_id, job in jobs.value:
        uses = _get(job, "uses")
        if not (isinstance(uses, yaml.ScalarNode) and uses.start_mark.line + 1 == lineno):
            continue
        perms = _get(job, "permissions")
        if not isinstance(perms, yaml.MappingNode):
            return None
        return {
            str(k.value): str(v.value)
            for k, v in perms.value
            if isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.ScalarNode)
        }
    return None


def _job_uses(text: str) -> tuple[list[tuple[int, str]], bool]:
    """``(job-level uses entries, coverage_is_complete)``.

    Complete when a YAML parser was available. When it was not, the lexical fallback runs and the
    flag is False — and the caller turns that into a FAILURE, not a warning. A warning would leave
    a non-strict run reporting ``ok``, which is the fail-open shape this check exists to remove:
    an inconclusive pin check must not be indistinguishable from a conformant one. The fallback's
    findings are still reported, because a bad pin it *did* see is still a bad pin.
    """
    parsed = _job_uses_from_yaml(text)
    if parsed is not None:
        return parsed, True
    return _job_uses_lexically(text), False


def _job_uses_lexically(text: str) -> list[tuple[int, str]]:
    """Every JOB-LEVEL ``uses:`` in a workflow file, as ``(line number, reference)``.

    Structural, not "the word appears on the line". Three drafts got here and the last two are
    worth recording, because they failed in opposite directions and the second failure was the
    dangerous one.

    1. Anchored on a bare ``uses:`` at the start of a line. A QUOTED key (``'uses':`` — ordinary
       YAML) walked straight past it, so an unpinned release caller could hide behind a pinned
       CI caller.
    2. Widened to match anywhere on the line. That closed the quoted-key hole and opened a worse
       one: ``run: echo uses: …/plugin-ci.yml@<sha>`` inside a hand-rolled lane now looked like a
       caller. The docstring called over-reporting "the safe direction" and that was wrong — the
       SAME scan feeds the presence proof (*does this repo call the reusable lane at all?*),
       where a false positive is FAIL-OPEN: a repo that calls nothing passes.
    3. This one. A ``uses`` key must sit at the indentation of a job's own body, directly under a
       job id, directly under a top-level ``jobs:`` — which is the only place a reusable-workflow
       call can live. A ``run:`` value cannot reach that position, and neither can a step's
       ``uses`` (steps are deeper), nor a key inside ``with:`` or ``secrets:``.

    Block scalars are skipped: everything indented under ``run: |`` is text, and a line reading
    ``uses: x`` in there is not a key.

    This is the FALLBACK path, used only when no YAML parser is importable. It cannot see a call
    written as a flow mapping (``tap: {uses: x}``) or a ref written as a folded scalar, and
    missing a caller is **fail-open for the pin half**: a caller the scan cannot see is a caller
    whose bad pin is never reported. An earlier draft called that "fails closed", which was
    wrong — it fails closed only for the presence half. So a file that falls back is reported as
    reduced coverage rather than silently trusted; ``_job_uses`` is the entry point that decides.
    """
    found: list[tuple[int, str]] = []
    jobs_indent: int | None = None
    job_id_indent: int | None = None
    job_body_indent: int | None = None
    skip_deeper_than: int | None = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())

        # Inside a block scalar: its body is text, not structure.
        if skip_deeper_than is not None:
            if indent > skip_deeper_than:
                continue
            skip_deeper_than = None

        key_match = _KEY_RE.match(raw)
        if key_match is None:
            continue
        key = key_match.group("key")
        rest = key_match.group("rest").strip()
        if _BLOCK_SCALAR_RE.match(rest):
            skip_deeper_than = indent

        if jobs_indent is None:
            if key == "jobs" and indent == 0:
                jobs_indent = indent
            continue

        if indent <= jobs_indent:
            # Left the jobs block entirely (a later top-level key).
            jobs_indent = job_id_indent = job_body_indent = None
            if key == "jobs" and indent == 0:
                jobs_indent = indent
            continue

        if job_id_indent is None or indent == job_id_indent:
            # A job id. Its body is whatever indent comes next, deeper than this.
            job_id_indent = indent
            job_body_indent = None
            continue

        if job_body_indent is None:
            job_body_indent = indent
        if indent != job_body_indent:
            continue

        uses_match = _USES_KEY_RE.match(raw)
        if uses_match and uses_match.group("ref"):
            found.append((lineno, uses_match.group("ref")))
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
    lexical_only: list[str] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        rel = path.relative_to(repo_root).as_posix()
        entries, complete = _job_uses(path.read_text(encoding="utf-8", errors="replace"))
        if not complete:
            lexical_only.append(rel)
        for lineno, ref in entries:
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

    check.details = {"callers": callers, "lexical_only": lexical_only}
    if lexical_only:
        check.fail(
            "no YAML parser available, so "
            + ", ".join(lexical_only)
            + " could only be scanned line by line — a call written as a flow mapping or with a "
            "folded ref is invisible to that scan, and a caller it cannot see is a bad pin it "
            "cannot report. This check therefore cannot make the claim it exists to make, so it "
            "reports INCONCLUSIVE as a failure rather than a pass: a pin check that did not "
            "examine every caller must not read as conformant. Install the validator's test-tier "
            "dependencies (PyYAML) and re-run"
        )
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


# ---------------------------------------------------------------------------
# The caller's grant
# ---------------------------------------------------------------------------

#: The single permission a caller of the reusable lane needs, once core's scanning job uploads
#: SARIF instead of writing to the dependency graph.
REQUIRED_CALLER_GRANT = ("security-events", "write")


def _check_caller_permissions(repo_root: Path, result: ValidationResult) -> None:
    """Does the job that calls the reusable lane grant the one permission that lane needs?

    A called workflow cannot hold more permission than its caller granted, so a job whose grant is
    short of what the lane declares does not fail a step — the whole run is refused before any job
    exists, which surfaces as ``startup_failure`` and names nothing. That is the most expensive
    shape of failure a lane can have: a red that looks like an outage rather than a defect, with no
    job, no log and no plugin named. This check exists so the missing grant is reported where it
    can be read, against the repository that has to fix it.

    The grant is ``security-events: write``, at JOB level, on the job that calls the lane —
    deliberately narrow: core's scanning job uploads SARIF to the Security tab and needs nothing
    else. `contents: write` is NOT wanted anywhere for scanning; an earlier arrangement had the
    lane write to the dependency graph, which forced every caller to grant repository write for a
    reporting side effect.

    A WARNING while core's SARIF job is not yet live, because a grant for a requirement that does
    not exist yet is noise. **A ratchet, like the nightly lane:** it becomes a failure once the
    uploading job ships, at which point a caller without the grant cannot run at all.

    **A lingering ``contents: write`` is reported too, even when the narrow grant is present.** The
    first version only asked whether ``security-events: write`` was there, so a caller holding BOTH
    read as fully conformant — which would let the broad legacy grant survive the migration by
    being invisible, in a change whose entire purpose is that nobody needs repository write for
    scanning. It is required today (core still writes the dependency graph) and becomes an
    over-grant the moment that job is replaced, so it is reported rather than failed, and the
    message says to remove it in the same change that adds the narrow one.
    """
    check = CheckResult(
        id="repo-caller-permissions",
        name="The job calling the reusable lane grants the permission that lane needs",
    )
    workflow_dir = repo_root / _WORKFLOW_DIR
    if not workflow_dir.is_dir():
        check.info(f"no {_WORKFLOW_DIR}/ — no caller to check a grant on")
        result.checks.append(check)
        return

    key, value = REQUIRED_CALLER_GRANT
    checked: list[dict[str, object]] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        entries, _complete = _job_uses(text)
        for lineno, ref in entries:
            target, _, _pin = ref.partition("@")
            if target != REUSABLE_CALLER:
                continue
            perms = _job_permissions(text, lineno)
            granted = perms is not None and perms.get(key) == value
            legacy_write = perms is not None and perms.get("contents") == "write"
            checked.append({"file": rel, "line": lineno, "granted": granted, "contents_write": legacy_write})
            if legacy_write:
                # Required TODAY — core's snapshot job still writes the dependency graph, and
                # removing it now breaks the lane. It becomes an over-grant the moment that job
                # is replaced by the SARIF upload, and it is the thing to delete in the same
                # change that adds the narrow grant. Reported even when the narrow grant is
                # present, because otherwise a caller holding both reads as fully conformant and
                # the broad legacy grant survives the migration by being invisible.
                check.warn(
                    f"{rel}:{lineno} grants `contents: write` on the job calling the reusable lane. "
                    "That is repository write, and it is needed only while core's scanning job "
                    "writes the dependency graph; once that job uploads SARIF instead it is an "
                    f"over-grant. Remove it in the same change that adds `{key}: {value}` — do not "
                    "leave both",
                    path=rel,
                )
            if granted:
                continue
            missing = (
                "declares no job-level `permissions:` block, so it inherits the workflow default"
                if perms is None
                else f"grants {sorted(perms.items())} at job level"
            )
            check.warn(
                f"{rel}:{lineno} calls the reusable lane and {missing} — it needs "
                f"`{key}: {value}` on THAT job so the lane can upload its scan results. Without it "
                "the run is refused before any job exists, which shows up as startup_failure "
                "naming nothing, not as a failed step. A warning until core's uploading job ships; "
                "a failure after",
                path=rel,
            )

    check.details = {"callers": checked}
    if not checked:
        check.info("no caller of the reusable lane in this repository")
    elif all(c["granted"] for c in checked) and not any(c["contents_write"] for c in checked):
        check.info(f"{len(checked)} caller(s), each granting {key}: {value} at job level and nothing broader")
    result.checks.append(check)


# ---------------------------------------------------------------------------
# The nightly lane's SHAPE
# ---------------------------------------------------------------------------

#: A ``harness_ref`` that points the nightly at core's moving tip. Accepted either as the bare
#: scalar ``main`` or as a workflow expression whose FALLBACK is main
#: (``${{ inputs.harness_ref || 'main' }}`` — a maintainer's dispatch input with main as the
#: scheduled default). The second spelling is why this is a pattern and not an equality test:
#: a literal match reported gryphon-playground as not probing main when it does.
_HARNESS_MAIN_RE = re.compile(r"""^(?:main|.*\|\|\s*['"]main['"].*)$""", re.DOTALL)

#: ``gh issue list`` with no ``--limit`` takes gh's default page of 30. The owner issue falling
#: past that page reads as "no issue yet", and the job files a duplicate — every night.
_GH_ISSUE_LIST_RE = re.compile(r"gh\s+issue\s+list\b[^\n]*(?:\\\s*\n[^\n]*)*")

#: Selecting the job's own issue by TITLE. The title is not the bot's to own: anyone who can open
#: an issue can open one with this title, and the job will then comment on — or CLOSE — a
#: stranger's issue. What identifies the issue must be something only the job can have written.
_TITLE_MATCH_RE = re.compile(r"\.title\s*==")

#: The issue-identifying evidence that IS the job's own: a hidden marker in the body it wrote,
#: and/or the authoring bot. Either alone is weak (a marker is copyable, an author is shared by
#: every bot-filed issue in the repo); together they are the job's.
_BODY_MARKER_RE = re.compile(r"\.body\b[^\n]*\bcontains\(|\bcontains\([^\n]*\.body\b")
_AUTHOR_MATCH_RE = re.compile(r"\.author\b")


def _workflow_jobs(text: str) -> list[dict[str, Any]] | None:
    """Every job of a workflow, with the fields the nightly-shape check reads. ``None`` if no parser.

    ``compose`` rather than ``safe_load`` for the same reason ``_job_uses_from_yaml`` uses it: a
    finding has to name a line, and it executes no tags, so an untrusted workflow still cannot
    construct a Python object.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised by the fallback test
        return None
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return []
    if not isinstance(root, yaml.MappingNode):
        return []

    def _get(node: object, key: str) -> Any:
        if not isinstance(node, yaml.MappingNode):
            return None
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                return v
        return None

    def _scalars_under(node: object, key: str) -> list[str]:
        """Every ``key:`` scalar value anywhere beneath *node* — used to collect ``run:`` scripts."""
        out: list[str] = []
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                if isinstance(k, yaml.ScalarNode) and k.value == key and isinstance(v, yaml.ScalarNode):
                    out.append(str(v.value))
                out.extend(_scalars_under(v, key))
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                out.extend(_scalars_under(item, key))
        return out

    jobs_node = _get(root, "jobs")
    if not isinstance(jobs_node, yaml.MappingNode):
        return []

    jobs: list[dict[str, Any]] = []
    for job_id, job in jobs_node.value:
        if not isinstance(job_id, yaml.ScalarNode):
            continue
        uses = _get(job, "uses")
        with_node = _get(job, "with")
        harness = _get(with_node, "harness_ref") if with_node is not None else None
        perms = _get(job, "permissions")
        permissions = (
            {
                str(k.value): str(v.value)
                for k, v in perms.value
                if isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.ScalarNode)
            }
            if isinstance(perms, yaml.MappingNode)
            else None
        )
        jobs.append(
            {
                "id": str(job_id.value),
                "line": job_id.start_mark.line + 1,
                "uses": str(uses.value).strip() if isinstance(uses, yaml.ScalarNode) else None,
                "harness_ref": str(harness.value).strip() if isinstance(harness, yaml.ScalarNode) else None,
                "permissions": permissions,
                "concurrency": _get(job, "concurrency") is not None,
                "run": _scalars_under(job, "run"),
            }
        )
    return jobs


def _check_nightly_shape(repo_root: Path, result: ValidationResult) -> None:
    """Does the nightly lane do the job the standard gives it, and can its reporter be steered?

    ``repo-workflows`` asks whether ``nightly.yml`` EXISTS. This asks what is in it, because a
    scheduled lane that calls the reusable workflow at the plugin's declared floor probes nothing
    the push lane did not already probe — it is a nightly in name, burning runner minutes to
    re-answer a settled question. The ceiling probe is the whole point of the lane (plugin
    standard C2), so a nightly that never points a caller at core ``main`` fails.

    **Who receives the red (``tap#367``) is the second half, and it is a WARNING, not a rule.**
    The fleet's answer is an ``owner-issue`` job holding ``issues: write`` that files one issue on
    a red and closes it on the next green. gryphon-playground deliberately has none: an
    issue-filing reporter was built and WITHDRAWN there (operator ruling 2026-09-14, ``tap#439``)
    because github_core collects every run in the org and the landing page shows a red nightly —
    and a nightly that never fired — without an inbox of its own. That is a legitimate second
    answer, so this check reports the absence and names the alternative rather than failing a
    repository for a decision that was actually made.

    **The three defects below are in the job itself, and 15 of the 16 nightlies carry all three**,
    because the job was copy-pasted per repository rather than shared. They are reported together
    since they are one fix:

    * ``gh issue list`` with no ``--limit`` takes gh's default page of thirty. Past thirty open
      issues the owner issue falls off the page, the job reads that as "none yet", and files a
      duplicate — nightly, forever. A listing that hits its limit should refuse rather than guess.
    * No ``concurrency:`` group, so a slow scheduled run and a dispatch can each see no issue and
      each file one. The same duplicate by a different road.
    * Selecting the issue by TITLE. This is the one that is not merely noisy: the title is not the
      bot's to own, so anyone who can open an issue can open one with that title and the job will
      comment on — or CLOSE — a stranger's issue on the next green night. A write steered by
      text a stranger chose. What identifies the issue has to be something only this job could
      have written: a hidden marker in the body it wrote, checked together with the author.
    """
    check = CheckResult(id="repo-nightly-shape", name="The nightly lane probes core main and reports safely")
    rel = NIGHTLY_WORKFLOW
    path = repo_root / rel
    if not path.is_file():
        # `repo-workflows` owns the absence and already ratchets on it. Saying it twice would
        # double-count one defect across two checks.
        check.info(f"no {rel} — its absence is repo-workflows' finding, not this one")
        result.checks.append(check)
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    jobs = _workflow_jobs(text)
    if jobs is None:
        check.fail(
            f"{rel} could not be parsed — no YAML parser is importable, so the nightly's shape is "
            "UNKNOWN. An unknown shape is not a conformant one: install this package's "
            "dependencies (PyYAML) and re-run",
            path=rel,
        )
        result.checks.append(check)
        return

    inherited = [j for j in jobs if j["uses"] and j["uses"].partition("@")[0] == REUSABLE_NIGHTLY]
    callers = [j for j in jobs if j["uses"] and j["uses"].partition("@")[0] == REUSABLE_CALLER]
    probing = [j for j in callers if j["harness_ref"] and _HARNESS_MAIN_RE.match(j["harness_ref"])]
    reporters = [j for j in jobs if (j["permissions"] or {}).get("issues") == "write"]

    check.details = {
        "inherited": [j["id"] for j in inherited],
        "callers": [j["id"] for j in callers],
        "probes_main": [j["id"] for j in probing],
        "reporters": [j["id"] for j in reporters],
    }

    if inherited:
        # The whole lane is core's. Both halves this check asks about — the ceiling probe and an
        # unsteerable reporter — are inside the file being called, held by core's own tests, and
        # reach this repository through its pin. Re-deriving them from the caller would be
        # checking a thing that is not here; worse, the OLD rules would fail this shape outright
        # (no direct plugin-ci call, no harness_ref), which would punish the repositories that
        # adopted the fix. What remains checkable here is the grant, and repo-caller-permissions
        # owns that.
        missing = [j["id"] for j in inherited if (j["permissions"] or {}).get("issues") != "write"]
        for job_id in missing:
            check.fail(
                f"{rel} job `{job_id}` calls {REUSABLE_NIGHTLY} but does not grant `issues: write` "
                "at job level. That workflow's owner-issue job declares it, and a caller short of "
                "what a called workflow declares is refused before ANY job starts — "
                "startup_failure, zero jobs, no log",
                path=rel,
            )
        if not missing:
            check.info(
                f"inherits the nightly from core ({', '.join(j['id'] for j in inherited)}): the "
                "ceiling probe and the owner issue are core's, held by core's tests"
            )
        result.checks.append(check)
        return

    if not callers:
        check.fail(
            f"{rel} calls {REUSABLE_CALLER} from no job — a scheduled lane that does not invoke "
            "the reusable workflow proves nothing about this plugin against any core",
            path=rel,
        )
    elif not probing:
        refs = ", ".join(sorted({str(j["harness_ref"] or "(none — the declared floor)") for j in callers}))
        check.fail(
            f"{rel} calls the reusable lane but no job passes `harness_ref: main` (found: {refs}). "
            "The nightly's reason to exist is the CEILING of the declared requires_tap range — "
            "will the NEXT core break this plugin. Pinned at the floor it re-answers what ci.yml "
            "already answered, on a clock",
            path=rel,
        )
    else:
        check.info(f"probes core main from job(s): {', '.join(j['id'] for j in probing)}")

    if not reporters:
        check.warn(
            f"{rel} has no job holding `issues: write`, so a red night files nothing in this "
            "repository and is heard only by whoever opens the Actions tab (tap#367). That is a "
            "legitimate choice when a central collector watches the org's runs — gryphon-playground "
            "withdrew its reporter for exactly that reason (tap#439) — so this is a warning, not a "
            "rule. If nothing central watches this repository, the red is silent",
            path=rel,
        )
        result.checks.append(check)
        return

    for job in reporters:
        script = "\n".join(job["run"])
        where = f"{rel}:{job['line']} (job `{job['id']}`)"

        if _TITLE_MATCH_RE.search(script) and not (_BODY_MARKER_RE.search(script) and _AUTHOR_MATCH_RE.search(script)):
            check.fail(
                f"{where} finds its own issue by TITLE. The title is not this job's to own: anyone "
                "who can open an issue can open one with that title, and this job will then comment "
                "on it — or CLOSE it on the next green night. That is a write steered by text a "
                "stranger chose. Identify the issue by a hidden marker in the body this job wrote, "
                "checked together with the author, so only an issue it actually filed can match",
                path=rel,
            )

        listings = _GH_ISSUE_LIST_RE.findall(script)
        if listings and not any("--limit" in call for call in listings):
            check.warn(
                f"{where} runs `gh issue list` with no `--limit`, so it sees gh's default page of "
                "thirty open issues. Past thirty the owner issue falls off the page, this job reads "
                "that as 'none open yet', and files a duplicate — every night, forever. Pass an "
                "explicit `--limit` AND fail the step when the listing hits it: a truncated listing "
                "is an unknown answer, not a negative one",
                path=rel,
            )

        if not job["concurrency"]:
            check.warn(
                f"{where} declares no `concurrency:` group. A slow scheduled run and a "
                "workflow_dispatch can overlap, each see no open issue, and each file one — the "
                "same duplicate the missing `--limit` produces, by a different road. A group keyed "
                "on this job, with cancel-in-progress false, serialises it",
                path=rel,
            )

    if check.status == "pass":
        check.info(f"{len(reporters)} reporter job(s), each identifying its issue safely")
    result.checks.append(check)


# ---------------------------------------------------------------------------
# The waiver ledger
# ---------------------------------------------------------------------------

#: The waiver ledger a plugin repository keeps at its root. ABSENCE IS THE CORRECT STATE and is
#: never reported (ruling George, 2026-09-26, Q94b/Q94c): an absent ledger means nothing has been
#: waived, and reporting it would teach people to create an empty file to silence a checker —
#: which destroys the only signal the file carries. Nor is one seeded at generation time. What is
#: worth checking is the inverse: a ledger that EXISTS must carry a reason for every entry.
TRIVYIGNORE = ".trivyignore"


def unreasoned_waivers(text: str) -> list[tuple[int, str]]:
    """Every ``.trivyignore`` entry whose line is not directly under a reason comment.

    The ledger's rule (core's own ``.trivyignore`` header): a waiver is an operator's decision,
    and the reason sits in the comment immediately above the id. A bare ``#`` does not count, and
    a blank line between the reason and the id breaks the link — otherwise one comment at the top
    of a file would read as the reason for everything under it.

    DELIBERATELY a second implementation of ``scripts/release_cve_gate.py``'s function of the same
    name, not an import of it. That script is stdlib-only and runs on the runner's bare
    interpreter under ``scripts/``, which is not shipped in this package's wheel; this one has to
    work from an installed wheel against a repository that is not TAP. The two are held identical
    by ``tap/tests/test_release_cve_gate.py``, over one shared corpus, so the duplication cannot
    drift into two different meanings of "waived".
    """
    missing: list[tuple[int, str]] = []
    previous = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            reason = previous.lstrip("#").strip() if previous.startswith("#") else ""
            if not reason:
                missing.append((number, line))
        previous = line
    return missing


def _check_waiver_ledger(repo_root: Path, result: ValidationResult) -> None:
    """If this repository waives a vulnerability, does it say why?

    The author-time mirror of the gate `plugin-ci.yml` runs in CI (`release_cve_gate.py
    --check-waivers`): the same rule, reported before the push rather than after it.

    **A missing ledger is not a finding.** That is the ruling (George, 2026-09-26, Q94b/Q94c) and
    it is the opposite of what a conformance checker reaches for by default. An absent
    `.trivyignore` means nothing is waived, which is the state to want; reporting it would teach
    authors to create an empty file to make a checker quiet, and an empty ledger is
    indistinguishable from a repository that has never had to think about a CVE. Nor are empty
    ledgers seeded during a sweep — a seeded file is a claim about a repository that nobody made.

    This matters more now than it did: the plugin gate no longer passes `--ignore-unfixed`
    (Q94d), so an unfixable HIGH blocks a pull request until someone ships a fix, a workaround, or
    a waiver. Waivers are about to be written for the first time, and a waiver without a reason is
    the shape that turns a gate into a rubber stamp.
    """
    check = CheckResult(id="repo-waiver-ledger", name="Every vulnerability waiver carries its reason")
    path = repo_root / TRIVYIGNORE
    if not path.is_file():
        check.info(f"no {TRIVYIGNORE} — nothing is waived, which is the state to want")
        result.checks.append(check)
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    missing = unreasoned_waivers(text)
    entries = [ln for ln in (raw.strip() for raw in text.splitlines()) if ln and not ln.startswith("#")]
    check.details = {"entries": len(entries), "unreasoned": [n for n, _ in missing]}

    for number, entry in missing:
        check.fail(
            f"{TRIVYIGNORE}:{number}: waiver `{entry}` has no reason comment directly above it. Say "
            "what the finding is, why it does not apply (or is accepted), who accepted it and when "
            "— a bare `#` does not count, and a blank line between the comment and the id breaks "
            "the link. This is the same rule the CI gate applies; failing it here costs a re-edit "
            "rather than a red lane",
            path=TRIVYIGNORE,
        )
    if not missing:
        check.info(f"{len(entries)} waiver(s), each under a reason comment")
    result.checks.append(check)
