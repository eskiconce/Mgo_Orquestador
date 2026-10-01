# Agent Systemd

## ADDED Requirements

### Requirement: units creados por el agente acotan los reinicios (anti crash-loop)

El endpoint `POST /jobs/create` del agente Linux SHALL generar el unit systemd con `StartLimitIntervalSec=60` y `StartLimitBurst=3` en la sección `[Unit]`, de modo que un proceso que falle 3 veces en 60 segundos deje de reiniciarse (crash-loop acotado).

#### Scenario: crash-loop acotado
- WHEN un job creado por el agente falla 3 veces dentro de 60 segundos
- THEN systemd detiene los intentos de reinicio (`Result: start-limit-hit`) y el unit queda en estado `failed`

#### Scenario: reinicio legítimo puntual
- WHEN un job falla una vez y se recupera
- THEN systemd lo reinicia normalmente (dentro del burst permitido)

### Requirement: /jobs/control stop verificado

El endpoint `POST /jobs/control?action=stop` SHALL verificar el `ActiveState` real de systemd después de ejecutar el stop. SHALL retornar HTTP 502 si el servicio sigue en estado `active`, `activating`, `reloading` o `deactivating`; solo SHALL retornar 200 cuando el estado final confirma la detención (`inactive`/`failed`). Si el estado final es `failed` (artefacto de `KillSignal=SIGKILL` durante el stop, `Result=signal`), el agente SHALL normalizarlo con `systemctl reset-failed` para que el unit quede `inactive` y `/jobs/status` reporte `STOPPED` (no `FATAL`) tras un stop deliberado.

#### Scenario: stop exitoso
- WHEN `systemctl stop` termina y el estado final es `inactive`
- THEN 200 con `verified_state: inactive`

#### Scenario: stop deja el unit en failed
- WHEN el stop mata el proceso vivo con SIGKILL y el unit queda `failed` (`Result=signal`)
- THEN el agente ejecuta `reset-failed`, el unit queda `inactive` y se retorna 200 con `verified_state: inactive` (el canal reporta STOPPED, no FATAL)

#### Scenario: stop no surte efecto
- WHEN el servicio sigue `active` o `activating` tras el stop
- THEN HTTP 502 con detalle del estado (el orquestador NO marca el job `stopped`)

#### Scenario: servicio ya detenido
- WHEN el servicio ya estaba `inactive` (stop idempotente)
- THEN 200 con `verified_state: inactive`

### Requirement: /jobs/status mapea crash-loop a BACKOFF y fallo definitivo a FATAL

El endpoint `GET /jobs/status` SHALL mapear los estados de systemd así:

- `active` → `RUNNING`
- `failed` → `FATAL` (incluye `start-limit-hit`)
- `activating` + SubState `auto-restart`/`start-limit-hit` → `BACKOFF` (ciclo de reinicio por fallo)
- `activating` + otro SubState → `STARTING` (arranque normal)
- `deactivating` → `STARTING`
- resto (`inactive`, desconocido) → `STOPPED`

#### Scenario: crash-loop en curso
- WHEN un unit está `activating` con SubState `auto-restart`
- THEN `/jobs/status` reporta `BACKOFF` (el orquestador aplica su rama FATAL/BACKOFF → auto-kill tras 60s)

#### Scenario: start limit alcanzado
- WHEN el unit alcanza `StartLimitBurst` y queda `failed`
- THEN `/jobs/status` reporta `FATAL`

#### Scenario: arranque normal
- WHEN un unit está `activating` con SubState `start` (arranque recién iniciado)
- THEN `/jobs/status` reporta `STARTING`
