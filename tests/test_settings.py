"""
Tests para settings_service (app_settings clave-valor + API-key).
"""
import pytest
from fastapi import HTTPException
import models
from core.config import AGENT_API_KEY
from services.settings_service import get_setting, get_section, save_section, get_api_key


class TestSettingsService:

    def test_get_setting_fallback_when_missing(self, db_session):
        assert get_setting(db_session, "telegram", "bot_token", default="fallback") == "fallback"

    def test_save_and_get_setting(self, db_session):
        save_section(db_session, "telegram", {"bot_token": "XYZ", "enabled": "1"})
        assert get_setting(db_session, "telegram", "bot_token") == "XYZ"
        assert get_setting(db_session, "telegram", "enabled") == "1"

    def test_get_section_merges_defaults(self, db_session):
        save_section(db_session, "telegram", {"bot_token": "XYZ"})
        sec = get_section(db_session, "telegram", defaults={"bot_token": "", "enabled": "0"})
        assert sec["bot_token"] == "XYZ"
        assert sec["enabled"] == "0"

    def test_get_api_key_fallback_when_no_row(self, db_session):
        assert get_api_key(db_session) == AGENT_API_KEY

    def test_get_api_key_reads_db(self, db_session):
        save_section(db_session, "security", {"api_key": "nueva_key_1234567890"})
        assert get_api_key(db_session) == "nueva_key_1234567890"

    def test_get_api_key_empty_value_falls_back(self, db_session):
        save_section(db_session, "security", {"api_key": ""})
        assert get_api_key(db_session) == AGENT_API_KEY


class TestApiKeyValidation:

    def test_internal_verify_accepts_db_key(self, db_session):
        from routers.internal import verify_api_key
        save_section(db_session, "security", {"api_key": "k" * 32})
        verify_api_key("k" * 32, db_session)  # no levanta excepción

    def test_internal_verify_rejects_wrong_key(self, db_session):
        from routers.internal import verify_api_key
        save_section(db_session, "security", {"api_key": "k" * 32})
        with pytest.raises(HTTPException) as exc:
            verify_api_key("wrong", db_session)
        assert exc.value.status_code == 401

    def test_internal_verify_fallback_default_key(self, db_session):
        from routers.internal import verify_api_key
        verify_api_key(AGENT_API_KEY, db_session)  # sin fila en BD → default pasa

    def test_cms_token_rejects_wrong_key(self, db_session):
        from utils.helpers import verify_cms_token
        save_section(db_session, "security", {"api_key": "otra_key_1234567890"})
        with pytest.raises(HTTPException) as exc:
            verify_cms_token("wrong", db_session)
        assert exc.value.status_code == 403

    def test_cms_token_accepts_db_key(self, db_session):
        from utils.helpers import verify_cms_token
        save_section(db_session, "security", {"api_key": "otra_key_1234567890"})
        verify_cms_token("otra_key_1234567890", db_session)


class TestApiKeyOutgoing:

    def test_http_client_injects_current_key(self, monkeypatch):
        import core.http_client as hc
        monkeypatch.setattr(hc, "get_api_key", lambda: "clave_nueva_desde_bd")
        client = hc.create_sync_client()
        try:
            assert client.headers["X-API-Key"] == "clave_nueva_desde_bd"
        finally:
            client.close()

    def test_async_client_injects_current_key(self, monkeypatch):
        import core.http_client as hc
        monkeypatch.setattr(hc, "get_api_key", lambda: "otra_clave_bd")
        client = hc.create_async_client()
        try:
            assert client.headers["X-API-Key"] == "otra_clave_bd"
        finally:
            pass  # cierre async manejado por httpx


