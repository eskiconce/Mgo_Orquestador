# Monitoreo de Errores TS (mpegts) y Conmutación Automática a Fuente de Respaldo

**Versión:** v2.1.0 → v2.3.1  
**Fecha:** 23 Julio 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Resumen

Sistema de detección y escalado automático ante errores de demux MPEG-TS en encoders y estancamiento de ffmpeg, con capacidad de conmutar a una fuente multicast de respaldo cuando está configurada.

---

## v2.1.0 → v2.2.0 (23 Julio 2026)

### Archivos Modificados

#### `core/version.py`
- `VERSION_MINOR = 1 → 2` → **v2.2.0**

#### `services/builders.py`
- `generate_linux_encoder_bash(channel, node, include_subtitles=None, **use_backup=False**)`
- `generate_mac_encoder_bash(channel, node, include_subtitles=None, **use_backup=False**)`
- Cuando `use_backup=True` y existe `origin2_multicast_ip/port`, la fuente de entrada del encoder cambia a la de respaldo
- Nueva función: `compress_command(script)` — comprime script con zlib + base64

#### `main.py`
- Endpoints `/orchestrator/encoder-linux/build` y `/orchestrator/encoder-mac/build` ahora pasan `use_backup=channel.active_origin == "backup"`

#### `monitor.py`
Nuevas funciones para monitoreo de errores TS:

| Función | Propósito |
|---|---|
| `notify_telegram(message)` | Envía alerta HTML a Telegram (si token configurado) |
| `check_encoder_ts_errors(db, job, req_session)` | Detecta errores `"length violation"`, `"Found tag"`, `"PES packet size mismatch"` en logs del encoder |
| `_try_switch_to_backup(db, job, req_session)` | Conmuta a fuente de respaldo, regenera script, actualiza comando en agente |
| `_send_final_alert(db, job, prog_name)` | Alerta final cuando se agotan todas las acciones automáticas |

### Máquina de Estados — Escalado Automático

```
[Error TS detectado]
       │
       ▼
┌─────────────────┐    ≥30s persistente
│  restart #1     │─────────────────────►┌─────────────────┐
│  (reinicia       │                      │  restart #2      │
│   encoder)       │                      │  (down 60s +     │
└─────────────────┘                      │   restart)        │
                                           └─────────────────┘
       │                                            │
       │                                     ≥180s total
       ▼                                            ▼
┌─────────────────┐                      ┌─────────────────┐
│  Backup source   │◄─────────────────────│  Switch a       │
│  (si configurado)│                      │  respaldo       │
└─────────────────┘                      └─────────────────┘
       │
       │ (si persiste)
       ▼
┌─────────────────┐
│  Alerta final    │
│  (Telegram + CMS)│
└─────────────────┘
```

---

## v2.2.0 → v2.3.0 (23 Julio 2026)

### Mejoras en `monitor.py`

#### 1. Detección de Estancamiento (Stuck Encoder)

Cuando el encoder está vivo pero colgado (mismo `frame=` y `time=` repitiéndose), el monitor:

1. Extrae `frame=N` y `time=HH:MM:SS.ms` del log vía regex
2. Compara con el valor del ciclo anterior (guardado en `_ts_error_state`)
3. Si se mantiene igual por **3 ciclos consecutivos (≥30s)** → activa escalado
4. Usa la misma máquina de estados que errores TS (restart → backup → alerta)

Esto cubre el caso donde los errores TS ya scrollaron fuera de la ventana de 30 líneas pero el proceso sigue colgado.

#### 2. Conexiones HTTP para 250+ Canales

| Mejora | Antes | Después |
|---|---|---|
| `httpx.Client` connection pool | `max_connections=20, keepalive=10` | `max_connections=50, keepalive=20` |
| Pool timeout | `pool=5.0s` | `pool=10.0s` |

