#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer den Chat-Kern bei schnellen Wechseln (omcad_a_chat + omcad_a_anbieter).

    python tests/test_chat_kern.py            (-v zeigt jede Zeile)
    python tests/test_chat_kern.py --quelle <ordner>
        faehrt dieselben Zellen gegen omcad_a_chat.py/omcad_a_anbieter.py
        aus <ordner> — so wurde gezeigt, dass sie am alten Stand ROT werden.

Faehrt den ECHTEN Claude-Code-Weg (`starten` -> `claude.cmd` -> Leser ->
Karten -> `beenden`) gegen eine Attrappe: `cli_pfad()` sucht zuerst
`%APPDATA%\\npm\\claude.cmd`; APPDATA zeigt hier auf einen Temp-Ordner, und
die `claude.cmd` dort startet ein kleines Python-Skript, das stream-json
spricht (system/init mit session_id, Antworttext, can_use_tool, result) und
jede Zeile, die es auf stdin bekommt, in eine eigene Protokolldatei
schreibt. Gemessen wird also, was beim PROZESS ankommt.

Die Rennen, um die es geht (Befund 2026-09-25):
  * Beenden -> sofort Starten, waehrend der alte Prozess noch lebt.
  * das `finally` eines alten Lesers/Arbeitsthreads schaltet den NEUEN
    Chat ab.
  * eine Karte des alten Chats erreicht den neuen Prozess.
  * der neue Prozess bekommt keinen Leser, weil der alte noch lebt.
Dazu die anderen Anbieter (Schleife, Codex) und Wechsel zwischen ihnen.

Nachgezogen nach einer Mutanten-Pruefung (2026-09-25): neun Mutanten in
omcad_a_anbieter ueberlebten das Gate. Jetzt hat jeder Pfad seine Zelle —
S5 (CLI -> Schleife, waehrend das CLI auslaeuft; 'nach dem Zug beenden'),
S6 (Codex-App-Server lebt), S7 (spaete Modellantwort nach dem Beenden),
S8 (zweiter Werkzeugaufruf nach dem Beenden), S9 (beenden() vor dem
Eintragen des MCP-Servers), S10 (spaetes beenden() der alten Schleife),
S11 (Codex-Frage waehrend des Beendens), S12 (Codex-Handshake scheitert) —
und K11: ein Leser, der an einer Zeile aussteigt, waehrend sein CLI lebt.

M1-M3 (Film 2026-09-25): die Dock-Anweisung (reiner Text, kein Markdown,
Sprache des Nutzers) kommt in allen drei Wegen an — gemessen hinter
claude.cmd an der Befehlszeile, an der Nutzlast fuer /chat/completions und
an thread/start von Codex. Die Kontrolle faehrt dieselben Wege mit Modulen
ohne die Regel. Seit der Gegenpruefung 2026-09-26 verlangen M2/M3 den
VOLLEN Wortlaut (nicht nur Stichwoerter), und M4 vergleicht die beiden
Kopien der Konstanten aus dem QUELLTEXT — die Mutanten M19 (ein Satz fehlt)
und M26 (Sprachsatz verdreht) ueberlebten vorher.

