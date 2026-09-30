# Parámetros Generales — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menú "Parámetros Generales" con configuración en BD de Telegram, Correo (SMTP/Microsoft Graph), CMS, API-key global y CRUD de fuentes de alertas, más endpoint genérico de ingesta para fuentes nuevas.

**Architecture:** Tabla clave-valor `app_settings` (sección/clave/valor) + tabla `alert_sources`. Servicio `settings_service` como fuente única de lectura (fallback a defaults). API-key global migra de `core/config.py` a BD con efecto inmediato. Fuentes nuevas hacen POST a `/api/fuentes/{slug}/alertas` con token propio y payload idéntico a tsmonitor, entrando al mismo motor de reglas.

**Tech Stack:** FastAPI + SQLAlchemy + MySQL (migraciones `.sql` numeradas), Jinja2 + Bootstrap 5, `smtplib` (SMTP), `httpx` (Graph OAuth client_credentials), pytest + SQLite en memoria.

**Spec:** `docs/superpowers/specs/2026-09-29-parameters-menu-design.md` (aprobado, empujado a GitHub).

## Global Constraints

- Python 3.9 compatible (servidor): sin `X | Y`, sin `match`.
- GitHub `eskiconce/Mgo_Orquestador` = fuente de verdad; local `/Users/edmundocuevas/github/11_Git/Mgo_Orquestador/` = respaldo.
- Issue de GitHub ANTES de implementar (Task 1).
- OpenSpec obligatorio: `openspec new change parametros-generales` y `openspec archive` tras deploy (AGENTS.md).
- Roles: `/ui/settings` y toda la API de settings/sources = **admin only** (`require_role("admin")`); `GET /api/alert-rules/sources` = admin+operator (alimenta dropdown de reglas).
- Preservación de comportamiento: CMS seed `enabled=1`; tsmonitor/packager dedicados siguen abiertos y sin token; endpoint tsmonitor conserva respuestas idénticas.
- Versionado: bump **MINOR** → `2.19.0` (Task 9).
- Tests: `python3 -m pytest tests/ -q` debe pasar (22 tests base + nuevos).
- Deploy: SOLO código a `/opt/encoder-orchestrator/` (nunca CHANGELOG.md ni docs). Servicios: `encoder-monitor.service`, `encoder-api.service`.
- SSH: `ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5`, sudo password `S3rv1c3.operaciones`.

## File Structure

| Acción | Archivo | Responsabilidad |
|--------|---------|-----------------|
| Crear | `scripts/migrations/003_app_settings_alert_sources.sql` | Tablas + seeds |
| Crear | `services/settings_service.py` | Lectura/escritura de parámetros + `get_api_key()` |
| Crear | `services/email_service.py` | Envío SMTP/Graph + prueba |
| Crear | `services/alert_intake.py` | Ingesta estilo tsmonitor (compartida) |
| Crear | `routers/settings.py` | API settings/sources + UI de parámetros |
| Crear | `templates/settings.html` | Página de parámetros |
| Crear | `tests/test_settings.py`, `tests/test_alert_intake.py` | Tests |
| Modificar | `models.py` | `AppSetting`, `AlertSource` |
| Modificar | `main.py` | Registrar settings router |
| Modificar | `core/http_client.py`, `routers/{internal,processes,nodes,orchestrator}.py`, `utils/helpers.py`, `services/{vod_service,cms_gateway}.py`, `monitor/commands.py` | API-key desde BD |
| Modificar | `monitor/alerts.py` | Telegram/CMS con toggles |
| Modificar | `services/vod_service.py` | Refactor tsmonitor + endpoint genérico |
| Modificar | `routers/alert_rules.py`, `templates/alert_rules.html` | `source` desde BD |
| Modificar | `templates/base.html` | Dropdown Parámetros Generales |
| Modificar | `tests/conftest.py` | Fixtures `admin_client`, `operator_client` |
| Modificar | `core/version.py`, `CHANGELOG.md`, `README.md`, `INSTALLATION_GUIDE.md` | v2.19.0 + docs |

---

### Task 1: Issue GitHub + cambio OpenSpec

**Files:**
- Crear issue en `eskiconce/Mgo_Orquestador`
- Crear: `openspec/changes/parametros-generales/{proposal.md,tasks.md,specs/parametros/spec.md}`

**Interfaces:**
- Produces: issue #N (referenciar en CHANGELOG Task 9), cambio OpenSpec `parametros-generales`.

- [ ] **Step 1: Crear issue en GitHub**

Título: `Parámetros Generales: config notificaciones (Telegram/Correo/CMS), API-key en BD y fuentes de alertas`
Labels: `enhancement`
Body (resumen del spec):

```markdown
Spec completo: docs/superpowers/specs/2026-09-29-parameters-menu-design.md

## Alcance
1. Dropdown "Parámetros Generales" = Usuarios + Parámetros (Reglas Alertas y KMS sin cambios)
2. /ui/settings: Seguridad (API-key), Telegram, Correo (SMTP | Microsoft Graph OAuth), CMS, Fuentes de alertas (CRUD con token)
3. API-key global migra de config.py a app_settings (BD = fuente única, efecto inmediato, fallback al default)
4. Endpoint genérico POST /api/fuentes/{slug}/alertas (payload tsmonitor, x-api-key por fuente)
5. source de reglas alimentado desde alert_sources (fin del hardcoded)
6. Correo: config + botón de prueba (envío en alertas → issue futuro)
7. Endpoints dedicados tsmonitor/packager: siguen abiertos sin token

## Fuera de alcance
Envío de correos en alertas, auth sobre endpoints dedicados, rotación/hashing de keys.

## Versión: v2.19.0 (MINOR)
```

- [ ] **Step 2: Crear cambio OpenSpec**

Run: `cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador && openspec new change parametros-generales`
Expected: directorio `openspec/changes/parametros-generales/` creado (si el CLI pide confirmación, aceptar).

- [ ] **Step 3: Escribir proposal.md**

`openspec/changes/parametros-generales/proposal.md`:

```markdown
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
```

- [ ] **Step 4: Escribir specs/parametros/spec.md**

```markdown
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
```

- [ ] **Step 5: Escribir tasks.md**

```markdown
# Tasks

- [ ] 1. Issue GitHub + cambio OpenSpec (proposal, spec, tasks)
- [ ] 2. Migración 003 + modelos AppSetting/AlertSource + settings_service + tests
- [ ] 3. API-key global desde BD (validación + saliente) + tests
- [ ] 4. notify_telegram / notify_cms con toggles desde BD + tests
- [ ] 5. email_service (SMTP/Graph) + API settings/sources + tests
- [ ] 6. UI /ui/settings + menú Parámetros Generales + tests
- [ ] 7. alert_intake refactor + endpoint genérico /api/fuentes/{slug}/alertas + tests
- [ ] 8. Reglas source desde BD + dropdown dinámico en alert_rules.html + tests
- [ ] 9. v2.19.0 + CHANGELOG + README + INSTALLATION_GUIDE + push
- [ ] 10. Deploy servidor + verificación + openspec archive + cierre issue
```

- [ ] **Step 6: Run `openspec instructions` y revisar salida**

Run: `cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador && openspec instructions`
Expected: imprime el workflow de OpenSpec — seguirlo para el resto de tareas (tasks de arriba).

- [ ] **Step 7: Commit + push**

```bash
cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador
git add openspec/changes/parametros-generales/
git commit -m "docs(openspec): change parametros-generales — proposal + spec + tasks"
git push
```

---

### Task 2: Migración 003 + modelos + settings_service

**Files:**
- Crear: `scripts/migrations/003_app_settings_alert_sources.sql`
- Modificar: `models.py` (agregar `AppSetting`, `AlertSource` al final del archivo; agregar `UniqueConstraint` al import de sqlalchemy línea 1)
- Crear: `services/settings_service.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `get_setting(db, section, key, default=None) -> Optional[str]`
  - `get_section(db, section, defaults=None) -> dict`
  - `save_section(db, section, values: dict) -> None`
  - `get_api_key(db=None) -> str` (db opcional; si es None usa `SessionLocal` propio con fallback `AGENT_API_KEY`)
  - `SECTION_DEFAULTS: dict` (defaults por sección: telegram, email, cms, security)
  - Modelos `models.AppSetting`, `models.AlertSource`

- [ ] **Step 1: Escribir la migración**

`scripts/migrations/003_app_settings_alert_sources.sql`:

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    section VARCHAR(50) NOT NULL,
    `key` VARCHAR(100) NOT NULL,
    value TEXT NULL,
    UNIQUE KEY uq_section_key (section, `key`)
);

CREATE TABLE IF NOT EXISTS alert_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    token VARCHAR(64) NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    description VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_alert_sources_slug (slug)
);

INSERT INTO app_settings (section, `key`, value) VALUES
('telegram', 'enabled', '0'),
('telegram', 'bot_token', ''),
('telegram', 'chat_id', ''),
('email', 'enabled', '0'),
('email', 'auth_mode', 'smtp'),
('email', 'smtp_host', ''),
('email', 'smtp_port', '587'),
('email', 'smtp_tls', '1'),
('email', 'smtp_user', ''),
('email', 'smtp_password', ''),
('email', 'graph_tenant_id', ''),
('email', 'graph_client_id', ''),
('email', 'graph_client_secret', ''),
('email', 'from_addr', ''),
('email', 'recipients', ''),
('cms', 'enabled', '1'),
('cms', 'webhook_url', 'https://core-dev.mundogo.cl/api/webhook-vod'),
('security', 'api_key', 'a1b2c3d4e5f67890123456789abcdef0')
ON DUPLICATE KEY UPDATE `key` = `key`;

INSERT INTO alert_sources (slug, name, token, enabled, description) VALUES
('tsmonitor', 'TSMonitor', '', 1, 'Endpoint dedicado /api/alertas/tsmonitor (abierto, sin token)'),
('packager', 'Packager', '', 1, 'Endpoint dedicado /api/alertas/packager (abierto, sin token)'),
('encoder', 'Encoder', '', 1, 'Alertas internas del encoder')
ON DUPLICATE KEY UPDATE slug = slug;
```

Nota: `run_migrations.py` divide en `;` — no incluir `;` dentro de strings (no los hay).

- [ ] **Step 2: Modelos en `models.py`**

Agregar al import de sqlalchemy (línea 1) `UniqueConstraint` y al final del archivo:

```python
class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    section = Column(String(50), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("section", "key", name="uq_section_key"),)


class AlertSource(Base):
    __tablename__ = "alert_sources"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    token = Column(String(64), nullable=False)
    enabled = Column(Boolean, default=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

- [ ] **Step 3: `services/settings_service.py`**

```python
"""
Settings service — parámetros de la plataforma en app_settings (clave-valor por sección).
Fuente única de verdad; fallback a defaults cuando la fila no existe.
"""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from core.config import AGENT_API_KEY

logger = logging.getLogger(__name__)

SECTION_DEFAULTS: Dict[str, Dict[str, str]] = {
    "telegram": {"enabled": "0", "bot_token": "", "chat_id": ""},
    "email": {
        "enabled": "0", "auth_mode": "smtp",
        "smtp_host": "", "smtp_port": "587", "smtp_tls": "1",
        "smtp_user": "", "smtp_password": "",
        "graph_tenant_id": "", "graph_client_id": "", "graph_client_secret": "",
        "from_addr": "", "recipients": "",
    },
    "cms": {"enabled": "1", "webhook_url": "https://core-dev.mundogo.cl/api/webhook-vod"},
    "security": {"api_key": AGENT_API_KEY},
}


