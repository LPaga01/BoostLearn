"""Utenti, biblioteca, conversazioni e progressi persistenti in SQLite."""

import json
import sqlite3
import uuid
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).with_name("data") / "progressi.sqlite3"


# Apre SQLite e crea le tabelle necessarie se non esistono ancora.
def connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, title_key TEXT NOT NULL, UNIQUE(user_id, title_key)
        );
        CREATE TABLE IF NOT EXISTS library_documents (
            id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(id),
            digest TEXT NOT NULL, name TEXT NOT NULL, pdf BLOB NOT NULL,
            chunks TEXT NOT NULL, topics TEXT NOT NULL, page_count INTEGER NOT NULL,
            empty_pages INTEGER NOT NULL, UNIQUE(subject_id, digest)
        );
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(id),
            title TEXT NOT NULL, state TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS source_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
            original_page INTEGER NOT NULL, UNIQUE(document_id, original_page)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id),
            role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
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


# Normalizza i nomi anche per Unicode: Anna e ANNA identificano lo stesso utente.
def name_key(value):
    value = unicodedata.normalize("NFKC", value).strip()
    if not value or len(value) > 80 or any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("Usa un nome da 1 a 80 caratteri, senza caratteri di controllo.")
    return value, value.casefold()


# Il vincolo UNIQUE impedisce duplicati anche con registrazioni contemporanee.
def create_user(username, path=DEFAULT_DB):
    username, key = name_key(username)
    user_id = uuid.uuid4().hex
    try:
        with closing(connect(path)) as connection, connection:
            connection.execute("INSERT INTO users VALUES (?,?,?)", (user_id, username, key))
    except sqlite3.IntegrityError as error:
        raise ValueError("Username gia' esistente: scegli un altro nome oppure accedi.") from error
    return {"id": user_id, "username": username}


# L'accesso richiesto riconosce il nome; non verifica una password.
def find_user(username, path=DEFAULT_DB):
    _, key = name_key(username)
    with closing(connect(path)) as connection:
        row = connection.execute("SELECT id,username FROM users WHERE username_key=?", (key,)).fetchone()
    return dict(row) if row else None


def create_subject(user_id, title, path=DEFAULT_DB):
    """Crea un contenitore di PDF privato del profilo selezionato."""
    title, key = name_key(title)
    subject_id = uuid.uuid4().hex
    try:
        with closing(connect(path)) as connection, connection:
            connection.execute("INSERT INTO subjects VALUES (?,?,?,?)", (subject_id, user_id, title, key))
    except sqlite3.IntegrityError as error:
        raise ValueError("Argomento gia' presente o utente non valido.") from error
    return subject_id


def list_subjects(user_id, path=DEFAULT_DB):
    """Ogni elenco viene filtrato sul proprietario, non sul nome visualizzato."""
    with closing(connect(path)) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,title FROM subjects WHERE user_id=? ORDER BY rowid", (user_id,))]


# Tutte le operazioni sulla biblioteca controllano il proprietario in SQLite.
def require_subject(connection, user_id, subject_id):
    if not connection.execute("SELECT 1 FROM subjects WHERE id=? AND user_id=?",
                              (subject_id, user_id)).fetchone():
        raise ValueError("Argomento non disponibile per questo utente.")


def load_library(user_id, subject_id, path=DEFAULT_DB):
    """Il PDF originale resta in SQLite; gli indici separati restano in Chroma."""
    with closing(connect(path)) as connection:
        require_subject(connection, user_id, subject_id)
        rows = connection.execute("SELECT * FROM library_documents WHERE subject_id=? ORDER BY rowid",
                                  (subject_id,)).fetchall()
    return [{**dict(row), "chunks": json.loads(row["chunks"]), "topics": json.loads(row["topics"])}
            for row in rows]


def save_document(user_id, subject_id, document, path=DEFAULT_DB):
    """Salva solo documenti completamente preparati, senza duplicare lo stesso PDF."""
    with closing(connect(path)) as connection, connection:
        require_subject(connection, user_id, subject_id)
        # Riferimenti stabili evitano collisioni fra pagina 1 di PDF diversi.
        mapping = {}
        for page in range(1, document["page_count"] + 1):
            cursor = connection.execute("INSERT INTO source_pages(document_id,original_page) VALUES (?,?)",
                                        (document["id"], page))
            mapping[page] = cursor.lastrowid
        chunks = [{**chunk, "page": mapping[chunk["page"]], "original_page": chunk["page"],
                   "document_id": document["id"], "document_name": document["name"],
                   "user_id": user_id, "topic_id": subject_id} for chunk in document["chunks"]]
        topics = [{**topic, "id": document["id"] + ":" + topic["id"],
                   "title": document["name"] + " - " + topic["title"],
                   "pages": [mapping[page] for page in topic["pages"]]} for topic in document["topics"]]
        connection.execute("INSERT INTO library_documents VALUES (?,?,?,?,?,?,?,?,?)", (
            document["id"], subject_id, document["digest"], document["name"], document["pdf"],
            json.dumps(chunks, ensure_ascii=False), json.dumps(topics, ensure_ascii=False),
            document["page_count"], document["empty_pages"]))


