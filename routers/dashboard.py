from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

import models
from database import get_db
from core.deps import templates, get_current_user
from utils.helpers import time_duration

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=templates.TemplateResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).all()
    channels = db.query(models.Channel).options(joinedload(models.Channel.jobs).joinedload(models.EncodingJob.node)).all()

    nodes_online = sum(1 for n in nodes if n.status == 'online')
    drm_nodes = [n for n in nodes if n.tipo == 'DRM']
    drm_up_count = sum(1 for n in drm_nodes if n.status in ('online', 'degraded'))
    drm_total_users = sum(n.drm_total_users or 0 for n in drm_nodes)
    drm_total_devices = sum(n.drm_total_devices or 0 for n in drm_nodes)
    kms_nodes = [n for n in nodes if n.tipo == 'KMS']
    kms_up_count = sum(1 for n in kms_nodes if n.status == 'online')

    channel_statuses = {"total": 0, "online": 0, "online_solo_encoder": 0, "failover": 0, "error": 0, "offline": 0}
    for ch in channels:
        channel_statuses["total"] += 1
        running = [j for j in ch.jobs if j.status == 'running']
        if not running:
            channel_statuses["offline"] += 1
        elif ch.active_origin == 'backup':
            channel_statuses["failover"] += 1
        elif ch.origin_count and ch.origin_count >= 2:
            channel_statuses["online"] += 1
        else:
            channel_statuses["online_solo_encoder"] += 1

    node_types = set(n.tipo for n in nodes)
    node_summary = {}
    for tipo in node_types:
        t_nodes = [n for n in nodes if n.tipo == tipo]
        node_summary[tipo] = {"total": len(t_nodes), "online": sum(1 for n in t_nodes if n.status == 'online'), "offline": sum(1 for n in t_nodes if n.status == 'offline')}

    jobs = db.query(models.EncodingJob).all()
    job_statuses_enc = {}
    job_statuses_pkg = {}
    for estado in ['running', 'stopped', 'starting', 'error', 'failover']:
        job_statuses_enc[estado] = sum(1 for j in jobs if j.status == estado and j.node.tipo == 'Encoder')
        job_statuses_pkg[estado] = sum(1 for j in jobs if j.status == estado and j.node.tipo == 'Packager')

    recent_events = db.query(models.MonitorLog).order_by(models.MonitorLog.timestamp.desc()).limit(10).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": current_user,
        "nodes": nodes, "nodes_online": nodes_online,
        "drm_nodes": drm_nodes, "drm_up_count": drm_up_count,
        "drm_total_users": drm_total_users, "drm_total_devices": drm_total_devices,
        "kms_nodes": kms_nodes, "kms_up_count": kms_up_count,
        "channel_statuses": channel_statuses,
        "node_summary": node_summary,
        "job_statuses_enc": job_statuses_enc, "job_statuses_pkg": job_statuses_pkg,
        "recent_events": recent_events
    })
