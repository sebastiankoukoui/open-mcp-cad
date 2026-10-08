#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer open_mcp_cad/auftraege.py und die Antwort-Zeitgrenze im Client.

Anlass (Probelauf 2026-09-25, Stabschale mit 286 Staeben und 2288 Achsen):
  * Ein Auftrag lief in Cadwork 10,7 s und GELANG; der Agent bekam "nicht
    erreichbar, Plugin klicken". Jetzt: `AntwortFehlt` im Client,
    error="antwort_fehlt" im Server, und eine Zeitgrenze je Aufruf.
  * Grosse Mengen musste der Agent als Code-Text ausschreiben. Jetzt:
    `paketlauf` liest eine JSON-Liste und schickt den Code paketweise.

Prueft VERHALTEN: echte Sockets auf ephemeren Ports AUSSERHALB 53127..53199
(der Bereich kommt aus dem Kern-Quelltext), der Paketcode wird wirklich
ausgefuehrt (gegen eine Attrappe statt Cadwork). Zu jeder Ablehnung steht
derselbe Aufbau ohne den Fehler, der dann gelingt (Arbeitsregel 2).

Die Werkzeuge im Server (undo/redo, timeout_s, Paketlauf) werden nur
geprueft, wenn `mcp` da ist — sonst steht das ausdruecklich da.

    python tests/test_auftraege.py
    <Server-Python mit mcp> tests/test_auftraege.py
"""

import ast
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from open_mcp_cad import auftraege as A          # noqa: E402
from open_mcp_cad import bridge_client as BC     # noqa: E402

KERN = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    zeichen = "ok  " if bedingung else "FEHL"
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % (zeichen, titel,
                               ("  — %s" % (detail,)) if detail else ""))
    return bool(bedingung)


def _kern_konstanten(*namen):
    """Konstanten aus dem Kern-QUELLTEXT — keine eigene Liste (Regel 3)."""
    with io.open(KERN, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    return {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
            if isinstance(k, ast.Assign) and len(k.targets) == 1
            and isinstance(k.targets[0], ast.Name)
            and k.targets[0].id in namen}


def _kern_modul():
    """Der Kern selbst (nur Standardbibliothek beim Laden), fuer Funktionen,
    deren Verhalten ein Gate braucht — z. B. wie er `paketlauf` liest."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("omcad_kern_auftraege_gate",
                                                  KERN)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


_K = _kern_konstanten("PORT_VON", "PORT_BIS", "MAX_CODE_LENGTH")
_CADWORK_PORTS = set(range(_K["PORT_VON"], _K["PORT_BIS"] + 1))


def _ephemerer_socket():
    """Ein Socket auf einem ephemeren Port AUSSERHALB des Cadwork-Bereichs."""
    for _ in range(200):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        if s.getsockname()[1] not in _CADWORK_PORTS:
            return s
        s.close()
    raise RuntimeError("kein ephemerer Port ausserhalb des Cadwork-Bereichs")


