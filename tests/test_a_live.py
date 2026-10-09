#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Das A-Dashboard WIRKLICH bauen und bedienen — offscreen, ohne Cadwork.

Warum es diese Datei gibt: `test_a_prototyp.py` liest nur den Quelltext.
Damit liessen sich die Befunde vom 2026-08-15 nicht pruefen — "die Auswahl
geht verloren", "die Bauteile werden nicht aktiviert", "der Kontext ist nicht
sichtbar" sind Aussagen ueber VERHALTEN. Hier wird das Dock deshalb echt
gebaut (Qt offscreen), bedient und nachgemessen.

Cadwork wird durch Attrappen ersetzt: ein Kern-Modul mit genau den
Attributen, die das Dashboard anfasst, und ein Dienst, dessen Listen wir
selbst fuellen. cwapi3d kommt nie vor.

    python tests/test_a_live.py

BRAUCHT PyQt6. Das System-Python hat es nicht (Cadwork bringt sein eigenes
mit). Einmalig einrichten, ausserhalb des Repos:

    python -m venv %LOCALAPPDATA%\\Temp\\omcadqt
    %LOCALAPPDATA%\\Temp\\omcadqt\\Scripts\\python -m pip install PyQt6
    %LOCALAPPDATA%\\Temp\\omcadqt\\Scripts\\python scripts\\omcad\\test_a_live.py

Der Pfad muss KURZ sein: PyQt6 entpackt sehr tiefe Verzeichnisse, und unter
einem langen Ablageordner scheitert die Installation an Windows' Pfadlaenge
(gemessen 2026-08-15).

JEDE Zelle hat eine Kontrollzelle, die FEHLSCHLAGEN muss. Ohne sie sieht ein
Aufbau, der gar nichts misst, wie ein bestandener Test aus — das ist hier
schon zweimal passiert.
"""
import ast
import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Echte Schriften statt der Ersatzschrift von "offscreen": ohne sie misst
# Qt Kaestchen, und Breiten und Umbrueche (L58/L59, 300 px) waeren nicht die
# von Windows. Fehlt der Ordner, bleibt es beim Ersatz.
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
# Die Chat-Einstellungen (Anbieter, Adresse, Modell) NIE ins echte Profil:
# schon das Aufbauen des Tabs liest sie, die Anbieter-Zelle schreibt sie.
import tempfile as _tempfile                                # noqa: E402
os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = os.path.join(
    _tempfile.mkdtemp(prefix="omcad_live_einst_"), "chat.json")
# Die Zellen mit dem ECHTEN Kern (L22-L26) tragen sich in eine Registry ein
# und schreiben ein Log. Beides NIE ins echte `C:\Users\Public`: die
# Registry liest der Kern beim Laden, gesetzt wird sie also hier oben.
_LIVE_TMP = _tempfile.mkdtemp(prefix="omcad_live_kern_")
os.environ["OPEN_MCP_CAD_REGISTRY"] = os.path.join(_LIVE_TMP, "registry")
# Die Vermerke "Chat laeuft in einem anderen Cadwork" (Nacharbeit D) NIE in
# den echten Temp-Ordner, den laufende Docks lesen.
os.environ["OPEN_MCP_CAD_BELEGT"] = os.path.join(_LIVE_TMP, "belegt")

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo

# Umzug 2026-09-20: Gate liegt in tests/, Generator und Verbindungs-Client in
# scripts/. Ohne diesen Eintrag findet `import plugins_generieren` nichts —
# und zwar mit einem Abbruch, nicht still.
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
A = os.path.join(REPO, "cad_plugin", "Open MCP CAD A")

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if not bedingung:
        # `(detail,)`: ein Tupel als Detail warf sonst genau dann TypeError,
        # wenn die Zelle rot war (gefunden 2026-09-26 an einem Mutanten).
        print("  [FEHL] %s%s" % (titel, ("  — %s" % (detail,)) if detail
                                  else ""))
    return bool(bedingung)


# --- Attrappen ------------------------------------------------------------

class _Queue:
    def __init__(self):
        self.items = []

    def put(self, job):
        self.items.append(job)


class Dienst:
    """So viel Dienst, wie das Dashboard anfasst — mehr nicht."""

    def __init__(self):
        self.sperre = threading.RLock()
        self.beenden = False
        self.beenden_nach_auftrag = False
        self.pausiert = False
        self.zustand = "ready"
        self._zustand = "ready"
        self.verlauf = []
        self.hinweise = []
        self.postfach = []
        self.job_queue = _Queue()
        self.dunkel_entstanden = []
        self.aktive_elemente = 3

    def status(self):
        return {"zustand": self.zustand, "instanz": "A", "port": 53127,
                "dokument": "Probe.3d", "dokument_elemente": 1234,
                "aktive_elemente": self.aktive_elemente,
                "zeichenmodus": "auto", "haeppchen_empfehlung": 40,
                "ms_je_teil": 120.0, "auftrag": None, "hinweis": None,
                "fehler_text": None, "schreiblizenz": True, "wartende": 0}


class Kern:
    CORE_VERSION = "2.14.0"
    BESCHAEFTIGT = ("busy_read", "busy_write")
    ZUSTAENDE = ("ready", "busy_read", "busy_write", "paused", "error",
                 "starting", "stopped")
    ZEICHENMODI = (
        {"schluessel": "sicher", "anzeige": "langsam", "text": "Sicher"},
        {"schluessel": "auto", "anzeige": "auto", "text": "Automatisch"},
        {"schluessel": "max", "anzeige": "schnell", "text": "Maximal"},
    )

    class AuftragsMeta:
        def __init__(self, methode, params):
            self.methode, self.params = methode, params

    class Job:
        def __init__(self, client, methode, params, meta):
            self.client, self.methode = client, methode
            self.params, self.meta = params, meta

    class Konfiguration:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.fenster = True
            self.antrieb = ""

    @staticmethod
    def serve(cfg):
        return Dienst()

    @staticmethod
    def _warteschlange_verwerfen(d, grund):
        pass


def hinweis(nr, titel, text="", schwere="hinweis", dring=3, alter_s=0,
            ids=None, status="offen", gelesen=False, lauf=None):
    h = {"nr": nr, "titel": titel, "text": text, "schweregrad": schwere,
         "dringlichkeit": dring, "zeit": time.time() - alter_s,
         "element_ids": list(ids or []), "status": status, "gelesen": gelesen}
    if lauf is not None:
        h["lauf"] = lauf
    return h


def dashboard_laden():
    pfad = os.path.join(A, "omcad_a_dashboard.py")
    spec = importlib.util.spec_from_file_location("a_dash_live", pfad)
    m = importlib.util.module_from_spec(spec)
    sys.modules["a_dash_live"] = m
    spec.loader.exec_module(m)
    return m


_APP = None            # die QApplication MUSS am Leben bleiben


def aufbauen(hinweise=(), post=(), D=None):
    """Baut das Dock offscreen. Rueckgabe (Modul, Zustand, Dienst).

    `D`: ein schon geladenes Dashboard (etwa ein Mutant, s. `_mutant`),
    sonst frisch von der Platte.
    """
    global _APP
    from PyQt6.QtWidgets import QApplication
    # Ohne die feste Bezugnahme raeumt Python die QApplication sofort wieder
    # ab, und `_zustand()` findet keine — der Zustand des Docks haengt naemlich
    # an ihr (das ist genau der Trick, mit dem er das Modul-Neuladen ueberlebt).
    _APP = QApplication.instance() or QApplication([])
    if D is None:
        D = dashboard_laden()
    D._monitor_starten = lambda z: None          # kein Thread, kein Netz
    D._verbindungen_zeichnen = lambda z: None    # braucht echte Ports
    D._ablage_pflegen = lambda z: None           # nichts auf die Platte
    kern = Kern()
    D.oeffnen(lambda: kern, lambda k: Kern.Konfiguration(
        instanz="A", port=53127, anzeigename="Open MCP CAD A",
        log_datei=""))
    z = D._zustand()
    d = Dienst()
    z["dienst"], z["kern"] = d, kern
    with d.sperre:
        d.hinweise.extend(hinweise)
        d.postfach.extend(post)
    return D, z, d


def _hinweise_probe():
    return [
        hinweis(1, "Annahme: Wandhoehe von der Nachbarwand uebernommen",
                # Bewusst laenger als die Kuerzungsgrenze der Karte (220) —
                # sonst misst der Vergleich Karte-gegen-Vollbild nichts.
                "In der Vorlage stand keine Hoehe fuer diese Wand. Der Agent "
                "hat deshalb die Hoehe der Nachbarwand im selben Geschoss "
                "genommen, weil sonst nichts zur Hand war. Weicht die echte "
                "Hoehe ab, verschieben sich alle Oeffnungen darin um "
                "denselben Betrag. Bitte gegen die Plaene des Projekts "
                "Seeblick pruefen. Betrifft die Nordwand im Erdgeschoss.",
                "warnung", 4, 2.0, [1001, 1002, 1003]),
        hinweis(2, "Fenstersturz geraten", "Kein Mass vorhanden.",
                "frage", 2, 3.0, [2001]),
        hinweis(3, "Kollision geprueft, nichts gefunden", "",
                "hinweis", 1, 4.0, []),
    ]


# --- Die Zellen -----------------------------------------------------------

def zelle_auswahl():
    """Der Hauptbefund: "sie werden wie abgewaehlt".

    Der alte Aufbau hatte einen Zeiteimer `int(alter/5)` im Stempel und
    baute die Liste damit alle fuenf Sekunden neu. Gemessen: Auswahl nach
    0,75 s weg. Hier wird 4,5 s lang aufgefrischt — deutlich laenger.
    """
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    b = z["w"]["hinweise"]
    z["w"]["hinweis_umgebung"]["waehlen"](1)
    start = b["gewaehlt_nr"]
    for _ in range(30):
        time.sleep(0.15)
        D._auffrischen(z)
    pruefe("L1 die Auswahl ueberlebt 4,5 s Auffrischen",
           start == 1 and b["gewaehlt_nr"] == 1,
           "start=%s ende=%s" % (start, b["gewaehlt_nr"]))
    z["w"]["hinweis_umgebung"]["waehlen"](1)
    pruefe("L1 KONTROLLE: ein zweiter Klick waehlt wirklich ab",
           b["gewaehlt_nr"] is None,
           "sonst waere 'bleibt gewaehlt' trivial erfuellt — ein Aufbau, der "
           "die Auswahl NIE aendert, bestuende die Zeile darueber auch")


def zelle_aktivieren():
    """"die objekte muessen pink aktiviert werden nicht nur angezoomt"."""
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    d.job_queue.items = []
    z["w"]["hinweis_umgebung"]["waehlen"](1)
    auftraege = [(j.methode, j.params) for j in d.job_queue.items]
    zeigen = [p for m, p in auftraege if m == "elemente_zeigen"]
    pruefe("L2 Anwaehlen schickt sofort einen Zeige-Auftrag",
           len(zeigen) == 1 and zeigen[0]["element_ids"] == [1001, 1002, 1003],
           "Auftraege: %s" % [m for m, _ in auftraege])
    d.job_queue.items = []
    z["w"]["hinweis_umgebung"]["waehlen"](3)          # Hinweis OHNE Bauteile
    pruefe("L2 KONTROLLE: ein Hinweis ohne Bauteile schickt nichts",
           not [j for j in d.job_queue.items
                if j.methode == "elemente_zeigen"],
           "sonst kaeme der Auftrag oben von irgendwo sonst")


def zelle_abhaken():
    """"man muss klar und einfach abhaken koennen ... direkt im hinweisfenster"."""
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    karte = z["w"]["hinweise"]["karten"][2]
    karte.haken.setChecked(True)
    with d.sperre:
        stand = [h["status"] for h in d.hinweise if h["nr"] == 2][0]
    pruefe("L3 der Haken in der Karte setzt 'erledigt'", stand == "erledigt",
           stand)
    karte.haken.setChecked(False)
    with d.sperre:
        zurueck = [h["status"] for h in d.hinweise if h["nr"] == 2][0]
    pruefe("L3 KONTROLLE: Haken weg macht ihn wieder offen",
           zurueck == "offen", zurueck)


def zelle_gruppen(H):
    """"nach sitzung sortiert ... die anderen wie in ein archiv"."""
    frisch = [hinweis(9, "neu", "", "hinweis", 3, 10),
              hinweis(8, "neu2", "", "hinweis", 3, 30)]
    alt = [hinweis(2, "alt", "", "hinweis", 3, 4000),
           hinweis(1, "aelter", "", "hinweis", 3, 4200)]
    gruppen = H.gruppieren(frisch + alt)
    pruefe("L4 zwei Laeufe werden getrennt", len(gruppen) == 2,
           "%d Gruppen" % len(gruppen))
    pruefe("L4 der neue Lauf steht oben",
           gruppen and gruppen[0][2][0]["nr"] == 9)
    pruefe("L4 KONTROLLE: dicht beieinander bleibt EINE Gruppe",
           len(H.gruppieren(frisch)) == 1)
    # Der Stempel aus dem Kern ist genauer als die Zeitluecke: zwei
    # Zeichenlaeufe koennen 20 Sekunden auseinanderliegen.
    pruefe("L4 der Lauf-Stempel trennt auch ohne Zeitluecke",
           len(H.gruppieren([dict(frisch[0], lauf=7),
                             dict(frisch[1], lauf=8)])) == 2)
    pruefe("L4 KONTROLLE: gleicher Lauf-Stempel trennt NICHT",
           len(H.gruppieren([dict(frisch[0], lauf=7),
                             dict(frisch[1], lauf=7)])) == 1,
           "sonst trennte die Pruefung oben bei jedem Stempel, auch gleichem")


def zelle_kontext(H):
    """"muss klar erkennbar sein das es als kontext mitkommt"."""
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    b = z["w"]["hinweise"]
    z["w"]["hinweis_umgebung"]["waehlen"](1)
    D._auffrischen(z)
    streifen = b["kontext"].text()
    pruefe("L5 der Kontext-Streifen nennt Hinweis und Bauteile",
           "#1" in streifen and "Bauteil" in streifen, streifen[:90])
    # Die Zahl der aktiven Bauteile ist im Kern bis zu 5 s alt (sie wird nur
    # im Leerlauf aufgefrischt, waehrend eines Zeichenlaufs gar nicht).
    # Der Streifen darf sie deshalb ZEIGEN, aber nicht als Gegenwart
    # ausgeben — geprueft wird genau diese Vorsicht.
    pruefe("L5 der Streifen nennt die aktiven Bauteile mit Vorbehalt",
           "aktiv" in streifen and "zuletzt gesehen" in streifen,
           streifen[:110])
    pruefe("L5 KONTROLLE: die Nachricht selbst behauptet KEINE Zahl",
           "3" not in H.nachricht_bauen(None, "x", 3).split("]")[0],
           "die IDs im Anhang sind frisch, die Zahl aus der Oberflaeche "
           "waere es nicht")
    d.job_queue.items = []
    b["antwort"].setText("Ja, 15 mm stimmt.")
    b["btn_antwort"].click()
    gesendet = [j.params["text"] for j in d.job_queue.items
                if j.methode == "nachricht_senden"]
    pruefe("L5 die Nachricht im Briefkasten traegt den Bezug",
           gesendet and "#1" in gesendet[0] and "1001" in gesendet[0]
           and "15 mm stimmt" in gesendet[0],
           (gesendet[0][:100] if gesendet else "nichts gesendet"))
    pruefe("L5 KONTROLLE: ohne gewaehlten Hinweis steht KEIN Bezug drin",
           "#" not in H.nachricht_bauen(None, "blosser Text", 0))


def zelle_vollbild():
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    z["w"]["hinweis_umgebung"]["vollbild"](1)
    dlg = z.get("hinweis_fenster")
    pruefe("L6 Vollbild geht auf und ist NICHT modal",
           dlg is not None and dlg.isModal() is False,
           "modal waere fatal: es hielte Cadworks Ereignisschleife an, und "
           "in genau der laeuft die Auftragswarteschlange")
    from PyQt6.QtWidgets import QTextBrowser
    koerper = dlg.findChildren(QTextBrowser) if dlg else []
    ganzer = koerper[0].toPlainText() if koerper else ""
    kurz = z["w"]["hinweise"]["karten"][1].text.text()
    pruefe("L6 Vollbild zeigt den GANZEN Text", "Erdgeschoss" in ganzer,
           "%d Zeichen" % len(ganzer))
    pruefe("L6 KONTROLLE: in der Karte steht er gekuerzt",
           len(ganzer) > len(kurz) and kurz.endswith("…"),
           "Karte %d, Vollbild %d" % (len(kurz), len(ganzer)))
    # Wieder zu: L94 zaehlt spaeter die sichtbaren Fenster des Prozesses
    # (vorher blieb dieser Dialog bis zum Ende des Gates offen).
    if dlg is not None:
        dlg.close()


def zelle_karten_hoehe():
    """Traegt der Behaelter umbrechenden Text im schmalen Dock?

    Die Falle: ein QLabel mit Wortumbruch braucht eine Hoehe, die von der
    BREITE abhaengt (`heightForWidth`). Ein QListWidget fragt nicht danach —
    dort war der Text abgeschnitten (0/6 gemessen). Diese Zelle nagelt fest,
    dass das Board den Weg nimmt, der es richtig macht.
    """
    from PyQt6.QtWidgets import QApplication
    D, z, d = aufbauen(_hinweise_probe())
    D._auffrischen(z)
    b = z["w"]["hinweise"]
    b["tab"].resize(320, 700)
    b["tab"].show()
    QApplication.processEvents()
    schlecht = []
    for nr, karte in b["karten"].items():
        lb = karte.titel
        if lb.width() > 0 and lb.height() < lb.heightForWidth(lb.width()):
            schlecht.append(nr)
    pruefe("L7 kein Kartentitel ist abgeschnitten (Dock 320 px)",
           not schlecht, "abgeschnitten: %s" % schlecht)
    # Kontrolle: derselbe Massstab an einem absichtlich zu niedrigen Label.
    karte = b["karten"][1]
    karte.titel.setFixedHeight(4)
    QApplication.processEvents()
    lb = karte.titel
    pruefe("L7 KONTROLLE: der Massstab erkennt abgeschnittenen Text",
           lb.height() < lb.heightForWidth(max(1, lb.width())),
           "sonst misst L7 gar nichts")


# --- Ein Klick verbindet (2026-09-22) ---------------------------------
#
# Diese Zellen laufen durch den ECHTEN Weg: `oeffnen(..., verbinden=True)`
# -> `_verbinden` -> `_steckplatz_reservieren` mit echten Sockets. Ersetzt
# sind nur der Kern (kein Cadwork, keine Registry, keine Logdatei) und der
# Verbindungs-Client (seine Steckplaetze zeigen auf Testports).
#
# ⚠ PORTS NUR EPHEMER UND NIE IM CADWORK-BEREICH. Jeder Testport kommt aus
# `_belegen()`. Ein blosses bind(("127.0.0.1", 0)) reicht NICHT: Windows
# vergibt ephemere Ports ab 49152, der Bereich PORT_VON..PORT_BIS liegt
# mittendrin (gemessen 2026-09-25: bind(0) landete auf 53134-53197). Dann
# stoesst der Test mit einem laufenden Cadwork zusammen (oder umgekehrt).

def _kern_bereich():
    """PORT_VON..PORT_BIS aus dem Kern-QUELLTEXT — keine eigene Liste."""
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
    with open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    werte = {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
             if isinstance(k, ast.Assign) and len(k.targets) == 1
             and isinstance(k.targets[0], ast.Name)
             and k.targets[0].id in ("PORT_VON", "PORT_BIS")}
    return set(range(werte["PORT_VON"], werte["PORT_BIS"] + 1))


_CADWORK_PORTS = _kern_bereich()
_VERGEBEN = []            # jeder Port, den dieses Gate belegt oder bedient


def _exklusiv():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    return s


def _belegen(verboten=None):
    """Ein Port, den "ein anderes Cadwork" haelt. -> (Socket, Port).

    Landet bind(0) in `verboten` (sonst: dem Cadwork-Bereich), wird der
    Socket sofort freigegeben und neu gezogen — wie `_ephemerer_socket` in
    test_bootstrap.
    """
    verboten = _CADWORK_PORTS if verboten is None else verboten
    for _ in range(200):
        s = _exklusiv()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        if p not in verboten:
            _VERGEBEN.append(p)
            return s, p
        s.close()
    raise RuntimeError("kein ephemerer Port ausserhalb des Cadwork-Bereichs")


def _ausserhalb(ports):
    """Gab es Testports, und liegt keiner im Cadwork-Bereich?"""
    return bool(ports) and not set(ports) & _CADWORK_PORTS


def _freie_ports(n):
    """n verschiedene Ports, die gerade frei sind (gleichzeitig gebunden,
    damit das System nicht zweimal denselben vergibt, dann freigegeben)."""
    socks = [_belegen()[0] for _ in range(n)]
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def _bindbar(port):
    s = _exklusiv()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class _Client:
    """Verbindungs-Client-Attrappe: nur, was `_verbinden` und der Tab lesen."""
    HOST = "127.0.0.1"
    BESCHAEFTIGT = ("busy_read", "busy_write")

    def __init__(self, steckplaetze):
        self.STECKPLAETZE = list(steckplaetze)


class _VerbindKern(Kern):
    """Kern-Attrappe fuers Verbinden: zaehlt serve() und behaelt den
    reservierten Socket — wie der echte Kern, der auf ihm lauscht."""

    def __init__(self, von, bis):
        self.PORT_VON, self.PORT_BIS = von, bis
        self.aufrufe = []

    @staticmethod
    def kennung_fuer(port):
        return "P%d" % port

    def serve(self, cfg, reserved_socket=None):
        self.aufrufe.append((cfg, reserved_socket))
        if reserved_socket is not None:
            # Gemessen, nicht angenommen: der Port, den das ECHTE
            # `_steckplatz_reservieren` gebunden hat (L21 prueft ihn).
            _VERGEBEN.append(reserved_socket.getsockname()[1])
        return Dienst()

    def aufraeumen(self):
        for _cfg, s in self.aufrufe:
            if s is not None:
                s.close()


def _cfg_leer(_kern):
    # Wie der dynamische Einstieg: alles offen, `_verbinden` setzt es.
    return Kern.Konfiguration(instanz=None, port=None, anzeigename=None,
                              log_datei=None)


_ALTE_ZUSTAENDE = []      # abgeloeste Docks: am Leben halten, nie freigeben


def _anker_name():
    """`ANKER` aus dem Dashboard-QUELLTEXT — keine eigene Kopie des Namens."""
    with open(os.path.join(A, "omcad_a_dashboard.py"), encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    for k in baum.body:
        if (isinstance(k, ast.Assign) and len(k.targets) == 1
                and isinstance(k.targets[0], ast.Name)
                and k.targets[0].id == "ANKER"):
            return ast.literal_eval(k.value)
    raise RuntimeError("ANKER fehlt im Dashboard")


def _frischer_start():
    """Als waere Cadwork gerade gestartet: kein Dock, kein Dienst.

    Der Zustand liegt in `sys.modules[ANKER]` (genau damit er das Neuladen
    des Moduls ueberlebt) und, fuer aeltere Docks, an der QApplication —
    also muss er an beiden Stellen entfernt werden.
    """
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    anker = sys.modules.pop(_anker_name(), None)
    z = getattr(anker, "z", None) or getattr(_APP, "_omcad_a_prototyp", None)
    if z is not None:
        # Beide Takte anhalten — der Chat-Takt lief sonst fuer jeden
        # abgeloesten Zustand weiter. Ein Timer kann schon tot sein (L24
        # loescht ein Dock samt Timern).
        for schluessel in ("timer", "chat_takt"):
            if z.get(schluessel) is not None:
                try:
                    z[schluessel].stop()
                except RuntimeError:
                    pass
        if z.get("chatfenster") is not None:
            # Seit K9 ein schwebendes Dock: ebenfalls nur verstecken.
            try:
                z["chatfenster"].hide()
            except RuntimeError:
                pass
        if z.get("mini") is not None:
            # Seit K11 zeigt der Klick die Leiste: ebenfalls nur verstecken.
            try:
                z["mini"].hide()
            except RuntimeError:
                pass
        for schluessel in ("anzeige", "fenster", "aufklapper"):
            # K12: das EINE Fenster und die Arbeitsanzeige — nur verstecken.
            if z.get(schluessel) is not None:
                try:
                    z[schluessel].hide()
                except RuntimeError:
                    pass
        if z.get("dock") is not None:
            # NUR verstecken, nicht freigeben: ein `deleteLater` hier stapelt
            # sich bis zum naechsten `processEvents` — und das Abraeumen
            # ganzer Docks mitten in einer anderen Zelle endete 2026-09-24 in
            # einer Zugriffsverletzung. Im Betrieb wird nie ein Dock
            # freigegeben; im Test bleiben die alten bis zum Prozessende.
            try:
                z["dock"].hide()
            except RuntimeError:
                pass
        _ALTE_ZUSTAENDE.append(z)
    _APP._omcad_a_prototyp = None


def _klick(client, kern, verbinden=True, laden=None):
    """EIN Plugin-Klick: der Einstieg laedt das Dashboard FRISCH von der
    Platte und ruft `oeffnen`. -> (Modul, Zustand, Rueckgabe).

    `laden`: statt `dashboard_laden` (etwa ein Mutant, s. `_mutant`)."""
    D = (laden or dashboard_laden)()
    D._monitor_starten = lambda z: None
    D._verbindungen_zeichnen = lambda z: None
    D._ablage_pflegen = lambda z: None
    D._verbindungen_client = lambda: client
    rueck = D.oeffnen(lambda: kern, _cfg_leer, verbinden=verbinden)
    return D, D._zustand(), rueck


def _hinweis(z):
    h = z["w"]["hinweis"]
    return h.text() if not h.isHidden() else ""


def _meldung(z):
    """Die Fehlerzeile an der Eingabe (S7) — leer, wenn sie verborgen ist."""
    f = z["w"].get("chat_fehler")
    return f.text() if f is not None and not f.isHidden() else ""


def _senden_klick(D, z, text="Probe-Nachricht"):
    """S8: Text ins Feld, dann der Senden-Knopf — seit S8 startet das den
    Chat (vorher "Starten"). -> was danach im Feld steht."""
    w = z["w"]
    w["chat_eingabe"].setPlainText(text)
    w["chat_senden"].click()
    return w["chat_eingabe"].toPlainText()


def _enter(D, z, text="Probe-Nachricht"):
    """Wie `_senden_klick`, aber mit Enter im Feld (auch bei gesperrtem
    Knopf moeglich). -> was danach im Feld steht."""
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    feld = z["w"]["chat_eingabe"]
    feld.setPlainText(text)
    _APP.sendEvent(feld, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                   Qt.KeyboardModifier.NoModifier))
    return feld.toPlainText()


def zelle_klick_verbindet():
    """Frischer Start -> genau einmal verbinden, erster freier Port, atomar."""
    _frischer_start()
    halter, p_x = _belegen()                  # X haelt "ein anderes Cadwork"
    p_y, p_z = _freie_ports(2)
    client = _Client([("X", p_x), ("Y", p_y), ("Z", p_z)])
    kern = _VerbindKern(1, 0)                 # kein weiterer Bereich
    try:
        _D, z, rueck = _klick(client, kern)
        pruefe("L8 frischer Plugin-Start verbindet GENAU einmal",
               len(kern.aufrufe) == 1 and rueck is z["dienst"]
               and rueck is not None,
               "%d serve()-Aufrufe, Rueckgabe %r" % (len(kern.aufrufe), rueck))
        cfg, sock = kern.aufrufe[0] if kern.aufrufe else (None, None)
        pruefe("L8 Standardfall: der ERSTE FREIE (Y), nicht der belegte X "
               "und nicht Z",
               cfg is not None and cfg.instanz == "Y" and cfg.port == p_y,
               "bekam %r/%r" % (getattr(cfg, "instanz", None),
                                getattr(cfg, "port", None)))
        pruefe("L8 der Port ist RESERVIERT: gebundener Socket an serve(), "
               "ein zweites Binden scheitert",
               sock is not None and sock.getsockname()[1] == p_y
               and not _bindbar(p_y),
               "Socket %r" % (sock.getsockname() if sock else None,))
        pruefe("L8 Qt-Antrieb verlangt, altes Kernfenster aus",
               cfg is not None and getattr(cfg, "require_qtimer", False)
               is True and cfg.fenster is False,
               "sonst blockiert ein Qt-Fehler Cadwork still")
        kern.aufraeumen()
        pruefe("L8 KONTROLLE: nach Freigabe ist Y wieder bindbar",
               _bindbar(p_y), "sonst misst 'ein zweites Binden scheitert' "
               "nichts")

        _frischer_start()
        kern2 = _VerbindKern(1, 0)
        _klick(client, kern2, verbinden=False)
        pruefe("L8 KONTROLLE: ohne verbinden=True startet nichts",
               kern2.aufrufe == [], "%d Aufrufe" % len(kern2.aufrufe))
    finally:
        halter.close()
        kern.aufraeumen()
        _frischer_start()


def zelle_kein_doppelstart():
    """Erneuter Plugin-Klick bei laufender Verbindung -> kein zweiter Start."""
    _frischer_start()
    p_y, p_z = _freie_ports(2)
    client = _Client([("Y", p_y), ("Z", p_z)])
    kern = _VerbindKern(1, 0)
    try:
        _D, z, erster = _klick(client, kern)
        _D2, z2, zweiter = _klick(client, kern)     # frisches Modul, wie Cadwork
        pruefe("L9 zweiter Klick bei laufender Verbindung startet NICHTS",
               len(kern.aufrufe) == 1 and zweiter is erster and z2 is z,
               "%d serve()-Aufrufe" % len(kern.aufrufe))
        pruefe("L9 und sagt es: _verbinden meldet 'laeuft'",
               _D2._verbinden(z2) == "laeuft" and len(kern.aufrufe) == 1)
        pruefe("L9 der laufende Steckplatz bleibt belegt, Z bleibt frei",
               not _bindbar(p_y) and _bindbar(p_z),
               "ein Doppelstart haette Z genommen")
        # KONTROLLE: ist der Dienst beendet, MUSS derselbe Klick neu
        # verbinden — sonst verhinderte oben etwas anderes als der Guard.
        erster.beenden = True
        kern.aufraeumen()
        _klick(client, kern)
        pruefe("L9 KONTROLLE: nach dem Trennen verbindet der Klick wieder",
               len(kern.aufrufe) == 2, "%d Aufrufe" % len(kern.aufrufe))
    finally:
        kern.aufraeumen()
        _frischer_start()


def zelle_wunsch_belegt():
    """Gewaehlter, belegter Steckplatz -> sauberer Fehler, kein Ausweichen."""
    _frischer_start()
    halter, p_x = _belegen()
    p_y, = _freie_ports(1)
    client = _Client([("X", p_x), ("Y", p_y)])
    kern = _VerbindKern(1, 0)
    try:
        # Erster Klick ohne Verbinden: nur das Dock. Die Wahl lebt dort
        # (2026-09-22: "nur in der Sitzung", keine Datei).
        _D, z, _r = _klick(client, kern, verbinden=False)
        wahl = z["w"]["steckplatz_wahl"]
        wahl.setCurrentIndex(wahl.findData("X"))
        _D, z, rueck = _klick(client, kern)          # der Plugin-Klick
        pruefe("L10 gewaehlter, belegter Steckplatz: kein serve(), kein "
               "Dienst", kern.aufrufe == [] and rueck is None
               and z["dienst"] is None,
               "%d Aufrufe — ein Ausweichen zeichnete in eine andere Datei"
               % len(kern.aufrufe))
        pruefe("L10 die Meldung nennt den Steckplatz",
               "Steckplatz X ist belegt" in _hinweis(z), _hinweis(z)[:90])
        pruefe("L10 nichts wurde nebenbei reserviert (Y bleibt frei)",
               _bindbar(p_y))
        # KONTROLLE: derselbe Weg mit einem FREIEN Wunsch verbindet — also
        # hat oben die Belegung gebremst, nicht ein kaputter Wahlweg.
        wahl.setCurrentIndex(wahl.findData("Y"))
        _D, z, rueck = _klick(client, kern)
        cfg = kern.aufrufe[0][0] if kern.aufrufe else None
        pruefe("L10 KONTROLLE: ein freier Wunsch wird genau so genommen",
               cfg is not None and cfg.instanz == "Y" and cfg.port == p_y,
               "bekam %r" % (getattr(cfg, "instanz", None),))
    finally:
        halter.close()
        kern.aufraeumen()
        _frischer_start()


def zelle_alle_belegt():
    """Alle Ports belegt -> sauberer Fehler, keine Ausnahme."""
    _frischer_start()
    h1, p1 = _belegen()
    h2, p2 = _belegen()
    h3, p3 = _belegen()
    client = _Client([("X", p1), ("Y", p2)])
    kern = _VerbindKern(p3, p3)             # auch der weitere Bereich belegt
    try:
        try:
            _D, z, rueck = _klick(client, kern)
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen, z, rueck = exc, None, None
        pruefe("L11 alle belegt: keine Ausnahme aus dem Klick",
               geworfen is None, repr(geworfen))
        pruefe("L11 alle belegt: kein serve(), kein Dienst",
               kern.aufrufe == [] and rueck is None,
               "%d Aufrufe" % len(kern.aufrufe))
        pruefe("L11 die Meldung sagt es",
               z is not None and "Steckplätze sind belegt" in _hinweis(z),
               _hinweis(z)[:90] if z else "")
        # KONTROLLE: wird einer frei, verbindet derselbe Klick auf genau den.
        h2.close()
        _klick(client, kern)
        cfg = kern.aufrufe[0][0] if kern.aufrufe else None
        pruefe("L11 KONTROLLE: einer frei -> genau der wird genommen",
               cfg is not None and cfg.port == p2,
               "bekam %r" % (getattr(cfg, "port", None),))
    finally:
        for h in (h1, h2, h3):
            h.close()
        kern.aufraeumen()
        _frischer_start()


def zelle_fehler_im_verbinden():
    """Ein Fehler beim Laden des Kerns landet im Dock, nicht im Einstieg."""
    _frischer_start()
    client = _Client([])

    def kaputt():
        raise RuntimeError("Kern-Attrappe: nicht ladbar")

    try:
        D = dashboard_laden()
        D._monitor_starten = lambda z: None
        D._verbindungen_zeichnen = lambda z: None
        D._ablage_pflegen = lambda z: None
        D._verbindungen_client = lambda: client
        try:
            rueck = D.oeffnen(kaputt, _cfg_leer, verbinden=True)
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen, rueck = exc, None
        z = D._zustand()
        pruefe("L12 Fehler beim Verbinden fliegt NICHT aus oeffnen()",
               geworfen is None and rueck is None, repr(geworfen))
        pruefe("L12 er steht in der Hinweiszeile",
               "nicht ladbar" in _hinweis(z), _hinweis(z)[:90])
        pruefe("L12 KONTROLLE: _verbinden meldet 'fehler'",
               D._verbinden(z) == "fehler")
    finally:
        _frischer_start()


# --- Die Anzeige der Verbindungen (2026-09-21/23) ---------------------
#
# Karten NUR fuer verbundene Steckplaetze, das Dropdown bietet ALLE Ports.
# Vorher: sechs feste Karten A-F, meist "Aus", alles jenseits von F nur als
# Textzeile.

def _status(port, instanz, zustand, dokument=""):
    return {"port": port, "instanz": instanz, "zustand": zustand,
            "dokument": dokument, "auftrag": None, "hinweis": ""}


def _dock_mit_zeichnen(client, kern):
    """Wie `_klick`, aber mit dem ECHTEN `_verbindungen_zeichnen`."""
    D = dashboard_laden()
    D._monitor_starten = lambda z: None
    D._ablage_pflegen = lambda z: None
    D._verbindungen_client = lambda: client
    D.oeffnen(lambda: kern, _cfg_leer, verbinden=False)
    return D, D._zustand()


def zelle_karten_nur_verbundene():
    from PyQt6.QtWidgets import QPushButton
    _frischer_start()
    client = _Client([(chr(ord("A") + i), 53127 + i) for i in range(6)])
    client.dauer_text = lambda s: ""
    try:
        D, z = _dock_mit_zeichnen(client, _VerbindKern(1, 0))
        z["monitor_daten"] = [
            _status(53127, "A", "ready", "Haus.3d"),
            _status(53128, "B", "unreachable"),
            _status(53129, "C", "no_answer"),
            _status(53130, "D", "unreachable"),
            _status(53153, "26", "busy_write", "Stall.3d")]
        D._verbindungen_zeichnen(z)
        karten = z["w"]["verb_karten"]
        pruefe("L13 Karten nur fuer verbundene Steckplaetze (auch '26')",
               list(karten) == [53127, 53129, 53153], list(karten))
        # Gegenpruefung Laien-Sicht K12: Steckplatz und Port stehen nur
        # noch in den Technik-Details (L112).
        pruefe("L13 die Karte nennt das Dokument, ohne Steckplatz und Port",
               karten.get(53153)
               and karten[53153]["dok"].text() == "Stall.3d"
               and karten[53153]["titel"].text() == "Anderes Cadwork",
               karten.get(53153) and (karten[53153]["titel"].text(),
                                      karten[53153]["dok"].text()))
        pruefe("L13 der Kopf zaehlt die verbundenen",
               z["w"]["verb_kopf"].text() == "3 Verbindungen aktiv",
               z["w"]["verb_kopf"].text())
        knoepfe = [b.text() for k in karten.values()
                   for b in k["widget"].findChildren(QPushButton)]
        pruefe("L13 keine Karte hat einen Startknopf",
               "Verbinden" not in knoepfe, knoepfe)
        vorher = {p: k["widget"] for p, k in karten.items()}
        D._verbindungen_zeichnen(z)
        pruefe("L13 gleiche Menge -> Karten bleiben (kein Neubau im Takt)",
               all(z["w"]["verb_karten"][p]["widget"] is w
                   for p, w in vorher.items()))
        z["monitor_daten"] = [_status(53127 + i, chr(65 + i), "unreachable")
                              for i in range(6)]
        D._verbindungen_zeichnen(z)
        pruefe("L13 KONTROLLE: nichts verbunden -> keine Karte, Hinweis",
               z["w"]["verb_karten"] == {}
               and "Keine Verbindung" in z["w"]["verb_kopf"].text(),
               z["w"]["verb_kopf"].text())
        # Bild vom 2026-09-24: A dreizehnmal. Ein doppelter Port in den
        # Daten liess je Takt eine Karte liegen.
        from PyQt6.QtWidgets import QApplication
        a, c = _status(53127, "A", "ready"), _status(53129, "C", "ready")
        for daten in ([a, a, c],) * 6 + ([a, c], [a, a, c]):
            z["monitor_daten"] = daten
            D._verbindungen_zeichnen(z)
            QApplication.processEvents()
        lay = z["w"]["verb_karten_lay"]
        pruefe("L13 doppelter Port: genau 2 Karten, auch nach 8 Takten",
               lay.count() == 2 and list(z["w"]["verb_karten"]) == [53127, 53129],
               "%d im Layout, %s gemerkt" % (lay.count(),
                                             list(z["w"]["verb_karten"])))
    finally:
        _frischer_start()


def zelle_dropdown_alle_ports():
    _frischer_start()
    client = _Client([(chr(ord("A") + i), 53127 + i) for i in range(6)])
    try:
        _D, z, _r = _klick(client, _VerbindKern(53127, 53199),
                           verbinden=False)
        wahl = z["w"]["steckplatz_wahl"]
        ports = [wahl.itemText(i) for i in range(wahl.count())]
        pruefe("L14 das Dropdown bietet ALLE Ports des Kerns (1 + 73)",
               wahl.count() == 74 and "53199" in ports[-1]
               and ports[1].startswith("A · Port 53127"),
               "%d Eintraege: %s … %s" % (wahl.count(), ports[:2], ports[-1:]))
        _frischer_start()
        _D, z, _r = _klick(client, Kern(), verbinden=False)
        pruefe("L14 KONTROLLE: ein Kern ohne Bereich -> nur die benannten",
               z["w"]["steckplatz_wahl"].count() == 7,
               z["w"]["steckplatz_wahl"].count())
    finally:
        _frischer_start()


def zelle_wunsch_jenseits_f():
    """Ein Port jenseits von F ist waehlbar — und wird genau so genommen."""
    _frischer_start()
    halter, p_x = _belegen()
    p_frei, = _freie_ports(1)
    client = _Client([("X", p_x)])
    kern = _VerbindKern(p_frei, p_frei)             # Kennung "P<port>"
    try:
        _D, z, _r = _klick(client, kern, verbinden=False)
        wahl = z["w"]["steckplatz_wahl"]
        idx = wahl.findData("P%d" % p_frei)
        wahl.setCurrentIndex(idx)
        _klick(client, kern)
        cfg = kern.aufrufe[0][0] if kern.aufrufe else None
        pruefe("L15 gewaehlter Port jenseits von F wird genau genommen",
               idx > 0 and cfg is not None and cfg.port == p_frei,
               "Index %d, bekam %r" % (idx, getattr(cfg, "port", None)))
    finally:
        halter.close()
        kern.aufraeumen()
        _frischer_start()


def zelle_steuerung_ueber_port():
    _frischer_start()
    gerufen = []
    client = _Client([])
    client.dauer_text = lambda s: ""
    client.pausieren = lambda ziel: gerufen.append(("pause", ziel))
    for n in ("fortsetzen", "beenden_nach_auftrag", "jetzt_beenden"):
        setattr(client, n, lambda ziel, n=n: gerufen.append((n, ziel)))
    try:
        D, z = _dock_mit_zeichnen(client, _VerbindKern(1, 0))
        z["monitor_daten"] = [_status(53153, "26", "ready")]
        D._verbindungen_zeichnen(z)
        z["w"]["verb_karten"][53153]["pause"].click()
        for _ in range(50):
            if gerufen:
                break
            time.sleep(0.02)
        pruefe("L16 'Pausieren' auf Karte '26' adressiert Port 53153",
               gerufen == [("pause", "53153")], gerufen)
    finally:
        _frischer_start()


# --- Chat: Anbieter-Auswahl (2026-09-24) -----------------------------------

def _warte_qt(D, z, bedingung, frist=10.0):
    """Takt und Ereignisse laufen lassen, bis `bedingung` gilt."""
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        _APP.processEvents()
        D._chat_zeichnen(z)
        if bedingung():
            return True
        time.sleep(0.03)
    return bool(bedingung())


def _dock_sitzung(arbeitsordner, kennung, titel=None, frage="Probe",
                  antwort=None, mtime=None):
    """Eine Sitzung, wie das Dock sie anlegt (Kennzeichnung SITZUNG_NAME aus
    dem Chat-Modul, `-n` schreibt sie zuerst), im Sitzungsordner des
    Arbeitsordners unter dem aktuellen USERPROFILE. -> Pfad."""
    C = dashboard_laden()._chat_modul()
    ordner = C.projekt_ordner(arbeitsordner)
    os.makedirs(ordner, exist_ok=True)
    zeilen = [{"type": "custom-title", "customTitle": C.SITZUNG_NAME},
              {"type": "agent-name", "agentName": C.SITZUNG_NAME},
              {"type": "user", "message": {"role": "user", "content": frage}}]
    if antwort:
        zeilen.append({"type": "assistant", "message": {
            "content": [{"type": "text", "text": antwort}]}})
    if titel:
        zeilen.append({"type": "custom-title", "customTitle": titel})
    pfad = os.path.join(ordner, kennung + ".jsonl")
    with open(pfad, "w", encoding="utf-8") as fh:
        for e in zeilen:
            fh.write(json.dumps(e, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    if mtime is not None:
        os.utime(pfad, (mtime, mtime))
    return pfad


def _liste_titel(z):
    """Die Titel der bisherigen Chats im Dock (erste Zeile je Eintrag)."""
    lst = z["w"]["chat_liste"]
    return [lst.item(i).text().split("\n")[0] for i in range(lst.count())]


def zelle_chat_anbieter():
    """Anbieter wechseln, Modelle holen, starten, Karte erlauben — im echten Tab.

    Gegen die Attrappen aus test_anbieter: OpenAI-kompatibler Dienst auf
    einem ephemeren Port, MCP-Server ueber stdio, der jeden Aufruf
    protokolliert. Einstellungen in einem Temp-Ordner, Tresor unter einem
    eigenen Praefix — nichts landet im echten Profil.
    """
    import json
    import tempfile
    import test_anbieter as TA
    from PyQt6.QtWidgets import QLabel, QPushButton

    _frischer_start()
    D, z, d = aufbauen()
    w = z["w"]
    C = D._chat_modul()
    A = D._anbieter_modul()
    t = tempfile.mkdtemp(prefix="omcad_live_chat_")
    alt_praefix = A.TRESOR_PRAEFIX
    A.TRESOR_PRAEFIX = "Open MCP CAD LIVETEST %d/" % os.getpid()
    attrappe = os.path.join(t, "mcp.py")
    with open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(TA.MCP_ATTRAPPE)
    protokoll = os.path.join(t, "aufrufe.log")
    alt_server = C.server_befehl
    C.server_befehl = lambda port, dokument=None: (
        [sys.executable, attrappe, protokoll], {})
    dienst = TA.Dienst()
    _VERGEBEN.append(dienst.port)

    def gerufen():
        try:
            with open(protokoll, encoding="utf-8") as fh:
                return [json.loads(x)["name"] for x in fh if x.strip()]
        except OSError:
            return []

    try:
        # -- 1. Wechsel: die Felder folgen dem Anbieter -------------------
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData("eigen"))
        pruefe("L17 'Eigene Adresse': Adresse/Schluessel/↻ da, Denkstufe, "
               "Arbeitsordner und bisherige Chats weg",
               not w["chat_api"].isHidden() and not w["chat_modelle"].isHidden()
               and w["chat_stufe"].isHidden()
               and w["chat_ordner_teil"].isHidden()
               and w["chat_liste"].isHidden())
        pruefe("L17 die Eingabe nennt den Anbieter",
               w["chat_eingabe"].placeholderText().startswith("Eigene Adresse"),
               w["chat_eingabe"].placeholderText())
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData("codex"))
        pruefe("L17 Codex: keine Adresse, kein Schluessel, Hinweis zur Anmeldung",
               not w["chat_api"].isHidden() and w["chat_basis"].isHidden()
               and w["chat_schluessel"].isHidden()
               and "Codex-App" in w["chat_schluessel_lage"].text()
               and "Standardmodell" in w["chat_modell"].lineEdit().placeholderText(),
               w["chat_schluessel_lage"].text())
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData("claude"))
        pruefe("L17 KONTROLLE: zurueck zu Claude Code — umgekehrt, Kurznamen",
               w["chat_api"].isHidden() and not w["chat_stufe"].isHidden()
               and w["chat_modell"].findData("sonnet") >= 0)
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData("eigen"))
        with open(os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"],
                  encoding="utf-8") as fh:
            gemerkt = json.load(fh).get("anbieter")
        pruefe("L17 die Wahl wird gemerkt (ohne Schluessel)", gemerkt == "eigen",
               gemerkt)

        # -- 2. Modelle vom Dienst ----------------------------------------
        # Rueckmeldung 2026-09-25: ohne Liste muss der Knopf auffallen, und
        # das Dropdown muss selbst zur Abfrage fuehren.
        w["chat_basis"].setText(dienst.basis)
        feld_m = w["chat_modell"]

        def eintraege():
            return [feld_m.itemText(i) for i in range(feld_m.count())]

        pruefe("L18a ohne Liste: Knopf hervorgehoben mit Text",
               w["chat_modelle"].objectName() == "hinweis"
               and w["chat_modelle"].text() == D.MODELLE_KNOPF_OFFEN,
               "%s / %s" % (w["chat_modelle"].objectName(),
                            w["chat_modelle"].text()))
        pruefe("L18a ohne Liste: das Dropdown bietet die Abfrage an",
               eintraege() == [D.MODELLE_EINTRAG], eintraege())
        feld_m.setEditText("mein-modell")
        pruefe("L18a der Abfrage-Eintrag ist nie das gewaehlte Modell",
               D._modellwahl(feld_m) == "mein-modell"
               and (feld_m.setEditText(D.MODELLE_EINTRAG)
                    or D._modellwahl(feld_m) is None))
        feld_m.setEditText("mein-modell")
        # Der Eintrag im Dropdown startet die Abfrage (wie ein Klick).
        feld_m.activated.emit(feld_m.findData(D.MODELLE_ABFRAGEN))
        _warte_qt(D, z, lambda: feld_m.count() == 4)
        pruefe("L18 der Dropdown-Eintrag holt die Modelle des Dienstes",
               eintraege() == ["alpha-chat", "text-embedding-3-large",
                               "zeta-chat", D.MODELLE_EINTRAG],
               w["chat_schluessel_lage"].text())
        pruefe("L18 der getippte Name bleibt stehen",
               feld_m.currentText() == "mein-modell", feld_m.currentText())
        pruefe("L18b mit aktueller Liste: kleiner ↻-Knopf",
               w["chat_modelle"].objectName() == "symbol"
               and w["chat_modelle"].text() == "↻",
               w["chat_modelle"].objectName())
        w["chat_basis"].setText(dienst.basis + "/")
        pruefe("L18b-K andere Adresse: Liste gilt als veraltet, Knopf wieder "
               "hervorgehoben", w["chat_modelle"].objectName() == "hinweis")
        w["chat_basis"].setText(dienst.basis)
        pruefe("L18b-K zurueck zur abgefragten Adresse: wieder aktuell",
               w["chat_modelle"].objectName() == "symbol")
        # Seit S6 haengt die Liste am GESPEICHERTEN Schluessel: Tippen
        # allein aendert nichts, erst «Speichern» macht sie alt. Der Tresor
        # ist hier eine Attrappe (nichts im echten Windows-Tresor).
        tresor = _TresorAttrappe(A).__enter__()
        try:
            w["chat_schluessel"].setText("sk-neu")
            pruefe("L18b-K nur getippt, nicht gespeichert: die Liste gilt "
                   "weiter", w["chat_modelle"].objectName() == "symbol")
            w["chat_schluessel_speichern"].click()
            pruefe("L18b-K neuer Schluessel gespeichert: veraltet, Feld leer",
                   w["chat_modelle"].objectName() == "hinweis"
                   and w["chat_schluessel"].text() == ""
                   and tresor.daten.get("eigen") == "sk-neu", tresor.daten)
            D._modelle_abfragen(z)
            _warte_qt(D, z, lambda: w["chat_modelle"].isEnabled())
            pruefe("L18b die Abfrage liest den gespeicherten Schluessel, und "
                   "zwar im Nebenthread", tresor.gelesen
                   and all(t != "MainThread" for _k, t in tresor.gelesen),
                   tresor.gelesen)
            w["chat_schluessel_entfernen"].click()
            w["chat_schluessel_entfernen"].click()
        finally:
            tresor.__exit__()
        D._modelle_abfragen(z)
        _warte_qt(D, z, lambda: w["chat_modelle"].isEnabled())
        pruefe("L18 erneute Abfrage ueber den Knopf: wieder aktuell",
               w["chat_modelle"].objectName() == "symbol")

        # -- 3. Die erste Nachricht startet (S8), Karte --------------------
        # Bis S8 hiess das: "Starten" druecken, dann senden. Jetzt gibt es
        # keinen Start-Knopf mehr; L60 prueft, dass der alte Weg (Senden
        # ohne laufenden Chat tut nichts) hier rot wuerde.
        w["chat_modell"].setEditText("alpha-chat")
        dienst.drehbuch[:] = [
            (200, TA.aufruf_antwort("execute_cadwork_command", {"code": "z = 3"})),
            (200, TA.text_antwort("Gezeichnet."))]
        chat = z["chat"]
        # KONTROLLE zuerst: nicht verbunden -> kein Start, der Text bleibt
        # stehen, die Zeile an der Eingabe sagt "Zuerst verbinden".
        z["dienst"].beenden = True
        rest = _senden_klick(D, z, "zeichne etwas")
        pruefe("L19 KONTROLLE: nicht verbunden -> kein Start, Text bleibt, "
               "Hinweis 'Zuerst verbinden' an der Eingabe",
               not chat.get("an") and rest == "zeichne etwas"
               and _meldung(z).startswith("Zuerst verbinden"),
               (chat.get("an"), rest, _meldung(z)))
        z["dienst"].beenden = False
        D._chat_zeichnen(z)
        pruefe("L19 wieder verbunden: der Hinweis 'Zuerst verbinden' geht "
               "von selbst", _meldung(z) == "", _meldung(z))
        w["chat_senden"].click()                   # derselbe Text, jetzt
        _warte_qt(D, z, lambda: chat.get("werkzeuge_da"))
        pruefe("L19 Senden startet den Chat ueber die Schleife, mit "
               "Werkzeugen, das Feld ist leer",
               chat.get("an") and chat.get("schleife") is not None
               and chat.get("werkzeuge_da") and not w["chat_anbieter"].isEnabled()
               and w["chat_eingabe"].toPlainText() == "",
               w["chat_lage"].text())
        # Daran haengt die Kostenanzeige (L40): kein Abo, Betrag wie bisher.
        pruefe("L19 der Start merkt den Anbieter fuer die Anzeige",
               chat.get("anbieter") == "eigen" and not D._chat_im_abo(chat),
               chat.get("anbieter"))
        _warte_qt(D, z, lambda: C.offene_freigaben(chat)
                  and not w["chat_freigabe"].isHidden())
        titel = [l.text() for l in w["chat_freigabe"].findChildren(QLabel)]
        pruefe("L19 die Karte kommt, nennt den Anbieter und zeigt den Code",
               any("Eigene Adresse möchte" in x for x in titel)
               and any("z = 3" in x for x in titel), titel)
        pruefe("L19 KONTROLLE: vor dem Klick ist NICHTS ausgefuehrt",
               gerufen() == [], gerufen())
        ja = [b for b in w["chat_freigabe"].findChildren(QPushButton)
              if b.text() == "Erlauben"]
        if ja:
            ja[0].click()
        _warte_qt(D, z, lambda: any(e["art"] == "schluss"
                                    for e in chat.get("ereignisse") or ()))
        _warte_qt(D, z, lambda: w["chat_verlauf"].count() >= 3
                  and _fuss(z), 2)
        zeilen = _verlauf_texte(z)
        fuss = _fuss(z)
        pruefe("L19 nach 'Erlauben' ausgefuehrt, Antwort im Verlauf, Token "
               "im Tooltip der Antwort (keine Zeile '— fertig')",
               gerufen() == ["execute_cadwork_command"]
               and "Gezeichnet." in zeilen
               and not any("fertig" in x for x in zeilen)
               and fuss.startswith("fertig") and "18 Token" in fuss,
               (zeilen, fuss))

        pruefe("L19 die erste Nachricht steht genau einmal im Verlauf",
               zeilen.count("Du:  zeichne etwas") == 1, zeilen)

        # -- 4. Beenden ----------------------------------------------------
        pruefe("L19 'Beenden' steht da, solange der Chat laeuft",
               not w["chat_ende"].isHidden())
        vorher = _verlauf_texte(z)
        w["chat_ende"].click()
        pruefe("L19 Beenden raeumt die Schleife ab",
               _warte_qt(D, z, lambda: not chat.get("an")))
        pruefe("L19 danach kein 'Beenden' mehr, der Verlauf bleibt lesbar",
               w["chat_ende"].isHidden()
               and _verlauf_texte(z)[:len(vorher)] == vorher
               and "Gezeichnet." in vorher, (vorher, _verlauf_texte(z)))
    finally:
        C.server_befehl = alt_server
        A.schluessel_loeschen("eigen")
        A.TRESOR_PRAEFIX = alt_praefix
        dienst.server.shutdown()
        _frischer_start()


# --- Robustheit des Docks (2026-09-25) --------------------------------------

def zelle_fehler_bleibt():
    """Befund 2026-09-25: eine Meldung des Docks ("Chat startet nicht: …")
    verschwand nach hoechstens 0,5 s — `_auffrischen` blendete die Zeile in
    jedem Takt aus, sobald der Kern selbst nichts meldete."""
    _frischer_start()
    D, z, d = aufbauen()
    try:
        D._auffrischen(z)
        D._fehler_zeigen(z, "Chat startet nicht: Probe-Grund")
        for _ in range(8):                        # acht Takte
            time.sleep(0.05)
            D._auffrischen(z)
        pruefe("L22 verbunden: die Meldung des Docks ueberlebt acht Takte",
               "Probe-Grund" in _hinweis(z), repr(_hinweis(z)))
        d.status = lambda: dict(Dienst.status(d), hinweis="Pausiert - Probe")
        D._auffrischen(z)
        beide = _hinweis(z)
        pruefe("L22 meldet der Kern etwas dazu, stehen beide da",
               "Probe-Grund" in beide and "Pausiert - Probe" in beide,
               repr(beide))
        # KONTROLLE: ist die Frist um, gilt das alte Verhalten — der Takt
        # ersetzt die Meldung durch den Kernhinweis und blendet dann aus.
        z["fehler_bis"] = time.monotonic() - 1.0
        D._auffrischen(z)
        nur_kern = _hinweis(z)
        del d.status
        D._auffrischen(z)
        pruefe("L22 KONTROLLE: Frist um -> nur der Kernhinweis, dann leer",
               nur_kern == "Pausiert - Probe" and _hinweis(z) == "",
               "%r / %r" % (nur_kern, _hinweis(z)))
        D._fehler_zeigen(z, "Chat startet nicht: Probe-Grund")
        D._primaer_geklickt(z)                   # der Nutzer trennt
        pruefe("L22 der Nutzer handelt (Trennen): die Meldung geht sofort",
               d.beenden and _hinweis(z) == "", repr(_hinweis(z)))
    finally:
        _frischer_start()


def zelle_chat_lage_verbinden():
    """Befund 2026-09-25: nach dem Verbinden blieb im Chat-Tab "Zuerst
    verbinden" stehen. Gezeichnet wurde nur, wenn sich `chat["stand"]`
    aenderte — und Verbinden aendert ihn nicht."""
    _frischer_start()
    D, z, _r = _klick(_Client([]), _VerbindKern(1, 0), verbinden=False)

    def lage():
        return z["w"]["chat_lage"].text()

    try:
        D._auffrischen(z)
        vorher = lage()
        z["dienst"] = Dienst()
        D._auffrischen(z)
        danach = lage()
        pruefe("L23 nach dem Verbinden 'bereit' statt 'Zuerst verbinden'",
               vorher.startswith("Zuerst verbinden")
               and danach.startswith("bereit"),
               "%r -> %r" % (vorher[:30], danach[:30]))
        z["dienst"].beenden = True
        D._auffrischen(z)
        pruefe("L23 nach dem Trennen wieder 'Zuerst verbinden'",
               lage().startswith("Zuerst verbinden"), lage()[:40])
        # KONTROLLE: der alte Stand (nur chat["stand"]) laesst nach dem
        # Verbinden "Zuerst verbinden" stehen — genau der Befund.
        D._chat_zeichenstand = (lambda chat, verbunden, an, veraltet:
                                chat.get("stand", 0))
        z["chat_gezeigt"] = -1
        D._auffrischen(z)
        z["dienst"] = Dienst()
        D._auffrischen(z)
        pruefe("L23 KONTROLLE: nur chat['stand'] -> 'Zuerst verbinden' bleibt",
               lage().startswith("Zuerst verbinden"), lage()[:40])
    finally:
        _frischer_start()


def _dock_loeschen_lauf(alter_weg=False):
    """Dock bauen, Chat mit Verlauf, Cadwork LOESCHT das Dock, Plugin-Klick.

    `alter_weg=True` stellt den Weg vor 2026-09-25 nach: Timer nur, wenn
    `chat_takt` None war; beim Neubau nur `dock = None`; `chat_gezeigt`
    nie zurueckgesetzt. -> dict mit den Messwerten.
    """
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent, QTimer
    from PyQt6.QtWidgets import QApplication
    _frischer_start()
    D, z, _r = _klick(_Client([]), _VerbindKern(1, 0), verbinden=False)
    if alter_weg:
        def alt_takt(zz, eltern):
            if zz.get("chat_takt") is None:
                t = QTimer(eltern)
                t.setInterval(100)
                t.timeout.connect(lambda: D._sicher(
                    lambda: D._chat_zeichnen(zz)))
                t.start()
                zz["chat_takt"] = t
        echt_tab = D._tab_chat_oder_ersatz
        gemerkt = {}

        def alt_tab(zz, register):
            zz["chat_gezeigt"] = gemerkt["stand"]     # nie zurueckgesetzt
            echt_tab(zz, register)
        D._chat_takt_starten = alt_takt
        D._dock_abbauen = lambda zz: (zz.__setitem__("dock", None),
                                      zz.__setitem__("fenster", None))
        D._tab_chat_oder_ersatz = alt_tab
    z["dienst"] = Dienst()
    z["chat"].update(stand=3, ereignisse=[{"art": "ich", "text": "Hallo"},
                                          {"art": "text", "text": "Antwort"}])
    D._auffrischen(z)
    m = {"vorher": z["w"]["chat_verlauf"].count()}
    if alter_weg:
        gemerkt["stand"] = z["chat_gezeigt"]
    alter_takt, altes_dock = z["chat_takt"], z["dock"]
    # Cadwork raeumt ab — seit K12 liegt der Chat wieder IM (einen)
    # Fenster; mit ihm geht sein Takt.
    altes_dock.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    m["alt_tot"] = sip.isdeleted(altes_dock) and sip.isdeleted(alter_takt)
    D.oeffnen(z["kern_laden"], z["cfg_bauen"])  # der naechste Plugin-Klick
    m["neues_dock"] = z["dock"] is not None and not sip.isdeleted(z["dock"])
    m["gleich_danach"] = z["w"]["chat_verlauf"].count()
    # Was NACH dem frueh-return gezeichnet wird (die Lage-Zeile): haengt an
    # `chat_gezeigt`. Der Verlauf hat seit K5 seine eigene Marke.
    m["lage"] = z["w"]["chat_lage"].text()
    # Ab hier darf NUR der Chat-Takt zeichnen: der 500-ms-Takt steht.
    z["timer"].stop()
    z["chat"]["ereignisse"].append({"art": "text", "text": "Nachtrag"})
    z["chat"]["stand"] = 4
    ende = time.monotonic() + 1.0
    while (time.monotonic() < ende
           and z["w"]["chat_verlauf"].count() < 3):
        QApplication.processEvents()
        time.sleep(0.02)
    takt = z.get("chat_takt")
    m["takt_lebt"] = (takt is not None and not sip.isdeleted(takt)
                      and takt.isActive())
    m["ende"] = z["w"]["chat_verlauf"].count()
    _frischer_start()
    return m


def zelle_dock_geloescht():
    """Loescht Cadwork das Dock, baut der naechste Klick ein neues — mit
    lebendem Chat-Takt und gezeichnetem Verlauf. Vorher blieb ein toter
    Timer in `chat_takt` stehen, und `chat_gezeigt` hielt den Verlauf leer."""
    m = _dock_loeschen_lauf()
    pruefe("L24 Vorbedingung: Verlauf gezeichnet, altes Dock samt Takt tot",
           m["vorher"] == 2 and m["alt_tot"], m)
    pruefe("L24 der Klick baut ein neues Dock, Verlauf und Lage stehen "
           "sofort da", m["neues_dock"] and m["gleich_danach"] == 2
           and m["lage"].startswith("bereit"), m)
    pruefe("L24 der neue Chat-Takt lebt und zeichnet von selbst (100 ms)",
           m["takt_lebt"] and m["ende"] == 3, m)
    k = _dock_loeschen_lauf(alter_weg=True)
    pruefe("L24 KONTROLLE: der alte Weg — toter Takt (der Nachtrag kommt "
           "nie), die Lage nie gezeichnet", k["vorher"] == 2 and k["alt_tot"]
           and not k["takt_lebt"] and not k["lage"].startswith("bereit")
           and k["ende"] == k["gleich_danach"], k)


def zelle_form_neubau():
    """Update ohne Cadwork-Neustart: ein Dock einer ANDEREN Fassung wird neu
    gebaut; Dienst und Chat bleiben. Vorher griff der neue Code in das alte
    Dock, fand einen Teil nicht (KeyError) — und der Einstieg meldete
    "Dashboard nicht möglich — NICHT verbunden"."""
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    _frischer_start()
    p_y, = _freie_ports(1)
    client = _Client([("Y", p_y)])
    kern = _VerbindKern(1, 0)
    try:
        D, z, _r = _klick(client, kern, verbinden=False)
        pruefe("L25 das Dock traegt seine Form", z.get("form") == D.FORM,
               z.get("form"))
        dienst, chat = Dienst(), z["chat"]
        z["dienst"] = dienst
        alt = z["dock"]
        # So sieht ein Dock einer aelteren Fassung aus: andere Form, und ein
        # Teil, den die neue Fassung anfasst, fehlt.
        z["form"] = 1
        del z["w"]["btn_undo"]
        try:
            D2, z2, rueck = _klick(client, kern, verbinden=True)
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen, z2, rueck = exc, None, None
        pruefe("L25 Klick auf ein Dock alter Form: kein Fehler, neu gebaut",
               geworfen is None and z2 is z and z["dock"] is not alt
               and z["form"] == D.FORM and "btn_undo" in z["w"],
               repr(geworfen))
        pruefe("L25 Dienst und Chat bleiben dieselben, kein zweiter Start",
               z["dienst"] is dienst and rueck is dienst
               and z["chat"] is chat and kern.aufrufe == [],
               "%d serve()-Aufrufe" % len(kern.aufrufe))
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pruefe("L25 das alte Dock ist abgeraeumt", sip.isdeleted(alt))
        # KONTROLLE 1: gleiche Form -> dasselbe Dock (kein Neubau je Klick).
        gleich = z["dock"]
        _klick(client, kern, verbinden=True)
        pruefe("L25 KONTROLLE: gleiche Form -> dasselbe Dock",
               z["dock"] is gleich)
        # KONTROLLE 2: ohne Formwechsel faellt der fehlende Teil als
        # KeyError aus oeffnen() — der alte Fehler, der den Einstieg traf.
        del z["w"]["btn_undo"]
        try:
            _klick(client, kern, verbinden=True)
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen = exc
        pruefe("L25 KONTROLLE: gleiche Form, fehlender Teil -> KeyError",
               isinstance(geworfen, KeyError), repr(geworfen))
    finally:
        kern.aufraeumen()
        _frischer_start()


def zelle_schnittstelle():
    """Chat und Anbieter bleiben bis zum Cadwork-Neustart im Speicher. Passt
    ihre Fassung nicht, startet kein Chat, und das Dock sagt warum."""
    import types
    from PyQt6.QtWidgets import QTabWidget
    name_c, name_a = "omcad_a_chat_A", "omcad_a_anbieter_A"
    _frischer_start()
    D, z, d = aufbauen()
    w = z["w"]
    echt_c, echt_a = sys.modules[name_c], sys.modules[name_a]
    alt_projekt = os.environ.get("OPEN_MCP_CAD_PROJEKT")
    os.environ["OPEN_MCP_CAD_PROJEKT"] = _tempfile.mkdtemp(
        prefix="omcad_live_projekt_")
    gestartet = []

    def kopie(echt, **ueber):
        m = types.ModuleType(echt.__name__)
        m.__dict__.update(echt.__dict__)
        m.__dict__.update(ueber)
        return m

    # Die Seiten eines heilen Fensters (K12: Chat, Briefkasten,
    # Einstellungen) — gemessen, keine Liste im Test.
    normal = w["seiten"].count()
    try:
        pruefe("L26 frisch von der Platte passen Chat und Anbieter",
               D._chat_veraltet() is None, D._chat_veraltet())
        w["chat_anbieter"].setCurrentIndex(
            w["chat_anbieter"].findData("claude"))
        def starten(chat, *a, **k):
            gestartet.append(k)
            chat.update(an=True, ereignisse=[], freigaben=[], schleife=None,
                        proc=_ProzessAttrappe(), schloss=threading.Lock())
        alt_c = kopie(echt_c, starten=starten)
        del alt_c.SCHNITTSTELLE              # so sieht jede Fassung vor heute aus
        sys.modules[name_c] = alt_c
        D._chat_zeichnen(z)
        # Der Senden-Knopf ist dann aus; Enter im Feld geht weiter — und
        # sagt, warum nichts startet (S8: Senden startet den Chat).
        rest = _enter(D, z)
        D._chat_zeichnen(z)
        pruefe("L26 alte Chat-Fassung im Speicher: kein Start, klare Meldung "
               "an der Eingabe, der Text bleibt",
               gestartet == [] and "Cadwork neu starten" in _meldung(z)
               and rest == "Probe-Nachricht", repr((_meldung(z), rest)))
        pruefe("L26 der Chat-Tab sagt es auch, Senden ist aus",
               "Cadwork neu starten" in w["chat_lage"].text()
               and not w["chat_senden"].isEnabled(), w["chat_lage"].text())
        # KONTROLLE: dieselbe Kopie MIT passender Fassung startet — gebremst
        # hat oben also die Fassung, nicht etwas anderes.
        alt_c.SCHNITTSTELLE = echt_c.SCHNITTSTELLE
        D._chat_zeichnen(z)
        rest = _senden_klick(D, z)
        D._chat_zeichnen(z)
        pruefe("L26 KONTROLLE: passende Fassung -> der Start geht durch",
               len(gestartet) == 1 and w["chat_senden"].isEnabled()
               and "neu starten" not in w["chat_lage"].text() and rest == "",
               "%d Starts, %r" % (len(gestartet), w["chat_lage"].text()))
        sys.modules[name_c] = echt_c
        sys.modules[name_a] = kopie(echt_a,
                                    SCHNITTSTELLE=echt_a.SCHNITTSTELLE + 1)
        pruefe("L26 eine andere Anbieter-Fassung wird ebenso erkannt",
               D._chat_veraltet() == D.CHAT_VERALTET, D._chat_veraltet())

        # Ein Anbieter-Modul, mit dem der Tab gar nicht baubar ist (es fehlt
        # etwas, das der Tab NACH addTab braucht): das Dock kommt trotzdem.
        kaputt = kopie(echt_a)
        del kaputt.SCHNITTSTELLE, kaputt.einstellungen_lesen
        sys.modules[name_a] = kaputt
        _frischer_start()
        import io
        alt_err, puffer = sys.stderr, io.StringIO()
        sys.stderr = puffer
        try:
            D3, z3, _r = _klick(_Client([]), _VerbindKern(1, 0),
                                verbinden=False)
        finally:
            sys.stderr = alt_err
        ersatz = z3["w"].get("chat_ersatz")
        stapel = z3["w"].get("seiten")
        pruefe("L26 Chat nicht baubar: das Fenster steht mit denselben "
               "Seiten — an der Stelle des Chats EINE Seite mit dem Grund, "
               "Briefkasten und Einstellungen wie sonst",
               z3["fenster"] is not None and ersatz is not None
               and "Cadwork neu starten" in ersatz.text()
               and D3.CHAT_TAB not in z3["w"] and stapel is not None
               and stapel.count() == normal
               and stapel.widget(0).isAncestorOf(ersatz)
               and stapel.widget(1) is z3["w"]["briefkasten_seite"]
               and stapel.widget(2) is z3["w"]["einst_seite"],
               (normal, stapel.count() if stapel else None))
        # Die halb gebaute Karte "Chat" auf der Einstellungsseite ist weg —
        # sonst stuenden dort Felder, die zu keinem Tab mehr gehoeren.
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        platz = z3["w"]["einst_chat_lay"]
        platz_t = z3["w"]["einst_technik_lay"]
        pruefe("L26 ... und auf der Einstellungsseite bleibt keine halbe "
               "Chat-Karte stehen (auch nicht in den Technik-Details)",
               platz.count() == 0 and platz_t.count() == 0
               and "chat_einst_karte" not in z3["w"],
               (platz.count(), platz_t.count()))
        pruefe("L26 ... und der Anlass steht auf stderr",
               "Chat-Tab bauen: AttributeError" in puffer.getvalue()
               and "einstellungen_lesen" in puffer.getvalue(),
               puffer.getvalue()[:120])
        z3["dienst"] = Dienst()
        try:
            D3._auffrischen(z3)
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen = exc
        pruefe("L26 ... und der Takt laeuft mit dem Ersatz-Tab",
               geworfen is None, repr(geworfen))
        try:
            D3._tab_chat(z3, QTabWidget())
            geworfen = None
        except Exception as exc:                      # noqa: BLE001
            geworfen = exc
        pruefe("L26 KONTROLLE: mit diesem Modul scheitert _tab_chat selbst",
               isinstance(geworfen, AttributeError), repr(geworfen))
        # KONTROLLE fuer die Karte: ohne das Abraeumen in
        # `_tab_chat_oder_ersatz` bleibt sie auf der Einstellungsseite.
        M = _mutant(_anweisungen(
            "_tab_chat_oder_ersatz",
            lambda s: (isinstance(s, ast.If)
                       and ast.unparse(s.test) == "einst is not None")))
        _frischer_start()
        sys.stderr = io.StringIO()
        try:
            _Dm, zm, _r = _klick(_Client([]), _VerbindKern(1, 0),
                                 verbinden=False, laden=lambda: M)
        finally:
            sys.stderr = alt_err
        QApplication.processEvents()
        pruefe("L26 KONTROLLE: ohne das Abraeumen bleibt die halbe Karte "
               "auf der Einstellungsseite stehen",
               M._mutant_treffer == [1]
               # zwei halbe Karten: "Chat" und (seit 2026-09-28) "Technik-
               # Details" (seit K12 in deren Abschnitt)
               and zm["w"]["einst_chat_lay"].count()
               + zm["w"]["einst_technik_lay"].count() == 2,
               (M._mutant_treffer, zm["w"]["einst_chat_lay"].count(),
                zm["w"]["einst_technik_lay"].count()))
    finally:
        sys.modules[name_c], sys.modules[name_a] = echt_c, echt_a
        if alt_projekt is None:
            os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        else:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = alt_projekt
        _frischer_start()


def zelle_takt_fehler():
    """Bis 2026-09-25 schluckten `_sicher` und die try-Bloecke in
    `_auffrischen` jede Ausnahme wortlos. Jetzt: einmal je Wortlaut auf
    stderr, und der Takt laeuft weiter."""
    import io
    from PyQt6.QtWidgets import QApplication
    _frischer_start()
    D, z, d = aufbauen()
    alt_err, puffer = sys.stderr, io.StringIO()
    sys.stderr = puffer

    def berichte(wo):
        return puffer.getvalue().count("Fehler im Takt (%s:" % wo)

    def wirft(exc):
        def fn(*_a):
            raise exc
        return fn

    try:
        for _ in range(5):
            D._sicher(wirft(ValueError("Probe A")), "Probe")
        pruefe("L27 ein Fehler im Takt steht auf stderr, EINMAL fuer 5 Takte",
               berichte("Probe") == 1 and "Probe A" in puffer.getvalue()
               and "Traceback" in puffer.getvalue(),
               puffer.getvalue()[-200:])
        D._sicher(wirft(ValueError("Probe B")), "Probe")
        pruefe("L27 KONTROLLE: ein ANDERER Wortlaut kommt eigens dazu",
               berichte("Probe") == 2, "%d Meldungen" % berichte("Probe"))

        # Der echte Chat-Takt: _chat_zeichnen wirft in jedem Takt.
        z["timer"].stop()
        takte = []

        def zeichnen_kaputt(_z):
            takte.append(1)
            raise KeyError("probe_teil")
        echt = D._chat_zeichnen
        D._chat_zeichnen = zeichnen_kaputt
        ende = time.monotonic() + 0.6
        while time.monotonic() < ende:
            QApplication.processEvents()
            time.sleep(0.02)
        D._chat_zeichnen = echt
        pruefe("L27 der Chat-Takt laeuft trotz Fehler weiter, gemeldet einmal",
               len(takte) >= 3 and z["chat_takt"].isActive()
               and berichte("Chat zeichnen") == 1,
               "%d Takte, %d Meldungen" % (len(takte),
                                           berichte("Chat zeichnen")))

        # Der 500-ms-Takt: eine Ausnahme in _auffrischen verlaesst den Slot
        # nicht (unbehandelt riefe PyQt dort qFatal).
        d.status = wirft(RuntimeError("Probe Status"))
        z["timer"].timeout.emit()
        z["timer"].timeout.emit()
        del d.status
        pruefe("L27 eine Ausnahme im 500-ms-Takt bleibt im Slot, einmal gemeldet",
               berichte("Auffrischen") == 1 and "Probe Status" in
               puffer.getvalue(), "%d Meldungen" % berichte("Auffrischen"))
    finally:
        sys.stderr = alt_err
        _frischer_start()


# --- Mutanten fuer Kontrollzellen (2026-09-25) ------------------------------
# Die staerkste Kontrolle baut GENAU den Fehler ein, den die Zelle finden
# soll, und verlangt, dass sie dann rot wird. `_mutant` laedt das Dashboard
# aus seiner QUELLE, veraendert vorher den Syntaxbaum und merkt sich, wie oft
# jede Mutation traf. Trifft eine nichts (der Code wurde umgebaut), steht 0 in
# `_mutant_treffer`, und die Kontrollzelle wird rot — sie prueft nie still
# das Original.

def _funktion(baum, name):
    for k in baum.body:
        if isinstance(k, ast.FunctionDef) and k.name == name:
            return k
    return None


def _ist_aufruf(s, name):
    return (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Name) and s.value.func.id == name)


def _ist_zuweisung(s, *namen):
    return isinstance(s, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in namen for t in s.targets)


def _ist_ersatz_return(s):
    """`if CHAT_TAB not in w: return` — der Ersatz-Return in _chat_zeichnen
    (bis S8 hiess die Marke "chat_start", der Knopf "Starten")."""
    return (isinstance(s, ast.If)
            and any(isinstance(b, ast.Return) for b in s.body)
            and any(isinstance(k, ast.Name) and k.id == "CHAT_TAB"
                    for k in ast.walk(s.test)))


def _ohne_aufruf(funktion, aufruf):
    """Mutation: jede Anweisung `aufruf(...)` in `funktion` streichen."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for knoten in (ast.walk(f) if f is not None else ()):
            for feld in ("body", "orelse", "finalbody"):
                liste = getattr(knoten, feld, None)
                if not isinstance(liste, list):
                    continue
                neu = [s for s in liste if not _ist_aufruf(s, aufruf)]
                n += len(liste) - len(neu)
                liste[:] = neu or [ast.Pass()]
        return n
    return mutation


def _melden_stumm(funktion, wo):
    """Mutation: `_melden(wo, exc)` in einem except von `funktion` -> `pass`."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for h in (ast.walk(f) if f is not None else ()):
            if not isinstance(h, ast.ExceptHandler):
                continue
            for i, s in enumerate(h.body):
                if (_ist_aufruf(s, "_melden") and s.value.args
                        and isinstance(s.value.args[0], ast.Constant)
                        and s.value.args[0].value == wo):
                    h.body[i] = ast.Pass()
                    n += 1
        return n
    return mutation


def _verschieben(funktion, was, hinter):
    """Mutation: die Anweisungen `was` im Rumpf von `funktion` hinter die
    erste Anweisung `hinter` setzen (die Reihenfolge von frueher)."""
    def mutation(baum):
        f = _funktion(baum, funktion)
        if f is None:
            return 0
        bewegt = [s for s in f.body if was(s)]
        rest = [s for s in f.body if not was(s)]
        ziel = next((i for i, s in enumerate(rest) if hinter(s)), None)
        if not bewegt or ziel is None:
            return 0
        neu = rest[:ziel + 1] + bewegt + rest[ziel + 1:]
        if [id(s) for s in neu] == [id(s) for s in f.body]:
            return 0                              # stand schon so
        f.body[:] = neu
        return len(bewegt)
    return mutation


def _anweisungen(funktion, erkennen, neu=None):
    """Mutation: jede Anweisung in `funktion`, fuer die `erkennen(s)` gilt,
    durch den Quelltext `neu` ersetzen — oder, mit `neu=None`, streichen."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for knoten in (list(ast.walk(f)) if f is not None else ()):
            for feld in ("body", "orelse", "finalbody"):
                liste = getattr(knoten, feld, None)
                if not isinstance(liste, list):
                    continue
                ergebnis = []
                for s in liste:
                    if isinstance(s, ast.stmt) and erkennen(s):
                        n += 1
                        if neu is not None:
                            ergebnis.extend(ast.parse(neu).body)
                    else:
                        ergebnis.append(s)
                # Leere Listen bleiben leer: ein `orelse` mit `pass` an einem
                # try/finally ohne except waere kein gueltiger Baum mehr.
                if liste:
                    liste[:] = ergebnis or [ast.Pass()]
        return n
    return mutation


def _beginnt(anfang):
    """Erkennt eine einfache Anweisung am Anfang ihres Quelltexts."""
    return lambda s: (isinstance(s, (ast.Expr, ast.Assign))
                      and ast.unparse(s).startswith(anfang))


def _mutant(*mutationen):
    """Das Dashboard aus der Quelle, mit `mutationen` veraendert.

    `m._mutant_treffer` zaehlt je Mutation die Treffer."""
    pfad = os.path.join(A, "omcad_a_dashboard.py")
    with open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read(), pfad)
    treffer = [mutation(baum) for mutation in mutationen]
    ast.fix_missing_locations(baum)
    m = types.ModuleType("a_dash_mutant")
    m.__file__ = pfad
    sys.modules[m.__name__] = m
    exec(compile(baum, pfad, "exec"), m.__dict__)
    m._mutant_treffer = treffer
    return m


class _TresorAttrappe:
    """Der Windows-Tresor im Speicher: das Anbieter-Modul liest und schreibt
    hier statt im echten Tresor. `gelesen` merkt je Lesen (Kennung, Name
    des Threads) — so laesst sich zeigen, dass der Qt-Thread nie liest."""

    def __init__(self, A, daten=None):
        self.A, self.daten, self.gelesen = A, dict(daten or {}), []

    def __enter__(self):
        A = self.A
        self.alt = (A.schluessel_speichern, A.schluessel_lesen,
                    A.schluessel_loeschen)

        def speichern(kennung, wert, praefix=None):
            self.daten[kennung] = wert.strip()

        def lesen(kennung, praefix=None):
            self.gelesen.append((kennung, threading.current_thread().name))
            return self.daten.get(kennung)

        def loeschen(kennung, praefix=None):
            return self.daten.pop(kennung, None) is not None
        A.schluessel_speichern, A.schluessel_lesen = speichern, lesen
        A.schluessel_loeschen = loeschen
        return self

    def __exit__(self, *_):
        (self.A.schluessel_speichern, self.A.schluessel_lesen,
         self.A.schluessel_loeschen) = self.alt


class _ProzessAttrappe:
    """Ein lebendes CLI fuer `C._schicken`: `poll()` None, `stdin` schreibt
    mit (`zeilen`). `tot = True` laesst es sterben (Senden scheitert)."""

    def __init__(self):
        self.tot, self.zeilen = False, []
        attrappe = self

        class _Ein:
            def write(self, text):
                if attrappe.tot:
                    raise OSError("Leitung zu")
                attrappe.zeilen.append(text)

            def flush(self):
                pass
        self.stdin = _Ein()

    def poll(self):
        return 1 if self.tot else None


class _ChatStartAttrappe:
    """Der Chat im Speicher, dessen `starten` wirft, solange `fehler` etwas
    enthaelt. Anbieter Claude Code, Projektordner in Temp (`projekt`: ein
    Pfad, oder None = OPEN_MCP_CAD_PROJEKT NICHT gesetzt). Stellt alles
    zurueck (`with`). `ordner` schreibt den Arbeitsordner je Start mit."""
    NAME = "omcad_a_chat_A"

    def __init__(self, D, z, projekt=True):
        self.D, self.z, self.projekt = D, z, projekt
        self.gestartet, self.fehler, self.ordner = [], [], []

    def __enter__(self):
        self.echt = self.D._chat_modul()
        self.alt_projekt = os.environ.get("OPEN_MCP_CAD_PROJEKT")
        if self.projekt is True:
            self.projekt = _tempfile.mkdtemp(prefix="omcad_live_projekt_")
        if self.projekt is None:
            os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        else:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = self.projekt

        def starten(chat, *a, **k):
            if self.fehler:
                raise RuntimeError(self.fehler[0])
            self.gestartet.append(k)
            self.ordner.append(a[0] if a else None)
            # So viel Chat, wie `senden` danach braucht (S8: die erste
            # Nachricht startet und wird gleich gesendet). Seit 2026-09-28
            # mit einem lebenden Prozess (Attrappe): ein Senden an KEINEN
            # Prozess laesst den Text jetzt im Feld (L74).
            self.proc = _ProzessAttrappe()
            chat.update(an=True, ereignisse=list(k.get("vorher") or ()),
                        freigaben=[], schleife=None, proc=self.proc,
                        schloss=threading.Lock())
        m = types.ModuleType(self.echt.__name__)
        m.__dict__.update(self.echt.__dict__)
        m.starten = starten
        sys.modules[self.NAME] = m
        wahl = self.z["w"]["chat_anbieter"]
        wahl.setCurrentIndex(wahl.findData("claude"))
        return self

    def __exit__(self, *_):
        sys.modules[self.NAME] = self.echt
        if self.alt_projekt is None:
            os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        else:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = self.alt_projekt


def _quittieren_lauf(laden=None):
    """Chat startet nicht -> Zeile an der Eingabe (seit S7, vorher die rote
    Zeile im Kopf). Dann (a) ein Start, der gelingt; (b) eine Meldung des
    Docks im Kopf, der Dienst endet, ein neuer Plugin-Klick verbindet.
    -> dict mit den Messwerten."""
    _frischer_start()
    p_y, = _freie_ports(1)
    client = _Client([("Y", p_y)])
    kern = _VerbindKern(1, 0)
    m = {}
    try:
        D, z, _r = _klick(client, kern, verbinden=True, laden=laden)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        with _ChatStartAttrappe(D, z) as att:
            att.fehler.append("Probe-Start")
            m["feld"] = _senden_klick(D, z)
            m["rot"] = _meldung(z)
            m["kopf"] = _hinweis(z)
            del att.fehler[:]
            _senden_klick(D, z)                    # (a) jetzt gelingt er
            D._auffrischen(z)
            m["nach_start"] = _meldung(z)
            m["starts"] = len(att.gestartet)
        # (b) Eine Meldung des Docks im Kopf; der Dienst endet von selbst
        # (etwa ein shutdown von aussen) — ohne Klick des Nutzers, die
        # Meldung bleibt also stehen ...
        D._fehler_zeigen(z, "Verbinden fehlgeschlagen: Probe-Kopf")
        z["dienst"].beenden = True
        kern.aufraeumen()
        D._auffrischen(z)
        m["nach_ende"] = _hinweis(z)
        # ... bis der naechste Plugin-Klick wieder verbindet.
        D, z, _r = _klick(client, kern, verbinden=True, laden=laden)
        D._auffrischen(z)
        m["verbindungen"] = len(kern.aufrufe)
        m["nach_verbinden"] = _hinweis(z)
    finally:
        kern.aufraeumen()
        _frischer_start()
    return m


def zelle_quittieren():
    """Nachpruefung 2026-09-25: dass ein neuer Versuch die Meldung des
    vorigen wegnimmt, mass keine Zelle (Mutanten M1d, M1e). Seit S7 steht
    ein Startfehler des Chats an der Eingabe, und der naechste Versuch
    (`_chat_fehler_quittieren` in `_chat_senden`) nimmt ihn weg; die
    Meldungen des Docks im Kopf nimmt weiter `_verbinden` weg."""
    m = _quittieren_lauf()
    pruefe("L28 Vorbedingung: der gescheiterte Start steht an der Eingabe "
           "(nicht im Kopf), der Text bleibt im Feld",
           "Chat startet nicht: Probe-Start" in m["rot"]
           and "Probe-Start" not in m["kopf"]
           and m["feld"] == "Probe-Nachricht", m)
    pruefe("L28 ein Start, der gelingt, nimmt die Meldung weg (auch nach "
           "dem Takt)", m["starts"] == 1 and m["nach_start"] == "", m)
    pruefe("L28 Vorbedingung: die Meldung im Kopf bleibt nach dem Ende des "
           "Dienstes stehen", "Probe-Kopf" in m["nach_ende"], m)
    pruefe("L28 ein neues Verbinden (Plugin-Klick) nimmt sie weg",
           m["verbindungen"] == 2 and m["nach_verbinden"] == "", m)
    k = _quittieren_lauf(lambda: _mutant(
        _ohne_aufruf("_chat_senden", "_chat_fehler_quittieren")))
    pruefe("L28 KONTROLLE M1d: ohne _chat_fehler_quittieren in _chat_senden "
           "bleibt sie nach dem Start stehen",
           k["treffer"] == [1] and k["starts"] == 1
           and "Probe-Start" in k["nach_start"]
           and k["nach_verbinden"] == "", k)
    k = _quittieren_lauf(lambda: _mutant(
        _ohne_aufruf("_verbinden", "_fehler_quittieren")))
    pruefe("L28 KONTROLLE M1e: ohne _fehler_quittieren in _verbinden bleibt "
           "sie nach dem Verbinden stehen",
           k["treffer"] == [1] and k["verbindungen"] == 2
           and "Probe-Kopf" in k["nach_verbinden"]
           and k["nach_start"] == "", k)


#: Die drei try-Bloecke in `_auffrischen` und ihre Namen auf stderr.
AUFFRISCHEN_BLOECKE = (("_verbindungen_zeichnen", "Auffrischen/Verbindungen"),
                       ("_chat_zeichnen", "Auffrischen/Chat"),
                       ("_technik_zeichnen", "Auffrischen/Technik"),
                       ("_ablage_pflegen", "Auffrischen/Notizen"))


def _auffrischen_fehler_lauf(D=None):
    """Jeder Block in `_auffrischen` wirft; BEIDE Takte stehen, gerufen wird
    `_auffrischen` direkt, dreimal. -> dict: Meldungen je Name, Liste."""
    import io
    _frischer_start()
    D, z, d = aufbauen(D=D)
    z["timer"].stop()
    z["chat_takt"].stop()        # sein "Chat zeichnen" darf hier nichts decken
    with d.sperre:
        d.verlauf.append({"ok": True, "beschreibung": "Probe-Auftrag",
                          "dauer_s": 0.1})
    for funktion, wo in AUFFRISCHEN_BLOECKE:
        def wirft(_z, _wo=wo):
            raise RuntimeError("Probe %s" % _wo)
        setattr(D, funktion, wirft)
    alt_err, puffer = sys.stderr, io.StringIO()
    sys.stderr = puffer
    try:
        for _ in range(3):
            D._auffrischen(z)
    finally:
        sys.stderr = alt_err
    text = puffer.getvalue()
    m = {wo: text.count("Fehler im Takt (%s:" % wo)
         for wo in [w for _f, w in AUFFRISCHEN_BLOECKE] + ["Chat zeichnen"]}
    m["liste"] = z["w"]["liste_auftraege"].count()
    m["treffer"] = getattr(D, "_mutant_treffer", None)
    _frischer_start()
    return m


def zelle_auffrischen_meldet():
    """Nachpruefung 2026-09-25: `_melden` in den try-Bloecken von
    `_auffrischen` liess sich wieder in `pass` verwandeln, ohne dass etwas rot
    wurde (M5e, M5f) — der Chat-Takt meldete unter demselben Namen "Chat
    zeichnen" und deckte den Block, "Verbindungen zeichnen" warf nie."""
    m = _auffrischen_fehler_lauf()
    namen = [w for _f, w in AUFFRISCHEN_BLOECKE]
    pruefe("L29 jeder Block in _auffrischen meldet unter EIGENEM Namen, "
           "einmal fuer drei Takte",
           all(m[w] == 1 for w in namen) and m["Chat zeichnen"] == 0, m)
    pruefe("L29 der Rest des Takts laeuft trotzdem (Verlauf gezeichnet)",
           m["liste"] == 1, m)
    for kennung, wo in (("M5f", "Auffrischen/Verbindungen"),
                        ("M5e", "Auffrischen/Chat"),
                        ("M5g", "Auffrischen/Notizen"),
                        ("M5h", "Auffrischen/Technik")):
        k = _auffrischen_fehler_lauf(_mutant(_melden_stumm("_auffrischen", wo)))
        andere = [w for w in namen if w != wo]
        pruefe("L29 KONTROLLE %s: %s stumm -> fehlt auf stderr, die anderen "
               "bleiben" % (kennung, wo),
               k["treffer"] == [1] and k[wo] == 0
               and all(k[w] == 1 for w in andere), k)


def _ersatz_lauf(D=None, ersatz=True, laeuft_zug=False, freigabe=False,
                 knopf=False):
    """Ein Dock mit ERSATZ-Tab (der Chat-Tab laesst sich nicht bauen), ein
    Chat laeuft noch (aus der Fassung vor dem Update), der Nutzer hat
    "Nach dem Zug beenden" beim Trennen gewaehlt. Beide Takte stehen; EIN
    `_auffrischen` (bzw. mit `knopf` der Trennen-Knopf). -> Messwerte."""
    import io
    _frischer_start()
    D = D if D is not None else dashboard_laden()
    if ersatz:
        def kaputt(_z, _register):
            raise RuntimeError("Probe: Chat-Tab nicht baubar")
        D._tab_chat = kaputt
    alt_err = sys.stderr
    sys.stderr = io.StringIO()      # "Chat-Tab bauen: …" gehoert nicht hierher
    try:
        D, z, d = aufbauen(D=D)
        for t in ("timer", "chat_takt"):
            if z.get(t) is not None:
                z[t].stop()
        chat = z["chat"]
        chat.update(an=True, laeuft_zug=laeuft_zug, kurzname="Probe",
                    freigaben=[{"id": "f1", "offen": True,
                                "name": "execute_cadwork_command",
                                "eingabe": {"code": "x = 1"}}]
                    if freigabe else [])
        if knopf:
            D._primaer_geklickt(z)            # Trennen, ohne Rueckfrage
        else:
            chat["beenden_nach_zug"] = True
            z["trennen_nach_chat"] = True
            D._auffrischen(z)
        m = {"ersatz": D.CHAT_TAB not in z["w"], "an": bool(chat.get("an")),
             "nach_zug": bool(chat.get("beenden_nach_zug")),
             "trennen_offen": bool(z.get("trennen_nach_chat")),
             "getrennt": d.beenden, "knopf": z["w"]["primaer"].text(),
             "karte": (not z["w"]["chat_freigabe"].isHidden())
             if "chat_freigabe" in z["w"] else None,
             "treffer": getattr(D, "_mutant_treffer", None)}
    finally:
        sys.stderr = alt_err
        _frischer_start()
    return m


def zelle_ersatz_nach_zug():
    """Nachpruefung 2026-09-25: mit dem Ersatz-Tab kehrte `_chat_zeichnen`
    am Ersatz-Return zurueck, BEVOR "nach dem Zug beenden / trennen"
    eingeloest wurde — der Chat lief weiter, das Trennen geschah nie. Der
    Ersatz-Tab hat keinen Chat-Takt: nur `_auffrischen` kann es einloesen."""
    m = _ersatz_lauf()
    pruefe("L30 Ersatz-Tab, Zug fertig: Chat aus, Trennen nachgeholt",
           m["ersatz"] and not m["an"] and not m["nach_zug"]
           and not m["trennen_offen"] and m["getrennt"], m)
    pruefe("L30 ... und schon dieser Takt zeigt 'Verbinden'",
           m["knopf"] == "Verbinden", m)
    m = _ersatz_lauf(laeuft_zug=True, freigabe=True)
    pruefe("L30 Ersatz-Tab, Zug wartet auf eine Freigabe (keine Karte "
           "moeglich): Chat aus, getrennt",
           m["ersatz"] and not m["an"] and m["getrennt"], m)
    m = _ersatz_lauf(laeuft_zug=True)
    pruefe("L30 KONTROLLE: Ersatz-Tab, Zug arbeitet noch -> er darf fertig "
           "werden", m["ersatz"] and m["an"] and m["nach_zug"]
           and m["trennen_offen"] and not m["getrennt"], m)
    m = _ersatz_lauf(ersatz=False, laeuft_zug=True, freigabe=True)
    pruefe("L30 KONTROLLE: mit Chat-Tab wartet derselbe Zug auf seine Karte",
           not m["ersatz"] and m["karte"] and m["an"]
           and not m["getrennt"], m)
    m = _ersatz_lauf(knopf=True)
    pruefe("L30 Trennen per Knopf geht im Ersatz-Tab weiterhin (Chat aus)",
           m["ersatz"] and not m["an"] and m["getrennt"]
           and m["knopf"] == "Verbinden", m)
    k = _ersatz_lauf(D=_mutant(_verschieben(
        "_chat_zeichnen", lambda s: _ist_aufruf(s, "_nach_zug_einloesen"),
        _ist_ersatz_return)))
    pruefe("L30 KONTROLLE: alte Reihenfolge (Einloesen hinter dem "
           "Ersatz-Return) -> Chat bleibt an, nichts getrennt",
           k["treffer"] == [1] and k["ersatz"] and k["an"]
           and k["nach_zug"] and not k["getrennt"], k)
    k = _ersatz_lauf(D=_mutant(_verschieben(
        "_auffrischen", lambda s: _ist_zuweisung(s, "d", "verbunden"),
        lambda s: _ist_zuweisung(s, "w"))))
    pruefe("L30 KONTROLLE: 'verbunden' vor dem Chat bestimmt -> getrennt, "
           "aber der Takt zeigt noch 'Trennen'",
           k["treffer"] == [2] and k["getrennt"] and k["knopf"] == "Trennen",
           k)


# --- FORM und die Teile des Docks ------------------------------------------
# `FORM` im Dashboard sagt, aus welcher Fassung ein Dock stammt; weicht sie
# ab, baut der naechste Klick es neu (L25). Das hilft nur, wenn FORM steigt,
# sobald sich die Teile aendern, in die neuer Code greift: die Schluessel in
# `z["w"]` und die Timer des Docks in `z`. Hier die Aufnahme dazu — GEMESSEN
# an einem echt gebauten Dock (L31), nicht aus dem Quelltext abgeschrieben.
# Aendert sich ein Teil: FORM im Dashboard heben UND diese Aufnahme
# nachfuehren, beides im selben Commit.
FORM_AUFNAHME = {
    "form": 21,
    "w": frozenset({
        # FORM 21 (2026-10-08): das "×" im Kopf ohne Verbindung.
        "kopf_schliessen",
        # FORM 20 (2026-10-08, angedockt unsichtbar in Cadwork): keine neuen
        # Teile — gehoben, damit ein offenes Fenster von FORM 19 (mit
        # WA_TranslucentBackground) beim naechsten Klick neu gebaut wird.
        # FORM 19 (Gegenpruefung Laien-Sicht K12): der Hinweis-Bereich rollt
        # als Ganzes (`hinweise_rolle`, Liste `hinweise_liste` in voller
        # Hoehe, `hinweise_tipp` ohne Wahl, die Knoepfe `hinweise_aktionen`
        # darunter), die Wahl des Steckplatzes in
        # den Technik-Details (`steckplatz_reihe`).
        "hinweise_rolle", "hinweise_liste", "hinweise_tipp",
        "hinweise_aktionen", "steckplatz_reihe",
        # K12 (2026-10-07): EIN Fenster. Weg sind Leiste (`mini_*`),
        # Steuerfenster (`inhalt`, `titel`, `register`, `mehr_port`,
        # `einst_knopf`, `chat_oeffnen`, `chat_stand`) und das ⚙ des Chats
        # (`chat_einst`); neu Kopf, Koerper, Segmente, Hinweis-Bereich,
        # Briefkasten-Seite, "⋯", der Popover und die Arbeitsanzeige.
        # FORM 18 (Gegenpruefung K12): "In den Chat übernehmen" am
        # Hinweis-Bereich, die Karten der Einstellungsseite.
        "hinweis_in_chat", "einst_karte_verbindung", "einst_karte_modus",
        "einst_karte_technik",
        "kopf", "kopf_griff", "kopf_logo", "kopf_hinweise", "kopf_chat",
        "kopf_andocken", "kopf_verkleinern", "pille", "primaer",
        "koerper", "kontext_zeile", "dok", "hinweis", "segment",
        "segment_chat", "segment_briefkasten", "segment_gruppe",
        "briefkasten_zahl", "hinweise_knopf", "hinweise_bereich",
        "hinweise_titel", "hinweise_zu", "seiten", "mehr_menue", "mehr_auf",
        "mehr_einst", "mehr_anleitung", "mehr_technik",
        "briefkasten_seite", "briefkasten_laeuft", "briefkasten_laeuft_text",
        "auftraege_kopf", "einst_titel", "einst_zurueck",
        "einst_technik_lay", "stufe_kachel", "stufe_gross", "modell_zeile",
        "stufe_winkel", "stufe_zurueck", "stufe_notiz", "stufe_hirn",
        "stufe_regler", "modell_liste_auf",
        "anzeige_karte", "anzeige_logo", "anzeige_zeichen", "anzeige_titel",
        "anzeige_knopf", "anzeige_weg", "anzeige_zeile", "anzeige_balken",
        "btn_nach", "btn_neu", "btn_pause", "btn_redo", "btn_undo",
        "chat_anbieter", "chat_api", "chat_art", "chat_basis",
        "chat_eingabe", "chat_einst_karte", "chat_ende",
        "chat_einst_fertig", "chat_einst_freigabe", "chat_einst_seite",
        "chat_stapel", "chat_status_symbol",
        "chat_ersatz", "chat_fehler", "chat_kontext",
        "chat_freigabe", "chat_freigabe_lay", "chat_modus",
        "chat_modus_auf", "chat_modell_knopf", "chat_modell_auf",
        "chat_eingaberahmen", "chat_ordner", "chat_ordner_auf",
        "chat_zusatz", "chat_zusatz_lay", "chat_lage", "chat_laufend",
        "chat_plus", "chat_plus_auf", "chat_anhaenge", "chat_anhaenge_lay",
        "chat_liste", "chat_status", "chat_technik_karte", "chat_liste_titel",
        "chat_lokal",
        "chat_lokal_frage", "chat_lokal_frage_text",
        "chat_lokal_installieren", "chat_lokal_ja", "chat_lokal_lage",
        "chat_lokal_nein", "chat_lokal_pruefen", "chat_lokal_starten",
        "chat_modell", "chat_modelle", "chat_neu", "chat_ordner_teil",
        "chat_ordner_text", "chat_ordner_waehlen", "chat_ordner_weg",
        "chat_schluessel",
        "chat_schluessel_abbrechen", "chat_schluessel_aendern",
        "chat_schluessel_ende", "chat_schluessel_entfernen",
        "chat_schluessel_gespeichert", "chat_schluessel_hilfe",
        "chat_schluessel_lage", "chat_schluessel_link",
        "chat_schluessel_speichern", "chat_senden",
        "chat_stufe", "chat_verlauf", "chat_wer",
        "chat_willkommen", "chat_willkommen_schritt",
        "chat_willkommen_claude", "chat_willkommen_codex",
        "chat_willkommen_schluessel", "chat_willkommen_pruefen",
        "chat_willkommen_anleitung",
        "einst_chat_lay", "einst_freigabe",
        "einst_seite", "einst_zum_chat",
        "hinweis_knoepfe", "hinweis_umgebung", "hinweise",
        "liste_auftraege", "marken", "modus_marken", "modus_text",
        "post_eingabe", "post_kontext", "post_senden", "post_verlauf",
        "regler", "steckplatz_wahl", "technik",
        "technik_knopf", "verb_karten", "verb_karten_lay",
        "verb_kopf"}),
    "timer": frozenset({"chat_takt", "timer"}),
}

def _dock_teile(z):
    """(Schluessel in z["w"], Namen der Timer in z) — gemessen, keine Liste."""
    from PyQt6.QtCore import QTimer
    return (frozenset(z["w"]),
            frozenset(k for k, v in z.items() if isinstance(v, QTimer)))


def _dock_vermessen(ersatz=False):
    """Ein Fenster ueber den Klick bauen, verbunden zeichnen, durch alle drei
    Zustaende fuehren (K12: alles baut schon der Klick). -> (D, z).

    `ersatz`: der Chat-Tab laesst sich nicht bauen (`_tab_chat_oder_ersatz`)
    — auch diese Gestalt des Docks gehoert zur FORM."""
    import io
    _frischer_start()
    D = dashboard_laden()
    if ersatz:
        def kaputt(_z, _register):
            raise RuntimeError("Probe: Chat-Tab nicht baubar")
        D._tab_chat = kaputt
    alt_err = sys.stderr
    sys.stderr = io.StringIO()
    try:
        D, z, _r = _klick(_Client([]), _VerbindKern(1, 0), verbinden=False,
                          laden=lambda: D)
        z["dienst"] = Dienst()
        D._auffrischen(z)
        # K12: alle drei Zustaende einmal (Kopf, Koerper, Popover).
        D._fenster_aktion(z, "chat")
        D._fenster_aktion(z, "andocken")
        D._fenster_aktion(z, "verkleinern")
        if "chat_modell_auf" in z["w"]:
            D._modell_aufklappen(z)
            z["w"]["chat_modell_auf"].hide()
        D._auffrischen(z)
    finally:
        sys.stderr = alt_err
    return D, z


def _form_urteil(form, teile, timer, aufnahme):
    """None, wenn Form und Teile zur Aufnahme passen — sonst die Anweisung."""
    if form != aufnahme["form"]:
        return ("FORM ist %r, die Aufnahme im Test gilt fuer %r: die Liste "
                "im Test nachführen (FORM_AUFNAHME)" % (form, aufnahme["form"]))
    neu = sorted((teile - aufnahme["w"]) | (timer - aufnahme["timer"]))
    weg = sorted((aufnahme["w"] - teile) | (aufnahme["timer"] - timer))
    if neu or weg:
        return ("FORM heben und die Liste im Test nachführen — neu: %s, "
                "weg: %s" % (neu, weg))
    return None


def zelle_form_teile():
    """Nachpruefung 2026-09-25: nichts erzwang, FORM zu heben, wenn sich
    Teile in `z["w"]` oder Timer des Docks aendern. Ohne das baute der Klick
    nach einem Update ein altes Dock nicht neu — und neuer Code griff in ein
    Dock ohne seine Teile (der KeyError, den L25 nachstellt)."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QLabel
    D, z = _dock_vermessen()
    teile, timer = _dock_teile(z)
    D2, z2 = _dock_vermessen(ersatz=True)
    teile2, timer2 = _dock_teile(z2)
    ersatz_ok = "chat_ersatz" in teile2 and D.CHAT_TAB not in teile2
    teile, timer = teile | teile2, timer | timer2
    urteil = _form_urteil(D.FORM, teile, timer, FORM_AUFNAHME)
    pruefe("L31 die Teile des Docks passen zur Aufnahme fuer FORM %r"
           % FORM_AUFNAHME["form"], urteil is None and ersatz_ok,
           urteil or "Ersatz-Tab nicht gebaut: %s" % sorted(teile2))
    # KONTROLLE: ein erfundener Teil bzw. Timer im ECHTEN Dock — gemessen
    # wie oben, also misst die Zelle das Dock und keine eigene Liste.
    z2["w"]["probe_teil"] = QLabel()
    z2["probe_takt"] = QTimer()
    t_k, s_k = _dock_teile(z2)
    urteil_w = _form_urteil(D.FORM, t_k | teile, timer, FORM_AUFNAHME)
    urteil_t = _form_urteil(D.FORM, teile, s_k | timer, FORM_AUFNAHME)
    pruefe("L31 KONTROLLE: ein erfundener Teil in z['w'] -> 'FORM heben'",
           urteil_w is not None and "FORM heben" in urteil_w
           and "probe_teil" in urteil_w, urteil_w)
    pruefe("L31 KONTROLLE: ein erfundener Timer in z -> 'FORM heben'",
           urteil_t is not None and "FORM heben" in urteil_t
           and "probe_takt" in urteil_t, urteil_t)
    weg = _form_urteil(D.FORM, teile - {"btn_undo"}, timer, FORM_AUFNAHME)
    pruefe("L31 KONTROLLE: ein fehlender Teil -> 'FORM heben'",
           weg is not None and "FORM heben" in weg and "btn_undo" in weg, weg)
    gehoben = _form_urteil(D.FORM + 1, teile, timer, FORM_AUFNAHME)
    pruefe("L31 KONTROLLE: FORM gehoben, Aufnahme alt -> 'nachführen'",
           gehoben is not None and "nachführen" in gehoben, gehoben)
    del z2["probe_takt"]
    _frischer_start()


# --- Befunde aus dem Viewer-Modus (2026-09-25) -----------------------------

def _zustand_weg():
    """Was ein NEUER App-Wrapper in Cadwork sieht: kein Attribut, und —
    im schlimmsten Fall — auch kein Anker (eine Fassung vor 2026-09-25)."""
    sys.modules.pop(_anker_name(), None)
    if hasattr(_APP, "_omcad_a_prototyp"):
        delattr(_APP, "_omcad_a_prototyp")


def zelle_wrapper_verlust():
    """Befund 2, Schicht Dashboard: der Zustand ueberlebt einen neuen
    App-Wrapper. In Cadwork gehoert die QApplication C++; ist ihr Wrapper
    weg, fehlt das Attribut (gemessen in L32-Messung)."""
    _frischer_start()
    p_y, p_z = _freie_ports(2)
    client = _Client([("Y", p_y), ("Z", p_z)])
    kern = _VerbindKern(1, 0)
    try:
        _D, z, erster = _klick(client, kern)
        delattr(_APP, "_omcad_a_prototyp")        # neuer Wrapper: Attribut weg
        _D2, z2, zweiter = _klick(client, kern)
        pruefe("L32 neuer App-Wrapper: der zweite Klick startet NICHTS",
               len(kern.aufrufe) == 1 and zweiter is erster and z2 is z,
               "%d serve()-Aufrufe" % len(kern.aufrufe))
        pruefe("L32 und baut kein zweites Dock", z2["dock"] is z["dock"])
        pruefe("L32 Z bleibt frei", _bindbar(p_z))
        # KONTROLLE: fehlt AUCH der Anker (so hing der Zustand bis
        # 2026-09-25 nur am Wrapper), startet derselbe Klick einen zweiten
        # Dienst — genau das Bild aus den Logs C und D.
        z["dock"].hide()
        _ALTE_ZUSTAENDE.append(z)
        _zustand_weg()
        _D3, z3, dritter = _klick(client, kern)
        pruefe("L32 KONTROLLE: ohne Anker startet derselbe Klick einen "
               "ZWEITEN Dienst", len(kern.aufrufe) == 2 and z3 is not z
               and dritter is not erster,
               "%d serve()-Aufrufe" % len(kern.aufrufe))
    finally:
        kern.aufraeumen()
        _frischer_start()


def zelle_wrapper_messung():
    """Die Ursache selbst, gemessen: eine C++-eigene QApplication (wie in
    Cadwork) verliert mit ihrem Python-Wrapper jedes Attribut. Eigener
    Prozess — die QApplication dieses Gates gehoert Python."""
    code = textwrap.dedent("""
        import gc, os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6 import sip
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        app._omcad_probe = 1
        gehalten = hasattr(QApplication.instance(), "_omcad_probe")
        sip.transferto(app, None)          # C++ besitzt sie, wie in Cadwork
        del app
        gc.collect()
        print(gehalten, hasattr(QApplication.instance(), "_omcad_probe"))
    """)
    lauf = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120)
    aus = lauf.stdout.split()
    pruefe("L32 gemessen: C++-eigene QApplication, neuer Wrapper -> "
           "Attribut weg", aus[-1:] == ["False"], lauf.stdout + lauf.stderr)
    pruefe("L32 KONTROLLE: haelt Python den Wrapper, bleibt das Attribut "
           "(darum sah L9 den Fehler nie)", aus[:1] == ["True"],
           lauf.stdout + lauf.stderr)


class _Cadwork:
    """cwapi3d-Attrappe fuer den ECHTEN Kern.

    Schreibt jeden Aufruf mit — und ob dabei ein modaler Dialog offen war.
    Genau das ist die Frage aus Befund 1: fasst der Takt cwapi3d an,
    waehrend Cadwork in einem Dialog rechnet?
    """

    NAMEN = ("utility_controller", "element_controller")

    def __init__(self):
        self.aufrufe = []          # (monotonic, modal offen?)
        self.haken = None          # einmal gerufen beim naechsten get_3d_hwnd
        self._vorher = {}

    def _merken(self):
        from PyQt6.QtWidgets import QApplication
        self.aufrufe.append((time.monotonic(),
                             QApplication.activeModalWidget() is not None))

    def einsetzen(self):
        import types
        uc = types.ModuleType("utility_controller")

        def name():
            self._merken()
            return "Seeblick_live.3d"

        def hwnd():
            haken, self.haken = self.haken, None
            if haken is not None:
                haken()
            return 0               # keine Fenster-Sonde: offscreen gibt es kein Handle

        uc.get_3d_file_name = name
        uc.get_3d_hwnd = hwnd
        ec = types.ModuleType("element_controller")
        ec.get_all_identifiable_element_ids = lambda: [1, 2, 3]
        ec.get_active_identifiable_element_ids = lambda: []
        for n, m in zip(self.NAMEN, (uc, ec)):
            self._vorher[n] = sys.modules.get(n)
            sys.modules[n] = m
        return self

    def entfernen(self):
        for n, m in self._vorher.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m


def _echter_kern_lader(bereich_port):
    """Laedt den ECHTEN Kern bei jedem Aufruf frisch — wie der Einstieg.

    Unter demselben Namen wie in Cadwork (`omcad_bridge_core_dyn`), damit
    `kern_modul` so entsteht wie dort. Umgelenkt wird nur, was das Gate
    nicht anfassen darf: der Portbereich (nur ein Testport) und die
    Logdatei (`_verbinden` setzt sonst `C:\\Users\\Public\\…`).
    """
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")

    def lade():
        spec = importlib.util.spec_from_file_location("omcad_bridge_core_dyn",
                                                      pfad)
        m = importlib.util.module_from_spec(spec)
        sys.modules["omcad_bridge_core_dyn"] = m
        spec.loader.exec_module(m)
        m.PORT_VON = m.PORT_BIS = bereich_port
        echt = m._logger_einrichten

        def umgelenkt(cfg):
            cfg.log_datei = os.path.join(_LIVE_TMP,
                                         "OpenMcpCad_%s.log" % cfg.instanz)
            echt(cfg)
            log = logging.getLogger("omcad.connect")
            for h in list(log.handlers):       # nur Datei, keine Konsole
                if type(h) is logging.StreamHandler:
                    log.removeHandler(h)

        m._logger_einrichten = umgelenkt
        return m

    return lade


class _OhneBuch:
    """Der Kern, wie das Dashboard ihn sieht — nur OHNE `dienst_im_prozess`.

    `serve` ist das echte und fuehrt sein Buch weiter. So ist die Frage
    getrennt pruefbar, ob der KERN selbst den zweiten Listener verhindert,
    wenn das Dashboard ihn nicht vorher fragen kann.
    """

    def __init__(self, kern):
        self._kern = kern

    def __getattr__(self, name):
        if name == "dienst_im_prozess":
            raise AttributeError(name)
        return getattr(self._kern, name)


_RESERVIERT = []          # jede Reservierung, die ein echter Klick versucht


def _klick_echt(client, kern_laden, **cfg_extra):
    """EIN Plugin-Klick mit dem echten Kern (frisch geladen)."""
    D = dashboard_laden()
    D._monitor_starten = lambda z: None
    D._verbindungen_zeichnen = lambda z: None
    D._ablage_pflegen = lambda z: None
    D._verbindungen_client = lambda: client
    echt_reservieren = D._steckplatz_reservieren

    def reservieren(*a, **kw):
        erg = echt_reservieren(*a, **kw)
        _RESERVIERT.append(erg[1])
        return erg

    D._steckplatz_reservieren = reservieren

    def cfg_bauen(kern):
        cfg = kern.Konfiguration()     # wie der dynamische Einstieg
        for k, v in cfg_extra.items():
            setattr(cfg, k, v)
        return cfg

    rueck = D.oeffnen(kern_laden, cfg_bauen, verbinden=True)
    return D, D._zustand(), rueck


def _nimmt_an(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _alle_beenden(kern, frist=10.0):
    """Jeden Dienst dieses Prozesses sauber beenden — ueber den Qt-Takt,
    wie das Trennen im Dock."""
    ende = time.monotonic() + frist
    d = kern.dienst_im_prozess()
    while d is not None and time.monotonic() < ende:
        d.beenden = True
        while kern.dienst_im_prozess() is d and time.monotonic() < ende:
            _APP.processEvents()
            time.sleep(0.02)
        d = kern.dienst_im_prozess()
    return kern.dienst_im_prozess() is None


def zelle_echter_kern_zweiter_klick():
    """Befund 2 mit dem ECHTEN Kern: Klick, Zustand weg, frischer Kern, Klick.

    Der schlimmste Fall: weder Attribut noch Anker (alte Fassung), der Kern
    frisch von der Platte — nur das Prozessbuch kennt den ersten Dienst.
    """
    _frischer_start()
    cw = _Cadwork().einsetzen()
    p_y, p_z = _freie_ports(2)
    client = _Client([("Y", p_y), ("Z", p_z)])
    lade = _echter_kern_lader(p_y)
    kern = None
    try:
        _D, z, erster = _klick_echt(client, lade)
        kern = z["kern"]
        pruefe("L33 echter Kern: der Klick verbindet ueber den Qt-Antrieb",
               erster is not None and erster.cfg.port == p_y
               and erster.zustand == "ready"
               and erster.cfg.antrieb == "qtimer",
               "%r" % (getattr(erster, "zustand", None),))
        z["dock"].hide()
        _ALTE_ZUSTAENDE.append(z)
        _zustand_weg()
        n_res = len(_RESERVIERT)
        _D2, z2, zweiter = _klick_echt(client, lade)
        pruefe("L33 ohne Dock-Zustand, frischer Kern: der zweite Klick "
               "uebernimmt den laufenden Dienst", zweiter is erster
               and z2["dienst"] is erster and z2["kern"] is not None)
        pruefe("L33 er fragt das Prozessbuch VOR dem Reservieren: kein Port "
               "angefasst", len(_RESERVIERT) == n_res,
               "reserviert: %r" % (_RESERVIERT[n_res:],))
        pruefe("L33 kein zweiter Listener: Z bleibt frei",
               _bindbar(p_z) and not _nimmt_an(p_z))
        pruefe("L33 das Dock bekommt den Kern, der den Dienst gestartet hat",
               erster.kern_modul is not None and z2["kern"] is erster.kern_modul)

        # Derselbe Klick, aber das Dashboard KANN nicht fragen: der Kern
        # selbst muss ablehnen und die Reservierung von Z freigeben.
        z2["dock"].hide()
        _ALTE_ZUSTAENDE.append(z2)
        _zustand_weg()
        n_res = len(_RESERVIERT)
        _D3, z3, dritter = _klick_echt(client, lambda: _OhneBuch(lade()))
        pruefe("L33 fragt das Dashboard nicht: serve() selbst lehnt ab",
               dritter is erster and not _nimmt_an(p_z) and _bindbar(p_z),
               "Rueckgabe %r" % (dritter,))
        pruefe("L33 KONTROLLE: dieser Klick hat Z wirklich reserviert (und "
               "der Kern gab es frei)", _RESERVIERT[n_res:] == [p_z],
               "sonst misst 'kein Port angefasst' oben nichts: %r"
               % (_RESERVIERT[n_res:],))

        # KONTROLLE: ohne Buch UND mit `mehrere_im_prozess` startet derselbe
        # Klick wirklich einen zweiten Listener auf Z.
        z3["dock"].hide()
        _ALTE_ZUSTAENDE.append(z3)
        _zustand_weg()
        _D4, _z4, vierter = _klick_echt(client, lambda: _OhneBuch(lade()),
                                         mehrere_im_prozess=True)
        pruefe("L33 KONTROLLE: ohne die Regel laeuft ein ZWEITER Listener",
               vierter is not None and vierter is not erster
               and _nimmt_an(p_z), "Rueckgabe %r" % (vierter,))
    finally:
        if kern is not None:
            pruefe("L33 alle Dienste lassen sich sauber beenden",
                   _alle_beenden(kern))
        cw.entfernen()
        _frischer_start()


def zelle_klick_im_start():
    """Ein Klick, den Cadwork MITTEN im Start ausfuehrt (im cwapi3d-Aufruf
    des ersten). Das Buch muss den ersten Dienst da schon kennen."""
    _frischer_start()
    cw = _Cadwork().einsetzen()
    p_y, p_z = _freie_ports(2)
    client = _Client([("Y", p_y), ("Z", p_z)])
    lade = _echter_kern_lader(p_y)
    innen = {}

    def zweiter_klick():
        innen["aussen_z"] = getattr(sys.modules.get(_anker_name()), "z", None)
        _zustand_weg()
        innen["D"], innen["z"], innen["rueck"] = _klick_echt(
            client, lambda: _OhneBuch(lade()))
        innen["z_frei"] = _bindbar(p_z) and not _nimmt_an(p_z)

    cw.haken = zweiter_klick
    kern = None
    try:
        _D, z, erster = _klick_echt(client, lade)
        kern = erster.kern_modul if erster is not None else None
        pruefe("L34 der innere Klick lief wirklich im Start des ersten",
               "rueck" in innen, repr(sorted(innen)))
        pruefe("L34 er bekommt den startenden Dienst, keinen zweiten",
               innen.get("rueck") is erster and innen.get("z_frei") is True,
               "innen %r, erster %r" % (innen.get("rueck"), erster))
        pruefe("L34 der erste Start laeuft danach normal zu Ende",
               erster is not None and erster.zustand == "ready"
               and erster.cfg.port == p_y)
    finally:
        for schluessel in ("aussen_z", "z"):
            alt = innen.get(schluessel)
            if alt is not None and alt.get("dock") is not None:
                alt["dock"].hide()
                _ALTE_ZUSTAENDE.append(alt)
        if kern is not None:
            _alle_beenden(kern)
        cw.entfernen()
        _frischer_start()


def zelle_qt_sonden():
    """Die ECHTEN Qt-Sonden des Kerns gegen echte Dialoge, Menues, Schleifen."""
    from PyQt6.QtCore import QEventLoop, Qt, QTimer
    from PyQt6.QtWidgets import QDialog, QMenu, QProgressDialog
    kern = _echter_kern_lader(0)()
    modal, popup, schleife = kern._qt_sonden()

    def lesen():
        return [modal(), popup(), schleife()]

    frei = lesen()                          # lernt die flachste Ebene
    gesehen = {}
    dlg = QDialog()
    dlg.setWindowTitle("omcad-live")

    def im_dialog():
        gesehen["dialog"] = lesen()
        menue = QMenu(dlg)
        menue.addAction("x")
        menue.popup(dlg.pos())
        _APP.processEvents()
        gesehen["menue"] = lesen()
        menue.close()
        _APP.processEvents()
        dlg.accept()

    QTimer.singleShot(50, im_dialog)
    dlg.exec()
    gesehen["danach"] = lesen()

    # Eine lange Rechnung im Hauptthread, die ihren Fortschrittsdialog ueber
    # processEvents am Leben haelt — KEINE verschachtelte Schleife.
    pd = QProgressDialog("rechnet", "Abbruch", 0, 5)
    pd.setWindowModality(Qt.WindowModality.ApplicationModal)
    pd.setMinimumDuration(0)
    pd.setValue(1)
    _APP.processEvents()
    gesehen["rechnung"] = lesen()
    pd.close()
    _APP.processEvents()

    schl = QEventLoop()
    QTimer.singleShot(20, lambda: (gesehen.__setitem__("schleife", lesen()),
                                   schl.quit()))
    schl.exec()

    pruefe("L35 ohne Dialog, Menue, Schleife: keine Sonde schlaegt an",
           frei == ["", "", ""], repr(frei))
    pruefe("L35 QDialog.exec: 'modal' nennt den Dialog, 'schleife' die Ebene",
           "QDialog 'omcad-live'" in gesehen["dialog"][0]
           and "verschachtelt" in gesehen["dialog"][2], repr(gesehen["dialog"]))
    pruefe("L35 offenes Menue: 'popup' schlaegt an",
           "QMenu" in gesehen["menue"][1], repr(gesehen["menue"]))
    pruefe("L35 processEvents-Rechnung mit Fortschrittsdialog: 'modal' sieht "
           "ihn, obwohl die Ebene gleich bleibt",
           "QProgressDialog" in gesehen["rechnung"][0]
           and gesehen["rechnung"][2] == "", repr(gesehen["rechnung"]))
    pruefe("L35 verschachtelte QEventLoop ohne Dialog: 'schleife'",
           "verschachtelt" in gesehen["schleife"][2]
           and gesehen["schleife"][0] == "", repr(gesehen["schleife"]))
    pruefe("L35 KONTROLLE: nach dem Dialog wieder still",
           gesehen["danach"] == ["", "", ""], repr(gesehen["danach"]))


def _anfrage(port, methode, params=None, timeout=20.0):
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall((json.dumps({"id": 1, "method": methode,
                               "params": params or {}}) + "\n").encode())
        puffer = bytearray()
        while b"\n" not in puffer:
            stueck = s.recv(4096)
            if not stueck:
                raise ConnectionError("ohne Antwort geschlossen")
            puffer.extend(stueck)
    return json.loads(bytes(puffer).partition(b"\n")[0].decode())


def _auftrag_unter_dialog(port, cw, dauer_s=1.5):
    """Oeffnet einen modalen Dialog und schickt WAEHREND er offen ist ein
    `status` und einen Leseauftrag ueber TCP — wie der Agent im Befund.

    -> dict mit Zeitpunkten, Antworten und den cwapi3d-Aufrufen.
    """
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog
    erg = {}
    offen = threading.Event()
    n_vorher = len(cw.aufrufe)

    def client():
        offen.wait(10)
        try:
            erg["status"] = _anfrage(port, "status")
            erg["status_t"] = time.monotonic()
            erg["auftrag"] = _anfrage(port, "get_document_info",
                                      {"description": "unter Dialog"})
            erg["auftrag_t"] = time.monotonic()
        except Exception as exc:                          # noqa: BLE001
            erg["fehler"] = repr(exc)

    t = threading.Thread(target=client, daemon=True)
    t.start()
    dlg = QDialog()
    dlg.setWindowTitle("Viewer-Modus")

    def zu():
        erg["zu_t"] = time.monotonic()
        dlg.accept()

    QTimer.singleShot(100, offen.set)
    QTimer.singleShot(int(dauer_s * 1000), zu)
    dlg.exec()
    ende = time.monotonic() + 15
    while t.is_alive() and time.monotonic() < ende:
        _APP.processEvents()
        time.sleep(0.01)
    erg["aufrufe"] = cw.aufrufe[n_vorher:]
    return erg


def zelle_modal_haelt_zurueck():
    """Befund 1 Ende-zu-Ende: echter Kern, echter QTimer, echtes TCP, ein
    modaler Dialog. Der Auftrag muss warten, der Status muss antworten."""
    cw = _Cadwork().einsetzen()
    s, port = _belegen()
    kern = _echter_kern_lader(port)()
    d = None
    try:
        cfg = kern.Konfiguration()
        cfg.fenster = False
        cfg.require_qtimer = True
        d = kern.serve(cfg, reserved_socket=s)
        pruefe("L36 echter Dienst im Qt-Antrieb bereit, Sonden aktiv",
               d.zustand == "ready" and d.cfg.antrieb == "qtimer"
               and "modal" in d.sonden, "%s %r" % (d.zustand, d.sonden))
        e = _auftrag_unter_dialog(port, cw)
        st = (e.get("status") or {}).get("result") or {}
        pruefe("L36 WAEHREND des Dialogs antwortet der Status",
               "status_t" in e and e["status_t"] < e.get("zu_t", 0),
               repr(e.get("fehler")))
        pruefe("L36 und sagt, dass Cadwork arbeitet und warum",
               "modaler Dialog offen: QDialog 'Viewer-Modus'"
               in st.get("cadwork_beschaeftigt", "")
               and "Nichts wiederholen" in (st.get("hinweis") or ""),
               repr(st.get("cadwork_beschaeftigt")))
        pruefe("L36 der Auftrag laeuft erst NACH dem Dialog, und sauber",
               e.get("auftrag_t", 0) > e.get("zu_t", 1e18)
               and (e.get("auftrag") or {}).get("ok") is True,
               "%r" % (e.get("auftrag"),))
        pruefe("L36 kein cwapi3d-Aufruf bei offenem Dialog",
               e["aufrufe"] and not any(m for _t, m in e["aufrufe"]),
               "%d Aufrufe, davon modal %d" % (
                   len(e["aufrufe"]), sum(1 for _t, m in e["aufrufe"] if m)))
        pruefe("L36 danach ist die Zurueckhaltung vorbei und gezaehlt",
               d.status()["cadwork_beschaeftigt"] == ""
               and d.status()["zurueckhaltungen"] >= 1)

        # KONTROLLE: derselbe Ablauf ohne Zurueckhalten — dann ruft der Takt
        # cwapi3d MITTEN im Dialog auf. Genau das war der Absturz.
        d.cfg.zurueckhalten = False
        k = _auftrag_unter_dialog(port, cw)
        pruefe("L36 KONTROLLE: ohne Zurueckhalten laeuft der Auftrag IM "
               "Dialog und fasst cwapi3d an",
               k.get("auftrag_t", 1e18) < k.get("zu_t", 0)
               and any(m for _t, m in k["aufrufe"]),
               "Auftrag %.2f s vor dem Schliessen" % (
                   k.get("zu_t", 0) - k.get("auftrag_t", 0)))
    finally:
        if d is not None:
            d.cfg.zurueckhalten = True
            pruefe("L36 Dienst laesst sich sauber beenden", _alle_beenden(kern))
        cw.entfernen()


class _CadworkBild:
    """cwapi3d-Attrappe mit dem, was im Bild waere: Sichtbarkeit, Material,
    Auffrischung. Fuer L46 (Paketlauf im echten Qt-Antrieb)."""

    NAMEN = ("utility_controller", "element_controller",
             "visualization_controller", "attribute_controller",
             "material_controller")

    def __init__(self):
        self.elemente = [1, 2, 3]
        self.unsichtbar = set()
        self.versteckt = set()     # alles, was je unsichtbar gemacht wurde
        self.hell = []             # Material bei eingeschalteter Auffrischung
        self.dunkel = []
        self.auffrischung = True
        self._vorher = {}
        # Jedes vc.refresh(): im Auftrag (welches Paket) oder im Leerlauf,
        # und was da schon hell war. `dienst` setzt die Zelle, sobald er
        # laeuft (Gegenpruefung 2026-09-26, Mutant K11).
        self.refreshs = []
        self.dienst = None

    def einsetzen(self):
        uc = types.ModuleType("utility_controller")
        uc.get_3d_file_name = lambda: "Seeblick_live.3d"
        uc.get_3d_hwnd = lambda: 0

        def aus():
            self.auffrischung = False

        def an():
            self.auffrischung = True

        uc.disable_auto_display_refresh = aus
        uc.enable_auto_display_refresh = an
        uc.show_progress_bar = uc.hide_progress_bar = lambda: None
        uc.update_progress_bar = lambda _p: None
        ec = types.ModuleType("element_controller")
        ec.get_all_identifiable_element_ids = lambda: list(self.elemente)
        ec.get_active_identifiable_element_ids = lambda: []

        def neu(*_a):
            self.elemente.append(max(self.elemente) + 1)
            return self.elemente[-1]

        ec.create_rectangular_beam_vectors = neu
        ec.add_created_elements_to_undo = lambda ids: None
        vc = types.ModuleType("visualization_controller")

        def zu(ids):
            self.unsichtbar.update(ids)
            self.versteckt.update(ids)

        vc.set_invisible = zu
        vc.set_visible = lambda ids: self.unsichtbar.difference_update(ids)

        def neu_gezeichnet():
            a = getattr(self.dienst, "aktueller_auftrag", None)
            self.refreshs.append({
                "im_auftrag": a is not None,
                "paket": getattr(a, "paket", None),
                "hell": frozenset(self.hell) if a is not None else None})

        vc.refresh = neu_gezeichnet
        ac = types.ModuleType("attribute_controller")
        ac.get_element_material_name = lambda eid: "Holz"
        ac.set_element_material = lambda ids, mid: (
            self.hell if self.auffrischung else self.dunkel).extend(ids)
        mc = types.ModuleType("material_controller")
        mc.get_material_id = lambda name: 1
        for n, m in zip(self.NAMEN, (uc, ec, vc, ac, mc)):
            self._vorher[n] = sys.modules.get(n)
            sys.modules[n] = m
        return self

    def entfernen(self):
        for n, m in self._vorher.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m


# Das Paket gibt Cadwork eine Runde Ereignisschleife je Bauteil — so wie
# Cadworks eigene Arbeit im Film (dabei zeichnete es die Schrauben schon).
# Der Takt feuert darin und muss sich zurueckhalten (Wiedereintritt).
L46_CODE = ("import element_controller as ec\n"
            "from PyQt6.QtWidgets import QApplication\n"
            "result = []\n"
            "for _e in paket:\n"
            "    result.append(ec.create_rectangular_beam_vectors())\n"
            "    QApplication.processEvents()\n")


def _l46_lauf(kern, port, cw, name, altes_feld=False):
    """Ein echter Paketlauf (Server-Code) aus einem Thread, der Hauptthread
    dreht Qt. -> (Antwort, Schnappschuesse je Paket, Popup-Proben)."""
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from open_mcp_cad import auftraege, bridge_client
    pfad = os.path.join(_LIVE_TMP, "%s.json" % name)
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump([{"i": i} for i in range(6)], fh)
    erg, schnapp = {}, []

    def rufen(methode, params, antwort_timeout=None):
        params = dict(params, client_id="anon")
        if altes_feld:
            params.pop("paketlauf", None)
        antwort = bridge_client.call(methode, params, port=port,
                                     antwort_timeout=antwort_timeout)
        schnapp.append({"ids": list((antwort or {}).get("result") or []),
                        "unsichtbar": set(cw.unsichtbar),
                        "hell": list(cw.hell),
                        "auffrischung": cw.auffrischung})
        return antwort

    def lauf():
        try:
            erg["a"] = auftraege.paketlauf(L46_CODE, pfad, 2, name,
                                           rufen=rufen)
        except Exception as exc:                          # noqa: BLE001
            erg["fehler"] = repr(exc)

    t = threading.Thread(target=lauf, daemon=True)
    t.start()
    popup = []
    ende = time.monotonic() + 30
    while t.is_alive() and time.monotonic() < ende:
        _APP.processEvents()
        w = kern._LAUF_POPUP.get("w")
        popup.append(bool(w is not None and w.isVisible()))
        time.sleep(0.01)
    return erg.get("a") or {"fehler": erg.get("fehler")}, schnapp, popup


def zelle_paketlauf_paketweise():
    """Film 2026-09-25 im ECHTEN Qt-Antrieb: ein Paketlauf in 'Auto' zeigt
    jedes Paket, sobald es fertig ist; ohne das Feld (Server vor 2.18)
    blitzen die Bauteile je Paket auf und verschwinden."""
    cw = _CadworkBild().einsetzen()
    s, port = _belegen()
    kern = _echter_kern_lader(port)()
    d = None
    try:
        cfg = kern.Konfiguration()
        cfg.fenster = False
        cfg.require_qtimer = True
        d = kern.serve(cfg, reserved_socket=s)
        cw.dienst = d
        d.ms_je_teil = 1000.0            # das Lauf-Fenster kommt ab Paket 1
        pruefe("L46 echter Dienst im Qt-Antrieb, Stufe 'Auto'",
               d.zustand == "ready" and d.cfg.antrieb == "qtimer"
               and d.zeichenmodus == "auto" and d.schnellzeichnen,
               "%s %s" % (d.zustand, d.zeichenmodus))
        a, sn, popup = _l46_lauf(kern, port, cw, "L46_auto")
        alle = [i for x in sn for i in x["ids"]]
        pruefe("L46 3 Pakete ueber TCP, 6 Bauteile", a.get("ok")
               and len(sn) == 3 and len(set(alle)) == 6, json.dumps(a)[:140])
        pruefe("L46 kein Bauteil eines Pakets wird je versteckt",
               not cw.versteckt & set(alle), sorted(cw.versteckt))
        pruefe("L46 nach jedem Paket ist alles bisher Angelegte nachgezogen "
               "(Auffrischung an) und sichtbar",
               all(set(i for x in sn[:k + 1] for i in x["ids"])
                   <= set(sn[k]["hell"])
                   and not set(i for x in sn[:k + 1] for i in x["ids"])
                   & sn[k]["unsichtbar"] and sn[k]["auffrischung"]
                   for k in range(len(sn))), repr(sn)[:200])
        je_paket = [sum(1 for r in cw.refreshs
                        if r["im_auftrag"] and r["paket"] == (k, len(sn))
                        and set(i for x in sn[:k] for i in x["ids"])
                        <= r["hell"])
                    for k in range(1, len(sn) + 1)]
        pruefe("L46 nach jedem Paket EINMAL neu gezeichnet (vc.refresh), im "
               "Auftrag und nach seinem Material", je_paket == [1, 1, 1],
               je_paket)
        erst = popup.index(True) if True in popup else None
        pruefe("L46 das Lauf-Fenster steht ab Paket 1 und geht zwischen den "
               "Paketen nicht zu", erst is not None
               and all(popup[erst:]), "%d Proben, zu nach Beginn: %d" % (
                   len(popup), popup[erst or 0:].count(False)))
        ende = time.monotonic() + 6
        while time.monotonic() < ende and kern._LAUF_POPUP["w"].isVisible():
            _APP.processEvents()
            time.sleep(0.02)
        pruefe("L46 nach dem Lauf ist das Fenster zu",
               not kern._LAUF_POPUP["w"].isVisible())

        # KONTROLLE: dieselbe Folge ohne das Feld — das Bild aus dem Film.
        ende = time.monotonic() + 6
        while time.monotonic() < ende and d.refresh_nachholen:
            _APP.processEvents()
            time.sleep(0.02)
        cw.refreshs = []
        d.ms_je_teil = 1000.0
        k_a, k_sn, _p = _l46_lauf(kern, port, cw, "L46_alt", altes_feld=True)
        k_alle = [i for x in k_sn for i in x["ids"]]
        pruefe("L46 KONTROLLE: ohne das Feld wird jedes Paket versteckt, "
               "nach Paket 1 ist nichts nachgezogen",
               k_a.get("ok") and set(k_alle) <= cw.versteckt
               and not set(k_sn[0]["ids"]) & set(k_sn[0]["hell"]),
               "versteckt %d von %d" % (len(set(k_alle) & cw.versteckt),
                                        len(k_alle)))
        ende = time.monotonic() + 6
        while time.monotonic() < ende and set(k_alle) & cw.unsichtbar:
            _APP.processEvents()
            time.sleep(0.02)
        pruefe("L46 und im Leerlauf trotzdem aufgedeckt (bisheriger Weg)",
               not set(k_alle) & cw.unsichtbar)
        ende = time.monotonic() + 6
        while (time.monotonic() < ende
               and not any(not r["im_auftrag"] for r in cw.refreshs)):
            _APP.processEvents()
            time.sleep(0.02)
        pruefe("L46 KONTROLLE: ohne das Feld wird nur im LEERLAUF neu "
               "gezeichnet, in keinem Paket (die Zaehlung oben unterscheidet "
               "beides)",
               any(not r["im_auftrag"] for r in cw.refreshs)
               and not any(r["im_auftrag"] for r in cw.refreshs),
               "im Auftrag %d, im Leerlauf %d" % (
                   sum(1 for r in cw.refreshs if r["im_auftrag"]),
                   sum(1 for r in cw.refreshs if not r["im_auftrag"])))
    finally:
        if d is not None:
            pruefe("L46 Dienst laesst sich sauber beenden", _alle_beenden(kern))
        cw.entfernen()
# --- Chat: was ueber einen Cadwork-Neustart bleibt (Film 2026-09-25) --------
# Befunde: nach jedem Neustart stand die Denkstufe wieder auf "sehr hoch"
# (und das Modell auf der Vorgabe); "fertig · 1.40 USD" wirkte im Abo wie
# Kosten je Lauf. Die Freigabe-Stufe soll ABSICHTLICH nicht bleiben.
# chat.json ist hier die Temp-Datei aus OPEN_MCP_CAD_CHAT_EINSTELLUNGEN
# (oben im Gate) — nie das echte Profil.

def _einst_setzen(inhalt):
    """chat.json roh schreiben (str/bytes) oder mit None entfernen."""
    pfad = os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"]
    if inhalt is None:
        try:
            os.remove(pfad)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "wb") as fh:
        fh.write(inhalt if isinstance(inhalt, bytes)
                 else inhalt.encode("utf-8"))


def _einst_lesen():
    """chat.json, wie es auf der Platte steht — None, wenn es fehlt."""
    try:
        with open(os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"],
                  encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _alle_werte(obj):
    """Jeder Schluessel und jeder Wert in einem JSON-Baum, flach."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _alle_werte(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _alle_werte(v)
    else:
        yield obj


def _neustart(D=None):
    """Als waere Cadwork neu gestartet: kein Dock, kein Zustand, frisch
    gebaut. Chat.json bleibt — genau darum geht es."""
    _frischer_start()
    return aufbauen(D=D)


def _modus_feld(z):
    """Der Modus, den das Chatfenster ZEIGT: der Modus-Knopf der Leiste
    (seit K3; eine Stelle fuer alle Zellen)."""
    return z["w"]["chat_modus"].property("modus")


def _modus_eintraege(z):
    """Den Modus-Aufklapper oeffnen wie ein Klick. -> seine Eintraege."""
    D = sys.modules.get("a_dash_live")
    knopf = z["w"]["chat_modus"]
    knopf.click()
    auf = z["w"]["chat_modus_auf"]
    return list(getattr(auf, "eintraege", []))


def _modus_klick(z, modus):
    """Wie eine Wahl des Nutzers: den Knopf druecken, im Aufklapper den
    Eintrag des Modus anklicken. -> gefunden?"""
    for e in _modus_eintraege(z):
        if getattr(e, "wert", None) == modus:
            e.click()
            return True
    z["w"]["chat_modus_auf"].hide()
    return False


def _modus_tipp(z):
    """(Tooltip des Modus-Knopfs, sichtbarer Satz des GEZEIGTEN Modus im
    Aufklapper)."""
    tipp = z["w"]["chat_modus"].toolTip()
    satz = ""
    for e in _modus_eintraege(z):
        if getattr(e, "wert", None) == _modus_feld(z):
            satz = e.satz.text()
    z["w"]["chat_modus_auf"].hide()
    return tipp, satz


def _chat_anzeige(D, z):
    """(Modell, Denkstufe, Modus im Feld, Modus, nach dem der Chat entscheidet)."""
    w = z["w"]
    C = D._chat_modul()
    return (D._modellwahl(w["chat_modell"]), w["chat_stufe"].currentData(),
            _modus_feld(z),
            (z.get("chat") or {}).get("modus", C.MODUS_VORGABE))


def _waehlen(feld, wert):
    """Wie ein Klick des Nutzers: Eintrag setzen UND `activated` senden."""
    i = feld.findData(wert)
    feld.setCurrentIndex(i)
    feld.activated.emit(i)
    return i


def zelle_wahl_gemerkt():
    """L37: Modell und Denkstufe ueberleben den Neustart (chat.json)."""
    try:
        _einst_setzen(None)
        D, z, d = _neustart()
        C = D._chat_modul()
        pruefe("L37 Vorbedingung: ohne chat.json stehen die Vorgaben da, und "
               "das Aufbauen allein schreibt nichts",
               _chat_anzeige(D, z)[:2] == (C.MODELL_VORGABE, C.EFFORT_VORGABE)
               and _einst_lesen() is None,
               repr((_chat_anzeige(D, z), _einst_lesen())))
        w = z["w"]
        _waehlen(w["chat_stufe"], "high")
        _waehlen(w["chat_modell"], "opus")
        gemerkt = _einst_lesen() or {}
        pruefe("L37 die Wahl steht in chat.json (Modell je Anbieter, "
               "Denkstufe)",
               (gemerkt.get("modell") or {}).get("claude") == "opus"
               and gemerkt.get("denkstufe") == "high", gemerkt)
        D, z, d = _neustart()
        pruefe("L37 nach dem Neustart steht die Wahl wieder da",
               _chat_anzeige(D, z)[:2] == ("opus", "high"),
               repr(_chat_anzeige(D, z)))

        # Ein von Hand getippter Name hat kein `activated` — er wird beim
        # Start gemerkt.
        with _ChatStartAttrappe(D, z) as att:
            z["w"]["chat_modell"].setEditText("claude-opus-4-7")
            _senden_klick(D, z)                    # startet (S8)
        pruefe("L37 ein getippter Name geht an den Start und wird gemerkt",
               [k.get("modell") for k in att.gestartet] == ["claude-opus-4-7"]
               and ((_einst_lesen() or {}).get("modell") or {}).get("claude")
               == "claude-opus-4-7", repr((att.gestartet, _einst_lesen())))
        D, z, d = _neustart()
        pruefe("L37 ... und steht nach dem Neustart im Feld",
               _chat_anzeige(D, z)[:2] == ("claude-opus-4-7", "high"),
               repr(_chat_anzeige(D, z)))

        _einst_setzen(None)
        D, z, d = _neustart()
        pruefe("L37 KONTROLLE: ohne chat.json wieder die Vorgaben — die Wahl "
               "oben kam aus der Datei",
               _chat_anzeige(D, z)[:2] == (C.MODELL_VORGABE, C.EFFORT_VORGABE)
               and C.EFFORT_VORGABE != "high" and C.MODELL_VORGABE != "opus",
               repr(_chat_anzeige(D, z)))
    finally:
        _einst_setzen(None)
        _frischer_start()


def _modus_nach_neustart(D=None):
    """-> (Modus im Feld, Modus, den der Chat nimmt, Denkstufe)."""
    D, z, d = _neustart(D)
    _m, stufe, feld, chat = _chat_anzeige(D, z)
    return feld, chat, stufe


def zelle_modus_gemerkt():
    """L38 (seit 2026-09-27 fuer die Modi): der gewaehlte Modus bleibt ueber
    einen Neustart — "Alles automatisch" aber NIE: dann beginnt die naechste
    Sitzung mit "Cadwork frei", auch wenn chat.json "alles_auto" traegt."""
    try:
        _einst_setzen(None)
        D, z, d = _neustart()
        C = D._chat_modul()
        pruefe("L38 ohne chat.json: 'Fragen' im Feld und im Chat",
               _chat_anzeige(D, z)[2:] == ("fragen", "fragen")
               and C.MODUS_VORGABE == "fragen", _chat_anzeige(D, z))
        _modus_klick(z, "nur_lesen")
        feld, chat, _s = _modus_nach_neustart()
        pruefe("L38 'Nur lesen' gewaehlt: nach dem Neustart wieder da (Feld "
               "UND Chat)", feld == chat == "nur_lesen"
               and (_einst_lesen() or {}).get("modus") == "nur_lesen",
               repr((feld, chat, _einst_lesen())))
        D, z, d = _neustart()
        _modus_klick(z, "alles_auto")
        pruefe("L38 Vorbedingung: 'Alles automatisch' gilt in DIESER Sitzung",
               z["chat"].get("modus") == "alles_auto", z["chat"])
        _waehlen(z["w"]["chat_stufe"], "high")     # schreibt chat.json
        with _ChatStartAttrappe(D, z) as att:      # schreibt es noch einmal
            _senden_klick(D, z)                    # startet (S8)
        gemerkt = _einst_lesen() or {}
        werte = list(_alle_werte(gemerkt))
        pruefe("L38 chat.json traegt 'Cadwork frei' statt 'Alles "
               "automatisch', obwohl dreimal geschrieben",
               len(att.gestartet) == 1 and gemerkt.get("denkstufe") == "high"
               and gemerkt.get("modus") == "cadwork_frei"
               and "alles_auto" not in werte, gemerkt)
        feld, chat, stufe = _modus_nach_neustart()
        pruefe("L38 nach dem Neustart: 'Cadwork frei' (Feld UND Chat), die "
               "Denkstufe bleibt", feld == chat == "cadwork_frei"
               and stufe == "high", repr((feld, chat, stufe)))
        # Ein chat.json, das 'alles_auto' TRAEGT (Hand-Aenderung, andere
        # Fassung): die Sitzung beginnt trotzdem nicht damit.
        _einst_setzen(json.dumps({"modus": "alles_auto", "denkstufe": "high"}))
        feld, chat, stufe = _modus_nach_neustart()
        pruefe("L38 auch mit 'alles_auto' in chat.json beginnt die Sitzung "
               "mit 'Cadwork frei' (die Datei wurde gelesen: Denkstufe)",
               feld == chat == "cadwork_frei" and stufe == "high",
               repr((feld, chat, stufe)))
        # KONTROLLE 1: ein Dashboard, das den gemerkten Modus woertlich nimmt.
        M = _mutant(_anweisungen(
            "_gemerkter_modus", lambda s: isinstance(s, ast.Return)
            and "MODUS_STATT_AUTO" in ast.unparse(s), "return wert"))
        feld, chat, _s = _modus_nach_neustart(M)
        pruefe("L38 KONTROLLE: nimmt das Dock chat.json woertlich, beginnt die "
               "Sitzung in 'Alles automatisch'", M._mutant_treffer == [1]
               and feld == chat == "alles_auto", repr((feld, chat)))
        # KONTROLLE 2: ein Merken ohne die Umschreibung.
        _einst_setzen(None)
        M = _mutant(_anweisungen(
            "_modus_merken", _beginnt("wert = C.MODUS_STATT_AUTO"),
            "wert = modus"))
        _D, z, _d = _neustart(M)
        _modus_klick(z, "alles_auto")
        pruefe("L38 KONTROLLE: ohne die Umschreibung steht 'alles_auto' in "
               "chat.json", M._mutant_treffer == [1]
               and (_einst_lesen() or {}).get("modus") == "alles_auto",
               _einst_lesen())
    finally:
        _einst_setzen(None)
        _frischer_start()


def _dock_mit_datei(inhalt, D=None):
    """Dock mit diesem chat.json neu bauen, dann auf einen Anbieter mit
    Adresse und zurueck wechseln (liest `basis`/`modell`) und die Wahl
    merken. -> (Befund-Text oder None, Anzeige)."""
    import io
    _einst_setzen(inhalt)
    alt_err, puffer = sys.stderr, io.StringIO()
    sys.stderr = puffer                # der Mutant meldet seinen Fehler dort
    try:
        D, z, d = _neustart(D)
        w = z["w"]
        if D.CHAT_TAB not in w or w.get("chat_ersatz") is not None:
            return "Chat-Tab nicht gebaut: %s" % puffer.getvalue()[:160], None
        C = D._chat_modul()
        A = D._anbieter_modul()
        anzeige = _chat_anzeige(D, z)
        anbieter = w["chat_anbieter"].currentData()
        for kennung in ("openai", "claude"):
            w["chat_anbieter"].blockSignals(True)
            w["chat_anbieter"].setCurrentIndex(
                w["chat_anbieter"].findData(kennung))
            w["chat_anbieter"].blockSignals(False)
            D._anbieter_gewechselt(z, merken=True)
        D._cli_wahl_merken(z)
        if anbieter != A.ANBIETER_VORGABE:
            return "Anbieter %r statt der Vorgabe" % (anbieter,), anzeige
        if anzeige[:2] != (C.MODELL_VORGABE, C.EFFORT_VORGABE):
            return "keine Vorgabe: %r" % (anzeige[:2],), anzeige
        return None, anzeige
    except Exception as exc:                          # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc), None
    finally:
        sys.stderr = alt_err


# chat.json, wie es kaputt oder fremd vorkommen kann. Jede Form trifft eine
# andere Stelle: die Datei selbst, die oberste Ebene, die Tabellen darunter,
# die Werte darin.
KAPUTTE_EINSTELLUNGEN = (
    ("kein JSON", "{kaputt"),
    ("kein UTF-8", b"\xff\xfe{\x00"),
    ("Liste statt Objekt", "[1, 2, 3]"),
    ("tief verschachtelt", "[" * 100000),
    ("Tabellen als Text", json.dumps({"modell": "opus", "basis": "http://x",
                                      "denkstufe": ["high"],
                                      "anbieter": ["claude"]})),
    ("falsche Typen, unbekannte Werte", json.dumps(
        {"modell": {"claude": 42, "openai": ["x"]}, "basis": {"openai": 7},
         "denkstufe": "turbo", "anbieter": "gibtsnicht"})),
    ("Steuerzeichen und Ueberlaenge", json.dumps(
        {"modell": {"claude": "opus\nrm"}, "denkstufe": None})),
    ("Ueberlaenge", json.dumps({"modell": {"claude": "o" * 5000}})),
)


def zelle_kaputte_einstellungen():
    """L39: kein chat.json kostet das Dock — Rueckfall auf die Vorgaben."""
    try:
        for name, inhalt in KAPUTTE_EINSTELLUNGEN:
            befund, anzeige = _dock_mit_datei(inhalt)
            pruefe("L39 chat.json %s: Dock und Chat-Tab stehen, Vorgaben, "
                   "Anbieterwechsel und Merken gehen" % name,
                   befund is None, befund)
        befund, anzeige = _dock_mit_datei(json.dumps(
            {"modell": {"claude": "opus"}, "denkstufe": "high",
             "anbieter": "claude"}))
        pruefe("L39 KONTROLLE: ein gutes chat.json wird gelesen — die "
               "Vorgaben oben sind ein Rueckfall, kein Nichtlesen",
               befund is not None and anzeige is not None
               and anzeige[:2] == ("opus", "high"), repr((befund, anzeige)))
        # KONTROLLE: das Auslesen ohne Schutz, wie es bis heute bei den
        # Adressen und Modellen der Schluessel-Anbieter stand. Dieselbe
        # Messung muss es sehen.
        M = dashboard_laden()
        M._gemerkt = lambda e, feld, kennung: (e.get(feld) or {}).get(kennung)
        befund, _a = _dock_mit_datei(dict(KAPUTTE_EINSTELLUNGEN)
                                     ["Tabellen als Text"], M)
        pruefe("L39 KONTROLLE: ohne den Schutz kostet 'Tabellen als Text' "
               "den Chat-Tab", befund is not None
               and "Chat-Tab nicht gebaut" in befund, befund)
    finally:
        _einst_setzen(None)
        _frischer_start()


def _verlauf_texte(z):
    """Die Eintraege des Verlaufs ohne Zeitlinien (K5: `Verlauf.texte`):
    eigene Nachricht "Du:  …", Antwort, Kopf einer Schrittgruppe, Notiz."""
    return z["w"]["chat_verlauf"].texte()


def _hinweis_im_aufklapper(D, z):
    """Oeffnet den Modell-Aufklapper und liest den Hinweis "gilt ab dem
    nächsten Chat" (seit 2026-09-28 dort statt unter der Leiste). -> Text
    oder ""."""
    from PyQt6.QtWidgets import QLabel
    D._modell_aufklappen(z)
    auf = z["w"]["chat_modell_auf"]
    texte = [lb.text() for lb in auf.findChildren(QLabel)
             if not lb.isHidden() and "nächsten Chat" in lb.text()]
    auf.hide()
    return texte[0] if texte else ""


def _schritt_zeilen(z):
    """Die Zeilen aller Schrittgruppen des Verlaufs (auch zugeklappte)."""
    return [t for g in z["w"]["chat_verlauf"].widgets("schritte")
            for t in g.zeilen()]


def _fuss(z):
    """Der Tooltip der letzten Antwort — dort steht seit 2026-09-28 der
    Schluss des Zugs ("fertig · 18 Token")."""
    ki = z["w"]["chat_verlauf"].widgets("ki")
    return ki[-1].text.toolTip() if ki else ""


def _schluss_zeigen(D, z, anbieter, kosten=1.4):
    """Ein fertiger Zug mit `total_cost_usd` -> der Schluss (Tooltip der
    Antwort; seit 2026-09-28 keine eigene Zeile mehr)."""
    chat = z["chat"]
    if anbieter is not None:
        chat["anbieter"] = anbieter
    chat["ereignisse"] = [{"art": "ich", "text": "zeichne"},
                          {"art": "text", "text": "Gezeichnet."},
                          {"art": "schluss", "kosten": kosten, "abgelehnt": 0,
                           "fehler": False, "text": ""}]
    chat["stand"] = chat.get("stand", 0) + 1
    z["w"]["chat_verlauf"]._n = None               # neu zeichnen erzwingen
    D._chat_zeichnen(z)
    return _fuss(z)


def zelle_abo_ohne_betrag():
    """L40: im Abo kein USD-Betrag, bei Anbietern mit Schluessel wie bisher."""
    try:
        _einst_setzen(None)
        D, z, d = _neustart()
        with _ChatStartAttrappe(D, z) as att:
            _senden_klick(D, z)                    # startet (S8)
        pruefe("L40 der Start von Claude Code merkt den Anbieter fuer die "
               "Anzeige", len(att.gestartet) == 1
               and z["chat"].get("anbieter") == "claude", z["chat"])
        zeile = _schluss_zeigen(D, z, None)       # so, wie der Start ihn ließ
        pruefe("L40 Claude Code (Abo): 'fertig' ohne USD-Betrag (Tooltip "
               "der Antwort)",
               zeile.startswith("fertig") and "USD" not in zeile, zeile)
        zeile = _schluss_zeigen(D, z, "codex")
        pruefe("L40 Codex (Abo): ebenso ohne Betrag",
               zeile.startswith("fertig") and "USD" not in zeile, zeile)
        for kennung in [a["id"] for a in D._anbieter_modul().ANBIETER
                        if a.get("schluessel") == "pflicht"]:
            zeile = _schluss_zeigen(D, z, kennung)
            pruefe("L40 KONTROLLE: %s (API-Schlüssel) zeigt den Betrag wie "
                   "bisher" % kennung, "1.40 USD" in zeile, zeile)
    finally:
        _frischer_start()


# --- Gegenpruefung 2026-09-26: Luecken hinter L37-L40 -----------------------
# Eine unabhaengige Mutanten-Pruefung liess M13, M20 und M25 im Dashboard
# ueberleben, dazu zwei Befunde (tief verschachteltes chat.json beim
# Schreiben, Freigabe-Feld nach einem Neubau des Docks). Jede Zelle hier
# faehrt ihre Kontrolle mit GENAU diesem Mutanten aus der Quelle (`_mutant`)
# und verlangt, dass die Mutation getroffen hat.

def _stufe_allein(laden=None):
    """NUR die Denkstufe waehlen — kein Modellwechsel, kein Start —, dann ein
    frischer Start. -> (Denkstufe in chat.json, Denkstufe im Feld danach)."""
    _einst_setzen(None)
    _D, z, _d = _neustart(laden)
    _waehlen(z["w"]["chat_stufe"], "high")
    gemerkt = (_einst_lesen() or {}).get("denkstufe")
    _D, z, _d = _neustart(laden)
    return gemerkt, z["w"]["chat_stufe"].currentData()


def zelle_stufe_allein():
    """L41 (Mutant M13): die Wahl der Denkstufe ALLEIN wird gemerkt. L37
    waehlte danach noch ein Modell — dessen `activated` merkte die Stufe
    mit, und ohne die Verbindung `stufe.activated` blieb L37 gruen."""
    try:
        C = dashboard_laden()._chat_modul()
        datei, feld = _stufe_allein()
        pruefe("L41 nur die Denkstufe gewaehlt (kein Modell, kein Start): sie "
               "steht in chat.json und nach dem Neustart im Feld",
               datei == feld == "high" and C.EFFORT_VORGABE != "high",
               repr((datei, feld)))
        M = _mutant(_anweisungen("_tab_chat",
                                 _beginnt("stufe.activated.connect(")))
        datei_m, feld_m = _stufe_allein(M)
        pruefe("L41 KONTROLLE M13: ohne stufe.activated -> Merken ist die "
               "Wahl nach dem Neustart weg (Vorgabe)",
               M._mutant_treffer == [1] and datei_m is None
               and feld_m == C.EFFORT_VORGABE,
               repr((M._mutant_treffer, datei_m, feld_m)))
    finally:
        _einst_setzen(None)
        _frischer_start()


#: Je ein Werkzeug, das in den Modi verschieden entschieden wird: Cadwork
#: aendern, lesen, und eins am Rechner.
_WERKZEUGE_PROBE = ("mcp__open-mcp-cad__execute_cadwork_command", "Read",
                    "Bash")


def _modus_nach_neubau(weg, laden=None):
    """'Alles automatisch' gewaehlt, ein Chat laeuft — dann baut sich das
    Dock in DERSELBEN Cadwork-Sitzung neu: `weg` 'geloescht' (Cadwork raeumt
    das Dock ab, der naechste Klick baut es) oder 'form' (andere FORM).
    -> dict mit den Messwerten."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    _frischer_start()
    client, kern = _Client([]), _VerbindKern(1, 0)
    D, z, _r = _klick(client, kern, verbinden=False, laden=laden)
    C = D._chat_modul()
    feld = z["w"]["chat_modus"]
    _modus_klick(z, "alles_auto")                     # die Wahl des Nutzers
    chat = z["chat"]
    chat.update(an=True, ereignisse=[], stand=1)      # der Chat laeuft
    m = {"vorher": (_modus_feld(z), chat.get("modus"))}
    if weg == "geloescht":
        altes = z["dock"]
        altes.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    else:
        z["form"] = -1
    _D2, z2, _r = _klick(client, kern, verbinden=False, laden=laden)
    m["neu_gebaut"] = (z2 is z and z2["w"]["chat_modus"] is not feld
                       and z2["chat"] is chat)
    m["feld"] = _modus_feld(z2)
    # So entscheidet der Chat (omcad_a_chat, Schleife, Codex).
    m["chat"] = chat.get("modus", C.MODUS_VORGABE)
    m["urteil_feld"] = [C.entscheiden(m["feld"], t) for t in _WERKZEUGE_PROBE]
    m["urteil_chat"] = [C.chat_entscheiden(chat, t) for t in _WERKZEUGE_PROBE]
    # Danach bedient der Nutzer das NEUE Feld: der laufende Chat folgt.
    _modus_klick(z2, "fragen")
    m["danach"] = chat.get("modus")
    chat["an"] = False
    kern.aufraeumen()
    return m


def zelle_modus_nach_neubau():
    """L42 (SICHERHEIT): baut sich das Dock in derselben Cadwork-Sitzung neu,
    zeigt das Modus-Feld den Modus, nach dem der laufende Chat WIRKLICH
    entscheidet. Befund 2026-09-26 (damals mit der Freigabestufe): dort stand
    die Vorgabe, waehrend der Chat weiter alles ohne Karte liess."""
    try:
        _einst_setzen(None)
        for weg, text in (("geloescht", "Cadwork loescht das Dock"),
                          ("form", "andere FORM")):
            m = _modus_nach_neubau(weg)
            pruefe("L42 Vorbedingung (%s): 'Alles automatisch' gewaehlt, das "
                   "Dock neu gebaut, derselbe Chat" % text,
                   m["vorher"] == ("alles_auto", "alles_auto")
                   and m["neu_gebaut"], m)
            pruefe("L42 %s, Chat laeuft in 'Alles automatisch': das neue Feld "
                   "zeigt es und entscheidet fuer jedes Werkzeug wie der Chat"
                   % text, m["feld"] == m["chat"] == "alles_auto"
                   and m["urteil_feld"] == m["urteil_chat"], m)
            pruefe("L42 %s: das neue Feld wirkt auf den laufenden Chat" % text,
                   m["danach"] == "fragen", m)
        feld, chat, _s = _modus_nach_neustart()
        pruefe("L42 ein echter Neustart beginnt mit der letzten Wahl im NEUEN "
               "Feld ('Fragen'), nicht mit dem Modus des alten Chats (Feld "
               "UND Chat; 'Alles automatisch' nie: L38)",
               feld == chat == "fragen", repr((feld, chat)))
        # KONTROLLE: ein Dock, das beim Bau den laufenden Modus nicht ansieht.
        _einst_setzen(None)
        M = _mutant(_anweisungen(
            "_modus_wirksam", lambda s: isinstance(s, ast.If)
            and ast.unparse(s.test) == "'modus' in chat"))
        k = _modus_nach_neubau("geloescht", laden=lambda: M)
        pruefe("L42 KONTROLLE: ohne Blick auf den laufenden Chat zeigt das "
               "neue Feld nach dem Neubau NICHT 'Alles automatisch'",
               M._mutant_treffer == [1] and k["feld"] != "alles_auto", k)
    finally:
        _einst_setzen(None)
        _frischer_start()


#: Tiefer, als `json.dump(indent=...)` zurueckschreibt, flacher, als
#: `json.load` noch liest (gemessen 2026-09-26, Python 3.12.10: Lesen bis
#: ~2000, Schreiben ab 1000 RecursionError). L43 misst die Vorbedingung.
_TIEFE = 1500
_TIEF_JSON = ('{"anbieter": "codex", "x": ' + "[" * _TIEFE + "]" * _TIEFE
              + "}")


def _alt_schreiben(daten):
    """So schrieb `einstellungen_schreiben` bis 2026-09-26 — die Kontrolle."""
    pfad = os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"]
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as fh:
            json.dump(daten, fh, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def _anbieter_tief_lauf(laden=None, alt=False):
    """chat.json 1500 Ebenen tief, Dock bauen, der Nutzer waehlt einen
    anderen Anbieter (das Signal wie bei einem Klick). `alt`: das Schreiben
    von vorher. -> dict mit den Messwerten."""
    import io
    _einst_setzen(_TIEF_JSON)
    pfad = os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"]
    D, z, _d = _neustart(laden)
    w = z["w"]
    A = D._anbieter_modul()
    m = {"gelesen": w["chat_anbieter"].currentData()}
    echt = A.einstellungen_schreiben
    if alt:
        A.einstellungen_schreiben = _alt_schreiben
    entkommen = []
    alt_hook, alt_err, puffer = sys.excepthook, sys.stderr, io.StringIO()
    # PyQt6 ruft fuer eine Ausnahme, die aus einem Slot laeuft, den
    # excepthook — ohne eigenen (wie in Cadwork) qFatal. Hier wird sie
    # nur gezaehlt.
    sys.excepthook = lambda t, v, tb: entkommen.append(t.__name__)
    sys.stderr = puffer
    try:
        w["chat_anbieter"].setCurrentIndex(
            w["chat_anbieter"].findData("openai"))
    finally:
        sys.excepthook, sys.stderr = alt_hook, alt_err
        A.einstellungen_schreiben = echt
    with open(pfad, "rb") as fh:
        nachher = fh.read()
    try:
        json.loads(nachher.decode("utf-8"))
        lesbar = True
    except (ValueError, RecursionError):
        lesbar = False
    m.update(entkommen=entkommen, lesbar=lesbar,
             gleich=nachher == _TIEF_JSON.encode("utf-8"),
             gemeldet="RecursionError" in puffer.getvalue(),
             rest=sorted(set(os.listdir(os.path.dirname(pfad)))
                         - {"chat.json"}),
             felder=not w["chat_api"].isHidden() and w["chat_stufe"].isHidden())
    return m


_SLOT_PROBE = r'''
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QComboBox
app = QApplication([])
feld = QComboBox()
feld.addItems(["a", "b"])
def wirft():
    raise RecursionError("tief")
feld.currentIndexChanged.connect(lambda: wirft())
if sys.argv[1:] == ["haken"]:
    sys.excepthook = lambda *a: None
feld.setCurrentIndex(1)
print("LEBT")
'''


def _slot_ausnahme(haken):
    """Ein Prozess, in dem eine Ausnahme aus einem Qt-Slot laeuft.
    -> (Rueckgabecode, lief danach weiter?)."""
    r = subprocess.run([sys.executable, "-c", _SLOT_PROBE]
                       + (["haken"] if haken else []),
                       capture_output=True, text=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, "LEBT" in r.stdout


def zelle_anbieter_tief():
    """L43: ein 1500 Ebenen tief verschachteltes chat.json kostet beim
    Anbieterwechsel weder Cadwork noch die Datei. Vorher: json.load las es,
    das Zurueckschreiben warf RecursionError (gefangen war nur OSError), die
    Ausnahme lief aus dem Qt-Slot (in Cadwork qFatal), und chat.json war da
    schon halb geschrieben."""
    try:
        code, lebt = _slot_ausnahme(haken=False)
        code_k, lebt_k = _slot_ausnahme(haken=True)
        pruefe("L43 gemessen: eine Ausnahme aus einem Qt-Slot beendet den "
               "Prozess (PyQt6 ohne eigenen excepthook: qFatal)",
               code != 0 and not lebt, (code, lebt))
        pruefe("L43 KONTROLLE: mit eigenem excepthook laeuft derselbe Prozess "
               "weiter", code_k == 0 and lebt_k, (code_k, lebt_k))
        m = _anbieter_tief_lauf()
        pruefe("L43 Vorbedingung: das tiefe chat.json wird gelesen (Anbieter "
               "'codex' daraus)", m["gelesen"] == "codex", m["gelesen"])
        pruefe("L43 Anbieterwechsel bei %d Ebenen: nichts laeuft aus dem "
               "Slot, der Wechsel wirkt, chat.json Byte fuer Byte unberuehrt, "
               "keine Temp-Datei" % _TIEFE,
               not m["entkommen"] and m["felder"] and m["gleich"]
               and not m["rest"], m)
        # KONTROLLE 1: das Schreiben von vorher, der Slot von jetzt. Der Slot
        # faengt (gemeldet auf stderr), aber die Datei ist halb geschrieben.
        k = _anbieter_tief_lauf(alt=True)
        pruefe("L43 KONTROLLE: mit dem alten Schreiben ist chat.json danach "
               "halb geschrieben (der Slot faengt und meldet)",
               not k["entkommen"] and k["gemeldet"] and not k["gleich"]
               and not k["lesbar"], k)
        # KONTROLLE 2: Schreiben UND Slot von vorher — die Ausnahme laeuft
        # aus dem Slot. In Cadwork waere das qFatal (s. o.).
        M = _mutant(_anweisungen(
            "_tab_chat", _beginnt("anbieter.currentIndexChanged.connect("),
            "anbieter.currentIndexChanged.connect("
            "lambda: _anbieter_gewechselt(z, merken=True))"))
        k = _anbieter_tief_lauf(laden=M, alt=True)
        pruefe("L43 KONTROLLE: Schreiben und Slot von vorher -> "
               "RecursionError laeuft aus dem Slot",
               M._mutant_treffer == [1]
               and k["entkommen"] == ["RecursionError"], k)
    finally:
        _einst_setzen(None)
        _frischer_start()


class _AnbieterStartAttrappe:
    """Das Anbieter-Modul im Speicher, dessen `starten` nur mitschreibt —
    kein MCP-Server, kein HTTP. Stellt alles zurueck (`with`)."""
    NAME = "omcad_a_anbieter_A"

    def __init__(self, D):
        self.D, self.gestartet = D, []

    def __enter__(self):
        self.echt = self.D._anbieter_modul()

        def starten(chat, kennung, modell, erlauben, **k):
            self.gestartet.append((kennung, modell, k.get("basis")))
            chat.update(an=True, ereignisse=[], freigaben=[], schleife=None,
                        proc=None)
        m = types.ModuleType(self.echt.__name__)
        m.__dict__.update(self.echt.__dict__)
        m.starten = starten
        sys.modules[self.NAME] = m
        return self

    def __exit__(self, *_):
        sys.modules[self.NAME] = self.echt


def _schluessel_start_lauf(laden=None):
    """chat.json mit `modell` und `basis` als TEXT (eine fremde Fassung),
    Start von Ollama ueber den Knopf, dann ein Neustart. -> dict."""
    _einst_setzen(json.dumps({"anbieter": "ollama", "modell": "opus",
                              "basis": "http://x"}))
    D, z, _d = _neustart(laden)
    w = z["w"]
    m = {"gewaehlt": w["chat_anbieter"].currentData(), "geworfen": None}
    w["chat_modell"].setEditText("qwen3")
    import io
    alt_err, puffer = sys.stderr, io.StringIO()
    with _AnbieterStartAttrappe(D) as att:
        # Seit S8 startet der Senden-Knopf, und sein Slot laeuft durch
        # `_sicher`: eine Ausnahme landet auf stderr statt im qFatal.
        sys.stderr = puffer
        try:
            _senden_klick(D, z)               # startet (S8, vorher "Starten")
        except Exception as exc:              # noqa: BLE001
            m["geworfen"] = type(exc).__name__
        finally:
            sys.stderr = alt_err
    if m["geworfen"] is None and "Fehler im Takt (" in puffer.getvalue():
        m["geworfen"] = puffer.getvalue().split(": ", 1)[1].split(":")[0]
    m["gestartet"] = att.gestartet
    m["datei"] = _einst_lesen()
    _D, z, _d = _neustart(laden)
    m["danach"] = (z["w"]["chat_anbieter"].currentData(),
                   D._modellwahl(z["w"]["chat_modell"]),
                   z["w"]["chat_basis"].text())
    return m


def zelle_schluessel_start():
    """L44 (Mutant M25): der Start eines Schluessel-Anbieters repariert ein
    chat.json, in dem `modell`/`basis` Text statt Tabelle sind. Die
    Reparatur (`_eintragen`) war nur ohne Qt geprueft (P10)."""
    try:
        m = _schluessel_start_lauf()
        # Die Adresse, die das Dock fuer Ollama vorgibt — aus ANBIETER.
        basis = dashboard_laden()._anbieter_modul().anbieter("ollama")["basis"]
        pruefe("L44 Vorbedingung: das fremde chat.json wird gelesen "
               "(Anbieter 'ollama' daraus)", m["gewaehlt"] == "ollama", m)
        pruefe("L44 Start mit {'modell': 'opus', 'basis': 'http://x'}: kein "
               "Fehler, der Start laeuft, beides steht danach als Tabelle "
               "in chat.json",
               m["geworfen"] is None
               and m["gestartet"] == [("ollama", "qwen3", basis)]
               and m["datei"] == {"anbieter": "ollama",
                                  "modell": {"ollama": "qwen3"},
                                  "basis": {"ollama": basis}}, m)
        pruefe("L44 ... und nach dem Neustart stehen Anbieter, Modell und "
               "Adresse wieder da", m["danach"] == ("ollama", "qwen3", basis),
               m["danach"])
        for kurz, feld in (("M25", "modell"), ("M25b", "basis")):
            M = _mutant(_anweisungen(
                "_chat_anbieter_starten",
                _beginnt("_eintragen(e, '%s'" % feld),
                "e.setdefault('%s', {})[a['id']] = %s" % (feld, feld)))
            k = _schluessel_start_lauf(M)
            pruefe("L44 KONTROLLE %s: ohne _eintragen fuer '%s' wirft der "
                   "Start (seit S8 aus dem Senden-Knopf, dessen Slot es in "
                   "`_sicher` nach stderr meldet)" % (kurz, feld),
                   M._mutant_treffer == [1] and k["geworfen"] == "TypeError",
                   (M._mutant_treffer, k["geworfen"]))
    finally:
        _einst_setzen(None)
        _frischer_start()


def _fremde_wahl_lauf(laden=None):
    """Mit einem Anbieter, der NICHT Claude Code ist, Modell und Denkstufe
    waehlen. -> dict: je Anbieter (chat.json unveraendert?, Rueckgabe von
    _cli_wahl_merken, chat.json danach)."""
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    w = z["w"]
    z["modelle"] = {"openai": ["gpt-a", "gpt-b"]}     # die Liste des Dienstes
    m = {}
    for kennung in ("openai", "codex", "claude"):
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData(kennung))
        w["chat_stufe"].setCurrentIndex(w["chat_stufe"].findData("high"))
        vorher = _einst_lesen()
        if kennung == "openai":
            _waehlen(w["chat_modell"], "gpt-b")       # Wahl aus der Liste
        elif kennung == "codex":
            w["chat_modell"].setEditText("gpt-5-codex")
        else:
            _waehlen(w["chat_modell"], "opus")
        rueck = D._cli_wahl_merken(z)
        m[kennung] = (vorher == _einst_lesen(), rueck, _einst_lesen())
    return m


def zelle_nur_claude_merkt():
    """L45 (Mutant M20): `_cli_wahl_merken` merkt NUR fuer Claude Code.
    Eine Modellwahl aus der Liste eines Schluessel-Anbieters (activated)
    und Codex schreiben nichts nach chat.json."""
    try:
        m = _fremde_wahl_lauf()
        pruefe("L45 OpenAI: Modell aus der Liste gewaehlt -> chat.json "
               "unveraendert, _cli_wahl_merken False",
               m["openai"][:2] == (True, False), m["openai"])
        pruefe("L45 Codex: ebenso", m["codex"][:2] == (True, False),
               m["codex"])
        pruefe("L45 KONTROLLE: bei Claude Code schreibt dieselbe Wahl",
               not m["claude"][0]
               and ((m["claude"][2] or {}).get("modell") or {}).get("claude")
               == "opus", m["claude"])
        M = _mutant(_anweisungen(
            "_cli_wahl_merken",
            lambda s: (isinstance(s, ast.If)
                       and ast.unparse(s.test) == "a['art'] != 'cli'")))
        k = _fremde_wahl_lauf(M)
        pruefe("L45 KONTROLLE M20: ohne 'nur Claude Code' schreibt die Wahl "
               "bei OpenAI und Codex",
               M._mutant_treffer == [1] and not k["openai"][0]
               and not k["codex"][0], (M._mutant_treffer, k["openai"],
                                       k["codex"]))
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L47-L49: Freigabe-Tooltip, Zeichenmodus, Ordnerwahl (2026-09-26) -------

def _prototyp_gate():
    """test_a_prototyp als Modul — fuer seinen Richter `freigabe_hinweis_falsch`
    (EINE Stelle, die Tooltip und Verhalten vergleicht; sein main laeuft
    nicht)."""
    spec = importlib.util.spec_from_file_location(
        "a_prototyp_gate", os.path.join(HIER, "test_a_prototyp.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tooltip_lauf(laden=None):
    """Jeden Modus waehlen wie der Nutzer und Tooltip und Satz ablesen; dann
    mit 'Alles automatisch' und laufendem Chat das Dock neu bauen (andere
    FORM). -> dict."""
    _frischer_start()
    _einst_setzen(None)
    client, kern = _Client([]), _VerbindKern(1, 0)
    D, z, _r = _klick(client, kern, verbinden=False, laden=laden)
    C = D._chat_modul()
    m = {"bau": (_modus_feld(z),) + _modus_tipp(z), "tips": {}, "saetze": {},
         "chat": {}}
    for modus in C.MODUS_WERTE:
        _modus_klick(z, modus)
        m["tips"][modus], m["saetze"][modus] = _modus_tipp(z)
        m["chat"][modus] = z["chat"].get("modus")
    _modus_klick(z, "alles_auto")
    z["chat"].update(an=True, ereignisse=[], stand=1)
    z["form"] = -1
    _D2, z2, _r = _klick(client, kern, verbinden=False, laden=laden)
    m["neubau"] = (_modus_feld(z2),) + _modus_tipp(z2)
    z["chat"]["an"] = False
    kern.aufraeumen()
    return m


def zelle_modus_tooltip():
    """L47 (SICHERHEIT): Tooltip und Satz des Modus-Felds sagen fuer JEDEN
    Modus, was die Politik wirklich tut (Richter aus test_a_prototyp). Bis
    2026-09-26 stand beim Feld fest "Cadwork-Werkzeuge fragen IMMER", auch
    dort, wo Cadwork ohne Karte durchging."""
    try:
        richter = _prototyp_gate().modus_hinweis_falsch
        C = dashboard_laden()._chat_modul()
        m = _tooltip_lauf()
        falsch = richter(lambda s: m["tips"].get(s), C)
        pruefe("L47 im gebauten Dock: je Modus gewaehlt, der Tooltip stimmt "
               "mit der Politik (Modi und Werkzeuge aus der Quelle), der Chat "
               "nimmt den Modus", not falsch and m["chat"] == {
                   s: s for s in C.MODUS_WERTE}, repr(falsch))
        pruefe("L47 der sichtbare Satz ist der Tooltip",
               m["saetze"] == m["tips"], m["saetze"])
        pruefe("L47 beim Bau passt er zum gezeigten Modus",
               not richter(lambda s: m["bau"][1] if s == m["bau"][0]
                           else m["tips"][s], C), m["bau"])
        pruefe("L47 Neubau mit laufendem Chat in 'Alles automatisch': das "
               "neue Feld warnt", m["neubau"][0] == "alles_auto"
               and m["neubau"][1].startswith("Achtung")
               and not richter(lambda s: m["neubau"][1] if s == "alles_auto"
                               else m["tips"][s], C), m["neubau"])
        M = _mutant(_anweisungen("_modus_zeigen", _beginnt("feld.setToolTip(")))
        k = _tooltip_lauf(laden=lambda: M)
        pruefe("L47 KONTROLLE: ohne den Tooltip bei der Wahl -> rot",
               M._mutant_treffer == [1]
               and richter(lambda s: k["tips"].get(s), C),
               M._mutant_treffer)
        M = _mutant(_anweisungen(
            "_modus_zeigen", _beginnt("text = _modus_hinweis("),
            "text = 'Cadwork-Werkzeuge fragen IMMER.'"))
        k = _tooltip_lauf(laden=lambda: M)
        pruefe("L47 KONTROLLE: der feste Satz von vorher -> rot bei 'Alles "
               "automatisch'", M._mutant_treffer == [1]
               and "alles_auto" in [f[0] for f in richter(
                   lambda s: k["tips"].get(s), C)], M._mutant_treffer)
    finally:
        _einst_setzen(None)
        _frischer_start()


class _ModusKern(_VerbindKern):
    """Kern-Attrappe mit Zeichenmodus: schreibt jeden Aufruf mit.

    `annehmen`: antwortet der Kern auf 'zeichenmodus' mit ok (sonst lehnt
    er ab). `alt`: ein aelterer Kern ohne 'zeichenmodus' in
    `_worker_methoden` (KeyError). `tot`: serve() liefert einen schon
    beendeten Dienst. Zur Laufzeit umstellbar: `buch` (sein
    `dienst_im_prozess` meldet den laufenden Dienst, wie Kern >= 2.17) und
    `fremd` (serve() startet nicht, sondern gibt diesen Dienst zurueck —
    der Kern lehnt einen zweiten im Prozess ab)."""

    def __init__(self, von, bis, annehmen=True, alt=False, tot=False):
        _VerbindKern.__init__(self, von, bis)
        self.modus_aufrufe = []
        self.annehmen, self.alt, self.tot = annehmen, alt, tot
        self.buch, self.fremd, self.dienste = False, None, []

    def dienst_im_prozess(self):
        laufend = [d for d in self.dienste if not d.beenden]
        return laufend[-1] if self.buch and laufend else None

    def serve(self, cfg, reserved_socket=None):
        # Der reservierte Socket bleibt in `aufrufe` (`aufraeumen`), auch
        # wenn ein fremder Dienst zurueckgeht — der echte Kern schliesst ihn.
        d = _VerbindKern.serve(self, cfg, reserved_socket)
        if self.fremd is not None:
            return self.fremd
        d.cfg = cfg
        d.beenden = self.tot
        self.dienste.append(d)
        return d

    def _worker_methoden(self, _d):
        if self.alt:
            return {}

        def zeichenmodus(params):
            self.modus_aufrufe.append(params.get("modus"))
            if not self.annehmen:
                return {"ok": False, "error": "abgelehnt"}
            return {"ok": True, "result": {"zeichenmodus": params.get("modus")}}
        return {"zeichenmodus": zeichenmodus}


def _modus_start(datei, laden=None, ports=1, **kern_kw):
    """chat.json setzen, frischer Start, EIN Klick (verbindet). Was nach
    stderr ginge, sammelt m["gemeldet"]; eine Ausnahme aus dem Klick steht
    in m["geworfen"]. -> (dict, Modul, Zustand, Client, Kern); `kern`
    raeumt der Aufrufer auf."""
    _einst_setzen(datei)
    _frischer_start()
    client = _Client(list(zip(("Y", "Z"), _freie_ports(ports))))
    kern = _ModusKern(1, 0, **kern_kw)
    gemeldet = []

    def lade():
        D = (laden or dashboard_laden)()
        D._stderr = gemeldet.append
        return D
    m = {"geworfen": None, "gemeldet": gemeldet}
    D = z = None
    try:
        D, z, _r = _klick(client, kern, verbinden=True, laden=lade)
    except Exception as exc:                           # noqa: BLE001
        m["geworfen"] = type(exc).__name__
    m["verbunden"] = (z is not None and z["dienst"] is not None
                      and len(kern.aufrufe) == 1)
    m["beim_start"] = list(kern.modus_aufrufe)
    return m, D, z, client, kern


def _modus_lauf(datei, laden=None, regler=None, **kern_kw):
    """`_modus_start` mit zwei freien Steckplaetzen, wahlweise den Regler
    auf `regler`, `_zeichenmodus_wiederherstellen` einmal direkt
    (m["direkt"]). Dann die drei Wege, auf denen ein Dienst, der SCHON
    LAEUFT, in ein Dock kommt:
      zweiter_klick  derselbe Zustand, `_verbinden` kehrt sofort zurueck
      buch           neues Dock, der Kern meldet den laufenden Dienst
                     (`dienst_im_prozess`) -> `_uebernehmen`
      fremd          neues Dock, serve() gibt den laufenden zurueck statt
                     einen zweiten zu starten -> `_uebernehmen`
    Bis 2026-09-26 lief nur der erste: er erreicht `_uebernehmen` nie.
    -> dict."""
    m, D, z, client, kern = _modus_start(datei, laden=laden, ports=2,
                                         **kern_kw)
    try:
        if z is None:
            return m
        dienst = z["dienst"]
        if regler is not None:
            stufen = [s["schluessel"] for s in kern.ZEICHENMODI]
            z["w"]["regler"].setValue(stufen.index(regler))
            m["regler"] = list(kern.modus_aufrufe[len(m["beim_start"]):])
        datei = _einst_lesen()
        m["datei"] = datei if len(json.dumps(datei)) < 200 else "(gross)"
        m["direkt"] = D._zeichenmodus_wiederherstellen(z)
        for weg in ("zweiter_klick", "buch", "fremd"):
            if weg != "zweiter_klick":
                _frischer_start()
            kern.buch = weg == "buch"
            kern.fremd = dienst if weg == "fremd" else None
            vorher, starts = len(kern.modus_aufrufe), len(kern.aufrufe)
            _D, z2, _r = _klick(client, kern, verbinden=True, laden=laden)
            m[weg] = {"derselbe": z2["dienst"] is dienst,
                      "serve": len(kern.aufrufe) - starts,
                      "modus": kern.modus_aufrufe[vorher:]}
    finally:
        kern.aufraeumen()
    return m


def _wiederherstellen_if(s):
    return (isinstance(s, ast.If)
            and "_zeichenmodus_wiederherstellen" in ast.unparse(s))


def zelle_zeichenmodus_gemerkt():
    """L48 (S4): der Zeichenmodus aus dem Regler steht in chat.json und wird
    nach dem naechsten Verbinden wieder eingestellt — nur in einem FRISCH
    gestarteten Dienst, nie in einem, der schon lief. Gemerkt und als
    gesetzt gemeldet nur, was der Kern angenommen hat."""
    max_datei = json.dumps({"zeichenmodus": "max"})
    try:
        m = _modus_lauf(max_datei)
        pruefe("L48 gemerkter Modus: der neue Dienst bekommt ihn beim "
               "Verbinden, genau einmal (angenommen -> gemeldet)",
               m["verbunden"] and m["beim_start"] == ["max"]
               and m["direkt"] == "max", m)
        wege = {"zweiter_klick": 0, "buch": 0, "fremd": 1}
        pruefe("L48 ein Dienst, der schon laeuft, behaelt seinen Modus: "
               "zweiter Klick, neues Dock ueber das Buch des Kerns, serve() "
               "gibt den laufenden zurueck",
               all(m[w]["derselbe"] and m[w]["serve"] == n
                   and m[w]["modus"] == [] for w, n in wege.items()), m)
        m = _modus_lauf(None, regler="sicher")
        pruefe("L48 ohne chat.json bleibt die Vorgabe des Kerns (kein "
               "Aufruf); der Regler stellt UND merkt",
               m["beim_start"] == [] and m["regler"] == ["sicher"]
               and m["datei"] == {"zeichenmodus": "sicher"}, m)
        m = _modus_lauf(json.dumps({"zeichenmodus": "turbo",
                                    "denkstufe": "high"}))
        pruefe("L48 ein Modus, den der Kern nicht kennt, wird nicht gesetzt",
               m["verbunden"] and m["beim_start"] == [], m)
        m = _modus_lauf(_TIEF_JSON)
        pruefe("L48 ein kaputtes chat.json kostet das Verbinden nicht",
               m["verbunden"] and m["beim_start"] == [], m)
        m = _modus_lauf(max_datei, regler="sicher", annehmen=False)
        pruefe("L48 lehnt der Kern ab: der Regler merkt nichts, das "
               "Wiederherstellen meldet nichts als gesetzt",
               m["verbunden"] and m["regler"] == ["sicher"]
               and m["datei"] == {"zeichenmodus": "max"}
               and m["direkt"] is None, m)
        m, _D, _z, _c, kern = _modus_start(max_datei, alt=True)
        kern.aufraeumen()
        pruefe("L48 ein aelterer Kern ohne 'zeichenmodus': verbunden, nichts "
               "fliegt aus dem Klick, einmal auf stderr",
               m["verbunden"] and m["geworfen"] is None
               and sum("Zeichenmodus wiederherstellen" in g
                       for g in m["gemeldet"]) == 1, m)
        m, _D, _z, _c, kern = _modus_start(max_datei, tot=True)
        kern.aufraeumen()
        pruefe("L48 ein Dienst, der beim Start schon beendet ist, bekommt "
               "keinen Modus", m["geworfen"] is None
               and len(kern.aufrufe) == 1 and m["beim_start"] == [], m)

        # -- Kontrollen: je ein Mutant aus der Quelle, der rot werden muss --
        M = _mutant(_anweisungen("_verbinden", _wiederherstellen_if))
        k = _modus_lauf(max_datei, laden=lambda: M)
        pruefe("L48 KONTROLLE: ohne das Wiederherstellen in _verbinden -> "
               "rot", M._mutant_treffer == [1] and k["beim_start"] == [],
               (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_modus_setzen", lambda s: (isinstance(s, ast.If) and
                                        "_zeichenmodus_merken"
                                        in ast.unparse(s))))
        k = _modus_lauf(None, laden=lambda: M, regler="sicher")
        pruefe("L48 KONTROLLE: ohne das Merken im Regler -> nichts in "
               "chat.json", M._mutant_treffer == [1]
               and k["regler"] == ["sicher"] and k["datei"] is None,
               (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_uebernehmen", _beginnt("z['instanz'] ="),
            "z['instanz'] = getattr(laufend.cfg, 'instanz', None)\n"
            "_zeichenmodus_wiederherstellen(z)"))
        k = _modus_lauf(max_datei, laden=lambda: M)
        pruefe("L48 KONTROLLE: Wiederherstellen auch beim Uebernehmen -> rot "
               "auf beiden Wegen dorthin", M._mutant_treffer == [1]
               and k["buch"]["modus"] == ["max"]
               and k["fremd"]["modus"] == ["max"], (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_verbinden", _wiederherstellen_if,
            "_sicher(lambda: _zeichenmodus_wiederherstellen(z), "
            "'Zeichenmodus wiederherstellen')"))
        k = _modus_lauf(max_datei, laden=lambda: M)
        pruefe("L48 KONTROLLE: Wiederherstellen ohne 'nur nach neuem Start' "
               "-> rot, wenn serve() den laufenden zurueckgibt",
               M._mutant_treffer == [1] and k["beim_start"] == ["max"]
               and k["fremd"]["modus"] == ["max"], (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_modus_setzen", lambda s: (isinstance(s, ast.If) and
                                        "_zeichenmodus_merken"
                                        in ast.unparse(s)),
            "_sicher(lambda: _zeichenmodus_merken(schluessel), "
            "'Zeichenmodus merken')"))
        k = _modus_lauf(max_datei, laden=lambda: M, regler="sicher",
                        annehmen=False)
        pruefe("L48 KONTROLLE: Merken ohne Blick auf ok -> rot",
               M._mutant_treffer == [1]
               and k["datei"] == {"zeichenmodus": "sicher"},
               (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_zeichenmodus_wiederherstellen",
            lambda s: (isinstance(s, ast.Return)
                       and "get('ok')" in ast.unparse(s)),
            "return schluessel"))
        k = _modus_lauf(max_datei, laden=lambda: M, annehmen=False)
        pruefe("L48 KONTROLLE: Wiederherstellen meldet ohne ok -> rot",
               M._mutant_treffer == [1] and k["direkt"] == "max",
               (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_verbinden",
            _beginnt("_sicher(lambda: _zeichenmodus_wiederherstellen("),
            "_zeichenmodus_wiederherstellen(z)"))
        k, _D, _z, _c, kern = _modus_start(max_datei, laden=lambda: M,
                                           alt=True)
        kern.aufraeumen()
        pruefe("L48 KONTROLLE: ohne _sicher -> der Fehler fliegt aus dem "
               "Klick", M._mutant_treffer == [1]
               and k["geworfen"] == "KeyError", (M._mutant_treffer, k))
        M = _mutant(_anweisungen(
            "_zeichenmodus_wiederherstellen",
            lambda s: isinstance(s, ast.If) and "d.beenden" in ast.unparse(s),
            "if methoden is None or d is None:\n    return None"))
        k, _D, _z, _c, kern = _modus_start(max_datei, laden=lambda: M,
                                           tot=True)
        kern.aufraeumen()
        pruefe("L48 KONTROLLE: ohne den Blick auf d.beenden -> rot",
               M._mutant_treffer == [1] and k["beim_start"] == ["max"],
               (M._mutant_treffer, k))
    finally:
        _einst_setzen(None)
        _frischer_start()


def _ordner_lauf(wahl, umgebung=None, laden=None):
    """chat.json mit `arbeitsordner` = `wahl`, eine Sitzung dieses Ordners
    in einem Temp-Heim (USERPROFILE), frischer Start, verbunden; die Liste
    zeichnen, dann starten. `umgebung`: OPEN_MCP_CAD_PROJEKT (None = nicht
    gesetzt). -> dict."""
    heim = _tempfile.mkdtemp(prefix="omcad_live_heim_")
    alt_heim = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = heim
    _einst_setzen(json.dumps({"arbeitsordner": wahl})
                  if wahl is not None else None)
    _frischer_start()
    p_y, = _freie_ports(1)
    client, kern = _Client([("Y", p_y)]), _VerbindKern(1, 0)
    m = {}
    alt_projekt = os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
    try:
        # VOR dem Klick: das Verbinden zeichnet die Liste schon einmal.
        for o, titel in ((wahl, "Seeblick Wand"), (umgebung, "Umgebung")):
            if o is None:
                continue
            _dock_sitzung(o, "abcd1234-%s" % titel[:4], titel=titel)
        if umgebung is not None:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = umgebung
        D, z, _r = _klick(client, kern, verbinden=True, laden=laden)
        m["verbunden"] = z["dienst"] is not None
        with _ChatStartAttrappe(D, z, projekt=umgebung) as att:
            # Die Liste kommt aus einem Nebenthread (Etappe D).
            _warte_qt(D, z, lambda: z["w"]["chat_liste"].count() > 0,
                      frist=1.5)
            m["liste"] = _liste_titel(z)
            _senden_klick(D, z)               # startet (S8)
        # Der Start merkt Modell und Denkstufe — die Wahl bleibt stehen.
        m["danach"] = (_einst_lesen() or {}).get("arbeitsordner")
        m["ordner"] = att.ordner
        m["hinweis"] = _meldung(z)            # seit S7 an der Eingabe
    finally:
        kern.aufraeumen()
        os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        if alt_projekt is not None:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = alt_projekt
        if alt_heim is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = alt_heim
    return m


def zelle_ordnerwahl():
    """L49 (S4, Entscheid 2026-09-26): der im Dock gewaehlte Arbeitsordner
    (chat.json) gilt fuer Liste UND Start; OPEN_MCP_CAD_PROJEKT geht vor;
    ohne Ordner kein Start."""
    try:
        gewaehlt = _tempfile.mkdtemp(prefix="omcad_live_wahl_")
        umgebung = _tempfile.mkdtemp(prefix="omcad_live_umg_")
        m = _ordner_lauf(gewaehlt)
        pruefe("L49 die Dock-Wahl aus chat.json: die Liste zeigt ihre "
               "Sitzungen, der Chat startet dort",
               m["verbunden"]
               and m["liste"] == ["Seeblick Wand"]
               and m["ordner"] == [gewaehlt], m)
        pruefe("L49 nach dem Start (merkt Modell und Denkstufe) steht die "
               "Wahl noch in chat.json", m["danach"] == gewaehlt, m)
        m = _ordner_lauf(gewaehlt, umgebung=umgebung)
        pruefe("L49 OPEN_MCP_CAD_PROJEKT geht vor (Liste und Start)",
               m["liste"] == ["Umgebung"]
               and m["ordner"] == [umgebung], m)
        weg = gewaehlt + "_weg"
        m = _ordner_lauf(weg)
        pruefe("L49 eine Wahl, die es nicht (mehr) gibt: kein Start, ein "
               "Hinweis, keine Liste",
               m["ordner"] == [] and m["liste"] == []
               and m["hinweis"] == dashboard_laden().CHAT_KEIN_ORDNER, m)
        for was, mut in (
                ("der Start fragt ohne die Wahl",
                 _anweisungen("_chat_starten",
                              _beginnt("ordner = arbeitsordner("),
                              "ordner = arbeitsordner()")),
                ("der Aufbau liest die Wahl nicht",
                 _anweisungen("_tab_chat",
                              _beginnt("z['ordner_wahl'] =")))):
            M = _mutant(mut)
            k = _ordner_lauf(gewaehlt, laden=lambda: M)
            pruefe("L49 KONTROLLE: %s -> kein Start im gewaehlten Ordner"
                   % was, M._mutant_treffer == [1]
                   and k["ordner"] != [gewaehlt], (M._mutant_treffer, k))
    finally:
        _einst_setzen(None)
        _frischer_start()


def _takt_ordner_lauf(laden=None):
    """L50: ohne Arbeitsordner (keine Umgebung, keine Wahl, projektordner.txt
    mit totem Pfad) 30 Chat-Takte — wie oft liest der Takt
    projektordner.txt? Dann eine Wahl im Dock (`_ordner_merken`), eine
    zweite, das Vergessen und ein Ordner, der erst danach entsteht.
    Sitzungen in einem Temp-Heim (USERPROFILE). -> dict."""
    tmp = _tempfile.mkdtemp(prefix="omcad_live_takt_")
    heim = os.path.join(tmp, "heim")
    projekt_datei = os.path.join(tmp, "projektordner.txt")
    with open(projekt_datei, "w", encoding="utf-8") as fh:
        fh.write(os.path.join(tmp, "gibt_es_nicht"))
    alt_heim = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = heim
    alt_projekt = os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
    _einst_setzen(None)
    _frischer_start()
    p_y, = _freie_ports(1)
    client, kern = _Client([("Y", p_y)]), _VerbindKern(1, 0)
    gelesen = []

    def lade():
        D = (laden or dashboard_laden)()
        D.PROJEKT_DATEI = projekt_datei

        def zaehlend(pfad, *a, **k):
            if pfad == projekt_datei:
                gelesen.append(pfad)
            return open(pfad, *a, **k)
        D.open = zaehlend           # das Modul-`open` vor dem eingebauten
        return D
    m = {}
    try:
        ordner = {}
        for name, titel in (("eins", "Seeblick Wand"),
                            ("zwei", "Seeblick Dach")):
            o = os.path.join(tmp, name)
            os.makedirs(o)
            _dock_sitzung(o, "abcd1234-%s" % name, titel=titel)
            ordner[name] = o
        D, z, _r = _klick(client, kern, verbinden=True, laden=lade)
        m["treffer"] = getattr(D, "_mutant_treffer", None)

        def eintraege(warten=1.0):
            # Die Liste kommt aus einem Nebenthread (Etappe D): so lange
            # zeichnen, bis etwas da ist — hoechstens `warten` s (kuerzer
            # als ORDNER_NACHFRAGE_S, sonst saehe L50 die Drossel nicht).
            _warte_qt(D, z, lambda: z["w"]["chat_liste"].count() > 0,
                      frist=warten)
            return _liste_titel(z)
        m["frist_s"] = D.ORDNER_NACHFRAGE_S
        vorher, t0 = len(gelesen), time.monotonic()
        for _ in range(30):
            D._chat_zeichnen(z)
        m["takte_s"] = round(time.monotonic() - t0, 3)
        m["gelesen_30"] = len(gelesen) - vorher
        m["leer"] = eintraege()
        D._ordner_merken(z, ordner["eins"])
        m["wahl_eins"] = eintraege()
        D._ordner_merken(z, ordner["zwei"])
        m["wahl_zwei"] = eintraege()
        # Vergessen -> wieder ohne Ordner. Ein Ordner, der erst DANACH in
        # projektordner.txt steht, gilt nach der Wartezeit, nicht sofort.
        D._ordner_merken(z, None)
        D._chat_zeichnen(z)
        with open(projekt_datei, "w", encoding="utf-8") as fh:
            fh.write(ordner["eins"])
        m["sofort"] = eintraege(warten=0.5)
        D.ORDNER_NACHFRAGE_S = 0.0
        m["nach_frist"] = eintraege()
    finally:
        kern.aufraeumen()
        _einst_setzen(None)
        if alt_projekt is not None:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = alt_projekt
        if alt_heim is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = alt_heim
        _frischer_start()
    return m


def zelle_takt_ohne_ordner():
    """L50 (Nachpruefung Etappe A, 2026-09-26): ohne Arbeitsordner las der
    100-ms-Takt projektordner.txt in JEDEM Takt (Neuling ohne Ordner,
    verschwundene Wahl, toter Pfad). Jetzt hoechstens einmal je
    ORDNER_NACHFRAGE_S; eine Wahl im Dock gilt trotzdem sofort und leert
    die Liste des vorigen Ordners."""
    wand, dach = ["Seeblick Wand"], ["Seeblick Dach"]
    m = _takt_ordner_lauf()
    erlaubt = 1 + int(m["takte_s"] / m["frist_s"])
    pruefe("L50 ohne Ordner: 30 Takte lesen projektordner.txt hoechstens "
           "einmal je Frist", m["leer"] == [] and m["gelesen_30"] <= erlaubt,
           m)
    pruefe("L50 eine Wahl im Dock gilt sofort, eine zweite ersetzt die Liste",
           m["wahl_eins"] == wand and m["wahl_zwei"] == dach, m)
    pruefe("L50 ein Ordner, der danach entsteht, wird nach der Frist "
           "gefunden (nicht sofort)",
           m["sofort"] == [] and m["nach_frist"] == wand, m)
    for was, mut, rot in (
            ("arbeitsordner in jedem Takt wie vorher",
             _anweisungen("_liste_takt",
                          _beginnt("ordner = _ordner_nachfragen(z)"),
                          "ordner = arbeitsordner(_ordner_wahl(z))"),
             lambda k: k["gelesen_30"] >= 30 and k["sofort"] == wand),
            ("_ordner_merken leert die Liste nicht",
             _anweisungen("_ordner_merken", _beginnt("z['liste'] = []")),
             lambda k: k["wahl_zwei"] == wand),
            ("_ordner_merken hebt die Wartezeit nicht auf",
             _anweisungen("_ordner_merken", _beginnt("z.pop('ordner_gefragt'")),
             lambda k: k["wahl_eins"] == [])):
        M = _mutant(mut)
        k = _takt_ordner_lauf(laden=lambda: M)
        pruefe("L50 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k), (M._mutant_treffer, k))


# --- L51-L54: Einstellungsseite, Schluessel, lokale Modelle (2026-09-26) ----
#
# S5: Anbieter, Rueckfragen, Verbindungen und Zeichenmodus auf einer Seite im
# Dock (⚙), nichts Modales. S6: Schluessel speichern als eigene Aktion, danach
# nur "gespeichert ···1234". Abschnitt 3 der Uebergabe 2026-09-25: Ollama und
# LM Studio erkennen, starten, installieren — hier NUR mit Attrappen; ein
# Stolperdraht (unten) macht jeden echten Aufruf von winget/ollama/lms rot.

_DRAHT = []                   # jeder echte Aufruf, den der Stolperdraht fing
_DRAHT_NAMEN = ("winget", "ollama", "lms")


def _draht_legen():
    """`subprocess.Popen` fuer den ganzen Lauf: winget, ollama und lms
    starten NIE — der Versuch steht in `_DRAHT` und wirft OSError."""
    echt = subprocess.Popen
    if getattr(echt, "_omcad_draht", False):
        return

    class DrahtPopen(echt):
        _omcad_draht = True

        def __init__(self, args, *a, **k):
            erstes = (args[0] if isinstance(args, (list, tuple)) and args
                      else str(args).split(" ")[0])
            name = os.path.basename(str(erstes)).lower()
            for endung in (".exe", ".cmd", ".bat"):
                if name.endswith(endung):
                    name = name[:-len(endung)]
            if name in _DRAHT_NAMEN:
                _DRAHT.append(list(args) if isinstance(args, (list, tuple))
                              else [args])
                raise OSError("Stolperdraht: %s startet im Test nicht" % name)
            super().__init__(args, *a, **k)

    subprocess.Popen = DrahtPopen


def _alle_texte(wurzel):
    """Jeder Text und Tooltip unter `wurzel` (samt ihr): [(Widget, Art, Text)].

    Gemessen an den Widgets, keine Liste von Schluesseln: auch ein Teil, den
    niemand in `z["w"]` eintraegt, wird gelesen."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QComboBox, QListWidget, QTabWidget, QWidget
    funde = []
    for wd in [wurzel] + wurzel.findChildren(QWidget):
        for art in ("text", "toolTip", "placeholderText", "toPlainText",
                    "currentText", "windowTitle", "statusTip", "whatsThis",
                    "accessibleName", "accessibleDescription", "title"):
            f = getattr(wd, art, None)
            if not callable(f):
                continue
            try:
                wert = f()
            except TypeError:
                continue
            if isinstance(wert, str) and wert:
                funde.append((wd, art, wert))
        if isinstance(wd, QComboBox):
            for i in range(wd.count()):
                funde.append((wd, "itemText", wd.itemText(i)))
                tipp = wd.itemData(i, Qt.ItemDataRole.ToolTipRole)
                if isinstance(tipp, str):
                    funde.append((wd, "itemTip", tipp))
        if isinstance(wd, QListWidget):
            for i in range(wd.count()):
                funde.append((wd, "item", wd.item(i).text()))
        if isinstance(wd, QTabWidget):
            for i in range(wd.count()):
                funde.append((wd, "tabText", wd.tabText(i)))
    return funde


def _verraten(texte, geheim, erlaubt=4):
    """Steht mehr als die letzten `erlaubt` Zeichen des Schluessels irgendwo?
    -> [(Art, Ausschnitt)]. Geprueft wird JEDES Stueck mit erlaubt+1 Zeichen."""
    stuecke = {geheim[i:i + erlaubt + 1]
               for i in range(len(geheim) - erlaubt)}
    return [(art, text[:60]) for _wd, art, text in texte
            if any(s in text for s in stuecke)]


def _texte_des_docks(z):
    """Alle Texte aller Fenster des Docks: das EINE Fenster (K12: Kopf,
    Koerper mit Chat, Briefkasten und Einstellungen samt Popover und
    Aufklappern) und die Arbeitsanzeige."""
    texte = _alle_texte(z["fenster"])
    if z.get("anzeige") is not None:
        texte += _alle_texte(z["anzeige"])
    return texte


def _einst_lauf(laden=None):
    """K12: Fenster bauen, verbunden zeichnen, aus der Pille den Chat
    oeffnen, "⋯ → Einstellungen" bedienen, "← Zurück". -> dict."""
    from PyQt6.QtWidgets import QApplication, QPushButton
    D, z, d = _neustart(laden)
    w = z["w"]
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    D._auffrischen(z)
    dock, seite, seiten = z["fenster"], w["einst_seite"], w["seiten"]
    m["vorher"] = (dock.isVisible(), not w["koerper"].isHidden(),
                   seiten.currentWidget() is seite)
    # Kein Einstellungsknopf im Kopf (Rueckmeldung 2026-10-07).
    m["kopf_einst"] = [b.accessibleName() for b in
                       w["kopf"].findChildren(QPushButton)
                       if "instellung" in b.accessibleName()
                       or b.property("symbol") == "einstellungen"]
    D._fenster_aktion(z, "chat")
    QApplication.processEvents()
    w["mehr_menue"].click()
    QApplication.processEvents()
    m["mehr"] = (w["mehr_auf"].isVisible(),
                 [b.text() for b in w["mehr_auf"].findChildren(QPushButton)
                  if not b.isHidden()])
    w["mehr_einst"].click()
    QApplication.processEvents()
    m["offen"] = (dock.isVisible(), seiten.currentWidget() is seite,
                  seite.isVisible(), not w["mehr_auf"].isVisible(),
                  w["segment_chat"].isChecked()
                  or w["segment_briefkasten"].isChecked())
    m["modal"] = QApplication.activeModalWidget()
    m["fenster"] = seite.isWindow() or not dock.isAncestorOf(seite)
    m["takte"] = (z["timer"].isActive(), z["chat_takt"].isActive())
    m["auf_seite"] = {k: seite.isAncestorOf(w[k])
                      for k in ("steckplatz_wahl", "regler", "technik",
                                "chat_anbieter", "chat_modell",
                                "chat_schluessel", "chat_lokal")}
    gespraech = seiten.widget(0)
    m["im_chat"] = {k: gespraech.isAncestorOf(w[k])
                    for k in ("chat_modus", "chat_modell_knopf",
                              "chat_eingabe", "chat_verlauf")}
    m["fertig"] = [b.text() for b in seite.findChildren(QPushButton)
                   if b.text() == "Fertig"]
    w["einst_zurueck"].click()
    QApplication.processEvents()
    m["verlassen"] = (seiten.currentWidget() is gespraech,
                      w["segment_chat"].isChecked(), dock.isVisible(),
                      D._einstellungen_sichtbar(z))
    # Modus: der Satz steht sichtbar unter dem Feld (wie der Tooltip), und
    # das Gespraech sagt, welcher Modus gilt.
    _modus_klick(z, "alles_auto")
    D._chat_zeichnen(z)
    tipp, satz = _modus_tipp(z)
    m["freigabe"] = (satz, tipp,
                     w["chat_modus"].volltext().replace(" ▴", ""),
                     gespraech.isAncestorOf(w["chat_modus"])
                     and not w["chat_modus"].isHidden())
    _modus_klick(z, "fragen")
    # Ein laufender Chat mit Sitzung, verbunden auf Port 53127 (Attrappe).
    z["chat"].update(an=True, sitzung="abcdef1234567890", modell="Probe",
                     werkzeuge_da=True, stand=99)
    z["chat_gezeigt"] = None
    D._chat_zeichnen(z)
    D._auffrischen(z)
    # Kopf, Kontextzeile und Segmentzeile des Fensters und das Gespraech:
    # nirgends ein Port oder die Sitzung (K12: die Kontextzeile nennt den
    # Steckplatz, nicht den Port).
    texte = (_alle_texte(gespraech) + _alle_texte(w["kopf"])
             + _alle_texte(w["kontext_zeile"]) + _alle_texte(w["segment"]))
    m["port_im_chat"] = [(a, t[:60]) for _wd, a, t in texte
                         if "53127" in t or "Port" in t or "abcdef12" in t]
    # KONTROLLE im selben Lauf: ein eingespritzter Port wird gefunden.
    w["chat_status"].setText(w["chat_status"].text() + " · Port 53127")
    m["eingespritzt"] = [a for _wd, a, t in _alle_texte(gespraech)
                         if "53127" in t]
    z["chat_gezeigt"] = None
    D._chat_zeichnen(z)
    # Technik-Details: dort MUSS der Port stehen (umgezogen, nicht weg) —
    # "⋯ → Technik-Details" oeffnet die Seite mit ihnen.
    w["mehr_menue"].click()
    w["mehr_technik"].click()
    ende = time.monotonic() + 10
    while time.monotonic() < ende and "53127" not in w["technik"].text():
        QApplication.processEvents()
        D._technik_zeichnen(z)
        time.sleep(0.02)
    m["technik"] = w["technik"].text()
    m["technik_offen"] = (not w["technik"].isHidden(),
                          seiten.currentWidget() is seite,
                          not w["chat_technik_karte"].isHidden())
    z["chat"].update(an=False, sitzung=None)
    return m


def zelle_einstellungen():
    """L51 (S5; seit K12 EINE Seite im Koerper): keine Einstellungen im
    Kopf (Rueckmeldung 2026-10-07); "⋯ → Einstellungen" zeigt die Seite
    mit Chat (Anbieter, Modellfeld, Schluessel, lokale Modelle),
    Verbindung, Zeichenmodus und Technik — kein eigenes Fenster, nichts
    Modales, kein "Fertig", sondern "← Zurück" zum Segment. Gespraech,
    Kopf und Kontextzeile zeigen keinen Port, die Technik-Details schon."""
    try:
        m = _einst_lauf()
        pruefe("L51 vorher: nur die Pille, die Einstellungen nicht vorn; im "
               "Kopf kein Einstellungsknopf",
               m["vorher"] == (True, False, False) and m["kopf_einst"] == [],
               (m["vorher"], m["kopf_einst"]))
        pruefe("L51 '⋯' zeigt Einstellungen, Pausieren, Nach Auftrag "
               "trennen, Anleitung, Technik-Details",
               m["mehr"][0] and m["mehr"][1] == [
                   "Einstellungen", "Pausieren", "Nach Auftrag trennen",
                   "Anleitung öffnen", "Technik-Details"], m["mehr"])
        pruefe("L51 '⋯ → Einstellungen' zeigt die Seite im Koerper, das "
               "Menue geht zu, kein Segment ist gewaehlt",
               m["offen"] == (True, True, True, True, False), m["offen"])
        pruefe("L51 nicht modal: kein modales Fenster, die Seite liegt im "
               "Fenster, beide Takte laufen weiter",
               m["modal"] is None and not m["fenster"]
               and m["takte"] == (True, True), m)
        pruefe("L51 auf der EINEN Seite: Steckplatz, Zeichenmodus, Technik "
               "und der Chat (Anbieter, Modellfeld, Schluessel, lokale "
               "Modelle); Modus, Modell-Knopf, Eingabe und Verlauf im Chat",
               all(m["auf_seite"].values()) and all(m["im_chat"].values()),
               (m["auf_seite"], m["im_chat"]))
        pruefe("L51 kein 'Fertig'; '← Zurück' fuehrt zum Chat (Segment "
               "gewaehlt), das Fenster bleibt",
               m["fertig"] == [] and m["verlassen"] == (True, True, True,
                                                        False),
               (m["fertig"], m["verlassen"]))
        f = m["freigabe"]
        pruefe("L51 Modus: der Satz steht sichtbar unter dem Feld (gleich dem "
               "Tooltip), das Gespraech nennt den Modus",
               f[0] == f[1] and "Achtung" in f[0]
               and "Alles automatisch" in f[2] and f[3] is True, f)
        pruefe("L51 Gespraech, Kopf, Kontextzeile und Segmentzeile zeigen "
               "weder Port noch Sitzung", m["port_im_chat"] == [],
               m["port_im_chat"])
        pruefe("L51 KONTROLLE: ein eingespritzter Port im Gespraech wird "
               "gefunden", m["eingespritzt"] != [], m["eingespritzt"])
        pruefe("L51 '⋯ → Technik-Details': die Seite mit den Details "
               "aufgeklappt (Verbindung UND Chat), sie nennen Port, Sitzung, "
               "Server-Python und Codex-Ordner",
               m["technik_offen"] == (True, True, True)
               and "Port 53127" in m["technik"]
               and "abcdef1234567890" in m["technik"]
               and "Server-Python" in m["technik"]
               and "Codex-Ordner" in m["technik"],
               (m["technik_offen"], m["technik"][:200]))
        # KONTROLLE: der Port wieder in der Kontextzeile (Tooltip).
        k = _einst_lauf(_mutant(_anweisungen(
            "_auffrischen", _beginnt("tipp = '%s · %s Elemente"),
            "tipp = '%s · Port %s' % (dok, st.get('port'))")))
        pruefe("L51 KONTROLLE: mit dem Port im Tooltip der Kontextzeile "
               "steht er wieder vor dem Chat", k["treffer"] == [1]
               and any("53127" in t for _a, t in k["port_im_chat"]),
               (k["treffer"], k["port_im_chat"]))
        k = _einst_lauf(_mutant(_anweisungen(
            "_einstellungen_zeigen", _beginnt("seiten.setCurrentWidget("
                                              "seite)"))))
        pruefe("L51 KONTROLLE: zeigt '⋯ → Einstellungen' die Seite nicht, "
               "bleibt der Chat vorn", k["treffer"] == [1]
               and k["offen"][1] is False, (k["treffer"], k["offen"]))
        k = _einst_lauf(_mutant(_anweisungen(
            "_kopf_bauen", _beginnt("klein.hide()"),
            "klein.hide()\nlay.addWidget(knopf('kopf_einst', "
            "'Einstellungen', 'Einstellungen', "
            "lambda: _einstellungen_zeigen(z, True)))")))
        pruefe("L51 KONTROLLE: mit ⚙ im Kopf (wie bis K11) wird 'kein "
               "Einstellungsknopf' rot", k["treffer"] == [1]
               and k["kopf_einst"] == ["Einstellungen"], k["kopf_einst"])
        k = _einst_lauf(_mutant(_anweisungen(
            "_einstellungen_bauen", _beginnt("lay.addWidget(freigabe)"),
            "lay.addWidget(freigabe)\n"
            "fertig = QPushButton('Fertig')\n"
            "lay.addWidget(fertig)")))
        pruefe("L51 KONTROLLE: mit einem 'Fertig' auf der Seite (wie bis "
               "K10) wird die Zeile rot", k["treffer"] == [1]
               and k["fertig"] == ["Fertig"], k["fertig"])
        k = _einst_lauf(_mutant(_anweisungen(
            "_einstellungen_zeigen", _beginnt("_segment_waehlen("))))
        pruefe("L51 KONTROLLE: fuehrt '← Zurück' nicht zum Segment, bleibt "
               "die Seite vorn", k["treffer"] == [1]
               and k["verlassen"][0] is False, k["verlassen"])
    finally:
        _frischer_start()


def _anbieter_waehlen(z, kennung):
    feld = z["w"]["chat_anbieter"]
    feld.setCurrentIndex(feld.findData(kennung))


def _schluessel_lauf(laden=None):
    """Den Schluessel-Teil wie ein Nutzer bedienen, Tresor als Attrappe.
    -> dict mit Messungen."""
    import uuid
    from PyQt6.QtWidgets import QApplication
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    w = z["w"]
    A = D._anbieter_modul()
    geheim = "sk-probe-" + uuid.uuid4().hex + uuid.uuid4().hex[:6]
    alt = "or-alt-" + uuid.uuid4().hex
    m = {"geheim": geheim}
    with _TresorAttrappe(A, {"openrouter": alt}) as tresor:
        D._chat_einstellungen_zeigen(z, True)
        _anbieter_waehlen(z, "openai")
        m["eingabe"] = {
            "feld": not w["chat_schluessel"].isHidden(),
            "speichern": not w["chat_schluessel_speichern"].isHidden(),
            "zeile": not w["chat_schluessel_gespeichert"].isHidden(),
            "link": (not w["chat_schluessel_link"].isHidden(),
                     w["chat_schluessel_link"].text()),
            "hilfe": w["chat_schluessel_hilfe"].text(),
            "adresse": not w["chat_basis"].isHidden()}
        w["chat_schluessel"].setText(geheim)
        # Beim Tippen und Einfuegen: der Schluessel steht nirgends im
        # Klartext — auch nicht im Feld selbst (gemessen an dem, was das
        # Feld ANZEIGT, nicht an seinem Inhalt; Mutant R6 der Pruefung).
        feld = w["chat_schluessel"]
        m["getippt_sichtbar"] = _verraten(
            [(wd, a, t) for wd, a, t in _texte_des_docks(z)
             if not (wd is feld and a == "text")]
            + [(feld, "displayText", feld.displayText())], geheim)
        m["getippt_im_tresor"] = dict(tresor.daten)
        w["chat_schluessel_speichern"].click()
        QApplication.processEvents()
        m["tresor"] = dict(tresor.daten)
        m["feld_leer"] = w["chat_schluessel"].text() == ""
        m["zeile"] = (not w["chat_schluessel_gespeichert"].isHidden(),
                      w["chat_schluessel_ende"].text(),
                      w["chat_schluessel"].isHidden())
        try:
            with open(os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"],
                      encoding="utf-8") as fh:
                m["datei_roh"] = fh.read()
        except OSError:
            m["datei_roh"] = ""
        m["datei"] = _einst_lesen()
        m["verraten"] = _verraten(_texte_des_docks(z), geheim)
        m["verraten_datei"] = _verraten([(None, "chat.json",
                                          m["datei_roh"])], geheim)
        # aendern / Abbrechen
        w["chat_schluessel_aendern"].click()
        m["aendern"] = (not w["chat_schluessel"].isHidden(),
                        not w["chat_schluessel_abbrechen"].isHidden(),
                        w["chat_schluessel_gespeichert"].isHidden())
        w["chat_schluessel_abbrechen"].click()
        m["abbrechen"] = (w["chat_schluessel"].isHidden(),
                          not w["chat_schluessel_gespeichert"].isHidden(),
                          tresor.daten.get("openai") == geheim)
        # entfernen: erst der zweite Klick
        w["chat_schluessel_entfernen"].click()
        m["entfernen_1"] = ("openai" in tresor.daten,
                            w["chat_schluessel_entfernen"].text())
        w["chat_schluessel_entfernen"].click()
        m["entfernen_2"] = ("openai" in tresor.daten,
                            ((_einst_lesen() or {}).get("schluessel_ende")
                             or {}).get("openai"),
                            not w["chat_schluessel"].isHidden())
        # Links je Anbieter, Adresse nur bei "Eigene Adresse"
        links = {}
        for kennung in ("openai", "anthropic", "openrouter"):
            _anbieter_waehlen(z, kennung)
            links[kennung] = w["chat_schluessel_link"].text()
        m["links"] = links
        # openrouter: ein Schluessel aus einer Fassung vor S6 (nichts in
        # chat.json) — der Nebenthread findet ihn.
        ende = time.monotonic() + 5
        while time.monotonic() < ende and w["chat_schluessel_gespeichert"] \
                .isHidden():
            QApplication.processEvents()
            D._chat_zeichnen(z)
            time.sleep(0.02)
        m["alt"] = (not w["chat_schluessel_gespeichert"].isHidden(),
                    w["chat_schluessel_ende"].text())
        # Getippt, aber nicht gespeichert, und dann "Starten": kein Start,
        # ein Hinweis, und der Tresor bleibt, wie er war (vor S6 speicherte
        # der Start den Schluessel selbst, auch wenn er danach scheiterte).
        _anbieter_waehlen(z, "openai")
        w["chat_schluessel"].setText("sk-ungespeichert-" + uuid.uuid4().hex)
        vorher = dict(tresor.daten)
        with _AnbieterStartAttrappe(D) as att:
            _senden_klick(D, z)               # startet (S8) — hier nicht
        m["start_ungespeichert"] = (list(att.gestartet), _meldung(z),
                                    tresor.daten == vorher)
        w["chat_schluessel"].clear()
        _anbieter_waehlen(z, "eigen")
        m["adresse_eigen"] = not w["chat_basis"].isHidden()
        _anbieter_waehlen(z, "ollama")
        m["adresse_ollama"] = not w["chat_basis"].isHidden()
        # Modelle abfragen mit leerem Feld: der Tresor im Nebenthread
        _anbieter_waehlen(z, "openrouter")
        w["chat_basis"].setText("http://127.0.0.1:9/v1")
        D._modelle_abfragen(z)
        ende = time.monotonic() + 5
        while time.monotonic() < ende and not w["chat_modelle"].isEnabled():
            QApplication.processEvents()
            D._chat_zeichnen(z)
            time.sleep(0.02)
        m["gelesen"] = list(tresor.gelesen)
        m["verraten_alt"] = _verraten(_texte_des_docks(z), alt)
    D._chat_einstellungen_zeigen(z, False)
    return m


def zelle_schluessel():
    """L52 (S6): Link "Schluessel holen" je Anbieter, Speichern als eigene
    Aktion, danach nur "gespeichert ···1234 · aendern · entfernen"; der
    Schluessel steht in keinem Widget-Text und keinem Tooltip, in chat.json
    nur die letzten vier Zeichen, und der Qt-Thread liest den Tresor nie."""
    try:
        m = _schluessel_lauf()
        g = m["geheim"]
        e = m["eingabe"]
        pruefe("L52 noch nichts gespeichert: Feld, 'Speichern' und der Link "
               "zur Schluessel-Seite, ein Satz zu Zweck und Kosten, keine "
               "Adresse",
               e["feld"] and e["speichern"] and not e["zeile"]
               and e["link"][0]
               and "platform.openai.com/api-keys" in e["link"][1]
               and "Zugangscode" in e["hilfe"] and "kostet" in e["hilfe"]
               and not e["adresse"], e)
        pruefe("L52 beim Tippen steht der Schluessel nirgends im Klartext, "
               "auch nicht im Feld (es zeigt nur Punkte)",
               m["getippt_sichtbar"] == [], m["getippt_sichtbar"])
        pruefe("L52 Tippen allein speichert nichts",
               m["getippt_im_tresor"] == {"openrouter": m["getippt_im_tresor"]
                                          .get("openrouter")},
               sorted(m["getippt_im_tresor"]))
        pruefe("L52 'Speichern': im Tresor, Feld leer und weg, die Zeile "
               "'Schlüssel gespeichert ···%s'" % g[-4:],
               m["tresor"].get("openai") == g and m["feld_leer"]
               and m["zeile"] == (True, "Schlüssel gespeichert ···" + g[-4:],
                                  True), m["zeile"])
        pruefe("L52 chat.json traegt genau die letzten vier Zeichen",
               (m["datei"] or {}).get("schluessel_ende") == {"openai": g[-4:]}
               and not m["verraten_datei"], (m["datei"], m["verraten_datei"]))
        pruefe("L52 der Schluessel steht in keinem Widget-Text und keinem "
               "Tooltip (auch nicht teilweise)", m["verraten"] == [],
               m["verraten"])
        pruefe("L52 'ändern' zeigt das Feld mit 'Abbrechen', 'Abbrechen' "
               "klappt zu, der alte Schluessel bleibt",
               m["aendern"] == (True, True, True)
               and m["abbrechen"] == (True, True, True),
               (m["aendern"], m["abbrechen"]))
        pruefe("L52 'entfernen' fragt zuerst ('wirklich entfernen?'), "
               "entfernt erst beim zweiten Klick aus Tresor und chat.json",
               m["entfernen_1"] == (True, "wirklich entfernen?")
               and m["entfernen_2"] == (False, None, True),
               (m["entfernen_1"], m["entfernen_2"]))
        pruefe("L52 Link je Anbieter auf die Schluessel-Seite",
               "platform.openai.com/api-keys" in m["links"]["openai"]
               and "console.anthropic.com/settings/keys"
               in m["links"]["anthropic"]
               and "openrouter.ai/keys" in m["links"]["openrouter"],
               m["links"])
        pruefe("L52 ein Schluessel von vorher (nichts in chat.json) wird "
               "gefunden: 'Schlüssel gespeichert' ohne Zeichen",
               m["alt"] == (True, "Schlüssel gespeichert"), m["alt"])
        pruefe("L52 getippt, nicht gespeichert, 'Starten': kein Start, der "
               "Hinweis sagt 'zuerst speichern', der Tresor bleibt",
               m["start_ungespeichert"][0] == []
               and "zuerst speichern" in m["start_ungespeichert"][1]
               and m["start_ungespeichert"][2], m["start_ungespeichert"])
        pruefe("L52 Adresse nur bei 'Eigene Adresse'",
               m["adresse_eigen"] and not m["adresse_ollama"],
               (m["adresse_eigen"], m["adresse_ollama"]))
        pruefe("L52 der Tresor wurde gelesen, aber NIE im Qt-Thread",
               m["gelesen"]
               and all(t != "MainThread" for _k, t in m["gelesen"]),
               m["gelesen"])
        pruefe("L52 auch der alte Schluessel steht nirgends",
               m["verraten_alt"] == [], m["verraten_alt"])
        # KONTROLLEN: je eine Mutante, die den Schluessel zeigt.
        M1 = _mutant(_anweisungen("_schluessel_speichern",
                                  _beginnt("feld.clear()")))
        k1 = _schluessel_lauf(M1)
        pruefe("L52 KONTROLLE: ohne Leeren des Felds steht der Schluessel "
               "im Widget-Text", M1._mutant_treffer == [1]
               and k1["verraten"] != [], (M1._mutant_treffer,
                                          k1["verraten"][:3]))
        M2 = _mutant(_anweisungen(
            "_schluessel_speichern", _beginnt("ende = text[-4:]"),
            "ende = text"))
        k2 = _schluessel_lauf(M2)
        # Die Zeile zeigt ihn trotzdem nicht: `_schluessel_ende` nimmt aus
        # chat.json nie mehr als vier Zeichen an (zweite Sicherung).
        pruefe("L52 KONTROLLE: der ganze Schluessel als 'Ende' -> in "
               "chat.json gefunden (die Zeile nimmt ihn nicht an)",
               M2._mutant_treffer == [1] and k2["verraten_datei"] != []
               and k2["verraten"] == [],
               (M2._mutant_treffer, k2["verraten_datei"][:1],
                k2["verraten"][:2]))
        M4 = _mutant(_anweisungen(
            "_schluessel_speichern", _beginnt("feld.clear()"),
            "w['chat_schluessel_ende'].setToolTip(text)\nfeld.clear()"))
        k4 = _schluessel_lauf(M4)
        pruefe("L52 KONTROLLE: der Schluessel als Tooltip der Zeile wird "
               "gefunden", M4._mutant_treffer == [1]
               and any(a == "toolTip" for a, _t in k4["verraten"]),
               (M4._mutant_treffer, k4["verraten"][:2]))
        M6 = _mutant(_anweisungen(
            "_tab_chat", _beginnt("schluessel.setEchoMode("),
            "schluessel.setEchoMode(QLineEdit.EchoMode.Normal)"))
        k6 = _schluessel_lauf(M6)
        pruefe("L52 KONTROLLE: mit sichtbarem Feld (EchoMode Normal) steht "
               "der Schluessel beim Tippen im Klartext",
               M6._mutant_treffer == [1] and any(
                   a == "displayText" for a, _t in k6["getippt_sichtbar"]),
               (M6._mutant_treffer, k6["getippt_sichtbar"][:2]))
        M3 = _mutant(_anweisungen(
            "_schluessel_zeigen", _beginnt("w = z['w']"),
            "w = z['w']\n_anbieter_modul().schluessel_fuer("
            "a or _gewaehlter_anbieter(z))"))
        k3 = _schluessel_lauf(M3)
        pruefe("L52 KONTROLLE: liest die Anzeige den Tresor wie vor S6, "
               "zaehlt das als Lesen im Qt-Thread", M3._mutant_treffer == [1]
               and any(t == "MainThread" for _k, t in k3["gelesen"]),
               (M3._mutant_treffer, k3["gelesen"][:3]))
    finally:
        _einst_setzen(None)
        _frischer_start()


class _LokalWelt:
    """Ein Rechner, wie ihn das Lokal-Modul sieht — ganz in Attrappen.

    `da`: Programme auf dem PATH ("ollama", "lms", "winget"); `laeuft`:
    Anbieter, deren Dienst antwortet; `gestartet`: jeder Aufruf von
    `ausfuehren` (Befehl, eigenes Fenster?). Startet `serve`/`server start`,
    laeuft der Dienst danach (wie im echten Leben, nur sofort)."""

    def __init__(self, L, da=("winget",), laeuft=()):
        self.L, self.da, self.laeuft = L, set(da), set(laeuft)
        self.gestartet, self.langsam = [], 0.0

    def __enter__(self):
        L = self.L
        self.alt = (L.WHICH, L.DATEI_DA, L.HOLEN, L.AUSFUEHREN)

        def which(name):
            return ("C:\\Attrappe\\%s.exe" % name) if name in self.da else None

        def holen(url, timeout):
            time.sleep(self.langsam)
            for kennung, eintrag in L.LOKAL.items():
                if url == eintrag["dienst"] and kennung in self.laeuft:
                    return 200
            raise OSError("verweigert (Attrappe)")

        def ausfuehren(befehl, fenster=False):
            self.gestartet.append((list(befehl), fenster))
            if befehl[-1:] == ["serve"]:
                self.laeuft.add("ollama")
            if befehl[-2:] == ["server", "start"]:
                self.laeuft.add("lmstudio")
            return 4711

        L.WHICH, L.DATEI_DA, L.HOLEN = which, (lambda p: False), holen
        L.AUSFUEHREN = ausfuehren
        return self

    def __exit__(self, *_):
        self.L.WHICH, self.L.DATEI_DA, self.L.HOLEN, self.L.AUSFUEHREN = \
            self.alt


def _warte_lokal(D, z, bedingung, frist=5.0):
    from PyQt6.QtWidgets import QApplication
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        QApplication.processEvents()
        D._chat_zeichnen(z)
        if bedingung():
            return True
        time.sleep(0.02)
    return bool(bedingung())


def _lokal_lauf(laden=None):
    """Ollama von "nicht installiert" bis "bereit", dazu LM Studio. -> dict."""
    from PyQt6.QtWidgets import QApplication
    # Ollama ist schon gewaehlt (aus chat.json): erst das OEFFNEN der
    # Einstellungen muss die Pruefung anstossen, kein Anbieterwechsel.
    _einst_setzen(json.dumps({"anbieter": "ollama"}))
    D, z, _d = _neustart(laden)
    D.LOKAL_INSTALL_TAKT_S = D.LOKAL_START_TAKT_S = 0.05
    w = z["w"]
    L = D._lokal_modul()
    m = {}
    lage = w["chat_lokal_lage"]
    with _LokalWelt(L) as welt:
        m["vorgewaehlt"] = w["chat_anbieter"].currentData()
        D._chat_einstellungen_zeigen(z, True)
        _warte_lokal(D, z, lambda: "nicht installiert" in lage.text())
        m["fehlt"] = (lage.text(), not w["chat_lokal_installieren"].isHidden(),
                      w["chat_lokal_starten"].isHidden(),
                      w["chat_anbieter"].currentText())
        # Chat mit einem nicht installierten Programm: kein Start.
        with _AnbieterStartAttrappe(D) as att:
            _senden_klick(D, z)               # startet (S8) — hier nicht
            m["start_gesperrt"] = (list(att.gestartet), _meldung(z))
            stand = z.setdefault("lokal_stand", {})
            gemerkt = stand.pop("ollama", None)
            _senden_klick(D, z)
            m["start_ungeprueft"] = list(att.gestartet)
            if gemerkt is not None:
                stand["ollama"] = gemerkt
        # Installieren …: erst die Rueckfrage, nichts laeuft.
        w["chat_lokal_installieren"].click()
        D._chat_zeichnen(z)
        m["frage"] = (not w["chat_lokal_frage"].isHidden(),
                      w["chat_lokal_frage_text"].text(),
                      list(welt.gestartet), QApplication.activeModalWidget())
        w["chat_lokal_nein"].click()
        m["nein"] = (w["chat_lokal_frage"].isHidden(), list(welt.gestartet))
        w["chat_lokal_installieren"].click()
        w["chat_lokal_ja"].click()
        _warte_lokal(D, z, lambda: welt.gestartet)
        m["installiert_befehl"] = list(welt.gestartet)
        _warte_lokal(D, z, lambda: "eigenen Fenster" in lage.text())
        m["install_meldung"] = lage.text()
        welt.da.add("ollama")                 # winget ist fertig
        _warte_lokal(D, z, lambda: "läuft aber nicht" in lage.text())
        m["installiert"] = (lage.text(),
                            not w["chat_lokal_starten"].isHidden(),
                            w["chat_lokal_installieren"].isHidden())
        del welt.gestartet[:]
        w["chat_lokal_starten"].click()
        _warte_lokal(D, z, lambda: "Bereit" in lage.text())
        m["gestartet"] = (list(welt.gestartet), lage.text(),
                          w["chat_anbieter"].currentText(),
                          w["chat_lokal_starten"].isHidden())
        # Ein langsamer Dienst haelt den Qt-Takt nicht an.
        welt.langsam = 1.0
        t0 = time.monotonic()
        D._lokal_pruefen(z, "ollama", erzwingen=True)
        m["pruefen_s"] = time.monotonic() - t0
        dauer = []
        ende = time.monotonic() + 3
        while time.monotonic() < ende and "ollama" in z.get("lokal_laeuft",
                                                           ()):
            t1 = time.monotonic()
            D._chat_zeichnen(z)
            D._auffrischen(z)
            QApplication.processEvents()
            dauer.append(time.monotonic() - t1)
            time.sleep(0.02)
        m["takt_max_s"] = max(dauer) if dauer else None
        welt.langsam = 0.0
        # LM Studio: nicht installiert -> winget-Kennung; dann Start mit lms.
        del welt.gestartet[:]
        _anbieter_waehlen(z, "lmstudio")
        _warte_lokal(D, z, lambda: "nicht installiert" in lage.text())
        w["chat_lokal_installieren"].click()
        w["chat_lokal_ja"].click()
        _warte_lokal(D, z, lambda: welt.gestartet)
        welt.da.add("lms")
        _warte_lokal(D, z, lambda: "läuft aber nicht" in lage.text())
        w["chat_lokal_starten"].click()
        _warte_lokal(D, z, lambda: "Bereit" in lage.text())
        m["lmstudio"] = (list(welt.gestartet), lage.text())
    D._chat_einstellungen_zeigen(z, False)
    return m


def zelle_lokal():
    """L53 (Uebergabe 2026-09-25 Abschnitt 3): Ollama und LM Studio nur als
    'bereit', wenn installiert und der Dienst antwortet; Installieren nur
    nach Rueckfrage im Dock; Starten losgeloest; nichts blockiert den Takt.
    Alles gegen Attrappen — winget, ollama und lms laufen nie."""
    try:
        m = _lokal_lauf()
        w_id = ["C:\\Attrappe\\winget.exe", "install", "--id"]
        pruefe("L53 Ollama aus chat.json, das Oeffnen der Einstellungen "
               "prueft: nicht installiert, 'Installieren …' da, 'Starten' "
               "nicht, im Anbieter-Feld vermerkt",
               m["vorgewaehlt"] == "ollama"
               and "nicht installiert" in m["fehlt"][0] and m["fehlt"][1]
               and m["fehlt"][2]
               and m["fehlt"][3].endswith("nicht installiert"), m["fehlt"])
        pruefe("L53 ein nicht installiertes Programm ist nicht waehlbar: der "
               "Chat startet nicht und sagt es",
               m["start_gesperrt"][0] == []
               and "nicht installiert" in m["start_gesperrt"][1],
               m["start_gesperrt"])
        pruefe("L53 KONTROLLE: ungeprueft startet er wie bisher",
               len(m["start_ungeprueft"]) == 1, m["start_ungeprueft"])
        pruefe("L53 'Installieren …' fragt im Dock (kein Dialog), in Klartext, "
               "und startet noch nichts",
               m["frage"][0] and "winget" in m["frage"][1]
               and "Ollama installieren?" in m["frage"][1]
               and m["frage"][2] == [] and m["frage"][3] is None, m["frage"])
        pruefe("L53 'Abbrechen': Frage weg, nichts gestartet",
               m["nein"] == (True, []), m["nein"])
        pruefe("L53 'Ja, installieren': winget mit Ollama.Ollama, in einem "
               "eigenen Fenster, genau einmal",
               m["installiert_befehl"] == [(w_id + ["Ollama.Ollama", "--exact",
                                                     "--source", "winget"],
                                            True)], m["installiert_befehl"])
        pruefe("L53 danach steht, was passiert, und das Dock sieht selbst "
               "nach, bis es installiert ist",
               "eigenen Fenster" in m["install_meldung"]
               and "läuft aber nicht" in m["installiert"][0]
               and m["installiert"][1] and m["installiert"][2],
               (m["install_meldung"], m["installiert"]))
        pruefe("L53 'Starten': ollama serve, losgeloest ohne Fenster, dann "
               "'bereit' (auch im Anbieter-Feld)",
               m["gestartet"][0] == [(["C:\\Attrappe\\ollama.exe", "serve"],
                                      False)]
               and "Bereit" in m["gestartet"][1]
               and m["gestartet"][2].endswith("bereit")
               and m["gestartet"][3], m["gestartet"])
        pruefe("L53 ein Dienst, der 1 s braucht, haelt den Qt-Takt nicht an "
               "(Pruefen < 0,2 s, jeder Takt < 0,2 s)",
               m["pruefen_s"] < 0.2 and m["takt_max_s"] is not None
               and m["takt_max_s"] < 0.2, (m["pruefen_s"], m["takt_max_s"]))
        pruefe("L53 LM Studio: winget mit ElementLabs.LMStudio, Start mit "
               "'lms server start'",
               m["lmstudio"][0] == [
                   (w_id + ["ElementLabs.LMStudio", "--exact", "--source",
                            "winget"], True),
                   (["C:\\Attrappe\\lms.exe", "server", "start"], False)]
               and "Bereit" in m["lmstudio"][1], m["lmstudio"])
        # KONTROLLE: das Pruefen im Qt-Thread statt im Nebenthread.
        M = _mutant(_anweisungen(
            "_lokal_pruefen",
            lambda s: "threading.Thread" in ast.unparse(s), "holen()"))
        k = _lokal_lauf(M)
        pruefe("L53 KONTROLLE: prueft der Qt-Thread selbst, steht er so lange "
               "wie der Dienst", M._mutant_treffer == [1]
               and k["pruefen_s"] >= 0.9, (M._mutant_treffer, k["pruefen_s"]))
        # KONTROLLE: ohne die Sperre im Start geht der Chat trotzdem los.
        M2 = _mutant(_anweisungen(
            "_chat_anbieter_starten",
            lambda s: (isinstance(s, ast.If)
                       and "installiert" in ast.unparse(s.test))))
        k2 = _lokal_lauf(M2)
        pruefe("L53 KONTROLLE: ohne die Sperre startet der Chat mit einem "
               "nicht installierten Programm", M2._mutant_treffer == [1]
               and len(k2["start_gesperrt"][0]) == 1,
               (M2._mutant_treffer, k2["start_gesperrt"]))
    finally:
        _einst_setzen(None)
        _frischer_start()


def zelle_stolperdraht():
    """L54: winget, ollama und lms liefen im GANZEN Gate nie echt — der
    Stolperdraht auf `subprocess.Popen` hat nichts gefangen. Kontrolle: der
    echte Weg des Lokal-Moduls laeuft genau in ihn hinein."""
    gefangen = list(_DRAHT)
    pruefe("L54 kein echter Aufruf von winget/ollama/lms im ganzen Gate",
           gefangen == [], gefangen)
    L = dashboard_laden()._lokal_modul()
    vorher = len(_DRAHT)
    for befehl, fenster in ((["ollama", "serve"], False),
                            (["C:\\X\\lms.exe", "server", "start"], False),
                            (["winget", "install", "--id", "Ollama.Ollama"],
                             True)):
        try:
            L._ausfuehren_echt(befehl, fenster=fenster)
        except OSError:
            pass
    pruefe("L54 KONTROLLE: der echte Startweg des Lokal-Moduls laeuft in den "
           "Draht (3 von 3 gefangen, keiner gestartet)",
           len(_DRAHT) - vorher == 3, _DRAHT[vorher:])
    del _DRAHT[vorher:]


# --- L55-L57: Nacharbeit Etappe B (Pruefung 2026-09-26) ----------------------
#
# Je Befund der unabhaengigen Pruefung eine Messung am gebauten Dock und je
# Messung ein Mutant aus der Quelle, der rot werden muss.

_FREMD_OLLAMA = "http://192.0.2.7:11434/v1"      # TEST-NET-1, antwortet nie
_FREMD_OPENAI = "http://192.0.2.8/v1"
_EIGENE = "http://192.0.2.9:8080/v1"


def _adresse_lauf(laden=None):
    """chat.json aus einer Fassung vor Etappe B: gemerkte Adressen auch fuer
    Anbieter mit vorgegebener Adresse. Je Anbieter: Feld sichtbar?, Adresse
    beim Start, Adresse der Modellabfrage. -> dict."""
    from PyQt6.QtWidgets import QApplication
    _einst_setzen(json.dumps({
        "anbieter": "ollama",
        "basis": {"ollama": _FREMD_OLLAMA, "openai": _FREMD_OPENAI,
                  "eigen": _EIGENE}}))
    D, z, _d = _neustart(laden)
    w = z["w"]
    A = D._anbieter_modul()
    L = D._lokal_modul()
    m = {}
    with _LokalWelt(L, da=("ollama",), laeuft=("ollama",)), \
            _TresorAttrappe(A, {"openai": "sk-probe-" + "x" * 20}), \
            _AnbieterStartAttrappe(D) as att:
        abgefragt = []
        kopie = sys.modules[att.NAME]
        kopie.modelle_laden = (lambda a, basis=None, schluessel=None, **k:
                               abgefragt.append((a["id"], basis)) or [])
        D._chat_einstellungen_zeigen(z, True)
        for kennung in ("ollama", "openai", "eigen"):
            _anbieter_waehlen(z, kennung)
            sichtbar = not w["chat_basis"].isHidden()
            del att.gestartet[:]
            z["chat"]["an"] = False           # jeder Durchgang ein neuer Chat
            _senden_klick(D, z)               # startet (S8)
            start = [b for _k, _m, b in att.gestartet]
            del abgefragt[:]
            D._modelle_abfragen(z)
            ende = time.monotonic() + 5
            while time.monotonic() < ende and not abgefragt:
                QApplication.processEvents()
                time.sleep(0.02)
            _warte_lokal(D, z, lambda: w["chat_modelle"].isEnabled())
            m[kennung] = (sichtbar, start, [b for _k, b in abgefragt])
        _anbieter_waehlen(z, "ollama")
        _warte_lokal(D, z, lambda: "Bereit" in w["chat_lokal_lage"].text())
        m["lokal"] = w["chat_lokal_lage"].text()
    m["datei"] = (_einst_lesen() or {}).get("basis")
    D._chat_einstellungen_zeigen(z, False)
    return m


def zelle_adresse_vorgegeben():
    """L55 (Befund mittel): eine Adresse aus chat.json gilt nur bei "Eigene
    Adresse". Vorher ging bei OpenAI der Schluessel an eine gemerkte
    Adresse, die im Dock nicht zu sehen war, und Ollama hiess "bereit"
    (geprueft auf localhost), waehrend der Chat woanders anfragte."""
    try:
        m = _adresse_lauf()
        A = dashboard_laden()._anbieter_modul()
        vorgabe = {k: A.anbieter(k)["basis"] for k in ("ollama", "openai")}
        for kennung in ("ollama", "openai"):
            sichtbar, start, abfrage = m[kennung]
            pruefe("L55 %s: Feld verborgen, Start UND Modellabfrage mit der "
                   "vorgegebenen Adresse %s (nicht der gemerkten)"
                   % (kennung, vorgabe[kennung]),
                   not sichtbar and start == [vorgabe[kennung]]
                   and abfrage == [vorgabe[kennung]], m[kennung])
        pruefe("L55 Ollama 'bereit' gilt fuer dieselbe Adresse, an die der "
               "Chat geht (localhost)",
               "Bereit" in m["lokal"]
               and m["ollama"][1] == ["http://localhost:11434/v1"],
               (m["lokal"], m["ollama"][1]))
        pruefe("L55 'Eigene Adresse': die gemerkte steht sichtbar im Feld und "
               "gilt", m["eigen"] == (True, [_EIGENE], [_EIGENE]), m["eigen"])
        pruefe("L55 nach dem Start steht in chat.json die vorgegebene Adresse "
               "(die fremde ist ueberschrieben)",
               (m["datei"] or {}).get("ollama") == vorgabe["ollama"]
               and (m["datei"] or {}).get("openai") == vorgabe["openai"]
               and (m["datei"] or {}).get("eigen") == _EIGENE, m["datei"])
        # KONTROLLE: die Zeile von vorher (gemerkte Adresse vor der Vorgabe).
        M = _mutant(_anweisungen(
            "_anbieter_gewechselt", _beginnt("w['chat_basis'].setText("),
            "w['chat_basis'].setText(_gemerkt(e, 'basis', a['id']) "
            "or a.get('basis') or '')"))
        k = _adresse_lauf(M)
        pruefe("L55 KONTROLLE: mit der Zeile von vorher gehen Start und "
               "Abfrage an die unsichtbare gemerkte Adresse",
               M._mutant_treffer == [1]
               and k["openai"] == (False, [_FREMD_OPENAI], [_FREMD_OPENAI])
               and k["ollama"][1] == [_FREMD_OLLAMA],
               (M._mutant_treffer, k["openai"], k["ollama"]))
    finally:
        _einst_setzen(None)
        _frischer_start()


class _TresorLangsam(_TresorAttrappe):
    """Wie `_TresorAttrappe`, aber ein Lesen merkt sich den Wert SOFORT und
    kehrt erst zurueck, wenn `los` gesetzt ist — eine Tresor-Pruefung, die
    von einem Speichern und Entfernen ueberholt wird."""

    def __enter__(self):
        super().__enter__()
        self.los = threading.Event()
        lesen = self.A.schluessel_lesen

        def langsam(kennung, praefix=None):
            wert = lesen(kennung, praefix)
            self.los.wait(10)
            return wert
        self.A.schluessel_lesen = langsam
        return self


def _feinheiten_lauf(laden=None):
    """Die vier kleinen Schluessel-Regeln der Uebergabe (Befunde R7, R8, R9,
    R11), je gemessen. -> dict."""
    import uuid
    from PyQt6.QtWidgets import QApplication
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    w = z["w"]
    A = D._anbieter_modul()
    m = {}
    D._chat_einstellungen_zeigen(z, True)
    # R8: ein kurzer Schluessel hinterlaesst KEINE Zeichen in chat.json.
    with _TresorAttrappe(A) as tresor:
        _anbieter_waehlen(z, "openai")
        kurz = "sk-" + uuid.uuid4().hex[:5]              # 8 Zeichen
        w["chat_schluessel"].setText(kurz)
        w["chat_schluessel_speichern"].click()
        m["kurz"] = (tresor.daten.get("openai") == kurz,
                     ((_einst_lesen() or {}).get("schluessel_ende")
                      or {}).get("openai"),
                     w["chat_schluessel_ende"].text())
        # R11: ein Anbieterwechsel leert ein halb getipptes Feld; "Speichern"
        # beim neuen Anbieter legt nichts ab.
        halb = "sk-halb-" + uuid.uuid4().hex
        w["chat_schluessel_aendern"].click()
        w["chat_schluessel"].setText(halb)
        _anbieter_waehlen(z, "anthropic")
        m["gewechselt_feld"] = w["chat_schluessel"].text()
        w["chat_schluessel_speichern"].click()
        m["gewechselt_tresor"] = (tresor.daten.get("anthropic"),
                                  tresor.daten.get("openai") == kurz)
    # R9: getippt, nicht gespeichert, "Modelle abfragen": keine Abfrage, der
    # Hinweis sagt "zuerst Speichern".
    with _TresorAttrappe(A, {"openrouter": "or-" + uuid.uuid4().hex}), \
            _AnbieterStartAttrappe(D) as att:
        abgefragt = []
        sys.modules[att.NAME].modelle_laden = (
            lambda a, basis=None, schluessel=None, **k:
            abgefragt.append(a["id"]) or [])
        _anbieter_waehlen(z, "openrouter")
        w["chat_schluessel_aendern"].click()
        w["chat_schluessel"].setText("sk-neu-" + uuid.uuid4().hex)
        D._modelle_abfragen(z)
        # Gleich lesen: eine spaeter fertige Tresor-Pruefung zeichnet die
        # Zeile neu (und leert dabei den Hinweis).
        hinweis = w["chat_schluessel_lage"].text()
        ende = time.monotonic() + 1.0
        while time.monotonic() < ende and not abgefragt:
            QApplication.processEvents()
            D._chat_zeichnen(z)
            time.sleep(0.02)
        m["abfrage"] = (list(abgefragt), hinweis)
        w["chat_schluessel"].clear()
        w["chat_schluessel_abbrechen"].click()
    # R7: eine Tresor-Pruefung, die VOR Speichern und Entfernen begann,
    # darf danach nichts mehr sagen.
    D._chat_einstellungen_zeigen(z, False)
    _anbieter_waehlen(z, "claude")
    z.pop("schluessel_da", None)
    with _TresorLangsam(A, {"openrouter": "or-alt-" + uuid.uuid4().hex}) as t:
        _anbieter_waehlen(z, "openrouter")
        D._chat_einstellungen_zeigen(z, True)          # startet die Pruefung
        ende = time.monotonic() + 5
        while time.monotonic() < ende and not t.gelesen:
            time.sleep(0.01)
        m["pruefung_laeuft"] = bool(t.gelesen)
        w["chat_schluessel"].setText("sk-probe-" + uuid.uuid4().hex)
        w["chat_schluessel_speichern"].click()
        w["chat_schluessel_entfernen"].click()
        w["chat_schluessel_entfernen"].click()
        m["entfernt"] = "openrouter" not in t.daten
        t.los.set()
        ende = time.monotonic() + 5
        while time.monotonic() < ende and (
                z.get("schluessel_da_neu")
                or "openrouter" in (z.get("schluessel_da_laeuft") or ())):
            QApplication.processEvents()
            D._chat_zeichnen(z)
            time.sleep(0.02)
        D._chat_zeichnen(z)
        m["veraltet"] = (w["chat_schluessel_gespeichert"].isHidden(),
                         not w["chat_schluessel"].isHidden(),
                         (z.get("schluessel_da") or {}).get("openrouter"))
    D._chat_einstellungen_zeigen(z, False)
    return m


def zelle_schluessel_feinheiten():
    """L56 (Befunde niedrig R7, R8, R9, R11): kurze Schluessel ohne Zeichen
    in chat.json, Abfrage erst nach dem Speichern, Anbieterwechsel leert das
    Feld, eine ueberholte Tresor-Pruefung wird verworfen."""
    try:
        m = _feinheiten_lauf()
        pruefe("L56 ein Schluessel unter 12 Zeichen: gespeichert, aber in "
               "chat.json KEINE Zeichen, die Zeile ohne ···",
               m["kurz"] == (True, "", "Schlüssel gespeichert"), m["kurz"])
        pruefe("L56 ein Anbieterwechsel leert das halb getippte Feld; "
               "'Speichern' legt beim neuen Anbieter nichts ab",
               m["gewechselt_feld"] == ""
               and m["gewechselt_tresor"] == (None, True),
               (m["gewechselt_feld"][:4], m["gewechselt_tresor"]))
        pruefe("L56 getippt, nicht gespeichert: 'Modelle abfragen' fragt "
               "nicht und sagt 'zuerst Speichern'",
               m["abfrage"][0] == [] and "Speichern" in m["abfrage"][1],
               m["abfrage"])
        pruefe("L56 eine Tresor-Pruefung, die vor Speichern und Entfernen "
               "begann, wird verworfen: das Feld steht da, keine Zeile",
               m["pruefung_laeuft"] and m["entfernt"]
               and m["veraltet"] == (True, True, False),
               (m["pruefung_laeuft"], m["entfernt"], m["veraltet"]))
        kontrollen = (
            ("R8 SCHLUESSEL_ENDE_AB uebergangen",
             _anweisungen("_schluessel_speichern", _beginnt("ende = text[-4:]"),
                          "ende = text[-4:]"),
             lambda k: k["kurz"][1] not in ("", None)),
            ("R11 Wechsel leert das Feld nicht",
             _anweisungen("_anbieter_gewechselt",
                          _beginnt("w['chat_schluessel'].clear()")),
             lambda k: k["gewechselt_tresor"][0] is not None),
            ("R9 Abfrage ohne 'zuerst Speichern'",
             _anweisungen("_modelle_abfragen", lambda s: (
                 isinstance(s, ast.If)
                 and "chat_schluessel" in ast.unparse(s.test))),
             lambda k: k["abfrage"][0] == ["openrouter"]),
            ("R7 veraltete Pruefung uebernommen",
             _anweisungen("_schluessel_takt", lambda s: (
                 isinstance(s, ast.If) and "version" in ast.unparse(s.test)),
                 "z.setdefault('schluessel_da', {})[kennung] = da\n"
                 "geaendert = True"),
             lambda k: k["veraltet"][0] is False),
        )
        for name, mutation, rot in kontrollen:
            M = _mutant(mutation)
            k = _feinheiten_lauf(M)
            pruefe("L56 KONTROLLE %s: wird rot" % name,
                   M._mutant_treffer == [1] and rot(k),
                   (M._mutant_treffer, k))
    finally:
        _einst_setzen(None)
        _frischer_start()


def _seite_lauf(laden=None):
    """Einstellungsseite, Nacharbeit: neu pruefen beim Oeffnen, Freigabe
    wartet, wer antwortet, Ausnahmen aus den Knoepfen. -> dict."""
    import io
    from PyQt6.QtWidgets import QApplication, QPushButton
    _einst_setzen(json.dumps({"anbieter": "ollama"}))
    D, z, _d = _neustart(laden)
    w = z["w"]
    L = D._lokal_modul()
    m = {}
    lage = w["chat_lokal_lage"]
    # Stand "nicht installiert"; danach ausserhalb des Docks installiert und
    # gestartet. Das naechste OEFFNEN muss es sehen.
    with _LokalWelt(L) as welt:
        D._chat_einstellungen_zeigen(z, True)
        _warte_lokal(D, z, lambda: "nicht installiert" in lage.text())
        m["vorher"] = lage.text()
        D._chat_einstellungen_zeigen(z, False)
        welt.da.add("ollama")
        welt.laeuft.add("ollama")
        D._chat_einstellungen_zeigen(z, True)
        _warte_lokal(D, z, lambda: "Bereit" in lage.text(), frist=3.0)
        m["nachher"] = lage.text()
    # Eine Freigabe wartet, waehrend die Seite offen ist.
    chat = z["chat"]
    chat.update(an=True, anbieter="claude", kurzname="Claude",
                freigaben=[{"id": "f1", "offen": True,
                            "name": "execute_cadwork_command",
                            "eingabe": {"code": "x = 1"}}])
    z["chat_gezeigt"] = None
    D._chat_zeichnen(z)
    # K12: EINE Einstellungsseite im Koerper des Fensters (hier offen).
    hinweis = w.get("einst_freigabe")
    m["freigabe_offen"] = hinweis is not None and not hinweis.isHidden()
    zurueck = [b for b in (hinweis.findChildren(QPushButton) if hinweis
                           else []) if b.text() == "Zum Chat"]
    if zurueck:
        zurueck[0].click()
    seiten = w["seiten"]
    m["zum_gespraech"] = (seiten.currentWidget() is seiten.widget(0),
                          len(zurueck))
    # Aus der Pille: `_einstellungen_zeigen` oeffnet das Fenster dafuer.
    D._fenster_aktion(z, "verkleinern")
    D._einstellungen_zeigen(z, True)
    D._chat_zeichnen(z)
    dock_hinweis = w.get("einst_freigabe")
    m["dock_freigabe"] = (dock_hinweis is not None
                          and not dock_hinweis.isHidden(),
                          z["fenster"].isVisible()
                          and not w["koerper"].isHidden(),
                          seiten.currentWidget() is w["einst_seite"])
    if w.get("einst_zum_chat") is not None:
        w["einst_zum_chat"].click()
    m["zum_chat"] = (not w["koerper"].isHidden(),
                     seiten.currentWidget() is seiten.widget(0))
    D._chat_einstellungen_zeigen(z, True)
    chat["freigaben"] = []
    D._chat_zeichnen(z)
    m["freigabe_weg"] = hinweis is None or hinweis.isHidden()
    # Wer antwortet: der LAUFENDE Anbieter, nicht der im Feld.
    _anbieter_waehlen(z, "openai")
    D._chat_zeichnen(z)
    m["wer"] = w["chat_wer"].text()
    chat.update(an=False, freigaben=[])
    D._chat_zeichnen(z)
    m["wer_danach"] = w["chat_wer"].text()
    D._chat_einstellungen_zeigen(z, False)
    # Ausnahmen aus "⋯ → Einstellungen", "← Zurück" und "Zum Chat" (K12):
    # nie aus dem Slot (in Cadwork qFatal, gemessen in L43). Die
    # Umschalter werfen hier ("Zum Chat" oeffnet den Chat).
    echt = (D._einstellungen_zeigen, D._chat_einstellungen_zeigen,
            D._chat_oeffnen)

    def wirft(*_a, **_k):
        raise RuntimeError("Probe: Einstellungen")
    knoepfe = {"mehr": [w["mehr_einst"]],
               "zurueck": [w["einst_zurueck"]],
               "zum_chat": [w["einst_zum_chat"]]}
    entkommen = {}
    alt_hook, alt_err = sys.excepthook, sys.stderr
    try:
        D._einstellungen_zeigen = D._chat_einstellungen_zeigen = wirft
        D._chat_oeffnen = wirft
        sys.stderr = io.StringIO()
        for name, liste in knoepfe.items():
            fang = []
            sys.excepthook = (lambda t, v, tb, fang=fang:
                              fang.append(t.__name__))
            for b in liste:
                b.click()
            QApplication.processEvents()
            entkommen[name] = (len(liste), fang)
        m["gemeldet"] = "Probe: Einstellungen" in sys.stderr.getvalue()
    finally:
        (D._einstellungen_zeigen, D._chat_einstellungen_zeigen,
         D._chat_oeffnen) = echt
        sys.excepthook, sys.stderr = alt_hook, alt_err
    m["entkommen"] = entkommen
    return m


def zelle_seite_nacharbeit():
    """L57 (Befunde niedrig): das Oeffnen der Einstellungen prueft NEU; eine
    wartende Freigabe steht auf der Seite (seit K12 die EINE
    Einstellungsseite im Koerper, auch aus der Pille), "Zum Chat" fuehrt
    hin; die Technik-Karte nennt den laufenden Anbieter; weder "⋯ →
    Einstellungen" noch "← Zurück" noch "Zum Chat" laesst eine Ausnahme
    aus dem Qt-Slot."""
    try:
        m = _seite_lauf()
        pruefe("L57 ausserhalb des Docks installiert und gestartet: das "
               "naechste Oeffnen der Einstellungen sieht es",
               "nicht installiert" in m["vorher"] and "Bereit" in m["nachher"],
               (m["vorher"], m["nachher"]))
        pruefe("L57 eine wartende Freigabe steht auf der Einstellungsseite; "
               "'Zum Chat' fuehrt zu den Karten",
               m["freigabe_offen"] and m["zum_gespraech"] == (True, 1),
               (m["freigabe_offen"], m["zum_gespraech"]))
        pruefe("L57 ... auch aus der Pille (das Fenster geht dafuer auf); "
               "'Zum Chat' zeigt den Chat", m["dock_freigabe"]
               == (True, True, True)
               and m["zum_chat"] == (True, True),
               (m["dock_freigabe"], m["zum_chat"]))
        pruefe("L57 ohne offene Freigabe kein Hinweis", m["freigabe_weg"])
        pruefe("L57 der Chat-Tab nennt den laufenden Anbieter und den "
               "naechsten getrennt; ohne Chat nur den gewaehlten",
               m["wer"].startswith("Claude Code")
               and "nächster Chat: OpenAI" in m["wer"]
               and m["wer_danach"].startswith("OpenAI"),
               (m["wer"], m["wer_danach"]))
        e = m["entkommen"]
        pruefe("L57 '⋯ → Einstellungen', '← Zurück' und 'Zum Chat': eine "
               "Ausnahme bleibt im Dock (gemeldet), nichts laeuft aus dem "
               "Slot",
               all(n == 1 and not f for n, f in e.values()) and m["gemeldet"],
               (e, m["gemeldet"]))
        # KONTROLLEN
        M1 = _mutant(_anweisungen(
            "_einstellungen_pruefen",
            _beginnt("_lokal_pruefen(z, a['id'], erzwingen=True)"),
            "_lokal_pruefen(z, a['id'])"))
        k1 = _seite_lauf(M1)
        pruefe("L57 KONTROLLE: ohne 'erzwingen' bleibt 'nicht installiert' "
               "stehen", M1._mutant_treffer == [1]
               and "nicht installiert" in k1["nachher"],
               (M1._mutant_treffer, k1["nachher"]))
        M2 = _mutant(_ohne_aufruf("_chat_zeichnen", "_einst_freigabe_zeigen"))
        k2 = _seite_lauf(M2)
        pruefe("L57 KONTROLLE: ohne den Hinweis im Takt sieht die Seite die "
               "Freigabe nicht", M2._mutant_treffer == [1]
               and not k2["freigabe_offen"],
               (M2._mutant_treffer, k2["freigabe_offen"]))
        M2b = _mutant(_anweisungen("_zum_chat",
                                   lambda s: isinstance(s, ast.Return),
                                   "return False"))
        k2b = _seite_lauf(M2b)
        pruefe("L57 KONTROLLE: fuehrt 'Zum Chat' nicht zum Chat, bleibt die "
               "Einstellungsseite vorn", M2b._mutant_treffer == [1]
               and k2b["zum_chat"][1] is False,
               (M2b._mutant_treffer, k2b["zum_chat"]))
        M2c = _mutant(_anweisungen(
            "_einstellungen_zeigen", lambda s: isinstance(s, ast.If)
            and "PILLE_Z" in ast.unparse(s.test)))
        k2c = _seite_lauf(M2c)
        pruefe("L57 KONTROLLE: oeffnet der Weg zu den Einstellungen die "
               "Pille nicht, sieht man den Hinweis nicht",
               M2c._mutant_treffer == [1]
               and k2c["dock_freigabe"][1] is False,
               (M2c._mutant_treffer, k2c["dock_freigabe"]))
        M3 = _mutant(_anweisungen(
            "_wer_zeigen", _beginnt("laeuft = "), "laeuft = None"))
        k3 = _seite_lauf(M3)
        pruefe("L57 KONTROLLE: nach dem Feld statt nach dem laufenden Chat "
               "steht 'OpenAI' oben", M3._mutant_treffer == [1]
               and k3["wer"].startswith("OpenAI"),
               (M3._mutant_treffer, k3["wer"]))
        for name, funktion, anfang, alt in (
                ("mehr", "_koerper_bauen", "b.clicked.connect(",
                 "b.clicked.connect(lambda _c=False, fn=fn: (auf.hide(), "
                 "fn()))"),
                ("zurueck", "_einstellungen_bauen",
                 "zurueck.clicked.connect(",
                 "zurueck.clicked.connect("
                 "lambda: _einstellungen_zeigen(z, False))"),
                ("zum_chat", "_einstellungen_bauen",
                 "zum_chat.clicked.connect(",
                 "zum_chat.clicked.connect(lambda: _zum_chat(z))")):
            mutationen = [_anweisungen(funktion, _beginnt(anfang), alt)]
            M = _mutant(*mutationen)
            k = _seite_lauf(M)
            pruefe("L57 KONTROLLE: '%s' ohne _sicher -> die Ausnahme laeuft "
                   "aus dem Slot" % name,
                   M._mutant_treffer == [1] * len(mutationen)
                   and k["entkommen"][name][1] == ["RuntimeError"],
                   (M._mutant_treffer, k["entkommen"]))
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L58-L60: Chat-Layout und "erste Nachricht startet" (S7/S8, 2026-09-26) --

class _Weg:
    def __init__(self, n):
        self.n = n

    def maximum(self):
        return self.n


class _Rahmen:
    """Das Chatfenster mit der Schnittstelle, die diese Messungen von einem
    Rollbereich brauchen. Bis K2 lag der Chat als Tab im GEROLLTEN Dock;
    "rollt" hiess dort: der Inhalt braucht mehr, als das Dock hat. Das
    Chatfenster rollt nicht — dort heisst dasselbe: das Layout braucht
    MINDESTENS mehr, als das Fenster hat, also ist etwas abgeschnitten."""

    def __init__(self, fenster):
        self.f = fenster

    def viewport(self):
        return self.f

    def verticalScrollBar(self):                       # noqa: N802
        return _Weg(max(0, self.f.layout().minimumSize().height()
                        - self.f.height()))

    def horizontalScrollBar(self):                     # noqa: N802
        return _Weg(max(0, self.f.layout().minimumSize().width()
                        - self.f.width()))


def _chat_ziehen(D, z, breite=None, hoehe=700):
    """Das Fenster beim Chat zeigen und seinen KOERPER (K12: dort lebt der
    Chat) auf `breite` x `hoehe` ziehen, drei Takte. `breite` None: die
    schmalste Breite, die das Fenster zulaesst (ANGEDOCKT_BREITE_MIN).
    -> `_Rahmen` um den Koerper."""
    if breite is None:
        breite = D.ANGEDOCKT_BREITE_MIN
    f = z["fenster"]
    D._chat_oeffnen(z)
    D._chat_einstellungen_zeigen(z, False)
    # Erst die Lage nach dem Oeffnen (`_fenster_lage`, singleShot) — sonst
    # setzte sie das Fenster nach dem Ziehen wieder auf 420 px.
    _APP.processEvents()
    # Seit K9 ist das Chatfenster ein QDockWidget: gemessen wird sein
    # INHALT (ohne Titelleiste), und der bekommt genau `breite` x `hoehe`
    # — wie vorher das ganze Fenster.
    inhalt = _chat_inhalt(f)
    lay_min = inhalt.layout().minimumSize() if inhalt.layout() else None
    if breite < inhalt.minimumWidth() or hoehe < inhalt.minimumHeight() \
            or (lay_min is not None and (breite < lay_min.width()
                                         or hoehe < lay_min.height())):
        # Nur fuer die Kontrollen: kleiner, als das Fenster sich ziehen
        # liesse (auch unter die Mindestgroesse seines Layouts).
        from PyQt6.QtWidgets import QLayout
        inhalt.layout().setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
        inhalt.setMinimumSize(0, 0)
        f.setMinimumSize(0, 0)
        if f is not inhalt and f.layout() is not None:
            # Das Dock selbst haelt sonst die Mindestgroesse seines Inhalts.
            f.layout().setSizeConstraint(
                QLayout.SizeConstraint.SetNoConstraint)
    f.resize(breite, hoehe)
    _APP.processEvents()
    dw, dh = breite - inhalt.width(), hoehe - inhalt.height()
    if dw or dh:
        f.resize(f.width() + dw, f.height() + dh)
    for _ in range(3):
        D._auffrischen(z)
        _APP.processEvents()
    return _Rahmen(inhalt)


def _chat_inhalt(f):
    """Der Inhalt des Fensters: `widget()` des Docks (seit K12 der Koerper
    mit Segmenten und dem Chat)."""
    from PyQt6.QtWidgets import QDockWidget
    if isinstance(f, QDockWidget) and f.widget() is not None:
        return f.widget()
    return f


def _chat_fuellen(D, z, fall):
    """Ein Chat-Zustand wie im Betrieb, ohne Prozess. `fall`: leer, karten,
    karte_klein, laufend, fehler."""
    chat = z["chat"]
    zeilen = [{"art": "text", "text": "Antwort %d, lang genug, dass sie im "
               "schmalen Dock umbricht" % i} for i in range(60)]
    if fall in ("karten", "karte_klein"):
        n = 3 if fall == "karten" else 1
        code = "x = 1\n" * 30 if fall == "karten" else "x = 1"
        chat.update(an=True, laeuft_zug=True, anbieter="claude",
                    ereignisse=zeilen, freigaben=[
                        {"id": "f%d" % i, "offen": True,
                         "name": "execute_cadwork_command",
                         "eingabe": {"code": code}, "beschreibung": "Probe"}
                        for i in range(n)])
    elif fall == "laufend":
        chat.update(an=True, laeuft_zug=True, anbieter="claude",
                    ereignisse=zeilen,
                    laufender_text="Wort " * 800 + "ENDE-DER-ANTWORT")
    elif fall == "fehler":
        chat.update(ereignisse=zeilen)
        D._chat_fehler_zeigen(z, "Chat startet nicht: " + "ein langer "
                              "Grund " * 40)
    chat["stand"] = chat.get("stand", 0) + 1


def _unten_messen(D, z, fall, hoehe=700, breite=None):
    """-> dict: rollt das Dock, stehen Eingabe, Senden und Modell ganz im
    Bild, Hoehen der Karten und der laufenden Antwort."""
    from PyQt6.QtCore import QPoint
    _chat_fuellen(D, z, fall)
    sc = _chat_ziehen(D, z, breite, hoehe)
    vp = sc.viewport()
    w = z["w"]
    unten = []
    for teil in ("chat_eingabe", "chat_senden", "chat_modus",
                 "chat_modell_knopf"):
        wd = w[teil]
        p = wd.mapTo(vp, QPoint(0, 0))
        unten.append(wd.isVisible() and p.y() >= 0
                     and p.y() + wd.height() <= vp.height())
    rolle = w["chat_freigabe"]
    inhalt = rolle.widget()
    return {"vmax": sc.verticalScrollBar().maximum(), "unten": all(unten),
            "rolle": rolle.height() if rolle.isVisible() else None,
            "karten": inhalt.heightForWidth(rolle.viewport().width()),
            "laufend": w["chat_laufend"].text(),
            "meldung": _meldung(z)}


def zelle_eingabe_bleibt_unten():
    """L58 (S7, Plan B.11): die Eingabe bleibt unten sichtbar und rollt nicht
    mit dem ganzen Dock. Vorher lag alles in EINEM Rollbereich, und alles,
    was im Chat wuchs (laufende Antwort, Freigabe-Karten, Verlauf mit
    200 px Mindesthoehe), schob sie aus dem Bild."""
    try:
        for fall in ("leer", "karten", "laufend", "fehler"):
            _frischer_start()
            D, z, _d = aufbauen()
            m = _unten_messen(D, z, fall)
            pruefe("L58 %s, schmalstes Fenster x 700: es rollt nicht, "
                   "Eingabe, Senden und Modell stehen ganz im Bild" % fall,
                   m["vmax"] == 0 and m["unten"], m)
            if fall == "karten":
                pruefe("L58 drei Karten: der Kartenbereich steht da, "
                       "mindestens %d px hoch" % D.FREIGABE_MIN_HOEHE,
                       m["rolle"] is not None
                       and m["rolle"] >= D.FREIGABE_MIN_HOEHE, m)
            if fall == "laufend":
                pruefe("L58 von einer langen Antwort steht das ENDE da, "
                       "gekuerzt", m["laufend"].endswith("ENDE-DER-ANTWORT")
                       and len(m["laufend"]) <= D.LAUFEND_ZEICHEN + 2,
                       (len(m["laufend"]), m["laufend"][-30:]))
            if fall == "fehler":
                pruefe("L58 die Fehlerzeile steht an der Eingabe",
                       m["meldung"].startswith("Chat startet nicht"), m)
        # Ein hohes Dock (Platz uebrig): hier zeigt sich leere Flaeche.
        _frischer_start()
        D, z, _d = aufbauen()
        m = _unten_messen(D, z, "karte_klein", hoehe=1000)
        pruefe("L58 eine kleine Karte, schmal x 1000: kein leerer Platz darunter "
               "(Bereich so hoch wie die Karte)", m["rolle"] is not None
               and m["rolle"] <= max(D.FREIGABE_MIN_HOEHE, m["karten"] + 4),
               m)
        # KONTROLLE: ein zu kleines Dock rollt — die Messung sieht es.
        _frischer_start()
        D, z, _d = aufbauen()
        k = _unten_messen(D, z, "leer", hoehe=150)
        pruefe("L58 KONTROLLE: schmal x 150 -> zu klein, die Messung merkt es",
               k["vmax"] > 0 or not k["unten"], k)
        # KONTROLLE: ein Verlauf, der viel Hoehe VERLANGT (Mindesthoehe),
        # schiebt die Eingabe aus dem Fenster — die Messung sieht es. (Bis K2
        # stand hier "ohne die Groessenregeln": im GEROLLTEN Dock bekam der
        # Inhalt die Summe der Hoehenwuensche; ein Fenster gibt nur, was es
        # hat — dort zaehlen die Mindesthoehen.)
        M = dashboard_laden()
        M.VERLAUF_MIN_HOEHE = M.VERLAUF_MIN_HOEHE_KARTE = 900
        _frischer_start()
        D, z, _d = aufbauen(D=M)
        k = _unten_messen(D, z, "karten")
        pruefe("L58 KONTROLLE: ein Verlauf mit 900 px Mindesthoehe -> das "
               "Fenster ist zu klein fuer sein Layout, die Messung merkt es",
               k["vmax"] > 0, k)
        # KONTROLLE: ohne Hoechstmass nach Inhalt steht Leere unter der Karte.
        M = _mutant(_anweisungen(
            "_hoehe_nach_inhalt",
            lambda s: (isinstance(s, ast.If)
                       and "maximumHeight" in ast.unparse(s.test)),
            "teil.setMaximumHeight(hoechst)"))
        _frischer_start()
        D, z, _d = aufbauen(D=M)
        k = _unten_messen(D, z, "karte_klein", hoehe=1000)
        pruefe("L58 KONTROLLE: ohne Hoehe nach Inhalt ist der Kartenbereich "
               "hoeher als die Karte", M._mutant_treffer == [1]
               and k["rolle"] is not None
               and k["rolle"] > max(M.FREIGABE_MIN_HOEHE, k["karten"] + 4),
               (M._mutant_treffer, k))
        # KONTROLLE: ohne Kuerzen steht die ganze Antwort im Feld.
        M = _mutant(_anweisungen(
            "_laufend_kurz",
            lambda s: (isinstance(s, ast.If)
                       and "LAUFEND_ZEICHEN" in ast.unparse(s.test)),
            "return text"))
        _frischer_start()
        D, z, _d = aufbauen(D=M)
        k = _unten_messen(D, z, "laufend")
        pruefe("L58 KONTROLLE: ohne Kuerzen steht die ganze Antwort im Feld",
               M._mutant_treffer == [1]
               and len(k["laufend"]) > M.LAUFEND_ZEICHEN + 2,
               (M._mutant_treffer, len(k["laufend"])))
    finally:
        _frischer_start()


def _breite_messen(D, z, breite=None):
    """-> dict: rollt das Dock quer, ist der Chat-Tab schmal genug, welche
    Knoepfe/Felder sind schmaler als ihr Mindestmass (gequetscht)."""
    from PyQt6.QtWidgets import (QComboBox, QPlainTextEdit, QPushButton,
                                 QWidget)
    sc = _chat_ziehen(D, z, breite)
    w = z["w"]
    feld = w["chat_eingabe"]
    seite = w["seiten"].widget(0)
    karte = feld.parentWidget()
    gequetscht = []
    if karte.width() < karte.minimumSizeHint().width():
        gequetscht.append(("karte", karte.width(),
                           karte.minimumSizeHint().width()))
    rolle = w["chat_freigabe"]
    for c in karte.findChildren(QWidget):
        if not isinstance(c, (QPushButton, QComboBox, QPlainTextEdit)):
            continue
        if not c.isVisible() or rolle.isAncestorOf(c):
            continue
        if c.width() < c.minimumSizeHint().width():
            gequetscht.append((c.text() if isinstance(c, QPushButton)
                               else type(c).__name__, c.width(),
                               c.minimumSizeHint().width()))
    return {"hmax": sc.horizontalScrollBar().maximum(),
            "seite": (seite.minimumSizeHint().width(), seite.width()),
            "gequetscht": gequetscht, "viewport": sc.viewport().width()}


def _breite_faelle(D, z, breite=None):
    """Die Gestalten des Chat-Tabs: Claude Code (Modell, Denkstufe, auch
    "Ultracode"), OpenAI (Modell und "Modelle abfragen"), laufend."""
    w = z["w"]
    ergebnis = {}
    _anbieter_waehlen(z, "claude")
    ergebnis["claude"] = _breite_messen(D, z, breite)
    _waehlen(w["chat_stufe"], "ultracode")
    ergebnis["ultracode"] = _breite_messen(D, z, breite)
    _anbieter_waehlen(z, "openai")
    ergebnis["openai"] = _breite_messen(D, z, breite)
    _anbieter_waehlen(z, "claude")
    z["chat"].update(an=True, laeuft_zug=False, anbieter="claude",
                     ereignisse=[], freigaben=[])
    ergebnis["laufend"] = _breite_messen(D, z, breite)
    z["chat"]["an"] = False
    return ergebnis


def zelle_breite_300():
    """L59 (S7): das Dock ist mindestens 300 px breit (`inhalt`); der
    Chat-Tab muss dort gehen — nichts gequetscht, kein Querrollen, in
    jeder Gestalt (Claude Code, "Ultracode", OpenAI, laufend). Gemessen mit
    Windows-Schriften (QT_QPA_FONTDIR oben). Der Stand vor S7 passte damit
    auch (Tab 238 px); nur mit der Ersatzschrift von Qt brauchte er 500."""
    try:
        _frischer_start()
        D, z, _d = aufbauen()
        for fall, m in _breite_faelle(D, z).items():
            # K12: der Koerper ist mindestens ANGEDOCKT_BREITE_MIN (320) px
            # breit — vorher das Chatfenster 300 px.
            pruefe("L59 %s bei %d px (Koerper des Fensters): nichts "
                   "abgeschnitten, Seite schmal genug, nichts gequetscht"
                   % (fall, D.ANGEDOCKT_BREITE_MIN),
                   m["viewport"] == D.ANGEDOCKT_BREITE_MIN and m["hmax"] == 0
                   and m["seite"][0] <= m["seite"][1]
                   and m["gequetscht"] == [], m)
        # KONTROLLE (schmaler): der Koerper 190 px breit — dort MUSS die
        # Messung Gequetschtes finden.
        _frischer_start()
        D, z, _d = aufbauen()
        k = _breite_messen(D, z, 190)
        pruefe("L59 KONTROLLE: Koerper 190 px breit -> die Messung findet "
               "Gequetschtes", k["gequetscht"] != []
               or k["seite"][0] > k["seite"][1] or k["hmax"] > 0, k)
    finally:
        _frischer_start()


def _aufruf_umbenennen(funktion, alt, neu):
    """Mutation: jeder Aufruf `alt(...)` in `funktion` ruft `neu(...)`."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for k in (ast.walk(f) if f is not None else ()):
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id == alt):
                k.func.id = neu
                n += 1
        return n
    return mutation


def _s8_lauf(laden=None):
    """Claude Code ueber die Start-Attrappe (Temp-Projekt, Temp-Heim): die
    erste Nachricht, eine zweite, "Neuer Chat" im Zug und dazwischen, die
    naechste Nachricht. -> dict."""
    from PyQt6.QtWidgets import QPushButton
    heim = _tempfile.mkdtemp(prefix="omcad_live_heim_")
    alt_heim = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = heim
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    w = z["w"]
    chat = z["chat"]
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    echt_geklaert = D._chat_ende_geklaert
    try:
        with _ChatStartAttrappe(D, z) as att:
            D._chat_zeichnen(z)
            karte = w["chat_stapel"].widget(0)
            # Knoepfe ohne Text (✎, ■) tragen ihren Namen als
            # `accessibleName` (Feinschliff 2026-09-28).
            m["knoepfe"] = sorted(b.accessibleName() or b.text() for b in
                                  karte.findChildren(QPushButton)
                                  if not b.isHidden())
            # Etappe D: ohne bisherige Chats steht der Verlauf da, nicht
            # die (leere) Liste.
            m["wahl_vorher"] = (not w["chat_verlauf"].isHidden()
                                and w["chat_liste"].isHidden())
            rest = _senden_klick(D, z, "erste Frage")
            m["erste"] = (len(att.gestartet), rest,
                          [e.get("text") for e in chat.get("ereignisse") or ()
                           if e.get("art") == "ich"])
            D._chat_zeichnen(z)
            hinweis = _hinweis_im_aufklapper(D, z)
            m["gesperrt"] = (w["chat_modell"].isEnabled(),
                             w["chat_stufe"].isEnabled(),
                             bool(hinweis), hinweis,
                             not w["chat_ende"].isHidden(),
                             w["chat_liste"].isHidden())
            _senden_klick(D, z, "zweite Frage")
            m["zweite"] = len(att.gestartet)
            # "Neuer Chat" mitten im Zug: keine Rueckfrage (nicht-modal),
            # der Chat laeuft weiter. Die Rueckfrage ist hier eine Attrappe,
            # sonst hielte ein Fehler das Gate im modalen Fenster fest.
            geklaert = []
            D._chat_ende_geklaert = lambda zz: geklaert.append(1) or False
            chat["laeuft_zug"] = True
            D._chat_zeichnen(z)
            knopf_im_zug = w["chat_neu"].isEnabled()
            D._chat_neu(z)
            m["neu_im_zug"] = (knopf_im_zug, len(geklaert),
                               bool(chat.get("an")), _meldung(z))
            D._chat_ende_geklaert = echt_geklaert
            chat["laeuft_zug"] = False
            # "Neuer Chat" zwischen zwei Zuegen: beendet sauber, leert.
            # (setdefault: in der Kontrolle "altes Senden" lief kein Start)
            chat.setdefault("ereignisse", []).append(
                {"art": "text", "text": "Antwort"})
            chat["stand"] = chat.get("stand", 0) + 1
            D._chat_zeichnen(z)
            m["vorher"] = w["chat_verlauf"].count()
            # Ein alter Chat aus der Liste war geoeffnet (fortsetzen, S9).
            z["sitzung_offen"] = {"id": "alt-1", "titel": "alte Sitzung",
                                  "ordner": att.projekt, "ereignisse": []}
            w["chat_neu"].click()
            # Ein Nachzuegler des beendeten Chats (sein Leser schreibt noch
            # in SEINE Liste) darf nicht wieder erscheinen.
            (chat.get("ereignisse") or []).append(
                {"art": "text", "text": "Nachzuegler"})
            chat["stand"] = chat.get("stand", 0) + 1
            D._chat_zeichnen(z)
            m["neu"] = (bool(chat.get("an")), w["chat_verlauf"].count(),
                        ["Neuer Chat"],
                        (z.get("sitzung_offen") or {}).get("id"))
            rest = _senden_klick(D, z, "neuer Anfang")
            D._chat_zeichnen(z)
            m["danach"] = (len(att.gestartet), rest, _verlauf_texte(z))
    finally:
        D._chat_ende_geklaert = echt_geklaert
        if alt_heim is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = alt_heim
        _frischer_start()
    return m


def _fehlerzeile_lauf(laden=None):
    """Ein Start scheitert; dann ist die Schutzfrist des Kopfes um, und zwei
    Takte laufen. -> dict: (Zeile an der Eingabe, Kopfzeile, Feld)."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        with _ChatStartAttrappe(D, z) as att:
            att.fehler.append("Probe-Grund")
            rest = _senden_klick(D, z)
            m["sofort"] = (_meldung(z), _hinweis(z), rest)
            z["fehler_bis"] = 0.0
            for _ in range(2):
                D._auffrischen(z)
                D._chat_zeichnen(z)
            m["zwei_takte"] = (_meldung(z), _hinweis(z))
    finally:
        _frischer_start()
    return m


def _art_lauf(laden=None):
    """Die Zeile "was laeuft" fuer jeden Anbieter aus ANBIETER (Quelle) und
    fuer einen laufenden Chat, dessen Anbieter nicht mehr im Feld steht."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    w = z["w"]
    m = {"treffer": getattr(D, "_mutant_treffer", None), "je": {}}
    try:
        for a in D._anbieter_modul().ANBIETER:
            _anbieter_waehlen(z, a["id"])
            D._chat_zeichnen(z)
            m["je"][a["id"]] = (a["art"], w["chat_art"].text(),
                                not w["chat_art"].isHidden())
        # Es laeuft Claude Code, im Feld steht schon OpenAI.
        z["chat"].update(an=True, anbieter="claude", ereignisse=[],
                         freigaben=[])
        _anbieter_waehlen(z, "openai")
        D._chat_zeichnen(z)
        m["laufend"] = w["chat_art"].text()
        z["chat"]["an"] = False
        D._chat_zeichnen(z)
        m["danach"] = w["chat_art"].text()
    finally:
        _frischer_start()
    return m


def _marke_lauf(laden=None):
    """Ein Chat mit einer Zeile, dann ein NEUER Chat (eigene Liste) mit
    ebenfalls einer Zeile. -> was der Verlauf danach zeigt."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    try:
        chat = z["chat"]
        chat.update(ereignisse=[{"art": "text", "text": "alter Chat"}],
                    stand=1)
        D._chat_zeichnen(z)
        chat.update(ereignisse=[{"art": "text", "text": "neuer Chat"}],
                    stand=2)
        D._chat_zeichnen(z)
        return (getattr(D, "_mutant_treffer", None), _verlauf_texte(z))
    finally:
        _frischer_start()


#: Was die Zeile je ART sagen muss (Uebergabe 2026-09-25, Abschnitt 5).
ART_MUSS = {"cli": ("Agent", "Arbeitsordner"),
            "codex": ("Codex", "nur mit den Cadwork-Werkzeugen"),
            "openai": ("nur mit den Cadwork-Werkzeugen",
                       "ohne Zugriff auf Dateien")}


def zelle_erste_nachricht():
    """L60 (S8): kein "Starten" mehr — die erste Nachricht startet den Chat,
    "Neuer Chat" beendet sauber und leert den Verlauf, "Beenden" steht
    fuer einen laufenden Chat da. Dazu (S7) die Fehlerzeile an der Eingabe,
    die gesperrte Leiste mitten im Chat und die Zeile "was laeuft"."""
    m = _s8_lauf()
    pruefe("L60 im Chat-Tab gibt es keinen Knopf 'Starten' mehr",
           "Starten" not in m["knoepfe"] and "Neuer Chat" in m["knoepfe"],
           m["knoepfe"])
    pruefe("L60 die erste Nachricht startet den Chat und wird gesendet, das "
           "Feld ist leer", m["erste"] == (1, "", ["erste Frage"]), m["erste"])
    pruefe("L60 mitten im Chat: Modell und Denkstufe gesperrt, Hinweis "
           "'gilt ab dem nächsten Chat', 'Beenden' steht da",
           m["gesperrt"][:3] == (False, False, True)
           and "gilt ab dem nächsten chat" in m["gesperrt"][3].lower()
           and m["gesperrt"][4], m["gesperrt"])
    pruefe("L60 vor dem Chat (ohne bisherige Chats) steht der Verlauf da, "
           "waehrend des Chats nie die Liste",
           m["wahl_vorher"] and m["gesperrt"][5],
           (m["wahl_vorher"], m["gesperrt"]))
    pruefe("L60 die zweite Nachricht startet keinen zweiten Chat",
           m["zweite"] == 1, m["zweite"])
    pruefe("L60 'Neuer Chat' mitten im Zug: Knopf aus, keine Rueckfrage, "
           "der Chat laeuft weiter, die Zeile sagt warum",
           m["neu_im_zug"][:3] == (False, 0, True)
           and "arbeitet gerade" in m["neu_im_zug"][3], m["neu_im_zug"])
    pruefe("L60 'Neuer Chat' zwischen zwei Zuegen: beendet, Verlauf leer "
           "(auch mit einem Nachzuegler), kein alter Chat mehr geoeffnet",
           m["vorher"] >= 2 and m["neu"][0] is False and m["neu"][1] == 0
           and m["neu"][2][:1] == ["Neuer Chat"] and m["neu"][3] is None,
           (m["vorher"], m["neu"]))
    pruefe("L60 die naechste Nachricht startet einen neuen Chat, der Verlauf "
           "zeigt nur ihn", m["danach"] == (2, "", ["Du:  neuer Anfang"]),
           m["danach"])
    # KONTROLLE: das alte Senden (ohne laufenden Chat tut es nichts).
    k = _s8_lauf(lambda: _mutant(_anweisungen(
        "_chat_senden",
        lambda s: (isinstance(s, ast.If)
                   and "_chat_starten" in ast.unparse(s.test)),
        "if not chat.get('an'):\n    return")))
    pruefe("L60 KONTROLLE: das alte Senden startet nichts, der Text bleibt",
           k["treffer"] == [1] and k["erste"] == (0, "erste Frage", []),
           (k["treffer"], k["erste"]))
    # KONTROLLE: "Neuer Chat" ohne das Verwerfen der Anzeige.
    k = _s8_lauf(lambda: _mutant(_anweisungen(
        "_chat_neu", _beginnt("z['verlauf_verworfen'] ="))))
    pruefe("L60 KONTROLLE: ohne Verwerfen bleibt der alte Verlauf stehen",
           k["treffer"] == [1] and k["neu"][1] > 0, (k["treffer"], k["neu"]))
    # KONTROLLE: "Neuer Chat" laesst den geoeffneten alten Chat stehen.
    k = _s8_lauf(lambda: _mutant(_anweisungen(
        "_chat_neu", _beginnt("z['sitzung_offen'] = None"))))
    pruefe("L60 KONTROLLE: ohne das Zuruecksetzen bleibt der alte Chat "
           "geoeffnet", k["treffer"] == [1] and k["neu"][3] == "alt-1",
           (k["treffer"], k["neu"]))
    # KONTROLLE: "Neuer Chat" ohne die Sperre im Zug fragt (modal) nach.
    k = _s8_lauf(lambda: _mutant(_anweisungen(
        "_chat_neu", lambda s: (isinstance(s, ast.If)
                                and "laeuft_zug" in ast.unparse(s.test)))))
    pruefe("L60 KONTROLLE: ohne die Sperre im Zug ginge 'Neuer Chat' an die "
           "Rueckfrage", k["treffer"] == [1] and k["neu_im_zug"][1] == 1,
           (k["treffer"], k["neu_im_zug"]))

    # Der Verlauf merkt sich (Liste, Laenge), nicht nur die Laenge: ein
    # neuer Chat mit gleich vielen Zeilen wird trotzdem gezeichnet.
    treffer, texte = _marke_lauf()
    pruefe("L60 ein neuer Chat mit gleich vielen Zeilen wird gezeichnet",
           texte == ["neuer Chat"], texte)
    treffer, texte = _marke_lauf(lambda: _mutant(_anweisungen(
        "_verlauf_zeigen", _beginnt("wer = id("), "wer = None")))
    pruefe("L60 KONTROLLE: nur die Laenge gemerkt -> der alte Chat bleibt "
           "stehen", treffer == [1] and texte == ["alter Chat"],
           (treffer, texte))

    f = _fehlerzeile_lauf()
    pruefe("L60 ein gescheiterter Start steht an der Eingabe, nicht im Kopf, "
           "der Text bleibt", "Probe-Grund" in f["sofort"][0]
           and "Probe-Grund" not in f["sofort"][1]
           and f["sofort"][2] == "Probe-Nachricht", f)
    pruefe("L60 ... und steht nach zwei Takten (Schutzfrist des Kopfes um) "
           "noch da", "Probe-Grund" in f["zwei_takte"][0], f)
    k = _fehlerzeile_lauf(lambda: _mutant(_aufruf_umbenennen(
        "_chat_starten", "_chat_fehler_zeigen", "_fehler_zeigen")))
    pruefe("L60 KONTROLLE: der alte Weg (Kopfzeile) — nach zwei Takten weg",
           # 8 Stellen seit der Nacharbeit D (Verlauf laedt, belegt, und
           # SitzungBelegt aus `C.starten`).
           k["treffer"] == [8] and "Probe-Grund" in k["sofort"][1]
           and k["zwei_takte"] == ("", ""), k)

    a = _art_lauf()
    falsch = {kennung: (art, text) for kennung, (art, text, sichtbar)
              in a["je"].items()
              if not sichtbar or not all(t in text
                                         for t in ART_MUSS.get(art, ("?",)))}
    pruefe("L60 'was laeuft' folgt der ART jedes Anbieters aus ANBIETER",
           a["je"] and not falsch, falsch or a["je"])
    pruefe("L60 ... und nennt beim laufenden Chat dessen Art, nicht die im "
           "Feld", "Arbeitsordner" in a["laufend"]
           and "ohne Zugriff" in a["danach"], (a["laufend"], a["danach"]))
    D = dashboard_laden()
    pruefe("L60 KONTROLLE: ein Name, der 'Claude Code' sagt, entscheidet "
           "nichts — die Art 'openai' gibt den Chat-Satz",
           "ohne Zugriff" in D._art_text({"art": "openai",
                                          "name": "Claude Code (Probe)"})
           and "Arbeitsordner" in D._art_text({"art": "cli",
                                                "name": "Probe"}))
    k = _art_lauf(lambda: _mutant(_anweisungen(
        "_art_zeigen", lambda s: (isinstance(s, ast.If)
                                  and ast.unparse(s.test) == "laeuft"))))
    pruefe("L60 KONTROLLE: ohne den laufenden Chat folgt die Zeile dem Feld",
           k["treffer"] == [1] and "Arbeitsordner" not in k["laufend"],
           (k["treffer"], k["laufend"]))


# --- L61: Nacharbeit Etappe C (Pruefung 2026-09-26) ---------------------------

def _test_ersetzen(funktion, alt, neu):
    """Mutation: die Bedingung jedes `if` in `funktion`, deren Quelltext
    `alt` ist, durch `neu` ersetzen."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for k in (ast.walk(f) if f is not None else ()):
            if isinstance(k, (ast.If, ast.BoolOp)) and hasattr(k, "test") \
                    and ast.unparse(k.test) == alt:
                k.test = ast.parse(neu, mode="eval").body
                n += 1
        return n
    return mutation


def _iter_ersetzen(funktion, alt, neu):
    """Mutation: worueber jede `for`-Schleife in `funktion` laeuft, deren
    Quelltext `alt` ist, durch `neu` ersetzen (auch in inneren Funktionen)."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for k in (ast.walk(f) if f is not None else ()):
            if isinstance(k, ast.For) and ast.unparse(k.iter) == alt:
                k.iter = ast.parse(neu, mode="eval").body
                n += 1
        return n
    return mutation


def _return_im_except(funktion):
    """Mutation: jedes `return` in einem except von `funktion` streichen."""
    def mutation(baum):
        f, n = _funktion(baum, funktion), 0
        for h in (ast.walk(f) if f is not None else ()):
            if isinstance(h, ast.ExceptHandler):
                rest = [s for s in h.body if not isinstance(s, ast.Return)]
                n += len(h.body) - len(rest)
                h.body[:] = rest or [ast.Pass()]
        return n
    return mutation


def _tot_lauf(laden=None, beenden=False):
    """S8-Weg: die erste Nachricht startet, dann stirbt Claude Code ohne ein
    Wort (stderr hat den Grund, wie bei einem unbekannten Modellnamen).
    `beenden`: vorher beendet der NUTZER. Danach "Neuer Chat". -> dict."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    w, chat = z["w"], z["chat"]
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        with _ChatStartAttrappe(D, z):
            m["feld_nach_senden"] = _senden_klick(D, z, "Hallo")
            if beenden:
                D._chat_beenden(z)
            # So endet der Leser des CLI (omcad_a_chat, finally).
            chat.update(an=False, laeuft_zug=False,
                        stderr=["Error: model 'claude-foo' not found"])
            chat["stand"] = chat.get("stand", 0) + 1
            for _ in range(2):
                D._auffrischen(z)
                D._chat_zeichnen(z)
            m["tot"] = (w["chat_lage"].text(), _meldung(z),
                        w["chat_eingabe"].toPlainText())
            w["chat_neu"].click()
            D._chat_zeichnen(z)
            m["neu"] = (w["chat_lage"].text(), _meldung(z))
    finally:
        _frischer_start()
    return m


def _stoerung_lauf(laden=None):
    """Eine Stoerung des alten Chats, dann "Neuer Chat" — und ein Nachzuegler
    seines Lesers setzt die Stoerung noch einmal. -> (vorher, nachher,
    nach dem Nachzuegler) als Text der Lage."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    w, chat = z["w"], z["chat"]
    try:
        chat.update(an=False, ereignisse=[{"art": "text", "text": "alt"}],
                    fehler="Probe-Stoerung")
        chat["stand"] = chat.get("stand", 0) + 1
        D._chat_zeichnen(z)
        vorher = w["chat_lage"].text()
        w["chat_neu"].click()
        D._chat_zeichnen(z)
        nachher = w["chat_lage"].text()
        chat["fehler"] = "Nachzuegler-Stoerung"
        chat["stand"] = chat.get("stand", 0) + 1
        D._chat_zeichnen(z)
        return (getattr(D, "_mutant_treffer", None), vorher, nachher,
                w["chat_lage"].text())
    finally:
        _frischer_start()


def _knoepfe_messen(D, z, hoehe, zeilen=12, n=1, beschreibung="Probe",
                    aufklappen=False):
    """Freigabe-Karten wie im Betrieb, Dock 300 x `hoehe`. -> dict: stehen
    "Erlauben"/"Ablehnen" der ERSTEN Karte ganz im Kartenbereich, Rollweg
    des Bereichs, seine Hoehe, rollt das Dock."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QPushButton
    chat = z["chat"]
    chat.update(an=True, laeuft_zug=True, anbieter="claude",
                ereignisse=[{"art": "text", "text": "Antwort %d" % i}
                            for i in range(60)],
                freigaben=[{"id": "f%d" % i, "offen": True,
                            "name": "execute_cadwork_command",
                            "eingabe": {"code": "x = 1\n" * zeilen},
                            "beschreibung": beschreibung}
                           for i in range(n)])
    chat["stand"] = chat.get("stand", 0) + 1
    sc = _chat_ziehen(D, z, 276, hoehe)
    rolle = z["w"]["chat_freigabe"]
    if aufklappen:
        for b in rolle.widget().findChildren(QPushButton):
            if b.text() == "Wortlaut zeigen":
                b.click()
                break
        for _ in range(3):
            D._auffrischen(z)
            _APP.processEvents()
    vp = rolle.viewport()
    karte = rolle.widget().layout().itemAt(0).widget()
    sichtbar = []
    for b in karte.findChildren(QPushButton):
        if b.text() in ("Erlauben", "Ablehnen"):
            p = b.mapTo(vp, QPoint(0, 0))
            sichtbar.append(b.isVisible() and p.y() >= 0
                            and p.y() + b.height() <= vp.height())
    return {"knoepfe": len(sichtbar) == 2 and all(sichtbar),
            "rollweg": rolle.verticalScrollBar().maximum(),
            "rolle": rolle.height(), "dock": sc.verticalScrollBar().maximum()}


def _karten_lauf(laden=None):
    """Die Knoepfe der ersten Karte in den Groessen aus der Pruefung."""
    m = {}
    faelle = {"12 Zeilen, 1000 px": dict(hoehe=1000, zeilen=12),
              "12 Zeilen, 700 px": dict(hoehe=500, zeilen=12),
              # Seit 2026-09-28 (weniger Kopf) an der Mindesthoehe des
              # Fensters: bei 500 px passten die Karten auch mit 80 px
              # Verlauf, die Kontrolle unten saehe nichts.
              # K12: an der Mindesthoehe des OFFENEN Fensters — der
              # Koerper darunter (ohne Kopf und Rand des Docks).
              "30 Zeilen, lange Beschreibung, Mindesthoehe": dict(
                  hoehe=None, zeilen=30, beschreibung="Eine lange "
                  "Beschreibung von Claude, was dieser Befehl tun soll " * 5),
              "drei Karten, 700 px": dict(hoehe=500, zeilen=30, n=3),
              "Wortlaut aufgeklappt, 700 px": dict(hoehe=500, zeilen=30,
                                                   aufklappen=True)}
    for name, kw in faelle.items():
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        if kw.get("hoehe") is None:
            kw = dict(kw, hoehe=D.OFFEN_HOEHE_MIN - D.KOPF_HOEHE - 4)
        try:
            m[name] = _knoepfe_messen(D, z, **kw)
            m["treffer"] = getattr(D, "_mutant_treffer", None)
        finally:
            _frischer_start()
    return m


def _knopf_wirft_lauf(laden=None):
    """Eine Karte; das Beantworten wirft. "Erlauben" und "Ablehnen" klicken
    und zaehlen, was aus dem Slot laeuft (eigener excepthook, wie L57)."""
    import io
    from PyQt6.QtWidgets import QPushButton
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    C = D._chat_modul()
    echt = C.freigabe_beantworten
    alt_hook, alt_err = sys.excepthook, sys.stderr
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        _knoepfe_messen(D, z, 1000)
        karte = z["w"]["chat_freigabe"].widget().layout().itemAt(0).widget()
        knoepfe = [b for b in karte.findChildren(QPushButton)
                   if b.text() in ("Erlauben", "Ablehnen")]

        def wirft(*_a, **_k):
            raise RuntimeError("Probe: Freigabe")
        C.freigabe_beantworten = wirft
        fang = []
        sys.excepthook = lambda t, v, tb: fang.append(t.__name__)
        sys.stderr = io.StringIO()
        for b in knoepfe:
            b.click()
        _APP.processEvents()
        m.update(klicks=len(knoepfe), entkommen=fang,
                 gemeldet="Probe: Freigabe" in sys.stderr.getvalue())
    finally:
        C.freigabe_beantworten = echt
        sys.excepthook, sys.stderr = alt_hook, alt_err
        _frischer_start()
    return m


def _aufklappen_lauf(laden=None):
    """300 x 1000, eine Karte: Hoehe des Kartenbereichs vor und nach
    "Wortlaut zeigen"."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    try:
        vorher = _knoepfe_messen(D, z, 1000, zeilen=30)["rolle"]
        nachher = _knoepfe_messen(D, z, 1000, zeilen=30,
                                  aufklappen=True)["rolle"]
        return getattr(D, "_mutant_treffer", None), vorher, nachher
    finally:
        _frischer_start()


def _kurz_laufend_lauf(laden=None):
    """Eine kurze laufende Antwort im hohen Dock: ihre Hoehe und was ihr
    Text braucht."""
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    try:
        z["chat"].update(an=True, laeuft_zug=True, anbieter="claude",
                         ereignisse=[], laufender_text="Kurze Antwort")
        z["chat"]["stand"] = 1
        _chat_ziehen(D, z, 300, 1000)
        lbl = z["w"]["chat_laufend"]
        return (getattr(D, "_mutant_treffer", None), lbl.height(),
                lbl.heightForWidth(lbl.width()))
    finally:
        _frischer_start()


def _kleinkram_lauf(laden=None):
    """Gestoppter Dienst, Sitzungswahl und Leisten-Hinweis vor dem Chat,
    lange Fehlermeldung, Senden scheitert, Ordner nach "Neuer Chat"."""
    heim = _tempfile.mkdtemp(prefix="omcad_live_heim_")
    alt_heim = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = heim
    m = {}
    try:
        # (1) Ein GESTOPPTER Dienst ist keine Verbindung.
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        with _ChatStartAttrappe(D, z) as att:
            z["dienst"].zustand = "stopped"
            rest = _senden_klick(D, z, "Hallo")
            m["gestoppt"] = (len(att.gestartet), rest, _meldung(z))
        z["dienst"].zustand = "ready"
        # (2) Vor dem Chat: die bisherigen Chats nur bei Claude Code, kein
        # Hinweis "gilt ab dem naechsten Chat". Ein Dock-Chat liegt bereit.
        je = {}
        with _ChatStartAttrappe(D, z) as att:
            _dock_sitzung(att.projekt, "d0c00001-kk", frage="Wand Nord")
            D._liste_auffrischen(z)
            for kennung in ("claude", "openai", "codex"):
                _anbieter_waehlen(z, kennung)
                _warte_qt(D, z, lambda: not w["chat_liste"].isHidden(),
                          frist=3.0 if kennung == "claude" else 1.5)
                je[kennung] = (not w["chat_liste"].isHidden(),
                               bool(_hinweis_im_aufklapper(D, z)))
        m["vor_dem_chat"] = je
        # (3) Eine sehr lange Meldung an der Eingabe.
        D._chat_fehler_zeigen(z, "Chat startet nicht: " + "Grund " * 200)
        m["lang"] = len(_meldung(z))
        _frischer_start()
        # (4) Der Chat laeuft, aber senden wirft: der Text bleibt.
        D, z, _d = aufbauen(D=laden() if laden else None)
        with _ChatStartAttrappe(D, z) as att:
            _senden_klick(D, z, "erste")

            def wirft(chat, text):
                raise RuntimeError("Probe-Senden")
            sys.modules[att.NAME].senden = wirft
            rest = _senden_klick(D, z, "zweite")
            m["senden_wirft"] = (rest, _meldung(z))
        _frischer_start()
        # (5) Ohne Ordner wartet die Nachfrage; "Neuer Chat" hebt das auf.
        D, z, _d = aufbauen(D=laden() if laden else None)
        w = z["w"]
        with _ChatStartAttrappe(D, z, projekt=None):
            D._chat_zeichnen(z)
            leer = w["chat_liste"].count()
            projekt = _tempfile.mkdtemp(prefix="omcad_live_projekt_")
            _dock_sitzung(projekt, "d0c00002-ordner", frage="Dach Ost")
            os.environ["OPEN_MCP_CAD_PROJEKT"] = projekt
            D._chat_zeichnen(z)
            time.sleep(0.2)
            D._chat_zeichnen(z)
            gedrosselt = w["chat_liste"].count()
            w["chat_neu"].click()
            _warte_qt(D, z, lambda: w["chat_liste"].count() > 0, frist=1.0)
            m["ordner"] = (leer, gedrosselt, _liste_titel(z))
    finally:
        if alt_heim is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = alt_heim
        _frischer_start()
    return m


#: Woran ein Satz fuer Laien scheitert: Technik, die nur der Entwickler kennt.
TECHNIK_WOERTER = ("OPEN_MCP_CAD", ".txt", "Steckplatz", "Umgebungsvariable",
                   "Port")


def _laientext_ok(text):
    return bool(text) and not any(t in text for t in TECHNIK_WOERTER)


def zelle_nacharbeit_c():
    """L61 (Pruefung Etappe C): der Grund, wenn Claude Code gleich nach der
    ersten Nachricht stirbt; die Knoepfe einer Freigabe-Karte im Bild;
    "Neuer Chat" nimmt die alte Stoerung mit; Kleinkram, den kein Gate
    pruefte (die Mutanten X3, X10, X11, X13, X14, X15, X17, X18)."""
    # -- Befund mittel 1: stirbt das CLI nach der ersten Nachricht ----------
    m = _tot_lauf()
    pruefe("L61 stirbt Claude Code nach der ersten Nachricht ohne ein Wort: "
           "der Grund steht in der Lage und an der Eingabe, der Text wieder "
           "im Feld", m["feld_nach_senden"] == ""
           and "claude-foo" in m["tot"][0]
           and m["tot"][1].startswith("Claude Code startet nicht")
           and "claude-foo" in m["tot"][1] and m["tot"][2] == "Hallo", m)
    pruefe("L61 ... 'Neuer Chat' nimmt die Meldung weg",
           "claude-foo" not in m["neu"][0] and m["neu"][1] == "", m["neu"])
    b = _tot_lauf(beenden=True)
    pruefe("L61 hat der NUTZER beendet, ist das kein Startfehler (Feld leer, "
           "keine Meldung)", "claude-foo" not in b["tot"][0]
           and b["tot"][1] == "" and b["tot"][2] == "", b["tot"])
    k = _tot_lauf(lambda: _mutant(_test_ersetzen(
        "_chat_zeichnen",
        "offen is None and _ohne_antwort_gestorben(z, chat, an, liste, "
        "verworfen)",
        "offen is None and not an and chat.get('stderr') and "
        "not chat.get('ereignisse')")))
    pruefe("L61 KONTROLLE: die alte Bedingung (Verlauf leer) -> der Grund "
           "geht verloren", k["treffer"] == [1] and "claude-foo"
           not in k["tot"][0] and k["tot"][1] == "", (k["treffer"], k["tot"]))
    k = _tot_lauf(lambda: _mutant(_anweisungen(
        "_ohne_antwort_gestorben",
        lambda s: (isinstance(s, ast.If)
                   and "chat_beendet_liste" in ast.unparse(s.test)))),
        beenden=True)
    pruefe("L61 KONTROLLE: ohne die Beenden-Pruefung meldet ein Ende durch "
           "den Nutzer einen Startfehler", k["treffer"] == [1]
           and "claude-foo" in k["tot"][1], (k["treffer"], k["tot"]))
    k = _tot_lauf(lambda: _mutant(_anweisungen(
        "_start_gescheitert_melden",
        lambda s: (isinstance(s, ast.If) and "erstmals" in ast.unparse(s.test)))))
    pruefe("L61 KONTROLLE: ohne Zurueckschreiben bleibt das Feld leer",
           k["treffer"] == [1] and k["tot"][2] == "", (k["treffer"], k["tot"]))

    # -- Befund mittel 2: die Knoepfe einer Freigabe-Karte ------------------
    m = _karten_lauf()
    for name in ("12 Zeilen, 1000 px", "12 Zeilen, 700 px",
                 "30 Zeilen, lange Beschreibung, Mindesthoehe",
                 "drei Karten, 700 px", "Wortlaut aufgeklappt, 700 px"):
        pruefe("L61 Karte %s: 'Erlauben' und 'Ablehnen' stehen ganz im "
               "Kartenbereich, das Dock rollt nicht" % name,
               m[name]["knoepfe"] and m[name]["dock"] == 0, m[name])
    pruefe("L61 bei Platz (1000 px) rollt der Kartenbereich nicht",
           m["12 Zeilen, 1000 px"]["rollweg"] == 0, m["12 Zeilen, 1000 px"])
    k = _karten_lauf(lambda: _mutant(_anweisungen(
        "_rollleiste_klaeren", lambda s: isinstance(s, ast.Expr)
        and "setVerticalScrollBarPolicy" in ast.unparse(s))))
    pruefe("L61 KONTROLLE: ohne das Klaeren bleibt die Rollleiste stehen "
           "(1000 px)", k["treffer"] == [2]
           and k["12 Zeilen, 1000 px"]["rollweg"] > 0,
           (k["treffer"], k["12 Zeilen, 1000 px"]))
    k = _karten_lauf(lambda: _mutant(_anweisungen(
        "_hoehe_nach_inhalt", _beginnt("rand ="), "rand = 0"),
        _anweisungen("_hoehe_nach_inhalt", _beginnt("breite ="),
                     "breite = teil.width() if teil.width() > 50 else 250"),
        _anweisungen("_hoehe_nach_inhalt", lambda s: isinstance(s, ast.If)
                     and ast.unparse(s.test) == "rolle"
                     and "_rollleiste_klaeren" in ast.unparse(s)),
        _anweisungen("_freigabe_karte", _beginnt("zeile = QLabel("),
                     "zeile = QLabel(' '.join(str(kurz).split())[:200])"),
        _verschieben("_freigabe_karte",
                     lambda s: ast.unparse(s) == "rl.addLayout(reihe)",
                     lambda s: ast.unparse(s) == "rl.addWidget(details)"),
        # Seit der Gegenpruefung Laien-Sicht K12 rollt `_freigabe_in_sicht`
        # die Knoepfe in den Blick — der Stand der Pruefung hatte das nicht.
        _anweisungen("_freigabe_in_sicht", _beginnt("w = z['w']"),
                     "return False")))
    pruefe("L61 KONTROLLE: der Stand der Pruefung (Breite mit Leiste, kein "
           "Klaeren, 200 Zeichen, Knoepfe zuletzt, kein In-den-Blick) -> "
           "Knoepfe abgeschnitten",
           k["treffer"] == [1, 1, 1, 1, 1, 1]
           and not k["12 Zeilen, 1000 px"]["knoepfe"]
           and not k["12 Zeilen, 700 px"]["knoepfe"],
           (k["treffer"], k["12 Zeilen, 1000 px"], k["12 Zeilen, 700 px"]))
    k = _karten_lauf(lambda: _mutant(_anweisungen(
        "_chat_zeichnen", _beginnt("mindest = VERLAUF_MIN_HOEHE_KARTE"),
        "mindest = VERLAUF_MIN_HOEHE")))
    # Seit dem Feinschliff 2026-09-28 (drei Kopfzeilen weniger) stehen die
    # Knoepfe auch mit 80 px Verlauf noch da; gemessen wird jetzt, was die
    # Regel bringt: der Kartenbereich bekommt die Hoehe, die der Verlauf
    # abgibt, und muss weniger rollen.
    lang = "30 Zeilen, lange Beschreibung, Mindesthoehe"
    pruefe("L61 KONTROLLE: der Verlauf behaelt 80 px -> bei langer "
           "Beschreibung (420 px) bekommen die Karten weniger Platz und "
           "rollen mehr", k["treffer"] == [1]
           and k[lang]["rolle"] < m[lang]["rolle"]
           and k[lang]["rollweg"] > m[lang]["rollweg"],
           (k["treffer"], k[lang], m[lang]))
    k = _karten_lauf(lambda: _mutant(_verschieben(
        "_freigabe_karte", lambda s: ast.unparse(s) == "rl.addLayout(reihe)",
        lambda s: ast.unparse(s) == "rl.addWidget(details)")))
    pruefe("L61 KONTROLLE: Knoepfe hinter dem Wortlaut -> aufgeklappt weg",
           k["treffer"] == [1]
           and not k["Wortlaut aufgeklappt, 700 px"]["knoepfe"],
           (k["treffer"], k["Wortlaut aufgeklappt, 700 px"]))
    # X14: "Wortlaut zeigen" laesst den Bereich mitwachsen.
    treffer, vorher, nachher = _aufklappen_lauf()
    pruefe("L61 'Wortlaut zeigen': der Kartenbereich waechst mit",
           nachher > vorher, (vorher, nachher))
    treffer, vorher, nachher = _aufklappen_lauf(lambda: _mutant(
        _ohne_aufruf("_freigabe_karte", "_freigabe_hoehe")))
    pruefe("L61 KONTROLLE (X14): ohne _freigabe_hoehe waechst er nicht",
           treffer == [1] and nachher <= vorher, (treffer, vorher, nachher))
    # X15: die laufende Antwort nur so hoch wie ihr Text.
    treffer, hoehe, braucht = _kurz_laufend_lauf()
    pruefe("L61 eine kurze laufende Antwort ist nur so hoch wie ihr Text "
           "(1000 px)", hoehe <= max(30, braucht + 4), (hoehe, braucht))
    treffer, hoehe, braucht = _kurz_laufend_lauf(lambda: _mutant(
        _anweisungen("_chat_zeichnen", lambda s: isinstance(s, ast.If)
                     and ast.unparse(s.test) == "laufend"
                     and "_hoehe_nach_inhalt" in ast.unparse(s))))
    pruefe("L61 KONTROLLE (X15): ohne Hoehe nach Inhalt steht Leere darunter",
           treffer == [1] and hoehe > max(30, braucht + 4),
           (treffer, hoehe, braucht))

    # Die Knoepfe der Karte (beim Umstellen angefasst): ueber `_sicher`.
    m = _knopf_wirft_lauf()
    pruefe("L61 wirft das Beantworten, laeuft nichts aus dem Slot (Erlauben, "
           "Ablehnen), der Fehler steht auf stderr",
           m["entkommen"] == [] and m["klicks"] == 2 and m["gemeldet"], m)
    k = _knopf_wirft_lauf(lambda: _mutant(
        _anweisungen("_freigabe_karte", _beginnt("ja.clicked.connect("),
                     "ja.clicked.connect(lambda: C.freigabe_beantworten("
                     "z['chat'], f['id'], True))")))
    pruefe("L61 KONTROLLE: 'Erlauben' ohne _sicher -> die Ausnahme laeuft "
           "aus dem Slot", k["treffer"] == [1]
           and k["entkommen"] == ["RuntimeError"], k)

    # -- Befund niedrig: "Neuer Chat" und die alte Stoerung -----------------
    treffer, vorher, nachher, spaeter = _stoerung_lauf()
    pruefe("L61 'Neuer Chat' nimmt die Stoerung des alten Chats mit, auch "
           "wenn sein Leser sie danach noch einmal setzt",
           vorher.startswith("Störung") and not nachher.startswith("Störung")
           and not spaeter.startswith("Störung"), (vorher, nachher, spaeter))
    ohne_wache = _test_ersetzen("_chat_zeichnen",
                                "chat.get('fehler') and (not verworfen) and "
                                "(offen is None)",
                                "chat.get('fehler') and (offen is None)")
    k = _stoerung_lauf(lambda: _mutant(ohne_wache))
    pruefe("L61 KONTROLLE: ohne die Wache bleibt 'Störung' ueber dem leeren "
           "Verlauf stehen", k[0] == [1] and k[2].startswith("Störung")
           and k[3].startswith("Störung"), k)

    # -- Kleinkram: X3, X10, X11, X13, X17, X18 -----------------------------
    m = _kleinkram_lauf()
    pruefe("L61 ein gestoppter Dienst ist keine Verbindung: kein Start, "
           "Text bleibt, 'Zuerst verbinden'", m["gestoppt"][:2] == (0, "Hallo")
           and m["gestoppt"][2].startswith("Zuerst verbinden"), m["gestoppt"])
    pruefe("L61 vor dem Chat: bisherige Chats nur bei Claude Code, kein "
           "Hinweis 'gilt ab dem nächsten Chat'", m["vor_dem_chat"] == {
               "claude": (True, False), "openai": (False, False),
               "codex": (False, False)}, m["vor_dem_chat"])
    pruefe("L61 eine lange Meldung an der Eingabe ist gekuerzt",
           0 < m["lang"] <= 300, m["lang"])
    pruefe("L61 scheitert das Senden, bleibt der Text und die Zeile sagt es",
           m["senden_wirft"][0] == "zweite"
           and "Probe-Senden" in m["senden_wirft"][1], m["senden_wirft"])
    pruefe("L61 ohne Ordner wartet die Nachfrage; 'Neuer Chat' fragt sofort "
           "neu", m["ordner"][:2] == (0, 0)
           and m["ordner"][2] == ["Dach Ost"], m["ordner"])
    kontrollen = [
        ("X3 ein gestoppter Dienst gilt als verbunden",
         _anweisungen("_chat_starten", lambda s: isinstance(s, ast.If)
                      and "stopped" in ast.unparse(s.test),
                      "if d is None or d.beenden:\n"
                      "    _chat_fehler_zeigen(z, CHAT_ZUERST_VERBINDEN, "
                      "'verbinden')\n    return False"),
         lambda k: k["gestoppt"][0] == 1),
        ("X10 bisherige Chats auch bei API-Anbietern",
         _anweisungen("_chat_zeichnen", _beginnt("_liste_takt("),
                      "_liste_takt(z, not an, not an and "
                      "(verworfen or not liste))"),
         lambda k: k["vor_dem_chat"]["openai"][0]),
        ("X11 Hinweis 'nächster Chat' immer im Popover",
         _anweisungen("_popover_fuellen",
                      _beginnt("w['stufe_notiz'].setVisible("),
                      "w['stufe_notiz'].setVisible(True)"),
         lambda k: k["vor_dem_chat"]["claude"][1]),
        ("X13 Meldung ohne Kuerzung",
         _anweisungen("_chat_fehler_zeigen", _beginnt("text = _kurz_text(")),
         lambda k: k["lang"] > 300),
        ("X17 'Neuer Chat' ohne Aufheben der Wartezeit",
         _anweisungen("_chat_neu", _beginnt("z.pop('ordner_gefragt'")),
         lambda k: k["ordner"][2] == []),
        ("X18 Feld wird auch geleert, wenn Senden wirft",
         _return_im_except("_chat_senden"),
         lambda k: k["senden_wirft"][0] == ""),
    ]
    for name, mutation, rot in kontrollen:
        k = _kleinkram_lauf(lambda: _mutant(mutation))
        pruefe("L61 KONTROLLE (%s): wird rot" % name,
               k["treffer"] == [1] and rot(k), k)

    # -- Befund niedrig: Texte fuer Laien -----------------------------------
    D = dashboard_laden()
    pruefe("L61 'Zuerst verbinden' und 'kein Arbeitsordner' ohne Technik",
           _laientext_ok(D.CHAT_ZUERST_VERBINDEN)
           and _laientext_ok(D.CHAT_KEIN_ORDNER),
           (D.CHAT_ZUERST_VERBINDEN, D.CHAT_KEIN_ORDNER))
    pruefe("L61 KONTROLLE: die alten Saetze fallen durch",
           not _laientext_ok("Zuerst verbinden — der Chat übernimmt "
                             "Steckplatz und Datei von der Verbindung.")
           and not _laientext_ok("Kein Projektordner. Entweder "
                                 "OPEN_MCP_CAD_PROJEKT setzen, oder den Pfad "
                                 "in projektordner.txt neben dem Plugin "
                                 "eintragen."))
    _frischer_start()
    D, z, _d = aufbauen()
    try:
        with _ChatStartAttrappe(D, z, projekt=None) as att:
            rest = _senden_klick(D, z, "Hallo")
            ohne = (len(att.gestartet), rest, _meldung(z))
    finally:
        _frischer_start()
    pruefe("L61 ohne Arbeitsordner: kein Start, Text bleibt, die Zeile sagt "
           "es ohne Technik", ohne[:2] == (0, "Hallo")
           and ohne[2] == D.CHAT_KEIN_ORDNER, ohne)


# --- L62-L64: Chatliste, Kontext, Ordnerwahl (Etappe D, 2026-09-26) ---------

def _heim_setzen():
    """Ein Temp-Heim (USERPROFILE) — die Sitzungsordner liegen darunter.
    -> (heim, alter Wert)."""
    heim = _tempfile.mkdtemp(prefix="omcad_live_heim_")
    alt = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = heim
    return heim, alt


def _heim_zurueck(alt):
    if alt is None:
        os.environ.pop("USERPROFILE", None)
    else:
        os.environ["USERPROFILE"] = alt


class _SitzungenZaehler:
    """Ersetzt `sitzungen` im Chat-Modul, das das Dock laedt: merkt je Aufruf
    den Thread und kann bremsen (`dauer`). Stellt alles zurueck (`with`)."""
    NAME = "omcad_a_chat_A"

    def __init__(self, D, dauer=0.0):
        self.D, self.dauer, self.threads = D, dauer, []

    def __enter__(self):
        self.modul = sys.modules.get(self.NAME) or self.D._chat_modul()
        self.echt = self.modul.sitzungen
        zaehler = self

        def sitzungen(*a, **k):
            zaehler.threads.append(threading.current_thread().name)
            if zaehler.dauer:
                time.sleep(zaehler.dauer)
            return zaehler.echt(*a, **k)
        self.modul.sitzungen = sitzungen
        return self

    def __exit__(self, *_):
        self.modul.sitzungen = self.echt


def _liste_lauf(laden=None):
    """L62: zwei Dock-Chats und eine Terminal-Sitzung im Arbeitsordner; die
    Liste, ihr Nebenthread, das Oeffnen, das Fortsetzen, das Ende, die
    Zeitangaben. -> dict."""
    from PyQt6.QtCore import Qt
    heim, alt_heim = _heim_setzen()
    m = {}
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        with _ChatStartAttrappe(D, z) as att:
            jetzt = time.time()
            _dock_sitzung(att.projekt, "d0c00001-wand", frage="Wand Nord",
                          antwort="Die Wand steht.", mtime=jetzt - 600)
            _dock_sitzung(att.projekt, "d0c00002-dach", frage="Dach Ost",
                          antwort="Das Dach steht.", mtime=jetzt - 60)
            C = D._chat_modul()
            terminal = os.path.join(C.projekt_ordner(att.projekt),
                                    "7e700003-terminal.jsonl")
            with open(terminal, "w", encoding="utf-8") as fh:
                fh.write('{"type":"custom-title","customTitle":"Terminal"}\n')
            # (1) Die Liste — geholt im Nebenthread, der Takt wartet nie.
            with _SitzungenZaehler(D, dauer=1.0) as sz:
                D._liste_auffrischen(z)
                z.pop("ordner_gefragt", None)
                t0 = time.monotonic()
                D._chat_zeichnen(z)
                m["takt_s"] = round(time.monotonic() - t0, 3)
                _warte_qt(D, z, lambda: w["chat_liste"].count() > 0,
                          frist=4.0)
                m["threads"] = list(sz.threads)
            m["liste"] = _liste_titel(z)
            m["sichtbar"] = (not w["chat_liste"].isHidden(),
                             not w["chat_liste_titel"].isHidden(),
                             w["chat_verlauf"].isHidden())
            m["quer"] = w["chat_liste"].horizontalScrollBar().maximum()
            texte = [w["chat_liste"].item(i).text()
                     for i in range(w["chat_liste"].count())]
            m["zeit_vorher"] = texte
            # (2) Die Zeitangaben gehen mit der Uhr, ohne neue Abfrage — und
            # ohne dass die Liste neu gebaut wird (die Auswahl bleibt).
            w["chat_liste"].setCurrentRow(1)
            echt_zeit = D.time

            class _Uhr:
                @staticmethod
                def time():
                    return echt_zeit.time() + 7200

                monotonic = staticmethod(echt_zeit.monotonic)
                sleep = staticmethod(echt_zeit.sleep)
            with _SitzungenZaehler(D) as sz:
                D.time = _Uhr
                try:
                    D._chat_zeichnen(z)
                finally:
                    D.time = echt_zeit
                m["zeit_nachher"] = ([w["chat_liste"].item(i).text()
                                      for i in range(w["chat_liste"].count())],
                                     len(sz.threads))
                m["auswahl"] = w["chat_liste"].currentRow()
            # (3) Oeffnen: der alte Verlauf, gelesen im Nebenthread.
            item = next((w["chat_liste"].item(i)
                         for i in range(w["chat_liste"].count())
                         if w["chat_liste"].item(i).data(
                             Qt.ItemDataRole.UserRole) == "d0c00001-wand"),
                        None)
            D._chat_fehler_zeigen(z, "Probe-Meldung")
            if item is not None:
                w["chat_liste"].itemClicked.emit(item)
            _warte_qt(D, z, lambda: w["chat_verlauf"].count() >= 2, frist=3.0)
            m["offen"] = (_verlauf_texte(z), w["chat_lage"].text(),
                          not w["chat_liste"].isHidden(),
                          w["chat_verlauf"].isHidden(), _meldung(z))
            # (4) Die naechste Nachricht setzt DIESEN Chat fort.
            rest = _senden_klick(D, z, "weiter bitte")
            D._chat_zeichnen(z)
            start = att.gestartet[-1] if att.gestartet else {}
            m["fort"] = (len(att.gestartet), rest, start.get("sitzung"),
                         start.get("abzweigen"), start.get("name"),
                         [e.get("art") for e in start.get("vorher") or ()],
                         _verlauf_texte(z), z.get("sitzung_offen"))
            # Waehrend der Chat laeuft, oeffnet ein Klick in die (verborgene)
            # Liste nichts (Schutz in der Tiefe, Nacharbeit D, Mutant D9).
            item = w["chat_liste"].item(0)
            if item is not None:
                w["chat_liste"].itemClicked.emit(item)
            m["oeffnen_waehrend"] = z.get("sitzung_offen")
            z["sitzung_offen"] = None
            # (5) Waehrenddessen entsteht ein neuer Chat; mit dem Ende steht
            # er in der Liste (die neue Datei des CLI).
            _dock_sitzung(att.projekt, "d0c00004-neu", frage="Fenster West",
                          mtime=time.time())
            m["waehrend"] = (not w["chat_liste"].isHidden(), _liste_titel(z))
            # Das CLI stirbt dabei, ohne zu antworten (etwa: die Sitzung
            # gibt es nicht mehr). Der alte Verlauf ("alt") zaehlt dabei
            # nicht als Antwort: der Grund muss an der Eingabe stehen.
            z["chat"].update(an=False, laeuft_zug=False, stderr=[
                "Error: No conversation found with session ID"])
            z["chat"]["stand"] = z["chat"].get("stand", 0) + 1
            _warte_qt(D, z, lambda: "Fenster West" in _liste_titel(z),
                      frist=3.0)
            m["nach_ende"] = _liste_titel(z)
            m["tot"] = (_meldung(z), w["chat_eingabe"].toPlainText())
            # (6) "Neuer Chat": der Verlauf weicht, die Liste kommt wieder.
            w["chat_neu"].click()
            _warte_qt(D, z, lambda: not w["chat_liste"].isHidden(), frist=3.0)
            m["neu"] = (not w["chat_liste"].isHidden(),
                        w["chat_verlauf"].isHidden(), z.get("sitzung_offen"))
            # (7) Ein Anbieterwechsel schliesst einen geoeffneten Chat.
            item = w["chat_liste"].item(0)
            if item is not None:
                w["chat_liste"].itemClicked.emit(item)
            _anbieter_waehlen(z, "openai")
            _anbieter_waehlen(z, "claude")
            D._chat_zeichnen(z)
            m["wechsel"] = (z.get("sitzung_offen"),
                            not w["chat_liste"].isHidden())
            # Ein geoeffneter Chat aus einem ANDEREN Ordner startet nicht.
            item = w["chat_liste"].item(0)
            if item is not None:
                w["chat_liste"].itemClicked.emit(item)
            anderer = _tempfile.mkdtemp(prefix="omcad_live_projekt_")
            os.environ["OPEN_MCP_CAD_PROJEKT"] = anderer
            vorher = len(att.gestartet)
            rest = _senden_klick(D, z, "falscher Ordner")
            m["anderer"] = (len(att.gestartet) - vorher, rest, _meldung(z))
        # (8) Ein sehr langer Titel rollt nicht quer (300 px).
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        w = z["w"]
        with _ChatStartAttrappe(D, z) as att:
            _dock_sitzung(att.projekt, "d0c00005-lang",
                          frage="Wand " + "Seeblick Erdgeschoss " * 12)
            D._liste_auffrischen(z)
            z.pop("ordner_gefragt", None)
            _warte_qt(D, z, lambda: w["chat_liste"].count() > 0, frist=3.0)
            m["breit"] = _breite_messen(D, z)
            m["breit_liste"] = (w["chat_liste"].horizontalScrollBar()
                                .maximum(), not w["chat_liste"].isHidden())
    finally:
        _heim_zurueck(alt_heim)
        _frischer_start()
    return m


def zelle_chatliste():
    """L62 (S9, Etappe D): die bisherigen Chats des Arbeitsordners — nur die
    des Docks, im Nebenthread geholt, anklicken oeffnet, die naechste
    Nachricht setzt DENSELBEN Chat fort (--resume, ohne Abzweigen)."""
    m = _liste_lauf()
    pruefe("L62 die Liste zeigt nur Chats des Docks, neueste zuerst",
           m["liste"] == ["Dach Ost", "Wand Nord"], m["liste"])
    pruefe("L62 sie steht an der Stelle des leeren Verlaufs, mit Titel",
           m["sichtbar"] == (True, True, True), m["sichtbar"])
    pruefe("L62 gelesen im Nebenthread; ein Takt wartet nicht auf eine "
           "langsame Abfrage (1 s)", m["threads"]
           and "MainThread" not in m["threads"] and m["takt_s"] < 0.3,
           (m["threads"], m["takt_s"]))
    pruefe("L62 die Zeitangaben gehen mit der Uhr, ohne neue Abfrage",
           m["zeit_vorher"] != m["zeit_nachher"][0]
           and all("vor 2 h" in t for t in m["zeit_nachher"][0])
           and m["zeit_nachher"][1] == 0, (m["zeit_vorher"],
                                           m["zeit_nachher"]))
    pruefe("L62 ... an Ort und Stelle: die Auswahl bleibt stehen (die Liste "
           "wird dafuer nicht neu gebaut)", m["auswahl"] == 1, m["auswahl"])
    pruefe("L62 waehrend eines Chats oeffnet ein Klick in die Liste nichts",
           m["oeffnen_waehrend"] is None, m["oeffnen_waehrend"])
    pruefe("L62 Anklicken oeffnet: der alte Verlauf steht da, die Lage sagt "
           "es, die Liste weicht",
           m["offen"][0][:2] == ["Du:  Wand Nord", "Die Wand steht."]
           and "setzt diesen Chat fort" in m["offen"][1]
           and not m["offen"][2] and not m["offen"][3]
           and m["offen"][4] == "", m["offen"])
    pruefe("L62 die naechste Nachricht setzt DENSELBEN Chat fort: --resume "
           "mit seiner Kennung, ohne Abzweigen, mit dem alten Verlauf",
           m["fort"][:5] == (1, "", "d0c00001-wand", False,
                             dashboard_laden()._chat_modul().SITZUNG_NAME)
           and m["fort"][5] == ["ich", "text"]
           and m["fort"][6][:2] == ["Du:  Wand Nord", "Die Wand steht."]
           and m["fort"][7] is None, m["fort"])
    pruefe("L62 waehrend des Chats keine Liste; nach seinem Ende steht der "
           "neue Chat darin", m["waehrend"][0] is False
           and m["nach_ende"][:1] == ["Fenster West"],
           (m["waehrend"], m["nach_ende"]))
    pruefe("L62 stirbt der fortgesetzte Chat ohne Antwort, steht der Grund "
           "an der Eingabe (der alte Verlauf zaehlt nicht als Antwort)",
           "No conversation found" in m["tot"][0]
           and m["tot"][1] == "weiter bitte", m["tot"])
    pruefe("L62 'Neuer Chat': Liste statt Verlauf, kein Chat geoeffnet",
           m["neu"] == (True, True, None), m["neu"])
    pruefe("L62 ein Anbieterwechsel schliesst den geoeffneten Chat, die "
           "Liste steht wieder da", m["wechsel"] == (None, True), m["wechsel"])
    pruefe("L62 ein geoeffneter Chat eines anderen Arbeitsordners startet "
           "nicht, der Text bleibt, die Zeile sagt es",
           m["anderer"][:2] == (0, "falscher Ordner")
           and "anderen Arbeitsordner" in m["anderer"][2], m["anderer"])
    pruefe("L62 ein langer Titel: kein Querrollen, nichts gequetscht (300 px)",
           m["breit"]["hmax"] == 0 and not m["breit"]["gequetscht"]
           and m["breit_liste"] == (0, True), (m["breit"], m["breit_liste"]))
    v = _veraltet_lauf()
    pruefe("L62 eine Abfrage, die beim Ordnerwechsel noch lief, zeigt nie "
           "den alten Ordner", ("Seeblick Eins",) not in v["gesehen"]
           and ("Seeblick Zwei",) in v["gesehen"], v)
    pruefe("L62 verschwindet der Ordner, leert sich die Liste",
           v["weg"] == [], v)
    for was, mut, rot in (
            ("ein altes Ergebnis gilt",
             _anweisungen("_liste_takt", lambda s: isinstance(s, ast.If)
                          and "liste_anlass" in ast.unparse(s.test)
                          and "neu is not None" in ast.unparse(s.test),
                          "if neu is not None:\n"
                          "    (z['liste_stand'], z['liste_ordner'], "
                          "z['liste']) = neu\n"
                          "    z['liste_gezeigt'] = None"),
             lambda k: ("Seeblick Eins",) in k["gesehen"]),
            ("ohne Ordner bleibt die alte Liste",
             _anweisungen("_liste_takt", _beginnt(
                 "z['liste'], z['liste_gezeigt'] = ([], None)")),
             lambda k: k["weg"] == ["Seeblick Zwei"])):
        M = _mutant(mut)
        k = _veraltet_lauf(lambda: M)
        pruefe("L62 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k), (M._mutant_treffer, k))
    for was, mut, rot in (
            ("die Liste im Qt-Takt geholt (wie vor Etappe D)",
             _anweisungen("_liste_takt", _beginnt("_liste_holen(z, ordner)"),
                          "z['liste_neu'] = (z.get('liste_anlass'), ordner, "
                          "_chat_modul().sitzungen(ordner, z['chat_cache'], "
                          "nur_dock=True))"),
             lambda k: "MainThread" in k["threads"] and k["takt_s"] >= 0.9),
            ("Fortsetzen als Abzweigung (wie vor Etappe D)",
             _anweisungen("_chat_starten", lambda s: "C.starten(" in
                          ast.unparse(s) and isinstance(s, ast.Try),
                          "try:\n    C.starten(chat, ordner, port=st.get("
                          "'port'), dokument=st.get('dokument'), sitzung="
                          "offen['id'] if offen else None, abzweigen=True, "
                          "name=C.SITZUNG_NAME, vorher=(offen.get("
                          "'ereignisse') or None) if offen else None, "
                          "modell=_modellwahl(z['w']['chat_modell']), "
                          "effort=z['w']['chat_stufe'].currentData())\n"
                          "except Exception as fehler:\n"
                          "    _chat_fehler_zeigen(z, 'Chat startet nicht: "
                          "%s' % fehler)\n    return False"),
             lambda k: k["fort"][3] is True),
            ("der geoeffnete Chat wird nicht fortgesetzt",
             _anweisungen("_chat_starten",
                          _beginnt("offen = z.get('sitzung_offen')"),
                          "offen = None"),
             lambda k: k["fort"][2] is None),
            ("kein Neuholen am Ende des Chats",
             _anweisungen("_chat_zeichnen", lambda s: (
                 isinstance(s, ast.If)
                 and "chat_war_an" in ast.unparse(s.test))),
             lambda k: "Fenster West" not in k["nach_ende"]),
            ("die Zeitangaben nur beim Holen gerechnet",
             _anweisungen("_liste_takt", lambda s: isinstance(s, ast.For)
                          and "setText" in ast.unparse(s)),
             lambda k: k["zeit_vorher"] == k["zeit_nachher"][0]),
            ("jede Minute neu gebaut (wie vor der Nacharbeit D)",
             _anweisungen("_liste_takt", _beginnt("marke = ("),
                          "marke = (id(z.get('liste')), len(eintraege), "
                          "int(time.time() // 60))"),
             lambda k: k["auswahl"] != 1),
            ("Oeffnen auch waehrend eines Chats",
             _anweisungen("_sitzung_oeffnen", lambda s: isinstance(s, ast.If)
                          and "chat.get('an')" in ast.unparse(s.test)),
             lambda k: k["oeffnen_waehrend"] is not None),
            ("der alte Verlauf zaehlt als Antwort",
             _anweisungen("_ohne_antwort_gestorben", lambda s: isinstance(
                 s, ast.Return) and "alt" in ast.unparse(s),
                          "return all((e.get('art') == 'ich' for e in "
                          "liste or ()))"),
             lambda k: "No conversation found" not in k["tot"][0]),
            ("Oeffnen laesst eine alte Meldung stehen",
             _ohne_aufruf("_sitzung_oeffnen", "_chat_fehler_quittieren"),
             lambda k: k["offen"][4] == "Probe-Meldung"),
            ("ein Anbieterwechsel laesst den geoeffneten Chat stehen",
             _anweisungen("_anbieter_gewechselt", lambda s: isinstance(
                 s, ast.If) and "sitzung_offen" in ast.unparse(s)),
             lambda k: k["wechsel"][0] is not None),
            ("ohne die Pruefung des Ordners",
             _anweisungen("_chat_starten", lambda s: (
                 isinstance(s, ast.If)
                 and "offen.get('ordner')" in ast.unparse(s.test))),
             lambda k: k["anderer"][0] == 1)):
        M = _mutant(mut)
        k = _liste_lauf(lambda: M)
        pruefe("L62 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k),
               (M._mutant_treffer, {x: k.get(x) for x in (
                   "threads", "takt_s", "fort", "nach_ende", "anderer",
                   "tot", "offen", "wechsel", "auswahl",
                   "oeffnen_waehrend")}))


class _VerlaufBremse:
    """Bremst `sitzung_verlauf` im Chat-Modul, das das Dock laedt (`with`)."""

    def __init__(self, D, dauer):
        self.D, self.dauer = D, dauer

    def __enter__(self):
        self.modul = self.D._chat_modul()
        self.echt = self.modul.sitzung_verlauf
        echt, dauer = self.echt, self.dauer

        def sitzung_verlauf(*a, **k):
            time.sleep(dauer)
            return echt(*a, **k)
        self.modul.sitzung_verlauf = sitzung_verlauf
        return self

    def __exit__(self, *_):
        self.modul.sitzung_verlauf = self.echt


def _item_mit(z, kennung):
    from PyQt6.QtCore import Qt
    lst = z["w"]["chat_liste"]
    return next((lst.item(i) for i in range(lst.count())
                 if lst.item(i).data(Qt.ItemDataRole.UserRole) == kennung),
                None)


def _belegt_lauf(laden=None):
    """L65 (Nacharbeit D): ein Chat, den gerade das Dock eines ANDEREN
    Cadwork fuehrt (Vermerk mit einem lebenden Python-Kind), und die erste
    Nachricht, waehrend der alte Verlauf noch laedt. -> dict."""
    heim, alt_heim = _heim_setzen()
    m = {}
    kind = None
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        with _ChatStartAttrappe(D, z) as att:
            jetzt = time.time()
            _dock_sitzung(att.projekt, "d0c00001-wand", frage="Wand Nord",
                          antwort="Die Wand steht.", mtime=jetzt - 600)
            _dock_sitzung(att.projekt, "d0c00002-dach", frage="Dach Ost",
                          antwort="Das Dach steht.", mtime=jetzt - 60)
            kind = subprocess.Popen([sys.executable, "-c",
                                     "import time; time.sleep(60)"])
            ordner = os.environ["OPEN_MCP_CAD_BELEGT"]
            os.makedirs(ordner, exist_ok=True)
            with open(os.path.join(ordner, "d0c00002-dach.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"sitzung": "d0c00002-dach", "pid": kind.pid,
                           "seit": time.time(), "besitzer": os.getpid() + 1},
                          fh)
            D._liste_auffrischen(z)
            z.pop("ordner_gefragt", None)
            _warte_qt(D, z, lambda: w["chat_liste"].count() == 2, frist=4.0)
            m["liste"] = [w["chat_liste"].item(i).text()
                          for i in range(w["chat_liste"].count())]
            # (1) Der belegte Chat: oeffnen zeigt es, senden startet nichts.
            item = _item_mit(z, "d0c00002-dach")
            if item is not None:
                w["chat_liste"].itemClicked.emit(item)
            _warte_qt(D, z, lambda: (z.get("sitzung_offen") or {}).get(
                "ereignisse") is not None, frist=3.0)
            D._chat_zeichnen(z)
            m["lage"] = w["chat_lage"].text()
            rest = _senden_klick(D, z, "weiter bitte")
            m["senden"] = (len(att.gestartet), rest, _meldung(z))
            # (2) Der freie Chat, die erste Nachricht kommt, bevor sein alter
            # Verlauf gelesen ist (0,8 s gebremst).
            w["chat_neu"].click()
            _warte_qt(D, z, lambda: not w["chat_liste"].isHidden(), frist=3.0)
            with _VerlaufBremse(D, 0.8):
                item = _item_mit(z, "d0c00001-wand")
                if item is not None:
                    w["chat_liste"].itemClicked.emit(item)
                rest = _senden_klick(D, z, "gleich weiter")
                m["laedt"] = (len(att.gestartet), rest, _meldung(z))
                _warte_qt(D, z, lambda: (z.get("sitzung_offen") or {}).get(
                    "ereignisse") is not None, frist=3.0)
            rest = _senden_klick(D, z, "gleich weiter")
            D._chat_zeichnen(z)
            start = att.gestartet[-1] if att.gestartet else {}
            m["danach"] = (len(att.gestartet), rest, start.get("sitzung"),
                           [e.get("art") for e in start.get("vorher") or ()],
                           _verlauf_texte(z)[:2])
    finally:
        if kind is not None:
            kind.kill()
            kind.wait()
        _heim_zurueck(alt_heim)
        _frischer_start()
    return m


def zelle_chatliste_nacharbeit():
    """L65 (Nacharbeit D): laeuft ein Chat gerade im Dock eines anderen
    Cadwork, sagt die Liste es und die naechste Nachricht setzt ihn NICHT
    fort; kommt die erste Nachricht, bevor der alte Verlauf gelesen ist,
    wartet sie (sonst erschiene der alte Verlauf nie)."""
    m = _belegt_lauf()
    D = dashboard_laden()
    pruefe("L65 die Liste sagt, welcher Chat gerade in einem anderen Cadwork "
           "laeuft (nur dieser)",
           len(m["liste"]) == 2 and D.LISTE_BELEGT in m["liste"][0]
           and D.LISTE_BELEGT not in m["liste"][1], m["liste"])
    pruefe("L65 geoeffnet sagt es auch die Lage", D.LISTE_BELEGT in m["lage"],
           m["lage"])
    pruefe("L65 die naechste Nachricht startet ihn nicht: der Text bleibt, "
           "die Zeile sagt es ohne Technik",
           m["senden"][:2] == (0, "weiter bitte")
           and "anderen Cadwork" in m["senden"][2]
           and _laientext_ok(m["senden"][2]), m["senden"])
    pruefe("L65 die erste Nachricht, waehrend der alte Verlauf laedt: kein "
           "Start, der Text bleibt, die Zeile sagt es",
           m["laedt"][:2] == (0, "gleich weiter")
           and m["laedt"][2] == D.CHAT_LAEDT_NOCH, m["laedt"])
    pruefe("L65 ... danach setzt sie fort, MIT dem alten Verlauf",
           m["danach"][:3] == (1, "", "d0c00001-wand")
           and m["danach"][3] == ["ich", "text"]
           and m["danach"][4] == ["Du:  Wand Nord", "Die Wand steht."],
           m["danach"])
    for was, mut, rot in (
            ("die Liste sagt 'belegt' nicht",
             _anweisungen("_liste_eintrag_text", lambda s: isinstance(
                 s, ast.If) and "belegt" in ast.unparse(s.test)),
             lambda k: not any(D.LISTE_BELEGT in x for x in k["liste"])),
            ("die Lage sagt 'belegt' nicht",
             _anweisungen("_chat_zeichnen", lambda s: isinstance(s, ast.Expr)
                          and "LISTE_BELEGT" in ast.unparse(s),
                          "w['chat_lage'].setText('«%s» · %s' % (_kurz_text("
                          "offen.get('titel'), 60), 'lädt den Verlauf …' if "
                          "offen.get('ereignisse') is None else 'die nächste "
                          "Nachricht setzt diesen Chat fort'))"),
             lambda k: D.LISTE_BELEGT not in k["lage"]),
            ("das Dock prueft 'belegt' nicht",
             _anweisungen("_chat_starten", lambda s: isinstance(s, ast.If)
                          and "sitzung_belegt" in ast.unparse(s.test)),
             lambda k: k["senden"][0] == 1),
            ("senden, waehrend der alte Verlauf laedt",
             _anweisungen("_chat_starten", lambda s: isinstance(s, ast.If)
                          and "ereignisse') is None" in ast.unparse(s.test)),
             lambda k: k["laedt"][0] == 1)):
        M = _mutant(mut)
        k = _belegt_lauf(lambda: M)
        pruefe("L65 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k), (M._mutant_treffer, k))


def _veraltet_lauf(laden=None):
    """L62: eine Abfrage, die bei einem Ordnerwechsel noch laeuft, gilt
    nicht; verschwindet der Ordner, leert sich die Liste. -> dict."""
    heim, alt_heim = _heim_setzen()
    _einst_setzen(None)
    m = {}
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        with _ChatStartAttrappe(D, z, projekt=None):
            eins = _tempfile.mkdtemp(prefix="omcad_live_eins_")
            zwei = _tempfile.mkdtemp(prefix="omcad_live_zwei_")
            _dock_sitzung(eins, "d0c0000a-eins", frage="Seeblick Eins")
            _dock_sitzung(zwei, "d0c0000b-zwei", frage="Seeblick Zwei")
            gesehen = set()
            with _SitzungenZaehler(D, dauer=0.6):
                D._ordner_merken(z, eins)
                D._chat_zeichnen(z)           # holt fuer "eins" (0,6 s)
                D._ordner_merken(z, zwei)     # ... und schon ist es "zwei"
                ende = time.monotonic() + 4.0
                while time.monotonic() < ende:
                    _APP.processEvents()
                    D._chat_zeichnen(z)
                    gesehen.add(tuple(_liste_titel(z)))
                    if _liste_titel(z) == ["Seeblick Zwei"]:
                        break
                    time.sleep(0.03)
            m["gesehen"] = sorted(gesehen)
            # Der Ordner verschwindet (ohne neue Wahl); am Ende des naechsten
            # Chats wird nachgesehen.
            os.rmdir(zwei)
            z["chat"]["an"] = True
            D._chat_zeichnen(z)
            z["chat"]["an"] = False
            _warte_qt(D, z, lambda: w["chat_liste"].count() == 0, frist=1.0)
            m["weg"] = _liste_titel(z)
    finally:
        _einst_setzen(None)
        _heim_zurueck(alt_heim)
        _frischer_start()
    return m


def _kontext_lauf(laden=None):
    """L63: die Kontextanzeige bei laufendem Chat — aus den am echten CLI
    gemessenen Ereignissen (durch den echten Leser `_einordnen`), bei der
    Schleife ohne Fenster, ohne Zahl, nach dem Ende, bei 300 px. -> dict."""
    m = {}
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        lbl = w["chat_kontext"]

        def zeigen():
            z["chat"]["stand"] = z["chat"].get("stand", 0) + 1
            D._chat_zeichnen(z)
            return (lbl.text() if not lbl.isHidden() else "", lbl.toolTip())
        with _ChatStartAttrappe(D, z):
            _senden_klick(D, z, "hallo")
            chat = z["chat"]
            m["vorher"] = zeigen()
            C = D._chat_modul()
            # Gemessen 2026-09-26 (CLI 2.1.263, Haiku, erster Lauf).
            chat["modell"] = "claude-haiku-4-5-20251001"
            C._einordnen(chat, {"type": "assistant", "message": {
                "content": [{"type": "text", "text": "OK"}],
                "usage": {"input_tokens": 10,
                          "cache_creation_input_tokens": 130158,
                          "cache_read_input_tokens": 0,
                          "output_tokens": 4}}})
            C._einordnen(chat, {"type": "result", "result": "OK",
                                "modelUsage": {"claude-haiku-4-5-20251001": {
                                    "contextWindow": 200000}}})
            m["cli"] = zeigen()
            m["breit"] = _breite_messen(D, z)
            m["breit_lbl"] = (lbl.width(), lbl.sizeHint().width(),
                              not lbl.isHidden())
            chat["kontext"] = {"belegt": 1234, "fenster": None}
            m["schleife"] = zeigen()
            chat["kontext"] = {"belegt": "viel", "fenster": 5}
            m["kaputt"] = zeigen()
            chat["kontext"] = {"belegt": 250000, "fenster": 200000}
            m["ueber"] = zeigen()
            chat["kontext"] = {"belegt": 130168, "fenster": 200000}
            zeigen()
            chat["an"] = False
            m["ende"] = zeigen()
    finally:
        _frischer_start()
    return m


def zelle_kontextanzeige():
    """L63 (S10, Etappe D): «xx % voll» in der Leiste unter der Eingabe —
    nur bei laufendem Chat und nur mit einer Zahl."""
    m = _kontext_lauf()
    pruefe("L63 vor der ersten Antwort: keine Anzeige", m["vorher"][0] == "",
           m["vorher"])
    pruefe("L63 Claude Code mit den gemessenen Zahlen: '65 % voll', der "
           "Tooltip nennt beide Zahlen",
           m["cli"][0] == "65 % voll" and "130 168" in m["cli"][1]
           and "200 000" in m["cli"][1], m["cli"])
    pruefe("L63 ohne Fenster (Schleife): keine Anzeige (kein Fuellstand, "
           "Gegenpruefung Laien-Sicht K12), der Tooltip sagt warum",
           m["schleife"][0] == ""
           and "meldet dieser Anbieter nicht" in m["schleife"][1],
           m["schleife"])
    pruefe("L63 keine brauchbare Zahl: nichts", m["kaputt"][0] == "",
           m["kaputt"])
    pruefe("L63 mehr als das Fenster: hoechstens '100 % voll'",
           m["ueber"][0] == "100 % voll", m["ueber"])
    pruefe("L63 nach dem Ende des Chats: nichts", m["ende"][0] == "",
           m["ende"])
    pruefe("L63 300 px mit Anzeige: kein Querrollen, nichts gequetscht, die "
           "Anzeige ganz zu sehen", m["breit"]["hmax"] == 0
           and not m["breit"]["gequetscht"] and m["breit_lbl"][2]
           and m["breit_lbl"][0] >= m["breit_lbl"][1],
           (m["breit"], m["breit_lbl"]))
    for was, mut, rot in (
            ("die Anzeige nie gezeichnet",
             _ohne_aufruf("_chat_zeichnen", "_kontext_zeigen"),
             lambda k: k["cli"][0] == ""),
            ("auch nach dem Ende",
             _anweisungen("_kontext_zeigen", _beginnt("text, tipp ="),
                          "text, tipp = _kontext_text(chat.get('kontext'))"),
             lambda k: k["ende"][0] != "")):
        M = _mutant(mut)
        k = _kontext_lauf(lambda: M)
        pruefe("L63 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k), (M._mutant_treffer, k))


class _DialogAttrappe:
    """Statt des echten QFileDialog: zaehlt open()/exec(), liefert per
    `waehlen` einen Ordner ueber das echte Signal `fileSelected`."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Q(QObject):
            fileSelected = pyqtSignal(str)
        self.q = _Q()
        self.fileSelected = self.q.fileSelected
        self.geoeffnet, self.exec_gerufen = 0, 0

    def open(self):
        self.geoeffnet += 1
        self.offen = True

    def exec(self):
        self.exec_gerufen += 1
        return 0

    def isVisible(self):
        return getattr(self, "offen", False)

    def raise_(self):
        pass

    def waehlen(self, pfad):
        self.offen = False
        self.fileSelected.emit(pfad)


def _ordnerwahl_lauf(laden=None):
    """L64: der echte Dialog (Optionen, kehrt sofort zurueck), dann die
    Wahl ueber eine Attrappe: chat.json, Anzeige, Liste, Start, Vergessen.
    -> dict."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QFileDialog
    heim, alt_heim = _heim_setzen()
    _einst_setzen(None)
    m = {}
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        # (1) Der echte Dialog: Qts eigener, nur Ordner, an einem OFFENEN
        # Fenster des Docks — seit K11 ist das Steuerfenster meist zu, ein
        # Dialog daran ging in der Ecke des Bildschirms auf (Gegenpruefung
        # K11). Seit K12 gibt es nur EIN Fenster, hier als Pille.
        dlg = D._ordner_dialog(z)
        eltern = dlg.parent()
        m["optionen"] = (
            dlg.testOption(QFileDialog.Option.DontUseNativeDialog),
            dlg.testOption(QFileDialog.Option.ShowDirsOnly),
            dlg.fileMode() == QFileDialog.FileMode.Directory,
            eltern is not None and eltern.isVisible()
            and eltern is z["fenster"])
        dlg.deleteLater()
        # (2) Der Knopf mit dem ECHTEN Dialog: kehrt sofort zurueck. Ein
        # Schutz schliesst jedes modale Fenster nach 1,5 s (sonst hielte
        # die Kontrolle mit exec() das Gate an).
        def schutz():
            offen = QApplication.activeModalWidget()
            if offen is not None:
                offen.reject()
        QTimer.singleShot(1500, schutz)
        t0 = time.monotonic()
        w["chat_ordner_waehlen"].click()
        m["knopf_s"] = round(time.monotonic() - t0, 3)
        echt = z.get("ordner_dialog")
        try:
            m["echt_sichtbar"] = bool(echt is not None and echt.isVisible())
        except RuntimeError:          # geschlossen und schon geloescht
            m["echt_sichtbar"] = False
        if m["echt_sichtbar"]:
            echt.reject()
        _APP.processEvents()
        # (3) Die Wahl ueber die Attrappe.
        att = _DialogAttrappe()
        D._ordner_dialog = lambda _z: att
        with _ChatStartAttrappe(D, z, projekt=None) as start:
            # Ohne Ordner: kein Start, die Zeile nennt die Wahl.
            _senden_klick(D, z, "Hallo")
            m["ohne"] = (len(start.gestartet), _meldung(z),
                         w["chat_ordner_text"].text())
            # Ein langer Pfad ohne Leerzeichen (umbrechen, L64).
            ordner = os.path.join(
                _tempfile.mkdtemp(prefix="omcad_live_wahl_"),
                "Seeblick_Wand_Erdgeschoss_Achse_Nord_Ost_Sued_West_Projekt")
            os.makedirs(ordner)
            _dock_sitzung(ordner, "d0c00001-gewaehlt", frage="Seeblick Wand")
            w["chat_ordner_waehlen"].click()
            w["chat_ordner_waehlen"].click()   # ein zweiter Klick: derselbe
            att.waehlen(ordner)
            _warte_qt(D, z, lambda: w["chat_liste"].count() > 0, frist=3.0)
            m["gewaehlt"] = (att.geoeffnet, att.exec_gerufen,
                             (_einst_lesen() or {}).get("arbeitsordner"),
                             w["chat_ordner_text"].text().replace(
                                 chr(0x200B), ""),
                             not w["chat_ordner_weg"].isHidden(),
                             _liste_titel(z), _meldung(z))
            # Was sich aus der Anzeige kopieren laesst (alles markiert), und
            # der Tooltip: beides ohne U+200B (Nacharbeit D).
            lbl = w["chat_ordner_text"]
            lbl.setSelection(0, len(lbl.text()))
            m["kopie"] = (lbl.selectedText(), lbl.toolTip(),
                          chr(0x200B) in lbl.text())
            # Die Seite bei 300 px: der lange Pfad bricht um, nichts rollt quer.
            _chat_ziehen(D, z, 300, 700)
            D._chat_einstellungen_zeigen(z, True)
            for _ in range(3):
                D._auffrischen(z)
                _APP.processEvents()
            # Gemessen wird die SEITE (im Rollbereich der Chat-Einstellungen):
            # ihre Mindestbreite gegen die Breite, die sie hat.
            # Seit K3 steht der Pfad im Ordner-Menue: seine Mindestbreite
            # gegen die Hoechstbreite dort (sonst abgeschnitten).
            lbl_o = w["chat_ordner_text"]
            m["einst_quer"] = max(0, lbl_o.minimumSizeHint().width()
                                  - lbl_o.maximumWidth())
            D._chat_einstellungen_zeigen(z, False)
            rest = _senden_klick(D, z, "Hallo")
            m["start"] = (len(start.gestartet), rest, start.ordner[-1:])
            z["chat"]["an"] = False
            # Ein Ordner, den es nicht gibt: nichts gemerkt.
            att.waehlen(ordner + "_gibt_es_nicht")
            m["falsch"] = ((_einst_lesen() or {}).get("arbeitsordner"),
                           w["chat_ordner_text"].text())
            # Eine Vorgabe der Einrichtung (Umgebung) geht der Wahl vor:
            # die Seite zeigt den Ordner, der gilt, und sagt es.
            vorgabe = _tempfile.mkdtemp(prefix="omcad_live_vorgabe_")
            os.environ["OPEN_MCP_CAD_PROJEKT"] = vorgabe
            D._chat_einstellungen_zeigen(z, True)
            m["vorgabe"] = (w["chat_ordner_text"].text().replace(
                chr(0x200B), "").startswith(vorgabe),
                "gilt gerade nicht" in w["chat_ordner_text"].text())
            D._chat_einstellungen_zeigen(z, False)
            os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
            D._ordner_zeigen(z)
            # Vergessen.
            w["chat_ordner_weg"].click()
            m["vergessen"] = ("arbeitsordner" in (_einst_lesen() or {}),
                              w["chat_ordner_text"].text(),
                              w["chat_ordner_weg"].isHidden())
    finally:
        _einst_setzen(None)
        _heim_zurueck(alt_heim)
        _frischer_start()
    return m


def zelle_ordnerwahl_dock():
    """L64 (S12, Etappe D): «Arbeitsordner wählen …» auf der
    Einstellungsseite — Qts Dialog, nicht der von Windows, mit open(), nie
    exec(); gemerkt in chat.json, die Liste frisch."""
    m = _ordnerwahl_lauf()
    pruefe("L64 der Dialog: Qts eigener, nur Ordner, an einem offenen "
           "Fenster des Docks",
           m["optionen"] == (True, True, True, True), m["optionen"])
    pruefe("L64 der Knopf kehrt sofort zurueck, der Dialog steht offen",
           m["knopf_s"] < 0.5 and m["echt_sichtbar"],
           (m["knopf_s"], m["echt_sichtbar"]))
    pruefe("L64 ohne Ordner: kein Start, die Zeile nennt die Wahl im Dock",
           m["ohne"][0] == 0 and "Arbeitsordner wählen" in m["ohne"][1]
           and m["ohne"][2].startswith("Noch keiner"), m["ohne"])
    ordner_ok = (m["gewaehlt"][2] is not None
                 and m["gewaehlt"][3].startswith(m["gewaehlt"][2]))
    pruefe("L64 gewaehlt: open() genau einmal, nie exec(); in chat.json; "
           "angezeigt; 'Wahl entfernen' da; die Liste des Ordners; die "
           "Meldung ohne Ordner ist weg",
           m["gewaehlt"][:2] == (1, 0) and ordner_ok
           and m["gewaehlt"][4] and m["gewaehlt"][5] == ["Seeblick Wand"]
           and m["gewaehlt"][6] == "", m["gewaehlt"])
    pruefe("L64 ein langer Pfad bricht auf der Seite um: bei 300 px ist "
           "die Seite nicht breiter als ihr Platz", m["einst_quer"] == 0,
           m["einst_quer"])
    pruefe("L64 der angezeigte Pfad traegt Umbruch-Angebote, aber was sich "
           "daraus kopieren laesst, nicht; der Tooltip ist der Pfad selbst",
           m["kopie"][2] and chr(0x200B) not in m["kopie"][0]
           and m["kopie"][1] == m["gewaehlt"][2], m["kopie"])
    pruefe("L64 die naechste Nachricht startet dort",
           m["start"][:2] == (1, "")
           and m["start"][2] == [m["gewaehlt"][2]], m["start"])
    pruefe("L64 eine Vorgabe der Einrichtung geht vor, die Seite sagt es",
           m["vorgabe"] == (True, True), m["vorgabe"])
    pruefe("L64 ein Ordner, den es nicht gibt, aendert nichts",
           m["falsch"][0] == m["gewaehlt"][2]
           and "nicht öffnen" in m["falsch"][1], m["falsch"])
    pruefe("L64 'Wahl entfernen': aus chat.json, 'Noch keiner', Knopf weg",
           m["vergessen"][0] is False
           and m["vergessen"][1].startswith("Noch keiner")
           and m["vergessen"][2], m["vergessen"])
    D = dashboard_laden()
    pruefe("L64 der Satz ohne Ordner ist fuer Laien und nennt den Knopf, "
           "wie er heisst", _laientext_ok(D.CHAT_KEIN_ORDNER)
           and "«Arbeitsordner wählen …»" in D.CHAT_KEIN_ORDNER,
           D.CHAT_KEIN_ORDNER)
    for was, mut, rot in (
            ("der Dialog von Windows",
             _anweisungen("_ordner_dialog", lambda s: "DontUseNativeDialog"
                          in ast.unparse(s)),
             lambda k: k["optionen"][0] is False),
            ("der Dialog nicht am Fenster (hier ohne Hauptfenster: ohne "
             "Eltern, in der Ecke des Bildschirms)",
             _anweisungen("_dialog_eltern",
                          lambda s: isinstance(s, ast.For),
                          "return _hauptfenster()"),
             lambda k: k["optionen"][3] is False),
            ("exec() statt open()",
             _anweisungen("_ordner_waehlen", _beginnt("dlg.open()"),
                          "dlg.exec()"),
             # exec() kehrt erst zurueck, wenn der Schutz den Dialog schloss
             lambda k: not k["echt_sichtbar"] and k["gewaehlt"][1] >= 1),
            ("ein zweiter Klick oeffnet einen zweiten Dialog",
             _anweisungen("_ordner_waehlen", lambda s: isinstance(s, ast.If)
                          and "alt is not None" in ast.unparse(s.test)),
             lambda k: k["gewaehlt"][0] == 2),
            ("die Vorgabe ohne Hinweis",
             _anweisungen("_ordner_zeigen", lambda s: isinstance(s, ast.If)
                          and "isdir(wahl)" in ast.unparse(s.test),
                          "if wahl and (not os.path.isdir(wahl)):\n"
                          "    zeilen.append('x')"),
             lambda k: k["vorgabe"][1] is False),
            ("die Wahl nicht gemerkt",
             _ohne_aufruf("_ordner_gewaehlt", "_ordner_merken"),
             lambda k: k["gewaehlt"][2] is None),
            ("der Pfad ohne Umbruch-Angebote",
             _anweisungen("_umbrechbar", lambda s: isinstance(s, ast.Return)
                          and "replace" in ast.unparse(s), "return pfad"),
             lambda k: k["einst_quer"] > 0),
            ("die alte Meldung ohne Ordner",
             _anweisungen("_chat_starten",
                          _beginnt("_chat_fehler_zeigen(z, CHAT_KEIN_ORDNER)"),
                          "_chat_fehler_zeigen(z, 'Claude Code braucht einen "
                          "Arbeitsordner, und es ist noch keiner "
                          "eingerichtet.')"),
             lambda k: "Arbeitsordner wählen" not in k["ohne"][1]),
            ("der Pfad markierbar (wie vor der Nacharbeit D)",
             _anweisungen("_tab_chat", _beginnt(
                 "ordner_text.setWordWrap(True)"),
                          "ordner_text.setWordWrap(True)\n"
                          "ordner_text.setTextInteractionFlags("
                          "Qt.TextInteractionFlag.TextSelectableByMouse)"),
             lambda k: chr(0x200B) in k["kopie"][0])):
        M = _mutant(mut)
        k = _ordnerwahl_lauf(lambda: M)
        pruefe("L64 KONTROLLE: %s -> rot" % was,
               M._mutant_treffer == [1] and rot(k), (M._mutant_treffer, k))


# --- L66: Selbstpruefung Etappe E (2026-09-26) -------------------------------
# Die vier Slots der Modellwahl und der Adresse liefen bis Etappe E ohne
# `_sicher`, obwohl `_modelle_abfragen` seit S6 chat.json liest. Eine Ausnahme
# aus einem Qt-Slot beendet Cadwork (L43).

MODELL_SLOTS = ("_modelle_abfragen", "_modell_gewaehlt", "_modell_getippt",
                "_modelle_knopf")


def _modellslots_lauf(laden=None):
    """Jeder der vier Handler wirft; den Slot ausloesen und zaehlen, was aus
    ihm herauslaeuft (eigener excepthook, wie L57/L61)."""
    import io
    _einst_setzen(None)
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    w = z["w"]
    _anbieter_waehlen(z, "eigen")
    ausloesen = {
        "_modelle_abfragen": lambda: (w["chat_modelle"].setEnabled(True),
                                      w["chat_modelle"].click()),
        "_modell_gewaehlt": lambda: w["chat_modell"].activated.emit(0),
        "_modell_getippt": lambda: w["chat_modell"].editTextChanged.emit(
            "probe-modell"),
        "_modelle_knopf": lambda: w["chat_basis"].textChanged.emit(
            "http://probe"),
    }
    echt = {n: getattr(D, n) for n in MODELL_SLOTS}
    alt_hook, alt_err = sys.excepthook, sys.stderr
    m = {"treffer": getattr(D, "_mutant_treffer", None), "entkommen": {}}
    try:
        sys.stderr = io.StringIO()
        for name in MODELL_SLOTS:
            def wirft(*_a, _name=name, **_k):
                raise RuntimeError("Probe: %s" % _name)
            setattr(D, name, wirft)
            fang = []
            sys.excepthook = lambda t, v, tb, fang=fang: fang.append(
                t.__name__)
            ausloesen[name]()
            _APP.processEvents()
            setattr(D, name, echt[name])
            m["entkommen"][name] = fang
        fehler = sys.stderr.getvalue()
        m["gemeldet"] = [n for n in MODELL_SLOTS
                         if "Probe: %s" % n in fehler]
    finally:
        for name, fn in echt.items():
            setattr(D, name, fn)
        sys.excepthook, sys.stderr = alt_hook, alt_err
        _frischer_start()
    return m


def zelle_modellslots_sicher():
    """L66: Modelle abfragen, Modell waehlen, Modell tippen, Adresse tippen —
    eine Ausnahme bleibt im Dock und steht auf stderr."""
    m = _modellslots_lauf()
    pruefe("L66 wirft ein Handler der Modellwahl oder der Adresse, laeuft "
           "nichts aus dem Slot, der Fehler steht auf stderr (4 Slots)",
           all(f == [] for f in m["entkommen"].values())
           and len(m["entkommen"]) == 4
           and m["gemeldet"] == list(MODELL_SLOTS), m)
    k = _modellslots_lauf(lambda: _mutant(
        _anweisungen("_tab_chat", _beginnt("btn_modelle.clicked.connect("),
                     "btn_modelle.clicked.connect("
                     "lambda: _modelle_abfragen(z))"),
        _anweisungen("_tab_chat", _beginnt("modell.activated.connect("),
                     "modell.activated.connect("
                     "lambda i: _modell_gewaehlt(z, i))"),
        _anweisungen("_tab_chat", _beginnt("modell.editTextChanged.connect("),
                     "modell.editTextChanged.connect("
                     "lambda t: _modell_getippt(z, t))"),
        _anweisungen("_tab_chat", _beginnt("basis.textChanged.connect("),
                     "basis.textChanged.connect("
                     "lambda _t: _modelle_knopf(z))")))
    pruefe("L66 KONTROLLE: die vier Verbindungen wie vor Etappe E (ohne "
           "_sicher) -> jede Ausnahme laeuft aus dem Slot",
           k["treffer"] == [1, 1, 1, 1]
           and all(f == ["RuntimeError"] for f in k["entkommen"].values()),
           k)


# --- L67: Modi im Chat (Chatfenster K1, 2026-09-27) ------------------------

class _SchleifenAttrappe:
    """Eine Schleife im Speicher: merkt jede Antwort auf eine Karte."""

    def __init__(self):
        self.antworten = []

    def freigabe_beantworten(self, kennung, erlauben, grund=""):
        self.antworten.append((kennung, erlauben))
        return True


def _sitzungskarten_lauf(modus, laden=None,
                         werkzeug="mcp__open-mcp-cad__execute_cadwork_command"):
    """Ein Chat (Schleifen-Attrappe) mit ZWEI offenen Karten derselben Art
    und einer abgelehnten Anfrage im Verlauf, im Modus `modus`; auf der
    ersten Karte "Für diese Sitzung nicht mehr fragen". -> dict."""
    from PyQt6.QtWidgets import QLabel, QPushButton
    D, z, d = _neustart(laden)
    w = z["w"]
    schleife = _SchleifenAttrappe()
    karten = [{"id": "k%d" % i, "werkzeug": werkzeug,
               "name": werkzeug.split("__")[-1],
               "eingabe": {"code": "x = %d" % i}, "offen": True}
              for i in (1, 2)]
    z["chat"].update(an=True, laeuft_zug=True, schleife=schleife,
                     freigaben=karten, modus=modus, stand=5,
                     ereignisse=[{"art": "ich", "text": "zeichne"},
                                 {"art": "verweigert", "werkzeug": "Write",
                                  "modus": "nur_lesen"}])
    _warte_qt(D, z, lambda: not w["chat_freigabe"].isHidden(), 2)
    knoepfe = [b for b in w["chat_freigabe"].findChildren(QPushButton)
               if b.text() == "Für diese Sitzung nicht mehr fragen"
               and not b.isHidden()]
    m = {"knoepfe": len(knoepfe), "verlauf": _verlauf_texte(z),
         "schritte": _schritt_zeilen(z),
         "treffer": getattr(D, "_mutant_treffer", None)}
    if knoepfe:
        knoepfe[0].click()
    m["antworten"] = list(schleife.antworten)
    m["sitzung"] = set(z["chat"].get("gewaehrt_sitzung") or ())
    m["texte"] = [l.text() for l in w["chat_freigabe"].findChildren(QLabel)]
    z["chat"].update(an=False, laeuft_zug=False, schleife=None, freigaben=[])
    return m


def zelle_karte_sitzung():
    """L67 (Wunsch 2026-09-27): im Modus "Fragen" traegt die Karte "Für diese
    Sitzung nicht mehr fragen" — der Klick erlaubt diesen Aufruf, gibt die
    Art bis zum Ende des Chats frei und erlaubt die zweite offene Karte
    derselben Art mit; in anderen Modi steht der Knopf nicht da. Eine
    Ablehnung durch den Modus steht im Verlauf."""
    try:
        _einst_setzen(None)
        m = _sitzungskarten_lauf("fragen")
        cad = "mcp__open-mcp-cad__execute_cadwork_command"
        pruefe("L67 Modus 'Fragen': je Karte der Knopf (2), der Klick "
               "erlaubt diese UND die zweite Karte derselben Art, die Art "
               "gilt fuer die Sitzung",
               m["knoepfe"] == 2 and m["antworten"] == [("k1", True),
                                                        ("k2", True)]
               and m["sitzung"] == {cad}, m)
        pruefe("L67 die Ablehnung durch den Modus steht im Verlauf (Kopf "
               "und aufgeklappte Zeile)",
               any("abgelehnt" in t for t in m["verlauf"])
               and any("abgelehnt" in t and "Nur lesen" in t
                       for t in m["schritte"]), m)
        m = _sitzungskarten_lauf("cadwork_frei", werkzeug="Bash")
        pruefe("L67 'Cadwork frei' fragt Aeusseres wie 'Fragen': an einer "
               "Karte fuer Bash steht der Knopf, der Klick gibt die Art fuer "
               "die Sitzung frei (Entscheid 2026-09-28)",
               m["knoepfe"] == 2 and m["antworten"] == [("k1", True),
                                                        ("k2", True)]
               and m["sitzung"] == {"Bash"}, m)
        k = _sitzungskarten_lauf("cadwork_frei")
        pruefe("L67 KONTROLLE: an einer Cadwork-Karte in 'Cadwork frei' "
               "(dort liefe sie ohne Frage) steht der Knopf nicht da",
               k["knoepfe"] == 0 and k["antworten"] == [], k)
        M = _mutant(_anweisungen(
            "_freigabe_karte",
            lambda s: isinstance(s, ast.If) and "modus_von" in
            ast.unparse(s.test)))
        k = _sitzungskarten_lauf("fragen", M)
        pruefe("L67 KONTROLLE: ohne den Knopf in _freigabe_karte -> rot",
               k["treffer"] == [1] and k["knoepfe"] == 0, k)
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L68: Chatfenster und kompakter Monitor (K2, Wunsch 2026-09-27) --------

def _fenster_lauf(laden=None):
    """L68 (K12): der Klick zeigt die Pille; der Chat-Knopf im Kopf oeffnet
    das Fenster beim Chat (ueber Cadwork, nicht modal); schliesst Cadwork
    es, steht die Pille, der Chat laeuft weiter; eine Freigabe laesst den
    Knopf auffallen; ein Neubau stellt den Zustand her. -> dict."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMainWindow
    _frischer_start()
    _einst_setzen(None)
    haupt = QMainWindow()
    haupt.resize(1200, 800)
    haupt.show()
    _ALTE_ZUSTAENDE.append({"haupt": haupt})       # am Leben halten
    m = {}
    try:
        client, kern = _Client([]), _VerbindKern(1, 0)
        D, z, _r = _klick(client, kern, verbinden=False, laden=laden)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        z["dienst"] = Dienst()
        w = z["w"]
        f = z["fenster"]
        D._auffrischen(z)
        QApplication.processEvents()
        # K12: der Klick zeigt die Pille (nur der Kopf) mit dem Chat-Knopf;
        # Leiste, Steuerfenster und Chat-Dock gibt es nicht mehr.
        m["kompakt"] = (f.isVisible(), w["koerper"].isHidden(),
                        not w["kopf_chat"].isHidden(),
                        z.get("mini") is None and z.get("chatfenster") is None,
                        "register" not in w)
        breite_zu = f.width()
        rechts_zu = f.frameGeometry().right()
        with d_sperre(z) as d:
            d.hinweise.extend([hinweis(1, "offen a"), hinweis(2, "offen b"),
                               hinweis(3, "erledigt", status="erledigt")])
        D._auffrischen(z)
        QApplication.processEvents()
        chip = w["kopf_hinweise"]
        m["mehr_text"] = chip.accessibleName()
        m["mehr_zahl"] = chip.text() if not chip.isHidden() else ""
        m["mehr_tipp"] = chip.toolTip()
        m["breiter"] = (f.width() > breite_zu,
                        abs(f.frameGeometry().right() - rechts_zu) <= 2)
        # Der Chat-Knopf im Kopf: das Fenster geht auf, beim Chat, ueber
        # Cadwork, nicht modal.
        w["kopf_chat"].click()
        QApplication.processEvents()
        m["offen"] = (not w["koerper"].isHidden(), f.isWindow(),
                      f.parentWidget() is haupt,
                      f.windowModality() == Qt.WindowModality.NonModal,
                      QApplication.activeModalWidget() is None,
                      w["seiten"].currentIndex() == 0,
                      z["fenster_zustand"] == D.OFFEN_Z)
        m["takt"] = z["chat_takt"].isActive()
        # Ein laufender Chat mit wartender Karte: der Kopf sagt es.
        chat = z["chat"]
        chat.update(an=True, laeuft_zug=True, kurzname="Claude", stand=7,
                    freigaben=[{"id": "f1", "offen": True, "name": "x",
                                "eingabe": {}}])
        f.close()                       # Cadwork schliesst das Dock
        _pumpen(0.1)
        D._chat_zeichnen(z)
        D._auffrischen(z)
        m["geschlossen"] = (f.isVisible(), w["koerper"].isHidden(),
                            chat.get("an"), z["chat_takt"].isActive(),
                            z["fenster"] is f)
        m["monitor"] = (w["kopf_chat"].toolTip(),
                        w["kopf_chat"].objectName(), w["pille"].text())
        w["kopf_chat"].click()
        m["wieder"] = (not w["koerper"].isHidden(), z["fenster"] is f)
        chat.update(freigaben=[], laeuft_zug=False)
        D._chat_zeichnen(z)
        D._auffrischen(z)
        m["monitor_danach"] = (w["kopf_chat"].toolTip(),
                               w["kopf_chat"].objectName(),
                               w["pille"].text())
        # Neubau (andere FORM) mit offenem Fenster: das neue steht wieder
        # offen, beim Chat, mit demselben Chat.
        z["form"] = -1
        _D2, z2, _r = _klick(client, kern, verbinden=False, laden=laden)
        _pumpen(0.1)
        f2 = z2["fenster"]
        m["neubau"] = (f2 is not f, not z2["w"]["koerper"].isHidden(),
                       z2["chat"] is chat, z2["fenster_zustand"])
        chat["an"] = False
        f2.hide()
        kern.aufraeumen()
    finally:
        haupt.hide()
        _frischer_start()
    return m


class d_sperre:
    """`with d_sperre(z) as d:` — der Dienst des Docks unter seiner Sperre."""

    def __init__(self, z):
        self.d = z["dienst"]

    def __enter__(self):
        self.d.sperre.acquire()
        return self.d

    def __exit__(self, *_):
        self.d.sperre.release()


def zelle_chatfenster():
    """L68 (K12, Rueckmeldung 2026-10-07: "nur eine Anzeige, Chat und
    Monitor vereint"): der Klick zeigt die Pille; der Chat-Knopf im Kopf
    oeffnet DASSELBE Fenster beim Chat — ueber Cadwork, nicht modal;
    schliesst Cadwork es, steht die Pille, der Chat laeuft weiter; die Zahl
    offener Hinweise steht als Chip in der Pille (rechte Kante bleibt);
    wartet eine Freigabe, faellt der Chat-Knopf auf und die Pille sagt
    "Wartet auf dich"."""
    try:
        m = _fenster_lauf()
        pruefe("L68 der Klick zeigt die Pille: Koerper zu, Chat-Knopf da, "
               "keine Fenster von K9-K11",
               m["kompakt"] == (True, True, True, True, True), m)
        pruefe("L68 die Pille nennt die offenen Hinweise (2 von 3: Name und "
               "Tooltip, sichtbar die Zahl), wird breiter, die rechte Kante "
               "bleibt",
               "2 offene Hinweise" in m["mehr_text"] and m["mehr_zahl"] == "2"
               and "2 offene Hinweise" in m["mehr_tipp"]
               and m["breiter"] == (True, True),
               (m["mehr_text"], m["mehr_zahl"], m["mehr_tipp"], m["breiter"]))
        pruefe("L68 der Chat-Knopf oeffnet das Fenster beim Chat: schwebend "
               "ueber Cadwork (Eltern), nicht modal; der Takt laeuft",
               m["offen"] == (True,) * 7 and m["takt"], m["offen"])
        pruefe("L68 schliesst Cadwork das Fenster, steht danach die Pille; "
               "der Chat bleibt an, der Takt laeuft, dasselbe Fenster",
               m["geschlossen"] == (True, True, True, True, True),
               m["geschlossen"])
        pruefe("L68 wartet eine Freigabe, faellt der Chat-Knopf auf (Tooltip "
               "nennt sie) und die Pille sagt 'Wartet auf dich'; danach "
               "nicht mehr",
               "Freigabe" in m["monitor"][0]
               and m["monitor"][1] == "hinweis"
               and m["monitor"][2].endswith("Wartet auf dich")
               and "Freigabe" not in m["monitor_danach"][0]
               and m["monitor_danach"][1] == "chatknopf",
               (m["monitor"], m["monitor_danach"]))
        pruefe("L68 der Knopf zeigt DASSELBE Fenster wieder offen",
               m["wieder"] == (True, True), m["wieder"])
        pruefe("L68 ein Neubau mit offenem Fenster stellt es offen wieder "
               "her (derselbe Chat)",
               m["neubau"] == (True, True, True, "offen"), m["neubau"])
        # KONTROLLEN
        k = _fenster_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen", _beginnt("zustand = z.get('fenster_zustand')"),
            "zustand = PILLE_Z")))
        pruefe("L68 KONTROLLE: ohne den gemerkten Zustand steht nach dem "
               "Neubau die Pille", k["treffer"] == [1]
               and k["neubau"][1] is False, k["neubau"])
        k = _fenster_lauf(lambda: _mutant(_ohne_aufruf(
            "_chat_zeichnen", "_chatknopf_zeigen")))
        pruefe("L68 KONTROLLE: ohne den Chat-Knopf im Takt faellt die "
               "Freigabe dort nicht auf", k["treffer"] == [1]
               and k["monitor"][1] != "hinweis", k["monitor"])
        k = _fenster_lauf(lambda: _mutant(_ohne_aufruf(
            "_auffrischen", "_hinweis_zahl_zeigen")))
        pruefe("L68 KONTROLLE: ohne die Zahl faellt ein Hinweis in der "
               "Pille nicht auf", k["treffer"] == [2]
               and k["mehr_zahl"] != "2", (k["mehr_text"], k["mehr_zahl"]))
        k = _fenster_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen",
            _beginnt("koerper.setVisible(zustand == OFFEN_Z)"),
            "koerper.setVisible(True)")))
        pruefe("L68 KONTROLLE: zeigte der Klick das ganze Fenster statt der "
               "Pille, waere die erste Zeile rot", k["treffer"] == [1]
               and k["kompakt"][1] is False, k["kompakt"])
        k = _fenster_lauf(lambda: _mutant(_aufruf_umbenennen(
            "_kopf_bauen", "_fenster_aktion", "_kopf_zeigen")))
        pruefe("L68 KONTROLLE: tut der Chat-Knopf nichts, bleibt die Pille",
               k["treffer"] == [4] and k["offen"][0] is False, k["offen"])
        k = _fenster_lauf(lambda: _mutant(_anweisungen(
            "_fenster_sichtbar", lambda s: isinstance(s, ast.Expr)
            and "singleShot" in ast.unparse(s))))
        pruefe("L68 KONTROLLE: ohne das Nachsehen nach dem Schliessen steht "
               "gar nichts mehr da", k["treffer"] == [1]
               and k["geschlossen"][0] is False, k["geschlossen"])
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L69: Leiste und Kopf des Chatfensters (K3, Wunsch 2026-09-27) ----------

def _leiste_lauf(laden=None):
    """Modus- und Modell-Aufklapper, Ring, Ordner-Menue, "+ Ordner" — im
    gezeigten Chatfenster, gemessen wie ein Klick. -> dict."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QApplication
    heim, alt_heim = _heim_setzen()
    _einst_setzen(None)
    m = {}
    try:
        _frischer_start()
        D, z, _d = aufbauen(D=laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        w = z["w"]
        C = D._chat_modul()
        _chat_ziehen(D, z, 460, 680)
        # Welche Richtung jeder Aufklapper VERLANGT (am Bildschirmrand darf
        # er umklappen — dann sagt die Lage allein nichts ueber die Wahl).
        m["richtung"] = {}
        for name in ("chat_modus_auf", "chat_modell_auf", "chat_ordner_auf"):
            auf0 = w[name]
            echt0 = auf0.zeigen_an

            def merken(knopf, nach_oben=True, rechts=False, _n=name,
                       _e=echt0):
                m["richtung"][_n] = (nach_oben, rechts)
                return _e(knopf, nach_oben, rechts)
            auf0.zeigen_an = merken

        def lage(auf, knopf):
            """(oben?, unten?, rechts buendig?) des Aufklappers zum Knopf."""
            a_oben = auf.mapToGlobal(QPoint(0, 0)).y()
            a_unten = a_oben + auf.height()
            k = knopf.mapToGlobal(QPoint(0, 0))
            rechts = abs((auf.mapToGlobal(QPoint(0, 0)).x() + auf.width())
                         - (k.x() + knopf.width())) <= 2
            return (a_unten <= k.y(), a_oben >= k.y() + knopf.height(),
                    rechts)
        # -- Modus -----------------------------------------------------------
        m["flach"] = (w["chat_modus"].objectName(),
                      w["chat_modell_knopf"].objectName())
        t0 = time.monotonic()
        w["chat_modus"].click()
        m["modus_s"] = time.monotonic() - t0
        auf = w["chat_modus_auf"]
        QApplication.processEvents()
        m["modus_auf"] = (auf.isVisible(),
                          bool(auf.windowFlags() & Qt.WindowType.Popup),
                          QApplication.activeModalWidget() is None,
                          QApplication.activePopupWidget() is auf)
        m["modus_lage"] = lage(auf, w["chat_modus"])
        m["modus_eintraege"] = [(e.wert, getattr(e, "haken", False),
                                 e.satz.text()) for e in auf.eintraege]
        m["modus_saetze_ok"] = all(
            satz == D._modus_hinweis(wert, C)
            for wert, _h, satz in m["modus_eintraege"])
        # Mitten im Chat waehlbar.
        z["chat"].update(an=True, laeuft_zug=True, ereignisse=[],
                         freigaben=[], anbieter="claude")
        for e in auf.eintraege:
            if e.wert == "cadwork_frei":
                e.click()
        QApplication.processEvents()
        m["modus_gewaehlt"] = (z["chat"].get("modus"), auf.isVisible(),
                               (_einst_lesen() or {}).get("modus"),
                               w["chat_modus"].property("modus"))
        # -- Modell mitten im Chat: gesperrt, mit Hinweis (K12: Popover) ----
        w["chat_modell_knopf"].click()
        mauf = w["chat_modell_auf"]
        QApplication.processEvents()
        m["modell_lage"] = lage(mauf, w["chat_modell_knopf"])
        m["modell_gesperrt"] = (
            [w["stufe_kachel"].isEnabled()],
            any("nächsten chat" in lb.text().lower() for lb in
                mauf.findChildren(type(w["chat_lage"]))
                if lb.isVisible()),
            w["chat_stufe"].isEnabled())
        mauf.hide()
        z["chat"].update(an=False, laeuft_zug=False)
        # -- Modell ohne Chat: die Kachel oeffnet die Liste DARUEBER, die
        # Wahl schliesst nur sie; die Denkstufe am Punktregler (Taste Pos1).
        from PyQt6.QtTest import QTest
        w["chat_modell_knopf"].click()
        QApplication.processEvents()
        w["stufe_kachel"].click()
        liste = w["modell_liste_auf"]
        QApplication.processEvents()
        m["modell_eintraege"] = [(e.wert, e.text().strip())
                                 for e in liste.eintraege
                                 if getattr(e, "wert", None)]
        m["stufe_sichtbar"] = not w["chat_stufe"].isHidden()
        for e in liste.eintraege:
            if getattr(e, "wert", None) == "opus":
                e.click()
        QApplication.processEvents()
        m["liste_zu_popover_bleibt"] = (not liste.isVisible(),
                                        mauf.isVisible())
        regler = w["chat_stufe"]
        regler.setFocus()
        QTest.keyClick(regler, Qt.Key.Key_Home)
        gemerkt = _einst_lesen() or {}
        m["modell_gewaehlt"] = (D._modellwahl(w["chat_modell"]),
                                (gemerkt.get("modell") or {}).get("claude"),
                                gemerkt.get("denkstufe"),
                                w["chat_modell_knopf"].volltext())
        _anbieter_waehlen(z, "openai")
        w["chat_modell_knopf"].click()
        m["stufe_openai"] = w["chat_stufe"].isHidden()
        mauf.hide()
        _anbieter_waehlen(z, "claude")
        # -- Ring ------------------------------------------------------------
        z["chat"].update(an=True, kontext={"belegt": 130000,
                                           "fenster": 200000})
        D._chat_zeichnen(z)
        ring = w["chat_kontext"]
        m["ring"] = (not ring.isHidden(), ring.anteil(), ring.toolTip())
        z["chat"].update(kontext=None)
        D._chat_zeichnen(z)
        m["ring_weg"] = ring.isHidden()
        z["chat"]["an"] = False
        # -- Ordner-Menue und + Ordner ----------------------------------------
        att = _DialogAttrappe()
        D._ordner_dialog = lambda _z: att
        eins = _tempfile.mkdtemp(prefix="omcad_live_ordner_eins_")
        zwei = _tempfile.mkdtemp(prefix="omcad_live_ordner_zwei_")
        for o in (eins, zwei):
            w["chat_ordner_waehlen"].click()
            att.waehlen(o)
        m["ordner_knopf"] = (w["chat_ordner"].volltext(),
                             w["chat_ordner"].toolTip())
        w["chat_ordner"].click()
        oauf = w["chat_ordner_auf"]
        QApplication.processEvents()
        m["ordner_lage"] = lage(oauf, w["chat_ordner"])
        zuletzt = [e for e in oauf.eintraege if getattr(e, "wert", None)]
        m["zuletzt"] = [e.wert for e in zuletzt]
        if zuletzt:
            zuletzt[0].click()
        m["zurueck"] = z.get("ordner_wahl")
        oauf.hide()
        zatt = _DialogAttrappe()
        D._zusatz_dialog = lambda _z: zatt
        extra = _tempfile.mkdtemp(prefix="omcad_live_extra_")
        w["chat_zusatz"].click()
        zatt.waehlen(extra)
        chips = [w["chat_zusatz_lay"].itemAt(i).widget()
                 for i in range(w["chat_zusatz_lay"].count())
                 if w["chat_zusatz_lay"].itemAt(i).widget() is not None]
        m["zusatz"] = (z.get("zusatz_ordner"),
                       (_einst_lesen() or {}).get("zusatzordner"),
                       [c.text() for c in chips], zatt.geoeffnet,
                       zatt.exec_gerufen)
        with _ChatStartAttrappe(D, z, projekt=eins) as start:
            _senden_klick(D, z, "Hallo")
            m["start_zusatz"] = [k.get("zusatz") for k in start.gestartet]
        z["chat"]["an"] = False
        if chips:
            chips[0].click()
        m["zusatz_weg"] = (z.get("zusatz_ordner"),
                           (_einst_lesen() or {}).get("zusatzordner"))
        m["zweite"] = (eins, zwei, extra)
    finally:
        _heim_zurueck(alt_heim)
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_leiste():
    """L69 (Wunsch 2026-09-27): die Leiste unter der Eingabe und der Kopf.
    Bedienteile sehen aus wie Text (`flach`), ein Klick klappt einen
    Aufklapper auf (Qt.Popup, show(): kehrt sofort zurueck, nichts Modales)
    — Modus und Modell NACH OBEN (Modell rechtsbuendig), der Ordner nach
    unten. Modus jederzeit waehlbar; Modell und Denkstufe mitten im Chat
    gesperrt; der Ring zeigt, wie voll der Kontext ist; das Ordner-Menue
    kennt die zuletzt benutzten; "+ Ordner" gibt weitere Ordner frei."""
    try:
        m = _leiste_lauf()
        pruefe("L69 Modus und Modell sehen aus wie Text (QSS 'flach')",
               m["flach"] == ("flach", "flach"), m["flach"])
        pruefe("L69 Modus-Aufklapper: sichtbar, ein Popup-Fenster, nichts "
               "Modales, er ist das aktive Popup (der Kern haelt so lange "
               "zurueck), der Klick kehrt sofort zurueck",
               m["modus_auf"] == (True, True, True, True)
               and m["modus_s"] < 0.5, (m["modus_auf"], m["modus_s"]))
        pruefe("L69 der Modus klappt NACH OBEN auf",
               m["modus_lage"][0] and not m["modus_lage"][1]
               and m["richtung"].get("chat_modus_auf") == (True, False),
               (m["modus_lage"], m["richtung"]))
        pruefe("L69 vier Modi, der wirksame mit Haken, je der Satz aus der "
               "Politik (_modus_hinweis)",
               [e[0] for e in m["modus_eintraege"]]
               == ["nur_lesen", "fragen", "cadwork_frei", "alles_auto"]
               and [e[1] for e in m["modus_eintraege"]]
               == [False, True, False, False] and m["modus_saetze_ok"],
               m["modus_eintraege"])
        pruefe("L69 mitten im Chat gewaehlt: gilt, gemerkt, der Knopf zeigt "
               "ihn, der Aufklapper geht zu",
               m["modus_gewaehlt"] == ("cadwork_frei", False, "cadwork_frei",
                                       "cadwork_frei"), m["modus_gewaehlt"])
        pruefe("L69 das Modell klappt nach oben und rechtsbuendig auf",
               m["modell_lage"] == (True, False, True)
               and m["richtung"].get("chat_modell_auf") == (True, True),
               (m["modell_lage"], m["richtung"]))
        eintr, notiz, stufe_an = m["modell_gesperrt"]
        pruefe("L69 mitten im Chat: Modellwahl (Kachel) gesperrt, Hinweis "
               "'nächsten Chat', Regler gesperrt", eintr and not any(eintr)
               and notiz
               and not stufe_an, m["modell_gesperrt"])
        pruefe("L69 die Modelle von Claude Code in der Liste ueber dem "
               "Popover, der Regler der Denkstufe da",
               [w for w, _t in m["modell_eintraege"]]
               == ["sonnet", "opus", "fable", "haiku"]
               and m["stufe_sichtbar"], m["modell_eintraege"])
        pruefe("L69 Modell gewaehlt (die Liste geht zu, der Popover bleibt) "
               "und Regler ganz links: beides gilt, gemerkt, der Knopf zeigt "
               "es ('Opus 5.5 · Niedrig')",
               m["modell_gewaehlt"][:3] == ("opus", "opus", "low")
               and m["modell_gewaehlt"][3].startswith("Opus")
               and m["modell_gewaehlt"][3].endswith("· Niedrig")
               and m["liste_zu_popover_bleibt"] == (True, True),
               (m["modell_gewaehlt"], m["liste_zu_popover_bleibt"]))
        pruefe("L69 bei OpenAI kein Regler (keine Denkstufe)",
               m["stufe_openai"], m["stufe_openai"])
        pruefe("L69 der Ring: sichtbar mit 65 %, der Tooltip nennt die Token; "
               "ohne Zahl weg", m["ring"][0] and m["ring"][1] == 0.65
               and "Token" in m["ring"][2] and m["ring_weg"],
               (m["ring"], m["ring_weg"]))
        eins, zwei, extra = m["zweite"]
        pruefe("L69 der Ordnerknopf nennt den Ordner, der Tooltip den Pfad",
               os.path.basename(zwei) in m["ordner_knopf"][0]
               and m["ordner_knopf"][1] == zwei, m["ordner_knopf"])
        pruefe("L69 das Ordner-Menue klappt nach UNTEN auf und kennt den "
               "vorigen Ordner; ein Klick waehlt ihn wieder",
               m["ordner_lage"][1] and not m["ordner_lage"][0]
               and m["richtung"].get("chat_ordner_auf") == (False, False)
               and m["zuletzt"] == [eins] and m["zurueck"] == eins,
               (m["ordner_lage"], m["zuletzt"], m["zurueck"]))
        pruefe("L69 '+ Ordner': Dialog ueber open() (nie exec), der Ordner "
               "steht als Knopf da und in chat.json",
               m["zusatz"][0] == [extra] and m["zusatz"][1] == [extra]
               and len(m["zusatz"][2]) == 1
               and os.path.basename(extra) in m["zusatz"][2][0]
               and m["zusatz"][3:] == (1, 0), m["zusatz"])
        pruefe("L69 der naechste Start bekommt ihn (Claude Code: --add-dir)",
               m["start_zusatz"] == [[extra]], m["start_zusatz"])
        pruefe("L69 ein Klick auf den Knopf nimmt ihn heraus",
               m["zusatz_weg"] == ([], None), m["zusatz_weg"])
        # KONTROLLEN
        k = _leiste_lauf(lambda: _mutant(_anweisungen(
            "_aufklapper_zeigen", _beginnt("auf.zeigen_an("),
            "auf.zeigen_an(knopf, not nach_oben, rechts)")))
        pruefe("L69 KONTROLLE: falsch herum verlangt -> rot (Modus nach "
               "unten, Ordner nach oben)", k["treffer"] == [1]
               and k["richtung"].get("chat_modus_auf") == (False, False)
               and k["richtung"].get("chat_ordner_auf") == (True, False),
               k["richtung"])
        k = _leiste_lauf(lambda: _mutant(_anweisungen(
            "_modus_aufklappen", _beginnt("auf.zeile("),
            "auf.zeile(_modus_anzeige(wert, C), _satz, lambda wert=wert: "
            "_sicher(lambda: _modus_waehlen(z, wert), 'Modus wählen'), "
            "haken=wert == jetzt, wert=wert)")))
        pruefe("L69 KONTROLLE: die festen Saetze aus MODI statt der Politik "
               "-> rot", k["treffer"] == [1] and not k["modus_saetze_ok"],
               k["treffer"])
        k = _leiste_lauf(lambda: _mutant(_anweisungen(
            "_chat_starten", lambda s: isinstance(s, ast.Try)
            and "C.starten(" in ast.unparse(s),
            "try:\n    C.starten(chat, ordner, port=st.get('port'), "
            "dokument=st.get('dokument'), sitzung=offen['id'] if offen else "
            "None, abzweigen=False, name=C.SITZUNG_NAME, vorher=(offen.get("
            "'ereignisse') or None) if offen else None, modell=_modellwahl("
            "z['w']['chat_modell']), effort=z['w']['chat_stufe']."
            "currentData())\nexcept C.SitzungBelegt as fehler:\n    "
            "_chat_fehler_zeigen(z, str(fehler))\n    return False\n"
            "except Exception as fehler:\n    _chat_fehler_zeigen(z, "
            "'Chat startet nicht: %s' % fehler)\n    return False")))
        pruefe("L69 KONTROLLE: ohne 'zusatz' im Start -> rot",
               k["treffer"] == [1] and k["start_zusatz"] == [None],
               (k["treffer"], k["start_zusatz"]))
        k = _leiste_lauf(lambda: _mutant(_anweisungen(
            "_ordner_merken", _beginnt("zuletzt = [pfad] +"))))
        pruefe("L69 KONTROLLE: ohne das Merken der zuletzt benutzten -> das "
               "Menue kennt den vorigen Ordner nicht",
               k["treffer"] == [1] and k["zuletzt"] == [], k["zuletzt"])
    finally:
        _frischer_start()


# --- L70: Anhaenge (K4, Wunsch 2026-09-27) -----------------------------------

class _DateienAttrappe:
    """Statt des echten Dateidialogs: zaehlt open()/exec(), liefert Dateien
    ueber das echte Signal `filesSelected`."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Q(QObject):
            filesSelected = pyqtSignal(list)
        self.q = _Q()
        self.filesSelected = self.q.filesSelected
        self.geoeffnet, self.exec_gerufen = 0, 0

    def open(self):
        self.geoeffnet += 1

    def exec(self):
        self.exec_gerufen += 1
        return 0

    def isVisible(self):
        return False

    def waehlen(self, pfade):
        self.filesSelected.emit(list(pfade))


def _png_datei(pfad, groesse=24, farbe=(20, 40, 220)):
    from PyQt6.QtGui import QColor, QImage
    bild = QImage(groesse, groesse, QImage.Format.Format_RGB32)
    bild.fill(QColor(*farbe))
    bild.save(pfad, "PNG")
    return pfad


def _chips(z):
    lay = z["w"]["chat_anhaenge_lay"]
    return [lay.itemAt(i).widget() for i in range(lay.count())
            if lay.itemAt(i).widget() is not None]


def _anhang_lauf(laden=None):
    """"+", Dateidialog (Attrappe), Einfuegen, Ablegen, zu grosse Datei,
    Senden an Claude Code und an OpenAI. -> dict."""
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication
    _einst_setzen(None)
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    t = _tempfile.mkdtemp(prefix="omcad_live_anhang_")
    try:
        _chat_ziehen(D, z, 460, 680)
        # -- "+" klappt nach oben auf -------------------------------------
        w["chat_plus"].click()
        auf = w["chat_plus_auf"]
        QApplication.processEvents()
        m["plus"] = ([e.text().strip() for e in auf.eintraege],
                     auf.isVisible(), QApplication.activeModalWidget())
        # -- Dateien ueber den Dialog -------------------------------------
        att = _DateienAttrappe()
        D._anhang_dialog = lambda _z: att
        # Wo gelesen wird: nie im Qt-Thread.
        m["leser_im_qt"] = []
        echt_lesen = D._anhang_datei_lesen

        def lesen_merken(pfad):
            m["leser_im_qt"].append(
                threading.current_thread() is threading.main_thread())
            return echt_lesen(pfad)
        D._anhang_datei_lesen = lesen_merken
        for e in auf.eintraege:
            if "Datei oder Foto" in e.text():
                e.click()
        bild = _png_datei(os.path.join(t, "plan.png"))
        text = os.path.join(t, "notiz.txt")
        with open(text, "w", encoding="utf-8") as fh:
            fh.write("INHALT-42 Seeblick")
        roh = os.path.join(t, "zeichnung.bin")
        with open(roh, "wb") as fh:
            fh.write(b"\x00\x01\x02" * 100)
        gross = os.path.join(t, "riesig.png")
        with open(gross, "wb") as fh:
            fh.write(b"\x89PNG" + b"0" * (D.BILD_MAX_BYTES + 10))
        t0 = time.monotonic()
        att.waehlen([bild, text, roh, gross])
        m["waehlen_s"] = time.monotonic() - t0
        m["dialog"] = (att.geoeffnet, att.exec_gerufen)
        _warte_qt(D, z, lambda: len(_chips(z)) == 3 and all(
            a.get("status") != "laedt" for a in z.get("anhaenge") or ()), 5)
        m["nach_dialog"] = (["%s|%s" % (c.property("symbol"), c.volltext())
                             for c in _chips(z)],
                            [(a["name"], a.get("art"))
                             for a in z.get("anhaenge") or ()],
                            _meldung(z))
        # -- Einfuegen eines Bilds (Strg+V) und Ablegen einer Datei ---------
        feld = w["chat_eingabe"]
        mime = QMimeData()
        b = QImage(30, 30, QImage.Format.Format_RGB32)
        b.fill(QColor(220, 20, 20))
        mime.setImageData(b)
        m["kann_bild"] = feld.canInsertFromMimeData(mime)
        feld.insertFromMimeData(mime)
        abgelegt = _png_datei(os.path.join(t, "foto.png"), 16)
        mime2 = QMimeData()
        mime2.setUrls([QUrl.fromLocalFile(abgelegt)])
        feld.insertFromMimeData(mime2)
        _warte_qt(D, z, lambda: len(_chips(z)) == 5 and all(
            a.get("status") != "laedt" for a in z.get("anhaenge") or ()), 5)
        m["eingefuegt"] = [(a["name"].split(" ")[0], a.get("art"),
                            a.get("mime")) for a in z["anhaenge"][3:]]
        mime3 = QMimeData()
        mime3.setText("nur Text")
        feld.insertFromMimeData(mime3)
        m["text_bleibt_text"] = (feld.toPlainText(), len(_chips(z)))
        feld.clear()
        # -- Ein Klick auf einen Anhang nimmt ihn heraus ------------------
        _chips(z)[-1].click()
        m["heraus"] = len(z["anhaenge"])
        # -- Senden an OpenAI mit einer anderen Datei: nichts startet -------
        with _AnbieterStartAttrappe(D) as an_att:
            _anbieter_waehlen(z, "openai")
            rest = _senden_klick(D, z, "schau")
            m["openai"] = (an_att.gestartet, rest, _meldung(z),
                           len(z["anhaenge"]))
        _anbieter_waehlen(z, "claude")
        # -- Laedt noch: nichts wird gesendet -------------------------------
        z["anhaenge"].append({"id": 999, "name": "langsam.png",
                              "status": "laedt"})
        with _ChatStartAttrappe(D, z) as start:
            gesendet = []
            mod = sys.modules[_ChatStartAttrappe.NAME]
            mod.senden = (lambda chat, text, anhaenge=None:
                          gesendet.append((text, anhaenge)))
            rest = _senden_klick(D, z, "schau")
            m["laedt"] = (len(start.gestartet), rest, _meldung(z))
            z["anhaenge"] = [a for a in z["anhaenge"] if a["id"] != 999]
            rest = _senden_klick(D, z, "schau")
            m["gesendet"] = ([(t_, [(a["art"], a["name"], bool(a.get("b64")),
                                     "INHALT-42" in (a.get("als_text") or ""))
                                    for a in (an or ())])
                              for t_, an in gesendet], rest,
                             len(z.get("anhaenge") or ()), len(_chips(z)))
    finally:
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_anhaenge():
    """L70 (Wunsch 2026-09-27): "+" klappt "Datei oder Foto hinzufügen"
    nach oben auf (Qts Dialog ueber open()); Einfuegen und Ablegen in die
    Eingabe; die Anhaenge als Knoepfe mit ×; gelesen im Nebenthread; zu
    grosse Bilder mit Grund heraus; Senden nimmt sie mit — bei anderen
    Anbietern als Claude Code keine anderen Dateien; solange einer laedt,
    wird nichts gesendet."""
    try:
        m = _anhang_lauf()
        pruefe("L70 '+' klappt auf: Datei oder Foto, Zwischenablage; nichts "
               "Modales", len(m["plus"][0]) == 2
               and "Datei oder Foto hinzufügen" in m["plus"][0][0]
               and m["plus"][1] and m["plus"][2] is None, m["plus"])
        pruefe("L70 der Dialog geht ueber open() (nie exec), das Waehlen "
               "kehrt sofort zurueck, gelesen wird im Nebenthread",
               m["dialog"] == (1, 0) and m["waehlen_s"] < 0.5
               and len(m["leser_im_qt"]) >= 4 and not any(m["leser_im_qt"]),
               (m["dialog"], m["waehlen_s"], m["leser_im_qt"]))
        chips, liste, meldung = m["nach_dialog"]
        pruefe("L70 Bild, Textdatei, andere Datei als Anhaenge; das zu grosse "
               "Bild ist heraus und die Zeile sagt warum",
               liste == [("plan.png", "bild"), ("notiz.txt", "text"),
                         ("zeichnung.bin", "datei")]
               and len(chips) == 3 and chips[0] == "bild|plan.png ×"
               and "riesig.png" in meldung and "zu gross" in meldung, m)
        pruefe("L70 Einfuegen (Bild aus der Zwischenablage) und Ablegen "
               "(Datei) werden Anhaenge; Text bleibt Text",
               m["kann_bild"] and m["eingefuegt"] == [
                   ("Bild", "bild", "image/png"),
                   ("foto.png", "bild", "image/png")]
               and m["text_bleibt_text"] == ("nur Text", 5), m)
        pruefe("L70 ein Klick auf den Anhang nimmt ihn heraus",
               m["heraus"] == 4, m["heraus"])
        pruefe("L70 OpenAI mit einer anderen Datei: kein Start, Text bleibt, "
               "die Zeile sagt es, die Anhaenge bleiben",
               m["openai"][0] == [] and m["openai"][1] == "schau"
               and "nur mit Claude Code" in m["openai"][2]
               and m["openai"][3] == 4, m["openai"])
        pruefe("L70 laedt einer noch: nichts gesendet, der Text bleibt",
               m["laedt"][1] == "schau" and "lädt noch" in m["laedt"][2],
               m["laedt"])
        pruefe("L70 Senden an Claude Code nimmt alle mit (Bild base64, Text "
               "mit Inhalt), danach sind Feld und Anhaenge leer",
               m["gesendet"][0] == [("schau", [
                   ("bild", "plan.png", True, False),
                   ("text", "notiz.txt", False, True),
                   ("datei", "zeichnung.bin", False, False),
                   ("bild", m["gesendet"][0][0][1][3][1], True, False)])]
               and m["gesendet"][1:] == ("", 0, 0), m["gesendet"])
        # KONTROLLEN
        k = _anhang_lauf(lambda: _mutant(_anweisungen(
            "_anhaenge_laden", lambda s_: isinstance(s_, ast.Expr)
            and ast.unparse(s_).startswith("threading.Thread(target=lesen"),
            "lesen()")))
        pruefe("L70 KONTROLLE: ohne Nebenthread liest der Qt-Thread",
               k["treffer"] == [1] and any(k["leser_im_qt"]),
               k["leser_im_qt"])
        k = _anhang_lauf(lambda: _mutant(_anweisungen(
            "_chat_senden", lambda s_: isinstance(s_, ast.If)
            and "laedt" in ast.unparse(s_.test))))
        pruefe("L70 KONTROLLE: ohne die Wache 'laedt noch' geht die Nachricht "
               "ohne den Anhang", k["treffer"] == [1]
               and "lädt noch" not in k["laedt"][2], k["laedt"])
        k = _anhang_lauf(lambda: _mutant(_anweisungen(
            "_anhang_aus_mime", lambda s_: isinstance(s_, ast.If)
            and "hasImage" in ast.unparse(s_.test))))
        pruefe("L70 KONTROLLE: ohne Bild im Einfuegen kein Anhang daraus",
               k["treffer"] == [1] and ("Bild", "bild", "image/png")
               not in k["eingefuegt"], k["eingefuegt"])
        k = _anhang_lauf(lambda: _mutant(_anweisungen(
            "_chat_senden", lambda s_: isinstance(s_, ast.If)
            and "datei" in ast.unparse(s_.test))))
        pruefe("L70 KONTROLLE: ohne die Pruefung 'nur Claude Code' startet "
               "OpenAI mit einer Datei, die es nicht lesen kann",
               k["treffer"] == [1] and k["openai"][0] != [], k["openai"])
    finally:
        _frischer_start()


# --- L71: lesbarer Chat (K5, Wunsch 2026-09-27) -----------------------------

MCP = "mcp__open-mcp-cad__"


class _Uhr:
    """Die Uhr des Dashboards, `vor` Sekunden vorgestellt (Zeitangaben)."""

    def __init__(self, vor=0.0):
        self.vor = vor

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return time.time() + self.vor


def _gespraech(t0, jetzt):
    """Ein Zug mit drei Cadwork-Schritten (einer scheitert), Antwort,
    Schluss — und zwei Stunden spaeter eine neue Nachricht."""
    return [
        {"art": "ich", "text": "Zeichne eine Wand von vier Metern auf der Achse A, mit Schwelle und Rähm",
         "zeit": t0},
        {"art": "werkzeug", "werkzeug": MCP + "get_document_info",
         "eingabe": {}, "id": "t1", "zeit": t0 + 1},
        {"art": "auto", "werkzeug": MCP + "get_document_info",
         "eingabe": {}, "zeit": t0 + 1},
        {"art": "ergebnis", "id": "t1", "fehler": False, "zeit": t0 + 2},
        {"art": "werkzeug", "werkzeug": MCP + "execute_cadwork_command",
         "eingabe": {"code": "x = 1", "description": "<b>fett</b>"},
         "id": "t2", "zeit": t0 + 3},
        {"art": "ergebnis", "id": "t2", "fehler": True, "zeit": t0 + 4},
        {"art": "werkzeug", "werkzeug": MCP + "execute_cadwork_command",
         "eingabe": {"code": "x = 2", "description": "Wand Nord"},
         "id": "t3", "zeit": t0 + 5},
        {"art": "ergebnis", "id": "t3", "fehler": False, "zeit": t0 + 6},
        {"art": "text", "text": "Die Wand steht.", "zeit": t0 + 20},
        {"art": "schluss", "token": 18, "zeit": t0 + 21},
        {"art": "ich", "text": "Danke", "zeit": jetzt - 20},
    ]


def _lesbar_lauf(laden=None):
    """Blasen, Schrittgruppe, Zeitlinien, Zeit laeuft weiter. -> dict."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QLabel
    _einst_setzen(None)
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    alt_uhr = D.time
    try:
        _chat_ziehen(D, z, 460, 680)
        jetzt = time.time()
        z["chat"].update(an=True, anbieter="claude", freigaben=[],
                         ereignisse=_gespraech(jetzt - 7200, jetzt),
                         stand=z["chat"].get("stand", 0) + 1)
        ver = w["chat_verlauf"]
        _warte_qt(D, z, lambda: ver.count() >= 5, 3)
        m["texte"] = ver.texte()
        m["mit_zeit"] = ver.texte(mit_zeit=True)
        gruppen = ver.widgets("schritte")
        g = gruppen[0] if gruppen else None
        m["zu"] = (g.teil.isHidden(), g.kopf.text(),
                   g.pfeil.property("symbol")) if g else None
        sichtbar = [x.text.text() for x in ver.widgets() if hasattr(x, "text")]
        if g:
            g.kopf.click()
            sichtbar += [g.kopf.text()] + g.zeilen()
            m["auf"] = (g.teil.isHidden(), g.pfeil.property("symbol"),
                        g.zeilen(),
                        [lb.toolTip() for lb in g.teil.findChildren(QLabel)],
                        [lb.property("symbol") for lb in
                         g.teil.findChildren(QLabel)
                         if lb.objectName() == "schritt_symbol"])
        m["sichtbar"] = sichtbar
        # Eingaben der KI (hier eine Beschreibung mit HTML) nie als Rich Text
        tipps = m["auf"][3] if g else []
        m["klartext"] = (g.kopf.textFormat() == Qt.TextFormat.PlainText
                         if g else None,
                         [t for t in tipps if "fett" in t])
        _APP.processEvents()
        vp = ver.viewport()
        ich = ver.widgets("ich")[-1].text
        ki = ver.widgets("ki")[0]
        links = ich.mapTo(vp, QPoint(0, 0)).x()
        m["ich_lage"] = (links, links + ich.width(), vp.width(),
                         ich.objectName())
        lang = ver.widgets("ich")[0].text
        m["ich_lang"] = (lang.width(), vp.width())
        pm = ki.marke.pixmap()
        m["ki_lage"] = (ki.text.mapTo(vp, QPoint(0, 0)).x(),
                        ki.marke.property("symbol")
                        if pm is not None and not pm.isNull()
                        else ki.marke.text(),
                        ki.marke.isVisible(), ki.text.objectName(),
                        # Die Quelle (QLabel.pixmap() gibt offscreen eine
                        # 1:1-Kopie fuer den Bildschirm zurueck).
                        D._logo_pixmap(20).devicePixelRatio()
                        if D._logo_pixmap(20) is not None else None)
        # -- Die Zeit laeuft weiter: "gerade eben" wird "vor 7 min" ---------
        zeitlinie = ver.widgets("zeit")[-1]
        vorher = zeitlinie.text.text()
        D.time = _Uhr(400)
        for _ in range(3):
            D._chat_zeichnen(z)
            _APP.processEvents()
        m["zeit_weiter"] = (vorher, zeitlinie.text.text(),
                            ver.widgets("zeit")[-1] is zeitlinie)
    finally:
        D.time = alt_uhr
        _einst_setzen(None)
        _frischer_start()
    return m


def _lauf_im_zug(laden=None):
    """Ein laufender Zug mit Paketlauf; die Gruppe waechst, aufgeklappt;
    dann rollt der Nutzer hoch, Neues kommt. -> dict."""
    _einst_setzen(None)
    _frischer_start()
    D, z, d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    try:
        _chat_ziehen(D, z, 460, 680)
        echt_status = d.status
        d.status = lambda: dict(echt_status(), auftrag={"paket": [3, 8]})
        chat = z["chat"]
        ev = [{"art": "ich", "text": "Zeichne das Dach"},
              {"art": "werkzeug", "werkzeug": MCP + "get_document_info",
               "eingabe": {}, "id": "b0"},
              {"art": "ergebnis", "id": "b0", "fehler": False},
              {"art": "werkzeug", "werkzeug": MCP + "execute_cadwork_batch",
               "eingabe": {"code": "…", "daten_datei": "d.json"}, "id": "b1"}]
        chat.update(an=True, anbieter="claude", freigaben=[], ereignisse=ev,
                    laeuft_zug=True, stand=chat.get("stand", 0) + 1)
        ver = w["chat_verlauf"]
        _warte_qt(D, z, lambda: bool(ver.widgets("schritte")), 3)
        g = ver.widgets("schritte")[0]
        m["kopf"] = g.kopf.text()
        erste = ver.widgets("ich")[0]
        g.kopf.click()
        ev.append({"art": "werkzeug", "werkzeug": MCP + "redraw_view",
                   "eingabe": {}, "id": "b2"})
        chat["stand"] += 1
        _warte_qt(D, z, lambda: len(ver.widgets("schritte")[0].zeilen()) == 3
                  if ver.widgets("schritte") else False, 2)
        g2 = ver.widgets("schritte")[0] if ver.widgets("schritte") else None
        m["waechst"] = (g2 is g, g2.teil.isHidden() if g2 else None,
                        g2.zeilen() if g2 else None,
                        ver.widgets("ich")[0] is erste)
        # -- Folgen: viele Antworten, dann hochrollen, dann Neues ------------
        chat["laeuft_zug"] = False
        for i in range(30):
            ev.append({"art": "text", "text": "Absatz %d mit etwas Text, "
                       "damit der Verlauf rollt." % i})
        chat["stand"] += 1
        _warte_qt(D, z, lambda: ver.count() >= 32, 3)
        for _ in range(5):
            _APP.processEvents()
        leiste = ver.verticalScrollBar()
        m["unten"] = (leiste.value(), leiste.maximum(), ver.neu.isHidden())
        leiste.setValue(0)
        _APP.processEvents()
        for i in range(3):
            ev.append({"art": "text", "text": "Nachtrag %d" % i})
        chat["stand"] += 1
        _warte_qt(D, z, lambda: ver.count() >= 35, 3)
        for _ in range(5):
            _APP.processEvents()
        m["oben"] = (leiste.value(), leiste.maximum(), ver.neu.isHidden())
        ver.neu.click()
        for _ in range(3):
            _APP.processEvents()
        m["neu_klick"] = (leiste.value(), leiste.maximum(),
                          ver.neu.isHidden())
    finally:
        _einst_setzen(None)
        _frischer_start()
    return m


def _auftraege_lauf(laden=None):
    """Die Auftragsliste im Monitor: lesbar, Technik im Tooltip, bei voller
    Liste trotzdem neu, Zeitangaben an Ort und Stelle. -> dict."""
    _einst_setzen(None)
    _frischer_start()
    D, z, d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    lst = z["w"]["liste_auftraege"]
    alt_uhr = D.time
    try:
        jetzt = time.time()
        with d.sperre:
            d.verlauf[:] = [{"methode": "get_document_info", "ok": True,
                             "dauer_s": 0.12, "beendet": jetzt - 3000 + i}
                            for i in range(47)]
            d.verlauf += [
                {"methode": "execute_cwapi3d", "beschreibung": "Wand Nord",
                 "ok": True, "dauer_s": 2.5, "paket": [3, 8],
                 "beendet": jetzt - 600},
                {"methode": "execute_cwapi3d", "beschreibung": "Dach",
                 "ok": False, "dauer_s": 0.4, "beendet": jetzt - 30},
                {"methode": "neu_zeichnen", "ok": True, "dauer_s": 0.05,
                 "beendet": jetzt - 5}]
        D._auffrischen(z)
        texte = [lst.item(i).text() for i in range(lst.count())]
        m["texte"] = texte[:4]
        # Seit K9 steht das Symbol als Ikone der Zeile (aus derselben Tabelle).
        m["symbole"] = [D._auftrag_symbol(v) for v in
                        list(reversed(d.verlauf))[:4]]
        m["ikonen"] = [not lst.item(i).icon().isNull() for i in range(4)]
        m["tipps"] = [lst.item(i).toolTip() for i in range(3)]
        m["technik_sichtbar"] = [t for t in texte if "execute_cwapi3d" in t
                                 or "get_document_info" in t
                                 or "neu_zeichnen" in t]
        # -- Volle Liste (VERLAUF_MAX): ein neuer Auftrag erscheint oben ------
        lst.setCurrentRow(2)
        with d.sperre:
            d.verlauf.append({"methode": "get_document_info", "ok": True,
                              "dauer_s": 0.1, "beendet": time.time()})
            del d.verlauf[:-50]
        D._auffrischen(z)
        m["voll"] = (lst.count(), lst.item(0).text(),
                     lst.item(0).toolTip().split(" ·")[0])
        # -- Zeit laeuft: Texte an Ort und Stelle, die Auswahl bleibt ----------
        lst.setCurrentRow(2)
        vorher = lst.item(2).text()
        D.time = _Uhr(400)
        D._auffrischen(z)
        m["zeit"] = (vorher, lst.item(2).text(), lst.currentRow())
        # -- Der laufende Auftrag in der Kopfkarte: lesbar und maskiert -------
        echt_status = d.status
        d.status = lambda: dict(echt_status(), auftrag={
            "methode": "execute_cwapi3d", "paket": [3, 8],
            "beschreibung": "<img src=x> Wand", "laufzeit_s": 4.2})
        D._auffrischen(z)
        lb = z["w"]["briefkasten_laeuft_text"]
        from PyQt6.QtCore import Qt as _Qt
        m["kopf"] = (lb.text(), lb.toolTip(),
                     lb.textFormat() == _Qt.TextFormat.PlainText,
                     not z["w"]["briefkasten_laeuft"].isHidden())
        d.status = echt_status
    finally:
        D.time = alt_uhr
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_lesbarer_chat():
    """L71 (Wunsch 2026-09-27): die Antwort in eigener Blase mit ✦, die
    eigene Nachricht rechts; Werkzeuge als EINE graue Zeile, aufklappbar,
    mit menschlichen Namen (der technische nur im Tooltip); Zeitlinien nur
    nach einer Pause, relativ und immer groeber; folgt dem Neuesten, ausser
    der Nutzer hat hochgerollt ("↓ Neu"); die Auftragsliste ebenso."""
    try:
        m = _lesbar_lauf()
        pruefe("L71 Nachricht, EINE Zeile fuer drei Schritte, Antwort, "
               "Nachricht (der Schluss ist keine Zeile mehr, 2026-09-28)",
               m["texte"][:2] == [
                   "Du:  Zeichne eine Wand von vier Metern auf der Achse A, mit Schwelle und Rähm",
                   "3 Schritte in Cadwork · 1 hat nicht geklappt"]
               and m["texte"][2] == "Die Wand steht."
               and m["texte"][3] == "Du:  Danke" and len(m["texte"]) == 4,
               m["texte"])
        zeiten = [t for t in m["mit_zeit"] if t not in m["texte"]]
        pruefe("L71 Zeitlinien nur nach einer Pause: am Anfang (vor zwei "
               "Stunden -> 'heute'/'gestern' mit Uhrzeit) und vor der neuen "
               "Nachricht ('gerade eben')", len(zeiten) == 2
               and zeiten[0].split(" ")[0] in ("heute", "gestern")
               and zeiten[1] == "gerade eben", m["mit_zeit"])
        pruefe("L71 zugeklappt steht nur die graue Zeile (Winkel nach "
               "rechts als Symbol)",
               m["zu"] is not None and m["zu"][0]
               and m["zu"][1].startswith("3 Schritte")
               and m["zu"][2] == "chevron-right", m["zu"])
        auf = m.get("auf") or (None, None, [], [])
        pruefe("L71 ein Klick klappt auf: menschliche Namen, der Fehler als "
               "'Hat nicht geklappt', je mit Symbol", auf[0] is False
               and auf[1] == "chevron-down"
               and auf[2] == ["Dokument angeschaut",
                              "Hat nicht geklappt, versucht es anders",
                              "Wand Nord"]
               and auf[4] == ["file-text", "triangle-alert", "hammer"],
               (auf[:3], auf[4:]))
        pruefe("L71 technische Namen nur im Tooltip",
               not [t for t in m["sichtbar"] if "mcp__" in t
                    or "execute_cadwork" in t or "get_document_info" in t]
               and any((MCP + "execute_cadwork_command") in t
                       for t in auf[3])
               and any("automatisch erlaubt" in t for t in auf[3]), m)
        pruefe("L71 Eingaben der KI im Tooltip maskiert, der Kopf ist "
               "Klartext", m["klartext"][0] is True and m["klartext"][1]
               and all("&lt;b&gt;fett" in t and "<b>" not in t
                       for t in m["klartext"][1]), m["klartext"])
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_tipp_klartext", lambda s_: isinstance(s_, ast.Return),
            "return str(text or '')")))
        pruefe("L71 KONTROLLE: ohne Maskieren steht '<b>' roh im Tooltip",
               k["treffer"] == [1]
               and any("<b>" in t for t in k["klartext"][1]), k["klartext"])
        links, rechts, breite, name = m["ich_lage"]
        pruefe("L71 die eigene Nachricht steht rechts in eigener Blase",
               name == "blase_ich" and rechts >= breite - 12
               and links > breite * 0.4, m["ich_lage"])
        pruefe("L71 eine lange eigene Nachricht nimmt die Breite (bis gut "
               "vier Fuenftel), statt nach wenigen Worten umzubrechen",
               m["ich_lang"][0] >= m["ich_lang"][1] * 0.6
               and m["ich_lang"][0] <= m["ich_lang"][1] * 0.85, m["ich_lang"])
        pruefe("L71 die Antwort links in eigener Blase, mit dem Logo des "
               "Plugins (scharf, doppelte Aufloesung) statt ✦",
               m["ki_lage"][0] < 40 and m["ki_lage"][1] == "logo"
               and m["ki_lage"][2] and m["ki_lage"][3] == "blase_ki"
               and (m["ki_lage"][4] or 0) >= 2, m["ki_lage"])
        pruefe("L71 die Zeit laeuft: 'gerade eben' wird 'vor 7 min', an "
               "Ort und Stelle", m["zeit_weiter"] == ("gerade eben",
                                                      "vor 7 min", True),
               m["zeit_weiter"])
        # KONTROLLEN
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_qt_klassen", lambda s_: isinstance(s_, ast.Expr)
            and ast.unparse(s_) == "lay.addStretch(1)")))
        # (Ohne den Platzhalter waechst die Blase bis zu ihrer Hoechstbreite
        # und steht in der Mitte — gemessen 2026-09-28: 46..388 von 434.)
        pruefe("L71 KONTROLLE: ohne den Platzhalter links steht die eigene "
               "Nachricht nicht mehr rechts", k["treffer"] == [1]
               and k["ich_lage"][1] < k["ich_lage"][2] - 12, k["ich_lage"])
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_qt_klassen", lambda s_: isinstance(s_, ast.If)
            and "minimumWidth" in ast.unparse(s_.test))))
        pruefe("L71 KONTROLLE: ohne Mindestbreite bricht die lange Nachricht "
               "schmal um", k["treffer"] == [1]
               and k["ich_lang"][0] < k["ich_lang"][1] * 0.6, k["ich_lang"])
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_verlauf_bloecke", lambda s_: isinstance(s_, ast.If)
            and ast.unparse(s_.test) == "gruppe is None",
            'gruppe = {"art": "schritte", "schluessel": "s%d" % i, '
            '"schritte": []}\nbloecke.append(gruppe)')))
        pruefe("L71 KONTROLLE: ohne Gruppe steht jeder Schritt einzeln da",
               k["treffer"] == [1] and len(k["texte"]) > 5, k["texte"])
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_verlauf_bloecke", _beginnt("luecke = "), "luecke = True")))
        pruefe("L71 KONTROLLE: ohne die Pause eine Zeitlinie vor jedem "
               "Eintrag", k["treffer"] == [1]
               and len(k["mit_zeit"]) - len(k["texte"]) > 2, k["mit_zeit"])
        k = _lesbar_lauf(lambda: _mutant(_anweisungen(
            "_verlauf_zeigen", _beginnt("marke = (wer"),
            "marke = (wer, len(ereignisse), 0, paket, laeuft)")))
        pruefe("L71 KONTROLLE: ohne die Zeit in der Marke bleibt 'gerade "
               "eben' stehen", k["treffer"] == [1]
               and k["zeit_weiter"][1] == "gerade eben", k["zeit_weiter"])

        m = _lauf_im_zug()
        pruefe("L71 im Zug nennt die Zeile den laufenden Schritt mit Paket",
               m["kopf"] == "2 Schritte in Cadwork · Zeichnet (Paket 3 "
               "von 8)", m["kopf"])
        pruefe("L71 die Gruppe waechst an Ort und Stelle und bleibt "
               "aufgeklappt; alte Eintraege werden nicht neu gebaut",
               m["waechst"][0] and m["waechst"][1] is False
               and m["waechst"][2] == ["Dokument angeschaut",
                                       "In Paketen gezeichnet",
                                       "Ansicht neu gezeichnet …"]
               and m["waechst"][3], m["waechst"])
        pruefe("L71 folgt dem Neuesten (ganz unten, kein '↓ Neu')",
               m["unten"][1] > 0 and m["unten"][0] == m["unten"][1]
               and m["unten"][2], m["unten"])
        pruefe("L71 hochgerollt: die Stelle bleibt, '↓ Neu' erscheint",
               m["oben"][0] == 0 and m["oben"][1] > 0 and not m["oben"][2],
               m["oben"])
        pruefe("L71 '↓ Neu' rollt ans Ende und verschwindet",
               m["neu_klick"][0] == m["neu_klick"][1] and m["neu_klick"][2],
               m["neu_klick"])
        k = _lauf_im_zug(lambda: _mutant(_anweisungen(
            "_laufendes_paket", lambda s_: isinstance(s_, ast.For))))
        pruefe("L71 KONTROLLE: ohne den Status des Kerns kein Paket",
               k["treffer"] == [1] and "Paket 3" not in k["kopf"], k["kopf"])
        k = _lauf_im_zug(lambda: _mutant(_anweisungen(
            "_verlauf_zeigen", lambda s_: isinstance(s_, ast.If)
            and "_wer" in ast.unparse(s_.test),
            "ver._wer = wer\nver.leeren()")))
        pruefe("L71 KONTROLLE: alles neu gebaut -> zugeklappt, neue Blasen",
               k["treffer"] == [1] and (k["waechst"][1] is not False
                                        or not k["waechst"][3]), k["waechst"])
        k = _lauf_im_zug(lambda: _mutant(_anweisungen(
            "_qt_klassen", lambda s_: isinstance(s_, ast.If)
            and ast.unparse(s_.test) == "self.folgen"
            and "setValue(bis)" in ast.unparse(s_))))
        pruefe("L71 KONTROLLE: ohne Folgen bleibt der Verlauf oben stehen",
               k["treffer"] == [1] and k["unten"][0] < k["unten"][1],
               k["unten"])
        k = _lauf_im_zug(lambda: _mutant(_anweisungen(
            "_qt_klassen", lambda s_: isinstance(s_, ast.If)
            and ast.unparse(s_.test) == "neu and (not self.folgen)")))
        pruefe("L71 KONTROLLE: ohne '↓ Neu' merkt man Neues oben nicht",
               k["treffer"] == [1] and k["oben"][2], k["oben"])

        m = _auftraege_lauf()
        pruefe("L71 Auftragsliste lesbar: was, wann; das Neueste oben",
               m["texte"][:3] == [
                   "Ansicht neu gezeichnet · gerade eben",
                   "Dach · hat nicht geklappt · gerade eben",
                   "Wand Nord (Paket 3 von 8) · vor 10 min"]
               and m["texte"][3] == "Dokument angeschaut · vor 45 min"
               and m["symbole"] == ["refresh-cw", "triangle-alert", "hammer",
                                    "file-text"], (m["texte"], m["symbole"]))
        pruefe("L71 Auftragsliste: Methode und Dauer nur im Tooltip",
               not m["technik_sichtbar"]
               and m["tipps"][2].startswith("execute_cwapi3d · 2.50 s")
               and "Paket 3/8" in m["tipps"][2], m["tipps"])
        pruefe("L71 volle Liste: der neue Auftrag steht trotzdem oben",
               m["voll"] == (50, "Dokument angeschaut · gerade eben",
                             "get_document_info"),
               m["voll"])
        pruefe("L71 die Zeitangaben laufen an Ort und Stelle, die Auswahl "
               "bleibt", m["zeit"][0].endswith("gerade eben")
               and m["zeit"][1].endswith("vor 7 min")
               and m["zeit"][2] == 2, m["zeit"])
        pruefe("L71 'Läuft jetzt' im Briefkasten (K12, vorher die "
               "Kopfkarte): der laufende Auftrag lesbar (Paket, Dauer), die "
               "Beschreibung der KI als Klartext (nie Rich Text), die "
               "Methode nur im Tooltip",
               m["kopf"][0] == "<img src=x> Wand (Paket 3 von 8) · 4 s"
               and m["kopf"][2] and m["kopf"][3]
               and "execute_cwapi3d" in m["kopf"][1], m["kopf"])
        k = _auftraege_lauf(lambda: _mutant(_anweisungen(
            "_briefkasten_bauen", _beginnt("laeuft_text.setTextFormat("))))
        pruefe("L71 KONTROLLE: ohne Klartext-Format liest Qt '<img' als "
               "Rich Text", k["treffer"] == [1] and k["kopf"][2] is False,
               k["kopf"])
        k = _auftraege_lauf(lambda: _mutant(_anweisungen(
            "_auffrischen", _beginnt("marke_a = "),
            "marke_a = len(verlauf)")))
        pruefe("L71 KONTROLLE: nur die Laenge gemerkt -> bei voller Liste "
               "traegt der neue Auftrag den Tooltip des alten",
               k["treffer"] == [1] and k["voll"][2] != "get_document_info",
               k["voll"])
        k = _auftraege_lauf(lambda: _mutant(_anweisungen(
            "_auffrischen", lambda s_: isinstance(s_, ast.For)
            and "item.setText(text)" in ast.unparse(s_))))
        pruefe("L71 KONTROLLE: ohne das Nachfuehren bleibt 'gerade eben'",
               k["treffer"] == [1] and k["zeit"][1].endswith("gerade eben"),
               k["zeit"])
    finally:
        _frischer_start()


# --- L73/L74: Feinschliff 2026-09-28 --------------------------------------

#: Was bis zum Feinschliff ueber dem Gespraech stand (Technik).
TECHNIK_ZEILEN = ("Claude Code (Abo)", "ein Agent auf diesem Rechner",
                  "läuft ·", "bereit —", "Cadwork-Werkzeuge:", "Fachwissen:",
                  "Modus:")


def _sichtbare_texte(wurzel, ausser=()):
    """Sichtbare QLabel-Texte unter `wurzel`, ohne die unter `ausser`."""
    from PyQt6.QtWidgets import QLabel
    return [lb.text() for lb in wurzel.findChildren(QLabel)
            if lb.isVisibleTo(wurzel) and lb.text()
            and not any(a.isAncestorOf(lb) for a in ausser)]


def _feinschliff_lauf(laden=None):
    """Chatfenster mit laufendem Chat: was ueber dem Gespraech steht, die
    Statuszeile in vier Lagen, das "…", der Ordner-Hinweis. -> dict."""
    from PyQt6.QtCore import QPoint
    _einst_setzen(None)
    _frischer_start()
    D, z, d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    try:
        _chat_ziehen(D, z, 460, 680)
        chat = z["chat"]
        chat.update(an=True, anbieter="claude", kurzname="Claude",
                    modell="claude-sonnet-5", werkzeuge_da=True, wissen=True,
                    freigaben=[], laeuft_zug=False, stand=chat.get(
                        "stand", 0) + 1,
                    ereignisse=[{"art": "ich", "text": "Hallo"},
                                {"art": "text", "text": "Grüezi."}])
        z["chat_gezeigt"] = None
        _warte_qt(D, z, lambda: w["chat_verlauf"].count() >= 2, 2)
        gespraech = w["chat_stapel"].widget(0)
        texte = _sichtbare_texte(gespraech, [w["chat_verlauf"]])
        m["technik_im_gespraech"] = [t for t in texte
                                     if any(x in t for x in TECHNIK_ZEILEN)]
        seite = w["chat_einst_seite"]
        m["technik_auf_seite"] = (
            seite.isAncestorOf(w["chat_lage"]) and seite.isAncestorOf(
                w["chat_wer"]) and seite.isAncestorOf(w["chat_art"]),
            w["chat_lage"].text())
        m["status_gut"] = (w["chat_status"].isHidden(),
                           w["chat_status"].text())
        # Neuer Chat / Beenden oben rechts, in der Zeile des Ordners
        neu, ende = w["chat_neu"], w["chat_ende"]
        oben = gespraech.mapFromGlobal(neu.mapToGlobal(QPoint(0, 0)))
        ordner = gespraech.mapFromGlobal(
            w["chat_ordner"].mapToGlobal(QPoint(0, 0)))
        m["knoepfe"] = (neu.accessibleName(), ende.accessibleName(),
                        not ende.isHidden(), oben.x() > ordner.x(),
                        abs(oben.y() - ordner.y()) < 12,
                        oben.x() + neu.width() > gespraech.width() * 0.8)
        # -- Statuszeile: vier Lagen ------------------------------------------
        lagen = {}
        chat.update(werkzeuge_da=False, stand=chat["stand"] + 1)
        D._chat_zeichnen(z)
        lagen["werkzeuge_fehlen"] = (w["chat_status"].isHidden(),
                                     w["chat_status"].text(),
                                     w["chat_status"].toolTip())
        chat.update(werkzeuge_da=None, stand=chat["stand"] + 1)
        D._chat_zeichnen(z)
        lagen["werkzeuge_unbekannt"] = (w["chat_status"].isHidden(),
                                        w["chat_status"].text())
        chat.update(werkzeuge_da=True, stand=chat["stand"] + 1)
        d.zustand = "stopped"
        D._chat_zeichnen(z)
        lagen["nicht_verbunden"] = (w["chat_status"].isHidden(),
                                    w["chat_status"].text(),
                                    w["chat_status"].toolTip())
        d.zustand = "ready"
        D._chat_zeichnen(z)
        lagen["wieder_gut"] = w["chat_status"].isHidden()
        m["lagen"] = lagen
        # -- "…" an der Stelle der naechsten Antwort --------------------------
        chat.update(laeuft_zug=True, stand=chat["stand"] + 1)
        _warte_qt(D, z, lambda: bool(w["chat_verlauf"].widgets("tippt")), 2)
        tippt = w["chat_verlauf"].widgets("tippt")
        m["tippt"] = None
        if tippt:
            b = tippt[0]
            vorher = b.text.text()
            ende_t = time.monotonic() + 1.5
            while time.monotonic() < ende_t and b.text.text() == vorher:
                _APP.processEvents()
                time.sleep(0.05)
            m["tippt"] = (w["chat_verlauf"].teile[-1][1] is b,
                          b.isVisibleTo(w["chat_verlauf"]), b.toolTip(),
                          vorher != b.text.text(), w["chat_verlauf"].count())
        chat.update(freigaben=[{"id": "k1", "werkzeug": "Bash", "name": "Bash",
                                "eingabe": {"command": "dir"}, "offen": True}],
                    stand=chat["stand"] + 1)
        _warte_qt(D, z, lambda: w["chat_verlauf"].widgets("tippt") and
                  "Freigabe" in w["chat_verlauf"].widgets("tippt")[0]
                  .toolTip(), 2)
        t2 = w["chat_verlauf"].widgets("tippt")
        m["tippt_freigabe"] = t2[0].toolTip() if t2 else None
        chat.update(freigaben=[], laufender_text="Ich zeichne jetzt",
                    stand=chat["stand"] + 1)
        _warte_qt(D, z, lambda: not w["chat_verlauf"].widgets("tippt"), 2)
        m["tippt_beim_schreiben"] = bool(w["chat_verlauf"].widgets("tippt"))
        chat.update(laufender_text="", laeuft_zug=False,
                    stand=chat["stand"] + 1)
        _warte_qt(D, z, lambda: not w["chat_verlauf"].widgets("tippt"), 2)
        m["tippt_danach"] = bool(w["chat_verlauf"].widgets("tippt"))
        # -- Ordner-Aufklapper: Hinweis nur im laufenden Chat ------------------
        from PyQt6.QtWidgets import QLabel

        def ordner_hinweis():
            D._ordner_aufklappen(z)
            auf = w["chat_ordner_auf"]
            da = any("nächsten Chat" in lb.text()
                     for lb in auf.findChildren(QLabel) if not lb.isHidden())
            auf.hide()
            return da
        m["ordner_im_chat"] = ordner_hinweis()
        chat.update(an=False, stand=chat["stand"] + 1)
        D._chat_zeichnen(z)
        m["ordner_ohne_chat"] = ordner_hinweis()
    finally:
        z["chat"].update(an=False, laeuft_zug=False)
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_feinschliff():
    """L73 (Feinschliff 2026-09-28): ueber dem Gespraech keine Technik mehr
    (sie steht auf ⚙ unter "Technik-Details"); eine Statuszeile nur, wenn
    etwas nicht stimmt; "Neuer Chat"/"Beenden" als ruhige Zeichen oben
    rechts; "…" im Verlauf, solange die KI arbeitet; "gilt ab dem nächsten
    Chat" nur in den Aufklappern."""
    try:
        m = _feinschliff_lauf()
        pruefe("L73 ueber dem Gespraech keine Technikzeile (laufender Chat, "
               "alles in Ordnung)", m["technik_im_gespraech"] == [],
               m["technik_im_gespraech"])
        pruefe("L73 Wer, Art und Lage stehen auf den Chat-Einstellungen "
               "(Technik-Details), die Lage mit Modell und Werkzeugen",
               m["technik_auf_seite"][0]
               and "claude-sonnet-5" in m["technik_auf_seite"][1]
               and "Cadwork-Werkzeuge: ja" in m["technik_auf_seite"][1], m)
        pruefe("L73 ist alles in Ordnung, steht keine Statuszeile da",
               m["status_gut"] == (True, ""), m["status_gut"])
        pruefe("L73 'Neuer Chat' und 'Beenden' als Zeichen oben rechts in der "
               "Zeile des Ordners, mit Namen", m["knoepfe"] == (
                   "Neuer Chat", "Beenden", True, True, True, True),
               m["knoepfe"])
        lagen = m["lagen"]
        pruefe("L73 Statuszeile: Cadwork-Werkzeuge fehlen, der Tooltip sagt "
               "warum", lagen["werkzeuge_fehlen"][0] is False
               and lagen["werkzeuge_fehlen"][1] == "Cadwork-Werkzeuge fehlen"
               and "OPEN_MCP_CAD_PYTHON" in lagen["werkzeuge_fehlen"][2],
               lagen["werkzeuge_fehlen"])
        pruefe("L73 Statuszeile: solange unbekannt (Server startet) nichts",
               lagen["werkzeuge_unbekannt"] == (True, ""),
               lagen["werkzeuge_unbekannt"])
        pruefe("L73 Statuszeile: nicht verbunden, danach wieder weg",
               lagen["nicht_verbunden"][:2] == (False, "Nicht verbunden")
               and "verbinden" in lagen["nicht_verbunden"][2]
               and lagen["wieder_gut"], lagen)
        pruefe("L73 '…' als letzter Eintrag im Verlauf, die Punkte laufen, "
               "der Tooltip sagt, was die KI tut; es zaehlt nicht als Eintrag",
               m["tippt"] is not None and m["tippt"][0] and m["tippt"][1]
               and m["tippt"][2] == "Claude arbeitet" and m["tippt"][3]
               and m["tippt"][4] == 2, m["tippt"])
        pruefe("L73 '…' wartet auf die Freigabe, verschwindet, sobald die "
               "Antwort sichtbar waechst und wenn der Zug endet",
               m["tippt_freigabe"] == "wartet auf deine Freigabe"
               and not m["tippt_beim_schreiben"] and not m["tippt_danach"], m)
        pruefe("L73 'Ein anderer Ordner gilt ab dem nächsten Chat' steht im "
               "Ordner-Aufklapper nur im laufenden Chat",
               m["ordner_im_chat"] and not m["ordner_ohne_chat"],
               (m["ordner_im_chat"], m["ordner_ohne_chat"]))
        # KONTROLLEN
        k = _feinschliff_lauf(lambda: _mutant(_anweisungen(
            "_tab_chat", lambda s: isinstance(s, ast.Expr)
            and ast.unparse(s) == "tkl.addWidget(lb)", "kl.addWidget(lb)")))
        pruefe("L73 KONTROLLE: Wer/Art/Lage wieder im Gespraech -> gefunden",
               k["treffer"] == [1] and k["technik_im_gespraech"],
               (k["treffer"], k["technik_im_gespraech"]))
        k = _feinschliff_lauf(lambda: _mutant(_test_ersetzen(
            "_status_text", "an and chat.get('werkzeuge_da') is False",
            "an and (not chat.get('werkzeuge_da'))")))
        pruefe("L73 KONTROLLE: 'fehlt' schon, solange unbekannt -> Fehlalarm "
               "bei jedem Start", k["treffer"] == [1]
               and k["lagen"]["werkzeuge_unbekannt"][0] is False,
               k["lagen"]["werkzeuge_unbekannt"])
        k = _feinschliff_lauf(lambda: _mutant(_anweisungen(
            "_verlauf_bloecke", lambda s: isinstance(s, ast.If)
            and ast.unparse(s.test) == "tippt")))
        pruefe("L73 KONTROLLE: ohne den Block kein '…'",
               k["treffer"] == [1] and k["tippt"] is None, k["tippt"])
        k = _feinschliff_lauf(lambda: _mutant(_anweisungen(
            "_qt_klassen", lambda s: isinstance(s, ast.Expr)
            and ast.unparse(s) == "self._uhr.start()")))
        pruefe("L73 KONTROLLE: ohne Zeitgeber stehen die Punkte still",
               k["treffer"] == [1] and k["tippt"] is not None
               and not k["tippt"][3], k["tippt"])
        k = _feinschliff_lauf(lambda: _mutant(_test_ersetzen(
            "_ordner_aufklappen", "(z.get('chat') or {}).get('an')", "True")))
        pruefe("L73 KONTROLLE: Hinweis immer -> auch ohne Chat",
               k["treffer"] == [1] and k["ordner_ohne_chat"],
               k["ordner_ohne_chat"])
    finally:
        _frischer_start()


def _cli_tot_lauf(laden=None):
    """L74: die erste Nachricht geht an ein lebendes CLI (Attrappe), dann
    stirbt es; die zweite kommt nicht an. -> dict."""
    _einst_setzen(None)
    _frischer_start()
    D, z, _d = aufbauen(D=laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    try:
        with _ChatStartAttrappe(D, z) as att:
            m["erste"] = _senden_klick(D, z, "erste")
            proc = att.proc
            m["angekommen"] = len(proc.zeilen)
            proc.tot = True
            m["zweite"] = _senden_klick(D, z, "zweite")
            chat = z["chat"]
            D._chat_zeichnen(z)
            m["danach"] = (_meldung(z),
                           [e.get("text") for e in chat.get("ereignisse")
                            or () if e.get("art") == "ich"],
                           bool(chat.get("laeuft_zug")),
                           w["chat_neu"].isEnabled(), len(proc.zeilen))
    finally:
        z["chat"].update(an=False, laeuft_zug=False)
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_totes_cli():
    """L74 (aelterer Befund, Gegenpruefung K7): ein Senden an ein schon totes
    CLI leerte das Feld — die Nachricht war weg. Jetzt bleibt der Text, die
    Zeile an der Eingabe sagt es, im Verlauf steht nichts Falsches."""
    try:
        m = _cli_tot_lauf()
        pruefe("L74 Vorbedingung: die erste Nachricht kommt an (Feld leer)",
               m["erste"] == "" and m["angekommen"] == 1, m)
        pruefe("L74 totes CLI: der Text bleibt, die Zeile sagt 'Nicht "
               "gesendet', im Verlauf nur die erste, kein Zug laeuft, 'Neuer "
               "Chat' geht", m["zweite"] == "zweite"
               and "Nicht gesendet" in m["danach"][0]
               and m["danach"][1] == ["erste"] and not m["danach"][2]
               and m["danach"][3] and m["danach"][4] == 1, m)
        k = _cli_tot_lauf(lambda: _mutant(_anweisungen(
            "_chat_senden", lambda s: isinstance(s, ast.If)
            and ast.unparse(s.test) == "gesendet is False")))
        pruefe("L74 KONTROLLE: ohne die Pruefung leert sich das Feld (der "
               "alte Fehler)", k["treffer"] == [1] and k["zweite"] == "",
               (k["treffer"], k["zweite"]))
    finally:
        _frischer_start()


def zelle_ports_ausserhalb():
    """Kein Port dieses Gates lag im Cadwork-Bereich — gemessen an allem,
    was belegt, von `_steckplatz_reservieren` reserviert oder vom
    Chat-Dienst bedient wurde. Laeuft deshalb als letzte Zelle."""
    im_bereich = sorted(set(_VERGEBEN) & _CADWORK_PORTS)
    pruefe("L21 kein Testport im Cadwork-Bereich",
           _ausserhalb(_VERGEBEN),
           "%d Ports, im Bereich: %s" % (len(set(_VERGEBEN)), im_bereich))
    pruefe("L21 KONTROLLE: ein Port aus dem Kernbereich faellt auf",
           not _ausserhalb(_VERGEBEN + sorted(_CADWORK_PORTS)[:1]),
           "sonst ist der Bereich leer und L21 misst nichts")
    try:
        s, p = _belegen(verboten=range(1, 65536))
        s.close()
        k = "bekam %d" % p
    except RuntimeError:
        k = "wirft"
    pruefe("L21 KONTROLLE: ist alles verboten, gibt _belegen auf", k == "wirft",
           "%s — sonst prueft _belegen den Bereich gar nicht" % k)


# --- L72: Gegenpruefung 2026-09-28 -------------------------------------------

def _wechsel_lauf(ziel, laden=None):
    """Ein Chat (Schleifen-Attrappe) im Modus "Fragen" mit drei offenen
    Karten: ein Cadwork-Befehl, ein Lesen AUSSERHALB des Ordners, ein
    Befehl am Rechner. Dann im Aufklapper `ziel` gewaehlt. -> dict."""
    from PyQt6.QtWidgets import QPushButton
    D, z, _d = _neustart(laden)
    w = z["w"]
    schleife = _SchleifenAttrappe()
    cad = "mcp__open-mcp-cad__execute_cadwork_command"
    karten = [
        {"id": "k1", "werkzeug": cad, "name": "execute_cadwork_command",
         "eingabe": {"code": "x = 1"}, "offen": True},
        {"id": "k2", "werkzeug": "Read", "name": "Read", "draussen": True,
         "eingabe": {"file_path": "C:/anderswo/zugang.txt"}, "offen": True},
        {"id": "k3", "werkzeug": "Bash", "name": "Bash",
         "eingabe": {"command": "dir"}, "offen": True}]
    z["chat"].update(an=True, laeuft_zug=True, schleife=schleife,
                     freigaben=karten, modus="fragen", stand=5,
                     ereignisse=[{"art": "ich", "text": "zeichne"}])
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        _warte_qt(D, z, lambda: not w["chat_freigabe"].isHidden(), 2)
        m["sitzung_knoepfe"] = len([
            b for b in w["chat_freigabe"].findChildren(QPushButton)
            if b.text() == "Für diese Sitzung nicht mehr fragen"
            and not b.isHidden()])
        m["gefunden"] = _modus_klick(z, ziel)
        m["antworten"] = list(schleife.antworten)
        m["modus"] = z["chat"].get("modus")
    finally:
        z["chat"].update(an=False, laeuft_zug=False, schleife=None,
                         freigaben=[])
    return m


def _einfuegen_lauf(laden=None):
    """Einfuegen in die Eingabe, waehrend `_anhang_aus_mime` wirft.
    -> (wirft beim Einfuegen?, Text im Feld, Treffer)."""
    from PyQt6.QtCore import QMimeData
    D, z, _d = _neustart(laden)
    feld = z["w"]["chat_eingabe"]

    def wirft(*_a):
        raise RuntimeError("Probe L72")
    D._anhang_aus_mime = wirft
    mime = QMimeData()
    mime.setText("nur Text")
    try:
        feld.insertFromMimeData(mime)
        ergebnis = False
    except RuntimeError:
        ergebnis = True
    text = feld.toPlainText()
    feld.clear()
    return ergebnis, text, getattr(D, "_mutant_treffer", None)


def _gross_lauf(laden=None):
    """Senden mit Anhaengen ueber der Gesamtgrenze. -> (gesendet, Feld,
    Meldung, Anhaenge, Treffer)."""
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    gesendet = []
    try:
        with _ChatStartAttrappe(D, z):
            mod = sys.modules[_ChatStartAttrappe.NAME]

            def senden(chat, text, anhaenge=None):
                gesendet.append((text, len(anhaenge or ())))
            mod.senden = senden
            z["anhaenge"] = [{"id": 1, "name": "riesig.png",
                              "status": "bereit", "art": "bild",
                              "mime": "image/png",
                              "b64": "A" * (D.ANHAENGE_GESAMT_MAX + 1)}]
            rest = _senden_klick(D, z, "schau")
            return (gesendet, rest, _meldung(z), len(z.get("anhaenge") or ()),
                    getattr(D, "_mutant_treffer", None))
    finally:
        _einst_setzen(None)


def zelle_gegenpruefung_0928():
    """L72 (Gegenpruefung 2026-09-28): ein Wechsel auf "Nur lesen" lehnt
    offene Karten ab, die dieser Modus verbietet; "Für diese Sitzung" steht
    nicht an einem Aufruf ausserhalb des Ordners; ein Fehler beim Einfuegen
    laeuft nicht aus der virtuellen Methode (in Cadwork: qFatal); Anhaenge
    ueber der Gesamtgrenze lassen Text und Anhaenge stehen."""
    try:
        m = _wechsel_lauf("nur_lesen")
        pruefe("L72 Wechsel auf 'Nur lesen' mitten im Chat: alle drei offenen "
               "Karten (Cadwork, Lesen draussen, Befehl) sind abgelehnt",
               m["gefunden"] and m["modus"] == "nur_lesen"
               and m["antworten"] == [("k1", False), ("k2", False),
                                      ("k3", False)], m)
        pruefe("L72 'Für diese Sitzung' steht an Cadwork und Befehl, NICHT "
               "am Lesen ausserhalb des Ordners (das fragt jedes Mal)",
               m["sitzung_knoepfe"] == 2, m["sitzung_knoepfe"])
        k = _wechsel_lauf("cadwork_frei")
        pruefe("L72 KONTROLLE: ein Wechsel auf 'Cadwork frei' lehnt nichts ab "
               "(die Karten bleiben beim Nutzer)",
               k["gefunden"] and k["antworten"] == [], k)
        M = _mutant(_anweisungen(
            "_modus_waehlen", lambda s: "_karten_nach_modus" in ast.unparse(s)))
        k = _wechsel_lauf("nur_lesen", M)
        pruefe("L72 KONTROLLE: ohne _karten_nach_modus bleiben die Karten "
               "offen (ein Klick liesse den Befehl laufen)",
               k["treffer"] == [1] and k["antworten"] == [], k)
        # Die Bedingung ohne die Anfrage (also ohne `draussen`), wie vor
        # der Gegenpruefung: nur der Modus und die Gewaehrung.
        M = _mutant(_test_ersetzen(
            "_freigabe_karte",
            "werkzeug_f and C.chat_entscheiden(z.get('chat'), werkzeug_f, "
            "anfrage_f) == 'fragen' and (C.entscheiden(C.modus_von("
            "z.get('chat')), werkzeug_f, anfrage_f, {werkzeug_f}) == 'ja')",
            "werkzeug_f and C.modus_von(z.get('chat')) == 'fragen' and "
            "C.entscheiden(C.modus_von(z.get('chat')), werkzeug_f, None, "
            "{werkzeug_f}) == 'ja'"))
        k = _wechsel_lauf("nur_lesen", M)
        pruefe("L72 KONTROLLE: ohne die Ausnahme fuer 'draussen' stuende der "
               "Knopf an allen drei Karten", k["treffer"] == [1]
               and k["sitzung_knoepfe"] == 3, k)

        wirft, text, _t = _einfuegen_lauf()
        pruefe("L72 wirft das Einfuegen innen, laeuft der Fehler nicht aus "
               "insertFromMimeData, und der Text kommt als Text an",
               not wirft and text == "nur Text", (wirft, text))
        M = _mutant(_aufruf_umbenennen("_tab_chat", "_anhang_aus_mime_sicher",
                                       "_anhang_aus_mime"))
        wirft, _text, treffer = _einfuegen_lauf(M)
        pruefe("L72 KONTROLLE: ohne die Huelle liefe er aus der virtuellen "
               "Methode (in Cadwork qFatal)", treffer == [1] and wirft,
               (treffer, wirft))

        gesendet, rest, meldung, anhaenge, _t = _gross_lauf()
        pruefe("L72 Anhaenge zusammen ueber der Grenze: nichts gesendet, "
               "Text und Anhang bleiben, die Zeile sagt warum",
               gesendet == [] and rest == "schau" and anhaenge == 1
               and "zu gross" in meldung, (gesendet, rest, meldung))
        M = _mutant(_anweisungen(
            "_chat_senden", lambda s: isinstance(s, ast.If)
            and ast.unparse(s.test) == "zu_gross"))
        gesendet, rest, _m, _a, treffer = _gross_lauf(M)
        pruefe("L72 KONTROLLE: ohne die Gesamtgrenze ginge alles hinaus",
               treffer == [1] and gesendet == [("schau", 1)], (treffer,
                                                              gesendet))
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L75: Hinweis "Nur lesen hat abgelehnt" (Rueckmeldung 2026-09-28) ------

def _symbol_farbe(knopf):
    """Die mittlere Farbe der deckenden Pixel im Symbol eines Knopfs
    (r, g, b) — oder None ohne Symbol."""
    ikone = knopf.icon()
    if ikone.isNull():
        return None
    bild = ikone.pixmap(16, 16).toImage()
    summe, n = [0, 0, 0], 0
    for y in range(bild.height()):
        for x in range(bild.width()):
            f = bild.pixelColor(x, y)
            if f.alpha() > 200:
                summe = [summe[0] + f.red(), summe[1] + f.green(),
                         summe[2] + f.blue()]
                n += 1
    return tuple(v // n for v in summe) if n else None


def _sperre_lauf(laden=None):
    """Ein Chat (Schleifen-Attrappe) in "Nur lesen" hat im laufenden Zug
    einen Cadwork-Befehl ohne Frage abgelehnt bekommen. Was zeigt das
    Chatfenster, was der Monitor, und was tut der Knopf? -> dict."""
    from PyQt6.QtWidgets import QApplication, QLabel
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    w = z["w"]
    schleife = _SchleifenAttrappe()
    cad = "mcp__open-mcp-cad__execute_cadwork_command"
    ereignisse = [{"art": "ich", "text": "zeichne die Wand"},
                  {"art": "werkzeug", "werkzeug": cad, "id": "c1",
                   "eingabe": {"code": "x", "description": "Wand Nord"}},
                  {"art": "verweigert", "werkzeug": cad, "id": "c1",
                   "eingabe": {"code": "x", "description": "Wand Nord"},
                   "modus": "nur_lesen"}]
    z["chat"].update(an=True, laeuft_zug=True, schleife=schleife,
                     freigaben=[], modus="nur_lesen", stand=5,
                     kurzname="Claude", ereignisse=ereignisse)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        _chat_ziehen(D, z, 460, 680)
        _warte_qt(D, z, lambda: not w["chat_freigabe"].isHidden(), 2)
        texte = [lb.text() for lb in w["chat_freigabe"].findChildren(QLabel)
                 if lb.objectName() == "sperre_text"]
        knopf = w.get("chat_sperre_knopf")
        m["karte"] = (not w["chat_freigabe"].isHidden(), texte,
                      knopf.text() if knopf else None)
        m["modal"] = QApplication.activeModalWidget()
        D._chatknopf_zeigen(z)
        m["monitor"] = (w["kopf_chat"].toolTip(),
                        w["kopf_chat"].objectName())
        # Das Symbol muss auf dem blauen "hinweis" weiss sein (K9).
        m["symbol_hinweis"] = _symbol_farbe(w["kopf_chat"])
        n_vorher = len(ereignisse)
        if knopf is not None:
            knopf.click()
        _warte_qt(D, z, lambda: w["chat_freigabe"].isHidden(), 2)
        m["danach"] = (z["chat"].get("modus"), _modus_feld(z),
                       w["chat_freigabe"].isHidden(),
                       (_einst_lesen() or {}).get("modus"))
        # Nichts wiederholt: keine neue Nachricht, keine Antwort an die
        # Schleife, der Zug laeuft weiter, wie er lief.
        m["nichts_wiederholt"] = (len(z["chat"]["ereignisse"]) == n_vorher,
                                  schleife.antworten == [])
        D._chatknopf_zeigen(z)
        m["monitor_danach"] = w["kopf_chat"].toolTip()
        # K12: der Knopf faellt auch auf, solange die KI arbeitet (der Zug
        # laeuft hier weiter) — wieder blau erst, wenn der Zug vorbei ist.
        z["chat"]["laeuft_zug"] = False
        D._chatknopf_zeigen(z)
        m["symbol_danach"] = _symbol_farbe(w["kopf_chat"])
        z["chat"]["laeuft_zug"] = True
        # Ein spaeter Klick (die Karte ist noch nicht neu gezeichnet), waehrend
        # der Chat schon in einem anderen Modus steht: nichts aendert sich —
        # der Knopf geht nur von «Nur lesen» nach «Fragen» (Gegenpruefung K9).
        spaet = []
        for modus in ("alles_auto", "cadwork_frei"):
            z["chat"]["modus"] = modus
            spaet.append((D._sperre_wechseln(z), z["chat"]["modus"]))
        m["spaet"] = spaet
    finally:
        z["chat"].update(an=False, laeuft_zug=False, schleife=None,
                         freigaben=[])
        _einst_setzen(None)
    return m


def zelle_sperre_hinweis():
    """L75 (Rueckmeldung 2026-09-28): lehnt "Nur lesen" etwas ohne Frage ab,
    steht im Chat ein Hinweis mit dem, was die KI wollte, und EIN Knopf
    "Zu «Fragen» wechseln" — er wechselt den Modus und fuehrt nichts aus.
    Der Monitor sagt es auch. Nichts Modales."""
    try:
        m = _sperre_lauf()
        pruefe("L75 Nur lesen hat abgelehnt: Karte mit dem Alltagsnamen und "
               "dem einen Knopf",
               m["karte"] == (True, ["Die KI wollte etwas ändern (Wand Nord). "
                                     "Im Modus «Nur lesen» ist das "
                                     "gesperrt."], "Zu «Fragen» wechseln")
               and m["modal"] is None, m)
        pruefe("L75 der Chat-Knopf im Kopf faellt auf und sagt es im "
               "Tooltip (K12, vorher die Chat-Zeile des Monitors)",
               m["monitor"] == ("Chat — «Nur lesen» hat etwas gesperrt.",
                                "hinweis"), m["monitor"])
        hell, danach = m.get("symbol_hinweis"), m.get("symbol_danach")
        pruefe("L75 das Symbol des Chat-Knopfs ist auf dem blauen Knopf weiss, "
               "nach dem Zug wieder blau",
               hell is not None and min(hell) > 220 and danach is not None
               and danach[2] > danach[0] + 80, (hell, danach))
        pruefe("L75 ein Klick: Modus «Fragen» (Chat, Knopf, chat.json), Karte "
               "weg, nichts wiederholt",
               m["danach"] == ("fragen", "fragen", True, "fragen")
               and m["nichts_wiederholt"] == (True, True)
               and "gesperrt" not in m["monitor_danach"],
               m)
        pruefe("L75 ein spaeter Klick in einem anderen Modus aendert nichts "
               "(nie weiter als «Fragen», nie zurueck)",
               m["spaet"] == [(False, "alles_auto"), (False, "cadwork_frei")],
               m["spaet"])
        M = _mutant(_test_ersetzen("_sperre_hinweis",
                                   "modus != SPERRE_MODUS", "True"))
        k = _sperre_lauf(M)
        pruefe("L75 KONTROLLE: ohne den Hinweis keine Karte, der Chat-Knopf "
               "sagt nichts von «Nur lesen»", k["treffer"] == [1]
               and k["karte"][0] is False
               and "gesperrt" not in k["monitor"][0], k)
        M = _mutant(_aufruf_umbenennen("_sperre_wechseln", "_modus_waehlen",
                                       "_modus_zeigen"))
        k = _sperre_lauf(M)
        pruefe("L75 KONTROLLE: tut der Knopf nichts, bleibt der Modus und "
               "die Karte", k["treffer"] == [1]
               and k["danach"][0] == "nur_lesen" and k["danach"][2] is False,
               k)
        M = _mutant(_anweisungen("_sperre_wechseln",
                                 lambda s: isinstance(s, ast.If)))
        k = _sperre_lauf(M)
        pruefe("L75 KONTROLLE: ohne die Pruefung des Modus stellte ein "
               "spaeter Klick «Alles automatisch» auf «Fragen»",
               k["treffer"] == [1] and k["spaet"][0] == (True, "fragen"),
               k["spaet"])
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L78: Strich-Symbole statt Emoji, Logo, ohne QtSvg (K9) ---------------

def _symbole_lauf(laden=None, ohne_svg=False):
    """Dock und Chatfenster gebaut; welche Knoepfe ein Symbol tragen, was
    ohne Symbol dasteht, "Neuer Chat" breit und schmal, das Logo. Mit
    `ohne_svg` fehlt PyQt6.QtSvg (wie es in Cadwork sein koennte — dort
    nicht gemessen). -> dict."""
    import io as _io
    from PyQt6.QtWidgets import QLabel, QPushButton
    alt_svg = sys.modules.get("PyQt6.QtSvg", "fehlt")
    alt_err = sys.stderr
    sys.stderr = _io.StringIO()
    import PyQt6 as _pyqt
    alt_attr = getattr(_pyqt, "QtSvg", None)
    if ohne_svg:
        # Import scheitert: der Eintrag in sys.modules UND das Attribut am
        # Paket (sonst liefert "from PyQt6 import QtSvg" das alte Modul).
        sys.modules["PyQt6.QtSvg"] = None
        if alt_attr is not None:
            delattr(_pyqt, "QtSvg")
    m = {}
    try:
        _einst_setzen(None)
        D, z, _d = _neustart(laden() if laden else None)
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        S = D._symbol_modul()
        m["qtsvg"] = S is not None and S.qtsvg() is not None
        w = z["w"]
        # "Beenden" steht nur bei laufendem Chat — fuer die Messung sichtbar.
        w["chat_ende"].show()
        _chat_ziehen(D, z, 460, 680)
        # K12: der Kopf (Chat, Andocken, Verkleinern), die Segmentzeile
        # (Rueckgaengig, Wiederherstellen, Neu zeichnen, Hinweise, "⋯") und
        # der Chat.
        w["kopf_verkleinern"].show()
        knoepfe = {"neu": w["chat_neu"], "ende": w["chat_ende"],
                   "senden": w["chat_senden"],
                   "plus": w["chat_plus"], "modus": w["chat_modus"],
                   "kopf_chat": w["kopf_chat"],
                   "andocken": w["kopf_andocken"],
                   "verkleinern": w["kopf_verkleinern"],
                   "mehr": w["mehr_menue"], "hinweise": w["hinweise_knopf"],
                   "undo": w["btn_undo"], "redo": w["btn_redo"],
                   "neu_zeichnen": w["btn_neu"]}
        m["ikonen"] = {k: (b is not None and not b.icon().isNull())
                       for k, b in knoepfe.items()}
        m["texte"] = {k: (b.volltext() if hasattr(b, "volltext")
                          else b.text()) if b is not None else None
                      for k, b in knoepfe.items()}
        m["neu_breit"] = QPushButton.text(w["chat_neu"])
        ende = w["chat_ende"]
        # K9b: Beenden = gefuelltes Quadrat (Mitte deckend; der Umriss eines
        # "circle-stop" liess die Mitte bis auf einen Punkt frei) + Wort.
        bild = ende.icon().pixmap(16, 16).toImage()             if not ende.icon().isNull() else None
        m["ende_breit"] = (QPushButton.text(ende), ende.property("symbol"),
                           D.SYMBOLE["beenden"][0],
                           bild.pixelColor(bild.width() // 2,
                                           bild.height() // 2).alpha()
                           if bild is not None else None,
                           ende.x() < w["chat_neu"].x())
        _chat_ziehen(D, z, 300, 680)
        m["neu_schmal"] = (QPushButton.text(w["chat_neu"]),
                           w["chat_neu"].accessibleName(),
                           w["chat_neu"].toolTip()[:10])
        m["ende_schmal"] = (QPushButton.text(ende), ende.accessibleName(),
                            ende.toolTip()[:7])
        pm = S.pixmap("plus", "#000000", 16) if S is not None else None
        m["scharf"] = pm.devicePixelRatio() if pm is not None else None
        # Das Logo: im Kopf des Fensters UND in der Arbeitsanzeige (K12) —
        # je ein QLabel "logo" mit Bild.
        def mit_logo(wurzel):
            logos = [lb for lb in wurzel.findChildren(QLabel)
                     if lb.objectName() == "logo"]
            return bool(logos) and logos[0].pixmap() is not None \
                and not logos[0].pixmap().isNull()
        m["logo"] = mit_logo(z["w"]["kopf"]) and mit_logo(z["anzeige"])
        m["fehler"] = [z_ for z_ in sys.stderr.getvalue().splitlines()
                       if "Fehler" in z_ or "Traceback" in z_]
    finally:
        sys.stderr = alt_err
        if alt_svg == "fehlt":
            sys.modules.pop("PyQt6.QtSvg", None)
        else:
            sys.modules["PyQt6.QtSvg"] = alt_svg
        if alt_attr is not None:
            _pyqt.QtSvg = alt_attr
        _einst_setzen(None)
        _frischer_start()
    return m


def zelle_symbole():
    """L78 (Rueckmeldung 2026-09-28): Strich-Symbole (Lucide) statt Emoji,
    "Neuer Chat" mit Wort, solange Platz ist; das Logo im Steuerfenster und
    (K11) in der Leiste, dort auch Chat-Symbol und ⤢. Ohne QtSvg steht Text
    da — kein Kaestchen, kein Fehler."""
    try:
        m = _symbole_lauf()
        pruefe("L78 mit QtSvg: alle Knoepfe tragen ein Symbol (Neuer Chat, "
               "Beenden, Senden, +, Modus; im Kopf Chat, Andocken, "
               "Verkleinern; in der Segmentzeile Rueckgaengig, "
               "Wiederherstellen, Neu zeichnen, Hinweise, '⋯')",
               m["qtsvg"] and all(m["ikonen"].values()), m["ikonen"])
        pruefe("L78 'Neuer Chat' mit Wort bei 460 px, nur das Symbol bei "
               "300 px (Name und Tooltip bleiben)",
               m["neu_breit"] == "Neuer Chat"
               and m["neu_schmal"][0] == ""
               and m["neu_schmal"][1] == "Neuer Chat", (m["neu_breit"],
                                                        m["neu_schmal"]))
        pruefe("L78 'Beenden' (K9b): gefuelltes Quadrat mit dem Wort bei "
               "460 px, links von 'Neuer Chat'; nur das Quadrat bei 300 px "
               "(Name und Tooltip bleiben)",
               m["ende_breit"][:3] == ("Beenden", "beenden", "square")
               and (m["ende_breit"][3] or 0) >= 200 and m["ende_breit"][4]
               and m["ende_schmal"] == ("", "Beenden", "Beenden"),
               (m["ende_breit"], m["ende_schmal"]))
        pruefe("L78 Symbole scharf (doppelte Aufloesung), Logo im Kopf "
               "und in der Arbeitsanzeige, keine Fehler",
               (m["scharf"] or 0) >= 2 and m["logo"]
               and not m["fehler"], (m["scharf"], m["logo"], m["fehler"]))
        k = _symbole_lauf(ohne_svg=True)
        pruefe("L78 ohne QtSvg: kein Symbol, dafuer Text (Stopp, Pfeil, "
               "+, 'Neuer Chat'; im Kopf 'Chat', ⤢, –; in der Segmentzeile "
               "↶, ↷, ↻, !, ⋯), Logo trotzdem, keine Fehler",
               k["qtsvg"] is False and not any(k["ikonen"].values())
               and k["texte"]["kopf_chat"] == "Chat"
               and k["texte"]["andocken"] == "⤢"
               and k["texte"]["verkleinern"] == "–"
               and k["texte"]["mehr"] == "⋯"
               and k["texte"]["hinweise"] == "!"
               and (k["texte"]["undo"], k["texte"]["redo"],
                    k["texte"]["neu_zeichnen"]) == ("↶", "↷", "↻")
               and k["texte"]["ende"] == "Beenden"
               and k["texte"]["senden"] == "↑"
               and k["texte"]["plus"] == "+"
               and k["texte"]["neu"] == "Neuer Chat" and k["logo"]
               and not k["fehler"], k)
        M = _mutant(_anweisungen(
            "_knopf_symbol", lambda s_: isinstance(s_, ast.Assign)
            and ast.unparse(s_).startswith("lucide, ersatz"),
            "return False"))
        k = _symbole_lauf(lambda: M)
        pruefe("L78 KONTROLLE: setzt _knopf_symbol nichts, fehlen Symbole",
               M._mutant_treffer == [1] and not all(k["ikonen"].values()),
               k["ikonen"])
        M = _mutant(_anweisungen(
            "_knopf_symbol", lambda s_: isinstance(s_, ast.Assign)
            and ast.unparse(s_).startswith("lucide, ersatz"),
            "return False"))
        k = _symbole_lauf(lambda: M, ohne_svg=True)
        pruefe("L78 KONTROLLE: ... und ohne QtSvg stuende kein Text da",
               M._mutant_treffer == [1] and k["texte"]["ende"] != "Beenden",
               k["texte"])
        M = _mutant()
        M._logo_pixmap = lambda groesse: None
        k = _symbole_lauf(lambda: M)
        pruefe("L78 KONTROLLE: ohne Logo-Bild fehlt das Logo (die Zeile oben "
               "wird rot)", k["logo"] is False, k["logo"])
        M = _mutant(_anweisungen(
            "_kopf_bauen", lambda s_: isinstance(s_, ast.If)
            and "_knopf_symbol(chat" in ast.unparse(s_.test),
            "_knopf_symbol(chat, 'chat', farbe=FARBEN['blau'])"))
        k = _symbole_lauf(lambda: M, ohne_svg=True)
        pruefe("L78 KONTROLLE: ohne den Ersatztext stuende der Chat-Knopf "
               "im Kopf ohne QtSvg leer da",
               M._mutant_treffer == [1] and k["texte"]["kopf_chat"] == "",
               k["texte"])
        M = _mutant()
        M.GEFUELLT = frozenset()
        k = _symbole_lauf(lambda: M)
        pruefe("L78 KONTROLLE: ohne Fuellung bliebe die Mitte des Quadrats "
               "leer", k["ende_breit"][3] is not None
               and k["ende_breit"][3] < 50, k["ende_breit"])
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- Hilfe: ganz auf einem Bildschirm (Gegenpruefung K9) -------------------

def _ganz_auf_schirm(teil):
    """Steht der Rahmen von `teil` ganz im verfuegbaren Bereich EINES
    Bildschirms?"""
    from PyQt6.QtWidgets import QApplication
    g = teil.frameGeometry()
    return any(s.availableGeometry().contains(g)
               for s in QApplication.screens())


# --- L80: erster Kontakt "Womit möchtest du chatten?" (2026-09-29) ---------

_NICHTS = {"claude": False, "codex": False, "schluessel": False,
           "lokal": False}


def _sichtbar_im(wurzel, wd):
    return wd.isVisibleTo(wurzel)


def _api_woerter(texte):
    """Sichtbare Texte, die "API" als Wort tragen (Tooltips zaehlen nicht:
    dort steht das Fachwort mit Erklaerung)."""
    import re as _re
    return [t for t in texte if _re.search(r"(?<![A-Za-z])API(?![a-z])", t)]


def _einstieg_lauf(laden=None):
    """Nichts eingerichtet: Chatfenster oeffnen wie ein Nutzer, die Knoepfe
    der Karte druecken. Das Nachsehen laeuft im echten Nebenthread, nur
    `_einstieg_wege` ist ersetzt (kein Claude Code usw.). -> dict."""
    import tempfile as _tf
    from PyQt6.QtWidgets import QApplication
    _einst_setzen(None)
    D, z, _d = _neustart(laden)
    w = z["w"]
    stand = {"wege": dict(_NICHTS), "gefragt": 0}

    def wege(C, A, L, e=None, env=None):
        stand["gefragt"] += 1
        return dict(stand["wege"])
    D._einstieg_wege = wege
    geoeffnet = []
    D.URL_OEFFNEN = geoeffnet.append
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    try:
        _chat_ziehen(D, z, 460, 680)
        karte = w["chat_willkommen"]
        _warte_qt(D, z, lambda: not karte.isHidden(), 3)
        inhalt = _chat_inhalt(z["fenster"])
        m["karte"] = (_sichtbar_im(inhalt, karte),
                      _sichtbar_im(inhalt, w["chat_verlauf"]),
                      stand["gefragt"] >= 1)
        texte = [t for wd, art, t in _alle_texte(karte)
                 if art == "text" and _sichtbar_im(inhalt, wd)]
        m["texte"] = texte
        m["modal"] = QApplication.activeModalWidget()
        # Claude: Anbieter gewaehlt (auch in chat.json), der eine Schritt steht
        w["chat_anbieter"].setCurrentIndex(w["chat_anbieter"].findData("eigen"))
        w["chat_willkommen_claude"].click()
        _APP.processEvents()
        schritt = w["chat_willkommen_schritt"]
        m["claude"] = (D._gewaehlter_anbieter(z)["id"],
                       _sichtbar_im(inhalt, schritt),
                       "irm https://claude.ai/install.ps1 | iex"
                       in schritt.text(),
                       (_einst_lesen() or {}).get("anbieter"))
        w["chat_willkommen_codex"].click()
        _APP.processEvents()
        # Seit 2026-10-09 der offizielle Befehl von OpenAI (ohne Node.js),
        # derselbe, den install.ps1 -ChatKi codex nimmt (aus der Quelle).
        import re as _re
        _url = _re.search(r'codex\s*=\s*"(https://[^"]+)"', open(
            os.path.join(REPO, "verteilung", "install.ps1"),
            encoding="ascii").read()).group(1)
        m["codex"] = (D._gewaehlter_anbieter(z)["id"],
                      ("irm %s | iex" % _url) in schritt.text()
                      and "codex login" in schritt.text())
        # Schluessel: OpenAI, die Chat-Einstellungen mit dem Feld
        w["chat_willkommen_schluessel"].click()
        _APP.processEvents()
        m["schluessel"] = (D._gewaehlter_anbieter(z)["id"],
                           D._chat_einstellungen_sichtbar(z),
                           not w["chat_schluessel"].isHidden(),
                           w["chat_schluessel"].placeholderText())
        # Rueckmeldung: "API" versteht niemand — sichtbar nirgends mehr auf
        # den Chat-Einstellungen (nur im Tooltip, mit Erklaerung).
        seite = w["chat_einst_seite"]
        sicht = [t for wd, art, t in _alle_texte(seite)
                 if art in ("text", "placeholderText", "currentText",
                            "itemText") and (art == "itemText"
                                             or _sichtbar_im(seite, wd))]
        tipps = [t for wd, art, t in _alle_texte(seite)
                 if art in ("toolTip", "itemTip")]
        m["api"] = (_api_woerter(sicht), any("Fachwort: API" in t
                                             for t in tipps))
        D._chat_einstellungen_zeigen(z, False)
        _APP.processEvents()
        # Anleitung: ohne PDF die Seite im Netz, mit PDF die Datei daneben
        w["chat_willkommen_anleitung"].click()
        ordner = _tf.mkdtemp(prefix="omcad_l80_")
        pdf = os.path.join(ordner, D.ANLEITUNG_DATEI)
        with open(pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n%%EOF\n")
        D.PLUGIN_ORDNER = ordner
        w["chat_willkommen_anleitung"].click()
        m["anleitung"] = list(geoeffnet)
        m["anleitung_soll"] = [D.ANLEITUNG_URL, pdf]
        # "Nochmal prüfen", nachdem Claude Code eingerichtet ist: Karte weg,
        # Verlauf wieder da
        stand["wege"] = dict(_NICHTS, claude=True)
        w["chat_willkommen_pruefen"].click()
        _warte_qt(D, z, lambda: karte.isHidden(), 3)
        m["nach_pruefen"] = (karte.isHidden(),
                             _sichtbar_im(inhalt, w["chat_verlauf"]))
        # Ein gespeicherter Schluessel (Takt kennt ihn) laesst sie auch gehen
        D._einstieg_setzen(z, dict(_NICHTS))
        _warte_qt(D, z, lambda: not karte.isHidden(), 2)
        z["schluessel_da"] = {"openai": True}
        _warte_qt(D, z, lambda: karte.isHidden(), 2)
        m["schluessel_da"] = karte.isHidden()
        z["schluessel_da"] = {}
        # Laeuft ein Chat, nie die Karte
        _warte_qt(D, z, lambda: not karte.isHidden(), 2)
        z["chat"].update(an=True, laeuft_zug=False, ereignisse=[
            {"art": "ich", "text": "Probe"}], stand=z["chat"].get("stand", 0) + 1)
        _warte_qt(D, z, lambda: karte.isHidden(), 2)
        m["laeuft"] = karte.isHidden()
    finally:
        z["chat"].update(an=False, laeuft_zug=False, ereignisse=[])
        _einst_setzen(None)
    return m


def zelle_erster_kontakt():
    """L80 (Rueckmeldung 2026-09-29): ist nichts eingerichtet, zeigt das
    Chatfenster beim Oeffnen "Womit möchtest du chatten?" mit drei Wegen
    in Alltagssprache; jeder Knopf fuehrt zur richtigen Stelle; die
    Anleitung oeffnet das PDF neben dem Plugin, sonst die Seite im Netz;
    auf den Chat-Einstellungen steht "API" nirgends mehr sichtbar."""
    try:
        m = _einstieg_lauf()
        pruefe("L80 nichts eingerichtet: beim Oeffnen die Karte statt des "
               "Verlaufs, nachgesehen im Nebenthread, nichts Modales",
               m["karte"] == (True, False, True) and m["modal"] is None, m)
        t = m.get("texte", [])
        pruefe("L80 die Karte: Frage, drei Wege, Anleitung, ohne Fachwoerter",
               "Womit möchtest du chatten?" in t
               and {"Claude-Abo (Pro oder Max)", "ChatGPT-Abo (Codex)",
                    "Eigener Schlüssel (ohne Abo)", "Anleitung öffnen",
                    "Nochmal prüfen"} <= set(t)
               and not _api_woerter(t), t)
        pruefe("L80 Claude: Anbieter Claude Code (gemerkt), der eine Schritt "
               "mit dem Befehl steht da; Codex ebenso",
               m["claude"] == ("claude", True, True, "claude")
               and m["codex"] == ("codex", True), (m["claude"], m["codex"]))
        pruefe("L80 eigener Schluessel: OpenAI, Chat-Einstellungen offen, "
               "Feld sichtbar, ohne 'API'",
               m["schluessel"] == ("openai", True, True,
                                   "Schlüssel hier einfügen …"),
               m["schluessel"])
        pruefe("L80 auf den Chat-Einstellungen kein sichtbares 'API', das "
               "Fachwort nur im Tooltip mit Erklaerung",
               m["api"] == ([], True), m["api"])
        pruefe("L80 Anleitung: ohne PDF die Seite im Netz, mit PDF neben dem "
               "Plugin die Datei", m["anleitung"] == m["anleitung_soll"],
               (m["anleitung"], m["anleitung_soll"]))
        pruefe("L80 'Nochmal prüfen' nach dem Einrichten: Karte weg, Verlauf "
               "da; ein gespeicherter Schluessel und ein laufender Chat "
               "lassen sie auch gehen",
               m["nach_pruefen"] == (True, True) and m["schluessel_da"]
               and m["laeuft"], (m["nach_pruefen"], m["schluessel_da"],
                                 m["laeuft"]))
        pruefe("L80 KONTROLLE: die alte Beschriftung 'OpenAI (API-Schlüssel)' "
               "fiele auf", _api_woerter(["OpenAI (API-Schlüssel)"]) != [])
        k = _einstieg_lauf(_mutant(_anweisungen(
            "_chat_oeffnen", _beginnt("_sicher(lambda: _einstieg_pruefen"))))
        pruefe("L80 KONTROLLE: sieht das Oeffnen nicht nach, erscheint keine "
               "Karte", k["treffer"] == [1] and k["karte"][0] is False,
               (k["treffer"], k["karte"]))
        k = _einstieg_lauf(_mutant(_test_ersetzen("_einstieg_zeigen",
                                                  "zeigen", "False")))
        pruefe("L80 KONTROLLE: versteckt die Karte den Verlauf nicht, stehen "
               "beide da", k["treffer"] == [1] and k["karte"][:2] == (True,
                                                                        True),
               (k["treffer"], k["karte"]))
        k = _einstieg_lauf(_mutant(_aufruf_umbenennen(
            "_einstieg_weg", "_chat_einstellungen_zeigen",
            "_chat_einstellungen_sichtbar")))
        pruefe("L80 KONTROLLE: oeffnet 'Schlüssel eingeben' die Einstellungen "
               "nicht, faellt es auf", k["treffer"] == [1]
               and k["schluessel"][1] is False, k["schluessel"])
        k = _einstieg_lauf(_mutant(_anweisungen(
            "_anleitung_ziel", lambda s: isinstance(s, ast.Return),
            "return ANLEITUNG_URL")))
        pruefe("L80 KONTROLLE: uebersieht der Knopf das PDF neben dem "
               "Plugin, faellt es auf", k["treffer"] == [1]
               and k["anleitung"] != k["anleitung_soll"], k["anleitung"])
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L81/L83: Leiste, Steuerfenster, Chat darunter (K10, K11) --------------
# Rueckmeldung aus Cadwork: der Monitor ging "mitten auf dem Bildschirm" auf,
# obwohl ihn diese Zellen oben rechts sahen. Gemessen 2026-10-01 (Qt 6.11,
# ECHTE Windows-Plattform, ein Hauptfenster-Ersatz, kein Cadwork): ein
# schwebendes Dock, das waehrend `setFloating` (im Signal
# `topLevelChanged`) verschoben wurde, verliert danach WA_Moved, und Windows
# setzt es beim Zeigen in die Mitte seines Hauptfensters; verschoben NACH
# `setFloating` bzw. nach `show()` steht es am Ziel. Offscreen geschieht das
# nie — deshalb stellt `_windows_nachahmer` genau dieses Verhalten nach.
# Seit K11 (2026-10-02) zeigt der Klick die LEISTE, ein rahmenloses
# Werkzeugfenster mit Eltern = Hauptfenster: fuer sie gilt dieselbe Regel
# (ein Fenster mit Eltern, beim ersten Zeigen ohne WA_Moved -> Mitte), also
# wirkt der Nachahmer auch auf sie.

_K10_DOCKS = ("OpenMcpCadADock", "OpenMcpCadChatDock")
#: Alle schwebenden Fenster des Docks, auf die der Nachahmer wirkt: die
#: beiden Docks (Steuerfenster, Chat) und die Leiste (K11).
_K11_FENSTER = _K10_DOCKS + ("OpenMcpCadMini", "OpenMcpCadFenster",
                             "OpenMcpCadAnzeige")


def _pumpen(sekunden):
    from PyQt6.QtWidgets import QApplication
    ende = time.monotonic() + sekunden
    while True:
        QApplication.processEvents()
        if time.monotonic() >= ende:
            break
        time.sleep(0.02)


def _windows_nachahmer(spaet_ms=None):
    """Ein Ereignisfilter wie Qts Windows-Plattform: ein schwebendes Fenster
    des Docks (Steuerfenster, Chat, seit K11 auch die Leiste — `_K11_FENSTER`),
    das beim Zeigen nicht als verschoben gilt (WA_Moved), kommt in die Mitte
    seines Hauptfensters. `spaet_ms`: ausserdem `spaet_ms` nach dem ersten
    Zeigen noch einmal dorthin (je Fenster einmal) — "Qt verschiebt es nach
    dem Zeigen". -> der Filter (installiert; `entfernen()` nimmt ihn wieder
    weg)."""
    from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
    from PyQt6.QtWidgets import QApplication

    def mitte(obj):
        try:
            p = obj.parentWidget()
            if p is None:
                return
            g = QRect(p.mapToGlobal(QPoint(0, 0)), p.size())
            r = obj.frameGeometry()
            r.moveCenter(g.center())
            obj.move(r.topLeft())
        except RuntimeError:
            pass

    class Filter(QObject):
        def __init__(self):
            super().__init__()
            self.zentriert, self.spaet = [], []

        def eventFilter(self, obj, ev):                # noqa: N802
            try:
                # Ein Dock nur schwebend (angedockt ist es kein Fenster); die
                # Leiste ist immer eins.
                if (ev.type() == QEvent.Type.Show
                        and obj.isWidgetType()
                        and obj.objectName() in _K11_FENSTER
                        and obj.isWindow()):
                    name = obj.objectName()
                    if not obj.testAttribute(Qt.WidgetAttribute.WA_Moved):
                        mitte(obj)
                        self.zentriert.append(name)
                    if spaet_ms is not None and name not in self.spaet:
                        self.spaet.append(name)
                        QTimer.singleShot(spaet_ms, lambda o=obj: mitte(o))
            except Exception:                          # noqa: BLE001
                pass
            return False

        def entfernen(self):
            QApplication.instance().removeEventFilter(self)

    f = Filter()
    QApplication.instance().installEventFilter(f)
    _ALTE_ZUSTAENDE.append({"filter": f})
    return f


class _ListenLog(logging.Handler):
    """Das Log des Kerns im Speicher (`kern.LOG` der Attrappe)."""

    def __init__(self):
        super().__init__()
        self.zeilen = []

    def emit(self, record):
        self.zeilen.append(record.getMessage())


def _cadwork_ersatz(ort=(120, 60), groesse=(640, 700)):
    """Ein Hauptfenster wie Cadworks — NICHT bei (0, 0), mit Menue und
    Werkzeugleiste (die Mitte beginnt darunter). Bleibt am Leben."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel, QMainWindow
    haupt = QMainWindow()
    haupt.setWindowTitle("Cadwork (Ersatz)")
    haupt.menuBar().addMenu("Datei")
    leiste = haupt.addToolBar("Werkzeuge")
    leiste.addAction("Wand")
    flaeche = QLabel("3D-Ansicht (Ersatz)")
    flaeche.setAlignment(Qt.AlignmentFlag.AlignCenter)
    flaeche.setStyleSheet("background: #3b4450; color: #d8dde3;")
    haupt.setCentralWidget(flaeche)
    haupt.resize(*groesse)
    haupt.move(*ort)
    haupt.show()
    _ALTE_ZUSTAENDE.append({"haupt": haupt})
    return haupt


def _global(wd, rahmen=True):
    """(links, oben, rechts_exkl, unten_exkl) von `wd` global — bei Fenstern
    mit Rahmen (`rahmen`), sonst die Innenflaeche wie `mapToGlobal`."""
    from PyQt6.QtCore import QPoint
    if wd.isWindow() and rahmen:
        g = wd.frameGeometry()
        return (g.left(), g.top(), g.left() + g.width(), g.top() + g.height())
    p = wd.mapToGlobal(QPoint(0, 0))
    return (p.x(), p.y(), p.x() + wd.width(), p.y() + wd.height())


# --- L94-L104: das EINE Fenster, Popover, Arbeitsanzeige (K12, 2026-10-07) --
# Rueckmeldung 2026-10-07 nach dem Test von K11 in Cadwork: "nur eine Anzeige
# mehr, Chat und Monitor vereint, ganz oben immer etwa so wie das ganz kleine
# Pop-up" (die Leiste, Bild 8), "das mittlere Pop-up will ich nicht mehr",
# "Vergroessern -> rechts andocken", "Einstellungen brauchts nicht in der
# obersten Leiste", Segmente "Chat | Briefkasten", der Popover fuer Modell
# und Denkstufe wie bei ChatGPT (Bild 2), und eine Arbeitsanzeige, die sagt,
# was wirklich geschieht ("KI denkt nach", "KI zeichnet"). Ersetzt die
# Fenster-Zellen von K9-K11 (L76, L77, L81, L83-L91 alt; L20, L68, L79,
# L85, L86, L92, L93 umgeschrieben).

_K11_NAMEN = ("OpenMcpCadMini", "OpenMcpCadADock", "OpenMcpCadChatDock")


class _K12:
    """Ein Plugin-Klick neben einem Cadwork-Ersatz (K12): Dienst-Attrappe
    (verbunden), das Log des Kerns im Speicher, auf Wunsch der
    Windows-Nachahmer (L81) und ein eigenes Dock von Cadwork rechts.
    `ende()` raeumt ab."""

    def __init__(self, laden=None, nachahmer=False, spaet_ms=None,
                 ort=(120, 60), groesse=(640, 700), fremd_dock=False,
                 anker=None, nativ=False):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QDockWidget, QLabel
        _frischer_start()
        _einst_setzen(None)
        self.filt = _windows_nachahmer(spaet_ms) if nachahmer else None
        self.haupt = _cadwork_ersatz(ort, groesse)
        if nativ:
            # Wie Cadwork (gemessen 2026-10-08): die 3D-Mitte ist ein
            # natives Fenster — dann wird jedes Dock ein natives Kind.
            self.haupt.centralWidget().setAttribute(
                Qt.WidgetAttribute.WA_NativeWindow)
        self.fremd = None
        if fremd_dock:
            self.fremd = QDockWidget("Eigenschaften", self.haupt)
            self.fremd.setObjectName("CadworkEigenschaften")
            self.fremd.setWidget(QLabel("Eigenschaften (Ersatz)"))
            self.haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                                     self.fremd)
        _pumpen(0.05)
        self.log = logging.getLogger("omcad.k12_probe_%d"
                                     % len(_ALTE_ZUSTAENDE))
        self.log.propagate = False
        self.log.setLevel(logging.INFO)
        self.ausgang = _ListenLog()
        self.log.addHandler(self.ausgang)
        self.client, self.kern = _Client([]), _VerbindKern(1, 0)
        self.kern.LOG = self.log
        if anker is not None:
            anker()
        self.D, self.z, _r = _klick(self.client, self.kern, verbinden=False,
                                    laden=laden)
        self.treffer = getattr(self.D, "_mutant_treffer", None)
        z = self.z
        z["dienst"] = Dienst()
        z["dienst"].cfg = types.SimpleNamespace(instanz="A", port=53127)
        z["instanz"] = "A"
        z["kern"] = self.kern
        self.D._auffrischen(z)
        _pumpen(0.4)
        self.D._auffrischen(z)
        self.w, self.f = z["w"], z["fenster"]

    def aktion(self, name, warten=0.35):
        self.D._fenster_aktion(self.z, name)
        _pumpen(warten)
        self.D._auffrischen(self.z)
        return self.z["fenster_zustand"]

    def kopf_g(self):
        """(rechts_exkl, oben) des schwebenden Fensters (dort steht der
        Kopf)."""
        g = _global(self.f)
        return (g[2], g[1])

    def ende(self):
        if self.filt is not None:
            self.filt.entfernen()
        self.log.removeHandler(self.ausgang)
        self.kern.aufraeumen()
        self.haupt.hide()
        _frischer_start()


def _maus(ziel, art, lokal, knopf=None, gedrueckt=None):
    """Ein Mausereignis an `ziel` (lokale Koordinaten). -> global."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication
    if knopf is None:
        knopf = Qt.MouseButton.LeftButton
    if gedrueckt is None:
        gedrueckt = (knopf if art != QEvent.Type.MouseButtonRelease
                     else Qt.MouseButton.NoButton)
    glob = ziel.mapToGlobal(lokal)
    QApplication.sendEvent(ziel, QMouseEvent(
        art, QPointF(lokal), QPointF(glob), knopf, gedrueckt,
        Qt.KeyboardModifier.NoModifier))
    return glob


def _sichtbare_fenster():
    """Die sichtbaren Fenster des Prozesses, die zu Open MCP CAD gehoeren
    koennten: alles ausser Cadwork-Ersatz (QMainWindow), Popups (Aufklapper,
    Popover) und der Arbeitsanzeige. -> [objectName]."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMainWindow
    namen = []
    for wd in QApplication.topLevelWidgets():
        if not wd.isVisible() or isinstance(wd, QMainWindow):
            continue
        if wd.windowType() == Qt.WindowType.Popup:
            continue
        if wd.objectName() == "OpenMcpCadAnzeige":
            continue
        namen.append(wd.objectName())
    return namen


# --- L20: die Pille (K12; bis K11 die Leiste) ------------------------------

def _mini_lauf(laden=None):
    """L20: die Pille nach dem Plugin-Klick — gemessen wie ein Nutzer sie
    sieht und bedient: Chat-Knopf, Ziehen am Kopf, Aussehen, der Chat geht
    auf, Verkleinern, ein zweiter Klick. -> dict."""
    from PyQt6.QtCore import QEvent, QPoint, Qt
    from PyQt6.QtGui import QColor
    k = _K12(laden=laden)
    D, z, w, f = k.D, k.z, k.w, k.f
    m = {"treffer": k.treffer}
    try:
        kopf, chat = w["kopf"], w["kopf_chat"]
        m["klick"] = (f.isVisible(), w["koerper"].isHidden(),
                      z.get("mini") is None and z.get("chatfenster") is None)
        m["chat_symbol"] = (not chat.isHidden(), kopf.isAncestorOf(chat),
                            chat.objectName(), chat.accessibleName(),
                            chat.toolTip().startswith("Chat"),
                            not chat.icon().isNull() or chat.text() == "Chat")
        # Frisch gesetzt: das Nachsehen (0/300 ms) steht beim Ziehen noch aus.
        D._fenster_lage(z)
        # Nicht-Druck zuerst: eine Bewegung OHNE vorherigen Druck verschiebt
        # nichts.
        vorher = f.pos()
        _maus(kopf, QEvent.Type.MouseMove, QPoint(5, 5),
              Qt.MouseButton.NoButton)
        m["ohne_druck"] = f.pos() == vorher
        logo = w["kopf_logo"]
        start = _maus(logo, QEvent.Type.MouseButtonPress,
                      QPoint(logo.width() // 2, logo.height() // 2))
        m["druck_logo"] = (f.isVisible(), w["koerper"].isHidden())
        ziel = start + QPoint(80, 50)
        _maus(kopf, QEvent.Type.MouseMove, kopf.mapFromGlobal(ziel),
              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        _maus(kopf, QEvent.Type.MouseButtonRelease, kopf.mapFromGlobal(ziel))
        m["gezogen"] = (f.pos() - vorher == QPoint(80, 50),
                        z.get("fenster_gezogen"), "%s" % (f.pos() - vorher))
        # Das Nachsehen nach dem Zeigen darf sie NICHT zuruecksetzen.
        _pumpen(0.35)
        m["gezogen_danach"] = (f.pos() - vorher == QPoint(80, 50),
                               "%s" % (f.pos() - vorher))
        m["zeiger"] = (kopf.cursor().shape() == Qt.CursorShape.OpenHandCursor,
                       all(b.cursor().shape()
                           == Qt.CursorShape.PointingHandCursor
                           for b in (chat, w["primaer"],
                                     w["kopf_andocken"])))

        # Aussehen: die Ecke liegt ausserhalb der Maske (rund — seit
        # 2026-10-08 Maske statt Durchsichtigkeit, L115), die Mitte darin;
        # am gerenderten Bild ist die obere Kante blau. Die Kontrolle
        # rendert denselben Kopf ohne die Regeln des Fensters — dann ist die
        # Kante nicht blau (die Maske prueft L115 mit eigenen Kontrollen).
        def blau(c):
            return c.blue() > 180 and c.red() < 60 and c.alpha() > 200

        def bild():
            # Das ganze schwebende Fenster; ein Kind allein fuellte seine
            # Flaeche mit dem Grund.
            return f.grab().toImage()

        def rund():
            maske = f.mask()
            return (not maske.isEmpty() and not maske.contains(QPoint(2, 2))
                    and maske.contains(QPoint(f.width() // 2,
                                              f.height() // 2)))

        def kante_von(b):
            for y in range(5):
                c = b.pixelColor(b.width() // 2, y)
                if blau(c):
                    return c
            return b.pixelColor(b.width() // 2, 3)
        b = bild()
        ecke, kante = b.pixelColor(2, 2), kante_von(b)
        m["aussehen"] = (rund(), blau(kante),
                         ecke.name(QColor.NameFormat.HexArgb),
                         kante.name(QColor.NameFormat.HexArgb))
        regeln = kopf.styleSheet()
        kopf.setStyleSheet(D._qss())
        b = bild()
        ecke_k, kante_k = b.pixelColor(2, 2), kante_von(b)
        kopf.setStyleSheet(regeln)
        m["aussehen_k"] = (not blau(kante_k),
                           ecke_k.name(QColor.NameFormat.HexArgb),
                           kante_k.name(QColor.NameFormat.HexArgb))
        # Die gezogene Pille ragt hier ueber den Rand des Bildschirms; offen
        # steht das Fenster immer GANZ darauf (L79) und rueckte dann mit
        # dem Kopf nach innen. Gemessen wird das Stehenbleiben an einer
        # Pille, die ganz auf dem Bildschirm steht.
        r = f.screen().availableGeometry()
        f.move(min(f.x(), r.right() + 1 - f.width() - 40),
               max(f.y(), r.top() + 40))
        _pumpen(0.05)
        rechts_oben = k.kopf_g()
        chat.click()
        _pumpen(0.35)
        m["auf"] = (not w["koerper"].isHidden(),
                    z["fenster_zustand"] == D.OFFEN_Z,
                    abs(k.kopf_g()[0] - rechts_oben[0]) <= 2
                    and abs(k.kopf_g()[1] - rechts_oben[1]) <= 2,
                    rechts_oben, k.kopf_g())
        w["kopf_verkleinern"].click()
        _pumpen(0.35)
        m["verkleinert"] = (w["koerper"].isHidden(), f.isVisible(),
                            z["fenster_zustand"] == D.PILLE_Z)
        D.oeffnen(z["kern_laden"], z["cfg_bauen"])
        _pumpen(0.1)
        m["zweiter_klick"] = (f.isVisible(), w["koerper"].isHidden(),
                              z["fenster"] is f)
    finally:
        k.ende()
    return m


def zelle_mini():
    """L20 (K12, Rueckmeldung 2026-10-07: "ganz oben sollte es immer etwa so
    aussehen wie das ganz kleine Pop-up"): der Plugin-Klick zeigt die PILLE
    — nur den Kopf des einen Fensters, mit dem Chat-Knopf. Sie hebt sich
    vom Cadwork ab (blaue Linie, runde Ecken), laesst sich am Kopf ziehen,
    geht NICHT auf, wenn man darauf drueckt; der Chat-Knopf oeffnet das
    Fenster darunter (der Kopf bleibt stehen), "Verkleinern" fuehrt zurueck
    (bis K11 die Leiste mit ⤢, Rueckmeldung 2026-09-25)."""
    try:
        m = _mini_lauf()
        pruefe("L20 der Plugin-Klick zeigt die Pille (Koerper zu), keine "
               "Fenster von K11", m["klick"] == (True, True, True),
               m["klick"])
        c = m["chat_symbol"]
        pruefe("L20 im Kopf der Chat-Knopf (objectName chatknopf, 'Chat' als "
               "Name und Tooltip, Symbol bzw. 'Chat')",
               c == (True, True, "chatknopf", "Chat", True, True), c)
        pruefe("L20-K Bewegung ohne Druck verschiebt nichts", m["ohne_druck"])
        pruefe("L20 Druck aufs Logo oeffnet NICHT",
               m["druck_logo"] == (True, True), m["druck_logo"])
        pruefe("L20 am Logo gezogen: das Fenster folgt genau und gilt als "
               "gegriffen", m["gezogen"][:2] == (True, True), m["gezogen"])
        pruefe("L20 ... und das Nachsehen nach dem Zeigen (0/300 ms) setzt "
               "sie NICHT zurueck: nach 350 ms steht sie noch dort",
               m["gezogen_danach"][0], m["gezogen_danach"])
        pruefe("L20 Hand-Zeiger zeigt, dass man ziehen kann; die Knoepfe "
               "zeigen den Finger", m["zeiger"] == (True, True), m["zeiger"])
        pruefe("L20 runde Ecken: die Ecke liegt ausserhalb der Maske, die "
               "Mitte darin", m["aussehen"][0], m["aussehen"])
        pruefe("L20 blaue Umrandung oben", m["aussehen"][1], m["aussehen"])
        pruefe("L20-K ohne die Regeln des Fensters: ohne blaue Linie",
               m["aussehen_k"][0], m["aussehen_k"])
        pruefe("L20 der Chat-Knopf oeffnet das Fenster, der Kopf bleibt "
               "stehen", m["auf"][:3] == (True, True, True), m["auf"])
        pruefe("L20 Verkleinern: zurueck zur Pille",
               m["verkleinert"] == (True, True, True), m["verkleinert"])
        pruefe("L20 ein zweiter Plugin-Klick laesst die Pille stehen (das "
               "Fenster geht nicht auf)",
               m["zweiter_klick"] == (True, True, True), m["zweiter_klick"])
        # KONTROLLEN
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen",
            _beginnt("koerper.setVisible(zustand == OFFEN_Z)"),
            "koerper.setVisible(True)")))
        pruefe("L20 KONTROLLE: zeigt der Bau das ganze Fenster statt der "
               "Pille, ist die erste Zeile rot",
               k["treffer"] == [1] and k["klick"][1] is False,
               (k["treffer"], k["klick"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "oeffnen", _beginnt("_sicher(lambda: _fenster_aktion(z, 'klick')"),
            "_sicher(lambda: _fenster_aktion(z, 'chat'), 'Fenster zeigen')")))
        pruefe("L20 KONTROLLE: oeffnet der zweite Klick das Fenster, ist die "
               "letzte Zeile rot", k["treffer"] == [1]
               and k["zweiter_klick"][1] is False,
               (k["treffer"], k["zweiter_klick"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_kopf_bauen", lambda s: isinstance(s, ast.If)
            and "_knopf_symbol(chat" in ast.unparse(s.test), "pass")))
        pruefe("L20 KONTROLLE: ohne Symbol und Text ist der Chat-Knopf leer "
               "(die Zeile oben wird rot)",
               k["treffer"] == [1] and k["chat_symbol"][5] is False,
               (k["treffer"], k["chat_symbol"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_kopf_bauen",
            _beginnt("self.setCursor(Qt.CursorShape.ClosedHandCursor)"),
            "self.setCursor(Qt.CursorShape.ClosedHandCursor)\n"
            "_fenster_aktion(z, 'chat')")))
        pruefe("L20 KONTROLLE: oeffnete ein Druck auf den Kopf das Fenster, "
               "waere 'Druck aufs Logo' rot", k["treffer"] == [1]
               and k["druck_logo"] == (True, False),
               (k["treffer"], k["druck_logo"]))

        def ohne_gegriffen():
            M = _mutant()
            M.ORT_GEGRIFFEN = {k_: v for k_, v in M.ORT_GEGRIFFEN.items()
                               if k_ != "fenster"}
            return M
        k = _mini_lauf(ohne_gegriffen)
        pruefe("L20 KONTROLLE: kennt das Nachsehen das gegriffene Fenster "
               "nicht, holt es es zurueck (das Flag allein waere gruen)",
               k["gezogen"][:2] == (True, True)
               and k["gezogen_danach"][0] is False,
               (k["gezogen"], k["gezogen_danach"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_kopf_bauen", _beginnt("dock.move(p - self._griff)"))))
        pruefe("L20 KONTROLLE: ohne das Verschieben im Ziehen folgt das "
               "Fenster nicht", k["treffer"] == [1]
               and k["gezogen"][0] is False, (k["treffer"], k["gezogen"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_kopf_bauen",
            _beginnt("self.setCursor(Qt.CursorShape.OpenHandCursor)"))))
        pruefe("L20 KONTROLLE: ohne die offene Hand zeigt nichts, dass man "
               "ziehen kann", k["treffer"] == [2]
               and k["zeiger"][0] is False, (k["treffer"], k["zeiger"]))
        k = _mini_lauf(lambda: _mutant(_anweisungen(
            "_zustand_setzen", _beginnt("koerper.hide()"))))
        pruefe("L20 KONTROLLE: versteckt Verkleinern den Koerper nicht, wird "
               "'zurueck zur Pille' rot", k["treffer"] == [1]
               and k["verkleinert"][0] is False,
               (k["treffer"], k["verkleinert"]))
    finally:
        _frischer_start()


# --- L94: genau EIN Fenster --------------------------------------------------

def _ein_fenster_lauf(laden=None):
    """-> dict: welche Fenster nach dem Klick und nach jedem Wechsel zu
    sehen sind."""
    k = _K12(laden=laden, fremd_dock=True)
    m = {"treffer": k.treffer, "fenster": {}}
    try:
        m["fenster"]["klick"] = _sichtbare_fenster()
        for aktion in ("chat", "andocken", "andocken", "verkleinern"):
            k.aktion(aktion)
            m["fenster"][aktion + "_" + k.z["fenster_zustand"]] = \
                _sichtbare_fenster()
        from PyQt6.QtWidgets import QApplication
        m["k11"] = sorted({wd.objectName() for wd in
                           QApplication.allWidgets()
                           if wd.objectName() in _K11_NAMEN
                           and wd.isVisible()})
        m["name"] = k.f.objectName()
    finally:
        k.ende()
    return m


def zelle_ein_fenster():
    """L94 (K12): nach dem Klick und in jedem Zustand GENAU ein sichtbares
    Fenster von Open MCP CAD — `OpenMcpCadFenster` (angedockt keins
    daneben); Leiste, Steuerfenster und Chat-Dock von K11 gibt es nicht."""
    try:
        m = _ein_fenster_lauf()
        f = m["fenster"]
        pruefe("L94 nach dem Klick genau ein Fenster: OpenMcpCadFenster",
               f["klick"] == ["OpenMcpCadFenster"]
               and m["name"] == "OpenMcpCadFenster", f)
        pruefe("L94 offen, angedockt, wieder offen, Pille: nie ein zweites "
               "(angedockt ist es kein eigenes Fenster mehr)",
               f.get("chat_offen") == ["OpenMcpCadFenster"]
               and f.get("andocken_angedockt") == []
               and f.get("andocken_offen") == ["OpenMcpCadFenster"]
               and f.get("verkleinern_pille") == ["OpenMcpCadFenster"], f)
        pruefe("L94 kein Fenster mit einem Namen von K11 zu sehen",
               m["k11"] == [], m["k11"])
        k = _ein_fenster_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen", _beginnt("_haken_setzen(z)"),
            "_haken_setzen(z)\n"
            "from PyQt6.QtWidgets import QWidget as _QW\n"
            "_leiste = _QW(haupt, Qt.WindowType.Tool)\n"
            "_leiste.setObjectName('OpenMcpCadMini')\n"
            "_leiste.show()\n"
            "z['mini'] = _leiste")))
        pruefe("L94 KONTROLLE: baut der Klick wieder eine Leiste daneben "
               "(wie K11), sind es zwei Fenster und ein Name von K11",
               k["treffer"] == [1] and len(k["fenster"]["klick"]) == 2
               and k["k11"] == ["OpenMcpCadMini"], k)
    finally:
        _frischer_start()


# --- L95: der Kopf -------------------------------------------------------

_KOPF_SOLL = {
    "pille": ["Chat", "Trennen", "Rechts andocken"],
    "offen": ["Chat", "Trennen", "Rechts andocken", "Verkleinern"],
    "angedockt": ["Chat", "Trennen", "Abdocken", "Verkleinern"],
}


def _kopf_lauf(laden=None):
    """-> dict: Kopf je Zustand (Objekt, sichtbare Knoepfe, Titelleiste)."""
    from PyQt6.QtWidgets import QPushButton
    k = _K12(laden=laden)
    m = {"treffer": k.treffer, "zustaende": {}}
    try:
        def messen():
            kopf = k.f.titleBarWidget()
            namen = [b.accessibleName() for b in
                     kopf.findChildren(QPushButton) if b.isVisible()]
            # Ein "×" gibt es seit 2026-10-08 nur OHNE Verbindung (L116);
            # hier ist verbunden: kein SICHTBARES.
            einst = [b.accessibleName() for b in kopf.findChildren(QPushButton)
                     if "instellung" in b.accessibleName()
                     or b.property("symbol") == "einstellungen"
                     or (b.property("symbol") == "schliessen"
                         and b.isVisible())]
            return {"id": id(kopf), "namen": namen, "einst": einst,
                    "hoehen": sorted({b.height() for b in
                                      kopf.findChildren(QPushButton)
                                      if b.isVisible()
                                      and b.objectName() != "kopf_chip"}),
                    "hoehe": kopf.height(), "dock": k.f.height()}
        m["zustaende"]["pille"] = messen()
        k.aktion("chat")
        m["zustaende"]["offen"] = messen()
        k.aktion("andocken")
        m["zustaende"]["angedockt"] = messen()
        k.aktion("verkleinern")
        m["zustaende"]["pille2"] = messen()
        m["kopf"] = id(k.w["kopf"])
    finally:
        k.ende()
    return m


def zelle_kopf():
    """L95 (K12, Spezifikation 2.1): der Kopf ist in Pille, offen und
    angedockt DASSELBE Objekt (die einzige Titelleiste); sichtbar genau die
    Knoepfe der Tabelle (Verkleinern nur offen und angedockt, angedockt
    "Abdocken"); kein Einstellungsknopf, verbunden kein Schliessen (ohne
    Verbindung das "×", L116); Knoepfe 28 px."""
    try:
        m = _kopf_lauf()
        z_ = m["zustaende"]
        pruefe("L95 der Kopf ist in allen Zustaenden dasselbe Objekt",
               len({v["id"] for v in z_.values()} | {m["kopf"]}) == 1,
               {k_: v["id"] for k_, v in z_.items()})
        pruefe("L95 sichtbare Knoepfe je Zustand wie Tabelle 2.1",
               all(z_[s]["namen"] == _KOPF_SOLL[s.rstrip("2")]
                   for s in z_), {k_: v["namen"] for k_, v in z_.items()})
        pruefe("L95 kein Einstellungsknopf, verbunden kein Schliessen im "
               "Kopf",
               all(v["einst"] == [] for v in z_.values()),
               {k_: v["einst"] for k_, v in z_.items()})
        pruefe("L95 Knoepfe 28 px hoch; die Pille %d px (44 +-2)"
               % z_["pille"]["dock"],
               all(v["hoehen"] == [28] for v in z_.values())
               and abs(z_["pille"]["dock"] - 44) <= 2,
               {k_: (v["hoehen"], v["dock"]) for k_, v in z_.items()})
        k = _kopf_lauf(lambda: _mutant(_anweisungen(
            "_kopf_bauen", _beginnt("klein.hide()"),
            "klein.hide()\nlay.addWidget(knopf('kopf_einst', "
            "'Einstellungen', 'Einstellungen', "
            "lambda: _einstellungen_zeigen(z, True)))")))
        pruefe("L95 KONTROLLE: mit ⚙ im Kopf werden Tabelle und 'kein "
               "Einstellungsknopf' rot", k["treffer"] == [1]
               and k["zustaende"]["pille"]["einst"] == ["Einstellungen"]
               and k["zustaende"]["pille"]["namen"] != _KOPF_SOLL["pille"],
               k["zustaende"]["pille"])
        k = _kopf_lauf(lambda: _mutant(_anweisungen(
            "_zustand_setzen", _beginnt("z['fenster_zustand'] = neu"),
            "z['fenster_zustand'] = neu\n"
            "dock.setTitleBarWidget(_kopf_bauen(z, dock))")))
        pruefe("L95 KONTROLLE: baut jeder Zustand seinen eigenen Kopf, ist es "
               "nicht mehr dasselbe Objekt", k["treffer"] == [1]
               and len({v["id"] for v in k["zustaende"].values()}) > 1,
               {k_: v["id"] for k_, v in k["zustaende"].items()})
    finally:
        _frischer_start()


# --- L96: der Ort der Pille (K10-Regel, Windows-Nachahmer, zwei Schirme) ----

def _ort_lauf(laden=None, nachahmer=True, ort=(120, 60), groesse=(640, 700),
              spaet_ms=100, fremd_dock=False):
    """-> dict: wo die Pille steht, wo sie stehen soll, was das Log sagt;
    mit `fremd_dock` ein eigenes Dock von Cadwork rechts: ob die Pille
    darueber liegt."""
    k = _K12(laden=laden, nachahmer=nachahmer, spaet_ms=spaet_ms, ort=ort,
             groesse=groesse, fremd_dock=fremd_dock)
    m = {"treffer": k.treffer}
    try:
        _pumpen(0.4)
        h = _global(k.haupt, rahmen=False)
        mitte = _global(k.haupt.centralWidget())
        g = _global(k.f)
        m["haupt"], m["pille"], m["mitte"] = h, g, mitte
        # Gegenpruefung K12: am rechten Rand der ZEICHENFLAECHE (ohne Dock
        # rechts derselbe wie der des Hauptfensters).
        m["soll"] = (mitte[2] - k.D.MONITOR_ABSTAND[0],
                     mitte[1] + k.D.MONITOR_ABSTAND[1])
        if k.fremd is not None:
            fd = _global(k.fremd, rahmen=False)
            m["fremd"] = fd
            m["ueber_fremd"] = not (g[2] <= fd[0] or fd[2] <= g[0]
                                    or g[3] <= fd[1] or fd[3] <= g[1])
        m["ort"] = (abs(g[2] - m["soll"][0]) <= 2
                    and abs(g[1] - m["soll"][1]) <= 2)
        m["hoehe"] = g[3] - g[1]
        m["log"] = [z_ for z_ in k.ausgang.zeilen
                    if z_.startswith("Fenster: pille gesetzt")]
        m["zentriert"] = list(k.filt.zentriert) if k.filt else []
        # Offen: der Kopf bleibt, der Koerper bis RAND_UNTEN ueber dem
        # unteren Rand des Hauptfensters.
        k.aktion("chat")
        o = _global(k.f)
        m["offen"] = (abs(o[2] - g[2]) <= 2, abs(o[1] - g[1]) <= 2,
                      abs(o[3] - (h[3] - k.D.RAND_UNTEN)) <= 3,
                      o[2] - o[0])
        m["offen_g"] = o
    finally:
        k.ende()
    return m


def _alte_fenster_reihenfolge():
    """Mutant: die Signale VOR `setFloating` verbunden, die Lage IM Signal
    gesetzt (wie K9) und ohne das Nachsehen — der Fehler aus K10."""
    M = _mutant(
        _anweisungen("_fenster_bauen",
                     _beginnt("_fenster_lage(z, vor_show=True)"), "pass"),
        _anweisungen("_fenster_bauen", _beginnt("dock.setFloating(True)"),
                     "dock.topLevelChanged.connect(lambda s: "
                     "_fenster_lage(z, vor_show=True))\n"
                     "dock.setFloating(True)"),
        _anweisungen("_fenster_bauen", _beginnt("_kopf_anpassen(z)")))
    # Alle Sicherungen weg: das Nachsehen (K10) und das Nachfuehren der
    # rechten Kante im Takt (K12) holten die Pille sonst zurueck.
    M.ORT_NACHSEHEN_MS = ()
    M._kopf_anpassen = lambda z: None
    return M


def _k12_kind():
    """Im KIND-Prozess (zwei Bildschirme, L96): der Ersatz auf dem ZWEITEN
    Bildschirm links vom ersten, dazu die Kontrolle ohne globale
    Koordinaten. Druckt eine JSON-Zeile."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QApplication
    global _APP
    _APP = QApplication.instance() or QApplication([])
    _draht_legen()
    schirme = [(s.name(), s.geometry().getRect()) for s in _APP.screens()]
    m = _ort_lauf(ort=(-1300, 320), groesse=(1100, 720))
    M = _mutant()
    M._haupt_rahmen = lambda h: QRect(QPoint(0, 0), h.size())
    k = _ort_lauf(lambda: M, ort=(-1300, 320), groesse=(1100, 720))
    print("K12KIND " + json.dumps({
        "schirme": schirme, "primaer": _APP.primaryScreen().name(),
        "m": {k_: m[k_] for k_ in ("haupt", "pille", "soll", "ort",
                                   "offen", "offen_g")},
        "k": {k_: k[k_] for k_ in ("pille", "soll", "ort")}}))
    return 0


def zelle_ort_pille():
    """L96 (K12, die Regel aus K10): die Pille oben rechts im Hauptfenster
    (rechte Kante = Hauptfenster - 16, Oberkante = Mitte + 12, je +-2),
    44 +-2 hoch, auch mit dem Windows-Nachahmer (Fenster ohne WA_Moved in
    die Mitte, dazu 100 ms nach dem Zeigen noch einmal); eine Zeile
    "Fenster: pille gesetzt" im Log; offen bleibt der Kopf, der Koerper
    reicht bis 16 px ueber den unteren Rand. Auf einem ZWEITEN Bildschirm
    links (negative Koordinaten) ebenso — im Kind-Prozess."""
    try:
        m = _ort_lauf()
        pruefe("L96 die Pille steht oben rechts im Hauptfenster (Ersatz bei "
               "120/60, Nachahmer an): %s, soll %s" % (m["pille"], m["soll"]),
               m["ort"], m)
        pruefe("L96 sie ist 44 +-2 px hoch", abs(m["hoehe"] - 44) <= 2,
               m["hoehe"])
        pruefe("L96 eine Zeile 'Fenster: pille gesetzt' im Log der Instanz",
               len(m["log"]) >= 1 and "Hauptfenster" in m["log"][0],
               m["log"][:1])
        pruefe("L96 offen: Kopf an derselben Stelle, Koerper bis RAND_UNTEN "
               "ueber dem unteren Rand des Hauptfensters, 420 px breit",
               m["offen"][:3] == (True, True, True)
               and m["offen"][3] == 420, (m["offen"], m["offen_g"]))
        f = _ort_lauf(fremd_dock=True, nachahmer=False)
        pruefe("L96 mit einem Dock von Cadwork rechts: die Pille am rechten "
               "Rand der ZEICHENFLAECHE, nicht ueber dem Dock "
               "(Gegenpruefung K12)", f["ort"] and f["ueber_fremd"] is False
               and f["mitte"][2] < f["haupt"][2] - 40,
               (f["pille"], f["soll"], f.get("fremd")))
        M = _mutant(_anweisungen("_monitor_ziel",
                                 _beginnt("rechts = m_rechts"), "pass"))
        k = _ort_lauf(lambda: M, fremd_dock=True, nachahmer=False)
        pruefe("L96 KONTROLLE: am rechten Rand des HAUPTFENSTERS (bis K12) "
               "liegt die Pille ueber dem Dock von Cadwork",
               M._mutant_treffer == [1] and k["ueber_fremd"] is True,
               (k["pille"], k.get("fremd")))
        k = _ort_lauf(_alte_fenster_reihenfolge)
        pruefe("L96 KONTROLLE: Lage im Signal topLevelChanged (K9) und ohne "
               "Nachsehen -> die Pille steht in der Mitte (Nachahmer)",
               k["treffer"] == [1, 1, 1] and not k["ort"]
               and "OpenMcpCadFenster" in k["zentriert"],
               (k["treffer"], k["pille"], k["zentriert"]))
        k = _ort_lauf(_alte_fenster_reihenfolge, nachahmer=False)
        pruefe("L96 KONTROLLE: ohne Nachahmer stuende derselbe Mutant oben "
               "(nicht in der Mitte) — darum braucht die Zelle den Nachahmer",
               k["zentriert"] == []
               and abs(k["pille"][1] - k["soll"][1]) <= 2,
               (k["pille"], k["soll"]))
        M = _mutant()
        M._ort_protokoll = lambda z, text: None
        k = _ort_lauf(lambda: M)
        pruefe("L96 KONTROLLE: ohne Zeile ins Log fehlt sie", k["log"] == [],
               k["log"])
    finally:
        _frischer_start()
    # Zwei Bildschirme im Kind-Prozess (offscreen kennt sonst nur einen).
    t = _tempfile.mkdtemp(prefix="omcad_k12_schirme_")
    with open(os.path.join(t, "schirm.json"), "w") as fh:
        json.dump({"screens": [
            {"name": "haupt", "x": 0, "y": 0, "width": 1280,
             "height": 800, "logicalDpi": 96, "logicalBaseDpi": 96,
             "dpr": 1},
            {"name": "links", "x": -1440, "y": 200, "width": 1440,
             "height": 900, "logicalDpi": 96, "logicalBaseDpi": 96,
             "dpr": 1}]}, fh)
    env = dict(os.environ)
    # RELATIV: der Doppelpunkt in "C:" trennte sonst die Optionen.
    env["QT_QPA_PLATFORM"] = "offscreen:configfile=schirm.json"
    env["PYTHONIOENCODING"] = "utf-8"
    erg = subprocess.run([sys.executable, os.path.abspath(__file__),
                          "--k12-kind"], cwd=t, env=env,
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=240)
    zeile = [z_ for z_ in erg.stdout.splitlines()
             if z_.startswith("K12KIND ")]
    if not zeile:
        pruefe("L96 Kind-Prozess mit zwei Bildschirmen lief", False,
               (erg.returncode, erg.stdout[-500:], erg.stderr[-1500:]))
        return
    d = json.loads(zeile[-1][len("K12KIND "):])
    links = [g for n, g in d["schirme"] if n == "links"]
    lx, ly, lb, lh = links[0] if links else (0, 0, 0, 0)

    def auf_links(r):
        return lx <= r[0] and r[2] <= lx + lb and ly <= r[1] \
            and r[3] <= ly + lh
    m, k = d["m"], d["k"]
    pruefe("L96 zweiter Bildschirm links: die Pille oben rechts im "
           "Hauptfenster dort (%s), nicht auf dem Hauptbildschirm"
           % (m["pille"],), d["primaer"] == "haupt" and m["ort"]
           and auf_links(m["pille"]) and m["pille"][0] < 0, d)
    pruefe("L96 ... und offen ebenso dort, der Kopf bleibt",
           tuple(m["offen"][:2]) == (True, True)
           and auf_links(m["offen_g"]), m["offen_g"])
    pruefe("L96 KONTROLLE: ohne globale Koordinaten des Hauptfensters stuende "
           "die Pille NICHT auf dem zweiten Bildschirm",
           not k["ort"] and k["pille"][0] >= 0, k)


# --- L97: Uebergaenge, der Chat bleibt (nichts umgehaengt) -------------------

class _Elternwechsel:
    """Ein Ereignisfilter, der jedes ParentChange an den beobachteten
    Widgets zaehlt — auch eines, das Qt in C++ ausloest (setWidget,
    addWidget)."""

    def __init__(self, teile):
        from PyQt6.QtCore import QEvent, QObject

        class F(QObject):
            def __init__(self):
                super().__init__()
                self.n = []

            def eventFilter(self, obj, ev):            # noqa: N802
                try:
                    if ev.type() == QEvent.Type.ParentChange:
                        self.n.append(obj.objectName() or type(obj).__name__)
                except Exception:                      # noqa: BLE001
                    pass
                return False
        self.f = F()
        self.teile = list(teile)
        for t in self.teile:
            t.installEventFilter(self.f)

    def weg(self):
        for t in self.teile:
            try:
                t.removeEventFilter(self.f)
            except RuntimeError:
                pass


def _uebergang_lauf(laden=None):
    """a->b->a, a->c->b->a, c->a. -> dict: Kopf je Schritt, Koerper, Fokus,
    Elternwechsel am Chat, ids, der Chat lebt."""
    k = _K12(laden=laden, fremd_dock=True)
    D, z, w, f = k.D, k.z, k.w, k.f
    m = {"treffer": k.treffer, "schritte": []}
    proc = _ProzessAttrappe()
    z["chat"].update(an=True, laeuft_zug=False, anbieter="claude",
                     kurzname="Claude", proc=proc, freigaben=[],
                     ereignisse=[{"art": "ich", "text": "Hallo"},
                                 {"art": "text", "text": "Antwort"}],
                     stand=z["chat"].get("stand", 0) + 1)
    D._chat_zeichnen(z)
    seite = w["seiten"].widget(0)
    ids = (id(seite), id(w["chat_verlauf"]), id(w["chat_eingabe"]),
           id(w["koerper"]))
    draht = _Elternwechsel([seite, w["chat_verlauf"], w["chat_eingabe"],
                            w["koerper"], w["seiten"]])
    try:
        start = k.kopf_g()

        def schritt(aktion):
            vor = k.kopf_g() if f.isFloating() else None
            zust = k.aktion(aktion)
            nach = k.kopf_g() if f.isFloating() else None
            feld = w["chat_eingabe"]
            m["schritte"].append({
                "aktion": aktion, "zustand": zust,
                "koerper": not w["koerper"].isHidden(),
                "kopf_fest": (vor is None or nach is None
                              or (abs(vor[0] - nach[0]) <= 2
                                  and abs(vor[1] - nach[1]) <= 2)),
                "am_ort": nach is None or (abs(nach[0] - start[0]) <= 2
                                           and abs(nach[1] - start[1]) <= 2),
                "fokus": feld.window().focusWidget() is feld})
        for aktion in ("chat", "chat", "andocken", "andocken",
                       "verkleinern", "andocken", "verkleinern"):
            schritt(aktion)
        m["ids_gleich"] = ids == (id(w["seiten"].widget(0)),
                                  id(w["chat_verlauf"]),
                                  id(w["chat_eingabe"]), id(w["koerper"]))
        m["eltern"] = list(draht.f.n)
        m["eltern_kette"] = (seite.parentWidget() is w["seiten"],
                             f.widget() is w["koerper"])
        m["chat_lebt"] = (z["chat"].get("an"), proc.poll() is None,
                          w["chat_verlauf"].count())
    finally:
        draht.weg()
        z["chat"]["an"] = False
        k.ende()
    return m


_SCHRITTE_SOLL = [("chat", "offen", True), ("chat", "pille", False),
                  ("andocken", "angedockt", True),
                  ("andocken", "offen", True),
                  ("verkleinern", "pille", False),
                  ("andocken", "angedockt", True),
                  ("verkleinern", "pille", False)]


def zelle_uebergaenge():
    """L97 (K12, Spezifikation 1.3/1.5): a->b->a, a->c->b->a, c->a — der Kopf
    bleibt an seinem Ort (rechte Kante und Oberkante, +-2), der Koerper
    geht auf und zu, der Chat-Knopf setzt den Fokus in die Eingabe; der
    Chat lebt (Prozess, Verlauf), dieselben Widgets, und NIEMAND haengt
    den Chat oder den Koerper um (kein ParentChange)."""
    try:
        m = _uebergang_lauf()
        s = m["schritte"]
        pruefe("L97 Zustaende und Koerper je Schritt wie die Tabelle",
               [(x["aktion"], x["zustand"], x["koerper"]) for x in s]
               == _SCHRITTE_SOLL, [(x["aktion"], x["zustand"], x["koerper"])
                                   for x in s])
        pruefe("L97 schwebend bleibt der Kopf am Ort der Pille (+-2), auch "
               "nach dem Andocken und Abdocken",
               all(x["kopf_fest"] and x["am_ort"] for x in s),
               [(x["aktion"], x["kopf_fest"], x["am_ort"]) for x in s])
        pruefe("L97 der Chat-Knopf aus der Pille setzt den Fokus in die "
               "Eingabe", s[0]["fokus"], s[0])
        pruefe("L97 dieselben Widgets (Chat-Seite, Verlauf, Eingabe, "
               "Koerper), kein Elternwechsel, der Chat lebt",
               m["ids_gleich"] and m["eltern"] == []
               and m["eltern_kette"] == (True, True)
               and m["chat_lebt"] == (True, True, 2), m)
        k = _uebergang_lauf(lambda: _mutant(_anweisungen(
            "_zustand_setzen", _beginnt("z['fenster_zustand'] = neu"),
            "z['fenster_zustand'] = neu\n"
            "_tab_chat_oder_ersatz(z, z['w']['seiten'])")))
        pruefe("L97 KONTROLLE: baut ein Wechsel die Chat-Seite neu, sind es "
               "nicht mehr dieselben Widgets", k["treffer"] == [1]
               and not k["ids_gleich"], k["ids_gleich"])
        k = _uebergang_lauf(lambda: _mutant(_anweisungen(
            "_zustand_setzen", _beginnt("z['fenster_zustand'] = neu"),
            "z['fenster_zustand'] = neu\n"
            "koerper.setParent(None)\ndock.setWidget(koerper)")))
        pruefe("L97 KONTROLLE: haengt ein Wechsel den Koerper um (auch "
               "zurueck an dieselbe Stelle), meldet der Draht es",
               k["treffer"] == [1] and k["eltern"] != [], k["eltern"])
    finally:
        _frischer_start()


# --- L98: angedockt = EINE Spalte -------------------------------------------

def _angedockt_lauf(laden=None, groesse=(1000, 700)):
    """Cadwork-Ersatz mit eigenem Dock rechts; das Fenster angedockt.
    -> dict."""
    from PyQt6.QtCore import Qt
    k = _K12(laden=laden, fremd_dock=True, ort=(20, 40), groesse=groesse)
    m = {"treffer": k.treffer}
    try:
        h_vorher = k.haupt.height()
        k.aktion("andocken", 0.5)
        haupt, f = k.haupt, k.f
        m["reiter"] = [d.objectName() for d in haupt.tabifiedDockWidgets(f)]
        m["bereich"] = haupt.dockWidgetArea(f) \
            == Qt.DockWidgetArea.RightDockWidgetArea
        m["schwebt"] = f.isFloating()
        m["hoehe"] = (f.height(), k.fremd.height())
        m["breite"] = f.width()
        m["haupt"] = (h_vorher, haupt.height())
        # Nebeneinander, nicht uebereinander: gleiche Oberkante, verschiedene
        # x-Bereiche.
        gf, gx = _global(f, rahmen=False), _global(k.fremd, rahmen=False)
        m["spalte"] = (gf[1] == gx[1], gf[0] >= gx[2] or gx[0] >= gf[2])
        m["log"] = [z_ for z_ in k.ausgang.zeilen
                    if z_.startswith("Fenster: angedockt gesetzt")]
    finally:
        k.ende()
    return m


def zelle_angedockt():
    """L98 (K12, Bild 6/7): angedockt ist das Fenster EINE eigene Spalte
    rechts neben Cadworks Dock — nicht in Reitern, nicht darueber oder
    darunter gestapelt; volle Hoehe, 420 px breit; ein niedriges
    Hauptfenster waechst dabei nicht."""
    try:
        m = _angedockt_lauf()
        pruefe("L98 angedockt rechts, keine Reiter mit Cadworks Dock",
               m["reiter"] == [] and m["bereich"] and not m["schwebt"], m)
        pruefe("L98 eine eigene Spalte: neben dem Dock von Cadwork, gleiche "
               "Oberkante, volle Hoehe (wie das Dock von Cadwork, +-4)",
               m["spalte"] == (True, True)
               and abs(m["hoehe"][0] - m["hoehe"][1]) <= 4, m)
        pruefe("L98 %d px breit (420 +-4)" % m["breite"],
               abs(m["breite"] - 420) <= 4, m["breite"])
        pruefe("L98 eine Zeile 'Fenster: angedockt gesetzt' im Log",
               len(m["log"]) >= 1, m["log"][:1])
        n = _angedockt_lauf(groesse=(1000, 560))
        pruefe("L98 ein niedriges Hauptfenster (560 px) waechst nicht",
               n["haupt"][0] == n["haupt"][1] and n["reiter"] == [],
               n["haupt"])
        k = _angedockt_lauf(lambda: _mutant(
            _anweisungen("_zustand_setzen", lambda s: isinstance(s, ast.Expr)
                         and "haupt.addDockWidget(" in ast.unparse(s),
                         "haupt.addDockWidget(_bereich(z.get("
                         "'angedockt_bereich')), dock)\n"
                         "[haupt.tabifyDockWidget(d_, dock) for d_ in "
                         "haupt.findChildren(type(dock)) if d_ is not dock "
                         "and not d_.isFloating()][:1]"),
            _anweisungen("_angedockt_pruefen", lambda s: isinstance(s, ast.If)
                         and "reiter" in ast.unparse(s.test))))
        pruefe("L98 KONTROLLE: tabifyDockWidget (Bild 6) und ohne das "
               "Herausnehmen -> Reiter", k["treffer"] == [1, 1]
               and k["reiter"] == ["CadworkEigenschaften"], k)
        k = _angedockt_lauf(lambda: _mutant(_anweisungen(
            "_zustand_setzen", lambda s: isinstance(s, ast.Expr)
            and "haupt.addDockWidget(" in ast.unparse(s),
            "haupt.addDockWidget(_bereich(z.get('angedockt_bereich')), dock, "
            "Qt.Orientation.Vertical)")))
        pruefe("L98 KONTROLLE: Vertical (Bild 7) -> gestapelt, nicht volle "
               "Hoehe", k["treffer"] == [1]
               and (k["spalte"] != (True, True)
                    or abs(k["hoehe"][0] - k["hoehe"][1]) > 4), k)
    finally:
        _frischer_start()


# --- L99: Segmente, Werkzeuge, Hinweise, Einstellungen ---------------------

def _segmente_lauf(laden=None):
    """-> dict: was in welchem Segment steht und was die Knoepfe rufen."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        k.aktion("chat")
        chat_seite = w["seiten"].widget(0)
        brief = w["briefkasten_seite"]
        werkzeuge = ("btn_undo", "btn_redo", "btn_neu", "hinweise_knopf",
                     "mehr_menue")
        m["liste"] = (chat_seite.isAncestorOf(w["liste_auftraege"]),
                      brief.isAncestorOf(w["liste_auftraege"]))
        m["werkzeuge_chat"] = [w[n].isVisible() for n in werkzeuge]
        d = z["dienst"]
        n0 = len(d.job_queue.items)
        for n in ("btn_undo", "btn_redo", "btn_neu"):
            w[n].click()
        m["rufe_chat"] = [j.methode for j in d.job_queue.items[n0:]]
        w["hinweise_knopf"].click()
        m["hinweise_chat"] = not w["hinweise_bereich"].isHidden()
        w["hinweise_knopf"].click()
        w["segment_briefkasten"].click()
        _pumpen(0.05)
        m["brief_vorn"] = (w["seiten"].currentWidget() is brief,
                           w["segment_briefkasten"].isChecked(),
                           not w["segment_chat"].isChecked(),
                           z["segment"])
        m["werkzeuge_brief"] = [w[n].isVisible() for n in werkzeuge]
        n0 = len(d.job_queue.items)
        for n in ("btn_undo", "btn_redo", "btn_neu"):
            w[n].click()
        m["rufe_brief"] = [j.methode for j in d.job_queue.items[n0:]]
        w["hinweise_knopf"].click()
        m["hinweise_brief"] = not w["hinweise_bereich"].isHidden()
        w["hinweise_zu"].click()
        m["hinweise_zu"] = w["hinweise_bereich"].isHidden()
        # Ohne Verbindung: die Werkzeuge aus.
        z["dienst"].beenden = True
        D._auffrischen(z)
        m["ohne_dienst"] = [w[n].isEnabled() for n in ("btn_undo", "btn_redo",
                                                       "btn_neu")]
        z["dienst"].beenden = False
        D._auffrischen(z)
        # ⋯ -> Einstellungen -> Zurueck: zum gemerkten Segment (Briefkasten).
        w["mehr_menue"].click()
        w["mehr_einst"].click()
        _pumpen(0.05)
        einst = w["seiten"].currentWidget() is w["einst_seite"]
        w["einst_zurueck"].click()
        _pumpen(0.05)
        m["einst"] = (einst, w["seiten"].currentWidget() is brief)
        # Tastatur: Ctrl+1 = Chat.
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        w["post_eingabe"].setFocus()
        QTest.keyClick(w["post_eingabe"], Qt.Key.Key_1,
                       Qt.KeyboardModifier.ControlModifier)
        m["taste"] = w["seiten"].currentWidget() is chat_seite
    finally:
        k.ende()
    return m


def zelle_segmente():
    """L99 (K12, Spezifikation 3): "Chat | Briefkasten" — die Liste der
    Auftraege nur im Briefkasten (im Chat zeigt der Verlauf die Schritte);
    Rueckgaengig, Wiederherstellen und Neu zeichnen in BEIDEN Segmenten
    sichtbar und mit den heutigen Auftraegen (undo, redo, neu_zeichnen =
    redraw_view des Servers), ohne Verbindung aus; die Hinweise in beiden
    Segmenten; "⋯ → Einstellungen" und "← Zurück" zum gemerkten Segment;
    Ctrl+1."""
    try:
        m = _segmente_lauf()
        pruefe("L99 die Auftragsliste nur im Briefkasten",
               m["liste"] == (False, True), m["liste"])
        pruefe("L99 Werkzeuge, Hinweise und '⋯' in beiden Segmenten zu sehen",
               all(m["werkzeuge_chat"]) and all(m["werkzeuge_brief"]),
               (m["werkzeuge_chat"], m["werkzeuge_brief"]))
        pruefe("L99 in beiden Segmenten rufen sie undo, redo, neu_zeichnen "
               "(ueber die Warteschlange)",
               m["rufe_chat"] == ["undo", "redo", "neu_zeichnen"]
               and m["rufe_brief"] == ["undo", "redo", "neu_zeichnen"],
               (m["rufe_chat"], m["rufe_brief"]))
        pruefe("L99 der Briefkasten kommt nach vorn (gemerkt)",
               m["brief_vorn"] == (True, True, True, "briefkasten"),
               m["brief_vorn"])
        pruefe("L99 die Hinweise gehen in beiden Segmenten auf, "
               "'Schliessen' klappt zu",
               m["hinweise_chat"] and m["hinweise_brief"]
               and m["hinweise_zu"], m)
        pruefe("L99 ohne Verbindung sind die Werkzeuge aus",
               m["ohne_dienst"] == [False, False, False], m["ohne_dienst"])
        pruefe("L99 '⋯ → Einstellungen', dann '← Zurück' zum Briefkasten; "
               "Ctrl+1 waehlt den Chat",
               m["einst"] == (True, True) and m["taste"],
               (m["einst"], m["taste"]))
        k = _segmente_lauf(lambda: _mutant(_anweisungen(
            "_koerper_bauen", _beginnt("seiten.addWidget(_briefkasten_bauen"),
            "seiten.addWidget(_briefkasten_bauen(z))\n"
            "seiten.widget(0).layout().insertWidget(0, "
            "z['w']['liste_auftraege'])")))
        pruefe("L99 KONTROLLE: die Auftragsliste im Chat (Mutant) wird rot",
               k["treffer"] == [1] and k["liste"][0] is True, k["liste"])
        k = _segmente_lauf(lambda: _mutant(_anweisungen(
            "_koerper_bauen", _beginnt("seiten.addWidget(_briefkasten_bauen"),
            "seiten.addWidget(_briefkasten_bauen(z))\n"
            "for _n in ('btn_undo', 'btn_redo', 'btn_neu'):\n"
            "    z['w']['briefkasten_seite'].layout().insertWidget("
            "0, z['w'][_n])")))
        pruefe("L99 KONTROLLE: die Werkzeuge nur im Briefkasten (Mutant) -> "
               "im Chat nicht zu sehen", k["treffer"] == [1]
               and not all(k["werkzeuge_chat"]), k["werkzeuge_chat"])
    finally:
        _frischer_start()


# --- L100: der Anker, Schliessen von aussen ---------------------------------

def _anker_lauf(laden=None, im_signal=False):
    """Zustand, Ort, Segment, Hinweise gemerkt; Neubau; frischer Anker;
    Schliessen von aussen. -> dict."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        # Die Pille verschieben (Ort), offen, Briefkasten, Hinweise auf.
        from PyQt6.QtCore import QEvent, QPoint, Qt
        kopf = w["kopf"]
        start = _maus(kopf, QEvent.Type.MouseButtonPress, QPoint(30, 10))
        ziel = start + QPoint(-60, 30)
        _maus(kopf, QEvent.Type.MouseMove, kopf.mapFromGlobal(ziel),
              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        _maus(kopf, QEvent.Type.MouseButtonRelease, kopf.mapFromGlobal(ziel))
        _pumpen(0.35)
        ort = k.kopf_g()
        k.aktion("chat")
        w["segment_briefkasten"].click()
        D._hinweise_zeigen(z, True)
        # Neubau (andere FORM).
        z["form"] = -1
        D2, z2, _r = _klick(k.client, k.kern, verbinden=False, laden=laden)
        _pumpen(0.4)
        w2, f2 = z2["w"], z2["fenster"]
        g = _global(f2)
        m["neubau"] = (z2["fenster_zustand"], not w2["koerper"].isHidden(),
                       w2["seiten"].currentWidget() is w2["briefkasten_seite"],
                       not w2["hinweise_bereich"].isHidden(),
                       abs(g[2] - ort[0]) <= 2 and abs(g[1] - ort[1]) <= 2)
        # Cadwork schliesst das Dock (Kontextmenue, Alt+F4). Gemessen wird
        # auch, OB das Dock im Signal handelt: `_zustand_setzen` waehrend
        # `close()` hiesse, im Signal.
        aufrufe, im_close = [], [False]
        echt_zs = D2._zustand_setzen

        def zs(z_, neu):
            aufrufe.append((neu, im_close[0]))
            return echt_zs(z_, neu)
        D2._zustand_setzen = zs
        im_close[0] = True
        f2.close()
        im_close[0] = False
        m["sofort"] = f2.isVisible()
        _pumpen(0.4)
        g = _global(f2)
        m["geschlossen"] = (f2.isVisible(), w2["koerper"].isHidden(),
                            z2["fenster_zustand"],
                            abs(g[2] - ort[0]) <= 2
                            and abs(g[1] - ort[1]) <= 2)
        m["im_signal"] = [a for a in aufrufe if a[1]]
        D2._zustand_setzen = echt_zs
        # Gegenpruefung K12 (vorher L88): schliesst Cadwork das ANGEDOCKTE
        # Fenster (Kontextmenue der Docks), kommt die Pille an ihren Ort.
        D2._fenster_aktion(z2, "chat")
        _pumpen(0.3)
        D2._fenster_aktion(z2, "andocken")
        _pumpen(0.4)
        m["angedockt_vorher"] = (z2["fenster_zustand"], f2.isFloating())
        f2.close()
        _pumpen(0.4)
        g = _global(f2)
        m["angedockt_zu"] = (f2.isVisible(), f2.isFloating(),
                             w2["koerper"].isHidden(), z2["fenster_zustand"],
                             abs(g[2] - ort[0]) <= 2
                             and abs(g[1] - ort[1]) <= 2)
        # Eine neue Sitzung (frischer Anker): die Pille.
        _frischer_start()
        D3, z3, _r = _klick(k.client, k.kern, verbinden=False, laden=laden)
        _pumpen(0.1)
        m["neu"] = (z3["fenster_zustand"], z3["w"]["koerper"].isHidden(),
                    z3["segment"])
    finally:
        k.ende()
    return m


def zelle_anker():
    """L100 (K12, Spezifikation 1.4): ein Neubau (Update ohne Neustart)
    stellt Zustand, Ort der Pille, Segment und Hinweise wieder her; eine
    neue Sitzung beginnt mit der Pille; schliesst Cadwork das Dock, steht
    danach die Pille am Ort (nicht im Signal, sondern danach)."""
    try:
        m = _anker_lauf()
        pruefe("L100 Neubau: offen, Briefkasten vorn, Hinweise auf, der Kopf "
               "am gezogenen Ort", m["neubau"] == ("offen", True, True, True,
                                                   True), m["neubau"])
        pruefe("L100 Cadwork schliesst das Dock: danach die Pille am Ort — "
               "gesetzt NACH dem Signal, nicht darin",
               m["geschlossen"] == (True, True, "pille", True)
               and m["im_signal"] == [], m)
        pruefe("L100 neue Sitzung (frischer Anker): die Pille, Chat",
               m["neu"] == ("pille", True, "chat"), m["neu"])
        pruefe("L100 Cadwork schliesst das ANGEDOCKTE Fenster: danach die "
               "Pille am Ort (vorher L88)",
               m["angedockt_vorher"] == ("angedockt", False)
               and m["angedockt_zu"] == (True, True, True, "pille", True),
               (m["angedockt_vorher"], m["angedockt_zu"]))
        k = _anker_lauf(lambda: _mutant(_anweisungen(
            "_pille_statt_nichts", lambda s: isinstance(s, ast.If)
            and ast.unparse(s).startswith("if not dock.isHidden()"),
            "if not dock.isHidden() or not dock.isFloating():\n"
            "    return False")))
        pruefe("L100 KONTROLLE: nur schwebend die Pille (Mutant) -> nach dem "
               "Schliessen des angedockten Fensters steht nichts da",
               k["treffer"] == [1] and k["angedockt_zu"][0] is False,
               k["angedockt_zu"])
        k = _anker_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen", _beginnt("zustand = z.get('fenster_zustand')"),
            "zustand = PILLE_Z")))
        pruefe("L100 KONTROLLE: ohne Wiederherstellen steht nach dem Neubau "
               "die Pille", k["treffer"] == [1]
               and k["neubau"][0] == "pille", k["neubau"])
        k = _anker_lauf(lambda: _mutant(_anweisungen(
            "_fenster_sichtbar", lambda s: isinstance(s, ast.Expr)
            and "singleShot" in ast.unparse(s),
            "_pille_statt_nichts(z, dock)")))
        pruefe("L100 KONTROLLE: handelt das Dock IM Signal, sieht die Zelle "
               "es", k["treffer"] == [1] and k["im_signal"] != [],
               (k["geschlossen"], k["im_signal"]))
    finally:
        _frischer_start()


# --- L101: Update aus K11 ohne Cadwork-Neustart -----------------------------

def _k11_anker_bauen(proc):
    """Ein Anker, wie ihn ein K11-Dashboard (FORM 16) hinterlaesst: Leiste,
    Steuerfenster und Chat-Dock offen, ihre Merker, ein laufender Chat."""
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import (QApplication, QDockWidget, QLabel,
                                 QMainWindow, QWidget)
    D0 = dashboard_laden()
    z = D0._zustand()
    haupt = [wd for wd in QApplication.topLevelWidgets()
             if isinstance(wd, QMainWindow) and wd.isVisible()][-1]
    mini = QWidget(haupt, Qt.WindowType.Tool
                   | Qt.WindowType.FramelessWindowHint)
    mini.setObjectName("OpenMcpCadMini")
    mini.resize(260, 44)
    mini.show()
    steuer = QDockWidget("Open MCP CAD", haupt)
    steuer.setObjectName("OpenMcpCadADock")
    steuer.setWidget(QLabel("Steuerfenster (K11)"))
    haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, steuer)
    steuer.setFloating(True)
    steuer.show()
    chat = QDockWidget("Open MCP CAD · Chat", haupt)
    chat.setObjectName("OpenMcpCadChatDock")
    chat.setWidget(QLabel("Chat (K11)"))
    haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, chat)
    chat.setFloating(True)
    chat.show()
    # Das Dock "Aufträge" von K10 (Gegenpruefung K12: vorher fehlte es hier,
    # und ein Mutant ohne es in ALTE_FENSTER blieb gruen).
    auftraege = QDockWidget("Open MCP CAD · Aufträge", haupt)
    auftraege.setObjectName("OpenMcpCadAuftraegeDock")
    auftraege.setWidget(QLabel("Aufträge (K10)"))
    haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, auftraege)
    auftraege.setFloating(True)
    auftraege.show()
    takt = QTimer(steuer)
    takt.start(500)
    for k_ in list(z):
        if k_ in ("fenster", "fenster_zustand", "segment", "hinweise_offen"):
            z.pop(k_)
    z.update(mini=mini, dock=steuer, chatfenster=chat, form=16, timer=takt,
             auftraege_dock=auftraege,
             monitor_angedockt=True, chat_angedockt=False,
             leiste_soll=(1, 2), leiste_rechts_oben=(3, 4),
             leiste_anker=5, chat_ort=(5, 6), chat_platziert=True,
             steuer_war_offen=True, hinweise_offen=3,
             monitor_bereich=2, chat_bereich=2, w={"mini_chat": QLabel()})
    z["chat"].update(an=True, laeuft_zug=False, kurzname="Claude",
                     anbieter="claude", proc=proc, freigaben=[],
                     ereignisse=[{"art": "ich", "text": "Hallo"}],
                     stand=z["chat"].get("stand", 0) + 1)
    return z, (mini, steuer, chat, takt, auftraege)


def _update_lauf(laden=None):
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication
    proc = _ProzessAttrappe()
    alt = {}

    def anker():
        alt["z"], alt["fenster"] = _k11_anker_bauen(proc)
        alt["chat"] = alt["z"]["chat"]
    k = _K12(laden=laden, anker=anker)
    m = {"treffer": k.treffer}
    try:
        z = k.z
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _pumpen(0.1)
        m["fenster"] = _sichtbare_fenster()
        m["alt_weg"] = [sip.isdeleted(x) or not x.isVisible()
                        for x in alt["fenster"][:3] + alt["fenster"][4:]]
        m["takt_alt"] = sip.isdeleted(alt["fenster"][3]) \
            or not alt["fenster"][3].isActive()
        m["schluessel"] = sorted(k_ for k_ in ("monitor_angedockt",
                                               "leiste_soll", "chat_ort",
                                               "steuer_war_offen",
                                               "leiste_rechts_oben",
                                               "monitor_bereich", "mini",
                                               "chatfenster",
                                               "auftraege_dock") if k_ in z)
        m["anker"] = (z is alt["z"], z["hinweise_offen"],
                      z["fenster_zustand"], z["form"] == k.D.FORM)
        m["chat"] = (z["chat"] is alt["chat"], z["chat"].get("an"),
                     proc.poll() is None,
                     k.w["chat_verlauf"].count())
    finally:
        z["chat"]["an"] = False
        k.ende()
    return m


def zelle_update_k11():
    """L101 (K12, Spezifikation 1.6): ein Klick mit einem Anker aus K11
    (Leiste, Steuerfenster, Chat-Dock offen, FORM 16, ihre Merker,
    `hinweise_offen` als Zahl) — danach steht NUR `OpenMcpCadFenster`, die
    alten Fenster und Merker sind weg, der laufende Chat bleibt."""
    try:
        m = _update_lauf()
        pruefe("L101 danach nur noch OpenMcpCadFenster, die drei Fenster von "
               "K11 und das Dock 'Aufträge' von K10 weg, ihr Takt steht",
               m["fenster"] == ["OpenMcpCadFenster"]
               and m["alt_weg"] == [True, True, True, True]
               and m["takt_alt"], m)
        pruefe("L101 die Merker von K11 sind weg; derselbe Anker, die "
               "Hinweise zu (nicht mehr die Zahl), die Pille",
               m["schluessel"] == []
               and m["anker"] == (True, False, "pille", True), m)
        pruefe("L101 der laufende Chat bleibt (dasselbe Gespraech, Prozess "
               "lebt, im Verlauf gezeigt)",
               m["chat"] == (True, True, True, 1), m["chat"])

        def ohne_alte():
            M = _mutant()
            M.ALTE_FENSTER = ()
            return M
        k = _update_lauf(ohne_alte)
        pruefe("L101 KONTROLLE: ohne das Abraeumen der alten Fenster steht "
               "die Leiste von K11 weiter da", "OpenMcpCadMini"
               in k["fenster"] or not all(k["alt_weg"]), k)

        def ohne_k10():
            M = _mutant()
            M.ALTE_FENSTER = ("mini", "chatfenster")
            return M
        k = _update_lauf(ohne_k10)
        pruefe("L101 KONTROLLE: ohne 'auftraege_dock' in ALTE_FENSTER bleibt "
               "das Dock 'Aufträge' von K10 stehen",
               "OpenMcpCadAuftraegeDock" in k["fenster"]
               and k["alt_weg"][3] is False, k)
    finally:
        _frischer_start()
        # Die Kontrolle laesst die nachgebauten Fenster von K11 stehen (ihre
        # Merker sind schon weg, `_frischer_start` findet sie nicht mehr).
        from PyQt6.QtWidgets import QApplication
        for wd in QApplication.topLevelWidgets():
            if wd.isVisible() and wd.objectName() in (
                    "OpenMcpCadMini", "OpenMcpCadADock", "OpenMcpCadChatDock",
                    "OpenMcpCadAuftraegeDock"):
                wd.hide()


# --- L102: der Popover fuer Modell und Denkstufe (Bild 2) -------------------

def _alter_regler(M):
    """Fuer die Kontrolle: der Regler bis K11 — eine Spur (QSlider) MIT dem
    Namen der Stufe daneben; die Spur wird mit "Ultracode" schmaler."""
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget
    ns = M._qt_klassen()

    class Alt(QWidget):
        activated = pyqtSignal(int)
        geaendert = pyqtSignal(int)

        def __init__(self, stufen):
            super().__init__()
            self._s = list(stufen)
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            self.spur = QSlider(Qt.Orientation.Horizontal)
            self.spur.setMaximum(len(self._s) - 1)
            self.t = QLabel(self._s[0][0])
            self.t.setObjectName("neben")
            lay.addWidget(self.spur, 1)
            lay.addWidget(self.t)
            self.spur.valueChanged.connect(self._g)

        def _g(self, i):
            self.t.setText(self._s[i][0])
            self.geaendert.emit(i)

        def count(self):
            return len(self._s)

        def itemData(self, i):                         # noqa: N802
            return self._s[i][1]

        def itemText(self, i):                         # noqa: N802
            return self._s[i][0]

        def currentIndex(self):                        # noqa: N802
            return self.spur.value()

        def currentData(self):                         # noqa: N802
            return self._s[self.spur.value()][1]

        def currentText(self):                         # noqa: N802
            return self._s[self.spur.value()][0]

        def findData(self, wert):                      # noqa: N802
            for i, (_a, w) in enumerate(self._s):
                if w == wert:
                    return i
            return -1

        def setCurrentIndex(self, i):                  # noqa: N802
            self.spur.setValue(i)
    ns.Punktregler = Alt
    return M


def _popover_lauf(laden=None):
    """-> dict: Aufbau, Breiten je Stufe, Text neben der Spur, Tasten,
    Modellliste, Codex, mitten im Chat."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel, QSlider
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        k.aktion("chat")
        _anbieter_waehlen(z, "claude")
        w["chat_modell_knopf"].click()
        QApplication.processEvents()
        pop = w["chat_modell_auf"]
        m["auf"] = (pop.isVisible(),
                    bool(pop.windowFlags() & Qt.WindowType.Popup),
                    QApplication.activeModalWidget() is None,
                    pop.width() == D.POPOVER_BREITE)
        teile = ("stufe_kachel", "stufe_gross", "modell_zeile",
                 "stufe_regler", "stufe_zurueck")
        m["teile"] = {t: pop.isAncestorOf(w[t]) and w[t].isVisible()
                      for t in teile}
        m["gross"] = (w["stufe_gross"].fontInfo().pixelSize(),
                      w["chat_eingabe"].fontInfo().pixelSize())
        regler = w["stufe_regler"]
        spuren = regler.findChildren(QSlider)
        spur = spuren[0] if spuren else regler
        innen = (pop.karte.contentsRect().width()
                 - pop.karte.layout().contentsMargins().left()
                 - pop.karte.layout().contentsMargins().right())
        breiten, namen, daneben = [], [], []
        for i in range(regler.count()):
            regler.setCurrentIndex(i)
            D._popover_fuellen(z)
            QApplication.processEvents()
            breiten.append(spur.width())
            namen.append(w["stufe_gross"].text())
            y = regler.mapTo(pop, QPoint(0, 0)).y()
            daneben += [lb.text() for lb in pop.findChildren(QLabel)
                        if lb.isVisible() and lb.text()
                        and abs(lb.mapTo(pop, QPoint(0, 0)).y() - y)
                        < regler.height()]
        m["breiten"], m["innen"], m["namen"] = breiten, innen, namen
        m["daneben"] = sorted(set(daneben))
        # Tasten und Code: activated nur bei einer Wahl des Nutzers.
        aktiviert = []
        regler.setCurrentIndex(2)
        if hasattr(regler, "activated"):
            regler.activated.connect(aktiviert.append)
        regler.setFocus()
        QTest.keyClick(regler, Qt.Key.Key_Right)
        QTest.keyClick(regler, Qt.Key.Key_Left)
        QTest.keyClick(regler, Qt.Key.Key_End)
        m["tasten"] = (list(aktiviert), regler.currentIndex())
        regler.setCurrentIndex(1)
        m["code_still"] = len(aktiviert)
        regler.setCurrentIndex(2)
        D._popover_fuellen(z)
        # Die Modellliste UEBER dem Popover.
        w["stufe_kachel"].click()
        QApplication.processEvents()
        liste = w["modell_liste_auf"]
        pg, lg = pop.mapToGlobal(QPoint(0, 0)), liste.mapToGlobal(QPoint(0,
                                                                         0))
        m["liste"] = (liste.isVisible(),
                      lg.y() + liste.height() <= pg.y() - 4,
                      abs(lg.x() - pg.x()) <= 2, liste.width() == pop.width(),
                      [getattr(e, "wert", None) for e in liste.eintraege
                       if getattr(e, "wert", None)])
        for e in liste.eintraege:
            if getattr(e, "wert", None) == "opus":
                e.click()
        QApplication.processEvents()
        m["wahl"] = (not liste.isVisible(), pop.isVisible(),
                     w["modell_zeile"].text(),
                     w["chat_modell_knopf"].volltext(),
                     ((_einst_lesen() or {}).get("modell") or {})
                     .get("claude"))
        # ↺: zurueck auf die Vorgabe.
        w["stufe_zurueck"].click()
        m["zurueck"] = (regler.currentData(), D._chat_modul().EFFORT_VORGABE,
                        w["stufe_zurueck"].isEnabled())
        pop.hide()
        # Ohne Denkstufe (Codex): kein Regler, das Modell gross.
        _anbieter_waehlen(z, "codex")
        w["chat_modell_knopf"].click()
        QApplication.processEvents()
        name = (w["chat_modell"].currentText() or "").strip()
        m["codex"] = (w["stufe_regler"].isVisible(),
                      w["stufe_zurueck"].isVisible(),
                      w["modell_zeile"].text(), w["stufe_gross"].text()
                      == (name if name and name != D.MODELLE_EINTRAG
                          else "Automatisch"))
        m["codex_texte"] = (w["stufe_gross"].text(),
                            w["chat_modell_knopf"].volltext())
        pop.hide()
        _anbieter_waehlen(z, "claude")
        # Mitten im Chat: gesperrt, mit der Notiz.
        z["chat"].update(an=True, laeuft_zug=False, anbieter="claude",
                         freigaben=[], ereignisse=[])
        w["chat_modell_knopf"].click()
        QApplication.processEvents()
        m["im_chat"] = (w["stufe_kachel"].isEnabled(),
                        w["stufe_regler"].isEnabled(),
                        w["stufe_notiz"].isVisible(),
                        w["stufe_notiz"].text())
        w["stufe_kachel"].click()
        m["im_chat_liste"] = liste.isVisible()
        pop.hide()
        z["chat"]["an"] = False
    finally:
        k.ende()
    return m


def zelle_popover():
    """L102 (K12, Bild 2, Spezifikation 4): der Popover fuer Modell und
    Denkstufe — oben die Kachel mit der Stufe gross und dem Modell klein
    (">"), darunter der Punktregler ueber die volle Breite, KEIN Text
    daneben, seine Breite fuer jede Stufe gleich (auch "Ultracode"); die
    Modellliste geht UEBER dem Popover auf, die Wahl schliesst nur sie;
    ↺ auf die Vorgabe; ohne Denkstufe (Codex) kein Regler; mitten im Chat
    gesperrt mit "Gilt ab dem nächsten Chat"; Tasten links/rechts/Ende,
    `activated` nur bei einer Wahl des Nutzers."""
    try:
        m = _popover_lauf()
        pruefe("L102 der Popover: ein Popup, nichts Modales, %d px breit"
               % 300, m["auf"] == (True, True, True, True), m["auf"])
        pruefe("L102 Kachel, Stufe gross, Modellzeile, Regler und ↺ im "
               "Popover", all(m["teile"].values()), m["teile"])
        pruefe("L102 die Stufe gross (mindestens 1,35 x die Grundschrift)",
               m["gross"][0] >= 1.35 * m["gross"][1], m["gross"])
        pruefe("L102 Reglerbreite fuer alle sechs Stufen gleich und = die "
               "Innenbreite (+-1)", len(set(m["breiten"])) == 1
               and abs(m["breiten"][0] - m["innen"]) <= 1,
               (m["breiten"], m["innen"]))
        pruefe("L102 die Stufen heissen kurz (Niedrig … Ultracode), kein "
               "Text neben dem Regler",
               m["namen"] == ["Niedrig", "Mittel", "Hoch", "Sehr hoch",
                              "Maximal", "Ultracode"]
               and m["daneben"] == [], (m["namen"], m["daneben"]))
        pruefe("L102 Tasten rechts/links/Ende waehlen (activated je Wahl), "
               "Setzen im Code meldet nichts",
               m["tasten"] == ([3, 2, 5], 5) and m["code_still"] == 3,
               (m["tasten"], m["code_still"]))
        pruefe("L102 die Modellliste UEBER dem Popover (Unterkante <= "
               "Oberkante - 4), linksbuendig, gleich breit, die Modelle von "
               "Claude Code", m["liste"][:4] == (True, True, True, True)
               and m["liste"][4] == ["sonnet", "opus", "fable", "haiku"],
               m["liste"])
        pruefe("L102 die Wahl schliesst nur die Liste; Popover bleibt, "
               "Modellzeile, Knopf und chat.json zeigen 'Opus 5.5'",
               m["wahl"][:2] == (True, True)
               and m["wahl"][2] == "Opus 5.5"
               and m["wahl"][3].startswith("Opus 5.5 · ")
               and m["wahl"][4] == "opus", m["wahl"])
        pruefe("L102 ↺ setzt die Vorgabe und ist danach aus",
               m["zurueck"][0] == m["zurueck"][1]
               and m["zurueck"][2] is False, m["zurueck"])
        pruefe("L102 Codex: kein Regler, kein ↺, das Modell gross, "
               "'Modell wechseln' klein",
               m["codex"] == (False, False, "Modell wechseln", True),
               (m["codex"], m["codex_texte"]))
        pruefe("L102 ohne gewaehltes Modell nie zweimal das Verb: gross und "
               "auf dem Knopf ein Name (nie 'Modell wählen')",
               "Modell wählen" not in m["codex_texte"][0]
               and "Modell wählen" not in m["codex_texte"][1],
               m["codex_texte"])
        k = _popover_lauf(lambda: _mutant(_anweisungen(
            "_modell_oder_vorgabe", lambda s: isinstance(s, ast.Return)
            and "MODELL_AUTOMATISCH" in ast.unparse(s),
            "return 'Modell wählen'")))
        pruefe("L102 KONTROLLE: mit 'Modell wählen' als Vorgabe (bis K12) "
               "steht das Verb gross", k["treffer"] == [1]
               and k["codex_texte"][0] == "Modell wählen", k["codex_texte"])
        pruefe("L102 mitten im Chat: Kachel und Regler gesperrt, die Notiz "
               "'Gilt ab dem nächsten Chat' — und keine Liste",
               m["im_chat"] == (False, False, True,
                                "Gilt ab dem nächsten Chat")
               and m["im_chat_liste"] is False,
               (m["im_chat"], m["im_chat_liste"]))
        k = _popover_lauf(lambda: _alter_regler(_mutant()))
        pruefe("L102 KONTROLLE: der alte Regler mit Text daneben -> Text "
               "neben der Spur, die Spur schwankt mit dem Namen",
               k["daneben"] != [] and len(set(k["breiten"])) > 1,
               (k["daneben"], k["breiten"]))
        k = _popover_lauf(lambda: _mutant(_anweisungen(
            "_modell_liste_zeigen", lambda s: isinstance(s, ast.Assign)
            and "liste.height() - 6" in ast.unparse(s),
            "x, y = g.x(), g.y() + pop.height() + 6")))
        pruefe("L102 KONTROLLE: die Liste UNTER dem Popover -> rot",
               k["treffer"] == [1] and k["liste"][1] is False, k["liste"])
    finally:
        _frischer_start()


# --- L103: die Arbeitsanzeige mit dem ECHTEN Kern (2.19) --------------------

L103_CODE = "import omcad_l103_probe as p\nresult = p.lesen()\n"


def _kern_ohne_haken(port):
    """Der echte Kern ohne den Haken (so verhaelt sich 2.18 gegenueber dem
    Dashboard: er nennt keinen Haken und ruft keinen)."""
    lade = _echter_kern_lader(port)

    def ohne():
        k = lade()
        del k.LAUF_ANZEIGE_HAKEN
        k._lauf_anzeige_rufen = lambda *a, **kw: False
        return k
    return ohne


def _anzeige_lauf(laden=None, kern_lader=None):
    """Ein echter Lauf (schreibend, dann lesend) ueber TCP, der Hauptthread
    dreht Qt; die Probe liest die Anzeige WAEHREND der Auftraege. Danach der
    Chat des Docks (Zug, Freigabe), Cadwork rechnet, das Ende. -> dict."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from open_mcp_cad import bridge_client
    _frischer_start()
    _einst_setzen(None)
    cw = _CadworkBild().einsetzen()
    haupt = _cadwork_ersatz(ort=(10, 30), groesse=(780, 700))
    p_y, = _freie_ports(1)
    client = _Client([("Y", p_y)])
    lade = (kern_lader or _echter_kern_lader)(p_y)
    zz = {}
    probe = types.ModuleType("omcad_l103_probe")

    def lesen():
        z_ = zz["z"]
        a = z_.get("anzeige")
        kp = getattr(z_["kern"], "_LAUF_POPUP", {}).get("w")
        w_ = z_["w"]
        return {"titel": (w_["anzeige_titel"].text()
                          if a is not None and a.isVisible() else None),
                "kern_popup": bool(kp is not None and kp.isVisible()),
                "pille": w_["pille"].text(),
                "laeuft": (not w_["briefkasten_laeuft"].isHidden(),
                           w_["briefkasten_laeuft_text"].text())}
    probe.lesen = lesen
    sys.modules["omcad_l103_probe"] = probe
    m = {"kern_popup": []}
    kern = None
    try:
        D = (laden or dashboard_laden)()
        D._monitor_starten = lambda z: None
        D._verbindungen_zeichnen = lambda z: None
        D._ablage_pflegen = lambda z: None
        D._verbindungen_client = lambda: client
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        D.oeffnen(lade, lambda k: k.Konfiguration(), verbinden=True)
        z = D._zustand()
        zz["z"] = z
        kern, d = z["kern"], z["dienst"]
        cw.dienst = d
        d.ms_je_teil = 1000.0          # 2 Bauteile -> 2 s: der Lauf zeigt sich
        m["haken"] = callable(getattr(d.cfg, "lauf_anzeige", None))
        # Angedockt: die Anzeige steht dann mittig ueber der 3D-Flaeche.
        D._fenster_aktion(z, "andocken")
        _pumpen(0.3)
        erg = {}

        def senden(params):
            a = bridge_client.call("execute_cwapi3d",
                                   dict(params, client_id="anon"),
                                   port=p_y, antwort_timeout=30)
            r = (a or {}).get("result")
            if isinstance(r, dict) and "titel" not in r:
                r = r.get("result")
            return r

        def lauf():
            try:
                erg["schreiben"] = senden({"code": L103_CODE,
                                           "description": "Wand Nord",
                                           "bauteile": 2, "lauf_gesamt": 6})
                erg["lesen"] = senden({"code": L103_CODE,
                                       "description": "Wände zählen",
                                       "access_mode": "read"})
            except Exception as exc:                  # noqa: BLE001
                erg["fehler"] = repr(exc)

        def drehen(bis, frist=10.0):
            ende = time.monotonic() + frist
            while time.monotonic() < ende and not bis():
                QApplication.processEvents()
                kp = kern._LAUF_POPUP.get("w")
                m["kern_popup"].append(bool(kp is not None
                                            and kp.isVisible()))
                time.sleep(0.01)
        t = threading.Thread(target=lauf, daemon=True)
        t.start()
        drehen(lambda: not t.is_alive(), 40)
        m["fehler"] = erg.get("fehler")
        m["schreiben"] = erg.get("schreiben")
        m["lesen"] = erg.get("lesen")
        anz = z.get("anzeige")
        m["sichtbar_nach"] = bool(anz is not None and anz.isVisible())
        # Keinen Fokus nehmen: offscreen aktiviert Qt JEDES gezeigte Fenster
        # (gemessen, auch mit dem Attribut) — dort laesst sich nur das
        # Attribut pruefen. Auf der echten Windows-Plattform von Qt 6.11
        # bleibt Cadworks Fenster damit aktiv, ohne es nicht (gemessen,
        # Skript messung_fokus.py, Uebergabe K12).
        from PyQt6.QtCore import Qt as _Qt
        m["aktiv"] = bool(
            anz is not None
            and anz.testAttribute(_Qt.WidgetAttribute.WA_ShowWithoutActivating)
            and not anz.windowFlags() & _Qt.WindowType.WindowStaysOnTopHint)
        if anz is not None and anz.isVisible():
            g = _global(anz)
            c = _global(haupt.centralWidget())
            m["ort"] = (abs((g[0] + g[2]) // 2 - (c[0] + c[2]) // 2) <= 2,
                        abs(g[1] - (c[1] + 12)) <= 2)
            m["logo"] = not z["w"]["anzeige_logo"].pixmap().isNull()
        # Der Chat des Docks: ein Zug ohne Auftrag.
        cad = "mcp__open-mcp-cad__execute_cadwork_command"
        z["chat"].update(an=True, laeuft_zug=True, kurzname="Claude",
                         anbieter="claude", freigaben=[], ereignisse=[
                             {"art": "werkzeug", "werkzeug": cad,
                              "eingabe": {"description": "Wand Nord"},
                              "id": "w1", "zeit": time.time() - 3}])
        D._auffrischen(z)
        m["denkt"] = (z["w"]["anzeige_titel"].text(), anz.isVisible(),
                      z["w"]["anzeige_zeile"].text())
        # Eine Freigabe wartet.
        z["chat"]["freigaben"] = [{"id": "f1", "offen": True,
                                   "werkzeug": cad,
                                   "eingabe": {"description": "Wand Süd"}}]
        D._auffrischen(z)
        knopf = z["w"]["anzeige_knopf"]
        m["freigabe"] = (z["w"]["anzeige_titel"].text(), knopf.text(),
                         knopf.isVisible())
        knopf.click()
        _pumpen(0.1)
        m["zum_chat"] = (not z["w"]["koerper"].isHidden(),
                         D._seite_jetzt(z) == "chat")
        z["chat"]["freigaben"] = []
        # Cadwork rechnet (Status des Kerns).
        D._anzeige_zeichnen(z, st=dict(d.status(),
                                       cadwork_beschaeftigt="Viewer-Modus"))
        m["cadwork"] = z["w"]["anzeige_titel"].text()
        # Das Ende: der Zug ist vorbei, der Lauf des Kerns endet in der
        # Ruhe -> "Fertig", dann weg.
        z["chat"]["laeuft_zug"] = False
        fertig = []

        def ende_da():
            D._auffrischen(z)
            t_ = z["w"]["anzeige_titel"].text()
            if anz.isVisible() and t_ not in fertig:
                fertig.append(t_)
            return not anz.isVisible() and not d.lauf_balken
        drehen(ende_da, 8)
        m["ende"] = (fertig, anz.isVisible())
        m["kern_popup_je"] = any(m["kern_popup"])
        # Ein Auftrag OHNE Lauf (Kern 2.19.1, `auftrag`): die Pille sagt
        # "Liest" waehrend er laeuft, die Anzeige erscheint nicht.
        D._auffrischen(z)
        m["pille_davor"] = z["w"]["pille"].text()
        erg2 = {}

        def lauf2():
            try:
                erg2["r"] = senden({"code": L103_CODE,
                                    "description": "Nach dem Lauf lesen",
                                    "access_mode": "read"})
            except Exception as exc:                  # noqa: BLE001
                erg2["fehler"] = repr(exc)
        t2 = threading.Thread(target=lauf2, daemon=True)
        t2.start()
        drehen(lambda: not t2.is_alive(), 20)
        m["ohne_lauf"] = erg2.get("r") or erg2.get("fehler")
        z["chat"]["an"] = False
    finally:
        if kern is not None:
            pruefe("L103 Dienst laesst sich sauber beenden",
                   _alle_beenden(kern))
        cw.entfernen()
        sys.modules.pop("omcad_l103_probe", None)
        haupt.hide()
        _frischer_start()
    return m


L103_TRENNEN = "import omcad_l103_probe as p\nresult = p.trennen()\n"


def _trennen_im_lauf(laden=None):
    """Ein schreibender Auftrag eines Laufs, in dem das Dock getrennt wird
    (die Probe ruft `_trennen` IM Auftrag — so kaeme ein Klick an, wenn
    Cadwork mitten im Auftrag Ereignisse verteilt). Gezaehlt: wie oft der
    Kern sein eigenes Fenster setzen wollte. -> dict."""
    from PyQt6.QtWidgets import QApplication
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from open_mcp_cad import bridge_client
    _frischer_start()
    _einst_setzen(None)
    cw = _CadworkBild().einsetzen()
    haupt = _cadwork_ersatz(ort=(10, 30), groesse=(780, 700))
    p_y, = _freie_ports(1)
    client = _Client([("Y", p_y)])
    lade = _echter_kern_lader(p_y)
    zz = {}
    probe = types.ModuleType("omcad_l103_probe")

    def trennen():
        z_ = zz["z"]
        zz["D"]._trennen(z_)
        return {"getrennt": bool(z_["dienst"].beenden_nach_auftrag)}
    probe.trennen = trennen
    sys.modules["omcad_l103_probe"] = probe
    m = {"kern_popup": [], "popup_rufe": 0}
    kern = None
    try:
        D = (laden or dashboard_laden)()
        D._monitor_starten = lambda z: None
        D._verbindungen_zeichnen = lambda z: None
        D._ablage_pflegen = lambda z: None
        D._verbindungen_client = lambda: client
        m["treffer"] = getattr(D, "_mutant_treffer", None)
        D.oeffnen(lade, lambda k: k.Konfiguration(), verbinden=True)
        z = D._zustand()
        zz["z"], zz["D"] = z, D
        kern, d = z["kern"], z["dienst"]
        cw.dienst = d
        d.ms_je_teil = 1000.0          # 2 Bauteile -> 2 s: ein Lauf
        echt = kern._popup_setzen

        def gezaehlt(*a, **kw):
            m["popup_rufe"] += 1
            return echt(*a, **kw)
        kern._popup_setzen = gezaehlt
        erg = {}

        def lauf():
            try:
                a = bridge_client.call("execute_cwapi3d", {
                    "code": L103_TRENNEN, "description": "Wand Nord",
                    "bauteile": 2, "client_id": "anon"}, port=p_y,
                    antwort_timeout=30)
                r = (a or {}).get("result")
                if isinstance(r, dict) and "getrennt" not in r:
                    r = r.get("result")
                erg["r"] = r
            except Exception as exc:                  # noqa: BLE001
                erg["fehler"] = repr(exc)
        t = threading.Thread(target=lauf, daemon=True)
        t.start()
        ende = time.monotonic() + 30
        while time.monotonic() < ende and (t.is_alive()
                                           or not d.beenden):
            QApplication.processEvents()
            kp = kern._LAUF_POPUP.get("w")
            m["kern_popup"].append(bool(kp is not None and kp.isVisible()))
            time.sleep(0.01)
        _pumpen(0.3)
        m["fehler"] = erg.get("fehler")
        m["getrennt"] = bool((erg.get("r") or {}).get("getrennt"))
        anz = z.get("anzeige")
        m["anzeige_nach"] = bool(anz is not None and anz.isVisible())
        m["kern_popup_je"] = any(m["kern_popup"])
        del m["kern_popup"]
    finally:
        if kern is not None:
            pruefe("L103 Dienst (Trennen im Lauf) laesst sich sauber beenden",
                   _alle_beenden(kern))
        cw.entfernen()
        sys.modules.pop("omcad_l103_probe", None)
        haupt.hide()
        _frischer_start()
    return m


def zelle_arbeitsanzeige():
    """L103 (K12, Spezifikation 5; Rueckmeldung 2026-10-07: "da steht immer
    zeichnet"): mit dem ECHTEN Kern 2.19 (Qt-Antrieb, cwapi3d-Attrappe,
    Temp-Registry, umgelenktes Log) liest ein Auftrag die Anzeige WAEHREND
    er laeuft: "KI zeichnet" beim schreibenden, "KI schaut ins Modell" beim
    lesenden; danach "KI denkt nach" (Chat-Zug ohne Auftrag), "Wartet auf
    deine Freigabe" mit "Zum Chat", "Cadwork rechnet", am Ende "Fertig" und
    weg. Das Fenster des Kerns nie zu sehen, der Fokus bleibt, Logo da,
    oben mittig ueber der 3D-Flaeche. Mit einem Kern ohne Haken (wie 2.18)
    NUR dessen Fenster."""
    try:
        m = _anzeige_lauf()
        pruefe("L103 der Haken ist gesetzt, der Lauf lief ohne Fehler",
               m["haken"] and m["fehler"] is None
               and isinstance(m["schreiben"], dict), m)
        pruefe("L103 WAEHREND des schreibenden Auftrags: 'KI zeichnet'",
               (m["schreiben"] or {}).get("titel") == "KI zeichnet",
               m["schreiben"])
        pruefe("L103 WAEHREND des lesenden Auftrags (im Lauf): 'KI schaut "
               "ins Modell'",
               (m["lesen"] or {}).get("titel") == "KI schaut ins Modell",
               m["lesen"])
        pruefe("L103 das Fenster des Kerns ('Open MCP CAD zeichnet …') nie "
               "zu sehen", not m["kern_popup_je"]
               and not (m["schreiben"] or {}).get("kern_popup")
               and not (m["lesen"] or {}).get("kern_popup"), m)
        pruefe("L103 oben mittig ueber der 3D-Flaeche, mit Logo, nimmt "
               "keinen Fokus (WA_ShowWithoutActivating, nicht immer obenauf)",
               m.get("ort") == (True, True)
               and m.get("logo") and m["aktiv"],
               (m.get("ort"), m.get("logo"), m["aktiv"]))
        pruefe("L103 Chat-Zug ohne Auftrag: 'KI denkt nach', die Zeile nennt "
               "den letzten Schritt", m["denkt"][0] == "KI denkt nach"
               and m["denkt"][1] and m["denkt"][2].startswith("Zuletzt: "),
               m["denkt"])
        pruefe("L103 eine Freigabe wartet: 'Wartet auf deine Freigabe' mit "
               "'Zum Chat' — der oeffnet den Chat",
               m["freigabe"] == ("Wartet auf deine Freigabe", "Zum Chat",
                                 True) and m["zum_chat"] == (True, True),
               (m["freigabe"], m["zum_chat"]))
        pruefe("L103 Cadwork rechnet: 'Cadwork rechnet'",
               m["cadwork"] == "Cadwork rechnet", m["cadwork"])
        pruefe("L103 am Ende 'Fertig', danach ist die Anzeige weg",
               "Fertig" in m["ende"][0] and m["ende"][1] is False, m["ende"])
        pruefe("L103 WAEHREND der Auftraege sagt die Pille im Kopf "
               "'Zeichnet' bzw. 'Liest' (nicht 'Bereit'; Gegenpruefung K12)",
               (m["schreiben"] or {}).get("pille") == "● Zeichnet"
               and (m["lesen"] or {}).get("pille") == "● Liest",
               ((m["schreiben"] or {}).get("pille"),
                (m["lesen"] or {}).get("pille")))
        pruefe("L103 WAEHREND des Auftrags steht im Briefkasten 'Läuft jetzt' "
               "mit seiner Beschreibung",
               list((m["schreiben"] or {}).get("laeuft") or ())
               == [True, "Wand Nord"]
               and list((m["lesen"] or {}).get("laeuft") or ())
               == [True, "Wände zählen"],
               ((m["schreiben"] or {}).get("laeuft"),
                (m["lesen"] or {}).get("laeuft")))
        o = m["ohne_lauf"] if isinstance(m["ohne_lauf"], dict) else {}
        pruefe("L103 ein Auftrag OHNE Lauf (Kern 2.19.1): die Pille sagt "
               "'Liest', 'Läuft jetzt' nennt ihn, die Anzeige bleibt weg",
               m["pille_davor"] == "● Bereit" and o.get("pille") == "● Liest"
               and list(o.get("laeuft") or ()) == [True,
                                                   "Nach dem Lauf lesen"]
               and o.get("titel") is None, (m["pille_davor"],
                                            m["ohne_lauf"]))
        a = _anzeige_lauf(kern_lader=_kern_ohne_haken)
        pruefe("L103 ein Kern ohne Haken (wie 2.18): kein Haken gesetzt, "
               "die Anzeige des Docks erscheint nicht, das Fenster des Kerns "
               "schon", not a["haken"] and a["fehler"] is None
               and (a["schreiben"] or {}).get("titel") is None
               and a["kern_popup_je"], a)
        k = _anzeige_lauf(lambda: _mutant(_anweisungen(
            "_anzeige_haken", lambda s: isinstance(s, ast.Expr)
            and "_auftrag_sofort" in ast.unparse(s))))
        pruefe("L103 KONTROLLE: setzt der Haken die Pille nicht (bis K12), "
               "sagt sie waehrend des Auftrags 'Bereit'",
               k["treffer"] == [1]
               and (k["schreiben"] or {}).get("pille") == "● Bereit"
               and list((k["schreiben"] or {}).get("laeuft")
                        or (None,))[0] is False, (k["schreiben"] or {}))
        k = _anzeige_lauf(lambda: _mutant(_anweisungen(
            "_anzeige_haken", _beginnt("_anzeige_zeichnen(z, sofort=True)"))))
        pruefe("L103 KONTROLLE: zeichnet der Haken nicht sofort, steht "
               "waehrend des Auftrags nicht 'KI zeichnet'",
               k["treffer"] == [1]
               and (k["schreiben"] or {}).get("titel") != "KI zeichnet",
               k["schreiben"])
        k = _anzeige_lauf(lambda: _mutant(_anweisungen(
            "_anzeige_haken", _beginnt("_anzeige_zeichnen(z, sofort=True)"),
            "_anzeige_zeichnen(z, sofort=True)\n"
            "raise RuntimeError('Probe: beide Fenster')")))
        pruefe("L103 KONTROLLE: wirft der Haken, zeigt der Kern sein Fenster "
               "dazu — zwei Anzeigen (die Zelle oben wird rot)",
               k["treffer"] == [1] and k["kern_popup_je"], k["kern_popup"][:5])
        k = _anzeige_lauf(lambda: _mutant(_anweisungen(
            "_anzeige_setzen", lambda s: isinstance(s, ast.Expr)
            and ast.unparse(s).startswith("titel.setText(zustand["),
            "titel.setText('KI zeichnet')")))
        pruefe("L103 KONTROLLE: mit festem Titel steht auch beim Lesen "
               "'KI zeichnet'", k["treffer"] == [1]
               and (k["lesen"] or {}).get("titel") == "KI zeichnet",
               k["lesen"])
        k = _anzeige_lauf(lambda: _mutant(_anweisungen(
            "_anzeige_bauen", _beginnt(
                "self.setAttribute(Qt.WidgetAttribute."
                "WA_ShowWithoutActivating)"))))
        pruefe("L103 KONTROLLE: ohne WA_ShowWithoutActivating (auf Windows "
               "nimmt sie dann den Fokus, gemessen) wird die Zeile rot",
               k["treffer"] == [1] and k["aktiv"] is False, k.get("aktiv"))
        # Trennen MITTEN im Lauf (Cadwork verteilt Ereignisse im Auftrag):
        # der stille Haken haelt das Fenster des Kerns fern.
        t = _trennen_im_lauf()
        pruefe("L103 Trennen mitten im Lauf: der Auftrag laeuft fertig, das "
               "Fenster des Kerns kommt NIE (_popup_setzen nie gerufen), die "
               "Anzeige des Docks ist weg (Gegenpruefung K12)",
               t["fehler"] is None and t["getrennt"]
               and t["popup_rufe"] == 0 and not t["kern_popup_je"]
               and t["anzeige_nach"] is False, t)
        k = _trennen_im_lauf(lambda: _mutant(_anweisungen(
            "_trennen", _beginnt("cfg.lauf_anzeige = _haken_still"),
            "cfg.lauf_anzeige = None")))
        pruefe("L103 KONTROLLE: nimmt Trennen den Haken nur weg (None statt "
               "still), zeigt der Kern sein Fenster fuer den letzten Auftrag",
               k["treffer"] == [1] and k["popup_rufe"] > 0, k)
    finally:
        _frischer_start()


# --- L104: Aussehen --------------------------------------------------------

def _aussehen_lauf(laden=None):
    """-> dict: Rot im Kopf, Knopfhoehen, blauer Rand schwebend/angedockt,
    Emoji in sichtbaren Texten."""
    from PyQt6.QtWidgets import QPushButton
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}

    def rot_im(bild):
        n = 0
        for x in range(0, bild.width(), 2):
            for y in range(0, bild.height(), 2):
                c = bild.pixelColor(x, y)
                if c.alpha() > 200 and c.red() > 220 and c.green() < 90 \
                        and c.blue() < 90:
                    n += 1
        return n

    def blau(c):
        return c.blue() > 180 and c.red() < 60 and c.alpha() > 200
    try:
        k.aktion("chat")
        kopf, koerper = w["kopf"], w["koerper"]
        w["kopf_verkleinern"].show()
        m["rot_kopf"] = rot_im(kopf.grab().toImage())
        m["hoehen"] = sorted({b.height() for b in kopf.findChildren(QPushButton)
                              if b.isVisible()
                              and b.objectName() != "kopf_chip"})
        bk, bb = kopf.grab().toImage(), koerper.grab().toImage()
        m["schwebend"] = (blau(bk.pixelColor(bk.width() // 2, 0)),
                          blau(bb.pixelColor(0, bb.height() // 2)))
        k.aktion("andocken")
        bk, bb = kopf.grab().toImage(), koerper.grab().toImage()
        m["angedockt"] = (blau(bk.pixelColor(bk.width() // 2, 0)),
                          blau(bb.pixelColor(0, bb.height() // 2)))
        texte = [t for _wd, _a, t in _texte_des_docks(z)]
        m["emoji"] = [t[:30] for t in texte
                      if any(ord(c) >= 0x1F000 or c in "✋⚡⛔⏳" for c in t)]
    finally:
        k.ende()
    return m


def zelle_aussehen():
    """L104 (K12, Spezifikation 6): im Kopf kein Rot (das rote X aus Bild 5
    kam von der nativen Leiste des Chat-Docks), alle Kopf-Knoepfe gleich
    hoch; schwebend 2 px blauer Rand um Kopf und Koerper, angedockt keiner;
    keine Emoji in sichtbaren Texten."""
    try:
        m = _aussehen_lauf()
        pruefe("L104 kein Rot im Kopf, alle Knoepfe 28 px",
               m["rot_kopf"] == 0 and m["hoehen"] == [28],
               (m["rot_kopf"], m["hoehen"]))
        pruefe("L104 schwebend blauer Rand an Kopf und Koerper, angedockt "
               "keiner", m["schwebend"] == (True, True)
               and m["angedockt"] == (False, False),
               (m["schwebend"], m["angedockt"]))
        pruefe("L104 keine Emoji in den Texten des Fensters", m["emoji"] == [],
               m["emoji"])

        def rot():
            M = _mutant()
            M.FENSTER_QSS = M.FENSTER_QSS + (
                'QFrame#OpenMcpCadA[teil="kopf"] QPushButton#kopf_knopf '
                '{ background: #ff3b30; }')
            return M
        k = _aussehen_lauf(rot)
        pruefe("L104 KONTROLLE: ein roter Knopf im Kopf (wie das X aus Bild "
               "5) faellt auf", k["rot_kopf"] > 0, k["rot_kopf"])
    finally:
        _frischer_start()


# --- L79: schwebend bleibt das Fenster auf dem Bildschirm --------------------

def _schirm_lauf(laden=None):
    """Ein Hauptfenster hoeher als der Bildschirm; das offene Fenster, und
    die Pille nach dem Ziehen neben alle Bildschirme. -> dict."""
    from PyQt6.QtCore import QEvent, QPoint, Qt
    k = _K12(laden=laden, ort=(30, 30), groesse=(700, 1200))
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        k.aktion("chat")
        m["offen"] = _ganz_auf_schirm(k.f)
        k.aktion("verkleinern")
        kopf = w["kopf"]
        start = _maus(kopf, QEvent.Type.MouseButtonPress, QPoint(30, 10))
        ziel = QPoint(-4000, start.y())
        _maus(kopf, QEvent.Type.MouseMove, kopf.mapFromGlobal(ziel),
              Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        _maus(kopf, QEvent.Type.MouseButtonRelease, kopf.mapFromGlobal(ziel))
        _pumpen(0.35)
        m["weg"] = not _ganz_auf_schirm(k.f)
        D.oeffnen(z["kern_laden"], z["cfg_bauen"])
        _pumpen(0.1)
        m["zurueck"] = _ganz_auf_schirm(k.f)
        k.aktion("chat")
        m["offen_danach"] = _ganz_auf_schirm(k.f)
    finally:
        k.ende()
    return m


def zelle_auf_dem_schirm():
    """L79 (Gegenpruefung K9, fuer K12): ein schwebendes Fenster steht ganz
    auf einem Bildschirm — offen nie hoeher als er, auch wenn das
    Hauptfenster hoeher ist; zieht der Nutzer die Pille neben alle
    Bildschirme (ein zweiter wurde abgesteckt), holt der Plugin-Klick sie
    zurueck."""
    try:
        m = _schirm_lauf()
        pruefe("L79 offen bei einem Hauptfenster hoeher als der Bildschirm: "
               "ganz auf dem Bildschirm", m["offen"], m)
        pruefe("L79 neben alle Bildschirme gezogen, holt der Klick die Pille "
               "zurueck; offen steht sie dann wieder ganz drauf",
               m["weg"] and m["zurueck"] and m["offen_danach"], m)
        k = _schirm_lauf(lambda: _mutant(_anweisungen(
            "_fenster_zurueckholen", lambda s: isinstance(s, ast.If),
            "pass")))
        pruefe("L79 KONTROLLE: ohne Zurueckholen bleibt die Pille neben den "
               "Bildschirmen", k["treffer"] == [1] and k["weg"]
               and not k["zurueck"], k)
    finally:
        _frischer_start()


# --- L92: die Rueckfrage an einem SICHTBAREN Fenster --------------------------

def _rueckfrage_lauf(laden=None):
    """L92: die Pille steht, der Chat arbeitet, "Trennen" im Kopf -> die
    Rueckfrage "Chat beenden?" (exec durch eine Attrappe ersetzt, die nur
    misst). -> dict."""
    from PyQt6.QtWidgets import QApplication, QMessageBox
    k = _K12(laden=laden)
    D, z = k.D, k.z
    gesehen = []
    echt_exec = QMessageBox.exec

    def exec_attrappe(box):
        box.show()
        QApplication.processEvents()
        p = box.parentWidget()
        g = box.frameGeometry()
        gesehen.append({"eltern": p.objectName() if p is not None else None,
                        "sichtbar": bool(p is not None and p.isVisible()),
                        "mitte": [g.center().x(), g.center().y()]})
        box.hide()
        return 0
    m = {"treffer": k.treffer}
    C = alt_lz = None
    try:
        C = D._chat_modul()
        alt_lz = C.laeuft_zug
        C.laeuft_zug = lambda c: True
        z["chat"].update(an=True, kurzname="Claude")
        m["vorher"] = (z["fenster"].isVisible(),
                       z["w"]["koerper"].isHidden(),
                       z["w"]["primaer"].text())
        QMessageBox.exec = exec_attrappe
        try:
            z["w"]["primaer"].click()
            QApplication.processEvents()
        finally:
            QMessageBox.exec = echt_exec
        m["gesehen"] = gesehen
        h = _global(k.haupt, rahmen=False)
        m["ueber_cadwork"] = [h[0] <= g["mitte"][0] < h[2]
                              and h[1] <= g["mitte"][1] < h[3]
                              for g in gesehen]
    finally:
        if C is not None:
            C.laeuft_zug = alt_lz
        z["chat"]["an"] = False
        k.ende()
    return m


def zelle_rueckfrage_sichtbar():
    """L92 (Gegenpruefung K11, fuer K12): steht nur die Pille und der Chat
    arbeitet, geht die Rueckfrage nach "Trennen" an der sichtbaren Pille
    auf, ueber Cadwork — nie an einem versteckten Teil (vorher: oben links
    in der Ecke des Bildschirms, waehrend Cadwork blockiert war)."""
    m = _rueckfrage_lauf()
    pruefe("L92 vorher steht nur die Pille, ihr Knopf heisst 'Trennen'",
           m["vorher"] == (True, True, "Trennen"), m["vorher"])
    g = m["gesehen"]
    pruefe("L92 die Rueckfrage geht am sichtbaren Fenster auf, ihre Mitte "
           "ueber Cadwork",
           len(g) == 1 and g[0]["eltern"] == "OpenMcpCadFenster"
           and g[0]["sichtbar"] and m["ueber_cadwork"] == [True], m)
    M = _mutant()
    M._dialog_eltern = lambda z: z["w"]["koerper"]
    k = _rueckfrage_lauf(lambda: M)
    pruefe("L92 KONTROLLE: an einem versteckten Teil (dem Koerper der Pille) "
           "faellt es auf", len(k["gesehen"]) == 1
           and not k["gesehen"][0]["sichtbar"], k["gesehen"])


# --- L93: alle neuen Slots laufen durch _sicher -----------------------------
#: Die Slots von K12: Name, die Arbeit im Dashboard, die die Kontrolle werfen
#: laesst, und wie der Slot ausgeloest wird (im offenen Fenster).
K12_SLOTS = (
    ("Chat-Knopf", "_fenster_aktion",
     lambda D, z: z["w"]["kopf_chat"].click()),
    ("Verbinden/Trennen", "_primaer_geklickt",
     lambda D, z: z["w"]["primaer"].click()),
    ("Andocken", "_fenster_aktion",
     lambda D, z: z["w"]["kopf_andocken"].click()),
    ("Verkleinern", "_fenster_aktion",
     lambda D, z: z["w"]["kopf_verkleinern"].click()),
    ("Segment", "_segment_waehlen",
     lambda D, z: z["w"]["segment_briefkasten"].click()),
    ("Rueckgaengig", "_auftrag", lambda D, z: z["w"]["btn_undo"].click()),
    ("Hinweise", "_hinweise_zeigen",
     lambda D, z: z["w"]["hinweise_knopf"].click()),
    ("Hinweise zu", "_hinweise_zeigen",
     lambda D, z: z["w"]["hinweise_zu"].click()),
    ("Mehr", "_mehr_aufklappen", lambda D, z: z["w"]["mehr_menue"].click()),
    ("Mehr: Einstellungen", "_einstellungen_zeigen",
     lambda D, z: z["w"]["mehr_einst"].click()),
    ("Zurueck", "_einstellungen_zeigen",
     lambda D, z: z["w"]["einst_zurueck"].click()),
    ("Seite gewechselt", "_seite_gewechselt",
     lambda D, z: z["w"]["seiten"].setCurrentIndex(
         (z["w"]["seiten"].currentIndex() + 1) % 3)),
    ("Letzte Aufträge", "_auftraege_klappen",
     lambda D, z: z["w"]["auftraege_kopf"].click()),
    ("Ablegen mit Enter", "_auftrag",
     lambda D, z: (z["w"]["post_eingabe"].setText("Probe"),
                   z["w"]["post_eingabe"].returnPressed.emit())),
    ("Ablegen mit dem Knopf", "_auftrag",
     lambda D, z: (z["w"]["post_eingabe"].setText("Probe"),
                   z["w"]["post_senden"].click())),
    ("Kachel", "_modell_liste_zeigen",
     lambda D, z: z["w"]["stufe_kachel"].click()),
    ("Auf Vorgabe zurueck", "_stufe_zurueck",
     lambda D, z: (z["w"]["stufe_zurueck"].setEnabled(True),
                   z["w"]["stufe_zurueck"].click())),
    ("Anzeige-Knopf", "_anzeige_knopf",
     lambda D, z: (z["w"]["anzeige_knopf"].show(),
                   z["w"]["anzeige_knopf"].click())),
    ("Anzeige weg", "_anzeige_weg",
     lambda D, z: z["w"]["anzeige_weg"].click()),
    ("Fenster zu", "_fenster_sichtbar",
     lambda D, z: (z["fenster"].show(), z["fenster"].hide())),
)


def _ohne_sicher(*funktionen):
    """Mutation: in `funktionen` wird jedes `_sicher(fn, …)` zu `fn()` —
    die Arbeit laeuft direkt im Slot."""
    def mutation(baum):
        n = 0
        for name in funktionen:
            f = _funktion(baum, name)
            for knoten in (list(ast.walk(f)) if f is not None else ()):
                for feld, wert in ast.iter_fields(knoten):
                    if isinstance(wert, list):
                        for i, x in enumerate(wert):
                            if (isinstance(x, ast.Call)
                                    and isinstance(x.func, ast.Name)
                                    and x.func.id == "_sicher" and x.args):
                                wert[i] = ast.Call(func=x.args[0], args=[],
                                                   keywords=[])
                                n += 1
                    elif (isinstance(wert, ast.Call)
                          and isinstance(wert.func, ast.Name)
                          and wert.func.id == "_sicher" and wert.args):
                        setattr(knoten, feld, ast.Call(func=wert.args[0],
                                                       args=[], keywords=[]))
                        n += 1
        return n
    return mutation


def _k11_slots_lauf(laden=None):
    """L93: jede Arbeit hinter den Slots von K12 wirft; nichts darf aus dem
    Slot laufen (in Cadwork qFatal, L43), der Fehler steht auf stderr.
    -> dict."""
    import io
    k = _K12(laden=laden)
    D, z = k.D, k.z
    m = {"treffer": k.treffer, "entkommen": {}}
    alt_hook, alt_err = sys.excepthook, sys.stderr
    try:
        k.aktion("chat")
        m["ablegen_an"] = z["w"]["post_senden"].isEnabled()
        sys.stderr = io.StringIO()
        for name, arbeit, ausloesen in K12_SLOTS:
            echt = getattr(D, arbeit)

            def wirft(*_a, _name=name, **_k):
                raise RuntimeError("Probe: %s" % _name)
            setattr(D, arbeit, wirft)
            fang = []
            sys.excepthook = (lambda t, v, tb, fang=fang:
                              fang.append(t.__name__))
            try:
                ausloesen(D, z)
                _APP.processEvents()
            except Exception as exc:                   # noqa: BLE001
                # Ein direkter Aufruf (Kachel.click) ohne Qt dazwischen:
                # dann laeuft die Ausnahme bis hierher — auch "entkommen".
                fang.append(type(exc).__name__)
            finally:
                setattr(D, arbeit, echt)
            m["entkommen"][name] = fang
        fehler = sys.stderr.getvalue()
        m["gemeldet"] = [n for n, _a, _x in K12_SLOTS
                         if "Probe: %s" % n in fehler]
    finally:
        sys.excepthook, sys.stderr = alt_hook, alt_err
        k.ende()
    return m


def zelle_k11_slots_sicher():
    """L93 (Pflicht der Spezifikation: "Alle neuen Slots über _sicher"; seit
    K12 die Knoepfe des Kopfs, der Segmentzeile, "⋯", die Einstellungsseite,
    der Briefkasten, der Popover, die Arbeitsanzeige und das Schliessen des
    Fensters): wirft die Arbeit dahinter, laeuft nichts aus dem Slot, und
    der Fehler steht auf stderr."""
    m = _k11_slots_lauf()
    namen = [n for n, _a, _x in K12_SLOTS]
    pruefe("L93 wirft die Arbeit hinter einem der %d Slots, laeuft nichts "
           "aus dem Slot, und jeder Fehler steht auf stderr" % len(namen),
           m["ablegen_an"] and all(m["entkommen"][n] == [] for n in namen)
           and m["gemeldet"] == namen, m)
    k = _k11_slots_lauf(lambda: _mutant(_ohne_sicher(
        "_kopf_bauen", "_koerper_bauen", "_briefkasten_bauen",
        "_einstellungen_bauen", "_popover_bauen", "_anzeige_bauen",
        "_fenster_bauen")))
    pruefe("L93 KONTROLLE: ohne _sicher an diesen Verbindungen laeuft jede "
           "Ausnahme aus dem Slot", k["treffer"][0] > 10
           and all(k["entkommen"][n] and set(k["entkommen"][n])
                   == {"RuntimeError"} for n in namen),
           {n: k["entkommen"][n] for n in namen})


# --- L85/L86: der Briefkasten ist ein Segment, kein zweiter Chat --------------

def _post_lauf(laden=None):
    """Der Briefkasten als Ablage (K12: das Segment Briefkasten): was darin
    steht, Enter und "Ablegen", die Notizen mit Zeit und Chip. -> dict."""
    from PyQt6.QtWidgets import (QLabel, QLineEdit, QPlainTextEdit,
                                 QPushButton, QTextEdit, QWidget)
    _einst_setzen(None)
    jetzt = time.time()
    post = [{"nr": 1, "text": "Erste Notiz", "zeit": jetzt - 125,
             "abgeholt": True},
            {"nr": 2, "text": "Zweite Notiz", "zeit": jetzt - 5,
             "abgeholt": False}]
    D, z, d = _neustart(laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    try:
        with d.sperre:
            d.postfach.extend(post)
        D._auffrischen(z)
        tab = w["briefkasten_seite"]

        def wie_chat(wurzel):
            """Was am Chat haengt: die Eingabe `_Eingabe` (#eingabe), der
            runde Knopf #senden, mehrzeilige Felder."""
            namen = {wd.objectName() for wd in wurzel.findChildren(QWidget)}
            return sorted(({"eingabe", "senden"} & namen)
                          | ({"mehrzeilig"} if wurzel.findChildren(
                              (QPlainTextEdit, QTextEdit)) else set()))
        m["wie_chat"] = wie_chat(tab)
        m["wie_chat_k"] = wie_chat(w["seiten"].widget(0))
        felder = tab.findChildren(QLineEdit)
        m["feld"] = ([f.placeholderText() for f in felder],
                     felder[0] is w["post_eingabe"] if felder else False)
        b = w["post_senden"]
        m["knopf"] = (QPushButton.text(b), b.accessibleName(),
                      b.property("symbol"), b.objectName() != "senden",
                      tab.isAncestorOf(b))
        # Die Zahl wartender Notizen am Segment.
        m["zahl"] = (w["briefkasten_zahl"].text(),
                     not w["briefkasten_zahl"].isHidden())
        anzahl = len(d.job_queue.items)
        w["post_eingabe"].setText("Bitte Wand Nord pruefen")
        w["post_eingabe"].returnPressed.emit()
        neu = d.job_queue.items[anzahl:]
        m["enter"] = ([(j.methode, j.params.get("text")) for j in neu],
                      w["post_eingabe"].text())
        anzahl = len(d.job_queue.items)
        w["post_eingabe"].setText("Und das Dach")
        b.click()
        neu = d.job_queue.items[anzahl:]
        m["ablegen"] = ([(j.methode, j.params.get("text")) for j in neu],
                        w["post_eingabe"].text())
        zeilen = []
        lay = w["post_verlauf"].widget().layout()
        for i in range(lay.count()):
            zeile = lay.itemAt(i).widget()
            if zeile is None or zeile.objectName() != "protokoll_zeile":
                continue
            labels = {lb.objectName(): lb for lb in zeile.findChildren(QLabel)}
            chip = labels.get("protokoll_chip")
            texte = [lb.text() for lb in zeile.findChildren(QLabel)
                     if lb.objectName() == ""]
            zeilen.append((labels["protokoll_zeit"].text()
                           if "protokoll_zeit" in labels else None,
                           chip.text() if chip else None,
                           chip.styleSheet() if chip else None, texte))
        m["zeilen"] = [z_[:2] + (z_[3],) for z_ in zeilen]
        m["chip_stil"] = [z_[2] for z_ in zeilen]
        m["chip_soll"] = [D._pille_stil(D.FARBEN["gruen"]),
                          D._pille_stil(D.FARBEN["orange"])]
    finally:
        _frischer_start()
    return m


def zelle_briefkasten_ablage():
    """L85 (K11, seit K12 das Segment "Briefkasten"): eine ABLAGE, kein
    zweiter Chat — keine Chat-Eingabe (#eingabe) und kein runder #senden,
    sondern eine Zeile "Notiz für die KI ablegen …" (Enter legt ab) und der
    Textknopf "Ablegen" mit Briefsymbol; die Notizen mit Zeit und Zustand
    als Chip "wartet"/"abgeholt"; die Zahl wartender am Segment."""
    try:
        m = _post_lauf()
        pruefe("L85 im Briefkasten nichts vom Chat: keine Chat-Eingabe, kein "
               "#senden, kein mehrzeiliges Feld", m["wie_chat"] == [],
               m["wie_chat"])
        pruefe("L85 KONTROLLE: dieselbe Messung findet im Chat Eingabe und "
               "#senden", {"eingabe", "senden"} <= set(m["wie_chat_k"]),
               m["wie_chat_k"])
        pruefe("L85 EINE Zeile 'Notiz für die KI ablegen …' und der "
               "Textknopf 'Ablegen' mit Briefsymbol",
               m["feld"] == (["Notiz für die KI ablegen …"], True)
               and m["knopf"] == ("Ablegen", "Ablegen", "ablegen", True,
                                  True), (m["feld"], m["knopf"]))
        pruefe("L85 am Segment die Zahl wartender Notizen (1)",
               m["zahl"] == ("1", True), m["zahl"])
        pruefe("L85 Enter legt die Notiz ab (ueber die Warteschlange) und "
               "leert die Zeile; 'Ablegen' ebenso",
               m["enter"] == ([("nachricht_senden",
                                "Bitte Wand Nord pruefen")], "")
               and m["ablegen"] == ([("nachricht_senden", "Und das Dach")],
                                    ""), (m["enter"], m["ablegen"]))
        z_ = m["zeilen"]
        pruefe("L85 die Notizen: aeltere oben, je Zeit, Chip "
               "('abgeholt' gruen, 'wartet' orange) und Text",
               len(z_) == 2 and z_[0][0] == "vor 2 min"
               and z_[0][1:] == ("abgeholt", ["Erste Notiz"])
               and z_[1][0].startswith("vor ") and z_[1][0].endswith(" s")
               and z_[1][1:] == ("wartet", ["Zweite Notiz"])
               and m["chip_stil"] == m["chip_soll"],
               (z_, m["chip_stil"]))
        # KONTROLLEN
        k = _post_lauf(lambda: _mutant(_anweisungen(
            "_briefkasten_bauen", lambda s: isinstance(s, ast.Expr)
            and ast.unparse(s).startswith("feld.returnPressed.connect("))))
        pruefe("L85 KONTROLLE: ohne Enter-Anschluss legt Enter nichts ab",
               k["treffer"] == [1] and k["enter"][0] == [], k["enter"])
        k = _post_lauf(lambda: _mutant(_anweisungen(
            "_post_zeichnen", _beginnt("chip = QLabel("),
            "chip = QLabel('wartet')")))
        pruefe("L85 KONTROLLE: zeigt der Chip immer 'wartet', faellt es auf",
               k["treffer"] == [1] and k["zeilen"][0][1] == "wartet",
               k["zeilen"])
        k = _post_lauf(lambda: _mutant(_anweisungen(
            "_briefkasten_bauen", _beginnt("feld.setPlaceholderText("),
            "feld.setPlaceholderText('Nachricht schreiben …')")))
        pruefe("L85 KONTROLLE: mit dem Platzhalter des Chats wird die Zeile "
               "rot", k["treffer"] == [1]
               and k["feld"][0] == ["Nachricht schreiben …"], k["feld"])
        k = _post_lauf(lambda: _mutant(_ohne_aufruf(
            "_auffrischen", "_briefkasten_zeigen")))
        pruefe("L85 KONTROLLE: ohne das Zeichnen im Takt fehlt die Zahl am "
               "Segment", k["treffer"] == [1] and k["zahl"][1] is False,
               k["zahl"])
    finally:
        _einst_setzen(None)
        _frischer_start()


def _protokoll_lauf(laden=None):
    """"Letzte Aufträge" im Briefkasten (K12): Kopf, Liste, wie sie
    gezeichnet wird. -> dict."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QLabel
    _einst_setzen(None)
    D, z, d = _neustart(laden() if laden else None)
    m = {"treffer": getattr(D, "_mutant_treffer", None)}
    w = z["w"]
    try:
        D._auffrischen(z)
        D._fenster_aktion(z, "chat")
        D._segment_waehlen(z, "briefkasten")
        _pumpen(0.3)
        tab = w["briefkasten_seite"]
        lst = w["liste_auftraege"]
        ahnen, p = [], lst.parentWidget()
        while p is not None and p is not tab:
            ahnen.append(p.objectName())
            p = p.parentWidget()
        m["liste"] = (lst.objectName(), lst.alternatingRowColors(),
                      "karte" in ahnen, tab.isAncestorOf(lst))
        m["titel"] = [w["auftraege_kopf"].text()] + [
            lb.text() for lb in tab.findChildren(QLabel)
            if lb.objectName() == "abschnitt"]
        m["verlauf"] = [lb.text() for lb in tab.findChildren(QLabel)
                        if lb.text() == "Verlauf"]
        bild = lst.viewport().grab().toImage()
        f = bild.pixelColor(bild.width() // 2, bild.height() - 4)
        m["grund"] = (f.name(QColor.NameFormat.HexRgb), D.FARBEN["grund"],
                      D.FARBEN["karte"])
        # Ein-/Ausklappen.
        w["auftraege_kopf"].click()
        m["klappen"] = (lst.isHidden(),)
        w["auftraege_kopf"].click()
        m["klappen"] += (not lst.isHidden(),)
    finally:
        _frischer_start()
    return m


def zelle_auftraege_protokoll():
    """L86 (K11, seit K12 im Briefkasten): "Letzte Aufträge" ist ein
    PROTOKOLL, kein zweiter Chat — der Kopf heisst "Letzte Aufträge" (nicht
    "Verlauf" wie der Chat), die Liste liegt flach auf dem Grund (objectName
    'protokoll', keine weisse Karte), Zeilen abwechselnd hinterlegt, ein- und
    ausklappbar. Die Zeilentexte prueft L71."""
    try:
        m = _protokoll_lauf()
        pruefe("L86 die Liste: objectName 'protokoll', Zeilen abwechselnd "
               "hinterlegt, in KEINER weissen Karte, im Briefkasten",
               m["liste"] == ("protokoll", True, False, True), m["liste"])
        pruefe("L86 der Kopf heisst 'Letzte Aufträge' (kein 'Verlauf')",
               m["titel"][:1] == ["Letzte Aufträge"] and m["verlauf"] == [],
               (m["titel"], m["verlauf"]))
        g = m["grund"]
        pruefe("L86 gezeichnet: der Grund der Liste ist %s (der des "
               "Fensters), nicht das Weiss einer Karte" % g[1],
               g[0] == g[1] and g[0] != g[2], g)
        pruefe("L86 'Letzte Aufträge' klappt zu und wieder auf",
               m["klappen"] == (True, True), m["klappen"])
        k = _protokoll_lauf(lambda: _mutant(_anweisungen(
            "_briefkasten_bauen", _beginnt("lay.addWidget(liste, 0)"),
            "karte, kl = _karte('Verlauf')\nkl.addWidget(liste)\n"
            "lay.addWidget(karte)")))
        pruefe("L86 KONTROLLE: in der weissen Karte 'Verlauf' (wie bis K10) "
               "werden die Zeilen rot", k["treffer"] == [1]
               and k["liste"][2] is True and k["verlauf"] == ["Verlauf"],
               (k["liste"], k["verlauf"]))
        k = _protokoll_lauf(lambda: _mutant(_anweisungen(
            "_briefkasten_bauen",
            _beginnt("liste.setObjectName('protokoll')"))))
        pruefe("L86 KONTROLLE: ohne den Namen ist die Liste wieder eine "
               "weisse Karte (gezeichnet)", k["treffer"] == [1]
               and k["grund"][0] == k["grund"][2], k["grund"])
    finally:
        _einst_setzen(None)
        _frischer_start()


# --- L105-L109: Gegenpruefung K12 (2026-10-07) ------------------------------

def _kopfknoepfe_lauf(laden=None):
    """L105: "Trennen" (zurueckhaltend) bzw. "Verbinden" (blau) im Kopf,
    der Chat-Knopf faellt auf, solange die KI arbeitet. -> dict."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        D._auffrischen(z)
        m["verbunden"] = (w["primaer"].text(), w["primaer"].objectName())
        z["chat"].update(an=True, laeuft_zug=True, kurzname="Claude",
                         anbieter="claude", freigaben=[], ereignisse=[])
        D._auffrischen(z)
        m["zug"] = w["kopf_chat"].objectName()
        z["chat"]["laeuft_zug"] = False
        D._auffrischen(z)
        m["ruhe"] = w["kopf_chat"].objectName()
        z["chat"]["an"] = False
        z["dienst"].beenden = True
        D._auffrischen(z)
        m["getrennt"] = (w["primaer"].text(), w["primaer"].objectName())
        m["name"] = D.CHAT_KNOPF_NAME
    finally:
        k.ende()
    return m


def zelle_kopfknoepfe():
    """L105 (Gegenpruefung K12; vorher L84 an der Leiste): verbunden steht
    im Kopf "Trennen" (objectName `trennen`, zurueckhaltend), getrennt
    "Verbinden" (`primaer`, blau); der Chat-Knopf faellt auf (`hinweis`),
    solange im Chat des Docks ein Zug laeuft, sonst nicht."""
    try:
        m = _kopfknoepfe_lauf()
        pruefe("L105 verbunden 'Trennen' (trennen), getrennt 'Verbinden' "
               "(primaer)", m["verbunden"] == ("Trennen", "trennen")
               and m["getrennt"] == ("Verbinden", "primaer"), m)
        pruefe("L105 der Chat-Knopf faellt auf, solange die KI arbeitet, "
               "danach nicht", m["zug"] == "hinweis"
               and m["ruhe"] == m["name"], m)
        k = _kopfknoepfe_lauf(lambda: _mutant(_anweisungen(
            "_auffrischen", _beginnt("name = 'trennen' if"),
            "name = 'primaer'")))
        pruefe("L105 KONTROLLE: 'Trennen' blau wie 'Verbinden' (Mutant) -> "
               "rot", k["treffer"] == [1]
               and k["verbunden"] == ("Trennen", "primaer"), k)
        k = _kopfknoepfe_lauf(lambda: _mutant(_anweisungen(
            "_chatknopf_zeigen", _beginnt("auffallen = bool("),
            "auffallen = bool(st['freigabe'] or st['gesperrt'])")))
        pruefe("L105 KONTROLLE: ohne die arbeitende KI im Grund (Mutant) "
               "faellt der Chat-Knopf nicht auf", k["treffer"] == [1]
               and k["zug"] != "hinweis", k)
    finally:
        _frischer_start()


def _geloescht_lauf(laden=None):
    """L106: die Arbeitsanzeige zeigt "Fertig", dann loescht Cadwork das
    Fenster (mit ihm den Takt). -> dict."""
    from PyQt6 import sip
    k = _K12(laden=laden)
    D, z = k.D, k.z
    m = {"treffer": k.treffer}
    try:
        k.kern.LAUF_ANZEIGE_HAKEN = True
        m["gesetzt"] = D._haken_setzen(z)
        haken = z["dienst"].cfg.lauf_anzeige
        haken("start", {"zugriff": "write", "beschreibung": "Wand",
                        "neu_lauf": True, "popup": True})
        haken("ende", {"lauf_gezeichnet": 3})
        D._auffrischen(z)
        anz = z["anzeige"]
        m["vorher"] = (anz.isVisible(), z["w"]["anzeige_titel"].text())
        sip.delete(z["fenster"])
        _pumpen(0.4)
        m["nachher"] = (sip.isdeleted(anz) or not anz.isVisible(),
                        getattr(z["dienst"].cfg, "lauf_anzeige", None)
                        is None)
        # Der naechste Klick baut neu und setzt den Haken wieder.
        D2, z2, _r = _klick(k.client, k.kern, verbinden=False, laden=laden)
        _pumpen(0.2)
        m["klick"] = (z2["fenster"].isVisible(),
                      callable(getattr(z2["dienst"].cfg, "lauf_anzeige",
                                       None)),
                      z2.get("anzeige") is not None)
    finally:
        k.ende()
    return m


def zelle_fenster_geloescht():
    """L106 (Gegenpruefung K12): loescht Cadwork das Fenster, stirbt mit ihm
    der Takt — die Arbeitsanzeige ("Fertig") darf nicht verwaist stehen
    bleiben, und der Haken im Kern muss weg (sonst unterdrueckte er das
    eigene Fenster des Kerns, und "KI zeichnet" bliebe haengen). Der
    naechste Klick baut neu und setzt den Haken wieder."""
    try:
        m = _geloescht_lauf()
        pruefe("L106 Vorbedingung: Haken gesetzt, die Anzeige sagt 'Fertig'",
               m["gesetzt"] and m["vorher"] == (True, "Fertig"), m)
        pruefe("L106 Fenster geloescht: die Anzeige ist weg, der Haken im "
               "Kern auch", m["nachher"] == (True, True), m["nachher"])
        pruefe("L106 der naechste Klick: neues Fenster, Haken und Anzeige "
               "wieder da", m["klick"] == (True, True, True), m["klick"])
        k = _geloescht_lauf(lambda: _mutant(_anweisungen(
            "_fenster_bauen", lambda s: isinstance(s, ast.Expr)
            and "destroyed.connect" in ast.unparse(s))))
        pruefe("L106 KONTROLLE: ohne das Signal destroyed (bis K12) bleibt "
               "die Anzeige verwaist stehen und der Haken gesetzt",
               k["treffer"] == [1] and k["nachher"] == (False, False),
               k["nachher"])
    finally:
        _frischer_start()


def _kern_modul_lesen():
    """Der Kern aus `_core` (nur fuer seine Qt-Sonden; kein Dienst)."""
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
    spec = importlib.util.spec_from_file_location("omcad_kern_sonden", pfad)
    km = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(km)
    return km


def _menue_lauf(laden=None):
    """L107: der Popover fuer Modell und Denkstufe ist offen — was sagen
    die Sonde des echten Kerns, Pille, Meldezeile und Anzeige; dagegen ein
    fremdes Popup. -> dict."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget
    km = _kern_modul_lesen()
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        k.aktion("chat")
        sonden = km._qt_sonden()
        w["chat_modell_knopf"].click()
        _pumpen(0.1)
        grund = km._cadwork_beschaeftigt(sonden)
        m["grund"] = grund
        st = dict(z["dienst"].status(), cadwork_beschaeftigt=grund)
        m["leer"] = D._pille_zustand(True, "ready", D._blockiert(
            z, dict(st, wartende_auftraege=0)))[0]
        m["wartet"] = D._pille_zustand(True, "ready", D._blockiert(
            z, dict(st, wartende_auftraege=2)))[0]
        m["anzeige"] = D._anzeige_zustand(blockiert=D._blockiert(
            z, dict(st, wartende_auftraege=2)), lauf_aktiv=True)["titel"]
        echt = z["dienst"].status
        z["dienst"].status = lambda: dict(
            echt(), cadwork_beschaeftigt=grund, wartende_auftraege=2,
            hinweis="Cadwork arbeitet gerade selbst (%s)." % grund)
        D._auffrischen(z)
        m["takt"] = (w["pille"].text(), _hinweis(z))
        z["dienst"].status = echt
        w["chat_modell_auf"].hide()
        _pumpen(0.05)
        fremd = QWidget(k.haupt, Qt.WindowType.Popup)
        fremd.resize(60, 40)
        fremd.show()
        _pumpen(0.05)
        grund_f = km._cadwork_beschaeftigt(sonden)
        m["fremd"] = (grund_f, D._pille_zustand(True, "ready", D._blockiert(
            z, dict(st, cadwork_beschaeftigt=grund_f,
                    wartende_auftraege=2)))[0])
        fremd.hide()
    finally:
        k.ende()
    return m


def zelle_eigenes_menue():
    """L107 (Gegenpruefung K12): die Sonde "popup" des Kerns zaehlt auch
    UNSEREN Popover — dann stand "Cadwork rechnet" in Pille und Anzeige und
    "Cadwork arbeitet gerade selbst" im Kontext. Jetzt: ohne wartende
    Auftraege nichts (Bereit), mit wartenden "Menü offen" bzw. "Wartet, bis
    das Menü zu ist"; ein FREMDES Popup bleibt "Cadwork rechnet"."""
    try:
        m = _menue_lauf()
        pruefe("L107 Vorbedingung: die Sonde des echten Kerns sieht den "
               "Popover", str(m["grund"]).startswith("Menue oder Popup offen"),
               m["grund"])
        pruefe("L107 eigenes Menue: ohne Wartende 'Bereit', mit Wartenden "
               "'Menü offen'; die Anzeige 'Wartet, bis das Menü zu ist'",
               m["leer"] == "Bereit" and m["wartet"] == "Menü offen"
               and m["anzeige"] == "Wartet, bis das Menü zu ist", m)
        pruefe("L107 im Takt: Pille 'Menü offen', im Kontext nicht 'Cadwork "
               "arbeitet gerade selbst'", m["takt"][0] == "● Menü offen"
               and "Cadwork arbeitet" not in m["takt"][1], m["takt"])
        pruefe("L107 ein FREMDES Popup bleibt 'Cadwork rechnet'",
               str(m["fremd"][0]).startswith("Menue oder Popup offen")
               and m["fremd"][1] == "Cadwork rechnet", m["fremd"])
        k = _menue_lauf(lambda: _mutant(_anweisungen(
            "_blockiert", lambda s: isinstance(s, ast.If))))
        pruefe("L107 KONTROLLE: ohne die Unterscheidung (bis K12) sagt die "
               "Pille beim eigenen Popover 'Cadwork rechnet'",
               k["treffer"] == [1] and k["wartet"] == "Cadwork rechnet"
               and k["leer"] == "Cadwork rechnet", k)
    finally:
        _frischer_start()


def _hinweis_chat_lauf(laden=None):
    """L108: ein Hinweis im Segment Chat und im Segment Briefkasten."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        d = z["dienst"]
        with d.sperre:
            d.hinweise.append(hinweis(7, "Fenstersturz geraten",
                                      ids=[2001, 2002]))
        k.aktion("chat")
        D._hinweise_zeigen(z, True)
        D._auffrischen(z)
        _pumpen(0.1)
        teile, knopf = w["hinweise"], w["hinweis_in_chat"]
        m["ohne_wahl"] = (knopf.isVisible(), knopf.isEnabled(),
                          teile["antwort"].isVisible(),
                          teile["btn_antwort"].isVisible())
        teile["gewaehlt_nr"] = 7
        D._auffrischen(z)
        m["mit_wahl"] = (knopf.isVisible(), knopf.isEnabled(),
                         teile["antwort"].isVisible(),
                         teile["btn_antwort"].isVisible())
        w["chat_eingabe"].setPlainText("bitte prüfen")
        vorher = len(d.job_queue.items)
        knopf.click()
        m["text"] = w["chat_eingabe"].toPlainText()
        m["gesendet"] = len(d.job_queue.items) - vorher
        m["seite"] = D._seite_jetzt(z)
        D._segment_waehlen(z, "briefkasten")
        _pumpen(0.05)
        m["brief"] = (knopf.isVisible(), teile["antwort"].isVisible(),
                      teile["antwort"].placeholderText())
    finally:
        k.ende()
    return m


def zelle_hinweis_in_chat():
    """L108 (Gegenpruefung K12, Spezifikation 3.5): im Segment Chat steht am
    Hinweis "In den Chat übernehmen" statt eines zweiten Sendefelds, das in
    den Briefkasten ging; der Knopf setzt "Zu Prüfhinweis #n «Titel»
    (Bauteile …): " vor die Chat-Eingabe und sendet NICHTS. Im Segment
    Briefkasten bleibt die Antwort dort, so beschriftet."""
    try:
        m = _hinweis_chat_lauf()
        pruefe("L108 Segment Chat: 'In den Chat übernehmen' erst mit Wahl "
               "(Gegenpruefung Laien-Sicht K12: ohne Wahl keine Knoepfe), "
               "kein Briefkasten-Feld",
               m["ohne_wahl"] == (False, False, False, False)
               and m["mit_wahl"] == (True, True, False, False),
               (m["ohne_wahl"], m["mit_wahl"]))
        pruefe("L108 der Knopf setzt den Bezug vor die Chat-Eingabe, nichts "
               "geht in den Briefkasten, der Chat bleibt vorn",
               m["text"] == "Zu Prüfhinweis #7 «Fenstersturz geraten» "
               "(Bauteile 2001, 2002): bitte prüfen"
               and m["gesendet"] == 0 and m["seite"] == "chat", m)
        pruefe("L108 Segment Briefkasten: das Feld 'Antwort in den "
               "Briefkasten …', kein Chat-Knopf",
               m["brief"] == (False, True, "Antwort in den Briefkasten …"),
               m["brief"])
        k = _hinweis_chat_lauf(lambda: _mutant(_anweisungen(
            "_hinweis_antwort_zeigen", _beginnt("chat = (z.get('segment')"),
            "chat = False")))
        pruefe("L108 KONTROLLE: Briefkasten-Feld auch im Chat (bis K12) -> "
               "zwei Sendewege, rot", k["treffer"] == [1]
               and k["mit_wahl"][2] is True, k["mit_wahl"])
    finally:
        _frischer_start()


def _pfeil_fuellung(feld):
    """Wie voll der Pfeil eines Auswahlfelds (rechte 22 px) seinen Rahmen
    fuellt: Anteil der dunklen Bildpunkte an ihrem umschliessenden Rechteck.
    Der alte Rahmen-Trick zeichnete einen VOLLEN Balken (~1,0), ein
    Winkel aus zwei Strichen fuellt ihn halb. -> (Anteil, Zahl)."""
    from PyQt6.QtGui import QImage
    bild = QImage(feld.size(), QImage.Format.Format_ARGB32)
    bild.fill(0xFFFFFFFF)
    feld.render(bild)
    punkte = []
    for x in range(max(0, feld.width() - 22), feld.width() - 3):
        for y in range(3, feld.height() - 3):
            c = bild.pixelColor(x, y)
            if c.red() < 170 and c.green() < 170 and c.blue() < 170:
                punkte.append((x, y))
    if not punkte:
        return (0.0, 0)
    xs, ys = [p_[0] for p_ in punkte], [p_[1] for p_ in punkte]
    flaeche = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    return (round(len(punkte) / float(flaeche), 2), len(punkte))


def _gestalt_lauf(laden=None):
    """L109: Kopf des Chats ohne Ordnerzeile, Koepfe und Liste im
    Briefkasten, die Karten der Einstellungsseite, der Pfeil der
    Auswahlfelder. -> dict."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QLabel
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        k.aktion("chat")
        k.aktion("andocken")
        _anbieter_waehlen(z, "codex")
        D._auffrischen(z)
        _pumpen(0.2)
        neu = w["chat_neu"]
        seite = w["seiten"].widget(0)
        rechts = neu.mapTo(seite, QPoint(neu.width(), 0)).x()
        m["neu"] = (w["chat_ordner_teil"].isHidden(), seite.width() - rechts,
                    neu.width(), neu.sizeHint().width())
        _anbieter_waehlen(z, "claude")
        # Briefkasten: drei Auftraege.
        d = z["dienst"]
        jetzt = time.time()
        with d.sperre:
            d.verlauf[:] = [{"methode": "execute_cwapi3d", "ok": True,
                             "beschreibung": "Wand %d" % i, "dauer_s": 1.0,
                             "beendet": jetzt - 10 * i} for i in (3, 2, 1)]
        D._segment_waehlen(z, "briefkasten")
        D._auffrischen(z)
        _pumpen(0.2)
        D._auffrischen(z)
        bs, kopf_a, liste = (w["briefkasten_seite"], w["auftraege_kopf"],
                             w["liste_auftraege"])
        notiz = [lb for lb in bs.findChildren(QLabel)
                 if lb.text() == "Notizen für die KI"][0]
        zeile = liste.sizeHintForRow(0)
        m["kopf"] = (kopf_a.mapTo(bs, QPoint(0, 0)).x(),
                     notiz.mapTo(bs, QPoint(0, 0)).x(),
                     kopf_a.fontInfo().pixelSize(),
                     notiz.fontInfo().pixelSize(),
                     kopf_a.font().weight() == notiz.font().weight())
        m["liste"] = (liste.count(), liste.height(), zeile,
                      int(bs.height() * D.AUFTRAEGE_ANTEIL))
        # Einstellungen: vier gleiche Karten.
        D._einstellungen_zeigen(z, True)
        _pumpen(0.1)
        karten = [w[n] for n in ("chat_einst_karte", "einst_karte_verbindung",
                                 "einst_karte_modus", "einst_karte_technik")]
        titel = [lb for kt in karten for lb in kt.findChildren(QLabel)
                 if lb.objectName() == "karte_titel"]
        m["karten"] = ([kt.objectName() for kt in karten],
                       sorted(lb.text() for lb in titel),
                       w["technik_knopf"].objectName(),
                       len({lb.fontInfo().pixelSize() for lb in titel}
                           | {w["technik_knopf"].fontInfo().pixelSize()}))
        # Die Wahl des Steckplatzes steht seit der Laien-Sicht K12 in den
        # Technik-Details — aufklappen, sonst ist nichts gezeichnet.
        D._technik_umschalten(z)
        _pumpen(0.1)
        feld = w["steckplatz_wahl"]
        m["pfeil"] = (bool(D._pfeil_datei()), _pfeil_fuellung(feld))
    finally:
        k.ende()
    return m


def zelle_gestalt():
    """L109 (Gegenpruefung K12, Bilder 04/06/09): "Neuer Chat" steht auch
    ohne Ordnerzeile (Codex) rechts; die Koepfe "Letzte Aufträge" und
    "Notizen für die KI" linksbuendig und gleich gesetzt, die Liste so hoch
    wie ihr Inhalt; auf der Einstellungsseite vier GLEICHE Karten (Chat,
    Verbindung, Zeichenmodus, Technik-Details) mit gleich grossen Titeln;
    der Pfeil der Auswahlfelder ein Symbol, kein schwarzer Balken."""
    try:
        m = _gestalt_lauf()
        # Seit der Laien-Sicht K12 steht "Neuer Chat" als Wort: so breit
        # wie Symbol + Wort (sizeHint), nicht wie die Zeile.
        pruefe("L109 Codex (ohne Ordnerzeile): 'Neuer Chat' so breit wie "
               "Symbol und Wort (sizeHint) am rechten Rand (<= 16 px) — "
               "nicht ueber die ganze Zeile mit dem Symbol in der Mitte",
               m["neu"][0] is True and m["neu"][1] <= 16
               and m["neu"][2] <= m["neu"][3] + 2 and m["neu"][2] <= 120,
               m["neu"])
        pruefe("L109 Briefkasten: 'Letzte Aufträge' linksbuendig wie "
               "'Notizen für die KI', gleich gross und gleich fett",
               abs(m["kopf"][0] - m["kopf"][1]) <= 12
               and m["kopf"][2] == m["kopf"][3] and m["kopf"][4], m["kopf"])
        n, h, zeile, hoechst = m["liste"]
        pruefe("L109 die Liste so hoch wie ihre drei Zeilen (nicht bis zur "
               "Grenze von 40 %)", n == 3 and h <= n * zeile + 12
               and h < hoechst, m["liste"])
        pruefe("L109 Einstellungen: vier Karten, Titel Chat, Verbindung, "
               "Zeichenmodus, Technik-Details gleich gross",
               m["karten"][0] == ["karte"] * 4
               and m["karten"][1] == ["Chat", "Verbindung", "Zeichenmodus"]
               and m["karten"][2] == "karte_titel" and m["karten"][3] == 1,
               m["karten"])
        pruefe("L109 der Pfeil der Auswahlfelder ist ein Symbol (ein Winkel, "
               "kein voller Balken)", m["pfeil"][0]
               and m["pfeil"][1][1] > 0 and m["pfeil"][1][0] < 0.7,
               m["pfeil"])
        k = _gestalt_lauf(lambda: _mutant(
            _anweisungen("_tab_chat", _beginnt("kopf.addStretch(0)")),
            _anweisungen("_briefkasten_bauen",
                         _beginnt("lay.addLayout(kopf_reihe)"),
                         "lay.addWidget(kopf_a, 0, "
                         "Qt.AlignmentFlag.AlignLeft)")))
        pruefe("L109 KONTROLLE: ohne den Stretch steht 'Neuer Chat' nicht "
               "rechts, mit der alten Ausrichtung steht der Kopf rechts",
               k["treffer"] == [1, 1] and k["neu"][2] > 60
               and k["kopf"][0] - k["kopf"][1] > 12, (k["neu"], k["kopf"]))

        def alter_pfeil():
            M = _mutant()
            M._PFEIL["pfad"] = None
            M.QSS += ("#OpenMcpCadA QComboBox::down-arrow { width: 0px; "
                      "height: 0px; border-left: 4px solid transparent; "
                      "border-right: 4px solid transparent; "
                      "border-top: 5px solid #6e6e73; }")
            return M
        k = _gestalt_lauf(alter_pfeil)
        pruefe("L109 KONTROLLE: der alte Rahmen-Trick zeichnet einen "
               "vollen Balken", k["pfeil"][1][0] >= 0.85, k["pfeil"])
    finally:
        _frischer_start()


# --- Gegenpruefung Laien-Sicht K12 (L110-L115) -------------------------------
# Eine Durchsicht "mit den Augen eines Zimmermanns ohne IT": dieselbe Zahl
# offener Hinweise zweimal, Knoepfe nur mit Zeichen, ein Ring wie ein
# Ladekreis, Fachwoerter ("Steckplatz A", "Port 53127", "120 ms je
# Bauteil", "Vorgabe von Codex", "anzoomen", "●●○○○"), offene Hinweise auf
# dem halben Fenster mit abgeschnittenem Text, und im Bild "Wartet auf
# deine Freigabe" keine Karte im Chat.

import re                                                   # noqa: E402

_CAD_WERKZEUG = "mcp__open-mcp-cad__execute_cadwork_command"


def _freigabe(i, text="Wand Süd"):
    return {"id": "f%d" % i, "offen": True, "werkzeug": _CAD_WERKZEUG,
            "name": "execute_cadwork_command",
            "eingabe": {"code": "x", "description": text}}


def _zahl_lauf(laden=None):
    """L110: die Zahl offener Hinweise je Zustand. -> dict."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        with d_sperre(z) as d:
            d.hinweise.extend(_hinweise_probe())
        D._auffrischen(z)
        _pumpen(0.2)
        chip, flagge = w["kopf_hinweise"], w["hinweise_knopf"]

        def stand():
            return (not chip.isHidden(), chip.text(), flagge.isVisible(),
                    flagge.property("zahl"), w["hinweise_titel"].text())
        m["pille"] = stand()
        m["pille_rand"] = k.kopf_g()
        k.aktion("chat")
        m["offen"] = stand()
        k.aktion("andocken")
        m["angedockt"] = stand()
        k.aktion("verkleinern")
        m["zurueck"] = stand()
        m["zurueck_rand"] = k.kopf_g()
    finally:
        k.ende()
    return m


def zelle_zahl_einmal():
    """L110: die Zahl offener Hinweise steht EINMAL — als Pille im Chip neben
    "Bereit" (dort ist sonst nichts zu sehen), offen und angedockt an der
    Flagge der Segmentzeile; der Titel des Bereichs nennt sie nicht noch
    einmal."""
    try:
        m = _zahl_lauf()
        pruefe("L110 Pille: Chip '3' im Kopf", m["pille"][:2] == (True, "3"),
               m["pille"])
        pruefe("L110 offen und angedockt: kein Chip, die Zahl an der Flagge, "
               "der Titel 'Hinweise' ohne Zahl",
               m["offen"] == (False, "3", True, 3, "Hinweise")
               and m["angedockt"] == (False, "3", True, 3, "Hinweise"),
               (m["offen"], m["angedockt"]))
        pruefe("L110 zurueck zur Pille: der Chip wieder da, die rechte Kante "
               "am alten Ort (±2 px)", m["zurueck"][:2] == (True, "3")
               and abs(m["zurueck_rand"][0] - m["pille_rand"][0]) <= 2,
               (m["zurueck"], m["pille_rand"], m["zurueck_rand"]))
        k = _zahl_lauf(lambda: _mutant(_anweisungen(
            "_chip_soll", lambda s: isinstance(s, ast.Return),
            "return int(n or 0) > 0")))
        pruefe("L110 KONTROLLE: Chip in jedem Zustand (bis K12) -> offen "
               "stehen Chip UND Flagge, rot",
               k["treffer"] == [1] and k["offen"][0] is True, k["offen"])
    finally:
        _frischer_start()


def _knopf_texte_lauf(laden=None, breite=None):
    """L111: Knoepfe ohne Wort, die Woerter im offenen Fenster, der letzte
    Knopf des Kopfs. -> dict."""
    from PyQt6.QtWidgets import QAbstractButton
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        an = w["kopf_andocken"]
        m["pille_andocken"] = (an.property("symbol"), an.accessibleName(),
                               an.toolTip(), an.icon().isNull())
        with d_sperre(z) as d:
            d.hinweise.extend(_hinweise_probe())
        k.aktion("chat")
        if breite:
            z["offen_groesse"] = (breite, 600)
            D._fenster_lage(z)
            _pumpen(0.3)
        z["chat"].update(an=True, laeuft_zug=False, anbieter="claude",
                         freigaben=[_freigabe(1)], ereignisse=[],
                         kontext={"belegt": 130000, "fenster": 200000},
                         stand=z["chat"].get("stand", 0) + 1)
        D._hinweise_zeigen(z, True)
        w["hinweise"]["gewaehlt_nr"] = 1
        D._chat_zeichnen(z)
        D._auffrischen(z)
        _pumpen(0.3)
        m["offen_worte"] = (w["chat_neu"].text(), w["chat_ende"].text())
        k.aktion("andocken")
        D._chat_zeichnen(z)
        _pumpen(0.2)
        m["angedockt_worte"] = (w["chat_neu"].text(), w["chat_ende"].text())
        m["angedockt_andocken"] = (an.property("symbol"),
                                   an.accessibleName(), an.toolTip())
        wurzeln = [z["fenster"]] + ([z["anzeige"]] if z.get("anzeige")
                                    is not None else [])
        ohne, zahl = [], 0
        for wurzel in wurzeln:
            for b in wurzel.findChildren(QAbstractButton):
                if b.metaObject().className() == "QDockWidgetTitleButton":
                    continue                  # Qts eigene, nie zu sehen
                zahl += 1
                if not b.text().strip() and (not b.toolTip().strip()
                                             or not b.accessibleName()
                                             .strip()):
                    ohne.append((b.objectName(), b.property("symbol"),
                                 b.toolTip()[:30], b.accessibleName()))
        m["ohne"], m["zahl"] = ohne, zahl
    finally:
        k.ende()
    return m


def zelle_knopf_texte():
    """L111: jeder Knopf ohne Wort hat Tooltip UND accessibleName (alle
    Knoepfe des Fensters samt Popover, Aufklappern, Hinweis-Karten und
    Freigabe-Karte, dazu die Arbeitsanzeige); im offenen und angedockten
    Fenster stehen "Neuer Chat" und "Beenden" als Wort; der letzte Knopf
    des Kopfs zeigt "Vergroessern/Andocken" (maximize-2, Tooltip "Rechts
    andocken"), angedockt "Abdocken" (minimize-2)."""
    try:
        m = _knopf_texte_lauf()
        pruefe("L111 jeder Knopf ohne Wort hat Tooltip und accessibleName "
               "(%d Knoepfe)" % m["zahl"], m["zahl"] > 40 and not m["ohne"],
               m["ohne"][:4])
        pruefe("L111 offen (420 px) und angedockt: 'Neuer Chat' und "
               "'Beenden' als Wort",
               m["offen_worte"] == ("Neuer Chat", "Beenden")
               and m["angedockt_worte"] == ("Neuer Chat", "Beenden"),
               (m["offen_worte"], m["angedockt_worte"]))
        pruefe("L111 der letzte Knopf des Kopfs: als Pille zwei Pfeile nach "
               "aussen (maximize-2), Tooltip 'Rechts andocken'; angedockt "
               "nach innen (minimize-2), 'Abdocken'",
               m["pille_andocken"] == ("andocken", "Rechts andocken",
                                       "Rechts andocken", False)
               and m["angedockt_andocken"][:2] == ("abdocken", "Abdocken")
               and _symbol_name("andocken") == "maximize-2"
               and _symbol_name("abdocken") == "minimize-2",
               (m["pille_andocken"], m["angedockt_andocken"]))
        k = _knopf_texte_lauf(lambda: _mutant(_anweisungen(
            "_koerper_bauen", _beginnt("b.setToolTip(tipp)"))))
        pruefe("L111 KONTROLLE: die Werkzeugknoepfe ohne Tooltip -> rot",
               k["treffer"] == [1] and len(k["ohne"]) >= 4, k["ohne"][:3])
        k = _knopf_texte_lauf(lambda: _mutant(_anweisungen(
            "_qt_klassen", _beginnt("self._ab_breite = ab_breite"),
            "self._ab_breite = 400")))
        pruefe("L111 KONTROLLE: Wort erst ab 400 px (bis K12) -> im offenen "
               "Fenster nur Zeichen, rot", k["treffer"] == [1]
               and k["offen_worte"] == ("", ""), k["offen_worte"])
        k = _knopf_texte_lauf(breite=340)
        pruefe("L111 schmal (340 px): Zeichen statt gekuerzter Woerter, der "
               "Ordner geht vor (Tooltip und accessibleName bleiben)",
               k["offen_worte"] == ("", "") and not k["ohne"],
               (k["offen_worte"], k["ohne"][:2]))
    finally:
        _frischer_start()


def _symbol_name(zweck):
    D = dashboard_laden()
    return D.SYMBOLE[zweck][0]


#: Was ein Zimmermann nicht lesen soll (ausser in den Technik-Details).
_FACHWORT = re.compile(r"Steckplatz|\bPort\b|\b\d+\s*ms\b|Vorgabe von|"
                       r"anzoomen|[●○]{2,}|○")


def _alle_sichtbaren(wurzel):
    from PyQt6.QtWidgets import QAbstractButton, QLabel
    texte = [lb.text() for lb in wurzel.findChildren(QLabel)
             if lb.isVisible() and lb.text()]
    texte += [b.text() for b in wurzel.findChildren(QAbstractButton)
              if b.isVisible() and b.text()]
    return texte


def _fachwort_lauf(laden=None):
    """L112: alle sichtbaren Texte im Chat, mit Hinweisen, im Briefkasten,
    auf den Einstellungen, im Popover (Codex) — danach die
    Technik-Details. -> dict."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer, "funde": []}
    try:
        echt = dashboard_laden()._verbindungen_zeichnen
        D._verbindungen_zeichnen = types.FunctionType(
            echt.__code__, D.__dict__, echt.__name__)
        z["monitor_daten"] = [{"port": 53127, "instanz": "A",
                               "zustand": "ready", "dokument": "Probe.3d",
                               "version": "2.19.1", "antwortzeit_ms": 4,
                               "wartende_auftraege": 0}]
        with d_sperre(z) as d:
            d.hinweise.extend(_hinweise_probe())
        k.aktion("chat")
        k.aktion("andocken")

        def sammeln(wo):
            D._auffrischen(z)
            _pumpen(0.2)
            for t in _alle_sichtbaren(z["fenster"]):
                if _FACHWORT.search(t):
                    m["funde"].append((wo, t[:60]))
        sammeln("chat")
        D._hinweise_zeigen(z, True)
        w["hinweis_umgebung"]["waehlen"](1)
        sammeln("hinweise")
        D._hinweise_zeigen(z, False)
        D._segment_waehlen(z, "briefkasten")
        sammeln("briefkasten")
        D._einstellungen_zeigen(z, True)
        sammeln("einstellungen")
        m["kontext"] = w["kontext_zeile"].text()
        m["karte"] = [kk["titel"].text() + " | " + kk["dok"].text()
                      for kk in w["verb_karten"].values()]
        D._technik_umschalten(z)
        _warte_qt(D, z, lambda: "Port 53127" in w["technik"].text(), 5)
        m["technik"] = (w["technik"].text(),
                        w["steckplatz_reihe"].isVisible())
        D._technik_umschalten(z)
        D._einstellungen_zeigen(z, False)
        D._segment_waehlen(z, "chat")
        _anbieter_waehlen(z, "codex")
        w["chat_modell_knopf"].click()
        _pumpen(0.2)
        for t in _alle_sichtbaren(w["chat_modell_auf"]):
            if _FACHWORT.search(t):
                m["funde"].append(("popover", t[:60]))
        m["codex"] = (w["stufe_gross"].text(),
                      w["chat_modell_knopf"].volltext())
        w["chat_modell_auf"].hide()
        _anbieter_waehlen(z, "claude")
    finally:
        k.ende()
    return m


def zelle_fachwoerter():
    """L112: kein "Steckplatz", "Port", "… ms", "Vorgabe von", "anzoomen",
    "●●○○○" in den sichtbaren Texten von Chat, Hinweisen, Briefkasten,
    Einstellungen und Popover; Steckplatz, Port und die Zeit je Bauteil
    stehen in den Technik-Details."""
    try:
        m = _fachwort_lauf()
        pruefe("L112 keine Fachwoerter in den sichtbaren Texten (Chat, "
               "Hinweise, Briefkasten, Einstellungen, Popover)",
               not m["funde"], m["funde"][:4])
        pruefe("L112 Kontextzeile nur die Datei, Verbindung 'Dieses "
               "Cadwork | Probe.3d', ohne Modell 'Automatisch'",
               m["kontext"] == "Probe.3d"
               and m["karte"] == ["Dieses Cadwork | Probe.3d"]
               and m["codex"] == ("Automatisch", "Modell: automatisch"),
               (m["kontext"], m["karte"], m["codex"]))
        pruefe("L112 Technik-Details: Steckplatz-Wahl, Port und die Zeit je "
               "Bauteil", m["technik"][1]
               and "Steckplatz A · Port 53127" in m["technik"][0]
               and "120 ms je Bauteil" in m["technik"][0], m["technik"])
        k = _fachwort_lauf(lambda: _mutant(_anweisungen(
            "_auffrischen", _beginnt("text = dok"),
            "text = '%s · Steckplatz A' % dok")))
        pruefe("L112 KONTROLLE: die Kontextzeile mit 'Steckplatz A' (bis "
               "K12) -> rot", k["treffer"] == [1]
               and any(wo == "chat" for wo, _t in k["funde"]), k["funde"][:2])
    finally:
        _frischer_start()


def _hinweis_platz_lauf(laden=None):
    """L113: der Hinweis-Bereich angedockt mit drei Hinweisen (einer
    lang), ohne und mit Wahl. -> dict."""
    from PyQt6.QtWidgets import QLabel
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        with d_sperre(z) as d:
            d.hinweise.extend(_hinweise_probe())
        k.aktion("chat")
        k.aktion("andocken")
        D._hinweise_zeigen(z, True)
        D._auffrischen(z)
        _pumpen(0.3)
        D._auffrischen(z)
        _pumpen(0.2)
        teile = w["hinweise"]
        bereich, koerper = w["hinweise_bereich"], w["koerper"]
        liste, rolle = w["hinweise_liste"], w["hinweise_rolle"]
        m["anteil"] = round(bereich.height() / float(koerper.height()), 3)
        rand = 2 * liste.frameWidth()
        innen = teile["innen"]
        m["liste"] = (liste.height() - rand,
                      innen.heightForWidth(liste.width() - rand))
        abgeschnitten = []
        for karte in teile["karten"].values():
            for lb in karte.widget.findChildren(QLabel):
                if lb.isVisibleTo(karte.widget) and lb.wordWrap() \
                        and lb.height() + 1 < lb.heightForWidth(lb.width()):
                    abgeschnitten.append((karte.nr, lb.text()[:30],
                                          lb.height(),
                                          lb.heightForWidth(lb.width())))
        m["abgeschnitten"] = abgeschnitten
        sb = rolle.verticalScrollBar()
        m["rollt"] = (sb.maximum() > 0,
                      rolle.widget().height() > rolle.viewport().height())
        m["ohne_wahl"] = (w["hinweise_tipp"].isVisible(),
                          w["hinweis_in_chat"].isVisible(),
                          teile["chk_zoom"].isVisible(),
                          teile["btn_loeschen"].isVisible())
        w["hinweis_umgebung"]["waehlen"](1)
        _pumpen(0.3)
        m["mit_wahl"] = (w["hinweise_tipp"].isVisible(),
                         D._ganz_zu_sehen(w["hinweis_in_chat"], z["fenster"]),
                         teile["kontext"].isVisible(),
                         teile["chk_zoom"].text(),
                         D._ganz_zu_sehen(teile["karten"][1].widget,
                                          z["fenster"]))
        m["anteil_wahl"] = round(bereich.height() / float(koerper.height()),
                                 3)
    finally:
        k.ende()
    return m


def zelle_hinweis_platz():
    """L113: offene Hinweise nehmen hoechstens 40 % des Koerpers, jeder
    Hinweis steht in voller Hoehe (Text umbrochen, nicht abgeschnitten),
    was nicht passt, rollt als Ganzes; ohne Wahl statt der Knoepfe eine
    Zeile, mit Wahl die Knoepfe im Blick."""
    try:
        m = _hinweis_platz_lauf()
        pruefe("L113 der Bereich hoechstens 40 % des Koerpers, mit "
               "gewaehltem Hinweis (Knoepfe darunter) hoechstens 50 %",
               0 < m["anteil"] <= 0.41 and 0 < m["anteil_wahl"] <= 0.51,
               (m["anteil"], m["anteil_wahl"]))
        pruefe("L113 die Liste so hoch wie alle Hinweise, kein Text einer "
               "Karte abgeschnitten", m["liste"][0] >= m["liste"][1] - 1
               and not m["abgeschnitten"],
               (m["liste"], m["abgeschnitten"][:2]))
        pruefe("L113 was nicht passt, rollt (der Bereich als Ganzes)",
               m["rollt"] == (True, True), m["rollt"])
        pruefe("L113 ohne Wahl: die Zeile statt der Knoepfe; mit Wahl die "
               "Knoepfe (der Bezug steht im Chat im eingefuegten Text), der "
               "gewaehlte Hinweis und 'In den Chat übernehmen' "
               "ganz zu sehen, 'nah heran'",
               m["ohne_wahl"] == (True, False, False, False)
               and m["mit_wahl"] == (False, True, False, "nah heran", True),
               (m["ohne_wahl"], m["mit_wahl"]))
        k = _hinweis_platz_lauf(lambda: _mutant(_ohne_aufruf(
            "_hoechstmasse", "_hinweise_masse")))
        pruefe("L113 KONTROLLE: die Liste rollt im eigenen Streifen (bis "
               "K12) -> Hinweise abgeschnitten, rot", k["treffer"] == [1]
               and (k["liste"][0] < k["liste"][1] - 1
                    or k["abgeschnitten"]), (k["liste"], k["abgeschnitten"][:1]))

        def breit():
            M = dashboard_laden()
            M.HINWEISE_ANTEIL = 0.6
            M._mutant_treffer = [1]
            return M
        k = _hinweis_platz_lauf(breit)
        pruefe("L113 KONTROLLE: 60 % statt 40 % -> der Bereich zu hoch, rot",
               k["anteil"] > 0.41, k["anteil"])
    finally:
        _frischer_start()


def _freigabe_sicht_lauf(laden=None):
    """L114: eine Freigabe kommt an — angedockt mit offenen Hinweisen, aus
    dem Briefkasten ueber "Zum Chat", aus der Pille ueber "Zum Chat".
    -> dict."""
    k = _K12(laden=laden)
    D, z, w = k.D, k.z, k.w
    m = {"treffer": k.treffer}
    try:
        def knoepfe():
            karte = D._erste_freigabe(z)
            if karte is None:
                return None
            return tuple(D._ganz_zu_sehen(b, z["fenster"])
                         for b in (karte.knopf_ja, karte.knopf_nein))
        with d_sperre(z) as d:
            d.hinweise.extend(_hinweise_probe())
        k.aktion("chat")
        k.aktion("andocken")
        D._hinweise_zeigen(z, True)
        w["hinweis_umgebung"]["waehlen"](1)
        z["chat"].update(an=True, laeuft_zug=True, anbieter="claude",
                         freigaben=[], ereignisse=[],
                         stand=z["chat"].get("stand", 0) + 1)
        D._auffrischen(z)
        _pumpen(0.2)
        z["chat"]["freigaben"] = [_freigabe(1)]
        z["chat"]["stand"] += 1
        D._auffrischen(z)
        _pumpen(0.3)
        m["angedockt"] = (knoepfe(), w["pille"].text())
        D._segment_waehlen(z, "briefkasten")
        _pumpen(0.1)
        m["briefkasten"] = knoepfe()
        D._zum_chat(z)
        _pumpen(0.3)
        m["zum_chat"] = (knoepfe(), D._seite_jetzt(z))
        k.aktion("verkleinern")
        m["pille"] = knoepfe()
        D._zum_chat(z)
        _pumpen(0.4)
        m["aus_pille"] = (knoepfe(), z["fenster_zustand"])
    finally:
        k.ende()
    return m


def zelle_freigabe_sicht():
    """L114: kommt eine Freigabe an, stehen "Erlauben" und "Ablehnen" GANZ
    zu sehen (angedockt, auch mit offenen Hinweisen); aus dem Briefkasten
    und aus der Pille bringt "Zum Chat" die Karte in den Blick. Das Bild
    12 rendert die echte Karte (scripts/bilder_rendern.py bricht ohne sie
    ab)."""
    try:
        m = _freigabe_sicht_lauf()
        pruefe("L114 angedockt mit offenen Hinweisen: Erlauben und Ablehnen "
               "ganz zu sehen, die Pille 'Wartet auf dich'",
               m["angedockt"][0] == (True, True)
               and "Wartet auf dich" in m["angedockt"][1], m["angedockt"])
        pruefe("L114 im Briefkasten nicht zu sehen; 'Zum Chat' -> Chat vorn, "
               "beide Knoepfe ganz zu sehen",
               m["briefkasten"] == (False, False)
               and m["zum_chat"] == ((True, True), "chat"),
               (m["briefkasten"], m["zum_chat"]))
        pruefe("L114 aus der Pille: 'Zum Chat' oeffnet, beide Knoepfe ganz zu "
               "sehen", m["pille"] == (False, False)
               and m["aus_pille"] == ((True, True), "offen"),
               (m["pille"], m["aus_pille"]))
        k = _freigabe_sicht_lauf(lambda: _mutant(_anweisungen(
            "_chat_zeichnen", _beginnt("w['chat_freigabe'].setVisible"))))
        pruefe("L114 KONTROLLE: die Karten bleiben versteckt -> rot",
               k["treffer"] == [1] and k["angedockt"][0] == (False, False),
               k["angedockt"])
        k = _freigabe_sicht_lauf(lambda: _mutant(_ohne_aufruf(
            "_chat_oeffnen", "_segment_waehlen")))
        pruefe("L114 KONTROLLE: 'Zum Chat' ohne Wechsel des Segments -> die "
               "Karte bleibt im Briefkasten verborgen, rot",
               k["treffer"] == [1] and k["zum_chat"][0] != (True, True),
               k["zum_chat"])
    finally:
        _frischer_start()


# --- L115: angedockt deckend, nie durchsichtig (Cadwork 2026-10-08) ---------
# Gemessen in Cadwork 2026: angedockt war das Fenster unsichtbar (alte Bilder
# der 3D-Ansicht an seiner Stelle). Jedes Dock ist dort ein natives Kind
# (die 3D-Mitte ist nativ), und ein Dock, das je WA_TranslucentBackground
# trug, behaelt ein Format mit Alphakanal — zur Laufzeit nicht zu heilen.
# Nachgestellt: Cadwork-Ersatz mit NATIVER Mitte; offscreen und auf der
# echten Windows-Plattform zeigt das alte Fenster angedockt
# alphaBufferSize 8 (gemessen 2026-10-08, PyQt6 6.11).

def _deckend_lauf(laden=None):
    """Klick, Chat, Andocken, Abdocken, Verkleinern neben einer nativen
    Mitte; WA_TranslucentBackground am Dock wird bei JEDEM Setzen
    mitgeschrieben (auch beim Bau). -> dict."""
    import PyQt6.QtWidgets as QtW
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QApplication
    transl = Qt.WidgetAttribute.WA_TranslucentBackground
    gesetzt = []
    echt = QtW.QDockWidget

    class Spion(echt):
        def setAttribute(self, attr, an=True):        # noqa: N802
            if attr == transl and an:
                gesetzt.append(self.objectName() or "?")
            super().setAttribute(attr, an)
    QtW.QDockWidget = Spion
    try:
        k = _K12(laden=laden, fremd_dock=True, nativ=True, ort=(20, 40),
                 groesse=(1000, 700))
    finally:
        QtW.QDockWidget = echt
    z, f = k.z, k.f
    m = {"treffer": k.treffer, "gesetzt": gesetzt, "je_zustand": {}}

    def alpha():
        h = f.windowHandle()
        return h.format().alphaBufferSize() if h is not None else None

    def schwebend():
        maske = f.mask()
        rand = f.style().pixelMetric(
            QtW.QStyle.PixelMetric.PM_DockWidgetFrameWidth, None, f)
        r = maske.boundingRect()
        return {"maske": not maske.isEmpty(),
                "ecke_weg": not maske.contains(QPoint(rand + 1, rand + 1)),
                "mitte": maske.contains(QPoint(f.width() // 2,
                                               f.height() // 2)),
                "rahmen": (r.x(), r.y(), r.width(), r.height())
                == (rand, rand, f.width() - 2 * rand,
                    f.height() - 2 * rand),
                "alpha": alpha()}

    def durchsichtige(bild):
        n = 0
        for y in range(bild.height()):
            for x in range(bild.width()):
                if bild.pixelColor(x, y).alpha() < 255:
                    n += 1
        return n

    def merken(name):
        m["je_zustand"][name] = (z["fenster_zustand"], f.testAttribute(transl))
    try:
        merken("klick")
        m["pille"] = schwebend()
        k.aktion("chat")
        merken("chat")
        m["offen"] = schwebend()
        # Der Nutzer zieht am Rand: die Maske folgt.
        f.resize(f.width() + 40, f.height() + 30)
        _pumpen(0.05)
        m["groesser"] = schwebend()
        k.aktion("andocken", 0.5)
        merken("andocken")
        bild = f.grab().toImage()
        m["angedockt"] = {
            "schwebt": f.isFloating(), "nativ":
            f.testAttribute(Qt.WidgetAttribute.WA_NativeWindow),
            "alpha": alpha(), "maske_leer": f.mask().isEmpty(),
            "fuellt": f.autoFillBackground(),
            "durchsichtig": durchsichtige(bild),
            "bild": (bild.width(), bild.height()), "groesse":
            (f.width(), f.height())}
        # Durchsichtige Widgets im Prozess: nur eigene Fenster (Popover,
        # Aufklapper, Arbeitsanzeige), nie ein Kind im angedockten Fenster.
        m["kinder"] = sorted(
            wd.objectName() or type(wd).__name__
            for wd in QApplication.allWidgets()
            if wd.testAttribute(transl) and not wd.isWindow())
        anz = z.get("anzeige")
        m["anzeige"] = (anz is None or (anz.isWindow()
                                        and anz.parentWidget() is k.haupt
                                        and not f.isAncestorOf(anz)))
        k.aktion("andocken")
        merken("abdocken")
        m["wieder_offen"] = schwebend()
        k.aktion("verkleinern")
        merken("verkleinern")
        m["wieder_pille"] = schwebend()
    finally:
        k.ende()
    return m


def _deckend_ok(m):
    """-> Liste der Befunde (leer = alles wie verlangt)."""
    falsch = []
    if m["gesetzt"]:
        falsch.append("WA_TranslucentBackground gesetzt: %s" % m["gesetzt"])
    for name, (_zust, transl) in m["je_zustand"].items():
        if transl:
            falsch.append("durchsichtig nach %s" % name)
    return falsch


#: Die Kontrollen von L115: Name -> Mutant (im Kind-Prozess gebaut).
_DECKEND_MUTANTEN = {
    # Wie bis 2026-10-08: durchsichtig gebaut.
    "alt": lambda: _mutant(_anweisungen(
        "_fenster_bauen", _beginnt("dock.setObjectName(FENSTER_NAME)"),
        "dock.setObjectName(FENSTER_NAME)\n"
        "dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)")),
    # Nur kurz: beim Bau gesetzt, gleich wieder weg.
    "kurz": lambda: _mutant(_anweisungen(
        "_fenster_bauen", _beginnt("dock.setAutoFillBackground(True)"),
        "dock.setAutoFillBackground(True)\n"
        "dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)\n"
        "dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, "
        "False)")),
    "ohne_maske": lambda: _mutant(_anweisungen(
        "_fenster_maske", _beginnt("dock.setMask("), "pass")),
    "maske_bleibt": lambda: _mutant(_anweisungen(
        "_fenster_maske", _beginnt("dock.clearMask("), "pass")),
    "ohne_filter": lambda: _mutant(_anweisungen(
        "_fenster_bauen", _beginnt("z['fenster_masken'] = "))),
    "ohne_grund": lambda: _mutant(_anweisungen(
        "_fenster_bauen", _beginnt("dock.setAutoFillBackground(True)"),
        "dock.setAutoFillBackground(False)")),
}


def _deckend_kind():
    """Im KIND-Prozess (L115): der echte Lauf und alle Kontrollen neben
    einer NATIVEN Mitte. Druckt eine JSON-Zeile und endet mit os._exit:
    native Fenster, die bis zum Ende des Interpreters leben, brechen
    offscreen beim Aufraeumen mit Segmentation fault ab (gemessen, rc 139;
    auch ein Freigeben vorher stuerzte) — das darf das Gate nicht treffen."""
    from PyQt6.QtWidgets import QApplication
    global _APP
    _APP = QApplication.instance() or QApplication([])
    _draht_legen()
    aufbauen()
    erg = {"echt": _deckend_lauf()}
    for name, laden in _DECKEND_MUTANTEN.items():
        erg[name] = _deckend_lauf(laden)
    sys.stdout.write("DECKENDKIND " + json.dumps(erg) + "\n")
    sys.stdout.flush()
    os._exit(0)


def zelle_angedockt_deckend():
    """L115 (gemessen in Cadwork 2026-10-08: angedockt unsichtbar): das
    Fenster traegt NIE WA_TranslucentBackground (Bau, schwebend,
    angedockt); angedockt neben einer NATIVEN Mitte hat sein natives
    Fenster kein Alpha-Format, keine Maske, fuellt seinen Grund und rendert
    ohne einen durchsichtigen Pixel; schwebend (Pille, offen, nach dem
    Ziehen am Rand, nach dem Abdocken) schneidet eine Maske die runde Karte
    aus. Durchsichtig sind nur eigene Fenster (Popover, Aufklapper,
    Arbeitsanzeige an Cadworks Hauptfenster), nie ein Kind im Dock.
    Im Kind-Prozess (native Fenster, s. `_deckend_kind`)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    erg = subprocess.run([sys.executable, os.path.abspath(__file__),
                          "--deckend-kind"], env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         timeout=300)
    zeile = [z_ for z_ in erg.stdout.splitlines()
             if z_.startswith("DECKENDKIND ")]
    if not zeile:
        pruefe("L115 Kind-Prozess mit nativer Mitte lief", False,
               (erg.returncode, erg.stdout[-500:], erg.stderr[-1500:]))
        return
    d = json.loads(zeile[-1][len("DECKENDKIND "):])
    m = d["echt"]
    pruefe("L115 nie WA_TranslucentBackground am Fenster (Bau, Pille, "
           "offen, angedockt, abgedockt, Pille)", _deckend_ok(m) == []
           and len(m["je_zustand"]) == 5, (_deckend_ok(m), m["je_zustand"]))
    a = m["angedockt"]
    pruefe("L115 angedockt neben nativer Mitte: natives Kind wie in "
           "Cadwork, Format OHNE Alphakanal",
           a["schwebt"] is False and a["nativ"] is True
           and a["alpha"] is not None and a["alpha"] <= 0, a)
    pruefe("L115 angedockt keine Maske, Grund gefuellt, grab() ohne "
           "einen durchsichtigen Pixel (ganzes Fenster)",
           a["maske_leer"] and a["fuellt"] and a["durchsichtig"] == 0
           and a["bild"] == a["groesse"], a)
    rund = ("maske", "ecke_weg", "mitte", "rahmen")
    for name in ("pille", "offen", "groesser", "wieder_offen",
                 "wieder_pille"):
        g = m[name]
        pruefe("L115 schwebend (%s): Maske = runde Karte im Rahmen, Ecke "
               "weg, Mitte drin, kein Alphakanal" % name,
               all(g[t] for t in rund)
               and (g["alpha"] is None or g["alpha"] <= 0), g)
    pruefe("L115 durchsichtig nur eigene Fenster — kein Kind im Dock; "
           "die Arbeitsanzeige ist ein Fenster an Cadworks Hauptfenster",
           m["kinder"] == [] and m["anzeige"], (m["kinder"], m["anzeige"]))
    # KONTROLLEN
    k = d["alt"]
    ka = k["angedockt"]
    pruefe("L115 KONTROLLE: das alte Fenster (durchsichtig gebaut) faellt "
           "auf — Setzen mitgeschrieben, angedockt Alphakanal 8, ein "
           "durchsichtiges Kind im Dock", k["treffer"] == [1]
           and _deckend_ok(k) != [] and ka["alpha"] == 8
           and k["kinder"] == ["OpenMcpCadFenster"],
           (k["treffer"], _deckend_ok(k), ka["alpha"], k["kinder"]))
    k = d["kurz"]
    # (Vor dem ersten Zeigen gibt es noch kein natives Fenster: das Format
    # bleibt hier ohne Alphakanal, gemessen — rot wird es am Mitschreiben
    # jedes Setzens.)
    pruefe("L115 KONTROLLE: auch nur kurz durchsichtig (beim Bau gesetzt, "
           "gleich wieder weg) wird rot", k["treffer"] == [1]
           and _deckend_ok(k) != [] and k["gesetzt"] != [],
           (k["treffer"], k["gesetzt"], k["angedockt"]["alpha"]))
    k = d["ohne_maske"]
    pruefe("L115 KONTROLLE: ohne setMask ist das schwebende Fenster "
           "eckig", k["treffer"] == [1] and not k["pille"]["maske"]
           and not k["offen"]["maske"], (k["treffer"], k["pille"]))
    k = d["maske_bleibt"]
    pruefe("L115 KONTROLLE: bleibt die Maske beim Andocken, wird die "
           "Zeile 'keine Maske' rot", k["treffer"] == [1]
           and not k["angedockt"]["maske_leer"], k["angedockt"])
    k = d["ohne_filter"]
    pruefe("L115 KONTROLLE: ohne den Filter folgt die Maske dem Ziehen am "
           "Rand nicht", k["treffer"] == [1]
           and not k["groesser"]["rahmen"], (k["treffer"], k["groesser"]))
    k = d["ohne_grund"]
    pruefe("L115 KONTROLLE: ohne gefuellten Grund faellt angedockt auf",
           k["treffer"] == [1] and not k["angedockt"]["fuellt"],
           k["angedockt"])


# --- L116: "×" ohne Verbindung schliesst das Fenster ganz (2026-10-08) ------

def _schliessen_lauf(laden=None):
    """Verbunden in allen drei Zustaenden, dann ohne Verbindung (nie
    verbunden bzw. getrennt), das "×", der naechste Plugin-Klick. -> dict.
    Mit dem ECHTEN Steckplatz-Thread (`_klick` ersetzt ihn sonst; sein
    Client ist die Attrappe, kein Netz)."""
    echt = {}

    def laden_echt():
        M = (laden or dashboard_laden)()
        echt["monitor"] = M._monitor_starten
        return M
    k = _K12(laden=laden_echt)
    D, z = k.D, k.z
    # Der Thread haengt in `alle_status`, bis die Zelle endet: so lebt der
    # alte sicher noch, wenn der Klick nach dem "×" kommt (sonst haengt es
    # vom Takt seines 1-s-Schlafs ab — im vollen Gate einmal gemessen: der
    # Neubau des Fensters dauerte laenger als der Rest des Schlafs).
    halt = threading.Event()
    client = D._verbindungen_client()

    class Haengt:
        def __getattr__(self, name):
            return getattr(client, name)

        def alle_status(self):
            halt.wait(30)
            return {}
    D._verbindungen_client = Haengt
    D._monitor_starten = echt["monitor"]
    D._monitor_starten(z)
    m = {"treffer": k.treffer, "verbunden": {}}

    def x_sichtbar():
        zu = z["w"].get("kopf_schliessen")
        return zu is not None and zu.isVisible()
    gerufen = []
    try:
        for aktion in (None, "chat", "andocken"):
            if aktion:
                k.aktion(aktion)
            m["verbunden"][z["fenster_zustand"]] = x_sichtbar()
        # Verbunden: auch ein direkter Ruf schliesst nicht.
        m["verbunden_ruf"] = (D._fenster_schliessen(z),
                              z.get("fenster") is k.f and k.f.isVisible())
        if m["verbunden_ruf"][0]:
            return m                         # (Kontrolle: schon zu)
        k.aktion("verkleinern")
        # Getrennt (wie nach "Trennen": der Dienst endet).
        z["dienst"].beenden = True
        D._auffrischen(z)
        zu = z["w"].get("kopf_schliessen")
        m["getrennt"] = (x_sichtbar(), zu.toolTip() if zu else None,
                         zu.accessibleName() if zu else None)
        # Nie verbunden.
        z["dienst"] = None
        D._auffrischen(z)
        m["nie"] = x_sichtbar()
        for aktion in ("chat", "andocken"):
            k.aktion(aktion)
            m["ohne_" + z["fenster_zustand"]] = x_sichtbar()
        # Angedockt mit "×" UND "Verkleinern": der Kopf passt in die
        # schmalste Spalte.
        kopf = z["w"]["kopf"]
        kopf.layout().activate()
        m["kopf_min"] = (kopf.minimumSizeHint().width(),
                         D.ANGEDOCKT_BREITE_MIN)
        alt, takt, anzeige = k.f, z.get("timer"), z.get("anzeige")
        faden = z.get("monitor")
        z["w"]["kopf_schliessen"].click()
        # Gleich danach (ein Klick kurz nach dem Schliessen): der alte
        # Steckplatz-Thread lebt noch.
        _pumpen(0.02)

        def lebt(o):
            try:
                return o is not None and o.isVisible()
            except RuntimeError:                     # geloescht
                return False

        def tickt(t):
            try:
                return t is not None and t.isActive()
            except RuntimeError:
                return False
        m["zu"] = {"sichtbar": _sichtbare_fenster(),
                   "alt_sichtbar": lebt(alt), "fenster": z.get("fenster"),
                   "takt": tickt(takt), "anzeige": lebt(anzeige),
                   "monitor": bool(z.get("monitor_an")),
                   "zustand": z.get("fenster_zustand")}
        m["zu"]["fenster"] = m["zu"]["fenster"] is not None
        # Der naechste Plugin-Klick: zurueck als Pille, und er verbindet.
        D._verbinden = lambda z_: gerufen.append(1) or "verbunden"
        m["alt_lebt"] = faden is not None and faden.is_alive()
        D.oeffnen(z["kern_laden"], z["cfg_bauen"], verbinden=True)
        _pumpen(0.3)
        f = z.get("fenster")
        m["wieder"] = {"sichtbar": _sichtbare_fenster(),
                       "pille": z.get("fenster_zustand") == D.PILLE_Z
                       and f is not None and f.widget().isHidden(),
                       "takt": tickt(z.get("timer")),
                       "monitor": bool(z.get("monitor_an"))
                       and z.get("monitor") is not None
                       and z["monitor"].is_alive(),
                       "verbinden": gerufen[:], "x": x_sichtbar()}
        # Verbunden: das "×" geht wieder weg.
        z["dienst"] = Dienst()
        D._auffrischen(z)
        m["wieder"]["x_verbunden"] = x_sichtbar()
    finally:
        z["monitor_an"] = False
        halt.set()
        k.ende()
    return m


def zelle_schliessen():
    """L116 (Rueckmeldung 2026-10-08): ohne Verbindung (nie verbunden oder
    nach "Trennen") steht im Kopf ein "×" ("Schliessen"); verbunden nie, in
    keinem Zustand, und ein Ruf schliesst dann auch nichts. Das "×"
    schliesst das Fenster GANZ (auch die Pille): kein Fenster mehr zu
    sehen, Takt und Steckplatz-Thread aus, Arbeitsanzeige weg. Der naechste
    Plugin-Klick bringt die Pille zurueck und verbindet wie immer."""
    try:
        m = _schliessen_lauf()
        pruefe("L116 verbunden kein '×' (Pille, offen, angedockt), und ein "
               "Ruf schliesst nicht",
               m["verbunden"] == {"pille": False, "offen": False,
                                  "angedockt": False}
               and m["verbunden_ruf"] == (False, True),
               (m["verbunden"], m["verbunden_ruf"]))
        pruefe("L116 nach dem Trennen das '×' mit Tooltip und Name "
               "'Schliessen'", m["getrennt"] == (True, "Schliessen",
                                                  "Schliessen"), m["getrennt"])
        pruefe("L116 mit '×' passt der Kopf angedockt in %d px (%d)"
               % (m["kopf_min"][1], m["kopf_min"][0]),
               m["kopf_min"][0] <= m["kopf_min"][1], m["kopf_min"])
        pruefe("L116 nie verbunden: das '×' in Pille, offen und angedockt",
               m["nie"] and m.get("ohne_offen") and m.get("ohne_angedockt"),
               (m["nie"], m.get("ohne_offen"), m.get("ohne_angedockt")))
        zu = m["zu"]
        pruefe("L116 '×' schliesst ganz: kein Fenster zu sehen, Takt, "
               "Steckplatz-Thread und Arbeitsanzeige aus",
               zu["sichtbar"] == [] and not zu["alt_sichtbar"]
               and not zu["fenster"] and not zu["takt"]
               and not zu["anzeige"] and not zu["monitor"], zu)
        w = m["wieder"]
        pruefe("L116 der naechste Plugin-Klick: Pille zurueck, Takt und "
               "Thread laufen, verbunden wird wie immer",
               w["sichtbar"] == ["OpenMcpCadFenster"] and w["pille"]
               and w["takt"] and w["monitor"] and w["verbinden"] == [1]
               and m["alt_lebt"], (w, m["alt_lebt"]))
        pruefe("L116 danach verbunden: das '×' ist wieder weg",
               w["x"] is True and w["x_verbunden"] is False, w)
        # KONTROLLEN
        k = _schliessen_lauf(lambda: _mutant(_anweisungen(
            "_schliessen_zeigen", _beginnt("zu.setVisible("),
            "zu.setVisible(True)")))
        pruefe("L116 KONTROLLE: steht das '×' immer da, wird 'verbunden kein "
               "×' rot", k["treffer"] == [1]
               and any(k["verbunden"].values()), k["verbunden"])
        k = _schliessen_lauf(lambda: _mutant(_anweisungen(
            "_fenster_schliessen", lambda s: isinstance(s, ast.If)
            and "_verbunden_ist" in ast.unparse(s.test))))
        pruefe("L116 KONTROLLE: ohne die Sperre schliesst ein Ruf auch "
               "verbunden", k["treffer"] == [1]
               and k["verbunden_ruf"][0] is True, k["verbunden_ruf"])
        k = _schliessen_lauf(lambda: _mutant(_anweisungen(
            "_fenster_schliessen", _beginnt("_dock_abbauen(z)"),
            "z['fenster'].hide()")))
        pruefe("L116 KONTROLLE: nur verstecken (ohne Abbau) laesst den Takt "
               "laufen", k["treffer"] == [1] and k["zu"]["takt"], k["zu"])
        def weit():
            M = _mutant()
            M.KOPF_ABSTAND_ENG = M.KOPF_ABSTAND
            return M
        k = _schliessen_lauf(weit)
        pruefe("L116 KONTROLLE: ohne engeren Abstand ist der Kopf mit '×' zu "
               "breit fuer die Spalte", k["kopf_min"][0] > k["kopf_min"][1],
               k["kopf_min"])
        k = _schliessen_lauf(lambda: _mutant(_anweisungen(
            "_fenster_schliessen", _beginnt("z['monitor_an'] = False"))))
        pruefe("L116 KONTROLLE: ohne Halt laeuft der Steckplatz-Thread "
               "weiter", k["treffer"] == [1] and k["zu"]["monitor"], k["zu"])
        k = _schliessen_lauf(lambda: _mutant(_anweisungen(
            "_monitor_starten", lambda s: isinstance(s, ast.If)
            and "is_alive" in ast.unparse(s.test),
            "if alt is not None and alt.is_alive():\n    return")))
        pruefe("L116 KONTROLLE: der alte Thread-Start (nur 'lebt er?') "
               "startet kurz nach dem Schliessen keinen neuen",
               k["treffer"] == [1] and k["alt_lebt"]
               and not k["wieder"]["monitor"], (k["wieder"], k["alt_lebt"]))
    finally:
        _frischer_start()


def main():
    # Die Konsole ist cp1252: ein "⚙" im Detail einer ROTEN Zelle brach das
    # Gate sonst mit UnicodeEncodeError ab (Etappe D, L64).
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        import PyQt6                                   # noqa: F401
    except ImportError:
        print("PyQt6 fehlt — die Live-Pruefungen laufen NICHT.")
        print("Einrichten: siehe Kopf dieser Datei.")
        print("(Das ist kein bestandener Test. Es ist gar keiner.)")
        return 2
    if "--k12-kind" in sys.argv:
        # L96: der Kind-Prozess mit zwei Bildschirmen.
        return _k12_kind()
    if "--deckend-kind" in sys.argv:
        # L115: der Kind-Prozess mit nativer Mitte.
        return _deckend_kind()

    print("A-Dashboard — LIVE, offscreen\n")
    # Vor ALLEM anderen: winget, ollama und lms starten in diesem Gate nie
    # (L54 prueft am Ende, dass der Draht nichts gefangen hat).
    _draht_legen()
    D, _z, _d = aufbauen()
    H = D._hinweis_modul()

    zelle_auswahl()
    zelle_aktivieren()
    zelle_abhaken()
    zelle_gruppen(H)
    zelle_kontext(H)
    zelle_vollbild()
    zelle_karten_hoehe()
    zelle_klick_verbindet()
    zelle_kein_doppelstart()
    zelle_wunsch_belegt()
    zelle_alle_belegt()
    zelle_fehler_im_verbinden()
    zelle_karten_nur_verbundene()
    zelle_dropdown_alle_ports()
    zelle_wunsch_jenseits_f()
    zelle_steuerung_ueber_port()
    zelle_chat_anbieter()
    zelle_mini()
    zelle_fehler_bleibt()
    zelle_chat_lage_verbinden()
    zelle_dock_geloescht()
    zelle_form_neubau()
    zelle_schnittstelle()
    zelle_takt_fehler()
    zelle_quittieren()
    zelle_auffrischen_meldet()
    zelle_ersatz_nach_zug()
    zelle_form_teile()
    zelle_wrapper_verlust()
    zelle_wrapper_messung()
    zelle_echter_kern_zweiter_klick()
    zelle_klick_im_start()
    zelle_qt_sonden()
    zelle_modal_haelt_zurueck()
    zelle_paketlauf_paketweise()
    zelle_wahl_gemerkt()
    zelle_modus_gemerkt()
    zelle_kaputte_einstellungen()
    zelle_abo_ohne_betrag()
    zelle_stufe_allein()
    zelle_modus_nach_neubau()
    zelle_anbieter_tief()
    zelle_schluessel_start()
    zelle_nur_claude_merkt()
    zelle_modus_tooltip()
    zelle_zeichenmodus_gemerkt()
    zelle_ordnerwahl()
    zelle_takt_ohne_ordner()
    zelle_einstellungen()
    zelle_schluessel()
    zelle_lokal()
    zelle_adresse_vorgegeben()
    zelle_schluessel_feinheiten()
    zelle_seite_nacharbeit()
    zelle_eingabe_bleibt_unten()
    zelle_breite_300()
    zelle_erste_nachricht()
    zelle_nacharbeit_c()
    zelle_chatliste()
    zelle_chatliste_nacharbeit()
    zelle_kontextanzeige()
    zelle_ordnerwahl_dock()
    zelle_modellslots_sicher()
    zelle_karte_sitzung()
    zelle_chatfenster()
    zelle_leiste()
    zelle_anhaenge()
    zelle_lesbarer_chat()
    zelle_feinschliff()
    zelle_totes_cli()
    zelle_gegenpruefung_0928()
    zelle_sperre_hinweis()
    zelle_symbole()
    zelle_auf_dem_schirm()
    zelle_erster_kontakt()
    zelle_ein_fenster()
    zelle_kopf()
    zelle_ort_pille()
    zelle_uebergaenge()
    zelle_angedockt()
    zelle_segmente()
    zelle_anker()
    zelle_update_k11()
    zelle_popover()
    zelle_arbeitsanzeige()
    zelle_kopfknoepfe()
    zelle_fenster_geloescht()
    zelle_eigenes_menue()
    zelle_hinweis_in_chat()
    zelle_gestalt()
    zelle_aussehen()
    zelle_briefkasten_ablage()
    zelle_auftraege_protokoll()
    zelle_rueckfrage_sichtbar()
    zelle_k11_slots_sicher()
    zelle_zahl_einmal()
    zelle_knopf_texte()
    zelle_fachwoerter()
    zelle_hinweis_platz()
    zelle_freigabe_sicht()
    zelle_angedockt_deckend()
    zelle_schliessen()
    zelle_ports_ausserhalb()
    zelle_stolperdraht()

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    if all(_ergebnisse):
        print("Das Board verhaelt sich, wie es soll — echt gebaut, echt "
              "bedient.")
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
