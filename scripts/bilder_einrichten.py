#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bebilderte Anleitung «So richtest du es ein»: die zweite Reihe neben
`bilder_anleitung_web.py` (Bedienung), im selben Stil — nummerierte Kreise
mit feinen Pfeilen, KEINE Saetze im Bild ausser denen, die der Nutzer
wirklich so sieht (Einrichtungsfenster und Dock sind nur deutsch), damit
ein Bild fuer alle Sprachen reicht. Die Erklaerungen zu den Nummern stehen
im Schnellstart (SCHNELLSTART(.xx).md, Abschnitt 6 «So richtest du es
ein») bzw. auf der Website.

    <omcadqt-python> scripts/bilder_einrichten.py ZIELORDNER
                     [--pdf ORDNER] [--persoenlich PFAD] [--privat PFAD]

Braucht PyQt6 (die venv aus CLAUDE.md, `%LOCALAPPDATA%\\Temp\\omcadqt`) und
Windows PowerShell 5.1 (WPF, fuer die Seiten des Einrichtungsfensters).

Die Bilder (Rueckmeldung 2026-10-09: Laien scheitern nicht an der
Bedienung, sondern an Installation, Wahl der KI und den Apps; seit dem
Einrichtungsfenster ohne das schwarze Fenster):

    einrichten-1-ki-app-holen  das Einrichtungsfenster, wenn noch keine
                               KI-App da ist (zwei Knoepfe zu den
                               offiziellen Seiten)
    einrichten-2-entpacken     der entpackte Ordner: oben nur der
                               Doppelklick, die Anleitung und
                               «Programmdateien» — Namen und Version aus
                               paket_bauen (`oben_soll`)
    einrichten-3a-wo           das Fenster: «Wo möchtest du mit der KI
                               arbeiten?» (seit 2026-10-09)
    einrichten-3-ki-app        das Fenster: «Deine KI-App»
    einrichten-4-installieren  das Fenster: «Bereit zum Installieren»
    einrichten-5-laeuft        das Fenster: die Schritte, mit der Unterzeile
                               «Zusatzteile werden geladen: numpy …»
    einrichten-5b-python       dasselbe beim Laden von Python (nur Website)
    einrichten-6-fertig        das Fenster: «Fertig eingerichtet»
                               Die Seiten 1, 3-6 rendert
                               verteilung/install_fenster.ps1 selbst
                               (`-Rendern`, RenderTargetBitmap, ohne Fenster
                               zu zeigen); die Lage der Teile fuer die Marken
                               und die sichtbaren Texte stehen in dessen
                               seiten.json. Hier kommt nur der Fensterrahmen
                               dazu.
    einrichten-7-apps          Schema fuer Claude Desktop und die ChatGPT-App:
                               App → Open MCP CAD → Cadwork «Bereit»;
                               «Browser / Handy» durchgestrichen. Nur Namen und
                               eigene Strich-Symbole, keine fremden Logos,
                               kein Nachbau fremder Oberflaechen.
    einrichten-8a-chat-ki      das Fenster: «Welche KI im Chat in Cadwork?»
    einrichten-8b-anmelden     das Fenster: «Bei Claude anmelden»
    einrichten-8-chat          Fuer Fortgeschrittene: die Karte «Womit
                               möchtest du chatten?» im Dock (offscreen wie
                               willkommen.png, dieselben Attrappen wie im
                               Gate; 620 px breit statt 420, unten nach
                               «Nochmal prüfen» abgeschnitten)

Ergebnis in ZIELORDNER: mcp-einrichten-1-ki-app-holen.webp … und je ein
-klein.webp (Vorschau 3:2); mit `--pdf verteilung/bilder` dazu
einrichten-1-ki-app-holen.png … fuer den Schnellstart.

KEINE ECHTEN NAMEN: jeder sichtbare Text jedes Bildes (auch die Texte der
gerenderten Fensterseiten) geht vor dem Speichern durch
`bilder_rendern.texte_pruefen` (Benutzerpfad, persoenlich.txt,
privat_spuren.txt); trifft eine, wird nichts gespeichert.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, HIER)

import bilder_anleitung_web as W                            # noqa: E402
import bilder_rendern as B                                  # noqa: E402
import paket_bauen as P                                     # noqa: E402

