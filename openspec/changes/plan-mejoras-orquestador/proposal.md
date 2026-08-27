## Why

El orquestador tiene deudas técnicas que dificultan su mantenimiento, despliegue y evolución: módulos "god" (>1000 líneas), configuración y secretos dispersos/duplicados, sin testeo automatizado, con logging desconectado y errores inconsistentes. Necesitamos un plan de mejoras estructurado para hacerlo más mantenible, seguro y observables.

## What Changes

- **Refactor de módulos**: dividir `main.py` (~1088 líneas) y `monitor.py` (~1079 líneas) en routers y checks por dominio.
- **Centralizar configuración**: unificar constantes/secretos en `core/config.py`, usar `.env` (python-dotenv o pydantic-settings) y agregar `requirements.txt`.
- **Estandarizar cliente HTTP**: adoptar un único patrón (cliente compartido httpx desde lifespan), eliminar uso de `requests` y clientes creados por request.
- **Automatizar testing**: agregar pytest e implementar los escenarios de las specs OpenSpec como tests.
- **Observabilidad**: agregar endpoint de salud propio del orquestador, logging unificado y estructurado, y métricas básicas.
- **Limpiar código muerto**: eliminar `backup/`, archivos `*.V1.py`, `core/version.py.bak` y bloques comentados.
- **Unificar errores y auth**: esquema de error consistente; asegurar auth en endpoints internos (`trigger-failover`, `analyze-callback`, `vod-webhook`).
- **Registrar cambios en GitHub** (principal) con commit/push, changelog y docs actualizados antes de desplegar al servidor.

## Capabilities

### New Capabilities
- `orchestrator/modular-architecture`: División del orquestador en routers/servicios por dominio.
- `orchestrator/config-management`: Centralización de configuración, secretos y dependencias.
- `orchestrator/observability`: Salud propia, logging unificado y métricas.
- `orchestrator/testing`: Framework de tests automatizados que cubra las specs.

### Modified Capabilities
- `monitoring/channel-recovery`: Los escenarios de la spec existente deben pasar como tests automatizados.

## Impact

- **Código**: `main.py`, `monitor.py`, `services/*`, `core/config.py`, `core/logging_service.py`, `utils/helpers.py`.
- **Despliegue**: sistema de unidades systemd (`encoder-api`, `encoder-monitor`), agregar `requirements.txt`.
- **Servidores**: orquestador (172.16.223.5), encoders, origins.
- **Sin cambios** en los agentes encoder (Linux/Mac) ni en el modelo de datos.
