import time
import httpx
import json
import base64
import zlib
import re
import logging
from logging.handlers import RotatingFileHandler
import os
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- IMPORTAMOS LA FUNCIÓN REGISTRADORA DEL MONITOR ---
from utils.helpers import log_monitor_event
from services import builders as bld
from core.config import (
    AGENT_API_KEY, AGENT_PORT, DRM_HEALTH_PORT, POLL_INTERVAL,
    CMS_REAL_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
)
from core.http_client import create_sync_client

# Almacena el contenido del log de cada proceso entre polls, para contar solo errores NUEVOS.
_prev_logs = {}

# Configuración
LOG_FILE = "logs/monitor.log"

# --- STATE TRACKER para errores TS y detección de estancamiento en encoders ---
# Estructura: { job_id: { "first_seen": datetime, "last_restart": datetime|None,
#                         "restart_count": int, "down_since": datetime|None,
#                         "backup_tried": bool, "final_alerted": bool,
#                         "last_frame": str|None, "last_time": str|None,
#                         "stuck_count": int } }
_ts_error_state = {}
_drm_stats_counter = {}  # Contador para polling de stats DRM (cada 3er poll)
_ts_discontinuity_state = {}  # {job_id: {"first_seen": datetime, "restart_count": int}}
_drop_baseline_state = {}  # {job_id: {"initial_drop": int, "last_alerted_drop": int}}


def notify_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.basicConfig(handlers=[handler], level=logging.INFO)
for _log in ("httpx", "httpcore", "hpack"):
    logging.getLogger(_log).setLevel(logging.WARNING)


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
        
        logging.info(f"📡 Notificando al CMS evento '{status_event}' para el canal {payload['canal']}")
        with httpx.Client(timeout=5.0) as client:
            client.post(CMS_REAL_WEBHOOK, json=payload)
        
    except Exception as e:
        logging.error(f"⚠️ Error enviando notificación de estado al CMS: {e}")
    finally:
        db.close()

def check_packager_source_health(db, job, req_session):
    if job.parent_job_id:
        parent = db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id).first()
        if parent and parent.status not in ['running', 'starting']:
            if job.status != "failover":
                logging.warning(f"🚨 ENCODER SIN SEÑAL (Estado: {parent.status}). Activando Failover en Packager {job.id}...")
                log_monitor_event(db, "FAILOVER_ACTIVATED", f"Encoder de {job.channel.channel_name} sin señal. Activando Failover.", job.node_id)
                notify_cms_channel_status(job.channel_id, "failover", f"Encoder en {parent.status}. Iniciando failover de emergencia.")
                try:
                    res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{job.channel_id}?mode=activate", timeout=30)
                    if res.status_code == 200:
                        logging.info(f"✅ Failover iniciado exitosamente por caída del origen.")
                        db.refresh(job) 
                        return True
                except Exception as e:
                    logging.error(f"⚠️ Error de red solicitando Failover: {e}")
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
                    logging.warning(f"🚨 ERROR CORRUPCIÓN detectado en logs de {prog_name}. Disparando Failover...")
                    log_monitor_event(db, "FAILOVER_ACTIVATED", f"Corrupción detectada en logs del packager {prog_name}. Activando Failover.", job.node_id)
                    notify_cms_channel_status(job.channel_id, "failover", "Corrupción de flujo detectada en logs del packager.")
                    try:
                        res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{job.channel_id}?mode=activate", timeout=30)
                        if res.status_code == 200:
                            logging.info(f"✅ Failover iniciado exitosamente por logs.")
                            db.refresh(job)
                            return True
                    except Exception as e:
                        logging.error(f"⚠️ Error en Failover al Orquestador: {e}")
    except Exception:
        pass 
        
    return False

