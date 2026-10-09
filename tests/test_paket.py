#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer das Verteilpaket (scripts/paket_bauen.py).

    python tests/test_paket.py

Baut das Paket in einen Temp-Ordner und misst, was drin ist — nicht, was
das Skript verspricht. Jede Pruefung hat eine Kontrolle, die rot werden
muss (Arbeitsregel 2). Den Installer selbst prueft dieses Gate NICHT:
Profilwahl, Cadwork-Version und Schlussmeldung misst `test_installer.py`,
den Server-Teil (pip, Internet) keines.
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import deployment_pruefen as DP                             # noqa: E402
import oeffentlich_exportieren as E                         # noqa: E402
import paket_bauen as P                                     # noqa: E402
import plugins_generieren as G                              # noqa: E402

# Ein Name, den es im Repo nicht gibt — das Muster der Kontrollen.
# Zusammengesetzt: am Stueck stuende er in dieser Datei, und der Export
# (T9) schluege an ihr selbst an.
ERIKA = "Erika" + " Musterfrau"
NAME = re.compile(ERIKA)

_ergebnisse = []


# --- Anleitung gegen die Quelle (Etappe E, 2026-09-26) ----------------------
# Plan B.14: die Deinstallation nannte chat.json und die Tresor-Eintraege
# nicht, obwohl der Chat beides anlegt. Und das Dock ist nur deutsch: jede
# Beschriftung, die eine Anleitung zitiert, muss es dort genau so geben.
# Was verlangt wird, kommt aus der QUELLE (Arbeitsregel 3): Anbieter-Tabelle,
# Tresor-Praefix und Ort von chat.json aus omcad_a_anbieter, Server-Ordner
# und Benutzervariable aus install.ps1, die Beschriftungen aus den
# Zeichenketten der Plugin-Module.

PLUGIN_ORDNER = os.path.join(REPO, "cad_plugin", "Open MCP CAD")
UI_MODULE = ("omcad_a_dashboard.py", "omcad_a_chat.py", "omcad_a_anbieter.py")


