"""Compound edges: the declaration, its checks, the retire rule in the delete walk, the closure read
and reconcile's contradiction exclusion (``req-grid-edge-compound``, ``tap_grid/specs/spec-grid-edge.md``).

The fixture is a compound edge built from ``grid_fixtures``' unconstrained types, which accept any
edge, so the role edges can carry the official names (``PROBE_SOURCE`` / ``PROBE_DESTINATION`` /
``TRAVERSES_COMPONENT``) without a plugin declaring them: ``COMPOUND_EDGE`` and, where a test needs
it, ``CONTAINMENT_EDGES`` are set per test with monkeypatch, as the cascade tests do. A monkeypatch
bypasses the class-creation guard, so every reader parses the declaration again; that is tested too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from tap_grid.compound_edges import (
    CompoundEdgeDeclarationError,
    compound_types,
    dependents_index,
    parse_compound_edge,
)
from tap_grid.models import BaseModel, BatchEvent, BatchEventType, Edge, Entity
from tap_grid.services import contained_closure, create_edge, create_node, delete_node

SENDER = "grid_fixtures__node"
MIDDLE = "grid_fixtures__unconstrained"
RECEIVER = "grid_fixtures__leaf"
COMPONENT = "grid_fixtures__cycle_node"
REGION = "grid_fixtures__hub"

SOURCE = "PROBE_SOURCE__grid_fixtures"
DESTINATION = "PROBE_DESTINATION__grid_fixtures"
PATH = "TRAVERSES_COMPONENT__grid_fixtures"
HOLDS = "HOLDS_LEAF__grid_fixtures"  # region → receiver, declared containment where a test needs it

DECLARATION: dict[str, Any] = {
    "source": SOURCE,
    "destination": DESTINATION,
    "carrier": None,
    "path": PATH,
    "retires_with": ("source", "destination"),
}


def _node(entity_type: str, name: str) -> Entity:
    result = create_node(entity_type, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return Entity.objects.get(pk=result.entity_id)


def _live(entity: Entity) -> bool:
    return Entity.objects.get(pk=entity.pk).deleted_at is None


def _delete_events(entity: Entity) -> list[BatchEvent]:
    return list(BatchEvent.objects.filter(entity_id=entity.pk, event_type=BatchEventType.DELETE))


def _model(entity_type: str) -> Any:
    from tap_grid.registry import get_model_class

    return get_model_class(entity_type)


@pytest.fixture
def declared(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    declaration = dict(DECLARATION)
    monkeypatch.setattr(_model(MIDDLE), "COMPOUND_EDGE", declaration, raising=False)
    return declaration


class Probe:
    """sender ─PROBE_SOURCE→ middle ─PROBE_DESTINATION→ receiver, middle ─TRAVERSES_COMPONENT→ component."""

    def __init__(self, name: str = "probe") -> None:
        self.sender = _node(SENDER, f"{name}-sender")
        self.middle = _node(MIDDLE, f"{name}-middle")
        self.receiver = _node(RECEIVER, f"{name}-receiver")
        self.component = _node(COMPONENT, f"{name}-component")
        self.source = create_edge(self.sender, self.middle, SOURCE)
        self.destination = create_edge(self.middle, self.receiver, DESTINATION)
        self.path = create_edge(self.middle, self.component, PATH)

    def edges(self) -> list[Edge]:
        return [self.source, self.destination, self.path]


def _edge_live(edge: Edge) -> bool:
    return Entity.objects.get(pk=edge.entity_id).deleted_at is None


# ---------------------------------------------------------------------------
# The declaration (-1, -2, -4)
# ---------------------------------------------------------------------------


class TestDeclaration:
    @pytest.mark.spec("req-grid-edge-compound-1")
    def test_no_type_is_a_middle_node_by_default_and_core_adds_no_base_type(self) -> None:
        assert BaseModel.COMPOUND_EDGE is None
        import tap_grid.models as grid_models

        assert not [
            n for n in dir(grid_models) if "compound" in n.lower() and isinstance(getattr(grid_models, n), type)
        ]

    @pytest.mark.spec("req-grid-edge-compound-2")
    def test_a_full_declaration_parses(self) -> None:
        parsed = parse_compound_edge("Probe", DECLARATION)
        assert parsed is not None
        assert parsed.kind == "PROBE"
        assert parsed.role_edges() == {"source": SOURCE, "destination": DESTINATION, "path": PATH}
        assert parsed.retires_with == ("source", "destination")
        assert parse_compound_edge("Probe", None) is None

    @pytest.mark.spec("req-grid-edge-compound-2")
    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"layers": ()}, "unknown key"),
            ({"retires_with": None}, "retires_with"),
            ({"retires_with": "source"}, "retires_with"),
            ({"retires_with": ("carrier",)}, "only an end"),
            ({"retires_with": ("source", "source")}, "repeats"),
            ({"destination": ""}, "edge-type slug"),
            ({"carrier": 7}, "edge-type slug"),
        ],
    )
    def test_a_malformed_declaration_is_refused(self, change: dict[str, Any], message: str) -> None:
        bad = {**DECLARATION, **change}
        bad = {k: v for k, v in bad.items() if not (k == "retires_with" and v is None)}
        with pytest.raises(CompoundEdgeDeclarationError, match=message):
            parse_compound_edge("Probe", bad)

    @pytest.mark.spec("req-grid-edge-compound-2")
    def test_a_role_edge_in_containment_is_refused_at_class_creation(self) -> None:
        from tap_grid.models import _check_compound_edge

        fake = type("FakeMiddle", (), {"COMPOUND_EDGE": dict(DECLARATION)})
        with pytest.raises(ImproperlyConfigured, match="never containment"):
            _check_compound_edge(fake, (DESTINATION,))
        _check_compound_edge(fake, ("OTHER_LINK__grid_fixtures",))
        broken = type("Broken", (), {"COMPOUND_EDGE": {**DECLARATION, "retires_with": ("path",)}})
        with pytest.raises(ImproperlyConfigured, match="only an end"):
            _check_compound_edge(broken, ())

    @pytest.mark.spec("req-grid-edge-compound-4")
    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"source": "PROBES_THING__grid_fixtures"}, "<KIND>_SOURCE"),
            ({"source": "SOURCE__grid_fixtures"}, "<KIND>_SOURCE"),
            ({"destination": "OTHER_DESTINATION__grid_fixtures"}, "one kind, one owning plugin"),
            ({"destination": "PROBE_DESTINATION__aws_core"}, "one kind, one owning plugin"),
            ({"carrier": "PROBE_RIDES_ON__grid_fixtures"}, "PROBE_CARRIER__grid_fixtures"),
            ({"path": "PASSES_THROUGH__grid_fixtures"}, "TRAVERSES_COMPONENT"),
        ],
    )
    def test_role_names_follow_the_official_exception(self, change: dict[str, Any], message: str) -> None:
        with pytest.raises(CompoundEdgeDeclarationError, match=message):
            parse_compound_edge("Probe", {**DECLARATION, **change})

    @pytest.mark.spec("req-grid-edge-compound-4")
    def test_the_two_planned_kinds_fit_the_declaration(self) -> None:
        """computing_core's application_flow and aws_core's reachability adopt this in plugin PRs."""
        flow = parse_compound_edge(
            "ApplicationFlow",
            {
                "source": "APPLICATION_FLOW_SOURCE__computing_core",
                "destination": "APPLICATION_FLOW_DESTINATION__computing_core",
                "retires_with": ["source", "destination"],
            },
        )
        reach = parse_compound_edge(
            "Reachability",
            {
                "source": "REACHABILITY_SOURCE__aws_core",
                "destination": "REACHABILITY_DESTINATION__aws_core",
                "path": "TRAVERSES_COMPONENT__aws_core",
                "retires_with": ["source", "destination"],
            },
        )
        assert flow is not None and flow.kind == "APPLICATION_FLOW" and flow.path is None
        assert reach is not None and reach.kind == "REACHABILITY" and reach.path == "TRAVERSES_COMPONENT__aws_core"

    @pytest.mark.spec("req-grid-edge-compound-4")
    @pytest.mark.spec("req-tap-plugin-edge-naming-5")
    def test_role_names_pass_the_structural_naming_check(self) -> None:
        from tap_plugins.validate.service import _edge_naming_violations

        for slug in ("REACHABILITY_SOURCE__aws_core", "REACHABILITY_DESTINATION__aws_core", "TCP_CARRIER__p", PATH):
            assert _edge_naming_violations(slug) == [], slug


# ---------------------------------------------------------------------------
# Resolution and admission (-3)
# ---------------------------------------------------------------------------


class TestRoleEdgesResolve:
    @pytest.mark.spec("req-grid-edge-compound-3")
    def test_role_edges_are_declarations_the_boot_check_resolves(self, declared: dict[str, Any]) -> None:
        from tap_grid.checks import check_edge_declarations_resolve

        errors = [e for e in check_edge_declarations_resolve(None) if "COMPOUND_EDGE" in e.msg]
        named = sorted(e.msg.split("names edge type ")[1].split(",")[0].strip("'") for e in errors)
        assert named == sorted([SOURCE, DESTINATION, PATH]), [e.msg for e in errors]
        assert all(e.id == "tap_grid.E004" for e in errors)

    @pytest.mark.spec("req-grid-edge-compound-3")
    def test_the_static_reader_sees_role_edges(self, tmp_path: Path) -> None:
        from tap.edge_declarations import read_declarations

        (tmp_path / "models.py").write_text(
            "class Reach:\n"
            '    ENTITY_TYPE = "p__reach"\n'
            "    COMPOUND_EDGE = {\n"
            '        "source": "REACH_SOURCE__p", "destination": "REACH_DESTINATION__p",\n'
            '        "carrier": None, "path": "TRAVERSES_COMPONENT__p", "retires_with": ("source",),\n'
            "    }\n",
            encoding="utf-8",
        )
        found, unreadable = read_declarations(tmp_path)
        assert not unreadable
        assert [(d.owner, d.attribute, d.edge_type) for d in found] == [
            ("p__reach", "COMPOUND_EDGE", "REACH_SOURCE__p"),
            ("p__reach", "COMPOUND_EDGE", "REACH_DESTINATION__p"),
            ("p__reach", "COMPOUND_EDGE", "TRAVERSES_COMPONENT__p"),
        ]

    @pytest.mark.spec("req-grid-edge-compound-3")
    def test_a_role_edge_nothing_admits_onto_the_middle_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.checks import check_compound_edge_roles_admit_the_middle, compound_edge_problems

        assert compound_edge_problems() == [], "the shipped stack declares no unwritable role"
        # INBOUND_EDGES = [] (nothing reaches it) and an OUTBOUND_EDGES that names none of the roles,
        # while the role edges define no endpoints: no role can be written onto it, in either direction.
        blocked = "grid_fixtures__inbound_blocked"
        monkeypatch.setattr(_model(blocked), "COMPOUND_EDGE", dict(DECLARATION), raising=False)
        problems = compound_edge_problems()
        assert sorted(p.split("COMPOUND_EDGE[")[1].split("]")[0] for p in problems) == [
            "'destination'",
            "'path'",
            "'source'",
        ]
        assert all(blocked in p for p in problems)
        errors = check_compound_edge_roles_admit_the_middle(None)
        assert {e.id for e in errors} == {"tap_grid.E006"} and len(errors) == 3

    @pytest.mark.spec("req-grid-edge-compound-3")
    def test_an_unconstrained_middle_admits_its_roles(self, declared: dict[str, Any]) -> None:
        from tap_grid.checks import compound_edge_problems

        assert compound_edge_problems() == []

    @pytest.mark.spec("req-grid-edge-compound-3")
    def test_a_declaration_broken_after_class_creation_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.checks import compound_edge_problems

        monkeypatch.setattr(_model(MIDDLE), "COMPOUND_EDGE", {**DECLARATION, "retires_with": ("carrier",)})
        assert any("only an end" in p for p in compound_edge_problems())


# ---------------------------------------------------------------------------
# The retire rule in the delete walk (-5, -8)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRetireWithAnEnd:
    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_deleting_the_source_retires_the_middle_node(self, declared: dict[str, Any]) -> None:
        p = Probe()
        result = delete_node(p.sender.pk, reason="operator")
        assert result.success, result.errors
        assert not _live(p.sender) and not _live(p.middle)
        assert _live(p.receiver) and _live(p.component)
        assert not any(_edge_live(e) for e in p.edges())
        [event] = _delete_events(p.middle)
        assert event.metadata["reason"] == "cascaded"
        assert event.metadata["consequence_of"] == str(p.sender.pk)
        assert event.metadata["cascade_root"] == str(p.sender.pk)
        assert event.metadata["root_reason"] == "operator"
        assert event.metadata["compound_end"] == "source"

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_deleting_the_destination_retires_the_middle_node(self, declared: dict[str, Any]) -> None:
        p = Probe()
        assert delete_node(p.receiver.pk).success
        assert not _live(p.middle) and _live(p.sender) and _live(p.component)
        [event] = _delete_events(p.middle)
        assert event.metadata["compound_end"] == "destination"
        assert event.metadata["root_reason"] == "unspecified"
        # The middle node's edges ended with the walk's provenance; the sender's own edges too.
        unlink = BatchEvent.objects.get(entity_id=p.source.entity_id, event_type=BatchEventType.UNLINK)
        assert unlink.metadata["consequence_of"] == str(p.middle.pk)

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_an_end_not_in_retires_with_leaves_the_middle_node(self, declared: dict[str, Any]) -> None:
        declared["retires_with"] = ("source",)
        p = Probe()
        assert delete_node(p.receiver.pk).success
        assert _live(p.middle), "the destination is not a retiring end for this kind"
        assert not _edge_live(p.destination) and _edge_live(p.source)
        assert delete_node(p.sender.pk).success
        assert not _live(p.middle)

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_both_ends_in_one_walk_retire_the_middle_once(self, declared: dict[str, Any], monkeypatch) -> None:
        monkeypatch.setattr(_model(REGION), "CONTAINMENT_EDGES", (HOLDS,), raising=False)
        p = Probe()
        region = _node(REGION, "region")
        create_edge(region, p.sender, HOLDS)
        create_edge(region, p.receiver, HOLDS)
        result = delete_node(region.pk, cascade="contained", reason="operator")
        assert result.success, result.errors
        assert not any(_live(n) for n in (region, p.sender, p.receiver, p.middle))
        assert _live(p.component)
        events = _delete_events(p.middle)
        assert len(events) == 1
        assert events[0].metadata["consequence_of"] in {str(p.sender.pk), str(p.receiver.pk)}
        assert events[0].metadata["cascade_root"] == str(region.pk)

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_a_contained_cascade_reaching_one_end_retires_the_middle(
        self, declared: dict[str, Any], monkeypatch
    ) -> None:
        monkeypatch.setattr(_model(REGION), "CONTAINMENT_EDGES", (HOLDS,), raising=False)
        p = Probe()
        region = _node(REGION, "region")
        create_edge(region, p.receiver, HOLDS)
        assert delete_node(region.pk, cascade="contained").success
        assert not _live(p.receiver) and not _live(p.middle)
        assert _live(p.sender) and _live(p.component)
        [event] = _delete_events(p.middle)
        assert event.metadata["consequence_of"] == str(p.receiver.pk)

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_the_middle_node_counts_against_the_cap(self, declared: dict[str, Any]) -> None:
        sender = _node(SENDER, "busy-sender")
        middles = []
        for i in range(2):
            m = _node(MIDDLE, f"m{i}")
            create_edge(sender, m, SOURCE)
            middles.append(m)
        with override_settings(TAP_CASCADE_MAX_CLOSURE=2):
            result = delete_node(sender.pk)
        assert not result.success
        assert result.errors[0].code == "cascade_closure_too_large"
        assert _live(sender) and all(_live(m) for m in middles), "refused whole: nothing written"

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_a_plain_delete_that_retires_no_middle_keeps_its_shape(self, declared: dict[str, Any]) -> None:
        lone = _node(SENDER, "lone")
        other = _node(RECEIVER, "other")
        edge = create_edge(lone, other, "WILDCARD_LINK__grid_fixtures")
        assert delete_node(lone.pk).success
        assert not BatchEvent.objects.filter(entity_id=edge.entity_id, event_type=BatchEventType.UNLINK).exists()
        assert "compound_end" not in _delete_events(lone)[0].metadata

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_an_open_ended_role_edge_onto_another_type_retires_nothing(self, declared: dict[str, Any]) -> None:
        sender = _node(SENDER, "sender")
        not_a_middle = _node(RECEIVER, "not-a-middle")
        create_edge(sender, not_a_middle, SOURCE)
        assert delete_node(sender.pk).success
        assert _live(not_a_middle)

    @pytest.mark.spec("req-grid-edge-compound-8")
    def test_deleting_a_path_component_never_retires_the_middle(self, declared: dict[str, Any]) -> None:
        p = Probe()
        assert delete_node(p.component.pk).success
        assert _live(p.middle) and _live(p.sender) and _live(p.receiver)
        assert not _edge_live(p.path) and _edge_live(p.source) and _edge_live(p.destination)

    @pytest.mark.spec("req-grid-edge-compound-8")
    def test_deleting_the_middle_node_retires_neither_end_nor_a_component(self, declared: dict[str, Any]) -> None:
        p = Probe()
        assert delete_node(p.middle.pk, cascade="contained").success
        assert _live(p.sender) and _live(p.receiver) and _live(p.component)
        assert not any(_edge_live(e) for e in p.edges())

    @pytest.mark.spec("req-grid-edge-compound-8")
    def test_a_carrier_edge_retires_nothing(self, declared: dict[str, Any]) -> None:
        declared["carrier"] = "PROBE_CARRIER__grid_fixtures"
        upper, lower = Probe("upper"), Probe("lower")
        create_edge(upper.middle, lower.middle, "PROBE_CARRIER__grid_fixtures")
        assert delete_node(lower.middle.pk).success
        assert _live(upper.middle), "what a compound stack's vertical link retires is undecided; nothing, today"

    @pytest.mark.spec("req-grid-edge-compound-5")
    def test_the_index_holds_only_retiring_ends(self, declared: dict[str, Any]) -> None:
        index = dependents_index()
        assert index.by_source == {SOURCE: frozenset({MIDDLE})}
        assert index.by_destination == {DESTINATION: frozenset({MIDDLE})}
        assert PATH not in index.by_source and PATH not in index.by_destination
        assert MIDDLE in compound_types()
        declared["retires_with"] = ()
        assert not dependents_index()


# ---------------------------------------------------------------------------
# The closure read (-6) and reconcile's contradiction check (-7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClosureAndReconcile:
    @pytest.fixture
    def held(self, declared: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> tuple[Entity, Probe]:
        monkeypatch.setattr(_model(REGION), "CONTAINMENT_EDGES", (HOLDS,), raising=False)
        p = Probe()
        region = _node(REGION, "region")
        create_edge(region, p.receiver, HOLDS)
        return region, p

    @pytest.mark.spec("req-grid-edge-compound-6")
    def test_the_closure_read_shows_the_middle_node(self, held: tuple[Entity, Probe]) -> None:
        region, p = held
        assert contained_closure(region.pk) == frozenset({p.receiver.pk, p.middle.pk})
        assert contained_closure(p.sender.pk) == frozenset({p.middle.pk}), "a plain end's dependents"

    @pytest.mark.spec("req-grid-edge-compound-7")
    def test_the_contradiction_read_leaves_middle_nodes_out(self, held: tuple[Entity, Probe]) -> None:
        region, p = held
        assert contained_closure(region.pk, compound_dependents=False) == frozenset({p.receiver.pk})

    @pytest.mark.spec("req-grid-edge-compound-7")
    def test_a_middle_node_observed_this_run_is_no_contradiction(self, held: tuple[Entity, Probe]) -> None:
        from tap_grid.candidates import _contradiction_of

        region, p = held
        assert _contradiction_of(region.pk, REGION, {p.middle.pk}) is None
        contradicted = _contradiction_of(region.pk, REGION, {p.receiver.pk})
        assert contradicted is not None and contradicted["observed_descendants"] == [str(p.receiver.pk)]

    @pytest.mark.spec("req-grid-edge-compound-7")
    def test_the_apply_fence_leaves_middle_nodes_out(self, declared: dict[str, Any], monkeypatch) -> None:
        """A middle node written after the candidate record was derived is not live evidence against it."""
        from django.utils import timezone

        from tap_grid.reconcile import _closure_observed_since

        monkeypatch.setattr(_model(REGION), "CONTAINMENT_EDGES", (HOLDS,), raising=False)
        region = _node(REGION, "region")
        receiver = _node(RECEIVER, "receiver")
        create_edge(region, receiver, HOLDS)
        since = timezone.now()
        sender = _node(SENDER, "sender")
        middle = _node(MIDDLE, "middle")
        create_edge(sender, middle, SOURCE)
        create_edge(middle, receiver, DESTINATION)
        assert _closure_observed_since(region.pk, since, set()) is None
        # Control: the same fence does see a contained node written after `since`.
        late = _node(RECEIVER, "late")
        create_edge(region, late, HOLDS)
        assert _closure_observed_since(region.pk, since, set()) is not None


def test_history_is_untouched_by_the_declaration() -> None:
    """History stays on for middle nodes: the declaration carries no history switch, and the
    parser has no key that could carry one (ruled on Issue# 1261 - tap)."""
    with pytest.raises(CompoundEdgeDeclarationError, match="unknown key"):
        parse_compound_edge("Probe", {**DECLARATION, "track_history": False})
    assert BaseModel.TRACK_HISTORY is True
