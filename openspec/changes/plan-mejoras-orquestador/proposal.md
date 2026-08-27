## Why

El orquestador MundoGo (v2.8.6) ha crecido orgánicamente desde un monitoreo simple hasta una plataforma completa de orquestación de encodeo, DRM, VOD y CMS. La deuda técnica acumulada dificulta mantenimiento, despliegue y evolución. Este proposal documenta el estado actual completo y define un plan de mejoras priorizado por impacto/esfuerzo.

---

## Estado Actual del Proyecto

### Arquitectura

```
Mgo_Orquestador/
├── main.py                 # FastAPI app + 30+ rutas UI/API (1088 líneas)
├── monitor.py              # Monitor multihread + recovery + failover (1114 líneas)
├── database.py             # SQLAlchemy engine + session factory
├── models.py               # 8 modelos: Node, Channel, EncodingJob, EncoderHealth,
│                           #   ChannelAlert, MonitorEvent, User, UserRole
├── core/
│   ├── config.py           # Constantes hardcodeadas (API_KEY, URLs, puertos)
│   ├── version.py          # Versionado manual v2.8.6
│   └── logging_service.py  # Interceptor de logs a BD
├── services/
│   ├── builders.py         # Generadores de scripts FFmpeg/Shaka (754 líneas)
│   ├── vod_service.py      # Webhooks VOD + tsmonitor handler (562 líneas)
│   └── cms_gateway.py      # Proxy inverso al CMS (245 líneas)
├── utils/
│   └── helpers.py          # Filtros Jinja2 + utilidades
├── scripts/
│   └── signal_analyzer.py  # Analizador de señal async con callback (1001 líneas)
├── templates/              # 23 archivos HTML (Jinja2)
├── static/                 # CSS, JS, logo.png
├── docs/                   # 14 documentos de diseño/cambios
├── openspec/               # Specs y cambios OpenSpec
├── crear_usuario.py        # CLI para crear usuarios
├── crear_admin.py          # CLI para crear admin
├── bump_version.py         # CLI para bump de versión
├── deploy.sh               # Script de deploy manual
├── deploy.exp              # Expect script de deploy
└── deploy_file.exp         # Expect script de deploy por archivo
```

### Componentes del Sistema

| Componente | Archivo | Líneas | Responsabilidad |
|-----------|---------|--------|-----------------|
| **API/Web UI** | `main.py` | 1088 | 30+ rutas: CRUD canales, encoders, packagers, nodos, DRM, VOD, auth, proxy |
| **Monitor** | `monitor.py` | 1114 | Sync loop multihread, NODE_UP/DOWN recovery, failover, health checks |
| **Builders** | `services/builders.py` | 754 | Genera scripts bash para encoders Linux/Mac y packagers |
| **VOD Service** | `services/vod_service.py` | 562 | Webhooks CMS, tsmonitor handler, borrado VOD |
| **CMS Gateway** | `services/cms_gateway.py` | 245 | Proxy inverso a CMS con API key |
| **Signal Analyzer** | `scripts/signal_analyzer.py` | 1001 | Análisis async de señal multicast con NUMA binding |
| **Models** | `models.py` | ~200 | 8 tablas SQLAlchemy |
| **Database** | `database.py` | ~30 | Engine SQLite + session factory |

### Infraestructura

| Servidor | IP | Servicios |
|----------|-----|-----------|
| Orquestador | 172.16.223.5 | encoder-api (FastAPI :9000), encoder-monitor |
| Mac-02 | 172.16.223.8 | encoder-agent (:8000) |
| Mac-01 | 172.16.223.10 | encoder-agent (:8000) |
| Linux-01 | 172.16.222.233 | api-agent (:8000) |
| Linux-02 | 172.16.222.235 | api-agent (:8000) |
| Origins | 172.16.222.246/248/250/252 | api-vod (:8005), HLS/DASH |
| DRM | (nodos BD) | Widevine license server (:8080) |

### Dependencias Python

- FastAPI + Uvicorn
- SQLAlchemy (SQLite)
- httpx (cliente HTTP async/sync)
- Jinja2 (templates)
- python-multipart (formularios)
- bcrypt (auth)
- PyJWT (tokens)

---

## Problemas Identificados

### Críticos

1. **Módulos "god"**: `main.py` (1088L) y `monitor.py` (1114L) concentran toda la lógica. Difícil de testear, mantener y depurar.

2. **Configuración dispersa**: API keys, URLs y puertos hardcodeados en `core/config.py` + valores duplicados en `main.py` y `monitor.py`. Sin `.env`, sin validación.

3. **Cliente HTTP inconsistente**: Mezcla de `httpx.Client()`, `httpx.AsyncClient()`, clientes creados por request, y pools configurados diferente por archivo.

4. **Sin tests**: Cero automatización de testing. Los escenarios de recovery y failover se verifican manualmente.

