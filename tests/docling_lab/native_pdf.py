"""Проверка встроенного PDF-режима Docling без моделей и без OCR."""
import os,sys,sqlite3,time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['OPENBLAS_NUM_THREADS']='1'
sys.modules['scipy']=None
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import NativePdfPipelineOptions
from docling.document_converter import DocumentConverter, NativePdfFormatOption
from docling_core.types.doc.page import TextCellUnit
root=Path(__file__).resolve().parents[2]; out=root/'.tmp/docling-inputs';out.mkdir(exist_ok=True)
c=sqlite3.connect((root/'data/app.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
for name,blob in c.execute("select filename, original from documents where filename in ('progit.pdf','atlassian-git-cheat-sheet.pdf')"):
    path=out/name
    if not path.exists(): path.write_bytes(blob)
c.close()
options=NativePdfPipelineOptions(text_cell_unit=TextCellUnit.LINE,parser_threads=2)
converter=DocumentConverter(format_options={InputFormat.PDF:NativePdfFormatOption(pipeline_options=options)})
for name,pages in [('atlassian-git-cheat-sheet.pdf',(1,1)),('progit.pdf',(1,10))]:
    start=time.perf_counter()
    try:
        result=converter.convert(out/name,page_range=pages)
        doc=result.document
        print(name,'status',result.status,'seconds',round(time.perf_counter()-start,2),'pages',pages,'items',len(doc.texts),'labels',[(str(x.label),x.text[:80]) for x in doc.texts[:8]],flush=True)
        (root/'.tmp'/('native-'+name+'.md')).write_text(doc.export_to_markdown(),encoding='utf-8-sig')
    except Exception as exc:
        print(name,type(exc).__name__,str(exc),flush=True)
