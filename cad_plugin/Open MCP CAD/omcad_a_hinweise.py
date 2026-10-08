# -*- coding: utf-8 -*-
"""Das Hinweis-Board: Pruefhinweise lesen, abhaken, beantworten.

Eigene Datei, weil das Dashboard sonst weiter waechst — und weil sich das
Board so OHNE Cadwork bauen und bedienen laesst. Qt ist erlaubt, cwapi3d
nicht: Modell-Arbeit geht ausschliesslich ueber die mitgegebene Funktion
`auftrag(...)`, also ueber dieselbe Warteschlange wie alles andere.

WARUM DER AUFBAU SO IST (am 2026-08-15 offscreen gemessen, Dock 320 px):

    A  QScrollArea + QVBoxLayout + eigene Karten     6/6 Karten vollstaendig
    B  QListWidget + setItemWidget                   0/6  <- Text abgeschnitten
    C  QListWidget + sizeHint von Hand nachgerechnet 6/6

Ein QLabel mit Wortumbruch braucht eine Hoehe, die von der BREITE abhaengt
(`heightForWidth`). Ein QListWidget fragt nicht danach; man muesste die
Hoehe bei jeder Breitenaenderung selbst nachrechnen (Weg C). Weg A macht das
Layout von sich aus richtig — deshalb ist es Weg A geworden.

UND DER ZWEITE GRUND FUER EIGENE KARTEN: die Auswahl.
Rueckmeldung 2026-08-15: "man kann sie nicht sauber auswaehlen sie werden wie
abgewaehlt die muessen wie markiert bleiben". Die Ursache lag im alten
Board: sein Stempel enthielt einen Zeiteimer `int(alter/5)`, der alle fuenf
Sekunden umsprang — dann wurde die Liste geleert und neu gefuellt, und die
Auswahl war weg. Gemessen: Auswahl nach 0,75 s verloren, die Kontrollzelle
(Eimerkante ausserhalb des Messfensters) behielt sie.
Hier gibt es deshalb kein `clear()` im Takt. Karten werden ANGELEGT, wenn
ein Hinweis neu ist, und sonst nur AKTUALISIERT. Die Auswahl ist ein
eigener Wert (`gewaehlt_nr`) und ueberlebt jedes Auffrischen.
"""
import time

# --- Gruppierung ----------------------------------------------------------
# Rueckmeldung: "briefkasten und hinweise sollten auch mal sortiert sein nach sitzung
# in der sie gesendet werden ... zb ein neuer zeichenlauf ging durch mit
# neuen hinweisen dann klar gruppiert ... die anderen wie in ein archiv".
#
# Der Kern stempelt jeden Hinweis mit `lauf` (siehe `d.lauf_nr`). Alte, schon
# gespeicherte Hinweise haben den Stempel nicht — fuer die gibt es den
# Rueckfall ueber die ZEITLUECKE. Beides zusammen heisst: das Board
# funktioniert auch mit den Notizen, die schon auf der Platte liegen.
LUECKE_S = 15 * 60          # ab 15 Min Ruhe beginnt eine neue Gruppe


