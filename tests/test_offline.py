#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline-Gate fuer Open MCP CAD — prueft ALLES ohne Cadwork.

Der Kern laeuft hier gegen ein untergeschobenes cwapi3d (zwei Attrappen-
Module im sys.modules). Damit sind lange Auftraege, Dokumentnamen und
Fehlerfaelle beliebig stellbar — und die Zustandsmaschine wird ueber echte
TCP-Verbindungen getestet, nicht ueber Funktionsaufrufe.

    python tests/test_offline.py
    python tests/test_offline.py -v      # mit Details
    python tests/test_offline.py --altkern PFAD   # V8 auch gegen einen alten
                                         # Kern (wird nur KOPIERT, +3 Zellen)

Abschnitt A prueft die vier Steckplaetze statisch (Syntax, XML, Ports,
Gleichheit der Kopien), Abschnitt B das Verhalten zur Laufzeit.
"""

import ast
import contextlib
import gc
import glob
import importlib.util
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import types
import weakref
import xml.etree.ElementTree as ET

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo

# Umzug 2026-09-20: Gate liegt in tests/, Generator und Verbindungs-Client in
# scripts/. Ohne diesen Eintrag findet `import plugins_generieren` nichts —
# und zwar mit einem Abbruch, nicht still.
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
KERN_PFAD = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")

AUSFUEHRLICH = "-v" in sys.argv
# Die Bridge lenkt stdout waehrend eines Auftrags in einen Puffer um
# (contextlib.redirect_stdout ist prozessweit). Der Testbericht darf davon
# nicht verschluckt werden — deshalb schreiben wir immer auf das echte stdout.
ECHT_STDOUT = sys.stdout


def sag(*teile):
    print(*teile, file=ECHT_STDOUT)


def _freier_block(anzahl=10, saat=None):
    """Erster Port eines Blocks freier Ports AUSSERHALB 53127..53199.

    Je Lauf anders (Saat = PID). Vorher fest 53911: zwei Sitzungen, die
    gleichzeitig testeten (Worktrees), sprachen mit dem Pruefstand der
    jeweils anderen — gemessen 2026-09-25, B2/B3/B7/J9 zufaellig rot.
    Gebraucht werden TESTPORT bis TESTPORT + 9.
    """
    import random
    zufall = random.Random(os.getpid() if saat is None else saat)
    for _ in range(200):
        basis = zufall.randrange(54000, 64000 - anzahl)
        offen = []
        try:
            for p in range(basis, basis + anzahl):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                offen.append(s)
                s.bind(("127.0.0.1", p))
            return basis
        except OSError:
            continue
        finally:
            for s in offen:
                s.close()
    raise RuntimeError("kein freier Block von %d Ports gefunden" % anzahl)


TESTPORT = _freier_block()

# Eine EIGENE Registry, nie die echte. Die Test-Instanzen heissen A-D (auf
# Ports ab TESTPORT); in der echten Registry sah ein laufendes Dashboard sie
# und fragte "A" beim echten Steckplatz A ab — A stand dreizehnmal im Dock
# (2026-09-24). Gesetzt VOR dem Laden von Kern und Client: beide lesen
# den Ordner beim Import.
REGISTRY_TEST = tempfile.mkdtemp(prefix="omcad_registry_")
os.environ["OPEN_MCP_CAD_REGISTRY"] = REGISTRY_TEST

_ergebnisse = []


def pruefe(name, bedingung, info=""):
    _ergebnisse.append((name, bool(bedingung), info))
    zeichen = "ok  " if bedingung else "FEHL"
    if AUSFUEHRLICH or not bedingung:
        sag("  [%s] %s%s" % (zeichen, name, ("  — %s" % info) if info else ""))
    elif len(_ergebnisse) % 1 == 0:
        pass
    return bool(bedingung)


# ==========================================================================
# Attrappen fuer cwapi3d
# ==========================================================================

class _FakeDoc:
    name = "Testdokument_offline.3d"
    elemente = list(range(1, 43))
    aktiv = []
    zooms = []
    undos = []
    aktiv_ids = []
    refresh_aus = 0
    refresh_an = 0
    # Cadworks Undo-Stack, so grob wie noetig: jeder Eintrag ist die
    # Elementliste EINES Auftrags. `make_undo` nimmt den obersten zurueck.
    # Bewusst nachgespielt statt nur mitgezaehlt — sonst pruefte das Gate
    # nur, DASS make_undo gerufen wird, nicht dass danach etwas weg ist.
    undo_stack = []
    redo_stack = []
    # Jeder set_element_material-Aufruf als (ids, material_id)
    material_gesetzt = []
    # Aufrufe an Cadworks Fortschrittsbalken: 'an' / Prozentzahlen / 'aus'
    balken = []
    # Sichtbarkeit: welche Elemente sind gerade unsichtbar, und was wurde
    # beim Wiederherstellen gerufen
    unsichtbar = set()
    sicht_wieder = []
    # Vorhang: ('zu', ids) beim Unsichtbarmachen, ('auf', ids) beim Aufdecken
    vorhang = []
    # Reihenfolge der Schritte am Ende eines Laufs. Genau darauf kam es an:
    # das Material MUSS gesetzt sein, bevor der Vorhang aufgeht.
    ablauf = []
    geaendert_angemeldet = []
    # Cadworks automatische Auffrischung: an oder aus, JETZT. Dazu, welche
    # Elemente ihr Material bei eingeschalteter ("hell") bzw. abgeschalteter
    # ("dunkel") Auffrischung bekamen — nur hell baut Cadwork ihre
    # Darstellung auf (Befund 2026-08-06, siehe `_dunkle_elemente_nachziehen`).
    auffrischung = True
    material_hell = []
    material_dunkel = []
    # So lange dauert ein set_element_material (V1: damit "vor der Antwort
    # nachgezogen" nicht am Wettlauf zweier Threads haengt).
    material_dauer_s = 0.0
    # Jedes vc.refresh(): lief es IN einem Auftrag, in welchem Paket, und was
    # war da schon hell nachgezogen? Den Dienst, dessen `aktueller_auftrag`
    # das sagt, stellt die Zelle ein (`dienst`). Gezaehlt, weil ein
    # Neuzeichnen im LEERLAUF (`refresh_nachholen`) das eines Pakets sonst
    # vortaeuscht — die Gegenpruefung 2026-09-26 (Mutant K11) sah nichts.
    refreshs = []
    dienst = None
    # V10: Cadwork lehnt das Abschalten der Auffrischung ab (Schnellzeichnen
    # scheitert, `_bildschirm_aus` liefert False).
    aus_kaputt = False


def cwapi3d_attrappen_setzen():
    """Legt utility_controller / element_controller in sys.modules.

    Der Kern importiert cwapi3d bewusst erst IM Aufruf (nicht beim Laden) —
    deshalb genuegt es, die Module vorher hier zu hinterlegen.
    """
    def _aus():
        if _FakeDoc.aus_kaputt:
            raise RuntimeError("disable_auto_display_refresh abgelehnt "
                               "(Attrappe, V10)")
        _FakeDoc.refresh_aus += 1
        _FakeDoc.auffrischung = False

    def _an():
        _FakeDoc.refresh_an += 1
        _FakeDoc.auffrischung = True

    uc = types.ModuleType("utility_controller")
    uc.get_3d_file_name = lambda: _FakeDoc.name
    uc.save_3d_file_silently = lambda: True
    uc.disable_auto_display_refresh = _aus
    uc.enable_auto_display_refresh = _an
    uc.show_progress_bar = lambda: _FakeDoc.balken.append("an")
    uc.update_progress_bar = lambda p: _FakeDoc.balken.append(int(p))
    uc.hide_progress_bar = lambda: _FakeDoc.balken.append("aus")
    sys.modules["utility_controller"] = uc

    gc = types.ModuleType("geometry_controller")
    gc.get_element_facets = lambda eid: [[0, 0, 0], [1, 0, 0]]
    gc.get_width = lambda eid: 120.0
    gc.get_height = lambda eid: 60.0
    gc.get_length = lambda eid: 1000.0
    sys.modules["geometry_controller"] = gc

    def _mat_setzen(ids, mid):
        _FakeDoc.ablauf.append("material")
        # Nachgespielt, weil genau DAS die Darstellung repariert (gemessen
        # 2026-08-06). Jeder Aufruf wird mitgeschrieben, damit das Gate
        # pruefen kann, dass die im Dunkeln entstandenen Elemente wirklich
        # angefasst werden — und nur die.
        if _FakeDoc.material_dauer_s:
            time.sleep(_FakeDoc.material_dauer_s)
        _FakeDoc.material_gesetzt.append((sorted(ids), mid))
        (_FakeDoc.material_hell if _FakeDoc.auffrischung
         else _FakeDoc.material_dunkel).extend(ids)

    ac = types.ModuleType("attribute_controller")
    ac.get_name = lambda eid: "Testbalken %d" % eid
    ac.get_group = lambda eid: "TestGruppe"
    ac.get_subgroup = lambda eid: ""
    ac.get_element_material_name = lambda eid: "Glaswolle"
    ac.set_element_material = _mat_setzen
    sys.modules["attribute_controller"] = ac

    mc = types.ModuleType("material_controller")
    mc.get_material_id = lambda name: 291 if name == "Glaswolle" else 0
    sys.modules["material_controller"] = mc

    def _anmelden(ids):
        _FakeDoc.undo_stack.append(list(ids))

    def _undo():
        _FakeDoc.undos.append(1)
        if _FakeDoc.undo_stack:
            eintrag = _FakeDoc.undo_stack.pop()
            for eid in eintrag:
                if eid in _FakeDoc.elemente:
                    _FakeDoc.elemente.remove(eid)
            _FakeDoc.redo_stack.append(eintrag)

    def _redo():
        # Cadwork kann das selbst (ec.make_redo, am 2026-08-06 am lebenden
        # Modell geprueft: 1790 -> 1793 -> Undo 1790 -> Redo 1793).
        if _FakeDoc.redo_stack:
            eintrag = _FakeDoc.redo_stack.pop()
            for eid in eintrag:
                if eid not in _FakeDoc.elemente:
                    _FakeDoc.elemente.append(eid)
            _FakeDoc.undo_stack.append(eintrag)

    def _create(*args, **kw):
        neu = (max(_FakeDoc.elemente) if _FakeDoc.elemente else 0) + 1
        _FakeDoc.elemente.append(neu)
        return neu

    ec = types.ModuleType("element_controller")
    ec.get_all_identifiable_element_ids = lambda: list(_FakeDoc.elemente)
    ec.make_undo = _undo
    ec.make_redo = _redo
    ec.add_created_elements_to_undo = _anmelden
    ec.add_modified_elements_to_undo = (
        lambda ids: _FakeDoc.geaendert_angemeldet.append(list(ids)))
    ec.create_rectangular_beam_vectors = _create
    ec.get_active_identifiable_element_ids = lambda: list(_FakeDoc.aktiv_ids)
    sys.modules["element_controller"] = ec

    vc = types.ModuleType("visualization_controller")
    def _unsichtbar(ids):
        _FakeDoc.vorhang.append(("zu", sorted(ids)))
        _FakeDoc.ablauf.append("vorhang_zu")
        _FakeDoc.unsichtbar.update(ids)
        _FakeDoc.sicht_wieder.append(("zu", sorted(ids)))

    def _sichtbar(ids):
        _FakeDoc.vorhang.append(("auf", sorted(ids)))
        _FakeDoc.ablauf.append("vorhang_auf")
        _FakeDoc.unsichtbar.difference_update(ids)
        _FakeDoc.sicht_wieder.append(("auf", sorted(ids)))

    vc.set_invisible = _unsichtbar
    vc.set_visible = _sichtbar
    vc.set_active = lambda ids: _FakeDoc.aktiv.__setitem__(slice(None), list(ids))
    vc.set_inactive = lambda ids: None
    vc.zoom_active_elements = lambda: _FakeDoc.zooms.append(1)
    def _sicht_sichern():
        # Bildet den ECHTEN Befund nach (gemessen 2026-08-07 in Cadwork):
        # der Rueckgabewert laesst sich nicht nach Python konvertieren. Die
        # Bridge darf sich also nicht darauf verlassen.
        raise RuntimeError("Unable to convert function return value to a "
                           "Python type! (Attrappe bildet Cadwork nach)")

    def _kaputt(*_a, **_k):
        raise RuntimeError("set_visible abgelehnt (Kontrolle)")

    globals()["_kaputt"] = _kaputt

    vc.save_visibility_state = _sicht_sichern
    vc.restore_visibility_state = _sicht_sichern
    vc.show_all_elements = lambda: _FakeDoc.sicht_wieder.append("ALLE")
    vc.is_visible = lambda eid: eid not in _FakeDoc.unsichtbar
    def _neu_gezeichnet():
        a = getattr(_FakeDoc.dienst, "aktueller_auftrag", None)
        _FakeDoc.refreshs.append({
            "im_auftrag": a is not None,
            "paket": getattr(a, "paket", None),
            "hell": (frozenset(_FakeDoc.material_hell) if a is not None
                     else None)})

    vc.refresh = _neu_gezeichnet
    sys.modules["visualization_controller"] = vc


def kern_laden(pfad=KERN_PFAD, name="omcad_bridge_core_test"):
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


# ==========================================================================
# Testgeruest: echter Dienst auf einem Testport
# ==========================================================================

class Pruefstand:
    def __init__(self, kern, port=TESTPORT, instanz="D", **cfg_kwargs):
        self.kern = kern
        self.cfg = kern.Konfiguration(instanz=instanz, port=port,
                                      anzeigename="Open MCP CAD TEST",
                                      log_datei=os.path.join(
                                          tempfile.gettempdir(),
                                          "omcad_test_offline.log"))
        for k, v in cfg_kwargs.items():
            setattr(self.cfg, k, v)
        self.dienst = kern.Verbindungsdienst(self.cfg)
        self.thread = None

    def __enter__(self):
        self.thread = threading.Thread(
            target=self.kern.serve, args=(self.cfg, self.dienst),
            name="Pruefstand", daemon=True)
        self.thread.start()
        # auf 'ready' warten
        for _ in range(200):
            if self.dienst.zustand in ("ready", "paused"):
                return self
            time.sleep(0.02)
        raise RuntimeError("Pruefstand wurde nicht bereit (Zustand %s)"
                           % self.dienst.zustand)

    def __exit__(self, *exc):
        self.dienst.beenden = True
        if self.thread:
            self.thread.join(timeout=5)
        return False

    # -- Protokoll --------------------------------------------------------

    def ruf(self, methode, params=None, timeout=10.0, roh=None):
        req = roh if roh is not None else {"id": 1, "method": methode,
                                           "params": params or {}}
        daten = (json.dumps(req) + "\n").encode("utf-8")
        with socket.create_connection(("127.0.0.1", self.cfg.port),
                                      timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(daten)
            puffer = bytearray()
            while b"\n" not in puffer:
                st = s.recv(4096)
                if not st:
                    raise ConnectionError("ohne Antwort geschlossen")
                puffer.extend(st)
        return json.loads(bytes(puffer).partition(b"\n")[0].decode("utf-8"))

    def ruf_async(self, methode, params=None, timeout=60.0):
        """Startet einen Aufruf im Hintergrund, liefert ein Ergebnis-Objekt."""
        behaelter = {}

        def lauf():
            try:
                behaelter["antwort"] = self.ruf(methode, params, timeout=timeout)
            except Exception as exc:                  # noqa: BLE001
                behaelter["fehler"] = exc

        t = threading.Thread(target=lauf, daemon=True)
        t.start()
        behaelter["thread"] = t
        return behaelter


LANGER_JOB = "import time\ntime.sleep(%.2f)\nresult = 'fertig'"


def _normiert(daten):
    """Zeilenenden vereinheitlichen — das Repo steht auf `* text=auto`."""
    return daten.replace(b"\r\n", b"\n")


def warte_bis(bedingung, sekunden=5.0, takt=0.02):
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(takt)
    return False


def _stufe(p, modus):
    """Zeichenstufe umstellen. -> True NUR, wenn der Kern sie eingestellt hat.

    Anlass (Gegenpruefung 2026-09-26): J9 stellte 'max' ein, das es seit
    2026-08-07 nicht mehr gibt. Der Kern antwortete `bad_mode`, niemand sah
    hin, und die Zellen "in 'max'" liefen still in der Stufe davor.
    """
    a = p.ruf("zeichenmodus", {"modus": modus})
    return bool(a.get("ok")
                and (a.get("result") or {}).get("zeichenmodus") == modus
                and p.dienst.zeichenmodus == modus)


# ==========================================================================
# Abschnitt A — statisch
# ==========================================================================

def abschnitt_a():
    sag("\n--- A  Steckplaetze A-D statisch ---")
    # Die Steckplaetze kommen aus der QUELLE, nicht aus einer Abschrift.
    # Sonst prueft dieses Gate nach jeder Erweiterung (2026-08-15: von vier
    # auf sechs) nur noch die alten vier — und sagt zu den neuen nichts,
    # waehrend es "alles gut" meldet.
    import plugins_generieren as _gen
    erwartet = {ordner: (instanz, port)
                for instanz, ordner, port in _gen.STECKPLAETZE}
    pruefe("A0 mehr als vier Steckplaetze sind vorgesehen",
           len(erwartet) >= 6, "%d Steckplaetze: %s"
           % (len(erwartet), ", ".join(sorted(i for i, _ in erwartet.values()))))
    # Der Testport-Block liegt ausserhalb des Cadwork-Bereichs und ist je
    # Lauf ein anderer, damit parallele Sitzungen sich nicht treffen.
    with open(KERN_PFAD, encoding="utf-8") as _fh:
        _baum = ast.parse(_fh.read())
    _w = {k.targets[0].id: ast.literal_eval(k.value) for k in _baum.body
          if isinstance(k, ast.Assign) and len(k.targets) == 1
          and isinstance(k.targets[0], ast.Name)
          and k.targets[0].id in ("PORT_VON", "PORT_BIS")}
    _kern_bereich = set(range(_w["PORT_VON"], _w["PORT_BIS"] + 1))
    pruefe("A0p Testports %d-%d ausserhalb des Cadwork-Bereichs"
           % (TESTPORT, TESTPORT + 9),
           not _kern_bereich & set(range(TESTPORT, TESTPORT + 10))
           and len(_kern_bereich) == 73, "Bereich %d Ports" % len(_kern_bereich))
    _andere = {_freier_block(saat=s) for s in (1, 2, 3)}
    pruefe("A0p-K andere Laeufe ziehen andere Bloecke (fest waere EINER)",
           len(_andere) == 3, sorted(_andere))

    # --- Der A-Prototyp ist eine BEKANNTE Abweichung ---------------------
    # A traegt das Dashboard: ein Einstieg mit Logik, eigene Module daneben,
    # ein von Hand gemachtes Icon. Dieses Gate hat das bisher als sechs
    # Fehler gemeldet — bei JEDEM Lauf, seit Wochen. Ein Messgeraet, das
    # immer rot zeigt, liest irgendwann niemand mehr; genau so verdeckt es
    # dann einen echten Fehler.
    #
    # Weggeschaut wird trotzdem nicht: A hat ein EIGENES Gate
    # (tests/test_a_prototyp.py, 123 Pruefungen), und dass es
    # existiert, wird hier nachgewiesen. Die Regeln fuer B, C und D bleiben
    # unveraendert scharf — sie sind der eigentliche Gleichheitsnachweis.
    PROTOTYP = "Open MCP CAD A"
    A_GATE = os.path.join(REPO, "tests", "test_a_prototyp.py")
    pruefe("A0 der A-Prototyp hat sein eigenes Gate", os.path.isfile(A_GATE),
           "sonst waere die Ausnahme unten eine Luecke, kein Verweis")
    a_extra = sorted(os.path.basename(p) for p in glob.glob(
        os.path.join(REPO, "cad_plugin", PROTOTYP, "omcad_a_*.py")))
    pruefe("A0 die Zusatzmodule liegen NUR bei A", bool(a_extra) and not [
        p for b in ("B", "C", "D")
        for p in glob.glob(os.path.join(REPO, "cad_plugin",
                                        "Open MCP CAD " + b,
                                        "omcad_a_*.py"))],
           "A: %s" % ", ".join(a_extra))

    # A1 Syntax aller Bridge-Dateien
    dateien = sorted(glob.glob(os.path.join(REPO, "cad_plugin", "**", "*.py"),
                               recursive=True))
    pruefe("A1 Bridge-Python-Dateien gefunden", len(dateien) >= 9,
           "%d Dateien" % len(dateien))
    for pfad in dateien:
        with open(pfad, "r", encoding="utf-8") as fh:
            quelle = fh.read()
        try:
            ast.parse(quelle)
            gut = True
            info = ""
        except SyntaxError as exc:
            gut, info = False, str(exc)
        pruefe("A1 Syntax %s" % os.path.relpath(pfad, REPO), gut, info)
        # Trunkierungs-Gate (AGENTS.md): ast.parse allein wuerde eine sauber
        # abgeschnittene Datei durchlassen — deshalb zusaetzlich der
        # Abschlussvertrag. Kern endet mit 'return d', Einstiege mit 'serve()'.
        letzte = [z for z in quelle.splitlines() if z.strip()][-1].strip()
        # Welcher Vertrag gilt: der Kern endet mit `return d`, ein EINSTIEG
        # mit `serve()`. Ein Einstieg ist die Datei, die so heisst wie ihr
        # Ordner — alles andere im Ordner ist ein Modul.
        _ordner = os.path.basename(os.path.dirname(pfad))
        _ist_einstieg = os.path.basename(pfad) == _ordner + ".py"
        if pfad.endswith("omcad_bridge_core.py"):
            soll_ende = "return d"
        elif not _ist_einstieg:
            # Die A-Module sind keine Einstiege und enden deshalb nicht mit
            # serve(). Gegen Trunkierung schuetzt hier, dass die letzte Zeile
            # ueberhaupt eine ABGESCHLOSSENE Anweisung ist — ein sauber
            # mittendrin abgeschnittener Python-Text scheitert schon oben an
            # ast.parse, ein an der Blockgrenze abgeschnittener faellt hier.
            soll_ende = None
        else:
            soll_ende = "serve()"
        if soll_ende is None:
            baum = ast.parse(quelle)
            gut = bool(baum.body) and quelle.endswith("\n")
            info = "endet mit %s" % type(baum.body[-1]).__name__
        else:
            gut = letzte == soll_ende and quelle.endswith("\n")
            info = "letzte Zeile %r, erwartet %r" % (letzte, soll_ende)
        pruefe("A1 vollstaendig %s" % os.path.relpath(pfad, REPO), gut, info)

    # A2 XML gueltig + richtiger Anzeigename
    for ordner, (instanz, _port) in erwartet.items():
        pfad = os.path.join(REPO, "cad_plugin", ordner, "plugin_info.xml")
        try:
            baum = ET.parse(pfad)
            name = baum.find('./Name/Text[@language="German"]').text
            gut = (name == "Open MCP CAD %s" % instanz)
            info = repr(name)
        except Exception as exc:                      # noqa: BLE001
            gut, info = False, str(exc)
        pruefe("A2 plugin_info.xml %s" % ordner, gut, info)

    # A2b DER TOOLTIP IM PLUGIN-MENUE IST FUER ANWENDER, NICHT FUER TECHNIKER.
    #
    # Rueckmeldung 2026-09-25: die Beschreibung nannte Portbereich und
    # Log-Pfad ("sehr technisch"). Den Port waehlt das Dock, der Server
    # findet ihn selbst; das Log steht in der Anleitung. Geprueft wird der
    # AUSGEROLLTE Ordner, in allen vier gepflegten Sprachen.
    import re as _re
    _TECHNIK = [(_re.compile(r"\b5\d{4}\b"), "Portnummer"),
                (_re.compile(r"\bport[oae]?\b", _re.I), "das Wort Port"),
                (_re.compile(r"[A-Za-z]:\\"), "Windows-Pfad"),
                (_re.compile(r"\.log\b", _re.I), "Logdatei")]

    def _technik(text):
        return [was for muster, was in _TECHNIK if muster.search(text)]

    _xml = os.path.join(REPO, "cad_plugin", _gen.DYNAMISCHER_ORDNER,
                        "plugin_info.xml")
    _texte = {}
    try:
        for _t in ET.parse(_xml).findall("./Description/Text"):
            if (_t.text or "").strip():
                _texte[_t.get("language")] = _t.text
    except Exception as exc:                          # noqa: BLE001
        _texte = {"Fehler": str(exc)}
    _gefunden = {s: _technik(t) for s, t in _texte.items() if _technik(t)}
    pruefe("A2b Tooltip des ausgerollten Plugins: DE/EN/FR/IT vorhanden, "
           "ohne Ports und Pfade",
           set(_texte) == {"German", "English", "French", "Italian"}
           and not _gefunden,
           "Sprachen %s, technisch: %s" % (sorted(_texte), _gefunden))
    # A2b-K KONTROLLE: der alte Wortlaut MUSS auffallen, sonst misst A2b
    # nichts.
    _alt = ("verbindet sofort über den ersten freien Port (53127 bis 53199)."
            "\nLog: C:\\Users\\Public\\OpenMcpCad_A.log")
    pruefe("A2b-K der alte Tooltip-Wortlaut faellt auf",
           len(_technik(_alt)) == 4, "gemeldet: %s" % _technik(_alt))

    # A3 Instanz + Port im Einstieg
    for ordner, (instanz, port) in erwartet.items():
        pfad = os.path.join(REPO, "cad_plugin", ordner, ordner + ".py")
        with open(pfad, "r", encoding="utf-8") as fh:
            quelle = fh.read()
        baum = ast.parse(quelle)
        werte = {}
        for knoten in baum.body:
            if isinstance(knoten, ast.Assign) and len(knoten.targets) == 1:
                ziel = knoten.targets[0]
                if isinstance(ziel, ast.Name) and isinstance(knoten.value,
                                                             ast.Constant):
                    werte[ziel.id] = knoten.value.value
        pruefe("A3 %s ist Steckplatz %s auf Port %d" % (ordner, instanz, port),
               werte.get("INSTANZ") == instanz and werte.get("PORT") == port,
               "gelesen: INSTANZ=%r PORT=%r" % (werte.get("INSTANZ"),
                                                werte.get("PORT")))
        # "Duenn" heisst: wenig CODE. Docstrings und Warum-Kommentare duerfen
        # wachsen — die tragen ja die Begruendung. Gezaehlt wird deshalb ohne
        # Kommentare und Zeichenketten-Literale.
        code_zeilen = 0
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.stmt) and not isinstance(
                    knoten, (ast.Expr, ast.Import, ast.ImportFrom)):
                code_zeilen += 1
        # A traegt das Dashboard und darf deshalb mehr — aber nicht beliebig
        # viel. Die Grenze bleibt, sie ist nur eine andere; sonst waere die
        # Ausnahme ein Freibrief und der Einstieg wuechse unbemerkt zu.
        grenze = 45 if ordner == PROTOTYP else 30
        pruefe("A3 %s Einstieg traegt keine Logik (< %d Anweisungen)"
               % (ordner, grenze),
               code_zeilen < grenze, "%d Anweisungen, %d Zeilen gesamt"
               % (code_zeilen, len(quelle.splitlines())))

    # A3b Icon: Cadwork zeigt eine icon.svg aus dem Plugin-Ordner an.
    # Seit 2026-09-24 erzeugt der Generator ALLE Icons aus einem Bild
    # (ICON_BILD), auch das von A und das des dynamischen Ordners. Bei A
    # wird die Plakette trotzdem nicht verlangt (siehe unten).
    for ordner, (instanz, _port) in erwartet.items():
        pfad = os.path.join(REPO, "cad_plugin", ordner, "icon.svg")
        try:
            baum = ET.parse(pfad)
            titel = baum.find("{http://www.w3.org/2000/svg}title").text
            knoten = baum.find("{http://www.w3.org/2000/svg}text")
            text = knoten.text if knoten is not None else None
            gut = titel == "Open MCP CAD %s" % instanz
            if ordner != PROTOTYP:
                gut = gut and text == instanz
            info = "%s / Buchstabe %r" % (titel, text)
        except Exception as exc:                      # noqa: BLE001
            gut, info = False, repr(exc)
        pruefe("A3b icon.svg %s" % ordner, gut, info)
    # Alle vier tragen dasselbe Logo — unterschieden werden sie ueber die
    # farbige Plakette mit dem Buchstaben. Geprueft wird deshalb, dass jede
    # Datei GENAU die Farbe ihres Steckplatzes traegt und keine fremde.
    farben = dict(_gen.ICON_FARBE)
    pruefe("A3b jeder Steckplatz hat eine EIGENE Plakettenfarbe",
           len(set(farben.values())) == len(farben),
           "sonst waeren zwei Cadwork-Fenster nicht unterscheidbar")
    for ordner, (instanz, _port) in erwartet.items():
        with open(os.path.join(REPO, "cad_plugin", ordner, "icon.svg"),
                  encoding="utf-8") as fh:
            inhalt = fh.read()
        eigene = farben[instanz] in inhalt
        fremde = [i for i, f in farben.items()
                  if i != instanz and f in inhalt]
        # Bei A zaehlt nur die Haelfte, die wirklich schadet: eine FREMDE
        # Plakettenfarbe. Sein Icon hat gar keine — das ist Absicht und
        # kein Fehler; zwei Steckplaetze zu verwechseln waere einer.
        pruefe("A3b %s traegt keine fremde Plakettenfarbe" % ordner,
               (eigene or ordner == PROTOTYP) and not fremde,
               "eigene=%s fremde=%s" % (eigene, fremde))

    # A3b-Bild: JEDER Ordner, auch der ausgerollte, zeigt das Bild aus
    # ICON_BILD. Gelesen wird das eingebettete PNG selbst, nicht ein Text
    # in der Datei — sonst saehe ein Ordner mit altem Zeichen gleich aus.
    import base64 as _b64
    with open(os.path.join(REPO, _gen.ICON_BILD.replace("/", os.sep)),
              "rb") as fh:
        _soll_bild = fh.read()

    def _eingebettet(svg_text):
        bild = ET.fromstring(svg_text).find(
            "{http://www.w3.org/2000/svg}image")
        if bild is None:
            return None
        href = bild.get("{http://www.w3.org/1999/xlink}href") or ""
        kopf = "data:image/png;base64,"
        return _b64.b64decode(href[len(kopf):]) if href.startswith(kopf) \
            else None

    for _i, ordner, _p in _gen.ALLE_ORDNER:
        with open(os.path.join(REPO, "cad_plugin", ordner, "icon.svg"),
                  encoding="utf-8") as fh:
            _svg = fh.read()
        pruefe("A3b-Bild %s zeigt %s" % (ordner, _gen.ICON_BILD),
               _eingebettet(_svg) == _soll_bild,
               "%d Byte erwartet" % len(_soll_bild))
    # A3b-Bild-K KONTROLLE: ein anderes Bild im SVG MUSS auffallen.
    _anders = _gen.icon_bauen(None).replace(
        _b64.b64encode(_soll_bild).decode("ascii"),
        _b64.b64encode(_soll_bild + b"\0").decode("ascii"))
    pruefe("A3b-Bild-K ein fremdes Bild faellt auf",
           _eingebettet(_anders) not in (None, _soll_bild),
           "Kontrolle muss abweichen")

    # A3c JEDER NAME, DEN EIN EINSTIEG AUFRUFT, MUSS DA SEIN.
    #
    # Der Anlass, 2026-09-21: der ausgerollte Einstieg rief
    # `dashboard_laden()` — eine Funktion, die es in dieser Datei nicht
    # gab. Beim Zusammenbauen war nur `DASHBOARD_PFAD` uebernommen worden,
    # die Funktion daneben nicht. Folge: der Plugin-Klick tat NICHTS
    # Sichtbares (`except Exception` fing den NameError), und im Log stand
    # kein Wort, weil der Kern nie erreicht wurde.
    #
    # Kein Gate konnte das sehen: `test_a_prototyp` prueft Steckplatz A,
    # `plugins_generieren --pruefen` vergleicht Bytes gegen eine Vorlage,
    # und der handgepflegte Ordner hat keine Vorlage. Syntaktisch war die
    # Datei einwandfrei — ein fehlender Name faellt erst beim AUFRUF auf.
    #
    # Geprueft wird deshalb ueber den AST: jeder Name, der in einer
    # Funktion dieser Datei aufgerufen wird, muss im Modul, in einem
    # Import oder als eingebaute Funktion vorkommen.
    import builtins as _bi

    def _fehlende_aufrufe(baum):
        da = set(dir(_bi))
        for k in ast.walk(baum):
            if isinstance(k, (ast.FunctionDef, ast.ClassDef)):
                da.add(k.name)
            elif isinstance(k, ast.Assign):
                for z in k.targets:
                    if isinstance(z, ast.Name):
                        da.add(z.id)
            elif isinstance(k, ast.Import):
                for a in k.names:
                    da.add((a.asname or a.name).split(".")[0])
            elif isinstance(k, ast.ImportFrom):
                for a in k.names:
                    da.add(a.asname or a.name)
            elif isinstance(k, ast.arg):
                da.add(k.arg)
            elif isinstance(k, ast.ExceptHandler) and k.name:
                da.add(k.name)
        return sorted({k.func.id for k in ast.walk(baum)
                       if isinstance(k, ast.Call)
                       and isinstance(k.func, ast.Name)
                       and k.func.id not in da})

    _baum_dyn = None
    for _ordner in sorted(set([o for _i, o, _p in _gen.ALLE_ORDNER])):
        _pfad = os.path.join(REPO, "cad_plugin", _ordner, _ordner + ".py")
        if not os.path.isfile(_pfad):
            continue
        _baum = ast.parse(io.open(_pfad, encoding="utf-8").read())
        if _ordner == _gen.DYNAMISCHER_ORDNER:
            _baum_dyn = _baum
        _fehlt = _fehlende_aufrufe(_baum)
        pruefe("A3c %s ruft nur Namen auf, die es gibt" % _ordner,
               not _fehlt, "fehlt: %s" % ", ".join(_fehlt))

    # A3c-K KONTROLLE, DIE ROT WERDEN MUSS: derselbe Einstieg, aus dem
    # genau der Fall vom 2026-09-21 wieder hergestellt wird — die Funktion
    # `dashboard_laden` fehlt, ihr Aufruf in `serve()` bleibt. Meldet die
    # Pruefung dann nicht genau diesen Namen, misst A3c nichts.
    _k_da = _baum_dyn is not None
    if _k_da:
        _baum_dyn.body = [k for k in _baum_dyn.body
                          if not (isinstance(k, ast.FunctionDef)
                                  and k.name == "dashboard_laden")]
    pruefe("A3c-K ohne dashboard_laden meldet A3c genau diesen Namen",
           _k_da and _fehlende_aufrufe(_baum_dyn) == ["dashboard_laden"],
           "dynamischer Einstieg nicht gefunden" if not _k_da
           else "gemeldet: %s" % _fehlende_aufrufe(_baum_dyn))

    # A3d DIE AUSGEROLLTE OBERFLAECHE IST DIE GEPRUEFTE.
    #
    # Die UI-Module liegen zweimal: in A, wo `test_a_prototyp` und
    # `test_a_live` sie pruefen, und im dynamischen Ordner, der als einziger
    # in Cadwork ausgerollt wird. Beide sind HANDGEPFLEGT, der Generator
    # vergleicht sie also nicht. Aendert jemand nur A, sind alle Tests gruen
    # und in Cadwork laeuft die alte Fassung; aendert er nur den
    # dynamischen, laeuft Ungeprueftes. Stand 2026-09-22 bytegleich — diese
    # Pruefung haelt es fest.
    _a_ordner = [o for i, o, _p in _gen.STECKPLAETZE if i == "A"][0]
    _ui = [n for n in _gen.HANDGEPFLEGT[None]
           if n.endswith(".py") and "{ordner}" not in n
           and os.path.isfile(os.path.join(REPO, "cad_plugin", _a_ordner, n))]

    def _abweichend(namen, ersetzt=None):
        aus = []
        for n in namen:
            with open(os.path.join(REPO, "cad_plugin", _a_ordner, n),
                      "rb") as fh:
                a = fh.read()
            with open(os.path.join(REPO, "cad_plugin",
                                   _gen.DYNAMISCHER_ORDNER, n), "rb") as fh:
                d = fh.read()
            if ersetzt and n in ersetzt:
                d = ersetzt[n](d)
            if a != d:
                aus.append(n)
        return aus

    _ab = _abweichend(_ui)
    pruefe("A3d UI-Module im ausgerollten Ordner == die in A gepruefte "
           "Fassung (%d Dateien)" % len(_ui),
           "omcad_a_dashboard.py" in _ui and not _ab,
           "abweichend: %s" % (", ".join(_ab) or "keine — Liste: %s" % _ui))
    # A3d-K KONTROLLE: ein Byte mehr im ausgerollten Dashboard MUSS als
    # Abweichung auffallen, und zwar nur dort.
    _k = _abweichend(_ui, {"omcad_a_dashboard.py": lambda b: b + b"\n"})
    pruefe("A3d-K ein geaendertes Byte im Dashboard faellt auf",
           _k == ["omcad_a_dashboard.py"], "gemeldet: %s" % _k)

    # Attrappen fuer den Startfehler-Weg (A3e, A3f): PyQt6/PyQt5 fehlen
    # (None in sys.modules) oder sind Attrappen, `ctypes` ist eine
    # Attrappe, deren MessageBoxW nur aufzeichnet, und sys.stderr ist wie
    # in Cadwork None. OHNE diese Huelle ginge im Gate eine ECHTE
    # Windows-Box auf, und das Gate stuende still, bis jemand klickt.
    # Beide Attrappen merken sich beim Aufruf, ob die Logdatei (`.log`,
    # von _a3f_lauf gesetzt) SCHON existiert: das Log kommt vor dem Dialog.
    def _log_da(attr):
        return bool(attr.log) and os.path.exists(attr.log)

    class _QtAttrappe:
        def __init__(self, mit_app=True):
            self.mit_app, self.instance_rufe, self.dialoge = mit_app, 0, []
            self.log = None
            attr = self

            class QApplication:                               # noqa: N801
                @staticmethod
                def instance():
                    attr.instance_rufe += 1
                    return object() if attr.mit_app else None

            class QMessageBox:                                # noqa: N801
                @staticmethod
                def warning(_eltern, titel, text):
                    attr.dialoge.append((titel, text, _log_da(attr)))

            self.modul = types.ModuleType("QtWidgets")
            self.modul.QApplication = QApplication
            self.modul.QMessageBox = QMessageBox

    class _CtypesAttrappe:
        def __init__(self, wirft=False):
            self.boxen, self.log = [], None
            attr = self

            def _box(_hwnd, text, titel, stil):
                if wirft:
                    raise OSError("Attrappe: kein Windows-Dialog")
                attr.boxen.append((titel, text, stil, _log_da(attr)))
                return 1

            self.modul = types.ModuleType("ctypes")
            self.modul.windll = types.SimpleNamespace(
                user32=types.SimpleNamespace(MessageBoxW=_box))

    _FEHLT = object()

    @contextlib.contextmanager
    def _startfehler_sandbox(qt6=None, qt5=None, ctypes_attr=None):
        ctypes_attr = ctypes_attr or _CtypesAttrappe()
        def _core(attr, pyqt, qt):
            # QtCore mit Versionen: das Startlog nennt sie (seit 2026-10-10).
            if not attr:
                return None
            m = types.ModuleType("QtCore")
            m.PYQT_VERSION_STR, m.QT_VERSION_STR = pyqt, qt
            return m
        ersatz = {
            "PyQt6": types.ModuleType("PyQt6") if qt6 else None,
            "PyQt6.QtWidgets": qt6.modul if qt6 else None,
            "PyQt6.QtCore": _core(qt6, "6.99.1", "6.99.2"),
            "PyQt5": types.ModuleType("PyQt5") if qt5 else None,
            "PyQt5.QtWidgets": qt5.modul if qt5 else None,
            "PyQt5.QtCore": _core(qt5, "5.15.91", "5.15.92"),
            "ctypes": ctypes_attr.modul,
        }
        alt_mod = {n: sys.modules.get(n, _FEHLT) for n in ersatz}
        alt_err = sys.stderr
        sys.modules.update(ersatz)
        sys.stderr = None
        try:
            yield ctypes_attr
        finally:
            sys.stderr = alt_err
            for n, m in alt_mod.items():
                if m is _FEHLT:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = m

    # A3e EIN KLICK VERBINDET — UND ZWAR NUR UEBER DAS DASHBOARD.
    #
    # Rueckmeldung 2026-09-22: der Plugin-Klick soll das Dock oeffnen UND verbinden,
    # ueber `_verbinden` (Reservierung, Wahl im Dock, kein Ausweichen, kein
    # Doppelstart). Der alte Einstieg hatte daneben einen Rueckfall
    # `kern.serve(...)` im except-Zweig — der startete den Dienst an alledem
    # vorbei. Geprueft wird VERHALTEN: `serve()` jedes Einstiegs, der ein
    # Dashboard laedt, laeuft gegen Attrappen fuer Kern und Dashboard.
    # Die Regel waehlt die Einstiege, keine Liste (Arbeitsregel 3).
    class _A3eKern:
        def __init__(self, version):
            self.CORE_VERSION = version
            self.serve_rufe = 0

        def Konfiguration(self, **kw):                    # noqa: N802
            return types.SimpleNamespace(**kw)

        def serve(self, *a, **kw):
            self.serve_rufe += 1

    class _A3eDashboard:
        def __init__(self, wirft):
            self.wirft, self.rufe = wirft, []

        def oeffnen(self, kern_laden, cfg_bauen, **kw):
            self.rufe.append(kw)
            if self.wirft:
                raise RuntimeError("Attrappe: Dashboard kaputt")
            return "dienst"

    def _a3e_messen(baum, pfad, wirft):
        """Fuehrt `serve()` aus. -> (Rueckgabe, oeffnen-kw, kern.serve-Rufe)."""
        raum = {"__name__": "a3e_einstieg", "__file__": pfad}
        exec(compile(baum, pfad, "exec"), raum)
        kern = _A3eKern(raum.get("ERWARTETE_KERN_VERSION"))
        dash = _A3eDashboard(wirft)
        raum["cadwork_dll_pfade_einrichten"] = lambda: None
        raum["kern_laden"] = lambda: kern
        raum["dashboard_laden"] = lambda: dash
        # Nie ins echte C:\Users\Public schreiben.
        raum["START_LOG"] = os.path.join(tempfile.mkdtemp(), "start.log")
        with _startfehler_sandbox():      # stderr None, keine echte Box
            rueck = raum["serve"]()
        return rueck, dash.rufe, kern.serve_rufe

    _a3e = []
    for _i, _ordner, _p in _gen.ALLE_ORDNER:
        _pfad = os.path.join(REPO, "cad_plugin", _ordner, _ordner + ".py")
        _quelle = io.open(_pfad, encoding="utf-8").read()
        _baum = ast.parse(_quelle)
        if not any(isinstance(k, ast.FunctionDef) and k.name == "dashboard_laden"
                   for k in _baum.body):
            continue                     # B-F: kein Dashboard, fester Port
        _a3e.append(_ordner)
        rueck, kw, serve_n = _a3e_messen(_baum, _pfad, wirft=False)
        pruefe("A3e %s: ein Klick oeffnet EINMAL mit verbinden=True"
               % _ordner,
               kw == [{"verbinden": True}] and rueck == "dienst"
               and serve_n == 0,
               "oeffnen-Aufrufe %s, Rueckgabe %r, kern.serve %dx"
               % (kw, rueck, serve_n))
        rueck, kw, serve_n = _a3e_messen(_baum, _pfad, wirft=True)
        pruefe("A3e %s: Dashboard kaputt -> KEIN kern.serve daneben"
               % _ordner, serve_n == 0 and rueck is None,
               "kern.serve %dx, Rueckgabe %r" % (serve_n, rueck))
        # A3e-K KONTROLLEN, DIE ROT WERDEN MUESSEN — sonst messen die zwei
        # Zeilen darueber nichts. (1) Der alte Rueckfall, wieder eingesetzt,
        # muss als kern.serve-Aufruf auffallen. (2) Ohne `verbinden=True`
        # (der Stand vor 2026-09-22) muss die erste Zeile es sehen.
        _k_baum = ast.parse(_quelle)
        for _f in _k_baum.body:
            if isinstance(_f, ast.FunctionDef) and _f.name == "serve":
                for _t in _f.body:
                    if isinstance(_t, ast.Try):
                        _t.handlers[0].body.append(ast.parse(
                            "return kern.serve(konfiguration(kern))").body[0])
        ast.fix_missing_locations(_k_baum)
        _r, _kw, _n = _a3e_messen(_k_baum, _pfad, wirft=True)
        pruefe("A3e-K %s: der alte Rueckfall wird erkannt" % _ordner, _n == 1,
               "kern.serve %dx (erwartet 1)" % _n)
        _k_baum = ast.parse(_quelle)
        for _c in ast.walk(_k_baum):
            if (isinstance(_c, ast.Call) and isinstance(_c.func, ast.Attribute)
                    and _c.func.attr == "oeffnen"):
                _c.keywords = []
        _r, _kw, _n = _a3e_messen(_k_baum, _pfad, wirft=False)
        pruefe("A3e-K %s: ohne verbinden=True faellt es auf" % _ordner,
               _kw == [{}], "oeffnen-Aufrufe %s (erwartet [{}])" % _kw)
    pruefe("A3e mindestens A und der ausgerollte Einstieg geprueft",
           _gen.DYNAMISCHER_ORDNER in _a3e and len(_a3e) >= 2,
           "geprueft: %s" % _a3e)

    # A3f EIN STARTFEHLER IST SICHTBAR — auch ohne Qt, ohne stderr.
    #
    # Rueckmeldung 2026-09-24: Menueeintrag da, Klick ohne jede Wirkung.
    # Rueckmeldung Kollege zu 0.1.0 (2026-09-26), Cadwork 2025 mit PyQt5:
    # `sys.stderr` ist in Cadwork None, das `sys.stderr.write` im Einstieg
    # warf AttributeError und verdeckte den echten Fehler; der Dialog
    # importierte PyQt6, das es dort nicht gibt. Die alte Messung ersetzte
    # stderr durch ein StringIO und sah beides deshalb nie.
    #
    # Gemessen wird jetzt WIE IN CADWORK: sys.stderr = None, PyQt6/PyQt5 je
    # Fall gesperrt (None in sys.modules) oder als Attrappe, `ctypes` als
    # Attrappe (MessageBoxW zeichnet auf), Logdatei ueber
    # OPEN_MCP_CAD_START_LOG in Temp. Fuer JEDEN Einstieg mit Dashboard
    # (dieselbe Regel wie A3e), das Hilfsmodul echt von der Platte.
    def _a3f_lauf(quelle, pfad, fehler_in="kern", qt6=None, qt5=None,
                  ctypes_attr=None, log=None, raum_extra=None,
                  dll_kaputt=False, kern_version=None):
        baum = ast.parse(quelle) if isinstance(quelle, str) else quelle
        log = log or os.path.join(tempfile.mkdtemp(), "start.log")
        alt_env = os.environ.get("OPEN_MCP_CAD_START_LOG")
        os.environ["OPEN_MCP_CAD_START_LOG"] = log
        try:
            raum = {"__name__": "a3f_einstieg", "__file__": pfad}
            exec(compile(baum, pfad, "exec"), raum)
        finally:
            if alt_env is None:
                os.environ.pop("OPEN_MCP_CAD_START_LOG", None)
            else:
                os.environ["OPEN_MCP_CAD_START_LOG"] = alt_env
        kern = _A3eKern(kern_version or raum.get("ERWARTETE_KERN_VERSION"))

        def _kern():
            if fehler_in == "kern":
                raise SyntaxError("Attrappe: Kern laedt nicht")
            return kern
        raum["kern_laden"] = _kern
        raum["dashboard_laden"] = lambda: _A3eDashboard(
            fehler_in == "dashboard")
        if dll_kaputt:
            raum["DLL_PFADE_PFAD"] = os.path.join(tempfile.mkdtemp(),
                                                  "fehlt.py")
        else:
            raum["cadwork_dll_pfade_einrichten"] = lambda: None
        raum.update(raum_extra or {})
        ctypes_attr = ctypes_attr or _CtypesAttrappe()
        for _a in (ctypes_attr, qt6, qt5):
            if _a is not None:
                _a.log = log
        rueck = geworfen = None
        with _startfehler_sandbox(qt6, qt5, ctypes_attr):
            try:
                rueck = raum["serve"]()
            except BaseException as exc:                  # noqa: BLE001
                geworfen = exc
        inhalt = io.open(log, encoding="utf-8").read() \
            if os.path.exists(log) else ""
        return types.SimpleNamespace(rueck=rueck, geworfen=geworfen, log=log,
                                     inhalt=inhalt, boxen=ctypes_attr.boxen,
                                     raum=raum)

    def _log_vollstaendig(r, pfad, erwartet):
        fehlt = [n for n, da in (
            ("Zeitstempel", re.search(r"=== \d{4}-\d\d-\d\d \d\d:\d\d:\d\d",
                                      r.inhalt)),
            ("Python-Version", sys.version.split()[0] in r.inhalt),
            ("sys.executable", sys.executable in r.inhalt),
            ("Plugin-Pfad", os.path.abspath(pfad) in r.inhalt),
            ("Traceback", "Traceback (most recent call last)" in r.inhalt),
            ("Fehlertext", erwartet in r.inhalt)) if not da]
        return fehlt

    def _laientext(text, log):
        # Seit 2026-10-10 (Cadwork 2025 mit PyQt5) nur OHNE jedes Qt: "braucht
        # Qt", beide Bindungen genannt — nie mehr "braucht Cadwork 2026".
        return ("braucht Qt" in text and "PyQt6" in text and "PyQt5" in text
                and "Cadwork 2026." not in text and log in text)

    def _mutiert(quelle, funktion, neuer_rumpf=None, davor=None):
        """Quelle mit ersetztem Rumpf / vorangestellter Anweisung."""
        b = ast.parse(quelle)
        for f in ast.walk(b):
            if isinstance(f, ast.FunctionDef) and f.name == funktion:
                if neuer_rumpf is not None:
                    f.body = ast.parse(neuer_rumpf).body
                if davor is not None:
                    f.body = ast.parse(davor).body + f.body
        ast.fix_missing_locations(b)
        return b

    _a3f = []
    for _i, _ordner, _p in _gen.ALLE_ORDNER:
        _pfad = os.path.join(REPO, "cad_plugin", _ordner, _ordner + ".py")
        _quelle = io.open(_pfad, encoding="utf-8").read()
        if not any(isinstance(k, ast.FunctionDef)
                   and k.name == "dashboard_laden"
                   for k in ast.parse(_quelle).body):
            continue
        _a3f.append(_ordner)
        for _wo in ("kern", "dashboard"):
            r = _a3f_lauf(_quelle, _pfad, fehler_in=_wo)
            _erw = ("Attrappe: Kern laedt nicht" if _wo == "kern"
                    else "Attrappe: Dashboard kaputt")
            _f = _log_vollstaendig(r, _pfad, _erw)
            pruefe("A3f %s: Fehler im %s, stderr None, ohne PyQt6/PyQt5 -> "
                   "kein Wurf, volles Startlog, Windows-Box fuer Laien"
                   % (_ordner, _wo.capitalize()),
                   r.geworfen is None and r.rueck is None and not _f
                   and len(r.boxen) == 1 and r.boxen[0][3] is True
                   and _laientext(r.boxen[0][1], r.log),
                   "geworfen %r, im Log fehlt %s, Boxen %r"
                   % (r.geworfen, _f, r.boxen))
        _q5 = _QtAttrappe()
        r = _a3f_lauf(_quelle, _pfad, qt5=_q5)
        pruefe("A3f %s: ohne PyQt6 mit PyQt5 -> Qt5-Dialog (\"konnte nicht "
               "starten\", nicht \"braucht Cadwork 2026\"), keine Windows-Box, "
               "Startlog mit PyQt5-/Qt-Version"
               % _ordner,
               r.geworfen is None and len(_q5.dialoge) == 1
               and _q5.dialoge[0][2] is True
               and "konnte nicht starten" in _q5.dialoge[0][1]
               and "2026" not in _q5.dialoge[0][1]
               and r.log in _q5.dialoge[0][1] and r.boxen == []
               and "PyQt5 5.15.91 / Qt 5.15.92" in r.inhalt,
               "Qt5 %r, Boxen %r, Qt-Zeile %r" % (
                   _q5.dialoge, r.boxen,
                   [z for z in r.inhalt.splitlines() if z.startswith("Qt ")]))
        _q6, _q5 = _QtAttrappe(), _QtAttrappe()
        r = _a3f_lauf(_quelle, _pfad, qt6=_q6, qt5=_q5)
        pruefe("A3f %s: mit PyQt6 -> Qt6-Dialog, PyQt5 unberuehrt" % _ordner,
               r.geworfen is None and len(_q6.dialoge) == 1
               and _q6.dialoge[0][2] is True
               and "konnte nicht starten" in _q6.dialoge[0][1]
               and r.log in _q6.dialoge[0][1]
               and _q5.instance_rufe == 0 and r.boxen == [],
               "Qt6 %r, Qt5-Rufe %d, Boxen %r"
               % (_q6.dialoge, _q5.instance_rufe, r.boxen))
        _q6, _q5 = _QtAttrappe(mit_app=False), _QtAttrappe()
        r = _a3f_lauf(_quelle, _pfad, qt6=_q6, qt5=_q5)
        pruefe("A3f %s: PyQt6 ohne QApplication -> Windows-Box, kein Qt5"
               % _ordner,
               r.geworfen is None and _q6.dialoge == [] and len(r.boxen) == 1
               and _q5.instance_rufe == 0,
               "Qt6 %r, Qt5-Rufe %d, Boxen %r"
               % (_q6.dialoge, _q5.instance_rufe, r.boxen))
        _tot = os.path.join(tempfile.mkdtemp(), "gibt_es_nicht", "start.log")
        r = _a3f_lauf(_quelle, _pfad, ctypes_attr=_CtypesAttrappe(wirft=True),
                      log=_tot)
        pruefe("A3f %s: nichts geht (keine Box, Log unschreibbar) -> "
               "wirft trotzdem nicht" % _ordner,
               r.geworfen is None and r.rueck is None
               and not os.path.exists(_tot), "geworfen %r" % (r.geworfen,))
        _leer = tempfile.mkdtemp()
        r = _a3f_lauf(_quelle, _pfad, raum_extra={
            "KERN_PFAD": os.path.join(_leer, "omcad_bridge_core.py")})
        _f = _log_vollstaendig(r, _pfad, "Attrappe: Kern laedt nicht")
        pruefe("A3f %s: Hilfsmodul fehlt -> Notnagel schreibt das Startlog"
               % _ordner,
               r.geworfen is None and "Hilfsmodul fehlt oder warf" in r.inhalt
               and not _f, "geworfen %r, im Log fehlt %s"
               % (r.geworfen, _f))
        r = _a3f_lauf(_quelle, _pfad, fehler_in=None, dll_kaputt=True,
                      kern_version="0.0.0")
        pruefe("A3f %s: DLL-Pfade kaputt + falscher Kern, stderr None -> "
               "verbindet trotzdem, kein Startlog" % _ordner,
               r.geworfen is None and r.rueck == "dienst" and r.inhalt == "",
               "Rueckgabe %r, geworfen %r, Log %d Zeichen"
               % (r.rueck, r.geworfen, len(r.inhalt)))
        _alt_env = os.environ.pop("OPEN_MCP_CAD_START_LOG", None)
        try:
            _raum = {"__name__": "a3f_standard", "__file__": _pfad}
            exec(compile(_quelle, _pfad, "exec"), _raum)
        finally:
            if _alt_env is not None:
                os.environ["OPEN_MCP_CAD_START_LOG"] = _alt_env
        pruefe("A3f %s: ohne Testvariable schreibt es nach "
               "C:\\Users\\Public\\OpenMcpCad_start.log" % _ordner,
               _raum.get("START_LOG")
               == r"C:\Users\Public\OpenMcpCad_start.log",
               "START_LOG %r" % _raum.get("START_LOG"))

        # A3f-K KONTROLLEN, DIE ROT WERDEN MUESSEN.
        # (1) Der gemeldete Fall: nacktes sys.stderr.write in `meldung` und
        # vorne in `startfehler_melden` (so stand es in 0.1.0). Dann MUSS
        # der Startfehler als AttributeError aus serve() fliegen und der
        # DLL-Fall darf nicht mehr verbinden.
        _k = _mutiert(_mutiert(ast.unparse(ast.parse(_quelle)), "meldung",
                               neuer_rumpf='sys.stderr.write(text + "\\n")'),
                      "startfehler_melden",
                      davor='sys.stderr.write("Start nicht moeglich\\n")')
        _k_src = ast.unparse(_k)
        r1 = _a3f_lauf(_k_src, _pfad)
        r2 = _a3f_lauf(_k_src, _pfad, fehler_in=None, dll_kaputt=True,
                       kern_version="0.0.0")
        pruefe("A3f-K %s: nacktes sys.stderr.write (Stand 0.1.0) faellt auf"
               % _ordner,
               isinstance(r1.geworfen, AttributeError) and r1.boxen == []
               and r2.rueck != "dienst",
               "geworfen %r, Boxen %r, DLL-Fall Rueckgabe %r"
               % (r1.geworfen, r1.boxen, r2.rueck))
        # (2) Ein Hilfsmodul OHNE den PyQt5-Schritt (nur PyQt6, wie 0.1.0)
        # muss in der PyQt5-Zelle auffallen: kein Qt5-Dialog.
        _hq = io.open(os.path.join(os.path.dirname(_pfad),
                                   "omcad_startfehler.py"),
                      encoding="utf-8").read()
        _hk = _mutiert(_hq, "_qt_widgets", neuer_rumpf=(
            "try:\n"
            "    return importlib.import_module('PyQt6.QtWidgets'), "
            "'qt6', False\n"
            "except Exception:\n"
            "    return None, None, True\n"))
        _kd = tempfile.mkdtemp()
        with io.open(os.path.join(_kd, "omcad_startfehler.py"), "w",
                     encoding="utf-8") as fh:
            fh.write(ast.unparse(_hk))
        _q5 = _QtAttrappe()
        r = _a3f_lauf(_quelle, _pfad, qt5=_q5, raum_extra={
            "KERN_PFAD": os.path.join(_kd, "omcad_bridge_core.py")})
        pruefe("A3f-K %s: Hilfsmodul ohne PyQt5-Schritt faellt auf"
               % _ordner, _q5.dialoge == [] and len(r.boxen) == 1,
               "Qt5 %r, Boxen %r" % (_q5.dialoge, r.boxen))
        # (2b) Cadwork 2025 (seit 2026-10-10): der alte Text "braucht
        # Cadwork 2026" bei PyQt5 und ein Startlog ohne Qt-Stand muessen in
        # der PyQt5-Zelle auffallen.
        _hq = io.open(os.path.join(os.path.dirname(_pfad),
                                   "omcad_startfehler.py"),
                      encoding="utf-8").read()
        for _was, _alt, _neu in (
                ("PyQt5 gilt als 'Qt fehlt' (alter Text)",
                 'return importlib.import_module("PyQt5.QtWidgets"), "qt5", '
                 'False',
                 'return importlib.import_module("PyQt5.QtWidgets"), "qt5", '
                 'True'),
                ("Startlog ohne Qt-Stand",
                 '"Qt          %s" % _qt_stand(),', '')):
            _kd = tempfile.mkdtemp()
            with io.open(os.path.join(_kd, "omcad_startfehler.py"), "w",
                         encoding="utf-8") as fh:
                fh.write(_hq.replace(_alt, _neu))
            _q5 = _QtAttrappe()
            r = _a3f_lauf(_quelle, _pfad, qt5=_q5, raum_extra={
                "KERN_PFAD": os.path.join(_kd, "omcad_bridge_core.py")})
            _gut = (len(_q5.dialoge) == 1
                    and "konnte nicht starten" in _q5.dialoge[0][1]
                    and "PyQt5 5.15.91 / Qt 5.15.92" in r.inhalt)
            pruefe("A3f-K %s: %s faellt auf" % (_ordner, _was),
                   _alt in _hq and not _gut,
                   "Mutant nicht gesetzt" if _alt not in _hq
                   else "Qt5 %r" % (_q5.dialoge,))
        # (3) Ohne Meldung im except-Zweig von serve(): kein Log, keine Box.
        _k_baum = ast.parse(_quelle)
        for _f in _k_baum.body:
            if isinstance(_f, ast.FunctionDef) and _f.name == "serve":
                for _t in _f.body:
                    if isinstance(_t, ast.Try):
                        _t.handlers[0].body = [ast.Pass()]
        ast.fix_missing_locations(_k_baum)
        r = _a3f_lauf(_k_baum, _pfad)
        pruefe("A3f-K %s: ohne Meldung im except-Zweig faellt es auf"
               % _ordner, r.inhalt == "" and r.boxen == [],
               "Log %d Zeichen, Boxen %r" % (len(r.inhalt), r.boxen))
        # (4) «Log erst nach dem Dialog» (Gegenpruefung 2026-09-26): die
        # Attrappe sieht beim Aufruf noch keine Logdatei -> MUSS auffallen.
        _hq = io.open(os.path.join(os.path.dirname(_pfad),
                                   "omcad_startfehler.py"),
                      encoding="utf-8").read()
        _alt1 = "log_ok = log_schreiben(exc, plugin, log)"
        _alt2 = '            _win32_dialog(text)\n            return "win32"'
        _spaet = _hq.replace(_alt1, "log_ok = True").replace(
            _alt2, '            _win32_dialog(text)\n'
                   '            log_schreiben(exc, plugin, log)\n'
                   '            return "win32"')
        _kd = tempfile.mkdtemp()
        with io.open(os.path.join(_kd, "omcad_startfehler.py"), "w",
                     encoding="utf-8") as fh:
            fh.write(_spaet)
        r = _a3f_lauf(_quelle, _pfad, raum_extra={
            "KERN_PFAD": os.path.join(_kd, "omcad_bridge_core.py")})
        pruefe("A3f-K %s: Log erst NACH dem Dialog faellt auf" % _ordner,
               _hq.count(_alt1) == 1 and _hq.count(_alt2) == 1
               and len(r.boxen) == 1 and r.boxen[0][3] is False
               and "Traceback" in r.inhalt,
               "Boxen %r, Log %d Zeichen" % (r.boxen, len(r.inhalt)))

        # melden() selbst wirft NIE — direkt gerufen, ohne den Notnagel des
        # Einstiegs, der einen Wurf sonst ueberdeckt.
        def _hilfsmodul(quelle, pfad):
            m = types.ModuleType("omcad_startfehler_a3f")
            m.__file__ = pfad
            exec(compile(quelle, pfad, "exec"), m.__dict__)
            return m

        def _melden_direkt(modul):
            log = os.path.join(tempfile.mkdtemp(), "start.log")
            ca = _CtypesAttrappe(wirft=True)
            ca.log = log
            try:
                with _startfehler_sandbox(ctypes_attr=ca):
                    return modul.melden(RuntimeError("Attrappe direkt"),
                                        _pfad, log), None, log
            except BaseException as exc:                  # noqa: BLE001
                return None, exc, log

        _hp = os.path.join(os.path.dirname(_pfad), "omcad_startfehler.py")
        _w, _g, _l = _melden_direkt(_hilfsmodul(_hq, _hp))
        pruefe("A3f %s: melden() direkt, MessageBoxW wirft -> None, kein "
               "Wurf, Log da" % _ordner,
               _w is None and _g is None and os.path.exists(_l),
               "Rueckgabe %r, geworfen %r" % (_w, _g))
        # KONTROLLE: melden() ohne seine try-Huellen (aeussere und die um
        # MessageBoxW) MUSS hier werfen.
        _mb = ast.parse(_hq)
        for _fn in ast.walk(_mb):
            if isinstance(_fn, ast.FunctionDef) and _fn.name == "melden":
                _aussen = [x for x in _fn.body if isinstance(x, ast.Try)][0]
                _rumpf = []
                for _x in _aussen.body:
                    if (isinstance(_x, ast.Try)
                            and "_win32_dialog" in ast.unparse(_x)):
                        _rumpf.extend(_x.body)
                    else:
                        _rumpf.append(_x)
                _fn.body = _rumpf
        ast.fix_missing_locations(_mb)
        _w, _g, _l = _melden_direkt(_hilfsmodul(ast.unparse(_mb), _hp))
        pruefe("A3f-K %s: melden() ohne try-Huellen wirft (die Zelle "
               "darueber misst also)" % _ordner, isinstance(_g, OSError),
               "geworfen %r" % (_g,))

        # Logdatei ueber 256 KB: wird zu <log>.1, die neue beginnt leer;
        # darunter wird angehaengt (Kontrolle: kleine Datei bleibt stehen).
        _d = tempfile.mkdtemp()
        _gross = os.path.join(_d, "start.log")
        with io.open(_gross, "w", encoding="utf-8") as fh:
            fh.write("ALT\n" * 70000)
        r = _a3f_lauf(_quelle, _pfad, log=_gross)
        _eins = _gross + ".1"
        _eins_gr = os.path.getsize(_eins) if os.path.exists(_eins) else 0
        pruefe("A3f %s: Log > 256 KB -> alte Datei als .1, neue beginnt"
               % _ordner,
               _eins_gr >= 280000 and "ALT\n" not in r.inhalt
               and "Traceback" in r.inhalt,
               ".1 %d Byte, neu %d Zeichen" % (_eins_gr, len(r.inhalt)))
        _klein = os.path.join(tempfile.mkdtemp(), "start.log")
        with io.open(_klein, "w", encoding="utf-8") as fh:
            fh.write("ALTINHALT\n")
        r = _a3f_lauf(_quelle, _pfad, log=_klein)
        pruefe("A3f-K %s: kleine Logdatei wird angehaengt, keine .1"
               % _ordner,
               r.inhalt.startswith("ALTINHALT\n") and "Traceback" in r.inhalt
               and not os.path.exists(_klein + ".1"),
               "%d Zeichen" % len(r.inhalt))
    pruefe("A3f mindestens A und der ausgerollte Einstieg geprueft",
           _gen.DYNAMISCHER_ORDNER in _a3f and len(_a3f) >= 2,
           "geprueft: %s" % _a3f)

    # A4 keine vier auseinanderlaufenden Kopien
    import hashlib
    hashes = {}
    for ordner in erwartet:
        pfad = os.path.join(REPO, "cad_plugin", ordner,
                            "omcad_bridge_core.py")
        with open(pfad, "rb") as fh:
            hashes[ordner] = hashlib.sha256(_normiert(fh.read())).hexdigest()
    with open(KERN_PFAD, "rb") as fh:
        quell_hash = hashlib.sha256(_normiert(fh.read())).hexdigest()
    pruefe("A4 alle vier Kern-Kopien == Quelle",
           set(hashes.values()) == {quell_hash},
           "Quelle %s / Kopien %s" % (quell_hash[:12],
                                      sorted({h[:12] for h in hashes.values()})))


# ==========================================================================
# Abschnitt B — Verhalten
# ==========================================================================

def abschnitt_b(kern):
    sag("\n--- B  Start, Status, Pause, Beenden ---")
    with Pruefstand(kern) as p:
        a = p.ruf("ping")
        pruefe("B1 ping antwortet mit pong (Altclient)",
               a.get("ok") and a["result"].get("pong") is True, json.dumps(a)[:90])

        a = p.ruf("status")
        s = a.get("result") or {}
        noetig = ["instanz", "port", "pid", "version", "protokoll", "dokument",
                  "zustand", "zustand_text", "gestartet", "laufzeit_s",
                  "verbindungen", "wartende_auftraege", "auftrag",
                  "letzter_auftrag", "letzter_fehler", "schreiblizenz",
                  "hauptthread_alter_s", "hinweis"]
        fehlend = [f for f in noetig if f not in s]
        pruefe("B2 Status liefert alle geforderten Felder", not fehlend,
               "fehlt: %s" % fehlend)
        pruefe("B2 Status: Zustand 'ready' -> 'Bereit'",
               s.get("zustand") == "ready" and s.get("zustand_text") == "Bereit",
               "%s / %s" % (s.get("zustand"), s.get("zustand_text")))
        pruefe("B2 Status: Dokument kommt aus dem Hauptthread-Cache",
               s.get("dokument") == _FakeDoc.name, repr(s.get("dokument")))
        pruefe("B2 Status: PID + Port + Instanz",
               s.get("pid") == os.getpid() and s.get("port") == TESTPORT
               and s.get("instanz") == "D", json.dumps(
                   {k: s.get(k) for k in ("pid", "port", "instanz")}))

        a = p.ruf("get_document_info")
        pruefe("B3 get_document_info unveraendert",
               a["ok"] and a["result"]["document_name"] == _FakeDoc.name
               and a["result"]["element_count"] == len(_FakeDoc.elemente),
               json.dumps(a.get("result"))[:90])

        # Altclient: nur 'code', keine neuen Metadaten
        a = p.ruf("execute_cwapi3d", {"code": "result = 6*7"})
        pruefe("B4 alter Client ohne Metadaten funktioniert",
               a["ok"] and a["result"]["result"] == 42
               and "stdout" in a["result"] and "vars" in a["result"],
               json.dumps(a.get("result"))[:90])

        a = p.ruf("execute_cwapi3d",
                  {"code": "result = uc.get_3d_file_name()",
                   "access_mode": "read"})
        pruefe("B4 Lesezugriff erreicht cwapi3d-Attrappe",
               a["ok"] and a["result"]["result"] == _FakeDoc.name)

        # Pause
        a = p.ruf("pause")
        pruefe("B5 pause wird angenommen", a["ok"] and a["result"]["pausiert"])
        s = p.ruf("status")["result"]
        pruefe("B5 Zustand 'paused' -> 'Pausiert'",
               s["zustand"] == "paused" and s["zustand_text"] == "Pausiert")
        a = p.ruf("execute_cwapi3d", {"code": "result = 1"})
        pruefe("B5 Modellauftrag wird mit bridge_paused abgelehnt",
               (not a["ok"]) and a["error"] == "bridge_paused", a.get("message", ""))
        pruefe("B5 Status bleibt waehrend Pause erreichbar",
               p.ruf("status")["ok"])
        a = p.ruf("resume")
        pruefe("B6 resume hebt die Pause auf",
               a["ok"] and p.ruf("status")["result"]["zustand"] == "ready")
        a = p.ruf("execute_cwapi3d", {"code": "result = 2"})
        pruefe("B6 nach resume wieder Auftraege moeglich",
               a["ok"] and a["result"]["result"] == 2)

        # Shutdown aus 'ready'
        a = p.ruf("shutdown")
        pruefe("B7 shutdown aus 'Bereit' wird angenommen",
               a["ok"] and a["result"]["shutting_down"], json.dumps(a)[:90])
        pruefe("B7 Dienst laeuft danach aus",
               warte_bis(lambda: p.dienst.zustand == "stopped", 5),
               "Zustand %s" % p.dienst.zustand)

    # Port muss wieder frei sein
    pruefe("B8 Port nach Stop frei",
           warte_bis(lambda: not kern._is_port_in_use("127.0.0.1", TESTPORT), 5))
    with Pruefstand(kern) as p:
        pruefe("B8 Neustart auf demselben Port gelingt",
               p.ruf("ping")["ok"] and p.dienst.zustand == "ready")


def abschnitt_c(kern):
    sag("\n--- C  Langer Auftrag: Status, Shutdown, Beenden nach Auftrag ---")
    with Pruefstand(kern) as p:
        lauf = p.ruf_async("execute_cwapi3d", {
            "code": LANGER_JOB % 2.5,
            "description": "Fensterwand Sued erzeugen",
            "operation_id": "op-4711",
            "access_mode": "write",
            "client_label": "Claude Code",
            "client_id": "sitzung-1",
        })
        pruefe("C1 Auftrag wird busy_write",
               warte_bis(lambda: p.dienst.zustand == "busy_write", 3),
               "Zustand %s" % p.dienst.zustand)

        t0 = time.monotonic()
        s = p.ruf("status", timeout=2.0)["result"]
        dauer = time.monotonic() - t0
        pruefe("C2 Status antwortet waehrend des Auftrags schnell", dauer < 1.0,
               "%.0f ms" % (dauer * 1000))
        pruefe("C2 Status zeigt 'Bearbeitet Modell'",
               s["zustand"] == "busy_write"
               and s["zustand_text"] == "Bearbeitet Modell")
        auftrag = s.get("auftrag") or {}
        pruefe("C3 description wird durchgereicht",
               auftrag.get("beschreibung") == "Fensterwand Sued erzeugen",
               repr(auftrag.get("beschreibung")))
        pruefe("C3 operation_id / access_mode / client_label kommen an",
               auftrag.get("operation_id") == "op-4711"
               and auftrag.get("zugriff") == "write"
               and auftrag.get("client") == "Claude Code",
               json.dumps(auftrag)[:120])
        pruefe("C3 Laufzeit des Auftrags wird mitgezaehlt",
               isinstance(auftrag.get("laufzeit_s"), (int, float))
               and auftrag["laufzeit_s"] >= 0,
               "%.1f s" % (auftrag.get("laufzeit_s") or -1))
        pruefe("C3 Schreiblizenz haelt der Auftraggeber",
               (s.get("schreiblizenz") or {}).get("client_id") == "sitzung-1",
               json.dumps(s.get("schreiblizenz")))

        # ping muss ebenfalls ohne Queue antworten
        t0 = time.monotonic()
        pruefe("C4 ping antwortet waehrend des Auftrags",
               p.ruf("ping", timeout=2.0)["ok"]
               and (time.monotonic() - t0) < 1.0)

        # Sofortiges Shutdown MUSS abgelehnt werden
        a = p.ruf("shutdown")
        pruefe("C5 shutdown waehrend 'busy' wird abgelehnt",
               (not a["ok"]) and a["error"] == "busy", a.get("message", "")[:80])
        pruefe("C5 Dienst laeuft nach der Ablehnung weiter",
               p.dienst.zustand == "busy_write")

        # Zweiter Schreibauftrag von einer ANDEREN Sitzung
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "access_mode": "write",
                                      "client_id": "sitzung-2",
                                      "client_label": "andere Sitzung"})
        pruefe("C6 zweiter Schreibauftrag anderer Sitzung -> document_busy",
               (not a["ok"]) and a["error"] == "document_busy",
               a.get("message", "")[:80])
        # Derselbe Client darf anhaengen (kontrolliert, sichtbar in der Queue)
        zweiter = p.ruf_async("execute_cwapi3d", {"code": "result = 99",
                                                  "access_mode": "write",
                                                  "client_id": "sitzung-1"})
        pruefe("C6 gleicher Client darf anhaengen",
               warte_bis(lambda: p.ruf("status")["result"]["wartende_auftraege"] >= 1,
                         3))

        lauf["thread"].join(timeout=15)
        pruefe("C7 erster Auftrag liefert sein Ergebnis",
               lauf.get("antwort", {}).get("ok")
               and lauf["antwort"]["result"]["result"] == "fertig",
               json.dumps(lauf.get("antwort", {}))[:90])
        zweiter["thread"].join(timeout=15)
        pruefe("C7 zweiter Auftrag laeuft danach",
               zweiter.get("antwort", {}).get("ok")
               and zweiter["antwort"]["result"]["result"] == 99)
        s = p.ruf("status")["result"]
        pruefe("C7 letzter_auftrag wird gemeldet",
               (s.get("letzter_auftrag") or {}).get("ok") is True
               and (s["letzter_auftrag"].get("dauer_s") or 0) >= 0,
               json.dumps(s.get("letzter_auftrag"))[:110])
        pruefe("C7 Zustand faellt auf 'Bereit' zurueck", s["zustand"] == "ready")

    sag("\n--- D  shutdown_after_current ---")
    with Pruefstand(kern) as p:
        lauf = p.ruf_async("execute_cwapi3d",
                           {"code": LANGER_JOB % 2.0,
                            "description": "Langer Testauftrag",
                            "client_id": "sitzung-1"})
        warte_bis(lambda: p.dienst.zustand == "busy_write", 3)
        # Ein wartender Auftrag, der kontrolliert verworfen werden soll
        wartend = p.ruf_async("execute_cwapi3d", {"code": "result = 5",
                                                  "client_id": "sitzung-1"})
        warte_bis(lambda: p.dienst.job_queue.qsize() >= 1, 3)

        t0 = time.monotonic()
        a = p.ruf("shutdown_after_current")
        pruefe("D1 shutdown_after_current wird sofort angenommen",
               a["ok"] and a["result"]["beenden_nach_auftrag"]
               and a["result"]["auftrag_laeuft"] is True, json.dumps(a)[:110])
        pruefe("D1 wartender Auftrag wird kontrolliert verworfen",
               a["result"]["verworfene_auftraege"] == 1,
               "verworfen=%s" % a["result"]["verworfene_auftraege"])
        wartend["thread"].join(timeout=5)
        pruefe("D1 verworfener Auftrag bekommt eine klare Antwort",
               wartend.get("antwort", {}).get("error") == "discarded",
               json.dumps(wartend.get("antwort", {}))[:90])
        pruefe("D2 Dienst laeuft noch, waehrend der Auftrag arbeitet",
               p.dienst.zustand in ("busy_write", "busy_read"),
               p.dienst.zustand)

        lauf["thread"].join(timeout=15)
        dauer = time.monotonic() - t0
        pruefe("D3 laufender Auftrag wird FERTIG (nicht abgeschnitten)",
               lauf.get("antwort", {}).get("ok")
               and lauf["antwort"]["result"]["result"] == "fertig",
               json.dumps(lauf.get("antwort", {}))[:90])
        pruefe("D3 Ende erst NACH dem Auftrag", dauer >= 1.0, "%.1f s" % dauer)
        pruefe("D4 Dienst beendet sich danach von selbst",
               warte_bis(lambda: p.dienst.zustand == "stopped", 5),
               p.dienst.zustand)
    pruefe("D4 Port danach frei",
           warte_bis(lambda: not kern._is_port_in_use("127.0.0.1", TESTPORT), 5))


def abschnitt_e(kern):
    sag("\n--- E  Dokumentschutz, Warteschlange, Fehlerfaelle ---")
    with Pruefstand(kern) as p:
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "expect_document": "Seeblick"})
        pruefe("E1 falsches Dokument -> wrong_document, nichts ausgefuehrt",
               (not a["ok"]) and a["error"] == "wrong_document",
               a.get("message", "")[:90])
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "expect_document": "Testdokument"})
        pruefe("E1 richtiges Dokument laeuft durch", a["ok"])

        a = p.ruf("execute_cwapi3d", {"code": "import os\nresult = 1"})
        pruefe("E2 Blocklist greift weiterhin",
               (not a["ok"]) and a["error"] == "PermissionError",
               a.get("message", "")[:60])

        a = p.ruf("execute_cwapi3d", {"code": "result = 1/0"})
        pruefe("E3 Fehler im Code kommt als Fehlerantwort",
               (not a["ok"]) and a["error"] == "ZeroDivisionError")
        s = p.ruf("status")["result"]
        pruefe("E3 letzter_fehler steht im Status",
               (s.get("letzter_fehler") or {}).get("fehler") == "ZeroDivisionError",
               json.dumps(s.get("letzter_fehler"))[:110])
        pruefe("E3 Dienst ist danach wieder 'Bereit'", s["zustand"] == "ready")

        a = p.ruf("unbekannte_methode")
        pruefe("E4 unbekannte Methode -> unknown_method",
               (not a["ok"]) and a["error"] == "unknown_method")
        a = p.ruf(None, roh="kein json")
        pruefe("E4 kaputtes JSON wird sofort beantwortet",
               (not a["ok"]) and a["error"] == "invalid_request")

        # Zugriffsart-Vorgabe: unbekannt gilt als Schreibzugriff
        p.ruf("release_write_lease", {"client_id": ""})
        p.ruf("execute_cwapi3d", {"code": "result = 1", "client_id": "sitzung-x"})
        s = p.ruf("status")["result"]
        pruefe("E5 execute_cwapi3d ohne Angabe gilt als Schreibzugriff",
               (s.get("schreiblizenz") or {}).get("client_id") == "sitzung-x",
               json.dumps(s.get("schreiblizenz")))
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "access_mode": "read",
                                      "client_id": "sitzung-y"})
        pruefe("E5 Lesezugriff einer anderen Sitzung bleibt erlaubt", a["ok"])
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "access_mode": "write",
                                      "client_id": "sitzung-y"})
        pruefe("E5 Schreibzugriff einer anderen Sitzung wird abgelehnt",
               (not a["ok"]) and a["error"] == "document_busy")
        a = p.ruf("execute_cwapi3d", {"code": "result = 1",
                                      "access_mode": "write",
                                      "client_id": "sitzung-y",
                                      "uebernehmen": True})
        pruefe("E5 ausdrueckliche Uebernahme ist moeglich", a["ok"])
        a = p.ruf("release_write_lease", {"client_id": "sitzung-y"})
        pruefe("E5 Lizenz kann freigegeben werden",
               a["ok"] and a["result"]["freigegeben"] is True)

    # Warteschlangen-Grenze
    with Pruefstand(kern, max_warteschlange=2) as p:
        laeufe = [p.ruf_async("execute_cwapi3d",
                              {"code": LANGER_JOB % 1.2, "client_id": "s"})
                  for _ in range(3)]
        warte_bis(lambda: p.dienst.job_queue.qsize() >= 2, 3)
        a = p.ruf("execute_cwapi3d", {"code": "result = 1", "client_id": "s"})
        pruefe("E6 volle Warteschlange -> queue_full statt stiller Stau",
               (not a["ok"]) and a["error"] == "queue_full",
               a.get("message", "")[:70])
        a = p.ruf("discard_pending")
        pruefe("E6 wartende Auftraege lassen sich verwerfen",
               a["ok"] and a["result"]["verworfene_auftraege"] >= 1,
               json.dumps(a.get("result")))
        for l in laeufe:
            l["thread"].join(timeout=10)


def abschnitt_i(kern):
    """Pruefhinweise und Elemente-Zeigen — der Inhalt des neuen Fensters."""
    sag("\n--- I  Pruefhinweise, Verlauf, Elemente zeigen ---")
    with Pruefstand(kern) as p:
        a = p.ruf("hinweis_melden", {
            "titel": "Staenderabstand ueber dem Fenster unklar",
            "text": "Angenommen: 625 stur ab links.",
            "element_ids": [3, 7, 11], "schweregrad": "frage"})
        pruefe("I1 Hinweis wird angenommen",
               a["ok"] and a["result"]["nr"] == 1
               and a["result"]["hinweise_offen"] == 1, json.dumps(a)[:90])
        a = p.ruf("hinweise")["result"]
        h = a["hinweise"][0]
        pruefe("I1 Hinweis traegt alles fuer die Anzeige",
               h["titel"].startswith("Staender") and h["schweregrad"] == "frage"
               and h["element_ids"] == [3, 7, 11] and h["status"] == "offen"
               and h["quelle"] == "KI", json.dumps(h)[:120])
        a = p.ruf("hinweis_melden", {"titel": "ohne Elemente",
                                     "schweregrad": "quatsch"})
        pruefe("I2 unbekannter Schweregrad faellt auf 'hinweis' zurueck",
               p.ruf("hinweise")["result"]["hinweise"][1]["schweregrad"]
               == "hinweis")
        a = p.ruf("hinweis_melden", {"text": "kein Titel"})
        pruefe("I2 Hinweis ohne Titel wird abgelehnt", not a["ok"],
               a.get("message", "")[:50])
        a = p.ruf("hinweis_status", {"nr": 1, "status": "erledigt"})
        pruefe("I3 Status laesst sich setzen", a["ok"])
        pruefe("I3 nur_offen filtert",
               p.ruf("hinweise", {"nur_offen": True})["result"]["anzahl"] == 1)
        a = p.ruf("hinweis_status", {"nr": 99, "status": "erledigt"})
        pruefe("I3 unbekannte Nummer -> not_found",
               (not a["ok"]) and a["error"] == "not_found")

        # I3b — die Wuensche vom 2026-08-06 an die Hinweise.
        a = p.ruf("hinweis_melden", {"titel": "dringend", "text": "x",
                                     "schweregrad": "fehler"})
        nr_f = a["result"]["nr"]
        h = [x for x in p.ruf("hinweise")["result"]["hinweise"]
             if x["nr"] == nr_f][0]
        pruefe("I3b Dringlichkeit wird aus dem Schweregrad abgeleitet",
               h["dringlichkeit"] == 5 and h["gelesen"] is False,
               json.dumps({k: h[k] for k in ("dringlichkeit", "gelesen")}))
        a = p.ruf("hinweis_melden", {"titel": "eigene Stufe",
                                     "dringlichkeit": 2})
        h = [x for x in p.ruf("hinweise")["result"]["hinweise"]
             if x["nr"] == a["result"]["nr"]][0]
        pruefe("I3b eine eigene Dringlichkeit gewinnt",
               h["dringlichkeit"] == 2, str(h["dringlichkeit"]))
        a = p.ruf("hinweis_melden", {"titel": "unsinnig", "dringlichkeit": 99})
        h = [x for x in p.ruf("hinweise")["result"]["hinweise"]
             if x["nr"] == a["result"]["nr"]][0]
        pruefe("I3b unsinnige Werte werden begrenzt statt uebernommen",
               h["dringlichkeit"] == 5, str(h["dringlichkeit"]))

        # gelesen ist NICHT erledigt — wie bei E-Mail.
        p.ruf("hinweis_status", {"nr": nr_f, "gelesen": True})
        h = [x for x in p.ruf("hinweise")["result"]["hinweise"]
             if x["nr"] == nr_f][0]
        pruefe("I3b gelesen laesst sich unabhaengig vom Status setzen",
               h["gelesen"] is True and h["status"] == "offen",
               json.dumps({k: h[k] for k in ("gelesen", "status")}))
        p.ruf("hinweis_status", {"nr": nr_f, "gelesen": False})
        h = [x for x in p.ruf("hinweise")["result"]["hinweise"]
             if x["nr"] == nr_f][0]
        pruefe("I3b und wieder auf ungelesen zuruecksetzen",
               h["gelesen"] is False)

        # Loeschen, nicht nur abhaken.
        vor = p.ruf("hinweise")["result"]["anzahl"]
        a = p.ruf("hinweis_loeschen", {"nr": nr_f})
        pruefe("I3b ein Hinweis laesst sich WEGWERFEN",
               a["ok"] and a["result"]["geloescht"] == 1
               and p.ruf("hinweise")["result"]["anzahl"] == vor - 1,
               json.dumps(a.get("result")))
        a = p.ruf("hinweis_loeschen", {"nr": nr_f})
        pruefe("I3b zweimal loeschen meldet not_found",
               (not a["ok"]) and a["error"] == "not_found")
        p.ruf("hinweis_status", {"nr": 1, "status": "erledigt"})
        a = p.ruf("hinweis_loeschen", {"erledigte": True})
        pruefe("I3b 'erledigte' raeumt alle abgehakten weg",
               a["ok"] and a["result"]["geloescht"] >= 1
               and all(x["status"] != "erledigt"
                       for x in p.ruf("hinweise")["result"]["hinweise"]),
               json.dumps(a.get("result")))
        a = p.ruf("hinweis_loeschen", {})
        pruefe("I3b ohne Angabe wird nichts geloescht", not a["ok"],
               a.get("message", "")[:50])

        # Elemente zeigen: die Attrappe kennt 1..42
        a = p.ruf("elemente_zeigen", {"element_ids": [3, 7, 999]})
        pruefe("I4 zeigt vorhandene, meldet fehlende",
               a["ok"] and a["result"]["gezeigt"] == [3, 7]
               and a["result"]["fehlen"] == [999], json.dumps(a.get("result")))
        a = p.ruf("elemente_zeigen", {"element_ids": [12345]})
        pruefe("I4 nur geloeschte Elemente -> klare Fehlermeldung",
               (not a["ok"]) and "existiert" in a.get("message", ""),
               a.get("message", "")[:70])

        # I4b — WERDEN SIE AUCH AKTIVIERT? Bis 2026-08-15 nicht: der Code
        # waehlte alles ab (`set_inactive`) und zoomte danach auf eine LEERE
        # Auswahl. Der Nutzer sah die Bauteile deshalb nur, wenn er zusaetzlich
        # "nur diese sichtbar" anhakte — pink markiert waren sie nie.
        # Die Attrappe schreibt `set_active` nach _FakeDoc.aktiv mit; ohne
        # den Aufruf im Kern bleibt die Liste leer und diese Zeile faellt.
        _FakeDoc.aktiv[:] = [99]
        a = p.ruf("elemente_zeigen", {"element_ids": [3, 7, 999]})
        pruefe("I4b die gezeigten Elemente werden AKTIVIERT (pink)",
               a["ok"] and list(_FakeDoc.aktiv) == [3, 7],
               "aktiv=%s (erwartet [3, 7])" % list(_FakeDoc.aktiv))
        pruefe("I4b KONTROLLE: fehlende Elemente werden NICHT aktiviert",
               999 not in _FakeDoc.aktiv,
               "sonst aktiviert der Kern IDs, die es nicht mehr gibt")
        pruefe("I5 Zeigen gilt als Lesezugriff (keine Schreiblizenz)",
               p.ruf("status")["result"]["schreiblizenz"] is None)

        # "nur diese sichtbar" — Aktivieren allein genuegt nicht, wenn das
        # Bauteil mitten im Modell steckt (2026-08-06).
        _FakeDoc.vorhang = []
        a = p.ruf("elemente_zeigen", {"element_ids": [3, 7],
                                      "nur_diese": True})
        versteckt = sum([i for z, i in _FakeDoc.vorhang if z == "zu"], [])
        pruefe("I5 'nur_diese' blendet alles ANDERE aus",
               a["ok"] and a["result"]["isoliert"] is True
               and 3 not in versteckt and 7 not in versteckt
               and len(versteckt) == len(_FakeDoc.elemente) - 2,
               "%d versteckt von %d" % (len(versteckt), len(_FakeDoc.elemente)))
        _FakeDoc.vorhang = []
        p.ruf("elemente_zeigen", {"element_ids": [3]})
        pruefe("I5 ohne 'nur_diese' bleibt die Sichtbarkeit unberuehrt",
               not _FakeDoc.vorhang, "%s" % _FakeDoc.vorhang)

        # I5b — "Ansicht zurueck". Live defekt gewesen (2026-08-06): das
        # Modell blieb isoliert, 2 von 16 627 Bauteilen sichtbar. Die
        # naheliegende Reparatur — Cadworks eigenen Zustand sichern — ist
        # UNMOEGLICH: `save_visibility_state()` kann seinen Rueckgabewert
        # nicht nach Python liefern (am 2026-08-07 gemessen, die Attrappe
        # bildet genau das nach). Die Bridge merkt sich die Sichtbarkeit
        # deshalb selbst.
        #
        # DIE KONTROLLE steckt in Element 11: es ist VORHER unsichtbar und
        # muss es HINTERHER wieder sein. Ein "zeig einfach alles" — die
        # bequeme Notloesung — wuerde genau daran scheitern.
        _FakeDoc.unsichtbar = {11}
        _FakeDoc.sicht_wieder = []
        p.ruf("elemente_zeigen", {"element_ids": [3, 7], "nur_diese": True})
        pruefe("I5b isoliert: nur die gezeigten sind sichtbar",
               _FakeDoc.unsichtbar == set(_FakeDoc.elemente) - {3, 7},
               "%d unsichtbar" % len(_FakeDoc.unsichtbar))
        a = p.ruf("sichtbarkeit_zurueck", {})
        pruefe("I5b stellt den Stand von vorher wieder her",
               a["ok"] and a["result"]["weg"] == "zustand"
               and _FakeDoc.unsichtbar == {11},
               "weg=%s unsichtbar=%s" % (a["result"].get("weg"),
                                         sorted(_FakeDoc.unsichtbar)))
        pruefe("I5b KONTROLLE: vorher Ausgeblendetes bleibt ausgeblendet",
               11 in _FakeDoc.unsichtbar,
               "Element 11 war vorher unsichtbar und muss es bleiben — "
               "'einfach alles zeigen' wuerde hier scheitern.")

        # Zweiter Klick darf KEIN veraltetes Bild wiederherstellen.
        a = p.ruf("sichtbarkeit_zurueck", {})
        pruefe("I5b ein zweiter Klick zeigt ersatzweise ALLES",
               a["result"]["weg"] == "alle_zeigen"
               and "ALLE" in _FakeDoc.sicht_wieder,
               "%s" % a["result"])

        # Scheitert das Zuruecknehmen, MUSS alles gezeigt werden — dieser
        # Knopf darf nie in einem isolierten Modell enden.
        import visualization_controller as _vc
        alt = _vc.set_visible
        _FakeDoc.unsichtbar = set()
        p.ruf("elemente_zeigen", {"element_ids": [3], "nur_diese": True})
        _vc.set_visible = _kaputt
        _FakeDoc.sicht_wieder = []
        a = p.ruf("sichtbarkeit_zurueck", {})
        _vc.set_visible = alt
        pruefe("I5b scheitert das Zuruecknehmen, wird ALLES gezeigt",
               a["ok"] and a["result"]["weg"] == "alle_zeigen"
               and "ALLE" in _FakeDoc.sicht_wieder,
               "%s" % _FakeDoc.sicht_wieder)
        _FakeDoc.unsichtbar = set()

        p.ruf("execute_cwapi3d", {"code": "result = 1",
                                  "description": "Testauftrag fuer Verlauf"})
        v = p.ruf("verlauf")["result"]["verlauf"]
        pruefe("I6 Verlauf enthaelt die Auftraege",
               any(x.get("beschreibung") == "Testauftrag fuer Verlauf"
                   for x in v), "%d Eintraege" % len(v))
        a = p.ruf("undo", {"schritte": 1})
        pruefe("I7 Undo laeuft ueber Cadworks eigenes make_undo",
               a["ok"] and a["result"]["rueckgaengig"] == 1,
               json.dumps(a)[:80])
        a = p.ruf("undo", {"schritte": 99})
        pruefe("I7 unsinnige Schrittzahl wird abgelehnt", not a["ok"],
               a.get("message", "")[:50])
        a = p.ruf("redo", {"schritte": 1})
        pruefe("I7 Wiederherstellen laeuft ueber Cadworks eigenes make_redo",
               a["ok"] and a["result"]["wiederhergestellt"] == 1,
               json.dumps(a)[:80])
        a = p.ruf("redo", {"schritte": 0})
        pruefe("I7 auch beim Wiederherstellen wird Unsinn abgelehnt",
               not a["ok"], a.get("message", "")[:50])

        # I8 — Undo hat ueberhaupt etwas zurueckzunehmen.
        # Bis 2026-08-06 meldete der Kern die erzeugten Elemente NICHT an;
        # `make_undo()` lief dann ins Leere (am lebenden Cadwork gemessen:
        # 563 Elemente vor UND nach dem Aufruf). Diese Pruefungen decken
        # genau das ab — sie schlagen fehl, wenn die Anmeldung wieder
        # verschwindet.
        _FakeDoc.undo_stack = []
        vor = len(_FakeDoc.elemente)
        a = p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = [ec.create_rectangular_beam_vectors()"
                     " for _ in range(2)]"),
            "description": "I8 zwei Elemente erzeugen"})
        pruefe("I8 neue Elemente werden fuer Undo angemeldet",
               a["ok"] and a["result"].get("undo_angemeldet") == 2,
               json.dumps(a.get("result"))[:90])
        pruefe("I8 und sind vor dem Undo wirklich da",
               len(_FakeDoc.elemente) == vor + 2,
               "%d statt %d" % (len(_FakeDoc.elemente), vor + 2))
        a = p.ruf("undo", {"schritte": 1})
        pruefe("I8 ein Schritt nimmt genau diesen Auftrag zurueck",
               a["ok"] and len(_FakeDoc.elemente) == vor,
               "%d statt %d" % (len(_FakeDoc.elemente), vor))
        # Wunsch 2026-08-06 — und am lebenden Modell geprueft:
        # 1790 -> 1793 -> Undo 1790 -> Redo 1793, Gruppe wieder vollstaendig.
        p.ruf("redo", {"schritte": 1})
        pruefe("I8 und Wiederherstellen holt sie zurueck",
               len(_FakeDoc.elemente) == vor + 2,
               "%d statt %d" % (len(_FakeDoc.elemente), vor + 2))
        p.ruf("undo", {"schritte": 1})

        a = p.ruf("execute_cwapi3d", {"code": "result = 1 + 1",
                                      "description": "I8 nur rechnen"})
        pruefe("I8 ein Auftrag ohne neue Elemente meldet nichts an",
               a["ok"] and a["result"].get("undo_angemeldet") == 0
               and not _FakeDoc.undo_stack,
               "stack=%d" % len(_FakeDoc.undo_stack))

        a = p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "undo_anmelden": False, "description": "I8 Abmeldung"})
        pruefe("I8 undo_anmelden=False laesst die Anmeldung weg",
               a["ok"] and a["result"].get("undo_angemeldet") == 0
               and not _FakeDoc.undo_stack,
               "stack=%d" % len(_FakeDoc.undo_stack))

        # Auch ein gescheiterter Auftrag hinterlaesst Elemente — gerade die
        # will man loswerden koennen.
        _FakeDoc.undo_stack = []
        vor = len(_FakeDoc.elemente)
        a = p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "ec.create_rectangular_beam_vectors()\n"
                     "raise RuntimeError('mittendrin abgebrochen')"),
            "description": "I8 halber Auftrag"})
        pruefe("I8 auch ein gescheiterter Auftrag meldet seine Elemente an",
               (not a["ok"]) and len(_FakeDoc.undo_stack) == 1
               and len(_FakeDoc.undo_stack[0]) == 1,
               "ok=%s stack=%s" % (a["ok"], _FakeDoc.undo_stack))
        p.ruf("undo", {"schritte": 1})
        pruefe("I8 und laesst sich danach zurueckdrehen",
               len(_FakeDoc.elemente) == vor,
               "%d statt %d" % (len(_FakeDoc.elemente), vor))


def abschnitt_j(kern):
    """Briefkasten und Schnellzeichnen."""
    sag("\n--- J  Briefkasten und Schnellzeichnen ---")
    # J0 — frisch gestartet zeichnet der Dienst so, wie die Stufe heisst,
    # die das Dock anzeigt. Bis 2.16.2 zeigte es "Auto", gezeichnet wurde
    # aber wie "Langsam", bis jemand den Regler anfasste (gemessen
    # 2026-09-25 an einem echten Steckplatz). Die Stufe kommt aus dem
    # Kern selbst, nicht aus einer Liste hier.
    cfg = kern.Konfiguration(instanz="D", port=TESTPORT + 7,
                             log_datei=os.path.join(tempfile.gettempdir(),
                                                    "omcad_test_offline.log"))
    alt_env = os.environ.pop("OPEN_MCP_CAD_SCHNELL", None)
    try:
        d = kern.Verbindungsdienst(cfg)
        pruefe("J0 frisch: Schnellzeichnen folgt der Vorgabe-Stufe '%s'"
               % kern.MODUS_VORGABE,
               d.zeichenmodus == kern.MODUS_VORGABE
               and d.schnellzeichnen is d.modus_werte()[0]
               and d.schnellzeichnen is True,
               "schnell=%r soll=%r" % (d.schnellzeichnen, d.modus_werte()[0]))
        os.environ["OPEN_MCP_CAD_SCHNELL"] = "0"
        d = kern.Verbindungsdienst(cfg)
        pruefe("J0-K OPEN_MCP_CAD_SCHNELL=0 sticht die Vorgabe (aus)",
               d.schnellzeichnen is False, repr(d.schnellzeichnen))
    finally:
        os.environ.pop("OPEN_MCP_CAD_SCHNELL", None)
        if alt_env is not None:
            os.environ["OPEN_MCP_CAD_SCHNELL"] = alt_env
    _FakeDoc.aktiv_ids = [7, 11]
    with Pruefstand(kern) as p:
        a = p.ruf("nachricht_senden", {"text": "strecke diese Facette um 15mm"})
        pruefe("J1 Nachricht wird angenommen und traegt den Bezug mit",
               a["ok"] and a["result"]["nr"] == 1
               and a["result"]["element_ids"] == [7, 11],
               json.dumps(a.get("result")))
        pruefe("J1 Facetten kommen bei wenigen Elementen mit",
               a["result"]["facetten_geliefert"] is True)
        a = p.ruf("nachricht_senden", {"text": ""})
        pruefe("J1 leere Nachricht wird abgelehnt", not a["ok"])

        a = p.ruf("nachrichten_abholen")["result"]
        pruefe("J2 Abholen liefert die Nachricht mit Kontext",
               a["anzahl"] == 1
               and a["nachrichten"][0]["text"].startswith("strecke")
               and a["nachrichten"][0]["kontext"]["element_ids"] == [7, 11],
               json.dumps(a["nachrichten"][0].get("kontext", {}))[:110])
        pruefe("J2 zweites Abholen liefert nichts mehr (nicht doppelt "
               "umsetzen)",
               p.ruf("nachrichten_abholen")["result"]["anzahl"] == 0)
        pruefe("J2 mit alle=True ist sie weiterhin nachlesbar",
               p.ruf("nachrichten_abholen", {"alle": True})["result"]["anzahl"]
               == 1)
        pruefe("J3 Status zaehlt wartende Nachrichten",
               p.ruf("status")["result"]["nachrichten_offen"] == 0)

        # Schnellzeichnen
        _FakeDoc.refresh_aus = 0
        _FakeDoc.refresh_an = 0
        a = p.ruf("schnellzeichnen", {"an": True})
        pruefe("J4 Schnellzeichnen laesst sich einschalten",
               a["ok"] and a["result"]["schnellzeichnen"] is True)
        p.ruf("execute_cwapi3d", {"code": "result = 1",
                                  "description": "mit Schnellzeichnen"})
        pruefe("J4 Auffrischung wird abgeschaltet",
               _FakeDoc.refresh_aus == 1 and p.dienst.bildschirm_aus,
               "aus=%d an=%d" % (_FakeDoc.refresh_aus, _FakeDoc.refresh_an))
        # Sie bleibt aus, solange Auftraege kommen — EIN Umschalten je Lauf
        # statt eins je Auftrag. Der Lauf ueber 125 Fensterzellen am
        # 2026-08-05 hat sonst 125-mal umgeschaltet und danach ein veraltetes
        # Bild hinterlassen.
        for _ in range(3):
            p.ruf("execute_cwapi3d", {"code": "result = 1"})
        pruefe("J4 bleibt ueber mehrere Auftraege aus (kein Flattern)",
               _FakeDoc.refresh_aus == 1,
               "%d Umschaltungen bei 4 Auftraegen" % _FakeDoc.refresh_aus)
        pruefe("J4 geht im Leerlauf von selbst wieder an",
               warte_bis(lambda: not p.dienst.bildschirm_aus, 6)
               and _FakeDoc.refresh_an >= 1,
               "aus=%d an=%d" % (_FakeDoc.refresh_aus, _FakeDoc.refresh_an))
        # Der wichtigste Fall: Auftrag geht schief, Bildschirm muss trotzdem
        # wieder angehen. Sonst bleibt Cadwork schwarz und keiner weiss warum.
        vor_an = _FakeDoc.refresh_an
        p.ruf("execute_cwapi3d", {"code": "result = 1/0"})
        pruefe("J5 auch nach einem FEHLER wird wieder eingeschaltet",
               warte_bis(lambda: _FakeDoc.refresh_an > vor_an, 6),
               "an: %d -> %d" % (vor_an, _FakeDoc.refresh_an))
        p.ruf("schnellzeichnen", {"an": False})
        p.ruf("execute_cwapi3d", {"code": "result = 1"})
        # Nach dem Wiedereinschalten muss NOCHMAL neu gezeichnet werden —
        # sonst steht ein veraltetes Bild (2026-08-05: Ausklinkungen
        # und Material erst nach Cadwork-Neustart sichtbar).
        pruefe("J5b nach Schnellzeichnen wird ein Nachzeichnen angefordert",
               p.dienst.refresh_nachholen >= 1,
               "offen: %d" % p.dienst.refresh_nachholen)
        pruefe("J5b und im Leerlauf abgearbeitet",
               warte_bis(lambda: p.dienst.refresh_nachholen == 0, 3),
               "offen: %d" % p.dienst.refresh_nachholen)
        pruefe("J5c 'Ansicht neu zeichnen' ist als Auftrag verfuegbar",
               p.ruf("neu_zeichnen")["result"]["neu_gezeichnet"] is True)
        pruefe("J5 ausgeschaltet wird nicht geklammert",
               _FakeDoc.refresh_aus == 2)
        # Ein Auftrag darf das Schnellzeichnen auch selbst mitbringen —
        # dann steht der Dauerschalter auf aus, und genau deshalb MUSS es
        # am Auftrag sichtbar sein (2026-08-05: "Haken war nicht
        # markiert, wahrscheinlich hast du es selbst aktiviert").
        vor_aus = _FakeDoc.refresh_aus
        p.ruf("execute_cwapi3d", {"code": "result = 1", "schnell": True,
                                  "description": "einmalig schnell"})
        st = p.ruf("status")["result"]
        pruefe("J7 einzelner Auftrag mit schnell=True schaltet ab",
               _FakeDoc.refresh_aus > vor_aus,
               "aus: %d -> %d" % (vor_aus, _FakeDoc.refresh_aus))
        pruefe("J7 und ist am Auftrag ablesbar, obwohl der Schalter aus ist",
               (st.get("letzter_auftrag") or {}).get("schnell") is True
               and st.get("schnellzeichnen") is False,
               json.dumps(st.get("letzter_auftrag"))[:110])
        # Relativ statt absolut: ein spaeter eingefuegter Test darf diese
        # Pruefung nicht kippen, nur weil der Zaehler weitergelaufen ist.
        vorher = _FakeDoc.refresh_aus
        p.ruf("schnellzeichnen", {"an": True})
        ok = p.ruf("elemente_zeigen", {"element_ids": [7]})["ok"]
        p.ruf("schnellzeichnen", {"an": False})
        pruefe("J6 Anzeigen wird NICHT geklammert, auch mit Schalter AN",
               ok and _FakeDoc.refresh_aus == vorher,
               "vorher=%d nachher=%d" % (vorher, _FakeDoc.refresh_aus))

        # J8 — der Anzeigebug selbst.
        # Am 2026-08-06 im Vergleichsblatt entschieden: Elemente, die bei
        # ABGESCHALTETER Auffrischung entstehen, bekommen keine Darstellung.
        # Weder vc.refresh() noch ein set_active/set_inactive-Zyklus half;
        # ein erneutes set_element_material holte Material UND Ausklinkung
        # zurueck. Diese Pruefungen schlagen fehl, wenn das Nachziehen
        # wieder verschwindet.
        pruefe("J8 Status meldet den ECHTEN Bildschirmzustand",
               "bildschirm_aus" in p.ruf("status")["result"],
               "Ohne diesen Wert war der Zustand von aussen unsichtbar — "
               "genau daran ist der erste Vergleichstest gescheitert.")

        _FakeDoc.material_gesetzt = []
        p.ruf("schnellzeichnen", {"an": True})
        a = p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = [ec.create_rectangular_beam_vectors()"
                     " for _ in range(2)]"),
            "description": "J8 im Dunkeln zeichnen"})
        dunkel = sorted(p.dienst.dunkel_entstanden)
        pruefe("J8 im Dunkeln entstandene Elemente werden gemerkt",
               a["ok"] and len(dunkel) == 2,
               "gemerkt: %s" % dunkel)
        pruefe("J8 solange der Bildschirm aus ist, wird noch nichts gesetzt",
               not _FakeDoc.material_gesetzt,
               "%d Aufrufe" % len(_FakeDoc.material_gesetzt))

        p.ruf("schnellzeichnen", {"an": False})
        pruefe("J8 im Leerlauf wird die Darstellung nachgezogen",
               warte_bis(lambda: bool(_FakeDoc.material_gesetzt), 6),
               "%d Aufrufe" % len(_FakeDoc.material_gesetzt))
        pruefe("J8 und zwar genau fuer diese Elemente",
               [ids for ids, _ in _FakeDoc.material_gesetzt] == [dunkel],
               json.dumps(_FakeDoc.material_gesetzt)[:110])
        pruefe("J8 die Liste ist danach leer (kein zweiter Durchgang)",
               not p.dienst.dunkel_entstanden,
               "offen: %s" % p.dienst.dunkel_entstanden)
        # `bildschirm_aus` faellt schon VOR dem Nachziehen auf False. Wer
        # daran misst, misst mittendrin — bei 2000 Bauteilen ergab das
        # "0 nachgezogen", obwohl alle 2000 nachgezogen wurden. Deshalb ein
        # Zaehler, auf den man von aussen warten kann.
        pruefe("J8 Status zaehlt die nachgezogenen Elemente mit",
               p.ruf("status")["result"].get("nachgezogen_gesamt") == 2,
               "gesamt: %s"
               % p.ruf("status")["result"].get("nachgezogen_gesamt"))
        # Rueckmeldung 2026-08-06: Cadwork zeigt bei eigener Rechenarbeit einen
        # Ladebalken — beim Nachziehen soll es genauso sein, sonst sieht
        # eine Pause wie ein Absturz aus.
        pruefe("J8 Cadworks Fortschrittsbalken wird ein- UND ausgeblendet",
               _FakeDoc.balken[:1] == ["an"] and _FakeDoc.balken[-1] == "aus",
               "%s" % _FakeDoc.balken)
        pruefe("J8 waehrend des Nachziehens meldet der Status keinen Haenger",
               p.ruf("status")["result"]["hauptthread_ok"] is True
               and p.ruf("status")["result"].get("nachzieht") is False,
               "Eigene Arbeit darf nicht wie ein Haenger aussehen.")

        # Ohne Schnellzeichnen gibt es nichts nachzuziehen — sonst zahlte
        # jeder normale Auftrag den Preis fuer ein Problem, das er nicht hat.
        _FakeDoc.material_gesetzt = []
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "description": "J8 bei eingeschaltetem Bildschirm"})
        pruefe("J8 bei eingeschaltetem Bildschirm wird nichts gesammelt",
               not p.dienst.dunkel_entstanden and not _FakeDoc.material_gesetzt,
               "gemerkt=%s gesetzt=%d" % (p.dienst.dunkel_entstanden,
                                          len(_FakeDoc.material_gesetzt)))

        # J9 — Zeichenmodus. DREI Stufen, deutsch. Rueckmeldung 2026-08-07, nachdem
        # 'cowork' im Echtbetrieb durchgefallen ist: "wuerde den modus
        # einfach rausstreichen ... auto, langsam, schnell".
        #
        # KEINE Stufe hat mehr eine harte Grenze. Die alte beruhte auf einer
        # Schaetzung und liess Auftraege durch, die 2,38 s blockierten, wo
        # 0,5 s erlaubt waren — eine Grenze, die nicht haelt, ist schlimmer
        # als keine. Was bleibt, ist eine EMPFEHLUNG.
        p.dienst.ms_je_teil = 35.0
        a = p.ruf("zeichenmodus", {})
        pruefe("J9 es gibt genau drei Stufen, deutsch benannt",
               [x["schluessel"] for x in a["result"]["stufen"]]
               == ["auto", "langsam", "schnell"],
               json.dumps([x["schluessel"] for x in a["result"]["stufen"]]))
        pruefe("J9 Vorgabe ist Auto",
               a["ok"] and a["result"]["zeichenmodus"] == "auto",
               json.dumps(a.get("result"))[:90])
        pruefe("J9 Auto nennt eine Haeppchen-Empfehlung",
               a["result"]["haeppchen_empfehlung"] >= 1,
               str(a["result"].get("haeppchen_empfehlung")))

        # KEIN Auftrag wird mehr abgelehnt — auch kein absurd grosser.
        b = p.ruf("execute_cwapi3d", {"code": "result = 1", "bauteile": 100000,
                                      "description": "J9 riesig"})
        pruefe("J9 kein Auftrag wird mehr wegen seiner Groesse abgelehnt",
               b["ok"], b.get("error", ""))
        pruefe("J9 und die Sperr-Zaehler sind weg",
               "abgelehnt_zu_gross" not in p.ruf("status")["result"],
               "Eine Sperre, die nicht haelt, gehoert auch nicht angezeigt.")

        a = p.ruf("zeichenmodus", {"modus": "langsam"})
        pruefe("J9 'langsam' ist die einzige Stufe ohne Schnellzeichnen",
               a["result"]["schnellzeichnen"] is False
               and all(x["schnell"] for x in a["result"]["stufen"]
                       if x["schluessel"] != "langsam"),
               json.dumps(a.get("result"))[:100])
        a = p.ruf("zeichenmodus", {"modus": "schnell"})
        pruefe("J9 'schnell' zeigt einen Ladebalken und kennt keine Empfehlung",
               a["result"]["balken_waehrend_lauf"] is True
               and a["result"]["blockade_ziel_s"] is None,
               json.dumps(a.get("result"))[:100])

        a = p.ruf("zeichenmodus", {"modus": "cowork"})
        pruefe("J9 die gestrichenen Stufen gibt es wirklich nicht mehr",
               (not a["ok"]) and a["error"] == "bad_mode",
               a.get("message", "")[:70])

        # Das Tempo muss GELERNT werden: ein fester Wert waere nach dem
        # ersten anderen Zeichenlauf falsch (Ausklinkung kostet ein
        # Vielfaches, und der Preis waechst mit dem Modell).
        p.dienst.ms_je_teil = 35.0
        p.dienst.tempo_lernen(100, 10.0)          # entspricht 100 ms je Teil
        pruefe("J9 Tempo wird gleitend gelernt, nicht uebernommen",
               35.0 < p.dienst.ms_je_teil < 100.0,
               "%.2f ms" % p.dienst.ms_je_teil)

        # Der Ladebalken in 'schnell' (bis 2026-08-07 'max') muss ueber den
        # ganzen Lauf stehen und am Ende WEG sein — Rueckmeldung 2026-08-06:
        # "sobald es fertig ist wird es ausgeblendet und dann sieht man es".
        # Erst abwarten, bis ein etwaiger Balken aus einem frueheren Test
        # abgeraeumt ist. Seit der Balken an der ERWARTETEN Dauer haengt,
        # loest schon der 100000-Bauteile-Auftrag von oben einen aus.
        warte_bis(lambda: not p.dienst.lauf_balken, 6)
        _FakeDoc.balken = []
        # KONTROLLE zur Umstellung: bis 2026-09-26 stand hier 'max'. Die
        # Stufe gibt es nicht mehr — wird das nicht rot, misst `_stufe` nichts.
        _stufe(p, "auto")
        pruefe("J9 KONTROLLE: die gestrichene Stufe 'max' wird NICHT "
               "eingestellt (bad_mode, Stufe bleibt 'auto')",
               not _stufe(p, "max") and p.dienst.zeichenmodus == "auto",
               p.dienst.zeichenmodus)
        pruefe("J9 Stufe 'schnell' eingestellt (Balken)", _stufe(p, "schnell"),
               p.dienst.zeichenmodus)
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "schnell": True, "bauteile": 1, "lauf_gesamt": 2,
            "description": "J9 schnell, Haeppchen 1"})
        pruefe("J9 in 'schnell' laeuft der Balken schon waehrend des Laufs",
               "an" in _FakeDoc.balken and "aus" not in _FakeDoc.balken,
               "%s" % _FakeDoc.balken)
        pruefe("J9 und zeigt echten Fortschritt, wenn das Ziel angemeldet ist",
               any(isinstance(x, int) and 0 < x < 100
                   for x in _FakeDoc.balken), "%s" % _FakeDoc.balken)
        pruefe("J9 am Ende des Laufs ist der Balken weg",
               warte_bis(lambda: _FakeDoc.balken[-1] == "aus", 6),
               "%s" % _FakeDoc.balken[-4:])

        # VORHANG. Rueckmeldung 2026-08-06: in 'max' (heute 'schnell') waren
        # die Zwischenschritte zu sehen, obwohl die Auffrischung aus war —
        # jedes Fensterereignis gibt
        # Cadwork eine Runde Ereignisschleife und laesst es neu zeichnen.
        # Wer nichts zeigen will, muss unsichtbar zeichnen und am Ende
        # aufdecken. Genau das wird hier festgenagelt.
        warte_bis(lambda: not p.dienst.lauf_balken, 6)
        _FakeDoc.vorhang = []
        _FakeDoc.ablauf = []
        pruefe("J9 Stufe 'schnell' eingestellt (Vorhang)", _stufe(p, "schnell"),
               p.dienst.zeichenmodus)
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "schnell": True, "bauteile": 1, "description": "J9 Vorhang zu"})
        pruefe("J9 in 'schnell' entstehen Bauteile UNSICHTBAR",
               [z for z, _i in _FakeDoc.vorhang] == ["zu"],
               "%s" % _FakeDoc.vorhang)
        pruefe("J9 am Ende geht der Vorhang auf",
               warte_bis(lambda: any(z == "auf" for z, _i in _FakeDoc.vorhang),
                         6), "%s" % _FakeDoc.vorhang)
        pruefe("J9 aufgedeckt werden genau die versteckten Bauteile",
               sorted(sum([i for z, i in _FakeDoc.vorhang if z == "zu"], []))
               == sorted(sum([i for z, i in _FakeDoc.vorhang if z == "auf"],
                             [])), "%s" % _FakeDoc.vorhang)
        # DIE Reihenfolge, an der es zuerst gescheitert ist: der Nutzer sah am
        # 2026-08-06 "kurz bevor das material geaendert wurde noch die
        # variante ohne material" — `vc.set_visible` zeichnet selbst neu.
        # Das Material MUSS vorher stehen.
        pruefe("J9 Material wird gesetzt BEVOR der Vorhang aufgeht",
               "material" in _FakeDoc.ablauf
               and _FakeDoc.ablauf.index("material")
               < _FakeDoc.ablauf.index("vorhang_auf"),
               "%s" % _FakeDoc.ablauf)

        # 'auto' zieht den Vorhang genauso — am 2026-08-06 kam die Frage, ob
        # das automatisch passiert, und es kostet gemessen 0,017 ms je
        # Bauteil. Kein Grund, es nur in 'max' (heute 'schnell') zu tun.
        warte_bis(lambda: not p.dienst.lauf_balken, 6)
        _FakeDoc.vorhang = []
        p.ruf("zeichenmodus", {"modus": "auto"})
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "schnell": True, "bauteile": 1, "description": "J9 Vorhang in auto"})
        pruefe("J9 auch 'auto' laesst unsichtbar entstehen",
               [z for z, _i in _FakeDoc.vorhang] == ["zu"],
               "%s" % _FakeDoc.vorhang)

        # 'langsam' ist die AUSNAHME: dort soll man zusehen koennen, ein
        # Vorhang waere das Gegenteil des Zwecks.
        warte_bis(lambda: not p.dienst.lauf_balken, 6)
        _FakeDoc.vorhang = []
        p.ruf("zeichenmodus", {"modus": "langsam"})
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "schnell": True, "bauteile": 1,
            "description": "J9 langsam ohne Vorhang"})
        pruefe("J9 in 'langsam' wird nichts versteckt",
               not _FakeDoc.vorhang, "%s" % _FakeDoc.vorhang)

        # WO der Fortschritt steht: in 'langsam' schaut man zu, da gehoert
        # kein Fenster ins Bild — dort nur Cadworks Balken unten rechts.
        a = p.ruf("zeichenmodus", {})["result"]
        popup = {}
        for x in a["stufen"]:
            popup[x["schluessel"]] = x["popup"]
        pruefe("J9 'langsam' zeigt KEIN Fenster im Bild",
               popup.get("langsam") is False, json.dumps(popup))

        # ... aber sehr wohl Cadworks Balken unten rechts. Bis 2026-08-07
        # hing die ganze Anzeige an `schnell` und konnte in 'langsam' nie
        # erscheinen — ausgerechnet dort, wo ein Lauf dreimal so lange
        # dauert. Rueckmeldung: "ob es unten rechts den ladebalken angezeigt hat,
        # das waere naemlich noch praktisch".
        warte_bis(lambda: not p.dienst.lauf_balken, 6)
        _FakeDoc.balken = []
        p.ruf("zeichenmodus", {"modus": "langsam"})
        p.ruf("execute_cwapi3d", {
            "code": ("import element_controller as ec\n"
                     "result = ec.create_rectangular_beam_vectors()"),
            "bauteile": 500, "description": "J9 langer Lauf in langsam"})
        pruefe("J9 auch in 'langsam' kommt der Balken",
               "an" in _FakeDoc.balken, "%s" % _FakeDoc.balken)
        pruefe("J9 und verschwindet nach dem Lauf wieder",
               warte_bis(lambda: _FakeDoc.balken and
                         _FakeDoc.balken[-1] == "aus", 8),
               "%s" % _FakeDoc.balken[-3:])
        pruefe("J9 'auto' und 'schnell' schon",
               popup.get("auto") and popup.get("schnell"), json.dumps(popup))
        p.ruf("zeichenmodus", {"modus": "auto"})
        p.ruf("zeichenmodus", {"modus": "auto"})

        # J10 — Aenderungen an BESTEHENDEN Bauteilen rueckgaengig machen.
        # Rueckmeldung 2026-08-06: "gibts keine moeglichkeit mit undo auch dinge zu
        # undoen die an bestehenden bauteilen geaendert wurden?" Doch —
        # ec.add_modified_elements_to_undo, am lebenden Modell geprueft
        # (Fi/Ta -> Glaswolle -> Undo -> Fi/Ta). Aber nur MIT ANSAGE:
        # alles pauschal anzumelden kostete gemessen 2,8 ms je Element.
        _FakeDoc.geaendert_angemeldet = []
        a = p.ruf("execute_cwapi3d", {
            "code": "result = aendert([1, 2, 3])",
            "description": "J10 Aenderung anmelden"})
        pruefe("J10 aendert() meldet bestehende Bauteile an",
               a["ok"] and a["result"]["result"] == 3
               and _FakeDoc.geaendert_angemeldet == [[1, 2, 3]],
               json.dumps(_FakeDoc.geaendert_angemeldet))
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert([])",
                                      "description": "J10 leer"})
        pruefe("J10 eine leere Liste ist kein Fehler, meldet aber nichts",
               a["ok"] and a["result"]["result"] == 0
               and len(_FakeDoc.geaendert_angemeldet) == 1)
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert('quatsch')",
                                      "description": "J10 Unsinn"})
        pruefe("J10 Unsinn wird abgelehnt statt still verschluckt",
               not a["ok"], a.get("message", "")[:60])

        # Drei Stufen (Vorschlag des Nutzers). Die Grenze ist gemessen: 2,6 ms je
        # Bauteil, 100 Sparren = 0,26 s. Ueber der Grenze wird bewusst NICHT
        # angemeldet — und das gezaehlt, statt es zu verschweigen.
        a = p.ruf("undo_aenderungen", {})
        pruefe("J10 Vorgabe ist 'bis_grenze' mit 500",
               a["ok"] and a["result"]["stufe"] == "bis_grenze"
               and a["result"]["grenze"] == 500,
               json.dumps(a.get("result")))
        p.ruf("undo_aenderungen", {"stufe": "bis_grenze", "grenze": 2})
        _FakeDoc.geaendert_angemeldet = []
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert([1, 2])",
                                      "description": "J10 unter der Grenze"})
        pruefe("J10 unter der Grenze wird angemeldet",
               a["result"]["result"] == 2 and _FakeDoc.geaendert_angemeldet,
               json.dumps(_FakeDoc.geaendert_angemeldet))
        _FakeDoc.geaendert_angemeldet = []
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert([1, 2, 3])",
                                      "description": "J10 ueber der Grenze"})
        pruefe("J10 ueber der Grenze wird NICHT angemeldet",
               a["result"]["result"] == 0
               and not _FakeDoc.geaendert_angemeldet,
               json.dumps(_FakeDoc.geaendert_angemeldet))
        pruefe("J10 und das wird gezaehlt statt verschwiegen",
               p.ruf("status")["result"]["uebersprungen_geaendert"] == 3,
               str(p.ruf("status")["result"]["uebersprungen_geaendert"]))
        p.ruf("undo_aenderungen", {"stufe": "immer"})
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert([1, 2, 3])",
                                      "description": "J10 immer"})
        pruefe("J10 'immer' meldet auch ueber der Grenze an",
               a["result"]["result"] == 3 and _FakeDoc.geaendert_angemeldet,
               json.dumps(_FakeDoc.geaendert_angemeldet))
        p.ruf("undo_aenderungen", {"stufe": "aus"})
        _FakeDoc.geaendert_angemeldet = []
        a = p.ruf("execute_cwapi3d", {"code": "result = aendert([1])",
                                      "description": "J10 aus"})
        pruefe("J10 'aus' meldet nie an",
               a["result"]["result"] == 0
               and not _FakeDoc.geaendert_angemeldet)
        a = p.ruf("undo_aenderungen", {"stufe": "quatsch"})
        pruefe("J10 unbekannte Stufe wird abgelehnt", not a["ok"],
               a.get("message", "")[:50])
        p.ruf("undo_aenderungen", {"stufe": "bis_grenze", "grenze": 500})


def abschnitt_f(kern):
    sag("\n--- F  Herzschlag / Hauptthread-Aufsicht ---")
    with Pruefstand(kern) as p:
        s = p.ruf("status")["result"]
        pruefe("F1 Herzschlag ist frisch",
               s["hauptthread_ok"] is True and s["hauptthread_alter_s"] < 1.0,
               "%.2f s" % s["hauptthread_alter_s"])
        # Gemessen 2026-08-04 in Cadwork 2026: DispatchMessageW loeste eine
        # access violation aus. Die Pumpe ist deshalb wieder aus.
        pruefe("F1 UI-Pumpe ist standardmaessig aus", s["ui_pumpe"] is False)
        # Der Default IST 'qtimer' (seit dem Nachweis an Steckplatz D).
        # Hier laeuft kein PyQt6 — also muss der Rueckfall greifen, und der
        # Status muss ehrlich sagen, was tatsaechlich antreibt.
        pruefe("F1 Default-Antrieb ist 'qtimer'",
               kern.Konfiguration("A", 1).antrieb == "qtimer",
               kern.Konfiguration("A", 1).antrieb)
        pruefe("F1 ohne Qt faellt der Antrieb auf 'mainthread' zurueck "
               "und sagt es",
               s.get("antrieb") == "mainthread", str(s.get("antrieb")))

        # Hauptthread simuliert haengen: Herzschlag kuenstlich altern lassen
        p.dienst.herzschlag_mono = time.monotonic() - 30.0
        # Zustand kuenstlich auf ready halten (kein Auftrag laeuft ohnehin)
        s = p.ruf("status")["result"]
        pruefe("F2 haengender Hauptthread wird erkannt",
               s["hauptthread_ok"] is False, json.dumps(s.get("hinweis"))[:110])
        # Die alte Fassung riet "einmal ins Cadwork-Fenster klicken oder die
        # Maus bewegen". Der Rat stammt aus der Zeit vor dem Qt-Antrieb und
        # ist nicht befolgbar, solange die Oberflaeche steht — Rueckmeldung
        # 2026-08-06: "das funktioniert ja nicht da die anzeige blockiert
        # ist, daher ist die meldung da definitiv unnoetig". Der Hinweis sagt
        # jetzt, was LOS ist, statt eine unmoegliche Handlung zu verlangen.
        pruefe("F2 Hinweis sagt was los ist, ohne unmoeglichen Rat",
               "nicht bedienbar" in s.get("hinweis", "")
               and "klicken" not in s.get("hinweis", "")
               and "Maus" not in s.get("hinweis", ""),
               s.get("hinweis", "")[:110])
        pruefe("F3 Status ist trotzdem erreichbar", s["zustand"] == "ready")

    # Einschaltbar muss sie bleiben ...
    os.environ["OPEN_MCP_CAD_UI_PUMPE"] = "1"
    try:
        with Pruefstand(kern) as p:
            pruefe("F4 OPEN_MCP_CAD_UI_PUMPE=1 schaltet die Pumpe ein",
                   p.ruf("status")["result"]["ui_pumpe"] is True)
            # ... und ein Zugriffsfehler darin darf NICHT den Dienst
            # mitnehmen. Genau das ist am 2026-08-04 in Cadwork passiert.
            p.dienst.cfg.ui_pumpe = False
            p.dienst.ui_pumpe_fehler = ("OSError: exception: access violation "
                                        "reading 0x0000000000000048")
            s2 = p.ruf("status")["result"]
            pruefe("F5 abgestuerzte UI-Pumpe wird im Status gemeldet",
                   s2["ui_pumpe"] is False
                   and "access violation" in (s2.get("ui_pumpe_fehler") or ""),
                   json.dumps(s2.get("ui_pumpe_fehler"))[:70])
            pruefe("F5 Hinweis sagt: Verbindung laeuft weiter, UI eingefroren",
                   "arbeitet normal weiter" in s2.get("hinweis", ""),
                   s2.get("hinweis", "")[:90])
            pruefe("F5 Dienst ist trotzdem einsatzbereit",
                   p.ruf("execute_cwapi3d", {"code": "result = 7"})["result"]
                   ["result"] == 7)
    finally:
        os.environ.pop("OPEN_MCP_CAD_UI_PUMPE", None)


def _g_fenster(daten):
    """Baut das Tk-Fenster, prueft G4/G5 und zerstoert es.

    Gibt (weakref auf Tk, Abfragefaden) zurueck, NIE das Tk selbst: nach der
    Rueckkehr zeigen nur noch der Faden und der Zyklus App <-> Zeile darauf.
    """
    import tkinter as tk
    import verbindungen_tk as vtk
    wurzel = app = None
    try:
        wurzel = tk.Tk()
        wurzel.withdraw()                 # nie sichtbar, nur aufgebaut
        app = vtk.App(wurzel)
        app._letzte_daten = (list(daten.values()), time.time())
        for d in daten.values():
            app.zeilen[d["instanz"]].aktualisieren(d)
        wurzel.update()
        zb = app.zeilen["B"]
        pruefe("G4 Fenster: B zeigt Dokument + Taetigkeit + Zeit",
               "Bearbeitet Modell" in zb.lbl_zustand.cget("text")
               and "Fensterwand" in zb.lbl_zustand.cget("text")
               and ":" in zb.lbl_zeit.cget("text"),
               "%r / %r" % (zb.lbl_zustand.cget("text"),
                            zb.lbl_zeit.cget("text")))
        pruefe("G4 Fenster: 'Jetzt beenden' ist bei laufendem Auftrag "
               "gesperrt", "disabled" in zb.btn_jetzt.state(),
               str(zb.btn_jetzt.state()))
        za = app.zeilen["A"]
        pruefe("G4 Fenster: 'Jetzt beenden' ist bei 'Bereit' erlaubt",
               "disabled" not in za.btn_jetzt.state(), str(za.btn_jetzt.state()))
        zd = app.zeilen["D"]
        pruefe("G4 Fenster: ausgeschalteter Steckplatz hat keine Knoepfe",
               all("disabled" in b.state() for b in
                   (zd.btn_pause, zd.btn_weiter, zd.btn_nach, zd.btn_jetzt)))
        zc = app.zeilen["C"]
        zc._details_umschalten()
        wurzel.update()
        text = zc.details.get("1.0", "end")
        pruefe("G5 Details nennen Port, PID, Version und Protokoll",
               all(w in text for w in ("Port / PID", "Plugin-Version",
                                       "Protokoll", "Schreiblizenz",
                                       "Herzschlag")),
               text.splitlines()[1] if text.strip() else "leer")
    except Exception as exc:                          # noqa: BLE001
        pruefe("G4 Fenster laesst sich aufbauen", False, repr(exc))
    finally:
        if app is not None:
            app._laeuft = False
        if wurzel is not None:
            try:
                wurzel.destroy()
            except tk.TclError:
                pass
    if wurzel is None:
        return None, None
    return weakref.ref(wurzel), getattr(app, "_abfrage_thread", None)


def _g_tk_abbauen(ref, faden):
    """Gibt Tk im HAUPTTHREAD frei, nicht irgendwann im naechsten GC.

    Nach G4/G5 haengt das Fenster in einem Referenzzyklus (App.zeilen ->
    Zeile.app -> App -> App.wurzel). Den loest nur die zyklische GC — und
    die laeuft in dem Thread, der gerade ihre Schwelle reisst. War das ein
    Thread des Pruefstands (gemessen: 'Open-MCP-CAD-D-Listener' mitten in
    V1, 47 s nach G), bricht Tcl den ganzen Prozess ab: 'Tcl_AsyncDelete:
    async handler deleted by the wrong thread', rc 3. Seit dem Merge
    Dock-Umbau (2026-09-26) traf es V1; vorher fiel die Schwelle zufaellig
    in den Hauptthread. Darum: Abfragefaden beenden (er haelt App bis zu
    seinem Ende), dann hier sammeln.
    """
    if ref is None:
        pruefe("G8 Tk wird im Hauptthread freigegeben", False,
               "Fenster nicht gebaut")
        return
    if faden is not None:
        faden.join(10)
    faden_laeuft = faden is not None and faden.is_alive()
    # Kontrolle: OHNE Sammeln im Hauptthread lebt Tk nach destroy() weiter,
    # genau der Rest, den spaeter ein fremder Thread freigibt. Wird das rot,
    # gibt es den Zyklus nicht mehr und G8 misst nichts.
    pruefe("G8-K ohne gc im Hauptthread lebt Tk nach destroy() weiter "
           "(G8 saehe den Fehler)", ref() is not None and not faden_laeuft,
           "Abfragefaden laeuft noch" if faden_laeuft else "")
    gc.collect()
    rest = ref()
    pruefe("G8 Tk wird im Hauptthread freigegeben (kein Rest fuer einen "
           "GC in einem Pruefstand-Thread)", rest is None,
           "" if rest is None else "Tk lebt, %d Verweise"
           % len(gc.get_referrers(rest)))
    del rest


def abschnitt_g(kern):
    """Oberflaeche: Client-Sicht, Fenster und Browser-Rueckfallebene.

    Das Fenster wird echt aufgebaut (Widgets realisiert), aber nie gezeigt —
    geprueft werden die Texte, die darin stehen wuerden.
    """
    sag("\n--- G  Oberflaeche 'Open MCP CAD Verbindungen' ---")
    sys.path.insert(0, HIER)
    os.environ["OPEN_MCP_CAD_PORTS"] = "A=%d,B=%d,C=%d,D=%d" % (
        TESTPORT, TESTPORT + 1, TESTPORT + 2, TESTPORT + 3)
    import connect_client as cc
    cc.STECKPLAETZE = cc._ports_aus_umgebung()
    cc.PORT_VON_INSTANZ = dict(cc.STECKPLAETZE)

    # Drei Steckplaetze in EINEM Prozess — in Cadwork seit Kern 2.17 nicht
    # mehr moeglich (ein Dienst je Prozess, Abschnitt K). Die Uebersicht
    # soll aber drei Cadwork-Prozesse sehen; nachgestellt wird das hier
    # ausdruecklich mit `mehrere_im_prozess`.
    with Pruefstand(kern, port=TESTPORT, instanz="A",
                    mehrere_im_prozess=True) as a, \
            Pruefstand(kern, port=TESTPORT + 1, instanz="B",
                       mehrere_im_prozess=True) as b, \
            Pruefstand(kern, port=TESTPORT + 2, instanz="C",
                       mehrere_im_prozess=True) as c:
        ui_job = b.ruf_async("execute_cwapi3d", {
            "code": LANGER_JOB % 3.0, "description": "Fensterwand Sued",
            "access_mode": "write", "client_id": "sitzung-ui"})
        warte_bis(lambda: b.dienst.zustand == "busy_write", 3)
        cc.pausieren("C")
        warte_bis(lambda: c.dienst.zustand == "paused", 3)

        daten = {d["instanz"]: d for d in cc.alle_status()}
        # Nicht "vier": die Zahl kommt aus der Quelle. Ein Gate, das die
        # alte Zahl festnagelt, meldet nach jeder Erweiterung Fehlalarm —
        # und Fehlalarm ist der zuverlaessigste Weg, spaeter einen echten
        # Fehler zu ueberlesen.
        pruefe("G1 alle %d Steckplaetze werden gemeldet" % len(cc.STECKPLAETZE),
               len(daten) == len(cc.STECKPLAETZE), sorted(daten))
        pruefe("G1 A meldet 'Bereit'", daten["A"]["zustand_text"] == "Bereit",
               daten["A"]["zustand_text"])
        pruefe("G1 B meldet 'Bearbeitet Modell' mit Beschreibung",
               daten["B"]["zustand_text"] == "Bearbeitet Modell"
               and (daten["B"].get("auftrag") or {}).get("beschreibung")
               == "Fensterwand Sued",
               json.dumps(daten["B"].get("auftrag"))[:80])
        pruefe("G1 C meldet 'Pausiert'", daten["C"]["zustand_text"] == "Pausiert")
        pruefe("G1 D (nicht gestartet) meldet 'Aus', nicht 'Stoerung'",
               daten["D"]["zustand_text"] == "Aus"
               and daten["D"]["erreichbar"] is False, daten["D"].get("hinweis"))
        pruefe("G2 Status aller vier in unter 3 s",
               all((d.get("antwortzeit_ms") or 0) < 3000 for d in daten.values()),
               str({k: v.get("antwortzeit_ms") for k, v in daten.items()}))

        zeilen = [cc.zeile(daten[i]) for i in "ABCD"]
        pruefe("G3 Zeilenformat wie gefordert",
               zeilen[1].startswith("B ")
               and "Bearbeitet Modell: Fensterwand Sued" in zeilen[1]
               and zeilen[3].strip().endswith("Aus"), zeilen[1].strip())

        # --- Fenster (Tk) ---
        # Bauen und Pruefen in einer eigenen Funktion: nach ihrer Rueckkehr
        # zeigt kein Name hier mehr auf Tk, G8 misst den Rest.
        _g_tk_abbauen(*_g_fenster(daten))

        # --- Ein ALTES Plugin darf nicht als "Stoerung" erscheinen ---
        # Genau der Fall beim Ausrollen: eine Instanz laeuft noch mit einer
        # Version vor 2.0 und kennt 'status' nicht.
        import socketserver

        class AltesPlugin(threading.Thread):
            """Antwortet auf alles mit unknown_method — wie die Vorversion."""

            def __init__(self, port):
                super().__init__(daemon=True)
                self.port = port
                self.server = socketserver.ThreadingTCPServer(
                    ("127.0.0.1", port), self._handler())
                self.server.allow_reuse_address = True

            def _handler(self):
                class H(socketserver.StreamRequestHandler):
                    def handle(self):
                        self.rfile.readline()
                        self.wfile.write(json.dumps({
                            "id": 1, "ok": False, "error": "unknown_method",
                            "message": "Unbekannte Methode: 'status'",
                            "details": ""}).encode() + b"\n")
                return H

            def run(self):
                self.server.serve_forever()

        alt = AltesPlugin(TESTPORT + 3)          # steht auf Steckplatz D
        alt.start()
        time.sleep(0.3)
        try:
            d_alt = cc.status("D")
            pruefe("G7 altes Plugin heisst 'Laeuft (alte Version)', "
                   "nicht 'Stoerung'",
                   d_alt["zustand"] == "veraltet"
                   and d_alt["zustand_text"] == cc.ZUSTAND_TEXT["veraltet"],
                   "%s / %s" % (d_alt["zustand"], d_alt["zustand_text"]))
            pruefe("G7 Hinweis nennt die Abhilfe",
                   "neu starten" in d_alt.get("hinweis", ""),
                   d_alt.get("hinweis", "")[:80])
            pruefe("G7 altes Plugin gilt als erreichbar",
                   d_alt["erreichbar"] is True)
            # Schonfrist: ein altes Plugin beantwortet 'status' ueber seine
            # Job-Queue, also im Cadwork-HAUPTTHREAD. Im Sekundentakt waere
            # das ein Dauerstrom von Fremdauftraegen in ein produktiv
            # genutztes Cadwork.
            cc._letzter_status.clear()
            vorher = alt.server.RequestHandlerClass
            cc.alle_status()
            zaehler = {"n": 0}
            urspruenglich = cc.status

            def gezaehlt(*a, **k):
                zaehler["n"] += 1
                return urspruenglich(*a, **k)

            cc.status = gezaehlt
            try:
                for _ in range(5):
                    cc.alle_status()
            finally:
                cc.status = urspruenglich
            pruefe("G7 altes Plugin wird nicht im Sekundentakt belaestigt",
                   zaehler["n"] == 5 * (len(cc.STECKPLAETZE) - 1),
                   "%d Abfragen statt %d" % (zaehler["n"],
                                             5 * len(cc.STECKPLAETZE)))
            cc._letzter_status.clear()
        finally:
            alt.server.shutdown()
            alt.server.server_close()

        # --- Browser-Rueckfallebene ---
        try:
            import urllib.request
            from http.server import ThreadingHTTPServer
            import verbindungen_web as vweb
            server = ThreadingHTTPServer(("127.0.0.1", TESTPORT + 9),
                                         vweb.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            basis = "http://127.0.0.1:%d" % (TESTPORT + 9)
            seite = urllib.request.urlopen(basis + "/", timeout=5).read().decode()
            pruefe("G6 Browser-Seite wird ausgeliefert",
                   "Open MCP CAD Verbindungen" in seite and "<script>" in seite,
                   "%d Zeichen" % len(seite))
            # B einen FRISCHEN Auftrag geben, statt zu hoffen, dass der aus
            # G1 noch laeuft. Er dauert 3 s, und zwischen G1 und hier liegt
            # inzwischen genug Arbeit — mit sechs Steckplaetzen fragt allein
            # G7 fuenfmal alle ab. Der Test haette also je nach Laufzeit der
            # Maschine bestanden oder nicht; das ist keine Messung, das ist
            # Wuerfeln. (Gefunden, als die Erweiterung auf sechs Steckplaetze
            # ihn kippte — der Fehler lag nicht an der Erweiterung.)
            b.ruf_async("execute_cwapi3d", {
                "code": LANGER_JOB % 8.0, "description": "Fensterwand Sued",
                "access_mode": "write", "client_id": "sitzung-ui"})
            warte_bis(lambda: b.dienst.zustand == "busy_write", 3)
            roh = urllib.request.urlopen(basis + "/status", timeout=8).read()
            js = json.loads(roh.decode())
            pruefe("G6 /status liefert alle %d Steckplaetze"
                   % len(cc.STECKPLAETZE),
                   len(js.get("steckplaetze", [])) == len(cc.STECKPLAETZE),
                   "%d gemeldet" % len(js.get("steckplaetze", [])))
            pruefe("G6 /status nennt Zustand im Klartext",
                   {s["zustand_text"] for s in js["steckplaetze"]}
                   >= {"Bereit", "Bearbeitet Modell", "Pausiert", "Aus"},
                   str([s["zustand_text"] for s in js["steckplaetze"]]))
            server.shutdown()
            server.server_close()
        except Exception as exc:                      # noqa: BLE001
            pruefe("G6 Browser-Rueckfallebene laeuft", False, repr(exc))

        # Den langen Auftrag ausdruecklich auslaufen lassen: ein noch
        # laufender Job haelt sonst stdout umgeleitet, und der Testbericht
        # verschwindet in dessen Puffer.
        ui_job["thread"].join(timeout=15)

    os.environ.pop("OPEN_MCP_CAD_PORTS", None)


def abschnitt_h(kern):
    """Qt-Takt: dieselbe Arbeit, anderer Antrieb.

    PyQt6 gibt es hier nicht — geprueft wird deshalb die Funktion, die der
    Timer-Rueckruf aufruft (`_tick(d, 0)`, nicht blockierend). Wenn die
    dasselbe leistet wie die klassische Schleife, haengt am Qt-Antrieb nur
    noch die Frage, ob Cadworks Timer feuert — und das ist eine Frage an
    Cadwork, nicht an diesen Code.
    """
    sag("\n--- H  Qt-Antrieb (Takt-Funktion ohne Qt) ---")
    cfg = kern.Konfiguration(instanz="D", port=TESTPORT + 5,
                             log_datei=os.path.join(tempfile.gettempdir(),
                                                    "omcad_test_offline.log"))
    d = kern.Verbindungsdienst(cfg)
    laeuft = {"an": True}

    def takt():
        """Steht fuer den QTimer: ruft _tick immer wieder, blockiert nie."""
        while laeuft["an"] and not d.beenden:
            t0 = time.monotonic()
            kern._tick(d, 0)
            # Ein Takt darf den Hauptthread nur kurz belegen - ausser er
            # arbeitet gerade einen Auftrag ab.
            if d.zustand not in ("busy_read", "busy_write"):
                dauer = time.monotonic() - t0
                d._letzte_taktdauer = dauer
                # ALLE Dauern sammeln, nicht nur die letzte: geprueft wird
                # der Median. Warum, steht bei H4.
                d._taktdauern = getattr(d, "_taktdauern", [])
                d._taktdauern.append(dauer)
            time.sleep(0.02)

    # Aufbau wie serve(), nur ohne dessen Schleife
    import socket as _socket
    import threading as _threading
    d.beenden = False
    d.start_epoch = time.time()
    d.start_mono = time.monotonic()
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.bind((cfg.host, cfg.port))
    sock.listen(4)
    sock.settimeout(1.0)
    _threading.Thread(target=kern._listener_loop, args=(d, sock),
                      daemon=True).start()
    kern._bereit_melden(d)
    t = _threading.Thread(target=takt, daemon=True)
    t.start()
    try:
        pruefe("H1 Dienst wird ohne die klassische Schleife bereit",
               warte_bis(lambda: d.zustand == "ready", 3), d.zustand)

        def ruf(methode, params=None, timeout=10.0):
            req = {"id": 1, "method": methode, "params": params or {}}
            with _socket.create_connection(("127.0.0.1", cfg.port),
                                           timeout=timeout) as s2:
                s2.settimeout(timeout)
                s2.sendall((json.dumps(req) + "\n").encode())
                puffer = bytearray()
                while b"\n" not in puffer:
                    puffer.extend(s2.recv(4096))
            return json.loads(bytes(puffer).partition(b"\n")[0].decode())

        a = ruf("execute_cwapi3d", {"code": "result = 3*14",
                                    "description": "Takt-Test"})
        pruefe("H2 Auftrag laeuft im Takt durch",
               a["ok"] and a["result"]["result"] == 42)
        s2 = ruf("status")["result"]
        pruefe("H2 Status kennt den Auftrag",
               (s2.get("letzter_auftrag") or {}).get("beschreibung")
               == "Takt-Test")
        pruefe("H3 Herzschlag laeuft auch im Takt",
               s2["hauptthread_ok"] is True
               and s2["hauptthread_alter_s"] < 1.0,
               "%.2f s" % s2["hauptthread_alter_s"])
        # H4 PRUEFT DEN MEDIAN, NICHT DEN LETZTEN TAKT.
        #
        # Vorher stand hier `_letzte_taktdauer < 0.02` — die Dauer EINES
        # Takts, naemlich des zufaellig letzten. Gemessen am 2026-09-21:
        # zwei von sechs Laeufen rot, mit 0.031 bis 0.032 s, waehrend
        # nichts am Kern anders war. Auf einer belasteten Maschine erwischt
        # ein einzelner Takt den Scheduler oder die Speicherbereinigung.
        #
        # Ein Gate, das zufaellig rot wird, ist schlimmer als keins: es
        # kostet jedes Mal eine Fehlersuche, und irgendwann glaubt man ihm
        # auch dann nicht, wenn es recht hat. (Beim Bau dieser Runde hat es
        # mich eine halbe Eingrenzung gekostet, die methodisch kaputt war —
        # bei einem flatternden Test sagt ein Einzellauf nichts.)
        #
        # Die Aussage, die zaehlt, ist "ein Takt belegt den Hauptthread
        # TYPISCH nur kurz". Das ist der Median. Der Hoechstwert wird
        # zusaetzlich geprueft, aber gegen eine Grenze, die einen einzelnen
        # Aussetzer vertraegt — ein systematisch langsamer Takt faellt in
        # beiden auf.
        # EIGENE MESSREIHE, statt die Takte des Hintergrundthreads zu
        # nehmen. Davon kommen gemessen nur ZWEI bis DREI zusammen, bis die
        # Pruefungen durch sind — und bei zwei Werten ist
        # `sorted(x)[len(x)//2]` der GROESSERE. Ein "Median" aus zwei
        # Messungen ist kein Median; der erste Anlauf dieses Fixes war
        # damit wirkungslos, und die sechs gruenen Laeufe danach waren
        # Glueck. (Gemessen, nachdem die Kontrollzelle "aus 1 Takten"
        # gemeldet hat.)
        _laeuft_vorher = laeuft["an"]
        laeuft["an"] = False          # den Hintergrundtakt anhalten
        time.sleep(0.05)
        _dauern = []
        for _ in range(21):
            _t0 = time.monotonic()
            kern._tick(d, 0)
            _dauern.append(time.monotonic() - _t0)
        laeuft["an"] = _laeuft_vorher
        _dauern.sort()
        _median = _dauern[len(_dauern) // 2]
        pruefe("H4 ein Leerlauf-Takt belegt den Hauptthread nur kurz "
               "(Median)",
               _median < 0.02,
               "Median %.4f s aus %d eigenen Takten (max %.4f)"
               % (_median, len(_dauern), _dauern[-1]))
        pruefe("H4 und auch der langsamste Takt bleibt im Rahmen",
               _dauern[-1] < 0.20,
               "max %.4f s — ein einzelner Aussetzer ist erlaubt, ein "
               "systematisch langsamer Takt nicht" % _dauern[-1])
        a = ruf("pause")
        pruefe("H5 Pause wirkt auch im Takt",
               a["ok"] and ruf("status")["result"]["zustand"] == "paused")
        ruf("resume")
        a = ruf("shutdown")
        pruefe("H6 Shutdown wirkt auch im Takt", a["ok"])
        pruefe("H6 Takt laeuft danach aus",
               warte_bis(lambda: d.beenden, 3))

    finally:
        laeuft["an"] = False
        d.beenden = True
        kern._safe_shutdown_close(sock)
        t.join(timeout=3)

    # Zweiter Start bei laufendem Steckplatz: kein Port-Konflikt, sondern
    # derselbe Dienst zurueck. In Cadwork holt der Plugin-Knopf damit ein
    # weggeklicktes Anzeigefenster zurueck, statt zu scheitern.
    d.beenden = False
    kern._QT_LAEUFT.append({"dienst": d, "timer": None, "fenster": None})
    try:
        pruefe("H7 zweiter Start liefert den laufenden Dienst zurueck",
               kern.serve(cfg) is d)
    finally:
        d.beenden = True
        kern._QT_LAEUFT.clear()


def _k_dienst(kern, instanz="K"):
    """Ein Dienst wie im Qt-Antrieb, aber ohne Netz: nur der Takt zaehlt."""
    cfg = kern.Konfiguration(instanz=instanz, port=TESTPORT + 7,
                             log_datei=os.path.join(tempfile.gettempdir(),
                                                    "omcad_test_offline.log"))
    d = kern.Verbindungsdienst(cfg)
    d.beenden = False
    kern._bereit_melden(d)
    return d


def _k_job(kern, methode="get_document_info", params=None):
    params = dict(params or {})
    return kern.Job(1, methode, params, kern.AuftragsMeta(methode, params))


def _k_zurueckhalten(kern, aufrufe):
    """Befund 1: Cadwork rechnet (Viewer-Modus) -> kein cwapi3d aus dem Takt.

    `_takt` ist genau das, was der QTimer des Qt-Antriebs aufruft. Die Sonde
    steht hier fuer 'modaler Fortschrittsdialog offen'; ob die ECHTEN
    Qt-Sonden ihn sehen, misst test_a_live (L35, L36).
    """
    d = _k_dienst(kern)
    lage = {"grund": "modaler Dialog offen: QProgressDialog 'Viewer-Modus'"}

    def sonde():
        return lage["grund"]

    job = _k_job(kern)
    d.job_queue.put(job)
    vorher = len(aufrufe)
    for _ in range(5):
        kern._takt(d, [sonde])
    s = d.status()
    pruefe("K1 Cadwork beschaeftigt: der Auftrag bleibt in der Warteschlange",
           not job.event.is_set() and d.job_queue.qsize() == 1,
           "Antwort %r, %d wartend" % (job.response, d.job_queue.qsize()))
    pruefe("K1 und in fuenf Takten KEIN einziger cwapi3d-Aufruf",
           len(aufrufe) == vorher, "%d Aufrufe" % (len(aufrufe) - vorher))
    pruefe("K1 der Status sagt, warum und wie viele warten",
           s["cadwork_beschaeftigt"] == lage["grund"]
           and "QProgressDialog" in s["hinweis"]
           and "1 wartend" in s["hinweis"]
           and s["zurueckgehalten_s"] is not None, s["hinweis"])
    pruefe("K1 Zustand bleibt 'bereit', der Hauptthread gilt als lebendig",
           s["zustand"] == "ready" and s["hauptthread_ok"] is True,
           "%s / %s" % (s["zustand"], s["hauptthread_ok"]))

    lage["grund"] = ""
    kern._takt(d, [sonde])
    s = d.status()
    pruefe("K2 frei: der naechste Takt fuehrt den Auftrag aus",
           job.event.is_set() and (job.response or {}).get("ok") is True,
           repr(job.response)[:120])
    pruefe("K2 Status wieder leer, die Zurueckhaltung ist gezaehlt",
           s["cadwork_beschaeftigt"] == "" and s["zurueckgehalten_s"] is None
           and s["zurueckhaltungen"] == 1
           and "arbeitet gerade selbst" not in s["hinweis"],
           "%r / %r" % (s["cadwork_beschaeftigt"], s["zurueckhaltungen"]))

    # KONTROLLE: dieselbe anschlagende Sonde, Zurueckhalten aus -> der
    # Auftrag laeuft. Sonst hielte oben etwas anderes als die Sonde an.
    d2 = _k_dienst(kern)
    d2.cfg.zurueckhalten = False
    job2 = _k_job(kern)
    d2.job_queue.put(job2)
    kern._takt(d2, [lambda: "modaler Dialog offen: X"])
    pruefe("K1 KONTROLLE: ohne Zurueckhalten laeuft derselbe Auftrag trotz "
           "Sonde", job2.event.is_set())

    # Die Leerlaufarbeit fasst cwapi3d ebenso an (Dokumentname alle 5 s).
    d3 = _k_dienst(kern)
    d3.letzte_dok_pruefung = 0.0
    n = len(aufrufe)
    kern._takt(d3, [lambda: "Menue oder Popup offen: QMenu"])
    ruhte = len(aufrufe) == n
    d3.letzte_dok_pruefung = 0.0
    kern._takt(d3, [])
    pruefe("K1 auch die Leerlaufarbeit (Dokumentname) ruht", ruhte)
    pruefe("K1 KONTROLLE: frei ruft dieselbe Leerlaufarbeit cwapi3d",
           len(aufrufe) > n, "sonst misst 'ruht' nichts")

    def kaputt():
        raise RuntimeError("Sonde kaputt")
    d4 = _k_dienst(kern)
    job4 = _k_job(kern)
    d4.job_queue.put(job4)
    kern._takt(d4, [kaputt])
    pruefe("K1 eine Sonde, die selbst scheitert, haelt nichts an",
           job4.event.is_set())


def _k_wiedereintritt(kern):
    """Ein Auftrag verteilt Ereignisse -> der Takt feuert IM Auftrag.

    Nachgestellt ueber die Attrappe: der Auftrag ruft `uc.omcad_test_takt`,
    und die ruft den Takt noch einmal — so, wie Cadwork den QTimer aus
    einer Rueckfrage oder einem processEvents heraus bedient.
    """
    uc = sys.modules["utility_controller"]
    d = _k_dienst(kern, "W")
    code = {"code": "result = uc.omcad_test_takt()", "access_mode": "read"}
    a, b = _k_job(kern, "execute_cwapi3d", code), _k_job(kern)
    d.job_queue.put(a)
    d.job_queue.put(b)
    innen = {}

    def takt_im_auftrag():
        kern._takt(d, [])
        innen["b_lief"] = b.event.is_set()
        innen["grund"] = d.status()["cadwork_beschaeftigt"]
        return "innen"

    uc.omcad_test_takt = takt_im_auftrag
    try:
        kern._takt(d, [])
        pruefe("K3 Wiedereintritt: der innere Takt fuehrt den naechsten "
               "Auftrag NICHT aus", innen.get("b_lief") is False, repr(innen))
        pruefe("K3 und nennt den Grund",
               "Wiedereintritt" in innen.get("grund", ""), repr(innen))
        pruefe("K3 der aeussere Auftrag lief dabei sauber durch",
               ((a.response or {}).get("result") or {}).get("result")
               == "innen", repr(a.response)[:160])
        kern._takt(d, [])
        pruefe("K3 der naechste Takt holt den wartenden Auftrag nach",
               b.event.is_set())

        # KONTROLLE: der alte Weg — der QTimer rief `_tick` direkt. Dann
        # laeuft der zweite Auftrag MITTEN im ersten.
        d2 = _k_dienst(kern, "V")
        a2, b2 = _k_job(kern, "execute_cwapi3d", code), _k_job(kern)
        d2.job_queue.put(a2)
        d2.job_queue.put(b2)
        uc.omcad_test_takt = lambda: (kern._tick(d2, 0), b2.event.is_set())[1]
        kern._tick(d2, 0)
        pruefe("K3 KONTROLLE: ohne Takt-Sperre (alter Weg) laeuft der zweite "
               "Auftrag im ersten",
               ((a2.response or {}).get("result") or {}).get("result") is True,
               repr(a2.response)[:160])
    finally:
        del uc.omcad_test_takt


def _k_fenster_sonde(kern):
    """Die Sonde 'fenster' an einem ECHTEN Win32-Fenster (unsichtbar)."""
    if sys.platform != "win32":
        pruefe("K4 Fenster-Sonde gibt es nur unter Windows",
               kern._fenster_sonde(123) is None)
        return
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    erzeugen = ctypes.WINFUNCTYPE(
        wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
        wintypes.LPVOID)(("CreateWindowExW", u32))
    sperren = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                 wintypes.BOOL)(("EnableWindow", u32))
    zerstoeren = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(
        ("DestroyWindow", u32))
    WS_CHILD = 0x40000000
    haupt = erzeugen(0, "STATIC", "omcad_k4", 0, 0, 0, 10, 10,
                     None, None, None, None)
    kind = erzeugen(0, "STATIC", "omcad_k4_3d", WS_CHILD, 0, 0, 5, 5,
                    haupt, None, None, None)
    try:
        sonde = kern._fenster_sonde(haupt)
        frei = sonde()
        sperren(haupt, False)
        gesperrt = sonde()
        sperren(haupt, True)
        wieder = sonde()
        pruefe("K4 Fenster-Sonde: freies Hauptfenster -> nichts", frei == "",
               repr(frei))
        pruefe("K4 gesperrtes Hauptfenster (modaler Dialog) -> Grund",
               "gesperrt" in gesperrt, repr(gesperrt))
        pruefe("K4 KONTROLLE: wieder freigegeben -> nichts", wieder == "",
               repr(wieder))
        pruefe("K4 ohne Handle gibt es keine Fenster-Sonde",
               kern._fenster_sonde(0) is None)

        uc = sys.modules["utility_controller"]
        uc.get_3d_hwnd = lambda: kind
        try:
            wurzel = kern._cadwork_wurzelfenster()
        finally:
            del uc.get_3d_hwnd
        pruefe("K4 vom 3D-Fenster wird auf das Hauptfenster gehoben",
               wurzel == haupt, "%r statt %r" % (wurzel, haupt))
        pruefe("K4 KONTROLLE: 3D-Fenster und Hauptfenster sind verschieden",
               kind and kind != haupt, "sonst misst die Zelle davor nichts")
        pruefe("K4 ohne get_3d_hwnd: kein Handle, kein Absturz",
               kern._cadwork_wurzelfenster() == 0)
    finally:
        zerstoeren(kind)
        zerstoeren(haupt)
    pruefe("K4 ein zerstoertes Fenster meldet nichts (kein Dauer-Halt)",
           sonde() == "")


def _k_nimmt_an(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _k_bindbar(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _k_zweiter_klick(kern_x, port, **cfg_kw):
    """Ein zweiter Plugin-Klick: FRISCHER Kern, reservierter Socket.

    -> (Rueckgabe von serve, neuer Dienst, Thread). Der Start laeuft in
    einem Thread: gelingt er, haelt ihn der klassische Antrieb fest.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    s.bind(("127.0.0.1", port))
    cfg = kern_x.Konfiguration(log_datei=os.path.join(
        tempfile.gettempdir(), "omcad_test_offline.log"))
    cfg.antrieb = "mainthread"
    for k, v in cfg_kw.items():
        setattr(cfg, k, v)
    neu = kern_x.Verbindungsdienst(cfg)
    erg = {}
    t = threading.Thread(target=lambda: erg.__setitem__(
        "d", kern_x.serve(cfg, dienst=neu, reserved_socket=s)), daemon=True)
    t.start()
    t.join(1.0)
    return erg.get("d"), neu, t


