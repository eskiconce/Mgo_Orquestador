# Anti-zombie y Crash-loop Sync

**Issue:** [#12](https://github.com/eskiconce/Mgo_Orquestador/issues/12) · **Cambio OpenSpec:** `zombie-crashloop-sync` · **Versión:** v2.20.0

## Contexto

Encoder_03 tenía 5 unidades systemd con `Restart=always, RestartSec=5` en crash-loop desde el 26 Sep (`status=231/APPARMOR` + `setsockopt(IP_ADD_MEMBERSHIP)`). Resultado en un solo día: 1,351 `ZOMBIE_DETECTED`, 8,423 líneas de consola zombie y 9,558 notificaciones CMS offline.

Ciclo original (~2 min por vuelta):
1. BD dice `stopped`, el proceso aparece `RUNNING` (revenido por systemd).
2. El monitor lo adoptaba como zombie real → `running`.
3. En el siguiente poll el proceso moría → rama STOPPED → `stopped` + CMS `offline`.
4. Repetía.

## Comportamiento actual

### 1. Anti-zombie efímero (`monitor/__init__.py`)

Un proceso visto `RUNNING` sin permiso (`status` BD en `stopped`/`error`, `auto_started=False`) solo se adopta si su **uptime continuo ≥ `ZOMBIE_MIN_UPTIME` (30s)**:

- **`start > 0`** (agentes con uptime real): uptime = `now - start`.
- **`start == 0`** (agente Linux, `/jobs/status` reporta `start: 0` siempre): ventana de observación en memoria `_zombie_watch[job.id]` (primera vez visto RUNNING). Se reinicia en cada poll donde el job deja de ser candidato (el proceso desapareció → el crash-loop nunca acumula 30s).

Si uptime < 30s → **inestable**:
- Consola `👻 ZOMBIE INESTABLE` + fila `ZOMBIE_UNSTABLE` (solo en la transición `stopped→error`, sin duplicados).
- `job.status = "error"`, `auto_started = False`, `started_at = None`, `updated_at = now`.
- Guard `unstable_zombie`: la rama `PROCESS_SYNCED` NO sincroniza a `running` y la rama de `started_at` NO lo actualiza durante la ventana.
- Con `started_at=None` la rama RECOVERY-RETRY nunca lo reintenta automáticamente.
- La rama STOPPED ya no aplica (status `error`), por lo que **no hay más CMS offline en el ciclo**.

Si uptime ≥ 30s → adopción normal (`running` + `started_at` real) con `ZOMBIE_DETECTED` **deduplicado 5 min** por job (`ZOMBIE_DEDUPE_SECONDS`, consola y BD juntas).

### 2. Rate-limit CMS (`monitor/alerts.py`)

- Clave `(channel_id, status_event)`; si el último envío fue hace < `cms.rate_limit_sec` (app_settings, default **600s**) → **sin POST, sin consola, sin fila**.
- Al enviar: consola `Notificando al CMS...` + fila `CMS_{STATUS}` (`CMS_OFFLINE`, `CMS_ONLINE`, `CMS_ERROR`, `CMS_WARNING`, `CMS_RESTART`) con el mismo instante timestamp y commit propio.

### 3. `log_monitor_event` sin commit propio (`utils/helpers.py`)

- `db.add` + `db.flush()`, **sin `db.commit()`** → fin de los deadlocks MySQL 1213.
- El commit lo hace el call-path. Commits explícitos agregados donde el evento se perdería:
  - `monitor/__init__.py`: transiciones `NODE_UP` y `NODE_DOWN` (commit antes de retornar en la ruta offline).
  - `monitor/recovery.py` / `monitor/health.py`: `NODE_RECOVERY` y `ENCODER_RESTART_RECOVERY` ahora loguean **antes** de su commit.
  - `routers/internal.py`: `ENCODER_RESTART` y `PACKAGER_RESTART` con `db.commit()` explícito (el `get_db` de FastAPI cierra sin commit).
- El resto de los eventos quedan en el commit final del ciclo (`db.commit()` al terminar `process_node_thread`). En un rollback del ciclo se acepta no persistir los eventos parciales.

### 4. Timestamp consola/BD idéntico (A7)

- `log_monitor_event` trunca microsegundos (`timestamp.replace(microsecond=0)`): el `DATETIME(0)` de MySQL redondeaba `48,618 → 49` mientras la consola mostraba `48`.
- Parámetro opcional `timestamp=` para que los flujos (CMS) usen el mismo instante en consola y fila.

### 5. `stop_job` honesto (`routers/processes.py`)

- Agente HTTP != 200 o excepción de red → **HTTP 502** y el job conserva su estado (antes: `except: pass` marcaba `stopped` sin confirmación).

### 6. Dropdown de eventos (`templates/monitor_logs.html`)

- 29 tipos de evento listados (agregados `PROCESS_SYNCED`, `PROCESS_START_FAIL`, `NODE_RECOVERY`, `GHOST_CLEANUP`, `AUTO_RESTART`, `TIMESTAMP_DISCONTINUITY`, `DROP_FRAMES`, `ENCODER_RESTART`, `ENCODER_RESTART_RECOVERY`, `PACKAGER_RESTART`, `ENCODER_STOPPED/STARTED/RESTARTED`, `ZOMBIE_UNSTABLE`, `CMS_*`, `TSMONITOR_ALERT`) con badges por grupo.

## Parámetros

| Parámetro | Valor | Dónde |
|-----------|-------|-------|
| `ZOMBIE_MIN_UPTIME` | 30s | `core/config.py` (env) |
| `ZOMBIE_DEDUPE_SECONDS` | 300s | `core/config.py` (env) |
| `cms.rate_limit_sec` | 600s | `app_settings` (editable en `/ui/settings`) |
| `cms.enabled` | toggle | `app_settings` |

## Operación

- A0 aplicado: las 5 units (`channel_{Click_Tv_181,Exprezion-TV_197,Rdo_183,Concepcion_Tv_221,LifeTime_262}.service`) quedaron `stop + disable` en encoder_03. Los 5 canales permanecen detenidos.
- Fase B pendiente (Api_agent-linux): `StartLimitIntervalSec=60`/`StartLimitBurst=3` en `/jobs/create`, stop verificado, mapeo `failed→FATAL` / `activating→BACKOFF`.

## Tests

`tests/test_zombie_sync.py` — 12 tests: stop_job 502 (3), estabilidad zombie (5), rate-limit + eventos CMS (2), log sin commit + paridad de timestamp (2).