def gruppieren(hinweise):
    """Hinweise in Laeufe zerlegen, neuester Lauf zuerst.

    Rueckgabe: Liste von (schluessel, titel, [hinweise]) — innerhalb einer
    Gruppe der neueste Hinweis oben.
    """
    if not hinweise:
        return []
    nach_zeit = sorted(hinweise, key=lambda h: h.get("zeit") or 0)

    gruppen, laufend, letzte_zeit, letzter_lauf = [], [], None, None
    for h in nach_zeit:
        lauf = h.get("lauf")
        zeit = h.get("zeit") or 0
        # BEIDE Signale zaehlen, nicht nur das genauere. Ein neuer Zeichenlauf
        # trennt immer — aber auch ohne Zeichenlauf soll eine lange Pause
        # trennen, sonst waeren alle Hinweise eines Chat-Nachmittags EINE
        # Gruppe, nur weil zwischendurch niemand gezeichnet hat.
        neu = False
        if lauf is not None and letzter_lauf is not None and lauf != letzter_lauf:
            neu = True
        elif letzte_zeit is not None and (zeit - letzte_zeit) > LUECKE_S:
            neu = True
        if neu and laufend:
            gruppen.append(laufend)
            laufend = []
        laufend.append(h)
        letzte_zeit, letzter_lauf = zeit, lauf
    if laufend:
        gruppen.append(laufend)

    gruppen.reverse()                       # neueste Gruppe zuerst
    heraus = []
    for i, g in enumerate(gruppen):
        g = sorted(g, key=lambda h: h.get("zeit") or 0, reverse=True)
        schluessel = g[0].get("lauf")
        if schluessel is None:
            schluessel = "z%d" % int(g[0].get("zeit") or 0)
        offen = sum(1 for h in g if h.get("status") == "offen")
        wann = vor_wie_lange(g[0].get("zeit") or 0)
        titel = ("Jetzt · %s" % wann) if i == 0 else ("Früher · %s" % wann)
        titel += "   %d Hinweis%s" % (len(g), "" if len(g) == 1 else "e")
        if offen:
            titel += ", %d offen" % offen
        heraus.append((schluessel, titel, g))
    return heraus


