from fastapi import APIRouter, Depends, Body, Header, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel
import httpx
import atexit
import secrets
import models
from database import get_db
from core.config import CMS_REAL_WEBHOOK, ORCHESTRATOR_WEBHOOK_URL, VOD_API_PORT
from services.settings_service import get_api_key
from core.logging_service import logger
from utils.helpers import sync_haproxy_vod_map, verify_cms_token, log_monitor_event
from fastapi import Request
from typing import Union
from sqlalchemy import or_, and_


router = APIRouter()

# HTTP sync client con connection pooling
_http = httpx.Client(
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
)
atexit.register(_http.close)

MAX_RETRY = 3

# ==========================================
# WEBHOOK VOD (RECEPCIÓN DEL ESTADO DE GRABACIONES)
# ==========================================
@router.post("/api/internal/vod-webhook")
def receive_vod_webhook(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db)
):
    api_key = request.headers.get("X-API-Key") if request.headers else None
    if api_key and not secrets.compare_digest(api_key, get_api_key(db)):
        logger.warning(f"Webhook VOD con API key invalida desde {request.client.host}")

    process_id = payload.get("process_id")
    status = payload.get("status")
    event = payload.get("event")
    error_msg = payload.get("error", "")

    logger.info(f"Webhook VOD: ID {process_id} | Evento {event} | Estado {status}")

    if process_id:
        record = db.query(models.Recording).filter(models.Recording.process_id == process_id).first()
        if record:
            if event in ["recording_deleted", "vod_deleted"]:
                if status == "success":
                    record.status = "deleted"
                    record.deleted_at = datetime.now()
                    record.retry_count = 0
                    record.last_error = None
                    record.cleanup_started_at = None
                    db.commit()
                    sync_haproxy_vod_map(db)
                else:
                    record.status = 'success'
                    record.cleanup_started_at = None
                    record.retry_count = (record.retry_count or 0) + 1
                    record.last_error = error_msg or status
                    db.commit()
                    logger.warning(f"Error borrando {process_id} en Origin (intento {record.retry_count}/{MAX_RETRY}): {error_msg or status}")
            else:
                record.status = status
                finished_at_str = payload.get("finished_at")
                if finished_at_str:
                    try:
                        record.finished_at = datetime.fromisoformat(finished_at_str)
                    except ValueError as e:
                        logger.warning(f"Error parseando finished_at '{finished_at_str}': {e}")

                db.commit()
                if status == "success":
                    sync_haproxy_vod_map(db)
                
    # Reenviar webhook final al CMS
    try:
        logger.info(f"Reenviando webhook final al CMS: {CMS_REAL_WEBHOOK}")
        respuesta_cms = _http.post(CMS_REAL_WEBHOOK, json=payload, timeout=5)
        if respuesta_cms.status_code in [200, 201, 204]:
            logger.info(f"✅ CMS confirmó recepción correctamente (Status {respuesta_cms.status_code})")
        else:
            logger.warning(f"⚠️ El CMS recibió el webhook pero respondió con error: Status {respuesta_cms.status_code} - {respuesta_cms.text}")
    except Exception as e:
        logger.error(f"❌ Error crítico de red o timeout al intentar contactar al CMS: {e}")

    return {"status": "ok"}

# ==========================================
# RECEPCIÓN DE LOGS REMOTOS (DESDE LOS ORIGINS)
# ==========================================
class RemoteLogPayload(BaseModel):
    hostname: str  # <-- Ahora el agente envía su propio nombre
    level: str
    message: str