def _k_ein_dienst(kern):
    """Befund 2: zwei Klicks im selben Prozess -> nie zwei Listener.

    Der zweite Klick kommt mit einem FRISCH geladenen Kern — genau so laedt
    der Einstieg ihn in Cadwork. Dessen `_QT_LAEUFT` ist leer; nur das
    Prozessbuch kennt den ersten Dienst.
    """
    port2 = TESTPORT + 8
    with Pruefstand(kern, port=TESTPORT + 7, instanz="K") as p:
        kern2 = kern_laden()
        pruefe("K5 der frische Kern sieht den laufenden Dienst NICHT im "
               "Modul-Global", kern2._QT_LAEUFT == [] and kern2 is not kern,
               "sonst misst K5 nicht das Prozessbuch")
        pruefe("K5 aber im Prozessbuch",
               kern2.dienst_im_prozess() is p.dienst)
        zurueck, neu, t = _k_zweiter_klick(kern2, port2)
        pruefe("K5 zweiter Klick: serve liefert den laufenden Dienst zurueck",
               zurueck is p.dienst and not t.is_alive(),
               "Rueckgabe %r" % (zurueck,))
        pruefe("K5 kein zweiter Listener, der reservierte Port ist wieder frei",
               not _k_nimmt_an(port2) and _k_bindbar(port2))
        pruefe("K5 der abgewiesene Dienst hat nie gelebt",
               neu.zustand == "stopped" and neu.start_mono is None,
               neu.zustand)

        # KONTROLLE: derselbe Klick mit `mehrere_im_prozess` startet
        # wirklich einen zweiten Listener — ohne das Buch passierte genau
        # das (Logs C und D, 2026-09-25).
        _z, neu2, t2 = _k_zweiter_klick(kern2, port2, mehrere_im_prozess=True)
        try:
            pruefe("K5 KONTROLLE: ohne die Regel laeuft ein ZWEITER Listener",
                   warte_bis(lambda: _k_nimmt_an(port2), 3)
                   and neu2.zustand == "ready", neu2.zustand)
        finally:
            neu2.beenden = True
            t2.join(timeout=5)
    pruefe("K6 nach dem Beenden ist der Prozess wieder frei",
           kern2.dienst_im_prozess() is None
           and kern.dienst_im_prozess() is None)
    with Pruefstand(kern2, port=TESTPORT + 7, instanz="K") as p2:
        pruefe("K6 und ein neuer Klick verbindet", p2.dienst.zustand == "ready"
               and kern.dienst_im_prozess() is p2.dienst)

    # Ein Start, der am belegten Port scheitert, darf das Buch nicht sperren.
    halter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        halter.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    halter.bind(("127.0.0.1", port2))
    alt = (kern2.BIND_RETRY_ATTEMPTS, kern2.BIND_RETRY_PAUSE_SECONDS)
    kern2.BIND_RETRY_ATTEMPTS, kern2.BIND_RETRY_PAUSE_SECONDS = 1, 0.0
    try:
        cfg = kern2.Konfiguration(instanz="M", port=port2,
                                  log_datei=os.path.join(
                                      tempfile.gettempdir(),
                                      "omcad_test_offline.log"))
        cfg.antrieb = "mainthread"
        d = kern2.serve(cfg)
        pruefe("K7 Port belegt: der Start scheitert sauber",
               d.zustand == "stopped", d.zustand)
        pruefe("K7 und sperrt keinen spaeteren Klick",
               kern2.dienst_im_prozess() is None)
    finally:
        kern2.BIND_RETRY_ATTEMPTS, kern2.BIND_RETRY_PAUSE_SECONDS = alt
        halter.close()