def get_setting(db: Session, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
    from models import AppSetting
    row = db.query(AppSetting).filter(
        AppSetting.section == section, AppSetting.key == key
    ).first()
    if row is not None and row.value is not None:
        return row.value
    return default


def get_section(db: Session, section: str, defaults: Optional[dict] = None) -> dict:
    from models import AppSetting
    result = dict(defaults if defaults is not None else SECTION_DEFAULTS.get(section, {}))
    for row in db.query(AppSetting).filter(AppSetting.section == section).all():
        result[row.key] = row.value
    return result


def save_section(db: Session, section: str, values: dict) -> None:
    from models import AppSetting
    for key, value in values.items():
        row = db.query(AppSetting).filter(
            AppSetting.section == section, AppSetting.key == key
        ).first()
        if row is not None:
            row.value = value
        else:
            db.add(AppSetting(section=section, key=key, value=value))
    db.commit()


def get_api_key(db: Session = None) -> str:
    """API-key global desde BD. Si db es None usa SessionLocal propio.
    Fallback: valor de config.AGENT_API_KEY si la fila falta o hay error."""
    own_session = db is None
    if own_session:
        from database import SessionLocal
        db = SessionLocal()
    try:
        value = get_setting(db, "security", "api_key", default=AGENT_API_KEY)
        return value or AGENT_API_KEY
    except Exception as e:
        logger.warning(f"No se pudo leer security.api_key de BD, usando default: {e}")
        return AGENT_API_KEY
    finally:
        if own_session:
            db.close()
```

- [ ] **Step 4: Escribir test (failing primero)**

`tests/test_settings.py`:

```python
"""
Tests para settings_service (app_settings clave-valor + API-key).
"""
import pytest
from core.config import AGENT_API_KEY
from services.settings_service import get_setting, get_section, save_section, get_api_key


class TestSettingsService:

    def test_get_setting_fallback_when_missing(self, db_session):
        assert get_setting(db_session, "telegram", "bot_token", default="fallback") == "fallback"

    def test_save_and_get_setting(self, db_session):
        save_section(db_session, "telegram", {"bot_token": "XYZ", "enabled": "1"})
        assert get_setting(db_session, "telegram", "bot_token") == "XYZ"
        assert get_setting(db_session, "telegram", "enabled") == "1"

    def test_get_section_merges_defaults(self, db_session):
        save_section(db_session, "telegram", {"bot_token": "XYZ"})
        sec = get_section(db_session, "telegram", defaults={"bot_token": "", "enabled": "0"})
        assert sec["bot_token"] == "XYZ"
        assert sec["enabled"] == "0"

    def test_get_api_key_fallback_when_no_row(self, db_session):
        assert get_api_key(db_session) == AGENT_API_KEY

    def test_get_api_key_reads_db(self, db_session):
        save_section(db_session, "security", {"api_key": "nueva_key_1234567890"})
        assert get_api_key(db_session) == "nueva_key_1234567890"

    def test_get_api_key_empty_value_falls_back(self, db_session):
        save_section(db_session, "security", {"api_key": ""})
        assert get_api_key(db_session) == AGENT_API_KEY
```

- [ ] **Step 5: Correr test — esperar PASS**

Run: `cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador && python3 -m pytest tests/test_settings.py -v`
Expected: 6 passed

- [ ] **Step 6: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: todos pasan (28+)

- [ ] **Step 7: Commit**

```bash
git add scripts/migrations/003_app_settings_alert_sources.sql models.py services/settings_service.py tests/test_settings.py
git commit -m "feat(settings): migración 003 app_settings/alert_sources + settings_service"
```

---

### Task 3: API-key global desde BD

**Files:**
- Modificar validación (incoming):
  - `routers/internal.py:20-23` (`verify_api_key`)
  - `utils/helpers.py:12-14` (`verify_cms_token`)
  - `services/vod_service.py:37-38` (log de webhook)
- Modificar saliente (headers `X-API-Key` hacia agentes/Haproxy) — reemplazar `AGENT_API_KEY` por `get_api_key()` en:
  - `core/http_client.py:18,27`
  - `routers/internal.py:85,86,135`
  - `routers/processes.py:143,160,192,210,234,250,253,265`
  - `routers/nodes.py:36,49`
  - `routers/orchestrator.py:39,92,170`
  - `monitor/commands.py:18`
  - `utils/helpers.py:43,84,100`
  - `services/vod_service.py:330,499` (y cualquier otro uso en el archivo)
  - `services/cms_gateway.py:147,203,231`
- Test: `tests/test_settings.py` (agregar clase)

**Interfaces:**
- Consumes: `get_api_key(db=None)` de Task 2.
- Produces: validación y salientes usan `get_api_key()`; firmas `verify_api_key(x_api_key, db)` y `verify_cms_token(x_api_key, db)` aceptan `db` (FastAPI `Depends(get_db)`).

- [ ] **Step 1: Actualizar `verify_api_key` en `routers/internal.py`**

Reemplazar las líneas 20-23 por:

```python
def verify_api_key(x_api_key: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """Verifica X-API-Key para endpoints internos (lee de BD con fallback)."""
    import secrets
    from services.settings_service import get_api_key
    if not x_api_key or not secrets.compare_digest(x_api_key, get_api_key(db)):
        raise HTTPException(status_code=401, detail="API key inválida")
```

(importar `Depends` — ya está de fastapi; `get_db` ya importado en el archivo.)

- [ ] **Step 2: Actualizar `verify_cms_token` en `utils/helpers.py`**

Reemplazar líneas 12-14 por (agregar `Depends` al import de fastapi de la línea 3 y `get_db`):

```python
from fastapi import Header, HTTPException, Depends
from database import get_db

def verify_cms_token(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    import secrets
    from services.settings_service import get_api_key
    if not secrets.compare_digest(x_api_key, get_api_key(db)):
        raise HTTPException(status_code=403, detail="Token de CMS inválido")
    return x_api_key
```

Nota: `utils/helpers.py` ya importa `Session` de sqlalchemy.orm. Evitar import circular: `services.settings_service` solo importa `core.config`/`models`/`database` — seguro.

- [ ] **Step 3: Reemplazar salientes en todos los archivos listados**

En cada archivo: agregar `from services.settings_service import get_api_key` (al lado de los imports de core.config) y reemplazar TODAS las apariciones de `AGENT_API_KEY` en:
- dicts de headers (`headers = {"X-API-Key": AGENT_API_KEY}` → `get_api_key()`)
- `headers.setdefault("X-API-Key", AGENT_API_KEY)` → `get_api_key()`
- comparaciones (`api_key != AGENT_API_KEY` → `secrets.compare_digest(api_key, get_api_key(db))`, manteniendo el solo-log de `vod_service.py:38`)

Luego: `rg "AGENT_API_KEY" --glob '!backup*' --glob '!*.bak*' -l` debe retornar solo: `core/config.py` (definición), `services/settings_service.py` (fallback) y `backup/`.

`vod_service.py` línea 9: si `AGENT_API_KEY` ya no se usa en el archivo, quitarlo del import de core.config (mantener `CMS_REAL_WEBHOOK, ORCHESTRATOR_WEBHOOK_URL, VOD_API_PORT`).

- [ ] **Step 4: Tests (failing primero)**

Agregar a `tests/test_settings.py`:

```python
import pytest
from fastapi import HTTPException
from services.settings_service import save_section


class TestApiKeyValidation:

    def test_internal_verify_accepts_db_key(self, db_session):
        from routers.internal import verify_api_key
        save_section(db_session, "security", {"api_key": "k" * 32})
        verify_api_key("k" * 32, db_session)  # no levanta excepción

    def test_internal_verify_rejects_wrong_key(self, db_session):
        from routers.internal import verify_api_key
        save_section(db_session, "security", {"api_key": "k" * 32})
        with pytest.raises(HTTPException) as exc:
            verify_api_key("wrong", db_session)
        assert exc.value.status_code == 401

    def test_internal_verify_fallback_default_key(self, db_session):
        from routers.internal import verify_api_key
        verify_api_key(AGENT_API_KEY, db_session)  # sin fila en BD → default pasa

    def test_cms_token_rejects_wrong_key(self, db_session):
        from utils.helpers import verify_cms_token
        save_section(db_session, "security", {"api_key": "otra_key_1234567890"})
        with pytest.raises(HTTPException) as exc:
            verify_cms_token("wrong", db_session)
        assert exc.value.status_code == 403

    def test_cms_token_accepts_db_key(self, db_session):
        from utils.helpers import verify_cms_token
        save_section(db_session, "security", {"api_key": "otra_key_1234567890"})
        verify_cms_token("otra_key_1234567890", db_session)


class TestApiKeyOutgoing:

    def test_http_client_injects_current_key(self, monkeypatch):
        import core.http_client as hc
        monkeypatch.setattr(hc, "get_api_key", lambda: "clave_nueva_desde_bd")
        client = hc.create_sync_client()
        try:
            assert client.headers["X-API-Key"] == "clave_nueva_desde_bd"
        finally:
            client.close()

    def test_async_client_injects_current_key(self, monkeypatch):
        import core.http_client as hc
        monkeypatch.setattr(hc, "get_api_key", lambda: "otra_clave_bd")
        client = hc.create_async_client()
        try:
            assert client.headers["X-API-Key"] == "otra_clave_bd"
        finally:
            pass  # cierre async manejado por httpx
```

Nota: `core/http_client.py` debe importar `get_api_key` a nivel de módulo (`from services.settings_service import get_api_key`) para que el monkeypatch funcione.

- [ ] **Step 5: Correr tests**

Run: `python3 -m pytest tests/test_settings.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Suite completa + grep de verificación**

```bash
python3 -m pytest tests/ -q
rg "AGENT_API_KEY" --glob '!backup*' --glob '!backup_v2*' --glob '!*.bak*' --glob '!*-V1*' -l
```
Expected: suite PASS; grep solo `core/config.py`, `services/settings_service.py`, `services/vod_service.py-09jun26.V1.py` (archivo viejo — no modificar).

- [ ] **Step 7: Commit**

```bash
git add -A ':!backup_v2.17.2_20260929_155605'
git commit -m "feat(security): API-key global desde BD con fallback y efecto inmediato"
```

---

### Task 4: Telegram/CMS con toggles desde BD

**Files:**
- Modificar: `monitor/alerts.py`
- Test: `tests/test_settings.py` (agregar clase)

**Interfaces:**
- Consumes: `get_setting(db, section, key, default)`.
- Produces: `notify_telegram(message)` y `notify_cms_channel_status(channel_id, status_event, description)` con firma idéntica (cambios internos).

- [ ] **Step 1: Reescribir `monitor/alerts.py`**

```python
"""
Monitor — Alerts module.
CMS notifications and Telegram alerts (toggles y parámetros desde app_settings).
"""
import httpx
import logging
from datetime import datetime
from sqlalchemy.orm import Session

import models
from core.config import CMS_REAL_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import SessionLocal
from services.settings_service import get_setting

logger = logging.getLogger(__name__)


def notify_telegram(message):
    """Envía mensaje a Telegram si telegram.enabled=1 en app_settings."""
    db = SessionLocal()
    try:
        if get_setting(db, "telegram", "enabled", "0") != "1":
            return
        token = get_setting(db, "telegram", "bot_token", "") or TELEGRAM_BOT_TOKEN
        chat_id = get_setting(db, "telegram", "chat_id", "") or TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass
    finally:
        db.close()


def notify_cms_channel_status(channel_id, status_event, description):
    """Envía webhook al CMS si cms.enabled=1 en app_settings. Posee su propia sesión (Thread-Safe)."""
    db = SessionLocal()
    try:
        if get_setting(db, "cms", "enabled", "1") != "1":
            return
        channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
        if not channel:
            return

        payload = {
            "event": "channel_status",
            "canal": channel.ruta if channel.ruta else channel.channel_name.lower().replace(" ", "_"),
            "status": status_event,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }

        webhook = get_setting(db, "cms", "webhook_url", "") or CMS_REAL_WEBHOOK
        logger.info(f"Notificando al CMS evento '{status_event}' para el canal {payload['canal']}")
        with httpx.Client(timeout=5.0) as client:
            client.post(webhook, json=payload)

    except Exception as e:
        logger.error(f"Error enviando notificación de estado al CMS: {e}")
    finally:
        db.close()
```

- [ ] **Step 2: Tests (failing primero)**

Agregar a `tests/test_settings.py`:

```python
import models


class TestNotificationToggles:

    def test_telegram_disabled_does_not_send(self, db_session, monkeypatch):
        import monitor.alerts as ma
        calls = []
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "post", lambda *a, **k: calls.append(a) or True)
        ma.notify_telegram("hola")
        assert calls == []

    def test_telegram_enabled_sends_with_bd_params(self, db_session, monkeypatch):
        import monitor.alerts as ma
        save_section(db_session, "telegram", {"enabled": "1", "bot_token": "TOK123", "chat_id": "42"})
        calls = []
        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return True
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "post", fake_post)
        ma.notify_telegram("hola")
        assert len(calls) == 1
        assert "TOK123" in calls[0][0]
        assert calls[0][1]["json"]["chat_id"] == "42"

    def test_cms_disabled_does_not_send(self, db_session, monkeypatch):
        import monitor.alerts as ma
        ch = models.Channel(channel_name="Canal Test", unique_id="991")
        db_session.add(ch)
        db_session.commit()
        save_section(db_session, "cms", {"enabled": "0", "webhook_url": "https://x/cl"})
        posts = []
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, **kw): posts.append(url)
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "Client", lambda **kw: FakeClient())
        ma.notify_cms_channel_status(ch.id, "error", "prueba")
        assert posts == []

    def test_cms_enabled_uses_bd_webhook(self, db_session, monkeypatch):
        import monitor.alerts as ma
        ch = models.Channel(channel_name="Canal Test 2", unique_id="992")
        db_session.add(ch)
        db_session.commit()
        save_section(db_session, "cms", {"enabled": "1", "webhook_url": "https://cms.nuevo/webhook"})
        posts = []
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, url, **kw): posts.append(url)
        monkeypatch.setattr(ma, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(ma.httpx, "Client", lambda **kw: FakeClient())
        ma.notify_cms_channel_status(ch.id, "error", "prueba")
        assert posts == ["https://cms.nuevo/webhook"]
```

Advertencia: `notify_*` hace `db.close()` en `finally` sobre `db_session` — SQLAlchemy permite reusar la sesión después de close (el fixture la cierra igual al final). Si el fixture falla por drop_all con sesión cerrada, cambiar `ma.SessionLocal` por una lambda que retorne una sesión nueva sobre el mismo engine: `sessionmaker(bind=db_session.get_bind())()`. Usar esa variante si el fixture reporta error.

- [ ] **Step 3: Correr tests**

Run: `python3 -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 4: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/alerts.py tests/test_settings.py
git commit -m "feat(notify): telegram y CMS con toggles/params desde app_settings"
```

---

### Task 5: email_service + API settings/sources

**Files:**
- Crear: `services/email_service.py`
- Crear: `routers/settings.py`
- Modificar: `main.py` (import + `include_router` — patrón de las líneas 17-28 y 61-74)
- Modificar: `tests/conftest.py` (fixtures admin/operator)
- Test: `tests/test_settings.py` (agregar clases API)

**Interfaces:**
- Consumes: `SECTION_DEFAULTS`, `get_section`, `save_section` (Task 2), `require_role`, `get_current_user` (`core/deps.py`).
- Produces:
  - `send_test_email(db) -> {"status": "ok"|"error", "message": str}`
  - `GET /api/settings` → `{sección: {clave: valor}}` (admin)
  - `GET/PUT /api/settings/{section}` (admin; PUT body `{"values": {clave: valor}}`)
  - `POST /api/settings/email/test` (admin)
  - `GET/POST /api/alert-sources`, `PUT/DELETE /api/alert-sources/{id}`, `POST /api/alert-sources/{id}/regenerate-token` (admin)
  - Response fuente: `{id, slug, name, token, enabled, description}`

- [ ] **Step 1: Fixtures en `tests/conftest.py`**

Agregar:

```python
@pytest.fixture(name="admin_client")
def fixture_admin_client(client, db_session):
    """Client con cookie de admin."""
    from core.deps import create_access_token
    import models as m
    user = m.User(username="admin_t", full_name="Admin Test", email="admin_t@test.cl",
                  hashed_password="x", role="admin", disabled=False)
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": "admin_t"})
    client.cookies.set("access_token", f"Bearer {token}")
    yield client
    client.cookies.clear()


@pytest.fixture(name="operator_client")
def fixture_operator_client(client, db_session):
    """Client con cookie de operator."""
    from core.deps import create_access_token
    import models as m
    user = m.User(username="operator_t", full_name="Operator Test", email="op_t@test.cl",
                  hashed_password="x", role="operator", disabled=False)
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": "operator_t"})
    client.cookies.set("access_token", f"Bearer {token}")
    yield client
    client.cookies.clear()
```

- [ ] **Step 2: `services/email_service.py`**

```python
"""
Email service — envío de correos por SMTP o Microsoft Graph OAuth (client_credentials).
Incluye envío de prueba desde /ui/settings. El envío en alertas llega en un issue futuro.
"""
import time
import smtplib
from email.mime.text import MIMEText
from typing import Optional

import httpx

from core.logging_service import logger
from services.settings_service import SECTION_DEFAULTS, get_section

GRAPH_TOKEN_URL = "https://graph.microsoft.com/{tenant}/oauth2/v2.0/token"
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

_token_cache = {"token": None, "expires_at": 0.0}


def _graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = httpx.post(
        GRAPH_TOKEN_URL.format(tenant=tenant_id),
        data={"client_id": client_id, "client_secret": client_secret,
              "grant_type": "client_credentials", "scope": GRAPH_SCOPE},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + float(data.get("expires_in", 5400))
    return _token_cache["token"]


def _recipients(settings: dict) -> list:
    raw = settings.get("recipients") or settings.get("from_addr") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def _build_message(settings: dict, subject: str, body: str) -> MIMEText:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.get("from_addr") or settings.get("smtp_user") or "orquestador@mundogo.cl"
    msg["To"] = ", ".join(_recipients(settings))
    return msg


def _send_smtp(settings: dict, msg: MIMEText) -> None:
    host = settings.get("smtp_host")
    port = int(settings.get("smtp_port") or 587)
    use_tls = settings.get("smtp_tls", "1") == "1"
    user = settings.get("smtp_user") or ""
    password = settings.get("smtp_password") or ""
    if use_tls:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)


def _send_graph(settings: dict, msg: MIMEText) -> None:
    token = _graph_token(settings["graph_tenant_id"], settings["graph_client_id"],
                         settings["graph_client_secret"])
    payload = {
        "message": {
            "subject": msg["Subject"],
            "body": {"contentType": "Text", "content": msg.get_payload()},
            "toRecipients": [{"emailAddress": {"address": a}} for a in _recipients(settings)],
        },
        "saveToSentItems": "true",
    }
    resp = httpx.post(GRAPH_SEND_URL, json=payload,
                      headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()


def send_test_email(db) -> dict:
    """Envía correo de prueba con la configuración actual. Retorna {status, message}."""
    try:
        settings = get_section(db, "email", defaults=SECTION_DEFAULTS["email"])
        if settings.get("enabled") != "1":
            return {"status": "error", "message": "Correo deshabilitado — actívalo primero."}
        required = ["from_addr", "recipients"]
        if settings.get("auth_mode") == "graph":
            required += ["graph_tenant_id", "graph_client_id", "graph_client_secret"]
        else:
            required += ["smtp_host"]
        missing = [k for k in required if not settings.get(k)]
        if missing:
            return {"status": "error", "message": f"Faltan parámetros: {', '.join(missing)}"}
        if not _recipients(settings):
            return {"status": "error", "message": "Sin destinatarios válidos."}
        msg = _build_message(settings, "Prueba de conexión — Mgo_Orquestador",
                             "Este es un correo de prueba enviado desde el orquestador Mgo_Orquestador.")
        if settings.get("auth_mode") == "graph":
            _send_graph(settings, msg)
        else:
            _send_smtp(settings, msg)
        logger.info("Correo de prueba enviado correctamente")
        return {"status": "ok", "message": "Correo de prueba enviado correctamente."}
    except Exception as e:
        logger.error(f"Error en prueba de correo: {e}")
        return {"status": "error", "message": str(e)}
```

- [ ] **Step 3: `routers/settings.py`**

```python
"""
Router de Parámetros Generales — configuración (app_settings), correo de prueba
y CRUD de fuentes de alertas (alert_sources). Solo admin.
"""
import re
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db
from core.deps import templates, get_current_user, require_role
from services.settings_service import SECTION_DEFAULTS, get_section, save_section
from services.email_service import send_test_email

router = APIRouter(tags=["settings"])

admin_only = require_role("admin")


def _normalize_value(key: str, value: Any) -> str:
    if key in ("enabled", "smtp_tls"):
        return "1" if str(value).lower() in ("1", "true", "on", "yes") else "0"
    if value is None:
        return ""
    return str(value).strip()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]


# --- Parámetros (app_settings) ---

@router.get("/api/settings")
def list_settings(db: Session = Depends(get_db), current_user: models.User = Depends(admin_only)):
    return {section: get_section(db, section, defaults=defaults)
            for section, defaults in SECTION_DEFAULTS.items()}


class SectionUpdate(BaseModel):
    values: Dict[str, Any]


@router.get("/api/settings/{section}")
def get_settings_section(section: str, db: Session = Depends(get_db),
                          current_user: models.User = Depends(admin_only)):
    if section not in SECTION_DEFAULTS:
        raise HTTPException(404, "Sección desconocida")
    return get_section(db, section, defaults=SECTION_DEFAULTS[section])


@router.put("/api/settings/{section}")
def update_settings_section(section: str, body: SectionUpdate,
                            db: Session = Depends(get_db),
                            current_user: models.User = Depends(admin_only)):
    if section not in SECTION_DEFAULTS:
        raise HTTPException(404, "Sección desconocida")
    allowed = set(SECTION_DEFAULTS[section].keys())
    unknown = set(body.values.keys()) - allowed
    if unknown:
        raise HTTPException(400, f"Claves no permitidas: {sorted(unknown)}")
    values = {k: _normalize_value(k, v) for k, v in body.values.items()}
    if section == "security" and "api_key" in values and len(values["api_key"]) < 16:
        raise HTTPException(400, "API key mínimo 16 caracteres")
    if section == "email":
        if "auth_mode" in values and values["auth_mode"] not in ("smtp", "graph"):
            raise HTTPException(400, "auth_mode debe ser 'smtp' o 'graph'")
        port = values.get("smtp_port")
        if port and not (port.isdigit() and 1 <= int(port) <= 65535):
            raise HTTPException(400, "smtp_port inválido")
    save_section(db, section, values)
    return {"status": "saved", "section": section}


@router.post("/api/settings/email/test")
def test_email(db: Session = Depends(get_db), current_user: models.User = Depends(admin_only)):
    return send_test_email(db)


# --- Fuentes de alertas (alert_sources) ---

class SourceCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


def _source_dict(r: models.AlertSource) -> dict:
    return {"id": r.id, "slug": r.slug, "name": r.name, "token": r.token,
            "enabled": bool(r.enabled), "description": r.description or ""}


@router.get("/api/alert-sources")
def list_sources(db: Session = Depends(get_db), current_user: models.User = Depends(admin_only)):
    rows = db.query(models.AlertSource).order_by(models.AlertSource.name).all()
    return [_source_dict(r) for r in rows]


@router.post("/api/alert-sources")
def create_source(body: SourceCreate, db: Session = Depends(get_db),
                  current_user: models.User = Depends(admin_only)):
    slug = _slugify(body.slug or body.name)
    if not slug:
        raise HTTPException(400, "Nombre/slug inválido")
    if db.query(models.AlertSource).filter(models.AlertSource.slug == slug).first():
        raise HTTPException(409, f"El slug '{slug}' ya existe")
    row = models.AlertSource(slug=slug, name=body.name.strip(),
                             token=secrets.token_hex(16),
                             enabled=body.enabled, description=body.description)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "created", **_source_dict(row)}


@router.put("/api/alert-sources/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: Session = Depends(get_db),
                  current_user: models.User = Depends(admin_only)):
    row = db.query(models.AlertSource).filter(models.AlertSource.id == source_id).first()
    if not row:
        raise HTTPException(404, "Fuente no encontrada")
    if body.slug is not None:
        slug = _slugify(body.slug)
        if not slug:
            raise HTTPException(400, "Slug inválido")
        dup = db.query(models.AlertSource).filter(
            models.AlertSource.slug == slug, models.AlertSource.id != source_id).first()
        if dup:
            raise HTTPException(409, f"El slug '{slug}' ya existe")
        row.slug = slug
    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description
    if body.enabled is not None:
        row.enabled = body.enabled
    db.commit()
    return {"status": "updated", **_source_dict(row)}


@router.post("/api/alert-sources/{source_id}/regenerate-token")
def regenerate_token(source_id: int, db: Session = Depends(get_db),
                     current_user: models.User = Depends(admin_only)):
    row = db.query(models.AlertSource).filter(models.AlertSource.id == source_id).first()
    if not row:
        raise HTTPException(404, "Fuente no encontrada")
    row.token = secrets.token_hex(16)
    db.commit()
    return {"status": "regenerated", "token": row.token}


@router.delete("/api/alert-sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db),
                  current_user: models.User = Depends(admin_only)):
    row = db.query(models.AlertSource).filter(models.AlertSource.id == source_id).first()
    if not row:
        raise HTTPException(404, "Fuente no encontrada")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": source_id}
```

- [ ] **Step 4: Registrar router en `main.py`**

```python
from routers.settings import router as settings_router
```
(después de `alert_rules_router`, línea 28)

```python
app.include_router(settings_router)
```
(después de `app.include_router(alert_rules_router)`, línea 74)

- [ ] **Step 5: Tests API (failing primero)**

Agregar a `tests/test_settings.py`:

```python
class TestSettingsAPI:

    def test_api_settings_requires_auth(self, client):
        assert client.get("/api/settings").status_code == 401

    def test_api_settings_forbidden_for_operator(self, operator_client):
        assert operator_client.get("/api/settings").status_code == 403

    def test_put_telegram_persists_for_admin(self, admin_client, db_session):
        resp = admin_client.put("/api/settings/telegram",
                                json={"values": {"enabled": "1", "bot_token": "ABC", "chat_id": "7"}})
        assert resp.status_code == 200
        assert get_setting(db_session, "telegram", "bot_token") == "ABC"
        got = admin_client.get("/api/settings/telegram").json()
        assert got["bot_token"] == "ABC"

    def test_put_rejects_unknown_key(self, admin_client):
        resp = admin_client.put("/api/settings/telegram", json={"values": {"hacker": "x"}})
        assert resp.status_code == 400

    def test_put_rejects_unknown_section(self, admin_client):
        assert admin_client.put("/api/settings/nope", json={"values": {"a": "b"}}).status_code == 404

    def test_put_security_short_key_rejected(self, admin_client):
        resp = admin_client.put("/api/settings/security", json={"values": {"api_key": "corto"}})
        assert resp.status_code == 400

    def test_put_email_invalid_auth_mode(self, admin_client):
        resp = admin_client.put("/api/settings/email", json={"values": {"auth_mode": "pigeon"}})
        assert resp.status_code == 400

    def test_checkbox_normalization(self, admin_client, db_session):
        admin_client.put("/api/settings/telegram", json={"values": {"enabled": True}})
        assert get_setting(db_session, "telegram", "enabled") == "1"

    def test_email_test_disabled_returns_error(self, admin_client):
        resp = admin_client.post("/api/settings/email/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


class TestAlertSourcesAPI:

    def test_create_generates_token(self, admin_client, db_session):
        resp = admin_client.post("/api/alert-sources", json={"name": "Mi Fuente"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "mi-fuente"
        assert len(data["token"]) == 32

    def test_create_duplicate_slug_conflict(self, admin_client):
        admin_client.post("/api/alert-sources", json={"name": "Otra"})
        resp = admin_client.post("/api/alert-sources", json={"name": "otra!"})
        assert resp.status_code == 409

    def test_sources_require_admin(self, operator_client):
        assert operator_client.get("/api/alert-sources").status_code == 403

    def test_regenerate_changes_token(self, admin_client):
        created = admin_client.post("/api/alert-sources", json={"name": "Regen"}).json()
        resp = admin_client.post(f"/api/alert-sources/{created['id']}/regenerate-token")
        assert resp.status_code == 200
        assert resp.json()["token"] != created["token"]

    def test_update_and_delete(self, admin_client):
        created = admin_client.post("/api/alert-sources", json={"name": "Borrar"}).json()
        resp = admin_client.put(f"/api/alert-sources/{created['id']}",
                                json={"enabled": False, "description": "d"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        resp = admin_client.delete(f"/api/alert-sources/{created['id']}")
        assert resp.status_code == 200
        assert admin_client.get("/api/alert-sources").json() == [] or \
            all(s["id"] != created["id"] for s in admin_client.get("/api/alert-sources").json())
```

- [ ] **Step 6: Correr tests**

Run: `python3 -m pytest tests/test_settings.py -v`
Expected: PASS (todos)

- [ ] **Step 7: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add services/email_service.py routers/settings.py main.py tests/conftest.py tests/test_settings.py
git commit -m "feat(settings): API de parámetros, correo SMTP/Graph de prueba y CRUD de fuentes"
```

---

### Task 6: UI /ui/settings + menú Parámetros Generales

**Files:**
- Crear: `templates/settings.html`
- Modificar: `routers/settings.py` (agregar endpoint UI)
- Modificar: `templates/base.html` (líneas 68-70: reemplazar `<li>` de Usuarios por dropdown)
- Test: `tests/test_settings.py` (classe TestSettingsUI)

**Interfaces:**
- Consumes: API de Task 5.
- Produces: `GET /ui/settings` (admin) → `templates/settings.html`.

- [ ] **Step 1: Endpoint UI en `routers/settings.py`**

Agregar (al inicio de la sección UI, antes de los endpoints API o al final):

```python
@router.get("/ui/settings")
def settings_ui(request: Request, db: Session = Depends(get_db),
                current_user: models.User = Depends(admin_only)):
    settings = {s: get_section(db, s, defaults=d) for s, d in SECTION_DEFAULTS.items()}
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": current_user, "settings": settings,
    })
```

- [ ] **Step 2: Menú en `templates/base.html`**

Reemplazar (líneas 68-70):

```html
                <li class="nav-item">
                    <a class="nav-link" href="/ui/users"><i class="fas fa-users-cog me-1"></i> Usuarios</a>
                </li>
```

por:

```html
                <li class="nav-item dropdown">
                    <a class="nav-link dropdown-toggle" href="#" id="paramsDropdown" role="button" data-bs-toggle="dropdown" aria-expanded="false">
                        <i class="fas fa-sliders-h me-1"></i> Parámetros Generales
                    </a>
                    <ul class="dropdown-menu">
                        <li><h6 class="dropdown-header"><i class="fas fa-cog me-1"></i>Parámetros Generales</h6></li>
                        <li><a class="dropdown-item" href="/ui/users"><i class="fas fa-users-cog me-2"></i>Usuarios</a></li>
                        <li><a class="dropdown-item" href="/ui/settings"><i class="fas fa-sliders-h me-2"></i>Parámetros</a></li>
                    </ul>
                </li>
```

*Reglas Alertas* y *KMS* quedan intactos.

- [ ] **Step 3: `templates/settings.html`**

```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-3">
    <h4 class="mb-1"><i class="fas fa-sliders-h me-2"></i>Parámetros Generales</h4>
    <p class="text-muted">Configuración de notificaciones, seguridad y fuentes de alertas.</p>

    <div class="row">
        <!-- SEGURIDAD -->
        <div class="col-lg-6 mb-3">
            <div class="card h-100">
                <div class="card-header"><i class="fas fa-shield-alt me-1"></i> Seguridad — API Key global</div>
                <div class="card-body">
                    <div class="mb-2"><small class="text-muted">Actual: <span id="apiKeyMask" class="font-monospace">—</span></small></div>
                    <div class="input-group mb-2">
                        <input type="password" class="form-control font-monospace" id="sec-security-api_key" data-section="security" data-key="api_key" autocomplete="off">
                        <button class="btn btn-outline-secondary" type="button" onclick="toggleKey()" title="Mostrar/ocultar"><i class="fas fa-eye" id="keyEye"></i></button>
                    </div>
                    <div class="alert alert-warning py-2 mb-2">
                        <small><i class="fas fa-exclamation-triangle me-1"></i>Cambiar el API key invalida inmediatamente las conexiones externas (agentes, CMS) que usen el key actual.</small>
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="saveSection('security', this)">Guardar</button>
                </div>
            </div>
        </div>

        <!-- TELEGRAM -->
        <div class="col-lg-6 mb-3">
            <div class="card h-100">
                <div class="card-header"><i class="fab fa-telegram me-1"></i> Telegram</div>
                <div class="card-body">
                    <div class="form-check form-switch mb-2">
                        <input class="form-check-input" type="checkbox" id="sec-telegram-enabled" data-section="telegram" data-key="enabled">
                        <label class="form-check-label" for="sec-telegram-enabled">Activar notificaciones Telegram</label>
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Bot Token</label>
                        <input type="password" class="form-control font-monospace" id="sec-telegram-bot_token" data-section="telegram" data-key="bot_token" autocomplete="off">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Chat ID</label>
                        <input type="text" class="form-control" id="sec-telegram-chat_id" data-section="telegram" data-key="chat_id">
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="saveSection('telegram', this)">Guardar</button>
                </div>
            </div>
        </div>

        <!-- CMS -->
        <div class="col-lg-6 mb-3">
            <div class="card h-100">
                <div class="card-header"><i class="fas fa-broadcast-tower me-1"></i> CMS — Webhook de notificación</div>
                <div class="card-body">
                    <div class="form-check form-switch mb-2">
                        <input class="form-check-input" type="checkbox" id="sec-cms-enabled" data-section="cms" data-key="enabled">
                        <label class="form-check-label" for="sec-cms-enabled">Activar notificaciones al CMS</label>
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Webhook URL</label>
                        <input type="text" class="form-control" id="sec-cms-webhook_url" data-section="cms" data-key="webhook_url">
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="saveSection('cms', this)">Guardar</button>
                </div>
            </div>
        </div>

        <!-- CORREO -->
        <div class="col-lg-6 mb-3">
            <div class="card h-100">
                <div class="card-header"><i class="fas fa-envelope me-1"></i> Correo electrónico</div>
                <div class="card-body">
                    <div class="form-check form-switch mb-2">
                        <input class="form-check-input" type="checkbox" id="sec-email-enabled" data-section="email" data-key="enabled">
                        <label class="form-check-label" for="sec-email-enabled">Activar correo</label>
                    </div>
                    <div class="mb-2">
                        <label class="form-label d-block">Modo de autenticación</label>
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="email_auth_mode" id="modeSmtp" value="smtp" data-section="email" data-key="auth_mode" onchange="updateEmailMode()">
                            <label class="form-check-label" for="modeSmtp">SMTP</label>
                        </div>
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="email_auth_mode" id="modeGraph" value="graph" data-section="email" data-key="auth_mode" onchange="updateEmailMode()">
                            <label class="form-check-label" for="modeGraph">Microsoft Graph (OAuth)</label>
                        </div>
                    </div>
                    <div id="smtpFields">
                        <div class="row">
                            <div class="col-md-6 mb-2">
                                <label class="form-label">SMTP Host</label>
                                <input type="text" class="form-control" id="sec-email-smtp_host" data-section="email" data-key="smtp_host" placeholder="smtp.mailgun.org">
                            </div>
                            <div class="col-md-3 mb-2">
                                <label class="form-label">Puerto</label>
                                <input type="number" class="form-control" id="sec-email-smtp_port" data-section="email" data-key="smtp_port">
                            </div>
                            <div class="col-md-3 mb-2">
                                <label class="form-label">TLS</label>
                                <select class="form-select" id="sec-email-smtp_tls" data-section="email" data-key="smtp_tls">
                                    <option value="1">STARTTLS</option>
                                    <option value="0">SSL (465)</option>
                                </select>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-2">
                                <label class="form-label">Usuario</label>
                                <input type="text" class="form-control" id="sec-email-smtp_user" data-section="email" data-key="smtp_user" autocomplete="off">
                            </div>
                            <div class="col-md-6 mb-2">
                                <label class="form-label">Contraseña</label>
                                <input type="password" class="form-control" id="sec-email-smtp_password" data-section="email" data-key="smtp_password" autocomplete="off">
                            </div>
                        </div>
                    </div>
                    <div id="graphFields" style="display:none">
                        <div class="row">
                            <div class="col-md-4 mb-2">
                                <label class="form-label">Tenant ID</label>
                                <input type="text" class="form-control font-monospace" id="sec-email-graph_tenant_id" data-section="email" data-key="graph_tenant_id" autocomplete="off">
                            </div>
                            <div class="col-md-4 mb-2">
                                <label class="form-label">Client ID</label>
                                <input type="text" class="form-control font-monospace" id="sec-email-graph_client_id" data-section="email" data-key="graph_client_id" autocomplete="off">
                            </div>
                            <div class="col-md-4 mb-2">
                                <label class="form-label">Client Secret</label>
                                <input type="password" class="form-control font-monospace" id="sec-email-graph_client_secret" data-section="email" data-key="graph_client_secret" autocomplete="off">
                            </div>
                        </div>
                        <small class="text-muted">App daemon con permiso Mail.Send (client_credentials, se renueva solo).</small>
                    </div>
                    <div class="row mt-1">
                        <div class="col-md-6 mb-2">
                            <label class="form-label">Desde (remitente)</label>
                            <input type="email" class="form-control" id="sec-email-from_addr" data-section="email" data-key="from_addr" placeholder="orquestador@empresa.cl">
                        </div>
                        <div class="col-md-6 mb-2">
                            <label class="form-label">Destinatarios (separados por coma)</label>
                            <input type="text" class="form-control" id="sec-email-recipients" data-section="email" data-key="recipients" placeholder="ops@empresa.cl, alertas@empresa.cl">
                        </div>
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="saveSection('email', this)">Guardar</button>
                    <button class="btn btn-outline-secondary btn-sm" id="btnTestEmail" onclick="testEmail(this)"><i class="fas fa-paper-plane me-1"></i>Probar envío</button>
                </div>
            </div>
        </div>

        <!-- FUENTES DE ALERTAS -->
        <div class="col-12 mb-3">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><i class="fas fa-satellite-dish me-1"></i> Fuentes de alertas externas</span>
                    <button class="btn btn-primary btn-sm" onclick="openSourceModal()"><i class="fas fa-plus me-1"></i>Nueva fuente</button>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-sm align-middle">
                            <thead>
                                <tr><th>Nombre</th><th>Slug</th><th>Token</th><th>Estado</th><th class="text-end">Acciones</th></tr>
                            </thead>
                            <tbody id="sourcesBody">
                                <tr><td colspan="5" class="text-muted">Cargando…</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="bg-light border rounded p-3 mt-2">
                        <h6>Integración de fuentes</h6>
                        <p class="mb-1">Las fuentes nuevas envían alertas con el mismo formato de TSMonitor:</p>
                        <pre class="mb-2 small">POST /api/fuentes/&lt;slug&gt;/alertas
x-api-key: &lt;token de la fuente&gt;
Content-Type: application/json

{"num_canal": 123, "fecha": "2026-09-29", "hora": "10:30:00", "status": "freeze"}</pre>
                        <small class="text-muted">La fuente debe estar registrada y activa. Los endpoints dedicados (tsmonitor/packager) no usan token.</small>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Modal fuente -->
<div class="modal fade" id="sourceModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="srcModalTitle">Nueva fuente</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div class="mb-2">
                    <label class="form-label">Nombre *</label>
                    <input type="text" class="form-control" id="srcName" placeholder="Monitor Satelital">
                </div>
                <div class="mb-2">
                    <label class="form-label">Slug (URL)</label>
                    <input type="text" class="form-control" id="srcSlug" placeholder="auto desde el nombre">
                </div>
                <div class="mb-2">
                    <label class="form-label">Descripción</label>
                    <input type="text" class="form-control" id="srcDesc">
                </div>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="srcEnabled" checked>
                    <label class="form-check-label" for="srcEnabled">Activo</label>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                <button type="button" class="btn btn-primary" onclick="saveSource()">Guardar</button>
            </div>
        </div>
    </div>
</div>

<script>
let SETTINGS = {};
let SOURCES = [];
let editingId = null;

function maskKey(k) { return (!k) ? '(vacío)' : '••••••••' + k.slice(-4); }

function setVal(section, key, value) {
    const el = document.getElementById(`sec-${section}-${key}`);
    if (!el) return;
    if (el.type === 'checkbox') {
        el.checked = (value === '1' || value === 1 || value === true);
    } else if (el.type === 'radio') {
        document.querySelectorAll(`input[name="${key === 'auth_mode' ? 'email_auth_mode' : el.name}"]`)
            .forEach(r => r.checked = (r.value === String(value)));
    } else {
        el.value = (value === null || value === undefined) ? '' : value;
    }
}

async function loadAll() {
    try {
        const r = await fetch('/api/settings');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        SETTINGS = await r.json();
    } catch (e) { alert('Error cargando parámetros: ' + e.message); return; }
    document.getElementById('apiKeyMask').textContent = maskKey(SETTINGS.security.api_key);
    document.getElementById('sec-security-api_key').value = SETTINGS.security.api_key || '';
    setVal('telegram', 'enabled', SETTINGS.telegram.enabled);
    setVal('telegram', 'bot_token', SETTINGS.telegram.bot_token);
    setVal('telegram', 'chat_id', SETTINGS.telegram.chat_id);
    setVal('cms', 'enabled', SETTINGS.cms.enabled);
    setVal('cms', 'webhook_url', SETTINGS.cms.webhook_url);
    setVal('email', 'enabled', SETTINGS.email.enabled);
    document.querySelectorAll('input[name="email_auth_mode"]').forEach(r => {
        r.checked = (r.value === (SETTINGS.email.auth_mode || 'smtp'));
    });
    ['smtp_host', 'smtp_port', 'smtp_tls', 'smtp_user', 'smtp_password',
     'graph_tenant_id', 'graph_client_id', 'graph_client_secret',
     'from_addr', 'recipients'].forEach(k => setVal('email', k, SETTINGS.email[k]));
    updateEmailMode();
}

function updateEmailMode() {
    const mode = (document.querySelector('input[name="email_auth_mode"]:checked') || {value: 'smtp'}).value;
    document.getElementById('smtpFields').style.display = mode === 'smtp' ? '' : 'none';
    document.getElementById('graphFields').style.display = mode === 'graph' ? '' : 'none';
}

function collectSection(section) {
    const values = {};
    document.querySelectorAll(`[data-section="${section}"]`).forEach(el => {
        if (el.type === 'radio') return;
        values[el.dataset.key] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value;
    });
    if (section === 'email') {
        const r = document.querySelector('input[name="email_auth_mode"]:checked');
        if (r) values['auth_mode'] = r.value;
    }
    return values;
}

async function saveSection(section, btn) {
    const values = collectSection(section);
    try {
        const r = await fetch(`/api/settings/${section}`, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({values})
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) { alert(data.detail || 'Error al guardar'); return; }
        if (section === 'security') {
            document.getElementById('apiKeyMask').textContent = maskKey(values.api_key);
        }
        if (btn) {
            const t = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-check me-1"></i>Guardado';
            setTimeout(() => btn.innerHTML = t, 1500);
        }
    } catch (e) { alert('Error: ' + e.message); }
}

function toggleKey() {
    const inp = document.getElementById('sec-security-api_key');
    inp.type = inp.type === 'password' ? 'text' : 'password';
    document.getElementById('keyEye').className = inp.type === 'password' ? 'fas fa-eye' : 'fas fa-eye-slash';
}

async function testEmail(btn) {
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Enviando...';
    try {
        const r = await fetch('/api/settings/email/test', {method: 'POST'});
        const data = await r.json();
        alert((data.status === 'ok' ? 'OK: ' : 'Error: ') + data.message);
    } catch (e) { alert('Error: ' + e.message); }
    btn.disabled = false;
    btn.innerHTML = original;
}

async function loadSources() {
    try {
        const r = await fetch('/api/alert-sources');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        SOURCES = await r.json();
        renderSources();
    } catch (e) {
        document.getElementById('sourcesBody').innerHTML =
            `<tr><td colspan="5" class="text-danger">Error cargando fuentes: ${e.message}</td></tr>`;
    }
}

function renderSources() {
    const tb = document.getElementById('sourcesBody');
    if (!SOURCES.length) {
        tb.innerHTML = '<tr><td colspan="5" class="text-muted">Sin fuentes registradas</td></tr>';
        return;
    }
    tb.innerHTML = SOURCES.map(s => `
        <tr>
            <td>${s.name}</td>
            <td><code>${s.slug}</code></td>
            <td>
                <span class="font-monospace" id="tok-${s.id}">••••••••${s.token.slice(-4)}</span>
                <button class="btn btn-link btn-sm p-0 ms-1" onclick="revealToken(${s.id})" title="Revelar token"><i class="fas fa-eye"></i></button>
            </td>
            <td>${s.enabled ? '<span class="badge bg-success">Activo</span>' : '<span class="badge bg-secondary">Inactivo</span>'}</td>
            <td class="text-end">
                <button class="btn btn-outline-secondary btn-sm" onclick="openSourceModal(${s.id})" title="Editar"><i class="fas fa-edit"></i></button>
                <button class="btn btn-outline-warning btn-sm" onclick="regenToken(${s.id})" title="Regenerar token"><i class="fas fa-sync-alt"></i></button>
                <button class="btn btn-outline-danger btn-sm" onclick="deleteSource(${s.id})" title="Eliminar"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
}

function revealToken(id) {
    const s = SOURCES.find(x => x.id === id);
    if (s) document.getElementById('tok-' + id).textContent = s.token;
}

function openSourceModal(id = null) {
    editingId = id;
    const s = id ? SOURCES.find(x => x.id === id) : null;
    document.getElementById('srcName').value = s ? s.name : '';
    document.getElementById('srcSlug').value = s ? s.slug : '';
    document.getElementById('srcDesc').value = s ? s.description : '';
    document.getElementById('srcEnabled').checked = s ? s.enabled : true;
    document.getElementById('srcModalTitle').textContent = id ? 'Editar fuente' : 'Nueva fuente';
    new bootstrap.Modal(document.getElementById('sourceModal')).show();
}

async function saveSource() {
    const body = {
        name: document.getElementById('srcName').value.trim(),
        slug: document.getElementById('srcSlug').value.trim() || null,
        description: document.getElementById('srcDesc').value.trim() || null,
        enabled: document.getElementById('srcEnabled').checked
    };
    if (!body.name) { alert('El nombre es obligatorio'); return; }
    try {
        const url = editingId ? `/api/alert-sources/${editingId}` : '/api/alert-sources';
        const r = await fetch(url, {
            method: editingId ? 'PUT' : 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) { alert(data.detail || 'Error al guardar'); return; }
        bootstrap.Modal.getInstance(document.getElementById('sourceModal')).hide();
        await loadSources();
    } catch (e) { alert('Error: ' + e.message); }
}

async function regenToken(id) {
    if (!confirm('Regenerar token: la fuente dejará de autenticar hasta que se actualice su token. Continuar?')) return;
    try {
        const r = await fetch(`/api/alert-sources/${id}/regenerate-token`, {method: 'POST'});
        if (!r.ok) { alert('Error al regenerar'); return; }
        await loadSources();
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteSource(id) {
    if (!confirm('Eliminar esta fuente?')) return;
    try {
        const r = await fetch(`/api/alert-sources/${id}`, {method: 'DELETE'});
        if (!r.ok) { alert('Error al eliminar'); return; }
        await loadSources();
    } catch (e) { alert('Error: ' + e.message); }
}

loadAll();
loadSources();
</script>
{% endblock %}
```

- [ ] **Step 4: Tests UI (failing primero)**

Agregar a `tests/test_settings.py`:

```python
class TestSettingsUI:

    def test_settings_page_renders_for_admin(self, admin_client):
        resp = admin_client.get("/ui/settings")
        assert resp.status_code == 200
        assert "Parámetros Generales" in resp.text
        assert "Fuentes de alertas" in resp.text

    def test_settings_page_forbidden_for_operator(self, operator_client):
        assert operator_client.get("/ui/settings").status_code == 403

    def test_settings_page_requires_auth(self, client):
        assert client.get("/ui/settings").status_code == 401

    def test_menu_shows_params_dropdown(self, admin_client):
        resp = admin_client.get("/ui/settings")
        assert "paramsDropdown" in resp.text
        assert 'href="/ui/users"' in resp.text
        assert 'href="/ui/settings"' in resp.text
```

- [ ] **Step 5: Correr tests**

Run: `python3 -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 6: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add templates/settings.html templates/base.html routers/settings.py tests/test_settings.py
git commit -m "feat(ui): página Parámetros Generales + dropdown en menú"
```

---

### Task 7: alert_intake refactor + endpoint genérico de fuentes

**Files:**
- Crear: `services/alert_intake.py`
- Modificar: `services/alert_normalizer.py` (`normalize_tsmonitor_alert` — parámetro `source`)
- Modificar: `services/vod_service.py` (refactor endpoint tsmonitor + endpoint nuevo)
- Test: `tests/test_alert_intake.py`

**Interfaces:**
- Consumes: `normalize_tsmonitor_alert(..., source=...)`, `process_alert`, `get_api_key`.
- Produces:
  - `services/alert_intake.py::ChannelNotFound(Exception)`
  - `handle_tsmonitor_style_alert(db, source, reporter, event_type, num_canal, fecha, hora, status) -> dict` (misma forma de retorno que el tsmonitor actual: `{"status", "message", "rule", "action_taken"}`; lanza `ChannelNotFound` si el canal no existe)
  - `POST /api/fuentes/{slug}/alertas` (Header `x-api-key`) → 200 dict, 404 slug/canal, 403 token/deshabilitada

- [ ] **Step 1: `source` param en `alert_normalizer.py`**

Firma actual (líneas ~54-62):

```python
def normalize_tsmonitor_alert(
    num_canal,
    status: str,
    fecha: str,
    hora: str,
    channel_id: int
) -> NormalizedAlert:
```

Cambiar a:

```python
def normalize_tsmonitor_alert(
    num_canal,
    status: str,
    fecha: str,
    hora: str,
    channel_id: int,
    source: str = "tsmonitor"
) -> NormalizedAlert:
```

Y dentro, en el `return NormalizedAlert(...)` cambiar `source="tsmonitor"` → `source=source`. Caller existentes sin `source` siguen igual.

- [ ] **Step 2: Leer el bloque completo a mover**

Run: `sed -n '442,564p' services/vod_service.py`
Expected: ves el endpoint `receive_tsmonitor_alert` completo (desde el `try` hasta el `return` final). Este bloque se mueve íntegro a `services/alert_intake.py` — únicamente se aplican los 4 cambios listados en Step 3.

- [ ] **Step 3: Crear `services/alert_intake.py`**

```python
"""
Alert Intake — ingesta de alertas externas con payload estilo TSMonitor.
Compartido por el endpoint dedicado /api/alertas/tsmonitor y el
endpoint genérico /api/fuentes/{slug}/alertas.
"""
import httpx
import atexit
from datetime import datetime
from typing import Union

from sqlalchemy.orm import Session

import models
from core.logging_service import logger
from services.alert_normalizer import normalize_tsmonitor_alert
from services.alert_rule_engine import process_alert
from services.settings_service import get_api_key


class ChannelNotFound(Exception):
    """El canal indicado en la alerta no existe."""


_http = httpx.Client(
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
)
atexit.register(_http.close)


def handle_tsmonitor_style_alert(
    db: Session,
    source: str,
    reporter: str,
    event_type: str,
    num_canal: Union[int, str],
    fecha: str,
    hora: str,
    status: str,
) -> dict:
    """Canal → normaliza → MonitorLog → motor de reglas → acción en encoder → commit.

    Lanza ChannelNotFound si el canal no existe.
    Retorna {"status", "message", "rule", "action_taken"} (forma del endpoint tsmonitor actual).
    """
    # 1. Buscar el Canal — por unique_id con fallback a id
    channel = db.query(models.Channel).filter(
        models.Channel.unique_id == str(num_canal)
    ).first()

    if not channel:
        try:
            numeric_id = int(num_canal)
            channel = db.query(models.Channel).filter(
                models.Channel.id == numeric_id
            ).first()
        except (TypeError, ValueError):
            channel = None

    if not channel:
        raise ChannelNotFound(f"Canal {num_canal} no encontrado.")

    # 2. Normalizar alerta a formato interno
    normalized = normalize_tsmonitor_alert(
        num_canal=num_canal,
        status=status,
        fecha=fecha,
        hora=hora,
        channel_id=channel.id,
        source=source,
    )

    # 3. Registrar en monitor_logs
    alert_entry = models.MonitorLog(
        event_type=event_type,
        message=f"Alerta externa [{status}] para el canal {channel.channel_name}. Reportada por {reporter}.",
        node_id=None,
        timestamp=normalized.timestamp
    )
    db.add(alert_entry)
    db.flush()

    # 4. Procesar con motor de reglas
    result = process_alert(db, normalized)

    # 5. Si la regla indica ejecutar acción en encoder, hacerlo
    if result["action_taken"] and result["rule"]:
        rule_action = result["rule"]["action"]

        encoder_job = db.query(models.EncodingJob).join(models.Node).filter(
            models.EncodingJob.channel_id == channel.id,
            models.Node.tipo == 'Encoder'
        ).first()

        if encoder_job and rule_action in ["stop_encoder", "start_encoder", "restart_encoder"]:
            agent_ip = encoder_job.node.ip_address
            headers = {"X-API-Key": get_api_key(db)}
            prog_name = f"channel_{channel.channel_name}_{encoder_job.id}"

            try:
                <MOVER AQUÍ EL BLOQUE try/except COMPLETO del endpoint tsmonitor actual
                 (líneas ~500-560 de vod_service.py: ramas stop_encoder / start_encoder /
                 restart_encoder y cualquier otra rama existente), cambiando SOLO:
                 - headers ya está arriba (get_api_key(db) en vez de AGENT_API_KEY)
                 - referencias a _http → _http (de este módulo)
                 - referencias a payload_start / variables locales: mantenerlas idénticas>
            except Exception as e:
                logger.warning(f"Error ejecutando acción en encoder: {e}")

    db.commit()
    return {
        "status": "success",
        "message": result.get("message", "Alerta procesada"),
        "rule": result.get("rule"),
        "action_taken": result.get("action_taken", False),
    }
```

**Importante:** el bloque `<MOVER AQUÍ...>` se copia textualmente de `vod_service.py` (Step 2), sin reescribirlo — solo asegurar que use el `_http` de este módulo y que las ramas existentes queden intactas.

- [ ] **Step 4: Reescribir `receive_tsmonitor_alert` en `vod_service.py`**

```python
@router.post("/api/alertas/tsmonitor")
def receive_tsmonitor_alert(payload: TSMonitorAlert, db: Session = Depends(get_db)):
    from services.alert_intake import handle_tsmonitor_style_alert, ChannelNotFound
    try:
        return handle_tsmonitor_style_alert(
            db, source="tsmonitor", reporter="TSMonitor",
            event_type="TSMONITOR_ALERT",
            num_canal=payload.num_canal, fecha=payload.fecha,
            hora=payload.hora, status=payload.status,
        )
    except ChannelNotFound as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
```

(Los bloques antiguos del endpoint — búsqueda de canal, normalización, MonitorLog, motor, acciones — quedan eliminados de `vod_service.py` porque viven en `alert_intake`.)

- [ ] **Step 5: Endpoint genérico en `vod_service.py` (al final del archivo, antes de `# ---- fin de archivo ----`)**

Agregar imports (ajustar línea existente `from fastapi import APIRouter, Depends, Body` → incluir `Header, HTTPException`; y `import secrets` arriba):

```python
# ==========================================
# INGESTA GENÉRICA DE FUENTES REGISTRADAS
# ==========================================

class SourceAlertPayload(BaseModel):
    num_canal: Union[int, str]
    fecha: str
    hora: str
    status: str


@router.post("/api/fuentes/{slug}/alertas")
def receive_source_alert(slug: str, payload: SourceAlertPayload,
                         db: Session = Depends(get_db),
                         x_api_key: Union[str, None] = Header(default=None)):
    """Alerta de fuente registrada en Parámetros Generales (token por fuente)."""
    import secrets as _secrets
    from services.alert_intake import handle_tsmonitor_style_alert, ChannelNotFound

    src = db.query(models.AlertSource).filter(models.AlertSource.slug == slug).first()
    if not src:
        raise HTTPException(status_code=404, detail="Fuente no registrada")
    if not src.enabled:
        raise HTTPException(status_code=403, detail="Fuente deshabilitada")
    if not x_api_key or not _secrets.compare_digest(x_api_key, src.token):
        raise HTTPException(status_code=403, detail="Token de fuente inválido")

    try:
        return handle_tsmonitor_style_alert(
            db, source=slug, reporter=src.name,
            event_type=f"EXT_ALERT_{slug.upper()}",
            num_canal=payload.num_canal, fecha=payload.fecha,
            hora=payload.hora, status=payload.status,
        )
    except ChannelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
```

Verificar: `grep -n "from fastapi import" services/vod_service.py` — `Header` y `HTTPException` deben estar importados (el import de línea 14 `from fastapi import Request` es aparte; agregar `Header, HTTPException` al import de la línea 1).

- [ ] **Step 6: Tests (failing primero)**

`tests/test_alert_intake.py`:

```python
"""
Tests del intake de alertas: tsmonitor (refactor) + endpoint genérico de fuentes.
"""
import pytest
import models
from services.settings_service import save_section


@pytest.fixture(name="canal")
def fixture_canal(db_session):
    ch = models.Channel(channel_name="Canal Uno", unique_id="777")
    db_session.add(ch)
    db_session.commit()
    return ch


@pytest.fixture(name="fuente")
def fixture_fuente(db_session):
    src = models.AlertSource(slug="mi-fuente", name="Mi Fuente", token="t" * 32, enabled=True)
    db_session.add(src)
    db_session.commit()
    return src


class TestTsmonitorPreserved:

    def test_tsmonitor_unknown_channel_returns_error_dict(self, client):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": 999999, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "no encontrado" in data["message"]

    def test_tsmonitor_happy_path(self, client, canal):
        resp = client.post("/api/alertas/tsmonitor",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["action_taken"] is False  # sin reglas configuradas


class TestGenericSourceEndpoint:

    def test_unknown_slug_404(self, client):
        resp = client.post("/api/fuentes/nope/alertas",
                           json={"num_canal": 1, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 404

    def test_wrong_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "wrong"},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_missing_token_403(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_disabled_source_403(self, client, db_session, fuente):
        fuente.enabled = False
        db_session.commit()
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "freeze"})
        assert resp.status_code == 403

    def test_channel_not_found_404(self, client, fuente):
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": 424242, "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "down"})
        assert resp.status_code == 404

    def test_happy_path_enters_rule_engine(self, client, db_session, canal, fuente):
        rule = models.AlertRule(name="Regla Mi Fuente", source="mi-fuente",
                                alert_type="down", action="notify_only",
                                enabled=True, priority=100, cooldown_seconds=0)
        db_session.add(rule)
        db_session.commit()
        resp = client.post("/api/fuentes/mi-fuente/alertas",
                           headers={"x-api-key": "t" * 32},
                           json={"num_canal": "777", "fecha": "2026-09-29",
                                 "hora": "10:00:00", "status": "dead"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["rule"] is not None
        assert data["rule"]["name"] == "Regla Mi Fuente"
        # MonitorLog con event_type de la fuente
        log = db_session.query(models.MonitorLog).filter(
            models.MonitorLog.event_type == "EXT_ALERT_MI-FUENTE").first()
        assert log is not None
```

Nota: `notify_only` en `execute_action` puede intentar Telegram/CMS — con settings sin `enabled` no envían (Task 4) y `cooldown_seconds=0` evita cooldown.

- [ ] **Step 7: Correr tests**

Run: `python3 -m pytest tests/test_alert_intake.py -v`
Expected: PASS

- [ ] **Step 8: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add services/alert_intake.py services/vod_service.py services/alert_normalizer.py tests/test_alert_intake.py
git commit -m "feat(alerts): intake compartido + endpoint generico /api/fuentes/{slug}/alertas con token"
```

---

### Task 8: Reglas con source desde BD

**Files:**
- Modificar: `routers/alert_rules.py` (validación en create/update + endpoint `GET /api/alert-rules/sources`)
- Modificar: `templates/alert_rules.html` (dropdowns dinámicos)
- Test: `tests/test_settings.py` (classe TestRulesSources)

**Interfaces:**
- Consumes: `models.AlertSource` (Task 2).
- Produces: `GET /api/alert-rules/sources` → `[{slug, name, enabled}]` incluyendo `{"slug": "any", "name": "Any (Global)", "enabled": true}`.

- [ ] **Step 1: Helper de validación en `routers/alert_rules.py`**

Agregar después de `router = APIRouter(...)`:

```python
def _valid_sources(db: Session) -> list:
    """Sources válidos = slugs en alert_sources + 'any' (desde BD, no hardcoded)."""
    rows = db.query(models.AlertSource.slug).all()
    return [r[0] for r in rows] + ["any"]
```

- [ ] **Step 2: Reemplazar los dos bloques hardcoded**

Línea 87 (`create`):

```python
    valid_sources = ["tsmonitor", "packager", "encoder", "any"]
```
→
```python
    valid_sources = _valid_sources(db)
```

Línea 137 (`update`):

```python
        valid_sources = ["tsmonitor", "packager", "encoder", "any"]
```
→
```python
        valid_sources = _valid_sources(db)
```

- [ ] **Step 3: Endpoint de fuentes para el dropdown**

```python
@router.get("/api/alert-rules/sources")
def list_alert_sources(db: Session = Depends(get_db),
                       current_user: models.User = Depends(get_current_user)):
    """Sources disponibles para el dropdown de reglas: filas de alert_sources + 'any'."""
    rows = db.query(models.AlertSource).order_by(models.AlertSource.name).all()
    sources = [{"slug": r.slug, "name": r.name, "enabled": bool(r.enabled)} for r in rows]
    sources.append({"slug": "any", "name": "Any (Global)", "enabled": True})
    return sources
```

- [ ] **Step 4: Dropdowns dinámicos en `templates/alert_rules.html`**

a) En `#filterSource` (líneas ~37-42) eliminar las 4 `<option>` de fuentes (dejar solo `<option value="">Todas las fuentes</option>`).
b) En `#ruleSource` (líneas ~165-170) eliminar las 4 `<option>` (dejar el `<select>` vacío).
c) Al final del bloque `{% endblock %}` (justo antes del cierre, después de los scripts existentes) agregar:

```html
<script>
async function loadRuleSources() {
    try {
        const resp = await fetch('/api/alert-rules/sources');
        if (!resp.ok) return;
        const sources = await resp.json();
        const filter = document.getElementById('filterSource');
        const ruleSel = document.getElementById('ruleSource');
        sources.forEach(s => {
            const label = s.enabled ? s.name : s.name + ' (deshabilitada)';
            filter.insertAdjacentHTML('beforeend', `<option value="${s.slug}">${label}</option>`);
            ruleSel.insertAdjacentHTML('beforeend', `<option value="${s.slug}">${label}</option>`);
        });
    } catch (e) { console.error('Error cargando fuentes:', e); }
}
loadRuleSources();
</script>
```

- [ ] **Step 5: Tests (failing primero)**

Agregar a `tests/test_settings.py`:

```python
class TestRulesSources:

    def test_sources_endpoint_includes_any(self, admin_client):
        resp = admin_client.get("/api/alert-rules/sources")
        assert resp.status_code == 200
        slugs = [s["slug"] for s in resp.json()]
        assert "any" in slugs

    def test_sources_endpoint_lists_db_rows(self, admin_client):
        admin_client.post("/api/alert-sources", json={"name": "Nueva Fuente"})
        slugs = [s["slug"] for s in admin_client.get("/api/alert-rules/sources").json()]
        assert "nueva-fuente" in slugs

    def test_create_rule_with_db_source_ok(self, admin_client):
        admin_client.post("/api/alert-sources", json={"name": "Fuente Regla"})
        resp = admin_client.post("/api/alert-rules", json={
            "name": "R1", "source": "fuente-regla", "alert_type": "down",
            "action": "notify_only", "enabled": True, "priority": 10,
            "cooldown_seconds": 60,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"

    def test_create_rule_with_unknown_source_400(self, admin_client):
        resp = admin_client.post("/api/alert-rules", json={
            "name": "R2", "source": "no-existe", "alert_type": "down",
            "action": "notify_only", "enabled": True, "priority": 10,
            "cooldown_seconds": 60,
        })
        assert resp.status_code == 400

    def test_create_rule_any_still_works(self, admin_client):
        resp = admin_client.post("/api/alert-rules", json={
            "name": "R3", "source": "any", "alert_type": "freeze",
            "action": "notify_only", "enabled": True, "priority": 5,
            "cooldown_seconds": 60,
        })
        assert resp.status_code == 200
```

- [ ] **Step 6: Correr tests**

Run: `python3 -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 7: Suite completa**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add routers/alert_rules.py templates/alert_rules.html tests/test_settings.py
git commit -m "feat(rules): source desde alert_sources + dropdown dinámico"
```

---

### Task 9: v2.19.0 + CHANGELOG + docs + push

**Files:**
- Modificar: `core/version.py` (`VERSION_MINOR = 19`, `VERSION_PATCH = 0`)
- Modificar: `CHANGELOG.md` (entrada nueva arriba)
- Modificar: `README.md` (sección nueva tras "Migraciones de esquema")
- Modificar: `INSTALLATION_GUIDE.md` (versión actual, sección 5.3, tabla 6.3)

- [ ] **Step 1: Bump versión**

`core/version.py`:

```python
VERSION_MAJOR = 2
VERSION_MINOR = 19
VERSION_PATCH = 0
```

- [ ] **Step 2: CHANGELOG.md — nueva entrada al inicio**

```markdown
## v2.19.0 (29 Sep 2026) — Issue #N: Parámetros Generales + fuentes de alertas

- Nuevo: dropdown **Parámetros Generales** en menú (Usuarios + Parámetros; Reglas Alertas y KMS sin cambios)
- Nuevo: `/ui/settings` — configuración de Telegram, Correo (SMTP | Microsoft Graph OAuth), CMS, API-key global y CRUD de fuentes de alertas
- Nuevo: tabla `app_settings` — parámetros clave-valor en BD (migración `003_app_settings_alert_sources.sql`)
- Nuevo: tabla `alert_sources` + CRUD con token por fuente y regeneración
- Nuevo: endpoint genérico `POST /api/fuentes/{slug}/alertas` — payload estilo TSMonitor, auth `x-api-key` por fuente (404/403 según estado)
- Nuevo: `services/email_service.py` — envío SMTP (TLS/SSL) y Microsoft Graph (client_credentials) con botón "Probar envío"
- Nuevo: `services/settings_service.py` — lectura/escritura de parámetros con fallback a defaults
- Modificado: API-key global migra de `core/config.py` a BD (`security.api_key`) — efecto inmediato, comparación con `compare_digest`, fallback al default
- Modificado: `notify_telegram` y `notify_cms_channel_status` respetan toggles y parámetros desde BD
- Modificado: `source` de reglas de alerta alimentado desde `alert_sources` (fin del hardcoded `["tsmonitor","packager","encoder","any"]`)
- Modificado: `templates/alert_rules.html` — dropdown de fuentes cargado desde API
- Modificado: ingestión tsmonitor refactorizada a `services/alert_intake.py` (comportamiento idéntico preservado)
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/N
```

(Reemplazar `#N` por el número real del issue de Task 1.)

- [ ] **Step 3: README.md — sección nueva**

Insertar después del bloque de "Migraciones de esquema" (tras la línea "Las migraciones se encuentran en..."):

```markdown
## Parámetros Generales

Menú **Parámetros Generales → Parámetros** (`/ui/settings`, solo admin) centraliza la configuración en BD (`app_settings`):

| Sección | Contenido |
|---------|-----------|
| Seguridad | API-key global editable (cambio efecto inmediato en validaciones y salientes) |
| Telegram | `bot_token`, `chat_id` + activar/desactivar |
| Correo | SMTP o Microsoft Graph OAuth + activar/desactivar + botón "Probar envío" |
| CMS | `webhook_url` + activar/desactivar |
| Fuentes de alertas | CRUD de fuentes externas con token por fuente (`alert_sources`) |

Fuentes nuevas envían alertas con el mismo formato de TSMonitor:

```bash
curl -X POST http://<orquestador>:9000/api/fuentes/<slug>/alertas \
  -H "x-api-key: <token>" -H "Content-Type: application/json" \
  -d '{"num_canal": 123, "fecha": "2026-09-29", "hora": "10:30:00", "status": "freeze"}'
```
```

- [ ] **Step 4: INSTALLATION_GUIDE.md**

a) "### Versión actual" → `- **v2.19.0** (29 Sep 2026)`
b) Nueva subsección tras 5.2 (antes de `## 6. Base de Datos`):