class _Gegenstelle:
    """Eine echte TCP-Gegenstelle, die eine Zeile liest und dann je nach
    `art` antwortet ("antwort"), schweigt ("schweigen") oder auflegt
    ("auflegen")."""

    def __init__(self, art):
        self.art = art
        self.sock = _ephemerer_socket()
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.zeilen = []
        self.halten = []
        threading.Thread(target=self._dienen, daemon=True).start()

    def _dienen(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            daten = b""
            while b"\n" not in daten:
                stueck = conn.recv(65536)
                if not stueck:
                    break
                daten += stueck
            self.zeilen.append(daten)
            if self.art == "antwort":
                conn.sendall(b'{"id": 1, "ok": true, "result": 42}\n')
                conn.close()
            elif self.art == "auflegen":
                conn.close()
            else:
                self.halten.append(conn)          # offen, aber stumm

    def zu(self):
        for c in self.halten:
            c.close()
        self.sock.close()


def _freier_port():
    """Ein Port ausserhalb des Cadwork-Bereichs, auf dem NIEMAND lauscht."""
    s = _ephemerer_socket()
    port = s.getsockname()[1]
    s.close()
    return port


# --- 1. Client: gesendet ohne Antwort ist etwas anderes als unerreichbar ----

def teil_client():
    alt = BC.BRIDGE_TIMEOUT_SECONDS
    try:
        g = _Gegenstelle("schweigen")
        BC.BRIDGE_TIMEOUT_SECONDS = 30.0
        t = time.monotonic()
        try:
            BC.call("execute_cwapi3d", {"code": "result=1"}, port=g.port,
                    antwort_timeout=0.4)
            exc = None
        except BC.BridgeUnreachable as e:
            exc = e
        dauer = time.monotonic() - t
        pruefe("C1 stumme Gegenstelle -> AntwortFehlt", isinstance(
            exc, BC.AntwortFehlt), repr(exc))
        pruefe("C1 antwort_timeout gilt fuer DIESEN Aufruf (0,4 s statt der "
               "Vorgabe 30 s)", dauer < 5 and getattr(exc, "gewartet_s", 0)
               == 0.4, "%.2f s" % dauer)
        pruefe("C1 der Auftrag ist wirklich angekommen",
               len(g.zeilen) == 1 and b"execute_cwapi3d" in g.zeilen[0],
               g.zeilen[:1])
        pruefe("C1 AntwortFehlt bleibt ein BridgeUnreachable (alte Aufrufer "
               "fangen weiter)", isinstance(exc, BC.BridgeUnreachable))
        g.zu()

        BC.BRIDGE_TIMEOUT_SECONDS = 0.4
        g = _Gegenstelle("schweigen")
        t = time.monotonic()
        try:
            BC.call("ping", port=g.port)
            exc = None
        except BC.BridgeUnreachable as e:
            exc = e
        pruefe("C2 ohne antwort_timeout gilt CADWORK_BRIDGE_TIMEOUT",
               isinstance(exc, BC.AntwortFehlt)
               and time.monotonic() - t < 5
               and exc.gewartet_s == 0.4, repr(exc))
        g.zu()
        BC.BRIDGE_TIMEOUT_SECONDS = 30.0

        g = _Gegenstelle("auflegen")
        try:
            BC.call("ping", port=g.port, antwort_timeout=5)
            exc = None
        except BC.BridgeUnreachable as e:
            exc = e
        pruefe("C3 Auflegen NACH dem Senden -> AntwortFehlt (Ausgang offen)",
               isinstance(exc, BC.AntwortFehlt), repr(exc))
        g.zu()

        port = _freier_port()
        try:
            BC.call("ping", port=port, antwort_timeout=5)
            exc = None
        except BC.BridgeUnreachable as e:
            exc = e
        pruefe("C4 niemand lauscht -> BridgeUnreachable, aber KEIN "
               "AntwortFehlt (nichts gesendet)",
               isinstance(exc, BC.BridgeUnreachable)
               and not isinstance(exc, BC.AntwortFehlt), repr(exc))

        g = _Gegenstelle("antwort")
        try:
            wert = BC.call("ping", port=g.port, antwort_timeout=5)
        except Exception as e:                            # noqa: BLE001
            wert = e
        pruefe("C1-K dieselbe Gegenstelle MIT Antwort -> kein Fehler",
               wert == 42, repr(wert))
        g.zu()
    finally:
        BC.BRIDGE_TIMEOUT_SECONDS = alt


# --- 2. Fehlerantwort: drei Faelle, drei Codes -----------------------------

def teil_fehlerantwort():
    f = A.fehler_antwort(BC.AntwortFehlt("x", 12.0))
    pruefe("F1 AntwortFehlt -> error antwort_fehlt, sagt NICHT wiederholen",
           f["error"] == "antwort_fehlt" and "NICHT wiederholen"
           in f["message"] and f["gewartet_s"] == 12.0, f)
    pruefe("F1 und schickt NICHT zum Plugin-Klick",
           "Plugin" not in f["message"], f["message"])
    f = A.fehler_antwort(BC.BridgeUnreachable("weg"))
    pruefe("F1-K nicht erreichbar -> bridge_unreachable (Plugin klicken)",
           f["error"] == "bridge_unreachable" and "Plugin" in f["message"], f)
    f = A.fehler_antwort(BC.InstanzUnklar("zwei offen.", [
        {"instanz": "A", "port": 1, "dokument": "Seeblick.3d"},
        {"instanz": "B", "port": 2, "dokument": "Seeblick.3d"}]))
    pruefe("F2 InstanzUnklar -> instanz_waehlen mit Liste",
           f["error"] == "instanz_waehlen" and len(f["instanzen"]) == 2, f)

    pruefe("F3 wartezeit: 0 -> Vorgabe", A.wartezeit(0, 10) == 10.0)
    pruefe("F3 wartezeit: angegeben -> angegeben", A.wartezeit(45, 10) == 45.0)
    pruefe("F3 wartezeit: begrenzt auf TIMEOUT_MAX_S",
           A.wartezeit(10 ** 7, 10) == A.TIMEOUT_MAX_S)
    pruefe("F3 wartezeit: Unsinn -> Vorgabe", A.wartezeit("x", 10) == 10.0)


# --- 3. Paketlauf ---------------------------------------------------------

class _Cadwork:
    """Attrappe fuer `bridge_client.call`: fuehrt den Paketcode WIRKLICH aus
    (ohne cwapi3d) und merkt sich jeden Aufruf. `fehler` = {paket_nr: exc}."""

    def __init__(self, fehler=None, nachgezogen=None):
        self.aufrufe = []
        self.fehler = fehler or {}
        # Wie ein Kern ab 2.18 in 'Auto': je Paket {"elemente", "s"}.
        self.nachgezogen = nachgezogen

    def __call__(self, methode, params, antwort_timeout=None):
        self.aufrufe.append((methode, dict(params), antwort_timeout))
        nr = len(self.aufrufe)
        if nr in self.fehler:
            raise self.fehler[nr]
        ns = {}
        exec(compile(params["code"], "<paket>", "exec"), ns)
        antwort = {"result": ns.get("result")}
        if self.nachgezogen:
            antwort["paket_nachgezogen"] = dict(self.nachgezogen)
        return antwort


def _datei(t, name, inhalt, roh=False):
    pfad = os.path.join(t, name)
    with io.open(pfad, "w", encoding="utf-8") as fh:
        fh.write(inhalt if roh else json.dumps(inhalt, ensure_ascii=False))
    return pfad


CODE = "result = [paket_nr, pakete, paket_start, [e['n'] for e in paket]]\n"


def teil_paketlauf(t):
    daten = [{"n": i, "name": "Stütze %d" % i} for i in range(7)]
    pfad = _datei(t, "sieben.json", daten)

    cw = _Cadwork()
    erg = A.paketlauf(CODE, pfad, 3, "Probe", rufen=cw)
    pruefe("P1 7 Eintraege, Pakete zu 3 -> 3 Pakete, alles ok",
           erg.get("ok") and erg["pakete"] == 3 and erg["eintraege"] == 7
           and erg["undo_schritte"] == 3, erg)
    pruefe("P1 der Code sieht paket, paket_nr, pakete, paket_start richtig",
           erg.get("ergebnisse") == [[1, 3, 0, [0, 1, 2]],
                                     [2, 3, 3, [3, 4, 5]],
                                     [3, 3, 6, [6]]], erg.get("ergebnisse"))
    p = [a[1] for a in cw.aufrufe]
    pruefe("P2 Fortschritt fuer das Dock: bauteile je Paket, lauf_gesamt",
           [x.get("bauteile") for x in p] == [3, 3, 1]
           and all(x.get("lauf_gesamt") == 7 for x in p), p and p[-1].get("bauteile"))
    pruefe("P2 Beschreibung traegt (Paket k/n), Zugriff ist Schreiben",
           p[1]["description"] == "Probe (Paket 2/3)"
           and all(x["access_mode"] == "write" for x in p),
           p[1]["description"])
    pruefe("P2 ohne Riegel geht kein expect_document mit",
           all("expect_document" not in x for x in p))
    pruefe("P2 Vorgabe-Wartezeit je Paket ist PAKET_TIMEOUT_VORGABE_S",
           all(a[2] == max(A.PAKET_TIMEOUT_VORGABE_S,
                           BC.BRIDGE_TIMEOUT_SECONDS) for a in cw.aufrufe),
           [a[2] for a in cw.aufrufe])

    cw = _Cadwork()
    code = "result = [e['name'] for e in paket]\n"
    erg = A.paketlauf(code, pfad, 10, erwartet="Seeblick.3d", timeout_s=33,
                      rufen=cw)
    pruefe("P3 Umlaute kommen unveraendert im Code an",
           erg.get("ergebnisse") == [[d["name"] for d in daten]],
           erg.get("ergebnisse"))
    pruefe("P3 Riegel geht als expect_document an JEDES Paket, timeout_s gilt",
           cw.aufrufe[0][1].get("expect_document") == "Seeblick.3d"
           and cw.aufrufe[0][2] == 33.0, cw.aufrufe[0][1:])

    # Fehler mitten im Lauf: aufhoeren, sagen was fertig ist.
    cw = _Cadwork({2: BC.BridgeError("ZeroDivisionError", "kaputt")})
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P4 Fehler in Paket 2 -> Lauf hoert auf, Paket 3 NIE gesendet",
           not erg.get("ok") and len(cw.aufrufe) == 2
           and erg["pakete_fertig"] == 1 and erg["abgebrochen_bei_paket"] == 2
           and erg["eintraege_fertig"] == 3, erg)
    pruefe("P4 sagt, dass Paket 2 teils gelaufen sein kann (undo)",
           "undo(1)" in erg["hinweis"] and erg["error"] == "ZeroDivisionError",
           erg.get("hinweis"))
    pruefe("P4 liefert die Ergebnisse der fertigen Pakete",
           erg["ergebnisse"] == [[1, 3, 0, [0, 1, 2]]], erg["ergebnisse"])
    cw = _Cadwork({2: BC.AntwortFehlt("still", 120.0)})
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P5 Antwort fehlt in Paket 2 -> antwort_fehlt, NICHT wiederholen",
           erg.get("error") == "antwort_fehlt" and len(cw.aufrufe) == 2
           and "NICHT wiederholen" in erg["hinweis"], erg.get("hinweis"))
    cw = _Cadwork({1: BC.BridgeUnreachable("weg")})
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P6 nicht erreichbar in Paket 1 -> nichts fertig, NICHT ausgefuehrt",
           erg.get("error") == "bridge_unreachable"
           and erg["pakete_fertig"] == 0
           and "NICHT ausgefuehrt" in erg["hinweis"], erg.get("hinweis"))
    cw = _Cadwork()
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P4-K derselbe Lauf ohne Fehler -> alle 3 Pakete gesendet",
           erg.get("ok") and len(cw.aufrufe) == 3, erg)

    # P10 — das Feld `paketlauf` (Film 2026-09-25: in 'Auto' verschwanden die
    # Schrauben jedes Pakets bis zum Ende des Laufs). Ab Kern 2.18 zieht der
    # Kern ein Paket sofort nach — aber nur, wenn er es als Paket ERKENNT.
    felder = [a[1].get("paketlauf") for a in cw.aufrufe]
    pruefe("P10 jedes Paket traegt paketlauf {paket: k, pakete: n}",
           felder == [{"paket": k, "pakete": 3} for k in (1, 2, 3)], felder)
    kern = _kern_modul()
    pruefe("P10 der Kern liest daraus Paket k von n (seine eigene Funktion)",
           [kern.paket_von(a[1]) for a in cw.aufrufe]
           == [(1, 3), (2, 3), (3, 3)],
           [kern.paket_von(a[1]) for a in cw.aufrufe])
    ohne = [dict(a[1]) for a in cw.aufrufe]
    for o in ohne:
        o.pop("paketlauf", None)
    pruefe("P10-K ohne das Feld ist es fuer den Kern ein Einzelauftrag — die "
           "Beschreibung '(Paket k/n)' allein entscheidet nichts",
           all(kern.paket_von(o) is None for o in ohne)
           and all("(Paket " in o["description"] for o in ohne),
           [o["description"] for o in ohne])

    # P11 — was das Nachziehen gekostet hat, gemessen in Cadwork.
    cw = _Cadwork(nachgezogen={"elemente": 3, "s": 0.25})
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P11 meldet der Kern je Paket sein Nachziehen, nennt der Lauf die "
           "Summe", erg.get("nachgezogen") == {"pakete": 3, "elemente": 9,
                                                "s": 0.75},
           erg.get("nachgezogen"))
    cw = _Cadwork(nachgezogen={"elemente": 3, "s": 0.25},
                  fehler={3: BC.BridgeError("X", "kaputt")})
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P11 auch im Abbruch steht, was bis dahin nachgezogen wurde",
           not erg.get("ok") and erg.get("nachgezogen")
           == {"pakete": 2, "elemente": 6, "s": 0.5}, erg.get("nachgezogen"))
    cw = _Cadwork()
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P11-K ohne Meldung (aelterer Kern, 'Langsam', 'Schnell'): keine "
           "erfundene Null in der Antwort", erg.get("ok")
           and "nachgezogen" not in erg, sorted(erg))

    # Zu grosse Pakete: abweisen, BEVOR das erste gesendet ist.
    gross = _datei(t, "gross.json", ["x" * 30000 for _ in range(6)])
    cw = _Cadwork()
    erg = A.paketlauf("result = len(paket)\n", gross, 6, rufen=cw)
    pruefe("P7 Paket ueber der Code-Grenze -> abgewiesen, NICHTS gesendet",
           erg.get("error") == "package_too_large" and cw.aufrufe == [], erg)
    cw = _Cadwork()
    erg = A.paketlauf("result = len(paket)\n", gross, 2, rufen=cw)
    pruefe("P7-K dieselben Daten in kleineren Paketen -> laeuft",
           erg.get("ok") and erg["ergebnisse"] == [2, 2, 2], erg)
    pruefe("P7 die Code-Grenze ist die des Kerns (Quelle, keine Liste)",
           A.MAX_CODE == _K["MAX_CODE_LENGTH"],
           "%s / %s" % (A.MAX_CODE, _K["MAX_CODE_LENGTH"]))

    # Datendatei: jede Ablehnung mit Kontrolle.
    faelle = [
        ("P8 relativer Pfad", "sieben.json", "path_not_absolute"),
        ("P8 falsche Endung", _datei(t, "x.txt", daten), "wrong_extension"),
        ("P8 Datei fehlt", os.path.join(t, "fehlt.json"), "file_missing"),
        ("P8 kein JSON", _datei(t, "kaputt.json", "{nein", roh=True),
         "bad_json"),
        ("P8 keine Liste", _datei(t, "objekt.json", {"a": 1}), "not_a_list"),
        ("P8 leere Liste", _datei(t, "leer.json", []), "empty"),
    ]
    for titel, pf, code in faelle:
        cw = _Cadwork()
        erg = A.paketlauf(CODE, pf, 3, rufen=cw)
        pruefe("%s -> %s, nichts gesendet" % (titel, code),
               erg.get("error") == code and cw.aufrufe == [], erg)
    cw = _Cadwork()
    erg = A.paketlauf(CODE, pfad, 3, rufen=cw)
    pruefe("P8-K gueltige Datei -> laeuft", erg.get("ok"), erg)
    for titel, gr in (("0", 0), ("-1", -1), ("x", "x")):
        cw = _Cadwork()
        erg = A.paketlauf(CODE, pfad, gr, rufen=cw)
        pruefe("P9 paket_groesse %s -> bad_package_size" % titel,
               erg.get("error") == "bad_package_size" and cw.aufrufe == [],
               erg)
    cw = _Cadwork()
    erg = A.paketlauf("  ", pfad, 3, rufen=cw)
    pruefe("P9 leerer Code -> code_missing",
           erg.get("error") == "code_missing" and cw.aufrufe == [], erg)


