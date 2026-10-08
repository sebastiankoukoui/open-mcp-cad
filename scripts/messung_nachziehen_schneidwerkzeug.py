#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Messung: bekommen VBA keine Abschnitte, wenn das Material ihres
Schneidwerkzeugs gerade neu gesetzt wurde?

VERMUTUNG (Film 2026-09-25, docs/UEBERGABE_2026-09-25.md Abschnitt 12):
nach dem VBA-Lauf hatten 200 von 2288 VBA 0 Abschnitte, immer ganze Staebe
(25 x 8). Im selben Paket wurden Schlitzbleche angelegt und mit
`ec.subtract_elements_with_undo([blech], [stab], False)` in die Staebe
geschnitten; danach setzte das Nachziehen des Kerns (`_dunkle_elemente_
nachziehen`, Schnellzeichnen) das Material der Bleche neu. Vielleicht rechnet
Cadwork daraufhin die Bearbeitung der Staebe verzoegert neu, und VBA, die in
dieser Zeit entstehen, bekommen keine Abschnitte. Die Zahl aenderte sich nach
dem Lauf ohne Schreibauftrag (168 -> 200 -> 194): Cadwork rechnete nach.

DIESES SKRIPT misst genau das, an frischen Testelementen in einer eigenen
Gruppe, und raeumt sie danach weg. Je Variante mehrere Staebe mit je zwei
Schlitzblechen (eins je Ende, geschnitten wie im Film) und 4 VBA je Ende
quer durch Holz|Blech|Holz. Gelesen wird `ca.get_section_count` sofort und
nach Wartezeiten, dazu `ca.check_axis` und die Kontaktelemente.

    K0       Kontrolle: Material NICHT neu gesetzt, VBA direkt danach
    K10      Kontrolle: wie K0, 10 s Pause vor den VBA
    A_gleich Material neu und VBA im SELBEN Auftrag (keine Ereignisschleife
             dazwischen)
    A0       Material neu in eigenem Auftrag, VBA sofort im naechsten (wie im
             Film: Nachziehen im Leerlauf, dann das naechste Paket)
    A2, A10  wie A0, 2 bzw. 10 s Pause vor den VBA
    PK       Kontrolle zu P0: VBA am einen Ende, dann am anderen
    P0       VBA am einen Ende, deren Material neu (eigener Auftrag), sofort
             VBA am anderen Ende — so zieht Kern 2.18 in 'Auto' jedes Paket
             eines Paketlaufs nach. Auch VBA bearbeiten den Stab (Bohrung);
             gilt die Vermutung auch fuer sie, traefe es das naechste Paket.

Gestuetzt ist die Vermutung, wenn A-Varianten Staebe mit VBA ohne Abschnitte
zeigen und die K-Varianten nicht. Zeigen beide nichts, war es etwas anderes
(dann den Ablauf des Films genauer nachstellen, z. B. mit dem Katalog-VBA
ueber --vba-name statt der leeren Achse). P0 gegen PK sagt, ob das
paketweise Nachziehen (2.18) dasselbe Risiko traegt. Gemessen werden immer
die VBA des LETZTEN VBA-Schritts einer Variante.

Keine Konstruktionslogik ueber das Noetigste hinaus: Masse wie im Film
(Stab 160 x 280, Blech 10 mm, VBA 16 x 200), sonst nichts.

