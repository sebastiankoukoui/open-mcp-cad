# -*- coding: utf-8 -*-
"""Open MCP CAD — Einstieg fuer Cadwork, DYNAMISCHER Steckplatz.

VON HAND GEPFLEGT (der Generator kennt ihn und schuetzt ihn; nur die
Kern-Kopie daneben erneuert er).

Der Unterschied zu "Open MCP CAD A" … "F": dieser Eintrag hat KEINEN
festen Port. Wer ihn startet, bekommt den naechsten freien Platz aus dem
Bereich des Kerns (53127-53199) und traegt sich mit seinem Dokumentnamen
in die Registry ein.

Damit haengt die Zahl der Leitungen nicht mehr an der Zahl der
Plugin-Ordner: EIN Menueeintrag, gestartet in so vielen Cadwork-Fenstern,
wie man braucht. Gesucht wird die Instanz danach ueber das DOKUMENT
(OPEN_MCP_CAD_DOC), nicht ueber den Port — "welcher Port bedient Seeblick"
stand vorher nirgends, man musste es sich merken.

Die festen A-F bleiben daneben: auf sie zeigen bestehende
Host-Konfigurationen, und ein fester Port ist leichter zu erklaeren,
solange man nur einen braucht.
"""

import contextlib
import importlib.util
import os
import sys
import time
import traceback

INSTANZ = None                 # None = aus dem Port ableiten
PORT = None                    # None = freien Port suchen
ANZEIGENAME = None             # ergibt sich aus der Kennung
LOG_DATEI = None               # ergibt sich aus der Kennung

ANTRIEB = ""                   # "" = Default aus der Konfiguration

ERWARTETE_KERN_VERSION = "2.19.1"
KERN_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "omcad_bridge_core.py")


DLL_PFADE_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "omcad_dll_pfade.py")


def cadwork_dll_pfade_einrichten():
    """Cadworks DLL-Suchpfade setzen — eine Zeile hier, der Rest im Modul.

    Ohne das findet Cadwork 2026 seine eigene `LxIfcBase.dll` beim BTL-/IFC-
    Laden nicht (Windows-Fehler 126): die Abhaengigkeiten liegen in
    `LxSDK.x64\bin` und `Pclib.x64`, nicht neben der DLL. Aus Kern 2.15
    (Codex-Sitzung 2026-09-15).

    Faellt es aus, ist das kein Grund, den Steckplatz nicht zu starten —
    alles ausser BTL/IFC funktioniert ohne. Deshalb nur eine Meldung.
    """
    try:
        return modul_laden("omcad_dll_pfade",
                           DLL_PFADE_PFAD).cadwork_dll_suchpfade_einrichten()
    except Exception as exc:                              # noqa: BLE001
        meldung("[Open MCP CAD] DLL-Pfade nicht gesetzt: %s" % exc)
        return None


def meldung(text):
    """Nach stderr, falls es eines gibt — in Cadwork ist `sys.stderr` None.

    Rueckmeldung Kollege zu 0.1.0 (2026-09-26): ein nacktes
    `sys.stderr.write` warf dort AttributeError und verdeckte den echten
    Fehler. JEDE Ausgabe im Einstieg geht deshalb hier durch.
    """
    with contextlib.suppress(Exception):
        sys.stderr.write(text + "\n")


DASHBOARD_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "omcad_a_dashboard.py")

