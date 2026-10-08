"""MCP Server für Cadwork 3D Holzbau.

Vier Tools:
  - get_document_info: schneller Status-Check (Dokumentname + Element-Anzahl)
  - execute_cadwork_command: führt cwapi3d-Python-Code in Cadwork aus
  - get_cadwork_api_help: listet verfügbare Module/Funktionen aus den
    Type-Stubs (.pyi) — funktioniert auch ohne laufendes Cadwork.
  - get_working_examples: verifizierte Code-Beispiele aus knowledge/.

Beim Start lädt der Server Wissens-Dateien aus knowledge/ (Regeln, bekannte
Probleme, Beispiele) und bettet sie in die Tool-Beschreibungen ein.

Architektur: Tool-Calls, die echte cwapi3d-Funktionen brauchen, werden
über bridge_client an das McpBridge-Plugin in Cadwork delegiert.
"""

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import (api_hilfe, auftraege, bootstrap, bridge_client, erfahrungen,
               erweiterungen, wissen)

# MCP Server initialisieren
mcp = FastMCP("open-mcp-cad")

# Multi-Bridge-Verwechslungs-Schutz (optional): Ist OPEN_MCP_CAD_EXPECT_DOC
# gesetzt, prüft execute_cadwork_command vor jeder Ausführung, ob der in
# Cadwork geöffnete Dokumentname diesen Teilstring (case-insensitiv) enthält.
# Passt er nicht, wird NICHT ausgeführt — so landet Code nicht versehentlich
# in der falschen Instanz/Datei. Leer = Schutz aus (Default).
EXPECT_DOC = os.environ.get("OPEN_MCP_CAD_EXPECT_DOC", "").strip()


# --- Wissens-System -------------------------------------------------------
#
# ZWEI EBENEN, bewusst getrennt:
#
#   1. Das EINGEBAUTE Wissen in `open_mcp_cad/knowledge/` handelt
#      ausschliesslich von der cwapi3d-Schnittstelle und der Bruecke —
#      Stolperfallen, die jedem begegnen, der cwapi3d benutzt. Es ist Teil
#      dieses Pakets und oeffentlich.
#
#   2. FACHWISSEN einer Domaene (Holzrahmenbau, Stahlbau, Treppenbau …)
#      gehoert NICHT hierher. Es kommt aus einem oder mehreren eigenen
#      Ordnern, die der Nutzer ueber die Umgebungsvariable
#      OPEN_MCP_CAD_KNOWLEDGE einhaengt (mehrere durch das Trennzeichen des
#      Systems getrennt; unter Windows das Semikolon).
#
# Ein Fachwissens-Ordner darf enthalten:
#      rules.md              Regeln, die JEDEM Auftrag mitgegeben werden.
#                            Kurz halten — sie kosten bei jedem Aufruf Tokens.
#                            Fehlt rules.md, gelten alle `*_rules.md` des
#                            Ordners (alphabetisch), z. B. `<domaene>_rules.md`.
#      known_issues.json     {"issues":   [ … ]}  wird angehaengt
#      working_examples.json {"examples": [ … ]}  wird angehaengt
#      detail_catalog.json   {"details":  [ … ]}  wird angehaengt
#
# Fehlt eine Datei oder ein ganzer Ordner, laeuft der Server weiter — aber
# ein ANGEGEBENER Ordner, den es nicht gibt, ist ein Tippfehler und wird
# gemeldet. Stilles Ignorieren waere hier das Schlechteste: man merkt
# monatelang nicht, dass die eigenen Regeln nie ankamen.

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def _fachwissen_ordner() -> list:
    """Die ueber OPEN_MCP_CAD_KNOWLEDGE eingehaengten Ordner."""
    roh = os.environ.get("OPEN_MCP_CAD_KNOWLEDGE", "")
    ordner = []
    for teil in roh.split(os.pathsep):
        teil = teil.strip().strip('"')
        if not teil:
            continue
        pfad = Path(teil)
        if pfad.is_dir():
            ordner.append(pfad)
        else:
            print("[open-mcp-cad] OPEN_MCP_CAD_KNOWLEDGE: Ordner nicht "
                  "gefunden, wird uebersprungen: %s" % pfad, file=sys.stderr)
    return ordner


def _lies_json(pfad, schluessel, behaelter, ersetzt=None):
    """Fuehrt die Eintraege aus `pfad` in `behaelter` zusammen.

    Listen: ein Eintrag mit einer `id`, die schon da ist, ERSETZT den
    vorhandenen an dessen Stelle — der spaeter geladene Ordner gewinnt.
    Der Anlass: das private Fachwissen ist die QUELLE, aus der das
    eingebaute exportiert wird (Feld `scope: "api"`). Haengt man es ein,
    stand vorher jeder dieser Eintraege doppelt da (gemessen 2026-09-22:
    33 Probleme, 23 Beispiele, nur im Feld `scope` verschieden). Ohne
    `id` wird angehaengt wie bisher. `ersetzt` zaehlt die Ersetzungen.
    """
    if not pfad.exists():
        return behaelter
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    teil = daten.get(schluessel)
    if isinstance(behaelter, list) and isinstance(teil, list):
        stelle = {e.get("id"): i for i, e in enumerate(behaelter)
                  if isinstance(e, dict) and e.get("id") is not None}
        for eintrag in teil:
            eid = eintrag.get("id") if isinstance(eintrag, dict) else None
            if eid is not None and eid in stelle:
                behaelter[stelle[eid]] = eintrag
                if ersetzt is not None:
                    ersetzt.append(eid)
            else:
                if eid is not None:
                    stelle[eid] = len(behaelter)
                behaelter.append(eintrag)
    elif isinstance(behaelter, dict) and isinstance(teil, dict):
        behaelter.update(teil)
    return behaelter


