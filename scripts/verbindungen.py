#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Startet "Open MCP CAD Verbindungen" — Fenster, sonst Browser.

    python scripts/verbindungen.py            # Fenster
    python scripts/verbindungen.py --web      # Browser
    python scripts/verbindungen.py --text     # einmalig Text

Die Reihenfolge ist bewusst: das eigenstaendige Fenster ist die
Standardoberflaeche, der Browser die Rueckfallebene, die Textausgabe der
Notnagel fuer eine Konsole ohne Bildschirm.
"""

import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
if HIER not in sys.path:
    sys.path.insert(0, HIER)


def main(argv):
    if "--text" in argv:
        import connect_client as cc
        print("Open MCP CAD Verbindungen (Momentaufnahme)\n")
        for d in cc.alle_status():
            print(cc.zeile(d))
            if d.get("hinweis"):
                print("      %s" % d["hinweis"])
        return 0

    if "--web" not in argv:
        try:
            import verbindungen_tk
            return verbindungen_tk.main()
        except SystemExit:
            raise
        except ImportError as exc:
            print("Fenster nicht moeglich (%s) — weiche auf den Browser aus." % exc)
        except Exception as exc:                      # noqa: BLE001
            print("Fenster konnte nicht geoeffnet werden (%s) — "
                  "weiche auf den Browser aus." % exc)

    import verbindungen_web
    return verbindungen_web.main([a for a in argv if a != "--web"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
