#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer das Wissens-System: eingebaut oeffentlich, Fachwissen eingehaengt.

    python tests/test_wissen.py

WAS HIER GEPRUEFT WIRD
  * Das eingebaute Wissen enthaelt KEIN Fachvokabular einer Domaene.
    Das ist die Zusage dieses Repos — sie muss gemessen werden, nicht
    behauptet.
  * Ein ueber OPEN_MCP_CAD_KNOWLEDGE eingehaengter Ordner wird wirklich
    geladen, und zwar ALLE vier Sorten (Regeln, Probleme, Beispiele,
    Katalog). Dass nur DREI ankamen, ist beim Bau genau so passiert:
    `details` war als Dict angelegt, der Katalog ist eine Liste, und das
    Zusammenfuehren tat still nichts.
  * Ein Ordner, den es nicht gibt, wird gemeldet und uebersprungen — nicht
    still geschluckt.

KONTROLLE: dieses Gate baut sich seinen Fachwissens-Ordner selbst und
prueft, dass die Zahlen sich dadurch AENDERN. Ohne diesen Vergleich saehe
ein Mechanismus, der gar nichts einhaengt, wie ein bestandener Test aus.
"""
import ast
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
SERVER = os.path.join(REPO, "open_mcp_cad", "server.py")

_ergebnisse = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if not bedingung:
        print("  [FEHL] %s%s" % (titel, ("  -- %s" % detail) if detail else ""))
    return bool(bedingung)


def wissensteil():
    """Laedt NUR den Wissens-Teil von server.py — ohne mcp/fastmcp."""
    quelle = io.open(SERVER, encoding="utf-8").read()
    a = quelle.index("KNOWLEDGE_DIR = Path(__file__).parent")
    e = quelle.index("KNOWLEDGE = load_knowledge()")
    raum = {"os": os, "sys": sys, "json": json, "Path": Path,
            "__file__": SERVER}
    exec(compile(quelle[a:e], "<wissen>", "exec"), raum)
    return raum["load_knowledge"]


# Vokabular, das im OEFFENTLICHEN Teil nichts zu suchen hat.
FACHWORTE = ("kerto", "weichfaser", "innenecke", "aussenecke", "kopfschwelle",
             "deckenauflager", "staenderlasche", "holzrahmenbau")


# --- Wissen 2026-09-27: Schema, Nachweis, Suche, Regression ---------------
#
# Anlass: die Kurven-/Raumkoerper-/Achsen-/Endtyp-/VBA-Messungen vom
# 26./27.09. kamen ueber den Export hinzu, und get_working_examples sucht
# seitdem ueber open_mcp_cad/wissen.py (auch in bekannten Problemen).

KERN = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")
KLASSEN = ("nativ_gemessen", "offline_geprueft", "nutzerbeobachtung",
           "offene_grenze")
DATEN_2026_09_26_27 = re.compile(r"2026-09-2[67]")
PRIVATER_PFAD = re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}(?!Public)",
                           re.I)
GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-")

# Suchbegriff -> Eintrag, der gefunden werden MUSS (Auftrag 2026-09-27).
SUCHE = (
    ("bogen", "kurve_kreisbogen_zylinder_boolean"),
    ("welle", "kurve_ebene_spline_kontur_extrusion"),
    ("s-kurve spline", "kurve_ebene_spline_kontur_extrusion"),
    ("raumstab", "raumstab_vier_eckkurven_sechs_flaechen"),
    ("helix", "raumstab_vier_eckkurven_sechs_flaechen"),
    ("convert_surfaces_to_volume", "raumstab_vier_eckkurven_sechs_flaechen"),
    ("zylinder platte", "zylinderplatte_konstanter_radialer_abstand"),
    ("sehne", "lokale_achse_sehne_huellmass"),
    ("huellmass", "lokale_achse_sehne_huellmass"),
    ("vba katalog", "vba_katalog_blank_bestuecken_zuruecklesen"),
    ("create_blank_connector", "vba_katalog_blank_bestuecken_zuruecklesen"),
    ("3dc", "standardprofil_und_3dc_katalog"),
    ("standardprofil", "standardprofil_und_3dc_katalog"),
    ("faser", "nurbs_kein_faserfeld_keine_sweep_historie"),
    ("sweep", "nurbs_kein_faserfeld_keine_sweep_historie"),
    ("is_beam", "is_beam_kein_rohling_nachweis"),
    ("normaldicke", "normalversatz_randkurven_keine_konstante_dicke"),
    ("step", "step_leer_sat_alternative"),
    ("viewer endtyp", "endtyp_materialisierung_nicht_in_rohkoerper_gettern"),
    ("kontakt vba", "vba_kontakt_id_und_volumen_getter_unzuverlaessig"),
    ("cutter", "temporaere_cutter_veraendern_vba_auswertung"),
    ("timeout schnitt", "schnitte_vor_verbindern_kein_resend"),
    ("subtract rueckgabe", "subtract_leere_rueckgabe_trotzdem_geschnitten"),
    ("export_3d_file", "export_3d_file_rueckgabe_falsch"),
)

# Die VBA-/Endtyp-Eintraege vom 2026-09-25 duerfen sich nur BEWUSST
# aendern: Hash ueber den ganzen Eintrag (sortiertes JSON). Wer einen davon
# absichtlich aendert, traegt hier den neuen Hash ein.
VBA_PINS = {
    "vba_standard_anlegen": "79383e49d4a1aedc",
    "vba_blech_ignore_in_vba_calculation": "499b7ecb914f7fab",
    "blech_nut_per_subtract_dann_vba": "900752dbc83f9cef",
    # 2026-10-01 bewusst: Verweis auf einen nicht mehr eingebauten Eintrag
    # ersetzt.
    "endtyp_per_name_setzen": "0c81fbb7269654c9",
    "vba_blech_in_endtyp_nut_ungueltig": "a4d675a7fdc3c731",
    "vba_update_cutting_ability_nach_stahl": "0b18436081dcee2a",
    "physisches_volumen_ohne_endtyp_nut": "ae26cb206b2ccb63",
    "subtract_blech_mit_vba_blockiert": "64d2172a686be83b",
}


def _pin(eintrag):
    roh = json.dumps(eintrag, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


def _verbotene_tokens():
    """FORBIDDEN_TOKENS aus dem KERN-Quelltext (nicht aus einer Liste hier)."""
    baum = ast.parse(io.open(KERN, encoding="utf-8").read())
    for knoten in baum.body:
        if (isinstance(knoten, ast.Assign)
                and any(getattr(z, "id", "") == "FORBIDDEN_TOKENS"
                        for z in knoten.targets)):
            return tuple(ast.literal_eval(knoten.value))
    return ()


def _nachweis_fehler(e):
    """Fehlerliste fuer das Feld `nachweis` eines Eintrags."""
    n = e.get("nachweis")
    if not isinstance(n, dict):
        return ["kein nachweis"]
    f = []
    if n.get("klasse") not in KLASSEN:
        f.append("klasse %r" % n.get("klasse"))
    if not str(n.get("cadwork", "")).strip():
        f.append("cadwork fehlt")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(n.get("stand", ""))):
        f.append("stand %r" % n.get("stand"))
    if n.get("klasse") == "nativ_gemessen" and not n.get("alter_versuch"):
        f.append("nativ_gemessen ohne alter_versuch")
    if "code" in e and "minimalbeispiel" not in n:
        f.append("Beispiel ohne minimalbeispiel-Status")
    return f


def _code_fehler(code):
    """Feste IDs, Ports, GUIDs, private Pfade im Beispielcode."""
    f = []
    for k in ast.walk(ast.parse(code)):
        if (isinstance(k, ast.Constant) and isinstance(k.value, int)
                and not isinstance(k.value, bool)):
            if k.value >= 100000:
                f.append("Element-ID? %d" % k.value)
            elif 53127 <= k.value <= 53199:
                f.append("Port %d" % k.value)
    if GUID.search(code):
        f.append("GUID-Konstante")
    if PRIVATER_PFAD.search(code):
        f.append("privater Pfad")
    return f


def neues_wissen(k, n_bsp):
    sys.path.insert(0, REPO)
    from open_mcp_cad import wissen

    print("--- 6. Schema, Code, Nachweis ---")
    dateien = {}
    for name, schl in (("working_examples.json", "examples"),
                       ("known_issues.json", "issues")):
        try:
            dateien[schl] = json.load(io.open(
                os.path.join(REPO, "open_mcp_cad", "knowledge", name),
                encoding="utf-8"))[schl]
        except Exception as exc:  # noqa: BLE001 - jeder Fehler ist rot
            dateien[schl] = []
            pruefe("W17 %s ist gueltiges JSON" % name, False, repr(exc))
    bsp, iss = dateien["examples"], dateien["issues"]
    pruefe("W17 beide JSON gueltig, Listen von Eintraegen mit id",
           bsp and iss and all(isinstance(e, dict) and isinstance(
               e.get("id"), str) for e in bsp + iss))
    ids = [e.get("id") for e in bsp + iss]
    doppelt = sorted({i for i in ids if ids.count(i) > 1})
    pruefe("W18 ids eindeutig (in und zwischen beiden Dateien)", not doppelt,
           ", ".join(doppelt))

    syntax = []
    for e in bsp:
        try:
            ast.parse(e.get("code", ""), filename=e["id"])
        except SyntaxError as exc:
            syntax.append("%s: %s" % (e["id"], exc))
    pruefe("W19 jeder Beispielcode ist gueltiges Python", not syntax,
           "; ".join(syntax[:3]))
    try:
        ast.parse("x = (1,\n")
        k19 = False
    except SyntaxError:
        k19 = True
    pruefe("W19-K KONTROLLE: kaputter Code wird erkannt", k19)

    tokens = _verbotene_tokens()
    blockiert = ["%s: %s" % (e["id"], t) for e in bsp for t in tokens
                 if t in e.get("code", "")]
    pruefe("W20 kein Beispiel nutzt ein vom Kern blockiertes Token",
           tokens and not blockiert,
           "Tokens=%d; %s" % (len(tokens), "; ".join(blockiert[:3])))
    pruefe("W20-K KONTROLLE: Tokenliste aus dem Kern greift",
           tokens and any(t in "import os\n" for t in tokens))

    pflicht = [e for e in bsp + iss
               if DATEN_2026_09_26_27.search(str(e.get("source", "")))]
    nachweis = ["%s: %s" % (e["id"], ", ".join(_nachweis_fehler(e)))
                for e in bsp + iss
                if (e in pflicht or "nachweis" in e) and _nachweis_fehler(e)]
    pruefe("W21 Eintraege vom 26./27.09. tragen einen gueltigen nachweis",
           # 17 seit 2026-10-02: ein Eintrag dieser Tage ist seitdem privat
           # und wird nicht mehr exportiert.
           len(pflicht) >= 17 and not nachweis,
           "%d Pflicht; %s" % (len(pflicht), "; ".join(nachweis[:3])))
    falsch = dict(pflicht[0], nachweis=dict(pflicht[0]["nachweis"],
                                            klasse="bestaetigt"))
    pruefe("W21-K KONTROLLE: unbekannte klasse wird abgewiesen",
           bool(_nachweis_fehler(falsch)))

    codefehler = ["%s: %s" % (e["id"], ", ".join(_code_fehler(e["code"])))
                  for e in bsp if "nachweis" in e and _code_fehler(e["code"])]
    privat = [e["id"] for e in bsp + iss
              if PRIVATER_PFAD.search(json.dumps(e, ensure_ascii=False))]
    pruefe("W22 neue Beispiele ohne feste IDs/Ports/GUIDs, nirgends private "
           "Pfade", not codefehler and not privat,
           "; ".join(codefehler[:3] + privat[:3]))
    pruefe("W22-K KONTROLLE: feste ID, Port und GUID werden erkannt",
           len(_code_fehler("a = 674740\nb = 53128\nc = '{5AE383DA-F134-"
                            "468E-A26E-06880523F9C5}'\n")) == 3)

    print("--- 7. Suche ueber get_working_examples ---")

    def ids_fuer(wissen_k, begriff):
        r = json.loads(wissen.beispiele_antwort(wissen_k, begriff))
        return [] if isinstance(r, dict) else [e.get("id") for e in r]

    fehlt = ["%r -> %s" % (b, soll) for b, soll in SUCHE
             if soll not in ids_fuer(k, b)]
    pruefe("W23 %d Suchbegriffe finden ihren Eintrag" % len(SUCHE), not fehlt,
           "; ".join(fehlt[:4]))
    r = json.loads(wissen.beispiele_antwort(k, "raumstab"))
    pruefe("W24 Treffer tragen nachweis (klasse) mit, Probleme mit art",
           isinstance(r, list) and all(e.get("nachweis", {}).get("klasse")
                                       in KLASSEN for e in r)
           and all(e.get("art") == "bekanntes_problem" for e in json.loads(
               wissen.beispiele_antwort(k, "cutter"))))

    neu = {soll for _, soll in SUCHE}
    zapfen = set(ids_fuer(k, "zapfen")) & neu
    leer = json.loads(wissen.beispiele_antwort(k, ""))
    pruefe("W25 Negativfaelle: 'zapfen' findet keinen neuen Eintrag, "
           "Unsinn liefert error, leer = nur alle Beispiele",
           not zapfen
           and "error" in json.loads(wissen.beispiele_antwort(k, "xyzzy"))
           and len(leer) == n_bsp and not any("art" in e for e in leer),
           "zapfen=%s leer=%d/%d" % (sorted(zapfen), len(leer), n_bsp))

    ohne = dict(k, examples={"examples": [e for e in bsp if e["id"] not in neu]},
                issues=[e for e in iss if e["id"] not in neu])
    noch = ["%r" % b for b, soll in SUCHE if soll in ids_fuer(ohne, b)]
    pruefe("W26 KONTROLLE: ohne die neuen Eintraege findet keiner der "
           "Begriffe sie", not noch, "; ".join(noch[:3]))

    alle = {e["id"]: e for e in bsp + iss}
    pins = ["%s: %s" % (i, "fehlt" if i not in alle else _pin(alle[i]))
            for i, h in VBA_PINS.items()
            if i not in alle or _pin(alle[i]) != h]
    vba = ids_fuer(k, "vba")
    pruefe("W27 bisherige VBA-/Endtyp-Eintraege unveraendert und weiter "
           "auffindbar", not pins and {"vba_standard_anlegen",
                                       "blech_nut_per_subtract_dann_vba",
                                       "vba_katalog_blank_bestuecken_zuruecklesen"}
           <= set(vba), "; ".join(pins[:3]))
    pruefe("W27-K KONTROLLE: eine Aenderung an einem VBA-Eintrag faellt auf",
           _pin(dict(alle["vba_standard_anlegen"], notes="x"))
           != VBA_PINS["vba_standard_anlegen"])

    summary = k.get("issues_summary") or ""
    hoch = [e for e in iss if e["id"] in neu
            and e.get("severity") in ("high", "medium")]
    alt = alle.get("bridge_exec_scope_no_locals_in_functions", {})
    pruefe("W28 neue high/medium-Grenzen stehen in der Beschreibung von "
           "execute; die alte Scope-Warnung nicht mehr",
           hoch and all(e["title"] in summary for e in hoch)
           and alt.get("severity") == "low"
           and "Code FLACH schreiben" not in summary,
           "%d neue high/medium" % len(hoch))

    # Mit mcp: das echte Werkzeug liefert dasselbe wie das Modul.
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("  (mcp fehlt: W29 uebersprungen)")
        return
    from open_mcp_cad import server
    pruefe("W29 server.get_working_examples == wissen.beispiele_antwort",
           server.get_working_examples("raumstab")
           == wissen.beispiele_antwort(server.KNOWLEDGE, "raumstab"))


# --- API-Hilfe ohne Stubs (Rueckmeldung 2026-09-28) ------------------------
#
# Im Server-Env fehlte das Paket cwapi3d; get_cadwork_api_help sagte fuer
# element_controller "stub_not_found", und der Agent hielt das Modul fuer
# falsch. Gemessen wird in einem Kind-Python mit -S (ohne site-packages):
# so ist "ohne Paket" unabhaengig davon, was in diesem Python installiert
# ist, und "mit Paket" ist eine Attrappe im Aufbau des echten cwapi3d
# 32.443.10 (Distribution cwapi3d, Modulordner nur mit __init__.pyi).

_API_KIND = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
if sys.argv[2]:
    sys.path.insert(0, sys.argv[2])
from open_mcp_cad import api_hilfe as H
if sys.argv[3] == "alt":
    # Stand vor 2026-09-28: das Paket galt nie als fehlend.
    H.stubs_installiert = lambda: True
mods = ("element_controller", "roof_controller")
aus = {m: H.hilfe(m, "", mods, {"ec": "element_controller"}) for m in mods}
aus["funktion"] = H.hilfe("element_controller", "neu_balken", mods, {})
aus["uebersicht"] = H.hilfe("", "", mods, {})
print(json.dumps(aus))
"""


