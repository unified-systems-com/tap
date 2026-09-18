"""The reference model on its own (Issue# 586 - tap): legitimate discoverers are a SET
derived from depth, never one run's pick; order-dependent scenarios are refused."""

from __future__ import annotations

import itertools

import pytest

from tap_grid.cascade_corpus.model_oracle import AmbiguousScenario, Graph, cascade

N, NESTS, LINKS = "grid_fixtures__node", "PG_NESTS__grid_fixtures", "PG_LINKS__grid_fixtures"


def graph(
    nodes: list[str],
    edges: list[tuple[str, str, str]],
    *,
    blocked: tuple[str, ...] = (),
    pre_retired: tuple[str, ...] = (),
    pre_retired_edges: tuple[str, ...] = (),
) -> Graph:
    return Graph(
        node_type=dict.fromkeys(nodes, N),
        edges=tuple((f"e_{a}_{b}_{t[:2]}", a, b, t) for a, b, t in edges),
        containment={N: (NESTS,)},
        blocked_types=frozenset(blocked),
        pre_retired=frozenset(pre_retired),
        pre_retired_edges=frozenset(pre_retired_edges),
    )


@pytest.mark.spec("req-grid-cascade-corpus-oracle-1")
@pytest.mark.spec("req-grid-cascade-corpus-oracle-2")
class TestDiscoverers:
    def test_three_way_convergence_admits_every_parent_at_the_right_depth(self) -> None:
        """R → {A, B, C}, each containing X (Codex's reproducer): A, B and C are all legitimate
        first discoverers of X, whatever order the database returns R's children in."""
        g = graph(
            ["R", "A", "B", "C", "X"],
            [
                ("R", "A", NESTS),
                ("R", "B", NESTS),
                ("R", "C", NESTS),
                ("A", "X", NESTS),
                ("B", "X", NESTS),
                ("C", "X", NESTS),
            ],
        )
        out = cascade(g, "R", mode="contained")
        assert out.node_parents["X"] == frozenset({"A", "B", "C"})
        assert out.node_parents["A"] == frozenset({"R"})

    def test_a_deeper_parent_is_never_a_legitimate_discoverer(self) -> None:
        """R → A → X and R → X: X is at depth 1, discovered by R; A (depth 1) reaches X too but
        only after X was already discovered, so A must not be admitted."""
        g = graph(["R", "A", "X"], [("R", "A", NESTS), ("A", "X", NESTS), ("R", "X", NESTS)])
        out = cascade(g, "R", mode="contained")
        assert out.node_parents["X"] == frozenset({"R"})

    def test_the_answer_does_not_depend_on_edge_order(self) -> None:
        base = [
            ("R", "A", NESTS),
            ("R", "B", NESTS),
            ("R", "C", NESTS),
            ("A", "X", NESTS),
            ("B", "X", NESTS),
            ("C", "X", NESTS),
        ]
        answers = set()
        for perm in itertools.permutations(base):
            out = cascade(graph(["R", "A", "B", "C", "X"], list(perm)), "R", mode="contained")
            answers.add((tuple(sorted(out.retired_nodes)), out.node_parents["X"]))
        assert len(answers) == 1

    def test_an_edge_between_same_depth_nodes_may_be_ended_by_either(self) -> None:
        g = graph(["R", "A", "B"], [("R", "A", NESTS), ("R", "B", NESTS), ("A", "B", NESTS)])
        out = cascade(g, "R", mode="contained")
        assert out.edge_parents["e_A_B_PG"] == frozenset({"A", "B"})
        assert out.edge_parents["e_R_A_PG"] == frozenset({"R"})
        assert out.node_parents["B"] == frozenset({"R"}), "B is at depth 1, reached from R, not through A"


@pytest.mark.spec("req-grid-cascade-corpus-oracle-2")
class TestOrderDependence:
    def test_block_and_overflow_both_reachable_is_refused_as_ambiguous(self) -> None:
        g = Graph(
            node_type={"R": N, "A": "grid_fixtures__hub", "B": N, "C": N},
            edges=(("e1", "R", "A", NESTS), ("e2", "R", "B", NESTS), ("e3", "R", "C", NESTS)),
            containment={N: (NESTS,), "grid_fixtures__hub": (NESTS,)},
            blocked_types=frozenset({"grid_fixtures__hub"}),
            pre_retired=frozenset(),
        )
        with pytest.raises(AmbiguousScenario, match="blocked node .* and an over-cap closure"):
            cascade(g, "R", mode="contained", cap=2)

    def test_block_alone_and_overflow_alone_are_deterministic(self) -> None:
        g = graph(["R", "A", "B"], [("R", "A", NESTS), ("R", "B", NESTS)])
        assert cascade(g, "R", mode="contained", cap=2).error_code == "cascade_closure_too_large"
        h = Graph(
            node_type={"R": N, "A": "grid_fixtures__hub"},
            edges=(("e1", "R", "A", NESTS),),
            containment={N: (NESTS,)},
            blocked_types=frozenset({"grid_fixtures__hub"}),
            pre_retired=frozenset(),
        )
        assert cascade(h, "R", mode="contained").error_code == "unsupported_operation"


@pytest.mark.spec("req-grid-cascade-corpus-oracle-3")
def test_a_pre_retired_edge_between_live_nodes_is_not_followed() -> None:
    g = graph(["R", "A"], [("R", "A", NESTS)], pre_retired_edges=("e_R_A_PG",))
    out = cascade(g, "R", mode="contained")
    assert out.retired_nodes == ["R"] and out.retired_edges == []


def test_the_model_imports_nothing_from_the_service_layer() -> None:
    import tap_grid.cascade_corpus.model_oracle as m

    assert not any(name.startswith("tap_grid.services") or name.startswith("django") for name in dir(m))
