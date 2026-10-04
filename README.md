# velo

[![test](https://github.com/GiuseppeB-portfolio/velo/actions/workflows/tests.yml/badge.svg)](https://github.com/GiuseppeB-portfolio/velo/actions/workflows/tests.yml)
[![licenza: MIT](https://img.shields.io/badge/licenza-MIT-blue.svg)](LICENSE)

Pseudonimizza file Excel, CSV e JSON **in locale**, prima di condividerli con terzi o con un'AI. Tu scegli i campi da sostituire: l'app non indovina niente.

> **Stato: versione 0.1, pre-release.** Il progetto è nato come lavoro personale e non è stato verificato da terzi. Leggi la sezione [Limiti](#limiti) prima di usarlo con dati reali.

## Cosa fa

1. Apri un file `.xlsx`, `.csv` o `.json`.
2. L'app mostra i campi con un'anteprima dei valori (le colonne per Excel e CSV, i percorsi come `clienti[].anagrafica.nome` per il JSON).
3. Per ogni campo che scegli, indichi che tipo di dato contiene e come sostituirlo: con un **valore finto realistico** generato da [Faker](https://faker.readthedocs.io/) (locale `it_IT`) oppure con un **segnaposto** come `[IBAN_VCS4M]`.
4. Ottieni un nuovo file e un **dizionario di ripristino** per tornare ai dati originali.

I campi che non scegli restano esattamente come erano.

Principi di progetto:

- **La scelta è tua.** Nessun riconoscimento automatico, nessun modello di machine learning.
- **Tutto in locale.** Il server ascolta solo su `127.0.0.1` e il codice non apre connessioni verso l'esterno.
- **Coerenza.** Lo stesso valore diventa sempre lo stesso valore finto, in tutti i fogli e in tutti i campi dello stesso tipo.
- **Fedeltà al formato.** Le colonne non scelte non cambiano di una virgola; in CSV e JSON il file ripristinato torna identico all'originale, byte per byte.

## Esempio

File originale (`clienti.csv`, dati inventati):

| Nome e cognome | Email | IBAN | Importo | Note |
|---|---|---|---|---|
| Anna Verdi | anna.verdi@posta.test | IT60X0542811101000000123456 | 1.234,56 | In cura per diabete, referente Luca Neri |

Dopo aver scelto *Nome e cognome*, *Email*, *IBAN* (come segnaposto) e *Importo*, ma non *Note*:

| Nome e cognome | Email | IBAN | Importo | Note |
|---|---|---|---|---|
| Durante Zaccagnini | tonino76@example.net | [IBAN_VCS4M] | 1.406,66 | In cura per diabete, referente Luca Neri |

I valori finti cambiano a ogni esecuzione. La colonna *Note* non è stata scelta e quindi **resta in chiaro, con il dato sanitario e il nome di un'altra persona**: è il limite più importante, spiegato in [Limiti](#limiti).

## Installazione

Serve Python 3.11 o superiore. In PowerShell su Windows:

```powershell
git clone https://github.com/GiuseppeB-portfolio/velo.git
cd velo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
velo
```

Su macOS e Linux l'attivazione dell'ambiente è `source .venv/bin/activate`; il resto è uguale.

**Controlla che l'ambiente sia attivo.** Dopo l'attivazione la riga di comando inizia con `(.venv)`. Se non c'è, `pip install .` installa nell'ambiente globale di Python e `velo` non viene trovato. Puoi verificarlo con `pip -V`: il percorso mostrato deve contenere `.venv`. L'attivazione `.\.venv\Scripts\Activate.ps1` funziona solo in PowerShell: se usi il Prompt dei comandi (`cmd`), il comando è `.venv\Scripts\activate.bat`.

Se dopo l'installazione `velo` risulta «non riconosciuto», quasi sempre l'ambiente non era attivo durante `pip install .`: attivalo e ripeti `pip install .`.

`velo` avvia il server e apre il browser su `http://127.0.0.1:8765`. Si chiude con `Ctrl+C`.

| Opzione | Effetto |
|---|---|
| `--port NUMERO` | usa un'altra porta (default 8765) |
| `--no-browser` | non apre il browser |

### Dalla volta successiva

L'installazione si fa una volta sola. Per riavviare il programma basta riattivare l'ambiente virtuale e lanciare `velo`, dalla cartella in cui hai clonato il progetto:

```powershell
cd velo
.\.venv\Scripts\Activate.ps1
velo
```

Su macOS e Linux la seconda riga è `source .venv/bin/activate`. Se all'inizio della riga di comando vedi già `(.venv)`, l'ambiente è attivo e puoi saltarla. Si chiude con `Ctrl+C`; se la porta risulta occupata da un avvio precedente, chiudi quella finestra oppure usa `velo --port 8766`.

Se non vuoi attivare l'ambiente ogni volta, puoi lanciare il comando direttamente: `.\.venv\Scripts\velo.exe` su Windows, `.venv/bin/velo` altrove.

**Per aggiornare** a una versione più recente: `git pull` e poi di nuovo `pip install .` (con l'ambiente attivo). Il passo `pip install .` serve perché l'installazione normale copia il programma nell'ambiente virtuale. Se invece hai installato in modalità sviluppo (`pip install -e ".[dev]"`), il codice viene letto direttamente dalla cartella del progetto e dopo un `git pull` non serve reinstallare, a meno che siano cambiate le dipendenze in `pyproject.toml`.

Funziona anche come `python -m velo`. Il nome del pacchetto per `pip` è `velo-pseudonymizer`, perché `velo` su PyPI è occupato da un progetto non correlato; il comando e il modulo Python si chiamano `velo`.

**Un consiglio pratico.** Il browser salva i file scaricati nella cartella Download, che su molti computer è sincronizzata con un servizio cloud (OneDrive, iCloud, Dropbox). Il dizionario di ripristino contiene i dati originali: salvalo in una cartella non sincronizzata.

## Uso

**Pseudonimizzare.** Carica il file con *Apri il file*. Spunta i campi da sostituire e, per ciascuno, scegli il tipo di dato (non c'è un valore preselezionato) e la modalità. Scegli la chiave (vedi [Coerenza e chiavi](#coerenza-e-chiavi)) e premi *Sostituisci i campi scelti*. Scarica il file pseudonimizzato (`nome.pseudo.xlsx`, `.csv` o `.json`) e, se ti serve tornare indietro, il dizionario (`nome.pseudo.xlsx.velo-map.json`). L'originale non viene mai toccato e nessun file esistente viene sovrascritto.

**Controllo dei valori.** Prima di scrivere, l'app confronta i valori dei campi scelti con il tipo indicato. Se, per esempio, in una colonna di IBAN c'è la scritta «Totale», te lo dice e aspetta una tua conferma. È solo un avviso: non cambia la scelta e non cerca dati sensibili da solo.

**Ripristinare.** Nella pagina *Ripristina* carica il file pseudonimizzato e il suo dizionario. I valori non presenti nel dizionario restano come sono e vengono segnalati.

**File temporanei.** I file caricati e prodotti stanno in una cartella temporanea privata (`velo-…` nella cartella temporanea del sistema). Vengono cancellati alla chiusura del programma, con il pulsante *Elimina questi file dal computer*, e all'avvio successivo se hanno più di 24 ore.

## Formati

**Excel (`.xlsx`).** La prima riga di ogni foglio è l'intestazione e i campi si chiamano `Foglio!Intestazione`. Più fogli, anche nascosti (l'app lo segnala). Le celle con formule non vengono mai toccate. Tipi, formati numerici, stili, larghezze, celle unite, riquadri bloccati e convalide dei dati restano intatti. Per default vengono rimossi titolo, oggetto, descrizione e parole chiave del documento e l'autore diventa «velo» (opzione disattivabile); le date di creazione e di modifica restano. Non sono supportati `.xls` e `.xlsm`.

**CSV.** Riconosce da solo la codifica (UTF-8 con o senza BOM, Windows-1252), il delimitatore (`;`, `,`, tabulazione, `|`), il terminatore di riga e la presenza dell'ultimo a capo, e scrive l'output con gli stessi parametri. I valori sono trattati come testo: `1.234,56` resta `1.234,56` nelle colonne non scelte.

**JSON.** Strutture annidate, campi scelti per percorso. Il file non viene riscritto: l'app sostituisce solo i tratti di testo scelti, quindi indentazione, ordine delle chiavi, escape (`\u00e8`, `\/`) e grafia dei numeri (`1.10`, `1e5`) restano come nell'originale. Un JSON non valido (compresi `NaN` e virgole finali) viene rifiutato.

## Tipi di dato

| Tipo | Valore finto |
|---|---|
| Nome e cognome, Nome, Cognome | Faker `it_IT`; mantiene maiuscole e minuscole |
| Codice fiscale | Faker; formalmente valido (carattere di controllo corretto), **non coerente** con nome e data di nascita |
| IBAN | Faker; IBAN italiano valido; mantiene gli spazi se l'originale li ha |
| Partita IVA | generata da velo con cifra di controllo valida; il prefisso `IT` solo se l'originale lo ha |
| Email | Faker `safe_email`: solo domini riservati `example.*` |
| Telefono | stesso formato, prefisso `+39`/`0039` e prima cifra dell'originale |
| Indirizzo, Città | Faker |
| CAP | cifre casuali della stessa lunghezza |
| Data | spostata di circa ±2 anni, nello stesso formato e dello stesso tipo (testo, data, data e ora) |
| Importo | moltiplicato per un fattore casuale (circa da 0,5 a 1,5), con gli stessi separatori, simboli, segno e decimali; gli zeri restano zero |
| Testo generico | testo Faker, lungo al più quanto l'originale (almeno 5 caratteri) |

Il **segnaposto** ha la forma `[CATEGORIA_XXXXX]` ed è sempre un testo. Un valore che non rispetta il formato del suo tipo (una data «boh», un importo «circa dieci euro») diventa un segnaposto e viene segnalato. In modalità valore finto i valori booleani restano invariati.

## Coerenza e chiavi

Ogni valore finto parte da `HMAC-SHA256(chiave, categoria | modalità | tipo | valore | tentativo)`, che fa da seme per Faker. A parità di chiave, lo stesso valore dà sempre lo stesso risultato. La corrispondenza è uno a uno: se un candidato è già preso, o coincide con il valore reale, si prova il successivo. La coerenza vale sul testo esatto: «Mario Rossi» e «MARIO ROSSI» sono due valori diversi.

| Chiave | Cosa succede |
|---|---|
| **Solo per questo file** (consigliata) | casuale, vive solo in memoria. Coerente dentro il file; file elaborati separatamente non sono collegabili tra loro. |
| **Salvata su questo computer** | `project.key` in `%APPDATA%\velo` (Windows) o `~/.config/velo` (altrove). La stessa persona ha lo stesso nome finto in **tutti** i file. Utile per i join tra file, ma chi riceve più file elaborati con la stessa chiave può incrociarli. |

La chiave salvata è sensibile quanto il dizionario: chi la possiede può provare nomi candidati e confrontarli con l'output.

## Il dizionario di ripristino

Il file `*.velo-map.json` contiene, per ogni valore finto, il valore reale (con il suo tipo esatto), il piano dei campi, la versione di Faker e i parametri del file originale. **Va trattato come il file originale**: non condividerlo, non caricarlo su servizi esterni o su un'AI, non spedirlo insieme al file pseudonimizzato. Un avviso in testa al file lo ricorda. Senza il dizionario il ripristino è impossibile.

Il ripristino di CSV e JSON restituisce l'originale byte per byte (l'app lo verifica con un'impronta SHA-256 e lo dice). Per Excel i valori, i tipi e i formati tornano uguali, ma il file viene riscritto, quindi non è identico byte per byte.

## Sicurezza dell'applicazione locale

- Il server ascolta solo su `127.0.0.1`; le richieste con un `Host` diverso vengono rifiutate (protegge dal *DNS rebinding*).
- Ogni operazione che modifica qualcosa richiede un token casuale generato all'avvio (protegge da richieste inviate da altri siti).
- Content-Security-Policy restrittiva, nessuna risorsa esterna, nessuna cache, nessun font o script da CDN.
- I nomi dei file caricati vengono sanificati e il contenuto dei file non viene mai inserito nelle pagine senza escape.
- Nessuna telemetria e nessuna richiesta di rete in uscita.

## Limiti

Questa sezione è volutamente lunga: sapere cosa l'app non fa è parte del suo valore.

### Pseudonimizzazione, non anonimizzazione

Esiste un dizionario che permette di tornare ai dati originali, quindi il risultato è una **pseudonimizzazione**. L'art. 4, n. 5 del GDPR definisce la pseudonimizzazione e il considerando 26 precisa che i dati pseudonimizzati, attribuibili a una persona con l'uso di informazioni aggiuntive, vanno considerati informazioni su una persona identificabile: restano dati personali. velo **riduce** il rischio di diffusione e lo rende controllabile: non lo annulla. Non è una consulenza legale e non sostituisce la valutazione del tuo responsabile della protezione dei dati.

### Cosa resta in chiaro

- **I campi che non scegli.** L'app non sa quali contengano dati personali. È una scelta di progetto, ma significa che dimenticare una colonna equivale a pubblicarla.
- **I dati personali scritti nel testo libero.** Note, descrizioni e commenti non scelti mantengono nomi, indirizzi, IBAN, targhe e dati sanitari. L'esempio sopra mostra esattamente questo caso. Anche se scegli un campo di testo libero, l'app lo sostituisce per intero: non cerca i dati al suo interno.
- **Combinazioni di campi rari.** Anche senza nomi, una data di nascita, un CAP e un importo insoliti possono bastare per riconoscere una persona. Pseudonimizzare un campo alla volta non misura questo rischio.
- **Importi e date approssimati, non nascosti.** Un importo moltiplicato per un fattore tra 0,5 e 1,5 e una data spostata di due anni conservano l'ordine di grandezza e la collocazione temporale. Chi conosce il contesto può ricostruire molto.
- **In Excel:** testo scritto dentro le formule, commenti delle celle (con autore), nomi dei fogli, intestazioni, nomi definiti e proprietà personalizzate del documento non vengono modificati. L'app segnala quando ne trova.

### Qualità dei valori finti

- **Il serbatoio di Faker è piccolo.** Con Faker 40 i nomi propri distinti sono circa 458, i cognomi circa 1.164 e i comuni circa 16.100. Quando i valori distinti superano il serbatoio, i finti ricevono un numero finale («Rossi 2») e l'app lo segnala. In un file di prova con 4.000 nomi distinti è successo per la grande maggioranza.
- **Un valore finto può coincidere con un valore vero di un'altra riga.** I nomi finti vengono estratti dallo stesso elenco di Faker da cui provengono molti nomi reali: se nel file c'è un «Mario», il finto di un'altra persona può essere «Mario». Non è una fuga di dati e il ripristino funziona lo stesso, ma chi legge l'output non può dedurre che un nome sia vero perché compare anche nell'originale.
- **I finti sono internamente incoerenti.** Il codice fiscale non corrisponde a nome e data di nascita; chi conosce la sua struttura capisce che è finto.
- **Possibili coincidenze con dati reali.** Un telefono, un IBAN o un'email finti potrebbero esistere davvero. Le email usano domini riservati, quindi non possono arrivare a nessuno; per telefoni e IBAN non c'è questa garanzia.
- **La stabilità tra file ha delle eccezioni.** Con la chiave salvata, lo stesso valore dà lo stesso finto in file diversi, tranne i valori coinvolti in collisioni, la cui sorte dipende dall'ordine di arrivo. Dipende anche dalla versione di Faker: aggiornarla può cambiare i valori generati (la versione è salvata nel dizionario).

### Per formato

- **Excel.** Non sono supportati `.xls` e `.xlsm`. Il file viene riscritto con openpyxl: grafici e immagini semplici sopravvivono, ma le immagini richiedono Pillow (non incluso) e andrebbero altrimenti perse; forme, slicer e commenti a catena possono andare persi, dei collegamenti esterni si perdono i valori memorizzati, e tabelle pivot e grafici complessi possono non essere conservati fedelmente. L'app lo segnala quando li rileva. Le formule non hanno valori memorizzati finché il file non viene riaperto in Excel, che li ricalcola.
- **CSV.** Se le virgolette dell'originale non sono quelle standard, nell'output vengono riscritte in modo diverso (i valori restano identici) e l'app lo dice. In un file solo ASCII la codifica originale non è determinabile: se l'output contiene lettere accentate viene scritto in UTF-8. UTF-16 non è supportato.
- **JSON.** Il file viene caricato per intero in memoria (un file di 17 MB si legge in circa 4 secondi). I file JSON Lines (`.jsonl`) non sono supportati. Se in un campo numerico scegli il segnaposto, il valore diventa testo e l'app lo segnala.

### Operativi e di sicurezza

- **Il file della chiave non è cifrato.** Su Windows non vengono ristretti i suoi permessi.
- **File temporanei.** Se chiudi la finestra del terminale invece di usare `Ctrl+C`, i file temporanei restano fino al prossimo avvio. Usa il pulsante *Elimina questi file dal computer* quando hai finito.
- **Un solo utente, un solo computer.** L'app usa il server di sviluppo di Flask. Non è pensata per essere esposta in rete, né per più utenti.
- **Nessun audit.** Il codice non è stato sottoposto a una revisione di sicurezza indipendente.

### Cosa non è stato verificato

- L'interfaccia in tutti i browser e i sistemi operativi; la suite di test gira su Windows e Linux nell'integrazione continua, ma non c'è stata una prova manuale approfondita.
- Il comportamento con file Excel reali di grandi dimensioni o con strutture insolite.
- La copertura del 99% dei test indica che le righe vengono eseguite, non che ogni risultato sia corretto. I test con dati casuali cercano difetti, non ne dimostrano l'assenza.

## Sviluppo

```text
src/velo/
├── model.py          tipi condivisi (categorie, modalità, piano)
├── engine.py         motore: HMAC, coerenza, unicità dei valori finti
├── generators.py     un generatore per categoria
├── checks.py         controllo dei valori rispetto al tipo scelto
├── mapping.py        dizionario di ripristino e ripristino
├── service.py        pseudonimizza() e ripristina()
├── keystore.py       chiavi
├── validators.py     controlli con checksum (CF, IBAN, P.IVA)
├── formats/          adapter: excel, csv, json
└── web/              interfaccia Flask (template e CSS inclusi)
scripts/              controllo di pubblicabilità
tests/                oltre 300 test, anche con dati generati a caso
```

L'architettura ruota attorno a un'interfaccia comune: ogni formato sa leggere i campi (`inspect`) e riscrivere il file toccando solo quelli del piano (`apply`). La pseudonimizzazione e il ripristino sono due «sostituitori» che passano per lo stesso codice, quindi la logica di lettura e scrittura è scritta e testata una volta sola.

```powershell
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest --cov
python scripts/check_publishable.py
```

L'ultimo comando controlla che nei file tracciati da git non ci siano dizionari di ripristino, chiavi, file di dati, segreti, percorsi personali o email, IBAN e codici fiscali non presenti nell'elenco di valori sintetici. Va eseguito prima di ogni push.

L'integrazione continua (`.github/workflows/tests.yml`) esegue gli stessi controlli su Ubuntu e Windows con Python 3.11, 3.12 e 3.13.

## Roadmap

**Fase 2 (non implementata).** Suggerimenti automatici, sempre da confermare o cambiare e mai decisioni prese al posto dell'utente: campi sensibili dedotti dal nome della colonna e dal formato dei valori (con i controlli già presenti per codice fiscale, IBAN e partita IVA, più carte di credito, email e telefoni) e riconoscimento di entità nel testo libero. Per quest'ultimo ogni modello verrà valutato su un test set scritto a mano, dando più peso alla recall (un dato mancato è l'errore grave), e prima di sceglierne uno si verificheranno le licenze di modelli e dataset per l'uso commerciale.

## Licenza

[MIT](LICENSE). Le dipendenze sono compatibili: Faker e openpyxl sono MIT, Flask e le sue dipendenze (Werkzeug, Jinja2, MarkupSafe, ItsDangerous, Click) sono BSD-3-Clause, Blinker ed et_xmlfile sono MIT. Gli strumenti di sviluppo (pytest, ruff, hypothesis) non sono distribuiti con il programma.
