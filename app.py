from contextlib import asynccontextmanager
from pathlib import Path
from hashlib import sha256
import secrets
import logging
import os
import re
from urllib.parse import urlsplit
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from src import chat_repository
from src.database import ROOT, Setting, engine
from sqlalchemy import select
from src.service import Settings, settings, save, test_call, repo, migrate_legacy_api_key, user_credentials
from src import user_repository
from src.request_context import set_user_id, reset_user_id

@asynccontextmanager
async def lifespan(app):
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'migrations'))
    command.upgrade(config, 'head')
    migrate_legacy_api_key()
    yield

app = FastAPI(title='Git Support', lifespan=lifespan)
logger = logging.getLogger(__name__)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

SESSION_COOKIE = 'git_support_session'


def _session_identity(request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return user_repository.session_user(sha256(raw.encode('utf-8')).hexdigest())

@app.middleware('http')
async def local_origin(request: Request, call_next):
    host = request.headers.get('host', '')
    origin = request.headers.get('origin')
    if request.url.path == '/health' and request.method == 'GET':
        return await call_next(request)
    allowed = {'127.0.0.1', 'localhost', 'testserver', '179.254.162.130'}
    allowed.update(value.strip().lower() for value in os.environ.get('APP_ALLOWED_HOSTS', '').split(',') if value.strip())
    valid = False
    try:
        if len(request.headers.getlist('host')) == 1 and re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', host):
            parsed = urlsplit('http://' + host)
            port = parsed.port
            valid = parsed.hostname in allowed and (port is None or 1 <= port <= 65535)
            if origin is not None:
                parsed_origin = urlsplit(origin)
                origin_port = parsed_origin.port
                scheme = request.url.scheme
                default_port = 443 if scheme == 'https' else 80
                valid = (valid and len(request.headers.getlist('origin')) == 1
                         and parsed_origin.scheme == scheme and parsed_origin.hostname == parsed.hostname
                         and parsed_origin.username is None and parsed_origin.password is None
                         and parsed_origin.path == '' and parsed_origin.query == '' and parsed_origin.fragment == ''
                         and re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', parsed_origin.netloc) is not None
                         and (origin_port is None or 1 <= origin_port <= 65535)
                         and (origin_port or default_port) == (port or default_port))
    except ValueError:
        valid = False
    if not valid:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Недопустимый источник запроса'}, status_code=403)
    return await call_next(request)

@app.middleware('http')
async def require_session(request: Request, call_next):
    path = request.url.path
    if path.startswith('/api/') and path not in {'/api/auth/login', '/api/auth/me'}:
        user = _session_identity(request)
        if user is None:
            return JSONResponse({'detail': 'Войдите по никнейму, чтобы продолжить.'}, status_code=401)
        request.state.user = user
        key, key_version = user_credentials(user['id'])
        context_token = set_user_id(user['id'], key, key_version)
        try:
            return await call_next(request)
        finally:
            reset_user_id(context_token)
    return await call_next(request)


class LoginData(BaseModel):
    nickname: str = Field(min_length=1, max_length=100)


@app.post('/api/auth/login')
def login(data: LoginData, request: Request, response: Response):
    try:
        user = user_repository.get_or_create(data.nickname)
    except user_repository.InvalidNickname as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = secrets.token_urlsafe(32)
    user_repository.create_session(sha256(token.encode('utf-8')).hexdigest(), user['id'])
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=request.url.scheme == 'https',
                        samesite='lax', max_age=int(user_repository.SESSION_TTL.total_seconds()), path='/')
    return {'user': user}


@app.get('/api/auth/me')
def auth_me(request: Request):
    return {'user': _session_identity(request)}


@app.post('/api/auth/logout', status_code=204)
def logout(request: Request, response: Response):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        user_repository.revoke_session(sha256(raw.encode('utf-8')).hexdigest())
    response.delete_cookie(SESSION_COOKIE, path='/', httponly=True,
                           secure=request.url.scheme == 'https', samesite='lax')
    response.status_code = 204
    return response


@app.get('/health', include_in_schema=False)
def health():
    try:
        with engine.connect() as connection:
            connection.execute(select(Setting.name).limit(1))
    except Exception as exc:
        logger.exception('Проверка готовности базы данных завершилась ошибкой')
        raise HTTPException(status_code=503, detail='База данных недоступна') from exc
    return {'status': 'ok'}

