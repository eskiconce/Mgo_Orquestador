# Design — Recuperación automática de canales

## Context

Ver `proposal.md` — Why. El proceso de monitoreo (`monitor.py`) y el handler de alertas tsmonitor (`services/vod_service.py`) tienen dos fallas que dejan canales detenidos sin recuperación automática. Este diseño define cómo corregirlas.

## Goals / Non-Goals

### Goals
- Relanzar automáticamente encoders cuando tsmonitor reporta la recuperación de un canal.
- Relanzar automáticamente los canales de un nodo encoder cuando vuelve a estar online.
- Reintentar periódicamente jobs en `error`/`stopped` mientras el nodo esté activo, como respaldo.

### Non-Goals
- No cambiar el modelo de datos ni agregar campos nuevos (la recuperación se basa en los estados existentes `error`/`stopped`/`running`/`starting`).
- No modificar los agentes encoder (Linux/Mac) — solo el orquestador.
- No implementar distribución de canales entre NUMA nodes (fuera de alcance).

## Decisions

### Decisión 1: Lookup de canal por `unique_id` y fallback a `id`
**Alternativa considerada:** solo `unique_id` (actual). Elegido: intentar `unique_id` primero y luego `id`, porque tsmonitor puede enviar cualquiera de los dos. Se corrige también el bug `payload.numero_canal` → `payload.num_canal`.

### Decisión 2: NODE_UP recovery busca `error` Y `stopped`
**Alternativa considerada:** solo `error` (actual). Elegido: incluir `stopped`, porque es el estado en que quedan los canales tras un reinicio rápido (<45s) del nodo donde no se dispara el ghost-cleanup.

### Decisión 3: Reintento periódico en el sync loop
Agregar una rama en el handler de STOPPED/ERROR que reintente `start` cada N segundos para jobs no recuperados, como respaldo a la recuperación por transición. 

**Alternativa considerada:** depender solo del evento NODE_UP. Rechazada porque si el nodo nunca transiciona (offline→online) pero el job quedó `stopped`, nunca se recuperaría.

### Decisión 4: Evitar relaunch de canales detenidos intencionalmente
**Riesgo importante:** no relanzar canales que el operador detuvo manualmente. Se resuelve usando `auto_started` como flag y un umbral de tiempo desde que quedó `stopped`, para no reponer canales detenidos a propósito.

## Risks / Trade-offs

- **[Riesgo: relanzar canal detenido manualmente]** → Se mitiga con el flag `auto_started` y un cooldown mínimo antes de reintentar.
- **[Riesgo: reinicio en bucle si la señal sigue fallando]** → Se mitiga limitando los reintentos y registrando cada intento en monitor log.
- **[Riesgo: tsmonitor envía campos/variantes de estado no contemplados]** → Se mitiga con un conjunto amplio de estados de recuperación (`restore`, `ok`, `up`, `restored`, `live`).

## Migration Plan

1. **Backup** de `monitor.py` y `vod_service.py` en el servidor y en el repo local.
2. **Desplegar** los archivos modificados al servidor (no docs/changelog).
3. **Reiniciar** `encoder-monitor.service` y `encoder-api.service`.
4. **Verificar sintaxis** con `ast.parse` antes del reinicio.
5. **Rollback**: restaurar desde el backup si falla.

## Open Questions

- ¿El cooldown mínimo para no relanzar canales detenidos manualmente debe ser configurable? (se puede responder luego sin cambiar specs)