# --- 4. Server-Werkzeuge (nur mit mcp) ------------------------------------

class _Bridge:
    """Attrappe fuer bridge_client.call im Server: Dokumentname + Protokoll."""

    def __init__(self, dokument="Seeblick.3d", fehler=None):
        self.dokument = dokument
        self.aufrufe = []
        self.fehler = fehler

    def __call__(self, methode, params=None, request_id=1, *, port=None,
                 antwort_timeout=None):
        self.aufrufe.append((methode, dict(params or {}), antwort_timeout))
        if methode == "get_document_info":
            return {"document_name": self.dokument}
        if self.fehler:
            raise self.fehler
        if methode in ("undo", "redo"):
            return {"schritte": params["schritte"]}
        if methode == "execute_cwapi3d":
            ns = {}
            exec(compile(params["code"], "<x>", "exec"), ns)
            return {"result": ns.get("result")}
        return {}

    def methoden(self):
        return [a[0] for a in self.aufrufe]


def teil_server(t):
    try:
        import mcp                                         # noqa: F401
    except ImportError:
        print("  (Server-Werkzeuge NICHT geprueft: `mcp` fehlt in diesem "
              "Python. Mit dem Env, das `mcp` hat, erneut laufen lassen.)")
        return
    from open_mcp_cad import server as S
    alt = (S.bridge_client.call, S.EXPECT_DOC)
    # Der Server haelt Erfahrungen aus Fehlern fest (erfahrungen.py): nie in
    # die echte Datei des Nutzers.
    alt_erf = os.environ.get("OPEN_MCP_CAD_ERFAHRUNGEN")
    os.environ["OPEN_MCP_CAD_ERFAHRUNGEN"] = os.path.join(t, "erfahrungen.jsonl")
    try:
        S.EXPECT_DOC = "Seeblick.3d"
        b = _Bridge()
        S.bridge_client.call = b
        erg = S.undo(0)
        pruefe("S1 undo(0) -> bad_value, nichts gesendet",
               erg.get("error") == "bad_value" and b.aufrufe == [], erg)
        erg = S.undo(11)
        pruefe("S1 undo(11) -> bad_value, nichts gesendet",
               erg.get("error") == "bad_value" and b.aufrufe == [], erg)
        erg = S.undo(2)
        pruefe("S2 undo(2) prueft erst das Dokument, dann Cadworks undo",
               erg.get("ok") and b.methoden() == ["get_document_info", "undo"]
               and b.aufrufe[1][1].get("schritte") == 2
               and b.aufrufe[1][1].get("expect_document") == "Seeblick.3d",
               b.aufrufe)
        b = _Bridge(dokument="Anderes.3d")
        S.bridge_client.call = b
        erg = S.undo(1)
        pruefe("S2 falsches Dokument -> wrong_document, undo NIE gesendet",
               erg.get("error") == "wrong_document"
               and "undo" not in b.methoden(), erg)
        b = _Bridge()
        S.bridge_client.call = b
        erg = S.redo(1)
        pruefe("S2-K richtiges Dokument -> redo wird gesendet",
               erg.get("ok") and "redo" in b.methoden(), b.aufrufe)

        b = _Bridge()
        S.bridge_client.call = b
        S.execute_cadwork_command("result = 1", "x", timeout_s=45)
        pruefe("S3 execute_cadwork_command(timeout_s=45) wartet 45 s",
               b.aufrufe[-1][2] == 45.0, b.aufrufe[-1][2])
        S.execute_cadwork_command("result = 1", "x")
        pruefe("S3-K ohne timeout_s -> Vorgabe CADWORK_BRIDGE_TIMEOUT",
               b.aufrufe[-1][2] == S.bridge_client.BRIDGE_TIMEOUT_SECONDS,
               b.aufrufe[-1][2])
        b = _Bridge(fehler=BC.AntwortFehlt("still", 10.0))
        S.bridge_client.call = b
        erg = S.execute_cadwork_command("result = 1", "x")
        pruefe("S4 Antwort fehlt -> antwort_fehlt statt 'nicht erreichbar'",
               erg.get("error") == "antwort_fehlt", erg)

        pfad = _datei(t, "server.json", [{"n": i} for i in range(5)])
        b = _Bridge()
        S.bridge_client.call = b
        erg = S.execute_cadwork_batch(CODE, pfad, 2, "Probe")
        pruefe("S5 execute_cadwork_batch: Dokument pruefen, dann 3 Pakete",
               erg.get("ok") and b.methoden() == ["get_document_info"]
               + ["execute_cwapi3d"] * 3, b.methoden())
        pruefe("S8 execute_cadwork_batch: jedes Paket traegt das Feld "
               "paketlauf",
               [a[1].get("paketlauf") for a in b.aufrufe[1:]]
               == [{"paket": k, "pakete": 3} for k in (1, 2, 3)],
               [a[1].get("paketlauf") for a in b.aufrufe[1:]])
        b = _Bridge()
        S.bridge_client.call = b
        S.execute_cadwork_command("result = 1", "Einzelauftrag")
        pruefe("S8-K execute_cadwork_command (Einzelauftrag) traegt es NICHT "
               "— dort bleibt der Vorhang",
               b.aufrufe and b.aufrufe[-1][0] == "execute_cwapi3d"
               and "paketlauf" not in b.aufrufe[-1][1], b.aufrufe[-1:])
        b = _Bridge(dokument="Anderes.3d")
        S.bridge_client.call = b
        erg = S.execute_cadwork_batch(CODE, pfad, 2, "Probe")
        pruefe("S5 falsches Dokument -> kein einziges Paket gesendet",
               erg.get("error") == "wrong_document"
               and "execute_cwapi3d" not in b.methoden(), erg)

        # S7 redraw_view (Generalprobe 2026-09-25: Ansicht blieb nach dem
        # Zoom leer, erst das Neuzeichnen des Docks zeigte den Knoten).
        b = _Bridge()
        S.bridge_client.call = b
        erg = S.redraw_view()
        gesendet = [a for a in b.aufrufe if a[0] != "get_document_info"]
        pruefe("S7 redraw_view prueft erst das Dokument, dann 'neu_zeichnen'",
               erg.get("ok") and b.methoden() == ["get_document_info",
                                                  "neu_zeichnen"]
               and gesendet[0][1].get("expect_document") == "Seeblick.3d",
               b.aufrufe)
        b = _Bridge(dokument="Anderes.3d")
        S.bridge_client.call = b
        erg = S.redraw_view()
        pruefe("S7-K falsches Dokument -> wrong_document, nichts neu gezeichnet",
               erg.get("error") == "wrong_document"
               and "neu_zeichnen" not in b.methoden(), erg)
        kern = _kern_konstanten("MODELL_METHODEN", "METHODEN_ZUGRIFF")
        pruefe("S7 der Kern kennt 'neu_zeichnen' als Modell-Methode, nur lesend "
               "(aus dem Kern-Quelltext)",
               gesendet and gesendet[0][0] in kern["MODELL_METHODEN"]
               and kern["METHODEN_ZUGRIFF"].get(gesendet[0][0]) == "read",
               (gesendet[:1], kern.get("METHODEN_ZUGRIFF", {}).get("neu_zeichnen")))

        import asyncio
        namen = {w.name for w in asyncio.run(S.mcp.list_tools())}
        pruefe("S6 die neuen Werkzeuge sind registriert",
               {"execute_cadwork_batch", "undo", "redo", "redraw_view"} <= namen,
               sorted(namen))
    finally:
        S.bridge_client.call, S.EXPECT_DOC = alt
        if alt_erf is None:
            os.environ.pop("OPEN_MCP_CAD_ERFAHRUNGEN", None)
        else:
            os.environ["OPEN_MCP_CAD_ERFAHRUNGEN"] = alt_erf


