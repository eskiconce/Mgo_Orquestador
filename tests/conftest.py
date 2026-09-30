"""
Fixtures compartidas para tests del orquestador.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app


@pytest.fixture(name="db_session")
def fixture_db_session():
    """Crea una BD SQLite en memoria para tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db_session):
    """Client de test con BD en memoria."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="admin_client")
def fixture_admin_client(client, db_session):
    """Client con cookie de admin."""
    from core.deps import create_access_token
    import models as m
    user = m.User(username="admin_t", full_name="Admin Test", email="admin_t@test.cl",
                  hashed_password="x", role="admin", disabled=False)
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": "admin_t"})
    client.cookies.set("access_token", f"Bearer {token}")
    yield client
    client.cookies.clear()


@pytest.fixture(name="operator_client")
def fixture_operator_client(client, db_session):
    """Client con cookie de operator."""
    from core.deps import create_access_token
    import models as m
    user = m.User(username="operator_t", full_name="Operator Test", email="op_t@test.cl",
                  hashed_password="x", role="operator", disabled=False)
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": "operator_t"})
    client.cookies.set("access_token", f"Bearer {token}")
    yield client
    client.cookies.clear()
