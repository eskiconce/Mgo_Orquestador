# Changelog — Encoder Orchestrator

## v2.16.0 (02 Sep 2026) — Issue #2: Restart callback para discontinuidades

- Nuevo: endpoint `POST /api/internal/encoder-restart` — recibe notificación del encoder al reiniciar FFmpeg
- Nuevo: `signal_analyzer.py` acepta `--restart-callback-url` y lo incluye en el script generado
- Fix: cuando encoder reinicia por discontinuidades (>20), ahora notifica al orquestador
- Fix: orquestador actualiza `started_at` del job → `check_and_heal_children()` resync el packager
- Orchestrator envía `restart_callback_url` junto con `callback_url` al iniciar análisis
- OpenSpec: change `issue-2-restart-callback`

## v2.15.0 (02 Sep 2026) — Issue #1: Mejoras post-plan

- Fix: `deploy.sh` ahora detecta archivos nuevos (`--diff-filter=AM`)
- Nuevo: countdown visible en barra de progreso de análisis de señal ("42s restantes")
- Nuevo: retry automático de análisis (hasta 2 reintentos con 3s delay)
- Nuevo: `SignalAnalysis` model — historial de análisis guardado en BD
- Nuevo: endpoint `/api/internal/analyze-callback` guarda historial automáticamente
- Nuevo: alerta Telegram cuando encoder se reinicia por discontinuity
- OpenSpec: change `issue-1-mejoras`

## v2.14.0 (28 Aug 2026) — Fase 6: Deploy

- Fix: eliminados `deploy.exp` y `deploy_file.exp` (scripts expect frágiles)
- Fix: `deploy.sh` ahora usa SSH key (`~/.ssh/id_opencode`) — sin passwords
- Nuevo: health check pre-deploy y post-deploy automático
- Nuevo: `deploy.sh --test` para verificar conexión + versión
- Nuevo: `deploy.sh --health` para verificar health endpoint
- OpenSpec: change `fase-6-deploy`

## v2.13.0 (28 Aug 2026) — Fase 5: Seguridad

- Fix: endpoints internos (`analyze-callback`, `trigger-failover`) ahora requieren `X-API-Key`
- Nuevo: `core/errors.py` — esquema de error unificado (`ErrorResponse`, `SuccessResponse`)
- Nuevo: `core/rate_limit.py` — rate limiting por IP (60 req/min)
- Fix: exception handler devuelve JSON consistente `{"success": false, "error": ..., "status_code": ...}`
- OpenSpec: change `fase-5-seguridad`

## v2.12.0 (28 Aug 2026) — Fase 4: Testing

- Nuevo: `tests/` — framework de tests con pytest
- Nuevo: `tests/conftest.py` — fixtures (BD SQLite en memoria, TestClient)
- Nuevo: `tests/test_health.py` — 14 tests para health/readiness/metrics endpoints
- Nuevo: `tests/test_api.py` — 8 tests para auth/endpoints protegidos
- Nuevo: `pyproject.toml` — configuración de pytest
- Fix: type hints `Optional[T]` en vez de `T | None` (compat Python 3.9)
- 22 tests pasando, cobertura de health + auth + endpoints principales
- OpenSpec: change `fase-4-testing`

## v2.11.0 (28 Aug 2026) — Fase 3: Observabilidad

- Nuevo: `GET /api/health` — health check con versión, DB, uptime, métricas de jobs/nodos/canales
- Nuevo: `GET /api/health/ready` — readiness probe (200 si DB OK)
- Nuevo: `GET /api/metrics` — métricas detalladas (jobs por estado/tipo, nodos por tipo/estado, canales con/sin encoder)
- Nuevo: `core/logging_service.py` — soporte para JSON format via `LOG_FORMAT=json`
- Nuevo: `routers/health.py` — router de salud y métricas
- OpenSpec: change `fase-3-observabilidad`

## v2.10.0 (28 Aug 2026) — Fase 2: Modularización

- Nuevo: `routers/` — main.py dividido en 10 routers por dominio (auth, users, dashboard, nodes, channels, processes, drm, orchestrator, internal, ui_logs)
- Nuevo: `core/deps.py` — dependencias compartidas (auth, roles, templates)
- Nuevo: `routers/internal.py` — endpoints internos (failover, analyze-callback)
- Nuevo: `routers/orchestrator.py` — orquestación de jobs y builders
- main.py reducido de 1051 a ~80 líneas (solo setup + router includes)
- OpenSpec: change `fase-2-modularizacion` (router split)

## v2.9.0 (28 Aug 2026) — Fase 1: Fundación

