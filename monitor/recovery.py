"""
Monitor — Recovery module.
Ghost cleanup, node recovery, failover, and child process healing.
"""
import base64
import zlib
import logging
from datetime import datetime, timedelta

import models
from core.config import AGENT_PORT
from core.http_client import create_sync_client
from database import SessionLocal
from utils.helpers import log_monitor_event
from services import builders as bld
from .alerts import notify_cms_channel_status
from .commands import send_command

logger = logging.getLogger(__name__)


def recover_node_jobs(db, node, req_session):
    """Recovery when a node comes back online — relaunch error/stopped jobs."""
    recovery_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(["error", "stopped"])
    ).all()
    error_jobs = [
        ej for ej in recovery_jobs
        if ej.status == "error" or ej.started_at is not None
    ]

    running_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(["running", "starting"])
    ).all()
    if running_jobs:
        try:
            resp_agent = req_session.get(f"http://{node.ip_address}:{AGENT_PORT}/jobs/status", timeout=10)
            if resp_agent.status_code == 200:
                raw = resp_agent.json()
                if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                    agent_names = {p['name'].lower() for p in raw}
                else:
                    agent_names = set()
                for rj in running_jobs:
                    prefix = "pkg" if rj.node.tipo == 'Packager' else "channel"
                    prog = f"{prefix}_{rj.channel.channel_name}_{rj.id}"
                    if prog.lower() not in agent_names:
                        logger.warning(f"👻 GHOST POST-RESTART: {prog} en BD como 'running' pero no existe en agente — marcando error")
                        rj.status = "error"
                        rj.auto_started = False
                        rj.updated_at = datetime.now()
                        if rj not in error_jobs:
                            error_jobs.append(rj)
        except Exception as e:
            logger.warning(f"No se pudo verificar procesos del agente en NODE_UP: {e}")

    if error_jobs:
        logger.warning(f"🔄 RECOVERY: {len(error_jobs)} jobs en estado 'error' en {node.hostname}, intentando relanzar...")
        for ej in error_jobs:
            prog_name = f"{'pkg' if node.tipo == 'Packager' else 'channel'}_{ej.channel.channel_name}_{ej.id}"
            try:
                if ej.command:
                    compressed = base64.b64encode(zlib.compress(ej.command.encode('utf-8'))).decode('utf-8')
                    payload = {"job_id": ej.id, "channel_name": ej.channel.channel_name, "command": compressed, "autostart": True}
                    resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                    if resp.status_code == 200:
                        ej.status = "starting"
                        ej.auto_started = True
                        ej.started_at = datetime.now()
                        logger.info(f"  ✅ {prog_name} → starting")
                    else:
                        logger.warning(f"  ❌ {prog_name} → error {resp.status_code}")
                else:
                    send_command(ej, "start", req_session)
                    ej.status = "starting"
                    ej.auto_started = True
                    ej.started_at = datetime.now()
                    logger.info(f"  ✅ {prog_name} → starting (start)")
            except Exception as re:
                logger.warning(f"  ❌ {prog_name} → exception: {re}")
        log_monitor_event(db, "NODE_RECOVERY", f"Relanzados {len(error_jobs)} jobs en {node.hostname} tras recuperación.", node.id)
        db.commit()


def cleanup_ghost_jobs(db, node, req_session):
    """Clean up ghost jobs when a node goes offline."""
    ghost_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(['running', 'starting', 'failover'])
    ).all()

    if ghost_jobs:
        logger.warning(f"🧹 Limpiando {len(ghost_jobs)} procesos fantasma en {node.hostname}...")
        log_monitor_event(db, "GHOST_CLEANUP", f"Limpiando {len(ghost_jobs)} procesos fantasma por caída de {node.hostname}.", node.id)
        for job in ghost_jobs:
            job.status = "error"
            job.auto_started = False
            job.updated_at = datetime.now()
            db.add(job)

            if job.node.tipo == 'Encoder':
                notify_cms_channel_status(job.channel_id, "error", f"Nodo hardware offline abruptamente: {node.hostname}")

        db.commit()
        if node.tipo == 'Packager':
            handle_node_failover(db, node, req_session)


