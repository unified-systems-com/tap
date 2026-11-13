"""Writing an entity's dimensions map: stored shape, provenance, absence and the wire
(req-grid-dimension-reference; George 2026-11-12, aws-build Q46, Q47,
Q48, Q54).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tap_grid import dimension_vocabulary as vocab
from tap_grid.dimension_map import DimensionWriteError, patch, rederive, stamp, supplied

OPEN = "01a1d150-2222-7000-8000-000000000001"
BOUNDED = "01a1d150-2222-7000-8000-000000000002"
EMPTY_OK = "01a1d150-2222-7000-8000-000000000003"


@pytest.fixture
def table() -> Iterator[None]:
    saved = vocab.vocabulary()
    vocab.reset(
        vocab.Vocabulary(
            by_id={
                OPEN: vocab.DeclaredDimension(OPEN, "tap.test.open", None, False, "test"),
                BOUNDED: vocab.DeclaredDimension(BOUNDED, "tap.test.bounded", ("a", "b"), False, "test"),
                EMPTY_OK: vocab.DeclaredDimension(EMPTY_OK, "tap.test.empty_ok", None, False, "test", empty_is_meaningful=True),
            },
            by_name={"tap.test.open": (OPEN,), "tap.test.bounded": (BOUNDED,), "tap.test.empty_ok": (EMPTY_OK,)},
        )
    )
    yield
    vocab.reset(saved)


@pytest.mark.spec("req-grid-dimension-reference-3")
@pytest.mark.usefixtures("table")
class TestProvenance:
    def test_defaults_are_stamped_default_and_the_caller_declared(self) -> None:
        stored = stamp({"tap.test.open": "x"}, {"tap.test.bounded": "a"})
        assert stored == {OPEN: {"v": "x", "src": "default"}, BOUNDED: {"v": "a", "src": "declared"}}

    def test_the_caller_beats_a_default_even_with_an_empty_value(self) -> None:
        """#712, where the dimension declares empty meaningful."""
        assert stamp({"tap.test.empty_ok": "x"}, {"tap.test.empty_ok": ""}) == {EMPTY_OK: {"v": "", "src": "declared"}}

    def test_a_key_may_be_a_name_or_a_node_id(self) -> None:
        assert supplied({OPEN: "x"}) == supplied({"tap.test.open": "x"})

    def test_an_undeclared_key_is_refused_and_never_minted(self) -> None:
        with pytest.raises(LookupError, match="tap.test.nobody"):
            supplied({"tap.test.nobody": "x"})


@pytest.mark.spec("req-grid-dimension-reference-6")
@pytest.mark.usefixtures("table")
class TestTheWire:
    def test_src_default_is_refused_from_a_writer(self) -> None:
        with pytest.raises(DimensionWriteError, match="default"):
            supplied({"tap.test.open": {"v": "x", "src": "default"}})

    def test_src_derived_is_reset_to_declared_unless_trusted(self) -> None:
        raw = {"tap.test.open": {"v": "x", "src": "derived"}}
        assert supplied(raw)[OPEN]["src"] == "declared"
        assert supplied(raw, trusted=True)[OPEN]["src"] == "derived"

    def test_a_value_object_holds_only_v_and_src(self) -> None:
        with pytest.raises(DimensionWriteError):
            supplied({"tap.test.open": {"v": "x", "extra": 1}})

    def test_a_value_is_a_string(self) -> None:
        with pytest.raises(DimensionWriteError):
            supplied({"tap.test.open": 3})


@pytest.mark.spec("req-grid-dimension-knobs-2")
@pytest.mark.usefixtures("table")
class TestBounded:
    def test_a_value_outside_a_bounded_dimension_is_refused(self) -> None:
        with pytest.raises(DimensionWriteError, match="bounded"):
            supplied({"tap.test.bounded": "c"})

    def test_an_open_dimension_accepts_any_string(self) -> None:
        assert supplied({"tap.test.open": "anything"})[OPEN]["v"] == "anything"


@pytest.mark.spec("req-grid-dimension-knobs-4")
@pytest.mark.usefixtures("table")
class TestEmptyIsMeaningful:
    def test_an_empty_value_is_refused_unless_the_dimension_says_it_means_something(self) -> None:
        with pytest.raises(DimensionWriteError, match="empty"):
            supplied({"tap.test.open": ""})
        with pytest.raises(DimensionWriteError, match="empty"):
            stamp({"tap.test.open": ""}, None)
        assert supplied({"tap.test.empty_ok": ""})[EMPTY_OK] == {"v": "", "src": "declared"}


@pytest.mark.spec("req-grid-dimension-reference-7")
@pytest.mark.usefixtures("table")
class TestAbsence:
    def test_null_is_never_stored(self) -> None:
        assert supplied({"tap.test.open": None}) == {}

    def test_a_patch_leaves_omitted_keys_and_removes_a_null_one(self) -> None:
        stored = stamp(None, {"tap.test.open": "x", "tap.test.bounded": "a"})
        assert patch(stored, {"tap.test.bounded": None}) == {OPEN: {"v": "x", "src": "declared"}}
        assert patch(stored, {}) == stored

    def test_rederivation_replaces_only_derived_or_absent_values(self) -> None:
        stored = {OPEN: {"v": "set", "src": "declared"}, BOUNDED: {"v": "a", "src": "derived"}}
        out = rederive(stored, {"tap.test.open": "computed", "tap.test.bounded": "b"})
        assert out[OPEN] == {"v": "set", "src": "declared"}
        assert out[BOUNDED] == {"v": "b", "src": "derived"}
        assert rederive({}, {"tap.test.open": "computed"})[OPEN] == {"v": "computed", "src": "derived"}


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-3")
class TestThroughTheServiceLayer:
    def test_a_created_node_stores_its_defaults_as_default(self) -> None:
        from tap_grid.models import Dimension, Entity

        node = Dimension.objects.create(name="tap.test.stored")
        stored = Entity.objects.get(pk=node.entity_id).dimensions
        meta = "01a1d14c-d80b-725d-8002-eb0b3e272f1d"  # tap.meta, core's seed
        assert stored == {meta: {"v": "dimension", "src": "default"}}