@app.get('/', include_in_schema=False)
def index(request: Request):
    if _session_identity(request) is None:
        return FileResponse(ROOT / 'static' / 'login.html', headers={'Cache-Control':'no-store'})
    return FileResponse(ROOT / 'static' / 'index.html', headers={'Cache-Control':'no-store'})

@app.get('/api/settings')
def get_settings(request: Request):
    data = settings(request.state.user['id'])
    data['is_admin'] = request.state.user['is_admin']
    data['can_edit_global'] = request.state.user['is_admin']
    return data

@app.put('/api/settings')
def put_settings(data: Settings, request: Request):
    try:
        save(data, request.state.user['id'], is_admin=request.state.user['is_admin'])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {'ok': True}

class PluginSelection(BaseModel):
    plugin: str = Field(min_length=1,max_length=120)

@app.get('/api/chunk-plugins')
def list_chunk_plugins(request: Request):
    from src.chunk_plugins import installed_plugins
    user_id = request.state.user['id']
    return {'selected':repo.settings(user_id).get('chunking_plugin','local'),
            'plugins':installed_plugins(), 'can_edit':request.state.user['is_admin']}

@app.put('/api/chunk-plugins')
def select_chunk_plugin(data: PluginSelection, request: Request):
    import uuid
    from src.chunk_plugins import installed_plugins
    if not request.state.user['is_admin']:
        raise HTTPException(status_code=403, detail='Общие настройки может изменять только admin.')
    choice=next((item for item in installed_plugins() if item['id']==data.plugin),None)
    if choice is None or not choice['available']:
        raise HTTPException(status_code=400,detail='Плагин недоступен или не установлен.')
    repo.save_settings({'chunking_plugin':data.plugin})
    repo.log(str(uuid.uuid4()),'chunk_plugin','ok',payload={'plugin':data.plugin})
    return {'selected':data.plugin}

@app.post('/api/test/{kind}')
def test_provider(kind: str):
    if kind not in ('connection', 'embedding', 'generation'):
        raise HTTPException(status_code=404, detail='Неизвестная проверка')
    return test_call(kind)

@app.get('/api/events')
def get_events():
    return {'events': repo.events(), 'costs': repo.costs()}
@app.get('/api/documents')
def documents_list():
    from src.document_repository import list_documents
    from src.index_repository import active
    documents = list_documents()
    for document in documents:
        generation = active(document['id'])
        document['index_count'] = generation['chunk_count'] if generation else 0
    return documents

@app.get('/api/documents/{document_id}')
def document_detail(document_id: str):
    from src.document_repository import get_document
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail='Документ не найден.')
    from src.chunk_store import latest_run
    run = latest_run(document_id)
    document['chunk_count'] = len(run['chunks']) if run else 0
    return document

