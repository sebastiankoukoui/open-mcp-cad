#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baut das Verteilpaket: einen sauberen Ordner und ein ZIP zum Weitergeben.

    python scripts/paket_bauen.py                 # Fassung fuer Kollegen
    python scripts/paket_bauen.py --oeffentlich   # bricht ab, solange
                                                  # Persoenliches drin ist
    python scripts/paket_bauen.py --ziel <ordner> # statt dist/

Ergebnis: dist/Open-MCP-CAD-<version>/ und dist/Open-MCP-CAD-<version>.zip

OBEN liegt nur, was ein Nutzer anfassen soll (Rueckmeldung 2026-09-29:
Kollegen ohne IT-Kenntnisse fanden in vielen Dateien nicht, was zu tun
ist):

    1_INSTALLIEREN.cmd    Doppelklick: der Installer
    2_ANLEITUNG.pdf       Schnellstart, deutsch (verbindlich)
    2_GUIDE_EN.pdf        Schnellstart, englisch
    Programmdateien/      alles andere:
        Open MCP CAD/         der Plugin-Ordner fuer Cadwork
        server/               das Paket open_mcp_cad + pyproject
        install.ps1           der eigentliche Installer
        install_fenster.ps1   das Einrichtungsfenster (seit 2026-10-09), mit
        install_fenster.xaml  seinen Seiten und Texten und
        logo.png              dem Logo; es startet install.ps1
        ANLEITUNG*.md         die ausfuehrliche Anleitung, vier Sprachen
        FUER_KI_ASSISTENTEN.md  der Abschnitt "Fuer KI-Assistenten" aus
                              den vier Anleitungen (erzeugt, KI_HINWEIS)
        Anleitungen/          Schnellstart als HTML (alle Sprachen) und
                              als PDF auf Franzoesisch und Italienisch
        LICENSE, THIRD_PARTY_NOTICES.md

Fehlt Microsoft Edge (es druckt die PDFs), liegt statt jedes PDFs die
HTML-Fassung oben, und das Skript sagt es; `--oeffentlich` bricht dann ab
(ein Release ohne PDF waere genau das, was die Rueckmeldung bemaengelte).

WAS NICHT HINEINKOMMT, und warum: Tests, Arbeitsnotizen (docs/, CLAUDE.md,
AGENTS.md, Uebergaben) und die Steckplatz-Ordner A-F. Sie sind fuer die
Entwicklung da; einem Kollegen sagen sie nichts, und A-F nebeneinander
installiert stuenden siebenfach im Cadwork-Menue.

KEINE EIGENE DATEILISTE (Arbeitsregel 3): der Plugin-Ordner kommt aus
`deployment_pruefen.DATEIEN` — derselben Liste, gegen die das Ausrollen
geprueft wird —, das Server-Paket aus `git ls-files open_mcp_cad` (nur
Eingechecktes, keine Caches).

PERSOENLICHES: das Ergebnis wird durchsucht. Ein Benutzerpfad
(C:\\Users\\<Name>, ausser Public) bricht IMMER ab — er waere auf jedem
anderen Rechner falsch. Namen und Projektnamen stehen NICHT hier (sonst
stuenden genau sie in einem oeffentlichen Repo), sondern in der lokalen,
nicht eingecheckten `persoenlich.txt` im Repo-Wurzelordner: eine Regex je
Zeile, `#` fuer Kommentare, Gross/Klein egal. Ohne `--oeffentlich` werden
Treffer nur gemeldet; mit bricht es ab — und OHNE diese Datei ebenfalls:
eine leere Liste saehe sonst wie eine bestandene Pruefung aus.

SPUREN PRIVATER TEILE: ebenso lokal, in `privat_spuren.txt` daneben
(Format bei PRIVAT_SPUREN unten). Mit `--oeffentlich` bricht jeder Treffer
ab, und ohne Muster ebenfalls. Die beiden lokalen Dateien selbst landen nie
im Paket (`lokale_dateien_in`).
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
if HIER not in sys.path:
    sys.path.insert(0, HIER)

import deployment_pruefen as DP                             # noqa: E402

PLUGIN = "Open MCP CAD"
VERTEILUNG = os.path.join(REPO, "verteilung")
#: Das Einrichtungsfenster (seit 2026-10-09): der Doppelklick ohne Schalter
#: startet es, es startet dann install.ps1.
FENSTER = "install_fenster.ps1"
FENSTER_XAML = "install_fenster.xaml"
#: Der Doppelklick oben im Paket; er startet UNTERORDNER\install.ps1
#: (`bauen` prueft, dass die Datei genau diesen Pfad nennt).
INSTALLIEREN = "1_INSTALLIEREN.cmd"
#: Alles, was ein Nutzer nicht anfassen muss.
UNTERORDNER = "Programmdateien"

# Ein Benutzerordner ausser Public: auf jedem anderen Rechner falsch.
# Platzhalter wie <Name>, ... oder %USERPROFILE% fallen nicht darunter.
HART = re.compile(r"[A-Za-z]:\\+Users\\+(?!Public(?![\w.-]))\w[\w.-]*", re.I)
PERSOENLICH = os.path.join(REPO, "persoenlich.txt")

# Spuren privater Teile (Rueckmeldung 2026-09-28: ein Audit fand Spuren
# eines privaten Repos in Werkzeugbeschreibungen, Kommentaren und einem
# Test). Die MUSTER stehen seit 2026-10-01 NICHT mehr hier: eingecheckt
# haette der Export genau die Liste veroeffentlicht, die sagt, was privat
# ist. Sie liegen wie die Namen in einer lokalen, nicht eingecheckten Datei
# im Repo-Wurzelordner, `privat_spuren.txt`:
#
#     # Kommentar
#     <Regex>          eine je Zeile, Gross/Klein egal
#     #+ <Text>        ein Beispiel, das ein Muster treffen MUSS
#     #- <Text>        ein Text, den kein Muster treffen darf
#
# Ohne diese Datei (oder ohne ein Muster darin) brechen der Export und
# `--oeffentlich` ab, wie ohne persoenlich.txt. Hier bleibt nur der
# Mechanismus und eine Pruefung, die nichts verraet: die beiden lokalen
# Dateien selbst duerfen nie in Paket oder Export landen (LOKALE_DATEIEN).
PRIVAT_SPUREN = os.path.join(REPO, "privat_spuren.txt")
LOKALE_DATEIEN = ("persoenlich.txt", "privat_spuren.txt")
#: None = die Muster aus `privat_spuren.txt`, zur Aufrufzeit gelesen. Ein
#: Gate darf hier eine eigene Liste einsetzen.
PRIVATE_SPUREN = None

# AUSNAHME mit Absicht, und sie wird gemeldet, nicht verschwiegen: das
# eingebaute Wissen ist ERZEUGT (Export aus dem privaten Repo, Feld
# `scope: "api"`). Seine Treffer werden dort bereinigt und neu exportiert,
# nie hier von Hand. Bis dahin zaehlt `private_spuren` sie getrennt.
SPUREN_AUSGENOMMEN = ("open_mcp_cad/knowledge/",)


