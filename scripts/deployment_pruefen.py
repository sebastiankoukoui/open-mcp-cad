#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueft, ob die Plugins im Cadwork-Userprofil dem Repo-Stand entsprechen.

Die Frage "laeuft in Cadwork ueberhaupt das, was hier im Repo steht?" ist
sonst nur zu erraten. Hier wird sie byteweise beantwortet — je Datei.

    python scripts/deployment_pruefen.py
    python scripts/deployment_pruefen.py --jahr 2025

Exit 0 = identisch, 1 = Abweichung oder fehlend. Es wird NICHTS kopiert;
das Ausrollen bleibt ein ausdruecklicher, eigener Schritt.
"""

import hashlib
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo
PLUGIN_DIR = os.path.join(REPO, "cad_plugin")

# AUSGEROLLT WIRD GENAU EIN ORDNER (Entscheid 2026-09-21: "EIN
# Eintrag wie in 2.15"). Er hat keinen Buchstaben und keinen festen Port —
# er reserviert sich beim Verbinden einen freien und traegt sich mit seinem
# Dokumentnamen in die Registry ein.
#
# Hier stand eine Liste A-D. Sie war schon vor diesem Entscheid falsch: der
# Generator erzeugt SECHS benannte Steckplaetze, E und F wurden also nie
# geprueft. Ein Pruefer, der eine eigene, kuerzere Liste fuehrt, altert
# lautlos — dieselbe Fehlerklasse, die E und F fuenf Wochen lang gar nicht
# startbar machte.
ORDNER = [(None, "Open MCP CAD")]

# Die benannten Steckplaetze bleiben im REPO (sie tragen den
# Bitgleichheits-Nachweis des Kerns), werden aber NICHT ausgerollt. Liegen
# sie trotzdem im Benutzerprofil, steht jedes Plugin mehrfach im Menue.
NICHT_AUSROLLEN = ["Open MCP CAD %s" % c for c in "ABCDEF"]
# Ordner aus der Zeit vor 2026-08-04. Liegen sie noch im Userprofil, steht
# jedes Plugin doppelt im Cadwork-Menue.
ALTE_ORDNER = (["McpBridge", "McpBridgeB", "McpBridgeC", "McpBridgeD",
                "OpenMcpCad_A", "OpenMcpCad_B",
                "OpenMcpCad_C", "OpenMcpCad_D",
                # Der Name vor dem 2026-09-20. Liegt er noch im
                # Benutzerprofil, steht die Bruecke ZWEIMAL im Menue — und
                # zwar in zwei Fassungen, die sich nicht gleichen.
                "LignoAI Connect", "LignoAI Connect A", "LignoAI Connect B",
                "LignoAI Connect C", "LignoAI Connect D"]
               + NICHT_AUSROLLEN)
# Die Oberflaeche gehoert dazu. Ohne diese fuenf pruefte der Abgleich die
# Dateien nicht, die das Plugin ueberhaupt bedienbar machen — und die
# Zaehlung "ueberzaehlig" haette sie als Fremdkoerper gemeldet.
DATEIEN = ("{ordner}.py", "omcad_bridge_core.py", "plugin_info.xml",
           "icon.svg", "omcad_a_dashboard.py", "omcad_a_chat.py",
           "omcad_a_anbieter.py", "omcad_a_lokal.py", "omcad_a_symbole.py",
           "omcad_a_hinweise.py", "omcad_verbindungen_client.py",
           "omcad_dll_pfade.py", "omcad_startfehler.py")

# Dateien, die NUR im Benutzerprofil leben und bewusst nicht im Repo
# stehen: sie gelten je Rechner. `projektordner.txt` sagt dem Chat, in
# welchem Projekt er arbeiten soll — ein Pfad also, der auf einem anderen
# Rechner falsch waere. Im Repo stand so etwas schon einmal (drei fest
# verdrahtete Benutzerpfade im Dashboard), und bei der Umbenennung sind
# sie mitgewandert. `wissensordner.txt` (seit 2026-09-22) ebenso: welches
# Fachwissen der Chat-Server einhaengt (OPEN_MCP_CAD_KNOWLEDGE).
# `ANLEITUNG.pdf` (seit 2026-09-29) legt der Installer aus dem Paket
# daneben (gebaut von paket_bauen, nicht im Repo); der Chat oeffnet sie.
NUR_LOKAL = {"projektordner.txt", "wissensordner.txt", "ANLEITUNG.pdf"}


def sha(pfad):
    """Hash ueber normierte Zeilenenden.

    Das Repo steht auf `* text=auto` (CRLF auf der Platte); ein Byte-fuer-
    Byte-Vergleich wuerde sonst schon an den Zeilenenden scheitern, obwohl
    Python beides gleich ausfuehrt.
    """
    with open(pfad, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def main(argv):
    jahr = "2026"
    if "--jahr" in argv:
        jahr = argv[argv.index("--jahr") + 1]
    api = (r"C:\Users\Public\Documents\cadwork\userprofil_%s\3d\API.x64" % jahr)
    print("Repo      : %s" % PLUGIN_DIR)
    print("Userprofil: %s\n" % api)
    if not os.path.isdir(api):
        print("FEHLER: Userprofil-Ordner existiert nicht.")
        return 1

    abweichungen = []
    for instanz, ordner in ORDNER:
        zeilen = []
        for vorlage in DATEIEN:
            name = vorlage.format(ordner=ordner)
            quelle = os.path.join(PLUGIN_DIR, ordner, name)
            ziel = os.path.join(api, ordner, name)
            if not os.path.isfile(quelle):
                zustand, grund = "FEHLT im Repo", name
            elif not os.path.isfile(ziel):
                zustand, grund = "FEHLT im Userprofil", name
            elif sha(quelle) != sha(ziel):
                zustand, grund = "ABWEICHUNG", name
            else:
                zustand, grund = "ok", name
            if zustand != "ok":
                abweichungen.append("%s/%s: %s" % (ordner, name, zustand))
            zeilen.append("%s %s" % ("=" if zustand == "ok" else "*", grund))
        print("  Open MCP CAD %s  (%s)" % (instanz, ordner))
        for z in zeilen:
            print("      %s" % z)

    # Alte Dateien, die nach dem Umbau uebrig sein koennten
    reste = []
    for _instanz, ordner in ORDNER:
        ziel_dir = os.path.join(api, ordner)
        if not os.path.isdir(ziel_dir):
            continue
        erlaubt = {v.format(ordner=ordner) for v in DATEIEN}
        erlaubt |= NUR_LOKAL
        for name in os.listdir(ziel_dir):
            if name not in erlaubt and not name.startswith("__"):
                reste.append("%s/%s" % (ordner, name))

    veraltet = [o for o in ALTE_ORDNER if os.path.isdir(os.path.join(api, o))]
    print()
    if veraltet:
        print("ALTE Plugin-Ordner noch im Userprofil — jedes Plugin erscheint")
        print("dadurch DOPPELT im Cadwork-Menue:")
        for v in veraltet:
            print("   -", v)
        print()
        abweichungen.append("alte Ordner: %s" % ", ".join(veraltet))
    if reste:
        print("Ueberzaehlige Dateien im Userprofil (aus einem frueheren Stand):")
        for r in reste:
            print("   -", r)
        print()
    if abweichungen:
        print("NICHT AUSGEROLLT — %d Abweichung(en):" % len(abweichungen))
        for a in abweichungen:
            print("   -", a)
        print("\nAusrollen: siehe docs/OPEN_MCP_CAD_CONNECT.md, Abschnitt 10.")
        return 1
    print("OK — Userprofil entspricht byteweise dem Repo-Stand.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
