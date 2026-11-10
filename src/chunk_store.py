"""Новые результаты сохраняются отдельно; существующие документы не перезаписываются."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.database import Session, Document, ChunkRun, PreparedChunk, Event, Setting

FIELDS=('id','title','source_type','language','version','source_url','filename','sha256')

class StaleDocument(ValueError):
    pass

def _selected(session):
    setting=session.get(Setting,'chunking_plugin')
    return setting.value if setting else 'local'

def _revision(row, plugin):
    values={field:getattr(row,field) for field in FIELDS}
    values['chunking_plugin']=plugin
    values['pipeline_revision']='3'
    encoded=json.dumps(values,ensure_ascii=False,sort_keys=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

def snapshot(document_id):
    with Session() as session:
        row=session.get(Document,document_id)
        if row is None: return None
        data={field:getattr(row,field) for field in FIELDS}
        data['original']=row.original
        data['plugin']=_selected(session)
        data['revision']=_revision(row,data['plugin'])
        return data

def save_run(document_id, revision, result, request_id):
    run_id=str(uuid.uuid4())
    with Session.begin() as session:
        row=session.get(Document,document_id)
        if row is None or _revision(row,_selected(session))!=revision:
            raise StaleDocument('Документ изменился во время обработки; результат не сохранён.')
        session.add(ChunkRun(id=run_id,document_id=document_id,revision=revision,
            created_at=datetime.now(timezone.utc).isoformat(),warnings=json.dumps(result['warnings'],ensure_ascii=False),
            chunk_count=len(result['chunks'])))
        session.add(Event(request_id=request_id,created_at=datetime.now(timezone.utc).isoformat(),operation='document_prepare',status='ok',model='',duration_ms=0,cost_rub=None,payload=json.dumps({'document_id':document_id,'run_id':run_id,'chunks':len(result['chunks']),'warnings':len(result['warnings']),'plugin':result.get('plugin',_selected(session))})))
        for position,chunk in enumerate(result['chunks']):
            session.add(PreparedChunk(run_id=run_id,position=position,chunk_id=chunk['chunk_id'],
                payload=json.dumps(chunk,ensure_ascii=False)))
    return run_id

def latest_run(document_id):
    with Session() as session:
        row=session.get(Document,document_id)
        if row is None: return None
        run=session.scalars(select(ChunkRun).where(ChunkRun.document_id==document_id,ChunkRun.revision==_revision(row,_selected(session)))
            .order_by(ChunkRun.created_at.desc(),ChunkRun.id.desc()).limit(1)).first()
        if run is None: return None
        chunks=session.scalars(select(PreparedChunk).where(PreparedChunk.run_id==run.id).order_by(PreparedChunk.position)).all()
        return {'run_id':run.id,'created_at':run.created_at,'warnings':json.loads(run.warnings),
                'chunks':[json.loads(chunk.payload) for chunk in chunks]}