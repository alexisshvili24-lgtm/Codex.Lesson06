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
                                    "VALUES ('legacy-id', '2026-01-01T00:00:00+00:00', 'generation', 'ok', 'model', 5, '0.25', '{}')"))
            connection.execute(text("DELETE FROM chat_conversations WHERE id = 'legacy-chat'"))
            connection.execute(text("INSERT INTO chat_conversations(id, title, updated_at, summary, turn_count) "
                                    "VALUES ('legacy-chat', 'Чат', '2026-01-01T00:00:00+00:00', '', 0)"))
        command.upgrade(cls.config, '0007')
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
            self.assertEqual(connection.execute(text("SELECT user_id FROM event_owners WHERE event_id = 1")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT user_id FROM conversation_owners WHERE conversation_id = 'legacy-chat'")).scalar_one(), 1)

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
