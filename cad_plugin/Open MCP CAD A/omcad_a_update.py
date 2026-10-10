# -*- coding: utf-8 -*-
"""Open MCP CAD — nach Updates sehen, ein Update laden, einrichten (ohne Qt).

Seit 2026-10-10 (Auftrag des Maintainers). Was es tut:

- `nachsehen`: EIN `GET` an die GitHub-API (`API_URL`, die Seite
  "releases/latest" des oeffentlichen Repos), kurzer Timeout, neutraler
  User-Agent, ohne irgendeine Angabe ueber den Nutzer, sein Modell oder
  seinen Rechner (GitHub sieht, wie bei jedem Abruf, die IP-Adresse). Die
  Antwort ist fremde Eingabe: Version nur aus Ziffern und Punkten, Asset nur
  mit festem Namen (`ASSET_NAME`) und einer Adresse unter
  `DOWNLOAD_PRAEFIX`. Das Dashboard ruft es hoechstens einmal je
  `TAKT_S` (24 h), nie waehrend eines Auftrags, im Nebenthread; abschaltbar
  (chat.json `updates_suchen`).
- `laden`: das Asset in einen Temp-Ordner, mit Fortschritt; Groesse gegen
  die API, SHA-256 gegen ihren `digest` (falls da); die ZIP muss
  `1_INSTALLIEREN.cmd` und `Programmdateien/install.ps1` tragen (`pruefen`);
  `entpacken` nach `%LOCALAPPDATA%\\OpenMcpCad\\updates\\<version>\\`
  (`update_wurzel`, ohne Pfade ausserhalb).
- `einrichten`: startet `1_INSTALLIEREN.cmd` aus dem entpackten Paket wie
  ein Doppelklick (`STARTEN`, ersetzbar — die Gates starten nie etwas). Das
  Einrichtungsfenster waehlt selbst alle Profile vor, die es braucht. Nie
  still, nie ohne Klick.
- `fehlende_profile`: Cadwork-Profile eines erlaubten Jahres
  (ab `CADWORK_ERLAUBT_AB`, derselbe Wert wie in install.ps1 — test_a_prototyp
  P24 liest ihn dort), in denen Cadwork installiert ist und Open MCP CAD fehlt.

Wie im Lokal-Modul: KEIN fester Name in `sys.modules` — laedt mit jedem
Dashboard frisch, ein Update dieses Moduls braucht keinen Neustart.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

SCHNITTSTELLE = 1

#: Die installierte Version — dieselbe wie `open_mcp_cad.__version__`
#: (test_paket T21 vergleicht beide, `paket_bauen` bricht sonst ab). Beim
#: Release mit `pyproject.toml` und `__init__.py` heben.
VERSION = "0.2.2"

#: Die Seite der GitHub-API mit dem neuesten Release (kein Pre-release).
API_URL = ("https://api.github.com/repos/sebastiankoukoui/open-mcp-cad/"
           "releases/latest")
#: Unter dieser Adresse muessen die Assets liegen (GitHub leitet von dort auf
#: seinen Speicher um).
DOWNLOAD_PRAEFIX = ("https://github.com/sebastiankoukoui/open-mcp-cad/"
                    "releases/download/")
#: Nur fuer Gates: eine andere Basis (lokaler HTTP-Dienst). Dann gilt der
#: Ursprung (Schema + Rechner + Port) dieser Adresse auch fuer die Assets.
UMGEBUNG_URL = "OPEN_MCP_CAD_UPDATE_URL"
#: Wohin entpackt wird (Vorgabe %LOCALAPPDATA%\OpenMcpCad\updates).
UMGEBUNG_ORDNER = "OPEN_MCP_CAD_UPDATES"
#: Das Asset des Releases (fester Name, CLAUDE.md "Release" Schritt 4).
ASSET_NAME = "Open-MCP-CAD.zip"
#: Hoechstens so oft von selbst nachsehen.
TAKT_S = 24 * 3600.0
#: Nach einem Fehlschlag (kein Netz) frueheste neue Frage.
WIEDER_S = 3600.0
TIMEOUT_S = 5.0
LADEN_TIMEOUT_S = 30.0
USER_AGENT = "Open-MCP-CAD-Update"
#: Groesser ist kein Paket von uns (heute ~6 MB).
MAX_BYTES = 200 * 1024 * 1024
MAX_API_BYTES = 1024 * 1024
#: Was die ZIP tragen muss (relativ zu ihrem obersten Ordner).
PFLICHT = ("1_INSTALLIEREN.cmd", "Programmdateien/install.ps1")
#: Das erste Jahr, fuer das das Plugin installiert wird — wie
#: `$CADWORK_ERLAUBT_AB` in install.ps1.
CADWORK_ERLAUBT_AB = 2025
CADWORK_WURZEL = r"C:\Users\Public\Documents\cadwork"
CADWORK_PROGRAMM = r"C:\Program Files\cadwork.dir"
PLUGIN_NAME = "Open MCP CAD"


class UpdateFehler(Exception):
    """Ein Update liess sich nicht laden oder pruefen (Text fuer Laien)."""


def _starten(pfad):
    os.startfile(pfad)                              # noqa: S606


#: Startet eine Datei wie ein Doppelklick. Ersetzbar (Gates).
STARTEN = _starten


# --- Versionen (rein) ------------------------------------------------------

_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


def version_tupel(text):
    """"v0.3.1" / "0.3.1" -> (0, 3, 1); alles andere (auch "0.3.1-rc1",
    Buchstaben, Pfade) -> None."""
    m = _VERSION.match(str(text or "").strip())
    if not m:
        return None
    return tuple(int(t) for t in m.groups())


def neuer(kandidat, installiert=VERSION):
    """Ist `kandidat` neuer als `installiert`? Unlesbares ist nie neuer."""
    a, b = version_tupel(kandidat), version_tupel(installiert)
    return a is not None and b is not None and a > b


def faellig(zuletzt, jetzt, an=True, takt=TAKT_S):
    """Ist es Zeit, von selbst nachzusehen? Abgeschaltet nie; noch nie
    nachgesehen sofort; sonst nach `takt`. Eine Zeit in der Zukunft (Uhr
    verstellt) zaehlt als "noch nie"."""
    if not an:
        return False
    try:
        zuletzt = float(zuletzt)
    except (TypeError, ValueError):
        return True
    if zuletzt > jetzt + 60:
        return True
    return jetzt - zuletzt >= takt


def api_url():
    return os.environ.get(UMGEBUNG_URL) or API_URL


def _erlaubter_ursprung(url, basis):
    """Darf von `url` geladen werden? Standard: nur unter
    DOWNLOAD_PRAEFIX. Mit umgelenkter Basis (Gates): derselbe Ursprung."""
    url = str(url or "")
    if basis == API_URL:
        return url.startswith(DOWNLOAD_PRAEFIX)
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(basis)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc) and \
        a.scheme in ("http", "https")


def antwort_lesen(daten, basis=None, installiert=VERSION):
    """Die Antwort der API (bytes oder dict) -> {"ok", "version", "neuer",
    "asset" ({name, url, groesse, digest} oder None), "grund"} — rein (P24).
    Fremde Eingabe: nur bekannte Felder, Version nur Ziffern/Punkte."""
    basis = basis or api_url()
    try:
        if isinstance(daten, (bytes, bytearray)):
            daten = json.loads(bytes(daten).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {"ok": False, "grund": "Antwort unlesbar"}
    if not isinstance(daten, dict):
        return {"ok": False, "grund": "Antwort unlesbar"}
    tag = daten.get("tag_name")
    t = version_tupel(tag)
    if t is None or daten.get("draft") or daten.get("prerelease"):
        return {"ok": False, "grund": "keine gültige Version"}
    version = "%d.%d.%d" % t
    asset = None
    for a in daten.get("assets") or ():
        if not isinstance(a, dict) or a.get("name") != ASSET_NAME:
            continue
        url = a.get("browser_download_url")
        groesse = a.get("size")
        if not isinstance(groesse, int) or groesse <= 0 \
                or groesse > MAX_BYTES or not _erlaubter_ursprung(url, basis):
            continue
        digest = a.get("digest")
        sha = None
        if isinstance(digest, str) and digest.lower().startswith("sha256:"):
            roh = digest.split(":", 1)[1].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", roh):
                sha = roh
        asset = {"name": ASSET_NAME, "url": url, "groesse": groesse,
                 "sha256": sha}
        break
    return {"ok": True, "version": version,
            "neuer": neuer(version, installiert), "asset": asset,
            "grund": None if asset else "kein Paket im Release"}


def _oeffnen(url, timeout):
    # Nur der User-Agent (GitHub verlangt einen) und was erwartet wird —
    # keine Angabe ueber Nutzer, Rechner oder Modell.
    api = not str(url).endswith(".zip")
    anfrage = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json" if api else "*/*"})
    return urllib.request.urlopen(anfrage, timeout=timeout)   # noqa: S310


#: Oeffnet eine Adresse (ersetzbar fuer Gates, die einen Stolperdraht
#: legen). -> eine Antwort mit read().
OEFFNEN = _oeffnen


def nachsehen(installiert=VERSION, timeout=TIMEOUT_S):
    """EIN Aufruf der API. Wirft nie: ohne Netz {"ok": False, "grund"}."""
    basis = api_url()
    try:
        with OEFFNEN(basis, timeout) as antwort:
            daten = antwort.read(MAX_API_BYTES + 1)
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "grund": "keine Verbindung (%s)"
                % type(exc).__name__}
    if len(daten) > MAX_API_BYTES:
        return {"ok": False, "grund": "Antwort zu gross"}
    return antwort_lesen(daten, basis, installiert)


# --- Laden, pruefen, entpacken ---------------------------------------------

def laden(asset, fortschritt=None, abbrechen=None, timeout=LADEN_TIMEOUT_S):
    """Das Asset in eine Temp-Datei. Prueft Groesse und (falls die API sie
    nennt) SHA-256. `fortschritt(geladen, gesamt)`; `abbrechen()` -> True
    bricht ab. -> Pfad der ZIP; wirft UpdateFehler (die Temp-Datei ist dann
    weg)."""
    basis = api_url()
    if not isinstance(asset, dict) or not _erlaubter_ursprung(
            asset.get("url"), basis):
        raise UpdateFehler("Die Adresse des Pakets ist nicht die erwartete.")
    gesamt = int(asset.get("groesse") or 0)
    fd, pfad = tempfile.mkstemp(prefix="open-mcp-cad-", suffix=".zip")
    sha = hashlib.sha256()
    geladen = 0
    try:
        with os.fdopen(fd, "wb") as aus:
            try:
                antwort = OEFFNEN(asset["url"], timeout)
            except Exception as exc:                  # noqa: BLE001
                raise UpdateFehler("Keine Verbindung zu GitHub (%s)."
                                   % type(exc).__name__)
            with antwort:
                while True:
                    if abbrechen is not None and abbrechen():
                        raise UpdateFehler("Abgebrochen.")
                    stueck = antwort.read(64 * 1024)
                    if not stueck:
                        break
                    geladen += len(stueck)
                    if geladen > min(MAX_BYTES, gesamt or MAX_BYTES):
                        raise UpdateFehler("Das Paket ist grösser als "
                                           "angekündigt.")
                    sha.update(stueck)
                    aus.write(stueck)
                    if fortschritt is not None:
                        fortschritt(geladen, gesamt)
        if gesamt and geladen != gesamt:
            raise UpdateFehler("Das Paket kam nicht vollständig an (%d von "
                               "%d Bytes)." % (geladen, gesamt))
        if asset.get("sha256") and sha.hexdigest() != asset["sha256"]:
            raise UpdateFehler("Die Prüfsumme des Pakets stimmt nicht — es "
                               "wird nicht verwendet.")
        pruefen(pfad)
        return pfad
    except BaseException:
        try:
            os.remove(pfad)
        except OSError:
            pass
        raise


def _oberster(namen):
    """Der gemeinsame oberste Ordner aller Eintraege ("" ohne)."""
    teile = {n.split("/", 1)[0] for n in namen if "/" in n}
    lose = [n for n in namen if "/" not in n]
    if len(teile) == 1 and not lose:
        return teile.pop() + "/"
    return ""


def pruefen(pfad):
    """Ist das eine ZIP von uns? Kein Eintrag ausserhalb (absolut, "..",
    Laufwerk), die Pflichtdateien da. -> der oberste Ordner in der ZIP;
    wirft UpdateFehler."""
    try:
        with zipfile.ZipFile(pfad) as zf:
            namen = [i.filename.replace("\\", "/") for i in zf.infolist()]
            summe = sum(i.file_size for i in zf.infolist())
    except (zipfile.BadZipFile, OSError, ValueError):
        raise UpdateFehler("Das Paket ist keine lesbare ZIP-Datei.")
    if summe > 4 * MAX_BYTES:
        raise UpdateFehler("Das Paket ist entpackt zu gross.")
    for n in namen:
        teile = n.split("/")
        if n.startswith("/") or ":" in teile[0] or ".." in teile:
            raise UpdateFehler("Das Paket enthält einen Pfad ausserhalb "
                               "seines Ordners.")
    oben = _oberster(namen)
    fehlt = [p for p in PFLICHT if oben + p not in namen]
    if fehlt:
        raise UpdateFehler("Das Paket ist nicht vollständig (es fehlt %s)."
                           % ", ".join(fehlt))
    return oben


def update_wurzel():
    """%LOCALAPPDATA%\\OpenMcpCad\\updates (umlenkbar fuer die Gates)."""
    ziel = os.environ.get(UMGEBUNG_ORDNER)
    if ziel:
        return ziel
    basis = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(basis, "OpenMcpCad", "updates")


def entpacken(zip_pfad, version):
    """Nach `update_wurzel()/<version>/` entpacken (ein alter Ordner dieser
    Version wird vorher geleert). -> der Ordner mit `1_INSTALLIEREN.cmd`."""
    t = version_tupel(version)
    if t is None:
        raise UpdateFehler("Unbekannte Version.")
    oben = pruefen(zip_pfad)
    wurzel = os.path.abspath(update_wurzel())
    ziel = os.path.join(wurzel, "%d.%d.%d" % t)
    try:
        if os.path.isdir(ziel):
            shutil.rmtree(ziel)
        os.makedirs(ziel, exist_ok=True)
        with zipfile.ZipFile(zip_pfad) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name.startswith(oben):
                    continue
                rel = name[len(oben):]
                if not rel:
                    continue
                aus = os.path.abspath(os.path.join(ziel, *rel.split("/")))
                if not (aus + os.sep).startswith(os.path.abspath(ziel)
                                                 + os.sep):
                    raise UpdateFehler("Das Paket enthält einen Pfad "
                                       "ausserhalb seines Ordners.")
                if name.endswith("/"):
                    os.makedirs(aus, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(aus), exist_ok=True)
                with zf.open(info) as quelle, open(aus, "wb") as senke:
                    shutil.copyfileobj(quelle, senke)
    except OSError as exc:
        raise UpdateFehler("Entpacken ging nicht: %s" % exc)
    cmd = os.path.join(ziel, PFLICHT[0])
    if not os.path.isfile(cmd):
        raise UpdateFehler("Das Paket ist nicht vollständig.")
    return ziel


def einrichten(ordner):
    """Das Einrichtungsfenster aus dem entpackten Paket starten — wie ein
    Doppelklick auf `1_INSTALLIEREN.cmd` (ueber `STARTEN`). -> der Pfad."""
    cmd = os.path.join(ordner, PFLICHT[0])
    if not os.path.isfile(cmd):
        raise UpdateFehler("Das Paket ist nicht vollständig.")
    STARTEN(cmd)
    return cmd


# --- Weitere Cadwork-Versionen ---------------------------------------------

_PROFIL = re.compile(r"^userprofil_(\d{4})$", re.IGNORECASE)


#: Nur fuer Gates und Bilder: andere Orte fuer Profile und Programm.
UMGEBUNG_WURZEL = "OPEN_MCP_CAD_CADWORK_WURZEL"
UMGEBUNG_PROGRAMM = "OPEN_MCP_CAD_CADWORK_PROGRAMM"


def fehlende_profile(wurzel=None, programm=None, hier=None,
                     erlaubt_ab=CADWORK_ERLAUBT_AB):
    """Cadwork-Profile (`userprofil_<Jahr>`, auch GROSS geschrieben) eines
    erlaubten Jahres, in denen Cadwork installiert ist (`EXE_<Jahr>` unter
    `programm`, wie install.ps1) und Open MCP CAD fehlt. `hier`: der
    Plugin-Ordner, aus dem dieses Dock laeuft (sein Profil zaehlt nie).
    Billig: nur Ordner auflisten. Wirft nie. -> [{"jahr", "profil",
    "api"}] nach Jahr."""
    wurzel = wurzel or os.environ.get(UMGEBUNG_WURZEL) or CADWORK_WURZEL
    programm = programm or os.environ.get(UMGEBUNG_PROGRAMM)         or CADWORK_PROGRAMM
    erg = []
    try:
        namen = os.listdir(wurzel)
    except OSError:
        return erg
    eigen = os.path.normcase(os.path.abspath(os.path.dirname(hier))) \
        if hier else None
    for name in sorted(namen):
        m = _PROFIL.match(name)
        if not m:
            continue
        jahr = int(m.group(1))
        if jahr < erlaubt_ab:
            continue
        api = os.path.join(wurzel, name, "3d", "API.x64")
        try:
            if not os.path.isdir(api) or not os.path.isdir(
                    os.path.join(programm, "EXE_%d" % jahr)):
                continue
            if eigen and os.path.normcase(os.path.abspath(api)) == eigen:
                continue
            if os.path.isdir(os.path.join(api, PLUGIN_NAME)):
                continue
        except OSError:
            continue
        erg.append({"jahr": jahr, "profil": name, "api": api})
    erg.sort(key=lambda e: e["jahr"])
    return erg


def jetzt():
    return time.time()
