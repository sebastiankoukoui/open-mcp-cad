#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Client fuer Open MCP CAD — fragt Steckplaetze ab und steuert sie.

Bewusst ohne Abhaengigkeiten (nur Stdlib), damit dieselbe Datei vom
Uebersichtsfenster, von der Browser-Rueckfallebene und von der Offline-
Testsuite benutzt werden kann.

Wichtig fuer die Anzeige: `status()` unterscheidet drei Faelle ehrlich —
  * erreichbar und antwortet         -> Zustand aus der Bridge
  * erreichbar, antwortet aber nicht -> "keine Antwort" (Hauptthread haengt)
  * nicht erreichbar                 -> "Aus" (Plugin laeuft dort nicht)
Ein Timeout wird NIE als "Aus" ausgegeben. Genau diese Verwechslung hat
frueher Stunden gekostet.
"""

import json
import math
import os
import socket
import time

HOST = "127.0.0.1"

# Die festen Steckplaetze. Rueckmeldung 2026-08-15: "aktuell immer noch einfach 4
# ports anstelle von unendlich oder zumindest erhoehen auf zb 6 ports".
#
# Es sind jetzt sechs. Warum nicht "unendlich": jeder Steckplatz ist ein
# eigener Cadwork-Plugin-ORDNER (Cadwork verlangt Ordnername == Dateiname)
# und ein eigener Eintrag in Claude Desktop. Beides ist Ausrollarbeit, keine
# Laufzeitentscheidung — ein Port, den niemand installiert hat, waere nur
# eine Zeile, die immer "Aus" zeigt. Mehr werden es, indem man hier
# ergaenzt und `plugins_generieren.py` laufen laesst; ab da traegt der Rest
# des Systems die Zahl von selbst.
ERSTER_PORT = 53127
STANDARD_PORTS = [(chr(ord("A") + i), ERSTER_PORT + i) for i in range(6)]


def _ports_aus_umgebung():
    """OPEN_MCP_CAD_PORTS="A=53911,B=53912" verschiebt die Ports.

    Nur fuer Tests und Vorfuehrungen gedacht — im Normalbetrieb bleiben es
    die vier festen Ports oben, auf die auch die MCP-Konfiguration zeigt.
    """
    roh = os.environ.get("OPEN_MCP_CAD_PORTS", "").strip()
    if not roh:
        return list(STANDARD_PORTS)
    zuordnung = dict(STANDARD_PORTS)
    for teil in roh.split(","):
        if "=" not in teil:
            continue
        instanz, _, port = teil.partition("=")
        instanz = instanz.strip().upper()
        if instanz in zuordnung:
            try:
                zuordnung[instanz] = int(port)
            except ValueError:
                pass
    return [(i, zuordnung[i]) for i, _p in STANDARD_PORTS]


STECKPLAETZE = _ports_aus_umgebung()
PORT_VON_INSTANZ = dict(STECKPLAETZE)

# --- Registry der laufenden Steckplaetze ----------------------------------
#
# Seit 2026-09-20 kann ein Steckplatz seinen Port selbst waehlen und sich
# mit seinem Dokumentnamen eintragen (Kern: `registry_eintragen`). Damit
# ist die Zahl der Leitungen nicht mehr an die Zahl der Plugin-Ordner
# gebunden — man startet EINEN Menueeintrag in so vielen Cadwork-Fenstern,
# wie man braucht.
#
# WARUM HIER EIN EIGENER LESER und kein Import des Kerns: der Kern gehoert
# in Cadworks Prozess. Ihn von aussen zu laden, um zwanzig Zeilen zu lesen,
# wuerde eine Abhaengigkeit schaffen, die es nicht braucht — die Registry
# ist ein DATEIFORMAT, kein Code. Dass Schreiber und Leser dasselbe Format
# sprechen, sichert `tests/test_registry.py` ab, indem der Kern schreibt
# und DIESER Leser liest.

REGISTRY_ORDNER = os.environ.get(
    "OPEN_MCP_CAD_REGISTRY", r"C:\Users\Public\open-mcp-cad")


# Spielraum zwischen dem Start des Prozesses und `start` im Eintrag. Der
# Kern traegt sich erst nach listen() ein, gemessen 10 s bis Minuten nach
# dem Start von Cadwork; die Toleranz faengt nur Uhr-Aufloesung und kleine
# Korrekturen der Systemuhr ab. Dieselbe Regel wie
# open_mcp_cad/registry.py (Gate: test_bootstrap G0-G5).
UHR_TOLERANZ_S = 2.0

_K32 = None


def _kernel32():
    """Eigene kernel32-Instanz: argtypes/restype hier aendern nichts an
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
    """(lebt, gestartet): Erzeugungszeit in s seit 1970 oder None.

    Nur SYNCHRONIZE zu haben -> die Probe ohne Startzeit.
    """
    import ctypes
    from ctypes import wintypes as w
    k = _kernel32()
    # SYNCHRONIZE fuer das Warten, PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
    # fuer die Startzeit. Gibt es nur SYNCHRONIZE, fehlt eben die Startzeit.
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


