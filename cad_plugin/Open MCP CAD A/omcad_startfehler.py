# -*- coding: utf-8 -*-
"""Open MCP CAD — ein Startfehler wird SICHTBAR, auch ohne Qt und stderr.

VON HAND GEPFLEGT und bytegleich in "Open MCP CAD" (ausgerollt) und
"Open MCP CAD A" (geprueft) — `test_offline` A3d vergleicht die Bytes,
A3f misst das Verhalten ueber beide Einstiege.

Rueckmeldung Kollege zu 0.1.0 (2026-09-26): in einem Cadwork 2025
(Python 3.12, Qt 5 / PyQt5) tat der Klick auf den Menueeintrag nichts
Sichtbares. Zwei Gruende uebereinander:

  * `sys.stderr` ist in Cadwork `None`. Das `sys.stderr.write(...)` im
    Einstieg warf `AttributeError` und verdeckte die echte Ausnahme.
  * Der Rueckfall-Dialog importierte PyQt6 — das es dort nicht gibt. Also
    kam gar nichts.

Deshalb liegt die Meldung hier, in EINEM Modul, das nur die
Standardbibliothek braucht, und KEIN Schritt darf werfen:

  1. Logdatei (Zeitstempel, Python, sys.executable, Plugin-Pfad, Qt-Stand,
     voller Traceback) — immer zuerst, sie ist das, was bleibt.
  2. Dialog: PyQt6; nur wenn PyQt6 FEHLT, PyQt5 (nie zwei Qt-Generationen
     in einem Prozess laden); ohne QApplication oder ohne Qt ein Windows-
     `MessageBoxW` ueber ctypes; geht auch das nicht, bleibt die Logdatei.

Seit 2026-10-10 laeuft Open MCP CAD auch mit PyQt5 (Cadwork 2025, Qt-Schicht
`omcad_qt.py`). PyQt5 ist deshalb kein Grund mehr fuer "braucht Cadwork
2026"; nur OHNE jedes Qt sagt der Dialog, dass Qt fehlt. Das Startlog nennt
den Qt-Stand (`PYQT_VERSION_STR`/`QT_VERSION_STR`, Wunsch des Maintainers
nach dem ersten Lauf in Cadwork 2025).

Fehlt dieses Modul selbst (unvollstaendig kopiert), schreibt der Einstieg
die Logdatei mit einem eigenen, kleinen Notnagel.
"""

import datetime
import importlib
import importlib.util
import os
import sys
import traceback

TITEL = "Open MCP CAD"
# Waechst die Datei darueber, wird sie zu `<log>.1` (die vorige Generation
# ersetzt), und eine neue beginnt — sie soll die letzten Fehler zeigen,
# nicht die Platte fuellen.
LOG_GRENZE = 256 * 1024
# MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST: sonst geht die Box hinter
# dem Cadwork-Fenster auf und sieht aus wie ein haengendes Cadwork.
MB_STIL = 0x30 | 0x10000 | 0x40000


def ausgabe(text):
    """Nach stderr, WENN es eines gibt — in Cadwork ist `sys.stderr` None."""
    try:
        strom = sys.stderr
        if strom is not None:
            strom.write(text.rstrip("\n") + "\n")
    except Exception:                                     # noqa: BLE001
        pass


def _vorhanden(paket):
    """'ja' / 'nein' / Grund — sucht nur, importiert nicht."""
    try:
        return "ja" if importlib.util.find_spec(paket) is not None else "nein"
    except Exception as exc:                              # noqa: BLE001
        return "unklar (%s)" % type(exc).__name__


def _qt_stand():
    """'PyQt5 5.15.11 / Qt 5.15.2 (geladen)' — oder warum nicht. Wirft nie.

    Eine schon geladene Bindung zuerst; sonst nach derselben Regel wie der
    Dialog (PyQt6, nur wenn es FEHLT PyQt5) und nur deren QtCore.
    """
    try:
        for name in ("PyQt6", "PyQt5"):
            core = sys.modules.get(name + ".QtCore")
            if core is not None:
                return "%s %s / Qt %s (geladen)" % (
                    name, getattr(core, "PYQT_VERSION_STR", "?"),
                    getattr(core, "QT_VERSION_STR", "?"))
        for name in ("PyQt6", "PyQt5"):
            try:
                core = importlib.import_module(name + ".QtCore")
            except ImportError:
                continue
            return "%s %s / Qt %s" % (
                name, getattr(core, "PYQT_VERSION_STR", "?"),
                getattr(core, "QT_VERSION_STR", "?"))
        return "kein Qt"
    except Exception as exc:                              # noqa: BLE001
        return "unklar (%s)" % type(exc).__name__


