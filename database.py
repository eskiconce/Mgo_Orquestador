import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config import DATABASE_URL

logger = logging.getLogger(__name__)

try:
    engine = create_engine(
        DATABASE_URL,
        pool_recycle=3600,
        pool_size=10
    )
except Exception as e:
    logger.critical(f"Fatal: No se pudo crear el engine de base de datos: {e}")
    sys.exit(1)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def verify_db_connection():
    """Verifica que la conexión a BD funcione. Llama al arranque."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
        return True
    except Exception as e:
        logger.critical(f"Fatal: No se pudo conectar a la base de datos: {e}")
        sys.exit(1)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
