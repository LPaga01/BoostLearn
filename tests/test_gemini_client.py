import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gemini_client as gemini


class GeminiTests(unittest.TestCase):
    def tearDown(self):
        gemini.get_client.cache_clear()

    def test_client_is_shared_and_receives_explicit_key(self):
        constructor = Mock()
        fake_google = SimpleNamespace(genai=SimpleNamespace(Client=constructor))
        gemini.get_client.cache_clear()
        with patch.dict('sys.modules', {'google': fake_google}):
            first = gemini.get_client('test-key')
            second = gemini.get_client('test-key')
        self.assertIs(first, second)
        self.assertEqual(constructor.call_count, 1)
        self.assertEqual(constructor.call_args.kwargs['api_key'], 'test-key')

    def test_empty_key_rejected_before_sdk_import(self):
        with self.assertRaisesRegex(ValueError, 'GEMINI_API_KEY'):
            gemini.get_client('')

    def test_errors_are_actionable_and_do_not_expose_key(self):
        for code in (403, 404, 429):
            error = ValueError(str(code) + ' fake-private-key')
            message = gemini.safe_ai_error(error, 'fake-private-key')
            self.assertNotIn('fake-private-key', message)
            self.assertIn('Gemini', message)

    def test_agno_shares_client_and_native_schema(self):
        import quiz
        model = Mock()
        agent = Mock()
        agent.return_value.run.return_value = SimpleNamespace(status='completed', content={'topics': []})
        client = object()
        with patch.dict('sys.modules', {'agno.models.google': SimpleNamespace(Gemini=model)}), \
             patch('agno.agent.Agent', agent), patch('quiz.get_client', return_value=client):
            result = quiz.run_agent('Test', 'Rispondi in JSON', {}, 'fake-key', 'test-model', quiz.TOPIC_SCHEMA)
        self.assertEqual(result, {'topics': []})
        self.assertIs(model.call_args.kwargs['client'], client)
        self.assertEqual(model.call_args.kwargs['generation_config']['response_json_schema'], quiz.TOPIC_SCHEMA)


if __name__ == '__main__':
    unittest.main()
