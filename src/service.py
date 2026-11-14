import json
import time
import uuid
import os
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from dotenv import dotenv_values, set_key, unset_key
import portalocker
from src.database import ROOT, ENV_PATH, Session, User
from src.user_repository import key_version
from src.repository import Repository
from src import routerai
from src.request_context import current_user_id, current_api_key_snapshot, has_api_key_snapshot

DEFAULTS = {'base_url': 'https://routerai.ru/api/v1', 'embedding_model': 'baai/bge-m3',
            'generation_model': 'deepseek/deepseek-v4.1-flash-1017',
            'system_prompt': (ROOT / 'src' / 'default_prompt.txt').read_text(encoding='utf-8-sig'),
            'vector_enabled': 'false', 'vector_threshold': '0.5', 'bm25_enabled': 'false', 'bm25_threshold': '0'}
repo = Repository()

class Settings(BaseModel):
    base_url: str | None = Field(default=None, min_length=1, max_length=500, pattern=r'^https://[^\s]+$')
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
    generation_model: str | None = Field(default=None, min_length=1, max_length=200)
    system_prompt: str | None = Field(default=None, min_length=1)
    vector_enabled: bool | None = None
    vector_threshold: float | None = Field(default=None, ge=-1, le=1)
    bm25_enabled: bool | None = None
    bm25_threshold: float | None = Field(default=None, ge=0)
    api_key: str | None = Field(default=None, max_length=1000)

class TestAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str

def _key_name(user_id):
    return f'ROUTERAI_API_KEY_USER_{user_id}'


def api_key(user_id=None):
    if user_id is None and has_api_key_snapshot():
        return current_api_key_snapshot()
    owner_id = user_id if user_id is not None else current_user_id()
    return user_credentials(owner_id)[0]


def user_credentials(user_id):
    """Возвращает ключ и его версию как согласованный снимок для запроса."""
    lock_path = ENV_PATH.with_name(ENV_PATH.name + '.lock')
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_path), mode='a', timeout=15):
        key = dotenv_values(ENV_PATH, encoding='utf-8-sig').get(_key_name(user_id))
        version = key_version(user_id)
        return key, version


def _store_user_api_key(user_id, value):
    name = _key_name(user_id)
    lock_path = ENV_PATH.with_name(ENV_PATH.name + '.lock')
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_path), mode='a', timeout=15):
        previous = dotenv_values(ENV_PATH, encoding='utf-8-sig').get(name)
        set_key(str(ENV_PATH), name, value, quote_mode='always', encoding='utf-8-sig')
        try:
            with Session.begin() as session:
                user = session.get(User, user_id)
                if user is None:
                    raise LookupError('Профиль не найден.')
                user.api_key_version = str(uuid.uuid4())
        except Exception:
            if previous:
                set_key(str(ENV_PATH), name, previous, quote_mode='always', encoding='utf-8-sig')
            else:
                unset_key(str(ENV_PATH), name, encoding='utf-8-sig')
            raise


def migrate_legacy_api_key():
    """Однократно переносит прежний общий ключ в секреты профиля admin."""
    lock_path = ENV_PATH.with_name(ENV_PATH.name + '.lock')
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_path), mode='a', timeout=15):
        values = dotenv_values(ENV_PATH, encoding='utf-8-sig')
        legacy = values.get('ROUTERAI_API_KEY')
        admin_name = _key_name(1)
        admin_key = values.get(admin_name)
        if legacy and not admin_key:
            set_key(str(ENV_PATH), admin_name, legacy, quote_mode='always', encoding='utf-8-sig')
            admin_key = legacy
        if legacy:
            unset_key(str(ENV_PATH), 'ROUTERAI_API_KEY', encoding='utf-8-sig')
        if admin_key:
            with Session.begin() as session:
                admin = session.get(User, 1)
                if admin and not admin.api_key_version:
                    admin.api_key_version = str(uuid.uuid4())


def allowed_base_urls():
    config = dotenv_values(ENV_PATH, encoding='utf-8-sig')
    raw = os.environ.get('ROUTERAI_ALLOWED_BASE_URLS')
    if raw is None:
        raw = config.get('ROUTERAI_ALLOWED_BASE_URLS', '')
    values = [part.strip() for part in raw.split(',') if part.strip()] if raw else [DEFAULTS['base_url']]
    return {normalized for value in values
            if (normalized := _normalize_https_base_url(value)) is not None}


