# HLD — MundoGo Platform: Orquestador como Hub Central

**Fecha:** 30 Aug 2026  
**Versión:** 1.0  
**Autor:** Generado por OpenCode (análisis automático)

---

## 1. Resumen Ejecutivo

El orquestador actual (`Mgo_Orquestador`) gestiona encoders y packagers. La plataforma completa incluye DRM (Widevine), KMS, origins (CDN), HAProxy, TsMonitor, y ecosistema VoIP. Este HLD define la arquitectura para convertir el orquestador en el **hub central** que gestione, monitoree y orqueste todos los procesos de la plataforma.

---

## 2. Stack Tecnológico de Cada Componente

| Componente | Stack | Puerto | Servidor(es) |
|------------|-------|--------|--------------|
| **Orquestador** | Python FastAPI + MySQL + Jinja2 | 9000 | 172.16.223.5 |
| **Agent Mac** | Python FastAPI + ProcessManager | 8000 | 172.16.223.8/10, 192.168.8.33 |
| **Agent Linux** | Python FastAPI + systemd | 8000 | 172.16.222.233/235 |
| **Api_Origins** | Python FastAPI + systemd | 8000 | 172.16.222.246/248/250 |
| **Widevine Server** | Java 11 + Redis + MySQL | 8080 | 172.16.222.241 |
| **Mgo_ApiKMS** | Python FastAPI + Redis + MySQL | 8000 | 172.16.222.240 |
| **TsMonitor** | Python Flask + SQLite/MySQL + InfluxDB | 5000 | (verificar) |
| **HAProxy** | HAProxy + custom agent | 8002 | 172.16.223.240/242/244/246 |
| **CMS** | Externo (core-dev.mundogo.cl) | 443 | Externo |

---

## 3. Arquitectura Actual

```
┌─────────────────────────────────────────────────────┐
│              CMS (core-dev.mundogo.cl)              │
│         Webhooks VOD + Channel Status               │
└───────────────────────┬─────────────────────────────┘
                        │ HTTPS
┌───────────────────────▼─────────────────────────────┐
│              ORQUESTADOR (172.16.223.5:9000)         │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ │
│  │Routers   │ │Monitor   │ │Services│ │Builders  │ │
│  │(12 APIs) │ │(10s poll)│ │VOD/CMS │ │FFmpeg/   │ │
│  │          │ │          │ │        │ │Shaka     │ │
│  └────┬─────┘ └────┬─────┘ └────┬───┘ └────┬─────┘ │
└───────┼─────────────┼────────────┼──────────┼───────┘
        │             │            │          │
   ┌────┴────┐   ┌────┴────┐  ┌───┴───┐  ┌───┴───┐
   │ HTTP    │   │ HTTP    │  │ MySQL │  │ Redis │
   │ agents  │   │ DRM/KMS │  │       │  │       │
   └────┬────┘   └────┬────┘  └───────┘  └───────┘
        │             │
   ┌────▼────┐   ┌────▼───────────────────────────┐
   │ Agents  │   │ DRM Stack (servidores separados)│
   │ Mac/Linux│  │ ┌───────────┐   ┌───────────┐  │
   │ Origins │   │ │ Widevine  │   │ ApiKMS    │  │
   └─────────┘   │ │ .241:8080 │   │ .240:8000 │  │
                 │ └───────────┘   └───────────┘  │
                 └────────────────────────────────┘
```

### 3.1 Lo que YA está integrado

