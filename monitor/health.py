"""
Monitor — Health module.
Node health checks and status detection for DRM, Encoder, and Packager nodes.
"""
import json
import logging
from datetime import datetime

import models
from core.config import AGENT_PORT, DRM_HEALTH_PORT
from utils.helpers import log_monitor_event
from .alerts import notify_cms_channel_status
from .commands import send_command

logger = logging.getLogger(__name__)

_drm_stats_counter = {}


def check_drm_node(db, node, req_session):
    """Health check for DRM nodes."""
    try:
        health_resp = req_session.get(f"http://{node.ip_address}:{DRM_HEALTH_PORT}/health", timeout=5)
        health = health_resp.json()
        if health.get("healthy", False):
            node.status = "online"
        else:
            node.status = "degraded"
        node.drm_health_status = health.get("status", "unknown")
        node.drm_widevine = health.get("widevine", "unknown")
        node.drm_database = health.get("database", "unknown")
        node.last_heartbeat = datetime.now()

        counter = _drm_stats_counter.get(node.id, 0) + 1
        _drm_stats_counter[node.id] = counter
        if counter >= 3:
            _drm_stats_counter[node.id] = 0
            try:
                stats_resp = req_session.get(f"http://{node.ip_address}:{DRM_HEALTH_PORT}/stats", timeout=5)
                stats = stats_resp.json()
                node.drm_total_users = stats.get("totalUsers", 0)
                node.drm_total_devices = stats.get("totalDevices", 0)
                node.drm_last_stats_at = datetime.now()
                if node.drm_total_devices > 50000:
                    logger.warning(f"⚠️ DRM {node.hostname}: {node.drm_total_devices} dispositivos (umbral 50k)")
                for u in stats.get("users", []):
                    if u.get("activeDevices", 0) >= u.get("maxScreens", 999):
                        logger.warning(f"⚠️ DRM {node.hostname}: usuario {u['userId']} al límite ({u['activeDevices']}/{u['maxScreens']})")
            except json.JSONDecodeError:
                logger.warning(f"⚠️ DRM {node.hostname}: /stats devolvió JSON inválido, ignorando stats en este ciclo")
            except Exception as e:
                logger.warning(f"⚠️ DRM {node.hostname}: error obteniendo stats: {e}")

        db.commit()
    except Exception as e:
        if node.status != "offline":
            logger.error(f"🔴 DRM {node.hostname} ({node.ip_address}) OFFLINE. Error: {e}")
            log_monitor_event(db, "NODE_DOWN", f"DRM {node.hostname} ({node.ip_address}) no responde: {e}", node.id)
        node.status = "offline"
        db.commit()


def detect_encoder_restart(db, node, current_uptime_seconds):
    """Detecta si un encoder se reinició comparando uptime."""
    if current_uptime_seconds is None or current_uptime_seconds == 0:
        return False

    if node.previous_uptime_seconds is None:
        node.previous_uptime_seconds = current_uptime_seconds
        return False

    if current_uptime_seconds < node.previous_uptime_seconds:
        logger.warning(f"🔄 REINICIO DETECTADO: {node.hostname} "
                       f"(uptime {node.previous_uptime_seconds}s → {current_uptime_seconds}s)")

        node.last_restart_detected_at = datetime.now()
        node.previous_uptime_seconds = current_uptime_seconds
        return True

    if current_uptime_seconds > node.previous_uptime_seconds:
        node.previous_uptime_seconds = current_uptime_seconds

    return False


