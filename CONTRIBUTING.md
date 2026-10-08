# Mitmachen

Danke fürs Interesse. Kurz, was hier gilt.

## Vor dem ersten Pull Request

Eine Zeile ins PR-Gespräch:

```
Ich stimme dem CLA in CLA.md zu.  <Name>  <E-Mail>  <Datum>
```

Warum, steht in [CLA.md](CLA.md).

## Was hierher gehört — und was nicht

**Hierher:** alles, was die Brücke betrifft. Nebenläufigkeit, Protokoll,
Freigaben, Oberfläche, Steckplätze, Anbindung weiterer Sprachmodelle,
gesicherte Erkenntnisse über die **cwapi3d-Schnittstelle**.

**Nicht hierher:** Konstruktionslogik und Fachwissen einer Branche. Keine
Bauteil-Generatoren, keine Detail-Kataloge, keine Bemessung. Das gehört in
ein eigenes Paket und wird über `OPEN_MCP_CAD_KNOWLEDGE` eingehängt — siehe
README. Ein Pull Request, der Holzbau (oder Stahlbau, oder Treppenbau) in
den Kern zieht, wird abgelehnt, egal wie gut er ist.

Der Grund ist nicht Geschmack: sobald hier eine Branche drinsteckt, tragen
alle anderen sie mit.

## Die Regeln der Codebasis

Sie sind nicht üblich, aber sie haben einen Grund. Kurz:

**1. Gemessen, nicht behauptet.** Eine Zahl in einem Kommentar oder in einer
Fehlermeldung ist eine Behauptung, solange sie nicht aus einer Messung
stammt. Wenn du schreibst "das dauert etwa 300 ms" — miss es.

**2. Jeder Vergleichstest braucht eine Kontrolle, die fehlschlagen MUSS.**
Sonst sieht ein Test, der gar nichts misst, wie ein bestandener Test aus.
Das ist hier zweimal passiert, beim zweiten Mal war die falsche Antwort das
Gegenteil der richtigen. Beispiel: `tests/test_wissen.py`, Prüfung W12.

**3. Lieber laut abbrechen als still das Falsche tun.** Ein Ordner, den es
nicht gibt, wird gemeldet. Ein Parameter, der nichts bewirkt, wird
abgelehnt. Eine Annahme, die kippt, wirft eine Ausnahme mit Ist-Wert,
Grenzwert und Auswegen im Text — nicht nur ein `False`.

**4. Kommentare erklären das WARUM, mit Herkunft.** Nicht "setzt den Port",
sondern warum dieser Weg und nicht der naheliegende — und woher man das
weiss. Die Kommentare in `cad_plugin/_core/` sind das Muster: sie erzählen
auch von den Wegen, die nicht funktioniert haben. Das ist kein Ballast, es
verhindert, dass jemand sie noch einmal geht.

**5. Eine Quelle.** Der Brücken-Kern steht einmal; die Steckplätze werden
daraus erzeugt und byteweise gegengeprüft. Änderst du den Kern:

```bash
python scripts/plugins_generieren.py
```

Die Steckplatz-Ordner **nie** von Hand ändern. Ausnahme ist Steckplatz A:
sein Dashboard, Chat und Icon sind handgepflegt (die Liste steht in
`HANDGEPFLEGT` im Generator und wird vom Gate geprüft).

## Vor dem Absenden

```bash
python tests/test_offline.py
python tests/test_wissen.py
python tests/test_a_prototyp.py
python scripts/plugins_generieren.py --pruefen
```

Mit PyQt6 zusätzlich `python tests/test_a_live.py` — es baut die Oberfläche
wirklich und bedient sie. Wer an der Oberfläche etwas ändert, muss dort
zeigen, dass es funktioniert: `test_a_prototyp.py` liest nur Quelltext und
kann über Verhalten nichts sagen.

Alles grün? Dann los.

## Commits

```
typ(bereich): beschreibung
```

`fix`, `feat`, `docs`, `test`, `refactor`. Bereich ist der Ordner oder das
Bauteil (`bridge`, `dashboard`, `wissen`, `generator`). Deutsch oder
Englisch, beides ist recht — bleib innerhalb eines Commits bei einer
Sprache.

## Fehlermeldungen

Hilfreich ist:

- Cadwork-Version und Python-Version
- der Steckplatz und was im Fenster "Open MCP CAD Verbindungen" stand
- die Logdatei aus `C:\Users\Public\OpenMcpCad_<X>.log`
- der kleinste Weg, es nachzustellen

"Es hängt" ohne den Zustand aus dem Fenster ist schwer zu greifen — dafür
gibt es `get_connection_status`, das auch antwortet, während gezeichnet wird.