| Componente | Integración | Estado |
|------------|-------------|--------|
| Encoders (Mac) | API directa (health/create/control/status/delete) | ✅ Completo |
| Encoders (Linux) | API directa (health/create/control/status/delete) | ✅ Completo |
| Packagers (Origins) | API directa (health/create/control/status/delete) | ✅ Completo |
| HAProxy | `sync_haproxy_map()` + `HAPROXY_NODES` config | ⚠️ Parcial |
| DRM Health | Polling `/health` + `/stats` cada 30s en monitor | ⚠️ Parcial |
| DRM Users | Dashboard de usuarios VIP via proxy a KMS | ⚠️ Parcial |
| KMS | Proxy `/api/kms-proxy/{path}` → KMS API | ⚠️ Parcial |
| CMS | Webhooks VOD + channel status notifications | ✅ Completo |
| TsMonitor | Remote logs via `/api/internal/remote-logs` | ⚠️ Parcial |

### 3.2 Lo que FALTA integrar

| Componente | Gap | Impacto |
|------------|-----|---------|
| DRM HA | Sin configuración active-standby | Alto |
| DRM 500k | Sin connection pooling ni escalabilidad | Alto |
| KMS HA | Sin configuración active-standby | Alto |
| KMS 500k | Sin connection pooling ni escalabilidad | Alto |
| Origins Health | Solo envía scripts, no monitorea salud | Medio |
| Origins Failover | Sin failover automático primario→backup | Medio |
| HAProxy Dashboard | Solo sync de mapa, sin métricas | Medio |
| HAProxy Backend Health | Sin monitoreo de salud de backends | Medio |
| TsMonitor Dashboard | Solo logs remotos, sin vista integrada | Bajo |
| Monitoreo Red | No existe | Bajo |

---

## 4. Arquitectura Objetivo

```
┌────────────────────────────────────────────────────────────────┐
│                    ORQUESTADOR (Hub Central)                    │
│                    172.16.223.5:9000                            │
│                                                                │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐ │
│  │  Routers    │  │   Monitor   │  │      Services          │ │
│  │  (12 APIs)  │  │  (10s poll) │  │  CMS / VOD / Builders  │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬────────────┘ │
│         │                │                      │              │
│  ┌──────▼────────────────▼──────────────────────▼────────────┐ │
│  │              Core Layer (FastAPI + SQLAlchemy)             │ │
│  │  config │ deps │ http_client │ errors │ rate_limit │ log  │ │
│  └──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┘ │
└─────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼────────┘
      │      │      │      │      │      │      │      │
      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
┌─────────┐┌────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌────────┐
│Encoders ││Pack││DRM  ││KMS  ││Origin││HAPro││TsMon││  CMS   │
│Mac/Linux││ager││WV   ││     ││(CDN) ││xy   ││itor ││External│
│5 nodes  ││3nods││1node││1node││3nodes││4node││     ││        │
└─────────┘└────┘└─────┘└─────┘└─────┘└─────┘└─────┘└────────┘
```

---

## 5. Flujo de Datos por Componente

### 5.1 Flujo Encoder → Packager (Live)

```
1. Frontend → POST /orchestrator/channels/{id}/start
2. Orquestador → POST /jobs/create al Encoder (FFmpeg script)
3. Orquestador → POST /jobs/create al Packager (Shaka script)
4. Monitor polla /jobs/status cada 10s
5. Si Encoder falla → trigger-failover → Packager usa señal offline
6. Si Encoder recupera → restore → Packager vuelve al stream normal
```

### 5.2 Flujo DRM (License)

```
1. Player → POST /wv/license al Widevine Server
2. Widevine → Redis: consultar content key
3. Widevine → MySQL: verificar límites de pantalla
4. Widevine → Redis: actualizar concurrencia
5. Monitor polla /health cada 10s + /stats cada 30s
6. Si Widevine cae → nodo marcado offline → alerta CMS
```

### 5.3 Flujo KMS (Key Management)

```
1. Orquestador → POST /kms/generate (al iniciar canal DRM)
2. KMS → MySQL: crear content key
3. KMS → Redis: cachear key
4. Widevine lee de MySQL/Redis → sirve licencias
5. Rotación: POST /api/keys/rotate → nueva key → widevine usa nueva
```

### 5.4 Flujo VOD (Recording)