# ========================================================================
# MONITOREO DE ERRORES MPEGTS (demux) EN ENCODERS
# ========================================================================
def check_encoder_ts_errors(db, job, req_session):
    if job.node.tipo != "Encoder":
        return False
    if job.status not in ("running", "starting", "error"):
        return False

    job_id = job.id
    channel = job.channel
    prog_name = f"channel_{channel.channel_name}_{job_id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 30}, timeout=5)
        if resp.status_code != 200:
            return False
        log_content = resp.json().get("content", "")
    except Exception:
        return False

    now = datetime.now()
    state = _ts_error_state.get(job_id)
    if state is None:
        state = {"first_seen": now, "last_restart": None, "restart_count": 0,
                 "down_since": None, "backup_tried": False, "final_alerted": False,
                 "last_frame": None, "last_time": None, "stuck_count": 0,
                 "last_error_seen": now}
        _ts_error_state[job_id] = state
    else:
        # Si pasaron >120s desde el ultimo error, es un nuevo incidente → resetear escalada
        last_error = state.get("last_error_seen")
        if last_error and (now - last_error).total_seconds() > 120:
            state["first_seen"] = now
            state["restart_count"] = 0
            state["down_since"] = None
            state["backup_tried"] = False
            state["final_alerted"] = False
            state["stuck_count"] = 0
        state["last_error_seen"] = now

    # Detectar errores TS activos en el log
    ts_error_patterns = ["length violation", "Found tag", "PES packet size mismatch", "Packet corrupt"]
    has_ts_error = any(p in log_content for p in ts_error_patterns)

    # Extraer frame actual del log para detectar estancamiento
    import re
    current_frame = None
    current_time = None
    m_frame = re.search(r'frame=\s*(\d+)', log_content)
    m_time = re.search(r'time=(\d+:\d+:\d+\.\d+)', log_content)
    if m_frame:
        current_frame = m_frame.group(1)
    if m_time:
        current_time = m_time.group(1)

    is_stuck = False
    if current_frame and current_time:
        if current_frame == state["last_frame"] and current_time == state["last_time"]:
            state["stuck_count"] += 1
            if state["stuck_count"] >= 3 and not has_ts_error:
                is_stuck = True
        else:
            state["stuck_count"] = 0
            state["last_frame"] = current_frame
            state["last_time"] = current_time

    if not has_ts_error and not is_stuck:
        state["stuck_count"] = 0
        return False

    reason = "TS error" if has_ts_error else "ENCERRADO"
    elapsed = (now - state["first_seen"]).total_seconds()

    # FASES de escalado (compartidas para errores TS y estancamiento)
    if state["restart_count"] == 0 and elapsed >= 30:
        logging.warning(f"{reason} persistente en {prog_name} por {elapsed:.0f}s — restart #1")
        send_command(job, "restart", req_session)
        job.started_at = datetime.now()
        db.commit()
        state["last_restart"] = now
        state["restart_count"] = 1
        state["first_seen"] = now
        _prev_logs.pop(f"{prog_name}_err", None)
        return True

    if state["restart_count"] == 1 and elapsed >= 90:
        logging.warning(f"{reason} tras restart en {prog_name} — stop + espera 60s")
        send_command(job, "stop", req_session)
        state["down_since"] = now
        state["restart_count"] = 2
        return True

    if state["restart_count"] == 2 and state["down_since"]:
        down_elapsed = (now - state["down_since"]).total_seconds()
        if down_elapsed >= 60:
            logging.warning(f"{reason} en {prog_name} tras 60s down — restart #2")
            send_command(job, "restart", req_session)
            job.started_at = datetime.now()
            db.commit()
            state["last_restart"] = now
            state["restart_count"] = 3
            state["first_seen"] = now
            _prev_logs.pop(f"{prog_name}_err", None)
            return True

    if state["restart_count"] == 3 and elapsed >= 180:
        if not state["backup_tried"]:
            logging.warning(f"{reason} persistente en {prog_name} — intentando switch a backup source")
            _try_switch_to_backup(db, job, req_session)
            state["backup_tried"] = True
            return True
        elif not state["final_alerted"]:
            logging.error(f"{reason} en {prog_name} persiste incluso con backup — alerta final")
            _send_final_alert(db, job, prog_name)
            state["final_alerted"] = True
            return True

    return False


def _try_switch_to_backup(db, job, req_session):
    channel = job.channel
    if channel.origin_count < 2:
        logging.warning(f"TS backup: {channel.channel_name} no tiene origen de respaldo")
        return False

    channel.active_origin = "backup"
    db.commit()
    logging.info(f"TS backup: active_origin=backup para {channel.channel_name}")

    prog_name = f"channel_{channel.channel_name}_{job.id}"
    try:
        if job.node.tipo == "Encoder" and "mac" in (job.node.os or "").lower():
            new_script = bld.generate_mac_encoder_bash(channel, job.node, use_backup=True)
        else:
            new_script = bld.generate_linux_encoder_bash(channel, job.node, use_backup=True)

        job.command = new_script
        db.commit()

        compressed = bld.compress_command(new_script)
        job.command_compress = compressed
        db.commit()

        url_create = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create"
        resp = req_session.post(url_create, json={
            "job_id": job.id,
            "channel_name": channel.channel_name,
            "command": compressed,
            "autostart": True
        }, timeout=10)
        if resp.status_code == 200:
            logging.info(f"TS backup: comando actualizado en agente para {prog_name}")
    except Exception as e:
        logging.error(f"TS backup: error regenerando script para {prog_name}: {e}")

    notify_cms_channel_status(channel.id, "backup_activated", f"Conmutación a fuente de respaldo por errores TS en encoder.")
    notify_telegram(f"<b>🔄 Backup activado</b> para <b>{channel.channel_name}</b>\nMotivo: errores TS persistentes en encoder\nOrigen: {channel.origin2_multicast_ip}:{channel.origin2_multicast_port}")

    send_command(job, "restart", req_session)
    job.started_at = datetime.now()
    db.commit()
    return True


def _send_final_alert(db, job, prog_name):
    channel = job.channel
    msg = f"<b>🚨 ALERTA: {channel.channel_name}</b>\nErrores TS persisten tras agotar reintentos y backup\nRequiere intervención manual"
    notify_telegram(msg)
    notify_cms_channel_status(channel.id, "critical_ts_error", "Errores TS críticos en encoder tras agotar todas las acciones automáticas")
    logging.error(f"TS FINAL ALERT: {prog_name}")


