# BoostLearn

BoostLearn è un assistente allo studio che organizza piu dispense PDF per argomento e per utente. L'idea è avere nello stesso posto le spiegazioni del materiale, qualche domanda per mettersi alla prova e un ripasso degli argomenti su cui si fanno più errori.

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

Si crea un utente con **Crea utente**, oppure si entra con **Accedi** usando il solo username. Il nome è univoco anche ignorando maiuscole, spazi esterni e varianti Unicode. Non è prevista una password: chi conosce lo username può aprire quel profilo.

Nella barra laterale si crea o seleziona un **Argomento**, poi si caricano uno o più PDF e si preme **Prepara i documenti**. Il limite di 10 MB, 100 pagine e 1.000 blocchi vale per ogni PDF; le scansioni non sono supportate. Si possono aggiungere dispense in seguito: i file identici nello stesso argomento vengono ignorati. Se un file non è valido, gli altri rimangono salvati.

Ogni PDF ha il proprio indice persistente. I metadati `user_id`, `topic_id` (argomento contenitore), `document_id`, `document_name`, `page` (riferimento interno) e `original_page` permettono di raggruppare e filtrare le fonti. L'interfaccia e l'esportazione mostrano file e pagina originale.

### Il mio materiale

C'è un unico campo in cui fare domande, chiedere spiegazioni, riassunti o schemi. Il sistema sceglie il percorso in base alla richiesta; se non capisce a cosa ci si riferisce, chiede un chiarimento nello stesso campo. Le conversazioni si salvano automaticamente in SQLite. **Nuova conversazione** apre una chat distinta; il selettore **Conversazione** permette di riprenderne una precedente anche dopo la chiusura dell'app. La cronologia completa resta consultabile; il modello riceve fino a 16.000 caratteri di messaggi recenti e l'ultimo contesto utile. Si ripristinano anche chiarimenti in corso e ultima risposta con fonti ed esportazione.

Per i PDF brevi viene usato il testo completo. Per quelli lunghi vengono recuperati i passaggi pertinenti oppure preparate sintesi delle varie parti, riutilizzate durante la sessione. Quando usa le sintesi lo segnala, perché alcuni dettagli possono andare persi.

Quando servono informazioni esterne, Gemini formula una query mirata e Tavily restituisce fino a cinque risultati con estratti e link. Gemini usa questi estratti per preparare l'approfondimento. La risposta distingue **Dal PDF**, con i riferimenti alle pagine, da **Approfondimento dal web**, con citazioni come `[W1]` e collegamenti alle fonti. Non vengono più mostrati i blocchi di testo nella sezione "Passaggi utilizzati": restano le pagine citate e le fonti web.

Prima di rispondere, il sistema controlla che la richiesta sia coerente con gli argomenti del PDF, usando titoli ed estratti del documento. Le domande chiaramente fuori tema vengono rifiutate prima della ricerca: per esempio, una ricetta non viene cercata se la dispensa parla di AI. Restano validi approfondimenti, prerequisiti, esempi e confronti collegati al materiale. Se il collegamento non è chiaro, viene chiesto un chiarimento. Il controllo è affidato al modello, mentre il codice impedisce la chiamata a Tavily quando la richiesta viene classificata come estranea.

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

SQLite salva utenti, argomenti, PDF originali, testo estratto, sottoargomenti, conversazioni e progressi in `data/progressi.sqlite3`. Chroma salva una collezione per PDF in `data/indexes/`; gli indici gia pronti vengono riaperti senza ricalcolare gli embedding. Se un indice manca o e incompleto, viene ricostruito dal testo salvato. Il modello di embedding fa parte della chiave dell'indice.

Le conversazioni appartengono a un argomento; quiz e progressi sono condivisi tra le conversazioni dello stesso argomento dello stesso utente. Cambiando utente o argomento si svuota lo stato temporaneo, senza cancellare il materiale. Le sintesi intermedie e un quiz non ancora consegnato restano temporanei.

La struttura dei moduli resta invariata: `progressi.py` gestisce anche biblioteca e chat; `rag.py` gestisce indici persistenti e ricerca filtrata tra i PDF. Le tabelle vengono aggiunte automaticamente al database esistente; i vecchi progressi del profilo unico non vengono assegnati arbitrariamente a un nuovo utente.

Gemini riceve il testo necessario alle elaborazioni; Tavily riceve la query di ricerca. Gli estratti web vengono poi inviati a Gemini. La cache web conserva in memoria fino a 64 ricerche e le riutilizza fino al cambio d'ora, per un massimo di circa un'ora.

## Verifiche e limiti

I test si eseguono dalla cartella `BoostLearn`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