# --- 5. Messskript "Nachziehen am Schneidwerkzeug" (Auftrag B) --------------
#
# Das Skript soll SPAETER in Cadwork laufen (nur mit Freigabe). Hier: sendet
# es ohne --ausfuehren nichts, und laeuft es mit --ausfuehren gegen eine
# cwapi3d-Attrappe so, wie es soll — und kann es die vermutete Wirkung
# ueberhaupt SEHEN? Dafuer spielt die Attrappe die Vermutung auf Wunsch nach.

class _Punkt:
    def __init__(self, x, y, z):
        self.k = [float(x), float(y), float(z)]

    def __getitem__(self, i):
        return self.k[i]


class _Uhr:
    """Falsche Zeit: `sleep` rueckt nur die Uhr vor (die Messung wartet
    bis zu 30 s je Variante)."""

    def __init__(self):
        self.jetzt = 1000.0

    def sleep(self, s):
        self.jetzt += max(0.0, float(s))

    def monotonic(self):
        return self.jetzt


class _MessCadwork:
    """So viel Cadwork, wie das Messskript braucht: Quader, Schnitte,
    Material, Gruppen, VBA mit Abschnitten.

    `wirkung=True` spielt die VERMUTUNG nach: wird das Material eines
    Werkzeugs neu gesetzt, das einen Stab bearbeitet (Blech nach dem
    Schnitt, VBA mit Bohrung), bekommen VBA in der naechsten Sekunde keine
    Abschnitte.

    `fremd_bei=k`: vor dem k-ten execute zeichnet JEMAND ANDERS im selben
    Modell — ein Bauteil in seiner eigenen Gruppe und eines ohne Gruppe
    (M7). Die Ids stehen danach in `fremd`.
    """

    def __init__(self, uhr, dokument="Seeblick_Messung.3d", modus="langsam",
                 wirkung=False, vba_material="Stahl", fremd_bei=None):
        self.uhr = uhr
        self.fremd_bei = fremd_bei
        self.fremd = {}
        self.executes = 0
        self.vba_material = vba_material   # "" = leere Achse ohne Material
        self.dokument = dokument
        self.modus = modus
        self.wirkung = wirkung
        self.el = {1: {"typ": "fremd", "min": [0, 0, 0], "max": [1, 1, 1],
                       "material": "", "gruppe": "Bestand", "schnitte": []}}
        self.naechste = 100
        self.material = {"Stahl": 7, "Holz": 3}
        self.gesetzt = []            # je set_element_material, s. unten
        self.dunkel_seit = None      # wann ein Werkzeug-Material neu kam
        self.werkzeuge = set()       # Bleche nach dem Schnitt, VBA
        self.aufrufe = []
        self.store = {}
        self.auffrischung = True
        self.lizenz_frei = 0

    # -- Bridge ----------------------------------------------------------
    def call(self, methode, params=None, request_id=1, *, port=None,
             antwort_timeout=None):
        params = dict(params or {})
        self.aufrufe.append((methode, params))
        if methode == "get_document_info":
            return {"document_name": self.dokument}
        if methode == "zeichenmodus":
            if params.get("modus"):
                self.modus = params["modus"]
            return {"zeichenmodus": self.modus}
        if methode == "release_write_lease":
            return {}
        assert methode == "execute_cwapi3d", methode
        # Ob jeder Auftrag den Riegel traegt, prueft M3 (nicht hier: ein
        # Abbruch in der Attrappe waere keine rote Zelle, sondern ein Absturz).
        self.executes += 1
        if self.executes == self.fremd_bei:
            for art, gruppe in (("gruppiert", "Nachbar_Wand"),
                                ("ohne_gruppe", "")):
                eid = self._neu("fremd", [5e5, 0, 0], [5e5 + 1, 1, 1])
                self.el[eid]["gruppe"] = gruppe
                self.fremd[art] = eid
        ns = self._namensraum()
        alt = sys.modules.get("connector_axis_controller")
        sys.modules["connector_axis_controller"] = ns["_ca"]
        try:
            exec(compile(params["code"], "<messung>", "exec"), ns)
        finally:
            if alt is None:
                sys.modules.pop("connector_axis_controller", None)
            else:
                sys.modules["connector_axis_controller"] = alt
        return {"result": ns.get("result")}

    def ziel_setzen(self, port):
        self.gebunden = port

    def release_write_lease(self):
        self.lizenz_frei += 1

    # -- cwapi3d ---------------------------------------------------------
    def _neu(self, typ, mn, mx):
        self.naechste += 1
        self.el[self.naechste] = {"typ": typ, "min": list(mn), "max": list(mx),
                                  "material": "", "gruppe": "",
                                  "schnitte": []}
        return self.naechste

    def _namensraum(self):
        import types
        M = self
        cadwork = types.SimpleNamespace(point_3d=_Punkt)
        ec, ac, gc, mc, uc, vc, ca = (types.SimpleNamespace()
                                      for _ in range(7))

        def balken(b, h, l, s, x, z):
            return M._neu("stab", [s[0], s[1] - b / 2, s[2] - h / 2],
                          [s[0] + l, s[1] + b / 2, s[2] + h / 2])

        def platte(b, t, l, s, x, z):          # absichtlich eckbasiert
            return M._neu("blech", [s[0], s[1], s[2]],
                          [s[0] + l, s[1] + t, s[2] + b])

        def ecken(eid):
            e = M.el[eid]
            return [_Punkt(x, y, z) for x in (e["min"][0], e["max"][0])
                    for y in (e["min"][1], e["max"][1])
                    for z in (e["min"][2], e["max"][2])]

        def schieben(ids, v):
            for i in ids:
                for k in range(3):
                    M.el[i]["min"][k] += v[k]
                    M.el[i]["max"][k] += v[k]

        def ueberlapp(a, b):
            return all(a["min"][k] < b["max"][k] and b["min"][k] < a["max"][k]
                       for k in range(3))

        def schneiden(harte, weiche, _undo):
            for w in weiche:
                for h in harte:
                    if ueberlapp(M.el[h], M.el[w]):
                        M.el[w]["schnitte"].append(h)
                        M.werkzeuge.add(h)
            return list(weiche)

        def volumen(eid):
            e = M.el[eid]
            v = 1.0
            for k in range(3):
                v *= e["max"][k] - e["min"][k]
            return v - 1.0 * len(e["schnitte"])

        def material_setzen(ids, mid):
            name = [n for n, i in M.material.items() if i == mid][0]
            # (ids, Material, hatten sie es schon = NEU gesetzt?)
            M.gesetzt.append((sorted(ids), name, all(
                M.el[i]["material"] == name for i in ids)))
            for i in ids:
                M.el[i]["material"] = name
            if any(i in M.werkzeuge for i in ids):
                M.dunkel_seit = M.uhr.monotonic()

        def vba(d_, p1, p2):
            x, z = p1[0], p1[2]
            y0, y1 = sorted((p1[1], p2[1]))
            n = 0
            for eid, e in M.el.items():
                if e["typ"] not in ("stab", "blech"):
                    continue
                if (e["min"][0] <= x <= e["max"][0]
                        and e["min"][2] <= z <= e["max"][2]
                        and y0 < e["max"][1] and e["min"][1] < y1):
                    quer = any(e2 for h in e["schnitte"]
                               for e2 in [M.el[h]]
                               if e2["min"][0] <= x <= e2["max"][0]
                               and e2["min"][2] <= z <= e2["max"][2])
                    n += 2 if quer else 1
            if (M.wirkung and M.dunkel_seit is not None
                    and M.uhr.monotonic() - M.dunkel_seit < 1.0):
                n = 0
            eid = M._neu("vba", [x, y0, z], [x, y1, z])
            M.el[eid]["abschnitte"] = n
            M.el[eid]["material"] = M.vba_material   # Katalog-VBA: "Stahl"
            M.werkzeuge.add(eid)
            return eid

        cadwork_fn = {
            "ec": {"create_rectangular_beam_vectors": balken,
                   "create_rectangular_panel_vectors": platte,
                   "move_element": schieben,
                   "subtract_elements_with_undo": schneiden,
                   "check_element_id": lambda e: e in M.el,
                   "get_all_identifiable_element_ids": lambda: list(M.el),
                   "delete_elements": lambda ids: [M.el.pop(i, None)
                                                   for i in ids]},
            "ac": {"set_element_material": material_setzen,
                   "get_element_material_name":
                       lambda e: M.el[e]["material"],
                   "set_group": lambda ids, g: [M.el[i].__setitem__(
                       "gruppe", g) for i in ids],
                   "get_group": lambda e: M.el[e]["gruppe"]},
            "gc": {"get_element_vertices": ecken,
                   "get_actual_physical_volume": volumen},
            "mc": {"get_material_id": lambda n: M.material.get(n, 0),
                   "get_name": lambda i: [n for n, j in M.material.items()
                                          if j == i][0]},
            "uc": {"enable_auto_display_refresh":
                       lambda: setattr(M, "auffrischung", True),
                   "disable_auto_display_refresh":
                       lambda: setattr(M, "auffrischung", False)},
            "vc": {"refresh": lambda: None},
            "ca": {"create_blank_connector": vba,
                   "create_standard_connector": lambda n, p1, p2: vba(0, p1,
                                                                      p2),
                   "get_section_count": lambda a: M.el[a]["abschnitte"],
                   "get_section_contact_element": lambda a, i: 0,
                   "check_axis": lambda a: M.el[a]["abschnitte"] > 0},
        }
        mods = dict(zip(("ec", "ac", "gc", "mc", "uc", "vc", "ca"),
                        (ec, ac, gc, mc, uc, vc, ca)))
        for kurz, fns in cadwork_fn.items():
            for n, f in fns.items():
                setattr(mods[kurz], n, f)
        ns = {"cadwork": cadwork, "_ca": ca,
              "store_as": lambda k, w: M.store.__setitem__(k, w),
              "get_stored": lambda k: M.store.get(k)}
        ns.update({k: v for k, v in mods.items() if k != "ca"})
        return ns


