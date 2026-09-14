from fastapi import APIRouter, Depends, HTTPException, Body, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import base64, zlib, httpx, requests

import models
from database import get_db
from core.deps import templates, get_current_user
from core.config import AGENT_PORT, AGENT_API_KEY
from services import builders
from utils.helpers import sync_haproxy_map
from core.logging_service import logger
from routers.orchestrator import analyze_tasks

router = APIRouter(tags=["internal"])


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verifica X-API-Key para endpoints internos."""
    if x_api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")


@router.post("/api/internal/analyze-callback")
async def analyze_callback(data: dict = Body(...), db: Session = Depends(get_db)):
    task_id = data.get("task_id")
    if not task_id or task_id not in analyze_tasks:
        raise HTTPException(404, "Task no encontrada")
    analyze_tasks[task_id]["status"] = "completed"
    analyze_tasks[task_id]["script"] = data.get("script", "")
    analyze_tasks[task_id]["analysis"] = data.get("analysis", {})

    # Guardar historial en BD
    try:
        task_info = analyze_tasks[task_id]
        existing = db.query(models.SignalAnalysis).filter(models.SignalAnalysis.task_id == task_id).first()
        if existing:
            existing.status = "completed"
            existing.script = data.get("script", "")
            existing.analysis = data.get("analysis", {})
            existing.completed_at = datetime.now()
        else:
            record = models.SignalAnalysis(
                channel_id=task_info.get("channel_id"),
                node_id=task_info.get("node_id"),
                task_id=task_id,
                status="completed",
                duration=task_info.get("duration", 300),
                analysis=data.get("analysis", {}),
                script=data.get("script", ""),
                started_at=datetime.fromisoformat(task_info.get("started_at")) if task_info.get("started_at") else None,
                completed_at=datetime.now()
            )
            db.add(record)
        db.commit()
    except Exception as e:
        logger.warning(f"Error guardando historial de análisis: {e}")

    logger.info(f"Análisis completado: task={task_id}")
    return {"status": "ok"}


@router.get("/api/internal/analyze-status/{task_id}")
async def analyze_status(task_id: str, current_user: models.User = Depends(get_current_user)):
    if task_id not in analyze_tasks:
        raise HTTPException(404, "Task no encontrada")
    return analyze_tasks[task_id]


@router.post("/api/internal/trigger-failover/{channel_id}")
async def trigger_failover(channel_id: int, mode: str = "activate", db: Session = Depends(get_db), _: None = Depends(verify_api_key)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    jobs = db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == channel_id, models.EncodingJob.node_id.in_(db.query(models.Node.id).filter(models.Node.tipo == 'Packager'))).all()
    for job in jobs:
        script_bash = builders.generate_packager_bash(channel, job.node, failover=True) if mode == "activate" else (job.command or builders.generate_packager_bash(channel, job.node, failover=False))
        job.status = "failover" if mode == "activate" else "running"
        if mode != "activate":
            job.command = script_bash
        compressed = base64.b64encode(zlib.compress(script_bash.encode('utf-8'))).decode('utf-8')
        prog_name = f"pkg_{channel.channel_name}_{job.id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"http://{job.node.ip_address}:8000/jobs/create", json={"job_id": job.id, "channel_name": channel.channel_name, "command": compressed, "autostart": True}, headers={"X-API-Key": AGENT_API_KEY})
                await client.post(f"http://{job.node.ip_address}:8000/jobs/control", params={"action": "restart", "program_name": prog_name}, headers={"X-API-Key": AGENT_API_KEY})
        except Exception:
            pass
    db.commit()
    sync_haproxy_map(db)
    return {"status": "done"}


@router.post("/api/internal/encoder-restart")
async def notify_encoder_restart(data: dict = Body(...), db: Session = Depends(get_db)):
    """Notificación del encoder cuando reinicia FFmpeg internamente (ej: por discontinuidades)."""
    channel_name = data.get("channel_name")
    reason = data.get("reason", "unknown")
    if not channel_name:
        raise HTTPException(400, "channel_name requerido")

    job = db.query(models.EncodingJob).join(models.Channel).filter(
        models.Channel.channel_name == channel_name,
        models.EncodingJob.status == "running",
        models.EncodingJob.node_id.isnot(None)
    ).first()

    if not job:
        logger.warning(f"encoder-restart: no se encontró job activo para canal {channel_name}")
        return {"status": "no_active_job"}

    job.started_at = datetime.now()
    db.commit()

    log_msg = f"Encoder reiniciado: canal={channel_name}, razón={reason}, job={job.id}"
    logger.info(log_msg)
    try:
        from utils.helpers import log_monitor_event
        log_monitor_event(db, "ENCODER_RESTART", log_msg, job.node_id)
    except Exception:
        pass

    # Reiniciar packager asociado para resincronizar stream
    try:
        packager_job = db.query(models.EncodingJob).filter(
            models.EncodingJob.parent_job_id == job.id,
            models.EncodingJob.status == "running"
        ).first()

        if packager_job and packager_job.node:
            prefix = "pkg"
            prog_name = f"{prefix}_{packager_job.channel.channel_name}_{packager_job.id}"
            url = f"http://{packager_job.node.ip_address}:{AGENT_PORT}/jobs/control"
            resp = requests.post(url, params={"action": "restart", "program_name": prog_name},
                                 headers={"X-API-Key": AGENT_API_KEY}, timeout=10)
            if resp.status_code == 200:
                packager_job.started_at = datetime.now()
                db.commit()
                pkg_msg = f"Packager {packager_job.id} reiniciado tras restart de encoder {channel_name}"
                logger.info(pkg_msg)
                log_monitor_event(db, "PACKAGER_RESTART", pkg_msg, packager_job.node_id)
            else:
                logger.warning(f"Packager restart falló: status={resp.status_code}")
    except Exception as e:
        logger.error(f"Error reiniciando packager tras encoder-restart: {e}")

    return {"status": "ok", "job_id": job.id, "channel_name": channel_name}
