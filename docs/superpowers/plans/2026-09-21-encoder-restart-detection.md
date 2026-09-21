# Encoder Restart Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect encoder restarts via uptime tracking and automatically recover encoding jobs.

**Architecture:** Compare `uptime_seconds` from agent health endpoint with stored baseline. If uptime decreases, a restart occurred → trigger recovery.

**Tech Stack:** Python 3.12, SQLAlchemy, MySQL, httpx

## Global Constraints

- Python 3.12 (server), 3.9.6 (local dev)
- Use `Optional[T]` not `T | None` for local compatibility
- SSH key: `~/.ssh/id_opencode`
- Deploy: `scp` → `sudo cp` → `systemctl restart`
- Commit: `git add -A && git commit && git push origin main`

---

### Task 1: Database Migration

**Files:**
- Create: `scripts/add_uptime_tracking_columns.py`
- Modify: None (SQL only)

**Interfaces:**
- Consumes: MySQL database `encoder_orchestrator`
- Produces: Two new columns in `nodos` table

- [ ] **Step 1: Create migration script**

```python
#!/usr/bin/env python3
"""Add uptime tracking columns to nodos table."""
import pymysql

DB_CONFIG = {
    'host': 'localhost',
    'user': 'ingservice',
    'password': 'S3rv1c3.Ingenieria',
    'database': 'encoder_orchestrator'
}

def migrate():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute("SHOW COLUMNS FROM nodos LIKE 'previous_uptime_seconds'")
    if cursor.fetchone():
        print("Columns already exist, skipping migration")
        return
    
    # Add columns
    cursor.execute("""
        ALTER TABLE nodos 
        ADD COLUMN previous_uptime_seconds INT DEFAULT NULL,
        ADD COLUMN last_restart_detected_at DATETIME DEFAULT NULL
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Migration completed: added previous_uptime_seconds, last_restart_detected_at")

if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2: Run migration on server**

```bash
scp -i ~/.ssh/id_opencode scripts/add_uptime_tracking_columns.py oymservice@172.16.223.5:/tmp/
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.operaciones' | sudo -S python3 /tmp/add_uptime_tracking_columns.py"
```

Expected: `Migration completed: added previous_uptime_seconds, last_restart_detected_at`

- [ ] **Step 3: Verify columns exist**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.Ingenieria' | mysql -u ingservice -p'S3rv1c3.Ingenieria' -D encoder_orchestrator -e 'SHOW COLUMNS FROM nodos LIKE \"%uptime%\"'"
```

Expected: Two rows returned

- [ ] **Step 4: Commit migration script**

```bash
git add scripts/add_uptime_tracking_columns.py
git commit -m "feat: migration script for uptime tracking columns"
```

---

### Task 2: Update Models

**Files:**
- Modify: `models.py:91-132` (Node class)

**Interfaces:**
- Consumes: SQLAlchemy Base
- Produces: `Node.previous_uptime_seconds`, `Node.last_restart_detected_at`

- [ ] **Step 1: Read current models.py**

```bash
grep -n "class Node\|backup_node_id\|drm_total_users" models.py
```

- [ ] **Step 2: Add new fields to Node class**

Add after line 119 (`backup_node = relationship(...)`):

```python
    # --- CAMPOS PARA DETECCIÓN DE REINICIO ---
    previous_uptime_seconds = Column(Integer, nullable=True)
    last_restart_detected_at = Column(DateTime, nullable=True)
    # -----------------------------------------
```

- [ ] **Step 3: Verify model loads**

```bash
python3 -c "from models import Node; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add previous_uptime_seconds, last_restart_detected_at to Node model"
```

---

### Task 3: Implement detect_encoder_restart()

**Files:**
- Modify: `monitor.py:484` (after `sync_single_node_thread` definition)

**Interfaces:**
- Consumes: `db` (Session), `node` (Node), `current_uptime_seconds` (int)
- Produces: `bool` (True if restart detected)

