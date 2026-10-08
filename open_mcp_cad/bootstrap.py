# -*- coding: utf-8 -*-
"""Datei-Bootstrap: eine Cadwork-Datei anlegen, oeffnen, auf die Bridge warten.

Alles OHNE Computer Use (2026-09-22). Der Ablauf:

  1. `create_from_init(init_datei, ziel_datei)`
        kopiert eine vorhandene Init-/Vorlagendatei als NEUE .3d-Datei.
  2. `open_document(ziel_datei)`
        oeffnet genau diese Datei ueber den normalen Windows-Weg (die
        Dateiverknuepfung .3d -> `ci_start.exe "%1"`).
  3. EIN Klick auf "Open MCP CAD" im Cadwork-Fenster. Das macht der
        Agent-Host per Computer Use — oder der Nutzer selbst. NICHT dieses
        Paket: Computer Use ist eine Faehigkeit des Hosts. Der Klick
        verbindet seit 2026-09-22 von selbst (ein Klick, kein zweiter).
  4. `warte_auf_bridge(ziel_datei)`
        wartet in der Registry auf genau diese Datei und prueft sie ueber
        die Bridge selbst: Dokumentname, Port und — bei vollem Pfad — den
        Ordner. Erst danach darf ein Modellauftrag laufen.

KEIN RATEN, an keiner Stelle:
  * Welche Init-Datei, sagt der Aufrufer. Welche von Cadworks Vorlagen die
    aktive "Standarddatei" ist, steht in keiner lesbaren Quelle — und
    Pfade mit Jahr und Profil gehoeren nicht in ein oeffentliches Paket.
  * Pfade muessen absolut sein (mit Laufwerk oder UNC). Ein relativer Pfad
    haengt am Arbeitsordner des Servers, den niemand sieht.
  * Nie ueberschreiben: das Ziel wird exklusiv angelegt (`open(..., "xb")`),
    auch gegen ein Rennen zwischen Pruefung und Anlegen.
  * Keine erfundene .3d: die Quelle muss eine vorhandene, nicht leere Datei
    sein. Eine leere Datei mit .3d-Endung ist keine Cadwork-Datei.

mcp-frei, wie `registry.py` und `bridge_client.py`: die Gates laufen im
System-Python ohne `mcp`. `server.py` registriert nur die Werkzeuge.

Alle drei Funktionen liefern ein dict im Stil der Server-Werkzeuge:
`{"ok": True, ...}` oder `{"ok": False, "error": <code>, "message": ...}`.
"""

import hashlib
import os
import shutil
import time

from . import bridge_client, registry

ENDUNG = ".3d"


def _fehler(code, text, **mehr):
    return dict({"ok": False, "error": code, "message": text}, **mehr)


def _pfad_pruefen(pfad, rolle):
    """-> (normierter Pfad, None) oder (None, Fehler-dict)."""
    if not isinstance(pfad, str) or not pfad:
        return None, _fehler("path_missing", "%s fehlt." % rolle)
    # Mit Laufwerk bzw. UNC-Freigabe: "\\x.3d" waere unter Windows zwar
    # `isabs` (bis Python 3.12), aber relativ zum aktuellen Laufwerk.
    if not (os.path.isabs(pfad) and os.path.splitdrive(pfad)[0]):
        return None, _fehler(
            "path_not_absolute",
            "%s muss ein absoluter Pfad mit Laufwerk sein: %r" % (rolle, pfad))
    if os.path.splitext(pfad)[1].lower() != ENDUNG:
        return None, _fehler(
            "wrong_extension",
            "%s muss auf %s enden: %r" % (rolle, ENDUNG, pfad))
    return os.path.normpath(pfad), None


def _gleiche_datei(a, b):
    return (os.path.normcase(os.path.realpath(a))
            == os.path.normcase(os.path.realpath(b)))


def _sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


# --- 1. Anlegen -------------------------------------------------------------

