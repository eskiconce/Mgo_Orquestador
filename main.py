from fastapi import FastAPI, Depends, HTTPException, Request, Form, BackgroundTasks, status, Body, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import cast, Date, or_
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Union
from contextlib import asynccontextmanager
import httpx
import asyncio
import zlib
import base64
import json

# --- Importaciones Modulares ---
import models
from database import get_db, engine
from core.config import *
from core.logging_service import logger
from services import builders
from services import cms_gateway
from services import vod_service
from utils.helpers import time_duration, sync_haproxy_map, task_delayed_action, log_monitor_event

# --- HTTP Client Singleton ---
http_client: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # Startup: crear cliente compartido con connection pooling
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    logger.info("HTTP client started with connection pooling")
    yield
    # Shutdown: cerrar conexiones
    await http_client.aclose()
    logger.info("HTTP client closed")

app = FastAPI(title="MundoGo-Plus Orchestrator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["duration"] = time_duration

# --- Incluir Sub-Módulos (APIs separadas) ---
app.include_router(cms_gateway.router)
app.include_router(vod_service.router)

# ==========================================
# CONFIGURACIÓN DE SEGURIDAD (Auth local)
# ==========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def verify_password(plain_password, hashed_password): return pwd_context.verify(plain_password, hashed_password)
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        if token.startswith("Bearer "): token = token.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 401: return RedirectResponse("/login", status_code=303)
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

# ==========================================
# RUTAS DE LOGIN / LOGOUT
# ==========================================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_action(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        logger.warning(f"Intento de login fallido para: {username}")
        return templates.TemplateResponse("login.html", {"request": {}, "error": "Usuario o contraseña incorrectos"})
    
    logger.info(f"Usuario '{username}' inició sesión.")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response

# ==========================================
# UI: DASHBOARD Y ESTADOS
# ==========================================
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).all() 
    return templates.TemplateResponse("dashboard.html", {"request": request, "nodes": nodes, "user": current_user})

@app.get("/api/nodes/status")
def get_nodes_status(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).all()
    status_list = []
    for n in nodes:
        health = db.query(models.EncoderHealth).filter(models.EncoderHealth.encoder_id == n.id).first()
        status_list.append({
            "id": n.id, "hostname": n.hostname, "status": n.status,
            "cpu": health.cpu_usage if health else 0, "ram": health.ram_usage if health else 0,
            "p_cpu": getattr(health, 'p_cpu_usage', 0) if health else 0,  # <-- NUEVA LÍNEA 22jun26
            "gpu": health.gpu_usage if health else 0, "uptime": getattr(n, 'uptime', "00:00:00")
        })
    return status_list

@app.get("/api/processes/status")
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

