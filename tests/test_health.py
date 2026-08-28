"""
Tests para el endpoint de salud y métricas.
"""
import pytest


class TestHealthEndpoint:
    """Tests para GET /api/health."""

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_returns_healthy_status(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "healthy"

    def test_health_returns_version(self, client):
        data = client.get("/api/health").json()
        assert "version" in data
        assert data["version"].startswith("v")

    def test_health_returns_uptime(self, client):
        data = client.get("/api/health").json()
        assert "uptime" in data
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_health_returns_database_status(self, client):
        data = client.get("/api/health").json()
        assert data["database"] == "connected"

    def test_health_returns_metrics(self, client):
        data = client.get("/api/health").json()
        assert "metrics" in data
        metrics = data["metrics"]
        assert "total_nodes" in metrics
        assert "online_nodes" in metrics
        assert "total_channels" in metrics
        assert "total_jobs" in metrics
        assert "running_jobs" in metrics
        assert "error_jobs" in metrics


class TestReadinessEndpoint:
    """Tests para GET /api/health/ready."""

    def test_ready_returns_200(self, client):
        resp = client.get("/api/health/ready")
        assert resp.status_code == 200

    def test_ready_returns_ready_true(self, client):
        data = client.get("/api/health/ready").json()
        assert data["ready"] is True


class TestMetricsEndpoint:
    """Tests para GET /api/metrics."""

    def test_metrics_returns_200(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200

    def test_metrics_has_jobs_section(self, client):
        data = client.get("/api/metrics").json()
        assert "jobs" in data
        assert "total" in data["jobs"]
        assert "by_status" in data["jobs"]
        assert "by_type" in data["jobs"]

    def test_metrics_has_nodes_section(self, client):
        data = client.get("/api/metrics").json()
        assert "nodes" in data
        assert "total" in data["nodes"]
        assert "by_type" in data["nodes"]

    def test_metrics_has_channels_section(self, client):
        data = client.get("/api/metrics").json()
        assert "channels" in data
        assert "total" in data["channels"]
