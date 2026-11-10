import json
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

class ProviderError(Exception):
    def __init__(self, message, request=None, response=None, generation_id=None):
        super().__init__(message)
        self.request = request
        self.response = response
        self.generation_id = generation_id

def request_json(base, key, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = Request(base.rstrip('/') + path, data=data, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=45) as response:
            raw = response.read().decode('utf-8', errors='replace')
            generation_id = response.headers.get('X-Generation-Id')
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace').replace(key, '[СКРЫТО]')
        raise ProviderError(f'RouterAI: HTTP {exc.code}', body, raw, exc.headers.get('X-Generation-Id')) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f'Ошибка соединения: {str(exc).replace(key, "[СКРЫТО]")}', body) from exc
    try:
        result = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError) as exc:
        raise ProviderError('Ответ API не является корректным JSON', body, raw.replace(key, '[СКРЫТО]'), generation_id) from exc
    return result, generation_id or result.get('id')

def cost(base, key, generation_id):
    if not generation_id:
        return None, 'Идентификатор вызова отсутствует'
    try:
        result, _ = request_json(base, key, '/generation?' + urlencode({'id': generation_id}))
        data = result.get('data')
        value = data.get('total_cost') if isinstance(data, dict) else result.get('total_cost')
        if value is None:
            return None, 'Стоимость пока не получена'
        result_cost = Decimal(str(value))
        if not result_cost.is_finite() or result_cost < 0:
            raise InvalidOperation
        return result_cost, None
    except (ProviderError, InvalidOperation, ValueError) as exc:
        return None, str(exc)