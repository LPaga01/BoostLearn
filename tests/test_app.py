import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import progressi
from fixtures import demo_pdf, demo_topics, demo_quiz, PAGES

READY = all(importlib.util.find_spec(name) for name in ('streamlit', 'pypdf', 'dotenv'))


@unittest.skipUnless(READY, 'Dipendenze UI non installate')
class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        original = progressi.connect
        self.patches = [
            patch('progressi.connect', side_effect=lambda path=None: original(Path(self.temp.name) / 'test.sqlite3')),
            patch.dict(os.environ, {'GEMINI_API_KEY': 'fake-test-key'}),
            patch('streamlit.file_uploader', return_value=None),
            patch('rag.build_index', return_value=(Mock(), Mock())),
            patch('quiz.discover_topics', return_value=demo_topics()),
            patch('pdf_export.answer_pdf', return_value=b'%PDF-1.4\nmock'),
        ]
        mocks = [item.start() for item in self.patches]
        self.upload = mocks[2]
        from streamlit.testing.v1 import AppTest
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()

    def prepare_pdf(self):
        self.upload.return_value = SimpleNamespace(name='test.pdf', getvalue=demo_pdf)
        self.app.run()
        self.click('Prepara il documento')
        self.assertEqual(len(self.app.exception), 0)

    def test_initial_page_has_no_demo_sidebar_or_export(self):
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.title[0].value, 'BoostLearn')
        self.assertEqual(len(self.app.toggle), 0)
        self.assertEqual(len(self.app.checkbox), 0)
        self.assertEqual(len(self.app.sidebar), 0)
        self.assertEqual(len(self.app.get('download_button')), 0)

    def test_missing_key_blocks_preparation(self):
        self.upload.return_value = SimpleNamespace(name='test.pdf', getvalue=demo_pdf)
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            self.app.run()
        self.assertTrue(any('GEMINI_API_KEY' in item.value for item in self.app.warning))
        self.assertTrue(self.app.button[0].disabled)

    def test_quiz_score_and_progress_without_export(self):
        self.prepare_pdf()
        chunks = [{'text':' '.join(lines), 'page':i+1} for i,lines in enumerate(PAGES)]
        questions, report = demo_quiz(chunks, ['topic-1','topic-2','topic-3','topic-1','topic-2'], [])
        with patch('quiz.make_quiz', return_value=(questions, report)):
            self.click('Prepara un nuovo quiz')
        for radio, question in zip(self.app.radio, questions):
            radio.set_value(question['correct'])
        self.app.session_state['review_result'] = {'topic_id': 'old-topic'}
        self.click('Correggi il quiz')
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(all(row['correct'] for row in self.app.session_state['quiz_results']))
        self.assertNotIn('review_result', self.app.session_state)
        self.assertEqual(len(self.app.get('download_button')), 0)
        review = {'text':'Ripasso collegato', 'pages':[1], 'topic_id':'topic-1',
                  'passages':[], 'attempt_count':2, 'correct_count':2}
        with patch('rag.consolidated_review', return_value=review) as generate:
            self.click('Mostra il ripasso')
            self.assertEqual(len(self.app.exception), 0)
            history = generate.call_args.args[1]
            self.assertEqual(len(history), 2)
            self.assertTrue(all(item['correct'] for item in history))

    def test_search_and_document_change_clear_context(self):
        self.prepare_pdf()
        answer = {'text':'Risposta', 'pages':[1], 'passages':[], 'summarized':False, 'request':'Domanda'}
        with patch('rag.answer_request', return_value=answer):
            self.app.text_input[0].set_value('Domanda')
            self.click('Rispondi')
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.get('download_button')), 1)
        self.upload.return_value = None
        self.app.run()
        for key in ('result', 'topics', 'request_context', 'summaries'):
            self.assertNotIn(key, self.app.session_state)

    def test_overview_routes_to_analysis(self):
        self.prepare_pdf()
        answer = {'text':'Macroargomenti', 'pages':[1], 'passages':[], 'summarized':True}
        with patch('rag.understand_request', return_value={'route':'overview','request':'Cinque macroargomenti','clarification':''}), \
             patch('rag.analyze_document', return_value=answer) as analyze, patch('rag.retrieve') as retrieve:
            self.assertEqual(len(self.app.selectbox), 0)
            self.app.text_input[0].set_value('Dividi il PDF in cinque macroargomenti')
            self.click('Rispondi')
            self.assertEqual(len(self.app.exception), 0)
            analyze.assert_called_once()
            retrieve.assert_not_called()

    def test_clarification_uses_same_input(self):
        self.prepare_pdf()
        responses = [
            {'clarification':'Quale argomento?', 'request':'Spiegamelo'},
            {'text':'Spiegazione', 'pages':[1], 'passages':[], 'summarized':False, 'request':'Spiega organizzazione'},
        ]
        with patch('rag.answer_request', side_effect=responses) as answer:
            self.app.text_input[0].set_value('Spiegamelo')
            self.click('Rispondi')
            self.assertEqual(len(self.app.text_input), 1)
            self.assertIn('pending_request', self.app.session_state)
            self.app.text_input[0].set_value('Organizzazione')
            self.click('Rispondi')
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(answer.call_args.args[-1]['request'], 'Spiegamelo')
            self.assertNotIn('pending_request', self.app.session_state)

    def test_rejected_request_preserves_previous_study_context(self):
        self.prepare_pdf()
        previous = {'request':'Spiega la valutazione', 'answer':'Risposta pertinente'}
        self.app.session_state['request_context'] = previous
        with patch('rag.understand_request', return_value={
            'route':'reject', 'request':'Ricetta lasagne', 'clarification':'', 'web':False}), \
             patch('web_search.web_explanation') as web:
            self.app.text_input[0].set_value('Ricetta lasagne')
            self.click('Rispondi')
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(self.app.session_state['result']['rejected'])
        self.assertEqual(self.app.session_state['request_context'], previous)
        web.assert_not_called()


if __name__ == '__main__':
    unittest.main()
