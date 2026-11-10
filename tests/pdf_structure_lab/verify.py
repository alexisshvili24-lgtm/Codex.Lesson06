"""Сравнивает символы результата с базовым извлечением pypdf постранично."""
import json
import re
import sys
from pathlib import Path
from pypdf import PdfReader

lab = Path(__file__).resolve().parent
run = Path(sys.argv[1]) if len(sys.argv) > 1 else max((lab / 'runs').iterdir(), key=lambda p: p.name)
report = {}
for name in ('progit','atlassian'):
    result = json.loads((run / f'{name}.json').read_text(encoding='utf-8-sig'))
    reader = PdfReader(str(lab / 'input' / f'{name}.pdf'))
    mismatches = []
    for page_number, page in enumerate(reader.pages, 1):
        expected = re.sub(r'\s+', '', page.extract_text() or '')
        actual = re.sub(r'\s+', '', ''.join(b['text'] for b in result['blocks'] if b['page'] == page_number))
        if expected != actual: mismatches.append(page_number)
    report[name] = {'pages':len(reader.pages), 'mismatched_pages':mismatches,
                    'blocks':len(result['blocks']), 'warnings':len(result['warnings']),
                    'note':'Сравнение с pypdf без пробелов не проверяет порядок колонок, правильность абзацев и содержимое изображений.'}
output = run / 'coverage.json'
with output.open('x', encoding='utf-8-sig') as file: json.dump(report, file, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=True))