def abschnitt_k(kern):
    """Befunde aus dem Viewer-Modus, 2026-09-25."""
    sag("\n--- K  Cadwork arbeitet selbst / ein Dienst je Prozess ---")
    uc = sys.modules["utility_controller"]
    aufrufe = []
    alt = uc.get_3d_file_name

    def gezaehlt():
        aufrufe.append(time.monotonic())
        return alt()

    uc.get_3d_file_name = gezaehlt
    try:
        _k_zurueckhalten(kern, aufrufe)
        _k_wiedereintritt(kern)
    finally:
        uc.get_3d_file_name = alt
    _k_fenster_sonde(kern)
    _k_ein_dienst(kern)


# ==========================================================================
# Abschnitt V — Paketlauf in 'Auto': paketweise statt Vorhang bis zum Ende
# ==========================================================================
#
# DER BEFUND (Film 2026-09-25, Log A 23:29-23:43): `execute_cadwork_batch`,
# 48 Pakete VBA je 15-20 s, Stufe 'Auto'. Die Schrauben erschienen waehrend
# jedes Pakets (Cadwork zeichnet sie im Paket schon), verschwanden an dessen
# Ende hinter dem Vorhang und kamen erst beim Nachziehen im Leerlauf wieder —
# das kam im ganzen Lauf zweimal. Hier laeuft der ECHTE Paketlauf des
# Servers (`open_mcp_cad.auftraege.paketlauf`) ueber TCP gegen den echten
# Kern; nach jedem Paket ein Schnappschuss dessen, was im Bild waere. Das
# Aufblitzen ist in der Attrappe genau das: ein Bauteil eines Pakets wird
# unsichtbar gemacht (Cadwork hat es waehrend des Pakets schon gezeigt).

