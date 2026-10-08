#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bilder des Fensters (Pille, Chat), offscreen gerendert — fuer die
Schnellstart-Anleitung (verteilung/bilder/) und spaeter fuer die Website.

    <omcadqt-python> scripts/bilder_rendern.py [ZIELORDNER] [--persoenlich PFAD]
                                               [--privat PFAD]
                                               [--ueberblick ORDNER]

Braucht PyQt6 (die venv aus CLAUDE.md, `%LOCALAPPDATA%\\Temp\\omcadqt`).
Vorgabe fuer ZIELORDNER: verteilung/bilder.

WIE: das Dock wird ueber `tests/test_a_live.py` gebaut (dieselben
Attrappen wie im Gate: kein Cadwork, kein Netz, chat.json und Registry in
Temp), mit Demo-Inhalt «Seeblick». Gezeichnet in doppelter Aufloesung
(wie auf einem 200-%-Bildschirm), Schrift Segoe UI 9 pt wie in Cadwork.

Bilder:
    monitor.png      die Pille (K12: das, was der Klick zeigt), verbunden,
                     «Bereit»
    chat.png         das Fenster offen beim Chat, mit dem Testsatz der
                     Anleitung
    willkommen.png   der erste Kontakt: «Womit möchtest du chatten?»
                     (nur, wenn das Dashboard die Karte kennt)

Mit `--ueberblick ORDNER` zusaetzlich (K12, fuer die Sichtung und die
Website, NICHT in die Anleitung) an den echten Orten ueber einem
Cadwork-Ersatz (Hauptfenster mit Menue, Werkzeugleiste, dunkler Flaeche und
einem eigenen Dock rechts) — die Bilder 01-13 der Spezifikation 7.3: Pille,
offen mit Chat, angedockt (Chat, Briefkasten, Hinweise, Einstellungen), der
Popover (Hoch, Ultracode, Modellliste, Codex) und die Arbeitsanzeige
(zeichnet, denkt nach, Freigabe, Cadwork rechnet).

KEINE ECHTEN NAMEN: bevor ein Bild gespeichert wird, werden alle
sichtbaren Texte seines Fensters gegen dieselben Pruefungen gehalten wie
das Verteilpaket (Benutzerpfad, persoenlich.txt, privat_spuren.txt). Trifft eine, bricht das Skript ab und speichert nichts.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import types

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, HIER)

import paket_bauen as P                                     # noqa: E402

#: Der Testsatz der Anleitung (SCHNELLSTART.md, Abschnitt 5) — gelesen,
#: nicht abgeschrieben.
def testsatz():
    with open(os.path.join(P.VERTEILUNG, "SCHNELLSTART.md"),
              encoding="utf-8") as fh:
        for zeile in fh:
            if zeile.startswith("> Zeichne"):
                return zeile[1:].strip()
    raise SystemExit("Testsatz nicht in SCHNELLSTART.md gefunden")


def _schirm():
    """Ein Bildschirm 1920x1080 mit Pixeldichte 2 fuer Qt offscreen.
    -> (Plattform-Angabe, Ordner). Der Pfad muss RELATIV sein: der
    Doppelpunkt in "C:" trennt dort Optionen (gemessen: Absturz 0xC0000409
    beim Bau der QApplication). Deshalb wechselt `main` in den Ordner."""
    t = tempfile.mkdtemp(prefix="omcad_bilder_")
    with open(os.path.join(t, "schirm.json"), "w") as fh:
        json.dump({"screens": [{"name": "s1", "x": 0, "y": 0, "width": 1920,
                                "height": 1080, "logicalDpi": 96,
                                "logicalBaseDpi": 96, "dpr": 2}]}, fh)
    return "offscreen:configfile=schirm.json", t


def _gate_laden():
    spec = importlib.util.spec_from_file_location(
        "tl_bilder", os.path.join(REPO, "tests", "test_a_live.py"))
    T = importlib.util.module_from_spec(spec)
    sys.modules["tl_bilder"] = T
    spec.loader.exec_module(T)
    return T


