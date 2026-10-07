"""Edge authority, dry-run: a batch claims a scope's edges are total, and the importer records what
that would remove, removing nothing.

Spec: ``req-grid-reconcile-edge-authority`` in ``tap_grid/specs/spec-grid-reconcile.md`` (Issue# 919 -
tap), and the ``edge_cases`` shape of ``req-grift-edge-identity-surface``. Nodes are panels
(``tap_web``), keyed on ``slug``, so an anchor can be named by key; edges are the unconstrained
``PG_LINKS__grid_fixtures``, addressed by explicit id so edge identity stays out of the way.

A claim needs a producing run for its read boundary. ``_run`` binds a batch stamped the way a
collection run's lifecycle batch is, as ``run_collection`` does; the end-to-end run is in
``tap_cares/tests/test_edge_authority_run.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from tap_grid.batch import create_batch
from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType, Edge, Entity
from tap_grid.reconcile import RUN_CONFIG_KEY, run_config
from tap_grid.tests.test_grift_edge_endpoints import _doc, _key, _panel

SPEC = {n: pytest.mark.spec(f"req-grid-reconcile-edge-authority-{n}") for n in (1, 2, 3, 4, 5, 6, 7, 8, 10)}
SURFACE = {n: pytest.mark.spec(f"req-grift-edge-identity-surface-{n}") for n in (1, 3)}
LINK = "PG_LINKS__grid_fixtures"
OTHER = "WILDCARD_LINK__grid_fixtures"


def _edge(source: str, target: str, *, edge_type: str = LINK, edge_id: str | None = None) -> dict[str, Any]:
    return {
        "entity": {"entity_id": edge_id or str(uuid.uuid4()), "entity_type": "edge", "dimensions": {}},
        "edge": {"edge_type": edge_type, "from_entity_id": source, "to_entity_id": target, "properties": {}},
    }


def _claim(anchor: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"edge_type": LINK, "anchor": anchor, "direction": "outbound", "read": "complete", **fields}


def _import(*claims: dict[str, Any], edges: list[dict[str, Any]] | None = None, **options: Any) -> Any:
    return grift_import(_doc(edges=edges or [], edge_cases={"authority": list(claims)}), **options)


def _seed(*slugs: str) -> dict[str, str]:
    nodes = [_panel(s) for s in slugs]
    result = grift_import(_doc(nodes=nodes))
    assert result.success, result.errors
    return {n["node"]["slug"]: n["entity"]["entity_id"] for n in nodes}


def _link(*edges: dict[str, Any]) -> list[str]:
    result = grift_import(_doc(edges=list(edges)))
    assert result.success, result.errors
    return [e["entity"]["entity_id"] for e in edges]


@contextmanager
def _run(*, stamped: bool = True) -> Iterator[Any]:
    """Bind a run's batch as the caller's, the way a collection run binds its lifecycle batch."""
    config = {RUN_CONFIG_KEY: run_config(authority=False, budget=None, collector="test")} if stamped else None
    run = create_batch(source="t:run", name="run", description="a test run", metadata=config)
    prior = get_caller_context()
    set_caller_context(CallerContext(user=prior.user if prior else None, batch_id=str(run.entity_id)))
    try:
        yield run
    finally:
        set_caller_context(prior)


def _proposals(result: Any) -> dict[str, dict[str, Any]]:
    """The claiming batch's per-edge records, by edge id."""
    (batch,) = result.imported_batches
    return {
        str(e.entity_id): e.metadata
        for e in BatchEvent.objects.filter(
            batch__entity_id=batch.batch_entity_id, event_type=BatchEventType.AUTHORITY_PROPOSED, entity_type="edge"
        )
    }


def _proposed(result: Any) -> set[str]:
    return {edge_id for edge_id, m in _proposals(result).items() if m["outcome"] == "proposed"}


def _codes(result: Any) -> list[str]:
    return [e.code for e in result.errors]


