import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os
import models
from database import SessionLocal
from core.config import LOG_DIR

# ==========================================
# INTERCEPTOR HACIA LA BASE DE DATOS
# ==========================================
class DBLogHandler(logging.Handler):
    def emit(self, record):
        try:
            db = SessionLocal()
            new_log = models.SystemLog(
                level=record.levelname,
                message=record.getMessage(),
                timestamp=datetime.fromtimestamp(record.created)
            )
            db.add(new_log)
            db.commit()
            db.close()
        except Exception:
            # Ignoramos si la BD está caída para no detener el orquestador
            pass

# ==========================================
# INICIALIZACIÓN DEL LOGGER
# ==========================================
def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    sys_logger = logging.getLogger("Orchestrator")
    sys_logger.setLevel(logging.INFO)
    
    # Evitar duplicar handlers si el framework recarga el módulo
    if not sys_logger.handlers:
        # 1. Handler de Archivo Físico (Rota a los 5MB)
        file_handler = RotatingFileHandler(f"{LOG_DIR}/orchestrator.log", maxBytes=5000000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        sys_logger.addHandler(file_handler)

        # 2. Handler de Base de Datos
        db_handler = DBLogHandler()
        db_handler.setLevel(logging.INFO)
        sys_logger.addHandler(db_handler)
        
    return sys_logger

# Exportamos la instancia lista para usar en todo el proyecto
logger = setup_logger()