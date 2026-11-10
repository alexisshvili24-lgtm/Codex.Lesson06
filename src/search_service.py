"""Поиск по снимку активных поколений документов."""
import os
from src.database import ROOT
from src.document_repository import list_documents
from src.index_repository import active
from src.indexing import _index_lock
from src.embeddings import embed_texts
from src.vector_store import VectorStore
from src.search_corpus import create_search_corpus
from src.hybrid_search import search, add_context, merge_query_results
from src.service import settings


class SearchError(ValueError):
    pass


def active_generations():
    return [generation for document in list_documents() if (generation := active(document['id']))]


def search_documents(question, *, search_groups=(), evidence_types=(), context_query='', embedder=embed_texts,
                     path=None, config=None, group_id=None):
    if not question.strip():
        raise SearchError('Введите вопрос.')
    config = config if config is not None else settings()
    before = active_generations()
    if not before:
        raise SearchError('Нет документов с актуальным индексом.')
    if _index_lock.locked():
        raise SearchError('Индекс сейчас занят. Повторите поиск чуть позже.')
    kwargs = {'config':config}
    if embedder is embed_texts: kwargs['group_id'] = group_id
    question = question.strip()
    queries = {question.casefold(): question}
    for pair in search_groups:
        for query in pair:
            queries.setdefault(query.casefold(), query)
    context_query = context_query.strip()
    context_key = context_query.casefold()
    if not context_query or context_key in queries:
        context_key = None
    else:
        queries[context_key] = context_query
    vectors = embedder(list(queries.values()), **kwargs)
    if not _index_lock.acquire(blocking=False):
        raise SearchError('Индекс сейчас занят. Повторите поиск чуть позже.')
    store = None
    corpus = None
    try:
        current = active_generations()
        signature = lambda items: sorted((x['document_id'], x['run_id'], x['collection'], x['model']) for x in items)
        if signature(before) != signature(current) or settings()['embedding_model'] != config['embedding_model']:
            raise SearchError('Индекс изменился во время поиска. Повторите запрос.')
        store = VectorStore(path or os.environ.get('QDRANT_PATH') or ROOT / 'data' / 'qdrant')
        corpus, created = create_search_corpus(store.client, [x['collection'] for x in current])
        if not created:
            raise SearchError('В активных индексах нет чанков.')
        thresholds = {
            'vector_threshold': float(config['vector_threshold']) if config['vector_enabled'] == 'true' else None,
            'bm25_threshold': float(config['bm25_threshold']) if config['bm25_enabled'] == 'true' else None,
        }
        results = {
            key: search(corpus, query, vector, candidate_limit=15 if evidence_types and key != context_key else 7,
                        **thresholds)
            for (key, query), vector in zip(queries.items(), vectors, strict=True)
        }
        result = results[question.casefold()]
        limit = 10 if search_groups else 5
        if search_groups:
            groups = [[results[query.casefold()] for query in pair] for pair in search_groups]
            nearby_corpus = corpus if all(value is None for value in thresholds.values()) else None
            result = merge_query_results(
                result, groups, limit, corpus=nearby_corpus, query_groups=search_groups, evidence_types=evidence_types,
            )
            result['query_results'] = [
                {'query': query, 'chunk_ids': [item['chunk_id'] for item in results[key]['rrf_candidates']]}
                for key, query in queries.items() if key != context_key
            ]
        if context_key is not None:
            result = add_context(result, results[context_key], context_query, limit=limit)
        if signature(current) != signature(active_generations()):
            raise SearchError('Документ изменился во время поиска. Повторите запрос.')
        return result
    finally:
        if corpus is not None:
            corpus.close()
        if store is not None:
            store.close()
        _index_lock.release()
