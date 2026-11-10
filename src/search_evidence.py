"""Локальный отбор фрагментов с командой, выводом или объяснением."""
import re
from qdrant_client import models
from src.search_corpus import LEXICAL_FIELD, SECTION_FIELDS, section_title


_WORDS = re.compile(r'[^\W_]+')
_STOP = set((
    'git как какой какую какие для или что чтобы это его при где чем них из каковы '
    'how what which when for with the and from into does using use'
).split())
_COMMAND = re.compile(r'(?:^\s*(?:[$>]\s*)?|\x60)(git[ \t]+[a-z][\w-]*(?:[ \t]+[^\x60]+)?)')
_FLAGS = re.compile(r'(?<![\w-])--?[a-zA-Z0-9][\w-]*(?=$|[\s=.,?;:!\x60)\]])')
_OUTPUT = re.compile(
    r'^\s*(?:[MADRCU?!]{2}(?=\s)|would remove\b|changes (?:to be committed|not staged)\b|gpg:|fatal:|error:)'
    r'|\x60(?:!!|\?\?|[MADRCU]{2})\x60', re.MULTILINE | re.IGNORECASE,
)
_RULE = re.compile(r'\b(?:если|когда|означает|позволяет|нельзя|if|when|means|unless|requires)\b', re.IGNORECASE)
_NUMBERS = {
    word: str(number)
    for number, words in enumerate((
        'ноль zero', 'один одна one', 'два двух две two', 'три трёх трех three', 'четыре четырёх четырех four',
        'пять пяти five', 'шесть шести six', 'семь семи seven', 'восемь восьми eight', 'девять девяти nine',
        'десять десяти ten',
    ))
    for word in words.split()
}


def _terms(text):
    terms = set()
    for word in _WORDS.findall(text.casefold()):
        if word in _STOP or len(word) < 3 and not word.isdigit():
            continue
        if word in _NUMBERS:
            terms.add(_NUMBERS[word])
        elif word.startswith(('патч', 'patch')):
            terms.add('patch')
        else:
            terms.add(word[:5])
    return terms


def _evidence(payload, terms, requested_flags, kind):
    text = payload['text']
    title = section_title(payload)
    if kind == 'command':
        lines = text.splitlines()
        related = False
        for index, line in enumerate(lines):
            match = _COMMAND.search(line)
            if not match:
                continue
            command = _terms(match[1])
            nearby = _terms(' '.join(lines[max(0, index - 2):index + 3]) + ' ' + title)
            if terms & command and len(terms & nearby) >= 2:
                if requested_flags.intersection(_FLAGS.findall(match[1])):
                    return True, 4
                related = True
        return False, 4 if related else 0
    if len(terms & _terms(title + ' ' + text)) < 2:
        return False, 0
    if kind == 'output':
        return False, 4 if _OUTPUT.search(text) else 0
    return False, 2 if _RULE.search(text) else 0


def _nearby_output(corpus, anchor):
    payload = anchor['payload']
    number = payload.get('chunk_index')
    if not payload.get('document_id') or not payload.get('source_file') or type(number) is not int:
        return None
    points, _ = corpus.scroll(
        'corpus',
        scroll_filter=models.Filter(must=[
            models.FieldCondition(key=field, match=models.MatchValue(value=payload[field]))
            for field in ('document_id', 'source_file')
        ] + [models.FieldCondition(key='chunk_index', range=models.Range(gte=number - 3, lte=number + 3))]),
        limit=7, with_payload=models.PayloadSelectorExclude(exclude=[LEXICAL_FIELD]), with_vectors=False,
    )
    candidates = [
        point.payload for point in points
        if point.payload['chunk_id'] != anchor['chunk_id']
        and all(point.payload.get(field) == payload.get(field) for field in SECTION_FIELDS)
        and _OUTPUT.search(point.payload['text'])
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (abs(item['chunk_index'] - number), item['chunk_index']))
    return {'chunk_id': best['chunk_id'], 'payload': best, 'score': 0.0,
            'vector_position': None, 'bm25_position': None, 'neighbor_of': anchor['chunk_id']}


def rank_evidence(corpus, candidates, queries, kind):
    terms = _terms(' '.join(queries))
    requested_flags = set(_FLAGS.findall(queries[0]))
    requested_flags.update(f'-{term}' for term in _terms(queries[0]) if term.isdigit())
    positions = [(index, *_evidence(item['payload'], terms, requested_flags, kind), item)
                 for index, item in enumerate(candidates)]
    ranked = [item for _, _, _, item in sorted(
        positions, key=lambda entry: (not entry[1], entry[0] - entry[2], entry[0]),
    )]
    if corpus is not None and kind == 'output' and positions and not any(bonus for _, _, bonus, _ in positions):
        neighbor = _nearby_output(corpus, ranked[0])
        if neighbor:
            ranked = [neighbor] + [item for item in ranked if item['chunk_id'] != neighbor['chunk_id']]
    return ranked
