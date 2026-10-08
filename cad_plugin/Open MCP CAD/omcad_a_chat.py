# -*- coding: utf-8 -*-
"""Der Gespraechsteil des A-Dashboards: Claude Code als Kindprozess.

BEWUSST OHNE QT UND OHNE cwapi3d.
Dieses Modul kennt weder Widgets noch Cadwork. Es startet den Kindprozess,
liest seinen Ereignisstrom in einem Nebenthread und legt alles in einfache
Python-Listen. Gezeichnet wird ausschliesslich im Qt-Takt des Dashboards
(`_tab_chat` / `_chat_zeichnen`), genau wie beim Verbindungs-Monitor.

Der Grund ist der Qt-Takt selbst: derselbe Thread zeichnet das Fenster UND
arbeitet die Cadwork-Auftraege ab. Wartet hier jemand auf Claudes Antwort,
laeuft der Takt nicht, der Zeichenauftrag verlaesst die Warteschlange nie,
Claude wartet auf sein Ergebnis — und Cadwork steht.
Deshalb: kein `.wait()`, kein `.communicate()`, kein `readline()` im
Qt-Pfad. Das Pipe-Lesen im Nebenthread ist unbedenklich, es fasst kein
cwapi3d an.

DIE FREIGABE — zwei Schalter, die nur ZUSAMMEN halten (gemessen 2026-08-09)

  --permission-prompt-tool stdio      WER gefragt wird: wir.
  permissions.ask = ["*"]             WAS gefragt wird: alles.

Ohne den zweiten Schalter fragt die Bruecke nur bei Aufrufen, die das CLI
ohnehin fuer genehmigungspflichtig haelt. Ein schlichtes `echo` lief in der
Messung MIT Bruecke genauso still durch wie ohne — ein Gate, das genau bei
den harmlosen Faellen anspringt und beim Rest schweigt. Erst `ask: ["*"]`
macht es lueckenlos; gegengeprueft an einem Befehl, der sonst still
durchlaeuft.

Nicht darauf hereinfallen: `--permission-mode manual` wird im
Kopflos-Betrieb IMMER verworfen (das `init`-Ereignis meldet ausnahmslos
`permissionMode: "default"`), auch zusammen mit der Bruecke und auch als
`permissions.defaultMode`. Der Schalter steht hier deshalb nicht.

Ausfall ist Stillstand, nicht Freifahrt: antwortet niemand — weil Cadwork
zu ist, das Dashboard haengt oder der Nutzer wegklickt — wird der Aufruf
NICHT ausgefuehrt (`tool permission stream closed before response
received`). Das Gate faellt zu, nicht auf.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

# = CHAT_SCHNITTSTELLE im Dashboard; heben bei neuem Bedarf.
# 2 (2026-09-26, Etappe D): `starten` mit `name` und `vorher`, `sitzungen`
# mit `nur_dock`, neu `sitzung_verlauf`, `chat["kontext"]`.
# 3 (2026-09-26, Nacharbeit D): `sitzung_belegt`, `SitzungBelegt`, Feld
# `belegt` in `sitzungen`.
# 4 (2026-09-27, Chatfenster K1): vier Modi (`MODI`, `chat["modus"]`,
# `entscheiden`, `chat_entscheiden`, `gewaehren`) statt `FREIGABE_STUFEN`/
# `automatisch_erlauben`; `freigabe_beantworten(..., sitzung=)`; Ereignisse
# mit `zeit`, Werkzeuge mit `id`, Ergebnisse (`ergebnis`), Ablehnungen ohne
# Frage (`verweigert`).
# 5 (2026-09-27, K3): `starten(..., zusatz=)` — weitere Ordner (`--add-dir`).
# 6 (2026-09-27, K4): `senden(chat, text, anhaenge=)` — Bilder als
# Bild-Bloecke, Text- und andere Dateien als Text (`anhang_inhalt`).
SCHNITTSTELLE = 6

CREATE_NO_WINDOW = 0x08000000

# Vorgabe nach dem Entscheid 2026-08-09: Sonnet 5 mit hoechster Stufe.
# Beides ist im Tab waehlbar — das hier ist nur der Startwert. Seit dem Film
# 2026-09-25 merkt sich das Dock die Wahl in chat.json (`_cli_wahl_merken`
# im Dashboard): vorher stand nach jedem Cadwork-Neustart wieder "sehr hoch"
# da, und der Nutzer musste jedes Mal neu waehlen. Die Vorgabe gilt nur noch,
# wenn nichts (oder nichts Brauchbares) gemerkt ist.
MODELL_VORGABE = "sonnet"
EFFORT_VORGABE = "xhigh"

# Was das Modell ueber die ANZEIGE wissen muss. Befund Film 2026-09-25: der
# Chat schrieb Markdown ("**Staebe**") und teils Englisch — das Dock zeigt
# aber reinen Text, die Sternchen standen woertlich da. Geht als
# `--append-system-prompt` an das CLI (`starten`). Derselbe Wortlaut steht
# als DOCK_ANWEISUNG in omcad_a_anbieter (Schleife und Codex); dieses Modul
# importiert jenes nicht. test_chat_kern M1-M3 pruefen, dass der VOLLE
# Wortlaut in allen drei Wegen ANKOMMT (Befehlszeile bzw. Nutzlast), M4
# vergleicht beide Konstanten aus dem Quelltext — nur beide zusammen aendern.
# Kein Anfuehrungszeichen und kein Prozentzeichen: der Text geht als ein
# Argument durch claude.cmd, also durch cmd.exe (M1 misst, dass er dort
# unversehrt ankommt).
# Gemessen 2026-09-26 am ECHTEN CLI (Haiku 4.5, Schalter wie im Dock, ohne
# Werkzeuge): der Schalter wird angenommen, 5 von 5 Antworten ohne Markdown
# und in der Sprache der Nachricht (deutsch wie englisch), auch auf die
# ausdrueckliche Bitte um Fettdruck. Kontrolle ohne Regel: "# Ueberschrift"
# und "**". Der Wortlaut ist so ausfuehrlich, weil die kuerzeren Fassungen
# messbar nicht hielten: "keine Sternchen fuer Fett" liess "*** X ***" und
# "**EICHE**" durch, und "Sprache des Nutzers" allein beantwortete eine
# englische Frage deutsch.
DOCK_ANWEISUNG = (
    "Deine Antworten erscheinen im Chat des Open-MCP-CAD-Docks in Cadwork, "
    "und der zeigt reinen Text an. Schreib deshalb kein Markdown: keine "
    "Sternchen zum Hervorheben, auch nicht als Verzierung, keine Rauten für "
    "Überschriften, keine Tabellen, keine Backticks und keine Codeblöcke. "
    "Hervorheben geht mit Worten oder Grossbuchstaben, auch wenn der "
    "Nutzer ausdrücklich um Fettdruck bittet. Aufzählungen mit einem "
    "einfachen Bindestrich oder mit Nummern, Code als schlichte Zeilen. "
    "Antworte immer in der Sprache des Nutzers, also in der Sprache seiner "
    "letzten Nachricht: auf eine deutsche deutsch, auf eine englische "
    "englisch, auf eine französische französisch. Das gilt auch, wenn "
    "Werkzeuge, Fehlermeldungen oder Unterlagen englisch sind. "
    # Rueckmeldung 2026-09-28: im Modus Nur lesen bekam die KI nur "nicht
    # erneut versuchen" und suchte andere Wege. Ohne Anfuehrungszeichen und
    # Guillemets: der Text geht durch claude.cmd, also durch cmd.exe.
    "Im Modus Nur lesen lehnt der Chat jeden Aufruf ab, der etwas ändert. "
    "Der Nutzer sieht dann im Chat einen Hinweis und kann den Modus mit "
    "einem Klick wechseln. Versuch es in dem Fall nicht auf einem anderen "
    "Weg, sondern sag dem Nutzer kurz, was du tun wolltest.")
# Rueckmeldung 2026-08-15: "model fable 5 ist zb nicht auswaehlbar wieso nicht? oder
# weitere modelle so wie im claude desktop app wie zb opus 4.7 opus 4.6"
#
# Fable fehlte schlicht — die CLI-Hilfe nennt es woertlich als gueltigen
# Kurznamen ("an alias for the latest model (e.g. 'fable', 'opus', or
# 'sonnet')"). Es steht jetzt drin.
#
# AELTERE Fassungen (opus 4.7, 4.6 …): welche genau dieses CLI annimmt, ist
# hier NICHT belegbar — es gibt keinen Befehl, der die Liste ausgibt, und
# raten waere das Schlechteste. Deshalb ist das Auswahlfeld BESCHREIBBAR:
# Der Nutzer kann jeden vollen Namen eintippen (`claude-opus-4-7`). Nimmt das CLI
# ihn nicht, steht der Grund jetzt im Chat — dafuer ist der stderr-Leser da.
# Die Werte sind Kurznamen: das CLI nimmt dafuer immer das NEUESTE Modell der
# Familie. Nur die Beschriftung altert — Stand 2026-09-24.
MODELLE = (("Sonnet 5", "sonnet"), ("Opus 5.5", "opus"),
           ("Fable 5.1", "fable"), ("Haiku 4.5", "haiku"))
# Rueckmeldung 2026-08-09: "xhigh" sagte ihm nichts. Die Werte gehen unveraendert
# ans CLI, angezeigt wird Deutsch.
EFFORT_STUFEN = (("niedrig", "low"), ("mittel", "medium"), ("hoch", "high"),
                 ("sehr hoch", "xhigh"), ("maximal", "max"),
                 # Ultracode ist keine weitere Stufe, sondern "xhigh plus
                 # staendige Mehr-Agenten-Arbeit". --effort nimmt den Wert an
                 # (gemessen 2026-08-09: das Modell zitiert dann "Ultracode is
                 # on: optimize for the most exhaustive..."; die Kontrollzelle
                 # ohne Schalter antwortete "NICHT VORHANDEN").
                 ("Ultracode (Mehr-Agenten)", "ultracode"))

# --- Freigabe-Politik: vier Modi (2026-09-27) --------------------------------
# Rueckmeldung 2026-08-09: "musste andauernd alles genehmigen". Die Loesung ist NICHT,
# die Bruecke zu lockern — `permissions.ask = ["*"]` bleibt, damit wirklich
# JEDER Aufruf hier ankommt. Entschieden wird HIER, im eigenen Code, fuer ALLE
# drei Wege (dieses CLI, die Schleife und Codex in omcad_a_anbieter, dem die
# Entscheidung hereingereicht wird): Harmloses geht sofort, Verbotenes wird
# sofort abgelehnt, der Rest kommt als Karte.
#
# Der Unterschied ist wichtig: waeren die harmlosen Werkzeuge stattdessen in
# der CLI-Konfiguration erlaubt, saehen wir sie gar nicht mehr. So bleibt
# jeder Aufruf sichtbar — automatisch erlaubte und abgelehnte stehen im
# Verlauf.

# Nur Lesen und Suchen, kein Seiteneffekt, verlaesst den Rechner nicht.
# Am 2026-08-09 an der echten Werkzeugliste einer Sitzung durchgegangen.
NUR_LESEND = {
    "Read", "Glob", "Grep", "ToolSearch", "NotebookRead", "TodoWrite",
    "TaskList", "TaskGet", "TaskOutput", "CronList",
    "ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool",
    "EnterPlanMode", "ExitPlanMode",
    # Fragt den Nutzer selbst — eine Karte davor waere eine Frage vor der Frage.
    "AskUserQuestion", "ReportFindings",
    # Laedt nur Anleitungstext; jede Handlung daraus kommt einzeln als
    # eigene Anfrage und wird dort gefragt.
    "Skill",
}
# Praefix der Werkzeuge dieses MCP-Servers. Heisst der Server in der
# Host-Konfiguration anders (z.B. `open-mcp-cad-b` fuer Steckplatz B),
# deckt der Praefix ohne abschliessende Unterstriche auch den ab.
MCP_PRAEFIX = "mcp__open-mcp-cad"

# Die Werkzeuge des Servers (open_mcp_cad/server.py), die NUR lesen: das
# Dokument, den Briefkasten, die Ablage, das Nachschlagewerk, die
# Erfahrungen. Alles andere auf diesem Server gilt als AENDERND — auch ein
# Werkzeug, das es hier noch nicht gibt (Regel: im Zweifel fragen); lesend
# ist dort nur, was eine Erweiterung so erklaert (unten). test_chat_kern
# liest die Werkzeugnamen aus server.py und verlangt, dass jeder Name hier
# dort existiert (ein Tippfehler machte ein Lese-Werkzeug zu einem
# aendernden).
CADWORK_LESEND = {
    "get_document_info", "get_connection_status", "get_pending_messages",
    "list_stored_keys", "get_cadwork_api_help", "get_working_examples",
    "get_detail", "get_experiences",
}

# Werkzeuge aus Erweiterungen (OPEN_MCP_CAD_ERWEITERUNGEN, seit 2026-10-01)
# laufen auf DEMSELBEN Server und gelten wie jedes unbekannte Werkzeug dort
# als AENDERND. Nur lesend ist eines nur, wenn die Erweiterung es so erklaert
# hat — dann erzwingt der Server (open_mcp_cad/erweiterungen.py) diesen
# Namen: Praefix plus Muster, und ein aenderndes darf den Praefix nicht
# tragen. Dieselben zwei Werte stehen dort (LESEND_PRAEFIX, NAME_MUSTER);
# test_chat_kern EP5 vergleicht sie aus dem Quelltext. Das Muster schliesst
# Doppel-Unterstriche, Grossbuchstaben und Leerzeichen aus (EP3).
ERWEITERUNG_LESEND_PRAEFIX = "lesen_"
ERWEITERUNG_NAME = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
_ERWEITERUNG_NAME = re.compile(ERWEITERUNG_NAME)


def _erweiterung_lesend(kurz):
    """Ist `kurz` ein als nur lesend erklaertes Werkzeug einer Erweiterung?"""
    return (kurz.startswith(ERWEITERUNG_LESEND_PRAEFIX)
            and len(kurz) > len(ERWEITERUNG_LESEND_PRAEFIX)
            and _ERWEITERUNG_NAME.fullmatch(kurz) is not None)


def _server_werkzeug(werkzeug):
    """Der kurze Name, wenn `werkzeug` zu DIESEM Server gehoert — sonst None.

    `mcp__open-mcp-cad__get_document_info` -> `get_document_info`, auch fuer
    `mcp__open-mcp-cad-b__…` (der Praefix haengt am Servernamen der
    Host-Konfiguration, s. MCP_PRAEFIX). Ein fremder Server, dessen Name nur
    so ANFAENGT (`open-mcp-cadx`), gehoert nicht dazu."""
    if not isinstance(werkzeug, str) or not werkzeug.startswith(MCP_PRAEFIX):
        return None
    teile = werkzeug.split("__", 2)
    if len(teile) != 3:
        return None
    server = teile[1]
    if server != "open-mcp-cad" and not server.startswith("open-mcp-cad-"):
        return None
    return teile[2]


def werkzeug_art(werkzeug):
    """"lesen", "cadwork" (aendert in Cadwork, ueber die Bruecke) oder
    "aussen" (alles andere: Befehle am Rechner, Dateien schreiben, Web,
    fremde MCP-Server — auch einer, der "cadwork" im Namen traegt: bis
    2026-09-27 galt so ein Name als Cadwork; seit es "Cadwork frei" gibt,
    hiesse das, ein FREMDES Werkzeug ohne Frage laufen zu lassen).

    Kein Text (None, eine Liste aus kaputtem JSON) ist "aussen": vorher warf
    `werkzeug in NUR_LESEND` bei einer Liste TypeError (Gegenpruefung
    2026-09-28)."""
    if not isinstance(werkzeug, str):
        return "aussen"
    if werkzeug in NUR_LESEND:
        return "lesen"
    kurz = _server_werkzeug(werkzeug)
    if kurz is None:
        return "aussen"
    if kurz in CADWORK_LESEND or _erweiterung_lesend(kurz):
        return "lesen"
    return "cadwork"


def ist_cadwork(werkzeug):
    """Aendert `werkzeug` etwas in Cadwork (ueber die Bruecke)?"""
    return werkzeug_art(werkzeug) == "cadwork"


# Die vier Modi (Wunsch 2026-09-27). (Wert, Anzeige, Zeichen, was er heisst.)
# Die WERTE sind neu — nicht die alten Stufen: das alte "cadwork" hiess "nur
# Cadwork fragen", also das Gegenteil von "Cadwork frei" (Regel 4: ein Name,
# der entscheidet, ist Logik). Der Chat liest `chat["modus"]`, nie mehr
# `freigabe_stufe`.
MODI = (
    ("nur_lesen", "Nur lesen", "🔍",
     "Liest das Dokument und schlägt nach. Alles, was Cadwork oder Dateien "
     "ändert, und alles ausserhalb wird abgelehnt, ohne zu fragen."),
    ("fragen", "Fragen", "✋",
     "Fragt vor jeder Änderung, einmal je Art bis zu deiner nächsten "
     "Nachricht."),
    ("cadwork_frei", "Cadwork frei", "🔨",
     "Arbeitet in Cadwork ohne Rückfrage. Befehle am Rechner, Dateien und "
     "Web fragen wie bei «Fragen», einmal je Art bis zu deiner nächsten "
     "Nachricht."),
    # Rueckmeldung 2026-08-15, ausdruecklich als wichtig markiert: "soll ein
    # modus geben wo nichts bestaetigt werden muss". Die BRUECKE bleibt auch
    # hier: sie wird im Leserthread sofort selbst bejaht, und jeder Aufruf
    # steht weiter im Verlauf — nur eben erst, nachdem er passiert ist.
    ("alles_auto", "Alles automatisch", "⚡",
     "Nichts wird gefragt. Du siehst jeden Schritt erst danach im Verlauf."),
)
MODUS_WERTE = tuple(m[0] for m in MODI)
MODUS_VORGABE = "fragen"
# "Alles automatisch" bleibt nie ueber einen Cadwork-Neustart (Sicherheits-
# entscheid 2026-09-26, bestaetigt 2026-09-27): gemerkt wird dann dieser.
MODUS_NIE_MERKEN = "alles_auto"
MODUS_STATT_AUTO = "cadwork_frei"


def entscheiden(modus, werkzeug, anfrage=None, gewaehrt=()):
    """"ja" (ohne Karte), "nein" (abgelehnt, ohne zu fragen) oder "fragen".

    EINE Politik fuer alle Wege. Bewusst ohne Auslegung des Befehls: ein
    `Bash` kann alles sein, von `git status` bis `rm -rf`.

    `anfrage`: die Anfrage des CLI. Meldet es `blocked_path` (der Aufruf
    greift aus dem Arbeitsordner heraus), ist auch ein "harmloses" Read nicht
    mehr harmlos — es koennte Zugangsdaten in den Verlauf holen.
    `gewaehrt`: Werkzeugarten, die der Nutzer auf einer Karte schon
    freigegeben hat (bis zur naechsten Nachricht bzw. fuer die Sitzung).
    Ein unbekannter Modus fragt — nie mehr Freiheit als gewaehlt.

    Streng geordnet (Entscheid Orchestrator 2026-09-28): Nur lesen ⊂ Fragen
    ⊂ Cadwork frei ⊂ Alles automatisch — fuer JEDES Werkzeug, jede Anfrage
    und jede Gewaehrung laesst ein spaeterer Modus mindestens so viel durch
    wie ein frueherer (nein < fragen < ja). "Cadwork frei" behandelt das
    Aeussere deshalb genau wie "Fragen" (einmal je Art); bis K7 fragte es
    dort jedes Mal und war damit strenger als "Fragen". test_chat_kern MN1.
    """
    # 'alles_auto' heisst wirklich alles — auch Cadwork, auch ausserhalb des
    # Ordners. Er steht VOR allen Grenzen, sonst waere er keiner.
    if modus == "alles_auto":
        return "ja"
    art = werkzeug_art(werkzeug)
    draussen = bool((anfrage or {}).get("blocked_path"))
    if modus == "nur_lesen":
        return "ja" if art == "lesen" and not draussen else "nein"
    if draussen:
        return "fragen"          # jedes Mal, keine Gewaehrung je Art
    if art == "lesen":
        return "ja"
    if modus == "cadwork_frei" and art == "cadwork":
        return "ja"
    # Nur Text kann gewaehrt sein: ein kaputter Name (Liste) warf hier
    # TypeError im Leserthread (gefunden von MN1, 2026-09-28).
    if modus in ("fragen", "cadwork_frei") and isinstance(werkzeug, str) \
            and werkzeug in (gewaehrt or ()):
        return "ja"
    return "fragen"


def modus_von(chat):
    """Der Modus, nach dem `chat` gerade entscheidet (unbekannt -> Vorgabe
    fuer die ANZEIGE; die Politik selbst fragt dann bei allem)."""
    modus = (chat or {}).get("modus", MODUS_VORGABE)
    return modus if modus in MODUS_WERTE else MODUS_VORGABE


def gewaehrt_von(chat):
    """Die Arten, die der Nutzer freigegeben hat: bis zur naechsten Nachricht
    (`gewaehrt_zug`) und fuer die Sitzung (`gewaehrt_sitzung`)."""
    return (set((chat or {}).get("gewaehrt_zug") or ())
            | set((chat or {}).get("gewaehrt_sitzung") or ()))


def chat_entscheiden(chat, werkzeug, anfrage=None):
    """`entscheiden` mit dem Modus und den Gewaehrungen dieses Chats.

    DAS reicht das Dashboard an omcad_a_anbieter herein (Schleife, Codex);
    `_einordnen` ruft es fuer das CLI. Der Modus wird bei JEDER Entscheidung
    neu gelesen: ein Wechsel mitten im Chat gilt ab dem naechsten Aufruf.
    """
    return entscheiden((chat or {}).get("modus", MODUS_VORGABE), werkzeug,
                       anfrage, gewaehrt_von(chat))


def gewaehren(chat, werkzeug, sitzung=False):
    """Eine Art freigeben: bis zur naechsten Nachricht, mit `sitzung` bis der
    Chat endet. Die Menge gehoert zum Chat (neu je Start)."""
    if not werkzeug:
        return
    chat.setdefault("gewaehrt_zug", set()).add(werkzeug)
    if sitzung:
        chat.setdefault("gewaehrt_sitzung", set()).add(werkzeug)


#: Was das MODELL hoert, wenn der Modus einen Aufruf ohne Frage ablehnt.
#: Rueckmeldung 2026-09-28: "Nicht erneut versuchen; frag den Nutzer" liess
#: die KI ratlos — sie wusste nicht, dass der Nutzer einen Hinweis sieht und
#: den Modus mit einem Klick wechseln kann. Dieselbe Vorlage steht in
#: omcad_a_anbieter (Schleife); test_chat_kern SP4 vergleicht beide aus dem
#: Quelltext. Codex bekommt bei "decline" keinen Text (das Schema kennt dort
#: kein Feld), dort traegt DOCK_ANWEISUNG dasselbe.
ABLEHNUNG_VORLAGE = (
    "Abgelehnt, ohne den Nutzer zu fragen: Im Modus «%(modus)s» ist "
    "%(werkzeug)s gesperrt, weil es etwas ändern oder ausserhalb des "
    "Arbeitsordners zugreifen würde. Der Nutzer sieht dazu jetzt im Chat "
    "einen Hinweis und kann dort mit einem Klick in den Modus «Fragen» "
    "wechseln. Versuch es nicht erneut und nicht auf einem anderen Weg. Sag "
    "dem Nutzer stattdessen in ein, zwei Sätzen, was du tun wolltest und "
    "warum — dann entscheidet er.")


def werkzeug_kurz(werkzeug):
    """Der Name ohne MCP-Praefix (`mcp__server__name` -> `name`)."""
    roh = str(werkzeug or "?")
    return roh.split("__")[-1] if roh.startswith("mcp__") else roh


def ablehnung_text(modus, werkzeug):
    """Was das MODELL hoert, wenn ein Aufruf ohne Frage abgelehnt wird."""
    anzeige = dict((m[0], m[1]) for m in MODI).get(modus, modus)
    return ABLEHNUNG_VORLAGE % {"modus": anzeige,
                                "werkzeug": werkzeug_kurz(werkzeug)}


def ereignis(art, **felder):
    """Ein Eintrag fuer den Verlauf — mit Zeit (fuer die Zeitmarken im Dock)."""
    felder["art"] = art
    felder.setdefault("zeit", time.time())
    return felder


# Der Name, mit dem das Dock JEDE neue Sitzung kennzeichnet (`-n`). Die
# Chatliste im Dock zeigt nur Sitzungen mit diesem Namen (`sitzungen`,
# `nur_dock`): vorher standen dort auch die Terminal-Sitzungen desselben
# Ordners (Plan B.7) — und eine davon im Dock fortzusetzen, waehrend sie im
# Terminal laeuft, hiesse zwei Prozesse an einer Sitzungsdatei. Fester
# Text ohne Nutzereingabe: er geht durch claude.cmd, also durch cmd.exe
# (keine Anfuehrungszeichen, kein Prozent). Im Terminal steht er im
# /resume-Picker — dort sagt er, woher die Sitzung kommt.
SITZUNG_NAME = "Open MCP CAD"

# Kopf- und Schwanzfenster der Sitzungsdateien. Die groesste gemessene Datei
# hatte 13,9 MB (2026-08), am 2026-09-25 schon 15,3 MB — sie darf NIE ganz
# gelesen werden, schon gar nicht im Qt-Takt.
KOPF_BYTES = 256 * 1024
SCHWANZ_BYTES = 1024 * 1024

# Anfaenge, die als Bezeichnung einer Sitzung nichts taugen. Alle im
# Bestand belegt (Messung 2026-08-09 ueber 25 Sitzungsdateien).
UNBRAUCHBAR = (
    "<command-name>", "<local-command-stdout>", "<system-reminder>",
    "<bash-input>", "Caveat: The messages below", "[Request interrupted",
    "This session is being continued from a previous",
)


# --- Wo das CLI liegt -----------------------------------------------------

def cli_kandidaten():
    """Wo Claude Code liegen kann, in der Reihenfolge, in der gesucht wird.

    Seit 2026-09-29 auch der Installer, den Anthropic heute empfiehlt
    (`irm https://claude.ai/install.ps1 | iex`, ohne Node, ohne
    Adminrechte): er legt `claude.exe` nach `%USERPROFILE%\\.local\\bin`
    (so die Anleitung von Anthropic, auch fuer die Deinstallation). Vorher
    fand der Chat nur `claude.cmd` von npm. Reihenfolge:

      1. `~\\.local\\bin\\claude.exe` (eigener Installer; die Anleitung von
         Anthropic empfiehlt ihn, wenn beide da sind),
      2. `%APPDATA%\\npm\\claude.cmd` (npm),
      3. `claude.exe`, dann `claude.cmd` auf dem PATH.

    Feste Orte VOR dem PATH: Cadwork erbt seinen PATH beim Start — wer
    Claude Code bei offenem Cadwork einrichtet, faende es sonst erst nach
    einem Neustart. Nie `claude.ps1` (braucht eine PowerShell) und nie das
    blosse `claude` von npm (ein sh-Skript). Dieselbe Reihenfolge hat
    `open_mcp_cad.ki_eintragen.claude_programm` (test_chat_kern CX
    vergleicht beide in denselben Welten).
    """
    heim = os.path.expanduser("~")
    return [("datei", os.path.join(heim, ".local", "bin", "claude.exe")),
            ("datei", os.path.join(os.environ.get("APPDATA", ""), "npm",
                                   "claude.cmd")),
            ("path", "claude.exe"), ("path", "claude.cmd")]


def cli_pfad():
    """Der volle Pfad auf Claude Code: `claude.exe` oder `claude.cmd`
    (s. `cli_kandidaten`). Wirft FileNotFoundError, wenn keins da ist.

    Gemessen 2026-09-29 am `claude.exe` 2.1.263 (dasselbe Programm, das
    npm heute unter node_modules mitbringt und das `claude.cmd` startet),
    mit einem Heim in Temp: als Kindprozess ohne cmd.exe, mit
    CREATE_NO_WINDOW und stream-json startet es, schickt `init` und
    antwortet; Argumente mit & | < > ^ % ! " und Umlauten kommen woertlich
    an. Das `claude.exe` des eigenen Installers selbst ist auf dem
    Entwicklungsrechner NICHT installiert, also nicht gemessen.
    """
    for art, wert in cli_kandidaten():
        if art == "datei":
            if os.path.isabs(wert) and os.path.isfile(wert):
                return wert
            continue
        auf_path = shutil.which(wert)
        if auf_path:
            return auf_path
    # Ohne Claude Code gibt es keinen Chat — der Rest (Verbinden, MCP fuer
    # ChatGPT/Codex/Claude Desktop) laeuft trotzdem. Vorher kam hier nur
    # "[WinError 2]" im Tab an.
    raise FileNotFoundError(
        "Claude Code ist nicht installiert (weder claude.exe noch claude.cmd "
        "gefunden). Der Chat-Tab braucht es; Verbinden und die "
        "MCP-Werkzeuge fuer andere KI-Programme funktionieren ohne.")


def mcp_python():
    """Das Python des MCP-Servers — eines, in dem `open_mcp_cad` installiert ist.

    Zuerst die Umgebungsvariable OPEN_MCP_CAD_PYTHON (voller Pfad auf
    python.exe); ist sie gesetzt, gilt NUR sie — ein ausdruecklicher Pfad,
    der nicht stimmt, soll auffallen, nicht still ersetzt werden. Sonst
    das Micromamba-Env `open-mcp-cad` im Benutzerordner.

    Gezaehlt wird ein Python nur, wenn pip dort `open_mcp_cad` verbucht
    hat (`open_mcp_cad-*.dist-info`, auch bei `pip install -e`). Bis
    2026-09-22 genuegte "python.exe existiert" — und der Chat startete den
    Server aus dem Arbeitsordner, also einem fremden Repo. Wird nichts
    gefunden, laeuft der Chat ohne Cadwork-Werkzeuge weiter und sagt es.
    """
    gesetzt = os.environ.get("OPEN_MCP_CAD_PYTHON", "").strip().strip('"')
    pfad = gesetzt or os.path.join(os.path.expanduser("~"), "micromamba",
                                   "envs", "open-mcp-cad", "python.exe")
    if not os.path.isfile(pfad):
        return None
    # Conda/Micromamba: python.exe neben Lib\. venv (so richtet es der
    # Installer der Verteilung ein): python.exe in Scripts\, Lib\ eine
    # Ebene hoeher.
    ordner = os.path.dirname(pfad)
    paket = [t for basis in (ordner, os.path.dirname(ordner))
             for t in glob.glob(os.path.join(basis, "Lib", "site-packages",
                                             "open_mcp_cad-*.dist-info"))]
    return pfad if paket else None


# Das eingehaengte Fachwissen des Servers (OPEN_MCP_CAD_KNOWLEDGE). Wie der
# Arbeitsordner: ein Verweis auf ein FREMDES Verzeichnis gehoert in die
# Konfiguration, nicht in den Quelltext (dieses Repo wird oeffentlich).
WISSEN_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "wissensordner.txt")


def wissensordner():
    """Die Fachwissens-Ordner fuer den Server, `;`-getrennt — oder None.

    Zuerst die Umgebungsvariable OPEN_MCP_CAD_KNOWLEDGE, sonst die Datei
    `wissensordner.txt` neben dem Plugin (ein Ordner je Zeile). Nur Ordner,
    die es gibt: der Server wuerde fehlende zwar ueberspringen, aber seine
    Meldung darueber sieht im Chat niemand. None heisst: nur das
    eingebaute cwapi3d-Wissen — die Oberflaeche sagt es.
    """
    roh = os.environ.get("OPEN_MCP_CAD_KNOWLEDGE", "")
    teile = roh.split(os.pathsep) if roh.strip() else []
    if not teile:
        try:
            with open(WISSEN_DATEI, encoding="utf-8") as fh:
                teile = fh.read().splitlines()
        except OSError:
            teile = []
    da = [t.strip().strip('"') for t in teile
          if t.strip() and os.path.isdir(t.strip().strip('"'))]
    return os.pathsep.join(da) or None


def server_befehl(port, dokument=None):
    """(Befehl, Umgebung) des MCP-Servers fuer DIESEN Steckplatz — oder None.

    Gestartet wird `python -m open_mcp_cad.server` — unabhaengig vom
    Arbeitsordner. Vorher war es `<Arbeitsordner>\\server.py`: Arbeitsort
    des Chats und Herkunft des Servers hingen an EINER Variable, und so
    lief der alte Server eines fremden Repos, der die Variablen dieses
    Plugins gar nicht kennt (immer Port 53127, kein Dokument-Riegel).

    Eine Quelle fuer BEIDE Wege: die Konfiguration des Claude-CLI
    (`mcp_konfig_schreiben`) und die eigene Schleife der anderen Anbieter
    (omcad_a_anbieter), die den Server selbst startet. `dokument` setzt den
    Riegel `OPEN_MCP_CAD_EXPECT_DOC`; beim CLI steht er in dessen Umgebung
    und wird vererbt.

    None heisst: kein Server-Python gefunden — dann laeuft der Chat ohne
    Cadwork-Werkzeuge, statt mit einer kaputten Konfiguration zu scheitern.
    """
    py = mcp_python()
    if py is None:
        return None
    # pythonw.exe, wenn es daneben liegt: python.exe ist ein Konsolenprogramm
    # und oeffnet bei jedem Start ein schwarzes Fenster (2026-09-24,
    # gemessen an den Codex-Eintraegen). Als stdio-Server laeuft pythonw
    # gleich (Handshake: 15 Werkzeuge).
    ohne_fenster = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.isfile(ohne_fenster):
        py = ohne_fenster
    umgebung = {"OPEN_MCP_CAD_PORT": str(port)}
    wissen = wissensordner()
    if wissen:
        umgebung["OPEN_MCP_CAD_KNOWLEDGE"] = wissen
    if dokument:
        umgebung["OPEN_MCP_CAD_EXPECT_DOC"] = dokument
    # Erweiterungen des Servers (seit 2026-10-01): ausdruecklich
    # weitergereicht, nicht nur vererbt — ob ein Host `env` zur Umgebung
    # hinzufuegt oder sie ersetzt, entscheidet er, nicht wir.
    erweiterungen = os.environ.get("OPEN_MCP_CAD_ERWEITERUNGEN", "").strip()
    if erweiterungen:
        umgebung["OPEN_MCP_CAD_ERWEITERUNGEN"] = erweiterungen
    return [py, "-m", "open_mcp_cad.server"], umgebung


def mcp_konfig_schreiben(port):
    """Die MCP-Konfiguration des Claude-CLI fuer genau DIESEN Steckplatz.

    Damit bekommt der Chat die Cadwork-Werkzeuge: Briefkasten lesen,
    Pruefhinweise melden, zeichnen. Der Port steht drin, damit der Server
    dieselbe Leitung nimmt wie das Dashboard. None = kein Server-Python.
    """
    server = server_befehl(port)
    if server is None:
        return None
    befehl, umgebung = server
    ziel = os.path.join(tempfile.gettempdir(),
                        "open_mcp_cad_%s.json" % port)
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump({"mcpServers": {"open-mcp-cad": {
            "command": befehl[0], "args": befehl[1:],
            "env": umgebung}}}, fh)
    return ziel


#: Laenger wird der Ordnername nicht; der Rest geht in eine Pruefsumme
#: (`projekt_ordner`). Gemessen 2026-09-26 am CLI 2.1.263.
PROJEKT_NAME_MAX = 200


def _utf16(text):
    """Die UTF-16-Einheiten von `text` — so zaehlt das CLI (JavaScript)."""
    roh = text.encode("utf-16-le", "surrogatepass")
    return [int.from_bytes(roh[i:i + 2], "little")
            for i in range(0, len(roh), 2)]


def _pruefsumme(text):
    """djb2 ueber UTF-16-Einheiten, 32 Bit mit Vorzeichen, Betrag zur Basis 36."""
    h = 0
    for einheit in _utf16(text):
        h = ((h << 5) - h + einheit) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    h = abs(h)
    ziffern = "0123456789abcdefghijklmnopqrstuvwxyz"
    aus = ""
    while True:
        h, rest = divmod(h, 36)
        aus = ziffern[rest] + aus
        if not h:
            return aus


def projekt_ordner(arbeitsordner):
    """Der `projects`-Unterordner, in dem die Sitzungen dieses Repos liegen.

    Claude Code bildet den Ordnernamen aus dem `cwd`: JEDES Zeichen ausser
    a-z, A-Z und 0-9 wird zu `-`. Deshalb entscheidet das `cwd` beim
    Starten, in welcher Liste eine neue Sitzung landet — startet das
    Dashboard woanders, tauchen die Chats in einer fremden Liste auf.

    Bis 2026-09-26 wurden nur Backslash, `/` und `:` ersetzt. Gemessen am
    Bestand (`~/.claude/projects`, je Ordner das `cwd` aus den
    Sitzungsdateien): die Regel hier traf 38 von 38 Ordnern, die alte 10.
    Ein Arbeitsordner mit Punkt (`.claude`), Leerzeichen oder Unterstrich
    zeigte also auf eine leere Liste.

    Gemessen 2026-09-26 am echten CLI 2.1.263 (Etappe D, ohne Werkzeuge):
    - Gezaehlt wird in UTF-16-Einheiten wie in JavaScript. Ein Zeichen
      ausserhalb von Ebene 0 (ein Emoji) wird zu ZWEI `-`
      ("Seeblick 🌲 Dach" -> "Seeblick----Dach").
    - Ueber PROJEKT_NAME_MAX Zeichen: die ersten 200, dann `-` und eine
      Pruefsumme des ganzen Pfads (djb2, Basis 36; zwei Messungen, zwei
      Treffer, z. B. "...-Wand-Erd-vnmcix").
    """
    einheiten = _utf16(arbeitsordner)
    marke = "".join(chr(e) if chr(e).isascii() and chr(e).isalnum() else "-"
                    for e in einheiten)
    if len(marke) > PROJEKT_NAME_MAX:
        marke = "%s-%s" % (marke[:PROJEKT_NAME_MAX],
                           _pruefsumme(arbeitsordner))
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", marke)


# --- Sitzungsliste --------------------------------------------------------

def _text_aus(inhalt):
    """`message.content` ist ENTWEDER ein String ODER eine Liste von Bloecken.

    Ohne diese Fallunterscheidung landet die JSON-Darstellung eines
    `tool_result` als Sitzungsname in der Liste — gemessen sind die meisten
    Eintraege Listen, nicht Strings.
    """
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        for blk in inhalt:
            if isinstance(blk, dict) and blk.get("type") == "text":
                return blk.get("text") or ""
    return ""


def _bloecke(pfad, groesse):
    """Genau zwei Bloecke je Datei: Kopf und Schwanz. Nie die ganze Datei."""
    with open(pfad, "rb") as fh:
        kopf = fh.read(KOPF_BYTES)
        schwanz = b""
        if groesse > KOPF_BYTES:
            fh.seek(max(KOPF_BYTES, groesse - SCHWANZ_BYTES))
            schwanz = fh.read()
    return kopf, schwanz


def _titel_zeilen(block, schluessel, feld):
    """Die Werte von `feld` aller Zeilen, die mit `schluessel` beginnen —
    von hinten nach vorn (der letzte zuerst)."""
    stelle = block.rfind(schluessel)
    while stelle != -1:
        ende = block.find(b"\n", stelle)
        zeile = block[stelle:ende if ende != -1 else len(block)]
        try:
            wert = (json.loads(zeile.decode("utf-8")) or {}).get(feld)
            if wert:
                yield str(wert).strip()
        except Exception:                               # noqa: BLE001
            pass
        stelle = block.rfind(schluessel, 0, stelle)


def _titel(kopf, schwanz):
    """Der zuletzt gesetzte Titel — Schwanz VOR Kopf.

    Titel werden nicht einmal geschrieben, sondern bei jedem Sitzungswechsel
    neu angehaengt (in einer Datei 326-mal). Es gilt der LETZTE. Wer nur den
    Kopf liest, zeigt bei 7 von 25 Dateien einen veralteten Namen an — wer
    nur den Schwanz liest, verliert den Titel einer Datei, deren einziger
    Eintrag 13,7 MB vor dem Ende steht. Also beides, Schwanz zuerst.

    Die Kennzeichnung der Dock-Sitzungen (SITZUNG_NAME) ist KEIN Titel: sie
    steht in jeder Dock-Sitzung gleich da. Dann gilt die erste Frage.
    """
    for schluessel, feld in ((b'{"type":"custom-title"', "customTitle"),
                             (b'{"type":"ai-title"', "aiTitle")):
        for block in (schwanz, kopf):
            for wert in _titel_zeilen(block, schluessel, feld):
                if wert != SITZUNG_NAME:
                    return wert
    return ""


def _ist_dock(kopf, schwanz):
    """Hat das Dock diese Sitzung angelegt (Name SITZUNG_NAME, `-n`)?

    Gemessen 2026-09-26 am CLI 2.1.263: `-n` schreibt `custom-title` (und
    `agent-name`) als ERSTE Zeilen der Datei, also immer in den Kopf, und
    nach jedem Zug erneut; ein `--resume` ohne `-n` laesst die ersten
    stehen. Die Datei wird nur angehaengt: benennt jemand die Sitzung im
    Terminal um, kommt ein neuer `custom-title` dazu, der erste bleibt im
    Kopf. Gesucht wird deshalb nur `custom-title`. `agent-name` zaehlte bis
    zur Nacharbeit D mit, entschied aber in keinem gemessenen Fall etwas
    (Mutant C4 der Pruefung).
    """
    schluessel = b'{"type":"custom-title"'
    for block in (kopf, schwanz):
        if any(w == SITZUNG_NAME
               for w in _titel_zeilen(block, schluessel, "customTitle")):
            return True
    return False


def _erste_frage(kopf):
    """Rueckfall, wenn eine Sitzung gar keinen Titel hat.

    Die erste ZEILE ist nie die erste Nutzerfrage (gemessen: 25 von 25) —
    davor stehen `queue-operation`, `custom-title` oder `ai-title`. Es wird
    also gesucht, nicht auf einen festen Index gegriffen.
    """
    for zeile in kopf.split(b"\n")[:-1]:        # letzte Zeile kann halb sein
        try:
            ev = json.loads(zeile.decode("utf-8"))
        except Exception:                       # noqa: BLE001
            continue
        if ev.get("type") != "user" or ev.get("isMeta"):
            continue
        text = _text_aus((ev.get("message") or {}).get("content")).strip()
        if text and not text.startswith(UNBRAUCHBAR):
            return " ".join(text.split())[:90]
    return ""


def sitzungen(arbeitsordner, cache=None, nur_dock=False):
    """Die Sitzungen dieses Projekts, neueste zuerst.

    `cache` ist ein Dict, das ueber (Groesse, mtime) puffert — kalt kostet
    die Liste rund 44 ms fuer 25 Dateien, warm 1,4 ms. Das Dock ruft sie
    seit Etappe D nur noch im Nebenthread (`_liste_auffrischen`).

    `nur_dock`: nur Sitzungen, die das Dock angelegt hat (`_ist_dock`).
    Jeder Eintrag traegt `dock` (bool) und `belegt` (bool, je Aufruf frisch,
    `sitzung_belegt`: laeuft gerade im Dock eines ANDEREN Cadwork).
    Die Eintraege gehoeren dem Aufrufer:
    die Bezeichnung mit Uhrzeit (s. u.) wird in eine KOPIE geschrieben, der
    Puffer bleibt unberuehrt (sonst waechst sie bei jedem Aufruf).
    """
    ordner = projekt_ordner(arbeitsordner)
    if cache is None:
        cache = {}
    liste = []
    for pfad in glob.glob(os.path.join(ordner, "*.jsonl")):
        try:
            st = os.stat(pfad)
        except OSError:
            continue
        schluessel = (pfad, st.st_size, int(st.st_mtime))
        eintrag = cache.get(schluessel)
        if eintrag is None:
            try:
                kopf, schwanz = _bloecke(pfad, st.st_size)
            except OSError:
                continue
            kennung = os.path.splitext(os.path.basename(pfad))[0]
            eintrag = {
                "id": kennung,
                "bezeichnung": (_titel(kopf, schwanz) or _erste_frage(kopf)
                                or kennung[:8]),
                "untertitel": _erste_frage(kopf),
                "geaendert": st.st_mtime,
                "groesse": st.st_size,
                "dock": _ist_dock(kopf, schwanz),
            }
            cache[schluessel] = eintrag
        if nur_dock and not eintrag.get("dock"):
            continue
        kopie = dict(eintrag)
        kopie["belegt"] = sitzung_belegt(kopie["id"])
        liste.append(kopie)
    liste.sort(key=lambda e: e["geaendert"], reverse=True)

    # Forts. und Abzweigungen kopieren den Titel mit: 7 von 25 Bezeichnungen
    # waren doppelt, dreimal woertlich gleich. Datum allein loest das nicht
    # auf (zwei gleich betitelte Chats am selben Tag) — also mit Uhrzeit.
    gesehen = {}
    for e in liste:
        gesehen.setdefault(e["bezeichnung"], []).append(e)
    for name, gleiche in gesehen.items():
        if len(gleiche) > 1:
            for e in gleiche:
                e["bezeichnung"] = "%s  (%s)" % (
                    name, time.strftime("%d.%m. %H:%M",
                                        time.localtime(e["geaendert"])))
    return liste


# --- Belegt: laeuft eine Sitzung gerade in einem anderen Cadwork? ----------
# Nacharbeit D (Pruefung 2026-09-26): der Arbeitsordner ist fuer alle
# Cadwork-Instanzen derselbe (projektordner.txt im Profil, chat.json unter
# %APPDATA%), jedes Dock zeigt also dieselbe Liste — auch den Chat, der im
# Dock einer ANDEREN Instanz gerade laeuft. Seit Etappe D setzt das Dock ohne
# Abzweigen fort (`--resume`): zwei CLI-Prozesse schrieben dann in dieselbe
# Sitzungsdatei, und der Verlauf der anderen Cadwork-Datei kaeme hierher.
# Deshalb traegt jeder Chat seine Sitzung in einen kleinen Vermerk ein
# (`<Kennung>.json` im Ordner `_belegt_ordner()`: PID des CLI, Startzeit,
# PID des Cadwork), und fortgesetzt wird nur, was kein lebender fremder
# Prozess belegt. Die Startzeit prueft wie die Registry, ob die PID noch
# dieselbe ist (Windows vergibt PIDs neu). Ein Vermerk eines toten Prozesses
# gilt nicht, auch wenn er liegen blieb. NICHT erfasst: eine Dock-Sitzung,
# die jemand im Terminal mit `claude --resume` fortsetzt (das Terminal
# schreibt keinen Vermerk).

#: Ueber diese Umgebungsvariable legen die Gates den Ordner in ihren Temp.
BELEGT_UMGEBUNG = "OPEN_MCP_CAD_BELEGT"
#: So viel Spiel hat der Vergleich der Startzeit (wie `registry.py`).
BELEGT_TOLERANZ_S = 2.0

SITZUNG_BELEGT = ("Dieser Chat läuft gerade in einem anderen Cadwork. Dort "
                  "weiterschreiben oder hier «Neuer Chat» drücken.")


class SitzungBelegt(RuntimeError):
    """starten() mit einer Sitzung, die ein anderes Cadwork gerade fuehrt."""


def _belegt_ordner():
    return (os.environ.get(BELEGT_UMGEBUNG, "").strip()
            or os.path.join(tempfile.gettempdir(), "open_mcp_cad_belegt"))


def _belegt_pfad(sitzung):
    if not isinstance(sitzung, str) or not _SITZUNG_ID.match(sitzung):
        return None
    return os.path.join(_belegt_ordner(), sitzung + ".json")


def _prozess_lebt(pid, seit):
    """Lebt `pid` noch als DERSELBE Prozess, der sich um `seit` eingetragen
    hat? Dieselbe Regel wie `_pid_lebt` in open_mcp_cad/registry.py (das
    Plugin kann das Paket nicht importieren): er lebt und ist nicht NACH
    dem Eintrag gestartet. Scheitert die Abfrage selbst, gilt er als lebend
    — lieber einmal zu vorsichtig als zwei Prozesse an einer Datei."""
    try:
        pid = int(pid)
        seit = float(seit)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = w.HANDLE
        k.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
        k.CloseHandle.argtypes = (w.HANDLE,)
        k.WaitForSingleObject.restype = w.DWORD
        k.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
        k.GetProcessTimes.argtypes = ((w.HANDLE,)
                                      + (ctypes.POINTER(w.FILETIME),) * 4)
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        h = k.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not h:
            return False
        try:
            if k.WaitForSingleObject(h, 0) == 0:     # beendet
                return False
            zeiten = [w.FILETIME() for _ in range(4)]
            if not k.GetProcessTimes(h, *[ctypes.byref(z) for z in zeiten]):
                return True
            ft = (zeiten[0].dwHighDateTime << 32) | zeiten[0].dwLowDateTime
            gestartet = ft / 1e7 - 11644473600.0      # 1601 -> 1970
            return gestartet <= seit + BELEGT_TOLERANZ_S
        finally:
            k.CloseHandle(h)
    except Exception:                                   # noqa: BLE001
        return True


def sitzung_belegt(sitzung, ich=None):
    """Fuehrt gerade ein ANDERES Cadwork diese Sitzung? Liest nur einen
    kleinen Vermerk, nie die Sitzungsdatei. `ich`: die PID, die als eigenes
    Cadwork gilt (Vorgabe: dieser Prozess) — den eigenen Chat haelt
    ohnehin `voriger_laeuft` auf."""
    pfad = _belegt_pfad(sitzung)
    if pfad is None:
        return False
    try:
        with open(pfad, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(v, dict):
        return False
    if v.get("besitzer") == (os.getpid() if ich is None else ich):
        return False
    return _prozess_lebt(v.get("pid"), v.get("seit"))


def _belegen(sitzung, proc):
    """Den Vermerk fuer `sitzung` schreiben: `proc` fuehrt sie."""
    pfad = _belegt_pfad(sitzung)
    if pfad is None or proc is None:
        return
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        tmp = "%s.%d.tmp" % (pfad, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"sitzung": sitzung, "pid": proc.pid,
                       "seit": getattr(proc, "omcad_seit", None) or time.time(),
                       "besitzer": os.getpid()}, fh)
        os.replace(tmp, pfad)
        belegt = getattr(proc, "omcad_belegt", None)
        if belegt is not None:
            belegt.add(sitzung)
    except OSError:
        pass


def _freigeben(proc):
    """Die Vermerke von `proc` entfernen — nur, wenn sie noch IHM gehoeren."""
    for sitzung in list(getattr(proc, "omcad_belegt", ()) or ()):
        pfad = _belegt_pfad(sitzung)
        try:
            with open(pfad, encoding="utf-8") as fh:
                v = json.load(fh)
            if isinstance(v, dict) and v.get("pid") == proc.pid \
                    and v.get("besitzer") == os.getpid():
                os.remove(pfad)
        except (OSError, ValueError, TypeError):
            pass


#: So viele Nachrichten zeigt ein geoeffneter Chat aus seinem alten Verlauf.
VERLAUF_ALT_MAX = 40
_SITZUNG_ID = re.compile(r"^[0-9A-Za-z-]{1,80}$")


def _iso_zeit(text):
    """"2026-09-27T08:12:33.123Z" -> Sekunden seit 1970, sonst None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        import datetime
        return datetime.datetime.fromisoformat(
            text.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def _ergebnisse_aus(inhalt):
    """Die Werkzeug-Ergebnisse in `message.content` einer Nutzer-Zeile als
    Ereignisse ("ergebnis", mit der Kennung des Aufrufs und `fehler`)."""
    aus = []
    for blk in inhalt if isinstance(inhalt, list) else ():
        if isinstance(blk, dict) and blk.get("type") == "tool_result":
            aus.append({"art": "ergebnis", "id": blk.get("tool_use_id"),
                        "fehler": bool(blk.get("is_error"))})
    return aus


def sitzung_verlauf(arbeitsordner, sitzung, hoechstens=VERLAUF_ALT_MAX):
    """Der fruehere Verlauf einer Sitzung — fuer die Anzeige, WARTET (Datei).

    Nur im Nebenthread (das Dock: `_sitzung_oeffnen`). Gelesen wird nur
    das Schwanzfenster (SCHWANZ_BYTES), nie die ganze Datei. -> Liste von
    Ereignissen wie im laufenden Chat ("ich", "text", "werkzeug"), jedes
    mit `alt: True`; fehlt davor etwas, steht vorne ein "hinweis". Eine
    Kennung, die kein Dateiname sein kann, gibt eine leere Liste.
    """
    if not isinstance(sitzung, str) or not _SITZUNG_ID.match(sitzung):
        return []
    pfad = os.path.join(projekt_ordner(arbeitsordner), sitzung + ".jsonl")
    try:
        groesse = os.path.getsize(pfad)
        with open(pfad, "rb") as fh:
            anfang = max(0, groesse - SCHWANZ_BYTES)
            fh.seek(anfang)
            block = fh.read()
    except OSError:
        return []
    zeilen = block.split(b"\n")
    if anfang > 0:
        zeilen = zeilen[1:]                     # die erste ist halb
    aus = []
    for zeile in zeilen:
        try:
            ev = json.loads(zeile.decode("utf-8"))
        except Exception:                                # noqa: BLE001
            continue
        if not isinstance(ev, dict) or ev.get("isSidechain") \
                or ev.get("isMeta"):
            continue
        inhalt = (ev.get("message") or {}).get("content")
        # Die Zeit steht in jeder Zeile als ISO-Text ("timestamp"); das
        # Dock setzt daraus die Zeitmarken. Fehlt sie, fehlt nur die Marke.
        zeit = _iso_zeit(ev.get("timestamp"))
        if ev.get("type") == "user":
            # Ein Werkzeug-Ergebnis hat keinen Textblock (`_text_aus` gibt
            # dann ""); steht doch einer dabei, hat ihn der Nutzer geschrieben.
            text = _text_aus(inhalt).strip()
            if text and not text.startswith(UNBRAUCHBAR):
                aus.append({"art": "ich", "text": text, "alt": True,
                            "zeit": zeit})
            # Nur GESCHEITERTE Ergebnisse: sie markieren im Dock den Schritt
            # ("hat nicht geklappt"); die vielen gelungenen fuellten sonst
            # das Fenster von VERLAUF_ALT_MAX.
            for erg in _ergebnisse_aus(inhalt):
                if erg["fehler"]:
                    aus.append(dict(erg, alt=True, zeit=zeit))
        elif ev.get("type") == "assistant":
            for blk in inhalt if isinstance(inhalt, list) else ():
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text" and (blk.get("text") or "").strip():
                    aus.append({"art": "text", "text": blk["text"].strip(),
                                "alt": True, "zeit": zeit})
                elif blk.get("type") == "tool_use":
                    aus.append({"art": "werkzeug", "werkzeug": blk.get("name"),
                                "eingabe": blk.get("input") or {},
                                "id": blk.get("id"), "alt": True,
                                "zeit": zeit})
    if len(aus) > hoechstens or (anfang > 0 and aus):
        aus = [{"art": "hinweis", "alt": True,
                "text": "… frühere Nachrichten sind hier ausgelassen"}] \
            + aus[-hoechstens:]
    return aus


# --- Der Kindprozess ------------------------------------------------------

def _einstellungen():
    """Die Freigabe-Haltung, die dem Kind mitgegeben wird.

    `ask: ["*"]` ist der Schalter, der aus der Bruecke ein lueckenloses Gate
    macht. Er sticht auch eine `allow`-Regel auf denselben Befehl (gemessen)
    — geerbte Projektregeln aus `.claude/settings.local.json` koennen das
    Gate also nicht aufweichen.

    Absichtlich NICHT hier: die Abkuerzung, die die Rueckfrage ganz
    abschaltet (der "alles durchwinken"-Modus und sein Kommandozeilen-
    Zwilling). Das A-Gate prueft woertlich, dass sie in dieser Datei in
    keiner Schreibweise vorkommt — deshalb steht sie hier auch nicht als
    Beispiel.
    """
    return {"permissions": {"ask": ["*"]}}


# --- Generationen: schnelle Wechsel ohne Uebersprechen --------------------
# Alle Anbieter (dieses CLI, die Schleife und Codex in omcad_a_anbieter)
# schreiben in EIN Dict, das das Dock zeichnet. Befund 2026-09-25: das
# `finally` eines ALTEN Lesers setzte `an`, `laeuft_zug` und `denkt` auch
# dann zurueck, wenn laengst ein neuer Chat lief — der neue stand als "aus"
# da. Deshalb zaehlt jeder Start `chat["generation"]` hoch; jeder Leser und
# jede Schleife merkt sich ihre und fasst gemeinsame Felder nur an, solange
# sie noch die aktuelle ist. Listen (Verlauf, Karten, stderr) bekommt jeder
# Chat neu.

class VorigerChatLaeuft(RuntimeError):
    """starten(), waehrend vom vorigen Chat noch ein Prozess lebt."""


VORIGER_CHAT = "Der vorige Chat endet noch — gleich nochmal versuchen"


def _neue_generation(chat):
    chat["generation"] = chat.get("generation", 0) + 1
    return chat["generation"]


def _aktuell(chat, generation):
    """Gehoert `generation` noch zu dem Chat, der gerade im Dict steht?"""
    return chat.get("generation") == generation


def voriger_laeuft(chat):
    """Laeuft vom vorigen Chat noch etwas? Dann darf kein neuer starten.

    `an` ist das Wort des Chats selbst; der Prozess ist die Wahrheit
    dahinter: das Dock setzt `an` beim Beenden sofort zurueck, das Kind
    braucht aber bis zu drei Sekunden (danach `taskkill`). Dieselbe Regel
    steht in omcad_a_anbieter (`_voriger_laeuft`), das dieses Modul nicht
    importiert.
    """
    if chat.get("an"):
        return True
    proc = chat.get("proc")
    if proc is not None and proc.poll() is None:
        return True
    laeuft_noch = getattr(chat.get("schleife"), "laeuft_noch", None)
    return bool(laeuft_noch and laeuft_noch())


# claude.cmd laeuft ueber cmd.exe, und Python maskiert Argumente nur fuer
# Programme, nicht fuer cmd.exe: ein `&` in einem Argument OHNE Leerzeichen
# steht dort ohne Anfuehrungszeichen und beendet den Befehl — der Rest
# laeuft als EIGENER Befehl. Gemessen 2026-09-28 (Gegenpruefung): ein
# Ordner `M&echo.INJ` als `--add-dir` fuehrte `echo.INJ` aus; `^` verschwand
# still aus dem Pfad, `%NAME%` wurde ersetzt. Von aussen kommen hier der
# weitere Ordner ("+ Ordner") und ein getippter Modellname — die gehen nur
# ohne diese Zeichen auf die Befehlszeile.
#
# Mit `claude.exe` (eigener Installer, seit 2026-09-29) laeuft KEIN cmd.exe
# dazwischen: subprocess setzt die Befehlszeile fuer CreateProcess, und das
# Programm liest jedes Argument woertlich (gemessen am claude.exe 2.1.263:
# `a&echo.INJ`, `x|y<z>^w%PATH%!q!`, Anfuehrungszeichen, Umlaute, ein
# Backslash am Ende). Die Pruefung gilt trotzdem fuer BEIDE Wege
# (Entscheid 2026-09-29): das Dock weist einen solchen Ordner schon beim
# Waehlen ab, ohne zu wissen, welches Claude Code spaeter startet — und
# welches das ist, kann sich zwischen Waehlen und Starten aendern (npm-
# Fassung dazu- oder weginstalliert). Betroffen sind nur seltene Namen.
BEFEHLSZEILE_VERBOTEN = '&|<>^%!"\r\n'


class BefehlszeileUngeeignet(ValueError):
    """Ein Argument enthielte ein Zeichen, das cmd.exe selbst auslegt."""


def _befehlszeile_pruefen(wert, was):
    """Wirft `BefehlszeileUngeeignet`, wenn `wert` so nicht ueber claude.cmd
    geht (s. BEFEHLSZEILE_VERBOTEN); der Text nennt Wert und Zeichen."""
    boese = sorted({z for z in wert if z in BEFEHLSZEILE_VERBOTEN})
    if boese:
        raise BefehlszeileUngeeignet(
            "%s «%s» enthält %s — so geht er nicht sicher an Claude Code. "
            "Bitte umbenennen oder herausnehmen." % (
                was, wert, " ".join(repr(z)[1:-1] for z in boese)))


def starten(chat, arbeitsordner, port, dokument=None, sitzung=None,
            abzweigen=False, modell=MODELL_VORGABE, effort=EFFORT_VORGABE,
            werkzeuge=True, name=SITZUNG_NAME, vorher=None, zusatz=None):
    """Claude Code starten. Gibt sofort zurueck — es wird nichts erwartet.

    `sitzung` fortsetzen oder None fuer einen neuen Chat. Fortgesetzt wird
    IN DERSELBEN Sitzung (`--resume` ohne `--fork-session`, Entscheid
    2026-09-26; gemessen am CLI 2.1.263: dieselbe `session_id`, dieselbe
    Datei, das Modell kennt den alten Verlauf). `abzweigen` legt stattdessen
    eine Kopie an (bis Etappe D die Vorgabe).

    `zusatz`: weitere Ordner, auf die Claude Code zugreifen darf ("+
    Ordner" im Dock) — je einer als `--add-dir` (Schalter des CLI 2.1.263,
    variadisch: deshalb steht er nie als letztes vor einem blossen Pfad).
    Nur Ordner, die es gibt.

    `name` kennzeichnet eine NEUE Sitzung (`-n`, s. SITZUNG_NAME); eine
    fortgesetzte behaelt ihre Kennzeichnung (gemessen). `vorher`: Ereignisse,
    mit denen der Verlauf beginnt (der alte Verlauf einer fortgesetzten
    Sitzung, `sitzung_verlauf`).

    Fuehrt ein anderes Cadwork die Sitzung gerade (`sitzung_belegt`), wirft
    es `SitzungBelegt`, ohne etwas zu starten (Nacharbeit D).

    Lebt vom vorigen Chat noch etwas, wirft es `VorigerChatLaeuft` — das
    Dock zeigt den Text. Bis 2026-09-25 kehrte es hier STILL zurueck: der
    Nutzer klickte "Starten", und es passierte nichts.
    """
    if voriger_laeuft(chat):
        raise VorigerChatLaeuft(VORIGER_CHAT)
    if sitzung and not abzweigen and sitzung_belegt(sitzung):
        raise SitzungBelegt(SITZUNG_BELEGT)

    args = [cli_pfad(), "--print", "--verbose",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--include-partial-messages",
            # Der Halt. Ohne diesen Schalter fragt niemand.
            "--permission-prompt-tool", "stdio",
            "--settings", json.dumps(_einstellungen()),
            # Reiner Text, Sprache des Nutzers (DOCK_ANWEISUNG). ANGEHAENGT,
            # nicht ersetzt: die eigene Anweisung des CLI bleibt, sonst
            # verloere es Werkzeug- und Sicherheitsregeln.
            "--append-system-prompt", DOCK_ANWEISUNG]
    if modell:
        _befehlszeile_pruefen(modell, "Der Modellname")
        args += ["--model", modell]
    if effort:
        _befehlszeile_pruefen(effort, "Die Denkstufe")
        args += ["--effort", effort]

    # Die Cadwork-Werkzeuge. NIE `--tools ""` dazunehmen: genau dieses eine
    # leere Argument hat am 2026-08-09 die ganze Werkzeugliste zerschossen,
    # und es sah aus, als lade die MCP-Konfiguration nicht.
    werkzeuge_da, wissen = False, None
    if werkzeuge:
        cfg = mcp_konfig_schreiben(port)
        if cfg:
            wissen = wissensordner()
            # strict: nur DIESER Server, nicht zusaetzlich die
            # claude.ai-Verbinder — der Chat soll Cadwork bedienen.
            args += ["--mcp-config", cfg, "--strict-mcp-config"]
            werkzeuge_da = True

    for ordner in zusatz or ():
        if isinstance(ordner, str) and os.path.isdir(ordner):
            _befehlszeile_pruefen(ordner, "Der weitere Ordner")
            args += ["--add-dir", ordner]

    if sitzung:
        args += ["--resume", sitzung]
        if abzweigen:
            args += ["--fork-session"]
    elif name:
        args += ["-n", name]

    umgebung = dict(os.environ)
    # Der elegante Teil: ein so gestarteter Chat kann gar nicht in die
    # falsche Cadwork-Datei zeichnen. Der Riegel steckt schon in server.py
    # (`error: "wrong_document"`), er wird hier endlich benutzt.
    umgebung["OPEN_MCP_CAD_PORT"] = str(port)
    if dokument:
        umgebung["OPEN_MCP_CAD_EXPECT_DOC"] = dokument

    chat["proc"] = subprocess.Popen(
        args, cwd=arbeitsordner, env=umgebung,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW)       # sonst blitzt eine Konsole auf
    proc = chat["proc"]
    proc.omcad_seit, proc.omcad_belegt = time.time(), set()
    if sitzung and not abzweigen:
        _belegen(sitzung, proc)           # ab jetzt sieht jedes Dock es

    # Ab hier ist es ein NEUER Chat: neue Generation, und er beginnt leer.
    # Vorher blieben Verlauf und Karten per `setdefault` stehen — samt
    # offener Karten des alten Prozesses, deren "Erlauben" dann beim neuen
    # ankam. Ein `beenden_nach_zug` des alten Chats beendete den neuen
    # gleich im ersten Takt (laeuft_zug ist dort noch False).
    _neue_generation(chat)
    chat.update(ereignisse=list(vorher or ()), freigaben=[], sitzung=sitzung,
                modell=None, kontext=None,
                werkzeuge_da=werkzeuge_da, wissen=wissen, fehler=None,
                laeuft_zug=False, denkt=False, laufender_text="",
                beenden_nach_zug=False, stderr=[],
                # Freigaben je Art (Modus "fragen") gelten nur fuer DIESEN
                # Chat: bis zur naechsten Nachricht bzw. bis er endet.
                gewaehrt_zug=set(), gewaehrt_sitzung=set(),
                # Lief vorher ein anderer Anbieter, darf seine Schleife hier
                # nichts mehr abfangen — senden/freigabe/beenden gingen sonst
                # ins Leere.
                schleife=None, an=True)
    chat["stand"] = chat.get("stand", 0) + 1
    # Zwei Threads schreiben auf stdin: die Oberflaeche schickt Nachrichten,
    # der Leser beantwortet Freigaben. Ohne Schloss verschraenken sich die
    # Zeilen und das Kind bekommt kaputtes JSON.
    chat["schloss"] = threading.Lock()
    _leser_starten(chat)
    _fehlerleser_starten(chat)
    return chat


def _fehlerleser_starten(chat):
    """Liest stderr mit — aus zwei Gruenden, beide handfest.

    ERSTENS SICHTBARKEIT. Lehnt das CLI etwas ab (ein Modellname, den es
    nicht kennt; ein unbekannter Schalter), sagt es das auf stderr und
    beendet sich. Auf stdout kommt dann NIE ein `result` — der Chat sah
    einfach tot aus, ohne ein Wort. Seit der Nutzer Modellnamen frei eintippen
    kann, ist genau das der wahrscheinlichste Fehlerfall.

    ZWEITENS, und schwerer: eine nicht gelesene Pipe laeuft voll. Windows
    puffert rund 64 kB; danach BLOCKIERT das Kind beim Schreiben und der
    Chat haengt, ohne dass irgendwo ein Fehler steht. Das ist kein
    theoretisches Risiko, sondern der klassische Popen-Deadlock.

    Gebunden an den PROZESS, wie `_leser_starten`: ein noch lebender Leser
    des vorigen Prozesses ist kein Grund, den neuen ungelesen zu lassen.
    Er schreibt in die stderr-Liste SEINES Chats, nie in die des naechsten.
    """
    proc = chat["proc"]
    generation = chat.get("generation")
    alt = chat.get("fehlerleser")
    if alt is not None and alt.is_alive() \
            and getattr(alt, "prozess", None) is proc:
        return
    zeilen = chat.setdefault("stderr", [])

    def schleife():
        try:
            for zeile in proc.stderr:
                zeile = zeile.rstrip()
                if not zeile:
                    continue
                zeilen.append(zeile)
                del zeilen[:-40]          # nur das Letzte behalten
                if _aktuell(chat, generation):
                    chat["stand"] = chat.get("stand", 0) + 1
        except Exception:                                 # noqa: BLE001
            pass

    t = threading.Thread(target=schleife, name="Open-MCP-CAD-A-Chat-Fehler",
                         daemon=True)
    t.prozess = proc
    t.start()
    chat["fehlerleser"] = t


def letzter_fehler(chat):
    """Was das CLI zuletzt beklagt hat — fuer die Oberflaeche aufbereitet.

    Nur brauchbar, wenn nichts mehr laeuft: waehrend eines Zuges schreibt
    das CLI auch Harmloses nach stderr (Fortschritt, Warnungen).
    """
    zeilen = [z for z in (chat.get("stderr") or [])
              if z.strip() and not z.startswith("[DEBUG")]
    if not zeilen:
        return None
    # Die aussagekraeftigste Zeile ist fast immer die mit "Error"/"error".
    fuer_fehler = [z for z in zeilen if "rror" in z]
    return (fuer_fehler or zeilen)[-1][:300]


def _leser_starten(chat):
    """Genau EIN Leserthread je PROZESS — wie beim Monitor, aus demselben Grund.

    Der Einstieg laedt das Modul bei jedem Plugin-Klick neu; ohne die
    `is_alive()`-Pruefung haette man nach fuenf Klicks fuenf Leser auf
    derselben Pipe.

    Die Pruefung gilt aber nur fuer DENSELBEN Prozess. Bis 2026-09-25 hiess
    sie "lebt irgendein alter Leser?" — nach einem schnellen Neustart liest
    der Leser des alten Prozesses oft noch dessen Rest, und der NEUE Prozess
    bekam gar keinen: seine Pipe lief nach ~64 kB voll, das Kind stand.
    """
    proc = chat["proc"]
    generation = chat.get("generation")
    alt = chat.get("leser")
    if alt is not None and alt.is_alive() \
            and getattr(alt, "prozess", None) is proc:
        return

    def schleife():
        try:
            for zeile in proc.stdout:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    ev = json.loads(zeile)
                except ValueError:
                    continue
                # NUR anhaengen und zuweisen. Kein Widget, nie. Ereignisse
                # eines abgeloesten Prozesses verwirft _einordnen selbst.
                _einordnen(chat, ev, proc, generation)
        except Exception as fehler:                     # noqa: BLE001
            if _aktuell(chat, generation):
                meldung = ("Claude Code lieferte etwas Unerwartetes, der Chat "
                           "wurde beendet (%s: %s)" % (type(fehler).__name__,
                                                       fehler))
                chat["fehler"] = meldung
                chat["ereignisse"].append(ereignis("text",
                                                   text="⚠ " + meldung))
        finally:
            # Der Strom ist zu: dieser Prozess fuehrt keine Sitzung mehr.
            _freigeben(proc)
            # Stirbt das CLI ohne `result`, muss der Zug hier enden — sonst
            # dreht die Laufanzeige fuer immer weiter. Das Ende des Fadens
            # ist das zweite Netz neben dem `result`-Ereignis.
            # Aber nur fuer SEINEN Chat: laeuft schon ein neuer, bleibt der an.
            if _aktuell(chat, generation):
                chat["an"] = False
                chat["laeuft_zug"] = False
                chat["denkt"] = False
                chat["laufender_text"] = ""
                chat["stand"] = chat.get("stand", 0) + 1
                # Ohne Leser liest niemand mehr stdout. Lebt das CLI weiter
                # (Befund 2026-09-25: eine Zeile `[1]` warf den Leser
                # hinaus, der Prozess wartete weiter auf stdin), sperrte
                # `voriger_laeuft` JEDEN neuen Start fuer immer — das Dock
                # zeigte "Starten", und nur ein Cadwork-Neustart half.
                # Deshalb derselbe Abraeum-Weg wie beim Beenden.
                if proc.poll() is None:
                    _prozess_abraeumen(chat, proc, generation)

    t = threading.Thread(target=schleife, name="Open-MCP-CAD-A-Chat", daemon=True)
    t.prozess = proc
    t.start()
    chat["leser"] = t


def _freigabe_antwort(kennung, erlauben, grund=""):
    """Die control_response auf eine Freigabe-Anfrage des CLI."""
    antwort = ({"behavior": "allow"} if erlauben else
               {"behavior": "deny",
                "message": grund or "Im Open-MCP-CAD-Dashboard abgelehnt"})
    return {"type": "control_response",
            "response": {"subtype": "success", "request_id": kennung,
                         "response": antwort}}


# --- Kontext: wie voll das Gespraech ist (S10) ------------------------------
# Gemessen 2026-09-26 am CLI 2.1.263 (Haiku, ohne Werkzeuge, zwei Laeufe):
# die Summe input_tokens + cache_creation_input_tokens +
# cache_read_input_tokens aus `usage` einer Antwort war GENAU `totalTokens`
# der CLI-eigenen Kontextabfrage (`get_context_usage`: 130168 und 8068),
# `modelUsage[<modell>].contextWindow` im `result` genau deren `maxTokens`
# (200000). Die Kontextabfrage selbst waere ein weiterer Steuerbefehl an das
# Kind; die Zahlen kommen ohnehin mit.

def _kontext_belegt(usage):
    """Wie viele Token die letzte Anfrage an das Modell mitnahm — oder None."""
    if not isinstance(usage, dict):
        return None
    summe = 0
    for feld in ("input_tokens", "cache_creation_input_tokens",
                 "cache_read_input_tokens"):
        wert = usage.get(feld)
        if isinstance(wert, (int, float)) and wert > 0:
            summe += int(wert)
    return summe or None


def _kontext_fenster(model_usage, modell):
    """Die Groesse des Kontextfensters aus `modelUsage` — oder None.

    `modelUsage` kann mehrere Modelle nennen (Nebenaufgaben mit einem
    kleineren). Gilt das des Chats (`init`), sonst nur ein einziges.
    """
    if not isinstance(model_usage, dict) or not model_usage:
        return None
    eintrag = model_usage.get(modell) if modell else None
    if eintrag is None and len(model_usage) == 1:
        eintrag = next(iter(model_usage.values()))
    wert = (eintrag or {}).get("contextWindow") if isinstance(
        eintrag, dict) else None
    return int(wert) if isinstance(wert, (int, float)) and wert > 0 else None


def _einordnen(chat, ev, proc=None, generation=None):
    """Ein Ereignis einsortieren. Laeuft im Nebenthread.

    `proc` und `generation` gibt der Leser mit: Antworten gehen an SEINEN
    Prozess, und stammt das Ereignis von einem abgeloesten Chat, wird es
    verworfen — es gehoert weder in den Verlauf noch in die Karten des
    neuen.
    """
    if generation is not None and not _aktuell(chat, generation):
        return
    art = ev.get("type")
    unterart = ev.get("subtype") or (ev.get("request") or {}).get("subtype")

    # --- Teilstuecke: der Text, waehrend er entsteht ---------------------
    # `--include-partial-messages` war von Anfang an gesetzt, aber es gab
    # hier keinen Zweig dafuer — der Nutzer sah deshalb 5 s lang gar nichts und
    # dann die ganze Antwort auf einmal. Gemessen 2026-08-09.
    if art == "stream_event":
        e = ev.get("event") or {}
        et = e.get("type")
        if et == "content_block_start":
            block = e.get("content_block") or {}
            if block.get("type") == "thinking":
                chat["denkt"] = True
            elif block.get("type") == "text":
                chat["laufender_text"] = ""
        elif et == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta":
                chat["denkt"] = False
                chat["laufender_text"] = (chat.get("laufender_text") or "") \
                    + (d.get("text") or "")
            elif d.get("type") == "thinking_delta":
                # Der Denk-TEXT ist hier immer leer (gemessen); brauchbar ist
                # nur die geschaetzte Menge.
                chat["denk_tokens"] = d.get("estimated_tokens") \
                    or chat.get("denk_tokens") or 0
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "system" and unterart == "thinking_tokens":
        chat["denk_tokens"] = ev.get("estimated_tokens") or 0
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "system" and unterart == "init":
        # Das init-Ereignis ist riesig (alle Werkzeuge + MCP-Server) und
        # gehoert NICHT ins Fenster — die Werkzeugliste allein sprengte
        # frueher eine 6000-Zeichen-Ausgabe. Nur das Brauchbare merken.
        chat["sitzung"] = ev.get("session_id") or chat.get("sitzung")
        chat["modell"] = ev.get("model")
        # Auch ein NEUER Chat steht mit seinem Ende in jeder Liste; von
        # hier an ist seine Kennung bekannt (s. `sitzung_belegt`).
        if proc is not None and ev.get("session_id"):
            _belegen(ev["session_id"], proc)
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "control_request" and unterart == "can_use_tool":
        anfrage = ev.get("request") or {}
        werkzeug = anfrage.get("tool_name")
        eintrag = {
            "id": ev.get("request_id"),
            "werkzeug": werkzeug,
            "name": anfrage.get("display_name") or werkzeug,
            "eingabe": anfrage.get("input") or {},
            "beschreibung": anfrage.get("description") or "",
            "zeit": time.time(),
            "offen": True,
            # Greift der Aufruf aus dem Ordner heraus, gilt keine Freigabe
            # je Art fuer ihn (s. `_geschwister_erlauben`).
            "draussen": bool(anfrage.get("blocked_path")),
            # Die Karte gehoert zu DIESEM Chat; freigabe_beantworten und
            # offene_freigaben nehmen nur Karten der aktuellen Generation.
            "generation": chat.get("generation"),
        }
        if chat.get("an") is False:
            # Der Chat wird gerade beendet (das Dock hat `an` schon
            # zurueckgesetzt): nichts mehr automatisch erlauben und keine
            # Karte mehr, die niemand beantworten kann — ein klares Nein.
            eintrag["offen"] = False
            eintrag["antwort"] = "abgelehnt"
            chat["freigaben"].append(eintrag)
            _schicken(chat, _freigabe_antwort(eintrag["id"], False,
                                              "Chat beendet"), proc)
        else:
            # Harmloses sofort selbst beantworten, Verbotenes sofort
            # ablehnen — beides SICHTBAR im Verlauf. Eine stille Automatik
            # waere schlimmer als die Fragerei: dann passieren Dinge, die
            # niemand gesehen hat.
            # `anfrage` MUSS mit: ohne sie ist der blocked_path-Riegel der
            # Politik tot (sie liest `(anfrage or {})`). Bis 2026-08-15
            # wurde er hier nicht uebergeben — die Grenze stand im Code, hat
            # aber nie gegriffen. Der Gate-Test dazu prueft den AUFRUF.
            urteil = chat_entscheiden(chat, werkzeug, anfrage)
            if urteil == "ja":
                eintrag["offen"] = False
                eintrag["antwort"] = "automatisch"
                chat["freigaben"].append(eintrag)
                chat["ereignisse"].append(ereignis(
                    "auto", werkzeug=werkzeug, eingabe=eintrag["eingabe"]))
                _schicken(chat, _freigabe_antwort(eintrag["id"], True), proc)
            elif urteil == "nein":
                modus = modus_von(chat)
                eintrag["offen"] = False
                eintrag["antwort"] = "verweigert"
                chat["freigaben"].append(eintrag)
                chat["ereignisse"].append(ereignis(
                    "verweigert", werkzeug=werkzeug,
                    eingabe=eintrag["eingabe"], modus=modus))
                _schicken(chat, _freigabe_antwort(
                    eintrag["id"], False, ablehnung_text(modus, werkzeug)),
                    proc)
            else:
                chat["freigaben"].append(eintrag)
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "user":
        # Die Ergebnisse der Werkzeuge (`tool_result`): ob ein Schritt
        # geklappt hat, zeigt das Dock am Schritt ("hat nicht geklappt").
        for erg in _ergebnisse_aus((ev.get("message") or {}).get("content")):
            chat["ereignisse"].append(ereignis(**erg))
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "assistant":
        if not ev.get("parent_tool_use_id"):
            belegt = _kontext_belegt((ev.get("message") or {}).get("usage"))
            if belegt:
                chat["kontext"] = {"belegt": belegt, "fenster": (
                    chat.get("kontext") or {}).get("fenster")}
        for blk in (ev.get("message") or {}).get("content") or []:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "text" and blk.get("text"):
                # Der fertige Block SETZT den Text, er haengt ihn nicht an —
                # sonst staende er doppelt da, wenn die Teilstuecke schon
                # liefen. Und ohne Teilstuecke ist er die Rueckfallebene.
                chat["laufender_text"] = ""
                chat["denkt"] = False
                chat["ereignisse"].append(ereignis("text", text=blk["text"]))
            elif blk.get("type") == "tool_use":
                chat["ereignisse"].append(ereignis(
                    "werkzeug", werkzeug=blk.get("name"),
                    eingabe=blk.get("input") or {}, id=blk.get("id")))
        chat["stand"] = chat.get("stand", 0) + 1
        return

    if art == "result":
        fenster = _kontext_fenster(ev.get("modelUsage"), chat.get("modell"))
        if fenster and chat.get("kontext"):
            chat["kontext"] = dict(chat["kontext"], fenster=fenster)
        chat["ereignisse"].append(ereignis(
            "schluss",
            kosten=ev.get("total_cost_usd"),
            abgelehnt=len(ev.get("permission_denials") or []),
            fehler=bool(ev.get("is_error")),
            text=str(ev.get("result") or "")[:400]))
        # NUR `result` beendet den Zug. `message_stop` taugt dafuer nicht:
        # nach einem Werkzeugaufruf kommt eine ZWEITE Nachricht im selben
        # Zug (gemessen: 2x message_start, 2x message_stop).
        chat["laeuft_zug"] = False
        chat["denkt"] = False
        chat["laufender_text"] = ""
        chat["stand"] = chat.get("stand", 0) + 1


def _schicken(chat, obj, proc=None):
    """Eine Zeile an das Kind — unter Schloss, weil zwei Threads schreiben.

    `proc` nennt den Empfaenger ausdruecklich (der Leser gibt SEINEN
    Prozess mit): eine Antwort des alten Lesers darf nie beim Prozess des
    naechsten Chats landen, nur weil der inzwischen in `chat["proc"]` steht.
    """
    if proc is None:
        proc = chat.get("proc")
    if proc is None or proc.poll() is not None:
        return False
    with chat["schloss"]:
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError) as fehler:
            # Beim Beenden ist die Leitung absichtlich zu — das ist keine
            # Stoerung, die der naechste Chat anzeigen soll.
            if proc is chat.get("proc") and chat.get("an"):
                chat["fehler"] = str(fehler)
            return False