```markdown
### 5.3 Parámetros Generales (UI)

`/ui/settings` (admin) permite editar sin deploy:

- **Seguridad:** API-key global (`app_settings.security.api_key`) — BD es fuente única con fallback al default de `core/config.py`.
- **Telegram:** `enabled`, `bot_token`, `chat_id` — controla `notify_telegram`.
- **Correo:** `enabled` + modo `auth_mode` (`smtp` con host/puerto/TLS/usuario/contraseña, o `graph` con tenant/client/secret de Microsoft 365) + remitente/destinatarios. Botón "Probar envío" valida la conexión real (el envío automático en alertas llegará en una mejora futura).
- **CMS:** `enabled` + `webhook_url` — controla `notify_cms_channel_status`.
- **Fuentes de alertas:** CRUD con token por fuente; endpoint genérico `POST /api/fuentes/{slug}/alertas` (payload `num_canal/fecha/hora/status`, header `x-api-key`). Los endpoints dedicados tsmonitor/packager no usan token.
```

c) En "### 6.3 Tablas principales" agregar dos filas al final de la tabla:

```markdown
| `app_settings` | Parámetros de plataforma (telegram, email, cms, security) |
| `alert_sources` | Fuentes externas de alerta con token |
```

- [ ] **Step 5: Verificar sintaxis local de TODO el código cambiado**

