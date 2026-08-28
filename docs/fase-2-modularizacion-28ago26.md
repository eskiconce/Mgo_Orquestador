# Fase 2: Modularización — v2.10.0

**Fecha:** 28 Aug 2026
**Versión:** v2.9.0 → v2.10.0

## Objetivo

Dividir `main.py` (1051 líneas, 53 rutas) en módulos independientes por dominio, facilitando mantenimiento y desarrollo colaborativo.

## Cambios realizados

### Estructura de routers

```
routers/
├── auth.py          (3 rutas)  — login, logout
├── users.py         (3 rutas)  — CRUD usuarios
├── dashboard.py     (1 ruta)   — dashboard principal
├── nodes.py         (8 rutas)  — CRUD nodos + health
├── channels.py      (6 rutas)  — CRUD canales + analyze-source
├── processes.py     (11 rutas) — CRUD jobs + start/stop/restart/move/logs
├── drm.py           (7 rutas)  — KMS UI + DRM health/stats
├── orchestrator.py  (8 rutas)  — builders + rotate-key + analyze
├── internal.py      (3 rutas)  — failover + analyze-callback
└── ui_logs.py       (3 rutas)  — recordings, system-logs, monitor-logs
```

### `core/deps.py`

Dependencias compartidas:
- `get_current_user()` — autenticación JWT
- `require_role(*roles)` — control de acceso por rol
- `templates` — Jinja2Templates
- `pwd_context` — bcrypt hashing
- `create_access_token()` — JWT tokens

### `main.py` reducido

**Antes:** 1051 líneas con 53 rutas + lógica de auth + helpers.
**Ahora:** ~80 líneas — solo setup de FastAPI, includes de routers, y exception handler.

## URLs — Sin cambios

Todas las URLs permanecen idénticas. No hay breaking changes.

## Rollback

```bash
git revert d791ad6  # v2.10.0 commit
```

## Archivos nuevos

| Archivo | Descripción |
|---------|-------------|
| `core/deps.py` | Dependencias compartidas |
| `routers/auth.py` | Login/logout |
| `routers/users.py` | CRUD usuarios |
| `routers/dashboard.py` | Dashboard |
| `routers/nodes.py` | CRUD nodos |
| `routers/channels.py` | CRUD canales |
| `routers/processes.py` | CRUD jobs |
| `routers/drm.py` | DRM/KMS |
| `routers/orchestrator.py` | Orquestación |
| `routers/internal.py` | Endpoints internos |
| `routers/ui_logs.py` | Logs UI |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `main.py` | Reescrito (~80 líneas, solo includes) |
| `core/version.py` | v2.10.0 |
| `CHANGELOG.md` | Entrada v2.10.0 |
