# Mover Nodo de Encoder: sincronizar IP multicast del script

## Why

Issue #15 (análisis 2026-10-02): `POST /orchestrator/move-job` (`routers/processes.py:232-250`) solo reasigna `job.node_id`; **`job.command` conserva la IP multicast del nodo origen**. Al iniciar después, `start-job` envía `job.command_compress` al agente nuevo con la interfaz equivocada → ffmpeg bindea el `localaddr`/`LOCADDRESS` del nodo anterior (no une el multicast de entrada o sale por la interfaz incorrecta).

- Script Linux/CPU: `LOCADDRESS = "<ip_nodo>"` (`builders.py:276,326`).
- Script Mac/GPU: `?localaddr=<ip_nodo>&` inline en 3 URLs (`builders.py:574,622-623`).
- Precedente de parcheo automático: `create_job` aplica `re.sub(r'INTERFACE=".*?"', ...)` al packager mirror (`processes.py:122`).
- `Node.ip_multicast` es **obligatorio** en la creación del nodo → siempre disponible en el destino.
- El camino manual (modal "Editar Script" → *Regenerar Script* → Guardar) funciona pero nada lo exige: un Start directo tras el move corre con la IP vieja.

## What Changes

- **M1** `move_job` (`routers/processes.py`): al mover un job **Encoder** (`new_node.tipo == 'Encoder'`), parchear `job.command` con `new_node.ip_multicast` mediante reemplazo quirúrgico por patrón (preserva ediciones manuales del script):
  - `LOCADDRESS = "..."` → IP destino (Linux/CPU).
  - `localaddr=<IP literal>` → IP destino (Mac/GPU). El patrón solo matchea literales (`localaddr=<dígitos.puntos>`), **no** la referencia `localaddr={LOCADDRESS}` del script Linux.
  - Defensivo: sin parcheo si `job.command` está vacío o `ip_multicast` es `None` (sin error).
  - `command_compress` se recalcula solo (property derivada de `command`).
  - El resto del flujo (delete en agente origen, `msg=moved`, `sync_haproxy_map` solo para Packager) queda igual.
- **M2** Tests: move de encoder → script parcheado con ambos patrones (var `LOCADDRESS` e inline `localaddr=`); referencia `localaddr={LOCADDRESS}` intacta; move de packager → `job.command` sin cambios; suite completa en verde.

## Non-Goals

- **Mover Packager** → mismo bug con `INTERFACE="..."` → issue/revisiones separadas.
- No se regenera el script completo con builders (se preservan ediciones manuales: subs, audio mapping, etc.).
- No se agrega validación ni parcheo en `start-job`.
- No se modifica la UI del modal de move (`process_list.html`).

## Impact

- Affected specs: `jobs/move-script-ip` (nuevo en este change).
- Affected code: `routers/processes.py`, `tests/` (nuevos).
- Version: **v2.22.1** (PATCH — corrección de bug operativo).
- Deploy: solo código (`routers/processes.py`, `core/version.py`) a `172.16.223.5` + restart `encoder-monitor` + `encoder-api`.
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/15
