# Open MCP CAD — Installazione

[Deutsch](ANLEITUNG.md) · [English](ANLEITUNG.en.md) · [Français](ANLEITUNG.fr.md) · **Italiano**

Open MCP CAD collega un programma di IA (Claude, ChatGPT/Codex, …) a un
**Cadwork 3D in esecuzione**. L'IA può leggere il modello aperto e, dopo la
tua approvazione, disegnarci dentro. Due parti:

- il **plugin** in Cadwork (`Open MCP CAD` nel menu dei plugin)
- il **server MCP**, avviato dal programma di IA

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

## Requisiti

- Windows, **Cadwork 3D 2026**. Le versioni precedenti non funzionano: il
  plugin ha bisogno di Python 3.14 e PyQt6 forniti da Cadwork 2026, mentre
  Cadwork 2025 porta Python 3.12 e PyQt5. L'installazione lo verifica e non
  copia nel profilo di un'altra versione di Cadwork.
- **Python da 3.10 a 3.13** per il server (il Python integrato in Cadwork
  non viene usato per questo). Se manca, `1_INSTALLIEREN.cmd` propone di
  installare Python 3.13 (senza diritti di amministratore): tramite winget e,
  dove winget manca (per esempio Windows 10 LTSC o un PC aziendale bloccato),
  direttamente da python.org. Esegue quel file solo se la sua firma digitale
  è valida e proviene dalla Python Software Foundation, poi lo cancella.
  Un Python 3.14 da solo non basta, ma può restare installato accanto.
- Un programma di IA con supporto MCP: Claude Desktop, Claude Code o
  ChatGPT/Codex
- Connessione Internet durante l'installazione (il server scarica il
  pacchetto `mcp`)

## Installazione

1. Estrarre lo ZIP (clic destro → «Estrai tutto …») e **chiudere
   Cadwork**. In cima alla cartella estratta ci sono solo
   `1_INSTALLIEREN.cmd`, la guida in PDF e la cartella `Programmdateien`
   (tutto il resto, compresa questa guida).