SICHERHEIT
  * Ohne --ausfuehren sendet das Skript NICHTS: es baut jeden Auftragscode,
    kompiliert ihn, prueft ihn gegen die Token-Sperre und die Code-Grenze
    des Kerns (aus dessen Quelle) und zeigt den Plan. Das ist die
    Offline-Pruefung.
  * Mit --ausfuehren braucht es --port (nur der zugewiesene Steckplatz,
    Arbeitsregel 6) und --dokument (Teil des Dateinamens; geprueft ueber
    die Bridge vor dem ersten Auftrag und als expect_document an JEDEM).
  * Nur in einer Wegwerf-Datei laufen lassen, nie im Projektmodell: die
    Elemente liegen weit abseits (--basis), werden aber im Modell angelegt.
    `subtract_elements_with_undo` neben bestehenden VBA kann eine Rueckfrage
    in Cadworks Befehlszeile ausloesen, die den Hauptthread blockiert
    (Uebergabe Abschnitt 8) — deshalb in einer Datei OHNE VBA messen.
  * Der Zeichenmodus muss 'Langsam' sein, sonst zieht der Kern selbst nach
    (und setzt das Material auch der Kontroll-Bleche neu). --modus-umstellen
    stellt ihn fuer die Messung um und danach zurueck.
  * Nur mit ausdruecklicher Freigabe gegen Cadwork laufen lassen.

    python scripts/messung_nachziehen_schneidwerkzeug.py
    python scripts/messung_nachziehen_schneidwerkzeug.py --ausfuehren \\
        --port 53127 --dokument Seeblick_Messung.3d --material Stahl \\
        [--modus-umstellen] [--ausgabe messung.json]
