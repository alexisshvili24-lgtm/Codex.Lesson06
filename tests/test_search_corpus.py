import unittest
from qdrant_client import QdrantClient, models
from src.search_corpus import create_search_corpus

class CorpusTest(unittest.TestCase):
    def test_combines_documents_and_retains_sources_for_both_channels(self):
        source=QdrantClient(':memory:')
        try:
            for name,ident,text,vector in [('one',1,'git reset --hard',[1.,0.]),('two',2,'git status ветка',[0.,1.])]:
                source.create_collection(name,vectors_config=models.VectorParams(size=2,distance=models.Distance.COSINE))
                source.upsert(name,[models.PointStruct(id=ident,vector=vector,payload={
                    'text':text,'document_id':name,'section':'Индексирование' if name == 'two' else ''
                })])
            corpus,created=create_search_corpus(source,['one','two'])
            try:
                self.assertTrue(created)
                self.assertEqual(corpus.count('corpus',exact=True).count,2)
                self.assertEqual(corpus.query_points('corpus',query=[1.,0.]).points[0].id,1)
                self.assertEqual(corpus.query_points('corpus',query=models.TextQuery(text='ветка'),using='lexical_text').points[0].id,2)
                self.assertEqual(corpus.query_points('corpus',query=models.TextQuery(text='Индексирование'),using='lexical_text').points[0].id,2)
            finally:corpus.close()
        finally:source.close()

    def test_bm25_distinguishes_git_flag_from_word_and_longer_flag(self):
        from src.hybrid_search import search
        source=QdrantClient(':memory:')
        try:
            source.create_collection('one',vectors_config=models.VectorParams(size=2,distance=models.Distance.COSINE))
            texts=['Объяснение: `--hard`, далее текст.', 'Hard reset', 'Флаг --harder']
            source.upsert('one',[models.PointStruct(id=i,vector=[1.,0.],payload={'text':t,'chunk_id':str(i)}) for i,t in enumerate(texts)])
            corpus,_=create_search_corpus(source,['one'])
            try:
                hits=search(corpus,'`--hard`?',[1.,0.])['bm25']
                self.assertEqual([hit['chunk_id'] for hit in hits], ['0'])
                self.assertEqual(hits[0]['payload']['text'], texts[0])
                self.assertNotIn('lexical_text', hits[0]['payload'])
            finally:corpus.close()
        finally:source.close()
