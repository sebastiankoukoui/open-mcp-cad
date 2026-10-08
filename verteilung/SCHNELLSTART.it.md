# Open MCP CAD – Avvio rapido

Dal file ZIP al primo muro che un'IA disegna in Cadwork. Senza conoscenze
informatiche, in circa 20 minuti.

Open MCP CAD collega un programma di IA (per esempio ChatGPT o Claude) al
tuo Cadwork aperto. Scrivi con parole semplici quello che vuoi, e l'IA lo
disegna in Cadwork. Prima di ogni modifica ti chiede. (MCP è il nome del
ponte attraverso cui un programma di IA può comandare un altro programma.)

Il plugin e l'installatore parlano tedesco. Le loro parole sono scritte qui
in **grassetto**, con la traduzione tra parentesi dove serve.

## 1. Cosa ti serve

- Un PC Windows con **Cadwork 3D 2026**.
- Internet durante l'installazione.
- **Un abbonamento IA** che forse hai già: ChatGPT (Plus o Pro) o Claude
  (Pro o Max). Un abbonamento è una quota mensile presso il fornitore.
  Senza abbonamento funziona anche con una **chiave** – un codice di
  accesso preso dal sito del fornitore; allora paghi per ogni richiesta.

## 2. Installare (un doppio clic)

1. Clic destro sul file ZIP → **Estrai tutto …** → **Estrai**.
2. **Chiudere Cadwork.**
3. Nella cartella estratta, fare doppio clic su **1_INSTALLIEREN.cmd**.
   Se Windows chiede se vuoi davvero eseguire il file: **Esegui** (oppure
   **Ulteriori informazioni** → **Esegui comunque**).
4. Appare una finestra nera che lavora per qualche minuto. Rispondi alle
   domande con **Invio** – così vale la proposta. Se al PC manca un
   componente, chiede se può prenderlo. Funziona anche sui PC aziendali
   senza il gestore di pacchetti di Windows winget: allora lo scarica
   direttamente dal produttore e prima ne verifica la firma digitale.
5. Alla fine chiede per ogni programma di IA trovato, per esempio «Open MCP
   CAD in Codex eintragen? [J/n]» (inserire Open MCP CAD in Codex?).
   **Invio** lo inserisce. Prima crea una copia di sicurezza.
6. In fondo, sotto **Ergebnis** (risultato), ogni parte è elencata da
   sola. Se c'è scritto «NICHT vollstaendig installiert» (non installato
   completamente), i motivi sono subito sopra.

> Suggerimento: se configuri un programma di IA più tardi, fai di nuovo
> doppio clic su 1_INSTALLIEREN.cmd. Aggiunge solo ciò che manca e non
> cambia nulla di ciò che è già giusto.

## 3. Collegare Cadwork

1. Avviare Cadwork e aprire un file (basta un file nuovo e vuoto).
2. Nel menu dei plugin, cliccare su **Open MCP CAD**.
3. In alto a destra, sopra il disegno, appare la piccola **barra** di
   Open MCP CAD. Quando mostra **Bereit** (pronto), Cadwork è collegato.

![La barra in alto a destra in Cadwork: collegata e pronta](bilder/monitor.png)

I pulsanti della barra:

- **Fumetto**: apre la chat sotto la barra. Il trattino tutto a destra
  la richiude a barra.
- **Due frecce**: mette la finestra a destra del disegno, in una colonna
  propria. Cliccare di nuovo la stacca.
- **Trennen** (scollegare): scollega Cadwork dall'IA. Poi a destra appare
  una **×** che chiude la finestra. Un clic su **Open MCP CAD** nel menu
  dei plugin la riporta.

## 4. Scegliere una via

Ci sono tre vie per parlare con l'IA. **Prendi la via dell'abbonamento IA
che hai già.** Se non ne hai ancora uno: la via B con l'app Codex è la più
provata tra i colleghi.

### Via A: chat nel plugin con un abbonamento Claude

Scrivi direttamente in Cadwork, nella chat di Open MCP CAD.