V_CODE = ("import element_controller as ec\n"
          "result = [ec.create_rectangular_beam_vectors() for _e in paket]\n")
V_CODE_FEHLER = (V_CODE + "if paket_nr == 2:\n"
                 "    raise RuntimeError('Paket 2 bricht nach dem Anlegen ab')\n")


def _v_frisch(p):
    """Ruhe abwarten (Lauf zu Ende, Bild zurueck, auch das nachgeholte
    Neuzeichnen), Mitschriebe leeren."""
    d = p.dienst
    warte_bis(lambda: not d.bildschirm_aus and not d.lauf_balken
              and not d.lauf_start_mono and not d.dunkel_entstanden
              and not getattr(d, "refresh_nachholen", 0), 8)
    _FakeDoc.vorhang = []
    _FakeDoc.material_gesetzt = []
    _FakeDoc.material_hell = []
    _FakeDoc.material_dunkel = []
    _FakeDoc.balken = []
    _FakeDoc.refreshs = []
    _FakeDoc.dienst = d


def _v_lauf(p, tmp, name, daten=6, groesse=2, code=V_CODE, altes_feld=False,
            feld=None):
    """Ein ECHTER Paketlauf gegen den Pruefstand.

    altes_feld=True spielt den Server VOR Kern 2.18: das Feld `paketlauf`
    fehlt. `feld` ersetzt es (kaputte Werte).
    -> (Antwort des Laufs, Schnappschuss je Paket, gesendete params)
    """
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from open_mcp_cad import auftraege, bridge_client
    pfad = os.path.join(tmp, "%s.json" % name.replace(" ", "_"))
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump([{"i": i} for i in range(daten)], fh)
    schnapp, gesendet = [], []

    def rufen(methode, params, antwort_timeout=None):
        # "anon" wie p.ruf: sonst hielte der Lauf die Schreiblizenz, und die
        # naechsten Zellen bekaemen document_busy.
        params = dict(params, client_id="anon")
        if altes_feld:
            params.pop("paketlauf", None)
        elif feld is not None:
            params["paketlauf"] = feld
        gesendet.append(params)
        antwort = bridge_client.call(methode, params, port=p.cfg.port,
                                     antwort_timeout=antwort_timeout)
        schnapp.append({
            "ids": list((antwort or {}).get("result") or []),
            "unsichtbar": set(_FakeDoc.unsichtbar),
            "hell": list(_FakeDoc.material_hell),
            "auffrischung": _FakeDoc.auffrischung,
            "balken": list(_FakeDoc.balken),
            "antwort": antwort or {},
        })
        return antwort

    erg = auftraege.paketlauf(code, pfad, groesse, name, rufen=rufen)
    return erg, schnapp, gesendet