def load_knowledge() -> dict:
    """Laedt eingebautes Wissen plus alle eingehaengten Fachwissens-Ordner."""
    knowledge = {}
    ordner = [KNOWLEDGE_DIR] + _fachwissen_ordner()

    # `details` ist eine LISTE (server.py liest sie als solche). Als Dict
    # angelegt fuehrte `_lies_json` sie stillschweigend NICHT zusammen —
    # gefunden, weil die Probe den Katalog gezaehlt hat statt ihn
    # anzunehmen.
    regeln, issues, beispiele, details = [], [], [], []
    ersetzt = []
    for ord_ in ordner:
        # rules.md, sonst jede `<domaene>_rules.md` (ein Fachwissens-Ordner
        # darf seine Regeldatei nach der Domaene benennen; vorher stand hier
        # ein fester Domaenenname, jetzt die Regel).
        haupt = ord_ / "rules.md"
        for p in ([haupt] if haupt.is_file()
                  else sorted(ord_.glob("*_rules.md"))):
            if p.is_file():
                regeln.append(p.read_text(encoding="utf-8").strip())
        _lies_json(ord_ / "known_issues.json", "issues", issues, ersetzt)
        _lies_json(ord_ / "working_examples.json", "examples", beispiele,
                   ersetzt)
        _lies_json(ord_ / "detail_catalog.json", "details", details, ersetzt)

    if regeln:
        knowledge["rules"] = "\n\n".join(regeln)
    if issues:
        zeilen = []
        for issue in issues:
            if issue.get("severity") in ("high", "medium"):
                erste = (issue.get("workaround") or "").split("\n", 1)[0]
                zeilen.append("- %s: %s" % (issue.get("title", "?"), erste))
        knowledge["issues_summary"] = "\n".join(zeilen)
        knowledge["issues"] = issues
    if beispiele:
        knowledge["examples"] = {"examples": beispiele}
    if details:
        knowledge["details"] = {"details": details}

    knowledge["quellen"] = [str(o) for o in ordner]
    knowledge["ersetzt_nach_id"] = len(ersetzt)
    return knowledge


KNOWLEDGE = load_knowledge()


# Bekannte cwapi3d-Module — synchron mit McpBridge.py halten.
CWAPI3D_MODULES = (
    "attribute_controller",
    "bim_controller",
    "connector_axis_controller",
    "dimension_controller",
    "element_controller",
    "endtype_controller",
    "file_controller",
    "geometry_controller",
    "list_controller",
    "machine_controller",
    "material_controller",
    "menu_controller",
    "multi_layer_cover_controller",
    "roof_controller",
    "scene_controller",
    "shop_drawing_controller",
    "utility_controller",
    "visualization_controller",
)

# Aliase, die in execute_cadwork_command-Snippets verfügbar sind.
CWAPI3D_ALIASES = {
    "ec": "element_controller",
    "uc": "utility_controller",
    "ac": "attribute_controller",
    "gc": "geometry_controller",
    "fc": "file_controller",
    "vc": "visualization_controller",
    "mc": "material_controller",
    "bc": "bim_controller",
    "sc": "scene_controller",
    "lc": "list_controller",
    "cw": "cadwork",
}


# --- Erfahrungen (Lernen aus Fehlern, Stufe 1, nur lokal) ----------------
#
# Logik mcp-frei in `erfahrungen.py` (Gate tests/test_erfahrungen.py). Der
# Beobachter sieht jede Antwort von execute_cadwork_command/_batch: ein
# Fehler, den der Code in Cadwork warf, und ein spaeterer Erfolg derselben
# Art werden zu einer Erfahrung in einer Datei auf DIESEM Rechner. Die
# Versionen fragt er ueber `status` (Steuermethode, ohne Hauptthread), nur
# nach einem solchen Fehler. `bridge_client.call` wird erst beim Aufruf
# nachgeschlagen, damit Gates es ersetzen koennen.

def _bekannte_dokumente() -> list:
    """Dokumentnamen, die aus gespeicherten Texten heraus muessen."""
    namen = [EXPECT_DOC] if EXPECT_DOC else []
    try:
        from . import registry
        namen += [e.get("dokument") or "" for e in registry.laufende()]
    except Exception:                                   # noqa: BLE001
        pass
    return [n for n in namen if n]


ERFAHRUNGEN = erfahrungen.Beobachter(
    rufen=lambda *a, **k: bridge_client.call(*a, **k),
    dokumente=_bekannte_dokumente)


# --- Hilfen für Bridge-Antworten -----------------------------------------

def _bridge_error_response(exc: bridge_client.BridgeUnreachable) -> dict:
    """Normalisierte Fehlerantwort (Logik in `auftraege.fehler_antwort`,
    dort ohne `mcp` testbar): nicht erreichbar, Instanz unklar oder
    GESENDET ohne Antwort."""
    return auftraege.fehler_antwort(exc)


# --- API-Help: Logik in api_hilfe.py (ohne mcp, Gate test_wissen W30) ---


# --- Tools ----------------------------------------------------------------

@mcp.tool()
def get_document_info() -> dict:
    """Liefert Informationen zum aktuell in Cadwork geöffneten Dokument.

    Schneller Status-Check: Dokumentname und Anzahl der identifizierbaren
    Elemente. Delegiert über die TCP-Bridge an das McpBridge-Plugin.
    """
    try:
        result = bridge_client.call("get_document_info")
        return {"ok": True, **result}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {
            "ok": False,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
        }


@mcp.tool()
def get_connection_status() -> dict:
    """Zustand der Open-MCP-CAD-Verbindung zu Cadwork.

    Antwortet auch dann, wenn Cadwork gerade minutenlang zeichnet — die
    Abfrage läuft NICHT über die Auftrags-Warteschlange des Plugins.

    Genau dafür gedacht, wenn execute_cadwork_command in ein Timeout gelaufen
    ist: Hier steht, ob der Auftrag noch läuft (dann warten, NICHT wiederholen),
    ob die Verbindung pausiert ist oder ob der Cadwork-Hauptthread hängt.

    Liefert unter anderem: instanz (A-D), port, pid, dokument, zustand +
    zustand_text (Aus / Wird gestartet / Bereit / Liest Modell / Bearbeitet
    Modell / Pausiert / Wird nach dem Auftrag beendet / Störung), laufender
    Auftrag mit Beschreibung und Laufzeit, wartende Aufträge, Schreiblizenz,
    letzter Fehler und ein Klartext-Hinweis.

    `cadwork_beschaeftigt` nicht leer heisst: Cadwork arbeitet gerade selbst
    (modaler Dialog, Fortschrittsdialog, offenes Menü). Aufträge warten dann
    in der Warteschlange und laufen danach von selbst — NICHT wiederholen.

    Sind Erweiterungen eingetragen (OPEN_MCP_CAD_ERWEITERUNGEN), steht unter
    `erweiterungen` je Eintrag, ob sie geladen ist und welche Werkzeuge sie
    gebracht hat (oder warum nicht).
    """
    antwort = _verbindungsstatus()
    if erweiterungen.eintraege():
        antwort["erweiterungen"] = ERWEITERUNGEN
    return antwort