- [ ] **Step 1: Add function after sync_single_node_thread**

Insert before line 484:

```python
def detect_encoder_restart(db, node, current_uptime_seconds):
    """Detecta si un encoder se reinició comparando uptime."""
    if current_uptime_seconds is None or current_uptime_seconds == 0:
        return False
    
    if node.previous_uptime_seconds is None:
        node.previous_uptime_seconds = current_uptime_seconds
        return False
    
    if current_uptime_seconds < node.previous_uptime_seconds:
        logging.warning(f"🔄 REINICIO DETECTADO: {node.hostname} "
                       f"(uptime {node.previous_uptime_seconds}s → {current_uptime_seconds}s)")
        
        node.last_restart_detected_at = datetime.now()
        node.previous_uptime_seconds = current_uptime_seconds
        return True
    
    if current_uptime_seconds > node.previous_uptime_seconds:
        node.previous_uptime_seconds = current_uptime_seconds
    
    return False
```

- [ ] **Step 2: Commit**

```bash
git add monitor.py
git commit -m "feat: add detect_encoder_restart() function"
```

---

### Task 4: Implement handle_encoder_restart_recovery()

**Files:**
- Modify: `monitor.py` (after detect_encoder_restart)

**Interfaces:**
- Consumes: `db` (Session), `node` (Node), `req_session` (httpx.Client)
- Produces: Jobs relaunched, events logged

- [ ] **Step 1: Add function**

Insert after `detect_encoder_restart()`:

```python
def handle_encoder_restart_recovery(db, node, req_session):
    """Maneja recovery completo tras reinicio de encoder."""
    # Rate limiting: max 1 recovery per hour per node
    if node.last_restart_detected_at:
        time_since_last = (datetime.now() - node.last_restart_detected_at).total_seconds()
        if time_since_last < 3600:
            logging.debug(f"Recovery rate limited for {node.hostname} ({time_since_last:.0f}s since last)")
            return
    
    # Find jobs that were running
    running_jobs = db.query(models.EncodingJob).filter(
        models.EncodingJob.node_id == node.id,
        models.EncodingJob.status.in_(["running", "starting"])
    ).all()
    
    if not running_jobs:
        return
    
    # Query agent for actual running processes
    agent_names = set()
    try:
        resp = req_session.get(f"http://{node.ip_address}:{AGENT_PORT}/jobs/status", timeout=10)
        if resp.status_code == 200:
            raw = resp.json()
            if isinstance(raw, list) and all(isinstance(p, dict) and 'name' in p for p in raw):
                agent_names = {p['name'].lower() for p in raw}
    except Exception as e:
        logging.warning(f"No se pudo verificar procesos del agente en RESTART_RECOVERY: {e}")
    
    # Identify ghost jobs
    ghost_jobs = []
    for job in running_jobs:
        prefix = "pkg" if job.node.tipo == 'Packager' else "channel"
        prog = f"{prefix}_{job.channel.channel_name}_{job.id}"
        if prog.lower() not in agent_names:
            job.status = "error"
            job.auto_started = False
            job.updated_at = datetime.now()
            ghost_jobs.append(job)
    
    if not ghost_jobs:
        return
    
    # Relaunch ghost jobs
    logging.warning(f"🔄 RECOVERY POST-RESTART: {len(ghost_jobs)} jobs en {node.hostname}")
    for job in ghost_jobs:
        prog_name = f"{'pkg' if node.tipo == 'Packager' else 'channel'}_{job.channel.channel_name}_{job.id}"
        try:
            if job.command:
                compressed = base64.b64encode(zlib.compress(job.command.encode('utf-8'))).decode('utf-8')
                payload = {"job_id": job.id, "channel_name": job.channel.channel_name, "command": compressed, "autostart": True}
                resp = req_session.post(f"http://{node.ip_address}:{AGENT_PORT}/jobs/create", json=payload, timeout=30)
                if resp.status_code == 200:
                    job.status = "starting"
                    job.auto_started = True
                    job.started_at = datetime.now()
                    logging.info(f"  ✅ {prog_name} → starting")
                else:
                    logging.warning(f"  ❌ {prog_name} → error {resp.status_code}")
            else:
                send_command(job, "start", req_session)
                job.status = "starting"
                job.auto_started = True
                job.started_at = datetime.now()
                logging.info(f"  ✅ {prog_name} → starting (start)")
        except Exception as e:
            logging.warning(f"  ❌ {prog_name} → exception: {e}")
    
    db.commit()
    log_monitor_event(db, "ENCODER_RESTART_RECOVERY", 
                     f"Recovery post-restart: {len(ghost_jobs)} jobs relanzados en {node.hostname}", 
                     node.id)
    
    # Telegram notification
    try:
        msg = f"🔄 *REINICIO DETECTADO*: {node.hostname}\n"
        msg += f"Jobs recovery: {len(ghost_jobs)} relanzados"
        from utils.helpers import send_telegram
        send_telegram(msg)
    except Exception:
        pass
```