def vor_wie_lange(t):
    if not t:
        return "—"
    s = max(0, int(time.time() - t))
    if s < 60:
        return "gerade eben"
    if s < 3600:
        return "vor %d Min" % (s // 60)
    if s < 86400:
        return "vor %d Std" % (s // 3600)
    return "vor %d Tagen" % (s // 86400)


# --- Aussehen -------------------------------------------------------------
# Rueckmeldung: "die schriftart soll viel cleaner sein und auch nicht nur die selbe
# schriftgroesse und dicke". Also eine echte Rangfolge statt einer Wand aus
# gleich grossem Text: Titel traegt, Text erklaert, Fusszeile fluestert.
SCHWEREGRAD = {
    "fehler":  ("Fehler",  "#ff3b30"),
    "warnung": ("Warnung", "#ff9f0a"),
    "frage":   ("Frage",   "#0071e3"),
    "hinweis": ("Hinweis", "#6e6e73"),
}

QSS = """
#hkarte {
  background: #ffffff; border: 1px solid #e3e3e6;
  border-left: 3px solid #e3e3e6; border-radius: 8px;
}
#hkarte[gewaehlt="ja"] { border: 1px solid #0071e3; border-left: 3px solid #0071e3;
  background: #f5faff; }
#hkarte[erledigt="ja"] { background: #fafafa; }
#htitel     { font-size: 13px; font-weight: 600; color: #1d1d1f; }
#htitel[gelesen="nein"] { font-weight: 700; }
#htext      { font-size: 11px; color: #4a4a4f; }
#hfuss      { font-size: 10px; color: #8e8e93; }
#hstufe     { font-size: 10px; font-weight: 700; }
#hgruppe    { font-size: 11px; font-weight: 700; color: #6e6e73;
              padding: 6px 2px 2px 2px; }
#hleer      { font-size: 12px; color: #8e8e93; padding: 24px 8px; }
#hkontext   { font-size: 11px; color: #0071e3; background: #eef6ff;
              border: 1px solid #cfe4ff; border-radius: 6px; padding: 5px 8px; }
"""


def dringlichkeit_zeichen(n):
    """Die Wichtigkeit in Worten: "Wichtigkeit: gering/mittel/hoch".

    Der alte Balken ("███··") war laut und schlecht lesbar (Rueckmeldung:
    "die kennzeichnung der wichtigkeit ... maximal unuebersichtlich"); die
    Punkte danach ("●●○○○") las niemand ohne Erklaerung (Gegenpruefung
    Laien-Sicht K12). Kaputte Werte zaehlen als mittel.
    """
    try:
        n = max(1, min(5, int(n or 3)))
    except (TypeError, ValueError):
        n = 3
    return "Wichtigkeit: %s" % ("gering" if n <= 2 else
                                "mittel" if n == 3 else "hoch")


#: Statt "anzoomen" (Gegenpruefung Laien-Sicht K12).
ZOOM_TEXT = "nah heran"
ZOOM_TIPP = ("Beim Zeigen fährt die Ansicht nah an die Bauteile des "
             "Hinweises heran")


# --- Eine Karte -----------------------------------------------------------

class Karte:
    """Ein Hinweis als eigenes Widget. Wird ANGELEGT, nicht neu gebaut.

    `setzen()` schreibt nur die Werte neu, die sich geaendert haben. Genau
    das ist der Unterschied zum alten Board: kein clear(), keine verlorene
    Auswahl, kein Flackern.
    """

    def __init__(self, hinweis, umgebung):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                                     QVBoxLayout, QWidget)
        self.u = umgebung
        self.nr = hinweis["nr"]
        self.stand = None

        w = QWidget()
        w.setObjectName("hkarte")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        w.setToolTip("Klick: im Modell zeigen · Doppelklick: den ganzen "
                     "Hinweis lesen")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        kopf = QHBoxLayout()
        kopf.setSpacing(6)
        # Der Haken ist das, worum der Nutzer ausdruecklich gebeten hat: "man muss
        # klar und einfach abhaken koennen ob man es angeschaut hat oder
        # nicht ... am besten durch etwas wie hacken, direkt im
        # hinweisfenster". Also IN der Karte, nicht als Knopf darunter.
        self.haken = QCheckBox()
        self.haken.setToolTip("Erledigt")
        self.haken.setAccessibleName("Erledigt")
        self.stufe = QLabel()
        self.stufe.setObjectName("hstufe")
        self.dring = QLabel()
        self.dring.setObjectName("hfuss")
        kopf.addWidget(self.haken)
        kopf.addWidget(self.stufe)
        kopf.addStretch(1)
        kopf.addWidget(self.dring)
        lay.addLayout(kopf)

        self.titel = QLabel()
        self.titel.setObjectName("htitel")
        self.titel.setWordWrap(True)
        lay.addWidget(self.titel)

        self.text = QLabel()
        self.text.setObjectName("htext")
        self.text.setWordWrap(True)
        lay.addWidget(self.text)

        self.fuss = QLabel()
        self.fuss.setObjectName("hfuss")
        lay.addWidget(self.fuss)

        self.widget = w
        w.mousePressEvent = self._geklickt
        w.mouseDoubleClickEvent = self._doppelt
        self.haken.stateChanged.connect(self._haken_geaendert)
        self.setzen(hinweis, gewaehlt=False)

    # -- Ereignisse --------------------------------------------------------
    def _geklickt(self, ereignis):
        self.u["waehlen"](self.nr)

    def _doppelt(self, ereignis):
        self.u["vollbild"](self.nr)

    def _haken_geaendert(self, _zustand):
        if self.haken.isChecked():
            self.u["setzen"](self.nr, status="erledigt", gelesen=True)
        else:
            self.u["setzen"](self.nr, status="offen")

    # -- Anzeige -----------------------------------------------------------
    def setzen(self, h, gewaehlt):
        """Nur schreiben, wenn sich wirklich etwas geaendert hat."""
        stand = (h.get("titel"), h.get("text"), h.get("status"),
                 h.get("gelesen"), h.get("schweregrad"),
                 h.get("dringlichkeit"), len(h.get("element_ids") or ()),
                 gewaehlt, vor_wie_lange(h.get("zeit")))
        if stand == self.stand:
            return
        self.stand = stand

        name, farbe = SCHWEREGRAD.get(h.get("schweregrad"),
                                      SCHWEREGRAD["hinweis"])
        erledigt = h.get("status") != "offen"
        self.stufe.setText(name.upper())
        self.stufe.setStyleSheet("color: %s;" % ("#9e9e9e" if erledigt
                                                 else farbe))
        self.dring.setText(dringlichkeit_zeichen(h.get("dringlichkeit")))
        self.titel.setText(h.get("titel") or "(ohne Titel)")
        self.titel.setProperty("gelesen", "ja" if h.get("gelesen") else "nein")

        text = (h.get("text") or "").strip()
        # Im Board nur der Anfang — der ganze Text steht im Vollbild. Sonst
        # schiebt ein langer Hinweis alle anderen aus dem Blick.
        if len(text) > 220:
            text = text[:220].rstrip() + " …"
        self.text.setText(text)
        self.text.setVisible(bool(text))

        teile = [vor_wie_lange(h.get("zeit"))]
        n = len(h.get("element_ids") or ())
        if n:
            teile.append("%d Bauteil%s" % (n, "" if n == 1 else "e"))
        if erledigt:
            teile.append(h.get("status"))
        if h.get("quelle") and h["quelle"] != "KI":
            teile.append(h["quelle"])
        self.fuss.setText("  ·  ".join(teile))

        if self.haken.isChecked() != erledigt:
            self.haken.blockSignals(True)
            self.haken.setChecked(erledigt)
            self.haken.blockSignals(False)

        self.widget.setProperty("gewaehlt", "ja" if gewaehlt else "nein")
        self.widget.setProperty("erledigt", "ja" if erledigt else "nein")
        for teil in (self.widget, self.titel):
            teil.style().unpolish(teil)
            teil.style().polish(teil)


# --- Das ganze Board ------------------------------------------------------

def bauen(umgebung):
    """Baut den Hinweis-Tab und gibt seine Teile zurueck.

    `umgebung` traegt die Rueckrufe ins Dashboard:
        waehlen(nr) · vollbild(nr) · setzen(nr, **werte) · zeigen(nr)
        antworten(nr, text) · loeschen(nr)
    So kennt dieses Modul weder den Dienst noch die Warteschlange.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                                 QPushButton, QScrollArea, QVBoxLayout,
                                 QWidget)
    tab = QWidget()
    aussen = QVBoxLayout(tab)
    aussen.setContentsMargins(0, 8, 0, 0)
    aussen.setSpacing(8)

    # -- Kopfzeile: Zaehler und Filter ------------------------------------
    kopf = QHBoxLayout()
    kopf.setSpacing(6)
    zaehler = QLabel("—")
    zaehler.setObjectName("hfuss")
    nur_offen = QCheckBox("nur offene")
    nur_offen.setToolTip("Erledigte ausblenden")
    kopf.addWidget(zaehler, 1)
    kopf.addWidget(nur_offen)
    aussen.addLayout(kopf)

    # -- Die Karten in einer Scroll-Flaeche (Weg A, s. Kopf der Datei) ----
    bereich = QScrollArea()
    bereich.setWidgetResizable(True)
    bereich.setFrameShape(bereich.Shape.NoFrame)
    innen = QWidget()
    innen.setObjectName("hinnen")
    spalte = QVBoxLayout(innen)
    spalte.setContentsMargins(0, 0, 0, 0)
    spalte.setSpacing(6)
    leer = QLabel("Keine Prüfhinweise.\nHier meldet die KI, wo sie etwas "
                  "angenommen hat.")
    leer.setObjectName("hleer")
    leer.setWordWrap(True)
    leer.setAlignment(Qt.AlignmentFlag.AlignCenter)
    spalte.addWidget(leer)
    spalte.addStretch(1)
    bereich.setWidget(innen)
    aussen.addWidget(bereich, 1)

    # -- Antwort mit SICHTBAREM Kontext ------------------------------------
    # Rueckmeldung: "wenn man ein kommentar dazu schreibt fuer briefkasten muss klar
    # erkennbar sein das es als kontext mitkommt ... auf welche hinweis man
    # antwortet und falls man was aktiviert hat das dies auch mitkommt".
    kontext = QLabel("Kein Hinweis gewählt")
    kontext.setObjectName("hkontext")
    kontext.setWordWrap(True)
    aussen.addWidget(kontext)

    reihe = QHBoxLayout()
    reihe.setSpacing(6)
    antwort = QLineEdit()
    antwort.setPlaceholderText("Antwort an die KI …")
    btn_antwort = QPushButton("Senden")
    reihe.addWidget(antwort, 1)
    reihe.addWidget(btn_antwort)
    aussen.addLayout(reihe)

    # -- Knoepfe -----------------------------------------------------------
    r2 = QHBoxLayout()
    r2.setSpacing(6)
    btn_zeigen = QPushButton("Im Modell zeigen")
    btn_zurueck = QPushButton("Ansicht zurück")
    r2.addWidget(btn_zeigen, 1)
    r2.addWidget(btn_zurueck, 1)
    aussen.addLayout(r2)

    r3 = QHBoxLayout()
    r3.setSpacing(6)
    chk_zoom = QCheckBox(ZOOM_TEXT)
    chk_zoom.setToolTip(ZOOM_TIPP)
    chk_zoom.setChecked(True)
    chk_nur = QCheckBox("nur diese sichtbar")
    chk_nur.setToolTip("Blendet alles andere aus — sonst sieht man ein "
                       "aktiviertes Bauteil mitten im Modell nicht. "
                       "«Ansicht zurück» stellt es wieder her.")
    btn_loeschen = QPushButton("Löschen")
    r3.addWidget(chk_zoom)
    r3.addWidget(chk_nur)
    r3.addStretch(1)
    r3.addWidget(btn_loeschen)
    aussen.addLayout(r3)

    teile = {"tab": tab, "spalte": spalte, "innen": innen, "leer": leer,
             "zaehler": zaehler, "nur_offen": nur_offen, "kontext": kontext,
             "antwort": antwort, "btn_antwort": btn_antwort,
             "btn_zeigen": btn_zeigen, "btn_zurueck": btn_zurueck,
             "btn_loeschen": btn_loeschen, "chk_zoom": chk_zoom,
             "chk_nur": chk_nur, "karten": {}, "koepfe": {},
             "gewaehlt_nr": None, "aufbau": None}
    return teile


def zeichnen(teile, hinweise, umgebung, aktive_elemente=0):
    """Das Board auffrischen — OHNE die Auswahl anzufassen.

    Karten werden nur angelegt und entfernt, wenn sich die MENGE aendert;
    sonst bekommen die vorhandenen ihre neuen Werte. Der Aufbau (welche
    Gruppen, welche Reihenfolge) wird nur neu gelegt, wenn er sich wirklich
    unterscheidet — sonst zappelt die Liste im Takt.
    """
    from PyQt6.QtWidgets import QLabel

    sichtbar = [h for h in hinweise
                if not teile["nur_offen"].isChecked()
                or h.get("status") == "offen"]
    gruppen = gruppieren(sichtbar)

    offen = sum(1 for h in hinweise if h.get("status") == "offen")
    ungelesen = sum(1 for h in hinweise
                    if not h.get("gelesen") and h.get("status") == "offen")
    teile["zaehler"].setText(
        "%d Hinweise · %d offen%s" % (len(hinweise), offen,
                                      (" · %d ungelesen" % ungelesen)
                                      if ungelesen else ""))
    teile["leer"].setVisible(not sichtbar)

    aufbau = tuple((s, t, tuple(h["nr"] for h in g)) for s, t, g in gruppen)
    spalte = teile["spalte"]
    if aufbau != teile["aufbau"]:
        teile["aufbau"] = aufbau
        # Nur die REIHENFOLGE neu legen. Die Karten selbst bleiben dieselben
        # Objekte — sonst waere die Auswahl wieder weg, und genau darum geht
        # es hier.
        for i in reversed(range(spalte.count())):
            posten = spalte.itemAt(i)
            if posten.widget() is teile["leer"]:
                continue
            spalte.takeAt(i)
        gebraucht = set()
        for schluessel, titel, gruppe in gruppen:
            kopf = teile["koepfe"].get(schluessel)
            if kopf is None:
                kopf = QLabel()
                kopf.setObjectName("hgruppe")
                kopf.setWordWrap(True)
                teile["koepfe"][schluessel] = kopf
            kopf.setText(titel)
            spalte.addWidget(kopf)
            for h in gruppe:
                karte = teile["karten"].get(h["nr"])
                if karte is None:
                    karte = Karte(h, umgebung)
                    teile["karten"][h["nr"]] = karte
                spalte.addWidget(karte.widget)
                gebraucht.add(h["nr"])
        spalte.addStretch(1)
        # Karten, die es nicht mehr gibt, wirklich abraeumen.
        for nr in [n for n in teile["karten"] if n not in gebraucht]:
            karte = teile["karten"].pop(nr)
            karte.widget.setParent(None)
            karte.widget.deleteLater()
        for s in [k for k in teile["koepfe"]
                  if k not in {g[0] for g in gruppen}]:
            kopf = teile["koepfe"].pop(s)
            kopf.setParent(None)
            kopf.deleteLater()
    else:
        for schluessel, titel, _g in gruppen:
            kopf = teile["koepfe"].get(schluessel)
            if kopf is not None:
                kopf.setText(titel)

    nach_nr = {h["nr"]: h for h in hinweise}
    for nr, karte in teile["karten"].items():
        h = nach_nr.get(nr)
        if h is not None:
            karte.setzen(h, gewaehlt=(nr == teile["gewaehlt_nr"]))

    _kontext_schreiben(teile, nach_nr.get(teile["gewaehlt_nr"]),
                       aktive_elemente)


def _kontext_schreiben(teile, hinweis, aktive_elemente):
    """Was mit der Antwort in den Briefkasten geht — im Klartext.

    Vorher stand hier nichts; der Bezug wurde still an den Text geklebt.
    Wer nicht in den Code sah, konnte nicht wissen, dass ueberhaupt etwas
    mitging — und schon gar nicht, was.
    """
    zeilen = []
    if hinweis is None:
        zeilen.append("Kein Hinweis gewählt — die Antwort geht ohne Bezug.")
    else:
        zeilen.append("↩ Antwort auf #%s «%s»"
                      % (hinweis["nr"], _kurz(hinweis.get("titel"), 40)))
        n = len(hinweis.get("element_ids") or ())
        if n:
            zeilen.append("mit den %d Bauteilen des Hinweises" % n)
    if aktive_elemente:
        # "zuletzt gesehen" ist kein Zoegern, sondern genau. Der Kern frischt
        # die Zahl nur im Leerlauf auf (hoechstens alle 5 s) und waehrend
        # eines Zeichenlaufs gar nicht. Was TATSAECHLICH mitgeht, liest der
        # Kern beim Senden frisch aus Cadwork — die Nachricht ist also
        # richtig, auch wenn diese Zahl hinterherhinkt. Nur behaupten darf
        # man es nicht.
        zeilen.append("+ Bauteile, die in Cadwork aktiv sind "
                      "(zuletzt gesehen: %d)" % aktive_elemente)
    teile["kontext"].setText("   ·   ".join(zeilen))


def _kurz(text, n):
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[:n - 1] + "…"


def nachricht_bauen(hinweis, text, aktive_elemente=0):
    """Die Nachricht, wie sie im Briefkasten landet — mit sichtbarem Bezug.

    Bewusst als Text und nicht als Feld: `get_pending_messages` liefert die
    Nachricht als Zeichenkette an die KI weiter. Ein Bezug, den nur die
    Oberflaeche kennt, kaeme dort nie an.
    """
    if hinweis is None:
        kopf = ""
    else:
        kopf = ("[Antwort auf Prüfhinweis #%s — %s]\n"
                % (hinweis["nr"], hinweis.get("titel") or ""))
        ids = hinweis.get("element_ids") or []
        if ids:
            gezeigt = ", ".join(str(i) for i in ids[:12])
            if len(ids) > 12:
                gezeigt += " … (%d insgesamt)" % len(ids)
            kopf += "[Bauteile des Hinweises: %s]\n" % gezeigt
    if aktive_elemente:
        # BEWUSST OHNE ZAHL. Die Zahl aus der Oberflaeche kann veraltet sein
        # (der Kern frischt sie nur im Leerlauf auf); die IDs im Anhang sind
        # es nicht — die liest `_m_nachricht_senden` im Cadwork-Hauptthread
        # frisch aus. Eine falsche Zahl neben richtigen IDs waere schlimmer
        # als gar keine: sie liesse die KI glauben, sie kenne den Umfang.
        kopf += ("[Die aktuell in Cadwork aktivierten Bauteile hängen als "
                 "Kontext an dieser Nachricht — die IDs stehen im Feld "
                 "'kontext'.]\n")
    return kopf + text


# --- Vollbild -------------------------------------------------------------

def vollbild_zeigen(eltern, hinweis, umgebung):
    """Einen Hinweis gross lesen. Ein ausdruecklicher Wunsch, und der Text steht sonst nur
    angeschnitten in der Karte.

    Nicht modal: Cadwork soll waehrenddessen bedienbar bleiben — ein modaler
    Dialog wuerde die Ereignisschleife anhalten, und in genau der laeuft die
    Auftragswarteschlange.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                                 QTextBrowser, QVBoxLayout)
    dlg = QDialog(eltern)
    dlg.setWindowTitle("Prüfhinweis #%s" % hinweis["nr"])
    dlg.setModal(False)
    dlg.resize(560, 460)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    name, farbe = SCHWEREGRAD.get(hinweis.get("schweregrad"),
                                  SCHWEREGRAD["hinweis"])
    kopf = QLabel("%s · %s · %s"
                  % (name.upper(),
                     dringlichkeit_zeichen(hinweis.get("dringlichkeit")),
                     vor_wie_lange(hinweis.get("zeit"))))
    kopf.setStyleSheet("color: %s; font-size: 11px; font-weight: 700;" % farbe)
    lay.addWidget(kopf)

    titel = QLabel(hinweis.get("titel") or "")
    titel.setWordWrap(True)
    titel.setStyleSheet("font-size: 17px; font-weight: 600; color: #1d1d1f;")
    lay.addWidget(titel)

    # QTextBrowser statt QLabel: der ganze Text kann lang sein und braucht
    # eine eigene Scroll-Flaeche. Auswaehlbar ist er hier ausserdem — im
    # Board waere das nur im Weg, hier will man zitieren koennen.
    koerper = QTextBrowser()
    koerper.setOpenExternalLinks(False)
    koerper.setPlainText(hinweis.get("text") or "(kein weiterer Text)")
    koerper.setStyleSheet("border: none; font-size: 13px; color: #2a2a2e;")
    lay.addWidget(koerper, 1)

    ids = hinweis.get("element_ids") or []
    fuss = QLabel("%d Bauteil%s: %s"
                  % (len(ids), "" if len(ids) == 1 else "e",
                     ", ".join(str(i) for i in ids[:20])
                     + (" …" if len(ids) > 20 else ""))
                  if ids else "Keine Bauteile verknüpft")
    fuss.setWordWrap(True)
    fuss.setStyleSheet("font-size: 11px; color: #8e8e93;")
    lay.addWidget(fuss)

    reihe = QHBoxLayout()
    btn_zeigen = QPushButton("Im Modell zeigen")
    btn_zeigen.setEnabled(bool(ids))
    btn_zu = QPushButton("Schliessen")
    reihe.addWidget(btn_zeigen)
    reihe.addStretch(1)
    reihe.addWidget(btn_zu)
    lay.addLayout(reihe)

    btn_zeigen.clicked.connect(lambda: umgebung["zeigen"](hinweis["nr"]))
    btn_zu.clicked.connect(dlg.close)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.show()
    return dlg
