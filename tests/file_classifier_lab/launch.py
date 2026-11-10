"""CPU-испытание загруженной модели на отдельном локальном порту."""
import hashlib,json,os,subprocess,sys,threading,time,urllib.request
from pathlib import Path
import psutil
root=Path(__file__).resolve().parents[2]
candidates=[root/'.tmp/llm-lab/Qwen3-1.7B-Q8_0.gguf',root/'.tmp/llm-lab/hub/Qwen3-1.7B-Q8_0.gguf']
model=next((p for p in candidates if p.is_file() and p.stat().st_size==1834426016),None)
server=root/'.tmp/llm-lab/runtime/llama-server.exe'
if model is None: raise RuntimeError('Модель ещё не загружена полностью.')
digest=hashlib.sha256()
with model.open('rb') as source:
    while block:=source.read(4*1024*1024): digest.update(block)
if digest.hexdigest()!='061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a':
    raise RuntimeError('SHA-256 модели не совпадает с официальным значением.')
cmd=[str(server),'-m',str(model),'--host','127.0.0.1','--port','8036','-ngl','0','-c','4096','-t','4','--no-webui']
logpath=root/'.tmp/llm-lab/server.log'
with logpath.open('w',encoding='utf-8-sig') as log:
    p=subprocess.Popen(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    peak=[0];done=threading.Event()
    def monitor():
        while not done.wait(.1):
            try: peak[0]=max(peak[0],psutil.Process(p.pid).memory_info().rss)
            except psutil.Error: break
    threading.Thread(target=monitor,daemon=True).start()
    try:
        start=time.perf_counter()
        while time.perf_counter()-start<180:
            if p.poll() is not None:raise RuntimeError('Сервер завершился; см. .tmp/llm-lab/server.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8036/health',timeout=2) as response:
                    if json.load(response).get('status')=='ok':break
            except Exception: pass
            time.sleep(.5)
        else:raise RuntimeError('Сервер не запустился за 180 секунд.')
        print('Сервер готов за',round(time.perf_counter()-start,2),'с',flush=True)
        trial=subprocess.run([str(root/'.venv/Scripts/python.exe'),str(root/'tests/file_classifier_lab/run.py')],cwd=root,check=False)
        if trial.returncode: raise RuntimeError('Сценарий теста завершился с ошибкой.')
    finally:
        done.set();p.terminate()
        try:p.wait(timeout=15)
        except subprocess.TimeoutExpired:p.kill();p.wait()
        print('Пик RSS процесса сервера:',round(peak[0]/2**20,1),'МиБ',flush=True)
