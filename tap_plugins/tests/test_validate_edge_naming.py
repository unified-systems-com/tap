"""Edge slugs name a mechanical action on a destination noun.

The convention (`tap_grid/skills/add-edge/SKILL.md`) is `<ACTION>_<OBJECT>` — a plain verb
plus the destination noun it acts on: `ASSUMES_ROLE`, `TRUSTS_ISSUER`, `WRITES_LOGS`.

**Why this lives in `validate_plugin` and not in core's guard harness.** Core's guards walk
`REPO_ROOT`, and evicted plugins live in their own repositories, so a core-tree guard would
scan zero edges and pass. `validate_plugin` already runs on every plugin repo's own CI
through the conformance job, which is the only check that reaches plugin code wherever it
lives — and it reaches `aws_core` and `identity_core` too, where some of the debt is.

**A fourth check was measured and deliberately NOT built:** "the object noun should match
the destination type" sounds obviously right and flagged 18 of 34 real edges, a ~53%
false-positive rate. Abbreviation (`OWNS_REPO` -> `github_repository`) and
semantic-rather-than-lexical objects (`EXEMPTS_ACTOR` -> `github_account`) are both correct
and both trip it. It would have shipped as permanently baselined noise, and a check nobody
can clear is a check everybody scrolls past.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap_plugins.validate.service import ValidationResult, _check_edge_naming, _edge_naming_violations


class TestConformantSlugsPass:
    """Real slugs from across the three plugins. None of these may ever be flagged."""

    @pytest.mark.parametrize(
        "slug",
        [
            "ASSUMES_ROLE__aws_core",
            "DIVIDED_INTO_AZ__aws_core",
            "TRUSTS_ISSUER__identity_core",
            "WRITES_LOGS__aws_core",
            "ROUTES_TRAFFIC__aws_core",
            "OWNS_REPO__github_core",
            "DEFINES_WORKFLOW__github_core",
            "EXEMPTS_ACTOR__github_core",
            "BYPASSED_RULE__github_core",
            "TRIGGERED_EVALUATION__github_core",
            "EVALUATED_ON_REF__github_core",
        ],
    )
    def test_no_violation(self, slug: str) -> None:
        assert _edge_naming_violations(slug) == []


class TestTheReservedFromSuffix:
    @pytest.mark.parametrize("slug", ["RETRIEVES_CERT_FROM__aws_core", "RETRIEVES_CONTENT_FROM__aws_core"])
    def test_from_is_a_data_reversal_marker_not_a_preposition(self, slug: str) -> None:
        """These are the two edges the checklist holds up as exemplary.

        `_FROM` is reserved to mean the data flows opposite the edge direction; the object
        noun sits before it. A naive ends-in-a-preposition rule would fail precisely the
        slugs that best demonstrate the convention, which is how a guard loses its
        credibility on day one.
        """
        assert _edge_naming_violations(slug) == []

    def test_from_alone_is_still_a_violation(self) -> None:
        """The exemption is for a marker AFTER an object, not for a bare `VERB_FROM`."""
        assert "trailing-preposition" in _edge_naming_violations("RETRIEVES_FROM__x")


class TestBareVerbs:
    @pytest.mark.parametrize("slug", ["INVOKES__aws_core", "PROTECTS__github_core"])
    def test_a_bare_verb_does_not_say_what_it_acts_on(self, slug: str) -> None:
        assert _edge_naming_violations(slug) == ["bare-verb"]


class TestModalsAndAuxiliaries:
    @pytest.mark.parametrize(
        "slug",
        [
            "HAS_REF__github_core",
            "HAS_ACTIONS_JOB__github_core",
            "CAN_BYPASS_RULE__github_core",
            "IS_MEMBER_OF_TEAM__x",
            "WILL_EXPIRE_KEY__x",
        ],
    )
    def test_a_state_is_not_an_action(self, slug: str) -> None:
        """`CAN` is a modal and `HAS`/`IS` are aspectual or copular. They describe a state
        of affairs rather than something that happens, which is the philosophical-not-
        mechanical naming the convention exists to reject."""
        assert "modal-prefix" in _edge_naming_violations(slug)


class TestTrailingPrepositions:
    @pytest.mark.parametrize(
        "slug",
        [
            "EXECUTED_ON__github_core",
            "INSTALLED_ON__github_core",
            "SCOPED_TO__github_core",
            "ENCRYPTED_WITH__aws_core",
            "FEDERATES_VIA__aws_core",
            "FEDERATES_INTO__aws_core",
        ],
    )
    def test_a_preposition_names_a_direction_not_an_object(self, slug: str) -> None:
        assert _edge_naming_violations(slug) == ["trailing-preposition"]

    def test_a_preposition_inside_the_slug_is_fine(self) -> None:
        """Only the ENDING matters — the object noun may follow the preposition."""
        assert _edge_naming_violations("DIVIDED_INTO_AZ__aws_core") == []
        assert _edge_naming_violations("DEPENDS_ON_JOB__github_core") == []
        assert _edge_naming_violations("EVALUATED_ON_REF__github_core") == []


class TestViolationsCompound:
    def test_one_slug_can_break_several_rules(self) -> None:
        """Reported separately so clearing one is visible in the baseline diff."""
        assert set(_edge_naming_violations("HAS_ON__x")) == {"modal-prefix", "trailing-preposition"}


class _FakeEdge:
    """The two attributes the check reads off a manifest edge."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.file_path = f"edges/{slug.split('__')[0]}.edge.json"


