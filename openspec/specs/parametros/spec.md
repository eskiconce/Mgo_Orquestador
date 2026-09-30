# parametros Specification

## Purpose
Definir el comportamiento del menú "Parámetros Generales": almacenamiento de parámetros de plataforma en `app_settings` (clave-valor por sección con fallback a defaults), API-key global editable con efecto inmediato, toggles de notificaciones Telegram/CMS, configuración de correo (SMTP/Microsoft Graph), CRUD de fuentes de alerta con token por fuente e ingesta genérica de alertas, y alimentación del `source` de las reglas de alerta desde la BD.

## Requirements

### Requirement: Parámetros en BD con fallback

El sistema SHALL almacenar parámetros de plataforma en `app_settings` (sección, clave, valor) y SHALL usar el default de la sección cuando la fila no exista.

#### Scenario: lectura con fila ausente
- WHEN no existe fila `telegram/bot_token`
- THEN `get_setting("telegram", "bot_token", default)` retorna el default

#### Scenario: escritura persiste
- WHEN `save_section("telegram", {"bot_token": "XYZ"})`
- THEN la lectura posterior retorna "XYZ" tras commit

### Requirement: API-key global editable

La validación de `x-api-key` SHALL leer `security.api_key` desde BD con fallback a `AGENT_API_KEY` de config.py, con comparación de tiempo constante.

#### Scenario: cambio de key con efecto inmediato
- WHEN `security.api_key` cambia en /ui/settings
- THEN requests con el key viejo reciben 401/403 y con el nuevo pasan (efecto inmediato, sin caché)

### Requirement: Notificaciones con toggle

El sistema SHALL respetar los toggles de notificaciones (`telegram.enabled`, `cms.enabled`) almacenados en `app_settings` antes de enviar cada notificación.

#### Scenario: telegram deshabilitado
- WHEN `telegram.enabled=0` THEN `notify_telegram` no envía

#### Scenario: cms deshabilitado
- WHEN `cms.enabled=0` THEN `notify_cms_channel_status` no envía

#### Scenario: cms seed default
- WHEN `cms.enabled=1` (seed default) THEN el comportamiento actual de notificación al CMS se preserva

### Requirement: Fuentes de alerta con token

El sistema SHALL exponer un endpoint genérico de intake de alertas autenticado por token de fuente, con registro CRUD de fuentes en /ui/settings.

#### Scenario: registro de fuente
- WHEN se registra fuente en /ui/settings THEN se genera token de 32 hex y aparece en dropdown de reglas

#### Scenario: intake con token válido
- WHEN POST /api/fuentes/{slug}/alertas con token correcto, fuente activa y canal existente
- THEN se normaliza con TSMONITOR_TYPE_MAP y entra al motor de reglas (mismo flujo que tsmonitor)

#### Scenario: errores de validación
- WHEN slug inexistente THEN 404; fuente deshabilitada o token inválido THEN 403; canal inexistente THEN 404

#### Scenario: endpoints dedicados sin token
- WHEN los endpoints dedicados /api/alertas/tsmonitor y /api/alertas/packager reciben requests THEN siguen funcionando sin token (sin cambios)

### Requirement: Reglas con source dinámico

El sistema SHALL poblar el listado de `source` de las reglas de alerta desde `alert_sources` y SHALL validar que el `source` de una regla exista en BD.

#### Scenario: consulta de sources
- WHEN se consulta GET /api/alert-rules/sources THEN retorna filas de alert_sources + "any"

#### Scenario: source inexistente
- WHEN se crea regla con source que no existe en BD THEN 400