- [ ] **Step 2: Commit**

```bash
git add monitor.py
git commit -m "feat: add handle_encoder_restart_recovery() function"
```

---

### Task 5: Integrate into Health Check Flow

**Files:**
- Modify: `monitor.py:557-558` (after uptime extraction)

**Interfaces:**
- Consumes: `detect_encoder_restart()`, `handle_encoder_restart_recovery()`
- Produces: Restart detection in health check loop

- [ ] **Step 1: Find integration point**

```bash
grep -n "node.uptime = str(h_data.get" monitor.py
```

Expected: Line ~558

- [ ] **Step 2: Add restart detection after uptime extraction**

After line 558 (`node.uptime = str(h_data.get('uptime', "00:00:00"))`):

```python
                    # Detectar reinicio (solo encoders)
                    if node.tipo == 'Encoder':
                        uptime_seconds = h_data.get('uptime_seconds', 0)
                        if detect_encoder_restart(db, node, uptime_seconds):
                            handle_encoder_restart_recovery(db, node, req_session)
```

- [ ] **Step 3: Commit**

```bash
git add monitor.py
git commit -m "feat: integrate restart detection into health check flow"
```

---

### Task 6: Deploy to Server

**Files:**
- Deploy: `monitor.py`, `models.py`
- Deploy: `scripts/signal_analyzer.py` (from previous issue)

**Interfaces:**
- Consumes: Server at 172.16.223.5
- Produces: Running v2.16.3

- [ ] **Step 1: Bump version to v2.16.3**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.operaciones' | sudo -S sed -i 's/VERSION_PATCH = 2/VERSION_PATCH = 3/' /opt/encoder-orchestrator/core/version.py"
```

- [ ] **Step 2: Deploy files**

```bash
scp -i ~/.ssh/id_opencode monitor.py oymservice@172.16.223.5:/tmp/monitor.py
scp -i ~/.ssh/id_opencode models.py oymservice@172.16.223.5:/tmp/models.py

ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "
echo 'S3rv1c3.operaciones' | sudo -S cp /tmp/monitor.py /opt/encoder-orchestrator/monitor.py &&
echo 'S3rv1c3.operaciones' | sudo -S cp /tmp/models.py /opt/encoder-orchestrator/models.py &&
echo 'S3rv1c3.operaciones' | sudo -S python3 -m py_compile /opt/encoder-orchestrator/monitor.py &&
echo 'S3rv1c3.operaciones' | sudo -S python3 -m py_compile /opt/encoder-orchestrator/models.py &&
echo 'S3rv1c3.operaciones' | sudo -S systemctl restart encoder-monitor.service &&
echo 'S3rv1c3.operaciones' | sudo -S systemctl restart encoder-api.service &&
sleep 2 && curl -s http://127.0.0.1:9000/api/health | head -100
"
```

Expected: `"version":"v2.16.3"`

- [ ] **Step 3: Update CHANGELOG.md**

Add entry for v2.16.3 at top of file.

- [ ] **Step 4: Commit and push**

```bash
git add -A
git commit -m "feat: v2.16.3 — Encoder restart detection via uptime tracking"
git push origin main
```

---

### Task 7: Test on Mac-05

**Files:**
- None (manual testing)

**Interfaces:**
- Consumes: Mac-05 at 172.16.222.155
- Produces: Verified restart detection

- [ ] **Step 1: Verify current status**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.Ingenieria' | mysql -u ingservice -p'S3rv1c3.Ingenieria' -D encoder_orchestrator -e 'SELECT hostname, status, previous_uptime_seconds FROM nodos WHERE hostname=\"mac_05\"'"
```

