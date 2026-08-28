from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import httpx

import models
from database import get_db
from core.deps import templates, get_current_user
from core.config import DRM_HEALTH_PORT, KMS_API_URL

router = APIRouter(tags=["drm"])


@router.get("/ui/kms", response_class=templates.TemplateResponse)
def kms_dashboard(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return templates.TemplateResponse("kms_dashboard.html", {"request": request, "user": current_user})


@router.get("/ui/kms/users", response_class=templates.TemplateResponse)
def kms_users(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return templates.TemplateResponse("kms_users.html", {"request": request, "user": current_user})


@router.get("/ui/kms/keys", response_class=templates.TemplateResponse)
def kms_keys(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return templates.TemplateResponse("kms_keys.html", {"request": request, "user": current_user})


@router.get("/ui/kms/logs", response_class=templates.TemplateResponse)
def kms_logs(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return templates.TemplateResponse("kms_logs.html", {"request": request, "user": current_user})


@router.api_route("/api/kms-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def kms_proxy(path: str, request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    if path.startswith("api/auth/login"):
        body = await request.json()
        async with httpx.AsyncClient() as client:
            resp = await client.post(KMS_API_URL + "/" + path, json=body)
            return JSONResponse(resp.json(), resp.status_code)
    url = KMS_API_URL + "/" + path
    async with httpx.AsyncClient() as client:
        if request.method == "GET":
            resp = await client.get(url, params=dict(request.query_params))
        elif request.method == "POST":
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.json()
                resp = await client.post(url, json=body)
            else:
                body = await request.form()
                resp = await client.post(url, data=body)
        elif request.method == "PUT":
            body = await request.json()
            resp = await client.put(url, json=body)
        elif request.method == "DELETE":
            resp = await client.delete(url)
        else:
            resp = {"error": "method not supported"}
        return JSONResponse(resp.json() if isinstance(resp, dict) else resp.json(), resp.status_code if hasattr(resp, "status_code") else 200)


@router.get("/orchestrator/drm-health/{node_id}")
async def drm_health_proxy(node_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(404, "Nodo no encontrado")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{node.ip_address}:{DRM_HEALTH_PORT}/health")
            return resp.json()
    except Exception as e:
        return {"status": "DOWN", "healthy": False, "error": str(e)}


@router.get("/api/drm/stats", response_class=JSONResponse)
def drm_stats(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    drm_nodes = db.query(models.Node).filter(models.Node.tipo == 'DRM', models.Node.enabled == True).all()
    return [{"id": n.id, "hostname": n.hostname, "status": n.status,
             "total_users": n.drm_total_users, "total_devices": n.drm_total_devices,
             "health": n.drm_health_status, "widevine": n.drm_widevine,
             "database": n.drm_database, "last_stats": n.drm_last_stats_at.isoformat() if n.drm_last_stats_at else None} for n in drm_nodes]


@router.get("/api/drm/user/{user_id}")
async def drm_user_stats(user_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    drm_nodes = db.query(models.Node).filter(models.Node.tipo == 'DRM', models.Node.enabled == True).all()
    for node in drm_nodes:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://{node.ip_address}:{DRM_HEALTH_PORT}/stats/user/{user_id}")
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            continue
    raise HTTPException(404, "Usuario no encontrado o DRM no disponible")