```
1. CMS → POST /api/internal/vod-webhook (solicitud de grabación)
2. Orquestador → POST /jobs/create al Origin (grabación)
3. Origin graba → notifica completado
4. Orquestador → POST cleanup → limpia archivos temporales
5. Sync HAProxy map
```

### 5.5 Flujo HAProxy (Routing)

```
1. Al iniciar/parar Packager → sync_haproxy_map()
2. Genera mapa: {canal} → {backend_ip:port}
3. POST a todos los HAPROXY_NODES (4 servidores)
4. HAProxy actualiza routing en tiempo real
```

---

## 6. Modelo de Datos (Tablas Existentes)

### 6.1 encoder_orchestrator (MySQL)

| Tabla | Registros | Propósito |
|-------|-----------|-----------|
| `channels` | ~50 | Canales streaming (IP multicast, puertos, DRM flag) |
| `nodos` | ~15 | Nodos (encoder/packager/DRM/HAProxy, IP, status, métricas) |
| `encoding_jobs` | ~100 | Jobs activos (canal + nodo, status, command) |
| `encoder_health` | ~10k | Historial de salud encoders |
| `users` | ~10 | Usuarios plataforma (admin/operator/viewer) |
| `recordings` | ~200 | Grabaciones VOD |
| `system_logs` | ~10k | Logs del sistema |
| `monitor_logs` | ~50k | Eventos del monitor |
| `packager_logs` | ~10k | Logs de packager |

### 6.2 drm_system (MySQL en 172.16.222.241 — DRM Server)

| Tabla | Propósito |
|-------|-----------|
| `content_keys` | Keys de contenido (kid, content_key, channel_id) |
| `vip_users` | Usuarios VIP (user_id, username, max_screens, status) |
| `license_activity` | Historial de licencias (user_id, kid, action, ip) |

### 6.3 Redis (172.16.222.241 — DRM Server)

| Key Pattern | TTL | Propósito |
|-------------|-----|-----------|
| `drm:key:<kidHex>` | 6h | Cache de content keys |
| `drm:limite:<userId>` | 1h | Cache de límites |
| `drm:concurrencia:<userId>` | 24h | Dispositivos activos |

---

## 7. APIs Existentes por Componente

### 7.1 Orquestador → Agents (HTTP, puerto 8000)

| Endpoint | Método | Auth | Uso |
|----------|--------|------|-----|
| `/health` | GET | No | CPU, RAM, GPU, uptime |
| `/jobs/create` | POST | X-API-Key | Crear job (script comprimido) |
| `/jobs/control` | POST | X-API-Key | Start/stop/restart |
| `/jobs/status` | GET | No | Lista de procesos |
| `/jobs/logs` | GET | No | Logs de un proceso |
| `/jobs/delete` | DELETE | X-API-Key | Eliminar job |
| `/encoder/analyze` | POST | X-API-Key (Mac) | Análisis de señal |
| `/encoder/build` | POST | X-API-Key (Mac) | Build FFmpeg script |

### 7.2 Orquestador → DRM (172.16.222.241)

| Endpoint | Método | Puerto | Uso |
|----------|--------|--------|-----|
| `172.16.222.241:8080/health` | GET | 8080 | Health check DRM |
| `172.16.222.241:8080/stats` | GET | 8080 | Stats DRM (users/devices) |
| `172.16.222.241:8080/stats/user/{id}` | GET | 8080 | Stats por usuario |

### 7.3 Orquestador → KMS (172.16.222.240)

| Endpoint | Método | Puerto | Uso |
|----------|--------|--------|-----|
| `172.16.222.240:8000/kms/generate` | POST | 8000 | Generar content key |
| `172.16.222.240:8000/api/keys/rotate` | POST | 8000 | Rotar key |
| `172.16.222.240:8000/api/keys` | GET | 8000 | Listar keys |
| `172.16.222.240:8000/api/vip/users` | GET | 8000 | Listar usuarios VIP |

