"""Ручная индексация документа с проверкой перед публикацией результата."""
from pathlib import Path
import threading
import time
import os
import uuid
from src.database import ROOT
from src.chunk_store import snapshot, latest_run
from src.embeddings import embed_texts, EmbeddingError
from src.index_repository import active, activate, run_chunk_ids, register_pending, pending_collections, pending_is_unreferenced, forget_pending
from src.service import settings, repo
from src.request_context import request_context_snapshot, set_user_id, reset_user_id
from src.vector_store import VectorStore

_index_lock = threading.Lock()

class IndexingError(ValueError):
    pass


def cleanup_pending(store, request_id):
    for collection in pending_collections():
        if not pending_is_unreferenced(collection):
            continue
        try:
            store.remove(collection)
            forget_pending(collection)
        except Exception as exc:
            repo.log(request_id, 'index_cleanup', 'error', payload={'collection':collection, 'error':str(exc)})


def index_document(document_id, *, path=None, embedder=embed_texts, progress=None):
    if not _index_lock.acquire(blocking=False):
        raise IndexingError('Другая индексация уже выполняется.')
    request_id = str(uuid.uuid4())
    store = None
    collection = None
    published = False
    try:
        source = snapshot(document_id)
        run = latest_run(document_id)
        if source is None:
            raise IndexingError('Документ не найден.')
        if run is None or not run['chunks']:
            raise IndexingError('Сначала подготовьте актуальные чанки документа.')
        conf = settings()
        model = conf['embedding_model']
        existing = active(document_id)
        store = VectorStore(path or os.environ.get('QDRANT_PATH') or ROOT / 'data' / 'qdrant')
        cleanup_pending(store, request_id)
        if existing and existing['chunk_count'] == len(run['chunks']) and run_chunk_ids(existing['run_id']) == [chunk['chunk_id'] for chunk in run['chunks']]:
            if store.client.collection_exists(existing['collection']) and store.count(existing['collection']) == len(run['chunks']):
                if existing['run_id'] != run['run_id']:
                    activate(document_id, run['run_id'], source['revision'], model, existing['collection'], len(run['chunks']))
                repo.log(request_id, 'index', 'ok', model, payload={'document_id':document_id, 'reused':True, 'chunks':len(run['chunks'])})
                return {'status':'unchanged', 'chunks':len(run['chunks'])}
        chunks = run['chunks']
        if progress: progress(0, len(chunks))
        for offset in range(0, len(chunks), 16):
            batch = chunks[offset:offset+16]
            kwargs = {'config': conf}
            if embedder is embed_texts: kwargs['group_id'] = request_id
            for attempt in range(3):
                try:
                    vectors = embedder([chunk['text'] for chunk in batch], **kwargs)
                    break
                except EmbeddingError as exc:
                    if 'HTTP 503' not in str(exc) or attempt == 2:
                        raise
                    repo.log(request_id, 'index_retry', 'error', model, payload={'document_id':document_id, 'attempt':attempt+1, 'error':str(exc)})
                    time.sleep(attempt + 1)
            if collection is None:
                collection = 'generation_' + uuid.uuid4().hex
                register_pending(document_id, collection)
                store.create(len(vectors[0]), name=collection)
            store.add(collection, batch, vectors)
            if progress: progress(min(offset + len(batch), len(chunks)), len(chunks))
        if store.count(collection) != len(chunks):
            raise IndexingError('Число сохранённых векторов не соответствует числу чанков.')
        old = activate(document_id, run['run_id'], source['revision'], model, collection, len(chunks))
        published = True
        if old and old != collection:
            try:
                store.remove(old)
                forget_pending(old)
            except Exception as exc:
                repo.log(request_id, 'index_cleanup', 'error', model, payload={'document_id':document_id, 'collection':old, 'error':str(exc)})
        repo.log(request_id, 'index', 'ok', model, payload={'document_id':document_id, 'collection':collection, 'chunks':len(chunks)})
        return {'status':'indexed', 'chunks':len(chunks), 'expenses':repo.embedding_group_cost(request_id)}
    except Exception as exc:
        expenses = repo.embedding_group_cost(request_id)
        repo.log(request_id, 'index', 'error', payload={'document_id':document_id, 'error':str(exc), 'expenses':expenses})
        try:
            exc.index_expenses = expenses
        except (AttributeError, TypeError):
            pass
        raise
    finally:
        try:
            if store is not None:
                try:
                    if collection and not published:
                        store.remove(collection)
                        forget_pending(collection)
                except Exception as exc:
                    repo.log(request_id, 'index_cleanup', 'error', payload={'document_id':document_id, 'collection':collection, 'error':str(exc)})
                finally:
                    store.close()
        finally:
            _index_lock.release()
        # Отложенная очистка удалённых документов выполняется после освобождения блокировки.
        try:
            from src.index_repository import deleted_document_ids
            for deleted_id in deleted_document_ids():
                try:
                    cleanup_deleted_document(deleted_id, path=path)
                except Exception as exc:
                    repo.log(request_id, 'index_cleanup', 'error', payload={'document_id':deleted_id, 'error':str(exc)})
        except Exception as exc:
            repo.log(request_id, 'index_cleanup', 'error', payload={'error':str(exc)})