def create_chat(user_id, subject_id, title="Nuova conversazione", path=DEFAULT_DB):
    """Le conversazioni appartengono a un argomento e quindi al suo utente."""
    chat_id = uuid.uuid4().hex
    with closing(connect(path)) as connection, connection:
        require_subject(connection, user_id, subject_id)
        connection.execute("INSERT INTO chats(id,subject_id,title) VALUES (?,?,?)", (chat_id, subject_id, title))
    return chat_id


def list_chats(user_id, subject_id, path=DEFAULT_DB):
    """Restituisce solo le chat del contenitore autorizzato."""
    with closing(connect(path)) as connection:
        require_subject(connection, user_id, subject_id)
        return [dict(row) for row in connection.execute(
            "SELECT id,title FROM chats WHERE subject_id=? ORDER BY rowid DESC", (subject_id,))]


def require_chat(connection, user_id, chat_id):
    """Controlla il proprietario anche quando arriva direttamente un ID chat."""
    row = connection.execute("SELECT c.* FROM chats c JOIN subjects s ON s.id=c.subject_id "
                             "WHERE c.id=? AND s.user_id=?", (chat_id, user_id)).fetchone()
    if not row:
        raise ValueError("Conversazione non disponibile per questo utente.")
    return row


def load_chat(user_id, chat_id, path=DEFAULT_DB):
    """Ripristina cronologia completa e l'eventuale domanda di chiarimento."""
    with closing(connect(path)) as connection:
        chat = require_chat(connection, user_id, chat_id)
        messages = [dict(row) for row in connection.execute(
            "SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))]
    return messages, json.loads(chat["state"])


def save_exchange(user_id, chat_id, question, answer, state, path=DEFAULT_DB):
    """Salva domanda e risposta insieme: nessuna cronologia parzialmente scritta."""
    with closing(connect(path)) as connection, connection:
        chat = require_chat(connection, user_id, chat_id)
        now = datetime.now(timezone.utc).isoformat()
        for role, content in (("user", question), ("assistant", answer)):
            connection.execute("INSERT INTO messages(chat_id,role,content,created_at) VALUES (?,?,?,?)",
                               (chat_id, role, content, now))
        title = question[:60] if chat["title"] == "Nuova conversazione" else chat["title"]
        connection.execute("UPDATE chats SET title=?,state=? WHERE id=?",
                           (title, json.dumps(state, ensure_ascii=False), chat_id))


# Salva o aggiorna il nome del documento e i suoi argomenti.
def save_topics(document_id, name, topics, path=DEFAULT_DB):
    with closing(connect(path)) as connection, connection:
        connection.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",
                           (document_id, name, json.dumps(topics, ensure_ascii=False)))


# Recupera gli argomenti salvati per il documento, oppure restituisce None.
def load_topics(document_id, path=DEFAULT_DB):
    with closing(connect(path)) as connection:
        row = connection.execute("SELECT topics FROM documents WHERE document_id=?", (document_id,)).fetchone()
    return json.loads(row["topics"]) if row else None


# Salva le domande accettate e il rapporto dei controlli sul quiz.
def save_questions(document_id, mode, questions, report, path=DEFAULT_DB):
    with closing(connect(path)) as connection, connection:
        for question in questions:
            connection.execute("INSERT OR IGNORE INTO questions VALUES (?, ?, ?, ?)",
                               (document_id, mode, question["id"], json.dumps(question, ensure_ascii=False)))
        connection.execute("INSERT INTO reviews(document_id,mode,report,created_at) VALUES (?,?,?,?)",
                           (document_id, mode, json.dumps(report, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))


# Carica le domande gia salvate per evitare di riproporle.
def load_questions(document_id, mode, path=DEFAULT_DB):
    with closing(connect(path)) as connection:
        rows = connection.execute("SELECT content FROM questions WHERE document_id=? AND mode=?",
                                  (document_id, mode)).fetchall()
    return [json.loads(row["content"]) for row in rows]


# Calcola e salva gli esiti del quiz, impedendo di contare due volte la consegna.
def save_attempt(document_id, mode, run_id, questions, selections, path=DEFAULT_DB):
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


# Calcola risultati totali e accuratezza delle ultime dieci risposte per argomento.
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


# Recupera gli ultimi dieci tentativi di un argomento, con risposte e fonti.
def recent_topic_answers(document_id, mode, topic_id, path=DEFAULT_DB):
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


# Sceglie gli argomenti del prossimo quiz, dando priorita a quelli sotto il 70%.
def study_plan(stats, count=5):
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


