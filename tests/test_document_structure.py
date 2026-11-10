import io
import unittest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from src.document_structure import prepare_structure, StructureError

class StructureTests(unittest.TestCase):
    def test_markdown_preserves_heading_code_and_text(self):
        text = '# Раздел\n\nПервый абзац\n\n```sh\ngit status\n```\n\nПоследний\n'
        result = prepare_structure('example.md', text.encode('utf-8'))
        self.assertEqual(''.join(b.text for b in result.blocks), text)
        self.assertEqual([b.kind for b in result.blocks], ['heading','paragraph','code','paragraph'])
        self.assertIn('git status', next(b.text for b in result.blocks if b.kind == 'code'))
    def test_asciidoc_and_html(self):
        result = prepare_structure('example.asc', b'NAME\n----\n\nDescription\n')
        self.assertEqual(result.blocks[0].kind, 'heading')
        html = prepare_structure('example.html', '<h1>Git</h1><p>Текст</p><script>bad</script><pre>git status</pre>'.encode())
        self.assertEqual([b.kind for b in html.blocks], ['heading','paragraph','code'])
        self.assertNotIn('bad', ''.join(b.text for b in html.blocks))
    def test_pdf_marks_heuristics(self):
        writer=PdfWriter(); page=writer.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 20 100 Td (git status) Tj ET'); page[NameObject('/Contents')]=writer._add_object(stream)
        output=io.BytesIO(); writer.write(output)
        result=prepare_structure('x.pdf', output.getvalue())
        self.assertEqual(result.status,'needs_review')
        self.assertEqual(result.blocks[0].page,1)
        self.assertIn('git status',result.blocks[0].text)
    def test_pdf_command_and_indented_output_stay_together(self):
        writer=PdfWriter(); page=writer.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Courier')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject(); stream.set_data(b'BT /F1 11 Tf 20 200 Td ($ git add -h) Tj 0 -15 Td (usage: git add) Tj 0 -28 Td (    -n, --dry-run) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream); output=io.BytesIO(); writer.write(output)
        result=prepare_structure('x.pdf', output.getvalue())
        code=[b.text for b in result.blocks if b.kind=='code']
        self.assertEqual(len(code),1)
        self.assertIn('$ git add -h',code[0]); self.assertIn('    -n, --dry-run',code[0])
    def test_asciidoc_source_and_warning_are_not_headings(self):
        source='=== Section\n\nBefore:\n[source,console]\n----\n$ git status\noutput\n----\n[NOTE]\n====\nWarning text.\n====\n'
        result=prepare_structure('test.asc',source.encode())
        self.assertEqual(''.join(b.text for b in result.blocks), source)
        self.assertEqual(sum(b.kind=='heading' for b in result.blocks),1)
        self.assertTrue(any(b.kind=='code' and '$ git status' in b.text and 'output' in b.text for b in result.blocks))
        self.assertTrue(any(b.kind=='warning' and 'Warning text.' in b.text for b in result.blocks))
    def test_code_delimiter_does_not_make_prose_a_heading(self):
        source='=== Topic\n\nПодробный текст перед примером команды и пояснение, которое описывает ситуацию.\n----\n$ git status\n----\n'
        result=prepare_structure('x.asc',source.encode())
        headings=[b.text for b in result.blocks if b.kind=='heading']
        self.assertEqual(len(headings),1)
        self.assertTrue(any(b.kind=='code' and '$ git status' in b.text for b in result.blocks))
        self.assertEqual(''.join(b.text for b in result.blocks),source)

    def test_markdown_list_is_a_single_semantic_block(self):
        source = '# Список\n\n- Первый пункт. Ещё текст.\n- Второй пункт. Продолжение.\n'
        result = prepare_structure('x.md', source.encode())
        self.assertEqual(''.join(block.text for block in result.blocks), source)
        self.assertEqual([block.kind for block in result.blocks], ['heading', 'list'])

    def test_empty_rejected(self):
        with self.assertRaises(StructureError): prepare_structure('x.txt', b'')

if __name__ == '__main__': unittest.main()