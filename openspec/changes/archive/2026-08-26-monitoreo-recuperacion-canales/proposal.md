## Why

El proceso de monitoreo actual tiene dos anomalías que dejan canales fuera de servicio sin recuperación automática:

1. **Recuperación tsmonitor incompleta:** cuando el tsmonitor externo reporta que un canal volvió, el orquestador debe reactivar el encoder, pero hay un bug que impide encontrar el canal (campo inexistente `numero_canal` y lookup que solo usa `unique_id`).
2. **Sin auto-start tras restart del encoder:** cuando un encoder Mac/Linux se reinicia, el orquestador marca sus canales como `stopped` (estado protegido). Al volver el encoder, los canales NO se relanzan porque la recuperación NODE_UP solo busca jobs en `error`, nunca en `stopped`.

El resultado son canales caídos indefinidamente que requieren intervención manual.

## What Changes

- **Fix tsmonitor recovery**: corregir el campo `numero_canal` → `num_canal` y mejorar el lookup del canal para que funcione con `unique_id` y/o `id`.
- **Auto-start de canales `stopped` tras recuperación de nodo**: al detectar NODE_UP, relanzar también los jobs en estado `stopped` (no solo `error`).
- **Recuperación cíclica en sync loop**: agregar rama de reintento periódico para jobs en `error`/`stopped` cuando el nodo está activo, como respaldo de la recuperación por transición.

## Capabilities

### New Capabilities
- `monitoring/channel-recovery`: Detección de canales caídos y relanzamiento automático de encoders tras la recuperación de la señal (tsmonitor) y tras el reinicio de un nodo encoder (NODE_UP).

### Modified Capabilities
- *(ninguna — no hay specs previas; se crean por primera vez)*

## Impact

- **`services/vod_service.py`**: handler de alertas tsmonitor (`receive_tsmonitor_alert`) — fix de campo y lookup.
- **`monitor.py`**: `process_node_thread` NODE_UP recovery + sync loop STOPPED/ERROR handler.
- **Código afectado**: modelo `EncodingJob` (estados), agentes encoder (no cambian), servicio `encoder-api` y `encoder-monitor`.
