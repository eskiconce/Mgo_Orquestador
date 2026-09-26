from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import httpx

from core.version import VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH, VERSION_STRING, VERSION_TYPE
from core.http_client import create_async_client
from core.logging_service import logger
from core.deps import templates
from core.rate_limit import RateLimitMiddleware
from database import verify_db_connection
from utils.helpers import time_duration
from services import cms_gateway, vod_service

# --- Routers ---
from routers.auth import router as auth_router
from routers.users import router as users_router
from routers.dashboard import router as dashboard_router
from routers.nodes import router as nodes_router
from routers.channels import router as channels_router
from routers.processes import router as processes_router
from routers.drm import router as drm_router
from routers.orchestrator import router as orchestrator_router
from routers.internal import router as internal_router
from routers.ui_logs import router as ui_logs_router
from routers.health import router as health_router

# --- HTTP Client Singleton ---
http_client: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    verify_db_connection()
    http_client = create_async_client()
    logger.info("HTTP client started with connection pooling")
    yield
    await http_client.aclose()
    logger.info("HTTP client closed")

app = FastAPI(title="MundoGo-Plus Orchestrator", lifespan=lifespan)

# Rate limiting: 60 requests/minute por IP
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Context Processor: Inyecta versión y filtros en TODOS los templates ---
templates.env.globals.update({
    "version_major": VERSION_MAJOR,
    "version_minor": VERSION_MINOR,
    "version_patch": VERSION_PATCH,
    "version_string": VERSION_STRING,
    "version_type": VERSION_TYPE
})
templates.env.filters["duration"] = time_duration

# --- Include routers ---
app.include_router(cms_gateway.router)
app.include_router(vod_service.router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(dashboard_router)
app.include_router(nodes_router)
app.include_router(channels_router)
app.include_router(processes_router)
app.include_router(drm_router)
app.include_router(orchestrator_router)
app.include_router(internal_router)
app.include_router(ui_logs_router)
app.include_router(health_router)

# --- Exception handler ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    return JSONResponse(
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code
        },
        status_code=exc.status_code
    )