class _FakeManifest:
    def __init__(self, plugin_root: Path, slugs: list[str]) -> None:
        self.plugin_root = plugin_root
        self.edges = [_FakeEdge(slug) for slug in slugs]


def _run(tmp_path: Path, slugs: list[str], baseline: str | None = None) -> ValidationResult:
    if baseline is not None:
        baselines = tmp_path / "guards" / "baselines"
        baselines.mkdir(parents=True, exist_ok=True)
        (baselines / "edge_naming.txt").write_text(baseline, encoding="utf-8")
    result = ValidationResult(ok=True, level="manifest", plugin_path=str(tmp_path), strict=False)
    _check_edge_naming(_FakeManifest(tmp_path, slugs), result)
    return result


class TestTheBaselineOnlyShrinks:
    """`req-tap-plugin-edge-naming-4`. Untested until the PR #222 review said so — and the
    one uncovered branch was the one that was wrong."""

    def test_a_baselined_violation_is_info_not_failure(self, tmp_path: Path) -> None:
        """Pre-convention edges are known debt; they must not block the plugin."""
        result = _run(tmp_path, ["INVOKES__demo"], baseline="# header\nINVOKES::bare-verb\n")

        check = result.checks[0]
        assert check.status == "pass"
        assert any("known debt" in m.text for m in check.messages)

    def test_an_unbaselined_violation_still_fails(self, tmp_path: Path) -> None:
        """Negative control: the baseline must be capable of NOT covering something."""
        result = _run(tmp_path, ["INVOKES__demo"], baseline="# header\n")

        assert result.checks[0].status == "fail"

    def test_a_stale_entry_fails(self, tmp_path: Path) -> None:
        """An exemption that exempts nothing misstates how strict the check is."""
        result = _run(tmp_path, ["INVOKES_LAMBDA__demo"], baseline="INVOKES::bare-verb\n")

        check = result.checks[0]
        assert check.status == "fail"
        assert any("no longer violating" in m.text for m in check.messages)

    def test_a_stale_entry_fails_even_with_no_edges_left(self, tmp_path: Path) -> None:
        """Deleting the last violating edge is exactly when an entry goes stale."""
        result = _run(tmp_path, [], baseline="INVOKES::bare-verb\n")

        assert result.checks, "an edge-less plugin carrying a baseline must still be checked"
        assert result.checks[0].status == "fail"

    def test_no_edges_and_no_baseline_adds_no_check(self, tmp_path: Path) -> None:
        """Nothing to say about a plugin that declares no edges and carries no debt."""
        assert _run(tmp_path, []).checks == []

    def test_failure_paths_come_from_the_manifest(self, tmp_path: Path) -> None:
        """The edge file location is manifest data, not a reconstructed naming guess."""
        result = _run(tmp_path, ["INVOKES__demo"], baseline="")

        assert [m.path for m in result.checks[0].messages] == ["edges/INVOKES.edge.json"]
