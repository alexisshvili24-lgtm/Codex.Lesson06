"""Структурированный ответ по снимкам найденных фрагментов."""
import json
import re
import time
import uuid
from typing import Literal
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from src import routerai
from src.database import ENV_PATH
from src.service import repo


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['full', 'partial', 'no_answer']
    answer: str = Field(min_length=1)
    source_ids: list[str]
    missing_information: list[str]


def validate_answer(raw, available):
    answer = Answer.model_validate_json(raw)
    cited = set(re.findall(r'\[(S\d+)\]', answer.answer))
    declared = set(answer.source_ids)
    if len(declared) != len(answer.source_ids) or cited != declared or not declared.issubset(available):
        raise ValueError('Ссылки в ответе не соответствуют переданным источникам.')
    if answer.status != 'no_answer' and not declared:
        raise ValueError('Ответ не содержит подтверждающих источников.')
    return answer


def generate_answer(question, sources, config, *, group_id=None, attempts=2, search_query=None):
    if not sources:
        return Answer(status='no_answer', answer='В документации не найдены подходящие фрагменты.', source_ids=[], missing_information=['Нет подходящих источников.'])
    available = {source['id'] for source in sources}
    request = {'question': question, 'sources': sources}
    prompt = config['system_prompt']
    if search_query is not None:
        request['search_query'] = search_query
        prompt += ('\nИспользуй search_query для понимания темы и ссылок на прошлые реплики. '
                   'Отвечай на question и соблюдай его пожелания к форме ответа.')
    if any(source.get('retrieval_role') == 'context' for source in sources):
        prompt += ('\nФрагменты с retrieval_role=context дополняют ответ, если они уместны. '
                   'Начни с сути текущего вопроса.')
    body = {'model':config['generation_model'], 'messages':[{'role':'system','content':prompt},
            {'role':'user','content':json.dumps(request, ensure_ascii=False)}],
            'response_format':{'type':'json_schema', 'json_schema':{'name':'rag_answer', 'strict':True, 'schema':Answer.model_json_schema()}}}
    return generate_structured(body, config, lambda raw: validate_answer(raw, available),
                               group_id=group_id, stage='answer', attempts=attempts)


def generate_structured(body, config, validate, *, group_id, stage, attempts=2):
    key = dotenv_values(ENV_PATH, encoding='utf-8-sig').get('ROUTERAI_API_KEY')
    if not key:
        raise ValueError('API-ключ не настроен.')
    last_error = None
    for _ in range(attempts):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        generation_id = None
        answer = None
        response = None
        error = None
        try:
            response, generation_id = routerai.request_json(config['base_url'], key, '/chat/completions', body)
            answer = validate(response['choices'][0]['message']['content'])
        except routerai.ProviderError as exc:
            generation_id = exc.generation_id
            error = str(exc).replace(key, '[СКРЫТО]')
        except (ValidationError, ValueError, KeyError, IndexError, TypeError) as exc:
            error = ('Некорректный ответ модели: ' + str(exc)).replace(key, '[СКРЫТО]')
        paid_cost, cost_error = routerai.cost(config['base_url'], key, generation_id)
        repo.log(request_id, 'generation', 'error' if error else 'ok', config['generation_model'],
                 round((time.perf_counter()-start)*1000), paid_cost,
                 {'group_id':group_id, 'stage':stage, 'generation_id':generation_id, 'error':error, 'cost_error':cost_error,
                  'request':json.loads(json.dumps(body, ensure_ascii=False).replace(key, '[СКРЫТО]')),
                  'response':json.loads(json.dumps(response, ensure_ascii=False, default=str).replace(key, '[СКРЫТО]')),
                  'validation':'ok' if answer is not None else 'error'})
        if answer is not None:
            return answer
        last_error = error
        if error and error.startswith('Некорректный ответ модели:'):
            body['messages'].append({'role':'user', 'content':'Предыдущий ответ не прошёл проверку: ' + error + '. Исправьте JSON согласно исходной инструкции.'})
    raise ValueError(last_error or 'Не удалось получить ответ модели.')
