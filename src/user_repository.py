"""Хранилище профилей и серверных сессий."""
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from src.database import Session, User, UserSession

_NICKNAME = re.compile(r'^[\w-]{1,32}$', re.UNICODE)
SESSION_TTL = timedelta(days=30)
_creation_lock = threading.Lock()


class InvalidNickname(ValueError):
    pass


def normalize_nickname(value: str) -> tuple[str, str]:
    nickname = unicodedata.normalize('NFC', value.strip())
    if not _NICKNAME.fullmatch(nickname):
        raise InvalidNickname('Никнейм должен содержать от 1 до 32 букв, цифр, дефисов или подчёркиваний.')
    return nickname, unicodedata.normalize('NFC', nickname.casefold())


def _identity(user: User) -> dict:
    return {'id': user.id, 'nickname': user.nickname, 'is_admin': user.is_admin,
            'api_key_configured': bool(user.api_key_version)}


def get_or_create(nickname: str) -> dict:
    display_name, normalized = normalize_nickname(nickname)
    with _creation_lock:
        return _get_or_create_locked(display_name, normalized)


def _get_or_create_locked(display_name: str, normalized: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with Session.begin() as session:
            user = session.scalar(select(User).where(User.nickname_normalized == normalized))
            if user is None:
                user = User(nickname='admin' if normalized == 'admin' else display_name,
                            nickname_normalized=normalized, is_admin=normalized == 'admin',
                            created_at=now)
                session.add(user)
                session.flush()
            return _identity(user)
    except IntegrityError:
        # Два одновременных первых входа по одному нику: уникальный индекс БД
        # выбирает единственную запись; проигравший читает уже созданный профиль.
        with Session() as session:
            user = session.scalar(select(User).where(User.nickname_normalized == normalized))
            if user is None:
                raise
            return _identity(user)


def create_session(token_hash: str, user_id: int) -> str:
    now = datetime.now(timezone.utc)
    expires = now + SESSION_TTL
    with Session.begin() as session:
        session.add(UserSession(token_hash=token_hash, user_id=user_id,
                                created_at=now.isoformat(), expires_at=expires.isoformat()))
    return expires.isoformat()


def session_user(token_hash: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with Session() as session:
        row = session.scalar(select(UserSession).where(
            UserSession.token_hash == token_hash, UserSession.expires_at > now))
        if row is None:
            return None
        user = session.get(User, row.user_id)
        return _identity(user) if user else None


def revoke_session(token_hash: str) -> None:
    with Session.begin() as session:
        session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))


def key_version(user_id: int) -> str | None:
    with Session() as session:
        user = session.get(User, user_id)
        return user.api_key_version if user else None


def update_key_version(user_id: int, version: str | None) -> None:
    with Session.begin() as session:
        user = session.get(User, user_id)
        if user is None:
            raise LookupError('Профиль не найден.')
        user.api_key_version = version
