import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

import rag
from web_search import web_explanation, search_sources, _search_cached

SOURCES = [{'id':'W1', 'title':'Fonte ufficiale', 'url':'https://example.org/source', 'content':'Un fatto verificabile'}]


class WebTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict('os.environ', {'TAVILY_API_KEY':'fake-test-key'})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    @patch('web_search.search_sources', return_value=SOURCES)
    @patch('web_search.get_client')
    def test_external_search_uses_main_model_without_google_tool(self, client, search):
        client.return_value.models.generate_content.side_effect = [NS(text=json.dumps({'query':'tema tecnico confronto'})), NS(text=json.dumps(
            {'sections':[{'text':'Confronto fondato', 'source_ids':['W1']}]}))]
        with patch.dict('os.environ', {'GEMINI_WEB_MODEL':'unavailable-legacy-model'}):
            result = web_explanation('Confronta', 'Dal PDF', 'fake', 'main-model')
        args = client.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(args['model'], 'main-model')
        search.assert_called_once_with('tema tecnico confronto')
        self.assertNotIn('tools', args['config'])
        self.assertIn('https://example.org/source', result['text'])
        self.assertEqual(result['sources'][0]['id'], 'W1')

    @patch('web_search.search_sources', return_value=SOURCES)
    @patch('web_search.get_client')
    def test_valid_inline_citations_are_preserved_without_duplication(self, client, search):
        for text in ('Una spiegazione [W1].', 'Una spiegazione [ W1 ].'):
            client.return_value.models.generate_content.side_effect = [
                NS(text=json.dumps({'query':'tema tecnico'})),
                NS(text=json.dumps({'sections':[{'text':text, 'source_ids':['W1']}]}))]
            result = web_explanation('Approfondisci', '', 'fake', 'model')
            body = result['text'].split('Fonti web:')[0].strip()
            self.assertEqual(body, text)

    @patch('web_search.search_sources', return_value=SOURCES)
    @patch('web_search.get_client')
    def test_invented_inline_citation_is_rejected(self, client, search):
        client.return_value.models.generate_content.side_effect = [
            NS(text=json.dumps({'query':'tema tecnico'})),
            NS(text=json.dumps({'sections':[{'text':'Testo [W99]', 'source_ids':['W1']}]}))]
        with self.assertRaisesRegex(ValueError, 'fonti non dichiarate'):
            web_explanation('Approfondisci', '', 'fake', 'model')

    @patch('web_search.search_sources', return_value=SOURCES)
    @patch('web_search.get_client')
    def test_missing_or_invented_citations_rejected(self, client, search):
        for data in ({'sections':[{'text':'Testo', 'source_ids':['W2']}]},
                     {'sections':[{'text':'Testo', 'source_ids':[]}]},
                     {'sections':[]}):
            client.return_value.models.generate_content.side_effect = [NS(text=json.dumps({'query':'tema tecnico'})), NS(text=json.dumps(data))]
            with self.assertRaises(ValueError):
                web_explanation('Confronta', '', 'fake', 'model')

    @patch.dict('os.environ', {'TAVILY_API_KEY':''})
    @patch('web_search.get_client')
    def test_missing_key_does_not_call_gemini(self, client):
        with self.assertRaisesRegex(ValueError, 'TAVILY_API_KEY'):
            web_explanation('Domanda', '', 'fake', 'model')
        client.assert_not_called()

    @patch.dict('os.environ', {'TAVILY_API_KEY':'fake-search-key'})
    @patch('web_search.urlopen')
    def test_basic_search_filters_sources_and_reuses_cache(self, open_url):
        _search_cached.cache_clear()
        data = {'results':[{'url':'javascript:alert(1)', 'content':'bad'},
                           {'url':SOURCES[0]['url'], 'title':'Fonte', 'content':'Fatto'},
                           {'url':SOURCES[0]['url'], 'content':'Duplicato'}]}
        open_url.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode()
        with patch('web_search.time.time', return_value=3601):
            first = search_sources('domanda di prova')
            second = search_sources('domanda di prova')
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(open_url.call_count, 1)
        payload = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(payload['search_depth'], 'basic')
        self.assertFalse(payload['auto_parameters'])
        _search_cached.cache_clear()

    @patch.dict('os.environ', {'TAVILY_API_KEY':'private-search-key'})
    @patch('web_search.urlopen')
    def test_quota_error_does_not_leak_key(self, open_url):
        _search_cached.cache_clear()
        open_url.side_effect = HTTPError('https://api.tavily.com/search', 432, 'private-search-key', {}, None)
        with self.assertRaisesRegex(ValueError, 'Limite Tavily') as raised:
            search_sources('altra domanda')
        self.assertNotIn('private-search-key', str(raised.exception))
        _search_cached.cache_clear()

    @patch('web_search.web_explanation')
    @patch('rag.analyze_document', return_value={'text':'Testo PDF', 'pages':[1], 'passages':[], 'summarized':False})
    @patch('rag.understand_request', return_value={'route':'search', 'request':'Confronta', 'web':True})
    def test_web_completion_preserves_document_pages(self, route, analyze, web):
        web.return_value = {'text':'Confronto [W1]', 'sources':[{'id':'W1','url':'https://example.org','title':'Fonte'}], 'search_suggestions':None}
        result = rag.answer_request('Confronta', [], None, [{'text':'PDF','page':1}], 'fake', 'model', {}, web_enabled=True)
        self.assertEqual(result['pages'], [1])
        self.assertIn('## Dal PDF\nTesto PDF', result['text'])
        self.assertIn('## Approfondimento dal web', result['text'])

    @patch('web_search.web_explanation', side_effect=ValueError('Quota esaurita'))
    @patch('rag.analyze_document', return_value={'text':'Testo PDF', 'pages':[1], 'passages':[], 'summarized':False})
    @patch('rag.understand_request', return_value={'route':'search', 'request':'Confronta', 'web':True})
    def test_web_failure_preserves_pdf_and_pdf_only_disables_search(self, route, analyze, web):
        args = ('Confronta', [], None, [{'text':'PDF','page':1}], 'fake', 'model', {})
        result = rag.answer_request(*args, web_enabled=True)
        self.assertEqual(result['text'], 'Testo PDF')
        self.assertEqual(result['web_warning'], 'Quota esaurita')
        route.return_value['web'] = False
        web.reset_mock()
        rag.answer_request(*args, web_enabled=True)
        web.assert_not_called()

    @patch('web_search.web_explanation')
    @patch('rag.analyze_document', return_value={'text':rag.NO_ANSWER, 'pages':[], 'passages':[], 'summarized':False})
    @patch('rag.understand_request', return_value={'route':'search', 'request':'Tema esterno', 'web':True})
    def test_external_question_can_be_answered_without_pdf_citations(self, route, analyze, web):
        web.return_value = {'text':'Risposta web', 'sources':[], 'search_suggestions':None}
        result = rag.answer_request('Tema esterno', [], None, [{'text':'PDF','page':1}], 'fake', 'model', {}, web_enabled=True)
        self.assertEqual(result['pages'], [])
        self.assertIn('Risposta web', result['text'])
