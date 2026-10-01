from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import Header, HTTPException, Depends
from database import get_db
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor

import models
from core.config import HAPROXY_NODES, HAPROXY_AGENT_PORT
from core.logging_service import logger
from services.settings_service import get_api_key

def verify_cms_token(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    import secrets
    from services.settings_service import get_api_key
    if not secrets.compare_digest(x_api_key, get_api_key(db)):
        raise HTTPException(status_code=403, detail="Token de CMS inválido")
    return x_api_key

def time_duration(dt):
    if not dt: return "-"
    now = datetime.now()
    if dt > now: return "Iniciando..."
    delta = now - dt
    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

def sync_haproxy_vod_map(db: Session):
    try:
        ready_records = db.query(models.Recording).filter(models.Recording.status == 'success').all()
        map_lines = []
        for record in ready_records:
            if record.node:
                backend = record.node.node_name if record.node.node_name else "backend_default"
                map_lines.append(f"{record.process_id.strip().lower()} {backend}")

        map_lines.append("default backend_default\n")
        map_content = "\n".join(map_lines)
        headers = {"X-API-Key": get_api_key()}
        payload = {"map_content": map_content}

        for haproxy_ip in HAPROXY_NODES:
            url = f"http://{haproxy_ip}:{HAPROXY_AGENT_PORT}/update-vod-map"
            try:
                with httpx.Client(timeout=2.0) as client:
                    client.post(url, json=payload, headers=headers)
                logger.info(f"✅ Mapa VOD sincronizado en HAProxy {haproxy_ip}")
            except Exception as e:
                logger.warning(f"⚠️ Error sincronizando VOD en HAProxy {haproxy_ip}: {e}")
    except Exception as e:
        logger.error(f"Error generando mapa VOD: {e}")

def _send_to_haproxy(url, payload, headers):
    try:
        with httpx.Client(timeout=2.0) as client:
            client.post(url, json=payload, headers=headers)
        logger.info(f"✅ Mapa de enrutamiento actualizado en HAProxy {url}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo sincronizar HAProxy en {url}: {e}")

def sync_haproxy_map(db: Session):
    try:
        active_jobs = db.query(models.EncodingJob).filter(
            models.EncodingJob.status.in_(['running', 'starting', 'failover'])
        ).all()

        map_lines = []
        for job in active_jobs:
            if job.node and job.node.tipo == 'Packager' and job.channel:
                if job.channel.ruta:
                    canal = job.channel.ruta.strip("/").strip().lower()
                else:
                    canal = job.channel.channel_name.replace(" ", "_").lower()
                
                backend = job.node.node_name if job.node.node_name else "backend_default"
                map_lines.append(f"{canal} {backend}")

        map_lines.append("default backend_default\n")
        map_content = "\n".join(map_lines)
        headers = {"X-API-Key": get_api_key()}
        payload = {"map_content": map_content}

        with ThreadPoolExecutor(max_workers=max(1, len(HAPROXY_NODES))) as executor:
            for haproxy_ip in HAPROXY_NODES:
                url = f"http://{haproxy_ip}:{HAPROXY_AGENT_PORT}/update-map"
                executor.submit(_send_to_haproxy, url, payload, headers)

    except Exception as e:
        logger.error(f"Error generando mapa HAProxy: {e}")

async def task_delayed_action(action: str, targets: list, delay: int = 15):
    logger.info(f"⏳ (Background Async) Esperando {delay}s para acción '{action}' en {len(targets)} hijos...")
    await asyncio.sleep(delay) 
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"X-API-Key": get_api_key()}
        for t in targets:
            try:
                logger.info(f"🚀 (Background Async) Ejecutando {action} en hijo...")
                if action == "create_start":
                    payload = {
                        "job_id": t['job_id'], 
                        "channel_name": t['channel_name'], 
                        "command": t['command'], 
                        "autostart": True
                    }
                    await client.post(t['url'], json=payload, headers=headers)
                else:
                    await client.post(t['url'], params={"action": "restart", "program_name": t['program_name']}, headers=headers)
            except Exception as e:
                logger.error(f"Fallo background task para {t.get('url')}: {e}")

def log_monitor_event(db: Session, event_type: str, message: str, node_id: int = None, timestamp: datetime = None):
    """
    Guarda un evento del monitor en la base de datos.

    NO ejecuta db.commit() (A5): el commit lo hace el call-path (commit final del ciclo,
    commit explícito de la ruta o de la función que notifica). Esto elimina los deadlocks
    MySQL 1213 causados por commits intermedios en cada evento.

    El timestamp se trunca a segundos (A7) para que consola y BD muestren el mismo
    segundo (MySQL DATETIME(0) redondea los microsegundos y desalineaba +1s).
    """
    try:
        ts = timestamp or datetime.now()
        new_alert = models.MonitorLog(
            event_type=event_type,
            message=message,
            node_id=node_id,
            timestamp=ts.replace(microsecond=0)
        )
        db.add(new_alert)
        db.flush()
    except Exception as e:
        logger.error(f"Fallo al guardar log del monitor en BD: {e}")