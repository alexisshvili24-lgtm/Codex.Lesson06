"""Сквозные проверки входа и серверной изоляции профилей."""
import os
import asyncio
import uuid
import unittest
import threading
import time
from decimal import Decimal
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
Path(ROOT / '.tmp').mkdir(exist_ok=True)
test_id = uuid.uuid4().hex
os.environ['DATABASE_URL'] = 'sqlite:///' + (ROOT / '.tmp' / f'multiuser-api-{test_id}.sqlite3').as_posix()
os.environ['GIT_SUPPORT_ENV_PATH'] = str(ROOT / '.tmp' / f'multiuser-api-{test_id}.env')

import httpx
from dotenv import dotenv_values, set_key
from alembic import command
from alembic.config import Config
from app import app
import src.database as database
import src.service as service
from src.database import ROOT, Session, Event, EventOwner, UserSession
from src.service import migrate_legacy_api_key
from src.service import repo
from src.request_context import set_user_id, reset_user_id
from src.user_repository import key_version
from src.request_context import current_key_version, current_user_id
from src.service import api_key
from sqlalchemy import select


class MultiuserApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Discovery может импортировать src.database раньше этого модуля.
        # Явно подменяем путь секретов после импорта, чтобы не затрагивать .env проекта.
        global ENV_PATH
        ENV_PATH = ROOT / '.tmp' / f'multiuser-api-{test_id}.env'
        database.ENV_PATH = ENV_PATH
        service.ENV_PATH = ENV_PATH
        assert '.tmp' in str(database.engine.url), 'Тестовая БД должна находиться в .tmp'
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'migrations'))
        command.upgrade(config, 'head')
        set_key(str(ENV_PATH), 'ROUTERAI_API_KEY', 'legacy-admin-test-key', encoding='utf-8-sig')
        migrate_legacy_api_key()
        migrated = dotenv_values(ENV_PATH, encoding='utf-8-sig')
        assert migrated.get('ROUTERAI_API_KEY') is None
        assert migrated.get('ROUTERAI_API_KEY_USER_1') == 'legacy-admin-test-key'
        # Повторный запуск не дублирует профиль и не перезаписывает уже новый ключ.
        set_key(str(ENV_PATH), 'ROUTERAI_API_KEY_USER_1', 'new-admin-test-key', encoding='utf-8-sig')
        set_key(str(ENV_PATH), 'ROUTERAI_API_KEY', 'stale-legacy-test-key', encoding='utf-8-sig')
        migrate_legacy_api_key()
        migrated = dotenv_values(ENV_PATH, encoding='utf-8-sig')
        assert migrated.get('ROUTERAI_API_KEY') is None
        assert migrated.get('ROUTERAI_API_KEY_USER_1') == 'new-admin-test-key'

    def setUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver')

    def tearDown(self):
        asyncio.run(self.client.aclose())

    async def login(self, nickname):
        response = await self.client.post('/api/auth/login', json={'nickname': nickname})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['user']

    def test_login_logout_cookie_and_api_gate(self):
        async def check():
            self.assertIn('Вход'.encode(), (await self.client.get('/')).content)
            for method, path in (
                ('GET', '/api/settings'), ('GET', '/api/events'), ('GET', '/api/documents'),
                ('GET', '/api/index/status'), ('GET', '/api/chat/conversations'),
                ('POST', '/api/test/generation'), ('POST', '/api/chat'),
            ):
                response = await self.client.request(method, path)
                self.assertEqual(response.status_code, 401, path)
            user = await self.login('Alice')
            self.assertFalse(user['is_admin'])
            cookie = self.client.cookies.get('git_support_session')
            self.assertIsNotNone(cookie)
            with Session() as session:
                hashes = session.scalars(select(UserSession.token_hash)).all()
            self.assertNotIn(cookie, hashes)
            self.assertIn(64, [len(token_hash) for token_hash in hashes])
            response = await self.client.post('/api/auth/logout')
            self.assertEqual(response.status_code, 204)
            self.assertEqual((await self.client.get('/api/settings')).status_code, 401)
        asyncio.run(check())

    def test_personal_settings_and_conversation_are_isolated(self):
        async def check():
            alice = await self.login('Alice')
            settings = (await self.client.get('/api/settings')).json()
            settings['system_prompt'] = 'Личный промпт Alice'
            settings['api_key'] = 'fake-alice-key'
            saved = await self.client.put('/api/settings', json=settings)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertNotIn('api_key', (await self.client.get('/api/settings')).json())
            self.assertTrue((await self.client.get('/api/settings')).json()['key_configured'])
            context_token = set_user_id(alice['id'], 'fake-alice-key', key_version(alice['id']))
            try:
                repo.log('alice-paid-call', 'generation', 'ok', 'test-model', cost=Decimal('1.23456789'),
                         payload={'test': 'Alice'})
            finally:
                reset_user_id(context_token)
            alice_version = key_version(alice['id'])
            with Session() as session:
                event_id = session.scalar(select(Event.id).where(Event.request_id == 'alice-paid-call'))
                event_version = session.scalar(select(EventOwner.key_version_id).where(EventOwner.event_id == event_id))
            self.assertEqual(event_version, alice_version)
            conversation_id = (await self.client.post('/api/chat/conversations')).json()['id']
            alice_events = (await self.client.get('/api/events')).json()
            self.assertEqual(alice_events['costs']['generation'], '1.23456789')
            self.assertNotIn('fake-alice-key', str(alice_events))
            alice_event_ids = {item['request_id'] for item in alice_events['events']}
            await self.client.post('/api/auth/logout')

            await self.login('Bob')
            bob_settings = (await self.client.get('/api/settings')).json()
            self.assertNotEqual(bob_settings['system_prompt'], 'Личный промпт Alice')
            self.assertFalse(bob_settings['key_configured'])
            bob_events = (await self.client.get('/api/events')).json()
            self.assertEqual(bob_events['costs']['generation'], '0')
            self.assertNotIn('alice-paid-call', {item['request_id'] for item in bob_events['events']})
            self.assertEqual((await self.client.get('/api/chat/conversations')).json()['conversations'], [])
            self.assertEqual((await self.client.get(f'/api/chat/conversations/{conversation_id}')).status_code, 404)
            forbidden = await self.client.put('/api/settings', json={
                'base_url': 'https://other.example/api/v1', 'system_prompt': 'Личный промпт Bob'
            })
            self.assertEqual(forbidden.status_code, 403)
            plugin_forbidden = await self.client.put('/api/chunk-plugins', json={'plugin': 'local'})
            self.assertEqual(plugin_forbidden.status_code, 403)
        asyncio.run(check())

    def test_shared_document_api_is_available_and_admin_is_case_insensitive(self):
        async def check():
            await self.login('User_1')
            self.assertEqual((await self.client.get('/api/documents')).status_code, 200)
            await self.client.post('/api/auth/logout')
            admin = await self.login('ADMIN')
            self.assertTrue(admin['is_admin'])
            admin_settings = (await self.client.get('/api/settings')).json()
            self.assertTrue(admin_settings['is_admin'])
            self.assertTrue(admin_settings['key_configured'])
            admin_settings['generation_model'] = 'test/admin-model'
            saved = await self.client.put('/api/settings', json=admin_settings)
            self.assertEqual(saved.status_code, 200, saved.text)
            admin_settings['embedding_model'] = 'test/different-embedding'
            self.assertEqual((await self.client.put('/api/settings', json=admin_settings)).status_code, 422)
            await self.client.post('/api/auth/logout')
            await self.login('User_1')
            visible = (await self.client.get('/api/settings')).json()
            self.assertEqual(visible['generation_model'], 'test/admin-model')
            self.assertEqual(visible['embedding_model'], 'baai/bge-m3')
        asyncio.run(check())

    def test_profile_without_key_cannot_call_routerai(self):
        async def check():
            await self.login('NoKeyUser')
            with patch('src.service.routerai.request_json') as request_json:
                response = await self.client.post('/api/test/generation')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['ok'])
            self.assertIn('ключ не настроен', response.json()['message'])
            request_json.assert_not_called()
        asyncio.run(check())

    def test_background_index_keeps_initiator_credentials_and_hides_costs_from_others(self):
        from src import indexing
        from src.user_repository import get_or_create

        owner = get_or_create('IndexOwner')
        other = get_or_create('IndexViewer')
        finished = threading.Event()
        observed = {}

        def fake_index(*_args, **_kwargs):
            observed.update(user_id=current_user_id(), key=api_key(), version=current_key_version())
            finished.set()
            return {'status': 'indexed', 'expenses': {'cost_rub': '0.125', 'unknown': 0}}

        with indexing._job_lock:
            indexing._job.clear()
            indexing._job.update(state='idle')
        with patch('src.indexing.index_document', side_effect=fake_index):
            token = set_user_id(owner['id'], 'index-owner-key', 'key-version-snapshot')
            try:
                indexing.start_job('shared-document')
            finally:
                reset_user_id(token)

            self.assertTrue(finished.wait(3), 'Фоновая задача не завершилась.')
            deadline = time.monotonic() + 3
            while indexing.job_status(owner['id'])['state'] == 'running' and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(observed, {'user_id': owner['id'], 'key': 'index-owner-key',
                                    'version': 'key-version-snapshot'})
        self.assertEqual(indexing.job_status(owner['id'])['result']['expenses']['cost_rub'], '0.125')
        viewer_status = indexing.job_status(other['id'])
        self.assertNotIn('expenses', viewer_status['result'])
        with indexing._job_lock:
            indexing._job.clear()
            indexing._job.update(state='idle')


if __name__ == '__main__':
    unittest.main()
