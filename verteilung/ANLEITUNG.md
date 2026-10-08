# Open MCP CAD — Installation

**Deutsch** · [English](ANLEITUNG.en.md) · [Français](ANLEITUNG.fr.md) · [Italiano](ANLEITUNG.it.md)

Open MCP CAD verbindet ein KI-Programm (Claude, ChatGPT/Codex, …) mit einem
**laufenden Cadwork 3D**. Die KI kann das offene Modell lesen und — nach
Freigabe — darin zeichnen. Zwei Teile:

- **Plugin** in Cadwork (`Open MCP CAD` im Plugin-Menü)
- **MCP-Server**, den das KI-Programm startet

<!-- ki-assistenten:anfang -->
## Für KI-Assistenten (For AI assistants)

Du bist eine KI und sollst Open MCP CAD einrichten? Dann gilt:

- **Der MCP-Server existiert schon.** Er heisst `open-mcp-cad` und startet
  mit `python -m open_mcp_cad.server`. **Baue keinen Adapter, keine Brücke
  und keinen eigenen Server.**
- **Sprich nie selbst mit dem Plugin.** Das Plugin in Cadwork lauscht auf
  `127.0.0.1`, Ports 53127–53199, mit einem internen Protokoll
  (JSON-Zeilen), das nur für diesen Server da ist. Kein KI-Programm
  verbindet sich dort direkt.

Deine Aufgabe ist nur:

1. **Den Installer laufen lassen, falls noch nicht geschehen.** Der Nutzer
   doppelklickt `1_INSTALLIEREN.cmd` oben im entpackten ZIP (neueste
   Fassung: https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest).
   Er kopiert das Plugin nach Cadwork, richtet den Server in
   `%LOCALAPPDATA%\OpenMcpCad\python` ein und bietet am Schluss selbst an,
   Schritt 2 zu erledigen. Installiert ist der Server, wenn
   `"%LOCALAPPDATA%\OpenMcpCad\python\Scripts\python.exe" -c "import open_mcp_cad.server"`
   ohne Fehler endet.
2. **Den Server im KI-Programm eintragen**, falls der Installer es nicht
   getan hat. `<PYTHON>` ist der volle Pfad von
   `%LOCALAPPDATA%\OpenMcpCad\python\Scripts\pythonw.exe` (mit **w**: ohne
   Konsolenfenster). Vorher eine Sicherungskopie der Datei anlegen, nur den
   Eintrag `open-mcp-cad` hinzufügen, alle anderen Einträge unverändert
   lassen.
   - **Codex** (CLI und Codex-App): `%USERPROFILE%\.codex\config.toml`
     (bzw. `%CODEX_HOME%\config.toml`)
     ```toml
     [mcp_servers.open-mcp-cad]
     command = '<PYTHON>'
     args = ["-m", "open_mcp_cad.server"]
     ```
   - **Claude Desktop**: `%APPDATA%\Claude\claude_desktop_config.json`
     (Store-Fassung: unter
     `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`), im
     JSON Backslashes doppelt
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
3. **Dem Nutzer sagen:** das KI-Programm ganz beenden und neu starten,
   dann in Cadwork im Plugin-Menü auf **Open MCP CAD** klicken, bis die
   kleine Leiste oben rechts **Bereit** zeigt. Danach stehen die Werkzeuge von Open MCP CAD
   (etwa `get_document_info`) im KI-Programm bereit.

ChatGPT (die normale Chat-App) kann keine lokalen MCP-Server benutzen. Mit
demselben ChatGPT-Konto geht es in der Codex-App.
<!-- ki-assistenten:ende -->

## Voraussetzungen

- Windows, **Cadwork 3D 2026**. Ältere Versionen gehen nicht: das Plugin
  braucht Python 3.14 und PyQt6 aus Cadwork 2026, Cadwork 2025 bringt
  Python 3.12 und PyQt5 mit. Der Installer prüft das und kopiert nicht in
  das Profil einer anderen Cadwork-Version.
