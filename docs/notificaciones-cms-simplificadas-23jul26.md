# Simplificación Notificaciones CMS — solo failover/online

**Versión:** v2.4.0 → v2.4.1  
**Fecha:** 23 Julio 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Resumen

Se simplificó el envío de notificaciones al webhook del CMS. La función `notify_cms_channel_status` ahora solo envía dos eventos: `failover` (cuando el encoder principal deja de procesar) y `online` (cuando se recupera). Todos los demás eventos fueron pausados (comentados).

---

## Archivos Modificados

### `core/version.py`
- `VERSION_PATCH = 0 → 1` → **v2.4.1**

### `monitor.py`

#### Función `notify_cms_channel_status` (línea 59)

**Antes:**
```python
def notify_cms_channel_status(channel_id, status_event, description):
    payload = {
        "event": "channel_status",
        "canal": channel.ruta if channel.ruta else channel.channel_name.lower().replace(" ", "_"),
        "status": status_event,
        "description": description,
        "timestamp": datetime.now().isoformat()
    }
```

**Después:**
```python
def notify_cms_channel_status(channel_id, status_event):
    if status_event not in ("failover", "online"):
        return
    payload = {
        "evento": "channel_status",
        "unique_id": channel.unique_id,
        "nombre": channel.channel_name,
        "estado": status_event,
        "fecha": now.strftime("%Y-%m-%d"),
        "hora": now.strftime("%H:%M:%S")
    }
```

#### Notificaciones activas (2)

| Línea | Evento | Contexto |
|-------|--------|----------|
| 94 | `failover` | Encoder padre no está `running`/`starting` → se activa failover |
| 804 | `online` | Encoder principal recuperado → se restaura packager a señal normal |

#### Notificaciones pausadas (8)

| Línea | Evento anterior | Motivo |
|-------|-----------------|--------|
| 125 | failover por corrupción en logs packager | En pausa |
| 281 | backup_activated por errores TS | En pausa |
| 294 | critical_ts_error tras agotar reintentos | En pausa |
| 467 | warning por reinicio preventivo severo | En pausa |
| 552 | error por nodo offline abruptamente | En pausa |
| 654 | error por proceso encoder caído | En pausa |
| 678 | error por fallo al iniciar encoder | En pausa |
| 690 | offline por encoder detenido | En pausa |

---

### Servicios Reiniciados
- `encoder-monitor.service`
- `encoder-api.service`