def check_encoder_health_logs(db, job, req_session):
    """
    Lee los logs del Encoder para detectar corrupción severa de red (UDP).
    Utiliza un umbral de tolerancia para no reiniciar ante micro-cortes recuperables.
    """
    if job.status != 'running' or not job.started_at:
        return False

    # Período de gracia (Cooldown) de 60 segundos tras un inicio/reinicio
    uptime = abs((datetime.now() - job.started_at).total_seconds())
    if uptime < 60:
        return False

    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"
    
    try:
        # AUMENTO DE MUESTRA: Pedimos 60 líneas para tener un contexto más amplio
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 60}, timeout=5)
        if resp.status_code == 200:
            log_content = resp.json().get("content", "")
            
            # Palabras clave de fallas críticas
            error_keywords = [
                "Packet corrupt", 
                "PES packet size mismatch", 
                "co located POCs unavailable", 
                "timestamp discontinuity"
            ]
            
            # ================================================
            # DEDUPLICACIÓN ENTRE POLLS: Contamos solo errores NUEVOS
            # Detectamos cuántas líneas del log actual ya estaban en el poll anterior.
            # Así evitamos que errores viejos (aún en la ventana de 60 líneas)
            # se sigan acumulando como si fueran fallas nuevas.
            # ================================================
            prev_content = _prev_logs.get(prog_name, "")
            _prev_logs[prog_name] = log_content
            
            prev_lines = prev_content.split('\n')
            curr_lines = log_content.split('\n')
            
            # Buscar solapamiento: la cola del log anterior coincide con la cabeza del actual
            # (ventana deslizante de 60 líneas)
            overlap = 0
            for i in range(min(len(prev_lines), len(curr_lines)), 0, -1):
                if prev_lines[-i:] == curr_lines[:i]:
                    overlap = i
                    break
            
            # Solo las líneas nuevas (no solapadas) se evalúan
            new_lines = curr_lines[overlap:]
            
            error_count = 0
            for line in new_lines:
                if any(keyword in line for keyword in error_keywords):
                    error_count += 1
            
            # Si no hay líneas nuevas, no hay errores frescos — salimos
            if len(new_lines) == 0:
                return False
            
            # LÓGICA DE UMBRAL (THRESHOLD) — sobre errores NUEVOS
            if error_count >= 10:
                # Falla en cascada: FFmpeg no se está recuperando bien. REINICIO.
                logging.warning(f"🚨 CORRUPCIÓN CRÍTICA ({error_count} errores en 60 líneas) en {prog_name}. Forzando reinicio preventivo...")
                log_monitor_event(db, "AUTO_RESTART", f"Corrupción severa de red ({error_count} fallos) en origen de {prog_name}. Reiniciando.", job.node_id)
                
                send_command(job, "restart", req_session)
                
                job.started_at = datetime.now()
                db.add(job)
                db.commit()
                
                notify_cms_channel_status(job.channel_id, "warning", "Reinicio preventivo por corrupción severa de red.")
                return True
                
            elif error_count > 0:
                # Micro-cortes aislados: FFmpeg lo manejó. SOLO OBSERVACIÓN.
                logging.info(f"⚠️ Micro-corte UDP en {prog_name} ({error_count} errores detectados). El encoder se recuperó, mantenemos en observación.")
                
    except Exception:
        pass 
        
    return False

def check_timestamp_discontinuity(db, job, req_session):
    """Detecta timestamp discontinuity en logs del encoder. Si persiste >60s, reinicia."""
    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"
    
    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 30}, timeout=5)
        if resp.status_code != 200:
            return False
        log_content = resp.text
    except Exception:
        return False
    
    if "timestamp discontinuity" not in log_content:
        # No hay discontinuity → limpiar estado
        _ts_discontinuity_state.pop(job.id, None)
        return False
    
    now = datetime.now()
    state = _ts_discontinuity_state.get(job.id)
    
    if state is None:
        _ts_discontinuity_state[job.id] = {"first_seen": now, "restart_count": 0}
        logging.warning(f"⚠️ Timestamp discontinuity detectado en {prog_name}")
        return False
    
    elapsed = (now - state["first_seen"]).total_seconds()
    
    if elapsed >= 60 and state["restart_count"] == 0:
        logging.warning(f"🔴 Timestamp discontinuity persistente en {prog_name} ({elapsed:.0f}s) — reiniciando encoder")
        send_command(job, "restart", req_session)
        job.started_at = datetime.now()
        db.commit()
        state["restart_count"] = 1
        state["first_seen"] = now
        _prev_logs.pop(f"{prog_name}_err", None)
        log_monitor_event(db, "TIMESTAMP_DISCONTINUITY", f"Encoder {prog_name} reiniciado por timestamp discontinuity persistente ({elapsed:.0f}s).", job.node.id)
        notify_cms_channel_status(job.channel_id, "restart", f"Encoder reiniciado por discontinuity")
        notify_telegram(f"⚠️ <b>Encoder reiniciado</b> por discontinuity\nCanal: <b>{job.channel.channel_name}</b>\nNodo: {job.node.hostname}\nTiempo: {elapsed:.0f}s")
        return True
    
    return False


