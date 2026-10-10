"""Open MCP CAD — gemeinsamer Kern aller vier Steckplaetze (A/B/C/D).

Diese Datei ist die EINZIGE Quelle der Bridge-Logik. Die vier Plugin-Ordner
enthalten je eine byte-identische Kopie plus einen sehr duennen Einstieg
(`McpBridge*.py`), der nur Instanz, Port, Anzeigename und Logdatei setzt.
Erzeugt und geprueft wird das von `scripts/plugins_generieren.py`.

Intern heisst das Ding weiter "Bridge"/"MCP" — benutzerseitig heisst es
"Open MCP CAD A..D", das Uebersichtsfenster "Open MCP CAD Verbindungen".

ARCHITEKTUR (unveraendert im Kern, praezisiert an den Raendern)
--------------------------------------------------------------
  Listener-Thread (daemon)   nimmt TCP-Verbindungen an
  Worker-Thread pro Conn     liest Requests, beantwortet SOFORT alles, was
                             ohne cwapi3d auskommt (ping, status, pause,
                             resume, shutdown*, Session-Speicher)
  Cadwork-Hauptthread        zieht Modell-Auftraege aus der Queue und ruft
                             cwapi3d auf — sequentiell, nie woanders

Der entscheidende Unterschied zur Vorversion: **Status und Steuerung laufen
nie ueber die Job-Queue.** Damit antwortet die Verbindung auch dann, wenn der
Cadwork-Hauptthread gerade minutenlang zeichnet oder haengt. Genau daran ist
die alte Version blind gewesen: ein Timeout war nicht unterscheidbar von
"Plugin gar nicht gestartet".

ZUSTAENDE
---------
  stopped              Aus
  starting             Wird gestartet
  ready                Bereit
  busy_read            Liest Modell
  busy_write           Bearbeitet Modell
  paused               Pausiert
  stopping_after_job   Wird nach dem Auftrag beendet
  error                Stoerung

UI-BEDIENBARKEIT / WIN32-PUMPE
------------------------------
Solange `serve()` den Cadwork-Hauptthread haelt, laeuft Cadworks eigene
Message-Schleife NICHT. Die Vorversion hat deshalb im Leerlauf-Zweig selbst
`PeekMessage/DispatchMessage` aufgerufen. Das holt die UI teilweise zurueck,
ruft aber Cadworks Fensterprozeduren aus einem laufenden Plugin heraus wieder
auf (Re-Entrance). Betritt eine dieser Prozeduren eine eigene modale
Schleife (Menue-Tracking, Move/Size, Tooltip, Cadwork-Eingabeaufforderung),
kehrt `DispatchMessageW` erst zurueck, wenn echte Benutzereingabe kommt —
der Hauptthread zieht dann keine Jobs mehr, CPU idle, Verbindung wird
angenommen aber nie beantwortet. Genau dieses Bild ist am 2026-07-24
dokumentiert (Messskript in einem privaten Builder-Repo).

AM 2026-08-04 IN CADWORK 2026 GEMESSEN — der Verdacht ist bestaetigt:

    OSError: exception: access violation reading 0x0000000000000048
      in _pumpe -> _DispatchMessageW(ctypes.byref(msg))

Steckplatz A lief 63 s auf "Bereit"; in dem Moment, in dem im Cadwork-Menue
weitergeklickt wurde, hat das Dispatchen einer Message den Speicher
verletzt. Es ist also nicht nur ein Haenger moeglich, sondern ein Absturz
im Cadwork-Prozess.

Konsequenz:
  * `ui_pumpe` ist **standardmaessig AUS** (`OPEN_MCP_CAD_UI_PUMPE=1` schaltet
    sie bewusst ein). Aus heisst: die Cadwork-Oberflaeche ist eingefroren,
    solange das Plugin laeuft.
  * Ist sie an, laeuft sie **begrenzt** (max. N Messages je Leerlaufrunde)
    UND faengt Zugriffsfehler ab: sie schaltet sich dann selbst ab, statt
    den ganzen Steckplatz mitzunehmen. Der Status meldet das im Klartext.
  * Herzschlag: der Hauptthread stempelt jede Runde. Der Status meldet das
    Alter. Steht der Hauptthread im Leerlauf, sagt der Status das im
    Klartext, statt still zu timeouten.
  * Was die Pumpe NICHT kann und nie konnte: waehrend eines laufenden
    Auftrags bedienbar halten. Sie steht im Leerlauf-Zweig, und der
    Hauptthread steckt waehrend eines Auftrags im cwapi3d-Aufruf. Dafuer
    gibt es 'pause' (Auftrag laeuft fertig, danach ist die UI frei) und
    Auftraege in Batches.

DER AUSWEG: QT-ANTRIEB (`antrieb='qtimer'`)
-------------------------------------------
Ebenfalls am 2026-08-04 in Cadwork 2026 gemessen: PyQt6 ist dort bereits
GELADEN (Cadwork benutzt es selbst), und `QApplication.instance()` liefert
Cadworks eigene Anwendung ("3D", 30 Fenster, Qt 6.8.2 / PyQt 6.8.1).

Damit laesst sich die Grundfrage anders loesen: statt den Hauptthread zu
belegen und Messages selbst zu verteilen, haengt sich der Steckplatz mit
einem `QTimer` in Cadworks EIGENE Ereignisschleife ein und `serve()` kehrt
zurueck. Cadwork behaelt seinen Hauptthread — die Oberflaeche bleibt
bedienbar — und die Auftraege laufen trotzdem sequentiell im Hauptthread,
naemlich im Timer-Rueckruf. Die Win32-Pumpe entfaellt ersatzlos.

Die Arbeit selbst ist in beiden Faellen dieselbe Funktion (`_tick`); nur
wer sie antreibt, unterscheidet sich. `mainthread` bleibt der Default, bis
`qtimer` im echten Cadwork abgenommen ist.

PROTOKOLL (JSON-Lines, rueckwaertskompatibel)
---------------------------------------------
  Request:  {"id": int, "method": str, "params": {...}}
  Response: {"id": int, "ok": true,  "result": ...}
            {"id": int, "ok": false, "error": str, "message": str,
             "details": str}

Neu und alle optional (alte Clients funktionieren unveraendert weiter):
  description     Klartext, was der Auftrag tut
  operation_id    Kennung des Clients fuer diesen Auftrag
  access_mode     "read" | "write"  — fehlt/unbekannt => "write"
  client_id       stabile Kennung fuer die Schreiblizenz
  client_label    lesbarer Name fuer die Anzeige
  expect_document Teilstring, der im Dokumentnamen vorkommen muss
  paketlauf       {"paket": k, "pakete": n} — dieser Auftrag ist Paket k von
                  n eines Paketlaufs (`execute_cadwork_batch` schickt es mit).
                  In 'Auto' wird dann jedes Paket sofort nachgezogen, statt
                  seine Bauteile bis zum Ende des Laufs zu verstecken.
"""

import contextlib
import io
import json
import logging
import math
import os
import queue
import re
import socket
import sys
import threading
import time
import traceback

# 2.18.1 (2026-09-26): Hinweis beim Nachziehen nennt nur gemessene Kosten
#   (0,6 bis 4,7 s je 1000 Bauteile statt geschaetzter "1 bis 5 s").
# 2.18.0 (2026-09-26): Paketlauf in 'Auto' paketweise statt mit Vorhang bis
#   zum Ende. Befund im Film 2026-09-25 (Log A 23:29-23:43): 48 Pakete VBA
#   je 15-20 s, die Schrauben erschienen waehrend jedes Pakets und
#   verschwanden am Paketende wieder — nachgezogen wurde im ganzen Lauf nur
#   zweimal. Siehe `_paket_nachziehen`.
# 2.17.0 (2026-09-25): zwei Befunde aus dem Viewer-Modus.
#   * Der Qt-Takt haelt Auftraege zurueck, solange Cadwork selbst im
#     Hauptthread arbeitet (modaler Dialog, Menue, verschachtelte
#     Ereignisschleife, Wiedereintritt) — siehe `_takt`. Anlass: Absturz
#     14 s nach zwei Leseauftraegen mitten in der Viewer-Modus-Rechnung.
#   * EIN Dienst je Prozess, ueber ein Buch in `sys.modules`, das jedes
#     frische Laden des Kerns ueberlebt — siehe `_prozess`. Anlass: zwei
#     gesammelte Plugin-Klicks starteten C und D im selben Cadwork.
# 2.16.3 (2026-09-25): Schnellzeichnen folgt beim Start der Vorgabe-Stufe
#   ('Auto' = schnell), statt bis zum ersten Griff an den Regler aus zu
#   bleiben, waehrend das Dock 'Auto' zeigte.
# 2.2.1 (2026-08-06): `nachgezogen_gesamt` im Status. `bildschirm_aus` faellt
#   schon VOR dem Nachziehen auf False — wer daran misst, misst mittendrin
#   und haelt einen geglueckten Lauf ueber 2000 Bauteile faelschlich fuer
#   wirkungslos. Genau so passiert.
# 2.2.0 (2026-08-06): Der Anzeigebug ist behoben — im Dunkeln entstandene
#   Elemente werden beim Wiedereinschalten angefasst, sonst bleiben sie
#   unsichtbar korrekt. Siehe _dunkle_elemente_nachziehen.
# 2.1.0 (2026-08-06): Auftraege melden ihre neu erzeugten Elemente in
#   Cadworks Undo-Stack an — vorher lief "Rueckgaengig" nachweislich ins Leere.
# Die Version steht hier, damit ein `ping` beweist, ob ein Neustart des
# Steckplatzes wirklich gegriffen hat; ein Klick auf ein LAUFENDES Plugin
# startet es naemlich nicht neu.
# 2.16.0 — eine DRITTE Zahl mit Absicht: 2.14 ist der Stand, aus dem dieses
# Repo hervorging, 2.15 der aus dem Cadwork-Benutzerprofil geretteten
# Codex-Arbeit. Dieser Kern ist beides zusammen und damit keins von beiden.
#
# Wofuer die Zahl da ist: ein `ping` soll beweisen, ob ein Neustart des
# Steckplatzes wirklich gegriffen hat — ein Klick auf ein LAUFENDES Plugin
# startet es naemlich nicht neu. Sie wurde bei 347 geaenderten Zeilen und
# der ganzen Registry NICHT gehoben; ein ping konnte diesen Kern von 2.14
# nicht unterscheiden.
# 2.19.0 (2026-10-07, K12): Haken `cfg.lauf_anzeige` (per getattr, wie
#   require_qtimer). Ist er gesetzt, zeigt das DASHBOARD die Arbeitsanzeige
#   ("KI zeichnet" / "KI schaut ins Modell" ...) statt des eigenen Fensters
#   "Open MCP CAD zeichnet …" — der Kern ruft ihn VOR jedem Auftrag eines
#   Laufs (`start`, auch lesend), danach (`fortschritt`) und am Ende
#   (`ende`). Ohne Haken wie 2.18. `LAUF_ANZEIGE_HAKEN` sagt einem
#   Dashboard, dass dieser Kern ihn kennt.
# 2.19.1 (2026-10-07, Gegenpruefung K12): derselbe Haken erfaehrt auch JEDEN
#   Auftrag ausserhalb eines Laufs (`auftrag`, vor dem Ausfuehren) — die
#   Zustandspille im Kopf des Docks sagt "Zeichnet"/"Liest" WAEHREND des
#   Auftrags, nicht erst im naechsten Takt (der waehrend des Auftrags nicht
#   laeuft). Wirft er dort, steht es einmal im Log; der Auftrag laeuft.
# 2.20.0 (2026-10-10, Cadwork 2025): der Qt-Antrieb, die Sonden und das
#   eigene Fenster laufen mit PyQt6 ODER PyQt5 (`_qt_bindung`, `_qt_namen`);
#   Cadwork 2025 bringt nur PyQt5 mit. Status und Log nennen den Qt-Stand
#   (`qt`, "Qt-Antrieb mit …").
CORE_VERSION = "2.20.0"
PROTOKOLL_VERSION = 2

# Eigener Logger statt des Root-Loggers: sonst wandern Cadwork-fremde
# Bibliotheksmeldungen in die Logdatei — und umgekehrt landeten frueher die
# Zeilen aller Steckplaetze in DERSELBEN Datei, ohne dass man sie einer
# Instanz zuordnen konnte.
LOG = logging.getLogger("omcad.connect")


# --- Qt: PyQt6 (Cadwork 2026) oder PyQt5 (Cadwork 2025) --------------------
#
# Anlass (gemessen vom Maintainer, 2026-10-10): Cadwork 3D 2025 bringt
# Python 3.12.7 und PyQt5 mit, kein PyQt6. Der Kern importierte nur PyQt6 —
# der Qt-Antrieb fiel dort aus, und ohne `require_qtimer` waere er auf
# 'mainthread' zurueckgefallen (Cadwork blockiert).
#
# DIESELBE Regel wie `omcad_qt.waehlen` im Dock (die Kopie ist Absicht: der
# Kern laeuft auch in den Ordnern B-F, die keine UI-Module haben;
# `test_offline` Q1 misst beide in denselben Welten):
#   1. eine schon GELADENE Bindung gewinnt (zuerst PyQt6) — mit ihr hat
#      Cadwork seine QApplication gebaut;
#   2. sonst PyQt6, wenn es sich importieren laesst;
#   3. sonst PyQt5.
# Was in Qt 6 in QtGui liegt und in Qt 5 in QtWidgets (QAction, QShortcut)
# sucht `_qt_namen` im jeweils anderen Modul. Voll qualifizierte Enums
# (`Qt.WindowType.Tool`) gehen in PyQt5 5.15 auch (gemessen 5.15.11).

QT_BINDUNGEN = ("PyQt6", "PyQt5")


def _qt_bindung(module=None, importieren=None):
    """-> "PyQt6" | "PyQt5". ImportError, wenn keine da ist.

    `module`/`importieren` ersetzen nur die Gates (Q1).
    """
    import importlib                                   # noqa: PLC0415
    module = sys.modules if module is None else module
    importieren = importieren or importlib.import_module
    for name in QT_BINDUNGEN:
        if (name + ".QtCore") in module:
            return name
    gruende = []
    for name in QT_BINDUNGEN:
        try:
            importieren(name + ".QtCore")
            return name
        except Exception as exc:                       # noqa: BLE001
            gruende.append("%s: %s" % (name, exc))
    raise ImportError("Weder PyQt6 noch PyQt5 (%s)" % "; ".join(gruende))


def _qt_namen(teil, *namen):
    """Namen aus `<Bindung>.<teil>` — einer allein, mehrere als Tupel."""
    import importlib                                   # noqa: PLC0415
    bindung = _qt_bindung()
    modul = importlib.import_module(bindung + "." + teil)
    werte = []
    for name in namen:
        wert = getattr(modul, name, None)
        if wert is None:
            ander = {"QtGui": "QtWidgets", "QtWidgets": "QtGui"}.get(teil)
            if ander:
                wert = getattr(importlib.import_module(
                    bindung + "." + ander), name, None)
        if wert is None:
            raise ImportError("%s.%s hat kein %s" % (bindung, teil, name))
        werte.append(wert)
    return werte[0] if len(werte) == 1 else tuple(werte)


def qt_stand():
    """'PyQt5 5.15.11 / Qt 5.15.2' — fuer Log und Status. Wirft nie."""
    try:
        bindung = _qt_bindung()
        qtcore = sys.modules.get(bindung + ".QtCore")
        return "%s %s / Qt %s" % (bindung,
                                  getattr(qtcore, "PYQT_VERSION_STR", "?"),
                                  getattr(qtcore, "QT_VERSION_STR", "?"))
    except Exception as exc:                           # noqa: BLE001
        return "kein Qt (%s)" % exc


# --- Zustaende ------------------------------------------------------------

ZUSTAND_TEXT = {
    "stopped": "Aus",
    "starting": "Wird gestartet",
    "ready": "Bereit",
    "busy_read": "Liest Modell",
    "busy_write": "Bearbeitet Modell",
    "paused": "Pausiert",
    "stopping_after_job": "Wird nach dem Auftrag beendet",
    "error": "Stoerung",
}

# Zustaende, in denen ein Auftrag im Cadwork-Hauptthread laeuft.
BESCHAEFTIGT = ("busy_read", "busy_write")
# Zustaende, in denen sofortiges Beenden erlaubt ist. Bewusst als Positiv-
# liste: ein unbekannter Zustand faellt damit auf "nicht beenden" — die
# sichere Richtung.
SOFORT_BEENDBAR = ("ready", "paused", "error", "starting", "stopped",
                   "stopping_after_job")


# --- Konfiguration --------------------------------------------------------

class Konfiguration:
    """Alles, was die Steckplaetze unterscheidet — sonst nichts.

    Port, Instanz-Kennung, Anzeigename und Logdatei sind Konfiguration.
    Es gibt bewusst KEINE Implementierung je Steckplatz.
    """

    #: Erlaubte Instanz-Kennungen. Bis 2026-09-20 stand hier fest
    #: ("A", "B", "C", "D") — der Guard stammte vom 2026-08-04, als es
    #: wirklich nur vier gab. Am 2026-08-15 wurde auf SECHS erhoeht, der
    #: Guard blieb stehen: der Generator erzeugte E und F, Cadwork zeigte
    #: sie im Menue, und ihr Start scheiterte an dieser Zeile. Fuenf
    #: Wochen lang, ohne dass ein Gate es sah — keines hat je einen
    #: Steckplatz KONFIGURIERT, sie pruefen nur die Liste.
    #:
    #: Deshalb steht hier jetzt kein Inventar mehr, sondern eine REGEL:
    #: ein bis zwei Zeichen, Buchstabe oder Ziffer. Das deckt A..Z, 0..9
    #: und zweistellige Kennungen fuer dynamisch vergebene Plaetze ab und
    #: altert nicht mit der Anzahl.
    #: ZWEI Formen, und nur diese beiden:
    #:   * eine kurze Kennung: ein oder zwei Buchstaben/Ziffern (A..Z, 0..99)
    #:   * eine PORTNUMMER: vier oder fuenf Ziffern — so heisst ein
    #:     Steckplatz ausserhalb des Standardbereichs (siehe `kennung_fuer`)
    #:
    #: Ein schlichtes `{1,5}` waere einfacher gewesen, haette aber auch
    #: "ABC" angenommen. Das ist keine Kennung, die dieser Code je bildet —
    #: und was er nicht bildet, soll er auch nicht annehmen. (Das Gate hat
    #: genau darauf bestanden: R5 verlangt, dass "ABC" abgelehnt wird.)
    INSTANZ_MUSTER = re.compile(r"^([A-Z0-9]{1,2}|[0-9]{4,5})$")

    def __init__(self, instanz=None, port=None, anzeigename=None,
                 log_datei=None, host="127.0.0.1"):
        # instanz=None heisst: aus dem Port ableiten, sobald er feststeht
        # (`serve()` -> `kennung_fuer`). Das ist der dynamische Steckplatz:
        # EIN Eintrag im Cadwork-Menue, so oft gestartet wie noetig.
        #
        # Warum None und kein Wort wie "AUTO": das Muster laesst hoechstens
        # zwei Zeichen zu — eine vierbuchstabige Marke kaeme hier gar nicht
        # durch, und die Markierung waere still wirkungslos gewesen.
        if instanz is not None:
            instanz = str(instanz).upper()
            if not self.INSTANZ_MUSTER.match(instanz):
                raise ValueError(
                    "instanz muss ein bis zwei Buchstaben oder Ziffern sein, "
                    "nicht %r" % instanz)
        elif port is not None:
            raise ValueError(
                "instanz=None gibt es nur zusammen mit port=None — mit "
                "festem Port muss die Kennung feststehen")
        self.instanz = instanz
        # port=None heisst: beim Start einen freien Port nehmen. Erst
        # `serve()` entscheidet ihn — vorher steht hier None, und wer ihn
        # vorher liest, bekommt kein stilles Falsch, sondern None.
        self.port = None if port is None else int(port)
        self.host = host
        # Bei instanz=None bleiben beide None, bis serve() den Port kennt.
        self.anzeigename = anzeigename or (
            ("Open MCP CAD %s" % instanz) if instanz else None)
        self.log_datei = log_datei or (
            (r"C:\Users\Public\OpenMcpCad_%s.log" % instanz)
            if instanz else None)

        # --- Laufzeit-Stellschrauben (Umgebungsvariablen, sonst Default) ---
        # ui_pumpe: siehe Modul-Docstring. Default AUS — und diesmal gemessen.
        #
        # Der Weg dahin, weil er zaehlt: erst AUS (Verdacht aus dem Code),
        # dann AN (2026-08-04: "im Modus bereit kann man das Dokument
        # jetzt schon bedienen"), dann wieder AUS — weil der erste echte Lauf
        # in Cadwork 2026 am 2026-08-04 22:06:39 dies lieferte:
        #
        #   OSError: exception: access violation reading 0x0000000000000048
        #     File omcad_bridge_core.py, line ..., in _pumpe
        #       _DispatchMessageW(ctypes.byref(msg))
        #
        # Steckplatz A lief 63 s auf "Bereit"; in dem Moment, in dem in
        # Cadwork weitergeklickt wurde, hat das Dispatchen einer Message in
        # Cadworks Fensterprozedur den Speicher verletzt. Das ist kein
        # Haenger, das ist ein Absturz im Cadwork-Prozess — und der kann
        # ungesicherte Arbeit kosten. Bedienbarkeit im Leerlauf ist das
        # nicht wert.
        #
        # OPEN_MCP_CAD_UI_PUMPE=1 schaltet sie bewusst wieder ein; sie schaltet
        # sich dann beim ersten Zugriffsfehler selbst ab (siehe _pumpe),
        # statt den ganzen Dienst mitzunehmen.
        self.ui_pumpe = _env_bool("OPEN_MCP_CAD_UI_PUMPE", False)
        self.ui_pumpe_max = _env_int("OPEN_MCP_CAD_UI_PUMPE_MAX", 200)
        # Antrieb — seit 2026-08-04 23:15 ist 'qtimer' der Standard.
        #
        # Nachgewiesen an Steckplatz D in Cadwork 2026: Antrieb qtimer,
        # Zustand "Bereit", Herzschlag 0,06 s alt, Leseauftrag 437 ms,
        # cwapi3d-Aufruf 313 ms — UND Cadwork war dabei normal bedienbar
        # ("D gestartet, cadwork laesst sich bedienen"). Mit 'mainthread'
        # war es das im selben Test NICHT.
        #
        # Faellt der Qt-Antrieb aus (kein PyQt6/PyQt5, keine QApplication), geht
        # serve() automatisch auf 'mainthread' zurueck und schreibt den
        # Grund ins Log. OPEN_MCP_CAD_ANTRIEB=mainthread erzwingt das alte
        # Verhalten.
        self.antrieb = os.environ.get("OPEN_MCP_CAD_ANTRIEB", "qtimer")
        # Schreiblizenz
        self.lizenz_ttl_s = _env_int("OPEN_MCP_CAD_LIZENZ_TTL", 120)
        # Wie viele Auftraege duerfen warten, bevor abgelehnt wird
        self.max_warteschlange = _env_int("OPEN_MCP_CAD_MAX_QUEUE", 16)
        # Dokumentname im Leerlauf auffrischen (0 = nie)
        self.dok_auffrischen_s = _env_int("OPEN_MCP_CAD_DOK_REFRESH", 5)
        # Kleines Anzeigefenster IN Cadwork (nur beim Qt-Antrieb). Ohne es
        # gibt es in Cadwork kein Zeichen dafuer, dass eine Verbindung
        # laeuft — der Plugin-Knopf bleibt beim Qt-Antrieb nicht gedrueckt.
        self.fenster = _env_bool("OPEN_MCP_CAD_FENSTER", True)
        # Auftraege zurueckhalten, solange Cadwork selbst im Hauptthread
        # arbeitet (siehe `_takt`). Abschaltbar nur fuer die Fehlersuche:
        # schlaegt in Cadwork eine Sonde dauerhaft falsch an, laufen die
        # Auftraege mit OPEN_MCP_CAD_ZURUECKHALTEN=0 wieder — ungeschuetzt.
        # Den Wiedereintritt (Takt im Takt) haelt der Kern immer ab.
        self.zurueckhalten = _env_bool("OPEN_MCP_CAD_ZURUECKHALTEN", True)

    def __repr__(self):
        # %s, nicht %d: vor `serve()` sind instanz und port beim dynamischen
        # Steckplatz None, und ein repr(), das dabei TypeError wirft, macht
        # aus jeder Fehlersuche eine zweite Fehlersuche.
        return "<Konfiguration %s Port %s>" % (self.instanz, self.port)


# --- Registry der laufenden Steckplaetze ----------------------------------
#
# WOFUER. Bis 2026-09-20 war jeder Steckplatz ein fester Port und ein
# eigener Plugin-Ordner: sechs Menueeintraege, sechs Eintraege in der
# Host-Konfiguration, und wer einen siebten wollte, musste ausrollen.
# Der Nutzer hat zweimal nach "unendlich" gefragt (2026-08-15 und 2026-09-20).
#
# Der Weg dahin ist nicht, die Zahl zu erhoehen, sondern die Bindung
# umzudrehen: ein Steckplatz sucht sich beim Start einen FREIEN Port und
# traegt sich mit seinem Dokumentnamen ein. Wer ihn sucht, fragt nicht
# mehr "welcher Port?", sondern "in welcher Instanz ist Seeblick offen?".
#
# WARUM EINE DATEI JE INSTANZ und nicht eine gemeinsame Liste: mehrere
# Cadwork-Fenster starten gleichzeitig. Eine gemeinsame Datei braeuchte ein
# Lock, und ein Lock, das jemand haelt, waehrend sein Prozess abstuerzt,
# ist schlimmer als das Problem. Je Instanz eine eigene Datei heisst: kein
# Lock, kein Konflikt, und ein abgestuerzter Prozess hinterlaesst genau
# eine verwaiste Datei, die der naechste Leser wegraeumt.
#
# WAS EIN EINTRAG NICHT IST: eine Zusage, dass der Steckplatz laeuft. Er
# kann abgestuerzt sein. Deshalb prueft `registry_lesen()` jeden Eintrag
# gegen die PID — und seit 2.17.1 gegen die Startzeit des Prozesses, denn
# Windows vergibt PIDs neu — und raeumt tote weg. Die Wahrheit ist der
# Prozess, nicht die Datei.

REGISTRY_ORDNER = os.environ.get(
    "OPEN_MCP_CAD_REGISTRY", r"C:\Users\Public\open-mcp-cad")

#: Portbereich fuer die automatische Vergabe. Die ersten sechs sind
#: weiterhin die festen Steckplaetze A-F — wer sie belegt hat, bekommt sie
#: nicht doppelt, denn die Suche prueft jeden Port, bevor sie ihn nimmt.
PORT_VON = 53127
PORT_BIS = 53199


def port_frei(port, host="127.0.0.1"):
    """Laesst sich `port` binden? Gemessen, nicht aus der Registry geraten.

    Ein Port kann von etwas ganz anderem belegt sein als von uns; die
    Registry weiss davon nichts. Deshalb ist das Binden die Probe.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # KEIN SO_REUSEADDR: das wuerde unter Windows einen Port als frei
        # melden, den gerade jemand haelt — genau die Falschaussage, die
        # diese Funktion verhindern soll.
        s.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def freier_port(host="127.0.0.1", von=None, bis=None):
    """Der erste freie Port im Bereich. Wirft, wenn keiner frei ist.

    Zwischen Pruefen und Binden liegt ein Moment, in dem ein anderer
    Prozess zugreifen kann. Das ist hingenommen: `serve()` bindet gleich
    darauf und faellt bei Misserfolg auf den naechsten Port zurueck — die
    Vergabe entscheidet also das Binden, nicht diese Funktion.
    """
    von = PORT_VON if von is None else int(von)
    bis = PORT_BIS if bis is None else int(bis)
    for p in range(von, bis + 1):
        if port_frei(p, host):
            return p
    raise RuntimeError(
        "kein freier Port zwischen %d und %d — laufen wirklich %d Instanzen?"
        % (von, bis, bis - von + 1))


def kennung_fuer(port):
    """Die Instanz-Kennung, die zu einem Port gehoert.

    Die ersten 26 Plaetze bekommen A..Z — damit heisst der Steckplatz auf
    Port 53127 weiterhin "A", genau wie in allen Host-Konfigurationen und
    Logdateien, die es schon gibt. Darueber wird durchgezaehlt (26..72).
    Beides passt in `Konfiguration.INSTANZ_MUSTER`.
    """
    i = int(port) - PORT_VON
    if i < 0 or int(port) > PORT_BIS:
        # AUSSERHALB DES BEREICHS: die Portnummer selbst.
        #
        # Hier stand "?" — und das war still verheerend: die Kennung geht in
        # den Namen der Logdatei (`OpenMcpCad_%s.log`), und "?" ist unter
        # Windows im Dateinamen VERBOTEN. Das Log waere nicht angelegt
        # worden, ohne dass jemand erfaehrt warum. Ausserdem genuegte "?"
        # dem eigenen INSTANZ_MUSTER nicht, das die Konfiguration erzwingt.
        #
        # Ein Port ausserhalb kommt vor: das Dashboard kann einen Socket
        # reservieren, den es anderswoher hat, und die Tests arbeiten mit
        # temporaeren Ports.
        return str(int(port))
    return chr(ord("A") + i) if i < 26 else str(i)


# Spielraum zwischen dem Start des Prozesses und `start` im Eintrag. Der
# Kern traegt sich erst nach listen() ein, gemessen 10 s bis Minuten nach
# dem Start von Cadwork; die Toleranz faengt nur Uhr-Aufloesung und kleine
# Korrekturen der Systemuhr ab. Dieselbe Regel wie die Leser in
# open_mcp_cad/registry.py, connect_client.py, omcad_verbindungen_client.py
# (Gate: test_bootstrap G0-G5, test_registry R57-R59).
UHR_TOLERANZ_S = 2.0

_K32 = None


def _kernel32():
    """Eigene kernel32-Instanz: argtypes/restype hier aendern nichts an
    `ctypes.windll.kernel32`, das andere Module in Cadworks Prozess teilen."""
    global _K32
    if _K32 is None:
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
        _K32 = k
    return _K32


def _prozess_windows(pid):
    """(lebt, gestartet): Erzeugungszeit in s seit 1970 oder None.

    Nur SYNCHRONIZE zu haben -> die Probe ohne Startzeit.
    """
    import ctypes
    from ctypes import wintypes as w
    k = _kernel32()
    # SYNCHRONIZE fuer das Warten, PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
    # fuer die Startzeit. Gibt es nur SYNCHRONIZE, fehlt eben die Startzeit.
    h = k.OpenProcess(0x00100000 | 0x1000, False, pid)
    abfragbar = bool(h)
    if not h:
        h = k.OpenProcess(0x00100000, False, pid)             # SYNCHRONIZE
        if not h:
            return False, None
    try:
        # Ein beendeter Prozess laesst sich weiter oeffnen, solange
        # irgendwer noch einen Handle auf ihn haelt (gemessen 2026-09-25:
        # Cadwork geschlossen, sein Eintrag galt weiter als laufend).
        # Beendet ist er, wenn das Objekt signalisiert (WAIT_OBJECT_0 = 0).
        if k.WaitForSingleObject(h, 0) == 0:
            return False, None
        if not abfragbar:
            return True, None
        zeiten = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(z) for z in zeiten]):
            return True, None
        ft = (zeiten[0].dwHighDateTime << 32) | zeiten[0].dwLowDateTime
        return True, ft / 1e7 - 11644473600.0     # 1601 -> 1970
    finally:
        k.CloseHandle(h)


def _pid_lebt(pid, seit=None):
    """Laeuft der Prozess noch — und ist es der, der sich eingetragen hat?

    `seit` ist `start` aus dem Eintrag. Windows vergibt PIDs neu; ein
    Prozess, der NACH dem Eintrag gestartet ist, kann ihn nicht geschrieben
    haben (Befund 2026-09-25: ein beendetes Cadwork galt als laufend, weil
    seine PID einem anderen Prozess gehoerte). Ohne `seit` nur die PID.
    Windows ueber die API, sonst os.kill(0).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            lebt, gestartet = _prozess_windows(pid)
        except Exception:                                   # noqa: BLE001
            # Im Zweifel als lebend melden: einen Eintrag faelschlich zu
            # loeschen kostet eine laufende Verbindung, ihn faelschlich zu
            # behalten kostet eine Zeile, die der naechste Leser aufraeumt.
            return True
        if not lebt:
            return False
        try:
            seit = float(seit)
        except (TypeError, ValueError):
            return True
        if gestartet is None or not math.isfinite(seit):
            return True
        return gestartet <= seit + UHR_TOLERANZ_S
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _registry_pfad(port):
    return os.path.join(REGISTRY_ORDNER, "instanz-%d.json" % int(port))


