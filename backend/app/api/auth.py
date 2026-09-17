from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from ..deps import CurrentUser, Db, audit
from ..models import User
from ..schemas import Token, UserOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["Аутентификация"])


@router.post("/login", response_model=Token)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Db,
    request: Request,
) -> Token:
    user = db.query(User).filter(User.login == form.username).one_or_none()
    if user is None or not verify_password(form.password, user.password_hash):
        # Одинаковый ответ для несуществующего логина и неверного пароля.
        audit(db, None, "login.failed", "app_user", form.username, request=request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись заблокирована")

    user.last_login_at = datetime.now(timezone.utc)
    audit(db, user, "login.success", "app_user", user.id, request=request)
    db.commit()
    return Token(access_token=create_access_token(user.login, user.role))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
