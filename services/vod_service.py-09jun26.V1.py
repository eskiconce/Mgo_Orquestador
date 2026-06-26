from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel
import requests
import models
from database import get_db
from core.config import AGENT_API_KEY, CMS_REAL_WEBHOOK, ORCHESTRATOR_WEBHOOK_URL, VOD_API_PORT
from core.logging_service import logger
from utils.helpers import sync_haproxy_vod_map, verify_cms_token, log_monitor_event
from fastapi import Request
from typing import Union
from sqlalchemy import or_, and_


router = APIRouter()

# ==========================================
# WEBHOOK VOD (RECEPCIÓN DEL ESTADO DE GRABACIONES)
# ==========================================
@router.post("/api/internal/vod-webhook")
def receive_vod_webhook(payload: dict = Body(...), db: Session = Depends(get_db)):
    process_id = payload.get("process_id")
    status = payload.get("status")  
    event = payload.get("event")    
    
    logger.info(f"Webhook VOD: ID {process_id} | Evento {event} | Estado {status}")
    
    if process_id:
        record = db.query(models.Recording).filter(models.Recording.process_id == process_id).first()
        if record:
            if event in ["recording_deleted", "vod_deleted"]:
                if status == "success":
                    record.status = "deleted" 
                    db.commit()
                    sync_haproxy_vod_map(db) 
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
        respuesta_cms = requests.post(CMS_REAL_WEBHOOK, json=payload, timeout=5)
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
#             headers = {"X-API-Key": AGENT_API_KEY} 

#             try:
#                 requests.post(delete_url, json=payload, headers=headers, timeout=5)
#                 deleted_count += 1
#                 logger.info(f"Orden de borrado enviada a {origin_ip} para proceso {record.process_id}")
#             except Exception as e:
#                 logger.error(f"Error pidiendo borrado a {origin_ip}: {e}")

#     return {"message": f"Se evaluaron registros. Se enviaron {deleted_count} órdenes de borrado."}


# ==========================================
# LIMPIEZA AUTOMÁTICA (BASURERO VOD Y LOGS)
# ==========================================
@router.post("/api/internal/cleanup-vod")
def cleanup_old_vods(db: Session = Depends(get_db)):
    """Basurero Inteligente optimizado por SQL."""
    now = datetime.now()
    cutoff_7_days = now - timedelta(days=7)
    cutoff_31_days = now - timedelta(days=31)
    cutoff_90_days = now - timedelta(days=90)

    # 1. LIMPIEZA DE LOGS DEL SISTEMA (> 3 MESES)
    try:
        deleted_logs = db.query(models.SystemLog).filter(models.SystemLog.timestamp <= cutoff_90_days).delete()
        db.commit()
        if deleted_logs > 0:
            logger.info(f"Rotación de logs: Se eliminaron {deleted_logs} eventos antiguos.")
    except Exception as e:
        logger.error(f"Error rotando logs del sistema: {e}")

    # 2. LIMPIEZA DE CARPETAS VOD (Optimizado)
    deleted_count = 0
    
    # MAGIA AQUÍ: Filtramos directo en la BD. Python solo recibe la basura real.
    records_to_delete = db.query(models.Recording).filter(
        models.Recording.status == 'success',
        or_(
            # Condición A: Más de 7 días y NO en uso (atrapa liberados antiguos inmediatamente)
            and_(models.Recording.created_at <= cutoff_7_days, models.Recording.in_use == False),
            
            # Condición B: Límite duro de 31 días para archivos olvidados en bloqueo
            and_(models.Recording.in_use == True, models.Recording.in_use_since <= cutoff_31_days)
        )
    ).all()

    for record in records_to_delete:
        if not record.node or not record.output_dir: 
            continue
            
        if record.in_use:
            logger.warning(f"¡Límite duro! Forzando borrado de {record.process_id} bloqueado hace más de 31 días.")
            
        origin_ip = record.node.ip_address
        delete_url = f"http://{origin_ip}:{VOD_API_PORT}/delete/"
        payload = {
            "process_id": record.process_id,
            "output_dir": record.output_dir,
            "kind": "recording",
            "callback_url": ORCHESTRATOR_WEBHOOK_URL 
        }
        headers = {"X-API-Key": AGENT_API_KEY} 

        try:
            requests.post(delete_url, json=payload, headers=headers, timeout=5)
            deleted_count += 1
            logger.info(f"Orden de borrado enviada a {origin_ip} para proceso {record.process_id}")
        except Exception as e:
            logger.error(f"Error pidiendo borrado a {origin_ip}: {e}")

    return {"message": f"Se evaluaron registros. Se enviaron {deleted_count} órdenes de borrado."}


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

