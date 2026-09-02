from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
import httpx, datetime

import models
from database import get_db
from core.deps import get_current_user
from core.config import AGENT_PORT, AGENT_API_KEY, KMS_API_URL
from services import builders
from core.logging_service import logger

router = APIRouter(tags=["orchestrator"])

analyze_tasks = {}


@router.post("/orchestrator/encoder/build")
async def build_encoder_script(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    video_codec = str(data.get("video_codec", "h264")).lower().strip()
    subtitles = str(data.get("include_subtitles", "")).lower() in ("1", "true", "yes", "on")
    payload = {
        "in_ip": channel.origin_multicast_ip, "in_port": int(channel.origin_multicast_port),
        "out_ip": channel.multicast_ip_out, "out_port_v1": int(channel.port_1080p),
        "out_port_v2": int(channel.port_480p), "out_port_a": int(channel.port_audio),
        "localaddr": node.ip_multicast, "apply_av_delay": False, "no_preflight": False,
        "include_subtitles": subtitles, "codec": video_codec, "prefer_libx264": (video_codec == "h264"),
        "fps_p1": float(channel.fps_p1 or 60.0), "gop_p1": int(channel.gop_p1 or 120),
        "fps_p2": float(channel.fps_p2 or 30.0), "gop_p2": int(channel.gop_p2 or 60),
        "audio_mapping": channel.audio_mapping or "-map 0:a:0"
    }
    if subtitles and getattr(channel, "subtitle_pid", None):
        payload["subtitle_pid"] = int(channel.subtitle_pid)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("http://172.16.223.10:8000/encoder/build", json=payload, headers={"X-API-Key": AGENT_API_KEY})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Error remoto")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orchestrator/packager/build")
def build_packager_script(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    return {"status": "ok", "script_multiline": builders.generate_packager_bash(channel, node, False)}


@router.post("/orchestrator/packager-drm/build")
def build_packager_drm_script(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    return {"status": "ok", "script_multiline": builders.generate_packager_drm_bash(channel, node)}


@router.post("/orchestrator/rotate-key/{channel_id}")
async def rotate_channel_key(channel_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(404, "Canal no encontrado")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{KMS_API_URL}/api/keys/rotate", json={"channel_id": channel.ruta or channel.channel_name})
            resp.raise_for_status()
            kms_data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"Error rotando llave en KMS: {e}")
    jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.channel_id == channel_id,
        models.EncodingJob.is_drm == True,
        models.EncodingJob.status.in_(["running", "starting", "failover"])
    ).all()
    restarted = []
    for job in jobs:
        try:
            prog = f"pkg_{channel.channel_name}_{job.id}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control",
                    params={"action": "restart", "program_name": prog},
                    headers={"X-API-Key": AGENT_API_KEY})
            job.started_at = datetime.datetime.now()
            restarted.append(job.id)
        except Exception as e:
            logger.warning(f"Rotate key: error reiniciando packager {job.id} ({job.node.hostname}): {e}")
    db.commit()
    logger.info(f"Rotate key canal {channel.channel_name} (id={channel_id}): KID={kms_data.get('kid')}, packagers encontrados={len(jobs)}, reiniciados={restarted}")
    return {"status": "rotated", "kid": kms_data.get("kid"), "key": kms_data.get("key"), "packagers_restarted": restarted}


@router.post("/orchestrator/encoder-linux/build")
def build_encoder_linux_script(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    raw_inc = data.get("include_subtitles")
    subs = raw_inc.lower() in ("1", "true") if isinstance(raw_inc, str) else bool(raw_inc) if raw_inc is not None else None
    return {"status": "ok", "script_multiline": builders.generate_linux_encoder_bash(channel, node, include_subtitles=subs)}


@router.post("/orchestrator/encoder-mac/build")
def build_encoder_mac_script(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    raw_inc = data.get("include_subtitles")
    subs = raw_inc.lower() in ("1", "true") if isinstance(raw_inc, str) else bool(raw_inc) if raw_inc is not None else None
    return {"status": "ok", "script_multiline": builders.generate_mac_encoder_bash(channel, node, include_subtitles=subs)}


@router.post("/orchestrator/encoder/analyze")
async def analyze_encoder_source(data: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    if not channel or not node:
        raise HTTPException(404, "Canal o nodo no encontrado")
    if node.tipo != "Encoder":
        raise HTTPException(400, "El nodo debe ser un Encoder")
    if not channel.origin_multicast_ip or not channel.origin_multicast_port:
        raise HTTPException(400, "El canal no tiene IP de origen configurada")
    source_url = f"udp://{channel.origin_multicast_ip}:{channel.origin_multicast_port}"
    dest_base = channel.multicast_ip_out
    if not dest_base:
        raise HTTPException(400, "El canal no tiene IP multicast de salida configurada")
    duration = int(data.get("duration", 300))
    if duration < 60 or duration > 600:
        raise HTTPException(400, "Duración debe ser entre 60 y 600 segundos")
    task_id = f"analyze_{channel.channel_name}_{node.id}_{int(datetime.datetime.now().timestamp())}"
    analyze_tasks[task_id] = {"status": "pending", "script": "", "analysis": {}, "error": "", "channel_name": channel.channel_name, "channel_id": channel.id, "node_id": node.id, "duration": duration, "started_at": datetime.datetime.now().isoformat()}

    # Guardar registro inicial en BD
    try:
        record = models.SignalAnalysis(
            channel_id=channel.id, node_id=node.id, task_id=task_id,
            status="pending", duration=duration, started_at=datetime.datetime.now()
        )
        db.add(record)
        db.commit()
    except Exception as e:
        logger.warning(f"Error creando registro de análisis: {e}")
    payload = {
        "source_url": source_url, "local_ip": node.ip_multicast, "dest_multicast_base": dest_base,
        "duration": duration, "p1_port": channel.port_1080p, "p4_port": channel.port_480p,
        "burn_subtitles": bool(channel.burn_subtitles),
        "subtitle_pid": channel.subtitle_pid if channel.burn_subtitles else None,
        "service_id": channel.unique_id, "service_name": channel.channel_name,
        "audio_mapping": channel.audio_mapping or "0:a:0",
        "gop_p1": int(channel.gop_p1 or 60), "gop_p2": int(channel.gop_p2 or 60),
        "callback_url": f"http://172.16.223.5:9000/api/internal/analyze-callback",
        "restart_callback_url": f"http://172.16.223.5:9000/api/internal/encoder-restart",
        "task_id": task_id
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"http://{node.ip_address}:{AGENT_PORT}/encoder/analyze", json=payload, headers={"X-API-Key": AGENT_API_KEY})
            if resp.status_code == 202:
                analyze_tasks[task_id]["status"] = "running"
                return {"status": "accepted", "task_id": task_id, "message": "Análisis iniciado en el encoder"}
            else:
                analyze_tasks[task_id]["status"] = "error"
                analyze_tasks[task_id]["error"] = f"Encoder respondió {resp.status_code}"
                return {"status": "error", "task_id": task_id, "error": f"Encoder respondió {resp.status_code}"}
    except Exception as e:
        analyze_tasks[task_id]["status"] = "error"
        analyze_tasks[task_id]["error"] = str(e)
        return {"status": "error", "task_id": task_id, "error": str(e)}