def _v_ids(schnapp, bis=None):
    return [i for s in schnapp[:bis] for i in s["ids"]]


def _v_versteckt():
    return {i for z, ids in _FakeDoc.vorhang if z == "zu" for i in ids}


def _v_neu_gezeichnet(sn):
    """Je Paket: wie oft vc.refresh() IN seinem Auftrag lief, nachdem alle
    bis dahin angelegten Bauteile hell nachgezogen waren.

    Ein Neuzeichnen im Leerlauf (`refresh_nachholen`, zwei Takte spaeter)
    zaehlt NICHT: das kommt auch ohne das Neuzeichnen je Paket, nur zu spaet
    und nicht vor der Antwort (Gegenpruefung 2026-09-26, Mutant K11).
    """
    n = len(sn)
    return [sum(1 for r in _FakeDoc.refreshs
                if r["im_auftrag"] and r["paket"] == (k, n)
                and set(_v_ids(sn, k)) <= r["hell"])
            for k in range(1, n + 1)]


def _v_auto(kern, p, tmp):
    """V1: der neue Weg — und V2, dieselbe Folge ohne das Feld (alt)."""
    gestellt = _stufe(p, "auto")
    # 2 Bauteile je Paket x 1000 ms: der Balken des Laufs kommt sofort.
    p.dienst.ms_je_teil = 1000.0
    _v_frisch(p)
    aus0 = _FakeDoc.refresh_aus
    # Ein Nachziehen, das 0,2 s dauert: "nach jedem Paket nachgezogen" soll
    # heissen VOR seiner Antwort — nicht, dass ein schneller Hauptthread den
    # Wettlauf mit dem Schnappschuss gewonnen hat.
    _FakeDoc.material_dauer_s = 0.2
    try:
        erg, sn, ges = _v_lauf(p, tmp, "V1 Auto")
    finally:
        _FakeDoc.material_dauer_s = 0.0
    alle = _v_ids(sn)
    pruefe("V1 Paketlauf in 'Auto': 3 Pakete, 6 neue Bauteile, alles ok",
           gestellt and erg.get("ok") and len(sn) == 3
           and len(set(alle)) == 6,
           json.dumps(erg)[:160])
    pruefe("V1 das Feld paketlauf geht an jedes Paket (k von n)",
           [g.get("paketlauf") for g in ges]
           == [{"paket": k, "pakete": 3} for k in (1, 2, 3)],
           [g.get("paketlauf") for g in ges])
    pruefe("V1 kein Bauteil eines Pakets wird je versteckt (kein Aufblitzen)",
           not _v_versteckt() & set(alle),
           "versteckt: %s" % sorted(_v_versteckt() & set(alle)))
    pruefe("V1 nach JEDEM Paket ist alles bisher Angelegte nachgezogen, und "
           "zwar bei eingeschalteter Auffrischung",
           all(set(_v_ids(sn, k + 1)) <= set(sn[k]["hell"])
               for k in range(len(sn))),
           [len(set(_v_ids(sn, k + 1)) - set(sn[k]["hell"]))
            for k in range(len(sn))])
    pruefe("V1 und sichtbar — Paket fuer Paket, fortschreitend",
           all(not set(_v_ids(sn, k + 1)) & sn[k]["unsichtbar"]
               for k in range(len(sn))))
    pruefe("V1 nach jedem Paket ist die Auffrischung wieder an (Cadwork "
           "zeichnet zwischen den Paketen)", all(s["auffrischung"] for s in sn),
           [s["auffrischung"] for s in sn])
    pruefe("V1 nach jedem Paket EINMAL neu gezeichnet (vc.refresh), noch in "
           "seinem Auftrag und erst nach seinem Material",
           _v_neu_gezeichnet(sn) == [1, 1, 1], _v_neu_gezeichnet(sn))
    pruefe("V1 jedes Bauteil genau EINMAL nachgezogen, keins im Dunkeln "
           "(dieselbe Arbeit wie vorher, nur verteilt)",
           sorted(_FakeDoc.material_hell) == sorted(alle)
           and not _FakeDoc.material_dunkel,
           "hell %d, dunkel %d" % (len(_FakeDoc.material_hell),
                                   len(_FakeDoc.material_dunkel)))
    pruefe("V1 Kosten: je Paket EIN Aus/An der Auffrischung (3 statt 1)",
           _FakeDoc.refresh_aus - aus0 == 3,
           "%d Aus" % (_FakeDoc.refresh_aus - aus0))
    teile = [s["antwort"].get("paket_nachgezogen") or {} for s in sn]
    pruefe("V1 jedes Paket meldet, was es nachgezogen hat und wie lange",
           [t.get("elemente") for t in teile] == [2, 2, 2]
           and all(isinstance(t.get("s"), float) for t in teile), teile)
    pruefe("V1 die Antwort des Laufs nennt die Summe (Kosten ablesbar)",
           (erg.get("nachgezogen") or {}).get("pakete") == 3
           and erg["nachgezogen"]["elemente"] == 6
           and erg["nachgezogen"]["s"] >= 0, erg.get("nachgezogen"))
    st = p.ruf("status")["result"]
    la = st.get("letzter_auftrag") or {}
    pruefe("V1 Status zaehlt mit, letzter Auftrag nennt Paket und 'paketweise'",
           st.get("pakete_nachgezogen", 0) >= 3
           and la.get("paket") == [3, 3] and la.get("paketweise") is True,
           "%s / %s" % (st.get("pakete_nachgezogen"), la))
    pruefe("V1 der Balken des Laufs steht ab Paket 1 und bleibt zwischen den "
           "Paketen stehen", "an" in sn[0]["balken"]
           and all("aus" not in s["balken"] for s in sn),
           [s["balken"] for s in sn])
    zahlen = [x for x in sn[-1]["balken"] if isinstance(x, int)]
    pruefe("V1 und laeuft nur vorwaerts (kein Sprung auf 100 und zurueck je "
           "Paket)", zahlen and zahlen == sorted(zahlen) and max(zahlen) < 100,
           zahlen)
    pruefe("V1 nach dem Lauf ist er weg und der Lauf abgeschlossen",
           warte_bis(lambda: _FakeDoc.balken[-1:] == ["aus"]
                     and not p.dienst.lauf_start_mono, 6),
           "%s / %s" % (_FakeDoc.balken[-3:], p.dienst.lauf_start_mono))
    # KONTROLLE zur Zelle "nur vorwaerts": gehoert der Balken dem
    # Nachziehen selbst (kein Lauf-Balken), fuehrt es ihn bis 100 — die
    # Zelle oben misst also, WEM die Anzeige gehoert, nicht ob es welche gibt.
    d = _k_dienst(kern, "V")
    d.dunkel_entstanden = [_FakeDoc.elemente[0]]
    vorher = len(_FakeDoc.balken)
    kern._dunkle_elemente_nachziehen(d)
    eigen = _FakeDoc.balken[vorher:]
    pruefe("V1 KONTROLLE: ohne Lauf-Balken zeigt das Nachziehen seinen "
           "eigenen, bis 100", eigen[:1] == ["an"] and 100 in eigen
           and eigen[-1:] == ["aus"], eigen)
    d.beenden = True

    # KONTROLLE: dieselbe Folge wie ein Server vor 2.18 sie schickt (ohne
    # das Feld). Genau das zeigte der Film: jedes Paket hinter den Vorhang,
    # nachgezogen erst im Leerlauf. Wird das hier nicht rot, misst V1 nichts.
    _v_frisch(p)
    aus0 = _FakeDoc.refresh_aus
    erg2, sn2, ges2 = _v_lauf(p, tmp, "V2 ohne Feld", altes_feld=True)
    alle2 = _v_ids(sn2)
    if not sn2:                       # Lauf brach vor Paket 1 ab
        sn2 = [{"ids": [], "hell": [], "auffrischung": None}]
    pruefe("V2 KONTROLLE: ohne das Feld wird JEDES Paket versteckt — das "
           "Aufblitzen aus dem Film",
           erg2.get("ok") and set(alle2) <= _v_versteckt()
           and [z for z, _i in _FakeDoc.vorhang].count("zu") == 3
           and all("paketlauf" not in g for g in ges2),
           "%s" % [z for z, _i in _FakeDoc.vorhang])
    pruefe("V2 KONTROLLE: nach Paket 1 ist nichts nachgezogen, die "
           "Auffrischung aus",
           not set(sn2[0]["ids"]) & set(sn2[0]["hell"])
           and sn2[0]["auffrischung"] is False,
           "%s / %s" % (sn2[0]["hell"], sn2[0]["auffrischung"]))
    pruefe("V2 KONTROLLE: EIN Aus der Auffrischung fuer den ganzen Lauf",
           _FakeDoc.refresh_aus - aus0 == 1,
           "%d Aus" % (_FakeDoc.refresh_aus - aus0))
    pruefe("V2 bisheriger Weg bleibt: erst im Leerlauf nachgezogen und "
           "aufgedeckt, keine Summe in der Antwort",
           warte_bis(lambda: set(alle2) <= set(_FakeDoc.material_hell)
                     and not set(alle2) & _FakeDoc.unsichtbar, 6)
           and "nachgezogen" not in erg2, json.dumps(erg2)[:120])
    # KONTROLLE zur Zaehlung in V1: neu gezeichnet wird hier sehr wohl —
    # aber nur im Leerlauf. Zaehlte V1 das mit, saehe ein Kern ohne das
    # Neuzeichnen je Paket gleich aus.
    pruefe("V2 KONTROLLE: ohne das Feld wird nur im LEERLAUF neu gezeichnet, "
           "in keinem Paket — V1 zaehlt also nur das Neuzeichnen im Auftrag",
           warte_bis(lambda: any(not r["im_auftrag"]
                                 for r in _FakeDoc.refreshs), 6)
           and not any(r["im_auftrag"] for r in _FakeDoc.refreshs),
           "im Auftrag %d, im Leerlauf %d" % (
               sum(1 for r in _FakeDoc.refreshs if r["im_auftrag"]),
               sum(1 for r in _FakeDoc.refreshs if not r["im_auftrag"])))

    # V3 — ein EINZELAUFTRAG in 'Auto' behaelt den Vorhang (Auftrag: das
    # heutige Verhalten bleibt ausserhalb eines Paketlaufs).
    _v_frisch(p)
    a = p.ruf("execute_cwapi3d", {"code": V_CODE.replace("paket", "[0, 1]"),
                                  "description": "V3 Einzelauftrag"})
    einzel = (a.get("result") or {}).get("result") or []
    pruefe("V3 Einzelauftrag in 'Auto': Vorhang wie bisher, nichts sofort "
           "nachgezogen",
           a.get("ok") and len(einzel) == 2 and set(einzel) <= _v_versteckt()
           and not set(einzel) & set(_FakeDoc.material_hell)
           and "paket_nachgezogen" not in (a.get("result") or {}),
           json.dumps(a.get("result"))[:120])
    pruefe("V3 und im Leerlauf aufgedeckt",
           warte_bis(lambda: not set(einzel) & _FakeDoc.unsichtbar
                     and set(einzel) <= set(_FakeDoc.material_hell), 6))