def _verbindungsstatus() -> dict:
    try:
        return {"ok": True, **bridge_client.call("status")}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        if exc.code == "unknown_method":
            return {
                "ok": False,
                "error": "altes_plugin",
                "message": ("Das Cadwork-Plugin kennt 'status' noch nicht. "
                            "Es läuft eine Version vor Open MCP CAD 2.0 — "
                            "Plugin im Userprofil aktualisieren und in "
                            "Cadwork neu starten."),
                "details": exc.details,
            }
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


@mcp.tool()
def report_check_note(
    titel: str,
    text: str = "",
    element_ids: list[int] | None = None,
    schweregrad: str = "hinweis",
    dringlichkeit: int = 0,
) -> dict:
    """Meldet einen Prüfhinweis ins Fenster „Open MCP CAD" in Cadwork.

    Dafür gedacht, dem Menschen etwas mitzuteilen, das er sich anschauen
    soll — eine Annahme, eine Unsicherheit, eine fehlende Angabe, eine
    Builder-Warnung. Der Hinweis erscheint sofort im Register „Hinweise";
    sind Element-IDs dabei, kann der Nutzer ihn anklicken und „Im Modell zeigen"
    aktiviert und zoomt genau diese Bauteile.

    Benutze das, statt Unsicherheiten nur im Chat zu erwähnen: im Chat gehen
    sie unter, hier stehen sie neben dem Modell und lassen sich abhaken.

    KEINE Kollisionssuche — Cadwork hat eine eigene. Hier landet nur, was
    ausdrücklich gemeldet wird.

    Args:
        titel: Eine Zeile, das Wichtigste zuerst
            ("Ständerabstand über dem Fenster unklar").
        text: Ausführlicher, wenn nötig — was angenommen wurde und warum.
        element_ids: Betroffene Bauteile. Damit wird der Hinweis anklickbar.
        schweregrad: "hinweis" (Standard) · "warnung" · "fehler" · "frage".
        dringlichkeit: 1 bis 5, wird als Balken angezeigt. 0 = aus dem
            Schweregrad ableiten (fehler 5, warnung/frage 4, hinweis 2).
            BEWUSST getrennt vom Schweregrad: eine Frage kann dringend sein
            und ein Fehler unwichtig.
    """
    try:
        result = bridge_client.call("hinweis_melden", {
            "titel": titel,
            "text": text,
            "element_ids": element_ids or [],
            "schweregrad": schweregrad,
            "dringlichkeit": dringlichkeit,
        })
        return {"ok": True, **result}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        if exc.code == "unknown_method":
            return {"ok": False, "error": "altes_plugin",
                    "message": ("Das Cadwork-Plugin kennt 'hinweis_melden' "
                                "noch nicht — Plugin aktualisieren und in "
                                "Cadwork neu starten."),
                    "details": exc.details}
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


@mcp.tool()
def clear_check_notes(nr: int = 0, nur_erledigte: bool = True) -> dict:
    """Räumt Prüfhinweise weg, die abgearbeitet sind.

    Abhaken allein genügt nicht: erledigte Hinweise bleiben in der Liste
    stehen und verdecken die neuen (2026-08-06). Wer einen Hinweis
    umgesetzt hat, soll ihn auch entfernen können.

    Args:
        nr: Nummer eines einzelnen Hinweises. 0 = nicht einzeln löschen.
        nur_erledigte: Ohne `nr` alle als erledigt markierten wegwerfen.
            Offene bleiben in jedem Fall stehen — sie sind ja der Grund,
            warum es die Liste gibt.
    """
    params = {"nr": nr} if nr else {"erledigte": bool(nur_erledigte)}
    try:
        return {"ok": True, **bridge_client.call("hinweis_loeschen", params)}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        if exc.code == "unknown_method":
            return {"ok": False, "error": "altes_plugin",
                    "message": ("Das Cadwork-Plugin kennt 'hinweis_loeschen' "
                                "noch nicht (ab Kern 2.12.0) — Plugin "
                                "aktualisieren und in Cadwork neu starten."),
                    "details": exc.details}
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


@mcp.tool()
def get_pending_messages(alle: bool = False) -> dict:
    """Holt Nachrichten ab, die der Nutzer in Cadwork in den Briefkasten gelegt hat.

    Der Briefkasten im Fenster „Open MCP CAD" ist bewusst kein Chat: Es
    gibt keinen Weg, dich von aussen anzustupsen. Die Nachricht liegt dort,
    bis DU sie hier abholst. Deshalb:

    **Während einer Zeichensitzung regelmässig aufrufen** — etwa zwischen
    zwei Batches. Sonst wartet eine Korrektur unbemerkt, während weiter in
    die falsche Richtung gebaut wird.

    Jede Nachricht bringt den Modell-Kontext mit, den sie beim Absenden
    hatte: die in Cadwork aktiven Element-IDs samt Name, Gruppe und
    Abmessungen, bei wenigen Elementen zusätzlich deren Facetten. Damit sind
    Anweisungen wie „strecke diese Facette um 15 mm" auflösbar.

    Abgeholte Nachrichten werden als gelesen markiert, damit dieselbe
    Anweisung nicht zweimal umgesetzt wird.

    Args:
        alle: True liefert auch schon Gelesenes und ändert nichts am Zustand
            (zum Nachschlagen, was vorhin gewünscht war).
    """
    try:
        return {"ok": True, **bridge_client.call("nachrichten_abholen",
                                                 {"alle": alle})}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        if exc.code == "unknown_method":
            return {"ok": False, "error": "altes_plugin",
                    "message": ("Das Cadwork-Plugin kennt den Briefkasten "
                                "noch nicht — Plugin aktualisieren und in "
                                "Cadwork neu starten."),
                    "details": exc.details}
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


