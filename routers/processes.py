from fastapi import APIRouter, Depends, Form, Request, HTTPException, BackgroundTasks, Body
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from typing import Optional
import requests, re

import models
from database import get_db
from core.deps import templates, get_current_user
from core.config import AGENT_PORT
from services.settings_service import get_api_key
from utils.helpers import time_duration, sync_haproxy_map, task_delayed_action
from core.logging_service import logger

router = APIRouter(tags=["processes"])


class JobCreateSchema(BaseModel):
    channel_id: int
    node_id: int
    command: Optional[str] = None
    create_mirror: bool = True
    is_drm: bool = False


@router.get("/api/processes/status")
def get_processes_status(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    jobs = db.query(models.EncodingJob).all()
    results = []
    for j in jobs:
        results.append({
            "id": j.id, "status": j.status,
            "bitrate": getattr(j, 'current_bitrate', "0 kbps"), "fps": getattr(j, 'current_fps', 0),
            "uptime": time_duration(j.started_at) if getattr(j, 'started_at', None) else "-"
        })
    return results


@router.get("/ui/processes", response_class=templates.TemplateResponse)
def processes_list(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    jobs = db.query(models.EncodingJob).options(joinedload(models.EncodingJob.channel), joinedload(models.EncodingJob.node)).all()
    nodes = db.query(models.Node).filter(models.Node.enabled == True).all()
    packagers_by_parent = {}
    for j in jobs:
        if j.node and j.node.tipo == 'Packager' and j.parent_job_id:
            packagers_by_parent.setdefault(j.parent_job_id, []).append(j)
    for parent_id, pkgs in packagers_by_parent.items():
        pkgs.sort(key=lambda x: x.id)
        if pkgs:
            pkgs[0].ha_role = "Principal"
        for p in pkgs[1:]:
            p.ha_role = "Respaldo"
    return templates.TemplateResponse("process_list.html", {"request": request, "jobs": jobs, "nodes": nodes, "user": current_user})


@router.get("/ui/processes/new", response_class=templates.TemplateResponse)
def new_process_form(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    nodes = db.query(models.Node).filter(models.Node.enabled == True).all()
    available_encoders, packagers = [], []
    for node in nodes:
        node.current_load = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status != 'stopped').count()
        if node.tipo == 'Encoder':
            if node.current_load < 30:
                node.slots_left = 30 - node.current_load
                available_encoders.append(node)
        else:
            packagers.append(node)
    all_channels = db.query(models.Channel).all()
    channels_data = []
    for ch in all_channels:
        e_job = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == ch.id, models.Node.tipo == 'Encoder').first()
        p_job = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == ch.id, models.Node.tipo == 'Packager').first()
        status = "full_completed" if (e_job and p_job) else "ready_for_packager" if e_job else "free"
        if status != "full_completed":
            channels_data.append({"id": ch.id, "name": ch.channel_name, "status": status})
    return templates.TemplateResponse("process_form.html", {"request": request, "encoders": available_encoders, "packagers": packagers, "channels": channels_data, "user": current_user})


@router.post("/ui/processes/update-command")
def update_process_command(job_id: int = Form(...), command: str = Form(...), is_drm_edit: str = Form(None), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.status in ['running', 'starting']:
        raise HTTPException(400, "Detenga el proceso antes.")
    job.command = command
    if job.node and job.node.tipo == 'Packager':
        job.is_drm = (is_drm_edit == "on")
    job.updated_at = __import__("datetime").datetime.now()
    db.commit()
    return RedirectResponse("/ui/processes?msg=updated", status_code=303)


@router.post("/orchestrator/create-job")
def create_job(data: JobCreateSchema, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    node = db.query(models.Node).filter(models.Node.id == data.node_id).first()
    if node.tipo == 'Encoder':
        if db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == data.channel_id, models.Node.tipo == 'Encoder').first():
            raise HTTPException(400, "Ya existe Encoder.")
        new_job = models.EncodingJob(channel_id=data.channel_id, node_id=node.id, command=data.command or "", status="stopped")
        db.add(new_job)
        db.commit()
        return {"status": "success", "job_id": new_job.id}
    else:
        parent = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == data.channel_id, models.Node.tipo == 'Encoder').first()
        if not parent:
            raise HTTPException(404, "Encoder activo requerido.")
        if db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == data.channel_id, models.EncodingJob.node_id == node.id).first():
            raise HTTPException(400, "Packager duplicado en este nodo.")
        main_job = models.EncodingJob(channel_id=data.channel_id, node_id=node.id, command=data.command or "", status="stopped", parent_job_id=parent.id, is_drm=data.is_drm)
        db.add(main_job)
        db.flush()
        created = [main_job.id]
        if data.create_mirror and node.backup_node_id:
            backup_node = db.query(models.Node).filter(models.Node.id == node.backup_node_id).first()
            b_cmd = re.sub(r'INTERFACE=".*?"', f'INTERFACE="{backup_node.ip_multicast}"', data.command or "") if backup_node and backup_node.ip_multicast else (data.command or "")
            mirror = models.EncodingJob(channel_id=data.channel_id, node_id=node.backup_node_id, command=b_cmd, status="stopped", parent_job_id=parent.id, is_drm=data.is_drm)
            db.add(mirror)
            db.flush()
            created.append(mirror.id)
        db.commit()
        return {"status": "success", "job_id": created[0]}


