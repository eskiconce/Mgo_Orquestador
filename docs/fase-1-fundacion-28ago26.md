# Fase 1: Fundación — v2.9.0

**Fecha:** 28 Aug 2026
**Versión:** v2.8.6 → v2.9.0

## Objetivo

Establecer la base técnica para futuras fases: configuración centralizada, dependencias documentadas, código limpio y cliente HTTP unificado.

## Cambios realizados

### 1. Configuración centralizada (`core/config.py`)

**Antes:** Constantes hardcodeadas en múltiples archivos, duplicadas entre `main.py` y `monitor.py`.

**Ahora:** Todas las constantes en `core/config.py` con `os.getenv()` y valores por defecto. Se usa `python-dotenv` para cargar `.env`.

```python
# Ejemplo de uso
from core.config import AGENT_PORT, SECRET_KEY, DATABASE_URL
```

**Archivos que importan desde config:** `main.py`, `monitor.py`, `database.py`, `services/*`, `utils/helpers.py`, `routers/*`

### 2. `.env.example`

Plantilla de configuración para el servidor. Copiar a `.env` y ajustar valores.

### 3. `requirements.txt`

11 dependencias documentadas:
- fastapi, uvicorn, sqlalchemy, pymysql
- httpx, python-dotenv, python-jose, passlib, bcrypt
- python-multipart, requests

### 4. Cliente HTTP unificado (`core/http_client.py`)

Factory para httpx sync/async con configuración estándar:
- `create_sync_client()` — para monitor.py
- `create_async_client()` — para main.py (lifespan)

Configuración compartida: 50 conexiones, 20 keepalive, timeouts estándar.

### 5. Limpieza de código muerto

Eliminados ~130 líneas de código comentado en `monitor.py` (versiones viejas de `check_encoder_health_logs`) y `main.py` (ruta vieja de monitor-logs).

## Rollback

```bash
git revert 280d266  # v2.9.0 commit
```

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `core/config.py` | Reescrito con `os.getenv()` |
| `core/http_client.py` | **Nuevo** |
| `database.py` | Importa `DATABASE_URL` desde config |
| `monitor.py` | Importa config desde `core.config` |
| `main.py` | Importa `create_async_client` |
| `.env.example` | **Nuevo** |
| `requirements.txt` | **Nuevo** |
