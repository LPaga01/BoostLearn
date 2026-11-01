"""Avvio: python -m streamlit run app.py. Un profilo locale, un PDF attivo."""

import hashlib
import os
import time
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from gemini_client import DEFAULT_MODEL
from pdf_export import answer_pdf
import progressi as db
from quiz import discover_topics, make_quiz
from rag import answer_request, build_index, consolidated_review, extract_chunks

load_dotenv(Path(__file__).with_name(".env"))
API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
REVIEW_MODEL = os.getenv("GEMINI_REVIEW_MODEL", MODEL) or MODEL

st.set_page_config(page_title="BoostLearn", page_icon="📖", layout="centered")
st.title("BoostLearn")
st.write("Studia il materiale, mettiti alla prova e scopri cosa ripassare.")


def clear_document():
    index = st.session_state.pop("index", None)
    if index:
        index[0].delete_collection(index[1].name)
    for key in ("digest", "chunks", "page_count", "empty_pages", "result", "topics",
                "current_quiz", "quiz_results", "run_id", "review_result", "summaries",
                "request_context", "pending_request"):
        st.session_state.pop(key, None)


def show_error(error):
    st.error(str(error) if isinstance(error, ValueError) else
             "Operazione non riuscita. Controlla rete, configurazione e permessi della cartella data.")


def show_sources(passages):
    for passage in passages:
        pages = passage.get("pages", [passage.get("page")])
        st.markdown("**Pagine: " + ", ".join(map(str, pages)) + "**")
        st.text(passage["text"])


mode = "ai"
if st.session_state.get("mode", mode) != mode:
    clear_document()
st.session_state["mode"] = mode
uploaded = st.file_uploader("Carica il tuo PDF", type=["pdf"])
data = uploaded.getvalue() if uploaded else b""
name = uploaded.name if uploaded else ""
st.caption("PDF con testo selezionabile, massimo 10 MB e 100 pagine. Il testo viene elaborato da Google Gemini.")
digest = hashlib.sha256(data).hexdigest() if data else None
if digest != st.session_state.get("digest"):
    clear_document()
if not API_KEY:
    st.warning("Inserisci GEMINI_API_KEY nel file .env e riavvia l'app.")

if data and "chunks" not in st.session_state:
    if st.button("Prepara il documento", type="primary", disabled=not API_KEY):
        index = None
        try:
            with st.spinner("Leggo il documento e preparo gli argomenti…"):
                chunks, pages, empty = extract_chunks(data)
                topics_key = f"{mode}:{digest}"
                topics = db.load_topics(topics_key)
                if topics is None:
                    topics = discover_topics(chunks, API_KEY, MODEL)
                index = build_index(chunks, API_KEY)
                db.save_topics(topics_key, name, topics)
                st.session_state.update(chunks=chunks, page_count=pages, empty_pages=empty,
                                        digest=digest, index=index, topics=topics)
        except Exception as error:
            if index:
                index[0].delete_collection(index[1].name)
            show_error(error)

if "chunks" not in st.session_state:
    st.write("Carica una dispensa per iniziare.")
    st.stop()

st.success(f"{name}: {st.session_state.page_count} pagine.")
if st.session_state.empty_pages:
    st.warning(f"{st.session_state.empty_pages} pagine senza testo estraibile sono state ignorate.")

topics = st.session_state.topics
chunks = st.session_state.chunks
try:
    stats = db.topic_stats(digest, mode, topics)
except Exception as error:
    show_error(error)
    st.stop()
material_tab, quiz_tab, review_tab = st.tabs(["Il mio materiale", "Mettimi alla prova", "Cosa ripassare"])

with material_tab:
    st.caption("Puoi chiedere anche confronti e approfondimenti: quando servono, uso fonti web e le distinguo dal PDF. Quiz e ripasso restano basati sulla dispensa.")
    if topics:
        st.caption("Argomenti individuati: " + " · ".join(topic["title"] for topic in topics))
    pending = st.session_state.get("pending_request")
    if pending:
        st.info(pending["clarification"] + " Rispondi nel campo qui sotto, oppure scrivi una nuova richiesta.")
    with st.form("question_form"):
        question = st.text_input("Che cosa vuoi sapere?", placeholder="Spiegami un concetto, riassumi il PDF o crea uno schema…", max_chars=1000)
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
                    answer = answer_request(question, topics, st.session_state.index[1], chunks,
                        API_KEY, MODEL, cache, st.session_state.get("request_context"), pending, web_enabled=True)
                    if "clarification" not in answer:
                        passages = answer.pop("passages")
                        summarized = answer.pop("summarized")
                    if "clarification" in answer:
                        st.session_state.pending_request = answer
                        st.rerun()
                    st.session_state.pop("pending_request", None)
                    if not answer.get('rejected'):
                        st.session_state.request_context = {"request": answer.get("request", question), "answer": answer["text"][:2000]}
                    st.session_state.result = {**answer, "passages": passages, "question": question, "summarized": summarized,
                                               "seconds": time.perf_counter() - started}
            except Exception as error:
                show_error(error)
    if "result" in st.session_state:
        result = st.session_state.result
        st.subheader("Risposta")
        st.caption(result["question"])
        st.write(result["text"])
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
            st.caption("Pagine del PDF: " + ", ".join(map(str, result["pages"])))
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
                        st.write(q["explanation"])
                        st.caption("Pagine: " + ", ".join(map(str, q["pages"])))
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
                st.caption("Pagine da rileggere: " + ", ".join(map(str, topic["pages"])))
                if st.button("Mostra il ripasso", key="review_" + topic["id"]):
                    try:
                        with st.spinner("Recupero il materiale utile…"):
                            history = db.recent_topic_answers(digest, mode, topic['id'])
                            st.session_state.review_result = consolidated_review(
                                topic, history, st.session_state.index[1], API_KEY, MODEL)
                    except Exception as error:
                        show_error(error)
                result = st.session_state.get("review_result")
                if result and result["topic_id"] == topic["id"]:
                    st.caption(f"Ultime {result['attempt_count']} risposte considerate: {result['correct_count']} corrette, "
                               f"{result['attempt_count'] - result['correct_count']} sbagliate.")
                    st.write(result["text"])
                    show_sources(result["passages"])
        plan = db.study_plan(stats)
        st.write("Prossimo quiz: " + " → ".join(titles[topic_id] for topic_id in plan))

st.caption("Verifica le risposte nelle fonti: anche un quiz approvato dall'AI puo' contenere errori. Le pagine si riferiscono al file PDF.")
