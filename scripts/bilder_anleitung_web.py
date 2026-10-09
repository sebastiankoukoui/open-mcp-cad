#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bebilderte Anleitung fuer die Website (Abschnitt #mcp auf lignoai.ch):
vier Bilder des EINEN Fensters ueber dem Cadwork-Ersatz, mit nummerierten
Kreisen und feinen Pfeilen auf die Knoepfe — OHNE Saetze im Bild, damit
ein Bild fuer alle Sprachen reicht. Die Erklaerungen zu den Nummern stehen
auf der Website neben dem Bild, je Sprache.

    <omcadqt-python> scripts/bilder_anleitung_web.py ZIELORDNER
                     [--persoenlich PFAD] [--privat PFAD] [--roh ORDNER]
                     [--pdf ORDNER]

Braucht PyQt6 (die venv aus CLAUDE.md, `%LOCALAPPDATA%\\Temp\\omcadqt`).

WIE: `bilder_rendern.py --ueberblick` rendert die Szenen (Demo-Inhalt
«Seeblick», 200 %, dieselben Attrappen wie im Gate, kein Cadwork, kein
Netz) und prueft dabei jeden sichtbaren Text gegen Benutzerpfad,
persoenlich.txt und privat_spuren.txt (Abbruch vor dem Speichern). Ueber
den Haken `bilder_rendern.NACH_BILD` misst dieses Skript, solange die
Fenster stehen, wo die markierten Knoepfe liegen — die Marken folgen also
dem echten Aufbau, keine festen Pixel. Dann: Ausschnitt, Kreise und
Pfeile, verkleinert, WebP unter `GRENZE_BYTES`, dazu je Szene ein kleines
Vorschaubild 3:2 (`VORSCHAU`) fuer die Kachelreihe der Website und mit
`--pdf ORDNER` dieselben Bilder als PNG fuer den Schnellstart (PDF).

