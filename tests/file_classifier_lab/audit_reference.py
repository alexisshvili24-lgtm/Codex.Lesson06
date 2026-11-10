"""Предварительная независимая разметка Pro Git по просмотренным фрагментам.
Пограничные случаи оставлены неопределёнными; это не полная проверка содержимого.
"""
import hashlib,json,zipfile
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parents[2]
archive=root/'docs/sources/progit2-ru-master.zip'
output=root/'.tmp/llm-lab/reference.json'
records=[]
service_exact={'.github/.dependabot.yml','.github/workflows/pr_build.yml','.github/workflows/release.yml','.gitignore','.mailmap','Gemfile','Rakefile','TRANSLATION_NOTES.asc','atlas.json','attributes.asc','book/contributors.asc','book/cover.html','book/dedication.asc','index.asc','progit.asc','status.json'}
material_exact={'A-git-in-other-environments.asc','B-embedding-git-in-your-applications.asc','C-git-commands.asc','book/07-git-tools/git-credential-read-only'}
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        path=item.filename;ext=PurePosixPath(path).suffix.lower()
        if item.is_dir() or ext in {'.png','.pdf','.svg'}:continue
        try:
            b=z.read(item)
            if b'\x00' in b:continue
            text=b.decode('utf-8-sig')
        except UnicodeError:continue
        short=path.removeprefix('progit2-ru-master/')
        if '/sections/' in short and ext=='.asc': expected='material'
        elif short in material_exact or (short.startswith('ch') and ext=='.asc'):expected='material'
        elif short in service_exact or short.startswith('theme/'):expected='service'
        else:expected='uncertain'
        evidence=' '.join(text.split())[:180]
        records.append({'path':path,'sha256':hashlib.sha256(b).hexdigest(),'expected':expected,'evidence':evidence})
output.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8-sig')
from collections import Counter
print('Оценено по фрагментам:',len(records),dict(Counter(x['expected'] for x in records)))
