"""Un profilo locale, progressi separati per PDF."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).with_name("data") / "progressi.sqlite3"


def connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY, name TEXT NOT NULL, topics TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            document_id TEXT NOT NULL, mode TEXT NOT NULL, question_id TEXT NOT NULL,
            content TEXT NOT NULL, PRIMARY KEY(document_id, mode, question_id)
        );
        CREATE TABLE IF NOT EXISTS attempts (
            run_id TEXT NOT NULL, document_id TEXT NOT NULL, mode TEXT NOT NULL,
            question_id TEXT NOT NULL, topic_id TEXT NOT NULL, selected INTEGER NOT NULL,
            correct INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(run_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, mode TEXT NOT NULL,
            report TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)
    return connection


def save_topics(document_id, name, topics, path=DEFAULT_DB):
    with closing(connect(path)) as connection, connection:
        connection.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",
                           (document_id, name, json.dumps(topics, ensure_ascii=False)))


def load_topics(document_id, path=DEFAULT_DB):
    with closing(connect(path)) as connection:
        row = connection.execute("SELECT topics FROM documents WHERE document_id=?", (document_id,)).fetchone()
    return json.loads(row["topics"]) if row else None


def save_questions(document_id, mode, questions, report, path=DEFAULT_DB):
    with closing(connect(path)) as connection, connection:
        for question in questions:
            connection.execute("INSERT OR IGNORE INTO questions VALUES (?, ?, ?, ?)",
                               (document_id, mode, question["id"], json.dumps(question, ensure_ascii=False)))
        connection.execute("INSERT INTO reviews(document_id,mode,report,created_at) VALUES (?,?,?,?)",
                           (document_id, mode, json.dumps(report, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))


def load_questions(document_id, mode, path=DEFAULT_DB):
    with closing(connect(path)) as connection:
        rows = connection.execute("SELECT content FROM questions WHERE document_id=? AND mode=?",
                                  (document_id, mode)).fetchall()
    return [json.loads(row["content"]) for row in rows]


def save_attempt(document_id, mode, run_id, questions, selections, path=DEFAULT_DB):
    """Calcola il punteggio in Python. La chiave univoca evita doppie consegne."""
    if len(questions) != len(selections) or not questions:
        raise ValueError("Rispondi a tutte le domande.")
    if any(type(choice) is not int or not 0 <= choice < 4 for choice in selections):
        raise ValueError("Seleziona una risposta per ogni domanda.")
    if len({question["id"] for question in questions}) != len(questions):
        raise ValueError("Il quiz contiene domande duplicate.")
    results = [{"question": question, "selected": choice, "correct": choice == question["correct"]}
               for question, choice in zip(questions, selections)]
    with closing(connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("SELECT question_id, selected FROM attempts WHERE run_id=?", (run_id,)).fetchall()
        if previous:
            saved = {row["question_id"]: row["selected"] for row in previous}
            submitted = {item["question"]["id"]: item["selected"] for item in results}
            if saved != submitted:
                raise ValueError("Questo quiz e' gia' stato consegnato con altre risposte.")
        # Nessuna soluzione o punteggio arriva dal browser: si usa il quiz in sessione.
        for item in results:
            connection.execute("""INSERT OR IGNORE INTO attempts
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, document_id, mode, item["question"]["id"], item["question"]["topic_id"],
                 item["selected"], int(item["correct"]), datetime.now(timezone.utc).isoformat()))
    return results


def topic_stats(document_id, mode, topics, path=DEFAULT_DB):
    with closing(connect(path)) as connection:
        rows = connection.execute("""SELECT topic_id, correct FROM attempts
            WHERE document_id=? AND mode=? ORDER BY rowid DESC""", (document_id, mode)).fetchall()
    stats = {topic["id"]: {"topic": topic, "total": 0, "correct": 0, "recent": []} for topic in topics}
    for row in rows:
        if row["topic_id"] not in stats:
            continue
        entry = stats[row["topic_id"]]
        entry["total"] += 1
        entry["correct"] += row["correct"]
        if len(entry["recent"]) < 10:
            entry["recent"].append(row["correct"])
    for entry in stats.values():
        recent = entry.pop("recent")
        entry["recent_accuracy"] = sum(recent) / len(recent) if recent else None
    return list(stats.values())


def recent_topic_answers(document_id, mode, topic_id, path=DEFAULT_DB):
    """Ultimi dieci tentativi dell'argomento, dal meno al piu' recente."""
    with closing(connect(path)) as connection:
        rows = connection.execute("""SELECT a.selected, a.correct, q.content
            FROM attempts a JOIN questions q ON a.document_id=q.document_id
            AND a.mode=q.mode AND a.question_id=q.question_id
            WHERE a.document_id=? AND a.mode=? AND a.topic_id=?
            ORDER BY a.rowid DESC LIMIT 10""", (document_id, mode, topic_id)).fetchall()
    history = []
    for row in reversed(rows):
        question = json.loads(row['content'])
        history.append({'question': question['question'],
                        'selected': question['options'][row['selected']],
                        'solution': question['options'][question['correct']],
                        'correct': bool(row['correct']), 'explanation': question['explanation'],
                        'sources': question.get('sources', [])})
    return history


def study_plan(stats, count=5):
    """Fino a 3 posti deboli, 2 per esplorare gli altri; soglia esplicita 70%."""
    if not stats:
        return []
    weak = sorted([entry for entry in stats if entry["recent_accuracy"] is not None
                   and entry["recent_accuracy"] < 0.7],
                  key=lambda entry: (entry["recent_accuracy"], entry["total"]))
    weak_ids = {entry["topic"]["id"] for entry in weak}
    other = sorted([entry for entry in stats if entry["topic"]["id"] not in weak_ids],
                   key=lambda entry: entry["total"])
    if not weak:
        pool = sorted(stats, key=lambda entry: entry["total"])
        return [pool[index % len(pool)]["topic"]["id"] for index in range(count)]
    result = [weak[index % len(weak)]["topic"]["id"] for index in range(min(3, count))]
    pool = other or weak
    result.extend(pool[index % len(pool)]["topic"]["id"] for index in range(count - len(result)))
    return result


