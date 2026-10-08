# -*- coding: utf-8 -*-
"""A-ONLY UI PROTOTYPE — Netzwerkteil fuer den Tab "Verbindungen".

    ################################################################
    #  A-ONLY UI PROTOTYPE                                         #
    #  HERKUNFT: scripts/connect_client.py                 #
    #  Bewusst eine getrimmte KOPIE, keine zweite Protokollwelt.   #
    #  Zusammenfuehren, sobald der Prototyp bleibt — siehe         #
    #  docs/PROTOTYP_A_dashboard.md, Abschnitt "Rueckbau".         #
    ################################################################

WARUM EINE KOPIE UND KEIN IMPORT
Der Pluginordner wird nach `…\\3d\\API.x64\\Open MCP CAD A\\` kopiert und
muss dort vollstaendig laufen. Ein Import aus `scripts/` haette eine
harte Abhaengigkeit auf den Repo-Pfad — auf einem anderen Rechner oder nach
dem Ausrollen waere der Tab tot.

WAS UEBERNOMMEN WURDE, WEIL ES TEUER ERKAUFT IST
  * Verbindungsaufbau und Antwort haben GETRENNTE Zeitgrenzen. Ein Timeout
    wird NIE als "Aus" ausgegeben: "nicht erreichbar" heisst, dort laeuft
    nichts; "keine Antwort" heisst, das Plugin lebt und sein Cadwork-
    Hauptthread steht. Genau diese Verwechslung hat frueher Stunden gekostet.
  * Auf "Connection refused" ist kein Verlass — gemessen laeuft eine
    Verbindung zu einem geschlossenen Localhost-Port in den Timeout.
  * `unknown_method` ist KEINE Stoerung, sondern ein Plugin vor 2.0. Solche
    Steckplaetze beantworten `status` ueber ihre Job-Queue, also im fremden
    Cadwork-Hauptthread — deshalb die Schonfrist, statt sie im Sekundentakt
    zu belaesten.
  * Alle parallel, sonst warten die gesunden auf einen toten.

NICHT uebernommen: Zeilen-Formatierung fuer die Konsole, Lizenz-Freigabe und
`client_kennung()` — der Tab braucht sie nicht.
"""

import json
import math
import os
import socket
import threading
import time

