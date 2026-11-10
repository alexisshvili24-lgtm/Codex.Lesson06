import unittest
from qdrant_client import QdrantClient, models
from src.hybrid_search import search
from src.search_corpus import create_search_corpus

class HybridSearchTest(unittest.TestCase):
    def test_thresholds_preserve_original_ranks_and_unify_sources(self):
        client=QdrantClient(':memory:')
        corpus=None
        try:
            client.create_collection('corpus',vectors_config=models.VectorParams(size=2,distance=models.Distance.COSINE))
            client.upsert('corpus',[
                models.PointStruct(id=1,vector=[1.,0.],payload={'chunk_id':'a','text':'git ветка'}),
                models.PointStruct(id=2,vector=[0.,1.],payload={'chunk_id':'b','text':'git status'}),
            ])
            corpus,_=create_search_corpus(client,['corpus'])
            result=search(corpus,'status',[1.,0.],vector_threshold=.5,bm25_threshold=None)
            self.assertEqual([r['chunk_id'] for r in result['rrf']],['a','b'])
            self.assertFalse(result['vector'][1]['accepted'])
            self.assertEqual(result['rrf'][1]['bm25_position'],1)
            self.assertEqual(result['rrf'][1]['payload']['text'],'git status')
        finally:
            if corpus is not None: corpus.close()
            client.close()

    def test_empty_query_rejected(self):
        with self.assertRaises(ValueError):search(None,'  ',[1.])


class ContextRankingTest(unittest.TestCase):
    @staticmethod
    def results(ids):
        ranked = [{'chunk_id': chunk_id, 'score': 10 - i, 'included': True} for i, chunk_id in enumerate(ids)]
        return {'rrf': ranked, 'rrf_candidates': ranked, 'vector': [], 'bm25': []}

    def test_context_is_last_and_never_duplicates_or_replaces_primary_search(self):
        from src.hybrid_search import add_context
        primary = self.results(['a', 'b', 'c', 'd', 'e'])
        result = add_context(primary, self.results(['a', 'e', 'f', 'g']), 'контекст')
        self.assertEqual([item['chunk_id'] for item in result['rrf']], ['a', 'b', 'c', 'd', 'f'])
        self.assertEqual(result['rrf'][-1]['retrieval_role'], 'context')
        self.assertFalse(result['rrf_candidates'][-1]['included'])
        self.assertEqual([item['chunk_id'] for item in result['context']['rrf']], ['f'])

        duplicates = add_context(primary, self.results(['e', 'a']), 'контекст')
        self.assertEqual([item['chunk_id'] for item in duplicates['rrf']], ['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(add_context(self.results([]), self.results(['f']), 'контекст')['rrf'], [])

    def test_subquestions_keep_places_when_other_queries_repeat_the_same_candidates(self):
        from src.hybrid_search import merge_query_results
        original = self.results(['a', 'b', 'c', 'd'])
        groups = [[self.results(['a', 'b']), self.results(['a', 'b'])],
                  [self.results(['f', 'g']), self.results(['h', 'f'])]]
        result = merge_query_results(original, groups, 4)
        self.assertEqual([item['chunk_id'] for item in result['rrf']], ['a', 'b', 'f', 'h'])
        self.assertEqual(sum(item['included'] for item in result['rrf_candidates']), 4)

    def test_command_boost_requires_related_words_near_command(self):
        from src.search_evidence import rank_evidence
        candidates = [
            {'chunk_id': 'prose', 'payload': {'text': 'Последние два коммита и их патчи.'}},
            {'chunk_id': 'unrelated', 'payload': {'text': 'Теги\n$ git tag v2.0'}},
            {'chunk_id': 'command', 'payload': {'text': 'Патчи двух последних коммитов\n$ git log -p -2'}},
        ]
        ranked = rank_evidence(None, candidates, ['Патчи двух последних коммитов', 'Git last two commits patch'], 'command')
        self.assertEqual([item['chunk_id'] for item in ranked], ['command', 'prose', 'unrelated'])

    def test_output_fallback_stays_in_same_document_and_section(self):
        from src.search_evidence import rank_evidence
        source = QdrantClient(':memory:')
        try:
            source.create_collection('corpus', vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
            anchor = {'chunk_id': 'a', 'document_id': 'doc', 'source_file': 'status.md',
                      'section': 'Вывод', 'chunk_index': 5, 'text': 'Формат состояния.'}
            points = [
                {**anchor, 'chunk_id': 'b', 'chunk_index': 6, 'section': 'Другой', 'text': '?? file'},
                {**anchor, 'chunk_id': 'c', 'chunk_index': 8, 'text': '!! ignored.log'},
                {**anchor, 'chunk_id': 'd', 'chunk_index': 9, 'text': '!! distant.log'},
            ]
            source.upsert('corpus', [models.PointStruct(id=i, vector=[1., 0.], payload=payload)
                                     for i, payload in enumerate(points)])
            ranked = rank_evidence(source, [{'chunk_id': 'a', 'payload': anchor}], ['Вывод git status'], 'output')
            self.assertEqual([item['chunk_id'] for item in ranked], ['c', 'a'])
            self.assertEqual(ranked[0]['neighbor_of'], 'a')
        finally:
            source.close()

    def test_matching_count_can_rescue_a_low_ranked_command(self):
        from src.search_evidence import rank_evidence
        candidates = [
            {'chunk_id': str(i), 'payload': {'text': 'Просмотр коммитов\n$ git log --since=2.weeks'}}
            for i in range(18)
        ]
        candidates.append({'chunk_id': 'exact', 'payload': {'text': 'Патчи двух последних коммитов\n$ git log -p -2'}})
        ranked = rank_evidence(None, candidates, ['Патчи двух последних коммитов', 'Git last two commits patch'], 'command')
        self.assertEqual(ranked[0]['chunk_id'], 'exact')
