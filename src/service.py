import json
import time
import uuid
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from dotenv import dotenv_values, set_key
from src.database import ROOT, ENV_PATH
from src.repository import Repository
from src import routerai

DEFAULTS = {'base_url': 'https://routerai.ru/api/v1', 'embedding_model': 'baai/bge-m3',
            'generation_model': 'deepseek/deepseek-v4.1-flash-1017',
            'system_prompt': (ROOT / 'src' / 'default_prompt.txt').read_text(encoding='utf-8-sig'),
            'vector_enabled': 'false', 'vector_threshold': '0.5', 'bm25_enabled': 'false', 'bm25_threshold': '0'}
repo = Repository()

class Settings(BaseModel):
    base_url: str = Field(min_length=1, max_length=500, pattern=r'^https://[^\s]+$')
    embedding_model: str = Field(min_length=1, max_length=200)
    generation_model: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1)
    vector_enabled: bool
    vector_threshold: float = Field(ge=-1, le=1)
    bm25_enabled: bool
    bm25_threshold: float = Field(ge=0)
    api_key: str | None = Field(default=None, max_length=1000)

class TestAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str

def settings():
    data = DEFAULTS | repo.settings()
    data['key_configured'] = bool(dotenv_values(ENV_PATH, encoding='utf-8-sig').get('ROUTERAI_API_KEY'))
    return data

def save(data: Settings):
    values = data.model_dump(exclude={'api_key'})
    repo.save_settings({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()})
    if data.api_key:
        set_key(str(ENV_PATH), 'ROUTERAI_API_KEY', data.api_key.strip(), encoding='utf-8-sig')
    repo.log(str(uuid.uuid4()), 'settings', 'ok', payload={'changed': list(values), 'key_updated': bool(data.api_key)})

def test_call(kind):
    conf = settings()
    key = dotenv_values(ENV_PATH, encoding='utf-8-sig').get('ROUTERAI_API_KEY')
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