### 7.4 Orquestador → HAProxy

| Endpoint | Método | Puerto | Uso |
|----------|--------|--------|-----|
| `{haproxy_ip}:8002/update-map` | POST | 8002 | Actualizar mapa de rutas |

### 7.5 CMS → Orquestador

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/api/internal/vod-webhook` | POST | Solicitud de grabación VOD |
| `/api/internal/encoder-restart` | POST | Notificación de reinicio (Issue #2) |

---

## 8. Gap Analysis

### 8.1 DRM (172.16.222.241)

| Aspecto | Actual | Objetivo | Gap |
|---------|--------|----------|-----|
| Health monitoring | ✅ Polling cada 10s | ✅ | Mínimo |
| Stats monitoring | ✅ Polling cada 30s | ✅ | Mínimo |
| Dashboard | ⚠️ Proxy a KMS | Dashboard propio | Medio |
| HA | ❌ Standalone | Active-Standby | **Alto** |
| 500k peticiones | ❌ Sin pooling | Connection pooling | **Alto** |
| Key rotation | ⚠️ Manual via KMS | Automático con alerta | Medio |
| Failover automático | ❌ | Auto-switch a backup | **Alto** |

### 8.2 KMS (172.16.222.240)

| Aspecto | Actual | Objetivo | Gap |
|---------|--------|----------|-----|
| API integration | ⚠️ Proxy desde orquestador | Client nativo | Medio |
| Dashboard | ⚠️ Via proxy KMS | Dashboard propio | Medio |
| HA | ❌ Standalone | Active-Standby | **Alto** |
| 500k peticiones | ❌ Sin pooling | Connection pooling | **Alto** |
| Key sync DRM↔KMS | ⚠️ Manual | Automático | Medio |

### 8.3 Origins (CDN)

| Aspecto | Actual | Objetivo | Gap |
|---------|--------|----------|-----|
| Job management | ✅ API completa | ✅ | Mínimo |
| Health monitoring | ⚠️ Solo al pollear | Dashboard de salud | Medio |
| Failover | ❌ | Primario→Backup automático | **Alto** |
| Traffic metrics | ❌ | Bytes, conexiones, errores | Medio |

### 8.4 HAProxy

| Aspecto | Actual | Objetivo | Gap |
|---------|--------|----------|-----|
| Map sync | ✅ Automático | ✅ | Mínimo |
| Dashboard | ❌ | Métricas en tiempo real | Medio |
| Backend health | ❌ | Monitoreo de salud | **Alto** |
| Rate limiting | ❌ | Por canal | Bajo |

### 8.5 TsMonitor

| Aspecto | Actual | Objetivo | Gap |
|---------|--------|----------|-----|
| Remote logs | ✅ Via API | ✅ | Mínimo |
| Dashboard integrado | ❌ | Vista unificada en orquestador | Bajo |
| Alarm correlation | ❌ | Correlacionar con encoder/packager status | Medio |

---

## 9. Plan de Fases

### Fase A: Consolidar existente (v2.15.0) — ~7h

| # | Tarea | Dependencias |
|---|-------|--------------|
| A1 | Sincronizar signal_analyzer.py canonical ↔ agents | Ninguna |
| A2 | Restart callback para discontinuidades (Issue #2) | A1 |
| A3 | Auth en Linux agent `/encoder/analyze` | Ninguna |
| A4 | Fix deploy.sh `--diff-filter=AM` | Ninguna |

### Fase B: DRM (172.16.222.241) — HA + 500k (v2.16.0) — ~28h

| # | Tarea | Dependencias |
|---|-------|--------------|
| B1 | Dashboard DRM: estado licencias, keys, expiración | A |
| B2 | API client nativo para Widevine server | A |
| B3 | HA DRM: configuración active-standby + health check cruzado | B2 |
| B4 | Connection pooling para 500k peticiones | B2 |
| B5 | Rotación automática de keys con notificación | B2 |
| B6 | Alertas expiración licencias DRM | B1 |

### Fase C: KMS (172.16.222.240) — HA + 500k (v2.17.0) — ~26h

| # | Tarea | Dependencias |
|---|-------|--------------|
| C1 | API client nativo para KMS | A |
| C2 | Dashboard KMS: keys activas, uso, expiración | C1 |
| C3 | HA KMS: configuración active-standby | C1 |
| C4 | Connection pooling para 500k peticiones | C1 |
| C5 | Integración DRM↔KMS: flujo completo de licencia | B2, C1 |

### Fase D: Origins / CDN (v2.18.0) — ~17h

| # | Tarea | Dependencias |
|---|-------|--------------|
| D1 | Dashboard origins: salud, latencia, uptime | A |
| D2 | Failover automático origin primario→backup | D1 |
| D3 | Monitoreo tráfico CDN (bytes, conexiones, errores) | D1 |
| D4 | Sincronización configuración origins | A |

### Fase E: HAProxy — Dashboard + Monitoreo (v2.19.0) — ~13h

| # | Tarea | Dependencias |
|---|-------|--------------|
| E1 | Dashboard HAProxy: conexiones, bytes, errores | A |
| E2 | Monitoreo salud backends (encoder→packager) | E1 |
| E3 | Alertas caída de backend | E2 |
| E4 | Rate limiting por canal | E1 |

### Fase F: Observabilidad Unificada (v2.20.0) — ~30h

| # | Tarea | Dependencias |
|---|-------|--------------|
| F1 | Dashboard unificado: todos los componentes | B, C, D, E |
| F2 | Métricas Prometheus/Grafana | F1 |
| F3 | Alertas consolidadas (email + Telegram) | F1 |
| F4 | Logs centralizados con correlación | F1 |

---

## 10. Dependencias entre Fases

```
A (Consolidar) ──► B (DRM) ──────────┐
       │                              │
       ├──► C (KMS) ─────────────────┤
       │                              │
       ├──► D (Origins) ─────────────┼──► F (Observabilidad)
       │                              │
       └──► E (HAProxy) ─────────────┘
