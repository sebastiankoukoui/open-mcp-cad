#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt die Open-MCP-CAD-Plugins aus EINER Quelle — und prueft sie.

Warum es das gibt
-----------------
Bis 2026-08-04 lagen vier fast identische Bridge-Implementierungen im Repo
(je ~756 Zeilen). Sie unterschieden sich in genau einer Zeile (`PORT`) —
gepflegt werden mussten sie trotzdem vierfach. Ab jetzt gilt:

  * Die Logik steht EINMAL in `cad_plugin/_core/omcad_bridge_core.py`.
  * Jeder Plugin-Ordner bekommt davon eine byte-identische Kopie
    (Cadworks Plugin-Loader laedt aus dem Plugin-Ordner; ein gemeinsamer
    Import ueber Ordnergrenzen hinweg waere eine unnoetige Wette).
  * Der Einstieg `McpBridge*.py` ist wenige Zeilen lang und setzt nur
    Instanz, Port, Anzeigename und Logdatei.

Damit ist "Port, Instanz-ID, Anzeigename und Logdatei sind Konfiguration"
kein Vorsatz, sondern nachpruefbar: `--pruefen` faellt durch, sobald eine
Kopie abweicht.

Aufruf
------
    python scripts/plugins_generieren.py            # erzeugen
    python scripts/plugins_generieren.py --pruefen  # nur pruefen
