import importlib.util
import unittest
from io import BytesIO

from pdf_export import answer_pdf

READY = all(importlib.util.find_spec(name) for name in ('reportlab', 'pypdf'))


@unittest.skipUnless(READY, 'Dipendenze PDF non installate')
class PdfExportTests(unittest.TestCase):
    def test_answer_question_and_references_are_exported(self):
        from pypdf import PdfReader
        result = {'question': 'Spiega quantità e qualità <test>',
                  'text': '## Concetti\nUna **risposta** con accenti: è così.\n- Primo punto\n- Secondo punto',
                  'pages': [2, 5], 'summarized': True}
        content = answer_pdf(result, 'Dispensa.pdf')
        self.assertTrue(content.startswith(b'%PDF'))
        reader = PdfReader(BytesIO(content))
        text = ''.join(page.extract_text() for page in reader.pages)
        for expected in ('quantità', '<test>', 'qualità', 'è così', '2, 5', 'sintesi intermedie', 'Dispensa.pdf'):
            self.assertIn(expected, text)

    def test_long_answer_flows_across_pages(self):
        from pypdf import PdfReader
        content = answer_pdf({'question':'Riassumi', 'text': '\n'.join(
            f'Punto {i}: una spiegazione abbastanza lunga per verificare il passaggio alla pagina successiva.'
            for i in range(100)), 'pages':[]}, 'Test.pdf')
        reader = PdfReader(BytesIO(content))
        self.assertGreater(len(reader.pages), 1)
        self.assertIn('Punto 99', reader.pages[-1].extract_text())

    def test_formula_and_markdown_are_readable(self):
        from pypdf import PdfReader
        result = {'question':'Spiega RSA', 'text': '```markdown\n### RSA\n- **Formula:** $c = p^E \\bmod N$\n- *Ordine:* $A \\rightarrow B$\n```', 'pages':[8]}
        reader = PdfReader(BytesIO(answer_pdf(result, 'Dispensa.pdf')))
        text = ''.join(page.extract_text() for page in reader.pages)
        for expected in ('RSA', 'c = p^E mod N', 'A -> B'):
            self.assertIn(expected, text)
        for unwanted in ('###', '**', '\\bmod', '\\rightarrow', '```'):
            self.assertNotIn(unwanted, text)


if __name__ == '__main__':
    unittest.main()
