"""The scoped closure walk behind plugin dependency snapshots (tap#664).

A synthetic metadata graph, not the live venv: the walk's rules — where it stops, what it
calls direct, which requirements it refuses to believe — must be provable without a boot.
"""

from __future__ import annotations

from typing import Any

import pytest

from tap.dependency_snapshot import (
    DistInfo,
    Lookup,
    build_payload,
    manifest_name,
    walk_closure,
)

# A plugin (`github-core-tap`) that depends on a third-party package, a SIBLING plugin, and a
# package carrying extras + markers. The sibling has its own subtree, which a scoped walk must
# never enter.
GRAPH: dict[str, DistInfo] = {
    "github-core-tap": DistInfo(
        name="github-core-tap",
        version="0.10.0",
        requires=(
            "PyYAML>=6.0.2",
            "git-core-tap>=0.1.0,<0.2",
            'pytest>=8 ; extra == "dev"',
            "httpx[http2]>=0.27",
        ),
    ),
    "PyYAML": DistInfo(name="PyYAML", version="6.0.2"),
    # The sibling's own closure — `only-in-sibling` exists ONLY here, so its presence in a
    # snapshot is proof the walk crossed a boundary it was told to stop at.
    "git-core-tap": DistInfo(name="git-core-tap", version="0.1.0", requires=("only-in-sibling>=1",)),
    "only-in-sibling": DistInfo(name="only-in-sibling", version="1.2.3"),
    "httpx": DistInfo(
        name="httpx",
        version="0.27.2",
        requires=("httpcore>=1", 'h2>=4 ; extra == "http2"', 'trio>=0.22 ; extra == "socks"'),
    ),
    "httpcore": DistInfo(name="httpcore", version="1.0.5"),
    "h2": DistInfo(name="h2", version="4.1.0"),
    "trio": DistInfo(name="trio", version="0.26.0"),
    "pytest": DistInfo(name="pytest", version="8.3.0"),
}


def _lookup(graph: dict[str, DistInfo] | None = None) -> Lookup:
    table = {key.lower().replace("_", "-"): value for key, value in (graph or GRAPH).items()}

    def resolve(name: str) -> DistInfo | None:
        return table.get(name.lower().replace("_", "-"))

    return resolve


class TestScoping:
    def test_the_root_is_not_a_node(self) -> None:
        """The repository IS the root; a snapshot lists what it depends ON."""
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "github-core-tap" not in snapshot.resolved

    def test_declared_requirements_are_direct_and_the_rest_indirect(self) -> None:
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert snapshot.resolved["pyyaml"]["relationship"] == "direct"
        assert snapshot.resolved["httpx"]["relationship"] == "direct"
        assert snapshot.resolved["httpcore"]["relationship"] == "indirect"

    def test_traversal_stops_at_a_sibling_plugin(self) -> None:
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "git-core-tap" not in snapshot.resolved
        assert "git-core-tap" in snapshot.scoped_out_siblings

    def test_the_boundary_is_reported_not_silently_dropped(self) -> None:
        """A sibling that vanished with no trace would read as 'no such dependency'."""
        payload = build_payload(
            "github-core-tap",
            sha="s",
            ref="refs/heads/main",
            job_id="1",
            job_correlator="c",
            detector_version="0.2.0",
            lookup=_lookup(),
        )
        metadata = payload["manifests"][manifest_name("github-core-tap")]["metadata"]
        assert "git-core-tap" in metadata["scoped_out_siblings"]

    def test_positive_control_an_unscoped_walk_would_have_crossed_the_boundary(self) -> None:
        """Rename the sibling so it no longer looks like a plugin: the walk then enters it.

        Without this, `only-in-sibling` being absent proves nothing — it could be absent
        because the walk works, or because the fixture never reached that far.
        """
        graph = dict(GRAPH)
        graph["notaplugin-core"] = DistInfo(name="notaplugin-core", version="0.1.0", requires=("only-in-sibling>=1",))
        graph["github-core-tap"] = DistInfo(
            name="github-core-tap",
            version="0.10.0",
            requires=("PyYAML>=6.0.2", "notaplugin-core>=0.1.0"),
        )
        snapshot = walk_closure("github-core-tap", lookup=_lookup(graph))
        assert "only-in-sibling" in snapshot.resolved
        assert not snapshot.scoped_out_siblings

    def test_a_siblings_subtree_is_not_listed_as_a_dependency_edge(self) -> None:
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "only-in-sibling" not in snapshot.resolved