def sichtbare_texte(wurzel):
    """Was ein Betrachter des Bildes lesen kann (ohne Tooltips)."""
    from PyQt6.QtWidgets import QWidget
    texte = []
    for wd in [wurzel] + wurzel.findChildren(QWidget):
        if not wd.isVisibleTo(wurzel) and wd is not wurzel:
            continue
        for art in ("text", "placeholderText", "toPlainText", "currentText",
                    "windowTitle", "title"):
            f = getattr(wd, art, None)
            if callable(f):
                try:
                    wert = f()
                except TypeError:
                    continue
                if isinstance(wert, str) and wert:
                    texte.append(wert)
    return texte


def texte_pruefen(texte, name):
    """Bricht ab, wenn ein sichtbarer Text etwas Persoenliches traegt.
    `--persoenlich PFAD` / `--privat PFAD`: eine andere persoenlich.txt
    bzw. privat_spuren.txt (etwa die des Haupt-Checkouts, wenn das Skript
    in einem Worktree laeuft)."""
    datei = privat = None
    if "--persoenlich" in sys.argv:
        datei = sys.argv[sys.argv.index("--persoenlich") + 1]
    if "--privat" in sys.argv:
        privat = sys.argv[sys.argv.index("--privat") + 1]
    muster = P.persoenliche_muster(datei)
    spuren = P.private_muster(privat) if privat else P.private_spuren_liste()
    funde = [t for t in texte if P.HART.search(t)
             or any(m.search(t) for m in muster)
             or any(m.search(t) for m in spuren)]
    if funde:
        raise SystemExit("ABBRUCH %s: sichtbarer Text mit Persoenlichem: %r"
                         % (name, funde[:3]))
    return len(muster)