def _mess_modul():
    import importlib.util
    pfad = os.path.join(REPO, "scripts", "messung_nachziehen_schneidwerkzeug.py")
    spec = importlib.util.spec_from_file_location("omcad_messung_gate", pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _mess_lauf(M, cw, uhr, *zusatz):
    import types
    args = M.argumente(["--ausfuehren", "--port", "1", "--dokument",
                        "Seeblick_Messung", *zusatz])
    alt = M.time
    M.time = types.SimpleNamespace(sleep=uhr.sleep, monotonic=uhr.monotonic,
                                   time=time.time, strftime=time.strftime)
    try:
        return M.Lauf(args, cw).ausfuehren()
    finally:
        M.time = alt


def teil_messung():
    M = _mess_modul()
    ausgabe = io.StringIO()
    befunde = M.offline_pruefen(M.argumente([]), aus=lambda *a: None)
    pruefe("M1 Messskript offline: jeder Auftragscode kompiliert, Token-Sperre "
           "und Code-Grenze des Kerns (aus der Quelle) halten", befunde == [],
           befunde)
    alt_lesen = M.LESEN
    M.LESEN = "import os\n" + alt_lesen
    try:
        kontrolle = M.offline_pruefen(M.argumente([]), aus=lambda *a: None)
    finally:
        M.LESEN = alt_lesen
    pruefe("M1-K ein gesperrtes Token faellt der Offline-Pruefung auf",
           any("blockierte Tokens" in b for b in kontrolle), kontrolle)

    # Ohne --ausfuehren: kein einziger Aufruf an die Bridge.
    gesendet = []

    class _Draht(Exception):
        pass

    def draht(methode, *a, **kw):
        gesendet.append(methode)
        raise _Draht(methode)

    alt_call = BC.call
    BC.call = draht
    try:
        stdout, sys.stdout = sys.stdout, ausgabe
        try:
            try:
                rc = M.main([])
            except _Draht:
                rc = "gesendet"
        finally:
            sys.stdout = stdout
        pruefe("M2 ohne --ausfuehren: Rueckgabe 0, NICHTS gesendet",
               rc == 0 and gesendet == [] and "Nichts gesendet"
               in ausgabe.getvalue(), (rc, gesendet))
        try:
            stdout, sys.stdout = sys.stdout, io.StringIO()
            try:
                M.main(["--ausfuehren", "--port", str(_freier_port()),
                        "--dokument", "Seeblick"])
            finally:
                sys.stdout = stdout
        except _Draht:
            pass
        pruefe("M2-K mit --ausfuehren wird gesendet (der Stolperdraht loest "
               "aus), zuerst die Dokumentpruefung", gesendet[:1]
               == ["get_document_info"], gesendet)
    finally:
        BC.call = alt_call

    uhr = _Uhr()
    cw = _MessCadwork(uhr)
    erg = _mess_lauf(M, cw, uhr)
    v = {x["variante"]: x for x in erg["varianten"]}
    # Gemessen werden die VBA des letzten VBA-Schritts: je Stab 4 je Ende.
    soll = {w["name"]: 5 * 4 * len([s for s in w["schritte"]
                                    if s[0] == "vba"][-1][1])
            for w in M.VARIANTEN}
    ist = {k: sum(len(s["vba"]) for s in x["je_stab"]) for k, x in v.items()}
    pruefe("M3 alle Varianten des Skripts gelaufen, jeder Stab wirklich "
           "geschnitten, gemessen die VBA des letzten Schritts",
           len(v) == len(M.VARIANTEN) >= 8
           and all(x["geschnitten"] == 5 for x in v.values()) and ist == soll,
           (ist, soll))
    abschnitte = {w.get("abschnitte") for x in erg["varianten"]
                  for les in x["lesungen"] for w in les["vba"].values()}
    pruefe("M3 ohne die vermutete Wirkung: jede VBA Holz|Blech|Holz (3 "
           "Abschnitte), 6 Lesungen je Variante",
           abschnitte == {3} and all(len(x["lesungen"]) == 6
                                     for x in v.values()), abschnitte)
    neu = [len(ids) for ids, _n, schon in cw.gesetzt if schon]
    pruefe("M3 NEU gesetzt (Material auf den eigenen Wert) wird nur in den "
           "4 A-Varianten (je alle 10 Bleche) und in P0 (die 20 VBA des "
           "ersten Schritts); sonst nur beim Anlegen",
           neu == [10, 10, 10, 10, 20]
           and sum(1 for g in cw.gesetzt if not g[2]) == 5 * len(v),
           (neu, len(cw.gesetzt)))
    pruefe("M3 jedes execute traegt expect_document, der Modus blieb "
           "'langsam', die Lizenz ist freigegeben",
           all(p.get("expect_document") == "Seeblick_Messung"
               for m, p in cw.aufrufe if m == "execute_cwapi3d")
           and cw.modus == "langsam" and cw.lizenz_frei == 1)
    pruefe("M3 aufgeraeumt: nur der Bestand bleibt, er wird nicht angefasst",
           list(cw.el) == [1] and erg["aufraeumen"]["geloescht"] > 0,
           (list(cw.el)[:5], erg.get("aufraeumen")))
    def _null(e):
        """Je Variante: Staebe, deren VBA in der ersten Lesung ALLE 0
        Abschnitte haben (so sah der Befund aus)."""
        aus = {}
        for x in e["varianten"]:
            les = x["lesungen"][0]["vba"]
            aus[x["variante"]] = sum(
                1 for s in x["je_stab"]
                if all(les[str(a)]["abschnitte"] == 0 for a in s["vba"]))
        return aus

    null_ohne = _null(erg)

    # Die Vermutung nachgespielt: kann die Messung sie SEHEN?
    uhr2 = _Uhr()
    cw2 = _MessCadwork(uhr2, wirkung=True)
    erg2 = _mess_lauf(M, cw2, uhr2)
    null = _null(erg2)
    pruefe("M4 mit der Wirkung zeigt die Messung Staebe ohne Abschnitte "
           "genau in A_gleich, A0 und P0, nicht in K0, K10, A2, A10, PK",
           null == {"K0": 0, "K10": 0, "A_gleich": 5, "A0": 5, "A2": 0,
                    "A10": 0, "PK": 0, "P0": 5}, null)
    tabelle2 = io.StringIO()
    M.zusammenfassen(erg2, aus=lambda t: tabelle2.write(t + "\n"))
    pruefe("M4 und die Tabelle nennt sie (5/40 in A0)",
           any(z.startswith("A0 ") and " 5/40 " in z
               for z in tabelle2.getvalue().splitlines()),
           tabelle2.getvalue()[-300:])
    pruefe("M4-K ohne Wirkung (M3): in keiner Variante ein Stab ohne "
           "Abschnitte", null_ohne == {k: 0 for k in null}, null_ohne)

    # Leere Achsen ohne Material: dann setzt der Material-Schritt von P0
    # nichts — die Zeile P0 saehe aus wie "kein Risiko", ohne es zu messen.
    uhr6 = _Uhr()
    cw6 = _MessCadwork(uhr6, wirkung=True, vba_material="")
    erg6 = _mess_lauf(M, cw6, uhr6, "--nur", "P0")
    t6 = io.StringIO()
    M.zusammenfassen(erg6, aus=lambda t: t6.write(t + "\n"))
    pruefe("M6 findet ein Material-Schritt kein Material, sagt die "
           "Zusammenfassung, dass die Zeile nichts aussagt",
           _null(erg6) == {"P0": 0} and "HINWEIS P0" in t6.getvalue(),
           t6.getvalue()[-200:])
    pruefe("M6-K mit Material (M4) kein solcher Hinweis",
           "HINWEIS" not in tabelle2.getvalue(), tabelle2.getvalue()[-200:])

    # Falsches Dokument / falscher Modus: nichts wird geschrieben.
    for titel, cw3, zusatz in (
            ("M5 falsches Dokument", _MessCadwork(_Uhr(), dokument="X.3d"), ()),
            ("M5 Modus 'auto' ohne --modus-umstellen",
             _MessCadwork(_Uhr(), modus="auto"), ())):
        try:
            _mess_lauf(M, cw3, _Uhr(), *zusatz)
            abbruch = False
        except SystemExit:
            abbruch = True
        pruefe("%s -> Abbruch, kein einziges execute" % titel,
               abbruch and not [m for m, _p in cw3.aufrufe
                                if m == "execute_cwapi3d"],
               [m for m, _p in cw3.aufrufe])
    # Aufraeumen: weg kommt die eigene Gruppe und Neues OHNE Gruppe
    # (Restkoerper eines Schnitts). Neues MIT fremder Gruppe gehoert jemand
    # anderem — nur melden (Gegenpruefung 2026-09-26, Mutant X1: dieser
    # Schutz war ungeprueft, M3 kennt nur den Bestand von vorher).
    def _fremd_lauf(aufraeumen):
        alt_auf = M.AUFRAEUMEN
        M.AUFRAEUMEN = aufraeumen
        try:
            uhr7 = _Uhr()
            cw7 = _MessCadwork(uhr7, fremd_bei=3)
            erg7 = _mess_lauf(M, cw7, uhr7, "--nur", "K0")
        finally:
            M.AUFRAEUMEN = alt_auf
        return cw7, erg7.get("aufraeumen") or {}

    cw7, auf7 = _fremd_lauf(M.AUFRAEUMEN)
    g7, o7 = cw7.fremd.get("gruppiert"), cw7.fremd.get("ohne_gruppe")
    pruefe("M7 waehrend der Messung Gezeichnetes MIT fremder Gruppe bleibt "
           "und wird gemeldet; der Bestand bleibt; Neues ohne Gruppe "
           "(Restkoerper) ist weg",
           g7 is not None and sorted(cw7.el) == [1, g7]
           and auf7.get("fremd_nicht_geloescht") == [g7]
           and auf7.get("geloescht", 0) > 0 and o7 not in cw7.el,
           (sorted(cw7.el)[:6], cw7.fremd, auf7))
    schutzlos = M.AUFRAEUMEN.replace("(weg if not g else fremd).append(e)",
                                     "weg.append(e)")
    cw7k, auf7k = _fremd_lauf(schutzlos)
    pruefe("M7-K KONTROLLE: ohne den Schutz (alles Neue loeschen) ist das "
           "fremde Bauteil weg und nichts gemeldet — M7 saehe es",
           schutzlos != M.AUFRAEUMEN
           and cw7k.fremd.get("gruppiert") not in cw7k.el
           and not auf7k.get("fremd_nicht_geloescht"),
           (sorted(cw7k.el)[:6], auf7k))

    uhr4 = _Uhr()
    cw4 = _MessCadwork(uhr4, modus="auto")
    _mess_lauf(M, cw4, uhr4, "--modus-umstellen", "--nur", "K0")
    modi = [p.get("modus") for m, p in cw4.aufrufe if m == "zeichenmodus"]
    pruefe("M5-K mit --modus-umstellen: fuer die Messung 'langsam', danach "
           "wieder 'auto'", modi == [None, "langsam", "auto"]
           and cw4.modus == "auto"
           and any(m == "execute_cwapi3d" for m, _p in cw4.aufrufe), modi)


def main():
    print("Auftraege: Antwort-Zeitgrenze, Fehlerantwort, Paketlauf — Gate\n")
    teil_client()
    teil_fehlerantwort()
    with tempfile.TemporaryDirectory(prefix="omcad_auftr_") as t:
        teil_paketlauf(t)
        teil_server(t)
    teil_messung()
    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