def registry_eintragen(cfg, dok_name="", pid=None):
    """Traegt diesen Steckplatz ein. Fehler hier duerfen nie den Start kippen."""
    try:
        os.makedirs(REGISTRY_ORDNER, exist_ok=True)
        eintrag = {
            "port": int(cfg.port),
            "instanz": cfg.instanz,
            "anzeigename": cfg.anzeigename,
            "pid": int(pid if pid is not None else os.getpid()),
            "dokument": dok_name or "",
            "kern": CORE_VERSION,
            "protokoll": PROTOKOLL_VERSION,
            "start": time.time(),
        }
        tmp = _registry_pfad(cfg.port) + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump(eintrag, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, _registry_pfad(cfg.port))    # atomar
        return eintrag
    except Exception as exc:                                # noqa: BLE001
        LOG.warning("Registry-Eintrag nicht geschrieben: %s", exc)
        return None


def registry_dokument_setzen(port, dok_name):
    """Frischt den Dokumentnamen eines Eintrags auf.

    Der Dokumentname ist das, wonach gesucht wird — er muss der Wahrheit
    folgen, wenn der Nutzer eine andere Datei oeffnet.
    """
    try:
        p = _registry_pfad(port)
        if not os.path.exists(p):
            return False
        with io.open(p, encoding="utf-8") as fh:
            eintrag = json.load(fh)
        if eintrag.get("dokument") == (dok_name or ""):
            return False                 # nichts zu tun, keine Schreiblast
        eintrag["dokument"] = dok_name or ""
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump(eintrag, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except Exception as exc:                                # noqa: BLE001
        LOG.debug("Registry-Dokument nicht aktualisiert: %s", exc)
        return False


def registry_austragen(port):
    """Nimmt den Eintrag heraus. Ein fehlender Eintrag ist kein Fehler."""
    try:
        p = _registry_pfad(port)
        if os.path.exists(p):
            os.remove(p)
            return True
    except Exception as exc:                                # noqa: BLE001
        LOG.debug("Registry-Eintrag nicht entfernt: %s", exc)
    return False


def registry_lesen(aufraeumen=True):
    """Alle laufenden Steckplaetze, nach Port sortiert.

    Eintraege, deren Prozess nicht mehr lebt, werden entfernt — ein
    abgestuerztes Cadwork hinterlaesst sonst eine Zeile, die fuer immer
    "laeuft" behauptet.
    """
    ergebnis = []
    try:
        namen = sorted(os.listdir(REGISTRY_ORDNER))
    except OSError:
        return ergebnis                  # Ordner gibt es noch nicht: leer
    for n in namen:
        if not (n.startswith("instanz-") and n.endswith(".json")):
            continue
        p = os.path.join(REGISTRY_ORDNER, n)
        try:
            with io.open(p, encoding="utf-8") as fh:
                eintrag = json.load(fh)
        except Exception:                                   # noqa: BLE001
            if aufraeumen:
                try:
                    os.remove(p)         # unlesbar ist so gut wie tot
                except OSError:
                    pass
            continue
        if not _pid_lebt(eintrag.get("pid"), eintrag.get("start")):
            if aufraeumen:
                try:
                    os.remove(p)
                except OSError:
                    pass
            continue
        ergebnis.append(eintrag)
    ergebnis.sort(key=lambda e: e.get("port", 0))
    return ergebnis


def registry_finden(dokument):
    """Die Eintraege, deren Dokumentname `dokument` enthaelt (ohne Gross/Klein).

    Liefert eine LISTE, keinen einzelnen Treffer: zwei offene Dateien
    koennen denselben Teilstring tragen, und dann muss der Aufrufer
    entscheiden statt raten. Genau diese Verwechslung ist der Grund, warum
    es OPEN_MCP_CAD_EXPECT_DOC ueberhaupt gibt.
    """
    suche = (dokument or "").strip().lower()
    if not suche:
        return []
    return [e for e in registry_lesen()
            if suche in (e.get("dokument") or "").lower()]


def _env_bool(name, default):
    wert = os.environ.get(name)
    if wert is None:
        return default
    return wert.strip().lower() in ("1", "true", "ja", "yes", "on", "an")


def _env_int(name, default):
    wert = os.environ.get(name)
    if wert is None:
        return default
    try:
        return int(wert)
    except (TypeError, ValueError):
        return default


# --- Feste Grenzen --------------------------------------------------------

SOCKET_BACKLOG = 4
ACCEPT_TIMEOUT_SECONDS = 1.0    # Listener schaut jede Sekunde auf Stop
POLL_INTERVAL_SECONDS = 0.05    # Hauptthread schaut alle 50 ms auf Jobs
JOB_WAIT_TIMEOUT_SECONDS = 0.5  # Worker-Wartepoll (sauberer Shutdown)
ANTWORT_WARTEN_S = 3.0          # Wie lange Shutdown auf das Absenden wartet
HERZSCHLAG_GRENZE_S = 3.0       # ab hier gilt der Hauptthread als haengend
SCHNELL_RUHE_S = 1.5    # so lange ohne Auftrag, dann Bildschirm wieder an

# --- Zeichenmodi ---------------------------------------------------------
# EIN Regler, EINE Frage: "wie sehr darf das Zeichnen mich stoeren?"
#
# Die Stufen sind aus Messungen abgeleitet, nicht geraten (2026-08-06,
# _zeichenmodi_messen.py, je 300 Bauteile MIT Ausklinkung, zwischen den
# Varianten aufgeraeumt damit jede gleich gross startet):
#
#   Haeppchen   ms/Teil   laengste Blockade   Hauptthread gesamt
#   300 (1x)      27,4          7,78 s              7,78 s
#    50 (6x)      33,0          1,38 s              7,92 s
#    25 (12x)     39,9          0,71 s              8,02 s
#    10 (30x)     59,0          0,30 s              8,40 s
#
# Der Befund dahinter: "Hauptthread gesamt" bleibt praktisch KONSTANT.
# Kleinere Haeppchen kosten keine Cadwork-Arbeit, nur Uebertragung — man
# kauft Bedienbarkeit also mit Wartezeit, nicht mit Rechenzeit.
#
# DREI Stufen, deutsch. Rueckmeldung 2026-08-07, nachdem 'cowork' im Echtbetrieb
# durchgefallen ist: "wuerde den modus einfach rausstreichen ... ich benutze
# sowieso eigentlich immer max. und wenn ich zusehen will stelle ich es auf
# slow, fast keine ahnung fuer was der eigentlich ist."
#
# Damit hat KEINE Stufe mehr eine harte Grenze — und das ist ehrlicher als
# vorher: die Grenze beruhte auf einer Schaetzung (Bauteile x gelerntem
# Preis), und die lag im 16 627-Element-Modell um den Faktor 7 daneben
# (geschaetzt 35 ms je Bauteil, gemessen rund 240). Sie liess Auftraege
# durch, die 2,38 s blockierten, wo 0,5 s erlaubt waren. Eine Grenze, die
# nicht haelt, ist schlimmer als keine.
#
# `blockade_s` bleibt als EMPFEHLUNG (Haeppchengroesse), nicht als Sperre.
ZEICHENMODI = (
    {"schluessel": "auto", "anzeige": "Auto", "schnell": True,
     "blockade_s": 1.0, "balken": False, "paketweise": True,
     "text": "Der Normalfall. Zeichnet zügig, versteckt Halbfertiges und "
             "zeigt das Ergebnis am Stück, einen Paketlauf Paket für "
             "Paket."},
    # KEINE Haeppchen-Empfehlung (blockade_s = None), und das ist der Witz
    # dieser Stufe: Cadworks Auffrischung bleibt AN, also zeichnet Cadwork
    # nach jedem einzelnen Bauteil neu — man sieht die Wand entstehen.
    # Kleine Haeppchen wuerden das kaputtmachen: zwischen zwei Auftraegen
    # liegt Uebertragungszeit, die Wand waechst dann stockend in Schueben.
    # Rueckmeldung 2026-08-07: "gibts keinen modus mehr der es altmodisch element
    # fuer element macht, wo man schoen zusehen kann?" — doch, dieser, aber
    # nur ohne Zerstueckelung.
    {"schluessel": "langsam", "anzeige": "Langsam", "schnell": False,
     "blockade_s": None, "balken": False, "vorhang": False,
     "text": "Zum Zuschauen: Cadwork zeichnet jedes Bauteil einzeln nach, "
             "du siehst die Wand entstehen. Der langsamste Modus — und der "
             "einzige ohne Vorhang."},
    {"schluessel": "schnell", "anzeige": "Schnell", "schnell": True,
     "blockade_s": None, "balken": True,
     "text": "Alles am Stück, ohne Zwischenbilder. Während des Laufs läuft "
             "ein Ladebalken; das Ergebnis erscheint erst, wenn es fertig "
             "ist. Cadwork ist dabei nicht bedienbar."},
)
# VORHANG ueberall AUSSER in 'slow'. Am 2026-08-06 kam die Frage, ob 'auto' das
# auch macht — es tat es nicht, und dafuer gab es keinen guten Grund:
# gemessen kostet der Vorhang 0,017 ms je Bauteil, also 63 ms fuer 3666
# Stueck (0,15 % eines 44-Sekunden-Laufs). Einen halbfertigen Zustand ohne
# Material und ohne Ausklinkungen zu zeigen hilft dagegen nie — er sieht aus
# wie ein Fehler. 'slow' ist und bleibt die Stufe zum Zuschauen; dort waere
# ein Vorhang das Gegenteil des Zwecks.
for _m in ZEICHENMODI:
    _m.setdefault("vorhang", _m["schluessel"] != "langsam")
# PAKETWEISE: ein Paketlauf (`execute_cadwork_batch`, Feld `paketlauf`) zieht
# jedes Paket gleich nach seinem Ende nach, statt seine Bauteile bis zum Ende
# des Laufs hinter dem Vorhang zu halten. Befund im Film 2026-09-25: ein
# Paket rechnet 15-20 s, Cadwork zeichnet die neuen Bauteile waehrenddessen
# schon (der Vorhang faellt erst am Auftragsende), und dann verschwinden sie
# bis zum Ende des Laufs — die Schrauben blinkten 48-mal auf. Nur in 'Auto':
# 'Schnell' verspricht ausdruecklich keine Zwischenbilder (Rueckmeldung
# 2026-08-06 zu 'max': "die zwischenschritte wurden immer angezeigt"), und in
# 'Langsam' bleibt die Auffrischung ohnehin an.
for _m in ZEICHENMODI:
    _m.setdefault("paketweise", False)

# WO der Fortschritt steht. Rueckmeldung 2026-08-06: "bei cowork soll es auch nicht
# drueber sein, da will man ja selber noch zeichnen, aber du kannst bei
# cowork und slow unten rechts den ladebalken anzeigen lassen."
# Genau die richtige Unterscheidung: das eigene Fenster steht mitten im
# Bild und ist dort im Weg, wo man nebenher arbeitet. In den beiden Stufen,
# die fuers Mitarbeiten und Zuschauen da sind, bleibt es deshalb bei
# Cadworks unauffaelligem Balken unten rechts.
POPUP_STUFEN = ("auto", "schnell")
for _m in ZEICHENMODI:
    _m["popup"] = _m["schluessel"] in POPUP_STUFEN
MODUS_VORGABE = "auto"
# Startwert fuer "was kostet ein Bauteil". Gemessen an Balken MIT
# Ausklinkung; der Wert wird im Betrieb gelernt (siehe tempo_lernen), weil
# er an Bauteilart UND Modellgroesse haengt und sonst nach dem ersten
# anderen Lauf falsch waere.
MS_JE_TEIL_START = 35.0
# Etwas Luft, bevor abgelehnt wird — sonst kippt jede Schaetzungenauigkeit
# einen Auftrag, der in Wahrheit knapp gepasst haette.
# Ab dieser ERWARTETEN Dauer kommt der Ladebalken. Gerechnet aus der
# angemeldeten Bauteilzahl mal dem gelernten Preis je Bauteil — und
# ersatzweise aus der bisher verstrichenen Zeit des Laufs, damit auch ein
# Auftrag ohne Anmeldung ihn ausloest. In 'max' kommt er immer sofort.
BALKEN_AB_S = 1.0
# Dringlichkeit 1..5, wenn die KI keine angibt. Bewusst nicht alles auf 3:
# ein Fehler ist im Zweifel dringender als ein Hinweis, und eine Frage
# blockiert die Arbeit, solange sie unbeantwortet ist.
DRINGLICHKEIT_AUS_STUFE = {"fehler": 5, "warnung": 4, "frage": 4,
                           "hinweis": 2}
VERLAUF_MAX = 50                # so viele Auftraege bleiben in der Anzeige
HINWEISE_MAX = 200              # so viele Pruefhinweise werden aufbewahrt
POSTFACH_MAX = 100              # so viele Nachrichten bleiben im Briefkasten
MAX_KONTEXT_ELEMENTE = 50       # so viele aktive Elemente kommen als Kontext mit
MAX_KONTEXT_FACETTEN = 5        # bis hierhin auch die Facetten

BIND_RETRY_ATTEMPTS = 5
BIND_RETRY_PAUSE_SECONDS = 1.0
PORT_PROBE_TIMEOUT_SECONDS = 0.2

MAX_CODE_LENGTH = 100_000

# Best-Effort-Blocklist fuer Datei-/Prozess-/Netzwerk-Operationen ausserhalb
# Cadwork. Substring-Match ist trivial umgehbar — die belastbare Schutzschicht
# bleibt das Localhost-Binding des TCP-Sockets.
FORBIDDEN_TOKENS = (
    "import os",
    "from os ",
    "import subprocess",
    "from subprocess ",
    "import shutil",
    "from shutil ",
    "import socket",
    "from socket ",
    "import requests",
    "import urllib",
    "from urllib",
    "__import__",
)


# --- cwapi3d Module-Registry ----------------------------------------------

_CWAPI3D_MODULE_NAMES = (
    "attribute_controller",
    "bim_controller",
    "connector_axis_controller",
    "dimension_controller",
    "element_controller",
    "endtype_controller",
    "file_controller",
    "geometry_controller",
    "list_controller",
    "machine_controller",
    "material_controller",
    "menu_controller",
    "multi_layer_cover_controller",
    "roof_controller",
    "scene_controller",
    "shop_drawing_controller",
    "utility_controller",
    "visualization_controller",
    "cadwork",
)

_CWAPI3D_ALIASES = {
    "ec": "element_controller",
    "uc": "utility_controller",
    "ac": "attribute_controller",
    "gc": "geometry_controller",
    "fc": "file_controller",
    "vc": "visualization_controller",
    "mc": "material_controller",
    "bc": "bim_controller",
    "sc": "scene_controller",
    "lc": "list_controller",
    "cw": "cadwork",
}


def _build_exec_globals():
    """Erstellt das globals-Dict fuer execute_cwapi3d-Calls."""
    g = {"__builtins__": __builtins__}
    imported = {}
    for name in _CWAPI3D_MODULE_NAMES:
        try:
            imported[name] = __import__(name)
        except ImportError:
            continue
    g.update(imported)
    for alias, target in _CWAPI3D_ALIASES.items():
        if target in imported:
            g[alias] = imported[target]
    return g


def _is_json_serializable(value):
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _to_jsonable(value):
    """Wandelt einen Wert in ein JSON-faehiges Format. Fallback: repr()."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if _is_json_serializable(value):
        return value
    return {"_repr": repr(value), "_type": type(value).__name__}


# --- Logging --------------------------------------------------------------

def _logger_einrichten(cfg):
    """Root-Logger mit Datei- und Konsolen-Handler, pro Instanz getrennt.

    Zwei Dinge, die in der Vorversion gefehlt haben:
      * eigene Logdatei je Steckplatz (vorher schrieben A-D in DIESELBE
        Datei, die Zeilen dort waren keiner Instanz zuzuordnen)
      * jede Zeile traegt zusaetzlich "[A:53127]", damit auch eine
        zusammenkopierte Datei eindeutig bleibt
    """
    marker = "_omcad_%s" % cfg.instanz
    for h in list(LOG.handlers):
        if getattr(h, marker, False):
            return  # schon eingerichtet (Plugin-Neuaufruf in derselben Sitzung)
    # Handler eines ANDEREN Steckplatzes abraeumen. Kommt vor, wenn in
    # derselben Cadwork-Sitzung nacheinander zwei Steckplaetze gestartet
    # werden — sonst schriebe der zweite auch in die Logdatei des ersten.
    # Am PRAEFIX erkennen, nicht an einer Liste von Buchstaben. Hier stand
    # `for i in "ABCD"` — ein Inventar, und zwar dasselbe, das den
    # Instanz-Guard fuenf Wochen lang bei A-D festhielt. Mit Kennungen wie
    # "E", "26" oder "72" haette es den alten Handler NICHT abgeraeumt: der
    # zweite Steckplatz haette zusaetzlich in die Logdatei des ersten
    # geschrieben, ohne dass irgendetwas auffaellt.
    for h in list(LOG.handlers):
        if any(a.startswith("_omcad_") for a in vars(h)):
            LOG.removeHandler(h)
            try:
                h.close()
            except Exception:                         # noqa: BLE001
                pass

    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    formatter = logging.Formatter(
        fmt="%%(asctime)s [%s:%d] [%%(levelname)s] [%%(threadName)s] %%(message)s"
            % (cfg.instanz, cfg.port),
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        fh = logging.FileHandler(cfg.log_datei, mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        setattr(fh, marker, True)
        LOG.addHandler(fh)
    except OSError as exc:
        sys.stderr.write("[%s] Konnte Log-Datei %r nicht oeffnen: %s\n"
                         % (cfg.anzeigename, cfg.log_datei, exc))
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    setattr(sh, marker, True)
    LOG.addHandler(sh)


# --- Job ------------------------------------------------------------------

class Job:
    """Ein Modell-Auftrag, vom Worker an den Cadwork-Hauptthread uebergeben.

    `gesendet` ist neu: der Hauptthread wartet beim Beenden darauf, damit
    "nach dem Auftrag beenden" die Antwort nicht abschneidet.
    """

    __slots__ = ("request_id", "method", "params", "event", "response",
                 "gesendet", "verworfen", "meta", "erstellt")

    def __init__(self, request_id, method, params, meta):
        self.request_id = request_id
        self.method = method
        self.params = params
        self.meta = meta                 # AuftragsMeta
        self.event = threading.Event()   # Hauptthread -> Worker: fertig
        self.gesendet = threading.Event()  # Worker -> Hauptthread: raus
        self.response = None
        self.verworfen = False
        self.erstellt = time.monotonic()


class AuftragsMeta:
    """Alles, was die Oberflaeche ueber einen Auftrag anzeigen soll."""

    __slots__ = ("operation_id", "beschreibung", "zugriff", "client",
                 "client_id", "methode", "start_epoch", "start_mono",
                 "schnell", "paket", "paketweise")

    def __init__(self, methode, params):
        self.methode = methode
        self.operation_id = _als_text(params.get("operation_id"))
        self.beschreibung = _als_text(params.get("description"))
        self.client = _als_text(params.get("client_label")) or "unbekannt"
        self.client_id = _als_text(params.get("client_id")) or "anon"
        self.zugriff = zugriff_bestimmen(methode, params)
        self.start_epoch = None
        self.start_mono = None
        # Wird erst beim Ausfuehren gesetzt: hat dieser Auftrag mit
        # abgeschalteter Bildschirm-Auffrischung gezeichnet?
        self.schnell = False
        # (k, n), wenn der Auftrag Paket k von n eines Paketlaufs ist.
        self.paket = paket_von(params)
        # Wird beim Ausfuehren gesetzt: zieht dieser Auftrag seine neuen
        # Bauteile selbst nach, statt sie hinter den Vorhang zu legen?
        # EINMAL entschieden, damit ein Griff an den Regler mitten im Paket
        # nicht die eine Haelfte (kein Vorhang) ohne die andere laesst.
        self.paketweise = False

    def als_dict(self, jetzt_mono=None):
        d = {
            "methode": self.methode,
            "operation_id": self.operation_id,
            "beschreibung": self.beschreibung,
            "zugriff": self.zugriff,
            "client": self.client,
            "client_id": self.client_id,
            "gestartet": self.start_epoch,
            "schnell": self.schnell,
            "paket": list(self.paket) if self.paket else None,
        }
        if self.start_mono is not None:
            jetzt = jetzt_mono if jetzt_mono is not None else time.monotonic()
            d["laufzeit_s"] = round(jetzt - self.start_mono, 1)
        else:
            d["laufzeit_s"] = None
        return d


def _als_text(wert):
    if wert is None:
        return ""
    if isinstance(wert, str):
        return wert.strip()
    return str(wert)


def paket_von(params):
    """(k, n) aus dem Feld `paketlauf` — oder None fuer einen Einzelauftrag.

    Bewusst ein eigenes Feld und NICHT die Beschreibung "(Paket k/n)": die
    ist Anzeigetext, und ein Name, der etwas entscheidet, ist Logik (Regel 4
    im Repo). Was nicht genau passt, gilt als Einzelauftrag — die bisherige,
    sichere Richtung.
    """
    feld = params.get("paketlauf") if isinstance(params, dict) else None
    if not isinstance(feld, dict):
        return None
    k, n = feld.get("paket"), feld.get("pakete")
    if (isinstance(k, int) and isinstance(n, int)
            and not isinstance(k, bool) and not isinstance(n, bool)
            and 1 <= k <= n):
        return (k, n)
    return None


# Methoden, die den Cadwork-Hauptthread brauchen (= echte Modell-Auftraege).
MODELL_METHODEN = ("execute_cwapi3d", "get_document_info",
                   "elemente_zeigen", "sichtbarkeit_zurueck", "undo", "redo",
                   "nachricht_senden", "neu_zeichnen")

# Was diese Methoden mit dem Modell tun.
METHODEN_ZUGRIFF = {
    "get_document_info": "read",
    # Anzeigen veraendert nur die Ansicht, nicht das Modell.
    "elemente_zeigen": "read",
    "sichtbarkeit_zurueck": "read",
    "neu_zeichnen": "read",
    # Eine Nachricht schreiben veraendert das Modell nicht.
    "nachricht_senden": "read",
    # Undo und Redo veraendern das Modell — eindeutig Schreibzugriff.
    "undo": "write",
    "redo": "write",
    "ping": "read",
    "status": "read",
    "list_store_keys": "read",
    "clear_store": "read",     # betrifft nur den Session-Speicher, nie das Modell
    "zeichenmodus": "read",    # stellt nur die Bridge ein, nie das Modell
    "undo_aenderungen": "read",
}


def zugriff_bestimmen(methode, params):
    """Lese- oder Schreibzugriff?

    Ein `execute_cwapi3d` ohne ausdrueckliche Angabe gilt **als Schreib-
    zugriff**. Das ist Absicht: der Code darin ist beliebig, und die falsche
    Annahme "ist ja nur lesend" waere die teure Richtung.
    """
    angabe = _als_text(params.get("access_mode")).lower()
    if angabe in ("read", "lesen", "r"):
        return "read"
    if angabe in ("write", "schreiben", "w"):
        return "write"
    return METHODEN_ZUGRIFF.get(methode, "write")


# --- Der eigentliche Dienst -----------------------------------------------

class Verbindungsdienst:
    """Eine Instanz = ein Steckplatz = ein Port.

    Der gesamte Zustand haengt an diesem Objekt (nicht an Modul-Globals),
    damit auch zwei in denselben Prozess geladene Einstiege sich nicht ins
    Gehege kommen.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.sperre = threading.RLock()

        self._zustand = "stopped"
        self._fehler_text = ""
        self.start_epoch = None
        self.start_mono = None

        self.job_queue = queue.Queue()
        self.offene_verbindungen = []
        self.verbindungs_sperre = threading.Lock()

        self.store = {}
        self.store_sperre = threading.Lock()

        self.beenden = False                 # Listener/Worker/Hauptthread-Stop
        self.beenden_nach_auftrag = False
        self.pausiert = False

        self.aktueller_auftrag = None        # AuftragsMeta | None
        self.letzter_auftrag = None          # dict | None
        self.letzter_fehler = None           # dict | None
        self.auftraege_gesamt = 0

        # Dokument-Cache — IMMER auf dem Hauptthread gefuellt, von ueberall
        # lesbar. Damit kann die Statusabfrage den Dokumentnamen nennen,
        # ohne cwapi3d aus einem Worker-Thread anzufassen (das waere der
        # sichere Weg in einen Absturz).
        self.dok_name = ""
        self.dok_elemente = None
        self.dok_stand_mono = None

        self.herzschlag_mono = None
        self.schreiblizenz = None            # dict | None

        self._ui_pumpe_warnung = False
        # Gesetzt, wenn die UI-Pumpe sich wegen eines Zugriffsfehlers selbst
        # abgeschaltet hat — gehoert in den Status, nicht nur ins Log.
        self.ui_pumpe_fehler = ""
        self.letzte_dok_pruefung = 0.0

        # Pruefhinweise: strukturierte Meldungen der KI oder eines Builders
        # ("bei diesem Bauteil bin ich unsicher"). Bewusst KEINE eigene
        # Kollisionskontrolle — Cadwork hat eine, und eine zweite waere
        # doppelte Arbeit mit halber Qualitaet. Hier landet nur, was jemand
        # ausdruecklich meldet.
        self.hinweise = []
        self.hinweis_zaehler = 0
        # Auftragsverlauf fuer die Anzeige (begrenzt, aelteste fliegen raus)
        self.verlauf = []

        # Briefkasten: Nachrichten von Cadwork AN die KI. Bewusst ein
        # Briefkasten und kein Chat — ohne API-Zugang kann niemand die KI
        # anstupsen. Die Nachricht liegt hier, bis die laufende Sitzung sie
        # mit `nachrichten_abholen` liest. Das ist ehrlicher als eine
        # Chat-Oberflaeche, die so tut, als koenne sie zustellen.
        self.postfach = []
        self.nachricht_zaehler = 0

        # Schnellzeichnen: Cadworks Bildschirm-Auffrischung waehrend eines
        # Auftrags abschalten. Laut Messung (Memory 2026-07) kostet Cadwork
        # ~120 ms je Element — ein guter Teil davon ist Neuzeichnen.
        #
        # Startwert = die Vorgabe-STUFE, die das Dock anzeigt. Bis 2.16.2
        # stand hier False: das Dock zeigte "Auto", gezeichnet wurde aber
        # wie "Langsam", bis jemand den Regler anfasste (gemessen
        # 2026-09-25 an einem frisch verbundenen Steckplatz: `schnell-
        # zeichnen` False, `schnellzeichnen_soll` True).
        self.schnellzeichnen = _env_bool(
            "OPEN_MCP_CAD_SCHNELL",
            next(m["schnell"] for m in ZEICHENMODI
                 if m["schluessel"] == MODUS_VORGABE))
        # Nur fuer die Anzeige: welche Elemente sind gerade angewaehlt
        self.aktive_elemente = []
        # Der von cwapi3d gelieferte Sichtbarkeitszustand vor dem letzten
        # "Im Modell zeigen". Gehoert dem STECKPLATZ, nicht dem Modul —
        # A/B/C/D laufen nebeneinander.
        self.sicht_zustand = None
        # Wie oft noch neu gezeichnet werden soll (siehe _bildschirm_an)
        self.refresh_nachholen = 0
        # Ist Cadworks Bildschirm-Auffrischung gerade abgeschaltet?
        # Sie bleibt es ueber MEHRERE Auftraege hinweg und geht erst wieder
        # an, wenn Ruhe eingekehrt ist — siehe _tick.
        self.bildschirm_aus = False
        self.letzter_auftrag_mono = 0.0
        # Elemente, die bei ABGESCHALTETER Auffrischung entstanden sind.
        # Cadwork baut ihre Darstellung nicht nach — sie bleiben unsichtbar
        # korrekt, bis sie einmal bei eingeschaltetem Bildschirm angefasst
        # werden. Wird beim Wiedereinschalten abgearbeitet und geleert,
        # siehe _dunkle_elemente_nachziehen.
        self.dunkel_entstanden = []
        # Wie viele Elemente insgesamt nachgezogen wurden. Steht im Status,
        # damit von aussen ABWARTBAR ist, wann das Nachziehen fertig ist:
        # `bildschirm_aus` faellt schon davor auf False (die Auffrischung
        # wird zuerst eingeschaltet), und wer daran misst, misst zu frueh.
        self.nachgezogen_gesamt = 0
        # Paketweises Nachziehen (siehe `_paket_nachziehen`): wie oft, und
        # wie lange zusammen. Steht im Status, damit die Kosten im echten
        # Cadwork ablesbar sind — offline laesst sich nur die Mechanik
        # pruefen, nicht, was Cadwork dafuer rechnet.
        self.pakete_nachgezogen = 0
        self.paket_nachziehen_s = 0.0
        # Laeuft das Nachziehen GERADE? Es laeuft ausserhalb eines Auftrags,
        # blockiert Cadwork aber genauso — ohne dieses Flag meldet der Status
        # faelschlich einen haengenden Hauptthread.
        self.nachzieh_laeuft = False
        # Zeichenmodus (2026-08-06: ein Regler mit Auto-Stufe, dazu ein
        # Entwicklermodus mit zwei getrennten Reglern). Feste Stufen
        # BEGRENZEN wirklich — "sonst machts ja keinen Sinn"; Auto regelt
        # nur die Empfehlung nach und sperrt nichts.
        self.zeichenmodus = MODUS_VORGABE
        self.ms_je_teil = MS_JE_TEIL_START
        # Ladebalken ueber einen ganzen Zeichenlauf (Modus 'max').
        # Rueckmeldung 2026-08-06: waehrend des Zeichnens soll man SEHEN, dass
        # gearbeitet wird, und das Ergebnis erst am Ende erscheinen.
        self.lauf_balken = False
        self.lauf_gezeichnet = 0     # angemeldete Bauteile bisher
        self.lauf_gesamt = None      # angemeldetes Ziel, wenn der Client es sagt
        # K12: der Haken der Arbeitsanzeige warf in diesem Lauf -> eigenes
        # Fenster bis zum Ende des Laufs (`_lauf_anzeige_rufen`).
        self.lauf_haken_kaputt = False
        self.lauf_takte = 0          # nur fuer den pulsierenden Balken
        self.lauf_auftraege = 0      # Auftraege seit Beginn dieses Laufs
        self.lauf_start_mono = 0.0   # wann dieser Lauf begonnen hat
        self.lauf_nr = 0             # welcher Zeichenlauf — stempelt Hinweise
        self.vorhang_aktiv = False   # sind Bauteile gerade unsichtbar?
        self.cadwork_balken = False  # laeuft Cadworks Balken unten rechts?
        self.angemeldet_geaendert = 0   # ueber aendert() gemeldete Bauteile
        # Sollen Aenderungen an BESTEHENDEN Bauteilen ruecknehmbar sein?
        # Rueckmeldung 2026-08-06: "vlt eine funktion oder 3. stufe beim schalter wo
        # einfach bis zu einer gewissen anzahl elementen es so gemacht wird
        # das es rueckgaengig machbar ist, also wenn man zb einfach 100
        # sparren verlaengert das es dann noch geht."
        # Gemessen am selben Tag mit stretch_end_facet:
        #    20 Sparren  aendern 82 ms  + anmelden  50 ms  = 121 ms  (+61 %)
        #   100          aendern 266 ms + anmelden 258 ms  = 519 ms  (+97 %)
        #   300          aendern 730 ms + anmelden 802 ms  = 1529 ms (+110 %)
        # Prozentual rund eine Verdopplung — in Sekunden aber ein Viertel
        # bei 100 Bauteilen. Deshalb ist die Grenze grosszuegig: erst im
        # vierstelligen Bereich wird daraus echte Wartezeit.
        self.undo_aenderungen = "bis_grenze"   # aus | bis_grenze | immer
        self.undo_grenze = 500
        self.uebersprungen_geaendert = 0
        # Arbeitet Cadwork gerade selbst im Hauptthread? (siehe `_takt`)
        # Leer = nein. Sonst der Grund, den die Sonde gemeldet hat — er
        # steht im Status, damit von aussen zu sehen ist, WARUM ein
        # Auftrag wartet, statt nur, DASS er wartet.
        self.blockiert_grund = ""
        self.blockiert_seit_mono = None
        self.zurueckhaltungen = 0      # wie oft schon zurueckgehalten
        self.sonden = []               # Namen der aktiven Sonden (Status)
        self.qt = ""                   # Qt-Stand des Antriebs (Status)
        # Wann der letzte Qt-Takt fertig war, und wie lange der Takt zuletzt
        # stillstand, weil Cadwork den Hauptthread hatte. Nur Messung: sie
        # soll im echten Cadwork zeigen, welche Sonde waehrend einer langen
        # Cadwork-Rechnung anschlaegt — und ob eine.
        self.takt_ende_mono = None
        self.letzter_stau_s = None
        # Wer diesen Dienst gestartet hat (das Kern-Modul) und sein Eintrag
        # in `_QT_LAEUFT`. Beides braucht ein ZWEITER Klick, der mit einem
        # frisch geladenen Kern kommt: das Modul-Global des alten Kerns
        # sieht er nicht.
        self.kern_modul = None
        self.qt_eintrag = None

    # -- Zustand ----------------------------------------------------------

    @property
    def zustand(self):
        with self.sperre:
            return self._zustand

    def zustand_setzen(self, neu, fehler_text=""):
        with self.sperre:
            if self._zustand != neu:
                LOG.info("Zustand %s -> %s%s", self._zustand, neu,
                             (" (%s)" % fehler_text) if fehler_text else "")
            self._zustand = neu
            if neu == "error":
                self._fehler_text = fehler_text

    def _zustand_nach_auftrag(self):
        """Wohin faellt der Dienst zurueck, wenn ein Auftrag fertig ist?"""
        with self.sperre:
            if self.beenden:
                return "stopped"
            if self.beenden_nach_auftrag:
                return "stopping_after_job"
            if self.pausiert:
                return "paused"
            return "ready"

    # -- Dokument-Cache (nur Hauptthread!) --------------------------------

    def aktive_auffrischen(self):
        """Merkt sich, wie viele Elemente gerade aktiv sind.

        Nur fuer die Anzeige im Briefkasten ("3 Elemente aktiv"). Wie jeder
        cwapi3d-Aufruf ausschliesslich aus dem Hauptthread.
        """
        try:
            import element_controller as ec
            self.aktive_elemente = [int(i) for i
                                    in ec.get_active_identifiable_element_ids()]
        except Exception:                             # noqa: BLE001
            self.aktive_elemente = []

    def dokument_auffrischen(self, mit_elementen=False):
        """Liest Dokumentdaten. **Nur aus dem Cadwork-Hauptthread aufrufen.**"""
        try:
            import utility_controller as uc
            name = uc.get_3d_file_name()
        except Exception as exc:                      # noqa: BLE001
            LOG.info("Dokumentname nicht lesbar: %s", exc)
            return
        anzahl = None
        if mit_elementen:
            try:
                import element_controller as ec
                anzahl = len(ec.get_all_identifiable_element_ids())
            except Exception as exc:                  # noqa: BLE001
                LOG.info("Elementzahl nicht lesbar: %s", exc)
        with self.sperre:
            vorher = self.dok_name
            self.dok_name = name or ""
            if anzahl is not None:
                self.dok_elemente = anzahl
            self.dok_stand_mono = time.monotonic()
        # Der Dokumentname ist das, wonach in der Registry gesucht wird —
        # er muss der Wahrheit folgen, wenn der Nutzer eine andere Datei
        # oeffnet. Ausserhalb der Sperre: Dateizugriff gehoert nicht unter
        # ein Schloss, das der Auftragstakt braucht. Und nur bei
        # Aenderung, sonst schriebe jede Auffrischung (alle 5 s) die Datei
        # neu.
        if (name or "") != vorher and self.cfg.port is not None:
            registry_dokument_setzen(self.cfg.port, name or "")

    # -- Schreiblizenz ----------------------------------------------------

    def lizenz_pruefen_und_nehmen(self, meta, uebernehmen=False):
        """Darf dieser Client schreiben? Liefert None oder eine Fehlerantwort.

        Bewusst einfach gehalten: die Lizenz ist eine kurze, sich selbst
        erneuernde Reservierung. Sie verhindert das, was verhindert werden
        muss — zwei KI-Sessions, die gleichzeitig dieselbe Datei veraendern —
        und heilt nach `lizenz_ttl_s` ohne Schreibzugriff von selbst.
        """
        jetzt = time.monotonic()
        with self.sperre:
            lz = self.schreiblizenz
            if lz and lz["bis_mono"] > jetzt and lz["client_id"] != meta.client_id:
                if not uebernehmen:
                    rest = int(lz["bis_mono"] - jetzt)
                    return _fehler(
                        "document_busy",
                        "Dokument %r ist fuer Schreibzugriffe von %r reserviert "
                        "(noch %d s). Zwei Sitzungen duerfen dieselbe Datei "
                        "nicht gleichzeitig veraendern."
                        % (self.dok_name or "?", lz["client"] or lz["client_id"], rest),
                        "client_id=%s haelt die Lizenz, angefragt von client_id=%s"
                        % (lz["client_id"], meta.client_id),
                    )
                LOG.info("Schreiblizenz wird von %s uebernommen (vorher %s)",
                             meta.client_id, lz["client_id"])
            self.schreiblizenz = {
                "client_id": meta.client_id,
                "client": meta.client,
                "bis_mono": jetzt + self.cfg.lizenz_ttl_s,
                "seit_epoch": (lz or {}).get("seit_epoch") if (
                    lz and lz["client_id"] == meta.client_id) else time.time(),
            }
        return None

    def lizenz_freigeben(self, client_id):
        with self.sperre:
            lz = self.schreiblizenz
            if lz is None:
                return False
            if client_id and lz["client_id"] != client_id:
                return False
            self.schreiblizenz = None
        return True

    # -- Status (antwortet IMMER, ohne Hauptthread) -----------------------

    def status(self):
        jetzt_mono = time.monotonic()
        with self.sperre:
            zustand = self._zustand
            auftrag = self.aktueller_auftrag
            lz = self.schreiblizenz
            herz = self.herzschlag_mono
            dok_stand = self.dok_stand_mono
            daten = {
                "instanz": self.cfg.instanz,
                "anzeigename": self.cfg.anzeigename,
                "port": self.cfg.port,
                "pid": os.getpid(),
                "version": CORE_VERSION,
                "protokoll": PROTOKOLL_VERSION,
                "dokument": self.dok_name,
                "dokument_elemente": self.dok_elemente,
                "zustand": zustand,
                "zustand_text": ZUSTAND_TEXT.get(zustand, zustand),
                "gestartet": self.start_epoch,
                "laufzeit_s": (round(jetzt_mono - self.start_mono, 1)
                               if self.start_mono is not None else None),
                "wartende_auftraege": self.job_queue.qsize(),
                "auftraege_gesamt": self.auftraege_gesamt,
                "auftrag": auftrag.als_dict(jetzt_mono) if auftrag else None,
                "letzter_auftrag": self.letzter_auftrag,
                "letzter_fehler": self.letzter_fehler,
                "pausiert": self.pausiert,
                "beenden_nach_auftrag": self.beenden_nach_auftrag,
                "ui_pumpe": self.cfg.ui_pumpe,
                "schnellzeichnen": self.schnellzeichnen,
                # Ist Cadworks Auffrischung GERADE abgeschaltet? Das ist
                # NICHT dasselbe wie `schnellzeichnen`: abgeschaltet wird sie
                # vom ersten Auftrag mit `schnell`, und sie bleibt es ueber
                # weitere Auftraege hinweg bis SCHNELL_RUHE_S Leerlauf.
                # Ohne diesen Wert war der Zustand von aussen unsichtbar —
                # und genau daran ist am 2026-08-06 ein Vergleichstest
                # gescheitert: seine "ohne Schnellzeichnen"-Zelle wurde in
                # Wahrheit ebenfalls mit abgeschaltetem Bildschirm gezeichnet.
                "bildschirm_aus": self.bildschirm_aus,
                "nachgezogen_gesamt": self.nachgezogen_gesamt,
                "pakete_nachgezogen": self.pakete_nachgezogen,
                "paket_nachziehen_s": round(self.paket_nachziehen_s, 2),
                "zeichenmodus": self.zeichenmodus,
                "ms_je_teil": self.ms_je_teil,
                "undo_aenderungen": self.undo_aenderungen,
                "undo_grenze": self.undo_grenze,
                "uebersprungen_geaendert": self.uebersprungen_geaendert,
                "nachrichten_offen": sum(1 for n in self.postfach
                                         if not n["abgeholt"]),
                "aktive_elemente": len(self.aktive_elemente),
                "hinweise_offen": sum(1 for h in self.hinweise
                                      if h["status"] == "offen"),
                "ui_pumpe_fehler": self.ui_pumpe_fehler,
                "antrieb": self.cfg.antrieb,
                "fehler_text": self._fehler_text,
                # Leer, solange Cadwork frei ist; sonst der Grund, warum
                # der Takt gerade kein cwapi3d anfasst (siehe `_takt`).
                "cadwork_beschaeftigt": self.blockiert_grund,
                "zurueckgehalten_s": (
                    round(jetzt_mono - self.blockiert_seit_mono, 1)
                    if self.blockiert_seit_mono is not None else None),
                "zurueckhaltungen": self.zurueckhaltungen,
                "sonden": list(self.sonden),
                "qt": self.qt,
                "takt_stau_s": self.letzter_stau_s,
            }
        with self.verbindungs_sperre:
            daten["verbindungen"] = len(self.offene_verbindungen)

        # Was die Zeichner brauchen, um sich an den Regler zu halten.
        schnell_soll, ziel = self.modus_werte()
        daten["blockade_ziel_s"] = ziel
        daten["haeppchen_empfehlung"] = self.haeppchen_empfehlung()
        daten["schnellzeichnen_soll"] = schnell_soll

        daten["dokument_stand_s"] = (round(jetzt_mono - dok_stand, 1)
                                     if dok_stand is not None else None)
        if lz:
            daten["schreiblizenz"] = {
                "client_id": lz["client_id"],
                "client": lz["client"],
                "rest_s": max(0, int(lz["bis_mono"] - jetzt_mono)),
                "seit": lz.get("seit_epoch"),
            }
        else:
            daten["schreiblizenz"] = None

        # Herzschlag: sagt ehrlich, ob der Cadwork-Hauptthread noch dreht.
        alter = (round(jetzt_mono - herz, 2) if herz is not None else None)
        daten["hauptthread_alter_s"] = alter
        # Das Nachziehen der Darstellung laeuft NICHT in einem Auftrag —
        # der Zustand ist dabei "bereit", der Herzschlag stockt trotzdem.
        # Ohne diese Ausnahme sah eigene Arbeit wie ein Haenger aus
        # (2026-08-06: "bei manchen Varianten stand eine Meldung").
        nachzieht = self.nachzieh_laeuft
        haengt = (zustand not in BESCHAEFTIGT and not nachzieht
                  and alter is not None and alter > HERZSCHLAG_GRENZE_S)
        daten["hauptthread_ok"] = not haengt
        daten["nachzieht"] = nachzieht
        if nachzieht:
            # Nur GEMESSENE Kosten nennen: 0,6 s je 1000 Bauteile am
            # 2026-08-06; im Film-Log 2026-09-25 2,2 bis 4,7 ms je VBA
            # (1760 in 3,79 s, 528 in 2,48 s). Die Spanne haengt am Bauteil.
            daten["hinweis"] = (
                "Die Darstellung wird nachgezogen — Cadwork ist so lange "
                "nicht bedienbar. Das gehoert zum Schnellzeichnen und "
                "dauert je nach Bauteil gemessen 0,6 bis 4,7 s je 1000 "
                "Bauteile.")
        elif daten["cadwork_beschaeftigt"]:
            daten["hinweis"] = (
                "Cadwork arbeitet gerade selbst (%s). Auftraege warten, bis "
                "das vorbei ist, und laufen dann von selbst weiter — %d "
                "wartend. Nichts wiederholen."
                % (daten["cadwork_beschaeftigt"],
                   daten["wartende_auftraege"]))
        elif haengt:
            # KEINE Handlungsanweisung mehr. Die alte lautete "einmal ins
            # Cadwork-Fenster klicken oder die Maus bewegen" — sie stammt aus
            # der Zeit vor dem Qt-Antrieb und ist zudem nicht befolgbar,
            # solange die Oberflaeche steht (2026-08-06: "das
            # funktioniert ja nicht da die anzeige blockiert ist").
            daten["hinweis"] = (
                "Cadwork arbeitet seit %.0f s an einem Stueck und ist so "
                "lange nicht bedienbar. Warten — es loest sich von selbst, "
                "sobald der laufende Schritt fertig ist. Bleibt es dauerhaft "
                "stehen, hilft nur das Beenden des Steckplatzes."
                % alter
            )
        elif self.ui_pumpe_fehler:
            daten["hinweis"] = (
                "Die UI-Pumpe wurde nach einem Zugriffsfehler abgeschaltet "
                "(%s). Die Verbindung arbeitet normal weiter; die "
                "Cadwork-Oberflaeche bleibt eingefroren, bis das Plugin "
                "beendet wird." % self.ui_pumpe_fehler)
        elif zustand == "paused":
            daten["hinweis"] = ("Pausiert - Cadwork kann von Hand bedient "
                                "werden. Modell-Auftraege werden abgelehnt.")
        else:
            daten["hinweis"] = ""
        return daten

    # -- Zeichenmodus (worker-sicher, kein cwapi3d) -----------------------

    def modus(self):
        """Die Beschreibung der aktuell eingestellten Stufe."""
        with self.sperre:
            schluessel = self.zeichenmodus
        for m in ZEICHENMODI:
            if m["schluessel"] == schluessel:
                return m
        return ZEICHENMODI[0]

    def modus_werte(self):
        """(schnellzeichnen, blockade_ziel_s) — aktuell gueltig."""
        m = self.modus()
        return m["schnell"], m["blockade_s"]

    def haeppchen_empfehlung(self):
        """Wie viele Bauteile ein Auftrag hoechstens zeichnen sollte.

        None heisst "keine Empfehlung". Der Wert steht im Status, damit die
        Zeichner ihn lesen koennen — die Bridge kann fremden Code NICHT
        zerlegen, sie kann nur sagen, was passen wuerde.

        AUSDRUECKLICH nur ein Rat, keine Sperre: die Rechnung
        `Bauteile x gelerntem Preis` lag am 2026-08-07 im grossen Modell um
        den Faktor 7 daneben. Wer sie als Grenze benutzt, lehnt entweder das
        Falsche ab oder laesst das Falsche durch — beides ist passiert.
        """
        _, ziel = self.modus_werte()
        if not ziel:
            return None
        with self.sperre:
            ms = self.ms_je_teil
        return max(1, int(ziel * 1000.0 / max(1.0, ms)))

    def tempo_lernen(self, bauteile, dauer_s):
        """Lernt aus echten Auftraegen, was ein Bauteil gerade kostet.

        Ein fester Wert waere nach dem ersten anderen Zeichenlauf falsch: ein
        Balken mit Ausklinkung kostet ein Vielfaches eines nackten, und der
        Preis waechst mit dem Modell. Gleitender Mittelwert, damit ein
        einzelner Ausreisser die Grenze nicht kippt.
        """
        try:
            n = int(bauteile or 0)
        except (TypeError, ValueError):
            return
        if n <= 0 or dauer_s <= 0:
            return
        with self.sperre:
            self.ms_je_teil = round(0.7 * self.ms_je_teil
                                    + 0.3 * (dauer_s * 1000.0 / n), 2)


    def aendert_anmelden(self, ids):
        """Im Auftragscode als `aendert(ids)`: bestehende Bauteile anmelden,
        BEVOR sie veraendert werden — dann nimmt Rueckgaengig sie mit zurueck.

        Warum ueberhaupt: das automatische Anmelden (`_undo_anmelden`) sieht
        nur NEUE Elemente, weil es zwei ID-Listen vergleicht. Eine Aenderung
        an gleichbleibender ID ist darin unsichtbar.

        Warum ANGEMELDET und nicht automatisch: Cadwork sichert beim
        Anmelden den Zustand jedes Elements, und das kostet. Gemessen am
        2026-08-06 — die Kosten haengen an der ANZAHL, nicht am Aufruf:

            1 Element      6,3 ms   (einmaliger Anlauf)
           10             20,2 ms   2,0 ms je Element
           50            134,4 ms   2,7 ms
          100            258,5 ms   2,6 ms
         1795           4990   ms   2,8 ms

        Linear, rund 2,6 ms je Element, unabhaengig von der Modellgroesse.
        Fuer den Normalfall (ein paar angewaehlte Bauteile) sind das
        Millisekunden. Pauschal vor jedem Auftrag ALLES anzumelden waere auf
        einem Modell mit 15 000 Bauteilen dagegen ueber 40 s — deshalb sagt
        der Auftrag, was er anfasst, statt dass die Bridge raet.

        Wirkung geprueft (2026-08-06): Material Fi/Ta -> Glaswolle -> Undo
        -> wieder Fi/Ta.

        REIHENFOLGE IST PFLICHT: erst `aendert(ids)`, dann aendern. Cadwork
        sichert den Zustand im Moment der Anmeldung; hinterher angemeldet
        wuerde der bereits geaenderte Zustand gesichert.
        """
        try:
            liste = [int(e) for e in (ids or [])]
        except (TypeError, ValueError):
            raise ValueError("aendert() erwartet eine Liste von Element-IDs")
        if not liste:
            return 0
        with self.sperre:
            modus = self.undo_aenderungen
            grenze = self.undo_grenze
        if modus == "aus" or (modus == "bis_grenze" and len(liste) > grenze):
            # Bewusst nicht anmelden — und das SAGEN, nicht verschweigen.
            with self.sperre:
                self.uebersprungen_geaendert += len(liste)
            LOG.info("aendert(): %d Bauteile NICHT angemeldet (%s, Grenze %d) "
                     "— diese Aenderung ist nicht ruecknehmbar",
                     len(liste), modus, grenze)
            return 0
        import element_controller as ec
        t0 = time.monotonic()
        ec.add_modified_elements_to_undo(liste)
        dauer = time.monotonic() - t0
        with self.sperre:
            self.angemeldet_geaendert += len(liste)
        if dauer > 0.5:
            # Sichtbar machen, statt still teuer zu sein: bei rund 2,6 ms je
            # Element sind das etwa 200 Bauteile aufwaerts. Wer so viele
            # anmeldet, soll im Log sehen, was es gekostet hat.
            LOG.info("aendert(): %d Bauteile angemeldet, %.2f s — das zaehlt "
                     "zur Blockade des Auftrags", len(liste), dauer)
        return len(liste)

    # -- Session-Speicher (worker-sicher, kein cwapi3d) -------------------

    def store_setzen(self, name, wert):
        with self.store_sperre:
            self.store[name] = wert
            LOG.info("store_as: %r gespeichert (%d Eintraege)",
                         name, len(self.store))

    def store_holen(self, name):
        with self.store_sperre:
            wert = self.store.get(name)
            LOG.info("get_stored: %r -> %s", name,
                         "gefunden" if wert is not None else "leer")
            return wert

    # -- Modell-Methoden (laufen IMMER im Hauptthread) --------------------

    def _m_get_document_info(self, params):
        self.dokument_auffrischen(mit_elementen=True)
        with self.sperre:
            return {
                "document_name": self.dok_name,
                "element_count": self.dok_elemente,
                # Zusatzfelder, alte Clients ignorieren sie
                "instanz": self.cfg.instanz,
                "port": self.cfg.port,
            }

    def _m_execute_cwapi3d(self, params):
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("'code' muss ein nicht-leerer String sein")
        if len(code) > MAX_CODE_LENGTH:
            raise ValueError("Code ueberschreitet %d Zeichen" % MAX_CODE_LENGTH)
        for token in FORBIDDEN_TOKENS:
            if token in code:
                raise PermissionError(
                    "Code enthaelt blockiertes Token: %r. Datei-/Prozess-/"
                    "Netzwerk-Operationen ausserhalb cwapi3d sind nicht "
                    "erlaubt." % token)

        result_var = params.get("result_var", "result")
        if not isinstance(result_var, str) or not result_var.isidentifier():
            raise ValueError("'result_var' muss ein gueltiger Python-Identifier sein")

        # EIN Namensraum, nicht zwei. Mit getrennten globals/locals verhaelt
        # sich der Auftragscode NICHT wie ein normales Modul: der Rumpf einer
        # Comprehension und jede im Auftrag definierte Funktion sehen die
        # Locals nicht, und ein dort angelegter Name ist "not defined".
        # Am 2026-08-06 dreimal in einer Sitzung darueber gestolpert
        # (`voll` in einem all(...), `P` in einer Hilfsfunktion, `n` in einem
        # any(...)). Mit einem gemeinsamen Namensraum faellt die ganze
        # Fehlerklasse weg — genau so fuehrt Python ein Modul aus.
        ns = _build_exec_globals()
        ns.update({
            "store_as": self.store_setzen,
            "get_stored": self.store_holen,
            "aendert": self.aendert_anmelden,
        })
        vorgegeben = set(ns)
        # Damit "Rueckgaengig" ueberhaupt etwas zu tun hat — Begruendung und
        # Messung stehen bei `_undo_anmelden`. Bewusst hier, an EINER Stelle,
        # statt als Zeile in jedem der 17 Zeichner: so ist auch der Code
        # abgedeckt, den die KI zur Laufzeit erzeugt, und das ist der
        # haeufigere Fall.
        anmelden = bool(params.get("undo_anmelden", True))
        vorher = _undo_momentaufnahme()
        angemeldet = 0
        stdout_buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buffer):
                compiled = compile(code, "<execute_cwapi3d>", "exec")
                exec(compiled, ns)
        finally:
            # Auch ein auf halber Strecke gescheiterter Auftrag hinterlaesst
            # Elemente — genau dann will man sie am ehesten wieder loswerden.
            neu = _neue_elemente(vorher)
            if anmelden:
                angemeldet = _undo_anmelden(neu)
            if neu and self.bildschirm_aus:
                # Im Dunkeln entstanden: Cadwork zeigt sie erst nach dem
                # Nachziehen richtig. Gesammelt statt sofort, damit es EIN
                # Durchgang je Zeichenlauf bleibt und nicht einer je Auftrag.
                with self.sperre:
                    self.dunkel_entstanden.extend(neu)
                # Ein Paket, das sich gleich selbst nachzieht, bekommt KEINEN
                # Vorhang: seine Bauteile hat Cadwork waehrend des Pakets
                # schon gezeigt, sie jetzt zu verstecken hiesse, sie bis
                # zum Nachziehen verschwinden zu lassen (siehe
                # `_paket_nachziehen`). Die Entscheidung faellt EINMAL, in
                # `_auftrag_ausfuehren`.
                paketweise = bool(getattr(self.aktueller_auftrag,
                                          "paketweise", False))
                if self.modus()["vorhang"] and not paketweise:
                    # VORHANG. Das Abschalten der automatischen Auffrischung
                    # allein genuegt NICHT: jedes Fensterereignis — auch das
                    # eigene Fortschritts-Fenster — gibt Cadwork eine Runde
                    # Ereignisschleife, und dabei zeichnet es die Ansicht mit
                    # dem aktuellen Stand neu. Am 2026-08-06 wurde genau
                    # das gesehen: "die zwischenschritte wurden immer
                    # angezeigt". Wer nichts zeigen will, muss die Bauteile
                    # unsichtbar entstehen lassen und am Ende aufdecken.
                    try:
                        import visualization_controller as vc
                        vc.set_invisible(neu)
                        self.vorhang_aktiv = True
                    except Exception as exc:          # noqa: BLE001
                        LOG.info("Vorhang nicht moeglich: %s", exc)

        return {
            "result": _to_jsonable(ns.get(result_var)),
            "stdout": stdout_buffer.getvalue(),
            # Nur was der Auftrag SELBST angelegt hat — sonst staenden hier
            # jedes Mal die vorimportierten cwapi3d-Module mit drin.
            "vars": sorted(k for k in ns if k not in vorgegeben),
            "result_var": result_var,
            "undo_angemeldet": angemeldet,
        }

    # Der Docstring von execute_cwapi3d nennt `aendert` bewusst mit: sonst
    # weiss niemand, dass es die Funktion gibt.

    def _m_elemente_zeigen(self, params):
        """Aktiviert Elemente und zoomt sie heran — wie in Cadwork gewohnt.

        Die vorherige Sichtbarkeit wird vorher gesichert, damit sich der
        Zustand mit `sichtbarkeit_zurueck` wiederherstellen laesst. cwapi3d
        laeuft ausschliesslich hier, im Cadwork-Hauptthread.
        """
        import element_controller as ec
        import visualization_controller as vc

        ids = [int(i) for i in (params.get("element_ids") or [])]
        if not ids:
            raise ValueError("'element_ids' ist leer")
        vorhanden = set(ec.get_all_identifiable_element_ids())
        fehlen = [i for i in ids if i not in vorhanden]
        zeigen = [i for i in ids if i in vorhanden]
        if not zeigen:
            raise ValueError("Keines der %d Elemente existiert noch "
                             "(geloescht oder anderes Dokument)" % len(ids))
        # cwapi3ds save/restore_visibility_state ist in der Python-Bindung
        # NICHT benutzbar. Gemessen am 2026-08-07:
        #   save_visibility_state() -> "Unable to convert function return
        #   value to a Python type!"
        # Der Zustand kommt also gar nicht erst in Python an, und
        # `restore_visibility_state` verlangt genau dieses Objekt. Deshalb
        # merkt sich die Bridge die Sichtbarkeit SELBST — und zwar nur, was
        # sie anfasst. Das ist sogar genauer als Cadworks Zustand: was der
        # Benutzer vorher ausgeblendet hatte, bleibt ausgeblendet.
        # Kosten gemessen: `is_visible` ueber alle 16 627 Elemente = 8,0 ms
        # (0,0005 ms je Element).
        alle = list(vorhanden)
        if alle:
            vc.set_inactive(alle)
        # DAS AKTIVIEREN SELBST — es fehlte.
        # Rueckmeldung 2026-08-15: "wenn man ein hinweis anwaehlt muessen die objekte
        # pink aktiviert werden nicht nur angezeigt werden das macht kein
        # sinn". Und genau so war es auch immer gemeint: die Uebergabe vom
        # 2026-08-05 beschreibt den Weg als "vc.set_active +
        # zoom_active_elements". Im Code stand aber nur das Abwaehlen aller
        # und danach der Zoom — also ein Zoom auf eine LEERE Auswahl. Was
        # Der Nutzer sah ("nur angezeigt"), kam allein von "nur diese sichtbar".
        vc.set_active(zeigen)
        # "Nur diese zeigen": alles andere ausblenden. Aktivieren allein
        # genuegt nicht, wenn die Bauteile mitten im Modell stecken — der Nutzer
        # 2026-08-06: "ob nur aktivierte angezeigt werden sollen, das man
        # es auch wirklich sieht". Wiederherstellbar ueber
        # `sichtbarkeit_zurueck`, weil vorher gesichert wurde.
        if params.get("nur_diese"):
            gezeigt = set(zeigen)
            andere = [e for e in alle if e not in gezeigt]
            # ZUERST lesen, dann aendern — sonst merkt man sich den Zustand,
            # den man selbst gerade hergestellt hat.
            zurueck_sichtbar = [e for e in andere if vc.is_visible(e)]
            zurueck_unsichtbar = [e for e in zeigen if not vc.is_visible(e)]
            if andere:
                vc.set_invisible(andere)
            vc.set_visible(zeigen)
            self.sicht_zustand = {"wieder_sichtbar": zurueck_sichtbar,
                                  "wieder_unsichtbar": zurueck_unsichtbar}
        if params.get("zoomen", True):
            vc.zoom_active_elements()
        vc.refresh()
        return {"gezeigt": zeigen, "fehlen": fehlen,
                "isoliert": bool(params.get("nur_diese"))}

    def _m_neu_zeichnen(self, params):
        """Zeichnet Cadworks Ansicht neu — gegen ein veraltetes Bild."""
        return {"neu_gezeichnet": _neu_zeichnen()}

    def _m_sichtbarkeit_zurueck(self, params):
        """Stellt die Sichtbarkeit von vor dem "Im Modell zeigen" wieder her.

        Der gemerkte Zustand wird IMMER verworfen — auch wenn das
        Wiederherstellen scheitert. Sonst stellt ein zweiter Klick ein
        veraltetes Bild wieder her.

        Faellt das Wiederherstellen aus (nichts gesichert, oder cwapi3d
        lehnt den Zustand ab), wird ersatzweise ALLES gezeigt. Dieser Knopf
        darf unter keinen Umstaenden in einem isolierten Modell enden — das
        ist genau die Lage, aus der er herausführen soll.
        """
        import visualization_controller as vc
        zustand, self.sicht_zustand = self.sicht_zustand, None
        weg = None
        if zustand:
            try:
                # Nur zuruecknehmen, was wir selbst angefasst haben. Was der
                # Benutzer vorher ausgeblendet hatte, bleibt ausgeblendet.
                if zustand.get("wieder_sichtbar"):
                    vc.set_visible(zustand["wieder_sichtbar"])
                if zustand.get("wieder_unsichtbar"):
                    vc.set_invisible(zustand["wieder_unsichtbar"])
                weg = "zustand"
            except Exception as exc:                  # noqa: BLE001
                LOG.error("Sichtbarkeit liess sich nicht wiederherstellen: "
                          "%s — zeige ersatzweise alles.", exc)
        if weg is None:
            vc.show_all_elements()
            weg = "alle_zeigen"
        vc.refresh()
        return {"wiederhergestellt": True, "weg": weg}

    def _m_nachricht_senden(self, params):
        """Legt eine Nachricht samt Modell-Kontext in den Briefkasten.

        Laeuft im Hauptthread, weil der Kontext aus cwapi3d kommt: welche
        Elemente gerade aktiv sind, wie sie heissen, und — bei wenigen —
        ihre Facetten. Damit kann eine Anweisung wie "strecke diese Facette
        um 15 mm" ueberhaupt zugeordnet werden.

        Cadwork kennt keine API fuer "welche Facette ist angewaehlt". Wir
        liefern deshalb die Facetten der aktiven Elemente mit, statt so zu
        tun, als waere die Auswahl bekannt.
        """
        text = _als_text(params.get("text"))
        if not text:
            raise ValueError("'text' fehlt")

        kontext = {"element_ids": [], "elemente": [], "facetten_geliefert": False}
        try:
            import element_controller as ec
            aktive = [int(i) for i in ec.get_active_identifiable_element_ids()]
            kontext["element_ids"] = aktive
        except Exception as exc:                      # noqa: BLE001
            kontext["fehler"] = "aktive Elemente nicht lesbar: %s" % exc
            aktive = []

        for eid in aktive[:MAX_KONTEXT_ELEMENTE]:
            eintrag = {"id": eid}
            try:
                import attribute_controller as ac
                eintrag["name"] = ac.get_name(eid)
                eintrag["gruppe"] = ac.get_group(eid)
                eintrag["untergruppe"] = ac.get_subgroup(eid)
            except Exception:                         # noqa: BLE001
                pass
            try:
                import geometry_controller as gc
                eintrag["breite"] = gc.get_width(eid)
                eintrag["hoehe"] = gc.get_height(eid)
                eintrag["laenge"] = gc.get_length(eid)
            except Exception:                         # noqa: BLE001
                pass
            kontext["elemente"].append(eintrag)

        # Facetten nur bei wenigen Elementen — bei 200 Balken waere das
        # eine Datenflut, die niemandem hilft.
        if 0 < len(aktive) <= MAX_KONTEXT_FACETTEN:
            try:
                import geometry_controller as gc
                for eintrag in kontext["elemente"]:
                    facetten = gc.get_element_facets(eintrag["id"])
                    eintrag["facetten"] = _to_jsonable(facetten)
                kontext["facetten_geliefert"] = True
            except Exception as exc:                  # noqa: BLE001
                kontext["facetten_fehler"] = str(exc)

        with self.sperre:
            self.nachricht_zaehler += 1
            eintrag = {
                "nr": self.nachricht_zaehler,
                "zeit": time.time(),
                "text": text,
                "dokument": self.dok_name,
                "kontext": kontext,
                "abgeholt": False,
                # Wie beim Pruefhinweis: derselbe Stempel, damit sich
                # Briefkasten und Hinweise nach demselben Lauf gruppieren
                # lassen — der Nutzer wollte beides sortiert, nicht nur eines.
                "lauf": self.lauf_nr,
            }
            self.postfach.append(eintrag)
            del self.postfach[:-POSTFACH_MAX]
        LOG.info("Briefkasten #%d: %r (%d aktive Elemente)",
                 eintrag["nr"], text[:60], len(kontext["element_ids"]))
        return {"nr": eintrag["nr"],
                "element_ids": kontext["element_ids"],
                "facetten_geliefert": kontext["facetten_geliefert"]}

    def _m_undo(self, params):
        """Loest Cadworks EIGENES Rueckgaengig aus.

        Bewusst kein selbstgebautes Journal: Cadwork fuehrt seinen Undo-Stack
        ohnehin. Ein Parallel-Undo waere eine zweite Wahrheit ueber denselben
        Modellzustand — genau die Sorte Doppelspurigkeit, die spaeter weh tut.

        Damit hier etwas zurueckzunehmen IST, meldet `_m_execute_cwapi3d`
        seit dem 2026-08-06 die je Auftrag neu entstandenen Elemente an
        (`_undo_anmelden`). Bis dahin tat `make_undo()` nachweislich nichts.

        EIN SCHRITT = EIN AUFTRAG, nicht ein Zeichenlauf. Ein Lauf ueber
        3360 Bauteile kommt in 17 Haeppchen — der braucht 17 Schritte, und
        mehr als 10 laesst diese Methode bewusst nicht auf einmal zu.
        """
        import element_controller as ec
        schritte = int(params.get("schritte", 1))
        if not 1 <= schritte <= 10:
            raise ValueError("'schritte' muss zwischen 1 und 10 liegen")
        for _ in range(schritte):
            ec.make_undo()
        return {"rueckgaengig": schritte}

    def _m_redo(self, params):
        """Holt zurueck, was ein Rueckgaengig weggenommen hat.

        Wunsch 2026-08-06 — und Cadwork kann es selbst, `ec.make_redo`.
        Gemessen am selben Tag im Testdokument: 1790 Elemente, drei Balken
        erzeugt (1793), Undo (1790), Redo — **1793**, und die Gruppe war
        wieder vollstaendig da.

        Auch hier kein eigenes Journal: Cadwork fuehrt den Stapel, wir
        bedienen ihn nur. Ein selbstgebautes Wiederherstellen muesste die
        Geometrie zwischenlagern und waere eine zweite Wahrheit ueber
        denselben Modellzustand.
        """
        import element_controller as ec
        schritte = int(params.get("schritte", 1))
        if not 1 <= schritte <= 10:
            raise ValueError("'schritte' muss zwischen 1 und 10 liegen")
        for _ in range(schritte):
            ec.make_redo()
        return {"wiederhergestellt": schritte}

    def modell_methode(self, name):
        return {
            "get_document_info": self._m_get_document_info,
            "execute_cwapi3d": self._m_execute_cwapi3d,
            "elemente_zeigen": self._m_elemente_zeigen,
            "nachricht_senden": self._m_nachricht_senden,
            "sichtbarkeit_zurueck": self._m_sichtbarkeit_zurueck,
            "neu_zeichnen": self._m_neu_zeichnen,
            "undo": self._m_undo,
            "redo": self._m_redo,
        }.get(name)