2. Fare doppio clic su `1_INSTALLIEREN.cmd`. Lo script
   1. sceglie il profilo Cadwork
      (`C:\Users\Public\Documents\cadwork\userprofil_<ANNO>\3d\API.x64\`):
      propone `userprofil_2026`, altrimenti il profilo più recente per cui
      Cadwork è installato (`C:\Program Files\cadwork.dir\EXE_<ANNO>`). Se ce ne sono diversi,
      mostra l'elenco con i percorsi e chiede. Indica quale profilo usa e
      perché,
   2. verifica che il profilo appartenga a Cadwork 2026. Altrimenti mostra
      per esempio "Dieses Paket braucht Cadwork 3D 2026. Gefunden: Cadwork
      2025 im Profil userprofil_2025." (questo pacchetto richiede Cadwork
      3D 2026; trovato: Cadwork 2025) e chiede "Trotzdem in dieses Profil
      kopieren? [j/N]" (copiare comunque in questo profilo?). Senza una
      `j` esplicita (o l'opzione `-TrotzdemKopieren`) si ferma e non copia
      nulla; il plugin non partirebbe comunque in un'altra versione,
   3. copia la cartella `Open MCP CAD` in quel profilo,
   4. installa il server in un proprio Python
      (`%LOCALAPPDATA%\OpenMcpCad\python`), con i type stub `cwapi3d` per
      l'aiuto API dell'IA (se non riesce, senza — il risultato lo dice),
      e, se nessun Python è adatto, installa prima Python 3.13 dopo
      avertelo chiesto,
   5. imposta la variabile utente `OPEN_MCP_CAD_PYTHON` (per la chat nel
      plugin),
   6. cerca Codex (anche l'app Codex), Claude Code e Claude Desktop e
      chiede per ogni programma trovato «Open MCP CAD in … eintragen?
      [J/n]» (inserire Open MCP CAD in …?). Invio lo inserisce: prima fa
      una copia di sicurezza `<file>.vor-open-mcp-cad-<data-ora>.bak`
      accanto al file, le altre voci restano come sono, una voce propria
      già presente non viene mai modificata, e un secondo passaggio non
      cambia nulla. Per ogni programma dice cosa ha cambiato e come
      annullarlo (Claude Code tramite `claude mcp add --scope user`). I
      programmi non trovati vengono mostrati per l'inserimento a mano,
   7. mostra alla fine sotto
      **Ergebnis** (risultato), ogni parte su una riga propria: server MCP
      installato e testato, plugin Cadwork copiato e versione di Cadwork
      corretta, oppure cosa manca.

   Altro profilo: `1_INSTALLIEREN.cmd -Profil "D:\...\3d\API.x64"`.
   Se il risultato dice **NICHT vollstaendig installiert** (installazione
   incompleta), le righe sopra indicano la parte mancante. Risolvere e
   avviare di nuovo `1_INSTALLIEREN.cmd`.
3. Chiudere completamente il programma di IA e riavviarlo. Solo se
   l'installatore non l'ha trovato (o hai scelto «n»): inserire la voce a
   mano (vedi sotto). Se configuri un programma di IA più tardi, avvia
   semplicemente di nuovo `1_INSTALLIEREN.cmd`.

## Collegarsi in Cadwork

Aprire un file → menu dei plugin → cliccare su **Open MCP CAD**. La piccola barra di Open MCP CAD appare in alto a destra, sopra l'area di disegno, e si collega subito (stato **Bereit**,
pronto). Ogni finestra Cadwork ha il proprio collegamento, la porta la
sceglie il pannello da solo.

Se il clic non fa nulla o compare un messaggio di errore, il motivo è in
`C:\Users\Public\OpenMcpCad_start.log`. Se qualcosa non funziona dopo il
collegamento, il motivo è nel log `C:\Users\Public\OpenMcpCad_A.log`
(prima finestra, poi `_B`, `_C` ...).

I messaggi dell'installazione e il pannello sono per ora in tedesco.

## Voce nel programma di IA

`<PYTHON>` è il percorso che l'installazione mostra alla fine, di solito
`C:\Users\<NOME>\AppData\Local\OpenMcpCad\python\Scripts\pythonw.exe`
(con **w**: si avvia senza finestra nera della console).

**Claude Desktop** — `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "open-mcp-cad": {
      "command": "<PYTHON>",
      "args": ["-m", "open_mcp_cad.server"]
    }
  }
}
```

(Nel JSON scrivere le barre rovesciate due volte: `C:\\Users\\...`.)

**Claude Code**:

```
claude mcp add --scope user open-mcp-cad -- "<PYTHON>" -m open_mcp_cad.server
```

**ChatGPT / Codex** — `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.open-mcp-cad]
command = '<PYTHON>'
args = ['-m', 'open_mcp_cad.server']
```

Senza altre impostazioni il server prende la finestra Cadwork collegata,
nessuno deve conoscere la porta. Se sono collegate più finestre, oppure
quella precedente è stata chiusa o mostra un altro file, non tira a
indovinare: l'IA chiede quale file si intende e lo sceglie con
`wait_for_bridge` e il nome del file. Il server verifica quella finestra e
resta collegato a essa.

Perché una voce sia fissata su una porta o un file, impostarvi una
variabile d'ambiente: `OPEN_MCP_CAD_PORT` (ad es. `53128`; quale finestra
riceve questa porta dipende dall'ordine dei clic) oppure `OPEN_MCP_CAD_DOC`
(una parte del nome del file). Se nessun file aperto corrisponde, o più di
uno, il server non continua semplicemente in un'altra finestra: lo segnala.

## Sicurezza

- Prima di ogni operazione di scrittura l'IA può verificare con
  `get_document_info` quale file è aperto.
  `OPEN_MCP_CAD_EXPECT_DOC=<parte del nome del file>` nella voce lo
  blocca: il codice viene eseguito solo in un file corrispondente.
- Un'operazione in corso non viene mai interrotta bruscamente durante la
  disconnessione.
- L'IA lavora tramite l'interfaccia Python ufficiale di Cadwork (cwapi3d),
  fornita con Cadwork stesso.

## Chat nel plugin (facoltativa)

Nella chat si scrive con un'IA che lavora direttamente nel modello Cadwork
aperto. Il collegamento e gli strumenti per gli altri programmi di IA
funzionano anche senza la chat. Il pannello è in tedesco; le diciture qui
sotto sono citate così come appaiono, con una traduzione tra parentesi.

**La finestra:** Open MCP CAD ha una sola finestra in tre dimensioni. Il
clic la mostra come piccola barra in alto a destra sopra l'area di
disegno: lo stato (per esempio "Bereit" (pronto), "Zeichnet" (disegna),
"Denkt nach" (sta pensando), "Wartet auf dich" (ti aspetta),
"Cadwork rechnet" (Cadwork sta calcolando)), accanto il numero di note di
controllo aperte, poi "Chat" (fumetto), "Verbinden" (collega) o "Trennen"
(scollega) e "Rechts andocken" (aggancia a destra; due frecce verso
l'esterno). "Chat" apre la finestra verso il basso, larga come una chat e
fino a poco sopra il bordo inferiore; si ingrandisce trascinando il bordo
e si sposta trascinando la barra. "Verkleinern" (riduci; un trattino) la
richiude a barra. "Rechts andocken" la mette in una colonna propria a
destra del disegno, accanto alle finestre di Cadwork; lo stesso pulsante
(ora due frecce verso l'interno) la stacca di nuovo. Il collegamento
continua in ogni dimensione. Se nulla è collegato (dopo "Trennen" o mai),
a destra nella barra appare una "×" ("Schliessen", chiudi): chiude del
tutto la finestra, e un clic su **Open MCP CAD** nel menu dei plugin la
riporta e si collega.

**Nella finestra aperta** in alto c'è il file aperto, sotto il selettore
"Chat" | "Briefkasten" (casella di posta; anche Ctrl+1 e Ctrl+2). A
destra, uguale in entrambe le aree: "Rückgängig" (annulla) e
"Wiederherstellen" (ripristina) (l'annullamento proprio di Cadwork, un
clic = un lavoro), "Ansicht neu zeichnen" (ridisegna la vista),
"Hinweise" (note di controllo; una bandierina con il numero di note
aperte) e i tre puntini ⋯ con "Einstellungen" (impostazioni),
"Pausieren" (pausa), "Nach Auftrag trennen" (scollega dopo il lavoro),
"Anleitung öffnen" (apri la guida) e "Technik-Details" (dettagli
tecnici). La bandierina apre le note di controllo sopra l'area: toccare
una nota mostra i suoi elementi nel modello; nella chat
"In den Chat übernehmen" (riprendi nella chat) la mette nel campo di
testo (viene inviata solo con il tuo messaggio).

**Casella di posta ("Briefkasten"):** per lavorare con un programma di IA
fuori dal plugin (app Codex, Claude Desktop, Claude Code). In alto c'è
ciò che sta girando adesso, sotto "Letzte Aufträge" (ultimi lavori;
apribile, i lavori stanno solo qui) e "Notizen für die KI" (note per
l'IA): scrivere una riga, "Ablegen" (deponi); la nota aspetta finché l'IA
la ritira.

**Riquadro sopra Cadwork:** mentre l'IA lavora, un piccolo riquadro con il
logo appare in alto al centro sopra Cadwork: "KI zeichnet" (l'IA disegna;
con elementi, tempo restante e barra), "KI schaut ins Modell" (l'IA
guarda il modello), "KI denkt nach" (l'IA sta pensando),
"Wartet auf deine Freigabe" (aspetta il tuo consenso; con "Zum Chat",
alla chat), "Cadwork rechnet" (Open MCP CAD aspetta che Cadwork abbia
finito) e per poco "Fertig" (fatto). "Anhalten" (ferma) scarta i lavori
ancora in attesa (il passo in corso finisce, poi appare "Angehalten",
fermato); la × accanto nasconde il riquadro fino alla prossima serie. La
chat stessa si ferma con "Beenden" (termina).

**Primo contatto:** se non è ancora configurato nulla (niente Claude Code,
niente Codex, nessuna chiave salvata, nessun modello locale), la chat
mostra "Womit möchtest du chatten?" (con cosa vuoi chattare?)
con tre vie: abbonamento Claude, abbonamento ChatGPT (Codex) e chiave
propria. "So geht's" (come si fa) sceglie il fornitore e mostra il passo
che manca (i comandi si possono selezionare e copiare),
"Schlüssel eingeben" (inserire la chiave) apre le impostazioni della chat alla
chiave, "Nochmal prüfen" (controlla di nuovo) guarda di nuovo dopo la
configurazione. "Anleitung öffnen" (apri la guida) apre la guida che
l'installatore mette accanto al plugin (`ANLEITUNG.pdf`), altrimenti la
pagina sul web. Appena una via è configurata, la scheda sparisce.

**Impostazioni** (⋯ → "Einstellungen"; "Zurück" (indietro) riporta alla
chat o alla casella di posta): quattro schede, chat, collegamento, modo di
disegno e "Technik-Details". Nella scheda chat, sotto "Wer antwortet" (chi
risponde) si
sceglie:

- **Claude Code (Abo)**: l'agente di Anthropic su questo computer, con il
  proprio abbonamento Claude. Claude Code deve essere installato: con
  l'installatore di Anthropic, in PowerShell
  `irm https://claude.ai/install.ps1 | iex` (senza Node.js, senza diritti
  di amministratore; mette `claude.exe` in `%USERPROFILE%\.local\bin`),
  oppure con Node.js `npm i -g @anthropic-ai/claude-code`. La chat li
  trova entrambi. Richiede una cartella di lavoro (vedi sotto).
