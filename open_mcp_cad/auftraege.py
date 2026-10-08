# -*- coding: utf-8 -*-
"""Auftraege an die Bridge: ehrliche Fehlerantworten und Paketlaeufe.

mcp-frei, wie `registry.py`, `bridge_client.py` und `bootstrap.py`: die Gates
laufen im System-Python ohne `mcp`. `server.py` registriert nur die Werkzeuge.

PAKETLAUF (2026-09-25, Anlass: Probelauf einer Stabschale mit 286 Staeben
und 2288 Verbindungsmittelachsen). Ohne ihn muss ein Agent grosse Mengen
selbst zerlegen, und jedes Paket kostet einen eigenen Werkzeugaufruf, in dem
er die Koordinaten als Code-Text ausschreibt — bei 2288 Achsen hunderte
Kilobyte Zahlen, die ein Sprachmodell Zeichen fuer Zeichen erzeugen muesste.
Hier liegen die Daten in einer JSON-Datei; der Agent schreibt den Code EINMAL,
der Server schickt ihn je Paket mit anderen Daten an Cadwork. Jedes Paket
ist ein eigener Auftrag: Cadwork bleibt zwischen den Paketen bedienbar, der
Fortschrittsbalken im Dock kennt Stand und Ziel (`bauteile`, `lauf_gesamt`).
Das Feld `paketlauf` sagt dem Kern, dass ein Auftrag Paket k von n ist: in
'Auto' zieht er dann jedes Paket sofort nach (Film 2026-09-25: die Schrauben
eines Pakets erschienen und verschwanden bis zum Ende des Laufs).

Bewusst NICHT hier: irgendein Wissen darueber, was gebaut wird. Der Server
kennt nur Listen, Pakete und Code.
"""

import json
import math
import os
import time

from . import bridge_client

# Code-Grenze des Kerns (omcad_bridge_core.MAX_CODE_LENGTH). Hier nur, damit
# ein zu grosses Paket abgewiesen wird, BEVOR das erste gesendet ist — sonst
# liefe der Lauf bis dorthin und braeche mittendrin ab. Das Gate vergleicht
# den Wert mit der Quelle im Kern.
MAX_CODE = 100_000
# Groesser wird eine Datendatei nicht gelesen: sie landet ganz im Speicher
# des Servers und paketweise als Code-Text in Cadwork.
MAX_DATEN_BYTES = 20 * 1024 * 1024
# Wartezeit auf die Antwort EINES Pakets, wenn der Aufruf keine nennt. Ein
# Paket ist gewollt groesser als ein Einzelauftrag, und es wird mit dem
# Modell langsamer; 10 s (CADWORK_BRIDGE_TIMEOUT) sind dafuer zu knapp.
PAKET_TIMEOUT_VORGABE_S = 120.0
# Obergrenze fuer jede angegebene Wartezeit: ein Tippfehler (Millisekunden
# statt Sekunden) soll den Agenten nicht einen Tag lang warten lassen.
TIMEOUT_MAX_S = 3600.0


def _fehler(code, text, **mehr):
    return dict({"ok": False, "error": code, "message": text}, **mehr)


def wartezeit(timeout_s, vorgabe):
    """Die Antwort-Wartezeit in Sekunden: angegeben (begrenzt) oder Vorgabe."""
    try:
        wert = float(timeout_s or 0)
    except (TypeError, ValueError):
        wert = 0.0
    if wert <= 0:
        return float(vorgabe)
    return min(wert, TIMEOUT_MAX_S)


def fehler_antwort(exc):
    """Normalisierte Antwort, wenn die Bridge nicht (oder nicht rechtzeitig)
    antwortet. Drei Faelle, die der Agent verschieden behandeln MUSS:

      instanz_waehlen   nichts gesendet, unklar wohin
      antwort_fehlt     GESENDET, Ausgang offen — nicht wiederholen
      bridge_unreachable  nichts gesendet, Plugin laeuft nicht

    Bis 2026-09-25 fielen die letzten beiden zusammen: ein Auftrag, der in
    Cadwork 10,7 s lief und gelang, kam beim Agenten als "nicht erreichbar,
    Plugin klicken" an. Das laedt zum Wiederholen ein.
    """
    if isinstance(exc, bridge_client.InstanzUnklar):
        if exc.instanzen:
            weiter = ("Welche Datei gemeint ist, sagt der Nutzer (frag ihn, "
                      "wenn der Auftrag es nicht sagt); dann wait_for_bridge("
                      "dokument='<Datei>.3d') aufrufen, danach geht alles "
                      "dorthin.")
        else:
            weiter = ("Gerade ist kein Cadwork verbunden: der Nutzer oeffnet "
                      "die Datei in Cadwork und klickt 'Open MCP CAD', dann "
                      "wait_for_bridge(dokument='<Datei>.3d') aufrufen.")
        return {
            "ok": False,
            "error": "instanz_waehlen",
            "message": "%s Es wurde NICHTS gesendet. %s" % (exc.grund, weiter),
            "instanzen": exc.instanzen,
            "details": str(exc),
        }
    if isinstance(exc, bridge_client.AntwortFehlt):
        return {
            "ok": False,
            "error": "antwort_fehlt",
            "message": (
                "Der Auftrag wurde an Cadwork GESENDET, die Antwort kam aber "
                "nicht innerhalb von %.0f s. Er kann noch laufen oder schon "
                "fertig sein. NICHT wiederholen: get_connection_status() "
                "zeigt, ob er noch laeuft; danach das Ergebnis im Modell "
                "nachlesen. Fuer lange Auftraege timeout_s hoeher setzen."
                % exc.gewartet_s),
            "gewartet_s": exc.gewartet_s,
            "details": str(exc),
        }
    return {
        "ok": False,
        "error": "bridge_unreachable",
        "message": (
            "Cadwork-Bridge nicht erreichbar. Stelle sicher, dass Cadwork "
            "läuft und im Plugin-Menü 'Open MCP CAD' geklickt wurde."
        ),
        "details": str(exc),
    }


