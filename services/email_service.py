"""
Email service — envío de correos por SMTP o Microsoft Graph OAuth (client_credentials).
Incluye envío de prueba desde /ui/settings. El envío en alertas llega en un issue futuro.
"""
import time
import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx

from core.logging_service import logger
from services.settings_service import SECTION_DEFAULTS, get_section

GRAPH_TOKEN_URL = "https://graph.microsoft.com/{tenant}/oauth2/v2.0/token"
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

_token_cache = {"token": None, "expires_at": 0.0}


def _graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = httpx.post(
        GRAPH_TOKEN_URL.format(tenant=tenant_id),
        data={"client_id": client_id, "client_secret": client_secret,
              "grant_type": "client_credentials", "scope": GRAPH_SCOPE},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + float(data.get("expires_in", 5400))
    return _token_cache["token"]


def _recipients(settings: dict) -> list:
    raw = settings.get("recipients") or settings.get("from_addr") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def _build_message(settings: dict, subject: str, body: str) -> MIMEText:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.get("from_addr") or settings.get("smtp_user") or "orquestador@mundogo.cl"
    msg["To"] = ", ".join(_recipients(settings))
    return msg


def _send_smtp(settings: dict, msg: MIMEText) -> None:
    host = settings.get("smtp_host")
    port = int(settings.get("smtp_port") or 587)
    use_tls = settings.get("smtp_tls", "1") == "1"
    user = settings.get("smtp_user") or ""
    password = settings.get("smtp_password") or ""
    if use_tls:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)


def _send_graph(settings: dict, msg: MIMEText) -> None:
    token = _graph_token(settings["graph_tenant_id"], settings["graph_client_id"],
                         settings["graph_client_secret"])
    payload = {
        "message": {
            "subject": msg["Subject"],
            "body": {"contentType": "Text", "content": msg.get_payload()},
            "toRecipients": [{"emailAddress": {"address": a}} for a in _recipients(settings)],
        },
        "saveToSentItems": "true",
    }
    resp = httpx.post(GRAPH_SEND_URL, json=payload,
                      headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()


def send_test_email(db) -> dict:
    """Envía correo de prueba con la configuración actual. Retorna {status, message}."""
    try:
        settings = get_section(db, "email", defaults=SECTION_DEFAULTS["email"])
        if settings.get("enabled") != "1":
            return {"status": "error", "message": "Correo deshabilitado — actívalo primero."}
        required = ["from_addr", "recipients"]
        if settings.get("auth_mode") == "graph":
            required += ["graph_tenant_id", "graph_client_id", "graph_client_secret"]
        else:
            required += ["smtp_host"]
        missing = [k for k in required if not settings.get(k)]
        if missing:
            return {"status": "error", "message": f"Faltan parámetros: {', '.join(missing)}"}
        if not _recipients(settings):
            return {"status": "error", "message": "Sin destinatarios válidos."}
        msg = _build_message(settings, "Prueba de conexión — Mgo_Orquestador",
                             "Este es un correo de prueba enviado desde el orquestador Mgo_Orquestador.")
        if settings.get("auth_mode") == "graph":
            _send_graph(settings, msg)
        else:
            _send_smtp(settings, msg)
        logger.info("Correo de prueba enviado correctamente")
        return {"status": "ok", "message": "Correo de prueba enviado correctamente."}
    except Exception as e:
        logger.error(f"Error en prueba de correo: {e}")
        return {"status": "error", "message": str(e)}
