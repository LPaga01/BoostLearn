import unittest
from unittest.mock import patch

import rag


class AnalysisTests(unittest.TestCase):
    def test_groups_cover_all_chunks_in_order(self):
        chunks = [{"text": "x" * 1000, "page": index + 1} for index in range(65)]
        groups = rag.document_groups(chunks)
        self.assertGreater(len(groups), 1)
        self.assertEqual([chunk for group in groups for chunk in group], chunks)

    @patch('rag.generate_answer')
    def test_short_document_is_used_whole(self, generate):
        chunks = [{"text": "Primo argomento", "page": 1}, {"text": "Secondo argomento", "page": 2}]
        generate.return_value = {"text": "Due argomenti", "pages": [1, 2]}
        result = rag.analyze_document('Dividi in macroargomenti', chunks, 'fake', 'model', {})
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.args[1], chunks)
        self.assertFalse(result['summarized'])
        self.assertTrue(generate.call_args.kwargs['overview'])

    @patch('rag.generate_answer')
    def test_long_document_cache_and_model_isolation(self, generate):
        chunks = [{"text": "x" * 1000, "page": index + 1} for index in range(65)]
        def response(question, sources, *args, **kwargs):
            pages = sorted({page for source in sources for page in source.get('pages', [source.get('page')])})
            return {"text": "Sintesi delle fonti", "pages": pages}
        generate.side_effect = response
        cache = {}
        groups = rag.document_groups(chunks)
        result = rag.analyze_document('Cinque macroargomenti', chunks, 'fake', 'model', cache)
        self.assertTrue(result['summarized'])
        self.assertEqual(generate.call_count, len(groups) + 1)
        self.assertEqual(len(cache), len(groups))
        rag.analyze_document('Ora fammi uno schema', chunks, 'fake', 'model', cache)
        self.assertEqual(generate.call_count, len(groups) + 2)
        rag.analyze_document('Uno schema', chunks, 'fake', 'another-model', cache)
        self.assertEqual(generate.call_count, 2 * len(groups) + 3)

    @patch('rag.generate_answer', return_value={"text": rag.NO_ANSWER, "pages": []})
    def test_failed_summary_is_not_cached(self, generate):
        chunks = [{"text": "x" * 1000, "page": index + 1} for index in range(35)]
        cache = {}
        with self.assertRaises(ValueError):
            rag.analyze_document('Riassumi', chunks, 'fake', 'model', cache)
        self.assertEqual(cache, {})

    def test_summary_cannot_cite_unknown_pages(self):
        with self.assertRaises(ValueError):
            rag.validate_answer('{"found":true,"answer":"Testo","pages":[99]}',
                                [{"text": "Sintesi", "pages": [1, 2]}])
        valid = rag.validate_answer('{"found":true,"answer":"Testo","pages":[2]}',
                                    [{"text": "Sintesi", "pages": [1, 2]}])
        self.assertEqual(valid['pages'], [2])

    def test_empty_document_rejected(self):
        with self.assertRaises(ValueError):
            rag.analyze_document('Riassumi', [], 'fake', 'model', {})