Kein Netz, kein Schluessel, kein Cadwork, kein echtes CLI (K0 bricht ab,
bevor eins starten koennte), keine Ports im Cadwork-Bereich (der
Halte-Dienst bindet ueber `_http_dienst` aus test_anbieter, H0 misst es).
"""

import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
A = os.path.join(REPO, "cad_plugin", "Open MCP CAD A")
CREATE_NO_WINDOW = 0x08000000

# Solange haelt ein "Enkel" der alten Attrappe deren stdout/stderr offen,
# nachdem sie selbst schon beendet ist — so lebt der alte Leser weiter,
# waehrend der neue Chat startet.
HALTEN = 3.0

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % ("ok  " if bedingung else "FEHL", titel,
                               ("  — %s" % (detail,)) if detail else ""))
    return bool(bedingung)


def quelle():
    if "--quelle" in sys.argv:
        return os.path.abspath(sys.argv[sys.argv.index("--quelle") + 1])
    return A


def laden(name, datei, ordner=None):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ordner or quelle(), datei))
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def warte(bedingung, frist=10.0):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.02)
    return bool(bedingung())


def eintraege(pfad):
    """Die Protokollzeilen — eine halb geschriebene letzte Zeile zaehlt nicht."""
    try:
        with io.open(pfad, encoding="utf-8") as fh:
            zeilen = fh.read().splitlines()
    except OSError:
        return []
    ergebnis = []
    for z in zeilen:
        try:
            ergebnis.append(json.loads(z))
        except ValueError:
            pass
    return ergebnis


def stdin_von(pfad):
    return [e["stdin"] for e in eintraege(pfad) if "stdin" in e]


def antworten_an(pfad, kennung):
    """Die control_responses, die dieser Prozess fuer `kennung` bekam."""
    return [m for m in stdin_von(pfad) if m.get("type") == "control_response"
            and (m.get("response") or {}).get("request_id") == kennung]


def texte(chat):
    return [e.get("text", "") for e in chat.get("ereignisse") or ()
            if e.get("art") == "text"]


def arten(chat):
    return [e.get("art") for e in chat.get("ereignisse") or ()]


def baum_toeten(pid):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


# --- Die Attrappe des Claude-Code-CLI ----------------------------------------
# Modi (OMCAD_ATTRAPPE_MODUS, kommagetrennt):
#   flut         schreibt gleich nach init ~300 kB auf stdout, dann ~300 kB
#                auf stderr, und protokolliert jeweils danach — ohne Leser
#                blockiert sie dazwischen (Pipe voll).
#   langsam      braucht nach stdin-EOF 1,5 s bis zum Ende.
#   spaet_frage  stellt nach stdin-EOF noch eine Freigabe-Anfrage.
#   halten       startet nach stdin-EOF einen Enkel, der stdout/stderr
#                erbt, HALTEN s wartet, dann "SPAET <name>" und ein result
#                schreibt — und endet selbst sofort.
#   kaputt       schreibt gleich nach init die Zeile `[1]`: gueltiges JSON,
#                aber kein Objekt — daran steigt der Leser aus, waehrend
#                die Attrappe weiter auf stdin wartet.
#   nutzung      antwortet mit `usage` und `modelUsage` in der Form, die am
#                echten CLI 2.1.263 gemessen ist (Etappe D, S10), dazu eine
#                Antwort eines Unter-Agenten (`parent_tool_use_id`) mit
#                anderer Zahl.
# Eine Nachricht mit `werkzeug:NAME` (mehrere durch Leerzeichen) stellt je
# Name eine Freigabe-Anfrage fuer genau dieses Werkzeug (Modi, 2026-09-27).
# `werkzeug:NAME*2` fragt nach einem "allow" fuer NAME noch einmal — im
# selben Zug, ohne neue Nachricht (Freigabe je Art bis zur naechsten
# Nachricht).

CLI_ATTRAPPE = r'''
import json, os, subprocess, sys, time
LOG = os.environ["OMCAD_ATTRAPPE_LOG"]
NAME = os.environ.get("OMCAD_ATTRAPPE_NAME", "x")
MODUS = set(filter(None, os.environ.get("OMCAD_ATTRAPPE_MODUS", "").split(",")))

def log(o):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(o) + "\n")

def schreib(o):
    sys.stdout.write(json.dumps(o) + "\n")
    sys.stdout.flush()

def text(t):
    schreib({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})

def eltern():
    """Programmname des Elternprozesses (cmd.exe bei claude.cmd, claude.exe
    beim direkt gestarteten Programm) — ueber die Windows-API."""
    try:
        import ctypes
        from ctypes import wintypes
        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                        ("modul", wintypes.DWORD), ("threads", wintypes.DWORD),
                        ("eltern", wintypes.DWORD), ("prio", ctypes.c_long),
                        ("flags", wintypes.DWORD), ("exe", ctypes.c_wchar * 260)]
        k = ctypes.windll.kernel32
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k.CreateToolhelp32Snapshot(2, 0)
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        namen, von = {}, {}
        ok = k.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            namen[e.pid], von[e.pid] = e.exe, e.eltern
            ok = k.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
        k.CloseHandle(wintypes.HANDLE(snap))
        return namen.get(von.get(os.getpid()))
    except Exception:
        return None

log({"start": os.getpid(), "argv": sys.argv[1:], "eltern": eltern()})
schreib({"type": "system", "subtype": "init", "session_id": "sitzung-" + NAME,
         "model": "attrappe-" + NAME})
if "kaputt" in MODUS:
    schreib([1])
if "flut" in MODUS:
    pad = "x" * 1000
    for _ in range(300):
        schreib({"type": "rauschen", "pad": pad})
    log({"flut": "stdout"})
    for _ in range(300):
        sys.stderr.write(pad + "\n")
    sys.stderr.flush()
    log({"flut": "stderr"})
n = 0
nochmal = {}

def anfrage(name):
    global n
    n += 1
    kennung = "req-%s-%d" % (NAME, n)
    schreib({"type": "control_request", "request_id": kennung,
             "request": {"subtype": "can_use_tool", "tool_name": name,
                         "input": {"nr": n}}})
    return kennung

for zeile in sys.stdin:
    try:
        m = json.loads(zeile)
    except ValueError:
        continue
    log({"stdin": m})
    if m.get("type") == "user":
        inhalt = (m.get("message") or {}).get("content") or ""
        if isinstance(inhalt, list):
            inhalt = " ".join(b.get("text", "") for b in inhalt
                              if isinstance(b, dict) and b.get("type") == "text")
        if "werkzeug:" in inhalt:
            for wort in inhalt.split():
                if not wort.startswith("werkzeug:"):
                    continue
                name = wort[len("werkzeug:"):]
                zweimal = name.endswith("*2")
                name = name[:-2] if zweimal else name
                kennung = anfrage(name)
                if zweimal:
                    nochmal[kennung] = name
        elif "karte" in inhalt:
            n += 1
            schreib({"type": "control_request", "request_id": "req-%s-%d" % (NAME, n),
                     "request": {"subtype": "can_use_tool", "tool_name": "Bash",
                                 "input": {"command": "echo " + NAME}}})
        elif "nutzung" in MODUS:
            schreib({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "Antwort %s: %s" % (NAME, inhalt)}],
                "usage": {"input_tokens": 10, "cache_creation_input_tokens": 130158,
                          "cache_read_input_tokens": 0, "output_tokens": 4}}})
            schreib({"type": "assistant", "parent_tool_use_id": "toolu_sub",
                     "message": {"content": [{"type": "text", "text": "unter"}],
                                 "usage": {"input_tokens": 5}}})
            schreib({"type": "result", "result": "ok", "total_cost_usd": 0,
                     "modelUsage": {
                         "klein-" + NAME: {"contextWindow": 100000},
                         "attrappe-" + NAME: {"contextWindow": 200000,
                                              "maxOutputTokens": 32000}}})
        else:
            text("Antwort %s: %s" % (NAME, inhalt))
            schreib({"type": "result", "result": "ok", "total_cost_usd": 0})
    elif m.get("type") == "control_response":
        r = m.get("response") or {}
        verhalten = (r.get("response") or {}).get("behavior")
        text("%s: %s" % (r.get("request_id"), verhalten))
        name = nochmal.pop(r.get("request_id"), None)
        if name and verhalten == "allow":
            anfrage(name)
            continue
        schreib({"type": "result", "result": "ok"})
log({"eof": True})
if "spaet_frage" in MODUS:
    schreib({"type": "control_request", "request_id": "req-%s-spaet" % NAME,
             "request": {"subtype": "can_use_tool", "tool_name": "Read",
                         "input": {"file_path": "spaet.txt"}}})
    time.sleep(0.5)
if "halten" in MODUS:
    spaet = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "SPAET " + NAME}]}})
    ende = json.dumps({"type": "result", "result": "spaet"})
    code = ("import sys, time\n"
            "time.sleep(%r)\n"
            "sys.stdout.write(%r + '\\n' + %r + '\\n')\n"
            "sys.stdout.flush()\n") % (float(os.environ.get("OMCAD_ATTRAPPE_HALTEN", "3")),
                                       spaet, ende)
    kind = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                            stdout=sys.stdout.fileno(), stderr=sys.stderr.fileno())
    log({"enkel": kind.pid})
if "langsam" in MODUS:
    time.sleep(1.5)
log({"ende": True})
'''


# --- MCP-Server-Attrappe, die JEDE Zeile protokolliert -------------------------
# Wie die aus test_anbieter (dieselben drei Werkzeuge), aber sie schreibt
# ihren Start, alles, was auf stdin ankommt, und das stdin-Ende mit — so
# misst S9, ob ein Server nach dem Beenden noch einen Auftrag bekam.

MCP_ATTRAPPE = r'''
import json, os, sys
LOG = sys.argv[1]

def log(o):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(o) + "\n")

log({"start": os.getpid()})
WERKZEUGE = [{"name": n, "description": n,
              "inputSchema": {"type": "object", "properties": {}}}
             for n in ("get_document_info", "execute_cadwork_command",
                       "get_cadwork_api_help",
                       # Werkzeuge einer Erweiterung (EW2), neutral benannt
                       "lesen_probe_pruefen", "probe_bauen")]
for zeile in sys.stdin:
    m = json.loads(zeile)
    log({"stdin": m})
    if "id" not in m:
        continue
    r = {}
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
             "serverInfo": {"name": "attrappe", "version": "1"}}
    elif m["method"] == "tools/list":
        r = {"tools": WERKZEUGE}
    elif m["method"] == "tools/call":
        r = {"content": [{"type": "text", "text": "ERGEBNIS " + m["params"]["name"]}],
             "isError": False}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
log({"eof": True})
'''

# --- Codex-App-Server, dessen Handshake scheitert ------------------------------
# Beantwortet `initialize` mit einem Fehler (wie eine abgelaufene Anmeldung)
# und wartet dann weiter auf stdin — er endet nur, wenn ihn jemand beendet.

CODEX_HANDSHAKE_FEHLER = r'''
import json, os, sys
LOG = sys.argv[1]

def log(o):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(o) + "\n")

log({"start": os.getpid()})
for zeile in sys.stdin:
    m = json.loads(zeile)
    log({"stdin": m})
    if m.get("method") == "initialize":
        sys.stdout.write(json.dumps({"id": m["id"], "error": {
            "code": -32000, "message": "Anmeldung abgelaufen"}}) + "\n")
        sys.stdout.flush()
log({"eof": True})
'''

# So lange darf das Abraeumen eines Prozesses dauern: stdin zu, bis zu 3 s
# auf das Ende warten, dann taskkill.
FRIST_ABRAEUMEN = 5.0


class Umgebung:
    """Temp-Ordner, claude.cmd-Attrappe, Protokolle, Aufraeumen."""

    def __init__(self):
        self.t = tempfile.mkdtemp(prefix="omcad_chatkern_")
        self.zaehler = itertools.count(1)
        self.skript = os.path.join(self.t, "cli_attrappe.py")
        with io.open(self.skript, "w", encoding="utf-8") as fh:
            fh.write(CLI_ATTRAPPE)
        self.appdata = os.path.join(self.t, "appdata")
        os.makedirs(os.path.join(self.appdata, "npm"))
        self.cmd = os.path.join(self.appdata, "npm", "claude.cmd")
        with io.open(self.cmd, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write('@echo off\n"%s" "%s" %%*\n' % (sys.executable, self.skript))
        self.mcp_skript = os.path.join(self.t, "mcp_protokoll.py")
        with io.open(self.mcp_skript, "w", encoding="utf-8") as fh:
            fh.write(MCP_ATTRAPPE)
        self.chats = []
        self.gespraeche = []

    def mcp_server(self, name):
        """Die protokollierende MCP-Attrappe -> (server, protokoll)."""
        log = os.path.join(self.t, "mcp_%s_%d.log" % (name, next(self.zaehler)))
        return ([sys.executable, self.mcp_skript, log], {}), log

    def cli_start(self, C, chat, name, modus=""):
        """Claude Code starten — ueber das ECHTE `starten`."""
        log = os.path.join(self.t, "cli_%s_%d.log" % (name, next(self.zaehler)))
        os.environ.update(OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME=name,
                          OMCAD_ATTRAPPE_MODUS=modus,
                          OMCAD_ATTRAPPE_HALTEN=str(HALTEN))
        if chat not in self.chats:
            self.chats.append(chat)
        C.starten(chat, self.t, port=1, werkzeuge=False, modell=None,
                  effort=None)
        return log

    def aufraeumen(self, C):
        for g in self.gespraeche:
            try:
                g.beenden()
            except Exception:                           # noqa: BLE001
                pass
        for chat in self.chats:
            try:
                C.beenden(chat)
            except Exception:                           # noqa: BLE001
                pass
            proc = chat.get("proc")
            if proc is not None and proc.poll() is None:
                baum_toeten(proc.pid)


# --- Ein Dienst, der die Antwort zurueckhaelt --------------------------------

class HalteDienst:
    """OpenAI-kompatibel; jede Antwort wartet, bis `freigabe` gesetzt ist.

    So haengt der Arbeitsthread einer alten Schleife in `_http`, waehrend
    der Nutzer beendet und neu startet — wie bei einem langsamen Modell
    (HTTP_TIMEOUT sind 600 s).
    """

    def __init__(self, TA):
        import http.server
        self.angekommen = threading.Event()
        self.freigabe = threading.Event()
        dienst = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                dienst.angekommen.set()
                dienst.freigabe.wait(30)
                roh = json.dumps(TA.text_antwort("SPAET Schleife")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(roh)))
                self.end_headers()
                self.wfile.write(roh)

        self.server = TA._http_dienst(Handler)
        self.port = self.server.server_address[1]
        self.basis = "http://127.0.0.1:%d/v1" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def schliessen(self):
        self.freigabe.set()
        self.server.shutdown()
        self.server.server_close()


# Nie aufgerufen: eine Schleife ohne Nachricht fragt keinen Dienst.
TOTE_BASIS = "http://127.0.0.1:9/v1"


def fehler_bei(fn):
    """-> Text der Ausnahme, oder "gestartet"."""
    try:
        fn()
        return "gestartet"
    except Exception as exc:                            # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)


def mcp_methoden(pfad):
    """Was beim MCP-Server auf stdin ankam (Methoden, in Reihenfolge)."""
    return [e["stdin"].get("method") for e in eintraege(pfad) if "stdin" in e]


def mcp_gerufen(pfad):
    """Die Werkzeuge, die beim MCP-Server WIRKLICH gerufen wurden."""
    return [e["stdin"]["params"]["name"] for e in eintraege(pfad)
            if (e.get("stdin") or {}).get("method") == "tools/call"]


def zwei_aufrufe_antwort():
    """Eine Modellantwort mit ZWEI Werkzeugaufrufen: execute (in 'lesen'
    eine Karte) und get_cadwork_api_help (in 'lesen' automatisch)."""
    aufrufe = [{"id": "call_%d" % i, "type": "function", "function": {
        "name": name, "arguments": json.dumps(argumente)}}
        for i, (name, argumente) in enumerate(
            (("execute_cadwork_command", {"code": "x = 1"}),
             ("get_cadwork_api_help", {})), 1)]
    return {"choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": aufrufe}}],
            "usage": {"total_tokens": 11}}


def dienst_schliessen(D):
    D.server.shutdown()
    D.server.server_close()


def codex_starten(P, C, U, TA, chat, name):
    """Codex ueber das ECHTE `starten` gegen die Attrappe aus test_anbieter.
    -> (gespraech, protokoll der Attrappe)."""
    attrappe = os.path.join(U.t, "codex_attrappe.py")
    if not os.path.isfile(attrappe):
        with io.open(attrappe, "w", encoding="utf-8") as fh:
            fh.write(TA.CODEX_ATTRAPPE)
    log = os.path.join(U.t, "codex_%s_%d.log" % (name, next(U.zaehler)))
    if chat not in U.chats:
        U.chats.append(chat)
    P.starten(chat, "codex", "", C.chat_entscheiden,
              server=([sys.executable, "-c", "pass"], {"OPEN_MCP_CAD_PORT": "1"}),
              codex_befehl=[sys.executable, attrappe, log])
    warte(lambda: chat.get("werkzeuge_da"))
    U.gespraeche.append(chat.get("schleife"))
    return chat.get("schleife"), log


# =============================================================================
# Claude Code (omcad_a_chat)
# =============================================================================

def grundweg(C, U):
    """K1-K3, K5, K6, K10: Start, Nachricht, Karte, Ende, Neustart."""
    chat = {"modus": "fragen"}
    log_a = U.cli_start(C, chat, "A")
    warte(lambda: chat.get("sitzung") == "sitzung-A")
    C.senden(chat, "hallo")
    warte(lambda: "schluss" in arten(chat))
    pruefe("K1 Start: init kommt an (Sitzung, Modell), Chat ist an",
           chat.get("sitzung") == "sitzung-A"
           and chat.get("modell") == "attrappe-A" and chat.get("an"),
           (chat.get("sitzung"), chat.get("modell"), chat.get("an")))
    pruefe("K1 erste Nachricht: ich, text, schluss — Zug beendet",
           arten(chat) == ["ich", "text", "schluss"]
           and texte(chat) == ["Antwort A: hallo"]
           and not chat.get("laeuft_zug"), chat.get("ereignisse"))

    # -- Karte, Erlauben ------------------------------------------------------
    C.senden(chat, "karte bitte")
    warte(lambda: C.offene_freigaben(chat))
    karte = (C.offene_freigaben(chat) or [{}])[0]
    pruefe("K2 can_use_tool wird Karte (Stufe 'alles'), nichts gesendet",
           karte.get("id") == "req-A-1" and karte.get("werkzeug") == "Bash"
           and not antworten_an(log_a, "req-A-1"), karte)
    ok = C.freigabe_beantworten(chat, "req-A-1", True)
    warte(lambda: antworten_an(log_a, "req-A-1")
          and "req-A-1: allow" in texte(chat))
    an_a = antworten_an(log_a, "req-A-1")
    pruefe("K2 Erlauben: genau EINE control_response allow beim Prozess",
           ok and len(an_a) == 1
           and an_a[0]["response"]["response"] == {"behavior": "allow"}
           and "req-A-1: allow" in texte(chat), an_a)

    # -- Beenden mit offener Karte ------------------------------------------
    C.senden(chat, "karte nochmal")
    warte(lambda: C.offene_freigaben(chat))
    alte_karte = (C.offene_freigaben(chat) or [{}])[0]
    # "Nach dem Zug beenden" gewaehlt, dann endet der Chat anders (hier:
    # beenden; im Betrieb z. B. ein abgestuerztes CLI) — der Wunsch bleibt
    # stehen, weil der Qt-Takt ihn nur bei laufendem Chat einloest.
    C.nach_zug_beenden(chat)
    C.beenden(chat)
    nein = antworten_an(log_a, "req-A-2")
    pruefe("K3 Beenden lehnt die offene Karte ab: deny beim ALTEN Prozess",
           len(nein) == 1
           and (nein[0]["response"]["response"] or {}).get("behavior") == "deny",
           nein)
    pruefe("K3 die Karte ist zu (abgelehnt), der Chat aus, kein Prozess mehr",
           alte_karte.get("offen") is False
           and alte_karte.get("antwort") == "abgelehnt"
           and not C.offene_freigaben(chat) and not chat.get("an")
           and chat.get("proc") is None,
           (alte_karte.get("offen"), alte_karte.get("antwort"),
            chat.get("an"), chat.get("proc")))

    # -- Neustart: leer ------------------------------------------------------
    log_b = U.cli_start(C, chat, "B")
    pruefe("K5 ein neuer Chat beginnt leer: kein alter Verlauf, keine Karte",
           chat.get("ereignisse") == [] and chat.get("freigaben") == []
           and C.offene_freigaben(chat) == [],
           (arten(chat), len(chat.get("freigaben") or ())))
    pruefe("K10 'nach dem Zug beenden' des alten Chats gilt nicht fuer den neuen",
           not chat.get("beenden_nach_zug"),
           "sonst beendet der Qt-Takt den neuen Chat im ersten Takt "
           "(laeuft_zug ist dort noch False)")
    warte(lambda: chat.get("sitzung") == "sitzung-B")

    # -- Die alte Karte erreicht den neuen Prozess nie ----------------------
    ok = C.freigabe_beantworten(chat, "req-A-2", True)
    C.senden(chat, "ping")
    warte(lambda: any(m.get("type") == "user" for m in stdin_von(log_b)))
    warte(lambda: "Antwort B: ping" in texte(chat))
    pruefe("K6 'Erlauben' auf die ALTE Karte: nichts geht an den neuen Prozess",
           not ok and not antworten_an(log_b, "req-A-2")
           and "Antwort B: ping" in texte(chat),
           (ok, antworten_an(log_b, "req-A-2")))

    # K6b: selbst wenn die alte Karte wieder in der Liste stuende (ein
    # Nachzuegler im Rennen), haelt der Generationsriegel.
    alte_karte["offen"] = True
    chat["freigaben"].append(alte_karte)
    ok = C.freigabe_beantworten(chat, "req-A-2", True)
    sichtbar = [f.get("id") for f in C.offene_freigaben(chat)]
    C.senden(chat, "ping2")
    warte(lambda: "Antwort B: ping2" in texte(chat))
    pruefe("K6b eine Karte frueherer Generation wird weder gezeigt noch gesendet",
           not ok and "req-A-2" not in sichtbar
           and not antworten_an(log_b, "req-A-2"), (ok, sichtbar))
    alte_karte["generation"] = chat.get("generation")
    ok = C.freigabe_beantworten(chat, "req-A-2", True)
    warte(lambda: antworten_an(log_b, "req-A-2"), 5)
    pruefe("K6b KONTROLLE: mit der Generation des neuen Chats ginge sie hin",
           ok and len(antworten_an(log_b, "req-A-2")) == 1,
           "sonst misst K6/K6b nicht, ob beim Prozess etwas ankommt")
    if alte_karte in chat["freigaben"]:
        chat["freigaben"].remove(alte_karte)

    # -- Eine Karte des NEUEN Chats kommt an ---------------------------------
    C.senden(chat, "karte B")
    warte(lambda: C.offene_freigaben(chat))
    karte_b = (C.offene_freigaben(chat) or [{}])[0]
    ok = C.freigabe_beantworten(chat, karte_b.get("id"), False, "nein danke")
    warte(lambda: antworten_an(log_b, "req-B-1"))
    an_b = antworten_an(log_b, "req-B-1")
    pruefe("K6 KONTROLLE: die Karte des neuen Chats erreicht den neuen Prozess",
           ok and len(an_b) == 1 and an_b[0]["response"]["response"]
           == {"behavior": "deny", "message": "nein danke"}, an_b)
    C.beenden(chat)


def schnell_neu(C, U):
    """K4: Beenden -> sofort Starten, waehrend der alte Prozess noch lebt."""
    chat = {"modus": "fragen"}
    U.cli_start(C, chat, "L", "langsam")
    warte(lambda: chat.get("sitzung") == "sitzung-L")
    proc_alt, gen_alt = chat.get("proc"), chat.get("generation")
    # Genau wie das Dock (_chat_beenden): `an` sofort aus, das Abraeumen
    # (bis zu 3 s) im Hintergrund — und der Nutzer klickt gleich "Starten".
    chat["an"] = False
    ende = threading.Thread(target=C.beenden, args=(chat,), daemon=True)
    ende.start()
    k = fehler_bei(lambda: U.cli_start(C, chat, "M"))
    lebte = proc_alt is not None and proc_alt.poll() is None
    pruefe("K4 Starten, waehrend der alte Prozess noch lebt: klare Ausnahme",
           "VorigerChatLaeuft" in k and "endet noch" in k,
           "%s (alter Prozess lebte: %s)" % (k[:90], lebte))
    pruefe("K4 ... und nichts am Chat veraendert",
           chat.get("generation") == gen_alt and chat.get("proc") in (proc_alt, None),
           (gen_alt, chat.get("generation")))
    ende.join(10)
    k = fehler_bei(lambda: U.cli_start(C, chat, "N"))
    warte(lambda: chat.get("sitzung") == "sitzung-N")
    if k == "gestartet":
        C.senden(chat, "hallo")
        warte(lambda: "Antwort N: hallo" in texte(chat))
    pruefe("K4 KONTROLLE: ist der alte Prozess fort, startet derselbe Aufruf",
           k == "gestartet" and "Antwort N: hallo" in texte(chat), k[:90])
    C.beenden(chat)


def leser_am_prozess(C, U, flut=True):
    """K7/K8: der alte Leser lebt noch (ein Enkel haelt die Pipe), der neue
    Chat startet. -> (vorbedingung, neuer_leser, finally_ok, details)."""
    chat = {"modus": "fragen"}
    U.cli_start(C, chat, "H", "halten")
    warte(lambda: chat.get("sitzung") == "sitzung-H")
    proc_alt = chat.get("proc")
    C.beenden(chat)
    leser_alt = chat.get("leser")
    fehler_alt = chat.get("fehlerleser")
    vorbedingung = (proc_alt is not None and proc_alt.poll() is not None
                    and leser_alt is not None and leser_alt.is_alive()
                    and fehler_alt is not None and fehler_alt.is_alive())
    log_neu = U.cli_start(C, chat, "F", "flut" if flut else "")
    warte(lambda: chat.get("sitzung") == "sitzung-F", 5)
    warte(lambda: {"flut": "stderr"} in eintraege(log_neu), 5 if flut else 0)
    protokoll = eintraege(log_neu)
    neuer_leser = (chat.get("sitzung") == "sitzung-F"
                   and (not flut or ({"flut": "stdout"} in protokoll
                                     and {"flut": "stderr"} in protokoll)))
    # Jetzt schreibt der Enkel seine spaeten Zeilen und schliesst die Pipe:
    # der alte Leser endet und laeuft durch sein `finally`.
    warte(lambda: not leser_alt.is_alive(), HALTEN + 8)
    time.sleep(0.2)
    an = chat.get("an")
    spaet = [x for x in texte(chat) if x.startswith("SPAET")]
    C.senden(chat, "hallo")
    antwortet = warte(lambda: "Antwort F: hallo" in texte(chat), 5)
    C.beenden(chat)
    return vorbedingung, neuer_leser, (an and not spaet and antwortet), (
        an, spaet, antwortet, [list(e) for e in protokoll][:6])


def ohne_leser_blockiert(U):
    """K7 KONTROLLE: dieselbe Flut ohne Leser bleibt stecken."""
    log = os.path.join(U.t, "ohne_leser.log")
    umgebung = dict(os.environ, OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME="O",
                    OMCAD_ATTRAPPE_MODUS="flut")
    proc = subprocess.Popen([U.cmd], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=umgebung, creationflags=CREATE_NO_WINDOW)
    try:
        warte(lambda: {"flut": "stdout"} in eintraege(log), 3)
        return eintraege(log)
    finally:
        baum_toeten(proc.pid)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass


def spaete_frage(C, U):
    """K9: eine Freigabe-Anfrage, die erst NACH dem Beenden kommt."""
    chat = {"modus": "alles_auto"}
    log = U.cli_start(C, chat, "S", "spaet_frage")
    warte(lambda: chat.get("sitzung") == "sitzung-S")
    chat["an"] = False                      # wie das Dock
    C.beenden(chat)
    leser = chat.get("leser")
    warte(lambda: leser is None or not leser.is_alive(), 5)
    spaet = [f for f in chat.get("freigaben") or ()
             if f.get("id") == "req-S-spaet"]
    pruefe("K9 kommt nach dem Beenden noch eine Anfrage: abgelehnt, nicht "
           "automatisch erlaubt (Stufe 'auto')",
           spaet and spaet[0].get("antwort") == "abgelehnt"
           and not spaet[0].get("offen") and "auto" not in arten(chat)
           and {"eof": True} in eintraege(log),
           (spaet, arten(chat)))
    pruefe("K9 ... und keine 'Stoerung' fuer die absichtlich zue Leitung",
           not chat.get("fehler"), chat.get("fehler"))


def leser_stirbt(C, U):
    """K11: das CLI schreibt gueltiges JSON, das kein Objekt ist (`[1]`) —
    der Leser steigt aus, der Prozess wartet weiter auf stdin. Bis
    2026-09-25 lebte er dann weiter, und jeder Start warf fuer immer
    VorigerChatLaeuft. -> (ausgestiegen, zu, fehler, warnung, eof, an, k,
    antwortet)."""
    chat = {"modus": "fragen"}
    log = U.cli_start(C, chat, "V", "kaputt")
    proc, leser = chat.get("proc"), chat.get("leser")
    ausgestiegen = warte(lambda: not leser.is_alive(), 10)
    zu = warte(lambda: proc.poll() is not None, FRIST_ABRAEUMEN)
    fehler = chat.get("fehler") or ""
    warnung = [x for x in texte(chat) if x.startswith("⚠")]
    eof = {"eof": True} in eintraege(log)
    an = chat.get("an")
    k = fehler_bei(lambda: U.cli_start(C, chat, "W"))
    antwortet = False
    if k == "gestartet":
        warte(lambda: chat.get("sitzung") == "sitzung-W")
        C.senden(chat, "hallo")
        antwortet = warte(lambda: "Antwort W: hallo" in texte(chat), 5)
    C.beenden(chat)
    if proc.poll() is None:
        baum_toeten(proc.pid)
    return ausgestiegen, zu, fehler, warnung, eof, an, k, antwortet


# =============================================================================
# Die anderen Anbieter (omcad_a_anbieter) und Wechsel
# =============================================================================

def schleife_spaet(P, C, U, TA, neu_ist_cli=False):
    """Der Arbeitsthread einer beendeten Schleife haengt im HTTP, der neue
    Chat laeuft schon — dann kommt die Antwort. -> (an, spaet, neu_ok)."""
    D = HalteDienst(TA)
    try:
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=D.basis)
        alt = chat.get("schleife")
        U.gespraeche.append(alt)
        C.senden(chat, "rechne")
        D.angekommen.wait(10)
        chat["an"] = False                  # wie das Dock
        C.beenden(chat)
        if neu_ist_cli:
            k = fehler_bei(lambda: U.cli_start(C, chat, "X"))
            warte(lambda: chat.get("sitzung") == "sitzung-X")
        else:
            k = fehler_bei(lambda: P.starten(chat, "eigen", "m",
                                             C.chat_entscheiden,
                                             basis=TOTE_BASIS))
        neu = chat.get("schleife")
        D.freigabe.set()
        warte(lambda: not alt.thread.is_alive(), 10)
        time.sleep(0.2)
        an = chat.get("an")
        spaet = [x for x in texte(chat) if x.startswith("SPAET")]
        neu_ok = k == "gestartet"
        if neu_ist_cli and neu_ok:
            C.senden(chat, "hallo")
            neu_ok = warte(lambda: "Antwort X: hallo" in texte(chat), 5)
        elif neu_ok:
            neu_ok = neu is not None and neu is not alt \
                and neu.thread.is_alive()
        C.beenden(chat)
        return an, spaet, neu_ok, k
    finally:
        D.schliessen()


def schleife_mcp_lebt(P, C, U, TA):
    """S2: Starten, waehrend der MCP-Server der alten Schleife noch lebt."""
    attrappe = os.path.join(U.t, "mcp_attrappe.py")
    with io.open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(TA.MCP_ATTRAPPE)
    server = ([sys.executable, attrappe, os.path.join(U.t, "mcp.log")], {})
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=TOTE_BASIS,
              server=server)
    warte(lambda: chat.get("werkzeuge_da"))
    alt = chat.get("schleife")
    U.gespraeche.append(alt)
    chat["an"] = False                      # wie das Dock, vor dem Abraeumen
    kp = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                      basis=TOTE_BASIS))
    if chat.get("schleife") is not alt:
        U.gespraeche.append(chat.get("schleife"))
    kc = fehler_bei(lambda: U.cli_start(C, chat, "Y"))
    pruefe("S2 Schleife: Starten, solange ihr MCP-Server lebt -> klare Ausnahme",
           "VorigerChatLaeuft" in kp and "endet noch" in kp, kp[:90])
    pruefe("S2 ... auch fuer Claude Code (Wechsel Anbieter -> CLI)",
           "VorigerChatLaeuft" in kc and "endet noch" in kc, kc[:90])
    pruefe("S2 ... und die alte Schleife steht unveraendert im Chat",
           chat.get("schleife") is alt and chat.get("proc") is None,
           (chat.get("schleife") is alt, chat.get("proc")))
    C.beenden(chat)
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    pruefe("S2 KONTROLLE: nach dem Beenden startet derselbe Aufruf",
           k == "gestartet" and chat.get("an")
           and chat.get("schleife") is not alt, k[:90])
    C.beenden(chat)


def codex_spaet(P, C, U, TA):
    """S3: ein abgeloestes Codex-Gespraech meldet sich spaet (beenden(),
    eine letzte Zeile des Lesers, sein finally). -> (an, karte_offen, ...)."""
    chat = {"modus": "fragen"}
    alt = codex_starten(P, C, U, TA, chat, "alt")[0]
    # Der Prozess ist fort, BEVOR der Abraeum-Thread des Docks lief (das Dock
    # setzt `an` sofort zurueck) — der Nutzer startet neu.
    chat["an"] = False
    alt.kanal.beenden()
    warte(lambda: alt.kanal.proc.poll() is not None, 5)
    k = fehler_bei(lambda: codex_starten(P, C, U, TA, chat, "neu"))
    neu = chat.get("schleife")
    C.senden(chat, "zeichne")
    warte(lambda: C.offene_freigaben(chat))
    karte = (C.offene_freigaben(chat) or [None])[0]
    # Jetzt meldet sich das alte Gespraech: sein beenden() (der Abraeum-
    # Thread), eine letzte Zeile seines Lesers, und sein Arbeitsthread endet.
    alt.beenden()
    alt._bearbeiten({"method": "turn/completed",
                     "params": {"turn": {"status": "completed"}}})
    warte(lambda: not alt.thread.is_alive(), 5)
    time.sleep(0.2)
    an, zug = chat.get("an"), chat.get("laeuft_zug")
    offen = bool(karte) and karte.get("offen") is True \
        and karte in C.offene_freigaben(chat)
    schluss = "schluss" in arten(chat)
    fertig = False
    if karte and offen:
        C.freigabe_beantworten(chat, karte["id"], True)
        fertig = warte(lambda: "schluss" in arten(chat), 5)
    C.beenden(chat)
    return an, zug, offen, schluss, fertig, k, neu is not alt


def cli_dann_schleife(P, C, U):
    """S4: Claude Code beendet (Leser lebt noch), dann eine Schleife."""
    chat = {"modus": "fragen"}
    U.cli_start(C, chat, "Z", "halten")
    warte(lambda: chat.get("sitzung") == "sitzung-Z")
    C.beenden(chat)
    leser_alt = chat.get("leser")
    vorbedingung = leser_alt is not None and leser_alt.is_alive()
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    neu = chat.get("schleife")
    if neu is not None:
        U.gespraeche.append(neu)
    warte(lambda: not leser_alt.is_alive(), HALTEN + 8)
    time.sleep(0.2)
    spaet = [x for x in texte(chat) if x.startswith("SPAET")]
    pruefe("S4 Vorbedingung: der Leser des beendeten CLI lebt noch beim Start",
           vorbedingung, "sonst misst S4 kein Rennen")
    pruefe("S4 Claude Code -> Schleife: der alte Leser schaltet sie nicht ab "
           "und schreibt nicht in ihren Verlauf",
           k == "gestartet" and chat.get("an") and chat.get("schleife") is neu
           and not spaet, (k[:60], chat.get("an"), spaet))
    C.beenden(chat)


def cli_dann_anbieter(P, C, U):
    """S5: Claude Code beenden (das CLI laeuft noch aus) -> sofort eine
    Schleife starten; dazu 'nach dem Zug beenden' des CLI."""
    chat = {"modus": "fragen"}
    U.cli_start(C, chat, "Q", "langsam")
    warte(lambda: chat.get("sitzung") == "sitzung-Q")
    C.nach_zug_beenden(chat)
    proc_alt, gen_alt = chat.get("proc"), chat.get("generation")
    chat["an"] = False                      # wie das Dock
    ende = threading.Thread(target=C.beenden, args=(chat,), daemon=True)
    ende.start()
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    lebte = proc_alt is not None and proc_alt.poll() is None
    if chat.get("schleife") is not None:
        U.gespraeche.append(chat["schleife"])
    pruefe("S5 Claude Code -> Schleife, waehrend das CLI noch auslaeuft: "
           "klare Ausnahme", "VorigerChatLaeuft" in k and "endet noch" in k,
           "%s (CLI lebte: %s)" % (k[:90], lebte))
    pruefe("S5 ... und nichts am Chat veraendert",
           chat.get("generation") == gen_alt and chat.get("schleife") is None
           and chat.get("beenden_nach_zug") is True,
           (gen_alt, chat.get("generation"), chat.get("schleife"),
            chat.get("beenden_nach_zug")))
    ende.join(10)
    vorher = chat.get("beenden_nach_zug")
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    neu = chat.get("schleife")
    if neu is not None:
        U.gespraeche.append(neu)
    pruefe("S5 KONTROLLE: ist das CLI fort, startet derselbe Aufruf",
           k == "gestartet" and chat.get("an") and neu is not None, k[:90])
    pruefe("S5 'nach dem Zug beenden' des CLI gilt nicht fuer die Schleife",
           vorher is True and k == "gestartet"
           and not chat.get("beenden_nach_zug"),
           "vorher %r, nachher %r — sonst beendet der Qt-Takt die Schleife im "
           "ersten Takt" % (vorher, chat.get("beenden_nach_zug")))
    C.beenden(chat)


def codex_lebt(P, C, U, TA):
    """S6: Starten, waehrend der App-Server des vorigen Codex noch lebt."""
    chat = {"modus": "fragen"}
    alt = codex_starten(P, C, U, TA, chat, "lebt")[0]
    chat["an"] = False                      # wie das Dock, vor dem Abraeumen
    lebte = alt.kanal is not None and alt.kanal.proc.poll() is None
    kp = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                      basis=TOTE_BASIS))
    if chat.get("schleife") is not alt:
        U.gespraeche.append(chat.get("schleife"))
    kc = fehler_bei(lambda: U.cli_start(C, chat, "R"))
    pruefe("S6 Codex: Starten, solange sein App-Server lebt -> klare Ausnahme "
           "(Schleife UND Claude Code)",
           "VorigerChatLaeuft" in kp and "VorigerChatLaeuft" in kc,
           (kp[:60], kc[:60], "App-Server lebte: %s" % lebte))
    pruefe("S6 ... und der alte Codex steht unveraendert im Chat",
           chat.get("schleife") is alt and chat.get("proc") is None,
           (chat.get("schleife") is alt, chat.get("proc")))
    C.beenden(chat)
    warte(lambda: alt.kanal.proc.poll() is not None, FRIST_ABRAEUMEN)
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    neu = chat.get("schleife")
    if neu is not alt:
        U.gespraeche.append(neu)
    pruefe("S6 KONTROLLE: nach dem Beenden startet derselbe Aufruf",
           k == "gestartet" and chat.get("an") and neu is not alt, k[:90])
    C.beenden(chat)


def schleife_spaete_antwort(P, C, U, TA, beenden=True):
    """S7: die Schleife wird beendet, waehrend das Modell rechnet — und es
    startet KEIN neuer Chat, der Verlauf im Dock ist noch ihrer.
    -> spaete Texte im Verlauf."""
    D = HalteDienst(TA)
    try:
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=D.basis)
        alt = chat.get("schleife")
        U.gespraeche.append(alt)
        C.senden(chat, "rechne")
        D.angekommen.wait(10)
        if beenden:
            chat["an"] = False              # wie das Dock
            C.beenden(chat)
        D.freigabe.set()
        warte(lambda: "schluss" in arten(chat), 10)
        if beenden:
            warte(lambda: not alt.thread.is_alive(), 10)
        time.sleep(0.2)
        spaet = [x for x in texte(chat) if x.startswith("SPAET")]
        C.beenden(chat)
        return spaet
    finally:
        D.schliessen()


def zwei_aufrufe(P, C, U, TA, beenden=True):
    """S8: das Modell will zwei Werkzeuge. Das erste wartet auf seine Karte,
    das zweite ginge in 'lesen' automatisch durch. Beendet der Nutzer bei
    offener Karte, darf das zweite nicht mehr laufen.
    -> (karte, auto, abgelehnt, gerufen)."""
    D = TA.Dienst()
    try:
        D.drehbuch[:] = [(200, zwei_aufrufe_antwort()),
                         (200, TA.text_antwort("fertig"))]
        server, log = U.mcp_server("zwei")
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=D.basis,
                  server=server)
        alt = chat.get("schleife")
        U.gespraeche.append(alt)
        warte(lambda: chat.get("werkzeuge_da"))
        C.senden(chat, "zwei")
        warte(lambda: C.offene_freigaben(chat))
        karte = (C.offene_freigaben(chat) or [{}])[0]
        if beenden:
            chat["an"] = False              # wie das Dock
            C.beenden(chat)
        else:
            C.freigabe_beantworten(chat, karte.get("id"), True)
        warte(lambda: "schluss" in arten(chat), 10)
        warte(lambda: not beenden or not alt.thread.is_alive(), 10)
        auto = [e.get("werkzeug") for e in chat.get("ereignisse") or ()
                if e.get("art") == "auto"]
        schluss = [e for e in chat.get("ereignisse") or ()
                   if e.get("art") == "schluss"]
        abgelehnt = schluss[0].get("abgelehnt") if schluss else None
        gerufen = mcp_gerufen(log)
        C.beenden(chat)
        return karte.get("werkzeug"), auto, abgelehnt, gerufen
    finally:
        dienst_schliessen(D)


def beenden_vor_server(P, C, U, frueh=True):
    """S9: beenden() kommt, bevor der Arbeitsthread den MCP-Server
    eingetragen hat — es kann ihn nicht sehen. Nachgestellt, indem die
    Schleife beendet wird, bevor ihr Thread laeuft.
    -> (methoden beim Server, gestartet, zu, mcp, werkzeuge_da)."""
    server, log = U.mcp_server("frueh")
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    s = P.Schleife(chat, P.anbieter("eigen"), TOTE_BASIS, "m", None, server,
                   C.chat_entscheiden)
    U.gespraeche.append(s)
    if frueh:
        s.beenden()
    s.thread.start()
    if frueh:
        warte(lambda: not s.thread.is_alive(), 10)
    else:
        warte(lambda: "tools/list" in mcp_methoden(log), 10)
    methoden = mcp_methoden(log)
    gestartet = any("start" in e for e in eintraege(log))
    zu = {"eof": True} in eintraege(log)
    mcp, werkzeuge_da = s.mcp, chat.get("werkzeuge_da")
    s.beenden()
    return methoden, gestartet, zu, mcp, werkzeuge_da


def schleife_spaetes_beenden(P, C, U, TA, kontrolle=False):
    """S10 (wie S3, fuer die Schleife): das spaete beenden() einer
    abgeloesten Schleife — der Abraeum-Thread des Docks — trifft die offene
    Karte des neuen Chats nicht. -> (k, an, offen, fertig)."""
    D = TA.Dienst()
    try:
        D.drehbuch[:] = [
            (200, TA.aufruf_antwort("execute_cadwork_command", {"code": "x = 1"})),
            (200, TA.text_antwort("fertig"))]
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        # Die alte Schleife ohne Server: nichts von ihr lebt, der neue Chat
        # darf sofort starten.
        P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=TOTE_BASIS)
        alt = chat.get("schleife")
        U.gespraeche.append(alt)
        chat["an"] = False                  # wie das Dock, vor dem Abraeumen
        server, log = U.mcp_server("neu")
        k = fehler_bei(lambda: P.starten(chat, "eigen", "m",
                                         C.chat_entscheiden,
                                         basis=D.basis, server=server))
        neu = chat.get("schleife")
        if neu is not alt:
            U.gespraeche.append(neu)
        warte(lambda: chat.get("werkzeuge_da"))
        C.senden(chat, "zeichne")
        warte(lambda: C.offene_freigaben(chat))
        karte = (C.offene_freigaben(chat) or [None])[0]
        if kontrolle:
            # So war es bis 2026-09-25: beenden() las chat["freigaben"],
            # also die Karten dessen, der gerade im Dict steht.
            alt.freigaben = chat.get("freigaben")
        alt.beenden()
        time.sleep(0.2)
        an = chat.get("an")
        offen = bool(karte) and karte.get("offen") is True \
            and karte in C.offene_freigaben(chat)
        fertig = False
        if offen:
            C.freigabe_beantworten(chat, karte["id"], True)
            fertig = warte(lambda: "schluss" in arten(chat), 5) \
                and mcp_gerufen(log) == ["execute_cadwork_command"]
        C.beenden(chat)
        return k, an, offen, fertig
    finally:
        dienst_schliessen(D)


# Eine Freigabe-Frage des Codex-App-Servers, wie codex-cli sie stellt.
CODEX_FRAGE = {"id": 55, "method": "mcpServer/elicitation/request", "params": {
    "serverName": "open-mcp-cad", "mode": "form",
    "message": 'Allow the open-mcp-cad MCP server to run tool '
               '"execute_cadwork_command"?',
    "_meta": {"codex_approval_kind": "mcp_tool_call",
              "tool_params": {"code": "x = 1"}}}}


def codex_frage_nach_ende(P, C, U, TA, aus=True):
    """S11: eine Freigabe-Frage erreicht ein Codex-Gespraech, das gerade
    beendet wird — `aus` steht, der Kanal ist noch offen (der Moment in
    beenden() vor kanal.beenden()). Stufe 'auto'. Die Frage geht an
    `_bearbeiten`, den Eingang, den der Leserthread fuer jede Zeile ruft.
    -> (antwort beim App-Server, auto im Verlauf)."""
    chat = {"modus": "alles_auto"}
    alt, log = codex_starten(P, C, U, TA, chat, "frage")

    def antwort():
        return next(((e["antwort"].get("result")) for e in eintraege(log)
                     if (e.get("antwort") or {}).get("id") == 55), None)

    alt.aus = aus
    alt._bearbeiten(json.loads(json.dumps(CODEX_FRAGE)))
    warte(lambda: antwort() is not None, 5)
    ergebnis = antwort(), "auto" in arten(chat)
    C.beenden(chat)
    return ergebnis


def codex_handshake_scheitert(P, C, U):
    """S12: der Codex-App-Server lehnt den Handshake ab. -> (zu, fehler, an,
    k, pid)."""
    attrappe = os.path.join(U.t, "codex_handshake.py")
    with io.open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(CODEX_HANDSHAKE_FEHLER)
    log = os.path.join(U.t, "codex_handshake_%d.log" % next(U.zaehler))
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    P.starten(chat, "codex", "", C.chat_entscheiden,
              codex_befehl=[sys.executable, attrappe, log])
    alt = chat.get("schleife")
    U.gespraeche.append(alt)
    warte(lambda: not alt.thread.is_alive(), 10)
    zu = warte(lambda: {"eof": True} in eintraege(log), FRIST_ABRAEUMEN)
    fehler, an = chat.get("fehler") or "", chat.get("an")
    k = fehler_bei(lambda: P.starten(chat, "eigen", "m", C.chat_entscheiden,
                                     basis=TOTE_BASIS))
    if chat.get("schleife") is not alt:
        U.gespraeche.append(chat.get("schleife"))
    C.beenden(chat)
    pid = next((e["start"] for e in eintraege(log) if "start" in e), None)
    if not zu and pid:
        baum_toeten(pid)                    # der Waise, falls es einen gibt
    return zu, fehler, an, k


def codex_handshake_ohne_abraeumen(P, U):
    """S12 KONTROLLE: derselbe App-Server, direkt ueber den Kanal gestartet,
    und niemand raeumt nach dem gescheiterten Handshake ab.
    -> (fehler, lebt_weiter)."""
    attrappe = os.path.join(U.t, "codex_handshake.py")
    log = os.path.join(U.t, "codex_handshake_k_%d.log" % next(U.zaehler))
    kanal = P._RpcKanal([sys.executable, attrappe, log], lambda m: None)
    try:
        k = fehler_bei(lambda: kanal.rufen("initialize", {}, timeout=10))
        lebt = not warte(lambda: {"eof": True} in eintraege(log), 1.5) \
            and kanal.proc.poll() is None
        return k, lebt
    finally:
        kanal.beenden()


# =============================================================================
# Die Dock-Anweisung: reiner Text, Sprache des Nutzers (Film 2026-09-25)
# =============================================================================

def klartext_regel(text):
    """Traegt diese Anweisung die Regel des Docks? Gemessen wird an dem, was
    ANKOMMT (Befehlszeile, Nutzlast) — nicht am Quelltext."""
    t = (text or "").lower()
    return ("reinen text" in t and "kein markdown" in t
            and "sprache des nutzers" in t)


def voller_text(text, anweisung):
    """Steht `anweisung` VOLLSTAENDIG und wortgleich in `text`?

    Gegenpruefung 2026-09-26: die Stichwoerter von `klartext_regel` hielten
    auch, wenn in einer der beiden Kopien ein Satz fehlte (Mutant M19) oder
    der Sprachsatz verdreht war (M26). Der Wortlaut ist am echten CLI
    gemessen — kuerzere Fassungen hielten messbar nicht."""
    return bool(anweisung) and anweisung in (text or "")


def quell_konstante(quelltext, name="DOCK_ANWEISUNG"):
    """Der Wert einer Konstanten, gelesen aus dem QUELLTEXT (ohne ihn
    auszufuehren). None, wenn sie fehlt oder kein Literal ist."""
    import ast
    for k in ast.parse(quelltext).body:
        if (isinstance(k, ast.Assign) and len(k.targets) == 1
                and isinstance(k.targets[0], ast.Name)
                and k.targets[0].id == name):
            try:
                return ast.literal_eval(k.value)
            except ValueError:
                return None
    return None


def quelle_mit(quelltext, neuer_wert, name="DOCK_ANWEISUNG"):
    """Derselbe Quelltext, nur mit `name = neuer_wert` (fuer Kontrollen)."""
    import ast
    baum = ast.parse(quelltext)
    for k in baum.body:
        if (isinstance(k, ast.Assign) and len(k.targets) == 1
                and isinstance(k.targets[0], ast.Name)
                and k.targets[0].id == name):
            k.value = ast.Constant(neuer_wert)
    return ast.unparse(baum)


def dock_anweisung_quellen():
    """(Quelltext omcad_a_chat.py, Quelltext omcad_a_anbieter.py) aus quelle()."""
    texte = []
    for datei in ("omcad_a_chat.py", "omcad_a_anbieter.py"):
        with io.open(os.path.join(quelle(), datei), encoding="utf-8") as fh:
            texte.append(fh.read())
    return tuple(texte)


def ohne_satz(text):
    """Mutant wie M19: ein Satz aus der Mitte fehlt."""
    saetze = text.split(". ")
    return ". ".join(saetze[:2] + saetze[3:])


def sprache_verdreht(text):
    """Mutant wie M26: der Sprachsatz verdreht (deutsch <-> englisch)."""
    return (text.replace("deutsche deutsch", "deutsche \x00")
            .replace("englische englisch", "englische deutsch")
            .replace("\x00", "englisch"))


def dock_anweisung_wege(P, C, U, TA, name="M"):
    """Was in den drei Wegen als Anweisung an das Modell ankommt.

    -> (Claude Code: der Wert hinter --append-system-prompt, so wie ihn der
        Prozess HINTER claude.cmd sieht — also nach cmd.exe;
        Schleife: die Systemnachricht der ersten POST-Nutzlast;
        Codex: developerInstructions aus thread/start)."""
    chat = {"modus": "fragen"}
    log = U.cli_start(C, chat, name)
    warte(lambda: any("argv" in e for e in eintraege(log)))
    argv = next((e["argv"] for e in eintraege(log) if "argv" in e), [])
    C.beenden(chat)
    cli = (argv[argv.index("--append-system-prompt") + 1]
           if "--append-system-prompt" in argv[:-1] else None)

    dienst = TA.Dienst()
    try:
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        P.starten(chat, "eigen", "alpha-chat", C.chat_entscheiden,
                  basis=dienst.basis, dokument="Seeblick.3d", port=1)
        U.gespraeche.append(chat.get("schleife"))
        C.senden(chat, "hallo")
        warte(lambda: "schluss" in arten(chat))
        posts = dienst.posts()
        nachrichten = (posts[0][2].get("messages") or []) if posts else []
        schleife = next((m.get("content") for m in nachrichten
                         if m.get("role") == "system"), None)
        C.beenden(chat)
    finally:
        dienst_schliessen(dienst)

    chat = {"modus": "fragen"}
    _g, log = codex_starten(P, C, U, TA, chat, name)
    start = next((e["thread_start"] for e in eintraege(log)
                  if "thread_start" in e), {})
    C.beenden(chat)
    return cli, schleife, start.get("developerInstructions")


# --- Etappe D: Kennzeichnung, Fortsetzen, Kontext ------------------------------

def etappe_d_lauf(C, U, name, **start):
    """Ein Start ueber das ECHTE `starten` (Attrappe im Modus "nutzung"), eine
    Nachricht, Ende. -> (argv hinter claude.cmd, Ereignisse, kontext)."""
    log = os.path.join(U.t, "cli_%s_%d.log" % (name, next(U.zaehler)))
    os.environ.update(OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME=name,
                      OMCAD_ATTRAPPE_MODUS="nutzung")
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    C.starten(chat, U.t, port=1, werkzeuge=False, modell=None, effort=None,
              **start)
    warte(lambda: chat.get("modell"))
    C.senden(chat, "hallo")
    warte(lambda: "schluss" in arten(chat))
    argv = next((e["argv"] for e in eintraege(log) if "argv" in e), [])
    C.beenden(chat)
    return argv, list(chat.get("ereignisse") or ()), chat.get("kontext")


def etappe_d(C, U):
    """D1-D4 (Etappe D, S9/S10): was beim PROZESS ankommt, und was der Leser
    aus seinen Zahlen macht. Kontrollen: Mutanten aus der Quelle."""
    marke = getattr(C, "SITZUNG_NAME", None)

    def urteil(M, name):
        neu = etappe_d_lauf(M, U, name + "n")
        fort = etappe_d_lauf(M, U, name + "f", sitzung="abcd-1234",
                             vorher=[{"art": "ich", "text": "alt", "alt": True}])
        return {
            "neu_n": neu[0][neu[0].index("-n") + 1]
            if "-n" in neu[0][:-1] else None,
            "neu_resume": "--resume" in neu[0],
            "fort_resume": fort[0][fort[0].index("--resume") + 1]
            if "--resume" in fort[0][:-1] else None,
            "fort_fork": "--fork-session" in fort[0],
            "fort_n": "-n" in fort[0],
            "fort_arten": [e.get("art") for e in fort[1]],
            "fort_erstes": fort[1][0] if fort[1] else None,
            "kontext": neu[2],
        }
    m = urteil(C, "D")
    pruefe("D1 ein neuer Chat traegt die Kennzeichnung (-n %s), so wie sie "
           "hinter claude.cmd ankommt, und kein --resume" % marke,
           bool(marke) and m["neu_n"] == marke and not m["neu_resume"], m)
    pruefe("D2 fortsetzen: --resume <Sitzung> OHNE --fork-session und ohne "
           "neue Kennzeichnung (Entscheid: dieselbe Sitzung)",
           m["fort_resume"] == "abcd-1234" and not m["fort_fork"]
           and not m["fort_n"], m)
    pruefe("D3 der alte Verlauf steht vor der neuen Nachricht",
           m["fort_arten"][:3] == ["ich", "ich", "text"]
           and (m["fort_erstes"] or {}).get("alt") is True, m)
    pruefe("D4 Kontext aus usage (input + cache) und modelUsage des "
           "Chat-Modells, der Unter-Agent zaehlt nicht",
           m["kontext"] == {"belegt": 130168, "fenster": 200000}, m["kontext"])
    q = os.path.join(quelle(), "omcad_a_chat.py")
    with io.open(q, encoding="utf-8") as fh:
        text = fh.read()
    for was, alt, neu, rot in (
            ("ohne Kennzeichnung", "    elif name:\n",
             "    elif False:\n", lambda k: k["neu_n"] is None),
            ("immer abzweigen", "        if abzweigen:\n",
             "        if True:\n", lambda k: k["fort_fork"]),
            ("ohne vorher", "chat.update(ereignisse=list(vorher or ()),",
             "chat.update(ereignisse=[],",
             lambda k: not (k["fort_erstes"] or {}).get("alt")),
            ("ohne Cache-Anteile", 'for feld in ("input_tokens", '
             '"cache_creation_input_tokens",\n                 '
             '"cache_read_input_tokens"):',
             'for feld in ("input_tokens",):',
             lambda k: (k["kontext"] or {}).get("belegt") == 10),
            ("Unter-Agent zaehlt mit",
             'if not ev.get("parent_tool_use_id"):', "if True:",
             lambda k: (k["kontext"] or {}).get("belegt") == 5),
            ("irgendein Modell statt dem des Chats",
             "eintrag = model_usage.get(modell) if modell else None",
             "eintrag = next(iter(model_usage.values()))",
             lambda k: (k["kontext"] or {}).get("fenster") == 100000)):
        treffer = text.count(alt)
        M = type(sys)("_chat_kern_d_mutant")
        M.__file__ = q
        exec(compile(text.replace(alt, neu), q, "exec"), M.__dict__)
        k = urteil(M, "K")
        pruefe("D KONTROLLE: %s -> rot" % was, treffer == 1 and rot(k),
               (treffer, k))
    # D5 (Nacharbeit D, Mutant C8): fehlt das Modell des Chats in
    # `modelUsage` und stehen dort MEHRERE, ist das Fenster unbekannt — kein
    # beliebiges. Genau der offene Fall mit "[1m]" im Modellnamen.
    def fenster(M):
        return (M._kontext_fenster({"klein": {"contextWindow": 100000},
                                    "gross": {"contextWindow": 1000000}},
                                   "gross[1m]"),
                M._kontext_fenster({"nur": {"contextWindow": 200000}},
                                   "gross[1m]"),
                M._kontext_fenster({"klein": {"contextWindow": 100000},
                                    "gross": {"contextWindow": 1000000}},
                                   "gross"))
    f = fenster(C)
    pruefe("D5 ohne das eigene Modell und mit mehreren in modelUsage: kein "
           "Fenster (nur die Token); mit einem einzigen: dessen",
           f == (None, 200000, 1000000), f)
    alt = "    if eintrag is None and len(model_usage) == 1:"
    M = type(sys)("_chat_kern_d5_mutant")
    M.__file__ = q
    exec(compile(text.replace(alt, "    if eintrag is None:"), q, "exec"),
         M.__dict__)
    k = fenster(M)
    pruefe("D5 KONTROLLE: ohne 'nur ein einziges' nimmt es irgendein "
           "Fenster -> rot", text.count(alt) == 1 and k[0] is not None,
           (text.count(alt), k))


# --- Nacharbeit D: laeuft die Sitzung in einem anderen Cadwork? ----------------

def _vermerk(kennung, pid, seit, besitzer):
    """Ein Vermerk, wie ihn `_belegen` im Dock eines ANDEREN Cadwork schreibt."""
    ordner = os.environ["OPEN_MCP_CAD_BELEGT"]
    os.makedirs(ordner, exist_ok=True)
    with io.open(os.path.join(ordner, kennung + ".json"), "w",
                 encoding="utf-8") as fh:
        json.dump({"sitzung": kennung, "pid": pid, "seit": seit,
                   "besitzer": besitzer}, fh)


def _vermerk_lesen(kennung):
    try:
        with io.open(os.path.join(os.environ["OPEN_MCP_CAD_BELEGT"],
                                  kennung + ".json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def belegt_lauf(C, U, name):
    """E1-E4 ueber das ECHTE `starten` gegen die Attrappe. -> dict."""
    m = {}

    def start(chat, kennung, **k):
        log = os.path.join(U.t, "cli_%s_%d.log" % (kennung, next(U.zaehler)))
        os.environ.update(OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME=kennung,
                          OMCAD_ATTRAPPE_MODUS="")
        U.chats.append(chat)
        try:
            C.starten(chat, U.t, port=1, werkzeuge=False, modell=None,
                      effort=None, **k)
            return "gestartet", log
        except Exception as exc:                        # noqa: BLE001
            return type(exc).__name__ + ": " + str(exc), log

    # E1: ein neuer Chat traegt seine Sitzung ein, sobald das CLI sie nennt.
    chat = {"modus": "fragen"}
    start(chat, name + "a")
    warte(lambda: chat.get("modell"))
    sid = chat.get("sitzung")
    fremd_sieht = warte(lambda: C.sitzung_belegt(sid, ich=-1), 3.0)
    m["neu"] = (sid, fremd_sieht, C.sitzung_belegt(sid))
    proc = chat.get("proc")
    C.beenden(chat)
    m["frei"] = (warte(lambda: not C.sitzung_belegt(sid, ich=-1), 5.0),
                 warte(lambda: _vermerk_lesen(sid) is None, 5.0),
                 proc is not None and proc.poll() is not None)
    # E2: ein anderes Cadwork fuehrt "fremd-<name>" (ein lebendes Kind).
    kennung = "fremd-" + name
    kind = subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(60)"])
    try:
        _vermerk(kennung, kind.pid, time.time(), os.getpid() + 1)
        chat2 = {"modus": "fragen"}
        k, log = start(chat2, name + "b", sitzung=kennung)
        time.sleep(0.5)
        m["fremd"] = (k, [e for e in eintraege(log) if "start" in e],
                      chat2.get("an"), chat2.get("proc"),
                      (_vermerk_lesen(kennung) or {}).get("pid") == kind.pid)
        if k == "gestartet":
            C.beenden(chat2)
        # ... abzweigen ist erlaubt: das schreibt in eine NEUE Datei.
        chat4 = {"modus": "fragen"}
        k4, log4 = start(chat4, name + "d", sitzung=kennung, abzweigen=True)
        warte(lambda: any("argv" in e for e in eintraege(log4)), 5.0)
        argv4 = next((e["argv"] for e in eintraege(log4) if "argv" in e), [])
        m["abzweigen"] = (k4, "--fork-session" in argv4)
        if k4 == "gestartet":
            C.beenden(chat4)
    finally:
        kind.kill()
        kind.wait()
    # E3: der fremde Prozess ist fort -> derselbe Aufruf startet, und der
    # Vermerk gehoert jetzt diesem Chat (schon vor dem init des CLI).
    chat3 = {"modus": "fragen"}
    k3, log3 = start(chat3, name + "c", sitzung=kennung)
    warte(lambda: any("argv" in e for e in eintraege(log3)), 5.0)
    argv = next((e["argv"] for e in eintraege(log3) if "argv" in e), [])
    v = _vermerk_lesen(kennung) or {}
    m["danach"] = (k3, argv[argv.index("--resume") + 1]
                   if "--resume" in argv[:-1] else None,
                   v.get("pid") == getattr(chat3.get("proc"), "pid", None),
                   v.get("besitzer") == os.getpid())
    if k3 == "gestartet":
        C.beenden(chat3)
    return m


def belegt(C, U):
    """E1-E4 (Nacharbeit D, Befund mittel): ein Chat, den das Dock eines
    ANDEREN Cadwork gerade fuehrt, wird nicht fortgesetzt. Kontrollen:
    Mutanten aus der Quelle."""
    m = belegt_lauf(C, U, "E")
    pruefe("E1 ein neuer Chat traegt seine Sitzung ein, sobald das CLI sie "
           "nennt: fuer ein anderes Cadwork belegt, fuer das eigene nicht",
           m["neu"][0] and m["neu"][1:] == (True, False), m["neu"])
    pruefe("E1 nach dem Ende: frei, und der Vermerk ist weg",
           m["frei"] == (True, True, True), m["frei"])
    pruefe("E2 fortsetzen, was ein lebender Prozess eines anderen Cadwork "
           "fuehrt: SitzungBelegt, kein Prozess, der Chat unveraendert, der "
           "fremde Vermerk bleibt",
           m["fremd"][0].startswith("SitzungBelegt")
           and m["fremd"][1:] == ([], None, None, True), m["fremd"])
    pruefe("E2 abzweigen (neue Datei) bleibt erlaubt",
           m["abzweigen"] == ("gestartet", True), m["abzweigen"])
    pruefe("E3 ist der fremde Prozess fort, startet derselbe Aufruf (--resume) "
           "und der Vermerk gehoert jetzt diesem Chat",
           m["danach"] == ("gestartet", "fremd-E", True, True), m["danach"])
    q = os.path.join(quelle(), "omcad_a_chat.py")
    with io.open(q, encoding="utf-8") as fh:
        text = fh.read()
    for was, alt, neu, rot in (
            ("starten ohne Pruefung",
             "    if sitzung and not abzweigen and sitzung_belegt(sitzung):\n"
             "        raise SitzungBelegt(SITZUNG_BELEGT)\n", "",
             lambda k: k["fremd"][0] == "gestartet"),
            ("kein Vermerk beim init",
             '        if proc is not None and ev.get("session_id"):\n'
             '            _belegen(ev["session_id"], proc)',
             "        pass", lambda k: k["neu"][1] is False),
            ("kein Vermerk beim Fortsetzen (erst das init)",
             "        _belegen(sitzung, proc)           # ab jetzt sieht jedes "
             "Dock es\n", "        pass\n",
             lambda k: k["danach"][2] is False),
            ("der Vermerk bleibt nach dem Ende liegen",
             "            _freigeben(proc)\n", "            pass\n",
             lambda k: k["frei"][1] is False)):
        treffer = text.count(alt)
        M = type(sys)("_chat_kern_e_mutant")
        M.__file__ = q
        exec(compile(text.replace(alt, neu), q, "exec"), M.__dict__)
        k = belegt_lauf(M, U, "K")
        pruefe("E KONTROLLE: %s -> rot" % was, treffer == 1 and rot(k),
               (treffer, k))


# =============================================================================
# Die vier Modi (Wunsch 2026-09-27): EINE Politik, drei Wege
# =============================================================================

CAD = "mcp__open-mcp-cad__execute_cadwork_command"
LESEN_CAD = "mcp__open-mcp-cad__get_document_info"


def laden_mit(name, datei, alt, neu):
    """Das Modul aus der QUELLE mit `alt` -> `neu` (Kontrollen).
    -> (Modul, Treffer); 0 Treffer heisst: keine Kontrolle, Zelle rot."""
    pfad = os.path.join(quelle(), datei)
    with io.open(pfad, encoding="utf-8") as fh:
        text = fh.read()
    modul = type(sys)(name)
    modul.__file__ = pfad
    exec(compile(text.replace(alt, neu), pfad, "exec"), modul.__dict__)
    return modul, text.count(alt)


def antwort_an(log, kennung):
    """(behavior, message) der EINEN control_response fuer `kennung` — oder
    None, wenn keine oder mehrere ankamen."""
    a = antworten_an(log, kennung)
    if len(a) != 1:
        return None
    r = a[0]["response"]["response"] or {}
    return r.get("behavior"), r.get("message", "")


def cli_modus_lauf(C, U, modus, nachrichten, name, antworten=None):
    """Claude Code (Attrappe) im Modus `modus`: je Nachricht warten, bis
    ihre Anfragen beantwortet sind — Karten beantwortet `antworten(chat,
    karte)` (sonst bleiben sie offen). -> (chat, log, karten_je_nachricht)."""
    chat = {"modus": modus}
    log = U.cli_start(C, chat, name)
    warte(lambda: chat.get("sitzung") == "sitzung-" + name)
    karten = []
    for text in nachrichten:
        vorher = {f["id"] for f in chat.get("freigaben") or ()}
        C.senden(chat, text)
        erwartet = text.count("werkzeug:") + text.count("*2")
        ende = time.monotonic() + 10
        gezeigt = []
        while time.monotonic() < ende:
            for f in list(C.offene_freigaben(chat)):
                if f["id"] not in vorher and f["id"] not in gezeigt:
                    gezeigt.append(f["id"])
                    if antworten is not None:
                        antworten(chat, f)
            neu = [f for f in chat.get("freigaben") or ()
                   if f["id"] not in vorher]
            if len(neu) >= erwartet and all(
                    antworten_an(log, f["id"]) or f.get("offen")
                    for f in neu):
                if antworten is None or not C.offene_freigaben(chat):
                    break
            time.sleep(0.02)
        karten.append(gezeigt)
        time.sleep(0.15)
    return chat, log, karten


def sperr_grund_ok(text, werkzeug):
    """Traegt der Grund einer Ablehnung durch "Nur lesen", was die KI
    braucht (Rueckmeldung 2026-09-28)?"""
    t = text or ""
    return ("«Nur lesen»" in t and werkzeug in t and "mcp__" not in t
            and "Hinweis" in t and "«Fragen»" in t
            and "was du tun wolltest" in t
            and "nicht erneut" in t.lower())


def modi_cli(C, U):
    """MO1-MO7: der Claude-Code-Weg — was beim PROZESS ankommt."""
    # -- MO1 Nur lesen: Aendern und Aeusseres ohne Frage abgelehnt ----------
    chat, log, karten = cli_modus_lauf(
        C, U, "nur_lesen",
        ["werkzeug:%s werkzeug:Write werkzeug:Read werkzeug:%s"
         % (CAD, LESEN_CAD)], "L1")
    antw = [antwort_an(log, "req-L1-%d" % i) for i in range(1, 5)]
    pruefe("MO1 Nur lesen: execute und Write ohne Karte abgelehnt (deny mit "
           "Grund), Read und get_document_info erlaubt",
           karten == [[]] and antw[0] and antw[0][0] == "deny"
           and "Nur lesen" in antw[0][1] and antw[1] and antw[1][0] == "deny"
           and antw[2] == ("allow", "") and antw[3] == ("allow", ""),
           (karten, antw))
    pruefe("MO1 ... und der Verlauf zeigt beide Ablehnungen",
           arten(chat).count("verweigert") == 2
           and [e.get("werkzeug") for e in chat["ereignisse"]
                if e.get("art") == "verweigert"] == [CAD, "Write"],
           arten(chat))
    # SP1 (Rueckmeldung 2026-09-28): der Grund sagt der KI, dass der Nutzer
    # einen Hinweis sieht, den Modus wechseln kann, und dass sie sagen soll,
    # was sie wollte — mit dem kurzen Werkzeugnamen, ohne MCP-Praefix.
    grund = antw[0][1] if antw[0] else ""
    pruefe("SP1 CLI, Nur lesen: der Grund nennt den Hinweis im Chat, den "
           "Wechsel nach «Fragen» und verlangt zu sagen, was die KI wollte",
           sperr_grund_ok(grund, "execute_cadwork_command"), grund)
    C.beenden(chat)
    M, n = laden_mit("_chat_sp1", "omcad_a_chat.py",
                     '"einen Hinweis und kann dort mit einem Klick in den '
                     'Modus «Fragen» "', '"nichts. "')
    k_chat, k_log, _k = cli_modus_lauf(M, U, "nur_lesen",
                                       ["werkzeug:%s" % CAD], "SP1K")
    k_antw = antwort_an(k_log, "req-SP1K-1")
    pruefe("SP1 KONTROLLE: ohne den Satz zum Hinweis ist der Grund rot",
           n == 1 and k_antw and k_antw[0] == "deny"
           and not sperr_grund_ok(k_antw[1], "execute_cadwork_command"),
           k_antw)
    M.beenden(k_chat)
    M, n = laden_mit("_chat_mo1", "omcad_a_chat.py",
                     'return "ja" if art == "lesen" and not draussen else "nein"',
                     'return "ja" if art == "lesen" and not draussen '
                     'else "fragen"')
    k_chat, k_log, k_karten = cli_modus_lauf(
        M, U, "nur_lesen", ["werkzeug:%s" % CAD], "L1K")
    pruefe("MO1 KONTROLLE: fragt Nur lesen statt abzulehnen, kommt eine Karte "
           "und beim Prozess nichts", n == 1 and k_karten == [["req-L1K-1"]]
           and antwort_an(k_log, "req-L1K-1") is None, (n, k_karten))
    M.beenden(k_chat)

    # -- MO2 Fragen: einmal je Art bis zur naechsten Nachricht ---------------
    def erlauben(chat, f):
        C.freigabe_beantworten(chat, f["id"], True)
    chat, log, karten = cli_modus_lauf(
        C, U, "fragen", ["werkzeug:Bash*2", "werkzeug:Bash"], "F2", erlauben)
    pruefe("MO2 Fragen: die erste Bash-Anfrage kommt als Karte, die zweite "
           "im selben Zug laeuft ohne Karte (dieselbe Art)",
           karten[0] == ["req-F2-1"]
           and antwort_an(log, "req-F2-1") == ("allow", "")
           and antwort_an(log, "req-F2-2") == ("allow", ""), (karten, log))
    pruefe("MO2 ... nach der naechsten Nachricht fragt dieselbe Art wieder",
           karten[1] == ["req-F2-3"], karten)
    C.beenden(chat)
    M, n = laden_mit("_chat_mo2", "omcad_a_chat.py",
                     '    chat["gewaehrt_zug"] = set()\n    if chat.get("schleife")',
                     '    if chat.get("schleife")')
    k_chat, _l, k_karten = cli_modus_lauf(
        M, U, "fragen", ["werkzeug:Bash", "werkzeug:Bash"], "F2K", erlauben)
    pruefe("MO2 KONTROLLE: ohne das Zuruecksetzen in senden() fragt die "
           "zweite Nachricht NICHT mehr", n == 1 and k_karten[1] == [],
           (n, k_karten))
    M.beenden(k_chat)

    # -- MO3 Für diese Sitzung nicht mehr fragen -------------------------------
    def sitzung(chat, f):
        C.freigabe_beantworten(chat, f["id"], True, sitzung=True)
    chat, log, karten = cli_modus_lauf(
        C, U, "fragen", ["werkzeug:Write", "werkzeug:Write werkzeug:Bash"],
        "F3", sitzung)
    pruefe("MO3 'Für diese Sitzung': Write fragt auch nach der naechsten "
           "Nachricht nicht mehr, eine andere Art (Bash) schon",
           karten[0] == ["req-F3-1"] and karten[1] == ["req-F3-3"]
           and antwort_an(log, "req-F3-2") == ("allow", ""), karten)
    C.beenden(chat)
    chat, log, karten = cli_modus_lauf(
        C, U, "fragen", ["werkzeug:Write"], "F3N", sitzung)
    pruefe("MO3 ... und ein NEUER Chat fragt wieder",
           karten[0] == ["req-F3N-1"], karten)
    C.beenden(chat)

    # -- MO4 Cadwork frei, MO5 Alles automatisch ------------------------------
    chat, log, karten = cli_modus_lauf(
        C, U, "cadwork_frei", ["werkzeug:%s werkzeug:Bash" % CAD], "CF")
    pruefe("MO4 Cadwork frei: execute ohne Karte, Bash als Karte",
           karten == [["req-CF-2"]]
           and antwort_an(log, "req-CF-1") == ("allow", "")
           and antwort_an(log, "req-CF-2") is None, (karten, stdin_von(log)))
    C.beenden(chat)
    chat, log, karten = cli_modus_lauf(
        C, U, "alles_auto", ["werkzeug:Write werkzeug:Bash werkzeug:%s" % CAD],
        "AA")
    pruefe("MO5 Alles automatisch: nichts fragt",
           karten == [[]] and all(antwort_an(log, "req-AA-%d" % i)
                                  == ("allow", "") for i in (1, 2, 3)),
           karten)
    C.beenden(chat)

    # -- MO6 Wechsel mitten im Chat gilt ab dem naechsten Aufruf --------------
    chat, log, karten = cli_modus_lauf(C, U, "fragen", [], "WE")
    C.senden(chat, "werkzeug:%s" % CAD)
    warte(lambda: C.offene_freigaben(chat))
    offen = [f["id"] for f in C.offene_freigaben(chat)]
    chat["modus"] = "cadwork_frei"            # wie `_modus_waehlen` im Dock
    C.senden(chat, "werkzeug:%s" % CAD)
    warte(lambda: antwort_an(log, "req-WE-2"))
    pruefe("MO6 Wechsel mitten im Chat: die offene Karte bleibt, der naechste "
           "Aufruf entscheidet nach dem neuen Modus",
           offen == ["req-WE-1"] and antwort_an(log, "req-WE-1") is None
           and antwort_an(log, "req-WE-2") == ("allow", "")
           and [f["id"] for f in C.offene_freigaben(chat)] == ["req-WE-1"],
           (offen, stdin_von(log)))
    C.beenden(chat)

    # -- MO7 Geschwister: zwei offene Karten derselben Art ---------------------
    chat, log, _k = cli_modus_lauf(
        C, U, "fragen", ["werkzeug:Write werkzeug:Write"], "GE")
    warte(lambda: len(C.offene_freigaben(chat)) == 2)
    erste = C.offene_freigaben(chat)[0]["id"]
    C.freigabe_beantworten(chat, erste, True)
    warte(lambda: antwort_an(log, "req-GE-2"))
    pruefe("MO7 Erlauben gibt eine zweite offene Karte derselben Art mit frei",
           antwort_an(log, "req-GE-1") == ("allow", "")
           and antwort_an(log, "req-GE-2") == ("allow", "")
           and not C.offene_freigaben(chat), stdin_von(log))
    C.beenden(chat)
    M, n = laden_mit("_chat_mo7", "omcad_a_chat.py",
                     "        _geschwister_erlauben(chat, karte.get(\"werkzeug\"), kennung)",
                     "        pass")
    k_chat, k_log, _k = cli_modus_lauf(
        M, U, "fragen", ["werkzeug:Write werkzeug:Write"], "GEK")
    warte(lambda: len(M.offene_freigaben(k_chat)) == 2)
    M.freigabe_beantworten(k_chat, M.offene_freigaben(k_chat)[0]["id"], True)
    time.sleep(0.4)
    pruefe("MO7 KONTROLLE: ohne _geschwister_erlauben bleibt die zweite offen",
           n == 1 and antwort_an(k_log, "req-GEK-2") is None
           and len(M.offene_freigaben(k_chat)) == 1, (n, stdin_von(k_log)))
    M.beenden(k_chat)


def schleife_modus_lauf(P, C, U, TA, modus, drehbuch, name, nachrichten,
                        antworten=None, entscheiden=None):
    """Die Schleife gegen den OpenAI-kompatiblen Attrappen-Dienst und die
    protokollierende MCP-Attrappe. -> (chat, gerufen, karten, posts)."""
    D = TA.Dienst()
    D.drehbuch[:] = list(drehbuch)
    srv, mlog = U.mcp_server(name)
    chat = {"modus": modus}
    U.chats.append(chat)
    P.starten(chat, "eigen", "m", entscheiden or C.chat_entscheiden,
              basis=D.basis, server=srv, port=1)
    warte(lambda: chat.get("werkzeuge_da"))
    karten = []
    try:
        for text in nachrichten:
            n = arten(chat).count("schluss")
            C.senden(chat, text)
            gezeigt = []
            ende = time.monotonic() + 10
            while time.monotonic() < ende and arten(chat).count("schluss") <= n:
                for f in list(C.offene_freigaben(chat)):
                    if f["id"] not in gezeigt:
                        gezeigt.append(f["id"])
                        if antworten is not None:
                            antworten(chat, f)
                time.sleep(0.02)
            karten.append(gezeigt)
        return chat, mcp_gerufen(mlog), karten, D.posts()
    finally:
        C.beenden(chat)
        dienst_schliessen(D)


def zusatz_ordner(C, U):
    """ZO1 (K3): "+ Ordner" — jeder weitere Ordner, den es gibt, kommt als
    `--add-dir <Ordner>` an die Befehlszeile hinter claude.cmd; einer, den
    es nicht gibt, nicht."""
    extra = tempfile.mkdtemp(prefix="omcad_zusatz_", dir=U.t)
    weg = os.path.join(U.t, "gibt_es_nicht")
    log = os.path.join(U.t, "cli_zusatz_%d.log" % next(U.zaehler))
    os.environ.update(OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME="ZO",
                      OMCAD_ATTRAPPE_MODUS="")
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    C.starten(chat, U.t, port=1, werkzeuge=False, modell=None, effort=None,
              zusatz=[extra, weg])
    warte(lambda: any("argv" in e for e in eintraege(log)))
    argv = next((e["argv"] for e in eintraege(log) if "argv" in e), [])
    paare = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--add-dir"]
    pruefe("ZO1 weitere Ordner kommen als --add-dir an (nur vorhandene)",
           paare == [extra], argv)
    C.beenden(chat)
    log2 = os.path.join(U.t, "cli_zusatz_%d.log" % next(U.zaehler))
    os.environ["OMCAD_ATTRAPPE_LOG"] = log2
    chat2 = {"modus": "fragen"}
    U.chats.append(chat2)
    C.starten(chat2, U.t, port=1, werkzeuge=False, modell=None, effort=None)
    warte(lambda: any("argv" in e for e in eintraege(log2)))
    argv2 = next((e["argv"] for e in eintraege(log2) if "argv" in e), [])
    pruefe("ZO1 KONTROLLE: ohne weitere Ordner kein --add-dir",
           "--add-dir" not in argv2 and argv2, argv2)
    C.beenden(chat2)


def modi_schleife(P, C, U, TA):
    """MS1-MS3: die Schleife (OpenAI-kompatibel)."""
    buch = [(200, TA.aufruf_antwort("execute_cadwork_command", {"code": "x"})),
            (200, TA.aufruf_antwort("get_document_info", {}, "call_2")),
            (200, TA.text_antwort("fertig"))]
    chat, gerufen, karten, posts = schleife_modus_lauf(
        P, C, U, TA, "nur_lesen", buch, "MS1", ["zeichne"])
    werkzeug_texte = [m.get("content") for p in posts
                      for m in (p[2] or {}).get("messages") or ()
                      if m.get("role") == "tool"]
    pruefe("MS1 Schleife, Nur lesen: execute ohne Karte abgelehnt, NICHT beim "
           "Server; get_document_info laeuft",
           karten == [[]] and gerufen == ["get_document_info"]
           and "verweigert" in arten(chat)
           and werkzeug_texte[:1] == [C.ablehnung_text(
               "nur_lesen", CAD)],
           (karten, gerufen, arten(chat), werkzeug_texte[:1]))
    pruefe("SP2 Schleife, Nur lesen: das Modell bekommt denselben Grund wie "
           "beim CLI (Hinweis, Wechsel, sagen was es wollte)",
           bool(werkzeug_texte)
           and sperr_grund_ok(werkzeug_texte[0], "execute_cadwork_command"),
           werkzeug_texte[:1])
    def ja(chat, f):
        C.freigabe_beantworten(chat, f["id"], True)
    buch2 = [(200, TA.aufruf_antwort("execute_cadwork_command", {"code": "a"})),
             (200, TA.aufruf_antwort("execute_cadwork_command", {"code": "b"},
                                     "call_2")),
             (200, TA.text_antwort("eins")),
             (200, TA.aufruf_antwort("execute_cadwork_command", {"code": "c"},
                                     "call_3")),
             (200, TA.text_antwort("zwei"))]
    chat, gerufen, karten, _p = schleife_modus_lauf(
        P, C, U, TA, "fragen", buch2, "MS2", ["eins", "zwei"], ja)
    pruefe("MS2 Schleife, Fragen: EINE Karte fuer zwei execute im selben Zug, "
           "nach der naechsten Nachricht wieder eine",
           [len(k) for k in karten] == [1, 1]
           and gerufen == ["execute_cadwork_command"] * 3, (karten, gerufen))
    chat, gerufen, karten, _p = schleife_modus_lauf(
        P, C, U, TA, "cadwork_frei", buch[:1] + buch[2:], "MS3", ["zeichne"])
    pruefe("MS3 Schleife, Cadwork frei: execute ohne Karte beim Server",
           karten == [[]] and gerufen == ["execute_cadwork_command"],
           (karten, gerufen))
    # KONTROLLE: eine Entscheidung, die (wie vor Schnittstelle 2) nur
    # "fragen" kennt, liesse Nur lesen eine Karte zeigen statt abzulehnen.
    chat, gerufen, karten, _p = schleife_modus_lauf(
        P, C, U, TA, "nur_lesen", buch, "MS1K", ["zeichne"],
        entscheiden=lambda c, w, a=None: (
            "ja" if C.chat_entscheiden(c, w, a) == "ja" else "fragen"))
    pruefe("MS1 KONTROLLE: ohne 'nein' in der Entscheidung kommt eine Karte",
           [len(k) for k in karten] == [1] and "verweigert" not in arten(chat),
           (karten, arten(chat)))


def modi_codex(P, C, U, TA):
    """MC1-MC3: Codex (App-Server-Attrappe aus test_anbieter)."""
    def lauf(modus, name, antworten=None):
        chat = {"modus": modus}
        gespraech, log = codex_starten(P, C, U, TA, chat, name)
        karten = []
        for text in ("zeichne", "zeichne"):
            n = arten(chat).count("schluss")
            C.senden(chat, text)
            gezeigt = []
            ende = time.monotonic() + 10
            while time.monotonic() < ende and arten(chat).count("schluss") <= n:
                for f in list(C.offene_freigaben(chat)):
                    if f["id"] not in gezeigt:
                        gezeigt.append(f["id"])
                        if antworten is not None:
                            antworten(chat, f)
                time.sleep(0.02)
            karten.append(gezeigt)
        C.beenden(chat)
        eintr = eintraege(log)
        return (chat, karten,
                [e["antwort"].get("result") for e in eintr if "antwort" in e],
                [e["gerufen"] for e in eintr if "gerufen" in e])
    chat, karten, antworten, gerufen = lauf("nur_lesen", "MC1")
    pruefe("MC1 Codex, Nur lesen: decline ohne Karte, nichts gerufen",
           karten == [[], []] and gerufen == []
           and antworten == [{"action": "decline"}] * 2
           and arten(chat).count("verweigert") == 2, (karten, antworten))

    def ja(chat, f):
        C.freigabe_beantworten(chat, f["id"], True)
    chat, karten, antworten, gerufen = lauf("fragen", "MC2", ja)
    pruefe("MC2 Codex, Fragen: je Nachricht eine Karte, accept OHNE persist",
           [len(k) for k in karten] == [1, 1]
           and antworten == [{"action": "accept", "content": {}}] * 2
           and len(gerufen) == 2, (karten, antworten))
    chat, karten, antworten, gerufen = lauf("cadwork_frei", "MC3")
    pruefe("MC3 Codex, Cadwork frei: accept ohne Karte",
           karten == [[], []]
           and antworten == [{"action": "accept", "content": {}}] * 2,
           (karten, antworten))


# =============================================================================
# Anhaenge (K4, 2026-09-27): was in allen drei Wegen ankommt
# =============================================================================

#: Ein 1x1-PNG (base64) — der Inhalt zaehlt nicht, nur dass er ankommt.
BILD_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4"
            "z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")


def anhaenge_probe():
    return [{"art": "bild", "name": "plan.png", "mime": "image/png",
             "b64": BILD_B64},
            {"art": "text", "name": "notiz.txt",
             "als_text": "Anhang «notiz.txt» (C:/x/notiz.txt):\nINHALT-42"}]


def anhaenge_cli(C, U):
    """AH1: Claude Code bekommt EINE Nutzernachricht mit Bloecken: Text
    (samt Textdatei) und Bild (base64) — die Form, die am echten CLI
    2.1.263 gemessen ist. Im Verlauf stehen nur die Namen."""
    chat = {"modus": "fragen"}
    log = U.cli_start(C, chat, "AH")
    warte(lambda: chat.get("sitzung") == "sitzung-AH")
    C.senden(chat, "schau", anhaenge_probe())
    warte(lambda: any(m.get("type") == "user" for m in stdin_von(log)))
    nachricht = next((m for m in stdin_von(log) if m.get("type") == "user"),
                     {})
    inhalt = (nachricht.get("message") or {}).get("content")
    ok = (isinstance(inhalt, list) and len(inhalt) == 2
          and inhalt[0].get("type") == "text"
          and inhalt[0].get("text", "").startswith("schau")
          and "INHALT-42" in inhalt[0].get("text", "")
          and inhalt[1] == {"type": "image", "source": {
              "type": "base64", "media_type": "image/png",
              "data": BILD_B64}})
    ich = next((e for e in chat.get("ereignisse") or ()
                if e.get("art") == "ich"), {})
    pruefe("AH1 Claude Code: Text-Block (mit der Textdatei) und Bild-Block "
           "(base64) in EINER Nachricht", ok, inhalt)
    pruefe("AH1 im Verlauf nur Text und Namen, kein Inhalt",
           ich.get("text") == "schau"
           and ich.get("anhaenge") == ["plan.png", "notiz.txt"]
           and "INHALT-42" not in json.dumps(ich), ich)
    C.senden(chat, "ohne")
    warte(lambda: sum(m.get("type") == "user" for m in stdin_von(log)) >= 2)
    zweite = [m for m in stdin_von(log) if m.get("type") == "user"][-1:]
    pruefe("AH1 KONTROLLE: ohne Anhaenge bleibt der Inhalt reiner Text",
           zweite and zweite[0]["message"]["content"] == "ohne", zweite)
    C.beenden(chat)


def anhaenge_schleife(P, C, U, TA):
    """AH2: die Schleife schickt Bilder als `image_url` (Data-URL) und die
    Textdatei im Text; gemessen an dem, was beim Dienst ankommt."""
    D = TA.Dienst()
    D.drehbuch[:] = [(200, TA.text_antwort("gesehen"))]
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    P.starten(chat, "eigen", "m", C.chat_entscheiden, basis=D.basis,
              server=None, port=1)
    try:
        C.senden(chat, "schau", anhaenge_probe())
        warte(lambda: "schluss" in arten(chat))
        nutzer = [m for p in D.posts() for m in (p[2] or {}).get("messages")
                  or () if m.get("role") == "user"]
        inhalt = nutzer[-1].get("content") if nutzer else None
        pruefe("AH2 Schleife: Text (mit der Textdatei) und image_url mit "
               "Data-URL", isinstance(inhalt, list) and len(inhalt) == 2
               and "INHALT-42" in inhalt[0].get("text", "")
               and inhalt[1] == {"type": "image_url", "image_url": {
                   "url": "data:image/png;base64," + BILD_B64}}, inhalt)
        ich = next((e for e in chat.get("ereignisse") or ()
                    if e.get("art") == "ich"), {})
        pruefe("AH2 im Verlauf der Schleife die Namen der Anhaenge",
               ich.get("anhaenge") == ["plan.png", "notiz.txt"], ich)
    finally:
        C.beenden(chat)
        dienst_schliessen(D)


def anhaenge_codex(P, C, U, TA):
    """AH3: Codex bekommt das Bild als `{"type": "image", "url": …}` in
    turn/start (Feldnamen aus dem Schema von codex-cli 0.156.1)."""
    chat = {"modus": "alles_auto"}
    _g, log = codex_starten(P, C, U, TA, chat, "AH3")
    C.senden(chat, "zeichne", anhaenge_probe())
    warte(lambda: "schluss" in arten(chat))
    start = next((e["turn_start"] for e in eintraege(log)
                  if "turn_start" in e), {})
    eingabe = start.get("input") or []
    pruefe("AH3 Codex: turn/start mit Text (samt Textdatei) und Bild",
           len(eingabe) == 2 and eingabe[0].get("type") == "text"
           and "INHALT-42" in eingabe[0].get("text", "")
           and eingabe[1] == {"type": "image",
                              "url": "data:image/png;base64," + BILD_B64},
           eingabe)
    C.beenden(chat)


# =============================================================================
# Gegenpruefung 2026-09-28: Politik gegen Tricks, Befehlszeile, Codex ohne
# Werkzeugnamen, Bilder, die das Modell nicht nimmt
# =============================================================================

#: Namen, die in "Nur lesen" NIE durchgehen duerfen: Aeusseres, Aenderndes,
#: Schreibweisen, fremde Server mit aehnlichem Namen, kaputte Typen.
NIE_IN_NUR_LESEN = [
    "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch",
    "WebSearch", "Agent", "Task", "KillShell", "BashOutput", "SlashCommand",
    "read", "READ", " Read", "Read ", "Read\n", "Glob2",
    "mcp__open-mcp-cad__execute_cadwork_command",
    "mcp__open-mcp-cad__execute_cadwork_batch",
    "mcp__open-mcp-cad__record_experience",
    "mcp__open-mcp-cad__create_from_init",
    "mcp__open-mcp-cad__GET_DOCUMENT_INFO",
    "mcp__open-mcp-cad__get_document_info__x",
    "mcp__open-mcp-cad__get_document_info ",
    "mcp__open-mcp-cadx__get_document_info",
    "mcp__Open-MCP-CAD__get_document_info",
    "mcp__andere__get_document_info", "mcp__cadwork__get_document_info",
    "get_document_info", "mcp__open-mcp-cad__", "mcp__open-mcp-cad",
    "mcp__open-mcp-cad__gibt_es_nicht", "", None, 42, ["Read"], {"a": 1},
    ("Read",),
] + [
    # Erweiterungen (seit 2026-10-01): nur `lesen_<name>` nach dem Muster
    # gilt als lesend - jede Schreibweise daneben ist aendernd bzw. fremd.
    "mcp__open-mcp-cad__probe_bauen", "mcp__open-mcp-cad__lesen_",
    "mcp__open-mcp-cad__lesen__x", "mcp__open-mcp-cad__LESEN_x",
    "mcp__open-mcp-cad__Lesen_x", "mcp__open-mcp-cad__lesen_x ",
    "mcp__open-mcp-cad__lesen_x\n", "mcp__open-mcp-cad__lesen-x",
    "mcp__open-mcp-cad__lesen_x__execute_cadwork_command",
    "mcp__open-mcp-cad__lesen_\u00e4", "mcp__open-mcp-cad__lesen_X",
    "mcp__open-mcp-cadx__lesen_x", "mcp__andere__lesen_x", "lesen_x",
]


def _urteile(C, modus, namen, anfrage=None, gewaehrt=()):
    """-> {repr(name): Urteil oder 'WIRFT …'}."""
    aus = {}
    for n in namen:
        try:
            aus[repr(n)] = C.entscheiden(modus, n, anfrage, gewaehrt)
        except Exception as exc:                        # noqa: BLE001
            aus[repr(n)] = "WIRFT %s" % type(exc).__name__
    return aus


def politik_tricks(C):
    """PT1-PT3: die Politik gegen Namen, die sie austricksen koennten."""
    nl = _urteile(C, "nur_lesen", NIE_IN_NUR_LESEN)
    pruefe("PT1 Nur lesen: kein Aeusseres, nichts Aenderndes, keine "
           "Schreibweise, kein fremder Server, kein kaputter Typ geht "
           "durch — alles 'nein', nichts wirft",
           set(nl.values()) == {"nein"},
           {k: v for k, v in nl.items() if v != "nein"})
    ja = _urteile(C, "nur_lesen", ["Read", LESEN_CAD, "Grep",
                                   "mcp__open-mcp-cad-b__get_document_info",
                                   ERW_LESEN])
    pruefe("PT1 KONTROLLE: Lesendes (auch des eigenen Servers in Steckplatz "
           "b) geht in Nur lesen durch", set(ja.values()) == {"ja"}, ja)
    raus = _urteile(C, "nur_lesen", ["Read", LESEN_CAD],
                    {"blocked_path": "C:/x"})
    pruefe("PT1 ... ausser es greift aus dem Ordner heraus (blocked_path)",
           set(raus.values()) == {"nein"}, raus)
    aussen = [n for n in NIE_IN_NUR_LESEN
              if isinstance(n, str) and C.werkzeug_art(n) == "aussen"]
    falsch = {m: _urteile(C, m, aussen, None, set(aussen))
              for m in ("fragen", "cadwork_frei")}
    frei = {m: {k: v for k, v in u.items() if v == "ja"}
            for m, u in falsch.items()}
    ohne = _urteile(C, "cadwork_frei", aussen)
    pruefe("PT2 Cadwork frei laesst nichts Aeusseres ohne Karte durch; mit "
           "einer Gewaehrung genau wie Fragen (Entscheid 2026-09-28)",
           set(ohne.values()) == {"fragen"}
           and frei["cadwork_frei"] == frei["fragen"]
           and set(frei["fragen"]) == {repr(n) for n in aussen}, (ohne, frei))
    nicht = _urteile(C, "fragen", aussen)
    pruefe("PT2 KONTROLLE: Fragen ohne Gewaehrung fragt bei allem Aeusseren",
           set(nicht.values()) == {"fragen"}, nicht)
    unbekannt = _urteile(C, "turbo", ["Bash", CAD, "Write"])
    pruefe("PT3 ein unbekannter Modus fragt (nie mehr Freiheit)",
           set(unbekannt.values()) == {"fragen"}, unbekannt)
    M, n = laden_mit("_chat_pt1", "omcad_a_chat.py",
                     '    if not isinstance(werkzeug, str):\n'
                     '        return "aussen"\n', "")
    k = _urteile(M, "nur_lesen", NIE_IN_NUR_LESEN)
    pruefe("PT1 KONTROLLE: ohne die Typpruefung wirft die Politik bei einer "
           "Liste (der Leser stiege aus)", n == 1
           and any(str(v).startswith("WIRFT") for v in k.values()), (n, k))


#: Ein als nur lesend erklaertes Werkzeug einer Erweiterung (seit 2026-10-01)
#: und ein aenderndes.
ERW_LESEN = "mcp__open-mcp-cad__lesen_probe_pruefen"
ERW_AENDERN = "mcp__open-mcp-cad__probe_bauen"
MODI_ALLE = ("nur_lesen", "fragen", "cadwork_frei", "alles_auto")


def _erweiterungen_modul():
    """open_mcp_cad/erweiterungen.py aus DIESEM Repo (nicht installiert)."""
    import importlib
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    E = importlib.import_module("open_mcp_cad.erweiterungen")
    assert os.path.dirname(os.path.dirname(os.path.abspath(E.__file__))) \
        == os.path.abspath(REPO), E.__file__
    return E


def erweiterungen_politik(C, U):
    """EP1-EP7: Werkzeuge aus Erweiterungen (OPEN_MCP_CAD_ERWEITERUNGEN).

    Vorgabe aendernd; lesend nur, was die Erweiterung so erklaert hat - der
    Server erzwingt dafuer den Namen (open_mcp_cad/erweiterungen.py), das
    Dock liest ihn mit DENSELBEN zwei Werten."""
    E = _erweiterungen_modul()
    u = {m: C.entscheiden(m, ERW_LESEN) for m in MODI_ALLE}
    pruefe("EP1 ein erklaert lesendes Werkzeug einer Erweiterung ist 'lesen' "
           "und laeuft in jedem Modus ohne Karte (auch in Steckplatz b)",
           C.werkzeug_art(ERW_LESEN) == "lesen"
           and C.werkzeug_art("mcp__open-mcp-cad-b__lesen_x") == "lesen"
           and set(u.values()) == {"ja"}, u)
    u = {m: C.entscheiden(m, ERW_AENDERN) for m in MODI_ALLE}
    pruefe("EP2 jedes andere Werkzeug einer Erweiterung gilt als aendernd: "
           "Nur lesen nein, Fragen fragt, Cadwork frei ja",
           C.werkzeug_art(ERW_AENDERN) == "cadwork"
           and u == {"nur_lesen": "nein", "fragen": "fragen",
                     "cadwork_frei": "ja", "alles_auto": "ja"}, u)
    tricks = [n for n in NIE_IN_NUR_LESEN if isinstance(n, str)
              and "lesen" in n.lower()]
    falsch = {repr(n): C.werkzeug_art(n) for n in tricks
              if C.werkzeug_art(n) == "lesen"}
    pruefe("EP3 keine Schreibweise daneben (leer, Doppel-Unterstrich, gross, "
           "Leerzeichen, Zeilenende, Bindestrich, Umlaut, angehaengter "
           "Kernname, fremder Server) gilt als lesend",
           len(tricks) >= 12 and not falsch, (len(tricks), falsch))
    kern = server_werkzeuge()
    lesend = {n for n in kern
              if C.werkzeug_art("mcp__open-mcp-cad__" + n) == "lesen"}
    pruefe("EP4 an den Kernwerkzeugen (aus server.py) aendert die Regel "
           "nichts: lesend sind genau die aus CADWORK_LESEND, keines traegt "
           "den Praefix", lesend == set(C.CADWORK_LESEND) & set(kern)
           and not any(n.startswith(C.ERWEITERUNG_LESEND_PRAEFIX)
                       for n in kern) and len(kern) >= 20,
           sorted(lesend ^ (set(C.CADWORK_LESEND) & set(kern))))
    with io.open(E.__file__, encoding="utf-8") as fh:
        q_erw = fh.read()
    with io.open(os.path.join(quelle(), "omcad_a_chat.py"),
                 encoding="utf-8") as fh:
        q_chat = fh.read()
    paare = (("LESEND_PRAEFIX", "ERWEITERUNG_LESEND_PRAEFIX"),
             ("NAME_MUSTER", "ERWEITERUNG_NAME"))
    werte = [(quell_konstante(q_erw, a), quell_konstante(q_chat, b))
             for a, b in paare]
    pruefe("EP5 Praefix und Namensmuster stehen im Server "
           "(erweiterungen.py) und im Dock (omcad_a_chat.py) gleich - aus "
           "dem Quelltext", all(a is not None and a == b for a, b in werte),
           werte)
    k = quell_konstante(quelle_mit(q_chat, "lies_",
                                   "ERWEITERUNG_LESEND_PRAEFIX"),
                        "ERWEITERUNG_LESEND_PRAEFIX")
    pruefe("EP5 KONTROLLE: ein geaenderter Praefix im Dock faellt auf",
           k == "lies_" and k != werte[0][0], k)
    namen = ["lesen_probe_pruefen", "lesen_x", "lesen_a1_b2", "lesen_",
             "lesen__x", "Lesen_x", "lesen_x_", "lesen_x ", "lesen_1x",
             "probe_bauen", "lesen", "lesenx", "lesen_x__y", "lesen-x"]
    ungleich = {n: (E.name_ist_lesend(n), C.werkzeug_art(
        "mcp__open-mcp-cad__" + n)) for n in namen
        if E.name_ist_lesend(n) != (C.werkzeug_art(
            "mcp__open-mcp-cad__" + n) == "lesen")}
    pruefe("EP6 Server und Dock urteilen ueber dieselben Namen gleich "
           "(lesend genau dann, wenn der Server den Namen als lesend annimmt)",
           not ungleich and E.name_ist_lesend("lesen_probe_pruefen"),
           ungleich)
    # EP7: der Server-Befehl reicht die Variable weiter.
    py_ordner = os.path.join(U.t, "ep_py")
    os.makedirs(os.path.join(py_ordner, "Lib", "site-packages",
                             "open_mcp_cad-0.1.0.dist-info"), exist_ok=True)
    for exe in ("python.exe", "pythonw.exe"):
        open(os.path.join(py_ordner, exe), "w").close()
    alt = {k: os.environ.get(k) for k in ("OPEN_MCP_CAD_PYTHON",
                                          "OPEN_MCP_CAD_ERWEITERUNGEN")}
    try:
        os.environ["OPEN_MCP_CAD_PYTHON"] = os.path.join(py_ordner,
                                                         "python.exe")
        os.environ["OPEN_MCP_CAD_ERWEITERUNGEN"] = "C:/erw/a;paket.b"
        mit = C.server_befehl(53911)
        os.environ.pop("OPEN_MCP_CAD_ERWEITERUNGEN")
        ohne = C.server_befehl(53911)
    finally:
        for k2, v in alt.items():
            if v is None:
                os.environ.pop(k2, None)
            else:
                os.environ[k2] = v
    pruefe("EP7 server_befehl reicht OPEN_MCP_CAD_ERWEITERUNGEN ausdruecklich "
           "an den Server weiter", mit is not None
           and mit[1].get("OPEN_MCP_CAD_ERWEITERUNGEN") == "C:/erw/a;paket.b",
           mit)
    pruefe("EP7 KONTROLLE: ohne Variable steht sie nicht in der Umgebung",
           ohne is not None and "OPEN_MCP_CAD_ERWEITERUNGEN" not in ohne[1],
           ohne)
    M, n = laden_mit("_chat_ep_k1", "omcad_a_chat.py",
                     "            and _ERWEITERUNG_NAME.fullmatch(kurz) is not "
                     "None)", ")")
    k1 = [t for t in tricks if M.werkzeug_art(t) == "lesen"]
    pruefe("EP3 KONTROLLE: nur der Praefix ohne Muster liesse Schreibweisen "
           "als lesend durch (u. a. den angehaengten Kernnamen)",
           n == 1 and "mcp__open-mcp-cad__lesen_x__execute_cadwork_command"
           in k1, (n, k1))
    M, n = laden_mit("_chat_ep_k2", "omcad_a_chat.py",
                     "    if kurz in CADWORK_LESEND or _erweiterung_lesend("
                     "kurz):", "    if kurz in CADWORK_LESEND:")
    pruefe("EP1 KONTROLLE: ohne die Regel waere das lesende Werkzeug einer "
           "Erweiterung in Nur lesen gesperrt",
           n == 1 and M.entscheiden("nur_lesen", ERW_LESEN) == "nein", n)


def erweiterungen_drei_wege(P, C, U, TA):
    """EW1-EW3 (seit 2026-10-01, Erweiterungs-Haken): ein Werkzeug einer
    Erweiterung wird in ALLEN DREI Wegen so eingestuft, wie die Politik es
    sagt — in "Nur lesen" laeuft das erklaert lesende ohne Karte, das
    aendernde wird ohne Karte abgelehnt und erreicht den Server nicht."""
    kurz_l = ERW_LESEN.split("__")[-1]
    kurz_a = ERW_AENDERN.split("__")[-1]
    # -- EW1 Claude Code ----------------------------------------------------
    chat, log, karten = cli_modus_lauf(
        C, U, "nur_lesen", ["werkzeug:%s werkzeug:%s" % (ERW_LESEN,
                                                       ERW_AENDERN)], "EW1")
    antw = [antwort_an(log, "req-EW1-%d" % i) for i in (1, 2)]
    pruefe("EW1 Claude Code, Nur lesen: lesen_… einer Erweiterung erlaubt, "
           "das aendernde ohne Karte abgelehnt (deny mit Grund)",
           karten == [[]] and antw[0] == ("allow", "")
           and antw[1] and antw[1][0] == "deny" and kurz_a in antw[1][1],
           (karten, antw))
    C.beenden(chat)
    M, n = laden_mit("_chat_ew1", "omcad_a_chat.py",
                     "    if kurz in CADWORK_LESEND or _erweiterung_lesend("
                     "kurz):", "    if kurz in CADWORK_LESEND:")
    k_chat, k_log, k_karten = cli_modus_lauf(
        M, U, "nur_lesen", ["werkzeug:%s" % ERW_LESEN], "EW1K")
    k_antw = antwort_an(k_log, "req-EW1K-1")
    pruefe("EW1 KONTROLLE: ohne die Regel fuer Erweiterungen waere das "
           "lesende in Nur lesen abgelehnt",
           n == 1 and k_antw and k_antw[0] == "deny", (n, k_antw))
    M.beenden(k_chat)

    # -- EW2 die Schleife (OpenAI-kompatibel) --------------------------------
    buch = [(200, TA.aufruf_antwort(kurz_l, {})),
            (200, TA.aufruf_antwort(kurz_a, {}, "call_2")),
            (200, TA.text_antwort("fertig"))]
    chat, gerufen, karten, posts = schleife_modus_lauf(
        P, C, U, TA, "nur_lesen", buch, "EW2", ["schau"])
    pruefe("EW2 Schleife, Nur lesen: lesen_… beim Server gerufen, das "
           "aendernde ohne Karte abgelehnt und NICHT gerufen",
           karten == [[]] and gerufen == [kurz_l]
           and [e.get("werkzeug") for e in chat["ereignisse"]
                if e.get("art") == "verweigert"] == [ERW_AENDERN],
           (karten, gerufen, arten(chat)))

    # -- EW3 Codex ------------------------------------------------------------
    attrappe = os.path.join(U.t, "codex_attrappe_ew.py")
    alt = ('werkzeug[0] = "get_cadwork_api_help" if "hilfe" in text else '
           '"execute_cadwork_command"')
    quelle = TA.CODEX_ATTRAPPE
    with io.open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(quelle.replace(alt, (
            'werkzeug[0] = (%r if "erwlesen" in text else %r if "erwbauen" '
            'in text else "get_cadwork_api_help" if "hilfe" in text else '
            '"execute_cadwork_command")' % (kurz_l, kurz_a))))
    log = os.path.join(U.t, "codex_EW3_%d.log" % next(U.zaehler))
    chat = {"modus": "nur_lesen"}
    U.chats.append(chat)
    P.starten(chat, "codex", "", C.chat_entscheiden,
              server=([sys.executable, "-c", "pass"],
                      {"OPEN_MCP_CAD_PORT": "1"}),
              codex_befehl=[sys.executable, attrappe, log])
    warte(lambda: chat.get("werkzeuge_da"))
    U.gespraeche.append(chat.get("schleife"))
    karten = []
    for text in ("erwlesen", "erwbauen"):
        n = arten(chat).count("schluss")
        C.senden(chat, text)
        ende = time.monotonic() + 10
        gezeigt = []
        while time.monotonic() < ende and arten(chat).count("schluss") <= n:
            gezeigt += [f["id"] for f in C.offene_freigaben(chat)
                        if f["id"] not in gezeigt]
            time.sleep(0.02)
        karten.append(gezeigt)
    C.beenden(chat)
    eintr = eintraege(log)
    antworten = [e["antwort"].get("result") for e in eintr if "antwort" in e]
    gerufen = [e["gerufen"] for e in eintr if "gerufen" in e]
    pruefe("EW3 Codex, Nur lesen: lesen_… ohne Karte angenommen, das "
           "aendernde ohne Karte abgelehnt, nur das lesende gerufen",
           alt in quelle and karten == [[], []] and gerufen == [kurz_l]
           and antworten == [{"action": "accept", "content": {}},
                             {"action": "decline"}],
           (karten, antworten, gerufen))


#: Die Modi in der entschiedenen Ordnung (Orchestrator 2026-09-28):
#: jeder laesst mindestens so viel durch wie der vorige.
MODUS_KETTE = ("nur_lesen", "fragen", "cadwork_frei", "alles_auto")
RANG = {"nein": 0, "fragen": 1, "ja": 2}


def monotonie_pruefen(C):
    """-> (Verletzungen, streng lockerer je Stufe, Zahl der Faelle).

    Ueber alle Namen (Aeusseres, Aenderndes, Lesendes, Schreibweisen,
    fremde Server, kaputte Typen, jedes Werkzeug aus server.py), mit und
    ohne `blocked_path`, ohne Gewaehrung, mit Gewaehrung genau dieser Art
    und mit Gewaehrung aller Arten."""
    namen = list(NIE_IN_NUR_LESEN) + ["Read", "Grep", "Glob", LESEN_CAD,
                                      "mcp__open-mcp-cad-b__get_document_info"]
    namen += ["mcp__open-mcp-cad__" + n for n in server_werkzeuge()]
    alle = frozenset(n for n in namen if isinstance(n, (str, int, tuple)))
    verletzt, strenger, faelle = [], set(), 0
    for n in namen:
        einzel = frozenset([n]) if isinstance(n, (str, int, tuple)) else ()
        for anfrage in (None, {"blocked_path": "C:/x"}):
            for gewaehrt in ((), einzel, alle):
                u = []
                for modus in MODUS_KETTE:
                    try:
                        u.append(C.entscheiden(modus, n, anfrage, gewaehrt))
                    except Exception as exc:            # noqa: BLE001
                        u.append("WIRFT %s" % type(exc).__name__)
                faelle += 1
                for i in range(len(u) - 1):
                    a, b = RANG.get(u[i], -9), RANG.get(u[i + 1], -9)
                    if a < 0 or b < 0 or a > b:
                        verletzt.append((repr(n), bool(anfrage),
                                         len(gewaehrt), MODUS_KETTE[i],
                                         u[i], MODUS_KETTE[i + 1], u[i + 1]))
                    elif a < b:
                        strenger.add(i)
    return verletzt, strenger, faelle


def server_werkzeuge():
    """Die Werkzeugnamen aus open_mcp_cad/server.py (dekorierte
    Funktionen) — aus der Quelle, keine eigene Liste."""
    import ast
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "open_mcp_cad", "server.py")
    with io.open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    return [f.name for f in ast.walk(baum)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any("mcp.tool" in ast.unparse(d) for d in f.decorator_list)]


def monotonie(C):
    """MN1 (Entscheid 2026-09-28): Nur lesen ⊂ Fragen ⊂ Cadwork frei ⊂
    Alles automatisch — ueber alle Werkzeugarten und Zustaende."""
    verletzt, strenger, faelle = monotonie_pruefen(C)
    pruefe("MN1 die Modi stehen in der Quelle in dieser Reihenfolge",
           tuple(C.MODUS_WERTE) == MODUS_KETTE, C.MODUS_WERTE)
    pruefe("MN1 kein spaeterer Modus laesst weniger durch als ein frueherer "
           "(%d Faelle: Namen x blocked_path x Gewaehrungen)" % faelle,
           faelle > 200 and not verletzt, verletzt[:6])
    pruefe("MN1 jede Stufe ist irgendwo wirklich lockerer",
           strenger == {0, 1, 2}, strenger)
    for titel, alt, neu in (
            ("Cadwork frei ohne Gewaehrung je Art (der Stand bis K7)",
             'if modus in ("fragen", "cadwork_frei") and isinstance(werkzeug,'
             ' str)', 'if modus == "fragen" and isinstance(werkzeug, str)'),
            ("Nur lesen laesst Cadwork-Befehle durch",
             'return "ja" if art == "lesen" and not draussen else "nein"',
             'return "ja" if art in ("lesen", "cadwork") and not draussen '
             'else "nein"')):
        M, n = laden_mit("_chat_mn1", "omcad_a_chat.py", alt, neu)
        k, _s, _f = monotonie_pruefen(M)
        pruefe("MN1 KONTROLLE: %s -> Verletzung" % titel, n == 1 and k,
               (n, k[:2]))


class _TotesCli:
    """Ein CLI, das schon beendet ist (`poll()` != None)."""
    stdin = None

    def poll(self):
        return 1


def senden_tot(C):
    """TS1 (Gegenpruefung K7, behoben 2026-09-28): `senden` an ein totes CLI
    -> False; die Nachricht steht NICHT im Verlauf, kein Zug laeuft."""
    import threading as _th

    def lauf(M):
        vorher = {"art": "ich", "text": "erste", "zeit": 1.0}
        chat = {"ereignisse": [vorher], "proc": _TotesCli(),
                "schloss": _th.Lock(), "stand": 3}
        ok = M.senden(chat, "zweite")
        return (ok, [e.get("text") for e in chat["ereignisse"]],
                chat.get("laeuft_zug"), chat["ereignisse"][0] is vorher)
    ok, texte, laeuft, gleich = lauf(C)
    pruefe("TS1 totes CLI: senden -> False, im Verlauf nur die alte "
           "Nachricht, kein Zug", ok is False and texte == ["erste"]
           and laeuft is False and gleich, (ok, texte, laeuft))
    M, n = laden_mit("_chat_ts1", "omcad_a_chat.py",
                     "        if liste[i] is ich:", "        if False:")
    k = lauf(M)
    pruefe("TS1 KONTROLLE: ohne das Herausnehmen stuende die Nachricht im "
           "Verlauf, als waere sie angekommen", n == 1 and k[1] == [
               "erste", "zweite"], (n, k))


def befehlszeile(C, U):
    """BZ1-BZ2: ein weiterer Ordner oder ein Modellname mit einem Zeichen,
    das cmd.exe auslegt, geht NIE ueber claude.cmd (gemessen: `&` beendet
    dort den Befehl, der Rest laeuft als eigener)."""
    boese = os.path.join(U.t, "Mueller&echo.BZ")
    os.makedirs(boese, exist_ok=True)
    log = os.path.join(U.t, "cli_bz_%d.log" % next(U.zaehler))
    os.environ.update(OMCAD_ATTRAPPE_LOG=log, OMCAD_ATTRAPPE_NAME="BZ",
                      OMCAD_ATTRAPPE_MODUS="")
    chat = {"modus": "fragen"}
    U.chats.append(chat)
    k = fehler_bei(lambda: C.starten(chat, U.t, port=1, werkzeuge=False,
                                     modell=None, effort=None,
                                     zusatz=[boese]))
    time.sleep(0.3)
    pruefe("BZ1 ein weiterer Ordner mit '&' startet nichts, der Grund "
           "nennt den Ordner", "BefehlszeileUngeeignet" in k and "&" in k
           and not eintraege(log) and chat.get("proc") is None, k[:120])
    k2 = fehler_bei(lambda: C.starten(chat, U.t, port=1, werkzeuge=False,
                                      modell="sonnet&echo.BZ", effort=None))
    pruefe("BZ2 ein Modellname mit '&' ebenso",
           "BefehlszeileUngeeignet" in k2 and chat.get("proc") is None,
           k2[:120])
    M, n = laden_mit("_chat_bz1", "omcad_a_chat.py",
                     '            _befehlszeile_pruefen(ordner, '
                     '"Der weitere Ordner")\n', "")
    k_chat = {"modus": "fragen"}
    U.chats.append(k_chat)
    M.starten(k_chat, U.t, port=1, werkzeuge=False, modell=None, effort=None,
              zusatz=[boese])
    warte(lambda: any("argv" in e for e in eintraege(log)))
    argv = next((e["argv"] for e in eintraege(log) if "argv" in e), [])
    paare = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--add-dir"]
    pruefe("BZ1 KONTROLLE: ohne die Pruefung kommt der Ordner hinter "
           "claude.cmd VERSTUEMMELT an (cmd.exe schnitt am '&')",
           n == 1 and paare and paare[0] != boese
           and "&" not in paare[0], (n, paare))
    M.beenden(k_chat)


# --- CX Claude Code als claude.exe (eigener Installer, 2026-09-29) -----------
# Anthropics heute empfohlener Installer legt `claude.exe` nach
# %USERPROFILE%\.local\bin; npm legt `claude.cmd` nach %APPDATA%\npm. Die
# Attrappe `claude.exe` ist ein ECHTES Programm: der Starter, mit dem pip
# Konsolenbefehle baut (distlib t64.exe), dahinter ein Zip, das dieselbe
# CLI-Attrappe laufen laesst. So startet es wie das echte ohne cmd.exe.

def exe_attrappe(ziel, skript):
    """Schreibt ein claude.exe, das `skript` mit diesem Python ausfuehrt.
    -> Pfad, oder None ohne Starter (dann ist CX rot, nicht still gruen)."""
    import zipfile
    try:
        import pip
    except ImportError:
        return None
    starter = os.path.join(os.path.dirname(pip.__file__), "_vendor",
                           "distlib", "t64.exe")
    if not os.path.isfile(starter):
        return None
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("__main__.py", "import runpy\nrunpy.run_path(%r, "
                                  "run_name='__main__')\n" % skript)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(starter, "rb") as fh, open(ziel, "wb") as aus:
        aus.write(fh.read() + b'#!"' + sys.executable.encode("mbcs")
                  + b'"\n' + puffer.getvalue())
    return ziel


def cli_welt(U, name, exe_heim=False, npm=False, path_exe=False,
             path_cmd=False):
    """Heim, APPDATA und PATH in Temp mit den gewuenschten Attrappen.
    -> dict (Pfade, env)."""
    t = os.path.join(U.t, "welt_" + name)
    w = {"heim": os.path.join(t, "Jürg Müller"), "appdata":
         os.path.join(t, "appdata"), "pfad": os.path.join(t, "pfad")}
    for o in w.values():
        os.makedirs(o, exist_ok=True)
    w["exe"] = os.path.join(w["heim"], ".local", "bin", "claude.exe")
    w["cmd"] = os.path.join(w["appdata"], "npm", "claude.cmd")
    w["path_exe"] = os.path.join(w["pfad"], "claude.exe")
    w["path_cmd"] = os.path.join(w["pfad"], "claude.cmd")
    if exe_heim:
        exe_attrappe(w["exe"], U.skript)
    if path_exe:
        exe_attrappe(w["path_exe"], U.skript)
    for an, ziel in ((npm, w["cmd"]), (path_cmd, w["path_cmd"])):
        if an:
            os.makedirs(os.path.dirname(ziel), exist_ok=True)
            shutil.copyfile(U.cmd, ziel)
    w["env"] = {"USERPROFILE": w["heim"], "APPDATA": w["appdata"],
                "PATH": w["pfad"]}
    return w


class _Umgebung:
    """os.environ fuer die Dauer eines with-Blocks setzen."""

    def __init__(self, werte):
        self.werte, self.alt = werte, {}

    def __enter__(self):
        for k, v in self.werte.items():
            self.alt[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *_a):
        for k, v in self.alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def cli_gefunden(C, w):
    with _Umgebung(w["env"]):
        try:
            return C.cli_pfad()
        except FileNotFoundError:
            return None


def cli_orte(C, U, KE):
    """CX1-CX4: welches Claude Code gefunden wird — und dass der Installer
    (`ki_eintragen.claude_programm`) in denselben Welten dasselbe findet."""
    welten = {
        "beide": (dict(exe_heim=True, npm=True), "exe"),
        "nur_exe": (dict(exe_heim=True), "exe"),
        "nur_cmd": (dict(npm=True), "cmd"),
        "keins": ({}, None),
        "path_beide": (dict(path_exe=True, path_cmd=True), "path_exe"),
        "path_cmd": (dict(path_cmd=True), "path_cmd"),
        "fest_vor_path": (dict(npm=True, path_exe=True), "cmd"),
    }
    gebaut, ist, soll, installer = {}, {}, {}, {}
    for name, (art, erwartet) in welten.items():
        w = gebaut[name] = cli_welt(U, name, **art)
        ist[name] = cli_gefunden(C, w)
        soll[name] = w[erwartet] if erwartet else None
        installer[name] = KE.claude_programm(dict(w["env"]))
    norm = (lambda p: os.path.normcase(p) if p else p)
    pruefe("CX1 gefunden wird claude.exe (eigener Installer) UND claude.cmd "
           "(npm); sind beide da, das claude.exe; feste Orte vor dem PATH; "
           "ohne beides nichts",
           exe_attrappe(os.path.join(U.t, "probe", "claude.exe"), U.skript)
           and all(norm(ist[n]) == norm(soll[n]) for n in welten),
           {n: (ist[n], soll[n]) for n in welten if norm(ist[n])
            != norm(soll[n])})
    pruefe("CX2 der Installer (ki_eintragen) findet in jeder Welt dasselbe "
           "Claude Code wie der Chat",
           all(norm(installer[n]) == norm(ist[n]) for n in welten),
           {n: (installer[n], ist[n]) for n in welten
            if norm(installer[n]) != norm(ist[n])})
    # KONTROLLEN: die alte Suche (nur claude.cmd) und eine, die npm vorzieht.
    echt = C.cli_kandidaten
    try:
        C.cli_kandidaten = lambda: [k for k in echt()
                                    if not k[1].endswith("claude.exe")]
        alt_nur_exe = cli_gefunden(C, gebaut["nur_exe"])
        C.cli_kandidaten = lambda: [echt()[1], echt()[0]] + echt()[2:]
        npm_zuerst = cli_gefunden(C, gebaut["beide"])
    finally:
        C.cli_kandidaten = echt
    pruefe("CX1-K KONTROLLE: nur nach claude.cmd gesucht, bliebe der eigene "
           "Installer unsichtbar; npm zuerst, naehme es bei beiden die .cmd",
           alt_nur_exe is None and norm(npm_zuerst)
           == norm(gebaut["beide"]["cmd"]), (alt_nur_exe, npm_zuerst))
    return gebaut


def cli_exe_start(C, U, welten):
    """CX3-CX4: ueber das ECHTE `starten` mit dem claude.exe — ohne cmd.exe
    dazwischen, Argumente woertlich, Antwort kommt an; dieselbe Pruefung
    der Befehlszeile gilt auch hier (Entscheid 2026-09-29)."""
    ergebnis = {}
    for name in ("nur_exe", "nur_cmd"):
        w = welten[name]
        with _Umgebung(w["env"]):
            chat = {"modus": "fragen"}
            try:
                log = U.cli_start(C, chat, "CX_" + name)
            except FileNotFoundError as exc:    # Mutante: nicht gefunden
                ergebnis[name] = {"eltern": "", "fehler": str(exc)[:80],
                                  "anweisung": False, "settings": False,
                                  "name": False, "antwort": False,
                                  "proc": "", "tot": False}
                continue
            warte(lambda: chat.get("sitzung") == "sitzung-CX_" + name)
            C.senden(chat, "hallo")
            warte(lambda: "schluss" in arten(chat))
            start = next((e for e in eintraege(log) if "argv" in e), {})
            argv = start.get("argv") or []
            werte = dict(zip(argv, argv[1:]))
            ergebnis[name] = {
                "eltern": (start.get("eltern") or "").lower(),
                "anweisung": werte.get("--append-system-prompt")
                == C.DOCK_ANWEISUNG,
                "settings": werte.get("--settings")
                == json.dumps(C._einstellungen()),
                "name": werte.get("-n") == C.SITZUNG_NAME,
                "antwort": texte(chat) == ["Antwort CX_%s: hallo" % name],
                "proc": os.path.normcase(chat["proc"].args[0])}
            C.beenden(chat)
            ergebnis[name]["tot"] = warte(
                lambda: any(e.get("ende") for e in eintraege(log)), 5)
    e, k = ergebnis["nur_exe"], ergebnis["nur_cmd"]
    pruefe("CX3 claude.exe startet direkt (Elternprozess claude.exe, nicht "
           "cmd.exe): Dock-Anweisung, --settings und -n kommen woertlich an, "
           "die Antwort steht im Verlauf, Beenden raeumt ab",
           e["eltern"] == "claude.exe" and e["anweisung"] and e["settings"]
           and e["name"] and e["antwort"] and e["tot"]
           and e["proc"] == os.path.normcase(welten["nur_exe"]["exe"]), e)
    pruefe("CX3-K KONTROLLE: ueber claude.cmd sitzt cmd.exe dazwischen "
           "(dieselbe Messung sieht den Unterschied)",
           k["eltern"] == "cmd.exe" and k["antwort"], k)
    boese = os.path.join(U.t, "Mueller&echo.CX")
    os.makedirs(boese, exist_ok=True)
    with _Umgebung(welten["nur_exe"]["env"]):
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        f = fehler_bei(lambda: C.starten(chat, U.t, port=1, werkzeuge=False,
                                         modell=None, effort=None,
                                         zusatz=[boese]))
    pruefe("CX4 auch mit claude.exe geht ein Ordner mit '&' nicht auf die "
           "Befehlszeile (dieselbe Regel fuer beide Wege)",
           "BefehlszeileUngeeignet" in f and chat.get("proc") is None, f[:100])


def codex_ohne_namen(P, C, U, TA):
    """MC4: nennt die Freigabe-Frage von Codex ihr Werkzeug nicht, ist der
    Name nur geraten (das zuletzt gestartete). In "Nur lesen" darf ein
    geratenes LESENDES nicht durchwinken."""
    frage = json.loads(json.dumps(CODEX_FRAGE))
    frage["params"]["message"] = "Allow this MCP tool call?"

    def lauf(P_):
        chat = {"modus": "nur_lesen"}
        g, log = codex_starten(P_, C, U, TA, chat, "MC4")
        g.letztes_werkzeug = "get_document_info"
        g._bearbeiten(json.loads(json.dumps(frage)))
        warte(lambda: any((e.get("antwort") or {}).get("id") == 55
                          for e in eintraege(log)), 5)
        antwort = next(((e["antwort"].get("result")) for e in eintraege(log)
                        if (e.get("antwort") or {}).get("id") == 55), None)
        C.beenden(chat)
        return antwort, arten(chat)
    antwort, a = lauf(P)
    pruefe("MC4 Codex, Nur lesen, Frage ohne Werkzeugnamen: abgelehnt, "
           "obwohl zuletzt ein lesendes lief", antwort == {"action": "decline"}
           and "auto" not in a, (antwort, a))
    M, n = laden_mit("_anbieter_mc4", "omcad_a_anbieter.py",
                     'voll if treffer else MCP_PRAEFIX + "?"', "voll")
    k_antwort, _a = lauf(M)
    pruefe("MC4 KONTROLLE: mit dem geratenen Namen winkt 'Nur lesen' durch",
           n == 1 and k_antwort == {"action": "accept", "content": {}},
           (n, k_antwort))


def bilder_scheitern(P, C, U, TA):
    """AH4: nimmt das Modell die Bilder nicht (Fehler des Dienstes), sind
    sie danach aus dem Gespraech — die naechste Nachricht geht ohne sie,
    und der Verlauf sagt es."""
    def lauf(P_):
        D = TA.Dienst()
        D.drehbuch[:] = [(400, {"error": {"message": "model does not "
                                          "support image input"}}),
                         (200, TA.text_antwort("ok"))]
        chat = {"modus": "fragen"}
        U.chats.append(chat)
        P_.starten(chat, "eigen", "m", C.chat_entscheiden, basis=D.basis,
                   server=None, port=1)
        try:
            C.senden(chat, "schau", anhaenge_probe())
            warte(lambda: arten(chat).count("schluss") >= 1)
            C.senden(chat, "und jetzt?")
            warte(lambda: arten(chat).count("schluss") >= 2)
            posts = D.posts()
            zweite = json.dumps(posts[1][2]) if len(posts) > 1 else ""
            return (len(posts), "image_url" in json.dumps(posts[0][2]),
                    "image_url" in zweite, "INHALT-42" in zweite,
                    [e.get("text") for e in chat.get("ereignisse") or ()
                     if e.get("art") == "text"])
        finally:
            C.beenden(chat)
            dienst_schliessen(D)
    n, erst, zweit, text_bleibt, texte = lauf(P)
    pruefe("AH4 Schleife: nach einem Fehler mit Bildern geht die naechste "
           "Nachricht OHNE die Bilder (der Text der ersten bleibt), der "
           "Verlauf sagt es", n == 2 and erst and not zweit and text_bleibt
           and any("Bilder" in (t or "") for t in texte), (n, erst, zweit,
                                                           texte))
    M, k = laden_mit("_anbieter_ah4", "omcad_a_anbieter.py",
                     '                nutzer["content"] = '
                     '_ohne_bilder(nutzer["content"])\n', "")
    _n, _e, k_zweit, _t, _x = lauf(M)
    pruefe("AH4 KONTROLLE: ohne das Herausnehmen geht das Bild mit jeder "
           "weiteren Nachricht mit", k == 1 and k_zweit, (k, k_zweit))


def erlauben_nach_wechsel(C, U):
    """MO8: steht eine Karte offen (oder entsteht sie im selben Moment) und
    wechselt der Nutzer auf "Nur lesen", wird ein spaetes "Erlauben" zur
    Ablehnung mit dem Grund des Modus — beim Prozess kommt deny an."""
    def lauf(M, name):
        chat, log, _k = cli_modus_lauf(M, U, "fragen", [], name)
        M.senden(chat, "werkzeug:%s" % CAD)
        warte(lambda: M.offene_freigaben(chat))
        kennung = M.offene_freigaben(chat)[0]["id"]
        chat["modus"] = "nur_lesen"
        M.freigabe_beantworten(chat, kennung, True, sitzung=True)
        warte(lambda: antwort_an(log, kennung))
        ergebnis = (antwort_an(log, kennung),
                    set(chat.get("gewaehrt_sitzung") or ()))
        M.beenden(chat)
        return ergebnis
    (verhalten, grund), gewaehrt = lauf(C, "NL8")
    pruefe("MO8 'Erlauben' nach dem Wechsel auf Nur lesen: deny mit dem "
           "Grund des Modus, keine Gewaehrung fuer die Sitzung",
           verhalten == "deny" and "Nur lesen" in grund and not gewaehrt,
           (verhalten, grund, gewaehrt))
    M, n = laden_mit("_chat_mo8", "omcad_a_chat.py",
                     '        erlauben, sitzung = False, False\n', "")
    (k_verhalten, _g), _k = lauf(M, "NL8K")
    pruefe("MO8 KONTROLLE: ohne die Pruefung beim Antworten liefe der "
           "Befehl trotz Nur lesen", n == 1 and k_verhalten == "allow",
           (n, k_verhalten))


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print("Chat-Kern: schnelle Wechsel — Gate  (Quelle: %s)\n" % quelle())
    C = laden("_chat_kern_gate", "omcad_a_chat.py")
    P = laden("_anbieter_kern_gate", "omcad_a_anbieter.py")
    TA = laden("_test_anbieter_hilfen", "test_anbieter.py", HIER)
    U = Umgebung()
    alt_env = {k: os.environ.get(k) for k in (
        "APPDATA", "CODEX_HOME", "LOCALAPPDATA", "OMCAD_ATTRAPPE_LOG",
        "OMCAD_ATTRAPPE_NAME", "OMCAD_ATTRAPPE_MODUS", "OMCAD_ATTRAPPE_HALTEN",
        "OPEN_MCP_CAD_BELEGT", "USERPROFILE")}
    os.environ["APPDATA"] = U.appdata
    # Ein Heim in Temp: sonst faende cli_pfad() auf einem Rechner mit dem
    # eigenen Installer von Anthropic das ECHTE ~\.local\bin\claude.exe
    # (K0 braeche dann ab, statt es zu starten).
    os.environ["USERPROFILE"] = os.path.join(U.t, "heim")
    os.makedirs(os.environ["USERPROFILE"], exist_ok=True)
    # Die Vermerke "belegt" (Nacharbeit D) im Temp dieses Laufs.
    os.environ["OPEN_MCP_CAD_BELEGT"] = os.path.join(U.t, "belegt")
    # Codex: eigene (leere) Konfiguration und eigener Arbeitsordner.
    os.environ["CODEX_HOME"] = os.path.join(U.t, "codex_heim")
    os.environ["LOCALAPPDATA"] = os.path.join(U.t, "localappdata")
    try:
        # --- 0. Nie das echte CLI ------------------------------------------
        gefunden = C.cli_pfad()
        pruefe("K0 cli_pfad() nimmt die Attrappe aus %APPDATA%\\npm",
               os.path.normcase(gefunden) == os.path.normcase(U.cmd), gefunden)
        if os.path.normcase(gefunden) != os.path.normcase(U.cmd):
            print("  ABBRUCH: sonst startete das ECHTE Claude Code.")
            return 1
        os.environ["APPDATA"] = os.path.join(U.t, "leer")
        os.environ["PATH"], alt_path = os.path.join(U.t, "leer"), os.environ["PATH"]
        try:
            k = fehler_bei(C.cli_pfad)
        finally:
            os.environ["APPDATA"], os.environ["PATH"] = U.appdata, alt_path
        pruefe("K0 KONTROLLE: ohne die Attrappe findet cli_pfad() nichts",
               "FileNotFoundError" in k, k[:80])

        # --- CX claude.exe (eigener Installer) und claude.cmd (npm) --------
        sys.path.insert(0, REPO)
        import open_mcp_cad.ki_eintragen as KE
        assert os.path.dirname(os.path.dirname(KE.__file__)) == REPO, \
            KE.__file__
        welten = cli_orte(C, U, KE)
        cli_exe_start(C, U, welten)

        d = HalteDienst(TA)
        pruefe("H0 der Halte-Dienst lauscht ausserhalb des Cadwork-Bereichs",
               bool(TA.CADWORK_PORTS) and d.port not in TA.CADWORK_PORTS, d.port)
        d.schliessen()

        # --- 1. Claude Code -----------------------------------------------
        grundweg(C, U)
        etappe_d(C, U)
        belegt(C, U)
        schnell_neu(C, U)

        vor, neuer_leser, finally_ok, detail = leser_am_prozess(C, U)
        pruefe("K7 Vorbedingung: alter Prozess tot, seine Leser leben noch",
               vor, "sonst misst K7/K8 kein Rennen")
        pruefe("K7 der neue Prozess bekommt Leser (stdout UND stderr), obwohl "
               "die alten noch leben — seine 300-kB-Flut laeuft durch",
               neuer_leser, detail[3])
        pruefe("K8 das finally des alten Lesers schaltet den neuen Chat nicht ab "
               "und seine spaeten Zeilen landen nicht im neuen Verlauf",
               finally_ok, detail[:3])
        protokoll = ohne_leser_blockiert(U)
        pruefe("K7 KONTROLLE: dieselbe Flut OHNE Leser bleibt stecken",
               {"flut": "stdout"} not in protokoll
               and any("start" in e for e in protokoll), protokoll[:3])

        C_mut = laden("_chat_kern_mutant", "omcad_a_chat.py")
        C_mut._aktuell = lambda chat, generation: True
        vor_m, _nl, finally_m, detail_m = leser_am_prozess(C_mut, U, flut=False)
        pruefe("K8 KONTROLLE: ohne Generationsriegel schaltet der alte Leser "
               "den neuen Chat ab",
               vor_m and not finally_m, detail_m[:3])

        spaete_frage(C, U)

        aus, zu, fehler, warnung, eof, an, k, antwortet = leser_stirbt(C, U)
        pruefe("K11 Vorbedingung: der Leser steigt an der Zeile [1] aus",
               aus, "sonst misst K11 nichts")
        pruefe("K11 ... der Fehler steht im Chat (Stoerung UND Verlauf), der "
               "Chat ist aus", "AttributeError" in fehler and warnung
               and an is False, (fehler[:90], warnung[:1], an))
        pruefe("K11 ... sein CLI wird beendet wie beim Beenden (stdin zu, "
               "Prozess fort)", zu and eof, (zu, eof))
        pruefe("K11 ... und der naechste Start gelingt, das neue CLI antwortet",
               k == "gestartet" and antwortet, (k[:90], antwortet))
        C_mut = laden("_chat_kern_mutant_leser", "omcad_a_chat.py")
        C_mut._prozess_abraeumen = lambda chat, proc, generation: None
        aus_m, zu_m, _f, _w, _e, _a, k_m, _x = leser_stirbt(C_mut, U)
        pruefe("K11 KONTROLLE: raeumt der Leser nicht ab (Stand bis "
               "2026-09-25), lebt das CLI weiter und der Start wirft "
               "VorigerChatLaeuft", aus_m and not zu_m
               and "VorigerChatLaeuft" in k_m, (aus_m, zu_m, k_m[:60]))

        # --- 2. Schleife, Codex und Wechsel ----------------------------------
        an, spaet, neu_ok, k = schleife_spaet(P, C, U, TA)
        pruefe("S1 Schleife -> Schleife: der alte Arbeitsthread (hing im HTTP) "
               "schaltet den neuen Chat nicht ab, schreibt nicht hinein",
               an and not spaet and neu_ok, (an, spaet, neu_ok, k[:60]))
        an, spaet, neu_ok, k = schleife_spaet(P, C, U, TA, neu_ist_cli=True)
        pruefe("S1 Schleife -> Claude Code: ebenso, und das CLI antwortet",
               an and not spaet and neu_ok, (an, spaet, neu_ok, k[:60]))
        P_mut = laden("_anbieter_kern_mutant", "omcad_a_anbieter.py")
        gespraech = getattr(P_mut, "_Gespraech", None)
        if gespraech is not None:
            gespraech._aktuell = lambda self: True
        an_m, _s, _n, _k = schleife_spaet(P_mut, C, U, TA)
        pruefe("S1 KONTROLLE: ohne Generationsriegel schaltet der alte Thread "
               "den neuen Chat ab", not an_m, an_m)

        schleife_mcp_lebt(P, C, U, TA)

        an, zug, offen, schluss, fertig, k, neu = codex_spaet(P, C, U, TA)
        pruefe("S3 Codex: der Start nach totem Prozess gelingt",
               k == "gestartet" and neu, k[:80])
        pruefe("S3 ein spaetes beenden()/finally des alten Codex schaltet den "
               "neuen Chat nicht ab (an, Zug laeuft)", an and zug, (an, zug))
        pruefe("S3 ... lehnt die offene Karte des neuen NICHT ab, und seine "
               "letzte Zeile beendet dessen Zug nicht", offen and not schluss,
               (offen, schluss))
        pruefe("S3 ... der neue Codex arbeitet danach normal weiter", fertig)
        an_m = codex_spaet(P_mut, C, U, TA)[0]
        pruefe("S3 KONTROLLE: ohne Generationsriegel schaltet das alte "
               "Gespraech den neuen Chat ab", not an_m, an_m)

        cli_dann_schleife(P, C, U)
        cli_dann_anbieter(P, C, U)
        codex_lebt(P, C, U, TA)

        spaet = schleife_spaete_antwort(P, C, U, TA)
        pruefe("S7 Schleife beendet, waehrend das Modell rechnet: seine "
               "spaete Antwort erscheint nicht mehr im Verlauf", not spaet,
               spaet)
        spaet = schleife_spaete_antwort(P, C, U, TA, beenden=False)
        pruefe("S7 KONTROLLE: ohne Beenden erscheint dieselbe Antwort",
               spaet == ["SPAET Schleife"], spaet)

        karte, auto, abgelehnt, gerufen = zwei_aufrufe(P, C, U, TA)
        pruefe("S8 zwei Aufrufe, Beenden bei offener Karte: der zweite laeuft "
               "nicht mehr (keine Auto-Freigabe, nichts beim Server, beide "
               "als abgelehnt gezaehlt)",
               karte == P.MCP_PRAEFIX + "execute_cadwork_command"
               and not auto and not gerufen and abgelehnt == 2,
               (karte, auto, gerufen, abgelehnt))
        karte, auto, abgelehnt, gerufen = zwei_aufrufe(P, C, U, TA,
                                                      beenden=False)
        pruefe("S8 KONTROLLE: ohne Beenden geht der zweite in 'lesen' "
               "automatisch durch und kommt beim Server an",
               auto == [P.MCP_PRAEFIX + "get_cadwork_api_help"]
               and gerufen == ["execute_cadwork_command", "get_cadwork_api_help"],
               (auto, gerufen))

        methoden, gestartet, zu, mcp, da = beenden_vor_server(P, C, U)
        pruefe("S9 beendet, bevor der MCP-Server eingetragen war: der Server "
               "bekommt keinen Auftrag mehr und endet",
               gestartet and not methoden and zu and mcp is None and not da,
               (gestartet, methoden, zu, mcp, da))
        methoden, gestartet, _z, _m, da = beenden_vor_server(P, C, U,
                                                            frueh=False)
        pruefe("S9 KONTROLLE: ohne das fruehe Beenden bekommt derselbe Server "
               "initialize und tools/list",
               methoden[:1] == ["initialize"] and "tools/list" in methoden,
               methoden)

        k, an, offen, fertig = schleife_spaetes_beenden(P, C, U, TA)
        pruefe("S10 Schleife: das spaete beenden() der abgeloesten Schleife "
               "lehnt die offene Karte des neuen Chats NICHT ab, der neue "
               "arbeitet weiter", k == "gestartet" and an and offen and fertig,
               (k[:60], an, offen, fertig))
        _k, _an, offen_m, _f = schleife_spaetes_beenden(P, C, U, TA,
                                                        kontrolle=True)
        pruefe("S10 KONTROLLE: hielte die alte Schleife die Kartenliste des "
               "neuen Chats, lehnte ihr beenden() die Karte ab", not offen_m,
               offen_m)

        antwort, auto = codex_frage_nach_ende(P, C, U, TA)
        pruefe("S11 Codex: eine Frage waehrend des Beendens wird abgelehnt — "
               "auch in 'auto' (decline beim App-Server, keine Auto-Zeile)",
               antwort == {"action": "decline"} and not auto, (antwort, auto))
        antwort, auto = codex_frage_nach_ende(P, C, U, TA, aus=False)
        pruefe("S11 KONTROLLE: nicht beendet, erlaubt 'auto' dieselbe Frage",
               antwort == {"action": "accept", "content": {}} and auto,
               (antwort, auto))

        zu, fehler, an, k = codex_handshake_scheitert(P, C, U)
        pruefe("S12 Codex: scheitert der Handshake, endet auch der App-Server "
               "(kein Waise), der Fehler steht im Chat",
               zu and "Anmeldung abgelaufen" in fehler and not an,
               (zu, fehler[:80], an))
        pruefe("S12 ... und der naechste Start gelingt", k == "gestartet",
               k[:90])
        k, lebt = codex_handshake_ohne_abraeumen(P, U)
        pruefe("S12 KONTROLLE: raeumt niemand ab, lebt derselbe App-Server "
               "nach dem gescheiterten Handshake weiter",
               "Anmeldung abgelaufen" in k and lebt, (k[:80], lebt))

        # --- 2b. Die vier Modi in allen drei Wegen (2026-09-27) --------------
        modi_cli(C, U)
        zusatz_ordner(C, U)
        modi_schleife(P, C, U, TA)
        modi_codex(P, C, U, TA)

        # --- 2c. Anhaenge in allen drei Wegen (K4) -----------------------
        anhaenge_cli(C, U)
        anhaenge_schleife(P, C, U, TA)
        anhaenge_codex(P, C, U, TA)

        # --- 2d. Gegenpruefung 2026-09-28 --------------------------------
        politik_tricks(C)
        erweiterungen_politik(C, U)
        erweiterungen_drei_wege(P, C, U, TA)
        monotonie(C)
        senden_tot(C)
        erlauben_nach_wechsel(C, U)
        befehlszeile(C, U)
        codex_ohne_namen(P, C, U, TA)
        bilder_scheitern(P, C, U, TA)

        # --- 3. Die Dock-Anweisung in allen drei Wegen ----------------------
        # Befund Film 2026-09-25: Markdown ("**Staebe**") und teils Englisch
        # in einem Fenster, das reinen Text zeigt.
        cli, schleife, codex = dock_anweisung_wege(P, C, U, TA)
        pruefe("M1 Claude Code: --append-system-prompt kommt hinter claude.cmd "
               "UNVERSEHRT an (Umlaute, ganzer Satz) und traegt die Regel",
               cli is not None and cli == getattr(C, "DOCK_ANWEISUNG", None)
               and klartext_regel(cli), (cli or "")[:90])
        # Der VOLLE Wortlaut, wie ihn M1 hinter claude.cmd sieht — nicht nur
        # Stichwoerter (Gegenpruefung 2026-09-26, Mutanten M19/M26).
        voll = getattr(C, "DOCK_ANWEISUNG", None)
        pruefe("M2 Schleife: die Systemnachricht an /chat/completions traegt "
               "die Regel im VOLLEN Wortlaut, Dokument und Port bleiben",
               klartext_regel(schleife) and voller_text(schleife, voll)
               and "Seeblick.3d" in (schleife or "")
               and "(Port 1)" in (schleife or ""),
               (schleife or "")[-90:])
        pruefe("M3 Codex: developerInstructions in thread/start tragen die "
               "Regel im VOLLEN Wortlaut",
               klartext_regel(codex) and voller_text(codex, voll),
               (codex or "")[-90:])
        # M4: die beiden Kopien (omcad_a_chat fuer das CLI, omcad_a_anbieter
        # fuer Schleife und Codex), gelesen aus dem QUELLTEXT. Ein Satz, der
        # nur in der einen fehlt, faellt hier auf — auch der letzte, der in
        # M2/M3 als Anfang des vollen Textes noch "enthalten" waere.
        q_chat, q_anb = dock_anweisung_quellen()
        t_chat, t_anb = quell_konstante(q_chat), quell_konstante(q_anb)
        pruefe("M4 DOCK_ANWEISUNG steht in omcad_a_chat.py und "
               "omcad_a_anbieter.py wortgleich (aus dem Quelltext) und ist, "
               "was M1 hinter claude.cmd sieht",
               t_chat is not None and t_chat == t_anb == voll
               and klartext_regel(t_chat),
               (len(t_chat or ""), len(t_anb or "")))
        # KONTROLLE M4: dieselbe Messung an Quelltexten, in denen EINE Kopie
        # veraendert ist. Die Stichwoerter halten dabei jedes Mal.
        falsch = []
        for art, veraendern in (("Satz fehlt", ohne_satz),
                                ("Sprachsatz verdreht", sprache_verdreht),
                                ("letzter Satz fehlt",
                                 lambda t: t.rsplit(" Das gilt", 1)[0])):
            for wo in ("chat", "anbieter"):
                neu = veraendern(t_chat or "")
                a = quell_konstante(quelle_mit(q_chat, neu) if wo == "chat"
                                    else q_chat)
                b = quell_konstante(quelle_mit(q_anb, neu) if wo == "anbieter"
                                    else q_anb)
                if not (neu != t_chat and klartext_regel(neu) and a != b):
                    falsch.append((art, wo))
        pruefe("M4 KONTROLLE: fehlt ein Satz, ist der Sprachsatz verdreht oder "
               "fehlt der letzte Satz — in EINER Kopie —, sieht der Vergleich "
               "es (die Stichwoerter nicht)", not falsch, falsch)
        # SP3 (2026-09-28): Codex bekommt bei "decline" keinen Text (das
        # Schema von codex-cli 0.156.1 kennt dort kein Feld) — die Anweisung
        # sagt der KI deshalb in ALLEN Wegen, was bei "Nur lesen" passiert.
        satz = "sag dem Nutzer kurz, was du tun wolltest"
        pruefe("SP3 alle drei Wege: die Anweisung erklaert Nur lesen (Hinweis, "
               "Wechsel, sagen was die KI wollte)",
               all(x and "Im Modus Nur lesen" in x and "Hinweis" in x
                   and satz in x for x in (cli, schleife, codex)),
               [(x or "")[-120:] for x in (cli, schleife, codex)])
        v_chat = quell_konstante(q_chat, "ABLEHNUNG_VORLAGE")
        v_anb = quell_konstante(q_anb, "ABLEHNUNG_VORLAGE")
        pruefe("SP4 ABLEHNUNG_VORLAGE in omcad_a_chat und omcad_a_anbieter "
               "wortgleich (aus dem Quelltext)",
               v_chat is not None and v_chat == v_anb, (v_chat, v_anb))
        v_mut = quell_konstante(quelle_mit(q_anb, ohne_satz(v_anb or ""),
                                           "ABLEHNUNG_VORLAGE"),
                                "ABLEHNUNG_VORLAGE")
        pruefe("SP4 KONTROLLE: fehlt in EINER Kopie ein Satz, sieht es der "
               "Vergleich", v_mut is not None and v_mut != v_chat)
        # KONTROLLE: dieselben drei Wege mit Modulen, deren Anweisung die
        # Regel NICHT traegt. Die Messung muss es in jedem Weg sehen — sonst
        # laese sie etwas anderes als das, was ankommt.
        C_ohne = laden("_chat_kern_ohne_regel", "omcad_a_chat.py")
        P_ohne = laden("_anbieter_kern_ohne_regel", "omcad_a_anbieter.py")
        C_ohne.DOCK_ANWEISUNG = P_ohne.DOCK_ANWEISUNG = "Antworte bitte."
        wege = dock_anweisung_wege(P_ohne, C_ohne, U, TA, "M_ohne")
        pruefe("M KONTROLLE: ohne die Regel ist jeder der drei Wege rot",
               wege[0] == "Antworte bitte."
               and not any(klartext_regel(x) for x in wege),
               [(x or "")[-60:] for x in wege])
        # KONTROLLE M2/M3: eine Anbieter-Kopie, der ein Satz fehlt bzw. deren
        # Sprachsatz verdreht ist (M19/M26 in omcad_a_anbieter), durch die
        # ECHTEN Wege gefahren. Die Stichwoerter halten dabei, der volle
        # Wortlaut nicht — genau das liessen M2/M3 bis 2026-09-26 durch.
        for kurz, art, veraendern in (("kurz", "ein Satz fehlt", ohne_satz),
                                      ("verdreht", "Sprachsatz verdreht",
                                       sprache_verdreht)):
            P_mut = laden("_anbieter_kern_%s" % kurz, "omcad_a_anbieter.py")
            P_mut.DOCK_ANWEISUNG = veraendern(P_mut.DOCK_ANWEISUNG)
            _c, s_m, x_m = dock_anweisung_wege(P_mut, C, U, TA, "M_" + kurz)
            pruefe("M2/M3 KONTROLLE: %s in omcad_a_anbieter -> Schleife UND "
                   "Codex rot, obwohl die Stichwoerter halten" % art,
                   P_mut.DOCK_ANWEISUNG != voll
                   and klartext_regel(s_m) and klartext_regel(x_m)
                   and not voller_text(s_m, voll)
                   and not voller_text(x_m, voll),
                   ((s_m or "")[-60:], (x_m or "")[-60:]))
    finally:
        try:
            U.aufraeumen(C)
        except Exception:                               # noqa: BLE001
            pass
        for k, v in alt_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    if all(_ergebnisse):
        shutil.rmtree(U.t, ignore_errors=True)
    else:
        print("  Protokolle der Attrappen: %s" % U.t)
    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
