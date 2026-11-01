import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import progressi as db
import quiz
from fixtures import PAGES, demo_topics, demo_quiz


def chunks():
    return [{"text": " ".join(lines), "page": index + 1} for index, lines in enumerate(PAGES)]


def question():
    return {"slot": 0, "topic_id": "topic-1", "question": "Quante persone puo' avere un gruppo?",
            "options": ["Tre", "Quattro", "Cinque", "Sei"], "correct": 0,
            "explanation": "I gruppi possono avere al massimo tre persone.", "pages": [1],
            "quote": "in gruppi di massimo tre persone."}


class QuizTests(unittest.TestCase):
    def test_agent_error_is_not_parsed_as_json(self):
        with self.assertRaisesRegex(ValueError, "429"):
            quiz.parse_agent_result(SimpleNamespace(status="error", content="HTTP 429"))
        self.assertEqual(quiz.parse_agent_result(SimpleNamespace(status="completed", content='{"topics": []}')), {"topics": []})

    def test_error_message_redacts_key(self):
        key = "fake-private-key"
        self.assertNotIn(key, quiz.safe_ai_error(ValueError("Error " + key), key))
        self.assertIn("10013", quiz.safe_ai_error(ValueError("[WinError 10013]"), key))

    def test_valid_sources(self):
        valid = quiz.validate_question(question(), "topic-1", chunks(), set())
        self.assertEqual(valid["id"], quiz.question_id(question()["question"]))

    def test_reject_false_quote_pages_and_ambiguity(self):
        invalid = [{"quote": "Questa frase non esiste nel PDF."}, {"pages": [90]},
                   {"pages": [2]}, {"correct": True}, {"correct": 4},
                   {"options": ["Tre", " tre ", "Cinque", "Sei"]},
                   {"options": ["Tre"]}, {"topic_id": "altro"}, {"explanation": ""}]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                quiz.validate_question({**question(), **change}, "topic-1", chunks(), set())

    def test_duplicate_normalization(self):
        q = question()
        with self.assertRaises(ValueError):
            quiz.validate_question(q, "topic-1", chunks(), {quiz.question_id(q["question"].upper())})

    def test_shuffle_preserves_solution(self):
        q = question()
        shuffled = quiz.shuffle_options(q, random.Random(42))
        self.assertEqual(shuffled["options"][shuffled["correct"]], "Tre")
        self.assertEqual(q["options"], ["Tre", "Quattro", "Cinque", "Sei"])

    @patch("quiz.run_agent")
    def test_generator_and_reviewer(self, agent):
        agent.side_effect = [{"questions": [question()]},
                             {"reviews": [{"slot": 0, "approved": True, "correct": 0, "reason": "Supportata dalle fonti."}]}]
        questions, report = quiz.make_quiz(chunks(), demo_topics(), ["topic-1"], [], "fake", "model")
        self.assertEqual(len(questions), 1)
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(agent.call_count, 2)
        self.assertNotEqual(agent.call_args_list[0].args[0], agent.call_args_list[1].args[0])

    @patch("quiz.run_agent")
    def test_reviewer_can_disagree(self, agent):
        agent.side_effect = [{"questions": [question()]},
                             {"reviews": [{"slot": 0, "approved": True, "correct": 1, "reason": "La soluzione non coincide."}]}]
        accepted, report = quiz.make_quiz(chunks(), demo_topics(), ["topic-1"], [], "fake", "model")
        self.assertEqual(accepted, [])
        self.assertEqual(report["rejected"][0]["stage"], "revisore")

    @patch("quiz.run_agent")
    def test_missing_review_prevents_publication(self, agent):
        agent.side_effect = [{"questions": [question()]}, {"reviews": []}]
        with self.assertRaises(ValueError):
            quiz.make_quiz(chunks(), demo_topics(), ["topic-1"], [], "fake", "model")

    @patch("quiz.run_agent")
    def test_bad_evidence_rejected_before_review(self, agent):
        agent.return_value = {"questions": [{**question(), "quote": "Questa citazione e' inventata."}]}
        accepted, report = quiz.make_quiz(chunks(), demo_topics(), ["topic-1"], [], "fake", "model")
        self.assertEqual(accepted, [])
        self.assertEqual(agent.call_count, 1)
        self.assertEqual(report["rejected"][0]["stage"], "codice")

    @patch("quiz.run_agent")
    def test_topics_validated_and_stable_ids(self, agent):
        agent.return_value = {"topics": [{"title": "Organizzazione", "pages": [1]}]}
        topics = quiz.discover_topics(chunks(), "fake", "model")
        self.assertEqual(topics[0]["id"], "topic-1")
        agent.return_value = {"topics": [{"title": "Inventato", "pages": [99]}]}
        with self.assertRaises(ValueError):
            quiz.discover_topics(chunks(), "fake", "model")

    def test_demo_has_real_quotes_and_no_repeats(self):
        plan = ["topic-1", "topic-2", "topic-3", "topic-1", "topic-2"]
        first, report = demo_quiz(chunks(), plan, [])
        second, _ = demo_quiz(chunks(), plan, first)
        self.assertEqual(len(first), 5)
        self.assertTrue(report["demo"])
        self.assertFalse({item["id"] for item in first} & {item["id"] for item in second})

    def test_sample_spans_document(self):
        source = [{"text": str(index), "page": index} for index in range(100)]
        sample = quiz.sample_passages(source, 4)
        self.assertEqual(len(sample), 4)
        self.assertEqual((sample[0]["page"], sample[-1]["page"]), (0, 99))


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "progress.sqlite3"
        self.topics = demo_topics()
        self.questions, self.report = demo_quiz(chunks(), ["topic-1", "topic-2", "topic-3"], [])

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_and_mode_isolation(self):
        db.save_topics("demo:doc", "file.pdf", self.topics, self.path)
        self.assertEqual(db.load_topics("demo:doc", self.path), self.topics)
        self.assertIsNone(db.load_topics("ai:doc", self.path))
        db.save_questions("doc", "demo", self.questions, self.report, self.path)
        self.assertEqual(len(db.load_questions("doc", "demo", self.path)), 3)
        self.assertEqual(db.load_questions("doc", "ai", self.path), [])
        self.assertEqual(db.load_questions("other", "demo", self.path), [])

    def test_score_atomic_validation_and_idempotence(self):
        correct = [item["correct"] for item in self.questions]
        with self.assertRaises(ValueError):
            db.save_attempt("doc", "demo", "run", self.questions, [None] * 3, self.path)
        first = db.save_attempt("doc", "demo", "run", self.questions, correct, self.path)
        self.assertTrue(all(item["correct"] for item in first))
        db.save_attempt("doc", "demo", "run", self.questions, correct, self.path)
        with self.assertRaises(ValueError):
            db.save_attempt("doc", "demo", "run", self.questions,
                            [(choice + 1) % 4 for choice in correct], self.path)
        stats = db.topic_stats("doc", "demo", self.topics, self.path)
        self.assertEqual(sum(item["total"] for item in stats), 3)
        self.assertEqual(sum(item["total"] for item in db.topic_stats("doc", "ai", self.topics, self.path)), 0)

    def test_plan_prioritizes_weak_and_explores(self):
        correct = [item["correct"] for item in self.questions]
        correct[0] = (correct[0] + 1) % 4
        db.save_attempt("doc", "ai", "run", self.questions, correct, self.path)
        stats = db.topic_stats("doc", "ai", self.topics, self.path)
        plan = db.study_plan(stats)
        self.assertEqual(plan[:3], ["topic-1"] * 3)
        self.assertEqual(set(plan[3:]), {"topic-2", "topic-3"})

    def test_initial_plan_covers_all_topics(self):
        stats = db.topic_stats("doc", "ai", self.topics, self.path)
        self.assertEqual(set(db.study_plan(stats)), {topic["id"] for topic in self.topics})
        self.assertEqual(db.study_plan([]), [])

    def test_recent_window_allows_recovery(self):
        q = self.questions[:1]
        db.save_attempt("doc", "ai", "wrong", q, [(q[0]["correct"] + 1) % 4], self.path)
        for index in range(10):
            db.save_attempt("doc", "ai", str(index), q, [q[0]["correct"]], self.path)
        stats = db.topic_stats("doc", "ai", self.topics, self.path)
        self.assertEqual(stats[0]["recent_accuracy"], 1)
        self.assertEqual(stats[0]["total"], 11)

    def test_review_history_has_choices_solutions_and_sources(self):
        db.save_questions('doc', 'ai', self.questions, self.report, self.path)
        choices = [item['correct'] for item in self.questions]
        choices[0] = (choices[0] + 1) % 4
        db.save_attempt('doc', 'ai', 'run', self.questions, choices, self.path)
        history = db.recent_topic_answers('doc', 'ai', 'topic-1', self.path)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]['correct'])
        self.assertEqual(history[0]['selected'], self.questions[0]['options'][choices[0]])
        self.assertEqual(history[0]['solution'], self.questions[0]['options'][self.questions[0]['correct']])
        self.assertTrue(history[0]['sources'])
        self.assertEqual(db.recent_topic_answers('other', 'ai', 'topic-1', self.path), [])
        self.assertEqual(db.recent_topic_answers('doc', 'demo', 'topic-1', self.path), [])

    def test_review_history_is_last_ten_in_chronological_order(self):
        q = self.questions[:1]
        db.save_questions('doc', 'ai', q, self.report, self.path)
        for index in range(12):
            choice = q[0]['correct'] if index % 2 else (q[0]['correct'] + 1) % 4
            db.save_attempt('doc', 'ai', str(index), q, [choice], self.path)
        history = db.recent_topic_answers('doc', 'ai', 'topic-1', self.path)
        self.assertEqual(len(history), 10)
        self.assertEqual([item['correct'] for item in history], [False, True] * 5)



if __name__ == "__main__":
    unittest.main()