def modul_laden(name, pfad):
    """Laedt ein Modul IMMER frisch von der Platte, unter eigenem Namen.

    Nicht `import …`: Python legt Module in `sys.modules` ab, und Cadwork
    behaelt seinen Python-Prozess ueber die ganze Sitzung. Ein einfacher
    Import haette zwei Folgen, die beide weh tun:
      * nach einem Plugin-Update laeuft beim naechsten Start weiter der ALTE
        Stand aus dem Speicher — man muesste Cadwork jedesmal neu starten;
      * zwei Steckplaetze in einem Prozess teilten sich dasselbe Modul.

    EINE Funktion fuer Kern UND DLL-Pfade. Der zweite Lader war eine Kopie
    davon und hat den Einstieg ueber die Anweisungsgrenze des Gates
    gebracht (gemessen 47 gegen 45). Zwei Kopien sind auch ohne diese
    Grenze eine zuviel — und die Grenze zu erhoehen waere die falsche
    Reaktion: sie ist der Grund, warum die Einstiege duenn BLEIBEN.
    """
    spec = importlib.util.spec_from_file_location(name, pfad)
    if spec is None:
        raise ImportError("Modul nicht gefunden: %s" % pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def kern_laden():
    """Der gemeinsame Bridge-Kern, frisch von der Platte."""
    return modul_laden("omcad_bridge_core_dyn", KERN_PFAD)


def dashboard_laden():
    """Das Dashboard, frisch von der Platte — wie der Kern.

    Derselbe Grund wie bei `kern_laden`: Cadwork behaelt seinen
    Python-Prozess, ein normaler Import wuerde nach einem Update
    weiter die alte Fassung aus dem Speicher nehmen. Der ZUSTAND (das
    offene Dock) ueberlebt trotzdem, weil er an der QApplication
    haengt und nicht am Modul.
    """
    return modul_laden("omcad_a_dashboard_dyn", DASHBOARD_PFAD)


def konfiguration(kern):
    # Alles offen lassen: der Kern sucht den Port und leitet Kennung,
    # Anzeigename und Logdatei daraus ab (`serve` -> `kennung_fuer`).
    cfg = kern.Konfiguration()
    if ANTRIEB:
        cfg.antrieb = ANTRIEB
    return cfg


def serve():
    """Zeigt das Dashboard und verbindet — ueber das Dashboard, nie daneben.

    EIN Klick genuegt (2026-09-22): `oeffnen(..., verbinden=True)`
    baut das Dock und verbindet ueber `_verbinden`, denselben Weg wie der
    Knopf. Dort wird der Steckplatz atomar reserviert — der erste freie,
    oder genau der im Dock gewaehlte, nie ein anderer —, und ein schon
    laufender Dienst bleibt, wie er ist.

    KEIN RUECKFALL auf `kern.serve`. Der alte Rueckfall startete den Dienst
    an allem vorbei: ohne Reservierung, mit SO_REUSEADDR und ohne einen
    laufenden Dienst zu erkennen. Faellt das Dashboard aus, bleibt der
    Steckplatz aus, und das wird gemeldet.
    """
    try:
        cadwork_dll_pfade_einrichten()
        kern = kern_laden()
        if kern.CORE_VERSION != ERWARTETE_KERN_VERSION:
            meldung("[Open MCP CAD] Achtung: Kern %s aus %s, erwartet %s"
                    % (kern.CORE_VERSION, KERN_PFAD, ERWARTETE_KERN_VERSION))
        return dashboard_laden().oeffnen(kern_laden, konfiguration,
                                         verbinden=True)
    except Exception as exc:                              # noqa: BLE001
        startfehler_melden(exc)


# Die Umgebungsvariable ist NUR fuer die Gates (Temp statt Public).
START_LOG = (os.environ.get("OPEN_MCP_CAD_START_LOG")
             or r"C:\Users\Public\OpenMcpCad_start.log")


def startfehler_melden(exc):
    """Ein Startfehler muss SICHTBAR sein — und darf selbst nie werfen.

    Die Arbeit (Logdatei, dann PyQt6 / PyQt5 / Windows-MessageBox) macht
    `omcad_startfehler.py`, das nur die Standardbibliothek braucht.
    Rueckmeldung 2026-09-24 und Kollege zu 0.1.0 (2026-09-26): ein Klick
    ohne jede Wirkung, weil stderr None war und der Dialog PyQt6 verlangte.

    Laesst sich das Hilfsmodul nicht laden (unvollstaendig kopiert) oder
    wirft es doch, steht wenigstens der Traceback in der Logdatei — der
    Notnagel unten.
    """
    try:
        return modul_laden("omcad_startfehler", os.path.join(
            os.path.dirname(KERN_PFAD), "omcad_startfehler.py")).melden(
                exc, os.path.abspath(__file__), START_LOG)
    except Exception as fehler:                           # noqa: BLE001
        with contextlib.suppress(Exception), \
                open(START_LOG, "a", encoding="utf-8") as fh:
            fh.write("=== %s  Start nicht moeglich, Hilfsmodul fehlt "
                     "oder warf (%r)\n"
                     "Python %s\n%s\nPlugin %s\n\n%s\n" % (
                         time.strftime("%Y-%m-%d %H:%M:%S"), fehler,
                         sys.version, sys.executable,
                         os.path.abspath(__file__),
                         "".join(traceback.format_exception(
                             type(exc), exc, exc.__traceback__))))


# Manche Loader rufen main() auf, Cadwork fuehrt die Datei als __main__ aus.
main = serve

if __name__ == "__main__":
    serve()
