# Design: Fix Encoder-Packager Restart Sync

## Problem Statement

When an encoder auto-restarts due to discontinuity errors (via signal_analyzer.py), the packager continues running with the old stream, causing the channel to go out of sync. The front-end also shows incorrect uptime because `started_at` is not properly updated.

## Current Flow (Broken)

```
1. signal_analyzer.py detects discontinuity → auto-restarts FFmpeg
2. Calls POST /api/internal/encoder-restart
3. Endpoint updates job.started_at for encoder
4. Packager NOT restarted → continues with old timestamps
5. Channel goes out of sync
6. Front-end shows incorrect uptime (from old started_at)
```

## Proposed Solution

### Change 1: `routers/internal.py` - Restart packager on callback

When the encoder-restart endpoint is called, also restart the associated packager job.

```python
@router.post("/api/internal/encoder-restart")
async def notify_encoder_restart(data: dict = Body(...), db: Session = Depends(get_db)):
    # ... existing code ...
    
    # NEW: Find and restart packager child
    packager_job = db.query(models.EncodingJob).filter(
        models.EncodingJob.parent_job_id == job.id,
        models.EncodingJob.status == "running"
    ).first()
    
    if packager_job:
        prefix = "pkg"
        prog_name = f"{prefix}_{packager_job.channel.channel_name}_{packager_job.id}"
        url = f"http://{packager_job.node.ip_address}:8000/jobs/control"
        requests.post(url, params={"action": "restart", "program_name": prog_name}, timeout=10)
        
        packager_job.started_at = datetime.now()
        db.commit()
        
        log_monitor_event(db, "PACKAGER_RESTART", 
            f"Packager {packager_job.id} reiniciado tras restart de encoder {channel_name}", 
            packager_job.node_id)
```

### Change 2: Front-end - Auto-refresh already works

The front-end uses `location.reload()` with configurable interval. When the backend updates `started_at`, the front-end will show the correct uptime on the next refresh.

## Testing

1. Trigger a discontinuity on an encoder
2. Verify encoder auto-restarts
3. Verify packager is also restarted
4. Verify front-end shows correct uptime after refresh

## Risk Assessment

- **Low Risk:** Adding packager restart to existing endpoint
- **Fallback:** If packager restart fails, encoder still works independently
