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
- **Un'app di IA con abbonamento:** Claude Desktop (con un abbonamento
  Claude, Pro o Max) o l'app ChatGPT di OpenAI (con un abbonamento
  ChatGPT, Plus o Pro). Un abbonamento è una quota mensile presso il
  fornitore. Funziona solo con l'app sul PC, non nel browser né sul
  telefono. Senza abbonamento funziona anche
  con una **chiave** – un codice di accesso preso dal sito del
  fornitore; allora paghi per ogni richiesta (vedi «Per utenti esperti»
  nella sezione 6).

## 2. Installare (un doppio clic)

La sezione 6 mostra questi passi in immagini.

1. Clic destro sul file ZIP → **Estrai tutto …** → **Estrai**.
2. **Chiudere Cadwork.**
3. Nella cartella estratta, fare doppio clic su **1_INSTALLIEREN.cmd**.
   Se Windows chiede se vuoi davvero eseguire il file: **Esegui** (oppure
   **Ulteriori informazioni** → **Esegui comunque**).
4. Si apre la finestra «Open MCP CAD einrichten» (configurare Open MCP
   CAD). Chiede dove vuoi lavorare con l'IA: nella tua app di IA,
   direttamente in Cadwork nella chat, o entrambi. Sotto **Deine KI-App**
   (la tua app di IA) è già spuntato ciò che ha trovato sul PC. Se non ne
   trova nessuna, ti mostra dove prenderne una.
5. Cliccare su **Weiter** (avanti) e poi su **Installieren**
   (installare). La finestra mostra ogni passo; ci vogliono alcuni
   minuti. Se al PC manca un componente, chiede prima se può installarlo
   anche. Funziona anche sui PC aziendali senza il gestore di pacchetti
   di Windows: allora lo scarica direttamente dal produttore e prima ne
   verifica la firma digitale. Prima crea una copia di sicurezza delle
   impostazioni della tua app di IA.
6. Quando appare **Fertig eingerichtet** (configurazione completata), c'è
   tutto. Se qualcosa non va, la finestra dice cosa manca e indica il
   registro `C:\Users\Public\OpenMcpCad_installer.log`.

> Suggerimento: se installi un'app di IA più tardi, fai di nuovo doppio
> clic su 1_INSTALLIEREN.cmd. Aggiunge solo ciò che manca e non cambia
> nulla di ciò che è già giusto.

Usi già un'app di IA sul PC? Copia questo testo e mandaglielo, ti aiuterà
a configurare. La finestra di configurazione resta la via consigliata;
nella sua prima pagina, **Text kopieren** (copiare il testo) copia lo
stesso testo in tedesco.

> Aiutami per favore a configurare Open MCP CAD. Collega Cadwork 3D 2026
> a un'IA. Guidami passo dopo passo, un solo passo alla volta, e aspetta
> che l'abbia fatto. 1) Scaricare l'ultimo file ZIP:
> https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest 2)
> Chiudere Cadwork ed estrarre il file ZIP (clic destro, «Estrai
> tutto»). 3) Nella cartella estratta fare doppio clic su
> 1_INSTALLIEREN.cmd e cliccare su «Installieren» nella finestra di
> configurazione. È la via consigliata. 4) Poi chiudere completamente
> l'app di IA e riavviarla. 5) In Cadwork cliccare su «Open MCP CAD»
> finché appare «Bereit». Se qualcosa non funziona, leggi il file
> Programmdateien\FUER_KI_ASSISTENTEN.md nella cartella estratta. Non
> costruire un tuo adattatore e non parlare tu stesso con la porta del
> plugin, è già tutto pronto.

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

Ci sono tre vie per parlare con l'IA. **Le vie B e C sono le più
semplici**, con un'app di IA adatta al tuo abbonamento. La via A è per
utenti esperti. La sezione 6 mostra le vie in immagini.

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

### Via B: app ChatGPT con un abbonamento ChatGPT

Scrivi nell'app ChatGPT di OpenAI sul PC, Cadwork disegna.

1. Installare l'app ChatGPT per il PC (nella finestra di configurazione,
   **ChatGPT-App holen** (prendere l'app ChatGPT) apre il Microsoft
   Store), avviarla e
   accedere con il tuo account ChatGPT.
