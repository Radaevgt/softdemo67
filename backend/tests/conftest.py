import os
import uuid
from pathlib import Path

import pytest

# Настройки должны быть выставлены до первого импорта приложения:
# get_settings кешируется, а engine создаётся на уровне модуля.
os.environ.setdefault("APP_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("APP_SECRET_KEY", "test-secret")
# Хеширование паролей — самая дорогая операция в фикстурах; в тестах стойкость не нужна.
os.environ.setdefault("APP_BCRYPT_ROUNDS", "4")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import main  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.enums import Role  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Municipality, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import sync_seed  # noqa: E402

PASSWORD = "test-password-1"


@pytest.fixture
def engine():
    # StaticPool keeps one in-memory database shared across sessions.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        sync_seed(session)
        yield session


@pytest.fixture
def municipalities(db):
    first = Municipality(name="Городской округ А", code="A")
    second = Municipality(name="Городской округ Б", code="B")
    db.add_all([first, second])
    db.commit()
    return first, second


@pytest.fixture
def users(db, municipalities):
    first, second = municipalities
    records = {
        "operator": User(
            login="operator", password_hash=hash_password(PASSWORD),
            full_name="Оператор", role=Role.OPERATOR, municipality_id=first.id,
        ),
        "methodologist": User(
            login="method", password_hash=hash_password(PASSWORD),
            full_name="Методолог", role=Role.METHODOLOGIST,
        ),
        "specialist_a": User(
            login="spec_a", password_hash=hash_password(PASSWORD),
            full_name="Специалист А", role=Role.SPECIALIST, municipality_id=first.id,
        ),
        "specialist_b": User(
            login="spec_b", password_hash=hash_password(PASSWORD),
            full_name="Специалист Б", role=Role.SPECIALIST, municipality_id=second.id,
        ),
        "viewer_a": User(
            login="view_a", password_hash=hash_password(PASSWORD),
            full_name="Наблюдатель А", role=Role.VIEWER, municipality_id=first.id,
        ),
    }
    db.add_all(records.values())
    db.commit()
    return records


@pytest.fixture
def client(monkeypatch, engine, session_factory, db, users):
    def override_get_db():
        with session_factory() as session:
            yield session

    # main.py импортировало engine и SessionLocal по имени, поэтому подменять
    # нужно именно его атрибуты — иначе startup поднимет собственную базу.
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", session_factory)

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def login(client):
    def _login(username: str) -> dict[str, str]:
        response = client.post(
            "/api/auth/login", data={"username": username, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
