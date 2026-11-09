"""Interfaccia: profili, argomenti con piu PDF e conversazioni persistenti."""

import hashlib
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from gemini_client import DEFAULT_MODEL
from pdf_export import answer_pdf
import progressi as db
from quiz import discover_topics, make_quiz
from rag import answer_request, open_subject_index, consolidated_review, extract_chunks

load_dotenv(Path(__file__).with_name(".env"))
API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
REVIEW_MODEL = os.getenv("GEMINI_REVIEW_MODEL", MODEL) or MODEL

st.set_page_config(page_title="BoostLearn", page_icon="📖", layout="centered")
st.title("BoostLearn")
st.write("Studia il materiale, mettiti alla prova e scopri cosa ripassare.")


# Il cambio di contesto libera soltanto la memoria, mai gli indici persistenti.
def clear_document():
    for key in ("digest", "chunks", "page_count", "empty_pages", "result", "topics", "index",
                "current_quiz", "quiz_results", "run_id", "review_result", "summaries",
                "request_context", "pending_request", "loaded_chat", "page_labels"):
        st.session_state.pop(key, None)


# Mostra un errore leggibile senza esporre dettagli tecnici inattesi.
def show_error(error):
    st.error(str(error) if isinstance(error, ValueError) else
             "Operazione non riuscita. Controlla rete, configurazione e permessi della cartella data.")


# I numeri interni collegano fonti e quiz; all'utente mostriamo file e pagina originale.
def source_labels(pages):
    return "; ".join(st.session_state.get("page_labels", {}).get(page, str(page)) for page in pages)


def source_text(text):
    """Rende leggibili le citazioni senza cambiare gli ID salvati nei quiz."""
    return re.sub(r"\[(?:pagina|pagine)\s+(\d+(?:\s*[,;]\s*\d+)*)\]",
        lambda match: "[" + source_labels([int(n) for n in re.findall(r"\d+", match[1])]) + "]",
        text, flags=re.IGNORECASE)


def recent_context(messages, limit=16000):
    """Limita il costo della richiesta, mantenendo tutta la cronologia nel database."""
    recent, remaining = [], limit
    for message in reversed(messages):
        if remaining <= 0:
            break
        content = message["content"][-remaining:]
        recent.append({"role": message["role"], "content": content})
        remaining -= len(content)
    return list(reversed(recent))


def show_sources(passages):
    """Mostra le fonti con riferimenti non ambigui tra PDF diversi."""
    for passage in passages:
        st.markdown("**" + source_labels(passage.get("pages", [passage.get("page")])) + "**")
        st.text(passage["text"])


# Registrazione e accesso sono distinti: un nome gia registrato non crea un nuovo profilo.
if "user" not in st.session_state:
    st.caption("Accedi con il solo username. Chi conosce il nome puo accedere al relativo profilo.")
    with st.form("access"):
        username = st.text_input("Username", max_chars=80)
        login = st.form_submit_button("Accedi")
        register = st.form_submit_button("Crea utente")
    if login or register:
        try:
            user = db.create_user(username) if register else db.find_user(username)
            if not user:
                raise ValueError("Username non trovato: crea prima il tuo utente.")
            st.session_state.user = user
            st.rerun()
        except Exception as error:
            show_error(error)
    st.stop()

user = st.session_state.user
user_id = user["id"]
with st.sidebar:
    st.write("Utente: " + user["username"])
    if st.button("Esci"):
        st.session_state.clear()
        st.rerun()
    with st.form("new_subject"):
        title = st.text_input("Nuovo argomento", max_chars=80)
        if st.form_submit_button("Crea argomento"):
            try:
                selected = db.create_subject(user_id, title)
                st.session_state["subject_choice"] = selected
                st.rerun()
            except Exception as error:
                show_error(error)
    subjects = db.list_subjects(user_id)
    if not subjects:
        st.info("Crea il primo argomento per caricare i PDF.")
        st.stop()
    subject_titles = {item["id"]: item["title"] for item in subjects}
    subject_id = st.selectbox("Argomento", list(subject_titles),
                              format_func=subject_titles.get, key="subject_choice")

name = subject_titles[subject_id]
mode = "ai"
# L'ID del contenitore separa anche progressi e quiz dei diversi utenti.
digest = subject_id
documents = db.load_library(user_id, subject_id)
version = (subject_id, tuple(document["id"] for document in documents))
if st.session_state.get("library_version") != version:
    clear_document()
    st.session_state.library_version = version

