from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from pydantic import BaseModel
import httpx
import atexit

import models
from database import get_db
from core.config import AGENT_API_KEY, VOD_API_PORT, ORCHESTRATOR_WEBHOOK_URL
from core.logging_service import logger
from utils.helpers import verify_cms_token

router = APIRouter()

# HTTP sync client con connection pooling
_http = httpx.Client(
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
)
atexit.register(_http.close)

# --- MODELOS PARA LA API DEL CMS ---
class LockRequest(BaseModel):
    process_id: str

class CMSRecordRequest(BaseModel):
    process_id: str | None = None
    canal: str
    program_start: str
    program_end: str
    output_dir: str
    mode: str = "from_start"
    nombre_mpd: str = "video"

class CMSVodRequest(BaseModel):
    process_id: str | None = None
    canal: str
    epg_start: str
    epg_end: str
    vod_dir: str
    nombre_mpd: str | None = None

class CMSDeleteRequest(BaseModel):
    process_id: str | None = None
    output_dir: str  
    kind: str = "recording"    

@router.get("/api/cms/channels")
def api_cms_get_channels(db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    channels = db.query(models.Channel).options(
        joinedload(models.Channel.jobs).joinedload(models.EncodingJob.node)
    ).all()
    
    canales_list = []
    for ch in channels:
        estado_real = "offline"
        packagers = [job for job in ch.jobs if job.node and job.node.tipo == 'Packager']
        
        if packagers:
            if any(p.status in ['running', 'starting'] for p in packagers):
                estado_real = "online"
            elif any(p.status == 'failover' for p in packagers):
                estado_real = "failover"
            elif any(p.status == 'error' for p in packagers):
                estado_real = "error"
        else:
            encoders = [job for job in ch.jobs if job.node and job.node.tipo == 'Encoder']
            if any(e.status in ['running', 'starting', 'failover'] for e in encoders):
                estado_real = "online_solo_encoder"

        canales_list.append({
            "id": ch.id,
            "nombre_canal": ch.channel_name,
            "numero_canal": ch.unique_id, 
            "ruta": ch.ruta if ch.ruta else "",
            "estado": estado_real
        })
        
    return {
        "status": "success",
        "total": len(canales_list),
        "activos": sum(1 for c in canales_list if c['estado'] in ['online', 'failover']),
        "data": canales_list
    }

@router.post("/api/cms/vod-lock")
def lock_recording(request_data: LockRequest, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    record = db.query(models.Recording).filter(models.Recording.process_id == request_data.process_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
    record.in_use = True
    record.in_use_since = datetime.now()
    db.commit()
    logger.info(f"Grabación {request_data.process_id} PROTEGIDA (En uso).")
    return {"status": "locked", "message": "Protección contra borrado activada."}

@router.post("/api/cms/vod-unlock")
def unlock_recording(request_data: LockRequest, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    record = db.query(models.Recording).filter(models.Recording.process_id == request_data.process_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Grabación no encontrada")
    record.in_use = False
    db.commit()
    logger.info(f"Grabación {request_data.process_id} LIBERADA.")
    return {"status": "unlocked", "message": "Grabación liberada para el ciclo de borrado."}

@router.post("/api/cms/record")
def proxy_cms_record(request_data: CMSRecordRequest, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    if not request_data.process_id:
        raise HTTPException(status_code=400, detail="process_id es estrictamente obligatorio")
    
    logger.info(f"📥 Solicitud REC recibida del CMS. Canal buscado: '{request_data.canal}'")

    existing_record = db.query(models.Recording).filter(models.Recording.process_id == request_data.process_id).first()
    if existing_record:
        raise HTTPException(status_code=409, detail=f"Conflicto: El process_id '{request_data.process_id}' ya existe.")

    canal_nombre = request_data.canal.lower()
    channel = db.query(models.Channel).filter(models.Channel.channel_name == canal_nombre).first()
    if not channel: raise HTTPException(404, detail="Canal no encontrado en BD.")

    packager_job = db.query(models.EncodingJob).join(models.Node).filter(
        models.EncodingJob.channel_id == channel.id, 
        models.Node.tipo == 'Packager',
        models.EncodingJob.status != 'stopped'
    ).first()

    if not packager_job or not packager_job.node: raise HTTPException(400, detail="Canal sin Origin activo.")

    new_record = models.Recording(
        process_id=request_data.process_id,
        canal=canal_nombre,
        node_id=packager_job.node.id,
        status="pending"
    )
    db.add(new_record)
    db.commit()

    origin_ip = packager_job.node.ip_address
    url_vod = f"http://{origin_ip}:{VOD_API_PORT}/vodlive/"
    
    try:
        payload = request_data.dict(exclude_unset=True)
        payload["callback_url"] = ORCHESTRATOR_WEBHOOK_URL
        headers = {"X-API-Key": AGENT_API_KEY}
        resp = _http.post(url_vod, json=payload, headers=headers, timeout=10)
        
        if resp.status_code not in [200, 201]:
            new_record.status = "error"
            db.commit()
            raise HTTPException(status_code=resp.status_code, detail=f"Error remoto: {resp.text}")
            
        logger.info(f"CMS solicitó GRABACIÓN. Registrado con process_id {request_data.process_id}")
        return resp.json()
        
    except httpx.RequestError as e:
        new_record.status = "error"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Error conectando con el Origin: {e}")

@router.post("/api/cms/vod")
def proxy_cms_vod(request_data: CMSVodRequest, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    if not request_data.process_id:
        raise HTTPException(status_code=400, detail="process_id es estrictamente obligatorio")

    logger.info(f"📥 Solicitud REC recibida del CMS. Canal buscado: '{request_data.canal}'")
    
    existing_record = db.query(models.Recording).filter(models.Recording.process_id == request_data.process_id).first()
    if existing_record:
        raise HTTPException(status_code=409, detail=f"Conflicto: El process_id '{request_data.process_id}' ya existe.")

    canal_nombre = request_data.canal.lower()
    channel = db.query(models.Channel).filter(models.Channel.channel_name == canal_nombre).first()
    if not channel: raise HTTPException(status_code=404, detail=f"Canal '{canal_nombre}' no encontrado.")

    packager_job = db.query(models.EncodingJob).join(models.Node).filter(
        models.EncodingJob.channel_id == channel.id, 
        models.Node.tipo == 'Packager',
        models.EncodingJob.status != 'stopped'
    ).first()

    if not packager_job or not packager_job.node:
        raise HTTPException(status_code=400, detail="Este canal no tiene un nodo Packager asignado o activo.")

    new_record = models.Recording(
        process_id=request_data.process_id,
        canal=canal_nombre,
        node_id=packager_job.node.id,
        output_dir=request_data.vod_dir,
        status="pending"
    )
    db.add(new_record)
    db.commit()

    origin_ip = packager_job.node.ip_address
    url_vod = f"http://{origin_ip}:{VOD_API_PORT}/vod/"
    
    try:
        payload = request_data.dict(exclude_unset=True) if hasattr(request_data, 'dict') else request_data.model_dump(exclude_unset=True)
        payload["callback_url"] = ORCHESTRATOR_WEBHOOK_URL
        headers = {"X-API-Key": AGENT_API_KEY}
        resp = _http.post(url_vod, json=payload, headers=headers, timeout=10)
        
        if resp.status_code not in [200, 201]:
            new_record.status = "error"
            db.commit()
            raise HTTPException(status_code=resp.status_code, detail=f"Error remoto Origin: {resp.text}")
            
        logger.info(f"CMS solicitó VOD histórico. Registrado con process_id {request_data.process_id}")
        return resp.json()
        
    except httpx.RequestError as e:
        new_record.status = "error"
        db.commit()
        logger.error(f"Fallo comunicando con VOD API en {origin_ip}: {e}")
        raise HTTPException(status_code=502, detail=f"Error conectando con el Origin {origin_ip}")

@router.post("/api/cms/delete")
def proxy_cms_delete(request_data: CMSDeleteRequest, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
    packager_nodes = db.query(models.Node).filter(
        models.Node.tipo == 'Packager',
        models.Node.status != 'offline'
    ).all()

    if not packager_nodes:
        raise HTTPException(status_code=503, detail="No hay nodos Origin disponibles en este momento.")

    payload = request_data.dict(exclude_unset=True) if hasattr(request_data, 'dict') else request_data.model_dump(exclude_unset=True)
    headers = {"X-API-Key": AGENT_API_KEY}
    respuestas = []

    for node in packager_nodes:
        url_delete = f"http://{node.ip_address}:{VOD_API_PORT}/delete/"
        try:
            _http.post(url_delete, json=payload, headers=headers, timeout=3)
            respuestas.append(f"Orden enviada a {node.hostname}")
        except Exception as e:
            logger.warning(f"No se pudo enviar borrado a {node.hostname} ({node.ip_address}): {e}")

    logger.info(f"CMS solicitó BORRAR carpeta '{request_data.output_dir}'. Broadcast enviado a {len(packager_nodes)} nodos.")
    return {
        "status": "deleting_broadcast", 
        "message": "Orden de borrado enviada a la granja de Origins", 
        "details": respuestas
    }