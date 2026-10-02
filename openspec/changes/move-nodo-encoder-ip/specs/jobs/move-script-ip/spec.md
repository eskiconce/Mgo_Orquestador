# Jobs / Move Script IP

## ADDED Requirements

### Requirement: move_job sincroniza la IP multicast del script al mover un Encoder

`POST /orchestrator/move-job` SHALL actualizar `job.command` con la `ip_multicast` del nodo destino cuando el destino es un Encoder, reemplazando por patrón `LOCADDRESS = "..."` y `localaddr=<IP literal>`, preservando el resto del contenido del script (ediciones manuales incluidas).

#### Scenario: move de encoder con script Linux/CPU
- WHEN se mueve un job Encoder con `LOCADDRESS = "10.0.0.5"` a un nodo con `ip_multicast = "10.0.0.9"`
- THEN `job.command` contiene `LOCADDRESS = "10.0.0.9"` y el resto del script es idéntico

#### Scenario: move de encoder con script Mac/GPU
- WHEN se mueve un job Encoder cuyo script contiene 3 ocurrencias de `?localaddr=10.0.0.5&`
- THEN las 3 ocurrencias quedan con `localaddr=10.0.0.9` (IP del nodo destino)

#### Scenario: referencia a variable preservada
- WHEN el script Linux contiene la referencia `localaddr={LOCADDRESS}`
- THEN esa referencia NO se modifica (el patrón solo matchea IPs literales)

#### Scenario: move de packager sin cambios
- WHEN se mueve un job Packager
- THEN `job.command` queda sin modificaciones (IP de packager fuera de alcance)

#### Scenario: valores defensivos
- WHEN `job.command` está vacío o el nodo destino no tiene `ip_multicast`
- THEN el move se completa sin error y sin modificar `job.command`

#### Scenario: inicio posterior usa la IP nueva
- WHEN después del move se inicia el job (`start-job`)
- THEN el `job.command_compress` enviado al agente contiene la IP del nodo destino
