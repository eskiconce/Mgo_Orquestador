import time
import requests
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

# Configuración
LOG_FILE = "logs/monitor.log"
AGENT_PORT = 8000
AGENT_API_KEY = "a1b2c3d4e5f67890123456789abcdef0"
POLL_INTERVAL = 10

# CONSTANTE DEL WEBHOOK DEL CMS
CMS_REAL_WEBHOOK = "https://core-dev.mundogo.cl/api/webhook-vod"

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.basicConfig(handlers=[handler], level=logging.INFO)


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
        requests.post(CMS_REAL_WEBHOOK, json=payload, timeout=5)
        
    except Exception as e:
        logging.error(f"⚠️ Error enviando notificación de estado al CMS: {e}")
    finally:
        db.close()

def check_packager_source_health(db, job, req_session):
    """
    1. Verifica si el Encoder Padre murió.
    2. (LAZY LOGGING): Lee logs del Origin SOLO si el bitrate cae críticamente.
    """
    if job.parent_job_id:
        parent = db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id).first()
        if parent and parent.status not in ['running', 'starting']:
            if job.status != "failover":
                logging.warning(f"🚨 ENCODER PADRE SIN SEÑAL (Estado: {parent.status}). Activando Failover para Packager {job.id}...")
                log_monitor_event(db, "FAILOVER_ACTIVATED", f"Encoder padre de {job.channel.channel_name} sin señal. Activando Failover.", job.node_id)
                notify_cms_channel_status(job.channel_id, "failover", f"Encoder padre en estado {parent.status}. Iniciando failover de emergencia.")
                try:
                    res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{job.channel_id}?mode=activate", timeout=30)
                    if res.status_code == 200:
                        logging.info(f"✅ Failover inyectado exitosamente por caída del origen padre.")
                        db.refresh(job) 
                        return True
                except Exception as e:
                    logging.error(f"⚠️ Error de red solicitando Failover: {e}")
            return False

    # --- LAZY LOGGING ---
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
                            logging.info(f"✅ Failover inyectado exitosamente por logs.")
                            db.refresh(job)
                            return True
                    except Exception as e:
                        logging.error(f"⚠️ Error en Failover al Orquestador: {e}")
    except Exception:
        pass 
        
    return False