FENSTER_PS1 = os.path.join(P.VERTEILUNG, P.FENSTER)
#: Kein Fenster, keine Konsole fuer den Kindprozess.
OHNE_FENSTER = 0x08000000


def fenster_seiten(ordner):
    """Rendert alle Seiten des Einrichtungsfensters ohne Fenster
    (install_fenster.ps1 -Rendern). -> seiten.json als dict, mit dem
    vollen Pfad je PNG unter "pfad"."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-STA", "-ExecutionPolicy", "Bypass", "-File",
                        FENSTER_PS1, "-Rendern", ordner],
                       capture_output=True, timeout=300,
                       creationflags=OHNE_FENSTER)
    try:
        with open(os.path.join(ordner, "seiten.json"),
                  encoding="utf-8") as fh:
            seiten = json.load(fh)
    except (OSError, ValueError):
        seiten = None
    if r.returncode != 0 or not seiten:
        raise SystemExit("ABBRUCH: install_fenster.ps1 -Rendern rc %d: %s"
                         % (r.returncode, (r.stdout + r.stderr).decode(
                             "utf-8", "replace")[-600:]))
    for info in seiten.values():
        info["pfad"] = os.path.join(ordner, info["datei"])
    return seiten


# --- Qt: Szenen bauen, rendern, beschriften -----------------------------------

#: Grund hinter den gezeichneten Szenen (wie ein heller Desktop).
GRUND = "#e9edf2"
#: Szene -> (Ausgabe ohne Endung, Rand links/oben/rechts/unten in logischen
#: px um das gerenderte Fenster, Marken wie in bilder_anleitung_web: (Nummer,
#: Ziel, Anker, dx, dy); Ziel ist ein Name aus dem Woerterbuch der Szene).
SZENEN = {
    "ki_app_holen": ("einrichten-1-ki-app-holen", (84, 24, 84, 24), [
        (1, "keine_claude", "links", -46, 0),
        (2, "keine_codex", "rechts", 46, 0),
        (3, "keine_chatgpt", "rechts", 60, 0),
        (4, "keine_nochmal", "rechts", 46, 0),
    ]),
    "entpacken": ("einrichten-2-entpacken", (24, 24, 24, 24), [
        (1, "zip", "unten", 0, 46),
        (2, "zeile_installieren", "rechts", 80, 0),
        (3, "zeile_anleitung", "rechts", 80, 0),
        (4, "zeile_ordner", "rechts", 80, 0),
    ]),
    "ki_app": ("einrichten-3-ki-app", (24, 24, 84, 24), [
        (1, "ki_karte_claude_desktop", "rechts", 46, 0),
        (2, "ki_karte_codex", "rechts", 46, 0),
        (3, "ki_chatgpt", "rechts", 46, 0),
        (4, "ki_weiter", "rechts", 46, 0),
    ]),
    "wo": ("einrichten-3a-wo", (24, 24, 84, 24), [
        (1, "wo_app", "rechts", 46, 0),
        (2, "wo_chat", "rechts", 46, 0),
        (3, "wo_beides", "rechts", 46, 0),
        (4, "wo_weiter", "rechts", 46, 0),
    ]),
    "installieren": ("einrichten-4-installieren", (24, 24, 84, 24), [
        (1, "bereit_liste", "rechts", 46, 0),
        (2, "bereit_installieren", "rechts", 46, 0),
    ]),
    "laeuft": ("einrichten-5-laeuft", (24, 24, 84, 24), [
        (1, "laeuft_leiste", "rechts", 46, 0),
        (2, "laeuft_unterzeile", "rechts", 46, 0),
        (3, "s3_text", "rechts", 60, 0),
        (4, "laeuft_details", "rechts", 60, 0),
    ]),
    # Nur fuer die Website (kein PNG fuer den Schnellstart).
    "python": ("einrichten-5b-python", (24, 24, 84, 24), [
        (1, "laeuft_unterzeile", "rechts", 46, 0),
    ]),
    "fertig": ("einrichten-6-fertig", (24, 24, 84, 24), [
        (1, "fertig_ki", "rechts", 46, 0),
        (2, "fertig_schritte", "rechts", 46, 0),
        (3, "fertig_anleitung", "oben", 0, -40),
        (4, "fertig_schliessen", "rechts", 46, 0),
    ]),
    "chat_ki": ("einrichten-8a-chat-ki", (24, 24, 84, 24), [
        (1, "chat_claude", "rechts", 46, 0),
        (2, "chat_codex", "rechts", 46, 0),
        (3, "chat_spaeter", "rechts", 46, 0),
        (4, "chat_weiter", "rechts", 46, 0),
    ]),
    "anmelden": ("einrichten-8b-anmelden", (24, 24, 84, 24), [
        (1, "anmelden_karte", "rechts", 46, 0),
        (2, "anmelden_los", "rechts", 46, 0),
    ]),
    "apps": ("einrichten-7-apps", (20, 20, 20, 20), [
        (1, "installer_marke", "unten", 0, 46),
        (2, "neu_claude", "oben", 30, -36),
        (3, "pille", "unten", 0, 46),
        (4, "chat_claude", "links", -50, 0),
        (5, "chatgpt", "links", -50, 0),
    ]),
    "chat": ("einrichten-8-chat", (100, 20, 20, 20), [
        (1, "chat_willkommen_claude", "links", -66, 0),
        (2, "chat_willkommen_codex", "links", -66, 0),
        (3, "chat_willkommen_schluessel", "links", -66, 0),
        (4, "chat_willkommen_pruefen", "rechts", 50, 0),
    ]),
}
#: Welche Seite des Einrichtungsfensters zu welcher Szene gehoert.
FENSTER_SZENEN = {"ki_app_holen": "ki_keine", "wo": "wo", "ki_app": "ki",
                  "installieren": "bereit", "laeuft": "laeuft_pip",
                  "python": "laeuft_python", "fertig": "fertig",
                  "chat_ki": "chat_ki", "anmelden": "anmelden"}
#: Szenen nur fuer die Website (ohne PNG im Schnellstart).
NUR_WEBSITE = ("python",)
#: Vorschau 3:2 fuer die Kachelreihe der Website: Ausschnitt (x, y, b) in
#: logischen px des fertigen Bildes; die Hoehe ist b * 2 / 3. Ohne Eintrag:
#: oben, mittig, so breit wie moeglich.
VORSCHAU = {}


def _pumpen(app, n=6):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


def _symbol(D, name, farbe="#1d1d1f", groesse=18):
    S = D._symbol_modul()
    pm = S.pixmap(name, farbe, groesse) if S else None
    if pm is None:
        raise SystemExit("ABBRUCH: Symbol %s nicht zu zeichnen (QtSvg?)"
                         % name)
    return pm


def _label(text, stil=""):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel
    lb = QLabel(text)
    lb.setTextFormat(Qt.TextFormat.PlainText)
    if stil:
        lb.setStyleSheet(stil)
    return lb


def _bild_label(pm):
    from PyQt6.QtWidgets import QLabel
    lb = QLabel()
    lb.setPixmap(pm)
    lb.setFixedSize(pm.deviceIndependentSize().toSize())
    lb.setStyleSheet("background: transparent;")
    return lb


def _flaeche(name, stil):
    """Ein QWidget mit eigenem Hintergrund aus dem Stil `#name { … }`."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget
    wd = QWidget()
    wd.setObjectName(name)
    wd.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    wd.setStyleSheet("#%s { %s }" % (name, stil))
    return wd


