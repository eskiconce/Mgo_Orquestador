"""
Monitor — Main orchestration module.
Syncs processes and automates recovery across all nodes.
"""
import time
import base64
import zlib
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import SessionLocal
import models
from core.config import POLL_INTERVAL, AGENT_PORT
from core.http_client import create_sync_client
from utils.helpers import log_monitor_event

from .alerts import notify_cms_channel_status
from .commands import send_command, kill_flow_safety
from .checks import (
    check_encoder_ts_errors, check_encoder_health_logs,
    check_timestamp_discontinuity, check_ffmpeg_drop_frames,
    reset_stale_state, _prev_logs, _ts_error_state,
)
from .health import (
    check_drm_node, detect_encoder_restart, handle_encoder_restart_recovery,
    check_packager_source_health,
)
from .recovery import (
    recover_node_jobs, cleanup_ghost_jobs, check_and_heal_children,
)

# --- Logging setup ---
LOG_FILE = "logs/monitor.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.basicConfig(handlers=[handler], level=logging.INFO)
for _log in ("httpx", "httpcore", "hpack"):
    logging.getLogger(_log).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

_cleanup_counter = 0


def process_node_thread(node_id):
    """Maneja la sincronización de UN SOLO nodo de forma independiente."""
    db = SessionLocal()
    req_session = create_sync_client()

    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if not node or not node.enabled:
            return

        if node.tipo == 'DRM':
            check_drm_node(db, node, req_session)
            return

        url_jobs = f"http://{node.ip_address}:{AGENT_PORT}/jobs/status"
        url_health = f"http://{node.ip_address}:{AGENT_PORT}/health"

        try:
            resp = req_session.get(url_jobs, timeout=15)
            try:
                resp_health = req_session.get(url_health, timeout=8)
                if resp_health.status_code == 200:
                    h_data = resp_health.json()
                    health_record = db.query(models.EncoderHealth).filter_by(encoder_id=node.id).first()
                    if not health_record:
                        health_record = models.EncoderHealth(encoder_id=node.id)
                        db.add(health_record)
                    health_record.reachable = True
                    health_record.cpu_usage = h_data.get('cpu', 0)
                    health_record.p_cpu_usage = h_data.get("p_cpu_usage", 0)
                    health_record.ram_usage = h_data.get('ram', 0)
                    health_record.gpu_usage = h_data.get('gpu', 0)
                    health_record.ffmpeg_running = True
                    node.uptime = str(h_data.get('uptime', "00:00:00"))

                    if node.tipo == 'Encoder':
                        uptime_seconds = h_data.get('uptime_seconds', 0)
                        if detect_encoder_restart(db, node, uptime_seconds):
                            handle_encoder_restart_recovery(db, node, req_session)
            except Exception as he:
                logger.warning(f"No se pudo obtener health del nodo {node.hostname}: {he}")

            if node.status != "online":
                logger.info(f"🟢 Nodo {node.hostname} ({node.ip_address}) está ONLINE.")
                log_monitor_event(db, "NODE_UP", f"El servidor {node.hostname} ({node.ip_address}) ha vuelto a responder al orquestador.", node.id)
                node.status = "online"
                recover_node_jobs(db, node, req_session)

            node.last_heartbeat = datetime.now()

        except Exception as e:
            if node.status != "offline":
                logger.error(f"🔴 Nodo {node.hostname} ({node.ip_address}) está OFFLINE. Error: {e}")
                node.status = "offline"
                db.commit()
                log_monitor_event(db, "NODE_DOWN", f"El servidor {node.hostname} ({node.ip_address}) ha dejado de responder.", node.id)

            time_since_last_beat = 46
            if getattr(node, 'last_heartbeat', None):
                time_since_last_beat = (datetime.now() - node.last_heartbeat).total_seconds()

            if time_since_last_beat > 45:
                cleanup_ghost_jobs(db, node, req_session)
            return

        if resp.status_code == 200:
            raw = resp.json()
            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                real_processes = raw
            else:
                logger.warning(f"⚠️ Agente {node.hostname} devolvió formato inesperado en /jobs/status: {type(raw).__name__} — se omite sync este ciclo")
                real_processes = []
            process_map = {p['name'].lower(): p for p in real_processes}
            db_jobs = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id).all()

            for job in db_jobs:
                prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
                prog_name = f"{prefix}_{job.channel.channel_name}_{job.id}"
                prog_name_lower = prog_name.lower()
                state = "STOPPED"
                real_info = None

                if prog_name_lower in process_map:
                    real_info = process_map[prog_name_lower]
                    state = real_info['statename']

                if job.status == "stopped" and state == "RUNNING" and not job.auto_started:
                    logger.warning(f"👻 ZOMBIE: {prog_name} corre sin permiso.")
                    log_monitor_event(db, "ZOMBIE_DETECTED", f"Proceso {prog_name} corría sin permiso. se asume como RUNNING.", node.id)
                    job.status = "running"
                    start_val = real_info.get('start', 0)
                    job.started_at = datetime.fromtimestamp(start_val) if start_val > 0 else datetime.now()

                if state == "RUNNING":
                    if real_info and real_info.get('bitrate'): job.current_bitrate = str(real_info['bitrate'])
                    if real_info and real_info.get('fps'): job.current_fps = float(real_info['fps'])

                    if job.status not in ["running", "failover"]:
                        logger.info(f"✅ Sincronizado: {prog_name} en estado RUNNING.")
                        log_monitor_event(db, "PROCESS_SYNCED", f"Proceso {prog_name} paso a estado RUNNING.", node.id)
                        job.status = "running"
                        job.auto_started = False
                        _ts_error_state.pop(job.id, None)
                        _prev_logs.pop(f"{prog_name}_err", None)

                    if real_info and 'start' in real_info:
                        start_ts = real_info.get('start', 0)
                        if start_ts > 0:
                            real_start = datetime.fromtimestamp(start_ts)
                            if job.started_at != real_start:
                                job.started_at = real_start
                        else:
                            if not job.started_at:
                                job.started_at = datetime.now()

                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        check_packager_source_health(db, job, req_session)

                    if node.tipo == 'Encoder':
                        if not check_timestamp_discontinuity(db, job, req_session):
                            check_and_heal_children(db, job, req_session)

                        if job.node.tipo == 'Encoder':
                            check_ffmpeg_drop_frames(db, job, req_session)

                elif state in ["FATAL", "BACKOFF", "EXITED"]:
                    is_failover_triggered = False
                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        is_failover_triggered = check_packager_source_health(db, job, req_session)

                    if not is_failover_triggered:
                        if job.status == "starting":
                            if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 20:
                                logger.warning(f"🕒 FALLO INICIO: {prog_name}. Reset a ERROR.")
                                job.status = "error"
                                job.auto_started = False
                                job.updated_at = datetime.now()
                                log_monitor_event(db, "PROCESS_START_FAIL", f"Fallo al iniciar {prog_name}.", node.id)

                        elif job.status not in ["error", "failover", "stopped"]:
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            logger.warning(f"⚠️ ERROR: {prog_name} cayó a estado {state}. Marcado en BD.")
                            log_monitor_event(db, "PROCESS_CRASHED", f"El proceso {prog_name} cayó a estado {state}.", node.id)

                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", f"El proceso encoder cayó a estado {state}")

                        else:
                            if job.updated_at and job.status != "failover":
                                elapsed = (datetime.now() - job.updated_at).total_seconds()
                                if elapsed > 60:
                                    if state == "BACKOFF":
                                        logger.error(f"💀 AUTO-KILL: {prog_name} inestable > 60s.")
                                        log_monitor_event(db, "AUTO_KILL", f"Proceso {prog_name} inestable. Auto-detenido.", node.id)
                                    kill_flow_safety(db, job, req_session)

                elif state == "STOPPED":
                    if job.status == "starting":
                        if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 20:
                            logger.warning(f"🕒 FALLO INICIO: {prog_name}. Reset a ERROR.")
                            log_monitor_event(db, "PROCESS_START_FAIL", f"Fallo al intentar iniciar {prog_name}. Tiempo agotado.", node.id)
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            db.commit()

                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", "Fallo al iniciar el proceso del encoder.")

                    elif job.status not in ["stopped", "error", "failover"]:
                        job.status = "stopped"
                        job.started_at = None
                        job.auto_started = False
                        job.updated_at = datetime.now()
                        db.commit()

                        if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "offline", "El encoder fue detenido.")

                elif job.status in ["error", "stopped"] and job.started_at is not None:
                    last_update = job.updated_at or job.started_at
                    cooldown = 60
                    if last_update and (datetime.now() - last_update).total_seconds() > cooldown:
                        logger.info(f"🔄 RECOVERY-RETRY: reintentando {prog_name} ({job.status}) en nodo activo.")
                        try:
                            if job.command:
                                compressed = base64.b64encode(zlib.compress(job.command.encode('utf-8'))).decode('utf-8')
                                payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": compressed, "autostart": True}
                                resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                                if resp.status_code == 200:
                                    job.status = "starting"
                                    job.auto_started = True
                                    job.updated_at = datetime.now()
                                    db.commit()
                                    logger.info(f"  ✅ {prog_name} → starting (recovery)")
                                else:
                                    job.updated_at = datetime.now()
                                    db.commit()
                                    logger.warning(f"  ❌ {prog_name} → error {resp.status_code}")
                            else:
                                send_command(job, "start", req_session)
                                job.status = "starting"
                                job.auto_started = True
                                job.updated_at = datetime.now()
                                db.commit()
                                logger.info(f"  ✅ {prog_name} → starting (recovery start)")
                        except Exception as re:
                            logger.warning(f"  ❌ {prog_name} recovery exception: {re}")

        db.commit()

    except Exception as e:
        logger.error(f"Error procesando hilo del nodo {node_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        req_session.close()
        db.close()


def sync_processes_and_automate():
    db = SessionLocal()
    try:
        nodes = db.query(models.Node).filter(models.Node.enabled == True).all()
        node_ids = [n.id for n in nodes]
    except Exception as e:
        logger.error(f"Error recuperando nodos de BD: {e}")
        return
    finally:
        db.close()

    if not node_ids:
        return

    with ThreadPoolExecutor(max_workers=min(20, len(node_ids))) as executor:
        futures = [executor.submit(process_node_thread, nid) for nid in node_ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Falla fatal en hilo de nodo: {e}")


def run_forever():
    """Main monitor loop — runs indefinitely."""
    global _cleanup_counter
    logger.info("⚡ Iniciando Orquestador en modo MULTITHREAD...")
    while True:
        start_time = time.time()
        sync_processes_and_automate()
        duration = time.time() - start_time

        _cleanup_counter += 1
        if _cleanup_counter >= 60:
            _cleanup_counter = 0
            db = SessionLocal()
            try:
                active_progs = set()
                jobs = db.query(models.EncodingJob).filter(
                    models.EncodingJob.status == 'running'
                ).all()
                for j in jobs:
                    prefix = "pkg" if j.node.tipo == 'Packager' else "channel"
                    active_progs.add(f"{prefix}_{j.channel.channel_name}_{j.id}")
                reset_stale_state(active_progs | {j.id for j in jobs})
            except Exception:
                pass
            finally:
                db.close()

        sleep_time = max(0, POLL_INTERVAL - duration)
        time.sleep(sleep_time)
