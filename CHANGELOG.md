# Changelog — Encoder Orchestrator

## v2.22.1 (2 Oct 2026) — Issue #15: Mover Nodo de Encoder sincroniza IP multicast del script

- Fix: **`move_job` actualiza la IP multicast en `job.command` al mover un Encoder** — antes solo reasignaba `job.node_id` y el script conservaba el `LOCADDRESS`/`localaddr` del nodo origen (al iniciar, ffmpeg bindeaba la interfaz equivocada)
- Parcheo quirúrgico por patrón (`LOCADDRESS="<IP>"` con cualquier espaciado — bash sin espacios y Python con N espacios, preservándolo — y `localaddr=<IP literal>` para Mac/GPU ×3 URLs) que **preserva las ediciones manuales** del script y la referencia `localaddr=$LOCADDRESS`/`{LOCADDRESS}`; defensivo con `command` vacío o `ip_multicast` None
- Tests: 10 nuevos (`tests/test_move_job_ip.py`) — suite completa: 113 en verde
- Fuera de alcance (deferido): mover Packager (`INTERFACE=`), regeneración completa, validación en `start-job`
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/15

## v2.22.0 (2 Oct 2026) — Issue #14: Numeración de streams por tipo + subtítulo PID relativo

- Modificado: **modal de escaneo numera `Stream #` por tipo desde #0** — video, audio y subtítulos cada grupo inicia en #0 (antes índice global ffprobe: audio mostraba #1 mientras enviaba `0:a:0`); el PID MPEG real se conserva informativo junto al número
- Modificado: **`subtitle_pid` como ordinal de subtítulo** — el radio envía el ordinal dentro de subtítulos (1er sub → 0, antes índice global → 7); el auto-fill tras escaneo usa el mismo criterio; placeholder `Ej: 0` (antes `Ej: 11`) — coherente con `audio_mapping` (`0:a:0`) y con los defaults de los agents (`0:s:0`)
- Tests: regresión completa en verde (103)
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/14
- Fuera de alcance (deferido): `/api/analyze-source` (campos FPS/field_order), `services/builders.py` (interpretación `0:{N}` → `0:s:{N}`), migración BD de 3 canales con burn activo, agents respetando `subtitle_pid`

## v2.21.0 (2 Oct 2026) — Issue #13: Mejoras al front de canales

- Nuevo: **validación de nombre de canal sin espacios** — JS al enviar (mensaje en español) + `save_channel` responde 400; placeholder corregido a `Ej: TVN_HD`
- Eliminado: **switch DRM del formulario de canales** — era UI muerta (`save_channel` nunca recibía `is_drm` y `Channel.is_drm` no se leía); DRM solo opera a nivel de proceso/packager en `process_form.html` (sin cambios)
- Nuevo: **Program ID = Número Canal MGO** — `program_id = int(unique_id)` en todo guardado; textbox manual y botón "Fijar Mapeo" reemplazados por campo readonly sincronizado en vivo; el escaneo ya no sobrescribe `program_id` (el detectado solo es informativo en el modal); `unique_id` debe ser numérico (400 si no)
- Modificado: **bitrate perfil 1 default `4500k`** (antes 6000k en alta) y el escaneo asigna `4500k` (antes 7000k/5000k/4000k según resolución detectada); campo editable (parámetro base); `bitrate_high_max` siempre emparejado a `bitrate_p1` (JS en el form + backend) para coherencia entre el encode de ffmpeg y el ancho de banda Shaka (`services/builders.py`)
- Docs: `docs/rotacion-llaves-drm-15jul26.md` corregido (sección de formulario de canales)
- Tests: 9 validaciones de `save_channel` + 2 de render del formulario (suite completa: 103 en verde)
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/13

## v2.20.0 (30 Sep 2026) — Issue #12: Anti-zombie + crash-loop sync + eventos CMS