@pytest.fixture
def star() -> dict[str, str]:
    """``hub`` with LINK edges out to ``b`` and ``c``, an OTHER edge out to ``d``, and a LINK edge in from
    ``d``: all written before any run opens."""
    ids = _seed("hub", "b", "c", "d")
    hub_b, hub_c, hub_d, d_hub = _link(
        _edge(ids["hub"], ids["b"]),
        _edge(ids["hub"], ids["c"]),
        _edge(ids["hub"], ids["d"], edge_type=OTHER),
        _edge(ids["d"], ids["hub"]),
    )
    return {**ids, "hub_b": hub_b, "hub_c": hub_c, "hub_d": hub_d, "d_hub": d_hub}


@pytest.mark.django_db
class TestTheStatementShape:
    @SPEC[1]
    @pytest.mark.parametrize(
        "claim",
        [
            {"edge_type": LINK, "anchor": {"entity_id": str(uuid.uuid4())}, "direction": "outbound"},
            {
                "edge_type": LINK,
                "anchor": {"entity_id": str(uuid.uuid4())},
                "direction": "sideways",
                "read": "complete",
            },
            {"edge_type": LINK, "anchor": {"entity_id": str(uuid.uuid4())}, "direction": "outbound", "read": "mostly"},
        ],
        ids=["no read", "unknown direction", "unknown read"],
    )
    def test_a_malformed_claim_fails_the_document_with_nothing_written(self, claim: dict[str, Any]) -> None:
        result = _import(claim)
        assert _codes(result) == ["schema_validation_failed"]
        assert not BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED).exists()

    @SPEC[1]
    def test_dimensions_are_reserved_and_refused(self) -> None:
        result = _import(_claim({"entity_id": str(uuid.uuid4())}, dimensions={"tap.graph": "web"}))
        assert _codes(result) == ["authority_dimensions_reserved"]

    @SURFACE[3]
    def test_edge_cases_is_closed(self) -> None:
        result = grift_import(_doc(edge_cases={"authority": [], "overwrite": "always"}))
        assert _codes(result) == ["schema_validation_failed"]

    @SPEC[1]
    def test_an_internal_only_edge_type_is_refused(self) -> None:
        """Its removal is the owning subsystem's, which the generic path refuses (req-grid-edge-internal)."""
        result = _import(_claim({"entity_id": str(uuid.uuid4())}, edge_type="PRODUCED_BATCH"))
        assert _codes(result) == ["authority_internal_edge_type"]

    @SPEC[1]
    def test_a_key_anchor_that_could_never_resolve_is_refused(self) -> None:
        result = _import(_claim(_key("hub", entity_type="grid_fixtures__node")))
        assert _codes(result) == ["endpoint_type_unkeyed"]

    @SURFACE[1]
    def test_the_schema_accepts_a_claim_now_that_the_importer_honours_it(self, star: dict[str, str]) -> None:
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}))
        assert result.success, result.errors