@app.post('/api/documents')
@app.put('/api/documents/{document_id}')
def document_write(document_id: str = '', file: UploadFile = File(...), title: str = Form(...),
                   source_type: str = Form(...), language: str = Form(...), version: str = Form(''),
                   published_at: str = Form(''), source_url: str = Form(''), git_commit: str = Form('')):
    import uuid
    from src.documents import save_document, DocumentError, MAX_BYTES
    request_id = str(uuid.uuid4())
    try:
        data = file.file.read(MAX_BYTES + 1)
        metadata = {'title': title, 'source_type': source_type, 'language': language, 'version': version,
                    'published_at': published_at, 'source_url': source_url, 'git_commit': git_commit}
        document = save_document(file.filename or '', data, metadata, request_id, document_id or None)
        if document is None:
            repo.log(request_id, 'document_replace', 'error', payload={'document_id': document_id, 'error': 'Документ не найден'})
            raise HTTPException(status_code=404, detail='Документ не найден.')
        if document_id:
            from src.indexing import cleanup_queued
            try:
                document['index_cleanup_pending'] = not cleanup_queued()
            except Exception as exc:
                repo.log(request_id, 'index_cleanup', 'error', payload={'document_id': document_id, 'error': str(exc)})
                document['index_cleanup_pending'] = True
        return document
    except DocumentError as exc:
        repo.log(request_id, 'document_replace' if document_id else 'document_upload', 'error', payload={'document_id': document_id, 'error': str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()

@app.delete('/api/documents/{document_id}')
def document_delete(document_id: str):
    import uuid
    from src.document_repository import delete_document
    request_id = str(uuid.uuid4())
    if not delete_document(document_id, request_id):
        repo.log(request_id, 'document_delete', 'error', payload={'document_id': document_id, 'error': 'Документ не найден'})
        raise HTTPException(status_code=404, detail='Документ не найден.')
    from src.indexing import cleanup_deleted_document
    try:
        cleaned = cleanup_deleted_document(document_id)
    except Exception as exc:
        repo.log(request_id, 'index_cleanup', 'error', payload={'document_id': document_id, 'error': str(exc)})
        cleaned = False
    return {'ok': True, 'index_cleanup_pending': not cleaned}
@app.post('/api/documents/{document_id}/prepare')
def document_prepare(document_id: str):
    import uuid
    from src.chunk_store import snapshot, save_run, StaleDocument
    from src.chunk_pipeline import prepare_chunks, PreparationError
    from src.chunking import bge_counter
    request_id=str(uuid.uuid4())
    source=snapshot(document_id)
    if source is None:
        raise HTTPException(status_code=404,detail='Документ не найден.')
    try:
        tokenizer=ROOT / 'data' / 'tokenizers' / 'bge-m3-tokenizer.json'
        if not tokenizer.is_file():
            raise PreparationError('Не найден локальный токенизатор BGE-M3; см. README.')
        result=prepare_chunks(source,source['filename'],source['original'],bge_counter(tokenizer),plugin=source['plugin'])
        run_id=save_run(document_id,source['revision'],result,request_id)
        return {'run_id':run_id,'plugin':result['plugin'],'count':len(result['chunks']),'warnings':result['warnings']}
    except (PreparationError, StaleDocument) as exc:
        repo.log(request_id,'document_prepare','error',payload={'document_id':document_id,'error':str(exc)})
        raise HTTPException(status_code=409 if isinstance(exc,StaleDocument) else 400,detail=str(exc)) from exc

@app.get('/api/documents/{document_id}/chunks')
def document_chunks(document_id: str, offset: int = 0, limit: int = 20):
    from src.chunk_store import latest_run
    from src.document_repository import get_document
    if get_document(document_id) is None: raise HTTPException(status_code=404,detail='Документ не найден.')
    if offset < 0 or not 1 <= limit <= 100: raise HTTPException(status_code=400,detail='Некорректная страница.')
    result=latest_run(document_id)
    if result is None: return {'count':0,'chunks':[],'warnings':[],'statistics':None}
    chunks=result.pop('chunks'); sizes=sorted(c['tokens'] for c in chunks)
    result.update({'count':len(chunks),'offset':offset,'chunks':chunks[offset:offset+limit],
                   'statistics':{'min':sizes[0] if sizes else 0,'max':sizes[-1] if sizes else 0,
                     'mean':round(sum(sizes)/len(sizes),1) if sizes else 0}})
    return result

@app.get('/api/index/status')
def index_status(request: Request):
    from src.indexing import job_status
    return job_status(request.state.user['id'])

@app.post('/api/documents/{document_id}/index')
def index_start(document_id: str):
    from src.indexing import start_job, IndexingError
    try:
        return start_job(document_id)
    except IndexingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post('/api/documents/{document_id}/prepare-and-index')
def prepare_and_index(document_id: str):
    from src.indexing import start_job, IndexingError
    try:
        return start_job(document_id, prepare=True)
    except IndexingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class ChatQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=36)

@app.get('/api/chat/history')
def chat_history(offset: int = Query(default=0, ge=0)):
    messages = repo.chat_history(limit=51, offset=offset)
    return {'messages': messages[-50:], 'has_more': len(messages) > 50}


@app.get('/api/chat/conversations')
def list_chat_conversations():
    return {'conversations': chat_repository.list_conversations()}


@app.post('/api/chat/conversations', status_code=201)
def create_chat_conversation():
    return chat_repository.create()


@app.get('/api/chat/conversations/{conversation_id}')
def get_chat_conversation(conversation_id: str):
    try:
        return chat_repository.history(conversation_id)
    except chat_repository.ConversationMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post('/api/chat')
def chat_answer(data: ChatQuestion):
    from src.rag_service import answer_question
    try:
        return answer_question(data.question, conversation_id=data.conversation_id)
    except chat_repository.ConversationMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chat_repository.ConversationChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
