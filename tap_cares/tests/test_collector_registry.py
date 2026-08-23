"""Tests for tap_cares CollectorConfig, CollectorBase, and collector_registry.

Covers:
  req-tap-cares-collector-config
  req-tap-cares-collector-module-class
  req-tap-cares-collector-registry
"""

import dataclasses
import uuid
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from tap_auth.errors import UnguardedOperation
from tap_cares.collectors import CollectorBase, CollectorConfig
from tap_cares.exceptions import (
    CollectorNotFoundError,
    InvalidCollectorRegistryKeyError,
)
from tap_cares.models import Collector
from tap_cares.registry import (
    NAMESPACE_COLLECTOR,
    _validate_collector_token,
    collector_registry,
    get_collector,
    reconcile_collector_nodes,
    register_collector,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_collector_registry_autouse(isolate_collector_registry):
    """Every test in this module manipulates the registry — isolate all of them
    (the shared fixture lives in tests/conftest.py)."""
    yield


def _make_collector_class(name: str = "Fake", module: str = "tap_cares.tests.fake_collector_module"):
    """Create a CollectorBase subclass with a controllable __module__."""

    class _Fake(CollectorBase):
        def run(self) -> None:
            return None

    _Fake.__name__ = name
    _Fake.__qualname__ = name
    _Fake.__module__ = module
    return _Fake


def _register(key, cls, **kwargs):
    """Test-only wrapper that supplies default name and description.

    register_collector requires name and description per
    req-tap-cares-collector-registration-3, but these registry-mechanics tests
    only care about the in-memory (ScopedRegistry) side. register_collector is
    read-only at runtime now (req-tap-plugin-load-v0-ready-readonly): it records the
    node descriptor but writes no grid node, so these tests need no DB. The on-grid
    node is materialized separately by reconcile_collector_nodes (see
    TestReconcileCollectorNodes).
    """
    # Production register_collector requires an explicit `scope` (identity must
    # not ride on cls.__module__ — req-tap-cares-collector-model-10). These
    # registry-mechanics tests control the scope via each fixture's __module__,
    # so the helper defaults scope to cls.__module__ for convenience; callers
    # can still override with scope=.
    return register_collector(
        key=key,
        cls=cls,
        scope=kwargs.pop("scope", cls.__module__),
        name=kwargs.pop("name", f"Test collector {key}"),
        description=kwargs.pop("description", "Fixture collector for registry tests."),
        **kwargs,
    )


def _make_config() -> CollectorConfig:
    return CollectorConfig(collector_entity_id=uuid4(), collection_job_entity_id=uuid4())


# ---------------------------------------------------------------------------
# CollectorConfig (req-tap-cares-collector-config)
# ---------------------------------------------------------------------------


class TestCollectorConfig:
    def test_construct_with_uuids(self):
        cid, jid = uuid4(), uuid4()
        cfg = CollectorConfig(collector_entity_id=cid, collection_job_entity_id=jid)
        assert cfg.collector_entity_id == cid
        assert cfg.collection_job_entity_id == jid

    def test_frozen_immutable(self):
        cfg = _make_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.collector_entity_id = uuid4()  # type: ignore[misc]

    def test_equality_by_value(self):
        cid, jid = uuid4(), uuid4()
        a = CollectorConfig(collector_entity_id=cid, collection_job_entity_id=jid)
        b = CollectorConfig(collector_entity_id=cid, collection_job_entity_id=jid)
        assert a == b
        assert hash(a) == hash(b)

    def test_json_safe_via_asdict(self):
        cfg = _make_config()
        d = dataclasses.asdict(cfg)
        assert set(d.keys()) == {"collector_entity_id", "collection_job_entity_id"}
        assert all(isinstance(v, UUID) for v in d.values())  # UUIDs are JSON-serializable as str.

    def test_v0_shape_is_two_uuids_only(self):
        # req-tap-cares-collector-config-6 — exactly these two fields, nothing else.
        fields = {f.name for f in dataclasses.fields(CollectorConfig)}
        assert fields == {"collector_entity_id", "collection_job_entity_id"}


# ---------------------------------------------------------------------------
# CollectorBase (req-tap-cares-collector-module-class)
# ---------------------------------------------------------------------------


class TestCollectorBase:
    def test_cannot_instantiate_abstract_base(self):
        with pytest.raises(TypeError, match="abstract"):
            CollectorBase(_make_config())  # type: ignore[abstract]

    def test_subclass_without_run_is_abstract(self):
        class Incomplete(CollectorBase):
            pass

        with pytest.raises(TypeError, match="abstract"):
            Incomplete(_make_config())  # type: ignore[abstract]

    def test_subclass_with_run_instantiates(self):
        Cls = _make_collector_class()
        cfg = _make_config()
        inst = Cls(cfg)
        assert inst.config is cfg

    def test_run_returns_none(self):
        Cls = _make_collector_class()
        inst = Cls(_make_config())
        assert inst.run() is None


# ---------------------------------------------------------------------------
# Validator helper (req-tap-cares-collector-registry-9, -10)
# ---------------------------------------------------------------------------


class TestValidateCollectorToken:
    @pytest.mark.parametrize(
        "value",
        ["a", "Z9", "alpha-beta", "alpha_beta", "a.b.c", "plugins.fedramp_20x_ksi"],
    )
    def test_valid_tokens(self, value):
        _validate_collector_token(value)  # does not raise

    @pytest.mark.parametrize(
        "value",
        ["", "-leading-dash", ".leading-dot", "_leading-underscore", "has space", "has:colon", "has/slash"],
    )
    def test_invalid_tokens(self, value):
        with pytest.raises(InvalidCollectorRegistryKeyError):
            _validate_collector_token(value)

    def test_non_string_rejected(self):
        with pytest.raises(InvalidCollectorRegistryKeyError):
            _validate_collector_token(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# register_collector (req-tap-cares-collector-registry, -module-class-6)
# ---------------------------------------------------------------------------


class TestRegisterCollector:
    def test_register_and_get_round_trip(self):
        Cls = _make_collector_class(module="my.plugin")
        _register("alpha", Cls)
        assert get_collector("my.plugin:alpha") is Cls

    def test_scope_is_required(self):
        # register_collector must NOT infer scope from cls.__module__: a
        # collector's derived entity id is a durable cross-referenced grid key,
        # so identity is an explicit declaration (req-tap-cares-collector-model-10).
        Cls = _make_collector_class(module="some.plugin.module")
        with pytest.raises(TypeError):
            register_collector(  # scope omitted → required keyword-only arg
                key="noscope",
                cls=Cls,
                name="No scope",
                description="Should fail: scope is mandatory.",
            )

    def test_scope_can_be_overridden(self):
        Cls = _make_collector_class(module="default.scope")
        _register("ovr", Cls, scope="explicit.scope")
        assert get_collector("explicit.scope:ovr") is Cls

    def test_non_class_rejected(self):
        def not_a_class():
            return None

        with pytest.raises(ImproperlyConfigured, match="CollectorBase"):
            _register("bad", not_a_class, scope="my.scope")  # type: ignore[arg-type]

    def test_non_collector_base_subclass_rejected(self):
        class NotACollector:
            pass

        with pytest.raises(ImproperlyConfigured, match="CollectorBase"):
            _register("bad", NotACollector, scope="my.scope")  # type: ignore[arg-type]

    def test_bad_key_format_rejected(self):
        Cls = _make_collector_class()
        with pytest.raises(InvalidCollectorRegistryKeyError):
            _register("bad key", Cls, scope="ok.scope")

    def test_bad_scope_format_rejected(self):
        Cls = _make_collector_class()
        with pytest.raises(InvalidCollectorRegistryKeyError):
            _register("ok", Cls, scope="bad scope")

    def test_duplicate_registration_raises(self):
        Cls = _make_collector_class(module="dup.scope")
        _register("dup", Cls)
        with pytest.raises(ImproperlyConfigured, match="already registered"):
            _register("dup", Cls)

    def test_different_scopes_same_key_coexist(self):
        A = _make_collector_class(name="A", module="scope.a")
        B = _make_collector_class(name="B", module="scope.b")
        _register("shared", A)
        _register("shared", B)
        assert get_collector("scope.a:shared") is A
        assert get_collector("scope.b:shared") is B

    def test_bad_format_register_leaves_registry_unchanged(self):
        Cls = _make_collector_class()
        try:
            _register("bad key", Cls, scope="ok.scope")
        except InvalidCollectorRegistryKeyError:
            pass
        assert collector_registry.keys() == []


# ---------------------------------------------------------------------------
# reconcile_collector_nodes — the deferred grid-side half of dual existence
# (req-tap-plugin-load-v0-ready-readonly, req-tap-auth-actor-model)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReconcileCollectorNodes:
    """register_collector is read-only; reconcile_collector_nodes materializes the
    grid node(s) in one batch under the caller-bound (program) actor."""

    def test_register_writes_no_grid_node(self):
        # ready-readonly: registration records the descriptor, never touches the grid.
        cls = _make_collector_class(module="recon.scope")
        _register("readonly", cls)
        entity_id = uuid.uuid5(NAMESPACE_COLLECTOR, "recon.scope:readonly")
        assert not Collector.objects.filter(entity_id=entity_id).exists()

    def test_reconcile_creates_then_is_idempotent(self):
        cls = _make_collector_class(module="recon.scope")
        _register("happy", cls, name="Recon Happy", description="d1")

        first = reconcile_collector_nodes()
        assert first["created"] == 1
        node = Collector.objects.get(entity_id=uuid.uuid5(NAMESPACE_COLLECTOR, "recon.scope:happy"))
        assert node.name == "Recon Happy"

        # Re-apply converges: nothing new to write.
        second = reconcile_collector_nodes()
        assert second == {"created": 0, "updated": 0, "unchanged": 1}

    def test_reconcile_patches_drifted_descriptor(self):
        cls = _make_collector_class(module="recon.scope")
        _register("drift", cls, name="Old Name", description="old")
        reconcile_collector_nodes()

        # Re-register the same key with a new descriptor (overwrites the metadata).
        collector_registry._reset_for_testing()
        _register("drift", cls, name="New Name", description="new")

        summary = reconcile_collector_nodes()
        assert summary["updated"] == 1
        node = Collector.objects.get(entity_id=uuid.uuid5(NAMESPACE_COLLECTOR, "recon.scope:drift"))
        assert node.name == "New Name"
        assert node.description == "new"

    def test_reconcile_under_human_actor_is_refused(self):
        # The batch writes INTERNAL_ONLY nodes via the bypass — a program-actor-only
        # door. A human reconcile is refused even holding BOTH the cares.reconcile_collectors
        # gate capability AND grid.write — so it passes the capability gate and the write
        # backstop, and it is the program-actor guard specifically that fires:
        # belt-and-suspenders defense-in-depth (the gate + the program-actor door).
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType

        from tap_auth import capabilities as caps
        from tap_auth.models import Capability
        from tap_grid.caller_context import CallerContext, set_caller_context

        cls = _make_collector_class(module="recon.scope")
        _register("human", cls)
        content_type = ContentType.objects.get_for_model(Capability)
        group = Group.objects.create(name="recon-human-writers")
        for capability in ("grid.write", "cares.reconcile_collectors"):
            group.permissions.add(
                Permission.objects.get(content_type=content_type, codename=caps.codename_for(capability))
            )
        human = User.objects.create_user(username="reconciler", password="x")  # user_kind defaults to human
        human.groups.add(group)
        set_caller_context(CallerContext(user=human))
        with pytest.raises(UnguardedOperation):
            reconcile_collector_nodes()

    def test_reconcile_missing_descriptor_fails_loud(self):
        # A runner present in collector_registry with no recorded descriptor is an
        # internal-consistency violation (register_collector records both halves
        # together). Boot materializes nodes through this reconcile, so it must fail
        # loud — never silently skip the node (req-tap-cares-collector-registration-9).
        from tap_cares.registry import _COLLECTOR_NODE_METADATA

        cls = _make_collector_class(module="recon.scope")
        _register("orphan", cls)
        _COLLECTOR_NODE_METADATA.pop("recon.scope:orphan")

        with pytest.raises(ImproperlyConfigured, match="no node descriptor"):
            reconcile_collector_nodes()


# ---------------------------------------------------------------------------
# get_collector (req-tap-cares-collector-registry, exceptions)
# ---------------------------------------------------------------------------


class TestGetCollector:
    def test_missing_key_raises_collector_not_found(self):
        with pytest.raises(CollectorNotFoundError, match="missing"):
            get_collector("some.scope:missing")

    def test_error_message_lists_registered_keys(self):
        _register("present", _make_collector_class(module="some.scope"))
        with pytest.raises(CollectorNotFoundError) as exc_info:
            get_collector("some.scope:absent")
        assert "some.scope:present" in str(exc_info.value)

    def test_malformed_key_raises_invalid_token(self):
        with pytest.raises(InvalidCollectorRegistryKeyError):
            get_collector("bad scope:key")
        with pytest.raises(InvalidCollectorRegistryKeyError):
            get_collector("ok.scope:bad key")


# ---------------------------------------------------------------------------
# Registry visibility (req-tap-cares-collector-registry-2, meta-registry surface)
# ---------------------------------------------------------------------------


class TestRegistryVisibility:
    def test_collector_registry_in_meta_registry(self):
        from tap.registry import meta_registry

        assert "collector" in meta_registry

    def test_collector_registry_separate_from_search(self):
        from tap_grid.registry import search_runner_registry

        assert collector_registry is not search_runner_registry