st.subheader(name)
if not API_KEY:
    st.warning("Inserisci GEMINI_API_KEY nel file .env e riavvia l'app.")
uploaded = st.file_uploader("Aggiungi PDF all'argomento", type=["pdf"], accept_multiple_files=True,
                            key="upload_" + subject_id)
st.caption("Ogni PDF: massimo 10 MB e 100 pagine, testo selezionabile. Elaborazione con Google Gemini.")
if uploaded and st.button("Prepara i documenti", type="primary", disabled=not API_KEY):
    # I PDF gia presenti vengono riconosciuti dai byte, anche se rinominati.
    known = {document["digest"] for document in documents}
    added = 0
    for upload in uploaded:
        data = upload.getvalue()
        file_digest = hashlib.sha256(data).hexdigest()
        if file_digest in known:
            st.info(upload.name + ": gia presente nell'argomento.")
            continue
        try:
            with st.spinner("Preparo " + upload.name + "..."):
                chunks, pages, empty = extract_chunks(data)
                topics = discover_topics(chunks, API_KEY, MODEL)
                db.save_document(user_id, subject_id, {
                    "id": uuid.uuid4().hex, "digest": file_digest, "name": upload.name,
                    "pdf": data, "chunks": chunks, "topics": topics,
                    "page_count": pages, "empty_pages": empty})
                known.add(file_digest)
                added += 1
        except Exception as error:
            st.error(upload.name + ": caricamento non completato.")
            show_error(error)
    if added:
        # Il riepilogo resta visibile anche se uno degli altri file non era valido.
        st.success(f"{added} PDF salvati. I file non validi possono essere caricati di nuovo.")
        documents = db.load_library(user_id, subject_id)
        clear_document()
        st.session_state.library_version = (subject_id, tuple(d["id"] for d in documents))

if not documents:
    st.write("Carica una o piu dispense per iniziare.")
    st.stop()

chunks = [chunk for document in documents for chunk in document["chunks"]]
topics = [topic for document in documents for topic in document["topics"]]
# Due file con lo stesso nome restano distinguibili anche nelle citazioni.
name_counts = Counter(document["name"] for document in documents)
document_labels = {d["id"]: d["name"] + (" [" + d["id"][:8] + "]" if name_counts[d["name"]] > 1 else "")
                   for d in documents}
st.session_state.page_labels = {chunk["page"]: f"{document_labels[chunk['document_id']]} (pagina {chunk['original_page']})"
                                for chunk in chunks}
for document in documents:
    st.caption(f"{document_labels[document['id']]}: {document['page_count']} pagine.")
    if document["empty_pages"]:
        st.warning(f"{document['name']}: {document['empty_pages']} pagine senza testo estraibile.")
try:
    if "index" not in st.session_state:
        with st.spinner("Apro gli indici dei PDF..."):
            st.session_state.index = open_subject_index(documents, user_id, subject_id, API_KEY)
    st.session_state.update(chunks=chunks, topics=topics, digest=digest)
    stats = db.topic_stats(digest, mode, topics)
except Exception as error:
    show_error(error)
    st.info("I PDF sono salvati. Puoi riprovare a preparare gli indici senza ricaricarli.")
    if st.button("Riprova ad aprire gli indici"):
        st.rerun()
    st.stop()

with st.sidebar:
    if st.button("Nuova conversazione"):
        chat_id = db.create_chat(user_id, subject_id)
        st.session_state["chat_choice_" + subject_id] = chat_id
        st.rerun()
    chats = db.list_chats(user_id, subject_id)
    if not chats:
        db.create_chat(user_id, subject_id)
        chats = db.list_chats(user_id, subject_id)
    chat_titles = {chat["id"]: chat["title"] for chat in chats}
    chat_id = st.selectbox("Conversazione", list(chat_titles), format_func=chat_titles.get,
                           key="chat_choice_" + subject_id)

if st.session_state.get("loaded_chat") != chat_id:
    for key in ("result", "request_context", "pending_request"):
        st.session_state.pop(key, None)
    _, saved_state = db.load_chat(user_id, chat_id)
    st.session_state.update(saved_state)
    st.session_state.loaded_chat = chat_id
messages, _ = db.load_chat(user_id, chat_id)

