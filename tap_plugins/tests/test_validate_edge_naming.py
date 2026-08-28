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

import pytest
from tap_plugins.validate.service import _edge_naming_violations


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
    @pytest.mark.parametrize(
        "slug", ["RETRIEVES_CERT_FROM__aws_core", "RETRIEVES_CONTENT_FROM__aws_core"]
    )
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
