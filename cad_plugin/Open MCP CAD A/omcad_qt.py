# -*- coding: utf-8 -*-
"""Open MCP CAD — EINE Qt-Schicht fuer PyQt6 (Cadwork 2026) und PyQt5 (2025).

VON HAND GEPFLEGT und bytegleich in "Open MCP CAD" (ausgerollt) und
"Open MCP CAD A" (geprueft) — `test_offline` A3d vergleicht die Bytes.

Anlass (gemessen vom Maintainer auf einem Laptop, 2026-10-10): Cadwork 3D
2025 bringt Python 3.12.7 und PyQt5 mit, kein PyQt6. Das Dock importierte
ueberall `PyQt6.*` und startete dort nicht (ModuleNotFoundError in
`_zustand`).

WIE MAN ES BENUTZT. Die UI-Module importieren nie `PyQt6`/`PyQt5` direkt,
sondern

    from omcad_qt.QtCore import Qt, QTimer
    from omcad_qt.QtGui import QShortcut          # in Qt 5 aus QtWidgets

Dafuer traegt dieses Modul beim Laden `omcad_qt.QtCore`, `.QtGui`,
`.QtWidgets` und (wenn vorhanden) `.QtSvg` in `sys.modules` ein — Python
findet ein Untermodul dort, ohne nach einem Paket zu fragen. Geladen wird
es vom Dashboard (`_qt_schicht`) bzw. von jedem UI-Modul selbst
(`_qt_schicht` dort), frisch von der Platte; es haelt keinen Zustand ausser
der Wahl der Bindung, und die bleibt im Prozess dieselbe (siehe `waehlen`).

WELCHE BINDUNG (`waehlen`, dieselbe Regel im Kern: `_qt_bindung`):
  1. eine schon GELADENE gewinnt (zuerst PyQt6, dann PyQt5) — Cadwork hat
     seine QApplication mit genau der gebaut; die andere Generation dazu zu
     laden waere zwei Qt in einem Prozess;
  2. sonst PyQt6, wenn es sich importieren laesst;
  3. sonst PyQt5;
  4. sonst nichts: `BINDUNG` ist None, `FEHLER` sagt warum, die Untermodule
     fehlen, und `laden()` wirft ImportError mit diesem Text.

WAS GEGLAETTET WIRD (nur was das Dock braucht, gemessen an PyQt5 5.15.11 /
Qt 5.15.2 und PyQt6 6.11.0 / Qt 6.11.0):
  * `QAction`, `QActionGroup`, `QShortcut`, `QFileSystemModel` liegen in
    Qt 6 in QtGui, in Qt 5 in QtWidgets — die Schicht bietet sie in BEIDEN
    an (eigene Modulobjekte, die echten PyQt5-Module bleiben unberuehrt).
  * voll qualifizierte Enums (`Qt.AlignmentFlag.AlignLeft`,
    `QEvent.Type.Resize`, `QSizePolicy.Policy.Ignored` …) gehen in PyQt5
    5.15 schon (gemessen) — nichts zu tun. Aelter als 5.15 ist NICHT
    geprueft.
  * `wert(enum)`: PyQt6-Enums tragen `.value`, PyQt5-Enums SIND int.
  * `global_punkt(e)` / `punkt(e)`: Qt 6 `globalPosition()`/`position()`
    (QPointF), Qt 5 `globalPos()`/`localPos()` bzw. `posF()`.
  * `exec()` gibt es in PyQt5 5.15 auch (gemessen), `exec_` braucht es nicht.

Was die Schicht NICHT tut: nichts global setzen (kein HiDPI-Attribut, kein
excepthook) — die QApplication gehoert Cadwork.
"""

import importlib
import sys
import types

SCHNITTSTELLE = 1
#: Unter diesem Namen stehen die Untermodule in `sys.modules` — fest, egal
#: unter welchem Namen dieses Modul selbst geladen wurde.
NAME = "omcad_qt"

#: Reihenfolge der Wahl, wenn noch keine Bindung geladen ist.
BINDUNGEN = ("PyQt6", "PyQt5")
#: Was in Qt 6 in QtGui liegt und in Qt 5 in QtWidgets.
NACH_QTGUI = ("QAction", "QActionGroup", "QShortcut", "QFileSystemModel",
              "QUndoCommand", "QUndoStack", "QUndoGroup")
TEILE = ("QtCore", "QtGui", "QtWidgets", "QtSvg")

BINDUNG = None
FEHLER = ""
QT_VERSION = ""
PYQT_VERSION = ""
QtCore = QtGui = QtWidgets = QtSvg = None
sip = None


