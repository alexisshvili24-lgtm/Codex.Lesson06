"""Завершает независимую оценку после полного прохода."""
import json,subprocess,time,sys
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[2];folder=ROOT/'.tmp/llm-lab';status=folder/'audit-status.json'
def state(name,**extra):status.write_text(json.dumps({'state':name,**extra},ensure_ascii=False,indent=2),encoding='utf-8-sig')
try:
    state('waiting_for_full')
    while True:
        data=json.loads((folder/'full-status.json').read_text(encoding='utf-8-sig'))
        if data['state']=='completed':break
        if data['state']=='error':raise RuntimeError('Основной проход завершился с ошибкой.')
        if not psutil.pid_exists(int(sys.argv[1])):raise RuntimeError('Основной процесс больше не работает.')
        time.sleep(30)
    state('supplementing')
    with (folder/'supplement.log').open('w',encoding='utf-8-sig') as log:
        p=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'tests/file_classifier_lab/supplement.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise RuntimeError('Дополнительная проверка завершилась с ошибкой; см. supplement.log')
    reference=json.loads((folder/'reference.json').read_text(encoding='utf-8-sig'))
    full=[json.loads(x) for x in (folder/'full-results.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    extra=[json.loads(x) for x in (folder/'supplement-results.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    bypath={x['path']:x for x in full};bypath.update({x['path']:x for x in extra})
    definite=[x for x in reference if x['expected']!='uncertain']; unclear=[x for x in reference if x['expected']=='uncertain']
    matched=[(r,bypath.get(r['path'],{})) for r in definite]
    valid=[(r,m) for r,m in matched if m.get('label') in ('material','service','uncertain') and m.get('scope') in ('text_full','text_sample')]
    correct=[(r,m) for r,m in valid if m['label']==r['expected']]
    wrong=[(r,m) for r,m in valid if m['label']!=r['expected']]
    omitted=[r['path'] for r,m in matched if (r,m) not in valid]
    report=['# Предварительная оценка модели по ZIP Pro Git','',f'Всего в ZIP: {len(full)} файлов. Текстовых файлов без PDF и изображений: {len(reference)}.',f'Независимая предварительная разметка по просмотренным фрагментам: однозначных {len(definite)}, неоднозначных {len(unclear)}.',f'Для {len(valid)} однозначных файлов получен ответ по тексту; совпало {len(correct)} ({100*len(correct)/len(valid):.1f}%). Ошибок или отсутствующих ответов: {len(omitted)}.','', 'Эталон подготовлен по кратким независимо просмотренным фрагментам и требует ручной перепроверки, особенно пограничные случаи. Модель на длинных файлах видела лишь начало, середину и конец. PDF, PNG и SVG исключены. Ответы по одним метаданным заменены повторной классификацией содержимого.','', '## Несовпадения','']
    for r,m in wrong:report.append(f"- {r['path']}: ожидалось {r['expected']}, модель — {m['label']}; {m.get('reason','')}")
    if omitted:report.extend(['','## Не получили ответ','']+[f'- {x}' for x in omitted])
    (folder/'full-report.md').write_text('\n'.join(report)+'\n',encoding='utf-8-sig')
    state('completed',reference=len(reference),definite=len(definite),valid=len(valid),correct=len(correct),wrong=len(wrong),omitted=len(omitted),unclear=len(unclear))
except Exception as exc:state('error',error=str(exc))
