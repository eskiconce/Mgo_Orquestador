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


# --- UI Parámetros Generales ---

@router.get("/ui/settings")
def settings_ui(request: Request, db: Session = Depends(get_db),
                current_user: models.User = Depends(admin_only)):
    settings = {s: get_section(db, s, defaults=d) for s, d in SECTION_DEFAULTS.items()}
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": current_user, "settings": settings,
    })


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
    if section == "security" and "api_key" in values:
        if not values["api_key"].isascii():
            raise HTTPException(400, "API key solo puede contener caracteres ASCII")
        if len(values["api_key"]) < 16:
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
