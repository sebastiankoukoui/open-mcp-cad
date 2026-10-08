# -*- coding: utf-8 -*-
"""Erweiterungen: zusaetzliche Werkzeuge aus eigenen Modulen (seit 2026-10-01).

Der Server laedt beim Start die Module aus der Umgebungsvariable
OPEN_MCP_CAD_ERWEITERUNGEN (`;`-getrennt). Ein Eintrag ist

  * ein Modul- oder Paketname (`paket.werkzeuge`), importiert wie ueblich,
  * ein Ordner, der ein Paket ist (mit `__init__.py`): sein Elternordner
    kommt vorne in `sys.path`, importiert wird der Ordnername,
  * eine `.py`-Datei, geladen unter einem eigenen Namen.

Jedes Modul stellt bereit:

    def registrieren(mcp, kontext):
        kontext.werkzeug(meine_pruefung, name="lesen_meine_pruefung",
                         lesend=True)
        kontext.werkzeug(mein_auftrag)            # aendernd (Vorgabe)

`mcp` ist der FastMCP-Server, `kontext` ein `Kontext` (unten): er registriert
Werkzeuge, schickt Auftragscode ueber dieselbe Bruecke mit demselben
Dokumentriegel wie execute_cadwork_command und reicht die Fehlerklassen der
Bruecke weiter. Eine Erweiterung importiert den Server NIE (Kreisimport).

LESEND ODER AENDERND — das entscheidet der Werkzeugname
    Die Freigabe-Politik des Docks (omcad_a_chat.werkzeug_art) sieht nur
    Namen. Jedes Werkzeug einer Erweiterung gilt deshalb als AENDERND, ausser
    die Erweiterung erklaert es mit `lesend=True` fuer nur lesend — dann MUSS
    sein Name mit LESEND_PRAEFIX anfangen und NAME_MUSTER erfuellen, und nur
    so ein Name darf mit dem Praefix anfangen. Beides prueft `werkzeug()`,
    und nach `registrieren` prueft `laden` noch einmal alle neuen Namen (auch
    solche, die an `kontext` vorbei direkt ueber `mcp.tool` kamen). Dieselben
    zwei Konstanten stehen im Dock (omcad_a_chat.py); test_chat_kern EP5
    vergleicht sie aus dem Quelltext. Nur beide zusammen aendern.

FEHLER BRINGEN DEN SERVER NIE ZU FALL
    Scheitert eine Erweiterung (Import, fehlendes `registrieren`, Ausnahme,
    SystemExit, verbotener Name, ein ersetztes Kernwerkzeug), werden alle
    Werkzeuge, die sie bis dahin angelegt hat, wieder entfernt und ein
    ersetztes Kernwerkzeug zurueckgestellt. Der Bericht (`laden` gibt ihn
    zurueck) steht im Server in `ERWEITERUNGEN`, auf stderr und — sobald die
    Variable gesetzt ist — in get_connection_status unter `erweiterungen`.

Bewusst ohne `mcp`-Import (Gate tests/test_erweiterungen.py im
System-Python gegen eine Attrappe, mit dem Server-Env gegen FastMCP).
"""

import hashlib
import importlib
import importlib.util
import os
import re
import sys
import traceback

from . import auftraege, bridge_client

#: Version dieser Schnittstelle (`kontext.schnittstelle`). Heben, wenn sich
#: `Kontext` inkompatibel aendert.
SCHNITTSTELLE = 1
UMGEBUNG = "OPEN_MCP_CAD_ERWEITERUNGEN"
TRENNER = ";"

#: Nur lesende Werkzeuge einer Erweiterung heissen so. Dieselben Werte in
#: omcad_a_chat.py (ERWEITERUNG_LESEND_PRAEFIX, ERWEITERUNG_NAME) — EP5.
LESEND_PRAEFIX = "lesen_"
NAME_MUSTER = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
_NAME = re.compile(NAME_MUSTER)

