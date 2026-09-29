"""
Router de reglas de alertas — CRUD para gestión de reglas configurables.
"""
from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

import models
from database import get_db
from core.deps import get_current_user

router = APIRouter(tags=["alert-rules"])


# --- Schemas ---

class AlertRuleCreate(BaseModel):
    name: str
    source: str
    channel_id: Optional[int] = None
    alert_type: str
    action: str
    enabled: bool = True
    priority: int = 0
    cooldown_seconds: int = 60
    notify_telegram: bool = True
    notify_cms: bool = True
    custom_message: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    channel_id: Optional[int] = None
    alert_type: Optional[str] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    notify_telegram: Optional[bool] = None
    notify_cms: Optional[bool] = None
    custom_message: Optional[str] = None


# --- Endpoints API ---

@router.get("/api/alert-rules")
def list_alert_rules(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Lista todas las reglas de alertas."""
    rules = db.query(models.AlertRule).order_by(
        models.AlertRule.source,
        models.AlertRule.priority.desc(),
        models.AlertRule.id
    ).all()
    
    return [
        {
            "id": r.id,
            "name": r.name,
            "source": r.source,
            "channel_id": r.channel_id,
            "channel_name": r.channel.channel_name if r.channel else "Todos",
            "alert_type": r.alert_type,
            "action": r.action,
            "enabled": r.enabled,
            "priority": r.priority,
            "cooldown_seconds": r.cooldown_seconds,
            "notify_telegram": r.notify_telegram,
            "notify_cms": r.notify_cms,
            "custom_message": r.custom_message,
            "last_executed_at": r.last_executed_at.isoformat() if r.last_executed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rules
    ]


@router.post("/api/alert-rules")
def create_alert_rule(rule: AlertRuleCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Crea una nueva regla de alertas."""
    if current_user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Solo admin puede crear reglas")
    
    # Validar source
    valid_sources = ["tsmonitor", "packager", "encoder", "any"]
    if rule.source not in valid_sources:
        raise HTTPException(400, f"Source inválido. Valores válidos: {valid_sources}")
    
    # Validar action
    valid_actions = ["stop_encoder", "start_encoder", "restart_encoder", "notify_only", "failover"]
    if rule.action not in valid_actions:
        raise HTTPException(400, f"Action inválido. Valores válidos: {valid_actions}")
    
    # Validar channel_id si se proporciona
    if rule.channel_id is not None:
        channel = db.query(models.Channel).filter(models.Channel.id == rule.channel_id).first()
        if not channel:
            raise HTTPException(404, "Canal no encontrado")
    
    new_rule = models.AlertRule(
        name=rule.name,
        source=rule.source,
        channel_id=rule.channel_id,
        alert_type=rule.alert_type,
        action=rule.action,
        enabled=rule.enabled,
        priority=rule.priority,
        cooldown_seconds=rule.cooldown_seconds,
        notify_telegram=rule.notify_telegram,
        notify_cms=rule.notify_cms,
        custom_message=rule.custom_message,
    )
    
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    
    return {"status": "created", "id": new_rule.id, "name": new_rule.name}


@router.put("/api/alert-rules/{rule_id}")
def update_alert_rule(rule_id: int, rule: AlertRuleUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Actualiza una regla de alertas."""
    if current_user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Solo admin puede actualizar reglas")
    
    db_rule = db.query(models.AlertRule).filter(models.AlertRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(404, "Regla no encontrada")
    
    # Actualizar campos
    if rule.name is not None:
        db_rule.name = rule.name
    if rule.source is not None:
        valid_sources = ["tsmonitor", "packager", "encoder", "any"]
        if rule.source not in valid_sources:
            raise HTTPException(400, f"Source inválido. Valores válidos: {valid_sources}")
        db_rule.source = rule.source
    if rule.channel_id is not None:
        if rule.channel_id != 0:
            channel = db.query(models.Channel).filter(models.Channel.id == rule.channel_id).first()
            if not channel:
                raise HTTPException(404, "Canal no encontrado")
        db_rule.channel_id = rule.channel_id if rule.channel_id != 0 else None
    if rule.alert_type is not None:
        db_rule.alert_type = rule.alert_type
    if rule.action is not None:
        valid_actions = ["stop_encoder", "start_encoder", "restart_encoder", "notify_only", "failover"]
        if rule.action not in valid_actions:
            raise HTTPException(400, f"Action inválido. Valores válidos: {valid_actions}")
        db_rule.action = rule.action
    if rule.enabled is not None:
        db_rule.enabled = rule.enabled
    if rule.priority is not None:
        db_rule.priority = rule.priority
    if rule.cooldown_seconds is not None:
        db_rule.cooldown_seconds = rule.cooldown_seconds
    if rule.notify_telegram is not None:
        db_rule.notify_telegram = rule.notify_telegram
    if rule.notify_cms is not None:
        db_rule.notify_cms = rule.notify_cms
    if rule.custom_message is not None:
        db_rule.custom_message = rule.custom_message
    
    db_rule.updated_at = datetime.now()
    db.commit()
    
    return {"status": "updated", "id": db_rule.id, "name": db_rule.name}


@router.delete("/api/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Elimina una regla de alertas."""
    if current_user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Solo admin puede eliminar reglas")
    
    db_rule = db.query(models.AlertRule).filter(models.AlertRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(404, "Regla no encontrada")
    
    db.delete(db_rule)
    db.commit()
    
    return {"status": "deleted", "id": rule_id}


@router.post("/api/alert-rules/{rule_id}/toggle")
def toggle_alert_rule(rule_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Habilita/deshabilita una regla de alertas."""
    if current_user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Solo admin puede cambiar estado de reglas")
    
    db_rule = db.query(models.AlertRule).filter(models.AlertRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(404, "Regla no encontrada")
    
    db_rule.enabled = not db_rule.enabled
    db_rule.updated_at = datetime.now()
    db.commit()
    
    return {"status": "toggled", "id": db_rule.id, "enabled": db_rule.enabled}


# --- Frontend UI ---

@router.get("/ui/alert-rules")
def alert_rules_ui(request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """Página de gestión de reglas de alertas."""
    from core.deps import templates
    
    rules = db.query(models.AlertRule).order_by(
        models.AlertRule.source,
        models.AlertRule.priority.desc(),
        models.AlertRule.id
    ).all()
    
    channels = db.query(models.Channel).order_by(models.Channel.channel_name).all()
    
    return templates.TemplateResponse("alert_rules.html", {
        "request": request,
        "user": current_user,
        "rules": rules,
        "channels": channels,
    })
