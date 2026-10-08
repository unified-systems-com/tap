"""Repository-scope conformance checks (req-tap-plugin-validate-repo).

The shell around the package: the CI lanes, the pin on core's reusable workflow, and the file
that names a human owner. Every check here is exercised in both directions — a conformant shell
passes and each specific deviation fails or warns — because a check that has only ever been seen
to pass has not been shown to be capable of failing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tap_plugins.validate.repo import (
    PROTECTED_RELEASE_TAGS,
    REUSABLE_CALLER,
    REUSABLE_PREFIX,
    REUSABLE_RELEASE,
)
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


def _nightly(
    *,
    harness_ref: str = "main",
    reporter: bool = True,
    identify: str = "marker",
    limit: bool = True,
    guard: bool = True,
    concurrency: bool = True,
) -> str:
    """A nightly lane. Conformant by default; each keyword removes exactly one property.

    The default is the shape `tap#832` settled for core's own nightly: the issue is found by a
    hidden marker in the body this job wrote AND its author, the listing passes `--limit` and
    refuses when it hits it, and the job carries a `concurrency` group.

    `guard=False` keeps the `--limit` and drops the count comparison. That combination used to be
    the DEFAULT here, which made this fixture not the safe shape it claimed to be — a `--limit` with
    nothing checking the returned length still cannot tell "none open" from "past the page".
    """
    ref = f"\n    with:\n      plugin_slug: shell_sample\n      harness_ref: {harness_ref}" if harness_ref else ""
    if not reporter:
        return f'name: nightly\non:\n  schedule:\n    - cron: "0 3 * * *"\njobs:\n  main:\n    uses: {REUSABLE_CALLER}@{_SHA}{ref}\n'

    select = {
        "marker": '[.[] | select(.author.login == "app/github-actions" and ((.body // "") | contains($m)))]',
        "title": '[.[] | select(.title == "Nightly red vs core main")]',
        "marker-only": '[.[] | select(((.body // "") | contains($m)))]',
        "author-only": '[.[] | select(.author.login == "app/github-actions")]',
        "title-and-marker": (
            '[.[] | select(.title == "Nightly red vs core main" and .author.login == "app/github-actions"'
            ' and ((.body // "") | contains($m)))]'
        ),
    }[identify]
    listing = (
        "gh issue list --repo x --state open --limit 1000 --json number,author,body"
        if limit
        else ("gh issue list --repo x --state open --json number,author,body")
    )
    guard_line = '          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n' if guard else ""
    conc = (
        "    concurrency:\n      group: nightly-owner-issue\n      cancel-in-progress: false\n" if concurrency else ""
    )
    return (
        "name: nightly\n"
        "on:\n"
        '  schedule:\n    - cron: "0 3 * * *"\n'
        "jobs:\n"
        "  main:\n"
        f"    uses: {REUSABLE_CALLER}@{_SHA}{ref}\n"
        "  owner-issue:\n"
        "    needs: [main]\n"
        "    runs-on: ubuntu-latest\n"
        f"{conc}"
        "    permissions:\n"
        "      issues: write\n"
        "    steps:\n"
        "      - name: file or close\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        f'          listed="$({listing})"\n'
        + guard_line
        + f'          existing="$(jq -r --arg m "$MARKER" \'{select} | .[0].number // empty\' <<<"$listed")"\n'
    )


def _make_repo(
    tmp_path: Path,
    *,
    workflows: dict[str, str] | None = None,
    codeowners: dict[str, str] | None = None,
    extra_files: dict[str, str] | None = None,
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
        workflows = {"ci.yml": _caller(_SHA), "nightly.yml": _nightly()}
    if workflows:
        wf_dir = repo / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        for name, content in workflows.items():
            (wf_dir / name).write_text(content)
    for rel, content in (codeowners or {}).items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    for rel, content in (extra_files or {}).items():
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
        assert ids == {
            "repo-codeowners",
            "repo-workflows",
            "repo-ci-caller-pin",
            "repo-caller-permissions",
            "repo-nightly-shape",
            "repo-release-lane",
            "repo-waiver-ledger",
        }

    def test_conformant_shell_passes(self, tmp_path: Path) -> None:
        """A repository with both lanes, a SHA pin and an owner file has nothing to report."""
        repo = _make_repo(tmp_path, codeowners={".github/CODEOWNERS": "* @unified-systems-com/maintainers\n"})
        result = validate_plugin(repo, repo_scope=True)
        for check_id in (
            "repo-codeowners",
            "repo-workflows",
            "repo-ci-caller-pin",
            "repo-nightly-shape",
            "repo-waiver-ledger",
        ):
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
        assert "is the CODEOWNERS GitHub consults and it declares no owner rule" in _messages(check)

    def test_pattern_without_owner_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, codeowners={"docs/CODEOWNERS": "*\n"})
        assert _check(validate_plugin(repo, repo_scope=True), "repo-codeowners").status == "fail"

    def test_a_ruleless_file_beside_a_populated_one_warns_rather_than_fails(self, tmp_path: Path) -> None:
        """GitHub consults ONE of the three locations by a precedence this check does not resolve
        offline. Failing on a ruleless file beside a populated one would reject a repository whose
        ownership is in fact enforced — the file failed on may be the one GitHub ignores."""
        repo = _make_repo(
            tmp_path,
            codeowners={".github/CODEOWNERS": "* @unified-systems-com/maintainers\n", "docs/CODEOWNERS": "# tbd\n"},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
        assert check.status == "warn", _messages(check)
        assert "sits at a path GitHub ignores" in _messages(check)
        assert check.details is not None
        assert check.details["with_rules"] == [".github/CODEOWNERS"]
        assert check.details["effective"] == ".github/CODEOWNERS"

    def test_an_unresolvable_owner_token_is_not_an_owner(self) -> None:
        """`* @` is syntactically a rule and resolves to nobody. A check whose point is that
        presence is not correctness cannot itself count a present non-owner."""
        from tap_plugins.validate.repo import _codeowners_rules

        assert _codeowners_rules("* @") == []
        assert _codeowners_rules("* @/") == []
        assert _codeowners_rules("* @org/") == []
        assert _codeowners_rules("* @user") == ["* @user"]
        assert _codeowners_rules("* @org/team") == ["* @org/team"]
        assert _codeowners_rules("* owner@example.com") == ["* owner@example.com"]

    def test_a_ruleless_effective_file_fails_even_when_an_ignored_one_has_rules(self, tmp_path: Path) -> None:
        """GitHub consults the first of .github/, root, docs/ and IGNORES the rest. So rules in an
        ignored file do not rescue an effective file that names nobody — the opposite direction from
        the ignored-ruleless case, and the reason precedence has to be modelled rather than avoided."""
        repo = _make_repo(
            tmp_path,
            codeowners={".github/CODEOWNERS": "# tbd\n", "docs/CODEOWNERS": "* @unified-systems-com/maintainers\n"},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
        assert check.status == "fail", _messages(check)
        assert "is the CODEOWNERS GitHub consults and it declares no owner rule" in _messages(check)
        assert "at a path GitHub ignores once this one exists" in _messages(check)

    def test_ruleless_in_every_location_still_fails(self, tmp_path: Path) -> None:
        """Whichever file GitHub consults, none of them names anybody."""
        repo = _make_repo(tmp_path, codeowners={"CODEOWNERS": "# tbd\n", "docs/CODEOWNERS": "*\n"})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
        assert check.status == "fail"
        assert "is the CODEOWNERS GitHub consults and it declares no owner rule" in _messages(check)

    def test_every_github_location_is_recognised(self, tmp_path: Path) -> None:
        for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            repo = _make_repo(tmp_path / rel.replace("/", "_"), codeowners={rel: "* @owner\n"})
            check = _check(validate_plugin(repo, repo_scope=True), "repo-codeowners")
            assert check.status == "pass", f"{rel}: {_messages(check)}"
            assert check.details == {"locations": [rel], "effective": rel, "with_rules": [rel]}


# ---------------------------------------------------------------------------
# Lanes (req-tap-plugin-validate-repo-3)
# ---------------------------------------------------------------------------


class TestWorkflows:
    def test_missing_ci_lane_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-workflows")
        assert check.status == "fail"
        assert "no .github/workflows/ci.yml" in _messages(check)

    def test_missing_nightly_fails(self, tmp_path: Path) -> None:
        """The ratchet has fired: every plugin repository carries the lane, so absence is a failure.

        Who receives the nightly's red is still unruled (tap#367); that decides routing, not
        whether the lane must exist.
        """
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-workflows")
        assert check.status == "fail"
        assert check.details == {"present": [".github/workflows/ci.yml"]}

    def test_the_nightly_failure_says_coverage_is_now_zero(self, tmp_path: Path) -> None:
        """With the central sweep retired, a repository with no nightly is covered by NOTHING.

        The message used to soften that by naming the sweep, and the softened form is now false.
        The final assertion is the regression guard: a retired workflow must not reappear here as
        reassurance, which is the direction an earlier draft of this message went wrong in.
        """
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA)})
        text = _messages(_check(validate_plugin(repo, repo_scope=True), "repo-workflows"))
        assert "nothing boots this plugin against core `main`" in text
        assert "covered by nothing" in text
        assert "nightly-plugins" not in text

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

    def test_a_quoted_uses_key_cannot_hide_an_unpinned_caller(self, tmp_path: Path) -> None:
        """`'uses':` is ordinary YAML. A scanner anchored on an UNQUOTED key at the start of a line
        walks past it, which would let a repository keep an unpinned release caller alive behind a
        correctly pinned ci.yml and still pass. A check that misses a legal spelling reports the
        absence of what it cannot see, which is worse than not checking."""
        sbom = textwrap.dedent(
            f"""\
            name: release-sbom
            on: [release]
            jobs:
              release:
                'uses': {REUSABLE_PREFIX}plugin-release-sbom.yml@main
            """
        )
        repo = _make_repo(
            tmp_path,
            workflows={"ci.yml": _caller(_SHA), "nightly.yml": _caller(_SHA), "release-sbom.yml": sbom},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail", _messages(check)
        assert "pins plugin-release-sbom.yml to `main`" in _messages(check)

    def test_every_yaml_spelling_of_a_job_level_call_is_seen(self) -> None:
        """The scanner went through three lexical drafts and each was defeated by a spelling it had
        not enumerated: a quoted key, then a value inside `run:`, then a flow mapping. Enumerating
        YAML's spellings is the parser's job, so these are asserted against the parsing path."""
        from tap_plugins.validate.repo import _job_uses

        assert _job_uses(f"jobs:\n  tap:\n    uses: {REUSABLE_CALLER}@{_SHA}\n")[0] == [
            (3, f"{REUSABLE_CALLER}@{_SHA}")
        ]
        assert _job_uses(f"jobs:\n  tap:\n    'uses': {REUSABLE_CALLER}@main\n")[0] == [(3, f"{REUSABLE_CALLER}@main")]
        assert _job_uses(f"jobs:\n  tap: {{uses: {REUSABLE_CALLER}@main}}\n")[0] == [(2, f"{REUSABLE_CALLER}@main")]
        assert _job_uses(f"jobs:\n  tap:\n    uses: >-\n      {REUSABLE_CALLER}@main\n")[0] == [
            (3, f"{REUSABLE_CALLER}@main")
        ]
        assert _job_uses("jobs:\n  a:\n    uses: x@1\n  b:\n    uses: y@2\n")[0] == [(3, "x@1"), (5, "y@2")]

    def test_a_flow_mapping_caller_is_held_to_the_pin_rule(self, tmp_path: Path) -> None:
        """A flow mapping is the spelling the lexical scan could not see, and missing a caller is
        fail-open for the PIN half: a caller the scan cannot see is a bad pin it cannot report."""
        sbom = f"name: release-sbom\non: [release]\njobs:\n  release: {{uses: {REUSABLE_PREFIX}plugin-release-sbom.yml@main}}\n"
        repo = _make_repo(
            tmp_path,
            workflows={"ci.yml": _caller(_SHA), "nightly.yml": _caller(_SHA), "release-sbom.yml": sbom},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail", _messages(check)
        assert "pins plugin-release-sbom.yml to `main`" in _messages(check)

    def test_a_uses_inside_a_run_script_is_not_a_caller(self) -> None:
        """The same scan feeds the PRESENCE proof — does this repo call the reusable lane at all? —
        where a false positive is fail-open: a hand-rolled lane echoing the string would satisfy
        it. So over-reporting is NOT the safe direction for a shared scanner; it inherits the
        stricter of its callers' requirements."""
        from tap_plugins.validate.repo import _job_uses

        assert _job_uses(f"run: echo uses: {REUSABLE_CALLER}@{_SHA}")[0] == []
        assert (
            _job_uses(
                f"jobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps:\n"
                f"      - run: echo uses: {REUSABLE_CALLER}@{_SHA}\n"
            )[0]
            == []
        )
        assert (
            _job_uses(
                f"jobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps:\n"
                f"      - run: |\n          uses: {REUSABLE_CALLER}@{_SHA}\n"
            )[0]
            == []
        )

    def test_a_step_level_uses_is_not_a_workflow_caller(self) -> None:
        """Only `jobs.<id>.uses` can call a workflow; a step's `uses` names an action."""
        from tap_plugins.validate.repo import _job_uses

        assert (
            _job_uses("jobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n")[0]
            == []
        )

    def test_the_lexical_fallback_declares_its_reduced_coverage(self, tmp_path: Path, monkeypatch) -> None:
        """With no YAML parser the scan is line-based and cannot see a flow mapping, so the check
        FAILS rather than warns: a warning leaves a non-strict run reporting ok, which makes an
        inconclusive pin check indistinguishable from a conformant one."""
        import builtins

        real_import = builtins.__import__

        def _no_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml for this test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_yaml)

        from tap_plugins.validate.repo import _job_uses, _job_uses_from_yaml

        assert _job_uses_from_yaml("jobs: {}") is None
        entries, complete = _job_uses(f"jobs:\n  tap:\n    uses: {REUSABLE_CALLER}@{_SHA}\n")
        assert complete is False
        assert entries == [(3, f"{REUSABLE_CALLER}@{_SHA}")]

        repo = _make_repo(tmp_path, codeowners={"CODEOWNERS": "* @owner\n"})
        result = validate_plugin(repo, repo_scope=True)
        check = _check(result, "repo-ci-caller-pin")
        assert check.status == "fail", _messages(check)
        assert "reports INCONCLUSIVE as a failure rather than a pass" in _messages(check)
        assert result.ok is False, "an inconclusive pin check must not produce a passing verdict"
        assert "no YAML parser available" in _messages(check)
        assert check.details is not None
        assert check.details["lexical_only"] == [".github/workflows/ci.yml", ".github/workflows/nightly.yml"]

    def test_a_hand_rolled_lane_cannot_echo_its_way_to_conformance(self, tmp_path: Path) -> None:
        """The end-to-end form of the round-2 finding: the presence proof must not be satisfiable
        by a string in a run: script."""
        hand_rolled = textwrap.dedent(
            f"""\
            name: ci
            on: [pull_request]
            jobs:
              tests:
                runs-on: ubuntu-latest
                steps:
                  - run: echo uses: {REUSABLE_CALLER}@{_SHA}
            """
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": hand_rolled, "nightly.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-ci-caller-pin")
        assert check.status == "fail", _messages(check)
        assert "does not call" in _messages(check)

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


# ---------------------------------------------------------------------------
# The caller's grant (req-tap-plugin-validate-repo-8)
# ---------------------------------------------------------------------------


def _caller_with_grant(ref: str, grant: str | None) -> str:
    perms = f"    permissions:\n      {grant}\n" if grant else ""
    return (
        "name: ci\non: [pull_request]\npermissions:\n  contents: read\n\njobs:\n  tap:\n"
        + perms
        + f"    uses: {REUSABLE_CALLER}@{ref}\n    with:\n      plugin_slug: shell_sample\n"
    )


def _caller_with_workflow_grant(ref: str, workflow_grant: str) -> str:
    """A caller whose job declares NO block, so the WORKFLOW grant is the effective one.

    The inheriting shape. `_caller_with_grant` fixes the workflow level at `contents: read`, which
    cannot express an inherited `contents: write` or GitHub's `read-all`/`write-all` shorthand —
    the two runnable shapes that an equality test silently failed.
    """
    return (
        f"name: ci\non: [pull_request]\npermissions:\n  {workflow_grant}\n\njobs:\n  tap:\n"
        f"    uses: {REUSABLE_CALLER}@{ref}\n    with:\n      plugin_slug: shell_sample\n"
    )


class TestCallerPermissions:
    def test_the_full_grant_passes(self, tmp_path: Path) -> None:
        """Both scopes on the calling job. `contents: read` is not optional: the lane's own jobs
        declare it, and a job-level block replaces the workflow grant rather than merging."""
        grant = "contents: read\n      security-events: write"
        repo = _make_repo(
            tmp_path,
            workflows={"ci.yml": _caller_with_grant(_SHA, grant), "nightly.yml": _caller_with_grant(_SHA, grant)},
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "pass", _messages(check)
        assert check.details is not None
        assert [c["granted"] for c in check.details["callers"]] == [True, True]
        assert [c["contents_write"] for c in check.details["callers"]] == [False, False]

    def test_security_events_alone_fails(self, tmp_path: Path) -> None:
        """THE REGRESSION. This exact shape was asserted to PASS by a test called
        `test_the_narrow_grant_passes`, and on 2026-09-29 eight repositories adopted it — following
        this check's own over-grant warning — and every CI run in all eight died at startup with
        zero jobs and no log. A job-level block replaces the workflow grant, so naming only
        `security-events` grants no `contents`, and the lane declares `contents: read`."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller_with_grant(_SHA, "security-events: write")})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "fail", _messages(check)
        text = _messages(check)
        assert "contents: read" in text
        assert "startup_failure" in text

    def test_the_over_grant_message_says_narrow_not_remove(self, tmp_path: Path) -> None:
        """The wording is the defect that caused the outage: a reader told to REMOVE `contents:
        write` produces a block with no `contents` at all."""
        grant = "contents: write\n      security-events: write"
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller_with_grant(_SHA, grant)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        text = _messages(check)
        assert "NARROW it to `contents: read`" in text
        assert "do not remove the scope" in text

    def test_no_permissions_block_warns_and_says_what_the_symptom_will_be(self, tmp_path: Path) -> None:
        """A job that declares nothing inherits the workflow default, which is not the same as
        granting nothing — and the failure it produces is a whole-run refusal, not a failed step."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller_with_grant(_SHA, None)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn"
        assert "declares no job-level `permissions:` block" in _messages(check)
        assert "startup_failure naming nothing" in _messages(check)

    def test_both_grants_together_still_reports_the_broad_one(self, tmp_path: Path) -> None:
        """A caller holding the narrow grant AND `contents: write` must not read as fully
        conformant: the whole point of the change is that nobody needs repository write for
        scanning, and a legacy grant that passes silently survives the migration by being
        invisible."""
        both = _caller_with_grant(_SHA, "security-events: write\n      contents: write")
        conformant = _caller_with_grant(_SHA, "contents: read\n      security-events: write")
        repo = _make_repo(tmp_path, workflows={"ci.yml": both, "nightly.yml": conformant})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn", _messages(check)
        assert "grants `contents: write` on the job calling the reusable lane" in _messages(check)
        assert check.details is not None
        assert [c["contents_write"] for c in check.details["callers"]] == [True, False]

    def test_contents_write_is_not_the_grant_that_is_wanted(self, tmp_path: Path) -> None:
        """The old arrangement forced repository write for a reporting side effect. The grant is
        narrow on purpose, so a caller holding `contents: write` instead still warns."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller_with_grant(_SHA, "contents: write")})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn"
        assert "security-events: write" in _messages(check)

    def test_a_ratchet_not_a_failure_yet(self, tmp_path: Path) -> None:
        """Core's uploading job is not live, so a missing grant must not red a repository for a
        requirement that does not exist yet; the message says it becomes a failure after."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller_with_grant(_SHA, None)})
        result = validate_plugin(repo, repo_scope=True)
        assert _check(result, "repo-caller-permissions").status == "warn"
        assert "a failure after" in _messages(_check(result, "repo-caller-permissions"))

    def test_only_the_reusable_lane_caller_is_held_to_the_grant(self, tmp_path: Path) -> None:
        """A job calling something else is not this check's business."""
        other = (
            "name: ci\non: [pull_request]\njobs:\n  tap:\n"
            f"    permissions:\n      contents: read\n      security-events: write\n    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "  extra:\n    uses: some-org/other/.github/workflows/x.yml@main\n"
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": other})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "pass", _messages(check)
        assert check.details is not None
        assert len(check.details["callers"]) == 1


# ---------------------------------------------------------------------------
# The nightly lane's shape (req-tap-plugin-validate-repo)
# ---------------------------------------------------------------------------


class TestNightlyShape:
    """Both directions for every property, because the fleet fails all three of the reporter
    rules at once — a check that has only ever been seen to fire on that one shape has not been
    shown to be capable of passing."""

    def test_conformant_nightly_passes(self, tmp_path: Path) -> None:
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass", _messages(check)

    def test_absent_nightly_is_not_this_checks_finding(self, tmp_path: Path) -> None:
        """repo-workflows owns the absence and fails on it; saying it twice double-counts it."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass"
        assert "repo-workflows" in _messages(check)

    def test_floor_pinned_nightly_fails(self, tmp_path: Path) -> None:
        """A nightly at the declared floor re-answers ci.yml's question on a clock."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(harness_ref="v0.2.0")})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail"
        assert "harness_ref: main" in _messages(check)
        assert "v0.2.0" in _messages(check), "the finding must name what it found, not only what it wanted"

    def test_no_harness_ref_fails(self, tmp_path: Path) -> None:
        """An omitted harness_ref means the declared floor — the same defect, spelled by absence."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(harness_ref="")})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail"
        assert "the declared floor" in _messages(check)

    def test_dispatch_input_defaulting_to_main_is_accepted(self, tmp_path: Path) -> None:
        """gryphon-playground's real spelling. A literal-equality test reported it as not probing
        main when it does, which is the false red this pattern exists to avoid."""
        expr = "${{ inputs.harness_ref || 'main' }}"
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(harness_ref=expr)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass", _messages(check)

    def test_no_reporter_warns_and_names_the_alternative(self, tmp_path: Path) -> None:
        """tap#439 withdrew the playground's reporter deliberately; a central collector is a
        legitimate second answer, so absence is reported, never failed."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(reporter=False)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "warn"
        assert "central" in _messages(check)

    def test_title_only_identification_fails(self, tmp_path: Path) -> None:
        """The steerable write: a stranger's issue carrying that title gets closed by the bot."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(identify="title")})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail"
        assert "narrows by BOTH" in _messages(check) or "does not narrow by" in _messages(check)

    def test_title_beside_marker_and_author_is_accepted(self, tmp_path: Path) -> None:
        """Matching the title is not itself the defect — matching ONLY the title is. A job that
        narrows by title AND by evidence only it could have written is safe, and failing it would
        push authors to drop a harmless clause."""
        repo = _make_repo(
            tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(identify="title-and-marker")}
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass", _messages(check)

    def test_listing_without_limit_warns(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(limit=False)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "warn"
        assert "--limit" in _messages(check)

    def test_reporter_without_concurrency_warns(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": _nightly(concurrency=False)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "warn"
        assert "concurrency" in _messages(check)

    def test_the_fleet_shape_reports_all_three(self, tmp_path: Path) -> None:
        """The shape 15 of 16 nightlies actually carry: one fix, three findings."""
        repo = _make_repo(
            tmp_path,
            workflows={
                "ci.yml": _caller(_SHA),
                "nightly.yml": _nightly(identify="title", limit=False, concurrency=False),
            },
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail"
        assert len([m for m in check.messages if m.severity in ("error", "warning")]) == 3


class TestNightlyInheritedFromCore:
    """The shape `plugin-nightly.yml` creates. It must PASS, and the reason is not politeness:
    the pre-existing rules would have failed it (no direct plugin-ci call, no harness_ref), so a
    repository that adopted the fix would have been reported as the broken one."""

    @staticmethod
    def _thin(grant: str | None = "issues: write") -> str:
        perms = "    permissions:\n      contents: read\n      security-events: write\n"
        if grant:
            perms += f"      {grant}\n"
        return (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "48 10 * * *"\n'
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@{_SHA}\n"
            f"{perms}"
            "    with:\n      plugin_slug: shell_sample\n"
        )

    def test_thin_caller_of_the_reusable_nightly_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": self._thin()})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass", _messages(check)
        assert "inherits the nightly from core" in _messages(check)

    def test_thin_caller_without_issues_write_fails(self, tmp_path: Path) -> None:
        """The called workflow declares `issues: write`; a caller short of it is refused before
        any job exists, which surfaces as startup_failure naming nothing."""
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": self._thin(grant=None)})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail"
        assert "issues: write" in _messages(check)
        assert "refused at startup" in _messages(check)


class TestWaiverLedger:
    """Q94b/Q94c: an ABSENT ledger is the state to want and is never a finding; a PRESENT one
    must justify every entry. Both directions, because the tempting default is the wrong one."""

    def test_absent_ledger_is_not_a_finding(self, tmp_path: Path) -> None:
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-waiver-ledger")
        assert check.status == "pass"
        assert "nothing is waived" in _messages(check)

    def test_reasoned_waivers_pass(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / ".trivyignore").write_text(
            "# CVE-2026-1 (libfoo): not reachable — TAP never invokes the codec path.\n"
            "#   Accepted A. Maintainer, 2026-09-26. Revisit on libfoo bump.\n"
            "CVE-2026-1\n"
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-waiver-ledger")
        assert check.status == "pass", _messages(check)

    def test_bare_waiver_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / ".trivyignore").write_text("CVE-2026-2\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-waiver-ledger")
        assert check.status == "fail"
        assert "CVE-2026-2" in _messages(check)

    def test_a_blank_line_breaks_the_link(self, tmp_path: Path) -> None:
        """Otherwise one comment at the top of a file reads as the reason for everything below."""
        repo = _make_repo(tmp_path)
        (repo / ".trivyignore").write_text("# a real reason, but detached\n\nCVE-2026-3\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-waiver-ledger")
        assert check.status == "fail"

    def test_a_bare_hash_is_not_a_reason(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / ".trivyignore").write_text("#\nCVE-2026-4\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-waiver-ledger")
        assert check.status == "fail"


def _caller_with_workflow_grant_literal(ref: str, literal: str) -> str:
    """A caller whose WORKFLOW `permissions:` is GitHub's scalar shorthand, not a mapping.

    `permissions: read-all` and `write-all` are strings. The map-form helpers cannot express them,
    and that is exactly why the shorthand went unhandled: nothing in the corpus had this shape.
    """
    return (
        f"name: ci\non: [pull_request]\npermissions: {literal}\n\njobs:\n  tap:\n"
        f"    uses: {REUSABLE_CALLER}@{ref}\n    with:\n      plugin_slug: shell_sample\n"
    )


class TestEffectiveGrantIsNotEquality:
    """The grant arithmetic once compared scopes for EQUALITY, so shapes GitHub accepts were
    failed. Fail-closed, so never a bypass — but a check that reds a runnable
    repository teaches people to "fix" a working one, which is how the 2026-09-29 outage was
    instructed in the first place. The same error class as the `-8` half of this change.
    """

    def test_inherited_contents_write_satisfies_the_read_requirement(self, tmp_path: Path) -> None:
        """`write` includes `read`. A job inheriting `contents: write` can read contents, so the
        callee's `contents: read` is satisfied and the run starts — it must not hard-fail."""
        caller = _caller_with_workflow_grant(_SHA, "contents: write\n  security-events: write")
        repo = _make_repo(tmp_path, workflows={"ci.yml": caller})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn", _messages(check)
        assert "missing `contents: read`" not in _messages(check)
        assert check.details is not None
        assert check.details["callers"][0]["granted"] is True

    def test_the_inherited_over_grant_is_still_reported(self, tmp_path: Path) -> None:
        """Satisfying the requirement is not the same as being narrow. An inherited
        `contents: write` is repository write just as a job-level one is, and the old job-block-only
        test for it reported nothing at all for the inheriting shape."""
        caller = _caller_with_workflow_grant(_SHA, "contents: write\n  security-events: write")
        repo = _make_repo(tmp_path, workflows={"ci.yml": caller})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert "NARROW it to `contents: read`" in _messages(check)
        assert check.details is not None
        assert check.details["callers"][0]["contents_write"] is True

    def test_read_all_shorthand_grants_contents_read(self, tmp_path: Path) -> None:
        """`permissions: read-all` is a STRING, not a map, so the parser returned None and every
        scope read as missing — including `contents`, which the shorthand plainly grants."""
        caller = _caller_with_workflow_grant_literal(_SHA, "read-all")
        repo = _make_repo(tmp_path, workflows={"ci.yml": caller})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn", _messages(check)
        assert "missing `security-events: write`" in _messages(check)
        assert "missing `contents: read`" not in _messages(check)

    def test_write_all_shorthand_satisfies_both_scopes(self, tmp_path: Path) -> None:
        """`write-all` grants write on every scope, which covers both requirements — reported as an
        over-grant rather than a missing one."""
        caller = _caller_with_workflow_grant_literal(_SHA, "write-all")
        repo = _make_repo(tmp_path, workflows={"ci.yml": caller})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-caller-permissions")
        assert check.status == "warn", _messages(check)
        assert "missing" not in _messages(check)
        assert "NARROW it to `contents: read`" in _messages(check)


class TestReleaseLane:
    """`tap#892`: a repository configured to cut releases, with nothing configured to attest them.

    Every direction, because the trigger is a DECLARATION rather than an event and it would be easy
    to build a check that either reports every plugin that never releases or stays silent until the
    first release — which is the run nobody watches, since it succeeds.
    """

    def _release_lane(
        self, ref: str = _SHA, *, calls_shared: bool = True, grant: str | None = None
    ) -> str:
        """The conformant caller shape, which is the one the fleet actually carries.

        The grant is part of the shape rather than decoration: the lane declares
        `permissions: {}` and its jobs take subsets of `contents: read`, `id-token: write` and
        `attestations: write`, so a caller granting less has its run refused at creation and
        attests nothing. `grant=""` builds the caller with no block at all.
        """
        target = f"{REUSABLE_RELEASE}@{ref}" if calls_shared else f"./.github/workflows/local.yml@{ref}"
        if grant is None:
            grant = "contents: read\n      id-token: write\n      attestations: write"
        block = f"    permissions:\n      {grant}\n" if grant else ""
        return (
            "name: release-sbom\non:\n  push:\n    tags: [\"v*\"]\njobs:\n  release-sbom:\n"
            + block
            + f"    uses: {target}\n    with:\n      plugin_slug: shell_sample\n"
        )

    def test_declares_releases_without_a_lane_fails(self, tmp_path: Path) -> None:
        """The defect as measured in the fleet: release-please onboarded, no release lane."""
        repo = _make_repo(tmp_path)
        (repo / "release-please-config.json").write_text("{}\n")
        (repo / ".release-please-manifest.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail"
        text = _messages(check)
        assert "release-please-config.json" in text
        assert "nobody downstream can verify" in text

    def test_the_manifest_alone_is_a_declaration(self, tmp_path: Path) -> None:
        """A repository mid-onboarding has still said it intends to release."""
        repo = _make_repo(tmp_path)
        (repo / ".release-please-manifest.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail"

    def test_declares_releases_with_a_lane_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "release-please-config.json").write_text("{}\n")
        (repo / ".github" / "workflows" / "release-sbom.yml").write_text(self._release_lane())
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "pass", _messages(check)

    def test_a_repository_that_declares_no_releases_is_not_reported(self, tmp_path: Path) -> None:
        """A plugin consumed only from a boot pin never cuts a tag. Silence is the correct answer,
        and reporting it would teach authors to add configuration to quiet a checker."""
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-release-lane")
        assert check.status == "pass"
        assert "declares no releases" in _messages(check)

    def test_a_lane_without_release_please_is_coherent(self, tmp_path: Path) -> None:
        """A hand-cut tag still reaches the lane, so this pair is not an inconsistency."""
        repo = _make_repo(tmp_path)
        (repo / ".github" / "workflows" / "release-sbom.yml").write_text(self._release_lane())
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "pass"

    def test_a_file_with_the_right_name_is_not_the_property(self, tmp_path: Path) -> None:
        """The check asserts a caller of the shared lane, not a correctly-named file. A hand-rolled
        release workflow produces no attestation a consumer can verify against."""
        repo = _make_repo(tmp_path)
        (repo / "release-please-config.json").write_text("{}\n")
        (repo / ".github" / "workflows" / "release-sbom.yml").write_text(
            self._release_lane(calls_shared=False)
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail"
        assert "no job calls" in _messages(check)

    def test_the_pin_is_not_this_check_s_business(self, tmp_path: Path) -> None:
        """`repo-ci-caller-pin` owns pinning across the whole reusable prefix. Asserting it here too
        would be a second place to fix one rule — so a branch ref passes THIS check and fails that
        one, which is the division of labour the two checks are written to keep."""
        repo = _make_repo(tmp_path)
        (repo / "release-please-config.json").write_text("{}\n")
        (repo / ".github" / "workflows" / "release-sbom.yml").write_text(self._release_lane("main"))
        result = validate_plugin(repo, repo_scope=True)
        assert _check(result, "repo-release-lane").status == "pass"
        assert _check(result, "repo-ci-caller-pin").status == "fail"


    def test_a_lookalike_reusable_path_is_not_the_shared_lane(self, tmp_path: Path) -> None:
        """The call was once matched with `startswith`, so
        `…/plugin-release-sbom.yml-disabled@<sha>` counted as the attestation lane.
        A repository could pass this check while calling something else entirely — and the pin check
        would accept it too, since it stays under `REUSABLE_PREFIX`. The target is compared exactly.
        """
        lane = self._release_lane().replace(
            f"{REUSABLE_RELEASE}@{_SHA}", f"{REUSABLE_RELEASE}-disabled@{_SHA}"
        )
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "no job calls" in _messages(check)

    def test_a_caller_that_cannot_grant_the_lane_fails(self, tmp_path: Path) -> None:
        """Presence is not capability. The lane signs provenance and both SBOM predicates, so it
        needs `id-token: write` and `attestations: write`; a caller granting only `contents: read`
        has its run refused at creation and the release publishes an unattested wheel anyway."""
        lane = self._release_lane(grant="contents: read")
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "`id-token: write`" in _messages(check)
        assert "`attestations: write`" in _messages(check)
        assert "startup_failure" in _messages(check)

    def test_a_job_level_write_all_satisfies_the_grant_but_is_reported(self, tmp_path: Path) -> None:
        """A job-level scalar shorthand DECLARES a block, so it replaces the workflow grant rather
        than reading as an absent one — and `write-all` covers all three scopes the lane needs.

        It is still not conformant-and-silent. The lane splits its jobs so no third-party step
        shares a token that can sign (`req-cicd-runner-least-privilege-3`), and a caller handing it
        every writable scope undoes that at the caller boundary. Capability is what this check
        asserts, so the grant is satisfied and the breadth warns — the same shape `-8` uses for
        `contents: write` on the CI caller, which this check was silent about until now.
        """
        lane = self._release_lane(grant=None).replace(
            "    permissions:\n      contents: read\n      id-token: write\n      attestations: write\n",
            "    permissions: write-all\n",
        )
        assert "write-all" in lane
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "warn", _messages(check)
        assert "NARROW it to" in _messages(check)
        assert "`attestations: write`" in _messages(check)

    def test_a_tag_filter_that_cannot_match_a_release_fails(self, tmp_path: Path) -> None:
        """A non-empty tag filter is not the property. `tags: ["never-release-*"]` catches nothing
        release-please cuts, so the lane never fires, the wheel publishes unattested, and a presence
        test calls the repository conformant — the silent failure this check exists to catch, one
        level further in (`tap#982`)."""
        lane = self._release_lane().replace('tags: ["v*"]', 'tags: ["never-release-*"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "none of which can match a release tag at all" in _messages(check)
        assert "tag-protection" in _messages(check)

    def test_a_different_but_working_spelling_passes(self, tmp_path: Path) -> None:
        """CAPABILITY, not equality. Asserting the literal string `v*` would red a repository whose
        filter is spelled differently and works — the question is whether a real release reaches the
        lane, so any filter that matches the protected shape is conformant."""
        for spelling in ('tags: ["v*.*.*"]', 'tags: ["v[0-9]*.[0-9]*.[0-9]*"]'):
            lane = self._release_lane().replace('tags: ["v*"]', spelling)
            repo = _make_repo(tmp_path / spelling[:12].replace("[", "_"), workflows={"release-sbom.yml": lane})
            (repo / "release-please-config.json").write_text("{}\n")
            check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
            assert check.status == "pass", f"{spelling}: {_messages(check)}"

    def test_a_single_digit_only_filter_fails(self, tmp_path: Path) -> None:
        """`v?.?.?` matches `v1.2.3` and MISSES `v0.12.2` — github-core-tap's actual release. So
        every representative tag must be covered, not merely one: a rule satisfied by a single match
        would bless a filter that silently skips every two-digit version. This test is why the
        implementation requires full coverage."""
        lane = self._release_lane().replace('tags: ["v*"]', 'tags: ["v?.?.?"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "cover only part of the release series" in _messages(check)
        assert "v10.20.30" in _messages(check)

    def test_the_samples_themselves_are_not_a_conformant_filter(self, tmp_path: Path) -> None:
        """A sample-based coverage test is a loophole unless literal filters are refused.

        Listing the representative tags AS the filters matches every sample and still misses the
        next release — `v2.3.4` — so a check that inferred full coverage from the sweep alone would
        certify a lane that fires on three tags forever. A filter with no metacharacter matches
        exactly one literal tag, which is the provable half of this method.
        """
        literals = '", "'.join(PROTECTED_RELEASE_TAGS)
        lane = self._release_lane().replace('tags: ["v*"]', f'tags: ["{literals}"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "glob metacharacter" in _messages(check)
        assert "unbounded release series" in _messages(check)

    def test_a_filter_matching_nothing_says_so_plainly(self, tmp_path: Path) -> None:
        """The three failure modes get three different sentences, because "none of which can match"
        is FALSE of a partially-covering glob and would send an author looking in the wrong place."""
        lane = self._release_lane().replace('tags: ["v*"]', 'tags: ["never-release-*"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "none of which can match a release tag at all" in _messages(check)

    def test_two_filters_together_can_cover_the_shape(self, tmp_path: Path) -> None:
        """Coverage is across the whole filter LIST, not per filter — a repository may split the
        single-digit and multi-digit cases and still catch every release."""
        lane = self._release_lane().replace('tags: ["v*"]', 'tags: ["v?.?.?", "v*.*.*"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "pass", _messages(check)

    def test_unmodellable_filter_syntax_warns_rather_than_failing(self, tmp_path: Path) -> None:
        """Actions filters also have `!`, `**` and `+`, which `fnmatch` cannot model faithfully.
        Reporting those as unmatched would teach authors to delete a filter to quiet the checker —
        the over-reporting mirror of the fail-open direction, and how the 2026-09-29 outage was
        instructed. So it warns and asks for a human confirmation."""
        lane = self._release_lane().replace('tags: ["v*"]', 'tags: ["v*", "!v*-rc*"]')
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "warn", _messages(check)
        assert "cannot evaluate" in _messages(check)

    def test_a_disabled_calling_job_fails(self, tmp_path: Path) -> None:
        """`if: ${{ false }}` is accepted by GitHub and simply never runs the job. Target, trigger
        and grant can all be correct while the repository publishes an unattested wheel on every
        release tag, which is the invisible state this check exists to catch."""
        lane = self._release_lane().replace(
            "  release-sbom:\n", "  release-sbom:\n    if: ${{ false }}\n"
        )
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "never runs" in _messages(check)

    def test_a_false_literal_comparison_disables_the_job(self, tmp_path: Path) -> None:
        """`${{ 'a' == 'b' }}` is two constants, so the file itself decides the answer and the job
        never runs. The guard's justification is that it decides what the file decides, so a
        constant comparison has to be in scope or the justification is only half applied."""
        lane = self._release_lane().replace(
            "  release-sbom:\n", "  release-sbom:\n    if: ${{ 'a' == 'b' }}\n"
        )
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "never runs" in _messages(check)

    def test_a_true_literal_comparison_is_accepted(self, tmp_path: Path) -> None:
        """The other direction, so the guard is not just "any comparison fails"."""
        lane = self._release_lane().replace(
            "  release-sbom:\n", "  release-sbom:\n    if: ${{ 'v' == 'v' }}\n"
        )
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "pass", _messages(check)

    def test_a_context_condition_warns_rather_than_passing_or_failing(self, tmp_path: Path) -> None:
        """A condition needing the event is neither proven nor dead, and the verdict says so.

        Passing it overstates what was checked — this requirement claims every release is attested,
        which an unevaluable condition does not establish. Failing it would forbid a construct core
        itself uses (`plugin-ci.yml` gates its upload job on `inputs.plugin_repo == ''`) and would
        teach authors to delete a fork guard to quiet the checker. So it warns.
        """
        lane = self._release_lane().replace(
            "  release-sbom:\n",
            "  release-sbom:\n    if: ${{ github.repository_owner == 'someone-else' }}\n",
        )
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "warn", _messages(check)
        assert "cannot be established by reading the file" in _messages(check)

    def test_an_unverifiable_trigger_fails_rather_than_passing(self, tmp_path: Path, monkeypatch) -> None:
        """Unknown is not conformant, the same verdict the caller-presence half of this check
        already reaches on an inconclusive parse.

        With no YAML parser the lexical fallback still finds the `uses:` line, so the call is
        proven — while the `on:` triggers cannot be read at all. Reporting that pair as conformant
        is this check's own defect one level up: a repository declaring releases would pass while
        GitHub never runs the lane, which is the unattested first release it exists to catch.
        """
        import builtins

        real_import = builtins.__import__

        def _no_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml for this test")
            return real_import(name, *args, **kwargs)

        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": self._release_lane()})
        (repo / "release-please-config.json").write_text("{}\n")
        monkeypatch.setattr(builtins, "__import__", _no_yaml)
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "could not be parsed" in _messages(check)
        assert "An unknown shape is not a conformant one" in _messages(check)

    def test_a_lane_that_cannot_fire_fails(self, tmp_path: Path) -> None:
        """Presence of the caller does not prove a release reaches it. A lane triggered only by
        `workflow_dispatch` passes every presence test and still lets each release tag publish
        unattested — the check would report the property while the property was false."""
        lane = self._release_lane().replace('on:\n  push:\n    tags: ["v*"]', "on:\n  workflow_dispatch:")
        assert "workflow_dispatch" in lane
        repo = _make_repo(tmp_path, workflows={"release-sbom.yml": lane})
        (repo / "release-please-config.json").write_text("{}\n")
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-lane")
        assert check.status == "fail", _messages(check)
        assert "does not trigger on a tag push" in _messages(check)

class TestNightlyShapeBypasses:
    """Two ways the shape check could certify something it had not proven.

    Both are the same species: a check that asks whether evidence exists SOMEWHERE, when what
    matters is whether it participates in the thing being judged. Each test below is the fixture
    that discriminates — it passes the tightened rule and would have passed the loose one too,
    which is why the loose one was not a check."""

    @staticmethod
    def _reporter(select: str, extra: str = "") -> str:
        return (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: |\n"
            '          listed="$(gh issue list --repo x --state open --limit 1000 --json number,author,body)"\n'
            '          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n'
            f'          existing="$(jq -r --arg m "$MARKER" \'{select}\' <<<"$listed")"\n'
            f"{extra}"
        )

    def test_marker_elsewhere_does_not_certify_a_title_only_selector(self, tmp_path: Path) -> None:
        """The bypass: the selecting expression uses ONLY the title, and the marker/author appear
        in an unrelated command. Asking whether they exist anywhere in the script passed this."""
        nightly = self._reporter(
            select='[.[] | select(.title == "Nightly red vs core main")] | .[0].number // empty',
            extra='          echo "unused: .author.login and ((.body // \\"\\") | contains($m))"\n',
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail", _messages(check)
        assert "same expression" in _messages(check)

    def test_title_narrowed_inside_the_same_program_is_accepted(self, tmp_path: Path) -> None:
        """The legitimate case must still pass, or the rule just pushes authors to drop a clause."""
        nightly = self._reporter(
            select=(
                '[.[] | select(.title == "Nightly red vs core main" and .author.login == "app/github-actions"'
                ' and ((.body // "") | contains($m)))] | .[0].number // empty'
            )
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "pass", _messages(check)

    def test_a_floating_pin_on_the_reusable_nightly_fails_the_pin_check(self, tmp_path: Path) -> None:
        """`_check_caller_pin` is keyed on the PREFIX, not on plugin-ci.yml, so the new workflow is
        already covered — asserted here because that was raised as unverifiable from the diff."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@main\n"
            "    permissions:\n      contents: read\n      security-events: write\n      issues: write\n"
            "    with:\n      plugin_slug: shell_sample\n"
        )
        result = validate_plugin(
            _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
        )
        pin = _check(result, "repo-ci-caller-pin")
        assert pin.status == "fail", _messages(pin)
        assert "plugin-nightly.yml" in _messages(pin)

    def test_a_nightly_caller_short_of_the_nested_tree_fails(self, tmp_path: Path) -> None:
        """`issues: write` alone is not enough: the nightly NESTS plugin-ci, whose SARIF job wants
        `security-events: write`, and GitHub validates the whole tree before creating any job."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@{_SHA}\n"
            "    permissions:\n      contents: read\n      issues: write\n"
            "    with:\n      plugin_slug: shell_sample\n"
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "security-events: write" in _messages(check)
        assert "NESTS" in _messages(check)


class TestSelectionMustNarrowByBoth:
    """The marker is PUBLIC. It is committed in this repository and shows in a rendered issue's
    source, so it can be copied into a stranger's issue exactly as a title can. Neither half alone
    is the job's own evidence, and a rule that only rejected title-equality passed the other."""

    def test_marker_without_author_fails(self, tmp_path: Path) -> None:
        nightly = _nightly(identify="marker-only")
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail", _messages(check)
        assert "the author" in _messages(check)

    def test_author_without_marker_fails(self, tmp_path: Path) -> None:
        nightly = _nightly(identify="author-only")
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail", _messages(check)
        assert "body marker" in _messages(check)

    def test_a_limit_without_a_truncation_guard_warns(self, tmp_path: Path) -> None:
        """The check's own message promises the count comparison; asking only for the flag
        certifies `--limit 1` with nothing checking the returned length."""
        nightly = _nightly(guard=False)
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "warn", _messages(check)
        assert "never compares the listing's own length" in _messages(check)

    def test_a_local_reporter_beside_an_inherited_call_is_still_read(self, tmp_path: Path) -> None:
        """Inheriting core's nightly says nothing about a hand-rolled reporter kept beside it. The
        early return that used to follow the inherited branch exempted exactly that job."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@{_SHA}\n"
            "    permissions:\n      contents: read\n      security-events: write\n      issues: write\n"
            "    with:\n      plugin_slug: shell_sample\n"
            "  legacy-reporter:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: |\n"
            '          existing="$(jq -r \'[.[] | select(.title == "Nightly red vs core main")] | .[0].number\')"\n'
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "legacy-reporter" in _messages(check)


def test_an_unpairable_script_is_reported_not_passed(tmp_path: Path) -> None:
    """The known limit of quote-pairing, held so it stays a deliberate choice.

    A bare apostrophe skews every quote pair after it, so the selecting program stops being
    recognisable. The rule reports that rather than passing it: an unreadable selection in the one
    job that closes issues is not evidence of a safe one. This test exists so the behaviour is a
    decision on the record, not an accident someone later "fixes" into a silent pass.
    """
    nightly = (
        "name: nightly\n"
        'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
        "jobs:\n"
        "  main:\n"
        f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
        "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
        "  owner-issue:\n"
        "    runs-on: ubuntu-latest\n"
        "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
        "    permissions:\n      issues: write\n"
        "    steps:\n"
        "      - run: |\n"
        "          # the repository's own note, with one apostrophe\n"
        '          existing="$(jq -r --arg m "$MARKER" \'[.[] | select(.title == "x")]\' <<<"$listed")"\n'
    )
    check = _check(
        validate_plugin(
            _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
        ),
        "repo-nightly-shape",
    )
    assert check.status == "fail", _messages(check)
    assert "cannot be" in _messages(check), "the finding must say the selection is unprovable"


class TestSelectionProofIsOwed:
    """The fail-open the proof obligation replaced: shapes the old pattern did not recognise.

    Each of these used to PASS, because the rule looked for known-bad selectors and everything it
    could not parse fell through as safe. A selector this cannot read is not evidence of a safe
    one, so the obligation now runs the other way: prove marker AND author, or be reported."""

    @staticmethod
    def _with(select_line: str) -> str:
        return (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: |\n"
            '          listed="$(gh issue list --repo x --state open --limit 1000 --json number,author,body)"\n'
            '          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n'
            f"{select_line}"
        )

    def test_a_double_quoted_author_only_selector_is_reported(self, tmp_path: Path) -> None:
        """No single quotes at all, so nothing the parser calls a program — the exact hole named."""
        line = '          existing="$(jq -r ".[] | select(.author.login == \\"app/github-actions\\") | .number" <<<"$listed")"\n'
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": self._with(line)}),
                repo_scope=True,
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "cannot be" in _messages(check), "the finding must say the selection is unprovable"

    def test_a_bare_index_selector_is_reported(self, tmp_path: Path) -> None:
        """`jq '.[0].number'` narrows by nothing — it takes whatever the listing happened to return
        first, which is any stranger's open issue."""
        line = '          existing="$(jq -r \'.[0].number\' <<<"$listed")"\n'
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": self._with(line)}),
                repo_scope=True,
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)

    def test_a_job_that_only_files_owes_no_selection_proof(self, tmp_path: Path) -> None:
        """The obligation must not be unconditional: a reporter that never picks an existing issue
        has no selection to prove. Its defect is duplicates, which is the --limit rule's business."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            '      - run: gh issue create --title "Nightly red" --body "see the run"\n'
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "pass", _messages(check)


class TestWorkflowLevelPermissionsAreEffective:
    """A job with no `permissions:` block INHERITS the workflow's. Reading only the job's own block
    classified such a job as not-a-reporter, so it escaped every selection, pagination and
    concurrency rule — while running with exactly the issue-write capability those rules exist for.

    The `write-all` scalar is the same hole with a shorter spelling."""

    @staticmethod
    def _inherited_grant(top: str) -> str:
        return (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            f"{top}"
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@{_SHA}\n"
            "    permissions:\n      contents: read\n      security-events: write\n      issues: write\n"
            "    with:\n      plugin_slug: shell_sample\n"
            "  legacy-reporter:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            '          listed="$(gh issue list --repo x --state open --json number,title)"\n'
            '          existing="$(jq -r \'[.[] | select(.title == "Nightly red vs core main")] | .[0].number\' <<<"$listed")"\n'
            '          gh issue close "$existing"\n'
        )

    def test_a_reporter_inheriting_issues_write_is_read(self, tmp_path: Path) -> None:
        nightly = self._inherited_grant("permissions:\n  contents: read\n  issues: write\n")
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "legacy-reporter" in _messages(check)

    def test_write_all_at_workflow_level_is_read_too(self, tmp_path: Path) -> None:
        """The scalar form. A mapping-only reader sees no `issues` key and moves on."""
        nightly = self._inherited_grant("permissions: write-all\n")
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "legacy-reporter" in _messages(check)

    def test_a_job_level_block_replaces_rather_than_merges(self, tmp_path: Path) -> None:
        """GitHub semantics: the job's block REPLACES the workflow's. A job declaring only
        `contents: read` beneath a workflow-level `issues: write` does NOT write issues, and must
        not be dragged into the reporter rules by the file's top-level grant."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "permissions:\n  issues: write\n"
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  not-a-reporter:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n      contents: read\n"
            "    steps:\n"
            '      - run: echo "no issue writing here"\n'
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert "not-a-reporter" not in _messages(check), _messages(check)


class TestDecoySelectorsDoNotSatisfyTheProof:
    """A narrowing program existing SOMEWHERE is not the obligation. The obligation is that every
    expression which could produce the issue narrows — otherwise one safe-looking selector stands in
    as the proof while a second, unnarrowed one does the picking."""

    @staticmethod
    def _reporter(body: str) -> str:
        return (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: |\n"
            '          listed="$(gh issue list --repo x --state open --limit 1000 --json number,author,body)"\n'
            '          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n'
            f"{body}"
        )

    def _check_it(self, tmp_path: Path, body: str) -> CheckResult:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": self._reporter(body)})
        return _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")

    def test_a_decoy_selector_beside_a_bare_index_is_reported(self, tmp_path: Path) -> None:
        """The exact shape: a narrowing program that is never used, and `jq '.[0].number'` — which
        has no `select(` — producing the number that gets closed."""
        body = (
            '          unused="$(jq -r \'[.[] | select(.author.login == "app/github-actions"'
            ' and (.body | contains($m)))]\' <<<"$listed")"\n'
            '          existing="$(jq -r \'.[0].number\' <<<"$listed")"\n'
            '          gh issue close "$existing"\n'
        )
        check = self._check_it(tmp_path, body)
        assert check.status == "fail", _messages(check)
        assert "EVERY expression" in _messages(check)

    def test_a_literal_contains_is_not_marker_proof(self, tmp_path: Path) -> None:
        """`contains("dummy")` is a body test that proves nothing. The marker must come in as a
        VARIABLE, because that is the only form that can carry the value the job actually wrote."""
        body = (
            '          existing="$(jq -r \'[.[] | select(.author.login == "app/github-actions"'
            ' and (.body | contains("dummy")))] | .[0].number\' <<<"$listed")"\n'
            '          gh issue close "$existing"\n'
        )
        check = self._check_it(tmp_path, body)
        assert check.status == "fail", _messages(check)
        assert "body marker" in _messages(check)

    def test_jq_length_does_not_count_as_touching_an_issue(self, tmp_path: Path) -> None:
        """The boundary: the truncation guard's own `jq length` counts the listing and touches no
        issue, so it must not be dragged into the obligation — otherwise the conformant shape, which
        needs that guard, could never satisfy it."""
        body = (
            '          existing="$(jq -r --arg m "$MARKER" \'[.[] | select(.author.login =='
            ' "app/github-actions" and ((.body // "") | contains($m)))] | .[0].number // empty\''
            ' <<<"$listed")"\n'
            '          gh issue close "$existing"\n'
        )
        check = self._check_it(tmp_path, body)
        assert check.status == "pass", _messages(check)


class TestUnreadableWritersAreReported:
    """Three ways a reporter's write could not be reasoned about at all, each of which used to pass.

    The through-line: a check that reports only what it recognises passes everything it does not.
    These all fail closed now — unprovable is a finding, not a clean bill."""

    def test_a_decoy_beside_a_double_quoted_picker_is_reported(self, tmp_path: Path) -> None:
        """A correct single-quoted selector satisfied the proof while a double-quoted
        `jq ".[0].number"` — invisible to the program parser — did the picking."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: |\n"
            '          listed="$(gh issue list --repo x --state open --limit 1000 --json number,author,body)"\n'
            '          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n'
            '          ok="$(jq -r --arg m "$MARKER" \'[.[] | select(.author.login == "app/github-actions"'
            ' and ((.body // "") | contains($m)))]\' <<<"$listed")"\n'
            '          existing="$(jq -r ".[0].number" <<<"$listed")"\n'
            '          gh issue close "$existing"\n'
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "no quoted jq program accounts for" in _messages(check)

    def test_a_uses_only_writer_beside_an_inherited_call_is_reported(self, tmp_path: Path) -> None:
        """A job holding `issues: write` whose steps are all `uses:` has no script to read, so
        keying the reporter scan on `run:` made it INVISIBLE — capability held, no finding drawn."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  nightly:\n"
            f"    uses: {REUSABLE_PREFIX}plugin-nightly.yml@{_SHA}\n"
            "    permissions:\n      contents: read\n      security-events: write\n      issues: write\n"
            "    with:\n      plugin_slug: shell_sample\n"
            "  legacy-action-writer:\n"
            "    runs-on: ubuntu-latest\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - uses: someone/close-stale-issues@v9\n"
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "fail", _messages(check)
        assert "legacy-action-writer" in _messages(check)
        assert "cannot be established at all" in _messages(check)

    def test_a_decoy_limit_comparison_does_not_satisfy_the_guard(self, tmp_path: Path) -> None:
        """`[ 0 -ge "$LIMIT" ]` compares a literal and checks nothing, but matched a token pattern —
        while the warning it silenced claims specifically that the listing's length was compared."""
        nightly = _nightly(guard=False).replace(
            "          set -euo pipefail\n",
            '          set -euo pipefail\n          [ 0 -ge "$LIMIT" ] && exit 1\n',
        )
        check = _check(
            validate_plugin(
                _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly}), repo_scope=True
            ),
            "repo-nightly-shape",
        )
        assert check.status == "warn", _messages(check)
        assert "never compares the listing's own length" in _messages(check)


class TestTheLimitGuardIsTraced:
    """The guard rule reads one variable's worth of dataflow, and both directions were observed here
    in this order: a token match certified a decoy, and same-line matching then reported core's own
    reporter. Each case below is one of the five the function has to get right."""

    @staticmethod
    def _guard(line: str) -> str:
        return _nightly(guard=False).replace("          set -euo pipefail\n", f"          set -euo pipefail\n{line}")

    def _status(self, tmp_path: Path, nightly: str) -> CheckResult:
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        return _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")

    def test_a_length_assigned_then_compared_on_a_later_line_counts(self, tmp_path: Path) -> None:
        """The conformant shape, and the one a same-line rule wrongly reported."""
        nightly = self._guard(
            '          count="$(jq length <<<"$listed")"\n          [ "$count" -ge "$LIMIT" ] && exit 1\n'
        )
        assert self._status(tmp_path, nightly).status == "pass", _messages(self._status(tmp_path, nightly))

    def test_a_length_inlined_into_the_comparison_counts(self, tmp_path: Path) -> None:
        nightly = self._guard('          [ "$(jq length <<<"$listed")" -ge "$LIMIT" ] && exit 1\n')
        assert self._status(tmp_path, nightly).status == "pass", _messages(self._status(tmp_path, nightly))

    def test_a_variable_assigned_from_something_else_does_not_count(self, tmp_path: Path) -> None:
        """It compares a number against the limit, but not the listing's length."""
        check = self._status(
            tmp_path, self._guard('          n="$(date +%s)"\n          [ "$n" -ge "$LIMIT" ] && exit 1\n')
        )
        assert check.status == "warn", _messages(check)
        assert "never compares the listing's own length" in _messages(check)


class TestCeilingProbeAndMixedWriters:
    """Round-seven shapes: an expression that mentions `main` without ever reaching it, and an
    issue-writing job whose harmless half vouched for its opaque half."""

    def test_an_expression_whose_fallback_is_unreachable_is_refused(self, tmp_path: Path) -> None:
        """`${{ 'v0.2.0' || 'main' }}` evaluates to `v0.2.0` — the fallback is never reached, so the
        lane sits at a pinned floor while satisfying a rule about the ceiling."""
        nightly = _nightly(harness_ref="${{ 'v0.2.0' || 'main' }}")
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail", _messages(check)
        assert "harness_ref: main" in _messages(check)

    def test_the_documented_input_fallback_is_still_accepted(self, tmp_path: Path) -> None:
        """gryphon-playground's real spelling must keep passing, or the rule just bans the feature."""
        nightly = _nightly(harness_ref="${{ inputs.harness_ref || 'main' }}")
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        assert _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape").status == "pass"

    def test_a_mixed_run_and_uses_writer_is_reported(self, tmp_path: Path) -> None:
        """One harmless `run:` beside an opaque action made the job read as a conformant reporter,
        because `opaque` was keyed on the ABSENCE of a script rather than the presence of an action."""
        nightly = (
            "name: nightly\n"
            'on:\n  schedule:\n    - cron: "0 3 * * *"\n'
            "jobs:\n"
            "  main:\n"
            f"    uses: {REUSABLE_CALLER}@{_SHA}\n"
            "    with:\n      plugin_slug: shell_sample\n      harness_ref: main\n"
            "  owner-issue:\n"
            "    runs-on: ubuntu-latest\n"
            "    concurrency:\n      group: g\n      cancel-in-progress: false\n"
            "    permissions:\n      issues: write\n"
            "    steps:\n"
            "      - run: echo ok\n"
            "      - uses: someone/close-stale-issues@main\n"
        )
        repo = _make_repo(tmp_path, workflows={"ci.yml": _caller(_SHA), "nightly.yml": nightly})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-nightly-shape")
        assert check.status == "fail", _messages(check)
        assert "someone/close-stale-issues@main" in _messages(check)
        assert "cannot be established at all" in _messages(check)


# ---------------------------------------------------------------------------
# release-please pair consistency (optional)
# ---------------------------------------------------------------------------


class TestReleasePleasePair:
    def test_both_absent_warns_and_does_not_fail(self, tmp_path: Path) -> None:
        check = _check(validate_plugin(_make_repo(tmp_path), repo_scope=True), "repo-release-please-pair")
        assert check.status == "warn"
        assert check.details == {"config": False, "manifest": False}

    def test_both_present_and_valid_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(
            tmp_path,
            extra_files={
                "release-please-config.json": '{"release-type": "python", "packages": {".": {}}}',
                ".release-please-manifest.json": '{".": "0.1.0"}',
            },
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-please-pair")
        assert check.status == "pass", _messages(check)

    def test_config_without_manifest_fails(self, tmp_path: Path) -> None:
        """A half-setup looks, from a directory listing, like release-please is wired up — which
        is exactly the shape worth failing on rather than warning about."""
        repo = _make_repo(tmp_path, extra_files={"release-please-config.json": '{"release-type": "python"}'})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-please-pair")
        assert check.status == "fail", _messages(check)
        assert "needs both together" in _messages(check)

    def test_manifest_without_config_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, extra_files={".release-please-manifest.json": '{".": "0.1.0"}'})
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-please-pair")
        assert check.status == "fail", _messages(check)

    def test_unparseable_config_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(
            tmp_path,
            extra_files={
                "release-please-config.json": "{ not json",
                ".release-please-manifest.json": '{".": "0.1.0"}',
            },
        )
        check = _check(validate_plugin(repo, repo_scope=True), "repo-release-please-pair")
        assert check.status == "fail", _messages(check)
        assert "does not parse as JSON" in _messages(check)
