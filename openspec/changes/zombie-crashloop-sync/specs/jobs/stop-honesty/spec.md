# Jobs Stop Honesty

## ADDED Requirements

### Requirement: stop_job solo reporta stopped si el agente confirma

`POST /jobs/{id}/stop` SHALL retornar 502 (y NO alterar `job.status`) cuando el agente responde con HTTP != 200 o la comunicación falla. NO se permitirá `except: pass` silencioso.

#### Scenario: agente responde 200
- WHEN el agente confirma el stop con HTTP 200
- THEN el job queda `stopped` y se retorna 200

#### Scenario: agente responde error
- WHEN el agente retorna HTTP != 200
- THEN se lanza HTTPException 502 y el job conserva su estado previo

#### Scenario: red inaccesible
- WHEN la conexión con el agente falla (timeout/refused)
- THEN se lanza HTTPException 502 y el job conserva su estado previo

#### Scenario: job inexistente
- WHEN el id no existe en BD
- THEN 404
