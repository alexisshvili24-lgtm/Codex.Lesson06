import io, unittest, zipfile
from unittest.mock import patch
from src.chunk_pipeline import prepare_chunks, PreparationError

def zip_bytes(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,text in files.items(): z.writestr(name,text)
    return out.getvalue()

class PipelineTest(unittest.TestCase):
    def test_zip_files_remain_distinct_and_idempotent(self):
        data=zip_bytes({'one.md':'# Section\n\nFirst text.', 'two.md':'# Section\n\nSecond text.'})
        meta={'id':'doc-1','title':'Example','source_url':'https://example.org','language':'ru','source_type':'official','version':'v1'}
        first=prepare_chunks(meta,'book.zip',data,lambda text:len(text.split()))
        second=prepare_chunks(meta,'book.zip',data,lambda text:len(text.split()))
        self.assertEqual(first,second)
        self.assertEqual({c['source_file'] for c in first['chunks']},{'one.md','two.md'})
        self.assertTrue(all(not ('First text.' in c['text'] and 'Second text.' in c['text']) for c in first['chunks']))
        self.assertTrue(all(c['document_id']=='doc-1' and len(c['text_hash'])==64 for c in first['chunks']))
    def test_engine_can_be_selected_and_recorded(self):
        result=prepare_chunks({'id':'doc'},'x.txt',b'First sentence. Second sentence.',lambda text:len(text.split()),plugin='local')
        self.assertEqual(result['plugin'],'local')
        self.assertTrue(all(c['plugin']=='local' for c in result['chunks']))

    def test_unknown_engine_fails_explicitly(self):
        with self.assertRaises(PreparationError):
            prepare_chunks({'id':'doc'},'x.txt',b'Text',lambda text:1,plugin='not_installed')

    def test_docling_missing_environment_gives_clear_error(self):
        with patch('src.chunk_plugins.docling.docling_python',return_value=None):
            with self.assertRaisesRegex(PreparationError, 'окружение Docling|Окружение Docling'):
                prepare_chunks({'id':'doc'},'x.md',b'# Heading',lambda text:1,plugin='docling')

    def test_registered_external_plugin_is_used(self):
        from src.chunking import Chunk
        class ExternalPlugin:
            def prepare_file(self,path,text,count):
                return [Chunk('External',text,count(text))], ['external plugin']
        class Entry:
            def load(self): return ExternalPlugin
        with patch('src.chunk_plugins.entry_points',return_value=[Entry()]):
            result=prepare_chunks({'id':'doc'},'x.txt',b'External text.',lambda t:len(t.split()),plugin='external')
        self.assertEqual(result['chunks'][0]['section'],'External')
        self.assertEqual(result['chunks'][0]['plugin'],'external')
        self.assertIn('external plugin',result['warnings'][0])

    def test_asciidoc_markup_does_not_become_overlap_or_separate_chunk(self):
        text = """[[anchor]]
=== Section

First paragraph has useful text. Last sentence is useful.

====

include::chapter.asc[]

Next paragraph has useful text. More details here.

[source,console]
----
echo '[[keep]]'
----
"""
        result=prepare_chunks({'id':'doc'},'x.asc',text.encode(),lambda t:len(t.split()))
        combined='\n'.join(c['text'] for c in result['chunks'])
        self.assertNotIn('[[anchor]]',combined)
        self.assertNotIn('include::chapter.asc[]',combined)
        self.assertNotIn('\n====',combined)
        self.assertIn("echo '[[keep]]'",combined)
        self.assertTrue(all(c['text'].strip() != '====' for c in result['chunks']))

    def test_include_inside_code_is_preserved_and_warned(self):
        text='=== Section\n\n[source,ruby]\n----\ninclude::example.rb[]\n----\n'
        result=prepare_chunks({'id':'doc'},'x.asc',text.encode(),lambda t:len(t.split()))
        self.assertIn('include::example.rb[]', result['chunks'][0]['text'])
        self.assertTrue(any('include' in warning for warning in result['warnings']))

    def test_adoc_txt_uses_asciidoc_headings(self):
        text='NAME\n----\n\nDescription text.\n'
        result=prepare_chunks({'id':'doc'},'git-status.adoc.txt',text.encode(),lambda t:len(t.split()))
        self.assertEqual(result['chunks'][0]['section'],'NAME')

    def test_pdf_not_used(self):
        with self.assertRaises(PreparationError): prepare_chunks({'id':'1'},'x.pdf',b'data',lambda t:1)

if __name__=='__main__': unittest.main()