def waehlen(module=None, importieren=None):
    """-> ("PyQt6"|"PyQt5"|None, Grund). Wirft nie.

    `module` (Vorgabe `sys.modules`) und `importieren` (Vorgabe
    `importlib.import_module`) sind nur fuer die Gates ersetzbar.
    """
    module = sys.modules if module is None else module
    importieren = importieren or importlib.import_module
    for name in BINDUNGEN:
        if (name + ".QtCore") in module:
            return name, "schon geladen"
    gruende = []
    for name in BINDUNGEN:
        try:
            importieren(name + ".QtCore")
            return name, "importiert"
        except Exception as exc:                          # noqa: BLE001
            gruende.append("%s: %s" % (name, exc))
    return None, "; ".join(gruende) or "keine Qt-Bindung"


def _huelle(name, echt, extra=None):
    """Ein eigenes Modulobjekt mit allen Namen von `echt` (+ extra)."""
    m = types.ModuleType(name)
    m.__dict__.update({k: v for k, v in vars(echt).items()
                       if not k.startswith("__")})
    if extra:
        m.__dict__.update(extra)
    m.__doc__ = "omcad_qt: %s" % getattr(echt, "__name__", name)
    return m


def _binden():
    global BINDUNG, FEHLER, QT_VERSION, PYQT_VERSION
    global QtCore, QtGui, QtWidgets, QtSvg, sip
    bindung, grund = waehlen()
    if bindung is None:
        FEHLER = "Weder PyQt6 noch PyQt5 im Prozess (%s)" % grund
        return
    core = importlib.import_module(bindung + ".QtCore")
    gui = importlib.import_module(bindung + ".QtGui")
    widgets = importlib.import_module(bindung + ".QtWidgets")
    try:
        svg = importlib.import_module(bindung + ".QtSvg")
    except Exception:                                     # noqa: BLE001
        svg = None
    try:
        sip = importlib.import_module(bindung + ".sip")
    except Exception:                                     # noqa: BLE001
        sip = None
    if bindung == "PyQt6":
        # In Qt 6 ist alles, wo es hingehoert — die echten Module genuegen.
        QtCore, QtGui, QtWidgets, QtSvg = core, gui, widgets, svg
    else:
        verschoben = {n: getattr(widgets, n) for n in NACH_QTGUI
                      if hasattr(widgets, n)}
        QtCore = _huelle(NAME + ".QtCore", core)
        QtGui = _huelle(NAME + ".QtGui", gui, verschoben)
        QtWidgets = _huelle(NAME + ".QtWidgets", widgets)
        QtSvg = None if svg is None else _huelle(NAME + ".QtSvg", svg)
    BINDUNG = bindung
    QT_VERSION = getattr(core, "QT_VERSION_STR", "")
    PYQT_VERSION = getattr(core, "PYQT_VERSION_STR", "")
    for teil, modul in (("QtCore", QtCore), ("QtGui", QtGui),
                        ("QtWidgets", QtWidgets), ("QtSvg", QtSvg)):
        if modul is not None:
            sys.modules[NAME + "." + teil] = modul
        else:
            sys.modules.pop(NAME + "." + teil, None)


def laden():
    """-> dieses Modul mit gebundener Qt-Schicht, sonst ImportError."""
    if BINDUNG is None:
        raise ImportError("Open MCP CAD braucht Qt: " + FEHLER)
    return sys.modules.get(__name__)


def stand():
    """'PyQt5 5.15.11 / Qt 5.15.2' — fuer Log und Technik-Details."""
    if BINDUNG is None:
        return "kein Qt (%s)" % FEHLER
    return "%s %s / Qt %s" % (BINDUNG, PYQT_VERSION, QT_VERSION)


def ist_qt5():
    return BINDUNG == "PyQt5"


def wert(enum):
    """Der Zahlenwert eines Enums/Flags — `.value` in PyQt6, int in PyQt5."""
    w = getattr(enum, "value", enum)
    try:
        return int(w)
    except Exception:                                     # noqa: BLE001
        return w


def global_punkt(e):
    """Die globale Mausposition eines Ereignisses als QPoint (Qt 6 und 5)."""
    f = getattr(e, "globalPosition", None)
    if f is not None:
        return f().toPoint()
    return e.globalPos()


def punkt(e):
    """Die lokale Position eines Ereignisses als QPointF (Qt 6 und 5)."""
    f = getattr(e, "position", None)
    if f is not None:
        return f()
    for name in ("localPos", "posF"):
        f = getattr(e, name, None)
        if f is not None:
            return f()
    return QtCore.QPointF(e.pos())


try:
    _binden()
except Exception as _exc:                                 # noqa: BLE001
    BINDUNG = None
    FEHLER = "%s: %s" % (type(_exc).__name__, _exc)
