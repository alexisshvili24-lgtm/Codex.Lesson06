"""Два канала поиска, независимые пороги и объединение RRF."""
from itertools import zip_longest
from qdrant_client import models
from src.rrf import fuse
from src.search_corpus import LEXICAL_FIELD, lexical_text
from src.search_evidence import rank_evidence


def search(corpus, question, vector, *, vector_threshold=None, bm25_threshold=None, candidate_limit=7):
    if not question.strip() or not vector:
        raise ValueError('Для поиска нужны вопрос и его embedding.')
    payload = models.PayloadSelectorExclude(exclude=[LEXICAL_FIELD])
    dense = corpus.query_points('corpus', query=vector, limit=candidate_limit, with_payload=payload).points
    query = lexical_text(question)
    lexical = corpus.query_points('corpus', query=models.TextQuery(text=query), using=LEXICAL_FIELD, limit=candidate_limit, with_payload=payload).points if query else []

    def prepare(points, threshold):
        results = []
        for position, point in enumerate(points, 1):
            accepted = threshold is None or point.score >= threshold
            results.append({'chunk_id':point.payload['chunk_id'], 'position':position,
                            'score':point.score, 'accepted':accepted,
                            'threshold':threshold, 'payload':point.payload,
                            'reason':'threshold_disabled' if threshold is None else ('meets_threshold' if accepted else 'below_threshold')})
        return results

    vector_results = prepare(dense, vector_threshold)
    bm25_results = prepare(lexical, bm25_threshold)
    candidates = fuse(vector_results, bm25_results, limit=2 * candidate_limit)
    merged = candidates[:5]
    payloads = {result['chunk_id']:result['payload'] for result in vector_results + bm25_results}
    for position, result in enumerate(candidates, 1):
        result['included'] = position <= 5
        result['payload'] = payloads[result['chunk_id']]
    return {'vector':vector_results, 'bm25':bm25_results, 'rrf':merged, 'rrf_candidates':candidates}


def _merge_ranks(rankings):
    """Учитывает лучшую позицию чанка, при равенстве предпочитает ранний запрос."""
    candidates = {}
    for row in zip_longest(*rankings):
        for item in row:
            if item is not None:
                candidates.setdefault(item['chunk_id'], item)
    return candidates


def merge_query_results(primary, groups, limit, *, corpus=None, query_groups=(), evidence_types=()):
    """Оставляет первый результат исходного запроса и место для каждой части."""
    ranked_groups = [
        list(_merge_ranks([result['rrf_candidates'] for result in pair]).values())
        for pair in groups
    ]
    if evidence_types:
        ranked_groups = [
            rank_evidence(corpus, ranked, queries, kind)
            for ranked, queries, kind in zip(ranked_groups, query_groups, evidence_types, strict=True)
        ]
    original = primary['rrf_candidates']
    candidates = _merge_ranks([original, *ranked_groups])
    selected = [original[0]['chunk_id']] if original else []
    for ranked in ranked_groups:
        chunk_id = next((item['chunk_id'] for item in ranked if item['chunk_id'] not in selected), None)
        if chunk_id is not None:
            selected.append(chunk_id)
    selected = (selected + [chunk_id for chunk_id in candidates if chunk_id not in selected])[:limit]
    selected_ids = set(selected)
    ordered = selected + [chunk_id for chunk_id in candidates if chunk_id not in selected_ids]
    diagnostics = [
        {**candidates[chunk_id], 'included': chunk_id in selected_ids}
        for chunk_id in ordered
    ]
    return {**primary, 'rrf': diagnostics[:len(selected)], 'rrf_candidates': diagnostics}


def add_context(primary, supporting, query, *, limit=5):
    """Резервирует одно место для нового источника из дополнительного поиска."""
    main_ids = {item['chunk_id'] for item in primary['rrf']}
    extra = next((item for item in supporting['rrf'] if item['chunk_id'] not in main_ids), None) if main_ids else None
    main = primary['rrf'][:limit - 1] if extra is not None else primary['rrf']
    main_ids = {item['chunk_id'] for item in main}
    extra_id = extra['chunk_id'] if extra is not None else None
    main_candidates = [{**item, 'included': item['chunk_id'] in main_ids} for item in primary['rrf_candidates']]
    context_candidates = [{**item, 'included': item['chunk_id'] == extra_id} for item in supporting['rrf_candidates']]
    selected = [{**item, 'retrieval_role': 'primary'} for item in main]
    if extra is not None:
        selected.append({**extra, 'retrieval_role': 'context'})
    return {
        **primary, 'rrf': selected, 'rrf_candidates': main_candidates,
        'context': {**supporting, 'query': query, 'rrf_candidates': context_candidates,
                    'rrf': [item for item in context_candidates if item['included']]},
    }