@app.get("/api/nodes/{node_id}/health")
async def get_node_health(node_id: int, db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(404, "Nodo no encontrado")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{node.ip_address}:{AGENT_PORT}/health", headers={"X-API-Key": AGENT_API_KEY})
            return resp.json()
    except Exception as e: return {"status": "offline", "error": str(e)}

@app.get("/orchestrator/node-health/{node_id}")
async def get_node_health_proxy(node_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(404, "Nodo no encontrado")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{node.ip_address}:{AGENT_PORT}/health", headers={"X-API-Key": AGENT_API_KEY})
            return resp.json()
    except Exception as e: return {"status": "offline", "error": str(e)}

# ==========================================
# UI: CANALES
# ==========================================
@app.get("/ui/channels", response_class=HTMLResponse)
def channels_inventory(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    channels = db.query(models.Channel).options(joinedload(models.Channel.jobs).joinedload(models.EncodingJob.node)).all()
    for c in channels:
        c.has_encoder, c.has_packager = False, False
        for job in c.jobs:
            if job.node.tipo == 'Encoder': c.has_encoder = True
            elif job.node.tipo == 'Packager': c.has_packager = True
    return templates.TemplateResponse("channel_list.html", {"request": request, "channels": channels, "user": current_user})

@app.post("/api/analyze-source")
async def analyze_source(ip: str = Form(...), port: int = Form(...), protocol: str = Form(...), current_user: models.User = Depends(get_current_user)):
    input_url = f"srt://{ip}:{port}?mode=caller" if protocol == 'srt' else f"{protocol}://@{ip}:{port}"
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_programs", "-show_streams", "-timeout", "5000000", input_url]
    try:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0: return JSONResponse({"status": "error", "detail": "Timeout conectando."}, status_code=400)
        data = json.loads(stdout)
        programs = [{"program_id": p.get("program_id"), "pmt_pid": p.get("pmt_pid"), "pcr_pid": p.get("pcr_pid"), "nb_streams": p.get("nb_streams")} for p in data.get("programs", [])]
        streams = [{"index": s.get("index"), "codec_type": s.get("codec_type"), "codec_name": s.get("codec_name"), "id": s.get("id"), "width": s.get("width"), "height": s.get("height"), "language": s.get("tags", {}).get("language", "und")} for s in data.get("streams", [])]
        return JSONResponse({"status": "success", "programs": programs, "streams": streams})
    except Exception as e: return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@app.get("/ui/channels/new", response_class=HTMLResponse)
def new_channel_form(request: Request, current_user: models.User = Depends(get_current_user)):
    return templates.TemplateResponse("channel_form.html", {"request": request, "user": current_user})

@app.get("/ui/channels/edit/{channel_id}", response_class=HTMLResponse)
def edit_channel_form(channel_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel: raise HTTPException(404, "Canal no encontrado")
    return templates.TemplateResponse("channel_form.html", {"request": request, "channel": channel, "user": current_user})

@app.post("/ui/channels/save")
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
    notes: str = Form(""), ruta: str = Form(""), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    try:
        count_origins = 2 if origin2_multicast_ip and origin2_multicast_port else 1
        if channel_id:
            c = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
            if not c: raise HTTPException(404, "Canal no existe")
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
    except Exception as e: db.rollback(); logger.error(f"Error guardando canal {channel_name}: {e}"); raise HTTPException(500, detail=str(e))

@app.get("/ui/channels/delete/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel: return RedirectResponse("/ui/channels", status_code=303)
    if db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == channel_id).count() > 0: raise HTTPException(400, "⛔ Elimine procesos asignados primero.")
    try:
        db.delete(channel); db.commit()
        logger.info(f"Usuario {current_user.username} eliminó el canal ID: {channel_id}")
        return RedirectResponse("/ui/channels", status_code=303)
    except Exception as e: db.rollback(); raise HTTPException(500, detail="Error interno.")

# ==========================================
# UI: NODOS
# ==========================================
@app.get("/ui/nodes", response_class=HTMLResponse)
def nodes_list(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).all()
    for node in nodes:
        node.job_count = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status.in_(['running', 'starting', 'failover'])).count()
    return templates.TemplateResponse("node_list.html", {"request": request, "nodes": nodes, "user": current_user})

@app.get("/ui/nodes/new", response_class=HTMLResponse)
def new_node_form(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    packagers = db.query(models.Node).filter(models.Node.tipo == 'Packager', models.Node.enabled == True).all()
    return templates.TemplateResponse("node_form.html", {"request": request, "user": current_user, "packagers": packagers})

@app.get("/ui/nodes/edit/{node_id}", response_class=HTMLResponse)
def edit_node_form(node_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node: raise HTTPException(404, "Nodo no encontrado")
    node.job_count = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status.in_(['running', 'starting', 'failover'])).count()
    packagers = db.query(models.Node).filter(models.Node.tipo == 'Packager', models.Node.id != node_id, models.Node.enabled == True).all()
    return templates.TemplateResponse("node_form.html", {"request": request, "node": node, "user": current_user, "packagers": packagers})

@app.post("/ui/nodes/save")
def save_node(
    node_id: int = Form(None), hostname: str = Form(...), ip_address: str = Form(...),
    ip_multicast: str = Form(...), tipo: str = Form(...), enabled: int = Form(0), 
    node_name: str = Form(None), backup_node_id: int = Form(None), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    try:
        is_enabled = True if enabled == 1 else False
        if tipo != 'Packager': node_name, backup_node_id = None, None
        if node_id:
            node = db.query(models.Node).filter(models.Node.id == node_id).first()
            node.hostname, node.ip_address, node.ip_multicast, node.tipo, node.enabled = hostname, ip_address, ip_multicast, tipo, is_enabled
            node.node_name, node.backup_node_id = node_name, backup_node_id if backup_node_id else None
        else:
            db.add(models.Node(hostname=hostname, ip_address=ip_address, ip_multicast=ip_multicast, tipo=tipo, enabled=is_enabled, status="offline", node_name=node_name, backup_node_id=backup_node_id if backup_node_id else None))
        db.commit()
        return RedirectResponse("/ui/nodes", 303)
    except Exception as e: db.rollback(); raise HTTPException(500, detail=str(e))

@app.get("/ui/nodes/delete/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_db)):
    try:
        if db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node_id).count() > 0: raise HTTPException(400, "Nodo tiene procesos asignados.")
        db.query(models.EncoderHealth).filter(models.EncoderHealth.encoder_id == node_id).delete()
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if node: db.delete(node); db.commit()
        return RedirectResponse("/ui/nodes", 303)
    except Exception as e: raise HTTPException(500, detail=str(e))


# ==========================================
# UI: PROCESOS (JOBS)
# ==========================================
class JobCreateSchema(BaseModel):
    channel_id: int
    node_id: int
    command: str | None = None
    create_mirror: bool = True 
    is_drm: bool = False 

@app.get("/ui/processes", response_class=HTMLResponse)
def processes_list(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    jobs = db.query(models.EncodingJob).options(joinedload(models.EncodingJob.channel), joinedload(models.EncodingJob.node)).all()
    nodes = db.query(models.Node).filter(models.Node.enabled == True).all()
    packagers_by_parent = {}
    for j in jobs:
        if j.node and j.node.tipo == 'Packager' and j.parent_job_id:
            packagers_by_parent.setdefault(j.parent_job_id, []).append(j)

    for parent_id, pkgs in packagers_by_parent.items():
        pkgs.sort(key=lambda x: x.id)
        if pkgs: pkgs[0].ha_role = "Principal"
        for p in pkgs[1:]: p.ha_role = "Respaldo"
    return templates.TemplateResponse("process_list.html", {"request": request, "jobs": jobs, "nodes": nodes, "user": current_user})

@app.get("/ui/processes/new", response_class=HTMLResponse)
def new_process_form(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    nodes = db.query(models.Node).filter(models.Node.enabled == True).all()
    available_encoders, packagers = [], []
    for node in nodes:
        node.current_load = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == node.id, models.EncodingJob.status != 'stopped').count()
        if node.tipo == 'Encoder':
            if node.current_load < 30: node.slots_left = 30 - node.current_load; available_encoders.append(node)
        else: packagers.append(node)

    all_channels = db.query(models.Channel).all()
    channels_data = []
    for ch in all_channels:
        e_job = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == ch.id, models.Node.tipo == 'Encoder').first()
        p_job = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == ch.id, models.Node.tipo == 'Packager').first()
        status = "full_completed" if (e_job and p_job) else "ready_for_packager" if e_job else "free"
        if status != "full_completed": channels_data.append({"id": ch.id, "name": ch.channel_name, "status": status})
    return templates.TemplateResponse("process_form.html", {"request": request, "encoders": available_encoders, "packagers": packagers, "channels": channels_data, "user": current_user})

@app.post("/ui/processes/update-command")
def update_process_command(job_id: int = Form(...), command: str = Form(...), is_drm_edit: str = Form(None), db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.status in ['running', 'starting']: raise HTTPException(400, "Detenga el proceso antes.")
    job.command = command
    if job.node and job.node.tipo == 'Packager': job.is_drm = (is_drm_edit == "on")
    job.updated_at = datetime.now()
    db.commit()
    return RedirectResponse("/ui/processes?msg=updated", status_code=303)

@app.post("/orchestrator/create-job") 
def create_job(data: JobCreateSchema, db: Session = Depends(get_db)):
    node = db.query(models.Node).filter(models.Node.id == data.node_id).first()
    if node.tipo == 'Encoder':
        if db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == data.channel_id, models.Node.tipo == 'Encoder').first(): raise HTTPException(400, "Ya existe Encoder.")
        new_job = models.EncodingJob(channel_id=data.channel_id, node_id=node.id, command=data.command or "", status="stopped")
        db.add(new_job); db.commit(); return {"status": "success", "job_id": new_job.id}
    else:
        parent = db.query(models.EncodingJob).join(models.Node).filter(models.EncodingJob.channel_id == data.channel_id, models.Node.tipo == 'Encoder').first()
        if not parent: raise HTTPException(404, "Encoder activo requerido.")
        if db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == data.channel_id, models.EncodingJob.node_id == node.id).first(): raise HTTPException(400, "Packager duplicado en este nodo.")

        main_job = models.EncodingJob(channel_id=data.channel_id, node_id=node.id, command=data.command or "", status="stopped", parent_job_id=parent.id, is_drm=data.is_drm)
        db.add(main_job); db.flush()
        
        created = [main_job.id]
        if data.create_mirror and node.backup_node_id:
            backup_node = db.query(models.Node).filter(models.Node.id == node.backup_node_id).first()
            import re
            b_cmd = re.sub(r'INTERFACE=".*?"', f'INTERFACE="{backup_node.ip_multicast}"', data.command or "") if backup_node and backup_node.ip_multicast else (data.command or "")
            mirror = models.EncodingJob(channel_id=data.channel_id, node_id=node.backup_node_id, command=b_cmd, status="stopped", parent_job_id=parent.id, is_drm=data.is_drm)
            db.add(mirror); db.flush(); created.append(mirror.id)
        db.commit()
        return {"status": "success", "job_id": created[0]}

@app.get("/ui/processes/delete/{job_id}")
def delete_process(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.status == 'running': raise HTTPException(400, "Proceso corriendo.")
    if job.node.tipo == 'Packager' and job.parent_job_id:
        if db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id, models.EncodingJob.status == 'running').first(): raise HTTPException(400, "Encoder padre corriendo.")
    elif job.node.tipo == 'Encoder' and db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).count() > 0: raise HTTPException(400, "Borre los Packagers primero.")
    
    try: requests.delete(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/delete", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": AGENT_API_KEY}, timeout=3)
    except: pass
    db.delete(job); db.commit()
    return RedirectResponse("/ui/processes", 303)

# ==========================================
# ORQUESTACIÓN Y CONTROL REMOTO
# ==========================================
@app.post("/orchestrator/encoder/build")
async def build_encoder_script(data: dict = Body(...), db: Session = Depends(get_db)):
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
    if subtitles and getattr(channel, "subtitle_pid", None): payload["subtitle_pid"] = int(channel.subtitle_pid)

    try:
        resp = await http_client.post("http://172.16.223.10:8000/encoder/build", json=payload, headers={"X-API-Key": AGENT_API_KEY})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Error remoto")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/orchestrator/packager/build")