#### 3. Fix en reset de `_ts_error_state`
- **Antes**: se limpiaba el estado al no encontrar errores TS en ventana → se perdía el contador de estancamiento
- **Ahora**: persiste entre ciclos para tracking de stuck; solo se resetea si el encoder se recupera (cambia frame/time)

### Máquina de Estados — Actualizada

```
[Error TS activo]  o  [Encoder estancado ≥30s]
       │
       ▼
┌─────────────────┐    ≥30s
│  restart #1     │─────────────────────►┌──────────────────┐
│  (reinicia       │                      │  down 60s +      │
│   encoder)       │                      │  restart #2      │
└─────────────────┘                      └──────────────────┘
       │                                            │
       │                                     ≥180s total
       ▼                                            ▼
┌─────────────────┐                      ┌─────────────────┐
│  Backup source   │◄─────────────────────│  Switch a       │
│  (si configurado)│                      │  respaldo       │
└─────────────────┘                      └─────────────────┘
       │
       │ (si persiste)
       ▼
┌─────────────────┐
│  Alerta final    │
│  (Telegram + CMS)│
└─────────────────┘
```

---

## Fix Post-Deploy (acumulado)

### Fix 1: `job.is_running` — AttributeError
- `monitor.py:140`: `job.is_running` no existe en `EncodingJob` → reemplazado por `job.status not in ("running", "starting", "error")`
- `__pycache__` eliminado antes del restart para evitar bytecode obsoleto

### Fix 2: Prefijo incorrecto en `prog_name`
- `monitor.py:145,220`: usaba `f"enc_{channel.channel_name}_{job_id}"` pero el agente espera el prefijo `"channel_"` (convención usada en el resto del código y en los nombres de archivos de log del encoder, ej: `channel_Sony_Channel_185.err.log`)
- Corregido a `f"channel_{channel.channel_name}_{job_id}"`

### Fix 3: Patrón faltante `"Packet corrupt"`
- Los logs del encoder mostraban `[mpegts @ ...] Packet corrupt (stream = 13, ...)` que no estaba en la lista de patrones de detección
- Agregado `"Packet corrupt"` a `ts_error_patterns`

### Fix 4: Estancamiento (Stuck Encoder) — v2.3.0
- `check_encoder_ts_errors` ahora parsea `frame=` y `time=` del log ffmpeg
- Si el mismo frame/time se repite ≥3 ciclos (30s), activa escalado aunque no haya errores TS activos en ventana
- `_ts_error_state` ya no se resetea al no encontrar errores TS en ventana

### Fix 5: `started_at` no se actualizaba tras restart — v2.3.1
- `check_encoder_ts_errors` enviaba `restart` al agente pero no actualizaba `job.started_at` en BD
- El frontend (`/api/processes/status`) leía `started_at` obsoleto → mostraba uptime de 8h en vez de 5min
- Agregado `job.started_at = datetime.now(); db.commit()` después de cada `send_command("restart")` en restart #1, restart #2 y `_try_switch_to_backup`

### Patrones de detección actuales (v2.3.1):
```python
ts_error_patterns = [
    "length violation",
    "Found tag",
    "PES packet size mismatch",
    "Packet corrupt"
]
```

---

## Versiones

| Versión | Cambio |
|---------|--------|
| v2.1.0 → v2.2.0 | Implementación inicial: detección errores TS, backup source, Telegram, Fix 1-3 post-deploy |
| v2.2.0 → v2.3.0 | Stuck encoder detection, pool tuning 250+ canales, Fix 4, máquina de estados extendida |
| v2.3.0 → v2.3.1 | Fix 5: `job.started_at` no se actualizaba tras restart → uptime incorrecto en frontend |
| v2.3.1 → v2.4.0 | Scan de señal multicast con modal interactivo: selección de audio/subtítulos, detección entrelazado |
| v2.4.0 → v2.4.1 | Fix 6: recovery automático de jobs en "error" tras reconnect de nodo offline |

---

## Pendiente

- Configurar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el servidor para activar alertas Telegram
