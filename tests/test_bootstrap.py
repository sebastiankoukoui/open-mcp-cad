#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer den Datei-Bootstrap (open_mcp_cad/bootstrap.py) und das Binden.

Prueft VERHALTEN mit temporaeren Dateien und Attrappen:
  * create_from_init: Quelle fehlt, falsche Endung, Ziel existiert,
    Quelle = Ziel, gueltige Kopie, kein Ueberschreiben — und mehr.
  * open_document: NUR mit ersetztem Starter.
  * warte_auf_bridge: gegen eine Registry- und Bridge-Attrappe.
  * bridge_client: `call(..., port=)` und `ziel_setzen` gegen einen echten
    Mini-Server auf einem EPHEMEREN Port; die Portwahl ohne jede Angabe
    und ueber OPEN_MCP_CAD_DOC gegen eine Temp-Registry.
  * die Registry-Leser: eine wiederverwendete PID oder ein beendeter
    Prozess zaehlt nicht als laufende Instanz (gegen ein echtes
    Python-Kind).
  * server.wait_for_bridge bindet — nur, wenn `mcp` da ist (im
    System-Python nicht; dann steht das ausdruecklich da).

⚠ CADWORK DARF HIER NIE STARTEN. Jede .3d, auch eine Attrappe, oeffnet
ueber die Dateiverknuepfung Cadwork. Deshalb sind `os.startfile` und
`subprocess.Popen` waehrend des ganzen Laufs durch Stolperdraehte ersetzt;
wer sie trotzdem erreicht, bekommt einen Fehler statt eines Cadwork.
Einzige Ausnahme: `_python_kind()` startet sys.executable (nie eine .3d)
am Draht vorbei, als fremden Prozess fuer die Registry-Leser.

Jede Pruefung hat eine Kontrolle, die das Gegenteil zeigt (Arbeitsregel 2):
zu jeder Ablehnung derselbe Aufbau ohne den Fehler, der dann gelingt.

    python tests/test_bootstrap.py
