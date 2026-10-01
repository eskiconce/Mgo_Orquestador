## Why

Issue #12: el crash-loop de systemd en encoder_03 (units `channel_{Click_Tv_181,Exprezion-TV_197,Rdo_183,Concepcion_Tv_221,LifeTime_262}.service` con `Restart=always, RestartSec=5`) generó 1,351 eventos `ZOMBIE_DETECTED`, 8,423 líneas de consola zombie y 9,558 notificaciones CMS offline en un solo día. El monitor adoptaba cada aparición efímera de RUNNING como zombie real (status → running), y al morir en el siguiente poll marcaba stopped + notificaba CMS offline, en ciclo de ~2 min. Además: `log_monitor_event` con `db.commit()` propio causó 12 deadlocks MySQL (1213); la consola mostraba eventos (`Notificando al CMS`, `RECOVERY-RETRY`) que nunca llegaban a `monitor_logs` con timestamps desalineados ~1s por redondeo de MySQL; `stop_job` marcaba `stopped` en BD aunque el agente no confirmara; y el dropdown del front no listaba la mayoría de tipos de evento.

## What Changes

- **A1** `stop_job`: sin `except: pass` — HTTP != 200 o fallo de comunicación → 502 y el job NO se marca `stopped`.
- **A2** Anti-zombie efímero en `monitor/__init__.py`: un proceso visto RUNNING sin permiso con uptime < 30s (desde `start` del agente, o por watch en memoria cuando `start=0` como en el agente Linux) no se adopta; se registra `ZOMBIE_UNSTABLE` y se marca `error` con `started_at=None` (evita recovery-retry y CMS offline). Se guarda un guard en la rama `PROCESS_SYNCED` para no sincronizar RUNNING durante la ventana inestable. Solo se adopta zombie tras 30s continuos de RUNNING.
- **A3** Rate-limit CMS: `notify_cms_channel_status` omite el webhook si ya se notificó el mismo `(canal, evento)` en los últimos 10 min (`cms.rate_limit_sec` en `app_settings`, default 600).
- **A4** Dedupe `ZOMBIE_DETECTED` cada 5 min por job (consola + BD juntas).
- **A5** `log_monitor_event` sin `db.commit()` propio (fin de los deadlocks 1213); commits explícitos agregados solo en los paths donde el evento se perdería (ruta offline del monitor, `internal.py`, `cleanup_ghost_jobs`, `ENCODER_RESTART_RECOVERY`).
- **A6** Notificaciones CMS al front: evento `CMS_{STATUS}` en `monitor_logs` cuando el webhook sí se envía.
- **A7** Timestamp consola/BD idéntico: `log_monitor_event` trunca microsegundos (evita el redondeo de MySQL DATETIME(0) que desalineaba +1s) y CMS captura el mismo instante para consola y fila.
- **A8** Dropdown de `/ui/monitor-logs` completado con todos los tipos de evento (incl. `ZOMBIE_UNSTABLE`, `CMS_*`, `ENCODER_*`, `TSMONITOR_*`, etc.) y badges consistentes.

## Impact

- Affected specs: monitoring (zombie-stability, event-integrity), cms (rate-limit), jobs (stop-honesty) — nuevos en este change.
- Affected code: `monitor/__init__.py`, `monitor/alerts.py`, `monitor/recovery.py`, `monitor/health.py`, `utils/helpers.py`, `routers/processes.py`, `routers/internal.py`, `core/config.py`, `templates/monitor_logs.html`.
- **Fase B** `Api_agent-linux` v1.5.0 (spec `agent-systemd`): B1 `StartLimitIntervalSec=60`/`StartLimitBurst=3` en `/jobs/create`, B2 stop verificado en `/jobs/control` (502 si el servicio sigue activo), B3 mapeo `activating(auto-restart)→BACKOFF` / `failed→FATAL` en `/jobs/status`, B4 docs+CHANGELOG, B5 deploy encoder_02+encoder_03. Incluye fix de syntax error en `main.py` (v1.4.0 nunca llegó a ejecutarse: servicio no reiniciado desde 2026-09-14/2026-09-07).
- Operacional: los 5 canales afectados (jobs 181/197/183/221/262) quedan detenidos permanentemente (`stop + disable` ya aplicado en encoder_03 — A0).
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/12