# --- Antwort-Bausteine ----------------------------------------------------

def _fehler(code, meldung, details=""):
    return {"ok": False, "error": code, "message": meldung, "details": details}


def _ok(result):
    return {"ok": True, "result": result}


# --- Worker-seitige Methoden (nie ueber die Queue!) -----------------------

def _worker_methoden(d):
    """Alles, was ohne den Cadwork-Hauptthread beantwortbar ist.

    Genau das macht die Oberflaeche moeglich: Status, Pause, Fortsetzen und
    sicheres Beenden funktionieren auch waehrend eines langen Zeichenlaufs.
    """
    cfg = d.cfg

    def m_ping(params):
        # 'pong' bleibt drin — der alte Smoke-Test prueft genau darauf.
        return _ok({"pong": True, "instanz": cfg.instanz, "port": cfg.port,
                    "zustand": d.zustand, "version": CORE_VERSION})

    def m_status(params):
        return _ok(d.status())

    def m_pause(params):
        with d.sperre:
            d.pausiert = True
            if d._zustand not in BESCHAEFTIGT and not d.beenden_nach_auftrag:
                d._zustand = "paused"
        LOG.info("Pause angefordert")
        return _ok({"pausiert": True, "zustand": d.zustand,
                    "hinweis": "Laufender Auftrag laeuft fertig, danach werden "
                               "Modell-Auftraege abgelehnt."})

    def m_resume(params):
        with d.sperre:
            d.pausiert = False
            if d._zustand == "paused":
                d._zustand = "ready"
        LOG.info("Fortsetzen angefordert")
        return _ok({"pausiert": False, "zustand": d.zustand})

    def m_shutdown(params):
        zustand = d.zustand
        if zustand not in SOFORT_BEENDBAR:
            # Regel 2: waehrend eines laufenden Auftrags NICHT sofort beenden.
            # Der Auftrag liefe im Cadwork-Hauptthread weiter — "abgebrochen"
            # waere schlicht gelogen.
            with d.sperre:
                auftrag = d.aktueller_auftrag
            was = ((auftrag.beschreibung or auftrag.methode) if auftrag
                   else ZUSTAND_TEXT.get(zustand, zustand))
            return _fehler(
                "busy",
                "Es laeuft gerade ein Auftrag (%s). Sofortiges Beenden wuerde "
                "ihn nicht stoppen, sondern nur die Verbindung kappen. "
                "'shutdown_after_current' verwenden." % was,
                "zustand=%s" % zustand,
            )
        verworfen = _warteschlange_verwerfen(d, "Bridge wird beendet")
        LOG.info("Sofortiges Beenden aus Zustand %r (%d wartende verworfen)",
                 zustand, verworfen)
        # `d.beenden` setzt der Worker ERST nach dem Absenden der Antwort —
        # sonst schliesst der finally-Block in serve() unter Umstaenden den
        # Socket, bevor der Client sein "shutting_down" gelesen hat.
        return _ok({"shutting_down": True, "verworfene_auftraege": verworfen})

    def m_shutdown_after_current(params):
        with d.sperre:
            d.beenden_nach_auftrag = True
            laeuft = d._zustand in BESCHAEFTIGT
            if not laeuft:
                d._zustand = "stopping_after_job"
        verworfen = _warteschlange_verwerfen(
            d, "Bridge beendet sich nach dem laufenden Auftrag")
        LOG.info("Beenden nach Auftrag angefordert (laeuft=%s, %d verworfen)",
                 laeuft, verworfen)
        return _ok({"beenden_nach_auftrag": True,
                    "auftrag_laeuft": laeuft,
                    "verworfene_auftraege": verworfen,
                    "zustand": d.zustand})

    def m_discard_pending(params):
        n = _warteschlange_verwerfen(d, "Wartende Auftraege verworfen")
        return _ok({"verworfene_auftraege": n})

    def m_release_write_lease(params):
        client_id = _als_text(params.get("client_id"))
        frei = d.lizenz_freigeben(client_id or None)
        return _ok({"freigegeben": frei})

    def m_hinweis_melden(params):
        """Die KI (oder ein Builder) meldet etwas, das ein Mensch sehen soll.

        Ausdruecklich KEINE Kollisionssuche: hier landet nur, was jemand
        aktiv meldet — eine Annahme, eine Unsicherheit, eine Builder-Warnung,
        eine fehlende Angabe. Cadwork hat eine eigene Kollisionskontrolle;
        eine zweite daneben waere doppelte Arbeit mit halber Qualitaet.
        """
        titel = _als_text(params.get("titel") or params.get("title"))
        if not titel:
            raise ValueError("'titel' fehlt")
        ids = params.get("element_ids") or []
        if not isinstance(ids, (list, tuple)):
            ids = [ids]
        sauber = []
        for i in ids:
            try:
                sauber.append(int(i))
            except (TypeError, ValueError):
                continue
        stufe = _als_text(params.get("schweregrad")).lower() or "hinweis"
        if stufe not in ("hinweis", "warnung", "fehler", "frage"):
            stufe = "hinweis"
        # Dringlichkeit 1..5, damit die KI gewichten kann (ausdruecklicher Wunsch
        # 2026-08-06). BEWUSST getrennt vom Schweregrad: eine 'frage' kann
        # dringend sein und ein 'fehler' unwichtig. Fehlt die Angabe, wird
        # sie aus dem Schweregrad abgeleitet, statt alles auf 3 zu setzen.
        try:
            dring = int(params.get("dringlichkeit")
                        or DRINGLICHKEIT_AUS_STUFE.get(stufe, 3))
        except (TypeError, ValueError):
            dring = DRINGLICHKEIT_AUS_STUFE.get(stufe, 3)
        dring = max(1, min(5, dring))
        with d.sperre:
            d.hinweis_zaehler += 1
            eintrag = {
                "nr": d.hinweis_zaehler,
                "zeit": time.time(),
                "titel": titel,
                "text": _als_text(params.get("text")),
                "schweregrad": stufe,
                "dringlichkeit": dring,
                "quelle": _als_text(params.get("quelle")) or "KI",
                "auftrag": _als_text(params.get("operation_id")),
                # Welcher Zeichenlauf lief, als dieser Hinweis kam. Das
                # Dashboard gruppiert danach; ohne den Stempel bliebe ihm nur
                # die Zeitluecke, und die trennt zwei kurz aufeinander
                # folgende Laeufe nicht.
                "lauf": d.lauf_nr,
                "element_ids": sauber,
                "status": "offen",
                # Gelesen ist NICHT dasselbe wie erledigt — wie bei E-Mail.
                # Anklicken setzt gelesen; von Hand laesst es sich wieder
                # auf ungelesen stellen.
                "gelesen": False,
            }
            d.hinweise.append(eintrag)
            del d.hinweise[:-HINWEISE_MAX]
        LOG.info("Hinweis #%d (%s): %s%s", eintrag["nr"], stufe, titel,
                 (" [%d Elemente]" % len(sauber)) if sauber else "")
        return _ok({"nr": eintrag["nr"], "hinweise_offen":
                    sum(1 for h in d.hinweise if h["status"] == "offen")})

    def m_hinweise(params):
        nur_offen = bool(params.get("nur_offen"))
        with d.sperre:
            liste = [dict(h) for h in d.hinweise
                     if not nur_offen or h["status"] == "offen"]
        return _ok({"hinweise": liste, "anzahl": len(liste)})

    def m_hinweis_status(params):
        """Status und/oder gelesen setzen — beides unabhaengig voneinander.

        Rueckmeldung 2026-08-06: "aehnlich wie E-Mail" — anklicken macht gelesen,
        aber man kann es wieder auf ungelesen stellen, und 'erledigt' ist
        davon unabhaengig.
        """
        nr = params.get("nr")
        neu = _als_text(params.get("status")).lower()
        if neu and neu not in ("offen", "geprueft", "erledigt", "ignoriert"):
            raise ValueError("unbekannter Status %r" % neu)
        gelesen = params.get("gelesen")
        if not neu and gelesen is None:
            neu = "erledigt"        # alter Aufruf ohne Angabe
        with d.sperre:
            for h in d.hinweise:
                if h["nr"] == nr:
                    if neu:
                        h["status"] = neu
                    if gelesen is not None:
                        h["gelesen"] = bool(gelesen)
                    return _ok({"nr": nr, "status": h["status"],
                                "gelesen": h.get("gelesen", False)})
        return _fehler("not_found", "Kein Hinweis mit Nummer %r" % nr)

    def m_hinweis_loeschen(params):
        """Hinweise WEGWERFEN, nicht nur abhaken.

        Rueckmeldung 2026-08-06: "es braucht eine Moeglichkeit, Hinweise die
        abgearbeitet werden zu loeschen lassen durch die Bridge, nicht nur
        als erledigt zu markieren." Abgehakte Hinweise sammeln sich sonst
        an und verdecken die neuen.

        `nr` loescht einen, `erledigte=True` raeumt alle abgehakten weg.
        """
        nr = params.get("nr")
        alle_erledigten = bool(params.get("erledigte"))
        with d.sperre:
            vorher = len(d.hinweise)
            if alle_erledigten:
                d.hinweise[:] = [h for h in d.hinweise
                                 if h["status"] != "erledigt"]
            elif nr is not None:
                d.hinweise[:] = [h for h in d.hinweise if h["nr"] != nr]
            else:
                return _fehler("bad_value",
                               "'nr' oder 'erledigte=true' angeben")
            weg = vorher - len(d.hinweise)
        if not weg and nr is not None:
            return _fehler("not_found", "Kein Hinweis mit Nummer %r" % nr)
        LOG.info("Hinweise geloescht: %d", weg)
        return _ok({"geloescht": weg, "verbleibend": len(d.hinweise)})

    def m_nachrichten_abholen(params):
        """Holt die noch nicht gelesenen Nachrichten — fuer die KI.

        Markiert sie als abgeholt, damit dieselbe Anweisung nicht zweimal
        umgesetzt wird. `alle=True` liefert auch schon Gelesenes, ohne den
        Zustand anzufassen.
        """
        alle = bool(params.get("alle"))
        with d.sperre:
            offen = [n for n in d.postfach if alle or not n["abgeholt"]]
            kopien = [dict(n) for n in offen]
            if not alle:
                for n in offen:
                    n["abgeholt"] = True
        if kopien and not alle:
            LOG.info("%d Nachricht(en) abgeholt", len(kopien))
        return _ok({"nachrichten": kopien, "anzahl": len(kopien)})

    def m_schnellzeichnen(params):
        an = params.get("an")
        with d.sperre:
            if an is not None:
                d.schnellzeichnen = bool(an)
            zustand = d.schnellzeichnen
        LOG.info("Schnellzeichnen: %s", "AN" if zustand else "aus")
        return _ok({"schnellzeichnen": zustand})

    def m_zeichenmodus(params):
        """Stellt den Regler — oder liest ihn nur ab, wenn nichts mitkommt.

        EINE Stellschraube, mehr nicht. Der frueher hier eingebaute
        Entwicklermodus mit zwei getrennten Reglern ist wieder raus —
        Rueckmeldung 2026-08-06: "unuebersichtlich und ueberfluessig, einfach ein
        regler, auto, slow, cowork, fast, max. reicht".
        """
        gueltig = [m["schluessel"] for m in ZEICHENMODI]
        modus = params.get("modus")
        if modus is not None:
            if modus not in gueltig:
                return _fehler("bad_mode",
                               "Unbekannter Zeichenmodus %r. Moeglich: %s"
                               % (modus, ", ".join(gueltig)))
            with d.sperre:
                d.zeichenmodus = modus
        m = d.modus()
        with d.sperre:
            # Schnellzeichnen ist keine eigene Bedienung mehr, es folgt der
            # Stufe. Die Methode `schnellzeichnen` bleibt fuer alte Clients.
            d.schnellzeichnen = bool(m["schnell"])
        LOG.info("Zeichenmodus: %s (schnell=%s, Grenze=%s)", m["schluessel"],
                 m["schnell"],
                 ("%.1f s" % m["blockade_s"]) if m["blockade_s"] else "keine")
        return _ok({"zeichenmodus": m["schluessel"],
                    "schnellzeichnen": bool(m["schnell"]),
                    "blockade_ziel_s": m["blockade_s"],
                    "balken_waehrend_lauf": m["balken"],
                    "haeppchen_empfehlung": d.haeppchen_empfehlung(),
                    "ms_je_teil": d.ms_je_teil,
                    "stufen": [dict(x) for x in ZEICHENMODI]})

    def m_undo_aenderungen(params):
        """Drei Stufen fuer "Aenderungen an bestehenden Bauteilen ruecknehmbar".

        aus         nie anmelden — schnellste Variante, nichts ruecknehmbar
        bis_grenze  bis `grenze` Bauteile anmelden (Vorgabe 500)
        immer       immer anmelden, egal wie viele

        Die Grenze existiert, weil das Anmelden rund 2,6 ms je Bauteil
        kostet: 100 Sparren = 0,26 s (kaum merklich), 2000 = 5 s (spuerbar).
        """
        stufe = params.get("stufe")
        grenze = params.get("grenze")
        with d.sperre:
            if stufe is not None:
                if stufe not in ("aus", "bis_grenze", "immer"):
                    return _fehler("bad_mode",
                                   "Unbekannte Stufe %r. Moeglich: aus, "
                                   "bis_grenze, immer" % stufe)
                d.undo_aenderungen = stufe
            if grenze is not None:
                try:
                    d.undo_grenze = max(0, int(grenze))
                except (TypeError, ValueError):
                    return _fehler("bad_value", "grenze muss eine Zahl sein")
            jetzt, g = d.undo_aenderungen, d.undo_grenze
        LOG.info("Aenderungen ruecknehmbar: %s (Grenze %d)", jetzt, g)
        return _ok({"stufe": jetzt, "grenze": g,
                    "ms_je_bauteil": 2.6,
                    "uebersprungen": d.uebersprungen_geaendert})

    def m_verlauf(params):
        with d.sperre:
            return _ok({"verlauf": [dict(v) for v in d.verlauf]})

    def m_list_store_keys(params):
        with d.store_sperre:
            keys = list(d.store.keys())
        return _ok({"keys": keys, "count": len(keys)})

    def m_clear_store(params):
        with d.store_sperre:
            n = len(d.store)
            d.store.clear()
        LOG.info("clear_store: %d Eintraege geloescht", n)
        return _ok({"cleared": n})

    return {
        "ping": m_ping,
        "status": m_status,
        "pause": m_pause,
        "resume": m_resume,
        "shutdown": m_shutdown,
        "shutdown_after_current": m_shutdown_after_current,
        "discard_pending": m_discard_pending,
        "release_write_lease": m_release_write_lease,
        "hinweis_melden": m_hinweis_melden,
        "hinweise": m_hinweise,
        "hinweis_status": m_hinweis_status,
        "hinweis_loeschen": m_hinweis_loeschen,
        "verlauf": m_verlauf,
        "nachrichten_abholen": m_nachrichten_abholen,
        "schnellzeichnen": m_schnellzeichnen,
        "zeichenmodus": m_zeichenmodus,
        "undo_aenderungen": m_undo_aenderungen,
        "list_store_keys": m_list_store_keys,
        "clear_store": m_clear_store,
    }