"""

import hashlib
import os
import sys
import xml.etree.ElementTree as ET

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo
PLUGIN_DIR = os.path.join(REPO, "cad_plugin")
KERN_QUELLE = os.path.join(PLUGIN_DIR, "_core", "omcad_bridge_core.py")
KERN_NAME = "omcad_bridge_core.py"

# Steckplatz -> (Ordner, Port)
#
# Der ORDNERNAME ist der Menueeintrag: gemessen am 2026-08-04 in Cadwork
# 2026 steht im Plugin-Menue der Ordnername, nicht <Name> aus
# plugin_info.xml. Cadwork verlangt ausserdem Ordnername == Dateiname.
#
# Leerzeichen sind erlaubt — nachgewiesen gestartet am 2026-08-04:
# "OpenMcpCad_A" um 22:05:35 und "Open MCP CAD D" um 22:08:38,
# beide mit eigener Logdatei auf "Bereit". (Eine fruehere Messung von mir
# behauptete das Gegenteil; sie war schlicht zu frueh gemacht, bevor der
# Steckplatz ueberhaupt gestartet war.)
# Der Nutzer hat sich fuer Leerzeichen entschieden — das ist der Name aus dem
# Auftrag. Zu wissen bleibt: ein Dateiname mit Leerzeichen ist KEIN
# gueltiger Python-Modulname. Cadwork fuehrt die Datei aus, deshalb geht
# es; wuerde ein kuenftiges Cadwork sie importieren, braeche es hier
# zuerst — dann auf Unterstriche zurueck.
ERSTER_PORT = 53127
ANZAHL_STECKPLAETZE = 6          # A-F; Begruendung in connect_client.py
STECKPLAETZE = [(chr(ord("A") + i), "Open MCP CAD %s" % chr(ord("A") + i),
                 ERSTER_PORT + i) for i in range(ANZAHL_STECKPLAETZE)]

# --- Der dynamische Steckplatz --------------------------------------------
#
# EIN Ordner, EIN Menueeintrag — aber ohne festen Port. Wer ihn startet,
# bekommt den naechsten freien Platz aus dem Bereich des Kerns und traegt
# sich mit seinem Dokumentnamen in die Registry ein. Man startet ihn in so
# vielen Cadwork-Fenstern, wie man braucht; die Zahl der Leitungen haengt
# nicht mehr an der Zahl der Ordner.
#
# Der Nutzer hat zweimal nach "unendlich" gefragt (2026-08-15 und 2026-09-20).
# Die Antwort war beide Male "mehr Ordner" — das war die falsche Achse.
#
# Die festen A-F bleiben daneben bestehen: auf sie zeigen bestehende
# Host-Konfigurationen, und ein fester Port ist leichter zu erklaeren,
# solange man nur einen braucht.
DYNAMISCHER_ORDNER = "Open MCP CAD"

# --- Was von Hand gepflegt wird und deshalb NICHT ueberschrieben wird -----
# A ist der UI-Prototyp: sein Einstieg oeffnet das Dashboard statt kern.serve.
# Das steht seit je in A's eigenem Docstring — der Generator wusste nur
# nichts davon und haette es bei jedem Lauf zerstoert. CLAUDE.md verlangt
# aber genau diesen Lauf nach jeder Kern-Aenderung; die Falle stand also
# scharf im dokumentierten Weg.
#
# Die Icons sind seit 2026-09-24 NICHT mehr handgepflegt: alle Ordner, auch
# A und der dynamische, bekommen ihre icon.svg aus ICON_BILD (s. u.).
# Vorher lagen in A und im dynamischen Ordner Handkopien — ein neues Bild
# haette sie nie erreicht.
#
# Der Kern selbst ist NICHT geschuetzt: die vier Kopien MUESSEN bytegleich
# bleiben, das ist der ganze Sinn des Generators. Geschuetzt sind nur die
# Dateien, die den Steckplatz beschreiben, nicht die, die ihn ausmachen.
HANDGEPFLEGT = {
    "A": ("{ordner}.py",),
    # Der dynamische Steckplatz: sein Einstieg setzt INSTANZ und PORT
    # bewusst auf None, und sein XML nennt keinen Port. Nichts davon laesst sich aus der Vorlage bilden,
    # die je Steckplatz einen Buchstaben und eine Zahl einsetzt.
    # Der dynamische Steckplatz traegt seit 2026-09-21 die ganze
    # Oberflaeche: Dashboard, Chat, Hinweise, Verbindungs-Client
    # und das DLL-Modul. Er ist der Steckplatz, der AUSGEROLLT
    # wird — die benannten A-F bleiben im Repo, weil sie den
    # Bitgleichheits-Nachweis des Kerns tragen, aber im
    # Cadwork-Menue soll nur EIN Eintrag stehen.
    None: ("{ordner}.py", "plugin_info.xml",
           "omcad_a_dashboard.py", "omcad_a_chat.py",
           "omcad_a_anbieter.py", "omcad_a_lokal.py", "omcad_a_symbole.py",
           "omcad_a_hinweise.py", "omcad_verbindungen_client.py",
           "omcad_dll_pfade.py", "omcad_startfehler.py", "omcad_qt.py",
           "omcad_a_update.py"),
}

#: Die Dateien, die `erzeugen()` je Ordner schreibt (oder, wenn
#: HANDGEPFLEGT, nur vergleicht). `erzeugen()` bricht ab, wenn seine
#: Eintraege davon abweichen — so ist diese Liste die Quelle, gegen die
#: `test_paket` T1b den ausgerollten Ordner und DATEIEN abgleicht.
ERZEUGT = ("{ordner}.py", KERN_NAME, "plugin_info.xml", "icon.svg")

#: Alles, was in cad_plugin/ liegen soll: die festen Steckplaetze und der
#: dynamische. Die Schleife unten laeuft ueber DIESE Liste — sonst faende
#: der Kern-Abgleich den dynamischen Ordner nicht, und seine Kopie
#: veraltete still bei jeder Kern-Aenderung.
ALLE_ORDNER = STECKPLAETZE + [(None, DYNAMISCHER_ORDNER, None)]

SPRACHEN = ["German", "English", "French", "Italian", "Spanish", "Czech",
            "Finnish", "Russian", "Polish", "Romanian", "Norwegian",
            "Chinese", "Portuguese", "Estonian", "Japanese"]

EINSTIEG_VORLAGE = '''# -*- coding: utf-8 -*-
"""Open MCP CAD {instanz} — Einstieg fuer Cadwork (Steckplatz {instanz}, Port {port}).

ERZEUGT — NICHT VON HAND AENDERN.
Aendern statt dessen: cad_plugin/_core/omcad_bridge_core.py
Neu erzeugen:        python scripts/plugins_generieren.py

Diese Datei enthaelt absichtlich keine Logik. Sie sagt nur, WELCHER
Steckplatz das hier ist; alles andere steht im gemeinsamen Kern neben ihr.