# --- Paketlauf ------------------------------------------------------------

def daten_laden(pfad):
    """-> (Liste, None) oder (None, Fehler-dict). Liest nur, aendert nichts."""
    if not isinstance(pfad, str) or not pfad.strip():
        return None, _fehler("path_missing", "daten_datei fehlt.")
    pfad = pfad.strip().strip('"')
    if not (os.path.isabs(pfad) and os.path.splitdrive(pfad)[0]):
        return None, _fehler(
            "path_not_absolute",
            "daten_datei muss ein absoluter Pfad mit Laufwerk sein: %r" % pfad)
    if os.path.splitext(pfad)[1].lower() != ".json":
        return None, _fehler("wrong_extension",
                             "daten_datei muss auf .json enden: %r" % pfad)
    if not os.path.isfile(pfad):
        return None, _fehler("file_missing", "daten_datei gibt es nicht: %s"
                             % pfad)
    groesse = os.path.getsize(pfad)
    if groesse > MAX_DATEN_BYTES:
        return None, _fehler(
            "file_too_large",
            "daten_datei hat %d Bytes, erlaubt sind %d." % (groesse,
                                                             MAX_DATEN_BYTES))
    try:
        with open(pfad, encoding="utf-8") as fh:
            daten = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, _fehler("bad_json", "daten_datei ist kein gueltiges "
                             "JSON: %s" % exc)
    if not isinstance(daten, list):
        return None, _fehler(
            "not_a_list", "daten_datei muss eine JSON-LISTE enthalten (ein "
            "Eintrag je Bauteil), gefunden: %s" % type(daten).__name__)
    if not daten:
        return None, _fehler("empty", "daten_datei enthaelt eine leere Liste.")
    return daten, None


def pakete_bauen(code, daten, groesse):
    """Der Auftragscode je Paket: Kopf mit den Paketdaten, dann `code`.

    Im Code stehen bereit:
        paket        die Eintraege dieses Pakets (Liste)
        paket_nr     1, 2, ...
        pakete       Anzahl Pakete
        paket_start  Index des ersten Eintrags in der ganzen Liste
    Die Daten gehen als JSON-Text hinein und werden in Cadwork mit `json`
    gelesen: so kommt jeder Wert unveraendert an, auch Umlaute.
    """
    n = int(math.ceil(len(daten) / float(groesse)))
    for k, start in enumerate(range(0, len(daten), groesse), 1):
        teil = daten[start:start + groesse]
        kopf = ("import json as _omcad_json\n"
                "paket = _omcad_json.loads(%r)\n"
                "paket_nr = %d\npakete = %d\npaket_start = %d\n"
                % (json.dumps(teil), k, n, start))
        yield kopf + code


