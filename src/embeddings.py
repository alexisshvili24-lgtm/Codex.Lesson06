"""Получение embeddings RouterAI с учётом каждого платного вызова."""
import math
import time
import uuid
from decimal import Decimal
from dotenv import dotenv_values
from src import routerai
from src.database import ENV_PATH
from src.service import settings, repo


class EmbeddingError(ValueError):
    pass


def embed_texts(texts, config=None, group_id=None):
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingError('Переданы пустые тексты для embeddings.')
    conf = config if config is not None else settings()
    key = dotenv_values(ENV_PATH, encoding='utf-8-sig').get('ROUTERAI_API_KEY')
    request_id = str(uuid.uuid4())
    if not key:
        repo.log(request_id, 'embedding', 'not_sent', payload={'error': 'API-ключ не настроен'})
        raise EmbeddingError('API-ключ не настроен.')
    model = conf['embedding_model']
    start = time.perf_counter()
    response = None
    generation_id = None
    error = None
    vectors = None
    try:
        response, generation_id = routerai.request_json(conf['base_url'], key, '/embeddings', {'model': model, 'input': texts})
        data = response['data']
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError('Количество векторов не соответствует количеству текстов')
        if any(not isinstance(item, dict) or type(item.get('index')) is not int for item in data):
            raise ValueError('Некорректные индексы векторов')
        ordered = sorted(data, key=lambda item: item['index'])
        if [item['index'] for item in ordered] != list(range(len(texts))):
            raise ValueError('Некорректные индексы векторов')
        vectors = [item['embedding'] for item in ordered]
        if not vectors[0] or any(not isinstance(v, list) or len(v) != len(vectors[0]) or any(isinstance(x, bool) or not isinstance(x, (int, float, Decimal)) or not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('Некорректные размеры или значения векторов')
    except routerai.ProviderError as exc:
        error, generation_id = str(exc).replace(key, '[СКРЫТО]'), exc.generation_id
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        error = 'Некорректный ответ embeddings: ' + str(exc).replace(key, '[СКРЫТО]')
    paid_cost, cost_error = routerai.cost(conf['base_url'], key, generation_id)
    repo.log(request_id, 'embedding', 'error' if error else 'ok', model,
             round((time.perf_counter() - start) * 1000), paid_cost,
             {'generation_id': generation_id, 'count': len(texts), 'error': error, 'cost_error': cost_error, 'group_id': group_id})
    if error:
        raise EmbeddingError(error)
    return [[float(x) for x in vector] for vector in vectors]
