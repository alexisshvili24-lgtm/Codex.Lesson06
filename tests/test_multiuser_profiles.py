"""Проверка переноса старых данных в профиль admin."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ['DATABASE_URL'] = 'sqlite:///' + (ROOT / '.tmp' / ('multiuser-' + uuid.uuid4().hex + '.sqlite3')).as_posix()

from alembic import command
from alembic.config import Config
from sqlalchemy import text, inspect
from src.database import Session, engine
from src.user_repository import get_or_create, normalize_nickname, InvalidNickname


class MultiuserMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Path(ROOT / '.tmp').mkdir(exist_ok=True)
        cls.config = Config()
        cls.config.set_main_option('script_location', str(ROOT / 'migrations'))
        with engine.connect() as connection:
            current = (connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
                       if inspect(connection).has_table('alembic_version') else None)
        if current == '0007':
            cls.migration_fixture = False
            return
        command.upgrade(cls.config, '0006')
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM settings WHERE name IN ('system_prompt', 'base_url')"))
            connection.execute(text("INSERT INTO settings(name, value) VALUES ('system_prompt', 'legacy prompt')"))
            connection.execute(text("INSERT INTO settings(name, value) VALUES ('base_url', 'https://router.example/api/v1')"))
            connection.execute(text("DELETE FROM events WHERE request_id = 'legacy-id'"))
            connection.execute(text("INSERT INTO events(request_id, created_at, operation, status, model, duration_ms, cost_rub, payload) "
                                    "VALUES ('legacy-id', '2026-01-01T00:00:00+00:00', 'rag', 'ok', 'model', 5, '0.25', '{\"question\":\"legacy\"}')"))
            legacy_event_id = connection.execute(text("SELECT id FROM events WHERE request_id = 'legacy-id'")).scalar_one()
            connection.execute(text("DELETE FROM chat_conversations WHERE id = 'legacy-chat'"))
            connection.execute(text("INSERT INTO chat_conversations(id, title, updated_at, summary, turn_count) "
                                    "VALUES ('legacy-chat', 'Чат', '2026-01-01T00:00:00+00:00', '', 0)"))
            connection.execute(text("INSERT INTO chat_turns(conversation_id, position, event_id) "
                                    "VALUES ('legacy-chat', 1, :event_id)"), {'event_id': legacy_event_id})
            connection.execute(text("INSERT INTO documents(id, title, source_type, language, version, published_at, source_url, git_commit, filename, sha256, uploaded_at, status, chunk_count, extracted_text, original) "
                                    "VALUES ('legacy-doc', 'Legacy document', 'official', 'en', '', '', '', '', 'legacy.md', :sha, '2026-01-01T00:00:00+00:00', 'ready', 1, 'Legacy text', :original)"),
                                {'sha': 'a' * 64, 'original': b'Legacy bytes'})
            connection.execute(text("INSERT INTO chunk_runs(id, document_id, revision, created_at, warnings, chunk_count) "
                                    "VALUES ('legacy-run', 'legacy-doc', 'legacy-revision', '2026-01-01T00:00:00+00:00', '[]', 1)"))
            connection.execute(text("INSERT INTO prepared_chunks(run_id, position, chunk_id, payload) "
                                    "VALUES ('legacy-run', 0, :chunk_id, :payload)"),
                                {'chunk_id': 'b' * 64, 'payload': '{"text":"Legacy text"}'})
            connection.execute(text("INSERT INTO index_generations(document_id, run_id, revision, collection, model, chunk_count, created_at) "
                                    "VALUES ('legacy-doc', 'legacy-run', 'legacy-revision', 'legacy-collection', 'baai/bge-m3', 1, '2026-01-01T00:00:00+00:00')"))
        command.upgrade(cls.config, '0007')
        command.upgrade(cls.config, 'head')
        cls.migration_fixture = True

    def test_migration_moves_personal_settings_and_preserves_shared_settings(self):
        if not self.migration_fixture:
            self.skipTest('Миграция уже применена общей тестовой базой; сценарий проверяется отдельно на чистом снимке.')
        with engine.connect() as connection:
            admin = connection.execute(text("SELECT nickname, is_admin FROM users WHERE id = 1")).one()
            self.assertEqual(tuple(admin), ('admin', True))
            prompt = connection.execute(text("SELECT value FROM user_settings WHERE user_id = 1 AND name = 'system_prompt'")).scalar_one()
            self.assertEqual(prompt, 'legacy prompt')
            self.assertEqual(connection.execute(text("SELECT value FROM settings WHERE name = 'system_prompt'")).scalar_one(),
                             'legacy prompt')
            self.assertEqual(connection.execute(text("SELECT value FROM settings WHERE name = 'base_url'")).scalar_one(),
                             'https://router.example/api/v1')
            legacy_event = connection.execute(text("SELECT id, cost_rub, payload FROM events WHERE request_id = 'legacy-id'")).one()
            self.assertEqual(str(legacy_event.cost_rub), '0.25')
            self.assertEqual(connection.execute(text("SELECT user_id FROM event_owners WHERE event_id = :id"),
                                                {'id': legacy_event.id}).scalar_one(), 1)
            turn = connection.execute(text("SELECT event_id FROM chat_turns WHERE conversation_id = 'legacy-chat' AND position = 1")).scalar_one()
            self.assertEqual(turn, legacy_event.id)
            self.assertEqual(connection.execute(text("SELECT user_id FROM conversation_owners WHERE conversation_id = 'legacy-chat'")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one(), 1)
            document = connection.execute(text("SELECT id, original, extracted_text FROM documents WHERE id = 'legacy-doc'")).one()
            self.assertEqual(tuple(document), ('legacy-doc', b'Legacy bytes', 'Legacy text'))
            self.assertEqual(connection.execute(text("SELECT chunk_id FROM prepared_chunks WHERE run_id = 'legacy-run' AND position = 0")).scalar_one(), 'b' * 64)
            generation = connection.execute(text("SELECT collection, model FROM index_generations WHERE document_id = 'legacy-doc'")).one()
            self.assertEqual(tuple(generation), ('legacy-collection', 'baai/bge-m3'))

    def test_nickname_normalization_and_admin_name(self):
        self.assertEqual(normalize_nickname('  Admin  '), ('Admin', 'admin'))
        self.assertEqual(get_or_create('ADMIN')['id'], 1)
        user = get_or_create('User_01')
        self.assertFalse(user['is_admin'])
        self.assertEqual(get_or_create('user_01')['id'], user['id'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            concurrent = list(pool.map(get_or_create, ['SimultaneousUser'] * 16))
        self.assertEqual(len({item['id'] for item in concurrent}), 1)
        with self.assertRaises(InvalidNickname):
            normalize_nickname('two words')


if __name__ == '__main__':
    unittest.main()
