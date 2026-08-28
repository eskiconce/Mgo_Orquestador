from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import cast, Date, or_
from typing import Optional
from datetime import datetime

import models
from database import get_db
from core.deps import templates, get_current_user

router = APIRouter(tags=["ui_logs"])


@router.get("/ui/recordings", response_class=HTMLResponse)
def recordings_list(request: Request, canal: Optional[str] = None, process_id: Optional[str] = None, fecha: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.Recording).options(joinedload(models.Recording.node))
    if not any([canal, process_id, fecha, status]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.Recording.created_at, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")
    if canal:
        query = query.filter(models.Recording.canal.ilike(f"%{canal}%"))
    if process_id:
        query = query.filter(models.Recording.process_id.ilike(f"%{process_id}%"))
    if status:
        query = query.filter(models.Recording.status == status)
    if fecha:
        try:
            query = query.filter(cast(models.Recording.created_at, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except Exception:
            pass
    recordings = query.order_by(models.Recording.created_at.desc()).limit(500).all()
    return templates.TemplateResponse("recordings_list.html", {"request": request, "recordings": recordings, "user": current_user, "filters": {"canal": canal or "", "process_id": process_id or "", "fecha": fecha or "", "status": status or ""}})


@router.get("/ui/system-logs", response_class=HTMLResponse)
def system_logs_view(request: Request, level: Optional[str] = None, search: Optional[str] = None, fecha: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.SystemLog)
    if not any([level, search, fecha]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.SystemLog.timestamp, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")
    if level:
        query = query.filter(models.SystemLog.level == level)
    if search:
        query = query.filter(models.SystemLog.message.ilike(f"%{search}%"))
    if fecha:
        try:
            query = query.filter(cast(models.SystemLog.timestamp, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except Exception:
            pass
    logs = query.order_by(models.SystemLog.timestamp.desc()).limit(1000).all()
    return templates.TemplateResponse("system_logs.html", {"request": request, "logs": logs, "user": current_user, "filters": {"level": level or "", "search": search or "", "fecha": fecha or ""}})


@router.get("/ui/monitor-logs", response_class=HTMLResponse)
def monitor_logs_view(request: Request, event_type: Optional[str] = None, search: Optional[str] = None, fecha: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.MonitorLog).options(joinedload(models.MonitorLog.node))
    if not any([event_type, search, fecha]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.MonitorLog.timestamp, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")
    if event_type:
        query = query.filter(models.MonitorLog.event_type == event_type)
    if search:
        query = query.outerjoin(models.Node).filter(
            or_(
                models.MonitorLog.message.ilike(f"%{search}%"),
                models.Node.hostname.ilike(f"%{search}%")
            )
        )
    if fecha:
        try:
            query = query.filter(cast(models.MonitorLog.timestamp, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except Exception:
            pass
    logs = query.order_by(models.MonitorLog.timestamp.desc()).limit(1000).all()
    filters = {"event_type": event_type or "", "search": search or "", "fecha": fecha or ""}
    return templates.TemplateResponse("monitor_logs.html", {"request": request, "logs": logs, "user": current_user, "filters": filters})
