# Signal Analyzer — v2.8.0

**Fecha:** 11 Agosto 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Resumen

Se integró un analizador de señal que ejecuta `signal_analyzer.py` en los encoders (Linux/Mac) para analizar la fuente multicast y generar un script de encoding optimizado. El análisis se ejecuta en modo async para no bloquear el orquestador.

---

## Arquitectura

```
Frontend                    Orquestador                    Encoder
   │                           │                             │
   ├── POST /encoder/analyze ──►│                             │
   │                           ├── POST /encoder/analyze ────►│
   │                           │◄── 202 (task_id) ───────────┤
   │◄── 202 (task_id) ────────┤                             │
   │                           │                             │
   ├── GET /analyze-status/{id}│    (cada 3s)                │
   │◄── {status: "running"} ──┤                             │
   │                           │                             ├── Análisis (5-10 min)
   │                           │                             │
   │                           │◄── POST /analyze-callback ──┤
   │                           │    {script, analysis}        │
   │                           │                             │
   ├── GET /analyze-status/{id}│                             │
   │◄── {status: "completed"} ─┤                             │
   │    {script, analysis}     │                             │
```

---

## Endpoints

### Orquestador

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/orchestrator/encoder/analyze` | POST | Inicia análisis async, retorna task_id |
| `/api/internal/analyze-callback` | POST | Recibe script del encoder (callback) |
| `/api/internal/analyze-status/{task_id}` | GET | Frontend consulta estado del análisis |

### Encoder Agent (Linux/Mac)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/encoder/analyze` | POST | Inicia análisis en background, retorna 202 |

---

## Parámetros del análisis

### Desde la BD (configurados en frontend)

| Campo DB | Uso |
|----------|-----|
| `channel.origin_multicast_ip` | source_url (IP) |
| `channel.origin_multicast_port` | source_url (Puerto) |
| `channel.multicast_ip_out` | dest_multicast_base |
| `channel.port_1080p` | Puerto perfil P1 |
| `channel.port_480p` | Puerto perfil P4 |
| `channel.unique_id` | service-id |
| `channel.channel_name` | service-name |
| `channel.burn_subtitles` | Quemar subtítulos |
| `channel.subtitle_pid` | PID del stream de subtítulos |
| `channel.audio_mapping` | Mapeo de audio |
| `channel.gop_p1` | GOP para ambos perfiles |
| `node.ip_multicast` | local_ip |

### Del análisis (detectados automáticamente)

| Parámetro | Fuente |
|-----------|--------|
| fps | Detectado del stream |
| bitrate | Recomendado según resolución |
| resolución | Según resolución source |
| deinterlace | bwdif si interlaced, none si progressive |
| audio_stream | Mejor stream de audio (prioriza español) |

---

## Frontend

- Botón "Analizar Señal" en process_form.html
- Selector de duración: 1, 2, 5, 10 minutos
- Barra de progreso con polling cada 3 segundos
- Resumen de análisis: video, calidad, warnings, recomendaciones
- Script generado se coloca en textarea

---

## Nginx

```nginx
location /orchestrator/encoder/analyze {
    proxy_pass http://127.0.0.1:9000;
    proxy_read_timeout 660s;
    proxy_connect_timeout 10s;
}
```

---

## Archivos

| Archivo | Ubicación |
|---------|-----------|
| `signal_analyzer.py` | `/home/canales/scripts/` (Linux), `/Users/soporte/canales/scripts/` (Mac) |
| `main.py` (orquestador) | `/opt/encoder-orchestrator/main.py` |
| `main.py` (Linux agent) | `/opt/api/main.py` |
| `main.py` (Mac agent) | `/Users/soporte/encoder-agent/main.py` |
| `process_form.html` | `/opt/encoder-orchestrator/templates/process_form.html` |

---

## Pendiente

- Análisis con subtítulos (burn_subtitles)
