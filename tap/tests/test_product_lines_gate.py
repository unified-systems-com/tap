"""The `gate` aggregator really aggregates (req-cicd-dco-signoff-3, req-cicd-branch-protection).

`gate` is the ONE GitHub Actions context the `main-required-checks` ruleset requires, so a job
that is not folded into it is advisory no matter how red it goes. That is not a hypothetical:
from 2026-08-12 to 2026-09-18 the `dco` job — DCO sign-off plus issue-link trailers — ran on
every PR, could go red, and blocked nothing, while CONTRIBUTING.md, CLAUDE.md and two specs all
said the checks were enforcing (tap#353). A declaration that exists but is false passes any check
that only tests presence.

The assertion is therefore DERIVED, not a hand-kept list of lane names: every job the workflow
defines must be in `gate.needs` and its result must reach gate's verdict step. A new lane added
outside the aggregator fails here on the PR that adds it, which is the only moment anyone is
looking.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "product-lines.yml"


@pytest.fixture(name="workflow")
def _workflow() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data


def _gate(workflow: dict[str, Any]) -> dict[str, Any]:
    gate: dict[str, Any] = workflow["jobs"]["gate"]
    return gate


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_the_dco_job_is_required_through_the_gate(workflow: dict[str, Any]) -> None:
    """The named defect (tap#353): `dco` outside `gate.needs` is a check that changes nothing."""
    assert "dco" in _gate(workflow)["needs"]


# Jobs that run AFTER gate and so cannot be among its inputs. The set is exact, not a pattern: a
# second entry is a deliberate edit here, and `test_the_owner_issue_job_is_report_only` pins the
# one member to a shape that cannot weaken the verdict (schedule-only, needs gate, issues: write,
# no checkout).
DOWNSTREAM_OF_GATE = frozenset({"owner-issue"})


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_every_job_is_folded_into_the_gate(workflow: dict[str, Any]) -> None:
    """Derived, so the next lane cannot be added outside the one required context unnoticed."""
    jobs = set(workflow["jobs"]) - {"gate"} - DOWNSTREAM_OF_GATE
    missing = sorted(jobs - set(_gate(workflow)["needs"]))
    assert not missing, (
        f"{missing} run in product-lines.yml but are not in `gate`'s needs — `gate` is the only "
        "context the main-required-checks ruleset requires, so a red in those jobs blocks nothing."
    )


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_every_needed_jobs_result_reaches_the_verdict(workflow: dict[str, Any]) -> None:
    """Being in `needs` only makes a job RUN first; gate must also read its result.

    `if: always()` means gate executes even when a lane fails, so an unread result is a silent
    pass — the same presence-not-correctness shape one level down.
    """
    gate = _gate(workflow)
    assert gate.get("if") == "always()", "gate must not be skippable into a false green"
    rendered = yaml.safe_dump(gate["steps"])
    unread = sorted(job for job in gate["needs"] if f"needs.{job}.result" not in rendered)
    assert not unread, f"gate needs {unread} but never reads their result — a failure there is invisible"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((WORKFLOW.parent / name).read_text(encoding="utf-8"))
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    raw: Any = workflow  # PyYAML reads the bare `on:` key as the boolean True, not "on"
    triggers: dict[str, Any] = raw.get("on", raw.get(True)) or {}
    return triggers


def _core_ci_calls(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every job in ``workflow`` that calls core-ci.yml, by job id."""
    return {
        job_id: job for job_id, job in workflow["jobs"].items() if job.get("uses") == "./.github/workflows/core-ci.yml"
    }


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_the_core_ci_line_requires_the_gryphon_corpus_to_execute() -> None:
    """The corpus runs on every PR: the core_ci line passes it to --require, by name."""
    job = _load("core-ci.yml")["jobs"]["line"]
    lane = next(s for s in job["steps"] if str(s.get("name", "")).startswith("Test lane"))
    assert 'require="gryphon_playground"' in lane["run"] and "--require" in lane["run"]
    assert "--record boot/core_ci.boot.json" in lane["run"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_cold_boot_boots_core_ci_on_the_full_and_boot_tiers(workflow: dict[str, Any]) -> None:
    """cold-boot proves core's own set, on every tier that can move boot — never the union."""
    caller = workflow["jobs"]["cold-boot"]
    assert "tier == 'full'" in caller["if"] and "tier == 'boot'" in caller["if"]
    assert caller["with"]["lane"] == "cold-boot"
    job = _load("core-ci.yml")["jobs"]["cold-boot"]
    assert job["env"]["TAP_BOOT_PROFILE"] == "core_ci"
    cache = next(s for s in job["steps"] if "actions/cache" in str(s.get("uses", "")))
    assert cache["with"]["key"].startswith("uv-ci-core_ci-")


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_gate_accepts_a_cold_boot_skip_only_on_the_tier(workflow: dict[str, Any]) -> None:
    """No other job's result can buy cold-boot's skip: the verdict's cold-boot arm never reads bom-boot."""
    rendered = "\n".join(step.get("run", "") for step in _gate(workflow)["steps"])
    arm = rendered[rendered.index('case "$R_COLD" in') :]
    arm = arm[: arm.index("esac")]
    assert "R_BOM" not in arm, "cold-boot's skip must be justified by the tier alone"


@pytest.mark.spec("req-dev-validation-product-line-lanes-1")
def test_core_ci_is_the_only_line_in_tap_checks(workflow: dict[str, Any]) -> None:
    """Product lines are proven in their own repos (tap#638): no product profile rides tap's PR checks.

    The `line` job is a call to core-ci.yml, not a matrix: there is no row a product line
    could be added back into without it showing up here.
    """
    calls = _core_ci_calls(workflow)
    assert {job_id: job["with"]["lane"] for job_id, job in calls.items()} == {"line": "line", "cold-boot": "cold-boot"}
    assert "strategy" not in workflow["jobs"]["line"]
    assert "matrix" not in workflow["jobs"]["setup"].get("outputs", {})
    assert not (_triggers(workflow)["workflow_dispatch"] or {}).get("inputs"), "one line: nothing to choose"


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_core_ci_is_defined_once_and_fails_closed_on_an_unknown_lane() -> None:
    """One definition, selected per call — and a call whose every job skipped must not read green."""
    core = _load("core-ci.yml")
    assert set(_triggers(core)) == {"workflow_call"}
    jobs = core["jobs"]
    assert jobs["line"]["if"] == "inputs.lane == 'line'"
    assert jobs["cold-boot"]["if"] == "inputs.lane == 'cold-boot'"
    check = jobs["lane-check"]
    assert check["if"] == "inputs.lane != 'line' && inputs.lane != 'cold-boot'"
    assert "exit 1" in "\n".join(step.get("run", "") for step in check["steps"])
    for job_id in ("line", "cold-boot"):
        checkout = jobs[job_id]["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert (
            checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"
        ), f"{job_id} must validate the ref it is given"
    # No copy of the job bodies survives in the PR workflow: nothing there runs them itself.
    runs = [
        str(step.get("run", ""))
        for job in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps") or []
    ]
    assert not [r for r in runs if "tap.lane_run" in r or re.search(r"scripts/gate(?!-lean)", r)]


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_a_release_gates_on_core_ci_not_on_the_union() -> None:
    """publish-release-tags.yml runs both core_ci lanes on the tag's commit, and retag needs them."""
    release = _load("publish-release-tags.yml")
    calls = _core_ci_calls(release)
    assert sorted(job["with"]["lane"] for job in calls.values()) == ["cold-boot", "line"]
    for job in calls.values():
        assert job["with"]["ref"] == "${{ github.ref }}", "the release candidate is the tag's own commit"
        assert job["permissions"] == {"contents": "read"}
    for gated in ("candidate", "retag"):
        needs = release["jobs"][gated]["needs"]
        needs = [needs] if isinstance(needs, str) else needs
        assert set(calls) <= set(needs), f"{gated} does not wait for core_ci: {needs}"
    used = {str(job.get("uses", "")) for job in release["jobs"].values()}
    assert not any("bom-boot" in u for u in used), "a tap release gates on core only, never the test_all union"


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_the_battery_runs_nightly_against_main(workflow: dict[str, Any]) -> None:
    """tap#791: a `schedule`, so main's own content is tested — and no `push` trigger (maintainer's call)."""
    triggers = _triggers(workflow)
    assert triggers["schedule"] == [{"cron": "23 8 * * *"}]
    assert "push" not in triggers
    # Nothing in setup may key off the event: the nightly gets the same tier logic a PR does, and
    # on main that is the empty diff, which change-tier fails closed to `full`.
    pick = next(s for s in workflow["jobs"]["setup"]["steps"] if s.get("id") == "pick")
    assert "event_name" not in str(pick) and "$EVENT" not in pick["run"]
    assert "scripts/change-tier origin/main" in pick["run"]


def _cron_field_matches(field: str, value: int) -> bool:
    """Whether one cron field (``*``, ``a``, ``a-b``, ``*/n``, ``a-b/n``, comma lists) can take ``value``."""
    for part in field.split(","):
        span, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if span == "*":
            low, high = 0, value
        elif "-" in span:
            low_text, high_text = span.split("-", 1)
            low, high = int(low_text), int(high_text)
        else:
            low = int(span)
            high = low if not step_text else value
        if low <= value <= high and (value - low) % step == 0:
            return True
    return False


def _workflow_crons() -> dict[str, list[str]]:
    """Every `schedule` cron in every workflow file (`.yml` and `.yaml`), read as YAML, keyed by file name."""
    found: dict[str, list[str]] = {}
    paths = sorted([*WORKFLOW.parent.glob("*.yml"), *WORKFLOW.parent.glob("*.yaml")])
    for path in paths:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        triggers = raw.get("on", raw.get(True)) or {}
        schedule = triggers.get("schedule", []) if isinstance(triggers, dict) else []
        found[path.name] = [str(entry["cron"]) for entry in schedule or []]
    return found


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_the_nightly_cron_is_clear_of_every_other_cron() -> None:
    """Derived from the workflow directory: no other cron can fire at 08:23 UTC, on any day.

    Compared by what each cron CAN match (minute and hour fields), not by string equality, so
    `23 8 * * 1` or `*/1 8 * * *` elsewhere is a collision too.
    """
    crons = _workflow_crons()
    assert crons.pop(WORKFLOW.name) == ["23 8 * * *"]
    others = [(name, cron) for name, entries in crons.items() for cron in entries]
    assert others, "found no other cron at all — the scan is not reading the workflows"
    clashes = [
        (name, cron)
        for name, cron in others
        if _cron_field_matches(cron.split()[0], 23) and _cron_field_matches(cron.split()[1], 8)
    ]
    assert not clashes, f"these crons can fire at 08:23 UTC alongside the nightly: {clashes}"


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("23", 23, True),
        ("*", 23, True),
        ("*/1", 23, True),
        ("20-25", 23, True),
        ("1,23", 23, True),
        ("0/23", 23, True),
        ("24", 23, False),
        ("*/5", 23, False),
        ("30-40", 23, False),
    ],
)
def test_the_cron_field_matcher(field: str, value: int, expected: bool) -> None:
    """The collision test is only as good as this matcher, so it gets its own known answers."""
    assert _cron_field_matches(field, value) is expected


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_an_empty_diff_does_not_require_the_bom_lane() -> None:
    """On `schedule` HEAD is main, so gate's BOM step pipes an empty list — it must answer `no-boot`.

    An unanswered verdict would require bom-boot, which only the `boot` tier runs: every nightly
    would go red on a lane it never scheduled. Pairs with `test_empty_diff_is_full`
    (test_change_tier.py), which proves the same empty diff runs the whole battery.
    """
    repo_root = WORKFLOW.parents[2]
    # nosemgrep — a literal interpreter plus the repo's own module path; no input reaches argv.
    out = subprocess.run(  # nosemgrep
        ["python3", str(repo_root / "tap" / "bom_inputs.py"), "--classify", "--root", str(repo_root)],
        input="\n",  # gate runs `printf '%s\n' "$files"`, so an empty diff is one empty line
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "no-boot"


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_the_owner_issue_job_is_report_only(workflow: dict[str, Any]) -> None:
    """The one job outside gate: after it, schedule-only, `issues: write` only, and no repo code checked out."""
    assert DOWNSTREAM_OF_GATE <= set(workflow["jobs"])
    job = workflow["jobs"]["owner-issue"]
    assert job["needs"] == ["gate"]
    assert job["if"] == "always() && github.event_name == 'schedule'"
    assert job["permissions"] == {"issues": "write"}
    assert len(job["steps"]) == 1, "one inline script: a second step would hold the same token unpinned"
    assert not [s for s in job["steps"] if "uses" in s], "the owner-issue job must not check out or run actions"
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "owner-issue" not in _gate(workflow)["needs"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_the_owner_issue_is_found_by_author_and_marker_not_title(workflow: dict[str, Any]) -> None:
    """Anyone can open an issue titled "Nightly red: tap main"; only the Actions bot's, carrying the marker, is ours."""
    job = workflow["jobs"]["owner-issue"]
    script = job["steps"][0]["run"]
    marker = job["env"]["MARKER"]
    assert marker.startswith("<!--") and marker.endswith("-->")
    listing = script[script.index("gh issue list") : script.index("existing=")]
    assert '--limit "$LIMIT"' in listing
    assert '"$count" -ge "$LIMIT"' in script, "a listing that hit --limit must fail, not read as 'no issue'"
    selector = script[script.index("existing=") : script.index("case ")]
    assert 'author.login == "app/github-actions"' in selector and "is_bot == true" in selector
    assert "contains($m)" in selector and '--arg m "$MARKER"' in selector
    assert "title" not in selector.lower(), "the existing issue must never be matched by title"
    create = script[script.index("gh issue create") - 600 : script.index("gh issue create")]
    assert '"$MARKER"' in create, "a filed issue must carry the marker, or the next night cannot find it"


@pytest.mark.spec("req-dev-validation-product-line-lanes-12")
def test_the_owner_issue_opens_only_on_failure_and_closes_only_on_success(workflow: dict[str, Any]) -> None:
    """A cancelled or skipped gate proved nothing, so it neither files nor closes."""
    script = workflow["jobs"]["owner-issue"]["steps"][0]["run"]
    arms = script[script.index('case "$GATE_RESULT" in') :]
    success = arms[arms.index("success)") : arms.index("failure)")]
    failure = arms[arms.index("failure)") : arms.index("*)")]
    other = arms[arms.index("*)") : arms.index("esac")]
    assert "gh issue close" in success and "gh issue create" not in success
    assert "gh issue create" in failure and "gh issue close" not in failure
    assert "gh issue" not in other
