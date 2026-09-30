# Mgo_Orquestador — Documentación Completa del Proyecto

## Índice

1. [Visión General](#1-visión-general)
2. [Arquitectura](#2-arquitectura)
3. [Prerrequisitos](#3-prerrequisitos)
4. [Instalación](#4-instalación)
5. [Configuración](#5-configuración)
6. [Base de Datos](#6-base-de-datos)
7. [Despliegue](#7-despliegue)
8. [Agentes Encoder](#8-agentes-encoder)
9. [Monitoreo](#9-monitoreo)
10. [Reglas de Alertas](#10-reglas-de-alertas)
11. [API Reference](#11-api-reference)
12. [Desarrollo](#12-desarrollo)
13. [Troubleshooting](#13-troubleshooting)
14. [Changelog](#14-changelog)

---

## 1. Visión General

**Mgo_Orquestador** es el backend en FastAPI que orquesta el pipeline de encoding y streaming en vivo de MundoGo. Gestiona nodos encoder, canales, jobs de FFmpeg/Shaka Packager, DRM/KMS, monitoreo con recovery automático y failover.

### Características principales

- Gestión de nodos, canales y jobs de transcodificación (start/stop/restart/move)
- Generación automática de scripts FFmpeg/Shaka Packager por canal
- Monitoreo continuo con detección de reinicios, drop frames y discontinuidades
- Recovery automático de jobs caídos
- **Sistema de reglas configurable para alertas de plataformas externas**
- Integración DRM/KMS (rotación de llaves, health/stats)
- Failover de señal offline
- Autenticación JWT + RBAC (admin / operator / viewer)
- Health checks y métricas (`/api/health`, `/api/health/ready`, `/api/metrics`)

### Versión actual

- **v2.19.0** (29 Sep 2026)
- Python 3.9+
- FastAPI + SQLAlchemy + MySQL

---

## 2. Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                        MUNDOGO HUB                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Encoder    │    │   Encoder    │    │   Encoder    │      │
│  │   Mac-01     │    │   Mac-02     │    │   Mac-05     │      │
│  │  (172.16.    │    │  (172.16.    │    │  (172.16.    │      │
│  │   223.10)    │    │   223.8)     │    │   222.155)   │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │   ORQUESTADOR   │                          │
│                    │  (172.16.223.5) │                          │
│                    │   FastAPI API   │                          │
│                    │   Monitor       │                          │
│                    └────────┬────────┘                          │
│                             │                                   │
│         ┌───────────────────┼───────────────────┐               │
│         │                   │                   │               │
│  ┌──────▼───────┐    ┌──────▼───────┐    ┌──────▼───────┐      │
│  │   Packager   │    │   Packager   │    │   Packager   │      │
│  │  (Linux)     │    │  (Linux)     │    │  (Linux)     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Origin 1   │    │   Origin 2   │    │   Origin 3   │      │
│  │  (172.16.    │    │  (172.16.    │    │  (172.16.    │      │
│  │   222.246)   │    │   222.248)   │    │   222.250)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  DRM Server  │    │     KMS      │    │    HAProxy   │      │
│  │  (172.16.    │    │  (172.16.    │    │  (172.16.    │      │
│  │   222.240)   │    │   222.240)   │    │   223.240)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Componentes

| Componente | Descripción | Puerto |
|------------|-------------|--------|
| **Orquestador** | API FastAPI + Monitor | 9000 |
| **Encoder Agent (Mac)** | Agent encoder Mac M4 | 8000 |
| **Encoder Agent (Linux)** | Agent encoder Linux | 8000 |
| **Packager** | Shaka Packager | 8000 |
| **Origin** | Servidor de orígenes | - |
| **DRM Server** | Widevine DRM | 8080 |
| **KMS** | Key Management Service | 8000 |
| **HAProxy** | Load balancer | 8002 |

---

## 3. Prerrequisitos

### Servidor Orquestador

- **SO:** Ubuntu 20.04+ / Debian 11+
- **Python:** 3.9+
- **MySQL:** 8.0+
- **RAM:** 4GB mínimo
- **Disco:** 20GB mínimo

### Agentes Encoder (Mac)

- **SO:** macOS 12+ (Monterey)
- **Python:** 3.14+ (Homebrew)
- **FFmpeg:** con soporte VideoToolbox (HEVC/H.264)
- **RAM:** 8GB mínimo
- **Network:** 1Gbps mínimo

### Agentes Encoder (Linux)

- **SO:** Ubuntu 20.04+ / Debian 11+
- **Python:** 3.12+ (venv)
- **FFmpeg:** con soporte libx264/libx265
- **RAM:** 8GB mínimo
- **Network:** 1Gbps mínimo

---

## 4. Instalación

### 4.1 Clonar el repositorio

```bash
git clone git@github.com:eskiconce/Mgo_Orquestador.git
cd Mgo_Orquestador
```

### 4.2 Crear entorno virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4.3 Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4.4 Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con los valores reales del entorno
```

### 4.5 Crear usuario administrador

```bash
python crear_admin.py
```

### 4.6 Ejecutar migraciones de esquema

```bash
python scripts/run_migrations.py
```

### 4.7 Iniciar el servidor (desarrollo)

```bash
uvicorn main:app --reload --port 8000
```

La aplicación queda disponible en `http://localhost:8000`, con login en `/login`.

---

## 5. Configuración

### 5.1 Variables de entorno

Todas se configuran en `.env` (ver `.env.example` como plantilla). **Ninguna debe quedar con el valor de ejemplo en producción.**

| Variable | Descripción | Default |
|---|---|---|
| `SECRET_KEY` | Clave secreta para JWT | - |
| `ALGORITHM` | Algoritmo JWT | HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Minutos de expiración token | 1440 |
| `AGENT_API_KEY` | API key compartida con agentes | - |
| `AGENT_PORT` | Puerto de agentes encoder | 8000 |
| `DRM_HEALTH_PORT` | Puerto health check DRM | 8080 |
| `POLL_INTERVAL` | Intervalo del loop de monitoreo (seg) | 10 |
| `DATABASE_URL` | Cadena de conexión SQLAlchemy | - |
| `KMS_API_URL` | URL del servicio KMS | - |
| `KMS_API_KEY` | API key del KMS | - |
| `CMS_REAL_WEBHOOK` | Webhook real hacia el CMS | - |
| `ORCHESTRATOR_WEBHOOK_URL` | URL interna webhook VOD | - |
| `VOD_API_PORT` | Puerto de la API VOD | 8005 |
| `HAPROXY_NODES` | IPs de nodos HAProxy (separadas por coma) | - |
| `HAPROXY_AGENT_PORT` | Puerto del agente HAProxy | 8002 |
| `OFFLINE_IP` | IP de señal de failover offline | 226.1.2.58 |
| `OFFLINE_PORT` | Puerto de señal offline | 2058 |
| `OFFLINE_PROTO` | Protocolo de señal offline | udp |
| `TELEGRAM_BOT_TOKEN` | Token de bot Telegram (opcional) | - |
| `TELEGRAM_CHAT_ID` | Chat ID de Telegram (opcional) | - |

> **IMPORTANTE:** `SECRET_KEY`, `AGENT_API_KEY`, `KMS_API_KEY` y `DATABASE_URL` deben generarse/rotarse por entorno. No reutilizar los valores de `.env.example`.

### 5.2 Estructura del proyecto

```
Mgo_Orquestador/
├── main.py                    # Punto de entrada — setup + routers
├── database.py                # Configuración SQLAlchemy
├── models.py                  # Modelos SQLAlchemy
├── monitor.py                 # Wrapper legacy → monitor/
├── monitor/                   # Paquete de monitoreo (modularizado)
│   ├── __init__.py            # Orquestación del loop principal
│   ├── alerts.py              # CMS notifications + Telegram
│   ├── checks.py              # TS errors, discontinuity, drop frames
│   ├── commands.py            # send_command, kill_flow_safety
│   ├── health.py              # Node health checks + restart detection
│   └── recovery.py            # Ghost cleanup, node recovery, failover
├── core/
│   ├── config.py              # Configuración centralizada (.env)
│   ├── deps.py                # Auth, roles, templates
│   ├── errors.py              # Esquema de error/success unificado
│   ├── http_client.py         # Factory httpx sync/async
│   ├── logging_service.py     # Logging a archivo/BD
│   ├── rate_limit.py          # Rate limiting por IP
│   └── version.py             # Versionado del proyecto
├── routers/                   # Un router por dominio
│   ├── auth.py                # Autenticación
│   ├── users.py               # Gestión de usuarios
│   ├── dashboard.py           # Dashboard principal
│   ├── nodes.py               # Gestión de nodos
│   ├── channels.py            # Gestión de canales
│   ├── processes.py           # Gestión de procesos
│   ├── drm.py                 # DRM/KMS
│   ├── orchestrator.py        # Orquestación de jobs
│   ├── internal.py            # Endpoints internos
│   ├── ui_logs.py             # Logs UI
│   ├── health.py              # Health checks y métricas
│   └── alert_rules.py         # CRUD reglas de alertas
├── services/
│   ├── builders.py            # Generadores de scripts FFmpeg/Shaka
│   ├── vod_service.py         # Webhooks y limpieza VOD
│   ├── cms_gateway.py         # Integración con CMS
│   ├── alert_normalizer.py    # Normalización de alertas externas
│   └── alert_rule_engine.py   # Motor de reglas de alertas
├── utils/
│   └── helpers.py             # Filtros Jinja2 y utilidades
├── scripts/
│   ├── run_migrations.py      # Sistema de migraciones
│   └── migrations/            # Archivos SQL de migración
│       ├── 001_*.sql          # Migración uptime tracking
│       └── 002_*.sql          # Migración alert rules
├── templates/                 # Frontend server-rendered (Jinja2)
├── static/                    # Archivos estáticos
├── tests/                     # Suite pytest
├── docs/                      # Documentación de diseño
├── openspec/                  # Specs y registro de cambios
├── deploy.sh                  # Script de despliegue
├── bump_version.py            # CLI para bump de versión
├── crear_admin.py             # CLI para crear admin
├── crear_usuario.py           # CLI para crear usuario
├── requirements.txt           # Dependencias Python
├── pyproject.toml             # Configuración pytest
├── .env.example               # Plantilla de variables
├── .gitignore                 # Archivos ignorados por git
├── README.md                  # Documentación principal
├── INSTALLATION_GUIDE.md      # Esta guía
└── CHANGELOG.md               # Historial de versiones
```

### 5.3 Parámetros Generales (UI)

`/ui/settings` (admin) permite editar sin deploy:

- **Seguridad:** API-key global (`app_settings.security.api_key`) — BD es fuente única con fallback al default de `core/config.py`.
- **Telegram:** `enabled`, `bot_token`, `chat_id` — controla `notify_telegram`.
- **Correo:** `enabled` + modo `auth_mode` (`smtp` con host/puerto/TLS/usuario/contraseña, o `graph` con tenant/client/secret de Microsoft 365) + remitente/destinatarios. Botón "Probar envío" valida la conexión real (el envío automático en alertas llegará en una mejora futura).
- **CMS:** `enabled` + `webhook_url` — controla `notify_cms_channel_status`.
- **Fuentes de alertas:** CRUD con token por fuente; endpoint genérico `POST /api/fuentes/{slug}/alertas` (payload `num_canal/fecha/hora/status`, header `x-api-key`). Los endpoints dedicados tsmonitor/packager no usan token.

---

## 6. Base de Datos

### 6.1 Crear base de datos

```sql
CREATE DATABASE encoder_orchestrator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ingservice'@'localhost' IDENTIFIED BY 'TU_PASSWORD_SEGURO';
GRANT ALL PRIVILEGES ON encoder_orchestrator.* TO 'ingservice'@'localhost';
FLUSH PRIVILEGES;
```

### 6.2 Ejecutar migraciones

```bash
# Ver estado de migraciones
python scripts/run_migrations.py --status

# Ejecutar migraciones pendientes
python scripts/run_migrations.py
```

### 6.3 Tablas principales

| Tabla | Descripción |
|-------|-------------|
| `users` | Usuarios de la plataforma |
| `nodos` | Nodos encoder/packager |
| `channels` | Canales de transmisión |
| `encoding_jobs` | Jobs de encoding/packaging |
| `monitor_logs` | Logs del monitor |
| `signal_analyses` | Historial de análisis de señal |
| `encoder_health` | Health de encoders |
| `alert_rules` | Reglas de alertas configurables |
| `schema_migrations` | Tracking de migraciones |
| `app_settings` | Parámetros de plataforma (telegram, email, cms, security) |
| `alert_sources` | Fuentes externas de alerta con token |

---

## 7. Despliegue

### 7.1 Despliegue manual

```bash
# Subir archivos al servidor
scp -i ~/.ssh/id_opencode archivo oymservice@SERVIDOR:/tmp/

# Copiar a ubicación de producción
ssh -i ~/.ssh/id_opencode oymservice@SERVIDOR "echo 'PASSWORD' | sudo -S cp /tmp/archivo /opt/encoder-orchestrator/archivo"

# Reiniciar servicios
ssh -i ~/.ssh/id_opencode oymservice@SERVIDOR "echo 'PASSWORD' | sudo -S systemctl restart encoder-api.service encoder-monitor.service"
```

### 7.2 Despliegue con deploy.sh

```bash
# Verificar conexión y versión
./deploy.sh --test

# Desplegar
./deploy.sh

# Verificar health post-deploy
./deploy.sh --health
```

### 7.3 Verificar despliegue

```bash
curl -s http://SERVIDOR:9000/api/health | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```

---

## 8. Agentes Encoder

### 8.1 Agentes Mac (Mac-01, Mac-02, Mac-05)

**Ubicación:** `/Users/soporte/encoder-agent/`

**Archivos principales:**
- `main.py` — API FastAPI del agente
- `process_manager.py` — Gestión de procesos FFmpeg
- `scripts/signal_analyzer.py` — Analizador de señal

**Servicio:** launchd (`com.mundogo.encoderagent.plist`)

**Comandos:**
```bash
# Ver estado
launchctl list | grep encoder

# Detener
launchctl unload ~/Library/LaunchAgents/com.mundogo.encoderagent.plist

# Iniciar
launchctl load ~/Library/LaunchAgents/com.mundogo.encoderagent.plist

# Verificar health
curl -s -H 'x-api-key: API_KEY' http://127.0.0.1:8000/health
```

**Deploy:**
```bash
sshpass -p 'PASSWORD' scp -o StrictHostKeyChecking=no archivo.soporte@IP:/Users/soporte/encoder-agent/
sshpass -p 'PASSWORD' ssh -o StrictHostKeyChecking=no soporte@IP "launchctl unload ~/Library/LaunchAgents/com.mundogo.encoderagent.plist && sleep 2 && launchctl load ~/Library/LaunchAgents/com.mundogo.encoderagent.plist"
```

### 8.2 Agentes Linux (encoder_02, encoder_03)

**Ubicación:** `/opt/api/`

**Archivos principales:**
- `main.py` — API FastAPI del agente
- `scripts/signal_analyzer.py` — Analizador de señal

**Servicio:** systemd (`api-encoder.service`)

**Comandos:**
```bash
# Ver estado
systemctl status api-encoder.service

# Reiniciar
echo 'PASSWORD' | sudo -S systemctl restart api-encoder.service

# Ver logs
journalctl -u api-encoder.service -f

# Verificar health
curl -s -H 'x-api-key: API_KEY' http://127.0.0.1:8000/health
```

**Deploy:**
```bash
scp -i ~/.ssh/id_opencode archivo oymservice@IP:/opt/api/
ssh -i ~/.ssh/id_opencode oymservice@IP "echo 'PASSWORD' | sudo -S systemctl restart api-encoder.service"
```

### 8.3 Endpoints de agentes

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Estado del sistema |
| `/jobs/create` | POST | Crear y ejecutar job |
| `/jobs/control` | POST | start/stop/restart |
| `/jobs/status` | GET | Estado de todos los jobs |
| `/jobs/logs` | GET | Leer logs de un job |
| `/jobs/delete` | DELETE | Eliminar job y archivos |
| `/encoder/build` | POST | Generar script FFmpeg (solo Mac) |
| `/encoder/analyze` | POST | Análisis de señal (background) |
| `/processes/metrics` | GET | Métricas CPU/RAM (solo Mac) |
| `/processes/{name}/restart` | POST | Reiniciar proceso (solo Mac) |
| `/processes/{name}/info` | GET | Info de proceso (solo Mac) |

---

## 9. Monitoreo

### 9.1 Loop de monitoreo

El monitor ejecuta un loop cada `POLL_INTERVAL` segundos (default: 10s):

1. **Health check** — Verifica conectividad de cada nodo
2. **Sync de procesos** — Sincroniza estado de jobs con agentes
3. **Detección de reinicios** — Compara uptime para detectar reinicios
4. **Recovery** — Relanza jobs caídos automáticamente
5. **Drop frames** — Monitorea caída de frames
6. **Discontinuity** — Detecta errores de timestamp

### 9.2 Eventos del monitor

| Evento | Descripción |
|--------|-------------|
| `NODE_UP` | Nodo vuelve a estar online |
| `NODE_DOWN` | Nodo cae offline |
| `NODE_RECOVERY` | Jobs relanzados tras recovery |
| `GHOST_CLEANUP` | Procesos fantasma limpiados |
| `PROCESS_SYNCED` | Proceso sincronizado con agente |
| `PROCESS_CRASHED` | Proceso cayó a estado error |
| `PROCESS_START_FAIL` | Fallo al iniciar proceso |
| `AUTO_START` | Inicio automático de proceso |
| `AUTO_RESYNC` | Re-sincronización automática |
| `AUTO_KILL` | Detención automática de proceso inestable |
| `FAILOVER_ACTIVATED` | Failover activado |
| `FAILOVER_RESTORED` | Failover restaurado |
| `TIMESTAMP_DISCONTINUITY` | Errores de discontinuity |
| `DROP_FRAMES` | Caída de frames detectada |
| `ENCODER_RESTART_RECOVERY` | Recovery post-reinicio de encoder |
| `ZOMBIE_DETECTED` | Proceso zombie detectado |

### 9.3 Logs

- **Monitor:** `/opt/encoder-orchestrator/logs/monitor.log`
- **API:** `journalctl -u encoder-api.service`
- **Agentes Mac:** `/Users/soporte/encoder-agent/logs/encoder-agent.log`
- **Agentes Linux:** `journalctl -u api-encoder.service`

---

## 10. Reglas de Alertas

### 10.1 Descripción

El sistema de reglas permite configurar qué acción ejecutar al recibir alertas de plataformas externas (tsmonitor, packager, encoder, etc.).

### 10.2 Acciones disponibles

| Acción | Descripción |
|--------|-------------|
| `stop_encoder` | Detiene el encoder del canal |
| `start_encoder` | Inicia el encoder del canal |
| `restart_encoder` | Reinicia el encoder del canal |
| `notify_only` | Solo registra log y notifica |
| `failover` | Activa failover a señal de respaldo |

### 10.3 Prioridad de búsqueda

1. **Regla específica** — source + channel_id + alert_type
2. **Regla global source** — source + channel_id=NULL + alert_type
3. **Regla global total** — source=NULL + channel_id=NULL + alert_type
4. **Comportamiento default** — hardcodeado

### 10.4 Gestión de reglas

**UI:** `https://admin.mundogo.cl/ui/alert-rules`

**API:**

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/alert-rules` | GET | Listar reglas |
| `/api/alert-rules` | POST | Crear regla |
| `/api/alert-rules/{id}` | PUT | Actualizar regla |
| `/api/alert-rules/{id}` | DELETE | Eliminar regla |
| `/api/alert-rules/{id}/toggle` | POST | Habilitar/deshabilitar |

### 10.5 Migración

```bash
# Ejecutar migración de alert rules
python scripts/run_migrations.py
```

---

## 11. API Reference

### 11.1 Health endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/health` | GET | Health check completo |
| `/api/health/ready` | GET | Readiness probe |
| `/api/metrics` | GET | Métricas detalladas |

### 11.2 Autenticación

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/login` | POST | Login de usuario |
| `/ui/users` | GET | Listado de usuarios |
| `/ui/users/save` | POST | Crear/editar usuario |
| `/ui/users/delete/{id}` | GET | Eliminar usuario |

### 11.3 Nodos

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/ui/nodes` | GET | Listado de nodos |
| `/ui/nodes/new` | GET | Formulario nuevo nodo |
| `/ui/nodes/edit/{id}` | GET | Formulario editar nodo |

### 11.4 Canales

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/ui/channels` | GET | Listado de canales |
| `/ui/channels/new` | GET | Formulario nuevo canal |
| `/ui/channels/edit/{id}` | GET | Formulario editar canal |

### 11.5 Procesos

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/ui/processes` | GET | Listado de procesos |
| `/orchestrator/start-job/{id}` | POST | Iniciar job |
| `/orchestrator/stop-job/{id}` | POST | Detener job |
| `/orchestrator/restart-job/{id}` | POST | Reiniciar job |

### 11.6 Alertas externas

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/alertas/tsmonitor` | POST | Recibir alerta TSMonitor |
| `/api/alertas/packager` | POST | Recibir alerta Packager |

### 11.7 Endpoints internos

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/internal/analyze-callback` | POST | Callback de análisis |
| `/api/internal/analyze-status/{task_id}` | GET | Estado de análisis |
| `/api/internal/trigger-failover/{channel_id}` | POST | Activar/desactivar failover |
| `/api/internal/encoder-restart` | POST | Notificación de reinicio |

---

## 12. Desarrollo

### 12.1 Ejecutar tests

```bash
pytest
```

### 12.2 Bump de versión

```bash
python bump_version.py
```

### 12.3 Branches

- `main` — Rama de producción
- No se usan feature branches (deploy directo a main)

### 12.4 Convenciones

- **Versionado:** SemVer (MAJOR.MINOR.PATCH)
- **Commits:** Convención de conventional commits
- **Tests:** pytest con cobertura mínima
- **Linting:** py_compile para verificar sintaxis

---

## 13. Troubleshooting

### 13.1 Error 429 "Demasiadas solicitudes"

**Causa:** Rate limit excedido (300 req/min por IP)

**Solución:** Los endpoints `/ui/`, `/api/internal/`, `/api/health` están excluidos. Si persiste, verificar que el servicio fue reiniciado con la última versión.

### 13.2 Error "name 'datetime' is not defined"

**Causa:** Import faltante en `monitor/__init__.py`

**Solución:** Verificar que `from datetime import datetime` esté en las imports de `monitor/__init__.py`

### 13.3 Monitor no inicia

**Causa:** Error en imports o conexión a BD

**Solución:**
```bash
# Ver logs
journalctl -u encoder-monitor.service -f

# Verificar conexión a BD
python3 -c "from database import verify_db_connection; verify_db_connection()"
```

### 13.4 Jobs quedan en "error"

**Causa:** Agente no responde o proceso cayó

**Solución:**
```bash
# Verificar agente
curl -s -H 'x-api-key: API_KEY' http://IP_NODO:8000/health

# Reiniciar agente
sshpass -p 'PASSWORD' ssh soporte@IP_NODO "launchctl unload ~/Library/LaunchAgents/com.mundogo.encoderagent.plist && launchctl load ~/Library/LaunchAgents/com.mundogo.encoderagent.plist"
```

### 13.5 Error "connection refused" en monitor

**Causa:** Agente no está corriendo

**Solución:**
```bash
# Verificar proceso
ps aux | grep uvicorn

# Reiniciar agente
# Mac: launchctl unload/load
# Linux: systemctl restart api-encoder.service
```

---

## 14. Changelog

### v2.18.1 (29 Sep 2026)
- Fix: navegación "Reglas Alertas" en base.html
- Fix: import Request en alert_rules.py

### v2.18.0 (29 Sep 2026)
- Nuevo: sistema de reglas configurable para alertas externas
- Nuevo: modelo AlertRule con tabla alert_rules
- Nuevo: normalizador multi-plataforma
- Nuevo: motor de reglas con cooldown
- Nuevo: CRUD de reglas (API + UI)

### v2.17.2 (26 Sep 2026)
- Fix: import faltante de `datetime` en `monitor/__init__.py`
- Fix: rate limit aumentado de 60 a 300 requests/min
- Fix: endpoints UI excluidos del rate limit

### v2.17.1 (26 Sep 2026)
- Eliminado: `estructura.txt`, `structura.txt`, `add_uptime_tracking_columns.py`
- Docs: README.md incluye sección de migraciones

### v2.17.0 (26 Sep 2026)
- Fix: `database.py` falla explícitamente si DB no conecta
- Nuevo: `scripts/run_migrations.py` para migraciones de esquema
- Nuevo: `monitor/` paquete modularizado (6 módulos)
- Nuevo: `README.md` con documentación completa

---

## Información de Contacto

- **GitHub:** https://github.com/eskiconce/Mgo_Orquestador
- **Issues:** https://github.com/eskiconce/Mgo_Orquestador/issues
