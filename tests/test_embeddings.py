import unittest
from decimal import Decimal
from unittest.mock import patch
from src.embeddings import embed_texts, EmbeddingError

class EmbeddingTests(unittest.TestCase):
    @patch('src.embeddings.repo')
    @patch('src.embeddings.routerai.cost', return_value=(Decimal('0.001'), None))
    @patch('src.embeddings.routerai.request_json')
    @patch('src.embeddings.api_key', return_value='secret')
    @patch('src.embeddings.settings', return_value={'base_url': 'https://example.test', 'embedding_model': 'model'})
    def test_batch_order_and_cost(self, settings, dotenv, request, cost, repo):
        request.return_value = ({'data': [{'index': 1, 'embedding': [Decimal('0.4')]}, {'index': 0, 'embedding': [Decimal('0.2')]}]}, 'generation')
        self.assertEqual(embed_texts(['a','b']), [[0.2],[0.4]])
        self.assertEqual(repo.log.call_args.args[2], 'ok')
        self.assertEqual(repo.log.call_args.args[5], Decimal('0.001'))

    @patch('src.embeddings.repo')
    @patch('src.embeddings.routerai.cost', return_value=(None, 'unknown'))
    @patch('src.embeddings.routerai.request_json', return_value=({'data': []}, 'generation'))
    @patch('src.embeddings.api_key', return_value='secret')
    @patch('src.embeddings.settings', return_value={'base_url': 'https://example.test', 'embedding_model': 'model'})
    def test_invalid_response_is_logged(self, settings, dotenv, request, cost, repo):
        with self.assertRaises(EmbeddingError): embed_texts(['a'])
        self.assertEqual(repo.log.call_args.args[2], 'error')

    @patch('src.embeddings.repo')
    @patch('src.embeddings.routerai.cost', return_value=(None, 'unknown'))
    @patch('src.embeddings.routerai.request_json')
    @patch('src.embeddings.api_key', return_value='secret')
    @patch('src.embeddings.settings', return_value={'base_url': 'https://example.test', 'embedding_model': 'model'})
    def test_rejects_boolean_indices_and_nonfinite_vectors(self, settings, dotenv, request, cost, repo):
        for data in ([{'index': False, 'embedding': [0.1]}], [{'index': 0, 'embedding': [float('nan')]}]):
            request.return_value=({'data':data}, 'generation')
            with self.assertRaises(EmbeddingError): embed_texts(['a'])
            self.assertEqual(repo.log.call_args.args[2], 'error')
