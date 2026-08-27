# Mejoras Proceso de Borrado VOD — 13 Julio 2026

## Problema
El proceso automático de limpieza de VODs no eliminaba algunas carpetas en los Origins. No había control de reintentos, el callback del Origin no incluía autenticación, y no existía estado intermedio para evitar re-envíos.

---

## Cambios en Origin API (4 servidores)

| Archivo | Servidores |
|---------|------------|
| `/opt/api/mainvod.py` | Origin_1 (172.16.222.246), Origin_2 (172.16.222.248), Origin_3 (172.16.222.250), Origin_4 (172.16.222.252) |

### 1. Callback con autenticación
- **Antes**: `requests.post(url, json=payload)` — sin headers
- **Ahora**: `requests.post(url, json=payload, headers={"X-API-Key": SECRET_TOKEN})` — incluye API key

### 2. Borrado síncrono con verificación
- **Antes**: `subprocess.Popen(["rm", "-rf", ...])` sin esperar resultado. El callback se enviaba inmediatamente como "success" antes de que el disco liberara los archivos.
- **Ahora**: `proc = Popen(...); proc.wait()` — espera que `rm -rf` termine y verifica `returncode == 0`. Si falla, envía `status: "error"` con el código de retorno.

### 3. Timeout de callback aumentado
- De 5s a 10s

---

## Cambios en Orquestador

| Archivo | Servidor |
|---------|----------|
| `services/vod_service.py` | orquestador-ott (172.16.223.5) |
| `models.py` | orquestador-ott |
| `templates/recordings_list.html` | orquestador-ott |
| `core/version.py` | orquestador-ott |

### 1. Días de retención
- **Antes**: 7 días para VODs sin marca de uso
- **Ahora**: **8 días** (según política del negocio)

### 2. Estado intermedio "deleting"
- **Antes**: el registro quedaba como `status='success'` durante todo el proceso de borrado. El cleanup podía enviar múltiples órdenes de borrado para el mismo VOD.
- **Ahora**: al enviar la orden de borrado, el registro pasa a `status='deleting'` y se guarda `cleanup_started_at=now()`. El cleanup excluye estos registros.

### 3. Stale lock timeout (1 hora)
- Si un registro queda en `status='deleting'` por más de 1 hora sin recibir callback, el cleanup lo recupera automáticamente como `status='success'` para reintentarlo.

### 4. Sistema de reintentos (MAX_RETRY=3)
- **Antes**: sin límite de reintentos, intento infinito sin registro de errores.
- **Ahora**: máximo 3 intentos. Cada fallo incrementa `retry_count` y guarda `last_error`. Al llegar a 3, se alerta "Requiere intervención manual" y se omite en ciclos siguientes.

### 5. Manejo de errores en webhook
- **Antes**: si el Origin reportaba error en el borrado, no se hacía nada (solo se ignoraba).
- **Ahora**: si el callback llega con `status != "success"`, el registro vuelve a `status='success'`, se incrementa `retry_count`, se guarda `last_error` y se resetea `cleanup_started_at` para permitir reintento.

### 6. Auth en webhook (no bloqueante)
- Se validó `X-API-Key` en `/api/internal/vod-webhook`. Por ahora solo registra advertencia si falta o es inválida, no bloquea la petición.

### 7. Rotación de registros antiguos en DB
- **Nuevo**: en cada ciclo de cleanup se eliminan registros de `recordings` con `created_at` > 90 días, sin importar su estado (success, error, deleted, etc.).

### 8. Reporte de cleanup mejorado
- **Antes**: `"Se evaluaron X registros"`
- **Ahora**: `"Enviadas: X, Errores: Y, Saltados (max_retry): Z"`

### 9. Frontend Vod.Log actualizado
- Nueva columna **"Limpieza"** que muestra:
  - Contador de reintentos (`retry_count / 3`)
  - Último error (`last_error`) en rojo
  - Timestamp de la orden de borrado (`cleanup_started_at`)
- Nuevo badge **"BORRANDO"** (cyan) para estado `deleting`
- Filtro por estado incluye opción "BORRANDO"
- Nuevo filtro **"Bloqueo"** con opciones: TODOS / EN USO / LIBRE (filtra por `in_use`)

---

## Nuevos campos en base de datos

Tabla `recordings` en `encoder_orchestrator`:

| Campo | Tipo | Propósito |
|-------|------|-----------|
| `retry_count` | INT DEFAULT 0 | Contador de reintentos de borrado |
| `last_error` | VARCHAR(255) | Último error reportado por el Origin |
| `cleanup_started_at` | DATETIME | Cuándo se envió la última orden de borrado |

---

## Versiones

| Versión | Cambio |
|---------|--------|
| v1.0.0 | Integración KMS (major) |
| v1.0.1 | Front Vod.Log: columna Limpieza + badge BORRANDO (patch) |
| v1.0.2 | Rotación de registros >90 días en DB (patch) |
| v1.0.3 | Front Vod.Log: filtro por Bloqueo (EN USO / LIBRE) (patch) |

---

## Servidores actualizados

| Servidor | IP | Archivos modificados | Servicio reiniciado |
|----------|-----|----------------------|---------------------|
| Origin_1 | 172.16.222.246 | mainvod.py | api-vod |
| Origin_2 | 172.16.222.248 | mainvod.py | api-vod |
| Origin_3 | 172.16.222.250 | mainvod.py | api-vod |
| Origin_4 | 172.16.222.252 | mainvod.py | api-vod |
| Orquestador | 172.16.223.5 | vod_service.py, models.py, recordings_list.html, version.py | encoder-api |

---

## Flujo final de borrado

```
Cleanup (cada ciclo)
  → busca: status='success' AND deleted_at IS NULL AND retry_count < 3
  → set status='deleting', cleanup_started_at=now()
  → POST /delete/ a Origin (con callback_url)
  → si Origin no responde: status vuelve a 'success', retry_count++
  → si retry_count >= 3: alerta, se omite

Origin
  → resuelve path, mueve a .trash/ (atómico, <5ms)
  → proc.wait() para rm -rf (síncrono)
  → callback con X-API-Key

Webhook Orquestador
  → success: status='deleted', deleted_at=now(), retry_count=0
  → error: status='success', retry_count++, cleanup_started_at=NULL

Stale lock (>1h en status='deleting')
  → cleanup recupera como 'success' para reintentar

Rotación (>90 días)
  → elimina registros con created_at > 90 días
```
