## Purpose

Define el contrato de recuperación automática de canales cuando una señal vuelve a estar disponible desde el tsmonitor y cuando un nodo encoder se reinicia, para que los canales caídos se relancen sin intervención manual.

## ADDED Requirements

### Requirement: Recuperación de canal desde tsmonitor

El sistema SHALL recibir alertas del tsmonitor externo y, cuando se reporte la recuperación de un canal, reactivar automáticamente el encoder asociado que haya sido detenido por una alerta previa de falla.

#### Scenario: tsmonitor reporta falla y luego recuperación

- **WHEN** el sistema recibe una alerta de falla (`freeze`, `dead`, `down`) para un canal y detiene su encoder
- **AND** posteriormente recibe una alerta de recuperación (`restore`, `ok`, `up`, `restored`, `live`) para el mismo canal
- **THEN** el sistema relanza el encoder del canal asociado mediante `POST /jobs/create` con `autostart: true`
- **AND** actualiza el estado del encoder a `starting`

#### Scenario: Identificación del canal por unique_id o id

- **WHEN** el sistema recibe una alerta de tsmonitor con el campo `num_canal`
- **THEN** localiza el canal usando su `unique_id` y, si no coincide, intenta con el `id` numérico del canal
- **AND** si el canal no existe, responde con un error claro sin lanzar un `AttributeError` por campos inexistentes

### Requirement: Recuperación de canales tras reinicio del nodo encoder

El sistema SHALL relanzar automáticamente los canales de un encoder que hayan quedado detenidos o en error cuando el nodo encoder vuelve a estar en línea.

#### Scenario: Nodo encoder vuelve a estar online

- **WHEN** un nodo encoder transiciona de `offline` a `online`
- **THEN** el sistema busca todos los jobs del nodo en estado `error` o `stopped`
- **AND** los relanza mediante `POST /jobs/create` (o start) actualizando su estado a `starting`
- **AND** registra el evento de recuperación con la cantidad de jobs relanzados

#### Scenario: Canal detenido por reinicio rápido del nodo

- **WHEN** un encoder se reinicia rápidamente (< 45s) y el nodo permanece alcanzable, dejando sus canales en estado `stopped`
- **AND** el nodo vuelve a responder correctamente
- **THEN** el sistema relanza esos canales `stopped` (no solo los `error`), sin requerir intervención manual

### Requirement: Reintento periódico de canales no recuperados

El sistema SHALL reintentar periódicamente el relanzamiento de jobs en estado `error` o `stopped` mientras el nodo esté activo, como mecanismo de respaldo a la recuperación por transición de estado del nodo.

#### Scenario: Job en error con nodo activo

- **WHEN** un job de encoder permanece en estado `error` o `stopped` y su nodo está en `online`
- **THEN** durante el ciclo de sincronización, el sistema reintenta el arranque del job
- **AND** registra el intento en el monitor log
