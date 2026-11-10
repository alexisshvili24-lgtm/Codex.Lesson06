"""Запуск независимой проверки PDF на копиях в этой папке."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.document_structure import prepare_structure

LAB = Path(__file__).resolve().parent
run = LAB / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
run.mkdir(parents=True, exist_ok=False)
for path in sorted((LAB / 'input').glob('*.pdf')):
    raw = path.read_bytes()
    result = prepare_structure(path.name, raw)
    stem = path.stem
    payload = result.to_dict()
    payload['source_sha256'] = hashlib.sha256(raw).hexdigest()
    (run / f'{stem}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8-sig')
    lines = [f"[{b.kind}; стр. {b.page}]\n{b.text}" for b in result.blocks]
    (run / f'{stem}.txt').write_text('\n\n'.join(lines), encoding='utf-8-sig')
    print(f'{stem}: blocks={len(result.blocks)}, warnings={len(result.warnings)}, status={result.status}')
print(f'Результаты: {run}')