# Die anderen Anbieter (omcad_a_anbieter) legen ihre Schleife unter
# chat["schleife"] ab. senden, freigabe_beantworten und beenden geben dann
# an sie weiter — das Dashboard ruft fuer JEDEN Anbieter dieselben drei.

def _mit_anhaengen(text, anhaenge):
    """Der Text der Nachricht samt den Anhaengen, die als TEXT mitgehen
    (Textdateien mit Inhalt, andere Dateien mit ihrem Pfad — `als_text`
    baut das Dock). Dieselbe Regel steht in omcad_a_anbieter (das dieses
    Modul nicht importiert)."""
    teile = [text] if text else []
    teile += [a.get("als_text") for a in anhaenge or ()
              if a.get("art") != "bild" and a.get("als_text")]
    return "\n\n".join(teile)


def anhang_inhalt(text, anhaenge):
    """`message.content` einer Nachricht an das CLI: ohne Anhaenge der Text,
    sonst Bloecke — ein Text-Block, dann je Bild ein Bild-Block (base64).

    Gemessen 2026-09-27 am echten CLI 2.1.263 (stream-json, Haiku, ohne
    Werkzeuge): ein blaues PNG in genau dieser Form -> "Blau", ein rotes ->
    "Rot" (Uebergabe 2026-09-27, "Vorab gemessen")."""
    if not anhaenge:
        return text
    inhalt = []
    voll = _mit_anhaengen(text, anhaenge)
    if voll:
        inhalt.append({"type": "text", "text": voll})
    for a in anhaenge:
        if a.get("art") == "bild" and a.get("b64"):
            inhalt.append({"type": "image", "source": {
                "type": "base64", "media_type": a.get("mime") or "image/png",
                "data": a["b64"]}})
    return inhalt


