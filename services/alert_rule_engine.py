"""
Alert Rule Engine — Busca y ejecuta reglas de alertas configurables.
"""
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session

import models
from services.alert_normalizer import NormalizedAlert

logger = logging.getLogger(__name__)


def find_applicable_rule(
    db: Session,
    alert: NormalizedAlert
) -> Optional[models.AlertRule]:
    """
    Busca la regla aplicable para una alerta normalizada.
    
    Prioridad de búsqueda:
    1. Regla específica: source + channel_id + alert_type
    2. Regla global source: source + channel_id=NULL + alert_type
    3. Regla global total: source=NULL + channel_id=NULL + alert_type
    
    Args:
        db: Sesión de BD
        alert: Alerta normalizada
    
    Returns:
        AlertRule encontrada o None
    """
    # 1. Buscar regla específica (source + channel_id + alert_type)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.source == alert.source,
        models.AlertRule.channel_id == alert.channel_id,
        models.AlertRule.alert_type == alert.alert_type,
        models.AlertRule.enabled == True
    ).order_by(models.AlertRule.priority.desc()).first()
    
    if rule:
        logger.debug(f"Regla específica encontrada: {rule.name} (id={rule.id})")
        return rule
    
    # 2. Buscar regla global source (source + channel_id=NULL + alert_type)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.source == alert.source,
        models.AlertRule.channel_id.is_(None),
        models.AlertRule.alert_type == alert.alert_type,
        models.AlertRule.enabled == True
    ).order_by(models.AlertRule.priority.desc()).first()
    
    if rule:
        logger.debug(f"Regla global source encontrada: {rule.name} (id={rule.id})")
        return rule
    
    # 3. Buscar regla global total (source=NULL + channel_id=NULL + alert_type)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.source == "any",
        models.AlertRule.channel_id.is_(None),
        models.AlertRule.alert_type == alert.alert_type,
        models.AlertRule.enabled == True
    ).order_by(models.AlertRule.priority.desc()).first()
    
    if rule:
        logger.debug(f"Regla global total encontrada: {rule.name} (id={rule.id})")
        return rule
    
    logger.debug(f"No se encontró regla para: source={alert.source}, channel_id={alert.channel_id}, alert_type={alert.alert_type}")
    return None


def check_cooldown(rule: models.AlertRule) -> bool:
    """
    Verifica si la regla está en período de cooldown.
    
    Args:
        rule: Regla a verificar
    
    Returns:
        True si está en cooldown (no ejecutar), False si puede ejecutar
    """
    if rule.last_executed_at is None:
        return False
    
    elapsed = (datetime.now() - rule.last_executed_at).total_seconds()
    if elapsed < rule.cooldown_seconds:
        logger.debug(f"Regla {rule.name} en cooldown ({elapsed:.0f}s / {rule.cooldown_seconds}s)")
        return True
    
    return False


def update_last_executed(db: Session, rule: models.AlertRule):
    """Actualiza el timestamp de última ejecución de la regla."""
    rule.last_executed_at = datetime.now()
    db.commit()


def execute_action(
    db: Session,
    rule: models.AlertRule,
    alert: NormalizedAlert
) -> dict:
    """
    Ejecuta la acción de una regla.
    
    Args:
        db: Sesión de BD
        rule: Regla a ejecutar
        alert: Alerta normalizada
    
    Returns:
        Dict con resultado de la ejecución
    """
    result = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "action": rule.action,
        "executed": False,
        "message": ""
    }
    
    # Buscar el canal
    channel = db.query(models.Channel).filter(
        models.Channel.id == alert.channel_id
    ).first()
    
    if not channel:
        result["message"] = f"Canal {alert.channel_id} no encontrado"
        logger.warning(result["message"])
        return result
    
    # Buscar job activo del encoder
    encoder_job = db.query(models.EncodingJob).join(models.Node).filter(
        models.EncodingJob.channel_id == channel.id,
        models.Node.tipo == "Encoder",
        models.EncodingJob.status.in_(["running", "starting", "stopped", "error"])
    ).first()
    
    if not encoder_job and rule.action not in ["notify_only"]:
        result["message"] = f"No se encontró job de encoder para canal {channel.channel_name}"
        logger.warning(result["message"])
        return result
    
    # Ejecutar acción según el tipo
    if rule.action == "stop_encoder":
        if encoder_job and encoder_job.status in ["running", "starting"]:
            result["executed"] = True
            result["message"] = f"Encoder detenido para canal {channel.channel_name}"
            logger.info(result["message"])
        else:
            result["message"] = f"Encoder ya está detenido para canal {channel.channel_name}"
            
    elif rule.action == "start_encoder":
        if encoder_job and encoder_job.status in ["stopped", "error"]:
            result["executed"] = True
            result["message"] = f"Encoder iniciado para canal {channel.channel_name}"
            logger.info(result["message"])
        else:
            result["message"] = f"Encoder ya está corriendo para canal {channel.channel_name}"
            
    elif rule.action == "restart_encoder":
        result["executed"] = True
        result["message"] = f"Encoder reiniciado para canal {channel.channel_name}"
        logger.info(result["message"])
        
    elif rule.action == "failover":
        result["executed"] = True
        result["message"] = f"Failover activado para canal {channel.channel_name}"
        logger.info(result["message"])
        
    elif rule.action == "notify_only":
        result["executed"] = True
        result["message"] = f"Notificación registrada para canal {channel.channel_name}"
        logger.info(result["message"])
    
    else:
        result["message"] = f"Acción desconocida: {rule.action}"
        logger.warning(result["message"])
    
    return result


def process_alert(
    db: Session,
    alert: NormalizedAlert
) -> dict:
    """
    Procesa una alerta normalizada usando el motor de reglas.
    
    Args:
        db: Sesión de BD
        alert: Alerta normalizada
    
    Returns:
        Dict con resultado del procesamiento
    """
    result = {
        "alert": {
            "source": alert.source,
            "channel_id": alert.channel_id,
            "alert_type": alert.alert_type,
            "raw_status": alert.raw_status,
        },
        "rule": None,
        "action_taken": False,
        "cooldown_active": False,
        "message": ""
    }
    
    # Buscar regla aplicable
    rule = find_applicable_rule(db, alert)
    
    if not rule:
        result["message"] = "No se encontró regla aplicable"
        logger.info(f"Alerta sin regla: {alert.source}/{alert.alert_type} canal={alert.channel_id}")
        return result
    
    result["rule"] = {
        "id": rule.id,
        "name": rule.name,
        "action": rule.action,
    }
    
    # Verificar cooldown
    if check_cooldown(rule):
        result["cooldown_active"] = True
        result["message"] = f"Regla {rule.name} en cooldown"
        logger.info(result["message"])
        return result
    
    # Ejecutar acción
    action_result = execute_action(db, rule, alert)
    result["action_taken"] = action_result["executed"]
    result["message"] = action_result["message"]
    
    # Actualizar timestamp de última ejecución
    if action_result["executed"]:
        update_last_executed(db, rule)
    
    return result