def _v_stufen(kern, p, tmp):
    """V4: jede Stufe AUS DER QUELLE — versteckt wird genau dort, wo die
    Stufe schnell zeichnet, einen Vorhang hat und NICHT paketweise ist."""
    pruefe("V4 die Vorgabe-Stufe ist paketweise (dort lag der Befund)",
           next(m for m in kern.ZEICHENMODI
                if m["schluessel"] == kern.MODUS_VORGABE)["paketweise"])
    pruefe("V4 eine Stufe mit Balken und ohne Zwischenbilder ('Schnell') ist "
           "es nicht (Rueckmeldung 2026-08-06)",
           all(not m["paketweise"] for m in kern.ZEICHENMODI if m["balken"]),
           [(m["schluessel"], m["paketweise"]) for m in kern.ZEICHENMODI])
    for m in kern.ZEICHENMODI:
        gestellt = _stufe(p, m["schluessel"])
        p.dienst.ms_je_teil = 35.0
        _v_frisch(p)
        erg, sn, _g = _v_lauf(p, tmp, "V4 %s" % m["schluessel"], daten=4)
        alle = _v_ids(sn)
        versteckt_soll = m["schnell"] and m["vorhang"] and not m["paketweise"]
        sofort_soll = m["schnell"] and m["paketweise"]
        versteckt = bool(set(alle) & _v_versteckt())
        sofort = set(_v_ids(sn, 1)) <= set(sn[0]["hell"])
        pruefe("V4 '%s': versteckt=%s, Paket 1 sofort nachgezogen=%s"
               % (m["schluessel"], versteckt_soll, sofort_soll),
               gestellt and erg.get("ok") and len(alle) == 4
               and versteckt == versteckt_soll
               and sofort == sofort_soll
               and ("nachgezogen" in erg) == sofort_soll,
               "versteckt=%s sofort=%s %s" % (versteckt, sofort,
                                              erg.get("nachgezogen")))
    _stufe(p, "auto")
    _v_frisch(p)