class TestNotificationToggles:

    def test_telegram_disabled_does_not_send(self, db_session, monkeypatch):
        import monitor.alerts as ma
        calls = []
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "post", lambda *a, **k: calls.append(a) or True)
        ma.notify_telegram("hola")
        assert calls == []

    def test_telegram_enabled_sends_with_bd_params(self, db_session, monkeypatch):
        import monitor.alerts as ma
        save_section(db_session, "telegram", {"enabled": "1", "bot_token": "TOK123", "chat_id": "42"})
        calls = []
        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return True
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "post", fake_post)
        ma.notify_telegram("hola")
        assert len(calls) == 1
        assert "TOK123" in calls[0][0]
        assert calls[0][1]["json"]["chat_id"] == "42"

    def test_cms_disabled_does_not_send(self, db_session, monkeypatch):
        import monitor.alerts as ma
        ch = models.Channel(channel_name="Canal Test", unique_id="991")
        db_session.add(ch)
        db_session.commit()
        save_section(db_session, "cms", {"enabled": "0", "webhook_url": "https://x/cl"})
        posts = []
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, **kw): posts.append(url)
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "Client", lambda **kw: FakeClient())
        ma.notify_cms_channel_status(ch.id, "error", "prueba")
        assert posts == []

    def test_cms_enabled_uses_bd_webhook(self, db_session, monkeypatch):
        import monitor.alerts as ma
        ch = models.Channel(channel_name="Canal Test 2", unique_id="992")
        db_session.add(ch)
        db_session.commit()
        save_section(db_session, "cms", {"enabled": "1", "webhook_url": "https://cms.nuevo/webhook"})
        posts = []
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, **kw): posts.append(url)
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "Client", lambda **kw: FakeClient())
        ma.notify_cms_channel_status(ch.id, "error", "prueba")
        assert posts == ["https://cms.nuevo/webhook"]


class TestSettingsAPI:

    def test_api_settings_requires_auth(self, client):
        # El handler global convierte 401 en redirect 303 a /login (patrón del repo)
        resp = client.get("/api/settings", allow_redirects=False)
        assert resp.status_code in (401, 303)

    def test_api_settings_forbidden_for_operator(self, operator_client):
        assert operator_client.get("/api/settings").status_code == 403

    def test_put_telegram_persists_for_admin(self, admin_client, db_session):
        resp = admin_client.put("/api/settings/telegram",
                                json={"values": {"enabled": "1", "bot_token": "ABC", "chat_id": "7"}})
        assert resp.status_code == 200
        assert get_setting(db_session, "telegram", "bot_token") == "ABC"
        got = admin_client.get("/api/settings/telegram").json()
        assert got["bot_token"] == "ABC"

    def test_put_rejects_unknown_key(self, admin_client):
        resp = admin_client.put("/api/settings/telegram", json={"values": {"hacker": "x"}})
        assert resp.status_code == 400

    def test_put_rejects_unknown_section(self, admin_client):
        assert admin_client.put("/api/settings/nope", json={"values": {"a": "b"}}).status_code == 404

    def test_put_security_short_key_rejected(self, admin_client):
        resp = admin_client.put("/api/settings/security", json={"values": {"api_key": "corto"}})
        assert resp.status_code == 400

    def test_put_email_invalid_auth_mode(self, admin_client):
        resp = admin_client.put("/api/settings/email", json={"values": {"auth_mode": "pigeon"}})
        assert resp.status_code == 400

    def test_checkbox_normalization(self, admin_client, db_session):
        admin_client.put("/api/settings/telegram", json={"values": {"enabled": True}})
        assert get_setting(db_session, "telegram", "enabled") == "1"

    def test_email_test_disabled_returns_error(self, admin_client):
        resp = admin_client.post("/api/settings/email/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


class TestAlertSourcesAPI:

    def test_create_generates_token(self, admin_client, db_session):
        resp = admin_client.post("/api/alert-sources", json={"name": "Mi Fuente"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "mi-fuente"
        assert len(data["token"]) == 32

    def test_create_duplicate_slug_conflict(self, admin_client):
        admin_client.post("/api/alert-sources", json={"name": "Otra"})
        resp = admin_client.post("/api/alert-sources", json={"name": "otra!"})
        assert resp.status_code == 409

    def test_sources_require_admin(self, operator_client):
        assert operator_client.get("/api/alert-sources").status_code == 403

    def test_regenerate_changes_token(self, admin_client):
        created = admin_client.post("/api/alert-sources", json={"name": "Regen"}).json()
        resp = admin_client.post(f"/api/alert-sources/{created['id']}/regenerate-token")
        assert resp.status_code == 200
        assert resp.json()["token"] != created["token"]

    def test_update_and_delete(self, admin_client):
        created = admin_client.post("/api/alert-sources", json={"name": "Borrar"}).json()
        resp = admin_client.put(f"/api/alert-sources/{created['id']}",
                                json={"enabled": False, "description": "d"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        resp = admin_client.delete(f"/api/alert-sources/{created['id']}")
        assert resp.status_code == 200
        assert admin_client.get("/api/alert-sources").json() == [] or \
            all(s["id"] != created["id"] for s in admin_client.get("/api/alert-sources").json())