def wissen_eintraege(ordner, funde):
    """Ausgenommene Funde ("datei:zeile") im erzeugten Wissen -> die
    Eintraege dahinter ("known_issues.json:<id>"), je einmal, in
    Fundreihenfolge — damit sie im privaten Repo umgestuft werden koennen.
    Ein Fund vor dem ersten Eintrag heisst "<datei>:(Kopf)", eine Datei
    ohne lesbares JSON "<datei>:(kein JSON)". Wirft nie."""
    import json
    aus, anfaenge = [], {}
    for f in funde:
        rel, _sep, nr = f.rpartition(":")
        if not rel or not nr.isdigit() or not rel.endswith(".json"):
            continue
        if rel not in anfaenge:
            anfaenge[rel] = _eintrag_anfaenge(os.path.join(ordner, rel))
        name = os.path.basename(rel.replace("\\", "/"))
        if anfaenge[rel] is None:
            eintrag = "%s:(kein JSON)" % name
        else:
            vorher = [i for z, i in anfaenge[rel] if z <= int(nr)]
            eintrag = "%s:%s" % (name, vorher[-1] if vorher else "(Kopf)")
        if eintrag not in aus:
            aus.append(eintrag)
    return aus


def _eintrag_anfaenge(pfad):
    """-> [(erste Zeile, id)] der Eintraege einer Wissensdatei (Listen von
    Objekten mit "id"), None, wenn sie nicht lesbar ist. Die erste Zeile ist
    die "{"-Zeile des Eintrags; gefunden wird je id ihre "id"-Zeile, in der
    Reihenfolge der Datei."""
    import json
    try:
        with io.open(pfad, encoding="utf-8") as fh:
            text = fh.read()
        daten = json.loads(text)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(daten, dict):
        return None
    ids = [e["id"] for v in daten.values() if isinstance(v, list)
           for e in v if isinstance(e, dict) and isinstance(e.get("id"), str)]
    zeilen, liste, i = text.splitlines(), [], 0
    for n, z in enumerate(zeilen, 1):
        if i >= len(ids):
            break
        m = re.match(r'\s*"id"\s*:\s*("(?:[^"\\]|\\.)*")', z)
        try:
            gleich = m is not None and json.loads(m.group(1)) == ids[i]
        except ValueError:
            gleich = False
        if gleich:
            start = n
            while start > 1 and zeilen[start - 2].strip() not in ("{", "},"):
                start -= 1
            liste.append((max(start - 1, 1), ids[i]))
            i += 1
    return liste


class PaketFehler(Exception):
    pass


def version():
    """`__version__` aus open_mcp_cad/__init__.py — gelesen, nicht importiert."""
    with io.open(os.path.join(REPO, "open_mcp_cad", "__init__.py"),
                 encoding="utf-8") as fh:
        treffer = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    if not treffer:
        raise PaketFehler("__version__ nicht gefunden")
    return treffer.group(1)


