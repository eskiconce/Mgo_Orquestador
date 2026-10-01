# zombie-stability Specification

## Purpose
TBD - created by archiving change zombie-crashloop-sync. Update Purpose after archive.

## Requirements

### Requirement: No adopción de zombie efímero

El monitor SHALL solo adoptar un proceso RUNNING sin permiso (`status` BD en `stopped`/`error`, `auto_started=False`) cuando su uptime continuo observado sea ≥ `ZOMBIE_MIN_UPTIME` (30s). Si `start` del agente es 0 (agente Linux), el uptime SHALL calcularse con una ventana de observación en memoria (`_zombie_watch`) que se reinicia en cada poll donde el estado no sea candidato.

#### Scenario: zombie inestable (< 30s) no se adopta
- WHEN un job con `status=stopped` aparece RUNNING con uptime < 30s
- THEN se registra consola + `ZOMBIE_UNSTABLE` en `monitor_logs`, el job queda `status=error`, `auto_started=False`, `started_at=None`, y NO se adopta como running

#### Scenario: uptime con start del agente
- WHEN `start > 0` y `(now - start) < 30s`
- THEN se trata como inestable sin usar la ventana de observación

#### Scenario: zombie estable se adopta
- WHEN el proceso permanece RUNNING ≥ 30s continuos sin permiso
- THEN se adopta (`status=running`, `started_at` real o now) con `ZOMBIE_DETECTED` deduplicado

#### Scenario: PROCESS_SYNCED no sincroniza durante la ventana inestable
- WHEN `unstable_zombie=True` en el ciclo (RUNNING con uptime < 30s)
- THEN la rama `PROCESS_SYNCED` no cambia el job a `running` y la rama de `started_at` no lo actualiza

#### Scenario: crash-loop nunca alcanza la ventana
- WHEN el proceso reaparece RUNNING tras haber desaparecido en un poll anterior
- THEN la ventana de observación se reinicia y el job jamás se adopta ni notifica CMS

#### Scenario: sin recovery-retry automático
- WHEN el job queda en `error` con `started_at=None` por zombie inestable
- THEN la rama RECOVERY-RETRY no lo reintenta

### Requirement: Dedupe de ZOMBIE_DETECTED

El sistema SHALL registrar consola + `monitor_logs` de `ZOMBIE_DETECTED` como máximo una vez cada `ZOMBIE_DEDUPE_SECONDS` (300s) por job (la ventana NO se reinicia al adoptar: una re-adopción dentro de los 5 min queda silenciada).

#### Scenario: ráfaga de adopciones
- WHEN se intenta registrar `ZOMBIE_DETECTED` para el mismo job dentro de los 5 min del último registro
- THEN ni la consola ni `monitor_logs` reciben el evento (parity consola/BD)
