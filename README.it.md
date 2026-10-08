<p align="center">
  <img src="assets/logo.png" alt="Open MCP CAD" width="210">
</p>

<p align="center">
  <a href="README.md">Deutsch</a> · <a href="README.en.md">English</a> · <a href="README.fr.md">Français</a> · <b>Italiano</b>
</p>

# Open MCP CAD

**Il ponte tra un assistente IA e il tuo CAD in esecuzione.**

Un server MCP e un plugin CAD che permettono a un modello linguistico di
leggere e creare geometria in un **documento Cadwork 3D aperto**, con coda
di lavoro, schede di approvazione, licenza di scrittura, supporto per
l'annullamento e una finestra che mostra in ogni momento cosa sta
succedendo.

> **Cosa NON c'è qui:** logica costruttiva. Nessun catalogo di dettagli,
> nessun generatore di elementi, nessuna conoscenza di settore. Questo
> repository è il tubo, non l'acqua. La tua conoscenza di settore la
> colleghi tramite `OPEN_MCP_CAD_KNOWLEDGE`, vedi
> [La tua conoscenza di settore](#la-tua-conoscenza-di-settore).

---

<!-- ki-assistenten:anfang -->
## Per gli assistenti IA (For AI assistants)

Sei un'IA e devi installare Open MCP CAD? Allora vale questo:

- **Il server MCP esiste già.** Si chiama `open-mcp-cad` e si avvia con
  `python -m open_mcp_cad.server`. **Non costruire un adattatore, un ponte
  o un server tuo.**
- **Non parlare mai direttamente con il plugin.** Il plugin in Cadwork
  ascolta su `127.0.0.1`, porte 53127–53199, con un protocollo interno
  (righe JSON) che esiste solo per questo server. Nessun programma di IA
  vi si collega direttamente.

Il tuo compito è solo questo:

1. **Eseguire l'installatore, se non è ancora stato fatto.** L'utente fa
   doppio clic su `1_INSTALLIEREN.cmd` in cima allo ZIP estratto (ultima
   versione:
   https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest).
   Copia il plugin in Cadwork, installa il server in
   `%LOCALAPPDATA%\OpenMcpCad\python` e alla fine propone di fare da sé il
   passo 2. Il server è installato quando
   `"%LOCALAPPDATA%\OpenMcpCad\python\Scripts\python.exe" -c "import open_mcp_cad.server"`
   termina senza errori.
2. **Registrare il server nel programma di IA**, se l'installatore non
   l'ha fatto. `<PYTHON>` è il percorso completo di
   `%LOCALAPPDATA%\OpenMcpCad\python\Scripts\pythonw.exe` (con **w**: senza
   finestra di console). Prima fare una copia di sicurezza del file,
   aggiungere solo la voce `open-mcp-cad` e lasciare invariate tutte le
   altre voci.
   - **Codex** (CLI e app Codex): `%USERPROFILE%\.codex\config.toml`
     (oppure `%CODEX_HOME%\config.toml`)
     ```toml
     [mcp_servers.open-mcp-cad]
     command = '<PYTHON>'
     args = ["-m", "open_mcp_cad.server"]
     ```
   - **Claude Desktop**: `%APPDATA%\Claude\claude_desktop_config.json`
     (versione dallo Store: sotto
     `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`), nel
     JSON le barre rovesciate vanno raddoppiate
     ```json
     {
       "mcpServers": {
         "open-mcp-cad": { "command": "<PYTHON>", "args": ["-m", "open_mcp_cad.server"] }
       }
     }
     ```
   - **Claude Code**:
     ```
     claude mcp add --scope user open-mcp-cad -- "<PYTHON>" -m open_mcp_cad.server
     ```
3. **Dire all'utente:** chiudere del tutto il programma di IA e riavviarlo,
   poi in Cadwork fare clic su **Open MCP CAD** nel menu dei plugin, finché
   la piccola barra in alto a destra mostra **Bereit** (pronto). Dopo, gli strumenti di Open MCP
   CAD (per esempio `get_document_info`) sono disponibili nel programma di
   IA.

ChatGPT (la normale app di chat) non può usare server MCP locali. Con lo
stesso account ChatGPT funziona nell'app Codex.
<!-- ki-assistenten:ende -->

## Perché esiste

Un modello linguistico sa scrivere codice cwapi3d. Farlo arrivare in un CAD
in esecuzione è il vero problema:

- **cwapi3d non è thread-safe.** Ogni chiamata all'API deve essere
  eseguita nel thread principale, una dopo l'altra. Chi lo ignora ottiene
  crash che sembrano impossibili da riprodurre.
- **Il CAD non deve bloccarsi** mentre un'operazione è in corso.
- **Al modello non deve succedere nulla di nascosto.** Ogni chiamata va in
  uno storico, ogni accesso in scrittura dietro un'approvazione.
- **Più documenti contemporaneamente** richiedono linee separate che non
  si incrociano.

Tutto questo è qui, misurato e non solo affermato: **oltre 600 controlli
senza installazione CAD**, più un test che costruisce e usa davvero
l'interfaccia.

## Architettura

```
Assistente IA --stdio--> server MCP --TCP 127.0.0.1:53127..53199--> plugin CAD
   (host)               (open-mcp-cad)                               (in Cadwork)
                                                                          |
                                                                       cwapi3d
```

**Tutte le linee che servono.** Una sola voce di menu **Open MCP CAD**,
avviata in tutte le finestre Cadwork che servono. Un clic apre il pannello
e si collega: ogni finestra riceve la prossima porta libera (53127–53199),
un proprio log e una propria casella di posta. Così lavori su più
documenti in parallelo senza che le linee si incrocino.

Ogni istanza si registra con il **nome del proprio documento**. Viene poi
trovata tramite il documento, non tramite la porta:

```bat
set OPEN_MCP_CAD_DOC=Seeblick
```

È la domanda che ci si pone davvero. *"Quale porta serve Seeblick?"* prima
non era scritto da nessuna parte, bisognava ricordarselo. Il client sceglie
solo se corrisponde **esattamente una** istanza in esecuzione. Se ne
corrispondono più d'una, o nessuna (per esempio perché il server è partito
prima di Cadwork), non invia nulla, elenca ciò che è collegato e chiede di
nuovo alla chiamata successiva. Non ripiega mai su una porta fissa: codice
nel file sbagliato è esattamente il danno che la protezione del documento
deve evitare. Una volta trovata, resta su quella finestra, come descritto
sotto.