Ordner und Datei heissen "{modul}" — Cadwork verlangt Ordnername ==
Dateiname und zeigt genau diesen Ordnernamen im Plugin-Menue an (gemessen
2026-08-04; <Name> aus plugin_info.xml wird dafuer NICHT benutzt). Das
Icon daneben kommt aus der icon.svg im selben Ordner.
"""

import importlib.util
import os
import sys

INSTANZ = "{instanz}"
PORT = {port}
ANZEIGENAME = "Open MCP CAD {instanz}"
LOG_DATEI = r"C:\\Users\\Public\\OpenMcpCad_{instanz}.log"

ANTRIEB = "{antrieb}"          # "" = Default aus der Konfiguration

ERWARTETE_KERN_VERSION = "{kern_version}"
KERN_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "omcad_bridge_core.py")


def kern_laden():
    """Laedt den Kern IMMER frisch von der Platte, unter eigenem Modulnamen.

    Nicht `import omcad_bridge_core`: Python legt Module in `sys.modules`
    ab, und Cadwork behaelt seinen Python-Prozess ueber die ganze Sitzung.
    Ein einfacher Import haette zwei Folgen, die beide weh tun:
      * nach einem Plugin-Update laeuft beim naechsten Start weiter der ALTE
        Kern aus dem Speicher — man muesste Cadwork jedesmal neu starten;
      * zwei Steckplaetze in einem Prozess wuerden sich dasselbe Modul teilen.
    """
    name = "omcad_bridge_core_%s" % INSTANZ
    spec = importlib.util.spec_from_file_location(name, KERN_PFAD)
    if spec is None:
        raise ImportError("Kern nicht gefunden: %s" % KERN_PFAD)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def konfiguration(kern):
    # INSTANZ/PORT = None heisst: der Kern sucht sich beim Start einen
    # freien Port und leitet die Kennung daraus ab. Dann sind auch
    # Anzeigename und Logdatei erst danach bekannt — sie bleiben hier leer.
    if INSTANZ is None:
        return kern.Konfiguration()
    cfg = kern.Konfiguration(instanz=INSTANZ, port=PORT,
                             anzeigename=ANZEIGENAME, log_datei=LOG_DATEI)
    if ANTRIEB:
        cfg.antrieb = ANTRIEB
    return cfg


def serve():
    """Startet Steckplatz {instanz}. Kehrt erst zurueck, wenn er beendet ist."""
    kern = kern_laden()
    if kern.CORE_VERSION != ERWARTETE_KERN_VERSION:
        sys.stderr.write(
            "[Open MCP CAD {instanz}] Achtung: Kern %s aus %s, erwartet %s\\n"
            % (kern.CORE_VERSION, KERN_PFAD, ERWARTETE_KERN_VERSION))
    return kern.serve(konfiguration(kern))


# Manche Loader rufen main() auf, Cadwork fuehrt die Datei als __main__ aus.
main = serve

if __name__ == "__main__":
    serve()
'''

BESCHREIBUNG_DE = """
Open MCP CAD {instanz} - Verbindung zwischen diesem Cadwork-Dokument und
Open MCP CAD.

Nach dem Start ist die Verbindung "Bereit". Der Zustand (Bereit, Liest
Modell, Bearbeitet Modell, Pausiert, Stoerung) ist jederzeit im Fenster
"Open MCP CAD Verbindungen" ablesbar; dort wird auch pausiert und sicher beendet.

Solange die Verbindung nur "Bereit" ist, bleibt Cadwork normal bedienbar.
Waehrend ein Auftrag laeuft ("Liest Modell" / "Bearbeitet Modell"), ist die
Oberflaeche blockiert - "Pausieren" gibt sie nach dem laufenden Auftrag
wieder frei. Beenden ueber "Open MCP CAD Verbindungen" oder ueber den
Open-MCP-CAD-Server (shutdown); waehrend eines Auftrags nur "nach Auftrag
beenden".

Technische Details: TCP 127.0.0.1:{port}, MCP-Bridge-Protokoll {protokoll},
Log C:\\Users\\Public\\OpenMcpCad_{instanz}.log
"""

BESCHREIBUNG_EN = """
Open MCP CAD {instanz} - link between this Cadwork document and Open MCP CAD.

Once started the connection reports "Ready". Its state (Ready, Reading
model, Modifying model, Paused, Fault) is visible at any time in the
"Open MCP CAD Verbindungen" window, which is also where you pause it or stop it
safely.

While the connection is merely "Ready", Cadwork stays usable. While a job
runs, the user interface is blocked - "Pause" releases it once the current
job finishes. Stop it from "Open MCP CAD Verbindungen" or via the Open MCP CAD server
(shutdown); while a job runs, only "stop after current job".

