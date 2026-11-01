import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import rag


class RoutingTests(unittest.TestCase):
    @patch('rag.get_client')
    def test_request_is_interpreted_with_clarification_context(self, client):
        result = {'route': 'search', 'request': 'Spiega il gradiente', 'clarification': ''}
        client.return_value.models.generate_content.return_value = SimpleNamespace(text=json.dumps(result))
        pending = {'request': 'Spiegamelo', 'clarification': 'Quale concetto?'}
        parsed = rag.understand_request('Il gradiente', [], 'fake', 'model', pending=pending)
        self.assertEqual(parsed, result)
        sent = json.loads(client.return_value.models.generate_content.call_args.kwargs['contents'])
        self.assertEqual(sent['pending'], pending)

    @patch('rag.get_client')
    def test_invalid_routes_and_empty_clarification_rejected(self, client):
        for result in ({'route':'other','request':'Test','clarification':''},
                       {'route':'clarify','request':'Test','clarification':''},
                       {'route':'search','request':'','clarification':''}):
            client.return_value.models.generate_content.return_value = SimpleNamespace(text=json.dumps(result))
            with self.subTest(result=result), self.assertRaises(ValueError):
                rag.understand_request('Test', [], 'fake', 'model')

    @patch('rag.analyze_document')
    @patch('rag.retrieve')
    @patch('rag.understand_request')
    def test_clarification_does_not_run_retrieval_or_analysis(self, route, retrieve, analyze):
        route.return_value = {'route':'clarify','request':'Spiegamelo','clarification':'Quale argomento?'}
        result = rag.answer_request('Spiegamelo', [], None, [], 'fake', 'model', {})
        self.assertEqual(result['clarification'], 'Quale argomento?')
        retrieve.assert_not_called()
        analyze.assert_not_called()

    @patch('rag.generate_answer', return_value={'text':'Risposta','pages':[1]})
    @patch('rag.retrieve', return_value=[{'text':'Fonte','page':1}])
    @patch('rag.understand_request')
    def test_specific_question_uses_rewritten_request(self, route, retrieve, generate):
        route.return_value = {'route':'search','request':'Spiega il gradiente','clarification':''}
        result = rag.answer_request('Spiegamelo', [], None, [], 'fake', 'model', {})
        self.assertIn('Spiega il gradiente', retrieve.call_args.args[1])
        self.assertIn('Spiegamelo', retrieve.call_args.args[1])
        self.assertFalse(result['summarized'])

    @patch('rag.analyze_document', return_value={'text':'Tre temi spiegati','pages':[1], 'passages':[], 'summarized':False})
    @patch('rag.retrieve')
    @patch('rag.understand_request', return_value={'route':'search','request':'Spiega il documento','clarification':''})
    def test_short_document_uses_complete_text_even_if_misrouted(self, route, retrieve, analyze):
        chunks = [{'text':'Contenuti della dispensa', 'page':1}]
        question = 'Spiegami il PDF dividendolo in 3 macroargomenti'
        result = rag.answer_request(question, [], None, chunks, 'fake', 'model', {})
        retrieve.assert_not_called()
        self.assertEqual(analyze.call_args.args[1], chunks)
        self.assertIn(question, analyze.call_args.args[0])
        self.assertEqual(result['text'], 'Tre temi spiegati')

    @patch('rag.analyze_document', return_value={'text':'Risposta trovata altrove','pages':[30], 'passages':[], 'summarized':True})
    @patch('rag.generate_answer', return_value={'text':rag.NO_ANSWER,'pages':[]})
    @patch('rag.retrieve', return_value=[{'text':'Passaggio non pertinente','page':1}])
    @patch('rag.understand_request', return_value={'route':'search','request':'Spiega il gradiente','clarification':''})
    def test_failed_search_tries_whole_document_before_abstaining(self, route, retrieve, generate, analyze):
        chunks = [{'text':'x'*1000,'page':i+1} for i in range(65)]
        cache = {}
        result = rag.answer_request('Spiega il gradiente', [], None, chunks, 'fake', 'model', cache)
        analyze.assert_called_once()
        self.assertIs(analyze.call_args.args[-1], cache)
        self.assertEqual(result['text'], 'Risposta trovata altrove')

    @patch('rag.analyze_document', return_value={'text':rag.NO_ANSWER,'pages':[], 'passages':[], 'summarized':False})
    @patch('rag.understand_request', return_value={'route':'search','request':'Dato assente','clarification':''})
    def test_missing_facts_can_still_be_rejected(self, route, analyze):
        result = rag.answer_request('Dato assente', [], None, [{'text':'Altri fatti','page':1}], 'fake', 'model', {})
        self.assertEqual(result['text'], rag.NO_ANSWER)


if __name__ == '__main__':
    unittest.main()