material_tab, quiz_tab, review_tab = st.tabs(["Il mio materiale", "Mettimi alla prova", "Cosa ripassare"])

with material_tab:
    st.caption("Puoi chiedere anche confronti e approfondimenti: quando servono, uso fonti web e le distinguo dal PDF. Quiz e ripasso restano basati sulla dispensa.")
    if topics:
        st.caption("Argomenti individuati: " + " · ".join(topic["title"] for topic in topics))
    # La cronologia completa resta consultabile; al modello inviamo il contesto recente.
    visible_messages = messages[:-2] if "result" in st.session_state else messages
    for message in visible_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    pending = st.session_state.get("pending_request")
    if pending:
        st.info(pending["clarification"] + " Rispondi nel campo qui sotto, oppure scrivi una nuova richiesta.")
    with st.form("question_form"):
        question = st.text_input("Che cosa vuoi sapere?", placeholder="Spiegami un concetto, riassumi il materiale o crea uno schema...", max_chars=1000, key="question_" + chat_id)
        submitted = st.form_submit_button("Rispondi", type="primary")
    if submitted:
        st.session_state.pop("result", None)
        if not question.strip():
            st.warning("Scrivi una domanda.")
        else:
            started = time.perf_counter()
            try:
                with st.spinner("Cerco nel documento…"):
                    cache = st.session_state.setdefault("summaries", {})
                    answer = answer_request(question, topics, st.session_state.index, chunks,
                        API_KEY, MODEL, cache, {
                            "previous": st.session_state.get("request_context"),
                            "history": recent_context(messages)}, pending, web_enabled=True)
                    if "clarification" not in answer:
                        passages = answer.pop("passages")
                        summarized = answer.pop("summarized")
                    if "clarification" in answer:
                        st.session_state.pending_request = answer
                        db.save_exchange(user_id, chat_id, question, answer["clarification"], {
                            "pending_request": answer,
                            "request_context": st.session_state.get("request_context")})
                        st.rerun()
                    st.session_state.pop("pending_request", None)
                    if not answer.get('rejected'):
                        st.session_state.request_context = {"request": answer.get("request", question), "answer": answer["text"][:2000]}
                    answer["text"] = source_text(answer["text"])
                    answer["source_labels"] = source_labels(answer["pages"])
                    result = {**answer, "passages": passages, "question": question, "summarized": summarized,
                              "seconds": time.perf_counter() - started}
                    # Salviamo anche fonti e risposta esportabile per la successiva riapertura.
                    db.save_exchange(user_id, chat_id, question, answer["text"], {
                        "request_context": st.session_state.get("request_context"), "result": result})
                    st.session_state.result = result
            except Exception as error:
                show_error(error)
    if "result" in st.session_state:
        result = st.session_state.result
        st.subheader("Risposta")
        st.caption(result["question"])
        st.write(source_text(result["text"]))
        if result.get('web_warning'):
            st.warning('Approfondimento web non disponibile. ' + result['web_warning'])
        for source in result.get('web_sources', []):
            st.link_button(f"{source['id']}: {source['title']}", source['url'])
        if result.get('search_suggestions'):
            import streamlit.components.v1 as components
            components.html(result['search_suggestions'], height=180, scrolling=True)
        if result.get("summarized"):
            st.info("Analisi basata sulle sintesi delle varie parti del PDF: alcuni dettagli possono andare persi.")
        if result["pages"]:
            st.caption("Fonti: " + source_labels(result["pages"]))
        try:
            if "pdf" not in result:
                result["pdf"] = answer_pdf(result, name)
            st.download_button("Scarica la risposta in PDF", result["pdf"],
                               "boostlearn-risposta.pdf", "application/pdf", on_click="ignore")
        except ImportError:
            st.caption("Per attivare il download PDF, riavvia avvia.cmd e attendi l'installazione delle librerie.")
        except Exception:
            st.warning("Non riesco a preparare il PDF. La risposta resta disponibile qui sopra.")
        st.caption(f"Tempo: {result['seconds']:.1f} secondi")