Technical details: TCP 127.0.0.1:{port}, MCP bridge protocol {protokoll},
log C:\\Users\\Public\\OpenMcpCad_{instanz}.log
"""


# Je Steckplatz eine eigene Plakettenfarbe — sie ist im Cadwork-Menue das
# Einzige, was A von F unterscheidet. Deutlich verschiedene Farbtoene, auch
# fuer Rot-Gruen-Schwaeche: wer zwei Cadwork-Fenster offen hat, soll auf
# einen Blick sehen, in welchem er gerade ist.
ICON_FARBE = {"A": "#1565c0", "B": "#2e7d32", "C": "#e65100", "D": "#6a1b9a",
              "E": "#00838f", "F": "#ad1457"}

# Antrieb je Steckplatz — leer heisst: Default aus dem Kern, und der ist
# seit dem Nachweis an Steckplatz D (2026-08-04 23:15) 'qtimer'. Dieser
# Haken bleibt, um im Zweifel EINEN Steckplatz abweichend zu fahren, etwa
# zum Vergleich: {"C": "mainthread"}.
ANTRIEB_JE_STECKPLATZ = {}

# Das Zeichen im Plugin-Menue — EINE Quelle fuer alle Ordner, relativ zum
# Repo. Seit 2026-09-24 das "M im Netz" (vorher ein gezeichneter Wuerfel).
#
# Cadwork liest laut Doku eine Icon.png ODER Icon.svg aus dem Plugin-Ordner,
# empfohlen ~30 px. Hier bleibt es bei icon.svg mit eingebettetem PNG:
#   * SVG ist das Format, das schon ausgerollt ist — eine zusaetzliche
#     icon.png daneben liesse offen, welche Cadwork nimmt, und beim
#     Ausrollen (darueber kopieren, nichts loeschen) bliebe die alte liegen.
#   * Die Plakette A-F kommt als Vektor darueber, ohne je Steckplatz ein
#     eigenes Bild zu pflegen.
#   * Eingebettete PNGs in icon.svg liefen schon im Vorgaenger-Plugin in
#     Cadwork. Qt (PyQt6 6.11, QIcon aus der SVG) zeichnet die 64-px-Fassung
#     bei 16-72 px sauberer als die 16- oder 32-px-Fassung — verglichen am
#     gerenderten Bild, 2026-09-24. Deshalb die 64er, auch fuers Menue.
ICON_BILD = "assets/icon-64.png"

ICON_VORLAGE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="48" height="48" viewBox="0 0 48 48" version="1.1"
     xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
  <title>{titel}</title>
  <image x="0" y="0" width="48" height="48"
         preserveAspectRatio="xMidYMid meet"
         xlink:href="data:image/png;base64,{daten}"/>
{plakette}</svg>
"""

# Steckplatz-Kennung oben rechts. Ohne diese Plakette waeren die Eintraege
# im Menue nicht zu unterscheiden.
PLAKETTE = """  <circle cx="40" cy="8" r="6.5" fill="{farbe}" stroke="#ffffff"
          stroke-width="1.2"/>
  <text x="40" y="11" font-family="Segoe UI, Arial, sans-serif"
        font-size="8.5" font-weight="700" fill="#ffffff"
        text-anchor="middle">{instanz}</text>
"""


def icon_bauen(instanz):
    """Erzeugt icon.svg fuer einen Steckplatz.

    Cadwork zeigt im Plugin-Menue die `icon.svg` aus dem Plugin-Ordner an —
    so machen es auch die mitgelieferten Plugins. Ein Eintrag in
    plugin_info.xml ist dafuer nicht noetig, die Datei genuegt.

    Das Bild kommt aus ICON_BILD und wird als PNG eingebettet. Die festen
    Steckplaetze bekommen ihren Buchstaben als Plakette in die Ecke.
    instanz=None ist der dynamische Steckplatz: er hat keinen Buchstaben
    und deshalb keine Plakette.

    Fehlt das Bild, bricht der Generator ab — ein stiller Rueckfall auf
    ein anderes Zeichen wuerde ausgerollt, ohne dass es jemand merkt.
    """
    import base64
    pfad = os.path.join(REPO, ICON_BILD.replace("/", os.sep))
    if not os.path.isfile(pfad):
        raise SystemExit("Icon-Bild fehlt: %s" % pfad)
    with open(pfad, "rb") as fh:
        daten = base64.b64encode(fh.read()).decode("ascii")
    if instanz is None:
        return ICON_VORLAGE.format(titel="Open MCP CAD", daten=daten,
                                   plakette="")
    return ICON_VORLAGE.format(
        titel="Open MCP CAD %s" % instanz, daten=daten,
        plakette=PLAKETTE.format(instanz=instanz, farbe=ICON_FARBE[instanz]))


