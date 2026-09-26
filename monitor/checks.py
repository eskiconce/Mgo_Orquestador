"""
Monitor — Checks module.
Encoder health checks: TS errors, health logs, discontinuity, drop frames.
"""
import re
import logging
from datetime import datetime

from core.config import AGENT_PORT
from utils.helpers import log_monitor_event
from services import builders as bld
from .alerts import notify_cms_channel_status, notify_telegram
from .commands import send_command

logger = logging.getLogger(__name__)

# State trackers (shared across checks)
_prev_logs = {}
_ts_error_state = {}
_ts_discontinuity_state = {}
_drop_baseline_state = {}


def reset_stale_state(active_job_ids):
    """Limpia estado de checks para jobs inactivos."""
    for store in (_prev_logs, _ts_error_state, _ts_discontinuity_state, _drop_baseline_state):
        if isinstance(store, dict):
            keys_to_remove = [k for k in store if k not in active_job_ids]
            for k in keys_to_remove:
                store.pop(k, None)


def check_encoder_ts_errors(db, job, req_session):
    if job.node.tipo != "Encoder":
        return False
    if job.status not in ("running", "starting", "error"):
        return False

    job_id = job.id
    channel = job.channel
    prog_name = f"channel_{channel.channel_name}_{job_id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 30}, timeout=5)
        if resp.status_code != 200:
            return False
        log_content = resp.json().get("content", "")
    except Exception:
        return False

    now = datetime.now()
    state = _ts_error_state.get(job_id)
    if state is None:
        state = {"first_seen": now, "last_restart": None, "restart_count": 0,
                 "down_since": None, "backup_tried": False, "final_alerted": False,
                 "last_frame": None, "last_time": None, "stuck_count": 0,
                 "last_error_seen": now}
        _ts_error_state[job_id] = state
    else:
        last_error = state.get("last_error_seen")
        if last_error and (now - last_error).total_seconds() > 120:
            state["first_seen"] = now
            state["restart_count"] = 0
            state["down_since"] = None
            state["backup_tried"] = False
            state["final_alerted"] = False
            state["stuck_count"] = 0
        state["last_error_seen"] = now

    ts_error_patterns = ["length violation", "Found tag", "PES packet size mismatch", "Packet corrupt"]
    has_ts_error = any(p in log_content for p in ts_error_patterns)

    current_frame = None
    current_time = None
    m_frame = re.search(r'frame=\s*(\d+)', log_content)
    m_time = re.search(r'time=(\d+:\d+:\d+\.\d+)', log_content)
    if m_frame:
        current_frame = m_frame.group(1)
    if m_time:
        current_time = m_time.group(1)

    is_stuck = False
    if current_frame and current_time:
        if current_frame == state["last_frame"] and current_time == state["last_time"]:
            state["stuck_count"] += 1
            if state["stuck_count"] >= 3 and not has_ts_error:
                is_stuck = True
        else:
            state["stuck_count"] = 0
            state["last_frame"] = current_frame
            state["last_time"] = current_time

    if not has_ts_error and not is_stuck:
        state["stuck_count"] = 0
        return False

    reason = "TS error" if has_ts_error else "ENCERRADO"
    elapsed = (now - state["first_seen"]).total_seconds()

    if state["restart_count"] == 0 and elapsed >= 30:
        logger.warning(f"{reason} persistente en {prog_name} por {elapsed:.0f}s — restart #1")
        send_command(job, "restart", req_session)
        job.started_at = datetime.now()
        db.commit()
        state["last_restart"] = now
        state["restart_count"] = 1
        state["first_seen"] = now
        _prev_logs.pop(f"{prog_name}_err", None)
        return True

    if state["restart_count"] == 1 and elapsed >= 90:
        logger.warning(f"{reason} tras restart en {prog_name} — stop + espera 60s")
        send_command(job, "stop", req_session)
        state["down_since"] = now
        state["restart_count"] = 2
        return True

    if state["restart_count"] == 2 and state["down_since"]:
        down_elapsed = (now - state["down_since"]).total_seconds()
        if down_elapsed >= 60:
            logger.warning(f"{reason} en {prog_name} tras 60s down — restart #2")
            send_command(job, "restart", req_session)
            job.started_at = datetime.now()
            db.commit()
            state["last_restart"] = now
            state["restart_count"] = 3
            state["first_seen"] = now
            _prev_logs.pop(f"{prog_name}_err", None)
            return True

    if state["restart_count"] == 3 and elapsed >= 180:
        if not state["backup_tried"]:
            logger.warning(f"{reason} persistente en {prog_name} — intentando switch a backup source")
            _try_switch_to_backup(db, job, req_session)
            state["backup_tried"] = True
            return True
        elif not state["final_alerted"]:
            logger.error(f"{reason} en {prog_name} persiste incluso con backup — alerta final")
            _send_final_alert(db, job, prog_name)
            state["final_alerted"] = True
            return True

    return False


