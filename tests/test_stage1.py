import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
os.environ['DATABASE_URL'] = 'sqlite:///' + (ROOT / '.tmp' / ('test-' + uuid.uuid4().hex + '.sqlite3')).as_posix()
from alembic import command
from alembic.config import Config
from src.service import Settings, save, settings, test_call, repo
from src import routerai

class StageOneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'migrations'))
        command.upgrade(config, 'head')

    def test_settings_persist_and_key_not_returned(self):
        data = settings()
        data['embedding_model'] = 'example/model'
        save(Settings(**data))
        self.assertEqual(settings()['embedding_model'], 'example/model')
        self.assertNotIn('api_key', settings())

    @patch('src.service.dotenv_values', return_value={'ROUTERAI_API_KEY': 'test-secret'})
    @patch('src.routerai.request_json')
    def test_cost_and_invalid_json_are_logged(self, request, env):
        request.side_effect = [({'choices': [{'message': {'content': '{bad'}}]}, 'id-1'), ({'data': {'total_cost': '0.125'}}, None)]
        result = test_call('generation')
        self.assertFalse(result['ok'])
        self.assertEqual(result['cost_rub'], '0.125')
        event = repo.events()[0]
        self.assertEqual(event['status'], 'error')
        self.assertNotIn('test-secret', event['payload'])
        self.assertEqual(repo.costs()['generation'], '0.125')

    @patch('src.service.dotenv_values', return_value={'ROUTERAI_API_KEY': 'test-secret'})
    @patch('src.routerai.request_json')
    def test_embedding_unknown_cost_is_not_zero(self, request, env):
        request.side_effect = [({'data': [{'embedding': [0.1, 0.2]}]}, 'id-2'), ({}, None)]
        result = test_call('embedding')
        self.assertTrue(result['ok'])
        self.assertIsNone(result['cost_rub'])
        self.assertGreaterEqual(repo.costs()['unknown'], 1)

if __name__ == '__main__':
    unittest.main()