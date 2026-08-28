## Why

El orquestador tenía configuración dispersa, dependencias sin documentar, código muerto y clientes HTTP inconsistentes. Esta fase establece la base para fases posteriores.

## What Changes

- `core/config.py` centralizado con `python-dotenv` — todas las constantes usan `os.getenv()` con defaults
- `.env.example` como plantilla de configuración para el servidor
- `requirements.txt` con las 11 dependencias del proyecto
- `core/http_client.py` — factory unificada para httpx sync/async con pool compartido
- `database.py` importa `DATABASE_URL` desde config (antes hardcodeada)
- `monitor.py` importa config desde `core.config` (eliminados duplicados)
- Limpieza: eliminados bloques de código comentado en `monitor.py` (~100 líneas) y `main.py` (~30 líneas)

## Impact

- **Archivos modificados:** `core/config.py`, `core/version.py`, `database.py`, `monitor.py`, `main.py`, `CHANGELOG.md`
- **Archivos nuevos:** `.env.example`, `requirements.txt`, `core/http_client.py`
- **Servidor:** v2.8.6 → v2.9.0
- **Sin breaking changes** — todos los defaults mantienen el comportamiento anterior