def paketlauf(code, daten_datei, paket_groesse=50, beschreibung="",
              timeout_s=0, erwartet="", rufen=None):
    """Fuehrt `code` paketweise ueber die Eintraege von `daten_datei` aus.

    Alle Pakete werden VOR dem ersten Senden gebaut und gegen die Code-Grenze
    geprueft. Beim ersten Fehler hoert der Lauf auf; die Antwort sagt, welche
    Pakete fertig sind und was mit dem abgebrochenen ist — damit nichts
    doppelt entsteht.
    """
    rufen = rufen or bridge_client.call
    if not isinstance(code, str) or not code.strip():
        return _fehler("code_missing", "code fehlt.")
    try:
        groesse = int(paket_groesse)
    except (TypeError, ValueError):
        groesse = 0
    if groesse < 1:
        return _fehler("bad_package_size",
                       "paket_groesse muss eine ganze Zahl ab 1 sein.")
    daten, f = daten_laden(daten_datei)
    if f:
        return f
    codes = list(pakete_bauen(code, daten, groesse))
    n = len(codes)
    zu_gross = [k for k, c in enumerate(codes, 1) if len(c) > MAX_CODE]
    if zu_gross:
        return _fehler(
            "package_too_large",
            "%d von %d Paketen ueberschreiten die Code-Grenze von %d Zeichen "
            "(erstes: Paket %d, %d Zeichen). paket_groesse verkleinern. Es "
            "wurde NICHTS gesendet."
            % (len(zu_gross), n, MAX_CODE, zu_gross[0],
               len(codes[zu_gross[0] - 1])),
            pakete=n)
    warten = wartezeit(timeout_s, max(PAKET_TIMEOUT_VORGABE_S,
                                      bridge_client.BRIDGE_TIMEOUT_SECONDS))
    name = (beschreibung or "").strip() or "Paketlauf"
    ergebnisse = []
    # Was der Kern je Paket fuer das Nachziehen der Darstellung meldet
    # (paketweise in 'Auto', Kern ab 2.18): die Kosten stehen damit in der
    # Antwort, gemessen in Cadwork, nicht geschaetzt.
    nachgezogen = {"pakete": 0, "elemente": 0, "s": 0.0}
    t0 = time.monotonic()
    for k, c in enumerate(codes, 1):
        start = (k - 1) * groesse
        params = {
            "code": c,
            "result_var": "result",
            "description": "%s (Paket %d/%d)" % (name, k, n),
            "access_mode": "write",
            # Fuer den Fortschritt im Dock: so viele Bauteile in diesem
            # Paket, so viele im ganzen Lauf.
            "bauteile": len(daten[start:start + groesse]),
            "lauf_gesamt": len(daten),
            # Sagt dem Kern (ab 2.18), dass dies ein Paket eines Laufs ist:
            # in 'Auto' zieht er es dann sofort nach, statt die neuen
            # Bauteile bis zum Ende des Laufs zu verstecken (Film
            # 2026-09-25: Schrauben erschienen und verschwanden je Paket).
            # Ein eigenes Feld, nicht die Beschreibung — die ist Anzeige.
            # Aeltere Kerne ignorieren es.
            "paketlauf": {"paket": k, "pakete": n},
        }
        if erwartet:
            params["expect_document"] = erwartet
        try:
            antwort = rufen("execute_cwapi3d", params, antwort_timeout=warten)
        except bridge_client.BridgeUnreachable as exc:
            fehler = fehler_antwort(exc)
            offen = isinstance(exc, bridge_client.AntwortFehlt)
            gesendet = offen
        except bridge_client.BridgeError as exc:
            fehler = _fehler(exc.code, exc.message, details=exc.details)
            offen = False
            gesendet = True
        else:
            ergebnisse.append((antwort or {}).get("result"))
            info = (antwort or {}).get("paket_nachgezogen")
            if isinstance(info, dict):
                nachgezogen["pakete"] += 1
                nachgezogen["elemente"] += int(info.get("elemente") or 0)
                nachgezogen["s"] += float(info.get("s") or 0.0)
            continue
        if offen:
            was = ("Paket %d ist gesendet, sein Ausgang ist offen (kann noch "
                   "laufen). NICHT wiederholen, erst get_connection_status() "
                   "und dann im Modell nachsehen." % k)
        elif gesendet:
            was = ("Paket %d brach in Cadwork mit einem Fehler ab. Was es bis "
                   "dahin angelegt hat, bleibt im Modell; undo(1) nimmt dieses "
                   "Paket zurueck." % k)
        else:
            was = "Paket %d wurde NICHT ausgefuehrt." % k
        fehler.update({
            "pakete": n,
            "pakete_fertig": k - 1,
            "eintraege_fertig": start,
            "abgebrochen_bei_paket": k,
            "hinweis": ("Pakete 1 bis %d sind fertig (je ein Undo-Schritt). "
                        % (k - 1) if k > 1 else "Kein Paket ist fertig. ") + was,
            "ergebnisse": ergebnisse,
            "dauer_s": round(time.monotonic() - t0, 2),
        })
        fehler.update(_nachgezogen_feld(nachgezogen))
        return fehler
    return {
        "ok": True,
        "description": name,
        "pakete": n,
        "eintraege": len(daten),
        "ergebnisse": ergebnisse,
        "dauer_s": round(time.monotonic() - t0, 2),
        # Der Kern meldet je Auftrag die neuen Elemente an: ein Paket ist
        # ein Schritt in Cadworks Rueckgaengig.
        "undo_schritte": n,
        **_nachgezogen_feld(nachgezogen),
    }


def _nachgezogen_feld(summe):
    """{"nachgezogen": {...}}, wenn der Kern paketweise nachgezogen hat.

    Fehlt, wenn kein Paket es gemeldet hat: aelterer Kern, Stufe 'Langsam'
    oder 'Schnell' — dort gibt es nichts zu berichten, und eine Null saehe
    aus wie eine Messung.
    """
    if not summe["pakete"]:
        return {}
    return {"nachgezogen": {"pakete": summe["pakete"],
                            "elemente": summe["elemente"],
                            "s": round(summe["s"], 2)}}
