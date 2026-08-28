## Why

`main.py` tenía 1051 líneas con 53 rutas mezcladas (auth, CRUD, orquestación, DRM, logs). Difícil de mantener, testear y navegar. La modularización facilita el desarrollo colaborativo y la separación de responsabilidades.

## What Changes

- `main.py` reducido de 1051 a ~80 líneas (solo setup + router includes)
- 10 routers nuevos en `routers/`:
  - `auth.py` — login, logout (3 rutas)
  - `users.py` — CRUD usuarios (3 rutas)
  - `dashboard.py` — dashboard principal (1 ruta)
  - `nodes.py` — CRUD nodos + health (8 rutas)
  - `channels.py` — CRUD canales + analyze-source (6 rutas)
  - `processes.py` — CRUD jobs + start/stop/restart/move/logs (11 rutas)
  - `drm.py` — KMS UI + DRM health/stats (7 rutas)
  - `orchestrator.py` — builders + rotate-key + analyze (8 rutas)
  - `internal.py` — failover + analyze-callback (3 rutas)
  - `ui_logs.py` — recordings, system-logs, monitor-logs (3 rutas)
- `core/deps.py` — dependencias compartidas (auth, roles, templates)

## Impact

- **Archivos nuevos:** `core/deps.py`, `routers/` (10 archivos)
- **Archivos modificados:** `main.py`, `core/version.py`, `CHANGELOG.md`
- **Servidor:** v2.9.0 → v2.10.0
- **Sin breaking changes** — todas las rutas mantienen las mismas URLs