def _v_feld(kern, p, tmp):
    """V5: nur ein GENAU passendes Feld macht einen Auftrag zum Paket."""
    gut = kern.paket_von({"paketlauf": {"paket": 2, "pakete": 3}})
    schlecht = {
        "fehlt": {}, "Text": {"paketlauf": "ja"},
        "Liste": {"paketlauf": [1, 3]},
        "k=0": {"paketlauf": {"paket": 0, "pakete": 3}},
        "k>n": {"paketlauf": {"paket": 4, "pakete": 3}},
        "Text-Zahl": {"paketlauf": {"paket": "1", "pakete": "3"}},
        "bool": {"paketlauf": {"paket": True, "pakete": True}},
        "kein dict": None,
    }
    falsch = {t: kern.paket_von(p_) for t, p_ in schlecht.items()
              if kern.paket_von(p_) is not None}
    pruefe("V5 paket_von: {paket: 2, pakete: 3} -> (2, 3)", gut == (2, 3),
           repr(gut))
    pruefe("V5 alles andere ist ein Einzelauftrag (sichere Richtung)",
           not falsch, repr(falsch))
    # Und im Betrieb: ein kaputtes Feld -> Vorhang wie ein Einzelauftrag.
    _v_frisch(p)
    erg, sn, _g = _v_lauf(p, tmp, "V5 kaputt", daten=2,
                          feld={"paket": 4, "pakete": 3})
    alle = _v_ids(sn)
    pruefe("V5 ein kaputtes Feld im Lauf: Vorhang wie bisher",
           erg.get("ok") and set(alle) <= _v_versteckt()
           and "nachgezogen" not in erg, json.dumps(erg)[:120])
    _v_frisch(p)


def _v_fehler(p, tmp):
    """V6: ein Paket bricht NACH dem Anlegen ab — sein Teil bleibt nicht
    unfertig im Bild, und der Bildschirm ist danach wieder an."""
    _v_frisch(p)
    vorher = set(_FakeDoc.elemente)
    erg, sn, _g = _v_lauf(p, tmp, "V6 Fehler", code=V_CODE_FEHLER)
    neu = sorted(set(_FakeDoc.elemente) - vorher)
    paket2 = sorted(set(neu) - set(_v_ids(sn)))
    pruefe("V6 Paket 2 bricht ab: Lauf hoert auf, Paket 1 fertig",
           not erg.get("ok") and erg.get("abgebrochen_bei_paket") == 2
           and erg.get("pakete_fertig") == 1 and len(paket2) == 2,
           json.dumps({k: erg.get(k) for k in ("error", "pakete_fertig",
                                               "abgebrochen_bei_paket")}))
    pruefe("V6 was Paket 2 vor dem Fehler anlegte, ist nachgezogen und "
           "sichtbar, die Auffrischung wieder an",
           set(paket2) <= set(_FakeDoc.material_hell)
           and not set(neu) & _FakeDoc.unsichtbar and _FakeDoc.auffrischung
           and not p.dienst.bildschirm_aus,
           "Paket 2 %s, hell %s" % (paket2, _FakeDoc.material_hell))
    la = p.ruf("status")["result"].get("letzter_auftrag") or {}
    pruefe("V6 der Fehler steht am Auftrag, paketweise lief er trotzdem",
           la.get("ok") is False and la.get("paketweise") is True
           and la.get("paket") == [2, 3], json.dumps(la)[:140])
    pruefe("V6 die Fehlerantwort nennt, was bis dahin nachgezogen wurde",
           (erg.get("nachgezogen") or {}).get("pakete") == 1,
           erg.get("nachgezogen"))
    _v_frisch(p)


def _v_ende(kern, p, tmp):
    """V7: ein paketweiser Lauf OHNE Balken wird im Leerlauf abgeschlossen.

    Sein letztes Paket hat die Auffrischung schon selbst eingeschaltet — der
    Leerlauf-Zweig, der sonst den Lauf beendet (`_bildschirm_an`), kommt
    nicht mehr. Bliebe `lauf_start_mono` stehen, galte der naechste
    Einzelauftrag als Fortsetzung eines langen Laufs.
    """
    gestellt = _stufe(p, "auto")
    p.dienst.ms_je_teil = 1.0          # kein Balken: kleiner, schneller Lauf
    _v_frisch(p)
    erg, sn, _g = _v_lauf(p, tmp, "V7 klein", daten=2, groesse=1)
    pruefe("V7 kleiner paketweiser Lauf ohne Balken",
           gestellt and erg.get("ok") and "an" not in _FakeDoc.balken
           and not p.dienst.lauf_balken, "%s" % _FakeDoc.balken)
    pruefe("V7 im Leerlauf ist der Lauf abgeschlossen (lauf_start_mono 0)",
           warte_bis(lambda: not p.dienst.lauf_start_mono
                     and not p.dienst.lauf_auftraege, 6),
           "%s / %s" % (p.dienst.lauf_start_mono, p.dienst.lauf_auftraege))
    _FakeDoc.balken = []
    p.ruf("execute_cwapi3d", {"code": "result = 1", "bauteile": 1,
                              "description": "V7 Einzelauftrag danach"})
    pruefe("V7 ein Einzelauftrag danach laesst keinen Balken aufblitzen",
           "an" not in _FakeDoc.balken, "%s" % _FakeDoc.balken)
    # KONTROLLE (ohne Netz, direkt): steht `lauf_start_mono` von vor 10 s
    # noch, blitzt der Balken fuer genau so einen Einzelauftrag auf. Sonst
    # misst die Zelle davor nichts.
    d = _k_dienst(kern, "V")
    d.ms_je_teil = 1.0
    d.schnellzeichnen = False          # hier zaehlt nur der Balken
    d.lauf_start_mono = time.monotonic() - 10.0
    job = _k_job(kern, "execute_cwapi3d",
                 {"code": "result = 1", "bauteile": 1})
    kern._auftrag_ausfuehren(d, job)
    pruefe("V7 KONTROLLE: stehengebliebener Laufbeginn -> Balken blitzt auf",
           d.lauf_balken is True and (job.response or {}).get("ok"),
           repr(job.response)[:100])
    kern._lauf_balken_weg(d)
    d.beenden = True
    _v_frisch(p)


def _v_ruhe(kern):
    """V9: nach einem LANGEN Nachziehen schliesst der naechste Leerlauf-Takt
    den Lauf NICHT — zwischen zwei Paketen ist keine Ruhe.

    Die Ruhe (`SCHNELL_RUHE_S`) zaehlt ab dem Ende des Nachziehens, nicht ab
    dem Ende des Auftragscodes. Sonst schliesst ein Nachziehen, das laenger
    dauert als die Ruhe, Balken und Lauf, bevor das naechste Paket kommt —
    und das Fenster geht je Paket auf und zu (Gegenpruefung 2026-09-26,
    Mutant K13). Deterministisch: kein Netz, Auftrag und Takt direkt
    gerufen; die Ruhe auf 0,5 s verkuerzt, das Nachziehen dauert 0,6 s.
    """
    alt_ruhe = kern.SCHNELL_RUHE_S
    kern.SCHNELL_RUHE_S = 0.5
    _FakeDoc.material_dauer_s = 0.6
    d = _k_dienst(kern, "V")
    _FakeDoc.dienst = d
    try:
        d.ms_je_teil = 1000.0          # Balken des Laufs ab Paket 1
        job = _k_job(kern, "execute_cwapi3d", {
            "code": V_CODE.replace("paket", "[0, 1]"), "bauteile": 2,
            "lauf_gesamt": 6, "paketlauf": {"paket": 1, "pakete": 3},
            "description": "V9 langes Nachziehen"})
        kern._auftrag_ausfuehren(d, job)
        info = (((job.response or {}).get("result") or {})
                .get("paket_nachgezogen") or {})
        pruefe("V9 Paket 1/3 lief paketweise, sein Nachziehen dauerte "
               "laenger als die Ruhe (%.1f s), der Lauf-Balken steht"
               % kern.SCHNELL_RUHE_S,
               job.meta.paketweise and d.lauf_balken
               and (info.get("s") or 0) > kern.SCHNELL_RUHE_S,
               "%s / Balken %s" % (info, d.lauf_balken))
        kern._tick(d, 0)
        pruefe("V9 der naechste Leerlauf-Takt laesst Balken und Lauf stehen "
               "(die Ruhe zaehlt ab dem Ende des Nachziehens)",
               d.lauf_balken and d.lauf_start_mono,
               "Balken %s, Laufbeginn %s" % (d.lauf_balken,
                                             d.lauf_start_mono))
        # KONTROLLE: liegt der letzte Auftrag wirklich laenger als die Ruhe
        # zurueck, schliesst DERSELBE Takt den Lauf. Sonst misst die Zelle
        # davor einen Takt, der nie schliesst, und nicht die Uhr.
        d.letzter_auftrag_mono -= kern.SCHNELL_RUHE_S + 0.1
        kern._tick(d, 0)
        pruefe("V9 KONTROLLE: nach echter Ruhe schliesst derselbe Takt Balken "
               "und Lauf", not d.lauf_balken and not d.lauf_start_mono,
               "Balken %s, Laufbeginn %s" % (d.lauf_balken,
                                             d.lauf_start_mono))
    finally:
        kern.SCHNELL_RUHE_S = alt_ruhe
        _FakeDoc.material_dauer_s = 0.0
        d.beenden = True


def _v_ohne_dunkel(kern):
    """V10: laesst sich die Auffrischung nicht abschalten (`_bildschirm_aus`
    scheitert), zeichnet ein Paket hell — dann gibt es nichts paketweise
    nachzuziehen, und die Auffrischung wird auch nicht "wieder" eingeschaltet.

    Genau dafuer steht `meta.schnell` in der Bedingung fuer `paketweise`
    (Gegenpruefung 2026-09-26, Mutant K2: ohne sie wuerde nachgezogen und
    ein Nachziehen gemeldet, das nie noetig war).
    """
    gemessen = {}
    for kaputt in (True, False):
        _FakeDoc.aus_kaputt = kaputt
        d = _k_dienst(kern, "V")
        _FakeDoc.dienst = d
        an0 = _FakeDoc.refresh_an
        try:
            job = _k_job(kern, "execute_cwapi3d", {
                "code": V_CODE.replace("paket", "[0, 1]"), "bauteile": 2,
                "paketlauf": {"paket": 1, "pakete": 3},
                "description": "V10 Auffrischung %s" % (
                    "nicht abschaltbar" if kaputt else "abschaltbar")})
            kern._auftrag_ausfuehren(d, job)
        finally:
            _FakeDoc.aus_kaputt = False
            d.beenden = True
        antwort = job.response or {}
        gemessen[kaputt] = {
            "ok": antwort.get("ok"), "schnell": job.meta.schnell,
            "paketweise": job.meta.paketweise,
            "gemeldet": "paket_nachgezogen" in (antwort.get("result") or {}),
            "pakete_nachgezogen": d.pakete_nachgezogen,
            "eingeschaltet": _FakeDoc.refresh_an - an0}
    k = gemessen[True]
    pruefe("V10 Auffrischung laesst sich nicht abschalten: das Paket laeuft "
           "hell und ok, NICHT paketweise — nichts nachgezogen, nichts "
           "eingeschaltet, nichts gemeldet",
           k["ok"] and not k["schnell"] and not k["paketweise"]
           and not k["gemeldet"] and k["pakete_nachgezogen"] == 0
           and k["eingeschaltet"] == 0, k)
    g = gemessen[False]
    pruefe("V10 KONTROLLE: dasselbe Paket mit abschaltbarer Auffrischung "
           "laeuft paketweise (nachgezogen, gemeldet, einmal eingeschaltet)",
           g["ok"] and g["schnell"] and g["paketweise"] and g["gemeldet"]
           and g["pakete_nachgezogen"] == 1 and g["eingeschaltet"] == 1, g)


def _v11_lauf(kern, haken, stufe="auto"):
    """Ein Lauf ohne Netz (wie V9): drei schreibende Pakete, dann ein
    Leseauftrag mitten im Lauf, dann der Leerlauf nach der Ruhe.
    `haken` -> cfg.lauf_anzeige. -> (Dienst, Balken-Mitschrieb, Popups)"""
    alt_ruhe = kern.SCHNELL_RUHE_S
    kern.SCHNELL_RUHE_S = 0.3
    d = _k_dienst(kern, "V")
    d.cfg.lauf_anzeige = haken
    with d.sperre:
        d.zeichenmodus = stufe
    _FakeDoc.dienst = d
    _FakeDoc.balken = []
    popups = []
    alt_popup = kern._popup_setzen
    kern._popup_setzen = lambda *a: (popups.append(a[1:]), False)[1]
    try:
        d.ms_je_teil = 1000.0          # Balken des Laufs ab Paket 1
        for k in (1, 2, 3):
            job = _k_job(kern, "execute_cwapi3d", {
                "code": V_CODE.replace("paket", "[0, 1]"), "bauteile": 2,
                "lauf_gesamt": 6, "paketlauf": {"paket": k, "pakete": 3},
                "description": "V11 Paket %d" % k})
            kern._auftrag_ausfuehren(d, job)
        lesen = _k_job(kern, "execute_cwapi3d", {
            "code": "result = 1", "access_mode": "read",
            "description": "V11 lesen"})
        kern._auftrag_ausfuehren(d, lesen)
        d.letzter_auftrag_mono -= kern.SCHNELL_RUHE_S + 0.1
        for _ in range(3):
            kern._tick(d, 0)
    finally:
        kern.SCHNELL_RUHE_S = alt_ruhe
        kern._popup_setzen = alt_popup
        d.beenden = True
    return d, list(_FakeDoc.balken), popups


V11_START = ('        _lauf_balken_zeigen(d, "start", meta, neu_lauf)\n'
             '    elif d.lauf_balken:')
V11_NACH = ("    if meta.paketweise:\n"
            "        # Auch nach einem Fehler")


