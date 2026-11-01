import importlib.util
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import rag
from fixtures import demo_pdf

HAS_PDF = importlib.util.find_spec("pypdf") is not None
HAS_CHROMA = importlib.util.find_spec("chromadb") is not None


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.passages = [{"text": "Il gruppo ha massimo tre persone.", "page": 2}]

    def test_valid_answer(self):
        result = rag.validate_answer(json.dumps({"found": True, "answer": "Tre.", "pages": [2, 2]}), self.passages)
        self.assertEqual(result, {"text": "Tre.", "pages": [2]})

    def test_abstention(self):
        result = rag.validate_answer('{"found": false}', self.passages)
        self.assertEqual(result["text"], rag.NO_ANSWER)
        self.assertEqual(result["pages"], [])

    def test_reject_unretrieved_page(self):
        with self.assertRaises(ValueError):
            rag.validate_answer('{"found":true,"answer":"Tre","pages":[9]}', self.passages)

    def test_reject_invalid_structures(self):
        invalid = ["non JSON", "[]", "null", '{"found":"false"}',
                   '{"found":true,"answer":"","pages":[2]}',
                   '{"found":true,"answer":"Tre","pages":[]}',
                   '{"found":true,"answer":"Tre","pages":[true]}']
        for content in invalid:
            with self.subTest(content=content), self.assertRaises(ValueError):
                rag.validate_answer(content, self.passages)

    @patch("rag.get_client")
    def test_generation_checks_citations(self, client):
        generate = client.return_value.models.generate_content
        generate.return_value = SimpleNamespace(text='{"found":true,"answer":"Tre","pages":[2]}',
                                               usage_metadata=SimpleNamespace(total_token_count=90))
        result = rag.generate_answer("Quante persone?", self.passages, "fake", "test")
        self.assertEqual(result["tokens"], 90)
        self.assertEqual(generate.call_args.kwargs["config"]["response_mime_type"], "application/json")

    @patch('rag.get_client')
    def test_overview_prompt_treats_organization_as_a_valid_task(self, client):
        generate = client.return_value.models.generate_content
        generate.return_value = SimpleNamespace(text='{"found":true,"answer":"Tre temi","pages":[2]}',
                                               usage_metadata=SimpleNamespace(total_token_count=20))
        rag.generate_answer('Dividi in 3 macroargomenti', self.passages, 'fake', 'test', overview=True)
        config = generate.call_args.kwargs['config']
        self.assertEqual(config['system_instruction'], rag.OVERVIEW_PROMPT)
        self.assertIn('Dividi in 3 macroargomenti', generate.call_args.kwargs['contents'])

    @patch("rag.get_client")
    def test_malformed_service_response(self, client):
        client.return_value.models.generate_content.return_value = SimpleNamespace(text=None)
        with self.assertRaises(ValueError):
            rag.generate_answer("Domanda", self.passages, "fake", "test")


class RetrievalTests(unittest.TestCase):
    @patch("rag.get_client")
    def test_embeddings_preserve_order_and_batches(self, client):
        request = client.return_value.models.embed_content
        def response(**kwargs):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(text)]) for text in kwargs["contents"]])
        request.side_effect = response
        self.assertEqual(rag.embed([str(i) for i in range(35)], "fake"), [[float(i)] for i in range(35)])
        self.assertEqual(request.call_count, 2)

    @patch("rag.get_client")
    def test_missing_embeddings_rejected(self, client):
        client.return_value.models.embed_content.return_value = SimpleNamespace(embeddings=[])
        with self.assertRaises(ValueError):
            rag.embed(["testo"], "fake")

    @unittest.skipUnless(HAS_CHROMA, "ChromaDB non installato")
    @patch("rag.embed")
    def test_chroma_retrieval_and_isolation(self, embed):
        chunks = [{"text": "gruppo tre", "page": 1}, {"text": "voto diciotto", "page": 2}]
        embed.return_value = [[1., 0.], [0., 1.]]
        client, collection = rag.build_index(chunks, "fake")
        other_client, other = None, None
        try:
            embed.return_value = [[0., 1.]]
            other_client, other = rag.build_index([{"text": "altro", "page": 9}], "fake")
            result = rag.retrieve(collection, "voto", "fake")
            self.assertEqual(embed.call_args.kwargs["task_type"], "RETRIEVAL_QUERY")
            self.assertEqual(result[0]["page"], 2)
            self.assertNotIn(9, [item["page"] for item in result])
            self.assertNotEqual(collection.name, other.name)
        finally:
            client.delete_collection(collection.name)
            if other:
                other_client.delete_collection(other.name)


@unittest.skipUnless(HAS_PDF, "pypdf non installato")
class PdfTests(unittest.TestCase):
    def test_real_pdf_extraction_and_page_numbers(self):
        chunks, pages, empty = rag.extract_chunks(demo_pdf(), size=150, overlap=25)
        self.assertEqual(pages, 2)
        self.assertEqual(empty, 0)
        self.assertEqual({item["page"] for item in chunks}, {1, 2})
        self.assertTrue(all(len(item["text"]) <= 150 for item in chunks))
        self.assertIn("trenta minuti", " ".join(item["text"] for item in chunks))

    def test_invalid_empty_and_oversize_pdf(self):
        for data in (b"", b"not a pdf", b"a" * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                rag.extract_chunks(data)


if __name__ == "__main__":
    unittest.main()
