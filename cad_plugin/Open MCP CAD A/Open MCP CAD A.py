# -*- coding: utf-8 -*-
"""Open MCP CAD A — Einstieg fuer Cadwork (Steckplatz A, Port 53127).

    ################################################################
    #  A-ONLY UI PROTOTYPE — bewusst vom Generator abweichend.     #
    #  `plugins_generieren.py --pruefen` meldet A deshalb als      #
    #  abweichend. Das ist erwartet. B, C und D sind unberuehrt,   #
    #  und der gemeinsame Kern ebenfalls.                          #
    #  Rueckbau: siehe docs/PROTOTYP_A_dashboard.md                #
    ################################################################

Der einzige Unterschied zur erzeugten Fassung: statt `kern.serve(cfg)` wird
das A-eigene Dashboard geoeffnet (`omcad_a_dashboard.oeffnen`), und es
verbindet gleich — ueber seinen eigenen Weg `_verbinden`, wie der
ausgerollte Einstieg. Der Kern selbst ist NICHT angefasst; er wird mit
`cfg.fenster = False` benutzt, damit nicht zusaetzlich das alte Fenster
aufgeht.

Aendern statt dessen: cad_plugin/_core/omcad_bridge_core.py
Neu erzeugen:        python scripts/plugins_generieren.py
                     (WUERDE DIESEN PROTOTYP UEBERSCHREIBEN)

Ordner und Datei heissen "Open MCP CAD A" — Cadwork verlangt Ordnername ==
Dateiname und zeigt genau diesen Ordnernamen im Plugin-Menue an (gemessen
2026-08-04; <Name> aus plugin_info.xml wird dafuer NICHT benutzt). Das
Icon daneben kommt aus der icon.svg im selben Ordner.
"""

import contextlib
import importlib.util
import os
import sys
import time
import traceback

INSTANZ = "A"
PORT = 53127
ANZEIGENAME = "Open MCP CAD A"
LOG_DATEI = r"C:\Users\Public\OpenMcpCad_A.log"

ANTRIEB = ""          # "" = Default aus der Konfiguration

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
        meldung("[Open MCP CAD %s] DLL-Pfade nicht gesetzt: %s"
                % (INSTANZ, exc))
        return None


def meldung(text):
    """Nach stderr, falls es eines gibt — in Cadwork ist `sys.stderr` None.

    Rueckmeldung Kollege zu 0.1.0 (2026-09-26): ein nacktes
    `sys.stderr.write` warf dort AttributeError und verdeckte den echten
    Fehler. JEDE Ausgabe im Einstieg geht deshalb hier durch.
    """
    with contextlib.suppress(Exception):
        sys.stderr.write(text + "\n")


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
    return modul_laden("omcad_bridge_core_%s" % INSTANZ, KERN_PFAD)


def konfiguration(kern):
    cfg = kern.Konfiguration(instanz=INSTANZ, port=PORT,
                             anzeigename=ANZEIGENAME, log_datei=LOG_DATEI)
    if ANTRIEB:
        cfg.antrieb = ANTRIEB
    return cfg


DASHBOARD_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "omcad_a_dashboard.py")


def dashboard_laden():
    """Laedt das A-Dashboard frisch von der Platte — wie den Kern.

    Denselben Grund wie bei `kern_laden`: Cadwork behaelt seinen
    Python-Prozess, ein normaler Import wuerde nach einem Update weiter die
    alte Fassung aus dem Speicher nehmen. Der ZUSTAND (das offene Dock)
    ueberlebt trotzdem, weil er an der QApplication haengt und nicht am
    Modul.

    Ueber `modul_laden` wie alles andere — hier stand eine eigene Kopie
    davon, und die Kopie war es, die den Einstieg an seine Grenze gebracht
    hat (43 von 44 Anweisungen, 2026-09-22).
    """
    return modul_laden("omcad_a_dashboard_%s" % INSTANZ, DASHBOARD_PFAD)


def serve():
    """Zeigt das Dashboard und verbindet — ueber das Dashboard, nie daneben.

    Kehrt sofort zurueck — Cadwork behaelt seinen Hauptthread. Verbunden
    wird in `oeffnen(..., verbinden=True)` ueber `_verbinden`, denselben Weg
    wie der Knopf "Verbinden".

    KEIN RUECKFALL auf `kern.serve` (2026-09-22). Der alte Rueckfall
    startete den Dienst an allem vorbei: ohne Reservierung, mit
    SO_REUSEADDR, ohne einen laufenden Dienst zu erkennen. Faellt das
    Dashboard aus, bleibt der Steckplatz aus, und das wird gemeldet.

    ALLES im try, auch Kern und DLL-Pfade: vorher lagen sie davor, und ein
    Fehler beim Laden des Kerns ging ungemeldet an Cadwork.
    """
    try:
        cadwork_dll_pfade_einrichten()
        kern = kern_laden()
        if kern.CORE_VERSION != ERWARTETE_KERN_VERSION:
            meldung("[Open MCP CAD A] Achtung: Kern %s aus %s, erwartet %s"
                    % (kern.CORE_VERSION, KERN_PFAD, ERWARTETE_KERN_VERSION))
        return dashboard_laden().oeffnen(kern_laden, konfiguration,
                                         verbinden=True)
    except Exception as exc:                      # noqa: BLE001
        startfehler_melden(exc)


# Die Umgebungsvariable ist NUR fuer die Gates (Temp statt Public).
START_LOG = (os.environ.get("OPEN_MCP_CAD_START_LOG")
             or r"C:\Users\Public\OpenMcpCad_start.log")


def startfehler_melden(exc):
    """Ein Startfehler muss SICHTBAR sein — und darf selbst nie werfen.

    Wie im ausgerollten Einstieg: die Arbeit macht `omcad_startfehler.py`
    (Logdatei, dann PyQt6 / PyQt5 / Windows-MessageBox). Fehlt es oder
    wirft es doch, schreibt
    der Notnagel unten wenigstens den Traceback in die Logdatei.
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
