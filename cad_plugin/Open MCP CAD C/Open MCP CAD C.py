# -*- coding: utf-8 -*-
"""Open MCP CAD C — Einstieg fuer Cadwork (Steckplatz C, Port 53129).

ERZEUGT — NICHT VON HAND AENDERN.
Aendern statt dessen: cad_plugin/_core/omcad_bridge_core.py
Neu erzeugen:        python scripts/plugins_generieren.py

Diese Datei enthaelt absichtlich keine Logik. Sie sagt nur, WELCHER
Steckplatz das hier ist; alles andere steht im gemeinsamen Kern neben ihr.

Ordner und Datei heissen "Open MCP CAD C" — Cadwork verlangt Ordnername ==
Dateiname und zeigt genau diesen Ordnernamen im Plugin-Menue an (gemessen
2026-08-04; <Name> aus plugin_info.xml wird dafuer NICHT benutzt). Das
Icon daneben kommt aus der icon.svg im selben Ordner.
"""

import importlib.util
import os
import sys

INSTANZ = "C"
PORT = 53129
ANZEIGENAME = "Open MCP CAD C"
LOG_DATEI = r"C:\Users\Public\OpenMcpCad_C.log"

ANTRIEB = ""          # "" = Default aus der Konfiguration

ERWARTETE_KERN_VERSION = "2.19.1"
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
    """Startet Steckplatz C. Kehrt erst zurueck, wenn er beendet ist."""
    kern = kern_laden()
    if kern.CORE_VERSION != ERWARTETE_KERN_VERSION:
        sys.stderr.write(
            "[Open MCP CAD C] Achtung: Kern %s aus %s, erwartet %s\n"
            % (kern.CORE_VERSION, KERN_PFAD, ERWARTETE_KERN_VERSION))
    return kern.serve(konfiguration(kern))


# Manche Loader rufen main() auf, Cadwork fuehrt die Datei als __main__ aus.
main = serve

if __name__ == "__main__":
    serve()