def kern_version():
    """Liest CORE_VERSION aus der Kernquelle, ohne sie zu importieren."""
    with open(KERN_QUELLE, "r", encoding="utf-8") as fh:
        for zeile in fh:
            if zeile.startswith("CORE_VERSION"):
                return zeile.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("CORE_VERSION nicht in %s gefunden" % KERN_QUELLE)


def protokoll_version():
    with open(KERN_QUELLE, "r", encoding="utf-8") as fh:
        for zeile in fh:
            if zeile.startswith("PROTOKOLL_VERSION"):
                return zeile.split("=", 1)[1].strip()
    return "2"


def xml_bauen(instanz, port, protokoll):
    # Dynamischer Steckplatz: handgepflegte XML, dieses Soll wird nie
    # geschrieben — nur gebildet.
    if instanz is None:
        instanz, port = "", 0
    """Erzeugt plugin_info.xml — **zeichengenau im Format des Originals**.

    Warum von Hand statt mit ElementTree: die erste Fassung hat das XML mit
    `ET.tostring` erzeugt. Formal gueltig, aber an drei Stellen anders als
    die Datei, die Cadwork seit Mai anstandslos gelesen hat:
      * `<Text language="Italian" />` statt `<Text language="Italian"/>`
      * Beschreibungstext ohne `<![CDATA[ ]]>`
      * andere Einrueckung
    Am 2026-08-04 zeigte Cadwork danach im Menue weiter den alten Namen,
    obwohl das neue XML 34 Minuten vor dem Cadwork-Start dort lag — was
    genau dazu passt, dass ein strenger Parser die Datei verwirft und auf
    den Ordnernamen zurueckfaellt. Deshalb hier: so wenig Abweichung vom
    bewaehrten Original wie moeglich, geaendert werden nur Name, Text,
    Version und Datum.
    """
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<PluginInfo>',
              '    <Version>2.0.0.0</Version>',
              '    <Date>2026-08-04</Date>',
              '    <Author>Sebastian Koukoui</Author>',
              '    <Name>']
    for sprache in SPRACHEN:
        if sprache in ("German", "English", "French"):
            zeilen.append('      <Text language="%s">Open MCP CAD %s</Text>'
                          % (sprache, instanz))
        else:
            zeilen.append('      <Text language="%s"/>' % sprache)
    zeilen.append('    </Name>')
    zeilen.append('    <Description>')
    for sprache in SPRACHEN:
        if sprache == "German":
            text = BESCHREIBUNG_DE
        elif sprache == "English":
            text = BESCHREIBUNG_EN
        else:
            zeilen.append('      <Text language="%s"/>' % sprache)
            continue
        zeilen.append('      <Text language="%s">' % sprache)
        zeilen.append('<![CDATA[')
        zeilen.append(text.format(instanz=instanz, port=port,
                                  protokoll=protokoll).strip())
        zeilen.append(']]>')
        zeilen.append('      </Text>')
    zeilen.append('    </Description>')
    zeilen.append('</PluginInfo>')
    return "\n".join(zeilen) + "\n"


def sha(pfad):
    with open(pfad, "rb") as fh:
        return hashlib.sha256(_normiert(fh.read())).hexdigest()


def _normiert(daten):
    """Zeilenenden vereinheitlichen.

    Das Repo steht auf `* text=auto` bei `core.autocrlf=true`: in Git liegt
    LF, auf der Platte CRLF. Ohne diese Normierung meldete der Vergleich
    nach jedem frischen `clone` alle zwoelf Dateien als abweichend — und
    der Gleichheitsnachweis waere wertlos, weil er staendig anschlaegt.
    (Die alten vier Kopien waren genau deshalb schon uneinheitlich: A lag
    mit LF im Repo, B/C/D mit CRLF.)
    """
    return daten.replace(b"\r\n", b"\n")


