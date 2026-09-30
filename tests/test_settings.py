"""
Tests para settings_service (app_settings clave-valor + API-key).
"""
import pytest
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