# @router.post("/api/internal/remote-logs/{node_id}")
# def receive_remote_logs(node_id: int, payload: RemoteLogPayload, db: Session = Depends(get_db), api_key: str = Depends(verify_cms_token)):
#     node = db.query(models.Node).filter(models.Node.id == node_id).first()
#     node_name = node.hostname if node else f"NODO_{node_id}"
#     try:
#         db.add(models.SystemLog(level=payload.level, message=f"[{node_name}] {payload.message}", timestamp=datetime.now()))
#         db.commit()
#     except: 
#         pass
#     return {"status": "ok"}
@router.post("/api/internal/remote-logs")
def receive_remote_logs(
    payload: RemoteLogPayload, 
    request: Request, 
    db: Session = Depends(get_db), 
    api_key: str = Depends(verify_cms_token)
):
    # 1. Intentamos buscar el nodo en la BD por su hostname
    node = db.query(models.Node).filter(models.Node.hostname == payload.hostname).first()
    
    # 2. Si no existe por hostname, intentamos identificarlo por su IP de red
    if not node:
        client_ip = request.client.host
        node = db.query(models.Node).filter(models.Node.ip_address == client_ip).first()

    # Si aún no existe, lo marcamos como UNREGISTERED para no perder el log
    node_name = node.hostname if node else f"UNREGISTERED_{payload.hostname}"
    
    try:
        db.add(models.SystemLog(
            level=payload.level, 
            message=f"[{node_name}] {payload.message}", 
            timestamp=datetime.now()
        ))
        db.commit()
    except: 
        pass
        
    return {"status": "ok"}

# # ==========================================
# # LIMPIEZA AUTOMÁTICA (BASURERO VOD Y LOGS)
# # ==========================================
# @router.post("/api/internal/cleanup-vod")
# def cleanup_old_vods(db: Session = Depends(get_db)):
#     """Basurero Inteligente con reglas de retención basadas en uso."""
#     now = datetime.now()
#     cutoff_7_days = now - timedelta(days=7)
#     cutoff_31_days = now - timedelta(days=31)
#     cutoff_90_days = now - timedelta(days=90)

#     # 1. LIMPIEZA DE LOGS DEL SISTEMA (> 3 MESES)
#     try:
#         deleted_logs = db.query(models.SystemLog).filter(models.SystemLog.timestamp <= cutoff_90_days).delete()
#         db.commit()
#         if deleted_logs > 0:
#             logger.info(f"Rotación de logs: Se eliminaron {deleted_logs} eventos antiguos.")
#     except Exception as e:
#         logger.error(f"Error rotando logs del sistema: {e}")

#     # 2. LIMPIEZA DE CARPETAS VOD
#     active_records = db.query(models.Recording).filter(models.Recording.status == 'success').all()
#     deleted_count = 0

#     for record in active_records:
#         to_delete = False
#         if record.created_at <= cutoff_7_days and not record.in_use:
#             to_delete = True
#         elif record.in_use and record.in_use_since and record.in_use_since <= cutoff_31_days:
#             to_delete = True
#             logger.warning(f"¡Límite duro! Forzando borrado de {record.process_id} después de 31 días.")

#         if to_delete:
#             if not record.node or not record.output_dir: continue
                
#             origin_ip = record.node.ip_address
#             delete_url = f"http://{origin_ip}:{VOD_API_PORT}/delete/"
#             payload = {
#                 "process_id": record.process_id,
#                 "output_dir": record.output_dir,
#                 "kind": "recording",
#                 "callback_url": ORCHESTRATOR_WEBHOOK_URL 
#             }
#             headers = {"X-API-Key": get_api_key()} 

#             try:
#                 _http.post(delete_url, json=payload, headers=headers, timeout=5)
#                 deleted_count += 1
#                 logger.info(f"Orden de borrado enviada a {origin_ip} para proceso {record.process_id}")
#             except Exception as e:
#                 logger.error(f"Error pidiendo borrado a {origin_ip}: {e}")

#     return {"message": f"Se evaluaron registros. Se enviaron {deleted_count} órdenes de borrado."}


# ==========================================
# LIMPIEZA AUTOMÁTICA (BASURERO VOD Y LOGS)
# ==========================================
# @router.post("/api/internal/cleanup-vod")
# def cleanup_old_vods(db: Session = Depends(get_db)):
#     """Basurero Inteligente optimizado por SQL."""
#     now = datetime.now()
#     cutoff_7_days = now - timedelta(days=7)
#     cutoff_31_days = now - timedelta(days=31)
#     cutoff_90_days = now - timedelta(days=90)