def senden(chat, text, anhaenge=None):
    """Nachricht des Nutzers an Claude bzw. den gewaehlten Anbieter.

    Jede Nachricht des Nutzers beendet die Freigaben "bis zur naechsten
    Nachricht" (Modus "fragen") — fuer ALLE Anbieter, deshalb hier vor der
    Weitergabe an die Schleife. `anhaenge`: vom Dock vorbereitet (Bilder
    base64, Text als `als_text`); im Verlauf stehen nur ihre Namen."""
    chat["gewaehrt_zug"] = set()
    if chat.get("schleife") is not None:
        if anhaenge:
            return chat["schleife"].senden(text, anhaenge)
        return chat["schleife"].senden(text)
    felder = {"text": text}
    if anhaenge:
        felder["anhaenge"] = [a.get("name") or "?" for a in anhaenge]
    ich = ereignis("ich", **felder)
    chat["ereignisse"].append(ich)
    chat["laeuft_zug"] = True
    chat["stand"] = chat.get("stand", 0) + 1
    if _schicken(chat, {"type": "user", "message": {
            "role": "user", "content": anhang_inhalt(text, anhaenge)}}):
        return True
    # Das CLI lebt nicht mehr (oder die Leitung ist zu): NICHT gesendet.
    # Dann steht die Nachricht auch nicht im Verlauf, und kein Zug "laeuft"
    # — sonst hiesse der Verlauf, sie sei angekommen, und "Neuer Chat" bliebe
    # gesperrt. Das Dock laesst den Text im Feld (Gegenpruefung K7: vorher
    # leerte es das Feld, die Nachricht war weg).
    liste = chat["ereignisse"]
    for i in range(len(liste) - 1, -1, -1):
        if liste[i] is ich:                  # genau DIESE, nicht eine gleiche
            del liste[i]
            break
    chat["laeuft_zug"] = False
    chat["stand"] = chat.get("stand", 0) + 1
    return False


