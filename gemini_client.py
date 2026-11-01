"""Client Gemini condiviso tra RAG e agenti, con errori senza credenziali."""

import re
from functools import lru_cache

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"


@lru_cache(maxsize=4)
def get_client(api_key):
    if not api_key.strip():
        raise ValueError("Inserisci GEMINI_API_KEY nel file .env e riavvia l'app.")
    try:
        from google import genai
    except ImportError as error:
        raise ValueError("Manca google-genai. Chiudi l'app e riapri avvia.cmd per installarlo.") from error
    return genai.Client(api_key=api_key, http_options={
        "timeout": 60000, "retry_options": {"attempts": 1},
    })


def safe_ai_error(error, api_key):
    message = str(error)
    if api_key:
        message = message.replace(api_key, "[chiave nascosta]")
    message = re.sub(r"AIza[A-Za-z0-9_-]+|mstrl_[A-Za-z0-9_-]+", "[chiave nascosta]", message)
    code = getattr(error, "code", None)
    if "10013" in message:
        return "Connessione a Gemini bloccata dai permessi di rete (Windows 10013)."
    if code == 429 or "429" in message or "RESOURCE_EXHAUSTED" in message:
        return "Quota o frequenza Gemini superata (429). Controlla i limiti del progetto in Google AI Studio: una quota pari a zero richiede un modello o piano abilitato, non solo un'attesa."
    if code in (401, 403) or re.search(r"\b(401|403)\b|API_KEY_INVALID|PERMISSION_DENIED", message):
        return "Gemini rifiuta l'accesso. Controlla chiave, progetto e autorizzazioni in Google AI Studio."
    if code == 404 or re.search(r"\b404\b|NOT_FOUND", message):
        return "Modello Gemini non disponibile. Controlla GEMINI_MODEL e GEMINI_EMBEDDING_MODEL nel file .env."
    return "Passaggio AI non riuscito: " + message[:400]
