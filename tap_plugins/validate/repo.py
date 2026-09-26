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

    TAP-IMPLEMENTS: req-tap-plugin-validate-repo@681d6d92dc56/77709e9ce6b2 (derivation) — the
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
