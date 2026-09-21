# Design: Encoder Restart Detection via Uptime Tracking

**Date:** 2026-09-21
**Status:** Approved
**Scope:** Mgo_Orquestador — monitor.py, models.py, BD

## Problem Statement

When an encoder (Mac/Linux) restarts unexpectedly, the monitor fails to detect it if the encoder comes back online within 45 seconds. This causes:

1. Channels remain down until manual intervention
2. No automatic recovery of encoding jobs
3. No notification to operators

**Root Cause:** The current detection mechanism relies on timeout-based offline detection (45s). If the encoder restarts faster than this threshold, the monitor never marks it as offline and never triggers recovery.

**Evidence:** On Sep 20, 2026, mac_01 (172.16.223.10) restarted unexpectedly. The monitor only logged a timeout warning. Channels remained down until manually started on Sep 21.

## Design

### Approach: Uptime Tracking

Compare `uptime_seconds` from agent health endpoint with stored baseline. If uptime decreases, a restart occurred.

### Components

#### 1. Database Changes

**Table `nodos`:**
```sql
ALTER TABLE nodos ADD COLUMN previous_uptime_seconds INT DEFAULT NULL;
ALTER TABLE nodos ADD COLUMN last_restart_detected_at DATETIME DEFAULT NULL;
```

**Migration script:** `scripts/add_uptime_tracking_columns.py`

#### 2. Model Changes (`models.py`)

Add to `Node` class:
```python
previous_uptime_seconds = Column(Integer, nullable=True)
last_restart_detected_at = Column(DateTime, nullable=True)
```

#### 3. Monitor Changes (`monitor.py`)

**New function `detect_encoder_restart()`:**
- Input: `db`, `node`, `current_uptime_seconds`
- Logic:
  - If `previous_uptime_seconds` is None → set baseline, return False
  - If `current_uptime_seconds < previous_uptime_seconds` → restart detected, return True
  - If `current_uptime_seconds > previous_uptime_seconds` → update baseline, return False
- Output: `bool` (True if restart detected)

**New function `handle_encoder_restart_recovery()`:**
- Input: `db`, `node`, `req_session`
- Logic:
  1. Find jobs with status `running` or `starting` on this node
  2. Query agent `/jobs/status` to get actual running processes
  3. Compare: jobs in BD but not in agent → ghost jobs
  4. Mark ghost jobs as `error`
  5. Relaunch ghost jobs via `/jobs/create`
  6. Log event `ENCODER_RESTART_RECOVERY`
  7. Send Telegram notification
- Safety: Max 1 recovery per hour per node

**Integration point (line ~558):**
```python
# After obtaining health_data from agent
uptime_seconds = h_data.get('uptime_seconds', 0)

# Detect restart (encoders only)
if node.tipo == 'Encoder':
    if detect_encoder_restart(db, node, uptime_seconds):
        handle_encoder_restart_recovery(db, node, req_session)
```

#### 4. Events

| Event Type | Description |
|------------|-------------|
| `ENCODER_RESTART_DETECTED` | Restart detected via uptime comparison |
| `ENCODER_RESTART_RECOVERY` | Recovery completed, jobs relaunched |

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Health Check (cada 10s)                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Agente reporta: uptime_seconds=3600                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  compare(3600, previous_uptime=72000)                       │
│  3600 < 72000 → REINICIO DETECTADO                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  handle_encoder_restart_recovery()                          │
│  ├─ Find jobs running/starting                              │
│  ├─ Query agent /jobs/status                                │
│  ├─ Identify ghost jobs                                     │
│  ├─ Mark as error                                           │
│  ├─ Relaunch via /jobs/create                               │
│  ├─ Log ENCODER_RESTART_RECOVERY                            │
│  └─ Send Telegram notification                              │
└─────────────────────────────────────────────────────────────┘
```

### Safety Mechanisms

1. **Rate limiting:** Max 1 recovery per hour per node
2. **Scope:** Only encoders (not packagers, origins, DRM)
3. **Baseline persistence:** `previous_uptime` updated every cycle
4. **Graceful handling:** If agent doesn't report uptime, skip detection

### Testing

1. **Unit tests:**
   - `detect_encoder_restart()` with various uptime scenarios
   - `handle_encoder_restart_recovery()` with mock agent

2. **Integration tests:**
   - Simulate encoder restart (kill agent, restart)
   - Verify recovery triggers
   - Verify Telegram notification

3. **Manual testing:**
   - Restart mac_05 (172.16.222.155) manually
   - Verify detection within 10s
   - Verify jobs relaunched automatically

## Implementation Plan

### Phase 1: Database + Model (15 min)
- [ ] Run migration SQL
- [ ] Update `models.py`
- [ ] Verify model loads correctly

### Phase 2: Monitor Logic (30 min)
- [ ] Implement `detect_encoder_restart()`
- [ ] Implement `handle_encoder_restart_recovery()`
- [ ] Integrate into health check flow
- [ ] Add rate limiting

### Phase 3: Testing (20 min)
- [ ] Unit tests
- [ ] Integration test on mac_05
- [ ] Verify Telegram notification

### Phase 4: Deploy (10 min)
- [ ] Deploy to server
- [ ] Deploy to all encoders
- [ ] Monitor logs for 1 hour
- [ ] Commit + push to GitHub

## Rollback Plan

If issues occur:
1. Revert `monitor.py` to previous version
2. Revert `models.py` to previous version
3. (Optional) Drop new columns from BD

## References

- Agent health endpoint: `/health` returns `uptime_seconds`
- Current monitor logic: `monitor.py:484-669`
- Node model: `models.py:91-132`
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/4
