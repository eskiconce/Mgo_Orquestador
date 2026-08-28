from fastapi import APIRouter, Depends, HTTPException, Body, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
import base64, zlib, httpx

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
async def analyze_callback(data: dict = Body(...), _: None = Depends(verify_api_key)):
    task_id = data.get("task_id")
    if not task_id or task_id not in analyze_tasks:
        raise HTTPException(404, "Task no encontrada")
    analyze_tasks[task_id]["status"] = "completed"
    analyze_tasks[task_id]["script"] = data.get("script", "")
    analyze_tasks[task_id]["analysis"] = data.get("analysis", {})
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
