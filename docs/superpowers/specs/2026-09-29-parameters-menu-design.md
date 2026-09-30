# Diseño — Menú Parámetros Generales, Configuración de Notificaciones y Fuentes de Alertas

**Fecha:** 2026-09-29
**Versión objetivo:** v2.19.0 (MINOR — feature nueva)
**Estado:** Aprobado en diseño, pendiente de revisión de spec

## 1. Contexto y problema

Hoy los parámetros operativos están dispersos y son estáticos:

- **API-key global** hardcodeada en `core/config.py` (`a1b2c3…abcdef0`) — no editable sin deploy.
- **Telegram** (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) y **CMS** (`CMS_REAL_WEBHOOK`) viven en variables de entorno — no editables desde la UI.
- **Correo** no existe (ni config ni envío).
- **`source` de reglas de alerta** hardcodeado en `routers/alert_rules.py:87,137` a `["tsmonitor", "packager", "encoder", "any"]` — cada fuente nueva requiere código.
- **Fuentes externas de alerta** solo pueden integrarse con un endpoint dedicado + código propio (modelo Pydantic + normalizador).

## 2. Alcance

### En scope

1. Dropdown de menú **"Parámetros Generales"** = Usuarios + Parámetros.
2. Página `/ui/settings` con tarjetas: Seguridad (API-key), Telegram, Correo (SMTP o Microsoft Graph OAuth), CMS, Fuentes de alertas (CRUD).
3. Migración de todos los parámetros a BD (tabla `app_settings`), con fallback a defaults.
4. API-key global editable en BD — fuente única de verdad, cambio efecto inmediato.
5. Endpoint genérico de ingesta para fuentes nuevas registradas en el menú (payload idéntico a tsmonitor, token por fuente).
6. Dropdown `source` de reglas de alerta alimentado desde BD.
7. Botón "Probar envío" de correo (test real). **Envío de correos en alertas queda para un issue futuro.**

### Fuera de scope

- Envío de correos al disparar reglas (`notify_only` sigue logueando).
- Autenticación sobre los endpoints dedicados existentes (tsmonitor/packager siguen abiertos).
- Rotación automática del API-key, hashing de tokens, MFA.
- Notificación a CMS/Telegram "de prueba" desde el menú (solo correo tiene test).
- Repos GitHub para agentes Mac/Linux.

## 3. Decisiones del usuario (Q&A)

| # | Pregunta | Decisión |
|---|----------|----------|
| 1 | Alcance de notificaciones | Menú + params en BD con activar/desactivar; correo: config + test; envío real futuro |
| 2 | Ingesta de fuentes nuevas | Mixto: dedicados actuales se mantienen; nuevas envían payload tsmonitor, solo cambia origen |
| 3 | Estructura de menú | **C)** Usuarios + Parámetros dentro del dropdown; Reglas Alertas y KMS fuera, sin mover |
| 4 | Auth de fuentes nuevas | **A)** Token/API-key por fuente |
| 5 | Migración API-key | **A)** BD = fuente única, fallback al default si la tabla está vacía, efecto inmediato |
| 6 | Endpoints existentes | **B)** Siguen abiertos; token por fuente solo aplica a fuentes nuevas |
| 7 | Correo | **C)** Config + test de conexión; envío en alertas después |
| 8 | Proveedor OAuth correo | **A)** Microsoft Graph (client_credentials) |
| 9 | Almacenamiento | **1)** Tabla clave-valor `app_settings` + `alert_sources` |

## 4. Modelo de datos (migración `003_app_settings_alert_sources.sql`)

### Tabla `app_settings`

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    section VARCHAR(50) NOT NULL,
    `key` VARCHAR(100) NOT NULL,
    value TEXT,
    UNIQUE KEY uq_section_key (section, `key`)
);
```

Defaults insertados por la migración:

| Sección | Claves → defaults |
|---------|-------------------|
| `telegram` | `enabled=0`, `bot_token=''`, `chat_id=''` |
| `email` | `enabled=0`, `auth_mode='smtp'`, `smtp_host=''`, `smtp_port=587`, `smtp_tls=1`, `smtp_user=''`, `smtp_password=''`, `graph_tenant_id=''`, `graph_client_id=''`, `graph_client_secret=''`, `from_addr=''`, `recipients=''` |
| `cms` | `enabled=1`, `webhook_url='https://core-dev.mundogo.cl/api/webhook-vod'` |
| `security` | `api_key='a1b2c3d4e5f67890123456789abcdef0'` |

> **Preservación de comportamiento:** el CMS notifica hoy siempre → `enabled=1` en seed. Telegram queda `enabled=0` salvo que el server tenga env vars (import manual en deploy).

### Tabla `alert_sources`

```sql
CREATE TABLE IF NOT EXISTS alert_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    token VARCHAR(64) NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    description VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