def _warteschlange_verwerfen(d, grund):
    """Verwirft NUR noch nicht gestartete Auftraege — kontrolliert.

    Der laufende Auftrag wird nie angefasst: er lebt im Cadwork-Hauptthread
    und laesst sich von aussen nicht anhalten, ohne Cadwork zu gefaehrden.
    """
    n = 0
    while True:
        try:
            job = d.job_queue.get_nowait()
        except queue.Empty:
            break
        job.verworfen = True
        job.response = _fehler("discarded", grund,
                               "Auftrag war noch nicht gestartet.")
        job.event.set()
        n += 1
    return n


# --- Verbindungsbehandlung ------------------------------------------------

def _read_line(conn):
    """Liest bis zum naechsten Newline. Liefert None bei sauberem EOF."""
    buffer = bytearray()
    while True:
        try:
            chunk = conn.recv(4096)
        except (ConnectionResetError, OSError):
            return None
        if not chunk:
            return None if not buffer else bytes(buffer)
        buffer.extend(chunk)
        if b"\n" in chunk:
            line, _, _rest = bytes(buffer).partition(b"\n")
            return line


def _send_json(conn, payload):
    data = (json.dumps(payload) + "\n").encode("utf-8")
    try:
        conn.sendall(data)
        return True
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        LOG.error("Senden fehlgeschlagen: %s", exc)
        return False


def _annahme_pruefen(d, methode, meta, params):
    """Darf dieser Modell-Auftrag ueberhaupt in die Warteschlange?

    Hier — und nur hier — wird abgelehnt statt still eingereiht. Ein zweiter
    Schreibauftrag soll nicht unbemerkt hinter einem anderen verschwinden.
    """
    with d.sperre:
        if d.beenden or d.beenden_nach_auftrag:
            return _fehler("shutting_down",
                           "%s beendet sich gerade und nimmt keine neuen "
                           "Auftraege mehr an." % d.cfg.anzeigename,
                           "zustand=%s" % d._zustand)
        if d.pausiert:
            return _fehler(
                "bridge_paused",
                "%s ist pausiert. Modell-Auftraege werden nicht angenommen, "
                "damit von Hand in Cadwork gearbeitet werden kann. "
                "'resume' hebt die Pause auf." % d.cfg.anzeigename,
                "zustand=paused")
        wartend = d.job_queue.qsize()
    if wartend >= d.cfg.max_warteschlange:
        return _fehler("queue_full",
                       "Es warten bereits %d Auftraege. Weitere werden "
                       "abgelehnt, statt sie unbemerkt anzuhaengen." % wartend,
                       "max_warteschlange=%d" % d.cfg.max_warteschlange)

    # Dokument-Identitaet pruefen, BEVOR etwas ausgefuehrt wird.
    erwartet = _als_text(params.get("expect_document"))
    if erwartet:
        with d.sperre:
            dok = d.dok_name
        if not dok:
            return _fehler("document_unknown",
                           "Dokumentname ist (noch) nicht bekannt — der "
                           "Auftrag wurde NICHT ausgefuehrt.",
                           "expect_document=%r" % erwartet)
        if erwartet.lower() not in dok.lower():
            return _fehler("wrong_document",
                           "Abbruch: erwartet wurde ein Dokument mit %r, offen "
                           "ist aber %r. Es wurde NICHTS ausgefuehrt."
                           % (erwartet, dok),
                           "instanz=%s port=%d" % (d.cfg.instanz, d.cfg.port))

    if meta.zugriff == "write":
        fehler = d.lizenz_pruefen_und_nehmen(
            meta, uebernehmen=bool(params.get("uebernehmen")))
        if fehler:
            return fehler
    return None