def freigabe_beantworten(chat, kennung, erlauben, grund="", sitzung=False):
    """Erlauben oder Ablehnen — die Antwort auf eine Karte.

    Wird gar nicht geantwortet, passiert nichts: der Aufruf bleibt haengen
    und wird beim Beenden abgelehnt. Das ist die gewollte Richtung.

    Nur Karten des AKTUELLEN Chats: die `request_id` einer Karte gehoert
    zu dem Prozess, der sie gestellt hat. Ein spaetes "Erlauben" auf die
    Karte eines abgeloesten Chats erreicht den naechsten Prozess nie.

    Erlauben gibt die ART frei (Modus "fragen"): bis zur naechsten
    Nachricht, mit `sitzung` ("Für diese Sitzung nicht mehr fragen") bis der
    Chat endet. Andere offene Karten derselben Art, die danach ohne Frage
    liefen, werden gleich mit erlaubt — fuer alle Anbieter, deshalb hier.
    """
    karte = next((f for f in offene_freigaben(chat) if f.get("id") == kennung),
                 None)
    if erlauben and karte is not None and chat_entscheiden(
            chat, karte.get("werkzeug"),
            {"blocked_path": True} if karte.get("draussen") else {}) == "nein":
        # Der Modus verbietet es JETZT (etwa nach dem Wechsel auf "Nur
        # lesen", waehrend die Karte offen stand oder gerade entstand): ein
        # "Erlauben" wird zur Ablehnung mit dem Grund des Modus
        # (Gegenpruefung 2026-09-28).
        erlauben, sitzung = False, False
        grund = ablehnung_text(modus_von(chat), karte.get("werkzeug"))
    if erlauben and karte is not None:
        gewaehren(chat, karte.get("werkzeug"), sitzung)
    if chat.get("schleife") is not None:
        ok = chat["schleife"].freigabe_beantworten(kennung, erlauben, grund)
    else:
        ok = _karte_beantworten(chat, kennung, erlauben, grund)
    if ok and erlauben and karte is not None:
        _geschwister_erlauben(chat, karte.get("werkzeug"), kennung)
    return ok