def _eingecheckt(pfad):
    aus = subprocess.run(["git", "ls-files", pfad], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [z for z in aus.splitlines() if z.strip()]


def paket_dateien():
    """-> [(Quelle, Ziel relativ zum Paketordner)].

    Oben nur der Doppelklick (INSTALLIEREN); alles andere unter UNTERORDNER.
    Die Anleitungen als PDF/HTML kommen in `bauen` dazu (sie entstehen erst
    beim Bauen)."""
    u = UNTERORDNER
    dateien = [(os.path.join(VERTEILUNG, INSTALLIEREN), INSTALLIEREN)]
    for muster in DP.DATEIEN:
        name = muster.format(ordner=PLUGIN)
        dateien.append((os.path.join(REPO, "cad_plugin", PLUGIN, name),
                        os.path.join(u, PLUGIN, name)))
    for rel in _eingecheckt("open_mcp_cad"):
        dateien.append((os.path.join(REPO, rel),
                        os.path.join(u, "server", rel)))
    anleitung = os.path.join(VERTEILUNG, "ANLEITUNG.md")
    dateien += [
        (os.path.join(REPO, "pyproject.toml"),
         os.path.join(u, "server", "pyproject.toml")),
        (os.path.join(REPO, "LICENSE"), os.path.join(u, "server", "LICENSE")),
        # pyproject verlangt `readme = "README.md"`; ohne sie scheitert pip.
        (anleitung, os.path.join(u, "server", "README.md")),
        (anleitung, os.path.join(u, "ANLEITUNG.md")),
    ]
    # Uebersetzungen der Anleitung (en, fr, it) liegen daneben, gefunden
    # ueber das Namensmuster statt ueber eine eigene Liste.
    for name in sorted(os.listdir(VERTEILUNG)):
        if re.fullmatch(r"ANLEITUNG\.[a-z]{2}\.md", name):
            dateien.append((os.path.join(VERTEILUNG, name),
                            os.path.join(u, name)))
    dateien += [
        (os.path.join(VERTEILUNG, "install.ps1"), os.path.join(u, "install.ps1")),
        # Das Einrichtungsfenster (Doppelklick ohne Schalter, seit
        # 2026-10-09): Skript, Seiten mit Texten, Logo.
        (os.path.join(VERTEILUNG, FENSTER), os.path.join(u, FENSTER)),
        (os.path.join(VERTEILUNG, FENSTER_XAML), os.path.join(u, FENSTER_XAML)),
        (os.path.join(REPO, "assets", "logo.png"), os.path.join(u, "logo.png")),
        (os.path.join(REPO, "LICENSE"), os.path.join(u, "LICENSE")),
        # Lizenzen fremder Teile (seit 2026-09-28: Lucide-Symbole im Plugin;
        # der Text steht zusaetzlich in omcad_a_symbole.py selbst).
        (os.path.join(REPO, "THIRD_PARTY_NOTICES.md"),
         os.path.join(u, "THIRD_PARTY_NOTICES.md")),
    ]
    return dateien


#: Die Schnellstart-Anleitung oben im Paket: (Sprache, Name ohne Endung).
#: Als .pdf — oder als .html, wenn kein Edge zum Drucken da war.
ANLEITUNG_OBEN = (("de", "2_ANLEITUNG"), ("en", "2_GUIDE_EN"))
#: Unter UNTERORDNER: der Schnellstart als HTML in allen Sprachen (mit
#: `bilder/`), als PDF in den Sprachen, die oben nicht stehen.
ANLEITUNGEN = "Anleitungen"
#: Quelle: verteilung/SCHNELLSTART.md (deutsch, verbindlich) und
#: SCHNELLSTART.<sprache>.md; Bilder aus verteilung/bilder (erzeugt von
#: scripts/bilder_rendern.py).
SCHNELLSTART = "SCHNELLSTART"
BILDER = os.path.join(VERTEILUNG, "bilder")


#: Der Hinweis fuer KI-Assistenten (Rueckmeldung 2026-09-29: die Codex-App
#: las das Plugin, sah dessen eigenes TCP-Protokoll und wollte erst "einen
#: kleinen Adapter" bauen; es ging erst, als man ihr sagte, dass alles schon
#: installiert ist). Die Quelle ist der markierte Abschnitt in
#: verteilung/ANLEITUNG(.xx).md — derselbe steht in README(.xx).md, test_paket
#: T18 vergleicht beide. Im Paket als eigene Datei unter UNTERORDNER, alle
#: Sprachen, Deutsch zuerst; oben bleibt es bei oben_soll().
KI_HINWEIS = "FUER_KI_ASSISTENTEN.md"
KI_ABSCHNITT = re.compile(r"<!-- ki-assistenten:anfang -->\n(.*?)"
                          r"<!-- ki-assistenten:ende -->", re.S)
KI_KOPF = (
    "# Open MCP CAD - for AI assistants\n\n"
    "The same text in four languages (German is binding). It is also part\n"
    "of ANLEITUNG*.md next to this file and of README.md in the source\n"
    "repository. Everything described here is already installed or is\n"
    "installed by 1_INSTALLIEREN.cmd; nothing has to be built.\n\n")


def anleitung_quellen():
    """-> {Sprache: Pfad} der ausfuehrlichen Anleitung (Namensmuster)."""
    aus = {}
    for name in sorted(os.listdir(VERTEILUNG)):
        m = re.fullmatch(r"ANLEITUNG(?:\.([a-z]{2}))?\.md", name)
        if m:
            aus[m.group(1) or "de"] = os.path.join(VERTEILUNG, name)
    return aus


def ki_abschnitt(text):
    """Der Abschnitt fuer KI-Assistenten aus einem Markdown-Text, oder None."""
    m = KI_ABSCHNITT.search(text.replace("\r\n", "\n"))
    return m.group(1).strip("\n") + "\n" if m else None


def ki_hinweis_text(quellen=None):
    """-> der Inhalt von KI_HINWEIS; PaketFehler, wenn eine Anleitung den
    Abschnitt nicht hat (nie still eine Sprache weniger)."""
    quellen = quellen if quellen is not None else anleitung_quellen()
    if "de" not in quellen:
        raise PaketFehler("keine deutsche Anleitung fuer %s" % KI_HINWEIS)
    teile, fehlt = [], []
    for sp in sorted(quellen, key=lambda s: (s != "de", s)):
        with io.open(quellen[sp], encoding="utf-8") as fh:
            abschnitt = ki_abschnitt(fh.read())
        if abschnitt is None:
            fehlt.append(os.path.basename(quellen[sp]))
        else:
            teile.append(abschnitt)
    if fehlt:
        raise PaketFehler("Abschnitt fuer KI-Assistenten fehlt in: %s"
                          % ", ".join(fehlt))
    return KI_KOPF + "\n---\n\n".join(teile)


def oben_soll(ordner=None):
    """Was oben im Paketordner liegen soll, in der Reihenfolge, in der es
    der Explorer nach Namen zeigt (Ordner kommen dort ohnehin zuerst)."""
    namen = [INSTALLIEREN]
    for _sprache, stamm in ANLEITUNG_OBEN:
        html = stamm + ".html"
        if (ordner is not None and os.path.isfile(os.path.join(ordner, html))
                and not os.path.isfile(os.path.join(ordner, stamm + ".pdf"))):
            namen.append(html)
        else:
            namen.append(stamm + ".pdf")
    return namen + [UNTERORDNER]


def oben_abweichung(ordner):
    """-> Liste der Abweichungen oben im Paketordner (leer = passt)."""
    soll, ist = set(oben_soll(ordner)), set(os.listdir(ordner))
    aus = ["zu viel: %s" % n for n in sorted(ist - soll)]
    aus += ["fehlt: %s" % n for n in sorted(soll - ist)]
    for n in sorted(soll & ist):
        if (n == UNTERORDNER) != os.path.isdir(os.path.join(ordner, n)):
            aus.append("falsche Art: %s" % n)
    return aus


def installieren_pruefen(pfad=None):
    """Nennt der Doppelklick genau UNTERORDNER\\install.ps1? Sonst startet
    er im Paket nichts. -> Fehlertext oder None. (Dass er es WIRKLICH
    startet, misst test_installer I11 am gebauten Paket.)"""
    pfad = pfad or os.path.join(VERTEILUNG, INSTALLIEREN)
    with io.open(pfad, encoding="ascii") as fh:
        text = fh.read()
    for ziel in ("install.ps1", FENSTER):
        soll = '"%%~dp0%s\\%s"' % (UNTERORDNER, ziel)
        if soll not in text:
            return "%s startet nicht %s" % (INSTALLIEREN, soll)
    return None


# --- Schnellstart: Markdown -> HTML -> PDF (Rueckmeldung 2026-09-29) --------
# Die Quelle ist Markdown (auf GitHub lesbar), aber nur der kleine Teil, den
# die Anleitungen brauchen: #/##/###, Absaetze, nummerierte und
# Strich-Listen (auch eingerueckt, mit Codeblock darin), > Tipp, ```Code```,
# **fett**, `code`, [Text](Adresse), ![Bild](bilder/x.png) auf eigener
# Zeile. Was die Umwandlung nicht kennt, bleibt als Zeichen stehen, und
# `md_reste` findet es (test_paket T14) — nie still verschluckt.

def schnellstart_quellen():
    """-> {Sprache: Pfad} aus verteilung/ (Namensmuster, keine Liste)."""
    aus = {}
    for name in sorted(os.listdir(VERTEILUNG)):
        m = re.fullmatch(re.escape(SCHNELLSTART) + r"(?:\.([a-z]{2}))?\.md",
                         name)
        if m:
            aus[m.group(1) or "de"] = os.path.join(VERTEILUNG, name)
    return aus


def _html(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _inline(text):
    """Eine Zeile Markdown -> HTML (Code, Links, fett)."""
    teile = re.split(r"(`[^`]+`)", text)
    aus = []
    for t in teile:
        if len(t) > 1 and t.startswith("`") and t.endswith("`"):
            aus.append("<code>%s</code>" % _html(t[1:-1]))
            continue
        t = _html(t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                   lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)),
                   t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        aus.append(t)
    return "".join(aus)


_LISTE = re.compile(r"^( *)(\d+\.|-) (.*)$")
_BILD = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")


def _liste_bauen(eintraege, i, tiefe):
    """eintraege: [(Einrueckung, 'ol'/'ul', Text, [Codezeilen]|None)]."""
    art = eintraege[i][1]
    teile = ["<%s>" % art]
    while i < len(eintraege) and eintraege[i][0] == tiefe:
        _e, _a, text, code = eintraege[i]
        teile.append("<li>" + _inline(text))
        i += 1
        # Codebloecke und Zeilen, die zu DIESEM Punkt gehoeren
        while i < len(eintraege) and eintraege[i][1] in ("code", "text") \
                and eintraege[i][0] > tiefe:
            if eintraege[i][1] == "code":
                teile.append("<pre>%s</pre>" % _html("\n".join(
                    eintraege[i][3])))
            else:
                teile.append("<p>%s</p>" % _inline(eintraege[i][2]))
            i += 1
        if i < len(eintraege) and eintraege[i][0] > tiefe \
                and eintraege[i][1] in ("ol", "ul"):
            unter, i = _liste_bauen(eintraege, i, eintraege[i][0])
            teile.append(unter)
        teile.append("</li>")
    teile.append("</%s>" % art)
    return "".join(teile), i


def md_zu_html(text, bild_praefix="bilder/"):
    """Markdown (der Teil oben) -> HTML-Koerper. `bild_praefix` ersetzt
    das `bilder/` der Quelle (die Bilder liegen im Paket woanders)."""
    zeilen = text.replace("\r\n", "\n").split("\n")
    aus, absatz, i = [], [], 0

    def absatz_schliessen():
        if absatz:
            aus.append("<p>%s</p>" % _inline(" ".join(absatz)))
            del absatz[:]

    while i < len(zeilen):
        z = zeilen[i]
        s = z.strip()
        if not s:
            absatz_schliessen()
            i += 1
            continue
        if s.startswith("```"):
            absatz_schliessen()
            code, i = [], i + 1
            while i < len(zeilen) and not zeilen[i].strip().startswith("```"):
                code.append(zeilen[i])
                i += 1
            aus.append("<pre>%s</pre>" % _html("\n".join(code)))
            i += 1
            continue
        m = re.match(r"^(#{1,3}) (.*)$", z)
        if m:
            absatz_schliessen()
            n = len(m.group(1))
            aus.append("<h%d>%s</h%d>" % (n, _inline(m.group(2)), n))
            i += 1
            continue
        m = _BILD.match(s)
        if m:
            absatz_schliessen()
            quelle = m.group(2)
            if quelle.startswith("bilder/"):
                quelle = bild_praefix + quelle[len("bilder/"):]
            aus.append('<figure><img src="%s" alt="%s"><figcaption>%s'
                       '</figcaption></figure>' % (_html(quelle),
                                                   _html(m.group(1)),
                                                   _inline(m.group(1))))
            i += 1
            continue
        if s.startswith(">"):
            absatz_schliessen()
            innen = []
            while i < len(zeilen) and zeilen[i].strip().startswith(">"):
                innen.append(zeilen[i].strip()[1:].strip())
                i += 1
            aus.append('<div class="tipp">%s</div>' % _inline(" ".join(innen)))
            continue
        if _LISTE.match(z):
            absatz_schliessen()
            eintraege = []
            while i < len(zeilen):
                z = zeilen[i]
                m = _LISTE.match(z)
                einr = len(z) - len(z.lstrip(" "))
                if m:
                    eintraege.append((len(m.group(1)),
                                      "ol" if m.group(2) != "-" else "ul",
                                      m.group(3), None))
                    i += 1
                elif not z.strip():
                    # Leerzeile: die Liste geht weiter, wenn danach wieder
                    # ein Punkt oder eingerueckter Text kommt.
                    j = i + 1
                    if j < len(zeilen) and (_LISTE.match(zeilen[j]) or
                                            zeilen[j].startswith("  ")):
                        i = j
                        continue
                    break
                elif einr > 0 and z.strip().startswith("```"):
                    code, i = [], i + 1
                    while i < len(zeilen) and \
                            not zeilen[i].strip().startswith("```"):
                        code.append(zeilen[i][einr:] if zeilen[i][:einr]
                                    .strip() == "" else zeilen[i].strip())
                        i += 1
                    i += 1
                    eintraege.append((einr, "code", "", code))
                elif einr > 0 and eintraege:
                    # Fortsetzung des letzten Punkts (oder Text danach)
                    letzt = eintraege[-1]
                    if letzt[1] in ("ol", "ul") and einr > letzt[0]:
                        eintraege[-1] = (letzt[0], letzt[1],
                                         letzt[2] + " " + z.strip(), None)
                    elif letzt[1] == "text" and einr == letzt[0]:
                        eintraege[-1] = (letzt[0], "text",
                                         letzt[2] + " " + z.strip(), None)
                    else:
                        eintraege.append((einr, "text", z.strip(), None))
                    i += 1
                else:
                    break
            j = 0
            while j < len(eintraege):
                html, j = _liste_bauen(eintraege, j, eintraege[j][0])
                aus.append(html)
            continue
        absatz.append(s)
        i += 1
    absatz_schliessen()
    return "\n".join(aus)


def md_reste(html):
    """Markdown-Zeichen, die im HTML-TEXT stehen geblieben sind -> Liste."""
    text = re.sub(r"<pre>.*?</pre>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return sorted({m for m in ("**", "`", "](", "![", "\n#", "```")
                   if m in "\n" + text})


