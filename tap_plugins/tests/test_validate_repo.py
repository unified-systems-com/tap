"""Repository-scope conformance checks (req-tap-plugin-validate-repo).

The shell around the package: the CI lanes, the pin on core's reusable workflow, and the file
that names a human owner. Every check here is exercised in both directions — a conformant shell
passes and each specific deviation fails or warns — because a check that has only ever been seen
to pass has not been shown to be capable of failing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tap_plugins.validate.repo import REUSABLE_CALLER, REUSABLE_PREFIX
from tap_plugins.validate.service import CheckResult, ValidationResult, validate_plugin

_SHA = "f64030e0ba5376ff6e2121bc7dd1ceddbbda1b96"

_MANIFEST = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "shell_sample"\nname = "S"\n'


def _caller(ref: str) -> str:
    return textwrap.dedent(
        f"""\
        name: ci
        on: [pull_request]
        jobs:
          tap:
            uses: {REUSABLE_CALLER}@{ref}
            with:
              plugin_slug: shell_sample
        """
    )


def _make_repo(
    tmp_path: Path,
    *,
    workflows: dict[str, str] | None = None,
    codeowners: dict[str, str] | None = None,
) -> Path:
    """A package-mode plugin repository root: pyproject + tap_plugin/<slug>/, plus the shell."""
    repo = tmp_path / "tap-plugin-shell-sample"
    package = repo / "tap_plugin" / "shell_sample"
    package.mkdir(parents=True)
    (package / "tap-plugin.toml").write_text(_MANIFEST)
    (package / "__init__.py").write_text("")
    (package / "apps.py").write_text(
        "from tap_plugins.base import TapPluginConfig\n\n\nclass ShellSampleConfig(TapPluginConfig):\n    pass\n"
    )
    (repo / "pyproject.toml").write_text('[project]\nname = "shell-sample-tap"\nversion = "0.1.0"\n')

    if workflows is None:
        workflows = {"ci.yml": _caller(_SHA), "nightly.yml": _caller(_SHA)}
    if workflows:
        wf_dir = repo / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        for name, content in workflows.items():
            (wf_dir / name).write_text(content)
    for rel, content in (codeowners or {}).items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return repo


def _check(result: ValidationResult, check_id: str) -> CheckResult:
    matches = [c for c in result.checks if c.id == check_id]
    assert len(matches) == 1, f"expected exactly one {check_id} check, got {len(matches)}"
    return matches[0]


def _messages(check: CheckResult) -> str:
    return " | ".join(m.text for m in check.messages)


# ---------------------------------------------------------------------------
# Opt-in (req-tap-plugin-validate-repo-1)
# ---------------------------------------------------------------------------


class TestOptIn:
    def test_repo_checks_absent_by_default(self, tmp_path: Path) -> None:
        """Without --repo the check set is unchanged — the reusable CI's verdict does not move."""
        result = validate_plugin(_make_repo(tmp_path, workflows={}))
        assert [c for c in result.checks if c.id.startswith("repo-")] == []

    def test_repo_checks_present_when_asked(self, tmp_path: Path) -> None:
        result = validate_plugin(_make_repo(tmp_path), repo_scope=True)
        ids = {c.id for c in result.checks if c.id.startswith("repo-")}
        assert ids == {"repo-codeowners", "repo-workflows", "repo-ci-caller-pin"}

    def test_conformant_shell_passes(self, tmp_path: Path) -> None:
        """A repository with both lanes, a SHA pin and an owner file has nothing to report."""
        repo = _make_repo(tmp_path, codeowners={".github/CODEOWNERS": "* @unified-systems-com/maintainers\n"})
        result = validate_plugin(repo, repo_scope=True)
        for check_id in ("repo-codeowners", "repo-workflows", "repo-ci-caller-pin"):
            assert _check(result, check_id).status == "pass", _messages(_check(result, check_id))


# ---------------------------------------------------------------------------
# CODEOWNERS (req-tap-plugin-validate-repo-2)
# ---------------------------------------------------------------------------


