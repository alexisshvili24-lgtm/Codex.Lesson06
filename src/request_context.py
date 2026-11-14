"""Контекст пользователя для серверных операций одного HTTP-запроса."""
from contextvars import ContextVar

_user_id: ContextVar[int | None] = ContextVar('git_support_user_id', default=None)
_UNSET = object()
_api_key: ContextVar[object | str | None] = ContextVar('git_support_api_key', default=_UNSET)
_key_version: ContextVar[str | None] = ContextVar('git_support_key_version', default=None)


def set_user_id(user_id: int, api_key=_UNSET, key_version=None):
    return (_user_id.set(user_id), _api_key.set(api_key), _key_version.set(key_version))


def reset_user_id(token) -> None:
    user_token, key_token, version_token = token
    _user_id.reset(user_token)
    _api_key.reset(key_token)
    _key_version.reset(version_token)


def current_user_id() -> int:
    user_id = _user_id.get()
    if user_id is None:
        # Сохраняет совместимость внутренних CLI и существующих тестов.
        # HTTP API всегда задаёт user_id только после проверки сессии.
        return 1
    return user_id


def current_api_key_snapshot():
    return _api_key.get()


def has_api_key_snapshot() -> bool:
    return _api_key.get() is not _UNSET


def current_key_version():
    return _key_version.get()


def request_context_snapshot():
    return _user_id.get(), _api_key.get(), _key_version.get()
