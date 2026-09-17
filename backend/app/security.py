import hashlib
import json
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

ALGORITHM = "HS256"

# bcrypt молча отбрасывает всё после 72 байт: кириллический пароль упирается в
# предел вдвое раньше латинского, поэтому длина проверяется явно.
BCRYPT_MAX_BYTES = 72


class PasswordTooLongError(ValueError):
    def __init__(self) -> None:
        super().__init__(
            f"Пароль длиннее {BCRYPT_MAX_BYTES} байт в кодировке UTF-8 "
            "(около 36 символов кириллицей)"
        )


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise PasswordTooLongError
    salt = bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)
    return bcrypt.hashpw(encoded, salt).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        # Хеш повреждён или создан другим алгоритмом — вход запрещён.
        return False


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {"sub": subject, "role": role, "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def content_hash(payload: dict) -> str:
    """Отпечаток утверждённого решения.

    Фиксирует авторство до подключения УКЭП: хеш считается от канонизированного
    JSON, поэтому любое изменение ответов или решения ломает сверку.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
