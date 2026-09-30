"""
Cliente HTTP unificado para el orquestador.
Proporciona factories para httpx sync/async con configuración estándar.
"""
import httpx
from services.settings_service import get_api_key

# Configuración estándar de connection pooling
LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=20)
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


def create_sync_client(**kwargs) -> httpx.Client:
    """Crea un httpx.Client sincrónico con configuración estándar."""
    limits = kwargs.pop("limits", LIMITS)
    timeout = kwargs.pop("timeout", TIMEOUT)
    headers = kwargs.pop("headers", {})
    headers.setdefault("X-API-Key", get_api_key())
    return httpx.Client(limits=limits, timeout=timeout, headers=headers, **kwargs)


def create_async_client(**kwargs) -> httpx.AsyncClient:
    """Crea un httpx.AsyncClient con configuración estándar."""
    limits = kwargs.pop("limits", LIMITS)
    timeout = kwargs.pop("timeout", TIMEOUT)
    headers = kwargs.pop("headers", {})
    headers.setdefault("X-API-Key", get_api_key())
    return httpx.AsyncClient(limits=limits, timeout=timeout, headers=headers, **kwargs)
