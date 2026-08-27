# Gestión de Usuarios y Roles en Frontend

**Versión:** v2.4.1 → v2.5.0  
**Parches:** v2.5.1, v2.5.2, v2.6.0  
**Fecha:** 26 Julio 2026  
**Servidor:** orquestador-ott (172.16.223.5)

---

## Resumen

Se agregó gestión completa de usuarios del orquestador desde el frontend web, con tres niveles de rol: `admin`, `operator` y `viewer`. Antes solo se podían crear usuarios por CLI (`crear_usuario.py`).

En v2.6.0 se implementó hardening RBAC completo: backend protege todas las rutas con `require_role()`, y el frontend oculta botones/menús según el rol del usuario.

---

## Archivos Modificados

### `core/version.py`
- `VERSION_MINOR = 5 → 6` → **v2.6.0**
- `VERSION_PATCH = 2 → 0`

### `models.py`
- Nuevo campo `role = Column(String(20), default="operator")` en clase `User`
- Roles disponibles: `admin`, `operator`, `viewer`

### `main.py`
- **`require_role(*roles)`** — dependency helper para checks de rol
- **`GET /ui/users`** — Lista todos los usuarios (requiere admin/operator)
- **`POST /ui/users/save`** — Crear/editar usuario (solo admin). Validación: username único, email único. `try/except IntegrityError`
- **`GET /ui/users/delete/{user_id}`** — Eliminar usuario (solo admin)
- **v2.6.0:** 25+ rutas protegidas con `require_role()` o `current_user` (build scripts, job control, channels/nodes CRUD, KMS)
- Excepción: `/api/internal/trigger-failover` sin auth (uso interno por `monitor.py`)

### `templates/base.html` (v2.6.0)
- Nav items **Nodos**, **KMS**, **Usuarios** ocultos para `viewer` (`{% if user.role in ('admin', 'operator') %}`)
- Visibles para admin y operator

### `templates/users.html`
- Tabla con todos los usuarios: ID, username, nombre, email, rol (badge color), estado
- Modal de formulario para crear/editar. Botón "Nuevo Usuario" solo visible para admin
- Botones editar/eliminar solo visibles para admin
- Alerta de error (`alert-danger`) para duplicados y validaciones

### `templates/channel_list.html` (v2.6.0)
- Botones "Nuevo Canal", "Editar", "Eliminar" ocultos para viewer

### `templates/process_list.html` (v2.6.0)
- Botones "Crear Proceso", "Rotar todas DRM", Start/Stop/Restart, Move, Edit, Delete ocultos para viewer
- Botón "Logs" siempre visible para todos los roles

### `templates/kms_users.html` (v2.6.0)
- Botones "Nuevo VIP", Editar, Eliminar ocultos para viewer (requiere admin/operator)

### `templates/partials/control_buttons.html` (v2.6.0)
- Start, Restart, Stop, Edit, Delete ocultos para viewer. Logs siempre visible.

### `crear_usuario.py`
- Ahora solicita `role` al crear usuario por CLI

---

## Roles y permisos (v2.6.0)

| Rol | Dashboard | Canales | Procesos | Nodos | KMS | Usuarios | Logs | Acciones |
|-----|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **admin** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Todas |
| **operator** | ✓ | ✓ | ✓ | ✓ | ✓ | Solo ver | ✓ | Todo menos users |
| **viewer** | ✓ | Solo ver | Solo ver | ✗ 403 | ✗ 403 | ✗ 403 | ✓ | Ninguna |

### Detalle viewer:
- **Permitido:** Dashboard, Canales (lista), Procesos (lista), System.Log, Monitor.Log, VOD.Log, logs de procesos
- **Bloqueado (403):** Nodos, KMS, Usuarios, crear/editar/eliminar canales, crear/editar procesos, start/stop/restart jobs, build scripts, key rotation, failover trigger

---

## Fixes aplicados

### v2.6.0
- Hardening RBAC completo: backend protege 25+ rutas, frontend oculta botones/menús según rol
- `require_role()` dependency helper
- Fix dashboard 500: `job_statuses_enc/pkg` ahora incluye 'failover'
- Fix `/api/internal/trigger-failover` revertido a sin auth (roto por monitor.py)

### v2.5.2
- Fix: `send_command(job, "down")` → `"stop"` en monitor.py

### v2.5.1
- Fix: `users_json` incluye `full_name` y `email` para edición en modal
- Fix: Manejo de `IntegrityError` por email duplicado con alerta visual
- Fix: Hash de password de `ingservice` regenerado

---

## Pruebas realizadas (v2.6.0)

- Viewer: dashboard 200, channels 200, processes 200, logs 200, VOD 200 ✓
- Viewer: nodes 403, KMS 403, users 403, channels/new 403, processes/new 403 ✓
- Viewer: POST start-job 403, DELETE channel 403 ✓
- Admin: acceso completo a todo ✓
- Operator: acceso a todo menos gestión de usuarios (editar/crear/eliminar) ✓
