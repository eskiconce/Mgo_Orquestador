from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config import DATABASE_URL

try:
    engine = create_engine(
        DATABASE_URL,
        pool_recycle=3600,
        pool_size=10
    )
except Exception as e:
    print(f"Error configurando engine DB: {e}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