def _geschwister_erlauben(chat, werkzeug, ausser=None):
    """Offene Karten derselben Art, die nach der Freigabe ohne Frage liefen.
    `ausser`: die eben beantwortete Karte (nie zweimal beantworten)."""
    for f in list(offene_freigaben(chat)):
        if f.get("werkzeug") != werkzeug or f.get("id") == ausser:
            continue
        anfrage = {"blocked_path": True} if f.get("draussen") else {}
        if chat_entscheiden(chat, werkzeug, anfrage) != "ja":
            continue
        if chat.get("schleife") is not None:
            chat["schleife"].freigabe_beantworten(f["id"], True, "")
        else:
            _karte_beantworten(chat, f["id"], True, "")


def _karte_beantworten(chat, kennung, erlauben, grund=""):
    """Die Antwort des CLI-Wegs auf genau eine Karte (s. o.)."""
    for eintrag in chat.get("freigaben", []):
        if eintrag["id"] != kennung or not eintrag["offen"]:
            continue
        if eintrag.get("generation") != chat.get("generation"):
            continue
        eintrag["offen"] = False
        eintrag["antwort"] = "erlaubt" if erlauben else "abgelehnt"
        chat["stand"] = chat.get("stand", 0) + 1
        return _schicken(chat, _freigabe_antwort(kennung, erlauben, grund))
    return False