def _handle_connection(d, conn, addr):
    """Worker-Thread (daemon): bedient eine Verbindung seriell."""
    LOG.info("Verbindung von %s", addr)
    worker_methoden = _worker_methoden(d)
    try:
        while not d.beenden:
            line = _read_line(conn)
            if line is None:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                _send_json(conn, {"id": None, "ok": False,
                                  "error": "invalid_request",
                                  "message": str(exc), "details": ""})
                continue
            # Gueltiges JSON ist noch kein gueltiger Request: `"text"` oder
            # `[1,2]` parsen anstandslos. Die Vorversion ist an dieser Stelle
            # mit AttributeError im Worker gestorben — die Verbindung brach
            # dann ohne Antwort ab.
            if not isinstance(request, dict):
                _send_json(conn, {"id": None, "ok": False,
                                  "error": "invalid_request",
                                  "message": "Request muss ein JSON-Objekt "
                                             "sein, war aber %s"
                                             % type(request).__name__,
                                  "details": ""})
                continue
            request_id = request.get("id")
            methode = request.get("method")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                params = {}

            # 1) Steuer- und Statusmethoden: sofort, ohne Hauptthread.
            handler = worker_methoden.get(methode)
            if handler is not None:
                try:
                    antwort = handler(params)
                except Exception as exc:              # noqa: BLE001
                    antwort = _fehler(type(exc).__name__, str(exc),
                                      traceback.format_exc())
                gesendet = _send_json(conn, {"id": request_id, **antwort})
                if methode == "shutdown" and antwort.get("ok"):
                    # Erst jetzt — die Antwort ist raus.
                    d.beenden = True
                    break
                if not gesendet:
                    break
                continue

            # 2) Modell-Auftraege: nur ueber die Queue an den Hauptthread.
            if methode not in MODELL_METHODEN:
                _send_json(conn, {"id": request_id, "ok": False,
                                  "error": "unknown_method",
                                  "message": "Unbekannte Methode: %r" % methode,
                                  "details": ""})
                continue

            try:
                meta = AuftragsMeta(methode, params)
                abgelehnt = _annahme_pruefen(d, methode, meta, params)
            except Exception as exc:                  # noqa: BLE001
                # Sicherheitsnetz: ein Worker darf niemals sterben, ohne dem
                # Client zu antworten — sonst sieht der Client ein Timeout und
                # weiss nicht, ob sein Auftrag gelaufen ist.
                LOG.error("Annahmepruefung abgestuerzt: %s", exc)
                _send_json(conn, {"id": request_id, "ok": False,
                                  "error": type(exc).__name__,
                                  "message": str(exc),
                                  "details": traceback.format_exc()})
                continue
            if abgelehnt is not None:
                LOG.info("Abgelehnt (%s): %s", abgelehnt["error"],
                             abgelehnt["message"])
                if not _send_json(conn, {"id": request_id, **abgelehnt}):
                    break
                continue

            job = Job(request_id, methode, params, meta)
            d.job_queue.put(job)
            LOG.info("Eingereiht: %s%s [%s, client=%s]", methode,
                         (" — %s" % meta.beschreibung) if meta.beschreibung else "",
                         meta.zugriff, meta.client)

            while not job.event.wait(timeout=JOB_WAIT_TIMEOUT_SECONDS):
                if d.beenden:
                    break

            if job.response is None:
                antwort = _fehler("shutting_down",
                                  "Bridge wurde beendet, bevor der Auftrag lief")
            else:
                antwort = job.response
            gesendet = _send_json(conn, {"id": request_id, **antwort})
            job.gesendet.set()          # Hauptthread darf jetzt beenden
            if not gesendet:
                break
    finally:
        with d.verbindungs_sperre:
            try:
                d.offene_verbindungen.remove(conn)
            except ValueError:
                pass
        try:
            conn.close()
        except OSError:
            pass
        LOG.info("Verbindung %s geschlossen", addr)


def _listener_loop(d, server_sock):
    LOG.info("Listener auf %s:%s aktiv", d.cfg.host, d.cfg.port)
    while not d.beenden:
        try:
            conn, addr = server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        with d.verbindungs_sperre:
            d.offene_verbindungen.append(conn)
        threading.Thread(
            target=_handle_connection, args=(d, conn, addr),
            name="Open-MCP-CAD-%s-Worker-%s" % (d.cfg.instanz, addr[1]),
            daemon=True,
        ).start()
    LOG.info("Listener beendet")


# --- Win32-Message-Pumpe (optional, standardmaessig AUS) ------------------

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.wintypes.LONG), ("y", ctypes.wintypes.LONG)]

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.wintypes.HWND),
            ("message", ctypes.wintypes.UINT),
            ("wParam", ctypes.wintypes.WPARAM),
            ("lParam", ctypes.wintypes.LPARAM),
            ("time", ctypes.wintypes.DWORD),
            ("pt", _POINT),
            ("lPrivate", ctypes.wintypes.DWORD),
        ]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _PeekMessageW = _user32.PeekMessageW
    _PeekMessageW.argtypes = [ctypes.POINTER(_MSG), ctypes.wintypes.HWND,
                              ctypes.wintypes.UINT, ctypes.wintypes.UINT,
                              ctypes.wintypes.UINT]
    _PeekMessageW.restype = ctypes.wintypes.BOOL
    _TranslateMessage = _user32.TranslateMessage
    _TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    _TranslateMessage.restype = ctypes.wintypes.BOOL
    _DispatchMessageW = _user32.DispatchMessageW
    _DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
    _DispatchMessageW.restype = ctypes.c_ssize_t
    _PM_REMOVE = 0x0001
    _WM_QUIT = 0x0012

    def _pumpe(d, maximum):
        """Arbeitet HOECHSTENS `maximum` Messages ab.

        Die Begrenzung ist der einzige Unterschied zur Vorversion: dort lief
        die Schleife, bis PeekMessage nichts mehr lieferte. Eine Message, die
        sich beim Verarbeiten selbst neu erzeugt (klassisch WM_PAINT ohne
        gueltige Update-Region), haelt so eine Schleife endlos fest.
        Das ist kein Ersatz fuer den Nachweis im echten Cadwork — deshalb ist
        die Pumpe standardmaessig aus.
        """
        msg = _MSG()
        n = 0
        try:
            while n < maximum and _PeekMessageW(ctypes.byref(msg), None, 0, 0,
                                                _PM_REMOVE):
                if msg.message == _WM_QUIT:
                    d.beenden = True
                    return n
                _TranslateMessage(ctypes.byref(msg))
                _DispatchMessageW(ctypes.byref(msg))
                n += 1
        except OSError as exc:
            # Gemessen am 2026-08-04 in Cadwork 2026:
            #   "access violation reading 0x0000000000000048" in
            #   _DispatchMessageW, waehrend der Benutzer im Cadwork-Menue
            #   weiterklickte. Der Aufruf fremder Fensterprozeduren aus einem
            #   laufenden Plugin heraus ist also nicht nur riskant, er geht
            #   real schief.
            # Vorher hat dieser Fehler die ganze Hauptschleife mitgenommen und
            # den Steckplatz beendet. Jetzt stirbt nur die Pumpe: die
            # Verbindung laeuft weiter, die Cadwork-UI bleibt eben
            # eingefroren, und der Status sagt beides im Klartext.
            d.cfg.ui_pumpe = False
            d.ui_pumpe_fehler = "%s: %s" % (type(exc).__name__, exc)
            LOG.error("UI-Pumpe abgeschaltet — Zugriffsfehler beim Verarbeiten "
                      "einer Windows-Message: %s. Die Verbindung laeuft weiter, "
                      "die Cadwork-Oberflaeche bleibt bis zum Beenden des "
                      "Plugins eingefroren.", exc)
        return n
else:
    def _pumpe(d, maximum):
        return 0


# --- Hauptthread-Loop -----------------------------------------------------

def _auftrag_ausfuehren(d, job):
    """Fuehrt einen Modell-Auftrag aus. Laeuft IMMER im Cadwork-Hauptthread."""
    meta = job.meta
    meta.start_epoch = time.time()
    meta.start_mono = time.monotonic()
    with d.sperre:
        d.aktueller_auftrag = meta
        d._zustand = "busy_write" if meta.zugriff == "write" else "busy_read"

    LOG.info("Verarbeite %s%s (id=%s, %s)", job.method,
                 (" — %s" % meta.beschreibung) if meta.beschreibung else "",
                 job.request_id, meta.zugriff)

    methode = d.modell_methode(job.method)
    # Schnellzeichnen: nur fuer echte Modell-Arbeit, nicht fuers Anzeigen.
    schnell = ((d.schnellzeichnen or bool(job.params.get("schnell")))
               and job.method == "execute_cwapi3d")
    if schnell and not d.bildschirm_aus:
        # Einmal abschalten und ABGESCHALTET LASSEN, solange Auftraege
        # kommen. Der Lauf ueber 125 Fensterzellen am 2026-08-05 hat sonst
        # 125-mal um- und zurueckgeschaltet — und danach stand ein
        # veraltetes Bild (Material und Ausklinkungen fehlten, bis Cadwork
        # neu gestartet wurde). Wieder eingeschaltet wird im Leerlauf,
        # siehe _tick, wenn wirklich Ruhe ist.
        d.bildschirm_aus = _bildschirm_aus(d)
    meta.schnell = bool(schnell and d.bildschirm_aus)
    # Paketweise: nur ein Paket eines Paketlaufs, nur wenn wirklich im
    # Dunkeln gezeichnet wird, und nur in einer Stufe, die es will ('Auto').
    # Einzelauftraege behalten Vorhang und Nachziehen im Leerlauf.
    meta.paketweise = bool(meta.paket and meta.schnell
                           and d.modus()["paketweise"])

    # Ladebalken, damit man sieht, dass gearbeitet wird, solange der
    # Bildschirm dunkel ist. Am 2026-08-06 kam die Frage, ob er bei
    # JEDEM langen Lauf kommt — also nicht nur in 'max':
    #   * in 'max' sofort (dort ist von Anfang an klar, dass man nichts sieht)
    #   * sonst ab dem ZWEITEN Auftrag eines Laufs. Ein einzelner kurzer
    #     Auftrag laesst den Balken damit nicht aufblitzen.
    # Gezeichnet wird er ZWISCHEN den Auftraegen (dann gehoert der
    # Hauptthread kurz wieder Cadwork); WAEHREND eines Auftrags steht er
    # still — in 'max' springt er deshalb in wenigen Stufen.
    # Der Fortschritt haengt an der DAUER, nicht am Schnellzeichnen. Bis
    # 2026-08-07 stand die ganze Anzeige hinter `meta.schnell` — in
    # 'langsam' konnte sie damit nie erscheinen, obwohl gerade dort ein
    # Lauf am laengsten dauert (gemessen dreimal so lang wie 'schnell').
    zeichnet = (job.method == "execute_cwapi3d" and meta.zugriff == "write")
    if zeichnet:
        d.lauf_auftraege += 1
        if not d.lauf_start_mono:
            d.lauf_start_mono = time.monotonic()
    # Ob der Balken kommt, haengt an der ERWARTETEN DAUER, nicht an einer
    # Auftragszahl — Rueckmeldung 2026-08-06: "verstehe nicht wieso es nicht an die
    # auftragsmenge und schnelligkeit gekoppelt ist". Beides weiss die
    # Bridge: die angemeldete Bauteilzahl und den gelernten Preis je
    # Bauteil. Dazu die bisher verstrichene Zeit des Laufs, damit auch ein
    # Auftrag ohne Anmeldung den Balken ausloest, sobald es wirklich dauert.
    zeigen = False
    if zeichnet:
        try:
            n_teile = int(job.params.get("bauteile") or 0)
        except (TypeError, ValueError):
            n_teile = 0
        schaetzung = n_teile * d.ms_je_teil / 1000.0
        bisher = time.monotonic() - (d.lauf_start_mono or time.monotonic())
        zeigen = (d.modus()["balken"] or schaetzung >= BALKEN_AB_S
                  or bisher >= BALKEN_AB_S)
    if zeigen:
        neu_lauf = not d.lauf_balken
        if not d.lauf_balken:
            # Welche Anzeige es wird, entscheidet _lauf_balken_zeigen: eigenes
            # Fenster wenn moeglich, sonst Cadworks Balken unten rechts.
            d.lauf_balken = True
            with d.sperre:
                d.lauf_gezeichnet = 0
                d.lauf_gesamt = None
                d.lauf_takte = 0
                # Ab hier zaehlt ein NEUER Zeichenlauf. Die Nummer landet auf
                # jedem Pruefhinweis und jeder Briefkasten-Nachricht, die
                # danach entsteht — damit kann das Dashboard sie gruppieren.
                # Rueckmeldung 2026-08-15: "zb ein neuer zeichenlauf ging durch mit
                # neuen hinweisen, dann klar gruppiert".
                d.lauf_nr += 1
        gesamt = job.params.get("lauf_gesamt")
        if gesamt:
            try:
                with d.sperre:
                    d.lauf_gesamt = int(gesamt)
            except (TypeError, ValueError):
                pass
        # K12: VOR dem Auftrag — der Haken sagt "KI zeichnet", solange der
        # Hauptthread dem Auftrag gehoert (danach kaeme es zu spaet).
        _lauf_balken_zeigen(d, "start", meta, neu_lauf)
    elif d.lauf_balken:
        # Ein Auftrag MITTEN in einem Lauf, der selbst keinen Balken
        # ausloest (etwa ein Leseauftrag): nur der Haken erfaehrt davon
        # ("KI schaut ins Modell"); Balken und Fenster wie bisher.
        _lauf_anzeige_rufen(d, "start", meta)
    else:
        # 2.19.1: ein Auftrag ohne Lauf — der Haken erfaehrt ihn trotzdem
        # VOR dem Ausfuehren (nur fuer die Zustandspille, keine Anzeige).
        _auftrag_anzeige_rufen(d, meta)
    if methode is None:
        antwort = _fehler("unknown_method", "Unbekannte Methode: %r" % job.method)
    else:
        try:
            antwort = _ok(methode(job.params))
        except Exception as exc:                      # noqa: BLE001
            antwort = _fehler(type(exc).__name__, str(exc), traceback.format_exc())
        finally:
            # NICHT hier wieder einschalten: das erledigt der Leerlauf, wenn
            # keine weiteren Auftraege mehr kommen. Damit bleibt es bei EINER
            # Umschaltung je Zeichenlauf statt einer je Auftrag — und Cadwork
            # bekommt danach echte Leerlaufzeit zum Neuzeichnen.
            # (Ausnahme: ein Paket, das paketweise laeuft, direkt unten.)
            d.letzter_auftrag_mono = time.monotonic()

    if meta.paketweise:
        # Auch nach einem Fehler: was das Paket bis dahin angelegt hat,
        # steht im Modell und soll nicht unfertig im Bild bleiben. VOR der
        # Antwort, damit "Paket k fertig" auch "Paket k sichtbar" heisst —
        # und die Dauer des Pakets ehrlich die ganze Blockade nennt.
        try:
            info = _paket_nachziehen(d, meta)
        except Exception as exc:                      # noqa: BLE001
            # Nie die Antwort verlieren: ohne sie wartet der Server bis zu
            # seiner Zeitgrenze, und der Zustand bliebe "Bearbeitet Modell".
            LOG.error("Paket nachziehen fehlgeschlagen: %s", exc)
            info = None
        d.letzter_auftrag_mono = time.monotonic()
        if (info and antwort.get("ok")
                and isinstance(antwort.get("result"), dict)):
            antwort["result"]["paket_nachgezogen"] = info

    dauer = round(time.monotonic() - meta.start_mono, 2)
    if job.method == "execute_cwapi3d" and antwort.get("ok"):
        # Aus echten Auftraegen lernen, was ein Bauteil gerade kostet.
        # NUR aus Auftraegen, die auch gezeichnet haben (write): ein
        # Leseauftrag ueber dieselbe Bauteilzahl waere um Groessenordnungen
        # billiger und wuerde den gelernten Preis verfaelschen.
        if zeichnet:
            d.tempo_lernen(job.params.get("bauteile"), dauer)
        if d.lauf_balken:
            try:
                with d.sperre:
                    d.lauf_gezeichnet += int(job.params.get("bauteile") or 0)
            except (TypeError, ValueError):
                pass
            _lauf_balken_zeigen(d, "fortschritt", meta)
    elif d.lauf_balken:
        _lauf_anzeige_rufen(d, "fortschritt", meta)
    with d.sperre:
        d.aktueller_auftrag = None
        d.auftraege_gesamt += 1
        d.letzter_auftrag = {
            "methode": job.method,
            "beschreibung": meta.beschreibung,
            "operation_id": meta.operation_id,
            "zugriff": meta.zugriff,
            "client": meta.client,
            "beendet": time.time(),
            "dauer_s": dauer,
            "schnell": meta.schnell,
            "paket": list(meta.paket) if meta.paket else None,
            "paketweise": meta.paketweise,
            "ok": bool(antwort.get("ok")),
        }
        if not antwort.get("ok"):
            d.letzter_fehler = {
                "zeit": time.time(),
                "methode": job.method,
                "beschreibung": meta.beschreibung,
                "fehler": antwort.get("error"),
                "meldung": antwort.get("message"),
            }
        d.verlauf.append(dict(d.letzter_auftrag))
        del d.verlauf[:-VERLAUF_MAX]
    job.response = antwort
    job.event.set()

    # Nach einem Schreibauftrag stimmt die Elementzahl im Cache nicht mehr.
    if meta.zugriff == "write" and antwort.get("ok"):
        d.dokument_auffrischen(mit_elementen=True)

    d.zustand_setzen(d._zustand_nach_auftrag())
    LOG.info("Fertig nach %.2f s: %s", dauer,
                 "ok" if antwort.get("ok") else antwort.get("error"))


def _bildschirm_aus(d):
    """Schaltet Cadworks automatische Bildschirm-Auffrischung ab.

    Liefert True, wenn es geklappt hat — nur dann wird hinterher wieder
    eingeschaltet. Schlaegt es fehl, laeuft der Auftrag ganz normal mit
    Auffrischung weiter; das ist langsamer, aber nie kaputt.
    """
    try:
        import utility_controller as uc
        uc.disable_auto_display_refresh()
        return True
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Schnellzeichnen nicht moeglich: %s", exc)
        return False


def _bildschirm_an(d):
    """Auffrischung wieder an, Darstellung nachziehen, neu zeichnen.

    Reihenfolge und Begruendung, Stand 2026-08-06 — hier lag der Anzeigebug,
    an dem zwei Sitzungen geraten haben:

    Ausklinkungen und Materialien fehlten nach einem Lauf mit
    Schnellzeichnen im Bild, waren aber am Modell die ganze Zeit korrekt.
    Die urspruengliche Erklaerung ("das refresh() kommt zu frueh, Cadwork
    hatte keine Runde seiner Ereignisschleife") ist WIDERLEGT: ein zweites,
    verzoegertes Neuzeichnen half nicht, und die Zahl der Umschaltungen
    (125 -> 3) aenderte ebenfalls nichts.

    Der Vergleich, der es entschieden hat, steht bei
    `_dunkle_elemente_nachziehen`: kein Neuzeichnen der WELT hilft, weil die
    Darstellung der einzelnen ELEMENTE nie aufgebaut wurde. Deshalb werden
    sie hier zuerst angefasst, und erst danach wird neu gezeichnet.

    Das zweite, verzoegerte Neuzeichnen bleibt trotzdem drin — es ist
    unabhaengig davon richtig (Cadwork bekommt so eine Runde seiner eigenen
    Ereignisschleife), war aber eben nie die Loesung.
    """
    _bildschirm_zurueck(d)
    # Jetzt ist der Lauf wirklich durch — Balken weg, Ergebnis sichtbar.
    _lauf_balken_weg(d)


def _bildschirm_zurueck(d, mit_balken=True):
    """Der Teil von `_bildschirm_an`, der NICHT das Ende des Laufs ist.

    Auffrischung an, im Dunkeln Entstandenes nachziehen (Vorhang auf, falls
    einer zu ist), neu zeichnen. Am Ende eines Laufs und nach jedem Paket
    eines paketweisen Paketlaufs dieselbe, am 2026-08-06 entschiedene
    Reihenfolge. `mit_balken=False`: kein eigener Fortschrittsbalken fuer das
    Nachziehen (siehe `_paket_nachziehen`). -> Anzahl nachgezogener Elemente.
    """
    try:
        import utility_controller as uc
        uc.enable_auto_display_refresh()
    except Exception as exc:                          # noqa: BLE001
        LOG.error("Bildschirm-Auffrischung liess sich nicht wieder "
                  "einschalten: %s — in Cadwork einmal zoomen hilft.", exc)
    # ERST die im Dunkeln entstandenen Elemente anfassen, DANN neu zeichnen:
    # `vc.refresh()` allein baut ihre Darstellung nachweislich nicht auf.
    n = _dunkle_elemente_nachziehen(d, mit_balken=mit_balken)
    _neu_zeichnen()
    d.refresh_nachholen = 2          # zwei weitere Takte, dann ist Ruhe
    return n


def _paket_nachziehen(d, meta):
    """Nach einem Paket eines Paketlaufs in 'Auto': Bild sofort fertig.

    DER BEFUND (Film 2026-09-25, Log A 23:29-23:43): `execute_cadwork_batch`
    mit 48 Paketen VBA, je 15-20 s. Der Vorhang faellt erst am ENDE eines
    Auftrags; waehrend des Pakets gibt Cadworks eigene Arbeit ihm Runden der
    Ereignisschleife, und es zeichnet die neuen Bauteile schon. Am Paketende
    wurden sie unsichtbar, aufgedeckt erst beim Nachziehen im Leerlauf — das
    kam im ganzen Lauf zweimal (23:32:33 528 Elemente in 2,48 s, 23:43:08
    1760 in 3,79 s), jeweils nur, weil zwischen zwei Paketen zufaellig mehr
    als SCHNELL_RUHE_S lag. Im Bild: Schrauben erscheinen und verschwinden.

    Jetzt, nur fuer so ein Paket: kein Vorhang (siehe `_m_execute_cwapi3d`),
    und direkt danach dasselbe wie am Ende eines Laufs — Auffrischung an,
    Material neu setzen, neu zeichnen. Der Fortschritt bleibt stehen (der
    Lauf ist nicht zu Ende); das naechste Paket schaltet die Auffrischung
    wieder ab. Kosten: je Paket ein Aus/An der Auffrischung und das
    Nachziehen genau der Bauteile dieses Pakets — dieselbe Zahl
    `set_element_material` wie vorher, nur verteilt. Was Cadwork fuer das
    Neuzeichnen zwischen den Paketen braucht, ist offline nicht messbar:
    deshalb stehen Zahl und Dauer im Log, im Ergebnis des Pakets und im
    Status (`pakete_nachgezogen`, `paket_nachziehen_s`).
    """
    t0 = time.monotonic()
    d.bildschirm_aus = False
    # Ohne eigenen Balken: das Nachziehen eines Pakets dauert Zehntel-
    # sekunden, ein Balken, der je Paket auf- und zugeht, waere genau das
    # Flackern, das hier weg soll. Laeuft der Balken des Laufs, bleibt er
    # ohnehin stehen.
    n = _bildschirm_zurueck(d, mit_balken=False)
    dauer = time.monotonic() - t0
    with d.sperre:
        d.pakete_nachgezogen += 1
        d.paket_nachziehen_s += dauer
    LOG.info("Paket %d/%d nachgezogen: %d Element(e), %.2f s (Auffrischung "
             "an, Material, neu zeichnen)", meta.paket[0], meta.paket[1], n,
             dauer)
    return {"elemente": n, "s": round(dauer, 3)}


def _neu_zeichnen():
    try:
        import visualization_controller as vc
        vc.refresh()
        return True
    except Exception:                                 # noqa: BLE001
        return False


