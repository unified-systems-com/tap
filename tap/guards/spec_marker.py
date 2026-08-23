"""`@pytest.mark.spec` resolution guard — `spec-tap-testing.md` (`req-tap-test-spec-linkage`).

Every acceptance-criterion id passed to `@pytest.mark.spec(...)` must resolve to an ACID
(or requirement) actually defined in the specs.

The marker has been registered in `pyproject.toml` and used across the suite since the
spec-linkage requirement landed, but until now **nothing consumed it** — a test could cite
a criterion that had been renamed, split, or never existed, and the link would read as
sound while pointing nowhere. That is the failure mode the traceability literature calls a
dangling claim, and it is worse than a duplicate because it looks fine.

A **hard lint with no baseline**: measured at introduction, every marker in the tree already
resolved, so there is no debt to grandfather and no reason to permit any.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard


class SpecMarkerResolutionGuard(Guard):
    slug = "spec-marker-resolution"
    map_row = "Spec-marker resolution"
    rid = "req-tap-test-spec-linkage"
    description = (
        "A `@pytest.mark.spec` citing a criterion that does not exist claims coverage of nothing; "
        "the link reads as sound while pointing nowhere, so the gap hides behind its own evidence."
    )

    def check(self) -> None:
        from tap.spec_trace import unresolvable_markers

        offenders = unresolvable_markers(REPO_ROOT)
        assert not offenders, (
            "`@pytest.mark.spec` cites acceptance criteria that resolve to nothing — correct the "
            "id to a criterion defined in a spec, or add the criterion:\n  "
            + "\n  ".join(f"{c.where(REPO_ROOT)} -> {c.token}" for c in sorted(offenders, key=lambda c: c.token))
        )