#: Laenger wird eine Fehlermeldung im Bericht nicht.
MELDUNG_MAX = 400


class ErweiterungFehler(Exception):
    """Eine Erweiterung verletzt die Regeln dieser Schnittstelle."""


def name_ist_lesend(name):
    """Traegt `name` die Kennzeichnung "nur lesend"? (wie das Dock)."""
    return (isinstance(name, str) and name.startswith(LESEND_PRAEFIX)
            and _NAME.fullmatch(name) is not None
            and len(name) > len(LESEND_PRAEFIX))


def name_pruefen(name, lesend):
    """Wirft ErweiterungFehler, wenn `name` nicht zu `lesend` passt."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ErweiterungFehler(
            "Werkzeugname %r: nur a-z, 0-9 und einzelne Unterstriche, "
            "Buchstabe zuerst" % (name,))
    if lesend and not name_ist_lesend(name):
        raise ErweiterungFehler(
            "Werkzeug %r ist als nur lesend erklaert, der Name muss dann mit "
            "%r anfangen" % (name, LESEND_PRAEFIX))
    if not lesend and name.startswith(LESEND_PRAEFIX):
        raise ErweiterungFehler(
            "Werkzeug %r aendert (lesend=False), sein Name darf nicht mit %r "
            "anfangen — das Dock liesse es sonst ohne Rueckfrage laufen"
            % (name, LESEND_PRAEFIX))


def _werkzeuge(mcp):
    """{Name: Werkzeugobjekt} des Servers (FastMCP: `_tool_manager._tools`)."""
    return getattr(getattr(mcp, "_tool_manager", None), "_tools", None)


def _kurz(exc):
    text = "%s: %s" % (type(exc).__name__, exc)
    return text if len(text) <= MELDUNG_MAX else text[:MELDUNG_MAX] + "…"


def _stderr(text):
    try:
        sys.stderr.write("[open-mcp-cad] %s\n" % text)
        sys.stderr.flush()
    except Exception:                                   # noqa: BLE001
        pass


class Kontext:
    """Was eine Erweiterung vom Server bekommt (je Erweiterung eins).

    werkzeug(fn, name=None, lesend=False, beschreibung=None) -> Name
        registriert `fn` als Werkzeug; Regeln fuer den Namen oben.
    auftrag(code, beschreibung="", lesen=False, timeout_s=0) -> dict
        schickt cwapi3d-Code an Cadwork wie execute_cadwork_command:
        schreibend erst nach dem Dokumentriegel des Servers, mit
        `expect_document`, `access_mode` "read"/"write"; Fehler als Antwort
        (`ok` False, `error` wie im Server, `antwort_fehlt` = gesendet, NICHT
        wiederholen).
    rufen(methode, params=None, antwort_timeout=None)
        roh wie bridge_client.call (erst beim Aufruf nachgeschlagen).
    erwartet() -> str
        der aktuelle Dokumentriegel (OPEN_MCP_CAD_EXPECT_DOC bzw. die
        Bindung von wait_for_bridge), leer = keiner.
    BridgeUnreachable, AntwortFehlt, BridgeError, fehler_antwort, wartezeit
        die Fehlerklassen und Helfer der Bruecke.
    melden(text)
        eine Zeile auf stderr.
    """

    schnittstelle = SCHNITTSTELLE
    lesend_praefix = LESEND_PRAEFIX
    name_muster = NAME_MUSTER
    BridgeUnreachable = bridge_client.BridgeUnreachable
    AntwortFehlt = bridge_client.AntwortFehlt
    BridgeError = bridge_client.BridgeError

    def __init__(self, mcp, erwartet=None, dokument_pruefen=None,
                 rufen=None, eintrag=""):
        self._mcp = mcp
        self._erwartet = erwartet or (lambda: "")
        self._dokument_pruefen = dokument_pruefen or (lambda: None)
        self._rufen = rufen
        self.eintrag = eintrag
        self.lesend = []
        self.aendernd = []

    # -- Werkzeuge ---------------------------------------------------------

    def werkzeug(self, fn, name=None, lesend=False, beschreibung=None):
        name = name or getattr(fn, "__name__", None)
        name_pruefen(name, bool(lesend))
        vorhanden = _werkzeuge(self._mcp)
        if vorhanden is not None and name in vorhanden:
            raise ErweiterungFehler("Werkzeugname %r ist schon vergeben"
                                    % name)
        k = {"name": name, "description": beschreibung}
        if lesend:
            try:
                from mcp.types import ToolAnnotations
                k["annotations"] = ToolAnnotations(readOnlyHint=True)
            except Exception:                            # noqa: BLE001
                pass
        self._mcp.add_tool(fn, **k)
        (self.lesend if lesend else self.aendernd).append(name)
        return name

    # -- Bruecke -----------------------------------------------------------

    def rufen(self, methode, params=None, **k):
        rufe = self._rufen or bridge_client.call
        return rufe(methode, params, **k)

    def erwartet(self):
        return (self._erwartet() or "").strip()

    @staticmethod
    def fehler_antwort(exc):
        return auftraege.fehler_antwort(exc)

    @staticmethod
    def wartezeit(timeout_s, vorgabe):
        return auftraege.wartezeit(timeout_s, vorgabe)

    def auftrag(self, code, beschreibung="", lesen=False, timeout_s=0):
        if not lesen:
            fehler = self._dokument_pruefen()
            if fehler:
                return fehler
        params = {"code": code, "result_var": "result",
                  "description": beschreibung,
                  "access_mode": "read" if lesen else "write"}
        erw = self.erwartet()
        if erw:
            params["expect_document"] = erw
        try:
            r = self.rufen("execute_cwapi3d", params,
                           antwort_timeout=auftraege.wartezeit(
                               timeout_s, bridge_client.BRIDGE_TIMEOUT_SECONDS))
        except bridge_client.BridgeUnreachable as exc:
            return auftraege.fehler_antwort(exc)
        except bridge_client.BridgeError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message,
                    "details": exc.details}
        return {"ok": True, "description": beschreibung, **(r or {})}

    @staticmethod
    def melden(text):
        _stderr(str(text))


# --- Laden --------------------------------------------------------------------

def eintraege(roh=None):
    """Die Eintraege aus OPEN_MCP_CAD_ERWEITERUNGEN (ohne leere, ohne
    Anfuehrungszeichen, ohne Doppelte, Reihenfolge bleibt)."""
    if roh is None:
        roh = os.environ.get(UMGEBUNG, "")
    aus = []
    for teil in (roh or "").split(TRENNER):
        t = teil.strip().strip('"').strip()
        if t and t not in aus:
            aus.append(t)
    return aus


def _ist_pfad(eintrag):
    return (os.sep in eintrag or "/" in eintrag or eintrag.endswith(".py")
            or os.path.isdir(eintrag))


def importieren(eintrag):
    """-> Modul. Wirft bei allem, was kein ladbares Modul ist."""
    if _ist_pfad(eintrag):
        pfad = os.path.abspath(eintrag)
        if os.path.isdir(pfad):
            if not os.path.isfile(os.path.join(pfad, "__init__.py")):
                raise ErweiterungFehler(
                    "Ordner %s ist kein Paket (keine __init__.py)" % pfad)
            eltern, name = os.path.split(pfad.rstrip("\\/"))
            if eltern not in sys.path:
                sys.path.insert(0, eltern)
            return importlib.import_module(name)
        if os.path.isfile(pfad) and pfad.endswith(".py"):
            name = "omcad_erweiterung_" + hashlib.sha256(
                os.path.normcase(pfad).encode("utf-8")).hexdigest()[:12]
            spec = importlib.util.spec_from_file_location(name, pfad)
            modul = importlib.util.module_from_spec(spec)
            sys.modules[name] = modul
            try:
                spec.loader.exec_module(modul)
            except BaseException:
                sys.modules.pop(name, None)
                raise
            return modul
        raise ErweiterungFehler("%s gibt es nicht" % pfad)
    return importlib.import_module(eintrag)


def _einen_laden(mcp, eintrag, kontext_fabrik):
    bericht = {"eintrag": eintrag, "ok": False, "lesend": [],
               "aendernd": [], "fehler": None}
    werkzeuge = _werkzeuge(mcp)
    if werkzeuge is None:
        bericht["fehler"] = "Server ohne Werkzeugliste (_tool_manager._tools)"
        return bericht
    vorher = dict(werkzeuge)
    try:
        modul = importieren(eintrag)
        bericht["modul"] = getattr(modul, "__name__", "?")
        registrieren = getattr(modul, "registrieren", None)
        if not callable(registrieren):
            raise ErweiterungFehler("Modul %s hat kein registrieren(mcp, "
                                    "kontext)" % bericht["modul"])
        k = kontext_fabrik(eintrag)
        registrieren(mcp, k)
        jetzt = _werkzeuge(mcp)
        ersetzt = sorted(n for n, w in vorher.items()
                         if jetzt.get(n) is not w)
        if ersetzt:
            raise ErweiterungFehler("Kernwerkzeuge ersetzt oder entfernt: %s"
                                    % ", ".join(ersetzt))
        neu = sorted(set(jetzt) - set(vorher))
        erklaert_lesend = set(k.lesend)
        for n in neu:
            if n in erklaert_lesend:
                name_pruefen(n, True)
            elif n.startswith(LESEND_PRAEFIX):
                raise ErweiterungFehler(
                    "Werkzeug %r traegt die Kennzeichnung nur lesend, ist "
                    "aber nicht ueber kontext.werkzeug(..., lesend=True) "
                    "erklaert" % n)
        bericht["lesend"] = [n for n in neu if n in erklaert_lesend]
        bericht["aendernd"] = [n for n in neu if n not in erklaert_lesend]
        bericht["ok"] = True
    except (Exception, SystemExit) as exc:              # noqa: BLE001
        # Zurueck auf den Stand vor dieser Erweiterung: ihre Werkzeuge weg,
        # ein ersetztes/entferntes Kernwerkzeug wieder her.
        jetzt = _werkzeuge(mcp)
        if jetzt is not None:
            for n in list(jetzt):
                if n not in vorher:
                    del jetzt[n]
            for n, w in vorher.items():
                if jetzt.get(n) is not w:
                    jetzt[n] = w
        bericht["fehler"] = _kurz(exc)
        _stderr("Erweiterung %r nicht geladen: %s" % (eintrag,
                                                      bericht["fehler"]))
        for zeile in traceback.format_exc().splitlines()[-6:]:
            _stderr("  " + zeile)
    return bericht


def laden(mcp, roh=None, erwartet=None, dokument_pruefen=None, rufen=None):
    """Laedt alle Erweiterungen. -> Bericht je Eintrag (Liste). Wirft nie."""
    berichte = []
    try:
        liste = eintraege(roh)
    except Exception as exc:                            # noqa: BLE001
        return [{"eintrag": roh, "ok": False, "fehler": _kurz(exc),
                 "lesend": [], "aendernd": []}]

    def fabrik(eintrag):
        return Kontext(mcp, erwartet=erwartet,
                       dokument_pruefen=dokument_pruefen, rufen=rufen,
                       eintrag=eintrag)

    for eintrag in liste:
        try:
            b = _einen_laden(mcp, eintrag, fabrik)
        except BaseException as exc:                    # noqa: BLE001
            if isinstance(exc, KeyboardInterrupt):
                raise
            b = {"eintrag": eintrag, "ok": False, "fehler": _kurz(exc),
                 "lesend": [], "aendernd": []}
        if b.get("ok"):
            _stderr("Erweiterung %r geladen: %d lesend, %d aendernd"
                    % (eintrag, len(b["lesend"]), len(b["aendernd"])))
        berichte.append(b)
    return berichte
