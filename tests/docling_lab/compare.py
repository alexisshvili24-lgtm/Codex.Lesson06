"""Офлайн-сравнение Docling и текущего чанкинга на локальных файлах."""
import json
import os
import re
import statistics
import sys
import threading
import time
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# SciPy недоступен на этой машине; в опыте OCR и PDF-конвертация не используются.
sys.modules['scipy'] = None
import psutil
from tokenizers import Tokenizer
from transformers import PreTrainedTokenizerFast
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DoclingDocument, DocItemLabel
from src.document_structure import prepare_structure
from src.chunking import chunk_sections, _sentences

INPUT = ROOT / '.tmp/docling-inputs'
OUTPUT = ROOT / '.tmp/docling-results.json'
model = Tokenizer.from_str((ROOT / 'data/tokenizers/bge-m3-tokenizer.json').read_text(encoding='utf-8-sig'))
def count(text): return len(model.encode(text, add_special_tokens=True).ids)
hf = PreTrainedTokenizerFast(tokenizer_object=model)
chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=hf, max_tokens=512), merge_peers=True)
converter = DocumentConverter()
process = psutil.Process()
peak = [process.memory_info().rss]
stop = threading.Event()
def monitor():
    while not stop.wait(.05):
        peak[0] = max(peak[0], process.memory_info().rss)
threading.Thread(target=monitor, daemon=True).start()

def stats(chunks):
    sizes = [count(text) for text in chunks]
    return {'count': len(sizes), 'min': min(sizes, default=0), 'median': statistics.median(sizes) if sizes else 0,
            'max': max(sizes, default=0), 'over_800': sum(x > 800 for x in sizes)}

def text_doc(source):
    doc = DoclingDocument(name='Текст после извлечения PDF')
    for paragraph in re.split(r'\n\s*\n', source):
        if paragraph.strip(): doc.add_text(label=DocItemLabel.TEXT, text=paragraph.strip())
    return doc

def with_overlap(chunks):
    result = []
    for index, chunk in enumerate(chunks):
        text = chunk.text
        overlap = ''
        overlap_mode = 'none'
        if index and chunk.meta.headings == chunks[index-1].meta.headings:
            previous = chunks[index-1].text
            paragraphs = [p for p in re.split(r'\n\s*\n', previous) if p.strip()]
            if paragraphs:
                selected = []
                limit = max(1, round(count(previous) * .15))
                for sentence in reversed(_sentences(previous)):
                    if selected and count(' '.join([sentence, *selected])) > limit: break
                    selected.insert(0, sentence)
                if selected:
                    needle = selected[0]
                    start = previous.rfind(needle)
                    boundary = previous.rfind('\n\n', 0, max(start, 0))
                    overlap = previous[boundary+2:].strip() if boundary >= 0 else previous.strip()
                    overlap_mode = 'paragraph'
                    if count(overlap + '\n\n' + text) > 800:
                        sentence_overlap = ' '.join(selected)
                        if count(sentence_overlap + '\n\n' + text) <= 800:
                            overlap = sentence_overlap
                            overlap_mode = 'sentences'
                    if count(overlap + '\n\n' + text) > 8192:
                        overlap = ''
                        overlap_mode = 'unavailable'
        result.append({'text': text, 'overlap': overlap, 'overlap_mode': overlap_mode, 'headings': chunk.meta.headings or [],
                       'combined_tokens': count((overlap + '\n\n' if overlap else '') + text)})
    return result

results = []
for path in sorted(INPUT.iterdir()):
    if not path.is_file() or path.suffix.lower() == '.pdf': continue
    peak[0] = process.memory_info().rss
    text = path.read_text(encoding='utf-8-sig')
    result = {'file':path.name, 'characters':len(text)}
    try:
        start = time.perf_counter()
        document = text_doc(text) if path.suffix == '.txt' else converter.convert(path).document
        raw = list(chunker.chunk(dl_doc=document))
        result['docling_seconds'] = round(time.perf_counter()-start, 3)
        result['docling_peak_rss_mb'] = round(peak[0]/1024**2, 1)
        docling_chunks = with_overlap(raw)
        result['docling'] = stats([c['text'] for c in docling_chunks])
        result['docling_with_overlap'] = stats([(c['overlap']+'\n\n' if c['overlap'] else '')+c['text'] for c in docling_chunks])
        result['docling_overlap_pairs'] = sum(bool(c['overlap']) for c in docling_chunks)
        result['overlap_modes'] = {mode:sum(c['overlap_mode']==mode for c in docling_chunks) for mode in ('none','paragraph','sentences','unavailable')}
        result['docling_chunks'] = docling_chunks
    except Exception as exc:
        result['docling_error'] = type(exc).__name__ + ': ' + str(exc)
    try:
        start=time.perf_counter()
        blocks=prepare_structure(path.name, path.read_bytes()).blocks
        own=chunk_sections(blocks,count)
        result['our_seconds']=round(time.perf_counter()-start,3)
        result['our']=stats([c.text for c in own])
        result['our_chunks']=[{'text':c.text,'chapter':c.chapter,'section':c.section,'subsection':c.subsection} for c in own]
    except Exception as exc:
        result['our_error']=type(exc).__name__+': '+str(exc)
    results.append(result)
    print(path.name, {k:v for k,v in result.items() if not k.endswith('_chunks')}, flush=True)
    OUTPUT.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8-sig')
stop.set()
