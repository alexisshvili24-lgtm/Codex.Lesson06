import os
import uuid
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///'+(Path(__file__).resolve().parent.parent/'.tmp'/('archive-test-'+uuid.uuid4().hex+'.sqlite3')).as_posix()
import io
import unittest
import zipfile
from src.archive_reader import extract_archive, read_archive_files, ArchiveError
from src.documents import extract

def bundle(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,text in files.items(): z.writestr(name,text)
    return out.getvalue()

class ArchiveTests(unittest.TestCase):
    def test_text_files_are_separate_and_includes_not_followed(self):
        data=bundle({'book/one.asc':'= One\ninclude::missing.asc[]\n','book/two.md':'# Two\nТекст\n','images/x.png':b'\x00\xff'})
        result=extract('book.zip',data)
        self.assertIn('Файл архива: book/one.asc',result)
        self.assertIn('Файл архива: book/two.md',result)
        self.assertIn('include::missing.asc[]',result)
        self.assertNotIn('images/x.png',result)
    def test_progit_omits_contributor_list(self):
        text=extract_archive(bundle({'repo/progit.asc':'= Book', 'repo/book/contributors.asc':'== Authors\nHidden contributors'}))
        self.assertNotIn('Hidden contributors',text)
        self.assertIn('= Book',text)
    def test_files_preserve_paths_and_text_without_synthetic_headings(self):
        data=bundle({'a/one.md':'# A\nAlpha', 'b/two.txt':'Beta'})
        files=read_archive_files(data)
        self.assertEqual(files,[('a/one.md','# A\nAlpha'),('b/two.txt','Beta')])

    def test_unstructured_text_accepted(self):
        self.assertIn('Текст без заголовка.',extract_archive(bundle({'readme.txt':'Текст без заголовка.'})))
    def test_invalid_paths_and_encoding_rejected(self):
        with self.assertRaises(ArchiveError): extract_archive(b'not zip')
        with self.assertRaises(ArchiveError): extract_archive(bundle({'../bad.txt':'bad'}))
        with self.assertRaises(ArchiveError): extract_archive(bundle({'bad.txt':b'\xff'}))
        with self.assertRaises(ArchiveError): extract_archive(bundle({'image.png':b'png'}))
    def test_progit_archive_contains_distinct_sections(self):
        path=Path(__file__).resolve().parent.parent/'docs/sources/progit2-ru-master.zip'
        if not path.exists(): self.skipTest('Архив Pro Git не скачан')
        text=extract_archive(path.read_bytes())
        self.assertIn('book/02-git-basics/sections/recording-changes.asc',text)
        self.assertIn('git status',text)

if __name__=='__main__': unittest.main()