- Nuevo: `core/config.py` centralizado con `python-dotenv` — todas las constantes usan `os.getenv()` con defaults
- Nuevo: `.env.example` como plantilla de configuración
- Nuevo: `requirements.txt` con dependencias del proyecto
- Nuevo: `core/http_client.py` — factory unificada para httpx sync/async con pool compartido
- Fix: `database.py` importa `DATABASE_URL` desde config (antes hardcodeada)
- Fix: `monitor.py` importa config desde `core.config` (eliminados duplicados)
- Limpieza: eliminados bloques de código comentado en `monitor.py` (~100 líneas) y `main.py` (~30 líneas)
- OpenSpec: change `fase-1-fundacion` (config, requirements, cleanup, http-client)

## v2.8.6 (27 Aug 2026) — Fix recovery post-reinicio

- Fix: crash en `process_node_thread` cuando agente devuelve formato inesperado en `/jobs/status` (lista de strings en vez de dicts) — validación defensiva en línea 705
- Fix: NODE_UP recovery ahora detecta jobs "running"/"starting" que no existen en el agente (caso down <45s donde ghost cleanup no se ejecuta) — los marca como error y los relanza
- Fix: `process_map` construido con validación de tipo para evitar `TypeError: string indices must be integers`

## v2.8.5 (26 Aug 2026) — Recuperación automática de canales

- Fix: campo `numero_canal` → `num_canal` en `services/vod_service.py` (bug que rompía la búsqueda de canal en alertas tsmonitor)
- Fix: lookup de canal en tsmonitor usa `unique_id` con fallback a `id` numérico
- Nuevo: NODE_UP recovery ahora relanza jobs en estado `error` Y `stopped` (antes solo `error`)
- Nuevo: filtro para no relanzar canales detenidos manualmente (usa `started_at`)
- Nuevo: reintento periódico en sync loop para jobs `error`/`stopped` en nodos activos (cooldown 60s)
- OpenSpec: change `monitoreo-recuperacion-canales` (proposal/specs/design/tasks)

## v2.8.4 (13 Aug 2026) — NUMA binding en signal_analyzer.py

- Nuevo: `numactl --cpunodebind=0 --membind=0` agregado al script generado por signal_analyzer.py (solo Linux)
- Cambio: NUMA node default 0, configurable por canal (el usuario decide manualmente)
- Detecta plataforma automáticamente: Linux usa numactl, Mac no

## v2.8.3 (12 Aug 2026) — Channel form: simplificación visual

- Cambio: audio_mapping ya no incluye `-map`, solo `0:a:X`
- Cambio: selects de Video Codec y Audio Codec ocultos (no se usan)
- Cambio: FPS/GOP unificados en un solo select global (aplica a ambos perfiles)
- Cambio: inputs de bitrate simplificados a uno por perfil (avg=max, hidden)
- Fix: placeholder de audio_mapping actualizado a `0:a:0`
- Backup: `channel_form.html.bak.{timestamp}`

## v2.8.2 (12 Aug 2026) — Analizar Señal disponible en edición de encoder

- Nuevo: botón "Analizar Señal" en modal de edición de encoder (`process_list.html`)
- Nuevo: selector de duración (1, 2, 5, 10 min) en modal de edición
- Nuevo: barra de progreso con polling en modal de edición
- Nuevo: función `analyzeSignalFromModal()` lee channel_id/node_id del modal
- Fix: `process_list.html` backup creado antes de cambios

## v2.8.1 (12 Aug 2026) — VOD deletion: soporte /storage/vod en Origins

- Nuevo: Origins buscan VOD en `/iscsi/vod` Y `/storage/vod` al eliminar
- Nuevo: `STORAGE_VOD_DIR` como segundo directorio base en Origins
- Cambio: `resolve_safe_vod_path()` retorna `tuple[Path, Path]` (target, base_dir)
- Cambio: `.trash` se crea en el mismo directorio base que la carpeta original
- Desplegado: origin1 (172.16.222.246), origin2 (172.16.222.248), origin3 (172.16.222.250)
- Pendiente: origin4 (172.16.222.252) sin acceso SSH

## v2.8.0 (11 Aug 2026) — Signal Analyzer: modo async + fixes

- Nuevo: análisis de señal funciona en modo async (no bloquea el orquestador)
- Nuevo: encoder ejecuta análisis en background con callback al orquestador
- Nuevo: frontend usa polling cada 3s para consultar resultado
- Nuevo: `POST /api/internal/analyze-callback` — orquestador recibe script del encoder
- Nuevo: `GET /api/internal/analyze-status/{task_id}` — frontend consulta estado
- Fix: `callback_url` apunta a `172.16.223.5` (orquestador) en vez de `127.0.0.1` (encoder)
- Fix: encoder agents devuelven `202 Accepted` en vez de `200 OK`
- Fix: `import requests` agregado al Mac agent
- Fix: `audio_stream_id` corregido a `audio_mapping_val` en script generado
- Fix: GOP simplificado — usa `gop_p1` de la BD para ambos perfiles
- Fix: `gop_p2` eliminado de `signal_analyzer.py` y encoder agents
- Fix: `nginx proxy_read_timeout` aumentado a 660s para endpoint de análisis
- Cambio: `signal_analyzer.py` desplegado en todos los encoders (Linux y Mac)
- Pendiente: análisis con subtítulos