def check_ffmpeg_drop_frames(db, job, req_session):
    """Monitorea cambios en drop frames vs baseline del encoder. Solo log, sin Telegram."""
    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"
    
    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 10}, timeout=5)
        if resp.status_code != 200:
            return
        log_content = resp.text
    except Exception:
        return
    
    drop_match = re.search(r'drop=(\d+)', log_content)
    if not drop_match:
        return
    
    drop_actual = int(drop_match.group(1))
    
    state = _drop_baseline_state.get(job.id)
    if state is None:
        _drop_baseline_state[job.id] = {
            "initial_drop": drop_actual,
            "last_alerted_drop": drop_actual,
        }
        logging.info(f"📊 Drop baseline para {prog_name}: {drop_actual}")
        return
    
    if drop_actual > state["last_alerted_drop"]:
        delta = drop_actual - state["initial_drop"]
        log_monitor_event(db, "DROP_FRAMES", 
            f"{prog_name}: drop {state['last_alerted_drop']}→{drop_actual} (baseline: {state['initial_drop']}, delta: +{delta})",
            job.node.id)
        state["last_alerted_drop"] = drop_actual
    
    elif drop_actual < state["last_alerted_drop"]:
        logging.info(f"📊 Drop disminuyó en {prog_name}: {state['last_alerted_drop']} → {drop_actual}")
        state["last_alerted_drop"] = drop_actual


def detect_encoder_restart(db, node, current_uptime_seconds):
    """Detecta si un encoder se reinició comparando uptime."""
    if current_uptime_seconds is None or current_uptime_seconds == 0:
        return False
    
    if node.previous_uptime_seconds is None:
        node.previous_uptime_seconds = current_uptime_seconds
        return False
    
    if current_uptime_seconds < node.previous_uptime_seconds:
        logging.warning(f"🔄 REINICIO DETECTADO: {node.hostname} "
                       f"(uptime {node.previous_uptime_seconds}s → {current_uptime_seconds}s)")
        
        node.last_restart_detected_at = datetime.now()
        node.previous_uptime_seconds = current_uptime_seconds
        return True
    
    if current_uptime_seconds > node.previous_uptime_seconds:
        node.previous_uptime_seconds = current_uptime_seconds
    
    return False


def handle_encoder_restart_recovery(db, node, req_session):
    """Maneja recovery completo tras reinicio de encoder."""
    # Rate limiting: max 1 recovery per hour per node
    if node.last_restart_detected_at:
        time_since_last = (datetime.now() - node.last_restart_detected_at).total_seconds()
        if time_since_last < 3600:
            logging.debug(f"Recovery rate limited for {node.hostname} ({time_since_last:.0f}s since last)")
            return
    
    # Find jobs that were running
    running_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(["running", "starting"])
    ).all()
    
    if not running_jobs:
        return
    
    # Query agent for actual running processes
    agent_names = set()
    try:
        resp = req_session.get(f"http://{node.ip_address}:{AGENT_PORT}/jobs/status", timeout=10)
        if resp.status_code == 200:
            raw = resp.json()
            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                agent_names = {p['name'].lower() for p in raw}
    except Exception as e:
        logging.warning(f"No se pudo verificar procesos del agente en RESTART_RECOVERY: {e}")
    
    # Identify ghost jobs
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
    
    # Relaunch ghost jobs
    logging.warning(f"🔄 RECOVERY POST-RESTART: {len(ghost_jobs)} jobs en {node.hostname}")
    for job in ghost_jobs:
        prog_name = f"{'pkg' if node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"
        try:
            if job.command:
                compressed = base64.b64encode(zlib.compress(job.command.encode('utf-8'))).decode('utf-8')
                payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": compressed, "autostart": True}
                resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                if resp.status_code == 200:
                    job.status = "starting"
                    job.auto_started = True
                    job.started_at = datetime.now()
                    logging.info(f"  ✅ {prog_name} → starting")
                else:
                    logging.warning(f"  ❌ {prog_name} → error {resp.status_code}")
            else:
                send_command(job, "start", req_session)
                job.status = "starting"
                job.auto_started = True
                job.started_at = datetime.now()
                logging.info(f"  ✅ {prog_name} → starting (start)")
        except Exception as e:
            logging.warning(f"  ❌ {prog_name} → exception: {e}")
    
    db.commit()
    log_monitor_event(db, "ENCODER_RESTART_RECOVERY", 
                     f"Recovery post-restart: {len(ghost_jobs)} jobs relanzados en {node.hostname}", 
                     node.id)
    
    # Telegram notification
    try:
        msg = f"🔄 *REINICIO DETECTADO*: {node.hostname}\n"
        msg += f"Jobs recovery: {len(ghost_jobs)} relanzados"
        notify_telegram(msg)
    except Exception:
        pass


