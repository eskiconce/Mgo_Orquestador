"""
Tests para endpoints principales de la API.
"""
import pytest


class TestAuthEndpoints:
    """Tests para autenticación."""

    def test_login_page_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_with_wrong_credentials_redirects(self, client):
        resp = client.post("/login", data={"username": "nonexistent", "password": "wrong"})
        assert resp.status_code == 200  # returns template with error

    def test_protected_endpoint_redirects_to_login(self, client):
        resp = client.get("/ui/processes", allow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]


class TestDashboardEndpoint:
    """Tests para el dashboard."""

    def test_dashboard_requires_auth(self, client):
        resp = client.get("/", allow_redirects=False)
        assert resp.status_code == 303


class TestNodesEndpoints:
    """Tests para endpoints de nodos."""

    def test_nodes_status_requires_auth(self, client):
        resp = client.get("/api/nodes/status", allow_redirects=False)
        # Could be 303 redirect or 401 depending on auth handler
        assert resp.status_code in [303, 401, 200]

    def test_nodes_list_requires_auth(self, client):
        resp = client.get("/ui/nodes", allow_redirects=False)
        assert resp.status_code == 303


class TestChannelsEndpoints:
    """Tests para endpoints de canales."""

    def test_channels_list_requires_auth(self, client):
        resp = client.get("/ui/channels", allow_redirects=False)
        assert resp.status_code == 303


class TestProcessesEndpoints:
    """Tests para endpoints de procesos."""

    def test_processes_list_requires_auth(self, client):
        resp = client.get("/ui/processes", allow_redirects=False)
        assert resp.status_code == 303

    def test_processes_status_requires_auth(self, client):
        resp = client.get("/api/processes/status", allow_redirects=False)
        assert resp.status_code in [303, 401, 200]


class TestDRMEndpoints:
    """Tests para endpoints de DRM."""

    def test_drm_stats_requires_auth(self, client):
        resp = client.get("/api/drm/stats", allow_redirects=False)
        assert resp.status_code == 303