@mcp.tool()
def set_fast_draw(an: bool) -> dict:
    """Schaltet das Schnellzeichnen ein oder aus.

    Ist es an, schaltet die Bridge Cadworks automatische Bildschirm-
    Auffrischung ab, solange ein Zeichenauftrag läuft, und danach wieder
    ein — auch wenn der Auftrag fehlschlägt. Bei langen Zeichenläufen mit
    vielen Elementen spart das spürbar Zeit, weil Cadwork nicht nach jedem
    Bauteil neu zeichnet.

    Der Schalter ist auch im Fenster „Open MCP CAD" in Cadwork zu finden.
    """
    try:
        return {"ok": True, **bridge_client.call("schnellzeichnen", {"an": an})}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


def _build_execute_description() -> str:
    """Baut die Tool-Beschreibung für execute_cadwork_command.

    Statischer Basistext + dynamisch eingebettetes Wissen aus knowledge/
    (Regeln aus dem eingehaengten Fachwissen, Zusammenfassung bekannter
    Probleme). So sieht
    Claude die Regeln bei JEDEM Tool-Aufruf.
    """
    base = """Führt cwapi3d-Python-Code in Cadwork aus und liefert das Ergebnis.

Du (Claude) generierst den Python-Code als String und übergibst ihn hier.
Der Code wird im Cadwork-Prozess ausgeführt, wo alle cwapi3d-Module
verfügbar sind.

Konvention: Weise das Endergebnis der Variable `result` zu — sie wird
als JSON zurückgegeben. Beispiel:
    result = ec.get_all_identifiable_element_ids()

Welches Cadwork: ohne feste Angabe nimmt der Server das EINE verbundene
Cadwork-Fenster und bleibt dabei. Sind mehrere verbunden, oder ist das
gewählte geschlossen bzw. zeigt eine andere Datei, antwortet jedes Werkzeug
mit error="instanz_waehlen" und der Liste — dann wait_for_bridge(dokument=...)
mit der gemeinten Datei aufrufen. Vor Arbeitsbeginn get_document_info
aufrufen und den Dokumentnamen prüfen, damit Code nicht in der falschen
Datei landet. Ist serverseitig OPEN_MCP_CAD_EXPECT_DOC gesetzt, wird diese
Prüfung automatisch erzwungen.

Verfügbare Module (Voll-Namen + Aliase):
    element_controller (ec)        utility_controller (uc)
    attribute_controller (ac)      geometry_controller (gc)
    file_controller (fc)           visualization_controller (vc)
    material_controller (mc)       bim_controller (bc)
    scene_controller (sc)          list_controller (lc)
    cadwork (cw, Typen)            ... weitere via get_cadwork_api_help()
Name und Gruppe eines Elements stehen im attribute_controller, nicht im
element_controller: ac.get_name(eid), ac.get_group(eid).

Sicherheit: Imports von os, subprocess, shutil, socket, urllib, requests
sowie __import__ sind blockiert (Best-Effort). Datei-Operationen sollten
ausschließlich über cwapi3d-Funktionen laufen.

Verifizierte Code-Beispiele liefert get_working_examples() — bei Holzbau-
Operationen zuerst dort nachschauen statt zu raten.

Hängt eingebundenes Fachwissen (OPEN_MCP_CAD_KNOWLEDGE) einen
Detail-Katalog ein, liefert get_detail() fertige Details: zuerst
get_detail(list_types=True) für die Übersicht, dann
get_detail(type=..., variant=...) für Code + Detail-Regeln.

Achtung Klassiker: Panels: `thickness` ist die z_local-Dimension, NICHT
die phys. Plattendicke (kann 2700mm Wandhöhe sein).

Bei error="antwort_fehlt" NICHT blind wiederholen: der Auftrag ist
gesendet und kann noch laufen. get_connection_status() sagt, ob er noch
läuft (dann warten), ob die Verbindung pausiert ist oder ob der
Cadwork-Hauptthread hängt. Nur "bridge_unreachable" und "instanz_waehlen"
heissen: nichts gesendet.

Erfahrungen (nur auf diesem Rechner): scheitert ein Auftrag am Code und
gelingt danach einer derselben Art, hält der Server das fest (Feld
`erfahrung_festgehalten` in der Antwort). Dann mit
record_experience(erfahrung_id=..., loesung="...") in einem Satz ergänzen,
was geholfen hat. Kommt ein Fehler, den es schon gab, steht in der Antwort
unter `erfahrungen`, was damals half. Frühere Erfahrungen stehen unten;
get_experiences() liefert sie ausführlich.

Viele gleichartige Bauteile (hunderte Stäbe, tausende Achsen): Daten als
JSON-Liste in eine Datei schreiben und execute_cadwork_batch nehmen, statt
die Werte hier als Code auszuschreiben. Jeder Auftrag ist ein Undo-Schritt
(undo()).

Args:
    code: cwapi3d-Python-Code. Endergebnis bitte in `result` schreiben.
    description: Kurzer Klartext, WAS der Auftrag baut ("Fensterwand Süd
        erzeugen"). Wird im Fenster "Open MCP CAD Verbindungen" angezeigt,
        solange der Auftrag läuft, und landet im Log. Bitte immer setzen —
        sonst steht dort nur "execute_cwapi3d".
    timeout_s: Wie lange auf die Antwort gewartet wird. 0 = Vorgabe
        (CADWORK_BRIDGE_TIMEOUT, meist 10 s). Für einen Auftrag, der
        absehbar länger rechnet (z. B. Endtypen an hunderten Stäben in
        einem Schritt), höher setzen, höchstens 3600.

Liefert:
    {"ok": True, "result": <JSON-Wert>, "stdout": <prints>, "vars": [...]}
    oder Fehlerobjekt mit "error", "message", "details"."""

    parts = [base]
    if KNOWLEDGE.get("rules"):
        parts.append(
            "=== REGELN AUS DEM FACHWISSEN (immer beachten) ===\n"
            + KNOWLEDGE["rules"].strip()
        )
    if KNOWLEDGE.get("issues_summary"):
        parts.append(
            "=== BEKANNTE PROBLEME + WORKAROUNDS ===\n"
            + KNOWLEDGE["issues_summary"]
        )
    # Notizen aus frueheren Fehlern: als DATEN gekennzeichnet, jede eine
    # Zeile, begrenzt (erfahrungen.abschnitt, KOPF).
    eigene = erfahrungen.abschnitt()
    if eigene:
        parts.append(eigene)
    return "\n\n".join(parts)


