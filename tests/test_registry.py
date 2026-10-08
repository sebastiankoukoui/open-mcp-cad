#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer Port-Automatik und Registry — und fuer die Luecke, die E und F
fuenf Wochen lang tot liess.

    python tests/test_registry.py

DER ANLASS. Am 2026-08-04 stand in `Konfiguration.__init__` die Pruefung
`instanz not in ("A","B","C","D")` — damals richtig, es gab vier. Am
2026-08-15 wurde auf SECHS erhoeht: der Generator erzeugte E und F,
Cadwork zeigte sie im Menue, und ihr Start scheiterte an dieser Zeile.
Gefunden erst am 2026-09-20.

Warum kein Gate es sah: `test_offline` prueft die LISTE der Steckplaetze
("mehr als vier sind vorgesehen") und die erzeugten DATEIEN. Keines hat je
einen Steckplatz KONFIGURIERT. Eine Liste, die stimmt, und Dateien, die
erzeugt werden, sagen nichts darueber, ob der Steckplatz startet.

Deshalb ist die erste Pruefung hier: JEDER Steckplatz, den der Generator
kennt, muss sich konfigurieren lassen. Diese Pruefung waechst mit der Zahl
mit, weil sie die Liste des Generators liest statt eine eigene zu fuehren.
"""
import io
import json
import os
import shutil
import socket
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if not bedingung:
        print("  [FEHL] %s%s" % (titel, ("  -- %s" % detail) if detail else ""))
    return bool(bedingung)


def kern_laden(registry_ordner):
    """Laedt den Kern frisch, mit eigenem Registry-Ordner."""
    import importlib.util
    os.environ["OPEN_MCP_CAD_REGISTRY"] = registry_ordner
    pfad = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
    spec = importlib.util.spec_from_file_location("omcad_kern_test", pfad)
    kern = importlib.util.module_from_spec(spec)
    sys.modules["omcad_kern_test"] = kern
    spec.loader.exec_module(kern)
    return kern


def main():
    print("Open MCP CAD - Registry-Gate\n")
    tmp = tempfile.mkdtemp(prefix="omcad_registry_")
    try:
        kern = kern_laden(tmp)

        # --- 1. JEDER erzeugte Steckplatz muss startbar sein --------------
        print("--- 1. Alle Steckplaetze des Generators konfigurieren ---")
        import plugins_generieren as gen
        schlecht = []
        for instanz, ordner, port in gen.STECKPLAETZE:
            try:
                cfg = kern.Konfiguration(instanz=instanz, port=port)
                if cfg.port != port or cfg.instanz != instanz:
                    schlecht.append("%s: falsch uebernommen" % instanz)
            except Exception as exc:                        # noqa: BLE001
                schlecht.append("%s: %s" % (instanz, exc))
        pruefe("R1 jeder erzeugte Steckplatz laesst sich konfigurieren",
               not schlecht,
               "; ".join(schlecht[:3]) or "")
        pruefe("R2 es sind mehr als vier", len(gen.STECKPLAETZE) > 4,
               "%d" % len(gen.STECKPLAETZE))

        # KONTROLLE: das alte Inventar haette E und F abgelehnt. Ohne diese
        # Zeile pruefte R1 nur, dass der heutige Zustand sich selbst gleicht.
        alt_erlaubt = ("A", "B", "C", "D")
        wuerden_fallen = [i for i, _o, _p in gen.STECKPLAETZE
                          if i not in alt_erlaubt]
        pruefe("R3 KONTROLLE: mit dem alten Inventar waeren Steckplaetze "
               "gefallen", bool(wuerden_fallen),
               "sonst misst R1 nichts: %r" % (wuerden_fallen,))

        # --- 2. Was die Instanz-Regel annimmt und was nicht ---------------
        print("--- 2. Instanz-Kennung ---")
        for gut in ("A", "F", "Z", "9", "12", "a", "53200", "65373"):
            try:
                kern.Konfiguration(instanz=gut, port=53127)
                ok = True
            except Exception:                               # noqa: BLE001
                ok = False
            pruefe("R4 %r wird angenommen" % gut, ok)
        # "123" steht bewusst dabei: drei Ziffern sind weder eine kurze
        # Kennung noch eine Portnummer. Das Muster darf nicht einfach
        # "irgendwas Kurzes" durchlassen.
        for schlecht_i in ("", "ABC", "A!", "-", "A B", "123", "123456"):
            try:
                kern.Konfiguration(instanz=schlecht_i, port=53127)
                ok = False
            except ValueError:
                ok = True
            except Exception:                               # noqa: BLE001
                ok = False
            pruefe("R5 %r wird abgelehnt" % schlecht_i, ok)

        # --- 3. Port-Automatik -------------------------------------------
        print("--- 3. Port-Automatik ---")
        cfg = kern.Konfiguration(instanz="A")
        pruefe("R6 ohne Port steht None, nicht heimlich eine Zahl",
               cfg.port is None)

        p = kern.freier_port()
        pruefe("R7 freier_port() liefert eine Zahl im Bereich",
               kern.PORT_VON <= p <= kern.PORT_BIS, str(p))
        pruefe("R8 und der Port ist wirklich frei", kern.port_frei(p))

        # Belegen und messen, dass die Suche ihn ueberspringt.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", p))
        s.listen(1)
        try:
            pruefe("R9 ein belegter Port meldet sich als belegt",
                   not kern.port_frei(p))
            p2 = kern.freier_port()
            pruefe("R10 die Suche nimmt den naechsten", p2 != p, "%d/%d" % (p, p2))
        finally:
            s.close()
        pruefe("R11 nach dem Schliessen ist er wieder frei", kern.port_frei(p))

        pruefe("R12 ein leerer Bereich wirft, statt None zu liefern",
               _wirft(lambda: kern.freier_port(von=1, bis=0)))

        # --- 4. Registry: eintragen, finden, austragen --------------------
        print("--- 4. Registry ---")
        c1 = kern.Konfiguration(instanz="A", port=53127)
        c2 = kern.Konfiguration(instanz="B", port=53128)
        kern.registry_eintragen(c1, "Seeblick_EG.3d")
        kern.registry_eintragen(c2, "Detailkatalog.3d")

        alle = kern.registry_lesen()
        pruefe("R13 beide Eintraege sind da", len(alle) == 2, str(len(alle)))
        pruefe("R14 nach Port sortiert",
               [e["port"] for e in alle] == [53127, 53128])

        treffer = kern.registry_finden("seeblick")
        pruefe("R15 Suche findet ueber den Dokumentnamen, ohne Gross/Klein",
               len(treffer) == 1 and treffer[0]["port"] == 53127)
        pruefe("R16 Suche liefert eine LISTE, auch bei einem Treffer",
               isinstance(treffer, list))
        pruefe("R17 zwei Dateien mit gleichem Teilstring geben ZWEI Treffer",
               len(kern.registry_finden(".3d")) == 2,
               "sonst raet der Aufrufer, statt zu entscheiden")
        pruefe("R18 leere Suche findet nichts",
               kern.registry_finden("") == []
               and kern.registry_finden("   ") == [])

        geaendert = kern.registry_dokument_setzen(53127, "Seeblick_OG.3d")
        pruefe("R19 der Dokumentname laesst sich nachfuehren", geaendert)
        pruefe("R20 und die Suche findet den neuen Namen",
               len(kern.registry_finden("Seeblick_OG")) == 1
               and kern.registry_finden("Seeblick_EG") == [])
        pruefe("R21 derselbe Name schreibt NICHT neu",
               kern.registry_dokument_setzen(53127, "Seeblick_OG.3d") is False,
               "sonst schriebe jede Auffrischung die Datei")

        kern.registry_austragen(53127)
        pruefe("R22 austragen entfernt genau einen",
               len(kern.registry_lesen()) == 1)
        pruefe("R23 zweimal austragen ist kein Fehler",
               kern.registry_austragen(53127) is False)

        # --- 5. Tote Eintraege ------------------------------------------
        print("--- 5. Abgestuerzte Instanzen ---")
        c3 = kern.Konfiguration(instanz="C", port=53129)
        kern.registry_eintragen(c3, "Tot.3d", pid=999999)
        vorher = len(os.listdir(tmp))
        alle = kern.registry_lesen()
        pruefe("R24 ein Eintrag mit toter PID taucht nicht auf",
               all(e["port"] != 53129 for e in alle))
        pruefe("R25 und seine Datei ist weg",
               len(os.listdir(tmp)) < vorher,
               "sonst behauptet sie fuer immer 'laeuft'")

        # KONTROLLE: der eigene Prozess lebt — sein Eintrag MUSS bleiben.
        c4 = kern.Konfiguration(instanz="D", port=53130)
        kern.registry_eintragen(c4, "Lebt.3d")
        pruefe("R26 KONTROLLE: der lebende Eintrag bleibt",
               any(e["port"] == 53130 for e in kern.registry_lesen()),
               "sonst raeumt R24 einfach alles weg")

        # Unlesbare Datei
        kaputt = os.path.join(tmp, "instanz-53199.json")
        io.open(kaputt, "w", encoding="utf-8").write("{kein json")
        alle = kern.registry_lesen()
        pruefe("R27 eine unlesbare Datei kippt das Lesen nicht",
               all(e["port"] != 53199 for e in alle)
               and not os.path.exists(kaputt))

        # Wiederverwendete PID (Befund 2026-09-25): die PID lebt, gehoert
        # aber einem Prozess, der NACH dem Eintrag gestartet ist — hier der
        # eigene, mit einem Eintrag "von gestern". Der Kern ist der einzige
        # Leser, der aufraeumt; er muss den Eintrag verwerfen UND loeschen,
        # darf aber nichts Lebendes anfassen.
        import time as _time
        geist = os.path.join(tmp, "instanz-53198.json")

        def _geist_schreiben():
            with io.open(geist, "w", encoding="utf-8") as fh:
                json.dump({"port": 53198, "instanz": "72", "pid": os.getpid(),
                           "dokument": "Geist.3d",
                           "start": _time.time() - 86400}, fh)

        def _alte_probe(pid, seit=None):
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x00100000, False,
                                                   int(pid))
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True

        if os.name == "nt":
            _geist_schreiben()
            echt_probe = kern._pid_lebt
            kern._pid_lebt = _alte_probe
            try:
                mit_alter = kern.registry_lesen()
            finally:
                kern._pid_lebt = echt_probe
            pruefe("R57-K KONTROLLE, DIE ROT WERDEN MUSS: mit der alten Probe "
                   "(nur PID) bleibt der Geist stehen, samt Datei",
                   any(e["port"] == 53198 for e in mit_alter)
                   and os.path.exists(geist))
            alle = kern.registry_lesen()
            pruefe("R57 wiederverwendete PID: der Eintrag zaehlt nicht und "
                   "seine Datei ist weg",
                   all(e["port"] != 53198 for e in alle)
                   and not os.path.exists(geist))
            pruefe("R58 das Aufraeumen laesst den lebenden Eintrag stehen",
                   any(e["port"] == 53130 for e in alle)
                   and os.path.exists(os.path.join(tmp, "instanz-53130.json")))
            ohne_start = os.path.join(tmp, "instanz-53195.json")
            with io.open(ohne_start, "w", encoding="utf-8") as fh:
                json.dump({"port": 53195, "instanz": "68",
                           "pid": os.getpid(), "dokument": "Alt.3d"}, fh)
            pruefe("R59 ein Eintrag ohne Startzeit bleibt bei der PID und "
                   "wird nicht geloescht",
                   any(e["port"] == 53195 for e in kern.registry_lesen())
                   and os.path.exists(ohne_start))
            os.remove(ohne_start)

        # --- 7. Drei Leser, ein Format -----------------------------------
        # Der Kern schreibt (in Cadworks Prozess), das Verbindungsfenster
        # liest (daneben), open_mcp_cad/registry.py liest (im MCP-Prozess).
        # Jeder hat seinen eigenen Leser, weil jeder in einem anderen
        # Prozess lebt. Dass sie dasselbe Format sprechen, kann man nur
        # messen, indem der eine schreibt und die anderen lesen.
        print("--- 7. Drei Leser, ein Format ---")
        kern.REGISTRY_ORDNER = tmp
        # Mit leerem Ordner anfangen: R32 zaehlt, und die Eintraege aus
        # Abschnitt 4 und 5 leben noch. (Genau das hat R32 beim Bauen
        # gemeldet — die Pruefung misst also wirklich.)
        for _e in kern.registry_lesen():
            kern.registry_austragen(_e["port"])
        c5 = kern.Konfiguration(instanz="A", port=53150)
        c6 = kern.Konfiguration(instanz="B", port=53151)
        kern.registry_eintragen(c5, "Alpha.3d")
        kern.registry_eintragen(c6, "Beta.3d")

        vom_kern = kern.registry_lesen()

        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        import importlib
        import open_mcp_cad.registry as reg
        reg.REGISTRY_ORDNER = tmp
        vom_server = reg.laufende()

        import connect_client as cc
        cc.REGISTRY_ORDNER = tmp
        vom_fenster = cc.registry_lesen()

        schl = lambda liste: sorted((e.get("port"), e.get("instanz"),
                                     e.get("dokument")) for e in liste)
        pruefe("R30 Kern und MCP-Server lesen dasselbe",
               schl(vom_kern) == schl(vom_server),
               "%r != %r" % (schl(vom_kern)[:2], schl(vom_server)[:2]))
        pruefe("R31 Kern und Verbindungsfenster lesen dasselbe",
               schl(vom_kern) == schl(vom_fenster))
        pruefe("R32 und es sind wirklich zwei Eintraege",
               len(vom_kern) == 2,
               "sonst vergleichen R30/R31 zwei leere Listen")

        # --- 8. Die Instanz ueber das Dokument finden --------------------
        print("--- 8. Auswahl ueber den Dokumentnamen ---")
        pruefe("R33 genau ein Treffer liefert den Port",
               reg.port_fuer("alpha") == 53150)
        pruefe("R34 kein Treffer liefert None",
               reg.port_fuer("gibtsnicht") is None)
        mehrdeutig = False
        try:
            reg.port_fuer(".3d")
        except reg.MehrdeutigesDokument as exc:
            mehrdeutig = "Alpha.3d" in str(exc) and "Beta.3d" in str(exc)
        pruefe("R35 MEHRERE Treffer brechen ab und nennen beide",
               mehrdeutig,
               "raten waere hier der Schaden, den der Dokumentschutz "
               "verhindern soll")

        os.environ["OPEN_MCP_CAD_DOC"] = "beta"
        import open_mcp_cad.bridge_client as bc
        importlib.reload(bc)
        bc.registry = reg                       # auf denselben Testordner
        vorher_port = bc.BRIDGE_PORT
        gewaehlt = bc._port()
        pruefe("R36 der Client waehlt den Port ueber das Dokument",
               gewaehlt == 53151, "%s -> %s" % (vorher_port, gewaehlt))
        pruefe("R37 KONTROLLE: ohne das Dokument bliebe es beim festen Port",
               vorher_port != 53151,
               "sonst misst R36 nichts")
        # Gefragt wird je Aufruf, bis ein Treffer eindeutig ist; der klebt
        # dann an Port und PID (Faelle: test_bootstrap D1-D11).
        pruefe("R38 der Treffer bleibt gewaehlt, auch beim naechsten Aufruf",
               (getattr(bc, "_gewaehlt", None) or {}).get("port") == 53151
               and bc._port() == 53151)
        os.environ.pop("OPEN_MCP_CAD_DOC", None)

        # Aufraeumen, damit Abschnitt 6 (fehlender Ordner) davon nichts sieht
        for p in (53150, 53151):
            kern.registry_austragen(p)

        # --- 9. Der reservierte Socket -----------------------------------
        # Kein bestehendes Gate deckt das ab: serve() nimmt seit dem Merge
        # einen bereits gebundenen Listener entgegen, statt selbst zu binden.
        # Das ist der Unterschied zwischen "pruefen, dann binden" (mit einem
        # Rennen dazwischen) und "gebunden, Punkt".
        print("--- 9. Reservierter Socket ---")
        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s1.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s1.bind(("127.0.0.1", 0))
        reservierter_port = s1.getsockname()[1]
        try:
            cfgr = kern.Konfiguration()
            kern._steckplatz_festlegen(cfgr, s1)
            pruefe("R39 der Port kommt aus dem reservierten Socket",
                   cfgr.port == reservierter_port,
                   "%s statt %s" % (cfgr.port, reservierter_port))
            pruefe("R40 die Kennung ist gueltig, auch ausserhalb des Bereichs",
                   bool(kern.Konfiguration.INSTANZ_MUSTER.match(cfgr.instanz)),
                   "Kennung %r" % cfgr.instanz)
            verboten = set('<>:"/|?*') & set(os.path.basename(cfgr.log_datei))
            pruefe("R41 der Logdateiname enthaelt kein verbotenes Zeichen",
                   not verboten,
                   "hier stand frueher '?' — unter Windows nicht anlegbar: %r"
                   % os.path.basename(cfgr.log_datei))

            # KONTROLLE: ohne reservierten Socket kommt der Port aus der
            # Suche, nicht aus dem Socket. Sonst misst R39 nichts.
            cfgk = kern.Konfiguration()
            kern._steckplatz_festlegen(cfgk, None)
            pruefe("R42 KONTROLLE: ohne Socket kommt der Port aus der Suche",
                   cfgk.port != reservierter_port
                   and kern.PORT_VON <= cfgk.port <= kern.PORT_BIS,
                   "%s" % cfgk.port)
        finally:
            s1.close()

        # Das Rennen, das die Reservierung schliesst — mit Kontrollzelle.
        a = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            for sk in (a, b):
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sk.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_EXCLUSIVEADDRUSE, 1)
            a.bind(("127.0.0.1", 0))
            pa = a.getsockname()[1]
            zweimal_moeglich = True
            try:
                b.bind(("127.0.0.1", pa))
            except OSError:
                zweimal_moeglich = False
            pruefe("R43 ein reservierter Port laesst sich nicht zweimal binden",
                   not zweimal_moeglich,
                   "genau das verhindert SO_EXCLUSIVEADDRUSE")
            # KONTROLLE: `port_frei()` bindet nur probeweise und gibt den Port
            # sofort wieder her. Es RESERVIERT nichts — deshalb ist es die
            # letzte Wahl und nicht die erste.
            pruefe("R44 KONTROLLE: port_frei() haelt den Port NICHT",
                   kern.port_frei(53199) and kern.port_frei(53199),
                   "zweimal hintereinander 'frei' — dazwischen passt jeder")
        finally:
            a.close()
            b.close()

        # --- 10. require_qtimer: kein stiller Rueckfall -------------------
        # Hier laeuft kein PyQt6, der Qt-Antrieb scheitert also immer. Genau
        # deshalb laesst sich beides in derselben Umgebung messen.
        print("--- 10. require_qtimer ---")
        import threading

        def _starten(mit_riegel, port):
            cfg = kern.Konfiguration(instanz="A", port=port)
            cfg.fenster = False
            if mit_riegel:
                cfg.require_qtimer = True
            d = kern.Verbindungsdienst(cfg)
            fehler = {}
            def lauf():
                try:
                    kern.serve(cfg, d)
                except Exception as exc:              # noqa: BLE001
                    fehler["exc"] = exc
            th = threading.Thread(target=lauf, daemon=True)
            th.start()
            th.join(timeout=4.0)
            d.beenden = True
            th.join(timeout=4.0)
            return cfg, fehler.get("exc")

        cfg_o, exc_o = _starten(False, 53196)
        pruefe("R45 ohne Riegel faellt der Antrieb zurueck und sagt es",
               cfg_o.antrieb == "mainthread" and exc_o is None,
               "antrieb=%r exc=%r" % (cfg_o.antrieb, exc_o))

        cfg_m, exc_m = _starten(True, 53197)
        pruefe("R46 MIT Riegel wird laut abgebrochen statt still "
               "zurueckzufallen",
               isinstance(exc_m, RuntimeError)
               and "require_qtimer" in str(exc_m),
               "exc=%r" % (exc_m,))
        pruefe("R47 und der Antrieb bleibt 'qtimer' — kein heimlicher Wechsel",
               cfg_m.antrieb == "qtimer", cfg_m.antrieb)

        # --- 11. Die Registry an der Oberflaeche -------------------------
        # `alle_steckplaetze()` und `finde_dokument()` waren toter Code:
        # definiert, nie aufgerufen. Jetzt haengen `status()` und
        # `alle_status()` daran — und nur so ist ein Steckplatz, der sich
        # seinen Port selbst gesucht hat, ueberhaupt abfragbar.
        print("--- 11. Registry an der Oberflaeche ---")
        import importlib
        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        import connect_client as cc2
        importlib.reload(cc2)
        cc2.REGISTRY_ORDNER = tmp

        for _e in kern.registry_lesen():
            kern.registry_austragen(_e["port"])
        cdyn = kern.Konfiguration(instanz="18", port=53145)
        kern.registry_eintragen(cdyn, "Dynamisch.3d")

        plaetze = cc2.alle_steckplaetze()
        pruefe("R48 alle_steckplaetze() enthaelt den dynamischen Platz",
               ("18", 53145) in plaetze,
               "%r" % (plaetze[-2:],))
        pruefe("R49 die benannten stehen weiter vorn und behalten ihre Ports",
               plaetze[0] == ("A", 53127))
        pruefe("R50 port_von findet eine dynamische Kennung",
               cc2.port_von("18") == 53145,
               "hier warf PORT_VON_INSTANZ[...] einen KeyError")
        pruefe("R51 port_von nimmt auch eine Portnummer",
               cc2.port_von(53145) == 53145 and cc2.port_von("53145") == 53145)
        pruefe("R52 kennung_von gibt den Namen, nicht '?'",
               cc2.kennung_von(53145) == "18",
               "hier stand next((...), '?')")
        unbekannt = False
        try:
            cc2.port_von("QQ")
        except KeyError as exc:
            unbekannt = "bekannt sind" in str(exc)
        pruefe("R53 eine unbekannte Kennung wirft und nennt das Bekannte",
               unbekannt,
               "ein stilles None fuehrte zu 'Port None nicht erreichbar' — "
               "eine Meldung, die in die falsche Richtung zeigt")

        # KONTROLLE: ohne Registry-Eintrag ist der Platz weg — sonst messen
        # R48-R52 nur, dass die feste Liste sich selbst gleicht.
        kern.registry_austragen(53145)
        pruefe("R54 KONTROLLE: ohne Eintrag ist der Platz wieder fort",
               ("18", 53145) not in cc2.alle_steckplaetze()
               and _wirft(lambda: cc2.port_von("18")))

        # --- 12. Kernversion in ALLEN Einstiegen -------------------------
        # Der Generator zieht `ERWARTETE_KERN_VERSION` nach — aber nur in den
        # Einstiegen, die er erzeugt. A und der dynamische sind
        # HANDGEPFLEGT; dort stand nach dem Sprung auf 2.16.0 weiter
        # "2.14.0", und der Start haette bei jedem Klick auf stderr gewarnt.
        #
        # Genau dafuer ist die Zahl da: ein `ping` soll beweisen, ob ein
        # Neustart gegriffen hat. Eine Warnung, die immer kommt, beweist
        # nichts mehr.
        print("--- 12. Kernversion in allen Einstiegen ---")
        import glob
        import re as _re
        _kernquelle = io.open(
            os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py"),
            encoding="utf-8").read()
        _ist = _re.search(r'^CORE_VERSION = "([^"]+)"', _kernquelle,
                          _re.M).group(1)
        _falsch = []
        _gepruefte = 0
        for _e in glob.glob(os.path.join(REPO, "cad_plugin", "*", "*.py")):
            _q = io.open(_e, encoding="utf-8").read()
            _m = _re.search(r'ERWARTETE_KERN_VERSION = "([^"]+)"', _q)
            if _m is None:
                continue
            _gepruefte += 1
            if _m.group(1) != _ist:
                _falsch.append("%s: %s" % (os.path.basename(_e), _m.group(1)))
        pruefe("R55 jeder Einstieg erwartet die Kernversion, die da ist",
               not _falsch, "Kern %s, aber %s" % (_ist, "; ".join(_falsch)))
        pruefe("R56 und es wurden wirklich Einstiege gefunden",
               _gepruefte >= len(gen.STECKPLAETZE),
               "%d gefunden, mindestens %d erwartet"
               % (_gepruefte, len(gen.STECKPLAETZE)))

        # --- 6. Fehlender Ordner ----------------------------------------
        print("--- 6. Ohne Registry-Ordner ---")
        leer = os.path.join(tmp, "gibt_es_nicht")
        kern.REGISTRY_ORDNER = leer
        pruefe("R28 kein Ordner heisst leere Liste, kein Absturz",
               kern.registry_lesen() == [])
        pruefe("R29 und die Suche ebenso", kern.registry_finden("x") == [])

    finally:
        os.environ.pop("OPEN_MCP_CAD_REGISTRY", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


def _wirft(fn):
    try:
        fn()
        return False
    except Exception:                                       # noqa: BLE001
        return True


if __name__ == "__main__":
    sys.exit(main())