def _logo_uri():
    import base64
    with open(os.path.join(REPO, "assets", "icon-64.png"), "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


SCHNELLSTART_CSS = """
@page { size: A4; margin: 15mm 16mm 16mm 16mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1d1d1f; margin: 0; }
header { display: flex; align-items: center; gap: 12px;
         border-bottom: 3px solid #0071e3; padding-bottom: 8px;
         margin-bottom: 10px; }
header img { width: 44px; height: 44px; }
h1 { font-size: 22pt; margin: 0; }
h2 { font-size: 15pt; color: #0071e3; margin: 18px 0 6px;
     break-after: avoid; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 14px 0 4px; padding: 5px 9px;
     background: #f0f5fc; border-left: 4px solid #0071e3;
     break-after: avoid; page-break-after: avoid; }
p { margin: 5px 0; }
ol, ul { margin: 4px 0 6px; padding-left: 22px; }
li { margin: 3px 0; break-inside: avoid; page-break-inside: avoid; }
li::marker { font-weight: 700; color: #0071e3; }
code { font-family: Consolas, monospace; font-size: 9.5pt;
       background: #f2f2f4; padding: 0 3px; border-radius: 3px; }
pre { font-family: Consolas, monospace; font-size: 10pt; margin: 5px 0;
      background: #1d1d1f; color: #ffffff; padding: 7px 10px;
      border-radius: 6px; white-space: pre-wrap; break-inside: avoid; }
.tipp { background: #fff7e6; border: 1px solid #ffcf70; border-radius: 8px;
        padding: 7px 11px; margin: 8px 0; break-inside: avoid; }
figure { margin: 10px 0; text-align: center; break-inside: avoid;
         page-break-inside: avoid; }
figure img { max-width: 100%; max-height: 105mm; border: 1px solid #e3e3e6;
             border-radius: 8px; }
figcaption { font-size: 9pt; color: #6e6e73; margin-top: 3px; }
a { color: #0071e3; }
"""


def schnellstart_html(md_text, sprache, bild_praefix="bilder/"):
    """Eine ganze HTML-Seite (UTF-8) aus einer Schnellstart-Quelle."""
    koerper = md_zu_html(md_text, bild_praefix)
    titel = "Open MCP CAD"
    m = re.search(r"<h1>(.*?)</h1>", koerper)
    if m:
        titel = re.sub(r"<[^>]+>", "", m.group(1))
        koerper = koerper.replace(m.group(0), "", 1)
    return ('<!doctype html>\n<html lang="%s"><head><meta charset="utf-8">'
            '<title>%s</title><style>%s</style></head><body>\n'
            '<header><img src="%s" alt=""><h1>%s</h1></header>\n%s\n'
            '</body></html>\n' % (sprache, titel, SCHNELLSTART_CSS,
                                  _logo_uri(), titel, koerper))


#: Wo Microsoft Edge ueblicherweise liegt (Windows 10/11 bringen ihn mit).
EDGE_PFADE = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
)


def edge_finden():
    """-> Pfad auf msedge.exe oder None."""
    for p in EDGE_PFADE:
        pfad = os.path.expandvars(p)
        if "%" not in pfad and os.path.isfile(pfad):
            return pfad
    return shutil.which("msedge")