def _try_switch_to_backup(db, job, req_session):
    channel = job.channel
    if channel.origin_count < 2:
        logger.warning(f"TS backup: {channel.channel_name} no tiene origen de respaldo")
        return False

    channel.active_origin = "backup"
    db.commit()
    logger.info(f"TS backup: active_origin=backup para {channel.channel_name}")

    prog_name = f"channel_{channel.channel_name}_{job.id}"
    try:
        if job.node.tipo == "Encoder" and "mac" in (job.node.os or "").lower():
            new_script = bld.generate_mac_encoder_bash(channel, job.node, use_backup=True)
        else:
            new_script = bld.generate_linux_encoder_bash(channel, job.node, use_backup=True)

        job.command = new_script
        db.commit()

        compressed = bld.compress_command(new_script)
        job.command_compress = compressed
        db.commit()

        url_create = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create"
        resp = req_session.post(url_create, json={
            "job_id": job.id,
            "channel_name": channel.channel_name,
            "command": compressed,
            "autostart": True
        }, timeout=10)
        if resp.status_code == 200:
            logger.info(f"TS backup: comando actualizado en agente para {prog_name}")
    except Exception as e:
        logger.error(f"TS backup: error regenerando script para {prog_name}: {e}")

    notify_cms_channel_status(channel.id, "backup_activated", f"Conmutación a fuente de respaldo por errores TS en encoder.")
    notify_telegram(f"<b>🔄 Backup activado</b> para <b>{channel.channel_name}</b>\nMotivo: errores TS persistentes en encoder\nOrigen: {channel.origin2_multicast_ip}:{channel.origin2_multicast_port}")

    send_command(job, "restart", req_session)
    job.started_at = datetime.now()
    db.commit()
    return True


def _send_final_alert(db, job, prog_name):
    channel = job.channel
    msg = f"<b>🚨 ALERTA: {channel.channel_name}</b>\nErrores TS persisten tras agotar reintentos y backup\nRequiere intervención manual"
    notify_telegram(msg)
    notify_cms_channel_status(channel.id, "critical_ts_error", "Errores TS críticos en encoder tras agotar todas las acciones automáticas")
    logger.error(f"TS FINAL ALERT: {prog_name}")


def check_encoder_health_logs(db, job, req_session):
    if job.status != 'running' or not job.started_at:
        return False

    uptime = abs((datetime.now() - job.started_at).total_seconds())
    if uptime < 60:
        return False

    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 60}, timeout=5)
        if resp.status_code == 200:
            log_content = resp.json().get("content", "")

            error_keywords = [
                "Packet corrupt",
                "PES packet size mismatch",
                "co located POCs unavailable",
                "timestamp discontinuity"
            ]

            prev_content = _prev_logs.get(prog_name, "")
            _prev_logs[prog_name] = log_content

            prev_lines = prev_content.split('\n')
            curr_lines = log_content.split('\n')

            overlap = 0
            for i in range(min(len(prev_lines), len(curr_lines)), 0, -1):
                if prev_lines[-i:] == curr_lines[:i]:
                    overlap = i
                    break

            new_lines = curr_lines[overlap:]

            error_count = 0
            for line in new_lines:
                if any(keyword in line for keyword in error_keywords):
                    error_count += 1

            if len(new_lines) == 0:
                return False

            if error_count >= 10:
                logger.warning(f"🚨 CORRUPCIÓN CRÍTICA ({error_count} errores en 60 líneas) en {prog_name}. Forzando reinicio preventivo...")
                log_monitor_event(db, "AUTO_RESTART", f"Corrupción severa de red ({error_count} fallos) en origen de {prog_name}. Reiniciando.", job.node_id)

                send_command(job, "restart", req_session)

                job.started_at = datetime.now()
                db.add(job)
                db.commit()

                notify_cms_channel_status(job.channel_id, "warning", "Reinicio preventivo por corrupción severa de red.")
                return True

            elif error_count > 0:
                logger.info(f"⚠️ Micro-corte UDP en {prog_name} ({error_count} errores detectados). El encoder se recuperó, mantenemos en observación.")

    except Exception:
        pass

    return False