def create_from_init(init_datei, ziel_datei):
    """Kopiert eine vorhandene Cadwork-Init-/Vorlagendatei als neue .3d-Datei.

    Die Quelle bleibt unveraendert. Das Ziel darf NICHT existieren, sein
    Ordner MUSS existieren (angelegt wird nichts, was man nicht verlangt
    hat). Nach dem Kopieren wird verglichen: Groesse und SHA-256.
    """
    quelle, f = _pfad_pruefen(init_datei, "Init-Datei")
    if f:
        return f
    ziel, f = _pfad_pruefen(ziel_datei, "Zieldatei")
    if f:
        return f
    if not os.path.exists(quelle):
        return _fehler("source_missing", "Init-Datei gibt es nicht: %s" % quelle)
    if not os.path.isfile(quelle):
        return _fehler("source_not_file", "Init-Datei ist keine Datei: %s"
                       % quelle)
    groesse = os.path.getsize(quelle)
    if groesse == 0:
        return _fehler("source_empty", "Init-Datei ist leer — das ist keine "
                       "Cadwork-Datei: %s" % quelle)
    # VOR "Ziel existiert": bei Quelle = Ziel existiert das Ziel natuerlich,
    # und die ehrliche Meldung ist die genauere.
    if _gleiche_datei(quelle, ziel):
        return _fehler("same_file", "Quelle und Ziel sind dieselbe Datei: %s"
                       % quelle)
    if os.path.lexists(ziel):
        return _fehler("target_exists", "Zieldatei existiert schon — es wird "
                       "nie ueberschrieben: %s" % ziel)
    ordner = os.path.dirname(ziel)
    if not os.path.isdir(ordner):
        return _fehler("target_dir_missing", "Zielordner gibt es nicht: %s"
                       % ordner)

    angelegt = False
    try:
        with open(quelle, "rb") as src:
            # "x": exklusiv anlegen. Taucht das Ziel zwischen der Pruefung
            # oben und hier auf, scheitert das — statt es zu ueberschreiben.
            with open(ziel, "xb") as dst:
                angelegt = True
                shutil.copyfileobj(src, dst, 1024 * 1024)
    except FileExistsError:
        return _fehler("target_exists", "Zieldatei ist eben entstanden — es "
                       "wird nie ueberschrieben: %s" % ziel)
    except OSError as exc:
        if angelegt:
            _eigene_teilkopie_weg(ziel)
        return _fehler("copy_failed", "Kopieren fehlgeschlagen: %s" % exc)

    soll = _sha256(quelle)
    ist = _sha256(ziel)
    if os.path.getsize(ziel) != groesse or ist != soll:
        _eigene_teilkopie_weg(ziel)
        return _fehler("copy_mismatch", "Die Kopie weicht von der Quelle ab "
                       "und wurde wieder entfernt: %s" % ziel)
    return {"ok": True, "init_datei": quelle, "ziel_datei": ziel,
            "bytes": groesse, "sha256": ist,
            "naechster_schritt": "open_document(%r)" % ziel}


def _eigene_teilkopie_weg(ziel):
    """Nur die Datei, die DIESER Aufruf eben angelegt hat — nie eine fremde."""
    try:
        os.remove(ziel)
    except OSError:
        pass


# --- 2. Oeffnen -------------------------------------------------------------

def _windows_starten(pfad):
    """Der normale Windows-Weg: die Dateiverknuepfung von .3d.

    Gemessen 2026-09-22: .3d -> ProgID `cadwork.3d` ->
    `"C:\\Program Files\\cadwork.dir\\ci_start.exe" "%1"`. Ob ci_start ein
    NEUES Cadwork startet oder an ein laufendes uebergibt, ist nicht
    gemessen.

    ⚠ In Tests NIE aufrufen: jede .3d, auch eine Attrappe, startet Cadwork.
    """
    os.startfile(pfad)                       # nur unter Windows vorhanden