## v2.7.5 (07 Aug 2026) — Recovery automático post-downtime de nodo

- Nuevo: cuando un nodo vuelve a ONLINE, el monitor busca jobs en estado "error" y los relanza automáticamente
- Nuevo: envía `/jobs/create` con script comprimido al agente para regenerar servicio + script
- Nuevo: log `NODE_RECOVERY` con cantidad de jobs relanzados
- Fix: jobs quedaban en "error" permanentemente después de ghost cleanup (fix documentado pero nunca implementado)
- Imports: `base64` y `zlib` agregados a monitor.py

## v2.7.4 (06 Aug 2026) — Fix encoder "file not found" al reiniciar

- Fix: recrear job encoder via `/jobs/create` genera script `.py` y actualiza servicio systemd
- Causa: agente guardaba script como `.py` pero archivo en disco era `.sh` tras reemplazo manual
- Solución: enviar `/jobs/create` con script comprimido → agente regenera `.py` + actualiza systemd
- Canal afectado: Espn4 (job 149) en encoder_02

## v2.7.3 (01 Aug 2026) — Fix rotate-key usa ruta para KMS

- Fix: endpoint `/orchestrator/rotate-key` usa `channel.ruta` (igual que script packager) en vez de `channel_name`

## v2.7.2 (01 Aug 2026) — Rotación DRM individual por canal

- Nuevo: `POST /orchestrator/rotate-key/{channel_id}` — rota llave en KMS y reinicia packagers DRM del canal
- Nuevo: flujo simplificado: KMS rota key → packager reinicia → toma nueva key al arrancar
- Eliminado: `generate_packager_drm_with_keys` en builders.py (código muerto)
- Eliminado: lógica `rotate-and-build` en frontend (reemplazada por flujo simpler)
- Frontend: checkbox "Rotar llave al generar" deshabilitado (usar botón en lista de procesos)

## v2.7.1 (28 Jul 2026) — Detección timestamp discontinuity

- Nuevo: `check_timestamp_discontinuity()` detecta errores `timestamp discontinuity` en logs de encoder
- Si persiste por más de 60 segundos → reinicia el encoder automáticamente
- Limpia el estado si los errores desaparecen (nuevo incidente vs continuo)
- Notifica CMS con evento `restart` y registra en monitor log
- `_ts_discontinuity_state` se limpia periódicamente para jobs inactivos

## v2.7.0 (28 Jul 2026) — Monitoreo DRM: health + stats + dashboard

- Nuevo: campos DRM en modelo `Node` (`drm_total_users`, `drm_total_devices`, `drm_health_status`, `drm_widevine`, `drm_database`, `drm_last_stats_at`)
- Nuevo: monitor.py llama `/health` cada 10s y `/stats` cada 30s a nodos DRM
- Nuevo: `DRM_HEALTH_PORT = 8080` en monitor.py
- Nuevo: `GET /orchestrator/drm-health/{node_id}` — proxy a health del DRM
- Nuevo: `GET /api/drm/stats` — stats de todos los nodos DRM (para dashboard)
- Nuevo: `GET /api/drm/user/{user_id}` — consulta individual de sesiones DRM
- Nuevo: DRM card en dashboard muestra usuarios y dispositivos totales
- Nuevo: tabla DRM en node_list muestra columnas Usuarios y Dispositivos
- Nuevo: `fetchDrmStats()` en node_list.html para actualizar stats via AJAX
- Fix: `import json` agregado a monitor.py
- Fix: error JSON inválido del endpoint `/stats` del DRM manejado gracefully (warning en vez de crash)
- Fix: DRM `status` se actualiza a `online`/`degraded`/`offline` según respuesta de `/health`
- Alerta si `drm_total_devices > 50000` o si usuario está al límite de pantallas

## v2.6.4 (26 Jul 2026) — Desactivar TS error detection + health logs

- Desactivado: `check_encoder_ts_errors` — causaba stops prematuros por warnings benignos del encoder (Found tag, Packet corrupt, length violation)
- Desactivado: `check_encoder_health_logs` — causaba restarts por "timestamp discontinuity" común en streams UDP multicast
- Restaurado flujo de la versión estable (16may26): solo `check_and_heal_children` en el pipeline de encoders
- Las funciones quedan como código muerto para análisis futuro