ERFAHRUNGEN_KOPF = erfahrungen.KOPF


def _dokument_pruefen() -> dict | None:
    """Verwechslungs-Schutz vor jedem Schreibauftrag: ist OPEN_MCP_CAD_
    EXPECT_DOC gesetzt (oder von wait_for_bridge gebunden), erst nachsehen,
    ob die richtige Datei offen ist. None = passt oder kein Riegel."""
    if not EXPECT_DOC:
        return None
    try:
        info = bridge_client.call("get_document_info")
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code,
                "message": exc.message, "details": exc.details}
    doc_name = info.get("document_name", "")
    if EXPECT_DOC.lower() not in doc_name.lower():
        return {
            "ok": False,
            "error": "wrong_document",
            "message": (
                f"Abbruch: erwartetes Dokument enthält {EXPECT_DOC!r}, "
                f"offen ist aber {doc_name!r}. Code wurde NICHT ausgeführt "
                "(falsche Cadwork-Instanz?)."
            ),
            "details": f"OPEN_MCP_CAD_EXPECT_DOC={EXPECT_DOC!r}",
        }
    return None


@mcp.tool(description=_build_execute_description())
def execute_cadwork_command(code: str, description: str = "",
                            timeout_s: float = 0) -> dict:
    """Führt cwapi3d-Python-Code in Cadwork aus und liefert das Ergebnis.

    (Die an Claude gesendete Tool-Beschreibung wird dynamisch von
    _build_execute_description() erzeugt und enthält zusätzlich die
    Regeln aus dem eingehaengten Fachwissen, siehe load_knowledge.)
    """
    # Verwechslungs-Schutz: Wenn OPEN_MCP_CAD_EXPECT_DOC gesetzt ist, erst
    # prüfen, ob die richtige Datei offen ist, bevor Code ausgeführt wird.
    fehler = _dokument_pruefen()
    if fehler:
        return fehler
    return ERFAHRUNGEN.nach_auftrag(
        "execute_cadwork_command", code, description,
        _ausfuehren(code, description, timeout_s))


def _ausfuehren(code: str, description: str, timeout_s: float) -> dict:
    """Der eigentliche Auftrag von execute_cadwork_command."""
    try:
        result = bridge_client.call(
            "execute_cwapi3d",
            {
                "code": code,
                "result_var": "result",
                # Ab Protokoll 2: die Beschreibung geht an die Bridge, damit
                # "Open MCP CAD Verbindungen" im Klartext zeigt, was gerade läuft.
                # Vorher wurde sie hier stillschweigend weggeworfen.
                "description": description,
                # Ohne ausdrückliche Angabe gilt ein Auftrag als Schreib-
                # zugriff — die sichere Richtung.
                "access_mode": "write",
                # Doppelte Sicherung des Dokuments: server.py hat oben schon
                # geprüft, die Bridge prüft ohne zweiten Roundtrip nochmal.
                **({"expect_document": EXPECT_DOC} if EXPECT_DOC else {}),
            },
            antwort_timeout=auftraege.wartezeit(
                timeout_s, bridge_client.BRIDGE_TIMEOUT_SECONDS),
        )
        return {"ok": True, "description": description, **result}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {
            "ok": False,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
        }


@mcp.tool()
def execute_cadwork_batch(code: str, daten_datei: str,
                          paket_groesse: int = 50, description: str = "",
                          timeout_s: float = 0) -> dict:
    """Führt denselben cwapi3d-Code paketweise über eine Datenliste aus.

    Für grosse Mengen gleichartiger Bauteile: die Daten (ein Eintrag je
    Bauteil, z. B. Punkte, Masse, Namen) liegen als JSON-LISTE in
    `daten_datei` (absoluter Pfad, .json). Der Code wird EINMAL geschrieben;
    der Server schickt ihn je Paket mit anderen Daten an Cadwork. Im Code
    stehen bereit:
        paket        die Einträge dieses Pakets (Liste)
        paket_nr     1, 2, ...        pakete       Anzahl Pakete
        paket_start  Index des ersten Eintrags in der ganzen Liste
    `result` jedes Pakets kommt in `ergebnisse` zurück (Liste, ein Wert je
    Paket) — klein halten, z. B. nur die neuen IDs oder Zähler.

    Jedes Paket ist ein eigener Auftrag und ein Undo-Schritt. Zwischen den
    Paketen bleibt Cadwork bedienbar, der Fortschrittsbalken im Dock zeigt
    den Stand. Im Zeichenmodus «Auto» erscheint jedes Paket im Bild, sobald
    es fertig ist; `nachgezogen` in der Antwort nennt, was das Nachziehen
    der Darstellung dafür gekostet hat. Paketgrösse so wählen, dass ein
    Paket einige Sekunden braucht. Alle Pakete werden vor dem ersten Senden
    gebaut und gegen die Code-Grenze geprüft.

    Beim ersten Fehler hört der Lauf auf. Die Antwort nennt `pakete_fertig`,
    `abgebrochen_bei_paket` und ob das abgebrochene Paket gelaufen sein kann
    (`antwort_fehlt`: dann NICHT wiederholen, erst get_connection_status()).
    Einen Rest-Lauf mit einer neuen Datei ab `eintraege_fertig` starten.

    Args:
        code: cwapi3d-Python-Code, der `paket` verarbeitet.
        daten_datei: absoluter Pfad einer .json-Datei mit einer Liste.
        paket_groesse: Einträge je Paket (ab 1).
        description: Klartext für Dock und Log, bekommt "(Paket k/n)".
        timeout_s: Wartezeit auf die Antwort EINES Pakets (0 = 120 s).
    """
    fehler = _dokument_pruefen()
    if fehler:
        return fehler
    return ERFAHRUNGEN.nach_auftrag(
        "execute_cadwork_batch", code, description,
        auftraege.paketlauf(code, daten_datei, paket_groesse,
                            description, timeout_s, EXPECT_DOC),
        # Die Funktion, nicht ihr Wert: gerechnet wird erst nach einem
        # Fehler, im try des Beobachters (die Antwort ist dann schon da).
        versatz=erfahrungen.paket_versatz)