def _vor_wie_lange(zeit_epoch):
    """"vor 10 s" / "vor 5 min" / "vor 2 h" — grob, aber sofort lesbar.

    Rueckmeldung 2026-08-06: "eine Zeitangabe, wo steht: wurde vor 10 s, 30 s, 1 min,
    5 min, 1 h etc. geschrieben, damit man auch daraus schliessen kann, ob es
    ein neuer Hinweis ist oder nicht." Eine Uhrzeit beantwortet das nicht —
    man muesste sie erst mit der aktuellen vergleichen.
    """
    d_s = max(0, int(time.time() - (zeit_epoch or 0)))
    if d_s < 60:
        return "vor %d s" % d_s
    if d_s < 3600:
        return "vor %d min" % (d_s // 60)
    if d_s < 86400:
        return "vor %d h" % (d_s // 3600)
    return "vor %d d" % (d_s // 86400)


def _fortschritt_an():
    """Cadworks EIGENEN Fortschrittsbalken einblenden.

    Wunsch 2026-08-06: "cadwork selber blendet ein pop up ein mit
    einem ladebalken wenn das passiert, vlt koennen wir auch sowas
    einbauen." Cadwork kann es (`uc.show_progress_bar`), am 2026-08-06
    fehlerfrei angesteuert.

    Bewusst NUR fuer Arbeit, die die Bridge selbst macht und in Schritten
    kennt (das Nachziehen). Innerhalb eines Zeichenauftrags laeuft fremder
    Code am Stueck — dort waere ein Balken zwar sichtbar, aber er stuende
    still und wuerde mehr vortaeuschen als zeigen.
    """
    try:
        import utility_controller as uc
        uc.show_progress_bar()
        return True
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Fortschrittsbalken nicht verfuegbar: %s", exc)
        return False


def _fortschritt(prozent):
    try:
        import utility_controller as uc
        uc.update_progress_bar(int(max(0, min(100, prozent))))
    except Exception:                                 # noqa: BLE001
        pass


def _fortschritt_aus(an):
    if not an:
        return
    try:
        import utility_controller as uc
        uc.hide_progress_bar()
    except Exception as exc:                          # noqa: BLE001
        # Ein stehengebliebener Balken waere schlimmer als keiner.
        LOG.error("Fortschrittsbalken liess sich nicht ausblenden: %s", exc)


_LAUF_POPUP = {"w": None, "balken": None, "titel": None, "zeile": None,
               "knopf": None}


def _popup_bauen(d):
    """Eigenes Fortschritts-Fenster ueber Cadwork.

    Rueckmeldung 2026-08-06: "ich meinte eigentlich ein eigenes pop up fenster ueber
    dem screen mit ladeanzeige, so machts cadwork auch bei elementgenerator
    oder kollisionskontrolle."

    Cadworks eigene Fortschrittsfenster sind intern — cwapi3d hat KEINE
    Dialog-API dafuer (am 2026-08-06 nachgesehen: nur Datei-/Pfaddialoge und
    `print_message`). Also ein eigenes Qt-Fenster; PyQt6 ist im Prozess
    ohnehin geladen.

    GRENZE, die man kennen muss: gezeichnet wird es nur, wenn Cadworks
    Ereignisschleife dran ist — also ZWISCHEN den Auftraegen. Waehrend eines
    Auftrags steht es still. Das ist kein Fehler des Fensters, sondern die
    Folge davon, dass cwapi3d nicht thread-safe ist und ein Auftrag am
    Stueck im Hauptthread laeuft.
    """
    Qt = _qt_namen("QtCore", "Qt")
    (QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton,
     QVBoxLayout, QWidget) = _qt_namen(
        "QtWidgets", "QApplication", "QHBoxLayout", "QLabel", "QProgressBar",
        "QPushButton", "QVBoxLayout", "QWidget")
    if QApplication.instance() is None:
        return None
    # KIND von Cadworks Hauptfenster, und KEIN WindowStaysOnTopHint.
    # Vorher war es elternlos und immer obenauf — Rueckmeldung 2026-08-06: "das
    # popup ist auch in der Mitte vom Bildschirm aufgeploppt, wenn cadwork
    # im Hintergrund war, also als ich im Browser war. Das sollte
    # eigentlich nicht so sein." Ein Tool-Fenster MIT Eltern liegt ueber
    # seinem Elternfenster, aber nicht ueber fremden Anwendungen.
    haupt, _weg = _cadwork_hauptfenster()
    w = QWidget(haupt, Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint)
    w.setObjectName("Open MCP CADLaufPopup")
    w.setStyleSheet(
        "#Open MCP CADLaufPopup { background:#ffffff; border:1px solid #b0b0b0; }"
        "QLabel { color:#222; }")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 14, 16, 12)
    lay.setSpacing(8)
    titel = QLabel("Open MCP CAD zeichnet …")
    titel.setStyleSheet("font-weight:700; font-size:13px;")
    lay.addWidget(titel)
    balken = QProgressBar()
    balken.setRange(0, 100)
    balken.setMinimumWidth(320)
    lay.addWidget(balken)
    zeile = QLabel("—")
    zeile.setStyleSheet("color:#666; font-size:11px;")
    lay.addWidget(zeile)
    reihe = QHBoxLayout()
    reihe.addStretch(1)
    knopf = QPushButton("Nach diesem Schritt anhalten")
    knopf.setToolTip(
        "Verwirft die noch WARTENDEN Auftraege. Der gerade laufende Schritt "
        "wird fertig gerechnet — ihn abzubrechen ginge nicht, ohne das "
        "Modell in einem halben Zustand zu hinterlassen.")
    knopf.clicked.connect(
        lambda: _warteschlange_verwerfen(d, "Vom Benutzer angehalten"))
    reihe.addWidget(knopf)
    lay.addLayout(reihe)
    _LAUF_POPUP.update(w=w, balken=balken, titel=titel, zeile=zeile,
                       knopf=knopf)
    return w


def _restzeit(d, fertig, gesamt):
    """Grobe Restzeit aus dem bisherigen Tempo DIESES Laufs.

    Bewusst aus dem laufenden Tempo statt aus `ms_je_teil`: der gelernte
    Wert ist ein Mittel ueber frueher, hier zaehlt, wie schnell es GERADE
    geht. Ohne angemeldete Gesamtzahl gibt es keine Restzeit — dann wird
    nichts geschaetzt statt etwas erfunden.
    """
    if not gesamt or fertig <= 0 or not d.lauf_start_mono:
        return None
    verbraucht = time.monotonic() - d.lauf_start_mono
    if verbraucht <= 0:
        return None
    return max(0.0, verbraucht / fertig * (gesamt - fertig))


def _popup_setzen(d, prozent, fertig, gesamt):
    """Fortschritts-Fenster zeigen und nachfuehren.

    Liefert True, wenn es steht — dann braucht es Cadworks Balken unten
    rechts nicht mehr (2026-08-06: "dann reicht das pop up in dem
    moment"). Faellt das Fenster aus, uebernimmt der Balken wieder.
    """
    try:
        w = _LAUF_POPUP.get("w")
        if w is None:
            w = _popup_bauen(d)
            if w is None:
                return False
            haupt, _weg = _cadwork_hauptfenster()
            if haupt is not None:
                mitte = haupt.geometry().center()
                w.adjustSize()
                w.move(mitte.x() - w.width() // 2,
                       mitte.y() - w.height() // 2)
        _LAUF_POPUP["balken"].setRange(0, 100)
        _LAUF_POPUP["balken"].setValue(int(max(0, min(100, prozent))))
        rest = _restzeit(d, fertig, gesamt)
        if gesamt:
            text = "%d von %d Bauteilen" % (fertig, gesamt)
            if rest is not None:
                text += ("   ·   noch etwa %s"
                         % ("%.0f s" % rest if rest < 90
                            else "%.0f min" % (rest / 60.0)))
        else:
            text = ("%d Bauteile — ohne angemeldete Gesamtzahl gibt es keine "
                    "Restzeit" % fertig)
        _LAUF_POPUP["zeile"].setText(text)
        if not w.isVisible():
            w.show()
        # Nur nach vorn holen, wenn Cadwork ueberhaupt im Vordergrund ist —
        # sonst reisst der Fortschritt eines Hintergrundlaufs die
        # Aufmerksamkeit aus einer anderen Anwendung.
        eltern = w.parent()
        if eltern is None or eltern.isActiveWindow():
            w.raise_()
        return True
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Fortschritts-Fenster nicht moeglich: %s", exc)
        return False


def _popup_weg():
    try:
        w = _LAUF_POPUP.get("w")
        if w is not None:
            w.hide()
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Fortschritts-Fenster nicht schliessbar: %s", exc)


#: Dieser Kern kennt den Haken `cfg.lauf_anzeige` (K12). Ein Dashboard liest
#: es per getattr: fehlt es (Kern < 2.19), zeigt es KEINE eigene Anzeige —
#: sonst stuenden zwei Fenster fuer denselben Lauf da.
LAUF_ANZEIGE_HAKEN = True


def _lauf_info(d, meta=None, prozent=None, neu=False):
    """Was die Arbeitsanzeige des Dashboards ueber den Lauf wissen muss —
    nur Werte, keine Qt-Objekte, kein cwapi3d."""
    with d.sperre:
        fertig, gesamt = d.lauf_gezeichnet, d.lauf_gesamt
    info = {"lauf_gezeichnet": fertig, "lauf_gesamt": gesamt,
            "prozent": prozent, "restzeit_s": _restzeit(d, fertig, gesamt),
            "popup": bool(d.modus()["popup"]),
            "lauf_s": (time.monotonic() - d.lauf_start_mono)
            if d.lauf_start_mono else 0.0, "neu_lauf": bool(neu)}
    if meta is not None:
        info.update(methode=meta.methode, zugriff=meta.zugriff,
                    beschreibung=meta.beschreibung, client=meta.client,
                    paket=list(meta.paket) if meta.paket else None)
    return info


def _lauf_anzeige_rufen(d, art, meta=None, prozent=None, neu=False):
    """Den Haken `cfg.lauf_anzeige` rufen (K12) -> True, wenn er die Anzeige
    uebernommen hat. Wirft er, steht es im Log, und fuer DIESEN Lauf zeigt
    der Kern wieder sein eigenes Fenster (`lauf_haken_kaputt`, am Ende des
    Laufs zurueckgesetzt). Ohne Haken: False, nichts geschieht."""
    haken = getattr(getattr(d, "cfg", None), "lauf_anzeige", None)
    if not callable(haken) or getattr(d, "lauf_haken_kaputt", False):
        return False
    try:
        haken(art, _lauf_info(d, meta, prozent, neu))
        return True
    except Exception as exc:                          # noqa: BLE001
        d.lauf_haken_kaputt = True
        LOG.error("Arbeitsanzeige des Dashboards warf (%s): %s — fuer diesen "
                  "Lauf das eigene Fenster", art, exc)
        return False


def _auftrag_anzeige_rufen(d, meta):
    """2.19.1: den Haken `cfg.lauf_anzeige` mit `("auftrag", info)` rufen —
    fuer einen Auftrag AUSSERHALB eines Laufs (dort zeigt das Dashboard
    keine Arbeitsanzeige, nur der Zustand im Kopf wechselt). Wirft der
    Haken, steht das EINMAL je Dienst im Log, der Auftrag laeuft, und der
    Lauf-Rueckfall (`lauf_haken_kaputt`) bleibt unberuehrt. -> gerufen?"""
    haken = getattr(getattr(d, "cfg", None), "lauf_anzeige", None)
    if not callable(haken):
        return False
    try:
        haken("auftrag", _lauf_info(d, meta))
        return True
    except Exception as exc:                          # noqa: BLE001
        if not getattr(d, "auftrag_haken_gemeldet", False):
            d.auftrag_haken_gemeldet = True
            LOG.error("Zustand des Dashboards warf (auftrag): %s", exc)
        return False


def _lauf_balken_zeigen(d, art="fortschritt", meta=None, neu=False):
    """Setzt den Ladebalken fuer den laufenden Zeichenlauf.

    ECHTER Fortschritt nur, wenn der Auftraggeber sein Ziel angemeldet hat
    (`lauf_gesamt`) und seine Bauteile zaehlt (`bauteile`). Sonst pulsiert
    der Balken bewusst: er zeigt dann "es arbeitet", ohne einen Stand
    vorzutaeuschen, den niemand kennt. Die Bridge bekommt fertigen Code und
    kann ihm nicht ansehen, wie viel er noch zeichnen wird.
    """
    with d.sperre:
        gesamt = d.lauf_gesamt
        fertig = d.lauf_gezeichnet
        d.lauf_takte += 1
        takte = d.lauf_takte
    if gesamt and gesamt > 0:
        prozent = min(99, 100 * fertig / gesamt)
    else:
        prozent = 5 + (takte * 13) % 90
    # K12: zuerst der Haken des Dashboards (er zeigt die Arbeitsanzeige nur
    # in den Stufen mit Fenster; `popup` steht in der Info). Er wird auch in
    # 'cowork'/'langsam' gerufen — dort bleibt der Balken unten rechts.
    haken = _lauf_anzeige_rufen(d, art, meta, prozent, neu)
    # In den Stufen zum Mitarbeiten und Zuschauen ('cowork', 'slow') bleibt
    # es bei Cadworks Balken unten rechts — ein Fenster mitten im Bild waere
    # dort im Weg. Sonst das eigene Fenster (oder, mit Haken, die Anzeige des
    # Dashboards); steht es, bleibt der Balken aus, zwei Anzeigen fuer
    # dieselbe Sache sind eine zu viel.
    if d.modus()["popup"] and (haken
                               or _popup_setzen(d, prozent, fertig, gesamt)):
        if d.cadwork_balken:
            _fortschritt_aus(True)
            d.cadwork_balken = False
        return
    if not d.cadwork_balken:
        d.cadwork_balken = _fortschritt_an()
    _fortschritt(prozent)


def _lauf_balken_weg(d):
    """Balken weg — der Lauf ist durch, jetzt darf man das Ergebnis sehen."""
    # Der Zaehler wird IMMER zurueckgesetzt, auch wenn nie ein Balken kam:
    # sonst gilt der naechste Lauf faelschlich als Fortsetzung und blendet
    # den Balken schon beim ersten Auftrag ein.
    with d.sperre:
        d.lauf_auftraege = 0
        d.lauf_start_mono = 0.0
    # Das Fenster IMMER schliessen, auch wenn nie ein Balken lief — ein
    # stehengebliebenes Fortschrittsfenster ueber Cadwork waere das
    # Aergerlichste an der ganzen Anzeige.
    _popup_weg()
    if not d.lauf_balken:
        d.lauf_haken_kaputt = False
        return
    # K12: der Haken erfaehrt das Ende (die Anzeige sagt "Fertig").
    _lauf_anzeige_rufen(d, "ende", None, 100)
    d.lauf_haken_kaputt = False
    if d.cadwork_balken:
        _fortschritt(100)
        _fortschritt_aus(True)
    with d.sperre:
        d.cadwork_balken = False
        d.lauf_balken = False
        d.lauf_gezeichnet = 0
        d.lauf_gesamt = None
        d.lauf_auftraege = 0


def _undo_momentaufnahme():
    """Alle Element-IDs vor einem Auftrag — oder None, wenn nicht lesbar.

    Kostet gemessen am 2026-08-06 auf einem Modell mit 15 300 Elementen
    0,9 ms (fuenf Messungen: 3,4 / 1,45 / 0,88 / 0,79 / 0,86 ms; der erste
    Wert ist Anlauf). Zweimal je Auftrag ist damit neben Zeichenlaeufen von
    Sekunden nicht messbar.
    """
    try:
        import element_controller as ec
        return set(ec.get_all_identifiable_element_ids())
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Undo-Anmeldung: Momentaufnahme nicht moeglich: %s", exc)
        return None


def _neue_elemente(vorher):
    """Welche Elemente sind seit der Momentaufnahme dazugekommen?

    EINE Messung, ZWEI Abnehmer: der Undo-Stack (`_undo_anmelden`) und das
    Nachziehen der Darstellung (`_dunkle_elemente_nachziehen`). Beide brauchen
    genau dieselbe Liste — die im Auftrag neu entstandenen Elemente.
    """
    if vorher is None:
        return []
    try:
        import element_controller as ec
        return [e for e in ec.get_all_identifiable_element_ids()
                if e not in vorher]
    except Exception as exc:                          # noqa: BLE001
        LOG.info("Neue Elemente nicht ermittelbar: %s", exc)
        return []


def _undo_anmelden(neu):
    """Meldet die neu entstandenen Elemente in Cadworks Undo-Stack an.

    WARUM UEBERHAUPT — gemessen am 2026-08-06 in einem Wegwerf-Dokument,
    weil der Knopf laut Rueckmeldung (2026-08-05) noch nie
    funktioniert hat:
      * OHNE Anmeldung blieb die Elementzahl nach `ec.make_undo()`
        unveraendert (563 -> 563), die neuen Elemente standen noch.
      * MIT Anmeldung verschwanden genau die neuen (563 -> 560), in EINEM
        Schritt, und der Bestand blieb unangetastet. Ein zweites
        `make_undo()` blieb bei 560 — es frisst sich nicht weiter.
    `make_undo()` nimmt also nur zurueck, was in Cadworks eigenem Stack
    steht; von einem Plugin erzeugte Elemente stehen dort nicht von selbst.

    WARUM DIE DIFFERENZ statt der IDs des Zeichners: `subtract_elements_*`
    ersetzt Koerper. Im selben Test kamen drei erzeugte Balken als
    930021/930031/930033 zurueck — nicht zusammenhaengend. Ein Zeichner, der
    seine eigenen create-Rueckgaben anmeldet, verfehlt genau die
    Split-Koerper, die schon einmal ohne Gruppe und Material liegenblieben.
    Die Momentaufnahme-Differenz fasst sie mit.

    GRENZE, bewusst: nur NEUE Elemente. Wer bestehende bloss veraendert
    (Material, Verschieben), muss sich weiterhin selbst anmelden
    (`ec.add_modified_elements_to_undo`) — ein Vergleich von IDs kann
    Aenderungen an unveraenderter ID nicht sehen.
    """
    if not neu:
        return 0
    try:
        import element_controller as ec
        ec.add_created_elements_to_undo(neu)
        return len(neu)
    except Exception as exc:                          # noqa: BLE001
        # Nie den Auftrag mitreissen: ein nicht angemeldetes Undo ist
        # aergerlich, ein abgebrochener Zeichenlauf waere schlimmer.
        LOG.info("Undo-Anmeldung fehlgeschlagen: %s", exc)
        return 0


def _dunkle_elemente_nachziehen(d, mit_balken=True):
    """Baut die Darstellung der Elemente neu auf, die im Dunkeln entstanden.

    DER BEFUND (Vergleichsblatt 2026-08-06, am Bild bestaetigt,
    Geometrie vorher am Modell gemessen — alle Zellen identisch):

      Zelle              repariert mit                  Bild
      1_kontrolle        nichts                         KAPUTT  (Kontrolle)
      2_refresh          vc.refresh()                   kaputt
      3_aktiv_zyklus     set_active/set_inactive        kaputt
      4_material_neu     ac.set_element_material        GUT

    Ein erneutes Setzen des Materials holt Material UND Ausklinkung zurueck.
    Cadwork baut die Darstellung eines Elements offenbar erst dann neu auf,
    wenn das Element bei EINGESCHALTETER Auffrischung angefasst wird — wer
    im Dunkeln entsteht, bleibt sonst unsichtbar korrekt.

    Das Material wird auf seinen EIGENEN Wert zurueckgesetzt, fachlich also
    ein Nulldurchgang. Gemessen: 0,0067 ms je Element zum Lesen des Namens
    (3000 Elemente in 20 ms), danach EIN Sammel-Schreiben je Material — im
    echten Modell waren es fuenf. `set_element_material` legt dabei keinen
    eigenen Undo-Eintrag an (geprueft: nach einem reinen Material-Auftrag
    ging ein Undo direkt auf den Stand davor zurueck), der Knopf
    "Letzten Auftrag rueckgaengig" bleibt also unberuehrt.
    """
    with d.sperre:
        ids = list(dict.fromkeys(d.dunkel_entstanden))
        d.dunkel_entstanden = []
    if not ids:
        return 0
    begonnen = time.monotonic()
    d.nachzieh_laeuft = True
    # Laeuft schon eine Anzeige fuer den ganzen Lauf, bleibt die stehen —
    # zwei ineinander waeren nur Flackern. Abgeraeumt wird sie danach, in
    # _lauf_balken_weg.
    balken = (False if (d.lauf_balken or not mit_balken)
              else _fortschritt_an())
    try:
        import attribute_controller as ac
        import element_controller as ec
        import material_controller as mc
        vorhanden = set(ec.get_all_identifiable_element_ids())
        je_material = {}
        for eid in ids:
            if eid not in vorhanden:
                continue          # zwischendurch geloescht (z.B. Cutter)
            je_material.setdefault(ac.get_element_material_name(eid),
                                   []).append(eid)
        gezogen = 0
        for nr, (name, gruppe) in enumerate(je_material.items(), 1):
            # Nur den EIGENEN Balken fuehren. Gehoert die Anzeige dem Lauf,
            # sprang sie hier auf 100 und beim naechsten Auftrag zurueck —
            # paketweise waere das je Paket einmal (2.18).
            if balken:
                _fortschritt(100 * nr / max(1, len(je_material)))
            if not name:
                continue          # ohne Material gibt es nichts zu setzen
            try:
                mid = mc.get_material_id(name)
            except Exception as exc:                  # noqa: BLE001
                LOG.info("Material %r nicht aufloesbar: %s", name, exc)
                continue
            ac.set_element_material(gruppe, mid)
            gezogen += len(gruppe)
        if gezogen:
            dauer = time.monotonic() - begonnen
            with d.sperre:
                d.nachgezogen_gesamt += gezogen
            # Die Dauer gehoert ins Log: das Nachziehen laeuft im
            # Cadwork-Hauptthread, ist also fuer den Benutzer eine Pause.
            LOG.info("Darstellung nachgezogen: %d Element(e), %d Material(ien), "
                     "%.2f s", gezogen, len(je_material), dauer)
        return gezogen
    except Exception as exc:                          # noqa: BLE001
        # Schlaegt das Nachziehen fehl, bleibt das Bild veraltet — aergerlich,
        # aber die Geometrie stimmt. Auf keinen Fall den Steckplatz mitnehmen.
        LOG.info("Darstellung nachziehen fehlgeschlagen: %s", exc)
        return 0
    finally:
        # VORHANG AUF — ZULETZT. Erst stand er vor dem Nachziehen, und der Nutzer
        # sah am 2026-08-06 "kurz bevor das material geaendert wurde noch die
        # variante ohne material": `vc.set_visible` loest selbst ein
        # Neuzeichnen aus, und das kam damit VOR dem Material. Jetzt bekommen
        # die Bauteile ihr Material, solange sie unsichtbar sind — und das
        # Aufdecken ist der letzte Schritt, es gibt keinen Zwischenzustand
        # mehr zu sehen.
        #
        # Im `finally`, damit der Vorhang auch dann aufgeht, wenn das
        # Nachziehen scheitert. Unsichtbare Bauteile im Modell waeren das
        # Schlimmste, was diese Funktion anrichten koennte.
        if d.vorhang_aktiv:
            try:
                import visualization_controller as vc
                vc.set_visible(ids)
            except Exception as exc:                  # noqa: BLE001
                LOG.error("Vorhang liess sich nicht oeffnen (%d Bauteile "
                          "bleiben unsichtbar): %s — in Cadwork hilft "
                          "'Alle Elemente zeigen'.", len(ids), exc)
            d.vorhang_aktiv = False
        d.nachzieh_laeuft = False
        _fortschritt_aus(balken)


def _bereit_melden(d):
    """Einmalige Anlaufarbeit im Cadwork-Hauptthread."""
    d.dokument_auffrischen(mit_elementen=True)
    d.zustand_setzen("paused" if d.pausiert else "ready")
    d.letzte_dok_pruefung = time.monotonic()


def _tick(d, warten):
    """EIN Durchlauf der Hauptthread-Arbeit. Laeuft immer im Hauptthread.

    `warten` ist die Zeit, die auf einen Auftrag gewartet werden darf:
      * POLL_INTERVAL_SECONDS beim klassischen Antrieb (`serve` haelt den
        Hauptthread und darf blockieren)
      * 0 beim Qt-Timer-Antrieb — dort gehoert der Hauptthread Cadwork, und
        wir duerfen ihn keine Millisekunde laenger als noetig belegen.

    Genau diese Trennung macht den Qt-Antrieb ueberhaupt moeglich: die
    Arbeit ist dieselbe, nur wer sie antreibt, unterscheidet sich.
    """
    cfg = d.cfg
    d.herzschlag_mono = time.monotonic()
    try:
        if warten:
            job = d.job_queue.get(timeout=warten)
        else:
            job = d.job_queue.get_nowait()
    except queue.Empty:
        # --- Leerlauf ---
        ruhe = (d.job_queue.empty()
                and time.monotonic() - d.letzter_auftrag_mono > SCHNELL_RUHE_S)
        if d.bildschirm_aus and ruhe:
            # Ruhe eingekehrt: Bildschirm zurueckgeben.
            d.bildschirm_aus = False
            _bildschirm_an(d)
        elif (d.lauf_balken or d.lauf_start_mono) and ruhe:
            # In 'langsam' wird die Auffrischung nie abgeschaltet, also
            # laeuft _bildschirm_an dort nie — und ohne diesen Zweig bliebe
            # der Fortschrittsbalken nach dem Lauf einfach stehen.
            # Ebenso nach einem paketweisen Paketlauf: sein letztes Paket
            # hat die Auffrischung schon selbst wieder eingeschaltet. Auch
            # OHNE Balken gehoert der Lauf hier beendet (`lauf_start_mono`),
            # sonst gilt der naechste Auftrag — Minuten spaeter — als
            # Fortsetzung, die schon "lange laeuft", und laesst den Balken
            # fuer einen Einzelauftrag aufblitzen.
            _lauf_balken_weg(d)
        if d.refresh_nachholen:
            # Jetzt liegt eine Runde von Cadworks Ereignisschleife hinter
            # uns — erst dieses Neuzeichnen greift zuverlaessig.
            d.refresh_nachholen -= 1
            _neu_zeichnen()
        with d.sperre:
            if d.beenden_nach_auftrag:
                LOG.info("Leerlauf + 'nach Auftrag beenden' -> Ende")
                d.beenden = True
                return
        if cfg.dok_auffrischen_s and (
                time.monotonic() - d.letzte_dok_pruefung > cfg.dok_auffrischen_s):
            d.letzte_dok_pruefung = time.monotonic()
            d.dokument_auffrischen(mit_elementen=False)
            d.aktive_auffrischen()
        if cfg.ui_pumpe:
            n = _pumpe(d, cfg.ui_pumpe_max)
            if n >= cfg.ui_pumpe_max and not d._ui_pumpe_warnung:
                d._ui_pumpe_warnung = True
                LOG.error(
                    "UI-Pumpe hat die Obergrenze von %d Messages erreicht — "
                    "das ist genau das Muster, das die Bridge frueher "
                    "haengen liess.", cfg.ui_pumpe_max)
        return

    if job.verworfen:
        return
    _auftrag_ausfuehren(d, job)

    with d.sperre:
        ende = d.beenden_nach_auftrag
    if ende:
        # Regel 4: erst die Antwort raus, dann beenden.
        job.gesendet.wait(timeout=ANTWORT_WARTEN_S)
        _warteschlange_verwerfen(d, "Bridge beendet sich nach dem Auftrag")
        LOG.info("Auftrag fertig + 'nach Auftrag beenden' -> Ende")
        d.beenden = True


# --- Cadwork arbeitet selbst: Auftraege zurueckhalten ----------------------
#
# DER BEFUND (2026-09-25, Log C 20:34:54/55, Windows-Ereignis APPCRASH um
# 20:35:09 in SpaACIS.dll/CwCommon.dll, c0000005): waehrend Cadwork ueber
# Extra -> Viewer-Modus rechnete (modaler Fortschrittsdialog), hat der Takt
# zwei Leseauftraege ausgefuehrt; 14 s spaeter stuerzte Cadwork ab.
# Dieselbe Datei lief ohne Auftraege zweimal sauber durch.
#
# Der Mechanismus, in PyQt6 nachgemessen: ein QTimer feuert auch in fremden
# Ereignisschleifen — in `QDialog.exec()` UND in jedem `processEvents()`,
# mit dem eine lange Rechnung ihren Fortschrittsdialog am Leben haelt. Der
# Takt ruft cwapi3d dann MITTEN in Cadworks eigener Arbeit auf. Genau das
# verbietet Regel 9.
#
# Deshalb fragt jeder Qt-Takt zuerst, ob Cadwork gerade selbst arbeitet,
# und laesst dann ALLES liegen, was cwapi3d anfasst: Auftraege UND die
# Leerlaufarbeit (Dokumentname, Bildschirm wieder an, Nachziehen). Die
# Sonden fassen cwapi3d selbst nie an und lesen nur:
#
#   fenster   Cadworks Hauptfenster ist gesperrt. Gemessen 2026-09-25 unter
#             Windows (PyQt6 6.11): ein modaler QDialog, ein
#             applikationsmodaler QProgressDialog UND eine native
#             MessageBoxW sperren das Hauptfenster alle drei.
#   modal     Qt kennt einen modalen Dialog oder ein modales Fenster. Das
#             greift auch in einer processEvents-Rechnung — dort bleibt die
#             Schleifenebene gleich (gemessen: 0 vorher, 0 waehrenddessen).
#   popup     ein Menue oder Popup ist offen.
#   schleife  der Takt laeuft in einer verschachtelten Ereignisschleife,
#             tiefer als die flachste, in der er je lief.
#
# Dazu der WIEDEREINTRITT: feuert der Takt, waehrend ein Takt noch laeuft
# (ein Auftrag verteilt Ereignisse, etwa ueber eine Cadwork-Rueckfrage),
# tut der innere nichts. Ohne das holte er sich den naechsten Auftrag und
# fuehrte ihn im cwapi3d-Aufruf des ersten aus.
#
# Steuermethoden (status, ping, pause, shutdown, …) beantworten die
# Worker-Threads — sie laufen waehrenddessen ungestoert weiter.

#: Ab dieser Luecke zwischen zwei Qt-Takten steht eine Zeile im Log: so
#: lange hatte Cadwork den Hauptthread. Nur Messung, kein Zurueckhalten —
#: im Hintergrund drosselt Windows womoeglich Timer, und eine Sperre, die
#: daran haengt, haette die Bruecke dann ganz angehalten. Das Log soll im
#: echten Cadwork zeigen, welche Sonde waehrend einer Rechnung anschlaegt.
TAKT_STAU_S = 1.0


def _fenstername(w):
    """Klasse und Titel eines Fensters — fuer Status und Log."""
    try:
        titel = w.windowTitle() if hasattr(w, "windowTitle") else w.title()
    except Exception:                                  # noqa: BLE001
        titel = ""
    return "%s%s" % (type(w).__name__, (" '%s'" % titel) if titel else "")


def _qt_sonden():
    """Die Qt-Sonden `modal`, `popup`, `schleife`. Braucht PyQt6 oder PyQt5."""
    QThread = _qt_namen("QtCore", "QThread")
    QGuiApplication = _qt_namen("QtGui", "QGuiApplication")
    QApplication = _qt_namen("QtWidgets", "QApplication")

    flachste = {"ebene": None}

    def modal():
        w = QApplication.activeModalWidget()
        if w is not None:
            return "modaler Dialog offen: %s" % _fenstername(w)
        f = QGuiApplication.modalWindow()
        if f is not None:
            return "modales Fenster offen: %s" % _fenstername(f)
        return ""

    def popup():
        w = QApplication.activePopupWidget()
        if w is not None:
            return "Menue oder Popup offen: %s" % _fenstername(w)
        return ""

    def schleife():
        # Die flachste Ebene wird GELERNT, nicht angenommen: in Cadwork
        # laeuft der Takt in dessen Hauptschleife, im Gate ohne `exec()` auf
        # Ebene 0. Tiefer als die flachste = eine Schleife in der Schleife.
        ebene = QThread.currentThread().loopLevel()
        if flachste["ebene"] is None or ebene < flachste["ebene"]:
            flachste["ebene"] = ebene
        if ebene > flachste["ebene"]:
            return ("verschachtelte Ereignisschleife (Ebene %d, sonst %d)"
                    % (ebene, flachste["ebene"]))
        return ""

    return [modal, popup, schleife]


def _fenster_sonde(hwnd):
    """Die Sonde `fenster` fuer ein Fenster-Handle — oder None.

    Nur lesend (`IsWindowEnabled`), kein Nachrichtenverteilen: das ist
    etwas anderes als die UI-Pumpe, die Cadwork 2026-08-04 abstuerzen
    liess. Eigene Prototypen statt `windll.user32.X.argtypes` — das waere
    ein prozessweiter Eingriff in fremden Code.
    """
    if not _IS_WINDOWS or not hwnd:
        return None
    import ctypes                                      # noqa: PLC0415
    from ctypes import wintypes                        # noqa: PLC0415
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)
    user32 = ctypes.WinDLL("user32")
    ist_fenster = proto(("IsWindow", user32))
    ist_frei = proto(("IsWindowEnabled", user32))

    def fenster():
        if not ist_fenster(hwnd):
            return ""          # Fenster weg: dazu kann diese Sonde nichts sagen
        if ist_frei(hwnd):
            return ""
        return "Cadwork-Hauptfenster gesperrt (modaler Dialog)"

    return fenster


def _cadwork_wurzelfenster():
    """Handle von Cadworks Hauptfenster. EIN cwapi3d-Aufruf, beim Start.

    `get_3d_hwnd` liefert das 3D-Fenster; gesperrt wird von einem modalen
    Dialog aber das Hauptfenster, also dessen Wurzel (`GA_ROOT`).
    """
    try:
        import utility_controller as uc
        hwnd = int(uc.get_3d_hwnd())
    except Exception as exc:                           # noqa: BLE001
        LOG.info("get_3d_hwnd() nicht verfuegbar (%s) — ohne Fenster-Sonde",
                 exc)
        return 0
    if not hwnd or not _IS_WINDOWS:
        return hwnd
    try:
        import ctypes                                  # noqa: PLC0415
        from ctypes import wintypes                    # noqa: PLC0415
        vorfahr = ctypes.WINFUNCTYPE(wintypes.HWND, wintypes.HWND,
                                     wintypes.UINT)(
            ("GetAncestor", ctypes.WinDLL("user32")))
        return int(vorfahr(hwnd, 2) or 0) or hwnd      # 2 = GA_ROOT
    except Exception as exc:                           # noqa: BLE001
        LOG.info("GetAncestor fehlgeschlagen (%s) — nehme das 3D-Fenster",
                 exc)
        return hwnd


def _cadwork_beschaeftigt(sonden):
    """Der erste Grund, den eine Sonde meldet — oder ''."""
    for sonde in sonden:
        try:
            grund = sonde()
        except Exception:                              # noqa: BLE001
            # Eine Sonde, die selbst scheitert, weiss nichts — sie darf
            # die Bruecke nicht anhalten.
            grund = ""
        if grund:
            return grund
    return ""


def _zurueckhalten(d, grund, jetzt):
    """Cadwork arbeitet selbst: kein cwapi3d, nur Herzschlag und Status."""
    # Der Hauptthread dreht ja — er gehoert nur gerade Cadwork. Ohne den
    # Herzschlag meldete der Status nach 3 s faelschlich einen Haenger.
    d.herzschlag_mono = jetzt
    with d.sperre:
        neu = d.blockiert_seit_mono is None
        if neu:
            d.blockiert_seit_mono = jetzt
        d.blockiert_grund = grund
        wartend = d.job_queue.qsize()
    if neu:
        LOG.warning("Cadwork arbeitet selbst (%s) — kein cwapi3d, %d "
                    "Auftrag/Auftraege warten", grund, wartend)


def _freigeben(d, jetzt):
    with d.sperre:
        seit = d.blockiert_seit_mono
        if seit is None:
            return
        grund = d.blockiert_grund
        d.blockiert_seit_mono = None
        d.blockiert_grund = ""
        d.zurueckhaltungen += 1
    LOG.info("Cadwork wieder frei nach %.1f s (%s) — Auftraege laufen weiter",
             jetzt - seit, grund)


def _takt(d, sonden):
    """EIN Qt-Takt: erst fragen, ob Cadwork gerade selbst arbeitet.

    Nur der Qt-Antrieb braucht das. Der klassische Antrieb haelt den
    Hauptthread selbst; dort kann Cadwork nebenher nichts rechnen.
    """
    jetzt = time.monotonic()
    faden = _prozess().faden
    if getattr(faden, "im_takt", False):
        _zurueckhalten(d, "Wiedereintritt: Cadwork verteilt Ereignisse "
                          "mitten in einem laufenden Takt", jetzt)
        return
    grund = (_cadwork_beschaeftigt(sonden)
             if getattr(d.cfg, "zurueckhalten", True) else "")
    if d.takt_ende_mono is not None and jetzt - d.takt_ende_mono >= TAKT_STAU_S:
        d.letzter_stau_s = round(jetzt - d.takt_ende_mono, 1)
        LOG.info("Qt-Takt stand %.1f s still — so lange hatte Cadwork den "
                 "Hauptthread (%s)", d.letzter_stau_s,
                 grund or "keine Sonde schlaegt an")
    if grund:
        _zurueckhalten(d, grund, jetzt)
        d.takt_ende_mono = time.monotonic()
        return
    _freigeben(d, jetzt)
    faden.im_takt = True
    try:
        _tick(d, 0)
    finally:
        faden.im_takt = False
        d.takt_ende_mono = time.monotonic()


def _main_loop(d):
    """Klassischer Antrieb: haelt den Cadwork-Hauptthread, bis Schluss ist."""
    LOG.info("Hauptthread-Loop laeuft (cwapi3d-Aufrufe nur hier)")
    _bereit_melden(d)
    while not d.beenden:
        _tick(d, POLL_INTERVAL_SECONDS)
    LOG.info("Hauptthread-Loop beendet")


# Haelt Dienst, Timer und Fenster am Leben, nachdem serve() zurueckgekehrt
# ist — ohne diese Referenz wuerde der Garbage Collector alles einsammeln.
_QT_LAEUFT = []

# Farbe je Zustand fuer den Punkt im Anzeigefenster. Wie ueberall gilt:
# Farbe ist Zugabe, der Zustand steht immer als Text daneben.
_QT_FARBE = {
    "ready": "#2e7d32", "busy_read": "#1565c0", "busy_write": "#1565c0",
    "paused": "#e65100", "stopping_after_job": "#e65100",
    "starting": "#6a6a6a", "stopped": "#9e9e9e", "error": "#c62828",
}


def _cadwork_hauptfenster():
    """Findet Cadworks QMainWindow — ueber das Fenster-Handle, nicht geraten.

    `uc.get_3d_hwnd()` liefert das Handle des 3D-Fensters. Dessen
    Top-Level-Widget ist das Cadwork-Hauptfenster. Einfach das erste
    Top-Level-Widget zu nehmen waere eine Wette: `QApplication` hatte in der
    Messung am 2026-08-04 **30** davon, darunter Dialoge und Paletten.

    Liefert (fenster, weg) — `weg` sagt, wie es gefunden wurde, damit im Log
    nachvollziehbar bleibt, worauf angedockt wurde.
    """
    QWindow = _qt_namen("QtGui", "QWindow")
    (QApplication, QMainWindow, QWidget) = _qt_namen(
        "QtWidgets", "QApplication", "QMainWindow", "QWidget")

    app = QApplication.instance()
    if app is None:
        return None, "keine QApplication"

    try:
        import utility_controller as uc
        hwnd = int(uc.get_3d_hwnd())
    except Exception as exc:                           # noqa: BLE001
        hwnd = 0
        LOG.info("get_3d_hwnd() nicht verfuegbar (%s)", exc)

    if hwnd:
        # Direkter Treffer: ein Widget mit genau diesem Handle …
        for w in app.topLevelWidgets():
            try:
                if int(w.winId()) == hwnd and isinstance(w, QMainWindow):
                    return w, "winId == get_3d_hwnd"
            except Exception:                          # noqa: BLE001
                continue
        # … sonst ueber das Fremdfenster zum zugehoerigen Widget.
        try:
            fremd = QWindow.fromWinId(hwnd)
            traeger = QWidget.find(hwnd)
            if isinstance(traeger, QMainWindow):
                return traeger, "QWidget.find(hwnd)"
            if traeger is not None:
                fenster = traeger.window()
                if isinstance(fenster, QMainWindow):
                    return fenster, "QWidget.find(hwnd).window()"
            if fremd is not None:
                fremd.deleteLater()
        except Exception as exc:                       # noqa: BLE001
            LOG.info("Handle-Zuordnung fehlgeschlagen: %s", exc)

    # Rueckfall: das einzige sichtbare QMainWindow — und nur, wenn es
    # genau EINES gibt. Bei mehreren wird nicht geraten.
    haupt = [w for w in app.topLevelWidgets()
             if isinstance(w, QMainWindow) and w.isVisible()]
    if len(haupt) == 1:
        return haupt[0], "einziges sichtbares QMainWindow"
    return None, "nicht eindeutig (%d QMainWindow sichtbar)" % len(haupt)


def _qt_fenster(d):
    """Kleines Anzeigefenster IN Cadwork — nicht modal, immer sichtbar.

    Warum es das braucht: mit dem Qt-Antrieb kehrt `serve()` sofort zurueck,
    also bleibt der Plugin-Knopf im Cadwork-Menue NICHT gedrueckt. Ohne
    dieses Fenster gaebe es in Cadwork kein einziges Zeichen dafuer, ob eine
    Verbindung an oder aus ist (2026-08-04: "das stoert mich").

    Bewusst klein gehalten: Zustand, Dokument, laufender Auftrag, und die
    drei Knoepfe, die man wirklich braucht. Die Vollansicht ueber alle vier
    Steckplaetze bleibt das eigenstaendige Fenster "Open MCP CAD Verbindungen" —
    das sieht auch die Steckplaetze in ANDEREN Cadwork-Prozessen.
    """
    Qt, QTimer = _qt_namen("QtCore", "Qt", "QTimer")
    QColor = _qt_namen("QtGui", "QColor")
    (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
     QWidget) = _qt_namen("QtWidgets", "QHBoxLayout", "QLabel", "QPushButton",
                          "QVBoxLayout", "QWidget")

    inhalt = QWidget()
    inhalt.setMinimumWidth(380)
    inhalt.setMinimumHeight(420)
    w = inhalt          # bis klar ist, ob angedockt wird
    # Wird nach dem Andocken auf das AEUSSERE Fenster gesetzt (Dock oder
    # freies Fenster). Das Einklappen muss es kennen, um wirklich zu
    # schrumpfen — sonst versteckt es nur den Inhalt.
    _fenster = {"w": None}

    aussen = QVBoxLayout(inhalt)
    aussen.setContentsMargins(12, 10, 12, 10)
    aussen.setSpacing(6)

    # Kopfzeile mit Einklapp-Taste. Ein QDockWidget kennt kein Minimieren —
    # fuer ein Seitenpanel heisst das Einklappen: alles ausser der Kopfzeile
    # verschwindet, der Zustand bleibt lesbar. Rueckmeldung 2026-08-06: "das popup
    # fenster so machen das man es minimieren kann".
    reihe_kopf = QHBoxLayout()
    kopf = QLabel(d.cfg.anzeigename)
    kopf.setStyleSheet("font-weight:700; font-size:13px;")
    reihe_kopf.addWidget(kopf, 1)
    btn_klapp = QPushButton("▾")
    btn_klapp.setFixedWidth(28)
    btn_klapp.setToolTip("Einklappen — nur Zustand und Dokument bleiben "
                         "sichtbar. Nochmal klicken klappt wieder auf.")
    reihe_kopf.addWidget(btn_klapp)
    aussen.addLayout(reihe_kopf)

    lbl_dok = QLabel("—")
    lbl_dok.setStyleSheet("color:#555;")
    aussen.addWidget(lbl_dok)

    lbl_zustand = QLabel("…")
    lbl_zustand.setStyleSheet("font-size:14px; font-weight:600;")
    aussen.addWidget(lbl_zustand)

    lbl_hinweis = QLabel("")
    lbl_hinweis.setWordWrap(True)
    lbl_hinweis.setStyleSheet("color:#8a4b00; font-size:11px;")
    lbl_hinweis.hide()
    aussen.addWidget(lbl_hinweis)

    reihe = QHBoxLayout()
    btn_pause = QPushButton("Pausieren")
    btn_nach = QPushButton("Nach Auftrag beenden")
    btn_jetzt = QPushButton("Beenden")
    for b in (btn_pause, btn_nach, btn_jetzt):
        reihe.addWidget(b)
    aussen.addLayout(reihe)

    # --- Register: Auftraege und Pruefhinweise ---------------------------
    (QAbstractItemView, QListWidget, QListWidgetItem,
     QTabWidget) = _qt_namen("QtWidgets", "QAbstractItemView", "QListWidget",
                             "QListWidgetItem", "QTabWidget")

    register = QTabWidget()
    aussen.addWidget(register, 1)

    def _in_queue(methode, params, beschreibung):
        """Legt einen Modell-Auftrag in dieselbe Warteschlange wie die KI.

        Nicht direkt cwapi3d aufrufen: waehrend ein Auftrag laeuft, waere
        das ein Wiedereintritt mitten in eine laufende Operation — genau
        die Sorte Zugriff, die uns die Message-Pumpe eingebrockt hat. Ueber
        die Queue wird es sauber zwischen zwei Auftraegen abgearbeitet.
        """
        meta = AuftragsMeta(methode, dict(params, description=beschreibung,
                                          client_label="Open MCP CAD"))
        d.job_queue.put(Job(None, methode, params, meta))

    # -- Auftraege ---------------------------------------------------------
    tab_auftraege = QWidget()
    la = QVBoxLayout(tab_auftraege)
    la.setContentsMargins(6, 6, 6, 6)
    liste_auftraege = QListWidget()
    liste_auftraege.setSelectionMode(
        QAbstractItemView.SelectionMode.NoSelection)
    la.addWidget(liste_auftraege)
    # Zwei schmale Pfeiltasten statt zweier breiter Knoepfe — der Nutzer
    # 2026-08-06: "simpel mit kleinen pfeiltasten darstellen".
    reihe_undo = QHBoxLayout()
    btn_undo = QPushButton("↶")
    btn_undo.setFixedWidth(34)
    btn_undo.setToolTip(
        "Nimmt die Elemente des LETZTEN Auftrags zurück (Cadworks eigenes "
        "make_undo).\n\n"
        "Ein Klick = ein Auftrag, nicht ein Zeichenlauf. Ein Lauf über 3360 "
        "Bauteile kommt in 17 Häppchen — der braucht 17 Klicks.\n\n"
        "Zurückgenommen wird nur, was NEU entstanden ist. Wurden bestehende "
        "Bauteile bloß geändert (Material, Verschieben), bleibt die Änderung "
        "stehen.\n\n"
        "Gemessen am 2026-08-06: ohne Anmeldung der Elemente tat der Knopf "
        "nichts (563 → 563), mit Anmeldung verschwinden genau die neuen "
        "(563 → 560), ohne den Bestand anzutasten.")
    btn_undo.clicked.connect(
        lambda: _in_queue("undo", {"schritte": 1},
                          "Rückgängig (aus Open MCP CAD)"))
    btn_redo = QPushButton("↷")
    btn_redo.setFixedWidth(34)
    btn_redo.setToolTip(
        "Holt zurück, was ein Rückgängig weggenommen hat (Cadworks eigenes "
        "make_redo).\n\n"
        "Gemessen am 2026-08-06: 1790 Elemente, drei erzeugt (1793), "
        "Rückgängig (1790), Wiederherstellen — 1793, Gruppe wieder "
        "vollständig.\n\n"
        "Wie beim Rückgängig: ein Klick = ein Schritt.")
    btn_redo.clicked.connect(
        lambda: _in_queue("redo", {"schritte": 1},
                          "Wiederherstellen (aus Open MCP CAD)"))
    reihe_undo.addWidget(btn_undo)
    reihe_undo.addWidget(btn_redo)
    lbl_undo = QLabel("letzten Auftrag rückgängig / wiederherstellen")
    lbl_undo.setStyleSheet("color:#777; font-size:11px;")
    reihe_undo.addWidget(lbl_undo, 1)
    la.addLayout(reihe_undo)

    # Drei Stufen fuer Aenderungen an BESTEHENDEN Bauteilen. Der Vorschlag
    # 2026-08-06, und die Grenze ist gemessen: das Anmelden kostet rund
    # 2,6 ms je Bauteil, 100 Sparren also 0,26 s — erst im vierstelligen
    # Bereich wird daraus Wartezeit.
    QComboBox = _qt_namen("QtWidgets", "QComboBox")
    _undo_setzen = _worker_methoden(d)["undo_aenderungen"]
    reihe_ua = QHBoxLayout()
    reihe_ua.addWidget(QLabel("Änderungen rücknehmbar:"))
    box_ua = QComboBox()
    _UA = (("bis_grenze", "bis 500 Bauteile"), ("immer", "immer"),
           ("aus", "nie (schnellste)"))
    for _s, txt in _UA:
        box_ua.addItem(txt)
    box_ua.setCurrentIndex([i for i, (s, _t) in enumerate(_UA)
                            if s == d.undo_aenderungen][0])
    box_ua.setToolTip(
        "Gilt für Änderungen an BESTEHENDEN Bauteilen (verlängern, "
        "verschieben, Material).\n\n"
        "Gemessen 2026-08-06 am Verlängern von Sparren:\n"
        "   20 Sparren   82 ms  ->  121 ms mit Undo  (+61 %)\n"
        "  100          266 ms  ->  519 ms           (+97 %)\n"
        "  300          730 ms  -> 1529 ms          (+110 %)\n\n"
        "Prozentual eine Verdopplung, in Sekunden aber ein Viertel bei 100 "
        "Bauteilen. Deshalb ist die Vorgabe grosszügig.\n\n"
        "Neu erzeugte Bauteile sind IMMER rücknehmbar — das kostet nichts "
        "und ist von dieser Einstellung nicht betroffen.")
    box_ua.currentIndexChanged.connect(
        lambda i: _undo_setzen({"stufe": _UA[i][0]}))
    reihe_ua.addWidget(box_ua, 1)
    la.addLayout(reihe_ua)
    register.addTab(tab_auftraege, "Aufträge")

    # -- Pruefhinweise -----------------------------------------------------
    tab_hinweise = QWidget()
    lh = QVBoxLayout(tab_hinweise)
    lh.setContentsMargins(6, 6, 6, 6)
    liste_hinweise = QListWidget()
    liste_hinweise.setWordWrap(True)
    lh.addWidget(liste_hinweise)

    reihe_h = QHBoxLayout()
    btn_zeigen = QPushButton("Im Modell zeigen")
    btn_zurueck = QPushButton("Ansicht zurück")
    btn_erledigt = QPushButton("Erledigt")
    btn_ungelesen = QPushButton("Ungelesen")
    btn_ungelesen.setToolTip("Wie bei E-Mail: Anklicken macht einen Hinweis "
                             "gelesen, hiermit wird er wieder ungelesen.")
    btn_loeschen = QPushButton("Löschen")
    btn_loeschen.setToolTip("Wirft den Hinweis weg — nicht nur abhaken. "
                            "Erledigte sammeln sich sonst an und verdecken "
                            "die neuen.")
    for b in (btn_zeigen, btn_zurueck, btn_erledigt, btn_ungelesen,
              btn_loeschen):
        reihe_h.addWidget(b)
    lh.addLayout(reihe_h)

    # Anzeige-Optionen. Rueckmeldung 2026-08-06: "Option, wie etwas aktiviert werden
    # soll, z.B. dass angezoomt wird oder nicht, Default auf anzoomen ein.
    # Dann ob nur aktivierte angezeigt werden sollen, das man es auch
    # wirklich sieht."
    _QCheckBox = _qt_namen("QtWidgets", "QCheckBox")
    reihe_opt = QHBoxLayout()
    chk_zoom = _QCheckBox("beim Zeigen anzoomen")
    chk_zoom.setChecked(True)
    chk_nur = _QCheckBox("nur diese Bauteile sichtbar")
    chk_nur.setToolTip("Blendet alles andere aus — sonst sieht man ein "
                       "aktiviertes Bauteil mitten im Modell nicht. "
                       "«Ansicht zurück» stellt es wieder her.")
    reihe_opt.addWidget(chk_zoom)
    reihe_opt.addWidget(chk_nur)
    reihe_opt.addStretch(1)
    lh.addLayout(reihe_opt)

    # Antwort auf einen Hinweis — landet im Briefkasten, mit Bezug auf die
    # Hinweis-Nummer. Rueckmeldung: "eine Funktion, dass man zu einem Hinweis eine
    # Notiz in den Briefkasten direkt schreiben kann".
    QLineEdit = _qt_namen("QtWidgets", "QLineEdit")
    reihe_antwort = QHBoxLayout()
    eingabe_antwort = QLineEdit()
    eingabe_antwort.setPlaceholderText("Notiz zu diesem Hinweis …")
    btn_antwort = QPushButton("In den Briefkasten")
    reihe_antwort.addWidget(eingabe_antwort, 1)
    reihe_antwort.addWidget(btn_antwort)
    lh.addLayout(reihe_antwort)
    register.addTab(tab_hinweise, "Hinweise")

    def _gewaehlter_hinweis():
        i = liste_hinweise.currentItem()
        return None if i is None else i.data(Qt.ItemDataRole.UserRole)

    def _hinweis_setzen(nr, **werte):
        with d.sperre:
            for e in d.hinweise:
                if e["nr"] == nr:
                    e.update(werte)
                    return

    def hinweis_zeigen():
        h = _gewaehlter_hinweis()
        if not h or not h.get("element_ids"):
            return
        # Anklicken macht gelesen — wie bei E-Mail.
        _hinweis_setzen(h["nr"], gelesen=True)
        _in_queue("elemente_zeigen",
                  {"element_ids": h["element_ids"],
                   "zoomen": chk_zoom.isChecked(),
                   "nur_diese": chk_nur.isChecked()},
                  "Hinweis #%s im Modell zeigen" % h.get("nr"))

    def ansicht_zurueck():
        _in_queue("sichtbarkeit_zurueck", {}, "Ansicht zurücksetzen")

    def hinweis_erledigt():
        h = _gewaehlter_hinweis()
        if h:
            _hinweis_setzen(h["nr"], status="erledigt", gelesen=True)

    def hinweis_ungelesen():
        h = _gewaehlter_hinweis()
        if h:
            _hinweis_setzen(h["nr"], gelesen=False, status="offen")

    def hinweis_loeschen():
        h = _gewaehlter_hinweis()
        if not h:
            return
        with d.sperre:
            d.hinweise[:] = [e for e in d.hinweise if e["nr"] != h["nr"]]
        LOG.info("Hinweis #%s geloescht (aus dem Fenster)", h["nr"])

    def hinweis_antworten():
        h = _gewaehlter_hinweis()
        text = eingabe_antwort.text().strip()
        if not text:
            return
        bezug = ("Zu Hinweis #%s (%s): " % (h["nr"], h["titel"])) if h else ""
        _in_queue("nachricht_senden", {"text": bezug + text},
                  "Notiz zu Hinweis in den Briefkasten")
        eingabe_antwort.clear()
        if h:
            _hinweis_setzen(h["nr"], gelesen=True)

    btn_zeigen.clicked.connect(hinweis_zeigen)
    liste_hinweise.itemDoubleClicked.connect(lambda _i: hinweis_zeigen())
    liste_hinweise.itemClicked.connect(
        lambda i: _hinweis_setzen(
            (i.data(Qt.ItemDataRole.UserRole) or {}).get("nr"), gelesen=True))
    btn_zurueck.clicked.connect(ansicht_zurueck)
    btn_erledigt.clicked.connect(hinweis_erledigt)
    btn_ungelesen.clicked.connect(hinweis_ungelesen)
    btn_loeschen.clicked.connect(hinweis_loeschen)
    btn_antwort.clicked.connect(hinweis_antworten)
    eingabe_antwort.returnPressed.connect(hinweis_antworten)

    # -- Briefkasten -------------------------------------------------------
    (QCheckBox, QPlainTextEdit) = _qt_namen(
        "QtWidgets", "QCheckBox", "QPlainTextEdit")

    tab_post = QWidget()
    lp = QVBoxLayout(tab_post)
    lp.setContentsMargins(6, 6, 6, 6)

    erklaerung = QLabel(
        "Briefkasten — kein Chat. Die Nachricht liegt hier, bis die laufende "
        "Open-MCP-CAD-Sitzung sie abholt. Ohne laufende Sitzung wird sie nicht "
        "zugestellt.")
    erklaerung.setWordWrap(True)
    erklaerung.setStyleSheet("color:#555; font-size:11px;")
    lp.addWidget(erklaerung)

    lbl_kontext = QLabel("—")  # zeigt die aktive Auswahl als Bezug
    lbl_kontext.setStyleSheet("font-size:11px; color:#1565c0;")
    lbl_kontext.setWordWrap(True)
    lp.addWidget(lbl_kontext)

    eingabe = QPlainTextEdit()
    eingabe.setPlaceholderText(
        "Anweisung an Open MCP CAD …\n\n"
        "Elemente vorher in Cadwork aktivieren — sie gehen als Bezug mit, "
        "dann geht «strecke diese Facette um 15 mm».")
    eingabe.setMinimumHeight(70)
    lp.addWidget(eingabe)

    reihe_p = QHBoxLayout()
    btn_senden = QPushButton("In den Briefkasten legen")
    reihe_p.addWidget(btn_senden)
    lp.addLayout(reihe_p)

    liste_post = QListWidget()
    liste_post.setWordWrap(True)
    lp.addWidget(liste_post, 1)
    register.addTab(tab_post, "Briefkasten")

    def nachricht_senden():
        text = eingabe.toPlainText().strip()
        if not text:
            return
        _in_queue("nachricht_senden", {"text": text},
                  "Nachricht in den Briefkasten")
        eingabe.clear()

    btn_senden.clicked.connect(nachricht_senden)

    # -- Zeichenmodus ------------------------------------------------------
    # EIN Regler, EINE Frage: "wie sehr darf das Zeichnen mich stoeren?"
    # Vorher stand hier ein einzelner Haken "Schnellzeichnen". Der Nutzer
    # 2026-08-06: der muss nie angefasst werden, "also waere eher ein
    # schiebregler angebracht", plus Entwicklermodus mit zwei getrennten
    # Reglern fuer ihn.
    btn_neu = QPushButton("Ansicht neu zeichnen")
    btn_neu.setToolTip("Zeichnet Cadworks Ansicht neu. Nützlich, wenn nach "
                       "einem Lauf mit Schnellzeichnen noch ein veraltetes "
                       "Bild steht.")
    btn_neu.clicked.connect(
        lambda: _in_queue("neu_zeichnen", {}, "Ansicht neu zeichnen"))
    reihe.addWidget(btn_neu)

    QSlider = _qt_namen("QtWidgets", "QSlider")

    # Der Regler bedient dieselbe Methode wie ein Client — eine Quelle fuer
    # Fenster und Fernsteuerung, statt zweier Wege in denselben Zustand.
    _modus_setzen = _worker_methoden(d)["zeichenmodus"]

    regler = QSlider(Qt.Orientation.Horizontal)
    regler.setMinimum(0)
    regler.setMaximum(len(ZEICHENMODI) - 1)
    regler.setTickPosition(QSlider.TickPosition.TicksBelow)
    regler.setTickInterval(1)
    regler.setPageStep(1)
    regler.setToolTip(
        "Wie sehr darf das Zeichnen dich stören?\n\n"
        "Gemessen 2026-08-06 an 300 Bauteilen mit Ausklinkung:\n"
        "  300 am Stück   27,4 ms/Teil   7,8 s blockiert\n"
        "   50er-Häppchen 33,0 ms/Teil   1,4 s\n"
        "   25er          39,9 ms/Teil   0,7 s\n"
        "   10er          59,0 ms/Teil   0,3 s\n\n"
        "Bedienbarkeit wird mit Übertragungszeit bezahlt, NICHT mit "
        "Cadwork-Arbeit — die blieb in allen Varianten gleich.")

    reihe_regler = QHBoxLayout()
    marken = []
    for i, m in enumerate(ZEICHENMODI):
        lb = QLabel(m["anzeige"])
        lb.setAlignment(Qt.AlignmentFlag.AlignLeft if i == 0 else
                        (Qt.AlignmentFlag.AlignRight
                         if i == len(ZEICHENMODI) - 1
                         else Qt.AlignmentFlag.AlignHCenter))
        marken.append(lb)
        reihe_regler.addWidget(lb, 1)

    lbl_modus = QLabel()
    lbl_modus.setWordWrap(True)
    lbl_modus.setStyleSheet("color:#555; font-size:11px;")

    def modus_anzeigen():
        """Beschriftung aus dem WIRKLICHEN Zustand, nie aus der Reglerstellung."""
        st = d.status()
        modus = st["zeichenmodus"]
        ziel = st["blockade_ziel_s"]
        hae = st["haeppchen_empfehlung"]
        for i, m in enumerate(ZEICHENMODI):
            aktiv = m["schluessel"] == modus
            marken[i].setStyleSheet(
                "color:#111; font-size:10px; font-weight:600;" if aktiv
                else "color:#999; font-size:10px;")
        # "Empfehlung", nicht "Grenze" — sie wird NICHT durchgesetzt. Eine
        # Sperre, die auf einer Schaetzung beruht, hat am 2026-08-07 das
        # Falsche durchgelassen; das Wort waere ein Versprechen ohne Deckung.
        teile = (("empfohlen: rund %d Bauteile je Auftrag" % hae) if hae
                 else "Auftragsgrösse egal")
        lbl_modus.setText(
            "%s<br><span style='color:#777;'>%s · gemessen %.0f ms je "
            "Bauteil</span>" % (d.modus()["text"], teile, st["ms_je_teil"]))

    def regler_bewegt(pos):
        _modus_setzen({"modus": ZEICHENMODI[pos]["schluessel"]})
        modus_anzeigen()

    _start = [i for i, m in enumerate(ZEICHENMODI)
              if m["schluessel"] == d.zeichenmodus]
    regler.setValue(_start[0] if _start else 0)
    regler.valueChanged.connect(regler_bewegt)

    aussen.addWidget(QLabel("<b>Zeichenmodus</b>"))
    aussen.addWidget(regler)
    aussen.addLayout(reihe_regler)
    aussen.addWidget(lbl_modus)
    modus_anzeigen()

    _STUFE = {"fehler": ("✖", "#c62828"), "warnung": ("▲", "#e65100"),
              "frage": ("?", "#1565c0"), "hinweis": ("•", "#555555")}

    def listen_auffrischen():
        """Beide Listen neu aufbauen — nur wenn sich etwas geaendert hat.

        Ein Neuaufbau bei jedem Takt wuerde die Auswahl staendig
        wegreissen; deshalb der Vergleich ueber einen einfachen Stempel.
        """
        with d.sperre:
            verlauf = [dict(v) for v in d.verlauf]
            hinweise = [dict(h) for h in d.hinweise]

        stempel_a = len(verlauf)
        if getattr(liste_auftraege, "_stempel", None) != stempel_a:
            liste_auftraege._stempel = stempel_a
            liste_auftraege.clear()
            for v in reversed(verlauf):
                zeit = time.strftime("%H:%M:%S", time.localtime(v.get("beendet") or 0))
                liste_auftraege.addItem(
                    "%s  %s  %s  (%.2f s)"
                    % (zeit, "ok " if v.get("ok") else "FEHL",
                       v.get("beschreibung") or v.get("methode"),
                       v.get("dauer_s") or 0))

        # Der Stempel muss auch das Alter enthalten, sonst friert die
        # Zeitangabe ("vor 30 s") ein, sobald sich sonst nichts aendert.
        stempel_h = (len(hinweise),
                     tuple((h["status"], h.get("gelesen"),
                            int((time.time() - h["zeit"]) / 5))
                           for h in hinweise))
        if getattr(liste_hinweise, "_stempel", None) != stempel_h:
            liste_hinweise._stempel = stempel_h
            gewaehlt = _gewaehlter_hinweis()
            liste_hinweise.clear()
            for h in reversed(hinweise):
                zeichen, farbe = _STUFE.get(h["schweregrad"], _STUFE["hinweis"])
                # Dringlichkeit als Balken: auf einen Blick lesbar, ohne
                # dass man die Stufe interpretieren muss (ausdruecklicher Wunsch).
                dring = int(h.get("dringlichkeit") or 3)
                balken = "█" * dring + "·" * (5 - dring)
                text = "%s %s  %s  %s" % (zeichen, balken, _vor_wie_lange(
                    h["zeit"]), h["titel"])
                if h.get("element_ids"):
                    text += "   [%d Element%s]" % (
                        len(h["element_ids"]),
                        "" if len(h["element_ids"]) == 1 else "e")
                if h["status"] != "offen":
                    text += "   (%s)" % h["status"]
                if h.get("text"):
                    text += "\n     %s" % h["text"]
                eintrag = QListWidgetItem(text)
                eintrag.setData(Qt.ItemDataRole.UserRole, h)
                if h["status"] != "offen":
                    eintrag.setForeground(QColor("#9e9e9e"))
                else:
                    eintrag.setForeground(QColor(farbe))
                if not h.get("gelesen") and h["status"] == "offen":
                    # Ungelesenes faellt auf — wie im Posteingang.
                    schrift = eintrag.font()
                    schrift.setBold(True)
                    eintrag.setFont(schrift)
                liste_hinweise.addItem(eintrag)
                if gewaehlt and gewaehlt.get("nr") == h["nr"]:
                    liste_hinweise.setCurrentItem(eintrag)
        offen = sum(1 for h in hinweise if h["status"] == "offen")
        register.setTabText(1, "Hinweise (%d)" % offen if offen else "Hinweise")

        # --- Briefkasten ---
        with d.sperre:
            post = [dict(n) for n in d.postfach]
            aktive_bekannt = d.postfach[-1]["kontext"]["element_ids"] if d.postfach else []
        stempel_p = (len(post), tuple(n["abgeholt"] for n in post))
        if getattr(liste_post, "_stempel", None) != stempel_p:
            liste_post._stempel = stempel_p
            liste_post.clear()
            for n in reversed(post):
                zeit = time.strftime("%H:%M", time.localtime(n["zeit"]))
                marke = "abgeholt" if n["abgeholt"] else "wartet"
                ids = n["kontext"].get("element_ids") or []
                bezug = ("  [%d Element%s]" % (len(ids), "" if len(ids) == 1
                                               else "e")) if ids else ""
                eintrag = QListWidgetItem("%s  (%s)%s\n     %s"
                                          % (zeit, marke, bezug, n["text"]))
                if n["abgeholt"]:
                    eintrag.setForeground(QColor("#9e9e9e"))
                liste_post.addItem(eintrag)
        wartend = sum(1 for n in post if not n["abgeholt"])
        register.setTabText(2, "Briefkasten (%d)" % wartend if wartend
                            else "Briefkasten")
        hat = _gewaehlter_hinweis() is not None
        btn_zeigen.setEnabled(hat and bool((_gewaehlter_hinweis() or {})
                                           .get("element_ids")))
        btn_erledigt.setEnabled(hat)

    def pause_umschalten():
        with d.sperre:
            d.pausiert = not d.pausiert
            if d.pausiert and d._zustand not in BESCHAEFTIGT:
                d._zustand = "paused"
            elif not d.pausiert and d._zustand == "paused":
                d._zustand = "ready"

    def nach_auftrag():
        with d.sperre:
            d.beenden_nach_auftrag = True
            if d._zustand not in BESCHAEFTIGT:
                d._zustand = "stopping_after_job"
        _warteschlange_verwerfen(d, "Beenden nach dem laufenden Auftrag")

    def jetzt_beenden():
        if d.zustand in BESCHAEFTIGT:
            return                      # Knopf ist dann ohnehin gesperrt
        _warteschlange_verwerfen(d, "Verbindung wurde beendet")
        d.beenden = True

    btn_pause.clicked.connect(pause_umschalten)
    btn_nach.clicked.connect(nach_auftrag)
    btn_jetzt.clicked.connect(jetzt_beenden)

    def auffrischen():
        s = d.status()
        lbl_dok.setText(s.get("dokument") or "—")
        text = s.get("zustand_text") or "?"
        auftrag = s.get("auftrag")
        if auftrag:
            was = auftrag.get("beschreibung") or auftrag.get("methode") or ""
            dauer = auftrag.get("laufzeit_s") or 0
            # "schnell" gehoert hierhin: der Dauerschalter unten bleibt aus,
            # wenn ein einzelner Auftrag das Schnellzeichnen selbst
            # mitbringt — ohne diesen Zusatz waere das unsichtbar.
            if auftrag.get("schnell"):
                text += " (schnell)"
            text = "%s: %s  (%02d:%02d)" % (text, was, int(dauer) // 60,
                                            int(dauer) % 60)
        farbe = _QT_FARBE.get(s.get("zustand"), "#c62828")
        lbl_zustand.setText("● %s" % text)
        lbl_zustand.setStyleSheet(
            "font-size:14px; font-weight:600; color:%s;" % farbe)
        if s.get("hinweis"):
            lbl_hinweis.setText(s["hinweis"])
            lbl_hinweis.show()
        else:
            lbl_hinweis.hide()
        btn_pause.setText("Fortsetzen" if s.get("pausiert") else "Pausieren")
        beschaeftigt = s.get("zustand") in BESCHAEFTIGT
        btn_jetzt.setEnabled(not beschaeftigt)
        btn_jetzt.setToolTip("Waehrend eines Auftrags nicht moeglich — "
                             "'Nach Auftrag beenden' verwenden."
                             if beschaeftigt else "")
        n_aktiv = s.get("aktive_elemente") or 0
        lbl_kontext.setText(
            "Bezug: %d Element%s aktiv — sie gehen mit der Nachricht mit."
            % (n_aktiv, "" if n_aktiv == 1 else "e") if n_aktiv else
            "Bezug: nichts aktiv. Für elementgenaue Anweisungen vorher in "
            "Cadwork auswählen.")
        listen_auffrischen()
        if d.beenden:
            anzeige.stop()
            for e in list(_QT_LAEUFT):
                f = e.get("fenster") or {}
                if f.get("inhalt") is inhalt:
                    ziel = f.get("widget")
                    try:
                        if f.get("angedockt") and ziel is not None:
                            # Dock aus Cadworks Hauptfenster nehmen, sonst
                            # bleibt eine leere Palette stehen.
                            eltern = ziel.parent()
                            if eltern is not None and hasattr(eltern,
                                                              "removeDockWidget"):
                                eltern.removeDockWidget(ziel)
                        if ziel is not None:
                            ziel.close()
                            ziel.deleteLater()
                    except Exception as exc:           # noqa: BLE001
                        LOG.info("Fenster nicht sauber entfernt: %s", exc)
                    e["fenster"] = None

    # --- Einklappen -------------------------------------------------------
    # Kopfzeile, Dokument, Zustand und Hinweis bleiben immer stehen — sonst
    # waere eingeklappt nicht mehr ablesbar, ob ueberhaupt etwas laeuft.
    _KLAPP_AB = 4

    def klappen():
        zu = btn_klapp.text() == "▾"
        for i in range(_KLAPP_AB, aussen.count()):
            eintrag = aussen.itemAt(i)
            wdg = eintrag.widget()
            if wdg is not None:
                wdg.setVisible(not zu)
                continue
            lay = eintrag.layout()
            if lay is None:
                continue
            for j in range(lay.count()):
                w2 = lay.itemAt(j).widget()
                if w2 is not None:
                    w2.setVisible(not zu)
        btn_klapp.setText("▸" if zu else "▾")
        btn_klapp.setToolTip("Wieder aufklappen." if zu else
                             "Einklappen — nur Zustand und Dokument bleiben "
                             "sichtbar.")
        # OHNE das hier bleibt das Fenster gleich gross und nur der Inhalt
        # verschwindet — genau das war am 2026-08-06 zu sehen. Ursache
        # ist die feste Mindesthoehe von 420 px: sie zwingt das Fenster in
        # seine Groesse, egal was drinsteckt.
        if zu:
            inhalt.setMinimumHeight(0)
            inhalt.setMaximumHeight(inhalt.sizeHint().height())
        else:
            inhalt.setMaximumHeight(16777215)
            inhalt.setMinimumHeight(420)
        inhalt.adjustSize()
        ziel = _fenster.get("w")
        if ziel is not None:
            ziel.adjustSize()

    btn_klapp.clicked.connect(klappen)

    anzeige = QTimer()
    anzeige.timeout.connect(auffrischen)
    anzeige.start(500)
    auffrischen()

    # --- Andocken, wenn Cadworks Hauptfenster sicher gefunden wird --------
    # Sonst ein normales Fenster: minimierbar, in der Taskleiste
    # wiederzufinden, immer ueber Cadwork (sonst waere die Anzeige weg,
    # dass die Verbindung ueberhaupt laeuft).
    haupt, weg = _cadwork_hauptfenster()
    dock = None
    if haupt is not None:
        try:
            QDockWidget = _qt_namen("QtWidgets", "QDockWidget")
            dock = QDockWidget(d.cfg.anzeigename, haupt)
            # Stabiler objectName: daran wird ein vorhandenes Dock
            # wiedererkannt, statt ein zweites danebenzustellen.
            dock.setObjectName("Open MCP CADConnectDock_%s" % d.cfg.instanz)
            dock.setWidget(inhalt)
            dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                                 | Qt.DockWidgetArea.RightDockWidgetArea)
            dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                             | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                             | QDockWidget.DockWidgetFeature.DockWidgetClosable)
            haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            dock.show()
            w = dock
            LOG.info("Angedockt an Cadworks Hauptfenster (%s)", weg)
        except Exception as exc:                       # noqa: BLE001
            LOG.error("Andocken fehlgeschlagen (%s) — freies Fenster", exc)
            dock = None
    else:
        LOG.info("Kein eindeutiges Cadwork-Hauptfenster (%s) — freies "
                 "Fenster", weg)

    if dock is None:
        w = inhalt
        w.setWindowTitle(d.cfg.anzeigename)
        w.setWindowFlags(Qt.WindowType.Window
                         | Qt.WindowType.WindowMinimizeButtonHint
                         | Qt.WindowType.WindowCloseButtonHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        w.setMinimumWidth(330)
        w.show()

    # Erst jetzt steht fest, was das aeussere Fenster ist — das Einklappen
    # braucht es, um wirklich zu schrumpfen statt nur den Inhalt zu leeren.
    _fenster["w"] = w

    return {"widget": w, "inhalt": inhalt, "timer": anzeige,
            "angedockt": dock is not None, "weg": weg}


def _qtimer_antrieb(d, aufraeumen):
    """Qt-Antrieb: haengt sich in Cadworks EIGENE Ereignisschleife ein.

    Der entscheidende Unterschied: `serve()` kehrt danach ZURUECK. Cadwork
    behaelt seinen Hauptthread und damit seine Bedienbarkeit; die Auftraege
    werden trotzdem sequentiell im Hauptthread abgearbeitet, naemlich im
    Timer-Rueckruf. Damit entfaellt die Win32-Message-Pumpe ersatzlos — die
    am 2026-08-04 einen Zugriffsfehler in Cadwork ausgeloest hat.

    Voraussetzung, am 2026-08-04 in Cadwork 2026 gemessen: PyQt6 ist dort
    bereits geladen und `QApplication.instance()` liefert Cadworks eigene
    Anwendung ("3D", 30 Fenster).
    """
    QTimer = _qt_namen("QtCore", "QTimer")
    QApplication = _qt_namen("QtWidgets", "QApplication")

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Keine QApplication im Prozess — der Qt-Antrieb "
                           "braucht Cadworks eigene Ereignisschleife.")

    timer = QTimer()
    eintrag = {"dienst": d, "timer": timer}
    d.qt_eintrag = eintrag

    # Die Sonden VOR dem ersten Takt: ohne sie liefe schon der erste
    # Auftrag ungeschuetzt. Die Fenster-Sonde braucht einen cwapi3d-Aufruf
    # (das Handle) — der geschieht hier, im Plugin-Klick, im Hauptthread.
    try:
        sonden = _qt_sonden()
    except Exception as exc:                           # noqa: BLE001
        LOG.error("Qt-Sonden nicht verfuegbar (%s) — Auftraege laufen "
                  "OHNE Schutz vor Cadworks eigenen Dialogen", exc)
        sonden = []
    fenster_sonde = _fenster_sonde(_cadwork_wurzelfenster())
    if fenster_sonde is not None:
        sonden.insert(0, fenster_sonde)
    d.sonden = [s.__name__ for s in sonden]
    d.qt = qt_stand()
    LOG.info("Qt-Antrieb mit %s", d.qt)
    LOG.info("Sonden aktiv: %s%s", ", ".join(d.sonden) or "keine",
             "" if getattr(d.cfg, "zurueckhalten", True) else
             " — ABGESCHALTET (OPEN_MCP_CAD_ZURUECKHALTEN=0)")

    def schlag():
        if d.beenden:
            timer.stop()
            try:
                aufraeumen()
            finally:
                if eintrag in _QT_LAEUFT:
                    _QT_LAEUFT.remove(eintrag)
            return
        try:
            _takt(d, sonden)
        except Exception as exc:                       # noqa: BLE001
            # Ein Fehler im Timer darf Cadwork nicht mitnehmen.
            LOG.error("Fehler im Qt-Takt: %s\n%s", exc, traceback.format_exc())

    timer.timeout.connect(schlag)
    timer.start(int(POLL_INTERVAL_SECONDS * 1000))
    _QT_LAEUFT.append(eintrag)

    if d.cfg.fenster:
        try:
            eintrag["fenster"] = _qt_fenster(d)
        except Exception as exc:                       # noqa: BLE001
            # Ohne Fenster laeuft die Verbindung trotzdem — nur sieht man
            # in Cadwork dann nicht, dass sie an ist.
            LOG.error("Anzeigefenster konnte nicht geoeffnet werden: %s", exc)

    _bereit_melden(d)
    LOG.info("Qt-Antrieb aktiv (Takt %d ms) — Cadwork behaelt seinen "
             "Hauptthread, die Oberflaeche bleibt bedienbar",
             int(POLL_INTERVAL_SECONDS * 1000))
    return d