- **Codex (ChatGPT-Abo)**: richiede la CLI Codex `npm i -g @openai/codex`.
  Qui lavora solo con gli strumenti di Cadwork.
- **OpenAI, Anthropic o OpenRouter (Schlüssel, ohne Abo)**: una chat semplice
  solo con gli strumenti di Cadwork, senza accesso ai propri file. Ogni
  richiesta costa denaro presso il fornitore. Un link porta alla pagina
  del fornitore dove si crea la chiave. Incollarla, "Speichern" (salva).
  La chiave viene poi salvata nella Gestione credenziali di Windows; il
  pannello mostra solo "Schlüssel gespeichert" (chiave salvata) con gli
  ultimi quattro caratteri, più "ändern" (modifica) ed "entfernen"
  (rimuovi).
- **Ollama o LM Studio (lokal)**: modelli su questo computer, senza
  chiave. Il pannello mostra se il programma è pronto. "Starten" (avvia)
  lo avvia, "Installieren …" (installa) lo installa dopo una conferma in
  una finestra propria (winget; le condizioni del produttore si accettano
  lì personalmente). Poi si scaricano i modelli di IA nel programma (di
  solito diversi GB).
- **Eigene Adresse (OpenAI-kompatibel)** (indirizzo proprio): qualsiasi
  altro servizio con un'interfaccia compatibile con OpenAI. **Se Ollama o
  LM Studio gira su un altro computer**, scegliere questa voce e inserire
  l'indirizzo, per esempio `http://<COMPUTER>:11434/v1` per Ollama o
  `http://<COMPUTER>:1234/v1` per LM Studio (l'altro computer deve
  accettare richieste dalla rete). "Ollama (lokal)" e "LM Studio (lokal)"
  interrogano sempre questo computer; un indirizzo modificato lì in
  passato non vale più.