@mcp.tool()
def undo(schritte: int = 1) -> dict:
    """Nimmt die letzten Änderungen in Cadwork zurück (Cadworks eigenes
    Rückgängig, wie der Knopf ↶ im Dock).

    Ein Schritt ist ein Auftrag von execute_cadwork_command bzw. EIN Paket
    von execute_cadwork_batch — ein Lauf mit 20 Paketen braucht 20 Schritte.
    Höchstens 10 je Aufruf. Neu angelegte Elemente nimmt es immer zurück;
    Änderungen an bestehenden nur, wenn der Auftrag sie vorher mit
    `aendert(ids)` angemeldet hat.
    """
    return _schritte("undo", schritte)


@mcp.tool()
def redo(schritte: int = 1) -> dict:
    """Stellt wieder her, was undo() zurückgenommen hat (höchstens 10)."""
    return _schritte("redo", schritte)


@mcp.tool()
def redraw_view() -> dict:
    """Zeichnet Cadworks Ansicht neu (wie der Knopf «Ansicht neu zeichnen» im
    Dock). Ändert das Modell nicht.

    Was IM Auftrag entsteht oder gezoomt wird, kann danach unsichtbar
    bleiben: Generalprobe 2026-09-25 (Zeichenmodus «Langsam»), die Ansicht
    blieb nach `vc.set_active` + `vc.zoom_active_elements()` leer, erst
    «Ansicht neu zeichnen» zeigte den Knoten. Die Ursache ist nicht
    geklärt. Deshalb nach einem Auftrag, der auf Elemente zoomt, dieses
    Werkzeug aufrufen.
    """
    fehler = _dokument_pruefen()
    if fehler:
        return fehler
    try:
        return {"ok": True, **bridge_client.call(
            "neu_zeichnen", {**({"expect_document": EXPECT_DOC}
                                if EXPECT_DOC else {})})}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


def _schritte(methode: str, schritte: int) -> dict:
    """undo/redo: Dokument prüfen, dann Cadworks eigenen Stapel bedienen."""
    try:
        n = int(schritte)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= 10:
        return {"ok": False, "error": "bad_value",
                "message": "schritte muss eine ganze Zahl von 1 bis 10 sein."}
    fehler = _dokument_pruefen()
    if fehler:
        return fehler
    try:
        return {"ok": True, **bridge_client.call(
            methode, {"schritte": n,
                      **({"expect_document": EXPECT_DOC}
                         if EXPECT_DOC else {})})}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code, "message": exc.message,
                "details": exc.details}


@mcp.tool()
def get_cadwork_api_help(module: str = "", function: str = "") -> dict:
    """Listet verfügbare cwapi3d-Module bzw. -Funktionen.

    Liest Type-Stubs (.pyi) lokal aus dem cwapi3d-Paket. Funktioniert auch,
    wenn Cadwork nicht läuft (kein Bridge-Aufruf nötig). Fehlt das Paket
    im Python des Servers, antwortet es mit error="stubs_fehlen" und dem
    Installationshinweis — dann ist nicht das Modul falsch.

    Aufrufmuster:
        get_cadwork_api_help()
            -> Liste aller bekannten Controller-Module + Aliase.
        get_cadwork_api_help(module="element_controller")
            -> Alle Funktionen mit Signatur und Kurzbeschreibung.
        get_cadwork_api_help(module="element_controller",
                             function="get_all_identifiable_element_ids")
            -> Volle Docstring der Funktion.

    Args:
        module: Optional, Modulname (z.B. "element_controller").
        function: Optional, Funktionsname innerhalb des Moduls.
    """
    # Fehlt das Paket cwapi3d im Python des Servers, heisst die Antwort
    # "stubs_fehlen" (mit Installationshinweis), nicht "stub_not_found".
    return api_hilfe.hilfe(module, function, CWAPI3D_MODULES,
                           CWAPI3D_ALIASES)


@mcp.tool()
def get_working_examples(category: str = "") -> str:
    """Gibt geprüfte Code-Beispiele für Cadwork-Operationen zurück — mit
    einem Suchbegriff auch die passenden bekannten Probleme und Grenzen.

    Quelle: knowledge/working_examples.json und known_issues.json (plus
    eingehängtes Fachwissen). Einträge mit Feld `nachweis` sagen, wie sie
    belegt sind (nativ_gemessen, offline_geprueft, nutzerbeobachtung,
    offene_grenze), an welcher Cadwork-Version und wofür sie gelten.

    Args:
        category: Optional. Suchbegriff(e), jedes Wort muss vorkommen,
                  z.B. 'vba', 'raumstab', 'bogen', 'platte', 'sehne',
                  'endtyp', '3dc', 'step', 'panel', 'material'. Leer = alle
                  Beispiele (ohne Probleme).
    """
    return wissen.beispiele_antwort(KNOWLEDGE, category)