def offene_freigaben(chat):
    """Offene Karten des aktuellen Chats (Karten ohne Generation — die der
    anderen Anbieter, die eigene Listen fuehren — gelten als aktuell)."""
    jetzt = chat.get("generation")
    return [f for f in chat.get("freigaben", [])
            if f.get("offen") and f.get("generation", jetzt) == jetzt]


def laeuft_zug(chat):
    """Ist gerade ein Zug unterwegs? Entscheidet, ob beim Beenden gefragt wird."""
    return bool(chat.get("laeuft_zug"))


def nach_zug_beenden(chat):
    """Merken statt abwuergen — der laufende Zug darf fertig werden.

    Dieselbe Haltung wie `shutdown_after_current` in der Bridge: ein
    laufender Auftrag wird nie hart abgebrochen. Ausgefuehrt wird es vom
    Qt-Takt, sobald `laeuft_zug` faellt — nicht aus dem Leserthread, damit
    das Abraeumen nicht mitten im Pipe-Lesen passiert.
    """
    chat["beenden_nach_zug"] = True
    chat["stand"] = chat.get("stand", 0) + 1


def beenden(chat):
    """Den ganzen Prozessbaum abraeumen, nicht nur den Mantel.

    `claude.cmd` ist eine Huelle (cmd.exe) um das eigentliche Programm.
    Wird nur die Huelle abgeschossen, laeuft das Kind weiter — und haelt
    Cadwork beim Schliessen auf. `taskkill /T` nimmt die Kinder mit (auch
    die MCP-Server, die ein direkt gestartetes `claude.exe` startet).

    Offene Karten gelten als ABGELEHNT, wie bei den anderen Anbietern: das
    Kind bekommt das Nein, bevor stdin zugeht, und keine Karte bleibt offen,
    deren "Erlauben" spaeter beim Prozess des naechsten Chats landen koennte
    (bis 2026-09-25 blieben sie offen stehen).
    """
    chat["an"] = False
    schleife = chat.get("schleife")
    if schleife is not None:
        schleife.beenden()          # offene Karten gelten als abgelehnt
        chat["stand"] = chat.get("stand", 0) + 1
        return
    proc = chat.get("proc")
    if proc is None:
        return
    _prozess_abraeumen(chat, proc, chat.get("generation"))


