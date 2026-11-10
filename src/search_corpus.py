"""Подготовка общего поискового представления активных документов."""
import re
from qdrant_client import QdrantClient, models


LEXICAL_FIELD = 'lexical_text'
SECTION_FIELDS = ('chapter', 'section', 'subsection')
_GIT_OPTION = re.compile(r'(?<![\w-])--[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*')

def lexical_text(text):
    """Кодирует длинные опции Git одним словом для токенизатора Qdrant Local."""
    return _GIT_OPTION.sub(lambda match: ' gitflag' + match[0].encode('ascii').hex() + ' ', text)


def section_title(payload):
    return ' '.join(payload[field] for field in SECTION_FIELDS if payload.get(field))


def create_search_corpus(source, collections):
    """Создаёт временную общую коллекцию без изменения постоянного индекса."""
    target = QdrantClient(':memory:')
    created = False
    try:
        for collection in collections:
            offset = None
            while True:
                points, offset = source.scroll(collection, offset=offset, limit=128, with_payload=True, with_vectors=True)
                if points and not created:
                    size = len(points[0].vector)
                    target.create_collection('corpus', vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE))
                    target.create_payload_index('corpus', LEXICAL_FIELD, models.TextIndexParams(type='text', scoring=True))
                    created = True
                if points:
                    target.upsert('corpus', [
                        models.PointStruct(id=point.id, vector=point.vector, payload={
                            **point.payload,
                            LEXICAL_FIELD: lexical_text(section_title(point.payload) + '\n' + point.payload['text']),
                        }) for point in points
                    ])
                if offset is None:
                    break
        return target, created
    except Exception:
        target.close()
        raise