"""

import argparse
import ast
import json
import os
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
KERN = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")

# --- Aufbau (Masse wie im Film, mm) ----------------------------------------
STAB_B, STAB_H, STAB_L = 160.0, 280.0, 2000.0
BLECH_D, BLECH_H, BLECH_L, BLECH_UEBERSTAND = 10.0, 200.0, 350.0, 100.0
VBA_D, VBA_L = 16.0, 200.0
VBA_DX = (60.0, 180.0)          # Abstand vom Stabende nach innen
VBA_DZ = (-60.0, 60.0)          # Hoehe relativ zur Stabachse
ABSTAND_STAB = 1000.0           # Staebe einer Variante nebeneinander (Y)
ABSTAND_VARIANTE = 2000.0       # Varianten uebereinander (Z)
NACHLESEN_S = (0.5, 2.0, 5.0, 10.0, 30.0)

# Schritte nach dem Anlegen (Stab + Bleche + Schnitt, immer zuerst):
#   ("vba", enden, material_hier)  VBA an diesen Enden; material_hier: das
#                                  Material der Bleche im SELBEN Auftrag neu
#   ("material", "bleche"|"vba")   eigener Auftrag: Material neu setzen
#   ("pause", s)                   warten (Cadwork hat die Ereignisschleife)
BEIDE, LINKS, RECHTS = [-1, 1], [-1], [1]
VARIANTEN = (
    {"name": "K0", "schritte": [("vba", BEIDE, False)],
     "text": "Kontrolle: Material NICHT neu, VBA direkt danach"},
    {"name": "K10", "schritte": [("pause", 10.0), ("vba", BEIDE, False)],
     "text": "Kontrolle: Material NICHT neu, 10 s Pause"},
    {"name": "A_gleich", "schritte": [("vba", BEIDE, True)],
     "text": "Material neu und VBA im selben Auftrag"},
    {"name": "A0", "schritte": [("material", "bleche"),
                                ("vba", BEIDE, False)],
     "text": "Material neu, VBA sofort im naechsten Auftrag (wie im Film)"},
    {"name": "A2", "schritte": [("material", "bleche"), ("pause", 2.0),
                                ("vba", BEIDE, False)],
     "text": "Material neu, 2 s Pause"},
    {"name": "A10", "schritte": [("material", "bleche"), ("pause", 10.0),
                                 ("vba", BEIDE, False)],
     "text": "Material neu, 10 s Pause"},
    {"name": "PK", "schritte": [("vba", LINKS, False),
                                ("vba", RECHTS, False)],
     "text": "Kontrolle zu P0: VBA links, dann rechts"},
    {"name": "P0", "schritte": [("vba", LINKS, False), ("material", "vba"),
                                ("vba", RECHTS, False)],
     "text": "VBA links, deren Material neu, sofort VBA rechts (Kern 2.18)"},
)

# Gemeinsamer Kopf jedes Auftrags. Laeuft IN Cadwork (execute_cwapi3d);
# ec, ac, gc, mc, uc, vc und cadwork stellt der Kern bereit.
KOPF = '''\
import json as _j
import connector_axis_controller as ca
P = cadwork.point_3d


def _mitte(eid):
    v = gc.get_element_vertices(eid)
    n = float(len(v))
    return [sum(p[0] for p in v) / n, sum(p[1] for p in v) / n,
            sum(p[2] for p in v) / n]


def _material_neu(ids):
    # Wie `_dunkle_elemente_nachziehen` im Kern: je Material EIN Setzen auf
    # den eigenen Wert, bei EINGESCHALTETER Auffrischung.
    je = {}
    for e in ids:
        je.setdefault(ac.get_element_material_name(e), []).append(e)
    for name, gruppe in je.items():
        if name:
            ac.set_element_material(gruppe, mc.get_material_id(name))
    return sorted(je)


def _vba_lesen(ids):
    aus = {}
    for a in ids:
        try:
            n = int(ca.get_section_count(a))
        except Exception as exc:
            aus[str(a)] = {"fehler": str(exc)}
            continue
        kontakte = []
        for i in range(n):
            try:
                kontakte.append(int(ca.get_section_contact_element(a, i)))
            except Exception:
                kontakte.append(None)
        try:
            gueltig = bool(ca.check_axis(a))
        except Exception:
            gueltig = None
        aus[str(a)] = {"abschnitte": n, "kontakte": kontakte,
                       "gueltig": gueltig}
    return aus


d = _j.loads(DATEN)
'''

ANLEGEN = '''\
mid = mc.get_material_id(d["material"])
if not mid or mc.get_name(mid) != d["material"]:
    raise RuntimeError("Material %r nicht gefunden - mit --material ein "
                       "vorhandenes angeben" % d["material"])
if d["dunkel"]:
    uc.disable_auto_display_refresh()
try:
    staebe = []
    for x0, y0, z0 in d["orte"]:
        stab = ec.create_rectangular_beam_vectors(
            d["stab"][0], d["stab"][1], d["stab"][2], P(x0, y0, z0),
            P(1., 0., 0.), P(0., 0., 1.))
        c = _mitte(stab)
        bleche = []
        for seite in (-1, 1):
            ende_x = c[0] + seite * d["stab"][2] / 2.0
            mitte_x = ende_x - seite * (d["blech"][2] / 2.0 - d["ueberstand"])
            bl = ec.create_rectangular_panel_vectors(
                d["blech"][1], d["blech"][0], d["blech"][2], P(0., 0., 0.),
                P(1., 0., 0.), P(0., 1., 0.))
            m = _mitte(bl)
            ec.move_element([bl], P(mitte_x - m[0], c[1] - m[1], c[2] - m[2]))
            bleche.append(bl)
        ac.set_element_material(bleche, mid)
        ac.set_group([stab] + bleche, d["gruppe"])
        vol_vor = gc.get_actual_physical_volume(stab)
        rest = [int(e) for e in ec.subtract_elements_with_undo(
            bleche, [stab], False)]
        holz = [e for e in (rest or [stab]) if ec.check_element_id(e)]
        ac.set_group(holz, d["gruppe"])
        staebe.append({"stab": int(stab), "holz": holz,
                       "bleche": [int(b) for b in bleche], "mitte": c,
                       "vol_vor": vol_vor,
                       "vol_nach": sum(gc.get_actual_physical_volume(e)
                                       for e in holz)})
finally:
    if d["dunkel"]:
        uc.enable_auto_display_refresh()
result = staebe
'''

NACHZIEHEN = '''\
uc.enable_auto_display_refresh()
result = _material_neu(d["ids"])
vc.refresh()
'''

VBA = '''\
material_neu = None
if d["material_hier"]:
    # A_gleich: Material neu wie beim Nachziehen, dann OHNE Ereignisschleife
    # dazwischen gleich die VBA.
    uc.enable_auto_display_refresh()
    material_neu = _material_neu(d["bleche"])
if d["dunkel"]:
    uc.disable_auto_display_refresh()
try:
    je_stab = []
    for s in d["staebe"]:
        c = s["mitte"]
        ids = []
        for seite in d["enden"]:
            ende_x = c[0] + seite * d["stab_l"] / 2.0
            for dx in d["vba_dx"]:
                x = ende_x - seite * dx
                for dz in d["vba_dz"]:
                    p1 = P(x, c[1] - d["vba"][1] / 2.0, c[2] + dz)
                    p2 = P(x, c[1] + d["vba"][1] / 2.0, c[2] + dz)
                    if d["vba_name"]:
                        a = ca.create_standard_connector(d["vba_name"], p1, p2)
                    else:
                        a = ca.create_blank_connector(d["vba"][0], p1, p2)
                    ids.append(int(a))
        ac.set_group(ids, d["gruppe"])
        je_stab.append({"stab": s["stab"], "vba": ids})
    sofort = _vba_lesen([a for s in je_stab for a in s["vba"]])
finally:
    if d["dunkel"]:
        uc.enable_auto_display_refresh()
result = {"je_stab": je_stab, "sofort": sofort, "material_neu": material_neu}
'''

LESEN = '''\
result = _vba_lesen(d["vba"])
'''

# Weg kommt, was in der Gruppe liegt, und was waehrend der Messung neu
# entstand und GAR KEINE Gruppe hat (Restkoerper eines Schnitts). Alles
# andere Neue wird nur gemeldet — es koennte jemandem gehoeren.
AUFRAEUMEN = '''\
vorher = set(get_stored(d["merker"]) or [])
weg, fremd = [], []
for e in ec.get_all_identifiable_element_ids():
    g = ac.get_group(e)
    if g == d["gruppe"]:
        weg.append(e)
    elif vorher and e not in vorher:
        (weg if not g else fremd).append(e)
if weg:
    ec.delete_elements(weg)
result = {"geloescht": len(weg), "fremd_nicht_geloescht": fremd[:50]}
'''

MERKEN = '''\
store_as(d["merker"], [int(e) for e in ec.get_all_identifiable_element_ids()])
result = len(get_stored(d["merker"]))
'''


def auftrag(teil, daten):
    """Kopf + Teil, die Daten als JSON-Text (kommt unveraendert an)."""
    return (KOPF.replace("DATEN", repr(json.dumps(daten))) + teil)


def _orte(basis, v_nr, staebe):
    x0, y0, z0 = basis
    return [[x0, y0 + k * ABSTAND_STAB, z0 + v_nr * ABSTAND_VARIANTE]
            for k in range(staebe)]


def _anlegen_daten(args, gruppe, v_nr):
    return {"material": args.material, "dunkel": True, "gruppe": gruppe,
            "orte": _orte(args.basis, v_nr, args.staebe),
            "stab": [STAB_B, STAB_H, STAB_L],
            "blech": [BLECH_D, BLECH_H, BLECH_L],
            "ueberstand": BLECH_UEBERSTAND}


def _vba_daten(args, gruppe, staebe, bleche, schritt):
    return {"enden": schritt[1], "material_hier": schritt[2],
            "bleche": bleche, "dunkel": True, "gruppe": gruppe,
            "staebe": staebe, "stab_l": STAB_L, "vba": [VBA_D, VBA_L],
            "vba_dx": list(VBA_DX), "vba_dz": list(VBA_DZ),
            "vba_name": args.vba_name}


def plan(args):
    """Alle Auftraege der Messung mit Beispieldaten — fuer die Offline-
    Pruefung. Im echten Lauf entstehen dieselben Texte mit echten IDs."""
    gruppe = "OMCAD_Messung_PRUEFUNG"
    beispiel_stab = {"stab": 1, "holz": [1], "bleche": [2, 3],
                     "mitte": [0.0, 0.0, 0.0]}
    auftraege = [("merken", auftrag(MERKEN, {"merker": "omcad_messung_x"}))]
    for v_nr, v in enumerate(VARIANTEN):
        auftraege.append(("anlegen %s" % v["name"], auftrag(
            ANLEGEN, _anlegen_daten(args, gruppe, v_nr))))
        for schritt in v["schritte"]:
            if schritt[0] == "material":
                auftraege.append(("material %s" % v["name"], auftrag(
                    NACHZIEHEN, {"ids": [2, 3]})))
            elif schritt[0] == "vba":
                auftraege.append(("vba %s" % v["name"], auftrag(
                    VBA, _vba_daten(args, gruppe,
                                    [beispiel_stab] * args.staebe, [2, 3],
                                    schritt))))
        auftraege.append(("lesen %s" % v["name"], auftrag(
            LESEN, {"vba": list(range(10, 10 + 8 * args.staebe))})))
    auftraege.append(("aufraeumen", auftrag(AUFRAEUMEN, {
        "gruppe": gruppe, "merker": "omcad_messung_x"})))
    return auftraege


def kern_grenzen():
    """Token-Sperre und Code-Grenze aus der QUELLE des Kerns."""
    with open(KERN, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())
    return {k.targets[0].id: ast.literal_eval(k.value) for k in baum.body
            if isinstance(k, ast.Assign) and len(k.targets) == 1
            and isinstance(k.targets[0], ast.Name)
            and k.targets[0].id in ("FORBIDDEN_TOKENS", "MAX_CODE_LENGTH")}


def offline_pruefen(args, aus=print):
    """-> Liste der Befunde (leer = alles gut). Sendet nichts."""
    grenzen = kern_grenzen()
    befunde = []
    auftraege = plan(args)
    for name, code in auftraege:
        try:
            compile(code, "<%s>" % name, "exec")
        except SyntaxError as exc:
            befunde.append("%s: Syntaxfehler %s" % (name, exc))
        gesperrt = [t for t in grenzen["FORBIDDEN_TOKENS"] if t in code]
        if gesperrt:
            befunde.append("%s: blockierte Tokens %s" % (name, gesperrt))
        if len(code) > grenzen["MAX_CODE_LENGTH"]:
            befunde.append("%s: %d Zeichen > %d" % (
                name, len(code), grenzen["MAX_CODE_LENGTH"]))
    n_vba = len(VARIANTEN) * args.staebe * 2 * len(VBA_DX) * len(VBA_DZ)
    aus("Plan: %d Varianten x %d Staebe, je Stab 2 Bleche und %d VBA -> "
        "%d Staebe, %d VBA, %d Auftraege (+ %d Nachlese-Runden je Variante)"
        % (len(VARIANTEN), args.staebe, 2 * len(VBA_DX) * len(VBA_DZ),
           len(VARIANTEN) * args.staebe, n_vba, len(auftraege),
           len(NACHLESEN_S)))
    for v in VARIANTEN:
        aus("  %-8s %s" % (v["name"], v["text"]))
    aus("Offline-Pruefung: %d Auftragscodes kompiliert, Token-Sperre und "
        "Code-Grenze des Kerns: %s" % (len(auftraege),
                                       "OK" if not befunde else "FEHLER"))
    for b in befunde:
        aus("  - " + b)
    return befunde


# --- Echter Lauf (nur mit --ausfuehren) ------------------------------------

class Lauf:
    def __init__(self, args, bridge_client):
        self.args = args
        self.bc = bridge_client
        self.port = args.port
        self.gruppe = "OMCAD_Messung_%s" % time.strftime("%Y%m%d_%H%M%S")
        self.merker = "omcad_messung_%d" % int(time.time())

    def ruf(self, methode, params=None, lesend=False, timeout=120.0):
        params = dict(params or {})
        if methode == "execute_cwapi3d":
            params.setdefault("access_mode", "read" if lesend else "write")
            params["expect_document"] = self.args.dokument
        return self.bc.call(methode, params, port=self.port,
                            antwort_timeout=timeout)

    def code(self, teil, daten, beschreibung, lesend=False):
        antwort = self.ruf("execute_cwapi3d", {
            "code": auftrag(teil, daten), "result_var": "result",
            "description": "Messung Schneidwerkzeug: %s" % beschreibung},
            lesend=lesend)
        return (antwort or {}).get("result")

    def variante(self, v_nr, v):
        a = self.args
        t0 = time.monotonic()
        staebe = self.code(ANLEGEN, _anlegen_daten(a, self.gruppe, v_nr),
                           "%s anlegen" % v["name"])
        bleche = [b for s in staebe for b in s["bleche"]]
        geschnitten = sum(1 for s in staebe if s["vol_nach"] < s["vol_vor"])
        vba_bisher, vba, ablauf = [], None, []
        for schritt in v["schritte"]:
            ablauf.append([schritt[0], round(time.monotonic() - t0, 2)])
            if schritt[0] == "pause":
                time.sleep(schritt[1])
            elif schritt[0] == "material":
                ids = bleche if schritt[1] == "bleche" else vba_bisher
                # Welche Materialien es fand: ohne eines (leere Achse ohne
                # Material?) hat der Schritt nichts gesetzt — wie auch das
                # Nachziehen im Kern solche Elemente auslaesst.
                ablauf[-1].append(self.code(
                    NACHZIEHEN, {"ids": ids}, "%s Material neu (%s)"
                    % (v["name"], schritt[1])))
            else:
                vba = self.code(VBA, _vba_daten(a, self.gruppe, staebe,
                                                bleche, schritt),
                                "%s VBA" % v["name"])
                vba_bisher += [x for s in vba["je_stab"] for x in s["vba"]]
        t_vba = time.monotonic() - t0
        # Gemessen werden die VBA des LETZTEN VBA-Schritts.
        alle = [x for s in vba["je_stab"] for x in s["vba"]]
        lesungen = [{"nach_s": 0.0, "vba": vba["sofort"]}]
        start = time.monotonic()
        for warte in NACHLESEN_S:
            rest = warte - (time.monotonic() - start)
            if rest > 0:
                time.sleep(rest)
            lesungen.append({"nach_s": warte, "vba": self.code(
                LESEN, {"vba": alle}, "%s lesen %.1f s" % (v["name"], warte),
                lesend=True)})
        return {"variante": v["name"], "text": v["text"],
                "staebe": [s["stab"] for s in staebe],
                "geschnitten": geschnitten, "je_stab": vba["je_stab"],
                "ablauf_s": ablauf, "vba_ab_start_s": round(t_vba, 2),
                "lesungen": lesungen}

    def ausfuehren(self):
        bc, a = self.bc, self.args
        info = bc.call("get_document_info", {}, port=self.port)
        name = (info or {}).get("document_name", "")
        if a.dokument.lower() not in name.lower():
            raise SystemExit("Abbruch: offen ist %r, erwartet %r. Nichts "
                             "gesendet." % (name, a.dokument))
        bc.ziel_setzen(self.port)
        modus = bc.call("zeichenmodus", {})["zeichenmodus"]
        umgestellt = False
        if modus != "langsam":
            if not a.modus_umstellen:
                raise SystemExit(
                    "Abbruch: Zeichenmodus ist %r. Die Messung braucht "
                    "'Langsam' (sonst zieht der Kern selbst nach). Im Dock "
                    "umstellen oder --modus-umstellen." % modus)
            bc.call("zeichenmodus", {"modus": "langsam"})
            umgestellt = True
        ergebnis = {"dokument": name, "port": self.port,
                    "gruppe": self.gruppe, "modus_vorher": modus,
                    "vba_name": a.vba_name or "(leere Achse, Durchmesser %g)"
                    % VBA_D, "varianten": []}
        try:
            self.code(MERKEN, {"merker": self.merker}, "Bestand merken",
                      lesend=True)
            for v_nr, v in enumerate(VARIANTEN):
                if a.nur and v["name"] not in a.nur:
                    continue
                print("... %s: %s" % (v["name"], v["text"]))
                ergebnis["varianten"].append(self.variante(v_nr, v))
        finally:
            if not a.behalten:
                try:
                    ergebnis["aufraeumen"] = self.code(AUFRAEUMEN, {
                        "gruppe": self.gruppe, "merker": self.merker},
                        "aufraeumen")
                except Exception as exc:                  # noqa: BLE001
                    ergebnis["aufraeumen"] = {"fehler": str(exc)}
            if umgestellt:
                bc.call("zeichenmodus", {"modus": modus})
            bc.release_write_lease()
        return ergebnis


def zusammenfassen(ergebnis, aus=print):
    """Je Variante und Lesezeitpunkt: Staebe, deren VBA ALLE 0 Abschnitte
    haben (so sah der Befund aus), und VBA mit 0 Abschnitten insgesamt."""
    aus("\nVariante  geschnitten  " + "  ".join(
        "%5.1fs" % x["nach_s"] for x in
        (ergebnis["varianten"][0]["lesungen"] if ergebnis["varianten"]
         else [])) + "   (Staebe ohne Abschnitte / VBA mit 0)")
    for v in ergebnis["varianten"]:
        zellen = []
        for les in v["lesungen"]:
            null = {k for k, w in les["vba"].items()
                    if w.get("abschnitte") == 0}
            staebe = sum(1 for s in v["je_stab"]
                         if all(str(x) in null for x in s["vba"]))
            zellen.append("%2d/%-3d" % (staebe, len(null)))
        aus("%-9s %2d/%-2d        %s" % (v["variante"], v["geschnitten"],
                                        len(v["staebe"]), " ".join(zellen)))
    for v in ergebnis["varianten"]:
        for schritt in v.get("ablauf_s", []):
            if schritt[0] == "material" and not [
                    n for n in (schritt[2] if len(schritt) > 2 else []) if n]:
                aus("HINWEIS %s: der Material-Schritt fand kein Material, "
                    "hat also nichts neu gesetzt — die Zeile sagt nichts. "
                    "Mit einem Katalog-VBA (--vba-name) wiederholen."
                    % v["variante"])
    if "aufraeumen" in ergebnis:
        aus("Aufgeraeumt: %s" % ergebnis["aufraeumen"])


def argumente(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ausfuehren", action="store_true",
                   help="wirklich gegen Cadwork laufen (sonst nur offline)")
    p.add_argument("--port", type=int, help="Port des zugewiesenen Steckplatzes")
    p.add_argument("--dokument", help="Teil des erwarteten Dateinamens")
    p.add_argument("--material", default="Stahl",
                   help="vorhandenes Material fuer die Bleche")
    p.add_argument("--vba-name", default="",
                   help="Standard-VBA aus dem Katalog statt leerer Achse")
    p.add_argument("--staebe", type=int, default=5,
                   help="Staebe je Variante (Vorgabe 5)")
    p.add_argument("--basis", type=float, nargs=3,
                   default=(0.0, -100000.0, 0.0), metavar=("X", "Y", "Z"),
                   help="Ort der Messung, weit abseits (mm)")
    p.add_argument("--nur", nargs="*", help="nur diese Varianten")
    p.add_argument("--modus-umstellen", action="store_true",
                   help="Zeichenmodus fuer die Messung auf 'Langsam', danach "
                        "zurueck")
    p.add_argument("--behalten", action="store_true",
                   help="Testelemente NICHT loeschen (zum Ansehen)")
    p.add_argument("--ausgabe", help="Ergebnis zusaetzlich als JSON-Datei")
    return p.parse_args(argv)


def main(argv=None):
    args = argumente(sys.argv[1:] if argv is None else argv)
    befunde = offline_pruefen(args)
    if befunde:
        return 1
    if not args.ausfuehren:
        print("\nNichts gesendet (ohne --ausfuehren). Freigabe vor dem "
              "echten Lauf: ausdruecklich einholen.")
        return 0
    if not args.port or not args.dokument:
        print("--ausfuehren braucht --port und --dokument.")
        return 2
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from open_mcp_cad import bridge_client
    ergebnis = Lauf(args, bridge_client).ausfuehren()
    zusammenfassen(ergebnis)
    if args.ausgabe:
        with open(args.ausgabe, "w", encoding="utf-8") as fh:
            json.dump(ergebnis, fh, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
