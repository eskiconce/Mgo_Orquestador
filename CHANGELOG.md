# Changelog — Encoder Orchestrator

## v2.18.0 (29 Sep 2026) — Issue #7: Sistema de reglas configurable para alertas

- Nuevo: modelo `AlertRule` — reglas configurables para alertas de plataformas externas
- Nuevo: tabla `alert_rules` con reglas por defecto (comportamiento actual preservado)
- Nuevo: `services/alert_normalizer.py` — normalización de alertas a formato interno unificado
- Nuevo: `services/alert_rule_engine.py` — motor de reglas con búsqueda por prioridad y cooldown
- Nuevo: `routers/alert_rules.py` — CRUD completo para gestión de reglas (API + UI)
- Nuevo: `/ui/alert-rules` — interfaz de configuración de reglas con filtros
- Modificado: `services/vod_service.py` — endpoint tsmonitor ahora usa motor de reglas
- Modificado: `main.py` — registro de router alert_rules
- Nuevo: `scripts/migrations/002_add_alert_rules.sql` — migración con reglas por defecto
- Nuevo: `docs/alert-rules-workflow.html` — diagrama de flujo interactivo
- Nuevo: `docs/alert-rules-diagram.md` — diagrama Mermaid
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/7

## v2.17.2 (26 Sep 2026) — Fix: Rate limit + import datetime

- Fix: `monitor/__init__.py` — import faltante de `datetime` causaba `NameError` en el loop de monitoreo
- Fix: rate limit aumentado de 60 a 300 requests/min por IP
- Fix: endpoints internos del monitor (`/api/internal/`, `/api/metrics`, `/api/nodes/stats`) excluidos del rate limit
- Fix: endpoints UI (`/ui/`, `/login`, `/orchestrator/`) excluidos del rate limit

## v2.17.1 (26 Sep 2026) — Issue #6: Limpieza pendiente v2.17.0

- Eliminado: `estructura.txt` (desactualizado, reemplazado por README.md)
- Eliminado: `structura.txt` (typo vacío creado accidentalmente al intentar borrar el original)
- Eliminado: `scripts/add_uptime_tracking_columns.py` (credenciales MySQL hardcodeadas, reemplazado por migración 001)
- Docs: README.md ahora incluye sección sobre `run_migrations.py` y comandos de migración
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/6

## v2.17.0 (26 Sep 2026) — Issue #5: Refactor, limpieza y modularización

- Fix: `database.py` ahora falla explícitamente (`sys.exit(1)`) si no puede crear el engine de BD (antes solo hacía `print()`)
- Nuevo: `verify_db_connection()` se ejecuta al arranque en `main.py` (fail-fast si DB no conecta)
- Eliminado: `templates/dashboard-nuevo.html` (duplicado no utilizado)
- Eliminado: `structura.txt` (desactualizado, reemplazado por README.md)
- Nuevo: `scripts/run_migrations.py` — sistema de migraciones de esquema con tracking en tabla `schema_migrations`
- Nuevo: `scripts/migrations/` — archivos `.sql` numerados para migraciones de esquema
- Eliminado: `scripts/add_uptime_tracking_columns.py` (credenciales hardcodeadas, reemplazado por migración 001)
- Nuevo: `monitor/` paquete modularizado (1170 líneas → 6 módulos)
  - `monitor/alerts.py` — CMS notifications + Telegram
  - `monitor/checks.py` — TS errors, discontinuity, drop frames
  - `monitor/commands.py` — send_command, kill_flow_safety
  - `monitor/health.py` — Node health checks + restart detection
  - `monitor/recovery.py` — Ghost cleanup, node recovery, failover
  - `monitor/__init__.py` — Orquestación del loop principal
- Nuevo: `README.md` — Documentación de setup, variables de entorno, estructura, tests y deploy
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/5

## v2.16.3 (21 Sep 2026) — Issue #4: Encoder restart detection via uptime tracking