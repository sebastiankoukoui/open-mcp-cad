#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline-Gate NUR fuer den A-ONLY UI PROTOTYPE.

Bewusst getrennt von `test_offline.py`: dieser Prototyp gilt ausschliesslich
fuer Steckplatz A, und das gemeinsame Gate darf davon nichts wissen — sonst
waere die Trennung, um die es hier geht, schon im Test aufgeweicht.

WAS HIER GEPRUEFT WIRD (ohne Cadwork und ohne PyQt6):
  * A weicht vom Generator ab — und NUR A. B, C, D und der Kern nicht.
  * Die A-Kopie des Kerns ist bytegleich mit dem gemeinsamen Kern.
  * Der Einstieg laedt das Dashboard und startet den Dienst nie selbst —
    verbunden wird im Dashboard (`_verbinden`), nie per `kern.serve` daneben.
  * Das Dashboard fasst weder cwapi3d noch einen eigenen Thread an und setzt
    kein globales Stylesheet.
  * Die Zustands-Zuordnung deckt alle Zustaende des Kerns ab.

WAS HIER NICHT GEPRUEFT WIRD: das VERHALTEN der Oberflaeche. Dieses Gate
liest Quelltext. Dafuer gibt es seit 2026-08-15 ein zweites, das das Dock
wirklich baut und bedient (Qt offscreen, Cadwork durch Attrappen ersetzt):

    tests/test_a_live.py

Beides zusammen ist der Massstab. Der Anlass war handfest: die Befunde
("die Auswahl geht verloren", "die Bauteile werden nicht aktiviert") sind
Aussagen ueber Verhalten, und dieses Gate hier stand waehrenddessen auf
gruen — es KONNTE sie gar nicht sehen.

    python tests/test_a_prototyp.py