Ergebnis in ZIELORDNER: mcp-anleitung-1-leiste.webp, -2-chat.webp,
-3-angedockt.webp, -4-anzeige.webp und je ein -klein.webp (Vorschau).
Mit `--pdf verteilung/bilder` dazu anleitung-1-leiste.png … fuer
SCHNELLSTART(.xx).md, Abschnitt 7. Die Rohbilder bleiben in `--roh`
(Vorgabe: ein Temp-Ordner). Auf der Website liegen sie ohne das
Praefix "mcp-" unter assets/mcp/ (anleitung-1-leiste.webp …); aendert
sich ein Ausschnitt, auch width/height der <img> in src/index.html der
Website nachziehen.
"""
import math
import os
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

import bilder_rendern as B                                  # noqa: E402

#: Farbe der Marken: das Violett von Open MCP CAD auf lignoai.ch.
FARBE = "#6547c9"
#: Groesse der Bilder: Breite des Ausschnitts (logische px) mal MASSSTAB.
MASSSTAB = 1.75
#: Fuer das PDF (hoechstens 105 mm hoch, ~300 dpi) reicht weniger.
MASSSTAB_PDF = 1.5
GRENZE_BYTES = 300 * 1024
#: Vorschaubilder (3:2) der Kachelreihe: Ausschnitt x, y, b, h (logisch)
#: aus dem SCHON beschrifteten Bild, Breite der Ausgabe in px.
VORSCHAU = {
    "01_pille.png": (840, 20, 450, 300),
    "02_pille_chat.png": (760, 40, 510, 340),
    "04_angedockt_briefkasten.png": (1017, 40, 423, 282),
    "10_anzeige_zeichnet.png": (170, 30, 540, 360),
}
VORSCHAU_BREITE = 480

#: Szene -> (Ausgabe, Ausschnitt x, y, b, h in logischen px des Cadwork-
#: Ersatzes, Marken). Marke = (Nummer, Ziel, Anker, dx, dy): Ziel ist ein
#: Schluessel aus z["w"], "fenster" (das eine Fenster), "anzeige" (die
#: Arbeitsanzeige) oder "text:<Teil>" (das kleinste sichtbare Teil des
#: Fensters mit diesem Text); der Kreis sitzt um (dx, dy) logische px neben
#: dem Anker des Ziels (mitte, links, rechts, oben, unten), der Pfeil zeigt
#: auf den naechsten Punkt des Ziels.
SZENEN = {
    "01_pille.png": ("mcp-anleitung-1-leiste.webp", (600, 0, 840, 230), [
        (1, "fenster", "links", -60, 0),
        (2, "pille", "unten", 0, 60),
        (3, "kopf_chat", "unten", 0, 60),
        (4, "kopf_andocken", "unten", 0, 60),
    ]),
    "02_pille_chat.png": ("mcp-anleitung-2-chat.webp", (755, 40, 500, 820), [
        (1, "chat_eingabe", "links", -69, 0),
        (2, "text:Schritte in Cadwork", "links", -69, 0),
        (3, "btn_undo", "oben", -65, -15),
        (4, "chat_modus", "links", -107, 0),
        (5, "chat_modell_knopf", "oben", 20, -110),
    ]),
    "04_angedockt_briefkasten.png": ("mcp-anleitung-3-angedockt.webp",
                                     (1017, 40, 423, 820), [
        (1, "segment", "rechts", 28, 0),
        (2, "briefkasten_laeuft", "unten", 60, 28),
        (3, "post_eingabe", "oben", 60, -50),
        (4, "kopf_andocken", "unten", -40, 50),
    ]),
    "10_anzeige_zeichnet.png": ("mcp-anleitung-4-anzeige.webp",
                                (140, 40, 680, 230), [
        (1, "anzeige", "links", -50, 0),
        (2, "anzeige_balken", "unten", 0, 60),
        (3, "anzeige_knopf", "rechts", 75, 40),
    ]),
}

_ORTE = {}


def _ziel_widget(ziel, z):
    if ziel.startswith("text:"):
        from PyQt6.QtWidgets import QWidget
        teil = ziel[5:]
        treffer = []
        for wd in z["fenster"].findChildren(QWidget):
            f = getattr(wd, "text", None)
            if not callable(f) or not wd.isVisible():
                continue
            try:
                t = f()
            except TypeError:
                continue
            if isinstance(t, str) and teil in t:
                treffer.append((wd.width() * wd.height(), id(wd), wd))
        return min(treffer)[2] if treffer else None
    if ziel == "fenster":
        return z["fenster"]
    if ziel == "anzeige":
        return z["anzeige"]
    return z["w"][ziel]


def orte_messen(name, haupt, z, schwebend):
    """Haken `NACH_BILD`: die Rechtecke der Ziele in logischen px relativ
    zum Cadwork-Ersatz (wie `bild()` die schwebenden Fenster einsetzt)."""
    if name not in SZENEN:
        return
    from PyQt6.QtCore import QPoint, QRect
    null = haupt.mapToGlobal(QPoint(0, 0))
    orte = {}
    for _nr, ziel, _anker, _dx, _dy in SZENEN[name][2]:
        wd = _ziel_widget(ziel, z)
        if wd is None or not wd.isVisible():
            raise SystemExit("ABBRUCH %s: %s ist nicht zu sehen" % (name, ziel))
        if wd.isWindow():
            g = wd.frameGeometry()
            p = QPoint(g.left() - null.x(), g.top() - null.y())
        else:
            g = wd.mapToGlobal(QPoint(0, 0))
            p = QPoint(g.x() - null.x(), g.y() - null.y())
        orte[ziel] = QRect(p, wd.size())
    _ORTE[name] = orte


def _naechster_punkt(rect, x, y):
    """Der Punkt des Rechtecks, der (x, y) am naechsten liegt."""
    return (min(max(x, rect[0]), rect[0] + rect[2]),
            min(max(y, rect[1]), rect[1] + rect[3]))


def _webp(bild, pfad):
    """Speichert als WebP unter GRENZE_BYTES (Guete absteigend)."""
    for guete in (90, 84, 78, 70, 60):
        if not bild.save(pfad, "WEBP", guete):
            raise SystemExit("ABBRUCH: WebP nicht schreibbar: %s" % pfad)
        if os.path.getsize(pfad) < GRENZE_BYTES:
            break
    else:
        raise SystemExit("ABBRUCH: %s bleibt ueber %d Bytes"
                         % (pfad, GRENZE_BYTES))
    print("%s  %dx%d  %d KB  (Guete %d)" % (
        pfad, bild.width(), bild.height(), os.path.getsize(pfad) // 1024,
        guete))


def marken_malen(m, marken, orte, k=2.0):
    """Malt die Marken mit dem QPainter `m` in ein Bild mit Massstab `k`
    (das Rohbild ist 200 %): je Marke (Nummer, Ziel, Anker, dx, dy) einen
    feinen Rahmen um das Rechteck `orte[Ziel]` (logische px, QRect), einen
    Pfeil und einen Kreis mit der Nummer. Auch fuer
    `bilder_einrichten.py` (dieselbe Gestalt in beiden Reihen)."""
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
    violett = QColor(FARBE)
    weiss = QColor("#ffffff")
    radius = 13 * k
    rand = 4

    def lokal(x, y):
        return x * k, y * k

    for nr, ziel, anker, dx, dy in marken:
        r = orte[ziel]
        rr = (r.x() - rand, r.y() - rand, r.width() + 2 * rand,
              r.height() + 2 * rand)
        mx, my = r.x() + r.width() / 2.0, r.y() + r.height() / 2.0
        mx, my = {"mitte": (mx, my), "links": (rr[0], my),
                  "rechts": (rr[0] + rr[2], my), "oben": (mx, rr[1]),
                  "unten": (mx, rr[1] + rr[3])}[anker]
        kx, ky = mx + dx, my + dy
        # Rahmen um das Ziel (fein, mit weissem Saum fuer dunklen Grund).
        x0, y0 = lokal(rr[0], rr[1])
        rahmen = QRectF(x0, y0, rr[2] * k, rr[3] * k)
        for farbe, breite in ((weiss, 5.0), (violett, 2.6)):
            m.setPen(QPen(farbe, breite))
            m.setBrush(Qt.BrushStyle.NoBrush)
            m.drawRoundedRect(rahmen, 8 * k / 2, 8 * k / 2)
        # Pfeil vom Kreisrand zum naechsten Punkt des Rahmens.
        px, py = _naechster_punkt(rr, kx, ky)
        lx, ly = lokal(px, py)
        cx, cy = lokal(kx, ky)
        laenge = math.hypot(lx - cx, ly - cy)
        if laenge > radius + 6:
            ux, uy = (lx - cx) / laenge, (ly - cy) / laenge
            sx, sy = cx + ux * radius, cy + uy * radius
            spitze = 9.0 * k / 2
            fx, fy = lx - ux * spitze * 1.6, ly - uy * spitze * 1.6
            kopf = QPainterPath(QPointF(lx, ly))
            kopf.lineTo(fx - uy * spitze, fy + ux * spitze)
            kopf.lineTo(fx + uy * spitze, fy - ux * spitze)
            kopf.closeSubpath()
            for farbe, breite in ((weiss, 5.5), (violett, 2.6)):
                m.setPen(QPen(farbe, breite, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                m.drawLine(QPointF(sx, sy), QPointF(fx, fy))
            m.setPen(QPen(weiss, 2.5))
            m.setBrush(QBrush(violett))
            m.drawPath(kopf)
        # Kreis mit Nummer.
        m.setPen(QPen(weiss, 3.0))
        m.setBrush(QBrush(violett))
        m.drawEllipse(QPointF(cx, cy), radius, radius)
        schrift = QFont("Segoe UI")
        schrift.setPixelSize(int(radius * 1.15))
        schrift.setBold(True)
        m.setFont(schrift)
        m.setPen(weiss)
        m.drawText(QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                   int(Qt.AlignmentFlag.AlignCenter), str(nr))


def bild_beschriften(roh, name, ziel_ordner, pdf_ordner=None):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    ausgabe, (ax, ay, ab, ah), marken = SZENEN[name]
    orte = _ORTE.get(name)
    if not orte:
        raise SystemExit("ABBRUCH: fuer %s wurde nichts gemessen" % name)
    voll = QImage(os.path.join(roh, name))
    if voll.isNull():
        raise SystemExit("ABBRUCH: %s nicht lesbar" % name)
    k = 2.0                                    # das Rohbild ist 200 %
    # Beschriftet wird das GANZE Bild, ausgeschnitten erst danach (Haupt-
    # bild, Vorschau, PDF aus denselben Marken).
    bild = voll.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    m = QPainter(bild)
    m.setRenderHint(QPainter.RenderHint.Antialiasing)
    marken_malen(m, marken, orte, k)
    m.end()

    def ausschnitt(x, y, b, h, breite_px):
        teil = bild.copy(int(x * k), int(y * k), int(b * k), int(h * k))
        return teil.scaledToWidth(int(round(breite_px)),
                                  Qt.TransformationMode.SmoothTransformation)

    pfad = os.path.join(ziel_ordner, ausgabe)
    _webp(ausschnitt(ax, ay, ab, ah, ab * MASSSTAB), pfad)
    vx, vy, vb, vh = VORSCHAU[name]
    _webp(ausschnitt(vx, vy, vb, vh, VORSCHAU_BREITE),
          pfad[:-len(".webp")] + "-klein.webp")
    if pdf_ordner:
        png = os.path.join(pdf_ordner, ausgabe[len("mcp-"):-len(".webp")]
                           + ".png")
        gross = ausschnitt(ax, ay, ab, ah, ab * MASSSTAB_PDF)
        if not gross.convertToFormat(QImage.Format.Format_RGB32).save(png,
                                                                      "PNG"):
            raise SystemExit("ABBRUCH: PNG nicht schreibbar: %s" % png)
        print("%s  %dx%d  %d KB" % (png, gross.width(), gross.height(),
                                    os.path.getsize(png) // 1024))
    return pfad


def main():
    args = sys.argv[1:]
    frei = [a for i, a in enumerate(args)
            if not a.startswith("--")
            and (i == 0 or args[i - 1] not in ("--persoenlich", "--privat",
                                                "--roh", "--pdf"))]
    if not frei:
        raise SystemExit(__doc__)
    ziel = os.path.abspath(frei[0])
    os.makedirs(ziel, exist_ok=True)
    roh = (os.path.abspath(args[args.index("--roh") + 1]) if "--roh" in args
           else tempfile.mkdtemp(prefix="omcad_web_roh_"))
    os.makedirs(roh, exist_ok=True)
    pdf = (os.path.abspath(args[args.index("--pdf") + 1]) if "--pdf" in args
           else None)
    if pdf:
        os.makedirs(pdf, exist_ok=True)
    schnell = tempfile.mkdtemp(prefix="omcad_web_schnell_")
    weiter = []
    for schalter in ("--persoenlich", "--privat"):
        if schalter in args:
            weiter += [schalter, args[args.index(schalter) + 1]]
    B.NACH_BILD = orte_messen
    sys.argv = [os.path.join(HIER, "bilder_rendern.py"), schnell,
                "--ueberblick", roh] + weiter
    rc = B.main()
    if rc:
        return rc
    for name in SZENEN:
        bild_beschriften(roh, name, ziel, pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
