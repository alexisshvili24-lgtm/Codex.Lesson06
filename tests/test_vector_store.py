import unittest
import uuid
from pathlib import Path
from qdrant_client import models
from src.vector_store import VectorStore

class VectorStoreTest(unittest.TestCase):
    def test_persistence_metadata_and_idempotence(self):
        path = Path(__file__).resolve().parents[1] / '.tmp' / ('vector-store-' + uuid.uuid4().hex)
        store = VectorStore(path)
        chunks = [{'chunk_id': 'abc', 'text': 'git ветка', 'document_id': 'd', 'source_file': 'x.asc'},
                  {'chunk_id': 'def', 'text': 'git status', 'document_id': 'd', 'source_file': 'y.asc'}]
        try:
            collection = store.create(3)
            store.add(collection, chunks, [[1.,0.,0.],[0.,1.,0.]])
            store.add(collection, chunks, [[1.,0.,0.],[0.,1.,0.]])
            self.assertEqual(store.count(collection), 2)
        finally:
            store.close()
        store = VectorStore(path)
        try:
            points = store.client.query_points(collection, query=[1.,0.,0.], with_payload=True).points
            self.assertEqual(points[0].payload, chunks[0])
            self.assertEqual(store.client.query_points(collection, query=models.TextQuery(text='ветка'), using='text').points[0].payload, chunks[0])
        finally:
            store.close()

    def test_rejects_unequal_lengths(self):
        store=VectorStore(':memory:')
        try:
            collection=store.create(3)
            with self.assertRaises(ValueError): store.add(collection,[{'chunk_id':'a'}],[])
        finally:
            store.close()