_job_lock = threading.Lock()
_job = {'state':'idle'}

def job_status(user_id=None):
    from src.request_context import current_user_id
    owner_id = user_id if user_id is not None else current_user_id()
    with _job_lock:
        state = dict(_job)
        job_owner = state.get('owner_id')
    state.pop('owner_id', None)
    if job_owner is not None and job_owner != owner_id:
        state.pop('expenses', None)
        if isinstance(state.get('result'), dict):
            state['result'] = dict(state['result'])
            state['result'].pop('expenses', None)
    if state.get('state') == 'idle':
        last = repo.last_index_job()
        if last and last['status'] == 'running':
            return {'state':'interrupted', 'document_id':last['payload']['document_id'],
                    'error':'Сервер остановился во время индексации. Запустите её повторно.'}
    return state

def start_job(document_id, *, prepare=False):
    owner_id, owner_key, owner_key_version = request_context_snapshot()
    with _job_lock:
        if _job.get('state') == 'running':
            raise IndexingError('Другая индексация уже выполняется.')
        job_id = str(uuid.uuid4())
        repo.log(job_id, 'index_job', 'running', payload={'document_id':document_id})
        _job.clear()
        _job.update(state='running', document_id=document_id, completed=0, total=0,
                    phase='preparing' if prepare else 'indexing', owner_id=owner_id)
    def progress(completed, total):
        with _job_lock:
            _job.update(phase='indexing', completed=completed, total=total)
    def worker():
        context_token = set_user_id(owner_id or 1, owner_key, owner_key_version)
        try:
            warnings = []
            if prepare:
                from src.chunk_store import save_run
                from src.chunk_pipeline import prepare_chunks
                from src.chunking import bge_counter
                source = snapshot(document_id)
                if source is None:
                    raise IndexingError('Документ не найден.')
                prepared = prepare_chunks(source, source['filename'], source['original'],
                                          bge_counter(ROOT / 'data' / 'tokenizers' / 'bge-m3-tokenizer.json'),
                                          plugin=source['plugin'])
                save_run(document_id, source['revision'], prepared, job_id)
                warnings = prepared['warnings']
            result = index_document(document_id, progress=progress)
            result['warnings'] = warnings
            repo.log(job_id, 'index_job', 'ok', payload={'document_id':document_id, 'result':result})
            with _job_lock:
                _job.update(state='completed', result=result)
        except Exception as exc:
            repo.log(job_id, 'index_job', 'error', payload={'document_id':document_id, 'error':str(exc)})
            with _job_lock:
                _job.update(state='error', error=str(exc), expenses=getattr(exc, 'index_expenses', None))
        finally:
            reset_user_id(context_token)
    threading.Thread(target=worker, daemon=True).start()
    return job_status(owner_id)


def cleanup_deleted_document(document_id, *, path=None):
    """Удаляет только коллекцию, связанную с уже удалённым документом."""
    from src.index_repository import retired_collection, forget_retired
    if not _index_lock.acquire(blocking=False):
        return False
    try:
        name = retired_collection(document_id)
        if name is None:
            return True
        store = VectorStore(path or os.environ.get('QDRANT_PATH') or ROOT / 'data' / 'qdrant')
        try:
            store.remove(name)
        finally:
            store.close()
        forget_retired(document_id, name)
        return True
    finally:
        _index_lock.release()


def cleanup_queued(*, path=None):
    """Повторяет очистку зарегистрированных неактивных поколений."""
    if not _index_lock.acquire(blocking=False):
        return False
    try:
        if not pending_collections():
            return True
        store = VectorStore(path or os.environ.get('QDRANT_PATH') or ROOT / 'data' / 'qdrant')
        try:
            cleanup_pending(store, str(uuid.uuid4()))
        finally:
            store.close()
        return not pending_collections()
    finally:
        _index_lock.release()
