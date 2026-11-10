import os, uuid, unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
os.environ['DATABASE_URL']='sqlite:///'+(ROOT/'.tmp'/('chunk-storage-'+uuid.uuid4().hex+'.sqlite3')).as_posix()
from alembic import command
from alembic.config import Config
from src.database import engine
from src.document_repository import write_document
from src.documents import prepare
from src.chunk_store import snapshot, save_run, latest_run, StaleDocument

class ChunkStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert '.tmp' in str(engine.url), 'Тестовая БД должна быть изолирована'
        cfg=Config(); cfg.set_main_option('script_location',str(ROOT/'migrations')); command.upgrade(cfg,'head')
    def test_save_retrieve_and_source_change(self):
        meta={'title':'Doc','language':'ru','source_type':'official'}
        doc=prepare('x.txt',b'Hello world.',meta)
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id']); self.assertEqual(snap['original'],b'Hello world.')
        result={'chunks':[{'chunk_id':'a'*64,'text':'Hello world.','tokens':5,'text_hash':'b'*64,'source_file':'x.txt'}],'warnings':['warning']}
        run=save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        self.assertEqual(latest_run(doc['id'])['chunks'][0]['text'],'Hello world.')
        self.assertEqual(latest_run(doc['id'])['warnings'],['warning'])
        changed=prepare('x.txt',b'Changed.',meta,doc['id']); write_document(changed,str(uuid.uuid4()),replace=True)
        self.assertIsNone(latest_run(doc['id']))
        with self.assertRaises(StaleDocument): save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))

    def test_index_builds_once_and_preserves_previous_on_failure(self):
        from src.indexing import index_document
        from src.index_repository import active
        from src.repository import Repository
        repository=Repository()
        repository.save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('index-build.txt',b'Index build example.',{'title':'Index build','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        result={'chunks':[{'chunk_id':'d'*64,'text':'Index build example.','tokens':4}], 'warnings':[]}
        save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        path=ROOT/'.tmp'/('qdrant-index-'+uuid.uuid4().hex)
        calls=[]
        def embed(texts, config):
            calls.append(texts)
            return [[1., 0., 0.] for text in texts]
        self.assertEqual(index_document(doc['id'],path=path,embedder=embed)['status'],'indexed')
        first=active(doc['id'])['collection']
        self.assertEqual(index_document(doc['id'],path=path,embedder=embed)['status'],'unchanged')
        self.assertEqual(len(calls),1)
        save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        self.assertEqual(index_document(doc['id'],path=path,embedder=embed)['status'],'unchanged')
        self.assertEqual(len(calls),1)
        changed={'chunks':[{'chunk_id':'e'*64,'text':'Changed chunk.','tokens':4}], 'warnings':[]}
        save_run(doc['id'],snap['revision'],changed,str(uuid.uuid4()))
        def failure(texts, config): raise RuntimeError('provider error')
        with patch('src.indexing.repo.embedding_group_cost', return_value={'cost_rub':'0.12','unknown':1,'calls':2}):
            with self.assertRaises(RuntimeError) as error: index_document(doc['id'],path=path,embedder=failure)
        self.assertEqual(error.exception.index_expenses, {'cost_rub':'0.12','unknown':1,'calls':2})
        self.assertIsNone(active(doc['id']))

    def test_replacement_during_embedding_does_not_publish_stale_vectors(self):
        from src.indexing import index_document
        from src.index_repository import active, StaleIndex, pending_collections
        from src.repository import Repository
        from src.vector_store import VectorStore
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        meta={'title':'Concurrent replacement','language':'ru','source_type':'official'}
        doc=prepare('concurrent.txt',b'Original.',meta)
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'3'*64,'text':'Original.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        path=ROOT/'.tmp'/('index-race-'+uuid.uuid4().hex)
        def embed(texts,config):
            write_document(prepare('concurrent.txt',b'Changed.',meta,doc['id']),str(uuid.uuid4()),replace=True)
            return [[1.,0.] for text in texts]
        with self.assertRaises(StaleIndex): index_document(doc['id'],path=path,embedder=embed)
        self.assertIsNone(active(doc['id']))
        store=VectorStore(path)
        try:self.assertEqual(len(store.client.get_collections().collections),0)
        finally:store.close()
        self.assertFalse(pending_collections())

    def test_replacement_queues_old_collection_for_cleanup(self):
        from src.indexing import index_document, cleanup_queued
        from src.index_repository import active, pending_collections
        from src.repository import Repository
        from src.vector_store import VectorStore
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        meta={'title':'Cleanup after replacement','language':'ru','source_type':'official'}
        doc=prepare('cleanup-replace.txt',b'Original.',meta)
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'7'*64,'text':'Original.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        path=ROOT/'.tmp'/('replacement-cleanup-'+uuid.uuid4().hex)
        index_document(doc['id'],path=path,embedder=lambda texts,config:[[1.,0.] for t in texts])
        old=active(doc['id'])['collection']
        write_document(prepare('cleanup-replace.txt',b'Changed.',meta,doc['id']),str(uuid.uuid4()),replace=True)
        self.assertIsNone(active(doc['id']))
        self.assertIn(old,pending_collections())
        self.assertTrue(cleanup_queued(path=path))
        store=VectorStore(path)
        try:self.assertFalse(store.client.collection_exists(old))
        finally:store.close()
        self.assertNotIn(old,pending_collections())

    def test_replace_and_reindex_removes_old_collection(self):
        from src.indexing import index_document
        from src.index_repository import active
        from src.repository import Repository
        from src.vector_store import VectorStore
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        meta={'title':'Replacement','language':'ru','source_type':'official'}
        doc=prepare('replacement.txt',b'Original.',meta)
        write_document(doc,str(uuid.uuid4()))
        path=ROOT/'.tmp'/('replacement-'+uuid.uuid4().hex)
        def embed(texts,config):return [[1.,0.] for text in texts]
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'1'*64,'text':'Original.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        index_document(doc['id'],path=path,embedder=embed)
        old=active(doc['id'])['collection']
        write_document(prepare('replacement.txt',b'Changed.',meta,doc['id']),str(uuid.uuid4()),replace=True)
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'2'*64,'text':'Changed.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        index_document(doc['id'],path=path,embedder=embed)
        new=active(doc['id'])['collection']
        self.assertNotEqual(old,new)
        store=VectorStore(path)
        try:
            self.assertFalse(store.client.collection_exists(old))
            self.assertTrue(store.client.collection_exists(new))
        finally:store.close()

    def test_transient_503_retries_same_batch(self):
        from src.indexing import index_document
        from src.embeddings import EmbeddingError
        from src.repository import Repository
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('retry.txt',b'Retry.',{'title':'Retry','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'8'*64,'text':'Retry.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        calls=[]
        def embed(texts,config):
            calls.append(texts)
            if len(calls)<3: raise EmbeddingError('RouterAI: HTTP 503')
            return [[1.,0.]]
        with patch('src.indexing.time.sleep'):
            result=index_document(doc['id'],path=ROOT/'.tmp'/('retry-'+uuid.uuid4().hex),embedder=embed)
        self.assertEqual(result['status'],'indexed')
        self.assertEqual(calls,[['Retry.']]*3)

    def test_batches_preserve_every_vector_and_payload(self):
        from src.indexing import index_document
        from src.index_repository import active
        from src.repository import Repository
        from src.vector_store import VectorStore
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('batches.txt',b'Multiple chunks.',{'title':'Batches','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        chunks=[{'chunk_id':f'{i:064x}','text':f'Chunk {i}','tokens':3,'source_file':f'file-{i}.txt','document_id':doc['id']} for i in range(20)]
        save_run(doc['id'],snap['revision'],{'chunks':chunks, 'warnings':[]},str(uuid.uuid4()))
        path=ROOT/'.tmp'/('batches-'+uuid.uuid4().hex)
        def embed(texts,config):
            return [[float(int(t.split()[-1])+1),1.0] for t in texts]
        result=index_document(doc['id'],path=path,embedder=embed)
        self.assertEqual(result['chunks'],20)
        store=VectorStore(path)
        try:
            collection=active(doc['id'])['collection']
            self.assertEqual(store.count(collection),20)
            for chunk in chunks:
                point_id=str(uuid.uuid5(uuid.NAMESPACE_URL,chunk['chunk_id']))
                point=store.client.retrieve(collection,ids=[point_id],with_payload=True,with_vectors=True)[0]
                self.assertEqual(point.payload,chunk)
                # Qdrant normalizes cosine vectors: their component ratio must be preserved.
                self.assertAlmostEqual(point.vector[0]/point.vector[1],float(int(chunk['text'].split()[-1])+1),places=4)
        finally:store.close()

    def test_combined_job_prepares_before_indexing(self):
        import time
        from src.indexing import start_job, job_status
        from src.repository import Repository
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('combined.txt',b'Combined document.',{'title':'Combined','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        def fake_index(document_id, progress):
            run=latest_run(document_id)
            self.assertIsNotNone(run)
            self.assertTrue(any('Combined document.' in c['text'] for c in run['chunks']))
            return {'status':'indexed','chunks':len(run['chunks']),'expenses':{'cost_rub':'0','unknown':0,'calls':0}}
        with patch('src.indexing.index_document',side_effect=fake_index):
            start_job(doc['id'],prepare=True)
            for _ in range(100):
                state=job_status()
                if state['state'] != 'running':break
                time.sleep(.02)
        self.assertEqual(state['state'],'completed',state)
        self.assertEqual(state['result']['chunks'],1)

    def test_combined_job_does_not_index_if_preparation_fails(self):
        import time
        from src.indexing import start_job, job_status
        with patch('src.indexing.index_document') as index:
            start_job(str(uuid.uuid4()),prepare=True)
            for _ in range(100):
                state=job_status()
                if state['state'] != 'running':break
                time.sleep(.02)
        self.assertEqual(state['state'],'error',state)
        index.assert_not_called()

    def test_search_active_documents_and_rejects_mutation(self):
        from src.indexing import index_document
        from src.search_service import search_documents, SearchError
        from src.repository import Repository
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3', 'vector_enabled':'false', 'bm25_enabled':'false'})
        path=ROOT/'.tmp'/('search-'+uuid.uuid4().hex)
        doc=prepare('search.txt',b'Git status example.',{'title':'Search','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'4'*64,'text':'Git status example.','tokens':3,'document_id':doc['id']}], 'warnings':[]},str(uuid.uuid4()))
        index_document(doc['id'],path=path,embedder=lambda texts,config:[[1.,0.] for t in texts])
        # The isolated database may hold other test documents, so constrain the snapshot.
        from src.index_repository import active
        with patch('src.search_service.active_generations',side_effect=lambda:[active(doc['id'])]):
            result=search_documents('status',path=path,embedder=lambda texts,config:[[1.,0.]])
            self.assertEqual(result['rrf'][0]['chunk_id'],'4'*64)
            queries = []
            def embed_batch(texts, config):
                queries.append(texts)
                return [[1., 0.] for _ in texts]
            combined = search_documents('status', context_query='Git', path=path, embedder=embed_batch)
            self.assertEqual(queries, [['status', 'Git']])
            self.assertEqual([item['chunk_id'] for item in combined['rrf']], ['4'*64])
            self.assertEqual(combined['context']['rrf'], [])
            queries.clear()
            planned = search_documents('status', search_groups=[['status', 'working tree'], ['Git', 'Status']],
                                       context_query='git', path=path, embedder=embed_batch)
            self.assertEqual(queries, [['status', 'working tree', 'Git']])
            self.assertEqual(len(planned['query_results']), 3)
            self.assertEqual([item['chunk_id'] for item in planned['rrf']], ['4'*64])
        with patch('src.search_service.active_generations',side_effect=[[active(doc['id'])],[]]):
            with self.assertRaises(SearchError):search_documents('status',path=path,embedder=lambda texts,config:[[1.,0.]])

    def test_index_activation_requires_current_document_and_model(self):
        from src.index_repository import activate, active, StaleIndex
        from src.repository import Repository
        repository=Repository()
        repository.save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('index.txt',b'Index example.',{'title':'Index','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        result={'chunks':[{'chunk_id':'c'*64,'text':'Index example.','tokens':4}], 'warnings':[]}
        run=save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        self.assertIsNone(activate(doc['id'],run,snap['revision'],'baai/bge-m3','generation_a',1))
        self.assertEqual(active(doc['id'])['collection'],'generation_a')
        repository.save_settings({'embedding_model':'other-model'})
        self.assertIsNone(active(doc['id']))
        with self.assertRaises(StaleIndex):
            activate(doc['id'],run,snap['revision'],'baai/bge-m3','generation_b',1)
        repository.save_settings({'embedding_model':'baai/bge-m3'})

    def test_interrupted_index_job_is_reported_after_restart(self):
        from src.indexing import job_status
        from src.repository import Repository
        job_id=str(uuid.uuid4())
        repo=Repository()
        repo.log(job_id,'index_job','running',payload={'document_id':'example'})
        with patch('src.indexing._job', {'state':'idle'}):
            status=job_status()
            self.assertEqual(status['state'],'interrupted')
            self.assertEqual(status['document_id'],'example')
            repo.log(job_id,'index_job','error',payload={'document_id':'example'})
            self.assertEqual(job_status()['state'],'idle')

    def test_index_cost_groups_are_separate_and_unknown_is_preserved(self):
        from decimal import Decimal
        from src.repository import Repository
        repo=Repository()
        group=str(uuid.uuid4())
        repo.log(str(uuid.uuid4()),'embedding','ok','model',1,Decimal('0.0000000123'),{'group_id':group})
        repo.log(str(uuid.uuid4()),'embedding','error','model',1,None,{'group_id':group})
        repo.log(str(uuid.uuid4()),'embedding','ok','model',1,Decimal('8.2'),{'group_id':'different'})
        result=repo.embedding_group_cost(group)
        self.assertEqual(Decimal(result['cost_rub']),Decimal('0.0000000123'))
        self.assertEqual((result['unknown'],result['calls']),(1,2))

    def test_recovery_removes_only_recorded_unpublished_collection(self):
        from src.indexing import cleanup_pending
        from src.index_repository import register_pending, pending_collections
        from src.vector_store import VectorStore
        path=ROOT/'.tmp'/('recovery-'+uuid.uuid4().hex)
        store=VectorStore(path)
        try:
            orphan='generation_'+uuid.uuid4().hex
            live='generation_'+uuid.uuid4().hex
            register_pending('orphan-document',orphan)
            store.create(2,name=orphan)
            store.create(2,name=live)
            cleanup_pending(store,str(uuid.uuid4()))
            self.assertFalse(store.client.collection_exists(orphan))
            self.assertTrue(store.client.collection_exists(live))
            self.assertNotIn(orphan,pending_collections())
        finally:store.close()

    def test_delete_cleans_only_deleted_document_collection(self):
        from src.indexing import index_document, cleanup_deleted_document
        from src.index_repository import active, retired_collection
        from src.document_repository import delete_document
        from src.repository import Repository
        from src.vector_store import VectorStore
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        doc=prepare('cleanup.txt',b'Cleanup.',{'title':'Cleanup','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        save_run(doc['id'],snap['revision'],{'chunks':[{'chunk_id':'9'*64,'text':'Cleanup.','tokens':2}], 'warnings':[]},str(uuid.uuid4()))
        path=ROOT/'.tmp'/('cleanup-'+uuid.uuid4().hex)
        index_document(doc['id'],path=path,embedder=lambda texts,config:[[1.,0.] for text in texts])
        name=active(doc['id'])['collection']
        self.assertTrue(cleanup_deleted_document(doc['id'],path=path))
        store=VectorStore(path)
        try:self.assertTrue(store.client.collection_exists(name))
        finally:store.close()
        delete_document(doc['id'],str(uuid.uuid4()))
        self.assertTrue(cleanup_deleted_document(doc['id'],path=path))
        self.assertIsNone(retired_collection(doc['id']))
        store=VectorStore(path)
        try:self.assertFalse(store.client.collection_exists(name))
        finally:store.close()

    def test_index_is_inactive_after_replacement_or_deletion(self):
        from src.index_repository import activate, active
        from src.document_repository import delete_document
        from src.repository import Repository
        Repository().save_settings({'chunking_plugin':'local', 'embedding_model':'baai/bge-m3'})
        meta={'title':'Life cycle','language':'ru','source_type':'official'}
        doc=prepare('life.txt',b'Initial.',meta)
        write_document(doc,str(uuid.uuid4()))
        snap=snapshot(doc['id'])
        result={'chunks':[{'chunk_id':'f'*64,'text':'Initial.','tokens':3}], 'warnings':[]}
        run=save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        activate(doc['id'],run,snap['revision'],'baai/bge-m3','generation_life',1)
        replacement=prepare('life.txt',b'Changed.',meta,doc['id'])
        write_document(replacement,str(uuid.uuid4()),replace=True)
        self.assertIsNone(active(doc['id']))
        delete_document(doc['id'],str(uuid.uuid4()))
        self.assertIsNone(active(doc['id']))

    def test_changing_plugin_hides_old_result(self):
        from src.repository import Repository
        repository=Repository()
        doc=prepare('plugin.txt',b'Plugin test.',{'title':'Plugin','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        repository.save_settings({'chunking_plugin':'local'})
        snap=snapshot(doc['id'])
        result={'chunks':[{'chunk_id':'b'*64,'text':'Plugin test.','tokens':3}], 'warnings':[]}
        save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        self.assertIsNotNone(latest_run(doc['id']))
        repository.save_settings({'chunking_plugin':'docling'})
        self.assertIsNone(latest_run(doc['id']))
        with self.assertRaises(StaleDocument):
            save_run(doc['id'],snap['revision'],result,str(uuid.uuid4()))
        repository.save_settings({'chunking_plugin':'local'})
        self.assertIsNotNone(latest_run(doc['id']))

    def test_website_selection_not_overridden_by_environment(self):
        from src.repository import Repository
        repo=Repository(); repo.save_settings({'chunking_plugin':'local'})
        doc=prepare('env.txt',b'Text.',{'title':'Env','language':'ru','source_type':'official'})
        write_document(doc,str(uuid.uuid4()))
        with patch.dict(os.environ, {'CHUNKING_PLUGIN':'docling'}):
            self.assertEqual(snapshot(doc['id'])['plugin'],'local')

if __name__=='__main__': unittest.main()