def _prozess_abraeumen(chat, proc, generation):
    """Offene Karten von `generation` ablehnen, dann den Baum von `proc` beenden.

    EIN Weg fuer `beenden` und fuer einen Leser, der aussteigt, waehrend
    sein Prozess noch lebt (`_leser_starten`).
    """
    for eintrag in list(chat.get("freigaben") or ()):
        if eintrag.get("offen") and eintrag.get("generation") == generation:
            eintrag["offen"] = False
            eintrag["antwort"] = "abgelehnt"
            _schicken(chat, _freigabe_antwort(eintrag["id"], False,
                                              "Chat beendet"), proc)
    chat["laeuft_zug"] = False
    chat["stand"] = chat.get("stand", 0) + 1
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()          # sauberes Ende: Kind laeuft aus
    except Exception:                                   # noqa: BLE001
        pass
    try:
        proc.wait(timeout=3)
    except Exception:                                   # noqa: BLE001
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           creationflags=CREATE_NO_WINDOW,
                           capture_output=True, timeout=10)
        except Exception:                               # noqa: BLE001
            try:
                proc.kill()
            except Exception:                           # noqa: BLE001
                pass
    # Nur den EIGENEN Prozess austragen: kaum ist er tot, darf schon ein
    # neuer Chat gestartet sein — dessen Prozess bleibt stehen.
    if chat.get("proc") is proc:
        chat["proc"] = None
    chat["stand"] = chat.get("stand", 0) + 1