def process_node_thread(node_id):
    """Maneja la sincronización de UN SOLO nodo de forma independiente."""
    db = SessionLocal()
    req_session = requests.Session()
    req_session.headers.update({"X-API-Key": AGENT_API_KEY})
    
    try:
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if not node or not node.enabled:
            return

        url_jobs = f"http://{node.ip_address}:{AGENT_PORT}/jobs/status"
        url_health = f"http://{node.ip_address}:{AGENT_PORT}/health"
        
        try:
            resp = req_session.get(url_jobs, timeout=5)
            try:
                resp_health = req_session.get(url_health, timeout=3)
                if resp_health.status_code == 200:
                    h_data = resp_health.json()
                    health_record = db.query(models.EncoderHealth).filter_by(encoder_id=node.id).first()
                    if not health_record:
                        health_record = models.EncoderHealth(encoder_id=node.id)
                        db.add(health_record)
                    health_record.reachable = True
                    health_record.cpu_usage = h_data.get('cpu_percent', 0)
                    health_record.ram_usage = h_data.get('ram_percent', 0)
                    health_record.gpu_usage = h_data.get('gpu_percent', 0) 
                    health_record.ffmpeg_running = True
                    node.uptime = str(h_data.get('uptime', "00:00:00"))
            except Exception as he:
                logging.warning(f"No se pudo obtener health del nodo {node.hostname}: {he}")

            if node.status != "online":
                logging.info(f"🟢 Nodo {node.hostname} ({node.ip_address}) está ONLINE.")
                log_monitor_event(db, "NODE_UP", f"El servidor {node.hostname} ({node.ip_address}) ha vuelto a responder al orquestador.", node.id)
                node.status = "online"
            
            node.last_heartbeat = datetime.now()
            
        except requests.exceptions.RequestException as e:
            if node.status != "offline":
                logging.error(f"🔴 Nodo {node.hostname} ({node.ip_address}) está OFFLINE. Error: {e}")
                log_monitor_event(db, "NODE_DOWN", f"El servidor {node.hostname} ({node.ip_address}) ha dejado de responder.", node.id)
                node.status = "offline"
                db.flush() 
                
            time_since_last_beat = 16 
            if getattr(node, 'last_heartbeat', None):
                time_since_last_beat = (datetime.now() - node.last_heartbeat).total_seconds()
            
            if time_since_last_beat > 15:
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
            real_processes = resp.json() 
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
                    log_monitor_event(db, "ZOMBIE_DETECTED", f"Proceso {prog_name} corría sin permiso. Asimilado como RUNNING.", node.id)
                    job.status = "running"
                    job.started_at = datetime.fromtimestamp(real_info['start'])
                
                if state == "RUNNING":
                    if real_info and real_info.get('bitrate'): job.current_bitrate = str(real_info['bitrate'])
                    if real_info and real_info.get('fps'): job.current_fps = float(real_info['fps'])

                    if job.status not in ["running", "failover"]:
                        logging.info(f"✅ Sincronizado: {prog_name} ahora es RUNNING.")
                        job.status = "running"
                        job.auto_started = False

                    if real_info and real_info.get('start'):
                        real_start = datetime.fromtimestamp(real_info['start'])
                        if job.started_at != real_start: job.started_at = real_start

                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        check_packager_source_health(db, job, req_session)

                    if node.tipo == 'Encoder':
                        check_and_heal_children(db, job, req_session)

                elif state in ["FATAL", "BACKOFF", "EXITED"]:
                    is_failover_triggered = False
                    if job.node.tipo == 'Packager' and job.status != 'failover':
                        is_failover_triggered = check_packager_source_health(db, job, req_session)

                    if not is_failover_triggered:
                        if job.status not in ["error", "failover"]:
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            db.commit()
                            logging.warning(f"⚠️ ERROR: {prog_name} cayó a estado {state}. Marcado en BD.")
                            log_monitor_event(db, "PROCESS_CRASHED", f"El proceso {prog_name} cayó a estado {state}.", node.id)
                            
                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", f"El proceso encoder cayó a estado {state}")

                        else:
                            if job.updated_at:
                                elapsed = (datetime.now() - job.updated_at).total_seconds()
                                if elapsed > 60:
                                    logging.error(f"💀 AUTO-KILL: {prog_name} inestable > 60s.")
                                    log_monitor_event(db, "AUTO_KILL", f"Proceso {prog_name} inestable por más de 60s. Auto-detenido por seguridad.", node.id)
                                    kill_flow_safety(db, job, req_session)

                elif state == "STOPPED":
                    if job.status == "starting":
                        if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 15:
                            logging.warning(f"🕒 FALLO INICIO: {prog_name}. Reset a ERROR.")
                            log_monitor_event(db, "PROCESS_START_FAIL", f"Fallo al intentar iniciar {prog_name}. Tiempo agotado.", node.id)
                            job.status = "error"
                            job.auto_started = False
                            job.updated_at = datetime.now()
                            db.commit()
                            
                            if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "error", "Fallo al iniciar el proceso del encoder.")

                    elif job.status not in ["stopped", "error"]:
                        job.status = "stopped"
                        job.started_at = None
                        job.auto_started = False
                        job.updated_at = datetime.now()
                        db.commit()
                        
                        if job.node.tipo == 'Encoder':
                                notify_cms_channel_status(job.channel_id, "offline", "El encoder fue detenido.")

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
    uptime = (datetime.now() - parent_job.started_at).total_seconds()
    if uptime < 30: return 

    children = db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == parent_job.id).all()

    for child in children:
        if child.status == 'stopped' and not child.auto_started:
            logging.info(f"🚀 AUTO-START: Iniciando Packager {child.id}")
            log_monitor_event(db, "AUTO_START", f"Iniciando Packager {child.id} vinculado al Encoder principal.", child.node_id)
            child.auto_started = True
            child.status = "starting"
            db.add(child)
            db.commit()

            if send_command(child, "start", req_session):
                try: req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=5)
                except Exception: pass
            else:
                child.auto_started = False
                child.status = "error" 
                db.add(child)
                db.commit()

        elif child.status == 'failover':
            logging.info(f"🚑 AUTO-RESTORE: Restaurando Packager {child.id} a la señal principal...")
            log_monitor_event(db, "FAILOVER_RESTORED", f"Encoder principal recuperado. Restaurando Packager {child.id} a la señal normal.", child.node_id)
            notify_cms_channel_status(child.channel_id, "online", "Encoder principal restaurado. Volviendo a señal normal.")
            try:
                res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{child.channel_id}?mode=restore", timeout=30)
                if res.status_code == 200:
                    db.refresh(child)
            except Exception as e:
                logging.error(f"⚠️ Error de red restaurando failover: {e}")

        elif child.status == 'running' and child.started_at:
            if parent_job.started_at > (child.started_at + timedelta(seconds=15)):
                logging.info(f"♻️ RE-SYNC: Reiniciando Packager {child.id} por desfase con Encoder padre.")
                log_monitor_event(db, "AUTO_RESYNC", f"Reiniciando Packager {child.id} por desfase temporal con su Encoder padre.", child.node_id)
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
        method = req_session if req_session else requests
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

if __name__ == "__main__":
    logging.info("⚡ Iniciando Orquestador en modo MULTITHREAD...")
    while True:
        start_time = time.time()
        sync_processes_and_automate()
        duration = time.time() - start_time
        
        sleep_time = max(0, POLL_INTERVAL - duration)
        time.sleep(sleep_time)