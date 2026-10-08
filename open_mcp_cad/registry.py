# -*- coding: utf-8 -*-
"""Lesender Zugriff auf die Registry der laufenden Steckplätze.

Seit 2026-09-20 sucht sich ein Steckplatz beim Start einen freien Port und
trägt sich mit seinem Dokumentnamen ein. Damit ist die Zahl der Leitungen
nicht mehr an die Zahl der Plugin-Ordner gebunden: man startet **einen**
Menüeintrag in so vielen Cadwork-Fenstern, wie man braucht.

Der eigentliche Gewinn ist nicht die Zahl, sondern die Frage, die man
stellen kann. Vorher: *"welcher Port bedient Seeblick?"* — und die Antwort
stand nirgends, man musste sie sich merken. Jetzt: *"wer hat Seeblick
offen?"*

DREI LESER, EIN FORMAT. Der Kern schreibt (in Cadworks Prozess), das
Verbindungsfenster liest (daneben), dieses Modul liest (im MCP-Prozess).
Jeder lebt in einem anderen Prozess, deshalb hat jeder seinen eigenen
Leser statt eines geteilten Imports — die Registry ist ein *Dateiformat*,
kein Code. Dass alle drei dasselbe Format sprechen, misst
`tests/test_registry.py`, indem der Kern schreibt und die Leser lesen.

EIN EINTRAG IST KEINE ZUSAGE, dass der Steckplatz läuft: der Prozess kann
abgestürzt sein. Deshalb prüft jeder Leser die PID — und seit 2026-09-25
auch, ob es noch DERSELBE Prozess ist (`_pid_lebt`). Aufgeräumt wird nur
vom Kern — ein Leser, der löscht, ist ein Leser, der Schaden anrichten
kann.
"""

import json
import math
import os

REGISTRY_ORDNER = os.environ.get(
    "OPEN_MCP_CAD_REGISTRY", r"C:\Users\Public\open-mcp-cad")


class MehrdeutigesDokument(Exception):
    """Mehrere laufende Instanzen passen auf denselben Suchbegriff.

    Bewusst ein Fehler und keine Auswahl per Zufall: genau diese
    Verwechslung — Code landet in der falschen Datei — ist der Grund,
    warum es den Dokumentschutz überhaupt gibt.
    """

    def __init__(self, suche, treffer):
        self.suche = suche
        self.treffer = treffer
        super().__init__(
            "%r passt auf %d laufende Instanzen: %s — bitte genauer angeben"
            % (suche, len(treffer),
               ", ".join("%s (Port %s, %s)" % (t["instanz"], t["port"],
                                               t["dokument"])
                         for t in treffer)))


# Spielraum zwischen dem Start des Prozesses und `start` im Eintrag. Der
# Kern trägt sich erst nach listen() ein, gemessen 10 s bis Minuten nach
# dem Start von Cadwork; die Toleranz fängt nur Uhr-Auflösung und kleine
# Korrekturen der Systemuhr ab.
UHR_TOLERANZ_S = 2.0

_K32 = None


def _kernel32():
    """Eigene kernel32-Instanz: argtypes/restype hier ändern nichts an
    `ctypes.windll.kernel32`, das andere Module im selben Prozess teilen."""
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = w.HANDLE
        k.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
        k.CloseHandle.argtypes = (w.HANDLE,)
        k.WaitForSingleObject.restype = w.DWORD
        k.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
        k.GetProcessTimes.argtypes = ((w.HANDLE,)
                                      + (ctypes.POINTER(w.FILETIME),) * 4)
        _K32 = k
    return _K32


def _prozess_windows(pid):
    """(lebt, gestartet) über die Windows-API, ohne neue Abhängigkeit.

    `gestartet`: Erzeugungszeit in Sekunden seit 1970, None wenn nicht
    lesbar. Ist nur SYNCHRONIZE zu haben, bleibt es bei der Probe ohne
    Startzeit — strenger wird es nur, wo es sich belegen lässt.
    """
    import ctypes
    from ctypes import wintypes as w
    k = _kernel32()
    # SYNCHRONIZE für das Warten, PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
    # für die Startzeit. Gibt es nur SYNCHRONIZE, fehlt eben die Startzeit.
    h = k.OpenProcess(0x00100000 | 0x1000, False, pid)
    abfragbar = bool(h)
    if not h:
        h = k.OpenProcess(0x00100000, False, pid)             # SYNCHRONIZE
        if not h:
            return False, None
    try:
        # Ein beendeter Prozess laesst sich weiter oeffnen, solange
        # irgendwer noch einen Handle auf ihn haelt. Gemessen
        # 2026-09-25: Cadwork mit dem Dokument geschlossen, sein
        # Eintrag galt weiter als laufend, und open_document
        # verweigerte dieselbe Datei ("name_in_use"). Beendet ist
        # er, wenn das Objekt signalisiert (WAIT_OBJECT_0 = 0).
        if k.WaitForSingleObject(h, 0) == 0:
            return False, None
        if not abfragbar:
            return True, None
        zeiten = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(z) for z in zeiten]):
            return True, None
        ft = (zeiten[0].dwHighDateTime << 32) | zeiten[0].dwLowDateTime
        return True, ft / 1e7 - 11644473600.0     # 1601 -> 1970
    finally:
        k.CloseHandle(h)