HOST = "127.0.0.1"
# Sechs Steckplaetze (A-F). Dieselbe Bildung wie in der Quelle
# scripts/connect_client.py — die Zahl steht dort begruendet.
ERSTER_PORT = 53127
STECKPLAETZE = [(chr(ord("A") + i), ERSTER_PORT + i) for i in range(6)]
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

    Drei Formen werden angenommen:
      * eine benannte Kennung ("A" … "F")
      * eine Kennung aus der Registry (ein dynamischer Steckplatz heisst
        nach seiner Position bzw. seinem Port)
      * eine Portnummer, als Zahl oder als Ziffernfolge

    WARUM ES DAS BRAUCHT: `PORT_VON_INSTANZ[instanz]` kannte nur die feste
    Liste. Eine Kennung wie "26" oder "53200" — genau die, die ein
    dynamischer Steckplatz traegt — warf dort einen KeyError, mitten in der
    Statusabfrage. Der Steckplatz lief, war aber nicht abfragbar.

    Wirft KeyError mit einer Liste des Bekannten, wenn nichts passt. Ein
    stilles None waere hier das Schlechteste: der Aufrufer fragte dann
    Port None ab und bekaeme "nicht erreichbar" — eine Fehlermeldung, die
    in die falsche Richtung zeigt.
    """
    s = str(instanz_oder_port).strip()
    if s.isdigit() and len(s) >= 4:
        return int(s)                     # ist schon ein Port
    k = s.upper()
    if k in PORT_VON_INSTANZ:
        return PORT_VON_INSTANZ[k]
    for e in registry_lesen():
        if (e.get("instanz") or "").upper() == k:
            return int(e["port"])
    bekannt = [i for i, _p in alle_steckplaetze()]
    raise KeyError("kein Steckplatz %r — bekannt sind %s"
                   % (instanz_oder_port, ", ".join(bekannt) or "keine"))


STATUS_TIMEOUT_S = 2.0
STEUER_TIMEOUT_S = 5.0
VERBINDUNGS_TIMEOUT_S = 0.6
VERALTET_SCHONFRIST_S = 30.0

ZUSTAND_TEXT = {
    "stopped": "Aus",
    "starting": "Verbindet …",
    "ready": "Bereit",
    "busy_read": "Liest Modell",
    "busy_write": "Bearbeitet Modell",
    "paused": "Pausiert",
    "stopping_after_job": "Wird nach Auftrag beendet",
    "error": "Störung",
    "unreachable": "Aus",
    "no_answer": "Keine Antwort",
    "veraltet": "Läuft (alte Version)",
}

# Zustaende, in denen ein Auftrag im fremden Cadwork-Hauptthread laeuft.
BESCHAEFTIGT = ("busy_read", "busy_write")


def anfrage(port, methode, params=None, timeout=STEUER_TIMEOUT_S):
    """Ein Request, eine kurzlebige Verbindung. Wirft nie."""
    req = {"id": 1, "method": methode, "params": params or {}}
    daten = (json.dumps(req) + "\n").encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(VERBINDUNGS_TIMEOUT_S)
        try:
            sock.connect((HOST, port))
        except (ConnectionRefusedError, socket.timeout, TimeoutError,
                OSError) as exc:
            return {"ok": False, "error": "unreachable", "erreichbar": False,
                    "message": "Auf Port %d läuft keine Verbindung (%s)."
                               % (port, type(exc).__name__)}
        sock.settimeout(timeout)
        try:
            sock.sendall(daten)
            puffer = bytearray()
            while b"\n" not in puffer:
                stueck = sock.recv(4096)
                if not stueck:
                    return {"ok": False, "error": "closed", "erreichbar": True,
                            "message": "Verbindung ohne Antwort geschlossen"}
                puffer.extend(stueck)
            zeile, _, _ = bytes(puffer).partition(b"\n")
        except (socket.timeout, TimeoutError):
            return {"ok": False, "error": "no_answer", "erreichbar": True,
                    "message": "Port %d nimmt Verbindungen an, antwortet aber "
                               "seit %.0f s nicht. Das Plugin lebt, sein "
                               "Cadwork-Hauptthread steht." % (port, timeout)}
        except OSError as exc:
            return {"ok": False, "error": "unreachable", "erreichbar": False,
                    "message": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        try:
            sock.close()
        except OSError:
            pass
    try:
        antwort = json.loads(zeile.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": "invalid_response", "erreichbar": True,
                "message": "Antwort war kein gültiges JSON: %s" % exc}
    antwort["erreichbar"] = True
    return antwort


def status(instanz, timeout=STATUS_TIMEOUT_S, port=None):
    """Status EINES Steckplatzes — immer anzeigbar, nie eine Ausnahme.

    `instanz` darf eine benannte Kennung, eine Registry-Kennung oder eine
    Portnummer sein (siehe `port_von`).
    """
    instanz = str(instanz).upper()
    port = port_von(instanz) if port is None else int(port)
    t0 = time.monotonic()
    antwort = anfrage(port, "status", timeout=timeout)
    dauer_ms = int((time.monotonic() - t0) * 1000)

    if antwort.get("ok"):
        daten = dict(antwort.get("result") or {})
        daten["erreichbar"] = True
        daten["antwortzeit_ms"] = dauer_ms
        daten.setdefault("instanz", instanz)
        daten.setdefault("port", port)
        daten["zustand_text"] = ZUSTAND_TEXT.get(
            daten.get("zustand"), daten.get("zustand_text", "?"))
        return daten

    code = antwort.get("error", "unreachable")
    if code == "unknown_method":
        zustand = "veraltet"
        hinweis = ("Älteres Plugin (vor Open MCP CAD 2.0) — Zustand, "
                   "Dokument und Auftrag sind von aussen nicht lesbar. In "
                   "diesem Cadwork das Plugin beenden und neu starten.")
    else:
        zustand = code if code in ("unreachable", "no_answer") else "error"
        # "Aus" ist der Normalzustand eines nicht gestarteten Steckplatzes.
        # Dort eine Warnfarbe anzuzeigen waere Rauschen; die technische
        # Meldung bleibt unter "Details" abrufbar.
        hinweis = "" if zustand == "unreachable" else antwort.get("message", "")
    return {
        "instanz": instanz, "port": port,
        "erreichbar": bool(antwort.get("erreichbar")),
        "zustand": zustand,
        "zustand_text": ZUSTAND_TEXT.get(zustand, "Störung"),
        "dokument": "", "auftrag": None, "hinweis": hinweis,
        "antwortzeit_ms": dauer_ms, "fehler_code": code,
        "fehler_detail": antwort.get("message", ""),
    }


_letzter_status = {}


def alle_status(timeout=STATUS_TIMEOUT_S):
    """Alle vier, parallel — ein toter Steckplatz bremst die anderen nicht.

    Alte Plugins werden geschont: sie beantworten `status` ueber ihre
    Job-Queue, also im fremden Cadwork-Hauptthread. Im Sekundentakt waere das
    ein Dauerstrom von Fremdauftraegen in ein produktiv benutztes Cadwork.
    """
    # Die feste Liste PLUS die dynamisch eingetragenen. Hier stand
    # `len(STECKPLAETZE)` — damit war ein Steckplatz, der sich selbst einen
    # Port gesucht hat, in der Anzeige gar nicht vorhanden. Er lief, und
    # niemand sah ihn.
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
            ergebnis[i] = status(instanz, timeout=timeout, port=port)
            _letzter_status[port] = (time.monotonic(), ergebnis[i])
        except Exception as exc:                      # noqa: BLE001
            ergebnis[i] = {"instanz": instanz,
                           "port": port,
                           "erreichbar": False, "zustand": "error",
                           "zustand_text": "Störung", "dokument": "",
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
# Adressiert ueber `port_von` — Buchstabe, Registry-Kennung oder Port. Hier
# stand `PORT_VON_INSTANZ[...]`, das nur A-F kennt: Pausieren eines
# Steckplatzes "26" warf einen KeyError (gefunden 2026-09-23).
#
# Genau die Methoden des vorhandenen Protokolls. Die Bridge setzt ihre
# Sicherheitsregeln selbst durch — `shutdown` lehnt sie waehrend eines
# Auftrags ab. Die Oberflaeche graut den Knopf zusaetzlich aus, damit man
# gar nicht erst in die Absage laeuft.

def pausieren(instanz):
    return anfrage(port_von(instanz), "pause")


def fortsetzen(instanz):
    return anfrage(port_von(instanz), "resume")


def beenden_nach_auftrag(instanz):
    return anfrage(port_von(instanz),
                   "shutdown_after_current")


def jetzt_beenden(instanz):
    return anfrage(port_von(instanz), "shutdown")


def dauer_text(sekunden):
    if sekunden is None:
        return ""
    sekunden = int(sekunden)
    return "%02d:%02d" % (sekunden // 60, sekunden % 60)