#     # 1. LIMPIEZA DE LOGS DEL SISTEMA (> 3 MESES)
#     try:
#         deleted_logs = db.query(models.SystemLog).filter(models.SystemLog.timestamp <= cutoff_90_days).delete()
#         db.commit()
#         if deleted_logs > 0:
#             logger.info(f"Rotación de logs: Se eliminaron {deleted_logs} eventos antiguos.")
#     except Exception as e:
#         logger.error(f"Error rotando logs del sistema: {e}")

#     # 2. LIMPIEZA DE CARPETAS VOD (Optimizado)
#     deleted_count = 0
    
#     # MAGIA AQUÍ: Filtramos directo en la BD. Python solo recibe la basura real.
#     records_to_delete = db.query(models.Recording).filter(
#         models.Recording.status == 'success',
#         models.Recording.deleted_at == None,  # <--- EL SEGURO DE VIDA 24jun26
#         or_(
#             # Condición A: Más de 7 días y NO en uso (atrapa liberados antiguos inmediatamente)
#             and_(models.Recording.created_at <= cutoff_7_days, models.Recording.in_use == False),
            
#             # Condición B: Límite duro de 31 días para archivos olvidados en bloqueo
#             and_(models.Recording.in_use == True, models.Recording.in_use_since <= cutoff_31_days)
#         )
#     ).all()

#     for record in records_to_delete:
#         if not record.node or not record.output_dir: 
#             continue
            
#         if record.in_use:
#             logger.warning(f"¡Límite duro! Forzando borrado de {record.process_id} bloqueado hace más de 31 días.")
            
#         origin_ip = record.node.ip_address
#         delete_url = f"http://{origin_ip}:{VOD_API_PORT}/delete/"
#         payload = {
#             "process_id": record.process_id,
#             "output_dir": record.output_dir,
#             "kind": "recording",
#             "callback_url": ORCHESTRATOR_WEBHOOK_URL 
#         }
#         headers = {"X-API-Key": get_api_key()} 

#         try:
#             _http.post(delete_url, json=payload, headers=headers, timeout=5)
#             deleted_count += 1
#             logger.info(f"Orden de borrado enviada a {origin_ip} para proceso {record.process_id}")
#         except Exception as e:
#             logger.error(f"Error pidiendo borrado a {origin_ip}: {e}")

#     return {"message": f"Se evaluaron registros. Se enviaron {deleted_count} órdenes de borrado."}

