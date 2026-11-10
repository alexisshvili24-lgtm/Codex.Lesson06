"""Изолированное измерение текущего парсера без импорта Docling."""
import os, sys, time, threading
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1'
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
import psutil
process=psutil.Process(); peak=[process.memory_info().rss]; done=threading.Event()
def monitor():
    while not done.wait(.05): peak[0]=max(peak[0],process.memory_info().rss)
threading.Thread(target=monitor,daemon=True).start()
from src.document_structure import prepare_structure
from src.chunking import chunk_sections,bge_counter
count=bge_counter(root/'data/tokenizers/bge-m3-tokenizer.json')
for name in ('recording-changes.asc','progit-pdf-extracted.txt'):
    path=root/'.tmp/docling-inputs'/name
    start=time.perf_counter()
    blocks=prepare_structure(name,path.read_bytes()).blocks
    chunks=chunk_sections(blocks,count)
    print(name,'seconds',round(time.perf_counter()-start,3),'chunks',len(chunks),'peak_rss_mb',round(peak[0]/1024**2,1),flush=True)
done.set()
