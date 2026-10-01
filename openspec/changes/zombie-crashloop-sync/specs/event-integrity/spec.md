# Event Integrity

## ADDED Requirements

### Requirement: log_monitor_event sin commit propio

`log_monitor_event` SHALL agregar el evento a la sesión (`db.add`, con flush opcional) SIN ejecutar `db.commit()`, para eliminar los deadlocks MySQL 1213. Cada call-path que pueda terminar antes del commit del ciclo SHALL tener un commit explícito.

#### Scenario: commit del ciclo
- WHEN el ciclo normal del monitor termina (`db.commit()` final)
- THEN todos los eventos del ciclo quedan persistidos

#### Scenario: ruta offline persiste sus eventos
- WHEN un nodo se marca offline y el hilo retorna (sin llegar al commit final)
- THEN `NODE_DOWN` y `GHOST_CLEANUP` + cambios de cleanup quedan persistidos por un commit explícito antes del retorno

#### Scenario: endpoint interno persiste
- WHEN `routers/internal.py` registra `ENCODER_RESTART`/`PACKAGER_RESTART`
- THEN hay un `db.commit()` explícito después (el `get_db` de FastAPI cierra sin commit)

#### Scenario: excepción en el ciclo
- WHEN ocurre una excepción que dispara `db.rollback()`
- THEN se acepta que los eventos parciales del ciclo no se persisten (rollback coherente)

### Requirement: Timestamp consola/BD idéntico

`log_monitor_event` SHALL truncar los microsegundos del timestamp antes de persistir (evita el redondeo del `DATETIME(0)` de MySQL que desalineaba +1s respecto a la consola) y SHALL aceptar un `timestamp` opcional para que los flujos que loguean consola y fila usen el mismo instante.

#### Scenario: paridad de segundo
- WHEN la consola registra un evento en `20:55:48,618`
- THEN la fila en `monitor_logs` tiene timestamp `20:55:48`

#### Scenario: CMS usa el mismo instante
- WHEN `notify_cms_channel_status` loguea consola y luego la fila `CMS_*`
- THEN ambas usan el instante capturado antes del webhook (independiente de la latencia HTTP)

### Requirement: Eventos CMS hacia monitor_logs

`notify_cms_channel_status` SHALL registrar `CMS_{STATUS}` (OFFLINE, ONLINE, ERROR, WARNING, RESTART) en `monitor_logs` con su propio commit, SOLO cuando el webhook realmente se envía (tras superar el rate-limit).

#### Scenario: webhook enviado
- WHEN el POST al CMS responde y la notificación no está rate-limited
- THEN se loguea consola + fila `CMS_*` + commit

#### Scenario: webhook omitido por rate-limit
- WHEN el mismo `(canal, evento)` fue notificado hace < `cms.rate_limit_sec`
- THEN no hay consola, no hay fila, no hay POST (parity total)

### Requirement: Rate-limit CMS

El sistema SHALL omitir `notify_cms_channel_status` si el mismo `(channel_id, status_event)` se notificó en los últimos `cms.rate_limit_sec` (default 600s, editable en app_settings sección `cms`).

#### Scenario: ráfaga de notificaciones offline
- WHEN el CMS recibe `offline` del canal X y vuelve a llegar `offline` de X dentro de 10 min
- THEN solo se envía la primera

#### Scenario: umbral configurable
- WHEN `cms.rate_limit_sec` cambia en `app_settings`
- THEN el siguiente check usa el nuevo valor (lectura por evento, sin caché)

### Requirement: Dropdown completo de tipos de evento

El dropdown de `/ui/monitor-logs` SHALL listar todos los tipos de evento que el sistema puede generar (`ZOMBIE_UNSTABLE`, `CMS_*`, `ENCODER_*`, `TSMONITOR_*`, `PROCESS_*`, `NODE_*`, `FAILOVER_*`, `AUTO_*`, `GHOST_CLEANUP`, `NODE_RECOVERY`, `TIMESTAMP_DISCONTINUITY`, `DROP_FRAMES`, `PACKAGER_RESTART`, etc.) con badges consistentes.

#### Scenario: filtrado de tipo nuevo
- WHEN se selecciona `ZOMBIE_UNSTABLE` o `CMS_OFFLINE` en el dropdown
- THEN la tabla filtra correctamente por ese tipo
