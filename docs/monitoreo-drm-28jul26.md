# Monitoreo DRM — v2.7.0

**Fecha:** 28 Julio 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Resumen

Se integró monitoreo completo de nodos DRM (Widevine License Server) al orquestador. El monitor consulta los endpoints `/health` y `/stats` de cada nodo DRM y actualiza la base de datos con el estado, usuarios y dispositivos.

---

## Endpoints del DRM Server

El DRM server expone tres endpoints en el puerto 8080:

### GET /health
Health check del nodo DRM. Retorna:
```json
{"status":"UP","widevine":"UP","database":"UP","healthy":true}
```

### GET /stats
Dashboard de concurrencia. Retorna:
```json
{"timestamp":"2026-07-28T00:51:35Z","totalUsers":2,"totalDevices":5,"users":[...]}
```

### GET /stats/user/{userId}
Consulta individual de sesiones. Retorna:
```json
{"userId":"15181941","activeDevices":2,"maxScreens":4,"devices":["web_xxx","tv_samsung"]}
```

---

## Archivos Modificados

### `models.py`
- Nuevos campos en `Node`: `drm_total_users`, `drm_total_devices`, `drm_health_status`, `drm_widevine`, `drm_database`, `drm_last_stats_at`

### `monitor.py`
- `DRM_HEALTH_PORT = 8080` — configuración del puerto DRM
- `import json` — para manejo de errores JSON
- En `process_node_thread()`: DRM nodes consultan `/health` cada 10s y `/stats` cada 30s
- Manejo de error JSON inválido del endpoint `/stats` (warning en vez de crash)
- Alertas si `drm_total_devices > 50000` o si usuario está al límite de pantallas

### `main.py`
- `GET /orchestrator/drm-health/{node_id}` — proxy a health del DRM
- `GET /api/drm/stats` — stats de todos los nodos DRM
- `GET /api/drm/user/{user_id}` — consulta individual de sesiones

### `templates/dashboard.html`
- DRM card muestra total de usuarios y dispositivos

### `templates/node_list.html`
- Columnas Usuarios y Dispositivos en tabla DRM
- `fetchDrmStats()` para actualizar stats via AJAX cada 3s

---

## Base de Datos

Columnas agregadas a tabla `nodos`:
```sql
ALTER TABLE nodos ADD COLUMN drm_total_users INT DEFAULT 0;
ALTER TABLE nodos ADD COLUMN drm_total_devices INT DEFAULT 0;
ALTER TABLE nodos ADD COLUMN drm_health_status VARCHAR(20) DEFAULT 'unknown';
ALTER TABLE nodos ADD COLUMN drm_widevine VARCHAR(10) DEFAULT 'unknown';
ALTER TABLE nodos ADD COLUMN drm_database VARCHAR(10) DEFAULT 'unknown';
ALTER TABLE nodos ADD COLUMN drm_last_stats_at DATETIME NULL;
```

---

## Monitoreo en Tiempo Real

El monitor (`encoder-monitor.service`) ejecuta:
- **Cada 10s:** GET `/health` a cada nodo DRM → actualiza `status`, `drm_health_status`, `drm_widevine`, `drm_database`
- **Cada 30s:** GET `/stats` a cada nodo DRM → actualiza `drm_total_users`, `drm_total_devices`

---

## API del Orquestador

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/orchestrator/drm-health/{node_id}` | GET | Proxy a health del DRM |
| `/api/drm/stats` | GET | Stats de todos los nodos DRM |
| `/api/drm/user/{user_id}` | GET | Consulta individual de sesiones |

---

## Estado Actual (28 Jul 2026)

- **drm-01** (172.31.203.108): `online`, health=UP, widevine=UP, database=UP
- **Endpoint `/stats`**: devuelve JSON inválido (`"users":[,]`) — bug conocido del DRM server, manejado gracefully con warning