- [ ] **Step 2: Check agent uptime**

```bash
curl -s http://172.16.222.155:9000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('uptime_seconds'))"
```

- [ ] **Step 3: Restart Mac-05 agent**

```bash
sshpass -p 'deepseek' ssh -o StrictHostKeyChecking=no soporte@172.16.222.155 "launchctl unload ~/Library/LaunchAgents/com.mundogo.encoderagent.plist && pkill -f 'python.*main.py' && launchctl load ~/Library/LaunchAgents/com.mundogo.encoderagent.plist"
```

- [ ] **Step 4: Monitor logs for restart detection**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "journalctl -u encoder-monitor.service -f --since '1 min ago'"
```

Expected: `🔄 REINICIO DETECTADO: mac_05` and `🔄 RECOVERY POST-RESTART: X jobs`

- [ ] **Step 5: Verify jobs recovered**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.Ingenieria' | mysql -u ingservice -p'S3rv1c3.Ingenieria' -D encoder_orchestrator -e 'SELECT id, status, auto_started FROM encoding_jobs WHERE node_id=20'"
```

Expected: All jobs in `starting` or `running` with `auto_started=1`

- [ ] **Step 6: Verify Telegram notification**

Check Telegram for restart notification.

---

### Task 8: Close Issue

**Files:**
- None (GitHub only)

**Interfaces:**
- Consumes: GitHub API
- Produces: Issue #4 updated

- [ ] **Step 1: Add comment to issue #4**

```bash
curl -X POST -H "Authorization: token <PAT>" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/eskiconce/Mgo_Orquestador/issues/4/comments \
  -d '{"body":"## ✅ v2.16.3 — Restart Detection\n\n**Commit:** <sha>\n\n### Cambios:\n- Uptime tracking en `monitor.py`\n- Recovery automático post-restart\n- Max 1 recovery/hora por nodo\n- Telegram notification\n\n### Test:\n- Mac-05 restart test passed"}'
```

- [ ] **Step 2: Verify issue updated**

```bash
curl -s -H "Authorization: token <PAT>" https://api.github.com/repos/eskiconce/Mgo_Orquestador/issues/4 | python3 -c "import sys,json; print(json.load(sys.stdin).get('state'))"
```

Expected: `open` (still open for monitoring)

---

## Rollback Plan

If issues occur:

1. **Revert monitor.py:**
```bash
scp -i ~/.ssh/id_opencode oymservice@172.16.223.5:/opt/encoder-orchestrator/monitor.py /tmp/monitor.py
# Edit to remove new functions
```

2. **Revert models.py:**
```bash
scp -i ~/.ssh/id_opencode oymservice@172.16.223.5:/opt/encoder-orchestrator/models.py /tmp/models.py
# Edit to remove new fields
```

3. **Restart services:**
```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 "echo 'S3rv1c3.operaciones' | sudo -S systemctl restart encoder-monitor.service encoder-api.service"
```

## Success Criteria

1. ✅ Restart detected within 10s of occurrence
2. ✅ Ghost jobs identified and relaunched automatically
3. ✅ Telegram notification sent
4. ✅ Max 1 recovery per hour per node
5. ✅ No false positives during normal operation