class TestCodeowners:
    def test_absent_warns_and_does_not_fail(self, tmp_path: Path) -> None:
        """C4 is deliberately unmet: absence is reported, never failed."""
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-codeowners")
        assert check.status == "warn"
        assert "C4" in _messages(check)

    def test_strict_promotes_the_absence(self, tmp_path: Path) -> None:
        """The warning is still a warning — --strict promotes it like any other, which is why
        the repo scope is opt-in rather than on in the conformance gate."""
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True, strict=True), "repo-codeowners")
        assert check.status == "fail"

    def test_comment_only_file_fails(self, tmp_path: Path) -> None:
        """Presence is not correctness: a file with no rule names nobody while looking like it does."""
        repo = _make_repo(tmp_path, codeowners={"CODEOWNERS": "# owners to be decided\n\n"})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
        assert check.status == "fail"
        assert "declares no owner rule" in _messages(check)

    def test_pattern_without_owner_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, codeowners={"docs/CODEOWNERS": "*\n"})
        assert _check(validate_plugin(repo, repo_scope=True), "repo-codeowners").status == "fail"

    def test_every_github_location_is_recognised(self, tmp_path: Path) -> None:
        for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            repo = _make_repo(tmp_path / rel.replace("/", "_"), codeowners={rel: "* @owner\n"})
            check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
            assert check.status == "pass", f"{rel}: {_messages(check)}"
            assert check.details == {"locations": [rel]}


# ---------------------------------------------------------------------------
# Lanes (req-tap-plugin-validate-repo-3)
# ---------------------------------------------------------------------------


class TestWorkflows:
    def test_missing_ci_lane_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-workflows")
        assert check.status == "fail"
        assert "no .github/workflows/ci.yml" in _messages(check)

    def test_missing_nightly_only_warns(self, tmp_path: Path) -> None:
        """Nightly failure routing is unruled (tap#367), so its absence is not forced."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-workflows")
        assert check.status == "warn"
        assert check.details == {"present": [".github/workflows/ci.yml"]}

    def test_the_nightly_warning_does_not_overstate_what_is_missing(self, tmp_path: Path) -> None:
        """Core's nightly-plugins.yml discovers every plugin repo and runs the conformance gate
        against core main, so the missing per-repo lane is the DEEPER half, not all coverage. The
        first draft said "nothing probes core main", which was false for the 8 repos concerned."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA)})
        text = _messages(_check(validate_plugin(repo, repo_scope=True), "repo-workflows"))
        assert "nothing probes core `main`" not in text
        assert "nightly-plugins.yml still discovers this repository" in text

    def test_no_workflow_dir_fails_both_lane_and_pin(self, tmp_path: Path) -> None:
        result = validate_plugin(_make_repo(tmp_path, workflows={}), repo_scope=True)
        assert _check(result, "repo-workflows").status == "fail"
        assert _check(result, "repo-ci-caller-pin").status == "fail"


# ---------------------------------------------------------------------------
# The pin (req-tap-plugin-validate-repo-4)
# ---------------------------------------------------------------------------