- Fix: **anti-zombie efímero** — un proceso RUNNING sin permiso con uptime < 30s ya no se adopta como `running`; se registra `ZOMBIE_UNSTABLE` y se marca `error` con `started_at=None` (corta el ciclo crash-loop: sin CMS offline, sin PROCESS_SYNCED, sin RECOVERY-RETRY). Adopción recién tras 30s continuos de RUNNING (ventana en memoria cuando el agente reporta `start=0`)
- Nuevo: dedupe de `ZOMBIE_DETECTED` — máximo 1 evento por job cada 5 min (consola + BD juntas)
- Nuevo: rate-limit de notificaciones CMS — omite webhook/consola/fila si el mismo `(canal, evento)` se notificó hace < 10 min (`cms.rate_limit_sec` en app_settings, default 600s)
- Nuevo: eventos `CMS_OFFLINE/ONLINE/ERROR/WARNING/RESTART` persistidos en `monitor_logs` cuando el webhook sí se envía
- Fix: `log_monitor_event` **sin `db.commit()` propio** — eliminados los deadlocks MySQL 1213; commits explícitos agregados solo en los paths que perderían eventos (ruta offline del monitor, NODE_UP/NODE_RECOVERY, ENCODER_RESTART/PACKAGER_RESTART en `internal.py`, ENCODER_RESTART_RECOVERY)
- Fix: timestamp consola/BD idéntico — `log_monitor_event` trunca microsegundos (el `DATETIME(0)` de MySQL redondeaba +1s respecto a la consola)
- Fix: `stop_job` honesto — HTTP != 200 o fallo de red del agente → HTTP 502 y el job **NO** se marca `stopped` (eliminado el `except: pass` silencioso)
- Modificado: `/ui/monitor-logs` — dropdown con los 29 tipos de evento reales del sistema + badges consistentes
- Cambio OpenSpec `zombie-crashloop-sync` **completo**: Fase A (orquestador, v2.20.0) + Fase B (`Api_agent-linux` v1.5.0 — StartLimit anti crash-loop 3/60s, stop verificado con normalización `reset-failed`, mapeo `activating(auto-restart)→BACKOFF` / `failed→FATAL` en `/jobs/status`, fix parseo del marcador `●` de `list-units` y syntax error que impedía ejecutar v1.4.0)
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/12

## v2.19.0 (29 Sep 2026) — Issue #10: Parámetros Generales + fuentes de alertas

- Nuevo: dropdown **Parámetros Generales** en menú (Usuarios + Parámetros; Reglas Alertas y KMS sin cambios)
- Nuevo: `/ui/settings` — configuración de Telegram, Correo (SMTP | Microsoft Graph OAuth), CMS, API-key global y CRUD de fuentes de alertas
- Nuevo: tabla `app_settings` — parámetros clave-valor en BD (migración `003_app_settings_alert_sources.sql`)
- Nuevo: tabla `alert_sources` + CRUD con token por fuente y regeneración
- Nuevo: endpoint genérico `POST /api/fuentes/{slug}/alertas` — payload estilo TSMonitor, auth `x-api-key` por fuente (404/403 según estado)
- Nuevo: `services/email_service.py` — envío SMTP (TLS/SSL) y Microsoft Graph (client_credentials) con botón "Probar envío"
- Nuevo: `services/settings_service.py` — lectura/escritura de parámetros con fallback a defaults
- Modificado: API-key global migra de `core/config.py` a BD (`security.api_key`) — efecto inmediato, comparación con `compare_digest`, fallback al default
- Modificado: `notify_telegram` y `notify_cms_channel_status` respetan toggles y parámetros desde BD
- Modificado: `source` de reglas de alerta alimentado desde `alert_sources` (fin del hardcoded `["tsmonitor","packager","encoder","any"]`)
- Modificado: `templates/alert_rules.html` — dropdown de fuentes cargado desde API
- Modificado: ingestión tsmonitor refactorizada a `services/alert_intake.py` (comportamiento idéntico preservado)
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/10

## v2.18.2 (29 Sep 2026) — Issue #9: Fix alert_rules.html usa base.html

- Fix: `templates/alert_rules.html` — reescrito para usar `{% extends "base.html" %}` como el resto de páginas
- Fix: eliminada sidebar duplicada del template
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/9

## v2.18.1 (29 Sep 2026) — Issue #8: Fix navegación + import Request

- Fix: `templates/base.html` — agregado menú "Reglas Alertas" para admin/operator
- Fix: `routers/alert_rules.py` — import y tipo de `Request` corregido en endpoint UI
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/8

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