Senza alcuna impostazione non serve nemmeno questo: il server prende
l'**unica** finestra collegata. Se ne sono collegate più d'una, non tira a
indovinare ma risponde con `instanz_waehlen` e l'elenco, e l'IA sceglie
con `wait_for_bridge`. Una volta scelta, resta su quella finestra, anche se
più tardi se ne collega una seconda. Se viene chiusa o mostra un altro file,
chiede di nuovo; non cambia mai in silenzio. (Solo il server sceglie così;
gli script che importano `bridge_client` restano su 53127 senza
impostazioni.)

Il nucleo esiste **una sola volta** in
`cad_plugin/_core/omcad_bridge_core.py`. Le cartelle del plugin vengono
generate da lì e verificate byte per byte. Accanto alla cartella
distribuita `Open MCP CAD`, il repository contiene `Open MCP CAD A` … `F`
con porte fisse (53127–53132), per i test e per gli host che hanno bisogno
di una porta fissa.

### Come il CAD resta utilizzabile

Il listener TCP gira in un thread secondario, l'elaborazione di
un'operazione esclusivamente nel thread principale, tramite un `QTimer`
che si aggancia al ciclo di eventi **esistente** del CAD. Richieste di
stato, pausa e arresto vengono gestite direttamente dai thread di lavoro e
non aspettano mai un'operazione in corso.

Quando il CAD lavora esso stesso nel thread principale (una finestra di
dialogo modale o di avanzamento, un menu aperto, un ciclo di eventi
annidato), il timer lascia tutte le operazioni in coda e non chiama l'API;
`get_connection_status` ne indica il motivo (`cadwork_beschaeftigt`).
L'occasione è stata un crash dopo che due operazioni di lettura erano state
eseguite nel mezzo di un lungo calcolo del CAD. Per ogni processo del CAD
gira al massimo un servizio: un altro clic sul plugin riporta quello in
esecuzione invece di aprire una seconda porta.

> La strada più ovvia, pompare i messaggi di finestra dall'interno del
> plugin, non era la soluzione ma la causa: ha provocato in modo
> dimostrato una violazione di accesso nel processo del CAD. Il
> ragionamento è in [`docs/BRIDGE.md`](docs/BRIDGE.md), sezione 2 (in
> tedesco).

## Strumenti

