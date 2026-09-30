"""
Tests del intake de alertas: tsmonitor (refactor) + endpoint genérico de fuentes.
"""
import pytest
import models


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

    def test_alert_intake_imported_at_module_level(self):
        # ImportError de alert_intake debe fallar al arrancar, nunca 500 por request
        import services.vod_service as vs
        assert callable(vs.handle_tsmonitor_style_alert)
        assert issubclass(vs.ChannelNotFound, Exception)

    def test_tsmonitor_unknown_channel_returns_error_dict(self, client):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": 999999, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"status", "message"}
        assert data["status"] == "error"
        assert "no encontrado" in data["message"]

    def test_tsmonitor_happy_path(self, client, canal):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"status", "message", "rule", "action_taken"}
        assert data["status"] == "success"
        assert data["action_taken"] is False  # sin reglas configuradas


class TestGenericSourceEndpoint:

    def test_unknown_slug_404(self, client):
        resp = client.post("/api/fuentes/nope/alertas",
                           json={"num_canal": 1, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 404
        assert resp.json()["error"] == "Fuente no registrada"

    def test_wrong_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "wrong"},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "Token de fuente inválido"

    def test_missing_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "Token de fuente inválido"

    def test_disabled_source_403(self, client, db_session, fuente):
        fuente.enabled = False
        db_session.commit()
        # token inválido: deshabilitada debe ganar (orden: enabled antes que token)
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "wrong"},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "Fuente deshabilitada"

    def test_channel_not_found_404(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": 424242, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "down"})
        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["error"]

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

    def test_event_type_truncated_to_50_for_long_slug(self, client, db_session, canal):
        # slug de 50 chars → event_type calculado de 60 chars; debe truncarse a 50
        slug = "a" * 50
        db_session.add(models.AlertSource(slug=slug, name="Fuente Larga",
                                          token="t" * 32, enabled=True))
        db_session.commit()
        resp = client.post(f"/api/fuentes/{slug}/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        log = db_session.query(models.MonitorLog).filter(
            models.MonitorLog.event_type.startswith("EXT_ALERT_")).first()
        assert log is not None
        assert log.event_type == ("EXT_ALERT_" + slug.upper())[:50]
        assert len(log.event_type) <= 50
