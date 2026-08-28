from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
import asyncio, json

import models
from database import get_db
from core.deps import templates, get_current_user
from core.logging_service import logger

router = APIRouter(tags=["channels"])


@router.get("/ui/channels", response_class=templates.TemplateResponse)
def channels_inventory(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    channels = db.query(models.Channel).options(joinedload(models.Channel.jobs).joinedload(models.EncodingJob.node)).all()
    for c in channels:
        c.has_encoder, c.has_packager = False, False
        for job in c.jobs:
            if job.node.tipo == 'Encoder':
                c.has_encoder = True
            elif job.node.tipo == 'Packager':
                c.has_packager = True
    return templates.TemplateResponse("channel_list.html", {"request": request, "channels": channels, "user": current_user})


@router.post("/api/analyze-source")
async def analyze_source(ip: str = Form(...), port: int = Form(...), protocol: str = Form(...), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    input_url = f"srt://{ip}:{port}?mode=caller" if protocol == 'srt' else f"{protocol}://@{ip}:{port}"
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_programs", "-show_streams", "-timeout", "5000000", input_url]
    try:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            return JSONResponse({"status": "error", "detail": "Timeout conectando."}, status_code=400)
        data = json.loads(stdout)
        programs = [{"program_id": p.get("program_id"), "pmt_pid": p.get("pmt_pid"), "pcr_pid": p.get("pcr_pid"), "nb_streams": p.get("nb_streams")} for p in data.get("programs", [])]
        streams = [{"index": s.get("index"), "codec_type": s.get("codec_type"), "codec_name": s.get("codec_name"), "id": s.get("id"), "width": s.get("width"), "height": s.get("height"), "language": s.get("tags", {}).get("language", "und")} for s in data.get("streams", [])]
        return JSONResponse({"status": "success", "programs": programs, "streams": streams})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@router.get("/ui/channels/new", response_class=templates.TemplateResponse)
def new_channel_form(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return templates.TemplateResponse("channel_form.html", {"request": request, "user": current_user})


@router.get("/ui/channels/edit/{channel_id}", response_class=templates.TemplateResponse)
def edit_channel_form(channel_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(404, "Canal no encontrado")
    return templates.TemplateResponse("channel_form.html", {"request": request, "channel": channel, "user": current_user})


@router.post("/ui/channels/save")
def save_channel(
    channel_id: int = Form(None), channel_name: str = Form(...), unique_id: str = Form(...),
    origin_multicast_ip: str = Form(...), origin_multicast_port: int = Form(...),
    origin2_multicast_ip: str = Form(""), origin2_multicast_port: int = Form(None),
    input_protocol: str = Form("udp"), program_id: int = Form(0),
    probesize: str = Form("5M"), analyzeduration: str = Form("5M"), fifo_size: int = Form(1000000), buffer_size: int = Form(2000000),
    video_codec: str = Form("libx264"), audio_codec: str = Form("aac"),
    fps_p1: float = Form(30.0), fps_p2: float = Form(30.0), gop_p1: int = Form(60), gop_p2: int = Form(60),
    interlaced: bool = Form(False), burn_subtitles: bool = Form(False), subtitle_pid: int = Form(None),
    audio_mapping: str = Form(""), multicast_ip_out: str = Form(...),
    port_1080p: int = Form(3140), resolution_p1: str = Form("1920x1080"), bitrate_p1: str = Form("6000k"), bitrate_high_max: str = Form("6000k"),
    port_480p: int = Form(3141), bitrate_p2: str = Form("2500k"), bitrate_low_max: str = Form("2500k"), port_audio: int = Form(3142),
    notes: str = Form(""), ruta: str = Form(""),
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    try:
        count_origins = 2 if origin2_multicast_ip and origin2_multicast_port else 1
        if channel_id:
            c = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
            if not c:
                raise HTTPException(404, "Canal no existe")
            c.channel_name, c.unique_id, c.origin_multicast_ip, c.origin_multicast_port = channel_name, unique_id, origin_multicast_ip, origin_multicast_port
            c.origin2_multicast_ip, c.origin2_multicast_port, c.origin_count = origin2_multicast_ip, origin2_multicast_port, count_origins
            c.input_protocol, c.program_id, c.probesize, c.analyzeduration = input_protocol, program_id, probesize, analyzeduration
            c.fifo_size, c.buffer_size, c.video_codec, c.audio_codec = fifo_size, buffer_size, video_codec, audio_codec
            c.fps_p1, c.fps_p2, c.gop_p1, c.gop_p2, c.interlaced = fps_p1, fps_p2, gop_p1, gop_p2, interlaced
            c.burn_subtitles, c.subtitle_pid, c.audio_mapping, c.multicast_ip_out = burn_subtitles, subtitle_pid, audio_mapping, multicast_ip_out
            c.port_1080p, c.resolution_p1, c.bitrate_p1, c.bitrate_high_max = port_1080p, resolution_p1, bitrate_p1, bitrate_high_max
            c.port_480p, c.bitrate_p2, c.bitrate_low_max, c.port_audio = port_480p, bitrate_p2, bitrate_low_max, port_audio
            c.notes, c.ruta = notes, ruta
            logger.info(f"Usuario {current_user.username} actualizó el canal ID {channel_id}")
        else:
            db.add(models.Channel(
                channel_name=channel_name, unique_id=unique_id, origin_multicast_ip=origin_multicast_ip, origin_multicast_port=origin_multicast_port,
                origin2_multicast_ip=origin2_multicast_ip, origin2_multicast_port=origin2_multicast_port, origin_count=count_origins,
                input_protocol=input_protocol, program_id=program_id, probesize=probesize, analyzeduration=analyzeduration,
                fifo_size=fifo_size, buffer_size=buffer_size, video_codec=video_codec, audio_codec=audio_codec, fps_p1=fps_p1, gop_p1=gop_p1,
                interlaced=interlaced, burn_subtitles=burn_subtitles, subtitle_pid=subtitle_pid, audio_mapping=audio_mapping,
                multicast_ip_out=multicast_ip_out, port_1080p=port_1080p, resolution_p1=resolution_p1, bitrate_p1=bitrate_p1, bitrate_high_max=bitrate_high_max,
                port_480p=port_480p, bitrate_p2=bitrate_p2, bitrate_low_max=bitrate_low_max, port_audio=port_audio, notes=notes, ruta=ruta, enabled=True, redundancy_group="default", customer="Mundo"
            ))
            logger.info(f"Usuario {current_user.username} creó el nuevo canal: {channel_name}")
        db.commit()
        return RedirectResponse("/ui/channels", 303)
    except Exception as e:
        db.rollback()
        logger.error(f"Error guardando canal {channel_name}: {e}")
        raise HTTPException(500, detail=str(e))


@router.get("/ui/channels/delete/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        return RedirectResponse("/ui/channels", status_code=303)
    if db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == channel_id).count() > 0:
        raise HTTPException(400, "⛔ Elimine procesos asignados primero.")
    try:
        db.delete(channel)
        db.commit()
        logger.info(f"Usuario {current_user.username} eliminó el canal ID: {channel_id}")
        return RedirectResponse("/ui/channels", status_code=303)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail="Error interno.")