- **Python 3.10 bis 3.13** für den Server (Cadworks eigenes Python wird
  dafür nicht benutzt). Fehlt es, bietet `1_INSTALLIEREN.cmd` an, Python 3.13
  zu installieren (ohne Adminrechte): per winget, und wo winget fehlt (etwa
  Windows 10 LTSC oder ein gesperrter Firmen-PC) direkt von python.org. Diese
  Datei führt er nur aus, wenn ihre digitale Signatur gültig ist und von der
  Python Software Foundation stammt; danach löscht er sie. Ein Python 3.14
  allein reicht nicht, es darf aber daneben bleiben.
- Ein KI-Programm mit MCP: Claude Desktop, Claude Code oder ChatGPT/Codex
- Internet während der Installation (der Server lädt das Paket `mcp`)

## Installation

1. ZIP entpacken (Rechtsklick → «Alle extrahieren …»), **Cadwork
   schliessen**. Oben im entpackten Ordner liegen nur
   `1_INSTALLIEREN.cmd`, die Anleitung als PDF und der Ordner
   `Programmdateien` (darin alles andere, auch diese Anleitung).
2. `1_INSTALLIEREN.cmd` doppelklicken. Das Skript
   1. wählt das Cadwork-Profil
      (`C:\Users\Public\Documents\cadwork\userprofil_<JAHR>\3d\API.x64\`):
      vorgeschlagen wird `userprofil_2026`, sonst das neueste Profil, zu
      dem ein Cadwork installiert ist
      (`C:\Program Files\cadwork.dir\EXE_<JAHR>`). Gibt es mehrere,
      zeigt es die Liste mit Pfad und fragt nach. Es schreibt, welches
      Profil es nimmt und warum,
   2. prüft, ob das Profil zu Cadwork 2026 gehört. Wenn nicht, meldet es
      zum Beispiel «Dieses Paket braucht Cadwork 3D 2026. Gefunden:
      Cadwork 2025 im Profil userprofil_2025.» und fragt «Trotzdem in
      dieses Profil kopieren? [j/N]». Ohne ausdrückliches `j` (oder den
      Schalter `-TrotzdemKopieren`) bricht es ab und kopiert nichts — das
      Plugin startet in einer anderen Version ohnehin nicht,
   3. kopiert den Ordner `Open MCP CAD` in dieses Profil,
   4. richtet den Server in einem eigenen Python ein
      (`%LOCALAPPDATA%\OpenMcpCad\python`), mit den Type-Stubs `cwapi3d`
      für die API-Hilfe der KI (geht das nicht, ohne — das steht dann im
      Ergebnis), und installiert vorher nach Rückfrage Python 3.13, falls
      keines passt,
   5. setzt die Benutzervariable `OPEN_MCP_CAD_PYTHON` (für den Chat im
      Plugin),
   6. sucht Codex (auch die Codex-App), Claude Code und Claude Desktop
      und fragt je gefundenem Programm «Open MCP CAD in … eintragen?
      [J/n]». Mit Enter trägt es Open MCP CAD dort ein: vorher legt es
      neben der Datei eine Sicherungskopie
      `<Datei>.vor-open-mcp-cad-<Datum-Zeit>.bak` an, andere Einträge
      bleiben, wie sie sind, ein vorhandener eigener Eintrag wird nie
      geändert, und ein zweiter Lauf ändert nichts. Es sagt je Programm,
      was es geändert hat und wie man es zurücknimmt (Claude Code über
      `claude mcp add --scope user`). Nicht gefundene Programme zeigt es
      zum Eintragen von Hand,
   7. zeigt zum Schluss unter
      **Ergebnis** jeden Teil einzeln: «MCP-Server: installiert und
      getestet», «Cadwork-Plugin: kopiert nach …, Cadwork-Version passt»,
      oder was fehlt.

   Anderes Profil: `1_INSTALLIEREN.cmd -Profil "D:\...\3d\API.x64"`.
   Steht im Ergebnis **NICHT vollstaendig installiert**, nennen die Zeilen
   darüber den fehlenden Teil — beheben und `1_INSTALLIEREN.cmd` erneut starten.
3. Das KI-Programm ganz schliessen und neu starten. Nur wenn der Installer
   es nicht gefunden hat (oder du «n» gewählt hast): den Eintrag von Hand
   eintragen (siehe unten). Wird ein KI-Programm erst später eingerichtet,
   `1_INSTALLIEREN.cmd` einfach nochmals starten.

## In Cadwork verbinden

Datei öffnen → Plugin-Menü → **Open MCP CAD** klicken. Oben rechts über der Zeichenfläche erscheint die kleine Leiste von Open MCP CAD und verbindet sofort (Zustand **Bereit**). Jedes Cadwork-Fenster
bekommt seine eigene Verbindung, den Port sucht das Dock selbst aus.

Tut der Klick nichts oder erscheint eine Fehlermeldung, steht der Grund in
`C:\Users\Public\OpenMcpCad_start.log`. Klappt nach dem Verbinden etwas
nicht, steht der Grund im Protokoll `C:\Users\Public\OpenMcpCad_A.log`
(erstes Fenster, dann `_B`, `_C` …).

## Eintrag im KI-Programm

`<PYTHON>` ist der Pfad, den der Installer am Schluss ausgibt, normalerweise
`C:\Users\<NAME>\AppData\Local\OpenMcpCad\python\Scripts\pythonw.exe`
(mit **w**: startet ohne schwarzes Konsolenfenster).

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

(Backslashes im JSON doppelt schreiben: `C:\\Users\\...`.)

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

Ohne weitere Angabe nimmt der Server das verbundene Cadwork-Fenster, den
Port muss niemand kennen. Sind mehrere Fenster verbunden, oder wurde das
bisherige geschlossen bzw. zeigt es eine andere Datei, rät er nicht: die KI
fragt nach, welche Datei gemeint ist, und wählt sie mit `wait_for_bridge`
und dem Dateinamen. Der Server prüft das Fenster und bleibt daran.

Soll ein Eintrag fest auf einen Port oder eine Datei zeigen, dort eine
Umgebungsvariable setzen: `OPEN_MCP_CAD_PORT` (z. B. `53128`; welches
Fenster diesen Port bekommt, entscheidet die Reihenfolge der Klicks) oder
`OPEN_MCP_CAD_DOC` (ein Teil des Dateinamens). Passt keine oder mehr als
eine offene Datei, arbeitet der Server nicht einfach in einem anderen
Fenster weiter, sondern meldet es.

## Sicherheit

- Vor jedem Schreibauftrag kann die KI mit `get_document_info` prüfen,
  welche Datei offen ist. `OPEN_MCP_CAD_EXPECT_DOC=<Teil des Dateinamens>`
  im Eintrag verriegelt das: Code läuft dann nur in einer passenden Datei.
- Ein laufender Auftrag wird beim Trennen nie hart abgebrochen.
- Die KI arbeitet über die offizielle Cadwork-Python-Schnittstelle
  (cwapi3d), die Cadwork selbst mitbringt.

## Chat im Plugin (optional)

Im Chat schreibst du mit einer KI, die direkt im offenen Cadwork-Modell
arbeitet. Verbinden und die Werkzeuge für die anderen KI-Programme
funktionieren auch ohne Chat.

**Das Fenster:** Open MCP CAD hat ein einziges Fenster in drei Grössen.
Der Klick zeigt es als kleine Leiste oben rechts über der Zeichenfläche:
der Zustand (etwa „Bereit“, „Zeichnet“, „Denkt nach“, „Wartet auf dich“,
„Cadwork rechnet“), daneben die Zahl offener Prüfhinweise, dann „Chat“
(Sprechblase), „Verbinden“ bzw. „Trennen“ und „Rechts andocken“ (zwei
Pfeile nach aussen). „Chat“ öffnet das Fenster nach unten, so breit wie ein
Chat und bis kurz vor den unteren Rand; am Rand lässt es sich grösser
ziehen, an der Leiste verschieben. „Verkleinern“ (Strich) macht es wieder
zur Leiste. „Rechts andocken“ stellt es als eigene Spalte rechts neben die
Zeichnung, neben Cadworks eigene Fenster; derselbe Knopf (jetzt zwei Pfeile
nach innen) löst es wieder. Die Verbindung läuft in jeder Grösse weiter.
Ist nichts verbunden (nach „Trennen“ oder noch nie), steht rechts in der
Leiste ein „×“ („Schliessen“): es schliesst das Fenster ganz, ein Klick auf
**Open MCP CAD** im Plugin-Menü bringt es zurück und verbindet.

**Im offenen Fenster** steht oben die offene Datei, darunter der Schalter
„Chat“ | „Briefkasten“ (auch Strg+1 und Strg+2). Rechts daneben, in beiden
Bereichen gleich: „Rückgängig“ und „Wiederherstellen“ (Cadworks eigenes
Rückgängig, ein Klick = ein Auftrag), „Ansicht neu zeichnen“, „Hinweise“
(Flagge mit der Zahl offener Prüfhinweise) und die drei Punkte ⋯ mit
„Einstellungen“, „Pausieren“, „Nach Auftrag trennen“, „Anleitung öffnen“
und „Technik-Details“. Die Flagge klappt die Prüfhinweise über dem Bereich
auf: einen Hinweis antippen zeigt seine Bauteile im Modell; im Chat
übernimmt „In den Chat übernehmen“ ihn in die Eingabe (gesendet wird erst
mit deiner Nachricht).

**Briefkasten:** für die Arbeit mit einem KI-Programm ausserhalb des
Plugins (Codex-App, Claude Desktop, Claude Code). Oben steht, was gerade
läuft, darunter „Letzte Aufträge“ (aufklappbar, die Aufträge stehen nur
hier) und „Notizen für die KI“: eine Zeile schreiben, „Ablegen“; die Notiz
wartet, bis die KI sie abholt.

**Anzeige über Cadwork:** Solange die KI arbeitet, steht oben in der Mitte
über Cadwork eine kleine Anzeige mit dem Logo: „KI zeichnet“ (mit
Bauteilen, Restzeit und Balken), „KI schaut ins Modell“, „KI denkt nach“,
„Wartet auf deine Freigabe“ (mit „Zum Chat“), „Cadwork rechnet“ (Open MCP
CAD wartet, bis Cadwork selbst fertig ist) und kurz „Fertig“. „Anhalten“
verwirft Aufträge, die noch warten (der laufende Schritt wird fertig,
danach steht „Angehalten“), das × daneben blendet die Anzeige bis zum
nächsten Lauf aus. Den Chat selbst hält „Beenden“ an.

**Erster Kontakt:** Ist noch nichts eingerichtet (kein Claude Code, kein
Codex, kein gespeicherter Schlüssel, kein lokales Modell), steht im
Chat „Womit möchtest du chatten?“ mit drei Wegen: Claude-Abo,
ChatGPT-Abo (Codex) und eigener Schlüssel. „So geht's“ wählt den Anbieter
und zeigt den einen Schritt, der fehlt (die Befehle lassen sich markieren
und kopieren), „Schlüssel eingeben“ öffnet die Chat-Einstellungen beim
Schlüssel, „Nochmal prüfen“ sieht nach dem Einrichten neu nach.
„Anleitung öffnen“ öffnet die Anleitung, die der Installer neben das Plugin
legt (`ANLEITUNG.pdf`), sonst die Seite im Netz. Sobald ein Weg
eingerichtet ist, verschwindet die Karte.

**Einstellungen** (⋯ → „Einstellungen“; „Zurück“ führt zurück zum Chat
bzw. Briefkasten): vier Karten, Chat, Verbindung, Zeichenmodus und
„Technik-Details“. In der Karte Chat wählst du unter „Wer antwortet“:

- **Claude Code (Abo)**: der Agent von Anthropic auf diesem Rechner, mit
  deinem Claude-Abo. Claude Code muss installiert sein: mit dem
  Installer von Anthropic, in PowerShell `irm https://claude.ai/install.ps1 | iex`
  (ohne Node.js, ohne Adminrechte; legt `claude.exe` nach
  `%USERPROFILE%\.local\bin`), oder mit Node.js
  `npm i -g @anthropic-ai/claude-code`. Der Chat findet beide. Er braucht
  einen Arbeitsordner (siehe unten).
- **Codex (ChatGPT-Abo)**: braucht die Codex-CLI `npm i -g @openai/codex`.
  Arbeitet hier nur mit den Cadwork-Werkzeugen.
- **OpenAI, Anthropic oder OpenRouter (Schlüssel, ohne Abo)**: ein einfacher Chat
  nur mit den Cadwork-Werkzeugen, ohne Zugriff auf deine Dateien. Jede
  Anfrage kostet beim Anbieter Geld. Ein Link führt zur Seite des
  Anbieters, wo du den Schlüssel erstellst. Einfügen, „Speichern“. Der
  Schlüssel liegt dann in der Windows-Anmeldeinformationsverwaltung; das
  Dock zeigt nur noch „Schlüssel gespeichert“ mit den letzten vier Zeichen,
  dazu „ändern“ und „entfernen“.
- **Ollama oder LM Studio (lokal)**: Modelle auf diesem Rechner, ohne
  Schlüssel. Das Dock zeigt, ob das Programm bereit ist. „Starten“ startet
  es, „Installieren …“ installiert es nach einer Rückfrage in einem eigenen
  Fenster (winget; den Bedingungen des Herstellers stimmst du dort selbst
  zu). Die KI-Modelle lädst du danach im Programm herunter (meist mehrere
  GB).
- **Eigene Adresse (OpenAI-kompatibel)**: jeder andere Dienst mit
  OpenAI-kompatibler Schnittstelle. **Läuft Ollama oder LM Studio auf
  einem anderen Rechner**, wähle diesen Eintrag und trage die Adresse ein,
  zum Beispiel `http://<RECHNER>:11434/v1` für Ollama oder
  `http://<RECHNER>:1234/v1` für LM Studio (der andere Rechner muss
  Anfragen aus dem Netz annehmen). „Ollama (lokal)“ und
  „LM Studio (lokal)“ fragen immer diesen Rechner, eine früher dort
  geänderte Adresse gilt nicht mehr.

**Modus:** Wie viel die KI ohne Frage darf, stellst du unten links unter der
Eingabe ein. Ein Klick klappt die vier Modi nach oben auf, jeder mit einem
Satz, was er bedeutet. Ein Wechsel gilt ab dem nächsten Schritt, auch mitten
im Chat.

- „Nur lesen“: die KI liest das Dokument und schlägt nach. Alles, was
  Cadwork oder Dateien ändert, und alles ausserhalb wird abgelehnt, ohne zu
  fragen. Wechselst du mitten im Chat hierher, werden offene Karten für
  solche Schritte gleich abgelehnt. Will die KI etwas ändern, steht über
  der Eingabe ein Hinweis, was sie wollte, mit „Zu «Fragen» wechseln“. Der
  Knopf wechselt nur den Modus; die KI versucht es erst wieder, wenn du ihr
  schreibst.
- „Fragen“ (Vorgabe): vor jeder Änderung steht über der Eingabe eine Karte
  mit „Erlauben“ und „Ablehnen“, einmal je Art bis zu deiner nächsten
  Nachricht. „Für diese Sitzung nicht mehr fragen“ erlaubt diese Art, bis
  der Chat endet.
- „Cadwork frei“: in Cadwork läuft alles ohne Rückfrage; Befehle am
  Rechner, Dateien und Web fragen wie bei „Fragen“ (einmal je Art bis zu
  deiner nächsten Nachricht). Kein Modus lässt weniger durch als der
  davor.
- „Alles automatisch“: nichts wird gefragt. Du siehst jeden Schritt erst
  danach im Verlauf. Dieser Modus gilt nie über einen Neustart von Cadwork
  hinaus, danach steht „Cadwork frei“.

**Chatten:** Es gibt kein Starten. Der Chat beginnt mit deiner ersten
Nachricht. Oben rechts fängt „Neuer Chat“ (Stift-Symbol; im schmalen
Fenster nur das Symbol) von vorn an, „Beenden“ (gefülltes Quadrat wie
bei einem Abspielgerät, im schmalen Fenster nur das Quadrat) beendet den
laufenden Chat. Ohne Verbindung bleibt dein Text stehen: zuerst
verbinden, dann senden. Kam eine Nachricht nicht an (etwa weil der Chat
nicht mehr läuft), bleibt sie ebenfalls im Feld. Kann der Chat nicht
starten, steht der Grund direkt über der Eingabe. Stimmt sonst etwas nicht
(keine Verbindung, Cadwork-Werkzeuge fehlen), steht oben eine kurze Zeile;
die Einzelheiten stehen unter ⋯ bei „Technik-Details“. In der Leiste unter
der Eingabe:

- „+“ klappt „Datei oder Foto hinzufügen“ und
  „Aus der Zwischenablage einfügen“ auf. Du kannst auch mit Strg+V einfügen
  oder Dateien in die Eingabe ziehen. Die Anhänge stehen über der Eingabe,
  ein Klick nimmt einen heraus. Bilder (bis 3,5 MB) gehen an alle Anbieter,
  Textdateien (bis 200 kB) mit ihrem Inhalt, andere Dateien nur an Claude
  Code, das sie selbst liest. Alle Anhänge einer Nachricht zusammen gehen
  bis 20 MB. Nimmt ein Modell keine Bilder, steht das im Verlauf, und die
  nächste Nachricht geht ohne sie.
- Rechts Modell und Denkstufe, zum Beispiel Opus 5.5 · Hoch. Ein Klick
  öffnet eine kleine Karte: gross die „Denkstufe“, klein das Modell; ein
  Klick darauf zeigt die Modelle darüber. Darunter der Regler mit sechs
  Stufen von „Niedrig“ bis „Ultracode“, der runde Pfeil stellt die Vorgabe
  wieder her. Codex und die Anbieter mit Schlüssel haben nur das Modell;
  ohne Wahl steht „Automatisch“. Während eines Chats steht dort
  „Gilt ab dem nächsten Chat“.
- Ist das Gedächtnis des Chats mindestens halb voll, steht daneben ein
  kleiner Balken mit der Zahl, zum Beispiel 65 %. Wird es voll, lieber
  einen neuen Chat beginnen.

**Verlauf:** Deine Nachrichten stehen rechts, die Antworten mit dem Logo links. Was
die KI dazwischen tut, steht als eine graue Zeile, zum Beispiel 3 Schritte
in Cadwork. Ein Klick zeigt die einzelnen Schritte, über der Maus steht der
technische Name. Hast du hochgerollt, bleibt die Stelle stehen, und „Neu“
(Pfeil nach unten) führt zum Neuesten. Die Zeitangaben sind grob (gerade eben, vor 5 min, heute
09:12). Solange die KI arbeitet, steht an der Stelle der nächsten Antwort
ein „…“ (über der Maus: was sie gerade tut). Was ein Zug gekostet hat
(Token, bei Anbietern mit Schlüssel auch den Betrag), zeigt die Maus über
der Antwort.

**Arbeitsordner (nur Claude Code):** Claude Code arbeitet nur in einem
Ordner. Der Knopf mit dem Ordner-Symbol oben links im Chat zeigt ihn. Ein Klick zeigt
die zuletzt gewählten Ordner und „Arbeitsordner wählen …“; „Wahl entfernen“
hebt die Wahl auf. Dateien darin liest Claude Code in jedem Modus ohne
Rückfrage. Wähle deshalb einen Projektordner, nicht ein ganzes Laufwerk oder
deinen Benutzerordner. „Ordner“ daneben (Ordner mit Plus) gibt Claude Code bis zu drei weitere
Ordner ab dem nächsten Chat, mit denselben Rechten; ein Klick auf einen
davon nimmt ihn wieder heraus. Ein weiterer Ordner mit einem der
Zeichen & % ^ ! im Namen geht nicht, weil er so nicht sicher bei Claude Code
ankommt. Ohne Wahl gilt eine Datei `projektordner.txt`
im Plugin-Ordner mit dem Pfad eines Ordners. Die Umgebungsvariable
`OPEN_MCP_CAD_PROJEKT` geht beidem vor; der Chat sagt dann, dass
deine Wahl gerade nicht gilt.

**Bisherige Chats (nur Claude Code):** Solange kein Chat läuft, stehen im
Chat die Chats, die hier in diesem Arbeitsordner begonnen
wurden, der neueste oben. Ein Klick öffnet einen, die nächste Nachricht
setzt ihn fort. Chats aus dem Terminal oder aus älteren Fassungen des
Plugins stehen nicht darin. Steht bei einem Chat
„läuft gerade in einem anderen Cadwork“, schreibst du dort weiter oder
drückst hier „Neuer Chat“.

## Deinstallation

- Ordner `Open MCP CAD` im Cadwork-Profil löschen
- Ordner `%LOCALAPPDATA%\OpenMcpCad` löschen (Server-Python,
  Arbeitsordner von Codex und die Erfahrungen `erfahrungen.jsonl`)
- Ordner `%APPDATA%\OpenMcpCad` löschen (Chat-Einstellungen `chat.json`:
  Anbieter, Modelle, Arbeitsordner, die letzten vier Zeichen der
  Schlüssel)
- Gespeicherte Schlüssel entfernen: am einfachsten vorher unter ⋯ → „Einstellungen“ bei jedem Anbieter „entfernen“. Sonst in der Systemsteuerung unter
  Anmeldeinformationsverwaltung → Windows-Anmeldeinformationen →
  Generische Anmeldeinformationen jeden Eintrag, der mit `Open MCP CAD/`
  beginnt: `Open MCP CAD/openai`, `Open MCP CAD/anthropic`,
  `Open MCP CAD/openrouter`, `Open MCP CAD/eigen`
- Benutzervariable `OPEN_MCP_CAD_PYTHON` entfernen
- Eintrag im KI-Programm entfernen: der Installer nannte beim Eintragen
  den Weg dazu (den Abschnitt bzw. Eintrag `open-mcp-cad` löschen oder
  die Sicherungskopie zurückkopieren, `copy /Y` in der
  Eingabeaufforderung; Claude Code: `claude mcp remove open-mcp-cad -s user`)

Wer gar nichts zurücklassen will, löscht ausserdem die Protokolle
`C:\Users\Public\OpenMcpCad_*.log`, die Ordner `C:\Users\Public\open-mcp-cad`
und `C:\Users\Public\OpenMcpCad_Notizen`, die Dateien `*.omcad.json` neben
den Cadwork-Dateien (Prüfhinweise und Briefkasten) und im Temp-Ordner
(`%TEMP%`) alles, was mit `open_mcp_cad` beginnt. Python 3.13, Ollama und
LM Studio, falls sie dafür installiert wurden, entfernst du in den
Windows-Einstellungen unter Apps. Die Chats von Claude Code gehören zu
Claude Code (`%USERPROFILE%\.claude\projects`) und bleiben.

## Lizenz

GNU AGPL-3.0, siehe `LICENSE`. Kein Produkt der cadwork informatik AG.