| Strumento | Cosa fa | Tramite il ponte? |
|---|---|---|
| `get_document_info` | nome del documento + numero di elementi | sì |
| `get_connection_status` | stato, operazione in corso, coda, licenza di scrittura, **risponde anche durante il disegno** | sì, senza thread principale |
| `execute_cadwork_command` | esegue codice Python cwapi3d (attesa della risposta con `timeout_s`) | sì |
| `execute_cadwork_batch` | esegue lo stesso codice a pacchetti su un elenco di dati JSON: grandi quantità, avanzamento nel pannello | sì |
| `undo` / `redo` | annulla o ripristina le ultime operazioni (l'annulla proprio di cadwork) | sì |
| `set_fast_draw` | disattiva l'aggiornamento dello schermo durante lunghi disegni | sì |
| `redraw_view` | ridisegna la vista se dopo uno zoom in un'operazione non si vede nulla (non modifica il modello) | sì |
| `report_check_note` | segnala un'ipotesi o un'incertezza nella finestra del CAD, con ID degli elementi cliccabili | sì, senza thread principale |
| `clear_check_notes` | rimuove le note di controllo già risolte | sì, senza thread principale |
| `get_pending_messages` | recupera i messaggi che l'utente ha lasciato nel CAD | sì, senza thread principale |
| `list_stored_keys` / `clear_store` | vedere / svuotare la memoria di sessione del ponte (liste di ID degli elementi) | sì |
| `create_from_init` | crea un nuovo `.3d` come copia di un modello (non sovrascrive mai) | no, locale |
| `open_document` | apre un `.3d` tramite l'associazione dei file di Windows | no, locale |
| `wait_for_bridge` | aspetta che proprio questo file sia collegato, lo verifica e vi lega la sessione | sì |
| `get_cadwork_api_help` | moduli, funzioni e firme dai type stub | no, locale |
| `get_working_examples` | esempi di codice verificati | no, locale |
| `get_detail` | catalogo di dettagli, **solo con conoscenza di settore collegata** | no, locale |
| `get_experiences` | esperienze da errori precedenti su questo computer | no, locale |
| `record_experience` | registra ciò che ha aiutato dopo un errore | no, locale |

**Creare un nuovo file e collegarsi:** `create_from_init` →
`open_document` → cliccare una volta su **Open MCP CAD** (l'utente o
l'host dell'agente) → `wait_for_bridge`. Solo dopo un'operazione scrive
nel modello.

## Esperienze (solo su questo computer)

Se un'operazione fallisce per il suo codice (Cadwork segnala un'eccezione
Python) e in seguito ne riesce una dello stesso tipo, il server registra
un'**esperienza**: tipo e messaggio d'errore, la funzione che ha fallito,
cosa è cambiato dopo (chiamate nuove e rimosse, un estratto del codice),
versione di Cadwork e del nucleo. L'agente aggiunge con
`record_experience` una frase su ciò che ha aiutato. Al prossimo avvio le
esperienze più recenti sono nella descrizione di
`execute_cadwork_command`, e un errore già visto porta con sé la sua
esperienza nella risposta.

Il file resta su questo computer; il server non lo invia da nessuna
parte. Ciò che l'agente ne legge (descrizione, risposte) va, come ogni
testo degli strumenti, al fornitore del suo modello. Il salvataggio è quindi
ripulito — senza percorsi, nomi di file, documenti, utente e computer,
senza la descrizione dell'operazione, senza stringhe e numeri a più cifre
del codice — e limitato (200 voci, 256 KB), in
`%LOCALAPPDATA%\OpenMcpCad\erfahrungen.jsonl`. Altra posizione:
`OPEN_MCP_CAD_ERFAHRUNGEN=<file>`; `OPEN_MCP_CAD_ERFAHRUNGEN=aus` la
disattiva.

## La tua conoscenza di settore

La conoscenza integrata in `open_mcp_cad/knowledge/` riguarda
esclusivamente l'**interfaccia cwapi3d**, trappole in cui cadono tutti:
che `cut_element_with_plane` conserva il lato opposto alla normale, che
`z_local` determina la rotazione, che i calcoli puri non hanno nulla a che
fare con il ponte. Ogni voce è stata verificata su un modello reale.

La conoscenza del tuo settore la aggiungi accanto:

```bat
set OPEN_MCP_CAD_KNOWLEDGE=C:\mio-catalogo\knowledge
```

Una cartella di questo tipo può contenere:

| File | Effetto |
|---|---|
| `rules.md` | regole passate con **ogni** operazione. Tenerle brevi, costano token a ogni chiamata. Senza `rules.md` valgono tutti i `<dominio>_rules.md` della cartella (in ordine alfabetico). |
| `known_issues.json` | `{"issues": [...]}`, aggiunto |
| `working_examples.json` | `{"examples": [...]}`, aggiunto |
| `detail_catalog.json` | `{"details": [...]}`, aggiunto, alimenta `get_detail` |

