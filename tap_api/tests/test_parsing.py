"""NUL-rejection at the API parse chokepoint (NulForbiddingParser).

PostgreSQL text fields cannot store U+0000, so a NUL riding any request into an
ORM write or filter detonates as a psycopg DataError 500 (authenticated api-fuzz
finding, 2026-08-10). The parser rejects it wholesale — body, query params, and
nested container keys/values — with a 400 before any view runs (ninja wraps all
parse_body exceptions into 400, so 400 is the uniform rejection status).
"""

import json

import pytest

NUL = chr(0)  # written via chr() — a literal escape would put a raw NUL byte in this file

# Carriers: a JSON body (the Gryphon execute endpoint: a top-level string and a nested `inputs`
# container) and a query string (the type catalog's `kind` filter). Both reach their views only
# through the API's one configured parser.
_GRYPHON = "/api/v1/gryphon/execute"
_QUERY = "MATCH (n:grid_fixtures__node) RETURN n"


@pytest.mark.django_db
class TestNulRejection:
    def test_nul_in_body_string_rejected(self, logged_in_client):
        """The original fuzz repro's shape: a NUL inside a top-level body string."""
        response = logged_in_client.post(
            _GRYPHON,
            data=json.dumps({"query": NUL + _QUERY}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_nul_in_query_param_rejected(self, logged_in_client):
        """%00 in a filter param would ride into a psycopg text bind the same way.
        The querydict path is not wrapped by ninja, so our message survives."""
        response = logged_in_client.get("/api/v1/entity-types/?kind=%00x")
        assert response.status_code == 400
        assert "NUL" in response.json()["detail"]

    def test_nul_nested_in_container_rejected(self, logged_in_client):
        """Recursion proof: a NUL buried in a nested dict (value AND key)."""
        payloads = (
            {"note": f"a{NUL}b"},
            {f"k{NUL}ey": "v"},
            {"deep": ["ok", {"x": NUL}]},
        )
        for inputs in payloads:
            response = logged_in_client.post(
                _GRYPHON,
                data=json.dumps({"query": _QUERY, "inputs": inputs}),
                content_type="application/json",
            )
            assert response.status_code == 400


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestNulFreeInput:
    def test_nul_free_input_unaffected(self, logged_in_client):
        """The control: the same carriers without a NUL pass the parser and their views answer."""
        response = logged_in_client.post(
            _GRYPHON,
            data=json.dumps({"query": _QUERY, "inputs": {}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert logged_in_client.get("/api/v1/entity-types/?kind=node").status_code == 200
