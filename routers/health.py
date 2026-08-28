"""
Router de salud y métricas del orquestador.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import time

import models
from database import get_db
from core.version import VERSION_STRING

router = APIRouter(tags=["health"])

_start_time = time.time()


@router.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    """Health check completo: versión, DB, uptime, métricas básicas."""
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Check DB
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Conteos
    total_jobs = db.query(models.EncodingJob).count()
    running_jobs = db.query(models.EncodingJob).filter(models.EncodingJob.status == "running").count()
    error_jobs = db.query(models.EncodingJob).filter(models.EncodingJob.status == "error").count()
    total_nodes = db.query(models.Node).count()
    online_nodes = db.query(models.Node).filter(models.Node.status == "online").count()
    total_channels = db.query(models.Channel).count()

    status = "healthy" if db_ok else "degraded"

    return {
        "status": status,
        "version": VERSION_STRING,
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "database": "connected" if db_ok else "disconnected",
        "started_at": datetime.fromtimestamp(_start_time).isoformat(),
        "metrics": {
            "total_nodes": total_nodes,
            "online_nodes": online_nodes,
            "total_channels": total_channels,
            "total_jobs": total_jobs,
            "running_jobs": running_jobs,
            "error_jobs": error_jobs,
        }
    }


@router.get("/api/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe — responde 200 solo si DB está OK."""
    try:
        db.execute(text("SELECT 1"))
        return {"ready": True}
    except Exception:
        return {"ready": False}


@router.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Métricas detalladas del orquestador para observabilidad."""
    uptime_seconds = int(time.time() - _start_time)

    # Jobs por estado
    jobs_by_status = {}
    for status_val in ["running", "stopped", "starting", "error", "failover"]:
        count = db.query(models.EncodingJob).filter(models.EncodingJob.status == status_val).count()
        jobs_by_status[status_val] = count

    # Jobs por tipo de nodo
    jobs_by_type = {"encoder": 0, "packager": 0}
    for job in db.query(models.EncodingJob).all():
        if job.node:
            if job.node.tipo == "Encoder":
                jobs_by_type["encoder"] += 1
            elif job.node.tipo == "Packager":
                jobs_by_type["packager"] += 1

    # Nodos por tipo y estado
    nodes_by_type = {}
    for node in db.query(models.Node).all():
        tipo = node.tipo.lower()
        if tipo not in nodes_by_type:
            nodes_by_type[tipo] = {"total": 0, "online": 0, "offline": 0}
        nodes_by_type[tipo]["total"] += 1
        if node.status == "online":
            nodes_by_type[tipo]["online"] += 1
        elif node.status == "offline":
            nodes_by_type[tipo]["offline"] += 1

    # Canales con/ sin encoder
    channels_with_encoder = 0
    channels_with_packager = 0
    for ch in db.query(models.Channel).all():
        has_enc = db.query(models.EncodingJob).join(models.Node).filter(
            models.EncodingJob.channel_id == ch.id, models.Node.tipo == "Encoder"
        ).count() > 0
        has_pkg = db.query(models.EncodingJob).join(models.Node).filter(
            models.EncodingJob.channel_id == ch.id, models.Node.tipo == "Packager"
        ).count() > 0
        if has_enc:
            channels_with_encoder += 1
        if has_pkg:
            channels_with_packager += 1

    return {
        "uptime_seconds": uptime_seconds,
        "version": VERSION_STRING,
        "jobs": {
            "total": sum(jobs_by_status.values()),
            "by_status": jobs_by_status,
            "by_type": jobs_by_type,
        },
        "nodes": {
            "total": sum(v["total"] for v in nodes_by_type.values()),
            "by_type": nodes_by_type,
        },
        "channels": {
            "total": db.query(models.Channel).count(),
            "with_encoder": channels_with_encoder,
            "with_packager": channels_with_packager,
        }
    }
