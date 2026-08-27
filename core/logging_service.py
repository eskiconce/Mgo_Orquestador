import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os
import models
from database import SessionLocal
from core.config import LOG_DIR

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
            pass

def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    sys_logger = logging.getLogger("Orchestrator")
    sys_logger.setLevel(logging.INFO)
    
    if not sys_logger.handlers:
        file_handler = RotatingFileHandler(f"{LOG_DIR}/orchestrator.log", maxBytes=5000000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        sys_logger.addHandler(file_handler)

        db_handler = DBLogHandler()
        db_handler.setLevel(logging.INFO)
        sys_logger.addHandler(db_handler)
        
    return sys_logger

logger = setup_logger()
