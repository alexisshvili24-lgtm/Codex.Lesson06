"""Повторная проверка прежних ошибок с промптом v2; результаты независимы от старых."""
import hashlib,json,statistics,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; folder=ROOT/'.tmp/llm-lab'
prompt=(ROOT/'tests/file_classifier_lab/classifier_prompt_v2.txt').read_text(encoding='utf-8-sig')
ref=json.loads((folder/'reference.json').read_text(encoding='utf-8-sig'))
full=[json.loads(x) for x in (folder/'full-results.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
extra=[json.loads(x) for x in (folder/'supplement-results.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
prior={x['path']:x for x in full};prior.update({x['path']:x for x in extra})
failed={x['path'] for x in (json.loads(line) for line in (folder/'retest-v2-results.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()) if 'error' in x}
targets=[x for x in ref if x['path'] in failed]
output=folder/'retest-v2-retry-results.jsonl';status=folder/'retest-v2-retry-status.json'
if output.exists():raise RuntimeError('Результаты повторного запуска уже существуют.')
def save(state,**kw): status.write_text(json.dumps({'state':state,**kw},ensure_ascii=False,indent=2),encoding='utf-8-sig')
model=folder/'Qwen3-1.7B-Q8_0.gguf';h=hashlib.sha256()
with model.open('rb') as f:
 while block:=f.read(4*1024*1024):h.update(block)
if h.hexdigest()!='061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a':raise RuntimeError('Неверный SHA-256 модели')
schema={'type':'object','properties':{'role':{'type':'string','enum':['content','support','mixed','unknown']},'decision':{'type':'string','enum':['include','exclude','review']},'evidence':{'type':'array','items':{'type':'object','properties':{'block_id':{'type':'string'},'quote':{'type':'string'}},'required':['block_id','quote'],'additionalProperties':False}},'reason':{'type':'string'},'need':{'type':'string','enum':['none','more_text','archive_context','purpose']}},'required':['role','decision','evidence','reason','need'],'additionalProperties':False}
with (folder/'retest-v2-retry-server.log').open('w',encoding='utf-8-sig') as log:
 p=subprocess.Popen([str(folder/'runtime/llama-server.exe'),'-m',str(model),'--host','127.0.0.1','--port','8050','-ngl','0','-c','4096','-t','4','--cache-ram','256','--parallel','1','--no-webui'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 try:
  save('starting',total=len(targets))
  for _ in range(360):
   if p.poll() is not None:raise RuntimeError('Сервер завершился')
   try:
    with urllib.request.urlopen('http://127.0.0.1:8050/health',timeout=2) as r:
     if json.load(r).get('status')=='ok':break
   except Exception:pass
   time.sleep(.5)
  else:raise RuntimeError('Сервер не запустился')
  results=[]
  with zipfile.ZipFile(ROOT/'docs/sources/progit2-ru-master.zip') as z,output.open('w',encoding='utf-8-sig') as out:
   for item in targets:
    text=z.read(item['path']).decode('utf-8-sig');mid=len(text)//2
    blocks=[{'id':'B1','text':text}] if len(text)<=3000 else [{'id':'B1','text':text[:1000]},{'id':'B2','text':text[mid-500:mid+500]},{'id':'B3','text':text[-1000:]}]
    payload={'purpose':'База знаний для ответов пользователям о Git, командах, настройках и работе с репозиториями.','file':{'path':item['path'],'characters':len(text)},'coverage':'complete' if len(text)<=3000 else 'partial','blocks':blocks,'archive_context':None}
    request={'model':'qwen','temperature':0,'max_tokens':512,'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_schema','json_schema':{'name':'classification','schema':schema}},'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]}
    row={'path':item['path'],'expected':item['expected'],'coverage':payload['coverage']};start=time.perf_counter()
    try:
     req=urllib.request.Request('http://127.0.0.1:8050/v1/chat/completions',data=json.dumps(request,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
     with urllib.request.urlopen(req,timeout=240) as response: data=json.load(response)
     answer=json.loads(data['choices'][0]['message']['content']);row['answer']=answer
     sources={b['id']:b['text'] for b in blocks}
     row['evidence_valid']=all(e.get('block_id') in sources and bool(e.get('quote')) and e['quote'] in sources[e['block_id']] for e in answer.get('evidence',[])) and (answer.get('decision')=='review' or bool(answer.get('evidence')))
    except Exception as exc:row['error']=str(exc)
    row['seconds']=round(time.perf_counter()-start,2);results.append(row);out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush()
    times=[x['seconds'] for x in results];save('running',completed=len(results),total=len(targets),minimum=min(times),mean=round(statistics.mean(times),2),maximum=max(times),errors=sum('error' in x for x in results))
  save('completed',completed=len(results),total=len(targets),minimum=min(times),mean=round(statistics.mean(times),2),maximum=max(times),errors=sum('error' in x for x in results))
 except Exception as exc:save('error',error=str(exc));raise
 finally:
  p.terminate()
  try:p.wait(timeout=15)
  except subprocess.TimeoutExpired:p.kill();p.wait()
