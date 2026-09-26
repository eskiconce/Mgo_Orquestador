# Mgo_Orquestador — MundoGo-Plus Orchestrator

Backend en FastAPI que orquesta el pipeline de encoding y streaming en vivo de MundoGo: gestión de nodos encoder, canales, jobs de FFmpeg/Shaka, DRM/KMS, monitoreo con recovery automático y failover.

## Características principales

- Gestión de nodos, canales y jobs de transcodificación (start/stop/restart/move)
- Generación automática de scripts FFmpeg/Shaka Packager por canal
- Monitoreo continuo con detección de reinicios, drop frames y discontinuidades, con recovery automático
- Integración DRM/KMS (rotación de llaves, health/stats)
- Failover de señal offline
- Autenticación JWT + RBAC (admin / operator / viewer)
- Health checks y métricas (`/api/health`, `/api/health/ready`, `/api/metrics`)

## Requisitos

- Python 3.9+
- MySQL (u otro motor compatible con SQLAlchemy vía la URL en `DATABASE_URL`)

## Instalación

```bash
git clone git@github.com:eskiconce/Mgo_Orquestador.git
cd Mgo_Orquestador

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Editar .env con los valores reales del entorno (ver sección Variables de entorno)
```

## Variables de entorno

Todas se configuran en `.env` (ver `.env.example` como plantilla). **Ninguna debe quedar con el valor de ejemplo en producción.**

| Variable | Descripción |
|---|---|
| `AGENT_API_KEY` | API key compartida con los agentes encoder |
| `AGENT_PORT` | Puerto de la API del orquestador |
| `DRM_HEALTH_PORT` | Puerto de health check de nodos DRM |
| `POLL_INTERVAL` | Intervalo (s) del loop de monitoreo |
| `ORCHESTRATOR_WEBHOOK_URL` | URL interna de webhook VOD |
| `CMS_REAL_WEBHOOK` | Webhook real hacia el CMS |
| `VOD_API_PORT` | Puerto de la API VOD |
| `HAPROXY_NODES` | IPs de nodos HAProxy (separadas por coma) |
| `HAPROXY_AGENT_PORT` | Puerto del agente HAProxy |
| `OFFLINE_IP` / `OFFLINE_PORT` / `OFFLINE_PROTO` | Señal de failover offline |
| `KMS_API_URL` / `KMS_API_KEY` | Integración con el servicio KMS/DRM |
| `SECRET_KEY` / `ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | Configuración JWT |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alertas por Telegram (opcional) |
| `DATABASE_URL` | Cadena de conexión SQLAlchemy a MySQL |

> `SECRET_KEY`, `AGENT_API_KEY`, `KMS_API_KEY` y `DATABASE_URL` deben generarse/rotarse por entorno. No reutilizar los valores de `.env.example`.

## Primer arranque

```bash
# Ejecutar migraciones de esquema (si es primera vez)
python scripts/run_migrations.py

# Crear usuario administrador
python crear_admin.py

# Levantar el servidor (desarrollo)
uvicorn main:app --reload --port 8000
```

La aplicación queda disponible en `http://localhost:8000`, con login en `/login`.

## Migraciones de esquema

El proyecto usa un sistema de migraciones SQL simple:

```bash
# Ver estado de migraciones
python scripts/run_migrations.py --status

# Ejecutar migraciones pendientes
python scripts/run_migrations.py
```

Las migraciones se encuentran en `scripts/migrations/` como archivos `.sql` numerados. El sistema crea una tabla `schema_migrations` en BD para tracking.

## Estructura del proyecto

```
main.py            # Punto de entrada — setup + inclusión de routers
database.py        # Configuración de SQLAlchemy (engine, sesión)
models.py          # Modelos SQLAlchemy
monitor.py          # Wrapper legacy → monitor/
monitor/            # Paquete de monitoreo (modularizado)
├── __init__.py     # Orquestación del loop principal
├── alerts.py       # CMS notifications + Telegram
├── checks.py       # TS errors, discontinuity, drop frames
├── commands.py     # send_command, kill_flow_safety
├── health.py       # Node health checks + restart detection
└── recovery.py     # Ghost cleanup, node recovery, failover

core/
├── config.py           # Configuración centralizada (.env vía python-dotenv)
├── deps.py             # Auth, roles, templates (dependencias compartidas)
├── errors.py           # Esquema de error/success unificado
├── http_client.py      # Factory httpx sync/async con connection pooling
├── logging_service.py  # Logging a archivo/BD, soporte JSON
├── rate_limit.py        # Rate limiting por IP
└── version.py           # Versionado del proyecto

routers/              # Un router por dominio
├── auth.py, users.py, dashboard.py, nodes.py, channels.py,
├── processes.py, drm.py, orchestrator.py, internal.py,
└── ui_logs.py, health.py

services/
├── builders.py       # Generadores de scripts FFmpeg/Shaka
├── vod_service.py     # Webhooks y limpieza VOD
└── cms_gateway.py      # Integración con la API del CMS

utils/helpers.py     # Filtros Jinja2 y utilidades
scripts/              # Analizador de señal + migraciones
scripts/migrations/   # Migraciones de esquema SQL
templates/ · static/   # Frontend server-rendered (Jinja2)
tests/                 # Suite pytest
docs/                  # Documentación de diseño y decisiones (fechada)
openspec/              # Specs y registro formal de cambios
```

## Tests

```bash
pytest
```

Configuración en `pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`).

## Deploy

```bash
./deploy.sh --test     # Verifica conexión y versión antes de desplegar
./deploy.sh             # Deploy (usa SSH key, sin passwords)
./deploy.sh --health    # Verifica el health endpoint post-deploy
```

## Versionado

```bash
python bump_version.py
```

Actualiza `core/version.py`. Ver historial completo de cambios en [`CHANGELOG.md`](./CHANGELOG.md).

## Documentación adicional

Decisiones de diseño, fases de refactor y specs formales en [`docs/`](./docs) y [`openspec/`](./openspec).