def open_document(ziel_datei, starter=None, laufende=None):
    """Oeffnet eine VORHANDENE .3d-Datei ueber den normalen Windows-Weg.

    Wartet nicht auf Cadwork. Danach: im Cadwork-Fenster einmal
    "Open MCP CAD" klicken, dann `warte_auf_bridge(ziel_datei)`.

    Abgelehnt wird, wenn eine verbundene Instanz schon eine Datei GLEICHEN
    NAMENS offen hat: die Registry kennt nur Namen, und zwei gleiche waeren
    fuer `warte_auf_bridge` nicht auseinanderzuhalten.

    `starter` und `laufende` sind fuer Tests austauschbar.
    """
    ziel, f = _pfad_pruefen(ziel_datei, "Zieldatei")
    if f:
        return f
    if not os.path.isfile(ziel):
        return _fehler("target_missing", "Datei gibt es nicht: %s" % ziel)
    if os.path.getsize(ziel) == 0:
        return _fehler("target_empty", "Datei ist leer — das ist keine "
                       "Cadwork-Datei: %s" % ziel)
    name = os.path.basename(ziel).lower()
    gleich = [e for e in (laufende or registry.laufende)()
              if (e.get("dokument") or "").lower() == name]
    if gleich:
        return _fehler(
            "name_in_use",
            "Eine verbundene Cadwork-Instanz hat schon eine Datei namens %r "
            "offen (%s). Die Bridge waere danach nicht eindeutig zu finden."
            % (os.path.basename(ziel),
               ", ".join("Port %s" % e.get("port") for e in gleich)))
    try:
        (starter or _windows_starten)(ziel)
    except Exception as exc:                            # noqa: BLE001
        return _fehler("start_failed", "Start fehlgeschlagen: %s" % exc)
    return {"ok": True, "geoeffnet": ziel,
            "weg": "Windows-Dateiverknuepfung (.3d)",
            "naechster_schritt": (
                "Im Cadwork-Fenster dieser Datei einmal 'Open MCP CAD' "
                "klicken (Agent-Host per Computer Use, oder der Nutzer), "
                "dann wait_for_bridge(%r)." % ziel)}


# --- 3. Warten und pruefen --------------------------------------------------

_PFAD_CODE = ("import utility_controller as uc\n"
              "result = str(uc.get_3d_file_path())\n")


def _ordner_passt(gemeldet, ziel):
    """Passt der von Cadwork gemeldete Pfad zur erwarteten Datei?

    Ob `get_3d_file_path()` den Pfad der DATEI oder ihres ORDNERS liefert,
    ist nicht gemessen (die cwapi3d-Doku sagt nur "the 3D file path").
    Beide Lesarten werden deshalb verglichen — ein fremder Ordner faellt in
    beiden auf.
    """
    g = os.path.normcase(os.path.normpath(gemeldet or ""))
    z = os.path.normcase(os.path.normpath(ziel))
    if g.endswith(ENDUNG):
        return g == z
    return g == os.path.dirname(z)


def _standard_rufen(methode, params, port):
    return bridge_client.call(methode, params, port=port)


def _treffer_pruefen(eintrag, name, dokument, mit_pfad, rufen):
    """Prueft EINEN Registry-Treffer ueber die Bridge selbst.

    -> ("ok", Ergebnis) | ("fehler", Fehler-dict) | ("warten", Grund).
    "warten" heisst: noch nicht so weit (antwortet nicht, anderes Dokument)
    — ein spaeterer Versuch kann gelingen. "fehler" heisst: das wird nicht
    besser, und binden waere falsch.
    """
    port = int(eintrag["port"])
    try:
        info = rufen("get_document_info", {}, port) or {}
    except bridge_client.BridgeUnreachable as exc:
        return "warten", "Port %d antwortet nicht: %s" % (port, exc)
    except bridge_client.BridgeError as exc:
        return "warten", "Port %d meldet: %s" % (port, exc.message)
    gemeldet_port = info.get("port")
    gemeldet_dok = info.get("document_name") or ""
    if gemeldet_port is None or int(gemeldet_port) != port:
        return "fehler", _fehler(
            "port_mismatch",
            "Auf Port %d antwortet eine Instanz, die sich als Port %r meldet "
            "— Registry und Leitung passen nicht zusammen." % (port,
                                                             gemeldet_port))
    if gemeldet_dok.lower() != name.lower():
        return "warten", ("Port %d meldet ein anderes Dokument: %r"
                          % (port, gemeldet_dok))
    erg = {"ok": True, "port": port,
           "instanz": info.get("instanz") or eintrag.get("instanz"),
           "dokument": gemeldet_dok, "pfad": None, "ordner_geprueft": False}
    if not mit_pfad:
        return "ok", erg
    try:
        pfad = (rufen("execute_cwapi3d",
                      {"code": _PFAD_CODE, "result_var": "result",
                       "access_mode": "read",
                       "description": "wait_for_bridge: Pfad pruefen"},
                      port) or {}).get("result")
    except bridge_client.BridgeUnreachable as exc:
        return "warten", "Port %d antwortet nicht: %s" % (port, exc)
    except bridge_client.BridgeError as exc:
        return "fehler", _fehler("path_unverifiable", "Pfad der offenen "
                                 "Datei nicht lesbar: %s" % exc.message)
    if not _ordner_passt(pfad, dokument):
        return "fehler", _fehler(
            "wrong_folder", "Port %d hat %r offen, aber aus %r — erwartet "
            "war %r." % (port, gemeldet_dok, pfad, dokument))
    erg.update(pfad=pfad, ordner_geprueft=True)
    return "ok", erg