@pytest.mark.django_db
class TestTheDryRun:
    @SPEC[2]
    @SPEC[3]
    def test_every_live_edge_in_scope_the_batch_does_not_assert_is_proposed(self, star: dict[str, str]) -> None:
        """Dominant: the proposed edge was written by another batch, not the claimant."""
        with _run():
            result = _import(
                _claim({"entity_id": star["hub"]}), edges=[_edge(star["hub"], star["b"], edge_id=star["hub_b"])]
            )
        assert result.success, result.errors
        assert _proposed(result) == {star["hub_c"]}

    @SPEC[3]
    def test_a_new_edge_the_batch_writes_is_asserted(self, star: dict[str, str]) -> None:
        with _run():
            fresh = _edge(star["hub"], star["d"])
            result = _import(_claim({"entity_id": star["hub"]}), edges=[fresh])
        assert fresh["entity"]["entity_id"] not in _proposals(result)
        assert _proposed(result) == {star["hub_b"], star["hub_c"]}

    @SPEC[2]
    def test_the_scope_is_one_type_in_one_direction(self, star: dict[str, str]) -> None:
        with _run():
            outbound = _import(_claim({"entity_id": star["hub"]}))
            inbound = _import(_claim({"entity_id": star["hub"]}, direction="inbound"))
        assert _proposed(outbound) == {star["hub_b"], star["hub_c"]}, "OTHER and the inbound edge are out of scope"
        assert _proposed(inbound) == {star["d_hub"]}

    @SPEC[2]
    def test_an_anchor_named_by_key_resolves(self, star: dict[str, str]) -> None:
        with _run():
            result = _import(_claim(_key("hub")))
        (claim,) = result.imported_batches[0].authority
        assert claim["anchor_entity_id"] == star["hub"]
        assert _proposed(result) == {star["hub_b"], star["hub_c"]}

    @SPEC[3]
    def test_a_skipped_edge_counts_as_asserted(self, star: dict[str, str]) -> None:
        """An edge the batch could not wire is listed among what it asserts, never read as a denial."""
        unwired = {
            "entity": {"entity_id": str(uuid.uuid4()), "entity_type": "edge", "dimensions": {}},
            "edge": {"edge_type": LINK, "from_entity_id": star["hub"], "to_key": _key("nobody"), "properties": {}},
        }
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}), edges=[unwired], dangling_edge_mode="permissive")
        assert result.success, result.errors
        (skip,) = result.imported_batches[0].skips
        (claim,) = result.imported_batches[0].authority
        assert claim["asserted_skipped"] == [skip["event_id"]]
        assert claim["asserted"] == 1

    @SPEC[2]
    def test_an_anchor_that_names_nothing_proposes_nothing(self, star: dict[str, str]) -> None:
        with _run():
            result = _import(_claim(_key("nobody")))
        (claim,) = result.imported_batches[0].authority
        assert (claim["outcome"], claim["reason"]) == ("not_claimed", "anchor_unresolved")
        assert _proposals(result) == {}

    @SPEC[6]
    def test_nothing_is_removed_ended_or_changed(self, star: dict[str, str]) -> None:
        before = {e: Entity.objects.get(pk=e).version for e in (star["hub_b"], star["hub_c"])}
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}))
        assert _proposed(result) == {star["hub_b"], star["hub_c"]}
        for edge_id, version in before.items():
            entity = Entity.objects.get(pk=edge_id)
            assert (entity.deleted_at, entity.version) == (None, version)
        (batch,) = result.imported_batches
        assert not BatchEvent.objects.filter(
            batch__entity_id=batch.batch_entity_id, event_type=BatchEventType.UNLINK
        ).exists()

    @SPEC[7]
    def test_each_proposal_is_recorded_whole_and_counted(self, star: dict[str, str]) -> None:
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}))
        record = _proposals(result)[star["hub_c"]]
        assert record["outcome"] == "proposed"
        assert record["claim"] == {
            "edge_type": LINK,
            "anchor": {"entity_id": star["hub"]},
            "anchor_entity_id": star["hub"],
            "direction": "outbound",
            "read": "complete",
        }
        assert record["identity"] == {
            "edge_type": LINK,
            "from_entity_id": star["hub"],
            "to_entity_id": star["c"],
            "discriminators": {},
        }
        (claim,) = result.imported_batches[0].authority
        assert (claim["outcome"], claim["proposed"], claim["rejected_stale"]) == ("claimed", 2, 0)
        claim_event = BatchEvent.objects.get(pk=claim["event_id"])
        assert (claim_event.event_type, claim_event.entity_type) == (BatchEventType.AUTHORITY_PROPOSED, "batch")
        assert result.counts.edges_proposed == 2


