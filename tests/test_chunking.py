import unittest
from src.chunking import chunk_sections, ChunkingError, _overlap_start, _sentences, _list_items
from src.document_structure import Block

words=lambda value:len(value.split())
class ChunkTests(unittest.TestCase):
    def test_overlap_sentence_and_no_cross_section(self):
        blocks=[Block('heading','First'),Block('paragraph','One two. Three four.'),Block('paragraph','Five six. Seven eight.'),Block('paragraph','Nine ten. Eleven twelve.'),Block('heading','Second'),Block('paragraph','Other section.')]
        chunks=chunk_sections(blocks,words,target=8,soft_limit=12,overlap_ratio=.15)
        self.assertEqual([x.section for x in chunks],['First','First','Second'])
        self.assertIn('Five six. Seven eight.',chunks[0].text)
        self.assertTrue(chunks[1].text.startswith('Seven eight.'))
        self.assertNotIn('Nine ten',chunks[2].text)
    def test_overlap_copies_only_last_complete_sentence(self):
        blocks=[Block('paragraph','Alpha beta gamma delta. Final short.'), Block('paragraph','Next paragraph follows now.'), Block('paragraph','Another paragraph follows now.')]
        chunks=chunk_sections(blocks,words,target=6,soft_limit=10,overlap_ratio=.15)
        self.assertGreater(len(chunks),1)
        self.assertTrue(chunks[1].text.startswith('Final short.'))
        self.assertNotIn('Alpha beta gamma delta.',chunks[1].text)

    def test_long_paragraph_splits_sentences_and_progresses(self):
        source=' '.join(f'Sentence number {n} is complete.' for n in range(1,13))
        chunks=chunk_sections([Block('paragraph',source)],words,target=20,soft_limit=25,overlap_ratio=.15)
        self.assertGreater(len(chunks),2)
        for n in range(1,13): self.assertTrue(any(f'Sentence number {n} is complete.' in c.text for c in chunks))
        for a,b in zip(chunks,chunks[1:]): self.assertEqual(a.text.split('\n\n')[-1],b.text.split('\n\n')[0])
    def test_long_prose_exceeding_hard_limit_is_split(self):
        source=' '.join(f'Sentence {n} contains enough words.' for n in range(18))
        result=chunk_sections([Block('paragraph',source)],words,target=12,soft_limit=18,hard_limit=25)
        self.assertGreater(len(result),2)
        for n in range(18): self.assertTrue(any(f'Sentence {n} contains enough words.' in chunk.text for chunk in result))
        self.assertTrue(all(chunk.tokens<=25 for chunk in result))
    def test_single_sentence_over_soft_limit_is_preserved(self):
        sentence = 'word ' * 15
        chunks = chunk_sections([Block('paragraph', sentence)], words, target=5, soft_limit=10, hard_limit=20)
        self.assertEqual(chunks[0].text, sentence.strip())

    def test_abbreviations_do_not_split_sentences(self):
        text = 'Используйте Git и т. д. Затем проверьте результат. Например, в г. Москве это работает.'
        self.assertEqual(_sentences(text), ['Используйте Git и т. д.', 'Затем проверьте результат.', 'Например, в г. Москве это работает.'])

    def test_single_sentence_exceeding_hard_limit_is_rejected(self):
        with self.assertRaises(ChunkingError):
            chunk_sections([Block('paragraph','word '*40)],words,target=5,soft_limit=10,hard_limit=20)
    def test_overlap_counts_sentences_before_expanding_to_paragraphs(self):
        units=[('Long paragraph with many many many words. Brief ending.', False), ('Tiny ending.', False)]
        self.assertEqual(_overlap_start(units,0,2,words,5),0)
        self.assertEqual(_overlap_start(units,0,2,words,2),1)

    def test_heading_hierarchy_is_carried_into_chunks(self):
        blocks=[Block('heading','== Глава',level=2),Block('heading','=== Раздел',level=3),Block('heading','==== Подраздел',level=4),Block('paragraph','Текст.')]
        chunk=chunk_sections(blocks,words)[0]
        self.assertEqual(chunk.chapter,'Глава')
        self.assertEqual(chunk.section,'Раздел')
        self.assertEqual(chunk.subsection,'Подраздел')

    def test_warning_remains_one_block_even_if_longer_than_soft_limit(self):
        warning='Warning first sentence. Warning second sentence. Warning third sentence.'
        chunks=chunk_sections([Block('warning',warning)],words,target=4,soft_limit=6,hard_limit=50)
        self.assertEqual(len(chunks),1)
        self.assertEqual(chunks[0].text,warning)

    def test_oversized_list_splits_only_between_whole_items(self):
        items = [f'- Item {n} has several words.' for n in range(12)]
        chunks = chunk_sections([Block('list', '\n'.join(items))], words, target=10, soft_limit=15, hard_limit=25)
        self.assertGreater(len(chunks), 1)
        for item in items:
            self.assertTrue(any(item in chunk.text for chunk in chunks))
        for left, right in zip(chunks, chunks[1:]):
            self.assertTrue(any(item in left.text and item in right.text for item in items))
        self.assertTrue(all(chunk.tokens <= 25 for chunk in chunks))

    def test_nested_list_stays_with_parent(self):
        text = '- Parent\n  - Nested one\n  - Nested two\n- Second parent'
        self.assertEqual(_list_items(text), ['- Parent\n  - Nested one\n  - Nested two', '- Second parent'])

    def test_unbreakable_list_item_is_rejected(self):
        text = '- ' + 'word ' * 30 + '\n- short item'
        with self.assertRaises(ChunkingError):
            chunk_sections([Block('list', text)], words, target=5, soft_limit=10, hard_limit=20)

    def test_large_code_not_silently_cut(self):
        with self.assertRaises(ChunkingError): chunk_sections([Block('code','word '*40)],words,target=5,soft_limit=10,hard_limit=20)
    def test_command_keeps_explanation_without_colon(self):
        blocks = [Block('paragraph', 'Предыдущий текст. ' * 4), Block('paragraph', 'Запустите команду следующим образом.'), Block('code', '$ git status\nOn branch main'), Block('paragraph', 'Последующий текст. ' * 4)]
        chunks = chunk_sections(blocks, words, target=8, soft_limit=16)
        self.assertTrue(any('Запустите команду следующим образом.' in chunk.text and '$ git status' in chunk.text for chunk in chunks))

    def test_explanation_and_command_stay_together(self):
        chunks=chunk_sections([Block('paragraph','Run command:'),Block('code','$ git status\nOn branch main'),Block('paragraph','All clean.')],words,target=5,soft_limit=12)
        self.assertTrue(any('Run command:' in c.text and '$ git status' in c.text for c in chunks))

if __name__=='__main__': unittest.main()