def szene_entpacken(D):
    """Der entpackte Ordner, gezeichnet: links die ZIP-Datei, rechts ein
    neutrales Fenster mit dem, was oben im Paket liegt
    (`paket_bauen.oben_soll`, Ordner zuerst wie im Explorer).
    -> (Wurzel, Ziele)"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout
    paket = "Open-MCP-CAD-%s" % P.version()
    oben = P.oben_soll()
    namen = [n for n in oben if n == P.UNTERORDNER] + \
        [n for n in oben if n != P.UNTERORDNER]
    wurzel = _flaeche("wurzel", "background: %s;" % GRUND)
    wurzel.setStyleSheet(wurzel.styleSheet() + " QLabel { color: #1d1d1f; "
                         "font-size: 13px; background: transparent; }")
    lay = QHBoxLayout(wurzel)
    lay.setContentsMargins(20, 24, 24, 24)
    lay.setSpacing(18)
    zip_teil = _flaeche("zipteil", "background: transparent;")
    zl = QVBoxLayout(zip_teil)
    zl.setContentsMargins(6, 6, 6, 6)
    zl.setSpacing(4)
    zl.addWidget(_bild_label(_symbol(D, "archive", "#8a6d1f", 56)), 0,
                 Qt.AlignmentFlag.AlignHCenter)
    zl.addWidget(_label(paket + ".zip", "font-size: 12px;"), 0,
                 Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(zip_teil, 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(_bild_label(_symbol(D, "chevron-right", "#6e6e73", 40)), 0,
                  Qt.AlignmentFlag.AlignVCenter)
    fenster = _flaeche("fenster", "background: #ffffff; border: 1px solid "
                       "#c9ced6; border-radius: 8px;")
    fl = QVBoxLayout(fenster)
    fl.setContentsMargins(1, 1, 1, 10)
    fl.setSpacing(12)
    kopf = _flaeche("kopf", "background: #f3f4f6; border: none; "
                    "border-bottom: 1px solid #dfe2e7; "
                    "border-top-left-radius: 8px; "
                    "border-top-right-radius: 8px;")
    kl = QHBoxLayout(kopf)
    kl.setContentsMargins(12, 9, 12, 9)
    kl.setSpacing(8)
    kl.addWidget(_bild_label(_symbol(D, "folder", "#c99a2e", 18)))
    kl.addWidget(_label(paket, "font-weight: 600;"))
    kl.addStretch(1)
    fl.addWidget(kopf)
    ziele = {"zip": zip_teil}
    for name in namen:
        zeile = _flaeche("zeile_%d" % len(ziele), "background: transparent; "
                         "border: none;")
        rl = QHBoxLayout(zeile)
        rl.setContentsMargins(12, 6, 16, 6)
        rl.setSpacing(10)
        if name == P.UNTERORDNER:
            art, farbe, schluessel = "folder", "#c99a2e", "zeile_ordner"
        elif name == P.INSTALLIEREN:
            art, farbe = "terminal", "#1d1d1f"
            schluessel = "zeile_installieren"
        else:
            art, farbe = "file-text", "#c0392b"
            schluessel = ("zeile_anleitung" if name.startswith(
                P.ANLEITUNG_OBEN[0][1]) else "zeile_" + name)
        rl.addWidget(_bild_label(_symbol(D, art, farbe, 20)))
        rl.addWidget(_label(name))
        rl.addStretch(1)
        fl.addWidget(zeile)
        ziele[schluessel] = zeile
    fl.addStretch(1)
    fenster.setFixedWidth(360)
    lay.addWidget(fenster, 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addSpacing(110)                    # Platz fuer die Marken rechts
    return wurzel, ziele


def szene_fenster(D, info):
    """Eine Seite des Einrichtungsfensters (PNG aus install_fenster.ps1,
    doppelte Aufloesung) in einem schlichten Fensterrahmen mit dem Titel des
    Fensters. Fuer jedes benannte Teil aus seiten.json liegt ein
    unsichtbares Ziel an derselben Stelle (fuer die Marken).
    -> (Wurzel, Ziele)"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
    pm = QPixmap(info["pfad"])
    if pm.isNull():
        raise SystemExit("ABBRUCH: Seite nicht zu laden: %s" % info["pfad"])
    pm.setDevicePixelRatio(2.0)
    wurzel = _flaeche("wurzel", "background: %s;" % GRUND)
    aussen = QHBoxLayout(wurzel)
    aussen.setContentsMargins(0, 0, 0, 0)
    rahmen = _flaeche("rahmen", "background: #ffffff; border: 1px solid "
                      "#c9ced6; border-radius: 8px;")
    rl = QVBoxLayout(rahmen)
    rl.setContentsMargins(1, 1, 1, 1)
    rl.setSpacing(0)
    kopf = _flaeche("kopf", "background: #ffffff; border: none; "
                    "border-bottom: 1px solid #e4e1ee; "
                    "border-top-left-radius: 8px; "
                    "border-top-right-radius: 8px;")
    kl = QHBoxLayout(kopf)
    kl.setContentsMargins(12, 7, 14, 7)
    kl.setSpacing(8)
    logo = D._logo_pixmap(16)
    if logo is not None:
        kl.addWidget(_bild_label(logo))
    kl.addWidget(_label(FENSTER_TITEL, "font-size: 12px; color: #1d1d1f; "
                        "background: transparent; border: none;"))
    kl.addStretch(1)
    for name in ("minus", "x"):
        kl.addWidget(_bild_label(_symbol(D, name, "#6e6e73", 14)))
        kl.addSpacing(10)
    rl.addWidget(kopf)
    seite = QLabel()
    seite.setPixmap(pm)
    seite.setFixedSize(int(info["breite"]), int(info["hoehe"]))
    seite.setStyleSheet("border: none; background: transparent;")
    rl.addWidget(seite)
    aussen.addWidget(rahmen, 0, Qt.AlignmentFlag.AlignLeft)
    ziele = {}
    for name, (x, y, b, h) in info["ziele"].items():
        z = QWidget(seite)
        z.setObjectName(name)
        z.setGeometry(int(round(x)), int(round(y)), max(1, int(round(b))),
                      max(1, int(round(h))))
        z.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ziele[name] = z
    return wurzel, ziele