def _api_kind(pfad="", art="neu"):
    import subprocess
    r = subprocess.run([sys.executable, "-S", "-c", _API_KIND, REPO, pfad,
                        art], capture_output=True, timeout=60)
    try:
        return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except Exception:                                     # noqa: BLE001
        return {"_fehler": (r.stdout + r.stderr).decode("utf-8", "replace")}


def api_hilfe_gate():
    print("--- API-Hilfe: Stubs fehlen vs. Modul fehlt ---")
    ohne = _api_kind()
    em = ohne.get("element_controller", {})
    pruefe("W30 ohne Paket cwapi3d: error stubs_fehlen mit pip-Hinweis, "
           "sagt, dass das Modul nicht falsch ist",
           em.get("error") == "stubs_fehlen"
           and "pip install cwapi3d" in em.get("hint", "")
           and "[stubs]" in em.get("hint", "")
           and "nicht falsch" in em.get("message", ""), ohne)
    pruefe("W30b ohne Paket: die Uebersicht sagt es auch (stubs: fehlen)",
           ohne.get("uebersicht", {}).get("stubs") == "fehlen"
           and ohne.get("uebersicht", {}).get("ok") is True, ohne)
    alt = _api_kind(art="alt")
    pruefe("W30-K KONTROLLE: mit der alten Logik hiess es stub_not_found",
           alt.get("element_controller", {}).get("error")
           == "stub_not_found", alt)

    tmp = tempfile.mkdtemp(prefix="omcad_stubs_")
    try:
        dist = os.path.join(tmp, "cwapi3d-9.9.9.dist-info")
        os.makedirs(dist)
        io.open(os.path.join(dist, "METADATA"), "w", encoding="utf-8").write(
            "Metadata-Version: 2.1\nName: cwapi3d\nVersion: 9.9.9\n")
        mod = os.path.join(tmp, "element_controller")
        os.makedirs(mod)
        io.open(os.path.join(mod, "__init__.pyi"), "w",
                encoding="utf-8").write(
            "def neu_balken(breite: float) -> int:\n"
            "    \"\"\"Legt einen Balken an.\n\n    Lang.\"\"\"\n")
        io.open(os.path.join(mod, "py.typed"), "w").write("")
        mit = _api_kind(tmp)
        em = mit.get("element_controller", {})
        pruefe("W31 mit Paket: Funktionen aus der .pyi, keine Warnung in der "
               "Uebersicht",
               em.get("ok") is True
               and [f["name"] for f in em.get("functions", [])]
               == ["neu_balken"]
               and "stubs" not in mit.get("uebersicht", {}), mit)
        fn = mit.get("funktion", {})
        pruefe("W31b mit Paket: volle Doku einer Funktion",
               fn.get("ok") is True
               and fn.get("signature") == "(breite: float) -> int"
               and "Lang." in fn.get("docstring", ""), fn)
        pruefe("W32 Paket da, Modul fehlt darin: weiter stub_not_found "
               "(nicht stubs_fehlen)",
               mit.get("roof_controller", {}).get("error")
               == "stub_not_found", mit.get("roof_controller"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        import mcp  # noqa: F401
    except ImportError:
        print("  (mcp fehlt: W33 uebersprungen)")
        return
    from open_mcp_cad import server, api_hilfe
    echt = server.get_cadwork_api_help("element_controller")
    erwartet = api_hilfe.hilfe("element_controller", "",
                               server.CWAPI3D_MODULES,
                               server.CWAPI3D_ALIASES)
    pruefe("W33 server.get_cadwork_api_help == api_hilfe.hilfe (%s)"
           % ("Paket da" if api_hilfe.stubs_installiert()
              else "Paket fehlt: stubs_fehlen"),
           echt == erwartet
           and (api_hilfe.stubs_installiert()
                or echt.get("error") == "stubs_fehlen"), echt)


def main():
    print("Open MCP CAD - Wissens-Gate\n")
    lade = wissensteil()
    os.environ.pop("OPEN_MCP_CAD_KNOWLEDGE", None)

    # --- 1. Das eingebaute Wissen ist frei von Fachvokabular --------------
    print("--- 1. Eingebautes Wissen ist domaenenfrei ---")
    eingebaut = Path(REPO) / "open_mcp_cad" / "knowledge"
    pruefe("W1 der Ordner existiert", eingebaut.is_dir(), str(eingebaut))
    treffer = []
    for p in sorted(eingebaut.glob("*")):
        text = io.open(p, encoding="utf-8", errors="ignore").read().lower()
        for wort in FACHWORTE:
            if wort in text:
                treffer.append("%s: %s (%dx)" % (p.name, wort, text.count(wort)))
    pruefe("W2 kein Fachvokabular im eingebauten Wissen", not treffer,
           "; ".join(treffer[:4]))
    # Regeldateien nach der Regel des Laders (rules.md oder *_rules.md),
    # nicht nach einem festen Domaenennamen.
    verboten = sorted(p.name for p in eingebaut.iterdir()
                      if p.name in ("detail_catalog.json", "rules.md")
                      or p.name.endswith("_rules.md"))
    pruefe("W3 kein Detail-Katalog, keine Domaenen-Regeln", not verboten,
           ", ".join(verboten))

    ohne = lade()
    n_iss = len(ohne.get("issues", []))
    n_bsp = len(ohne.get("examples", {}).get("examples", []))
    pruefe("W4 eingebautes Wissen ist nicht leer", n_iss > 0 and n_bsp > 0,
           "issues=%d examples=%d" % (n_iss, n_bsp))
    pruefe("W5 ohne Einhaengen gibt es keine Domaenen-Regeln",
           not ohne.get("rules") and not ohne.get("details"))

    # --- 2. Einhaengen wirkt, und zwar in allen vier Sorten ---------------
    print("--- 2. Fachwissen einhaengen ---")
    tmp = tempfile.mkdtemp(prefix="omcad_wissen_")
    try:
        io.open(os.path.join(tmp, "rules.md"), "w", encoding="utf-8").write(
            "# Testregeln\nEine Regel aus dem Fachwissens-Ordner.\n")
        json.dump({"issues": [{"id": "t1", "severity": "high",
                               "title": "Testproblem", "workaround": "Weg A"}]},
                  io.open(os.path.join(tmp, "known_issues.json"), "w",
                          encoding="utf-8"))
        json.dump({"examples": [{"id": "e1", "code": "pass"}]},
                  io.open(os.path.join(tmp, "working_examples.json"), "w",
                          encoding="utf-8"))
        json.dump({"details": [{"id": "d1", "type": "test", "variant": "a"}]},
                  io.open(os.path.join(tmp, "detail_catalog.json"), "w",
                          encoding="utf-8"))

        os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = tmp
        mit = lade()

        pruefe("W6 Regeln kommen an", "Testregeln" in (mit.get("rules") or ""))
        pruefe("W7 Probleme werden ANGEHAENGT, nicht ersetzt",
               len(mit.get("issues", [])) == n_iss + 1,
               "%d statt %d" % (len(mit.get("issues", [])), n_iss + 1))
        pruefe("W8 Beispiele werden angehaengt",
               len(mit.get("examples", {}).get("examples", [])) == n_bsp + 1)
        # Genau hier war der stille Fehler.
        pruefe("W9 der Detail-Katalog kommt an",
               len(mit.get("details", {}).get("details", [])) == 1,
               "als Liste zusammenfuehren, nicht als Dict")
        pruefe("W10 das Testproblem steht in der Zusammenfassung",
               "Testproblem" in (mit.get("issues_summary") or ""))
        pruefe("W11 beide Quellen werden genannt", len(mit["quellen"]) == 2)

        # KONTROLLE: ohne das Einhaengen darf nichts davon da sein.
        os.environ.pop("OPEN_MCP_CAD_KNOWLEDGE", None)
        kontrolle = lade()
        pruefe("W12 KONTROLLE: ohne Einhaengen fehlt all das",
               "Testregeln" not in (kontrolle.get("rules") or "")
               and len(kontrolle.get("issues", [])) == n_iss
               and not kontrolle.get("details"),
               "sonst misst W6-W9 gar nicht das Einhaengen")

        # --- 3. Tippfehler im Pfad ---------------------------------------
        print("--- 3. Ordner, den es nicht gibt ---")
        os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = os.path.join(tmp, "gibt_es_nicht")
        k3 = lade()
        pruefe("W13 fehlender Ordner wird uebersprungen",
               len(k3["quellen"]) == 1)

        # --- 3b. Regeldatei nach der Domaene benannt (2026-09-28) --------
        # Vorher stand im Lader ein fester Domaenenname als zweite Wahl.
        # Jetzt: rules.md, sonst jede <domaene>_rules.md des Ordners.
        print("--- 3b. <domaene>_rules.md ---")
        tmp3 = tempfile.mkdtemp(prefix="omcad_wissen3_")
        try:
            for name, text in (("b_rules.md", "Regel Zwei"),
                               ("a_rules.md", "Regel Eins"),
                               ("rules_alt.md", "Regel Fremd")):
                io.open(os.path.join(tmp3, name), "w",
                        encoding="utf-8").write(text + "\n")
            os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = tmp3
            r3 = lade().get("rules") or ""
            pruefe("W34 ohne rules.md gelten alle *_rules.md, alphabetisch",
                   r3 == "Regel Eins\n\nRegel Zwei", repr(r3[:80]))
            pruefe("W34-K KONTROLLE: eine Datei ausserhalb des Musters "
                   "(rules_alt.md) zaehlt nicht", "Fremd" not in r3,
                   repr(r3[:80]))
            io.open(os.path.join(tmp3, "rules.md"), "w",
                    encoding="utf-8").write("Regel Haupt\n")
            r3b = lade().get("rules") or ""
            pruefe("W34b rules.md geht vor, die *_rules.md fallen dann weg",
                   r3b == "Regel Haupt", repr(r3b[:80]))
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)

        # --- 4. Mehrere Ordner -------------------------------------------
        tmp2 = tempfile.mkdtemp(prefix="omcad_wissen2_")
        try:
            json.dump({"issues": [{"id": "t2", "severity": "high",
                                   "title": "Zweites", "workaround": "Weg B"}]},
                      io.open(os.path.join(tmp2, "known_issues.json"), "w",
                              encoding="utf-8"))
            os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = tmp + os.pathsep + tmp2
            k4 = lade()
            pruefe("W14 mehrere Ordner werden zusammengefuehrt",
                   len(k4.get("issues", [])) == n_iss + 2
                   and len(k4["quellen"]) == 3)
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        # --- 5. Gleiche id: ersetzen statt verdoppeln --------------------
        # Das private Fachwissen ist die Quelle des eingebauten; eingehaengt
        # stand vorher jeder exportierte Eintrag doppelt da.
        print("--- 5. Gleiche id ---")
        erster = ohne["issues"][0]
        tmp3 = tempfile.mkdtemp(prefix="omcad_wissen3_")
        try:
            quelle = dict(erster, scope="api", workaround="Weg aus der QUELLE")
            json.dump({"issues": [quelle,
                                  {"id": "neu_x", "severity": "low",
                                   "title": "Neu", "workaround": "-"},
                                  {"severity": "low", "title": "ohne id"}]},
                      io.open(os.path.join(tmp3, "known_issues.json"), "w",
                              encoding="utf-8"))
            os.environ["OPEN_MCP_CAD_KNOWLEDGE"] = tmp3
            k5 = lade()
            gleich = [i for i in k5["issues"] if i.get("id") == erster["id"]]
            pruefe("W15 gleiche id wird ERSETZT, nicht verdoppelt",
                   len(gleich) == 1
                   and gleich[0].get("workaround") == "Weg aus der QUELLE"
                   and k5["issues"][0] is gleich[0]
                   and k5.get("ersetzt_nach_id") == 1,
                   "%d Eintraege mit id %r, ersetzt=%r"
                   % (len(gleich), erster["id"], k5.get("ersetzt_nach_id")))
            pruefe("W16 KONTROLLE: neue id und Eintraege OHNE id kommen dazu",
                   len(k5["issues"]) == n_iss + 2,
                   "%d statt %d" % (len(k5["issues"]), n_iss + 2))
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)
    finally:
        os.environ.pop("OPEN_MCP_CAD_KNOWLEDGE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    neues_wissen(lade(), n_bsp)
    api_hilfe_gate()

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