@mcp.tool()
def get_detail(type: str = "", variant: str = "", list_types: bool = False) -> str:
    """Liefert Konstruktionsdetails aus einem eingehaengten Detail-Katalog.

    Einen Katalog bringt nur eingehaengtes Fachwissen mit
    (OPEN_MCP_CAD_KNOWLEDGE, Datei detail_catalog.json); das eingebaute
    Wissen hat keinen. Ein Detail ist eine wiederkehrende konstruktive
    Lösung, gegliedert nach Typ und Variante; welche es gibt, bestimmt der
    Katalog, nicht dieses Werkzeug. Jedes Detail bringt eigene Regeln und
    parametrischen cwapi3d-Code mit. Allgemeine Regeln stehen in den Regeln
    des Fachwissens (rules.md).

    Nur on-demand abrufen, wenn ein
    konkretes Detail gebaut werden soll — das Tool ist NICHT in die
    Beschreibung von execute_cadwork_command eingebettet.

    Aufrufmuster:
        get_detail(list_types=True)
            -> Übersicht: alle Typen und ihre Varianten.
        get_detail(type="<typ>")
            -> Alle Varianten dieses Typs (Kurzform, ohne Code).
        get_detail(type="<typ>", variant="<variante>")
            -> Komplettes Detail: Code, Regeln, Parameter, Status.

    Args:
        type: Hauptkategorie, wie sie get_detail(list_types=True) nennt.
        variant: Variante innerhalb des Typs, ebenso aus der Übersicht.
        list_types: True = nur Typen/Varianten-Übersicht zurückgeben.

    Hinweis: validated=false bedeutet, dass das Detail noch nicht in Cadwork
    visuell geprüft wurde — Code ggf. erst als Platzhalter vorhanden.
    """
    details = KNOWLEDGE.get("details", {}).get("details", [])

    if not details:
        return json.dumps(
            {"error": "Kein Detail-Katalog geladen (detail_catalog.json fehlt?)."},
            ensure_ascii=False,
        )

    # Fall 1: Typen-/Varianten-Übersicht.
    if list_types or (not type and not variant):
        overview: dict = {}
        for d in details:
            overview.setdefault(d["type"], []).append(
                {
                    "variant": d["variant"],
                    "title": d["title"],
                    "validated": d.get("validated", False),
                }
            )
        return json.dumps(
            {
                "types": overview,
                "hint": (
                    "Rufe get_detail(type='<typ>') für alle Varianten auf, "
                    "oder get_detail(type='<typ>', variant='<variante>') "
                    "für das komplette Detail mit Code."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )

    t = type.lower()
    matches = [d for d in details if d["type"].lower() == t]

    if not matches:
        available = sorted({d["type"] for d in details})
        return json.dumps(
            {
                "error": f"Kein Detail-Typ '{type}' gefunden.",
                "available_types": available,
            },
            ensure_ascii=False,
        )

    # Fall 2: Alle Varianten eines Typs (Kurzform).
    if not variant:
        return json.dumps(
            {
                "type": type,
                "variants": [
                    {
                        "variant": d["variant"],
                        "title": d["title"],
                        "description": d.get("description", ""),
                        "validated": d.get("validated", False),
                    }
                    for d in matches
                ],
                "hint": (
                    "Rufe erneut mit variant='<variante>' auf für Code und "
                    "Detail-Regeln."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )

    # Fall 3: Komplettes Detail.
    v = variant.lower()
    detail = next((d for d in matches if d["variant"].lower() == v), None)
    if detail is None:
        return json.dumps(
            {
                "error": f"Keine Variante '{variant}' für Typ '{type}' gefunden.",
                "available_variants": [d["variant"] for d in matches],
            },
            ensure_ascii=False,
        )

    return json.dumps(detail, indent=2, ensure_ascii=False)


@mcp.tool()
def list_stored_keys() -> dict:
    """Zeigt alle gespeicherten Namen im Session-Speicher der Bridge.

    Nützlich zum Debuggen: zeigt welche Element-ID-Listen aktuell
    im Session-Speicher vorhanden sind. Speicher wird beim
    Plugin-Neustart automatisch geleert.

    Beispiel-Ausgabe: {"ok": True, "keys": ["staender_sued", "osb_aw"], "count": 2}
    """
    try:
        result = bridge_client.call("list_store_keys")
        return {"ok": True, **result}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code,
                "message": exc.message, "details": exc.details}


@mcp.tool()
def clear_store() -> dict:
    """Leert den Session-Speicher der Bridge komplett.

    Nützlich am Anfang einer neuen Aufgabe oder nach Bridge-Timeouts
    um sauber neu zu starten. Gibt zurück wie viele Einträge gelöscht wurden.
    """
    try:
        result = bridge_client.call("clear_store")
        return {"ok": True, **result}
    except bridge_client.BridgeUnreachable as exc:
        return _bridge_error_response(exc)
    except bridge_client.BridgeError as exc:
        return {"ok": False, "error": exc.code,
                "message": exc.message, "details": exc.details}


# --- Erfahrungen -----------------------------------------------------------

@mcp.tool()
def get_experiences(suche: str = "", anzahl: int = 20) -> dict:
    """Erfahrungen aus früheren Fehlern auf DIESEM Rechner, neueste zuerst.

    Lokal, ohne Cadwork: je Erfahrung der Fehler (Typ, Meldung, Funktion),
    was geholfen hat (`loesung` bzw. neue/weggefallene Aufrufe und ein
    Code-Auszug ohne Zeichenketten und Zahlen), Cadwork- und Kern-Version.
    Die neuesten stehen schon in der Beschreibung von
    execute_cadwork_command; hier ausführlich und durchsuchbar.

    Args:
        suche: Teilwort, z. B. ein Funktionsname ("create_rectangular") oder
            ein Fehlertyp ("TypeError"). Leer = alle.
        anzahl: höchstens so viele (1 bis 50).
    """
    return erfahrungen.liste(suche, anzahl)


@mcp.tool()
def record_experience(loesung: str, problem: str = "", befehl: str = "",
                      fehlermeldung: str = "",
                      erfahrung_id: str = "") -> dict:
    """Hält eine Erfahrung lokal fest: was schiefging und was geholfen hat.

    Die Datei bleibt auf diesem Rechner (was du liest, geht wie jeder
    Werkzeugtext an den Anbieter deines Modells). Gespeichert wird bereinigt:
    ohne Pfade, Datei-, Dokument- und Benutzernamen; ein Befehl nur als
    Auszug ohne Zeichenketten, Kommentare und mehrstellige Zahlen. Keine
    Modelldaten hineinschreiben (Bauteilnamen, Masse, Element-IDs) — die
    Lehre gilt fürs nächste Projekt. Eine Erfahrung beschreibt, was an einem
    cwapi3d-Auftrag half; Anweisungen an einen Agenten nimmt sie nicht an.

    Zwei Wege:
      - erfahrung_id (aus `erfahrung_festgehalten` einer Antwort) +
        loesung: ergänzt die Erfahrung, die der Server gerade automatisch
        festgehalten hat, um einen Satz, was geholfen hat.
      - problem + loesung (+ befehl, fehlermeldung): eine neue Erfahrung,
        z. B. eine Stolperfalle, die kein Fehler war.

    Args:
        loesung: in einem Satz, was geholfen hat.
        problem: was schiefging (ohne erfahrung_id Pflicht).
        befehl: optional der cwapi3d-Code, um den es ging.
        fehlermeldung: optional die Meldung von Cadwork.
        erfahrung_id: optional die id einer vorhandenen Erfahrung.
    """
    return erfahrungen.festhalten(problem, loesung, befehl, fehlermeldung,
                                  erfahrung_id, _bekannte_dokumente())


# --- Datei-Bootstrap ------------------------------------------------------
#
# Eine Cadwork-Datei anlegen und oeffnen OHNE Computer Use; die Logik steht
# mcp-frei in `bootstrap.py` (dort auch der ganze Ablauf). Hier nur die
# Werkzeuge — und bei `wait_for_bridge` das Binden der Sitzung.

@mcp.tool()
def create_from_init(init_datei: str, ziel_datei: str) -> dict:
    """Legt eine NEUE Cadwork-Datei als Kopie einer vorhandenen Init-/
    Vorlagendatei an. Schritt 1 des Datei-Bootstraps.

    Beide Pfade absolut, beide auf .3d. Die Init-Datei muss existieren und
    darf nicht leer sein; die Zieldatei darf NICHT existieren (es wird nie
    ueberschrieben), ihr Ordner muss existieren. Welche Init-Datei, sagt
    der Aufrufer — es wird keine geraten.

    Danach: open_document(ziel_datei).
    """
    return bootstrap.create_from_init(init_datei, ziel_datei)


@mcp.tool()
def open_document(ziel_datei: str) -> dict:
    """Oeffnet eine vorhandene .3d-Datei ueber die Windows-Dateiverknuepfung
    (startet Cadwork bzw. ci_start.exe). Schritt 2 des Datei-Bootstraps.

    Wartet NICHT auf Cadwork. Danach muss im Cadwork-Fenster dieser Datei
    EINMAL das Plugin "Open MCP CAD" geklickt werden — per Computer Use des
    Agent-Hosts oder vom Nutzer; der Klick verbindet von selbst. Dann
    wait_for_bridge(ziel_datei).

    Lehnt ab, wenn eine verbundene Instanz schon eine Datei gleichen Namens
    offen hat (sonst waere die Bridge danach nicht eindeutig).
    """
    return bootstrap.open_document(ziel_datei)


@mcp.tool()
def wait_for_bridge(dokument: str, timeout_s: float = 120.0) -> dict:
    """Wartet, bis genau EINE Cadwork-Instanz `dokument` offen und verbunden
    hat, prueft sie und BINDET diese Sitzung daran. Schritt 3 des Datei-
    Bootstraps — und Pflicht vor jedem Modellauftrag nach open_document.
    Auch der Weg, ein Fenster zu WAEHLEN, wenn mehrere verbunden sind
    (Antwort error="instanz_waehlen"): kehrt sofort zurueck, wenn die Datei
    schon offen ist.

    `dokument`: voller Pfad der .3d-Datei (dann wird auch ihr Ordner
    geprueft) oder nur ihr Dateiname. Geprueft wird ueber die Bridge
    selbst: Dokumentname und Port aus get_document_info, bei vollem Pfad
    der Ordner. Erst dann wird gebunden: alle weiteren Aufrufe gehen an
    diesen Port, und execute_cadwork_command ist auf dieses Dokument
    verriegelt.

    Nichts wird gebunden bei: Zeitablauf, mehreren Treffern, fremdem Port
    oder Ordner, oder wenn OPEN_MCP_CAD_EXPECT_DOC nicht zum Dokument passt.
    """
    global EXPECT_DOC
    erg = bootstrap.warte_auf_bridge(dokument, timeout_s,
                                     erwartet=EXPECT_DOC)
    if erg.get("ok"):
        bridge_client.ziel_setzen(erg["port"])
        EXPECT_DOC = erg["dokument"]
        erg["gebunden"] = True
    return erg


# --- Erweiterungen (OPEN_MCP_CAD_ERWEITERUNGEN, seit 2026-10-01) ------------
#
# Zusaetzliche Werkzeuge aus eigenen Modulen, jedes mit
# `registrieren(mcp, kontext)`; Regeln und Kontext in `erweiterungen.py`
# (Gate tests/test_erweiterungen.py). Geladen NACH allen Kernwerkzeugen:
# eine Erweiterung kann keinen Kernnamen belegen, und scheitert sie, bleibt
# der Server mit allen Kernwerkzeugen stehen. Der Dokumentriegel ist
# derselbe wie fuer execute_cadwork_command (auch nach wait_for_bridge,
# darum als Funktion).

ERWEITERUNGEN = erweiterungen.laden(
    mcp, erwartet=lambda: EXPECT_DOC,
    dokument_pruefen=lambda: _dokument_pruefen())


def main() -> None:
    """Einstiegspunkt: MCP-Server ueber stdio.

    Gleichzeitig das Ziel des Konsolenbefehls `open-mcp-cad` und von
    `python -m open_mcp_cad.server`.

    Nur hier waehlt der Client ohne Angabe selbst das verbundene Cadwork
    (`bridge_client.AUTOMATISCH`); wer `bridge_client` als Bibliothek
    importiert, behaelt den festen Port.
    """
    bridge_client.AUTOMATISCH = True
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
