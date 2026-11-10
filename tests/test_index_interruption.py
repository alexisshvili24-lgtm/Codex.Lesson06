import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class IndexInterruptionTest(unittest.TestCase):
    def test_process_exit_preserves_interrupted_status_and_recovers_staged_collection(self):
        token=uuid.uuid4().hex
        db=ROOT/'.tmp'/('interrupt-'+token+'.sqlite3')
        path=ROOT/'.tmp'/('interrupt-qdrant-'+token)
        env=os.environ.copy()
        env['DATABASE_URL']='sqlite:///'+db.as_posix()
        env['QDRANT_PATH']=str(path)
        env['PYTHONIOENCODING']='utf-8'
        worker=r"""
import os,time,uuid
from alembic import command
from alembic.config import Config
from src.documents import prepare
from src.document_repository import write_document
from src.chunk_store import snapshot,save_run
from src import indexing
cfg=Config();cfg.set_main_option('script_location','migrations');command.upgrade(cfg,'head')
doc=prepare('test.txt',b'Test.',{'title':'Crash','language':'ru','source_type':'official'})
write_document(doc,str(uuid.uuid4())); snap=snapshot(doc['id'])
chunks=[{'chunk_id':f'{i:064x}','text':f'Text {i}','tokens':2} for i in range(20)]
save_run(doc['id'],snap['revision'],{'chunks':chunks,'warnings':[]},str(uuid.uuid4()))
original=indexing.index_document
def interrupted(doc_id,progress=None):
 def stop_after_first(completed,total):
  if progress: progress(completed,total)
  if completed: os._exit(0)
 return original(doc_id,embedder=lambda texts,config:[[1.,0.] for t in texts],progress=stop_after_first)
indexing.index_document=interrupted
indexing.start_job(doc['id'])
time.sleep(30)
os._exit(3)
"""
        result=subprocess.run([sys.executable,'-c',worker],cwd=ROOT,env=env,capture_output=True,text=True,timeout=50)
        self.assertEqual(result.returncode,0,result.stderr)
        check=r"""
from src.indexing import job_status,cleanup_queued
from src.index_repository import pending_collections
from src.vector_store import VectorStore
import os
status=job_status()
assert status['state']=='interrupted',status
pending=pending_collections()
assert len(pending)==1,pending
store=VectorStore(os.environ['QDRANT_PATH'])
try: assert store.client.collection_exists(pending[0])
finally: store.close()
assert cleanup_queued()
store=VectorStore(os.environ['QDRANT_PATH'])
try: assert not store.client.collection_exists(pending[0])
finally: store.close()
assert not pending_collections()
print('interruption recovered')
"""
        result=subprocess.run([sys.executable,'-c',check],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('interruption recovered',result.stdout)