@router.get("/ui/processes/delete/{job_id}")
def delete_process(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.status == 'running':
        raise HTTPException(400, "Proceso corriendo.")
    if job.node.tipo == 'Packager' and job.parent_job_id:
        if db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id, models.EncodingJob.status == 'running').first():
            raise HTTPException(400, "Encoder padre corriendo.")
    elif job.node.tipo == 'Encoder' and db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).count() > 0:
        raise HTTPException(400, "Borre los Packagers primero.")
    try:
        requests.delete(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/delete", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": get_api_key()}, timeout=3)
    except Exception:
        pass
    db.delete(job)
    db.commit()
    return RedirectResponse("/ui/processes", status_code=303)


@router.post("/orchestrator/start-job/{job_id}")
def start_process_manual(job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.node.tipo == 'Packager' and job.parent_job_id:
        if db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id, models.EncodingJob.status != 'running').first():
            raise HTTPException(400, "Encoder padre detenido.")
    try:
        response = requests.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create", json={"job_id": job.id, "channel_name": job.channel.channel_name, "command": job.command_compress, "autostart": True}, headers={"X-API-Key": get_api_key()}, timeout=45)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        job.status, job.started_at = "running", __import__("datetime").datetime.now()
    except requests.exceptions.ReadTimeout:
        job.status, job.started_at = "running", __import__("datetime").datetime.now()
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(502, detail=str(e))
    children = []
    if job.node.tipo == 'Encoder':
        children = db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).all()
        target_data = [{"url": f"http://{c.node.ip_address}:{AGENT_PORT}/jobs/create", "job_id": c.id, "channel_name": c.channel.channel_name, "command": c.command_compress} for c in children]
        for c in children:
            c.status = "starting"
        if target_data:
            background_tasks.add_task(task_delayed_action, "create_start", target_data, delay=15)
    db.commit()
    if job.node.tipo == 'Packager' or children:
        sync_haproxy_map(db)
    return {"status": "success"}


@router.post("/orchestrator/stop-job/{job_id}")
async def stop_job(job_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job is None:
        raise HTTPException(404, "Job no encontrado")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control", params={"action": "stop", "program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": get_api_key()})
        if resp.status_code != 200:
            logger.warning(f"Stop-job {job_id}: agente {job.node.hostname} respondió {resp.status_code} — no se marca 'stopped' en BD")
            raise HTTPException(status_code=502, detail=f"El agente {job.node.hostname} no confirmó la detención (HTTP {resp.status_code}). El job NO fue marcado como detenido.")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Stop-job {job_id}: fallo de comunicación con agente {job.node.hostname}: {e} — no se marca 'stopped' en BD")
        raise HTTPException(502, detail=f"Sin respuesta del agente {job.node.hostname}: {e}. El job NO fue marcado como detenido.")
    job.status = "stopped"
    db.commit()
    if job.node.tipo == 'Packager':
        sync_haproxy_map(db)
    return {"status": "success"}


@router.post("/orchestrator/restart-job/{job_id}")
async def restart_job(job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control", params={"action": "restart", "program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": get_api_key()})
            resp.raise_for_status()
        job.started_at = __import__("datetime").datetime.now()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Error de comunicación")
    if job.node.tipo == 'Encoder':
        targets = [{"url": f"http://{c.node.ip_address}:{AGENT_PORT}/jobs/control", "program_name": f"pkg_{c.channel.channel_name}_{c.id}"} for c in db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).all() if c.status != 'stopped']
        if targets:
            background_tasks.add_task(task_delayed_action, "restart", targets, delay=15)
    db.commit()
    return {"status": "restarted"}


@router.post("/orchestrator/move-job")
def move_job(job_id: int = Form(...), new_node_id: int = Form(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    new_node = db.query(models.Node).filter(models.Node.id == new_node_id).first()
    if job.status in ["running", "starting"]:
        raise HTTPException(400, "Detenga el proceso antes.")
    if db.query(models.EncodingJob).filter(models.EncodingJob.node_id == new_node.id, models.EncodingJob.channel_id == job.channel_id).first():
        raise HTTPException(400, "Canal ya asignado en nodo destino.")
    try:
        requests.delete(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/delete", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": get_api_key()}, timeout=3)
    except Exception:
        pass
    job.node_id, job.node = new_node.id, new_node
    db.commit()
    if job.node.tipo == 'Packager':
        sync_haproxy_map(db)
    return RedirectResponse("/ui/processes?msg=moved", status_code=303)


@router.get("/ui/processes/logs/{job_id}", response_class=HTMLResponse)
def view_process_logs(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    p_name = f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"
    logs_err, logs_out = {"content": "Conectando..."}, {"content": "Conectando..."}
    try:
        r_err = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": p_name, "type": "err", "lines": 100}, headers={"X-API-Key": get_api_key()}, timeout=3)
        if r_err.status_code == 200:
            logs_err = r_err.json()
        r_out = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": p_name, "type": "out", "lines": 100}, headers={"X-API-Key": get_api_key()}, timeout=3)
        if r_out.status_code == 200:
            logs_out = r_out.json()
    except Exception as e:
        logs_err["content"] = str(e)
    return templates.TemplateResponse("logs_view.html", {"request": request, "job": job, "program_name": p_name, "logs_err": logs_err, "logs_out": logs_out, "user": current_user})


@router.get("/api/processes/logs/{job_id}")
def api_get_process_logs(job_id: int, type: str = "err", lines: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    try:
        r = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}", "type": type, "lines": lines}, headers={"X-API-Key": get_api_key()}, timeout=3)
        if r.status_code == 200:
            return r.json()
        return {"content": "Esperando conexión..."}
    except Exception as e:
        return {"content": str(e)}