```

**Fase A** es prerequisito para todas.  
**Fases B, C, D, E** pueden ejecutarse en paralelo.  
**Fase F** es la última: consolida todo.

---

## 11. Estimación de Esfuerzo

| Fase | Versión | Descripción | Esfuerzo |
|------|---------|-------------|----------|
| A | v2.15.0 | Consolidar existente | ~7h |
| **Fase B** | v2.16.0 | DRM (172.16.222.241): HA + 500k | ~28h |
| **Fase C** | v2.17.0 | KMS (172.16.222.240): HA + 500k | ~26h |
| D | v2.18.0 | Origins / CDN | ~17h |
| E | v2.19.0 | HAProxy: Dashboard | ~13h |
| F | v2.20.0 | Observabilidad unificada | ~30h |
| **Total** | | | **~121h** |

---

## 12. Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| DRM/KMS HA requiere cambio de infra | Alto | DRM (.241) y KMS (.240) son independientes — diseñar HA por separado |
| 500k peticiones necesita load balancer | Alto | Evaluar HAProxy como LB para DRM (.241) y KMS (.240) independientemente |
| TsMonitor es monolito (9200 líneas) | Medio | No refactorizar, solo integrar vía API |
| Agents Mac/Linux se desincronizan | Medio | Canonical = signal_analyzer.py del orquestador |
| CMS es externo y no controlamos cambios | Bajo | Mantener API contract documentado |

---

## 13. Próximos Pasos

1. Revisar y aprobar este HLD
2. Crear issues detallados por fase (B-F)
3. Ejecutar Fase A (consolidar)
4. Iniciar Fases B-E en paralelo según prioridad
5. Cerrar con Fase F (observabilidad unificada)
