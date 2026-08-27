from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import Header, HTTPException
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor

import models
from core.config import AGENT_API_KEY, HAPROXY_NODES, HAPROXY_AGENT_PORT
from core.logging_service import logger

def verify_cms_token(x_api_key: str = Header(...)):
    if x_api_key != AGENT_API_KEY:
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
        headers = {"X-API-Key": AGENT_API_KEY}
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
        headers = {"X-API-Key": AGENT_API_KEY}
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
        headers = {"X-API-Key": AGENT_API_KEY}
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

def log_monitor_event(db: Session, event_type: str, message: str, node_id: int = None):
    """
    Guarda un evento del monitor en la base de datos.
    Ej: log_monitor_event(db, "NODE_DOWN", "El nodo Origin_2 no responde al ping", 12)
    """
    try:
        new_alert = models.MonitorLog(
            event_type=event_type,
            message=message,
            node_id=node_id,
            timestamp=datetime.now()
        )
        db.add(new_alert)
        db.commit()
    except Exception as e:
        logger.error(f"Fallo al guardar log del monitor en BD: {e}")