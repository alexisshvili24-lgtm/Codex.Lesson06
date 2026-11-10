import unittest
from src.rrf import fuse

class RRFTest(unittest.TestCase):
    def test_fusion_uses_original_ranks_and_filters_without_duplicates(self):
        vector = [{'chunk_id':'a','position':1,'accepted':True}, {'chunk_id':'b','position':2,'accepted':False}, {'chunk_id':'c','position':3,'accepted':True}]
        bm25 = [{'chunk_id':'c','position':1,'accepted':True}, {'chunk_id':'a','position':2,'accepted':True}]
        result = fuse(vector, bm25)
        self.assertEqual({x['chunk_id'] for x in result},{'a','c'})
        entry = next(x for x in result if x['chunk_id']=='c')
        self.assertAlmostEqual(entry['score'],1/63+1/61)
        self.assertEqual((entry['vector_position'],entry['bm25_position']),(3,1))

    def test_empty_results(self):
        self.assertEqual(fuse([],[]),[])
