# Open MCP CAD – Schnellstart

Vom ZIP bis zur ersten Wand, die eine KI in Cadwork zeichnet. Ohne
IT-Kenntnisse, in etwa 20 Minuten.

Open MCP CAD verbindet ein KI-Programm (zum Beispiel ChatGPT oder Claude)
mit deinem offenen Cadwork. Du schreibst in normalen Worten, was du willst,
und die KI zeichnet es in Cadwork. Vor jeder Änderung fragt sie dich.
(MCP ist der Name der Brücke, über die ein KI-Programm ein anderes Programm
bedienen darf.)

## 1. Was du brauchst

- Einen Windows-PC mit **Cadwork 3D 2026**.
- Internet während der Installation.
- **Ein KI-Abo**, das du vielleicht schon hast: ChatGPT (Plus oder Pro)
  oder Claude (Pro oder Max). Ein Abo ist ein Monatsbeitrag beim Anbieter.
  Ohne Abo geht es auch mit einem **Schlüssel** – das ist ein Zugangscode
  von der Website des Anbieters, bezahlt wird dann pro Anfrage.

## 2. Installieren (ein Doppelklick)

1. Die ZIP-Datei mit der rechten Maustaste anklicken → **Alle
   extrahieren …** → **Extrahieren**.
2. **Cadwork schliessen.**
3. Im entpackten Ordner **1_INSTALLIEREN.cmd** doppelklicken.
   Fragt Windows, ob du die Datei wirklich ausführen willst: **Ausführen**
   (oder **Weitere Informationen** → **Trotzdem ausführen**).
4. Ein schwarzes Fenster erscheint und arbeitet einige Minuten. Fragen
   beantwortest du mit **Enter** – dann gilt der Vorschlag. Fehlt dem PC
   ein Programmteil, fragt es, ob es ihn holen darf. Das geht auch auf
   Firmen-PCs ohne den Windows-Paketmanager winget: dann lädt es ihn direkt
   beim Hersteller und prüft vorher dessen digitale Unterschrift.
5. Zum Schluss fragt es für jedes gefundene KI-Programm, zum Beispiel
   «Open MCP CAD in Codex eintragen? [J/n]». Mit **Enter** trägt es Open
   MCP CAD dort ein. Vorher legt es eine Sicherungskopie an.
6. Ganz unten unter **Ergebnis** steht jeder Teil einzeln. Steht dort
   «NICHT vollstaendig installiert», stehen die Gründe direkt darüber.

> Tipp: Hast du ein KI-Programm erst später eingerichtet, doppelklicke
> 1_INSTALLIEREN.cmd einfach nochmals. Es trägt nur nach, was fehlt, und
> ändert nichts, was schon stimmt.

## 3. Cadwork verbinden

1. Cadwork starten und eine Datei öffnen (eine neue, leere Datei genügt).
2. Im Plugin-Menü auf **Open MCP CAD** klicken.
3. Oben rechts über der Zeichnung erscheint die kleine **Leiste** von
   Open MCP CAD. Steht dort **Bereit**, ist Cadwork verbunden.

![Die Leiste oben rechts in Cadwork: verbunden und bereit](bilder/monitor.png)

Die Knöpfe der Leiste:

- **Sprechblase**: öffnet darunter den Chat. Der Strich ganz rechts macht
  ihn wieder zur Leiste.
- **Zwei Pfeile**: stellt das Fenster rechts neben die Zeichnung, als
  eigene Spalte. Nochmals klicken löst es wieder.
- **Trennen**: trennt Cadwork von der KI. Danach steht rechts ein **×**,
  das das Fenster schliesst. Ein Klick auf **Open MCP CAD** im Plugin-Menü
  holt es zurück.

## 4. Einen Weg wählen

Es gibt drei Wege, mit der KI zu reden. **Nimm den Weg zu dem KI-Abo, das
du schon hast.** Hast du noch keins: Weg B mit der Codex-App ist bei den
Kollegen am meisten erprobt.

### Weg A: Chat im Plugin mit einem Claude-Abo

Du schreibst direkt in Cadwork, im Chat von Open MCP CAD.

