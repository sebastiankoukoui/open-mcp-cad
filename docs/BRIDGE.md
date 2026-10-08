# Open MCP CAD — Verbindung zwischen Cadwork und Open MCP CAD

Stand 2026-08-04. Ersetzt die vier handgepflegten `McpBridge*.py`.
Alles hier ist **gemessen oder aus dem Code belegt**; wo etwas offen ist,
steht das ausdrücklich dabei.

> **Herleitung, Stand 2026-08.** Zustände, Protokoll, Beenden, Schreiblizenz
> und Qt-Antrieb gelten weiter. Überholt sind Abschnitt 1 (vier Ordner) sowie
> 10 und 11 (Ausrollen): heute gibt es EINEN Plugin-Ordner `Open MCP CAD`,
> siehe README.

---

## 1. Namen

| Benutzerseitig | Intern (bleibt) |
|---|---|
| **Open MCP CAD A / B / C / D** (Cadwork-Plugin-Menü) | Ordner `McpBridge`, `McpBridgeB/C/D` |
| **Open MCP CAD Verbindungen** (Übersichtsfenster) | `scripts/verbindungen_tk.py` |
| „Verbindung", „Auftrag", „Bereit / Bearbeitet Modell" | Bridge, Job, `ready` / `busy_write` |

Port, PID, Protokoll und das Wort „MCP" tauchen nur noch unter
**Technische Details** auf.