**Modalità:** quanto l'IA può fare senza chiedere si imposta in basso a
sinistra sotto il campo di testo. Un clic apre le quattro modalità verso
l'alto, ognuna con una frase che dice cosa significa. Un cambio vale dal
passo successivo, anche a metà chat.

- "Nur lesen" (solo lettura): l'IA legge il documento e consulta. Tutto
  ciò che modifica Cadwork o file, e tutto ciò che è all'esterno, viene
  rifiutato senza chiedere. Se ci si passa a metà chat, le schede aperte
  per tali passi vengono rifiutate subito. Se l'IA vuole modificare
  qualcosa, sopra il campo di testo appare un avviso con ciò che voleva e
  "Zu «Fragen» wechseln" (passa a chiedi). Il pulsante cambia solo la
  modalità; l'IA riprova solo quando le si scrive.
- "Fragen" (chiedi, predefinita): prima di ogni modifica sopra il campo di
  testo appare una scheda con "Erlauben" (consenti) e "Ablehnen"
  (rifiuta), una volta per tipo fino al tuo prossimo messaggio.
  "Für diese Sitzung nicht mehr fragen" (non chiedere più in questa
  sessione) consente quel tipo fino alla fine della chat.
- "Cadwork frei" (Cadwork libero): tutto in Cadwork gira senza chiedere;
  comandi sul computer, file e web chiedono come in "Fragen" (una volta
  per tipo fino al prossimo messaggio). Nessuna modalità lascia passare
  meno della precedente.