# --- ENDPOINT RECEPTOR ---
@router.post("/api/alertas/tsmonitor")
def receive_tsmonitor_alert(payload: TSMonitorAlert, db: Session = Depends(get_db)):
    try:
        # 1. Buscar el Canal
        # channel = db.query(models.Channel).filter(
        #     (models.Channel.id == payload.num_canal) | 
        #     (models.Channel.unique_id == str(payload.num_canal))
        # ).first()

        channel = db.query(models.Channel).filter(
            models.Channel.unique_id == str(payload.num_canal)
        ).first()

        if not channel:
            return {"status": "error", "message": f"Canal {payload.numero_canal} no encontrado."}

        # 2. 🛠️ MAGIA: Combinar y parsear la FECHA Y HORA REALES de tsmonitor
        try:
            # Recomienda que tsmonitor envíe formatos estándar (Ej: "2026-05-19" y "15:30:00")
            string_fecha = f"{payload.fecha} {payload.hora}"
            timestamp_real = datetime.strptime(string_fecha, "%Y-%m-%d %H:%M:%S")
        except Exception:
            # Fallback de seguridad: si el formato falla, usamos la hora del servidor
            timestamp_real = datetime.now()

        falla_tipo = payload.status.lower()

        # 3. Guardar en la BD usando la HORA REAL del incidente en origen
        alert_entry = models.MonitorLog(
            event_type="TSMONITOR_ALERT",
            message=f"Alerta externa [{falla_tipo}] para el canal {channel.channel_name}. Reportada por TSMonitor.",
            node_id=None,
            timestamp=timestamp_real  # <-- AQUÍ se guarda el tiempo real enviado
        )
        db.add(alert_entry)
        db.flush() # Obtenemos persistencia temporal antes del commit

        if falla_tipo == "black":
            db.commit()
            return {"status": "success", "message": "Alerta black registrada cronológicamente."}

        # 4. Buscar el trabajo del ENCODER activo
        encoder_job = db.query(models.EncodingJob).join(models.Node).filter(
            models.EncodingJob.channel_id == channel.id,
            models.Node.tipo == 'Encoder'
        ).first()

        if not encoder_job:
            db.commit()
            return {"status": "error", "message": "No hay un nodo Encoder asignado a este canal."}

        agent_ip = encoder_job.node.ip_address
        headers = {"X-API-Key": AGENT_API_KEY}
        agent_port=8005
        prog_name = f"channel_{channel.channel_name}_{encoder_job.id}"

        # 5. LÓGICA DE FALLO (Freeze / Down)
        if falla_tipo in ["freeze", "dead", "down"]:
            if encoder_job.status in ["running", "starting"]:
                try:
                    url_stop = f"http://{agent_ip}:8000/jobs/control"
                    requests.post(url_stop, params={"action": "stop", "program_name": prog_name}, headers=headers, timeout=5)

                    encoder_job.status = "stopped"
                    encoder_job.auto_started = False

                    # Registramos la detención con la misma estampa de tiempo real
                    db.add(models.MonitorLog(
                        event_type="ENCODER_STOPPED",
                        message=f"Encoder de {channel.channel_name} detenido por orden de TSMonitor ({falla_tipo}).",
                        node_id=encoder_job.node_id,
                        timestamp=timestamp_real  # <-- Misma estampa de tiempo
                    ))
                    db.commit()
                    return {"status": "success", "message": "Encoder detenido con estampa de tiempo sincronizada."}
                except Exception as e:
                    db.commit()
                    return {"status": "error", "message": f"Fallo al contactar al Agente Encoder: {e}"}
            else:
                db.commit()
                return {"status": "success", "message": "El Encoder ya se encontraba detenido."}

        # 6. LÓGICA DE RESTAURACIÓN
        elif falla_tipo in ["restore", "ok", "up", "restored"]:
            if encoder_job.status != "running":
                try:
                    url_start = f"http://{agent_ip}:8000/jobs/create"
                    payload_start = {
                        "job_id": encoder_job.id,
                        "channel_name": channel.channel_name,
                        "command": encoder_job.command_compress,
                        "autostart": True
                    }
                    requests.post(url_start, json=payload_start, headers=headers, timeout=10)

                    encoder_job.status = "starting"

                    db.add(models.MonitorLog(
                        event_type="ENCODER_STARTED",
                        message=f"Encoder de {channel.channel_name} restablecido. Señal recuperada en origen.",
                        node_id=encoder_job.node_id,
                        timestamp=timestamp_real  # <-- Misma estampa de tiempo
                    ))
                    db.commit()
                    return {"status": "success", "message": "Encoder reiniciado con estampa de tiempo sincronizada."}
                except Exception as e:
                    db.commit()
                    return {"status": "error", "message": f"Fallo al iniciar el Agente Encoder: {e}"}

        db.commit()
        return {"status": "ignored", "message": f"Falla '{falla_tipo}' no reconocida."}

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}