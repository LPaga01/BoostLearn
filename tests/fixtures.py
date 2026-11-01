"""Dati fittizi per i test; nessun documento viene salvato su disco."""

PAGES = [
    [
        "BoostLearn - Guida fittizia al progetto",
        "Documento inventato per provare l'app. Non e' un regolamento UPO.",
        "Il progetto puo' essere svolto individualmente o in gruppi di massimo tre persone.",
        "La proposta deve essere inviata via email al docente prima di iniziare.",
        "Per la consegna sono richiesti codice sorgente e una relazione in PDF.",
        "La dimostrazione dura circa trenta minuti e coinvolge tutti i componenti.",
    ],
    [
        "Valutazione e tempi - esempio fittizio",
        "Il progetto pesa due terzi del voto finale, lo scritto un terzo.",
        "Per superare l'esame occorre almeno 18 su 30 in ciascuna prova.",
        "Il progetto deve essere completato almeno otto giorni prima dello scritto.",
        "E' consentita l'assistenza AI, ma ogni studente deve spiegare il codice.",
        "Questa guida non contiene date degli appelli o costi di iscrizione.",
    ],
]


def demo_pdf():
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for index, lines in enumerate(PAGES):
        stream_id = 5 + index * 2
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        commands = ["BT /F1 12 Tf 45 540 Td 24 TL"]
        for line in lines:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe}) Tj T*")
        stream = ("\n".join(commands) + "\nET").encode("ascii")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)



from quiz import validate_question, shuffle_options

def demo_topics():
    return [{"id": "topic-1", "title": "Organizzazione", "pages": [1]},
            {"id": "topic-2", "title": "Valutazione", "pages": [2]},
            {"id": "topic-3", "title": "Scadenze e responsabilita", "pages": [2]}]


def demo_quiz(chunks, plan, history):
    """Domande scritte a mano SOLO per guida_demo.pdf, non generate o verificate dall'AI."""
    rows = [
        ("topic-1", "Quante persone puo' avere un gruppo?", ["Al massimo tre", "Quattro", "Cinque", "Almeno sei"], "Il progetto puo' essere svolto individualmente o in gruppi di massimo tre persone.", 1),
        ("topic-1", "Come deve essere inviata la proposta?", ["Via email al docente", "Solo a voce", "Tramite social", "Non serve inviarla"], "La proposta deve essere inviata via email al docente prima di iniziare.", 1),
        ("topic-1", "Quali materiali sono richiesti per la consegna?", ["Codice sorgente e relazione PDF", "Solo schermate", "Solo una presentazione", "Un video senza codice"], "Per la consegna sono richiesti codice sorgente e una relazione in PDF.", 1),
        ("topic-1", "Quanto dura la dimostrazione del progetto?", ["Circa trenta minuti", "Cinque ore", "Un minuto", "Una giornata"], "La dimostrazione dura circa trenta minuti e coinvolge tutti i componenti.", 1),
        ("topic-2", "Quanto pesa il progetto sul voto finale?", ["Due terzi", "Un terzo", "Un decimo", "Non contribuisce"], "Il progetto pesa due terzi del voto finale, lo scritto un terzo.", 2),
        ("topic-2", "Quale voto minimo serve in ciascuna prova?", ["18 su 30", "15 su 30", "10 su 30", "30 su 30"], "Per superare l'esame occorre almeno 18 su 30 in ciascuna prova.", 2),
        ("topic-2", "Quale quota del voto dipende dallo scritto?", ["Un terzo", "Due terzi", "Tutto il voto", "Nessuna quota"], "Il progetto pesa due terzi del voto finale, lo scritto un terzo.", 2),
        ("topic-3", "Quando deve essere completato il progetto?", ["Almeno otto giorni prima dello scritto", "Dopo lo scritto", "Il giorno dello scritto", "Non ci sono indicazioni"], "Il progetto deve essere completato almeno otto giorni prima dello scritto.", 2),
        ("topic-3", "Quale obbligo rimane usando assistenza AI?", ["Saper spiegare il codice", "Nascondere il codice", "Non leggere il codice", "Cambiare universita'"], "E' consentita l'assistenza AI, ma ogni studente deve spiegare il codice.", 2),
        ("topic-3", "La guida fornisce la data esatta degli appelli?", ["No, non contiene le date", "Si', il primo giugno", "Si', il due luglio", "Si', il tre agosto"], "Questa guida non contiene date degli appelli o costi di iscrizione.", 2),
    ]
    seen = {item["id"] for item in history}
    bank = []
    for topic, text, options, quote, page in rows:
        raw = {"topic_id": topic, "question": text, "options": options, "correct": 0,
               "explanation": quote, "quote": quote, "pages": [page]}
        bank.append(validate_question(raw, topic, [chunk for chunk in chunks if chunk["page"] == page], set()))
    chosen = []
    for topic_id in plan:
        available = [item for item in bank if item["topic_id"] == topic_id and item["id"] not in seen]
        if available:
            item = available[0]
            chosen.append(shuffle_options({**item, "review_reason": "Domanda dimostrativa scritta a mano."}))
            seen.add(item["id"])
    return chosen, {"requested": len(plan), "generated": len(chosen), "accepted": len(chosen),
                    "rejected": [], "demo": True, "note": "Nessuna verifica AI: esempi predisposti."}