"""

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from open_mcp_cad import bootstrap as B          # noqa: E402
from open_mcp_cad import bridge_client as BC     # noqa: E402

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    zeichen = "ok  " if bedingung else "FEHL"
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % (zeichen, titel,
                               ("  — %s" % detail) if detail else ""))
    return bool(bedingung)


# --- Stolperdraehte -------------------------------------------------------

_ausgeloest = []


def _stolperdraht(name):
    def ausgeloest(*a, **kw):
        _ausgeloest.append((name, a))
        raise RuntimeError("STOLPERDRAHT %s — Test haette Cadwork gestartet"
                           % name)
    return ausgeloest


class _PopenDraht:
    """Wie `subprocess.Popen` eine KLASSE: `mcp` schreibt beim Import
    `subprocess.Popen[bytes]` — eine blosse Funktion bricht dort ab."""

    def __init__(self, *a, **kw):
        _ausgeloest.append(("subprocess.Popen", a))
        raise RuntimeError("STOLPERDRAHT subprocess.Popen — Test haette "
                           "Cadwork gestartet")

    def __class_getitem__(cls, _typ):
        return cls


_ECHT = {"startfile": getattr(os, "startfile", None),
         "Popen": subprocess.Popen}


def _draehte_spannen():
    os.startfile = _stolperdraht("os.startfile")
    subprocess.Popen = _PopenDraht


def _draehte_loesen():
    if _ECHT["startfile"] is not None:
        os.startfile = _ECHT["startfile"]
    subprocess.Popen = _ECHT["Popen"]


# --- Hilfen ---------------------------------------------------------------

INHALT = b"CADWORK-ATTRAPPE\x00\x01" * 4096     # 72 KB, kein echtes Format


def _datei(pfad, inhalt=INHALT):
    with open(pfad, "wb") as fh:
        fh.write(inhalt)
    return pfad


def _lies(pfad):
    with open(pfad, "rb") as fh:
        return fh.read()


def _code(erg):
    return erg.get("error") if not erg.get("ok") else "ok"


# --- create_from_init -----------------------------------------------------

def teil_create(t):
    init = _datei(os.path.join(t, "Vorlage.3d"))
    projekte = os.path.join(t, "projekte")
    os.makedirs(projekte)

    # C1 gueltige Kopie
    ziel = os.path.join(projekte, "Neu.3d")
    erg = B.create_from_init(init, ziel)
    pruefe("C1 gueltige Kopie gelingt", erg.get("ok"), erg)
    pruefe("C1 Kopie ist bytegleich, Quelle unveraendert",
           os.path.isfile(ziel) and _lies(ziel) == INHALT
           and _lies(init) == INHALT and erg.get("bytes") == len(INHALT))

    # C2 kein Ueberschreiben: derselbe Aufruf noch einmal
    _datei(ziel, b"vom Nutzer weitergearbeitet")
    erg = B.create_from_init(init, ziel)
    pruefe("C2 Ziel existiert -> target_exists", _code(erg) == "target_exists",
           erg)
    pruefe("C2 das vorhandene Ziel ist NICHT angefasst",
           _lies(ziel) == b"vom Nutzer weitergearbeitet")
    ziel2 = os.path.join(projekte, "Neu2.3d")
    pruefe("C2 KONTROLLE: ein freier Zielname gelingt",
           B.create_from_init(init, ziel2).get("ok"))

    # C3 Quelle fehlt
    ziel3 = os.path.join(projekte, "Neu3.3d")
    erg = B.create_from_init(os.path.join(t, "gibtsnicht.3d"), ziel3)
    pruefe("C3 Quelle fehlt -> source_missing, kein Ziel angelegt",
           _code(erg) == "source_missing" and not os.path.exists(ziel3), erg)
    pruefe("C3 KONTROLLE: mit vorhandener Quelle gelingt es",
           B.create_from_init(init, ziel3).get("ok"))

    # C4 falsche Endung — an Quelle UND Ziel
    txt = _datei(os.path.join(t, "Vorlage.txt"))
    ziel4 = os.path.join(projekte, "Neu4.3d")
    erg_q = B.create_from_init(txt, ziel4)
    erg_z = B.create_from_init(init, os.path.join(projekte, "Neu4.3dx"))
    pruefe("C4 falsche Endung der Quelle -> wrong_extension",
           _code(erg_q) == "wrong_extension" and not os.path.exists(ziel4),
           erg_q)
    pruefe("C4 falsche Endung des Ziels -> wrong_extension",
           _code(erg_z) == "wrong_extension"
           and not os.path.exists(os.path.join(projekte, "Neu4.3dx")), erg_z)
    pruefe("C4 KONTROLLE: Endung .3D (gross) gilt als .3d",
           B.create_from_init(init, os.path.join(projekte, "Gross.3D"))
           .get("ok"))

    # C5 Quelle = Ziel — auch in anderer Schreibweise
    erg = B.create_from_init(init, init)
    umweg = os.path.join(t, "projekte", "..", "VORLAGE.3d")
    erg2 = B.create_from_init(init, umweg)
    pruefe("C5 Quelle = Ziel -> same_file", _code(erg) == "same_file", erg)
    pruefe("C5 auch ueber '..' und Gross/Klein -> same_file",
           _code(erg2) == "same_file", erg2)
    pruefe("C5 die Quelle ist dabei unveraendert", _lies(init) == INHALT)

    # C6 relativer Pfad
    alt = os.getcwd()
    try:
        os.chdir(t)
        erg = B.create_from_init("Vorlage.3d",
                                 os.path.join(projekte, "Rel.3d"))
        erg2 = B.create_from_init(init, "Rel.3d")
    finally:
        os.chdir(alt)
    pruefe("C6 relative Quelle -> path_not_absolute",
           _code(erg) == "path_not_absolute", erg)
    pruefe("C6 relatives Ziel -> path_not_absolute, nichts angelegt",
           _code(erg2) == "path_not_absolute"
           and not os.path.exists(os.path.join(t, "Rel.3d")), erg2)
    pruefe("C6 ohne Laufwerk ('\\x.3d') -> path_not_absolute",
           _code(B.create_from_init(init, "\\Rel.3d")) == "path_not_absolute")

    # C7 leere Quelle: keine erfundene .3d
    leer = _datei(os.path.join(t, "Leer.3d"), b"")
    ziel7 = os.path.join(projekte, "Neu7.3d")
    erg = B.create_from_init(leer, ziel7)
    pruefe("C7 leere Quelle -> source_empty, nichts angelegt",
           _code(erg) == "source_empty" and not os.path.exists(ziel7), erg)

    # C8 Quelle ist ein Ordner mit .3d-Namen
    ordner = os.path.join(t, "Ordner.3d")
    os.makedirs(ordner)
    erg = B.create_from_init(ordner, os.path.join(projekte, "Neu8.3d"))
    pruefe("C8 Quelle ist ein Ordner -> source_not_file",
           _code(erg) == "source_not_file", erg)

    # C9 Zielordner fehlt: wird NICHT angelegt
    fehlt = os.path.join(t, "gibtsnicht", "Neu9.3d")
    erg = B.create_from_init(init, fehlt)
    pruefe("C9 Zielordner fehlt -> target_dir_missing, kein Ordner angelegt",
           _code(erg) == "target_dir_missing"
           and not os.path.exists(os.path.dirname(fehlt)), erg)

    # C10 das Rennen: das Ziel entsteht zwischen Pruefung und Anlegen
    ziel10 = os.path.join(projekte, "Rennen.3d")
    echt_lexists = os.path.lexists

    def lexists_und_dann_entsteht_es(p):
        vorher = echt_lexists(p)
        if os.path.normcase(p) == os.path.normcase(ziel10) and not vorher:
            _datei(ziel10, b"fremd")          # genau jetzt kommt ein anderer
        return vorher

    B.os.path.lexists = lexists_und_dann_entsteht_es
    try:
        erg = B.create_from_init(init, ziel10)
    finally:
        B.os.path.lexists = echt_lexists
    pruefe("C10 Ziel entsteht im Rennen -> target_exists, fremde Datei "
           "unangetastet",
           _code(erg) == "target_exists" and _lies(ziel10) == b"fremd", erg)


# --- open_document --------------------------------------------------------

def teil_open(t):
    datei = _datei(os.path.join(t, "Offen.3d"))
    gestartet = []
    frei = lambda: []                                    # noqa: E731

    erg = B.open_document(datei, starter=gestartet.append, laufende=frei)
    pruefe("O1 vorhandene Datei: der Starter bekommt GENAU diesen Pfad",
           erg.get("ok") and gestartet == [os.path.normpath(datei)],
           "%s / %s" % (erg, gestartet))

    gestartet.clear()
    for titel, pfad, code in (
            ("O2 Datei fehlt", os.path.join(t, "Fehlt.3d"), "target_missing"),
            ("O3 falsche Endung", _datei(os.path.join(t, "Offen.txt")),
             "wrong_extension"),
            ("O4 relativer Pfad", "Offen.3d", "path_not_absolute"),
            ("O5 leere Datei", _datei(os.path.join(t, "Leer2.3d"), b""),
             "target_empty")):
        erg = B.open_document(pfad, starter=gestartet.append, laufende=frei)
        pruefe("%s -> %s, NICHTS gestartet" % (titel, code),
               _code(erg) == code and gestartet == [], erg)

    # O6 gleicher Name schon verbunden -> Ablehnung
    belegt = lambda: [{"port": 53999, "dokument": "OFFEN.3d"}]  # noqa: E731
    erg = B.open_document(datei, starter=gestartet.append, laufende=belegt)
    pruefe("O6 gleicher Dateiname schon verbunden -> name_in_use, nichts "
           "gestartet", _code(erg) == "name_in_use" and gestartet == [], erg)
    anders = lambda: [{"port": 53999, "dokument": "Anders.3d"}]  # noqa: E731
    pruefe("O6 KONTROLLE: ein anderer Name stoert nicht",
           B.open_document(datei, starter=gestartet.append,
                           laufende=anders).get("ok"))

    # O7 der STANDARD-Weg ist os.startfile — gemessen gegen den
    # Stolperdraht, der ihn ersetzt. Ruft der Standard-Weg etwas anderes,
    # faengt der Popen-Draht es ab.
    _ausgeloest.clear()
    erg = B.open_document(datei, laufende=frei)
    pruefe("O7 ohne eigenen Starter geht es ueber os.startfile (Draht)",
           _ausgeloest and _ausgeloest[0][0] == "os.startfile"
           and _ausgeloest[0][1] == (os.path.normpath(datei),)
           and _code(erg) == "start_failed", "%s / %s" % (_ausgeloest, erg))


# --- warte_auf_bridge -----------------------------------------------------

class _Uhr:
    def __init__(self):
        self.t = 0.0
        self.schlaefe = 0

    def __call__(self):
        return self.t

    def schlafen(self, s):
        self.schlaefe += 1
        self.t += s


class _Bridge:
    """Attrappe: `rufen(methode, params, port)` wie bridge_client.call."""

    def __init__(self, antworten):
        self.antworten = antworten       # port -> dict oder Callable
        self.rufe = []

    def __call__(self, methode, params, port):
        self.rufe.append((methode, port, params.get("access_mode")))
        a = self.antworten[port]
        return a(methode) if callable(a) else a[methode]


def _warten(dokument, eintraege_folge, bridge, **kw):
    uhr = _Uhr()
    folge = list(eintraege_folge)

    def laufende():
        return folge.pop(0) if len(folge) > 1 else folge[0]

    erg = B.warte_auf_bridge(dokument, kw.pop("timeout_s", 10.0), 1.0,
                             laufende=laufende, rufen=bridge, uhr=uhr,
                             schlafen=uhr.schlafen, **kw)
    return erg, uhr


def teil_warten(t):
    pfad = os.path.join(t, "projekte", "Seeblick.3d")
    ordner = os.path.dirname(pfad)
    eintrag = {"port": 54001, "instanz": "Q", "dokument": "Seeblick.3d"}
    gut = _Bridge({54001: {
        "get_document_info": {"document_name": "Seeblick.3d", "port": 54001,
                              "instanz": "Q"},
        "execute_cwapi3d": {"result": pfad}}})

    # W1 erst leer, dann eingetragen ohne Namen, dann mit Namen
    erg, uhr = _warten(pfad, [[], [dict(eintrag, dokument="")], [eintrag]],
                       gut)
    pruefe("W1 wartet, bis die Datei eingetragen ist, und bestaetigt sie",
           erg.get("ok") and erg["port"] == 54001 and erg["ordner_geprueft"]
           and uhr.schlaefe == 2, "%s / %d Pausen" % (erg, uhr.schlaefe))
    pruefe("W1 geprueft wird ueber die Bridge, der Pfad nur LESEND",
           [m for m, _p, _a in gut.rufe] == ["get_document_info",
                                             "execute_cwapi3d"]
           and gut.rufe[1][2] == "read", gut.rufe)

    # W2 zwei Instanzen mit demselben Namen
    zwei = [eintrag, dict(eintrag, port=54002)]
    erg, _ = _warten(pfad, [zwei], gut)
    pruefe("W2 zwei Treffer -> ambiguous, keine Wahl",
           _code(erg) == "ambiguous" and len(erg.get("treffer", [])) == 2, erg)

    # W3 Zeitablauf
    erg, uhr = _warten(pfad, [[]], gut, timeout_s=5.0)
    pruefe("W3 nichts eingetragen -> timeout nach der Frist",
           _code(erg) == "timeout" and 5 <= uhr.t <= 6, "%s / t=%s"
           % (_code(erg), uhr.t))

    # W4 Teilstring zaehlt NICHT
    erg, _ = _warten(pfad, [[dict(eintrag, dokument="Seeblick_alt.3d")]], gut,
                     timeout_s=3.0)
    pruefe("W4 'Seeblick_alt.3d' ist nicht 'Seeblick.3d' -> timeout",
           _code(erg) == "timeout", erg)

    # W5 die Bridge meldet ein anderes Dokument als die Registry
    falsch = _Bridge({54001: {"get_document_info": {
        "document_name": "Andere.3d", "port": 54001}}})
    erg, _ = _warten(pfad, [[eintrag]], falsch, timeout_s=3.0)
    pruefe("W5 Bridge meldet anderes Dokument -> wird NICHT bestaetigt",
           _code(erg) == "timeout" and "Andere.3d" in erg["message"], erg)

    # W6 die Leitung meldet einen anderen Port
    # Pfad passend, damit NUR der Port die Ablehnung tragen kann.
    fremd = _Bridge({54001: {"get_document_info": {
        "document_name": "Seeblick.3d", "port": 54009},
        "execute_cwapi3d": {"result": pfad}}})
    erg, _ = _warten(pfad, [[eintrag]], fremd)
    pruefe("W6 fremder Port auf der Leitung -> port_mismatch",
           _code(erg) == "port_mismatch", erg)
    ohne = _Bridge({54001: {"get_document_info": {
        "document_name": "Seeblick.3d"}, "execute_cwapi3d": {"result": pfad}}})
    erg, _ = _warten(pfad, [[eintrag]], ohne)
    pruefe("W6 gar kein Port gemeldet -> port_mismatch",
           _code(erg) == "port_mismatch", erg)

    # W7 der Ordner — beide Lesarten von get_3d_file_path
    for titel, gemeldet, soll in (
            ("voller Pfad, gleich", pfad, "ok"),
            ("nur Ordner, gleich", ordner, "ok"),
            ("voller Pfad, anderer Ordner",
             os.path.join(t, "woanders", "Seeblick.3d"), "wrong_folder"),
            ("nur Ordner, anderer", os.path.join(t, "woanders"),
             "wrong_folder"),
            ("leer", "", "wrong_folder")):
        br = _Bridge({54001: {
            "get_document_info": {"document_name": "Seeblick.3d",
                                  "port": 54001},
            "execute_cwapi3d": {"result": gemeldet}}})
        erg, _ = _warten(pfad, [[eintrag]], br)
        pruefe("W7 Ordner %s -> %s" % (titel, soll), _code(erg) == soll, erg)

    # W8 nur der Dateiname: kein Ordner, und das steht im Ergebnis
    br = _Bridge({54001: {"get_document_info": {
        "document_name": "Seeblick.3d", "port": 54001}}})
    erg, _ = _warten("Seeblick.3d", [[eintrag]], br)
    pruefe("W8 nur Dateiname -> ok, aber ordner_geprueft=False",
           erg.get("ok") and erg["ordner_geprueft"] is False
           and [m for m, _p, _a in br.rufe] == ["get_document_info"], erg)

    # W9 der Riegel des Servers
    erg, _ = _warten(pfad, [[eintrag]], gut, erwartet="Zug")
    pruefe("W9 OPEN_MCP_CAD_EXPECT_DOC passt nicht -> expect_doc_conflict",
           _code(erg) == "expect_doc_conflict", erg)
    erg, _ = _warten(pfad, [[eintrag]], gut, erwartet="seeb")
    pruefe("W9 KONTROLLE: passender Riegel -> ok", erg.get("ok"), erg)

    # W10 Endung
    erg, _ = _warten(os.path.join(ordner, "Seeblick"), [[eintrag]], gut)
    pruefe("W10 ohne .3d -> wrong_extension (sonst wartete es ewig)",
           _code(erg) == "wrong_extension", erg)

    # W11 die Bridge antwortet erst beim zweiten Mal
    n = {"rufe": 0}

    def zickig(methode):
        if methode == "get_document_info":
            n["rufe"] += 1
            if n["rufe"] == 1:
                raise BC.BridgeUnreachable("noch nicht bereit")
            return {"document_name": "Seeblick.3d", "port": 54001}
        return {"result": pfad}

    erg, uhr = _warten(pfad, [[eintrag]], _Bridge({54001: zickig}))
    pruefe("W11 Bridge noch nicht bereit -> es wird weiter gewartet",
           erg.get("ok") and n["rufe"] == 2 and uhr.schlaefe == 1, erg)

    # W12 der Pfad ist nicht lesbar (Bridge-Fehler) -> nicht binden
    def ohne_pfad(methode):
        if methode == "get_document_info":
            return {"document_name": "Seeblick.3d", "port": 54001}
        raise BC.BridgeError("execution_error", "kaputt")

    erg, _ = _warten(pfad, [[eintrag]], _Bridge({54001: ohne_pfad}))
    pruefe("W12 Pfad nicht lesbar -> path_unverifiable",
           _code(erg) == "path_unverifiable", erg)


# --- bridge_client: port= und ziel_setzen ---------------------------------

def _kern_bereich():
    """PORT_VON..PORT_BIS aus dem Kern-QUELLTEXT — keine eigene Liste."""
    import ast
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
    with io.open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    werte = {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
             if isinstance(k, ast.Assign) and len(k.targets) == 1
             and isinstance(k.targets[0], ast.Name)
             and k.targets[0].id in ("PORT_VON", "PORT_BIS")}
    return set(range(werte["PORT_VON"], werte["PORT_BIS"] + 1))


_CADWORK_PORTS = _kern_bereich()


def _ephemerer_socket():
    """Ein Socket auf einem ephemeren Port AUSSERHALB 53127..53199.

    Windows vergibt ephemere Ports ab 49152 — der Cadwork-Bereich liegt
    mittendrin. Landet `bind(0)` dort, wird sofort wieder freigegeben und
    neu gezogen: ein Test lauscht nie auf einem Cadwork-Port und spricht
    nie einen an.
    """
    for _ in range(200):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        if s.getsockname()[1] not in _CADWORK_PORTS:
            return s
        s.close()
    raise RuntimeError("kein ephemerer Port ausserhalb 53127..53199")


class _MiniBridge:
    """Eine echte TCP-Gegenstelle auf einem EPHEMEREN Port.

    Beantwortet jede Zeile mit {"ok": true, "result": {"port": <eigener>}}.
    """

    def __init__(self):
        self.sock = _ephemerer_socket()
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.methoden = []
        self.t = threading.Thread(target=self._dienen, daemon=True)
        self.t.start()

    def _dienen(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                zeile = b""
                while b"\n" not in zeile:
                    teil = conn.recv(4096)
                    if not teil:
                        break
                    zeile += teil
                try:
                    self.methoden.append(json.loads(zeile)["method"])
                except ValueError:
                    pass
                conn.sendall((json.dumps(
                    {"ok": True, "result": {"port": self.port}})
                    + "\n").encode())

    def zu(self):
        self.sock.close()


def _toter_port():
    s = _ephemerer_socket()
    p = s.getsockname()[1]
    s.close()
    return p


def teil_client():
    mini = _MiniBridge()
    alt = (BC.BRIDGE_PORT, BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt,
           BC.BRIDGE_CONNECT_TIMEOUT_SECONDS)
    try:
        BC.BRIDGE_CONNECT_TIMEOUT_SECONDS = 0.5
        BC._gewaehlt = None
        BC.BRIDGE_PORT = _toter_port()
        BC._gebunden = True
        r = BC.call("ping", port=mini.port)
        pruefe("K1 call(port=) spricht genau diesen Port",
               r == {"port": mini.port}, r)
        try:
            BC.call("ping")
            ohne = "erreicht"
        except BC.BridgeUnreachable:
            ohne = "unerreichbar"
        pruefe("K1 KONTROLLE: ohne port= geht es an den Sitzungsport "
               "(hier tot)", ohne == "unerreichbar", ohne)

        # ziel_setzen: danach geht alles dorthin, und OPEN_MCP_CAD_DOC fragt
        # die Registry nicht mehr.
        gefragt = []
        echt = B.registry.laufende
        B.registry.laufende = lambda: gefragt.append("gefragt") or []
        try:
            BC.BRIDGE_DOC, BC._gebunden = "Seeblick", False
            try:
                BC._port()
            except BC.InstanzUnklar:
                pass                    # leere Registry: nichts gefunden
            ohne_bindung = list(gefragt)
            gefragt.clear()
            BC.BRIDGE_DOC, BC._gebunden = "Seeblick", False
            BC.ziel_setzen(mini.port)
            try:
                r = BC.call("status")
            except BC.BridgeUnreachable as exc:
                r = repr(exc)
        finally:
            B.registry.laufende = echt
        pruefe("K2 nach ziel_setzen geht call() an den gebundenen Port",
               r == {"port": mini.port}, r)
        pruefe("K2 und die Dokument-Suche fragt die Registry nicht mehr",
               gefragt == [], gefragt)
        pruefe("K2 KONTROLLE: ohne ziel_setzen fragt sie (die Messung sieht "
               "es)", ohne_bindung == ["gefragt"], ohne_bindung)
    finally:
        (BC.BRIDGE_PORT, BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt,
         BC.BRIDGE_CONNECT_TIMEOUT_SECONDS) = alt
        mini.zu()


# --- bridge_client: Portwahl ohne jede Angabe -----------------------------
#
# Im MCP-Server (AUTOMATISCH) waehlt der Client ohne OPEN_MCP_CAD_PORT,
# OPEN_MCP_CAD_DOC und Bindung ueber die Registry. Hier gegen eine
# TEMP-Registry und echte Gegenstellen auf ephemeren Ports AUSSERHALB
# 53127..53199; der Rueckfall-Port ist ein toter ephemerer, nie ein
# Cadwork-Port.

def _eintragen(ordner, port, dokument, pid=None):
    with open(os.path.join(ordner, "instanz-%d.json" % port), "w",
              encoding="utf-8") as fh:
        json.dump({"port": port, "instanz": "P%d" % port,
                   "pid": os.getpid() if pid is None else pid,
                   "dokument": dokument}, fh)


def _austragen(ordner, port):
    os.remove(os.path.join(ordner, "instanz-%d.json" % port))


def _leeren(ordner):
    for n in os.listdir(ordner):
        if n.startswith("instanz-"):
            os.remove(os.path.join(ordner, n))


def _toter_pid():
    for pid in (2 ** 31 - 4, 2 ** 30 - 4, 999999996):
        if not B.registry._pid_lebt(pid):
            return pid
    return None


def teil_tote(t):
    """T: ein beendeter Prozess, auf den noch ein Handle offen ist, zaehlt
    nicht als laufend (Anlass 2026-09-25: Cadwork geschlossen, sein Eintrag
    galt weiter als laufend, open_document verweigerte die Datei)."""
    if os.name != "nt":
        pruefe("T0 nur unter Windows (Handle-Semantik)", True)
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    reg = B.registry
    # Der echte Popen, nicht der Draht: gestartet wird nur dieses Python.
    p = _ECHT["Popen"]([sys.executable, "-c", "pass"])
    p.wait()                   # beendet; das Popen-Objekt haelt den Handle
    h = k32.OpenProcess(0x00100000, False, p.pid)
    oeffnen_geht = bool(h)
    if h:
        k32.CloseHandle(h)
    pruefe("T1-K KONTROLLE: der beendete Prozess laesst sich noch oeffnen "
           "(genau das hielt die alte Pruefung fuer lebend)", oeffnen_geht)
    pruefe("T1 er zaehlt nicht als lebend", not reg._pid_lebt(p.pid))
    pruefe("T2 der eigene Prozess zaehlt als lebend", reg._pid_lebt(os.getpid()))
    alt = reg.REGISTRY_ORDNER
    reg.REGISTRY_ORDNER = t
    try:
        _eintragen(t, 1, "Beendet.3d", pid=p.pid)
        _eintragen(t, 2, "Lebt.3d")
        docs = [e["dokument"] for e in reg.laufende()]
        pruefe("T3 laufende() nennt nur den lebenden Eintrag",
               docs == ["Lebt.3d"], docs)
    finally:
        reg.REGISTRY_ORDNER = alt
        del p


def _bc_frisch_geladen(**umgebung):
    """Eine FRISCHE Kopie von bridge_client, geladen mit dieser Umgebung.

    Die Umgebungsvariablen liest das Modul nur beim Import — eine Zelle, die
    `_PORT_ANGEGEBEN` von Hand setzt, prueft das Lesen nicht.
    """
    import importlib.util
    namen = ("OPEN_MCP_CAD_PORT", "CADWORK_BRIDGE_PORT", "OPEN_MCP_CAD_DOC")
    alt = {n: os.environ.pop(n, None) for n in namen}
    os.environ.update(umgebung)
    try:
        spec = importlib.util.spec_from_file_location(
            "open_mcp_cad._bc_umgebung", BC.__file__)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for n in namen:
            os.environ.pop(n, None)
            if alt[n] is not None:
                os.environ[n] = alt[n]
    m.AUTOMATISCH = True                   # wie im Server
    m.BRIDGE_CONNECT_TIMEOUT_SECONDS = 0.5
    return m


def teil_portwahl(t):
    reg = B.registry
    m1, m2, m3 = _MiniBridge(), _MiniBridge(), _MiniBridge()
    tot = _toter_port()
    alt = (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
           BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
           BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER)

    def frisch(automatisch=True):
        """Ein frisch gestarteter Server ohne jede Angabe."""
        BC.BRIDGE_PORT = BC._PORT_BEIM_IMPORT = int(str(tot))
        BC._PORT_ANGEGEBEN, BC._gebunden = False, False
        BC.BRIDGE_DOC, BC._gewaehlt = "", None
        BC.AUTOMATISCH = automatisch

    def ziel(modul=BC):
        """Wohin call() WIRKLICH ging: Port der Gegenstelle, sonst warum nicht."""
        try:
            return modul.call("ping")["port"]
        except modul.InstanzUnklar:
            return "unklar"
        except modul.BridgeUnreachable:
            return "unerreichbar"

    def gesendet():
        return len(m1.methoden) + len(m2.methoden) + len(m3.methoden)

    try:
        BC.BRIDGE_CONNECT_TIMEOUT_SECONDS = 0.5
        reg.REGISTRY_ORDNER = t
        pruefe("P0 als Bibliothek ist die Automatik aus",
               alt[6] is False, alt[6])
        pruefe("P0 keine Test-Gegenstelle im Cadwork-Bereich",
               not {m1.port, m2.port, m3.port, tot} & _CADWORK_PORTS,
               [m1.port, m2.port, m3.port, tot])

        frisch()
        try:
            BC.call("ping")
            p1 = "erreicht"
        except BC.InstanzUnklar:
            p1 = "unklar"
        except BC.BridgeUnreachable as exc:
            p1 = str(exc)
        pruefe("P1 nichts eingetragen -> Rueckfallport, die Meldung nennt "
               "die leere Registry",
               str(tot) in p1 and "keine Instanz eingetragen" in p1, p1)
        _eintragen(t, m1.port, "Seeblick.3d")
        r = ziel()
        pruefe("P1 DIESELBE Sitzung findet das Cadwork, das danach verbindet "
               "(Server startet vor Cadwork)", r == m1.port, r)

        frisch()
        r = ziel()
        pruefe("P2 genau ein Cadwork eingetragen -> call() geht dorthin",
               r == m1.port, r)
        frisch(automatisch=False)
        r = ziel()
        pruefe("P2 KONTROLLE: als Bibliothek (ohne Server) bleibt es beim "
               "festen Port — ein Skript baut nie still ins laufende Cadwork",
               r == "unerreichbar", r)
        frisch()
        BC._PORT_ANGEGEBEN = True
        r = ziel()
        pruefe("P2 KONTROLLE: mit angegebenem Port bleibt es beim festen",
               r == "unerreichbar", r)
        frisch()
        BC.BRIDGE_PORT = int(str(tot))          # gleicher Wert, neues Objekt
        r = ziel()
        pruefe("P3 `BRIDGE_PORT = x` von aussen ist eine Wahl, auch mit "
               "demselben Wert (Kontrolle: P2)", r == "unerreichbar", r)

        # Die Umgebung wird beim IMPORT gelesen — also frisch laden.
        for var in ("OPEN_MCP_CAD_PORT", "CADWORK_BRIDGE_PORT"):
            m = _bc_frisch_geladen(**{var: str(tot)})
            r = ziel(m)
            pruefe("P3 %s beim Start setzt den Port fest" % var,
                   r == "unerreichbar", r)
        r = ziel(_bc_frisch_geladen())
        pruefe("P3 KONTROLLE: dieselbe Ladung ohne Variable waehlt selbst",
               r == m1.port, r)

        _eintragen(t, m2.port, "Zweitdatei.3d")
        frisch()
        vorher = gesendet()
        try:
            BC.call("ping")
            p4 = None
        except BC.InstanzUnklar as exc:
            p4 = exc
        pruefe("P4 zwei eingetragen -> InstanzUnklar nennt beide "
               "(Kontrolle: P2)",
               p4 is not None and sorted(i["port"] for i in p4.instanzen)
               == sorted([m1.port, m2.port]), p4)
        pruefe("P4 und es wurde NICHTS gesendet", gesendet() == vorher,
               gesendet() - vorher)
        pruefe("P4 InstanzUnklar ist ein BridgeUnreachable (die Werkzeuge "
               "fangen es schon)", isinstance(p4, BC.BridgeUnreachable))

        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _eintragen(t, m2.port, "Zweitdatei.3d")
        dann = ziel()
        pruefe("P5 ein spaeter verbundenes zweites Fenster lenkt nicht um "
               "(Kontrolle: P4)", erst == dann == m1.port, repr((erst, dann)))

        _austragen(t, m1.port)
        vorher = gesendet()
        r = ziel()
        pruefe("P6 das gewaehlte verschwindet, uebrig ist ein ANDERES "
               "Dokument -> unklar, nichts gesendet",
               r == "unklar" and gesendet() == vorher, r)
        frisch()
        r = ziel()
        pruefe("P6 KONTROLLE: eine frische Sitzung nimmt dasselbe Fenster",
               r == m2.port, r)

        # Neu gestartet mit DERSELBEN Datei: auch das wird nicht still
        # uebernommen — die Registry kennt nur den Namen, nicht den Ordner.
        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _leeren(t)
        _eintragen(t, m3.port, "Seeblick.3d")
        vorher = gesendet()
        r = ziel()
        pruefe("P7 das gewaehlte verschwindet, gleicher Dateiname auf neuem "
               "Port -> unklar, nichts gesendet (Kontrolle: P6 KONTROLLE)",
               erst == m1.port and r == "unklar" and gesendet() == vorher,
               repr((erst, r)))

        # Gleicher Port, anderer lebender Prozess: das Dock nimmt immer den
        # ersten freien Port, ein neu gestartetes Cadwork bekommt oft
        # denselben. Bewusst mit DERSELBEN Datei — sonst schluege schon die
        # Dateiwechsel-Pruefung (P8) an, und die PID bliebe ungeprueft.
        ander = os.getppid()
        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _eintragen(t, m1.port, "Seeblick.3d", pid=ander)
        r = ziel()
        pruefe("P7 gleicher Port und Dateiname, anderer Prozess -> unklar",
               B.registry._pid_lebt(ander) and ander != os.getpid()
               and erst == m1.port and r == "unklar", repr((ander, erst, r)))

        # Der Kern traegt sich erst OHNE Dokumentnamen ein und fuehrt ihn
        # nach; ein Dateiwechsel im selben Cadwork dagegen ist ein Wechsel.
        _leeren(t)
        _eintragen(t, m1.port, "")
        frisch()
        erst = ziel()
        _eintragen(t, m1.port, "Seeblick.3d")
        zweit = ziel()
        _eintragen(t, m1.port, "Zweitdatei.3d")
        vorher = gesendet()
        dritt = ziel()
        pruefe("P8 ein nachgetragener Dokumentname stoert nicht",
               erst == zweit == m1.port, repr((erst, zweit)))
        pruefe("P8 eine andere Datei im gewaehlten Cadwork -> unklar, nichts "
               "gesendet", dritt == "unklar" and gesendet() == vorher, dritt)
        _eintragen(t, m1.port, "SEEBLICK.3d")
        frisch()
        ziel()
        _eintragen(t, m1.port, "seeblick.3d")
        r = ziel()
        pruefe("P8 KONTROLLE: nur Gross/Klein anders -> derselbe",
               r == m1.port, r)

        toter = _toter_pid()
        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        _eintragen(t, m2.port, "Zweitdatei.3d", pid=toter)
        frisch()
        r = ziel()
        pruefe("P9 ein Eintrag mit totem Prozess zaehlt nicht mit",
               toter is not None and r == m1.port, repr((toter, r)))
        _eintragen(t, m2.port, "Zweitdatei.3d")
        frisch()
        r = ziel()
        pruefe("P9 KONTROLLE: lebt der Prozess, sind es zwei -> unklar",
               r == "unklar", r)

        frisch()
        BC.ziel_setzen(m2.port)
        r = ziel()
        pruefe("P10 nach ziel_setzen (wait_for_bridge) geht es an den "
               "gebundenen, trotz zweier Fenster", r == m2.port, r)
        frisch()
        BC.BRIDGE_DOC = "zweitdatei"
        r = ziel()
        pruefe("P10 OPEN_MCP_CAD_DOC waehlt weiter ueber das Dokument",
               r == m2.port, r)

        try:
            import mcp                                     # noqa: F401
        except ImportError:
            print("  (Portwahl ueber die Server-Werkzeuge NICHT geprueft: "
                  "`mcp` fehlt in diesem Python.)")
            return
        BC.AUTOMATISCH = False
        from open_mcp_cad import server as S
        pruefe("P12 der Import des Servers allein schaltet die Automatik "
               "NICHT ein (Kontrolle: P12 unten)", BC.AUTOMATISCH is False)
        frisch()
        erg = S.get_document_info()
        pruefe("P11 Werkzeug bei zwei Fenstern: error instanz_waehlen mit "
               "der Liste",
               erg.get("error") == "instanz_waehlen"
               and sorted(i["port"] for i in erg.get("instanzen", []))
               == sorted([m1.port, m2.port])
               and "wait_for_bridge" in erg.get("message", ""), erg)
        _austragen(t, m2.port)
        frisch()
        erg = S.get_document_info()
        pruefe("P11 KONTROLLE: bei einem Fenster antwortet dieses",
               erg.get("ok") and erg.get("port") == m1.port, erg)
        _austragen(t, m1.port)
        erg = S.get_document_info()
        pruefe("P11 das gewaehlte ist weg und nichts mehr da: die Meldung "
               "sagt, dass kein Cadwork verbunden ist",
               erg.get("error") == "instanz_waehlen"
               and erg.get("instanzen") == []
               and "kein Cadwork verbunden" in erg.get("message", ""), erg)
        frisch(automatisch=False)
        gerufen = []
        echt_run = S.mcp.run
        S.mcp.run = lambda **kw: gerufen.append(kw)
        try:
            S.main()
        finally:
            S.mcp.run = echt_run
        pruefe("P12 erst server.main() schaltet die Automatik ein",
               BC.AUTOMATISCH is True and gerufen == [{"transport": "stdio"}],
               repr((BC.AUTOMATISCH, gerufen)))
    finally:
        (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
         BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
         BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER) = alt
        for m in (m1, m2, m3):
            m.zu()


# --- bridge_client: Wahl ueber OPEN_MCP_CAD_DOC ---------------------------
#
# Befund 2026-09-25: die Registry wurde nur beim ERSTEN Aufruf gefragt. Fand
# sie da nichts (der Server startet oft vor Cadwork), ging jeder weitere
# Aufruf still an den festen Port; mehrere Treffer warfen einmal einen
# Fehler, den die Werkzeuge nicht fingen, und der zweite Aufruf ging
# ebenfalls an den festen Port. Jetzt waehlt nur ein eindeutiger Treffer.
#
# Der feste Port ist hier eine LEBENDE Gegenstelle (m3): ginge ein Aufruf
# still dorthin, saehe man es an ihrer Antwort. Mit einem toten Port waere
# "nicht gesendet" von "gesendet, aber niemand da" nicht zu unterscheiden.

def teil_dokument(t):
    reg = B.registry
    m1, m2, m3 = _MiniBridge(), _MiniBridge(), _MiniBridge()
    alt = (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
           BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
           BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER)

    def frisch(dokument="Seeblick", automatisch=False):
        """Ein frisch gestarteter Prozess mit OPEN_MCP_CAD_DOC — als
        Bibliothek (ein Zeichner), es sei denn `automatisch` — und einem
        festen Port, der ANTWORTET."""
        BC.BRIDGE_PORT = BC._PORT_BEIM_IMPORT = int(str(m3.port))
        BC._PORT_ANGEGEBEN, BC._gebunden = False, False
        BC.BRIDGE_DOC, BC._gewaehlt = dokument, None
        BC.AUTOMATISCH = automatisch

    def ziel(modul=BC):
        """Wohin call() WIRKLICH ging: Port der Gegenstelle, sonst warum nicht."""
        try:
            return modul.call("ping")["port"]
        except modul.InstanzUnklar:
            return "unklar"
        except modul.BridgeUnreachable:
            return "unerreichbar"
        except Exception as exc:                          # noqa: BLE001
            return type(exc).__name__          # z. B. MehrdeutigesDokument

    def gesendet():
        return len(m1.methoden) + len(m2.methoden) + len(m3.methoden)

    def unklar_mit(modul=BC):
        try:
            modul.call("ping")
        except Exception as exc:                          # noqa: BLE001
            return exc
        return None

    try:
        BC.BRIDGE_CONNECT_TIMEOUT_SECONDS = 0.5
        reg.REGISTRY_ORDNER = t
        _leeren(t)
        pruefe("D0 keine Test-Gegenstelle im Cadwork-Bereich",
               not {m1.port, m2.port, m3.port} & _CADWORK_PORTS,
               [m1.port, m2.port, m3.port])

        frisch(dokument="")
        r = ziel()
        pruefe("D1 KONTROLLE: ohne Dokument geht ein Skript an den festen "
               "Port — er antwortet", r == m3.port, r)
        frisch()
        vorher = gesendet()
        r1, r2 = ziel(), ziel()
        pruefe("D1 Dokument gesetzt, nichts eingetragen -> unklar, der feste "
               "Port bekommt nichts",
               r1 == "unklar" and gesendet() == vorher, r1)
        pruefe("D1 auch beim ZWEITEN Aufruf kein Rueckfall auf den festen "
               "Port (der Befund)", r2 == "unklar" and gesendet() == vorher,
               repr((r2, gesendet() - vorher)))
        _eintragen(t, m1.port, "Seeblick.3d")
        r = ziel()
        pruefe("D2 DIESELBE Sitzung findet die Datei, sobald Cadwork "
               "verbindet (neu gefragt je Aufruf)", r == m1.port, r)
        frisch(automatisch=True)
        _leeren(t)
        r1 = ziel()
        _eintragen(t, m1.port, "Seeblick.3d")
        r2 = ziel()
        pruefe("D2 ebenso im Server (Automatik an): erst unklar, dann die "
               "Datei", (r1, r2) == ("unklar", m1.port), repr((r1, r2)))

        _leeren(t)
        _eintragen(t, m2.port, "Zweitdatei.3d")
        frisch()
        vorher = gesendet()
        d3 = unklar_mit()
        pruefe("D3 nur eine ANDERE Datei verbunden -> InstanzUnklar, nichts "
               "gesendet, die Liste nennt sie und die Meldung die Suche",
               isinstance(d3, BC.InstanzUnklar)
               and [i["port"] for i in d3.instanzen] == [m2.port]
               and "Seeblick" in d3.grund and gesendet() == vorher, repr(d3))
        frisch(dokument="", automatisch=True)
        r = ziel()
        pruefe("D3 KONTROLLE: ohne Dokument nimmt der Server genau dieses "
               "Fenster", r == m2.port, r)

        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        _eintragen(t, m2.port, "Seeblick_Kopie.3d")
        frisch()
        vorher = gesendet()
        d4 = unklar_mit()
        pruefe("D4 zwei passende Dateien -> InstanzUnklar (ein "
               "BridgeUnreachable, die Werkzeuge fangen es) nennt beide",
               isinstance(d4, BC.InstanzUnklar)
               and sorted(i["port"] for i in d4.instanzen)
               == sorted([m1.port, m2.port]), repr(d4))
        r = ziel()
        pruefe("D4 auch der zweite Aufruf: unklar, nichts gesendet",
               r == "unklar" and gesendet() == vorher,
               repr((r, gesendet() - vorher)))
        BC.BRIDGE_DOC = "seeblick_kopie"
        r = ziel()
        pruefe("D4 KONTROLLE: ein genauerer Name waehlt eindeutig",
               r == m2.port, r)

        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _eintragen(t, m2.port, "Seeblick_Kopie.3d")
        dann = ziel()
        pruefe("D5 ein spaeter verbundenes, ebenfalls passendes Fenster "
               "lenkt nicht um (Kontrolle: D4)",
               erst == dann == m1.port, repr((erst, dann)))
        _austragen(t, m1.port)
        vorher = gesendet()
        r = ziel()
        pruefe("D6 das gewaehlte verschwindet, uebrig ist ein anderes "
               "PASSENDES -> unklar, nichts gesendet",
               r == "unklar" and gesendet() == vorher, r)
        frisch()
        r = ziel()
        pruefe("D6 KONTROLLE: eine frische Sitzung nimmt das uebrige",
               r == m2.port, r)

        ander = os.getppid()
        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _eintragen(t, m1.port, "Seeblick.3d", pid=ander)
        r = ziel()
        pruefe("D7 gleicher Port und Dateiname, anderer Prozess -> unklar",
               B.registry._pid_lebt(ander) and ander != os.getpid()
               and erst == m1.port and r == "unklar", repr((ander, erst, r)))

        _leeren(t)
        _eintragen(t, m1.port, "Seeblick.3d")
        frisch()
        erst = ziel()
        _eintragen(t, m1.port, "")
        zweit = ziel()
        _eintragen(t, m1.port, "Seeblick_v2.3d")
        vorher = gesendet()
        dritt = ziel()
        pruefe("D8 ein leerer Name im gewaehlten Cadwork stoert nicht",
               erst == zweit == m1.port, repr((erst, zweit)))
        pruefe("D8 eine andere Datei im gewaehlten Cadwork -> unklar, auch "
               "wenn ihr Name ebenfalls passt",
               dritt == "unklar" and gesendet() == vorher, dritt)
        _eintragen(t, m1.port, "SEEBLICK.3d")
        frisch()
        ziel()
        _eintragen(t, m1.port, "seeblick.3d")
        r = ziel()
        pruefe("D8 KONTROLLE: nur Gross/Klein anders -> derselbe",
               r == m1.port, r)

        # Die Umgebung wird beim IMPORT gelesen — also frisch laden.
        _leeren(t)
        _eintragen(t, m2.port, "Zweitdatei.3d")
        vorher = gesendet()
        r = ziel(_bc_frisch_geladen(OPEN_MCP_CAD_DOC="Seeblick",
                                    OPEN_MCP_CAD_PORT=str(m3.port)))
        pruefe("D9 OPEN_MCP_CAD_DOC ohne Treffer neben OPEN_MCP_CAD_PORT "
               "(beide beim Start gesetzt) -> unklar, der feste Port bekommt "
               "nichts", r == "unklar" and gesendet() == vorher, r)
        r = ziel(_bc_frisch_geladen(OPEN_MCP_CAD_PORT=str(m3.port)))
        pruefe("D9 KONTROLLE: nur OPEN_MCP_CAD_PORT -> dorthin",
               r == m3.port, r)
        _eintragen(t, m1.port, "Seeblick.3d")
        r = ziel(_bc_frisch_geladen(OPEN_MCP_CAD_DOC="Seeblick",
                                    OPEN_MCP_CAD_PORT=str(m3.port)))
        pruefe("D9 KONTROLLE: mit Treffer geht das Dokument vor dem Port",
               r == m1.port, r)

        # wait_for_bridge bzw. ein Adapter mit eigenem festem Port
        # binden mit ziel_setzen — das geht dem Dokument vor.
        frisch()
        BC.ziel_setzen(m2.port)
        r = ziel()
        pruefe("D10 nach ziel_setzen geht es an den gebundenen, obwohl die "
               "Datei woanders offen ist (Kontrolle: D2)", r == m2.port, r)

        try:
            import mcp                                     # noqa: F401
        except ImportError:
            print("  (Dokument-Wahl ueber die Server-Werkzeuge NICHT "
                  "geprueft: `mcp` fehlt in diesem Python.)")
            return
        from open_mcp_cad import server as S
        _leeren(t)
        _eintragen(t, m2.port, "Zweitdatei.3d")
        frisch(automatisch=True)
        erg = S.get_document_info()
        pruefe("D11 Werkzeug mit OPEN_MCP_CAD_DOC ohne Treffer: error "
               "instanz_waehlen, nennt die Suche und die Liste",
               erg.get("error") == "instanz_waehlen"
               and "Seeblick" in erg.get("message", "")
               and [i["port"] for i in erg.get("instanzen", [])] == [m2.port],
               erg)
        _eintragen(t, m1.port, "Seeblick.3d")
        erg = S.get_document_info()
        pruefe("D11 KONTROLLE: sobald die Datei verbunden ist, antwortet "
               "dieses Fenster — in derselben Sitzung",
               erg.get("ok") and erg.get("port") == m1.port, erg)
    finally:
        (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
         BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
         BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER) = alt
        for m in (m1, m2, m3):
            m.zu()


# --- Registry-Leser: wiederverwendete PID ---------------------------------
#
# Befund 2026-09-25: ein Eintrag zeigte auf PID 17820, sein Cadwork war
# seit dem Vortag beendet, die PID gehoerte einem anderen Prozess. Jeder
# Leser hielt den Steckplatz fuer belegt, die Automatik im Server sah zwei
# Instanzen statt einer. Nachgebaut mit einem ECHTEN fremden Prozess: einem
# Python-Kind, gestartet NACH dem Eintrag. Nur dafuer der echte Popen am
# Draht vorbei — mit sys.executable, nie mit einer .3d.

def _alte_probe(pid):
    """Die Lebend-Pruefung bis 2026-09-25, woertlich: nur die PID."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def _python_kind():
    return _ECHT["Popen"]([sys.executable, "-c",
                           "import time; time.sleep(120)"],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def _modul_aus(pfad, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _registry_leser():
    """Jeder Registry-Leser, aus der QUELLE geladen: Server, Statusfenster,
    der Kern (seit 2.17.1, hier ohne Aufraeumen — das misst test_registry
    R57-R59) und der Verbindungs-Client in jedem Plugin-Ordner des
    Generators, der einen hat. [(name, modul, lesefunktion)]"""
    import importlib.util
    gen = _modul_aus(os.path.join(REPO, "scripts", "plugins_generieren.py"),
                     "_pg_lebend")
    cc = _modul_aus(os.path.join(REPO, "scripts", "connect_client.py"),
                    "_cc_lebend")
    spec = importlib.util.spec_from_file_location("_kern_lebend",
                                                  gen.KERN_QUELLE)
    kern = importlib.util.module_from_spec(spec)
    sys.modules["_kern_lebend"] = kern
    spec.loader.exec_module(kern)
    leser = [("registry.py", B.registry, B.registry.laufende),
             ("connect_client.py", cc, cc.registry_lesen),
             ("Kern", kern, lambda: kern.registry_lesen(aufraeumen=False))]
    for _i, ordner, _p in gen.ALLE_ORDNER:
        pfad = os.path.join(gen.PLUGIN_DIR, ordner,
                            "omcad_verbindungen_client.py")
        if os.path.exists(pfad):
            m = _modul_aus(pfad, "_vc_lebend_%d" % len(leser))
            leser.append(("%s/omcad_verbindungen_client.py" % ordner, m,
                          m.registry_lesen))
    return leser


def _mit_probe(modul, probe, fn):
    """`fn()` mit `modul._pid_lebt` ersetzt durch `probe` — der Mutant."""
    echt = modul._pid_lebt
    modul._pid_lebt = lambda pid, seit=None: probe(pid)
    try:
        return fn()
    finally:
        modul._pid_lebt = echt


def teil_lebend(t):
    import time
    if os.name != "nt":
        print("  (wiederverwendete PID NICHT geprueft: nur unter Windows)")
        return
    leser = _registry_leser()
    namen = [n for n, _m, _f in leser]
    pruefe("G0 alle Leser gefunden: Server, Statusfenster, Kern, "
           "Verbindungs-Client in A und im ausgerollten Ordner",
           len(leser) >= 5 and "Kern" in namen
           and sum("verbindungen" in n for n in namen) >= 2, namen)

    vor_dem_kind = time.time()
    time.sleep(0.05)
    kind = _python_kind()
    try:
        nach_dem_kind = time.time()
        with open(os.path.join(t, "instanz-54001.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"port": 54001, "instanz": "G", "pid": kind.pid,
                       "dokument": "Geist.3d",
                       "start": vor_dem_kind - 60},
                      fh)
        for port, dok, pid, start in (
                (54002, "Echt.3d", os.getpid(), time.time()),
                (54003, "KindEcht.3d", kind.pid, nach_dem_kind),
                (54004, "OhneStart.3d", kind.pid, None)):
            eintrag = {"port": port, "instanz": "G", "pid": pid,
                       "dokument": dok}
            if start is not None:
                eintrag["start"] = start
            with open(os.path.join(t, "instanz-%d.json" % port), "w",
                      encoding="utf-8") as fh:
                json.dump(eintrag, fh)

        pruefe("G1 KONTROLLE: die PID des Geists lebt (alte Probe: ja) — "
               "sonst misst G1 nur eine tote PID",
               _alte_probe(kind.pid) and kind.poll() is None, kind.pid)
        for name, modul, lesen in leser:
            alt = modul.REGISTRY_ORDNER
            modul.REGISTRY_ORDNER = t
            try:
                doks = {e.get("dokument") for e in lesen()}
                mutant = {e.get("dokument")
                          for e in _mit_probe(modul, _alte_probe, lesen)}
            finally:
                modul.REGISTRY_ORDNER = alt
            pruefe("G1 %s: fremde lebende PID, gestartet NACH dem Eintrag, "
                   "zaehlt nicht" % name, "Geist.3d" not in doks, sorted(doks))
            pruefe("G1-K %s KONTROLLE, DIE ROT WERDEN MUSS: mit der alten "
                   "Probe (nur PID) zaehlt der Geist" % name,
                   "Geist.3d" in mutant, sorted(mutant))
            pruefe("G2 %s: dieselbe PID mit einem Eintrag NACH ihrem Start "
                   "zaehlt, der eigene Prozess ebenso" % name,
                   {"KindEcht.3d", "Echt.3d"} <= doks, sorted(doks))
            pruefe("G3 %s: ein Eintrag ohne Startzeit bleibt bei der "
                   "PID-Pruefung" % name, "OhneStart.3d" in doks,
                   sorted(doks))

        # Die Folge im Server: ein echtes Cadwork und ein Geist. Vorher
        # `InstanzUnklar` ("zwei Instanzen"), jetzt das echte.
        _leeren(t)
        mini = _MiniBridge()
        tot = _toter_port()
        reg = B.registry
        alt = (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
               BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
               BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER)

        def ziel():
            BC.BRIDGE_PORT = BC._PORT_BEIM_IMPORT = int(str(tot))
            BC._PORT_ANGEGEBEN, BC._gebunden = False, False
            BC.BRIDGE_DOC, BC._gewaehlt = "", None
            BC.AUTOMATISCH = True
            try:
                return BC.call("ping")["port"]
            except BC.InstanzUnklar:
                return "unklar"
            except BC.BridgeUnreachable:
                return "unerreichbar"

        try:
            BC.BRIDGE_CONNECT_TIMEOUT_SECONDS = 0.5
            reg.REGISTRY_ORDNER = t
            for port, pid, start, dok in (
                    (mini.port, os.getpid(), time.time(), "Seeblick.3d"),
                    (tot, kind.pid, vor_dem_kind - 60, "Geist.3d")):
                with open(os.path.join(t, "instanz-%d.json" % port), "w",
                          encoding="utf-8") as fh:
                    json.dump({"port": port, "instanz": "G", "pid": pid,
                               "dokument": dok, "start": start}, fh)
            r = ziel()
            pruefe("G5 Automatik im Server: ein Cadwork und ein Geist -> "
                   "call() geht an das Cadwork", r == mini.port, r)
            r = _mit_probe(reg, _alte_probe, ziel)
            pruefe("G5-K KONTROLLE, DIE ROT WERDEN MUSS: mit der alten Probe "
                   "-> unklar, der Befund vom 2026-09-25", r == "unklar", r)
            pruefe("G5 keine Test-Gegenstelle im Cadwork-Bereich",
                   not {mini.port, tot} & _CADWORK_PORTS, [mini.port, tot])
        finally:
            (BC.BRIDGE_PORT, BC._PORT_BEIM_IMPORT, BC._PORT_ANGEGEBEN,
             BC._gebunden, BC.BRIDGE_DOC, BC._gewaehlt, BC.AUTOMATISCH,
             BC.BRIDGE_CONNECT_TIMEOUT_SECONDS, reg.REGISTRY_ORDNER) = alt
            mini.zu()

        # Beendet, aber das Prozessobjekt lebt weiter, weil `kind` sein
        # Handle haelt: die PID ist belegt, der Prozess tot.
        _leeren(t)
        kind.kill()
        kind.wait()
        with open(os.path.join(t, "instanz-54005.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"port": 54005, "instanz": "G", "pid": kind.pid,
                       "dokument": "Beendet.3d", "start": nach_dem_kind}, fh)
        pruefe("G4 KONTROLLE: die alte Probe haelt den beendeten Prozess "
               "fuer lebend (sein Handle ist noch offen)",
               _alte_probe(kind.pid), kind.pid)
        for name, modul, lesen in leser:
            alt = modul.REGISTRY_ORDNER
            modul.REGISTRY_ORDNER = t
            try:
                doks = {e.get("dokument") for e in lesen()}
            finally:
                modul.REGISTRY_ORDNER = alt
            pruefe("G4 %s: ein beendeter Prozess zaehlt nicht, auch wenn "
                   "noch ein Handle auf ihn offen ist" % name,
                   "Beendet.3d" not in doks, sorted(doks))
    finally:
        if kind.poll() is None:
            kind.kill()
        kind.wait()


# --- server.wait_for_bridge (nur mit mcp) ---------------------------------

def teil_server():
    try:
        import mcp                                         # noqa: F401
    except ImportError:
        print("  (server.wait_for_bridge NICHT geprueft: `mcp` fehlt in "
              "diesem Python. Mit dem Env, das `mcp` hat, erneut laufen "
              "lassen.)")
        return
    from open_mcp_cad import server as S
    alt = (BC.BRIDGE_PORT, BC._gebunden, S.EXPECT_DOC,
           S.bootstrap.warte_auf_bridge)
    try:
        S.EXPECT_DOC = ""
        S.bootstrap.warte_auf_bridge = lambda *a, **kw: {
            "ok": False, "error": "timeout", "message": "x"}
        BC.BRIDGE_PORT = 1
        erg = S.wait_for_bridge("C:\\x\\Seeblick.3d", 1)
        pruefe("S1 kein Fund -> nichts gebunden",
               not erg.get("ok") and BC.BRIDGE_PORT == 1
               and S.EXPECT_DOC == "", erg)
        gesehen = {}

        def fund(dok, timeout_s, erwartet=""):
            gesehen["erwartet"] = erwartet
            return {"ok": True, "port": 54321, "dokument": "Seeblick.3d"}

        S.bootstrap.warte_auf_bridge = fund
        erg = S.wait_for_bridge("C:\\x\\Seeblick.3d", 1)
        pruefe("S2 Fund -> Port UND Dokument-Riegel gebunden",
               erg.get("gebunden") and BC.BRIDGE_PORT == 54321
               and S.EXPECT_DOC == "Seeblick.3d", erg)
        S.bootstrap.warte_auf_bridge = fund
        S.wait_for_bridge("C:\\x\\Seeblick.3d", 1)
        pruefe("S3 ein gesetzter Riegel geht an die Suche mit",
               gesehen.get("erwartet") == "Seeblick.3d", gesehen)
        namen = set()
        try:
            import asyncio
            namen = {w.name for w in asyncio.run(S.mcp.list_tools())}
        except Exception as exc:                          # noqa: BLE001
            namen = {"Fehler: %r" % exc}
        pruefe("S4 die drei Werkzeuge sind registriert",
               {"create_from_init", "open_document",
                "wait_for_bridge"} <= namen, sorted(namen))
    finally:
        (BC.BRIDGE_PORT, BC._gebunden, S.EXPECT_DOC,
         S.bootstrap.warte_auf_bridge) = alt


def main():
    print("Datei-Bootstrap — Gate\n")
    _draehte_spannen()
    try:
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_create(t)
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_open(t)
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_warten(t)
        teil_client()
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_tote(t)
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_portwahl(t)
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_dokument(t)
        with tempfile.TemporaryDirectory(prefix="omcad_boot_") as t:
            teil_lebend(t)
        teil_server()
    finally:
        _draehte_loesen()
    unerwartet = [a for a in _ausgeloest if a[0] != "os.startfile"]
    pruefe("Z Kein Start ausser dem erwarteten Draht in O7",
           len(_ausgeloest) == 1 and not unerwartet, _ausgeloest)

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