1. Configurare Claude Code una volta: premere il tasto Windows, digitare
   **PowerShell**, Invio. Si apre una finestra per i comandi. Digitare (o
   copiare) questa riga e premere Invio:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   Ci vuole circa un minuto e non servono diritti di amministratore. Poi
   chiudere la finestra, aprirne una **nuova** (di nuovo **PowerShell**)
   e digitare:
   ```
   claude
   ```
   Al primo avvio si apre il browser: accedere con il tuo account Claude.
   Poi chiudere la finestra. Se Windows non conosce ancora «claude», usare
   invece questa riga:
   ```
   ~\.local\bin\claude.exe
   ```
   Solo se la prima riga non funziona (per esempio perché un computer
   aziendale la blocca): Claude Code si può configurare anche con
   Node.js, con `winget install OpenJS.NodeJS.LTS` e poi, in una nuova
   finestra, `npm install -g @anthropic-ai/claude-code`. Se winget manca,
   installare Node.js (versione «LTS») da [nodejs.org](https://nodejs.org).
2. In Cadwork, cliccare sul **fumetto** nella barra. La chat si apre
   sotto.
3. In alto a sinistra nella chat, cliccare su **Ordner
   wählen** (scegliere la cartella) e scegliere una cartella di progetto
   (non l'intero disco). Claude può leggere lì.
4. Scrivere la frase di prova in basso (vedi sezione 5) e premere Invio.

![La chat sotto la barra: scrivi in basso, l'IA risponde e disegna](bilder/chat.png)

### Via B: app Codex con un abbonamento ChatGPT

Scrivi nell'app Codex di OpenAI, Cadwork disegna.

1. Installare l'app **Codex** dal **Microsoft Store**, avviarla e
   accedere con il tuo account ChatGPT.
2. Fare (di nuovo) doppio clic su **1_INSTALLIEREN.cmd** e confermare
   «Open MCP CAD in Codex eintragen?» con **Invio**.
3. Chiudere completamente l'app Codex e riavviarla.
4. In Cadwork, cliccare su **Open MCP CAD** (la barra mostra
   **Bereit**).
5. Nell'app Codex iniziare una nuova chat e scrivere la frase di prova. Se
   Codex chiede se può usare Open MCP CAD: consentirlo.

### Via C: Claude Desktop o Claude Code con un abbonamento Claude

Scrivi nell'app Claude (o nella finestra dei comandi), Cadwork disegna.

1. Installare **Claude Desktop** da claude.ai/download, avviarlo e
   accedere.
2. Chiudere completamente Claude Desktop (anche in basso a destra vicino
   all'orologio: clic destro sull'icona di Claude → **Esci**) prima di
   avviare l'installatore.
3. Fare (di nuovo) doppio clic su **1_INSTALLIEREN.cmd** e confermare
   «Open MCP CAD in Claude Desktop eintragen?» con **Invio**.
4. Riavviare Claude Desktop. In Cadwork, cliccare su **Open MCP CAD** (la
   barra mostra **Bereit**).
5. Scrivere la frase di prova in Claude. Se Claude chiede se può usare
   Open MCP CAD: consentirlo.

Funziona anche con **Claude Code** (via A, passo 1) nella finestra dei
comandi: l'installatore inserisce Open MCP CAD anche lì. Digitare
**claude** in una cartella di progetto e scrivere la frase di prova.

## 5. La prima prova

Scrivi all'IA:

> Disegna un muro lungo 4 m e alto 2,5 m

L'IA guarda prima il modello Cadwork aperto. Prima di disegnare ti chiede
(nella chat del plugin con **Erlauben** / **Ablehnen**, consentire /
rifiutare). Mentre lavora, un piccolo riquadro sopra Cadwork mostra cosa
sta facendo, per esempio **KI zeichnet** (l'IA disegna). Dopo il tuo
consenso il muro è in Cadwork. Poi puoi
continuare, per esempio «Fallo spesso 20 cm» o «Metti una finestra al
centro».

## 6. Se non funziona

- **Il clic su Open MCP CAD non fa nulla:** il motivo è nel file
  `C:\Users\Public\OpenMcpCad_start.log`.
- **L'IA non conosce Cadwork:** chiudere completamente il programma di IA
  e riavviarlo. Se non basta, fare di nuovo doppio clic su
  1_INSTALLIEREN.cmd e confermare l'inserimento con Invio.
- **L'IA dice che Cadwork non è raggiungibile:** in Cadwork, cliccare su
  **Open MCP CAD** e aspettare che la barra mostri **Bereit**.
- **Nella chat del plugin c'è «Womit möchtest du chatten?»** (con cosa
  vuoi chattare?): scegliere la via adatta al tuo abbonamento; i pulsanti
  mostrano il passo successivo.
- **Se chiedi aiuto a un'IA** (per esempio «installa questo»): dalle il
  file `Programmdateien\FUER_KI_ASSISTENTEN.md`. Dice che cosa deve
  fare. Se vuole prima costruire qualcosa in più (per esempio un
  «adattatore»): non serve, è già tutto pronto.
- **Altrimenti:** scrivici su
  [github.com/sebastiankoukoui/open-mcp-cad/issues](https://github.com/sebastiankoukoui/open-mcp-cad/issues)
  o tramite [lignoai.ch](https://lignoai.ch). Allega il file
  `C:\Users\Public\OpenMcpCad_start.log` e uno screenshot dell'**Ergebnis**
  (risultato) dell'installatore.

![Primo contatto nella chat del plugin, finché non è configurato nulla](bilder/willkommen.png)

Di più (tutte le impostazioni, disinstallazione): la guida dettagliata
nella cartella Programmdateien.
