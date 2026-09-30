"""
Monitor — Commands module.
send_command and kill_flow_safety for controlling encoder/packager processes.
"""
import httpx
import logging
from datetime import datetime

from core.config import AGENT_PORT
from services.settings_service import get_api_key

logger = logging.getLogger(__name__)


def send_command(job, action, req_session=None):
    try:
        url = f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/create" if action == "start" else f"http://{job.node.ip_address}:{AGENT_PORT}/jobs/control"
        method = req_session if req_session else httpx
        headers = {"X-API-Key": get_api_key()}

        if action == "start":
            payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": job.command_compress, "autostart": True}
            r = method.post(url, json=payload, headers=headers, timeout=30)
            return r.status_code in [200, 201]
        else:
            prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
            prog = f"{prefix}_{job.channel.channel_name}_{job.id}"
            r = method.post(url, params={"action": action, "program_name": prog}, headers=headers, timeout=10)
            return r.status_code == 200
    except Exception:
        return False


def kill_flow_safety(db, job, req_session):
    job.status = "error"
    job.auto_started = False
    job.updated_at = datetime.now()
    db.add(job)
    send_command(job, "stop", req_session)
    db.commit()