2. Fare (di nuovo) doppio clic su **1_INSTALLIEREN.cmd**. Nella finestra
   **ChatGPT-App (mit Codex)** è spuntata: **Weiter** → **Installieren**.
3. Chiudere completamente l'app ChatGPT e riavviarla.
4. In Cadwork, cliccare su **Open MCP CAD** (la barra mostra
   **Bereit**).
5. Nell'app ChatGPT iniziare una nuova chat con Codex e scrivere la
   frase di prova. Se l'app chiede se può usare Open MCP CAD:
   consentirlo.

### Via C: Claude Desktop o Claude Code con un abbonamento Claude

Scrivi nell'app Claude (o nella finestra dei comandi), Cadwork disegna.

1. Installare **Claude Desktop** (nella finestra di configurazione:
   **Claude Desktop holen** (prendere Claude Desktop), oppure da
   claude.com/download), avviarlo e accedere.
2. Chiudere completamente Claude Desktop (anche in basso a destra vicino
   all'orologio: clic destro sull'icona di Claude → **Esci**) prima di
   avviare 1_INSTALLIEREN.cmd.
3. Fare (di nuovo) doppio clic su **1_INSTALLIEREN.cmd**. Nella finestra
   **Claude Desktop** è spuntato: **Weiter** → **Installieren**.
4. Riavviare Claude Desktop. In Cadwork, cliccare su **Open MCP CAD** (la
   barra mostra **Bereit**).
5. Scrivere la frase di prova in Claude. Se Claude chiede se può usare
   Open MCP CAD: consentirlo.

Funziona anche con **Claude Code** (via A, passo 1) nella finestra dei
comandi: la finestra di configurazione inserisce Open MCP CAD anche lì.
Digitare **claude** in una cartella di progetto e scrivere la frase di
prova.

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

## 6. Come configurarlo

Le sezioni da 2 a 4 in immagini, in quattro passi. I numeri in ogni
immagine corrispondono ai punti sotto.

### Passo 1: prendere un'app di IA

Ti serve **Claude Desktop** (con un abbonamento Claude) o l'**app ChatGPT** sul PC (con un abbonamento ChatGPT). Se non ne hai ancora nessuna, la
finestra di configurazione (passo 2) mostra questa pagina:

![Configurazione 1: la finestra di configurazione finché non c'è un'app di IA](bilder/einrichten-1-ki-app-holen.png)

1. Apre la pagina di Anthropic per Claude Desktop.
2. Apre l'app ChatGPT nel Microsoft Store.
3. Funziona solo con l'app sul PC, non nel browser né sul telefono.
4. Dopo l'installazione e l'accesso, cliccare qui. Poi si continua come
   nel passo 3.

### Passo 2: estrarre lo ZIP e fare doppio clic

![Configurazione 2: il file ZIP e la cartella estratta](bilder/einrichten-2-entpacken.png)

1. Clic destro sul file ZIP → **Estrai tutto …** → **Estrai**.
2. Chiudere Cadwork. Poi, nella cartella estratta, fare doppio clic su
   **1_INSTALLIEREN.cmd**. Si apre la finestra di configurazione.
3. Questa guida in PDF (in tedesco; questa guida in italiano è nella
   cartella Programmdateien).
4. Qui c'è tutto ciò che serve alla finestra di configurazione. Non devi
   aprire nulla qui dentro.

### Passo 3: «Installieren» nella finestra