def _v_haken(kern):
    """V11 (K12, Kern 2.19): der Haken `cfg.lauf_anzeige` der Arbeitsanzeige
    des Dashboards. VOR jedem Auftrag eines Laufs `start` (mit `zugriff`,
    auch lesend), danach `fortschritt`, am Ende `ende`; ohne Haken wie 2.18
    (V1-V10 laufen ohne); wirft er, Log + eigenes Fenster, der Auftrag
    laeuft. Gemessen wird, WANN gerufen wird: die Zahl neuer Elemente im
    Modell im Moment des Aufrufs (vor Paket k: 2k-2)."""
    pruefe("V11 der Kern meldet, dass er den Haken kennt",
           getattr(kern, "LAUF_ANZEIGE_HAKEN", False) is True,
           kern.CORE_VERSION)
    rufe = []
    basis = []

    def haken(art, info):
        rufe.append((art, dict(info), len(_FakeDoc.elemente) - basis[0]))

    basis.append(len(_FakeDoc.elemente))
    d, balken, popups = _v11_lauf(kern, haken)
    arten = [r[0] for r in rufe]
    pruefe("V11 Folge: je Auftrag start/fortschritt, am Ende einmal ende",
           arten == ["start", "fortschritt"] * 4 + ["ende"], arten)
    starts = [r for r in rufe if r[0] == "start"]
    pruefe("V11 `start` VOR dem Auftrag: vor Paket k standen erst 2k-2 neue "
           "Bauteile im Modell",
           [r[2] for r in starts[:3]] == [0, 2, 4],
           [r[2] for r in starts])
    pruefe("V11 `start` nennt zugriff, Beschreibung, Paket und das Ziel",
           [(r[1].get("zugriff"), r[1].get("beschreibung"),
             r[1].get("paket"), r[1].get("lauf_gesamt")) for r in starts]
           == [("write", "V11 Paket 1", [1, 3], 6),
               ("write", "V11 Paket 2", [2, 3], 6),
               ("write", "V11 Paket 3", [3, 3], 6),
               ("read", "V11 lesen", None, 6)],
           [(r[1].get("zugriff"), r[1].get("paket")) for r in starts])
    fort = [r for r in rufe if r[0] == "fortschritt"]
    pruefe("V11 `fortschritt` danach zaehlt mit (2, 4, 6 Bauteile, Prozent "
           "steigt)", len(fort) >= 3
           and [r[1].get("lauf_gezeichnet") for r in fort[:3]] == [2, 4, 6]
           and fort[0][1].get("prozent") < fort[2][1].get("prozent"),
           [(r[1].get("lauf_gezeichnet"), r[1].get("prozent")) for r in fort])
    pruefe("V11 `ende` am Schluss, die Info sagt 'popup' fuer die Stufe Auto "
           "und ob ein Lauf neu beginnt",
           bool(rufe) and rufe[-1][0] == "ende"
           and rufe[-1][1].get("popup") is True
           and len(starts) > 1 and starts[0][1].get("neu_lauf") is True
           and starts[1][1].get("neu_lauf") is False,
           rufe[-1][1] if rufe else None)
    pruefe("V11 mit Haken kein eigenes Fenster und kein Cadwork-Balken "
           "(die Anzeige gehoert dem Dashboard)",
           not popups and "an" not in balken, "%s / %s" % (popups, balken))

    # Stufe ohne Fenster: Haken trotzdem, Balken unten rechts wie bisher.
    rufe[:] = []
    basis[:] = [len(_FakeDoc.elemente)]
    d, balken, popups = _v11_lauf(kern, haken, stufe="langsam")
    pruefe("V11 in 'langsam': Haken gerufen (popup False), Cadworks Balken "
           "unten rechts wie bisher",
           bool(rufe) and all(r[1].get("popup") is False for r in rufe)
           and "an" in balken and not popups,
           "%d Rufe, Balken %s" % (len(rufe), balken[:3]))

    # Ohne Haken: wie 2.18 — das eigene Fenster bekommt den Lauf.
    d, balken, popups = _v11_lauf(kern, None)
    pruefe("V11 ohne Haken: das eigene Fenster wie bisher (_popup_setzen)",
           len(popups) >= 6, len(popups))

    # Werfender Haken: Log, eigenes Fenster, der Auftrag laeuft.
    gesehen = []
    alt_error = kern.LOG.error
    kern.LOG.error = lambda *a, **k: gesehen.append(a[0] % a[1:])

    def wirft(art, info):
        raise RuntimeError("Probe")

    basis[:] = [len(_FakeDoc.elemente)]
    try:
        d, balken, popups = _v11_lauf(kern, wirft)
    finally:
        kern.LOG.error = alt_error
    pruefe("V11 wirft der Haken: Zeile im Log, eigenes Fenster, die Auftraege "
           "laufen (6 neue Bauteile)",
           any("Arbeitsanzeige" in g for g in gesehen) and bool(popups)
           and len(_FakeDoc.elemente) - basis[0] == 6
           and (d.letzter_auftrag or {}).get("ok"),
           "%s / %d Popups" % (gesehen[:1], len(popups)))
    pruefe("V11 und am Ende des Laufs gilt der Haken wieder",
           d.lauf_haken_kaputt is False)

    # KONTROLLE: ein Kern, der den Haken erst NACH dem Auftrag ruft
    # (Mutant) — dann steht "KI zeichnet" waehrend des Auftrags nicht.
    with io.open(KERN_PFAD, encoding="utf-8") as fh:
        quelle = fh.read()
    with tempfile.TemporaryDirectory(prefix="omcad_v11_") as tmp:
        pfad = os.path.join(tmp, "omcad_bridge_core.py")
        mut = quelle.replace(V11_START, "        pass\n    elif d.lauf_balken:")
        mut = mut.replace(V11_NACH, "    if zeigen:\n        _lauf_balken_zeigen("
                          "d, 'start', meta, neu_lauf)\n" + V11_NACH)
        with io.open(pfad, "w", encoding="utf-8") as fh:
            fh.write(mut)
        km = kern_laden(pfad, name="omcad_bridge_core_v11")
        rufe[:] = []
        basis[:] = [len(_FakeDoc.elemente)]
        _v11_lauf(km, haken)
        starts = [r for r in rufe if r[0] == "start"]
    pruefe("V11 KONTROLLE: ruft ein Kern den Haken erst nach dem Auftrag, "
           "stuenden schon die neuen Bauteile (Zelle oben rot)",
           quelle.count(V11_START) == 1 and quelle.count(V11_NACH) == 1
           and [r[2] for r in starts[:3]] != [0, 2, 4],
           [r[2] for r in starts])


V11B_AUFRUF = ("        # VOR dem Ausfuehren (nur fuer die Zustandspille, keine "
               "Anzeige).\n        _auftrag_anzeige_rufen(d, meta)\n")


def _v_auftrag(kern):
    """V11b (Kern 2.19.1, Gegenpruefung K12): ein Auftrag AUSSERHALB eines
    Laufs (kein Balken: Auto, ohne angemeldete Bauteile) — der Haken
    erfaehrt ihn trotzdem VOR dem Ausfuehren als `auftrag` (zugriff,
    Beschreibung), damit die Zustandspille des Docks WAEHREND des Auftrags
    "Zeichnet"/"Liest" sagt; kein `start` (keine Arbeitsanzeige). Wirft er,
    eine Zeile im Log, der Auftrag laeuft, der Lauf-Rueckfall bleibt aus."""
    rufe, basis = [], []

    def haken(art, info):
        rufe.append((art, info.get("zugriff"), info.get("beschreibung"),
                     len(_FakeDoc.elemente) - basis[0]))

    def lauf(km, haken_):
        d = _k_dienst(km, "V")
        d.cfg.lauf_anzeige = haken_
        _FakeDoc.dienst = d
        basis[:] = [len(_FakeDoc.elemente)]
        try:
            for params in ({"code": V_CODE.replace("paket", "[0, 1]"),
                            "description": "V11b schreiben"},
                           {"code": "result = 1", "access_mode": "read",
                            "description": "V11b lesen"}):
                km._auftrag_ausfuehren(d, _k_job(km, "execute_cwapi3d",
                                                 params))
        finally:
            d.beenden = True
        return d

    d = lauf(kern, haken)
    pruefe("V11b ohne Lauf: je Auftrag EIN `auftrag` (schreibend, dann "
           "lesend) VOR dem Ausfuehren (0 neue Bauteile im Moment des "
           "Aufrufs), kein `start`",
           rufe == [("auftrag", "write", "V11b schreiben", 0),
                    ("auftrag", "read", "V11b lesen", 2)], rufe)
    gesehen = []
    alt_error = kern.LOG.error
    kern.LOG.error = lambda *a, **k: gesehen.append(a[0] % a[1:])

    def wirft(art, info):
        raise RuntimeError("Probe")
    try:
        d = lauf(kern, wirft)
    finally:
        kern.LOG.error = alt_error
    pruefe("V11b wirft der Haken: EINE Zeile im Log, beide Auftraege laufen, "
           "der Lauf-Rueckfall bleibt aus",
           len(gesehen) == 1 and "auftrag" in gesehen[0]
           and (d.letzter_auftrag or {}).get("ok")
           and d.lauf_haken_kaputt is False, (gesehen, d.lauf_haken_kaputt))
    with io.open(KERN_PFAD, encoding="utf-8") as fh:
        quelle = fh.read()
    with tempfile.TemporaryDirectory(prefix="omcad_v11b_") as tmp:
        pfad = os.path.join(tmp, "omcad_bridge_core.py")
        with io.open(pfad, "w", encoding="utf-8") as fh:
            fh.write(quelle.replace(V11B_AUFRUF, "        pass\n"))
        km = kern_laden(pfad, name="omcad_bridge_core_v11b")
        rufe[:] = []
        lauf(km, haken)
    pruefe("V11b KONTROLLE: ein Kern ohne den Aufruf (wie 2.19.0) ruft den "
           "Haken fuer einen Auftrag ohne Lauf nie (Zelle oben rot)",
           quelle.count(V11B_AUFRUF) == 1 and rufe == [], rufe)


def _v_altkern(kern_alt, tmp, titel):
    """V8: der NEUE Server-Paketlauf gegen einen Kern, der das Feld
    `paketlauf` nicht kennt (jeder Kern vor 2.18, ausgerollt ist 2.17.0).

    Anlass: der MCP-Server des Chats laeuft aus dem Haupt-Checkout. Nach dem
    Merge schickt er das Feld auch an den ausgerollten Kern. Ein Kern vor
    2.18 liest es nie und weist unbekannte Felder nicht ab — dann laeuft der
    Lauf wie bisher (Vorhang je Paket, Nachziehen im Leerlauf).
    """
    with Pruefstand(kern_alt) as p:
        gestellt = _stufe(p, "auto")
        p.dienst.ms_je_teil = 35.0
        _v_frisch(p)
        erg, sn, ges = _v_lauf(p, tmp, "V8 %s" % titel)
        alle = _v_ids(sn)
        pruefe("V8 [%s] neuer Server-Paketlauf: ok, 3 Pakete, 6 Bauteile, "
               "das Feld paketlauf ging an jedes Paket" % titel,
               gestellt and erg.get("ok") and len(sn) == 3
               and len(set(alle)) == 6
               and [g.get("paketlauf") for g in ges]
               == [{"paket": k, "pakete": 3} for k in (1, 2, 3)],
               json.dumps(erg)[:160])
        pruefe("V8 [%s] der Kern uebergeht das Feld: jedes Paket hinter dem "
               "Vorhang wie bisher, nichts paketweise gemeldet" % titel,
               set(alle) <= _v_versteckt()
               and [z for z, _i in _FakeDoc.vorhang].count("zu") == 3
               and "nachgezogen" not in erg
               and not any("paket_nachgezogen" in s["antwort"] for s in sn),
               "%s" % [z for z, _i in _FakeDoc.vorhang])
        pruefe("V8 [%s] im Leerlauf nachgezogen und aufgedeckt (bisheriger "
               "Weg)" % titel,
               warte_bis(lambda: set(alle) <= set(_FakeDoc.material_hell)
                         and not set(alle) & _FakeDoc.unsichtbar, 6))
        _v_frisch(p)


def _v_streng(kern_streng, tmp):
    """V8 KONTROLLE: ein Kern, der unbekannte Felder ABWEIST. So einer
    braeuchte einen Rueckfall im Server (Feld nur, wenn der Kern es kennt).
    Keiner der ausgerollten tut das — aber die Zellen V8 muessen es sehen."""
    with Pruefstand(kern_streng) as p:
        _stufe(p, "auto")
        _v_frisch(p)
        erg, _sn, ges = _v_lauf(p, tmp, "V8 streng")
        pruefe("V8 KONTROLLE: ein Kern, der das Feld abweist, bricht den Lauf "
               "bei Paket 1 ab — V8 wuerde rot",
               not erg.get("ok") and erg.get("abgebrochen_bei_paket") == 1
               and erg.get("pakete_fertig") == 0 and len(ges) == 1
               and "paketlauf" in (erg.get("message") or ""),
               json.dumps(erg)[:200])
        _v_frisch(p)


def _kern_ohne_paketlauf():
    """Der heutige Kern, frisch geladen, der `paketlauf` nie liest — so wie
    jeder Kern vor 2.18 (dort gibt es `paket_von` nicht)."""
    k = kern_laden(name="omcad_bridge_core_ohne_paketlauf")
    k.paket_von = lambda params: None
    return k


def _kern_streng():
    """Wie `_kern_ohne_paketlauf`, weist das Feld aber in der Annahme ab."""
    k = kern_laden(name="omcad_bridge_core_streng")
    k.paket_von = lambda params: None
    annahme = k._annahme_pruefen

    def pruefen(d, methode, meta, params):
        if "paketlauf" in params:
            return k._fehler("bad_params", "unbekannter Parameter 'paketlauf'")
        return annahme(d, methode, meta, params)

    k._annahme_pruefen = pruefen
    return k


def abschnitt_v(kern, altkern=None):
    """Film 2026-09-25: Paketlauf in 'Auto' paketweise.

    `altkern`: Pfad eines alten Kerns (z. B. des ausgerollten). Er wird in
    ein Temp-Verzeichnis KOPIERT und nur die Kopie geladen; V8 laeuft dann
    zusaetzlich gegen ihn (`--altkern PFAD`).
    """
    sag("\n--- V  Paketlauf: paketweise statt Vorhang bis zum Ende ---")
    with tempfile.TemporaryDirectory(prefix="omcad_v_") as tmp:
        with Pruefstand(kern) as p:
            _v_auto(kern, p, tmp)
            _v_stufen(kern, p, tmp)
            _v_feld(kern, p, tmp)
            _v_fehler(p, tmp)
            _v_ende(kern, p, tmp)
        _v_ruhe(kern)
        _v_ohne_dunkel(kern)
        _v_haken(kern)
        _v_auftrag(kern)
        _v_altkern(_kern_ohne_paketlauf(), tmp, "Kern ohne paketlauf")
        _v_streng(_kern_streng(), tmp)
        if altkern:
            import shutil
            kopie = os.path.join(tmp, "altkern", "omcad_bridge_core.py")
            os.makedirs(os.path.dirname(kopie))
            shutil.copyfile(altkern, kopie)
            alt = kern_laden(kopie, name="omcad_bridge_core_altkern")
            sag("    V8 zusaetzlich gegen Kern %s (Kopie von %s)"
                % (alt.CORE_VERSION, altkern))
            _v_altkern(alt, tmp, "Kern %s" % alt.CORE_VERSION)


# --- Q: Qt-Schicht PyQt6 / PyQt5 (Cadwork 2025, seit 2026-10-10) ----------
#
# Anlass (gemessen vom Maintainer auf einem Laptop, 2026-10-10): Cadwork 3D
# 2025 bringt Python 3.12.7 und PyQt5 mit, kein PyQt6. Die Wahl der Bindung
# steht ZWEIMAL — `omcad_qt.waehlen` (Dock) und `_qt_bindung` (Kern, auch in
# B-F ohne UI-Module). Gemessen wird beides in denselben Welten, gegen
# Attrappen-Pakete in einem Kind-Prozess (dieses Gate hat kein Qt und
# importiert keins).

Q_WELTEN = (
    # (Name, geladen, importierbar, erwartet)
    ("nichts geladen, beide da", (), ("PyQt6", "PyQt5"), "PyQt6"),
    ("nichts geladen, nur PyQt5 (Cadwork 2025)", (), ("PyQt5",), "PyQt5"),
    ("PyQt5 geladen, PyQt6 auch importierbar", ("PyQt5",),
     ("PyQt6", "PyQt5"), "PyQt5"),
    ("beide geladen", ("PyQt6", "PyQt5"), ("PyQt6", "PyQt5"), "PyQt6"),
    ("PyQt6 geladen, nur PyQt6", ("PyQt6",), ("PyQt6",), "PyQt6"),
    ("keine Bindung", (), (), None),
)


def _q_welt(waehlen, geladen, importierbar):
    module = {b + ".QtCore": types.ModuleType(b) for b in geladen}
    versucht = []

    def importieren(name):
        versucht.append(name)
        if name.split(".")[0] in importierbar:
            return types.ModuleType(name)
        raise ImportError("Attrappe: %s fehlt" % name)
    try:
        erg = waehlen(module, importieren)
    except ImportError:
        erg = None
    if isinstance(erg, tuple):
        erg = erg[0]
    return erg, versucht


def _q_schicht_laden(pfad, name="omcad_qt_q"):
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# Ein Kind-Prozess mit Attrappen-Paketen PyQt5 (und wahlweise PyQt6) auf dem
# Pfad laedt die ECHTE Schicht und meldet, was sie gebunden hat.
_Q_KIND = r"""
import importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("omcad_qt", sys.argv[2])
m = importlib.util.module_from_spec(spec)
sys.modules["omcad_qt"] = m
spec.loader.exec_module(m)
aus = {"bindung": m.BINDUNG, "stand": m.stand(), "fehler": m.FEHLER}
try:
    from omcad_qt.QtGui import QAction, QShortcut
    from omcad_qt.QtWidgets import QApplication
    from omcad_qt.QtCore import Qt
    aus["namen"] = [QAction.__module__, QShortcut.__module__,
                    QApplication.__module__, Qt.__module__]
except Exception as exc:
    aus["namen"] = "%s: %s" % (type(exc).__name__, exc)
gui = sys.modules.get((m.BINDUNG or "x") + ".QtGui")
aus["echtes_qtgui_unberuehrt"] = gui is not None and not hasattr(gui, "QAction")
class E5:
    def globalPos(self): return "global5"
    def localPos(self): return "lokal5"
class E6:
    class P:
        def toPoint(self): return "global6"
    def globalPosition(self): return E6.P()
    def position(self): return "lokal6"
class Wert6:
    value = 7
aus["punkte"] = [m.global_punkt(E5()), m.punkt(E5()), m.global_punkt(E6()),
                 m.punkt(E6())]
aus["wert"] = [m.wert(5), m.wert(Wert6())]
try:
    m.laden()
    aus["laden"] = "ok"
except ImportError as exc:
    aus["laden"] = str(exc)
print("QKIND " + json.dumps(aus))
"""


def _q_attrappen(wurzel, bindungen):
    for b in bindungen:
        d = os.path.join(wurzel, b)
        os.makedirs(d)
        with open(os.path.join(d, "__init__.py"), "w") as fh:
            fh.write("")
        with open(os.path.join(d, "QtCore.py"), "w") as fh:
            fh.write("class Qt:\n    pass\n"
                     "QT_VERSION_STR = %r\nPYQT_VERSION_STR = %r\n"
                     % (b[-1] + ".99.2", b[-1] + ".99.1"))
        with open(os.path.join(d, "QtGui.py"), "w") as fh:
            fh.write("class QColor:\n    pass\n"
                     + ("class QAction:\n    pass\n"
                        "class QShortcut:\n    pass\n" if b == "PyQt6"
                        else ""))
        with open(os.path.join(d, "QtWidgets.py"), "w") as fh:
            fh.write("class QApplication:\n    pass\n"
                     + ("class QAction:\n    pass\n"
                        "class QShortcut:\n    pass\n" if b == "PyQt5"
                        else ""))


def _q_kind(schicht, bindungen):
    import subprocess
    wurzel = tempfile.mkdtemp(prefix="omcad_q_")
    _q_attrappen(wurzel, bindungen)
    erg = subprocess.run([sys.executable, "-I", "-c", _Q_KIND, wurzel,
                          schicht], capture_output=True, text=True,
                         timeout=60)
    zeile = [z for z in erg.stdout.splitlines() if z.startswith("QKIND ")]
    if not zeile:
        return {"kaputt": erg.stdout[-400:] + erg.stderr[-800:]}
    return json.loads(zeile[0][6:])


def abschnitt_q(kern):
    sag("\nQ  Qt-Schicht: PyQt6 (Cadwork 2026) oder PyQt5 (Cadwork 2025)")
    schicht_pfade = [os.path.join(REPO, "cad_plugin", o, "omcad_qt.py")
                     for o in ("Open MCP CAD", "Open MCP CAD A")]
    schicht = _q_schicht_laden(schicht_pfade[0])
    pruefe("Q0 ohne Qt (dieses Gate): Schicht laedt, bindet nichts, sagt "
           "warum, laden() wirft ImportError",
           schicht.BINDUNG is None and "PyQt" in schicht.FEHLER
           and "omcad_qt.QtCore" not in sys.modules,
           "BINDUNG %r, FEHLER %r" % (schicht.BINDUNG, schicht.FEHLER))
    try:
        schicht.laden()
        geworfen = None
    except ImportError as exc:
        geworfen = str(exc)
    pruefe("Q0 laden() ohne Qt -> ImportError mit Grund",
           geworfen is not None and "braucht Qt" in geworfen, geworfen)

    def kern_waehlen(module, importieren):
        return kern._qt_bindung(module, importieren)
    for titel, geladen, importierbar, erwartet in Q_WELTEN:
        d, v_d = _q_welt(schicht.waehlen, geladen, importierbar)
        k, v_k = _q_welt(kern_waehlen, geladen, importierbar)
        # Ist schon eine Bindung geladen, wird NICHTS importiert.
        ruhig = (not geladen) or (v_d == [] and v_k == [])
        pruefe("Q1 %s -> %s (Dock und Kern gleich, ohne Import, wenn "
               "geladen)" % (titel, erwartet),
               d == erwartet and k == erwartet and ruhig,
               "Dock %r %r, Kern %r %r" % (d, v_d, k, v_k))
    # Q1-K: eine Wahl, die eine GELADENE Bindung uebergeht (nur die
    # Reihenfolge), MUSS in der Welt "PyQt5 geladen" auffallen.
    def nur_reihenfolge(module, importieren):
        return schicht.waehlen({}, importieren)
    d, _v = _q_welt(nur_reihenfolge, ("PyQt5",), ("PyQt6", "PyQt5"))
    pruefe("Q1-K eine Wahl ohne Blick auf das Geladene faellt auf "
           "(PyQt6 neben Cadworks PyQt5)", d == "PyQt6", d)
    # Q1-K2: der Kern ohne PyQt5-Rueckfall (Stand 2.19) faellt auf.
    alt = kern.QT_BINDUNGEN
    try:
        kern.QT_BINDUNGEN = ("PyQt6",)
        k, _v = _q_welt(kern_waehlen, (), ("PyQt5",))
    finally:
        kern.QT_BINDUNGEN = alt
    pruefe("Q1-K Kern ohne PyQt5 (Stand 2.19) faellt in der Welt "
           "Cadwork 2025 auf", k is None, k)

    # Q2: die ECHTE Schicht gegen Attrappen-Pakete, je Ordner.
    for pfad in schicht_pfade:
        ordner = os.path.basename(os.path.dirname(pfad))
        a5 = _q_kind(pfad, ("PyQt5",))
        pruefe("Q2 %s nur PyQt5: gebunden, QAction/QShortcut ueber QtGui "
               "(aus QtWidgets), echtes QtGui unberuehrt, Stand mit "
               "Versionen" % ordner,
               a5.get("bindung") == "PyQt5"
               and a5.get("namen") == ["PyQt5.QtWidgets", "PyQt5.QtWidgets",
                                       "PyQt5.QtWidgets", "PyQt5.QtCore"]
               and a5.get("echtes_qtgui_unberuehrt") is True
               and a5.get("stand") == "PyQt5 5.99.1 / Qt 5.99.2"
               and a5.get("laden") == "ok", a5)
        pruefe("Q2 %s Positionen und Enum-Werte fuer Qt 5 und Qt 6"
               % ordner,
               a5.get("punkte") == ["global5", "lokal5", "global6", "lokal6"]
               and a5.get("wert") == [5, 7], a5)
        a6 = _q_kind(pfad, ("PyQt6", "PyQt5"))
        pruefe("Q2 %s PyQt6 und PyQt5: PyQt6 (QAction aus QtGui)" % ordner,
               a6.get("bindung") == "PyQt6"
               and a6.get("namen") == ["PyQt6.QtGui", "PyQt6.QtGui",
                                       "PyQt6.QtWidgets", "PyQt6.QtCore"],
               a6)
    # Q2-K: eine Schicht OHNE das Verschieben (Qt5 wie Qt6 behandelt) MUSS
    # an QAction scheitern.
    quelle = io.open(schicht_pfade[0], encoding="utf-8").read()
    alt_z = 'NACH_QTGUI = ("QAction",'
    kd = tempfile.mkdtemp(prefix="omcad_qk_")
    kpfad = os.path.join(kd, "omcad_qt.py")
    with io.open(kpfad, "w", encoding="utf-8") as fh:
        fh.write(quelle.replace(alt_z, 'NACH_QTGUI = ("xQAction",'))
    k5 = _q_kind(kpfad, ("PyQt5",))
    pruefe("Q2-K Schicht ohne verschobenes QAction faellt unter PyQt5 auf",
           alt_z in quelle and isinstance(k5.get("namen"), str)
           and "QAction" in k5.get("namen"), k5)
    pruefe("Q3 beide Schicht-Kopien bytegleich (A und ausgerollt)",
           open(schicht_pfade[0], "rb").read()
           == open(schicht_pfade[1], "rb").read())

    # Q4: kein UI-Modul und kein Kern importiert PyQt6/PyQt5 an der Schicht
    # vorbei (geprueft am AST: jede Import-Anweisung).
    vorbei = []
    for ordner in ("Open MCP CAD", "Open MCP CAD A"):
        for datei in sorted(glob.glob(os.path.join(REPO, "cad_plugin", ordner,
                                                   "*.py"))):
            name = os.path.basename(datei)
            if name in ("omcad_qt.py", "omcad_startfehler.py"):
                continue          # die Schicht selbst; Startfehler: eigener Weg
            baum = ast.parse(io.open(datei, encoding="utf-8").read())
            for n in ast.walk(baum):
                mods = []
                if isinstance(n, ast.ImportFrom):
                    mods = [n.module or ""]
                elif isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                for mod in mods:
                    if mod.split(".")[0] in ("PyQt6", "PyQt5"):
                        vorbei.append("%s/%s:%d %s" % (ordner, name,
                                                       n.lineno, mod))
    pruefe("Q4 kein Plugin-Modul importiert PyQt6/PyQt5 an der Schicht "
           "vorbei (Kern: _qt_namen)", vorbei == [], vorbei[:8])
    k_baum = ast.parse("from PyQt6.QtCore import Qt\n")
    pruefe("Q4-K die Suche findet einen direkten Import",
           any(isinstance(n, ast.ImportFrom) and n.module.startswith("PyQt6")
               for n in ast.walk(k_baum)))

    # Q5: Python 3.12 (Cadwork 2025 bringt 3.12.7). Jedes Plugin-Modul muss
    # mit DIESEM Interpreter uebersetzen; das Gate laeuft mit 3.12.
    import py_compile
    kaputt = []
    for datei in sorted(glob.glob(os.path.join(REPO, "cad_plugin", "*",
                                               "*.py"))):
        try:
            py_compile.compile(datei, cfile=os.path.join(
                tempfile.mkdtemp(), "x.pyc"), doraise=True)
        except py_compile.PyCompileError as exc:
            kaputt.append("%s: %s" % (datei, exc))
    pruefe("Q5 alle Plugin-Module uebersetzen mit Python %s"
           % sys.version.split()[0], kaputt == [] and sys.version_info[:2]
           == (3, 12), kaputt[:3] or sys.version.split()[0])


def _argument(name):
    """Wert nach `name` in der Befehlszeile, sonst None."""
    if name in sys.argv[:-1]:
        return sys.argv[sys.argv.index(name) + 1]
    return None


def main():
    cwapi3d_attrappen_setzen()
    kern = kern_laden()
    import logging
    logging.disable(logging.CRITICAL)     # Testlauf soll leise sein

    sag("Open MCP CAD — Offline-Gate")
    sag("Kern %s, Protokoll %d, Python %s"
          % (kern.CORE_VERSION, kern.PROTOKOLL_VERSION, sys.version.split()[0]))

    abschnitt_a()
    abschnitt_b(kern)
    abschnitt_c(kern)
    abschnitt_e(kern)
    abschnitt_f(kern)
    abschnitt_g(kern)
    abschnitt_h(kern)
    abschnitt_i(kern)
    abschnitt_j(kern)
    abschnitt_k(kern)
    abschnitt_v(kern, altkern=_argument("--altkern"))
    abschnitt_q(kern)

    fehler =[(n, i) for n, gut, i in _ergebnisse if not gut]
    sag("\n" + "=" * 66)
    sag("%d/%d bestanden" % (len(_ergebnisse) - len(fehler), len(_ergebnisse)))
    if fehler:
        sag("\nFEHLGESCHLAGEN:")
        for n, i in fehler:
            sag("  - %s%s" % (n, ("  — %s" % i) if i else ""))
        return 1
    sag("Alle Offline-Kriterien erfuellt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