```bash
cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador
python3 -c "
import ast
files = ['models.py','main.py','core/http_client.py','core/version.py',
 'routers/settings.py','routers/internal.py','routers/processes.py','routers/nodes.py',
 'routers/orchestrator.py','routers/alert_rules.py','services/settings_service.py',
 'services/email_service.py','services/alert_intake.py','services/vod_service.py',
 'services/cms_gateway.py','utils/helpers.py','monitor/alerts.py','monitor/commands.py',
 'tests/conftest.py','tests/test_settings.py','tests/test_alert_intake.py']
for f in files: ast.parse(open(f).read())
print('SYNTAX OK', len(files), 'archivos')
"
```

Expected: `SYNTAX OK`

- [ ] **Step 6: Suite completa final**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit + push**

```bash
git add core/version.py CHANGELOG.md README.md INSTALLATION_GUIDE.md
git commit -m "chore: bump version v2.19.0 — Parámetros Generales + fuentes de alertas"
git push
```

---

### Task 10: Deploy + verificación + cierre

**Files:**
- Servidor `172.16.223.5:/opt/encoder-orchestrator/` (solo código)
- BD `encoder_orchestrator` (migración 003)

- [ ] **Step 1: Backup de BD antes de migrar**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "mysqldump -u ingservice -p'S3rv1c3.Ingenieria' encoder_orchestrator | gzip > /tmp/backup_pre_v2190_$(date +%Y%m%d_%H%M).sql.gz && ls -lh /tmp/backup_pre_v2190_*.sql.gz"
```

- [ ] **Step 2: Empaquetar y subir código**

```bash
cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador
tar czf /tmp/deploy_v2190.tgz \
  models.py main.py core/http_client.py core/version.py \
  routers/settings.py routers/internal.py routers/processes.py routers/nodes.py \
  routers/orchestrator.py routers/alert_rules.py \
  services/settings_service.py services/email_service.py services/alert_intake.py \
  services/vod_service.py services/cms_gateway.py services/alert_normalizer.py \
  utils/helpers.py monitor/alerts.py monitor/commands.py \
  templates/base.html templates/settings.html templates/alert_rules.html \
  scripts/migrations/003_app_settings_alert_sources.sql