![Configurazione 3a: «Wo möchtest du mit der KI arbeiten?» (dove vuoi lavorare con l'IA?)](bilder/einrichten-3a-wo.png)

1. Nella tua app di IA: Claude Desktop o l'app ChatGPT.
2. Direttamente in Cadwork nella chat, accanto al disegno (vedi «Chat
   direttamente in Cadwork» più sotto).
3. Entrambi. Se c'è già un'app di IA, è preselezionato.
4. **Weiter** (avanti).

![Configurazione 3: «Deine KI-App» (la tua app di IA) nella finestra di configurazione](bilder/einrichten-3-ki-app.png)

1. Trovata sul PC e spuntata: qui la finestra inserisce Open MCP CAD.
2. Lo stesso. Togli la spunta a un'app che non vuoi collegare.
3. Funziona solo con l'app sul PC, non nel browser né sul telefono.
4. **Weiter** (avanti).

![Configurazione 4: «Bereit zum Installieren» (pronto per l'installazione)](bilder/einrichten-4-installieren.png)

1. Ciò che la finestra configura. Se al PC manca un componente, la
   finestra chiede prima se può installarlo anche; allora compare anche
   qui.
2. Cliccare su **Installieren** (installare).

![Configurazione 5: la finestra sta configurando e mostra che cosa si sta scaricando](bilder/einrichten-5-laeuft.png)

1. L'avanzamento. Ci vogliono alcuni minuti.
2. Che cosa succede in questo momento, per esempio quale componente si
   sta scaricando. Il trattino sopra si muove finché si lavora.
3. Il passo in corso.
4. Mostra che cosa succede esattamente. È anche nel registro
   `C:\Users\Public\OpenMcpCad_installer.log`.

![Configurazione 6: «Fertig eingerichtet» (configurazione completata)](bilder/einrichten-6-fertig.png)

1. Con quale app Open MCP CAD è ora collegato.
2. I passi successivi, vedi il passo 4.
3. Apre questa guida.
4. Chiude la finestra.

### Passo 4: riavviare l'app di IA e cominciare

![Configurazione 7: Claude Desktop o l'app ChatGPT, Open MCP CAD e Cadwork](bilder/einrichten-7-apps.png)

1. La finestra di configurazione ha inserito Open MCP CAD nell'app. Se
   hai installato l'app solo dopo: fare di nuovo doppio clic su
   1_INSTALLIEREN.cmd.
2. Chiudere completamente l'app e riavviarla. Solo allora conosce Open
   MCP CAD.
3. In Cadwork, cliccare su **Open MCP CAD** finché la barra mostra
   **Bereit**.
4. Scrivere normalmente nella chat dell'app, per esempio la frase di
   prova della sezione 5. Se l'app chiede se può usare Open MCP CAD:
   consentirlo. Per verificare puoi chiedere: «Quale file è aperto in
   Cadwork?» Se l'IA nomina il tuo file, tutto è collegato. Altrimenti
   vedi la sezione 8.
5. Non funziona nel browser né sul telefono, solo con l'app sul PC.

### Chat direttamente in Cadwork

Se scegli «Direkt in Cadwork im Chat» (direttamente in Cadwork nella
chat) o «Beides» (entrambi), la finestra chiede l'IA della chat:

![Configurazione 8a: «Welche KI im Chat in Cadwork?» (quale IA nella chat di Cadwork?)](bilder/einrichten-8a-chat-ki.png)

1. Claude, con un abbonamento Claude. La finestra installa per questo
   Claude Code con il comando ufficiale di Anthropic.
2. ChatGPT, con un abbonamento ChatGPT. La finestra installa per questo
   Codex con il comando ufficiale di OpenAI. L'app ChatGPT da sola non
   basta per la chat in Cadwork.
3. Più tardi o con una tua chiave (vedi sotto).
4. **Weiter** (avanti).

Dopo l'installazione accedi una volta:

![Configurazione 8b: «Bei Claude anmelden» (accedere a Claude)](bilder/einrichten-8b-anmelden.png)

1. Ecco come: si aprono una piccola finestra nera e il tuo browser.
   Accedi con il tuo account nel browser.
2. Cliccare su **Anmelden** (accedere). Poi appare «Fertig
   eingerichtet». Va bene anche **Später** (più tardi); allora avvia di
   nuovo 1_INSTALLIEREN.cmd più tardi.

Poi in Cadwork cliccare su **Open MCP CAD**, sul fumetto nella barra, e
scrivere nella chat.

### Per utenti esperti

Se nella chat di Cadwork non è ancora configurata nessuna IA (per esempio
dopo «Später», più tardi), appare questa scheda (il fumetto nella barra
apre la chat):

![Configurazione 8: «Womit möchtest du chatten?» nella chat di Open MCP CAD](bilder/einrichten-8-chat.png)

1. Con un abbonamento Claude: **So geht's** (come si fa) mostra l'unico
   passo che manca ancora (gli stessi comandi della via A, passo 1).
2. Con un abbonamento ChatGPT: **So geht's** mostra i comandi per Codex.
3. Senza abbonamento: **Schlüssel eingeben** (inserire la chiave) apre le
   impostazioni al campo della chiave. Lì, sotto **Wer antwortet** (chi
   risponde), scegli anche un'IA locale sul tuo PC, per esempio Ollama:
   senza abbonamento, ma buoni risultati richiedono un modello potente e
   un PC potente.
4. Una volta configurato, **Nochmal prüfen** (verificare di nuovo). Appena
   una via è pronta, la scheda sparisce e puoi scrivere.

## 7. Come funziona

Ecco Open MCP CAD in Cadwork. I numeri in ogni immagine corrispondono ai
punti sotto.

### Avviare il plugin

![Passo 1: la barra in alto a destra in Cadwork](bilder/anleitung-1-leiste.png)

1. Nel menu dei plugin, cliccare su **Open MCP CAD**. In alto a destra,
   sopra il disegno, appare la barra.
2. **Bereit** (pronto) significa che Cadwork è collegato e l'IA può
   iniziare.
3. Il fumetto apre la chat sotto la barra.
4. Questo pulsante aggancia la finestra a destra, in una colonna propria.

### Chattare con l'IA

![Passo 2: la chat con la frase di prova e la risposta dell'IA](bilder/anleitung-2-chat.png)

1. Qui scrivi ciò che ti serve, per esempio la frase di prova della
   sezione 5.
2. Ogni passo in Cadwork compare nella cronologia. Con un clic vedi i
   dettagli.
3. La freccia annulla l'ultimo passo in Cadwork. Accanto: ripristina e
   ridisegna.
4. La modalità stabilisce quanto può fare l'IA da sola: **Nur lesen**
   (sola lettura), **Fragen** (chiedere prima di ogni modifica),
   **Cadwork frei** (libera in Cadwork) o **Alles automatisch** (tutto
   automatico).
5. Qui scegli il modello e il livello di ragionamento.

### Agganciato a destra

![Passo 3: agganciato a destra, nella casella di posta](bilder/anleitung-3-angedockt.png)

1. Passa dalla **Chat** al **Briefkasten** (casella di posta) e
   viceversa.
2. La casella di posta mostra cosa sta girando ora in Cadwork, con gli
   ultimi lavori sotto.
3. Qui lasci una nota per l'IA. Aspetta finché l'IA la ritira.
4. Sgancia la finestra, che torna mobile.

### Mentre l'IA disegna

![Passo 4: il riquadro KI zeichnet (l'IA disegna) sopra il disegno](bilder/anleitung-4-anzeige.png)

1. Un piccolo riquadro sopra il disegno mostra che l'IA sta lavorando.
2. Quanti elementi sono già pronti e quanto manca.
3. **Anhalten** (ferma) scarta i lavori in attesa. Il passo in corso
   viene ancora completato.

## 8. Se non funziona

- **Il clic su Open MCP CAD non fa nulla:** il motivo è nel file
  `C:\Users\Public\OpenMcpCad_start.log`.
- **L'IA non conosce Cadwork:** chiudere completamente il programma di IA
  e riavviarlo. Se non basta, fare di nuovo doppio clic su
  1_INSTALLIEREN.cmd, lasciare spuntata l'app e cliccare su
  **Installieren**. Per ChatGPT prendere l'app ChatGPT dal Microsoft
  Store; la vecchia «ChatGPT Classic» non conosce Open MCP CAD.
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
  o tramite [lignoai.ch](https://lignoai.ch). Allega i file
  `C:\Users\Public\OpenMcpCad_start.log` e
  `C:\Users\Public\OpenMcpCad_installer.log` (il registro della
  finestra di configurazione).

![Primo contatto nella chat del plugin, finché non è configurato nulla](bilder/willkommen.png)

Di più (tutte le impostazioni, disinstallazione): la guida dettagliata
nella cartella Programmdateien.