def pdf_drucken(html_datei, pdf_datei, edge=None, zeit=120):
    """HTML -> PDF mit Edge ohne Fenster. -> None oder der Grund, warum
    nicht. Ein EIGENER, leerer Profilordner: sonst reicht ein schon offenes
    Edge den Auftrag an sich weiter und kehrt ohne PDF zurueck."""
    import tempfile
    edge = edge or edge_finden()
    if not edge:
        return "Microsoft Edge nicht gefunden"
    try:
        if os.path.exists(pdf_datei):
            os.remove(pdf_datei)
    except OSError as exc:
        # Gegenpruefung 2026-09-29: ein PDF, das noch in einem Betrachter
        # offen ist, warf hier roh (PermissionError, Traceback).
        return ("altes PDF laesst sich nicht ersetzen (offen in einem "
                "anderen Programm?): %s" % exc)
    import time
    profil = tempfile.mkdtemp(prefix="omcad_edge_")
    beginn = time.time()
    try:
        url = "file:///" + os.path.abspath(html_datei).replace("\\", "/")
        r = subprocess.run(
            [edge, "--headless", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--disable-extensions",
             "--user-data-dir=" + profil, "--no-pdf-header-footer",
             "--print-to-pdf=" + os.path.abspath(pdf_datei), url],
            capture_output=True, timeout=zeit)
        # Gemessen 2026-09-29 (Edge 154): msedge.exe kehrt nach 0,1 s mit
        # 0 zurueck, das PDF schreibt ein Kindprozess ~1,5 s spaeter. Also
        # warten, bis es ganz da ist (Ende %%EOF, Groesse steht).
        groesse = -1
        while time.time() - beginn < zeit:
            try:
                with open(pdf_datei, "rb") as fh:
                    daten = fh.read()
            except OSError:
                daten = None
            if daten and daten.rstrip().endswith(b"%%EOF") \
                    and len(daten) == groesse:
                break
            groesse = len(daten) if daten else -1
            time.sleep(0.3)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "Edge: %s" % exc
    finally:
        shutil.rmtree(profil, ignore_errors=True)
    try:
        with open(pdf_datei, "rb") as fh:
            daten = fh.read()
    except OSError:
        return "Edge schrieb kein PDF in %d s (rc %s): %s" % (
            zeit, r.returncode,
            (r.stderr or b"")[-300:].decode("utf-8", "replace"))
    if daten[:5] != b"%PDF-" or not daten.rstrip().endswith(b"%%EOF"):
        return "Edge schrieb kein ganzes PDF (Kopf %r)" % daten[:5]
    return None


def schnellstart_bauen(ordner, edge=None):
    """Schreibt die Anleitungen ins Paket. -> (gedruckte PDFs, Warnungen).

    Unter UNTERORDNER/ANLEITUNGEN: je Sprache SCHNELLSTART.<sp>.html mit
    `bilder/`, dazu das PDF der Sprachen, die oben nicht stehen. Oben je
    ANLEITUNG_OBEN das PDF — oder, ohne Edge, eine HTML-Fassung, deren
    Bilder auf den Unterordner zeigen."""
    quellen = schnellstart_quellen()
    fehlt = [sp for sp, _st in ANLEITUNG_OBEN if sp not in quellen]
    if fehlt:
        raise PaketFehler("Schnellstart fehlt fuer: %s" % ", ".join(fehlt))
    ziel = os.path.join(ordner, UNTERORDNER, ANLEITUNGEN)
    os.makedirs(os.path.join(ziel, "bilder"), exist_ok=True)
    for name in sorted(os.listdir(BILDER)):
        if name.lower().endswith(".png"):
            shutil.copyfile(os.path.join(BILDER, name),
                            os.path.join(ziel, "bilder", name))
    oben = dict(ANLEITUNG_OBEN)
    gedruckt, warnungen = [], []
    edge = edge if edge is not None else edge_finden()
    for sp, pfad in sorted(quellen.items()):
        with io.open(pfad, encoding="utf-8") as fh:
            md = fh.read()
        reste = md_reste(md_zu_html(md))
        if reste:
            raise PaketFehler("%s: Markdown nicht umgewandelt: %s"
                              % (os.path.basename(pfad), reste))
        html = os.path.join(ziel, "%s.%s.html" % (SCHNELLSTART, sp))
        with io.open(html, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(schnellstart_html(md, sp))
        if sp in oben:
            pdf = os.path.join(ordner, oben[sp] + ".pdf")
        else:
            pdf = os.path.join(ziel, "%s.%s.pdf" % (SCHNELLSTART, sp))
        grund = pdf_drucken(html, pdf, edge) if edge else \
            "Microsoft Edge nicht gefunden"
        if grund is None:
            gedruckt.append(pdf)
            continue
        warnungen.append("%s: kein PDF (%s)" % (sp, grund))
        if sp in oben:
            # Oben dann die HTML-Fassung, die Bilder im Unterordner.
            with io.open(os.path.join(ordner, oben[sp] + ".html"), "w",
                         encoding="utf-8", newline="\n") as fh:
                fh.write(schnellstart_html(md, sp, "%s/%s/bilder/"
                                           % (UNTERORDNER, ANLEITUNGEN)))
    return gedruckt, warnungen


def persoenliche_muster(datei=None):
    """Die lokalen Namensmuster aus persoenlich.txt; [] ohne Datei."""
    datei = datei or PERSOENLICH
    if not os.path.isfile(datei):
        return []
    with io.open(datei, encoding="utf-8") as fh:
        zeilen = [z.strip() for z in fh]
    return [re.compile(z, re.I) for z in zeilen if z and not z.startswith("#")]


def private_muster(datei=None):
    """Die lokalen Spuren-Muster aus privat_spuren.txt; [] ohne Datei.
    Gleiches Format wie persoenlich.txt ("#+"/"#-" sind Kommentare)."""
    return persoenliche_muster(datei or PRIVAT_SPUREN)


def private_beispiele(datei=None):
    """-> (treffen, harmlos): die Zeilen "#+ <Text>" und "#- <Text>" aus
    privat_spuren.txt (Text ohne das Zeilenende, sonst woertlich);
    ([], []) ohne Datei."""
    datei = datei or PRIVAT_SPUREN
    treffen, harmlos = [], []
    if not os.path.isfile(datei):
        return treffen, harmlos
    with io.open(datei, encoding="utf-8") as fh:
        for z in fh:
            z = z.rstrip("\r\n")
            if z.startswith("#+ ") and z[3:].strip():
                treffen.append(z[3:])
            elif z.startswith("#- ") and z[3:].strip():
                harmlos.append(z[3:])
    return treffen, harmlos


def private_spuren_liste():
    """Die geltenden Spuren-Muster: PRIVATE_SPUREN, wenn ein Gate eine
    Liste eingesetzt hat, sonst die aus privat_spuren.txt."""
    if PRIVATE_SPUREN is not None:
        return list(PRIVATE_SPUREN)
    return private_muster()


def lokale_dateien_in(ordner):
    """-> relative Pfade der lokalen Musterdateien (LOKALE_DATEIEN) in
    `ordner`, auch in ZIPs. Leer = gut."""
    funde = []
    namen = {n.lower() for n in LOKALE_DATEIEN}
    for wurzel, dirs, dateinamen in os.walk(ordner):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in dateinamen:
            p = os.path.join(wurzel, n)
            rel = os.path.relpath(p, ordner)
            if n.lower() in namen:
                funde.append(rel)
            if n.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(p) as z:
                        funde += ["%s!%s" % (rel, i) for i in z.namelist()
                                  if i.replace("\\", "/").rsplit("/", 1)[-1]
                                  .lower() in namen]
                except (zipfile.BadZipFile, OSError):
                    pass
    return funde


def _pdf_stroeme(daten, ort):
    """Die ausgepackten Stroeme eines PDFs, die keine Bilder sind ->
    [(ort#strom<n>, Text als latin-1)]. Ein Strom, der sich nicht auspacken
    laesst, bleibt, wie er ist (seine Rohbytes stehen schon in der
    latin-1-Sicht des ganzen PDFs)."""
    import zlib
    aus, n, pos = [], 0, 0
    anfang = re.compile(rb"(?<!end)stream\r?\n")
    while True:
        m = anfang.search(daten, pos)
        if not m:
            break
        ende = daten.find(b"endstream", m.end())
        if ende < 0:
            break
        # Das Woerterbuch davor: ab dem letzten "obj".
        kopf_anfang = daten.rfind(b"obj", max(0, m.start() - 4096), m.start())
        kopf = daten[kopf_anfang if kopf_anfang >= 0 else m.start() - 400:
                     m.start()]
        pos = ende + 9
        if re.search(rb"/Subtype\s*/Image", kopf) or b"/FlateDecode" not in kopf:
            continue
        try:
            # decompressobj: das Zeilenende vor "endstream" ist kein Fehler.
            text = zlib.decompressobj().decompress(
                daten[m.end():ende]).decode("latin-1")
        except zlib.error:
            continue
        n += 1
        aus.append(("%s#strom%d" % (ort, n), text))
    return (aus + _pdf_texte([s for _o, s in aus], ort)
            + _pdf_utf16([daten.decode("latin-1")] + [s for _o, s in aus],
                         ort))


def _pdf_utf16(texte, ort):
    """PDF-Textstrings in UTF-16 (BOM FE FF) lesbar machen: als Hex
    `<FEFF…>` oder als Literal `(\\376\\377…)`. So schreibt Edge den Titel
    mit einem Umlaut und den Alt-Text jedes Bildes (Struktur des PDFs).
    Gemessen 2026-09-29 (Gegenpruefung): ein Name NUR im Alt-Text eines
    Bildes oder im Titel mit Umlaut fand die Pruefung vorher nicht — auf
    der Seite steht er nicht, also auch nicht im Seitentext."""
    funde = []
    for t in texte:
        for h in re.findall(r"<\s*(FEFF[0-9A-Fa-f\s]*)>", t, re.I):
            h = re.sub(r"\s", "", h)
            try:
                funde.append(bytes.fromhex(h[:len(h) // 2 * 2]).decode(
                    "utf-16-be", "replace"))
            except ValueError:
                pass
        for roh in re.findall(r"\((\xfe\xff(?:\\.|[^\\)])*)\)", t, re.S):
            b = re.sub(r"\\([0-7]{1,3}|.)", lambda m: chr(int(m.group(1), 8))
                       if m.group(1)[0] in "01234567" else m.group(1), roh,
                       flags=re.S).encode("latin-1", "replace")
            funde.append(b.decode("utf-16-be", "replace"))
    return [("%s#utf16" % ort, "\n".join(funde))] if funde else []


def _pdf_cmap(text):
    """Eine ToUnicode-CMap -> {Code (Hex, gross): Zeichen}."""
    karte = {}

    def zeichen(h):
        try:
            return bytes.fromhex(h).decode("utf-16-be", "replace")
        except ValueError:
            return "?"
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            karte[a.upper()] = zeichen(b)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for a, e, rest in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|"
                r"\[[^\]]*\])", block):
            von, bis, breite = int(a, 16), int(e, 16), len(a)
            if bis - von > 4096:
                continue
            if rest.startswith("["):
                ziele = re.findall(r"<([0-9A-Fa-f]+)>", rest)
                for k, z in enumerate(ziele[:bis - von + 1]):
                    karte["%0*X" % (breite, von + k)] = zeichen(z)
            else:
                basis = int(rest[1:-1], 16)
                for k in range(bis - von + 1):
                    karte["%0*X" % (breite, von + k)] = chr(basis + k) \
                        if basis + k < 0x110000 else "?"
    return karte


def _pdf_texte(stroeme, ort):
    """Der Seitentext eines PDFs, so weit er sich ohne Schriftzuordnung
    lesen laesst: jede ToUnicode-CMap auf JEDEN Textstrang angewandt, je
    CMap eine Sicht (die richtige Schrift trifft, die anderen ergeben
    Kauderwelsch). Gemessen 2026-09-29: Edge schreibt Text nur als
    Glyphennummern (<002B0044…> Tj) — ohne diese Sicht fand die Pruefung
    einen Namen im Fliesstext eines PDFs NICHT."""
    karten = [_pdf_cmap(s) for s in stroeme if "begincmap" in s]
    straenge = []
    for s in stroeme:
        if "begincmap" in s:
            continue
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*Tj|\[((?:[^\]])*)\]\s*TJ",
                             s):
            if m.group(1) is not None:
                straenge.append([m.group(1)])
            else:
                straenge.append(re.findall(r"<([0-9A-Fa-f]+)>", m.group(2)))
    aus = []
    for k, karte in enumerate(karten, 1):
        if not karte:
            continue
        breite = len(next(iter(karte)))
        zeilen = []
        for teile in straenge:
            h = "".join(teile).upper()
            zeilen.append("".join(karte.get(h[i:i + breite], "?")
                                  for i in range(0, len(h), breite)))
        # Edge trennt Woerter an Unterschneidungen in eigene Straenge
        # ("Zeichne eine W" + "and", gemessen): einmal lueckenlos
        # aneinander, einmal mit Leerzeichen (Zeilenumbrueche).
        aus.append(("%s#text%d" % (ort, k), "".join(zeilen)))
        aus.append(("%s#text%d" % (ort, k), " ".join(zeilen)))
    return aus


