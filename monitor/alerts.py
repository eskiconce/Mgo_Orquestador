"""
Monitor — Alerts module.
CMS notifications and Telegram alerts (toggles y parámetros desde app_settings).
"""
import httpx
import logging
from datetime import datetime
from sqlalchemy.orm import Session

import models
from core.config import CMS_REAL_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import SessionLocal
from services.settings_service import get_setting

logger = logging.getLogger(__name__)


def notify_telegram(message):
    """Envía mensaje a Telegram si telegram.enabled=1 en app_settings."""
    db = SessionLocal()
    try:
        if get_setting(db, "telegram", "enabled", "0") != "1":
            return
        token = get_setting(db, "telegram", "bot_token", "") or TELEGRAM_BOT_TOKEN
        chat_id = get_setting(db, "telegram", "chat_id", "") or TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass
    finally:
        db.close()


def notify_cms_channel_status(channel_id, status_event, description):
    """Envía webhook al CMS si cms.enabled=1 en app_settings. Posee su propia sesión (Thread-Safe)."""
    db = SessionLocal()
    try:
        if get_setting(db, "cms", "enabled", "1") != "1":
            return
        channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
        if not channel:
            return

        payload = {
            "event": "channel_status",
            "canal": channel.ruta if channel.ruta else channel.channel_name.lower().replace(" ", "_"),
            "status": status_event,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }

        webhook = get_setting(db, "cms", "webhook_url", "") or CMS_REAL_WEBHOOK
        logger.info(f"Notificando al CMS evento '{status_event}' para el canal {payload['canal']}")
        with httpx.Client(timeout=5.0) as client:
            client.post(webhook, json=payload)

    except Exception as e:
        logger.error(f"Error enviando notificación de estado al CMS: {e}")
    finally:
        db.close()