- "Alles automatisch" (tutto automatico): non si chiede nulla. Ogni passo
  si vede solo dopo nella cronologia. Questa modalità non sopravvive mai a
  un riavvio di Cadwork; dopo vale "Cadwork frei".

**Chattare:** non c'è un pulsante di avvio. La chat inizia con il primo
messaggio. In alto a destra "Neuer Chat" (nuova chat, icona matita; in una
finestra stretta solo l'icona) ricomincia da capo e il pulsante di stop
("Beenden", termina; un quadrato pieno come su un lettore, in una finestra
stretta solo il quadrato) termina la chat in corso. Senza collegamento il
testo resta nel campo: prima collegarsi, poi inviare. Se un messaggio non è
arrivato (per esempio perché la chat non è più in corso), resta anch'esso
nel campo. Se la chat non può partire, il motivo appare subito sopra il
campo di testo. Se qualcos'altro non va (nessun collegamento, strumenti
Cadwork mancanti), in alto appare una breve riga; i dettagli sono sotto ⋯ in
"Technik-Details" (dettagli tecnici). Nella barra sotto il campo di testo:

- "+" apre "Datei oder Foto hinzufügen" (aggiungi file o foto) e
  "Aus der Zwischenablage einfügen" (incolla dagli appunti). Si può anche
  incollare con Ctrl+V o trascinare file nel campo di testo. Gli allegati
  appaiono sopra il campo, un clic ne toglie uno. Le immagini (fino a 3,5
  MB) vanno a tutti i fornitori, i file di testo (fino a 200 kB) con il loro
  contenuto, gli altri file solo a Claude Code, che li legge da sé. Tutti
  gli allegati di un messaggio insieme arrivano fino a 20 MB. Se un modello
  non accetta immagini, la cronologia lo dice, e il messaggio successivo
  parte senza di esse.
- A destra modello e livello di ragionamento, per esempio
  Opus 5.5 · Hoch. Un clic apre una piccola scheda: in grande la
  "Denkstufe" (livello di ragionamento), in piccolo il modello; un clic su
  di esso mostra i modelli sopra. Sotto il cursore a sei livelli, da
  "Niedrig" (basso) a "Ultracode", la freccia rotonda ripristina il
  valore predefinito. Codex e i fornitori con chiave hanno solo il
  modello; senza scelta appare "Automatisch" (automatico). Durante una
  chat appare "Gilt ab dem nächsten Chat" (vale dalla prossima chat).
- Quando la memoria della chat è piena almeno a metà, accanto appare una
  piccola barra con il numero, per esempio 65 %. Quando si riempie, meglio
  iniziare una nuova chat.