def fenster_titel():
    """Der Titel des Einrichtungsfensters, aus der XAML gelesen."""
    with open(os.path.join(P.VERTEILUNG, P.FENSTER_XAML),
              encoding="utf-8") as fh:
        m = re.search(r'<Window[^>]*\sTitle="([^"]+)"', fh.read())
    if not m:
        raise SystemExit("ABBRUCH: kein Titel in %s" % P.FENSTER_XAML)
    return m.group(1)


FENSTER_TITEL = None


def szene_apps(D):
    """Schema: Claude Desktop und ChatGPT-App -> Open MCP CAD -> Cadwork
    «Bereit»; «Browser / Handy» durchgestrichen (dort geht es nicht). Nur Namen und eigene
    Strich-Symbole, keine fremden Logos, kein Nachbau fremder Oberflaechen."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPen
    from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
    text, farbe_bereit = D.PILLE["ready"]
    karte = "background: #ffffff; border: 1px solid #c9ced6; " \
            "border-radius: 10px;"

    class Leinwand(QWidget):
        linien = ()

        def paintEvent(self, _ev):
            m = QPainter(self)
            m.setRenderHint(QPainter.RenderHint.Antialiasing)
            farbe = QColor("#6e6e73")
            for von, nach in self.linien:
                y_von = von.mapTo(self, von.rect().center()).y()
                y_nach = nach.mapTo(self, nach.rect().center()).y()
                a = QPointF(von.mapTo(self, von.rect().topRight()).x() + 6,
                            y_von)
                b = QPointF(nach.mapTo(self, nach.rect().topLeft()).x() - 6,
                            y_nach)
                m.setPen(QPen(farbe, 2.5))
                m.drawLine(a, QPointF(b.x() - 10, b.y()))
                m.setPen(Qt.PenStyle.NoPen)
                m.setBrush(farbe)
                m.drawPolygon([b, QPointF(b.x() - 13, b.y() - 6.5),
                               QPointF(b.x() - 13, b.y() + 6.5)])
            m.end()

    wurzel = Leinwand()
    wurzel.setObjectName("wurzel")
    wurzel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    wurzel.setStyleSheet("#wurzel { background: %s; } QLabel { color: "
                         "#1d1d1f; font-size: 13px; background: "
                         "transparent; border: none; }" % GRUND)
    lay = QHBoxLayout(wurzel)
    lay.setContentsMargins(76, 60, 24, 70)
    lay.setSpacing(90)
    ziele = {}

    def app_karte(kennung, name, aktiv=True):
        k = _flaeche("app_" + kennung, karte if aktiv else
                     "background: #f4f5f7; border: 1px dashed #b8bec8; "
                     "border-radius: 10px;")
        kl = QVBoxLayout(k)
        kl.setContentsMargins(14, 10, 12, 12)
        kl.setSpacing(9)
        kopf = QHBoxLayout()
        kopf.setSpacing(8)
        kopf.addWidget(_bild_label(_symbol(
            D, "message-square" if aktiv else "globe",
            "#1d1d1f" if aktiv else "#9aa0a8", 18)))
        kopf.addWidget(_label(name, "font-weight: 600;" if aktiv else
                              "font-weight: 600; color: #9aa0a8;"))
        kopf.addStretch(1)
        if aktiv:
            neu = _bild_label(_symbol(D, "refresh-cw", "#1d1d1f", 18))
            kopf.addWidget(neu)
            ziele["neu_" + kennung] = neu
        else:
            kopf.addWidget(_bild_label(_symbol(D, "ban", "#d70015", 20)))
        kl.addLayout(kopf)
        if aktiv:
            feld = _flaeche("feld_" + kennung, "background: #f6f7f9; "
                            "border: 1px solid #dfe2e7; border-radius: 14px;")
            fl = QHBoxLayout(feld)
            fl.setContentsMargins(12, 5, 6, 5)
            fl.addWidget(_label("…", "color: #8e8e93;"))
            fl.addStretch(1)
            fl.addWidget(_bild_label(_symbol(D, "arrow-up", "#8e8e93", 16)))
            kl.addWidget(feld)
            ziele["chat_" + kennung] = feld
        k.setFixedWidth(220)
        return k

    links = QVBoxLayout()
    links.setSpacing(20)
    claude = app_karte("claude", "Claude Desktop")
    codex = app_karte("codex", "ChatGPT-App")
    chatgpt = app_karte("chatgpt", "Browser / Handy", aktiv=False)
    links.addStretch(1)
    links.addWidget(claude)
    links.addWidget(codex)
    links.addSpacing(30)
    links.addWidget(chatgpt)
    links.addStretch(1)
    lay.addLayout(links)
    ziele["chatgpt"] = chatgpt

    mitte = _flaeche("mitte", karte)
    ml = QVBoxLayout(mitte)
    ml.setContentsMargins(18, 16, 18, 16)
    ml.setSpacing(8)
    logo = D._logo_pixmap(44)
    if logo is None:
        raise SystemExit("ABBRUCH: Logo nicht zu laden")
    ml.addWidget(_bild_label(logo), 0, Qt.AlignmentFlag.AlignHCenter)
    ml.addWidget(_label("Open MCP CAD", "font-weight: 600;"), 0,
                 Qt.AlignmentFlag.AlignHCenter)
    marke = _flaeche("marke", "background: #f3f4f6; border: none; "
                     "border-radius: 6px;")
    mk = QHBoxLayout(marke)
    mk.setContentsMargins(8, 4, 8, 4)
    mk.setSpacing(6)
    mk.addWidget(_bild_label(_symbol(D, "terminal", "#1d1d1f", 14)))
    mk.addWidget(_label(P.INSTALLIEREN, "font-size: 11px;"))
    ml.addWidget(marke, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(mitte, 0, Qt.AlignmentFlag.AlignVCenter)
    ziele["installer_marke"] = marke

    cad = _flaeche("cad", karte)
    cl = QVBoxLayout(cad)
    cl.setContentsMargins(22, 16, 22, 16)
    cl.setSpacing(10)
    cl.addWidget(_bild_label(_symbol(D, "layers", "#1d1d1f", 40)), 0,
                 Qt.AlignmentFlag.AlignHCenter)
    cl.addWidget(_label("Cadwork", "font-weight: 600;"), 0,
                 Qt.AlignmentFlag.AlignHCenter)
    pille = _label("● " + text, "border-radius: 10px; padding: 3px 10px; "
                   "font-size: 11px; font-weight: 600; color: #ffffff; "
                   "background: %s;" % farbe_bereit)
    cl.addWidget(pille, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(cad, 0, Qt.AlignmentFlag.AlignVCenter)
    ziele["pille"] = pille
    wurzel.linien = ((claude, mitte), (codex, mitte), (mitte, cad))
    return wurzel, ziele


def _rechteck(wd, wurzel, rand):
    """Rechteck eines Ziels (Widget oder Liste von Widgets) in logischen px
    der Leinwand (Wurzel plus Rand)."""
    from PyQt6.QtCore import QPoint, QRect
    r = QRect()
    for teil in (wd if isinstance(wd, list) else [wd]):
        if not teil.isVisible():
            raise SystemExit("ABBRUCH: ein Ziel ist nicht zu sehen: %r"
                             % teil.objectName())
        r = r.united(QRect(teil.mapTo(wurzel, QPoint(0, 0)), teil.size()))
    return r.translated(rand[0], rand[1])


def _kreis(r, anker, dx, dy):
    """Mitte des Kreises einer Marke (wie `marken_malen`)."""
    rand = 4
    mx, my = r.x() + r.width() / 2.0, r.y() + r.height() / 2.0
    mx, my = {"mitte": (mx, my), "links": (r.x() - rand, my),
              "rechts": (r.x() + r.width() + rand, my),
              "oben": (mx, r.y() - rand),
              "unten": (mx, r.y() + r.height() + rand)}[anker]
    return mx + dx, my + dy


#: Zahl der Muster aus persoenlich.txt, gegen die geprueft wurde.
_MUSTER = [0]


def rendern(name, wurzel, ziele, ziel_ordner, pdf_ordner, bis=None,
            texte=()):
    """Rendert `wurzel` (200 %) auf eine Leinwand mit Rand, prueft die
    sichtbaren Texte, malt die Marken, schreibt WebP (+ Vorschau) und mit
    `pdf_ordner` das PNG. `bis`: ein Widget, unter dem das Bild endet
    (24 px Luft). -> Pfad des WebP"""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    ausgabe, rand, marken = SZENEN[name]
    fehlt = [z for _n, z, _a, _x, _y in marken if z not in ziele]
    if fehlt:
        raise SystemExit("ABBRUCH: %s ohne %s" % (ausgabe, fehlt))
    # `texte`: was im gerenderten Bild einer Fensterseite steht (Qt sieht
    # dort nur ein Bild).
    _MUSTER[0] = B.texte_pruefen(B.sichtbare_texte(wurzel) + list(texte),
                                 ausgabe)
    k = 2.0
    b = wurzel.width() + rand[0] + rand[2]
    h = wurzel.height() + rand[1] + rand[3]
    bild = QImage(int(b * k), int(h * k),
                  QImage.Format.Format_ARGB32_Premultiplied)
    bild.setDevicePixelRatio(k)
    bild.fill(QColor(GRUND))
    m = QPainter(bild)
    wurzel.render(m, QPoint(rand[0], rand[1]))
    m.end()
    bild.setDevicePixelRatio(1.0)
    if bis is not None:
        h = _rechteck(bis, wurzel, rand).bottom() + 24
        bild = bild.copy(0, 0, bild.width(), int(h * k))
    orte = {ziel: _rechteck(ziele[ziel], wurzel, rand)
            for _nr, ziel, _a, _dx, _dy in marken}
    for nr, ziel, anker, dx, dy in marken:
        # Jeder Kreis ganz im Bild (sonst waere eine Nummer abgeschnitten).
        kx, ky = _kreis(orte[ziel], anker, dx, dy)
        if not (15 <= kx <= b - 15 and 15 <= ky <= h - 15):
            raise SystemExit("ABBRUCH: %s Marke %d liegt am Rand (%d, %d in "
                             "%dx%d)" % (ausgabe, nr, kx, ky, b, h))
    m = QPainter(bild)
    m.setRenderHint(QPainter.RenderHint.Antialiasing)
    W.marken_malen(m, marken, orte, k)
    m.end()
    pfad = os.path.join(ziel_ordner, "mcp-" + ausgabe + ".webp")
    W._webp(bild.scaledToWidth(int(round(b * W.MASSSTAB)),
                               Qt.TransformationMode.SmoothTransformation),
            pfad)
    if name in VORSCHAU:
        vx, vy, vb = VORSCHAU[name]
    else:
        vb = min(b, h * 1.5)
        vx, vy = (b - vb) / 2.0, 0
    teil = bild.copy(int(vx * k), int(vy * k), int(vb * k),
                     int(vb * 2 / 3.0 * k))
    W._webp(teil.scaledToWidth(W.VORSCHAU_BREITE,
                               Qt.TransformationMode.SmoothTransformation),
            pfad[:-len(".webp")] + "-klein.webp")
    if pdf_ordner:
        png = os.path.join(pdf_ordner, ausgabe + ".png")
        gross = bild.scaledToWidth(int(round(b * W.MASSSTAB_PDF)),
                                   Qt.TransformationMode.SmoothTransformation)
        if not gross.convertToFormat(QImage.Format.Format_RGB32).save(png,
                                                                      "PNG"):
            raise SystemExit("ABBRUCH: PNG nicht schreibbar: %s" % png)
        print("%s  %dx%d  %d KB" % (png, gross.width(), gross.height(),
                                    os.path.getsize(png) // 1024))
    return pfad


def _zeigen(app, wurzel):
    from PyQt6.QtCore import Qt
    wurzel.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    wurzel.move(0, 0)
    wurzel.show()
    _pumpen(app, 8)
    wurzel.adjustSize()
    _pumpen(app, 4)


def _dock_takt(D, z, app):
    D._fenster_lage(z)
    _pumpen(app, 10)
    for _ in range(5):
        D._auffrischen(z)
        D._chat_zeichnen(z)
        _pumpen(app)


def main():
    args = sys.argv[1:]
    frei = [a for i, a in enumerate(args)
            if not a.startswith("--")
            and (i == 0 or args[i - 1] not in ("--persoenlich", "--privat",
                                                "--pdf"))]
    if not frei:
        raise SystemExit(__doc__)
    ziel = os.path.abspath(frei[0])
    os.makedirs(ziel, exist_ok=True)
    pdf = (os.path.abspath(args[args.index("--pdf") + 1]) if "--pdf" in args
           else None)
    if pdf:
        os.makedirs(pdf, exist_ok=True)
    # Zuerst die Seiten des Einrichtungsfensters (WPF, ohne Fenster).
    global FENSTER_TITEL
    FENSTER_TITEL = fenster_titel()
    seiten_ordner = tempfile.mkdtemp(prefix="omcad_fensterseiten_")
    seiten = fenster_seiten(seiten_ordner)

    # Qt wie bilder_rendern.main: ein Bildschirm 1920x1080 mit Dichte 2,
    # das Dock aus dem Gate (Attrappen, kein Cadwork, kein Netz).
    plattform, schirm_ordner = B._schirm()
    os.environ["QT_QPA_PLATFORM"] = plattform
    T = B._gate_laden()
    os.environ["QT_QPA_PLATFORM"] = plattform
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    T._draht_legen()
    vorher = os.getcwd()
    os.chdir(schirm_ordner)
    app = QApplication.instance() or QApplication([])
    os.chdir(vorher)
    T._APP = app
    app.setFont(QFont("Segoe UI", 9))
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
    z["dienst"] = Dienst()
    D._auffrischen(z)
    _pumpen(app)

    def fenster_szene(name):
        info = seiten[FENSTER_SZENEN[name]]
        wurzel, ziele = szene_fenster(D, info)
        _zeigen(app, wurzel)
        rendern(name, wurzel, ziele, ziel,
                None if name in NUR_WEBSITE else pdf, texte=info["texte"])
        wurzel.hide()

    # 1 noch keine KI-App
    fenster_szene("ki_app_holen")

    # 2 der entpackte Ordner
    wurzel, ziele = szene_entpacken(D)
    _zeigen(app, wurzel)
    rendern("entpacken", wurzel, ziele, ziel, pdf)
    wurzel.hide()

    # 3-6 das Einrichtungsfenster
    for name in ("wo", "ki_app", "installieren", "laeuft", "python",
                 "fertig", "chat_ki", "anmelden"):
        fenster_szene(name)
    shutil.rmtree(seiten_ordner, ignore_errors=True)

    # 8 fuer Fortgeschrittene: die Karte "Womit möchtest du chatten?" im
    # Dock — wie willkommen.png in bilder_rendern (nichts eingerichtet).
    chat = z["chat"]
    chat.update(an=False, ereignisse=[], stand=chat.get("stand", 0) + 1)
    D._chat_oeffnen(z)
    D._einstieg_setzen(z, {"claude": False, "codex": False,
                           "schluessel": False, "lokal": False})
    # Breiter als die Vorgabe (420): weniger Umbrueche, im PDF lesbar.
    z["offen_groesse"] = (620, 700)
    _dock_takt(D, z, app)
    f, w = z["fenster"], z["w"]
    if not w["chat_willkommen"].isVisible():
        raise SystemExit("ABBRUCH: die Karte 'Womit möchtest du chatten?' "
                         "ist nicht zu sehen")
    rendern("chat", f, w, ziel, pdf, bis=w["chat_willkommen_pruefen"])
    f.hide()

    # 7 Claude Desktop / Codex-App
    wurzel, ziele = szene_apps(D)
    _zeigen(app, wurzel)
    rendern("apps", wurzel, ziele, ziel, pdf)
    wurzel.hide()
    T._frischer_start()
    print("geprueft gegen %s Muster aus persoenlich.txt%s" % (
        _MUSTER[0], "" if _MUSTER[0] else
        " (keine Datei — nur Benutzerpfade und Spuren geprueft)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
