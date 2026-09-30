# Parametros

## Requirement: Parámetros en BD con fallback

El sistema SHALL almacenar parámetros de plataforma en `app_settings` (sección, clave, valor) y SHALL usar el default de la sección cuando la fila no exista.

#### Scenario: lectura con fila ausente
- WHEN no existe fila `telegram/bot_token`
- THEN `get_setting("telegram", "bot_token", default)` retorna el default

#### Scenario: escritura persiste
- WHEN `save_section("telegram", {"bot_token": "XYZ"})`
- THEN la lectura posterior retorna "XYZ" tras commit

## Requirement: API-key global editable

La validación de `x-api-key` SHALL leer `security.api_key` desde BD con fallback a `AGENT_API_KEY` de config.py, con comparación de tiempo constante.

- WHEN `security.api_key` cambia en /ui/settings
- THEN requests con el key viejo reciben 401/403 y con el nuevo pasan (efecto inmediato, sin caché)

## Requirement: Notificaciones con toggle

- WHEN `telegram.enabled=0` THEN `notify_telegram` no envía
- WHEN `cms.enabled=0` THEN `notify_cms_channel_status` no envía
- WHEN `cms.enabled=1` (seed default) THEN el comportamiento actual de notificación al CMS se preserva

## Requirement: Fuentes de alerta con token

- WHEN se registra fuente en /ui/settings THEN se genera token de 32 hex y aparece en dropdown de reglas
- WHEN POST /api/fuentes/{slug}/alertas con token correcto, fuente activa y canal existente
- THEN se normaliza con TSMONITOR_TYPE_MAP y entra al motor de reglas (mismo flujo que tsmonitor)
- WHEN slug inexistente THEN 404; fuente deshabilitada o token inválido THEN 403; canal inexistente THEN 404
- WHEN los endpoints dedicados /api/alertas/tsmonitor y /api/alertas/packager reciben requests THEN siguen funcionando sin token (sin cambios)

## Requirement: Reglas con source dinámico

- WHEN se consulta GET /api/alert-rules/sources THEN retorna filas de alert_sources + "any"
- WHEN se crea regla con source que no existe en BD THEN 400
