"""
Tests del intake de alertas: tsmonitor (refactor) + endpoint genérico de fuentes.
"""
import pytest
import models
from services.settings_service import save_section


@pytest.fixture(name="canal")
def fixture_canal(db_session):
    ch = models.Channel(channel_name="Canal Uno", unique_id="777")
    db_session.add(ch)
    db_session.commit()
    return ch


@pytest.fixture(name="fuente")
def fixture_fuente(db_session):
    src = models.AlertSource(slug="mi-fuente", name="Mi Fuente", token="t" * 32, enabled=True)
    db_session.add(src)
    db_session.commit()
    return src


class TestTsmonitorPreserved:

    def test_tsmonitor_unknown_channel_returns_error_dict(self, client):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": 999999, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "no encontrado" in data["message"]

    def test_tsmonitor_happy_path(self, client, canal):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["action_taken"] is False  # sin reglas configuradas


class TestGenericSourceEndpoint:

    def test_unknown_slug_404(self, client):
        resp = client.post("/api/fuentes/nope/alertas",
                           json={"num_canal": 1, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 404

    def test_wrong_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "wrong"},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_missing_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_disabled_source_403(self, client, db_session, fuente):
        fuente.enabled = False
        db_session.commit()
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_channel_not_found_404(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": 424242, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "down"})
        assert resp.status_code == 404

    def test_happy_path_enters_rule_engine(self, client, db_session, canal, fuente):
        rule = models.AlertRule(name="Regla Mi Fuente", source="mi-fuente",
                                alert_type="down", action="notify_only",
                                enabled=True, priority=100, cooldown_seconds=0)
        db_session.add(rule)
        db_session.commit()
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "dead"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["rule"] is not None
        assert data["rule"]["name"] == "Regla Mi Fuente"
        # MonitorLog con event_type de la fuente
        log = db_session.query(models.MonitorLog).filter(
            models.MonitorLog.event_type == "EXT_ALERT_MI-FUENTE").first()
        assert log is not None