def handle_encoder_restart_recovery(db, node, req_session):
    """Maneja recovery completo tras reinicio de encoder."""
    if node.last_restart_detected_at:
        time_since_last = (datetime.now() - node.last_restart_detected_at).total_seconds()
        if time_since_last < 3600:
            logger.debug(f"Recovery rate limited for {node.hostname} ({time_since_last:.0f}s since last)")
            return

    running_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(["running", "starting"])
    ).all()

    if not running_jobs:
        return

    agent_names = set()
    try:
        resp = req_session.get(f"http://{node.ip_address}:{AGENT_PORT}/jobs/status", timeout=10)
        if resp.status_code == 200:
            raw = resp.json()
            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                agent_names = {p['name'].lower() for p in raw}
    except Exception as e:
        logger.warning(f"No se pudo verificar procesos del agente en RESTART_RECOVERY: {e}")

    ghost_jobs = []
    for job in running_jobs:
        prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
        prog = f"{prefix}_{job.channel.channel_name}_{job.id}"
        if prog.lower() not in agent_names:
            job.status = "error"
            job.auto_started = False
            job.updated_at = datetime.now()
            ghost_jobs.append(job)

    if not ghost_jobs:
        return

    logger.warning(f"🔄 RECOVERY POST-RESTART: {len(ghost_jobs)} jobs en {node.hostname}")
    for job in ghost_jobs:
        prog_name = f"{'pkg' if node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"
        try:
            if job.command:
                import base64, zlib
                compressed = base64.b64encode(zlib.compress(job.command.encode('utf-8'))).decode('utf-8')
                payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": compressed, "autostart": True}
                resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                if resp.status_code == 200:
                    job.status = "starting"
                    job.auto_started = True
                    job.started_at = datetime.now()
                    logger.info(f"  ✅ {prog_name} → starting")
                else:
                    logger.warning(f"  ❌ {prog_name} → error {resp.status_code}")
            else:
                send_command(job, "start", req_session)
                job.status = "starting"
                job.auto_started = True
                job.started_at = datetime.now()
                logger.info(f"  ✅ {prog_name} → starting (start)")
        except Exception as e:
            logger.warning(f"  ❌ {prog_name} → exception: {e}")

    log_monitor_event(db, "ENCODER_RESTART_RECOVERY",
                     f"Recovery post-restart: {len(ghost_jobs)} jobs relanzados en {node.hostname}",
                     node.id)
    db.commit()

    try:
        from .alerts import notify_telegram
        msg = f"🔄 *REINICIO DETECTADO*: {node.hostname}\n"
        msg += f"Jobs recovery: {len(ghost_jobs)} relanzados"
        notify_telegram(msg)
    except Exception:
        pass


def check_packager_source_health(db, job, req_session):
    if job.parent_job_id:
        parent = db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id).first()
        if parent and parent.status not in ['running', 'starting']:
            if job.status != "failover":
                logger.warning(f"🚨 ENCODER SIN SEÑAL (Estado: {parent.status}). Activando Failover en Packager {job.id}...")
                log_monitor_event(db, "FAILOVER_ACTIVATED", f"Encoder de {job.channel.channel_name} sin señal. Activando Failover.", job.node_id)
                notify_cms_channel_status(job.channel_id, "failover", f"Encoder en {parent.status}. Iniciando failover de emergencia.")
                try:
                    res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{job.channel_id}?mode=activate", timeout=30)
                    if res.status_code == 200:
                        logger.info(f"✅ Failover iniciado exitosamente por caída del origen.")
                        db.refresh(job)
                        return True
                except Exception as e:
                    logger.error(f"⚠️ Error de red solicitando Failover: {e}")
            return False

    try:
        bitrate_val = float(job.current_bitrate) if getattr(job, 'current_bitrate', None) else 0.0
    except ValueError:
        bitrate_val = 0.0

    if bitrate_val > 50000:
        return False

    prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
    prog_name = f"{prefix}_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 20}, timeout=3)
        if resp.status_code == 200:
            log_content = resp.json().get("content", "")
            if "Input/output error" in log_content or "End of stream" in log_content:
                if job.status != "failover":
                    logger.warning(f"🚨 ERROR CORRUPCIÓN detectado en logs de {prog_name}. Disparando Failover...")
                    log_monitor_event(db, "FAILOVER_ACTIVATED", f"Corrupción detectada en logs del packager {prog_name}. Activando Failover.", job.node_id)
                    notify_cms_channel_status(job.channel_id, "failover", "Corrupción de flujo detectada en logs del packager.")
                    try:
                        res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{job.channel_id}?mode=activate", timeout=30)
                        if res.status_code == 200:
                            logger.info(f"✅ Failover iniciado exitosamente por logs.")
                            db.refresh(job)
                            return True
                    except Exception as e:
                        logger.error(f"⚠️ Error en Failover al Orquestador: {e}")
    except Exception:
        pass

    return False