scp -i ~/.ssh/id_opencode /tmp/deploy_v2190.tgz oymservice@172.16.223.5:/tmp/
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "echo 'S3rv1c3.operaciones' | sudo -S tar xzf /tmp/deploy_v2190.tgz -C /opt/encoder-orchestrator && echo DEPLOY_OK"
```

- [ ] **Step 3: Verificar sintaxis en el servidor**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 'python3 -c "
import ast
files = [\"models.py\",\"main.py\",\"routers/settings.py\",\"services/settings_service.py\",
\"services/email_service.py\",\"services/alert_intake.py\",\"services/vod_service.py\",
\"utils/helpers.py\",\"monitor/alerts.py\"]
for f in files: ast.parse(open(\"/opt/encoder-orchestrator/\"+f).read())
print(\"SYNTAX OK\")"'
```

- [ ] **Step 4: Ejecutar migración 003**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "echo 'S3rv1c3.operaciones' | sudo -S python3 /opt/encoder-orchestrator/scripts/run_migrations.py --status"
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "echo 'S3rv1c3.operaciones' | sudo -S python3 /opt/encoder-orchestrator/scripts/run_migrations.py"
```

Expected: `Applied: 003_app_settings_alert_sources.sql`

- [ ] **Step 4b: Habilitar Telegram en BD (decisión humana 2026-09-29)**

El default del plan es `telegram.enabled=0`; para no cortar alertas Telegram existentes en prod, setearlo tras la migración:

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "mysql -u ingservice -p'S3rv1c3.Ingenieria' -D encoder_orchestrator -e \"UPDATE app_settings SET value='1' WHERE section='telegram' AND \\\`key\\\`='enabled'; SELECT * FROM app_settings WHERE section='telegram';\""
```

