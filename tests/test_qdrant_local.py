import unittest
import uuid
from pathlib import Path
from qdrant_client import QdrantClient, models


class QdrantLocalTest(unittest.TestCase):
    def test_persistent_vectors_bm25_and_rrf(self):
        path = Path(__file__).resolve().parents[1] / '.tmp' / ('qdrant-test-' + uuid.uuid4().hex)
        client = QdrantClient(path=str(path))
        try:
            client.create_collection('documents', vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
            client.create_payload_index('documents', 'text', models.TextIndexParams(type='text', scoring=True))
            client.upsert('documents', [
                models.PointStruct(id=1, vector=[1, 0, 0], payload={'text': 'ветка git ветка merge'}),
                models.PointStruct(id=2, vector=[0, 1, 0], payload={'text': 'git status рабочее дерево'}),
            ])
        finally:
            client.close()
        client = QdrantClient(path=str(path))
        try:
            dense = client.query_points('documents', query=[1, 0, 0], limit=2).points
            russian = client.query_points('documents', query=models.TextQuery(text='ветка'), using='text', limit=2).points
            english = client.query_points('documents', query=models.TextQuery(text='status'), using='text', limit=2).points
            combined = client.query_points('documents', prefetch=[
                models.Prefetch(query=[1, 0, 0], limit=2),
                models.Prefetch(query=models.TextQuery(text='status'), using='text', limit=2),
            ], query=models.FusionQuery(fusion=models.Fusion.RRF), limit=2).points
            self.assertEqual([p.id for p in dense], [1, 2])
            self.assertEqual(russian[0].id, 1)
            self.assertEqual(english[0].id, 2)
            self.assertEqual({p.id for p in combined}, {1, 2})
        finally:
            client.close()

    def test_exact_option_requires_substring_filter(self):
        client=QdrantClient(':memory:')
        try:
            client.create_collection('docs',vectors_config=models.VectorParams(size=2,distance=models.Distance.COSINE))
            client.create_payload_index('docs','text',models.TextIndexParams(type='text',scoring=True))
            client.upsert('docs',[
                models.PointStruct(id=1,vector=[1,0],payload={'text':'git reset --hard HEAD'}),
                models.PointStruct(id=2,vector=[0,1],payload={'text':'this task is hard'}),
            ])
            scored=client.query_points('docs',query=models.TextQuery(text='--hard'),using='text').points
            self.assertEqual({point.id for point in scored},{1,2})
            condition=models.Filter(must=[models.FieldCondition(key='text',match=models.MatchSubstring(substring='--hard'))])
            exact=client.scroll('docs',scroll_filter=condition)[0]
            self.assertEqual([point.id for point in exact],[1])
        finally:client.close()