def _binaer_sichten(daten, ort, tiefe=0):
    """Lesbare Sichten auf Binaerdaten -> [(ort, text)], None = unlesbar.

    Rueckmeldung 2026-09-25: eine Cadwork-Datei (.3d, innen ein ZIP) traegt
    Benutzer- und Rechnername, IP und MAC dessen, der sie gespeichert hat —
    und diese Pruefung hatte jede Datei, die kein UTF-8 ist, uebersprungen.
    Deshalb: Bytes als latin-1 und als UTF-16 (gerader und ungerader
    Versatz) lesen, ZIP-Container auspacken. Ein Archiv, das sich nicht
    oeffnen laesst, ist ein Fund, kein sauberer Stand.
    """
    sichten = [(ort, daten.decode("latin-1")),
               (ort, daten.decode("utf-16-le", errors="ignore")),
               (ort, daten[1:].decode("utf-16-le", errors="ignore"))]
    if daten[:5] == b"%PDF-":
        # Seit 2026-09-29 liegen PDFs im Paket. Ihr Inhalt steckt in
        # gepackten Stroemen (FlateDecode): auspacken, was kein Bild ist —
        # Metadaten, Verweise, Seiteninhalt. Bilder bleiben gepackt: roh
        # ausgepackte Pixel waeren Megabytes Zufall, an denen ein kurzes
        # Namensmuster irgendwann zufaellig anschluege.
        sichten += _pdf_stroeme(daten, ort)
    if daten[:4] == b"PK\x03\x04" and tiefe < 3:
        try:
            with zipfile.ZipFile(io.BytesIO(daten)) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    innen = _binaer_sichten(z.read(info), "%s!%s"
                                            % (ort, info.filename), tiefe + 1)
                    if innen is None:
                        return None
                    sichten += innen
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError,
                NotImplementedError, EOFError, OSError):
            return None
    return sichten