def process_node_thread(node_id):
    """Maneja la sincronización de UN SOLO nodo de forma independiente."""
    db = SessionLocal()
    req_session = create_sync_client()
    
    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if not node or not node.enabled:
            return

        if node.tipo == 'DRM':
            try:
                # Health check cada poll (~10s)
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

                # Stats cada 3er poll (~30s)
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
                        # Alertar si dispositivos superan umbral
                        if node.drm_total_devices > 50000:
                            logging.warning(f"⚠️ DRM {node.hostname}: {node.drm_total_devices} dispositivos (umbral 50k)")
                        # Alertar usuarios al límite
                        for u in stats.get("users", []):
                            if u.get("activeDevices", 0) >= u.get("maxScreens", 999):
                                logging.warning(f"⚠️ DRM {node.hostname}: usuario {u['userId']} al límite ({u['activeDevices']}/{u['maxScreens']})")
                    except json.JSONDecodeError:
                        logging.warning(f"⚠️ DRM {node.hostname}: /stats devolvió JSON inválido, ignorando stats en este ciclo")
                    except Exception as e:
                        logging.warning(f"⚠️ DRM {node.hostname}: error obteniendo stats: {e}")

                db.commit()
            except Exception as e:
                if node.status != "offline":
                    logging.error(f"🔴 DRM {node.hostname} ({node.ip_address}) OFFLINE. Error: {e}")
                    log_monitor_event(db, "NODE_DOWN", f"DRM {node.hostname} ({node.ip_address}) no responde: {e}", node.id)
                node.status = "offline"
                db.commit()
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
                    health_record.p_cpu_usage = h_data.get("p_cpu_usage", 0)  # <-- NUEVA LÍNEA 22jun26
                    health_record.ram_usage = h_data.get('ram', 0)
                    health_record.gpu_usage = h_data.get('gpu', 0) 
                    health_record.ffmpeg_running = True
                    node.uptime = str(h_data.get('uptime', "00:00:00"))
            except Exception as he:
                logging.warning(f"No se pudo obtener health del nodo {node.hostname}: {he}")

            if node.status != "online":
                logging.info(f"🟢 Nodo {node.hostname} ({node.ip_address}) está ONLINE.")
                log_monitor_event(db, "NODE_UP", f"El servidor {node.hostname} ({node.ip_address}) ha vuelto a responder al orquestador.", node.id)
                node.status = "online"

                # RECOVERY: reiniciar jobs que quedaron en "error" o "stopped" durante el downtime
                recovery_jobs = db.query(models.EncodingJob).filter(
                    models.EncodingJob.node_id == node.id,
                    models.EncodingJob.status.in_(["error", "stopped"])
                ).all()
                # Filtrar: no relanzar canales detenidos manualmente (sin start previo)
                error_jobs = [
                    ej for ej in recovery_jobs
                    if ej.status == "error" or ej.started_at is not None
                ]

                # RECOVERY EXTRA: si el down fue <45s, los jobs quedaron en "running" pero el agente los perdió
                # Verificar jobs "running"/"starting" que no existen en el agente
                running_jobs = db.query(models.EncodingJob).filter(
                    models.EncodingJob.node_id == node.id,
                    models.EncodingJob.status.in_(["running", "starting"])
                ).all()
                if running_jobs:
                    try:
                        resp_agent = req_session.get(f"http://{node.ip_address}:{AGENT_PORT}/jobs/status", timeout=10)
                        if resp_agent.status_code == 200:
                            raw = resp_agent.json()
                            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                                agent_names = {p['name'].lower() for p in raw}
                            else:
                                agent_names = set()
                            for rj in running_jobs:
                                prefix = "pkg" if rj.node.tipo == 'Packager' else "channel"
                                prog = f"{prefix}_{rj.channel.channel_name}_{rj.id}"
                                if prog.lower() not in agent_names:
                                    logging.warning(f"👻 GHOST POST-RESTART: {prog} en BD como 'running' pero no existe en agente — marcando error")
                                    rj.status = "error"
                                    rj.auto_started = False
                                    rj.updated_at = datetime.now()
                                    if rj not in error_jobs:
                                        error_jobs.append(rj)
                    except Exception as e:
                        logging.warning(f"No se pudo verificar procesos del agente en NODE_UP: {e}")

                if error_jobs:
                    logging.warning(f"🔄 RECOVERY: {len(error_jobs)} jobs en estado 'error' en {node.hostname}, intentando relanzar...")
                    for ej in error_jobs:
                        prog_name = f"{'pkg' if node.tipo == 'Packager' else 'channel'}_{ej.channel.channel_name}_{ej.id}"
                        try:
                            if ej.command:
                                compressed = base64.b64encode(zlib.compress(ej.command.encode('utf-8'))).decode('utf-8')
                                payload = {"job_id": ej.id, "channel_name": ej.channel.channel_name, "command": compressed, "autostart": True}
                                resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                                if resp.status_code == 200:
                                    ej.status = "starting"
                                    ej.auto_started = True
                                    ej.started_at = datetime.now()
                                    logging.info(f"  ✅ {prog_name} → starting")
                                else:
                                    logging.warning(f"  ❌ {prog_name} → error {resp.status_code}")
                            else:
                                send_command(ej, "start", req_session)
                                ej.status = "starting"
                                ej.auto_started = True
                                ej.started_at = datetime.now()
                                logging.info(f"  ✅ {prog_name} → starting (start)")
                        except Exception as re:
                            logging.warning(f"  ❌ {prog_name} → exception: {re}")
                    db.commit()
                    log_monitor_event(db, "NODE_RECOVERY", f"Relanzados {len(error_jobs)} jobs en {node.hostname} tras recuperación.", node.id)


            
            node.last_heartbeat = datetime.now()
            
        except httpx.RequestError as e:
            if node.status != "offline":
                logging.error(f"🔴 Nodo {node.hostname} ({node.ip_address}) está OFFLINE. Error: {e}")
                node.status = "offline"
                db.commit() 
                log_monitor_event(db, "NODE_DOWN", f"El servidor {node.hostname} ({node.ip_address}) ha dejado de responder.", node.id)
                
            time_since_last_beat = 46 
            if getattr(node, 'last_heartbeat', None):
                time_since_last_beat = (datetime.now() - node.last_heartbeat).total_seconds()
            
            if time_since_last_beat > 45:
                ghost_jobs = db.query(models.EncodingJob).filter(
                    models.EncodingJob.node_id == node.id,
                    models.EncodingJob.status.in_(['running', 'starting', 'failover'])
                ).all()
                
                if ghost_jobs:
                    logging.warning(f"🧹 Limpiando {len(ghost_jobs)} procesos fantasma en {node.hostname}...")
                    log_monitor_event(db, "GHOST_CLEANUP", f"Limpiando {len(ghost_jobs)} procesos fantasma por caída de {node.hostname}.", node.id)
                    for job in ghost_jobs:
                        job.status = "error"
                        job.auto_started = False
                        job.updated_at = datetime.now()
                        db.add(job)
                        
                        if job.node.tipo == 'Encoder':
                            notify_cms_channel_status(job.channel_id, "error", f"Nodo hardware offline abruptamente: {node.hostname}")

                    db.commit() 
                    if node.tipo == 'Packager':
                        handle_node_failover(db, node, req_session)
            return

        if resp.status_code == 200:
            raw = resp.json()
            # Validar que el agente devolvió una lista de dicts (no strings ni otro formato)
            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                real_processes = raw
            else:
                logging.warning(f"⚠️ Agente {node.hostname} devolvió formato inesperado en /jobs/status: {type(raw).__name__} — se omite sync este ciclo")
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
                    logging.warning(f"👻 ZOMBIE: {prog_name} corre sin permiso.")
                    log_monitor_event(db, "ZOMBIE_DETECTED", f"Proceso {prog_name} corría sin permiso. se asume como RUNNING.", node.id)
                    job.status = "running"
                    # PARCHE: Proteger BD de error de fecha "1969"
                    start_val = real_info.get('start', 0)
                    job.started_at = datetime.fromtimestamp(start_val) if start_val > 0 else datetime.now()
                
                if state == "RUNNING":
                    if real_info and real_info.get('bitrate'): job.current_bitrate = str(real_info['bitrate'])
                    if real_info and real_info.get('fps'): job.current_fps = float(real_info['fps'])

                    if job.status not in ["running", "failover"]:
                        logging.info(f"✅ Sincronizado: {prog_name} en estado RUNNING.")
                        log_monitor_event(db, "PROCESS_SYNCED", f"Proceso {prog_name} paso a estado RUNNING.", node.id)
                        job.status = "running"
                        job.auto_started = False
                        # Resetear estado de errores TS al confirmar running
                        _ts_error_state.pop(job.id, None)
                        _prev_logs.pop(f"{prog_name}_err", None)

                    # if real_info and 'start' in real_info:
                    #     start_ts = real_info.get('start', 0)
                    #     real_start = datetime.fromtimestamp(start_ts) if start_ts > 0 else datetime.now()
                    #     if job.started_at != real_start: job.started_at = real_start

                    # -- 08jun26 corrige problemas de tiempo activo en front
                    if real_info and 'start' in real_info:
                        start_ts = real_info.get('start', 0)
                        
                        if start_ts > 0:
                            # Si el agente envía una fecha real y válida (Systemd o Packager), la usamos
                            real_start = datetime.fromtimestamp(start_ts)
                            if job.started_at != real_start: 
                                job.started_at = real_start
                        else:
                            # Si el agente envía 0, solo asignamos la hora actual UNA VEZ.
                            # Si ya tiene una fecha guardada en la BD, la respetamos y NO la pisamos.
                            if not job.started_at:
                                job.started_at = datetime.now()

                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        check_packager_source_health(db, job, req_session)

                    if node.tipo == 'Encoder':
                        #check_and_heal_children(db, job, req_session)

                        # NUEVO: Monitoreo de errores TS (demux) — escala antes que health_logs
                        # --- DESACTIVADO 26jul26: TS errors y health logs causan stops agresivos ---
                        # is_ts_error = check_encoder_ts_errors(db, job, req_session)
                        # if not is_ts_error:
                        #     is_corrupt = check_encoder_health_logs(db, job, req_session)
                        #     if not is_corrupt:
                        #         check_and_heal_children(db, job, req_session)
                        
                        # NUEVO: Detección de timestamp discontinuity (falla real)
                        if not check_timestamp_discontinuity(db, job, req_session):
                            check_and_heal_children(db, job, req_session)
                        
                        # Monitoreo de drop frames (solo encoders)
                        if job.node.tipo == 'Encoder':
                            check_ffmpeg_drop_frames(db, job, req_session)

                elif state in ["FATAL", "BACKOFF", "EXITED"]:
                    is_failover_triggered = False
                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        is_failover_triggered = check_packager_source_health(db, job, req_session)

                    if not is_failover_triggered:
                        # PARCHE: Damos gracia de 20s en STARTING
                        if job.status == "starting":
                            if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 20:
                                logging.warning(f"🕒 FALLO INICIO: {prog_name}. Reset a ERROR.")
                                job.status = "error"
                                job.auto_started = False
                                job.updated_at = datetime.now()
                                log_monitor_event(db, "PROCESS_START_FAIL", f"Fallo al iniciar {prog_name}.", node.id)
                        
                        # PARCHE: Proteger estado 'stopped' manual
                        elif job.status not in ["error", "failover", "stopped"]:
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            logging.warning(f"⚠️ ERROR: {prog_name} cayó a estado {state}. Marcado en BD.")
                            log_monitor_event(db, "PROCESS_CRASHED", f"El proceso {prog_name} cayó a estado {state}.", node.id)
                            
                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", f"El proceso encoder cayó a estado {state}")

                        else:
                            if job.updated_at and job.status != "failover":
                                elapsed = (datetime.now() - job.updated_at).total_seconds()
                                if elapsed > 60:
                                    # PARCHE: Silenciar spam visual de AUTO_KILL en modo FATAL
                                    if state == "BACKOFF":
                                        logging.error(f"💀 AUTO-KILL: {prog_name} inestable > 60s.")
                                        log_monitor_event(db, "AUTO_KILL", f"Proceso {prog_name} inestable. Auto-detenido.", node.id)
                                    kill_flow_safety(db, job, req_session)

                elif state == "STOPPED":
                    if job.status == "starting":
                        if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 20:
                            logging.warning(f"🕒 FALLO INICIO: {prog_name}. Reset a ERROR.")
                            log_monitor_event(db, "PROCESS_START_FAIL", f"Fallo al intentar iniciar {prog_name}. Tiempo agotado.", node.id)
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            db.commit()
                            
                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", "Fallo al iniciar el proceso del encoder.")

                    # PARCHE: Proteger estado failover de un breve corte en STOPPED
                    elif job.status not in ["stopped", "error", "failover"]:
                        job.status = "stopped"
                        job.started_at = None
                        job.auto_started = False
                        job.updated_at = datetime.now()
                        db.commit()
                        
                        if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "offline", "El encoder fue detenido.")

                # RECOVERY periódico: reintentar jobs en error/stopped cuyo nodo esté activo
                # y que hayan estado corriendo previamente (started_at no None = no stop manual).
                elif job.status in ["error", "stopped"] and job.started_at is not None:
                    last_update = job.updated_at or job.started_at
                    cooldown = 60  # segundos entre reintentos
                    if last_update and (datetime.now() - last_update).total_seconds() > cooldown:
                        logging.info(f"🔄 RECOVERY-RETRY: reintentando {prog_name} ({job.status}) en nodo activo.")
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
                                    logging.info(f"  ✅ {prog_name} → starting (recovery)")
                                else:
                                    job.updated_at = datetime.now()
                                    db.commit()
                                    logging.warning(f"  ❌ {prog_name} → error {resp.status_code}")
                            else:
                                send_command(job, "start", req_session)
                                job.status = "starting"
                                job.auto_started = True
                                job.updated_at = datetime.now()
                                db.commit()
                                logging.info(f"  ✅ {prog_name} → starting (recovery start)")
                        except Exception as re:
                            logging.warning(f"  ❌ {prog_name} recovery exception: {re}")

        db.commit()

    except Exception as e:
        logging.error(f"Error procesando hilo del nodo {node_id}: {e}", exc_info=True)
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
        logging.error(f"Error recuperando nodos de BD: {e}")
        return
    finally:
        db.close()

    if not node_ids: return

    with ThreadPoolExecutor(max_workers=min(20, len(node_ids))) as executor:
        futures = [executor.submit(process_node_thread, nid) for nid in node_ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logging.error(f"Falla fatal en hilo de nodo: {e}")


def handle_node_failover(db, failed_node, req_session):
    if failed_node.tipo == 'Packager': return
    jobs_to_move = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == failed_node.id, models.EncodingJob.status != 'stopped').all()
    if not jobs_to_move: return
    available_nodes = db.query(models.Node).filter(models.Node.tipo == failed_node.tipo, models.Node.enabled == True, models.Node.status == 'online', models.Node.id != failed_node.id).all()
    if not available_nodes: return
    failover_exitoso = False
    for index, job in enumerate(jobs_to_move):
        target_node = available_nodes[index % len(available_nodes)] 
        job.node_id = target_node.id
        job.node = target_node
        job.status = "starting"
        job.auto_started = True 
        db.flush()
        if send_command(job, "start", req_session): failover_exitoso = True
        else: job.status = "error"
    if failover_exitoso:
        db.commit() 
        try: req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=2)
        except Exception: pass