def handle_node_failover(db, failed_node, req_session):
    if failed_node.tipo == 'Packager':
        return
    jobs_to_move = db.query(models.EncodingJob).filter(models.EncodingJob.node_id == failed_node.id, models.EncodingJob.status != 'stopped').all()
    if not jobs_to_move:
        return
    available_nodes = db.query(models.Node).filter(models.Node.tipo == failed_node.tipo, models.Node.enabled == True, models.Node.status == 'online', models.Node.id != failed_node.id).all()
    if not available_nodes:
        return
    failover_exitoso = False
    for index, job in enumerate(jobs_to_move):
        target_node = available_nodes[index % len(available_nodes)]
        job.node_id = target_node.id
        job.node = target_node
        job.status = "starting"
        job.auto_started = True
        db.flush()
        if send_command(job, "start", req_session):
            failover_exitoso = True
        else:
            job.status = "error"
    if failover_exitoso:
        db.commit()
        try:
            req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=2)
        except Exception:
            pass


def check_and_heal_children(db, parent_job, req_session):
    if parent_job.status != 'running' or not parent_job.started_at:
        return

    uptime = abs((datetime.now() - parent_job.started_at).total_seconds())
    if uptime < 30:
        return

    children = db.query(models.EncodingJob).filter(models.EncodingJob.parent_job_id == parent_job.id).all()

    for child in children:
        channel_name = child.channel.channel_name if child.channel else "Desconocido"

        if child.status in ['stopped', 'error']:
            logger.info(f"🚀 AUTO-START/HEAL: Forzando inicio de Packager {child.id} ({channel_name})")
            log_monitor_event(db, "AUTO_START", f"Encoder estable. Forzando inicio de Packager {child.id} ({channel_name}).", child.node_id)
            child.auto_started = True
            child.status = "starting"
            db.add(child)
            db.commit()

            if send_command(child, "start", req_session):
                try:
                    req_session.post("http://127.0.0.1:9000/api/internal/sync-haproxy", timeout=10)
                except Exception:
                    pass
            else:
                child.auto_started = False
                child.status = "error"
                db.add(child)
                db.commit()

        elif child.status == 'failover':
            logger.info(f"🚑 AUTO-RESTORE: Restaurando Packager {child.id} ({channel_name}) a la señal principal...")
            log_monitor_event(db, "FAILOVER_RESTORED", f"Encoder principal recuperado. Restaurando Packager {child.id} ({channel_name}).", child.node_id)
            notify_cms_channel_status(child.channel_id, "online", f"Encoder principal de {channel_name} restaurado. Volviendo a señal normal.")
            try:
                res = req_session.post(f"http://127.0.0.1:9000/api/internal/trigger-failover/{child.channel_id}?mode=restore", timeout=30)
                if res.status_code == 200:
                    db.refresh(child)
                    prefix = "pkg" if child.node.tipo == 'Packager' else "channel"
                    prog_name = f"{prefix}_{child.channel.channel_name}_{child.id}"
                    try:
                        verify = req_session.get(f"http://{child.node.ip_address}:{AGENT_PORT}/jobs/status", timeout=5)
                        if verify.status_code == 200:
                            processes = verify.json()
                            for p in processes:
                                if p.get('name', '').lower() == prog_name.lower() and p.get('statename') == 'RUNNING':
                                    logger.info(f"✅ Packager {child.id} ({channel_name}) verificado como RUNNING tras restore.")
                                    break
                            else:
                                logger.warning(f"⚠️ Packager {child.id} ({channel_name}) no está RUNNING tras restore. Estado: {[p.get('statename') for p in processes if p.get('name','').lower() == prog_name.lower()]}")
                    except Exception as ve:
                        logger.warning(f"⚠️ No se pudo verificar estado del packager tras restore: {ve}")
            except Exception as e:
                logger.error(f"⚠️ Error de red restaurando failover: {e}")

        elif child.status == 'running' and child.started_at:
            if parent_job.started_at > (child.started_at + timedelta(seconds=15)):
                logger.info(f"♻️ RE-SYNC: Reiniciando Packager {child.id} ({channel_name}) por desfase con Encoder padre.")
                log_monitor_event(db, "AUTO_RESYNC", f"Reiniciando Packager {child.id} ({channel_name}) por desfase temporal con Encoder.", child.node_id)
                send_command(child, "restart", req_session)
                child.started_at = datetime.now()
                db.add(child)
                db.commit()
