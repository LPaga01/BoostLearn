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
            patch('rag.open_subject_index', return_value=Mock()),
            patch('quiz.discover_topics', return_value=demo_topics()),
            patch('pdf_export.answer_pdf', return_value=b'%PDF-1.4\nmock'),
        ]
        mocks = [item.start() for item in self.patches]
        self.upload = mocks[2]
        self.user = progressi.create_user('Mario')
        self.subject = progressi.create_subject(self.user['id'], 'Intelligenza artificiale')
        from streamlit.testing.v1 import AppTest
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()

    def prepare_pdf(self):
        self.upload.return_value = [SimpleNamespace(name='test.pdf', getvalue=demo_pdf)]
        self.app.session_state['user'] = self.user
        self.app.run()
        self.click('Prepara i documenti')
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
        self.upload.return_value = [SimpleNamespace(name='test.pdf', getvalue=demo_pdf)]
        self.app.session_state['user'] = self.user
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            self.app.run()
        self.assertTrue(any('GEMINI_API_KEY' in item.value for item in self.app.warning))
        self.assertTrue(next(b for b in self.app.button if b.label == 'Prepara i documenti').disabled)

    def test_quiz_score_and_progress_without_export(self):
        self.prepare_pdf()
        chunks = [{'text':' '.join(lines), 'page':i+1} for i,lines in enumerate(PAGES)]
        topic_ids = [topic['id'] for topic in self.app.session_state['topics']]
        questions, report = demo_quiz(chunks, ['topic-1','topic-2','topic-3','topic-1','topic-2'], [])
        for question in questions:
            question['topic_id'] = topic_ids[int(question['topic_id'][-1]) - 1]
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
        review = {'text':'Ripasso collegato', 'pages':[1], 'topic_id':topic_ids[0],
                  'passages':[], 'attempt_count':2, 'correct_count':2}
        with patch('rag.consolidated_review', return_value=review) as generate:
            self.click('Mostra il ripasso')
            self.assertEqual(len(self.app.exception), 0)
            history = generate.call_args.args[1]
            self.assertEqual(len(history), 2)
            self.assertTrue(all(item['correct'] for item in history))

    def test_removing_upload_selection_keeps_saved_documents(self):
        self.prepare_pdf()
        answer = {'text':'Risposta', 'pages':[1], 'passages':[], 'summarized':False, 'request':'Domanda'}
        with patch('rag.answer_request', return_value=answer):
            next(item for item in self.app.text_input if item.label == 'Che cosa vuoi sapere?').set_value('Domanda')
            self.click('Rispondi')
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.get('download_button')), 1)
        self.upload.return_value = None
        self.app.run()
        # Rimuovere la selezione di upload non cancella i documenti gia salvati.
        for key in ('result', 'topics', 'request_context', 'summaries'):
            self.assertIn(key, self.app.session_state)

    def test_overview_routes_to_analysis(self):
        self.prepare_pdf()
        answer = {'text':'Macroargomenti', 'pages':[1], 'passages':[], 'summarized':True}
        with patch('rag.understand_request', return_value={'route':'overview','request':'Cinque macroargomenti','clarification':''}), \
             patch('rag.analyze_document', return_value=answer) as analyze, patch('rag.retrieve') as retrieve:
            self.assertEqual(len(self.app.selectbox), 2)
            next(item for item in self.app.text_input if item.label == 'Che cosa vuoi sapere?').set_value('Dividi il PDF in cinque macroargomenti')
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
            next(item for item in self.app.text_input if item.label == 'Che cosa vuoi sapere?').set_value('Spiegamelo')
            self.click('Rispondi')
            self.assertEqual(len([i for i in self.app.text_input if i.label == 'Che cosa vuoi sapere?']), 1)
            self.assertIn('pending_request', self.app.session_state)
            next(item for item in self.app.text_input if item.label == 'Che cosa vuoi sapere?').set_value('Organizzazione')
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
            next(item for item in self.app.text_input if item.label == 'Che cosa vuoi sapere?').set_value('Ricetta lasagne')
            self.click('Rispondi')
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(self.app.session_state['result']['rejected'])
        self.assertEqual(self.app.session_state['request_context'], previous)
        web.assert_not_called()

    def test_username_registration_rejects_duplicates_and_login_is_case_insensitive(self):
        self.app.run()
        self.app.text_input[0].set_value(' MARIO ')
        self.click('Crea utente')
        self.assertTrue(any('esistente' in e.value for e in self.app.error))
        self.click('Accedi')
        self.assertEqual(self.app.session_state['user']['id'], self.user['id'])
        self.assertEqual(len(self.app.exception), 0)

    def test_multiple_uploads_ignore_duplicates_and_keep_valid_files_on_error(self):
        self.prepare_pdf()
        self.upload.return_value = [
            SimpleNamespace(name='rinominato.pdf', getvalue=demo_pdf),
            SimpleNamespace(name='secondo.pdf', getvalue=lambda: demo_pdf() + b'\n'),
            SimpleNamespace(name='rotto.pdf', getvalue=lambda: b'not a pdf'),
        ]
        self.app.run()
        self.click('Prepara i documenti')
        self.assertEqual(len(self.app.exception), 0)
        documents = progressi.load_library(self.user['id'], self.subject)
        self.assertEqual(len(documents), 2)
        self.assertTrue(any('rotto.pdf' in item.value for item in self.app.error))
        self.assertEqual(len({c['page'] for d in documents for c in d['chunks']}), 4)

    def test_chats_are_independent_and_resume_after_logout(self):
        self.prepare_pdf()
        first_chat = self.app.session_state['loaded_chat']
        answer = {'text': 'Risposta [pagina 1]', 'pages': [1], 'passages': [],
                  'summarized': False, 'request': 'Domanda'}
        with patch('rag.answer_request', return_value=answer):
            next(i for i in self.app.text_input if i.label == 'Che cosa vuoi sapere?').set_value('Domanda')
            self.click('Rispondi')
        self.click('Nuova conversazione')
        self.assertNotEqual(self.app.session_state['loaded_chat'], first_chat)
        self.assertNotIn('result', self.app.session_state)
        next(i for i in self.app.selectbox if i.label == 'Conversazione').set_value(first_chat).run()
        self.assertEqual(self.app.session_state['loaded_chat'], first_chat)
        self.assertIn('test.pdf (pagina 1)', self.app.session_state['result']['text'])
        self.click('Esci')
        self.upload.return_value = None
        self.app.text_input[0].set_value('mario')
        self.click('Accedi')
        next(i for i in self.app.selectbox if i.label == 'Conversazione').set_value(first_chat).run()
        self.assertIn('test.pdf (pagina 1)', self.app.session_state['result']['text'])
        self.assertEqual(len(self.app.get('download_button')), 1)
        self.assertEqual(len(self.app.exception), 0)

    def test_subject_change_clears_memory_and_does_not_show_previous_pdfs(self):
        self.prepare_pdf()
        other_subject = progressi.create_subject(self.user['id'], 'Altro argomento')
        self.app.run()
        next(i for i in self.app.selectbox if i.label == 'Argomento').set_value(other_subject).run()
        for key in ('result', 'chunks', 'index', 'request_context'):
            self.assertNotIn(key, self.app.session_state)
        self.assertFalse(any('test.pdf:' in c.value for c in self.app.caption))
        self.assertEqual(len(self.app.exception), 0)


if __name__ == '__main__':
    unittest.main()