"""

import ast
import hashlib
import importlib.util
import io
import os
import re
import socket
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo

# Umzug 2026-09-20: Gate liegt in tests/, Generator und Verbindungs-Client in
# scripts/. Ohne diesen Eintrag findet `import plugins_generieren` nichts —
# und zwar mit einem Abbruch, nicht still.
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
PLUGIN = os.path.join(REPO, "cad_plugin")
A = os.path.join(PLUGIN, "Open MCP CAD A")
KERN = os.path.join(PLUGIN, "_core", "omcad_bridge_core.py")

_ergebnisse = []


def _kern_bereich():
    """PORT_VON..PORT_BIS aus dem Kern-QUELLTEXT — keine eigene Liste."""
    with io.open(KERN, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    werte = {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
             if isinstance(k, ast.Assign) and len(k.targets) == 1
             and isinstance(k.targets[0], ast.Name)
             and k.targets[0].id in ("PORT_VON", "PORT_BIS")}
    return set(range(werte["PORT_VON"], werte["PORT_BIS"] + 1))


_CADWORK_PORTS = _kern_bereich()


def _ephemerer_socket(verboten=None):
    """Ein exklusiv gebundener Socket auf einem ephemeren Port AUSSERHALB
    des Cadwork-Bereichs.

    Windows vergibt ephemere Ports ab 49152, der Bereich liegt mittendrin
    (gemessen 2026-09-25: bind(0) landete auf 53134-53197). Landet bind(0)
    in `verboten` (sonst: dem Cadwork-Bereich), wird sofort freigegeben und
    neu gezogen — wie `_ephemerer_socket` in test_bootstrap.
    """
    verboten = _CADWORK_PORTS if verboten is None else verboten
    for _ in range(200):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", 0))
        if s.getsockname()[1] not in verboten:
            return s
        s.close()
    raise RuntimeError("kein ephemerer Port ausserhalb des Cadwork-Bereichs")


def _ausserhalb(ports):
    """Gab es Testports, und liegt keiner im Cadwork-Bereich?"""
    return bool(ports) and not set(ports) & _CADWORK_PORTS



def _arbeitsordner_laden(quelltext, plugin_ordner):
    """Fuehrt NUR den Arbeitsordner-Abschnitt des Dashboards aus.

    Kein Qt, kein Cadwork: der Abschnitt haengt an nichts als `os`. So laesst
    sich messen, WOHIN die Funktion zeigt, statt nur zu pruefen, DASS sie
    dasteht — der Unterschied, an dem die Vorgaengerpruefung gescheitert ist.
    """
    try:
        a = quelltext.index("PROJEKT_DATEI = os.path.join(_HIER")
        e = quelltext.index("def _verbindungen_client")
    except ValueError:
        return None
    raum = {"os": os, "_HIER": plugin_ordner}
    try:
        exec(compile(quelltext[a:e], "<arbeitsordner>", "exec"), raum)
    except Exception:
        return None
    return raum.get("arbeitsordner")



def _funktion_laden(quelltext, name, von, bis):
    """Fuehrt einen Abschnitt des Dashboards aus und gibt eine Funktion her.

    Wie `_arbeitsordner_laden`: kein Qt, kein Cadwork. So laesst sich das
    VERHALTEN messen statt der Wortlaut.
    """
    try:
        a = quelltext.index(von)
        e = quelltext.index(bis, a)
    except ValueError:
        return None
    import socket as _s
    raum = {"os": os, "socket": _s}
    try:
        exec(compile(quelltext[a:e], "<" + name + ">", "exec"), raum)
    except Exception:
        return None
    return raum.get(name)


def _chat_server_verhalten(chat_pfad):
    """P9g: WELCHER Server startet der Chat, mit welchem Python und Wissen?

    Gemessen, nicht gelesen: das Chat-Modul kennt weder Qt noch cwapi3d und
    laesst sich deshalb hier laden. Bis 2026-09-22 startete der Chat
    `<Arbeitsordner>\\server.py` — den Server eines fremden Repos — aus
    einem Env, das es nicht gab.
    """
    import importlib.util
    import json as _json
    import tempfile
    spec = importlib.util.spec_from_file_location("p9g_chat", chat_pfad)
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)
    # OPEN_MCP_CAD_ERWEITERUNGEN reicht der Chat bewusst durch (EP in
    # test_chat_kern) — hier gehoert sie nicht hinein: auf dem Rechner des
    # Maintainers steht sie in der Shell, und "mit Port UND Fachwissen" war
    # dort allein deshalb rot (gemessen 2026-10-02, auch auf main).
    alt = {k: os.environ.get(k) for k in ("OPEN_MCP_CAD_PYTHON",
                                          "OPEN_MCP_CAD_KNOWLEDGE",
                                          "OPEN_MCP_CAD_ERWEITERUNGEN")}
    alt_datei = C.WISSEN_DATEI
    with tempfile.TemporaryDirectory(prefix="omcad_p9g_") as t:
        # Die MCP-Konfiguration heisst nach dem Port und liegt im Temp: hier
        # im Temp DIESES Laufs, sonst teilen sich parallele Laeufe die Datei
        # %TEMP%\open_mcp_cad_1.json (PermissionError, Nacharbeit D).
        C.tempfile = type(sys)("p9g_tempfile")
        C.tempfile.gettempdir = lambda: t
        env = os.path.join(t, "env")
        paket = os.path.join(env, "Lib", "site-packages")
        os.makedirs(paket)
        py = os.path.join(env, "python.exe")
        open(py, "w").close()                   # nie ausgefuehrt, nur da
        w1, w2 = os.path.join(t, "w1"), os.path.join(t, "w2")
        os.makedirs(w1)
        os.makedirs(w2)
        try:
            os.environ.pop("OPEN_MCP_CAD_ERWEITERUNGEN", None)
            os.environ["OPEN_MCP_CAD_PYTHON"] = py
            ohne_paket = C.mcp_python()
            os.makedirs(os.path.join(paket, "open_mcp_cad-0.1.0.dist-info"))
            mit_paket = C.mcp_python()
            pruefe("P9g Server-Python zaehlt nur MIT installiertem open_mcp_cad",
                   ohne_paket is None and mit_paket == py,
                   "ohne %r / mit %r" % (ohne_paket, mit_paket))
            os.environ["OPEN_MCP_CAD_PYTHON"] = os.path.join(t, "fehlt.exe")
            pruefe("P9g ein gesetztes, falsches OPEN_MCP_CAD_PYTHON wird "
                   "nicht still ersetzt", C.mcp_python() is None)
            # venv-Aufbau, wie ihn der Installer der Verteilung anlegt:
            # python.exe in Scripts\, Lib\ eine Ebene hoeher.
            venv = os.path.join(t, "venv")
            os.makedirs(os.path.join(venv, "Scripts"))
            os.makedirs(os.path.join(venv, "Lib", "site-packages",
                                     "open_mcp_cad-0.1.0.dist-info"))
            vpy = os.path.join(venv, "Scripts", "python.exe")
            open(vpy, "w").close()
            os.environ["OPEN_MCP_CAD_PYTHON"] = vpy
            pruefe("P9g auch ein venv (Scripts\\python.exe) wird erkannt",
                   C.mcp_python() == vpy, repr(C.mcp_python()))

            # Ohne Claude Code: eine Meldung, die man versteht.
            alt_appdata, alt_which = os.environ.get("APPDATA"), C.shutil.which
            alt_heim = os.environ.get("USERPROFILE")
            try:
                os.environ["APPDATA"] = t
                # Heim in Temp: sonst zaehlte ein echtes claude.exe des
                # eigenen Installers von Anthropic (~/.local/bin).
                os.environ["USERPROFILE"] = t
                C.shutil.which = lambda _n: None
                try:
                    C.cli_pfad()
                    meldung = ""
                except FileNotFoundError as exc:
                    meldung = str(exc)
                pruefe("P9g ohne Claude Code: klare Meldung statt WinError",
                       "Claude Code ist nicht installiert" in meldung, meldung)
                os.makedirs(os.path.join(t, "npm"))
                cmd = os.path.join(t, "npm", "claude.cmd")
                open(cmd, "w").close()
                pruefe("P9g KONTROLLE: mit claude.cmd wird es gefunden",
                       C.cli_pfad() == cmd)
            finally:
                C.shutil.which = alt_which
                for k, v in (("APPDATA", alt_appdata),
                             ("USERPROFILE", alt_heim)):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = os.pathsep.join(
                [w1, os.path.join(t, "gibtsnicht"), w2])
            pruefe("P9g Wissen aus der Umgebung, nur vorhandene Ordner",
                   C.wissensordner() == os.pathsep.join([w1, w2]),
                   repr(C.wissensordner()))
            os.environ.pop("OPEN_MCP_CAD_KNOWLEDGE")
            C.WISSEN_DATEI = os.path.join(t, "wissensordner.txt")
            with open(C.WISSEN_DATEI, "w", encoding="utf-8") as fh:
                fh.write('"%s"\n\n' % w2)
            pruefe("P9g sonst Wissen aus wissensordner.txt",
                   C.wissensordner() == w2, repr(C.wissensordner()))
            os.remove(C.WISSEN_DATEI)
            pruefe("P9g KONTROLLE: ohne beides kein Wissen",
                   C.wissensordner() is None, repr(C.wissensordner()))

            # Port 1: die Datei heisst nach dem Port und liegt im Temp — ein
            # echter Steckplatz darf dabei nicht ueberschrieben werden.
            os.environ["OPEN_MCP_CAD_PYTHON"] = py
            os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = w1
            cfg = C.mcp_konfig_schreiben(1)
            pruefe("P9g die Konfiguration liegt im Temp dieses Laufs",
                   os.path.dirname(cfg) == t, cfg)
            try:
                with open(cfg, encoding="utf-8") as fh:
                    s = _json.load(fh)["mcpServers"]["open-mcp-cad"]
            finally:
                os.remove(cfg)
            pruefe("P9g der Chat startet `python -m open_mcp_cad.server`, "
                   "nicht server.py eines Arbeitsordners",
                   s["command"] == py
                   and s["args"] == ["-m", "open_mcp_cad.server"], s)
            pruefe("P9g mit Port UND Fachwissen",
                   s["env"] == {"OPEN_MCP_CAD_PORT": "1",
                                "OPEN_MCP_CAD_KNOWLEDGE": w1}, s["env"])
            # Liegt pythonw.exe daneben, startet der Server OHNE Konsole.
            pyw = os.path.join(env, "pythonw.exe")
            open(pyw, "w").close()
            cfg = C.mcp_konfig_schreiben(1)
            try:
                with open(cfg, encoding="utf-8") as fh:
                    kommando = _json.load(fh)["mcpServers"]["open-mcp-cad"][
                        "command"]
            finally:
                os.remove(cfg)
            os.remove(pyw)
            pruefe("P9g mit pythonw.exe daneben: Server ohne Konsolenfenster",
                   kommando == pyw, kommando)
            os.environ["OPEN_MCP_CAD_PYTHON"] = os.path.join(t, "fehlt.exe")
            pruefe("P9g KONTROLLE: ohne Server-Python keine Konfiguration",
                   C.mcp_konfig_schreiben(1) is None)
        finally:
            C.WISSEN_DATEI = alt_datei
            for k, v in alt.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class _Feld:
    """So viel QComboBox, wie `_modellwahl` und `_cli_wahl_merken` lesen."""

    def __init__(self, daten=None, text=""):
        self._daten, self._text = daten, text

    def currentData(self):                            # noqa: N802
        return self._daten

    def currentText(self):                            # noqa: N802
        return self._text

    def count(self):
        return 0


def _modus_feld(D, C):
    """P11 (Gegenpruefung 2026-09-26, seit 2026-09-27 fuer die Modi): welcher
    Modus beim Bau im Feld steht — der, nach dem der Chat entscheidet.
    Gemessen an `chat_entscheiden`, also am Verhalten. Das Dock selbst
    (Neubau mit laufendem Chat) prueft test_a_live L42."""
    probe = ("mcp__open-mcp-cad__execute_cadwork_command", "Read", "Bash",
             "Write", "mcp__open-mcp-cad__get_document_info")

    def urteile(chat):
        return [C.chat_entscheiden(chat, t) for t in probe]

    # (Chat im Speicher, chat.json): ein laufender Chat (derselbe Prozess)
    # bzw. eine neue Sitzung mit gemerktem Modus.
    faelle = [({}, {}), ({"modus": "alles_auto"}, {}),
              ({"modus": "nur_lesen"}, {"modus": "alles_auto"}),
              ({"modus": "turbo"}, {}), ({"modus": None}, {}),
              ({}, {"modus": "nur_lesen"}), ({}, {"modus": "alles_auto"}),
              ({}, {"modus": "kaputt"}), ({}, {"modus": ["fragen"]})]

    def messen(regel):
        """-> die Faelle, in denen Feld und Chat verschieden entscheiden oder
        ein laufender Chat einen anderen Modus bekaeme."""
        falsch = []
        for chat, e in faelle:
            z = {"chat": dict(chat)}
            feld = regel(z, C, e)
            gleich = urteile({"modus": feld}) == urteile(z["chat"])
            behalten = (chat.get("modus") not in C.MODUS_WERTE
                        or feld == chat["modus"])
            if feld not in C.MODUS_WERTE or not gleich or not behalten:
                falsch.append((chat, e, feld, z["chat"].get("modus")))
        return falsch

    falsch = messen(D._modus_wirksam)
    pruefe("P11 das Modus-Feld zeigt den Modus, nach dem der Chat "
           "entscheidet (auch 'Alles automatisch' im laufenden Chat; "
           "Unbekanntes als 'Fragen')", not falsch, repr(falsch))
    neu = {k: D._modus_wirksam({}, C, e) for k, e in (
        ("leer", {}), ("nur_lesen", {"modus": "nur_lesen"}),
        ("auto", {"modus": "alles_auto"}), ("kaputt", {"modus": 7}))}
    pruefe("P11 neue Sitzung: der gemerkte Modus, nie 'Alles automatisch' "
           "(dann 'Cadwork frei'), sonst die Vorgabe",
           neu == {"leer": "fragen", "nur_lesen": "nur_lesen",
                   "auto": "cadwork_frei", "kaputt": "fragen"}, repr(neu))
    # KONTROLLE 1: die Regel bis 2026-09-26 — beim Bau immer die Vorgabe.
    falsch = messen(lambda z, C, e: C.MODUS_VORGABE)
    pruefe("P11 KONTROLLE: 'immer die Vorgabe' faellt auf — ein Chat in "
           "'Alles automatisch' laesst durch, was das Feld fragen wuerde",
           ({"modus": "alles_auto"}, {}) in [f[:2] for f in falsch],
           repr(falsch))
    # KONTROLLE 2: chat.json woertlich genommen — 'Alles automatisch'
    # ueberlebte den Neustart.
    def woertlich(z, C, e):
        z["chat"].setdefault("modus", (e or {}).get("modus")
                             if isinstance(e, dict) else None)
        return D._modus_wirksam(z, C, e)
    pruefe("P11 KONTROLLE: nimmt der Start chat.json woertlich, beginnt eine "
           "Sitzung in 'Alles automatisch'",
           woertlich({"chat": {}}, C, {"modus": "alles_auto"})
           == "alles_auto")


def _gemerkte_wahl(C):
    """P10 (Film 2026-09-25): was das Dock in chat.json merkt und liest, und
    die Kostenzeile. Die Helfer des Dashboards kennen kein Qt — sie werden
    hier direkt gerufen; das Dock selbst prueft test_a_live L37-L40."""
    import json as _json
    import tempfile as _tf
    vor = {n: sys.modules.get(n) for n in ("omcad_a_chat_A",
                                           "omcad_a_anbieter_A")}
    alt_env = os.environ.get("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN")
    pfad = os.path.join(_tf.mkdtemp(prefix="omcad_p10_"), "chat.json")
    os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = pfad
    try:
        spec = importlib.util.spec_from_file_location(
            "p10_dash", os.path.join(A, "omcad_a_dashboard.py"))
        D = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(D)
        vorgabe = (C.MODELL_VORGABE, C.EFFORT_VORGABE)

        def wahl(e):
            return D._cli_modell(e, "claude", C), D._cli_stufe(e, C)

        kaputt = [None, [], "x", {"modell": "opus"}, {"modell": ["opus"]},
                  {"modell": {"claude": 42}}, {"modell": {"claude": "  "}},
                  {"modell": {"claude": "opus\nrm"}},
                  {"modell": {"claude": "o" * (D.MODELLNAME_MAX + 1)}},
                  {"denkstufe": "turbo"}, {"denkstufe": ["high"]},
                  {"denkstufe": None}]
        falsch = [e for e in kaputt if wahl(e) != vorgabe]
        pruefe("P10 kaputte oder fremde Werte in chat.json -> die Vorgaben",
               not falsch, repr(falsch[:2]))
        gut = {"modell": {"claude": "claude-opus-4-7"}, "denkstufe": "high"}
        pruefe("P10 KONTROLLE: brauchbare Werte werden genommen (auch ein "
               "getippter Name)", wahl(gut) == ("claude-opus-4-7", "high")
               and wahl(gut) != vorgabe, repr(wahl(gut)))
        e = {"modell": "opus", "basis": 7}
        D._eintragen(e, "modell", "claude", "haiku")
        D._eintragen(e, "basis", "openai", "http://x")
        pruefe("P10 _eintragen repariert eine Tabelle, die keine war",
               e == {"modell": {"claude": "haiku"},
                     "basis": {"openai": "http://x"}}, repr(e))

        # Das Merken: Modell und Denkstufe — den Modus merkt nur
        # `_modus_merken`, auch wenn der Chat in "Alles automatisch" steht.
        z = {"chat": {"modus": "alles_auto"},
             "w": {"chat_anbieter": _Feld("claude"),
                   "chat_modell": _Feld(text="opus"),
                   "chat_stufe": _Feld("high")}}
        geschrieben = D._cli_wahl_merken(z)
        with io.open(pfad, encoding="utf-8") as fh:
            inhalt = _json.load(fh)
        pruefe("P10 _cli_wahl_merken schreibt Modell und Denkstufe",
               geschrieben and inhalt == {"modell": {"claude": "opus"},
                                          "denkstufe": "high"}, repr(inhalt))
        pruefe("P10 ... und keinen Modus, obwohl der Chat auf 'Alles "
               "automatisch' steht", "auto" not in _json.dumps(inhalt)
               and "modus" not in inhalt, repr(inhalt))
        # Der Modus: gemerkt, aber "Alles automatisch" als "Cadwork frei".
        wege = []
        for modus in ("nur_lesen", "alles_auto", "fragen", "turbo"):
            wege.append((modus, D._modus_merken(modus, C)))
            with io.open(pfad, encoding="utf-8") as fh:
                wege[-1] += (_json.load(fh).get("modus"),)
        pruefe("P10m _modus_merken: Nur lesen und Fragen wie gewaehlt, "
               "'Alles automatisch' als 'Cadwork frei', Unbekanntes gar nicht",
               wege == [("nur_lesen", True, "nur_lesen"),
                        ("alles_auto", True, "cadwork_frei"),
                        ("fragen", True, "fragen"),
                        ("turbo", False, "fragen")], repr(wege))
        with io.open(os.path.join(A, "omcad_a_dashboard.py"),
                     encoding="utf-8") as fh:
            _dq = fh.read()
        _alt = ("    wert = C.MODUS_STATT_AUTO if modus == C.MODUS_NIE_MERKEN "
                "else modus\n")
        _mut = type(sys)("p10m_mutant")
        _mut.__file__ = os.path.join(A, "omcad_a_dashboard.py")
        exec(compile(_dq.replace(_alt, "    wert = modus\n"),
                     _mut.__file__, "exec"), _mut.__dict__)
        _mut._modus_merken("alles_auto", C)
        with io.open(pfad, encoding="utf-8") as fh:
            _k = _json.load(fh).get("modus")
        pruefe("P10m KONTROLLE: ohne die Umschreibung stuende 'Alles "
               "automatisch' in chat.json", _dq.count(_alt) == 1
               and _k == "alles_auto", _k)
        D._modus_merken("fragen", C)
        with io.open(pfad, encoding="utf-8") as fh:
            _rest = _json.load(fh)
        _rest.pop("modus", None)
        with io.open(pfad, "w", encoding="utf-8") as fh:
            _json.dump(_rest, fh)
        pruefe("P10 KONTROLLE: unveraendert wird nicht erneut geschrieben",
               D._cli_wahl_merken(z) is False)

        # Die Kostenzeile: im Abo ohne Betrag, sonst wie bisher.
        zug = {"kosten": 1.4, "token": 0, "abgelehnt": 1}
        pruefe("P10 Abo: 'fertig' ohne USD, der Rest bleibt",
               D._schluss_text(zug, abo=True) == "— fertig · 1 abgelehnt",
               D._schluss_text(zug, abo=True))
        pruefe("P10 KONTROLLE: ohne Abo steht der Betrag da",
               "1.40 USD" in D._schluss_text(zug, abo=False))
        A_mod = D._anbieter_modul()
        abo = {a["id"]: D._chat_im_abo({"anbieter": a["id"]})
               for a in A_mod.ANBIETER}
        pruefe("P10 Claude Code ist ein Abo, kein Anbieter mit Pflicht-"
               "Schluessel ist eins (aus ANBIETER gelesen)",
               abo.get(A_mod.ANBIETER_VORGABE) is True
               and not any(abo[a["id"]] for a in A_mod.ANBIETER
                           if a.get("schluessel") == "pflicht"), repr(abo))
        pruefe("P10 KONTROLLE: ein unbekannter Anbieter gilt nicht als Abo "
               "(Betrag wie bisher)",
               D._chat_im_abo({}) is False
               and D._chat_im_abo({"anbieter": "gibtsnicht"}) is False)
        _modus_feld(D, C)
        _gemerkte_orte(D, C, pfad)
        _modus_hinweis_pruefen(D, C, os.path.join(A, "omcad_a_dashboard.py"))
        _lesbar_pruefen(D, C)
        _anhaenge_pruefen(D, os.path.join(A, "omcad_a_dashboard.py"))
        _sperre_pruefen(D, C, os.path.join(A, "omcad_a_dashboard.py"))
        _symbole_pruefen(D, os.path.join(A, "omcad_a_dashboard.py"))
        _einstieg_p19(D, os.path.join(A, "omcad_a_dashboard.py"))
        _k12_p20_p21(D, C, os.path.join(A, "omcad_a_dashboard.py"))
        _laien_p22(D, os.path.join(A, "omcad_a_dashboard.py"))
        _ruhe_p23(D, os.path.join(A, "omcad_a_dashboard.py"))
        _updates_p24(D, os.path.join(A, "omcad_a_dashboard.py"))
    finally:
        for _n, _alt in vor.items():
            if _alt is None:
                sys.modules.pop(_n, None)
            else:
                sys.modules[_n] = _alt
        if alt_env is None:
            os.environ.pop("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN", None)
        else:
            os.environ["OPEN_MCP_CAD_CHAT_EINSTELLUNGEN"] = alt_env


# --- S3: Namensregel und Sitzungsliste — VERHALTEN, gegen ein Temp-Heim ---

def _chat_variante(chat_pfad, ersetzungen=(), name="p9_chat"):
    """Das Chat-Modul aus der QUELLE, mit `ersetzungen` (alt, neu) veraendert.

    -> (Modul, Treffer je Ersetzung). Ein Mutant, der seine Stelle nicht
    findet (Treffer 0), ist keine Kontrolle — die Zellen verlangen je 1.
    """
    with io.open(chat_pfad, encoding="utf-8") as fh:
        text = fh.read()
    treffer = []
    for alt, neu in ersetzungen:
        treffer.append(text.count(alt))
        text = text.replace(alt, neu)
    m = type(sys)(name)
    m.__file__ = chat_pfad
    exec(compile(text, chat_pfad, "exec"), m.__dict__)
    return m, treffer


class _Lesezaehler:
    """Ersetzt `open` im Chat-Modul: zaehlt Oeffnungen und gelesene Bytes."""

    def __init__(self):
        self.oeffnungen = 0
        self.bytes = {}

    def open(self, pfad, *a, **k):
        fh = io.open(pfad, *a, **k)
        self.oeffnungen += 1
        zaehler = self

        class _Datei:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                fh.close()

            def read(self, n=-1):
                daten = fh.read(n)
                zaehler.bytes[pfad] = zaehler.bytes.get(pfad, 0) + len(daten)
                return daten

            def seek(self, *a):
                return fh.seek(*a)
        return _Datei()


#: Arbeitsordner und der Ordnername, den das CLI dafuer anlegt. Die Formen
#: sind am Bestand belegt (docs/UEBERGABE_2026-09-26_DOCKPLAN.md B.7 und
#: "Umsetzung": 38 von 38 Ordnern): `.claude` -> `-claude`, " - " -> "---",
#: "_" -> "-". Nur Pfade unter Public (Export-Regel).
NAMENSFAELLE = (
    (r"C:\Users\Public\Documents\OpenMcpCad_Demo",
     "C--Users-Public-Documents-OpenMcpCad-Demo"),
    (r"C:\Users\Public\Documents\OpenMcpCad_Demo\Arbeitsordner",
     "C--Users-Public-Documents-OpenMcpCad-Demo-Arbeitsordner"),
    (r"C:\Users\Public\projekte\open-mcp-cad\.claude\worktrees\seeblick",
     "C--Users-Public-projekte-open-mcp-cad--claude-worktrees-seeblick"),
    (r"C:\Users\Public\OneDrive - Holzbau AG\Seeblick 2",
     "C--Users-Public-OneDrive---Holzbau-AG-Seeblick-2"),
)
#: Der Arbeitsordner, dessen Sitzungen unten liegen — mit Unterstrich, damit
#: die alte Regel an ihm vorbeischaut.
SITZUNGS_ORDNER = r"C:\Users\Public\Documents\OpenMcpCad_Demo\Seeblick_1"
SITZUNGS_MARKE = "C--Users-Public-Documents-OpenMcpCad-Demo-Seeblick-1"


def _jsonl(pfad, zeilen, mtime):
    import json as _json
    with open(pfad, "wb") as fh:
        for z in zeilen:
            # Kompakt wie das CLI (`{"type":"custom-title"`): `_titel`
            # sucht genau diese Schreibweise.
            fh.write((z if isinstance(z, bytes)
                      else _json.dumps(z, ensure_ascii=False,
                                       separators=(",", ":"))
                      .encode("utf-8")) + b"\n")
    os.utime(pfad, (mtime, mtime))


def _sitzungen_anlegen(heim, C):
    """Sitzungsdateien wie die des CLI in `heim/.claude/projects`. -> Pfade."""
    import json as _json
    import time as _t
    ordner = os.path.join(heim, ".claude", "projects", SITZUNGS_MARKE)
    fremd = os.path.join(heim, ".claude", "projects", "C--Users-Public-anderes")
    os.makedirs(ordner)
    os.makedirs(fremd)
    jetzt = _t.time()
    p = {}

    def nutzer(inhalt, **mehr):
        e = {"type": "user", "message": {"role": "user", "content": inhalt}}
        e.update(mehr)
        return e
    fueller = _json.dumps({"type": "assistant", "message": {
        "content": [{"type": "text", "text": "x" * 2000}]}}).encode("utf-8")
    kopf_voll = C.KOPF_BYTES // len(fueller) + 2
    schwanz_voll = C.SCHWANZ_BYTES // len(fueller) + 2
    # a) gross: der alte Titel im Kopf, einer mitten drin, der neue im
    #    Schwanz. Groesser als Kopf und Schwanz zusammen.
    p["gross"] = os.path.join(ordner, "aaaa0001-gross.jsonl")
    _jsonl(p["gross"],
           [{"type": "queue-operation"},
            {"type": "custom-title", "customTitle": "Alter Titel"},
            {"type": "ai-title", "aiTitle": "KI-Titel"},
            nutzer("Wand im Erdgeschoss")]
           + [fueller] * kopf_voll
           + [{"type": "custom-title", "customTitle": "Mitte"}]
           + [fueller] * schwanz_voll
           + [{"type": "custom-title", "customTitle": "Neuer Titel"},
              fueller], jetzt - 400)
    # b) Inhalt als Text; davor ein Befehl und eine Meta-Zeile.
    p["text"] = os.path.join(ordner, "bbbb0002-text.jsonl")
    _jsonl(p["text"], [{"type": "queue-operation"},
                       nutzer("<command-name>/clear</command-name>"),
                       nutzer("Meta-Zeile", isMeta=True),
                       nutzer("Dach über dem Anbau")], jetzt - 300)
    # c) Inhalt als Liste von Bloecken, zuerst ein tool_result.
    p["liste"] = os.path.join(ordner, "cccc0003-liste.jsonl")
    _jsonl(p["liste"], [nutzer([{"type": "tool_result", "content": "ok"},
                                {"type": "text", "text": "Fenster setzen"}])],
           jetzt - 200)
    # d) zwei Sitzungen mit demselben Titel (Fortsetzung / Abzweigung).
    for i, name in enumerate(("dddd0004-a.jsonl", "eeee0005-b.jsonl")):
        p["doppelt%d" % i] = os.path.join(ordner, name)
        _jsonl(p["doppelt%d" % i],
               [{"type": "custom-title", "customTitle": "Doppelt"},
                nutzer("Frage %d" % i)], jetzt - 100 + i * 60)
    # e) eine Terminal-Sitzung in einem ANDEREN Projekt.
    p["fremd"] = os.path.join(fremd, "ffff0006-fremd.jsonl")
    _jsonl(p["fremd"], [nutzer("Gehoert nicht hierher")], jetzt)
    return p


def _sitzungen_messen(C, heim, pfade):
    """-> dict Zelle -> (bestanden, Detail) fuer ein Chat-Modul `C`.

    Laesst die Dateien am Ende so zurueck, wie sie waren."""
    r = {}
    projekte = os.path.join(heim, ".claude", "projects")
    falsch = [(w, os.path.basename(C.projekt_ordner(w)), soll)
              for w, soll in NAMENSFAELLE + ((SITZUNGS_ORDNER,
                                               SITZUNGS_MARKE),)
              if C.projekt_ordner(w) != os.path.join(projekte, soll)]
    r["namen"] = (not falsch, falsch)
    zaehler = _Lesezaehler()
    C.open = zaehler.open
    cache = {}
    liste = C.sitzungen(SITZUNGS_ORDNER, cache)
    namen = {e["id"]: e["bezeichnung"] for e in liste}
    ids = [e["id"] for e in liste]
    r["gefunden"] = (len(liste) == 5 and "ffff0006-fremd" not in ids, ids)
    r["titel"] = (namen.get("aaaa0001-gross") == "Neuer Titel",
                  namen.get("aaaa0001-gross"))
    gelesen = zaehler.bytes.get(pfade["gross"], 0)
    r["fenster"] = (0 < gelesen <= C.KOPF_BYTES + C.SCHWANZ_BYTES
                    < os.path.getsize(pfade["gross"]),
                    (gelesen, os.path.getsize(pfade["gross"])))
    r["text"] = (namen.get("bbbb0002-text") == "Dach über dem Anbau",
                 namen.get("bbbb0002-text"))
    r["liste"] = (namen.get("cccc0003-liste") == "Fenster setzen",
                  namen.get("cccc0003-liste"))
    doppelt = [namen.get("dddd0004-a"), namen.get("eeee0005-b")]
    r["doppelt"] = (all(n and n.startswith("Doppelt  (") for n in doppelt)
                    and doppelt[0] != doppelt[1], doppelt)
    r["reihenfolge"] = (ids[:1] == ["eeee0005-b"]
                        and ids[-1:] == ["aaaa0001-gross"], ids)
    # Warm: dieselbe Liste, ohne eine einzige Datei zu oeffnen. Dann waechst
    # eine Datei -> genau sie wird neu gelesen.
    vorher = zaehler.oeffnungen
    warm = C.sitzungen(SITZUNGS_ORDNER, cache)
    ohne_oeffnen = zaehler.oeffnungen - vorher
    # Die Eintraege gehoeren dem Aufrufer: was an ihnen geaendert wird —
    # auch die Uhrzeit, die `sitzungen` selbst an gleiche Titel haengt —,
    # darf nicht in den Puffer zurueck. Sonst waechst "(TT.MM. HH:MM)" bei
    # zwei gleichen Titeln derselben Minute mit jedem Aufruf.
    for e in warm:
        e["bezeichnung"] += " (TT.MM. HH:MM)"
    dritter = {e["id"]: e["bezeichnung"]
               for e in C.sitzungen(SITZUNGS_ORDNER, cache)}
    r["doppelt_warm"] = (dritter == namen, (dritter, namen))
    st = os.stat(pfade["liste"])
    with open(pfade["liste"], "rb") as fh:
        urfassung = fh.read()
    with open(pfade["liste"], "ab") as fh:
        fh.write(b'{"type":"custom-title","customTitle":"Umbenannt"}\n')
    os.utime(pfade["liste"], (st.st_atime, st.st_mtime + 5))
    vorher = zaehler.oeffnungen
    danach = {e["id"]: e["bezeichnung"]
              for e in C.sitzungen(SITZUNGS_ORDNER, cache)}
    r["puffer"] = (ohne_oeffnen == 0 and len(warm) == len(liste)
                   and zaehler.oeffnungen - vorher == 1
                   and danach.get("cccc0003-liste") == "Umbenannt",
                   (ohne_oeffnen, zaehler.oeffnungen - vorher,
                    danach.get("cccc0003-liste")))
    with open(pfade["liste"], "wb") as fh:
        fh.write(urfassung)
    os.utime(pfade["liste"], (st.st_atime, st.st_mtime))
    return r


def _sitzungsliste(chat_pfad):
    """P9 Namensregel und Sitzungsliste (S3, 2026-09-26): gemessen an echten
    Dateien in einem Temp-Heim (USERPROFILE), je Zelle eine Kontrolle mit
    einem Mutanten aus der Quelle. Ersetzt die Textsuchen von vorher."""
    import shutil as _sh
    import tempfile as _tf
    heim = _tf.mkdtemp(prefix="omcad_p9_heim_")
    alt = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = heim
    os.environ.pop("HOME", None)
    try:
        C, _t = _chat_variante(chat_pfad)
        pruefe("P9 Vorbedingung: das Heim des Gates ist der Temp-Ordner",
               os.path.expanduser("~") == heim, os.path.expanduser("~"))
        pfade = _sitzungen_anlegen(heim, C)
        echt = _sitzungen_messen(C, heim, pfade)
        texte = (
            ("namen", "die Ordnernamen folgen der Regel des CLI (alles "
                      "ausser a-zA-Z0-9 wird '-')"),
            ("gefunden", "die Liste zeigt genau die Sitzungen DIESES "
                         "Arbeitsordners"),
            ("titel", "der zuletzt gesetzte Titel gewinnt (Schwanz vor Kopf)"),
            ("fenster", "eine grosse Sitzungsdatei wird nie ganz gelesen "
                        "(nur Kopf und Schwanz)"),
            ("text", "Befehle und Meta-Zeilen taugen nicht als Name"),
            ("liste", "message.content als Liste von Bloecken"),
            ("doppelt", "gleiche Titel bekommen Datum und Uhrzeit"),
            ("doppelt_warm", "die Eintraege gehoeren dem Aufrufer: was er "
                             "(oder die Uhrzeit bei gleichen Titeln) daran "
                             "aendert, kommt beim naechsten Aufruf nicht "
                             "zurueck"),
            ("reihenfolge", "neueste zuerst"),
            ("puffer", "warm wird keine Datei geoeffnet, eine geaenderte "
                       "genau einmal"),
        )
        for zelle, text in texte:
            pruefe("P9 " + text, echt[zelle][0], echt[zelle][1])
        # KONTROLLEN: je ein Mutant aus der Quelle, der die Zelle rot
        # machen MUSS. Treffer 1 heisst: die Stelle gibt es genau so.
        # Seit Etappe D je UTF-16-Einheit (gemessen, s. NAMENSFAELLE_GEMESSEN).
        regel = ('marke = "".join(chr(e) if chr(e).isascii() and '
                 'chr(e).isalnum() else "-"\n'
                 '                    for e in einheiten)')
        alte_regel = ('marke = arbeitsordner.replace("\\\\", "-")'
                      '.replace("/", "-").replace(":", "-")')
        mutanten = (
            ("namen", "die alte Regel (nur Trenner ersetzt)",
             [(regel, alte_regel)], ("namen", "gefunden")),
            ("titel", "Kopf vor Schwanz",
             [("for block in (schwanz, kopf):",
               "for block in (kopf, schwanz):")], ("titel",)),
            ("fenster", "die ganze Datei lesen",
             [("kopf = fh.read(KOPF_BYTES)", "kopf = fh.read()")],
             ("fenster",)),
            ("text", "kein Filter fuer unbrauchbare Anfaenge",
             [("if text and not text.startswith(UNBRAUCHBAR):\n"
               "            return",
               "if text:\n            return")], ("text",)),
            ("liste", "content nur als Text",
             [("    if isinstance(inhalt, list):", "    if False:")],
             ("liste",)),
            ("puffer", "kein Puffer",
             [("eintrag = cache.get(schluessel)", "eintrag = None")],
             ("puffer",)),
            ("doppelt_warm", "die Eintraege des Puffers selbst herausgeben",
             [("        kopie = dict(eintrag)\n",
               "        kopie = eintrag\n")], ("doppelt_warm",)),
        )
        for zelle, was, ersetzungen, rot in mutanten:
            M, treffer = _chat_variante(chat_pfad, ersetzungen)
            m = _sitzungen_messen(M, heim, pfade)
            pruefe("P9 KONTROLLE (%s): %s -> rot" % (zelle, was),
                   treffer == [1] and not any(m[k][0] for k in rot),
                   repr((treffer, {k: m[k] for k in rot})))
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _sh.rmtree(heim, ignore_errors=True)


# --- Etappe D (S9): nur Dock-Sitzungen, alter Verlauf — gegen ein Temp-Heim --

#: Gemessen 2026-09-26 am echten CLI 2.1.263 (Haiku, ohne Werkzeuge, je ein
#: Lauf mit diesem cwd; die Ordner danach wieder entfernt): ueber 200
#: Zeichen gekuerzt plus Pruefsumme, ein Emoji zaehlt doppelt (UTF-16).
NAMENSFAELLE_GEMESSEN = (
    (r"C:\Users\Public\Documents\OpenMcpCad_Messung\Seeblick_"
     + "Wand_Erdgeschoss_Achse_" * 7 + "Ende",
     "C--Users-Public-Documents-OpenMcpCad-Messung-Seeblick-"
     + "Wand-Erdgeschoss-Achse-" * 6 + "Wand-Erd-vnmcix"),
    ("C:\\Users\\Public\\Documents\\OpenMcpCad_Messung\\Seeblick "
     "\U0001F332 Dach \u00e4\u00f6\u00fc",
     "C--Users-Public-Documents-OpenMcpCad-Messung-Seeblick----Dach----"),
    # Nacharbeit D: ein Pfad, dessen djb2 als 32-Bit-Zahl NEGATIV ist
    # (-1877906895); die beiden oberen sind positiv. Gemessen 2026-09-26 am
    # CLI 2.1.263 (Haiku, ohne Werkzeuge, ein Lauf, Ordner danach entfernt).
    (r"C:\Users\Public\Documents\OpenMcpCad_Messung\Seeblick_"
     + "Wand_Erdgeschoss_Achse_" * 7 + "Ost",
     "C--Users-Public-Documents-OpenMcpCad-Messung-Seeblick-"
     + "Wand-Erdgeschoss-Achse-" * 6 + "Wand-Erd-v2228f"),
)


def _dock_sitzungen_anlegen(heim, C):
    """Dock- und Terminal-Sitzungen desselben Ordners. -> Pfade."""
    import json as _json
    import time as _t
    ordner = os.path.join(heim, ".claude", "projects", SITZUNGS_MARKE)
    os.makedirs(ordner, exist_ok=True)
    jetzt = _t.time()
    marke = C.SITZUNG_NAME
    p = {}

    def nutzer(inhalt, **mehr):
        e = {"type": "user", "message": {"role": "user", "content": inhalt}}
        e.update(mehr)
        return e

    def antwort(*bloecke, **mehr):
        e = {"type": "assistant", "message": {"content": list(bloecke)}}
        e.update(mehr)
        return e
    # So beginnt eine Dock-Sitzung (gemessen: `-n` schreibt beide Zeilen
    # zuerst, nach jedem Zug noch einmal).
    kopf = [{"type": "custom-title", "customTitle": marke},
            {"type": "agent-name", "agentName": marke}]
    p["dock"] = os.path.join(ordner, "d0c00001-dock.jsonl")
    _jsonl(p["dock"], kopf + [
        nutzer("Wand im Obergeschoss"),
        antwort({"type": "text", "text": "Ich lege die Wand an."}),
        {"type": "custom-title", "customTitle": marke},
        {"type": "agent-name", "agentName": marke}], jetzt - 50)
    # Im Terminal umbenannt: der neue Titel gilt, Dock-Sitzung bleibt sie.
    p["umbenannt"] = os.path.join(ordner, "d0c00002-umbenannt.jsonl")
    _jsonl(p["umbenannt"], kopf + [
        nutzer("Dach"), {"type": "custom-title", "customTitle": "Umbenannt"}],
        jetzt - 40)
    # Gross: die Kennzeichnung nur im Kopf, danach mehr als ein Schwanz.
    fueller = _json.dumps(antwort({"type": "text", "text": "x" * 2000}))
    fueller = fueller.encode("utf-8")
    p["gross"] = os.path.join(ordner, "d0c00003-gross.jsonl")
    _jsonl(p["gross"], [kopf[0], nutzer("Fenster im Anbau")]
           + [fueller] * (C.SCHWANZ_BYTES // len(fueller) + 3)
           + [nutzer("Und jetzt die Tür"),
              antwort({"type": "thinking", "thinking": ""}),
              antwort({"type": "text", "text": "Die Tür steht."},
                      {"type": "tool_use", "name": "Read",
                       "input": {"file_path": "a.txt"}}),
              nutzer([{"type": "tool_result", "content": "Inhalt"}]),
              nutzer("Meta", isMeta=True),
              antwort({"type": "text", "text": "Nebenbei"}, isSidechain=True),
              nutzer("<command-name>/clear</command-name>"),
              antwort({"type": "text", "text": "Fertig."})], jetzt - 30)
    # Gross, aber im Schwanz nur zwei Nachrichten (dazwischen nur
    # Werkzeug-Ergebnisse): der Hinweis haengt an der Grenze der Datei,
    # nicht an der Hoechstzahl (Nacharbeit D, Mutant C7).
    ergebnis = _json.dumps(nutzer([{"type": "tool_result",
                                    "content": "y" * 2000}]))
    ergebnis = ergebnis.encode("utf-8")
    p["lang"] = os.path.join(ordner, "d0c00005-lang.jsonl")
    _jsonl(p["lang"], [kopf[0], nutzer("Treppe")]
           + [ergebnis] * (C.SCHWANZ_BYTES // len(ergebnis) + 3)
           + [nutzer("Und das Geländer"),
              antwort({"type": "text", "text": "Steht."})], jetzt - 35)
    # Eine Terminal-Sitzung im selben Ordner (ohne Kennzeichnung).
    p["terminal"] = os.path.join(ordner, "7e700004-terminal.jsonl")
    _jsonl(p["terminal"], [{"type": "custom-title", "customTitle": "Refactor"},
                           nutzer("Im Terminal")], jetzt - 20)
    # Ausserhalb des Ordners — eine Kennung wie "..\x" darf sie nicht lesen.
    p["draussen"] = os.path.join(heim, ".claude", "projects", "geheim.jsonl")
    _jsonl(p["draussen"], [nutzer("GEHEIM")], jetzt)
    return p


def _dock_messen(C, heim, pfade):
    """-> dict Zelle -> (bestanden, Detail)."""
    r = {}
    projekte = os.path.join(heim, ".claude", "projects")
    falsch = [(w, os.path.basename(C.projekt_ordner(w)), soll)
              for w, soll in NAMENSFAELLE_GEMESSEN
              if C.projekt_ordner(w) != os.path.join(projekte, soll)]
    r["gemessen"] = (not falsch, falsch)
    alle = C.sitzungen(SITZUNGS_ORDNER, {})
    dock = C.sitzungen(SITZUNGS_ORDNER, {}, nur_dock=True)
    namen = {e["id"]: e["bezeichnung"] for e in dock}
    r["filter"] = (sorted(namen) == ["d0c00001-dock", "d0c00002-umbenannt",
                                     "d0c00003-gross", "d0c00005-lang"]
                   and "7e700004-terminal" in [e["id"] for e in alle],
                   (sorted(namen), [e["id"] for e in alle]))
    r["bezeichnung"] = (namen.get("d0c00001-dock") == "Wand im Obergeschoss"
                        and namen.get("d0c00002-umbenannt") == "Umbenannt"
                        and C.SITZUNG_NAME not in namen.values(), namen)
    zaehler = _Lesezaehler()
    C.open = zaehler.open
    try:
        verlauf = C.sitzung_verlauf(SITZUNGS_ORDNER, "d0c00003-gross")
        klein = C.sitzung_verlauf(SITZUNGS_ORDNER, "d0c00001-dock")
        lang = C.sitzung_verlauf(SITZUNGS_ORDNER, "d0c00005-lang")
        fremd = [C.sitzung_verlauf(SITZUNGS_ORDNER, k)
                 for k in ("..\\geheim", "../geheim", "", None)]
    finally:
        del C.open
    gelesen = zaehler.bytes.get(pfade["gross"], 0)
    groesse = os.path.getsize(pfade["gross"])
    r["verlauf_fenster"] = (0 < gelesen <= C.SCHWANZ_BYTES < groesse,
                            (gelesen, groesse))
    arten = [(e.get("art"), e.get("text") or e.get("werkzeug"))
             for e in verlauf[-4:]]
    r["verlauf_inhalt"] = (arten == [("ich", "Und jetzt die Tür"),
                                     ("text", "Die Tür steht."),
                                     ("werkzeug", "Read"),
                                     ("text", "Fertig.")]
                           and all(e.get("alt") for e in verlauf), arten)
    r["verlauf_hinweis"] = (
        verlauf[:1] and verlauf[0].get("art") == "hinweis"
        and len(verlauf) == C.VERLAUF_ALT_MAX + 1
        and [e.get("art") for e in klein] == ["ich", "text"], (
            verlauf[:1], len(verlauf), [e.get("art") for e in klein]))
    r["verlauf_rand"] = (
        [e.get("art") for e in lang] == ["hinweis", "ich", "text"],
        [(e.get("art"), e.get("text")) for e in lang])
    r["verlauf_fremd"] = (fremd == [[], [], [], []], fremd)
    # Belegt (Nacharbeit D): die Vermerke legt `_dock_liste` an.
    belegt = {e["id"]: e.get("belegt")
              for e in C.sitzungen(SITZUNGS_ORDNER, {}, nur_dock=True)}
    r["belegt_fremd"] = (belegt.get("d0c00001-dock") is True, belegt)
    r["belegt_tot"] = (belegt.get("d0c00002-umbenannt") is False
                       and belegt.get("d0c00005-lang") is False, belegt)
    r["belegt_neu_vergeben"] = (belegt.get("d0c00003-gross") is False, belegt)
    eigen = pfade.get("eigen")
    r["belegt_eigen"] = (bool(eigen) and not C.sitzung_belegt(eigen)
                         and C.sitzung_belegt(eigen, ich=-1),
                         (C.sitzung_belegt(eigen), C.sitzung_belegt(
                             eigen, ich=-1)) if eigen else None)
    return r


def _dock_liste(chat_pfad):
    """P9 Etappe D: Ordnernamen wie gemessen, nur Dock-Sitzungen, alter
    Verlauf. Kontrollen: Mutanten aus der Quelle."""
    import shutil as _sh
    import tempfile as _tf
    heim = _tf.mkdtemp(prefix="omcad_p9_dock_")
    alt = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = heim
    os.environ.pop("HOME", None)
    alt_belegt = os.environ.get("OPEN_MCP_CAD_BELEGT")
    os.environ["OPEN_MCP_CAD_BELEGT"] = os.path.join(heim, "belegt")
    kind = None
    try:
        C, _t = _chat_variante(chat_pfad, name="p9_dock")
        pfade = _dock_sitzungen_anlegen(heim, C)
        kind, pfade["eigen"] = _vermerke_anlegen(heim)
        echt = _dock_messen(C, heim, pfade)
        for zelle, text in (
                ("gemessen", "Ordnernamen wie am echten CLI gemessen: ueber "
                             "200 Zeichen gekuerzt mit Pruefsumme, ein Emoji "
                             "zaehlt doppelt"),
                ("filter", "die Chatliste zeigt nur Sitzungen, die das Dock "
                           "angelegt hat (auch umbenannte und grosse)"),
                ("bezeichnung", "die Kennzeichnung ist kein Titel: es gilt "
                                "die erste Frage bzw. ein neuer Titel"),
                ("verlauf_fenster", "der alte Verlauf liest nur das Ende "
                                    "einer grossen Datei"),
                ("verlauf_inhalt", "der alte Verlauf: eigene Fragen, "
                                   "Antworten, Werkzeuge; ohne Ergebnisse, "
                                   "Meta, Nebenfaeden, Befehle; alles 'alt'"),
                ("verlauf_hinweis", "fehlt etwas davor, steht vorne ein "
                                    "Hinweis; eine kleine Datei ganz"),
                ("verlauf_rand", "eine grosse Datei mit wenigen Nachrichten "
                                 "im Schwanz: vorne der Hinweis"),
                ("verlauf_fremd", "eine Kennung, die aus dem Ordner fuehrt, "
                                  "liest nichts"),
                ("belegt_fremd", "ein Chat, den ein lebender Prozess eines "
                                 "anderen Cadwork fuehrt, ist 'belegt'"),
                ("belegt_tot", "der Vermerk eines beendeten Prozesses gilt "
                               "nicht, ohne Vermerk nichts belegt"),
                ("belegt_neu_vergeben", "eine neu vergebene PID (Prozess "
                                        "nach dem Vermerk gestartet) gilt "
                                        "nicht"),
                ("belegt_eigen", "der Vermerk des EIGENEN Cadwork sperrt "
                                 "nicht (den eigenen Chat haelt "
                                 "voriger_laeuft auf)")):
            pruefe("P9 " + text, echt[zelle][0], echt[zelle][1])
        mutanten = (
            ("gemessen", "ohne Kuerzung",
             [("    if len(marke) > PROJEKT_NAME_MAX:",
               "    if False:")]),
            ("gemessen", "je Zeichen statt je UTF-16-Einheit",
             [("    einheiten = _utf16(arbeitsordner)",
               "    einheiten = [ord(c) for c in arbeitsordner]")]),
            ("gemessen", "ohne Vorzeichen (32 Bit ohne Umrechnung)",
             [("    if h >= 0x80000000:\n        h -= 0x100000000\n", "")]),
            ("filter", "kein Filter",
             [('        if nur_dock and not eintrag.get("dock"):',
               "        if False:")]),
            ("filter", "Kennzeichnung nur im Schwanz gesucht",
             [("    for block in (kopf, schwanz):\n"
               "        if any(w == SITZUNG_NAME",
               "    for block in (schwanz,):\n"
               "        if any(w == SITZUNG_NAME")]),
            ("bezeichnung", "die Kennzeichnung als Titel",
             [("                if wert != SITZUNG_NAME:",
               "                if True:")]),
            ("verlauf_fenster", "die ganze Datei lesen",
             [("            anfang = max(0, groesse - SCHWANZ_BYTES)",
               "            anfang = 0")]),
            ("verlauf_inhalt", "Nebenfaeden mitlesen",
             [('        if not isinstance(ev, dict) or ev.get("isSidechain")',
               '        if not isinstance(ev, dict)')]),
            ("verlauf_hinweis", "ohne Hoechstzahl",
             [("            + aus[-hoechstens:]", "            + aus")]),
            ("verlauf_rand", "Hinweis nur ueber der Hoechstzahl",
             [("    if len(aus) > hoechstens or (anfang > 0 and aus):",
               "    if len(aus) > hoechstens:")]),
            ("verlauf_fremd", "ohne Pruefung der Kennung",
             [("    if not isinstance(sitzung, str) or not "
               "_SITZUNG_ID.match(sitzung):\n        return []",
               "    if not isinstance(sitzung, str):\n        return []")]),
            ("belegt_fremd", "die Liste traegt 'belegt' nicht",
             [('        kopie["belegt"] = sitzung_belegt(kopie["id"])',
               '        kopie["belegt"] = False')]),
            ("belegt_tot", "jeder Vermerk gilt, auch der eines toten "
                           "Prozesses",
             [('    return _prozess_lebt(v.get("pid"), v.get("seit"))',
               "    return True")]),
            ("belegt_neu_vergeben", "ohne Vergleich der Startzeit",
             [("            return gestartet <= seit + BELEGT_TOLERANZ_S",
               "            return True")]),
            ("belegt_eigen", "auch der eigene Vermerk sperrt",
             [('    if v.get("besitzer") == (os.getpid() if ich is None '
               'else ich):', "    if False:")]),
        )
        for zelle, was, ersetzungen in mutanten:
            M, treffer = _chat_variante(chat_pfad, ersetzungen,
                                        name="p9_dock_mut")
            m = _dock_messen(M, heim, pfade)
            pruefe("P9 KONTROLLE (%s): %s -> rot" % (zelle, was),
                   treffer == [1] and not m[zelle][0],
                   repr((treffer, m[zelle])))
    finally:
        if kind is not None:
            kind.kill()
            kind.wait()
        if alt_belegt is None:
            os.environ.pop("OPEN_MCP_CAD_BELEGT", None)
        else:
            os.environ["OPEN_MCP_CAD_BELEGT"] = alt_belegt
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _sh.rmtree(heim, ignore_errors=True)


def _vermerke_anlegen(heim):
    """Vermerke, wie `_belegen` sie schreibt (Nacharbeit D): ein lebender
    Prozess eines ANDEREN Cadwork (ein echtes Python-Kind), ein beendeter,
    eine neu vergebene PID (Vermerk aelter als der Prozess) und einer des
    eigenen Cadwork. -> (Kind, Kennung des eigenen)."""
    import json as _json
    import subprocess as _sp
    import time as _t
    ordner = os.environ["OPEN_MCP_CAD_BELEGT"]
    os.makedirs(ordner, exist_ok=True)
    kind = _sp.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    tot = _sp.Popen([sys.executable, "-c", "pass"])
    tot.wait()
    jetzt = _t.time()

    def vermerk(kennung, pid, seit, besitzer):
        with open(os.path.join(ordner, kennung + ".json"), "w",
                  encoding="utf-8") as fh:
            _json.dump({"sitzung": kennung, "pid": pid, "seit": seit,
                        "besitzer": besitzer}, fh)
    fremd = os.getpid() + 1
    vermerk("d0c00001-dock", kind.pid, jetzt, fremd)
    vermerk("d0c00002-umbenannt", tot.pid, jetzt, fremd)
    vermerk("d0c00003-gross", kind.pid, jetzt - 3600, fremd)
    vermerk("e16e0001-eigen", kind.pid, jetzt, os.getpid())
    return kind, "e16e0001-eigen"

# --- S4: Arbeitsordner, Rangfolge — ausgefuehrt, nicht gegrept -----------

def _ordner_rangfolge(dash):
    """P9 Rangfolge (Entscheid 2026-09-26): OPEN_MCP_CAD_PROJEKT vor der
    Wahl im Dock vor projektordner.txt, ohne Ordner None. Der Abschnitt des
    Dashboards laeuft mit einem Temp-Pluginordner (projektordner.txt).
    Kontrollen: Mutanten desselben Abschnitts aus der Quelle."""
    import shutil as _sh
    import tempfile as _tf
    wurzel = _tf.mkdtemp(prefix="omcad_p9_ordner_")
    plugin = os.path.join(wurzel, "plugin")
    umg, wahl, datei = (os.path.join(wurzel, n)
                        for n in ("umg", "wahl", "datei"))
    for o in (plugin, umg, wahl, datei):
        os.makedirs(o)
    fehlt = os.path.join(wurzel, "gibt_es_nicht")
    alt = os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)

    def messen(quelltext):
        ao = _arbeitsordner_laden(quelltext, plugin)
        if ao is None:
            return None
        faelle = []
        for env, w, txt, soll in (
                (umg, wahl, datei, umg),       # 1 vor 2 vor 3
                (None, wahl, datei, wahl),     # 2 vor 3
                (None, None, datei, datei),    # 3
                (None, fehlt, datei, datei),   # Wahl ohne Ordner zaehlt nicht
                (fehlt, wahl, None, wahl),     # Umgebung ohne Ordner ebenso
                (None, None, None, None),      # nichts -> None, nie raten
                (None, fehlt, None, None)):
            if env is None:
                os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
            else:
                os.environ["OPEN_MCP_CAD_PROJEKT"] = env
            txt_pfad = os.path.join(plugin, "projektordner.txt")
            if txt is None:
                if os.path.exists(txt_pfad):
                    os.remove(txt_pfad)
            else:
                with io.open(txt_pfad, "w", encoding="utf-8") as fh:
                    fh.write('"%s"\n' % txt)
            try:
                ist = ao(w)
            except Exception as exc:                   # noqa: BLE001
                ist = "wirft %s" % type(exc).__name__
            faelle.append((soll, ist))
        return faelle

    try:
        echt = messen(dash)
        pruefe("P9 der Arbeitsordner-Abschnitt laeuft mit nichts als os und "
               "_HIER (und nimmt die Wahl als Parameter)", echt is not None)
        if echt is None:
            return
        falsch = [f for f in echt if f[0] != f[1]]
        pruefe("P9 Rangfolge: Umgebung vor Dock-Wahl vor projektordner.txt, "
               "nur vorhandene Ordner, ohne Angabe None",
               not falsch, repr(falsch))
        wahl_zeilen = ("    if isinstance(wahl, str) and wahl and "
                       "os.path.isdir(wahl):\n        return wahl\n")
        umg_zeilen = ('    gesetzt = os.environ.get("OPEN_MCP_CAD_PROJEKT")\n'
                      '    if gesetzt and os.path.isdir(gesetzt):\n'
                      '        return gesetzt\n')
        for was, alt_t, neu_t in (
                ("die Wahl wird uebergangen", wahl_zeilen, ""),
                ("die Wahl sticht die Umgebung",
                 umg_zeilen + wahl_zeilen, wahl_zeilen + umg_zeilen)):
            m = messen(dash.replace(alt_t, neu_t)) or []
            pruefe("P9 KONTROLLE: %s -> Rangfolge rot" % was,
                   dash.count(alt_t) == 1
                   and any(f[0] != f[1] for f in m), repr(m))
    finally:
        os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        if alt is not None:
            os.environ["OPEN_MCP_CAD_PROJEKT"] = alt
        _sh.rmtree(wurzel, ignore_errors=True)


# --- Sicherheitskorrektur: der Satz zum Modus (seit 2026-09-27) -----------

def _server_werkzeuge(C):
    """Die Werkzeuge aus open_mcp_cad/server.py (dekorierte Funktionen), so
    benannt, wie der Chat sie sieht. Aus der QUELLE, keine eigene Liste."""
    with io.open(os.path.join(REPO, "open_mcp_cad", "server.py"),
                 encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    return [C.MCP_PRAEFIX + "__" + f.name for f in ast.walk(baum)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any("mcp.tool" in ast.unparse(d) for d in f.decorator_list)]


#: Was "aussen" in den Saetzen meint: Befehle am Rechner, Dateien, Web.
_AUSSEN = ("Bash", "PowerShell", "Write", "Edit", "NotebookEdit", "WebFetch",
           "WebSearch")


def modus_hinweis_falsch(hinweis, C):
    """-> Liste der Modi, deren Satz nicht zum Verhalten passt.

    Modi aus C.MODI, Verhalten aus C.entscheiden, Cadwork-Werkzeuge aus
    server.py (die aendern: `ist_cadwork`), lesende aus server.py und
    NUR_LESEND. Der Satz muss sagen: ob Lesen ohne Frage laeuft, ob Cadwork
    ohne Frage laeuft, ob Aendern und Aeusseres abgelehnt werden, ob
    gefragt wird und ob einmal je Art.
    """
    server = _server_werkzeuge(C)
    cad = [t for t in server if C.ist_cadwork(t)]
    lesend = ([t for t in server if C.werkzeug_art(t) == "lesen"]
              + sorted(C.NUR_LESEND))
    falsch = []
    for modus in C.MODUS_WERTE:
        text = (hinweis(modus) or "").lower()

        def alle(gruppe, urteil, gewaehrt=()):
            return all(C.entscheiden(modus, t, None, gewaehrt) == urteil
                       for t in gruppe)
        fragend = [t for t in cad + list(_AUSSEN)
                   if C.entscheiden(modus, t) == "fragen"]
        soll = {
            "warnt": alle(cad, "ja") and alle(_AUSSEN, "ja"),
            "lesen frei": alle(lesend, "ja"),
            "cadwork frei": alle(cad, "ja") and not alle(_AUSSEN, "ja"),
            "abgelehnt": alle(cad, "nein") and alle(_AUSSEN, "nein"),
            "fragt": alle(cad, "fragen") and alle(_AUSSEN, "fragen"),
            # Genuegt EINE Freigabe je Art fuer alles, was fragt?
            "je art": bool(fragend) and all(
                C.entscheiden(modus, t, None, {t}) == "ja" for t in fragend),
        }
        ist = {
            "warnt": text.startswith("achtung") and "nichts wird gefragt"
            in text,
            "lesen frei": "lesen und nachschlagen laufen ohne rückfrage"
            in text or text.startswith("achtung"),
            "cadwork frei": "cadwork-befehle laufen ohne rückfrage" in text,
            "abgelehnt": "abgelehnt, ohne zu fragen" in text,
            "fragt": "vor jeder änderung wird gefragt" in text,
            "je art": "einmal je art" in text,
        }
        if soll != ist:
            falsch.append((modus, {k for k in soll if soll[k] != ist[k]},
                           text[:80]))
    return falsch


def _kern_methoden():
    """`MODELL_METHODEN` aus der Quelle des Kerns — was in seiner
    Auftragsliste stehen kann."""
    with io.open(KERN, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    for k in baum.body:
        if isinstance(k, ast.Assign) and any(
                getattr(t, "id", None) == "MODELL_METHODEN" for t in k.targets):
            return list(ast.literal_eval(k.value))
    return []


def schritte_ohne_namen(D, C):
    """-> Werkzeuge (server.py) und Kern-Methoden, fuer die der Verlauf nur
    die Ersatzform haette (lesbar gemachter Name, Symbol SCHRITT_ANDERES).
    Gefragt wird `_schritt_eintrag` wie beim Zeichnen, nicht die Tabelle
    direkt (seit K9 ohne Emoji-Praefix, an dem man es vorher erkannte)."""
    fehlt = [t for t in _server_werkzeuge(C)
             if D._schritt_eintrag(t, C=C)[1] is None]
    fehlt += [m for m in _kern_methoden()
              if D._schritt_eintrag(m)[1] is None]
    return fehlt


#: Werkzeugnamen von Erweiterungen (neutral, seit 2026-10-01): je Name, ob
#: die Politik ihn lesend nennt. Der technische Name darf nie im Text stehen.
ERW_NAMEN = (("lesen_probe_pruefen", True), ("lesen_probe_nachlesen", True),
             ("probe_bauen", False), ("probe_zuweisen", False),
             ("lesen__probe", False), ("lesen_", False))


def _erw_texte(D, C):
    """-> [(Name, Text, Symbol, lesend laut Politik)] fuer ERW_NAMEN, im
    Steckplatz ohne und mit Kennung (open-mcp-cad-b)."""
    aus = []
    for server in ("open-mcp-cad", "open-mcp-cad-b"):
        for name, _l in ERW_NAMEN:
            voll = "mcp__%s__%s" % (server, name)
            aus.append((voll, D._schritt_text(voll, C=C),
                        D._schritt_symbol(voll, C),
                        C.werkzeug_art(voll) == "lesen"))
    return aus


def _erw_falsch(D, C):
    falsch = []
    for voll, text, symbol, lesend in _erw_texte(D, C):
        soll = D.SCHRITT_ERWEITERUNG_LESEN if lesend             else D.SCHRITT_ERWEITERUNG
        if (symbol, text) != soll or "probe" in text.lower():
            falsch.append((voll, text, symbol))
    return falsch


def erweiterungen_lesbar(D, C):
    """P14e (seit 2026-10-01): ein Werkzeug einer Erweiterung (Werkzeug
    DIESES Servers, nicht in SCHRITTE) bekommt im Verlauf einen neutralen
    Satz — lesend oder aendernd wie die Politik —, nie seinen technischen
    Namen; ein fremder Server bleibt, wie er war."""
    falsch = _erw_falsch(D, C)
    lesend = [v for v, _t, _s, l in _erw_texte(D, C) if l]
    pruefe("P14e Werkzeuge einer Erweiterung: neutraler Satz und Symbol je "
           "Einstufung (lesend genau die mit gueltigem lesen_-Namen), nie "
           "der technische Name", not falsch and len(lesend) == 4, falsch)
    fremd = D._schritt_text("mcp__fremd__probe_bauen", C=C)
    pruefe("P14e ein fremder Server ist keine Erweiterung (lesbar, mit "
           "Server)", fremd == "Probe bauen (fremd)", fremd)
    alt = D._schritt_erweiterung
    D._schritt_erweiterung = lambda *a, **k: None
    try:
        k = _erw_falsch(D, C)
    finally:
        D._schritt_erweiterung = alt
    pruefe("P14e KONTROLLE: ohne die neutrale Form stuende der technische "
           "Name im Verlauf", len(k) == len(_erw_texte(D, C))
           and any("probe" in t.lower() for _v, t, _s in k), k[:3])
    # Ohne Unterschied lesend/aendernd (immer der Satz der aendernden)
    # fallen genau die vier lesenden auf.
    alt_lesen = D.SCHRITT_ERWEITERUNG_LESEN
    D.SCHRITT_ERWEITERUNG_LESEN = D.SCHRITT_ERWEITERUNG
    try:
        k2 = [v for v, _t, _s in _erw_falsch_gegen(D, C, alt_lesen)]
    finally:
        D.SCHRITT_ERWEITERUNG_LESEN = alt_lesen
    pruefe("P14e KONTROLLE: ein Satz fuer alle (ohne die Einstufung) faellt "
           "an den vier lesenden auf", len(k2) == 4
           and all("lesen_probe" in v for v in k2), k2)


def _erw_falsch_gegen(D, C, soll_lesen):
    """Wie _erw_falsch, aber gegen einen festen Soll-Satz fuer lesende."""
    falsch = []
    for voll, text, symbol, lesend in _erw_texte(D, C):
        soll = soll_lesen if lesend else D.SCHRITT_ERWEITERUNG
        if (symbol, text) != soll:
            falsch.append((voll, text, symbol))
    return falsch


def _lesbar_pruefen(D, C):
    """P14 (K5, Wunsch 2026-09-27): EINE Tabelle macht aus Werkzeugen
    Saetze; Zeitangaben relativ und immer groeber. Der gebaute Verlauf:
    test_a_live L71."""
    import datetime
    server, kern = _server_werkzeuge(C), _kern_methoden()
    pruefe("P14 Vorbedingung: server.py und der Kern nennen Werkzeuge bzw. "
           "Methoden", len(server) >= 20 and len(kern) >= 5,
           (len(server), kern))
    fehlt = schritte_ohne_namen(D, C)
    pruefe("P14 jedes Werkzeug von server.py und jede Methode der "
           "Auftragsliste hat einen menschlichen Namen", not fehlt, fehlt)
    for weg in ("wait_for_bridge", "neu_zeichnen"):
        alt = D.SCHRITTE.pop(weg)
        try:
            k = schritte_ohne_namen(D, C)
        finally:
            D.SCHRITTE[weg] = alt
        pruefe("P14 KONTROLLE: ohne '%s' in der Tabelle faellt es auf" % weg,
               any(x.endswith(weg) for x in k), k)
    pfx = C.MCP_PRAEFIX + "__"
    faelle = [
        (D._schritt_text(pfx + "get_document_info", C=C),
         "Dokument angeschaut"),
        (D._schritt_text("mcp__fremd__get_document_info", C=C),
         "Get document info (fremd)"),
        (D._schritt_text(pfx + "ganz_neues_werkzeug", C=C),
         D.SCHRITT_ERWEITERUNG[1]),
        (D._schritt_text(pfx + "execute_cadwork_batch", paket=(3, 8), C=C),
         "Zeichnet (Paket 3 von 8)"),
        (D._schritt_text(pfx + "execute_cadwork_command",
                         {"description": "Wand  Nord"}, C=C), "Wand Nord"),
        (D._schritt_text("Read"), "Datei gelesen"),
        # Seit K9 das Symbol getrennt vom Text (keine Emoji mehr).
        (D._schritt_symbol(pfx + "get_document_info", C), "file-text"),
        (D._schritt_symbol("mcp__fremd__get_document_info", C),
         D.SCHRITT_ANDERES),
        (D._schritt_symbol(pfx + "execute_cadwork_command", C), "hammer"),
    ]
    pruefe("P14 Namen: eigene aus der Tabelle, ein fremder Server mit "
           "gleichem Namen NICHT (lesbar, mit Server), Paket, Beschreibung",
           all(a == b for a, b in faelle), faelle)
    erweiterungen_lesbar(D, C)
    j = datetime.datetime(2026, 9, 27, 15, 0).timestamp()
    zeiten = [
        (j - 30, "gerade eben"), (j - 59, "gerade eben"), (j - 60, "vor 1 min"),
        (j - 9 * 60, "vor 9 min"), (j - 42 * 60, "vor 40 min"),
        (j - 59 * 60, "vor 55 min"), (j - 7200, "heute 13:00"),
        (datetime.datetime(2026, 9, 26, 17, 40).timestamp(), "gestern 17:40"),
        (datetime.datetime(2026, 9, 12, 8, 15).timestamp(), "12.09. 08:15"),
        (datetime.datetime(2025, 12, 31, 9, 0).timestamp(), "31.12.2025"),
        (j + 100, "gerade eben"), (None, "")]
    falsch = [(t, soll, D._zeit_text(t, j)) for t, soll in zeiten
              if D._zeit_text(t, j) != soll]
    pruefe("P14 Zeitangaben: gerade eben, vor N min (ab 10 min in 5er-"
           "Schritten), heute, gestern, Datum", not falsch, falsch)
    ev = [{"art": "ich", "text": "a"},
          {"art": "werkzeug", "werkzeug": "Write", "eingabe": {}, "id": "w1"},
          {"art": "verweigert", "werkzeug": "Write", "eingabe": {},
           "id": "w1", "modus": "nur_lesen"},
          {"art": "text", "text": "b"}]
    b1 = D._verlauf_bloecke(ev, j, C=C)
    b2 = D._verlauf_bloecke(ev + [{"art": "werkzeug", "werkzeug": "Read",
                                   "eingabe": {}, "id": "r1"}], j, C=C)
    pruefe("P14 Bloecke: ohne Zeit keine Zeitlinie, eine fremde Gruppe "
           "heisst nicht 'in Cadwork', die Ablehnung nennt den Modus",
           [b["art"] for b in b1] == ["ich", "schritte", "ki"]
           and b1[1]["kopf"] == "1 Schritt · 1 abgelehnt"
           and b1[1]["zeilen"][0][0]
           == "Datei geschrieben — abgelehnt (Modus «Nur lesen»)"
           and b1[1]["symbole"] == ["ban"] and b1[1]["warnung"] is True, b1)
    pruefe("P14 Bloecke: Neues aendert die Schluessel der alten nicht",
           [b["schluessel"] for b in b2[:3]]
           == [b["schluessel"] for b in b1], (b1, b2))


def _modus_hinweis_pruefen(D, C, dash_pfad):
    """P12 (2026-09-26, seit 2026-09-27 fuer die Modi): der Satz zum Modus
    stimmt fuer JEDEN Modus mit der Politik ueberein. Das gebaute Dock:
    test_a_live L47."""
    server = _server_werkzeuge(C)
    pruefe("P12 Vorbedingung: server.py nennt Werkzeuge, darunter aendernde "
           "und lesende", len(server) >= 10
           and any(C.ist_cadwork(t) for t in server)
           and any(C.werkzeug_art(t) == "lesen" for t in server), len(server))
    falsch = modus_hinweis_falsch(lambda m: D._modus_hinweis(m, C), C)
    pruefe("P12 der Satz sagt je Modus, was ohne Frage laeuft, was abgelehnt "
           "wird und was fragt — wie C.entscheiden", not falsch, repr(falsch))
    pruefe("P12 bei 'Alles automatisch' warnt er ausdruecklich",
           D._modus_hinweis("alles_auto", C).startswith("Achtung"),
           D._modus_hinweis("alles_auto", C))
    with io.open(dash_pfad, encoding="utf-8") as fh:
        quelle = fh.read()
    for was, alt_t, neu_t in (
            ("der feste Text von vorher",
             "def _modus_hinweis(modus, C):\n",
             "def _modus_hinweis(modus, C):\n    return %r\n"
             % "Cadwork-Werkzeuge fragen IMMER."),
            ("mit einem Lese-Werkzeug statt Cadwork gefragt",
             '        cad = C.MCP_PRAEFIX + "__execute_cadwork_command"\n',
             '        cad = "Read"\n'),
            ("'einmal je Art' ohne Blick auf die Gewaehrung",
             "        je_art = bool(fragend) and all(\n",
             "        je_art = True or all(\n")):
        m = type(sys)("p12_mutant")
        m.__file__ = dash_pfad
        exec(compile(quelle.replace(alt_t, neu_t), dash_pfad, "exec"),
             m.__dict__)
        # Die dritte Mutante zeigt sich erst an einer Politik, in der eine
        # Gewaehrung NICHT gilt (sonst stimmt "einmal je Art" zufaellig).
        C_p = C
        if "Gewaehrung" in was:
            C_p = type(sys)("p12_ohne_gewaehrung")
            C_p.__dict__.update(C.__dict__)
            C_p.entscheiden = (lambda modus, w, a=None, g=(): C.entscheiden(
                modus, w, a, ()))
        k = modus_hinweis_falsch(lambda md: m._modus_hinweis(md, C_p), C_p)
        pruefe("P12 KONTROLLE: %s -> rot" % was,
               quelle.count(alt_t) == 1 and k, repr(k))

    class _Kaputt:
        """Ein Chat-Modul, dessen Politik sich nicht erfragen laesst."""
        MCP_PRAEFIX = C.MCP_PRAEFIX

        @staticmethod
        def entscheiden(*_a):
            raise RuntimeError("alt")
    t = D._modus_hinweis("fragen", _Kaputt)
    pruefe("P12 laesst sich das Verhalten nicht erfragen, verspricht der "
           "Satz nichts", "rückfrage" not in t.lower()
           and "gefragt" not in t.lower(), t)
    pruefe("P12 KONTROLLE: mit der echten Politik verspricht er etwas",
           "gefragt" in D._modus_hinweis("fragen", C).lower())


# --- S4: Ordnerwahl und Zeichenmodus in chat.json -------------------------

def _gemerkte_orte(D, C, pfad):
    """P10b (S4, 2026-09-26): Arbeitsordner und Zeichenmodus in chat.json —
    kaputte Werte werden nie genommen, das Merken laesst die anderen
    Eintraege stehen, und die Freigabe kommt weiter nie hinein. `pfad` ist
    die Temp-chat.json aus P10."""
    import json as _json
    import tempfile as _tf

    def lesen():
        try:
            with io.open(pfad, encoding="utf-8") as fh:
                return _json.load(fh)
        except (OSError, ValueError):
            return None
    ordner = _tf.mkdtemp(prefix="omcad_p10_ordner_")
    kaputt = [None, [], "x", {"arbeitsordner": 7},
              {"arbeitsordner": ["C:\\"]}, {"arbeitsordner": ""},
              {"arbeitsordner": "relativ\\ordner"},
              {"arbeitsordner": ordner + "\n"},
              {"arbeitsordner": "C:\\" + "o" * (D.ORDNERPFAD_MAX + 1)}]
    falsch = [e for e in kaputt if D._gemerkter_ordner(e) is not None]
    pruefe("P10b kaputte Ordnerangaben in chat.json gelten nicht",
           not falsch, repr(falsch[:2]))

    # Die Laengengrenze mit festen Zahlen, NICHT aus der Konstante der
    # geprueften Quelle: sonst waere jede Grenze (auch 10**9) "richtig".
    def lang(n):
        return {"arbeitsordner": "C:\\" + "o" * (n - 3)}

    def laengen_urteil(M):
        return (M._gemerkter_ordner(lang(260)) is not None,
                M._gemerkter_ordner(lang(5000)) is None,
                M._gemerkter_ordner(lang(200000)) is None)
    pruefe("P10b ein Pfad von 260 Zeichen gilt, 5000 und 200000 nicht",
           laengen_urteil(D) == (True, True, True), laengen_urteil(D))
    with io.open(D.__file__, encoding="utf-8") as fh:
        quelle = fh.read()
    alt_t = "\nORDNERPFAD_MAX = 1024\n"
    m = type(sys)("p10b_mutant")
    m.__file__ = D.__file__
    exec(compile(quelle.replace(alt_t, "\nORDNERPFAD_MAX = 10 ** 9\n"),
                 D.__file__, "exec"), m.__dict__)
    pruefe("P10b KONTROLLE: Grenze 10**9 -> rot",
           quelle.count(alt_t) == 1
           and laengen_urteil(m) != (True, True, True), laengen_urteil(m))
    pruefe("P10b KONTROLLE: ein absoluter Pfad wird genommen (auch einer, "
           "den es gerade nicht gibt — ob er gilt, sagt arbeitsordner)",
           D._gemerkter_ordner({"arbeitsordner": ordner}) == ordner
           and D._gemerkter_ordner({"arbeitsordner": ordner + "_weg"})
           == ordner + "_weg")
    stufen = ({"schluessel": "auto"}, {"schluessel": "langsam"})
    kaputt = [None, {}, {"zeichenmodus": "turbo"}, {"zeichenmodus": 1},
              {"zeichenmodus": ["auto"]}, {"zeichenmodus": None}]
    falsch = [e for e in kaputt if D._gemerkter_zeichenmodus(e, stufen)
              is not None]
    pruefe("P10b ein Zeichenmodus, den der Kern nicht kennt, gilt nicht",
           not falsch and D._gemerkter_zeichenmodus(
               {"zeichenmodus": "langsam"}, ()) is None, repr(falsch))
    pruefe("P10b KONTROLLE: einer aus ZEICHENMODI wird genommen",
           D._gemerkter_zeichenmodus({"zeichenmodus": "langsam"}, stufen)
           == "langsam")

    # Merken: in eine Datei mit fremden Eintraegen, die stehen bleiben.
    with io.open(pfad, "w", encoding="utf-8") as fh:
        _json.dump({"anbieter": "openai", "denkstufe": "high"}, fh)
    z = {"w": {}, "chat": {"modus": "alles_auto"}}
    a = D._ordner_merken(z, ordner)
    b = D._zeichenmodus_merken("langsam")
    inhalt = lesen() or {}
    pruefe("P10b Ordner und Zeichenmodus werden gemerkt, der Rest bleibt",
           a and b and z.get("ordner_wahl") == ordner
           and inhalt == {"anbieter": "openai", "denkstufe": "high",
                          "arbeitsordner": ordner,
                          # K3: die zuletzt benutzten fuers Ordner-Menue
                          "ordner_zuletzt": [ordner],
                          "zeichenmodus": "langsam"}, repr(inhalt))
    pruefe("P10b ... und kein Modus, obwohl der Chat auf 'Alles "
           "automatisch' steht", "auto" not in _json.dumps(inhalt)
           and "modus" not in inhalt, repr(inhalt))
    pruefe("P10b KONTROLLE: unveraendert wird nicht erneut geschrieben",
           D._ordner_merken(z, ordner) is False
           and D._zeichenmodus_merken("langsam") is False)
    pruefe("P10b ein unbrauchbarer Ordner aendert nichts",
           D._ordner_merken(z, "relativ") is False
           and z.get("ordner_wahl") == ordner
           and (lesen() or {}).get("arbeitsordner") == ordner)
    pruefe("P10b _ordner_wahl liest den Zustand, nicht die Datei",
           D._ordner_wahl(z) == ordner and D._ordner_wahl({}) is None
           and D._ordner_wahl({"ordner_wahl": 5}) is None)
    pruefe("P10b None vergisst die Wahl",
           D._ordner_merken(z, None) and z.get("ordner_wahl") is None
           and "arbeitsordner" not in (lesen() or {}), repr(lesen()))
    os.rmdir(ordner)


def _lokal_laden(pfad=None, name="p13_lokal"):
    pfad = pfad or os.path.join(A, "omcad_a_lokal.py")
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _http_probe(status):
    """Ein HTTP-Dienst auf einem ephemeren Port AUSSERHALB des Cadwork-
    Bereichs, der jede GET-Anfrage mit `status` beantwortet. -> (Server,
    Basis-URL). Gebunden VOR listen() ueber `_ephemerer_socket`."""
    import http.server
    import threading

    class Antwort(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                            # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"models": []}')

        def log_message(self, *_a):
            pass

    sock = _ephemerer_socket()
    server = http.server.HTTPServer(sock.getsockname(), Antwort,
                                    bind_and_activate=False)
    server.socket.close()
    server.socket = sock
    server.server_activate()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % sock.getsockname()[1]


def _lokal_pruefen_offline():
    """P13: das Lokal-Modul (Ollama, LM Studio) ohne Qt — erkennen,
    Dienst fragen, Befehle bilden. Nichts wird gestartet: `AUSFUEHREN` ist
    eine Attrappe, und ein Stolperdraht auf `subprocess.Popen` meldet jeden
    Versuch, winget/ollama/lms echt zu starten."""
    import subprocess
    import time as _time
    quelle = lies(os.path.join(A, "omcad_a_lokal.py"))

    def importe(text):
        gefunden = set()
        for knoten in ast.walk(ast.parse(text)):
            if isinstance(knoten, ast.Import):
                gefunden.update(a.name.split(".")[0] for a in knoten.names)
            elif isinstance(knoten, ast.ImportFrom) and knoten.module:
                gefunden.add(knoten.module.split(".")[0])
        return gefunden
    verboten = {"PyQt6", "PyQt5", "omcad_qt", "cwapi3d", "element_controller",
                "utility_controller"}
    pruefe("P13 das Lokal-Modul importiert weder Qt noch cwapi3d",
           not (importe(quelle) & verboten), importe(quelle) & verboten)
    pruefe("P13 KONTROLLE: ein Qt-Import faellt auf",
           importe("from PyQt6.QtCore import Qt\n" + quelle) & verboten
           == {"PyQt6"})
    gefangen = []
    echt_popen = subprocess.Popen

    def draht(args, *a, **k):
        gefangen.append(list(args))
        raise OSError("Stolperdraht")
    subprocess.Popen = draht
    try:
        L = _lokal_laden()
        gestartet = []
        L.AUSFUEHREN = lambda befehl, fenster=False: gestartet.append(
            (befehl, fenster))
        # -- Erkennen: nur ueber WHICH/DATEI_DA/HOLEN, alle ersetzt --------
        auf_pfad = {}
        dateien = set()
        antwortet = {}
        L.WHICH = lambda n: auf_pfad.get(n)
        L.DATEI_DA = lambda p: p in dateien
        L.HOLEN = lambda url, timeout: antwortet.get(url, 0)
        leer = L.pruefen("ollama")
        pruefe("P13 nichts da: nicht installiert, laeuft nicht",
               leer == {"installiert": False, "programm": None, "app": None,
                        "laeuft": False}, leer)
        auf_pfad["ollama"] = r"C:\X\ollama.exe"
        da = L.pruefen("ollama")
        pruefe("P13 ollama auf dem PATH: installiert, Startbefehl 'serve'",
               da["installiert"] and not da["laeuft"]
               and L.start_befehl("ollama", da) == [r"C:\X\ollama.exe",
                                                   "serve"], da)
        antwortet[L.LOKAL["ollama"]["dienst"]] = 200
        pruefe("P13 Dienst antwortet 200: laeuft",
               L.pruefen("ollama")["laeuft"])
        # LM Studio nur als App (ohne lms): installiert, Start = die App
        app = os.path.expandvars(L.LOKAL["lmstudio"]["app"][0])
        dateien.add(app)
        lm = L.pruefen("lmstudio")
        pruefe("P13 LM Studio ohne 'lms': installiert, Start oeffnet die App",
               lm["installiert"] and lm["programm"] is None
               and L.start_befehl("lmstudio", lm) == [app], lm)
        auf_pfad["lms"] = r"C:\X\lms.exe"
        pruefe("P13 mit 'lms': Start ist 'lms server start'",
               L.start_befehl("lmstudio", L.pruefen("lmstudio"))
               == [r"C:\X\lms.exe", "server", "start"])
        # -- Befehle ------------------------------------------------------
        auf_pfad["winget"] = r"C:\W\winget.exe"
        L.installieren("ollama")
        L.installieren("lmstudio")
        L.starten("ollama", da)
        pruefe("P13 Installieren: winget mit genau der Paket-Kennung, ohne "
               "stilles Zustimmen, in eigenem Fenster; Starten ohne Fenster",
               gestartet == [
                   ([r"C:\W\winget.exe", "install", "--id", "Ollama.Ollama",
                     "--exact", "--source", "winget"], True),
                   ([r"C:\W\winget.exe", "install", "--id",
                     "ElementLabs.LMStudio", "--exact", "--source", "winget"],
                    True),
                   ([r"C:\X\ollama.exe", "serve"], False)]
               and not any("accept" in " ".join(b) for b, _f in gestartet),
               gestartet)
        del auf_pfad["winget"]
        del gestartet[:]
        try:
            L.installieren("ollama")
            fehler = None
        except L.LokalFehler as exc:
            fehler = str(exc)
        pruefe("P13 ohne winget: klare Meldung mit Download-Seite, nichts "
               "gestartet", fehler and "ollama.com" in fehler
               and gestartet == [], fehler)
        try:
            L.starten("ollama", {"programm": None, "app": None})
            fehler = None
        except L.LokalFehler as exc:
            fehler = str(exc)
        pruefe("P13 Starten ohne Programm: Meldung statt Aufruf",
               fehler and "nicht installiert" in fehler and gestartet == [],
               fehler)
        # -- Der ECHTE HTTP-Weg (`_holen`) gegen einen Dienst im Test ------
        L2 = _lokal_laden(name="p13_lokal_http")
        gut, url_gut = _http_probe(200)
        schlecht, url_schlecht = _http_probe(500)
        try:
            L2.LOKAL["ollama"]["dienst"] = url_gut + "/api/tags"
            L2.LOKAL["lmstudio"]["dienst"] = url_schlecht + "/v1/models"
            pruefe("P13 echter GET: ein Dienst mit 200 laeuft",
                   L2.dienst_laeuft("ollama"))
            pruefe("P13 KONTROLLE: ein Dienst mit 500 laeuft nicht",
                   not L2.dienst_laeuft("lmstudio"))
            port_zu = _ephemerer_socket()
            frei = port_zu.getsockname()[1]
            port_zu.close()
            L2.LOKAL["ollama"]["dienst"] = "http://127.0.0.1:%d/" % frei
            t0 = _time.monotonic()
            laeuft = L2.dienst_laeuft("ollama")
            dauer = _time.monotonic() - t0
            pruefe("P13 niemand am Port: nein, ohne Ausnahme, innerhalb der "
                   "Frist", not laeuft and dauer <= L2.DIENST_TIMEOUT_S + 1.0,
                   dauer)
            pruefe("P13 der Dienst-Test lief ausserhalb des Cadwork-Bereichs",
                   _ausserhalb([gut.server_address[1],
                                schlecht.server_address[1], frei]))
        finally:
            gut.shutdown()
            schlecht.shutdown()
        # -- Der echte Startweg laeuft in den Stolperdraht ----------------
        L3 = _lokal_laden(name="p13_lokal_echt")
        for befehl in (["ollama", "serve"], ["lms", "server", "start"]):
            try:
                L3.ausfuehren(befehl)
            except OSError:
                pass
        pruefe("P13 KONTROLLE: ohne Attrappe geht der Start an "
               "subprocess.Popen (hier: der Stolperdraht)",
               gefangen == [["ollama", "serve"], ["lms", "server", "start"]],
               gefangen)
    finally:
        subprocess.Popen = echt_popen
    _lokal_fensterflags()


def _flags_messen(L):
    """Den ECHTEN Startweg (`_ausfuehren_echt`) durchlaufen, aber an einem
    `subprocess` im Speicher, das nur mitschreibt: Installieren (winget) und
    Starten (ollama serve). -> [(Befehl, Schluesselwort-Argumente)]."""
    import subprocess
    import types as _types
    aufrufe = []

    class Popen:
        def __init__(self, args, **k):
            aufrufe.append((list(args), k))
            self.pid = 4711
    L.subprocess = _types.SimpleNamespace(Popen=Popen,
                                          DEVNULL=subprocess.DEVNULL)
    L.WHICH = lambda n: {"winget": r"C:\W\winget.exe"}.get(n)
    L.installieren("ollama")
    L.starten("ollama", {"programm": r"C:\X\ollama.exe"})
    return aufrufe


def _flags_urteil(aufrufe):
    """Was an den Fenstern falsch ist — gemessen an den Werten von Windows
    selbst (`subprocess.CREATE_…`), nicht an den Konstanten des Moduls."""
    import subprocess
    neu = subprocess.CREATE_NEW_CONSOLE
    still = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    fehler = []
    if [b[0] for b, _k in aufrufe] != [r"C:\W\winget.exe",
                                       r"C:\X\ollama.exe"]:
        return ["unerwartete Aufrufe: %r" % (aufrufe,)]
    (_b1, winget), (_b2, dienst) = aufrufe
    f1, f2 = winget.get("creationflags", 0), dienst.get("creationflags", 0)
    if not f1 & neu:
        fehler.append("winget ohne eigenes Konsolenfenster")
    if f1 & still:
        fehler.append("winget unsichtbar (DETACHED/NO_WINDOW)")
    if any(k in winget for k in ("stdin", "stdout", "stderr")):
        fehler.append("winget umgelenkt: nichts im Fenster zu sehen")
    if f2 & neu:
        fehler.append("Dienst mit Konsolenfenster")
    if (f2 & still) != still:
        fehler.append("Dienst nicht losgeloest ohne Fenster")
    if dienst.get("stdout") is not subprocess.DEVNULL:
        fehler.append("Dienst schreibt nach Cadwork")
    return fehler


def _lokal_fensterflags():
    """P13 (Pruefung 2026-09-26, Mutant R3): winget laeuft in einem EIGENEN,
    SICHTBAREN Fenster (dort stimmt der Nutzer selbst zu), der Dienst
    losgeloest OHNE Fenster. Gemessen an den `creationflags`, die wirklich
    an `subprocess.Popen` gehen — vorher prueften P13 und L53 nur das
    Argument `fenster=` an einer Attrappe."""
    import shutil
    import tempfile
    pruefe("P13 Fenster wirklich: winget sichtbar im eigenen Fenster, "
           "der Dienst losgeloest ohne Fenster",
           os.name == "nt" and _flags_urteil(_flags_messen(
               _lokal_laden(name="p13_flags"))) == [],
           _flags_urteil(_flags_messen(_lokal_laden(name="p13_flags_2"))))
    quelle = lies(os.path.join(A, "omcad_a_lokal.py"))
    alt = ("CREATE_NEW_CONSOLE if fenster\n"
           "            else DETACHED_PROCESS | CREATE_NO_WINDOW)")
    tausch = ("DETACHED_PROCESS | CREATE_NO_WINDOW if fenster\n"
              "            else CREATE_NEW_CONSOLE)")
    ordner = tempfile.mkdtemp(prefix="omcad_p13_flags_")
    pfad = os.path.join(ordner, "omcad_a_lokal.py")
    with open(pfad, "w", encoding="utf-8") as fh:
        fh.write(quelle.replace(alt, tausch))
    try:
        urteil = _flags_urteil(_flags_messen(_lokal_laden(pfad,
                                                          "p13_flags_m")))
    finally:
        shutil.rmtree(ordner, ignore_errors=True)
    pruefe("P13 KONTROLLE: mit vertauschten Fensterflags wird die Messung rot",
           quelle.count(alt) == 1 and len(urteil) >= 3, (quelle.count(alt),
                                                         urteil))


class _Url:
    def __init__(self, pfad):
        self.pfad = pfad

    def isLocalFile(self):                              # noqa: N802
        return True

    def toLocalFile(self):                              # noqa: N802
        return self.pfad


class _Mime:
    """Ein QMimeData ohne Qt: nur, was `_lokale_dateien` fragt."""

    def __init__(self, pfade):
        self.pfade = pfade

    def hasUrls(self):                                  # noqa: N802
        return bool(self.pfade)

    def urls(self):
        return [_Url(p) for p in self.pfade]


def _dash_mutant(dash_pfad, alt, neu, name):
    """Das Dashboard aus der Quelle mit `alt` -> `neu`. -> (Modul, Treffer)."""
    with io.open(dash_pfad, encoding="utf-8") as fh:
        text = fh.read()
    m = type(sys)(name)
    m.__file__ = dash_pfad
    exec(compile(text.replace(alt, neu), dash_pfad, "exec"), m.__dict__)
    return m, text.count(alt)


def _anhaenge_pruefen(D, dash_pfad):
    """P15 (Gegenpruefung 2026-09-28): ein Anhang ist ein Bild nach seinem
    INHALT (nicht der Endung), alle Anhaenge einer Nachricht zusammen haben
    eine Grenze, und das Ziehen fragt das Dateisystem nie im Qt-Thread."""
    import base64 as _b64
    import tempfile as _tf
    t = _tf.mkdtemp(prefix="omcad_p15_")
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 40
    png = _b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AA"
        "AAMBAQDJ/pLvAAAAAElFTkSuQmCC")
    dateien = {"foto.png": jpeg, "foto.jfif": jpeg, "echt.png": png,
               "kaputt.png": b"kein Bild, nur Text",
               "notiz.txt": "INHALT-15 Seeblick".encode("utf-8")}
    for name, roh in dateien.items():
        with io.open(os.path.join(t, name), "wb") as fh:
            fh.write(roh)
    os.makedirs(os.path.join(t, "ein ordner"))

    def lesen(M):
        aus = {}
        for name in list(dateien) + ["ein ordner"]:
            e = M._anhang_datei_lesen(os.path.join(t, name))
            aus[name] = (e.get("status"), e.get("art"), e.get("mime"))
        return aus
    r = lesen(D)
    pruefe("P15 ein JPEG heisst image/jpeg, auch als .png und als .jfif; ein "
           "echtes PNG image/png; Text mit Bild-Endung und ein Ordner sind "
           "Fehler; eine Textdatei bleibt Text",
           r == {"foto.png": ("bereit", "bild", "image/jpeg"),
                 "foto.jfif": ("bereit", "bild", "image/jpeg"),
                 "echt.png": ("bereit", "bild", "image/png"),
                 "kaputt.png": ("fehler", None, None),
                 "notiz.txt": ("bereit", "text", None),
                 "ein ordner": ("fehler", None, None)}, r)
    M, n = _dash_mutant(dash_pfad, "        mime = _bild_art(kopf)\n",
                        "        mime = BILD_TYPEN.get(endung)\n", "p15_mut")
    k = lesen(M)
    pruefe("P15 KONTROLLE: nach der Endung waere das JPEG ein 'image/png'",
           n == 1 and k["foto.png"] == ("bereit", "bild", "image/png"),
           (n, k.get("foto.png")))

    bild = {"art": "bild", "b64": "A" * 4000000}
    text = {"art": "text", "als_text": "x" * 150000}
    faelle = {"ein Bild": [bild], "sechs Bilder": [bild] * 6,
              "zwei Texte": [text] * 2, "drei Texte": [text] * 3, "nichts": []}
    urteil = {k_: bool(D._anhaenge_zu_gross(a)) for k_, a in faelle.items()}
    pruefe("P15 zusammen zu gross: sechs Bilder zu 4 MB base64 und drei "
           "Texte zu 150 kB ja, ein Bild und zwei Texte nein",
           urteil == {"ein Bild": False, "sechs Bilder": True,
                      "zwei Texte": False, "drei Texte": True,
                      "nichts": False}, urteil)
    pruefe("P15 die Grenze liegt unter den 32 MB je Anfrage der Anthropic-"
           "Schnittstelle, und zehn volle Bilder (BILD_MAX_BYTES) passen NICHT",
           D.ANHAENGE_GESAMT_MAX < 32000000
           and D._anhaenge_zu_gross([{"art": "bild", "b64": "A" * (
               D.BILD_MAX_BYTES * 4 // 3)}] * D.ANHANG_MAX),
           D.ANHAENGE_GESAMT_MAX)

    pfade = [os.path.join(t, "foto.png"), os.path.join(t, "ein ordner")]
    gefragt = []
    echt_isfile, echt_isdir = os.path.isfile, os.path.isdir

    def draht(p):
        gefragt.append(p)
        return echt_isfile(p)

    def ziehen(M):
        del gefragt[:]
        os.path.isfile = draht
        os.path.isdir = draht
        try:
            return M._lokale_dateien(_Mime(pfade)), list(gefragt)
        finally:
            os.path.isfile, os.path.isdir = echt_isfile, echt_isdir
    liste, fragen = ziehen(D)
    pruefe("P15 Ziehen/Einfuegen: die lokalen Pfade ohne eine Frage an das "
           "Dateisystem (Qt ruft das bei jeder Mausbewegung)",
           liste == pfade and fragen == [], (liste, fragen))
    M, n = _dash_mutant(dash_pfad, "if u.isLocalFile() and u.toLocalFile()]",
                        "if u.isLocalFile() and os.path.isfile("
                        "u.toLocalFile())]", "p15_mut2")
    _l, k_fragen = ziehen(M)
    pruefe("P15 KONTROLLE: mit isfile fragt es das Dateisystem je Pfad",
           n == 1 and len(k_fragen) == 2, (n, k_fragen))


def _sperre_pruefen(D, C, dash_pfad):
    """P17 (Rueckmeldung 2026-09-28): hat "Nur lesen" im laufenden Zug etwas
    ohne Frage abgelehnt, sagt ein Hinweis, WAS die KI wollte — nur in
    diesem Modus, nur fuer den laufenden Zug. Rein, ohne Qt."""
    cad = C.MCP_PRAEFIX + "__execute_cadwork_command"
    ev = [{"art": "ich", "text": "zeichne"},
          {"art": "verweigert", "werkzeug": cad,
           "eingabe": {"code": "x", "description": "Wand Nord"}},
          {"art": "verweigert", "werkzeug": "Write", "eingabe": {}},
          {"art": "verweigert", "werkzeug": cad, "eingabe": {"code": "y"}}]
    h = D._sperre_hinweis(ev, "nur_lesen", C)
    text = D._sperre_text(h) if h else ""
    pruefe("P17 Nur lesen, zwei Ablehnungen im Zug: ein Hinweis mit den "
           "Alltagsnamen (ohne Zeichen davor), 'etwas ändern'",
           h is not None and h["namen"] == ["Wand Nord", "Datei geschrieben",
                                            "Arbeitet in Cadwork"]
           and not h["lesen"]
           and text == ("Die KI wollte etwas ändern (Wand Nord, Datei "
                        "geschrieben, Arbeitet in Cadwork). Im Modus «Nur "
                        "lesen» ist das gesperrt."), (h, text))
    pruefe("P17 in jedem anderen Modus kein Hinweis (der Wechsel erledigt "
           "ihn)", all(D._sperre_hinweis(ev, m, C) is None
                       for m in ("fragen", "cadwork_frei", "alles_auto")))
    pruefe("P17 eine neue Nachricht beginnt einen neuen Zug: kein Hinweis",
           D._sperre_hinweis(ev + [{"art": "ich", "text": "und?"}],
                             "nur_lesen", C) is None)
    lesen = D._sperre_hinweis([{"art": "verweigert", "werkzeug": "Read"}],
                              "nur_lesen", C)
    pruefe("P17 nur ein Lesen ausserhalb abgelehnt: 'ausserhalb des "
           "Arbeitsordners lesen'", lesen is not None and lesen["lesen"]
           and "ausserhalb des Arbeitsordners lesen" in D._sperre_text(lesen),
           lesen)
    viele = D._sperre_text({"namen": list("ABCDE"), "lesen": False})
    pruefe("P17 mehr als drei Namen: 'und 2 weitere'",
           "(A, B, C und 2 weitere)" in viele, viele)
    pruefe("P17 alte Ereignisse (fortgesetzter Chat) zaehlen nicht",
           D._sperre_hinweis([dict(ev[1], alt=True)], "nur_lesen", C) is None)
    M, n = _dash_mutant(dash_pfad, "    if modus != SPERRE_MODUS:\n"
                        "        return None\n", "", "p17_mutant")
    pruefe("P17 KONTROLLE: ohne die Bedingung auf den Modus bliebe der "
           "Hinweis nach dem Wechsel stehen",
           n == 1 and M._sperre_hinweis(ev, "fragen", C) is not None)


def _emoji_in_texten(quelltext):
    """Die Zeichenketten im Quelltext (ohne Kommentare, ohne Docstrings), die
    ein Emoji-Bildzeichen tragen (ab U+1F000, dazu ✋ ⚡ ⛔ ⏳). -> Liste."""
    import ast as _ast
    treffer = []
    baum = _ast.parse(quelltext)
    doc = set()
    for k in _ast.walk(baum):
        if isinstance(k, (_ast.FunctionDef, _ast.ClassDef, _ast.Module)) \
                and k.body and isinstance(k.body[0], _ast.Expr) \
                and isinstance(getattr(k.body[0], "value", None),
                               _ast.Constant):
            doc.add(id(k.body[0].value))
    for k in _ast.walk(baum):
        if isinstance(k, _ast.Constant) and isinstance(k.value, str) \
                and id(k) not in doc:
            if any(ord(c) >= 0x1F000 or c in "✋⚡⛔⏳" for c in k.value):
                treffer.append(k.value[:40])
    return treffer


def _einstieg_p19(D, dash_pfad):
    """P19 (Rueckmeldung 2026-09-29): die Karte "Womit möchtest du
    chatten?" steht nur, wenn NICHTS eingerichtet ist, kein Chat laeuft und
    der Verlauf leer ist. Rein, ohne Qt; das Nachsehen gegen Attrappen."""
    nichts = {"claude": False, "codex": False, "schluessel": False,
              "lokal": False}
    n = D._einstieg_noetig
    pruefe("P19 nichts eingerichtet, leer, kein Chat -> Karte",
           n(nichts, {}, False, True, None) is True)
    faelle = {k: n(dict(nichts, **{k: True}), {}, False, True, None)
              for k in nichts}
    faelle["schluessel_da"] = n(nichts, {"openai": True}, False, True, None)
    faelle["laeuft"] = n(nichts, {}, True, True, None)
    faelle["verlauf"] = n(nichts, {}, False, False, None)
    faelle["alter_chat"] = n(nichts, {}, False, True, {"id": "x"})
    faelle["veraltet"] = n(nichts, {}, False, True, None, "neu starten")
    faelle["unbekannt"] = n(None, {}, False, True, None)
    pruefe("P19 jeder eingerichtete Weg, ein Schluessel im Tresor, ein "
           "laufender Chat, ein Verlauf, ein alter Chat, eine alte Fassung "
           "oder ein unbekannter Stand -> keine Karte",
           not any(faelle.values()), faelle)

    class _C:
        def __init__(self, da):
            self.da = da

        def cli_pfad(self):
            if not self.da:
                raise FileNotFoundError("nicht da")
            return "claude.cmd"

    class _A:
        ANBIETER = D._anbieter_modul().ANBIETER

        def __init__(self, da):
            self.da = da

        def codex_pfad(self):
            if not self.da:
                raise RuntimeError("nicht da")
            return "codex.cmd"

    class _L:
        def __init__(self, da):
            self.da = da

        def programm(self, k):
            return "ollama.exe" if self.da and k == "ollama" else None

        def app(self, k):
            return None

    w = D._einstieg_wege
    leer = w(_C(False), _A(False), _L(False), {}, {})
    pruefe("P19 Nachsehen: nichts da -> alles nein",
           leer == nichts, leer)
    einzeln = {
        "claude": w(_C(True), _A(False), _L(False), {}, {})["claude"],
        "codex": w(_C(False), _A(True), _L(False), {}, {})["codex"],
        "lokal": w(_C(False), _A(False), _L(True), {}, {})["lokal"],
        "schluessel_ende": w(_C(False), _A(False), _L(False),
                             {"schluessel_ende": {"openai": "1234"}},
                             {})["schluessel"],
        "umgebung": w(_C(False), _A(False), _L(False), {},
                      {"OPENAI_API_KEY": "sk-x"})["schluessel"],
        "eigene_adresse": w(_C(False), _A(False), _L(False),
                            {"basis": {"eigen": "http://x:1/v1"}},
                            {})["schluessel"]}
    pruefe("P19 Nachsehen: jeder Weg wird erkannt (Claude Code, Codex, "
           "lokal, Schluessel aus chat.json, aus der Umgebung, eigene "
           "Adresse)", all(einzeln.values()), einzeln)
    M, t = _dash_mutant(dash_pfad, "    if any(stand.get(k) for k in (\"claude\", \"codex\", \"schluessel\", \"lokal\")):\n        return False\n", "", "p19_mutant")
    pruefe("P19 KONTROLLE: ohne die Pruefung auf Eingerichtetes stuende "
           "die Karte auch mit Claude Code da",
           t == 1 and M._einstieg_noetig(dict(nichts, claude=True), {}, False,
                                         True, None) is True)

    # P19b (2026-09-29): die Karte nennt fuer Claude dieselben Befehle in
    # derselben Reihenfolge wie Weg A im Schnellstart (beide aus der
    # Quelle), und der erste ist der Installer von Anthropic (ohne Node).
    weg_a = weg_a_befehle()
    karte = karten_befehle(D.EINSTIEG_SCHRITT["claude"], weg_a)
    pruefe("P19b Karte 'So geht's' fuer Claude = Befehle von Weg A im "
           "Schnellstart (%s), zuerst der Installer ohne Node" % len(weg_a),
           weg_a and karte == weg_a and weg_a[0].startswith("irm https://")
           and "npm install" not in " ".join(weg_a), (karte, weg_a))
    alt = subprocess.run(["git", "show", "a092618:cad_plugin/Open MCP CAD A/"
                          "omcad_a_dashboard.py"], cwd=REPO,
                         capture_output=True).stdout.decode("utf-8")
    ns = {}
    m = re.search(r"(?ms)^EINSTIEG_SCHRITT = \{.*?^\}", alt)
    exec(m.group(0) if m else "EINSTIEG_SCHRITT = {'claude': ''}", ns)
    pruefe("P19b KONTROLLE: die alte Karte (Node.js + npm, a092618) weicht "
           "vom Schnellstart ab", karten_befehle(
               ns["EINSTIEG_SCHRITT"]["claude"], weg_a) != weg_a,
           karten_befehle(ns["EINSTIEG_SCHRITT"]["claude"], weg_a))


def weg_a_befehle():
    """Die Zeilen der Codebloecke von Weg A in verteilung/SCHNELLSTART.md."""
    text = open(os.path.join(REPO, "verteilung", "SCHNELLSTART.md"),
                encoding="utf-8").read()
    teil = re.search(r"(?ms)^### Weg A.*?(?=^### )", text)
    zeilen = []
    for block in re.findall(r"```\n(.*?)```", teil.group(0) if teil else "",
                            re.S):
        zeilen += [z.strip() for z in block.splitlines() if z.strip()]
    return zeilen


def karten_befehle(schritt, bekannte):
    """Die Zeilen der Karte, die Befehle sind: jede, die irgendwo als
    Befehl vorkommt (im Schnellstart) oder so aussieht (npm/winget/irm)."""
    return [z.strip() for z in schritt.splitlines()
            if z.strip() in bekannte
            or re.match(r"(npm|winget|irm) ", z.strip())]


def _symbole_pruefen(D, dash_pfad):
    """P18 (Rueckmeldung 2026-09-28): Strich-Symbole statt Emoji. Jeder Name,
    den das Dock verlangt, steht im Symbol-Modul (aus der Quelle gelesen:
    SYMBOLE, MODUS_SYMBOLE, SCHRITTE, die Zustands-Symbole); jedes Symbol ist
    gueltiges SVG 24x24; die Lizenz steht in der Datei und im Repo; in den
    Texten des Docks steht kein Emoji mehr."""
    import xml.dom.minidom as _xml
    spec = importlib.util.spec_from_file_location(
        "p18_symbole", os.path.join(A, "omcad_a_symbole.py"))
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    verlangt = ({v[0] for v in D.SYMBOLE.values()}
                | set(D.MODUS_SYMBOLE.values())
                | {v[0] for v in D.SCHRITTE.values()}
                | {D.SCHRITT_ANDERES, D.SCHRITT_SYMBOL_FEHLER,
                   D.SCHRITT_SYMBOL_ABGELEHNT, "check", "folder",
                   "folder-open", "refresh-cw", "paperclip",
                   "clipboard-paste", "grip-vertical", "sparkles",
                   "triangle-alert"})
    fehlt = sorted(n for n in verlangt if n not in S.SYMBOLE)
    pruefe("P18 jeder Name, den das Dock verlangt, steht im Symbol-Modul "
           "(%d Namen)" % len(verlangt), not fehlt, fehlt)
    kaputt = []
    for name in S.SYMBOLE:
        try:
            wurzel = _xml.parseString(S.svg(name, "#123456")).documentElement
            if wurzel.getAttribute("viewBox") != "0 0 24 24" \
                    or wurzel.getAttribute("stroke") != "#123456" \
                    or not wurzel.childNodes:
                kaputt.append(name)
        except Exception as exc:                        # noqa: BLE001
            kaputt.append("%s: %s" % (name, exc))
    pruefe("P18 jedes Symbol ist gueltiges SVG (24x24, Strichfarbe gesetzt)",
           not kaputt and S.svg("gibt-es-nicht") is None, kaputt)
    pruefe("P18 KONTROLLE: ein Name, den es nicht gibt, fiele auf",
           "gibt-es-nicht" not in S.SYMBOLE)
    kopf = S.__doc__ or ""
    notiz = io.open(os.path.join(REPO, "THIRD_PARTY_NOTICES.md"),
                    encoding="utf-8").read()
    pruefe("P18 Lizenz (ISC von Lucide, MIT fuer die Feather-Teile) in der "
           "Datei, die mit dem Plugin geht, und in THIRD_PARTY_NOTICES.md",
           all(t in kopf and t in notiz for t in (
               "ISC License", "Lucide Icons and Contributors",
               "Permission to use, copy, modify", "Cole Bemis",
               "The MIT License (MIT)")))
    class _Knopf:
        def __init__(self):
            self.t, self.ikone = None, None

        def setText(self, t):                           # noqa: N802
            self.t = t

        def setIcon(self, i):                           # noqa: N802
            self.ikone = i

    k1, k2 = _Knopf(), _Knopf()
    ohne_qt = "PyQt6" not in sys.modules
    ergebnis = (S.knopf_setzen(k1, "settings", "⚙"),
                S.knopf_setzen(k2, "square-pen", "Neu", text="Neuer Chat"))
    pruefe("P18 ohne QtSvg (hier: ohne PyQt6): kein Symbol, der Ersatztext "
           "steht da, nichts wirft",
           ohne_qt and S.qtsvg() is None and S.symbol("plus") is None
           and ergebnis == (False, False) and k1.t == "⚙"
           and k2.t == "Neuer Chat" and k1.ikone is None,
           (ohne_qt, ergebnis, k1.t, k2.t))
    with io.open(dash_pfad, encoding="utf-8") as fh:
        quelle_d = fh.read()
    reste = _emoji_in_texten(quelle_d)
    pruefe("P18 in den Texten des Docks steht kein Emoji mehr", not reste,
           reste[:8])
    pruefe("P18 KONTROLLE: ein Emoji in einem Text fiele auf",
           _emoji_in_texten('x = "📁 Ordner"\n') == ["📁 Ordner"]
           and _emoji_in_texten('# 📁 nur Kommentar\nx = 1\n') == [])


def _k12_p20_p21(D, C, dash_pfad):
    """P20/P21 (K12, Spezifikation 2.2, 5.3, 1.3, 4.2): die reinen
    Entscheidungen des EINEN Fensters — was die Pille und die
    Arbeitsanzeige sagen, die Zustandsmaschine, die Kurznamen der
    Denkstufen. Ausgefuehrt, nicht gegrept; je eine Kontrolle mit einem
    Mutanten aus der Quelle."""
    # -- P20 Pille ---------------------------------------------------------
    pz = D._pille_zustand
    faelle = [
        ((False, "ready"), "Aus"),
        ((True, "stopped"), "Aus"),
        ((True, "starting", "x", True, True), "Verbindet …"),
        ((True, "error", "x", True, True), "Störung"),
        ((True, "busy_write", "Viewer-Modus", True, True), "Cadwork rechnet"),
        ((True, "ready", D.EIGENES_MENUE, True, True), "Menü offen"),
        ((True, "busy_write", None, True, True), "Wartet auf dich"),
        ((True, "busy_write", None, False, True), "Zeichnet"),
        ((True, "busy_read", None, False, True), "Liest"),
        ((True, "ready", None, False, True), "Denkt nach"),
        ((True, "paused", None, False, False), "Pausiert"),
        ((True, "stopping_after_job"), "Trennt nach Auftrag"),
        ((True, "ready"), "Bereit"),
    ]
    falsch = [(a, s, pz(*a)[0]) for a, s in faelle if pz(*a)[0] != s]
    pruefe("P20 Pille: dreizehn Faelle in der Reihenfolge der "
           "Spezifikation 2.2 (aus, verbindet, Stoerung, Cadwork rechnet, "
           "eigenes Menue offen — Gegenpruefung K12 —, Freigabe, zeichnet, "
           "liest, denkt nach, pausiert, trennt, bereit)",
           not falsch, falsch[:3])
    pruefe("P20 Pille: Farben — grau aus, orange wartet/Cadwork, gruen "
           "bereit, blau zeichnet/denkt",
           pz(False, None)[1] == "#8e8e93"
           and pz(True, "ready", "x")[1] == D.FARBEN["orange"]
           and pz(True, "ready", None, True)[1] == D.FARBEN["orange"]
           and pz(True, "ready")[1] == D.FARBEN["gruen"]
           and pz(True, "busy_write")[1] == D.FARBEN["blau"]
           and pz(True, "ready", None, False, True)[1] == D.FARBEN["blau"])

    # -- P20 Arbeitsanzeige --------------------------------------------------
    az = D._anzeige_zustand
    schreib = {"zugriff": "write", "beschreibung": "Wand Nord",
               "paket": [3, 8], "t0": 100.0}
    lesen = {"zugriff": "read", "beschreibung": "Waende zaehlen"}
    lauf_g = {"lauf_gezeichnet": 12, "lauf_gesamt": 40, "prozent": 30,
              "restzeit_s": 20.0}
    tabelle = [
        (dict(blockiert="Viewer", freigabe="x", auftrag=schreib),
         ("Cadwork rechnet", None, None, "orange")),
        (dict(freigabe="Zeichnen in Cadwork", auftrag=schreib,
              chat_zug=True), ("Wartet auf deine Freigabe", "zum_chat",
                               None, "orange")),
        (dict(auftrag=schreib, jetzt=104.0, lauf={}),
         ("KI zeichnet", "anhalten", "unbestimmt", "blau")),
        (dict(auftrag=schreib, lauf=lauf_g, jetzt=104.0),
         ("KI zeichnet", "anhalten", 30, "blau")),
        (dict(auftrag=lesen, chat_zug=True),
         ("KI schaut ins Modell", "anhalten", None, "blau")),
        # Gegenpruefung K12: "Anhalten" nur, wo es etwas anhaelt — ohne
        # laufenden Auftrag und ohne Wartende haelt es nichts an.
        (dict(chat_zug=True, letzter=("Element erzeugt", 3.2)),
         ("KI denkt nach", None, None, "blau")),
        (dict(chat_zug=True, wartende=2),
         ("KI denkt nach", "anhalten", None, "blau")),
        (dict(lauf_aktiv=True, client="Codex"),
         ("Wartet auf den nächsten Schritt", None, None, "blau")),
        (dict(lauf_aktiv=True, client="Codex", wartende=1),
         ("Wartet auf den nächsten Schritt", "anhalten", None, "blau")),
        (dict(fertig=(12, 8.0)), ("Fertig", None, 100, "gruen")),
        (dict(angehalten=2, lauf_aktiv=True, balken_vorher=40),
         ("Angehalten", None, 40, "orange")),
        (dict(angehalten=2, auftrag=schreib, jetzt=104.0),
         ("KI zeichnet", "anhalten", "unbestimmt", "blau")),
        (dict(angehalten=0, chat_zug=True),
         ("KI denkt nach", None, None, "blau")),
        (dict(blockiert=D.EIGENES_MENUE, auftrag=schreib),
         ("Wartet, bis das Menü zu ist", None, None, "orange")),
    ]
    falsch = []
    for eingabe, soll in tabelle:
        ist = az(**eingabe)
        ist = ist and (ist["titel"], ist["knopf"], ist["balken"],
                       ist["farbe"])
        if ist != soll:
            falsch.append((sorted(eingabe), ist))
    pruefe("P20 Arbeitsanzeige: vierzehn Faelle der Tabelle 5.3 (Titel, "
           "Knopf, Balken, Farbe; Anhalten nur mit Auftrag oder Wartenden, "
           "Angehalten nur nach einem Verwerfen, eigenes Menue)",
           not falsch, falsch[:2])
    pruefe("P20 Arbeitsanzeige: 'Angehalten' nennt, was verworfen wurde, "
           "und im Chat, wer den Chat anhaelt",
           az(angehalten=2, lauf_aktiv=True)["zeile"]
           == "2 wartende Aufträge verworfen"
           and az(angehalten=1, chat_zug=True)["zeile"]
           == "1 wartender Auftrag verworfen · den Chat hält «Beenden» an",
           (az(angehalten=2, lauf_aktiv=True)["zeile"],
            az(angehalten=1, chat_zug=True)["zeile"]))
    zeilen = (az(auftrag=schreib, jetzt=104.0)["zeile"],
              az(auftrag=schreib, lauf=lauf_g, jetzt=104.0)["zeile"],
              az(chat_zug=True, letzter=("Element erzeugt", 3.2))["zeile"],
              az(fertig=(12, 8.0))["zeile"],
              az(blockiert="Viewer")["zeile"])
    pruefe("P20 Arbeitsanzeige: Zeilen wie in der Spezifikation",
           zeilen == ("Wand Nord · Paket 3 von 8 · 4 s",
                      "12 von 40 Bauteilen · noch etwa 20 s",
                      "Zuletzt: Element erzeugt · vor 3 s",
                      "12 Bauteile in 8 s",
                      "Open MCP CAD wartet, bis Cadwork fertig ist."),
           zeilen)
    pruefe("P20 Arbeitsanzeige: ohne Lauf, Zug und Ende nichts (None)",
           az() is None and az(lauf={"prozent": 5}) is None)

    # KONTROLLE: ein Mutant mit vertauschtem Vorrang (die Freigabe HINTER
    # dem Auftrag) — dann stuende "KI zeichnet", waehrend die KI auf eine
    # Antwort wartet.
    alt = ("    if freigabe:\n        return erg(ANZEIGE_FREIGABE, "
           "str(freigabe), knopf=\"zum_chat\",\n                   "
           "farbe=\"orange\")\n")
    with io.open(dash_pfad, encoding="utf-8") as fh:
        quelle = fh.read()
    mut = quelle.replace(alt, "").replace(
        "    if lauf_aktiv:\n        return erg(ANZEIGE_WARTET",
        alt + "    if lauf_aktiv:\n        return erg(ANZEIGE_WARTET")
    M = type(sys)("p20_mutant")
    M.__file__ = dash_pfad
    exec(compile(mut, dash_pfad, "exec"), M.__dict__)
    rot = M._anzeige_zustand(freigabe="Zeichnen in Cadwork",
                             auftrag=schreib, chat_zug=True)
    pruefe("P20 KONTROLLE: Freigabe hinter dem Auftrag (Mutant) -> die "
           "Zelle oben waere rot",
           quelle.count(alt) == 1 and rot["titel"] == "KI zeichnet",
           rot and rot["titel"])
    # KONTROLLE: "KI denkt nach" mit "Anhalten" wie bis zur Gegenpruefung
    # (ein Knopf, der nichts anhaelt).
    alt2 = "return erg(ANZEIGE_DENKT, zeile, None, anhalten)"
    M2 = type(sys)("p20_mutant2")
    M2.__file__ = dash_pfad
    exec(compile(quelle.replace(alt2, alt2.replace(", anhalten)",
                                                   ", \"anhalten\")")),
                 dash_pfad, "exec"), M2.__dict__)
    rot2 = M2._anzeige_zustand(chat_zug=True, letzter=("x", 1.0))
    pruefe("P20 KONTROLLE: 'KI denkt nach' mit Anhalten (alter Stand) -> "
           "die Zelle oben waere rot", quelle.count(alt2) == 1
           and rot2["knopf"] == "anhalten", rot2 and rot2["knopf"])

    # -- P21 Zustandsmaschine --------------------------------------------
    ue = D._fenster_uebergang
    P, O, A_ = D.PILLE_Z, D.OFFEN_Z, D.ANGEDOCKT_Z
    soll = {
        (P, "klick", "chat"): (P, "chat", False, None),
        (O, "klick", "chat"): (O, "chat", False, None),
        (A_, "klick", "chat"): (A_, "chat", False, None),
        (P, "chat", "chat"): (O, "chat", True, None),
        (P, "chat", "briefkasten"): (O, "chat", True, None),
        (O, "chat", "chat"): (P, "chat", False, None),
        (O, "chat", "briefkasten"): (O, "chat", True, None),
        (O, "chat", "einstellungen"): (O, "chat", True, None),
        (A_, "chat", "briefkasten"): (A_, "chat", True, None),
        (A_, "chat", "chat"): (A_, "chat", True, None),
        (P, "andocken", "chat"): (A_, "chat", False, None),
        (O, "andocken", "briefkasten"): (A_, "briefkasten", False, None),
        (A_, "andocken", "chat"): (O, "chat", False, None),
        (P, "verkleinern", "chat"): (P, "chat", False, None),
        (O, "verkleinern", "chat"): (P, "chat", False, None),
        (A_, "verkleinern", "briefkasten"): (P, "briefkasten", False, None),
        (P, "hinweise", "chat"): (O, "chat", False, "auf"),
        (O, "hinweise", "briefkasten"): (O, "briefkasten", False, "um"),
        (A_, "hinweise", "chat"): (A_, "chat", False, "um"),
        (O, "schliessen", "chat"): (P, "chat", False, None),
        (A_, "schliessen", "chat"): (P, "chat", False, None),
    }
    falsch = []
    for (z0, aktion, seg), erwartet in soll.items():
        e = ue(z0, aktion, seg)
        ist = (e["zustand"], e["segment"], e["fokus"], e["hinweise"])
        if ist != erwartet:
            falsch.append(((z0, aktion, seg), ist))
    pruefe("P21 Zustandsmaschine: alle %d Paare der Tabelle 1.3"
           % len(soll), not falsch, falsch[:3])
    pruefe("P21 ein unbekannter Zustand gilt als Pille",
           ue("kaputt", "chat", "chat")["zustand"] == O)
    # KONTROLLE: "Chat aus (b) bei Briefkasten schliesst" (Mutant).
    alt_c = ('        elif zustand == OFFEN_Z and segment == "chat":\n'
             '            erg["zustand"] = PILLE_Z\n')
    mut = quelle.replace(alt_c, '        elif zustand == OFFEN_Z:\n'
                                '            erg["zustand"] = PILLE_Z\n')
    M2 = type(sys)("p21_mutant")
    M2.__file__ = dash_pfad
    exec(compile(mut, dash_pfad, "exec"), M2.__dict__)
    e = M2._fenster_uebergang(O, "chat", "briefkasten")
    pruefe("P21 KONTROLLE: schliesst der Chat-Knopf (b) auch beim "
           "Briefkasten (Mutant), waere die Zelle oben rot",
           quelle.count(alt_c) == 1 and e["zustand"] == P, e)

    # -- P21 Kurznamen der Denkstufen ----------------------------------
    werte = [w for _a, w in C.EFFORT_STUFEN]
    pruefe("P21 STUFE_KURZ deckt genau C.EFFORT_STUFEN (gleiche Werte, je "
           "ein Name, Gross geschrieben, ohne Klammern)",
           sorted(D.STUFE_KURZ) == sorted(werte)
           and all(n and n[0].isupper() and "(" not in n
                   for n in D.STUFE_KURZ.values()), D.STUFE_KURZ)
    pruefe("P21 KONTROLLE: eine Stufe mehr in C fiele auf",
           sorted(D.STUFE_KURZ) != sorted(werte + ["turbo"]))


def _ruhe_p23(D, dash_pfad):
    """P23 (Ruhe in der Anzeige, Rueckmeldung 2026-10-10 "Disco"): der
    Arbeitsblock, die geglaettete Pille, wann die Arbeitsanzeige steht, die
    zusammengefassten Zeilen der Auftragsliste — ausgefuehrt, je mit
    Kontrolle (alte Logik bzw. Mutant der Quelle)."""
    quelle = lies(dash_pfad)

    def mutant(name, alt, neu):
        M = type(sys)(name)
        M.__file__ = dash_pfad
        exec(compile(quelle.replace(alt, neu), dash_pfad, "exec"),
             M.__dict__)
        return M, quelle.count(alt)

    def folge(muster, dauer=0.05, pause=0.4, takt=0.5):
        """Auftraege nach `muster` ("l" lesen, "z" zeichnen), je `dauer`
        lang, dazwischen `pause`; der Takt des Docks alle `takt` s."""
        ev, t, naechst = [], 0.0, 0.0
        for m in muster:
            ev.append((t, "zeichnen" if m == "z" else "lesen"))
            t += dauer
            ev.append((t, "takt"))
            naechst = max(naechst, t)
            while naechst + takt < t + pause:
                naechst += takt
                ev.append((naechst, "takt"))
            t += pause
        ev += [(t + 0.5 * i, "takt") for i in range(12)]
        return ev

    PL, B = D.PILLE, D._block_schritt
    # -- Block -----------------------------------------------------------
    b = D._block_auftrag(None, 0.0, "read")
    b = D._block_auftrag(b, 0.3, "write")
    b = D._block_auftrag(b, 0.6, "read")
    pruefe("P23 Block: drei Auftraege hintereinander sind EIN Block, "
           "'write' gewinnt, gezaehlt 3 (1 aendernd)",
           b["aktiv"] and b["art"] == "write" and b["anzahl"] == 3
           and b["schreibend"] == 1 and b["start"] == 0.0, b)
    pruefe("P23 Block: endet erst RUHE_BEREIT_S nach dem letzten Auftrag",
           B(b, 0.6 + D.RUHE_BEREIT_S - 0.01)["aktiv"]
           and not B(b, 0.6 + D.RUHE_BEREIT_S)["aktiv"]
           and D.RUHE_BEREIT_S >= 1.5 and D.RUHE_HALTEN_S >= 1.0,
           (D.RUHE_BEREIT_S, D.RUHE_HALTEN_S))
    pruefe("P23 Block: nach dem Ende beginnt ein neuer (Zaehler 1, lesend)",
           D._block_auftrag(B(b, 10.0), 10.0, "read")["anzahl"] == 1
           and D._block_auftrag(B(b, 10.0), 10.0, "read")["art"] == "read")
    # -- Pille -----------------------------------------------------------
    g, z1 = D._pille_ruhig(None, PL["busy_read"], b, 0.0)
    g, z2 = D._pille_ruhig(g, PL["ready"], b, 0.7)
    g2, z3 = D._pille_ruhig(g, PL[None], b, 0.8)
    _g, z4 = D._pille_ruhig(g, D.PILLE_FREIGABE, b, 0.8)
    _g, z5 = D._pille_ruhig(g, D.PILLE_CADWORK, b, 0.8)
    pruefe("P23 Pille: im Block 'Zeichnet' (auch beim Lesen und dazwischen), "
           "Aus/Freigabe sofort, 'Cadwork rechnet' bleibt sichtbar",
           (z1[0], z2[0], z3[0], z4[0], z5[0])
           == ("Zeichnet", "Zeichnet", "Aus", "Wartet auf dich",
               "Cadwork rechnet"), (z1, z2, z3, z4, z5))
    lb = D._block_auftrag(None, 0.0, "read")
    g, _z = D._pille_ruhig(None, PL["busy_read"], lb, 0.0)
    _g, halt = D._pille_ruhig(g, D.PILLE_DENKT, D._block_schritt(
        dict(lb, aktiv=False), 0.5), 0.5)
    _g, frei = D._pille_ruhig(g, D.PILLE_DENKT, D._block_schritt(
        dict(lb, aktiv=False), 1.6), 1.6)
    pruefe("P23 Pille: ein Arbeitszustand bleibt RUHE_HALTEN_S stehen "
           "(auch wenn der Block schon vorbei waere)",
           halt[0] == "Liest" and frei[0] == "Denkt nach", (halt, frei))
    # -- Die Folge: 30 kurze Leseauftraege, gemischt ---------------------
    lesen = folge("l" * 30)
    gemischt = folge("zllll" * 6)
    neu_l, alt_l = D._ruhe_folge(lesen), D._ruhe_folge(lesen, glatt=False)
    neu_g, alt_g = D._ruhe_folge(gemischt), D._ruhe_folge(gemischt,
                                                          glatt=False)
    werte = {"lesen_pille": (D._wechsel(alt_l, 1), D._wechsel(neu_l, 1)),
             "lesen_anzeige": (D._wechsel(alt_l, 2), D._wechsel(neu_l, 2)),
             "gemischt_pille": (D._wechsel(alt_g, 1), D._wechsel(neu_g, 1)),
             "gemischt_anzeige": (D._wechsel(alt_g, 2),
                                  D._wechsel(neu_g, 2))}
    print("  [info] P23 Folge (alt, neu): %s" % werte)
    pruefe("P23 30 kurze Leseauftraege: die Pille wechselt EINMAL (Liest -> "
           "Bereit am Ende), die Anzeige erscheint nie",
           werte["lesen_pille"][1] == 1 and werte["lesen_anzeige"][1] == 0
           and neu_l[-1][1:] == ("Bereit", False), werte)
    pruefe("P23 gemischt (zeichnen + 4x lesen, 6 Runden): Pille einmal, "
           "Anzeige einmal an, einmal aus; nie 'Liest' im Block",
           werte["gemischt_pille"][1] == 1
           and werte["gemischt_anzeige"][1] == 2
           and not any(f[1] == "Liest" for f in neu_g), werte)
    pruefe("P23 KONTROLLE: die alte Logik (Zustand je Auftrag) wechselt die "
           "Pille bei jedem Auftrag (>= 50 Wechsel)",
           werte["lesen_pille"][0] >= 50 and werte["gemischt_pille"][0] >= 50,
           werte)
    kurz = D._ruhe_folge([(0.0, "zeichnen"), (0.1, "takt"), (0.5, "takt"),
                          (1.0, "takt"), (2.5, "takt"), (5.0, "takt")])
    pruefe("P23 ein kurzer Einzelauftrag (aendernd, 0,1 s) blitzt nicht auf: "
           "die Anzeige erscheint erst ab ANZEIGE_AB_S Blockdauer",
           not any(f[2] for f in kurz[:2]) and D.ANZEIGE_AB_S >= 0.3,
           kurz)
    pruefe("P23 Anzeige nur fuer aendernde Bloecke, nie neu waehrend "
           "Cadwork rechnet, angemeldeter Lauf gleich",
           not D._anzeige_soll(lb, 5.0, False, lauf_aktiv=True)
           and not D._anzeige_soll(b, 5.0, False, lauf_aktiv=True,
                                   blockiert="Viewer")
           and D._anzeige_soll(b, 0.1, False, lauf_aktiv=True,
                               angemeldet=True)
           and not D._anzeige_soll(b, 0.1, False, lauf_aktiv=True)
           and D._anzeige_soll(b, 0.1, True))
    M, n = mutant("p23_mutant", "RUHE_BEREIT_S = 2.0", "RUHE_BEREIT_S = 0.0")
    rot = M._wechsel(M._ruhe_folge(lesen), 1)
    pruefe("P23 KONTROLLE: ohne Nachlauf des Blocks (RUHE_BEREIT_S 0, "
           "Mutant) wechselt die Pille wieder je Auftrag",
           n == 1 and rot >= 8, (n, rot))
    # -- Auftragsliste ---------------------------------------------------
    jetzt = 1000.0
    lesend = [{"methode": "execute_cwapi3d", "zugriff": "read", "ok": True,
               "beschreibung": "Wand %d" % i, "beendet": jetzt - i}
              for i in range(12)]
    liste = ([{"methode": "execute_cwapi3d", "zugriff": "write", "ok": True,
               "beschreibung": "Dach", "beendet": jetzt + 1}] + lesend
             + [{"methode": "execute_cwapi3d", "zugriff": "read", "ok": False,
                 "beschreibung": "Fehler", "beendet": jetzt - 20}])
    gr = D._auftrag_gruppen(liste, jetzt + 2)
    pruefe("P23 Auftragsliste: 12 Leseauftraege hintereinander sind EINE "
           "Zeile 'KI schaut ins Modell (12×)', aendernde und fehlerhafte "
           "einzeln",
           [x["anzahl"] for x in gr] == [1, 12, 1]
           and gr[1]["text"].startswith("KI schaut ins Modell (12×)")
           and "Wand 0" in gr[1]["tipp"] and "… und 4 weitere" in gr[1]["tipp"],
           [(x["anzahl"], x["text"]) for x in gr])
    gr2 = D._auftrag_gruppen([dict(lesend[0], beendet=jetzt + 0.5)] + liste,
                             jetzt + 2)
    pruefe("P23 Auftragsliste: der Schluessel einer Zeile bleibt, wenn ein "
           "neuer Leseauftrag dazukommt (Auswahl/Rollstand)",
           [x["schluessel"] for x in gr2][2:] ==
           [x["schluessel"] for x in gr][1:] and gr2[0]["anzahl"] == 1)
    M, n = mutant("p23_mutant2", 'and a.get("methode") == b.get("methode"))',
                  "and False)")
    pruefe("P23 KONTROLLE: ohne Zusammenfassen (Mutant) 14 Zeilen",
           n == 1 and len(M._auftrag_gruppen(liste, jetzt)) == 14)


def _updates_p24(D, dash_pfad):
    """P24 (Updates, 2026-10-10): Versionsvergleich, Takt 24 h,
    abgeschaltet, fremde Antworten, lokaler HTTP-Dienst als API (ephemerer
    Port, umgelenkte Basis), Download mit falscher Pruefsumme/Groesse,
    ZIP ohne install.ps1 und mit Pfad nach draussen, Start des
    Einrichtungsfensters ueber einen ersetzten Starter, fehlende Profile in
    Temp-Welten, die Zeile des Docks. Ein Stolperdraht auf
    socket.create_connection: nichts geht an einen anderen Rechner."""
    import http.server
    import json as _json
    import shutil
    import tempfile
    import threading
    import zipfile
    U = D._update_modul()
    # -- Version und Takt ------------------------------------------------
    vt = U.version_tupel
    pruefe("P24 Versionen: v0.3.1/0.3.1 lesbar, Unsinn nicht; 0.10.0 > 0.9.9"
           " (semantisch, nicht als Text)",
           vt("v0.3.1") == (0, 3, 1) and vt("0.3.1") == (0, 3, 1)
           and vt("0.3.1-rc1") is None and vt("..\\x") is None
           and vt(None) is None and U.neuer("0.10.0", "0.9.9")
           and not U.neuer("0.2.2", "0.2.2") and not U.neuer("0.2.1", "0.2.2")
           and not U.neuer("kaputt", "0.2.2"))
    pruefe("P24 KONTROLLE: als Text verglichen waere 0.10.0 aelter",
           not ("0.10.0" > "0.9.9"))
    t0 = 1_000_000.0
    pruefe("P24 Takt: noch nie -> jetzt; nach 23 h nicht, nach 24 h ja; "
           "abgeschaltet nie; Zeit in der Zukunft zaehlt als nie",
           U.faellig(None, t0) and not U.faellig(t0 - 23 * 3600, t0)
           and U.faellig(t0 - 24 * 3600, t0)
           and not U.faellig(None, t0, an=False)
           and U.faellig(t0 + 7200, t0) and U.TAKT_S == 24 * 3600)
    pruefe("P24 Version des Moduls == open_mcp_cad.__version__",
           U.VERSION == re.search(r'__version__\s*=\s*"([^"]+)"', lies(
               os.path.join(REPO, "open_mcp_cad", "__init__.py"))).group(1),
           U.VERSION)
    erlaubt = re.search(r"^\$CADWORK_ERLAUBT_AB\s*=\s*(\d+)", lies(
        os.path.join(REPO, "verteilung", "install.ps1")), re.M)
    pruefe("P24 CADWORK_ERLAUBT_AB == install.ps1 (aus der Quelle)",
           erlaubt and int(erlaubt.group(1)) == U.CADWORK_ERLAUBT_AB,
           erlaubt and erlaubt.group(1))
    # -- Fremde Antworten (rein) -----------------------------------------
    basis = U.API_URL
    gut = {"tag_name": "v9.0.1", "assets": [{
        "name": U.ASSET_NAME, "size": 10,
        "browser_download_url": U.DOWNLOAD_PRAEFIX + "v9.0.1/"
        + U.ASSET_NAME, "digest": "sha256:" + "a" * 64}]}
    r = U.antwort_lesen(_json.dumps(gut).encode(), basis)
    falsch = [
        dict(gut, tag_name="v9.0.1/../x"), dict(gut, prerelease=True),
        dict(gut, assets=[dict(gut["assets"][0], name="Anderes.zip")]),
        dict(gut, assets=[dict(gut["assets"][0],
                               browser_download_url="https://boese.example/"
                               + U.ASSET_NAME)]),
        dict(gut, assets=[dict(gut["assets"][0], size=U.MAX_BYTES + 1)])]
    rf = [U.antwort_lesen(_json.dumps(f).encode(), basis) for f in falsch]
    pruefe("P24 API-Antwort: Version, neuer, Asset mit Groesse und SHA-256",
           r["ok"] and r["version"] == "9.0.1" and r["neuer"]
           and r["asset"]["sha256"] == "a" * 64 and r["asset"]["groesse"] == 10,
           r)
    pruefe("P24 fremde Eingabe: Pfad als Version, Pre-release, anderer "
           "Asset-Name, fremde Adresse, zu gross -> kein Paket",
           [x.get("asset") for x in rf] == [None] * 5
           and not rf[0]["ok"] and not rf[1]["ok"],
           [(x.get("ok"), x.get("grund")) for x in rf])
    pruefe("P24 unlesbare Antwort -> ok False, wirft nicht",
           not U.antwort_lesen(b"\xff{", basis)["ok"]
           and not U.antwort_lesen(b"[]", basis)["ok"])
    # -- Lokaler Dienst --------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="omcad_p24_")
    alt_env = {k: os.environ.get(k) for k in (U.UMGEBUNG_URL,
                                              U.UMGEBUNG_ORDNER)}
    fremd = []
    echt_verbinden = socket.create_connection

    def draht(adresse, *a, **kw):
        if adresse[0] not in ("127.0.0.1", "localhost"):
            fremd.append(adresse)
            raise OSError("Stolperdraht: %r" % (adresse,))
        return echt_verbinden(adresse, *a, **kw)

    def zip_bauen(name, dateien):
        p = os.path.join(tmp, name)
        with zipfile.ZipFile(p, "w") as zf:
            for n, inhalt in dateien.items():
                zf.writestr(n, inhalt)
        with open(p, "rb") as fh:
            return fh.read()
    gutes_zip = zip_bauen("gut.zip", {
        "Open-MCP-CAD-9.0.1/1_INSTALLIEREN.cmd": "@echo off\r\n",
        "Open-MCP-CAD-9.0.1/Programmdateien/install.ps1": "# probe\n",
        "Open-MCP-CAD-9.0.1/Programmdateien/x/y.txt": "y"})
    ohne_ps1 = zip_bauen("ohne.zip", {
        "Open-MCP-CAD-9.0.1/1_INSTALLIEREN.cmd": "@echo off\r\n"})
    draussen = zip_bauen("draussen.zip", {
        "1_INSTALLIEREN.cmd": "x", "Programmdateien/install.ps1": "x",
        "../boese.txt": "x"})
    inhalte = {"/gut.zip": gutes_zip, "/ohne.zip": ohne_ps1,
               "/draussen.zip": draussen}
    abrufe = []

    class Dienst(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):                             # noqa: N802
            abrufe.append((self.path, self.headers.get("User-Agent"),
                           self.headers.get("Cookie")))
            if self.path == "/api":
                daten = _json.dumps(antwort[0]).encode()
            else:
                daten = inhalte.get(self.path)
            if daten is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

    s = _ephemerer_socket()
    srv = http.server.HTTPServer(("127.0.0.1", 0), Dienst,
                                 bind_and_activate=False)
    srv.socket.close()
    srv.socket = s
    srv.server_address = s.getsockname()
    srv.server_activate()
    port = s.getsockname()[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ursprung = "http://127.0.0.1:%d" % port

    def asset(pfad, daten, sha=True, groesse=None):
        return {"name": U.ASSET_NAME, "size": groesse or len(daten),
                "browser_download_url": ursprung + pfad,
                "digest": ("sha256:" + hashlib.sha256(daten).hexdigest()
                           if sha is True else sha)}
    def paket(*a, **kw):
        """Ein Asset, wie `antwort_lesen` es aus der API macht."""
        return U.antwort_lesen({"tag_name": "v9.0.1", "assets": [
            asset(*a, **kw)]}, ursprung + "/api")["asset"]
    antwort = [{"tag_name": "v9.0.1",
                "assets": [asset("/gut.zip", gutes_zip)]}]
    socket.create_connection = draht
    gestartet = []
    alt_starten = U.STARTEN
    U.STARTEN = gestartet.append
    try:
        os.environ[U.UMGEBUNG_URL] = ursprung + "/api"
        os.environ[U.UMGEBUNG_ORDNER] = os.path.join(tmp, "updates")
        n = U.nachsehen("0.2.2")
        pruefe("P24 nachsehen gegen den lokalen Dienst: neuere Version mit "
               "Paket; EIN Abruf, neutraler User-Agent, kein Cookie",
               n["ok"] and n["neuer"] and n["version"] == "9.0.1"
               and _ausserhalb([port]) and len(abrufe) == 1
               and abrufe[0][1] == U.USER_AGENT and abrufe[0][2] is None,
               (n, abrufe, port))
        pruefe("P24 gleiche Version: nicht neuer",
               not U.nachsehen("9.0.1")["neuer"])
        ordner_alt = os.path.join(tmp, "updates", "9.0.1")
        os.makedirs(ordner_alt)
        with open(os.path.join(ordner_alt, "alt.txt"), "w") as fh:
            fh.write("alt")
        prozente = []
        zp = U.laden(n["asset"], fortschritt=lambda a, b: prozente.append(
            (a, b)))
        ordner = U.entpacken(zp, n["version"])
        cmd = U.einrichten(ordner)
        pruefe("P24 laden + pruefen + entpacken nach updates/<version>/ "
               "(alter Inhalt weg), dann das Einrichtungsfenster ueber den "
               "ERSETZTEN Starter (nie echt)",
               os.path.isfile(os.path.join(ordner, "Programmdateien",
                                           "install.ps1"))
               and not os.path.exists(os.path.join(ordner, "alt.txt"))
               and ordner == ordner_alt and gestartet == [cmd]
               and cmd.endswith("1_INSTALLIEREN.cmd") and prozente
               and prozente[-1] == (len(gutes_zip), len(gutes_zip)),
               (ordner, gestartet, prozente[-1:]))
        os.remove(zp)

        def scheitert(a, text):
            vorher = set(os.listdir(tempfile.gettempdir()))
            try:
                U.laden(a)
            except U.UpdateFehler as exc:
                rest = [x for x in set(os.listdir(tempfile.gettempdir()))
                        - vorher if x.startswith("open-mcp-cad-")]
                return text in str(exc) and not rest
            return False
        pruefe("P24 falsche Pruefsumme -> abgelehnt, keine Temp-Datei bleibt",
               scheitert(paket("/gut.zip", gutes_zip, sha="sha256:" + "0"
                               * 64), "Prüfsumme"))
        pruefe("P24 falsche Groesse -> abgelehnt",
               scheitert(paket("/gut.zip", gutes_zip, sha=None,
                               groesse=len(gutes_zip) + 5), "vollständig")
               and scheitert(paket("/gut.zip", gutes_zip, sha=None,
                                   groesse=len(gutes_zip) - 5), "grösser"))
        pruefe("P24 ZIP ohne install.ps1 -> abgelehnt",
               scheitert(paket("/ohne.zip", ohne_ps1),
                         "Programmdateien/install.ps1"))
        pruefe("P24 ZIP mit Pfad nach draussen -> abgelehnt",
               scheitert(paket("/draussen.zip", draussen), "ausserhalb"))
        n_abrufe = len(abrufe)
        pruefe("P24 Adresse eines anderen Ursprungs -> abgelehnt, nie "
               "abgerufen", _abgelehnt(U, {"url": "http://127.0.0.2:%d/gut."
                                                  "zip" % port,
                                           "groesse": 10})
               and len(abrufe) == n_abrufe)
        pruefe("P24 KONTROLLE: ohne Pruefung der Summe (Mutant) ginge die "
               "falsche Summe durch",
               _ohne_summe_durch(U, paket("/gut.zip", gutes_zip,
                                          sha="sha256:" + "0" * 64)))
        # Kein Netz: still.
        os.environ[U.UMGEBUNG_URL] = "http://127.0.0.1:1/api"
        kein = U.nachsehen()
        pruefe("P24 kein Netz -> ok False mit Grund, wirft nicht",
               kein["ok"] is False and "Verbindung" in kein["grund"], kein)
        pruefe("P24 Stolperdraht: nichts ging an einen anderen Rechner",
               not fremd, fremd)
    finally:
        socket.create_connection = echt_verbinden
        U.STARTEN = alt_starten
        srv.shutdown()
        srv.server_close()
        for k, v in alt_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    # -- Fehlende Profile in Temp-Welten ---------------------------------
    wurzel, programm = os.path.join(tmp, "cw"), os.path.join(tmp, "prog")
    for name, mit_plugin in (("userprofil_2026", True),
                             ("USERPROFIL_2027", False),
                             ("userprofil_2025", False),
                             ("userprofil_2024", False),
                             ("userprofil_2028", False), ("anders", False)):
        api = os.path.join(wurzel, name, "3d", "API.x64")
        os.makedirs(os.path.join(api, "Open MCP CAD") if mit_plugin
                    else api)
    for jahr in (2024, 2026, 2027, 2025):
        os.makedirs(os.path.join(programm, "EXE_%d" % jahr))
    hier = os.path.join(wurzel, "userprofil_2025", "3d", "API.x64",
                        "Open MCP CAD")
    fp = U.fehlende_profile(wurzel, programm)
    fp_hier = U.fehlende_profile(wurzel, programm, hier=hier)
    pruefe("P24 fehlende Profile: 2025 und 2027 (GROSS geschrieben) — nicht "
           "2026 (hat es), 2024 (zu alt), 2028 (Cadwork fehlt); das eigene "
           "Profil zaehlt nie",
           [p["jahr"] for p in fp] == [2025, 2027]
           and fp[1]["profil"] == "USERPROFIL_2027"
           and [p["jahr"] for p in fp_hier] == [2027], (fp, fp_hier))
    pruefe("P24 KONTROLLE: mit erlaubt_ab 2024 kaeme 2024 dazu (die Grenze "
           "wirkt)", [p["jahr"] for p in U.fehlende_profile(
               wurzel, programm, erlaubt_ab=2024)] == [2024, 2025, 2027])
    pruefe("P24 fehlende Profile ohne Ordner: leer, wirft nicht",
           U.fehlende_profile(os.path.join(tmp, "gibtsnicht"), programm)
           == [])
    shutil.rmtree(tmp, ignore_errors=True)
    # -- Die Zeile des Docks (rein) --------------------------------------
    zi = D._update_zeile_inhalt
    neu = {"ok": True, "neuer": True, "version": "0.3.0", "asset": {"x": 1}}
    prof = [{"jahr": 2027}]
    faelle = [
        (zi({}, set(), 0), None),
        (zi({"ergebnis": neu}, set(), 0)[1:], ("Aktualisieren", "neu")),
        (zi({"ergebnis": neu, "weg": "0.3.0"}, set(), 0), None),
        (zi({"ergebnis": dict(neu, neuer=False)}, set(), 0), None),
        (zi({"profile": prof}, set(), 0)[0],
         "Open MCP CAD auch in Cadwork 2027 einrichten?"),
        (zi({"profile": prof}, {2027}, 0), None),
        (zi({"laden": {"laeuft": True, "prozent": 45, "version": "0.3.0"}},
            set(), 0)[0], "Update 0.3.0 wird geladen … 45 %"),
        (zi({"laden": {"fertig": True}}, set(), 0)[0], D.UPDATE_SCHLIESSEN),
        (zi({"laden": {"fehler": "x"}}, set(), 0)[2], "nochmal"),
        (zi({"meldung": ("m", 5)}, set(), 4)[0], "m"),
        (zi({"meldung": ("m", 5)}, set(), 6), None)]
    falsch = [(i, a, b) for i, (a, b) in enumerate(faelle) if a != b]
    pruefe("P24 Zeile: neu/Später/gleich alt/Profil/Nein danke/laden/fertig/"
           "Fehler/Meldung mit Ablauf", not falsch, falsch)
    pruefe("P24 'Schliesse Cadwork …' steht im Text",
           "Schliesse Cadwork" in D.UPDATE_SCHLIESSEN)
    pruefe("P24 chat.json: Vorgabe an, kaputte Werte an; profil_frage_weg "
           "nur ganze Jahre",
           D._updates_an({}) and D._updates_an({"updates_suchen": "nein"})
           and not D._updates_an({"updates_suchen": False})
           and D._profil_weg({"profil_frage_weg": [2027, "x", True, 2.5]})
           == {2027})


def _abgelehnt(U, a):
    try:
        U.laden(a)
    except U.UpdateFehler as exc:
        return "nicht die erwartete" in str(exc)
    return False


def _ohne_summe_durch(U, a):
    """KONTROLLE: das Modul mit ausgeschalteter Summenpruefung."""
    pfad = U.__file__
    quelle = lies(pfad)
    alt = 'if asset.get("sha256") and sha.hexdigest() != asset["sha256"]:'
    M = type(sys)("p24_mutant")
    M.__file__ = pfad
    exec(compile(quelle.replace(alt, "if False:"), pfad, "exec"),
         M.__dict__)
    try:
        p = M.laden(a)
    except M.UpdateFehler:
        return False
    os.remove(p)
    return quelle.count(alt) == 1


def _laien_p22(D, dash_pfad):
    """P22 (Gegenpruefung Laien-Sicht K12): die reinen Entscheidungen —
    die Zahl offener Hinweise steht EINMAL (als Chip nur in der Pille), der
    Fuellstand des Chat-Gedaechtnisses erst ab KONTEXT_AB %, ohne Modell
    "Automatisch" statt "Vorgabe von …", die Wichtigkeit eines Hinweises in
    Worten. Ausgefuehrt; je eine Kontrolle mit einem Mutanten aus der
    Quelle."""
    P, O, A_ = D.PILLE_Z, D.OFFEN_Z, D.ANGEDOCKT_Z
    quelle = lies(dash_pfad)

    def mutant(name, alt, neu):
        M = type(sys)(name)
        M.__file__ = dash_pfad
        exec(compile(quelle.replace(alt, neu), dash_pfad, "exec"),
             M.__dict__)
        return M

    cs = D._chip_soll
    faelle = {(P, 2): True, (P, 0): False, (O, 2): False, (A_, 5): False,
              (P, None): False, (O, 0): False}
    falsch = [(k, cs(*k)) for k, v in faelle.items() if cs(*k) != v]
    pruefe("P22 Chip mit der Zahl offener Hinweise nur in der Pille und nur "
           "bei > 0 (offen und angedockt steht sie an der Flagge)",
           not falsch, falsch)
    alt = "    return zustand == PILLE_Z and int(n or 0) > 0\n"
    M = mutant("p22_m1", alt, "    return int(n or 0) > 0\n")
    pruefe("P22 KONTROLLE: Chip in jedem Zustand (bis K12: die Zahl stand "
           "doppelt) -> die Zelle oben waere rot",
           quelle.count(alt) == 1 and M._chip_soll(O, 2) is True)

    ks = D._kontext_sichtbar
    faelle = {"65 % voll": True, "50 % voll": True, "49 % voll": False,
              "10 % voll": False, "1 234 Token": False, "": False,
              "100 % voll": True}
    falsch = [(t, ks(t)) for t, v in faelle.items() if ks(t) != v]
    pruefe("P22 Fuellstand des Chat-Gedaechtnisses erst ab %d %%, ohne "
           "Prozent (nur Token) nie" % D.KONTEXT_AB,
           D.KONTEXT_AB == 50 and not falsch, falsch)
    alt = ("    return bool(treffer) and int(treffer.group(1)) "
           ">= KONTEXT_AB\n")
    M = mutant("p22_m2", alt, "    return bool(text)\n")
    pruefe("P22 KONTROLLE: Anzeige bei jedem Text (bis K12: schon bei 10 %, "
           "sah aus wie ein Ladekreis) -> rot", quelle.count(alt) == 1
           and M._kontext_sichtbar("10 % voll") is True)

    mv = D._modell_oder_vorgabe
    codex = {"name": "Codex (Abo)"}
    texte = (mv("", codex), mv("", codex, knopf=True),
             mv(D.MODELLE_EINTRAG, codex), mv("gpt-5", codex))
    pruefe("P22 ohne Modell: gross 'Automatisch', auf dem Knopf 'Modell: "
           "automatisch' — nie 'Vorgabe'; ein Name bleibt",
           texte == ("Automatisch", "Modell: automatisch", "Automatisch",
                     "gpt-5"), texte)

    H = _hinweis_modul_laden()
    worte = [H.dringlichkeit_zeichen(n) for n in (1, 2, 3, 4, 5, None, "x")]
    pruefe("P22 Wichtigkeit eines Hinweises in Worten (gering/mittel/hoch), "
           "keine Punkte; kaputte Werte = mittel",
           worte == ["Wichtigkeit: gering"] * 2 + ["Wichtigkeit: mittel"]
           + ["Wichtigkeit: hoch"] * 2 + ["Wichtigkeit: mittel"] * 2
           and not any(c in "".join(worte) for c in "●○"), worte)
    pruefe("P22 statt 'anzoomen' steht 'nah heran' (mit Tooltip)",
           H.ZOOM_TEXT == "nah heran" and H.ZOOM_TIPP
           and 'QCheckBox("anzoomen")' not in lies(H.__file__), H.ZOOM_TEXT)


def _hinweis_modul_laden():
    import importlib.util
    pfad = os.path.join(A, "omcad_a_hinweise.py")
    spec = importlib.util.spec_from_file_location("p22_hinweise", pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if not bedingung:
        # `(detail,)`: ein Tupel als Detail warf sonst genau dann TypeError,
        # wenn die Zelle rot war (wie in test_a_live, 2026-09-26).
        print("  [FEHL] %s%s" % (titel, ("  — %s" % (detail,)) if detail
                                  else ""))
    return bool(bedingung)


def lies(pfad):
    with io.open(pfad, encoding="utf-8") as fh:
        return fh.read()


def sha(pfad):
    with open(pfad, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    # Ein Emoji oder ein Pfeil im Detail einer roten Zelle brach das Gate
    # sonst ab, wenn stdout nicht UTF-8 ist (Nacharbeit D, wie test_a_live).
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print("A-ONLY UI PROTOTYPE — Offline-Gate\n")

    # --- 1. Syntax --------------------------------------------------------
    for name in ("Open MCP CAD A.py", "omcad_a_dashboard.py",
                 "omcad_a_chat.py", "omcad_a_lokal.py"):
        pfad = os.path.join(A, name)
        try:
            ast.parse(lies(pfad))
            ok = True
        except SyntaxError as exc:
            ok = False
            print("      %s" % exc)
        pruefe("P1 %s ist syntaktisch gueltig" % name, ok)

    # --- 2. Die Abgrenzung ------------------------------------------------
    # Die A-Kopie des Kerns MUSS bytegleich zum gemeinsamen Kern sein — der
    # Prototyp darf sich nur im Einstieg unterscheiden.
    pruefe("P2 A-Kopie des Kerns ist bytegleich mit dem gemeinsamen Kern",
           sha(os.path.join(A, "omcad_bridge_core.py")) == sha(KERN),
           "sonst waere der Kern doch angefasst worden")
    for buchstabe in ("B", "C", "D"):
        ordner = os.path.join(PLUGIN, "Open MCP CAD %s" % buchstabe)
        pruefe("P2 %s benutzt weiterhin den gemeinsamen Kern" % buchstabe,
               sha(os.path.join(ordner, "omcad_bridge_core.py")) == sha(KERN))
        pruefe("P2 %s hat KEIN Dashboard bekommen" % buchstabe,
               not os.path.exists(os.path.join(ordner,
                                               "omcad_a_dashboard.py")))

    # --- 3. Der Einstieg --------------------------------------------------
    einstieg = lies(os.path.join(A, "Open MCP CAD A.py"))
    pruefe("P3 Einstieg ist als Prototyp gekennzeichnet",
           "A-ONLY UI PROTOTYPE" in einstieg)
    pruefe("P3 Einstieg laedt das Dashboard", "dashboard_laden" in einstieg)
    baum = ast.parse(einstieg)
    serve_fn = None
    for k in ast.walk(baum):
        if isinstance(k, ast.FunctionDef) and k.name == "serve":
            serve_fn = k
    quelle_serve = ast.get_source_segment(einstieg, serve_fn) or ""
    pruefe("P3 serve() ruft oeffnen() statt direkt kern.serve()",
           "oeffnen(" in quelle_serve)
    # Seit 2026-09-22 verbindet der Klick — aber NUR ueber das Dashboard
    # (`_verbinden`). Der alte Rueckfall `kern.serve(...)` im except-Zweig
    # ist weg: er startete den Dienst ohne Reservierung und ohne einen
    # laufenden zu erkennen. Ueber den AST, nicht den Text (Docstrings
    # nennen `kern.serve`). Das VERHALTEN misst test_offline A3e.
    _einstieg_serve = [k for k in ast.walk(baum)
                       if isinstance(k, ast.Call)
                       and isinstance(k.func, ast.Attribute)
                       and k.func.attr == "serve"]
    pruefe("P3 der Einstieg ruft kern.serve() nirgends, auch nicht als "
           "Rueckfall", not _einstieg_serve,
           "%d Aufrufe — ein zweiter Weg an _verbinden vorbei"
           % len(_einstieg_serve))

    # --- 4. Das Dashboard -------------------------------------------------
    dash = lies(os.path.join(A, "omcad_a_dashboard.py"))
    pruefe("P4 Dashboard ist als Prototyp gekennzeichnet",
           "A-ONLY UI PROTOTYPE" in dash)
    pruefe("P4 startet den Dienst mit cfg.fenster = False",
           "cfg.fenster = False" in dash,
           "sonst ginge zusaetzlich das alte Fenster auf")
    # Seit der Reservierung heisst der Aufruf `kern.serve(cfg,
    # reserved_socket=…)`. Die Zusicherung ist dieselbe: GENAU EIN Weg in
    # den Dienst, kein zweiter daneben.
    # Ueber den AST gezaehlt, nicht ueber den Text: `kern.serve(...)` steht
    # auch im Docstring von `_steckplatz_reservieren`, und eine Textsuche
    # zaehlt das mit. Der AST sieht nur echte Aufrufe.
    _serve_rufe = [k for k in ast.walk(ast.parse(dash))
                   if isinstance(k, ast.Call)
                   and isinstance(k.func, ast.Attribute)
                   and k.func.attr == "serve"]
    pruefe("P4 verbindet ausschliesslich ueber kern.serve()",
           len(_serve_rufe) == 1, "%d Aufrufe" % len(_serve_rufe))
    pruefe("P4 KEIN globales Stylesheet",
           "QApplication.instance().setStyleSheet" not in dash
           and "app.setStyleSheet" not in dash,
           "ein globales QSS wuerde Cadworks eigene Dialoge umfaerben")
    pruefe("P4 QSS haengt am eigenen objectName",
           "#OpenMcpCadA" in dash and 'setObjectName("OpenMcpCadA")' in dash)
    # Threads sind seit dem Verbindungs-Tab ERLAUBT — aber nur fuers Netz.
    # Die Regel, die zaehlt, ist nicht "kein Thread", sondern "kein cwapi3d
    # ausserhalb des Hauptthreads". Genau das prueft die naechste Zusicherung,
    # und sie ist die strengere: das Dashboard ruft cwapi3d NIRGENDS direkt.
    pruefe("P4 Modell-Arbeit laeuft nie in einem eigenen Thread",
           "job_queue.put" in dash
           and "element_controller" not in dash,
           "Netz-Threads sind erlaubt, cwapi3d-Threads nicht")
    # Praezise statt per Zeichenkette: seit der Notiz-Ablage steht
    # `utility_controller` als eingebetteter CODESTRING im Dashboard — und
    # genau der laeuft ueber die Warteschlange im Cadwork-Hauptthread, ist
    # also erlaubt. Verboten ist ein IMPORT im Dashboard selbst. Der AST
    # unterscheidet beides exakt, eine Textsuche nicht.
    import ast as _ast
    cwapi = {"element_controller", "utility_controller", "material_controller",
             "visualization_controller", "attribute_controller",
             "geometry_controller", "cadwork"}
    importiert = set()
    for knoten in _ast.walk(_ast.parse(dash)):
        if isinstance(knoten, _ast.Import):
            importiert.update(a.name.split(".")[0] for a in knoten.names)
        elif isinstance(knoten, _ast.ImportFrom) and knoten.module:
            importiert.add(knoten.module.split(".")[0])
    pruefe("P4 importiert cwapi3d NIRGENDS selbst",
           not (importiert & cwapi),
           "verboten waere: %s — Modell-Arbeit laeuft ueber die "
           "Warteschlange" % sorted(importiert & cwapi))
    pruefe("P4 Modell-Arbeit geht ueber die Warteschlange",
           "job_queue.put" in dash)
    # Seit 2026-09-25 liegt der Zustand in `sys.modules[ANKER]`; das
    # Attribut an der QApplication bleibt fuer Docks aelterer Fassungen.
    # Das VERHALTEN (neuer App-Wrapper, zweiter Klick) misst test_a_live L32.
    pruefe("P4 Zustand haengt nicht am Modul (Anker, altes Attribut)",
           "_omcad_a_prototyp" in dash and "sys.modules.get(ANKER)" in dash,
           "sonst faende ein zweiter Klick das Dock nicht wieder")
    pruefe("P4 Port und Instanz kommen aus dem Einstieg, nicht aus dem "
           "Dashboard",
           "53127" not in dash,
           "keine zweite Quelle fuer die Portnummer")
    # Phase 2 ist da: EIN Knopf fuer alle Cadwork-Instanzen, also sucht das
    # Dashboard den ersten freien Steckplatz. Die Portnummern stehen
    # trotzdem NICHT hier — sie kommen aus dem Verbindungs-Client, damit es
    # weiterhin nur EINE Quelle fuer die vier Steckplaetze gibt.
    pruefe("P4 keine Portnummern im Dashboard",
           "53127" not in dash and "53128" not in dash
           and "53129" not in dash and "53130" not in dash,
           "die vier Steckplaetze stehen im Verbindungs-Client")
    # Der Steckplatz wird RESERVIERT, nicht erfragt: gebunden mit
    # SO_EXCLUSIVEADDRUSE, und der fertige Socket geht an serve(). Die alte
    # Fassung fragte per `ping` — das beantwortet die falsche Frage (ein
    # Port kann von etwas belegt sein, das nicht antwortet) und laesst
    # zwischen Antwort und Binden ein Rennen offen.
    pruefe("P4 reserviert den Steckplatz, statt ihn zu erfragen",
           "def _steckplatz_reservieren" in dash
           and "SO_EXCLUSIVEADDRUSE" in dash
           and "reserved_socket=" in dash,
           "sonst kann nur EIN Cadwork eine Verbindung starten")
    pruefe("P4 die benannten Steckplaetze kommen aus dem Client",
           "client.STECKPLAETZE" in dash,
           "EINE Quelle fuer ihre Namen und Ports")
    pruefe("P4 ein fehlgeschlagener Start gibt den Port wieder frei",
           "reservierung.close()" in dash,
           "sonst bliebe er belegt — von einem Steckplatz, den es nicht gibt")
    pruefe("P4 sagt es ehrlich, wenn alle Steckplaetze belegt sind",
           "Steckplätze sind belegt" in dash
           and "kern.PORT_BIS - kern.PORT_VON + 1" in dash,
           "die Zahl muss aus der Quelle kommen, nicht im Text stehen — "
           "sonst meldet sie nach jeder Erweiterung etwas Falsches")
    # Die Wahl (2026-08-15): ein GEWUENSCHTER Steckplatz darf nicht still
    # ausweichen. Das ist die eigentliche Zusicherung — ein Ausweichen
    # zeichnete in eine andere Datei als gemeint, und genau davor schuetzt
    # die ganze Steckplatz-Zuordnung.
    # GEMESSEN statt gegrept: die Funktion wird ausgefuehrt, mit einem
    # Wunsch-Steckplatz, dessen Port belegt ist. Sie muss (None, None, None)
    # liefern — nicht einen anderen Platz. Eine Textsuche haette nach der
    # Umstellung auf die Reservierung nur gemeldet, dass sich der Wortlaut
    # geaendert hat; sie kann ueber das Verhalten nichts sagen.
    _resv = _funktion_laden(dash, "_steckplatz_reservieren",
                            "def _steckplatz_reservieren",
                            "def _verbinden")
    pruefe("P5 die Reservierung laesst sich ausfuehren", _resv is not None)
    if _resv is not None:
        class _Client:
            HOST = "127.0.0.1"
            STECKPLAETZE = []

        # Beide Testports ephemer, aber NIE im Cadwork-Bereich. Vorher war Y
        # Port 0 ("beliebig") — dann band die Reservierung selbst irgendwo,
        # auch mitten in 53127..53199.
        _belegt = _ephemerer_socket()
        _p = _belegt.getsockname()[1]
        _frei = _ephemerer_socket()
        _py = _frei.getsockname()[1]
        _frei.close()
        _gebunden = []
        try:
            _c = _Client()
            _c.STECKPLAETZE = [("X", _p), ("Y", _py)]   # Y ist frei
            i, po, so = _resv(_c, wunsch="X")
            if so is not None:
                so.close()
            pruefe("P5 ein gewaehlter Steckplatz weicht NICHT aus",
                   i is None and po is None and so is None,
                   "bekam %r/%r — ein Ausweichen zeichnete in eine andere "
                   "Datei als gemeint" % (i, po))
            # KONTROLLE: OHNE Wunsch muss dieselbe Funktion ausweichen,
            # sonst misst die Pruefung oben nur, dass sie gar nichts findet.
            i2, po2, so2 = _resv(_c, wunsch=None)
            if so2 is not None:
                _gebunden.append(so2.getsockname()[1])
                so2.close()
            pruefe("P5 KONTROLLE: ohne Wunsch wird ausgewichen",
                   i2 == "Y", "bekam %r" % (i2,))
        finally:
            _belegt.close()
        # Gemessen an dem, was wirklich gebunden war: der belegte Port und
        # der, den die ECHTE Reservierung gebunden hat.
        pruefe("P5 kein Testport im Cadwork-Bereich",
               _ausserhalb([_p] + _gebunden),
               "belegt %d, reserviert %s" % (_p, _gebunden))
        pruefe("P5 KONTROLLE: ein Port aus dem Kernbereich faellt auf",
               not _ausserhalb([_p] + sorted(_CADWORK_PORTS)[:1]),
               "sonst ist der Bereich leer und die Zeile oben misst nichts")
        try:
            _ephemerer_socket(verboten=range(1, 65536)).close()
            _k = "bekam einen Port"
        except RuntimeError:
            _k = "wirft"
        pruefe("P5 KONTROLLE: ist alles verboten, gibt _ephemerer_socket auf",
               _k == "wirft", "%s — sonst prueft er den Bereich gar nicht" % _k)
    pruefe("P4 die Wahl steht in der Oberflaeche",
           "steckplatz_wahl" in dash
           and "automatisch (erster freier)" in dash)

    # --- 5. Trennen ist sicher -------------------------------------------
    pruefe("P5 laufender Auftrag wird NICHT hart abgebrochen",
           "beenden_nach_auftrag = True" in dash
           and "BESCHAEFTIGT" in dash,
           "bei laufendem Auftrag nur 'nach Auftrag trennen'")
    pruefe("P5 zweites Verbinden wird abgefangen",
           'z["dienst"] is not None and not z["dienst"].beenden' in dash,
           "sonst zweiter Dienst auf Port 53127")

    # --- 6. Zustaende vollstaendig ---------------------------------------
    kern_quelle = lies(KERN)
    zt = kern_quelle.split("ZUSTAND_TEXT = {", 1)[1].split("}", 1)[0]
    zustaende = set()
    for zeile in zt.splitlines():
        if '"' in zeile:
            zustaende.add(zeile.split('"')[1])
    fehlend = sorted(s for s in zustaende if '"%s":' % s not in dash)
    pruefe("P6 alle Zustaende des Kerns haben eine Pille",
           not fehlend, "ohne Zuordnung: %s" % fehlend)

    # --- 7. Tab "Verbindungen" -------------------------------------------
    vc_pfad = os.path.join(A, "omcad_verbindungen_client.py")
    pruefe("P7 der Netzwerkteil liegt IM Pluginordner",
           os.path.exists(vc_pfad),
           "sonst haette der Tab eine harte Abhaengigkeit auf das Repo")
    vc = lies(vc_pfad)
    pruefe("P7 Herkunft ist benannt",
           "scripts/connect_client.py" in vc,
           "eine Kopie ohne Herkunft driftet unbemerkt auseinander")
    pruefe("P7 kein cwapi3d im Netzwerkteil",
           "cwapi3d" not in vc and "element_controller" not in vc,
           "Ueberwachung darf das Modell nie anfassen")

    # Der teuer erkaufte Unterschied: ein Timeout ist NICHT "Aus".
    pruefe("P7 getrennte Zeitgrenzen fuer Verbindung und Antwort",
           "VERBINDUNGS_TIMEOUT_S" in vc and "STATUS_TIMEOUT_S" in vc)
    pruefe("P7 'keine Antwort' ist ein eigener Zustand, nicht 'Aus'",
           '"no_answer"' in vc and vc.count('"unreachable"') >= 2
           and 'ZUSTAND_TEXT' in vc,
           "ein haengender Hauptthread darf nie als 'Aus' erscheinen")
    pruefe("P7 altes Plugin wird als 'veraltet' erkannt, nicht als Stoerung",
           '"veraltet"' in vc and "unknown_method" in vc)
    pruefe("P7 alte Plugins werden geschont (Schonfrist)",
           "VERALTET_SCHONFRIST_S" in vc,
           "sonst Dauerstrom in einen fremden Cadwork-Hauptthread")
    pruefe("P7 alle vier werden PARALLEL abgefragt",
           "threading.Thread" in vc,
           "seriell waeren im schlimmsten Fall vier Timeouts")
    for m in ("pause", "resume", "shutdown_after_current", "shutdown"):
        pruefe("P7 Steuerung benutzt die vorhandene Methode %r" % m,
               '"%s"' % m in vc)

    # Der Monitor im Dashboard
    pruefe("P7 Abfrage laeuft im Hintergrund, nicht im Qt-Takt",
           "Open-MCP-CAD-A-Monitor" in dash and "daemon=True" in dash,
           "eine Statusabfrage im 500-ms-Timer wuerde Cadwork anhalten")
    pruefe("P7 nur EIN Monitor-Thread, auch nach mehreren Plugin-Klicks",
           "is_alive()" in dash,
           "sonst haette man nach fuenf Klicks fuenf Threads")
    pruefe("P7 der Thread ruehrt KEINE Widgets an",
           'z["monitor_daten"] = client.alle_status()' in dash,
           "er weist nur Daten zu; gezeichnet wird im Qt-Takt")
    pruefe("P7 gezeichnet wird ausschliesslich im Qt-Takt",
           "_verbindungen_zeichnen(z)" in dash
           and "def _verbindungen_zeichnen" in dash)
    # Praezise statt ueber die ganze Datei: die Frage ist, ob der Aufruf
    # INNERHALB von `_auffrischen` vor dem frueh-return steht. Der alte
    # Index-Vergleich ueber den gesamten Text brach, sobald irgendwo sonst
    # ein "if not verbunden:" auftauchte — er mass die Datei, nicht die
    # Funktion.
    def quelle_von(name, text=None):
        text = dash if text is None else text
        for knoten in ast.walk(ast.parse(text)):
            if isinstance(knoten, ast.FunctionDef) and knoten.name == name:
                return ast.get_source_segment(text, knoten) or ""
        return ""

    auffrischen = quelle_von("_auffrischen")
    pruefe("P7 der Tab arbeitet auch, wenn A selbst aus ist",
           ("_verbindungen_zeichnen(z)" in auffrischen
            and auffrischen.index("_verbindungen_zeichnen(z)")
            < auffrischen.index("if not verbunden:")),
           "sonst saehe man B/C/D nie, solange man nicht verbunden ist")
    pruefe("P7 KONTROLLE: die Reihenfolge-Pruefung misst die FUNKTION",
           "def _auffrischen" not in auffrischen[1:]
           and len(auffrischen) < len(dash) / 2,
           "sonst misst sie wieder die ganze Datei")
    # Seit 2026-09-23 gibt es Karten nur fuer VERBUNDENE Steckplaetze — und
    # damit gar keinen Startknopf mehr in einer Karte (verbunden wird mit dem
    # Plugin-Klick im jeweiligen Cadwork). Das Verhalten misst test_a_live
    # L13; hier nur, dass die Steuerung JEDEN Steckplatz erreicht.
    _vc_spec = importlib.util.spec_from_file_location("p7_client", vc_pfad)
    _vc = importlib.util.module_from_spec(_vc_spec)
    _vc_spec.loader.exec_module(_vc)
    _gerufen = []
    _vc.anfrage = lambda port, methode, *a, **k: _gerufen.append(
        (port, methode)) or {}
    _vc.pausieren("53153")
    _vc.fortsetzen("A")
    _vc.jetzt_beenden(53131)
    pruefe("P7 Steuerung erreicht auch Steckplaetze jenseits von F",
           _gerufen == [(53153, "pause"), (53127, "resume"),
                        (53131, "shutdown")], _gerufen)
    pruefe("P7 KONTROLLE: die alte Tabelle kannte 53153 nicht",
           "53153" not in _vc.PORT_VON_INSTANZ,
           "sonst misst die Zeile darueber nichts Neues")
    # 2026-09-24: ein Registry-Eintrag auf 53911 mit der Kennung "A" wurde
    # bei 53127 abgefragt — A stand doppelt im Dock.
    _gefragt = []
    _vc.anfrage = lambda port, methode, *a, **k: _gefragt.append(port) or {
        "ok": False, "error": "unreachable"}
    _vc.alle_steckplaetze = lambda: [("A", 53127), ("A", 53911)]
    _vc._letzter_status.clear()
    _vc.alle_status(timeout=0.2)
    pruefe("P7 Registry-Eintraege werden ueber ihren PORT abgefragt",
           sorted(_gefragt) == [53127, 53911], sorted(_gefragt))
    _gefragt.clear()
    _vc.status("A", timeout=0.2)
    pruefe("P7 KONTROLLE: ueber den Buchstaben ginge 'A' an 53127",
           _gefragt == [53127], _gefragt)
    pruefe("P7 'Jetzt beenden' ist waehrend eines Auftrags gesperrt",
           'zustand not in client.BESCHAEFTIGT' in dash,
           "ein laufender Auftrag wird nie hart abgebrochen")
    pruefe("P7 Steuerbefehle blockieren den Qt-Thread nicht",
           "def im_thread(fn)" in dash,
           "sie duerfen bis zum Steuer-Timeout dauern")

    # --- 8. Hinweise und Briefkasten ueberleben den Neustart -------------
    pruefe("P8 Notizen werden NEBEN der Cadwork-Datei abgelegt",
           ".omcad.json" in dash and "get_3d_file_path" in dash,
           "so wandern sie mit dem Projekt mit")
    pruefe("P8 der Dokumentpfad kommt ueber die Warteschlange",
           'kern.Job(None, "execute_cwapi3d"' in dash,
           "cwapi3d nie direkt aus der Oberflaeche")
    pruefe("P8 Ausweichort, wenn der Projektordner nicht beschreibbar ist",
           "AUSWEICH_ORDNER" in dash and "os.access" in dash,
           "sonst gingen Notizen auf Netzlaufwerken still verloren")
    pruefe("P8 Zaehler werden mitgeladen",
           "hinweis_zaehler = max" in dash
           and "nachricht_zaehler = max" in dash,
           "sonst vergibt der Kern Nummern doppelt und 'Erledigt' trifft "
           "den falschen Hinweis")
    pruefe("P8 wird nur bei Aenderung geschrieben",
           "speicher_stempel" in dash and "SPEICHER_TAKT_S" in dash,
           "kein Dauerschreiben im 500-ms-Takt")
    pruefe("P8 nicht serialisierbarer Kontext killt die Datei nicht",
           "default=str" in dash,
           "der Briefkasten traegt Cadwork-Facettenlisten mit")

    # --- 9. Tab "Chat" ----------------------------------------------------
    chat_pfad = os.path.join(A, "omcad_a_chat.py")
    pruefe("P9 der Gespraechsteil liegt IM Pluginordner",
           os.path.exists(chat_pfad),
           "sonst haette der Tab eine harte Abhaengigkeit auf das Repo")
    chat = lies(chat_pfad)

    # Eine Zusicherung, die im FLIESSTEXT fuendig wird, prueft nichts: die
    # Kontrollzellen haben genau das zweimal aufgedeckt — "taskkill" stand im
    # Docstring, also bestand die Pruefung auch, nachdem der Aufruf entfernt
    # war. Deshalb gibt es fuer solche Fragen eine prosafreie Fassung:
    # Kommentare und Docstrings raus, echte Zeichenketten drin.
    def ohne_prosa(quelle):
        baum = ast.parse(quelle)
        for knoten in ast.walk(baum):
            if isinstance(knoten, (ast.Module, ast.FunctionDef,
                                   ast.AsyncFunctionDef, ast.ClassDef)):
                koerper = getattr(knoten, "body", [])
                if (len(koerper) > 1 and isinstance(koerper[0], ast.Expr)
                        and isinstance(koerper[0].value, ast.Constant)
                        and isinstance(koerper[0].value.value, str)):
                    koerper.pop(0)
        # ast.unparse vereinheitlicht auf einfache Anfuehrungszeichen —
        # die Nadeln unten sind deshalb ebenfalls einfach gesetzt.
        return ast.unparse(baum)

    chat_code = ohne_prosa(chat)

    def zuweisungen(quelle):
        return {ziel.id for knoten in ast.walk(ast.parse(quelle))
                if isinstance(knoten, ast.Assign)
                for ziel in knoten.targets if isinstance(ziel, ast.Name)}

    chat_namen = zuweisungen(chat)

    # -- 9a. Die Freigabe: zwei Schalter, die nur ZUSAMMEN halten ----------
    # Gemessen am 2026-08-09. Fehlt der zweite, springt das Gate nur bei den
    # Aufrufen an, die das CLI ohnehin fuer heikel haelt — ein schlichtes
    # `echo` lief MIT Bruecke genauso still durch wie ohne.
    pruefe("P9 WER gefragt wird: --permission-prompt-tool stdio",
           "'--permission-prompt-tool', 'stdio'" in chat_code,
           "ohne diesen Schalter fragt im Kopflos-Betrieb niemand")
    pruefe("P9 WAS gefragt wird: ask-Sammelregel",
           "'ask': ['*']" in chat_code,
           "sonst bleibt das Gate bei genau den stillen Faellen stumm")
    # Die Abkuerzung, die die Rueckfrage abschaltet — in KEINER Schreibweise.
    # Hier zaehlt der CODE: im Fliesstext darf darueber geschrieben werden,
    # im ausgefuehrten Teil nicht.
    dash_code = ohne_prosa(dash)
    for verboten in ("dangerously-skip-permissions", "bypassPermissions",
                     "dangerouslySkipPermissions"):
        pruefe("P9 %r kommt im Code nicht vor" % verboten,
               verboten not in chat_code and verboten not in dash_code,
               "das ist die Abkuerzung, die das Gate abschaltet")
    # RICHTIGSTELLUNG zum Uebergabedokument: dort stand, das Gate solle
    # pruefen, dass `--permission-mode manual` GESETZT wird. Gemessen wird
    # der Schalter im Kopflos-Betrieb aber IMMER verworfen (das
    # init-Ereignis meldet ausnahmslos "default") — auch zusammen mit der
    # Bruecke und auch als permissions.defaultMode. Eine Pruefung darauf
    # haette Sicherheit vorgetaeuscht, die es nicht gibt.
    pruefe("P9 verlaesst sich NICHT auf --permission-mode",
           '"--permission-mode"' not in chat,
           "der Schalter wird im -p-Betrieb still verworfen")

    # -- 9b. cwapi3d im Gespraechsteil — MIT Kontrollzelle -----------------
    def importe(quelle):
        gefunden = set()
        for knoten in ast.walk(ast.parse(quelle)):
            if isinstance(knoten, ast.Import):
                gefunden.update(a.name.split(".")[0] for a in knoten.names)
            elif isinstance(knoten, ast.ImportFrom) and knoten.module:
                gefunden.add(knoten.module.split(".")[0])
        return gefunden

    pruefe("P9 der Gespraechsteil importiert cwapi3d NIRGENDS",
           not (importe(chat) & cwapi),
           "er darf das Modell nie anfassen")
    # KONTROLLZELLE: an einer vergifteten Kopie MUSS die Pruefung anspringen.
    # Ohne sie waere nicht zu unterscheiden, ob die Pruefung haelt oder bloss
    # schweigt (zweimal passiert am 2026-08-06).
    pruefe("P9 KONTROLLE: die cwapi3d-Pruefung springt wirklich an",
           bool(importe("import element_controller\n" + chat) & cwapi),
           "eine Pruefung, die nie anspringt, ist keine Pruefung")
    pruefe("P9 der Gespraechsteil kennt kein Qt",
           not any(q in chat for q in ("PyQt6", "PyQt5", "omcad_qt")),
           "so laesst er sich ohne Cadwork pruefen — und genau das wurde er")

    # -- 9c. Kein Warten im Qt-Takt ---------------------------------------
    # Wartet der Chat-Code im Qt-Takt auf Claude, laeuft der Auftragstakt
    # nicht, der Zeichenauftrag verlaesst die Warteschlange nie, Claude
    # wartet auf sein Ergebnis — und Cadwork steht.
    QT_PFAD = ("_tab_chat", "_chat_zeichnen",
               "_chat_beenden", "_freigabe_karte", "_trennen", "_auffrischen",
               # seit 2026-09-25 (Robustheit des Docks)
               "_zustand_vorgabe", "_dock_abbauen", "_chat_takt_starten",
               "_tab_chat_oder_ersatz", "_chat_zeichenstand",
               "_chat_veraltet", "_fehler_zeigen", "_zeile_rot",
               "_fehler_steht", "_fehler_quittieren", "_sicher", "_melden",
               "_stderr", "_nach_zug_einloesen",
               # seit 2026-09-26 (S5/S6, lokale Modelle): Einstellungsseite,
               # Schluessel, Ollama/LM Studio — alles im Qt-Takt oder Slot
               "_einstellungen_bauen", "_einstellungen_zeigen",
               "_einstellungen_pruefen", "_technik_umschalten",
               "_technik_anstossen", "_technik_zeichnen", "_wer_zeigen",
               "_schluessel_zeigen", "_schluessel_da_pruefen",
               "_schluessel_takt", "_schluessel_speichern",
               "_schluessel_aendern", "_schluessel_entfernen",
               "_anbieter_gewechselt", "_modelle_abfragen",
               "_lokal_pruefen", "_lokal_takt", "_lokal_zeichnen",
               "_lokal_fragen", "_lokal_frage_weg", "_lokal_im_thread",
               "_lokal_installieren", "_lokal_starten",
               # Nacharbeit Etappe B: Freigabe-Hinweis auf der Seite
               "_zum_chat", "_einst_freigabe_zeigen",
               # S7/S8: die erste Nachricht startet, "Neuer Chat",
               # "Beenden", Fehlerzeile, Zeile "was laeuft", Hoehen
               "_chat_starten", "_chat_senden", "_chat_neu",
               "_chat_beenden_geklickt", "_chat_fehler_zeigen",
               "_chat_fehler_quittieren", "_art_zeigen",
               "_hoehe_nach_inhalt", "_freigabe_hoehe",
               # Etappe D (S9/S10/S12): Chatliste, geoeffneter Chat,
               # Kontextanzeige, Ordnerwahl
               "_liste_auffrischen", "_liste_holen", "_liste_takt",
               "_sitzung_oeffnen", "_kontext_text", "_kontext_zeigen",
               "_ordner_zeigen", "_ordner_dialog", "_ordner_waehlen",
               "_ordner_gewaehlt", "_ordner_vergessen", "_umbrechbar",
               # Chatfenster (2026-09-27): Modi (K1), eigenes Fenster und
               # kompakter Monitor (K2)
               "_modus_waehlen", "_modus_zeigen", "_modus_wirksam",
               "_modus_hinweis", "_chat_oeffnen",
               "_chat_einstellungen_zeigen", "_dialog_eltern",
               # K3: Leiste, Aufklapper, Ordner-Kopf
               "_qt_klassen", "_aufklapper_zeigen", "_modus_aufklappen",
               "_modell_aufklappen", "_modell_aus_liste", "_anderes_modell",
               "_modell_knopf_zeigen", "_ordner_aufklappen",
               "_zusatz_dialog", "_zusatz_waehlen", "_zusatz_gewaehlt",
               "_zusatz_entfernen", "_zusatz_merken", "_zusatz_zeigen",
               # K4: Anhaenge (Lesen und Kodieren NUR im Nebenthread:
               # `_anhang_datei_lesen`, `_bild_kodieren` stehen hier nicht)
               "_anhang_aus_mime", "_anhang_eintrag", "_anhaenge_laden",
               "_bild_einfuegen", "_anhang_entfernen", "_anhaenge_takt",
               "_anhaenge_zeigen", "_anhang_dialog", "_anhang_waehlen",
               "_zwischenablage_einfuegen", "_plus_aufklappen",
               "_lokale_dateien", "_anhang_nutzlast",
               # 2026-09-29: erster Kontakt (das Nachsehen selbst,
               # `_einstieg_wege`, laeuft NUR im Nebenthread)
               "_einstieg_bauen", "_einstieg_takt", "_einstieg_zeigen",
               "_einstieg_pruefen", "_einstieg_weg", "_anbieter_setzen",
               "_anleitung_oeffnen",
               # K10 (2026-10-01): Nachsehen nach dem Zeigen, Zeilen ins Log
               "_monitor_ziel", "_ort_spaeter", "_ort_nachsehen",
               "_lage_text", "_ort_protokoll", "_ort_ausgeben",
               "_schwebend_ziel", "_post_zeichnen",
               # K12 (2026-10-07): das EINE Fenster (Kopf, Koerper,
               # Zustaende, Lage), der Briefkasten als Segment, die
               # Einstellungsseite, der Popover, die Arbeitsanzeige
               "_fenster_bauen", "_kopf_bauen", "_koerper_bauen",
               "_briefkasten_bauen", "_einstellungen_bauen",
               "_fenster_aktion", "_zustand_setzen", "_fenster_lage",
               "_fenster_schwebt", "_fenster_sichtbar", "_pille_statt_nichts",
               "_angedockt_pruefen", "_kopf_anpassen", "_kopf_zeigen",
               "_segment_waehlen", "_seite_gewechselt", "_hinweise_zeigen",
               "_hoechstmasse", "_mehr_aufklappen", "_technik_zeigen",
               "_pille_setzen", "_pille_tipp", "_hinweis_zahl_zeigen",
               "_kontext_setzen", "_chatknopf_zeigen", "_chat_stand",
               "_abloesen_beim_ziehen", "_pille_ort_merken",
               "_fenster_zurueckholen", "_eingabe_fokus",
               "_popover_bauen", "_popover_kachel", "_popover_fuellen",
               "_modell_liste_zeigen", "_stufe_zurueck",
               "_anzeige_bauen", "_anzeige_haken", "_anzeige_zeichnen",
               "_anzeige_setzen", "_anzeige_platzieren", "_anzeige_knopf",
               "_anzeige_takt", "_haken_setzen", "_briefkasten_zeigen")
    BLOCKIEREND = {"wait", "communicate", "readline", "read", "join"}

    # Ein Name, den es nicht gibt, wird unten STILL uebergangen — ein
    # Tippfehler hier hiesse "geprueft" ohne Pruefung. Also nachsehen.
    def fehlende_defs(quelle, namen):
        da = {k.name for k in ast.parse(quelle).body
              if isinstance(k, ast.FunctionDef)}
        return [n for n in namen if n not in da]

    pruefe("P9 jeder Name in QT_PFAD ist eine Funktion des Dashboards",
           fehlende_defs(dash, QT_PFAD) == [],
           "fehlt: %s" % fehlende_defs(dash, QT_PFAD))
    pruefe("P9 KONTROLLE: ein erfundener Name faellt auf",
           fehlende_defs(dash, QT_PFAD + ("_gibt_es_nicht",))
           == ["_gibt_es_nicht"])

    def blockierer(quelle, namen):
        treffer = []
        for knoten in ast.walk(ast.parse(quelle)):
            if not isinstance(knoten, ast.FunctionDef) or knoten.name not in namen:
                continue
            for inner in ast.walk(knoten):
                if not (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in BLOCKIEREND):
                    continue
                # `" · ".join(teile)` blockiert nichts — `thread.join()`
                # schon. Der Unterschied steht am Empfaenger: eine
                # Zeichenkette ist nie ein Thread.
                if isinstance(inner.func.value, ast.Constant) \
                        and isinstance(inner.func.value.value, str):
                    continue
                treffer.append("%s -> .%s()" % (knoten.name,
                                               inner.func.attr))
        return treffer

    offen = blockierer(dash, QT_PFAD)
    pruefe("P9 kein blockierender Aufruf im Qt-Pfad",
           not offen, "gefunden: %s" % offen)
    # KONTROLLZELLE fuer den Sucher selbst.
    pruefe("P9 KONTROLLE: der Sucher findet ein eingebautes .wait()",
           blockierer("def _chat_zeichnen(z):\n    proc.wait()\n",
                      QT_PFAD) == ["_chat_zeichnen -> .wait()"],
           "sonst besteht der Test, weil er nichts sucht")
    pruefe("P9 KONTROLLE: er findet auch ein thread.join()",
           blockierer("def _chat_zeichnen(z):\n    t.join()\n",
                      QT_PFAD) == ["_chat_zeichnen -> .join()"],
           "die Ausnahme fuer Zeichenketten darf Threads nicht mitbefreien")
    pruefe("P9 KONTROLLE: ein String-join ist KEIN Treffer",
           blockierer("def _chat_zeichnen(z):\n    x = ' '.join(t)\n",
                      QT_PFAD) == [],
           "sonst zwingt der Test zu umstaendlichem Code")

    # -- 9c2. Fassungen: Dashboard, Chat und Anbieter passen zusammen ------
    # Das Dashboard verweigert den Chat, wenn `SCHNITTSTELLE` in Chat oder
    # Anbieter nicht zu seiner Erwartung passt (Update ohne Neustart). Hebt
    # jemand nur EINE Seite, verweigerte es ihn auch nach dem Neustart fuer
    # immer. Gemessen am Verhalten: das Dashboard-Modul importiert Qt erst
    # in den Funktionen, laesst sich hier also ganz laden und fragen.
    _vor = {n: sys.modules.get(n) for n in ("omcad_a_chat_A",
                                            "omcad_a_anbieter_A")}
    try:
        _dspec = importlib.util.spec_from_file_location(
            "p9_fassung_dash", os.path.join(A, "omcad_a_dashboard.py"))
        _dmod = importlib.util.module_from_spec(_dspec)
        _dspec.loader.exec_module(_dmod)
        for _n in _vor:
            sys.modules.pop(_n, None)             # frisch von der Platte
        _urteil = _dmod._chat_veraltet()
        pruefe("P9 Chat und Anbieter auf der Platte passen zum Dashboard",
               _urteil is None, repr(_urteil))
        _dmod.ANBIETER_SCHNITTSTELLE += 1
        pruefe("P9 KONTROLLE: eine abweichende Fassung wird erkannt",
               _dmod._chat_veraltet() == _dmod.CHAT_VERALTET,
               repr(_dmod._chat_veraltet()))
    finally:
        for _n, _m in _vor.items():
            if _m is None:
                sys.modules.pop(_n, None)
            else:
                sys.modules[_n] = _m

    # -- 9d. Der Leserthread ----------------------------------------------
    # stderr MUSS mitgelesen werden — aus zwei Gruenden. Sichtbarkeit: lehnt
    # das CLI einen Modellnamen ab, kommt auf stdout nie ein `result`, der
    # Chat sah wortlos tot aus. Und schwerer: eine nicht gelesene Pipe laeuft
    # nach ~64 kB voll, dann blockiert das Kind beim Schreiben.
    pruefe("P9 stderr wird mitgelesen (sonst Deadlock bei voller Pipe)",
           "def _fehlerleser_starten" in chat_code
           and "_fehlerleser_starten(chat)" in ohne_prosa(
               quelle_von("starten", chat)),
           "stderr=subprocess.PIPE ohne Leser ist der klassische Popen-Haenger")
    pruefe("P9 der stderr-Leser ist ein Daemon und haelt Cadwork nie fest",
           "daemon=True" in quelle_von("_fehlerleser_starten", chat))
    pruefe("P9 der Grund fuer 'startet nicht' erreicht die Oberflaeche",
           "letzter_fehler" in chat_code
           and "letzter_fehler(chat)" in ohne_prosa(
               quelle_von("_chat_zeichnen")),
           "sonst bleibt ein abgelehnter Modellname unsichtbar")

    pruefe("P9 genau EIN Leserthread, auch nach mehreren Plugin-Klicks",
           "Open-MCP-CAD-A-Chat" in chat and "alt.is_alive()" in chat,
           "sonst haette man nach fuenf Klicks fuenf Leser auf einer Pipe")
    pruefe("P9 der Leser ist ein Daemon",
           'name="Open-MCP-CAD-A-Chat", daemon=True' in chat,
           "er darf Cadwork beim Schliessen nie festhalten")
    pruefe("P9 zwei Schreiber auf stdin sind gegeneinander verriegelt",
           "chat[\"schloss\"]" in chat and "threading.Lock()" in chat,
           "Oberflaeche und Leser schreiben beide — sonst kaputtes JSON")

    # -- 9e. Dokument- und Steckplatz-Riegel -------------------------------
    pruefe("P9 der Chat bekommt Steckplatz und Datei mit",
           'OPEN_MCP_CAD_PORT' in chat and 'OPEN_MCP_CAD_EXPECT_DOC' in chat,
           "so kann er gar nicht in die falsche Cadwork-Datei zeichnen")
    # Derselbe Vertrag wie beim Verbindungs-Tab: der Chat muss auch dann
    # gezeichnet werden, wenn A aus ist — sonst friert der Tab ein, statt
    # "Zuerst verbinden" zu sagen.
    pruefe("P9 der Chat wird VOR dem frueh-return gezeichnet",
           ("_chat_zeichnen(z)" in auffrischen
            and auffrischen.index("_chat_zeichnen(z)")
            < auffrischen.index("if not verbunden:")),
           "sonst zeigt der Tab ohne Verbindung gar nichts")
    # Der Arbeitsordner des Chats — GEMESSEN, nicht gegrept.
    #
    # Bis 2026-09-20 stand hier eine Textsuche nach "OPEN_MCP_CAD_REPO" und
    # "def arbeitsordner". Beides war vorhanden, waehrend die Funktion auf
    # das FALSCHE Verzeichnis zeigte: bei der Umbenennung des Repos sind die
    # drei fest verdrahteten Benutzerpfade mitgewandert, aus
    # der alte Repo-Name wurde zu "…\projekte\open-mcp-cad". Der Chat
    # haette im Bruecken-Repo gearbeitet statt im Projekt des Nutzers.
    # Eine Textsuche kann das nicht sehen — sie prueft, DASS etwas dasteht,
    # nicht WOHIN es zeigt.
    _ao = _arbeitsordner_laden(dash, A)   # A = der Plugin-Ordner, oben gesetzt
    pruefe("P9 der Chat hat einen Arbeitsordner-Entscheider",
           _ao is not None,
           "def arbeitsordner() in omcad_a_dashboard.py")
    if _ao is not None:
        _umg = os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
        try:
            pruefe("P9 ohne Angabe wird NICHT geraten",
                   _ao() is None,
                   "ein geratener Ordner ist schlimmer als keiner — die "
                   "Gespraeche landen dann in einer fremden Sitzungsliste")
            os.environ["OPEN_MCP_CAD_PROJEKT"] = REPO
            pruefe("P9 die Umgebungsvariable wird genommen", _ao() == REPO)
            os.environ["OPEN_MCP_CAD_PROJEKT"] = os.path.join(REPO, "gibt_es_nicht")
            pruefe("P9 ein falscher Pfad gibt None, statt ihn zu nehmen",
                   _ao() is None)
        finally:
            os.environ.pop("OPEN_MCP_CAD_PROJEKT", None)
            if _umg is not None:
                os.environ["OPEN_MCP_CAD_PROJEKT"] = _umg
    # DIE PRUEFUNG, DIE GEFEHLT HAT: kein fest verdrahteter Benutzerpfad.
    # Ein solcher Pfad sieht im Quelltext aus wie ein Name dieses Projekts
    # und wandert bei einer Umbenennung mit — obwohl er auf etwas FREMDES
    # zeigt. Ausserdem hat er in einem quelloffenen Repo nichts verloren.
    # `C:\Users\Public\…` ist ausgenommen, und das ist keine Aufweichung:
    # das ist der gemeinsame Ort, an dem auch die Logdateien liegen, und er
    # existiert auf jedem Windows unabhaengig vom angemeldeten Nutzer.
    # Verboten ist ein Pfad unter einem konkreten BENUTZERNAMEN — der gilt
    # nur auf einem Rechner und wandert bei jeder Umbenennung mit.
    _pfade = [p for p in re.findall(r'r?"[A-Za-z]:\\\\?Users\\\\?[^"]*"', dash)
              if "users\\public" not in p.lower().replace("\\\\", "\\")]
    _ordner_rangfolge(dash)
    pruefe("P9 keine fest verdrahteten Benutzerpfade im Dashboard",
           not _pfade,
           "gefunden: %s" % ", ".join(_pfade[:3]))
    pruefe("P9 fehlender Projektordner wird gemeldet",
           "OPEN_MCP_CAD_PROJEKT" in dash and "projektordner.txt" in dash,
           "lieber abbrechen als Gespraeche in einer fremden Liste ablegen")

    # -- 9f. Sitzungsliste -------------------------------------------------
    # Bis 2026-09-26 fuenf Textsuchen ("read(KOPF_BYTES)" steht da, "cache"
    # steht da ...). `sitzungen` lief in keinem Gate, und die Namensregel
    # war falsch, ohne dass eine davon es sah. Jetzt gemessen, mit Mutanten.
    _sitzungsliste(chat_pfad)
    _dock_liste(chat_pfad)

    # -- 9f2. Cadwork-Werkzeuge im Chat ------------------------------------
    pruefe("P9 der Chat bekommt die Cadwork-Werkzeuge",
           "'--mcp-config'" in chat_code and "'--strict-mcp-config'" in chat_code,
           "ohne sie kann er reden, aber nicht zeichnen und den "
           "Briefkasten nicht lesen")
    pruefe("P9 die MCP-Konfiguration traegt DEN gewaehlten Port",
           "def mcp_konfig_schreiben" in chat
           and "'OPEN_MCP_CAD_PORT': str(port)" in chat_code,
           "sonst redet der Chat mit einem anderen Steckplatz als das "
           "Dashboard")
    # Die Falle vom 2026-08-09: dieses eine leere Argument hat die ganze
    # Werkzeugliste zerschossen — es sah aus, als lade die MCP-Konfiguration
    # nicht, dabei war sie in Ordnung.
    pruefe("P9 kein leeres --tools-Argument",
           "'--tools', ''" not in chat_code and '"--tools", ""' not in chat,
           "ein leeres --tools loescht die Werkzeugliste, auch die "
           "MCP-Werkzeuge")
    pruefe("P9 fehlendes Server-Python macht den Chat nicht kaputt",
           "def mcp_python" in chat and "return None" in chat_code,
           "dann laeuft er ohne Cadwork-Werkzeuge weiter — und sagt es")
    _chat_server_verhalten(chat_pfad)
    pruefe("P9 die Oberflaeche sagt, ob die Werkzeuge da sind",
           "werkzeuge_da" in dash_code and "Cadwork-Werkzeuge" in dash,
           "sonst merkt niemand, dass Claude gar nicht zeichnen kann")

    # -- 9f3. Modell, Denkstufe, Not-Aus -----------------------------------
    pruefe("P9 Vorgabe ist Sonnet 5 mit hoechster Denkstufe",
           "MODELL_VORGABE = 'sonnet'" in chat_code
           and "EFFORT_VORGABE = 'xhigh'" in chat_code,
           "Entscheid 2026-08-09")
    pruefe("P9 Modell und Denkstufe sind waehlbar",
           "chat_modell" in dash_code and "chat_stufe" in dash_code
           and "'--effort'" in chat_code)
    # Nicht "kommt vor", sondern "haengt am Knopf": die Kontrollzelle hat
    # gezeigt, dass ein `if False:` den ganzen Dialog totlegt, ohne dass
    # eine Vorhandensein-Pruefung das merkt.
    geklaert = ohne_prosa(quelle_von("_chat_ende_geklaert"))
    pruefe("P9 Beenden mitten im Zug fragt nach",
           "def laeuft_zug" in chat
           and "C.laeuft_zug(chat)" in geklaert
           and "QMessageBox" in geklaert,
           "ein laufender Zug wird nie ohne Rueckfrage abgewuergt")
    # Der Nutzer hat im Sichttest den ZWEITEN Weg erwischt: der Chat lief, und
    # "Trennen" hat ihn wortlos abgeschossen. Beide Wege muessen durch
    # dieselbe Rueckfrage.
    # Seit S8 (2026-09-26) gibt es keinen Knopf Starten/Beenden mehr; beendet
    # wird ueber "Beenden" und "Neuer Chat" — beide durch dieselbe Stelle.
    for weg in ("_chat_beenden_geklickt", "_chat_neu", "_trennen"):
        pruefe("P9 %s fragt ueber _chat_ende_geklaert" % weg,
               "_chat_ende_geklaert(z)" in ohne_prosa(quelle_von(weg)),
               "sonst gibt es einen zweiten Weg, der still abwuergt")
    pruefe("P9 die Rueckfrage hat alle drei Auswege",
           "Jetzt beenden" in dash and "Nach dem Zug beenden" in dash
           and "Weiterlaufen lassen" in dash)
    pruefe("P9 'nach dem Zug' wird im Qt-Takt eingeloest, nicht im Leser",
           "beenden_nach_zug" in ohne_prosa(quelle_von("_chat_zeichnen")),
           "sonst raeumt der Leserthread mitten im Pipe-Lesen ab")

    # -- 9f4. Die vier Modi — FUNKTIONAL geprueft (2026-09-27) --------------
    # Der Gespraechsteil kennt weder Qt noch cwapi3d, laesst sich also hier
    # importieren. Das ist ungleich staerker als eine Textsuche: geprueft
    # wird, was die Politik TUT, nicht wie sie geschrieben ist.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("_a_chat_gate", chat_pfad)
    _m = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_m)

    server = _server_werkzeuge(_m)
    kurz = {w.split("__", 2)[2] for w in server}
    pruefe("P9 jedes Werkzeug in CADWORK_LESEND gibt es in server.py (aus "
           "der Quelle)", _m.CADWORK_LESEND <= kurz and len(server) >= 10,
           sorted(_m.CADWORK_LESEND - kurz))
    pruefe("P9 KONTROLLE: ein Tippfehler in der Menge faellt auf",
           not ({"get_document_infos"} | _m.CADWORK_LESEND) <= kurz)
    aendernd = [w for w in server if _m.ist_cadwork(w)]
    lesend = ([w for w in server if w.split("__", 2)[2] in _m.CADWORK_LESEND]
              + sorted(_m.NUR_LESEND))
    aussen = ["Bash", "PowerShell", "Write", "Edit", "NotebookEdit",
              "WebFetch", "WebSearch", "Task", "mcp__fremd__cadwork_zeichnen",
              "mcp__open-mcp-cadx__execute_cadwork_command"]
    soll = {"nur_lesen": ("nein", "nein", "ja"),
            "fragen": ("fragen", "fragen", "ja"),
            "cadwork_frei": ("ja", "fragen", "ja"),
            "alles_auto": ("ja", "ja", "ja")}

    def urteil_je_gruppe(entscheiden, modus):
        """-> (aendernd, aussen, lesend): das Urteil, wenn alle einer Gruppe
        gleich entschieden werden, sonst 'gemischt'."""
        aus = []
        for gruppe in (aendernd, aussen, lesend):
            u = {entscheiden(modus, w) for w in gruppe}
            aus.append(u.pop() if len(u) == 1 else "gemischt")
        return tuple(aus)
    ist = {m: urteil_je_gruppe(_m.entscheiden, m) for m in _m.MODUS_WERTE}
    pruefe("P9 die vier Modi: Cadwork aendern / aussen / lesen je Modus "
           "(Werkzeuge aus server.py)", ist == soll and len(aendernd) >= 5,
           repr(ist))
    pruefe("P9 ein fremder Server mit 'cadwork' im Namen gilt als aussen "
           "(nie ohne Frage in 'Cadwork frei')",
           _m.entscheiden("cadwork_frei", "mcp__fremd__cadwork_zeichnen")
           == "fragen"
           and _m.entscheiden("cadwork_frei",
                              "mcp__open-mcp-cad-b__execute_cadwork_command")
           == "ja")
    # KONTROLLE: die Regel bis 2026-09-26 ("cadwork" im Namen = Cadwork)
    # liesse das fremde Werkzeug in "Cadwork frei" ohne Frage laufen.
    with io.open(chat_pfad, encoding="utf-8") as fh:
        _chat_quelle = fh.read()
    _alt = '    if kurz is None:\n        return "aussen"\n'
    _neu = ('    if kurz is None:\n        return "cadwork" if "cadwork" in '
            '(werkzeug or "").lower() else "aussen"\n')
    _mut = type(sys)("_a_chat_p9_mut")
    _mut.__file__ = chat_pfad
    exec(compile(_chat_quelle.replace(_alt, _neu), chat_pfad, "exec"),
         _mut.__dict__)
    pruefe("P9 KONTROLLE: mit der alten Namensregel liefe das fremde "
           "Werkzeug in 'Cadwork frei' ohne Frage",
           _chat_quelle.count(_alt) == 1 and _mut.entscheiden(
               "cadwork_frei", "mcp__fremd__cadwork_zeichnen") == "ja")
    draussen = {"blocked_path": "C:/geheim/.env"}
    pruefe("P9 Lesen ausserhalb des Ordners: Nur lesen lehnt ab, Fragen und "
           "Cadwork frei fragen jedes Mal (auch mit Freigabe je Art), nur "
           "Alles automatisch laesst es durch",
           [_m.entscheiden(m, "Read", draussen, {"Read"})
            for m in _m.MODUS_WERTE] == ["nein", "fragen", "fragen", "ja"],
           [_m.entscheiden(m, "Read", draussen) for m in _m.MODUS_WERTE])
    pruefe("P9 KONTROLLE: ohne Pfad-Warnung geht dasselbe Read ueberall durch",
           {_m.entscheiden(m, "Read", {}) for m in _m.MODUS_WERTE} == {"ja"})
    pruefe("P9 Freigabe je Art gilt in 'Fragen' und 'Cadwork frei' (dort "
           "fuer das Aeussere, Entscheid 2026-09-28), nur fuer die Art, nie "
           "in 'Nur lesen'",
           _m.entscheiden("fragen", "Bash", None, {"Bash"}) == "ja"
           and _m.entscheiden("fragen", "Write", None, {"Bash"}) == "fragen"
           and _m.entscheiden("cadwork_frei", "Bash", None, {"Bash"}) == "ja"
           and _m.entscheiden("cadwork_frei", "Write", None, {"Bash"})
           == "fragen"
           and _m.entscheiden("nur_lesen", "Bash", None, {"Bash"}) == "nein")
    pruefe("P9 ein unbekannter Modus gibt nie mehr frei als 'Fragen'",
           [_m.entscheiden("turbo", w) for w in (aendernd[0], "Bash", "Read")]
           == ["fragen", "fragen", "ja"])
    pruefe("P9 'Alles automatisch' ist der EINZIGE Modus, in dem ein "
           "Befehl am Rechner ohne Frage laeuft",
           [m for m in _m.MODUS_WERTE if _m.entscheiden(m, "Bash") == "ja"]
           == ["alles_auto"])
    beschreibung = dict((m[0], m[3]) for m in _m.MODI)
    pruefe("P9 der Modus ohne Grenze sagt es in seiner Beschreibung",
           "nichts wird gefragt" in beschreibung.get("alles_auto", "").lower()
           and not any("nichts wird gefragt" in t.lower()
                       for m, t in beschreibung.items() if m != "alles_auto"),
           repr(beschreibung))
    pruefe("P9 Vorgabe 'Fragen', nie gemerkt wird 'Alles automatisch' (dann "
           "'Cadwork frei')", _m.MODUS_VORGABE == "fragen"
           and _m.MODUS_NIE_MERKEN == "alles_auto"
           and _m.MODUS_STATT_AUTO == "cadwork_frei")
    # -- 9f4b. Der AUFRUF, nicht nur die Funktion --------------------------
    # Bis 2026-08-15 rief `_einordnen` die Politik ohne die Anfrage auf —
    # der blocked_path-Riegel stand im Code und griff nie. Deshalb hier der
    # ganze Weg: ein echtes Ereignis durch `_einordnen`, und nachgesehen,
    # was hinten herauskommt.
    class _FakeStdin:
        def __init__(self):
            self.zeilen = []

        def write(self, s):
            self.zeilen.append(s)

        def flush(self):
            pass

    def _durchreichen(modus, werkzeug, anfrage_extra):
        import threading as _th
        chat = {"modus": modus, "ereignisse": [], "freigaben": [],
                "schloss": _th.Lock()}
        chat["proc"] = type("P", (), {"stdin": _FakeStdin(),
                                      "poll": lambda self: None})()
        ev = {"type": "control_request", "request_id": "r1",
              "request": dict({"subtype": "can_use_tool",
                               "tool_name": werkzeug, "input": {}},
                              **anfrage_extra)}
        _m._einordnen(chat, dict(ev, subtype="can_use_tool"))
        return ((chat["freigaben"][-1] if chat["freigaben"] else None),
                chat["proc"].stdin.zeilen)

    karte, _z = _durchreichen("cadwork_frei", "Read",
                              {"blocked_path": "C:/geheim/.env"})
    pruefe("P9 der Pfad-Riegel greift auch im ECHTEN Weg (_einordnen)",
           karte is not None and karte.get("offen") is True,
           "die Anfrage muss bis in die Politik durchgereicht werden — "
           "sonst ist der Riegel toter Code")
    frei, _z = _durchreichen("cadwork_frei", "Read", {})
    pruefe("P9 KONTROLLE: ohne Pfad-Warnung geht derselbe Weg automatisch "
           "durch", frei is not None and frei.get("offen") is False,
           "sonst kaeme die Karte oben von irgendetwas anderem")
    nein, zeilen = _durchreichen("nur_lesen", "Write", {})
    pruefe("P9 Nur lesen im echten Weg: Write ohne Karte abgelehnt, das CLI "
           "bekommt 'deny' mit dem Grund",
           nein is not None and nein.get("offen") is False
           and nein.get("antwort") == "verweigert"
           and '"deny"' in "".join(zeilen) and "Nur lesen" in "".join(zeilen),
           zeilen)

    pruefe("P9 automatisch Erlaubtes bleibt im Verlauf sichtbar",
           "ereignis('auto'" in chat_code and "automatisch" in dash,
           "eine stille Automatik waere schlimmer als die Fragerei")
    pruefe("P9 die Bruecke bleibt lueckenlos, trotz Automatik",
           "'ask': ['*']" in chat_code,
           "entschieden wird im Dashboard — die CLI meldet weiterhin ALLES")

    # -- 9f5. Streaming und Laufanzeige ------------------------------------
    # Rueckmeldung 2026-08-09: "habe gar nicht gesehen, ob Claude am Nachdenken war".
    # Ursache war, dass --include-partial-messages zwar gesetzt war, die
    # stream_event-Ereignisse aber verworfen wurden.
    pruefe("P9 Teilstuecke werden ausgewertet, nicht verworfen",
           "'stream_event'" in chat_code and "'text_delta'" in chat_code
           and "laufender_text" in chat_code,
           "sonst kommt die Antwort erst am Stueck, Sekunden spaeter")
    pruefe("P9 der fertige Block SETZT den Text, statt ihn anzuhaengen",
           "chat['laufender_text'] = ''" in chat_code,
           "sonst steht die Antwort doppelt da")
    pruefe("P9 nur 'result' beendet den Zug",
           "message_stop" not in ohne_prosa(chat),
           "nach einem Werkzeug kommt eine ZWEITE Nachricht im selben Zug")
    # Der Haenger, den die Messung gefunden hat.
    leser = ohne_prosa(quelle_von("_leser_starten", chat))
    pruefe("P9 stirbt das CLI, endet auch der Zug",
           "chat['laeuft_zug'] = False" in leser,
           "sonst dreht die Laufanzeige fuer immer weiter")
    zeichnen = ohne_prosa(quelle_von("_chat_zeichnen"))
    # Seit 2026-09-28 ist die Laufanzeige das "…" im Verlauf (`tippt`);
    # die Punkte bewegt ein Zeitgeber der Blase (test_a_live L73).
    pruefe("P9 die Laufanzeige lebt VOR dem frueh-return",
           "tippt" in zeichnen and zeichnen.index("_verlauf_zeigen(")
           < zeichnen.index("chat_gezeigt")
           and zeichnen.index("tippt") < zeichnen.index("_verlauf_zeigen("),
           "sonst frieren die Punkte ein, sobald sich die Daten nicht "
           "aendern — und genau dann laeuft ein Werkzeug (bis 22 s still)")
    pruefe("P9 eigener schneller Takt fuer den Chat",
           "setInterval(100)" in dash_code,
           "500 ms reicht fuer Streaming messbar nicht")

    # -- 9g. Die Karte -----------------------------------------------------
    pruefe("P9 die Karte zeigt den Wortlaut, nicht nur eine Frage",
           'eingabe.get("code")' in dash and "Wortlaut zeigen" in dash,
           "sonst waere 'Erlauben' ein Blindflug")
    pruefe("P9 Erlauben und Ablehnen sind beide da",
           "Erlauben" in dash and "Ablehnen" in dash
           and "freigabe_beantworten" in dash)
    pruefe("P9 der Prozessbaum wird abgeraeumt, nicht nur der Mantel",
           "'taskkill', '/T', '/F'" in chat_code,
           "claude.cmd ist nur eine Huelle um Node — ohne /T laeuft das "
           "Node-Kind weiter und haelt Cadwork beim Schliessen auf")
    pruefe("P9 es wird claude.cmd genommen, nicht claude.ps1",
           "claude.cmd" in chat_code and "claude.ps1" not in chat_code,
           "auf dem PATH gewinnt die ps1-Fassung, die eine Shell braucht")
    pruefe("P9 kein Konsolenfenster vor Cadwork",
           "CREATE_NO_WINDOW" in chat_namen
           and "creationflags=CREATE_NO_WINDOW" in chat_code)

    _gemerkte_wahl(_m)
    _lokal_pruefen_offline()

    print("\n" + "=" * 62)
    n_ok = sum(_ergebnisse)
    print("%d/%d bestanden" % (n_ok, len(_ergebnisse)))
    if n_ok != len(_ergebnisse):
        return 1
    print("A-Prototyp: Abgrenzung und Zustandslogik in Ordnung.")
    print("NICHT geprueft (geht nur in Cadwork): Aussehen, Andocken, "
          "Verbinden/Trennen im Betrieb.")
    print("Das VERHALTEN prueft tests/test_a_live.py — dieses "
          "Gate hier liest nur Quelltext.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