with quiz_tab:
    st.subheader("Un piccolo test per capire come stai andando")
    st.write("Cinque domande, quando le fonti lo permettono. Tre posti vanno agli argomenti deboli e due agli altri; all'inizio il test distribuisce le domande tra gli argomenti.")
    if not topics:
        st.info("Non sono stati individuati argomenti per il quiz.")
    else:
        pending = "current_quiz" in st.session_state and "quiz_results" not in st.session_state
        if st.button("Prepara un nuovo quiz", type="primary", disabled=pending):
            try:
                with st.spinner("Preparo e controllo le domande…"):
                    history = db.load_questions(digest, mode)
                    plan = db.study_plan(stats)
                    questions, report = make_quiz(chunks, topics, plan, history, API_KEY, MODEL, REVIEW_MODEL)
                    db.save_questions(digest, mode, questions, report)
                    if questions:
                        st.session_state.current_quiz = questions
                        st.session_state.run_id = uuid.uuid4().hex
                        st.session_state.pop("quiz_results", None)
                    else:
                        st.warning("Nessuna nuova domanda ha superato i controlli. Puoi riprovare.")
            except Exception as error:
                show_error(error)
        if "current_quiz" in st.session_state:
            questions = st.session_state.current_quiz
            if "quiz_results" not in st.session_state:
                if len(questions) < 5:
                    st.info(f"Sono disponibili {len(questions)} domande: le altre sono state omesse o scartate.")
                with st.form("quiz_" + st.session_state.run_id):
                    choices = []
                    for index, item in enumerate(questions):
                        choices.append(st.radio(f"{index + 1}. {item['question']}", range(4),
                            format_func=lambda value, options=item["options"]: options[value],
                            index=None, key=f"answer_{st.session_state.run_id}_{index}"))
                    check = st.form_submit_button("Correggi il quiz", type="primary")
                if check:
                    try:
                        st.session_state.quiz_results = db.save_attempt(digest, mode, st.session_state.run_id, questions, choices)
                        st.session_state.pop("review_result", None)
                        st.rerun()
                    except Exception as error:
                        show_error(error)
            else:
                results = st.session_state.quiz_results
                score = sum(item["correct"] for item in results)
                st.success(f"Risultato: {score} risposte corrette su {len(results)}.")
                for item in results:
                    q = item["question"]
                    with st.expander(("Corretta: " if item["correct"] else "Da ripassare: ") + q["question"]):
                        st.write("La tua risposta: " + q["options"][item["selected"]])
                        st.write("Soluzione: " + q["options"][q["correct"]])
                        st.write(source_text(q["explanation"]))
                        st.caption("Fonti: " + source_labels(q["pages"]))
                        st.text(q["quote"])
                        show_sources(q["sources"])

with review_tab:
    st.subheader("Da dove ripartire")
    if not topics:
        st.write("Non ci sono ancora argomenti da ripassare.")
    elif not any(entry["total"] for entry in stats):
        st.write("Completa il primo quiz: qui compariranno gli argomenti da ripassare.")
    else:
        st.caption("Gli argomenti sotto il 70% nelle ultime 10 risposte ricevono priorita. Non e' una misura scientifica dell'apprendimento.")
        titles = {topic["id"]: topic["title"] for topic in topics}
        for entry in stats:
            topic = entry["topic"]
            with st.expander(topic["title"], expanded=entry["recent_accuracy"] is not None and entry["recent_accuracy"] < .7):
                if not entry["total"]:
                    st.write("Non ancora affrontato.")
                else:
                    st.write(f"Totale: {entry['correct']}/{entry['total']} corrette. Ultime 10: {entry['recent_accuracy']:.0%}.")
                st.caption("Da rileggere: " + source_labels(topic["pages"]))
                if st.button("Mostra il ripasso", key="review_" + topic["id"]):
                    try:
                        with st.spinner("Recupero il materiale utile…"):
                            history = db.recent_topic_answers(digest, mode, topic['id'])
                            st.session_state.review_result = consolidated_review(
                                topic, history, st.session_state.index, API_KEY, MODEL)
                    except Exception as error:
                        show_error(error)
                result = st.session_state.get("review_result")
                if result and result["topic_id"] == topic["id"]:
                    st.caption(f"Ultime {result['attempt_count']} risposte considerate: {result['correct_count']} corrette, "
                               f"{result['attempt_count'] - result['correct_count']} sbagliate.")
                    st.write(source_text(result["text"]))
                    show_sources(result["passages"])
        plan = db.study_plan(stats)
        st.write("Prossimo quiz: " + " → ".join(titles[topic_id] for topic_id in plan))

st.caption("Verifica le risposte nelle fonti: anche un quiz approvato dall'AI puo' contenere errori. Ogni fonte indica il file e la sua pagina originale.")
