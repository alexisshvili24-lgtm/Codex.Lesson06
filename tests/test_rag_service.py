import unittest
from unittest.mock import patch
from pydantic import ValidationError
from src.chat_context import SearchContext
from src.rag_answer import Answer
from src.rag_service import answer_question

class RagServiceTest(unittest.TestCase):
    def setUp(self):
        planner = patch('src.rag_service.update_context', return_value=SearchContext(
            summary='', search_query='Что это?', context_query='',
            search_groups=[['Что это?', 'Как это работает?']], evidence_types=['rule'],
        ))
        self.plan = planner.start()
        self.addCleanup(planner.stop)

    @patch('src.rag_service.repo')
    @patch('src.rag_service.settings',return_value={'generation_model':'model'})
    @patch('src.rag_service.generate_answer')
    @patch('src.rag_service.search_documents')
    def test_source_snapshot_and_diagnostics_are_logged(self, search, generate, settings, repo):
        search.return_value={'vector':[], 'bm25':[], 'rrf':[{'payload':{'chunk_id':'abc','text':'Git status'}}]}
        generate.return_value=Answer(status='full',answer='Ответ [S1]',source_ids=['S1'],missing_information=[])
        result=answer_question(' Что это? ')
        self.assertEqual(result['sources'][0]['id'],'S1')
        self.assertEqual(result['sources'][0]['text'],'Git status')
        self.assertEqual(repo.log.call_args.kwargs['payload'],result)
        self.plan.assert_called_once()
        self.assertEqual(search.call_args.kwargs['search_groups'], [['Что это?', 'Как это работает?']])
        self.assertEqual(search.call_args.kwargs['evidence_types'], ['rule'])
        self.assertEqual(generate.call_args.args[0], 'Что это?')
    @patch('src.rag_service.repo')
    @patch('src.rag_service.settings',return_value={'generation_model':'model'})
    @patch('src.rag_service.generate_answer')
    @patch('src.rag_service.search_documents',return_value={'vector':[], 'bm25':[], 'rrf':[]})
    def test_empty_results_pass_no_sources(self, search, generate, settings, repo):
        generate.return_value=Answer(status='no_answer',answer='Не найдено',source_ids=[],missing_information=[])
        answer_question('Вопрос')
        self.assertEqual(generate.call_args.args[1],[])

    @patch('src.rag_service.repo')
    @patch('src.rag_service.settings', return_value={'generation_model':'model'})
    @patch('src.rag_service.generate_answer', side_effect=ValueError('Ошибка API'))
    @patch('src.rag_service.search_documents')
    def test_failed_generation_keeps_retrieval_snapshot(self, search, generate, settings, repo):
        search.return_value={'vector':[], 'bm25':[], 'rrf':[{'payload':{'chunk_id':'abc','text':'Git status'}}]}
        with self.assertRaisesRegex(ValueError, 'Ошибка API'):
            answer_question('Вопрос')
        self.assertEqual(repo.log.call_args.args[2], 'error')
        self.assertEqual(repo.log.call_args.kwargs['payload']['sources'][0]['text'], 'Git status')


class SearchContextSchemaTest(unittest.TestCase):
    def test_each_group_requires_two_nonempty_strings_and_forbids_extra_fields(self):
        base = {'summary': '', 'search_query': 'Git', 'context_query': '', 'evidence_types': ['rule']}
        for groups in ([], ['a', 'b'], [['a']], [['a', 'b', 'c']], [['a', 3]], [['a', ' ']]):
            with self.subTest(groups=groups), self.assertRaises(ValidationError):
                SearchContext.model_validate({**base, 'search_groups': groups})
        with self.assertRaises(ValidationError):
            SearchContext.model_validate({**base, 'search_groups': [['a', 'b']], 'unexpected': True})
        for kinds in (['invalid'], ['rule', 'command']):
            with self.subTest(kinds=kinds), self.assertRaises(ValidationError):
                SearchContext.model_validate({**base, 'search_groups': [['a', 'b']], 'evidence_types': kinds})
