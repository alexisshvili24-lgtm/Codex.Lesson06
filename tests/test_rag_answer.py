import unittest
from unittest.mock import patch
from pydantic import ValidationError
from src.rag_answer import validate_answer, generate_answer

class RagAnswerTest(unittest.TestCase):
    def test_accepts_matching_citations(self):
        a=validate_answer('{"status":"full","answer":"Ответ [S1]","source_ids":["S1"],"missing_information":[]}',{'S1'})
        self.assertEqual(a.status,'full')
    def test_rejects_unavailable_and_mismatched_citations(self):
        for raw in ['{"status":"full","answer":"Ответ [S2]","source_ids":["S2"],"missing_information":[]}', '{"status":"full","answer":"Ответ [S1]","source_ids":[],"missing_information":[]}']:
            with self.assertRaises(ValueError): validate_answer(raw,{'S1'})
    def test_empty_context_does_not_call_model(self):
        result=generate_answer('Вопрос',[],{})
        self.assertEqual(result.status,'no_answer')

    @patch('src.rag_answer.repo')
    @patch('src.rag_answer.routerai.cost', return_value=(None, None))
    @patch('src.rag_answer.routerai.request_json')
    @patch('src.rag_answer.api_key', return_value='secret-key')
    def test_generation_records_request_response_and_masks_key(self, env, request, cost, repo):
        request.return_value = ({'choices':[{'message':{'content':'{"status":"full","answer":"Ответ [S1]","source_ids":["S1"],"missing_information":[]}'}}], 'usage':{'total_tokens':10}}, 'gen-id')
        config={'generation_model':'test', 'system_prompt':'prompt secret-key', 'base_url':'https://example.test'}
        generate_answer('Вопрос', [{'id':'S1', 'text':'Текст'}], config)
        payload=repo.log.call_args.args[6]
        self.assertEqual(payload['validation'], 'ok')
        self.assertEqual(payload['response']['usage']['total_tokens'], 10)
        self.assertNotIn('secret-key', str(payload))
        self.assertIn('[СКРЫТО]', str(payload))

    def test_no_answer_can_cite_related_sources_without_claiming_answer(self):
        result=validate_answer('{"status":"no_answer","answer":"Источники описывают только общую команду [S1].","source_ids":["S1"],"missing_information":["Нужный параметр"]}', {'S1'})
        self.assertEqual(result.source_ids, ['S1'])
