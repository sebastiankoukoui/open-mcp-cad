# -*- coding: utf-8 -*-
"""Cadworks DLL-Suchpfade einrichten — damit BTL/IFC ueberhaupt laedt.

WARUM EIN EIGENES MODUL. Diese ~70 Zeilen standen in Kern 2.15 direkt im
Plugin-Einstieg. Der Einstieg hat aber eine Aufgabe und nur eine: sagen,
WELCHER Steckplatz das hier ist. Gemessen bringt ihn dieser Block auf 78
AST-Anweisungen; die Gate-Grenze liegt bei 45, und sie ist nicht
willkuerlich — sie ist der Grund, warum die Einstiege nachpruefbar duenn
bleiben. Die naheliegende Reaktion waere, die Grenze zu erhoehen. Das waere
die falsche.

Hier ist der Block also ein Modul, und im Einstieg steht eine Zeile.

DER BEFUND SELBST stammt aus der Codex-Sitzung vom 2026-09-15 (03:33Z):

    "LxIfcBase.dll ist vorhanden, aber ohne die zugehoerigen Suchpfade
     scheitert Windows mit Fehler 126 ... Mit Pclib.x64, LxSDK.x64\bin und
     dessen dlls laedt exakt die von Cadwork verwendete Variante"

Cadwork 2026 kann `LxIfcBase.dll` installiert haben und sie beim BTL-/IFC-
Laden trotzdem nicht finden: `Base.dll` liegt im LxSDK-Unterordner,
`Qt6Core.dll` in `Pclib.x64`. Nur den DLL-Ordner einzutragen genuegt nicht.

Die Handles leben auf `sys` und ueberstehen das frische Laden des
Einstiegs — sonst waere nach jedem Plugin-Klick alles wieder weg.

AUSSERHALB VON CADWORK tut das Modul nichts: `_cadwork_exe_root()` sucht
`EXE_20xx` im Pfad von `sys.executable` und liefert sonst None. Es ist
damit gefahrlos importierbar, auch in den Gates.
"""

import ctypes
import os
import sys


def _cadwork_exe_root():
    """Findet EXE_20xx ausschliesslich aus Cadworks eigenem Programm-Pfad."""
    pfad = os.path.abspath(sys.executable or "")
    ordner = os.path.dirname(pfad)
    while ordner and os.path.dirname(ordner) != ordner:
        if os.path.basename(ordner).upper().startswith("EXE_20"):
            return ordner
        ordner = os.path.dirname(ordner)
    return None


def cadwork_dll_suchpfade_einrichten(exe_root=None):
    """Laedt Cadworks IFC-Basis samt Abhaengigkeiten aus demselben Release.

    Cadwork 2026 Build 317 kann ``LxIfcBase.dll`` zwar installiert haben,
    sie beim spaeteren BTL-/IFC-Laden aber trotzdem nicht finden: ``Base.dll``
    liegt im LxSDK-Unterordner und ``Qt6Core.dll`` in ``Pclib.x64``. Nur den
    DLL-Ordner einzutragen reicht deshalb nicht. Die Handles leben auf
    ``sys`` und ueberstehen das frische Laden des Plugin-Einstiegs.
    """
    vorhanden = getattr(sys, "_omcad_cadwork_ifc_dll", None)
    if vorhanden is not None:
        return getattr(sys, "_omcad_cadwork_ifc_pfad", None)

    wurzel = os.path.abspath(exe_root or _cadwork_exe_root() or "")
    if not wurzel or not os.path.isdir(wurzel):
        return None

    varianten = (
        (os.path.join(wurzel, "LxSDK.x64", "bin"),
         os.path.join(wurzel, "Pclib.x64")),
        (os.path.join(wurzel, "Lexocad.x64"), None),
    )
    letzter_fehler = None
    for basis, qt_basis in varianten:
        dll_ordner = os.path.join(basis, "dlls")
        dll_pfad = os.path.join(dll_ordner, "LxIfcBase.dll")
        suchpfade = [pfad for pfad in (qt_basis, basis, dll_ordner)
                     if pfad and os.path.isdir(pfad)]
        if not os.path.isfile(dll_pfad):
            continue
        neue_handles = []
        try:
            for pfad in suchpfade:
                neue_handles.append(os.add_dll_directory(pfad))
            dll = ctypes.WinDLL(dll_pfad)
        except (AttributeError, OSError) as exc:
            letzter_fehler = exc
            for handle in reversed(neue_handles):
                try:
                    handle.close()
                except OSError:
                    pass
            continue
        handles = getattr(sys, "_omcad_cadwork_dll_dirs", None)
        if handles is None:
            handles = []
            sys._omcad_cadwork_dll_dirs = handles
        handles.extend(neue_handles)
        sys._omcad_cadwork_ifc_dll = dll
        sys._omcad_cadwork_ifc_pfad = dll_pfad
        return dll_pfad

    if letzter_fehler is not None:
        sys.stderr.write("[Open MCP CAD] Cadwork-DLL-Pfade konnten nicht "
                         "initialisiert werden: %s\n" % letzter_fehler)
    return None
