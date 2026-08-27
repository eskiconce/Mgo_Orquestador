# Integración KMS/DRM — 12 Julio 2026

## Resumen
Implementación de la API KMS (Key Management System) para gestión de licencias DRM, usuarios VIP, y webhook CMS. Se agregó UI de administración en el orquestador y sistema de health checks para nodos DRM/KMS.

---

## Servidores involucrados

| Servidor | IP | Rol |
|----------|-----|-----|
| kms-license | 172.16.222.240 | KMS API (Mgo_ApiKMS) |
| orquestador-ott | 172.16.223.5 | Orquestador (UI + Proxy) |

---

## 1. KMS API — Servidor kms-license (172.16.222.240)

**Ruta**: `/opt/kms/main.py`
**Servicio**: `kms-api.service` (uvicorn, puerto 8000)

### 1.1 Redis con fallback a MySQL
- Conexión a Redis con `ConnectionPool` (20 conexiones máx.)
- Si Redis no está disponible al iniciar o durante operaciones, fallback automático a MySQL directo
- Cache de keys DRM en Redis con TTL configurable

### 1.2 Base de datos (`drm_system`)

| Tabla | Propósito |
|-------|-----------|
| `content_keys` | Claves DRM por canal/channel_id (62 claves existentes) |
| `vip_users` | Usuarios VIP con límite de pantallas |
| `license_activity` | Registro de solicitudes de licencia |
| `usuarios` | Tabla legacy migrada a `vip_users` al iniciar |

### 1.3 Endpoints de la API

| Método | Ruta | Propósito |
|--------|------|-----------|
| GET | `/health` | Health check del servicio (Redis + MySQL) |
| GET | `/api/stats` | Estadísticas: total keys, VIP activos, solicitudes 24h |
| GET | `/api/keys` | Listado de claves DRM (con paginación) |
| GET | `/api/vip/users` | Listar usuarios VIP (filtro por status) |
| GET | `/api/vip/users/{user_id}` | Detalle de usuario VIP |
| POST | `/api/vip/users` | Crear usuario VIP |
| PUT | `/api/vip/users/{user_id}` | Actualizar usuario VIP |
| DELETE | `/api/vip/users/{user_id}` | Eliminar usuario VIP |
| POST | `/api/cms/webhook` | Webhook desde CMS (crea/actualiza/elimina VIP) |
| POST | `/kms/generate` | Generar o recuperar key DRM para un canal |
| POST | `/wv-v1/license` | Licencia Widevine V1 (token fijo) |
| POST | `/wv-v2/license` | Licencia Widevine V2 (integración) |
| POST | `/wv/license` | Proxy de licencia Widevine a proveedor externo |
| GET | `/api/logs` | Obtener líneas del log de actividad |
| GET | `/api/activity` | Actividad de licencias reciente |

### 1.4 Webhook CMS
- Endpoint: `POST /api/cms/webhook`
- Autenticación: header `X-API-Key` (validado contra `CMS_API_KEY`)
- Acciones: `upsert` (crear/actualizar) y `delete`
- Payload: `{user_id, username, email, max_screens, action}`
- CMS_API_KEY: `a1b2c3d4e5f67890123456789abcdef0` (misma que AGENT_API_KEY)

### 1.5 Migración de datos legacy
- Tabla `usuarios` migrada a `vip_users` automáticamente al iniciar
- Usuario migrado: `user_lab` con límite de 10 pantallas

---

## 2. Dashboard — Health Checks de DRM/KMS

### 2.1 Problema original
El dashboard mostraba el estado de nodos DRM y KMS usando `node.status` de la base de datos, que el monitor setea basado en el puerto del agente (8000), no en el puerto real del servicio (8080 para DRM, 8000 para KMS).

### 2.2 Solución
- Health checks directos por HTTP a cada nodo:
  - **Nodos DRM**: `GET http://{ip}:8080/health` (timeout 2s)
  - **Nodo KMS**: `GET http://{ip}:8000/health` (timeout 2s)
- Las variables `drm_up_count`, `kms_up_count` y `node_summary["DRM"]`/`node_summary["KMS"]` ahora reflejan el estado real del servicio, no el de la BD.

---

## 3. Encoder / Packager — Vista combinada

### 3.1 Problema original
Los job counts de Encoder y Packager se mostraban en tarjetas separadas, ocupando espacio vertical excesivo.

### 3.2 Solución
- Tabla única "Procesos por Tipo" con columnas: Estado, Encoders, Packagers, Total
- Vista compacta que permite comparar ambos tipos lado a lado

---

## 4. Sistema de Versiones — Version Patch

### 4.1 Problema original
El archivo `version.py` no tenía campo `VERSION_PATCH` y el `bump_version.py` no soportaba parches.

### 4.2 Solución
- Nuevo campo `VERSION_PATCH` en `core/version.py`
- `bump_version.py` soporta: `patch`, `minor`, `major`
- `VERSION_PATCH` se muestra en el dashboard como `vMAJOR.MINOR.PATCH`

---

## 5. UI de Administración KMS en Orquestador

### 5.1 Nuevas rutas

| Ruta | Template | Propósito |
|------|----------|-----------|
| `/ui/kms` | `kms_dashboard.html` | Dashboard con stats del KMS |
| `/ui/kms/users` | `kms_users.html` | CRUD de usuarios VIP (modal crear/editar/eliminar) |
| `/ui/kms/keys` | `kms_keys.html` | Listado de claves DRM |
| `/ui/kms/logs` | `kms_logs.html` | Visor de logs (50-1000 líneas) |

### 5.2 Proxy
- Ruta: `/api/kms-proxy/{path}` → redirige a `http://172.16.222.240:8000/{path}`
- Requiere autenticación de sesión del orquestador (JWT)
- Configurable via `KMS_API_URL` en `core/config.py`

### 5.3 Navegación
- Dropdown "KMS" en el navbar del orquestador con enlaces a Dashboard, Usuarios VIP, Claves, Logs
- Estilo consistente con el resto del menú

---

## Versiones

| Versión | Cambio |
|---------|--------|
| v0.9.0 → v0.9.1 | DRM/KMS health checks directos + tabla Encoder/Packager (patch) |
| v0.9.1 → v0.9.2 | Version patch system (patch) |
| v0.9.2 → v1.0.0 | Integración KMS API + UI orquestador + webhook CMS (major) |

---

## Archivos modificados

### KMS API (kms-license)
- `/opt/kms/main.py` — API completa con Redis, MySQL, endpoints

### Orquestador (orquestador-ott)
- `main.py` — Dashboard health checks, rutas KMS, proxy
- `core/config.py` — `KMS_API_URL`, `KMS_API_KEY`
- `core/version.py` — Sistema de versiones con patch
- `templates/base.html` — Dropdown KMS en navbar
- `templates/kms_dashboard.html` — Dashboard KMS
- `templates/kms_users.html` — CRUD usuarios VIP
- `templates/kms_keys.html` — Listado de claves
- `templates/kms_logs.html` — Visor de logs
- `bump_version.py` — Soporte para patch