def ueberblick_rendern(T, Dienst, ziel, pumpen, satz):
    """Die Bilder fuer `--ueberblick` (K12, Spezifikation 7.3): das EINE
    Fenster als Pille, offen und rechts angedockt (neben einem eigenen Dock
    von Cadwork), Briefkasten, Hinweise, Einstellungen, der Popover fuer
    Modell und Denkstufe samt Modellliste, die Arbeitsanzeige — an ihren
    ECHTEN Orten ueber einem Cadwork-Ersatz: gerendert wird das
    Hauptfenster, die schwebenden Fenster (und Popups) darueber an ihrem
    Abstand zu ihm. -> Zahl der Muster aus persoenlich.txt."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtWidgets import QDockWidget, QLabel, QVBoxLayout, QWidget
    T._frischer_start()
    haupt = T._cadwork_ersatz(ort=(0, 0), groesse=(1440, 860))
    haupt.centralWidget().setText("")
    # Ein eigenes Dock von Cadwork rechts (wie dessen Eigenschaften).
    fremd = QDockWidget("Eigenschaften", haupt)
    fremd.setObjectName("CadworkEigenschaften")
    innen = QWidget()
    lay = QVBoxLayout(innen)
    for text in ("Name", "Material", "Gruppe", "Untergruppe", "Kommentar",
                 "Breite", "Höhe", "Länge"):
        lb = QLabel(text)
        lb.setStyleSheet("color: #3b4450; padding: 3px;")
        lay.addWidget(lb)
    lay.addStretch(1)
    innen.setMinimumWidth(170)
    fremd.setWidget(innen)
    haupt.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, fremd)
    pumpen()
    client, kern = T._Client([]), T._VerbindKern(1, 0)
    D, z, _r = T._klick(client, kern, verbinden=False)
    # Die Verbindungskarten wie im Betrieb: `_klick` legt eine leere
    # Attrappe auf `_verbindungen_zeichnen` (Gates ohne Netz) — fuer die
    # Bilder die echte Funktion, gefuettert mit EINEM verbundenen
    # Steckplatz (sonst stand "Wird abgefragt …", Gegenpruefung K12).
    echt_vz = T.dashboard_laden()._verbindungen_zeichnen
    D._verbindungen_zeichnen = types.FunctionType(
        echt_vz.__code__, D.__dict__, echt_vz.__name__)
    jetzt = time.time()
    d = Dienst()
    d.cfg = type("Cfg", (), {"instanz": "A", "port": 53127})()
    z["dienst"] = d
    z["instanz"] = "A"
    # Der Kern (Attrappe) traegt die Zeichenmodi — sonst stand beim
    # Zeichenmodus "Erst verbinden.", obwohl der Kopf "Trennen" zeigte.
    z["kern"] = kern
    z["monitor_daten"] = [{"port": 53127, "instanz": "A", "zustand": "ready",
                           "dokument": "Seeblick.3d", "version": "2.19.1",
                           "antwortzeit_ms": 4, "wartende_auftraege": 0}]
    with d.sperre:
        d.hinweise.extend([
            T.hinweis(1, "Wandhöhe von der Nachbarwand übernommen",
                      "Bitte gegen die Pläne von Seeblick prüfen.",
                      "warnung", 4, 300.0, [1001, 1002]),
            T.hinweis(2, "Fenstersturz geraten", "Kein Mass vorhanden.",
                      "frage", 2, 120.0, [2001])])
        d.postfach.extend([
            {"nr": 1, "text": "Die Nordwand bitte 2 cm dicker.",
             "zeit": jetzt - 900, "abgeholt": True},
            {"nr": 2, "text": "Beim Dach die Sparren auf 80 cm Abstand.",
             "zeit": jetzt - 60, "abgeholt": False}])
        d.verlauf[:] = [
            {"methode": "get_document_info", "ok": True, "dauer_s": 0.1,
             "beendet": jetzt - 400},
            {"methode": "execute_cwapi3d", "beschreibung": "Wand Nord",
             "ok": True, "dauer_s": 2.5, "paket": [1, 8],
             "beendet": jetzt - 90},
            {"methode": "execute_cwapi3d", "beschreibung": "Wand Nord",
             "ok": True, "dauer_s": 2.3, "paket": [2, 8],
             "beendet": jetzt - 40}]
    for _ in range(4):
        D._auffrischen(z)
        pumpen()
    muster = [0]
    w, f = z["w"], z["fenster"]

    def bild(name, schwebend=()):
        texte = sichtbare_texte(haupt)
        for teil in schwebend:
            texte += sichtbare_texte(teil)
        muster[0] = texte_pruefen(texte, name)
        oben_links = haupt.mapToGlobal(QPoint(0, 0))
        pm = QPixmap(haupt.width() * 2, haupt.height() * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.white)
        haupt.render(pm)
        maler = QPainter(pm)
        for teil in schwebend:
            g = teil.frameGeometry()
            p = QPoint(g.left() - oben_links.x(), g.top() - oben_links.y())
            teil.render(maler, p)
        maler.end()
        pfad = os.path.join(ziel, name)
        pm.save(pfad)
        print("%s  %dx%d" % (pfad, pm.width(), pm.height()))

    def takt(n=4):
        for _ in range(n):
            D._auffrischen(z)
            D._chat_zeichnen(z)
            pumpen()

    def pille_pruefen(name, soll):
        # Jedes Bild zeigt EINEN Zustand: die Pille im Kopf muss zu dem
        # passen, was das Bild sonst zeigt (Gegenpruefung K12: "KI
        # zeichnet" neben "Bereit"). Sonst Abbruch.
        ist = w["pille"].text()
        if ist != "● " + soll:
            raise SystemExit("ABBRUCH: %s — die Pille sagt %r statt %r"
                             % (name, ist, soll))

    def schwebt():
        return [f] if f.isFloating() and f.isVisible() else []

    # 01 die Pille: oben rechts, "Bereit", zwei offene Hinweise.
    if not (f.isVisible() and f.isFloating() and w["koerper"].isHidden()):
        raise SystemExit("ABBRUCH: der Klick zeigt keine Pille")
    bild("01_pille.png", schwebt())

    # 02 offen, mit kurzem Gespraech (zwei Blasen, eine Schrittgruppe).
    cad = "mcp__open-mcp-cad__execute_cadwork_command"
    info = "mcp__open-mcp-cad__get_document_info"
    t0 = jetzt - 70
    chat = z["chat"]
    chat.update(an=True, laeuft_zug=False, anbieter="claude",
                kurzname="Claude", modell="claude-opus-5-5",
                werkzeuge_da=True, wissen=True, modus="fragen", freigaben=[],
                kontext={"belegt": 21000, "fenster": 200000},
                stand=chat.get("stand", 0) + 1, ereignisse=[
                    {"art": "ich", "text": satz, "zeit": t0},
                    {"art": "werkzeug", "werkzeug": info, "eingabe": {},
                     "id": "a", "zeit": t0 + 4},
                    {"art": "auto", "werkzeug": info, "eingabe": {},
                     "zeit": t0 + 4},
                    {"art": "ergebnis", "id": "a", "fehler": False,
                     "zeit": t0 + 5},
                    {"art": "werkzeug", "werkzeug": cad, "id": "b",
                     "eingabe": {"code": "x", "description": "Wand"},
                     "zeit": t0 + 9},
                    {"art": "ergebnis", "id": "b", "fehler": False,
                     "zeit": t0 + 12},
                    {"art": "text", "text": "Die Wand steht in Seeblick.3d: "
                     "4,00 m lang und 2,50 m hoch. Soll ich die Dicke "
                     "ändern?", "zeit": t0 + 14},
                    {"art": "schluss", "kosten": None, "token": 0,
                     "abgelehnt": 0, "fehler": False, "text": "",
                     "zeit": t0 + 14}])
    D._fenster_aktion(z, "chat")
    pumpen(10)
    takt()
    chat["an"] = False
    takt(2)
    chat["an"] = True
    takt(2)
    bild("02_pille_chat.png", schwebt())

    # 03 rechts angedockt, Chat, neben Cadworks Dock — das Gedaechtnis des
    # Chats zu 65 % voll: der Fuellstand steht (erst ab 50 %).
    chat["kontext"] = {"belegt": 130000, "fenster": 200000}
    D._fenster_aktion(z, "andocken")
    pumpen(10)
    takt()
    if f.isFloating():
        raise SystemExit("ABBRUCH: das Fenster ist nicht angedockt")
    if not w["chat_kontext"].isVisible():
        raise SystemExit("ABBRUCH: 03 — kein Fuellstand bei 65 %")
    bild("03_angedockt_chat.png")
    chat["kontext"] = {"belegt": 21000, "fenster": 200000}

    # 04 Briefkasten: "Läuft jetzt", Letzte Aufträge, Notizen.
    echt_status = d.status
    d.status = lambda: dict(echt_status(), auftrag={
        "methode": "execute_cwapi3d", "paket": [3, 8],
        "beschreibung": "Wand Nord", "laufzeit_s": 4.2,
        "zugriff": "write"})
    d.zustand = "busy_write"
    D._segment_waehlen(z, "briefkasten")
    takt()
    pille_pruefen("04", "Zeichnet")
    bild("04_angedockt_briefkasten.png")
    d.status = echt_status
    d.zustand = "ready"

    # 05 Chat, Hinweise offen.
    D._segment_waehlen(z, "chat")
    D._hinweise_zeigen(z, True)
    # Ein Hinweis gewaehlt: "In den Chat übernehmen" ist bereit.
    w["hinweise"]["gewaehlt_nr"] = 1
    takt()
    pille_pruefen("05", "Bereit")
    bild("05_hinweise_offen.png")
    w["hinweise"]["gewaehlt_nr"] = None
    D._hinweise_zeigen(z, False)

    # 06 die Einstellungsseite ueber "⋯".
    chat["an"] = False
    takt(2)
    D._einstellungen_zeigen(z, True)
    takt()
    if w["verb_kopf"].text().startswith("Wird abgefragt")             or w["modus_text"].text().startswith("Erst verbinden"):
        raise SystemExit("ABBRUCH: 06 — Einstellungen ohne Stand: %r / %r"
                         % (w["verb_kopf"].text(), w["modus_text"].text()))
    bild("06_einstellungen.png")
    D._einstellungen_zeigen(z, False)

    # 07/07b/08/09 der Popover (Claude Code: Opus 5.5, Hoch / Ultracode),
    # die Modellliste darueber, Codex ohne Regler.
    D._anbieter_setzen(z, "claude")
    feld = w["chat_modell"]
    i = feld.findData("opus")
    if i >= 0:
        feld.setCurrentIndex(i)
    stufe = w["chat_stufe"]
    stufe.setCurrentIndex(stufe.findData("high"))
    takt(2)
    pop = w["chat_modell_auf"]
    D._modell_aufklappen(z)
    pumpen()
    bild("07_popover.png", [pop])
    stufe.setCurrentIndex(stufe.findData("ultracode"))
    D._popover_fuellen(z)
    pumpen()
    bild("07b_popover_ultracode.png", [pop])
    stufe.setCurrentIndex(stufe.findData("high"))
    D._popover_fuellen(z)
    D._modell_liste_zeigen(z)
    pumpen()
    liste = w["modell_liste_auf"]
    bild("08_modellliste.png", [pop, liste])
    liste.hide()
    pop.hide()
    D._anbieter_setzen(z, "codex")
    takt(2)
    D._modell_aufklappen(z)
    pumpen()
    bild("09_popover_codex.png", [pop])
    pop.hide()
    D._anbieter_setzen(z, "claude")
    takt(2)

    # 10-13 die Arbeitsanzeige (Zustaende gesetzt wie vom Haken des Kerns).
    anz = z["anzeige"]
    lauf_info = {"zugriff": "write", "beschreibung": "Wand Nord",
                 "paket": [3, 8], "lauf_gezeichnet": 12, "lauf_gesamt": 30,
                 "prozent": 40, "restzeit_s": 20.0, "popup": True,
                 "client": "Codex"}
    z["anzeige_lauf"] = {"aktiv": True, "popup": True, "start_t":
                         time.monotonic() - 8, "info": dict(lauf_info),
                         "auftrag": dict(lauf_info,
                                         t0=time.monotonic() - 4),
                         "fertig": None, "fertig_t": None,
                         "angehalten": False, "weg": False}
    def anzeige(name, titel, pille, st=None):
        # Ein ganzer Takt (Pille, Chat) und die Anzeige; geprueft werden
        # Titel UND Pille NACH dem Pumpen — beide muessen dasselbe sagen.
        takt(2)
        D._anzeige_zeichnen(z, st=st)
        pumpen()
        jetzt_titel = z["w"]["anzeige_titel"].text()
        if not anz.isVisible() or jetzt_titel != titel:
            raise SystemExit("ABBRUCH: %s zeigt %r statt %r"
                             % (name, jetzt_titel, titel))
        pille_pruefen(name, pille)
        bild(name, [anz])

    d.zustand = "busy_write"
    anzeige("10_anzeige_zeichnet.png", D.ANZEIGE_ZEICHNET, "Zeichnet")
    d.zustand = "ready"
    z["anzeige_lauf"]["auftrag"] = None
    chat.update(an=True, laeuft_zug=True, freigaben=[], ereignisse=[
        {"art": "werkzeug", "werkzeug": cad, "id": "c",
         "eingabe": {"code": "x", "description": "Wand Nord"},
         "zeit": time.time() - 3}], stand=chat.get("stand", 0) + 1)
    anzeige("11_anzeige_denkt.png", D.ANZEIGE_DENKT, "Denkt nach")
    # Die ECHTE Freigabe-Karte im Chat (Gegenpruefung Laien-Sicht K12: das
    # Bild sagte "Wartet auf deine Freigabe", im Chat stand keine Karte —
    # ohne neuen `stand` zeichnete der Takt den Chat nicht neu).
    chat["freigaben"] = [{"id": "f1", "offen": True, "werkzeug": cad,
                          "name": "execute_cadwork_command",
                          "eingabe": {"code": "x",
                                      "description": "Wand Süd"}}]
    chat["stand"] = chat.get("stand", 0) + 1
    takt(2)
    pumpen()
    karte = D._erste_freigabe(z)
    if karte is None or not D._freigabe_in_sicht(z):
        raise SystemExit("ABBRUCH: 12 — keine Freigabe-Karte mit Erlauben/"
                         "Ablehnen im Chat zu sehen")
    anzeige("12_anzeige_freigabe.png", D.ANZEIGE_FREIGABE, "Wartet auf dich")
    chat["freigaben"] = []
    chat["stand"] = chat.get("stand", 0) + 1
    echt_status = d.status
    d.status = lambda: dict(echt_status(), cadwork_beschaeftigt="Viewer-Modus")
    anzeige("13_anzeige_cadwork.png", D.ANZEIGE_CADWORK[0],
            "Cadwork rechnet")
    d.status = echt_status
    chat["an"] = False
    anz.hide()
    haupt.hide()
    T._frischer_start()
    return muster[0]


def main():
    frei = [a for i, a in enumerate(sys.argv[1:], 1)
            if not a.startswith("--")
            and sys.argv[i - 1] not in ("--persoenlich", "--privat", "--ueberblick")]
    ueberblick = None
    if "--ueberblick" in sys.argv:
        ueberblick = os.path.abspath(
            sys.argv[sys.argv.index("--ueberblick") + 1])
        os.makedirs(ueberblick, exist_ok=True)
    ziel = os.path.abspath(frei[0] if frei else P.BILDER)
    os.makedirs(ziel, exist_ok=True)
    plattform, schirm_ordner = _schirm()
    os.environ["QT_QPA_PLATFORM"] = plattform
    T = _gate_laden()
    # test_a_live setzt beim Laden "offscreen" — wieder unseren Bildschirm.
    os.environ["QT_QPA_PLATFORM"] = plattform
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QPixmap
    from PyQt6.QtWidgets import QApplication
    T._draht_legen()
    vorher = os.getcwd()
    os.chdir(schirm_ordner)
    app = QApplication.instance() or QApplication([])
    os.chdir(vorher)
    print("Bildschirm", app.primaryScreen().geometry().getRect(),
          app.primaryScreen().devicePixelRatio())
    T._APP = app
    app.setFont(QFont("Segoe UI", 9))
    anzahl_muster = None

    def pumpen(n=6):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.02)

    def speichern(widget, name):
        nonlocal anzahl_muster
        anzahl_muster = texte_pruefen(sichtbare_texte(widget), name)
        pm = QPixmap(widget.width() * 2, widget.height() * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.transparent)
        widget.render(pm)
        pfad = os.path.join(ziel, name)
        pm.save(pfad)
        print("%s  %dx%d" % (pfad, pm.width(), pm.height()))

    # Demo-Arbeitsordner «Seeblick» in Temp: der Knopf zeigt nur den Namen.
    demo = os.path.join(tempfile.mkdtemp(prefix="omcad_demo_"), "Seeblick")
    os.makedirs(demo)
    T._einst_setzen(json.dumps({"arbeitsordner": demo,
                                "ordner_zuletzt": [demo]}))

    class Dienst(T.Dienst):
        def status(self):
            s = T.Dienst.status(self)
            s.update(dokument="Seeblick.3d", dokument_elemente=0,
                     aktive_elemente=0)
            return s

    T._frischer_start()
    D = T.dashboard_laden()
    D, z, _d = T.aufbauen(D=D)
    d = Dienst()
    z["dienst"] = d
    jetzt = time.time()
    satz = testsatz()
    D._auffrischen(z)
    pumpen()

    # 1. Die Pille (K12: das, was der Klick zeigt): verbunden, «Bereit»
    pille = z["fenster"]
    D._auffrischen(z)
    pumpen()
    speichern(pille, "monitor.png")

    # 2. Chatfenster: der Testsatz, ein Blick ins Dokument, die Wand
    cad = "mcp__open-mcp-cad__execute_cadwork_command"
    info = "mcp__open-mcp-cad__get_document_info"
    t0 = jetzt - 70
    chat = z["chat"]
    chat.update(an=True, laeuft_zug=False, anbieter="claude",
                kurzname="Claude", modell="claude-sonnet-5",
                werkzeuge_da=True, wissen=True, modus="fragen", freigaben=[],
                kontext={"belegt": 21000, "fenster": 200000},
                stand=chat.get("stand", 0) + 1, ereignisse=[
                    {"art": "ich", "text": satz, "zeit": t0},
                    {"art": "text", "text": "Ich schaue zuerst ins "
                     "Dokument.", "zeit": t0 + 3},
                    {"art": "werkzeug", "werkzeug": info, "eingabe": {},
                     "id": "a", "zeit": t0 + 4},
                    {"art": "auto", "werkzeug": info, "eingabe": {},
                     "zeit": t0 + 4},
                    {"art": "ergebnis", "id": "a", "fehler": False,
                     "zeit": t0 + 5},
                    {"art": "werkzeug", "werkzeug": cad, "id": "b",
                     "eingabe": {"code": "x", "description": "Wand"},
                     "zeit": t0 + 9},
                    {"art": "ergebnis", "id": "b", "fehler": False,
                     "zeit": t0 + 12},
                    {"art": "text", "text": "Die Wand steht in Seeblick.3d: "
                     "4,00 m lang und 2,50 m hoch, am Nullpunkt entlang der "
                     "x-Achse. Soll ich die Dicke oder die Lage ändern?",
                     "zeit": t0 + 14},
                    {"art": "schluss", "kosten": None, "token": 0,
                     "abgelehnt": 0, "fehler": False, "text": "",
                     "zeit": t0 + 14}])
    D._modus_zeigen(z)
    # Das Fenster offen beim Chat, so gross wie bisher das Chatfenster.
    z["offen_groesse"] = (460, 540)
    D._chat_oeffnen(z)
    f = z["fenster"]
    pumpen(10)
    for _ in range(5):
        D._auffrischen(z)
        D._chat_zeichnen(z)
        pumpen()
    speichern(f, "chat.png")

    # 3. Erster Kontakt (Stufe 4): nichts eingerichtet
    if hasattr(D, "_einstieg_setzen"):
        chat.update(an=False, ereignisse=[], stand=chat.get("stand", 0) + 1)
        D._einstieg_setzen(z, {"claude": False, "codex": False,
                               "schluessel": False, "lokal": False})
        z["offen_groesse"] = (460, 740)
        D._fenster_lage(z)
        pumpen(10)
        for _ in range(5):
            D._auffrischen(z)
            D._chat_zeichnen(z)
            pumpen()
        speichern(f, "willkommen.png")
    if ueberblick:
        anzahl_muster = ueberblick_rendern(T, Dienst, ueberblick, pumpen,
                                           satz) or anzahl_muster
    print("geprueft gegen %s Muster aus persoenlich.txt%s" % (
        anzahl_muster, "" if anzahl_muster else
        " (keine Datei — nur Benutzerpfade und Spuren geprueft)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