def check_and_heal_children(db, parent_job, req_session):
    if parent_job.status != 'running' or not parent_job.started_at: return
    
    # PARCHE: Absoluto para evitar bugs de NTP (Desfases de horas en Linux)
    uptime = abs((datetime.now() - parent_job.started_at).total_seconds())
    if uptime < 30: return 

    children = db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == parent_job.id).all()

    # for child in children:
    #     channel_name = child.channel.channel_name if child.channel else "Desconocido"

    #     # Sanación clásica estable: Si estaba detenido sin permiso o cayó en error, lo levantamos
    #     if (child.status == 'stopped' and not child.auto_started) or child.status == 'error':
    #         logging.info(f"🚀 AUTO-START/HEAL: Forzando inicio de Packager {child.id} ({channel_name})")
    #         log_monitor_event(db, "AUTO_START", f"Encoder estable. Forzando inicio de Packager {child.id} ({channel_name}).", child.node_id)
    #         child.auto_started = True
    #         child.status = "starting"
    #         db.add(child)
    #         db.commit()

    #         if send_command(child, "start", req_session):
    #             try: req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=10)
    #             except Exception: pass
    #         else:
    #             child.auto_started = False
    #             child.status = "error" 
    #             db.add(child)
    #             db.commit()

    #     elif child.status == 'failover':

    # ----  correccion xxx 09jun26 problemas de restart packager despues de una falla
    for child in children:
        channel_name = child.channel.channel_name if child.channel else "Desconocido"

        # MEJORA: Si el Packager está detenido o en error, el Encoder Padre lo levanta a la fuerza sin importar su historial.
        if child.status in ['stopped', 'error']:
            logging.info(f"🚀 AUTO-START/HEAL: Forzando inicio de Packager {child.id} ({channel_name})")
            log_monitor_event(db, "AUTO_START", f"Encoder estable. Forzando inicio de Packager {child.id} ({channel_name}).", child.node_id)
            child.auto_started = True
            child.status = "starting"
            db.add(child)
            db.commit()

            if send_command(child, "start", req_session):
                try: req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=10)
                except Exception: pass
            else:
                child.auto_started = False
                child.status = "error" 
                db.add(child)
                db.commit()

        elif child.status == 'failover':
            logging.info(f"🚑 AUTO-RESTORE: Restaurando Packager {child.id} ({channel_name}) a la señal principal...")
            log_monitor_event(db, "FAILOVER_RESTORED", f"Encoder principal recuperado. Restaurando Packager {child.id} ({channel_name}).", child.node_id)
            notify_cms_channel_status(child.channel_id, "online", f"Encoder principal de {channel_name} restaurado. Volviendo a señal normal.")
            try:
                res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{child.channel_id}?mode=restore", timeout=30)
                if res.status_code == 200:
                    db.refresh(child)
                    # Verificar que el proceso realmente se reinició en el agente
                    prefix = "pkg" if child.node.tipo == 'Packager' else "channel"
                    prog_name = f"{prefix}_{child.channel.channel_name}_{child.id}"
                    try:
                        verify = req_session.get(f"http://{child.node.ip_address}:{AGENT_PORT}/jobs/status", timeout=5)
                        if verify.status_code == 200:
                            processes = verify.json()
                            for p in processes:
                                if p.get('name', '').lower() == prog_name.lower() and p.get('statename') == 'RUNNING':
                                    logging.info(f"✅ Packager {child.id} ({channel_name}) verificado como RUNNING tras restore.")
                                    break
                            else:
                                logging.warning(f"⚠️ Packager {child.id} ({channel_name}) no está RUNNING tras restore. Estado: {[p.get('statename') for p in processes if p.get('name','').lower() == prog_name.lower()]}")
                    except Exception as ve:
                        logging.warning(f"⚠️ No se pudo verificar estado del packager tras restore: {ve}")
            except Exception as e:
                logging.error(f"⚠️ Error de red restaurando failover: {e}")

        elif child.status == 'running' and child.started_at:
            if parent_job.started_at > (child.started_at + timedelta(seconds=15)):
                logging.info(f"♻️ RE-SYNC: Reiniciando Packager {child.id} ({channel_name}) por desfase con Encoder padre.")
                log_monitor_event(db, "AUTO_RESYNC", f"Reiniciando Packager {child.id} ({channel_name}) por desfase temporal con Encoder.", child.node_id)
                send_command(child, "restart", req_session)
                child.started_at = datetime.now()
                db.add(child)
                db.commit()

