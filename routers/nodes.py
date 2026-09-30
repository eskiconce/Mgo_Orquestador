from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import httpx

import models
from database import get_db
from core.deps import templates, get_current_user
from core.config import AGENT_PORT
from services.settings_service import get_api_key

router = APIRouter(tags=["nodes"])


@router.get("/api/nodes/status")
def get_nodes_status(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).all()
    status_list = []
    for n in nodes:
        health = db.query(models.EncoderHealth).filter(models.EncoderHealth.encoder_id == n.id).first()
        status_list.append({
            "id": n.id, "hostname": n.hostname, "status": n.status,
            "cpu": health.cpu_usage if health else 0, "ram": health.ram_usage if health else 0,
            "p_cpu": getattr(health, 'p_cpu_usage', 0) if health else 0,
            "gpu": health.gpu_usage if health else 0, "uptime": getattr(n, 'uptime', "00:00:00")
        })
    return status_list


@router.get("/api/nodes/{node_id}/health")
async def get_node_health(node_id: int, db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Nodo no encontrado")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{node.ip_address}:{AGENT_PORT}/health", headers={"X-API-Key": get_api_key()})
            return resp.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}


@router.get("/orchestrator/node-health/{node_id}")
async def get_node_health_proxy(node_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Nodo no encontrado")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{node.ip_address}:{AGENT_PORT}/health", headers={"X-API-Key": get_api_key()})
            return resp.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}


@router.get("/ui/nodes", response_class=templates.TemplateResponse)
def nodes_list(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    nodes = db.query(models.Node).all()
    for node in nodes:
        node.job_count = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status.in_(['running', 'starting', 'failover'])).count()
    return templates.TemplateResponse("node_list.html", {"request": request, "nodes": nodes, "user": current_user})


@router.get("/ui/nodes/new", response_class=templates.TemplateResponse)
def new_node_form(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    packagers = db.query(models.Node).filter(models.Node.tipo == 'Packager', models.Node.enabled == True).all()
    return templates.TemplateResponse("node_form.html", {"request": request, "user": current_user, "packagers": packagers})


@router.get("/ui/nodes/edit/{node_id}", response_class=templates.TemplateResponse)
def edit_node_form(node_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Nodo no encontrado")
    node.job_count = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status.in_(['running', 'starting', 'failover'])).count()
    packagers = db.query(models.Node).filter(models.Node.tipo == 'Packager', models.Node.id != node_id, models.Node.enabled == True).all()
    return templates.TemplateResponse("node_form.html", {"request": request, "node": node, "user": current_user, "packagers": packagers})


@router.post("/ui/nodes/save")
def save_node(
    node_id: int = Form(None), hostname: str = Form(...), ip_address: str = Form(...),
    ip_multicast: str = Form(...), tipo: str = Form(...), enabled: int = Form(0),
    node_name: str = Form(None), backup_node_id: int = Form(None),
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    try:
        is_enabled = True if enabled == 1 else False
        if tipo != 'Packager':
            node_name, backup_node_id = None, None
        if node_id:
            node = db.query(models.Node).filter(models.Node.id == node_id).first()
            node.hostname, node.ip_address, node.ip_multicast, node.tipo, node.enabled = hostname, ip_address, ip_multicast, tipo, is_enabled
            node.node_name, node.backup_node_id = node_name, backup_node_id if backup_node_id else None
        else:
            db.add(models.Node(hostname=hostname, ip_address=ip_address, ip_multicast=ip_multicast, tipo=tipo, enabled=is_enabled, status="offline", node_name=node_name, backup_node_id=backup_node_id if backup_node_id else None))
        db.commit()
        return RedirectResponse("/ui/nodes", 303)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=str(e))


@router.get("/ui/nodes/delete/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    try:
        if db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node_id).count() > 0:
            raise HTTPException(400, "Nodo tiene procesos asignados.")
        db.query(models.EncoderHealth).filter(models.EncoderHealth.encoder_id == node_id).delete()
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if node:
            db.delete(node)
            db.commit()
        return RedirectResponse("/ui/nodes", 303)
    except Exception as e:
        raise HTTPException(500, detail=str(e))