Separare più cartelle con `;` (Windows). Una cartella che non esiste viene
**segnalata** e saltata. Ignorarla in silenzio significherebbe non
accorgersi per mesi che le proprie regole non sono mai arrivate.

## Installazione

**Requisiti:** Windows, Cadwork 3D 2026 (lì i plugin girano con
Python 3.14), Python 3.10–3.13 per il server MCP (se manca, `1_INSTALLIEREN.cmd`
installa Python 3.13 tramite winget dopo averlo chiesto, oppure, senza
winget, direttamente da python.org con verifica della firma).

**Come utente:** costruire il pacchetto (oppure prendere lo ZIP dalle
release), estrarlo, fare doppio clic su `1_INSTALLIEREN.cmd`. Copia il plugin nel
profilo di Cadwork 2026 (se ci sono più profili chiede quale, e non
copia nel profilo di un'altra versione di Cadwork), installa il server in un proprio Python e
mostra la voce per il programma di IA. Dettagli:
[`verteilung/ANLEITUNG.it.md`](verteilung/ANLEITUNG.it.md).

```bash
python scripts/paket_bauen.py      # -> dist/Open-MCP-CAD-<version>.zip
```

**Come sviluppatore:**

```bash
git clone https://github.com/sebastiankoukoui/open-mcp-cad
cd open-mcp-cad
pip install -e .
pip install -e .[stubs]     # facoltativo: aiuto API (type stub cwapi3d)
```

Copiare la cartella `cad_plugin/Open MCP CAD/` nel profilo utente di
Cadwork:

```
C:\Users\Public\Documents\cadwork\userprofil_<ANNO>\3d\API.x64\Open MCP CAD\
```

> Solo nel profilo utente, **non** anche in `ProgramData`, altrimenti il
> plugin compare due volte in Cadwork.
>
> Solo **questa** cartella, non tutto `cad_plugin/`: da `Open MCP CAD A` a
> `F` sono cartelle di test (porte fisse, senza finestra). Nel menu di
> Cadwork sembrano il plugin, ma un clic non apre nessuna finestra.

Verificare che repository e profilo utente coincidano:

```bash
python scripts/deployment_pruefen.py
```

Configurazione dell'host (esempio Claude Desktop; su Windows `pythonw`
invece di `python`, altrimenti a ogni avvio compare per un attimo una
finestra della console):

```json
{
  "mcpServers": {
    "open-mcp-cad": { "command": "pythonw", "args": ["-m", "open_mcp_cad.server"] }
  }
}
```

