"""Объединение отфильтрованных результатов двух поисковых каналов."""

def fuse(vector_results, bm25_results, limit=5, k=60):
    """Применяет RRF к исходным позициям, сохраняя вклад обоих каналов."""
    combined = {}
    for channel, results in (('vector', vector_results), ('bm25', bm25_results)):
        seen = set()
        for result in results:
            chunk_id = result['chunk_id']
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            if not result['accepted']:
                continue
            position = result['position']
            if not isinstance(position, int) or isinstance(position, bool) or position < 1:
                raise ValueError('Позиция результата должна быть положительным целым числом.')
            entry = combined.setdefault(chunk_id, {'chunk_id': chunk_id, 'score': 0.0, 'vector_position': None, 'bm25_position': None})
            entry[channel + '_position'] = position
            entry['score'] += 1.0 / (k + position)
    return sorted(combined.values(), key=lambda entry: (-entry['score'], entry['chunk_id']))[:limit]
