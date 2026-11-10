"""Docling PDF с локальной моделью разметки, без OCR и без сети."""
import os,time,threading
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import psutil
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorDevice,AcceleratorOptions
from docling.document_converter import DocumentConverter,PdfFormatOption
root=Path(__file__).resolve().parents[2]
process=psutil.Process();peak=[process.memory_info().rss];stop=threading.Event()
def monitor():
    while not stop.wait(.05):peak[0]=max(peak[0],process.memory_info().rss)
threading.Thread(target=monitor,daemon=True).start()
options=PdfPipelineOptions(do_ocr=False,do_table_structure=False,artifacts_path=root/'.tmp/docling-models',accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU,num_threads=4))
converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)})
for name,pages in [('atlassian-git-cheat-sheet.pdf',(1,1)),('progit.pdf',(33,38))]:
    start=time.perf_counter()
    try:
        result=converter.convert(root/'.tmp/docling-inputs'/name,page_range=pages)
        doc=result.document
        print(name,'status',result.status,'seconds',round(time.perf_counter()-start,2),'pages',pages,'items',len(doc.texts),'peak_rss_mb',round(peak[0]/1024**2,1),flush=True)
        print('labels',[(str(x.label),x.text[:100]) for x in doc.texts[:15]],flush=True)
        (root/'.tmp'/('standard-'+name+'.md')).write_text(doc.export_to_markdown(),encoding='utf-8-sig')
    except Exception as exc:
        print(name,type(exc).__name__,str(exc),flush=True)
stop.set()