1. Einmal Claude Code einrichten: Windows-Taste drücken, **PowerShell**
   tippen, Enter. Es öffnet sich ein Fenster für Befehle. Dort diese
   Zeile eintippen (oder kopieren) und Enter drücken:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   Das dauert etwa eine Minute und braucht keine Adminrechte. Danach das
   Fenster schliessen, ein **neues** öffnen (wieder **PowerShell**) und
   eintippen:
   ```
   claude
   ```
   Beim ersten Start öffnet sich der Browser: mit deinem Claude-Konto
   anmelden. Danach das Fenster schliessen. Kennt Windows «claude» noch
   nicht, geht es mit dieser Zeile:
   ```
   ~\.local\bin\claude.exe
   ```
   Nur falls die erste Zeile nicht geht (etwa weil ein Firmenrechner sie
   sperrt): Claude Code lässt sich auch mit Node.js einrichten, mit
   `winget install OpenJS.NodeJS.LTS` und danach in einem neuen Fenster
   `npm install -g @anthropic-ai/claude-code`. Fehlt winget, Node.js
   (Version «LTS») von [nodejs.org](https://nodejs.org) installieren.
2. In Cadwork in der Leiste auf die **Sprechblase** klicken. Der Chat
   öffnet sich darunter.
3. Im Chat oben links auf **Ordner wählen** klicken und einen
   Projektordner wählen (nicht das ganze Laufwerk). Dort darf Claude lesen.
4. Unten den Testsatz schreiben (siehe Abschnitt 5) und Enter drücken.

![Der Chat unter der Leiste: du schreibst unten, die KI antwortet und zeichnet](bilder/chat.png)

### Weg B: Codex-App mit einem ChatGPT-Abo

Du schreibst in der Codex-App von OpenAI, Cadwork zeichnet.

1. Im **Microsoft Store** die App **Codex** installieren, starten und mit
   deinem ChatGPT-Konto anmelden.
2. **1_INSTALLIEREN.cmd** (nochmals) doppelklicken und bei «Open MCP CAD
   in Codex eintragen?» mit **Enter** bestätigen.
3. Die Codex-App ganz schliessen und neu starten.
4. In Cadwork auf **Open MCP CAD** klicken (die Leiste zeigt **Bereit**).
5. In der Codex-App einen neuen Chat beginnen und den Testsatz schreiben.
   Fragt Codex, ob es Open MCP CAD benutzen darf: erlauben.

### Weg C: Claude Desktop oder Claude Code mit einem Claude-Abo

Du schreibst in der Claude-App (oder im Befehlsfenster), Cadwork zeichnet.

1. **Claude Desktop** von claude.ai/download installieren, starten und
   anmelden.
2. Claude Desktop ganz beenden (auch unten rechts beim Uhrzeit-Bereich:
   rechte Maustaste auf das Claude-Symbol → **Beenden**), bevor du den
   Installer startest.
3. **1_INSTALLIEREN.cmd** (nochmals) doppelklicken und bei «Open MCP CAD
   in Claude Desktop eintragen?» mit **Enter** bestätigen.
4. Claude Desktop wieder starten. In Cadwork auf **Open MCP CAD** klicken
   (die Leiste zeigt **Bereit**).
5. In Claude den Testsatz schreiben. Fragt Claude, ob es Open MCP CAD
   benutzen darf: erlauben.

Mit **Claude Code** (Weg A, Schritt 1) geht es auch im Befehlsfenster: der
Installer trägt Open MCP CAD dort ebenfalls ein. In einem Projektordner
**claude** eintippen und den Testsatz schreiben.

## 5. Der erste Test

Schreibe der KI:

> Zeichne eine Wand 4 m lang, 2,5 m hoch

Die KI schaut zuerst ins offene Cadwork-Modell. Bevor sie zeichnet, fragt
sie dich (im Plugin-Chat mit **Erlauben** / **Ablehnen**). Solange sie
arbeitet, zeigt oben über Cadwork eine kleine Anzeige, was sie tut, zum
Beispiel **KI zeichnet**. Nach dem Erlauben steht die Wand in Cadwork. Danach kannst du weiterreden, zum
Beispiel «Mach sie 20 cm dick» oder «Setze ein Fenster in die Mitte».

## 6. Wenn es nicht klappt

- **Der Klick auf Open MCP CAD tut nichts:** der Grund steht in der Datei
  `C:\Users\Public\OpenMcpCad_start.log`.
- **Die KI kennt Cadwork nicht:** das KI-Programm ganz schliessen und neu
  starten. Hilft das nicht, 1_INSTALLIEREN.cmd nochmals doppelklicken und
  beim Eintragen mit Enter bestätigen.
- **Die KI sagt, Cadwork sei nicht erreichbar:** in Cadwork auf **Open
  MCP CAD** klicken und warten, bis die Leiste **Bereit** zeigt.
- **Im Plugin-Chat steht «Womit möchtest du chatten?»:** dort den Weg
  wählen, der zu deinem Abo passt; die Knöpfe zeigen den nächsten Schritt.
- **Wenn du eine KI um Hilfe bittest** (etwa «installiere das»): gib
  ihr die Datei `Programmdateien\FUER_KI_ASSISTENTEN.md`. Darin steht,
  was sie tun soll. Will sie zuerst etwas dazubauen (etwa einen
  «Adapter»): nicht nötig, alles ist schon da.
- **Sonst:** schreib uns auf
  [github.com/sebastiankoukoui/open-mcp-cad/issues](https://github.com/sebastiankoukoui/open-mcp-cad/issues)
  oder über [lignoai.ch](https://lignoai.ch). Hänge die Datei
  `C:\Users\Public\OpenMcpCad_start.log` und ein Bildschirmfoto vom
  **Ergebnis** des Installers an.

![Der erste Kontakt im Plugin-Chat, solange noch nichts eingerichtet ist](bilder/willkommen.png)

Mehr (alle Einstellungen, Deinstallation): die ausführliche Anleitung im
Ordner Programmdateien.