def erzeugen(pruefen_nur=False):
    if not os.path.isfile(KERN_QUELLE):
        raise SystemExit("Kernquelle fehlt: %s" % KERN_QUELLE)
    with open(KERN_QUELLE, "rb") as fh:
        kern_bytes = fh.read()
    kv = kern_version()
    pv = protokoll_version()
    kern_hash = hashlib.sha256(_normiert(kern_bytes)).hexdigest()

    print("Kern      : %s" % os.path.relpath(KERN_QUELLE, REPO))
    print("Version   : %s (Protokoll %s)" % (kv, pv))
    print("SHA-256   : %s\n" % kern_hash[:16])

    abweichungen = []
    for instanz, ordner, port in ALLE_ORDNER:
        ziel_dir = os.path.join(PLUGIN_DIR, ordner)
        einstieg = os.path.join(ziel_dir, ordner + ".py")
        kern_kopie = os.path.join(ziel_dir, KERN_NAME)
        xml_pfad = os.path.join(ziel_dir, "plugin_info.xml")

        soll_einstieg = EINSTIEG_VORLAGE.format(
            instanz=instanz, port=port, modul=ordner, kern_version=kv,
            antrieb=ANTRIEB_JE_STECKPLATZ.get(instanz, ""))
        soll_xml = xml_bauen(instanz, port, pv)

        eintraege = [
            (einstieg, soll_einstieg.encode("utf-8")),
            (kern_kopie, kern_bytes),
            (xml_pfad, soll_xml.encode("utf-8")),
            (os.path.join(ziel_dir, "icon.svg"),
             icon_bauen(instanz).encode("utf-8")),
        ]
        if sorted(os.path.basename(e[0]) for e in eintraege) != sorted(
                v.format(ordner=ordner) for v in ERZEUGT):
            raise SystemExit("ERZEUGT passt nicht zu erzeugen(): %s"
                             % [os.path.basename(e[0]) for e in eintraege])
        geschuetzt = {v.format(ordner=ordner)
                      for v in HANDGEPFLEGT.get(instanz, ())}
        geaendert = 0
        bewahrt = []
        for pfad, soll in eintraege:
            ist = None
            if os.path.isfile(pfad):
                with open(pfad, "rb") as fh:
                    ist = fh.read()
            if ist is not None and _normiert(ist) == _normiert(soll):
                continue
            if os.path.basename(pfad) in geschuetzt and ist is not None:
                # Abweichend UND handgepflegt: melden, aber stehen lassen.
                bewahrt.append(os.path.basename(pfad))
                continue
            geaendert += 1
            abweichungen.append(os.path.relpath(pfad, REPO))
            if not pruefen_nur:
                if not os.path.isdir(ziel_dir):
                    os.makedirs(ziel_dir)
                with open(pfad, "wb") as fh:
                    fh.write(soll)

        print("  %s  %-18s %-12s ->  cad_plugin/%s/  (%s)"
              % ("=" if not geaendert else "*",
                 ordner,
                 ("Port %d" % port) if port else "freier Port",
                 ordner,
                 "unveraendert" if not geaendert
                 else "%d Datei(en) abweichend" % geaendert))
        if bewahrt:
            print("       handgepflegt, NICHT ueberschrieben: %s"
                  % ", ".join(sorted(bewahrt)))

    print()
    if pruefen_nur:
        if abweichungen:
            print("ABWEICHUNG in %d Datei(en):" % len(abweichungen))
            for a in abweichungen:
                print("   -", a)
            print("\nNeu erzeugen mit: python scripts/plugins_generieren.py")
            return 1
        print("OK — alle %d Ordner stimmen mit der Quelle ueberein (%d feste Steckplaetze + der dynamische)."
              % (len(ALLE_ORDNER), len(STECKPLAETZE)))
        return 0

    if abweichungen:
        print("Geschrieben: %d Datei(en)" % len(abweichungen))
        for a in abweichungen:
            print("   +", a)
    else:
        print("Nichts zu tun — alles schon aktuell.")

    # Gegenprobe: sind alle Kern-Kopien wirklich byte-identisch?
    #
    # ⚠ Hier stand bis 2026-09-20 `STECKPLAETZE` statt `ALLE_ORDNER` — der
    # dynamische Ordner waere also nie geprueft worden, und eine veraltete
    # Kopie dort haette weiterhin "alle identisch" gemeldet. Das ist
    # dieselbe Fehlerklasse, die E und F fuenf Wochen lang tot liess: ein
    # Pruefer, der seine eigene, kuerzere Liste fuehrt.
    hashes = {}
    for _instanz, ordner, _port in ALLE_ORDNER:
        p = os.path.join(PLUGIN_DIR, ordner, KERN_NAME)
        hashes[ordner] = sha(p)
    if len(set(hashes.values())) != 1:
        print("FEHLER: Kern-Kopien unterscheiden sich:", hashes)
        return 1
    if set(hashes.values()) != {kern_hash}:
        print("FEHLER: Kopien weichen von der Quelle ab.")
        return 1
    print("Gegenprobe: alle %d Kern-Kopien identisch (%s…)"
          % (len(ALLE_ORDNER), kern_hash[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(erzeugen(pruefen_nur="--pruefen" in sys.argv))