class TestCallerPin:
    def test_release_sbom_caller_is_held_to_the_same_rule(self, tmp_path: Path) -> None:
        """The rule is about the prefix, not one file. The first version of this check looked only
        at plugin-ci.yml and missed `plugin-release-sbom.yml@main` sitting beside it in
        tap-plugin-gryphon-playground — the release-side workflow, where an unpinned call matters
        more rather than less (tap#376's done-test names every @main reusable workflow)."""
        sbom = textwrap.dedent(
            f"""\
            name: release-sbom
            on: [release]
            jobs:
              sbom:
                uses: {REUSABLE_PREFIX}plugin-release-sbom.yml@main
            """
        )
        repo = _make_repo(
            tmp_path,
            workflows={"ci.yml": _caller(_SHA), "nightly.yml": _caller(_SHA), "release-sbom.yml": sbom},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail"
        assert "pins plugin-release-sbom.yml to `main`" in _messages(check)
        assert [m.path for m in check.messages if m.severity == "error"] == [".github/workflows/release-sbom.yml"]

    def test_a_pinned_release_sbom_caller_passes(self, tmp_path: Path) -> None:
        sbom = f"jobs:\n  sbom:\n    uses: {REUSABLE_PREFIX}plugin-release-sbom.yml@{_SHA}\n"
        repo = _make_repo(
            tmp_path,
            workflows={"ci.yml": _caller(_SHA), "nightly.yml": _caller(_SHA), "release-sbom.yml": sbom},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "pass", _messages(check)
        assert check.details is not None
        assert {c["workflow"] for c in check.details["callers"]} == {"plugin-ci.yml", "plugin-release-sbom.yml"}

    def test_a_pinned_sbom_caller_does_not_satisfy_the_ci_lane(self, tmp_path: Path) -> None:
        """A repo that calls only the release workflow still has no admission gate — the ci.yml
        requirement keys on plugin-ci.yml, not on any core workflow being called somewhere."""
        sbom = f"jobs:\n  sbom:\n    uses: {REUSABLE_PREFIX}plugin-release-sbom.yml@{_SHA}\n"
        repo = _make_repo(tmp_path, workflows={"ci.yml": sbom, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail"
        assert "does not call" in _messages(check)

    def test_sha_pin_passes_and_is_recorded(self, tmp_path: Path) -> None:
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "pass"
        assert check.details is not None
        assert [c["ref"] for c in check.details["callers"]] == [_SHA, _SHA]

    def test_tag_pin_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller("v1"), "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail"
        assert "pins plugin-ci.yml to `v1`, which is a name, not a pin" in _messages(check)

    def test_branch_pin_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller("main"), "nightly.yml": _caller(_SHA)})
        assert _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin").status == "fail"

    def test_short_sha_fails(self, tmp_path: Path) -> None:
        """An abbreviated SHA is ambiguous and GitHub does not resolve it for `uses:`."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA[:12]), "nightly.yml": _caller(_SHA)})
        assert _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin").status == "fail"

    def test_unpinned_caller_fails(self, tmp_path: Path) -> None:
        body = _caller(_SHA).replace(f"@{_SHA}", "")
        repo = _make_repo(tmp_path, workflows={"ci.yml": body, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail"
        assert "no ref at all" in _messages(check)

    def test_hand_rolled_lane_fails(self, tmp_path: Path) -> None:
        """A ci.yml that calls the reusable lane nowhere is the drift it exists to remove."""
        hand_rolled = textwrap.dedent(
            """\
            name: ci
            on: [pull_request]
            jobs:
              tests:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
                  - run: pytest
            """
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": hand_rolled, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail"
        assert "does not call" in _messages(check)

    def test_other_actions_are_not_held_to_the_caller_rule(self, tmp_path: Path) -> None:
        """Only calls of core's reusable lane are this check's business; a third-party action's
        pin is zizmor's job, and reporting it here would duplicate a check that already exists."""
        body = _caller(_SHA).replace(
            "          plugin_slug: shell_sample\n",
            "          plugin_slug: shell_sample\n",
        ) + textwrap.dedent(
            """\
              extra:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
            """
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": body, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "pass", _messages(check)

    def test_commented_out_caller_is_not_read_as_live(self, tmp_path: Path) -> None:
        """A pin merely discussed in a comment must not satisfy — nor break — the check."""
        body = _caller(_SHA).replace(
            "    uses:",
            f"    # historic: {REUSABLE_CALLER}@v1\n    uses:",
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": body, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "pass", _messages(check)


# ---------------------------------------------------------------------------
# The envelope (req-tap-plugin-validate-repo-5)
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_repo_findings_serialise_against_the_published_schema(self, tmp_path: Path) -> None:
        """to_json self-validates, so a drifted envelope raises rather than shipping."""
        repo = _make_repo(tmp_path, workflows={"nightly.yml": _caller("v1")})
        result = validate_plugin(repo, repo_scope=True)
        assert not result.ok
        assert '"repo-ci-caller-pin"' in result.to_json()

    def test_findings_carry_a_path(self, tmp_path: Path) -> None:
        """A repair hook needs the path, and it is already carried on every message."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller("v1"), "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert [m.path for m in check.messages if m.severity == "error"] == [".github/workflows/ci.yml"]
