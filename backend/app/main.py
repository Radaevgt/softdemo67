import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, assessments, auth, cases, catalog, escalations
from .config import STATIC_DIR, get_settings
from .db import Base, SessionLocal, engine
from .enums import Role
from .models import Municipality, User
from .security import PasswordTooLongError, hash_password
from .services import sync_seed

logger = logging.getLogger(__name__)
settings = get_settings()


def bootstrap() -> None:
    """Готовит базу к работе: матрица из ТЗ и первый оператор.

    Схема в PostgreSQL создаётся Alembic; ``auto_create_schema`` нужен только для
    локального запуска на SQLite и для тестов.
    """
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)

    with SessionLocal() as db:
        sync_seed(db)

        if db.query(User).count() == 0:
            municipality = Municipality(name="Тестовое муниципальное образование", code="00")
            db.add(municipality)
            db.flush()
            db.add(
                User(
                    login=settings.bootstrap_operator_login,
                    password_hash=hash_password(settings.bootstrap_operator_password),
                    full_name="Оператор системы",
                    role=Role.OPERATOR,
                    municipality_id=municipality.id,
                )
            )
            db.commit()
            logger.warning(
                "Создана учётная запись оператора «%s» — смените пароль после первого входа",
                settings.bootstrap_operator_login,
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Портал работы с заброшенными объектами",
    description=(
        "Этап 4: определение способа оформления права муниципальной собственности "
        "или понуждения собственника к сносу."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, catalog, cases, assessments, admin, escalations):
    app.include_router(module.router)


@app.exception_handler(PasswordTooLongError)
def password_too_long(_: Request, error: PasswordTooLongError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(error)})


@app.get("/api/health", tags=["Служебное"])
def health() -> dict:
    return {"status": "ok"}


def mount_frontend(application: FastAPI, static_dir: Path) -> None:
    """Отдаёт собранный фронтенд из этого же приложения.

    Одна служба вместо двух: не нужен ни отдельный веб-сервер, ни CORS. Локально
    каталога со сборкой нет — там фронтенд поднимает собственный сервер.
    """
    root = static_dir.resolve()
    index = root / "index.html"

    assets = root / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str) -> FileResponse:
        # Маршруты вида /cases/<id> разбирает браузер, поэтому неизвестный путь
        # отдаёт index.html. Кроме /api — там 404 обязан остаться 404, иначе
        # клиент получит HTML вместо описания ошибки.
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")

        candidate = (root / path).resolve()
        # Проверка вложенности обязательна: путь приходит из запроса и может
        # содержать выход за пределы каталога.
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


if settings.serves_frontend:
    mount_frontend(app, STATIC_DIR)
else:
    logger.info("Каталог со сборкой фронтенда не найден — отдаётся только API")


