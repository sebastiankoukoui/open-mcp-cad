# -*- coding: utf-8 -*-
"""Suche im geladenen Wissen — fuer das Werkzeug get_working_examples.

Ohne `mcp` importierbar (Gate `tests/test_wissen.py` im System-Python).
`server.py` laedt das Wissen und ruft hier nur `beispiele_antwort`.

Anlass (2026-09-27): die Suche verglich den GANZEN Begriff mit id, Titel
und Beschreibung der Beispiele. Bekannte Probleme waren gar nicht
durchsuchbar — nur die Zusammenfassung der Stufen high/medium stand in der
Beschreibung von execute_cadwork_command, low-Eintraege nirgends. Jetzt:
jedes Wort des Begriffs muss vorkommen (Gross/Klein und Umlaute egal),
gesucht wird auch in Stichworten, Kategorie, Notizen und betroffenen
Funktionen, und zu einem Begriff kommen passende bekannte Probleme mit.
Das Feld `nachweis` (wie belegt, Version, Geltungsbereich) wird mitgegeben.
"""
import json
import re

_FALTEN = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "ae", "Ö": "oe", "Ü": "ue"})

# Felder, in denen gesucht wird. `code` und `nachweis` bewusst NICHT:
# Code nennt viele Funktionen nebenbei, Belege nennen Nachbarthemen —
# beides machte die Treffer unscharf.
_FELDER = ("id", "title", "description", "category", "notes", "stichworte",
           "affected_functions", "workaround")
_STARK = ("id", "title", "stichworte")


def _falten(text):
    return str(text).translate(_FALTEN).lower()


def _feldtext(eintrag, feld):
    wert = eintrag.get(feld)
    if isinstance(wert, (list, tuple)):
        return " ".join(str(w) for w in wert)
    return "" if wert is None else str(wert)


def woerter(begriff):
    """Suchbegriff in Woerter (Leerraum, Komma, Semikolon)."""
    return [w for w in re.split(r"[\s,;]+", _falten(begriff or "")) if w]


def suchen(eintraege, begriff):
    """Eintraege, in denen JEDES Wort des Begriffs vorkommt.

    Reihenfolge: zuerst Treffer in id/Titel/Stichworten, sonst die
    Reihenfolge der Quelle. Leerer Begriff = alle.
    """
    liste = [e for e in (eintraege or []) if isinstance(e, dict)]
    ws = woerter(begriff)
    if not ws:
        return list(liste)
    treffer = []
    for i, e in enumerate(liste):
        alles = _falten(" ".join(_feldtext(e, f) for f in _FELDER))
        if all(w in alles for w in ws):
            stark = _falten(" ".join(_feldtext(e, f) for f in _STARK))
            treffer.append((0 if all(w in stark for w in ws) else 1, i, e))
    treffer.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in treffer]


def _beispiel(e):
    zeile = {"id": e.get("id"), "title": e.get("title", ""),
             "code": e.get("code", ""), "notes": e.get("notes", "")}
    if e.get("nachweis"):
        zeile["nachweis"] = e["nachweis"]
    return zeile


def _problem(e):
    zeile = {"art": "bekanntes_problem", "id": e.get("id"),
             "title": e.get("title", ""), "severity": e.get("severity", ""),
             "description": e.get("description", ""),
             "workaround": e.get("workaround", "")}
    if e.get("nachweis"):
        zeile["nachweis"] = e["nachweis"]
    return zeile


def beispiele_antwort(knowledge, category=""):
    """Die Antwort von get_working_examples als JSON-Text.

    Ohne Begriff: alle Beispiele (wie bisher). Mit Begriff: passende
    Beispiele, danach passende bekannte Probleme (`art`).
    """
    beispiele = (knowledge.get("examples") or {}).get("examples", [])
    gefunden = [_beispiel(e) for e in suchen(beispiele, category)]
    if category:
        gefunden += [_problem(e) for e in
                     suchen(knowledge.get("issues") or [], category)]
    if not gefunden:
        return json.dumps(
            {"error": "Keine Beispiele für '%s' gefunden." % category},
            ensure_ascii=False)
    return json.dumps(gefunden, indent=2, ensure_ascii=False)
