"""
Alert Intake — ingesta de alertas externas con payload estilo TSMonitor.
Compartido por el endpoint dedicado /api/alertas/tsmonitor y el
endpoint genérico /api/fuentes/{slug}/alertas.
"""
import httpx
import atexit
from datetime import datetime
from typing import Union

from sqlalchemy.orm import Session

import models
from core.logging_service import logger
from services.alert_normalizer import normalize_tsmonitor_alert
from services.alert_rule_engine import process_alert
from services.settings_service import get_api_key


class ChannelNotFound(Exception):
    """El canal indicado en la alerta no existe."""


_http = httpx.Client(
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
)
atexit.register(_http.close)


def handle_tsmonitor_style_alert(
    db: Session,
    source: str,
    reporter: str,
    event_type: str,
    num_canal: Union[int, str],
    fecha: str,
    hora: str,
    status: str,
) -> dict:
    """Canal → normaliza → MonitorLog → motor de reglas → acción en encoder → commit.

    Lanza ChannelNotFound si el canal no existe.
    Retorna {"status", "message", "rule", "action_taken"} (forma del endpoint tsmonitor actual).
    """
    # 1. Buscar el Canal — por unique_id con fallback a id
    channel = db.query(models.Channel).filter(
        models.Channel.unique_id == str(num_canal)
    ).first()

    if not channel:
        try:
            numeric_id = int(num_canal)
            channel = db.query(models.Channel).filter(
                models.Channel.id == numeric_id
            ).first()
        except (TypeError, ValueError):
            channel = None

    if not channel:
        raise ChannelNotFound(f"Canal {num_canal} no encontrado.")

    # 2. Normalizar alerta a formato interno
    normalized = normalize_tsmonitor_alert(
        num_canal=num_canal,
        status=status,
        fecha=fecha,
        hora=hora,
        channel_id=channel.id,
        source=source,
    )

    # 3. Registrar en monitor_logs
    alert_entry = models.MonitorLog(
        event_type=event_type,
        message=f"Alerta externa [{status}] para el canal {channel.channel_name}. Reportada por {reporter}.",
        node_id=None,
        timestamp=normalized.timestamp
    )
    db.add(alert_entry)
    db.flush()

    # 4. Procesar con motor de reglas
    result = process_alert(db, normalized)

    # 5. Si la regla indica ejecutar acción en encoder, hacerlo
    if result["action_taken"] and result["rule"]:
        rule_action = result["rule"]["action"]

        encoder_job = db.query(models.EncodingJob).join(models.Node).filter(
            models.EncodingJob.channel_id == channel.id,
            models.Node.tipo == 'Encoder'
        ).first()

        if encoder_job and rule_action in ["stop_encoder", "start_encoder", "restart_encoder"]:
            agent_ip = encoder_job.node.ip_address
            headers = {"X-API-Key": get_api_key(db)}
            prog_name = f"channel_{channel.channel_name}_{encoder_job.id}"

            try:
                if rule_action == "stop_encoder" and encoder_job.status in ["running", "starting"]:
                    url_stop = f"http://{agent_ip}:8000/jobs/control"
                    _http.post(url_stop, params={"action": "stop", "program_name": prog_name}, headers=headers, timeout=5)
                    encoder_job.status = "stopped"
                    encoder_job.auto_started = False
                    db.add(models.MonitorLog(
                        event_type="ENCODER_STOPPED",
                        message=f"Encoder de {channel.channel_name} detenido por regla: {result['rule']['name']}",
                        node_id=encoder_job.node_id,
                        timestamp=normalized.timestamp
                    ))
                elif rule_action == "start_encoder" and encoder_job.status in ["stopped", "error"]:
                    url_start = f"http://{agent_ip}:8000/jobs/create"
                    payload_start = {
                        "job_id": encoder_job.id,
                        "channel_name": channel.channel_name,
                        "command": encoder_job.command_compress,
                        "autostart": True
                    }
                    _http.post(url_start, json=payload_start, headers=headers, timeout=10)
                    encoder_job.status = "starting"
                    db.add(models.MonitorLog(
                        event_type="ENCODER_STARTED",
                        message=f"Encoder de {channel.channel_name} iniciado por regla: {result['rule']['name']}",
                        node_id=encoder_job.node_id,
                        timestamp=normalized.timestamp
                    ))
                elif rule_action == "restart_encoder":
                    # Stop first, then start
                    url_stop = f"http://{agent_ip}:8000/jobs/control"
                    _http.post(url_stop, params={"action": "stop", "program_name": prog_name}, headers=headers, timeout=5)
                    url_start = f"http://{agent_ip}:8000/jobs/create"
                    payload_start = {
                        "job_id": encoder_job.id,
                        "channel_name": channel.channel_name,
                        "command": encoder_job.command_compress,
                        "autostart": True
                    }
                    _http.post(url_start, json=payload_start, headers=headers, timeout=10)
                    encoder_job.status = "starting"
                    db.add(models.MonitorLog(
                        event_type="ENCODER_RESTARTED",
                        message=f"Encoder de {channel.channel_name} reiniciado por regla: {result['rule']['name']}",
                        node_id=encoder_job.node_id,
                        timestamp=normalized.timestamp
                    ))
            except Exception as e:
                logger.warning(f"Error ejecutando acción en encoder: {e}")

    db.commit()
    return {
        "status": "success",
        "message": result.get("message", "Alerta procesada"),
        "rule": result.get("rule"),
        "action_taken": result.get("action_taken", False),
    }
