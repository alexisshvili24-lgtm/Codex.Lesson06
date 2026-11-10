"""Диагностика перекрытия предложениями поверх сохранённых результатов Docling."""
import json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.chunking import bge_counter,_sentences
counter=bge_counter(ROOT/'data/tokenizers/bge-m3-tokenizer.json')
data=json.loads((ROOT/'.tmp/docling-results.json').read_text(encoding='utf-8-sig'))
for record in data:
    if 'docling_chunks' not in record: continue
    chunks=record['docling_chunks'];sizes=[];overlap_sizes=[]
    for index,item in enumerate(chunks):
        selected=[]
        if index and item['headings']==chunks[index-1]['headings']:
            previous=chunks[index-1]['text'];limit=max(1,round(counter(previous)*.15))
            for sentence in reversed(_sentences(previous)):
                if selected and counter(' '.join([sentence,*selected]))>limit: break
                selected.insert(0,sentence)
        overlap=' '.join(selected)
        overlap_sizes.append(counter(overlap) if overlap else 0)
        sizes.append(counter((overlap+'\n\n' if overlap else '')+item['text']))
    if sizes:
        print(record['file'], 'chunks',len(sizes),'median',statistics.median(sizes),'max',max(sizes),'over_800',sum(size>800 for size in sizes),'pairs',sum(x>0 for x in overlap_sizes),flush=True)
