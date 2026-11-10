"""Подготовка локальной выборки для сравнения, без изменения рабочей БД."""
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.tmp' / 'docling-inputs'
OUT.mkdir(parents=True, exist_ok=True)
sections = ('recording-changes.asc', 'basic-branching-and-merging.asc', 'rebasing.asc')
with zipfile.ZipFile(ROOT / 'docs/sources/progit2-ru-master.zip') as archive:
    for suffix in sections:
        path = next(name for name in archive.namelist() if '/sections/' in name and name.endswith('/' + suffix))
        (OUT / suffix).write_text(archive.read(path).decode('utf-8-sig'), encoding='utf-8-sig')
connection = sqlite3.connect((ROOT / 'data/app.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
for filename, text in connection.execute('SELECT filename, extracted_text FROM documents'):
    target = {'progit.pdf': 'progit-pdf-extracted.txt', 'atlassian-git-cheat-sheet.pdf': 'atlassian-pdf-extracted.txt', 'git-status.adoc.txt': 'git-status.asc'}.get(filename)
    if target:
        (OUT / target).write_text(text, encoding='utf-8-sig')
connection.close()
(OUT / 'fixture.md').write_text('# Пример\n\nПроверяем состояние репозитория.\n\n```sh\ngit status\n```\n\n## Список\n\n- Первый пункт.\n- Второй пункт.\n', encoding='utf-8-sig')
(OUT / 'fixture.html').write_text('<html><body><h1>Пример</h1><p>Проверяем состояние репозитория.</p><pre>git status</pre><h2>Список</h2><ul><li>Первый пункт.</li><li>Второй пункт.</li></ul></body></html>', encoding='utf-8-sig')
print('Подготовлены образцы:', ', '.join(p.name for p in sorted(OUT.iterdir()) if p.is_file()))
