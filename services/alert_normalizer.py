"""
Alert Normalizer — Convierte alertas de plataformas externas a formato interno unificado.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class NormalizedAlert:
    """Formato interno unificado de alertas."""
    source: str          # "tsmonitor", "packager", "encoder"
    channel_id: int      # ID del canal
    alert_type: str      # Tipo normalizado (freeze, down, restore, etc.)
    raw_status: str      # Status original de la plataforma
    timestamp: datetime  # Fecha/hora de la alerta
    metadata: Dict[str, Any] = None  # Datos adicionales de la plataforma

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# Mapeo de status de tsmonitor a tipos normalizados
TSMONITOR_TYPE_MAP = {
    "freeze": "freeze",
    "dead": "down",
    "down": "down",
    "restore": "restore",
    "ok": "restore",
    "up": "restore",
    "restored": "restore",
    "live": "restore",
    "black": "black",
}

# Mapeo de status de packager a tipos normalizados
PACKAGER_TYPE_MAP = {
    "caido": "down",
    "activo": "restore",
    "error": "down",
    "ok": "restore",
}

# Mapeo de status de encoder a tipos normalizados
ENCODER_TYPE_MAP = {
    "restart": "restart",
    "stop": "down",
    "start": "restore",
}


def normalize_tsmonitor_alert(
    num_canal,
    status: str,
    fecha: str,
    hora: str,
    channel_id: int
) -> NormalizedAlert:
    """
    Normaliza una alerta de TSMonitor.
    
    Args:
        num_canal: Número de canal (unique_id o numérico)
        status: Tipo de alerta (freeze, dead, down, restore, ok, up, etc.)
        fecha: Fecha en formato "YYYY-MM-DD"
        hora: Hora en formato "HH:MM:SS"
        channel_id: ID del canal en la BD
    
    Returns:
        NormalizedAlert con formato unificado
    """
    # Convertir timestamp
    try:
        timestamp = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        timestamp = datetime.now()

    # Normalizar tipo
    alert_type = TSMONITOR_TYPE_MAP.get(status.lower(), "unknown")

    return NormalizedAlert(
        source="tsmonitor",
        channel_id=channel_id,
        alert_type=alert_type,
        raw_status=status,
        timestamp=timestamp,
        metadata={
            "num_canal": num_canal,
            "fecha": fecha,
            "hora": hora,
        }
    )


def normalize_packager_alert(
    canal: str,
    servidor: str,
    estado: str,
    mensaje: str,
    timestamp_str: str,
    channel_id: int
) -> NormalizedAlert:
    """
    Normaliza una alerta de Packager.
    
    Args:
        canal: Nombre del canal
        servidor: Hostname del servidor
        estado: Estado (caido, activo, error, ok)
        mensaje: Mensaje de la alerta
        timestamp_str: Timestamp en formato "YYYY-MM-DD HH:MM:SS"
        channel_id: ID del canal en la BD
    
    Returns:
        NormalizedAlert con formato unificado
    """
    # Convertir timestamp
    try:
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        timestamp = datetime.now()

    # Normalizar tipo
    alert_type = PACKAGER_TYPE_MAP.get(estado.lower(), "unknown")

    return NormalizedAlert(
        source="packager",
        channel_id=channel_id,
        alert_type=alert_type,
        raw_status=estado,
        timestamp=timestamp,
        metadata={
            "canal": canal,
            "servidor": servidor,
            "mensaje": mensaje,
        }
    )


def normalize_encoder_alert(
    channel_name: str,
    reason: str,
    channel_id: int
) -> NormalizedAlert:
    """
    Normaliza una alerta de Encoder (reinicio interno).
    
    Args:
        channel_name: Nombre del canal
        reason: Razón del reinicio
        channel_id: ID del canal en la BD
    
    Returns:
        NormalizedAlert con formato unificado
    """
    # Normalizar tipo
    alert_type = ENCODER_TYPE_MAP.get("restart", "restart")

    return NormalizedAlert(
        source="encoder",
        channel_id=channel_id,
        alert_type=alert_type,
        raw_status="restart",
        timestamp=datetime.now(),
        metadata={
            "channel_name": channel_name,
            "reason": reason,
        }
    )