## v2.6.3 (26 Jul 2026) — Fix escalada prematura post-restart

- Fix: `first_seen` se resetea a `now` después de cada restart (#1 y #2) para que los 90s de gracia cuenten desde el reinicio real, no desde el primer error
- Fix: `_prev_logs` se limpia en cada restart para evitar re-detección de errores viejos en el archivo de log

## v2.6.2 (26 Jul 2026) — Fixes TS error state stale + paradas repetidas + import requests

- Fix: `import requests` restaurado (perdido en rollback) — afectaba start/delete/logs
- Fix: `_ts_error_state` se resetea cuando el job confirma `running` en sync loop
- Fix: `first_seen` se refresca tras 120s sin errores TS (nuevo incidente = nueva escalada)
- Fix: limpieza periódica de `_ts_error_state` para jobs inactivos (cada ~10 min)

## v2.6.1 (26 Jul 2026) — DRM nodes sin agente + fix versión frontend

- Fix: nodos tipo `DRM` se marcan `online` sin health check en `process_node_thread()` (sin agente/API)
- Fix: `templates.env.globals` restaurado para mostrar `{{ version_string }}` en frontend
- Fix: dashboard DRM count ahora usa `n.tipo == 'DRM'` en vez de `EncodingJob.is_drm`

## v2.6.0 (26 Jul 2026) — Hardening de roles RBAC

- Nuevo: `require_role()` dependency helper en main.py
- Seguridad: 15+ rutas sin auth protegidas con `get_current_user` + role check (admin/operator)
- Seguridad: 15+ rutas con auth añadido check de rol (KMS, channels CRUD, nodes CRUD, processes, build scripts, job control, failover)
- Frontend: nav oculta Nodos, KMS, Usuarios para viewer en base.html
- Frontend: botones crear/editar/eliminar ocultos para viewer en channel_list, node_list, process_list, kms_users, control_buttons
- Frontend: botones de gestión de usuarios ocultos para operator en users.html (solo admin)
- Viewer: solo acceso a Dashboard, Canales (lista), Procesos (lista), Logs — sin botones de gestión

## v2.5.2 (26 Jul 2026) — Fix acción 'down' inválida en monitor

- Fix: `send_command(job, "down", ...)` → `send_command(job, "stop", ...)` en `check_encoder_ts_errors()`

## v2.5.1 (26 Jul 2026) — Fixes post-deploy gestión de usuarios

- Fix: `users_json` ahora incluye `full_name` y `email` para edición correcta en modal
- Fix: Manejo de `IntegrityError` por email duplicado con alerta visual en lugar de 500
- Fix: Validación previa de email y username duplicados con mensaje específico
- Fix: Hash de password de `ingservice` regenerado (no verificaba con bcrypt actual)
- Fix: `ingservice.role` actualizado a `admin`

## v2.5.0 (26 Jul 2026) — Gestión de usuarios y roles en frontend

- Nuevo: `GET /ui/users` — listado de usuarios con roles y estados
- Nuevo: `POST /ui/users/save` — crear/editar usuarios (solo admin)
- Nuevo: `GET /ui/users/delete/{user_id}` — eliminar usuarios (solo admin)
- Nuevo: `User.role` (admin/operator/viewer) en modelo y frontend
- Nuevo: Nav "Usuarios" en `base.html` + rol en dropdown de usuario
- Cambio: `crear_usuario.py` ahora solicita rol por CLI

## v2.4.1 (23 Jul 2026) — Simplificación notificaciones CMS

- Cambio: `notify_cms_channel_status` solo acepta `failover`/`online`
- Payload simplificado: `evento`, `unique_id`, `nombre`, `estado`, `fecha`, `hora`

## v2.4.0 (23 Jul 2026) — Scan de señal multicast

- Nuevo: `/api/analyze-source` con ffprobe, retorna codec, resolución, field_order, audio, subtítulos
- Nuevo: Modal de scan en `channel_form.html` con secciones Video / Audio / Subtítulos + "Aplicar Selección"
- Fix: `job.status="starting"` en start-job para evitar race condition con sync loop

## v2.3.1 (22 Jul 2026) — Fix started_at post-restart

- Fix: `job.started_at` se actualiza correctamente tras restart en `check_encoder_ts_errors()`

## v2.3.0 (22 Jul 2026) — Stuck encoder detection + HTTP pool

- Nuevo: Detección de encoder trabado (frame/time sin cambios por ≥3 ciclos)
- Nuevo: `_ts_error_state` persistente entre ciclos (no se resetea al no encontrar errores TS)
- Cambio: HTTP pool: `max_connections=20→50`, `max_keepalive_connections=10→20`, `pool=5.0→10.0`
