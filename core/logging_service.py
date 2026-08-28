"""
Servicio de logging centralizado.
Soporta formato texto (default) y JSON (opcional via LOG_FORMAT=json).
"""
import logging
import json
from logging.handlers import RotatingFileHandler
from datetime import datetime
import os
import traceback
from core.config import LOG_DIR

LOG_FORMAT = os.getenv("LOG_FORMAT", "text")


class JSONFormatter(logging.Formatter):
    """Formatter que produce JSON estructurado para cada log record."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class DBLogHandler(logging.Handler):
    """Escribe logs a la tabla SystemLog de la BD."""

    def emit(self, record):
        try:
            from database import SessionLocal
            import models
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
        # Handler de archivo con rotación
        file_handler = RotatingFileHandler(
            f"{LOG_DIR}/orchestrator.log", maxBytes=5000000, backupCount=5
        )

        if LOG_FORMAT == "json":
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            )

        sys_logger.addHandler(file_handler)

        # Handler de BD
        db_handler = DBLogHandler()
        db_handler.setLevel(logging.INFO)
        sys_logger.addHandler(db_handler)

    return sys_logger


logger = setup_logger()