def _normalize_https_base_url(value):
    """Нормализует разрешённый адрес и отбрасывает небезопасную конфигурацию."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            return None
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower()
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    netloc = host + (f':{port}' if port is not None and port != 443 else '')
    path = parsed.path.rstrip('/')
    return urlunsplit(('https', netloc, path, '', ''))


def settings(user_id=None):
    owner_id = user_id if user_id is not None else current_user_id()
    data = DEFAULTS | repo.settings(owner_id)
    data['key_configured'] = bool(api_key(owner_id))
    return data


def save(data: Settings, user_id=None, *, is_admin=False):
    owner_id = user_id if user_id is not None else current_user_id()
    values = data.model_dump(exclude={'api_key'}, exclude_unset=True)
    current = settings(owner_id)
    embedding = values.pop('embedding_model', current['embedding_model'])
    if embedding != current['embedding_model']:
        raise ValueError('Модель embeddings общая и не может быть изменена после создания индекса.')
    shared = {name: values.pop(name) for name in ('base_url', 'generation_model') if name in values}
    if shared and not is_admin:
        if any(str(value) != str(current[name]) for name, value in shared.items()):
            raise PermissionError('Общие настройки может изменять только admin.')
        shared = {}
    if is_admin:
        if 'base_url' in shared and shared['base_url'].rstrip('/') not in allowed_base_urls():
            raise ValueError('Этот RouterAI Base URL не разрешён настройками сервера.')
        if shared:
            repo.save_settings(shared, user_id=owner_id)
    personal = {k: str(v).lower() if isinstance(v, bool) else str(v)
                for k, v in values.items() if v is not None}
    if personal:
        repo.save_settings(personal, user_id=owner_id)
    key_updated = bool(data.api_key and data.api_key.strip())
    if key_updated:
        _store_user_api_key(owner_id, data.api_key.strip())
    repo.log(str(uuid.uuid4()), 'settings', 'ok', payload={
        'changed': list(personal) + list(shared), 'key_updated': key_updated}, user_id=owner_id)

def test_call(kind):
    conf = settings()
    key = api_key()
    request_id = str(uuid.uuid4())
    if not key:
        repo.log(request_id, kind, 'not_sent', payload={'error': 'API-ключ не настроен'})
        return {'ok': False, 'message': 'API-ключ не настроен', 'request_id': request_id}
    if kind == 'connection':
        path, body, model = '/models', None, ''
    elif kind == 'embedding':
        model = conf['embedding_model']
        path, body = '/embeddings', {'model': model, 'input': 'Проверка подключения к Git'},
    else:
        model = conf['generation_model']
        path = '/chat/completions'
        body = {'model': model, 'messages': [{'role': 'system', 'content': 'Верни JSON с одним полем message типа string.'}, {'role': 'user', 'content': 'Ответь коротким приветствием.'}],
                'response_format': {'type': 'json_schema', 'json_schema': {'name': 'test_answer', 'strict': True, 'schema': TestAnswer.model_json_schema()}}}
    start = time.perf_counter()
    response, generation_id, error, paid_cost, cost_error = None, None, None, None, None
    try:
        response, generation_id = routerai.request_json(conf['base_url'], key, path, body)
        if kind == 'embedding':
            vector = response['data'][0]['embedding']
            if not isinstance(vector, list) or not vector:
                raise ValueError('Пустой embedding')
        elif kind == 'generation':
            TestAnswer.model_validate_json(response['choices'][0]['message']['content'])
    except routerai.ProviderError as exc:
        error, response, generation_id = str(exc), exc.response, exc.generation_id
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        error = 'Проверка ответа не пройдена: ' + str(exc).replace(key, '[СКРЫТО]')
    if kind != 'connection':
        paid_cost, cost_error = routerai.cost(conf['base_url'], key, generation_id)
    duration = round((time.perf_counter() - start) * 1000)
    payload = {'request': body, 'response': response, 'generation_id': generation_id, 'error': error, 'cost_error': cost_error}
    payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str).replace(key, '[СКРЫТО]'))
    repo.log(request_id, kind, 'error' if error else 'ok', model, duration, paid_cost, payload)
    return {'ok': error is None, 'message': error or ('Проверка выполнена' if not cost_error else 'Проверка выполнена; стоимость неизвестна'), 'cost_rub': str(paid_cost) if paid_cost is not None else None, 'request_id': request_id}
