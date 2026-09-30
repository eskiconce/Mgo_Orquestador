"""
Settings service — parámetros de la plataforma en app_settings (clave-valor por sección).
Fuente única de verdad; fallback a defaults cuando la fila no existe.
"""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from core.config import AGENT_API_KEY

logger = logging.getLogger(__name__)

SECTION_DEFAULTS: Dict[str, Dict[str, str]] = {
    "telegram": {"enabled": "0", "bot_token": "", "chat_id": ""},
    "email": {
        "enabled": "0", "auth_mode": "smtp",
        "smtp_host": "", "smtp_port": "587", "smtp_tls": "1",
        "smtp_user": "", "smtp_password": "",
        "graph_tenant_id": "", "graph_client_id": "", "graph_client_secret": "",
        "from_addr": "", "recipients": "",
    },
    "cms": {"enabled": "1", "webhook_url": "https://core-dev.mundogo.cl/api/webhook-vod"},
    "security": {"api_key": AGENT_API_KEY},
}


def get_setting(db: Session, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
    from models import AppSetting
    row = db.query(AppSetting).filter(
        AppSetting.section == section, AppSetting.key == key
    ).first()
    if row is not None and row.value is not None:
        return row.value
    return default


def get_section(db: Session, section: str, defaults: Optional[dict] = None) -> dict:
    from models import AppSetting
    result = dict(defaults if defaults is not None else SECTION_DEFAULTS.get(section, {}))
    for row in db.query(AppSetting).filter(AppSetting.section == section).all():
        result[row.key] = row.value
    return result


def save_section(db: Session, section: str, values: dict) -> None:
    from models import AppSetting
    for key, value in values.items():
        row = db.query(AppSetting).filter(
            AppSetting.section == section, AppSetting.key == key
        ).first()
        if row is not None:
            row.value = value
        else:
            db.add(AppSetting(section=section, key=key, value=value))
    db.commit()


def get_api_key(db: Session = None) -> str:
    """API-key global desde BD. Si db es None usa SessionLocal propio.
    Fallback: valor de config.AGENT_API_KEY si la fila falta o hay error."""
    own_session = db is None
    if own_session:
        from database import SessionLocal
        db = SessionLocal()
    try:
        value = get_setting(db, "security", "api_key", default=AGENT_API_KEY)
        return value or AGENT_API_KEY
    except Exception as e:
        logger.warning(f"No se pudo leer security.api_key de BD, usando default: {e}")
        return AGENT_API_KEY
    finally:
        if own_session:
            db.close()
