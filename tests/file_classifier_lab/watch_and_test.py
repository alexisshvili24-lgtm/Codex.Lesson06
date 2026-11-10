"""Дожидается разрешённого скачивания, затем запускает CPU-тест."""
import json,subprocess,sys,time
from pathlib import Path
import psutil
root=Path(__file__).resolve().parents[2]
folder=root/'.tmp/llm-lab'; status=folder/'background-status.json'
model=folder/'Qwen3-1.7B-Q8_0.gguf'; hub=folder/'hub/Qwen3-1.7B-Q8_0.gguf'; total=1834426016
url='https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf'
def write(state,**values):status.write_text(json.dumps({'state':state,**values},ensure_ascii=False,indent=2),encoding='utf-8-sig')
try:
    pid=int(sys.argv[1]);process=psutil.Process(pid)
    while process.is_running():
        write('downloading',bytes=model.stat().st_size if model.exists() else 0,total=total)
        time.sleep(30)
    for attempt in range(8):
        if any(path.is_file() and path.stat().st_size==total for path in (model,hub)):break
        write('resuming',attempt=attempt+1,bytes=model.stat().st_size if model.exists() else 0,total=total)
        with (folder/'download.log').open('a',encoding='utf-8-sig') as log:
            result=subprocess.run(['curl.exe','-L','--fail','--retry','4','--continue-at','-','-o',str(model),url],cwd=root,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:time.sleep(30)
    else:raise RuntimeError('Не удалось полностью загрузить модель после повторных попыток.')
    write('testing')
    with (folder/'experiment.log').open('w',encoding='utf-8-sig') as log:
        result=subprocess.run([str(root/'.tmp/docling-lab/Scripts/python.exe'),str(root/'tests/file_classifier_lab/launch.py')],cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Тест завершился ошибкой; см. experiment.log.')
    write('completed',results=str(folder/'results.json'))
except Exception as exc:
    write('error',error=str(exc))