# ---- version nueva 24jun26
# ==========================================
# LIMPIEZA AUTOMÁTICA (BASURERO VOD Y LOGS)
# ==========================================
@router.post("/api/internal/cleanup-vod")
def cleanup_old_vods(db: Session = Depends(get_db)):
    """Basurero Inteligente con estado intermedio 'deleting' y timeout 1h."""
    now = datetime.now()
    cutoff_8_days = now - timedelta(days=8)
    cutoff_31_days = now - timedelta(days=31)
    cutoff_90_days = now - timedelta(days=90)
    stale_lock = now - timedelta(hours=1)
    
    # 1. LIMPIEZA DE LOGS DEL SISTEMA (> 3 MESES)
    try:
        deleted_logs = db.query(models.SystemLog).filter(models.SystemLog.timestamp <= cutoff_90_days).delete()
        db.commit()
        if deleted_logs > 0:
            logger.info(f"Rotación de logs: Se eliminaron {deleted_logs} eventos antiguos.")
    except Exception as e:
        logger.error(f"Error rotando logs del sistema: {e}")

    # 2. RECUPERAR REGISTROS STUCK (cleanup_started_at > 1h sin callback)
    stuck_deleting = db.query(models.Recording).filter(
        models.Recording.status == 'deleting',
        models.Recording.cleanup_started_at <= stale_lock
    ).all()
    for s in stuck_deleting:
        logger.warning(f"Recuperando registro stale en 'deleting' desde {s.cleanup_started_at}: {s.process_id}")
        s.status = 'success'
        s.cleanup_started_at = None
    if stuck_deleting:
        db.commit()

    # 3. LIMPIEZA DE CARPETAS VOD
    sent_count = 0
    error_count = 0
    
    records_to_delete = db.query(models.Recording).filter(
        models.Recording.status == 'success',
        models.Recording.deleted_at == None,
        models.Recording.retry_count < MAX_RETRY,
        or_(
            and_(models.Recording.created_at <= cutoff_8_days, models.Recording.in_use == False),
            and_(models.Recording.in_use == True, models.Recording.in_use_since <= cutoff_31_days)
        )
    ).all()

    for record in records_to_delete:
        if not record.node or not record.output_dir: 
            continue
            
        if record.in_use:
            logger.warning(f"Límite duro: Forzando borrado de {record.process_id} bloqueado hace más de 31 días.")

        retry = record.retry_count or 0
        if retry > 0:
            logger.info(f"Reintento {retry}/{MAX_RETRY} para {record.process_id} (ultimo error: {record.last_error})")

        record.status = 'deleting'
        record.cleanup_started_at = now
        db.commit()

        origin_ip = record.node.ip_address
        delete_url = f"http://{origin_ip}:{VOD_API_PORT}/delete/"
        
        payload = {
            "process_id": record.process_id,
            "output_dir": record.output_dir,
            "kind": "recording",
            "callback_url": ORCHESTRATOR_WEBHOOK_URL 
        }
        headers = {"X-API-Key": get_api_key()} 

        try:
            resp = _http.post(delete_url, json=payload, headers=headers, timeout=10)
            if resp.status_code < 400:
                sent_count += 1
                logger.info(f"Orden de borrado enviada a {origin_ip} para {record.process_id} (status=deleting)")
            else:
                record.status = 'success'
                record.cleanup_started_at = None
                record.retry_count = retry + 1
                record.last_error = f"HTTP {resp.status_code}"
                db.commit()
                error_count += 1
                logger.error(f"Origin {origin_ip} rechazo borrado de {record.process_id}: HTTP {resp.status_code}")
        except Exception as e:
            record.status = 'success'
            record.cleanup_started_at = None
            record.retry_count = retry + 1
            record.last_error = str(e)[:200]
            db.commit()
            error_count += 1
            logger.error(f"Error pidiendo borrado a {origin_ip} para {record.process_id}: {e}")

    # Alertar sobre registros que excedieron max reintentos
    stuck = db.query(models.Recording).filter(
        models.Recording.status == 'success',
        models.Recording.deleted_at == None,
        models.Recording.retry_count >= MAX_RETRY
    ).all()
    for s in stuck:
        logger.warning(f"MAX RETRIES ({MAX_RETRY}) alcanzado para {s.process_id} en {s.node.hostname if s.node else '?'}: {s.last_error}. Requiere intervencion manual.")

    # 4. LIMPIEZA DE REGISTROS ANTIGUOS EN DB (> 90 DÍAS)
    try:
        old_records = db.query(models.Recording).filter(
            models.Recording.created_at <= cutoff_90_days
        ).delete()
        db.commit()
        if old_records > 0:
            logger.info(f"Rotación de grabaciones: Se eliminaron {old_records} registros antiguos (>90 días).")
    except Exception as e:
        logger.error(f"Error rotando grabaciones antiguas: {e}")

    return {
        "message": f"Enviadas: {sent_count}, Errores: {error_count}, Saltados (max_retry): {len(stuck)}"
    }



# ==========================================
# RECEPCION LOG DESDE ORIGINS
# ==========================================