@pytest.mark.django_db
class TestOneClaimPerScope:
    @SPEC[4]
    def test_one_anchor_named_twice_fails_the_batch_with_nothing_written(self, star: dict[str, str]) -> None:
        fresh = _edge(star["hub"], star["d"])
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}), _claim(_key("hub")), edges=[fresh])
        assert "duplicate_authority_claim" in _codes(result)
        assert not Entity.objects.filter(pk=fresh["entity"]["entity_id"]).exists()
        assert not BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED).exists()

    @SPEC[4]
    def test_the_two_directions_are_two_scopes(self, star: dict[str, str]) -> None:
        with _run():
            result = _import(
                _claim({"entity_id": star["hub"]}), _claim({"entity_id": star["hub"]}, direction="inbound")
            )
        assert result.success, result.errors


@pytest.mark.django_db
class TestOnlyACompleteReadLicenses:
    @SPEC[5]
    @pytest.mark.parametrize("read", ["partial", "failed"])
    def test_a_partial_or_failed_read_proposes_nothing(self, star: dict[str, str], read: str) -> None:
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}, read=read))
        assert result.success, result.errors
        (claim,) = result.imported_batches[0].authority
        assert (claim["outcome"], claim["reason"], claim["proposed"]) == ("not_claimed", read, 0)
        assert _proposals(result) == {}


@pytest.mark.django_db
class TestTheFence:
    @SPEC[8]
    def test_an_edge_observed_after_the_run_opened_is_rejected_stale(self, star: dict[str, str]) -> None:
        with _run():
            (late,) = _link(_edge(star["hub"], star["d"]))
            result = _import(_claim({"entity_id": star["hub"]}))
        record = _proposals(result)[late]
        assert record["outcome"] == "rejected_stale"
        assert len(record["observed_by"]) == 1
        assert _proposed(result) == {star["hub_b"], star["hub_c"]}

    @SPEC[8]
    def test_a_re_observation_by_another_batch_fences_an_older_edge(self, star: dict[str, str]) -> None:
        with _run():
            _link(_edge(star["hub"], star["c"], edge_id=star["hub_c"]))  # re-sent: an update, after the opening
            result = _import(_claim({"entity_id": star["hub"]}))
        assert _proposals(result)[star["hub_c"]]["outcome"] == "rejected_stale"
        assert _proposed(result) == {star["hub_b"]}

    @SPEC[8]
    def test_no_producing_run_means_no_read_boundary(self, star: dict[str, str]) -> None:
        result = _import(_claim({"entity_id": star["hub"]}))
        (claim,) = result.imported_batches[0].authority
        assert (claim["outcome"], claim["reason"]) == ("not_claimed", "no_read_boundary")
        assert _proposals(result) == {}

    @SPEC[8]
    def test_a_caller_bound_to_no_batch_has_no_boundary(self, star: dict[str, str]) -> None:
        prior = get_caller_context()
        set_caller_context(CallerContext(user=prior.user if prior else None, batch_id=None))
        try:
            result = _import(_claim({"entity_id": star["hub"]}))
        finally:
            set_caller_context(prior)
        (claim,) = result.imported_batches[0].authority
        assert claim["reason"] == "no_read_boundary"
        assert _proposals(result) == {}

    @SPEC[8]
    def test_a_bound_batch_that_is_not_a_run_has_no_boundary(self, star: dict[str, str]) -> None:
        with _run(stamped=False):
            result = _import(_claim({"entity_id": star["hub"]}))
        (claim,) = result.imported_batches[0].authority
        assert claim["reason"] == "no_read_boundary"

    @SPEC[8]
    def test_a_document_cannot_supply_its_own_boundary(self, star: dict[str, str]) -> None:
        """The run stamp on the claiming batch's own metadata names no run: only the caller's binding does."""
        doc = _doc(edge_cases={"authority": [_claim({"entity_id": star["hub"]})]})
        doc["batches"][0]["batch_node"]["metadata"] = {
            RUN_CONFIG_KEY: run_config(authority=True, budget=None, collector="forged")
        }
        result = grift_import(doc)
        (claim,) = result.imported_batches[0].authority
        assert claim["reason"] == "no_read_boundary"


