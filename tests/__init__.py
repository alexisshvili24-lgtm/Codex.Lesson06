
# Тестовые импорты не должны подключаться к рабочей базе независимо от порядка.
import os
from pathlib import Path
from uuid import uuid4
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(__file__).resolve().parents[1] / '.tmp' / ('test-suite-' + uuid4().hex + '.sqlite3')).as_posix())
