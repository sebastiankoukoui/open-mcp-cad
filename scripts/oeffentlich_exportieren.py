#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schreibt den oeffentlichen Stand in einen Klon des GitHub-Repos.

    git clone https://github.com/sebastiankoukoui/open-mcp-cad <ziel>
    python scripts/oeffentlich_exportieren.py <ziel>
    # danach im <ziel>: git add -A, commit, push

Alles im Ziel ausser `.git` wird ersetzt durch die eingecheckten Dateien
dieses Repos (`git ls-files`) ohne NICHT_OEFFENTLICH. Danach durchsucht
`paket_bauen.pruefen` das Ziel: ein Benutzerpfad oder ein Treffer aus
`persoenlich.txt` bricht ab, ebenso eine Spur privater Teile aus der
lokalen `privat_spuren.txt` (das erzeugte Wissen unter
`paket_bauen.SPUREN_AUSGENOMMEN` wird nur gemeldet). Fehlt eine der beiden
lokalen Dateien (oder steht kein Muster darin), bricht der Export ab:
eine leere Liste saehe wie eine bestandene Pruefung aus. Ist eine der
beiden eingecheckt, bricht er ab, bevor er etwas kopiert. Committet und
gepusht wird hier NICHTS.

WARUM EIN EIGENES REPO und kein zweiter Remote: die History dieses Repos
enthaelt Arbeitsnotizen, lokale Pfade und Namen. Das oeffentliche Repo
bekommt nur Staende, die diesen Export bestanden haben.

Exportiert wird der ARBEITSSTAND der eingecheckten Dateien; der Aufruf von
der Kommandozeile verlangt deshalb einen sauberen Stand (nichts
Uncommittetes), damit jeder oeffentliche Stand einem Commit hier entspricht.
"""

import os
import shutil
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
if HIER not in sys.path:
    sys.path.insert(0, HIER)

import paket_bauen as P                                     # noqa: E402

# Arbeitsnotizen: fuer Agenten und den Maintainer, nicht fuer die Welt.
NICHT_OEFFENTLICH = ("CLAUDE.md", "AGENTS.md", "docs/UEBERGABE_")


class ExportFehler(Exception):
    pass


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=True).stdout


def oeffentliche_dateien():
    return [rel for rel in _git("ls-files").splitlines()
            if rel.strip() and not rel.startswith(NICHT_OEFFENTLICH)]


def exportieren(ziel, muster=None, sauber_verlangen=True, spuren=None):
    """-> (Anzahl Dateien, Commit dieses Repos). `muster`/`spuren`: Namens-
    bzw. Spuren-Muster, None = aus persoenlich.txt bzw. privat_spuren.txt."""
    ziel = os.path.abspath(ziel)
    if muster is None:
        muster = P.persoenliche_muster()
    if spuren is None:
        spuren = P.private_spuren_liste()
    if not muster:
        raise ExportFehler("keine Namensmuster in %s — ohne sie prueft der "
                           "Export nichts" % P.PERSOENLICH)
    if not spuren:
        raise ExportFehler("keine Spuren-Muster in %s — ohne sie prueft der "
                           "Export nichts" % P.PRIVAT_SPUREN)
    if not os.path.isdir(os.path.join(ziel, ".git")):
        raise ExportFehler("%s ist kein Git-Arbeitsordner" % ziel)
    if os.path.normcase(ziel) == os.path.normcase(REPO):
        raise ExportFehler("das Ziel ist dieses Repo selbst")
    if sauber_verlangen and _git("status", "--porcelain",
                                 "--untracked-files=no").strip():
        raise ExportFehler("uncommittete Aenderungen — erst committen")

    dateien = oeffentliche_dateien()
    # Die lokalen Musterdateien selbst nie (sie sagen, was privat ist).
    eingecheckt = [rel for rel in dateien if rel.rsplit("/", 1)[-1].lower()
                   in {n.lower() for n in P.LOKALE_DATEIEN}]
    if eingecheckt:
        raise ExportFehler("lokale Musterdatei eingecheckt (nichts "
                           "exportiert): %s" % ", ".join(eingecheckt))

    for eintrag in os.listdir(ziel):
        if eintrag == ".git":
            continue
        p = os.path.join(ziel, eintrag)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    for rel in dateien:
        z = os.path.join(ziel, rel)
        os.makedirs(os.path.dirname(z), exist_ok=True)
        shutil.copyfile(os.path.join(REPO, rel), z)

    # Erweiterungen (OPEN_MCP_CAD_ERWEITERUNGEN) nie im Export (2026-10-01).
    erw = P.erweiterungen_im_paket(ziel)
    if erw:
        raise ExportFehler("Erweiterung im Export (nichts committet): %s"
                           % ", ".join(erw[:10]))
    harte, weiche = P.pruefen(ziel, muster)
    if harte or weiche:
        raise ExportFehler("Persoenliches im Export (nichts committet): %s"
                           % ", ".join((harte + weiche)[:10]))
    lokal = P.lokale_dateien_in(ziel)
    if lokal:
        raise ExportFehler("lokale Musterdatei im Export (nichts "
                           "committet): %s" % ", ".join(lokal[:10]))
    # Spuren privater Teile (Muster lokal, Ausnahme in paket_bauen).
    funde, _aus = P.private_spuren(ziel, spuren)
    if funde:
        raise ExportFehler("Spuren privater Teile (privat_spuren.txt) im "
                           "Export (nichts committet): %s"
                           % ", ".join(funde[:10]))
    return len(dateien), _git("rev-parse", "--short", "HEAD").strip()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        n, commit = exportieren(sys.argv[1])
    except ExportFehler as exc:
        print("ABBRUCH: %s" % exc)
        return 1
    print("%d Dateien aus %s nach %s — geprueft, nichts Persoenliches."
          % (n, commit, os.path.abspath(sys.argv[1])))
    P.spuren_melden(os.path.abspath(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