**Cronologia:** i propri messaggi stanno a destra, le risposte con il logo
a sinistra. Quello che l'IA fa nel frattempo sta in una riga grigia, p. es. 3
Schritte in Cadwork (3 passi in Cadwork). Un clic mostra i singoli passi, il
nome tecnico appare al passaggio del mouse. Se si è scorso verso l'alto, la
posizione resta e "Neu" (nuovo, freccia in giù) porta al più recente. Gli orari sono
approssimativi (gerade eben, vor 5 min, heute 09:12: proprio ora, 5 min fa,
oggi 09:12). Mentre l'IA lavora, un "…" sta dove apparirà la prossima
risposta (al passaggio del mouse: cosa sta facendo). Quanto è costato un
turno (token e, per i fornitori con chiave, l'importo) appare al passaggio
del mouse sulla risposta.

**Cartella di lavoro (solo Claude Code):** Claude Code lavora solo in una
cartella. Il pulsante con l'icona della cartella in alto a sinistra nella
chat la mostra. Un clic mostra le cartelle scelte di recente e
"Arbeitsordner wählen …" (scegli cartella di lavoro); "Wahl entfernen"
(rimuovi scelta) la annulla. In ogni modalità Claude Code vi legge i file
senza chiedere. Scegliere quindi una cartella di progetto, non un intero
disco né la propria cartella utente. "Ordner" accanto (cartella con più) dà a Claude
Code fino a tre cartelle in più dalla chat successiva, con gli stessi
diritti; un clic su una di esse la toglie. Una cartella in più con uno
dei caratteri & % ^ ! nel nome non viene accettata, perché non arriverebbe
in modo sicuro a Claude Code. Senza scelta vale un file
`projektordner.txt` nella cartella del plugin con il percorso di una
cartella. La variabile d'ambiente `OPEN_MCP_CAD_PROJEKT` ha la precedenza su
entrambi; la chat indica allora che la propria scelta al
momento non vale.

**Chat precedenti (solo Claude Code):** finché nessuna chat è in corso, la
chat elenca le chat iniziate qui in
questa cartella di lavoro, la più recente in alto. Un clic ne apre una, il
messaggio successivo la prosegue. Le chat del terminale o di versioni
precedenti del plugin non compaiono. Se una chat indica
"läuft gerade in einem anderen Cadwork" (in corso in un altro Cadwork),
continuare lì o premere qui "Neuer Chat".

## Disinstallazione

- Eliminare la cartella `Open MCP CAD` nel profilo Cadwork
- Eliminare la cartella `%LOCALAPPDATA%\OpenMcpCad` (Python del server,
  cartella di lavoro di Codex e le esperienze `erfahrungen.jsonl`)
- Eliminare la cartella `%APPDATA%\OpenMcpCad` (impostazioni della chat
  `chat.json`: fornitore, modelli, cartella di lavoro, gli ultimi quattro
  caratteri delle chiavi)
- Rimuovere le chiavi API salvate: più semplice prima, sotto ⋯ → "Einstellungen" con "entfernen" (rimuovi) per ogni fornitore. Altrimenti nel Pannello
  di controllo in Gestione credenziali → Credenziali di Windows →
  Credenziali generiche, ogni voce che inizia con `Open MCP CAD/`:
  `Open MCP CAD/openai`, `Open MCP CAD/anthropic`,
  `Open MCP CAD/openrouter`, `Open MCP CAD/eigen`
- Rimuovere la variabile utente `OPEN_MCP_CAD_PYTHON`
- Rimuovere la voce nel programma di IA: l'installatore ha mostrato il
  modo durante l'inserimento (eliminare la sezione o la voce
  `open-mcp-cad`, oppure ricopiare la copia di sicurezza con `copy /Y`
  nel prompt dei comandi; Claude Code:
  `claude mcp remove open-mcp-cad -s user`)

Per non lasciare nulla, eliminare anche i log
`C:\Users\Public\OpenMcpCad_*.log`, le cartelle
`C:\Users\Public\open-mcp-cad` e `C:\Users\Public\OpenMcpCad_Notizen`, i
file `*.omcad.json` accanto ai file Cadwork (note di verifica e casella
postale) e, nella cartella temporanea (`%TEMP%`), tutto ciò che inizia con
`open_mcp_cad`. Python 3.13, Ollama e LM Studio, se sono stati installati
per questo, si rimuovono nelle impostazioni di Windows sotto App. Le chat
di Claude Code appartengono a Claude Code
(`%USERPROFILE%\.claude\projects`) e restano.

## Licenza

GNU AGPL-3.0, vedi `LICENSE`. Non è un prodotto di cadwork informatik AG.