def warte_auf_bridge(dokument, timeout_s=120.0, intervall_s=1.0, *,
                     erwartet="", laufende=None, rufen=None,
                     uhr=time.monotonic, schlafen=time.sleep):
    """Wartet, bis GENAU EINE Instanz `dokument` offen hat, und prueft sie.

    `dokument` ist der volle Pfad der Datei (dann wird auch der Ordner
    geprueft) oder nur ihr Dateiname mit .3d. Gesucht wird der Dateiname
    exakt (ohne Gross/Klein), nicht als Teilstring.

    Geprueft wird ueber die Bridge SELBST, nicht nur ueber die Registry:
      * `get_document_info` auf dem gefundenen Port meldet denselben
        Dokumentnamen UND denselben Port;
      * bei vollem Pfad: `get_3d_file_path()` passt zum Ordner.
    Ein Eintrag zaehlt erst mit Dokumentnamen — der Kern traegt sich nach
    `listen()` mit leerem Namen ein und fuehrt ihn nach.

    `erwartet` ist der Riegel des Servers (OPEN_MCP_CAD_EXPECT_DOC): passt
    das Dokument nicht dazu, wird gar nicht erst gewartet.

    Abbruch OHNE Warten bis zum Ende bei: mehreren Treffern (kein Raten),
    fremdem Port auf der Leitung, fremdem Ordner, Bridge-Fehler beim Lesen
    des Pfads. Weiter gewartet wird, solange die Bridge nicht antwortet
    oder noch ein anderes Dokument meldet.
    """
    if not isinstance(dokument, str) or not dokument:
        return _fehler("path_missing", "Dokument fehlt.")
    name = os.path.basename(dokument)
    if os.path.splitext(name)[1].lower() != ENDUNG:
        return _fehler("wrong_extension", "Dokument muss auf %s enden (so "
                       "steht es in der Registry): %r" % (ENDUNG, dokument))
    mit_pfad = bool(os.path.isabs(dokument) and os.path.splitdrive(dokument)[0])
    if erwartet and erwartet.lower() not in name.lower():
        return _fehler("expect_doc_conflict",
                       "Der Server ist auf Dokumente mit %r verriegelt "
                       "(OPEN_MCP_CAD_EXPECT_DOC), gesucht ist %r."
                       % (erwartet, name))
    laufende = laufende or registry.laufende
    rufen = rufen or _standard_rufen
    ende = uhr() + float(timeout_s)
    zuletzt = "noch keine Instanz mit diesem Dokument eingetragen"

    while True:
        eintraege = laufende()
        treffer = [e for e in eintraege
                   if (e.get("dokument") or "").lower() == name.lower()]
        if len(treffer) > 1:
            return _fehler(
                "ambiguous",
                "%d verbundene Instanzen haben %r offen — nicht eindeutig, "
                "es wird nicht geraten." % (len(treffer), name),
                treffer=[{"port": e.get("port"), "instanz": e.get("instanz")}
                         for e in treffer])
        if treffer:
            art, wert = _treffer_pruefen(treffer[0], name, dokument,
                                         mit_pfad, rufen)
            if art != "warten":
                return wert
            zuletzt = wert
        if uhr() >= ende:
            return _fehler(
                "timeout",
                "Nach %.0f s keine bestaetigte Bridge fuer %r. Zuletzt: %s. "
                "Ist das Plugin 'Open MCP CAD' im Cadwork-Fenster dieser "
                "Datei geklickt? Eingetragen: %s"
                % (float(timeout_s), name, zuletzt,
                   "; ".join("Port %s %s" % (e.get("port"),
                                             e.get("dokument") or "(leer)")
                             for e in eintraege) or "nichts"))
        schlafen(intervall_s)
