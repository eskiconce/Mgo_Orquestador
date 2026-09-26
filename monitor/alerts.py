"""
Monitor — Alerts module.
CMS notifications and Telegram alerts.
"""
import httpx
import logging
from datetime import datetime
from sqlalchemy.orm import Session

import models
from core.config import CMS_REAL_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import SessionLocal

logger = logging.getLogger(__name__)


def notify_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


def notify_cms_channel_status(channel_id, status_event, description):
    """Envía webhook al CMS. Posee su propia sesión de BD (Thread-Safe)."""
    db = SessionLocal()
    try:
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

        logger.info(f"Notificando al CMS evento '{status_event}' para el canal {payload['canal']}")
        with httpx.Client(timeout=5.0) as client:
            client.post(CMS_REAL_WEBHOOK, json=payload)

    except Exception as e:
        logger.error(f"Error enviando notificación de estado al CMS: {e}")
    finally:
        db.close()