- **Seed:** `tsmonitor`, `packager`, `encoder` (alimentan el dropdown de reglas; sus endpoints dedicados siguen abiertos y sin token).
- **`"any"`** no es fila: constante especial en UI y validación.

## 5. Backend

### 5.1 `services/settings_service.py`

- `get_setting(section, key, default=None)` — lee de BD; fila ausente → `default`.
- `get_section(section) -> dict` — todas las claves de una sección.
- `save_section(section, values: dict)` — upsert de cada clave.
- Sin caché: cada lectura es actual (requisito para API-key: efecto inmediato).

### 5.2 API-key global

- Reemplazar toda validación de `AGENT_API_KEY` (headers `x-api-key` / `X-API-Key`) por `get_setting("security", "api_key", fallback=config.AGENT_API_KEY)`.
- Comparación con `secrets.compare_digest`.
- Puntos a localizar en plan: validación de agentes, endpoints internos, métricas — grep de `AGENT_API_KEY`/`x-api-key`.

### 5.3 Notificaciones existentes

- `monitor/alerts.py::notify_telegram` — si `telegram.enabled=0` → return; token/chat desde BD (fallback config solo si la clave no existe).
- `monitor/alerts.py::notify_cms_channel_status` — si `cms.enabled=0` → return; webhook desde BD (fallback config).
- El toggle global `cms.enabled` es una condición **necesaria y previa**: gatea cualquier notificación al CMS sin importar el origen (monitor, motor de reglas, campo `notify_cms` por regla — ese campo se mantiene como está, sin cambios en esta versión).
- Ambas leen con sesión propia/Thread-Safe como hoy.

### 5.4 Email — envío y test

- `services/email_service.py`:
  - `send_test_email()` — envía asunto `Prueba de conexión — Mgo_Orquestador` a `recipients` (fallback `from_addr` si vacío).
  - Modo `smtp`: `smtplib` + STARTTLS (`smtp_tls=1`) o SSL (`smtp_tls=0`, puerto 465 típico).
  - Modo `graph`: POST `https://graph.microsoft.com/v1.0/{tenant}/oauth2/v2.0/token` (client_credentials, scope `https://graph.microsoft.com/.default`) → POST `/v1.0/me/sendMail`. Token cacheado en memoria con expiración (~90 min), se renueva al vencer.
- **No se integra con el motor de reglas** en esta versión.

### 5.5 Endpoint genérico de ingesta

- `POST /api/fuentes/{slug}/alertas` — path completamente separado de `/api/alertas/*`, sin solapamiento de rutas con los endpoints dedicados.
- Header: `x-api-key: <token de la fuente>` (convención existente de la plataforma).
- Payload: `{"num_canal": ..., "fecha": "YYYY-MM-DD", "hora": "HH:MM:SS", "status": ...}` (idéntico a tsmonitor).
- Flujo:
  1. Busca fuente por `slug` → 404 si no existe.
  2. `enabled` → 403 si deshabilitada.
  3. Token con `secrets.compare_digest` → 403 si no coincide.
  4. Canal por `unique_id` → fallback `id` numérico (mismo código que tsmonitor) → 404 si no existe.
  5. Normaliza con `TSMONITOR_TYPE_MAP` (payload equivalente ⇒ mismo mapeo).
  6. `alert_rule_engine.process_alert(...)`.
- Rate limit: sin exclusión (misma treatment que `/api/alertas/`, 300 req/min).

### 5.6 Reglas de alerta

- `routers/alert_rules.py`: `valid_sources` = `[slug de alert_sources] + ["any"]` (desde BD).
- `GET /api/alert-rules/sources` → `[{slug, name, enabled}]` + `{"slug": "any", "name": "Cualquiera", "enabled": true}`.
- UI marca deshabilitadas con *(deshabilitada)*; validación acepta cualquier fila existente (reglas viejas no rompen).

## 6. UI

### 6.1 Menú (`templates/base.html`)

Dentro del bloque `{% if user.role in ('admin', 'operator') %}`:

