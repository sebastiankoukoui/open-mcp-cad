#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer die Chat-Anbieter neben Claude Code (omcad_a_anbieter.py).

    python tests/test_anbieter.py        (-v zeigt jede Zeile)

Faehrt die ECHTE Schleife gegen Attrappen: einen OpenAI-kompatiblen
HTTP-Dienst auf einem ephemeren Port ausserhalb des Cadwork-Bereichs
(Antworten nach Drehbuch), einen
MCP-Server ueber stdio, der jeden `tools/call` in eine Datei schreibt, und
einen Codex-App-Server nach dem am 2026-09-24 gemessenen Protokoll.
Gemessen wird also, was beim Server ANKOMMT — nicht, was die Schleife zu
tun glaubt. Kein Netz, kein Schluessel, kein Cadwork.

Der Tresor-Test schreibt einen Eintrag unter einem eigenen Praefix in die
Windows-Anmeldeinformationsverwaltung und loescht ihn wieder.
"""

import ast
import http.server
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
A = os.path.join(REPO, "cad_plugin", "Open MCP CAD A")

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % ("ok  " if bedingung else "FEHL", titel,
                               ("  — %s" % (detail,)) if detail else ""))
    return bool(bedingung)


def laden(name, datei):
    spec = importlib.util.spec_from_file_location(name, os.path.join(A, datei))
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def laden_mit(name, datei, alt, neu):
    """Das Modul aus der QUELLE, mit `alt` -> `neu` ersetzt (Kontrollen).
    -> (Modul, Treffer). Treffer 0 heisst: die Stelle gibt es nicht mehr —
    dann ist es keine Kontrolle, und die Zelle wird rot."""
    pfad = os.path.join(A, datei)
    with io.open(pfad, encoding="utf-8") as fh:
        text = fh.read()
    treffer = text.count(alt)
    modul = type(sys)(name)
    modul.__file__ = pfad
    exec(compile(text.replace(alt, neu), pfad, "exec"), modul.__dict__)
    return modul, treffer


def warte(bedingung, frist=10.0):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.02)
    return bool(bedingung())


# --- Attrappe 1: OpenAI-kompatibler Dienst -------------------------------

def _kern_bereich():
    """PORT_VON..PORT_BIS aus dem Kern-QUELLTEXT — keine eigene Liste."""
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
    with io.open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    werte = {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
             if isinstance(k, ast.Assign) and len(k.targets) == 1
             and isinstance(k.targets[0], ast.Name)
             and k.targets[0].id in ("PORT_VON", "PORT_BIS")}
    return set(range(werte["PORT_VON"], werte["PORT_BIS"] + 1))


CADWORK_PORTS = _kern_bereich()


def _http_dienst(handler, verboten=None):
    """HTTP-Dienst auf einem ephemeren Port AUSSERHALB des Cadwork-Bereichs.

    Windows vergibt ephemere Ports ab 49152, der Cadwork-Bereich liegt
    mittendrin. Gebunden wird deshalb erst OHNE zu lauschen; liegt der Port
    in `verboten` (sonst: dem Cadwork-Bereich), wird er freigegeben und neu
    gezogen — wie `_ephemerer_socket` in test_bootstrap. `listen()` kommt
    erst danach: der Dienst nimmt nie auf einem Cadwork-Port an.
    """
    verboten = CADWORK_PORTS if verboten is None else verboten
    for _ in range(200):
        s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler,
                                            bind_and_activate=False)
        s.server_bind()
        if s.server_address[1] not in verboten:
            s.server_activate()
            return s
        s.server_close()
    raise RuntimeError("kein ephemerer Port ausserhalb des Cadwork-Bereichs")


class Dienst:
    """Antwortet nach Drehbuch und merkt sich jede Anfrage."""

    def __init__(self):
        self.drehbuch = []          # Liste von (Status, Koerper)
        self.anfragen = []          # (Pfad, Kopfzeilen, Koerper)
        dienst = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _antworten(self, status, koerper):
                roh = json.dumps(koerper).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(roh)))
                self.end_headers()
                self.wfile.write(roh)

            def do_GET(self):
                dienst.anfragen.append((self.path, dict(self.headers), None))
                self._antworten(200, {"data": [
                    {"id": "zeta-chat"}, {"id": "alpha-chat"},
                    {"id": "text-embedding-3-large"}, {"id": "alpha-chat"}]})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                koerper = json.loads(self.rfile.read(n).decode("utf-8"))
                dienst.anfragen.append((self.path, dict(self.headers), koerper))
                if dienst.drehbuch:
                    status, antwort = dienst.drehbuch.pop(0)
                else:
                    status, antwort = 200, text_antwort("(Drehbuch leer)")
                self._antworten(status, antwort)

        self.server = _http_dienst(Handler)
        self.port = self.server.server_address[1]
        self.basis = "http://127.0.0.1:%d/v1" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self):
        return [a for a in self.anfragen if a[2] is not None]


def text_antwort(text):
    # S10 (Etappe D): mit prompt/completion wie bei OpenAI — daraus kommt die
    # Kontextanzeige (letzte Runde), aus total_tokens die Summe je Zug.
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2,
                      "total_tokens": 7}}


def aufruf_antwort(name, argumente, kennung="call_1"):
    return {"choices": [{"message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": kennung, "type": "function", "function": {
            "name": name, "arguments": json.dumps(argumente)}}]}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 3,
                  "total_tokens": 11}}


# --- Attrappe 2: MCP-Server ueber stdio ----------------------------------

MCP_ATTRAPPE = r'''
import json, sys
protokoll = sys.argv[1]
WERKZEUGE = [
    {"name": "get_document_info", "description": "Dokument",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "execute_cadwork_command", "description": "Code ausfuehren",
     "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}},
                     "required": ["code"]}},
    {"name": "get_cadwork_api_help", "description": "Hilfe",
     "inputSchema": {"type": "object", "properties": {}}},
]
for zeile in sys.stdin:
    m = json.loads(zeile)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
             "serverInfo": {"name": "attrappe", "version": "1"},
             "instructions": "ATTRAPPEN-ANLEITUNG"}
    elif m["method"] == "tools/list":
        r = {"tools": WERKZEUGE}
    elif m["method"] == "tools/call":
        with open(protokoll, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(m["params"]) + "\n")
        r = {"content": [{"type": "text",
                          "text": "ERGEBNIS " + m["params"]["name"]}],
             "isError": False}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\n")
    sys.stdout.flush()
'''


# --- Attrappe 3: Codex-App-Server --------------------------------------------
# Spricht das Protokoll so, wie es codex-cli 0.156.1 am 2026-09-24 gemessen
# gesprochen hat: MCP-Aufruf -> item/started -> elicitation (id 0) ->
# nach der Antwort item/completed, Nachricht, turn/completed. Protokolliert
# thread/start, jede Antwort und jeden tatsaechlichen Aufruf.

CODEX_ATTRAPPE = r'''
import json, sys
protokoll = sys.argv[1]
werkzeug = [None]
def schreib(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
def log(o):
    with open(protokoll, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(o) + "\n")
def zug_ende(text):
    # S10: `last` und `modelContextWindow` wie in codex-cli 0.156.1
    # (ThreadTokenUsage, aus dem Programm gelesen).
    schreib({"method": "thread/tokenUsage/updated",
             "params": {"tokenUsage": {"total": {"totalTokens": 150},
                                       "last": {"totalTokens": 50,
                                                "inputTokens": 45,
                                                "outputTokens": 5},
                                       "modelContextWindow": 272000}}})
    schreib({"method": "item/started", "params": {"item": {"type": "agentMessage"}}})
    schreib({"method": "item/agentMessage/delta", "params": {"delta": text[:3]}})
    schreib({"method": "item/completed",
             "params": {"item": {"type": "agentMessage", "text": text}}})
    schreib({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
for zeile in sys.stdin:
    m = json.loads(zeile)
    meth = m.get("method")
    if "id" in m and meth is None:
        log({"antwort": m})
        if m["id"] == 0:
            ok = (m.get("result") or {}).get("action") == "accept"
            if ok:
                log({"gerufen": werkzeug[0]})
            schreib({"method": "item/completed", "params": {"item": {
                "type": "mcpToolCall", "id": "mcp1", "server": "open-mcp-cad", "tool": werkzeug[0],
                "status": "completed" if ok else "failed",
                "error": None if ok else {"message": "user rejected MCP tool call"}}}})
            zug_ende("fertig" if ok else "abgelehnt")
        elif m["id"] == 7:
            zug_ende("ohne Shell")
        continue
    if meth == "initialize":
        schreib({"id": m["id"], "result": {"userAgent": "attrappe"}})
    elif meth == "thread/start":
        log({"thread_start": m["params"]})
        schreib({"id": m["id"], "result": {"thread": {"id": "t1"}}})
        schreib({"method": "mcpServer/startupStatus/updated",
                 "params": {"name": "open-mcp-cad", "status": "ready"}})
    elif meth == "model/list":
        schreib({"id": m["id"], "result": {"data": [
            {"model": "gpt-a", "hidden": False}, {"model": "gpt-geheim", "hidden": True},
            {"id": "gpt-b", "hidden": False}]}})
    elif meth == "turn/start":
        log({"turn_start": m["params"]})
        text = m["params"]["input"][0]["text"]
        schreib({"id": m["id"], "result": {"turn": {"id": "u1", "status": "inProgress"}}})
        schreib({"method": "thread/tokenUsage/updated",
                 "params": {"tokenUsage": {"total": {"totalTokens": 100},
                                           "last": {"totalTokens": 100},
                                           "modelContextWindow": 272000}}})
        if "shell" in text:
            schreib({"id": 7, "method": "item/commandExecution/requestApproval",
                     "params": {"command": "dir"}})
            continue
        werkzeug[0] = "get_cadwork_api_help" if "hilfe" in text else "execute_cadwork_command"
        argumente = {} if "hilfe" in text else {"code": "x = 1"}
        schreib({"method": "item/started", "params": {"item": {"type": "reasoning"}}})
        schreib({"method": "item/started", "params": {"item": {
            "type": "mcpToolCall", "id": "mcp1", "server": "open-mcp-cad", "tool": werkzeug[0],
            "arguments": argumente}}})
        schreib({"id": 0, "method": "mcpServer/elicitation/request", "params": {
            "serverName": "open-mcp-cad", "mode": "form",
            "message": 'Allow the open-mcp-cad MCP server to run tool "%s"?' % werkzeug[0],
            "_meta": {"codex_approval_kind": "mcp_tool_call",
                      "persist": ["session", "always"], "tool_params": argumente}}})
'''


def codex_zellen(P, C, t, warte, arten):
    attrappe = os.path.join(t, "codex_attrappe.py")
    with io.open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(CODEX_ATTRAPPE)
    heim = os.path.join(t, "codex_heim")
    os.makedirs(heim)
    with io.open(os.path.join(heim, "config.toml"), "w", encoding="utf-8") as fh:
        fh.write('model = "x"\n[mcp_servers.alt-a]\ncommand = "a"\n'
                 '[mcp_servers.alt-b]\ncommand = "b"\n'
                 '[mcp_servers.open-mcp-cad]\ncommand = "alt"\n')
    alt_heim = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = heim
    server = ([sys.executable, "-c", "pass"], {"OPEN_MCP_CAD_PORT": "53999"})

    def protokoll_von(name):
        return os.path.join(t, "codex_%s.log" % name)

    def eintraege(pfad):
        try:
            with io.open(pfad, encoding="utf-8") as fh:
                return [json.loads(z) for z in fh if z.strip()]
        except OSError:
            return []

    def neu(stufe, name, erlauben=None):
        pfad = protokoll_von(name)
        chat = {"modus": stufe}
        P.starten(chat, "codex", "", erlauben or C.chat_entscheiden,
                  server=server, dokument="Seeblick.3d", port=53999,
                  codex_befehl=[sys.executable, attrappe, pfad])
        warte(lambda: chat.get("werkzeuge_da"))
        return chat, pfad

    try:
        # -- Modelle und Abschottung -------------------------------------
        namen = P.codex_modelle(befehl=[sys.executable, attrappe,
                                        protokoll_von("modelle")])
        pruefe("C1 Codex-Modelle ueber model/list, ohne versteckte",
               namen == ["gpt-a", "gpt-b"], namen)
        k = P.codex_konfig(server)
        mcp = k["mcp_servers"]
        pruefe("C2 fremde Server aus config.toml sind abgeschaltet",
               mcp.get("alt-a") == {"enabled": False}
               and mcp.get("alt-b") == {"enabled": False}, mcp)
        pruefe("C2 unser Server kommt aus server_befehl, nicht aus config.toml",
               mcp.get("open-mcp-cad", {}).get("command") == sys.executable
               and mcp["open-mcp-cad"].get("env") == {"OPEN_MCP_CAD_PORT": "53999"})
        pruefe("C2 Shell, Plugins, Apps, Browser, Computer-Use aus",
               all(k["features"].get(f) is False for f in
                   ("shell_tool", "plugins", "apps", "browser_use",
                    "computer_use", "in_app_browser")), k["features"])
        with io.open(os.path.join(heim, "config.toml"), "a", encoding="utf-8") as fh:
            fh.write("[[kaputt\n")
        try:
            P.codex_konfig(server)
            kk = "gelesen"
        except P.AnbieterFehler as exc:
            kk = str(exc)
        pruefe("C2 KONTROLLE: unlesbare config.toml = kein Start",
               "nicht lesbar" in kk, kk[:80])
        with io.open(os.path.join(heim, "config.toml"), "w", encoding="utf-8") as fh:
            fh.write('[mcp_servers.alt-a]\ncommand = "a"\n')

        # -- Ein Zug mit Karte ----------------------------------------------
        chat, pfad = neu("fragen", "zug")
        C.senden(chat, "zeichne")
        warte(lambda: C.offene_freigaben(chat))
        karte = C.offene_freigaben(chat)
        vorher = [e for e in eintraege(pfad) if "gerufen" in e]
        start = next((e["thread_start"] for e in eintraege(pfad)
                      if "thread_start" in e), {})
        pruefe("C3 thread/start: on-request, Pruefer = Nutzer, read-only, fluechtig",
               start.get("approvalPolicy") == "on-request"
               and start.get("approvalsReviewer") == "user"
               and start.get("sandbox") == "read-only"
               and start.get("ephemeral") is True, start)
        pruefe("C3 thread/start traegt die Abschottung und Dokument/Port",
               start.get("config", {}).get("mcp_servers", {}).get("alt-a")
               == {"enabled": False}
               and "Seeblick.3d" in (start.get("developerInstructions") or ""))
        pruefe("C3 Karte offen, Werkzeug NICHT gerufen",
               bool(karte) and not vorher
               and karte[0]["werkzeug"] == "mcp__open-mcp-cad__execute_cadwork_command"
               and karte[0]["eingabe"] == {"code": "x = 1"}, (karte, vorher))
        if karte:
            C.freigabe_beantworten(chat, karte[0]["id"], True)
        warte(lambda: "schluss" in arten(chat))
        log = eintraege(pfad)
        antwort = next((e["antwort"] for e in log if "antwort" in e), {})
        pruefe("C3 erlaubt: accept OHNE persist, dann gerufen",
               antwort.get("result") == {"action": "accept", "content": {}}
               and {"gerufen": "execute_cadwork_command"} in log, antwort)
        pruefe("C3 Verlauf: ich, werkzeug, ergebnis, text, schluss mit Token "
               "dieses Zugs", arten(chat) == ["ich", "werkzeug", "ergebnis",
                                               "text", "schluss"]
               and chat["ereignisse"][-1].get("token") == 150, chat["ereignisse"])
        # S10: der Kontext ist die LETZTE Anfrage gegen das Fenster des
        # Modells, nicht die Summe der Sitzung (total 150).
        pruefe("C3b Kontext: last.totalTokens gegen modelContextWindow",
               chat.get("kontext") == {"belegt": 50, "fenster": 272000},
               chat.get("kontext"))
        C.beenden(chat)
        # KONTROLLE: mit der Summe der Sitzung statt der letzten Anfrage.
        P_mut, n_mut = laden_mit(
            "_anbieter_codex_summe", "omcad_a_anbieter.py",
            "kontext = _codex_kontext(nutzung)",
            'kontext = _codex_kontext({"last": gesamt, "modelContextWindow":'
            ' nutzung.get("modelContextWindow")})')
        k_chat = {"modus": "alles_auto"}
        P_mut.starten(k_chat, "codex", "", C.chat_entscheiden,
                      server=server, dokument="Seeblick.3d", port=53999,
                      codex_befehl=[sys.executable, attrappe,
                                    protokoll_von("summe")])
        warte(lambda: k_chat.get("werkzeuge_da"))
        C.senden(k_chat, "zeichne")
        warte(lambda: "schluss" in arten(k_chat))
        pruefe("C3b KONTROLLE: die Summe der Sitzung statt der letzten "
               "Anfrage -> rot",
               n_mut == 1 and k_chat.get("kontext") == {"belegt": 150,
                                                        "fenster": 272000},
               (n_mut, k_chat.get("kontext")))
        C.beenden(k_chat)

        # -- Ablehnen --------------------------------------------------------
        chat, pfad = neu("fragen", "nein")
        C.senden(chat, "zeichne")
        warte(lambda: C.offene_freigaben(chat))
        C.freigabe_beantworten(chat, C.offene_freigaben(chat)[0]["id"], False)
        warte(lambda: "schluss" in arten(chat))
        log = eintraege(pfad)
        pruefe("C4 abgelehnt: decline, nie gerufen, als Ablehnung gezaehlt",
               any(e.get("antwort", {}).get("result") == {"action": "decline"}
                   for e in log)
               and not any("gerufen" in e for e in log)
               and chat["ereignisse"][-1].get("abgelehnt") == 1, log[-3:])
        C.beenden(chat)

        # -- Nachschlagen laeuft in 'lesen' ohne Karte -----------------------
        chat, pfad = neu("fragen", "hilfe")
        C.senden(chat, "hilfe")
        warte(lambda: "schluss" in arten(chat))
        pruefe("C5 get_cadwork_api_help: automatisch erlaubt, sichtbar",
               {"gerufen": "get_cadwork_api_help"} in eintraege(pfad)
               and "auto" in arten(chat) and not chat["freigaben"], arten(chat))
        C.beenden(chat)

        # -- Kontrolle: ohne Politik keine Karte -----------------------------
        chat, pfad = neu("fragen", "mutant", lambda *a: True)
        C.senden(chat, "zeichne")
        warte(lambda: "schluss" in arten(chat))
        pruefe("C6 KONTROLLE: ohne Freigabe-Politik liefe execute ohne Karte",
               {"gerufen": "execute_cadwork_command"} in eintraege(pfad)
               and not chat["freigaben"])
        C.beenden(chat)

        # -- Unerwartetes wird abgelehnt --------------------------------------
        chat, pfad = neu("alles_auto", "shell")
        C.senden(chat, "shell bitte")
        warte(lambda: "schluss" in arten(chat))
        log = eintraege(pfad)
        pruefe("C7 eine Shell-Freigabe wird abgelehnt — auch in 'auto'",
               any(e.get("antwort", {}).get("result") == {"decision": "decline"}
                   for e in log)
               and any("abgelehnt" in e.get("text", "") for e in chat["ereignisse"]),
               log[-2:])
        C.beenden(chat)

        # -- Beenden bei offener Karte -----------------------------------------
        chat, pfad = neu("fragen", "ende")
        C.senden(chat, "zeichne")
        warte(lambda: C.offene_freigaben(chat))
        C.beenden(chat)
        warte(lambda: any("antwort" in e for e in eintraege(pfad)), 5)
        log = eintraege(pfad)
        pruefe("C8 beendet mit offener Karte: decline geschickt, nie gerufen",
               any(e.get("antwort", {}).get("result") == {"action": "decline"}
                   for e in log)
               and not any("gerufen" in e for e in log)
               and not chat.get("an"), log[-2:])
    finally:
        if alt_heim is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = alt_heim

    # -- Ohne CLI: klare Meldung -------------------------------------------
    alt_app, alt_path = os.environ.get("APPDATA"), os.environ.get("PATH")
    os.environ["APPDATA"] = os.path.join(t, "leer")
    os.environ["PATH"] = os.path.join(t, "leer")
    try:
        try:
            P.codex_pfad()
            kp = "gefunden"
        except P.AnbieterFehler as exc:
            kp = str(exc)
        pruefe("C9 ohne Codex-CLI: Meldung mit Installationsbefehl",
               "npm i -g @openai/codex" in kp, kp[:90])
    finally:
        os.environ["APPDATA"], os.environ["PATH"] = alt_app, alt_path


# --- chat.json robust schreiben (Gegenpruefung 2026-09-26) -----------------
# So tief verschachtelt liest `json.load` (der C-Leser) ein chat.json noch,
# `json.dump` mit `indent` (reines Python) schreibt es aber nicht mehr zurueck.
# Gemessen 2026-09-26 mit Python 3.12.10: Lesen bis ~2000 Ebenen, Schreiben
# mit indent ab 1000 RecursionError. A13b prueft die Vorbedingung selbst.
TIEFE = 1500


def _alt_schreiben(P, daten):
    """So schrieb `einstellungen_schreiben` bis 2026-09-26 — die Kontrolle."""
    pfad = P._einstellungs_datei()
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with io.open(pfad, "w", encoding="utf-8") as fh:
            json.dump(daten, fh, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def _schreib_lauf(P, schreiben, roh, aendern):
    """chat.json = `roh`, lesen, `aendern(daten)`, mit `schreiben` zurueck.

    -> dict: geworfen (Typname oder None), rueckgabe, gleich (Datei Byte fuer
    Byte wie vorher), lesbar (danach noch JSON), rest (Dateien im Ordner
    ausser chat.json), anbieter (wie ihn einstellungen_lesen vorher sah)."""
    pfad = P._einstellungs_datei()
    ordner = os.path.dirname(pfad)
    shutil.rmtree(ordner, ignore_errors=True)
    os.makedirs(ordner)
    with io.open(pfad, "wb") as fh:
        fh.write(roh.encode("utf-8"))
    daten = P.einstellungen_lesen()
    m = {"anbieter": daten.get("anbieter"), "geworfen": None, "rueckgabe": None}
    aendern(daten)
    try:
        m["rueckgabe"] = schreiben(daten)
    except Exception as exc:                           # noqa: BLE001
        m["geworfen"] = type(exc).__name__
    with io.open(pfad, "rb") as fh:
        nachher = fh.read()
    m["gleich"] = nachher == roh.encode("utf-8")
    try:
        json.loads(nachher.decode("utf-8"))
        m["lesbar"] = True
    except (ValueError, RecursionError):
        m["lesbar"] = False
    m["rest"] = sorted(set(os.listdir(ordner)) - {"chat.json"})
    return m


def einstellungen_robust(P, ordner):
    """A13b: `einstellungen_schreiben` wirft nie und schreibt nie halb."""
    alt = os.environ.get("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN")
    os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = os.path.join(
        ordner + "_robust", "chat.json")
    tief = ('{"anbieter": "claude", "x": ' + "[" * TIEFE + "]" * TIEFE + "}")
    neu = P.einstellungen_schreiben

    def wechsel(d):
        d["anbieter"] = "openai"

    def menge(d):
        d["anbieter"] = "openai"
        d["y"] = {1, 2}                 # kein JSON-Typ

    try:
        m = _schreib_lauf(P, neu, tief, wechsel)
        pruefe("A13b Vorbedingung: json.load liest %d Ebenen noch" % TIEFE,
               m["anbieter"] == "claude", m)
        pruefe("A13b %d Ebenen tief: kein Fehler, False, die Datei Byte fuer "
               "Byte unberuehrt, keine Temp-Datei liegt herum" % TIEFE,
               m["geworfen"] is None and m["rueckgabe"] is False and m["gleich"]
               and not m["rest"], m)
        m = _schreib_lauf(P, neu, '{"anbieter": "claude"}', menge)
        pruefe("A13b kein JSON-Typ im Inhalt: ebenso False und unberuehrt",
               m["geworfen"] is None and m["rueckgabe"] is False and m["gleich"]
               and not m["rest"], m)
        m = _schreib_lauf(P, neu, '{"anbieter": "claude"}', wechsel)
        pruefe("A13b KONTROLLE: ein normaler Inhalt wird geschrieben (True, "
               "gelesen wie geschrieben, keine Temp-Datei)",
               m["rueckgabe"] is True and not m["gleich"] and m["lesbar"]
               and P.einstellungen_lesen() == {"anbieter": "openai"}
               and not m["rest"], m)
        # KONTROLLE am alten Verhalten: dieselben beiden Laeufe mit dem
        # Schreiben bis 2026-09-26. Die Messung muss es sehen.
        m = _schreib_lauf(P, lambda d: _alt_schreiben(P, d), tief, wechsel)
        pruefe("A13b KONTROLLE: das alte Schreiben wirft RecursionError und "
               "laesst ein halb geschriebenes chat.json zurueck",
               m["geworfen"] == "RecursionError" and not m["gleich"]
               and not m["lesbar"], m)
        m = _schreib_lauf(P, lambda d: _alt_schreiben(P, d),
                          '{"anbieter": "claude"}', menge)
        pruefe("A13b KONTROLLE: ... und bei einem Nicht-JSON-Typ TypeError, "
               "ebenfalls halb geschrieben",
               m["geworfen"] == "TypeError" and not m["gleich"]
               and not m["lesbar"], m)
    finally:
        if alt is None:
            os.environ.pop("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN", None)
        else:
            os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = alt


def main():
    # Die Konsole ist cp1252; "⚠" in einer Detailzeile darf das Gate nicht
    # mit einem UnicodeEncodeError abbrechen.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print("Chat-Anbieter — Gate\n")
    P = laden("_anbieter_gate", "omcad_a_anbieter.py")
    C = laden("_chat_gate_anbieter", "omcad_a_chat.py")
    t = tempfile.mkdtemp(prefix="omcad_anbieter_")
    attrappe = os.path.join(t, "mcp_attrappe.py")
    with io.open(attrappe, "w", encoding="utf-8") as fh:
        fh.write(MCP_ATTRAPPE)
    D = Dienst()
    eigen = dict(P.anbieter("eigen"))

    # --- 0. Der Dienst lauscht nie im Cadwork-Bereich ----------------------
    pruefe("A0 der Modell-Dienst lauscht ausserhalb des Cadwork-Bereichs",
           bool(CADWORK_PORTS) and D.port not in CADWORK_PORTS,
           "Port %d, Bereich %d Ports" % (D.port, len(CADWORK_PORTS)))
    try:
        _http_dienst(http.server.BaseHTTPRequestHandler,
                     verboten=range(1, 65536)).server_close()
        k = "bekam einen Port"
    except RuntimeError:
        k = "wirft"
    pruefe("A0 KONTROLLE: ist alles verboten, gibt _http_dienst auf",
           k == "wirft", "%s — sonst prueft er den Bereich gar nicht" % k)

    def server(name):
        protokoll = os.path.join(t, name + ".log")
        return (([sys.executable, attrappe, protokoll], {}), protokoll)

    def gerufen(protokoll):
        try:
            with io.open(protokoll, encoding="utf-8") as fh:
                return [json.loads(z)["name"] for z in fh if z.strip()]
        except OSError:
            return []

    def neuer_chat(stufe, name, erlauben=None):
        chat = {"modus": stufe}
        srv, protokoll = server(name)
        P.starten(chat, "eigen", "alpha-chat", erlauben or C.chat_entscheiden,
                  basis=D.basis, server=srv, dokument="Seeblick.3d", port=53999)
        warte(lambda: chat.get("werkzeuge_da"))
        return chat, protokoll

    def arten(chat):
        return [e["art"] for e in chat["ereignisse"]]

    # --- 1. Modelle vom Dienst, nicht aus dem Code ------------------------
    D.anfragen.clear()
    ids = P.modelle_laden(eigen, D.basis, "sk-test")
    pruefe("A1 Modelle kommen vom Dienst, sortiert, ohne Doppel",
           ids == ["alpha-chat", "text-embedding-3-large", "zeta-chat"], ids)
    kopf = D.anfragen[-1][1]
    pruefe("A1 mit Bearer-Schluessel gefragt",
           kopf.get("Authorization") == "Bearer sk-test", kopf.get("Authorization"))
    oa = dict(P.anbieter("openai"), basis=D.basis)
    ids = P.modelle_laden(oa, D.basis, "sk-test")
    pruefe("A1 bei OpenAI fallen Einbettungen & Co. raus",
           "text-embedding-3-large" not in ids and "alpha-chat" in ids, ids)
    an = dict(P.anbieter("anthropic"), basis=D.basis)
    P.modelle_laden(an, D.basis, "sk-ant")
    # HTTP-Kopfzeilen kennen kein Gross/Klein; urllib schreibt "X-Api-Key".
    kopf = {k.lower(): v for k, v in D.anfragen[-1][1].items()}
    pruefe("A1 Anthropic bekommt x-api-key und anthropic-version",
           kopf.get("x-api-key") == "sk-ant"
           and kopf.get("anthropic-version") == "2023-06-01", kopf)
    try:
        P.modelle_laden(eigen, "http://127.0.0.1:9/v1", timeout=2)
        k = "kein Fehler"
    except P.AnbieterFehler as exc:
        k = str(exc)
    pruefe("A1 KONTROLLE: ein toter Dienst meldet sich laut",
           "nicht erreichbar" in k, k[:90])

    # --- 2. Pflichtangaben brechen VOR dem Start ab -----------------------
    alt_env = os.environ.pop("OPENAI_API_KEY", None)
    alt_praefix = P.TRESOR_PRAEFIX
    P.TRESOR_PRAEFIX = "Open MCP CAD TEST %s/" % uuid.uuid4().hex[:8]
    try:
        try:
            P.starten({}, "openai", "alpha-chat", C.chat_entscheiden)
            k = "gestartet"
        except P.AnbieterFehler as exc:
            k = str(exc)
        pruefe("A2 ohne Schluessel startet OpenAI nicht — mit Ausweg im Text",
               "Schlüssel fehlt" in k and "OPENAI_API_KEY" in k, k[:120])
        os.environ["OPENAI_API_KEY"] = "sk-aus-env"
        wert, herkunft = P.schluessel_fuer(P.anbieter("openai"))
        pruefe("A2 KONTROLLE: aus der Umgebung wird er gefunden",
               wert == "sk-aus-env" and "OPENAI_API_KEY" in herkunft, herkunft)
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        if alt_env is not None:
            os.environ["OPENAI_API_KEY"] = alt_env
    try:
        P.starten({}, "eigen", "  ", C.chat_entscheiden, basis=D.basis)
        k = "gestartet"
    except P.AnbieterFehler as exc:
        k = str(exc)
    pruefe("A2 ohne Modell kein Start", "kein Modell" in k, k[:80])
    try:
        P.starten({}, "eigen", "m", C.chat_entscheiden, basis="localhost:1")
        k = "gestartet"
    except P.AnbieterFehler as exc:
        k = str(exc)
    pruefe("A2 eine Adresse ohne http(s) wird abgewiesen",
           "keine gueltige Adresse" in k, k[:80])

    # --- 3. Tresor --------------------------------------------------------
    if os.name == "nt":
        try:
            pruefe("A3 KONTROLLE: nie Gespeichertes liest sich als None",
                   P.schluessel_lesen("gibtsnicht") is None)
            P.schluessel_speichern("eigen", "  sk-geheim-äö  ")
            pruefe("A3 Tresor: speichern und lesen (getrimmt, UTF-8)",
                   P.schluessel_lesen("eigen") == "sk-geheim-äö")
            wert, herkunft = P.schluessel_fuer(P.anbieter("eigen"))
            pruefe("A3 der Tresor geht vor", wert == "sk-geheim-äö"
                   and "Tresor" in herkunft, herkunft)
            pruefe("A3 loeschen", P.schluessel_loeschen("eigen")
                   and P.schluessel_lesen("eigen") is None)
        finally:
            P.schluessel_loeschen("eigen")
            P.TRESOR_PRAEFIX = alt_praefix

    # --- 4. Ein ganzer Zug: Werkzeug, Ergebnis, Antwort --------------------
    D.anfragen.clear()
    D.drehbuch[:] = [(200, aufruf_antwort("get_document_info", {})),
                     (200, text_antwort("Das Dokument heisst Seeblick."))]
    chat, protokoll = neuer_chat("alles_auto", "zug")
    pruefe("A4 der MCP-Server laeuft, Werkzeuge da", chat.get("werkzeuge_da"),
           chat.get("ereignisse"))
    C.senden(chat, "Wie heisst das Dokument?")
    warte(lambda: "schluss" in arten(chat))
    pruefe("A4 Reihenfolge ich, werkzeug, auto, ergebnis, text, schluss",
           arten(chat) == ["ich", "werkzeug", "auto", "ergebnis", "text",
                           "schluss"],
           arten(chat))
    pruefe("A4 der Server wurde WIRKLICH gerufen",
           gerufen(protokoll) == ["get_document_info"], gerufen(protokoll))
    posts = D.posts()
    zweite = posts[1][2]["messages"] if len(posts) > 1 else []
    pruefe("A4 das Ergebnis ging als tool-Nachricht zurueck ans Modell",
           any(m.get("role") == "tool" and m.get("content") == "ERGEBNIS get_document_info"
               and m.get("tool_call_id") == "call_1" for m in zweite), zweite[-2:])
    erste = posts[0][2] if posts else {}
    system = (erste.get("messages") or [{}])[0].get("content") or ""
    pruefe("A4 Systemtext nennt Dokument, Port und die Server-Anleitung",
           "Seeblick.3d" in system and "53999" in system
           and "ATTRAPPEN-ANLEITUNG" in system, system[:120])
    pruefe("A4 dem Modell werden genau die 3 Server-Werkzeuge angeboten",
           sorted(w["function"]["name"] for w in erste.get("tools") or [])
           == ["execute_cadwork_command", "get_cadwork_api_help",
               "get_document_info"])
    schluss = chat["ereignisse"][-1]
    pruefe("A4 Token gezaehlt, Zug beendet",
           schluss.get("token") == 18 and not chat.get("laeuft_zug"), schluss)
    # S10 (Etappe D): der Kontext ist die LETZTE Runde (Frage 5 + Antwort 2),
    # nicht die Summe des Zugs (18); ein Fenster meldet die Schleife nicht.
    pruefe("A4b Kontext: letzte Runde, ohne Fenster",
           chat.get("kontext") == {"belegt": 7, "fenster": None},
           chat.get("kontext"))
    C.beenden(chat)
    pruefe("A4 beenden raeumt ab", warte(lambda: not chat.get("an")))
    chat["kontext"] = {"belegt": 99, "fenster": None}
    P.starten(chat, "eigen", "alpha-chat", C.chat_entscheiden,
              basis=D.basis, server=None, port=53999)
    pruefe("A4b ein neuer Start beginnt ohne Kontext",
           chat.get("kontext") is None, chat.get("kontext"))
    C.beenden(chat)
    warte(lambda: not chat.get("an"))
    # KONTROLLE: dieselbe Messung mit einer Schleife, die die Summe des Zugs
    # nimmt — sie muss sie sehen.
    P_sum, n_sum = laden_mit("_anbieter_summe", "omcad_a_anbieter.py",
                             'belegt = _runde_belegt(antwort.get("usage"))',
                             "belegt = token")
    D.drehbuch[:] = [(200, aufruf_antwort("get_document_info", {})),
                     (200, text_antwort("Das Dokument heisst Seeblick."))]
    k_chat = {"modus": "alles_auto"}
    srv, _p = server("zug_summe")
    P_sum.starten(k_chat, "eigen", "alpha-chat", C.chat_entscheiden,
                  basis=D.basis, server=srv, port=53999)
    warte(lambda: k_chat.get("werkzeuge_da"))
    C.senden(k_chat, "Wie heisst das Dokument?")
    warte(lambda: "schluss" in arten(k_chat))
    pruefe("A4b KONTROLLE: die Summe des Zugs statt der letzten Runde -> rot",
           n_sum == 1 and k_chat.get("kontext") == {"belegt": 18,
                                                    "fenster": None},
           (n_sum, k_chat.get("kontext")))
    C.beenden(k_chat)
    warte(lambda: not k_chat.get("an"))

    # --- 5. Das Gate: Cadwork fragt IMMER, bis zur Antwort passiert nichts --
    def gate_haelt(erlauben):
        D.drehbuch[:] = [
            (200, aufruf_antwort("execute_cadwork_command", {"code": "x = 1"})),
            (200, text_antwort("erledigt"))]
        chat, protokoll = neuer_chat("fragen", "gate_%d" % time.monotonic_ns(),
                                     erlauben)
        C.senden(chat, "zeichne")
        warte(lambda: C.offene_freigaben(chat) or "schluss" in arten(chat), 5)
        time.sleep(0.3)
        karte = C.offene_freigaben(chat)
        vorher = gerufen(protokoll)
        ok = bool(karte) and vorher == []
        if karte:
            C.freigabe_beantworten(chat, karte[0]["id"], True)
            warte(lambda: "schluss" in arten(chat))
            ok = ok and gerufen(protokoll) == ["execute_cadwork_command"]
        C.beenden(chat)
        return ok, karte, vorher

    ok, karte, vorher = gate_haelt(C.chat_entscheiden)
    pruefe("A5 execute: Karte offen, Server NICHT gerufen; nach Erlauben gerufen",
           ok, "Karte %s, vorher %s" % (bool(karte), vorher))
    pruefe("A5 die Karte zeigt den Code",
           bool(karte) and karte[0]["eingabe"].get("code") == "x = 1"
           and karte[0]["werkzeug"] == "mcp__open-mcp-cad__execute_cadwork_command")
    ok_k, _k, vorher_k = gate_haelt(lambda *a: True)
    pruefe("A5 KONTROLLE: ohne Freigabe-Politik faellt es auf",
           not ok_k and vorher_k == ["execute_cadwork_command"], vorher_k)

    # --- 6. Ablehnen: nicht ausgefuehrt, das Modell erfaehrt es -------------
    D.anfragen.clear()
    D.drehbuch[:] = [
        (200, aufruf_antwort("execute_cadwork_command", {"code": "loesche()"})),
        (200, text_antwort("Verstanden, nichts geloescht."))]
    chat, protokoll = neuer_chat("fragen", "nein")
    C.senden(chat, "loesch alles")
    warte(lambda: C.offene_freigaben(chat))
    C.freigabe_beantworten(chat, C.offene_freigaben(chat)[0]["id"], False, "zu heikel")
    warte(lambda: "schluss" in arten(chat))
    zweite = D.posts()[1][2]["messages"] if len(D.posts()) > 1 else []
    tool = [m for m in zweite if m.get("role") == "tool"]
    pruefe("A6 abgelehnt: Server nicht gerufen",
           gerufen(protokoll) == [], gerufen(protokoll))
    pruefe("A6 das Modell bekommt die Ablehnung mit Grund",
           bool(tool) and "abgelehnt" in tool[0]["content"]
           and "zu heikel" in tool[0]["content"], tool)
    pruefe("A6 der Schluss zaehlt die Ablehnung",
           chat["ereignisse"][-1].get("abgelehnt") == 1)
    C.beenden(chat)

    # --- 7. Lesendes Nachschlagen geht in 'lesen' ohne Karte ------------------
    D.drehbuch[:] = [(200, aufruf_antwort("get_cadwork_api_help", {})),
                     (200, text_antwort("ok"))]
    chat, protokoll = neuer_chat("fragen", "hilfe")
    C.senden(chat, "hilfe")
    warte(lambda: "schluss" in arten(chat))
    pruefe("A7 get_cadwork_api_help laeuft in 'lesen' automatisch (wie beim CLI)",
           gerufen(protokoll) == ["get_cadwork_api_help"]
           and "auto" in arten(chat), arten(chat))
    C.beenden(chat)

    # --- 8. Beenden bei offener Karte = ablehnen -------------------------
    D.drehbuch[:] = [
        (200, aufruf_antwort("execute_cadwork_command", {"code": "y = 2"}))]
    chat, protokoll = neuer_chat("fragen", "ende")
    C.senden(chat, "zeichne")
    warte(lambda: C.offene_freigaben(chat))
    offen = list(C.offene_freigaben(chat))
    C.beenden(chat)
    time.sleep(0.3)
    pruefe("A8 beendet mit offener Karte: nichts ausgefuehrt",
           bool(offen) and gerufen(protokoll) == []
           and offen[0].get("antwort") == "abgelehnt"
           and not chat.get("an"), (len(offen), gerufen(protokoll)))

    # --- 9. HTTP-Fehler: sichtbar, der Chat bleibt benutzbar --------------
    D.drehbuch[:] = [(401, {"error": {"message": "Incorrect API key"}}),
                     (200, text_antwort("jetzt geht es"))]
    chat, protokoll = neuer_chat("fragen", "http")
    C.senden(chat, "hallo")
    warte(lambda: "schluss" in arten(chat))
    texte = [e.get("text", "") for e in chat["ereignisse"] if e["art"] == "text"]
    pruefe("A9 401 steht im Verlauf, mit dem Text des Dienstes",
           any("HTTP 401" in x and "Incorrect API key" in x for x in texte), texte)
    pruefe("A9 der Schluss traegt den Fehler, der Chat laeuft weiter",
           chat["ereignisse"][-1].get("fehler") is True and chat.get("an"))
    C.senden(chat, "nochmal")
    warte(lambda: arten(chat).count("schluss") == 2)
    pruefe("A9 die naechste Nachricht geht wieder",
           chat["ereignisse"][-2].get("text") == "jetzt geht es",
           chat["ereignisse"][-2:])
    C.beenden(chat)

    # --- 10. Ohne MCP-Server: sagen, nicht still reden -------------------
    D.anfragen.clear()
    D.drehbuch[:] = [(200, text_antwort("ohne Werkzeuge"))]
    chat = {"modus": "fragen"}
    P.starten(chat, "eigen", "alpha-chat", C.chat_entscheiden, basis=D.basis,
              server=([os.path.join(t, "gibtsnicht.exe")], {}))
    warte(lambda: chat["ereignisse"])
    C.senden(chat, "hallo")
    warte(lambda: "schluss" in arten(chat))
    pruefe("A10 ohne Server: Warnung im Verlauf, werkzeuge_da falsch",
           not chat.get("werkzeuge_da") and "Cadwork-Werkzeuge nicht"
           in chat["ereignisse"][0].get("text", ""), chat["ereignisse"][:1])
    pruefe("A10 und dem Modell werden keine Werkzeuge angeboten",
           D.posts() and "tools" not in D.posts()[0][2])
    C.beenden(chat)

    # --- 11. Kreisel: nach MAX_RUNDEN ist Schluss -------------------------
    alt_max = P.MAX_RUNDEN
    P.MAX_RUNDEN = 3
    try:
        D.anfragen.clear()
        D.drehbuch[:] = [(200, aufruf_antwort("get_document_info", {}, "c%d" % i))
                         for i in range(10)]
        chat, protokoll = neuer_chat("alles_auto", "kreisel")
        C.senden(chat, "los")
        warte(lambda: "schluss" in arten(chat))
        pruefe("A11 nach MAX_RUNDEN abgebrochen, mit Hinweis",
               len(D.posts()) == 3 and any(
                   "Runden abgebrochen" in e.get("text", "")
                   for e in chat["ereignisse"]), len(D.posts()))
        C.beenden(chat)
    finally:
        P.MAX_RUNDEN = alt_max
        D.drehbuch.clear()

    # --- 12. Der Server-Befehl kommt aus dem Chat-Modul --------------------
    py_ordner = os.path.join(t, "py")
    os.makedirs(os.path.join(py_ordner, "Lib", "site-packages",
                             "open_mcp_cad-0.1.0.dist-info"))
    for exe in ("python.exe", "pythonw.exe"):
        open(os.path.join(py_ordner, exe), "w").close()
    alt = os.environ.get("OPEN_MCP_CAD_PYTHON")
    os.environ["OPEN_MCP_CAD_PYTHON"] = os.path.join(py_ordner, "python.exe")
    try:
        befehl, umgebung = C.server_befehl(53130, "Seeblick.3d")
        pruefe("A12 server_befehl: pythonw -m open_mcp_cad.server, Port, Riegel",
               befehl == [os.path.join(py_ordner, "pythonw.exe"), "-m",
                          "open_mcp_cad.server"]
               and umgebung.get("OPEN_MCP_CAD_PORT") == "53130"
               and umgebung.get("OPEN_MCP_CAD_EXPECT_DOC") == "Seeblick.3d",
               (befehl, umgebung))
        pruefe("A12 KONTROLLE: ohne Dokument kein Riegel",
               "OPEN_MCP_CAD_EXPECT_DOC" not in C.server_befehl(53130)[1])
    finally:
        if alt is None:
            os.environ.pop("OPEN_MCP_CAD_PYTHON", None)
        else:
            os.environ["OPEN_MCP_CAD_PYTHON"] = alt

    # --- 13. Einstellungen ohne Schluessel --------------------------------
    os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = os.path.join(t, "e", "chat.json")
    try:
        pruefe("A13 KONTROLLE: ohne Datei leer", P.einstellungen_lesen() == {})
        P.einstellungen_schreiben({"anbieter": "ollama",
                                   "modell": {"ollama": "qwen3"}})
        pruefe("A13 Einstellungen ueberleben",
               P.einstellungen_lesen().get("modell") == {"ollama": "qwen3"})
        einstellungen_robust(P, os.path.join(t, "e"))
    finally:
        os.environ.pop("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN", None)

    # --- 15. Der ECHTE Server: Handshake und ein lokales Werkzeug ----------
    # Nur, wo ein Server-Python mit open_mcp_cad liegt. Port ausserhalb des
    # Cadwork-Bereichs; get_cadwork_api_help fasst die Bridge nicht an.
    echt = C.server_befehl(53911)
    if echt is None:
        print("  (A15 uebersprungen: kein Server-Python mit open_mcp_cad)")
    else:
        klient = P.McpKlient(*echt)
        try:
            namen = sorted(w["name"] for w in klient.starten())
            # Die Soll-Liste kommt aus der QUELLE (jede mit @mcp.tool
            # dekorierte Funktion in server.py), nicht aus einer Zahl hier:
            # bis 2026-09-25 stand "15", und jedes neue Werkzeug machte das
            # Gate rot, ohne dass etwas kaputt war.
            with io.open(os.path.join(REPO, "open_mcp_cad", "server.py"),
                         encoding="utf-8") as fh:
                baum = ast.parse(fh.read())
            soll = sorted(
                f.name for f in baum.body if isinstance(f, ast.FunctionDef)
                and any("mcp.tool" in ast.unparse(d) for d in f.decorator_list))
            pruefe("A15 echter Server: Handshake, alle %d Werkzeuge aus "
                   "server.py" % len(soll),
                   namen == soll and "execute_cadwork_command" in soll
                   and "wait_for_bridge" in soll, (namen, soll))
            text, ist_fehler = klient.werkzeug("get_cadwork_api_help", {})
            pruefe("A15 echter Server: get_cadwork_api_help antwortet",
                   not ist_fehler and len(text) > 50, text[:80])
        except P.AnbieterFehler as exc:
            pruefe("A15 echter Server", False, str(exc)[:160])
        finally:
            klient.beenden()

    # --- 16. Codex ueber den App-Server (Attrappe) --------------------------
    codex_zellen(P, C, t, warte, arten)

    # --- 14. Die Abkuerzung, die das Gate abschaltet, gibt es hier nicht ----
    quelle = io.open(os.path.join(A, "omcad_a_anbieter.py"), encoding="utf-8").read()
    # Dazu die Codex-Gegenstuecke: der Schalter, der Freigaben UND Sandbox
    # abschaltet, und der automatische Pruefer statt des Nutzers.
    for verboten in ("dangerously-skip-permissions", "bypassPermissions",
                     "dangerouslySkipPermissions", "dangerously-bypass",
                     "approve-for-me", "auto_review", "guardian_subagent"):
        pruefe("A14 %r kommt nicht vor" % verboten, verboten not in quelle)

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