Senza `env` il server prende la finestra Cadwork collegata (se ce n'è più
d'una, vedi sopra). Una voce fissa su una porta o un documento:
`"env": { "OPEN_MCP_CAD_PORT": "53128" }` oppure `"env": { "OPEN_MCP_CAD_DOC": "Seeblick" }`.

**Protezione dagli scambi:** impostare `OPEN_MCP_CAD_EXPECT_DOC` su una
parte del nome del file. Il server verifica allora prima di **ogni**
chiamata che sia davvero aperto il documento atteso, invece di eseguire
codice nell'istanza sbagliata.

## Test

Tutto senza installazione CAD, Cadwork non viene mai avviato:

```bash
python tests/test_offline.py       # stati, pausa, arresto, licenza di scrittura, protezione del documento
python tests/test_wissen.py        # caricatore della conoscenza di settore
python tests/test_a_prototyp.py    # dashboard e chat senza Qt
python tests/test_registry.py      # registro e porte (occupa porte reali 53127–53199)
python tests/test_bootstrap.py     # bootstrap dei file
python tests/test_paket.py         # pacchetto di distribuzione
python tests/test_erfahrungen.py   # esperienze: ripulite, limitate, solo locali
python scripts/plugins_generieren.py --pruefen
```

Con PyQt6 si aggiunge `tests/test_a_live.py`: costruisce davvero
l'interfaccia e la usa, con sostituti al posto di Cadwork.

## Stato e limiti

**Cosa funziona:** il ponte, un numero qualsiasi di finestre Cadwork
tramite una sola voce di menu, la dashboard con collegamenti, storico,
note di controllo e casella di posta, la chat nella stessa finestra,
il bootstrap dei file, tutti i test. Il pannello e i messaggi dell'installazione sono
per ora in tedesco.

**Una sola finestra per tutto:** Claude Code (abbonamento), Codex
(abbonamento ChatGPT, richiede la CLI Codex `npm i -g @openai/codex`) o
qualsiasi interfaccia compatibile con OpenAI: OpenAI, Anthropic, OpenRouter
con una chiave API (salvata nella Gestione credenziali di Windows, il
pannello mostra solo gli ultimi quattro caratteri), Ollama e LM Studio in
locale (il pannello li riconosce, li avvia e li installa via winget dopo
conferma), oppure un indirizzo proprio (anche per Ollama su un altro
computer). Il clic mostra una piccola barra in alto a
destra sopra l'area di disegno (stato, pulsante "Chat", "Trennen",
aggancio; senza collegamento una "×" che chiude la finestra); "Chat" apre la
stessa finestra, mai modale, verso il basso; agganciata sta in una colonna
propria a destra del disegno. Un selettore "Chat | Briefkasten" (casella di
posta) separa la chat del plugin dal lavoro con un programma di IA esterno
(lavoro in corso, ultimi lavori, note per l'IA); annulla, ripristina,
ridisegna e le note di controllo stanno in entrambi, le impostazioni sotto
"⋯". Mentre l'IA lavora, un piccolo riquadro sopra Cadwork mostra cosa sta
facendo ("KI zeichnet" con l'avanzamento, "KI denkt nach", "Wartet auf
deine Freigabe", "Cadwork rechnet"), con "Anhalten" (ferma). Icone a tratto
(Lucide, ISC, vedi `THIRD_PARTY_NOTICES.md`) invece di emoji. In alto a
sinistra la cartella di lavoro (quelle scelte di recente, "Ordner" con un
più per altre), sotto
il campo di testo una barra come nelle app di chat: "+" per file e foto
(anche incollare e trascinare; immagini a tutti i fornitori), la modalità,
modello e livello di ragionamento in una piccola scheda (i modelli sopra,
un cursore sotto) e, da metà in su, una barra che mostra quanto è pieno il
contesto. Nella cronologia le risposte hanno una propria
bolla, le chiamate agli strumenti stanno in una riga espandibile con nomi
leggibili, gli orari sono approssimativi e relativi. La chat inizia con il
primo messaggio; le chat di Claude Code si possono proseguire da un elenco.
Il pannello chiede i modelli al fornitore, le schede di approvazione sono le
stesse.

**Limiti:**

- **Modelli locali: con riserva.** `execute_cadwork_command` fa
  **generare** Python al modello. I modelli piccoli (7B/8B) di solito non
  ci riescono, né riescono a chiamare strumenti in modo affidabile. Il
  collegamento funzionerà, risultati utili richiedono un modello potente.
- **Solo Cadwork 3D.** L'architettura (coda, obbligo del thread
  principale, approvazioni) si potrebbe trasferire ad altri CAD con
  un'API Python. Non è stato fatto.
- I type stub provengono da Cadwork 2025. `get_cadwork_api_help` potrebbe
  non conoscere funzioni più recenti. Le chiamate reali passano per i
  moduli integrati del CAD e non ne sono toccate.

## Sicurezza

- Il ponte ascolta esclusivamente su `127.0.0.1` e non è raggiungibile
  dall'esterno.
- Il codice eseguito viene filtrato contro l'importazione di `os`,
  `subprocess`, `shutil`, `socket`, `urllib`, `requests` e `__import__`.
  È una lista di blocco fatta al meglio, **non una sandbox**: chi dà al
  modello accesso al proprio CAD gli dà accesso al proprio CAD.
- La chat ha quattro modalità: "Nur lesen" (solo lettura)
  rifiuta senza chiedere tutto ciò che modifica qualcosa, "Fragen" (chiedi,
  predefinita) mostra una scheda prima di ogni modifica (una volta per tipo
  fino al messaggio successivo), "Cadwork frei" (Cadwork libero) lascia
  lavorare Cadwork senza schede e chiede per tutto ciò che è all'esterno
  come "Fragen",
  "Alles automatisch" (tutto automatico) non chiede nulla e non sopravvive
  mai a un riavvio. In ogni modalità ogni chiamata compare nello storico:
  un'automazione che non lascia traccia sarebbe peggio di tutte le
  domande.
- Se l'approvazione non funziona, non viene eseguito nulla. Il blocco si
  chiude, non si apre.

## Licenza

[AGPL-3.0](LICENSE). Chi distribuisce open-mcp-cad modificato o lo
gestisce come servizio trasmette le modifiche con la stessa licenza.

I contributi richiedono un [CLA](CLA.md) (in tedesco).

**Nome e logo non fanno parte della licenza.** Fare un fork è
espressamente consentito, chiamare il fork "Open MCP CAD" no.

*Cadwork è un marchio di cadwork informatik AG. Open MCP CAD è un progetto
indipendente e non ha alcun legame con cadwork.*

Il [README](README.md) tedesco è la versione di riferimento.
