"""
Rate limiting simple por IP para endpoints sensibles.
"""
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiter en memoria.
    Limita requests por IP en endpoints sensibles.
    Excluye health checks y endpoints de lectura.
    """

    def __init__(self, app, requests_per_minute: int = 300):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Excluir health checks, endpoints internos del monitor y endpoints de lectura frecuentes
        excluded_prefixes = [
            '/api/health', '/api/health/ready', '/docs', '/openapi.json',
            '/api/internal/', '/api/metrics', '/api/nodes/stats',
            '/static/', '/favicon.ico'
        ]
        if any(path.startswith(p) for p in excluded_prefixes):
            return await call_next(request)
        
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60  # 1 minuto

        # Limpiar requests viejos
        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if now - t < window
        ]

        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                content={
                    "success": False,
                    "error": "Demasiadas solicitudes. Intenta de nuevo en un minuto.",
                    "status_code": 429
                },
                status_code=429
            )

        self.requests[client_ip].append(now)
        return await call_next(request)
