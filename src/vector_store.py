"""Изолированное хранилище векторов для подготовленных поколений индекса."""
from pathlib import Path
import uuid
from qdrant_client import QdrantClient, models


class VectorStore:
    def __init__(self, path):
        self.client = QdrantClient(path=str(Path(path)))

    def close(self):
        self.client.close()

    def create(self, dimension, name=None):
        name = name or 'generation_' + uuid.uuid4().hex
        self.client.create_collection(name, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE))
        try:
            self.client.create_payload_index(name, 'text', models.TextIndexParams(type='text', scoring=True))
        except Exception:
            self.client.delete_collection(name)
            raise
        return name

    def add(self, collection, chunks, vectors):
        if not chunks or len(chunks) != len(vectors):
            raise ValueError('Количество чанков и векторов должно совпадать.')
        ids = [chunk['chunk_id'] for chunk in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError('Обнаружены повторяющиеся идентификаторы чанков.')
        points = [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk['chunk_id'])), vector=vector, payload=chunk)
                  for chunk, vector in zip(chunks, vectors)]
        self.client.upsert(collection, points, wait=True)

    def count(self, collection):
        return self.client.count(collection, exact=True).count

    def remove(self, collection):
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection)