# --- Binden / Schliessen --------------------------------------------------

def _is_port_in_use(host, port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(PORT_PROBE_TIMEOUT_SECONDS)
    try:
        probe.connect((host, port))
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        try:
            probe.close()
        except OSError:
            pass


def _bind_with_retry(d, server_sock):
    cfg = d.cfg
    last_error = None
    for attempt in range(1, BIND_RETRY_ATTEMPTS + 1):
        try:
            server_sock.bind((cfg.host, cfg.port))
            return True
        except OSError as exc:
            last_error = exc
            if attempt < BIND_RETRY_ATTEMPTS:
                LOG.info("Bind-Versuch %d/%d auf %s:%s fehlgeschlagen (%s) — "
                             "warte %.1fs", attempt, BIND_RETRY_ATTEMPTS,
                             cfg.host, cfg.port, exc, BIND_RETRY_PAUSE_SECONDS)
                time.sleep(BIND_RETRY_PAUSE_SECONDS)
    LOG.error("Bind auf %s:%s nach %d Versuchen aufgegeben: %s",
                  cfg.host, cfg.port, BIND_RETRY_ATTEMPTS, last_error)
    return False


def _safe_shutdown_close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


# --- Einstieg -------------------------------------------------------------

def _steckplatz_festlegen(cfg, reserved_socket=None):
    """Port, Kennung, Anzeigename und Logdatei — in dieser Reihenfolge.

    DREI QUELLEN FUER DEN PORT, in dieser Rangfolge:

      1. ein RESERVIERTER SOCKET. Das Dashboard hat ihn mit
         SO_EXCLUSIVEADDRUSE gebunden und reicht ihn durch. Zwischen
         Reservierung und Betrieb liegt dann kein Moment, in dem ein
         anderer Prozess dazwischengehen koennte.
      2. ein FEST VORGEGEBENER Port (die klassischen Steckplaetze).
      3. die EIGENE SUCHE. Sie prueft und bindet danach — dazwischen liegt
         ein Rennen. Deshalb ist sie die letzte Wahl und nicht die erste.

    WARUM DAS VOR `_logger_einrichten` STEHT: die Logdatei heisst nach der
    Kennung, die Kennung kommt aus dem Port, und der Port steht bei einem
    dynamischen Steckplatz erst hier fest. Vorher lief der Logger zuerst —
    mit `log_datei=None`. Das hat den dynamischen Steckplatz unbrauchbar
    gemacht, ohne eine einzige Fehlermeldung.
    """
    if reserved_socket is not None:
        cfg.port = int(reserved_socket.getsockname()[1])
    elif cfg.port is None:
        cfg.port = freier_port(cfg.host)
    if cfg.instanz is None:
        cfg.instanz = kennung_fuer(cfg.port)
    if cfg.anzeigename is None:
        cfg.anzeigename = "Open MCP CAD %s" % cfg.instanz
    if cfg.log_datei is None:
        cfg.log_datei = r"C:\Users\Public\OpenMcpCad_%s.log" % cfg.instanz
    return cfg


# --- Ein Dienst je Prozess -------------------------------------------------
#
# DER BEFUND (2026-09-25, Logs C und D, PID 38428): zwei Plugin-Klicks, die
# Cadwork waehrend des Viewer-Modus gesammelt und danach in derselben
# Sekunde ausgefuehrt hat, starteten ZWEI Dienste im selben Prozess — C auf
# 53129 und D auf 53130, beide auf demselben Dokument, jeder mit eigener
# Schreiblizenz (damit schuetzt die Lizenz nicht mehr: zwei Clients
# schreiben gleichzeitig in dasselbe Modell). Die Logzeilen von C landeten
# ab da in der Datei von D.
#
# Beide Schutzstellen hingen an Dingen, die das nicht ueberleben:
#   * `_QT_LAEUFT` ist ein Modul-Global — und der Einstieg laedt den Kern
#     bei JEDEM Klick frisch. Ein zweiter Klick sah eine leere Liste.
#   * das Dashboard merkte sich den Dienst an `QApplication.instance()`.
#     In Cadwork gehoert die QApplication C++; ihr Python-Wrapper
#     verschwindet, sobald ihn niemand mehr haelt, und mit ihm jedes
#     Attribut. Gemessen 2026-09-25 in PyQt6 6.11 mit einer C++-eigenen
#     QApplication (`sip.transferto(app, None)`): neuer Wrapper, Attribut
#     weg.
#
# Deshalb liegt das Buch der laufenden Dienste in `sys.modules` unter einem
# festen Namen, der nicht an diesem Modul haengt: es ueberlebt jedes frische
# Laden, jeden neuen Wrapper und jede Kernversion — so lange wie der
# Python-Prozess, also so lange wie Cadwork.
_PROZESS_BUCH = "omcad_prozess_buch"


def _prozess():
    """Das Buch dieses Prozesses (bei Bedarf angelegt)."""
    buch = sys.modules.get(_PROZESS_BUCH)
    if buch is None:
        import types                                   # noqa: PLC0415
        neu = types.ModuleType(
            _PROZESS_BUCH, "Open MCP CAD: die Dienste dieses Prozesses")
        neu.sperre = threading.Lock()
        neu.dienste = []
        # Je Thread: laeuft dort gerade ein Takt? (siehe `_takt`). In
        # Cadwork laufen alle Takte im Hauptthread; je Thread, damit die
        # Pruefstaende der Gates sich nicht gegenseitig anhalten.
        neu.faden = threading.local()
        buch = sys.modules.setdefault(_PROZESS_BUCH, neu)
    return buch


def dienst_im_prozess():
    """Der Dienst, der in diesem Prozess laeuft oder gerade startet — oder None.

    Fuer das Dashboard: ein zweiter Klick findet damit den laufenden Dienst,
    auch wenn er selbst mit einem frischen Kern und ohne sein altes Dock
    kommt.

    Lebendig heisst `not d.beenden`. Trennen und Beenden setzen das Flag
    zuerst — ab da darf ein Klick wieder starten, auch wenn das Aufraeumen
    im naechsten Takt noch laeuft (es gibt nur noch den eigenen Port frei).
    Ausgetragen wird im naechsten `_prozess_belegen`; nur ein Start, der gar
    nicht erst lebendig wurde, traegt `serve` sofort aus.
    """
    buch = _prozess()
    with buch.sperre:
        for d in buch.dienste:
            if not d.beenden:
                return d
    return None


def _prozess_belegen(d, cfg):
    """Traegt `d` ein — ausser es laeuft schon ein anderer. -> der oder None.

    Pruefen und Eintragen unter EINER Sperre, und bevor irgendetwas Qt
    oder cwapi3d anfasst: ein zweiter Klick, der mitten in diesem Start
    ausgefuehrt wird, findet den Eintrag schon vor.

    `cfg.mehrere_im_prozess` (per getattr, kein Konfigurationsfeld) laesst
    mehrere zu — NUR fuer Pruefstaende, die mehrere Steckplaetze in einem
    Prozess nachstellen. In Cadwork hat ein Prozess genau ein Dokument.
    """
    buch = _prozess()
    with buch.sperre:
        buch.dienste[:] = [x for x in buch.dienste if not x.beenden]
        if not getattr(cfg, "mehrere_im_prozess", False):
            for x in buch.dienste:
                if x is not d:
                    return x
        if d not in buch.dienste:
            buch.dienste.append(d)
    return None


def _prozess_freigeben(d):
    buch = _prozess()
    with buch.sperre:
        buch.dienste[:] = [x for x in buch.dienste if x is not d]


def _dieses_modul():
    """Das Modulobjekt dieses Kerns, wenn es in `sys.modules` steht."""
    m = sys.modules.get(__name__)
    return m if getattr(m, "serve", None) is serve else None


def _fenster_zeigen(e, laeuft, cfg):
    """Das Anzeigefenster eines laufenden Dienstes wieder zeigen."""
    fenster = e.get("fenster")
    if fenster is None and cfg.fenster:
        try:
            e["fenster"] = _qt_fenster(laeuft)
        except Exception as exc:                       # noqa: BLE001
            LOG.error("Anzeigefenster nicht moeglich: %s", exc)
    elif fenster is not None:
        try:
            w = fenster["widget"]
            w.show()                    # Dock: wieder einblenden
            if not fenster.get("angedockt"):
                w.showNormal()          # freies Fenster: entminimieren
            w.raise_()
            w.activateWindow()
        except Exception as exc:                       # noqa: BLE001
            LOG.error("Anzeigefenster nicht erreichbar: %s", exc)


def _zweiter_start(laufend, cfg, reserved_socket):
    """Es laeuft schon ein Dienst in diesem Prozess: keinen zweiten starten.

    Der reservierte Socket wurde uns uebergeben — wir nehmen ihn nicht,
    also geben wir ihn frei. Sonst hielte ihn niemand und doch jemand.
    Geloggt wird VOR `_logger_einrichten`: die Zeile landet damit in der
    Datei des laufenden Dienstes, nicht in einer neuen fuer einen
    Steckplatz, den es nie gab.
    """
    if reserved_socket is not None:
        _safe_shutdown_close(reserved_socket)
    LOG.warning("Kein zweiter Dienst in diesem Prozess: %s (Port %s) laeuft "
                "schon — der Start%s unterbleibt.",
                laufend.cfg.anzeigename, laufend.cfg.port,
                (" auf Port %s" % cfg.port) if cfg.port else "")
    e = getattr(laufend, "qt_eintrag", None)
    if e is not None:
        _fenster_zeigen(e, laufend, cfg)
    return laufend


def serve(cfg, dienst=None, reserved_socket=None):
    """Startet einen Steckplatz — hoechstens EINEN je Prozess.

    Genau ein Dienst pro Cadwork-Prozess: laeuft schon einer (egal, welcher
    Kern ihn gestartet hat und auf welchem Port), wird kein zweiter
    gestartet, sondern der laufende zurueckgegeben und sein Fenster
    gezeigt; ein mitgegebener reservierter Socket wird freigegeben.

    Mit `qtimer` kehrt die Funktion sofort zurueck, mit `mainthread` haelt
    sie den Cadwork-Hauptthread, bis der Dienst beendet ist.

    `reserved_socket` ist ein bereits gebundener Listener. Wer ihn mitgibt,
    hat den Port schon exklusiv in der Hand; `serve` bindet dann nicht noch
    einmal. Ohne ihn bleibt alles wie bisher — der Parameter hat einen
    Default, kein bestehender Aufruf aendert sich.
    """
    d = dienst or Verbindungsdienst(cfg)
    laufend = _prozess_belegen(d, cfg)
    if laufend is not None:
        return _zweiter_start(laufend, cfg, reserved_socket)
    d.kern_modul = _dieses_modul()
    try:
        ergebnis = _serve(cfg, d, reserved_socket)
    except BaseException:
        _prozess_freigeben(d)
        raise
    # Kein laufender Dienst daraus geworden (Port belegt, anderer Dienst
    # auf demselben Port, klassischer Antrieb schon wieder zu Ende): dann
    # darf er auch nicht im Buch stehen, sonst sperrte er jeden weiteren
    # Start bis zum Cadwork-Neustart.
    if ergebnis is not d or d.beenden or d.zustand == "stopped":
        _prozess_freigeben(d)
    return ergebnis


def _serve(cfg, d, reserved_socket=None):
    """Der eigentliche Start — `serve` hat den Prozess schon belegt."""
    _steckplatz_festlegen(cfg, reserved_socket)
    _logger_einrichten(cfg)

    # Laeuft dieser Steckplatz schon? Dann waere ein zweiter Start ein
    # Port-Konflikt. Stattdessen wird das Anzeigefenster wieder gezeigt —
    # damit ist der Plugin-Knopf im Cadwork-Menue der natuerliche Weg,
    # ein weggeklicktes Fenster zurueckzuholen. (Seit 2.17 faengt das
    # Prozessbuch in `serve` diesen Fall schon vorher; hier bleiben Dienste,
    # die ein aelterer Kern ohne Buch gestartet hat.)
    for e in list(_QT_LAEUFT):
        laeuft = e.get("dienst")
        if laeuft is None or laeuft.cfg.port != cfg.port or laeuft.beenden:
            continue
        LOG.info("%s laeuft bereits — Anzeigefenster wird wieder gezeigt",
                 cfg.anzeigename)
        _fenster_zeigen(e, laeuft, cfg)
        return laeuft

    LOG.info("=" * 70)
    LOG.info("%s startet — Kern %s, Protokoll %d, PID %d, Python %s",
                 cfg.anzeigename, CORE_VERSION, PROTOKOLL_VERSION,
                 os.getpid(), sys.version.split()[0])
    LOG.info("Port %s:%d | UI-Pumpe %s | Antrieb %s | Lizenz-TTL %ds",
                 cfg.host, cfg.port, "AN" if cfg.ui_pumpe else "aus",
                 cfg.antrieb, cfg.lizenz_ttl_s)

    if cfg.antrieb not in ("mainthread", "qtimer"):
        LOG.error("Antrieb %r ist unbekannt — es wird 'mainthread' verwendet.",
                  cfg.antrieb)
        cfg.antrieb = "mainthread"

    d.beenden = False
    d.beenden_nach_auftrag = False
    d.job_queue = queue.Queue()
    d.offene_verbindungen = []
    d.start_epoch = time.time()
    d.start_mono = time.monotonic()
    d.herzschlag_mono = time.monotonic()
    d.zustand_setzen("starting")

    # Der Steckplatz steht oben schon fest (`_steckplatz_festlegen`).
    LOG.info("Steckplatz %s auf Port %d%s", cfg.instanz, cfg.port,
             " (reservierter Socket)" if reserved_socket is not None else "")

    # Die Belegt-Pruefung gilt nur fuer den Fall, dass WIR gleich binden.
    # Mit reserviertem Socket ist der Port schon in unserer Hand — dort
    # wuerde die Pruefung den eigenen Listener als "belegt" melden.
    if reserved_socket is None and _is_port_in_use(cfg.host, cfg.port):
        LOG.error("Port %s:%d ist noch belegt — warte %.1fs auf Freigabe",
                      cfg.host, cfg.port, BIND_RETRY_PAUSE_SECONDS)
        time.sleep(BIND_RETRY_PAUSE_SECONDS)

    if reserved_socket is not None:
        # Schon gebunden — und zwar exklusiv. Kein SO_REUSEADDR: das ist
        # hier nicht noetig und waere sogar schaedlich, weil es unter
        # Windows mehrfaches Binden zulassen kann. Genau davor schuetzt die
        # Reservierung.
        server_sock = reserved_socket
    else:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if not _bind_with_retry(d, server_sock):
            _safe_shutdown_close(server_sock)
            d.zustand_setzen("error", "Port %d belegt" % cfg.port)
            d.zustand_setzen("stopped")
            return d
    server_sock.listen(SOCKET_BACKLOG)
    server_sock.settimeout(ACCEPT_TIMEOUT_SECONDS)

    # Erst JETZT eintragen: vorher waere der Eintrag eine Behauptung. Der
    # Port ist gebunden, der Steckplatz nimmt Verbindungen an.
    registry_eintragen(cfg, d.dok_name)

    listener = threading.Thread(
        target=_listener_loop, args=(d, server_sock),
        name="Open-MCP-CAD-%s-Listener" % cfg.instanz, daemon=True)
    listener.start()

    def aufraeumen():
        LOG.info("Shutdown laeuft …")
        if d.bildschirm_aus:
            # Auf keinen Fall mit abgeschaltetem Bildschirm zurueckgeben.
            d.bildschirm_aus = False
            _bildschirm_an(d)
        # Und auf keinen Fall mit stehendem Ladebalken.
        _lauf_balken_weg(d)
        d.beenden = True
        _warteschlange_verwerfen(d, "Bridge wurde beendet")
        _safe_shutdown_close(server_sock)
        with d.verbindungs_sperre:
            n = len(d.offene_verbindungen)
            LOG.info("schliesse %d offene Verbindung(en)", n)
            for conn in list(d.offene_verbindungen):
                _safe_shutdown_close(conn)
            d.offene_verbindungen.clear()
        listener.join(timeout=ACCEPT_TIMEOUT_SECONDS + 1)
        if listener.is_alive():
            LOG.error("Listener-Thread laeuft noch — daemon, stirbt mit "
                      "dem Prozess")
        if d.zustand != "error":
            d.zustand_setzen("stopped")
        # Austragen, solange wir noch laufen. Faellt der Prozess hart, bleibt
        # die Datei liegen — dann raeumt sie der naechste Leser weg, weil die
        # PID nicht mehr lebt.
        registry_austragen(cfg.port)
        LOG.info("%s beendet", cfg.anzeigename)

    if cfg.antrieb == "qtimer":
        # Kehrt SOFORT zurueck — Cadwork behaelt seinen Hauptthread.
        # Aufgeraeumt wird spaeter, im Timer-Rueckruf.
        try:
            return _qtimer_antrieb(d, aufraeumen)
        except Exception as exc:                      # noqa: BLE001
            # `require_qtimer`: kein stiller Rueckfall.
            #
            # Der Rueckfall auf 'mainthread' ist die bewaehrte Architektur —
            # aber er HAELT den Cadwork-Hauptthread. Wer den Steckplatz von
            # Hand startet und danebensitzt, merkt das; wer ihn automatisch
            # starten laesst, merkt es NICHT, und Cadwork steht.
            #
            # Deshalb kann der Aufrufer verlangen, dass es Qt sein muss.
            # Dann wird sauber abgeraeumt und laut abgebrochen, statt
            # unbemerkt die Oberflaeche zu blockieren.
            #
            # Uebernommen aus Kern 2.15 (Codex-Sitzung 2026-09-14).
            # `getattr` mit Default: bestehende Konfigurationen ohne das
            # Feld verhalten sich unveraendert.
            if getattr(cfg, "require_qtimer", False):
                for eintrag in list(_QT_LAEUFT):
                    if eintrag.get("dienst") is d:
                        eintrag["timer"].stop()
                        _QT_LAEUFT.remove(eintrag)
                aufraeumen()
                raise RuntimeError(
                    "Qt-Antrieb konnte nicht gestartet werden, und "
                    "require_qtimer verbietet den Rueckfall auf den "
                    "Hauptthread-Antrieb (er wuerde Cadwork blockieren)"
                ) from exc
            LOG.error("Qt-Antrieb nicht moeglich (%s) — es wird auf den "
                      "bewaehrten Antrieb zurueckgefallen.", exc)
            cfg.antrieb = "mainthread"

    try:
        _main_loop(d)
    except Exception as exc:                          # noqa: BLE001
        LOG.error("Hauptthread-Loop abgestuerzt: %s\n%s", exc,
                  traceback.format_exc())
        d.zustand_setzen("error", str(exc))
    finally:
        aufraeumen()
        time.sleep(0.1)
    return d