def _pid_lebt(pid, seit=None):
    """Laeuft der Prozess noch — und ist es der, der sich eingetragen hat?

    `seit` ist `start` aus dem Eintrag. Windows vergibt PIDs neu; ein
    Prozess, der NACH dem Eintrag gestartet ist, kann ihn nicht geschrieben
    haben (Befund 2026-09-25: ein beendetes Cadwork galt als laufend, weil
    seine PID einem anderen Prozess gehoerte). Ohne `seit` nur die PID.
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
            return True          # im Zweifel behalten, nicht wegraeumen
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


def registry_lesen():
    """Alle eingetragenen Steckplaetze, nach Port sortiert.

    Eintraege toter Prozesse werden uebersprungen (aber NICHT geloescht —
    Aufraeumen ist Sache des Kerns, der schreibt; ein Leser, der loescht,
    ist ein Leser, der Schaden anrichten kann).
    """
    try:
        namen = sorted(os.listdir(REGISTRY_ORDNER))
    except OSError:
        return []
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


def alle_steckplaetze():
    """Feste Steckplaetze PLUS die dynamisch eingetragenen, ohne Doppel.

    Die festen kommen zuerst und behalten ihren Buchstaben — sie stehen so
    auch in den Host-Konfigurationen. Ein dynamischer Steckplatz auf einem
    festen Port ist derselbe Steckplatz, kein zweiter.
    """
    ergebnis = list(STECKPLAETZE)
    bekannt = {p for _i, p in ergebnis}
    for e in registry_lesen():
        port = e.get("port")
        if port in bekannt:
            continue
        bekannt.add(port)
        ergebnis.append((e.get("instanz") or "?", port))
    return ergebnis


def finde_dokument(name):
    """Steckplaetze, in denen `name` als Teil des Dokumentnamens vorkommt.

    Liefert [(instanz, port, dokument), ...] — eine LISTE, weil zwei offene
    Dateien denselben Teilstring tragen koennen. Wer daraus einen einzelnen
    Treffer macht, muss die Mehrdeutigkeit selbst behandeln statt sie zu
    verstecken.
    """
    suche = (name or "").strip().lower()
    if not suche:
        return []
    return [(e.get("instanz") or "?", e.get("port"), e.get("dokument") or "")
            for e in registry_lesen()
            if suche in (e.get("dokument") or "").lower()]

def port_von(instanz_oder_port):
    """Der Port zu einer Kennung — feste Liste ODER Registry.

    Drei Formen: eine benannte Kennung ("A" … "F"), eine Kennung aus der
    Registry (ein dynamischer Steckplatz heisst nach seiner Position bzw.
    seinem Port), oder eine Portnummer.

    Wirft KeyError mit einer Liste des Bekannten. Ein stilles None waere
    hier das Schlechteste: der Aufrufer fragte Port None ab und bekaeme
    "nicht erreichbar" — eine Fehlermeldung, die in die falsche Richtung
    zeigt.
    """
    s = str(instanz_oder_port).strip()
    if s.isdigit() and len(s) >= 4:
        return int(s)
    k = s.upper()
    if k in PORT_VON_INSTANZ:
        return PORT_VON_INSTANZ[k]
    for e in registry_lesen():
        if (e.get("instanz") or "").upper() == k:
            return int(e["port"])
    bekannt = [i for i, _p in alle_steckplaetze()]
    raise KeyError("kein Steckplatz %r — bekannt sind %s"
                   % (instanz_oder_port, ", ".join(bekannt) or "keine"))


def kennung_von(port):
    """Die Kennung zu einem Port — feste Liste ODER Registry.

    Hier stand `next((i for i, p in STECKPLAETZE if p == port), "?")`. Fuer
    einen dynamisch vergebenen Port lieferte das "?" — der Steckplatz war
    in der Anzeige namenlos, obwohl er sich mit Kennung eingetragen hat.
    """
    for i, p in alle_steckplaetze():
        if p == port:
            return i
    return str(port)


# Kurzer Timeout: Status muss schnell antworten, sonst stimmt etwas nicht.
STATUS_TIMEOUT_S = 2.0
STEUER_TIMEOUT_S = 5.0
# Verbindungsaufbau: ein laufender Steckplatz nimmt sofort an.
VERBINDUNGS_TIMEOUT_S = 0.6

# Der Kern selbst bleibt bewusst ASCII (er laeuft in Cadworks Python und
# loggt in eine Konsole mit unbekannter Codepage). Die Anzeige gehoert aber
# dem Client — und der darf Umlaute. Deshalb wird hier IMMER neu gemappt und
# der Text der Bridge nur als Rueckfallebene benutzt.
ZUSTAND_TEXT = {
    "stopped": "Aus",
    "starting": "Wird gestartet",
    "ready": "Bereit",
    "busy_read": "Liest Modell",
    "busy_write": "Bearbeitet Modell",
    "paused": "Pausiert",
    "stopping_after_job": "Wird nach dem Auftrag beendet",
    "error": "Störung",
    # Nur clientseitig:
    "unreachable": "Aus",
    "no_answer": "Keine Antwort",
    "veraltet": "Läuft (alte Version)",
}

# Zustaende, in denen der Steckplatz zwar lebt, aber nicht voll steuerbar ist.
NUR_ALT_STEUERBAR = ("veraltet",)


class Antwort(dict):
    """Antwort der Bridge plus die zwei Client-Felder erreichbar/fehler."""

    @property
    def ok(self):
        return bool(self.get("ok"))


def anfrage(port, methode, params=None, timeout=STEUER_TIMEOUT_S, host=HOST,
            verbindungs_timeout=VERBINDUNGS_TIMEOUT_S):
    """Ein Request, eine kurzlebige Verbindung. Wirft nie.

    Verbindungsaufbau und Antwort haben BEWUSST getrennte Zeitgrenzen:

      * Ein laufender Steckplatz nimmt die Verbindung in Sekundenbruchteilen
        an. Klappt das nicht in `verbindungs_timeout`, laeuft dort nichts —
        das ist "Aus".
      * Kommt die Verbindung zustande, bleibt aber die Antwort aus, lebt das
        Plugin, waehrend sein Cadwork-Hauptthread steht — das ist "Keine
        Antwort" und etwas voellig anderes.

    Auf ein "Connection refused" darf man sich dabei nicht verlassen:
    gemessen am 2026-08-04 auf dem Legion laeuft eine Verbindung zu einem
    geschlossenen Localhost-Port in den Timeout, statt abgewiesen zu werden.
    """
    req = {"id": 1, "method": methode, "params": params or {}}
    daten = (json.dumps(req) + "\n").encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(verbindungs_timeout)
        try:
            sock.connect((host, port))
        except (ConnectionRefusedError, socket.timeout, TimeoutError, OSError) as exc:
            return Antwort(ok=False, error="unreachable", erreichbar=False,
                           message="Auf Port %d laeuft keine Verbindung (%s)."
                                   % (port, type(exc).__name__))
        sock.settimeout(timeout)
        try:
            sock.sendall(daten)
            puffer = bytearray()
            while b"\n" not in puffer:
                stueck = sock.recv(4096)
                if not stueck:
                    return Antwort(ok=False, error="closed", erreichbar=True,
                                   message="Verbindung wurde ohne Antwort "
                                           "geschlossen")
                puffer.extend(stueck)
            zeile, _, _ = bytes(puffer).partition(b"\n")
        except (socket.timeout, TimeoutError):
            return Antwort(ok=False, error="no_answer", erreichbar=True,
                           message="Port %d nimmt Verbindungen an, antwortet "
                                   "aber seit %.0f s nicht. Das Plugin lebt, "
                                   "sein Cadwork-Hauptthread steht."
                                   % (port, timeout))
        except OSError as exc:
            return Antwort(ok=False, error="unreachable", erreichbar=False,
                           message="%s: %s" % (type(exc).__name__, exc))
    finally:
        try:
            sock.close()
        except OSError:
            pass

    try:
        antwort = json.loads(zeile.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return Antwort(ok=False, error="invalid_response", erreichbar=True,
                       message="Antwort war kein gueltiges JSON: %s" % exc)
    antwort["erreichbar"] = True
    return Antwort(antwort)


def status(instanz_oder_port, timeout=STATUS_TIMEOUT_S):
    """Status eines Steckplatzes — immer ein anzeigbares Dict, nie eine Ausnahme."""
    if isinstance(instanz_oder_port, str) and not instanz_oder_port.isdigit():
        instanz = instanz_oder_port.upper()
        try:
            port = port_von(instanz)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
    else:
        port = int(instanz_oder_port)
        instanz = kennung_von(port)

    t0 = time.monotonic()
    antwort = anfrage(port, "status", timeout=timeout)
    dauer_ms = int((time.monotonic() - t0) * 1000)

    if antwort.ok:
        daten = dict(antwort.get("result") or {})
        daten["erreichbar"] = True
        daten["antwortzeit_ms"] = dauer_ms
        daten.setdefault("instanz", instanz)
        daten.setdefault("port", port)
        daten["zustand_text"] = ZUSTAND_TEXT.get(daten.get("zustand"),
                                                 daten.get("zustand_text", "?"))
        return daten

    # Kein gueltiger Status -> ehrlich benennen, nicht schoenreden.
    code = antwort.get("error", "unreachable")
    if code == "unknown_method":
        # Der Steckplatz laeuft, kennt 'status' aber nicht: das ist ein
        # Plugin vor Open MCP CAD 2.0. "Stoerung" waere hier schlicht
        # falsch — dem Ding fehlt nichts, es ist nur alt. Tritt beim
        # Ausrollen zwangslaeufig auf, solange eine Instanz noch laeuft.
        zustand = "veraltet"
        hinweis = ("Aelteres Plugin (vor Open MCP CAD 2.0) — Zustand, "
                   "Dokument und Auftrag sind von aussen nicht lesbar. In "
                   "diesem Cadwork das Plugin beenden und neu starten, dann "
                   "laeuft der neue Stand.")
    else:
        zustand = code if code in ("unreachable", "no_answer") else "error"
        # "Aus" ist der Normalzustand eines nicht gestarteten Steckplatzes —
        # dort eine Fehlermeldung in Warnfarbe anzuzeigen ist Rauschen. Die
        # technische Meldung bleibt unter "Details" abrufbar.
        hinweis = "" if zustand == "unreachable" else antwort.get("message", "")
    return {
        "instanz": instanz,
        "port": port,
        "erreichbar": bool(antwort.get("erreichbar")),
        "zustand": zustand,
        "zustand_text": ZUSTAND_TEXT.get(zustand, "Stoerung"),
        "dokument": "",
        "auftrag": None,
        "hinweis": hinweis,
        "antwortzeit_ms": dauer_ms,
        "fehler_code": code,
        "fehler_detail": antwort.get("message", ""),
    }


# Zwischenspeicher fuer die Schonfrist unten: instanz -> (zeit, daten)
_letzter_status = {}
# Wie lange ein als "veraltet" erkannter Steckplatz in Ruhe gelassen wird.
VERALTET_SCHONFRIST_S = 30.0


def alle_status(timeout=STATUS_TIMEOUT_S):
    """Status aller vier Steckplaetze, in der Reihenfolge A B C D.

    Parallel, damit ein toter Steckplatz die anderen drei nicht ausbremst:
    seriell waeren im schlimmsten Fall 4 x Timeout zu warten.

    **Alte Plugins werden geschont.** Eine Version vor 2.0 beantwortet auch
    `status` ueber ihre Job-Queue — die Anfrage landet also im Cadwork-
    HAUPTTHREAD dieser Instanz. Im Sekundentakt waere das ein Dauerstrom
    von Fremdauftraegen in ein produktiv genutztes Cadwork, und waehrend
    eines langen Auftrags wuerden sie sich dort stauen. Ein einmal als
    "veraltet" erkannter Steckplatz wird deshalb nur noch alle
    VERALTET_SCHONFRIST_S Sekunden gefragt; dazwischen zeigt die Oberflaeche
    den letzten bekannten Stand.
    """
    import threading
    # Die feste Liste PLUS die dynamisch eingetragenen. Mit `len(STECKPLAETZE)`
    # war ein Steckplatz, der sich selbst einen Port gesucht hat, in der
    # Anzeige gar nicht vorhanden: er lief, und niemand sah ihn.
    plaetze = alle_steckplaetze()
    ergebnis = [None] * len(plaetze)
    jetzt = time.monotonic()

    # Abgefragt wird ueber den PORT, nicht den Buchstaben (2026-09-24):
    # ein Registry-Eintrag auf einem fremden Port mit der Kennung "A"
    # (test_offline traegt solche ein) landete sonst bei 53127 — A stand
    # doppelt in den Daten, und das Dock liess je Takt eine Karte liegen.
    def hole(i, instanz, port):
        alt = _letzter_status.get(port)
        if (alt and alt[1].get("zustand") == "veraltet"
                and jetzt - alt[0] < VERALTET_SCHONFRIST_S):
            gespeichert = dict(alt[1])
            gespeichert["aus_zwischenspeicher_s"] = round(jetzt - alt[0], 1)
            ergebnis[i] = gespeichert
            return
        try:
            ergebnis[i] = status(port, timeout=timeout)
            _letzter_status[port] = (time.monotonic(), ergebnis[i])
        except Exception as exc:                      # noqa: BLE001
            ergebnis[i] = {"instanz": instanz, "port": port,
                           "erreichbar": False, "zustand": "error",
                           "zustand_text": "Stoerung", "dokument": "",
                           "auftrag": None, "hinweis": str(exc)}

    threads = [threading.Thread(target=hole, args=(i, instanz, port),
                                daemon=True)
               for i, (instanz, port) in enumerate(plaetze)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 1.0)
    return [e for e in ergebnis if e is not None]


# --- Steuerung ------------------------------------------------------------

def pausieren(instanz):
    return anfrage(port_von(instanz), "pause")


def fortsetzen(instanz):
    return anfrage(port_von(instanz), "resume")


def beenden_nach_auftrag(instanz):
    return anfrage(port_von(instanz), "shutdown_after_current")


def jetzt_beenden(instanz):
    """Sofort beenden. Die Bridge lehnt selbst ab, wenn ein Auftrag laeuft."""
    return anfrage(port_von(instanz), "shutdown")


def wartende_verwerfen(instanz):
    return anfrage(port_von(instanz), "discard_pending")


def lizenz_freigeben(instanz, client_id=""):
    return anfrage(port_von(instanz), "release_write_lease",
                   {"client_id": client_id})


# --- Aufbereitung fuer die Anzeige ---------------------------------------

def zeile(daten, breite_dok=22):
    """Eine Zeile wie im Fenster 'Open MCP CAD Verbindungen'."""
    dok = daten.get("dokument") or "—"
    text = daten.get("zustand_text") or "?"
    auftrag = daten.get("auftrag")
    if auftrag:
        besch = auftrag.get("beschreibung") or auftrag.get("methode") or ""
        if besch:
            text = "%s: %s" % (text, besch)
        laufzeit = dauer_text(auftrag.get("laufzeit_s"))
    else:
        laufzeit = ""
    return "%-3s %-*s %-46s %s" % (daten.get("instanz", "?"), breite_dok,
                                   dok[:breite_dok], text[:46], laufzeit)


def dauer_text(sekunden):
    if sekunden is None:
        return ""
    sekunden = int(sekunden)
    return "%02d:%02d" % (sekunden // 60, sekunden % 60)


def client_kennung():
    """Stabile Kennung dieses Clients fuer die Schreiblizenz.

    Reihenfolge: ausdruecklich gesetzt > Sitzungskennung > Prozess.
    """
    fuer = os.environ.get("OPEN_MCP_CAD_CLIENT_ID")
    if fuer:
        return fuer
    sitzung = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("OPEN_MCP_CAD_SESSION")
    if sitzung:
        return "sitzung:%s" % sitzung[:16]
    return "pid:%d" % os.getpid()


if __name__ == "__main__":
    print("Open MCP CAD Verbindungen (Momentaufnahme)\n")
    for d in alle_status():
        print(zeile(d))
        if d.get("hinweis"):
            print("      %s" % d["hinweis"])