5. **Archivos de deploy manuales**: `deploy.sh`, `deploy.exp`, `deploy_file.exp` — scripts expect frágiles.

### Moderados

6. **Logging desconectado**: `logging_service.py` escribe a BD pero el monitor usa `logging` estándar a archivo. Sin correlación de eventos.

7. **Error handling inconsistente**: Algunos endpoints devuelven HTML, otros JSON, otros 200 con error en body. Sin esquema de errores unificado.

8. **Auth incompleta**: Endpoints internos (`trigger-failover`, `analyze-callback`, `vod-webhook`) sin protección.

9. **Código muerto**: Archivos `.V1.py` (ya eliminados), bloques comentados en `monitor.py`, imports sin usar.

10. **Versionado manual**: `core/version.py` se edita a mano, sin semver automático.

### Menores

11. **Templates sin CSS framework**: HTML inline, sin componentes reutilizables.
12. **Sin migraciones de BD**: Cambios de schema se hacen manualmente.
13. **scripts/signal_analyzer.py monolítico**: 1001 líneas, mezcla CLI con lógica de análisis.

---

## Plan de Mejoras — Priorizado

### Fase 1: Fundación (Alto impacto, bajo riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 1.1 | **Config centralizada con .env** | 2h | Alto | `core/config.py`, `.env.example` |
| 1.2 | **requirements.txt** | 30min | Alto | `requirements.txt` |
| 1.3 | **Limpieza de código muerto** | 1h | Medio | `monitor.py`, `main.py` |
| 1.4 | **Cliente HTTP unificado** | 3h | Alto | `core/http_client.py`, todos los archivos |

### Fase 2: Modularización (Alto impacto, medio riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 2.1 | **Split main.py en routers** | 6h | Alto | `routers/*.py`, `main.py` |
| 2.2 | **Split monitor.py en checks** | 4h | Alto | `monitor/checks/*.py`, `monitor.py` |
| 2.3 | **Services como clases** | 3h | Medio | `services/*.py` |

### Fase 3: Observabilidad (Medio impacto, bajo riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 3.1 | **Health endpoint propio** | 1h | Alto | `routers/health.py` |
| 3.2 | **Logging estructurado** | 2h | Medio | `core/logging_service.py` |
| 3.3 | **Métricas básicas** | 2h | Medio | `core/metrics.py` |

### Fase 4: Testing (Alto impacto, bajo riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 4.1 | **pytest + fixtures** | 2h | Alto | `tests/conftest.py`, `pytest.ini` |
| 4.2 | **Tests de recovery/failover** | 4h | Alto | `tests/test_monitor.py` |
| 4.3 | **Tests de API** | 3h | Alto | `tests/test_api.py` |

### Fase 5: Seguridad (Medio impacto, bajo riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 5.1 | **Auth en endpoints internos** | 2h | Alto | `main.py` |
| 5.2 | **Error schema unificado** | 1h | Medio | `core/errors.py` |
| 5.3 | **Rate limiting** | 1h | Bajo | `main.py` |

### Fase 6: Deploy (Medio impacto, medio riesgo)

| # | Mejora | Esfuerzo | Impacto | Archivos |
|---|--------|----------|---------|----------|
| 6.1 | **Eliminar scripts expect** | 30min | Medio | `deploy.exp`, `deploy_file.exp` |
| 6.2 | **Deploy con rsync/scp directo** | 1h | Medio | `deploy.sh` |
| 6.3 | **Health check post-deploy** | 1h | Medio | `deploy.sh` |

---

## Workflow de Cambios (válido desde ahora)

```
1. openspec new change <nombre>
2. Desarrollar + testear localmente
3. Actualizar CHANGELOG.md + core/version.py
4. git add + commit + push a GitHub (fuente principal)
5. Deploy al servidor (solo código, no docs)
6. Verificar en producción
7. openspec archive <nombre>
```

**Regla**: GitHub es la fuente de verdad. La carpeta local es respaldo. Cada cambio se registra en OpenSpec, se documenta en CHANGELOG, y se despliega al servidor.

---

## Impacto

- **Código**: Todos los archivos Python del proyecto
- **Despliegue**: systemd units, nginx, requirements.txt
- **Servidores**: Solo orquestador (172.16.223.5) — sin cambios en agentes ni origins
- **Riesgo**: Bajo-Medio por fases incrementales
- **Timeline estimado**: 2-3 sesiones de trabajo

## Capabilities

### New Capabilities
- `orchestrator/modular-architecture`: División en routers/checks por dominio
- `orchestrator/config-management`: Centralización con .env y validación
- `orchestrator/observability`: Health endpoint, logging estructurado, métricas
- `orchestrator/testing`: Framework pytest con tests de recovery y API
- `orchestrator/http-client`: Cliente HTTP unificado con pool compartido

### Modified Capabilities
- `monitoring/channel-recovery`: Tests automatizados para los escenarios de la spec existente
- `orchestrator/deploy`: Deploy simplificado sin scripts expect
