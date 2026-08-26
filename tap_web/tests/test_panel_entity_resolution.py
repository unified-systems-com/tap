"""Tests for the canonical entity-resolution helper.

Covers req-web-panel-entity-resolution-tests-2 — verify the two lookup
helpers issue the right Gryphon shapes and unpack the results correctly,
and verify the orchestrator's URL-wins / fallback-fires / error-state
dispatch per the spec.

No Django/DB setup required — tests mock the Gryphon executor at its
source path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tap_web.panels.entity_resolution import (
    _lookup_by_entity_id,
    _run_fallback_query,
    resolve_entity,
)


class FakePanel:
    """Minimal duck-typed panel for tests — just carries a config dict."""

    def __init__(self, config: dict[str, Any]):
        self.config = config


def _fake_request(get_params: dict[str, str] | None = None) -> Any:
    """Minimal request stand-in with a GET dict."""
    request = MagicMock()
    request.GET = get_params or {}
    return request


class TestLookupByEntityId:
    """`_lookup_by_entity_id` issues a labelless MATCH and unpacks the envelope."""

    @pytest.mark.spec("req-web-panel-entity-resolution-tests-2")

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_issues_labelless_match(self, mock_exec):
        mock_exec.return_value = {"nodes": [], "edges": []}
        _lookup_by_entity_id("abc-123")
        called_query = mock_exec.call_args[0][0]
        called_inputs = mock_exec.call_args[0][1]
        assert "MATCH (n)" in called_query
        assert "n.entity_id = $entity_id" in called_query
        assert called_inputs == {"entity_id": "abc-123"}
        # Spec requires extended layer for rich envelope.
        assert mock_exec.call_args.kwargs.get("layer") == "extended"

    @pytest.mark.spec("req-web-panel-entity-resolution-helper-3")

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_returns_node_when_envelope_populated(self, mock_exec):
        node = {"entity_id": "abc-123", "name": "thing", "data": {}}
        mock_exec.return_value = {"nodes": [node], "edges": []}
        result = _lookup_by_entity_id("abc-123")
        assert result is node

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_returns_none_when_envelope_empty(self, mock_exec):
        mock_exec.return_value = {"nodes": [], "edges": []}
        result = _lookup_by_entity_id("abc-123")
        assert result is None


class TestRunFallbackQuery:
    """`_run_fallback_query` runs the panel-supplied query verbatim and returns (nodes, count)."""

    @pytest.mark.spec("req-web-panel-entity-resolution-helper-2")

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_runs_query_verbatim(self, mock_exec):
        mock_exec.return_value = {"nodes": [], "edges": []}
        query = "MATCH (a:compliance_artifact) WHERE a.data.kind = 'oscal_ssp' ORDER BY a.data.fetched_at DESC LIMIT 1"
        _run_fallback_query(query)
        called_query = mock_exec.call_args[0][0]
        assert called_query == query
        assert mock_exec.call_args.kwargs.get("layer") == "extended"

    @pytest.mark.spec("req-web-panel-entity-resolution-helper-3")

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_returns_nodes_and_count(self, mock_exec):
        nodes = [
            {"entity_id": "a", "name": "1"},
            {"entity_id": "b", "name": "2"},
        ]
        mock_exec.return_value = {"nodes": nodes, "edges": []}
        result_nodes, count = _run_fallback_query("MATCH (n:t) LIMIT 2")
        assert result_nodes == nodes
        assert count == 2

    @patch("tap_grid.gryphon.executor.execute_gryphon_raw")
    def test_empty_envelope_returns_zero(self, mock_exec):
        mock_exec.return_value = {"nodes": [], "edges": []}
        nodes, count = _run_fallback_query("MATCH (n:t) WHERE n.data.k = 'x' LIMIT 1")
        assert nodes == []
        assert count == 0


class TestResolveEntitySingleEntity:
    """Single-entity panel — `entity_id_var` + `fallback.{query, description}`."""

    SAMPLE_NODE = {"entity_id": "node-1", "name": "the thing"}
    SAMPLE_QUERY = "MATCH (a:t) WHERE a.data.kind = 'x' ORDER BY a.data.ts DESC LIMIT 1"

    @pytest.mark.spec("req-web-panel-entity-resolution-order-1")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_url_deep_link_wins(self, mock_fallback, mock_lookup):
        mock_lookup.return_value = self.SAMPLE_NODE
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": self.SAMPLE_QUERY, "description": "Latest oscal_ssp"},
            }
        )
        request = _fake_request({"ssp_eid": "node-1"})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert result.ok
        assert result.entity_id == "node-1"
        assert result.node is self.SAMPLE_NODE
        assert result.used_fallback is False
        # Fallback path must not have been touched.
        mock_fallback.assert_not_called()

    @pytest.mark.spec("req-web-panel-entity-resolution-order-2")

    @pytest.mark.spec("req-web-panel-entity-resolution-helper-4")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_fallback_fires_when_url_var_empty(self, mock_fallback, mock_lookup):
        mock_fallback.return_value = ([self.SAMPLE_NODE], 1)
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": self.SAMPLE_QUERY, "description": "Latest oscal_ssp"},
            }
        )
        request = _fake_request({})  # no URL var
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert result.ok
        assert result.entity_id == "node-1"
        assert result.used_fallback is True
        assert result.fallback_description == "Latest oscal_ssp"
        assert result.fallback_count == 1
        # Deep-link path must not have been touched.
        mock_lookup.assert_not_called()

    @pytest.mark.spec("req-web-panel-entity-resolution-config-2")

    @pytest.mark.spec("req-web-panel-entity-resolution-errors-2")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    def test_no_url_var_no_fallback_returns_source_error(self, mock_lookup):
        panel = FakePanel({"entity_id_var": "ssp_eid"})
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "No entity specified" in result.error
        assert "ssp_eid" in result.error
        mock_lookup.assert_not_called()

    @pytest.mark.spec("req-web-panel-entity-resolution-order-3")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    def test_url_supplied_but_entity_missing_returns_load_error(self, mock_lookup):
        mock_lookup.return_value = None
        panel = FakePanel({"entity_id_var": "ssp_eid"})
        request = _fake_request({"ssp_eid": "missing-id"})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "Entity not found" in result.error
        assert "missing-id" in result.error

    @pytest.mark.spec("req-web-panel-entity-resolution-empty-state-1")

    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_fallback_zero_rows_returns_empty_error(self, mock_fallback):
        mock_fallback.return_value = ([], 0)
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": self.SAMPLE_QUERY, "description": "Latest oscal_ssp"},
            }
        )
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "no entities yet" in result.error
        assert "Latest oscal_ssp" in result.error
        assert result.fallback_count == 0

    @pytest.mark.spec("req-web-panel-entity-resolution-empty-state-3")

    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_fallback_ambiguous_returns_ambiguous_error(self, mock_fallback):
        mock_fallback.return_value = ([{"entity_id": "a"}, {"entity_id": "b"}], 2)
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": "MATCH (n:t) LIMIT 2", "description": "Unique user 'george'"},
            }
        )
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "ambiguous" in result.error.lower()
        assert "2" in result.error
        assert "Unique user 'george'" in result.error
        assert result.fallback_count == 2

    @pytest.mark.spec("req-web-panel-entity-resolution-config-3")

    def test_partial_fallback_query_without_description_is_config_error(self):
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": self.SAMPLE_QUERY},  # no description
            }
        )
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "misconfigured" in result.error.lower()
        assert "description" in result.error.lower()

    @pytest.mark.spec("req-web-panel-entity-resolution-config-1")

    def test_default_var_name_used_when_config_omits_entity_id_var(self):
        panel = FakePanel({})  # no entity_id_var
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="my_default")
        assert not result.ok
        assert "my_default" in result.error

    @pytest.mark.spec("req-web-panel-entity-resolution-errors-1")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    def test_transient_lookup_exception_surfaces_polished_error(self, mock_lookup):
        mock_lookup.side_effect = RuntimeError("connection dropped")
        panel = FakePanel({"entity_id_var": "ssp_eid"})
        request = _fake_request({"ssp_eid": "node-1"})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "Entity lookup failed" in result.error
        assert "connection dropped" in result.error

    @pytest.mark.spec("req-web-panel-entity-resolution-errors-1")

    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_transient_fallback_exception_surfaces_polished_error(self, mock_fallback):
        mock_fallback.side_effect = RuntimeError("gryphon parse error")
        panel = FakePanel(
            {
                "entity_id_var": "ssp_eid",
                "fallback": {"query": self.SAMPLE_QUERY, "description": "Latest oscal_ssp"},
            }
        )
        request = _fake_request({})
        result = resolve_entity(panel, request, default_var_name="default_eid")
        assert not result.ok
        assert "Fallback query failed" in result.error


class TestResolveEntityMultiEntity:
    """Multi-entity panel — per-role config keys."""

    SAMPLE_NODE = {"entity_id": "ssp-1", "name": "SSP"}
    SSP_QUERY = "MATCH (a:compliance_artifact) WHERE a.data.kind = 'oscal_ssp' ORDER BY a.data.fetched_at DESC LIMIT 1"
    POAM_QUERY = (
        "MATCH (a:compliance_artifact) WHERE a.data.kind = 'oscal_poam' ORDER BY a.data.fetched_at DESC LIMIT 1"
    )

    @pytest.mark.spec("req-web-panel-entity-resolution-multi-1")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    @patch("tap_web.panels.entity_resolution._run_fallback_query")
    def test_role_reads_role_prefixed_keys(self, mock_fallback, mock_lookup):
        mock_fallback.return_value = ([self.SAMPLE_NODE], 1)
        panel = FakePanel(
            {
                "ssp_entity_id_var": "ssp_eid",
                "poam_entity_id_var": "poam_eid",
                "fallback": {
                    "ssp": {"query": self.SSP_QUERY, "description": "Latest oscal_ssp"},
                    "poam": {"query": self.POAM_QUERY, "description": "Latest oscal_poam"},
                },
            }
        )
        request = _fake_request({})
        result = resolve_entity(panel, request, role="ssp", default_var_name="ssp_default")
        assert result.ok
        assert result.var_name == "ssp_eid"
        assert result.fallback_description == "Latest oscal_ssp"
        # The SSP query was used (not POAM).
        called_query = mock_fallback.call_args[0][0]
        assert called_query == self.SSP_QUERY
        mock_lookup.assert_not_called()

    @pytest.mark.spec("req-web-panel-entity-resolution-multi-1")

    @patch("tap_web.panels.entity_resolution._lookup_by_entity_id")
    def test_role_reads_role_prefixed_url_var(self, mock_lookup):
        mock_lookup.return_value = self.SAMPLE_NODE
        panel = FakePanel(
            {
                "ssp_entity_id_var": "ssp_eid",
                "poam_entity_id_var": "poam_eid",
            }
        )
        request = _fake_request({"ssp_eid": "ssp-1", "poam_eid": "poam-1"})
        result = resolve_entity(panel, request, role="poam", default_var_name="poam_default")
        # The poam URL var was read, not ssp's.
        assert result.entity_id == "poam-1"
        assert result.var_name == "poam_eid"