def check_timestamp_discontinuity(db, job, req_session):
    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 30}, timeout=5)
        if resp.status_code != 200:
            return False
        log_content = resp.text
    except Exception:
        return False

    if "timestamp discontinuity" not in log_content:
        _ts_discontinuity_state.pop(job.id, None)
        return False

    now = datetime.now()
    state = _ts_discontinuity_state.get(job.id)

    if state is None:
        _ts_discontinuity_state[job.id] = {"first_seen": now, "restart_count": 0}
        logger.warning(f"⚠️ Timestamp discontinuity detectado en {prog_name}")
        return False

    elapsed = (now - state["first_seen"]).total_seconds()

    if elapsed >= 60 and state["restart_count"] == 0:
        logger.warning(f"🔴 Timestamp discontinuity persistente en {prog_name} ({elapsed:.0f}s) — reiniciando encoder")
        send_command(job, "restart", req_session)
        job.started_at = datetime.now()
        db.commit()
        state["restart_count"] = 1
        state["first_seen"] = now
        _prev_logs.pop(f"{prog_name}_err", None)
        log_monitor_event(db, "TIMESTAMP_DISCONTINUITY", f"Encoder {prog_name} reiniciado por timestamp discontinuity persistente ({elapsed:.0f}s).", job.node.id)
        notify_cms_channel_status(job.channel_id, "restart", f"Encoder reiniciado por discontinuity")
        notify_telegram(f"⚠️ <b>Encoder reiniciado</b> por discontinuity\nCanal: <b>{job.channel.channel_name}</b>\nNodo: {job.node.hostname}\nTiempo: {elapsed:.0f}s")
        return True

    return False


def check_ffmpeg_drop_frames(db, job, req_session):
    prog_name = f"channel_{job.channel.channel_name}_{job.id}"
    url_logs = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/logs"

    try:
        resp = req_session.get(url_logs, params={"program_name": prog_name, "type": "err", "lines": 10}, timeout=5)
        if resp.status_code != 200:
            return
        log_content = resp.text
    except Exception:
        return

    drop_match = re.search(r'drop=(\d+)', log_content)
    if not drop_match:
        return

    drop_actual = int(drop_match.group(1))

    state = _drop_baseline_state.get(job.id)
    if state is None:
        _drop_baseline_state[job.id] = {
            "initial_drop": drop_actual,
            "last_alerted_drop": drop_actual,
        }
        logger.info(f"📊 Drop baseline para {prog_name}: {drop_actual}")
        return

    if drop_actual > state["last_alerted_drop"]:
        delta = drop_actual - state["initial_drop"]
        log_monitor_event(db, "DROP_FRAMES",
            f"{prog_name}: drop {state['last_alerted_drop']}→{drop_actual} (baseline: {state['initial_drop']}, delta: +{delta})",
            job.node.id)
        state["last_alerted_drop"] = drop_actual

    elif drop_actual < state["last_alerted_drop"]:
        logger.info(f"📊 Drop disminuyó en {prog_name}: {state['last_alerted_drop']} → {drop_actual}")
        state["last_alerted_drop"] = drop_actual
