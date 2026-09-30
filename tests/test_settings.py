"""
Tests para settings_service (app_settings clave-valor + API-key).
"""
import pytest
from fastapi import HTTPException
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