def log_schreiben(exc, plugin, log):
    """Haengt den Fehler an die Logdatei. -> True, wenn geschrieben. Wirft nie."""
    try:
        zeilen = [
            "=== %s  Open MCP CAD: Start nicht moeglich"
            % datetime.datetime.now().isoformat(" ", "seconds"),
            "Python      %s" % sys.version.replace("\n", " "),
            "Programm    %s" % sys.executable,
            "Plugin      %s" % plugin,
            "PyQt6 %s, PyQt5 %s" % (_vorhanden("PyQt6"), _vorhanden("PyQt5")),
            "Qt          %s" % _qt_stand(),
            "",
            "".join(traceback.format_exception(type(exc), exc,
                                               exc.__traceback__)),
            "",
        ]
        try:
            # Zu gross: die alte Datei wird zu `<log>.1` (eine vorige
            # Generation bleibt), die neue beginnt leer.
            if os.path.getsize(log) > LOG_GRENZE:
                os.replace(log, log + ".1")
        except OSError:
            pass
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("\n".join(zeilen))
        return True
    except Exception:                                     # noqa: BLE001
        return False


def meldetext(exc, qt_fehlt, log, log_ok):
    """Der Text fuer den Dialog — fuer Laien, die technische Zeile zuletzt.

    `qt_fehlt`: weder PyQt6 noch PyQt5 (seit 2026-10-10 laeuft das Plugin
    mit beiden, PyQt5 allein ist kein Grund mehr).
    """
    if qt_fehlt:
        kopf = ("Open MCP CAD braucht Qt (PyQt6 aus Cadwork 2026 oder PyQt5 "
                "aus Cadwork 2025). Diese Cadwork-Version hat keins davon.")
    else:
        kopf = "Open MCP CAD konnte nicht starten und ist NICHT verbunden."
    if log_ok:
        fuss = "Details: %s" % log
    else:
        fuss = "Die Logdatei %s liess sich nicht schreiben." % log
    return "%s\n\n%s\n\n(%s: %s)" % (kopf, fuss, type(exc).__name__, exc)


def _qt_widgets():
    """-> (QtWidgets-Modul oder None, Weg, Qt fehlt ganz?). Wirft nie.

    PyQt5 nur, wenn PyQt6 FEHLT: in einem Qt-6-Cadwork noch Qt 5 zu laden,
    waere ein neues Risiko, um einen Fehler zu melden.
    """
    try:
        return importlib.import_module("PyQt6.QtWidgets"), "qt6", False
    except ImportError:
        pass
    except Exception:                                     # noqa: BLE001
        return None, None, False
    try:
        return importlib.import_module("PyQt5.QtWidgets"), "qt5", False
    except Exception:                                     # noqa: BLE001
        return None, None, True


def _win32_dialog(text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, TITEL, MB_STIL)


def melden(exc, plugin, log):
    """Startfehler melden. -> "qt6", "qt5", "win32" oder None. Wirft nie.

    None heisst: kein Dialog ging auf, nur die Logdatei (falls sie sich
    schreiben liess).
    """
    try:
        # Die Datei ZUERST — vor stderr und vor jedem Dialog (A3f prueft
        # beim Aufruf jedes Dialogs, dass sie schon da ist).
        log_ok = log_schreiben(exc, plugin, log)
        ausgabe("[Open MCP CAD] Start nicht moeglich (%s: %s) - NICHT "
                "verbunden. Details: %s" % (type(exc).__name__, exc, log))
        widgets, weg, qt_fehlt = _qt_widgets()
        text = meldetext(exc, qt_fehlt, log, log_ok)
        if widgets is not None:
            try:
                # Ohne QApplication ginge ein Dialog nicht sauber schief,
                # sondern braeche den Prozess ab — dann lieber Windows.
                if widgets.QApplication.instance() is not None:
                    widgets.QMessageBox.warning(None, TITEL, text)
                    return weg
            except Exception:                             # noqa: BLE001
                pass
        try:
            _win32_dialog(text)
            return "win32"
        except Exception:                                 # noqa: BLE001
            return None
    except Exception:                                     # noqa: BLE001
        return None