**A ist jetzt eindeutig A** — im Menü („Open MCP CAD A" statt „MCP
Bridge"), im Status (`instanz: "A"`), in den Thread-Namen
(`Open-MCP-CAD-A-Listener`) und in der eigenen Logdatei. Ordner- und Dateiname
bleiben `McpBridge/McpBridge.py`: Cadwork verlangt Ordnername ==
Dateiname, und ein Umbenennen würde jede bestehende Installation im
Userprofil doppelt erscheinen lassen. Wenn das später trotzdem gewünscht
ist, ist es ein eigener, klar abgegrenzter Schritt.

---

## 2. Die UI-Blockade — Ursache gefunden UND behoben

> **Ergebnis vorweg (2026-08-04, 23:15, in Cadwork 2026 gemessen):**
> Mit dem **Qt-Antrieb** bleibt Cadwork bedienbar, während eine Verbindung
> läuft. Rueckmeldung: *„D gestartet, cadwork lässt sich bedienen."* Gleichzeitig
> gemessen: Zustand „Bereit", Herzschlag 0,06 s alt, Leseauftrag 437 ms,
> cwapi3d-Aufruf 313 ms. Mit dem alten Antrieb war Cadwork im selben Test
> **nicht** bedienbar (*„kann die maus bewegen über den bildschirm aber im
> cadwork passiert nichts"*).
>
> Der Weg dahin steht unten — er ist lehrreich, weil zwei Annahmen
> unterwegs gekippt sind.

## 2a. Die UI-Blockade — was tatsächlich dahintersteckte

### Der Widerspruch

| Quelle | Aussage |
|---|---|
| alter Code, `_main_loop` | „damit die Cadwork-UI bedienbar bleibt" |
| `CLAUDE.md`, `plugin_info.xml` | „Cadwork-UI ist blockiert, solange das Plugin läuft" |
| Messskript in einem privaten Builder-Repo (2026-07-24) | Bridge zieht keine Jobs mehr, bis eine Mausbewegung im Cadwork-Fenster ankommt |
| **Rueckmeldung 2026-08-04** | **im Zustand „Bereit" ist Cadwork bedienbar; den Hänger kennt er nicht** |

Die Aussage des Nutzers löst den Widerspruch zugunsten des Codes auf: Der Code hat
recht **für den Leerlauf**, die Doku hat recht **für die Auftragszeit** —
und das Aufwachproblem ist ein Randfall, kein Alltag.

### Was aus dem Code sicher folgt

1. **Die Pumpe lief nur im Leerlauf.** `_pump_windows_messages()` stand
   ausschliesslich im `queue.Empty`-Zweig. Während eines Auftrags — also
   genau in den Minuten, in denen gezeichnet wird — wurde **keine einzige**
   Windows-Message verarbeitet. „UI bleibt bedienbar" war für die gesamte
   Arbeitszeit schlicht nicht wahr; bestenfalls galt es zwischen zwei
   Aufträgen.
2. **Die Pumpe war unbegrenzt.** `while _PeekMessageW(...)` lief, bis keine
   Message mehr kam. Eine Message, die sich beim Verarbeiten selbst wieder
   erzeugt, hält so eine Schleife dauerhaft fest.
3. **Die Pumpe ruft Cadworks eigene Fensterprozeduren auf.**
   `DispatchMessageW` betritt Cadworks UI-Code, während ein Plugin auf dem
   Stack liegt. Mehrere Standard-Win32-Pfade (Menü-Tracking, Move/Size über
   `WM_NCLBUTTONDOWN`, Tooltip-Tracking, Eingabeaufforderungen) betreten
   dort **ihre eigene modale Message-Schleife**, die erst bei echter
   Benutzereingabe zurückkehrt.

### Was die Beobachtung dazu sagt

Der dokumentierte Befund vom 2026-07-24: Verbindungen wurden angenommen,
aber nie beantwortet; die Worker-Threads lebten (kaputtes JSON wurde sofort
beantwortet); **`3d.exe` war dabei CPU-idle**; eine per `PostMessage`
gesendete Mausbewegung ins Viewport-Fenster hat die Bridge wiederbelebt,
`WM_NULL` reichte nicht.

*CPU-idle* schliesst Punkt 2 als Ursache praktisch aus — eine
selbstnachliefernde `WM_PAINT`-Schleife würde einen Kern auslasten. Idle
plus „steht" plus „lebt wieder auf, sobald eine Mausbewegung eintrifft"
passt genau auf Punkt 3: der Hauptthread **wartet blockierend in einer
fremden modalen Schleife** auf Benutzereingabe.

### Ergebnis

> **Die Message-Pumpe macht die UI im Leerlauf bedienbar — und ist zugleich
> der einzig plausible Weg in das Aufwachproblem.** Das Plugin nimmt Cadwork
> die Ereignisschleife weg und ruft sie von innen wieder auf; betritt eine
> der so aufgerufenen Fensterprozeduren ihre eigene modale Schleife, parkt
> der Hauptthread dort.

Das ist kein Grund, sie abzuschalten — im Alltag funktioniert sie (Rueckmeldung aus dem Betrieb).
Es ist ein Grund, sie zu **begrenzen** und einen Hänger **sichtbar** zu
machen. Genau das ist gebaut.

**Was das Log dazu NICHT hergibt** (ehrlich gemessen am 2026-08-04 über
`C:\Users\Public\McpBridge.log`, 7431 Zeilen, 2337 Verbindungen seit
2026-07-24): 533 Verbindungen waren ≥ 5 s offen, aber **keine einzige** ohne
`Verarbeite`-Zeile im selben Zeitfenster. Das Log **stützt den Befund also
nicht** — es widerlegt ihn aber auch nicht, aus zwei Gründen:

* Alle vier Instanzen schrieben in **dieselbe Datei**; eine `Verarbeite`-Zeile
  kann von einer anderen Instanz stammen. Eine saubere Zuordnung ist mit dem
  alten Log gar nicht möglich.
* Seit dem 2026-07-24 läuft bei jedem längeren Bridge-Lauf der
  WM_MOUSEMOVE-Keepalive mit — der Fall wird seither aktiv verhindert.

Beides ist jetzt behoben: **eigene Logdatei je Steckplatz**, jede Zeile
zusätzlich mit `[A:53127]` gestempelt, und eine `Fertig nach x.xx s`-Zeile
je Auftrag, damit Laufzeiten überhaupt messbar werden.

### Was der Nutzer dazu sagt — und was daraus gebaut wurde

**Rueckmeldung 2026-08-04, nach der ersten Fassung dieses Dokuments:**

> „im modus bereit also wenn nichts aktiv gesendet ausgelesen oder
> gespeichert etc wird kann man das dokument jetzt schon bedienen vor dem
> umbau … das problem kenne ich gar nicht das wird ein sehr altes problem
> gewesen sein"

Das ist der entscheidende Messwert, den ich nicht hatte: **die Pumpe
liefert im Alltag genau das, wofür sie da ist**, und der Hänger ist ihm nie
begegnet. Meine erste Fassung hätte sie abgeschaltet — das wäre eine
Verschlechterung gegen ein Problem gewesen, das er nicht hat. Deshalb:

* **`ui_pumpe` ist standardmässig AN.** Im Zustand „Bereit" bleibt Cadwork
  bedienbar, so wie bisher. `OPEN_MCP_CAD_UI_PUMPE=0` schaltet sie aus, falls
  der Hänger doch einmal auftritt.
* Sie läuft aber **begrenzt** (`OPEN_MCP_CAD_UI_PUMPE_MAX`, Default 200 Messages
  je Leerlaufrunde — bei 50 ms Takt sind das 4000/s, mehr als genug) und
  schreibt eine Fehlerzeile ins Log, wenn sie die Grenze erreicht.
* Tritt der Hänger doch auf, ist er jetzt **sichtbar statt rätselhaft**:
  siehe Herzschlag unten. Und die Abhilfe (einmal ins 3D-Fenster klicken)
  steht als Klartext im Status.
* **Herzschlag + Aufsicht.** Der Hauptthread stempelt jede Schleifenrunde.
  Der Status meldet `hauptthread_alter_s` und `hauptthread_ok`. Steht der
  Hauptthread im Leerlauf länger als 3 s, sagt der Status im Klartext:
  *„Cadwork-Hauptthread meldet sich seit 42 s nicht … Abhilfe: einmal ins
  Cadwork-3D-Fenster klicken."* Aus einem stillen Timeout wird eine
  Diagnose.

### Die eigentliche Frage: bedienbar WÄHREND gearbeitet wird

Das ist das Ziel („ich will ja dass es geht während dem was bearbeitet
wird") — und das kann die Pumpe **prinzipiell nicht leisten**, egal wie man
sie einstellt: sie steht im Leerlauf-Zweig, und während eines Auftrags
steckt der Hauptthread im cwapi3d-Aufruf. Es gibt keinen Punkt, an dem sie
drankäme.

Drei Wege dahin, in aufsteigender Grösse:

1. **Pause.** Schon da, sofort nutzbar: „Pausieren" drücken → der laufende
   Auftrag läuft fertig → danach ist der Hauptthread im Leerlauf, die Pumpe
   läuft wieder, Cadwork ist bedienbar. „Fortsetzen", wenn du fertig bist.
   Bei einem Ablauf in Batches ist die Wartezeit ein Batch, nicht der ganze
   Lauf.
2. **`atme()`-Haken im Auftragscode.** Wie `store_as`/`get_stored` liesse
   sich eine Funktion in den ausgeführten Code injizieren, die die Pumpe
   zwischen zwei cwapi3d-Aufrufen laufen lässt — die Zeichner setzen sie
   alle N Elemente in ihre Schleife. **Nicht gebaut**, weil sie genau die
   Re-Entrance einführt, die oben als Ursache verdächtigt wird, und weil
   „Benutzer bearbeitet Elemente, die der halbfertige Auftrag gleich
   anfasst" eine neue Fehlerklasse wäre. Machbar, wenn du es willst — dann
   aber mit klarer Ansage, dass währenddessen nicht am Modell gearbeitet
   werden darf, nur geschaut.
3. **Qt-Timer-Antrieb** (unten): der saubere Weg.

Die **eigentliche** Lösung wäre, den Hauptthread gar nicht erst zu
belegen: Plugin startet, hängt sich in Cadworks *eigene* Ereignisschleife
ein und kehrt zurück — die UI bliebe vollständig bedienbar, Aufträge
liefen trotzdem sequentiell im Hauptthread. Dafür braucht es einen
Tick-Hook. `cwapi3d` hat keinen (verifiziert für 2025/437), **Qt hätte
einen** — siehe [Abschnitt 7](#7-oberflächen-technik-was-in-cadwork-2026-wirklich-da-ist).
Der Kern hat dafür den Platzhalter `antrieb='qtimer'`; er ist **nicht
aktiv** und lehnt sich mit einer Logzeile ab, solange er nicht im echten
Cadwork nachgewiesen ist.

---

## 3. Zustände

| Zustand | Text im Fenster | Bedeutung |
|---|---|---|
| `stopped` | **Aus** | Plugin läuft nicht |
| `starting` | **Wird gestartet** | Port wird belegt, Dokument wird gelesen |
| `ready` | **Bereit** | erreichbar, kein Auftrag |
| `busy_read` | **Liest Modell** | Auftrag läuft, ausdrücklich lesend |
| `busy_write` | **Bearbeitet Modell** | Auftrag läuft und darf verändern |
| `paused` | **Pausiert** | erreichbar, lehnt Modell-Aufträge ab |
| `stopping_after_job` | **Wird nach dem Auftrag beendet** | beendet sich, sobald der laufende Auftrag fertig ist |
| `error` | **Störung** | mit Klartext-Meldung |

Farben (grün/blau/orange/rot/grau) sind **nur Zugabe** — der Zustand steht
in jeder Ansicht als Text daneben.

Zwei Zustände kennt nur der Client, weil sie von aussen entstehen:

| | |
|---|---|
| **Aus** | Verbindungsaufbau scheitert (0,6 s) — dort läuft nichts |
| **Keine Antwort** | Verbindung kommt zustande, Antwort bleibt aus — das Plugin lebt, sein Cadwork-Hauptthread steht |

Diese Unterscheidung ist absichtlich hart gebaut: **ein Timeout wird nie als
„Aus" ausgegeben.** Auf ein „Connection refused" ist dabei kein Verlass —
gemessen am 2026-08-04 auf dem Legion läuft eine TCP-Verbindung zu einem
*geschlossenen* Localhost-Port in den Timeout, statt abgewiesen zu werden.
Deshalb haben Verbindungsaufbau und Antwort getrennte Zeitgrenzen.

---

## 4. Protokoll

JSON-Lines wie bisher. **Alle Neuerungen sind optional** — alte Clients
laufen unverändert weiter, und ein neuer Client läuft auch gegen ein altes
Plugin (beides gemessen, siehe [Abschnitt 9](#9-was-offline-geprüft-ist)).

```json
Request : {"id": 1, "method": "execute_cwapi3d", "params": {...}}
Response: {"id": 1, "ok": true,  "result": ...}
          {"id": 1, "ok": false, "error": "...", "message": "...", "details": "..."}
```

### Neue Parameter für `execute_cwapi3d`

| Parameter | Wirkung |
|---|---|
| `description` | Klartext, was der Auftrag tut → steht im Fenster und im Log |
| `operation_id` | Kennung des Clients für diesen Auftrag |
| `access_mode` | `read` / `write`. **Fehlt oder unbekannt ⇒ `write`** |
| `client_id` | stabile Kennung für die Schreiblizenz |
| `client_label` | lesbarer Name („Claude Code") |
| `expect_document` | Teilstring, der im Dokumentnamen vorkommen muss, sonst `wrong_document` und es passiert nichts |
| `uebernehmen` | `true` nimmt eine fremde Schreiblizenz ausdrücklich weg |

`execute_cadwork_command(..., description=...)` hat die Beschreibung bisher
**verworfen** — `server.py` reicht sie jetzt durch. Damit steht im Fenster:

```
B   Fenster_Test.3d      Bearbeitet Modell: Fensterwand Süd erzeugen   00:42
```

### Methoden ohne Umweg über den Cadwork-Hauptthread

`ping` · `status` · `pause` · `resume` · `shutdown` ·
`shutdown_after_current` · `discard_pending` · `release_write_lease` ·
`list_store_keys` · `clear_store`

Diese werden **im Worker-Thread** beantwortet und rufen kein cwapi3d auf.
Deshalb antworten sie auch, während Cadwork minutenlang zeichnet. Über die
Queue laufen nur noch `execute_cwapi3d` und `get_document_info`.

### `status` liefert

`instanz` · `port` · `pid` · `version` · `protokoll` · `dokument`
(aus dem Cache) · `dokument_stand_s` · `dokument_elemente` · `zustand` +
`zustand_text` · `gestartet` · `laufzeit_s` · `verbindungen` ·
`wartende_auftraege` · `auftraege_gesamt` · `auftrag` (Methode,
Beschreibung, `operation_id`, Zugriff, Client, Startzeit, Laufzeit) ·
`letzter_auftrag` · `letzter_fehler` · `schreiblizenz` ·
`hauptthread_alter_s` · `hauptthread_ok` · `hinweis` · `ui_pumpe` ·
`antrieb`.

**Der Dokumentname kommt aus einem Cache, den ausschliesslich der
Cadwork-Hauptthread füllt** (beim Start, alle 5 s im Leerlauf und nach
jedem Schreibauftrag). Aus einem Worker-Thread wird nie cwapi3d angefasst —
das wäre der sichere Weg in einen Absturz, weil cwapi3d nicht thread-sicher
ist.

---

## 5. Sicheres Beenden und Pausieren

| Situation | `shutdown` | `shutdown_after_current` |
|---|---|---|
| Bereit / Pausiert / Störung | beendet sofort, wartende Aufträge werden verworfen | dasselbe |
| **Liest / Bearbeitet Modell** | **wird abgelehnt** (`error: busy`) | angenommen; beendet sich nach dem Auftrag |

Der alte `shutdown` hat mitten in einem laufenden Auftrag die Sockets
gekappt. Der Auftrag lief im Cadwork-Hauptthread **weiter** — „abgebrochen"
war eine Lüge. Jetzt gilt:

1. Läuft nichts, wird sofort sauber beendet.
2. Läuft etwas, wird sofortiges Beenden **abgelehnt**, mit Hinweis auf
   `shutdown_after_current`.
3. Nach `shutdown_after_current` läuft der aktuelle Auftrag vollständig zu
   Ende, **seine Antwort geht raus** (der Hauptthread wartet ausdrücklich
   auf das Absenden, bis zu 3 s), erst danach werden Sockets und Listener
   geschlossen.
4. Noch nicht gestartete Aufträge werden **kontrolliert verworfen** — jeder
   bekommt eine eigene Antwort `discarded`, keiner läuft ins Timeout.
5. **Kein Thread wird gewaltsam beendet**, und es gibt keinen Knopf, der
   Cadwork abschiesst. „Jetzt beenden" ist im Fenster gesperrt, solange ein
   Auftrag läuft — und selbst wenn man ihn erwischt, lehnt die Verbindung
   selbst noch einmal ab.

**Pause** heisst: laufender Auftrag läuft fertig, danach werden Modell-
Aufträge mit `bridge_paused` abgelehnt. Status, `resume` und sicheres
Beenden bleiben erreichbar. Cadwork kann danach von Hand bedient werden —
sobald die UI-Frage aus Abschnitt 2 geklärt ist, ist genau das der Weg für
„ich will jetzt selber ran".

---

## 6. Manuelles Arbeiten und Konfliktschutz

Was **nicht** versprochen wird: gleichzeitiges Arbeiten von Mensch und KI
am selben Modell. Was gilt:

* **Zustand „Bereit": Cadwork ist normal bedienbar.** Zoomen, drehen,
  auswählen, ändern — die Pumpe läuft im Leerlauf-Zweig mit.
* **Während eines Auftrags („Liest Modell" / „Bearbeitet Modell"): nicht.**
  Der Hauptthread steckt im cwapi3d-Aufruf, ein Auftrag ist unteilbar. Das
  steht jetzt als Zustand da, statt sich hinter einem eingefrorenen Fenster
  zu verstecken.
* Lange Abläufe gehören in **Batches**; zwischen Batches kann pausiert
  werden. **„Pausieren" ist der Weg, um selbst ranzukommen:** der laufende
  Auftrag läuft fertig, danach ist der Hauptthread frei und Cadwork wieder
  bedienbar — bis „Fortsetzen".
* **Keine cwapi3d-Aufrufe in Hintergrundthreads.** Unverändert und
  ausdrücklich: der Statuspfad wurde genau deshalb so gebaut, dass er ohne
  cwapi3d auskommt.
* Fernsteuernder Code soll mit **ausdrücklichen Element-IDs** arbeiten und
  nicht still von Auswahl, Sichtbarkeit oder aktiver Gruppe abhängen. Das
  ist eine Regel für den erzeugten Code, keine, die die Bridge erzwingen
  kann — sie gehört deshalb auch in die Regeln (`rules.md`) des
  eingehängten Fachwissens.

### Schreiblizenz

Bewusst klein gehalten:

* Ein Schreibauftrag nimmt eine Lizenz auf `client_id`, gültig
  `OPEN_MCP_CAD_LIZENZ_TTL` Sekunden (Default **120**), bei jedem weiteren
  Schreibauftrag erneuert.
* Ein Schreibauftrag einer **anderen** `client_id` wird mit `document_busy`
  abgelehnt — mit Name und Restzeit im Klartext.
* Leseaufträge sind davon nie betroffen.
* `bridge_client` gibt die Lizenz beim Prozessende automatisch frei
  (`atexit`), damit das nächste Skript nicht auf den Ablauf warten muss.
* Ausdrückliche Übernahme ist möglich (`uebernehmen: true`), ebenso
  Freigabe von Hand — beides auch aus dem Fenster.

Damit ist die eigentliche Gefahr abgedeckt: **zwei KI-Sitzungen, die
gleichzeitig dieselbe Datei verändern.** Die Lizenz heilt von selbst, statt
eine Datei dauerhaft zu sperren.

### Kein stiller Stau

* Mehr als `OPEN_MCP_CAD_MAX_QUEUE` (Default 16) wartende Aufträge ⇒
  `queue_full` statt unbemerktem Anhängen.
* Ein zweiter Schreibauftrag derselben Sitzung wird angenommen und ist in
  `wartende_auftraege` sichtbar; von einer anderen Sitzung wird er
  abgelehnt.
* `discard_pending` wirft wartende Aufträge kontrolliert weg.

### Dokument-Identität

`expect_document` wird **in der Bridge** geprüft, bevor irgendetwas läuft —
gegen den Cache, den nur der Hauptthread füllt. `server.py` prüft zusätzlich
weiterhin selbst (`OPEN_MCP_CAD_EXPECT_DOC`), damit der Schutz auch gegen ein
altes Plugin greift.

---

## 7. Oberflächen-Technik: was in Cadwork 2026 wirklich da ist

Gemessen am 2026-08-04 auf dem Legion, in
`C:\Program Files\cadwork.dir\EXE_2026\Pclib.x64`
(`python scripts/_gui_sondierung.py --lokal`):

| | |
|---|---|
| Python | **3.14.4** (`python314.dll`) |
| **PyQt6** | liegt in `python314\site-packages\PyQt6`, mit eigenem **Qt 6.8.2** |
| Qt von Cadwork | **Qt 6.8.3** in `Pclib.x64` |
| tkinter | vollständig da (`tkinter\`, `_tkinter.pyd`, `tcl86t/tk86t 8.6.2`) |

### Am 2026-08-04 im laufenden Cadwork gemessen — beides bestätigt

`scripts/_gui_sondierung.py --im-cadwork` (Stufe 1, lädt nichts):

```
"schon_geladen": ["PyQt6"]
```

**Cadwork hat PyQt6 selbst geladen** — es benutzt es für seine eigenen
Dialoge. Es ist also keine fremde Bibliothek, die man in den Prozess
schmuggelt, sondern die dort etablierte Technik.

`--qt-import` (Stufe 2, importiert wirklich):

```
qt_version 6.8.2 · pyqt_version 6.8.1
qapplication_vorhanden: true · app_name "3D" · app_klasse QApplication
fenster: 30
```

Cadworks eigene `QApplication` ist aus dem Plugin heraus erreichbar, mit 30
Top-Level-Widgets. Damit ist zweierlei belegt:

1. Ein **nicht-modales Fenster im Plugin** ist möglich (Variante 1).
2. Ein **`QTimer` auf dieser QApplication ist der fehlende Tick-Hook.**
   Damit müsste `serve()` den Hauptthread nicht mehr halten: Listener
   starten, Timer alle 50 ms die Queue abarbeiten, `main()` kehrt zurück —
   Cadwork behält seine eigene Ereignisschleife, die Oberfläche bleibt
   bedienbar, und die Message-Pumpe mit ihrem Absturzrisiko entfällt
   ersatzlos. Das ist der Weg zu „bedienbar, während gearbeitet wird".

Damit ist `antrieb='qtimer'` von „unbewiesene Idee" zu „nächster
Arbeitsschritt" geworden. Gebaut ist er noch nicht.

### Entscheidung

**Gebaut wird jetzt Variante 2 des Auftrags: eine kleine eigenständige
Oberfläche neben Cadwork.** Gründe:

1. Sie ist **sofort beweisbar sicher**. Ein eigener Prozess kann Cadwork
   weder blockieren noch mitreissen — und genau das Gegenteil war das
   Problem, das wir gerade untersuchen.
2. Sie zeigt **alle vier Steckplätze gleichzeitig**, auch die in anderen
   Cadwork-Prozessen. Eine Oberfläche *in* Cadwork sähe immer nur sich
   selbst, es sei denn, sie fragt die anderen ebenfalls über TCP — dann ist
   sie aber genau dasselbe Programm, nur an einem gefährlicheren Ort.
3. Eine Oberfläche im Cadwork-Prozess müsste sich dessen Ereignisschleife
   teilen. Das ist dieselbe Stelle, an der die alte Bridge hängengeblieben
   ist. Sie dort hinzubauen, **bevor** die Ursache im echten Cadwork bestätigt
   ist, wäre genau der Fehler, den der Auftrag verbietet.

**Variante 1 (Fenster in Cadwork) ist seit dem 2026-08-04 abends belegt
machbar** (siehe Messung oben) und der nächste Arbeitsschritt — zusammen
mit dem QTimer-Antrieb, der dasselbe Fundament nutzt. Das eigenständige
Fenster bleibt trotzdem sinnvoll: es sieht **alle vier** Steckplätze, auch
die in anderen Cadwork-Prozessen, und überlebt einen Cadwork-Absturz.

**Variante 3 (Browser) ist als Rückfallebene mitgebaut**
(`verbindungen_web.py`) — gleiche Inhalte, gleiche Regeln, für Rechner ohne
Tkinter. Das Muster (kleiner lokaler HTTP-Dienst plus Browser) hatte sich
vorher in einem privaten Builder-Repo bewährt.

Technik der gebauten Oberfläche: **Tkinter aus dem System-Python**
(3.12.10, Tk 8.6 — geprüft). Nicht modal, kein Blockieren, Netzwerkabfragen
laufen in einem Hintergrundthread, damit das Fenster selbst nie hängt.

### Was das Fenster kann — und was ehrlich nicht

```
Open MCP CAD Verbindungen                                       Stand 19:42:07

●  A   Haus_Seeblick.3d       Bereit                                [Pausieren] [Fortsetzen] [Nach Auftrag beenden] [Jetzt beenden] [Details]
●  B   Fenster_Test.3d      Bearbeitet Modell: Fensterwand Süd   00:42
●  C   Tragwerk_OG.3d       Pausiert
●  D   —                    Aus
```

* Pro Verbindung: Dokument, Zustand, aktuelle Tätigkeit, verstrichene Zeit,
  Pausieren / Fortsetzen / Nach Auftrag beenden / Jetzt beenden, dazu
  aufklappbare technische Details (Port, PID, Version, Protokoll,
  Warteschlange, Schreiblizenz, Herzschlag, Antwortzeit).
* „Jetzt beenden" ist gesperrt, solange ein Auftrag läuft.
* Beschäftigt oder nicht erreichbar wird **so benannt** und nicht
  geschönt.
* **Starten kann das Fenster nichts.** Läuft in einem Cadwork-Prozess noch
  kein Plugin, gibt es dort nichts, womit man reden könnte — es gibt keinen
  Weg von aussen hinein. Der Steckplatz steht auf „Aus" und hat bewusst
  keinen Startknopf. Gestartet wird im jeweiligen Cadwork:
  **Plugin-Menü → Plugin user → Open MCP CAD A/B/C/D.**
  Überwacht und sicher beendet wird zentral.

---

## 8. Vier Kopien — eine Quelle

Vorher: vier Dateien à 756 Zeilen, die sich in **genau einer** Zeile
unterschieden (`PORT`), plus ein Zeilenende-Unterschied bei A (LF statt
CRLF). Vier Kopien, viermal zu pflegen.

Jetzt:

```
cad_plugin/
├── _core/
│   └── omcad_bridge_core.py     ← DIE Quelle, ~1150 Zeilen
├── McpBridge/                      Open MCP CAD A, Port 53127
│   ├── McpBridge.py                ← 52 Zeilen, nur Instanz/Port/Name/Log
│   ├── omcad_bridge_core.py      ← byte-identische Kopie
│   └── plugin_info.xml             ← erzeugt
├── McpBridgeB/  … C/  … D/         dito
```

Erzeugt und geprüft von `scripts/plugins_generieren.py`:

```bash
python scripts/plugins_generieren.py            # erzeugen
python scripts/plugins_generieren.py --pruefen  # nur prüfen (Exit 1 bei Abweichung)
```

Warum Kopien statt eines gemeinsamen Imports über Ordnergrenzen: Cadworks
Plugin-Loader lädt aus dem Plugin-Ordner; ein Ordner ohne `plugin_info.xml`
in `API.x64` wäre eine Wette auf ungeprüftes Verhalten. Die Kopien sind
**erzeugt und per SHA-256 geprüft**, nicht gepflegt — der Unterschied ist
entscheidend. Das Offline-Gate lässt vier auseinanderlaufende Kopien nicht
durch (Prüfung A4).

Der Zustand hängt am Objekt `Verbindungsdienst`, nicht an Modul-Globals.
Würden in einem Cadwork-Prozess nacheinander zwei Steckplätze geladen,
kämen sie sich trotz gleichen Modulnamens nicht ins Gehege; der Einstieg
meldet ausserdem, wenn er einen Kern anderer Version vorfindet.

### Logs

Vorher schrieben **alle vier** nach `C:\Users\Public\McpBridge.log` — mit
Thread-Namen wie `McpBridge-Worker-53123`, die auch bei B/C/D so hiessen.
Eine Zeile war keiner Instanz zuzuordnen (genau daran ist die Log-Analyse in
Abschnitt 2 gescheitert).

Jetzt: `C:\Users\Public\OpenMcpCad_A.log` (bzw. B/C/D), **und**
zusätzlich jede Zeile mit `[A:53127]` gestempelt, Threads heissen
`Open-MCP-CAD-A-Listener` / `Open-MCP-CAD-A-Worker-<port>`. Geloggt wird über einen
eigenen Logger (`omcad.connect`, `propagate=False`) statt über den
Root-Logger.

---

## 9. Was offline geprüft ist

```bash
python tests/test_offline.py        # 110 Prüfungen
python tests/test_offline.py -v     # mit Einzelnachweis
```

Der Kern läuft dabei gegen ein untergeschobenes cwapi3d (zwei Attrappen in
`sys.modules`) und wird über **echte TCP-Verbindungen** getestet — nicht
über Funktionsaufrufe.

| Abschnitt | Inhalt |
|---|---|
| **A** | XML gültig · alle Python-Dateien syntaktisch vollständig (`ast.parse` + Abschlussvertrag gegen Trunkierung) · A–D haben Instanz und Port richtig · Einstiege < 70 Zeilen · alle vier Kern-Kopien == Quelle |
| **B** | Start · `ping` liefert weiterhin `pong` · Status hat alle geforderten Felder · Pause / Resume · Shutdown aus „Bereit" · Port danach frei · Neustart auf demselben Port |
| **C** | Langer Auftrag: Zustand `busy_write` · **Status antwortet in < 1 s, während der Auftrag läuft** · `description`/`operation_id`/`access_mode`/`client_label` kommen an · **Shutdown während `busy` wird abgelehnt** · zweiter Schreibauftrag einer anderen Sitzung ⇒ `document_busy` · gleicher Client darf anhängen |
| **D** | `shutdown_after_current`: sofort bestätigt · wartender Auftrag kontrolliert verworfen (`discarded`) · laufender Auftrag wird **fertig** · Ende erst danach · Port frei |
| **E** | `wrong_document` ohne Ausführung · Blocklist · Fehler im Code ⇒ Fehlerantwort + `letzter_fehler` · unbekannte Methode · kaputtes JSON · Zugriffsart-Voreinstellung `write` · Übernahme und Freigabe der Lizenz · `queue_full` · `discard_pending` |
| **F** | Herzschlag frisch · UI-Pumpe an (und per `OPEN_MCP_CAD_UI_PUMPE=0` abschaltbar) · hängender Hauptthread wird erkannt und im Klartext benannt · Status bleibt erreichbar |
| **G** | Oberfläche: alle vier Steckplätze · „Aus" ≠ „Keine Antwort" · Zeilenformat · Tk-Fenster baut auf und zeigt Dokument/Tätigkeit/Zeit · „Jetzt beenden" gesperrt bei laufendem Auftrag, frei bei „Bereit" · Details nennen Port/PID/Version/Protokoll/Lizenz/Herzschlag · Browser-Rückfallebene liefert Seite und `/status` |

**Ergebnis: 110/110.**

### Zusätzlich gemessen (einmalig, nicht im Dauergate)

Rückwärtskompatibilität in **beide** Richtungen, gegen die alte Bridge aus
`git show HEAD:cad_plugin/McpBridge/McpBridge.py`:

| | Ergebnis |
|---|---|
| neuer `bridge_client` → **altes** Plugin | `execute_cwapi3d` ✅ (neue Parameter werden ignoriert) · `get_document_info` ✅ · `status` ⇒ `unknown_method` (sauber) · `release_write_lease` still verschluckt |
| neuer `server.py` → **altes** Plugin | `execute_cadwork_command` ✅ · `get_connection_status` ⇒ verständliche Meldung „Es läuft eine Version vor Open MCP CAD 2.0" |
| neuer `server.py` → **neues** Plugin | Status „Bereit \| Dokument Haus_Seeblick.3d" · Beschreibung sichtbar · Lizenz greift und wird freigegeben |

**Damit ist die Reihenfolge beim Ausrollen unkritisch:** `server.py` darf vor
dem Plugin aktualisiert werden.

### Ein Fund nebenbei

Ein `Request`, der gültiges JSON, aber kein Objekt ist (`"text"`, `[1,2]`),
liess den Worker-Thread mit `AttributeError` sterben — **ohne Antwort**. Der
Client sah ein abgebrochenes Timeout. Das galt für die alte Version genauso;
jetzt kommt `invalid_request` zurück, und ein Sicherheitsnetz sorgt dafür,
dass ein Worker nie ohne Antwort stirbt.

---

## 10. Ausrollen

> **Überholt** (Stand 2026-08, vier `McpBridge`-Ordner) — heute siehe README.

1. **Plugins erzeugen und prüfen** (im Repo, ändert nichts an Cadwork):

   ```bash
   python scripts/plugins_generieren.py --pruefen
   python tests/test_offline.py
   ```

2. **Alle laufenden Verbindungen sauber beenden** — im Fenster
   „Nach Auftrag beenden", oder in jedem Cadwork das Plugin beenden lassen.
   Nie ein Plugin überschreiben, während es läuft.

3. **Ins Cadwork-Userprofil kopieren** (unverändertes Verfahren, nur liegen
   jetzt drei Dateien je Ordner):

   ```powershell
   $api = "C:\Users\Public\Documents\cadwork\userprofil_2026\3d\API.x64"
   foreach ($p in "McpBridge","McpBridgeB","McpBridgeC","McpBridgeD") {
     $target = Join-Path $api $p
     if (Test-Path $target) { Remove-Item $target -Recurse -Force }
     Copy-Item -Path ".\cad_plugin\$p" -Destination $target -Recurse -Force
   }
   ```

4. **Gleichheit nachweisen** (Quelle == Userprofil):

   ```bash
   python scripts/deployment_pruefen.py
   ```

5. **Plugin neu aufrufen.** Im Menü steht jetzt „Open MCP CAD A/B/C/D".
   Ein **Cadwork-Neustart ist nicht nötig**: der Einstieg lädt den Kern über
   `importlib` frisch von der Platte, unter einem instanzeigenen Modulnamen
   (`omcad_bridge_core_A`). Ein einfaches `import` hätte beim zweiten
   Start in derselben Sitzung den ALTEN Kern aus `sys.modules` genommen —
   dann wäre jedes Update ohne Neustart wirkungslos geblieben.
   **Was nicht geht:** ein laufendes Plugin aktualisieren. Erst beenden,
   dann neu starten.

6. **`server.py` neu starten** (Claude Desktop neu starten). Nötig für
   `get_connection_status` und die durchgereichte Beschreibung — darf aber
   auch vorher passieren, siehe Abschnitt 9.

7. **Manuellen Testplan abarbeiten:**
   [`docs/OPEN_MCP_CAD_CONNECT_testplan_cadwork.md`](OPEN_MCP_CAD_CONNECT_testplan_cadwork.md)

**Zurück geht es jederzeit:** `git checkout <alter-stand> -- cad_plugin/`
und Schritt 3 wiederholen. Die alten Dateien stehen unverändert in der
Historie.

---

## 11. Phase 2 — dynamische Steckplätze (nur dokumentiert)

Heute bleibt es bei den vier festen Steckplätzen A–D. Sie sind stabil, die
MCP-Konfiguration zeigt darauf, und sie sind über Neustarts hinweg
vorhersagbar. **Nicht implementiert**, weil es weder klein noch
rückwirkungsfrei wäre.

Skizze, falls es später kommt:

* Nur noch **ein** Plugin-Knopf „Open MCP CAD".
* Beim Start **atomar** den ersten freien Steckplatz A–D belegen — atomar
  heisst hier: den Port selbst als Sperre benutzen (wer binden kann, hat
  ihn), nicht eine Datei vorher lesen und dann binden.
* Registrierung von Port, PID und Dokument in einer gemeinsamen Datei unter
  `C:\Users\Public\`, jeder Eintrag mit PID — Einträge ohne lebenden Prozess
  gelten als veraltet und werden beim nächsten Start aufgeräumt (deckt den
  Absturzfall ab).
* Die bestehende MCP-Konfiguration A–D bleibt unverändert nutzbar, weil sich
  an den Ports nichts ändert.

Offener Punkt, der das heute verhindert: der Nutzen ist gering (vier
Steckplätze reichen), der Preis ist eine neue Fehlerklasse — „welches
Dokument hängt an welchem Port" wird dynamisch, und genau diese Frage ist
die, die im Betrieb am meisten weh tut.

---

## 11b. Undo — Ursache gemessen, behoben in Kern 2.1.0

Der Knopf ruft `ec.make_undo()`. **Rueckmeldung 2026-08-05: es hat noch nie
funktioniert.** Getestet wurde es vor der Auslieferung nicht — das war ein
Fehler.

**Die Ursache ist keine Vermutung mehr.** Gemessen am 2026-08-06 im
Wegwerf-Dokument, jeweils über die vollständige Liste
der Element-IDs vor und nach dem Aufruf:

| Fall | vor `make_undo()` | danach | Bestand angetastet? |
|---|---|---|---|
| ohne Anmeldung | 563 | **563** — nichts passiert | nein |
| mit `add_created_elements_to_undo` | 563 | **560** — genau die neuen weg | nein |

Ein zweites `make_undo()` blieb bei 560: es frisst sich **nicht** in den
Bestand weiter. Die schlimmere der beiden befürchteten Varianten („nimmt die
letzte Aktion des Benutzers zurück") ist damit ausgeschlossen — der Knopf tat
schlicht *nichts*.

**Der Fix sitzt an einer Stelle, nicht in 17 Zeichnern.**
`_m_execute_cwapi3d` nimmt vor und nach jedem Auftrag eine Momentaufnahme
aller Element-IDs und meldet die Differenz mit
`ec.add_created_elements_to_undo` an (`_undo_anmelden`). Drei Gründe:

* Es deckt auch den Code ab, den die KI zur Laufzeit erzeugt — und das ist
  der häufigere Fall als die Zeichner im Katalog.
* Es fängt **Split-Körper**. Im Test kamen drei erzeugte Balken als
  `930021/930031/930033` zurück, nicht zusammenhängend:
  `subtract_elements_with_undo` ersetzt Körper. Ein Zeichner, der seine
  eigenen `create`-Rückgaben anmeldet, verfehlt genau die Teile, die schon
  einmal ohne Gruppe und Material liegengeblieben sind.
* Es kostet nichts: eine ID-Momentaufnahme dauert auf einem Modell mit
  15 300 Elementen **0,9 ms**.

Die Anmeldung steht in einem `finally` — auch ein auf halber Strecke
gescheiterter Auftrag lässt sich zurückdrehen, und gerade den will man
loswerden.

**Zwei Grenzen, die der Knopf ehrlich benennt:**

1. **Ein Schritt = ein Auftrag, nicht ein Zeichenlauf.** Ein Lauf über 3360
   Bauteile kommt in 17 Häppchen und braucht 17 Schritte; mehr als 10 lässt
   die Methode bewusst nicht auf einmal zu.

   Das ist gemessen, nicht angenommen — die naheliegende Sorge war, dass
   `subtract_elements_with_undo` eigene Einträge hinterlässt und ein Klick
   dann nur einen davon zurücknimmt. Zwei getrennte Aufträge mit je drei
   Balken und Ausklinkung, Bestand 560:

   | | Elemente |
   |---|---|
   | nach Auftrag A / B | 563 / 566 |
   | Undo 1 → 2 → 3 → 4 | 563 → 560 → 560 → 560 |

   Der Stapel läuft also sauber auftragsweise zurück und **stoppt am
   Bestand**, statt sich weiterzufressen.
2. **Nur NEUE Elemente.** Wer Bestehendes bloß ändert (Material,
   Verschieben), meldet sich weiterhin selbst an
   (`ec.add_modified_elements_to_undo`) — ein Vergleich von IDs kann
   Änderungen an unveränderter ID nicht sehen.

Abschaltbar je Auftrag mit `undo_anmelden: False`.

Abgesichert im Offline-Gate als Block **I8** (7 Prüfungen): Anmeldung,
Zurücknehmen, Auftrag ohne neue Elemente, Abschaltung, und der gescheiterte
Auftrag. Die Attrappe spielt Cadworks Undo-Stack nach, statt nur zu zählen —
sonst prüfte das Gate nur, *dass* `make_undo` gerufen wird, nicht dass danach
etwas weg ist.

## 11a. Schnellzeichnen — gemessen

`uc.disable_auto_display_refresh()` um Zeichenaufträge herum, Schalter im
Cadwork-Fenster oder `set_fast_draw(True)`.

Gemessen am 2026-08-05 mit einem Zeichenauftrag aus einem privaten
Builder-Repo (Aussenecken aus Holzbauteilen) auf Steckplatz A, in einem
Wegwerf-Dokument. Jeder Durchgang
startet im leeren Modell, Reihenfolge gedreht (aus/an/an/aus), gemessen
wird die Zeit **im Cadwork-Hauptthread**:

| | 4 Ecken = 112 Bauteile | 20 Ecken = 560 Bauteile |
|---|---|---|
| ohne | 0,86 s → **7,7 ms** je Bauteil | 6,87 s → **12,3 ms** je Bauteil |
| mit | 0,14 s → **1,2 ms** je Bauteil | 0,71 s → **1,3 ms** je Bauteil |
| Faktor | 6,4 | **9,7** |

Der Befund steckt im Vergleich der Spalten: **ohne Schnellzeichnen wächst
die Zeit je Bauteil mit dem Modell (7,7 → 12,3 ms), mit Schnellzeichnen
bleibt sie konstant (1,2 → 1,3 ms).** Cadwork zeichnet nach jedem Bauteil
neu, also wird jedes weitere teurer. Bei grossen Modellen fällt der Faktor
entsprechend höher aus.

Reproduzierbarkeit: 6,82 / 6,91 s (ohne) und 0,71 / 0,71 s (mit), in beiden
Reihenfolgen — kein Aufwärmeffekt.

Nachmessen: `OPEN_MCP_CAD_PORT=53127 python
scripts/_mess_schnellzeichnen.py --ecken 20`

#### Einschränkung: „bleibt konstant" gilt nur ohne Ausklinkung

Die Zahlen oben stammen aus **reinem Erzeugen** von Bauteilen. Sobald jedes
Bauteil zusätzlich eine Ausklinkung bekommt (create + create + subtract +
delete), wächst die Zeit je Bauteil **auch mit Schnellzeichnen** — gemessen
am 2026-08-06 mit `_schnellzeichnen_validierung.py --gross`:

| Bauteile | ohne | mit | Faktor |
|---|---|---|---|
| 12 | 61,94 ms | 45,38 ms | 1,4 |
| 480 | 52,11 ms | **16,05 ms** | **3,2** |
| 2000 | 73,74 ms | 49,17 ms | 1,5 |

Der Vorsprung bleibt also real, aber er ist **nicht konstant**: bei sehr
kleinen Läufen frisst ihn der Auftrags-Overhead, bei sehr grossen wächst der
Grundpreis je Bauteil in beiden Spalten mit. Für die Planung langer Läufe
heisst das: mit Faktor ~3 rechnen, nicht mit 9,7.

Der 2000er-Lauf **mit** Schnellzeichnen lief bewusst als zweiter, also im
bereits gewachsenen Modell und damit im Nachteil — er gewinnt trotzdem.
Deshalb ist der Vorsprung nicht der Reihenfolge geschuldet.

### Bedienbarkeit während eines Zeichenlaufs — gemessen

Rueckmeldung am 2026-08-05, während 3360 Bauteile in 17 Batches gezeichnet wurden:

> „es war jetzt bisschen ruckartig, immer so ca. alle halbe Sekunde 5 Ecken
> plötzlich da, aber konnte zwischen den Rucklern problemlos die Maus
> bewegen und Dinge aktivieren in der Zeichnung."

**Damit ist die Frage beantwortet, die den ganzen Umbau ausgelöst hat.** Mit
dem Qt-Antrieb ist Cadwork während eines Zeichenlaufs praktisch bedienbar —
nicht *während* eines einzelnen Auftrags (da steckt der Hauptthread im
cwapi3d-Aufruf), aber **zwischen** den Aufträgen. Ein Batch von 200
Bauteilen dauert unter einer Sekunde; danach gibt der Timer den Hauptthread
frei, Cadwork verarbeitet Eingaben, und der nächste Batch beginnt.

Das erklärt auch die Erinnerung an die alte Bridge A: ein Zeichenlauf
besteht aus vielen kurzen Aufträgen, und dazwischen war schon damals Luft.
Der Unterschied ist, dass diese Luft jetzt aus Cadworks eigener
Ereignisschleife kommt statt aus einer Message-Pumpe, die abstürzen kann.

**Praktische Folge für Zeichner:** Batches klein halten. 200 Bauteile je
Auftrag ergeben ~0,5 s Ruckler — angenehm. Ein einziger Auftrag über 3360
Bauteile wäre eine Minute Blockade und würde ausserdem an der
100-000-Zeichen-Grenze für Code scheitern.

### Der Anzeigebug — behoben am 2026-08-06 (Kern 2.2.0)

**Befund (2026-08-04 und 05, mehrfach):** Nach einem Zeichenlauf
sahen Bauteile in Cadwork aus, als hätten sie kein Material und keine
Ausklinkungen. **Am Modell gemessen war beides da** — direkt nach dem Lauf,
vor jedem Neustart: 4409 Elemente Glaswolle, 4757 Fi/Ta, 2270 OSB. Erst ein
Cadwork-Neustart zeigte es korrekt.

Zwei Hypothesen waren zuvor widerlegt worden, beide Umbauten bleiben drin,
weil sie unabhängig davon richtig sind — Lösung waren sie nicht:

| Hypothese | Gegenprobe |
|---|---|
| „ein zweites, verzögertes `vc.refresh()` reicht" | eingebaut — half nicht |
| „es liegt am 125-fachen Umschalten der Auffrischung" | auf **3** reduziert — **derselbe Bug** |

**Was es wirklich war.** Die Entscheidung fiel an zwei Vergleichsblättern,
deren Zellen am Modell nachweislich identisch waren (18 000 000 mm³,
12 Ecken, Glaswolle) — jeder sichtbare Unterschied also reine Darstellung.

*Blatt 1 — kommt es überhaupt vom Schnellzeichnen?* Ja: die Zelle ohne war
richtig, die mit zeigte 8 Ecken und kein Material.

*Blatt 2 — was repariert es?*

| Zelle | repariert mit | Bild |
|---|---|---|
| `1_kontrolle` | nichts | **kaputt** ← Kontrolle, beweist dass der Aufbau misst |
| `2_refresh` | `vc.refresh()` | kaputt |
| `3_aktiv_zyklus` | `set_active`/`set_inactive` | kaputt |
| `4_material_neu` | `ac.set_element_material` | **gut** |

**Cadwork baut die Darstellung eines ELEMENTS erst auf, wenn das Element bei
eingeschalteter Auffrischung angefasst wird.** Ein Neuzeichnen der *Welt*
hilft deshalb nicht — die einzelnen Elemente hatten nie eine Darstellung.

**Der Fix** steht in `_dunkle_elemente_nachziehen`: der Kern sammelt die
Elemente, die bei abgeschaltetem Bildschirm entstehen, und setzt ihnen beim
Wiedereinschalten ihr **eigenes** Material erneut (fachlich ein
Nulldurchgang). Die Liste fällt gratis an — es ist dieselbe
Momentaufnahme-Differenz, die seit 2.1.0 den Undo-Stack füttert.

Validiert mit `_schnellzeichnen_validierung.py --gross` über Menge,
Häppchengrösse und Schalter, je mit Ausklinkung und vier Materialien; alle
acht Fälle stimmen an Modell, Log und Zähler. Entscheidend darin: **120
Bauteile in 6 Häppchen** (die Elemente sammeln sich über Auftragsgrenzen),
**2000 Bauteile** (hält im Grossen), und die Fälle *ohne* Schnellzeichnen,
die nachweislich **nichts** nachziehen — ein normaler Auftrag zahlt den
Preis nicht.

Kosten des Nachziehens: **1,27 s für 2000 Bauteile**, 0,37 s für 480. Das
läuft im Cadwork-Hauptthread, ist also eine Pause; die Dauer steht deshalb
im Log.

**Grenze, bewusst:** Nachgezogen werden nur **neu entstandene** Elemente.
Wer bestehende Bauteile bei abgeschaltetem Bildschirm bloss *ändert*
(Material, Verschieben), wird von einer ID-Differenz nicht erfasst und muss
sich selbst darum kümmern.

**Warum Schnellzeichnen trotzdem nicht Standard ist:** Bei abgeschalteter
Auffrischung sieht man während des Laufs nicht, was entsteht. Das ist eine
bewusste Abwägung und gehört dem Benutzer, nicht dem Programm. Der Schalter
steht im Fenster.

## 12. Dateien

| Datei | Was |
|---|---|
| `cad_plugin/_core/omcad_bridge_core.py` | **die Quelle**: Zustandsmaschine, Protokoll, Threads, Schreiblizenz |
| `cad_plugin/Open MCP CAD {A,B,C,D}/Open MCP CAD X.py` | erzeugte Einstiege, keine Logik |
| `cad_plugin/Open MCP CAD {A,B,C,D}/omcad_bridge_core.py` | erzeugte, byte-identische Kopien |
| `cad_plugin/Open MCP CAD {A,B,C,D}/plugin_info.xml` | erzeugt |
| `cad_plugin/Open MCP CAD {A,B,C,D}/icon.svg` | erzeugt — Cadwork zeigt diese Datei im Plugin-Menü. Das Bild kommt aus `ICON_BILD` im Generator (`assets/icon-64.png`, als PNG ins SVG eingebettet, bei A–F mit Buchstaben-Plakette) |
| `scripts/plugins_generieren.py` | Generator + Gleichheitsprüfung |
| `scripts/connect_client.py` | Status-/Steuerclient für A–D (nur Stdlib) |
| `scripts/verbindungen.py` | Starter: Fenster → Browser → Text |
| `scripts/verbindungen_tk.py` | das Fenster „Open MCP CAD Verbindungen" |
| `scripts/verbindungen_web.py` | Browser-Rückfallebene |
| `tests/test_offline.py` | Offline-Gate, 110 Prüfungen |
| `scripts/deployment_pruefen.py` | Quelle == Userprofil? |
| `scripts/_vorfuehrung.py` | vier Attrappen-Steckplätze auf Testports |
| `scripts/_gui_sondierung.py` | was an Oberflächen-Technik in Cadwork da ist |
| `bridge_client.py` | Kennung, getrennte Zeitgrenzen, `status()`, Lizenzfreigabe |
| `server.py` | reicht `description` durch, neues Tool `get_connection_status` |
| `docs/OPEN_MCP_CAD_CONNECT_testplan_cadwork.md` | manueller Test im echten Cadwork |