@pytest.mark.django_db(transaction=True)
class TestAConcurrentWriter:
    @SPEC[7]
    @SPEC[8]
    def test_an_edge_created_at_the_anchor_while_a_claim_is_judged_is_in_the_record(self, star: dict[str, str]) -> None:
        """A writer holding the anchor creates an edge there: the claim waits for it, then records it.

        Without the anchor lock the claim would read its scope while the writer is mid-flight, and an
        edge committed between that read and the claim's commit would be in no record at all.
        """
        from tap_grid.cascade_corpus.timing import contend

        with _run():
            holder, claimant = contend(
                uuid.UUID(star["hub"]),
                lambda: _link(_edge(star["hub"], star["d"]))[0],
                lambda: _import(_claim({"entity_id": star["hub"]})),
            )
        late = holder.value
        assert _proposals(claimant.value)[late]["outcome"] == "rejected_stale"
        assert _proposed(claimant.value) == {star["hub_b"], star["hub_c"]}


@pytest.mark.django_db
class TestARolledBackBatchReportsNothing:
    @SPEC[7]
    def test_a_failure_at_commit_leaves_no_proposal_reported(
        self, star: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A batch whose transaction fails as it ends (a deferred constraint at commit) reports no claim."""
        from contextlib import contextmanager
        from types import SimpleNamespace

        from django.db import IntegrityError, transaction

        from tap_grid.grift import importer

        real_atomic = transaction.atomic

        @contextmanager
        def failing_at_the_end(*args: Any, **kwargs: Any) -> Iterator[None]:
            with real_atomic(*args, **kwargs):
                yield
                raise IntegrityError("a deferred constraint failed at commit")

        monkeypatch.setattr(importer, "transaction", SimpleNamespace(atomic=failing_at_the_end))
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}))
        assert not result.success
        (batch,) = result.imported_batches
        assert (batch.authority, batch.edges_proposed, result.counts.edges_proposed) == ([], 0, 0)
        assert not BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED).exists()


@pytest.mark.django_db
class TestAProposalIsARead:
    @SPEC[10]
    def test_an_actor_refused_read_is_refused_the_claim_and_nothing_is_recorded(
        self, star: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        real_authorize = policy.authorize
        asked: list[str] = []

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "grift_import_edge_authority":
                asked.append(capability)
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        with _run():
            result = _import(_claim({"entity_id": star["hub"]}))
        assert asked == [READ_CAPABILITY]
        assert not result.success
        assert not BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED).exists()
        assert Edge.objects.filter(entity_id__in=[star["hub_b"], star["hub_c"]]).count() == 2

    @SPEC[10]
    @pytest.mark.parametrize("holds_read", [True, False], ids=["holds read", "lacks read"])
    def test_a_real_actor_needs_read_to_claim(self, star: dict[str, str], holds_read: bool) -> None:
        """No monkeypatch: an actor holding import and write, with and without read."""
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType

        from tap_auth import capabilities as caps
        from tap_auth import sync
        from tap_auth.models import Capability, User

        sync.sync_auth()
        held = [caps.IMPORT_GRIFT_CAPABILITY, caps.WRITE_CAPABILITY] + ([caps.READ_CAPABILITY] if holds_read else [])
        group = Group.objects.create(name=f"t919-{holds_read}")
        content_type = ContentType.objects.get_for_model(Capability)
        for capability in held:
            group.permissions.add(
                Permission.objects.get(content_type=content_type, codename=caps.codename_for(capability))
            )
        actor = User.objects.create_user(username=f"t919-{holds_read}", password="x")
        actor.groups.add(group)

        with _run():
            result = _import(_claim({"entity_id": star["hub"]}), actor=actor)
        assert result.success is holds_read, result.errors
        proposals = BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED, entity_type="edge")
        assert proposals.count() == (2 if holds_read else 0)