def _pid_lebt(pid, seit=None) -> bool:
    """Lebt der Prozess — und ist es noch der, der sich eingetragen hat?

    `seit` ist `start` aus dem Eintrag (vom Kern NACH dem Start seines
    Prozesses geschrieben). Windows vergibt PIDs neu: Befund 2026-09-25,
    ein Eintrag zeigte auf PID 17820, sein Cadwork war seit dem Vortag
    beendet und die PID gehörte einem anderen Prozess. Die automatische
    Portwahl sah zwei Instanzen statt einer. Ein Prozess, der NACH dem
    Eintrag gestartet ist, kann ihn nicht geschrieben haben.

    Bewusst kein Vergleich des Prozessnamens: welcher Name zählt (`3d.exe`,
    ein Python der Tests, ein künftiger Cadwork-Starter), wäre eine Liste,
    die veraltet.

    Ohne `seit` (Einträge ohne Startzeit) bleibt es bei der PID.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            lebt, gestartet = _prozess_windows(pid)
        except Exception:                                   # noqa: BLE001
            # Im Zweifel als lebend melden. Einen Eintrag fälschlich zu
            # übergehen kostet eine erreichbare Instanz; ihn fälschlich zu
            # behalten kostet eine Zeile, die der Kern aufräumt.
            return True
        if not lebt:
            return False
        try:
            seit = float(seit)
        except (TypeError, ValueError):
            return True
        if gestartet is None or not math.isfinite(seit):
            return True
        return gestartet <= seit + UHR_TOLERANZ_S
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def laufende() -> list:
    """Alle eingetragenen Steckplätze, nach Port sortiert."""
    try:
        namen = sorted(os.listdir(REGISTRY_ORDNER))
    except OSError:
        return []                      # Ordner gibt es nicht: nichts läuft
    ergebnis = []
    for n in namen:
        if not (n.startswith("instanz-") and n.endswith(".json")):
            continue
        try:
            with open(os.path.join(REGISTRY_ORDNER, n), encoding="utf-8") as fh:
                eintrag = json.load(fh)
        except Exception:                                   # noqa: BLE001
            continue
        if _pid_lebt(eintrag.get("pid"), eintrag.get("start")):
            ergebnis.append(eintrag)
    ergebnis.sort(key=lambda e: e.get("port", 0))
    return ergebnis


def finde(dokument: str, eintraege=None) -> list:
    """Einträge, deren Dokumentname `dokument` enthält (ohne Gross/Klein).

    `eintraege`: schon gelesene (`laufende()`), damit Auswahl und Liste in
    einer Fehlermeldung aus DEMSELBEN Blick stammen; sonst liest es selbst.
    """
    suche = (dokument or "").strip().lower()
    if not suche:
        return []
    return [e for e in (laufende() if eintraege is None else eintraege)
            if suche in (e.get("dokument") or "").lower()]


def port_fuer(dokument: str):
    """Der Port der EINEN Instanz, die `dokument` offen hat.

    None, wenn keine passt. `MehrdeutigesDokument`, wenn mehrere passen —
    dort ist Raten die schlechteste aller Antworten.
    """
    treffer = finde(dokument)
    if not treffer:
        return None
    if len(treffer) > 1:
        raise MehrdeutigesDokument(dokument, treffer)
    return int(treffer[0]["port"])


def beschreibung() -> str:
    """Eine Zeile je laufender Instanz — für Fehlermeldungen."""
    eintraege = laufende()
    if not eintraege:
        return ("Es ist keine Instanz eingetragen. Läuft das Plugin in "
                "Cadwork? (Registry: %s)" % REGISTRY_ORDNER)
    return "\n".join(
        "  %-3s Port %-6s %s" % (e.get("instanz", "?"), e.get("port", "?"),
                                 e.get("dokument") or "(kein Dokument)")
        for e in eintraege)