# Schema para validar la estructura exacta que envía el script de bash
class PackagerAlertPayload(BaseModel):
    canal: str
    servidor: str  # Captura el $(hostname) enviado por el nodo
    estado: str
    mensaje: str
    timestamp: str # Viene como cadena 'YYYY-MM-DD HH:MM:SS'

@router.post("/api/alertas/packager")
def receive_packager_alert(payload: PackagerAlertPayload, db: Session = Depends(get_db)):
    try:
        # 1. Autodescubrimiento: Buscamos el nodo por hostname para amarrar el ID relacional
        node = db.query(models.Node).filter(models.Node.hostname == payload.servidor).first()
        node_id = node.id if node else None
        
        # 2. Parseo seguro de la fecha enviada por el bash
        try:
            parsed_time = datetime.strptime(payload.timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            parsed_time = datetime.now()

        # 3. Guardamos el registro histórico puro en la tabla nueva
        new_log = models.PackagerLog(
            timestamp=parsed_time,
            canal=payload.canal,
            node_id=node_id,
            hostname=payload.servidor,
            estado=payload.estado,
            mensaje=payload.mensaje
        )
        db.add(new_log)
        db.commit()
        
        # 4. 🔥 ESTRATEGIA: Replicamos en monitor_logs si el proceso se cayó
        # Así el Front actual de auditoría mostrará la alerta roja de inmediato.
        if payload.estado == "caido":
            db.add(models.MonitorLog(
                timestamp=parsed_time,
                node_id=node_id,
                event_type="PROCESS_CRASHED",
                message=f"❌ PUSH ALERT [{payload.canal.upper()}]: {payload.mensaje}"
            ))
            db.commit()

        return {"status": "success", "detail": "Alerta de empaquetado procesada y sincronizada."}

    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}

# --- SCHEMA PARA TSMONITOR ---
class TSMonitorAlert(BaseModel):
    num_canal: Union[int, str]
    fecha: str
    hora: str
    status: str

# --- ENDPOINT RECEPTOR (v2 — usa motor de reglas) ---
@router.post("/api/alertas/tsmonitor")
def receive_tsmonitor_alert(payload: TSMonitorAlert, db: Session = Depends(get_db)):
    from services.alert_intake import handle_tsmonitor_style_alert, ChannelNotFound
    try:
        return handle_tsmonitor_style_alert(
            db, source="tsmonitor", reporter="TSMonitor",
            event_type="TSMONITOR_ALERT",
            num_canal=payload.num_canal, fecha=payload.fecha,
            hora=payload.hora, status=payload.status,
        )
    except ChannelNotFound as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


# ==========================================
# INGESTA GENÉRICA DE FUENTES REGISTRADAS
# ==========================================

class SourceAlertPayload(BaseModel):
    num_canal: Union[int, str]
    fecha: str
    hora: str
    status: str


@router.post("/api/fuentes/{slug}/alertas")
def receive_source_alert(slug: str, payload: SourceAlertPayload,
                         db: Session = Depends(get_db),
                         x_api_key: Union[str, None] = Header(default=None)):
    """Alerta de fuente registrada en Parámetros Generales (token por fuente)."""
    import secrets as _secrets
    from services.alert_intake import handle_tsmonitor_style_alert, ChannelNotFound

    src = db.query(models.AlertSource).filter(models.AlertSource.slug == slug).first()
    if not src:
        raise HTTPException(status_code=404, detail="Fuente no registrada")
    if not src.enabled:
        raise HTTPException(status_code=403, detail="Fuente deshabilitada")
    if not x_api_key or not _secrets.compare_digest(x_api_key, src.token):
        raise HTTPException(status_code=403, detail="Token de fuente inválido")

    try:
        return handle_tsmonitor_style_alert(
            db, source=slug, reporter=src.name,
            event_type=f"EXT_ALERT_{slug.upper()}",
            num_canal=payload.num_canal, fecha=payload.fecha,
            hora=payload.hora, status=payload.status,
        )
    except ChannelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---- fin de archivo ---- #