Expected: fila `telegram/enabled` con value `1`.

- [ ] **Step 5: Reiniciar servicios**

```bash
ssh -i ~/.ssh/id_opencode oymservice@172.16.223.5 \
  "echo 'S3rv1c3.operaciones' | sudo -S systemctl restart encoder-monitor.service encoder-api.service && sleep 3 && systemctl is-active encoder-monitor.service encoder-api.service"
```

Expected: `active active`

- [ ] **Step 6: Verificación funcional**

```bash
# Login page
curl -sk -o /dev/null -w "login:%{http_code}\n" http://172.16.223.5:9000/login
# API-key actual (seed = key vigente) sigue autenticando
curl -sk -o /dev/null -w "key_ok:%{http_code}\n" -H "x-api-key: a1b2c3d4e5f67890123456789abcdef0" http://172.16.223.5:9000/api/cms/channels
# Key incorrecta rechazada
curl -sk -o /dev/null -w "key_bad:%{http_code}\n" -H "x-api-key: incorrecta123" http://172.16.223.5:9000/api/cms/channels
# Fuente inexistente → 404
curl -sk -o /dev/null -w "fuente:%{http_code}\n" -X POST http://172.16.223.5:9000/api/fuentes/nope/alertas \
  -H "Content-Type: application/json" -d '{"num_canal":1,"fecha":"2026-09-29","hora":"10:00:00","status":"freeze"}'
```