def build_packager_script(data: dict = Body(...), db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    return {"status": "ok", "script_multiline": builders.generate_packager_bash(channel, node, False)}

@app.post("/orchestrator/packager-drm/build")
def build_packager_drm_script(data: dict = Body(...), db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    return {"status": "ok", "script_multiline": builders.generate_packager_drm_bash(channel, node)}

@app.post("/orchestrator/encoder-linux/build")
def build_encoder_linux_script(data: dict = Body(...), db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    raw_inc = data.get("include_subtitles")
    subs = raw_inc.lower() in ("1", "true") if isinstance(raw_inc, str) else bool(raw_inc) if raw_inc is not None else None
    return {"status": "ok", "script_multiline": builders.generate_linux_encoder_bash(channel, node, include_subtitles=subs)}


# ---- se agrega nueva funcion y boton en el front 11jun26
@app.post("/orchestrator/encoder-mac/build")
def build_encoder_mac_script(data: dict = Body(...), db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == int(data.get("channel_id", 0))).first()
    node = db.query(models.Node).filter(models.Node.id == int(data.get("node_id", 0))).first()
    raw_inc = data.get("include_subtitles")
    subs = raw_inc.lower() in ("1", "true") if isinstance(raw_inc, str) else bool(raw_inc) if raw_inc is not None else None
    return {"status": "ok", "script_multiline": builders.generate_mac_encoder_bash(channel, node, include_subtitles=subs)}

@app.post("/api/internal/trigger-failover/{channel_id}")
async def trigger_failover(channel_id: int, mode: str = "activate", db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    jobs = db.query(models.EncodingJob).filter(models.EncodingJob.channel_id == channel_id, models.EncodingJob.node_id.in_(db.query(models.Node.id).filter(models.Node.tipo == 'Packager'))).all()
    for job in jobs:
        script_bash = builders.generate_packager_bash(channel, job.node, failover=True) if mode == "activate" else (job.command or builders.generate_packager_bash(channel, job.node, failover=False))
        job.status = "failover" if mode == "activate" else "running"
        if mode != "activate": job.command = script_bash
        
        compressed = base64.b64encode(zlib.compress(script_bash.encode('utf-8'))).decode('utf-8')
        prog_name = f"pkg_{channel.channel_name}_{job.id}"
        try:
            await http_client.post(f"http://{job.node.ip_address}:8000/jobs/create", json={"job_id": job.id, "channel_name": channel.channel_name, "command": compressed, "autostart": True}, headers={"X-API-Key": AGENT_API_KEY})
            await http_client.post(f"http://{job.node.ip_address}:8000/jobs/control", params={"action": "restart", "program_name": prog_name}, headers={"X-API-Key": AGENT_API_KEY})
        except Exception:
            pass
    db.commit(); sync_haproxy_map(db)
    return {"status": "done"}

@app.post("/orchestrator/start-job/{job_id}")
def start_process_manual(job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    if job.node.tipo == 'Packager' and job.parent_job_id:
        if db.query(models.EncodingJob).filter(models.EncodingJob.id == job.parent_job_id, models.EncodingJob.status != 'running').first(): raise HTTPException(400, "Encoder padre detenido.")
    
    try:
        response = requests.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create", json={"job_id": job.id, "channel_name": job.channel.channel_name, "command": job.command_compress, "autostart": True}, headers={"X-API-Key": AGENT_API_KEY}, timeout=45)
        if response.status_code != 200: raise HTTPException(status_code=response.status_code, detail=response.text)
        job.status, job.started_at = "running", datetime.now()
    except requests.exceptions.ReadTimeout: job.status, job.started_at = "running", datetime.now()
    except Exception as e:
        job.status = "error"
        db.commit()
        raise HTTPException(502, detail=str(e))

    children = []
    if job.node.tipo == 'Encoder':
        children = db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).all()
        target_data = [{"url": f"http://{c.node.ip_address}:{AGENT_PORT}/jobs/create", "job_id": c.id, "channel_name": c.channel.channel_name, "command": c.command_compress} for c in children]
        for c in children: c.status = "starting"
        if target_data: background_tasks.add_task(task_delayed_action, "create_start", target_data, delay=15)
    db.commit()
    if job.node.tipo == 'Packager' or children: sync_haproxy_map(db)
    return {"status": "success"}

@app.post("/orchestrator/stop-job/{job_id}")
async def stop_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    try:
        await http_client.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control", params={"action": "stop", "program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": AGENT_API_KEY})
    except httpx.HTTPStatusError as e:
        pass
    job.status = "stopped"
    db.commit()
    if job.node.tipo == 'Packager': sync_haproxy_map(db)
    return {"status": "success"}

@app.post("/orchestrator/restart-job/{job_id}")
async def restart_job(job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    try:
        resp = await http_client.post(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control", params={"action": "restart", "program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": AGENT_API_KEY})
        resp.raise_for_status()
        job.started_at = datetime.now()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Error de comunicación")
    
    if job.node.tipo == 'Encoder':
        targets = [{"url": f"http://{c.node.ip_address}:{AGENT_PORT}/jobs/control", "program_name": f"pkg_{c.channel.channel_name}_{c.id}"} for c in db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == job.id).all() if c.status != 'stopped']
        if targets: background_tasks.add_task(task_delayed_action, "restart", targets, delay=15)
    db.commit()
    return {"status": "restarted"}

@app.post("/orchestrator/move-job")
def move_job(job_id: int = Form(...), new_node_id: int = Form(...), db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    new_node = db.query(models.Node).filter(models.Node.id == new_node_id).first()
    if job.status in ["running", "starting"]: raise HTTPException(400, "Detenga el proceso antes.")
    if db.query(models.EncodingJob).filter(models.EncodingJob.node_id == new_node.id, models.EncodingJob.channel_id == job.channel_id).first(): raise HTTPException(400, "Canal ya asignado en nodo destino.")

    try: requests.delete(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/delete", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"}, headers={"X-API-Key": AGENT_API_KEY}, timeout=3)
    except: pass
    job.node_id, job.node = new_node.id, new_node
    db.commit()
    if job.node.tipo == 'Packager': sync_haproxy_map(db)
    return RedirectResponse("/ui/processes?msg=moved", status_code=303)

@app.get("/ui/processes/logs/{job_id}", response_class=HTMLResponse)
def view_process_logs(job_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    p_name = f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"
    logs_err, logs_out = {"content": "Conectando..."}, {"content": "Conectando..."}
    try:
        r_err = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": p_name, "type": "err", "lines": 100}, headers={"X-API-Key": AGENT_API_KEY}, timeout=3)
        if r_err.status_code == 200: logs_err = r_err.json()
        r_out = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": p_name, "type": "out", "lines": 100}, headers={"X-API-Key": AGENT_API_KEY}, timeout=3)
        if r_out.status_code == 200: logs_out = r_out.json()
    except Exception as e: logs_err["content"] = str(e)
    return templates.TemplateResponse("logs_view.html", {"request": request, "job": job, "program_name": p_name, "logs_err": logs_err, "logs_out": logs_out, "user": current_user})

@app.get("/api/processes/logs/{job_id}")
def api_get_process_logs(job_id: int, type: str = "err", lines: int = 100, db: Session = Depends(get_db)):
    job = db.query(models.EncodingJob).filter(models.EncodingJob.id == job_id).first()
    try:
        r = requests.get(f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs", params={"program_name": f"{'pkg' if job.node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}", "type": type, "lines": lines}, headers={"X-API-Key": AGENT_API_KEY}, timeout=3)
        if r.status_code == 200: return r.json()
        return {"content": "Esperando conexión..."}
    except Exception as e: return {"content": str(e)}

# ==========================================
# UI: LOGS VOD Y AUDITORÍA DE SISTEMA
# ==========================================
@app.get("/ui/recordings", response_class=HTMLResponse)
def recordings_list(request: Request, canal: Optional[str] = None, process_id: Optional[str] = None, fecha: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.Recording).options(joinedload(models.Recording.node))
    if not any([canal, process_id, fecha, status]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.Recording.created_at, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")

    if canal: query = query.filter(models.Recording.canal.ilike(f"%{canal}%"))
    if process_id: query = query.filter(models.Recording.process_id.ilike(f"%{process_id}%"))
    if status: query = query.filter(models.Recording.status == status)
    if fecha:
        try: query = query.filter(cast(models.Recording.created_at, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except: pass

    recordings = query.order_by(models.Recording.created_at.desc()).limit(500).all()
    return templates.TemplateResponse("recordings_list.html", {"request": request, "recordings": recordings, "user": current_user, "filters": {"canal": canal or "", "process_id": process_id or "", "fecha": fecha or "", "status": status or ""}})

@app.get("/ui/system-logs", response_class=HTMLResponse)
def system_logs_view(request: Request, level: Optional[str] = None, search: Optional[str] = None, fecha: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.SystemLog)
    if not any([level, search, fecha]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.SystemLog.timestamp, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")

    if level: query = query.filter(models.SystemLog.level == level)
    if search: query = query.filter(models.SystemLog.message.ilike(f"%{search}%"))
    if fecha:
        try: query = query.filter(cast(models.SystemLog.timestamp, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except: pass

    logs = query.order_by(models.SystemLog.timestamp.desc()).limit(1000).all()
    return templates.TemplateResponse("system_logs.html", {"request": request, "logs": logs, "user": current_user, "filters": {"level": level or "", "search": search or "", "fecha": fecha or ""}})



# @app.get("/ui/monitor-logs", response_class=HTMLResponse)
# async def monitor_logs_view(
#     request: Request, 
#     event_type: Optional[str] = None, 
#     search: Optional[str] = None, 
#     fecha: Optional[str] = None, 
#     db: Session = Depends(get_db), 
#     current_user: models.User = Depends(get_current_user)
# ):
#     # Traemos la relación con node para poder mostrar el hostname en la tabla
#     query = db.query(models.MonitorLog).options(joinedload(models.MonitorLog.node))
    
#     # --- Lógica de Carga Inicial (Hoy por defecto) ---
#     if not any([event_type, search, fecha]):
#         hoy = datetime.now().date()
#         query = query.filter(cast(models.MonitorLog.timestamp, Date) == hoy)
#         fecha = hoy.strftime("%Y-%m-%d")

#     # --- Aplicación de Filtros ---
#     if event_type: 
#         query = query.filter(models.MonitorLog.event_type == event_type)
#     if search: 
#         query = query.filter(models.MonitorLog.message.ilike(f"%{search}%"))
#     if fecha:
#         try: 
#             query = query.filter(cast(models.MonitorLog.timestamp, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
#         except: 
#             pass

#     logs = query.order_by(models.MonitorLog.timestamp.desc()).limit(1000).all()
    
#     filters = {"event_type": event_type or "", "search": search or "", "fecha": fecha or ""}
#     return templates.TemplateResponse("monitor_logs.html", {"request": request, "logs": logs, "user": current_user, "filters": filters})

@app.get("/ui/monitor-logs", response_class=HTMLResponse)
def monitor_logs_view(
    request: Request, 
    event_type: Optional[str] = None, 
    search: Optional[str] = None, 
    fecha: Optional[str] = None, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.MonitorLog).options(joinedload(models.MonitorLog.node))
    
    # --- Lógica de Carga Inicial (Hoy por defecto) ---
    if not any([event_type, search, fecha]):
        hoy = datetime.now().date()
        query = query.filter(cast(models.MonitorLog.timestamp, Date) == hoy)
        fecha = hoy.strftime("%Y-%m-%d")

    # --- Aplicación de Filtros ---
    if event_type: 
        query = query.filter(models.MonitorLog.event_type == event_type)
        
    if search: 
        # MAGIA AQUÍ: Unimos la tabla de Nodos y buscamos en el mensaje O en el hostname
        query = query.outerjoin(models.Node).filter(
            or_(
                models.MonitorLog.message.ilike(f"%{search}%"),
                models.Node.hostname.ilike(f"%{search}%")
            )
        )
        
    if fecha:
        try: 
            query = query.filter(cast(models.MonitorLog.timestamp, Date) == datetime.strptime(fecha, "%Y-%m-%d").date())
        except: 
            pass

    logs = query.order_by(models.MonitorLog.timestamp.desc()).limit(1000).all()
    
    filters = {"event_type": event_type or "", "search": search or "", "fecha": fecha or ""}
    return templates.TemplateResponse("monitor_logs.html", {"request": request, "logs": logs, "user": current_user, "filters": filters})    

# ---- fin del archivo ---- #