```html
<li class="nav-item dropdown">
  <a class="nav-link dropdown-toggle" data-bs-toggle="dropdown">Parámetros Generales</a>
  <ul class="dropdown-menu">
    <li><a href="/ui/users">Usuarios</a></li>        <!-- admin+operator (como hoy) -->
    <li><a href="/ui/settings">Parámetros</a></li>    <!-- admin only (backend lo exige) -->
  </ul>
</li>
```

- Se elimina el `<li>` suelto de *Usuarios*.
- *Reglas Alertas* y *KMS* sin cambios.

### 6.2 Página `/ui/settings`

Extiende `base.html`. Cinco tarjetas, cada una con **Guardar** (PUT por sección):

1. **Seguridad** — API-key enmascarada (últimos 4 chars), botón revelar, campo editable, aviso: *"Cambiar invalida conexiones externas que usen el key actual."*
2. **Telegram** — toggle, `bot_token`, `chat_id`.
3. **Correo** — toggle, radio `SMTP | Microsoft Graph`; campos SMTP *o* Graph visibles según modo; `from_addr`, `recipients`; botón **Probar envío**.
4. **CMS** — toggle, `webhook_url`.
5. **Fuentes de alertas** — tabla (nombre, slug, token enmascarado, estado, Editar/Eliminar con confirm). **Nueva fuente** → modal (nombre → slug auto, **generar token**, descripción, activo). Caja de ayuda: URL de ejemplo `POST /api/fuentes/{slug}/alertas`, header, payload JSON.

### 6.3 `templates/alert_rules.html`

- `#ruleSource` y `#filterSource` se poblan con `fetch('/api/alert-rules/sources')` al cargar (reemplazan `<option>` hardcodeadas).

## 7. Seguridad

- API-key y tokens se muestran enmascarados en UI; revelar solo admin.
- Tokens por fuente y API-key se guardan **plaintext** en BD (trade-off aceptado: el servidor y la BD ya custodian credenciales equivalentes; permite revelar/reutilizar desde la UI).
- Contraseñas SMTP/secret Graph: mismas consideraciones.
- Endpoints de settings: dependency `admin` en backend (no solo en template).
- Datos sensibles nunca en logs.

## 8. Validación / Testing

1. `python3 -c "import ast; ast.parse(...)"` en todos los archivos tocados.
2. Migración 003 corre limpia vía `scripts/run_migrations.py` (con `schema_migrations`).
3. Checks manuales tras deploy:
   - Menú muestra dropdown con Usuarios + Parámetros; operador no accede a `/ui/settings` (403).
   - Guardar Telegram/CMS/Email persiste y sobrevive reinicio de servicios.
   - Cambiar API-key en menú → request con key viejo recibe 401/403; key nuevo pasa.
   - Crear fuente → token aparece → `curl -H "x-api-key: <token>" POST /api/fuentes/{slug}/alertas` con payload tsmonitor dispara motor de reglas.
   - Fuentes deshabilitadas → 403 en ingesta; marcadas en dropdown de reglas.
   - Test de correo en modo SMTP y en modo Graph.
   - Telegram/CMS: `enabled=0` no envía; `enabled=1` envía (verificar con token/webhook reales si están configurados).
4. Dashboard, jobs y agentes siguen operativos con el key nuevo.

## 9. Entrega (workflow obligatorio)

1. Issue en GitHub describiendo el cambio (antes de implementar).
2. Implementar siguiendo este spec.
3. Bump `core/version.py` → **2.19.0** (MINOR).
4. `CHANGELOG.md` + `README.md` + `INSTALLATION_GUIDE.md` actualizados.
5. Push a GitHub (fuente principal).
6. Verificar sintaxis en servidor → deploy **solo código** (nunca docs/CHANGELOG) → reiniciar `encoder-monitor` + `encoder-api`.
7. Verificación funcional (sección 8).
8. `openspec archive` / cierre del issue tras deploy exitoso.

## 10. Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Cambiar API-key rompe agentes/externos | Aviso en UI; rollback = restaurar key anterior en el menú (queda visible enmascarado) |
| Migración deshabilita CMS sin querer | Seed `cms.enabled=1` |
| Endpoint genérico expuesto sin auth | Token por fuente obligatorio en todas las respuestas 403 |
| Reglas existentes con source hardcodeado | Seed de fuentes + validación contra filas existentes |
| Graph OAuth mal configurado | Botón "Probar envío" antes de activar |
