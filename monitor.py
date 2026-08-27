import time
import httpx
import json
import base64
import zlib
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

_prev_logs = {}

# Configuración
LOG_FILE = "logs/monitor.log"
AGENT_PORT = 8000
DRM_HEALTH_PORT = 8080
AGENT_API_KEY = "a1b2c3d4e5f67890123456789abcdef0"
POLL_INTERVAL = 10

# CONSTANTE DEL WEBHOOK DEL CMS
CMS_REAL_WEBHOOK = "https://core-dev.mundogo.cl/api/webhook-vod"

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_ts_error_state = {}
_drm_stats_counter = {}
_ts_discontinuity_state = {}


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
        last_error = state.get("last_error_seen")
        if last_error and (now - last_error).total_seconds() > 120:
            state["first_seen"] = now
            state["restart_count"] = 0
            state["down_since"] = None
            state["backup_tried"] = False
            state["final_alerted"] = False
            state["stuck_count"] = 0
        state["last_error_seen"] = now

    ts_error_patterns = ["length violation", "Found tag", "PES packet size mismatch", "Packet corrupt"]
    has_ts_error = any(p in log_content for p in ts_error_patterns)

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
    if job.status != 'running' or not job.started_at:
        return False

    uptime = abs((datetime.now() - job.started_at).total_seconds())
    if uptime < 60:
        return False

    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"
    
    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 60}, timeout=5)
        if resp.status_code == 200:
            log_content = resp.json().get("content", "")
            
            error_keywords = [
                "Packet corrupt", 
                "PES packet size mismatch", 
                "co located POCs unavailable", 
                "timestamp discontinuity"
            ]
            
            prev_content = _prev_logs.get(prog_name, "")
            _prev_logs[prog_name] = log_content
            
            prev_lines = prev_content.split('\n')
            curr_lines = log_content.split('\n')
            
            overlap = 0
            for i in range(min(len(prev_lines), len(curr_lines)), 0, -1):
                if prev_lines[-i:] == curr_lines[:i]:
                    overlap = i
                    break
            
            new_lines = curr_lines[overlap:]
            
            error_count = 0
            for line in new_lines:
                if any(keyword in line for keyword in error_keywords):
                    error_count += 1
            
            if len(new_lines) == 0:
                return False
            
            if error_count >= 10:
                logging.warning(f"🚨 CORRUPCIÓN CRÍTICA ({error_count} errores en 60 líneas) en {prog_name}. Forzando reinicio preventivo...")
                log_monitor_event(db, "AUTO_RESTART", f"Corrupción severa de red ({error_count} fallos) en origen de {prog_name}. Reiniciando.", job.node_id)
                
                send_command(job, "restart", req_session)
                
                job.started_at = datetime.now()
                db.add(job)
                db.commit()
                
                notify_cms_channel_status(job.channel_id, "warning", "Reinicio preventivo por corrupción severa de red.")
                return True
                
            elif error_count > 0:
                logging.info(f"⚠️ Micro-corte UDP en {prog_name} ({error_count} errores detectados). El encoder se recuperó, mantenemos en observación.")
                
    except Exception:
        pass 
        
    return False

def check_timestamp_discontinuity(db, job, req_session):
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
        return True
    
    return False