def kill_flow_safety(db, job, req_session):
    job.status = "error" 
    job.auto_started = False
    job.updated_at = datetime.now()
    db.add(job)
    send_command(job, "stop", req_session)
    db.commit()

def send_command(job, action, req_session=None):
    try:
        url = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create" if action == "start" else f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control"
        method = req_session if req_session else httpx
        headers = {"X-API-Key": AGENT_API_KEY}
        
        if action == "start":
            payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": job.command_compress, "autostart": True}
            r = method.post(url, json=payload, headers=headers, timeout=30)
            return r.status_code in [200, 201]
        else:
            prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
            prog = f"{prefix}_{job.channel.channel_name}_{job.id}"
            r = method.post(url, params={"action": action, "program_name": prog}, headers=headers, timeout=10)
            return r.status_code == 200
    except Exception:
        return False

_cleanup_counter = 0

if __name__ == "__main__":
    logging.info("⚡ Iniciando Orquestador en modo MULTITHREAD...")
    while True:
        start_time = time.time()
        sync_processes_and_automate()
        duration = time.time() - start_time
        
        # Limpiar cada 60 ciclos (~10 min) logs en memoria de procesos inactivos
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
                for key in list(_prev_logs.keys()):
                    if key not in active_progs:
                        _prev_logs.pop(key, None)
                for key in list(_ts_error_state.keys()):
                    if key not in [j.id for j in jobs]:
                        _ts_error_state.pop(key, None)
                for key in list(_ts_discontinuity_state.keys()):
                    if key not in [j.id for j in jobs]:
                        _ts_discontinuity_state.pop(key, None)
                for key in list(_drop_baseline_state.keys()):
                    if key not in [j.id for j in jobs]:
                        _drop_baseline_state.pop(key, None)
            except Exception:
                pass
            finally:
                db.close()
        
        sleep_time = max(0, POLL_INTERVAL - duration)
        time.sleep(sleep_time)


# ----  fin del archivo ---- #