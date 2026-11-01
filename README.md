# BoostLearn

BoostLearn è un assistente allo studio che parte da una dispensa in PDF. L'idea è avere nello stesso posto le spiegazioni del materiale, qualche domanda per mettersi alla prova e un ripasso degli argomenti su cui si fanno più errori.

Per le domande ho aggiunto anche la ricerca web: serve per approfondire, confrontare concetti e trovare informazioni che non sono nel documento. I quiz e il ripasso, invece, rimangono basati solo sul PDF caricato.

## Come si avvia

Serve Python 3.12. Su Windows basta aprire `avvia.cmd`: al primo avvio crea l'ambiente e installa le librerie, quindi serve Internet. Se il browser non si apre automaticamente, l'indirizzo è http://localhost:8501.

Nel file `.env`, creato al primo avvio, vanno inserite le chiavi:

```dotenv
GEMINI_API_KEY=la_tua_chiave_gemini
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_REVIEW_MODEL=
TAVILY_API_KEY=la_tua_chiave_tavily
```

Gemini gestisce le risposte, gli embedding e i quiz. Tavily serve solo per cercare sul web; la chiave si può creare su [app.tavily.com](https://app.tavily.com). Senza Tavily si può comunque lavorare sul documento, ma gli approfondimenti web non sono disponibili.

Se `GEMINI_REVIEW_MODEL` rimane vuoto, il revisore dei quiz usa lo stesso modello dell'autore. I nomi dei modelli sono configurabili perché la disponibilità dipende dal progetto Google AI Studio. Dopo aver cambiato il `.env` bisogna fermare e riavviare l'app. Il file contiene chiavi private e non va condiviso: per la consegna c'è `.env.example`.

In alternativa, dalla cartella `BoostLearn`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Come si usa

Si carica un PDF con testo selezionabile e si preme **Prepara il documento**. Il limite è di 10 MB e 100 pagine. Le scansioni non sono supportate.

### Il mio materiale

C'è un unico campo in cui fare domande, chiedere spiegazioni, riassunti o schemi. Il sistema sceglie il percorso in base alla richiesta; se non capisce a cosa ci si riferisce, chiede un chiarimento nello stesso campo. Conserva l'ultima richiesta e parte dell'ultima risposta, così si può scrivere, per esempio, "spiegalo più semplice". Non è una cronologia completa.

Per i PDF brevi viene usato il testo completo. Per quelli lunghi vengono recuperati i passaggi pertinenti oppure preparate sintesi delle varie parti, riutilizzate durante la sessione. Quando usa le sintesi lo segnala, perché alcuni dettagli possono andare persi.

Quando servono informazioni esterne, Gemini formula una query mirata e Tavily restituisce fino a cinque risultati con estratti e link. Gemini usa questi estratti per preparare l'approfondimento. La risposta distingue **Dal PDF**, con i riferimenti alle pagine, da **Approfondimento dal web**, con citazioni come `[W1]` e collegamenti alle fonti. Non vengono più mostrati i blocchi di testo nella sezione "Passaggi utilizzati": restano le pagine citate e le fonti web.

La ricerca non parte a ogni domanda. Per chiedere un approfondimento si può scrivere "cerca sul web e confronta questo concetto con..."; per restare sulla dispensa, "usa solo il PDF". La scelta viene interpretata dal modello. Se il web non è disponibile o gli estratti non bastano, rimane la risposta del documento con un avviso.

Il codice controlla che le citazioni rimandino alle fonti recuperate. Questo non garantisce da solo la correttezza del contenuto: gli estratti non sono sempre pagine complete e le fonti vanno comunque controllate.

Con **Scarica la risposta in PDF** si salvano richiesta, risposta, pagine e gli eventuali URL web. Il file viene generato senza altre chiamate AI.

### Mettimi alla prova

Il quiz propone fino a cinque domande a scelta multipla, solo sul PDF. Prima di mostrarle vengono controllati formato, pagine, citazione letterale e duplicati; un secondo passaggio AI verifica domanda e soluzione. Le domande che non superano i controlli vengono scartate, quindi possono essercene meno di cinque.

Dopo aver risposto a tutte le domande si consegna il quiz. Il punteggio è calcolato in Python e vengono mostrate soluzione, spiegazione e fonti. Anche un quiz approvato può contenere errori.

### Cosa ripassare

Qui compaiono i risultati per argomento. Quelli sotto il 70% nelle ultime dieci risposte hanno priorità: il piano assegna fino a tre posti agli argomenti deboli e due agli altri, se disponibili. Senza storico distribuisce le domande.

**Mostra il ripasso** collega risposte corrette ed errori recenti usando le fonti della dispensa. Dopo un nuovo quiz il vecchio ripasso viene invalidato e va richiesto di nuovo. Questa regola serve a orientare lo studio, non è una misura scientifica dell'apprendimento.

## Struttura e dati

- `app.py`: interfaccia Streamlit e stato della sessione.
- `rag.py`: lettura del PDF, ricerca nel documento, risposte e ripasso.
- `web_search.py`: ricerca Tavily, cache e spiegazioni delle fonti con Gemini.
- `quiz.py`: argomenti, generazione e revisione dei quiz con Agno.
- `progressi.py`: database SQLite, correzione e piano di ripasso.
- `gemini_client.py`: client condiviso e gestione degli errori.
- `pdf_export.py` e `text_format.py`: esportazione e formattazione delle risposte.

Il PDF e l'indice Chroma restano in memoria. SQLite salva argomenti, quiz, tentativi e rapporti dei controlli in `data/progressi.sqlite3`. Ricaricando lo stesso identico PDF si ritrova lo storico. L'app usa un solo profilo locale.

Gemini riceve il testo necessario alle elaborazioni; Tavily riceve la query di ricerca. Gli estratti web vengono poi inviati a Gemini. La cache web conserva in memoria fino a 64 ricerche e le riutilizza fino al cambio d'ora, per un massimo di circa un'ora.

## Verifiche e limiti

I test si eseguono dalla cartella `BoostLearn`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
