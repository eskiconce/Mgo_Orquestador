# Recovery Automático de Jobs en Error tras Reconnect de Nodo

**Versión:** v2.4.1  
**Fecha:** 24 Julio 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Problema

Cuando un nodo encoder (mac02) se desconecta del orquestador (reboot, caída de red), el monitor marcaba todos los jobs del nodo como `status="error"`. Al volver el nodo, el agente tenía su **registry de procesos vacío** (perdió los procesos en memoria tras el reinicio). El sync loop veía `state=STOPPED` para todos los jobs, y como el handler de STOPPED ignoraba jobs en estado `"error"`, estos **quedaban en "error" permanentemente** sin intentar re-lanzarlos.

### Flujo del Bug

```
Nodo cae → RequestError → jobs marcados "error"
Nodo vuelve → /jobs/status responde 200 → process_map vacío
Sync loop: state=STOPPED, job.status="error"
  → STOPPED handler: "if status not in ['stopped','error','failover']" → FALSE
  → No hace nada → job muerto en "error" para siempre
```

---

## Cambios en `monitor.py`

### 1. Recovery al detectar nodo ONLINE (`process_node_thread`)

Cuando un nodo transiciona de `offline` a `online`, inmediatamente recupera todos los jobs en "error" del nodo y los re-lanza:

```python
stuck_jobs = db.query(models.EncodingJob).filter(
    models.EncodingJob.node_id == node.id,
    models.EncodingJob.status == "error"
).all()
for job in stuck_jobs:
    job.status = "starting"
    job.auto_started = True
    job.updated_at = datetime.now()
    send_command(job, "start", req_session)
```

### 2. Recovery en sync loop (respaldo)

En cada ciclo de sync, si un job está en `"error"` y el proceso no corre en el agente (`state=STOPPED`), se reintenta el start cada 30s:

```python
elif job.status == "error":
    if job.updated_at and (datetime.now() - job.updated_at).total_seconds() > 30:
        job.status = "starting"
        job.auto_started = True
        send_command(job, "start", req_session)
```

---

## Archivos Modificados

| Archivo | Cambio |
|---------|--------|
| `monitor.py` | Dos mecanismos de recovery: (1) transición offline→online, (2) sync loop cada 30s |
| `core/version.py` | `VERSION_PATCH = 1` → **v2.4.1** |

---

## Versiones

| Versión | Cambio |
|---------|--------|
| v2.4.0 → v2.4.1 | Fix: recovery automático de jobs en "error" tras reconnect de nodo |

---

## Pendiente

- Monitorear comportamiento de mac02 tras reinicio para validar que los jobs se recuperan automáticamente
- Configurar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para alertas Telegram
