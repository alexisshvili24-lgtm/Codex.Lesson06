import io
import os
import unittest
import uuid
import zipfile
from pathlib import Path
root = Path(__file__).resolve().parent.parent
os.environ['DATABASE_URL'] = 'sqlite:///' + (root / '.tmp' / ('api-zip-' + uuid.uuid4().hex + '.sqlite3')).as_posix()
from fastapi.testclient import TestClient
from src.database import engine
from app import app

def bundle(items):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,text in items.items(): z.writestr(name,text)
    return out.getvalue()

class ArchiveApiTest(unittest.TestCase):
    @unittest.skip('TestClient не завершается в текущей среде; HTTP проверяется отдельно')
    def test_upload_valid_and_reject_invalid(self):
        self.assertIn('.tmp', str(engine.url), 'Тестовая база должна быть изолирована от рабочей')
        data={'title':'Example', 'source_type':'official', 'language':'ru'}
        with TestClient(app) as client:
            valid=bundle({'index.adoc':'= Title\ninclude::chapter.asc[]\n', 'chapter.asc':'== Chapter\nTest git status\n'})
            response=client.post('/api/documents', data=data, files={'file':('book.zip',valid,'application/zip')})
            self.assertEqual(response.status_code,200,response.text)
            doc=response.json(); detail=client.get('/api/documents/'+doc['id']).json()
            self.assertIn('Test git status', detail['extracted_text'])
            invalid=bundle({'index.adoc':'= Title\ninclude::missing.asc[]'})
            failure=client.post('/api/documents', data=data, files={'file':('broken.zip',invalid,'application/zip')})
            self.assertEqual(failure.status_code,400)
            self.assertIn('missing.asc',failure.json()['detail'])
            self.assertEqual(len(client.get('/api/documents').json()),1)

if __name__=='__main__': unittest.main()