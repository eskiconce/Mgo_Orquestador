## Why

Los parámetros operativos (API-key, Telegram, CMS) están hardcodeados en config.py/env vars y no editables desde la UI; el campo `source` de las reglas de alerta está limitado a 4 valores fijos, por lo que integrar una fuente externa nueva requiere código. Se necesita un menú único "Parámetros Generales" para configurar notificaciones, seguridad y registrar fuentes de alerta con token.

## What Changes

- Tablas `app_settings` (clave-valor por sección) y `alert_sources` (CRUD con token) — migración 003.
- API-key global migrada a BD con efecto inmediato y fallback al default de config.py.
- Página /ui/settings con secciones: Seguridad, Telegram, Correo (SMTP | Graph), CMS, Fuentes.
- Endpoint genérico POST /api/fuentes/{slug}/alertas (payload estilo tsmonitor, auth por token).
- notify_telegram / notify_cms respetan toggles desde BD; source de reglas desde BD.
- Menú: dropdown Parámetros Generales (Usuarios + Parámetros).

## Impact

- Affected specs: parametros (nuevo)
- Affected code: models.py, main.py, core/http_client.py, routers/*, services/*, utils/helpers.py, monitor/*, templates/*, scripts/migrations/003_*.sql