def _anbieter_modul():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "omcad_anbieter_paketgate",
        os.path.join(PLUGIN_ORDNER, "omcad_a_anbieter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quelle_fuer_anleitung():
    """Was die Anleitungen nennen muessen, gelesen aus dem Code."""
    import ast
    A = _anbieter_modul()
    alt = {k: os.environ.get(k) for k in
           ("APPDATA", "OPEN_MCP_CAD_CHAT_EINSTELLUNGEN")}
    try:
        os.environ["APPDATA"] = "%APPDATA%"
        os.environ.pop("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN", None)
        chat_json = A._einstellungs_datei()
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    ps1 = open(os.path.join(P.VERTEILUNG, "install.ps1"),
               encoding="utf-8").read()
    server = re.search(r'\$PythonZiel = \(Join-Path \$env:LOCALAPPDATA '
                       r'"([^"\\]+)', ps1).group(1)
    variablen = re.findall(r'SetEnvironmentVariable\("([^"]+)"', ps1)
    texte = set()
    for m in UI_MODULE:
        baum = ast.parse(open(os.path.join(PLUGIN_ORDNER, m),
                              encoding="utf-8").read())
        texte |= {n.value for n in ast.walk(baum)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    namen = {a["id"]: a["name"] for a in A.ANBIETER}
    lokal = [a for a in A.ANBIETER if a["id"] in ("ollama", "lmstudio")]
    return {
        "loeschen": [os.path.dirname(chat_json),
                     "%LOCALAPPDATA%\\" + server] + variablen,
        "tresor": [A.TRESOR_PRAEFIX + a["id"] for a in A.ANBIETER
                   if a.get("schluessel") not in (None, "keiner")],
        "chat": [namen["eigen"]] + [a["name"] for a in lokal]
                + [":%d/v1" % int(re.search(r":(\d+)/", a["basis"]).group(1))
                   for a in lokal],
        "texte": texte,
    }


def _abschnitte(text):
    """(Chat-Abschnitt, der Abschnitt danach = Deinstallation)."""
    teile = re.split(r"(?m)^## ", text)
    for i, teil in enumerate(teile):
        if teil.startswith("Chat") and i + 1 < len(teile):
            return teil, teile[i + 1]
    return "", ""


def zitierte_beschriftungen(deutsch):
    """Alles in „…“ im deutschen Chat-Abschnitt."""
    return re.findall(r"„([^“]+)“", _abschnitte(deutsch)[0])


def anleitung_luecken(text, quelle, deutsch):
    """-> Liste dessen, was in dieser Anleitung fehlt oder nicht stimmt."""
    chat, weg = _abschnitte(text)
    if not chat or not weg:
        return ["kein Chat- oder Deinstallations-Abschnitt"]
    luecken = ["Deinstallation ohne %s" % x
               for x in quelle["loeschen"] + quelle["tresor"] if x not in weg]
    luecken += ["Chat ohne %s" % x for x in quelle["chat"] if x not in chat]
    for b in zitierte_beschriftungen(deutsch):
        if text is deutsch:
            if not any(b in t for t in quelle["texte"]):
                luecken.append("„%s“ steht so nicht im Dock" % b)
        elif b not in chat:
            luecken.append("Beschriftung „%s“ fehlt" % b)
    return luecken


def anleitung_pruefen():
    quelle = quelle_fuer_anleitung()
    namen = sorted(n for n in os.listdir(P.VERTEILUNG)
                   if re.fullmatch(r"ANLEITUNG(\.[a-z]{2})?\.md", n))
    texte = {n: open(os.path.join(P.VERTEILUNG, n), encoding="utf-8").read()
             for n in namen}
    deutsch = texte["ANLEITUNG.md"]
    zitate = zitierte_beschriftungen(deutsch)
    pruefe("T11 Quelle gelesen: %d Tresor-Eintraege, %d Orte, %d "
           "Beschriftungen zitiert" % (len(quelle["tresor"]),
                                       len(quelle["loeschen"]), len(zitate)),
           len(quelle["tresor"]) >= 3 and len(quelle["loeschen"]) >= 3
           and len(zitate) >= 10, (quelle["tresor"], quelle["loeschen"]))
    for n in namen:
        luecken = anleitung_luecken(texte[n], quelle, deutsch)
        pruefe("T11 %s: Deinstallation vollstaendig, Chat mit «Eigene "
               "Adresse», Beschriftungen wie im Dock" % n, not luecken,
               luecken[:4])
    # KONTROLLEN: je eine Luecke, die das Gate sehen MUSS.
    en = texte["ANLEITUNG.en.md"]
    faelle = {
        "Beschriftung, die es im Dock nicht gibt":
            (deutsch.replace("„Wahl entfernen“", "„Auswahl löschen“"), True),
        "Uebersetzung ohne eine Beschriftung":
            (en.replace('"Wahl entfernen"', '"remove choice"'), False),
        "Tresor-Eintrag fehlt":
            (deutsch.replace("`Open MCP CAD/eigen`", "`Open MCP CAD/…`"),
             True),
        "chat.json-Ordner fehlt":
            (deutsch.replace("%APPDATA%\\OpenMcpCad", "%APPDATA%\\Cadwork"),
             True),
        "falscher Port fuer Ollama auf einem anderen Rechner":
            (deutsch.replace(":11434/v1", ":11435/v1"), True),
    }
    rot = {}
    for titel, (mutant, ist_deutsch) in faelle.items():
        geaendert = mutant != (deutsch if ist_deutsch else en)
        # Der deutsche Mutant ist zugleich die Vorlage der Zitate.
        luecken = anleitung_luecken(mutant, quelle,
                                    mutant if ist_deutsch else deutsch)
        rot[titel] = geaendert and bool(luecken)
    pruefe("T11-K KONTROLLEN: jede eingebaute Luecke faellt auf",
           all(rot.values()), [t for t, r in rot.items() if not r])


# --- Hinweis fuer KI-Assistenten (Rueckmeldung 2026-09-29) ------------------
# Die Codex-App las das Plugin, sah dessen eigenes TCP-Protokoll und wollte
# erst "einen kleinen Adapter" bauen. README(.xx).md und ANLEITUNG(.xx).md
# tragen deshalb ganz oben einen Abschnitt fuer KI-Assistenten, im Paket
# zusaetzlich als Programmdateien/FUER_KI_ASSISTENTEN.md. Was er nennen muss,
# kommt aus der QUELLE (Arbeitsregel 3): Name, Servermodul und die Eintraege
# aus open_mcp_cad/ki_eintragen.py (die Eintraege, die es WIRKLICH schreibt,
# in eine Temp-Welt geschrieben und zurueckgelesen), Server-Python und
# Pruefbefehl aus install.ps1, Ports und "Bereit" aus dem Kern, der
# Konsolenbefehl aus pyproject.toml.

KERN = os.path.join(REPO, "cad_plugin", "_core", "omcad_bridge_core.py")


def _ki_modul():
    """open_mcp_cad/ki_eintragen.py DIESES Checkouts (das System-Python hat
    open_mcp_cad als -e aus einem anderen Ordner)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "omcad_ki_eintragen_paketgate",
        os.path.join(REPO, "open_mcp_cad", "ki_eintragen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quelle_fuer_ki(K=None):
    """Was der Abschnitt fuer KI-Assistenten nennen muss, aus dem Code."""
    import json
    import tomllib
    K = K or _ki_modul()
    platz = "<PYTHON>"
    with tempfile.TemporaryDirectory(prefix="omcad_ki_") as t:
        codex = os.path.join(t, "config.toml")
        desktop = os.path.join(t, "claude_desktop_config.json")
        K.codex_eintragen(codex, platz)
        K.desktop_eintragen(desktop, platz)
        codex_soll = tomllib.loads(open(codex, encoding="utf-8").read())
        desktop_soll = json.loads(open(desktop, encoding="utf-8").read())

        def nie(*_a, **_k):
            raise OSError("im Gate wird nichts gestartet")
        r = K.claude_code_eintragen("claude.exe", platz,
                                    env={"USERPROFILE": t, "PATH": ""},
                                    ausfuehren=nie)
    claude = r["text"].split("Von Hand: ", 1)[1].strip()
    ps1 = open(os.path.join(P.VERTEILUNG, "install.ps1"),
               encoding="utf-8").read()
    ziel = re.search(r'\$PythonZiel = \(Join-Path \$env:LOCALAPPDATA '
                     r'"([^"]+)"\)', ps1).group(1)
    pyw = re.search(r'Join-Path \$PythonZiel "(Scripts\\pythonw\.exe)"',
                    ps1).group(1)
    probe = re.search(r'& \$vpy -c "(import [\w.]+)"', ps1).group(1)
    kern = open(KERN, encoding="utf-8").read()
    von, bis = (re.search(r"(?m)^%s = (\d+)" % n, kern).group(1)
                for n in ("PORT_VON", "PORT_BIS"))
    bereit = re.search(r'"ready": "([^"]+)"', kern).group(1)
    return {
        "name": K.NAME,
        "modul": K.ARGS[-1],
        "start": " ".join(["python"] + list(K.ARGS)),
        "codex": codex_soll, "desktop": desktop_soll, "claude": claude,
        "python": "%%LOCALAPPDATA%%\\%s\\%s" % (ziel, pyw),
        "probe": probe,
        "ports": "%s–%s" % (von, bis),
        "bereit": "**%s**" % bereit,
        "installieren": P.INSTALLIEREN,
    }


def _codeblock(abschnitt, art):
    import textwrap
    m = re.search(r"```%s\n(.*?)^\s*```" % art, abschnitt, re.S | re.M)
    return textwrap.dedent(m.group(1)) if m else None


def ki_luecken(text, quelle):
    """-> Liste dessen, was am Abschnitt fuer KI-Assistenten in einem Text
    fehlt oder nicht stimmt."""
    import json
    import tomllib
    abschnitt = P.ki_abschnitt(text)
    if abschnitt is None:
        return ["kein Abschnitt fuer KI-Assistenten"]
    aus = []
    erste = re.search(r"(?m)^## .*$", text)
    if not abschnitt.startswith(erste.group(0) + "\n"):
        aus.append("nicht die erste Ueberschrift ##")
    if "For AI assistants" not in erste.group(0):
        aus.append("Ueberschrift ohne 'For AI assistants'")
    flach = " ".join(abschnitt.split())
    for was in ("name", "start", "claude", "python", "probe", "ports",
                "bereit", "installieren"):
        if quelle[was] not in flach:
            aus.append("nennt %s nicht: %s" % (was, quelle[was]))
    if "127.0.0.1" not in abschnitt:
        aus.append("nennt 127.0.0.1 nicht")
    # ChatGPT (die Chat-App) kann es nicht, die Codex-App schon: EIN Absatz.
    if not any("ChatGPT" in x and "Codex" in x
               for x in re.split(r"\n\s*\n", abschnitt)):
        aus.append("kein Absatz ChatGPT -> Codex-App")
    try:
        toml = tomllib.loads(_codeblock(abschnitt, "toml") or "")
    except tomllib.TOMLDecodeError as exc:
        toml = "kaputt: %s" % exc
    if toml != quelle["codex"]:
        aus.append("Codex-Eintrag != ki_eintragen: %s" % (toml,))
    try:
        js = json.loads(_codeblock(abschnitt, "json") or "null")
    except ValueError as exc:
        js = "kaputt: %s" % exc
    if js != quelle["desktop"]:
        aus.append("Claude-Desktop-Eintrag != ki_eintragen: %s" % (js,))
    return aus


def ki_texte():
    """-> {(Sprache, "README"|"ANLEITUNG"): Text}."""
    aus = {}
    for sp, pfad in P.anleitung_quellen().items():
        aus[(sp, "ANLEITUNG")] = open(pfad, encoding="utf-8").read()
        readme = os.path.join(REPO, "README%s.md"
                              % ("" if sp == "de" else "." + sp))
        aus[(sp, "README")] = (open(readme, encoding="utf-8").read()
                               if os.path.isfile(readme) else "")
    return aus


def ki_hinweis_pruefen():
    import tomllib
    quelle = quelle_fuer_ki()
    # Das Servermodul aus ki_eintragen gibt es wirklich, und es ist das des
    # Konsolenbefehls aus pyproject.toml.
    pyproject = tomllib.loads(open(os.path.join(REPO, "pyproject.toml"),
                                   encoding="utf-8").read())
    skripte = pyproject["project"]["scripts"]
    datei = os.path.join(REPO, *quelle["modul"].split(".")) + ".py"
    pruefe("T18 Quelle: %s, Modul %s (Datei da, = Konsolenbefehl), Eintraege "
           "aus ki_eintragen geschrieben und gelesen"
           % (quelle["name"], quelle["modul"]),
           os.path.isfile(datei)
           and skripte.get(quelle["name"], "").split(":")[0] == quelle["modul"]
           and quelle["codex"]["mcp_servers"][quelle["name"]]["args"][-1]
           == quelle["modul"] and quelle["claude"].startswith("claude mcp add"),
           (datei, skripte, quelle["claude"]))
    texte = ki_texte()
    sprachen = sorted({sp for sp, _a in texte})
    pruefe("T18 Abschnitt in %s, je README und ANLEITUNG"
           % ", ".join(sprachen), {"de", "en", "fr", "it"} <= set(sprachen),
           sprachen)
    for (sp, art), text in sorted(texte.items()):
        luecken = ki_luecken(text, quelle)
        pruefe("T18 %s %s: erster Abschnitt, Server/Eintraege/Pfad/Ports aus "
               "der Quelle, ChatGPT -> Codex" % (art, sp), not luecken,
               luecken[:4])
    for sp in sprachen:
        pruefe("T18 %s: README und ANLEITUNG tragen denselben Abschnitt" % sp,
               P.ki_abschnitt(texte[(sp, "README")])
               == P.ki_abschnitt(texte[(sp, "ANLEITUNG")]))

    # KONTROLLEN: je eine eingebaute Luecke MUSS auffallen.
    de, en = texte[("de", "ANLEITUNG")], texte[("en", "ANLEITUNG")]
    fr_readme, it = texte[("fr", "README")], texte[("it", "ANLEITUNG")]
    a = P.ki_abschnitt(de)
    faelle = {
        "Abschnitt fehlt (README fr)":
            (fr_readme.replace("ki-assistenten:anfang", "entfernt"),
             fr_readme),
        "falsches Servermodul (it)":
            (it.replace("open_mcp_cad.server", "open_mcp_cad.bruecke"), it),
        "python.exe statt pythonw.exe (de)":
            (de.replace("Scripts\\pythonw.exe", "Scripts\\python.exe"), de),
        "Codex-Eintrag ohne args (en)":
            (en.replace('args = ["-m", "open_mcp_cad.server"]\n', "", 1), en),
        "Desktop-Eintrag unter anderem Namen (de)":
            (de.replace('"open-mcp-cad": { "command"',
                        '"cadwork": { "command"', 1), de),
        "anderer Port-Bereich (en)": (en.replace("53127–53199", "53127"), en),
        "Abschnitt ans Ende gerueckt (de)":
            (de.replace(a, "", 1).replace("<!-- ki-assistenten:anfang -->\n"
                                          "<!-- ki-assistenten:ende -->", "")
             + "\n<!-- ki-assistenten:anfang -->\n" + a
             + "<!-- ki-assistenten:ende -->\n", de),
        "ohne ChatGPT-Absatz (en)":
            (re.sub(r"ChatGPT in the browser or on the phone.*?(?=<!-- ki-)",
                    "", en,
                    flags=re.S), en),
    }
    rot = {t: m != o and bool(ki_luecken(m, quelle))
           for t, (m, o) in faelle.items()}
    # README und ANLEITUNG auseinandergelaufen
    en_readme = texte[("en", "README")]
    anders = en_readme.replace("Never talk to the plugin yourself",
                               "Avoid talking to the plugin")
    rot["README en weicht von ANLEITUNG en ab"] = (
        anders != en_readme
        and P.ki_abschnitt(anders) != P.ki_abschnitt(en))
    # Aendert sich die QUELLE (anderer Eintragsname in ki_eintragen), muss
    # der unveraenderte Text rot werden: gelesen wird der Code, keine Kopie.
    K = _ki_modul()
    K.NAME = "omcad-anders"
    rot["Quelle geaendert (NAME in ki_eintragen)"] = bool(
        ki_luecken(de, quelle_fuer_ki(K)))
    pruefe("T18-K KONTROLLEN: jede eingebaute Luecke faellt auf",
           all(rot.values()), [t for t, r in rot.items() if not r])


def ki_hinweis_paket_pruefen(t, ordner):
    """T18b die Datei im gebauten Paket: jede Sprache, erzeugt aus den
    Anleitungen; fehlt einer Anleitung der Abschnitt, bricht bauen ab."""
    pfad = os.path.join(ordner, P.UNTERORDNER, P.KI_HINWEIS)
    inhalt = open(pfad, encoding="utf-8").read() if os.path.isfile(pfad) \
        else ""
    quellen = P.anleitung_quellen()
    teile = {sp: P.ki_abschnitt(open(q, encoding="utf-8").read())
             for sp, q in quellen.items()}
    da = all(x and x in inhalt for x in teile.values())
    pruefe("T18b %s/%s im Paket: Abschnitt aller %d Anleitungen, Deutsch "
           "zuerst" % (P.UNTERORDNER, P.KI_HINWEIS, len(quellen)),
           len(teile) >= 4 and da and inhalt == P.ki_hinweis_text()
           and inhalt.index(teile["de"]) == min(inhalt.index(x)
                                                for x in teile.values()),
           pfad)
    # KONTROLLE: eine Anleitung ohne den Abschnitt bricht ab, mit Namen.
    falle = os.path.join(t, "ki_falle")
    os.makedirs(falle, exist_ok=True)
    kaputt = dict(quellen)
    ziel = os.path.join(falle, "ANLEITUNG.fr.md")
    with io.open(ziel, "w", encoding="utf-8") as fh:
        fh.write(open(quellen["fr"], encoding="utf-8").read().replace(
            "ki-assistenten:ende", "weg"))
    kaputt["fr"] = ziel
    try:
        P.ki_hinweis_text(kaputt)
        k = ""
    except P.PaketFehler as exc:
        k = str(exc)
    pruefe("T18b-K KONTROLLE: eine Anleitung ohne Abschnitt bricht den Bau "
           "ab und wird genannt", "ANLEITUNG.fr.md" in k, k[:100])


# --- Spuren privater Teile (2026-09-28, Muster lokal seit 2026-10-01) -------
# Rueckmeldung 2026-09-28: ein Audit fand Spuren eines privaten Repos in
# handgepflegten Dateien, die der Export veroeffentlicht haette.
# persoenlich.txt faengt das nicht (keine Namen). Seit 2026-10-01 stehen
# die Muster NICHT mehr im Repo - eingecheckt haette der Export genau die
# Liste veroeffentlicht, die sagt, was privat ist -, sondern lokal in
# privat_spuren.txt, mit eigenen Beispielen ("#+") und Fehlalarmen ("#-").
# Hier stehen deshalb nur ERFUNDENE Muster (fuer den Mechanismus); die
# echten prueft das Gate, wenn die lokale Datei da ist.

#: Ein erfundenes Muster, das es im Repo nicht gibt. Zusammengesetzt: am
#: Stueck stuende es in dieser Datei, und der Export schluege an ihr an.
SYNTH_WORT = "Spur" + "_ohne_" + "Sinn"
SYNTH_SPUREN = [re.compile(SYNTH_WORT, re.I)]
#: Eine erfundene privat_spuren.txt (Format wie die echte), fuer T12f.
SYNTH_DATEI = "\n".join((
    "# Kommentar, kein Muster",
    "geheim_[a]bc",
    "(?-i:GROSS_[x])",
    "",
    "#+ ein Geheim_ABC hier",
    "#+ GROSS_x",
    "#- gross_x",
    "#- geheim_ab",
    "#+",
    "#-   ")) + "\n"
#: Die oeffentliche Schnittstelle: kein Spuren-Muster darf sie treffen
#: (cwapi3d der Endtypen, Lader des Fachwissens, Erweiterungs-Haken,
#: Beispieldokument).
SPUR_OEFFENTLICH = ("endtype_controller", "Endtyp", "Endtypen",
                    "detail_catalog.json", "rules.md", "omcad_bridge_core.py",
                    "Seeblick Erdgeschoss", "OPEN_MCP_CAD_ERWEITERUNGEN",
                    "open_mcp_cad/erweiterungen.py", "OPEN_MCP_CAD_PORT",
                    "Open MCP CAD")


def beispiele_luecken(muster, treffen, harmlos):
    """-> (Muster ohne Beispiel, Beispiele ohne Muster, Fehlalarme)."""
    tot = [m.pattern for m in muster if not any(m.search(b) for b in treffen)]
    ungetroffen = [b for b in treffen if not any(m.search(b) for m in muster)]
    fehlalarm = [h for h in harmlos if any(m.search(h) for m in muster)]
    return tot, ungetroffen, fehlalarm


def unabhaengig_suchen(ordner, muster):
    """Eigene Suche, ohne paket_bauen: jede Datei (ausser .git) als UTF-8
    und als latin-1 gelesen, jedes Muster ueber den ganzen Text. -> sortierte
    relative Pfade mit Treffer (mit "/")."""
    treffer = set()
    for wurzel, dirs, namen in os.walk(ordner):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in namen:
            p = os.path.join(wurzel, n)
            with open(p, "rb") as fh:
                daten = fh.read()
            text = daten.decode("utf-8", "replace") + "\n" + \
                daten.decode("latin-1")
            if any(m.search(text) for m in muster):
                treffer.add(os.path.relpath(p, ordner).replace("\\", "/"))
    return sorted(treffer)


#: Eine Wissensdatei wie die erzeugten (Kopf, zwei Eintraege, verschachtelte
#: "id" in einem davon) — fuer T12w.
WISSEN_PROBE = {
    "meta": {"hinweis": "ERZEUGT"},
    "issues": [
        {"id": "erster_eintrag", "title": "harmlos",
         "nachweis": {"id": "nicht_der_eintrag"}},
        {"id": "zweiter_eintrag", "title": "Spur",
         "workaround": "steht hier"},
    ]}


def _wissen_falsch(t):
    """-> Abweichungen von wissen_eintraege gegen WISSEN_PROBE (leer =
    richtig): Treffer im Kopf, im ersten Eintrag (auch in seiner
    verschachtelten "id"-Zeile), im zweiten und eine kaputte Datei."""
    probe = os.path.join(t, "wissen_probe")
    os.makedirs(probe, exist_ok=True)
    text = json.dumps(WISSEN_PROBE, indent=2, ensure_ascii=False)
    with io.open(os.path.join(probe, "k.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    with io.open(os.path.join(probe, "kaputt.json"), "w",
                 encoding="utf-8") as fh:
        fh.write("{nicht json\n")
    zeilen = text.splitlines()

    def nr(teil):
        return next(i for i, z in enumerate(zeilen, 1) if teil in z)
    faelle = [(["k.json:%d" % nr("ERZEUGT")], ["k.json:(Kopf)"]),
              (["k.json:%d" % nr("harmlos")], ["k.json:erster_eintrag"]),
              (["k.json:%d" % nr("nicht_der_eintrag")],
               ["k.json:erster_eintrag"]),
              (["k.json:%d" % nr("steht hier"), "k.json:%d" % nr("Spur")],
               ["k.json:zweiter_eintrag"]),
              (["kaputt.json:1"], ["kaputt.json:(kein JSON)"])]
    return [(f, soll, P.wissen_eintraege(probe, f)) for f, soll in faelle
            if P.wissen_eintraege(probe, f) != soll]


def spuren_datei_pruefen(t):
    """T12f: das Format der lokalen Datei an einer ERFUNDENEN Datei
    (Muster, Kommentare, "#+"/"#-", Gross/Klein, leere Beispielzeilen)."""
    datei = os.path.join(t, "synth_spuren.txt")
    with io.open(datei, "w", encoding="utf-8") as fh:
        fh.write(SYNTH_DATEI)
    muster = P.private_muster(datei)
    treffen, harmlos = P.private_beispiele(datei)
    luecken = beispiele_luecken(muster, treffen, harmlos)
    pruefe("T12f privat_spuren.txt gelesen: 2 Muster (Kommentar und "
           "Beispiele keine), Gross/Klein egal ausser (?-i:), je 2 "
           "Beispiele/Fehlalarme, leere ausgelassen",
           [m.pattern for m in muster] == ["geheim_[a]bc", "(?-i:GROSS_[x])"]
           and treffen == ["ein Geheim_ABC hier", "GROSS_x"]
           and harmlos == ["gross_x", "geheim_ab"]
           and luecken == ([], [], []), (muster, treffen, harmlos, luecken))
    fehlt = os.path.join(t, "gibt_es_nicht.txt")
    pruefe("T12f ohne Datei: keine Muster, keine Beispiele",
           P.private_muster(fehlt) == []
           and P.private_beispiele(fehlt) == ([], []))
    # KONTROLLE: ein Muster ohne Beispiel, ein Beispiel ohne Muster und ein
    # Fehlalarm fallen auf.
    k = beispiele_luecken(muster + [re.compile("nie_belegt")],
                          treffen + ["kein Muster trifft"],
                          harmlos + ["GEHEIM_abc"])
    pruefe("T12f-K KONTROLLE: Muster ohne Beispiel, Beispiel ohne Muster und "
           "Fehlalarm fallen auf",
           k == (["nie_belegt"], ["kein Muster trifft"], ["GEHEIM_abc"]), k)


def echte_spuren_pruefen(t, echte):
    """T12e/T12-K(a) gegen die lokale privat_spuren.txt: jedes Muster hat
    ein Beispiel, jedes Beispiel faellt auf (auch durch die Dateisuche),
    kein Fehlalarm, die oeffentliche Schnittstelle bleibt stumm."""
    treffen, harmlos = P.private_beispiele()
    tot, ungetroffen, fehlalarm = beispiele_luecken(echte, treffen, harmlos)
    pruefe("T12-K privat_spuren.txt: jedes der %d Muster trifft ein "
           "Beispiel, jedes der %d Beispiele wird getroffen"
           % (len(echte), len(treffen)),
           treffen and not tot and not ungetroffen, (tot, ungetroffen))
    oeffentlich = [h for h in SPUR_OEFFENTLICH
                   if any(m.search(h) for m in echte)]
    pruefe("T12-K privat_spuren.txt: %d Fehlalarm-Texte und die oeffentliche "
           "Schnittstelle bleiben stumm" % len(harmlos),
           not fehlalarm and not oeffentlich, (fehlalarm, oeffentlich))
    probe = os.path.join(t, "spuren_echt")
    os.makedirs(probe, exist_ok=True)
    for i, b in enumerate(treffen):
        with io.open(os.path.join(probe, "s%03d.py" % i), "w",
                     encoding="utf-8") as fh:
            fh.write("# ok\nx = %r\n" % b)
    with io.open(os.path.join(probe, "harmlos.py"), "w",
                 encoding="utf-8") as fh:
        fh.write("\n".join("y = %r" % h for h in harmlos + list(
            SPUR_OEFFENTLICH)) + "\n")
    funde, _a = P.private_spuren(probe)
    orte = sorted(x.replace("\\", "/") for x in funde)
    soll = sorted("s%03d.py:2" % i for i in range(len(treffen)))
    pruefe("T12e jedes Beispiel faellt in einer Datei auf (%d), Fehlalarm-"
           "Texte und Schnittstelle nicht" % len(treffen), orte == soll,
           sorted(set(orte) ^ set(soll))[:10])


def spuren_pruefen(t, klon, export, echte):
    # T12 der echte Export (aus T9 im Klon) ist frei von Spuren; die
    # ausgenommenen (erzeugtes Wissen) werden GENANNT, nicht verschwiegen.
    funde, aus = P.private_spuren(klon, echte or SYNTH_SPUREN)
    pruefe("T12 Export: keine Spur privater Teile in handgepflegten Dateien "
           "(%s)" % ("privat_spuren.txt, %d Muster" % len(echte) if echte
                     else "ohne privat_spuren.txt nur ein erfundenes Muster"),
           not funde, funde[:10])
    if not echte:
        print("  [info] privat_spuren.txt fehlt (%s) - T12e, T12-K "
              "(Beispiele) und T20 liefen nicht" % P.PRIVAT_SPUREN)
    print("  [info] T12 ausgenommen (%s, erzeugt, im privaten Repo zu "
          "bereinigen): %d Stellen%s" % (
              ", ".join(P.SPUREN_AUSGENOMMEN), len(aus),
              (": " + ", ".join(aus)) if aus else ""))
    print("  [info] T12 Eintraege dahinter: %s"
          % ", ".join(P.wissen_eintraege(klon, aus)))
    spuren_datei_pruefen(t)
    if echte:
        echte_spuren_pruefen(t, echte)
    falsch = _wissen_falsch(t)
    pruefe("T12w Funde im erzeugten Wissen werden ihrem Eintrag zugeordnet "
           "(Kopf, verschachtelte id, kaputte Datei)", not falsch, falsch)
    alt = P._eintrag_anfaenge
    P._eintrag_anfaenge = lambda pfad: [(1, "erster_eintrag")] \
        if pfad.endswith("k.json") else None
    try:
        k = _wissen_falsch(t)
    finally:
        P._eintrag_anfaenge = alt
    pruefe("T12w KONTROLLE: ordnet die Suche alles dem ersten Eintrag zu, "
           "faellt es auf", len(k) >= 2, k)

    # (b) eine Datei mit Spur faellt auf, dieselbe unter knowledge/ nur
    #     als ausgenommen, auch unter server/ (Paket), und nirgends sonst
    probe = os.path.join(t, "spuren")
    for rel in ("x.py", os.path.join("open_mcp_cad", "knowledge", "k.json"),
                os.path.join("server", "open_mcp_cad", "knowledge", "k.json"),
                os.path.join("open_mcp_cad", "knowledgex", "k.json")):
        p = os.path.join(probe, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write("ok\n# siehe %s\n" % SYNTH_WORT)
    f2, a2 = P.private_spuren(probe, SYNTH_SPUREN)
    f2 = sorted(x.replace("\\", "/") for x in f2)
    a2 = sorted(x.replace("\\", "/") for x in a2)
    pruefe("T12-K Spur faellt auf; unter open_mcp_cad/knowledge/ nur "
           "ausgenommen", f2 == ["open_mcp_cad/knowledgex/k.json:2", "x.py:2"]
           and a2 == ["open_mcp_cad/knowledge/k.json:2",
                      "server/open_mcp_cad/knowledge/k.json:2"], (f2, a2))
    # ohne ausdrueckliche Liste gilt die eingesetzte bzw. die lokale Datei
    alt_liste = P.PRIVATE_SPUREN
    P.PRIVATE_SPUREN = tuple(SYNTH_SPUREN)
    try:
        f3, _a3 = P.private_spuren(probe)
    finally:
        P.PRIVATE_SPUREN = alt_liste
    pruefe("T12-K ohne Liste nimmt private_spuren die eingesetzte "
           "(PRIVATE_SPUREN), sonst privat_spuren.txt",
           sorted(x.replace("\\", "/") for x in f3) == f2
           and [m.pattern for m in P.private_spuren_liste()]
           == [m.pattern for m in P.private_muster()], f3)

    # (c) Export und --oeffentlich brechen an einer Spur ab: ein Muster,
    #     das sicher trifft
    treffend = [re.compile("Open MCP CAD")]
    k = export(klon, [NAME], spuren=treffend)
    try:
        P.bauen(os.path.join(t, "oeff_spur"), oeffentlich=True,
                muster=[NAME], edge=False, spuren=treffend)
        kb = "gebaut"
    except P.PaketFehler as exc:
        kb = str(exc)
    pruefe("T12-K eine Spur bricht den Export ab",
           "Spuren privater Teile" in k, k[:80])
    pruefe("T12-K eine Spur bricht paket_bauen --oeffentlich ab",
           "Spuren privater Teile" in kb, kb[:80])

    # (d) ohne Spuren-Muster (Datei fehlt oder leer) brechen beide ab
    k = export(klon, [NAME], spuren=[])
    try:
        P.bauen(os.path.join(t, "oeff_ohne_spur"), oeffentlich=True,
                muster=[NAME], edge=False, spuren=[])
        kb = "gebaut"
    except P.PaketFehler as exc:
        kb = str(exc)
    pruefe("T12-L ohne privat_spuren.txt bricht der Export ab",
           "privat_spuren.txt" in k, k[:100])
    pruefe("T12-L ohne privat_spuren.txt bricht --oeffentlich ab",
           "privat_spuren.txt" in kb, kb[:100])

    # (e) die lokalen Musterdateien selbst nie in Export oder Paket
    falle = os.path.join(t, "lokal_falle")
    os.makedirs(os.path.join(falle, "innen"), exist_ok=True)
    with open(os.path.join(falle, "innen", "Persoenlich.TXT"), "w") as fh:
        fh.write("x\n")
    with zipfile.ZipFile(os.path.join(falle, "a.zip"), "w") as z:
        z.writestr("Paket/privat_spuren.txt", "x\n")
        z.writestr("Paket/privat_spuren.txt.bak", "x\n")
    funde = sorted(x.replace("\\", "/") for x in P.lokale_dateien_in(falle))
    sauber = os.path.join(t, "lokal_sauber")
    os.makedirs(sauber, exist_ok=True)
    with open(os.path.join(sauber, "privat_spuren.md"), "w") as fh:
        fh.write("x\n")
    pruefe("T12-L lokale Musterdateien werden gefunden (Gross/Klein egal, "
           "auch im ZIP), aehnliche Namen nicht",
           funde == ["a.zip!Paket/privat_spuren.txt",
                     "innen/Persoenlich.TXT"]
           and P.lokale_dateien_in(sauber) == [], funde)
    marke = os.path.join(klon, "bleibt_unberuehrt.txt")
    with open(marke, "w") as fh:
        fh.write("x")
    echt_dateien = E.oeffentliche_dateien
    E.oeffentliche_dateien = lambda: echt_dateien() + ["privat_spuren.txt"]
    try:
        k = export(klon, [NAME])
    finally:
        E.oeffentliche_dateien = echt_dateien
    pruefe("T12-L KONTROLLE: eine eingecheckte privat_spuren.txt bricht den "
           "Export ab, bevor er etwas anfasst",
           "eingecheckt" in k and os.path.isfile(marke), k[:100])
    echt_paket = P.paket_dateien
    lokal = os.path.join(t, "persoenlich.txt")
    with open(lokal, "w") as fh:
        fh.write("# nur ein Kommentar\n")
    P.paket_dateien = lambda: echt_paket() + [
        (lokal, P.UNTERORDNER + "/persoenlich.txt")]
    try:
        P.bauen(os.path.join(t, "lokal_paket"), edge=False)
        kb = "gebaut"
    except P.PaketFehler as exc:
        kb = str(exc)
    finally:
        P.paket_dateien = echt_paket
    pruefe("T12-L KONTROLLE: eine persoenlich.txt im Paket bricht bauen() ab "
           "(auch ohne --oeffentlich)", "lokale Musterdatei" in kb, kb[:100])


def export_echt_pruefen(t, export, eigene, echte):
    """T20 (seit 2026-10-01): ein ECHTER Export in Temp mit beiden lokalen
    Dateien besteht, und eine eigene Suche (ohne paket_bauen) findet darin
    keinen Treffer eines Musters aus privat_spuren.txt oder persoenlich.txt
    - ausser im erzeugten Wissen, das GENANNT wird."""
    if not (eigene and echte):
        print("  [info] T20 lief nicht: es fehlt %s" % " und ".join(
            n for n, m in (("persoenlich.txt", eigene),
                           ("privat_spuren.txt", echte)) if not m))
        return
    klon = os.path.join(t, "klon_echt")
    os.makedirs(os.path.join(klon, ".git"))
    k = export(klon, eigene, spuren=echte)
    alle = list(eigene) + list(echte)
    treffer = unabhaengig_suchen(klon, alle)
    erzeugt = [x for x in treffer
               if any(x.startswith(a) for a in P.SPUREN_AUSGENOMMEN)]
    hand = [x for x in treffer if x not in erzeugt]
    pruefe("T20 echter Export (persoenlich.txt %d + privat_spuren.txt %d "
           "Muster): besteht, und eine eigene Suche findet in keiner "
           "handgepflegten Datei einen Treffer" % (len(eigene), len(echte)),
           k == "ok" and not hand and len(os.listdir(klon)) > 5,
           (k[:160], hand[:10]))
    print("  [info] T20 erzeugtes Wissen mit Treffer (im privaten Repo zu "
          "bereinigen): %s" % (", ".join(erzeugt) or "keins"))
    # KONTROLLE: je ein Treffer aus beiden Arten im selben Baum faellt auf.
    treffen, _h = P.private_beispiele()
    with io.open(os.path.join(klon, "docs", "k_spur.md"), "w",
                 encoding="utf-8") as fh:
        fh.write("Siehe %s.\n" % treffen[0])
    with io.open(os.path.join(klon, "k_name.txt"), "w",
                 encoding="utf-8") as fh:
        fh.write("Fragen an %s\n" % ERIKA)
    k_treffer = unabhaengig_suchen(klon, alle + [NAME])
    pruefe("T20-K KONTROLLE: eine Spur (Beispiel aus privat_spuren.txt) und "
           "ein Name in den Baum gelegt - beide fallen auf",
           {"docs/k_spur.md", "k_name.txt"} <= set(k_treffer),
           [x for x in k_treffer if x not in treffer])


# --- Schnellstart (Rueckmeldung 2026-09-29) ---------------------------------
# Kollegen ohne IT-Kenntnisse wussten nach der Installation nicht weiter und
# stolperten ueber Woerter wie "API". Die Anleitung: vier Sprachen mit
# demselben Geruest (Abschnitte, Schritte, Befehle, Bilder), keine
# Fachwoerter ohne Erklaerung, was sie nennt, aus der QUELLE (Doppelklick,
# Startlog). Das PDF: gedruckt von Edge, mit Bildern und dem Testsatz.

#: Woerter, die ein Laie nicht kennt. Erlaubt nur in Code, in Adressen, im
#: Produktnamen "Open MCP CAD" und in der einen Klammer, die MCP erklaert.
FACHWOERTER = ("API", "MCP", "stdio", "JSON", "TOML", "venv", "PATH",
               "Server", "Terminal", "CLI", "Token", "Python", "pip")
MCP_ERKLAERT = re.compile(r"\(MCP (?:ist|is|est|è) [^)]*\)")
TESTSATZ = "Zeichne eine Wand 4 m lang, 2,5 m hoch"


def erweiterungen_paket_pruefen(t, klon, export):
    """T19 (seit 2026-10-01): was in OPEN_MCP_CAD_ERWEITERUNGEN steht, kommt
    nie ins Verteilpaket und nie in den Export — geprueft am gebauten Paket
    (auch im ZIP), mit Kontrollen, die rot werden muessen."""
    kennung = "omcad_testerw_%s" % os.urandom(4).hex()
    marke = "ERWEITERUNGSMARKE_%s" % os.urandom(6).hex()
    basis = os.path.join(t, "erw_quelle")
    ordner_erw = os.path.join(basis, kennung)
    os.makedirs(ordner_erw)
    inhalt = ('"""Private Testerweiterung %s."""\n' % marke
              + "def registrieren(mcp, kontext):\n    pass\n" * 3)
    datei = os.path.join(ordner_erw, "__init__.py")
    with io.open(datei, "w", encoding="utf-8") as fh:
        fh.write(inhalt)
    modul_basis = os.path.join(t, "erw_modul")
    os.makedirs(os.path.join(modul_basis, kennung + "_m"))
    with io.open(os.path.join(modul_basis, kennung + "_m", "__init__.py"),
                 "w", encoding="utf-8") as fh:
        fh.write(inhalt.replace("Testerweiterung", "Modulerweiterung"))
    alt_env = os.environ.get(P.ERW_UMGEBUNG)
    os.environ[P.ERW_UMGEBUNG] = "%s;%s_m.werkzeuge" % (ordner_erw, kennung)
    sys.path.insert(0, modul_basis)
    echt = P.paket_dateien
    try:
        quellen = P.erweiterung_quellen()
        pruefe("T19 die Quellen der Erweiterungen werden gefunden, ohne sie "
               "zu importieren (Ordner und Modulname)",
               [len(d) for _n, _p, d in quellen] == [1, 1]
               and kennung not in sys.modules
               and kennung + "_m" not in sys.modules, quellen)
        try:
            o, a, _w, _x = P.bauen(os.path.join(t, "erw_paket"), edge=False)
            gebaut = "gebaut"
        except P.PaketFehler as exc:
            o = a = None
            gebaut = str(exc)
        treffer = []
        if o:
            for wurzel, _d, namen in os.walk(o):
                for n in namen:
                    with open(os.path.join(wurzel, n), "rb") as fh:
                        if marke.encode() in fh.read():
                            treffer.append(n)
            with zipfile.ZipFile(a) as z:
                treffer += [n for n in z.namelist()
                            if marke.encode() in z.read(n)
                            or kennung in n]
        pruefe("T19 mit eingetragenen Erweiterungen baut das Paket, und ihre "
               "Marke steht in keiner Datei (auch nicht im ZIP)",
               gebaut == "gebaut" and not treffer, (gebaut[:120], treffer))
        P.paket_dateien = lambda: echt() + [
            (datei, P.UNTERORDNER + "/server/open_mcp_cad/zusatz.py")]
        try:
            P.bauen(os.path.join(t, "erw_k1"), edge=False)
            k1 = "gebaut"
        except P.PaketFehler as exc:
            k1 = str(exc)
        pruefe("T19-K KONTROLLE: laege eine Datei der Erweiterung im Paket "
               "(auch umbenannt), bricht bauen() ab", "Erweiterung" in k1
               and "zusatz.py" in k1, k1[:160])
        falle = os.path.join(t, "erw_falle")
        os.makedirs(falle)
        with io.open(os.path.join(falle, "hinweis.md"), "w",
                     encoding="utf-8") as fh:
            fh.write("Siehe %s_m.werkzeuge\n" % kennung)
        with zipfile.ZipFile(os.path.join(falle, "a.zip"), "w") as z:
            z.writestr("innen/x.py", inhalt)
        funde = P.erweiterungen_im_paket(falle)
        pruefe("T19-K KONTROLLE: der Name einer Erweiterung in einer Datei und "
               "ihr Inhalt in einem ZIP fallen auf",
               any("hinweis.md" in f for f in funde)
               and any("a.zip!innen/x.py" in f for f in funde), funde)
        pruefe("T19 ohne eingetragene Erweiterung prueft die Funktion nichts "
               "(kein Fund im selben Ordner)",
               P.erweiterungen_im_paket(falle, eintraege=[]) == [])
        k2 = export(klon, [NAME])
        pruefe("T19b der Export mit eingetragenen Erweiterungen gelingt",
               k2 == "ok", k2[:160])
        alt_fn = P.erweiterungen_im_paket
        P.erweiterungen_im_paket = lambda ordner, eintraege=None: [
            "attrappe"]
        try:
            k3 = export(klon, [NAME])
        finally:
            P.erweiterungen_im_paket = alt_fn
        pruefe("T19b-K KONTROLLE: meldet die Pruefung einen Fund, bricht der "
               "Export ab", "Erweiterung im Export" in k3, k3[:120])
    finally:
        P.paket_dateien = echt
        sys.path.remove(modul_basis)
        if alt_env is None:
            os.environ.pop(P.ERW_UMGEBUNG, None)
        else:
            os.environ[P.ERW_UMGEBUNG] = alt_env


def _prosa(md):
    """Nur das, was ein Mensch liest: ohne Code, Adressen, Produktnamen und
    ohne die Erklaerung von MCP."""
    t = re.sub(r"```.*?```", " ", md, flags=re.S)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"\]\([^)]*\)", "]", t)
    t = " ".join(t.replace("**", "").split())
    t = MCP_ERKLAERT.sub(" ", t)
    return t.replace("Open MCP CAD", " ")


def fachwoerter(md):
    return sorted({w for w in FACHWOERTER
                   if re.search(r"(?<![\w-])%s(?![\w])" % re.escape(w),
                                _prosa(md))})


def geruest(html):
    """Blockfolge ohne Absaetze: Ueberschriftenebenen, Listen, Punkte,
    Code, Bilder, Tipps."""
    return re.findall(r"<(h[123]|ol|ul|li|pre|figure|div class=\"tipp\")",
                      html)


def schnellstart_luecken(md, sprache, deutsch_html=None):
    """-> Liste dessen, was an einer Schnellstart-Quelle nicht stimmt."""
    ps1 = open(os.path.join(P.VERTEILUNG, "install.ps1"),
               encoding="ascii").read()
    start_log = re.search(r'\$START_LOG = "([^"]+)"', ps1).group(1)
    html = P.md_zu_html(md)
    aus = ["Fachwort ohne Erklaerung: %s" % w for w in fachwoerter(md)]
    aus += ["Markdown nicht umgewandelt: %s" % r for r in P.md_reste(html)]
    # Seit 2026-09-29 auch die Datei fuer KI-Assistenten (T18).
    for pflicht in (P.INSTALLIEREN, start_log,
                    "%s\\%s" % (P.UNTERORDNER, P.KI_HINWEIS)):
        if pflicht not in md:
            aus.append("nennt %s nicht" % pflicht)
    if sprache == "de" and not re.search(r"(?m)^> %s$" % re.escape(TESTSATZ),
                                         md):
        aus.append("Testsatz fehlt")
    # Abschnitt 4: genau drei Wege, jeder mit nummerierten Schritten
    teil = re.search(r"<h2>4\..*?(?=<h2>|$)", html, re.S)
    wege = re.split(r"<h3>", teil.group(0))[1:] if teil else []
    if len(wege) != 3 or not all("<ol>" in w for w in wege):
        aus.append("Abschnitt 4 hat nicht drei Wege mit Schritten (%d)"
                   % len(wege))
    for quelle in re.findall(r'<img src="([^"]+)"', html):
        if not os.path.isfile(os.path.join(P.VERTEILUNG, quelle)):
            aus.append("Bild fehlt: %s" % quelle)
    if deutsch_html is not None:
        if geruest(html) != geruest(deutsch_html):
            aus.append("Geruest weicht vom Deutschen ab")
        for was in (r"<pre>(.*?)</pre>", r'<img src="([^"]+)"',
                    r'<a href="([^"]+)"'):
            if re.findall(was, html, re.S) != re.findall(was, deutsch_html,
                                                          re.S):
                aus.append("anders als im Deutschen: %s" % was)
    return aus


def schnellstart_quellen_pruefen():
    quellen = P.schnellstart_quellen()
    texte = {sp: open(p, encoding="utf-8").read() for sp, p in quellen.items()}
    pruefe("T14 Schnellstart in %s (Deutsch verbindlich)"
           % ", ".join(sorted(texte)),
           {"de", "en", "fr", "it"} <= set(texte)
           and {sp for sp, _s in P.ANLEITUNG_OBEN} <= set(texte),
           sorted(texte))
    de_html = P.md_zu_html(texte["de"])
    for sp in sorted(texte):
        luecken = schnellstart_luecken(texte[sp], sp,
                                       None if sp == "de" else de_html)
        pruefe("T14 %s: Doppelklick und Startlog aus der Quelle, drei Wege "
               "mit Schritten, keine Fachwoerter, Geruest/Befehle/Bilder wie "
               "im Deutschen" % sp, not luecken, luecken[:4])
    # KONTROLLEN: je eine eingebaute Luecke MUSS auffallen.
    de, en = texte["de"], texte["en"]
    code = re.search(r"```\n.*?```\n", en, re.S).group(0)
    faelle = {
        "Fachwort": (de.replace("Ein Abo ist", "Ein API-Abo ist"), "de"),
        "MCP ohne Erklaerung": (de + "\nDer MCP-Dienst startet.\n", "de"),
        "offenes Fett": (de.replace("**Cadwork 3D 2026**",
                                    "**Cadwork 3D 2026"), "de"),
        "Testsatz geaendert": (de.replace(TESTSATZ, "Zeichne eine Wand"), "de"),
        "Startlog fehlt": (de.replace("OpenMcpCad_start.log", "start.log"),
                           "de"),
        "Bild fehlt": (de.replace("bilder/monitor.png", "bilder/fehlt.png"),
                       "de"),
        "ein Weg weniger": (re.sub(r"### Weg C.*?(?=## 5)", "", de,
                                   flags=re.S), "de"),
        "Befehl fehlt in der Uebersetzung": (en.replace(code, "", 1), "en"),
        "Schritt fehlt in der Uebersetzung": (
            en.replace("2. **Close Cadwork.**\n", "", 1), "en"),
        "Datei fuer KI-Assistenten nicht genannt": (
            texte["it"].replace("FUER_KI_ASSISTENTEN.md", "LEGGIMI.md"),
            "it"),
    }
    rot = {}
    for titel, (text, sp) in faelle.items():
        geaendert = text != texte[sp]
        rot[titel] = geaendert and bool(schnellstart_luecken(
            text, sp, None if sp == "de" else de_html))
    pruefe("T14-K KONTROLLEN: jede eingebaute Luecke faellt auf",
           all(rot.values()), [t for t, r in rot.items() if not r])
    # Die Umwandlung selbst: jedes Konstrukt, das die Anleitung benutzt.
    probe = ("# T\n\nA **b** `c` [d](https://e)\n\n1. eins\n   weiter\n"
             "   ```\n   befehl x\n   ```\n   danach\n2. zwei\n   - unter\n\n"
             "> Tipp: x\n\n![Bild](bilder/y.png)\n")
    h = P.md_zu_html(probe, "B/")
    erwartet = ["<h1>T</h1>", "<strong>b</strong>", "<code>c</code>",
                '<a href="https://e">d</a>', "<li>eins weiter<pre>befehl x"
                "</pre><p>danach</p></li>", "<li>zwei<ul><li>unter</li></ul>",
                '<div class="tipp">Tipp: x</div>', '<img src="B/y.png"']
    pruefe("T14b die Umwandlung kennt jedes benutzte Konstrukt",
           all(e in h for e in erwartet) and not P.md_reste(h),
           [e for e in erwartet if e not in h] or P.md_reste(h))


def _pdf_seiten(daten):
    return len(re.findall(rb"/Type\s*/Page[^s]", daten))


def schnellstart_paket_pruefen(t, ordner, warnungen):
    """T15/T16 am gebauten Paket (und an eigenen Bauten)."""
    u = os.path.join(ordner, P.UNTERORDNER, P.ANLEITUNGEN)
    zwillinge = sorted(n for n in os.listdir(u) if n.endswith(".html"))
    pruefe("T15 je Sprache die HTML-Fassung im Unterordner (%d)"
           % len(zwillinge),
           len(zwillinge) == len(P.schnellstart_quellen()), zwillinge)
    edge = P.edge_finden()
    if not edge:
        print("  [info] T15 kein Microsoft Edge — die PDF-Zellen laufen "
              "NICHT (das ist kein bestandener Test)")
        pruefe("T15 ohne Edge: oben die HTML-Fassung, gewarnt",
               bool(warnungen) and not P.oben_abweichung(ordner), warnungen)
        return
    quellen = P.schnellstart_quellen()
    de_md = open(quellen["de"], encoding="utf-8").read()
    bilder = len(re.findall(r"(?m)^!\[", de_md))
    for sp, stamm in P.ANLEITUNG_OBEN:
        pdf = os.path.join(ordner, stamm + ".pdf")
        daten = open(pdf, "rb").read() if os.path.isfile(pdf) else b""
        texte = " ".join(s for o, s in P._pdf_stroeme(daten, "x")
                         if "#text" in o)
        pruefe("T15 %s.pdf oben: ganzes PDF, %d Seiten, %d Bilder (Quelle %d "
               "+ Logo)%s" % (stamm, _pdf_seiten(daten),
                              len(re.findall(rb"/Subtype\s*/Image", daten)),
                              bilder, ", Testsatz im Text" if sp == "de"
                              else ""),
               daten[:5] == b"%PDF-" and daten.rstrip().endswith(b"%%EOF")
               and _pdf_seiten(daten) >= 2
               and len(re.findall(rb"/Subtype\s*/Image", daten)) >= bilder + 1
               and (sp != "de" or TESTSATZ in texte), pdf)
    unten = sorted(n for n in os.listdir(u) if n.endswith(".pdf"))
    oben_sp = {sp for sp, _s in P.ANLEITUNG_OBEN}
    pruefe("T15 die uebrigen Sprachen als PDF im Unterordner (%s), keine "
           "Warnung" % ", ".join(unten), not warnungen and unten == sorted(
               "%s.%s.pdf" % (P.SCHNELLSTART, sp) for sp in quellen
               if sp not in oben_sp), (unten, warnungen))
    # T15-K KONTROLLE: ohne Edge liegt oben die HTML-Fassung (Bilder aus
    # dem Unterordner), es wird gewarnt, und --oeffentlich bricht ab.
    o2, _a, _w, w2 = P.bauen(os.path.join(t, "ohne_edge"), edge=False)
    oben2 = sorted(os.listdir(o2))
    html_oben = os.path.join(o2, P.ANLEITUNG_OBEN[0][1] + ".html")
    bild_ok = all(os.path.isfile(os.path.join(o2, q)) for q in re.findall(
        r'<img src="([^"]+\.png)"', open(html_oben, encoding="utf-8").read()))
    pruefe("T15-K ohne Edge: oben HTML statt PDF, Bilder gefunden, gewarnt, "
           "Aufbau stimmt", not P.oben_abweichung(o2) and bild_ok
           and len(w2) == len(P.schnellstart_quellen())
           and not any(n.endswith(".pdf") for n in oben2), (oben2, w2))
    try:
        P.bauen(os.path.join(t, "ohne_edge_oeff"), oeffentlich=True,
                muster=[NAME], edge=False, spuren=SYNTH_SPUREN)
        k = "gebaut"
    except P.PaketFehler as exc:
        k = str(exc)
    pruefe("T15-K --oeffentlich ohne PDF bricht ab", "PDF" in k, k[:100])

    # T17 (Gegenpruefung 2026-09-29): die alte Ausgabe ist noch offen (das
    # ZIP im Explorer, ein PDF im Betrachter) -> ein Satz statt Traceback.
    zip_alt = o2 + ".zip"
    with open(zip_alt, "rb"):
        try:
            os.remove(zip_alt)
            gesperrt = False
        except PermissionError:
            gesperrt = True
        try:
            P.bauen(os.path.join(t, "ohne_edge"), edge=False)
            k = "gebaut"
        except P.PaketFehler as exc:
            k = "PaketFehler: %s" % exc
        except Exception as exc:                      # noqa: BLE001
            k = "%s: %s" % (type(exc).__name__, exc)
        pdf_offen = os.path.join(t, "offen.pdf")
        html_probe = os.path.join(t, "offen.html")
        with open(pdf_offen, "wb") as fh:
            fh.write(b"%PDF-1.4 alt")
        with open(html_probe, "w", encoding="utf-8") as fh:
            fh.write("<html><body><p>neu</p></body></html>")
        with open(pdf_offen, "rb"):
            g = P.pdf_drucken(html_probe, pdf_offen, edge)
    pruefe("T17 alte Ausgabe noch offen: Abbruch mit einem Satz (PaketFehler, "
           "'offen'), ein offenes PDF wird ein Grund statt eines Tracebacks "
           "(Vorbedingung: die Datei ist wirklich gesperrt)",
           gesperrt and k.startswith("PaketFehler") and "offen" in k
           and isinstance(g, str) and "offen" in g, (gesperrt, k[:120], g))

    # T16 Persoenliches IN einem PDF (gemessen 2026-09-29: Edge schreibt
    # Text als Glyphennummern; vorher fand die Pruefung darin nichts).
    falle = os.path.join(t, "pdf_falle")
    os.makedirs(falle)
    html = os.path.join(falle, "f.html")
    with open(html, "w", encoding="utf-8") as fh:
        fh.write('<html><body><p>Gezeichnet von %s</p><p>Datei C:\\Users\\'
                 'erika\\Seeblick.3d</p></body></html>' % ERIKA)
    grund = P.pdf_drucken(html, os.path.join(falle, "f.pdf"), edge)
    os.remove(html)
    h, w = P.pruefen(falle, [NAME])
    pruefe("T16 Name und Benutzerpfad im Fliesstext eines PDFs fallen auf",
           grund is None and any(x.startswith("f.pdf") for x in h)
           and any(x.startswith("f.pdf") for x in w), (grund, h, w))
    # T16d (Gegenpruefung 2026-09-29): ein Name NUR im Alt-Text eines
    # Bildes bzw. NUR im Titel mit Umlaut — Edge schreibt beides als
    # UTF-16 (<FEFF...>), auf der Seite steht es nicht.
    fallen = {}
    for n, kopf, koerper in (
            ("alt", "<title>x</title>",
             '<p>Hallo</p><img src="b.png" alt="Von %s überall">' % ERIKA),
            ("titel", "<title>Für %s – Anleitung</title>" % ERIKA,
             "<p>Hallo</p>")):
        d = os.path.join(t, "pdf_falle_" + n)
        os.makedirs(d)
        shutil.copyfile(os.path.join(P.BILDER, "monitor.png"),
                        os.path.join(d, "b.png"))
        with open(os.path.join(d, "f.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><head>%s</head><body>%s</body></html>"
                     % (kopf, koerper))
        g = P.pdf_drucken(os.path.join(d, "f.html"), os.path.join(d, "f.pdf"),
                          edge)
        os.remove(os.path.join(d, "f.html"))
        os.remove(os.path.join(d, "b.png"))
        fallen[n] = (g, d)
    echt_utf16 = P._pdf_utf16
    gefunden, ohne = {}, {}
    try:
        for n, (g, d) in fallen.items():
            gefunden[n] = g is None and bool(P.pruefen(d, [NAME])[1])
        P._pdf_utf16 = lambda *_a: []
        for n, (g, d) in fallen.items():
            ohne[n] = bool(P.pruefen(d, [NAME])[1])
    finally:
        P._pdf_utf16 = echt_utf16
    pruefe("T16d ein Name nur im Alt-Text eines Bildes bzw. nur im Titel "
           "(mit Umlaut) eines PDFs faellt auf", all(gefunden.values()),
           gefunden)
    pruefe("T16d-K KONTROLLE: ohne die UTF-16-Sicht fiele er nicht auf "
           "(so war es vorher)", not any(ohne.values()), ohne)
    h, w = P.pruefen(ordner, [NAME])
    pruefe("T16-K KONTROLLE: die echten PDFs des Pakets sind sauber",
           not [x for x in h + w if ".pdf" in x], [x for x in h + w][:4])
    # T16b von der Quelle bis ins PDF: ein Name in SCHNELLSTART.md bricht
    # --oeffentlich ab, und er steht im PDF UND in der HTML-Fassung.
    quellen_echt = P.schnellstart_quellen
    probe = os.path.join(t, "quelle")
    os.makedirs(probe)
    ersatz = {}
    for sp, pfad in quellen_echt().items():
        text = open(pfad, encoding="utf-8").read()
        if sp == "de":
            text = text.replace("## 6.", "Fragen an %s.\n\n## 6." % ERIKA, 1)
        ersatz[sp] = os.path.join(probe, os.path.basename(pfad))
        with open(ersatz[sp], "w", encoding="utf-8") as fh:
            fh.write(text)
    try:
        P.schnellstart_quellen = lambda: dict(ersatz)
        try:
            o3 = P.bauen(os.path.join(t, "name_in_quelle"), oeffentlich=True,
                         muster=[NAME], spuren=SYNTH_SPUREN)[0]
            k = "gebaut"
        except P.PaketFehler as exc:
            k = str(exc)
            o3 = os.path.join(t, "name_in_quelle",
                              "Open-MCP-CAD-%s" % P.version())
    finally:
        P.schnellstart_quellen = quellen_echt
    _h, w3 = P.pruefen(o3, [NAME])
    pruefe("T16b ein Name in der Quelle: --oeffentlich bricht ab, er steht "
           "im PDF oben und in der HTML-Fassung",
           "Persoenlichem" in k
           and any(x.startswith(P.ANLEITUNG_OBEN[0][1] + ".pdf") for x in w3)
           and any("SCHNELLSTART.de.html" in x for x in w3), (k[:80], w3[:6]))
    # T16c die sichtbaren Texte der Bilder (scripts/bilder_rendern.py)
    import bilder_rendern as B
    try:
        B.texte_pruefen(["Seeblick.3d", "Bereit"], "probe")
        sauber = True
    except SystemExit:
        sauber = False
    try:
        B.texte_pruefen(["C:\\Users\\" + "erika\\Seeblick"], "probe")
        pfad_faellt = False
    except SystemExit:
        pfad_faellt = True
    pruefe("T16c Bilder: ein Benutzerpfad im sichtbaren Text bricht das "
           "Rendern ab, Demo-Texte nicht", sauber and pfad_faellt)


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % ("ok  " if bedingung else "FEHL", titel,
                               ("  — %s" % (detail,)) if detail else ""))
    return bool(bedingung)


def dateien(ordner):
    return sorted(os.path.relpath(os.path.join(w, n), ordner).replace("\\", "/")
                  for w, _d, ns in os.walk(ordner) for n in ns)


def listen_abgleich(dateien, handgepflegt, erzeugt, im_ordner, ordner):
    """Drei Quellen, EIN Stand: was im ausgerollten Ordner liegt, was
    deployment_pruefen.DATEIEN ausrollt, und was der Generator kennt
    (HANDGEPFLEGT[None] + ERZEUGT). -> Liste der Abweichungen."""
    def f(xs):
        return {x.format(ordner=ordner) for x in xs}
    d, g = f(dateien), f(handgepflegt) | f(erzeugt)
    aus = []
    if set(im_ordner) != d:
        aus.append("Ordner != DATEIEN: zu viel %s, fehlt %s"
                   % (sorted(set(im_ordner) - d), sorted(d - set(im_ordner))))
    if d != g:
        aus.append("DATEIEN != HANDGEPFLEGT+ERZEUGT: nur DATEIEN %s, nur "
                   "Generator %s" % (sorted(d - g), sorted(g - d)))
    return aus


def main():
    print("Verteilpaket — Gate\n")

    # T1b Gegenpruefung 2026-09-26: fehlte eine neue Datei (z. B.
    # omcad_startfehler.py) in HANDGEPFLEGT[None] oder in DATEIEN, wurde
    # kein Gate rot — T1 vergleicht das Paket mit DATEIEN selbst. Jetzt
    # aus der QUELLE: die Dateien im Repo-Ordner gegen beide Listen.
    _ord = G.DYNAMISCHER_ORDNER
    _pfad = os.path.join(REPO, "cad_plugin", _ord)
    _im = sorted(n for n in os.listdir(_pfad)
                 if os.path.isfile(os.path.join(_pfad, n))
                 and n not in DP.NUR_LOKAL and not n.startswith("__"))
    _ab = listen_abgleich(DP.DATEIEN, G.HANDGEPFLEGT[None], G.ERZEUGT,
                          _im, _ord)
    pruefe("T1b ausgerollter Ordner == DATEIEN == HANDGEPFLEGT[None] + "
           "ERZEUGT (%d Dateien)" % len(_im), not _ab, _ab)
    # T1b-K KONTROLLEN: je eine Liste ohne omcad_startfehler.py, und eine
    # fremde Datei im Ordner, MUESSEN auffallen.
    _ohne = lambda xs: tuple(x for x in xs if x != "omcad_startfehler.py")
    _k = [listen_abgleich(_ohne(DP.DATEIEN), G.HANDGEPFLEGT[None],
                          G.ERZEUGT, _im, _ord),
          listen_abgleich(DP.DATEIEN, _ohne(G.HANDGEPFLEGT[None]),
                          G.ERZEUGT, _im, _ord),
          listen_abgleich(DP.DATEIEN, G.HANDGEPFLEGT[None], G.ERZEUGT,
                          _im + ["fremd.py"], _ord)]
    pruefe("T1b-K fehlt omcad_startfehler.py in DATEIEN / HANDGEPFLEGT oder "
           "liegt eine fremde Datei im Ordner -> faellt auf",
           "omcad_startfehler.py" in _im and all(_k), _k)

    with tempfile.TemporaryDirectory(prefix="omcad_paket_") as t:
        ordner, archiv, weiche, warnungen = P.bauen(t)
        drin = dateien(ordner)

        u = P.UNTERORDNER + "/"
        soll = sorted("%s%s/%s" % (u, P.PLUGIN, m.format(ordner=P.PLUGIN))
                      for m in DP.DATEIEN)
        ist = [d for d in drin if d.startswith(u + P.PLUGIN + "/")]
        pruefe("T1 der Plugin-Ordner ist genau deployment_pruefen.DATEIEN",
               ist == soll, "zu viel %s, fehlt %s"
               % (sorted(set(ist) - set(soll)), sorted(set(soll) - set(ist))))
        gleich = all(open(os.path.join(REPO, "cad_plugin", d[len(u):]),
                          "rb").read()
                     == open(os.path.join(ordner, d), "rb").read()
                     for d in ist)
        pruefe("T1 und bytegleich mit dem Repo", gleich)

        # T13 (Rueckmeldung 2026-09-29): oben liegt NUR, was ein Nutzer
        # anfassen soll — der Doppelklick, die Anleitungen und EIN Ordner.
        # Das Soll kommt aus paket_bauen (`oben_soll`), gemessen wird der
        # gebaute Ordner.
        oben = sorted(os.listdir(ordner))
        pruefe("T13 oben nur %s" % ", ".join(P.oben_soll(ordner)),
               not P.oben_abweichung(ordner), (oben, P.oben_abweichung(ordner)))
        pruefe("T13 der Doppelklick steht zuerst, der Ordner ist der einzige",
               oben[0] == P.INSTALLIEREN and [o for o in oben if os.path.isdir(
                   os.path.join(ordner, o))] == [P.UNTERORDNER], oben)
        falle_oben = os.path.join(t, "oben_falle")
        os.makedirs(os.path.join(falle_oben, P.UNTERORDNER))
        for n in P.oben_soll(ordner):
            if n != P.UNTERORDNER:
                open(os.path.join(falle_oben, n), "w").close()
        ohne_fehl = P.oben_abweichung(falle_oben)
        open(os.path.join(falle_oben, "install.ps1"), "w").close()
        pruefe("T13-K KONTROLLE: eine weitere Datei oben faellt auf, der "
               "Nachbau ohne sie nicht",
               not ohne_fehl and P.oben_abweichung(falle_oben) ==
               ["zu viel: install.ps1"], (ohne_fehl,
                                          P.oben_abweichung(falle_oben)))
        # T13b der Doppelklick nennt genau Programmdateien\install.ps1 (ob
        # er ihn WIRKLICH startet, misst test_installer I11).
        cmd_alt = os.path.join(t, "alt.cmd")
        with open(cmd_alt, "w", encoding="ascii") as fh:
            fh.write('powershell -File "%~dp0install.ps1" %*\r\n')
        # Seit 2026-10-09 auch das Einrichtungsfenster: ein Doppelklick, der
        # nur install.ps1 nennt (Stand vor dem Fenster), faellt auf.
        cmd_ohne = os.path.join(t, "ohne_fenster.cmd")
        with open(cmd_ohne, "w", encoding="ascii") as fh:
            fh.write('powershell -File "%%~dp0%s\\install.ps1" %%*\r\n'
                     % P.UNTERORDNER)
        pruefe("T13b %s nennt %s\\install.ps1 und %s; KONTROLLEN: der alte "
               "Aufruf (install.ps1 daneben) und einer ohne Fenster fallen auf"
               % (P.INSTALLIEREN, P.UNTERORDNER, P.FENSTER),
               P.installieren_pruefen() is None
               and P.installieren_pruefen(cmd_alt) is not None
               and P.FENSTER in (P.installieren_pruefen(cmd_ohne) or ""))

        verboten = ("tests/", "/docs/", "__pycache__", ".egg-info",
                    "CLAUDE.md", "AGENTS.md", "UEBERGABE", "projektordner.txt",
                    "wissensordner.txt") + tuple(
                        "Open MCP CAD %s/" % c for c in "ABCDEF")
        schlecht = [d for d in drin if any(v in d for v in verboten)]
        pruefe("T2 keine Tests, Notizen, Caches, A-F, lokalen Dateien",
               not schlecht, schlecht)

        pflicht = (P.INSTALLIEREN,) + tuple(u + p for p in (
                   "ANLEITUNG.md", "LICENSE", "install.ps1", P.FENSTER,
                   P.FENSTER_XAML, "logo.png",
                   "THIRD_PARTY_NOTICES.md",
                   "Open MCP CAD/omcad_a_symbole.py",
                   "server/pyproject.toml", "server/README.md",
                   "server/LICENSE", "server/open_mcp_cad/server.py",
                   "server/open_mcp_cad/bootstrap.py",
                   "server/open_mcp_cad/knowledge/known_issues.json"))
        pruefe("T3 Anleitung, Installer und installierbarer Server da",
               all(p in drin for p in pflicht),
               [p for p in pflicht if p not in drin])

        # T3c (2026-09-28): der Server im Paket laesst sich laden — jedes
        # Modul, das server.py relativ importiert, liegt daneben (das Paket
        # nimmt nur eingecheckte Dateien; ein neues, nicht eingechecktes
        # Modul fehlte dort still). Und das Extra "stubs", das install.ps1
        # nimmt, steht im pyproject des Pakets und bringt cwapi3d.
        import ast as _ast
        import tomllib
        srv_basis = os.path.join(ordner, P.UNTERORDNER)
        srv = os.path.join(srv_basis, "server", "open_mcp_cad", "server.py")
        rel = set()
        for n in _ast.walk(_ast.parse(open(srv, encoding="utf-8").read())):
            if isinstance(n, _ast.ImportFrom) and n.level == 1:
                if n.module:
                    rel.add(n.module.split(".")[0])
                else:
                    rel.update(a.name for a in n.names)

        def _fehlt(namen):
            return sorted(m for m in namen if not os.path.exists(
                os.path.join(srv_basis, "server", "open_mcp_cad", m + ".py"))
                and not os.path.isdir(os.path.join(
                    srv_basis, "server", "open_mcp_cad", m)))
        with open(os.path.join(srv_basis, "server", "pyproject.toml"),
                  "rb") as fh:
            stubs = tomllib.load(fh)["project"][
                "optional-dependencies"].get("stubs", [])
        pruefe("T3c jedes relativ importierte Modul von server.py im Paket "
               "(%d), Extra stubs mit cwapi3d im pyproject des Pakets"
               % len(rel),
               "api_hilfe" in rel and not _fehlt(rel)
               and any(d.strip().startswith("cwapi3d") for d in stubs),
               (_fehlt(rel), stubs))
        pruefe("T3c-K KONTROLLE: ein Modul, das es nicht gibt, fiele auf",
               _fehlt(rel | {"gibt_es_nicht"}) == ["gibt_es_nicht"])
        # T3d (2026-09-29): jedes Modul, das install.ps1 mit `-m
        # open_mcp_cad.<modul>` ruft, liegt im Server des Pakets (das Paket
        # nimmt nur Eingechecktes — ein neues, nicht eingechecktes Modul
        # fehlte dort still, und der Installer scheiterte erst beim Nutzer).
        ps1_text = open(os.path.join(P.VERTEILUNG, "install.ps1"),
                        encoding="ascii").read()
        gerufen = set(re.findall(r"-m open_mcp_cad\.(\w+)", ps1_text))
        pruefe("T3d die Module, die install.ps1 ruft (%s), liegen im Paket"
               % ", ".join(sorted(gerufen)),
               {"server", "ki_eintragen"} <= gerufen and not _fehlt(gerufen),
               _fehlt(gerufen))

        # T3b: jede Uebersetzung aus verteilung/ liegt im Paket. Die Liste
        # kommt aus dem Ordner selbst, nicht aus diesem Test.
        uebersetzt = sorted(n for n in os.listdir(
            os.path.join(REPO, "verteilung"))
            if n.startswith("ANLEITUNG.") and n.count(".") == 2)
        pruefe("T3b Uebersetzungen der Anleitung im Paket (%s)"
               % ", ".join(uebersetzt),
               len(uebersetzt) >= 3 and all(u + x in drin for x in uebersetzt),
               [x for x in uebersetzt if u + x not in drin])

        with zipfile.ZipFile(archiv) as z:
            im_zip = sorted(n.split("/", 1)[1] for n in z.namelist())
        pruefe("T4 das ZIP enthaelt genau den Ordner",
               im_zip == drin, "%d gegen %d" % (len(im_zip), len(drin)))

        cmd = open(os.path.join(ordner, P.INSTALLIEREN), "rb").read()
        pruefe("T5 %s hat CRLF (cmd.exe)" % P.INSTALLIEREN,
               b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b""))
        ps1 = open(os.path.join(ordner, P.UNTERORDNER, "install.ps1"),
                   "rb").read()
        pruefe("T5 install.ps1 ist reines ASCII (PowerShell 5.1 ohne BOM)",
               all(b < 128 for b in ps1),
               "erstes Nicht-ASCII bei Byte %s"
               % next((i for i, b in enumerate(ps1) if b >= 128), None))
        fps1 = open(os.path.join(ordner, P.UNTERORDNER, P.FENSTER),
                    "rb").read()
        fxaml = open(os.path.join(ordner, P.UNTERORDNER, P.FENSTER_XAML),
                     "rb").read()
        pruefe("T5 %s ist reines ASCII, die Texte stehen in %s (UTF-8 mit "
               "Umlauten, ohne BOM)" % (P.FENSTER, P.FENSTER_XAML),
               all(b < 128 for b in fps1)
               and not fxaml.startswith(b"\xef\xbb\xbf")
               and "ü".encode("utf-8") in fxaml)

        harte, _w = P.pruefen(ordner, [])
        pruefe("T6 kein lokaler Benutzerpfad im Paket", not harte, harte[:5])

        # KONTROLLEN — muessen anschlagen. Der Pfad ist zusammengesetzt,
        # sonst stuende er hier selbst im Quelltext und der Export (T9)
        # schluege an dieser Datei an.
        falle = os.path.join(t, "falle")
        os.makedirs(falle)
        with io.open(os.path.join(falle, "x.py"), "w", encoding="utf-8") as fh:
            fh.write('PFAD = r"C:\\Users\\' + 'erika\\projekte"\n')
            fh.write("# %s 2026\n" % ERIKA)
            fh.write('LOG = r"C:\\Users\\Public\\x.log"  # %USERPROFILE%\n')
        h, w = P.pruefen(falle, [NAME])
        pruefe("T6 KONTROLLE: Benutzerpfad und Name fallen auf, Public nicht",
               h == ["x.py:1"] and w == ["x.py:2"], (h, w))

        # T6b: Binaerdateien. Rueckmeldung 2026-09-25: eine Cadwork-Datei
        # (.3d, innen ein ZIP) traegt Benutzer- und Rechnername, IP und MAC
        # dessen, der sie gespeichert hat. Die Pruefung hatte jede Datei,
        # die kein UTF-8 ist, ungelesen uebersprungen.
        binaer = os.path.join(t, "falle_binaer")
        os.makedirs(binaer)

        def _3d(name, inhalt):
            with zipfile.ZipFile(os.path.join(binaer, name), "w",
                                 zipfile.ZIP_DEFLATED) as z:
                z.writestr("Project.xml", "<p/>")
                z.writestr("CONTENT_3D.FDB", inhalt)

        _3d("pfad.3d", b"\x00\x01" + ("C:\\Users\\" + "erika\\AppData")
            .encode("latin-1") + b"\x00")
        _3d("name.3d", b"\x00\x00" + ERIKA.encode("utf-16-le"))
        _3d("name_ungerade.3d", b"\x00\x00\x00" + ERIKA.encode("utf-16-le"))
        _3d("sauber.3d", b"\x00\x01" + "C:\\Users\\Public\\x.log"
            .encode("utf-16-le"))
        with open(os.path.join(binaer, "roh.bin"), "wb") as fh:
            fh.write(b"\xff\xfe\x00" + ERIKA.encode("latin-1"))
        with open(os.path.join(binaer, "kaputt.3d"), "wb") as fh:
            fh.write(b"PK\x03\x04" + b"\x00" * 12)
        h, w = P.pruefen(binaer, [NAME])

        def _trifft(liste, datei):
            return any(re.split(r"[!:]| \(", x)[0] == datei for x in liste)

        pruefe("T6b Benutzerpfad IN einer .3d faellt auf",
               _trifft(h, "pfad.3d"), h)
        pruefe("T6b Name IN einer .3d faellt auf (UTF-16, auch ungerade)",
               _trifft(w, "name.3d") and _trifft(w, "name_ungerade.3d"), w)
        pruefe("T6b Name in einer Datei, die kein UTF-8 ist, faellt auf",
               _trifft(w, "roh.bin"), w)
        pruefe("T6b ein unlesbares Archiv gilt als Fund, nicht als sauber",
               _trifft(h, "kaputt.3d"), h)
        pruefe("T6b KONTROLLE: eine saubere .3d (nur Public) faellt nicht auf",
               not _trifft(h + w, "sauber.3d"), (h, w))

        echt = P.paket_dateien
        try:
            P.paket_dateien = lambda: echt() + [
                (os.path.join(falle, "x.py"),
                 P.UNTERORDNER + "/Open MCP CAD/x.py")]
            try:
                P.bauen(os.path.join(t, "k1"), edge=False)
                k1 = "gebaut"
            except P.PaketFehler as exc:
                k1 = str(exc)
            pruefe("T6 KONTROLLE: bauen() bricht an einem Benutzerpfad ab",
                   "Benutzerpfad" in k1, k1[:90])
            P.paket_dateien = lambda: echt() + [
                (os.path.join(falle, "gibtsnicht.py"), "x.py")]
            try:
                P.bauen(os.path.join(t, "k2"))
                k2 = "gebaut"
            except P.PaketFehler as exc:
                k2 = str(exc)
            pruefe("T7 KONTROLLE: fehlende Quelle bricht ab",
                   "Quelle fehlt" in k2, k2[:90])
        finally:
            P.paket_dateien = echt

        def bau(muster, unter, edge=None, spuren=SYNTH_SPUREN):
            try:
                P.bauen(os.path.join(t, unter), oeffentlich=True,
                        muster=muster, edge=edge, spuren=spuren)
                return "gebaut"
            except P.PaketFehler as exc:
                return str(exc)

        k3 = bau([NAME], "oeff")
        pruefe("T8 --oeffentlich baut, wenn kein Muster trifft",
               k3 == "gebaut", k3[:80])
        k4 = bau([re.compile("Open MCP CAD")], "oeff_k", edge=False)
        pruefe("T8 KONTROLLE: --oeffentlich bricht an einem Treffer ab",
               "Persoenlichem" in k4, k4[:80])
        k5 = bau([], "oeff_leer")
        pruefe("T8 KONTROLLE: --oeffentlich ohne Muster bricht ab",
               "persoenlich.txt" in k5, k5[:80])

        eigene = P.persoenliche_muster()
        echte = P.private_muster()
        if eigene or echte:
            k6 = bau(eigene or [NAME], "oeff_eigen",
                     spuren=echte or SYNTH_SPUREN)
            pruefe("T8 das Paket besteht die lokale%s%s" % (
                " persoenlich.txt (%d Muster)" % len(eigene) if eigene else "",
                " privat_spuren.txt (%d Muster)" % len(echte) if echte
                else ""), k6 == "gebaut", k6[:160])

        # --- Export fuer das oeffentliche Repo ---------------------------
        klon = os.path.join(t, "klon")
        os.makedirs(os.path.join(klon, ".git"))
        with open(os.path.join(klon, ".git", "HEAD"), "w") as fh:
            fh.write("bleibt")
        with open(os.path.join(klon, "veraltet.txt"), "w") as fh:
            fh.write("weg")
        try:
            n, _c = E.exportieren(klon, [NAME], sauber_verlangen=False,
                                  spuren=SYNTH_SPUREN)
            fehler = ""
        except E.ExportFehler as exc:
            n, fehler = 0, str(exc)
        drin = dateien(klon)
        soll = sorted(E.oeffentliche_dateien())
        ohne_git = [d for d in drin if not d.startswith(".git/")]
        pruefe("T9 Export = eingecheckte Dateien ohne Arbeitsnotizen",
               not fehler and ohne_git == soll and n == len(soll),
               fehler[:160] or "%d gegen %d" % (len(ohne_git), len(soll)))
        pruefe("T9 keine Arbeitsnotizen, README/LICENSE/Tests dabei",
               not any(d.startswith(E.NICHT_OEFFENTLICH) for d in drin)
               and {"README.md", "LICENSE", "tests/test_offline.py"} <= set(drin))
        pruefe("T9 .git bleibt, Veraltetes ist weg",
               ".git/HEAD" in drin and "veraltet.txt" not in drin)
        if eigene or echte:
            try:
                E.exportieren(klon, eigene or [NAME], sauber_verlangen=False,
                              spuren=echte or SYNTH_SPUREN)
                k7 = "ok"
            except E.ExportFehler as exc:
                k7 = str(exc)
            pruefe("T9 der Export besteht die lokale%s%s" % (
                " persoenlich.txt" if eigene else "",
                " privat_spuren.txt" if echte else ""), k7 == "ok", k7[:160])

        def export(ziel, muster, spuren=SYNTH_SPUREN):
            try:
                E.exportieren(ziel, muster, sauber_verlangen=False,
                              spuren=spuren)
                return "ok"
            except E.ExportFehler as exc:
                return str(exc)

        k8 = export(klon, [re.compile("Open MCP CAD")])
        pruefe("T10 KONTROLLE: ein Treffer bricht den Export ab",
               "Persoenliches" in k8, k8[:80])
        k9 = export(klon, [])
        pruefe("T10 KONTROLLE: ohne Muster bricht der Export ab",
               "persoenlich.txt" in k9, k9[:80])
        k10 = export(falle, [NAME])
        pruefe("T10 KONTROLLE: ein Ziel ohne .git wird nicht angefasst",
               "kein Git" in k10 and os.path.isfile(os.path.join(falle, "x.py")),
               k10[:80])

        spuren_pruefen(t, klon, export, echte)
        export_echt_pruefen(t, export, eigene, echte)
        erweiterungen_paket_pruefen(t, klon, export)
        schnellstart_paket_pruefen(t, ordner, warnungen)
        ki_hinweis_paket_pruefen(t, ordner)

    anleitung_pruefen()
    ki_hinweis_pruefen()
    schnellstart_quellen_pruefen()

    print("\n" + "=" * 62)
    print("%d/%d bestanden" % (sum(_ergebnisse), len(_ergebnisse)))
    return 0 if all(_ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