def pruefen(ordner, muster=None):
    """Durchsucht einen Ordner (ohne .git). -> (harte, weiche) Funde.

    `muster`: die Namensmuster, None = aus persoenlich.txt. Textdateien
    werden je Zeile gemeldet (`datei:zeile`), Binaerdateien je Datei bzw.
    Archiv-Eintrag (`datei!eintrag`).
    """
    if muster is None:
        muster = persoenliche_muster()
    harte, weiche = [], []
    for wurzel, dirs, namen in os.walk(ordner):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in namen:
            p = os.path.join(wurzel, n)
            rel = os.path.relpath(p, ordner)
            try:
                with open(p, "rb") as fh:
                    daten = fh.read()
            except OSError:
                harte.append("%s (nicht lesbar)" % rel)
                continue
            text = None
            if b"\x00" not in daten and daten[:4] != b"PK\x03\x04":
                try:
                    text = daten.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            if text is None:
                sichten = _binaer_sichten(daten, rel)
                if sichten is None:
                    harte.append("%s (Archiv unlesbar)" % rel)
                    continue
                for ort, t in sichten:
                    if HART.search(t) and ort not in harte:
                        harte.append(ort)
                    if any(m.search(t) for m in muster) and ort not in weiche:
                        weiche.append(ort)
                continue
            for nr, zeile in enumerate(text.splitlines(), 1):
                if HART.search(zeile):
                    harte.append("%s:%d" % (rel, nr))
                if any(m.search(zeile) for m in muster):
                    weiche.append("%s:%d" % (rel, nr))
    return harte, weiche


def private_spuren(ordner, spuren=None, ausgenommen=None):
    """Durchsucht einen Ordner (ohne .git) nach Spuren privater Teile.

    -> (funde, ausgenommene_funde), je als "datei:zeile" bzw. "datei" fuer
    Binaerdateien. Ausgenommen ist jede Datei unter einem Pfad aus
    `ausgenommen` (auch unter einem Unterordner wie server/ im Paket).
    None = `private_spuren_liste()` bzw. SPUREN_AUSGENOMMEN, zur Aufrufzeit
    gelesen. Ohne Muster findet sie nichts - wer daraus "sauber" schliesst,
    muss vorher pruefen, dass es Muster gibt (bauen, exportieren tun das).
    """
    spuren = private_spuren_liste() if spuren is None else spuren
    ausgenommen = SPUREN_AUSGENOMMEN if ausgenommen is None else ausgenommen
    funde, aus = [], []
    for wurzel, dirs, namen in os.walk(ordner):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in namen:
            p = os.path.join(wurzel, n)
            rel = os.path.relpath(p, ordner)
            rel_n = "/" + rel.replace(os.sep, "/")
            ziel = aus if any("/" + a in rel_n for a in ausgenommen) else funde
            with open(p, "rb") as fh:
                daten = fh.read()
            text = None
            if b"\x00" not in daten and daten[:4] != b"PK\x03\x04":
                try:
                    text = daten.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            if text is None:
                sichten = _binaer_sichten(daten, rel) or []
                for ort, t in sichten:
                    if any(m.search(t) for m in spuren) and ort not in ziel:
                        ziel.append(ort)
                continue
            for nr, zeile in enumerate(text.splitlines(), 1):
                if any(m.search(zeile) for m in spuren):
                    ziel.append("%s:%d" % (rel, nr))
    return funde, aus


# --- Erweiterungen gehoeren NIE ins Paket (seit 2026-10-01) -------------------
#
# Der Server laedt Werkzeuge aus OPEN_MCP_CAD_ERWEITERUNGEN (open_mcp_cad/
# erweiterungen.py). Was dort eingetragen ist, ist fremder, oft privater
# Code — er darf weder im Verteilpaket noch im Export landen, auch nicht,
# wenn jemand ihn versehentlich ins Repo legt. Geprueft wird ohne ihn zu
# importieren: je Eintrag die Dateien (Ordner, .py-Datei oder das
# Top-Paket eines Modulnamens, gefunden ueber `PathFinder`), dann im Paket
# (auch in ZIPs) gleicher Inhalt (SHA-256, Dateien ab ERW_MIN_BYTES), der
# Name des Top-Pakets als Wort und ein Eintrag, der im Repo selbst liegt.

ERW_UMGEBUNG = "OPEN_MCP_CAD_ERWEITERUNGEN"
ERW_MIN_BYTES = 64


def _erw_hash(daten):
    """SHA-256 ohne Unterschied CRLF/LF (Git kann Zeilenenden umschreiben)."""
    return hashlib.sha256(daten.replace(b"\r\n", b"\n")).hexdigest()


def erweiterung_quellen(eintraege=None):
    """-> [(Top-Name, [Dateien])] je Eintrag (Ordner/Datei/Modulname).
    `eintraege`: Liste; None = aus der Umgebung. Importiert nichts."""
    import importlib.machinery
    if eintraege is None:
        eintraege = [e.strip().strip('"').strip() for e in os.environ.get(
            ERW_UMGEBUNG, "").split(";") if e.strip().strip('"').strip()]
    aus = []
    for e in eintraege:
        pfad = None
        if os.sep in e or "/" in e or e.endswith(".py") or os.path.isdir(e):
            pfad = os.path.abspath(e)
            name = os.path.splitext(os.path.basename(pfad.rstrip("\\/")))[0]
        else:
            name = e.split(".")[0]
            spec = importlib.machinery.PathFinder.find_spec(name)
            if spec is not None:
                orte = list(spec.submodule_search_locations or [])
                pfad = orte[0] if orte else spec.origin
        dateien = []
        if pfad and os.path.isdir(pfad):
            for wurzel, dirs, namen in os.walk(pfad):
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
                dateien += [os.path.join(wurzel, n) for n in namen]
        elif pfad and os.path.isfile(pfad):
            dateien.append(pfad)
        aus.append((name, pfad, dateien))
    return aus


def erweiterungen_im_paket(ordner, eintraege=None):
    """-> Funde (leer = gut): Inhalte, Namen oder Orte einer Erweiterung im
    Paket-/Exportordner `ordner`."""
    quellen = erweiterung_quellen(eintraege)
    if not quellen:
        return []
    funde, hashes, namen = [], {}, []
    repo = os.path.normcase(os.path.abspath(REPO))
    for name, pfad, dateien in quellen:
        if pfad and os.path.normcase(os.path.abspath(pfad)).startswith(
                repo + os.sep):
            funde.append("Erweiterung %s liegt im Repo: %s" % (name, pfad))
        if len(name) >= 4 and name != "open_mcp_cad":
            namen.append(re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])"
                                    % re.escape(name)))
        for d in dateien:
            try:
                with open(d, "rb") as fh:
                    daten = fh.read()
            except OSError:
                continue
            if len(daten) >= ERW_MIN_BYTES:
                hashes[_erw_hash(daten)] = d
    for wurzel, dirs, dateinamen in os.walk(ordner):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in dateinamen:
            p = os.path.join(wurzel, n)
            rel = os.path.relpath(p, ordner)
            with open(p, "rb") as fh:
                daten = fh.read()
            stuecke = [(rel, daten)]
            if daten[:4] == b"PK\x03\x04":
                try:
                    with zipfile.ZipFile(io.BytesIO(daten)) as z:
                        stuecke += [("%s!%s" % (rel, i), z.read(i))
                                    for i in z.namelist()]
                except (zipfile.BadZipFile, OSError):
                    pass
            for ort, inhalt in stuecke:
                if _erw_hash(inhalt) in hashes:
                    funde.append("%s = %s" % (ort, hashes[_erw_hash(inhalt)]))
                text = inhalt.decode("utf-8", "replace")
                if any(m.search(text) or m.search(ort) for m in namen):
                    funde.append("%s nennt eine Erweiterung" % ort)
    return funde


