"""Verifiche dei confini fra utenti, documenti, argomenti e conversazioni."""
import tempfile
import unittest
from pathlib import Path

import progressi as db


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'library.sqlite3'
        self.user = db.create_user('Anna', self.path)['id']
        self.other = db.create_user('Luca', self.path)['id']
        self.subject = db.create_subject(self.user, 'Biologia', self.path)

    def tearDown(self):
        self.temp.cleanup()

    def document(self, document_id='pdf-a', digest='hash-a', name='a.pdf'):
        return {'id': document_id, 'digest': digest, 'name': name, 'pdf': b'%PDF-test',
                'chunks': [{'page': 1, 'text': 'Le cellule contengono DNA.'}],
                'topics': [{'id': 'cellule', 'title': 'Cellule', 'pages': [1]}],
                'page_count': 1, 'empty_pages': 0}

    def test_username_unique_after_unicode_and_case_normalization(self):
        for username in (' anna ', 'ANNA', '\uff21\uff4e\uff4e\uff41'):
            with self.assertRaisesRegex(ValueError, 'esistente'):
                db.create_user(username, self.path)
        self.assertEqual(db.find_user(' ANNA ', self.path)['id'], self.user)
        self.assertIsNone(db.find_user('MaiCreato', self.path))
        for invalid in ('  ', 'a\nb', 'a' * 81):
            with self.assertRaises(ValueError):
                db.create_user(invalid, self.path)

    def test_documents_persist_with_distinct_sources_and_owner_metadata(self):
        db.save_document(self.user, self.subject, self.document(), self.path)
        db.save_document(self.user, self.subject, self.document('pdf-b', 'hash-b', 'b.pdf'), self.path)
        documents = db.load_library(self.user, self.subject, self.path)
        first, second = [document['chunks'][0] for document in documents]
        self.assertNotEqual(first['page'], second['page'])
        self.assertEqual(first['original_page'], second['original_page'])
        self.assertEqual(first['user_id'], self.user)
        self.assertEqual(first['topic_id'], self.subject)
        self.assertNotEqual(documents[0]['topics'][0]['id'], documents[1]['topics'][0]['id'])
        self.assertEqual(documents[0]['pdf'], b'%PDF-test')
        self.assertEqual(db.list_subjects(self.other, self.path), [])
        with self.assertRaises(ValueError):
            db.load_library(self.other, self.subject, self.path)
        with self.assertRaises(ValueError):
            db.save_document(self.other, self.subject, self.document('pdf-c'), self.path)
        # Il vincolo sul digest impedisce duplicati anche saltando l'interfaccia.
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            db.save_document(self.user, self.subject, self.document('pdf-c'), self.path)
        self.assertEqual(len(db.load_library(self.user, self.subject, self.path)), 2)

    def test_chats_resume_independently_and_reject_other_users(self):
        chat_a = db.create_chat(self.user, self.subject, path=self.path)
        chat_b = db.create_chat(self.user, self.subject, path=self.path)
        state = {'pending_request': {'clarification': 'Quale cellula?'}}
        db.save_exchange(self.user, chat_a, 'Spiegamelo', 'Quale cellula?', state, self.path)
        messages, saved = db.load_chat(self.user, chat_a, self.path)
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant'])
        self.assertEqual(saved, state)
        self.assertEqual(db.load_chat(self.user, chat_b, self.path), ([], {}))
        for action in (
            lambda: db.load_chat(self.other, chat_a, self.path),
            lambda: db.save_exchange(self.other, chat_a, 'x', 'y', {}, self.path),
            lambda: db.list_chats(self.other, self.subject, self.path),
        ):
            with self.assertRaises(ValueError):
                action()

    def test_persistent_indexes_reopen_without_embedding_and_filter_sources(self):
        db.save_document(self.user, self.subject, self.document(), self.path)
        db.save_document(self.user, self.subject, self.document('pdf-b', 'hash-b', 'b.pdf'), self.path)
        documents = db.load_library(self.user, self.subject, self.path)
        # Il processo separato rilascia gli handle Chroma prima di pulire su Windows.
        import subprocess
        import sys
        code = """
import sys
from pathlib import Path
from unittest.mock import patch
import progressi as db
import rag
path, user, subject, storage = sys.argv[1:]
documents = db.load_library(user, subject, path)
with patch('rag.embed', side_effect=lambda texts, *a, **k: [[1., 0., 0.] for _ in texts]) as embed:
    index = rag.open_subject_index(documents, user, subject, 'test', storage)
    assert embed.call_count == 2
    embed.reset_mock()
    index = rag.open_subject_index(documents, user, subject, 'test', storage)
    embed.assert_not_called()
    passages = rag.retrieve(index, 'cellule', 'test')
    assert {p['document_id'] for p in passages} == {'pdf-a', 'pdf-b'}
    page = documents[1]['chunks'][0]['page']
    filtered = rag.retrieve(index, 'cellule', 'test', pages=[page])
    assert [p['document_id'] for p in filtered] == ['pdf-b']
    wrong_owner = rag.SubjectIndex(index.collections, 'altro-utente', subject)
    assert rag.retrieve(wrong_owner, 'cellule', 'test') == []
    wrong_subject = rag.SubjectIndex(index.collections, user, 'altro-argomento')
    assert rag.retrieve(wrong_subject, 'cellule', 'test') == []
"""
        result = subprocess.run([sys.executable, '-c', code, str(self.path), self.user,
                                 self.subject, str(Path(self.temp.name) / 'indexes')],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == '__main__':
    unittest.main()
