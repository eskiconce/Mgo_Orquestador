from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# USO DE PYMYSQL (Driver Puro Python)
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://ingservice:S3rv1c3.Ingenieria@localhost:3306/encoder_orchestrator"

try:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
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