def bauen(ziel_basis=None, oeffentlich=False, muster=None, edge=None,
          spuren=None):
    """Baut Ordner und ZIP. -> (Ordner, ZIP, weiche Funde, Warnungen).

    `edge`: Pfad auf msedge.exe, None = suchen, False = nicht drucken (die
    Anleitung liegt dann als HTML oben; die Gates sparen so Zeit bei
    Bauten, in denen es um anderes geht). `muster`/`spuren`: Namens- bzw.
    Spuren-Muster, None = aus persoenlich.txt bzw. privat_spuren.txt."""
    if muster is None:
        muster = persoenliche_muster()
    if spuren is None:
        spuren = private_spuren_liste()
    if oeffentlich and not muster:
        raise PaketFehler("--oeffentlich braucht Namensmuster in %s — ohne "
                          "sie prueft es nichts" % PERSOENLICH)
    if oeffentlich and not spuren:
        raise PaketFehler("--oeffentlich braucht Spuren-Muster in %s — ohne "
                          "sie prueft es nichts" % PRIVAT_SPUREN)
    ziel_basis = os.path.abspath(ziel_basis or os.path.join(REPO, "dist"))
    name = "Open-MCP-CAD-%s" % version()
    ordner = os.path.join(ziel_basis, name)
    archiv = ordner + ".zip"
    fehlt = [q for q, _z in paket_dateien() if not os.path.isfile(q)]
    if fehlt:
        raise PaketFehler("Quelle fehlt: %s" % ", ".join(fehlt))
    falsch = installieren_pruefen()
    if falsch:
        raise PaketFehler(falsch)
    ki_hinweis = ki_hinweis_text()      # vor dem Loeschen: bricht sonst ab

    # Nur den eigenen Ausgabeordner neu anlegen, nie etwas anderes. Ist
    # darin etwas offen (ein PDF im Betrachter, das ZIP im Explorer), bricht
    # es mit einem Satz ab statt mit einem Traceback (Gegenpruefung
    # 2026-09-29).
    try:
        if os.path.isdir(ordner):
            shutil.rmtree(ordner)
        if os.path.isfile(archiv):
            os.remove(archiv)
    except OSError as exc:
        raise PaketFehler("die alte Ausgabe laesst sich nicht entfernen - "
                          "ist eine Datei daraus noch offen (PDF-Betrachter, "
                          "Explorer)? %s" % exc)
    for quelle, rel in paket_dateien():
        ziel = os.path.join(ordner, rel)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        if rel.endswith(".cmd"):
            # cmd.exe will CRLF; das Repo haelt alles in LF.
            with open(quelle, "rb") as fh:
                inhalt = fh.read().replace(b"\r\n", b"\n")
            with open(ziel, "wb") as fh:
                fh.write(inhalt.replace(b"\n", b"\r\n"))
        else:
            shutil.copyfile(quelle, ziel)
    with io.open(os.path.join(ordner, UNTERORDNER, KI_HINWEIS), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(ki_hinweis)
    gedruckt, warnungen = schnellstart_bauen(
        ordner, edge=edge if edge is not None else edge_finden() or False)
    abweichung = oben_abweichung(ordner)
    if abweichung:
        raise PaketFehler("oben im Paket: %s" % ", ".join(abweichung))

    # Immer, nicht nur bei --oeffentlich: auch ein Paket fuer Kollegen traegt
    # keine Erweiterung (seit 2026-10-01).
    erw = erweiterungen_im_paket(ordner)
    if erw:
        raise PaketFehler("Erweiterung (OPEN_MCP_CAD_ERWEITERUNGEN) im "
                          "Paket: %s" % ", ".join(erw[:10]))
    lokal = lokale_dateien_in(ordner)
    if lokal:
        raise PaketFehler("lokale Musterdatei im Paket (nie weitergeben): %s"
                          % ", ".join(lokal[:10]))
    harte, weiche = pruefen(ordner, muster)
    if harte:
        raise PaketFehler("lokaler Benutzerpfad im Paket (auf jedem anderen "
                          "Rechner falsch): %s" % ", ".join(harte[:10]))
    if oeffentlich and weiche:
        raise PaketFehler("%d Stellen mit Persoenlichem, fuer eine "
                          "Veroeffentlichung zu entfernen: %s"
                          % (len(weiche), ", ".join(weiche[:10])))
    if oeffentlich:
        funde, _aus = private_spuren(ordner, spuren)
        if funde:
            raise PaketFehler("%d Spuren privater Teile (privat_spuren.txt), "
                              "fuer eine Veroeffentlichung zu entfernen: %s"
                              % (len(funde), ", ".join(funde[:10])))
    if oeffentlich and warnungen:
        # Zuletzt, damit die Pruefungen oben ihren eigenen Grund nennen. Ein
        # Release ohne PDF waere genau das, was die Rueckmeldung 2026-09-29
        # bemaengelte.
        raise PaketFehler("Anleitung nicht als PDF gedruckt (%s) — ohne "
                          "PDF keine Veroeffentlichung" % "; ".join(warnungen))

    with zipfile.ZipFile(archiv, "w", zipfile.ZIP_DEFLATED) as z:
        for wurzel, _d, namen in os.walk(ordner):
            for n in sorted(namen):
                p = os.path.join(wurzel, n)
                z.write(p, os.path.join(name, os.path.relpath(p, ordner)))
    return ordner, archiv, weiche, warnungen


def main():
    oeffentlich = "--oeffentlich" in sys.argv
    ziel = None
    if "--ziel" in sys.argv:
        ziel = sys.argv[sys.argv.index("--ziel") + 1]
    try:
        ordner, archiv, weiche, warnungen = bauen(ziel, oeffentlich)
    except PaketFehler as exc:
        print("ABBRUCH: %s" % exc)
        return 1
    n = sum(len(f) for _w, _d, f in os.walk(ordner))
    print("Paket:  %s  (%d Dateien)" % (ordner, n))
    print("ZIP:    %s  (%.0f KB)" % (archiv, os.path.getsize(archiv) / 1024))
    print("Oben:   %s" % ", ".join(oben_soll(ordner)))
    for w in warnungen:
        print("WARNUNG: %s — die Anleitung liegt oben als HTML. Microsoft "
              "Edge installieren und neu bauen." % w)
    if weiche:
        print("Hinweis: %d Stellen treffen persoenlich.txt — fuer Kollegen "
              "ok, vor einer Veroeffentlichung entfernen (--oeffentlich "
              "prueft es): %s" % (len(weiche), ", ".join(weiche[:5])))
    spuren_melden(ordner)
    return 0


def spuren_melden(ordner):
    """Nennt Spuren privater Teile, auch die ausgenommenen (erzeugten)."""
    if not private_spuren_liste():
        print("Hinweis: keine Muster in %s - Spuren privater Teile NICHT "
              "geprueft (--oeffentlich und der Export brechen so ab)."
              % PRIVAT_SPUREN)
        return
    spuren, aus = private_spuren(ordner)
    if spuren:
        print("Hinweis: %d Spuren privater Teile (privat_spuren.txt; "
              "--oeffentlich bricht daran ab): %s"
              % (len(spuren), ", ".join(spuren[:5])))
    if aus:
        print("Ausgenommen (%s, erzeugt, im privaten Repo zu bereinigen): "
              "%d Stellen: %s" % (", ".join(SPUREN_AUSGENOMMEN), len(aus),
                                  ", ".join(aus[:5])))
        print("  Eintraege dahinter (im privaten Repo umstufen): %s"
              % ", ".join(wissen_eintraege(ordner, aus)))


if __name__ == "__main__":
    sys.exit(main())