Expected: `login:200`, `key_ok:200`, `key_bad:403`, `fuente:404`

Verificación manual en navegador (pedir al usuario):
- Menú muestra **Parámetros Generales** con Usuarios + Parámetros; `/ui/settings` carga las 5 tarjetas.
- En BD: `SELECT section,`key` FROM app_settings;` → 19 filas; `SELECT slug FROM alert_sources;` → tsmonitor, packager, encoder.
- Jobs/nodos siguen operativos (dashboard sin errores en `journalctl -u encoder-monitor -n 50`).

- [ ] **Step 7: Push final y archive OpenSpec**

```bash
cd /Users/edmundocuevas/github/11_Git/Mgo_Orquestador
git push
openspec archive parametros-generales
```

- [ ] **Step 8: Cerrar issue**

Comentar en el issue: `Desplegado en v2.19.0 — migración 003 aplicada, servicios reiniciados y verificado.` y cerrarlo.

- [ ] **Step 9: Limpiar terminal**

Run: `clear`

---

## Self-Review (realizado al escribir el plan)

1. **Spec coverage:** menú (T6), settings service/modelos/migración (T2), API-key (T3), notificaciones (T4), email+test (T5), ingesta genérica+token (T7), sources en reglas (T8), UI completa (T6), roles admin (T5/T6), docs/versiono/despliegue (T9/T10), issue+OpenSpec (T1).
2. **Placeholders:** el único bloque "<MOVER AQUÍ...>" de T7 es intencional y explícito: copia textual de un bloque existente del repo (líneas 442-564 de `vod_service.py`), con las 4 transformaciones enumeradas — no es un TODO.
3. **Type consistency:** `get_api_key(db=None)`, `get_setting(db, section, key, default)`, `save_section(db, section, values)`, `handle_tsmonitor_style_alert(db, source, reporter, event_type, num_canal, fecha, hora, status)` usados igual en todas las tareas. `require_role("admin")` existe en `core/deps.py`.
