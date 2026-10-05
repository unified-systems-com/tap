"""Tests for version endpoint and auth."""

import pytest


@pytest.mark.django_db
class TestVersionEndpoint:
    def test_version_info(self, client):
        response = client.get("/api/v1/")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1"
        assert data["latest"] is True


@pytest.mark.django_db
class TestUnversionedRedirect:
    def test_redirects_to_v1(self, client):
        response = client.get("/api/entity-types/", follow=False)
        assert response.status_code == 302
        assert response["Location"] == "/api/v1/entity-types/"


@pytest.mark.django_db
class TestAuthEnforced:
    def test_unauthenticated_rejected(self, client):
        response = client.get("/api/v1/entity-types/")
        assert response.status_code == 401
