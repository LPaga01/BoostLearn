import unittest
from unittest.mock import patch

import rag


class ReviewTests(unittest.TestCase):
    @patch('rag.generate_answer', return_value={'text': 'Ripasso consolidato', 'pages': [1, 2]})
    @patch('rag.retrieve', return_value=[{'text': 'Fonte nuova', 'page': 3}])
    def test_review_combines_successes_errors_and_sources(self, retrieve, generate):
        history = [
            {'question':'Domanda corretta', 'selected':'Tre', 'solution':'Tre', 'correct':True,
             'explanation':'Spiegazione corretta', 'sources':[{'text':'Fonte uno', 'page':1}]},
            {'question':'Domanda sbagliata', 'selected':'Quattro', 'solution':'Due', 'correct':False,
             'explanation':'Spiegazione errore', 'sources':[{'text':'Fonte due', 'page':2}]},
        ]
        result = rag.consolidated_review({'id':'topic-1','title':'Tema','pages':[1,2,3]}, history, None, 'fake', 'model')
        prompt, sources = generate.call_args.args[:2]
        self.assertIn('Domanda corretta', prompt)
        self.assertIn('Domanda sbagliata', prompt)
        self.assertIn('Quattro', prompt)
        self.assertIn('Due', prompt)
        self.assertEqual({source['page'] for source in sources}, {1,2,3})
        self.assertEqual(result['attempt_count'], 2)
        self.assertEqual(result['correct_count'], 1)
        self.assertIn('Domanda sbagliata', retrieve.call_args.args[1])

    @patch('rag.generate_answer', return_value={'text':'Ripasso','pages':[1]})
    @patch('rag.retrieve', return_value=[{'text':'Fonte','page':1}])
    def test_deduplicates_sources_and_handles_only_correct_answers(self, retrieve, generate):
        item = {'question':'Test', 'selected':'A', 'solution':'A', 'correct':True,
                'explanation':'Test', 'sources':[{'text':'Fonte','page':1}]}
        result = rag.consolidated_review({'id':'t','title':'Tema','pages':[1]}, [item,item], None, 'fake','model')
        self.assertEqual(len(result['passages']), 1)
        self.assertEqual(result['correct_count'], 2)

    @patch('rag.generate_answer', return_value={'text':'Introduzione','pages':[1]})
    @patch('rag.retrieve', return_value=[{'text':'Fonte','page':1}])
    def test_unseen_topic_has_no_invented_attempts(self, retrieve, generate):
        result = rag.consolidated_review({'id':'t','title':'Tema','pages':[1]}, [], None, 'fake','model')
        self.assertEqual(result['attempt_count'], 0)
        self.assertIn('"storico": []', generate.call_args.args[0])
