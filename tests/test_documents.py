import io
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (ROOT / '.tmp' / ('documents-' + uuid.uuid4().hex + '.sqlite3')).as_posix())
from alembic import command
from alembic.config import Config
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select
from src.database import Session, Document
from src.documents import extract, prepare, DocumentError, save_document
from src.document_repository import write_document, get_document, delete_document

class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'migrations'))
        command.upgrade(config, 'head')

    def test_text_formats_and_encodings(self):
        for name in ('git.txt', 'git.md', 'git.adoc', 'git.asc'):
            self.assertEqual(extract(name, 'Привет\n git --hard'.encode('utf-8-sig')), 'Привет\n git --hard')
        self.assertEqual(extract('git.txt', 'Привет'.encode('utf-16')), 'Привет')
        self.assertIn('git --hard', extract('git.html', '<h1>Заголовок</h1><pre>git --hard</pre><script>bad</script>'.encode()))
        self.assertNotIn('bad', extract('git.html', '<p>Текст</p><script>bad</script>'.encode()))
        with self.assertRaises(DocumentError): extract('git.txt', b'\xff')
        with self.assertRaises(DocumentError): extract('x.exe', b'abc')

    def test_duplicate_upload_and_replace(self):
        meta = {'title':'Первый', 'source_type':'official', 'language':'ru'}
        item = save_document('first.txt', b'unique duplicate sample', meta, str(uuid.uuid4()))
        duplicate_meta = {**meta, 'title':'Другое название'}
        with self.assertRaisesRegex(DocumentError, 'уже загружен'):
            save_document('different.txt', b'unique duplicate sample', duplicate_meta, str(uuid.uuid4()))
        other = save_document('second.txt', b'another unique sample', duplicate_meta, str(uuid.uuid4()))
        with self.assertRaisesRegex(DocumentError, 'уже загружен'):
            save_document('replacement.txt', b'unique duplicate sample', duplicate_meta, str(uuid.uuid4()), other['id'])
        self.assertEqual(get_document(other['id'])['extracted_text'], 'another unique sample')
        self.assertIsNotNone(save_document('same.txt', b'unique duplicate sample', meta, str(uuid.uuid4()), item['id']))
    def test_pdf_upload_rejected(self):
        with self.assertRaisesRegex(DocumentError, 'Загрузка PDF отключена'):
            extract('document.pdf', b'%PDF-1.4')
    def test_save_replace_delete_and_failed_replacement(self):
        meta = {'title':'Git', 'source_type':'official', 'language':'ru', 'source_url':'https://git-scm.com'}
        original = 'git status'.encode(); item = prepare('a.md', original, meta)
        write_document(item, str(uuid.uuid4()))
        found = get_document(item['id']); self.assertEqual(found['extracted_text'], 'git status')
        with Session() as s: self.assertEqual(s.get(Document, item['id']).original, original)
        with self.assertRaises(DocumentError): prepare('a.pdf', b'invalid', meta, item['id'])
        self.assertEqual(get_document(item['id'])['extracted_text'], 'git status')
        replacement = prepare('b.txt', b'git log', meta, item['id'])
        write_document(replacement, str(uuid.uuid4()), replace=True)
        self.assertEqual(get_document(item['id'])['extracted_text'], 'git log')
        self.assertTrue(delete_document(item['id'], str(uuid.uuid4())))
        self.assertIsNone(get_document(item['id']))

if __name__ == '__main__': unittest.main()