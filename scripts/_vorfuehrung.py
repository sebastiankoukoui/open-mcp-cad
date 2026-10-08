#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vier Attrappen-Steckplaetze auf Testports — zum Ausprobieren der Oberflaeche.

Startet echte Kern-Instanzen (gleiche Zustandsmaschine, gleiches Protokoll)
mit untergeschobenem cwapi3d. Damit laesst sich "Open MCP CAD Verbindungen"
vorfuehren und pruefen, OHNE Cadwork und ohne die echten Ports 53127-53130
anzufassen.

    python scripts/_vorfuehrung.py
    # in einer zweiten Konsole:
    OPEN_MCP_CAD_PORTS=A=53911,B=53912,C=53913,D=53914 \\
        python scripts/verbindungen.py

Vorgefuehrt wird: A bereit, B in einem langen Schreibauftrag, C pausiert,
D gar nicht gestartet ("Aus").
"""

import importlib.util
import os
import sys
import tempfile
import threading
import time
import types

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo
KERN_PFAD = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")

# Die Bridge leitet stdout waehrend eines Auftrags prozessweit um
# (contextlib.redirect_stdout). Weil hier absichtlich ein Dauerauftrag laeuft,
# muessen unsere eigenen Ausgaben aufs echte stdout gehen.
ECHT_STDOUT = sys.stdout


def sag(*teile):
    print(*teile, file=ECHT_STDOUT, flush=True)


PORTS = {"A": 53911, "B": 53912, "C": 53913, "D": 53914}
DOKUMENTE = {"A": "Haus_Seeblick.3d", "B": "Fenster_Test.3d",
             "C": "Tragwerk_OG.3d", "D": "—"}


def kern_laden(instanz):
    """Eigenes Modulobjekt je Instanz — sonst teilen sie sich die Attrappe."""
    spec = importlib.util.spec_from_file_location("kern_%s" % instanz, KERN_PFAD)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def attrappen_setzen(dokument):
    uc = types.ModuleType("utility_controller")
    uc.get_3d_file_name = lambda: dokument
    sys.modules["utility_controller"] = uc
    ec = types.ModuleType("element_controller")
    ec.get_all_identifiable_element_ids = lambda: list(range(1234))
    sys.modules["element_controller"] = ec


def start(instanz, kern):
    cfg = kern.Konfiguration(instanz=instanz, port=PORTS[instanz],
                             log_datei=os.path.join(tempfile.gettempdir(),
                                                    "omcad_vorfuehrung.log"))
    dienst = kern.Verbindungsdienst(cfg)
    threading.Thread(target=kern.serve, args=(cfg, dienst),
                     name="Vorfuehrung-%s" % instanz, daemon=True).start()
    for _ in range(200):
        if dienst.zustand in ("ready", "paused"):
            break
        time.sleep(0.02)
    return cfg, dienst


def main():
    import connect_client as cc
    # Die Attrappe ist prozessweit — der Dokumentname muss also VOR dem
    # jeweiligen Start passen. Reihenfolge: A, B, C.
    dienste = {}
    for instanz in ("A", "B", "C"):
        attrappen_setzen(DOKUMENTE[instanz])
        kern = kern_laden(instanz)
        dienste[instanz] = start(instanz, kern)
        # Dokumentname im Cache einfrieren: Auffrischen abschalten, sonst
        # ueberschreibt die naechste Attrappe alle Caches.
        dienste[instanz][0].dok_auffrischen_s = 0
        sag("  Open MCP CAD %s  Port %d  %s"
              % (instanz, PORTS[instanz], DOKUMENTE[instanz]))
    sag("  Open MCP CAD D  Port %d  (absichtlich nicht gestartet)"
          % PORTS["D"])

    os.environ["OPEN_MCP_CAD_PORTS"] = ",".join("%s=%d" % (i, p)
                                           for i, p in PORTS.items())
    cc.STECKPLAETZE = cc._ports_aus_umgebung()
    cc.PORT_VON_INSTANZ = dict(cc.STECKPLAETZE)

    cc.pausieren("C")
    threading.Thread(target=lambda: cc.anfrage(
        PORTS["B"], "execute_cwapi3d",
        {"code": "import time\ntime.sleep(600)\nresult = 1",
         "description": "Fensterwand Sued erzeugen",
         "access_mode": "write", "client_label": "Claude Code",
         "client_id": "sitzung-vorfuehrung"}, timeout=900), daemon=True).start()
    time.sleep(0.6)

    sag("\nOPEN_MCP_CAD_PORTS=%s" % os.environ["OPEN_MCP_CAD_PORTS"])
    sag("Uebersicht starten mit:")
    sag("  OPEN_MCP_CAD_PORTS=%s python scripts/verbindungen.py"
          % os.environ["OPEN_MCP_CAD_PORTS"])
    sag("\nMomentaufnahme:\n")
    for d in cc.alle_status():
        sag("  " + cc.zeile(d))
    sag("\nLaeuft — Strg-C beendet alles.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sag("\nbeendet")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, HIER)
    sys.exit(main())