class TestMarkersAndExtras:
    def test_an_extra_we_did_not_request_is_not_installed_and_not_listed(self) -> None:
        """`pytest ; extra == "dev"` is not part of a runtime boot."""
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "pytest" not in snapshot.resolved

    def test_a_requested_extra_is_expanded(self) -> None:
        """The root asks for `httpx[http2]`, so h2 IS in the closure."""
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "h2" in snapshot.resolved
        assert snapshot.resolved["h2"]["relationship"] == "indirect"

    def test_an_unrequested_extra_of_a_transitive_dep_is_not_expanded(self) -> None:
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert "trio" not in snapshot.resolved

    def test_an_unparseable_requirement_is_skipped_not_fatal(self) -> None:
        graph = dict(GRAPH)
        graph["github-core-tap"] = DistInfo(
            name="github-core-tap",
            version="0.10.0",
            requires=("PyYAML>=6.0.2", "this is not a requirement @@@"),
        )
        snapshot = walk_closure("github-core-tap", lookup=_lookup(graph))
        assert "pyyaml" in snapshot.resolved


class TestHonesty:
    def test_a_declared_but_uninstalled_dependency_is_reported_not_invented(self) -> None:
        graph = dict(GRAPH)
        graph["github-core-tap"] = DistInfo(
            name="github-core-tap", version="0.10.0", requires=("PyYAML>=6.0.2", "absent-package>=1")
        )
        snapshot = walk_closure("github-core-tap", lookup=_lookup(graph))
        assert "absent-package" not in snapshot.resolved
        assert "absent-package" in snapshot.declared_not_installed

    def test_a_missing_root_is_an_error_not_an_empty_snapshot(self) -> None:
        """An empty snapshot would submit 'this plugin depends on nothing' — a lie that reads as clean."""
        with pytest.raises(LookupError, match="not installed"):
            walk_closure("never-installed-tap", lookup=_lookup())

    def test_purls_are_pep503_normalized_with_the_installed_version(self) -> None:
        snapshot = walk_closure("github-core-tap", lookup=_lookup())
        assert snapshot.resolved["pyyaml"]["package_url"] == "pkg:pypi/pyyaml@6.0.2"


class TestPayload:
    def _payload(self) -> dict[str, Any]:
        return build_payload(
            "github-core-tap",
            sha="abc123",
            ref="refs/heads/main",
            job_id="42",
            job_correlator="ci-tap",
            detector_version="0.2.0",
            scanned="2026-09-19T12:00:00Z",
            lookup=_lookup(),
        )

    def test_shape_matches_what_the_submission_api_accepts(self) -> None:
        payload = self._payload()
        assert payload["version"] == 0
        assert payload["sha"] == "abc123"
        assert payload["job"] == {"id": "42", "correlator": "ci-tap"}
        assert payload["detector"]["name"] == "tap-dependency-snapshot"
        manifest = payload["manifests"][manifest_name("github-core-tap")]
        assert manifest["file"]["source_location"] == "pyproject.toml"
        node = manifest["resolved"]["httpx"]
        assert node["scope"] == "runtime"
        assert node["dependencies"] == ["h2", "httpcore"]

    def test_output_is_deterministic(self) -> None:
        """Same venv, same bytes — otherwise every run looks like a change."""
        import json

        first = json.dumps(self._payload(), sort_keys=True)
        second = json.dumps(self._payload(), sort_keys=True)
        assert first == second

    def test_resolved_keys_are_sorted(self) -> None:
        manifest = self._payload()["manifests"][manifest_name("github-core-tap")]
        assert list(manifest["resolved"]) == sorted(manifest["resolved"])
