#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer den Installer (verteilung/install.ps1): Profilwahl, Cadwork-
Version, Schlussmeldung.

    python tests/test_installer.py        (-v zeigt jede Zeile)

Rueckmeldung Kollege zu 0.1.0 (2026-09-26):
  * die Profile wurden als TEXT absteigend sortiert - userprofil_30 kam vor
    userprofil_2025, das Plugin landete im falschen Profil;
  * Cadwork 2025 (Python 3.12, PyQt5) wurde nicht erkannt, das Plugin
    startete dort nicht (seit 2026-10-10 laeuft es ueber eine Qt-Schicht
    auch mit PyQt5 und ist seit der Messung des Maintainers dort getestet:
    2025 wird ohne Hinweis kopiert, aelter als $CADWORK_ERLAUBT_AB warnt;
    die Jahre liest das Gate aus install.ps1);
  * am Ende stand "erfolgreich", obwohl nur der Server geprueft war.

Gemessen wird mit Windows PowerShell 5.1 (`powershell.exe`, wie
install.cmd) gegen ATTRAPPEN in Temp: Profilordner `userprofil_*` mit
`3d\\API.x64` und Programmordner `EXE_<Jahr>`. Die Funktionen laedt
`. install.ps1 -NurFunktionen`; der ganze Installer laeuft mit
-OhneServer -OhnePause und -CadworkWurzel/-CadworkProgramm in Temp - er
fasst also weder das echte Cadwork-Profil noch pip, venv oder
Umgebungsvariablen an. Den Server-Teil (pip, Internet) prueft dieses Gate
NICHT. Den Rueckfall ohne winget (Python von python.org) misst I20 gegen
Attrappen fuer Laden und Start - es wird nie etwas heruntergeladen oder
installiert; die Signaturpruefung laeuft echt an Dateien dieses Rechners.

Das Einrichtungsfenster (install_fenster.ps1, seit 2026-10-09) messen
I21-I27, OHNE ein Fenster zu zeigen: XAML laden, Knoepfe per Click-Ereignis,
Ereignisschleife ohne Fenster, Seiten per RenderTargetBitmap; jeder
Kindprozess ohne Konsole. `--nur-fenster` laeuft nur diese Zellen (dazu
I28-I30: Chat in Cadwork mit -ChatKi und Anmelden gegen ein falsches
claude.exe, Unterzeile, "Text kopieren"). I39/I40 (seit 2026-10-10):
mehrere Cadwork-Versionen auf einem PC - Haken je Profil, Vorauswahl,
install.ps1 -Profile "a;b".
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
INSTALL = os.path.join(REPO, "verteilung", "install.ps1")
sys.path.insert(0, os.path.join(REPO, "scripts"))
import paket_bauen as P                                     # noqa: E402
FENSTER = os.path.join(P.VERTEILUNG, P.FENSTER)
FENSTER_XAML = os.path.join(P.VERTEILUNG, P.FENSTER_XAML)
FENSTER_TEXTE = os.path.join(P.VERTEILUNG, P.FENSTER_TEXTE)
#: Das Store-Paket der ChatGPT-Desktop-App mit Codex (frueher "Codex-App"),
#: gemessen 2026-10-09 am Rechner des Maintainers: Get-AppxPackage ->
#: PackageFamilyName, Get-StartApps -> Name "ChatGPT", Version 26.1002.7124.0.
CHATGPT_PAKET = "OpenAI.Codex_2p2nqsd0c76g0"
#: Kein Fenster, keine Konsole fuer Kindprozesse der neuen Zellen (das
#: Gate oeffnet NIE ein sichtbares Fenster).
OHNE_FENSTER = 0x08000000
START_LOG = r"C:\Users\Public\OpenMcpCad_start.log"

_ergebnisse = []
_temp = []


def pruefe(titel, bedingung, detail=""):
    _ergebnisse.append(bool(bedingung))
    if "-v" in sys.argv or not bedingung:
        print("  [%s] %s%s" % ("ok  " if bedingung else "FEHL", titel,
                               ("  — %s" % (detail,)) if detail else ""))
    return bool(bedingung)


def _powershell():
    """Windows PowerShell 5.1 - dieselbe, die install.cmd startet."""
    fest = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                        "System32", "WindowsPowerShell", "v1.0",
                        "powershell.exe")
    return fest if os.path.isfile(fest) else shutil.which("powershell")


PS = _powershell()


def _lauf(argumente, zeit=180):
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass"] + argumente,
                       capture_output=True, timeout=zeit)
    aus = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    return r.returncode, aus


def ps_funktionen(code, ps1=None):
    """Laedt nur die Funktionen des Installers (oder einer Mutante `ps1`)
    und fuehrt `code` aus. -> das JSON, das `code` als letzte Zeile
    schreibt."""
    skript = ". '%s' -NurFunktionen\n%s" % (ps1 or INSTALL, code)
    rc, aus = _lauf(["-Command", skript])
    zeilen = [z for z in aus.splitlines() if z.strip()]
    try:
        return json.loads(zeilen[-1])
    except Exception:                                     # noqa: BLE001
        return {"_fehler": aus[-800:], "_rc": rc}


def attrappe(profile=(), exes=(), ohne_api=()):
    """Temp-Ordner mit cadwork\\userprofil_* und cadwork.dir\\EXE_*."""
    t = tempfile.mkdtemp(prefix="omcad_inst_")
    _temp.append(t)
    wurzel = os.path.join(t, "cadwork")
    programm = os.path.join(t, "cadwork.dir")
    os.makedirs(wurzel)
    os.makedirs(programm)
    for p in profile:
        os.makedirs(os.path.join(wurzel, p, "3d", "API.x64"))
    for p in ohne_api:
        os.makedirs(os.path.join(wurzel, p))
    for e in exes:
        os.makedirs(os.path.join(programm, "EXE_%s" % e))
    return t, wurzel, programm


def wahl(wurzel, programm, ps1=None):
    return ps_funktionen(
        "$k = @(Profil-Kandidaten '%s' '%s')\n"
        "$v = Profil-Vorgabe $k '%s'\n"
        "@{ namen = @($k | ForEach-Object { $_.Name }); "
        "vorgabe = $k[$v.Index].Name; pfad = $k[$v.Index].Pfad; "
        "grund = $v.Grund } | ConvertTo-Json -Compress"
        % (wurzel, programm, programm), ps1)


def mutante_ohne_jahr_vorrang():
    """install.ps1 ohne den Vorrang fuer $CADWORK_JAHR (Stand 60be238)."""
    quelle = open(INSTALL, encoding="ascii").read()
    a = quelle.index("# VORGABE-JAHR-ANFANG")
    e = quelle.index("# VORGABE-JAHR-ENDE")
    t = tempfile.mkdtemp(prefix="omcad_mut_")
    _temp.append(t)
    ziel = os.path.join(t, "install.ps1")
    with open(ziel, "w", encoding="ascii") as fh:
        fh.write(quelle[:a] + quelle[e:])
    return ziel


def paket_attrappe(cmd_quelle=None, pdf=True, name=None, ps1=None,
                   fenster=None):
    """Ein Paketordner wie dist/, im Aufbau aus paket_bauen (Regel 3):
    oben der Doppelklick, darunter UNTERORDNER mit install.ps1 und
    'Open MCP CAD/marke.txt'. `name`: der Paketordner heisst so (etwa
    mit Leerzeichen, Umlaut, & und Klammern). `fenster`: das
    Einrichtungsfenster daneben (True = das echte samt XAML, ein Pfad =
    diese Datei als install_fenster.ps1; None = keins, wie die Paket-
    Attrappe vor 2026-10-09). -> Pfad auf install.ps1."""
    t = tempfile.mkdtemp(prefix="omcad_paket_")
    _temp.append(t)
    if name:
        t = os.path.join(t, name)
        os.makedirs(t)
    unter = os.path.join(t, P.UNTERORDNER)
    os.makedirs(os.path.join(unter, "Open MCP CAD"))
    shutil.copy(ps1 or INSTALL, os.path.join(unter, "install.ps1"))
    if fenster is True:
        shutil.copy(FENSTER, os.path.join(unter, P.FENSTER))
        shutil.copy(FENSTER_XAML, os.path.join(unter, P.FENSTER_XAML))
        shutil.copy(FENSTER_TEXTE, os.path.join(unter, P.FENSTER_TEXTE))
    elif fenster:
        shutil.copy(fenster, os.path.join(unter, P.FENSTER))
    # Wie paket_bauen: der Doppelklick mit CRLF.
    with open(cmd_quelle or os.path.join(P.VERTEILUNG, P.INSTALLIEREN),
              "rb") as fh:
        roh = fh.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(os.path.join(t, P.INSTALLIEREN), "wb") as fh:
        fh.write(roh)
    with open(os.path.join(unter, "Open MCP CAD", "marke.txt"), "w") as fh:
        fh.write("Attrappe\n")
    if pdf:
        # Die Anleitung oben, unter dem Namen aus paket_bauen.
        with open(os.path.join(t, P.ANLEITUNG_OBEN[0][1] + ".pdf"),
                  "wb") as fh:
            fh.write(PDF_ATTRAPPE)
    return os.path.join(unter, "install.ps1")


PDF_ATTRAPPE = b"%PDF-1.4 Attrappe\n%%EOF\n"


def anleitung_im_plugin(wurzel, profil):
    """Der Inhalt der Anleitung neben dem kopierten Plugin, unter dem Namen,
    den das Dashboard sucht (ANLEITUNG_DATEI, aus dem Quelltext)."""
    import re
    dash = open(os.path.join(REPO, "cad_plugin", "Open MCP CAD",
                             "omcad_a_dashboard.py"), encoding="utf-8").read()
    name = re.search(r'(?m)^ANLEITUNG_DATEI = "([^"]+)"', dash).group(1)
    pfad = os.path.join(wurzel, profil, "3d", "API.x64", "Open MCP CAD", name)
    try:
        with open(pfad, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def installer(wurzel, programm, *extra):
    ps1 = paket_attrappe()
    # Nie ohne Attrappen: ohne -CadworkWurzel ginge es ins echte Profil.
    assert wurzel.startswith(tempfile.gettempdir())
    assert programm.startswith(tempfile.gettempdir())
    return _lauf(["-File", ps1, "-OhnePause", "-OhneServer",
                  "-CadworkWurzel", wurzel, "-CadworkProgramm", programm]
                 + list(extra))


def doppelklick(wurzel, programm, cmd_quelle=None, pdf=True, name=None,
                cwd=None, ps1=None, ohne_pause=True, ohne_unterordner=False):
    """Wie ein Doppelklick: der Doppelklick OBEN im Paket ueber cmd.exe
    (mit den Schaltern der Attrappe). `cwd`: Arbeitsordner (der Explorer
    setzt ihn nicht immer auf den Paketordner, "Als Administrator" etwa auf
    System32). stdin ist leer: ein `pause` kehrt sofort zurueck (gemessen).
    -> (rc, Ausgabe)."""
    ps1 = paket_attrappe(cmd_quelle, pdf, name, ps1)
    oben = os.path.dirname(os.path.dirname(ps1))
    cmd = os.path.join(oben, P.INSTALLIEREN)
    if ohne_unterordner:
        # wie ein Doppelklick IN der ZIP-Datei: nur die eine Datei
        shutil.rmtree(os.path.join(oben, P.UNTERORDNER))
    assert wurzel.startswith(tempfile.gettempdir())
    schalter = ["-OhnePause"] if ohne_pause else []
    # Die .cmd SELBST starten, wie der Explorer ("%1" %*): Windows setzt
    # dann cmd.exe /c "<ganze Zeile>" davor. Ein ["cmd.exe", "/c", pfad,
    # ...] mit Leerzeichen im Pfad UND weiteren Anfuehrungszeichen verlore
    # dagegen die aeusseren Anfuehrungszeichen (Regel von cmd /c) - das ist
    # kein Doppelklick.
    r = subprocess.run([cmd] + schalter + [
        "-OhneServer", "-CadworkWurzel", wurzel, "-CadworkProgramm",
        programm], capture_output=True, timeout=180, cwd=cwd,
        stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr).decode("cp850", "replace")


def kopiert_in(wurzel):
    """Profilnamen, in die das Plugin kopiert wurde."""
    return sorted(p for p in os.listdir(wurzel) if os.path.isfile(
        os.path.join(wurzel, p, "3d", "API.x64", "Open MCP CAD",
                     "marke.txt")))


# --- I10 Server mit API-Hilfe (Rueckmeldung 2026-09-28) --------------------
#
# Ohne das Extra "stubs" fehlte cwapi3d im Server-Python, und
# get_cadwork_api_help fand kein Modul. `Server-Installieren` ruft pip mit
# "<server>[stubs]", faellt ohne das Extra zurueck und sagt es. Gemessen mit
# einer Python-Attrappe (python.cmd -> dieses Python mit einem Skript), die
# jeden Aufruf mitschreibt - pip und Internet laufen nie.

_PIP_ATTRAPPE = r"""
import json, sys
rest = sys.argv[3:]
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rest) + "\n")
print("Attrappe: pip " + " ".join(rest))    # wie pip: schreibt auf stdout
art = sys.argv[2]
if art == "nie" or (art == "ohne_stubs" and any(a.endswith("[stubs]")
                                                 for a in rest)):
    sys.exit(1)
sys.exit(0)
"""


def pip_attrappe(art):
    t = tempfile.mkdtemp(prefix="omcad_pip_")
    _temp.append(t)
    skript = os.path.join(t, "pip_attrappe.py")
    log = os.path.join(t, "aufrufe.jsonl")
    with open(skript, "w", encoding="utf-8") as fh:
        fh.write(_PIP_ATTRAPPE)
    cmd = os.path.join(t, "python.cmd")
    with open(cmd, "w", encoding="ascii") as fh:
        fh.write('@"%s" "%s" "%s" %s %%*\r\n' % (sys.executable, skript,
                                                  log, art))
    return cmd, log


def server_installieren(art, ps1=None):
    cmd, log = pip_attrappe(art)
    quelle = os.path.join(os.path.dirname(cmd), "Paket mit Leerzeichen",
                          "server")
    r = ps_funktionen(
        "$r = @(Server-Installieren '%s' '%s')\n"
        "@{ anzahl = $r.Count; ok = $r[0].Ok; stubs = $r[0].Stubs } | "
        "ConvertTo-Json -Compress" % (cmd, quelle), ps1)
    aufrufe = []
    if os.path.isfile(log):
        with open(log, encoding="utf-8") as fh:
            aufrufe = [json.loads(z) for z in fh if z.strip()]
    return r, aufrufe, quelle


def mutante(alt, neu):
    quelle = open(INSTALL, encoding="ascii").read()
    assert quelle.count(alt) == 1, alt
    t = tempfile.mkdtemp(prefix="omcad_mut_")
    _temp.append(t)
    ziel = os.path.join(t, "install.ps1")
    with open(ziel, "w", encoding="ascii") as fh:
        fh.write(quelle.replace(alt, neu))
    return ziel


def pruefe_server_teil():
    r, aufrufe, quelle = server_installieren("immer")
    pip = ["-m", "pip", "install", "--disable-pip-version-check",
           "--upgrade"]
    pruefe("I10 pip mit dem Extra stubs, EIN Aufruf, Pfad mit Leerzeichen "
           "als EIN Argument, Rueckgabe = ein Objekt (Ok, Stubs)",
           aufrufe == [pip + [quelle + "[stubs]"]]
           and r == {"anzahl": 1, "ok": True, "stubs": True}, (r, aufrufe))
    r, aufrufe, quelle = server_installieren("ohne_stubs")
    pruefe("I10b mit Extra scheitert -> zweiter Aufruf ohne Extra, Ok, "
           "Stubs = false",
           aufrufe == [pip + [quelle + "[stubs]"], pip + [quelle]]
           and r == {"anzahl": 1, "ok": True, "stubs": False}, (r, aufrufe))
    r, aufrufe, quelle = server_installieren("nie")
    pruefe("I10c beide scheitern -> Ok = false (der Installer bricht ab)",
           len(aufrufe) == 2 and r.get("ok") is False, (r, aufrufe))
    # KONTROLLEN: die alte Zeile ohne Extra, und ohne Out-Host (dann landet
    # die Ausgabe von pip im Rueckgabewert) - beide MUESSEN auffallen.
    mut = mutante('($quelle + "[stubs]") | Out-Host', '$quelle | Out-Host')
    r, aufrufe, quelle = server_installieren("immer", mut)
    pruefe("I10-K ohne das Extra fiele I10 auf (pip bekaeme nur den Ordner)",
           aufrufe == [pip + [quelle]], aufrufe)
    mut = mutante('($quelle + "[stubs]") | Out-Host', '($quelle + "[stubs]")')
    r, aufrufe, quelle = server_installieren("immer", mut)
    pruefe("I10-K2 ohne Out-Host kaeme die pip-Ausgabe in den Rueckgabewert",
           r.get("anzahl") != 1, r)
    # Das Extra, das der Installer nennt, gibt es in pyproject.toml und es
    # bringt cwapi3d (Quelle lesen, keine eigene Liste - Regel 3).
    import re
    import tomllib
    ps = open(INSTALL, encoding="ascii").read()
    extras = set(re.findall(r'\$quelle \+ "\[(\w+)\]"', ps))
    with open(os.path.join(REPO, "pyproject.toml"), "rb") as fh:
        opt = tomllib.load(fh)["project"]["optional-dependencies"]
    pruefe("I10d das Extra aus install.ps1 steht in pyproject.toml und "
           "bringt cwapi3d",
           extras == {"stubs"} and any(
               d.split("<")[0].split(">")[0].split("=")[0].strip() == "cwapi3d"
               for d in opt.get("stubs", [])), (extras, opt))


# --- I12-I18 KI-Programme eintragen (Rueckmeldung 2026-09-29) ---------------
#
# Am Ende fragt der Installer je gefundenem Programm (Codex, Claude Code,
# Claude Desktop) und traegt Open MCP CAD ein. Gemessen gegen eine WELT in
# Temp: eigener Heimordner, APPDATA, LOCALAPPDATA, ein PATH nur mit einer
# claude.cmd-Attrappe (schreibt jeden Aufruf mit und fuehrt einen Stand in
# .claude.json wie das echte CLI 2.1.263: get 1/0, add zweimal -> 1).
# Das echte ~/.codex, ~/.claude.json und %APPDATA%\Claude fasst dieses Gate
# nie an (jeder Pfad wird vor dem Lauf gegen Temp geprueft).

_CLAUDE_ATTRAPPE = r"""
import json, os, sys
log, a = sys.argv[1], sys.argv[2:]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(a) + "\n")
datei = os.path.join(os.environ["USERPROFILE"], ".claude.json")
try:
    stand = json.load(open(datei, encoding="utf-8"))
except (OSError, ValueError):
    stand = {}
server = stand.setdefault("mcpServers", {})
if a[:2] == ["mcp", "get"]:
    if a[2] in server:
        print(a[2] + ":\n  Command: " + server[a[2]]["command"])
        sys.exit(0)
    print('No MCP server named "%s".' % a[2])
    sys.exit(1)
if a[:4] == ["mcp", "add", "--scope", "user"]:
    name, rest = a[4], a[6:]
    if name in server:
        print("MCP server %s already exists in user config" % name)
        sys.exit(1)
    server[name] = {"type": "stdio", "command": rest[0], "args": rest[1:],
                    "env": {}}
    json.dump(stand, open(datei, "w", encoding="utf-8"), indent=2)
    sys.exit(0)
sys.exit(2)
"""

CODEX_ALT = ('model = "gpt-5"\n\n[mcp_servers.anderer]\ncommand = "x.exe"\n'
             'args = ["a"]\n\n[mcp_servers.anderer.env]\nK = "v"\n')
DESKTOP_ALT = {"globalShortcut": "Ctrl+Space", "umlaut": "Gr\u00fcsse",
               "mcpServers": {"anderer": {"command": "y.exe", "args": ["b"],
                                          "env": {"A": "1"}}}}
CLAUDE_ALT = {"userID": "abc", "mcpServers": {"alt": {"command": "z.exe"}}}


def ki_welt(programme=("codex", "claude_code", "claude_desktop"),
            codex=CODEX_ALT, desktop=None, ki_quelle=None, heim_name=None,
            claude="cmd"):
    """-> dict mit Pfaden, env und dem Helfer-Python (python.cmd).
    `claude`: "cmd" = claude.cmd auf dem PATH (npm), "exe" = claude.exe
    unter ~/.local/bin, NICHT auf dem PATH (eigener Installer)."""
    t = tempfile.mkdtemp(prefix="omcad_ki_")
    _temp.append(t)
    heim = os.path.join(t, heim_name or "heim mit Leer")
    w = {"t": t, "heim": heim,
         "appdata": os.path.join(heim, "AppData", "Roaming"),
         "local": os.path.join(heim, "AppData", "Local"),
         "bin": os.path.join(t, "bin"), "log": os.path.join(t, "claude.log")}
    for o in (w["appdata"], w["local"], w["bin"]):
        os.makedirs(o)
    w["codex"] = os.path.join(heim, ".codex", "config.toml")
    w["desktop"] = os.path.join(w["appdata"], "Claude",
                                "claude_desktop_config.json")
    w["claude_json"] = os.path.join(heim, ".claude.json")
    if "codex" in programme:
        os.makedirs(os.path.dirname(w["codex"]))
        if codex is not None:
            with open(w["codex"], "wb") as fh:
                fh.write(codex.encode("utf-8"))
    if "claude_desktop" in programme:
        os.makedirs(os.path.dirname(w["desktop"]))
        with open(w["desktop"], "wb") as fh:
            fh.write(desktop if isinstance(desktop, bytes) else json.dumps(
                desktop or DESKTOP_ALT, indent=2,
                ensure_ascii=False).encode("utf-8"))
    if "claude_code" in programme:
        skript = os.path.join(t, "claude_attrappe.py")
        with open(skript, "w", encoding="utf-8") as fh:
            fh.write(_CLAUDE_ATTRAPPE)
        if claude == "exe":
            w["claude_exe"] = _exe_attrappe(
                os.path.join(heim, ".local", "bin", "claude.exe"), skript,
                [w["log"]])
        else:
            with open(os.path.join(w["bin"], "claude.cmd"), "w",
                      encoding="ascii") as fh:
                fh.write('@"%s" "%s" "%s" %%*\r\n' % (sys.executable, skript,
                                                       w["log"]))
        with open(w["claude_json"], "w", encoding="utf-8") as fh:
            json.dump(CLAUDE_ALT, fh)
    # Das Helfer-Python: dieses Python mit dem Repo (oder einer Mutante)
    # vorn auf dem Suchpfad.
    w["helfer"] = os.path.join(t, "python.cmd")
    with open(w["helfer"], "w", encoding="ascii") as fh:
        fh.write('@set "PYTHONPATH=%s"\r\n@"%s" %%*\r\n'
                 % (ki_quelle or REPO, sys.executable))
    root = os.environ.get("SystemRoot", r"C:\Windows")
    w["env"] = {"SystemRoot": root, "windir": root,
                "ComSpec": os.path.join(root, "System32", "cmd.exe"),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
                "PATH": ";".join([w["bin"], os.path.join(root, "System32"),
                                  root, os.path.join(root, "System32",
                                                     "WindowsPowerShell",
                                                     "v1.0")]),
                "USERPROFILE": heim, "HOME": heim, "APPDATA": w["appdata"],
                "LOCALAPPDATA": w["local"], "TEMP": t, "TMP": t,
                "PSModulePath": os.path.join(root, "System32",
                                             "WindowsPowerShell", "v1.0",
                                             "Modules")}
    w["server"] = os.path.join(t, "py mit Leer", "pythonw.exe")
    if heim_name:
        # wie der Installer: das Server-venv unter %LOCALAPPDATA%
        w["server"] = os.path.join(w["local"], "OpenMcpCad", "python",
                                   "Scripts", "pythonw.exe")
    for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP"):
        assert w["env"][k].startswith(tempfile.gettempdir()), k
    return w


def ki_lauf(w, antworten, alle=False, ps1=None):
    """Die Funktion des Installers in der Welt. -> (Ergebnis-JSON, Text)."""
    liste = ",".join("'%s'" % a for a in antworten) or ""
    skript = (". '%s' -NurFunktionen\n"
              "$global:antw = [System.Collections.ArrayList]@(%s)\n"
              "$frage = { param($t) Write-Host ('FRAGE: ' + $t); "
              "$a = 'n'; if ($global:antw.Count -gt 0) { $a = $global:antw[0]; "
              "$global:antw.RemoveAt(0) }; "
              "return ($a -match '^\\s*(j|ja|y|yes)?\\s*$') }\n"
              "$r = KI-Programme-Eintragen '%s' '%s' $frage $%s\n"
              "@{ zeilen = @($r | ForEach-Object { $_.Name + '|' + $_.Status }); "
              "ki = (KI-Zeile $r) } | ConvertTo-Json -Compress"
              % (ps1 or INSTALL, liste, w["helfer"], w["server"],
                 "true" if alle else "false"))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", skript], capture_output=True,
                       timeout=300, env=w["env"],
                       # NICHT im Repo: `-m` nimmt sonst open_mcp_cad aus
                       # dem Arbeitsordner statt vom Suchpfad (Mutanten)
                       cwd=w["t"])
    aus = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    zeilen = [z for z in aus.splitlines() if z.strip()]
    try:
        return json.loads(zeilen[-1]), aus
    except Exception:                                 # noqa: BLE001
        return {"_fehler": aus[-800:]}, aus


def _bytes(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _stand(w):
    """Alle Dateien der Welt, die ein Lauf aendern duerfte, als Bytes, dazu
    die Sicherungen und die Aufrufe von claude."""
    sicherungen = sorted(
        os.path.relpath(os.path.join(d, n), w["t"])
        for d, _u, ns in os.walk(w["t"]) for n in ns
        if ".vor-open-mcp-cad-" in n)
    log = _bytes(w["log"]) or b""
    return {"codex": _bytes(w["codex"]), "desktop": _bytes(w["desktop"]),
            "claude_json": _bytes(w["claude_json"]),
            "sicherungen": sicherungen,
            "aufrufe": [json.loads(z) for z in log.decode().splitlines()
                        if z.strip()]}


def _eintrag_ok(w, vorher):
    """Was nach einem Ja zu allen drei stimmen muss. -> Liste der Fehler."""
    import tomllib
    f = []
    neu = _stand(w)
    name, args = "open-mcp-cad", ["-m", "open_mcp_cad.server"]
    # Codex: alter Inhalt unveraendert VORN, dahinter nur unser Abschnitt
    c = neu["codex"] or b""
    d = tomllib.loads(c.decode("utf-8")) if c else {}
    alt = tomllib.loads(vorher["codex"].decode("utf-8"))
    if not c.startswith(vorher["codex"]):
        f.append("codex: alter Inhalt nicht unveraendert vorn")
    if d.get("mcp_servers", {}).get(name) != {"command": w["server"],
                                               "args": args}:
        f.append("codex: Eintrag fehlt/falsch")
    rest = {k: v for k, v in d.items() if k != "mcp_servers"}
    rest_alt = {k: v for k, v in alt.items() if k != "mcp_servers"}
    if rest != rest_alt or d["mcp_servers"].get("anderer") != \
            alt["mcp_servers"]["anderer"]:
        f.append("codex: andere Eintraege veraendert")
    # Desktop: alles andere gleich, unser Eintrag dazu
    dj = json.loads((neu["desktop"] or b"{}").decode("utf-8"))
    aj = json.loads(vorher["desktop"].decode("utf-8"))
    if dj.get("mcpServers", {}).get(name) != {"command": w["server"],
                                              "args": args}:
        f.append("desktop: Eintrag fehlt/falsch")
    dj_ohne = dict(dj, mcpServers={k: v for k, v in dj.get(
        "mcpServers", {}).items() if k != name})
    if dj_ohne != aj:
        f.append("desktop: andere Eintraege veraendert")
    # Claude Code: ueber claude mcp add --scope user, .claude.json sonst gleich
    soll_add = ["mcp", "add", "--scope", "user", name, "--", w["server"]] + args
    if neu["aufrufe"].count(soll_add) != 1:
        f.append("claude: add nicht genau einmal: %s" % neu["aufrufe"])
    cj = json.loads((neu["claude_json"] or b"{}").decode("utf-8"))
    if {k: v for k, v in cj.items() if k != "mcpServers"} != \
            {k: v for k, v in CLAUDE_ALT.items() if k != "mcpServers"} \
            or cj.get("mcpServers", {}).get("alt") != \
            CLAUDE_ALT["mcpServers"]["alt"]:
        f.append("claude: andere Eintraege veraendert")
    # Sicherungen: je Datei EINE, mit dem alten Inhalt
    for schluessel in ("codex", "desktop", "claude_json"):
        pfad = w[schluessel]
        kopien = [s for s in neu["sicherungen"] if os.path.basename(s)
                  .startswith(os.path.basename(pfad) + ".vor-open-mcp-cad-")]
        if len(kopien) != 1 or _bytes(os.path.join(w["t"], kopien[0])) \
                != vorher[schluessel]:
            f.append("%s: keine Sicherung mit altem Inhalt (%s)"
                     % (schluessel, kopien))
    return f


def pruefe_ki_teil():
    sys.path.insert(0, REPO)
    import importlib
    KE = importlib.import_module("open_mcp_cad.ki_eintragen")
    assert os.path.dirname(os.path.dirname(KE.__file__)) == REPO, KE.__file__

    # I12 finden: alle drei in der Welt, keins in einer leeren
    w = ki_welt()
    gef = [p["programm"] for p in KE.finden(w["env"])]
    leer = ki_welt(programme=())
    pruefe("I12 finden: Codex, Claude Code, Claude Desktop in der Welt; in "
           "einer leeren Welt keins (KONTROLLE)",
           gef == ["codex", "claude_code", "claude_desktop"]
           and KE.finden(leer["env"]) == [], (gef, KE.finden(leer["env"])))

    # I13 alles mit Enter (j): eingetragen, gesichert, sonst nichts geaendert
    vorher = _stand(w)
    erg, aus = ki_lauf(w, ["", "", ""])
    fehler = _eintrag_ok(w, vorher)
    pruefe("I13 Enter zu allen drei: eingetragen, je eine Sicherung mit dem "
           "alten Inhalt, andere Eintraege unveraendert",
           erg.get("zeilen") == ["Codex|eingetragen", "Claude Code|eingetragen",
                                 "Claude Desktop|eingetragen"] and not fehler,
           (erg, fehler, aus[-600:]))
    pruefe("I13 sagt je Programm, was geaendert wurde, wo die Sicherung liegt "
           "und wie man es zuruecknimmt",
           aus.count("Sicherung:") == 3 and aus.count("Rueckgaengig:") == 3
           and "claude mcp remove open-mcp-cad -s user" in aus
           and w["codex"] in aus.replace("\r\n", "") and "FRAGE: Open MCP CAD "
           "in Codex eintragen? [J/n]" in aus
           and erg.get("ki") == "Codex eingetragen; Claude Code eingetragen; "
           "Claude Desktop eingetragen", aus[-1500:])

    # I14 ein zweiter Lauf aendert nichts
    danach = _stand(w)
    erg2, aus2 = ki_lauf(w, ["", "", ""])
    pruefe("I14 zweiter Lauf: alles schon_da, keine Datei geaendert, keine "
           "neue Sicherung, kein zweites claude mcp add",
           erg2.get("zeilen") == ["Codex|schon_da", "Claude Code|schon_da",
                                  "Claude Desktop|schon_da"]
           and _stand(w) == dict(danach, aufrufe=_stand(w)["aufrufe"])
           and [a for a in _stand(w)["aufrufe"] if a[:2] == ["mcp", "add"]]
           == [a for a in danach["aufrufe"] if a[:2] == ["mcp", "add"]],
           (erg2, aus2[-600:]))

    # I15 "n" zu allen: nichts geaendert, nichts gesichert, claude nie gerufen
    w = ki_welt()
    vorher = _stand(w)
    erg, aus = ki_lauf(w, ["n", "n", "n"])
    pruefe("I15 'n' zu allen: nichts geaendert, keine Sicherung, claude nie "
           "gerufen", erg.get("zeilen") == ["Codex|abgelehnt",
                                             "Claude Code|abgelehnt",
                                             "Claude Desktop|abgelehnt"]
           and _stand(w) == vorher, (erg, aus[-500:]))

    # I16 ein eigener Eintrag mit anderem Befehl bleibt, wie er ist
    anders_codex = CODEX_ALT + ("\n[mcp_servers.open-mcp-cad]\ncommand = "
                                "'C:\\alt\\python.exe'\nargs = [\"-m\", "
                                "\"open_mcp_cad.server\"]\n")
    anders_desktop = dict(DESKTOP_ALT, mcpServers=dict(
        DESKTOP_ALT["mcpServers"], **{"open-mcp-cad": {"command": "alt"}}))
    w = ki_welt(programme=("codex", "claude_desktop"), codex=anders_codex,
                desktop=anders_desktop)
    vorher = _stand(w)
    erg, aus = ki_lauf(w, ["j", "j"])
    pruefe("I16 anderer eigener Eintrag: abweichend, nichts geaendert, keine "
           "Sicherung", erg.get("zeilen") == ["Codex|abweichend",
                                               "Claude Desktop|abweichend"]
           and _stand(w) == vorher, (erg, aus[-500:]))

    # I17 unlesbare Dateien bleiben unberuehrt; ein Eintrag, der die Datei
    # kaputt machte (mcp_servers als Inline-Tabelle), wird zurueckgenommen
    for titel, codex, desktop in (
            ("kaputt", "[[x\n", b"{ kaputt"),
            ("inline", 'mcp_servers = { a = { command = "x" } }\n',
             b"[1, 2]")):
        w = ki_welt(programme=("codex", "claude_desktop"), codex=codex,
                    desktop=desktop)
        vorher = _stand(w)
        erg, aus = ki_lauf(w, ["j", "j"])
        codex_bak = [s for s in _stand(w)["sicherungen"] if "config" in s]
        pruefe("I17 %s: fehler, beide Dateien unveraendert" % titel,
               erg.get("zeilen") == ["Codex|fehler", "Claude Desktop|fehler"]
               and _stand(w)["codex"] == vorher["codex"]
               and _stand(w)["desktop"] == vorher["desktop"]
               and (titel == "inline" or not codex_bak),
               (erg, aus[-500:]))

    # I18 nichts gefunden: die Zeile im Ergebnis sagt, was zu tun ist; ein
    # neu anzulegendes config.toml (nur der Ordner .codex da)
    w = ki_welt(programme=())
    erg, aus = ki_lauf(w, [])
    pruefe("I18 kein Programm: Ergebnis-Zeile verweist auf die Anleitung",
           erg.get("ki", "").startswith("keins gefunden - siehe "
                                        "2_ANLEITUNG.pdf"), (erg, aus[-300:]))
    w = ki_welt(programme=("codex",), codex=None)
    erg, aus = ki_lauf(w, ["j"])
    import tomllib
    neu = tomllib.loads((_bytes(w["codex"]) or b"").decode("utf-8"))
    pruefe("I18b nur der Ordner .codex: config.toml neu, darin nur unser "
           "Eintrag", erg.get("zeilen") == ["Codex|eingetragen"]
           and neu == {"mcp_servers": {"open-mcp-cad": {
               "command": w["server"], "args": ["-m", "open_mcp_cad.server"]}}},
           (erg, neu))
    # I18c ein Pfad mit ' (Benutzername O'Brien) wird ein TOML-String mit
    # Escapes und bleibt lesbar
    # (zusammengesetzt: am Stueck schluege der Export an dieser Datei an)
    obrien = "C:\\" + "Users\\O'Brien\\py\\pythonw.exe"
    block = KE.codex_block(obrien)
    pruefe("I18c Pfad mit ' bleibt in TOML lesbar",
           tomllib.loads(block)["mcp_servers"]["open-mcp-cad"]["command"]
           == obrien and "'" + obrien + "'" not in block, block)

    # I18d Rueckmeldung 2026-10-10: "KI-Programme: Claude Desktop
    # eingetragen; Claude Desktop eingetragen" - Claude Desktop hat zwei
    # Orte (%APPDATA%\Claude und das Store-Paket Packages\Claude_*). Jedes
    # Programm steht EINMAL in der Zeile; Gleiches an zwei Orten "(2 Orte)",
    # Verschiedenes bleibt unterscheidbar.
    def zwei_orte():
        w = ki_welt(programme=("claude_desktop",))
        store = os.path.join(w["local"], "Packages", "Claude_test123",
                             "LocalCache", "Roaming", "Claude")
        os.makedirs(store)
        with open(os.path.join(store, "claude_desktop_config.json"), "wb") \
                as fh:
            fh.write(json.dumps(DESKTOP_ALT, indent=2).encode("utf-8"))
        return w
    erg, aus = ki_lauf(zwei_orte(), ["", "", ""])
    gemischt = ps_funktionen(
        "$e = @([pscustomobject]@{ Name = 'Codex'; Status = 'eingetragen' },"
        " [pscustomobject]@{ Name = 'Claude Desktop'; Status = 'eingetragen' },"
        " [pscustomobject]@{ Name = 'Claude Desktop'; Status = 'schon_da' },"
        " [pscustomobject]@{ Name = 'Claude Code'; Status = 'abgelehnt' })\n"
        "@{ ki = (KI-Zeile $e) } | ConvertTo-Json -Compress")
    pruefe("I18d Claude Desktop an zwei Orten (APPDATA + Store-Paket): beide "
           "eingetragen, die Zeile nennt es EINMAL ('(2 Orte)'); verschiedene "
           "Ergebnisse desselben Programms bleiben unterscheidbar",
           erg.get("zeilen") == ["Claude Desktop|eingetragen",
                                 "Claude Desktop|eingetragen"]
           and erg.get("ki") == "Claude Desktop eingetragen (2 Orte)"
           and gemischt.get("ki") == "Codex eingetragen; Claude Desktop "
           "eingetragen, war schon eingetragen; Claude Code nicht gewollt",
           (erg, gemischt, aus[-400:]))
    # KONTROLLE: die Fassung vor 2026-10-10 (Commit 12ccf52, aus git) nennt
    # Claude Desktop in derselben Welt zweimal.
    alt_ps1 = os.path.join(tempfile.mkdtemp(prefix="omcad_kialt_"),
                           "install.ps1")
    _temp.append(os.path.dirname(alt_ps1))
    with open(alt_ps1, "wb") as fh:
        fh.write(subprocess.run(["git", "show", "12ccf52:verteilung/"
                                 "install.ps1"], cwd=REPO, capture_output=True,
                                check=True).stdout)
    erg_k, aus_k = ki_lauf(zwei_orte(), ["", "", ""], ps1=alt_ps1)
    pruefe("I18d-K KONTROLLE: die alte KI-Zeile (12ccf52) schreibt "
           "'Claude Desktop eingetragen; Claude Desktop eingetragen'",
           erg_k.get("ki") == "Claude Desktop eingetragen; Claude Desktop "
           "eingetragen", (erg_k, aus_k[-300:]))

    # KONTROLLEN: Mutanten von ki_eintragen.py (auf dem Suchpfad des
    # Helfers) und von install.ps1 — jede MUSS eine Zelle oben rot machen.
    quelle = open(KE.__file__, encoding="utf-8").read()

    def mutante(alt, neu):
        assert quelle.count(alt) == 1, alt
        t = tempfile.mkdtemp(prefix="omcad_kimut_")
        _temp.append(t)
        os.makedirs(os.path.join(t, "open_mcp_cad"))
        for n in os.listdir(os.path.dirname(KE.__file__)):
            if n.endswith(".py"):
                shutil.copy(os.path.join(os.path.dirname(KE.__file__), n),
                            os.path.join(t, "open_mcp_cad", n))
        with open(os.path.join(t, "open_mcp_cad", "ki_eintragen.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(quelle.replace(alt, neu))
        return t

    def mit_ja(q):
        w = ki_welt(ki_quelle=q)
        vorher = _stand(w)
        erg, _aus = ki_lauf(w, ["", "", ""])
        return w, erg, _eintrag_ok(w, vorher)

    _w, _e, f = mit_ja(mutante("    shutil.copy2(datei, ziel)\n",
                               "    pass\n"))
    k1 = any("Sicherung" in x for x in f)
    _w, _e, f = mit_ja(mutante('daten["mcpServers"] = dict(server)',
                               'daten = {"mcpServers": {}}'))
    k2 = "desktop: andere Eintraege veraendert" in f
    w, _e, _f = mit_ja(mutante("        if vorhanden is not None:",
                               "        if False:"))
    e2, _a = ki_lauf(w, ["", "", ""])
    k3 = (e2.get("zeilen") or [""])[0] != "Codex|schon_da"
    w, _e, _f = mit_ja(mutante("    if r.returncode == 0:\n        aus",
                               "    if False:\n        aus"))
    ki_lauf(w, ["", "", ""])
    k4 = len([a for a in _stand(w)["aufrufe"] if a[:2] == ["mcp", "add"]]) != 1
    ps_mut = mutante_ps("$ja = [bool](& $frage", "$ja = $true; $null = (& $frage")
    w = ki_welt()
    vorher = _stand(w)
    ki_lauf(w, ["n", "n", "n"], ps1=ps_mut)
    k5 = _stand(w) != vorher
    pruefe("I12-K KONTROLLEN: ohne Sicherung (I13), Desktop ohne alte "
           "Eintraege (I13), Codex ohne Pruefung auf den eigenen Eintrag "
           "(I14), claude ohne mcp get (I14), Frage ueberhoert (I15) - jede "
           "faellt auf", k1 and k2 and k3 and k4 and k5,
           dict(k1=k1, k2=k2, k3=k3, k4=k4, k5=k5))


# --- I19 Gegenpruefung 2026-09-29: fremde Dateien nie zerstoeren --------------
# Die Faelle, an denen ein Eintrag in die Konfiguration eines ANDEREN
# Programms schiefgehen kann: BOM und CRLF, eine unpassende Tabelle, ein
# Python ohne tomllib (3.10), eine gesperrte Datei, Umlaute und Leerzeichen
# im Benutzernamen, claude.exe statt claude.cmd. Kontrollen laufen gegen
# die ALTE Fassung (Commit a092618, aus git gelesen).

ALT_STAND = "a092618"


def _alte_fassung():
    """ki_eintragen.py im Stand vor der Gegenpruefung, als Modul."""
    import importlib.util
    roh = subprocess.run(["git", "show", ALT_STAND +
                          ":open_mcp_cad/ki_eintragen.py"], cwd=REPO,
                         capture_output=True, check=True).stdout
    t = tempfile.mkdtemp(prefix="omcad_kialt_")
    _temp.append(t)
    pfad = os.path.join(t, "ki_eintragen_alt.py")
    with open(pfad, "wb") as fh:
        fh.write(roh)
    spec = importlib.util.spec_from_file_location("ki_eintragen_alt", pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _OhneTomllib:
    """`import tomllib` scheitert wie in Python 3.10 (und auf Wunsch auch
    das tomli, das pip mitbringt)."""

    def __init__(self, auch_pip=False):
        self.namen = ["tomllib"] + (["pip._vendor.tomli"] if auch_pip else [])

    def __enter__(self):
        self.alt = {n: sys.modules.get(n, "-") for n in self.namen}
        for n in self.namen:
            sys.modules[n] = None            # import -> ImportError
        if len(self.namen) > 1:
            import pip._vendor as pv
            self.pv_alt = getattr(pv, "tomli", "-")
            if hasattr(pv, "tomli"):
                delattr(pv, "tomli")
        return self

    def __exit__(self, *_a):
        for n, v in self.alt.items():
            if v == "-":
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v
        if len(self.namen) > 1 and self.pv_alt != "-":
            import pip._vendor as pv
            pv.tomli = self.pv_alt


def _toml(pfad):
    import tomllib
    text = open(pfad, "rb").read().decode("utf-8")
    return tomllib.loads(text[1:] if text.startswith("\ufeff") else text)


def _exe_attrappe(ziel, skript, vorn=()):
    """Ein ECHTES claude.exe (Starter von pip, distlib t64.exe) vor `skript`,
    mit `vorn` als ersten Argumenten. -> Pfad oder None."""
    import io
    import zipfile
    import pip
    starter = os.path.join(os.path.dirname(pip.__file__), "_vendor",
                           "distlib", "t64.exe")
    if not os.path.isfile(starter):
        return None
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("__main__.py", "import runpy, sys\nsys.argv[1:1] = %r\n"
                   "runpy.run_path(%r, run_name='__main__')\n"
                   % (list(vorn), skript))
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(starter, "rb") as fh, open(ziel, "wb") as aus:
        aus.write(fh.read() + b'#!"' + sys.executable.encode("mbcs") + b'"\n'
                  + puffer.getvalue())
    return ziel


def _ascii(text):
    return "".join(c if ord(c) < 128 else "?" for c in text)


def pruefe_ki_kanten():
    import importlib
    KE = importlib.import_module("open_mcp_cad.ki_eintragen")
    ALT = _alte_fassung()
    py = "C:\\Programme\\Jürg Müller\\py\\pythonw.exe"
    soll = {"command": py, "args": ["-m", "open_mcp_cad.server"]}

    def datei(inhalt, name="config.toml"):
        t = tempfile.mkdtemp(prefix="omcad_kante_")
        _temp.append(t)
        pfad = os.path.join(t, name)
        with open(pfad, "wb") as fh:
            fh.write(inhalt)
        return pfad

    def baks(pfad):
        d = os.path.dirname(pfad)
        return sorted(n for n in os.listdir(d) if ".vor-open-mcp-cad-" in n)

    # I19a BOM + CRLF: eingetragen, alter Inhalt samt BOM vorn, CRLF auch im
    # neuen Abschnitt, alles andere gleich
    alt = ("\ufeff" + CODEX_ALT).replace("\n", "\r\n").encode("utf-8")
    pfad = datei(alt)
    e = KE.codex_eintragen(pfad, py)
    neu = open(pfad, "rb").read()
    d = _toml(pfad)
    rest = neu[len(alt):]
    pruefe("I19a config.toml mit BOM und CRLF: eingetragen, vorn der alte "
           "Inhalt samt BOM, neuer Abschnitt mit CRLF, Umlaut-Pfad lesbar",
           e["status"] == "eingetragen" and neu.startswith(alt)
           and b"\n" not in rest.replace(b"\r\n", b"")
           and d["mcp_servers"]["open-mcp-cad"] == soll
           and d["mcp_servers"]["anderer"]["env"] == {"K": "v"}
           and d["model"] == "gpt-5" and len(baks(pfad)) == 1, (e, rest))
    k = ALT.codex_eintragen(datei(alt), py)
    pruefe("I19a-K KONTROLLE: die alte Fassung wies die Datei mit BOM ab",
           k["status"] == "fehler", k)

    # I19b Python ohne tomllib (3.10): pip's tomli prueft; die unpassende
    # Datei (Inline-Tabelle) bleibt unberuehrt
    inline = b'mcp_servers = { a = { command = "x" } }\n'
    with _OhneTomllib():
        pfad = datei(inline)
        e = KE.codex_eintragen(pfad, py)
        gut = datei(CODEX_ALT.encode("utf-8"))
        e_gut = KE.codex_eintragen(gut, py)
    with _OhneTomllib(auch_pip=True):
        ohne = datei(CODEX_ALT.encode("utf-8"))
        e_ohne = KE.codex_eintragen(ohne, py)
    pruefe("I19b ohne tomllib: mit dem tomli von pip geprueft - die "
           "Inline-Tabelle bleibt unberuehrt, eine gute Datei wird "
           "eingetragen; ganz ohne Leser nichts geaendert",
           e["status"] == "fehler" and open(pfad, "rb").read() == inline
           and e_gut["status"] == "eingetragen"
           and _toml(gut)["mcp_servers"]["open-mcp-cad"] == soll
           and e_ohne["status"] == "fehler"
           and open(ohne, "rb").read() == CODEX_ALT.encode("utf-8"),
           (e, e_gut, e_ohne))
    with _OhneTomllib():
        k_pfad = datei(inline)
        k = ALT.codex_eintragen(k_pfad, py)
        try:
            _toml(k_pfad)
            k_lesbar = True
        except Exception:                             # noqa: BLE001
            k_lesbar = False
    pruefe("I19b-K KONTROLLE: die alte Fassung trug ohne tomllib in die "
           "Inline-Tabelle ein - danach war config.toml fuer Codex kaputt",
           k["status"] == "eingetragen" and not k_lesbar, k)

    # I19c unerwartete Formen: mcp_servers ist keine Tabelle / unser
    # Eintrag ist keine Tabelle -> nie geaendert, keine rohe Ausnahme
    faelle = {"liste": b"mcp_servers = [1, 2]\n",
              "text": b'[mcp_servers]\n"open-mcp-cad" = "x"\n'}
    erg = {}
    for n, inhalt in faelle.items():
        pfad = datei(inhalt)
        try:
            status = KE.codex_eintragen(pfad, py)["status"]
        except Exception as exc:                      # noqa: BLE001
            status = type(exc).__name__
        erg[n] = (status, open(pfad, "rb").read() == inhalt)
    k = []
    for inhalt in faelle.values():
        try:
            k.append(ALT.codex_eintragen(datei(inhalt), py)["status"])
        except Exception as exc:                      # noqa: BLE001
            k.append(type(exc).__name__)
    pruefe("I19c mcp_servers keine Tabelle / eigener Eintrag kein Objekt: "
           "fehler bzw. abweichend, Datei unveraendert",
           erg == {"liste": ("fehler", True), "text": ("abweichend", True)},
           erg)
    pruefe("I19c-K KONTROLLE: die alte Fassung warf dort (AttributeError)",
           k == ["AttributeError", "AttributeError"], k)

    # I19d gesperrte Datei (offen in einem anderen Programm): fehler,
    # Inhalt unveraendert, keine Temp-Datei liegt herum
    ergebnisse = {}
    for n, (inhalt, prog, name) in {
            "codex": (CODEX_ALT.encode("utf-8"), "codex", "config.toml"),
            "desktop": (json.dumps(DESKTOP_ALT).encode("utf-8"),
                        "claude_desktop", "claude_desktop_config.json")
    }.items():
        heim = tempfile.mkdtemp(prefix="omcad_sperre_")
        _temp.append(heim)
        env = {"USERPROFILE": heim, "APPDATA": os.path.join(heim, "a"),
               "LOCALAPPDATA": os.path.join(heim, "l"), "PATH": heim,
               "CODEX_HOME": os.path.join(heim, ".codex")}
        ordner = (env["CODEX_HOME"] if prog == "codex"
                  else os.path.join(env["APPDATA"], "Claude"))
        os.makedirs(ordner)
        pfad = os.path.join(ordner, name)
        with open(pfad, "wb") as fh:
            fh.write(inhalt)
        with open(pfad, "rb"):          # offen = os.replace scheitert
            try:
                e = KE.eintragen(prog, py, env)
            except Exception as exc:                  # noqa: BLE001
                e = [{"status": type(exc).__name__}]
            tmp = [x for x in os.listdir(ordner) if x.endswith(".tmp")]
            try:
                ALT.eintragen(prog, py, env)
                k = "kein Fehler"
            except OSError as exc:
                k = type(exc).__name__
        ergebnisse[n] = (e[0]["status"], open(pfad, "rb").read() == inhalt,
                         tmp, k)
    pruefe("I19d Datei offen in einem anderen Programm: fehler mit Grund, "
           "Inhalt unveraendert, keine Temp-Datei liegen gelassen",
           all(v[:3] == ("fehler", True, []) for v in ergebnisse.values()),
           ergebnisse)
    pruefe("I19d-K KONTROLLE: die alte Fassung warf dort roh (PermissionError)",
           all(v[3] == "PermissionError" for v in ergebnisse.values()),
           {n: v[3] for n, v in ergebnisse.items()})

    # I19e Claude Desktop: BOM wird gelesen und nicht wieder geschrieben;
    # Kommentare (kein JSON) -> unberuehrt
    bom = b"\xef\xbb\xbf" + json.dumps(DESKTOP_ALT, ensure_ascii=False
                                       ).encode("utf-8")
    pfad = datei(bom, "claude_desktop_config.json")
    e = KE.desktop_eintragen(pfad, py)
    neu = open(pfad, "rb").read()
    jc = b'{\n  // Kommentar\n  "mcpServers": {}\n}\n'
    pfad2 = datei(jc, "claude_desktop_config.json")
    e2 = KE.desktop_eintragen(pfad2, py)
    dj = json.loads(neu.decode("utf-8"))
    pruefe("I19e Desktop-Datei mit BOM: eingetragen, ohne BOM geschrieben, "
           "alles andere gleich; mit Kommentar: fehler, unveraendert",
           e["status"] == "eingetragen" and not neu.startswith(b"\xef\xbb\xbf")
           and dj["mcpServers"]["open-mcp-cad"] == soll
           and dict(dj, mcpServers={k: v for k, v in dj["mcpServers"].items()
                                    if k != "open-mcp-cad"}) == DESKTOP_ALT
           and e2["status"] == "fehler" and open(pfad2, "rb").read() == jc,
           (e, e2))

    # I19f Rueckwege, die man so eintippen kann: copy /Y nur mit dem
    # Hinweis auf cmd (in PowerShell scheitert es an "/Y"); claude ohne
    # PATH mit vollem Pfad
    pfad = datei(CODEX_ALT.encode("utf-8"))
    e = KE.codex_eintragen(pfad, py)
    pruefe("I19f Rueckgaengig bei Codex: Abschnitt loeschen oder die "
           "Sicherung zurueckholen - mit dem Hinweis, dass copy /Y in die "
           "Eingabeaufforderung (cmd) gehoert",
           "in der Eingabeaufforderung (cmd): copy /Y" in e["rueckgaengig"]
           and "[mcp_servers.open-mcp-cad]" in e["rueckgaengig"],
           e["rueckgaengig"])

    # I19g claude.exe (eigener Installer, nicht auf dem PATH) und ein
    # Benutzername mit Umlaut und Leerzeichen, ueber den ECHTEN Installer
    w = ki_welt(programme=("claude_code",), heim_name="Jürg Müller",
                claude="exe")
    erg, aus = ki_lauf(w, [""])
    add = [a for a in _stand(w)["aufrufe"] if a[:2] == ["mcp", "add"]]
    pruefe("I19g claude.exe unter ~\\.local\\bin (nicht auf dem PATH), "
           "Heim 'Jürg Müller': gefunden, eingetragen, der Pfad kommt "
           "woertlich an, Rueckweg mit vollem Pfad",
           erg.get("zeilen") == ["Claude Code|eingetragen"]
           and add == [["mcp", "add", "--scope", "user", "open-mcp-cad", "--",
                        w["server"], "-m", "open_mcp_cad.server"]]
           # Umlaute kommen in der UMGELEITETEN Ausgabe von PowerShell 5.1
           # in der Codepage der Umleitung an, hier also verstuemmelt; im
           # Fenster stehen sie richtig (Write-Host schreibt dort Unicode).
           # Verglichen wird deshalb nur das ASCII-Geruest.
           and _ascii('"%s" mcp remove open-mcp-cad -s user'
                      % w["claude_exe"]) in _ascii(aus.replace("\r\n", "")),
           (erg, add, aus[-700:]))
    w = ki_welt(programme=("claude_code",), heim_name="Jürg Müller")
    erg, aus = ki_lauf(w, [""])
    add = [a for a in _stand(w)["aufrufe"] if a[:2] == ["mcp", "add"]]
    pruefe("I19g ebenso ueber claude.cmd (cmd.exe dazwischen): der Umlaut-"
           "Pfad mit Leerzeichen kommt woertlich an",
           erg.get("zeilen") == ["Claude Code|eingetragen"]
           and add and add[0][6] == w["server"], (erg, add, aus[-500:]))


# --- I20 Python ohne winget (seit 2026-10-01) -------------------------------
#
# Auf Windows 10 LTSC und gesperrten Firmen-PCs fehlt winget; der Installer
# brach dort mit "bitte von python.org installieren" ab. Jetzt laedt er den
# offiziellen Installer (feste Version, HTTPS), prueft die Authenticode-
# Signatur und startet ihn erst dann. Gemessen gegen ATTRAPPEN: Laden,
# Signatur und Start sind eigene Funktionen, die das Gate nach dem Laden der
# Funktionen ersetzt - es wird NIE etwas heruntergeladen oder installiert.
# Die echte Signaturpruefung (Get-AuthenticodeSignature) laeuft an echten
# Dateien dieses Rechners: einem Python der Python Software Foundation,
# einer veraenderten Kopie davon, powershell.exe und einer unsignierten
# Datei.

PSF = ("CN=Python Software Foundation, O=Python Software Foundation, "
       "L=Beaverton, S=Oregon, C=US")


def _psf_exe():
    """Ein von der Python Software Foundation signiertes Programm dieses
    Rechners (gemessen mit Get-AuthenticodeSignature) oder None."""
    kandidaten = [sys.executable, getattr(sys, "_base_executable", ""),
                  shutil.which("py") or "", shutil.which("python") or ""]
    for k in kandidaten:
        if not k or not os.path.isfile(k):
            continue
        r = ps_funktionen(
            "$s = Get-AuthenticodeSignature -LiteralPath '%s'\n"
            "@{ status = \"$($s.Status)\"; wer = \"$($s.SignerCertificate."
            "Subject)\" } | ConvertTo-Json -Compress" % k)
        if r.get("status") == "Valid" and \
                "CN=Python Software Foundation" in r.get("wer", ""):
            return k
    return None


def python_org_lauf(quelle=None, laden="ok", signatur=None, setup=0,
                    ps1=None, aufruf="Python-Von-PythonOrg", pfad=None):
    """Fuehrt den Rueckfall gegen Attrappen aus.

    `quelle`: die Datei, die der Download "liefert"; `laden`: ok / fehler
    (wirft) / leer (keine Datei); `signatur`: (Status, Subject) als
    Attrappe oder None = die ECHTE Pruefung; `setup`: Rueckgabe des
    Installers (die Attrappe startet nichts); `pfad`: $env:Path vorher.
    -> (Ergebnis, Log-Zeilen, heruntergeladene Datei oder None)."""
    t = tempfile.mkdtemp(prefix="omcad_py_")
    _temp.append(t)
    log = os.path.join(t, "log.txt")
    if quelle is None:
        quelle = os.path.join(t, "attrappe.exe")
        with open(quelle, "wb") as fh:
            fh.write(b"MZ keine echte Datei\n")
    code = ["$log = '%s'" % log,
            "function Log($x) { Add-Content -LiteralPath $log -Value $x }",
            "function Python-Herunterladen([string]$url, [string]$ziel) {",
            "    Log ('laden|' + $url + '|' + $ziel)",
            "    if ('%s' -eq 'fehler') { throw 'Die Verbindung mit dem "
            "Remoteserver kann nicht hergestellt werden.' }" % laden,
            "    if ('%s' -eq 'leer') { return }" % laden,
            "    Copy-Item -LiteralPath '%s' -Destination $ziel" % quelle,
            "}",
            "function Python-Setup-Starten([string]$datei) {",
            "    Log ('setup|' + $datei + '|' + (Test-Path -LiteralPath "
            "$datei))",
            "    return %d" % setup,
            "}"]
    if signatur is not None:
        code += ["function Python-Signatur([string]$datei) {",
                 "    Log ('signatur|' + $datei)",
                 "    return [pscustomobject]@{ Status = '%s'; "
                 "SignerCertificate = [pscustomobject]@{ Subject = '%s' } }"
                 % signatur,
                 "}"]
    else:
        code += ["function Python-Signatur([string]$datei) {",
                 "    Log ('signatur|' + $datei)",
                 "    return (Get-AuthenticodeSignature -LiteralPath $datei)",
                 "}"]
    if pfad is not None:
        code.append("$env:Path = '%s'" % pfad)
    code += ["$r = %s" % aufruf,
             "@{ ok = $r.Ok; text = $r.Text } | ConvertTo-Json -Compress"]
    r = ps_funktionen("\n".join(code), ps1)
    zeilen = []
    if os.path.isfile(log):
        with open(log, encoding="utf-8-sig", errors="replace") as fh:
            zeilen = [z.rstrip("\r\n") for z in fh if z.strip()]
    geladen = next((z.split("|")[2] for z in zeilen
                    if z.startswith("laden|")), None)
    return r, zeilen, geladen


def _art(zeilen, art):
    return [z for z in zeilen if z.startswith(art + "|")]


def mutante_ohne(anfang, ende):
    """install.ps1 ohne den Block zwischen den Marken `anfang`/`ende`."""
    quelle = open(INSTALL, encoding="ascii").read()
    a, e = quelle.index(anfang), quelle.index(ende)
    t = tempfile.mkdtemp(prefix="omcad_mut_")
    _temp.append(t)
    ziel = os.path.join(t, "install.ps1")
    with open(ziel, "w", encoding="ascii") as fh:
        fh.write(quelle[:a] + quelle[e:])
    return ziel


def pruefe_python_rueckfall():
    import re
    quelle = open(INSTALL, encoding="ascii").read()
    werte = dict(re.findall(r'^\$(PYTHON_ORG_\w+) = "([^"]*)"', quelle,
                            re.M))
    argumente = re.search(r'^\$PYTHON_ORG_ARGUMENTE = @\(([^)]*)\)', quelle,
                          re.M)
    argumente = re.findall(r'"([^"]*)"', argumente.group(1)) \
        if argumente else []
    v = werte.get("PYTHON_ORG_VERSION", "")
    pruefe("I20 feste Version 3.10..3.13 (wie Finde-Python), URL per HTTPS "
           "auf genau diese Datei bei python.org, Benutzerbereich ohne "
           "Launcher und ohne PATH",
           re.fullmatch(r"3\.1[0-3]\.\d+", v) is not None
           and werte.get("PYTHON_ORG_URL") ==
           "https://www.python.org/ftp/python/%s/python-%s-amd64.exe" % (v, v)
           and werte.get("PYTHON_ORG_SIGNIERER") == "Python Software Foundation"
           and {"/quiet", "InstallAllUsers=0", "PrependPath=0",
                "Include_launcher=0"} <= set(argumente)
           and not any(a.endswith("=1") for a in argumente),
           (werte, argumente))

    # I20a welcher Weg: ohne winget auf dem PATH python.org, mit winget.
    leer = tempfile.mkdtemp(prefix="omcad_ohne_winget_")
    _temp.append(leer)
    mit = tempfile.mkdtemp(prefix="omcad_mit_winget_")
    _temp.append(mit)
    wlog = os.path.join(mit, "winget_aufrufe.txt")
    with open(os.path.join(mit, "winget.cmd"), "w", encoding="ascii") as fh:
        fh.write('@echo %%* >> "%s"\r\n@exit /b 0\r\n' % wlog)
    sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                         "System32")
    weg = ps_funktionen("$env:Path = '%s'\n$a = Python-Weg\n"
                        "$env:Path = '%s;%s'\n$b = Python-Weg\n"
                        "@{ ohne = $a; mit = $b; frage = (Python-Frage $a) } "
                        "| ConvertTo-Json -Compress" % (leer, mit, sys32))
    pruefe("I20a ohne winget auf dem PATH -> python.org, mit winget -> winget; "
           "die Rueckfrage nennt python.org und die Version",
           weg.get("ohne") == "python.org" and weg.get("mit") == "winget"
           and "python.org" in weg.get("frage", "")
           and werte.get("PYTHON_ORG_VERSION", "?") in weg.get("frage", ""),
           weg)

    # I20b gueltig signiert -> geladen von der festen URL, gestartet, danach
    # geloescht.
    r, z, geladen = python_org_lauf(signatur=("Valid", PSF))
    setup = _art(z, "setup")
    pruefe("I20b gueltige Signatur der PSF: geladen von der festen URL, "
           "EINMAL gestartet (die Datei lag da), danach geloescht, Ergebnis "
           "nennt Version und Pruefung",
           r.get("ok") is True and len(_art(z, "laden")) == 1
           and _art(z, "laden")[0].split("|")[1] == werte.get("PYTHON_ORG_URL")
           and len(setup) == 1 and setup[0].endswith("|True")
           and geladen and not os.path.exists(geladen)
           and v in r.get("text", "") and "Signatur" in r.get("text", ""),
           (r, z))

    # I20c ungueltig, falscher Unterzeichner -> NIE gestartet, geloescht.
    faelle = [("HashMismatch", PSF), ("NotSigned", ""),
              ("Valid", "CN=Microsoft Windows, O=Microsoft Corporation"),
              ("Valid", "CN=Jemand, O=Python Software Foundation"),
              ("Valid", "CN=Python Software Foundation Fake, O=X")]
    schlecht = []
    for status, wer in faelle:
        r, z, geladen = python_org_lauf(signatur=(status, wer))
        if not (r.get("ok") is False and not _art(z, "setup")
                and "NICHT ausgefuehrt" in r.get("text", "")
                and geladen and not os.path.exists(geladen)):
            schlecht.append((status, wer, r, z))
    pruefe("I20c ungueltige Signatur (HashMismatch, NotSigned) oder anderer "
           "Unterzeichner (auch O=PSF mit fremdem CN, aehnlicher CN): NICHT "
           "gestartet, geloescht, Grund im Ergebnis (%d Faelle)" % len(faelle),
           not schlecht, schlecht[:2])

    # I20d Download scheitert / liefert nichts -> klare Meldung, keine
    # Pruefung, kein Start.
    r, z, _g = python_org_lauf(laden="fehler")
    r2, z2, _g2 = python_org_lauf(laden="leer")
    pruefe("I20d Download scheitert: klare Meldung (Grund, python.org, was "
           "tun), nichts geprueft oder gestartet; ohne Datei ebenso",
           r.get("ok") is False and "Download von python.org ging nicht"
           in r.get("text", "") and "Remoteserver" in r.get("text", "")
           and "1_INSTALLIEREN.cmd" in r.get("text", "")
           and not _art(z, "signatur") and not _art(z, "setup")
           and r2.get("ok") is False and "keine Datei" in r2.get("text", "")
           and not _art(z2, "setup"), (r, r2))

    # I20e der Installer meldet einen Fehler -> nicht ok, Code genannt,
    # geloescht; 3010 (Neustart offen) gilt als gut.
    r, z, geladen = python_org_lauf(signatur=("Valid", PSF), setup=1603)
    r2, _z2, _g2 = python_org_lauf(signatur=("Valid", PSF), setup=3010)
    pruefe("I20e Installer meldet 1603: nicht ok, Code im Ergebnis, Datei "
           "geloescht; 3010 gilt als installiert",
           r.get("ok") is False and "1603" in r.get("text", "")
           and geladen and not os.path.exists(geladen)
           and r2.get("ok") is True, (r, r2))

    # I20f die ECHTE Signaturpruefung an echten Dateien dieses Rechners.
    psf = _psf_exe()
    t = tempfile.mkdtemp(prefix="omcad_sig_")
    _temp.append(t)
    unsigniert = os.path.join(t, "unsigniert.exe")
    with open(unsigniert, "wb") as fh:
        fh.write(b"MZ" + b"\0" * 512)
    ms = os.path.join(sys32, "WindowsPowerShell", "v1.0", "powershell.exe")
    echt = [(unsigniert, False), (ms, False)]
    if psf:
        veraendert = os.path.join(t, "veraendert.exe")
        with open(psf, "rb") as fh:
            daten = bytearray(fh.read())
        daten[len(daten) // 2] ^= 0xFF
        with open(veraendert, "wb") as fh:
            fh.write(bytes(daten))
        echt = [(psf, True), (veraendert, False)] + echt
    else:
        print("  [info] I20f: kein von der PSF signiertes Python auf diesem "
              "Rechner gefunden - nur die Ablehnungen gemessen")
    falsch = []
    for datei, soll in echt:
        r, z, geladen = python_org_lauf(quelle=datei, signatur=None)
        gestartet = bool(_art(z, "setup"))
        if (r.get("ok") is True) != soll or gestartet != soll or \
                (geladen and os.path.exists(geladen)):
            falsch.append((os.path.basename(datei), soll, r, z))
    pruefe("I20f echte Get-AuthenticodeSignature: %s, veraenderte Kopie, "
           "powershell.exe (Microsoft) und unsignierte Datei richtig "
           "entschieden" % ("PSF-Python gestartet" if psf else "ohne PSF-Python"),
           not falsch, falsch[:2])

    # I20g ganzer Weg ueber Python-Installieren: ohne winget python.org,
    # mit winget nur winget (--scope user), kein Download.
    r, z, _g = python_org_lauf(signatur=("Valid", PSF), pfad=leer,
                               aufruf="Python-Installieren (Python-Weg)")
    r2, z2, _g2 = python_org_lauf(signatur=("Valid", PSF),
                                  pfad="%s;%s" % (mit, sys32),
                                  aufruf="Python-Installieren (Python-Weg)")
    winget = open(wlog, encoding="ascii", errors="replace").read() \
        if os.path.isfile(wlog) else ""
    pruefe("I20g Python-Installieren ohne winget: python.org geladen und "
           "gestartet; mit winget: winget (--scope user), nichts geladen",
           r.get("ok") is True and len(_art(z, "laden")) == 1
           and len(_art(z, "setup")) == 1
           and r2.get("ok") is True and "winget" in r2.get("text", "")
           and not _art(z2, "laden") and "--scope user" in winget
           and "Python.Python.3.13" in winget, (r, r2, winget[:200]))

    # I20h das Ergebnis nennt Python einzeln.
    erg = ps_funktionen(
        "$z = Zusammenfassung @{ Server = 'fehlt'; ServerText = 'x'; "
        "Plugin = 'ok'; PluginText = 'y'; Profil = 'C:\\P'; Python = "
        "'Python-Installer von python.org NICHT ausgefuehrt: z' }\n"
        "$o = Zusammenfassung @{ Server = 'fehlt'; ServerText = 'x'; "
        "Plugin = 'ok'; PluginText = 'y'; Profil = 'C:\\P' }\n"
        "@{ mit = ($z.Zeilen -join \"`n\"); ohne = ($o.Zeilen -join \"`n\") }"
        " | ConvertTo-Json -Compress")
    pruefe("I20h das Ergebnis nennt Python in einer eigenen Zeile (nur wenn "
           "der Installer Python anfassen wollte)",
           "Python:         Python-Installer von python.org NICHT" in
           erg.get("mit", "") and "Python:" not in erg.get("ohne", "?"), erg)

    # KONTROLLEN, muessen anschlagen.
    mut = mutante_ohne("# PRUEFUNG-ANFANG", "# PRUEFUNG-ENDE")
    r, z, _g = python_org_lauf(signatur=("HashMismatch", PSF), ps1=mut)
    pruefe("I20-K KONTROLLE: ohne Signaturpruefung liefe ein manipulierter "
           "Installer (I20c faellt)", bool(_art(z, "setup")), (r, z))
    mut = mutante_ohne("# SIGNIERER-ANFANG", "# SIGNIERER-ENDE")
    r, z, _g = python_org_lauf(
        signatur=("Valid", "CN=Microsoft Windows, O=Microsoft Corporation"),
        ps1=mut)
    pruefe("I20-K KONTROLLE: ohne Pruefung des Unterzeichners liefe ein "
           "fremd signierter Installer", bool(_art(z, "setup")), (r, z))
    mut = mutante_ohne("# LOESCHEN-ANFANG", "# LOESCHEN-ENDE")
    r, z, geladen = python_org_lauf(signatur=("NotSigned", ""), ps1=mut)
    pruefe("I20-K KONTROLLE: ohne Loeschen bliebe der Download liegen",
           bool(geladen) and os.path.exists(geladen), (geladen, z))
    if geladen and os.path.isfile(geladen):
        os.remove(geladen)                  # die Attrappe der Mutante
    alt = ("        try {\n            Python-Herunterladen $PYTHON_ORG_URL "
           "$datei\n        } catch {")
    mut = mutante(alt, "        Python-Herunterladen $PYTHON_ORG_URL $datei\n"
                  "        if ($false) {")
    r, z, _g = python_org_lauf(laden="fehler", ps1=mut)
    pruefe("I20-K KONTROLLE: ohne das Abfangen gaebe ein gescheiterter "
           "Download keine Meldung fuer das Ergebnis",
           "Download von python.org ging nicht" not in r.get("text", ""), r)


# --- I21-I27 das Einrichtungsfenster (seit 2026-10-09) ---------------------
#
# Rueckmeldung 2026-10-09: das schwarze Fenster schreckte Laien ab. Der
# Doppelklick ohne Schalter oeffnet jetzt install_fenster.ps1 (WPF). Es
# fragt VORHER mit den Funktionen aus install.ps1 und startet dann
# install.ps1 mit den Antworten als Schalter. Gemessen OHNE ein Fenster zu
# zeigen: das XAML wird geladen, die Knoepfe bekommen ihr Click-Ereignis
# (`Klick`), die Ereignisschleife laeuft ohne Fenster (`Pumpen`), die Seiten
# werden mit RenderTargetBitmap gerendert. Jeder Kindprozess startet ohne
# Konsole (OHNE_FENSTER); Oeffnen von Seiten/Dateien und die Ablage sind
# ersetzt, das Verbergen der Konsole wirft im Gate.

def _ps_fenster(skript, env=None, sta=True, zeit=300):
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass"] + (["-STA"] if sta else ["-MTA"])
                       + ["-Command", skript], capture_output=True,
                       timeout=zeit, env=env, creationflags=OHNE_FENSTER)
    aus = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    zeilen = [z for z in aus.splitlines() if z.strip()]
    try:
        return json.loads(zeilen[-1]), aus
    except Exception:                                     # noqa: BLE001
        return {"_fehler": aus[-1500:], "_rc": r.returncode}, aus


def _ps_text(s):
    return "'" + str(s).replace("'", "''") + "'"


def fenster_lauf(wurzel, programm, schritte="", vorher="", env=None,
                 ohne_server=False, fenster=None, protokoll=None, aus="",
                 sprache="de", texte=None, schalter=""):
    """Das Fenster (oder eine Mutante `fenster`) ohne es zu zeigen: bauen,
    verdrahten, Willkommen, pruefen wie beim Start; dann `schritte`
    (PowerShell, `K 'knopf'` klickt und merkt die Seite). `vorher`:
    Ersatz-Funktionen (etwa Finde-Python). `sprache`: -Sprache (Vorgabe
    de, damit die deutschen Saetze unten nicht von der Anzeigesprache des
    Rechners abhaengen; "" = die von Windows). `texte`: -TexteDatei.
    -> (JSON, Text)."""
    assert wurzel.startswith(tempfile.gettempdir())
    assert programm.startswith(tempfile.gettempdir())
    if protokoll is None:
        t = tempfile.mkdtemp(prefix="omcad_fprot_")
        _temp.append(t)
        protokoll = os.path.join(t, "installer.log")
    skript = "\n".join([
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false",
        ". %s -NurFunktionen -CadworkWurzel %s -CadworkProgramm %s "
        "-Protokoll %s%s%s%s%s" % (
            _ps_text(fenster or FENSTER), _ps_text(wurzel),
            _ps_text(programm), _ps_text(protokoll),
            " -OhneServer" if ohne_server else "",
            " -Sprache %s" % _ps_text(sprache) if sprache else "",
            " -TexteDatei %s" % _ps_text(texte) if texte else "", schalter),
        "Wpf-Laden",
        "$global:urls = @()",
        "function Url-Oeffnen($u) { $global:urls += @($u) }",
        "function Datei-Oeffnen($p) { $global:urls += @('datei:' + $p) }",
        "function Ablage-Setzen($t) { $global:ablage = $t }",
        "function Konsole-Fenster($w) { throw 'Konsole im Gate angefasst' }",
        vorher,
        "$U = Fenster-Bauen; $S = Zustand-Neu; Verdrahten $U $S",
        "Seite-Zeigen $U $S 'willkommen'",
        "$global:vor = (El $U 'willkommen_weiter').IsEnabled",
        "Lage-Pruefen $S; Willkommen-Fuellen $U $S",
        "$global:v = @($S.Seite)",
        "function K($n) { Klick $U $n; $global:v += $S.Seite }",
        # "Nochmal suchen" sucht seit 2026-10-10 im Hintergrund: warten.
        "function KN($n) { Klick $U $n; $null = Pumpen { -not $S.Suche } 30;"
        " $global:v += $S.Seite }",
        # Willkommen, dann "In deiner KI-App" (die Faelle vor der Seite "wo")
        "function KW { K 'willkommen_weiter'; (El $U 'wo_app').IsChecked = $true; K 'wo_weiter' }",
        schritte,
        "$haken = @{}",
        "foreach ($id in $KI_PROGRAMME) { $c = El $U ('ki_' + $id); "
        "$haken[$id] = @($c.IsEnabled, ($c.IsChecked -eq $true)) }",
        "@{ v = $global:v; seite = $S.Seite; rc = $S.Rc; urls = $global:urls;"
        " args = (Fenster-Argumente (Wahl-Aus-Zustand $S 'E'));"
        " haken = $haken; vor = $global:vor; ablage = $global:ablage;"
        " code_karte = ((El $U 'ki_karte_claude_code').Visibility -eq 'Visible');"
        " fehler = $S.FehlerSchluessel; python_weg = (El $U 'python_weg').Text;"
        " fertig_ki = (El $U 'fertig_ki').Text; schritt = $S.Schritt;"
        " aus = (%s) } | ConvertTo-Json -Compress -Depth 5" % (aus or "$null"),
    ])
    return _ps_fenster(skript, env=env)


def _wert(args, schalter):
    """Der Wert hinter `schalter` in einer Argumentliste (oder None)."""
    return args[args.index(schalter) + 1] if schalter in args else None


def _welt_env(w):
    """Die Umgebung einer ki_welt, aber mit dem Rest des Systems (WPF)."""
    env = dict(os.environ)
    env.pop("CODEX_HOME", None)
    env.update({k: w["env"][k] for k in ("USERPROFILE", "HOME", "APPDATA",
                                         "LOCALAPPDATA", "PATH", "TEMP",
                                         "TMP")})
    return env


def ki_vorschau(w, ps1=None):
    """KI-Finden aus install.ps1 in der Welt `w`. -> Liste der ids."""
    skript = (". '%s' -NurFunktionen\n$l = KI-Finden\n@{ p = @($l | "
              "ForEach-Object { $_.programm }) } | ConvertTo-Json -Compress"
              % (ps1 or INSTALL))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", skript], capture_output=True,
                       timeout=120, env=w["env"], cwd=w["t"],
                       creationflags=OHNE_FENSTER)
    aus = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    try:
        p = json.loads([z for z in aus.splitlines() if z.strip()][-1])["p"]
    except Exception:                                     # noqa: BLE001
        return "kaputt: " + aus[-300:]
    return [p] if isinstance(p, str) else list(p or [])


def pruefe_fenster():
    import importlib
    import re
    KE = importlib.import_module("open_mcp_cad.ki_eintragen")

    # --- I21 KI-Finden (PowerShell, vor der Installation) == finden() -----
    welten = {"alle drei": ki_welt(), "leer": ki_welt(programme=()),
              "nur .codex": ki_welt(programme=("codex",), codex=None),
              "claude.exe, Umlaut-Heim": ki_welt(programme=("claude_code",),
                                                 heim_name="Jürg Müller",
                                                 claude="exe")}
    # Die ChatGPT-Desktop-App mit Codex (frueher "Codex-App"): ihr Store-
    # Paket, wie am Rechner des Maintainers gemessen (CHATGPT_PAKET).
    w = ki_welt(programme=())
    os.makedirs(os.path.join(w["local"], "Packages", CHATGPT_PAKET))
    welten["nur ChatGPT-App mit Codex (Store-Paket)"] = w
    # Ein anderes OpenAI-Paket (etwa eine aeltere ChatGPT-App; der Name
    # hier ist ein Beispiel, NICHT gemessen) zaehlt in beiden nicht.
    w = ki_welt(programme=())
    os.makedirs(os.path.join(w["local"], "Packages",
                             "OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0"))
    welten["anderes OpenAI-Paket"] = w
    w = ki_welt(programme=())
    os.makedirs(os.path.join(w["local"], "Packages", "Claude_pzs8sxrjxfjjc",
                             "LocalCache", "Roaming", "Claude"))
    welten["nur Claude Desktop (Store)"] = w
    w = ki_welt(programme=())
    os.makedirs(os.path.join(w["local"], "Packages", "Claude_pzs8sxrjxfjjc"))
    welten["Store-Ordner Claude ohne Einstellungen"] = w
    w = ki_welt(programme=())
    with open(os.path.join(w["bin"], "codex.cmd"), "w") as fh:
        fh.write("@exit /b 0\r\n")
    welten["codex.cmd auf dem PATH"] = w
    w = ki_welt(programme=())
    os.makedirs(os.path.join(w["appdata"], "npm"))
    with open(os.path.join(w["appdata"], "npm", "claude.cmd"), "w") as fh:
        fh.write("@exit /b 0\r\n")
    welten["claude.cmd unter APPDATA\\npm"] = w
    anders = {}
    for titel, w in welten.items():
        soll = [p["programm"] for p in KE.finden(w["env"])]
        ist = ki_vorschau(w)
        if soll != ist:
            anders[titel] = (soll, ist)
    pruefe("I21 KI-Finden (PowerShell, fuer das Fenster vor der Installation) "
           "== ki_eintragen.finden() in %d Welten" % len(welten), not anders,
           anders)
    mut = mutante_ps(" -or $app.Count -gt 0)", ")")
    k = ki_vorschau(welten["nur ChatGPT-App mit Codex (Store-Paket)"], mut)
    pruefe("I21-K KONTROLLE: ohne den Store-Ordner fehlte die ChatGPT-App mit "
           "Codex in der Vorschau", k == [], k)
    gef = {t: [p["programm"] for p in KE.finden(welten[t]["env"])]
           for t in ("nur ChatGPT-App mit Codex (Store-Paket)",
                     "anderes OpenAI-Paket")}
    pruefe("I21c das gemessene Store-Paket der ChatGPT-App (%s) gilt als "
           "Codex, ein anderes OpenAI-Paket nicht" % CHATGPT_PAKET,
           gef == {"nur ChatGPT-App mit Codex (Store-Paket)": ["codex"],
                   "anderes OpenAI-Paket": []}, gef)
    # Live, nur lesend: ist hier eine App mit dem Startmenue-Namen
    # "ChatGPT" installiert, muss ihr Paket unter das Muster fallen.
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command",
                        "@(Get-StartApps | Where-Object { $_.Name -eq "
                        "'ChatGPT' } | ForEach-Object { $_.AppID }) -join "
                        "';'"], capture_output=True, timeout=120,
                       creationflags=OHNE_FENSTER)
    ids = [i for i in r.stdout.decode("utf-8", "replace").strip().split(";")
           if i]
    if ids:
        import fnmatch
        pruefe("I21d live: die installierte ChatGPT-App (%s) faellt unter "
               "OpenAI.Codex_*" % ", ".join(ids),
               all(fnmatch.fnmatch(i.split("!")[0], "OpenAI.Codex_*")
                   for i in ids), ids)
    else:
        print("  [info] I21d: keine App 'ChatGPT' im Startmenue dieses "
              "Rechners - live nicht gemessen")

    # --- I21b -KiNur: genau die gewaehlten Programme, ohne Frage ---------
    w = ki_welt()
    vorher = _stand(w)
    skript = (". '%s' -NurFunktionen\n"
              "$r = KI-Programme-Eintragen '%s' '%s' (KI-Nur-Frage "
              "'claude_desktop,codex') $false\n"
              "@{ zeilen = @($r | ForEach-Object { $_.Name + '|' + $_.Status })"
              " } | ConvertTo-Json -Compress" % (INSTALL, w["helfer"],
                                                 w["server"]))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", skript], capture_output=True,
                       timeout=300, env=w["env"], cwd=w["t"],
                       creationflags=OHNE_FENSTER)
    aus = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    try:
        erg = json.loads([z for z in aus.splitlines() if z.strip()][-1])
    except Exception:                                     # noqa: BLE001
        erg = {"_fehler": aus[-500:]}
    neu = _stand(w)
    pruefe("I21b -KiNur claude_desktop,codex: diese beiden eingetragen, Claude "
           "Code abgelehnt (claude nie mit add gerufen), keine Frage gestellt",
           erg.get("zeilen") == ["Codex|eingetragen", "Claude Code|abgelehnt",
                                 "Claude Desktop|eingetragen"]
           and not [a for a in neu["aufrufe"] if a[:2] == ["mcp", "add"]]
           and neu["codex"] != vorher["codex"]
           and neu["desktop"] != vorher["desktop"]
           and "eintragen? [J/n]" not in aus, (erg, aus[-400:]))

    # --- I22 reine Teile: Argumente, Quoting, Schritt, Fehlersatz --------
    t = tempfile.mkdtemp(prefix="omcad_argv_")
    _temp.append(t)
    echo = os.path.join(t, "argv.py")
    with open(echo, "w", encoding="utf-8") as fh:
        fh.write("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    proben = ["a b", 'x"y', "ende\\", "C:\\Pfad mit Leer\\", "Jürg & (1) %x%",
              "", "a\\\\\"b", "ohne", "-KiNur", "codex,claude_desktop"]
    skript = (". '%s' -NurFunktionen\n"
              "$p = @(%s)\n"
              "$si = New-Object System.Diagnostics.ProcessStartInfo '%s'\n"
              "$si.Arguments = (@('%s') + @($p) | ForEach-Object { Arg-Text $_ })"
              " -join ' '\n"
              "$si.UseShellExecute = $false; $si.RedirectStandardOutput = $true\n"
              "$x = [Diagnostics.Process]::Start($si); $o = "
              "$x.StandardOutput.ReadToEnd(); $x.WaitForExit()\n"
              "@{ o = $o.Trim() } | ConvertTo-Json -Compress"
              % (FENSTER, ",".join(_ps_text(p) for p in proben),
                 sys.executable, echo))
    r, aus = _ps_fenster(skript)
    try:
        zurueck = json.loads(r.get("o", "null"))
    except ValueError:
        zurueck = r
    pruefe("I22 Arg-Text: %d Argumente (Leerzeichen, \", \\ am Ende, Umlaut, "
           "&, Klammern, %%, leer) kommen im Kindprozess woertlich an"
           % len(proben), zurueck == proben, (zurueck, aus[-300:]))
    r, aus = _ps_fenster(
        ". '%s' -NurFunktionen\n"
        "@{ s = @((Schritt-Aus-Zeile '== 3/5 MCP-Server einrichten'), "
        "(Schritt-Aus-Zeile '== Ergebnis'), (Schritt-Aus-Zeile 'x == 2/5 y'), "
        "(Schritt-Aus-Zeile '== 6/6 KI fuer den Chat'));"
        " f = @((Fehler-Schluessel $null), (Fehler-Schluessel @{ plugin='fehlt'"
        "; server=$null }), (Fehler-Schluessel @{ plugin='ok'; server='fehlt';"
        " serverText='Kein Python 3.10 bis 3.13 gefunden.' }), "
        "(Fehler-Schluessel @{ plugin='ok'; server='fehlt'; serverText="
        "'pip install des Servers ist fehlgeschlagen (Internet?).' }), "
        "(Fehler-Schluessel @{ plugin='version'; server='ok' }));"
        " g = @((Lauf-Gut 0 @{ fertig = $true }), (Lauf-Gut 3 @{ fertig = "
        "$true }), (Lauf-Gut 0 @{ fertig = $false }), (Lauf-Gut 0 $null)) }"
        " | ConvertTo-Json -Compress" % FENSTER)
    pruefe("I22 Schritt aus '== n/5', Fehlersatz je Lage (unerwartet, Plugin, "
           "Python, Internet, Version), gut nur mit 0 UND fertig",
           r.get("s") == [3, 0, 0, 6] and r.get("f") == [
               "t_fehler_unerwartet", "t_fehler_plugin", "t_fehler_python",
               "t_fehler_server", "t_fehler_version"]
           and r.get("g") == [True, False, False, False], (r, aus[-300:]))
    # Jeder Schluessel, den das Skript fuer einen Text nennt, steht in der
    # Textdatei (seit 2026-10-10 dort statt in der XAML; aus der Quelle
    # gelesen); jedes Teil, das es sucht, steht in der XAML.
    quelle = open(FENSTER, encoding="ascii").read()
    xaml = open(FENSTER_XAML, encoding="utf-8").read()
    _sp, schluessel, _gl = P.fenster_texte()
    texte = set(re.findall(r'"(t_[a-z_]+)"', quelle))
    texte |= {"t_name_" + i for i in re.findall(
        r'\$KI_PROGRAMME = @\(([^)]*)\)', quelle)[0].replace('"', "").replace(
            " ", "").split(",")}
    fehlt = sorted(x for x in texte if not x.endswith("_")
                   and x not in schluessel)
    teile = set(re.findall(r'El \$(?:F\.)?U "([a-z_0-9]+)"', quelle))
    teile |= {"Seite_" + s for s in re.findall(
        r'\$SEITEN = @\(([^)]*)\)', quelle)[0].replace('"', "").replace(
            " ", "").split(",")}
    teile_fehlt = sorted(x for x in teile if 'x:Name="%s"' % x not in xaml)
    pruefe("I22 jeder Text (%d) und jedes Teil (%d), das install_fenster.ps1 "
           "nennt, steht in der Textdatei bzw. der XAML; das Skript ist reines "
           "ASCII"
           % (len(texte), len(teile)),
           not fehlt and not teile_fehlt and len(texte) > 20
           and all(ord(c) < 128 for c in quelle), (fehlt, teile_fehlt))

    # --- I23 der Ablauf im Fenster (ohne es zu zeigen) ---------------------
    py_da = "function Finde-Python { return , @('python') }"
    py_fehlt = ("function Finde-Python { return $null }\n"
                "function Python-Weg { return 'python.org' }")
    welt = ki_welt(programme=("codex", "claude_desktop"))
    env = _welt_env(welt)
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    pfad26 = os.path.join(w, "userprofil_2026", "3d", "API.x64")
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'",
                          vorher=py_da, env=env)
    a = r.get("args") or []
    pruefe("I23a Normalfall (ein Profil 2026, Python da, Codex + Claude "
           "Desktop gefunden): Willkommen -> KI-App -> Bereit; beide "
           "angehakt, Claude Code (nicht gefunden) mit Karte und 'Holen' "
           "(seit 2026-10-10); Argumente: -Profil 2026, "
           "-KiNur claude_desktop,codex, -OhnePause, kein -TrotzdemKopieren "
           "und kein -PythonInstallieren; 'Los geht's' erst nach dem Pruefen",
           r.get("v") == ["willkommen", "wo", "ki", "bereit"]
           and r.get("haken") == {"claude_desktop": [True, True],
                                  "codex": [True, True],
                                  "claude_code": [False, False]}
           and r.get("code_karte") is True and r.get("vor") is False
           and _wert(a, "-Profil") == pfad26
           and _wert(a, "-KiNur") == "claude_desktop,codex"
           and "-OhnePause" in a and "-Utf8Ausgabe" in a
           and _wert(a, "-File") == os.path.join(P.VERTEILUNG, "install.ps1")
           and "-TrotzdemKopieren" not in a and "-PythonInstallieren" not in a
           and "-OhneKiEintrag" not in a, (r, aus[-600:]))
    r, aus = fenster_lauf(w, p, "KW; K 'ki_codex'; "
                          "K 'ki_weiter'", vorher=py_da, env=env)
    pruefe("I23a2 Codex abgewaehlt -> -KiNur nur claude_desktop",
           _wert(r.get("args") or [], "-KiNur") == "claude_desktop"
           and r.get("v") == ["willkommen", "wo", "ki", "ki", "bereit"],
           (r, aus[-400:]))
    r, aus = fenster_lauf(w, p, "KW; K 'ki_codex'; "
                          "K 'ki_claude_desktop'", vorher=py_da, env=env,
                          aus="(El $U 'ki_weiter').IsEnabled")
    pruefe("I23a3 nichts angehakt -> 'Weiter' gesperrt",
           r.get("aus") is False and r.get("seite") == "ki"
           and r.get("haken", {}).get("codex") == [True, False], (r, aus[-300:]))
    zu = ("$global:zu = $false; $U.W.Add_Closed({ $global:zu = $true })")
    # Die Warnung gilt einer NICHT erlaubten Version: ALT_JAHR (das Jahr vor
    # $CADWORK_ERLAUBT_AB aus der Quelle, seit 2026-10-10: 2024).
    alt = "userprofil_%d" % ALT_JAHR
    t, w, p = attrappe(["userprofil_2026", alt], ["2026", str(ALT_JAHR)])
    pfad_alt = os.path.join(w, alt, "3d", "API.x64")
    # Seit 2026-10-10 Haken statt einer Wahl: 2026 (vorab angehakt) ab-,
    # ALT_JAHR anhaken - dann gilt NUR dieses (wie vorher die eine Wahl).
    r, aus = fenster_lauf(
        w, p, "KW; K 'ki_weiter'; "
        "(El $U 'profil_wahl_1').IsChecked = $true; "
        "(El $U 'profil_wahl_0').IsChecked = $false; K 'profil_weiter'; "
        "K 'version_trotzdem'", vorher=py_da, env=env)
    a = r.get("args") or []
    pruefe("I23b zwei Profile: Seite 'Welches Cadwork?', nur %d angehakt -> "
           "Warnung, 'Trotzdem installieren' -> Bereit; Argumente -Profil %d "
           "(kein -Profile) und -TrotzdemKopieren" % (ALT_JAHR, ALT_JAHR),
           r.get("v") == ["willkommen", "wo", "ki", "profil", "version", "bereit"]
           and _wert(a, "-Profil") == pfad_alt and "-Profile" not in a
           and "-TrotzdemKopieren" in a,
           (r, aus[-500:]))
    t, w, p = attrappe([alt], [str(ALT_JAHR)])
    r, aus = fenster_lauf(w, p, zu + "\nKW; K 'ki_weiter';"
                          " Klick $U 'version_schliessen'", vorher=py_da,
                          env=env, aus="$global:zu")
    pruefe("I23c nur Cadwork %d: die Warnung kommt, 'Schliessen' schliesst, "
           "nichts gestartet, Rueckgabe 3" % ALT_JAHR,
           r.get("v") == ["willkommen", "wo", "ki", "version"] and r.get("aus") is True
           and r.get("rc") == 3, (r, aus[-400:]))
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'; "
                          "K 'python_ja'", vorher=py_fehlt, env=env)
    pruefe("I23d Python fehlt: Seite 'Ein Programmteil fehlt noch' nennt den "
           "Weg (python.org, Unterschrift), 'Mitinstallieren' -> Bereit, "
           "Argument -PythonInstallieren",
           r.get("v") == ["willkommen", "wo", "ki", "python", "bereit"]
           and "python.org" in (r.get("python_weg") or "")
           and "Unterschrift" in (r.get("python_weg") or "")
           and "-PythonInstallieren" in (r.get("args") or []), (r, aus[-400:]))
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'",
                          vorher=py_fehlt, env=env, ohne_server=True)
    pruefe("I23d2 Python fehlt, aber -OhneServer: keine Python-Seite",
           r.get("v") == ["willkommen", "wo", "ki", "bereit"]
           and "-PythonInstallieren" not in (r.get("args") or []),
           (r, aus[-300:]))
    leer = ki_welt(programme=())
    env_leer = _welt_env(leer)
    codex_ordner = os.path.join(leer["heim"], ".codex")
    r, aus = fenster_lauf(
        w, p, "KW; K 'keine_claude'; K 'keine_codex'; "
        "New-Item -ItemType Directory -Path %s | Out-Null; KN 'keine_nochmal';"
        " K 'ki_weiter'" % _ps_text(codex_ordner), vorher=py_da, env=env_leer)
    pruefe("I23e keine KI-App: 'Du brauchst zuerst eine KI-App', die zwei "
           "Knoepfe oeffnen die offiziellen Seiten (Anthropic, Microsoft "
           "Store); nach dem Installieren findet 'Nochmal suchen' sie und "
           "hakt sie an",
           r.get("v") == ["willkommen", "wo", "ki_keine", "ki_keine", "ki_keine",
                          "ki", "bereit"]
           and r.get("urls") == ["https://claude.com/download",
                                 "https://apps.microsoft.com/detail/"
                                 "9PLM9XGG6VKS"]
           and _wert(r.get("args") or [], "-KiNur") == "codex",
           (r, aus[-500:]))
    leer = ki_welt(programme=())
    r, aus = fenster_lauf(w, p, "KW; K 'keine_ohne'",
                          vorher=py_da, env=_welt_env(leer))
    pruefe("I23f 'Ohne KI-App weiter' -> Bereit, Argument -OhneKiEintrag",
           r.get("v") == ["willkommen", "wo", "ki_keine", "bereit"]
           and "-OhneKiEintrag" in (r.get("args") or [])
           and "-KiNur" not in (r.get("args") or []), (r, aus[-300:]))
    t, w0, p0 = attrappe([], ["2026"])
    r, aus = fenster_lauf(w0, p0, "KW; K 'ki_weiter'",
                          vorher=py_da, env=env)
    pruefe("I23g kein Cadwork-Profil: Fehlerseite mit dem Satz dafuer, "
           "Rueckgabe 3", r.get("v") == ["willkommen", "wo", "ki", "fehler"]
           and r.get("fehler") == "t_fehler_profil" and r.get("rc") == 3,
           (r, aus[-300:]))
    # KONTROLLEN: Mutanten von install_fenster.ps1 MUESSEN auffallen.
    q = open(FENSTER, encoding="ascii").read()

    def fmut(alt, neu):
        assert q.count(alt) == 1, alt
        d = tempfile.mkdtemp(prefix="omcad_fmut_")
        _temp.append(d)
        for n in (P.FENSTER_XAML, P.FENSTER_TEXTE):
            shutil.copy(os.path.join(P.VERTEILUNG, n), os.path.join(d, n))
        shutil.copy(INSTALL, os.path.join(d, "install.ps1"))
        ziel = os.path.join(d, P.FENSTER)
        with open(ziel, "w", encoding="ascii") as fh:
            fh.write(q.replace(alt, neu))
        return ziel
    t, w, p = attrappe(["userprofil_%d" % ALT_JAHR], [str(ALT_JAHR)])
    k1, _a = fenster_lauf(w, p, "KW; K 'ki_weiter'",
                          vorher=py_da, env=env, fenster=fmut(
                              '"version" { return ($S.Version -and',
                              '"version" { return ($false -and'))
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    k2, _a = fenster_lauf(w, p, "KW; K 'ki_codex'; "
                          "K 'ki_weiter'", vorher=py_da, env=env, fenster=fmut(
                              "else { @($S.KiWahl) }", "else { @($S.KiGefunden) }"))
    k3, _a = fenster_lauf(w, p, "KW; K 'ki_weiter'",
                          vorher=py_fehlt, env=env, fenster=fmut(
                              '"python"  { return ($S.PythonFehlt',
                              '"python"  { return ($false'))
    pruefe("I23-K KONTROLLEN: ohne Versionswarnung kaeme Cadwork %d ohne "
           "Frage auf 'Bereit' (I23c), ohne die Wahl ginge Codex trotz "
           "Abwahl mit (I23a2), ohne Python-Seite fehlte -PythonInstallieren "
           "(I23d)" % ALT_JAHR,
           k1.get("v") == ["willkommen", "wo", "ki", "bereit"]
           and "codex" in (_wert(k2.get("args") or [], "-KiNur") or "")
           and "-PythonInstallieren" not in (k3.get("args") or ["-Python"
                                                                "Installieren"]),
           (k1.get("v"), k2.get("args"), k3.get("args")))

    # --- I24 der ganze Weg: Fenster -> install.ps1 (Kindprozess) ----------
    # Im Paket unter einem Pfad mit Leerzeichen, Umlaut, & und Klammern;
    # das Cadwork-Profil unter einem Heim "Jürg Müller" (UTF-8 bis ins
    # Protokoll). Mit -OhneServer: kein pip, kein Internet.
    ps1 = paket_attrappe(name="Open MCP CAD (1) & Jürg Müller", fenster=True)
    fenster = os.path.join(os.path.dirname(ps1), P.FENSTER)
    t = tempfile.mkdtemp(prefix="omcad_kette_")
    _temp.append(t)
    w = os.path.join(t, "Jürg Müller", "cadwork")
    p = os.path.join(t, "cadwork.dir")
    os.makedirs(os.path.join(w, "userprofil_2026", "3d", "API.x64"))
    os.makedirs(os.path.join(p, "EXE_2026"))
    prot = os.path.join(t, "installer.log")
    warten = ("$global:ok = Pumpen { $S.Seite -eq 'fertig' -or $S.Seite -eq "
              "'fehler' } 240")
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'; "
                          "K 'bereit_installieren'; " + warten + "; "
                          "$global:v += $S.Seite; K 'fertig_anleitung'",
                          vorher=py_da, env=env,
                          ohne_server=True, fenster=fenster, protokoll=prot,
                          aus="$global:ok")
    log = open(prot, encoding="utf-8").read() if os.path.isfile(prot) else ""
    pruefe("I24 Fenster -> 'Installieren' -> install.ps1 im Kindprozess: "
           "Plugin kopiert, Seite 'Fertig', Rueckgabe 0; das Protokoll hat "
           "die Schritte und den Umlaut-Pfad unverstuemmelt",
           r.get("aus") is True and r.get("v") == [
               "willkommen", "wo", "ki", "bereit", "laeuft", "fertig", "fertig"]
           and r.get("rc") == 0 and kopiert_in(w) == ["userprofil_2026"]
           and "== 1/5" in log and "== 2/5" in log
           and "Plugin: " + os.path.join(w, "userprofil_2026", "3d",
                                         "API.x64", "Open MCP CAD") in log
           and "Rueckgabe des Installers: 0" in log
           # "Anleitung oeffnen": die Anleitung oben im Paket
           and r.get("urls") == ["datei:" + os.path.join(os.path.dirname(
               os.path.dirname(ps1)), P.ANLEITUNG_OBEN[0][1] + ".pdf")],
           (r, kopiert_in(w), log[-700:], aus[-500:]))
    t2 = tempfile.mkdtemp(prefix="omcad_kette_")
    _temp.append(t2)
    w2, p2 = os.path.join(t2, "cadwork"), os.path.join(t2, "cadwork.dir")
    os.makedirs(os.path.join(w2, "userprofil_%d" % ALT_JAHR, "3d",
                             "API.x64"))
    os.makedirs(os.path.join(p2, "EXE_%d" % ALT_JAHR))
    r2, aus2 = fenster_lauf(w2, p2, "KW; K 'ki_weiter'; "
                            "K 'version_trotzdem'; K 'bereit_installieren'; "
                            + warten + "; $global:v += $S.Seite; "
                            "K 'fehler_kopieren'", vorher=py_da, env=env,
                            ohne_server=True, fenster=fenster,
                            aus="$global:ok")
    pruefe("I24b Cadwork %d 'trotzdem': kopiert, aber Fehlerseite mit dem "
           "Satz zur Version, Rueckgabe 3 (wie das Textfenster)" % ALT_JAHR,
           r2.get("v", [])[-1:] == ["fehler"] and r2.get("rc") == 3
           and r2.get("fehler") == "t_fehler_version"
           and kopiert_in(w2) == ["userprofil_%d" % ALT_JAHR]
           # "Details kopieren": das ganze Protokoll in die Ablage
           and "== 2/5" in (r2.get("ablage") or "")
           and "NICHT vollstaendig" in (r2.get("ablage") or ""),
           (r2, aus2[-500:]))
    # KONTROLLEN: ohne -Utf8Ausgabe kaeme der Umlaut verstuemmelt ins
    # Protokoll, ohne -ErgebnisDatei stuende trotz Erfolg die Fehlerseite.
    qf = open(fenster, encoding="ascii").read()

    def kette_mut(alt, neu):
        assert qf.count(alt) == 1, alt
        ziel = os.path.join(os.path.dirname(fenster), "mut_" + P.FENSTER)
        with open(ziel, "w", encoding="ascii") as fh:
            fh.write(qf.replace(alt, neu))
        return ziel

    def kette(mut):
        t = tempfile.mkdtemp(prefix="omcad_kette_")
        _temp.append(t)
        wk = os.path.join(t, "Jürg Müller", "cadwork")
        pk = os.path.join(t, "cadwork.dir")
        os.makedirs(os.path.join(wk, "userprofil_2026", "3d", "API.x64"))
        os.makedirs(os.path.join(pk, "EXE_2026"))
        pr = os.path.join(t, "installer.log")
        r, _a = fenster_lauf(wk, pk, "KW; K 'ki_weiter'; "
                             "K 'bereit_installieren'; " + warten,
                             vorher=py_da, env=env, ohne_server=True,
                             fenster=mut, protokoll=pr)
        lg = open(pr, encoding="utf-8").read() if os.path.isfile(pr) else ""
        return r, lg, wk
    rk1, lg1, wk1 = kette(kette_mut('"-OhnePause", "-Utf8Ausgabe")',
                                    '"-OhnePause")'))
    rk2, _lg2, _w = kette(kette_mut(
        'if ($W.ErgebnisDatei) { $a += @("-ErgebnisDatei", $W.ErgebnisDatei) }',
        ''))
    pruefe("I24-K KONTROLLEN: ohne -Utf8Ausgabe fehlte der Umlaut-Pfad im "
           "Protokoll, ohne -ErgebnisDatei kaeme trotz Erfolg die Fehlerseite",
           "Plugin: " + os.path.join(wk1, "userprofil_2026") not in lg1
           and "== 2/5" in lg1 and rk2.get("seite") == "fehler",
           (lg1[-300:], rk2.get("seite")))

    pruefe_fenster_chat(env, py_da, py_fehlt, fmut)

    # --- I31 vier Sprachen, I32 das alte Plugin (seit 2026-10-10) -------
    pruefe_sprachen(env, py_da)
    pruefe_alte_version(env, py_da)
    pruefe_kopieren_details(env, py_da)
    pruefe_wahl_suche_zurueck(env, py_da)
    pruefe_logos(env, py_da)
    pruefe_versionen(env, py_da)
    pruefe_mehrere_profile(env, py_da)

    # --- I25 -ErgebnisDatei: der Stand fuer das Fenster ------------------
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    datei = os.path.join(t, "ergebnis.json")
    rc, aus = installer(w, p, "-ErgebnisDatei", datei)
    erg = json.load(open(datei, encoding="utf-8")) \
        if os.path.isfile(datei) else {}
    t, w, p = attrappe(["userprofil_%d" % ALT_JAHR], [str(ALT_JAHR)])
    datei2 = os.path.join(t, "ergebnis.json")
    rc2, _aus = installer(w, p, "-ErgebnisDatei", datei2)
    erg2 = json.load(open(datei2, encoding="utf-8")) \
        if os.path.isfile(datei2) else {}
    pruefe("I25 -ErgebnisDatei: Stand als JSON - fertig/plugin/server und "
           "die Zeilen des Ergebnisses; im Abbruch der Grund in 'fehler'",
           rc == 0 and erg.get("fertig") is True and erg.get("plugin") == "ok"
           and erg.get("server") == "uebersprungen"
           and any("Beide Teile" in z or "Plugin ist installiert" in z
                   for z in erg.get("zeilen", []))
           and rc2 == 3 and erg2.get("fertig") is False
           and erg2.get("plugin") == "fehlt"
           and "Cadwork %d" % ALT_JAHR in (erg2.get("fehler") or ""),
           (erg, erg2))

    # --- I26 die Seiten als Bilder, ohne Fenster -------------------------
    bilder = tempfile.mkdtemp(prefix="omcad_seiten_")
    _temp.append(bilder)
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-STA",
                        "-ExecutionPolicy", "Bypass", "-File", FENSTER,
                        "-Rendern", bilder], capture_output=True, timeout=300,
                       creationflags=OHNE_FENSTER)
    try:
        seiten = json.load(open(os.path.join(bilder, "seiten.json"),
                                encoding="utf-8"))
    except (OSError, ValueError):
        seiten = {}
    seiten_q = re.findall(r'\$SEITEN = @\(([^)]*)\)', quelle)[0].replace(
        '"', "").replace(" ", "").split(",")
    # dazu die Bilder der Seite "laeuft" mit Unterzeile und die weiteren
    # Lagen (seit 2026-10-10; aus der Quelle)
    seiten_q += re.findall(r'(?m)^    (laeuft_\w+) += @\(', quelle)
    weitere = re.findall(r'(?m)^    (\w+) += "\w+"$', quelle.split(
        "$WEITERE_BILDER = [ordered]@{", 1)[1].split("}", 1)[0])
    seiten_q += weitere

    def png_masse(pfad):
        import struct
        try:
            with open(pfad, "rb") as fh:
                kopf = fh.read(24)
        except OSError:
            return None
        return struct.unpack(">II", kopf[16:24]) if kopf[:4] == b"\x89PNG" \
            else None
    masse = {s: png_masse(os.path.join(bilder, "fenster-%s.png" % s))
             for s in seiten_q}
    pruefe("I26 -Rendern: jede Seite und Lage (%d) als PNG in doppelter "
           "Aufloesung (1280x960), seiten.json mit den Teilen fuer die Marken "
           "der Anleitung" % len(seiten_q),
           r.returncode == 0 and set(seiten) == set(seiten_q)
           and all(m == (1280, 960) for m in masse.values())
           and {"ki_claude_desktop", "ki_codex", "ki_weiter"}
           <= set(seiten.get("ki", {}).get("ziele", {}))
           and "bereit_installieren" in seiten.get("bereit", {}).get(
               "ziele", {})
           and "fertig_schritte" in seiten.get("fertig", {}).get("ziele", {})
           and {"wo_app", "wo_chat", "wo_beides", "wo_weiter"}
           <= set(seiten.get("wo", {}).get("ziele", {}))
           and {"chat_claude", "chat_codex", "chat_spaeter"}
           <= set(seiten.get("chat_ki", {}).get("ziele", {}))
           and "anmelden_los" in seiten.get("anmelden", {}).get("ziele", {})
           and "willkommen_kopieren" in seiten.get("willkommen", {}).get(
               "ziele", {})
           and any("numpy" in x for x in seiten.get("laeuft_pip", {}).get(
               "texte", []))
           and "bereit_alt_haken" in seiten.get("bereit_alt", {}).get(
               "ziele", {})
           and "bereit_alt" not in seiten.get("bereit", {}).get("ziele", {})
           # seit 2026-10-10: die Haken der Seite "Welches Cadwork?" (zwei
           # Profile, beide angehakt) und die Lagen mit zwei Cadwork
           and {"profil_wahl_0", "profil_wahl_1", "profil_weiter"}
           <= set(seiten.get("profil", {}).get("ziele", {}))
           and len(seiten_q) == 23 and len(weitere) == 8,
           (r.returncode, masse, r.stderr[-300:]))
    # Was man sieht: keine Pfade (ausser dem Protokoll auf der Fehlerseite),
    # keine Fachwoerter (Python nur auf der Seite, die es mitinstalliert).
    fach = re.compile(r"(?<![\w-])(API|MCP-Server|Server|stdio|JSON|TOML|venv|"
                      r"PATH|pip|winget|Terminal|CLI|Token)(?![\w])")

    def ungut(seiten):
        aus = []
        for s, info in seiten.items():
            for x in info.get("texte", []):
                y = x.replace("Open MCP CAD", "")
                if re.search(r"[A-Za-z]:\\", y) and not s.startswith("fehler"):
                    aus.append((s, x))
                if fach.search(y) or ("Python" in y and s not in (
                        "python", "laeuft_python")):
                    aus.append((s, x))
        return aus
    pruefe("I26 sichtbare Texte ohne Pfad und ohne Fachwort (Python nur auf "
           "der Seite dazu, der Pfad des Protokolls nur auf der Fehlerseite)",
           seiten and not ungut(seiten), ungut(seiten)[:5])
    falle = {"bereit": {"texte": ["Das richte ich ein: MCP-Server in "
                                  "D:\\Projekte\\x"]}}
    pruefe("I26-K KONTROLLE: ein Fachwort und ein Pfad im Text fallen auf",
           len(ungut(falle)) == 2, ungut(falle))

    # --- I27 der Doppelklick: Fenster, Rueckfall, Textfenster ------------
    # Mit Attrappen fuer install_fenster.ps1 und install.ps1 (schreiben ihre
    # Argumente mit): so laesst sich der Rueckfall messen, ohne dass etwas
    # ins echte Profil kopiert.
    d = tempfile.mkdtemp(prefix="omcad_stub_")
    _temp.append(d)
    spur = os.path.join(d, "spur.txt")

    def stub(name, rc):
        pfad = os.path.join(d, "%s_%d.ps1" % (name, rc))
        with open(pfad, "w", encoding="ascii") as fh:
            fh.write("Add-Content -LiteralPath '%s' -Value ('%s|' + "
                     "[Threading.Thread]::CurrentThread.GetApartmentState() "
                     "+ '|' + ($args -join ' '))\nexit %d\n" % (spur, name, rc))
        return pfad

    def klick(fenster_rc, *schalter, cmd_quelle=None, ohne_fenster=False):
        if os.path.exists(spur):
            os.remove(spur)
        ps1 = paket_attrappe(cmd_quelle=cmd_quelle, ps1=stub("konsole", 0),
                             fenster=None if ohne_fenster else
                             stub("fenster", fenster_rc))
        oben = os.path.dirname(os.path.dirname(ps1))
        r = subprocess.run([os.path.join(oben, P.INSTALLIEREN)]
                           + list(schalter), capture_output=True, timeout=120,
                           stdin=subprocess.DEVNULL, creationflags=OHNE_FENSTER)
        zeilen = open(spur, encoding="utf-8", errors="replace").read(
        ).split() if os.path.exists(spur) else []
        return r.returncode, (r.stdout + r.stderr).decode("cp850", "replace"), \
            [z for z in zeilen]
    rc0, a0, s0 = klick(0)
    rc3, a3, s3 = klick(3)
    rc10, a10, s10 = klick(10)
    rcs, _as, ss = klick(0, "-OhnePause")
    rco, _ao, so = klick(0, ohne_fenster=True)
    # Seit 2026-10-10: "-Sprache fr" allein oeffnet das Fenster in dieser
    # Sprache; ein unbekannter Wert oder ein weiterer Schalter das
    # Textfenster; faellt das Fenster aus, bekommt install.ps1 -Sprache mit
    # (es nimmt den Schalter an).
    _r, _a, sfr = klick(0, "-Sprache", "FR")
    _r, _a, sxx = klick(0, "-Sprache", "xx")
    _r, _a, sfp = klick(0, "-Sprache", "fr", "-OhnePause")
    _r, _a, s10f = klick(10, "-Sprache", "it")
    pruefe("I27s Doppelklick mit -Sprache: 'fr' allein -> Fenster mit "
           "-Sprache fr; unbekannter Wert oder ein Schalter mehr -> "
           "Textfenster; Fenster faellt aus -> Textfenster mit denselben "
           "Schaltern",
           sfr == ["fenster|STA|-Sprache", "fr"]
           and sxx == ["konsole|STA|-Sprache", "xx"]
           and sfp == ["konsole|STA|-Sprache", "fr", "-OhnePause"]
           and s10f == ["fenster|STA|-Sprache", "it", "konsole|STA|-Sprache",
                        "it"],
           dict(sfr=sfr, sxx=sxx, sfp=sfp, s10f=s10f))
    pruefe("I27 Doppelklick ohne Schalter: NUR das Fenster (im STA), dessen "
           "Rueckgabe 0/3 gilt; Rueckgabe 10 -> Hinweis und das Textfenster; "
           "mit Schalter oder ohne Fenster-Datei gleich das Textfenster",
           (rc0, s0) == (0, ["fenster|STA|"]) and (rc3, s3) == (3,
                                                               ["fenster|STA|"])
           and s10 == ["fenster|STA|", "konsole|STA|"] and rc10 == 0
           and "Einrichtungsfenster liess sich nicht oeffnen" in a10
           and ss == ["konsole|STA|-OhnePause"] and so == ["konsole|STA|"],
           dict(s0=s0, s3=s3, s10=s10, ss=ss, so=so, rc=(rc0, rc3, rc10)))
    alt_roh = subprocess.run(["git", "show", "f9adb78:verteilung/" +
                              P.INSTALLIEREN], cwd=REPO, capture_output=True,
                             check=True).stdout
    alt_cmd = os.path.join(d, "alt.cmd")
    with open(alt_cmd, "wb") as fh:
        fh.write(alt_roh)
    rck, _ak, sk = klick(0, cmd_quelle=alt_cmd)
    pruefe("I27-K KONTROLLE: der Doppelklick vor dem Fenster (f9adb78) startet "
           "ohne Schalter das Textfenster, nie das Fenster", sk ==
           ["konsole|STA|"], sk)
    # Der Rueckfall im Fenster selbst: kaputte XAML, kein STA -> 10, nichts
    # gezeigt.
    kaputt = os.path.join(d, "kaputt.xaml")
    with open(kaputt, "w", encoding="utf-8") as fh:
        fh.write("<Window xmlns='http://schemas.microsoft.com/winfx/2006/xaml/"
                 "presentation'><Grid>")
    r1 = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-STA",
                         "-ExecutionPolicy", "Bypass", "-File", FENSTER,
                         "-XamlDatei", kaputt], capture_output=True,
                        timeout=120, creationflags=OHNE_FENSTER)
    r2 = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-MTA",
                         "-ExecutionPolicy", "Bypass", "-File", FENSTER],
                        capture_output=True, timeout=120,
                        creationflags=OHNE_FENSTER)
    pruefe("I27b das Fenster geht nicht (XAML kaputt / kein STA): Rueckgabe 10 "
           "mit einem Satz - 1_INSTALLIEREN.cmd faellt dann aufs Textfenster",
           r1.returncode == 10 and r2.returncode == 10
           and b"laesst sich nicht oeffnen" in r1.stdout
           and b"STA" in r2.stdout, (r1.returncode, r1.stdout[-200:],
                                     r2.returncode, r2.stdout[-200:]))
    # I27c das Verbergen der Konsole: das C# dazu laesst sich uebersetzen,
    # die Funktion wirft nie. Im Kindprozess OHNE Konsole (OHNE_FENSTER:
    # GetConsoleWindow ist dort 0, gemessen) - es wird nichts verborgen.
    def konsole(fenster_ps1):
        r = subprocess.run([PS, "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-Command",
                            ". '%s' -NurFunktionen\n$a = Konsole-Fenster 0\n"
                            "$h = -1; if ('OmcadEinrichtung.Konsole' -as "
                            "[type]) { $h = [OmcadEinrichtung.Konsole]::"
                            "GetConsoleWindow().ToInt64() }\n"
                            "@{ a = $a; h = $h } | ConvertTo-Json -Compress"
                            % fenster_ps1], capture_output=True, timeout=120,
                           creationflags=OHNE_FENSTER)
        try:
            return json.loads(r.stdout.decode("utf-8", "replace").strip()
                              .splitlines()[-1])
        except Exception:                                 # noqa: BLE001
            return {"_fehler": (r.stdout + r.stderr)[-300:]}
    k = konsole(FENSTER)
    kaputt_cs = fmut("public static extern bool ShowWindow(",
                     "public static extern bool ShowWindow((")
    kk = konsole(kaputt_cs)
    pruefe("I27c Konsole verbergen: Add-Type uebersetzt (True), ohne Konsole "
           "nichts zu verbergen (0); KONTROLLE: kaputtes C# -> False, keine "
           "Ausnahme", k == {"a": True, "h": 0} and kk.get("a") is False,
           (k, kk))


# --- I28-I31 Chat in Cadwork, Unterzeile, KI hilft (Rueckmeldung 2026-10-09) -
#
# Das Fenster fragt jetzt auch, WO der Nutzer arbeiten will (KI-App, Chat in
# Cadwork, beides) und welche KI der Chat nimmt; die KI des Chats (Claude
# Code bzw. Codex-CLI) installiert install.ps1 mit dem offiziellen Befehl
# des Herstellers (-ChatKi), angemeldet wird in einem kleinen Fenster. Im
# Gate laeuft nie ein echter Installer und nie ein echtes Anmelden: ein
# falsches "claude.exe" (der Starter von pip vor einem Skript) schreibt
# seine Aufrufe mit und kennt "auth status/login".

FAKE_CLI = r'''
import os, sys
heim = os.environ["USERPROFILE"]
with open(os.path.join(heim, "cli_aufrufe.txt"), "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
marke = os.path.join(heim, "angemeldet.txt")
a = sys.argv[1:]
if a[:2] in (["auth", "status"], ["login", "status"]):
    sys.exit(0 if os.path.exists(marke) else 1)
if a[:2] == ["auth", "login"] or a[:1] == ["login"]:
    open(marke, "w").close()
    sys.exit(0)
sys.exit(2)
'''

#: Die Zeile in install.ps1, die der Gate-Installer ersetzt (nie der echte
#: Download).
CLI_BEFEHL_KOPF = "function Cli-Befehl-Ausfuehren([string]$url) {"


def fake_cli():
    """-> Pfad auf ein falsches claude.exe (in Temp, ausserhalb jeder
    Welt)."""
    t = tempfile.mkdtemp(prefix="omcad_fakecli_")
    _temp.append(t)
    skript = os.path.join(t, "fake_cli.py")
    with open(skript, "w", encoding="utf-8") as fh:
        fh.write(FAKE_CLI)
    return _exe_attrappe(os.path.join(t, "claude.exe"), skript)


def install_mit_cli_attrappe(fake):
    """install.ps1, dessen Cli-Befehl-Ausfuehren statt des Downloads das
    falsche claude.exe nach ~\\.local\\bin legt (fake=None: nichts)."""
    quelle = open(INSTALL, encoding="ascii").read()
    assert quelle.count(CLI_BEFEHL_KOPF) == 1
    if fake:
        tun = ("$z = Join-Path $env:USERPROFILE '.local\\bin'; New-Item "
               "-ItemType Directory -Force $z | Out-Null; Copy-Item "
               "-LiteralPath '%s' -Destination (Join-Path $z 'claude.exe')"
               % fake)
    else:
        tun = "$null = 0"
    ersatz = (CLI_BEFEHL_KOPF + "\n    Write-Host ('ATTRAPPE: ' + $url); "
              + tun + "; return 0\n}\nfunction Cli-Befehl-Echt([string]$url) {")
    d = tempfile.mkdtemp(prefix="omcad_climut_")
    _temp.append(d)
    ziel = os.path.join(d, "install.ps1")
    with open(ziel, "w", encoding="ascii") as fh:
        fh.write(quelle.replace(CLI_BEFEHL_KOPF, ersatz))
    return ziel


def _dock_module():
    import importlib.util
    aus = {}
    for name in ("omcad_a_chat", "omcad_a_anbieter"):
        spec = importlib.util.spec_from_file_location(
            "omcad_gate_" + name, os.path.join(REPO, "cad_plugin",
                                               "Open MCP CAD", name + ".py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        aus[name] = m
    return aus


def cli_welten():
    """Welten fuer die Suche nach Claude Code und der Codex-CLI."""
    welten = {}

    def welt(titel, dateien=(), codex_dir=False):
        t = tempfile.mkdtemp(prefix="omcad_cliw_")
        _temp.append(t)
        w = {"t": t, "heim": os.path.join(t, "heim"),
             "appdata": os.path.join(t, "heim", "AppData", "Roaming"),
             "local": os.path.join(t, "heim", "AppData", "Local"),
             "bin": os.path.join(t, "bin"),
             "wapps": os.path.join(t, "Microsoft", "WindowsApps"),
             "eigen": os.path.join(t, "eigen")}
        for k in ("heim", "appdata", "local", "bin", "wapps"):
            os.makedirs(w[k], exist_ok=True)
        for wurzel, rel in dateien:
            p = os.path.join(w[wurzel], rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(b"MZ")
        w["codex_dir"] = w["eigen"] if codex_dir else None
        welten[titel] = w
    welt("leer")
    welt("claude eigener Installer", [("heim", ".local\\bin\\claude.exe")])
    welt("claude npm", [("appdata", "npm\\claude.cmd")])
    welt("claude beide", [("heim", ".local\\bin\\claude.exe"),
                          ("appdata", "npm\\claude.cmd")])
    welt("claude.exe auf dem PATH", [("bin", "claude.exe")])
    welt("codex eigener Installer",
         [("local", "Programs\\OpenAI\\Codex\\bin\\codex.exe")])
    welt("codex npm", [("appdata", "npm\\codex.cmd")])
    welt("codex beide", [("local", "Programs\\OpenAI\\Codex\\bin\\codex.exe"),
                         ("appdata", "npm\\codex.cmd")])
    welt("codex.exe nur unter WindowsApps", [("wapps", "codex.exe")])
    welt("codex mit CODEX_INSTALL_DIR", [("eigen", "codex.exe"),
                                         ("appdata", "npm\\codex.cmd")],
         codex_dir=True)
    welt("codex.cmd auf dem PATH", [("bin", "codex.cmd")])
    return welten


def _cli_env(w):
    env = dict(os.environ)
    env.pop("CODEX_INSTALL_DIR", None)
    root = env.get("SystemRoot", r"C:\Windows")
    env.update({"USERPROFILE": w["heim"], "HOME": w["heim"],
                "APPDATA": w["appdata"], "LOCALAPPDATA": w["local"],
                "PATH": ";".join([w["bin"], w["wapps"],
                                  os.path.join(root, "System32"), root])})
    if w["codex_dir"]:
        env["CODEX_INSTALL_DIR"] = w["codex_dir"]
    return env


def cli_pfade_ps(w, ps1=None):
    skript = (". '%s' -NurFunktionen\n@{ claude = (Cli-Pfad 'claude'); "
              "codex = (Cli-Pfad 'codex') } | ConvertTo-Json -Compress"
              % (ps1 or INSTALL))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", skript], capture_output=True,
                       timeout=120, env=_cli_env(w), cwd=w["t"],
                       creationflags=OHNE_FENSTER)
    try:
        return json.loads(r.stdout.decode("utf-8", "replace").strip()
                          .splitlines()[-1])
    except Exception:                                     # noqa: BLE001
        return {"_fehler": (r.stdout + r.stderr)[-300:]}


def cli_pfade_dock(w, M):
    alt = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "APPDATA",
                                          "LOCALAPPDATA", "PATH",
                                          "CODEX_INSTALL_DIR")}
    cwd = os.getcwd()
    try:
        for k, v in _cli_env(w).items():
            if k in alt:
                os.environ[k] = v
        if not w["codex_dir"]:
            os.environ.pop("CODEX_INSTALL_DIR", None)
        os.chdir(w["t"])
        aus = {}
        try:
            aus["claude"] = M["omcad_a_chat"].cli_pfad()
        except FileNotFoundError:
            aus["claude"] = None
        try:
            aus["codex"] = M["omcad_a_anbieter"].codex_pfad()
        except M["omcad_a_anbieter"].AnbieterFehler:
            aus["codex"] = None
        return aus
    finally:
        os.chdir(cwd)
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def pruefe_fenster_chat(env, py_da, py_fehlt, fmut):
    import re
    # --- I28 Wo sucht der Chat? install.ps1 == Dock ----------------------
    M = _dock_module()
    welten = cli_welten()
    anders = {}
    for titel, w in welten.items():
        ps, dock = cli_pfade_ps(w), cli_pfade_dock(w, M)
        if ps != dock:
            anders[titel] = (ps, dock)
    pruefe("I28 Cli-Pfad (install.ps1) == cli_pfad/codex_pfad des Chats im "
           "Plugin in %d Welten (eigener Installer vor npm vor PATH, "
           "WindowsApps zaehlt bei Codex nie)" % len(welten), not anders,
           anders)
    dock_beide = cli_pfade_dock(welten["codex beide"], M)["codex"] or ""
    pruefe("I28b der Chat im Plugin findet die Codex-CLI des Installers von "
           "OpenAI (codex.exe unter Programs\\OpenAI\\Codex\\bin) vor npm",
           dock_beide.endswith("Programs\\OpenAI\\Codex\\bin\\codex.exe"),
           dock_beide)
    mut = mutante_ps(
        '        if ($env:LOCALAPPDATA) { $fest += (Join-Path $env:LOCALAPPDATA '
        '"Programs\\OpenAI\\Codex\\bin\\codex.exe") }\n'
        '        if ($env:APPDATA) { $fest += (Join-Path $env:APPDATA '
        '"npm\\codex.cmd") }',
        '        if ($env:APPDATA) { $fest += (Join-Path $env:APPDATA '
        '"npm\\codex.cmd") }\n'
        '        if ($env:LOCALAPPDATA) { $fest += (Join-Path $env:LOCALAPPDATA '
        '"Programs\\OpenAI\\Codex\\bin\\codex.exe") }')
    k = cli_pfade_ps(welten["codex beide"], mut)
    pruefe("I28-K KONTROLLE: npm vor dem eigenen Installer fiele auf",
           k != cli_pfade_dock(welten["codex beide"], M), k)

    # --- I23h Vorauswahl auf "Wo arbeiten?" und "Welche KI im Chat?" -----
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    vorab = {}
    for titel, kw in (("App gefunden", {"programme": ("codex",
                                                       "claude_desktop")}),
                      ("nichts", {"programme": ()}),
                      ("nur Claude Code", {"programme": ("claude_code",)})):
        welt = ki_welt(**kw)
        r, aus = fenster_lauf(w, p, "", vorher=py_da, env=_welt_env(welt),
                              aus="$S.Wo + '|' + $S.ChatKi")
        vorab[titel] = r.get("aus")
    pruefe("I23h Vorauswahl: mit KI-App 'Beides', ohne alles 'In deiner "
           "KI-App', nur mit Claude Code 'Chat in Cadwork' mit Claude",
           vorab == {"App gefunden": "beides|claude", "nichts": "app|claude",
                     "nur Claude Code": "chat|claude"}, vorab)

    # --- I23i der Weg ueber den Chat in Cadwork --------------------------
    r, aus = fenster_lauf(
        w, p, "K 'willkommen_weiter'; (El $U 'wo_chat').IsChecked = $true; "
        "K 'wo_weiter'; (El $U 'chat_codex').IsChecked = $true; "
        "K 'chat_weiter'", vorher=py_da, env=env)
    a = r.get("args") or []
    pruefe("I23i 'Direkt in Cadwork im Chat' + ChatGPT: Willkommen -> Wo -> "
           "Welche KI -> Bereit (keine Seite 'Deine KI-App'); Argumente "
           "-ChatKi codex und -OhneKiEintrag",
           r.get("v") == ["willkommen", "wo", "chat_ki", "bereit"]
           and _wert(a, "-ChatKi") == "codex" and "-OhneKiEintrag" in a
           and "-KiNur" not in a, (r.get("v"), a, aus[-400:]))
    r, aus = fenster_lauf(
        w, p, "K 'willkommen_weiter'; (El $U 'wo_beides').IsChecked = $true; "
        "K 'wo_weiter'; K 'ki_weiter'; (El $U 'chat_spaeter').IsChecked = "
        "$true; K 'chat_weiter'", vorher=py_da, env=env)
    a = r.get("args") or []
    pruefe("I23i 'Beides' + 'Später': beide Fragen, -KiNur fuer die Apps, "
           "kein -ChatKi",
           r.get("v") == ["willkommen", "wo", "ki", "chat_ki", "bereit"]
           and _wert(a, "-KiNur") == "claude_desktop,codex"
           and "-ChatKi" not in a, (r.get("v"), a))
    k, _a = fenster_lauf(
        w, p, "K 'willkommen_weiter'; (El $U 'wo_chat').IsChecked = $true; "
        "K 'wo_weiter'; (El $U 'chat_codex').IsChecked = $true; "
        "K 'chat_weiter'", vorher=py_da, env=env, fenster=fmut(
            'if ($W.ChatKi -eq "claude" -or $W.ChatKi -eq "codex") '
            '{ $a += @("-ChatKi", $W.ChatKi) }', ''))
    pruefe("I23i-K KONTROLLE: ohne -ChatKi in den Argumenten fiele es auf",
           "-ChatKi" not in (k.get("args") or ["-ChatKi"]), k.get("args"))

    # --- I24c der ganze Weg mit der KI fuer den Chat (Attrappen) ---------
    fake = fake_cli()
    welt = ki_welt(programme=())
    cenv = _welt_env(welt)

    def chat_kette(fake_oder_none, schritte_extra=""):
        ps1 = paket_attrappe(ps1=install_mit_cli_attrappe(fake_oder_none),
                             fenster=True)
        fenster = os.path.join(os.path.dirname(ps1), P.FENSTER)
        t2 = tempfile.mkdtemp(prefix="omcad_chatkette_")
        _temp.append(t2)
        w2, p2 = os.path.join(t2, "cadwork"), os.path.join(t2, "cadwork.dir")
        os.makedirs(os.path.join(w2, "userprofil_2026", "3d", "API.x64"))
        os.makedirs(os.path.join(p2, "EXE_2026"))
        for n in ("cli_aufrufe.txt", "angemeldet.txt"):
            if os.path.exists(os.path.join(welt["heim"], n)):
                os.remove(os.path.join(welt["heim"], n))
        lb = os.path.join(welt["heim"], ".local", "bin", "claude.exe")
        if os.path.exists(lb):
            os.remove(lb)
        vorher = py_da + "\n" + (
            "function Prozess-Sichtbar-Starten([string]$pfad, $argumente) {\n"
            "  $global:sichtbar += @($pfad + ' ' + ($argumente -join ' '))\n"
            "  $si = New-Object System.Diagnostics.ProcessStartInfo $pfad\n"
            "  $si.Arguments = ($argumente -join ' ')\n"
            "  $si.UseShellExecute = $false; $si.CreateNoWindow = $true\n"
            "  return [System.Diagnostics.Process]::Start($si)\n}\n"
            "$global:sichtbar = @()")
        warten = ("$global:ok = Pumpen { @('anmelden', 'fertig', 'fehler') "
                  "-contains $S.Seite } 240; $global:v += $S.Seite")
        r, aus = fenster_lauf(
            w2, p2, "K 'willkommen_weiter'; (El $U 'wo_chat').IsChecked = "
            "$true; K 'wo_weiter'; (El $U 'chat_claude').IsChecked = $true; "
            "K 'chat_weiter'; K 'bereit_installieren'; " + warten + "; "
            + schritte_extra, vorher=vorher, env=cenv, ohne_server=True,
            fenster=fenster, aus="@($global:sichtbar)")
        aufrufe = open(os.path.join(welt["heim"], "cli_aufrufe.txt"),
                       encoding="utf-8").read().splitlines() if os.path.exists(
            os.path.join(welt["heim"], "cli_aufrufe.txt")) else []
        return r, aus, aufrufe
    r, aus, aufrufe = chat_kette(
        fake, "if ($S.Seite -eq 'anmelden') { K 'anmelden_los'; "
        "$global:ok2 = Pumpen { $S.Seite -eq 'fertig' } 60; "
        "$global:v += $S.Seite }")
    pruefe("I24c Chat in Cadwork mit Claude: install.ps1 installiert (Attrappe "
           "statt des offiziellen Befehls), nicht angemeldet -> Seite "
           "'Anmelden', 'Anmelden' startet genau 'claude.exe auth login "
           "--claudeai' in einem eigenen Fenster, danach angemeldet -> "
           "'Fertig' mit den Schritten fuer den Chat",
           r.get("v", [])[-4:] == ["laeuft", "anmelden", "anmelden", "fertig"]
           and r.get("rc") == 0
           and [x.split("claude.exe ")[-1] for x in (r.get("aus") or [])]
           == ["auth login --claudeai"]
           and "auth login --claudeai" in aufrufe
           and aufrufe.count("auth status") >= 2,
           (r.get("v"), r.get("aus"), aufrufe, aus[-600:]))
    r2, aus2, aufrufe2 = chat_kette(None)
    pruefe("I24d die KI fuer den Chat laesst sich nicht installieren: "
           "Fehlerseite mit dem Satz dazu, Rueckgabe 3, kein Anmelden",
           r2.get("v", [])[-1:] == ["fehler"] and r2.get("rc") == 3
           and r2.get("fehler") == "t_fehler_chat" and not r2.get("aus"),
           (r2.get("v"), r2.get("fehler"), aus2[-400:]))

    # --- I25b dasselbe im Textfenster: -ChatKi --------------------------
    ps1 = paket_attrappe(ps1=install_mit_cli_attrappe(fake))
    t3, w3, p3 = attrappe(["userprofil_2026"], ["2026"])
    erg = os.path.join(t3, "erg.json")
    for n in ("cli_aufrufe.txt", "angemeldet.txt", ".local"):
        x = os.path.join(welt["heim"], n)
        if os.path.isdir(x):
            shutil.rmtree(x)
        elif os.path.exists(x):
            os.remove(x)
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-File", ps1, "-OhnePause", "-OhneServer",
                        "-CadworkWurzel", w3, "-CadworkProgramm", p3,
                        "-ChatKi", "claude", "-ErgebnisDatei", erg],
                       capture_output=True, timeout=180, env=cenv,
                       creationflags=OHNE_FENSTER)
    aus = (r.stdout + r.stderr).decode("utf-8", "replace")
    e = json.load(open(erg, encoding="utf-8")) if os.path.isfile(erg) else {}
    pruefe("I25b Textfenster mit -ChatKi claude: sechs Schritte, der "
           "offizielle Befehl (hier die Attrappe) mit der URL von Anthropic, "
           "danach 'Noch nicht angemeldet' mit dem Befehl, Rueckgabe 0, "
           "chatOk im Ergebnis",
           r.returncode == 0 and "== 6/6 KI fuer den Chat" in aus
           and "== 1/6" in aus and "ATTRAPPE: https://claude.ai/install.ps1"
           in aus and "Noch nicht angemeldet" in aus
           and "auth login --claudeai" in aus and e.get("chatOk") is True
           and e.get("chatPfad", "").endswith("claude.exe"),
           (r.returncode, aus[-700:], e))

    # --- I29 die Unterzeile: was gerade passiert -------------------------
    proben = [
        ("Lade https://www.python.org/ftp/python/3.13.16/python-3.13.16-"
         "amd64.exe ...", "t_unter_python_laden", ""),
        ("Installiere Python 3.13 (winget, Benutzerbereich) ...",
         "t_unter_python_installieren", ""),
        ("Collecting mcp<2", "t_unter_pip_laden", "mcp"),
        ("  Downloading numpy-2.1.0-cp313-cp313-win_amd64.whl (12.6 MB)",
         "t_unter_pip_laden", "numpy"),
        ("  Downloading https://files.pythonhosted.org/packages/ab/cd/"
         "pydantic_core-2.0-cp313-win_amd64.whl", "t_unter_pip_laden",
         "pydantic_core"),
        ("Collecting C:\\Users\\Public\\x\\server", "t_unter_pip_laden",
         "server"),
        ("Installing collected packages: numpy, mcp",
         "t_unter_pip_installieren", ""),
        ("Lade das offizielle Installationsprogramm von Claude Code: "
         "https://claude.ai/install.ps1", "t_unter_cli_laden", "Claude Code"),
        ("== 4/5 Umgebungsvariable", "", ""),
        ("Requirement already satisfied: x", None, None),
    ]
    code = ". '%s' -NurFunktionen\n$aus = @()\n" % FENSTER
    for z, _s, _w in proben:
        code += ("$u = Unterzeile-Aus-Zeile %s; if ($u) { $aus += ,@($u.Text, "
                 "$u.Wert) } else { $aus += ,@('NULL', 'NULL') }\n"
                 % _ps_text(z))
    code += "ConvertTo-Json -InputObject $aus -Compress"
    r, aus = _ps_fenster(code)
    soll = [[s if s is not None else "NULL", w if w is not None else "NULL"]
            for _z, s, w in proben]
    pruefe("I29 Unterzeile aus den Zeilen von install.ps1/pip/winget: Python "
           "laden/installieren, Paketname ohne Pfad oder Version, Zusatzteile "
           "installieren, KI fuer den Chat, neuer Schritt leert, Rest nichts",
           r == soll, (r, aus[-300:]))
    # I29b im Fenster, mit einem Installer, der langsam Zeilen schreibt.
    stub = os.path.join(tempfile.mkdtemp(prefix="omcad_langsam_"),
                        "install.ps1")
    _temp.append(os.path.dirname(stub))
    zeilen = ["== 1/5 Cadwork-Profil", "== 2/5 Plugin", "== 3/5 MCP-Server",
              "Lade https://www.python.org/ftp/python/3.13.16/python-3.13.16-"
              "amd64.exe ...", "Installiere Python 3.13 ...",
              "Collecting mcp<2", "  Downloading numpy-2.1.0-cp313-cp313-"
              "win_amd64.whl (12.6 MB)", "Collecting pydantic",
              "Installing collected packages: numpy, pydantic, mcp",
              "== 4/5 Umgebungsvariable", "== 5/5 KI-Programme"]
    with open(stub, "w", encoding="ascii") as fh:
        fh.write("$i = [array]::IndexOf($args, '-ErgebnisDatei')\n"
                 "$datei = $args[$i + 1]\n")
        for z in zeilen:
            fh.write("Write-Host %s; Start-Sleep -Milliseconds 450\n"
                     % _ps_text(z))
        # Nur mit -ErgebnisDatei schreiben (sonst entstuende eine Datei im
        # Arbeitsordner des Gates).
        fh.write("if ($i -ge 0) { [IO.File]::WriteAllText($datei, "
                 "'{\"fertig\": true, \"plugin\": \"ok\", \"server\": \"ok\", "
                 "\"kiListe\": []}') }\nexit 0\n")

    def langsam(fenster_mut=None):
        # Die Funktionen aus dem echten install.ps1, gestartet wird der
        # langsame Ersatz ($OMCAD_INSTALL nach dem Laden umgebogen).
        fenster = fmut(*fenster_mut) if fenster_mut else None
        mess = ("$global:spur = @(); $global:takte = New-Object "
                "System.Collections.ArrayList; $global:band = $false\n"
                "$tt = New-Object System.Windows.Threading.DispatcherTimer; "
                "$tt.Interval = [TimeSpan]::FromMilliseconds(40)\n"
                "$tt.Add_Tick({ [void]$global:takte.Add([DateTime]::Now."
                "Ticks); $zz = $global:OMCAD_F.S.Unterzeile; if ($zz -and $zz "
                "-ne ' ' -and ($global:spur.Count -eq 0 -or $global:spur[-1] "
                "-ne $zz)) { $global:spur += $zz }; if ((El $global:OMCAD_F.U "
                "'laeuft_band').Visibility -eq 'Visible') { $global:band = "
                "$true } })\n$tt.Start()\n")
        rechne = ("$global:luecke = 0; for ($i = 1; $i -lt $global:takte.Count;"
                  " $i++) { $d = ($global:takte[$i] - $global:takte[$i - 1]) / "
                  "10000; if ($d -gt $global:luecke) { $global:luecke = $d } }")
        r, aus = fenster_lauf(
            w, p, "KW; K 'ki_weiter'; K 'bereit_installieren'; " + mess
            + "$global:ok = Pumpen { $S.Seite -eq 'fertig' -or $S.Seite -eq "
            "'fehler' } 120; $global:v += $S.Seite; $tt.Stop(); " + rechne,
            vorher=py_da + "\n$OMCAD_INSTALL = %s" % _ps_text(stub),
            env=env, fenster=fenster,
            aus="@{ spur = @($global:spur); luecke = $global:luecke; band = "
                "$global:band; takte = $global:takte.Count }")
        return r, aus
    r, aus = langsam()
    m = r.get("aus") or {}
    soll = ["Python wird heruntergeladen (rund 30 MB) \u2026",
            "Python wird installiert \u2026",
            "Zusatzteile werden geladen: mcp \u2026",
            "Zusatzteile werden geladen: numpy \u2026",
            "Zusatzteile werden geladen: pydantic \u2026",
            "Zusatzteile werden installiert \u2026"]
    pruefe("I29b im Fenster mit einem langsamen Installer (11 Zeilen, je "
           "0,45 s): die Unterzeile folgt Python und den Zusatzteilen, das "
           "Band laeuft, die Ereignisschleife steht nie laenger als 0,5 s "
           "(Fenster bleibt fluessig), am Ende 'Fertig'",
           m.get("spur") == soll and m.get("band") is True
           and 0 < (m.get("luecke") or 9999) < 500
           and r.get("v", [])[-1:] == ["fertig"],
           (m, r.get("v"), aus[-400:]))
    r, aus = langsam(("    if ($unter -and $unter.Text) { Unterzeile-Setzen "
                      "$U $S $unter.Text $unter.Wert }", ""))
    pruefe("I29-K KONTROLLE: ohne das Setzen der Unterzeile bliebe sie leer",
           not (r.get("aus") or {}).get("spur"), r.get("aus"))

    # --- I30 "Lass dir von deiner KI helfen" ------------------------------
    r, aus = fenster_lauf(w, p, "K 'willkommen_kopieren'", vorher=py_da,
                          env=env, aus="(El $U 'willkommen_kopiert').Text")
    text = r.get("ablage") or ""
    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    url = re.search(r"https://github\.com/\S+?/releases/latest", readme).group(0)
    schnell = " ".join(open(os.path.join(P.VERTEILUNG, "SCHNELLSTART.md"),
                            encoding="utf-8").read().replace("> ", " ").split())
    pruefe("I30 'Text kopieren' legt den Text fuer die KI-App in die Ablage: "
           "Release-Adresse (wie im README), %s, %s\\%s, kein Adapter; "
           "derselbe Text steht im Schnellstart"
           % (P.INSTALLIEREN, P.UNTERORDNER, P.KI_HINWEIS),
           url in text and P.INSTALLIEREN in text
           and "%s\\%s" % (P.UNTERORDNER, P.KI_HINWEIS) in text
           and "Adapter" in text and r.get("aus") == "Kopiert."
           and " ".join(text.split()) in schnell, (text[:200], r.get("aus")))
    pruefe("I30-K KONTROLLE: ein anderer Text stuende nicht im Schnellstart",
           " ".join((text + " Extra").split()) not in schnell)


# --- I31 das Einrichtungsfenster in vier Sprachen (seit 2026-10-10) ---------
#
# Rueckmeldung: Website, README und Anleitungen gibt es auf Deutsch,
# Franzoesisch, Italienisch und Englisch, das Fenster war nur deutsch. Die
# Texte stehen jetzt in install_fenster_texte.xml (eine Quelle, Deutsch
# verbindlich), die Sprache kommt aus der Anzeigesprache von Windows.

#: Woerter, die in einem franzoesischen, italienischen oder englischen Text
#: des Fensters nur als deutscher Rest stehen koennen (nach dem Entfernen
#: von «…», Datei- und Ordnernamen).
DEUTSCHE_WOERTER = re.compile(
    r"(?i)(?<![\w-])(und|nicht|wird|werden|ist|mit|für|fuer|ich|dein|"
    r"deine|deinen|deiner|bitte|noch|oder|schon|jetzt|kein|keine|eine|einen|"
    r"der|das|dem|auf|wenn|dann|alles|nochmals|weiter|zurück|"
    r"schliessen|einrichten|installieren|herunterladen|anmelden|"
    r"später|gefunden|fertig)(?![\w-])")


def _ohne_namen(text):
    """Ohne «…» (Beschriftungen von Cadwork und Plugin, die deutsch
    bleiben), Adressen und Datei-/Ordnernamen."""
    t = re.sub("«[^»]*»", " ", text)
    t = re.sub(r"https?://\S+", " ", t)
    return " ".join(w for w in t.split() if not re.search(r"[\\/_.]\w", w))


def texte_luecken(sprachen, texte, gleich, xaml):
    """-> Liste dessen, was an den Texten des Fensters nicht stimmt: jede
    Sprache jeden Schluessel, nichts leer, dieselben Platzhalter wie das
    Deutsche, in fr/it/en kein deutscher Rest (gleich wie Deutsch nur, wo
    gleich="..." die Sprache nennt; kein deutsches Wort, kein Umlaut); in
    der XAML kein sichtbarer Text ausser Zeichen und dem Namen, jeder
    Schluessel dort in der Textdatei."""
    aus = []
    if sprachen != ["de", "fr", "it", "en"]:
        aus.append("Sprachen: %s" % sprachen)
    for k, je in sorted(texte.items()):
        de = je.get("de", "")
        for sp in sprachen:
            v = je.get(sp)
            if v is None:
                aus.append("%s fehlt in %s" % (k, sp))
                continue
            if not v.strip():
                aus.append("%s leer in %s" % (k, sp))
                continue
            if sorted(re.findall(r"\{\d\}", v)) != sorted(
                    re.findall(r"\{\d\}", de)):
                aus.append("%s: andere Platzhalter in %s" % (k, sp))
            if sp == "de":
                continue
            if v == de and sp not in gleich.get(k, ()):
                aus.append("%s in %s wie im Deutschen: %r" % (k, sp, v[:40]))
            rest = _ohne_namen(v)
            if v != de and (DEUTSCHE_WOERTER.search(rest)
                            or re.search("[äöüÄÖ"
                                         "Üß]", rest)):
                aus.append("%s in %s mit deutschem Rest: %r"
                           % (k, sp, rest[:60]))
    fest = re.findall(r'\s(?:Text|Content|Title)="([^"{][^"]*)"', xaml)
    erlaubt = {"Open MCP CAD", "i", "!", "1", "2", "3", "4", " "}
    aus += ["fester Text in der XAML: %r" % f for f in fest
            if f not in erlaubt]
    aus += ["XAML nennt %s, die Textdatei nicht" % k for k in sorted(set(
        re.findall(r"\{DynamicResource (t_\w+)\}", xaml))) if k not in texte]
    return aus


def _texte_mutante(was):
    """Eine Kopie der Textdatei, in der `was(text) -> text` geaendert hat."""
    q = open(FENSTER_TEXTE, encoding="utf-8").read()
    neu = was(q)
    assert neu != q
    d = tempfile.mkdtemp(prefix="omcad_texte_")
    _temp.append(d)
    ziel = os.path.join(d, P.FENSTER_TEXTE)
    with open(ziel, "w", encoding="utf-8") as fh:
        fh.write(neu)
    return ziel


def _schnellstart(sp):
    name = "SCHNELLSTART.md" if sp == "de" else "SCHNELLSTART.%s.md" % sp
    t = open(os.path.join(P.VERTEILUNG, name), encoding="utf-8").read()
    return " ".join(t.replace("> ", " ").replace(" ", " ").split())


def rendern_in(sprache, texte=None, xaml=None):
    """install_fenster.ps1 -Rendern in einer Sprache (ohne Fenster).
    -> (seiten.json als dict, Rueckgabe)"""
    d = tempfile.mkdtemp(prefix="omcad_seiten_%s_" % sprache)
    _temp.append(d)
    arg = [PS, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy",
           "Bypass", "-File", FENSTER, "-Rendern", d, "-Sprache", sprache]
    if texte:
        arg += ["-TexteDatei", texte]
    if xaml:
        arg += ["-XamlDatei", xaml]
    r = subprocess.run(arg, capture_output=True, timeout=300,
                       creationflags=OHNE_FENSTER)
    try:
        seiten = json.load(open(os.path.join(d, "seiten.json"),
                                encoding="utf-8"))
    except (OSError, ValueError):
        seiten = {}
    return seiten, r.returncode


def _abgeschnitten(seiten):
    return {s: [(a.get("teil"), a.get("text", "")[:40], a.get("gewuenscht"),
                 a.get("verfuegbar")) for a in (info.get("abgeschnitten")
                                                or [])]
            for s, info in seiten.items() if info.get("abgeschnitten")}


def _deutsch_auf_seiten(seiten, sp, texte):
    """Texte einer gerenderten Seite in `sp`, die deutsch sind: ein ganzer
    deutscher Text, der sich in `sp` unterscheidet, oder ein deutsches
    Wort (ausser in «…», Pfaden und Dateinamen)."""
    nur_de = {je["de"].replace(" ", " ") for je in texte.values()
              if je.get(sp) != je["de"]}
    aus = []
    for s, info in seiten.items():
        for x in info.get("texte", []):
            y = x.replace(" ", " ")
            if y in nur_de or DEUTSCHE_WOERTER.search(_ohne_namen(y)):
                aus.append((s, x[:50]))
    return aus


def pruefe_sprachen(env, py_da):
    sprachen, texte, gleich = P.fenster_texte()
    xaml = open(FENSTER_XAML, encoding="utf-8").read()
    luecken = texte_luecken(sprachen, texte, gleich, xaml)
    pruefe("I31 Texte des Fensters (%d Schluessel) in de/fr/it/en: jeder "
           "da, keiner leer, Platzhalter wie im Deutschen, in fr/it/en kein "
           "deutscher Rest; die XAML ohne festen Text, jeder Schluessel dort "
           "in der Textdatei" % len(texte), not luecken and len(texte) > 120,
           luecken[:6])
    # KONTROLLEN: je eine eingebaute Luecke MUSS auffallen.
    k = {}
    import copy
    t2 = copy.deepcopy(texte)
    t2["t_weiter"]["fr"] = t2["t_weiter"]["de"]
    k["fr wie deutsch"] = t2
    t2 = copy.deepcopy(texte)
    del t2["t_installieren"]["it"]
    k["it fehlt"] = t2
    t2 = copy.deepcopy(texte)
    t2["t_kopiert"]["en"] = " "
    k["en leer"] = t2
    t2 = copy.deepcopy(texte)
    t2["t_bereit_ki"]["fr"] = "Connexion"
    k["Platzhalter weg"] = t2
    t2 = copy.deepcopy(texte)
    t2["t_fertig_app_3"]["en"] += " Dann weiter."
    k["deutsches Wort"] = t2
    t2 = copy.deepcopy(texte)
    t2["t_das_dauert_ein_paar"]["it"] = "Ci vogliono alcuni minuti über."
    k["Umlaut"] = t2
    rot = {n: bool(texte_luecken(sprachen, t, gleich, xaml))
           for n, t in k.items()}
    rot["fester Text in der XAML"] = bool(texte_luecken(
        sprachen, texte, gleich, xaml.replace(
            'Content="{DynamicResource t_weiter}"', 'Content="Weiter"', 1)))
    rot["Schluessel fehlt in der Textdatei"] = bool(texte_luecken(
        sprachen, {x: v for x, v in texte.items() if x != "t_beides"},
        gleich, xaml))
    pruefe("I31-K KONTROLLEN: jede eingebaute Luecke faellt auf (%d)"
           % len(rot), all(rot.values()), [n for n, r in rot.items() if not r])

    # I31b PowerShell (Texte-Laden) liest dasselbe wie Python.
    code = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding "
            "$false\n"
            ". '%s' -NurFunktionen\n$aus = @{}\nforeach ($sp in $SPRACHEN) "
            "{ $aus[$sp] = Texte-Laden (Texte-Datei) $sp }\n"
            "ConvertTo-Json -InputObject $aus -Compress -Depth 3" % FENSTER)
    r, aus = _ps_fenster(code)
    ps_gleich = sorted(r) == sorted(sprachen) and all(
        r[sp] == {x: je[sp] for x, je in texte.items()} for sp in sprachen)
    pruefe("I31b Texte-Laden (PowerShell) == paket_bauen.fenster_texte "
           "(Python) in allen vier Sprachen", ps_gleich,
           aus[-300:] if not isinstance(r, dict) or "_fehler" in r else
           [sp for sp in sprachen if r.get(sp) != {
               x: je[sp] for x, je in texte.items()}])

    # I31c die Wahl der Sprache: -Sprache vor der Anzeigesprache.
    faelle = [("", "de-CH", "de"), ("", "de-DE", "de"), ("", "gsw-CH", "de"),
              ("", "fr-CH", "fr"), ("", "fr-FR", "fr"), ("", "it-CH", "it"),
              ("", "it-IT", "it"), ("", "rm-CH", "en"), ("", "en-US", "en"),
              ("", "es-ES", "en"), ("", "", "en"), ("fr", "de-CH", "fr"),
              ("IT", "de-CH", "it"), ("en", "fr-CH", "en"),
              ("xx", "fr-CH", "fr"), (" de ", "en-GB", "de")]

    def wahl_lauf(fenster=None):
        code = ". %s -NurFunktionen\n$aus = @(" % _ps_text(fenster or FENSTER)
        code += ", ".join("(Sprache-Waehlen %s %s)" % (_ps_text(w), _ps_text(k))
                          for w, k, _s in faelle)
        code += ")\nConvertTo-Json -InputObject $aus -Compress"
        return _ps_fenster(code)[0]
    soll = [s for _w, _k, s in faelle]
    r = wahl_lauf()
    pruefe("I31c Sprache-Waehlen in %d Faellen: de*/fr*/it* (auch -CH, gsw) "
           "-> diese, sonst en; -Sprache (eine der vier, Gross/Klein egal) geht "
           "vor, ein unbekannter Wert zaehlt nicht" % len(faelle), r == soll,
           r)
    q = open(FENSTER, encoding="ascii").read()

    def fmut2(alt, neu):
        assert q.count(alt) == 1, alt
        d = tempfile.mkdtemp(prefix="omcad_smut_")
        _temp.append(d)
        for n in (P.FENSTER_XAML, P.FENSTER_TEXTE):
            shutil.copy(os.path.join(P.VERTEILUNG, n), os.path.join(d, n))
        shutil.copy(INSTALL, os.path.join(d, "install.ps1"))
        ziel = os.path.join(d, P.FENSTER)
        with open(ziel, "w", encoding="ascii") as fh:
            fh.write(q.replace(alt, neu))
        return ziel
    k1 = wahl_lauf(fmut2("    if ($SPRACHEN -contains $w) { return $w }\n", ""))
    k2 = wahl_lauf(fmut2("-split '[-_]')[0]", "-split '[_]')[0]"))
    pruefe("I31c-K KONTROLLEN: ohne Vorrang fuer -Sprache und ohne das "
           "Abtrennen der Region (fr-CH) fiele es auf", k1 != soll
           and k2 != soll, (k1, k2))

    # I31d das echte Fenster mit der Anzeigesprache des Prozesses (ohne
    # -Sprache): Titel, Knopf und "Text kopieren" je Sprache; der kopierte
    # Text steht im Schnellstart DIESER Sprache.
    for kultur, sp in (("de-CH", "de"), ("fr-CH", "fr"), ("it-IT", "it"),
                       ("en-GB", "en"), ("es-ES", "en")):
        vor = ("[Threading.Thread]::CurrentThread.CurrentUICulture = %s\n"
               % _ps_text(kultur)) + py_da
        t, w, p = attrappe(["userprofil_2026"], ["2026"])
        r, aus = fenster_lauf(
            w, p, "K 'willkommen_kopieren'", vorher=vor, env=env, sprache="",
            aus="@{ titel = $U.W.Title; sprache = $U.Sprache; weiter = (El $U "
                "'willkommen_weiter').Content; kopiert = (El $U "
                "'willkommen_kopiert').Text }")
        a = r.get("aus") or {}
        text = " ".join((r.get("ablage") or "").replace(" ", " ").split())
        pruefe("I31d Anzeigesprache %s -> Fenster in %s: Titel, 'Los geht's'"
               ", 'Kopiert.' und der kopierte Text fuer die KI-App aus der "
               "Textdatei; derselbe Text steht im Schnellstart (%s)"
               % (kultur, sp, sp),
               a.get("sprache") == sp
               and a.get("titel") == texte["t_fenster_titel"][sp]
               and a.get("weiter") == texte["t_los_gehts"][sp]
               and a.get("kopiert") == texte["t_kopiert"][sp]
               and r.get("ablage") == texte["t_ki_hilfe"][sp]
               and len(text) > 200 and text in _schnellstart(sp),
               (a, (r.get("ablage") or "")[:80], aus[-300:]))
    t_fr = " ".join(texte["t_ki_hilfe"]["fr"].replace(" ", " ").split())
    pruefe("I31d-K KONTROLLE: der franzoesische Text stuende nicht im "
           "deutschen Schnellstart, ein veraenderter nicht im franzoesischen",
           t_fr not in _schnellstart("de")
           and (t_fr + " Extra") not in _schnellstart("fr"))

    # I31e jede Seite in jeder Sprache: nichts abgeschnitten (gewuenschte
    # gegen verfuegbare Groesse, Abgeschnitten im Skript), nichts Deutsches
    # in fr/it/en, keine Pfade oder Fachwoerter.
    fach = re.compile(r"(?<![\w-])(API|MCP-Server|Server|stdio|JSON|TOML|venv|"
                      r"PATH|pip|winget|Terminal|CLI|Token)(?![\w])")
    for sp in sprachen:
        seiten, rc = rendern_in(sp)
        ab = _abgeschnitten(seiten)
        deutsch = _deutsch_auf_seiten(seiten, sp, texte) if sp != "de" else []
        ungut = []
        for s, info in seiten.items():
            for x in info.get("texte", []):
                y = x.replace("Open MCP CAD", "")
                if re.search(r"[A-Za-z]:\\", y) and not s.startswith("fehler"):
                    ungut.append((s, x[:50]))
                if fach.search(y) or ("Python" in y and s not in (
                        "python", "laeuft_python")):
                    ungut.append((s, x[:50]))
        titel = {info.get("titel") for info in seiten.values()}
        pruefe("I31e alle %d Seiten und Lagen in %s: nichts abgeschnitten, "
               "Titel %r, nichts Deutsches, kein Pfad und kein Fachwort"
               % (len(seiten), sp, texte["t_fenster_titel"][sp]),
               # 23 seit 2026-10-10 (dazu bereit_zwei, fertig_zwei,
               # version_zwei: zwei Cadwork angehakt)
               rc == 0 and len(seiten) == 23 and not ab and not deutsch
               and not ungut and titel == {texte["t_fenster_titel"][sp]},
               (rc, ab, deutsch[:4], ungut[:4], titel))
    # KONTROLLEN: ein zu langer Knopf und ein zu langer Satz fallen auf, ein
    # fester deutscher Text in der XAML auch.
    lang = _texte_mutante(lambda q: q.replace(
        "<fr>Suivant</fr>", "<fr>%s</fr>" % ("Suivant " * 16).strip(), 1)
        .replace("<fr>Le chat est à côté du dessin.",
                 "<fr>%s Le chat est à côté du dessin."
                 % ("Le chat est à côté du dessin. " * 12), 1))
    seiten, _rc = rendern_in("fr", texte=lang)
    wo = (seiten.get("wo") or {}).get("abgeschnitten") or []
    breit = [a for a in wo if (a.get("text") or "").startswith("Suivant Suivant")]
    hoch = [a for a in wo if (a.get("gewuenscht") or [0, 0])[1]
            > (a.get("verfuegbar") or [0, 0])[1] + 1.5]
    xm = os.path.join(tempfile.mkdtemp(prefix="omcad_xmut_"), P.FENSTER_XAML)
    _temp.append(os.path.dirname(xm))
    with open(xm, "w", encoding="utf-8") as fh:
        fh.write(xaml.replace('x:Name="wo_weiter" DockPanel.Dock="Right" '
                              'Style="{StaticResource Haupt}" Content='
                              '"{DynamicResource t_weiter}"',
                              'x:Name="wo_weiter" DockPanel.Dock="Right" '
                              'Style="{StaticResource Haupt}" Content='
                              '"Weiter"', 1))
    s_x, _rc = rendern_in("fr", xaml=xm)
    pruefe("I31e-K KONTROLLEN: ein Knopf mit 16-fachem Wort (zu breit) und ein "
           "Satz mit 13-facher Laenge (zu hoch) auf der Seite 'wo' gelten als "
           "abgeschnitten; ein fester deutscher Knopf in der XAML faellt in "
           "der franzoesischen Seite auf",
           breit and hoch and _deutsch_auf_seiten(s_x, "fr", texte),
           (wo[:3], _deutsch_auf_seiten(s_x, "fr", texte)[:2]))


# --- I32 das alte Plugin "LignoAI Connect" (seit 2026-10-10) ----------------
#
# Rueckmeldung: auf einem Laptop lag noch das Plugin unter dem alten Namen;
# dann stehen zwei Eintraege im Cadwork-Menue. Der Installer legt es
# beiseite (verschiebt es in eine Sicherung), nie loeschen, nie ein fremdes.

ALT_KERN = 'KERN_PFAD = os.path.join(HIER, "lignoai_bridge_core.py")\n'
ALTE = {"LignoAI Connect", "lignoai connect b", "LignoAI Connect J"}
BLEIBEN = {"Open MCP CAD", "LignoAI Connect C", "LignoAI Connect X",
           "LignoAI Connect Tools", "Fremdes Plugin", "LignoAI Connect D"}


def alte_welt():
    """Ein Profil 2026 mit drei Fassungen des alten Plugins (Name in
    verschiedener Schreibweise, Einstieg laedt lignoai_bridge_core) und
    fuenf, die bleiben muessen: gleicher Name ohne alten Kern im Einstieg,
    gleicher Name ohne Einstieg, aehnlicher Name, ein fremdes Plugin mit
    dem Kern-Namen im Einstieg, eine DATEI mit dem alten Namen.
    -> (t, wurzel, programm, api)"""
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    api = os.path.join(w, "userprofil_2026", "3d", "API.x64")

    def plugin(name, einstieg=None, dateien=()):
        d = os.path.join(api, name)
        os.makedirs(d)
        if einstieg is not None:
            with open(os.path.join(d, name + ".py"), "w") as fh:
                fh.write(einstieg)
        for n in dateien:
            with open(os.path.join(d, n), "w") as fh:
                fh.write("Inhalt von %s\n" % n)
    plugin("LignoAI Connect", ALT_KERN, ["lignoai_bridge_core.py",
                                         "plugin_info.xml"])
    plugin("lignoai connect b", "import lignoai_bridge_core\n")
    plugin("LignoAI Connect J", 'NAME = "LIGNOAI_BRIDGE_CORE_J"\n',
           ["icon.svg"])
    plugin("LignoAI Connect C", "print('ein anderes Plugin')\n")
    plugin("LignoAI Connect X", None, ["icon.svg"])
    plugin("LignoAI Connect Tools", ALT_KERN)
    plugin("Fremdes Plugin", ALT_KERN)
    with open(os.path.join(api, "LignoAI Connect D"), "w") as fh:
        fh.write("eine Datei, kein Ordner\n")
    return t, w, p, api


def alte_stand(w, api):
    """-> (was in API.x64 liegt, {Name: Pfad} in der Sicherung)"""
    weg = {}
    sich = os.path.join(w, "OpenMcpCad_Backups")
    if os.path.isdir(sich):
        for z in os.listdir(sich):
            for n in os.listdir(os.path.join(sich, z)):
                weg[n] = os.path.join(sich, z, n)
    return set(os.listdir(api)), weg


def pruefe_alte_version(env, py_da):
    # I32a Alte-Plugins findet genau die drei Fassungen.
    t, w, p, api = alte_welt()
    r = ps_funktionen("$a = Alte-Plugins '%s'\n@{ n = @($a | ForEach-Object "
                      "{ $_.Name }) } | ConvertTo-Json -Compress" % api)
    pruefe("I32a Alte-Plugins: genau die drei Ordner des alten Plugins (Name "
           "in jeder Schreibweise, Einstieg laedt lignoai_bridge_core); "
           "gleicher Name ohne alten Kern, ohne Einstieg, aehnlicher Name, "
           "fremdes Plugin und eine Datei bleiben aussen vor",
           set(r.get("n") or []) == ALTE, r)

    # I32b -AltesWegraeumen: verschoben, nichts geloescht, Rueckweg genannt.
    vorher = {n: open(os.path.join(api, n, n + ".py"), "rb").read()
              for n in ALTE}
    datei = os.path.join(t, "ergebnis.json")
    rc, aus = installer(w, p, "-AltesWegraeumen", "-ErgebnisDatei", datei)
    erg = json.load(open(datei, encoding="utf-8")) \
        if os.path.isfile(datei) else {}
    bleibt, weg = alte_stand(w, api)
    pruefe("I32b -AltesWegraeumen: die drei liegen unter OpenMcpCad_Backups\\"
           "<Zeit>_alte_Version (Inhalt unveraendert), die fuenf anderen und "
           "das neue Plugin bleiben; Ergebnis nennt Sicherung und Rueckweg, "
           "Rueckgabe 0",
           rc == 0 and bleibt == BLEIBEN and set(weg) == ALTE
           and all(re.search(r"\\\d{4}-\d\d-\d\d_\d{6}_alte_Version\\", x)
                   for x in weg.values())
           and all(open(os.path.join(weg[n], n + ".py"), "rb").read()
                   == vorher[n] for n in ALTE)
           and erg.get("altWeg") == 3 and erg.get("altFehler") is False
           and "Rueckweg" in (erg.get("alt") or "") and api in erg.get("alt")
           and any(z.startswith("Alte Version:") for z in erg.get("zeilen", [])),
           (rc, sorted(bleibt), sorted(weg), erg.get("alt"), aus[-400:]))

    # I32c ohne Schalter (-OhnePause): nichts verschoben, aber gesagt.
    t, w, p, api = alte_welt()
    datei = os.path.join(t, "ergebnis.json")
    rc, aus = installer(w, p, "-ErgebnisDatei", datei)
    erg = json.load(open(datei, encoding="utf-8")) \
        if os.path.isfile(datei) else {}
    bleibt, weg = alte_stand(w, api)
    pruefe("I32c ohne -AltesWegraeumen und ohne Rueckfrage: nichts "
           "verschoben, das Ergebnis sagt, dass es doppelt im Menue steht und "
           "wie man es beiseitelegt; Rueckgabe 0",
           rc == 0 and bleibt == BLEIBEN | ALTE and not weg
           and "doppelt" in (erg.get("alt") or "")
           and "-AltesWegraeumen" in (erg.get("alt") or "")
           and erg.get("altWeg") == 0, (rc, erg.get("alt"), aus[-300:]))

    # I32d das Textfenster fragt: "n" laesst es liegen, Enter legt beiseite.
    def frage_lauf(eingabe):
        t, w, p, api = alte_welt()
        ps1 = paket_attrappe()
        r = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps1, "-OhneServer", "-CadworkWurzel", w,
                            "-CadworkProgramm", p], input=eingabe,
                           capture_output=True, timeout=180,
                           creationflags=OHNE_FENSTER)
        a = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        return r.returncode, a, alte_stand(w, api)
    rc_n, a_n, (b_n, w_n) = frage_lauf(b"n\r\n\r\n")
    rc_j, a_j, (b_j, w_j) = frage_lauf(b"\r\n\r\n")
    pruefe("I32d Textfenster: es fragt ('Beiseitelegen ... [J/n]'); 'n' "
           "laesst alles liegen, Enter legt die drei beiseite",
           "Nicht beiseitegelegt." in a_n and "Beiseitegelegt: " in a_j and not w_n
           and b_n == BLEIBEN | ALTE and set(w_j) == ALTE and b_j == BLEIBEN
           and rc_n == 0 and rc_j == 0,
           (rc_n, rc_j, sorted(w_n), sorted(w_j), a_n[-300:]))

    # I32e eine Datei des alten Plugins ist offen (Cadwork laeuft noch):
    # dieser Ordner bleibt, die anderen gehen, gemeldet statt Abbruch,
    # Rueckgabe 3 ("nicht vollstaendig").
    t, w, p, api = alte_welt()
    datei = os.path.join(t, "ergebnis.json")
    offen = open(os.path.join(api, "LignoAI Connect J", "icon.svg"), "rb")
    try:
        rc, aus = installer(w, p, "-AltesWegraeumen", "-ErgebnisDatei", datei)
    finally:
        offen.close()
    erg = json.load(open(datei, encoding="utf-8")) \
        if os.path.isfile(datei) else {}
    bleibt, weg = alte_stand(w, api)
    pruefe("I32e eine Datei im alten Ordner offen: dieser bleibt ganz (nichts "
           "halb verschoben), die zwei anderen gehen; das Ergebnis nennt den "
           "Fehler, das Plugin ist trotzdem kopiert, Rueckgabe 3",
           rc == 3 and set(weg) == ALTE - {"LignoAI Connect J"}
           and bleibt == BLEIBEN | {"LignoAI Connect J"}
           and set(os.listdir(os.path.join(api, "LignoAI Connect J"))) == {
               "LignoAI Connect J.py", "icon.svg"}
           and erg.get("altFehler") is True and erg.get("plugin") == "ok"
           and "NICHT beiseitegelegt" in (erg.get("alt") or "")
           and "NICHT vollstaendig" in aus,
           (rc, sorted(bleibt), sorted(weg), erg.get("alt"), aus[-400:]))

    # KONTROLLEN: ohne die Pruefung des Einstiegs ginge auch "LignoAI Connect
    # C" (ein anderes Plugin) mit; ohne das Verschieben bliebe alles liegen.
    def mut_ohne(anfang, ende):
        q = open(INSTALL, encoding="ascii").read()
        a, e = q.index(anfang), q.index(ende)
        d = tempfile.mkdtemp(prefix="omcad_amut_")
        _temp.append(d)
        z = os.path.join(d, "install.ps1")
        with open(z, "w", encoding="ascii") as fh:
            fh.write(q[:a] + q[e:])
        return z
    k1 = mut_ohne("        # KENNUNG-ANFANG", "        # KENNUNG-ENDE")
    t, w, p, api = alte_welt()
    r1 = ps_funktionen("$a = Alte-Plugins '%s'\n@{ n = @($a | ForEach-Object "
                       "{ $_.Name }) } | ConvertTo-Json -Compress" % api, k1)
    pruefe("I32-K KONTROLLE: ohne die Pruefung des Einstiegs ginge auch "
           "'LignoAI Connect C' (gleicher Name, fremder Einstieg) mit",
           "LignoAI Connect C" in (r1.get("n") or []), r1)

    # I32f das Fenster: auf "Bereit" der Haken (vorausgewaehlt) -> install.ps1
    # mit -AltesWegraeumen; abgewaehlt ohne; ohne altes Plugin keine Karte.
    zeig = ("@{ sicht = (El $U 'bereit_alt').Visibility.ToString(); haken = "
            "((El $U 'bereit_alt_haken').IsChecked -eq $true); name = (El $U "
            "'bereit_alt_name').Text }")
    t, w, p, api = alte_welt()
    r1, a1 = fenster_lauf(w, p, "KW; K 'ki_weiter'", vorher=py_da, env=env,
                          aus=zeig)
    r2, a2 = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'bereit_alt_haken'",
                          vorher=py_da, env=env, aus=zeig)
    t, w0, p0 = attrappe(["userprofil_2026"], ["2026"])
    r3, a3 = fenster_lauf(w0, p0, "KW; K 'ki_weiter'", vorher=py_da, env=env,
                          aus=zeig)
    pruefe("I32f Fenster: altes Plugin im Profil -> auf 'Bereit' die Karte mit "
           "Haken (vorausgewaehlt) und den drei Namen, Argument "
           "-AltesWegraeumen; Haken weg -> ohne; ohne altes Plugin keine Karte",
           r1.get("seite") == "bereit" and (r1.get("aus") or {}).get("sicht")
           == "Visible" and (r1.get("aus") or {}).get("haken") is True
           and all(n in (r1.get("aus") or {}).get("name", "") for n in ALTE)
           and "-AltesWegraeumen" in (r1.get("args") or [])
           and (r2.get("aus") or {}).get("haken") is False
           and "-AltesWegraeumen" not in (r2.get("args") or ["-Altes"
                                                             "Wegraeumen"])
           and (r3.get("aus") or {}).get("sicht") == "Collapsed"
           and "-AltesWegraeumen" not in (r3.get("args") or ["-Altes"
                                                             "Wegraeumen"]),
           (r1.get("aus"), r1.get("args"), r2.get("aus"), r3.get("aus"),
            a1[-300:]))
    q = open(FENSTER, encoding="ascii").read()
    alt_z = "        Alt = ((@($S.Alte).Count -gt 0) -and [bool]$S.AltWeg)\n"
    assert q.count(alt_z) == 1
    d = tempfile.mkdtemp(prefix="omcad_fmut_")
    _temp.append(d)
    for n in (P.FENSTER_XAML, P.FENSTER_TEXTE):
        shutil.copy(os.path.join(P.VERTEILUNG, n), os.path.join(d, n))
    shutil.copy(INSTALL, os.path.join(d, "install.ps1"))
    fm = os.path.join(d, P.FENSTER)
    with open(fm, "w", encoding="ascii") as fh:
        fh.write(q.replace(alt_z, "        Alt = $false\n"))
    t, w, p, api = alte_welt()
    rk, _a = fenster_lauf(w, p, "KW; K 'ki_weiter'", vorher=py_da, env=env,
                          fenster=fm)
    pruefe("I32f-K KONTROLLE: ohne den Haken in der Wahl fehlte "
           "-AltesWegraeumen trotz altem Plugin",
           rk.get("seite") == "bereit"
           and "-AltesWegraeumen" not in (rk.get("args") or []), rk.get("args"))

    # I32g der ganze Weg im Fenster: beiseitegelegt -> 'Fertig' sagt es;
    # Datei offen -> Fehlerseite mit dem Satz dazu.
    _sp, texte, _gl = P.fenster_texte()
    warten = ("$global:ok = Pumpen { $S.Seite -eq 'fertig' -or $S.Seite -eq "
              "'fehler' } 240")
    ps1 = paket_attrappe(fenster=True)
    fenster = os.path.join(os.path.dirname(ps1), P.FENSTER)
    t, w, p, api = alte_welt()
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'bereit_installieren'; "
                          + warten + "; $global:v += $S.Seite", vorher=py_da,
                          env=env, ohne_server=True, fenster=fenster,
                          aus="$global:ok")
    bleibt, weg = alte_stand(w, api)
    t, w2, p2, api2 = alte_welt()
    offen = open(os.path.join(api2, "LignoAI Connect", "plugin_info.xml"),
                 "rb")
    try:
        r2, aus2 = fenster_lauf(w2, p2, "KW; K 'ki_weiter'; K "
                                "'bereit_installieren'; " + warten + "; "
                                "$global:v += $S.Seite", vorher=py_da,
                                env=env, ohne_server=True, fenster=fenster,
                                aus="$global:ok")
    finally:
        offen.close()
    pruefe("I32g Fenster -> install.ps1: altes Plugin beiseitegelegt, 'Fertig' "
           "sagt es (Rueckgabe 0); ist eine Datei offen, Fehlerseite 'liess "
           "sich nicht beiseitelegen' (Rueckgabe 3), das neue Plugin liegt "
           "trotzdem da",
           r.get("v", [])[-1:] == ["fertig"] and r.get("rc") == 0
           and set(weg) == ALTE and texte["t_fertig_alt"]["de"]
           in (r.get("fertig_ki") or "")
           and r2.get("v", [])[-1:] == ["fehler"] and r2.get("rc") == 3
           and r2.get("fehler") == "t_fehler_alt"
           and kopiert_in(w2) == ["userprofil_2026"],
           (r.get("v"), r.get("fertig_ki"), sorted(weg), r2.get("v"),
            r2.get("fehler"), aus[-300:], aus2[-300:]))


# --- I33 Doppelklick IN der ZIP-Datei: freundlich entpacken (seit 2026-10-10)
#
# Rueckmeldung 2026-10-10 (echter Test): 1_INSTALLIEREN.cmd direkt in der
# ZIP doppelgeklickt -> schwarzes Fenster "... beliebige Taste", danach "wie
# nichts". Jetzt sucht die .cmd die ZIP, bietet in einem Fenster das
# Entpacken an und startet den Doppelklick aus dem entpackten Ordner. Im Gate
# nie ein Fenster: OMCAD_HILFE_ANTWORT beantwortet es (gebaut wird es
# trotzdem), OMCAD_HILFE_SPUR schreibt mit, was es zeigen wuerde,
# OMCAD_ZIP_ORTE ersetzt Downloads/Desktop/Dokumente.

def _hilfe_stub(spur, name, rc):
    d = tempfile.mkdtemp(prefix="omcad_hstub_")
    _temp.append(d)
    pfad = os.path.join(d, "%s.ps1" % name)
    with open(pfad, "w", encoding="ascii") as fh:
        fh.write("Add-Content -LiteralPath '%s' -Value ('%s|' + ($args -join "
                 "' '))\nexit %d\n" % (spur, name, rc))
    return pfad


def _zip_aus(ordner, ziel, oben, zone=False, mtime=None):
    """Packt `ordner` wie paket_bauen (Ordner `oben` obendrueber)."""
    import zipfile
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        for wurzel, _d, namen in os.walk(ordner):
            for n in sorted(namen):
                p = os.path.join(wurzel, n)
                z.write(p, os.path.join(oben, os.path.relpath(p, ordner))
                        if oben else os.path.relpath(p, ordner))
    if zone:
        with open(ziel + ":Zone.Identifier", "w") as fh:
            fh.write("[ZoneTransfer]\nZoneId=3\n")
    if mtime:
        os.utime(ziel, (mtime, mtime))
    return ziel


def gepackt_welt(temp_name="Temp1_Open-MCP-CAD-0.2.2.zip", cmd_quelle=None):
    """Downloads (unter einem Heim mit Umlaut und Leerzeichen) mit der
    passenden ZIP, einer neueren gueltigen und einer neuesten UNgueltigen,
    der Desktop mit einer aelteren; der Doppelklick liegt allein in einem
    Ordner wie vom Explorer (%TEMP%\\Temp1_<zip>\\<oben>\\). -> dict"""
    t = tempfile.mkdtemp(prefix="omcad_gepackt_")
    _temp.append(t)
    heim = os.path.join(t, "Jürg Müller")
    w = {"t": t, "dl": os.path.join(heim, "Downloads"),
         "desk": os.path.join(heim, "Desktop"),
         "spur": os.path.join(t, "spur.txt"),
         "hspur": os.path.join(t, "hilfe.jsonl")}
    os.makedirs(w["desk"])
    ps1 = paket_attrappe(ps1=_hilfe_stub(w["spur"], "konsole", 0),
                         fenster=_hilfe_stub(w["spur"], "fenster", 0))
    paket = os.path.dirname(os.path.dirname(ps1))
    jetzt = __import__("time").time()
    w["zip"] = _zip_aus(paket, os.path.join(w["dl"], "Open-MCP-CAD-0.2.2.zip"),
                        "Open-MCP-CAD-0.2.2", zone=True, mtime=jetzt - 3600)
    w["neuer"] = _zip_aus(paket, os.path.join(w["desk"],
                                              "Open-MCP-CAD-0.2.3.zip"),
                          "Open-MCP-CAD-0.2.3", mtime=jetzt - 600)
    _zip_aus(paket, os.path.join(w["desk"], "Open-MCP-CAD-0.1.0.zip"),
             "Open-MCP-CAD-0.1.0", mtime=jetzt - 86400)
    leer = os.path.join(t, "leer")
    os.makedirs(os.path.join(leer, "x"))
    with open(os.path.join(leer, "x", "liesmich.txt"), "w") as fh:
        fh.write("kein Paket\n")
    _zip_aus(leer, os.path.join(w["dl"], "Open-MCP-CAD-kaputt.zip"), "",
             mtime=jetzt)
    _zip_aus(leer, os.path.join(w["dl"], "anderes.zip"), "", mtime=jetzt)
    w["cmd"] = os.path.join(t, "Temp", temp_name, "Open-MCP-CAD-0.2.2",
                            P.INSTALLIEREN)
    os.makedirs(os.path.dirname(w["cmd"]))
    with open(cmd_quelle or os.path.join(P.VERTEILUNG, P.INSTALLIEREN),
              "rb") as fh:
        roh = fh.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(w["cmd"], "wb") as fh:
        fh.write(roh)
    return w


def gepackt_lauf(w, antwort, orte=None, sprache="de", schalter=()):
    env = dict(os.environ)
    env.update({"OMCAD_HILFE_ANTWORT": antwort, "OMCAD_HILFE_SPUR": w["hspur"],
                "OMCAD_ZIP_ORTE": ";".join(orte if orte is not None
                                           else (w["dl"], w["desk"])),
                "OMCAD_HILFE_SPRACHE": sprache})
    for d in (w["spur"], w["hspur"]):
        if os.path.exists(d):
            os.remove(d)
    r = subprocess.run([w["cmd"]] + list(schalter), capture_output=True,
                       timeout=180, env=env, stdin=subprocess.DEVNULL,
                       creationflags=OHNE_FENSTER)
    aus = (r.stdout + r.stderr).decode("cp850", "replace")
    spur = open(w["spur"], encoding="utf-8", errors="replace").read().split() \
        if os.path.exists(w["spur"]) else []
    hilfe = [json.loads(z) for z in open(w["hspur"], encoding="utf-8")
             .read().splitlines() if z.strip()] \
        if os.path.exists(w["hspur"]) else []
    return r.returncode, aus, spur, hilfe


def _taste(aus):
    return any(x in aus for x in ("Taste", "beliebige", "any key"))


def hilfe_funktionen(code, env=None):
    """Die Funktionen aus dem PowerShell-Teil von 1_INSTALLIEREN.cmd (ab der
    Marke, wie die .cmd ihn liest), dann `code`. -> JSON der letzten Zeile"""
    cmd = os.path.join(P.VERTEILUNG, P.INSTALLIEREN)
    skript = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding "
              "$false\n$env:OMCAD_HILFE_NUR_FUNKTIONEN = '1'\n"
              "$t = [IO.File]::ReadAllText(%s); . ([ScriptBlock]::Create("
              "$t.Substring($t.IndexOf('#OMCAD' + '-HILFE'))))\n%s"
              % (_ps_text(cmd), code))
    r, aus = _ps_fenster(skript, env=env)
    return r, aus


def pruefe_gepackt():
    w = gepackt_welt()
    rc, aus, spur, hilfe = gepackt_lauf(w, "starten")
    ziel = os.path.join(w["dl"], "Open-MCP-CAD-0.2.2")
    zone = os.path.join(ziel, P.UNTERORDNER, "install.ps1") + ":Zone.Identifier"
    pruefe("I33a Doppelklick IN der ZIP: Fenster 'Die Datei ist noch gepackt' "
           "nennt die ZIP aus dem Temp-Ordnernamen (nicht die neuere, nicht "
           "die ungueltige) und das Ziel; 'Entpacken und starten' -> "
           "Downloads\\Open-MCP-CAD-0.2.2 (ohne Ordner obendrueber, mit der "
           "Herkunftsmarke der ZIP), dort startet der Doppelklick das "
           "Einrichtungsfenster; Rueckgabe 0, kein 'beliebige Taste'",
           rc == 0 and spur == ["fenster|"] and len(hilfe) == 1
           and hilfe[0].get("art") == "angebot"
           and hilfe[0].get("zip") == w["zip"] and hilfe[0].get("ziel") == ziel
           and hilfe[0].get("knoepfe") == ["Entpacken und starten",
                                           "Abbrechen"]
           and os.path.isfile(os.path.join(ziel, P.INSTALLIEREN))
           and os.path.isfile(os.path.join(ziel, P.UNTERORDNER, "install.ps1"))
           and os.path.exists(zone) and not _taste(aus),
           (rc, spur, hilfe, aus[-400:]))
    with open(os.path.join(ziel, "eigenes.txt"), "w") as fh:
        fh.write("bleibt\n")
    rc2, aus2, spur2, hilfe2 = gepackt_lauf(w, "starten")
    ziel2 = ziel + " (2)"
    pruefe("I33b nochmals: der vorhandene Ordner bleibt (nie ueberschrieben), "
           "entpackt wird nach 'Open-MCP-CAD-0.2.2 (2)'",
           rc2 == 0 and hilfe2 and hilfe2[0].get("ziel") == ziel2
           and os.path.isfile(os.path.join(ziel2, P.INSTALLIEREN))
           and os.path.isfile(os.path.join(ziel, "eigenes.txt")),
           (rc2, hilfe2, aus2[-300:]))
    w = gepackt_welt()
    rc, aus, spur, hilfe = gepackt_lauf(w, "abbrechen")
    pruefe("I33c 'Abbrechen': nichts entpackt, nichts gestartet, Rueckgabe 2, "
           "kein 'beliebige Taste'",
           rc == 2 and not spur and not os.path.exists(os.path.join(
               w["dl"], "Open-MCP-CAD-0.2.2")) and not _taste(aus),
           (rc, spur, aus[-300:]))
    w = gepackt_welt(temp_name="Temp2_Download (3).zip")
    rc, aus, spur, hilfe = gepackt_lauf(w, "starten")
    pruefe("I33d ZIP unter anderem Namen geoeffnet: die NEUESTE gueltige "
           "Open-MCP-CAD*.zip (0.2.3 auf dem Desktop, nicht die neueste "
           "ungueltige), entpackt neben ihr",
           rc == 0 and hilfe and hilfe[0].get("zip") == w["neuer"]
           and os.path.isfile(os.path.join(w["desk"], "Open-MCP-CAD-0.2.3",
                                           P.INSTALLIEREN)), (rc, hilfe))
    leer = tempfile.mkdtemp(prefix="omcad_keinezip_")
    _temp.append(leer)
    rc, aus, spur, hilfe = gepackt_lauf(w, "ok", orte=[leer])
    pruefe("I33e keine ZIP gefunden: Fenster 'Bitte zuerst entpacken' mit drei "
           "Schritten (rechte Maustaste, 'Alle extrahieren', im neuen Ordner "
           "doppelklicken), Knopf OK, Rueckgabe 2, kein 'beliebige Taste'",
           rc == 2 and not spur and len(hilfe) == 1
           and hilfe[0].get("art") == "anleitung"
           and len(hilfe[0].get("texte", [])) == 5
           and "Alle extrahieren" in " ".join(hilfe[0]["texte"])
           and hilfe[0].get("knoepfe") == ["OK"] and not _taste(aus),
           (rc, hilfe, aus[-300:]))
    rc, aus, spur, hilfe = gepackt_lauf(w, "kaputt", orte=[leer])
    rcp, ausp, _s, hilfep = gepackt_lauf(w, "ok", orte=[leer],
                                        schalter=["-OhnePause"])
    pruefe("I33f geht das Fenster nicht (hier: OMCAD_HILFE_ANTWORT=kaputt), "
           "der Text wie frueher ('Alle extrahieren', wartet); mit -OhnePause "
           "kein Fenster, nur der Text",
           rc == 2 and "Alle extrahieren" in aus and _taste(aus)
           and rcp == 2 and not hilfep and "Alle extrahieren" in ausp
           and not _taste(ausp), (rc, aus[-300:], rcp, hilfep))
    # Sprachen: dieselben Schluessel, nichts leer, kein deutscher Rest; die
    # Wahl wie Sprache-Waehlen des Einrichtungsfensters.
    r, aus = hilfe_funktionen(
        "$aus = @{}\nforeach ($sp in $HILFE_TEXTE.Keys) { $aus[$sp] = @{}; "
        "foreach ($k in $HILFE_TEXTE[$sp].Keys) { $aus[$sp][$k] = "
        "[regex]::Unescape($HILFE_TEXTE[$sp][$k]) } }\n"
        "ConvertTo-Json -InputObject $aus -Compress -Depth 3")
    lu = []
    if sorted(r) != ["de", "en", "fr", "it"]:
        lu.append("Sprachen %s" % sorted(r))
    else:
        for sp in ("fr", "it", "en"):
            if sorted(r[sp]) != sorted(r["de"]):
                lu.append("%s: andere Schluessel" % sp)
            for k, v in r[sp].items():
                if not v.strip():
                    lu.append("%s %s leer" % (sp, k))
                elif v == r["de"].get(k) and k != "ok":
                    lu.append("%s %s wie deutsch" % (sp, k))
                elif DEUTSCHE_WOERTER.search(_ohne_namen(v)):
                    lu.append("%s %s deutsch: %s" % (sp, k, v[:40]))
        # Der Schnellstart je Sprache nennt Titel und Knopf wie das Fenster.
        for sp in ("de", "fr", "it", "en"):
            s = _schnellstart(sp)
            for k in ("gepackt_titel", "starten"):
                if " ".join(r[sp][k].split()) not in s:
                    lu.append("SCHNELLSTART %s ohne %r" % (sp, r[sp][k]))
    pruefe("I33g Texte der Fenster in de/fr/it/en: dieselben Schluessel, "
           "nichts leer, kein deutscher Rest; Titel und Knopf stehen so im "
           "Schnellstart der Sprache", not lu and r.get("de"),
           lu[:5] or aus[-300:])
    faelle = [("de-CH", "de"), ("gsw-CH", "de"), ("fr-CH", "fr"),
              ("it-IT", "it"), ("en-US", "en"), ("es-ES", "en"),
              ("rm-CH", "en")]
    code = "$aus = @()\n"
    for k, _s in faelle:
        code += ("[Threading.Thread]::CurrentThread.CurrentUICulture = %s; "
                 "$aus += @(Hilfe-Sprache)\n" % _ps_text(k))
    env = dict(os.environ)
    env.pop("OMCAD_HILFE_SPRACHE", None)
    r, aus = hilfe_funktionen(code + "ConvertTo-Json -InputObject $aus "
                              "-Compress", env=env)
    pruefe("I33h Sprache der Fenster aus der Anzeigesprache wie im "
           "Einrichtungsfenster (de*/gsw/fr*/it* -> diese, sonst en)",
           r == [s for _k, s in faelle], (r, aus[-300:]))
    w = gepackt_welt()
    rc, aus, spur, hilfe = gepackt_lauf(w, "starten", sprache="fr")
    pruefe("I33h-2 Windows auf Franzoesisch: das Fenster fragt franzoesisch",
           rc == 0 and hilfe and hilfe[0].get("sprache") == "fr"
           and hilfe[0].get("knoepfe") == ["Extraire et lancer", "Annuler"],
           hilfe)
    # KONTROLLE: der Doppelklick vor diesem Stand (d613809) zeigt in
    # derselben Welt nur Text, wartet auf eine Taste und entpackt nichts.
    alt_roh = subprocess.run(["git", "show", "d613809:verteilung/" +
                              P.INSTALLIEREN], cwd=REPO, capture_output=True,
                             check=True).stdout
    alt = os.path.join(tempfile.mkdtemp(prefix="omcad_altcmd_"),
                       P.INSTALLIEREN)
    _temp.append(os.path.dirname(alt))
    with open(alt, "wb") as fh:
        fh.write(alt_roh)
    w = gepackt_welt(cmd_quelle=alt)
    rc, aus, spur, hilfe = gepackt_lauf(w, "starten")
    pruefe("I33-K KONTROLLE: der Doppelklick von d613809 entpackt in derselben "
           "Welt nichts und sagt 'beliebige Taste'",
           rc == 2 and not hilfe and _taste(aus) and not os.path.exists(
               os.path.join(w["dl"], "Open-MCP-CAD-0.2.2")), (rc, aus[-200:]))


# --- I34 "diesen Text" kopiert, I35 Details ein/aus (seit 2026-10-10) -------

def _fmut_neu(alt, neu):
    """Eine Mutante von install_fenster.ps1 (mit XAML, Texten, install.ps1)."""
    q = open(FENSTER, encoding="ascii").read()
    assert q.count(alt) == 1, alt
    d = tempfile.mkdtemp(prefix="omcad_fmut_")
    _temp.append(d)
    for n in (P.FENSTER_XAML, P.FENSTER_TEXTE):
        shutil.copy(os.path.join(P.VERTEILUNG, n), os.path.join(d, n))
    shutil.copy(INSTALL, os.path.join(d, "install.ps1"))
    z = os.path.join(d, P.FENSTER)
    with open(z, "w", encoding="ascii") as fh:
        fh.write(q.replace(alt, neu))
    return z


def pruefe_kopieren_details(env, py_da):
    _sp, texte, _gl = P.fenster_texte()
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    zeig = ("@{ kopiert = (El $U 'willkommen_kopiert').Text; symbol = (El $U "
            "'willkommen_symbol_kopieren').Visibility.ToString(); haken = (El "
            "$U 'willkommen_symbol_haken').Visibility.ToString() }")
    for sp in ("de", "fr"):
        r, aus = fenster_lauf(
            w, p, "K 'willkommen_link'; $global:a1 = " + zeig + "; $null = "
            "Pumpen { $false } 3; $global:a2 = " + zeig, vorher=py_da,
            env=env, sprache=sp,
            aus="@{ a1 = $global:a1; a2 = $global:a2; tip = (El $U "
                "'willkommen_link').ToolTip; knopf_tip = (El $U "
                "'willkommen_kopieren').ToolTip; name = [System.Windows."
                "Automation.AutomationProperties]::GetName((El $U "
                "'willkommen_kopieren')); inhalt_text = ((El $U "
                "'willkommen_kopieren').Content -is [string]); satz = (New-Object "
                "System.Windows.Documents.TextRange((El $U 'willkommen_ki_satz')"
                ".ContentStart, (El $U 'willkommen_ki_satz').ContentEnd)).Text }")
        a = r.get("aus") or {}
        k = texte["t_ki_hilfe"][sp]
        pruefe("I34 (%s) 'diesen Text' im Satz ist ein Verweis: Klick kopiert "
               "den Text fuer die KI-App, zeigt Haken + 'Kopiert.' und nach "
               "2,5 s wieder das Kopier-Symbol; Tooltip ueber dem Verweis = "
               "Anfang des Texts; rechts nur ein Symbol mit Tooltip und Namen "
               "'Text kopieren'" % sp,
               r.get("ablage") == k
               and a.get("a1") == {"kopiert": texte["t_kopiert"][sp],
                                   "symbol": "Collapsed", "haken": "Visible"}
               and a.get("a2") == {"kopiert": "", "symbol": "Visible",
                                   "haken": "Collapsed"}
               and (a.get("tip") or "").endswith("…")
               and k.startswith((a.get("tip") or "x")[:-2].rstrip())
               and a.get("knopf_tip") == texte["t_text_kopieren"][sp]
               and a.get("name") == texte["t_text_kopieren"][sp]
               and a.get("inhalt_text") is False
               and a.get("satz") == texte["t_ki_hilfe_vor"][sp]
               + texte["t_ki_hilfe_link"][sp] + texte["t_ki_hilfe_nach"][sp],
               (a, (r.get("ablage") or "")[:60], aus[-300:]))
    r, aus = fenster_lauf(w, p, "K 'willkommen_kopieren'", vorher=py_da,
                          env=env)
    km = _fmut_neu('    (El $U "willkommen_link").Add_Click({ $F = '
                   '$global:OMCAD_F; KI-Hilfe-Kopieren $F.U $F.S })\n', "")
    rk, _a = fenster_lauf(w, p, "K 'willkommen_link'", vorher=py_da, env=env,
                          fenster=km)
    pruefe("I34b das Kopier-Symbol kopiert dasselbe; KONTROLLE: ohne den "
           "Verweis-Handler bliebe die Ablage leer",
           r.get("ablage") == texte["t_ki_hilfe"]["de"]
           and not rk.get("ablage"), (r.get("ablage", "")[:40], rk.get("ablage")))

    # I35 Details ein/aus: der Knopf sagt, was er tut.
    erg = ("$S.Ergebnis = [pscustomobject]@{ fertig = $true; kiListe = @() }; "
           "[void]$S.Log.AppendLine('Zeile im Protokoll')")
    schritte = []
    for seite in ("laeuft", "fertig", "fehler"):
        knopf = seite + "_details"
        schritte.append(
            "Seite-Zeigen $U $S '%s'; $global:d['%s'] = @(); foreach ($i in 1..2) "
            "{ Klick $U '%s'; $global:d['%s'] += ,@((El $U '%s').Content, "
            "(El $U '%s_protokoll').Visibility.ToString()) }"
            % (seite, seite, knopf, seite, knopf, seite))
    code = erg + "; $global:d = @{}; " + "; ".join(schritte)
    for sp in ("de", "it"):
        r, aus = fenster_lauf(w, p, code, vorher=py_da, env=env, sprache=sp,
                              aus="$global:d")
        d = r.get("aus") or {}
        an, aus_t = texte["t_details_ausblenden"][sp], \
            texte["t_details_anzeigen"][sp]
        pruefe("I35 (%s) 'Details anzeigen' auf Fortschritt, Fertig und "
               "Fehler: aufgeklappt 'Details ausblenden' mit Protokoll, "
               "wieder zu 'Details anzeigen' (echte Click-Ereignisse)" % sp,
               all(d.get(s) == [[an, "Visible"], [aus_t, "Collapsed"]]
                   for s in ("laeuft", "fertig", "fehler")), (d, aus[-300:]))
    km = _fmut_neu('(Text $U "t_details_ausblenden")',
                 '(Text $U "t_details_anzeigen")')
    r, aus = fenster_lauf(w, p, code, vorher=py_da, env=env, fenster=km,
                          aus="$global:d")
    pruefe("I35-K KONTROLLE: ohne den Wechsel stuende nach dem Aufklappen "
           "weiter 'Details anzeigen'",
           (r.get("aus") or {}).get("laeuft", [[None]])[0][0]
           == texte["t_details_anzeigen"]["de"], r.get("aus"))


# --- I36 jede Wahl sichtbar, "Nochmal suchen", Zurueck, Chat dazu ---------
# --- I37 die echten Symbole der Apps (beide seit 2026-10-10) --------------

def _lage(name):
    """Welten fuer I36: alles gefunden, nur Apps, nur Claude Code, nichts.
    -> (env, KiGefunden, CliDa claude/codex)"""
    prog = {"alles": ("codex", "claude_code", "claude_desktop"),
            "nur_apps": ("codex", "claude_desktop"),
            "nur_code": ("claude_code",), "nichts": ()}[name]
    w = ki_welt(programme=prog)
    if name == "alles":
        b = os.path.join(w["local"], "Programs", "OpenAI", "Codex", "bin")
        os.makedirs(b)
        with open(os.path.join(b, "codex.exe"), "wb") as fh:
            fh.write(b"MZ Attrappe")
    return w, _welt_env(w), set(prog), {
        "claude": "claude_code" in prog, "codex": name == "alles"}


def _png(pfad, groesse=48):
    """Ein gueltiges PNG (eine Farbe), ohne fremde Bibliothek."""
    import struct
    import zlib
    roh = b"".join(b"\x00" + b"\x5b\x3c\xc4\xff" * groesse
                   for _ in range(groesse))

    def stueck(art, daten):
        return (struct.pack(">I", len(daten)) + art + daten
                + struct.pack(">I", zlib.crc32(art + daten) & 0xffffffff))
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + stueck(b"IHDR", struct.pack(
            ">IIBBBBB", groesse, groesse, 8, 6, 0, 0, 0))
            + stueck(b"IDAT", zlib.compress(roh)) + stueck(b"IEND", b""))


def paket_attrappe_app(kaputt=False, nur_store=False):
    """Ein Store-Paket in Temp: AppxManifest.xml mit Square44x44Logo und
    Logo, die PNG-Dateien wie im echten Paket benannt."""
    d = tempfile.mkdtemp(prefix="omcad_appx_")
    _temp.append(d)
    with open(os.path.join(d, "AppxManifest.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<Package><Properties>'
                 '<Logo>Assets\\StoreLogo.png</Logo></Properties><Applications>'
                 '<Application><uap:VisualElements xmlns:uap="x" '
                 'Square44x44Logo="Assets\\Square44x44Logo.png"/></Application>'
                 '</Applications></Package>\n')
    a = os.path.join(d, "Assets")
    os.makedirs(a)
    _png(os.path.join(a, "StoreLogo.scale-100.png"), 50)
    if not nur_store:
        _png(os.path.join(a, "Square44x44Logo.scale-200.png"), 88)
        _png(os.path.join(a, "Square44x44Logo.targetsize-48_altform-unplated.png"), 48)
        ziel = os.path.join(a, "Square44x44Logo.targetsize-48_altform-lightunplated.png")
        if kaputt:
            with open(ziel, "wb") as fh:
                fh.write(b"\x89PNG kein Bild")
        else:
            _png(ziel, 48)
    return d


def pruefe_wahl_suche_zurueck(env0, py_da):
    _sp, texte, _gl = P.fenster_texte()
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    zeig = ("Seite-Zeigen $U $S 'ki'; $global:ki = @{}; foreach ($id in "
            "$KI_PROGRAMME) { $global:ki[$id] = @((El $U ('ki_karte_' + $id))."
            "Visibility.ToString(), (El $U ('ki_marke_' + $id)).Visibility."
            "ToString(), (El $U ('ki_holen_' + $id)).Visibility.ToString(), "
            "(El $U ('ki_' + $id)).IsEnabled) }; Seite-Zeigen $U $S 'chat_ki'; "
            "$global:chat = @{}; foreach ($k in 'claude','codex') { "
            "$global:chat[$k] = @((El $U ('chat_' + $k)).IsEnabled, (El $U "
            "('chat_stand_' + $k)).Text, (El $U ('chat_marke_' + $k))."
            "Visibility.ToString()) }; $S.Wo = 'chat'; (El $U 'chat_%s')."
            "IsChecked = $true; K 'chat_weiter'")
    aus_z = "@{ ki = $global:ki; chat = $global:chat }"

    def lage_pruefen(r, gef, cli, wahl):
        a = r.get("aus") or {}
        aus = []
        for id_ in ("claude_desktop", "codex", "claude_code"):
            da = id_ in gef
            soll = ["Visible", "Visible" if da else "Collapsed",
                    "Collapsed" if da else "Visible", da]
            if (a.get("ki") or {}).get(id_) != soll:
                aus.append(("ki", id_, (a.get("ki") or {}).get(id_), soll))
        for k in ("claude", "codex"):
            soll = [True, texte["t_gefunden" if cli[k] else
                               "t_wird_mitinstalliert"]["de"], "Visible"]
            if (a.get("chat") or {}).get(k) != soll:
                aus.append(("chat", k, (a.get("chat") or {}).get(k), soll))
        if r.get("seite") != "bereit" or _wert(r.get("args") or [],
                                                  "-ChatKi") != wahl:
            aus.append(("wahl", r.get("seite"), r.get("args")))
        return aus
    for lage, wahl in (("alles", "codex"), ("nur_apps", "codex"),
                       ("nur_code", "codex"), ("nichts", "claude")):
        _w, env, gef, cli = _lage(lage)
        r, aus = fenster_lauf(w, p, zeig % wahl, vorher=py_da, env=env,
                              aus=aus_z)
        luecken = lage_pruefen(r, gef, cli, wahl)
        pruefe("I36 Lage '%s': auf 'Deine KI-App' jede App zu sehen (gefunden "
               "-> Plakette, sonst 'Holen' und kein Haken); im Chat beide KI "
               "waehlbar ('Gefunden' bzw. 'Wird mitinstalliert'); %s waehlbar "
               "und installierbar (-ChatKi %s)" % (lage, wahl, wahl),
               not luecken, (luecken, aus[-300:]))
    # KONTROLLEN: die alte Regel (Claude Code nur, wenn gefunden; Plakette im
    # Chat nur, wenn gefunden) faellt in der Lage "nichts" auf.
    _w, env, gef, cli = _lage("nichts")
    k1 = _fmut_neu('        Sichtbar (El $U ("ki_holen_" + $id)) (-not $da)\n',
                   '        Sichtbar (El $U ("ki_holen_" + $id)) ($id -ne '
                   '"claude_code" -and -not $da)\n        if ($id -eq '
                   '"claude_code") { Sichtbar (El $U "ki_karte_claude_code") '
                   '$da }\n')
    k2 = _fmut_neu('        Sichtbar (El $U ("chat_marke_" + $k)) $true\n',
                   '        Sichtbar (El $U ("chat_marke_" + $k)) '
                   '([bool]$S.CliDa[$k])\n')
    rk1, _a = fenster_lauf(w, p, zeig % "claude", vorher=py_da, env=env,
                           aus=aus_z, fenster=k1)
    rk2, _a = fenster_lauf(w, p, zeig % "claude", vorher=py_da, env=env,
                           aus=aus_z, fenster=k2)
    pruefe("I36-K KONTROLLEN: Claude Code ohne Karte und die Chat-Plakette nur "
           "bei Gefundenem fielen auf",
           lage_pruefen(rk1, gef, cli, "claude")
           and lage_pruefen(rk2, gef, cli, "claude"))

    # I36b "Nochmal suchen": Kreisel + "Suche ...", Knopf gesperrt, mindestens
    # 600 ms, dann was neu ist; die Zeile verschwindet wieder.
    welt, env, _g, _c = _lage("nur_apps")
    neu = os.path.join(welt["heim"], ".local", "bin", "claude.exe")
    zeile = ("@{ text = (El $U 'ki_suche_text').Text; zeile = (El $U "
             "'ki_suche').Visibility.ToString(); kreisel = (El $U "
             "'ki_kreisel').Visibility.ToString(); knopf = (El $U "
             "'ki_nochmal').IsEnabled }")
    schritte = ("KW; New-Item -ItemType Directory -Force -Path %s | Out-Null; "
                "Set-Content -LiteralPath %s -Value x; $t0 = Get-Date; "
                "K 'ki_nochmal'; $global:a1 = %s; $null = Pumpen { -not "
                "$S.Suche } 30; $global:ms = ((Get-Date) - $t0)."
                "TotalMilliseconds; $global:a2 = %s; $global:code = (El $U "
                "'ki_claude_code').IsChecked; K 'ki_nochmal'; $null = Pumpen "
                "{ -not $S.Suche } 30; $global:a3 = %s; $null = Pumpen { "
                "$false } 4.6; $global:a4 = %s"
                % (_ps_text(os.path.dirname(neu)), _ps_text(neu), zeile, zeile,
                   zeile, zeile))
    r, aus = fenster_lauf(w, p, schritte, vorher=py_da, env=env,
                          aus="@{ a1 = $global:a1; a2 = $global:a2; a3 = "
                              "$global:a3; a4 = $global:a4; ms = $global:ms; "
                              "code = $global:code }")
    a = r.get("aus") or {}
    pruefe("I36b 'Nochmal suchen': sofort Kreisel und 'Suche ...', Knopf "
           "gesperrt; nach >= 600 ms 'Gefunden: Claude Code' (neu, angehakt), "
           "beim zweiten Mal 'Nichts Neues gefunden'; nach 4 s ist die Zeile "
           "weg",
           a.get("a1") == {"text": texte["t_suche_laeuft"]["de"],
                           "zeile": "Visible", "kreisel": "Visible",
                           "knopf": False}
           and a.get("a2") == {"text": "Gefunden: Claude Code",
                               "zeile": "Visible", "kreisel": "Collapsed",
                               "knopf": True}
           and (a.get("a3") or {}).get("text") == texte["t_suche_nichts"]["de"]
           and (a.get("a4") or {}).get("zeile") == "Hidden"
           and (a.get("ms") or 0) >= 600 and a.get("code") is True,
           (a, aus[-300:]))
    # Die Ereignisschleife laeuft waehrend der Suche weiter (Fenster bleibt
    # bedienbar): mit einer Suche, die 1,5 s braucht.
    langsam = ("function KI-Finden { Start-Sleep -Milliseconds 1500; return , "
               "@() }")
    mess = ("$global:takte = New-Object System.Collections.ArrayList; $tt = "
            "New-Object System.Windows.Threading.DispatcherTimer; $tt.Interval "
            "= [TimeSpan]::FromMilliseconds(40); $tt.Add_Tick({ [void]"
            "$global:takte.Add([DateTime]::Now.Ticks) }); $tt.Start(); $null = "
            "Pumpen { $false } 1; $t0 = Get-Date; K 'ki_nochmal'; $null = "
            "Pumpen { -not $S.Suche } 30; $global:ms = ((Get-Date) - $t0)."
            "TotalMilliseconds; $null = Pumpen { $false } 1; $tt.Stop(); $global:luecke = 0; for ($i = 1; "
            "$i -lt $global:takte.Count; $i++) { $d = ($global:takte[$i] - "
            "$global:takte[$i - 1]) / 10000; if ($d -gt $global:luecke) { "
            "$global:luecke = $d } }")
    auf = "@{ luecke = $global:luecke; ms = $global:ms; n = $global:takte.Count }"
    r, aus = fenster_lauf(w, p, "KW; " + mess, vorher=py_da + "\n" + langsam,
                          env=env, aus=auf)
    km = _fmut_neu("(El $U $n).Add_Click({ $F = $global:OMCAD_F; "
                   "Suche-Starten $F.U $F.S })",
                   "(El $U $n).Add_Click({ $F = $global:OMCAD_F; "
                   "KI-Suchen $F.S; Weiter $F.U $F.S \"wo\" })")
    rk, ausk = fenster_lauf(w, p, "KW; " + mess, vorher=py_da + "\n" + langsam,
                            env=env, aus=auf, fenster=km)
    a, ak = r.get("aus") or {}, rk.get("aus") or {}
    pruefe("I36c die Suche laeuft im Hintergrund: bei 1,5 s Suche steht die "
           "Ereignisschleife nie laenger als 0,6 s (Anlegen des Runspace); KONTROLLE: die alte, "
           "direkte Suche haelt sie >= 1,4 s an",
           0 < (a.get("luecke") or 9999) < 600 and (a.get("ms") or 0) >= 1500
           and (ak.get("luecke") or 0) >= 1400, (a, ak, aus[-200:],
                                                 ausk[-200:]))

    # I36d "Zurueck" auf jeder Seite mit Fragen.
    _w, env, _g, _c = _lage("nur_apps")
    weg = ("K 'willkommen_weiter'; K 'wo_weiter'; K 'ki_zurueck'; "
           "K 'wo_zurueck'; K 'willkommen_weiter'; (El $U 'wo_chat')."
           "IsChecked = $true; K 'wo_weiter'; K 'chat_zurueck'; (El $U "
           "'wo_app').IsChecked = $true; K 'wo_weiter'; K 'ki_weiter'; "
           "K 'bereit_zurueck'")
    soll = ["willkommen", "wo", "ki", "wo", "willkommen", "wo", "chat_ki",
            "wo", "ki", "bereit", "ki"]
    r, aus = fenster_lauf(w, p, weg, vorher=py_da, env=env)
    t2, w2, p2 = attrappe(["userprofil_2026", "userprofil_%d" % ALT_JAHR],
                          ["2026", str(ALT_JAHR)])
    r2, aus2 = fenster_lauf(w2, p2, "KW; K 'ki_weiter'; (El $U "
                            "'profil_wahl_1').IsChecked = $true; K "
                            "'profil_weiter'; K 'version_zurueck'; K "
                            "'profil_zurueck'", vorher=py_da, env=env)
    py_fehlt = ("function Finde-Python { return $null }\n"
                "function Python-Weg { return 'python.org' }")
    r3, aus3 = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'python_ja'; K "
                            "'bereit_zurueck'; $global:ja = $S.PythonJa; K "
                            "'python_zurueck'", vorher=py_fehlt, env=env,
                            aus="$global:ja")
    km = _fmut_neu("        if ($v[$i] -eq $S.Seite -or $FRAGE_SEITEN "
                   "-notcontains $v[$i]) { continue }",
                   "        if ($FRAGE_SEITEN -notcontains $v[$i]) { continue }")
    rk, _a = fenster_lauf(w, p, weg, vorher=py_da, env=env, fenster=km)
    pruefe("I36d 'Zurueck' auf jeder Seite (Wo, KI-App, Chat-KI, Bereit, "
           "Welches Cadwork, Version, Python) fuehrt zur Seite davor; die "
           "Antwort dort gilt wieder als offen; KONTROLLE: ohne das "
           "Ueberspringen der eigenen Seite bliebe es stehen",
           r.get("v") == soll and r2.get("v") == [
               "willkommen", "wo", "ki", "profil", "version", "profil", "ki"]
           and r3.get("v") == ["willkommen", "wo", "ki", "python", "bereit",
                               "python", "ki"] and r3.get("aus") is False
           and rk.get("v") != soll,
           (r.get("v"), r2.get("v"), r3.get("v"), r3.get("aus"), rk.get("v"),
            aus[-200:]))

    # I36e nur die KI-App gewaehlt: "Fertig" bietet den Chat in Cadwork an.
    fertig = ("$S.Ergebnis = [pscustomobject]@{ fertig = $true; kiListe = "
              "@() }; Seite-Zeigen $U $S 'fertig'; Fertig-Fuellen $U $S; "
              "$global:sicht = (El $U 'fertig_chat_dazu').Visibility."
              "ToString()")
    r, aus = fenster_lauf(w, p, "KW; K 'ki_weiter'; " + fertig + "; K "
                          "'fertig_chat_dazu'; (El $U 'chat_codex').IsChecked "
                          "= $true; K 'chat_weiter'", vorher=py_da, env=env,
                          aus="@{ sicht = $global:sicht; wo = $S.Wo }")
    r2, aus2 = fenster_lauf(w, p, "K 'willkommen_weiter'; (El $U 'wo_beides')"
                            ".IsChecked = $true; K 'wo_weiter'; " + fertig,
                            vorher=py_da, env=env, aus="$global:sicht")
    a = r.get("aus") or {}
    pruefe("I36e nur 'In deiner KI-App' gewaehlt: auf 'Fertig' steht 'Chat in "
           "Cadwork auch einrichten' -> Welche KI im Chat -> Bereit mit "
           "-ChatKi codex und den Apps; KONTROLLE: mit 'Beides' steht es nicht "
           "da",
           a.get("sicht") == "Visible" and a.get("wo") == "beides"
           and r.get("v", [])[-2:] == ["chat_ki", "bereit"]
           and _wert(r.get("args") or [], "-ChatKi") == "codex"
           and _wert(r.get("args") or [], "-KiNur") == "claude_desktop,codex"
           and r2.get("aus") == "Collapsed",
           (a, r.get("v"), r.get("args"), r2.get("aus"), aus[-200:]))


def pruefe_logos(env, py_da):
    gut = paket_attrappe_app()
    nur = paket_attrappe_app(nur_store=True)
    kaputt = paket_attrappe_app(kaputt=True)
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                      "WindowsPowerShell", "v1.0", "powershell.exe")
    code = ("[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding "
            "$false\n. %s -NurFunktionen\nWpf-Laden\n"
            "$b = { param($p) $x = Logo-Bild $p; if ($x) { $x.PixelWidth } "
            "else { 0 } }\n"
            "@{ m1 = (Manifest-Logo %s); m2 = (Manifest-Logo %s); m3 = "
            "(Manifest-Logo %s); b1 = (& $b (Manifest-Logo %s)); b2 = (& $b "
            "(Manifest-Logo %s)); b3 = (& $b %s); b4 = (& $b 'C:\\gibt\\es\\"
            "nicht.png') } | ConvertTo-Json -Compress"
            % (_ps_text(FENSTER), _ps_text(gut), _ps_text(nur),
               _ps_text(os.path.join(gut, "fehlt")), _ps_text(gut),
               _ps_text(kaputt), _ps_text(ps)))
    r, aus = _ps_fenster(code)
    pruefe("I37a Symbol aus einem Store-Paket (Attrappe in Temp): Manifest -> "
           "Square44x44Logo in targetsize-48 fuer helle Flaechen (vor dem weissen), sonst Logo in "
           "scale-100; ohne Manifest nichts; Bild (auf 64 px) aus dem PNG, das "
           "Symbol einer exe (powershell.exe), kaputtes oder fehlendes PNG -> "
           "nichts",
           (r.get("m1") or "").endswith(
               "Square44x44Logo.targetsize-48_altform-lightunplated.png")
           and (r.get("m2") or "").endswith("StoreLogo.scale-100.png")
           and r.get("m3") is None and r.get("b1") == 64 and r.get("b2") == 0
           and (r.get("b3") or 0) >= 16 and r.get("b4") == 0,
           (r, aus[-300:]))
    t, w, p = attrappe(["userprofil_2026"], ["2026"])

    def lauf(paket, schalter=""):
        vor = py_da + ("\nfunction App-Paket-Ort($name) { if ($name -eq "
                       "'Claude') { return %s }; return $null }"
                       % _ps_text(paket))
        return fenster_lauf(
            w, p, "Seite-Zeigen $U $S 'ki'; $U.Wurzel.Measure((New-Object "
            "System.Windows.Size 640, 480)); $U.Wurzel.Arrange((New-Object "
            "System.Windows.Rect 0, 0, 640, 480)); $null = Pumpen { "
            "-not $S.LogoSuche } 20; $U.Wurzel.UpdateLayout(); "
            "$global:l = @{}; foreach ($n in 'ki_logo_claude_desktop', "
            "'keine_claude', 'ki_logo_codex', 'keine_codex') { $e = El $U $n; "
            "$global:l[$n] = ($null -ne $e.Tag) }; $c = El $U 'ki_logo_codex'; "
            "$global:ersatz = $c.Template.FindName('ersatz', $c).Visibility."
            "ToString(); $d = El $U 'ki_logo_claude_desktop'; $global:ersatz2 "
            "= $d.Template.FindName('ersatz', $d).Visibility.ToString()",
            vorher=vor, env=env, schalter=schalter,
            aus="@{ l = $global:l; codex = $global:ersatz; claude = "
                "$global:ersatz2 }")
    r, aus = lauf(gut)
    rk, _a = lauf(kaputt)
    ro, _a = lauf(gut, " -OhneLogos")
    a, ak, ao = r.get("aus") or {}, rk.get("aus") or {}, ro.get("aus") or {}
    pruefe("I37b im Fenster: Claude Desktop (Paket-Attrappe) mit seinem "
           "Symbol auf 'Deine KI-App' und 'Holen'; die ChatGPT-App (kein "
           "Paket) mit dem Strich-Symbol; kaputtes PNG -> Strich-Symbol; mit "
           "-OhneLogos nie ein fremdes Symbol",
           a.get("l") == {"ki_logo_claude_desktop": True, "keine_claude": True,
                          "ki_logo_codex": False, "keine_codex": False}
           and a.get("codex") == "Visible" and a.get("claude") == "Collapsed"
           and not any((ak.get("l") or {"x": True}).values())
           and ak.get("claude") == "Visible"
           and not any((ao.get("l") or {"x": True}).values()),
           (a, ak, ao, aus[-300:]))
    r, aus = _ps_fenster(". %s -NurFunktionen -Rendern %s\n@{ o = "
                         "$global:OMCAD_F.OhneLogos } | ConvertTo-Json "
                         "-Compress" % (_ps_text(FENSTER), _ps_text(
                             tempfile.gettempdir())))
    r2, aus2 = _ps_fenster(". %s -NurFunktionen\n@{ o = $global:OMCAD_F."
                           "OhneLogos } | ConvertTo-Json -Compress"
                           % _ps_text(FENSTER))
    pruefe("I37c -Rendern (Bilder der Anleitung) liest nie ein fremdes Symbol "
           "(OhneLogos); KONTROLLE: ohne -Rendern schon",
           r.get("o") is True and r2.get("o") is False, (r, r2))


# --- I38 erlaubte und getestete Cadwork-Jahre (vorbereitet 2026-10-10) ------
# Zwei Werte in install.ps1 ($CADWORK_GETESTET, $CADWORK_ERLAUBT_AB)
# entscheiden: getestet ohne Warnung, ab ERLAUBT_AB "nicht getestet, sollte
# gehen", davor die Warnung. Das Gate liest beide aus der Quelle und prueft
# die Regel mit ihnen UND mit gesetzten Werten (2026 getestet, ab 2024).

def _jahre_aus(quelle):
    g = re.search(r"(?m)^\$CADWORK_GETESTET = @\(([^)]*)\)", quelle).group(1)
    a = re.search(r"(?m)^\$CADWORK_ERLAUBT_AB = (\d+)", quelle).group(1)
    return [int(x) for x in re.findall(r"\d+", g)], int(a)


#: Aus der QUELLE (Regel 3): getestete Jahre und das erste erlaubte. Die
#: Zellen, deren Absicht "nicht unterstuetzte Version warnt/bricht ab" ist,
#: nehmen ALT_JAHR = das Jahr davor (seit 2026-10-10: 2024) - nie eine
#: eigene Jahreszahl.
GETESTET, ERLAUBT_AB = _jahre_aus(open(INSTALL, encoding="ascii").read())
ALT_JAHR = ERLAUBT_AB - 1


def _jahre_mutante(getestet, ab):
    q = open(INSTALL, encoding="ascii").read()
    q2 = re.sub(r"(?m)^\$CADWORK_GETESTET = @\([^)]*\)",
                "$CADWORK_GETESTET = @(%s)" % ", ".join(map(str, getestet)), q)
    q2 = re.sub(r"(?m)^\$CADWORK_ERLAUBT_AB = \d+",
                "$CADWORK_ERLAUBT_AB = %d" % ab, q2)
    assert q2 != q or (_jahre_aus(q) == (getestet, ab))
    d = tempfile.mkdtemp(prefix="omcad_jahre_")
    _temp.append(d)
    z = os.path.join(d, "install.ps1")
    with open(z, "w", encoding="ascii") as fh:
        fh.write(q2)
    return z


def pruefe_versionen(env, py_da):
    quelle = open(INSTALL, encoding="ascii").read()
    jahre = [2023, 2024, 2025, 2026, 2027]

    def soll(getestet, ab):
        return ["getestet" if j in getestet else "ungetestet" if j >= ab
                else "nicht" for j in jahre]

    def ist(ps1):
        code = "$aus = @()\n"
        for j in jahre:
            code += ("$v = Version-Pruefen 'C:\\x\\userprofil_%d\\3d\\API.x64' "
                     "@(2023, 2024, 2025, 2026, 2027) 'C:\\x'; $aus += @($v.Art "
                     "+ '|' + $v.Passt)\n" % j)
        r = ps_funktionen(code + "@{ a = $aus } | ConvertTo-Json -Compress",
                          ps1)
        return [x.split("|")[0] for x in r.get("a", [])], \
            [x.split("|")[1] == "True" for x in r.get("a", [])]
    g, ab = _jahre_aus(quelle)
    a1, p1 = ist(None)
    mut = _jahre_mutante([2026], 2024)
    a2, p2 = ist(mut)
    pruefe("I38 Version-Pruefen nach $CADWORK_GETESTET %s / $CADWORK_ERLAUBT_AB "
           "%d aus der Quelle: %s; mit [2026] ab 2024: 2023 Warnung, 2024/2025/"
           "2027 'nicht getestet, sollte gehen', 2026 ohne Warnung"
           % (g, ab, dict(zip(jahre, a1))),
           a1 == soll(g, ab) and p1 == [x != "nicht" for x in soll(g, ab)]
           and a2 == soll([2026], 2024)
           and p2 == [False, True, True, True, True], (a1, p1, a2, p2))
    # I38b seit 2026-10-10 (Cadwork 2025 laeuft ueber die Qt-Schicht; seit
    # der Messung des Maintainers - 0.2.2 im echten Cadwork 2025 - auch
    # GETESTET): der ganze Installer MIT DEN WERTEN DER QUELLE in einer Welt
    # nur mit 2025 kopiert ohne Hinweis und ist vollstaendig; das Fenster
    # zeigt keine Sperrseite und auf "Bereit" keinen Hinweis.
    def welt_2025():
        return attrappe(["userprofil_2025"], ["2025"])

    def ganz(ps1_quelle):
        t, w, p = welt_2025()
        ps1 = paket_attrappe(ps1=ps1_quelle, fenster=True)
        datei = os.path.join(t, "erg.json")
        rc, aus = _lauf(["-File", ps1, "-OhnePause", "-OhneServer",
                         "-CadworkWurzel", w, "-CadworkProgramm", p,
                         "-ErgebnisDatei", datei])
        erg = json.load(open(datei, encoding="utf-8")) \
            if os.path.isfile(datei) else {}
        return rc, aus, erg, w, p, os.path.join(os.path.dirname(ps1),
                                                P.FENSTER)
    _sp, texte, _gl = P.fenster_texte()
    zeig = ("(@((El $U 'bereit_liste').Children | ForEach-Object { "
            "$_.Children[1].Text }) -join ' | ')")
    rc, aus, erg, w, p, fenster = ganz(None)
    r, a_f = fenster_lauf(w, p, "KW; K 'ki_weiter'", vorher=py_da, env=env,
                          fenster=fenster, aus=zeig)
    pruefe("I38b Werte der Quelle (%s ab %d), nur Cadwork 2025: 2025 ist "
           "getestet; install.ps1 kopiert (Rueckgabe 0, KEIN 'nicht "
           "getestet', vollstaendig); das Fenster geht ohne Sperrseite auf "
           "'Bereit', dort die Zeile ohne Hinweis" % (g, ab),
           ab <= 2025 and 2025 in g
           and rc == 0 and kopiert_in(w) == ["userprofil_2025"]
           and erg.get("pluginText") == "Cadwork 2025 im Profil "
           "userprofil_2025"
           and "nicht getestet" not in aus
           and erg.get("fertig") is True
           and "NICHT vollstaendig" not in aus
           and r.get("seite") == "bereit" and "version" not in r.get("v", [])
           and (r.get("aus") or "").split(" | ")[0] == texte[
               "t_bereit_plugin"]["de"].format(2025)
           and texte["t_bereit_plugin_ungetestet"]["de"].format(2025)
           not in (r.get("aus") or ""),
           (rc, erg.get("pluginText"), erg.get("fertig"), r.get("v"),
            r.get("aus"), aus[-300:], a_f[-300:]))
    # KONTROLLE: der Stand vor 2026-10-10 ([2026] ab 2026) in derselben
    # Welt: das Fenster zeigt die Warnseite, install.ps1 bricht ab.
    rc_k, aus_k, erg_k, w_k, p_k, fenster_k = ganz(_jahre_mutante([2026],
                                                                  2026))
    rk, _a = fenster_lauf(w_k, p_k, "KW; K 'ki_weiter'", vorher=py_da,
                          env=env, fenster=fenster_k)
    pruefe("I38b-K KONTROLLE: mit dem alten Stand ([2026] ab 2026) kommt fuer "
           "2025 die Warnseite, install.ps1 kopiert nichts (Rueckgabe 3)",
           rk.get("seite") == "version" and rc_k == 3
           and kopiert_in(w_k) == [] and erg_k.get("fertig") is False,
           (rk.get("v"), rc_k, kopiert_in(w_k), aus_k[-300:]))
    # KONTROLLE 2: der Stand von 0.2.2 ([2026] ab 2025) - 2025 erlaubt, aber
    # nicht getestet: kopiert MIT Hinweis, vollstaendig, das Fenster nennt
    # ihn auf "Bereit" (so bleibt der Weg "nicht getestet" gemessen, fuer ein
    # spaeteres Jahr).
    rc_2, aus_2, erg_2, w_2, p_2, fenster_2 = ganz(_jahre_mutante([2026],
                                                                  2025))
    r2, _a = fenster_lauf(w_2, p_2, "KW; K 'ki_weiter'", vorher=py_da,
                          env=env, fenster=fenster_2, aus=zeig)
    pruefe("I38b-K2 KONTROLLE: mit dem Stand von 0.2.2 ([2026] ab 2025) "
           "bekaeme 2025 den Hinweis 'nicht getestet' - im Textfenster, im "
           "Ergebnis und auf 'Bereit' - und waere trotzdem vollstaendig",
           rc_2 == 0 and kopiert_in(w_2) == ["userprofil_2025"]
           and "nicht getestet" in erg_2.get("pluginText", "")
           and "nicht getestet, sollte aber gehen" in aus_2
           and erg_2.get("fertig") is True and r2.get("seite") == "bereit"
           and texte["t_bereit_plugin_ungetestet"]["de"].format(2025)
           in (r2.get("aus") or ""),
           (rc_2, erg_2.get("pluginText"), r2.get("aus"), aus_2[-300:]))
    # I38c die Saetze des Fensters, die Jahre nennen, nennen jedes getestete
    # Jahr und das erste erlaubte - in allen vier Sprachen (die Texte sind
    # fest, die Jahre stehen in install.ps1). KONTROLLE: der alte Satz
    # (nur 2026) faellt auf.
    def jahre_fehlen(je):
        return [(k, sp) for k in ("t_auf_diesem_pc_gibt",
                                  "t_dort_startet_open_mcp")
                for sp, v in je[k].items()
                if not all(str(j) in v for j in list(g) + [ab])]
    alt_texte = {k: dict(v) for k, v in texte.items()}
    alt_texte["t_dort_startet_open_mcp"]["de"] = (
        "Dort startet Open MCP CAD nicht. Installiere zuerst Cadwork 3D 2026."
        " Oder installiere trotzdem, wenn du genau weisst, was du tust.")
    pruefe("I38c 'Welches Cadwork?' und die Warnseite nennen %s und %d in "
           "de/fr/it/en; KONTROLLE: der alte deutsche Satz (nur 2026) faellt "
           "auf" % (g, ab), not jahre_fehlen(texte)
           and jahre_fehlen(alt_texte) == [("t_dort_startet_open_mcp", "de")],
           (jahre_fehlen(texte), jahre_fehlen(alt_texte)))


# --- I39/I40 mehrere Cadwork-Versionen auf einem PC (seit 2026-10-10) ------
#
# Rueckmeldung 2026-10-10: auf einem Laptop stehen Cadwork 2025 und 2026
# nebeneinander (Profilordner auch GROSS geschrieben, USERPROFIL_2025). Das
# Einrichtungsfenster hakt jetzt jedes Profil ab $CADWORK_ERLAUBT_AB mit
# installiertem Cadwork vorab an (Profil-Vorauswahl in install.ps1) und
# uebergibt bei mehr als einem Haken -Profile "a;b"; install.ps1 prueft und
# beliefert jedes einzeln. Vertrag mit dem Dock: es startet nach einem
# Update bzw. fuer ein Cadwork ohne Open MCP CAD 1_INSTALLIEREN.cmd OHNE
# Schalter - die Vorauswahl muss also jedes erlaubte, installierte Cadwork
# enthalten (I39a, I39f).

ALT_PROFILE_STAND = "fc4dbfa"


def _alt_stand(dateien):
    """Ein Ordner mit den Dateien aus ALT_PROFILE_STAND (vor den
    Haken, RadioButtons) - fuer die Kontrollen. -> Pfad auf das Fenster."""
    d = tempfile.mkdtemp(prefix="omcad_alt_profile_")
    _temp.append(d)
    for n in dateien:
        roh = subprocess.run(["git", "show", ALT_PROFILE_STAND +
                              ":verteilung/" + n], cwd=REPO,
                             capture_output=True, check=True).stdout
        with open(os.path.join(d, n), "wb") as fh:
            fh.write(roh)
    return d


def mehr_welt(mit_2024=True):
    """Profile 2027 (ohne EXE_2027), 2026 (mit Open MCP CAD schon darin),
    USERPROFIL_2025 (gross, ohne Open MCP CAD) und - wenn `mit_2024` - das
    Jahr vor $CADWORK_ERLAUBT_AB, je mit EXE_<Jahr> ausser 2027.
    -> (t, wurzel, programm, {Jahr: API-Pfad})"""
    alt = "userprofil_%d" % ALT_JAHR
    profile = ["userprofil_2027", "userprofil_2026", "USERPROFIL_2025"]
    exes = ["2026", "2025"]
    if mit_2024:
        profile.append(alt)
        exes.append(str(ALT_JAHR))
    t, w, p = attrappe(profile, exes)
    api = {int(re.search(r"\d+$", n).group(0)): os.path.join(w, n, "3d",
                                                             "API.x64")
           for n in profile}
    os.makedirs(os.path.join(api[2026], "Open MCP CAD"))
    return t, w, p, api


def pruefe_mehrere_profile(env, py_da):
    _sp, texte, _gl = P.fenster_texte()

    # --- I39a Vorauswahl: jedes erlaubte Jahr mit installiertem Cadwork ---
    def vorauswahl(w, p, ps1=None):
        return ps_funktionen(
            "$k = @(Profil-Kandidaten '%s' '%s')\n$v = Profil-Vorauswahl $k "
            "'%s'\n@{ namen = @($k | ForEach-Object { $_.Name }); v = @($v | "
            "ForEach-Object { $k[$_].Name }) } | ConvertTo-Json -Compress"
            % (w, p, p), ps1)
    t, w, p, api = mehr_welt()
    r = vorauswahl(w, p)
    t2, w2, p2 = attrappe(["userprofil_2027", "userprofil_%d" % ALT_JAHR],
                          [str(ALT_JAHR)])
    r2 = vorauswahl(w2, p2)
    alt = "userprofil_%d" % ALT_JAHR
    pruefe("I39a Vorauswahl (Profil-Vorauswahl) bei 2027 ohne EXE, 2026, "
           "USERPROFIL_2025 (gross geschrieben, ohne Open MCP CAD) und %d: "
           "2026 und 2025 angehakt, %d (zu alt) und 2027 (kein Cadwork) "
           "nicht; trifft nichts zu, die bisherige Vorgabe (%s)"
           % (ALT_JAHR, ALT_JAHR, alt),
           r.get("namen") == ["userprofil_2027", "userprofil_2026",
                              "USERPROFIL_2025", alt]
           and r.get("v") == ["userprofil_2026", "USERPROFIL_2025"]
           and r2.get("v") in ([alt], alt), (r, r2))
    zeile = ("        if ($k[$i].Installiert -and $k[$i].Nummer -ge "
             "$CADWORK_ERLAUBT_AB) { $aus += $i }")
    k1 = vorauswahl(w, p, mutante_ps(zeile, zeile.replace(
        "$k[$i].Installiert -and ", "")))
    k2 = vorauswahl(w, p, mutante_ps(zeile, zeile.replace(
        " -and $k[$i].Nummer -ge $CADWORK_ERLAUBT_AB", "")))
    pruefe("I39a-K KONTROLLEN: ohne die Pruefung auf ein installiertes "
           "Cadwork kaeme 2027 dazu, ohne die Jahresgrenze %d" % ALT_JAHR,
           "userprofil_2027" in (k1.get("v") or [])
           and alt in (k2.get("v") or []), (k1, k2))

    # --- I39b das Fenster: Haken, vorab angehakt, -Profile ----------------
    zeig = ("(@((El $U 'bereit_liste').Children | ForEach-Object { "
            "$_.Children[1].Text }) -join ' | ')")
    merken = ("$global:h = @(0..3 | ForEach-Object { (El $U ('profil_wahl_' "
              "+ $_)).IsChecked -eq $true }); $global:we = (El $U "
              "'profil_weiter').IsEnabled; $global:typ = (El $U "
              "'profil_wahl_0').GetType().Name; $global:emp = @(0..3 | "
              "ForEach-Object { (El $U ('profil_wahl_' + $_)).Content."
              "Children[1].Text })")
    aus_b = ("@{ h = $global:h; we = $global:we; typ = $global:typ; emp = "
             "$global:emp; liste = %s }" % zeig)
    r, a_b = fenster_lauf(w, p, "KW; K 'ki_weiter'; " + merken + "; "
                          "K 'profil_weiter'", vorher=py_da, env=env,
                          aus=aus_b)
    x = r.get("aus") or {}
    a = r.get("args") or []
    emp = texte["t_profil_empfohlen"]["de"]
    pruefe("I39b Fenster, vier Profile: 'Welches Cadwork?' mit Haken "
           "(CheckBox), 2026 und 2025 vorab angehakt und 'empfohlen', 2027 "
           "und %d nicht; 'Weiter' -> Bereit (keine Warnung) mit einer Zeile "
           "je Cadwork; Argument -Profile '<2026>;<2025>', kein -Profil"
           % ALT_JAHR,
           x.get("typ") == "CheckBox" and x.get("h") == [False, True, True,
                                                         False]
           and x.get("we") is True
           and [emp in (e or "") for e in x.get("emp") or []] == [
               False, True, True, False]
           and r.get("v") == ["willkommen", "wo", "ki", "profil", "bereit"]
           and _wert(a, "-Profile") == api[2026] + ";" + api[2025]
           and "-Profil" not in a
           and texte["t_bereit_plugin"]["de"].format(2026) in (
               x.get("liste") or "")
           # 2025 ist seit 2026-10-10 getestet: ohne Hinweis
           and texte["t_bereit_plugin"]["de"].format(2025) in (
               x.get("liste") or "")
           and texte["t_bereit_plugin_ungetestet"]["de"].format(2025)
           not in (x.get("liste") or ""), (r, a_b[-400:]))
    alt_d = _alt_stand([P.FENSTER, P.FENSTER_XAML, P.FENSTER_TEXTE,
                        "install.ps1"])
    rk, a_k = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'profil_weiter'",
                           vorher=py_da, env=env,
                           fenster=os.path.join(alt_d, P.FENSTER))
    pruefe("I39b-K KONTROLLE: das alte Fenster (eine Wahl) gibt in "
           "derselben Welt nur -Profil 2026 weiter - 2025 fehlte",
           _wert(rk.get("args") or [], "-Profil") == api[2026]
           and "-Profile" not in (rk.get("args") or []), (rk, a_k[-300:]))

    # --- I39c Haken: ohne keinen 'Weiter', zwei mit einem zu alten -------
    schritte = (
        "KW; K 'ki_weiter'; K 'profil_wahl_1'; K 'profil_wahl_2'; "
        "$global:leer = (El $U 'profil_weiter').IsEnabled; "
        "$global:n0 = @($S.ProfilWahl).Count; "
        "try { Klick $U 'profil_weiter'; $global:gesperrt = $false } catch "
        "{ $global:gesperrt = $true }; "
        "K 'profil_wahl_3'; $global:eins = (El $U 'profil_weiter').IsEnabled; "
        "K 'profil_wahl_1'; K 'profil_weiter'; "
        "$global:satz = (El $U 'version_text').Text; K 'version_trotzdem'")
    aus_c = ("@{ leer = $global:leer; n0 = $global:n0; gesperrt = "
             "$global:gesperrt; eins = $global:eins; satz = $global:satz; "
             "liste = %s }" % zeig)
    r, a_c = fenster_lauf(w, p, schritte, vorher=py_da, env=env, aus=aus_c)
    x = r.get("aus") or {}
    a = r.get("args") or []
    satz = texte["t_version_mehrere"]["de"].format(ERLAUBT_AB,
                                                    "Cadwork %d" % ALT_JAHR)
    pruefe("I39c Haken per Klick: beide ab -> 'Weiter' gesperrt (auch ein "
           "Klick darauf tut nichts); %d an -> 'Weiter' geht; 2026 + %d -> "
           "Warnseite nennt nur %d und den Weg zurueck; 'Trotzdem' -> Bereit, "
           "-Profile '<2026>;<%d>' und -TrotzdemKopieren"
           % (ALT_JAHR, ALT_JAHR, ALT_JAHR, ALT_JAHR),
           x.get("leer") is False and x.get("n0") == 0
           and x.get("gesperrt") is True and x.get("eins") is True
           and x.get("satz") == satz
           and r.get("v") == ["willkommen", "wo", "ki", "profil", "profil",
                              "profil", "profil", "profil", "version",
                              "bereit"]
           and _wert(a, "-Profile") == api[2026] + ";" + api[ALT_JAHR]
           and "-TrotzdemKopieren" in a
           and texte["t_bereit_plugin_trotzdem"]["de"].format(ALT_JAHR) in (
               x.get("liste") or ""), (r, a_c[-400:]))
    km = _fmut_neu('    (El $U "profil_weiter").IsEnabled = ((Profil-Wahl $S)'
                   '.Count -gt 0)', '    (El $U "profil_weiter").IsEnabled = '
                   '$true')
    rk, _a = fenster_lauf(w, p, schritte, vorher=py_da, env=env, aus=aus_c,
                          fenster=km)
    pruefe("I39c-K KONTROLLE: ohne die Sperre waere 'Weiter' ohne Haken frei",
           (rk.get("aus") or {}).get("leer") is True, rk.get("aus"))

    # --- I39d ein Haken -> -Profil wie bisher; KONTROLLE ohne -Profile ---
    r, a_d = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'profil_wahl_2'; "
                          "K 'profil_weiter'", vorher=py_da, env=env)
    a = r.get("args") or []
    km = _fmut_neu('    if ($pf.Count -gt 1) { $a += @("-Profile", '
                   '($pf -join ";")) }', '    if ($false) { }')
    rk, _a = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'profil_weiter'",
                          vorher=py_da, env=env, fenster=km)
    pruefe("I39d nur 2026 angehakt -> -Profil <2026> (kein -Profile, wie "
           "vor 2026-10-10); KONTROLLE: ohne die Zeile fuer -Profile ginge "
           "bei zwei Haken nur das erste weiter",
           _wert(a, "-Profil") == api[2026] and "-Profile" not in a
           and r.get("v") == ["willkommen", "wo", "ki", "profil", "profil",
                              "bereit"]
           and "-Profile" not in (rk.get("args") or [])
           and _wert(rk.get("args") or [], "-Profil") == api[2026],
           (r, rk.get("args"), a_d[-300:]))

    # --- I39e reine Teile: Fehlersatz "teilweise", Jahre auf "Fertig" ----
    r, a_e = _ps_fenster(
        ". '%s' -NurFunktionen\n"
        "$S = Zustand-Neu; $S.Ergebnis = [pscustomobject]@{ profile = @("
        "[pscustomobject]@{ status = 'ok'; nummer = 2026 }, "
        "[pscustomobject]@{ status = 'fehlt'; nummer = 2025 }, "
        "[pscustomobject]@{ status = 'version'; nummer = %d }, "
        "[pscustomobject]@{ status = 'ok'; nummer = $null }) }\n"
        "$S2 = Zustand-Neu; $S2.Kandidaten = @([pscustomobject]@{ Nummer = "
        "2026 }, [pscustomobject]@{ Nummer = 2025 }); $S2.ProfilWahl = @(1, 0)\n"
        "@{ f = @((Fehler-Schluessel @{ plugin = 'teilweise'; server = "
        "'uebersprungen' }), (Fehler-Schluessel @{ plugin = 'teilweise'; "
        "server = 'fehlt'; serverText = 'pip' })); j = (Fertig-Jahre $S); "
        "j2 = (Fertig-Jahre $S2) } | ConvertTo-Json -Compress"
        % (FENSTER, ALT_JAHR))
    pruefe("I39e Fehlersatz bei 'teilweise' (nach dem Server), 'Fertig' nennt "
           "die Jahre, in die kopiert wurde (ok/version, ohne unbekannte), "
           "ohne Ergebnis die angehakten",
           r.get("f") == ["t_fehler_teilweise", "t_fehler_server"]
           and r.get("j") == [2026, ALT_JAHR] and r.get("j2") == [2025, 2026],
           (r, a_e[-300:]))

    # --- I39f der ganze Weg: Fenster -> install.ps1 in zwei Profile ------
    warten = ("$global:ok = Pumpen { $S.Seite -eq 'fertig' -or $S.Seite -eq "
              "'fehler' } 240")

    def kette(alte_dateien=False):
        ps1 = paket_attrappe(fenster=True)
        unter = os.path.dirname(ps1)
        if alte_dateien:
            d = _alt_stand([P.FENSTER, P.FENSTER_XAML, P.FENSTER_TEXTE,
                            "install.ps1"])
            for n in os.listdir(d):
                shutil.copy(os.path.join(d, n), os.path.join(unter, n))
        t, w, p, api = mehr_welt(mit_2024=False)
        prot = os.path.join(t, "installer.log")
        r, a = fenster_lauf(w, p, "KW; K 'ki_weiter'; K 'profil_weiter'; "
                            "K 'bereit_installieren'; " + warten + "; "
                            "$global:v += $S.Seite", vorher=py_da, env=env,
                            ohne_server=True, fenster=os.path.join(
                                unter, P.FENSTER), protokoll=prot,
                            aus="$global:ok")
        log = open(prot, encoding="utf-8").read() \
            if os.path.isfile(prot) else ""
        return r, a, w, api, log
    r, a_f, w, api, log = kette()
    jahre = "2026 %s 2025" % texte["t_und"]["de"]
    pruefe("I39f Fenster -> install.ps1 (Kindprozess): 2026 und 2025 vorab "
           "angehakt, 'Installieren' -> beide bekommen das Plugin (2025 "
           "hatte keins), Rueckgabe 0, 'Fertig' nennt '%s'" % jahre,
           r.get("aus") is True and r.get("v", [])[-1:] == ["fertig"]
           and r.get("rc") == 0
           and kopiert_in(w) == ["USERPROFIL_2025", "userprofil_2026"]
           and texte["t_fertig_cadwork"]["de"].format(jahre) in (
               r.get("fertig_ki") or "")
           and "-Profile" in log and "Rueckgabe des Installers: 0" in log,
           (r, kopiert_in(w), log[-600:], a_f[-400:]))
    rk, a_k, wk, _api, _log = kette(alte_dateien=True)
    pruefe("I39f-K KONTROLLE: mit altem Fenster und install.ps1 kommt das "
           "Plugin in derselben Welt nur nach 2026 - 2025 bliebe ohne",
           kopiert_in(wk) == ["userprofil_2026"], (kopiert_in(wk),
                                                   a_k[-300:]))

    # --- I40 install.ps1 -Profile -------------------------------------------
    def lauf(w, p, *extra, ps1=None):
        datei = os.path.join(tempfile.mkdtemp(prefix="omcad_erg_"), "e.json")
        _temp.append(os.path.dirname(datei))
        paket = paket_attrappe(ps1=ps1)
        rc, aus = _lauf(["-File", paket, "-OhnePause", "-OhneServer",
                         "-CadworkWurzel", w, "-CadworkProgramm", p,
                         "-ErgebnisDatei", datei] + list(extra))
        erg = json.load(open(datei, encoding="utf-8")) \
            if os.path.isfile(datei) else {}
        return rc, aus, erg

    def ergebnis(aus):
        return aus.split("== Ergebnis", 1)[-1]
    t, w, p, api = mehr_welt()
    rc, aus, erg = lauf(w, p, "-Profile", api[2026] + ";" + api[2025])
    pr = erg.get("profile") or []
    pruefe("I40a -Profile '<2026>;<USERPROFIL_2025>': beide bekommen Plugin "
           "und Anleitung, Schritt 2 einmal, im Ergebnis je Profil eine "
           "Zeile, in -ErgebnisDatei je Profil ein Eintrag (ok), vollstaendig, "
           "Rueckgabe 0",
           rc == 0 and kopiert_in(w) == ["USERPROFIL_2025", "userprofil_2026"]
           and anleitung_im_plugin(w, "USERPROFIL_2025") == PDF_ATTRAPPE
           and anleitung_im_plugin(w, "userprofil_2026") == PDF_ATTRAPPE
           and aus.count("== 2/5") == 1 and aus.count("== 1/5") == 1
           and ergebnis(aus).count("Cadwork-Plugin: kopiert nach ") == 2
           and "Cadwork-Plugin: kopiert nach %s, Cadwork-Version passt" % (
               api[2025]) in aus
           and [(e.get("pfad"), e.get("nummer"), e.get("status")) for e in pr]
           == [(api[2026], 2026, "ok"), (api[2025], 2025, "ok")]
           and erg.get("plugin") == "ok" and erg.get("fertig") is True
           and "NICHT vollstaendig" not in aus, (rc, kopiert_in(w), erg,
                                                 aus[-900:]))
    alt_d = _alt_stand(["install.ps1"])
    t, wk, pk, apik = mehr_welt()
    rck, ausk, ergk = lauf(wk, pk, "-Profile", apik[2026] + ";" + apik[2025],
                           ps1=os.path.join(alt_d, "install.ps1"))
    # (Gemessen: ein Skript ohne CmdletBinding legt den unbekannten
    # Schalter still in $args - der alte Installer nimmt dann die Vorgabe.)
    pruefe("I40a-K KONTROLLE: der alte Installer kennt -Profile nicht, "
           "uebergeht es still und kopiert nur in die Vorgabe 2026 - 2025 "
           "bliebe ohne", kopiert_in(wk) == ["userprofil_2026"]
           and "Cadwork-Plugin: kopiert nach %s" % apik[2025] not in ausk,
           (rck, kopiert_in(wk), ausk[-300:]))

    t, w, p, api = mehr_welt()
    rc, aus, erg = lauf(w, p, "-Profile", api[2026] + ";" + api[ALT_JAHR])
    pr = {e.get("nummer"): e for e in erg.get("profile") or []}
    alt = "userprofil_%d" % ALT_JAHR
    pruefe("I40b -Profile mit 2026 und %d: 2026 bekommt das Plugin, %d wird "
           "mit Grund uebersprungen; Ergebnis und -ErgebnisDatei nennen beide "
           "(%d 'fehlt'), 'teilweise', NICHT vollstaendig, Rueckgabe 3"
           % (ALT_JAHR, ALT_JAHR, ALT_JAHR),
           rc == 3 and kopiert_in(w) == ["userprofil_2026"]
           and "Dieses Profil wird uebersprungen: " + api[ALT_JAHR] in aus
           and "Cadwork-Plugin: NICHT kopiert nach %s - Dieses Paket braucht "
           "Cadwork 3D %d oder neuer. Gefunden: Cadwork %d im Profil %s. "
           "Nichts kopiert." % (api[ALT_JAHR], ERLAUBT_AB, ALT_JAHR, alt) in aus
           and "Cadwork-Plugin: kopiert nach %s, Cadwork-Version passt" % (
               api[2026]) in aus
           and pr.get(2026, {}).get("status") == "ok"
           and pr.get(ALT_JAHR, {}).get("status") == "fehlt"
           and erg.get("plugin") == "teilweise" and erg.get("fertig") is False
           and "NICHT vollstaendig" in aus, (rc, kopiert_in(w), erg,
                                             aus[-900:]))
    t, w2, p2, api2 = mehr_welt()
    rc2, aus2, erg2 = lauf(w2, p2, "-Profile", api2[2026] + ";" +
                           api2[ALT_JAHR], "-TrotzdemKopieren")
    mut = mutante_ps('    if ($kopiert.Count -lt $geprueft.Count) { '
                     '$stand.Plugin = "teilweise" }\n    elseif',
                     '    if ($false) { }\n    elseif')
    t, w3, p3, api3 = mehr_welt()
    rc3, aus3, erg3 = lauf(w3, p3, "-Profile", api3[2026] + ";" +
                           api3[ALT_JAHR], ps1=mut)
    pruefe("I40b-K KONTROLLEN: mit -TrotzdemKopieren kommt es in beide "
           "('version', Rueckgabe 3); ohne 'teilweise' galte der Lauf mit "
           "einem uebersprungenen Profil als vollstaendig (Rueckgabe 0)",
           rc2 == 3 and kopiert_in(w2) == [alt, "userprofil_2026"]
           and erg2.get("plugin") == "version"
           and rc3 == 0 and erg3.get("fertig") is True,
           (rc2, kopiert_in(w2), erg2.get("plugin"), rc3, erg3.get("plugin")))

    # I40c -Profil wie bisher (ein Profil, eine Zeile), auch neben -Profile
    # unbekannt.
    t, w, p, api = mehr_welt()
    rc, aus, erg = lauf(w, p, "-Profil", api[2025])
    pruefe("I40c -Profil <USERPROFIL_2025> wie bisher: nur dieses, EINE Zeile "
           "'Cadwork-Plugin:' im alten Wortlaut, 'mit -Profil angegeben', ein "
           "Eintrag in -ErgebnisDatei, Rueckgabe 0",
           rc == 0 and kopiert_in(w) == ["USERPROFIL_2025"]
           and ergebnis(aus).count("Cadwork-Plugin:") == 1
           and "Cadwork-Plugin: kopiert nach %s, Cadwork-Version passt (Cadwork"
           " 2025 im Profil USERPROFIL_2025)" % api[2025] in aus
           and "Warum:   mit -Profil angegeben" in aus
           and erg.get("profil") == api[2025]
           and len(erg.get("profile") or []) == 1, (rc, erg, aus[-600:]))

    # I40d die Liste: leer, doppelt (Gross/Klein), Anfuehrungszeichen; ein
    # Pfad, den es nicht gibt, zaehlt als nicht installiert.
    r = ps_funktionen("@{ l = (Profile-Liste ' C:\\a ; ;\"C:\\b\";c:\\A;') "
                      "} | ConvertTo-Json -Compress")
    t, w, p, api = mehr_welt()
    weg = os.path.join(w, "userprofil_2099", "3d", "API.x64")
    rc, aus, erg = lauf(w, p, "-Profile", api[2026] + ";;" + weg + ";" +
                        api[2026].upper())
    pruefe("I40d Profile-Liste: leere und doppelte (Gross/Klein) fallen weg, "
           "Anfuehrungszeichen auch; ein Profil, das es nicht gibt: dieses "
           "'NICHT kopiert' mit Grund, das andere kopiert, Rueckgabe 3",
           r.get("l") == ["C:\\a", "C:\\b"] and rc == 3
           and kopiert_in(w) == ["userprofil_2026"]
           and "Cadwork-Plugin: NICHT kopiert nach %s - Profilordner gibt es "
           "nicht" % weg in aus and len(erg.get("profile") or []) == 2,
           (r, rc, erg, aus[-600:]))

    # I40e das alte Plugin in ZWEI Profilen: je Profil ein Unterordner der
    # Sicherung (sonst laege der zweite "LignoAI Connect" im Weg).
    def alte_zwei(ps1=None):
        t, w, p, api = mehr_welt(mit_2024=False)
        for j in (2026, 2025):
            d = os.path.join(api[j], "LignoAI Connect")
            os.makedirs(d)
            with open(os.path.join(d, "LignoAI Connect.py"), "w") as fh:
                fh.write(ALT_KERN)
        rc, aus, erg = lauf(w, p, "-Profile", api[2026] + ";" + api[2025],
                            "-AltesWegraeumen", ps1=ps1)
        sich = os.path.join(w, "OpenMcpCad_Backups")
        weg = []
        for wurzel, ordner, _d in os.walk(sich):
            weg += [os.path.relpath(os.path.join(wurzel, o), sich)
                    for o in ordner if o == "LignoAI Connect"]
        bleibt = [j for j in (2026, 2025) if os.path.isdir(
            os.path.join(api[j], "LignoAI Connect"))]
        return rc, aus, erg, sorted(x.split(os.sep, 1)[-1] for x in weg), bleibt
    rc, aus, erg, weg, bleibt = alte_zwei()
    mut = mutante_ps("            if ($mehrere) { $altZiel = Join-Path "
                     "$altBasis (Split-Path -Leaf (Split-Path -Parent "
                     "(Split-Path -Parent $api))) }\n", "")
    rck, _ak, ergk, wegk, bleibtk = alte_zwei(mut)
    pruefe("I40e altes Plugin in 2026 und 2025, -Profile + -AltesWegraeumen: "
           "beide beiseitegelegt, je Profil ein Unterordner, Rueckgabe 0; "
           "KONTROLLE: ohne Unterordner bleibt das zweite liegen (Fehler, "
           "Rueckgabe 3)",
           rc == 0 and bleibt == [] and erg.get("altWeg") == 2
           and weg == [os.path.join("USERPROFIL_2025", "LignoAI Connect"),
                       os.path.join("userprofil_2026", "LignoAI Connect")]
           and rck == 3 and ergk.get("altFehler") is True and len(bleibtk) == 1,
           (rc, erg.get("alt"), weg, bleibt, rck, wegk, bleibtk))

    # I40f Textfenster: "a" nimmt alle mit * (die Vorauswahl), Enter wie
    # bisher die eine Vorgabe.
    def text_lauf(eingabe):
        t, w, p, api = mehr_welt()
        ps1 = paket_attrappe()
        r = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps1, "-OhneServer", "-CadworkWurzel", w,
                            "-CadworkProgramm", p], input=eingabe,
                           capture_output=True, timeout=180,
                           creationflags=OHNE_FENSTER)
        return r.returncode, (r.stdout + r.stderr).decode(
            "utf-8", errors="replace"), kopiert_in(w), api
    rc_a, a_a, k_a, api = text_lauf(b"a\r\n\r\n")
    rc_e, a_e, k_e, _api = text_lauf(b"\r\n\r\n")
    r = ps_funktionen("@{ a = (Profil-Antwort-Mehr 'A' 4 1 @(1, 2)); "
                      "z = (Profil-Antwort-Mehr '3' 4 1 @(1, 2)); "
                      "e = (Profil-Antwort-Mehr '' 4 1 @(1, 2)); "
                      "x = (Profil-Antwort-Mehr 'x' 4 1 @(1, 2)); "
                      "o = (Profil-Antwort-Mehr 'a' 4 1 @()) } | "
                      "ConvertTo-Json -Compress")
    pruefe("I40f Textfenster: die Liste markiert 2026 und 2025 mit *, 'a' "
           "kopiert in beide (Rueckgabe 0), Enter wie bisher nur in die "
           "Vorgabe 2026; 'a' ohne Vorauswahl fragt nochmal",
           "[2] %s   (Cadwork 2026 installiert) *   <- Vorgabe" % api[2026]
           in a_a and "[3] %s   (Cadwork 2025 installiert) *" % api[2025] in a_a
           # (die Frage selbst schreibt Read-Host bei umgeleiteter Eingabe
           # nicht, gemessen - geprueft wird die Wirkung)
           and "Warum:   alle mit * gewaehlt" in a_a
           and rc_a == 0 and k_a == ["USERPROFIL_2025", "userprofil_2026"]
           and rc_e == 0 and k_e == ["userprofil_2026"]
           and r == {"a": [1, 2], "z": [2], "e": [1], "x": [], "o": []},
           (rc_a, k_a, rc_e, k_e, r, a_a[:900]))
    # KONTROLLE: ohne "a" (Profil-Antwort wie vor 2026-10-10) faellt "a"
    # durch und es wird nochmal gefragt - der Lauf endet ohne Kopie.
    mut = mutante_ps("    if (\"$antwort\".Trim() -match '^(a|alle)$' -and "
                     "@($alle).Count -gt 0) { return , @($alle) }\n", "")
    t, w, p, api = mehr_welt()
    r = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", paket_attrappe(ps1=mut), "-OhneServer",
                        "-CadworkWurzel", w, "-CadworkProgramm", p],
                       input=b"a\r\n", capture_output=True, timeout=180,
                       creationflags=OHNE_FENSTER)
    pruefe("I40f-K KONTROLLE: ohne 'a' kopiert dieselbe Eingabe nicht in "
           "beide", kopiert_in(w) != ["USERPROFIL_2025", "userprofil_2026"],
           (r.returncode, kopiert_in(w)))


def mutante_ps(alt, neu):
    quelle = open(INSTALL, encoding="ascii").read()
    assert quelle.count(alt) == 1, alt
    t = tempfile.mkdtemp(prefix="omcad_mut_")
    _temp.append(t)
    ziel = os.path.join(t, "install.ps1")
    with open(ziel, "w", encoding="ascii") as fh:
        fh.write(quelle.replace(alt, neu))
    return ziel


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print("Installer — Gate\n")
    # Seit 2026-10-10 zeigt der Doppelklick ohne Programmdateien und bei
    # einem gesperrten Skript ein Fenster: im Gate beantwortet (nie gezeigt),
    # und die ZIP wird nie in den echten Downloads gesucht.
    leer = tempfile.mkdtemp(prefix="omcad_zip_orte_")
    _temp.append(leer)
    os.environ["OMCAD_HILFE_ANTWORT"] = "abbrechen"
    os.environ["OMCAD_ZIP_ORTE"] = leer
    if not PS:
        pruefe("I0 Windows PowerShell 5.1 gefunden", False, "powershell.exe")
        return 1
    if "--nur-fenster" in sys.argv:
        # Nur das Einrichtungsfenster (I21-I27), fuer die Arbeit daran.
        sys.path.insert(0, REPO)
        pruefe_fenster()
        pruefe_gepackt()
        for t in _temp:
            shutil.rmtree(t, ignore_errors=True)
        n, ok = len(_ergebnisse), sum(_ergebnisse)
        print("\n%d/%d bestanden (nur I21-I32)" % (ok, n))
        return 0 if ok == n else 1
    ver = ps_funktionen("@{ v = $PSVersionTable.PSVersion.Major } | "
                        "ConvertTo-Json -Compress")
    pruefe("I0 gemessen mit Windows PowerShell 5 (wie install.cmd)",
           ver.get("v") == 5, ver)

    # --- I1 der gemeldete Fall --------------------------------------------
    t, w, p = attrappe(["userprofil_30", "USERPROFIL_2025"], ["2025"])
    r = wahl(w, p)
    pruefe("I1 userprofil_30 + USERPROFIL_2025 + EXE_2025: Liste numerisch, "
           "Vorgabe USERPROFIL_2025",
           r.get("namen") == ["USERPROFIL_2025", "userprofil_30"]
           and r.get("vorgabe") == "USERPROFIL_2025"
           and "EXE_2025" in r.get("grund", ""), r)
    # I1-K KONTROLLE: die alte Textsortierung (0.1.0, wortgleich) MUSS auf
    # derselben Attrappe userprofil_30 waehlen - sonst bildet die Attrappe
    # den Fall nicht nach.
    alt = ps_funktionen(
        "$a = @(Get-ChildItem '%s' -Directory -Filter \"userprofil_*\" "
        "-ErrorAction SilentlyContinue | Sort-Object Name -Descending | "
        "ForEach-Object { Join-Path $_.FullName \"3d\\API.x64\" } | "
        "Where-Object { Test-Path $_ })\n"
        "@{ erstes = $a[0] } | ConvertTo-Json -Compress" % w)
    pruefe("I1-K die alte Textsortierung waehlt auf derselben Attrappe "
           "userprofil_30", str(alt.get("erstes", "")).endswith(
               "userprofil_30\\3d\\API.x64"), alt)

    t, w, p = attrappe(["userprofil_2025", "userprofil_2026"],
                       ["2025", "2026"])
    r = wahl(w, p)
    pruefe("I2 2025 + 2026 installiert -> 2026",
           r.get("vorgabe") == "userprofil_2026", r)
    # I3: das Profil fuer Cadwork 2026 geht vor - auch ohne EXE_2026 und
    # auch, wenn daneben ein NEUERES Cadwork installiert ist
    # (Gegenpruefung 2026-09-26: vorher 2025 bzw. 2027 vorgeschlagen, und
    # der Installer brach danach ab).
    t, w, p = attrappe(["userprofil_2026", "userprofil_2025"], ["2025"])
    fall_a = (w, p)
    r = wahl(w, p)
    pruefe("I3 Profil 2026 ohne EXE_2026, 2025 installiert -> Vorgabe 2026",
           r.get("namen") == ["userprofil_2026", "userprofil_2025"]
           and r.get("vorgabe") == "userprofil_2026"
           and "EXE_2026 nicht gefunden" in r.get("grund", ""), r)
    t, w, p = attrappe(["userprofil_2026", "userprofil_2027"],
                       ["2026", "2027"])
    fall_b = (w, p)
    r = wahl(w, p)
    pruefe("I3 2026 und 2027 installiert -> Vorgabe 2026 (nicht 2027)",
           r.get("namen") == ["userprofil_2027", "userprofil_2026"]
           and r.get("vorgabe") == "userprofil_2026"
           and "installiert unter" in r.get("grund", ""), r)
    # I3-K KONTROLLE: dieselbe Datei OHNE den Vorrang-Block (Stand 60be238)
    # MUSS auf denselben Attrappen 2025 bzw. 2027 vorschlagen.
    mut = mutante_ohne_jahr_vorrang()
    ka, kb = wahl(*fall_a, ps1=mut), wahl(*fall_b, ps1=mut)
    pruefe("I3-K ohne Vorrang fuer 2026 kaemen 2025 und 2027 heraus",
           ka.get("vorgabe") == "userprofil_2025"
           and kb.get("vorgabe") == "userprofil_2027", (ka, kb))
    t, w, p = attrappe(["userprofil_30", "userprofil_2025"], [])
    r = wahl(w, p)
    pruefe("I4 kein EXE_<Jahr> -> hoechste Jahreszahl als Zahl (2025)",
           r.get("vorgabe") == "userprofil_2025"
           and "kein passendes EXE" in r.get("grund", ""), r)
    t, w, p = attrappe(["userprofil_2026"], ["2026"],
                       ohne_api=["userprofil_2027", "userprofil_x"])
    r = wahl(w, p)
    pruefe("I5 Profile ohne 3d\\API.x64 zaehlen nicht",
           r.get("namen") in (["userprofil_2026"], "userprofil_2026"), r)

    # --- I6 Antwort auf die Profilfrage -----------------------------------
    r = ps_funktionen(
        "@{ leer = (Profil-Antwort '' 3 1); zwei = (Profil-Antwort '2' 3 1); "
        "blank = (Profil-Antwort ' 1 ' 3 1); neun = (Profil-Antwort '9' 3 1); "
        "null = (Profil-Antwort '0' 3 1); x = (Profil-Antwort 'x' 3 1) } | "
        "ConvertTo-Json -Compress")
    pruefe("I6 Enter = Vorgabe, 1..n = Zeile, sonst nochmal fragen (-1)",
           r == {"leer": 1, "zwei": 1, "blank": 0, "neun": -1, "null": -1,
                 "x": -1}, r)

    # --- I7 Cadwork-Version ------------------------------------------------
    t, w, p = attrappe([], [str(ALT_JAHR), "2025", "2026"])
    _, _, p_ohne = attrappe([], ["2025"])

    def version(api, prog):
        return ps_funktionen(
            "$v = Version-Pruefen '%s' @(Cadwork-Installiert '%s') '%s'\n"
            "@{ passt = $v.Passt; text = $v.Text } | ConvertTo-Json -Compress"
            % (api, prog, prog))
    v25 = version(os.path.join(w, "USERPROFIL_2025", "3d", "API.x64"), p)
    valt = version(os.path.join(w, "USERPROFIL_%d" % ALT_JAHR, "3d",
                                "API.x64"), p)
    v26 = version(os.path.join(w, "userprofil_2026", "3d", "API.x64"), p)
    v26o = version(os.path.join(w, "userprofil_2026", "3d", "API.x64"),
                   p_ohne)
    vx = version(os.path.join(w, "irgendwo", "3d", "API.x64"), p)
    pruefe("I7 Profil %d (vor $CADWORK_ERLAUBT_AB) passt NICHT, Meldung "
           "fuer Laien nennt das erste erlaubte Jahr aus der Quelle"
           % ALT_JAHR,
           valt.get("passt") is False and valt.get("text") ==
           "Dieses Paket braucht Cadwork 3D %d oder neuer. Gefunden: Cadwork "
           "%d im Profil USERPROFIL_%d." % (ERLAUBT_AB, ALT_JAHR, ALT_JAHR),
           valt)
    pruefe("I7 Profil USERPROFIL_2025 (gross geschrieben) passt seit "
           "2026-10-10 und ist seitdem getestet (0.2.2 im echten Cadwork "
           "2025): kein 'nicht getestet', kein Hinweis auf ein fehlendes EXE",
           v25.get("passt") is True and v25.get("text") ==
           "Cadwork 2025 im Profil USERPROFIL_2025", v25)
    pruefe("I7 Profil 2026 mit EXE_2026 passt (Kontrolle zu %d)" % ALT_JAHR,
           v26.get("passt") is True and "Hinweis" not in v26.get("text", ""),
           v26)
    pruefe("I7 Profil 2026 ohne EXE_2026: passt, mit Hinweis",
           v26o.get("passt") is True
           and "EXE_2026 nicht gefunden" in v26o.get("text", ""), v26o)
    pruefe("I7 Profil ohne Jahreszahl: passt nicht, 'unbekannt'",
           vx.get("passt") is False and "unbekannt" in vx.get("text", ""), vx)

    # --- I8 Schlussmeldung --------------------------------------------------
    def zusammen(server, stext, plugin, ptext):
        return ps_funktionen(
            "$z = Zusammenfassung @{ Server = %s; ServerText = '%s'; "
            "Plugin = '%s'; PluginText = '%s'; Profil = 'C:\\P\\API.x64' }\n"
            "@{ fertig = $z.Fertig; text = ($z.Zeilen -join \"`n\") } | "
            "ConvertTo-Json -Compress"
            % ("'%s'" % server if server else "$null", stext, plugin, ptext))

    def gelogen(text):
        """Behauptet die Meldung Vollstaendigkeit?"""
        t = text.lower()
        return ("erfolgreich" in t or "beide teile sind installiert" in t
                or ("vollstaendig" in t and "nicht vollstaendig" not in t))

    a = zusammen("ok", "py -m open_mcp_cad.server", "fehlt", "kein Profil")
    pruefe("I8 Server ok, Plugin fehlt -> beide Teile einzeln, NICHT "
           "vollstaendig, nirgends 'erfolgreich'",
           a.get("fertig") is False
           and "MCP-Server:     installiert und getestet" in a.get("text", "")
           and "Cadwork-Plugin: NICHT kopiert - kein Profil" in a.get("text", "")
           and "NICHT vollstaendig" in a.get("text", "")
           and not gelogen(a.get("text", "")), a)
    c = zusammen("ok", "py", "version", "Gefunden: Cadwork %d" % ALT_JAHR)
    pruefe("I8 Plugin in falsches Profil (bestaetigt) -> 'passt NICHT', "
           "NICHT vollstaendig",
           c.get("fertig") is False and "passt NICHT" in c.get("text", "")
           and not gelogen(c.get("text", "")), c)
    d = zusammen(None, "abgebrochen, bevor der Server an der Reihe war",
                 "ok", "Cadwork 2026")
    pruefe("I8 Server fehlt, Plugin ok -> NICHT vollstaendig",
           d.get("fertig") is False
           and "MCP-Server:     NICHT eingerichtet" in d.get("text", "")
           and not gelogen(d.get("text", "")), d)
    # I8-K KONTROLLE: sind beide Teile da, MUSS die Meldung es sagen (sonst
    # misst `gelogen` nichts) - mit dem offenen Klick und der Logdatei.
    b = zusammen("ok", "py", "ok", "Cadwork 2026")
    pruefe("I8-K beide Teile da -> 'Beide Teile sind installiert', Klick "
           "und Logdatei genannt",
           b.get("fertig") is True and gelogen(b.get("text", ""))
           and "Noch offen" in b.get("text", "")
           and START_LOG in b.get("text", ""), b)

    # --- I9 der ganze Installer gegen Attrappen ------------------------------
    t, w, p = attrappe(["userprofil_30", "USERPROFIL_2025"], ["2025"])
    rc, aus = installer(w, p)
    pruefe("I9 der gemeldete Fall (30 + USERPROFIL_2025, Cadwork 2025): seit "
           "2026-10-10 kopiert nach USERPROFIL_2025 (nicht 30), passt (2025 "
           "getestet, kein Hinweis), Rueckgabe 0, NICHT 'NICHT vollstaendig'",
           rc == 0 and kopiert_in(w) == ["USERPROFIL_2025"]
           and "Cadwork: Cadwork 2025 im Profil USERPROFIL_2025 - passt." in aus
           and "nicht getestet" not in aus
           and "Cadwork-Plugin: kopiert nach " + os.path.join(
               w, "USERPROFIL_2025", "3d", "API.x64") in aus
           and "passt NICHT" not in aus and "Trotzdem" not in aus
           and "NICHT vollstaendig" not in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    pruefe("I9 zeigt beide Profile mit Pfad, das gewaehlte und den Grund",
           "[1] " + os.path.join(w, "USERPROFIL_2025", "3d", "API.x64") in aus
           and "[2] " + os.path.join(w, "userprofil_30", "3d", "API.x64") in aus
           and "Profil:  " + os.path.join(w, "USERPROFIL_2025") in aus
           and "Warum:   neuestes Profil mit installiertem Cadwork" in aus,
           aus[:900])
    # I9-K KONTROLLE: derselbe Fall mit dem Stand vor 2026-10-10 ([2026] ab
    # 2026, Mutante der Quelle) bricht ab und kopiert nichts - die Attrappe
    # bildet den gemeldeten Fall also nach, und erlaubt wird er nur durch
    # $CADWORK_ERLAUBT_AB.
    t, w, p = attrappe(["userprofil_30", "USERPROFIL_2025"], ["2025"])
    ps1 = paket_attrappe(ps1=_jahre_mutante([2026], 2026))
    rc, aus = _lauf(["-File", ps1, "-OhnePause", "-OhneServer",
                     "-CadworkWurzel", w, "-CadworkProgramm", p])
    pruefe("I9-K KONTROLLE: mit [2026] ab 2026 bricht derselbe Fall ab, "
           "kopiert nichts, 'Gefunden: Cadwork 2025 im Profil "
           "USERPROFIL_2025.', NICHT vollstaendig",
           rc == 3 and kopiert_in(w) == []
           and "Gefunden: Cadwork 2025 im Profil USERPROFIL_2025." in aus
           and "NICHT vollstaendig" in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    # I9b eine NICHT erlaubte Version (ALT_JAHR, aus der Quelle): bricht ab,
    # kopiert nichts, sagt warum - auch neben userprofil_30.
    alt = "USERPROFIL_%d" % ALT_JAHR
    t, w, p = attrappe(["userprofil_30", alt], [str(ALT_JAHR)])
    rc, aus = installer(w, p)
    pruefe("I9b userprofil_30 + %s (Cadwork %d): bricht ab, kopiert NICHTS, "
           "sagt warum (erstes erlaubtes Jahr, wahrscheinlich kein Start)"
           % (alt, ALT_JAHR),
           rc == 3 and kopiert_in(w) == []
           and "Dieses Paket braucht Cadwork 3D %d oder neuer. Gefunden: "
           "Cadwork %d im Profil %s." % (ERLAUBT_AB, ALT_JAHR, alt) in aus
           and "startet mit dieser Version wahrscheinlich nicht" in aus
           and "Python 3.14 und PyQt6" not in aus
           and "Cadwork-Plugin: NICHT kopiert" in aus
           and "NICHT vollstaendig" in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    # I9b-K KONTROLLE: mit ausdruecklicher Bestaetigung MUSS kopiert werden -
    # sonst saehe ein Installer, der nie kopiert, oben gleich aus.
    t, w, p = attrappe(["userprofil_30", alt], [str(ALT_JAHR)])
    rc, aus = installer(w, p, "-TrotzdemKopieren")
    pruefe("I9b-K -TrotzdemKopieren: kopiert nach %s (nicht 30), meldet "
           "'passt NICHT', nicht vollstaendig" % alt,
           rc == 3 and kopiert_in(w) == [alt]
           and "passt NICHT" in aus and "NICHT vollstaendig" in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    t, w, p = attrappe(["userprofil_2025", "userprofil_2026"],
                       ["2025", "2026"])
    rc, aus = installer(w, p)
    pruefe("I9 Cadwork 2026 installiert: kopiert nur nach 2026, "
           "Version passt, Klick + Logdatei genannt",
           rc == 0 and kopiert_in(w) == ["userprofil_2026"]
           and "Cadwork-Version passt" in aus and "Noch offen" in aus
           and START_LOG in aus and "NICHT vollstaendig" not in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    t, w, p = attrappe(["userprofil_%d" % ALT_JAHR], [str(ALT_JAHR)])
    rc, aus = installer(w, p, "-Profil",
                        os.path.join(w, "userprofil_%d" % ALT_JAHR, "3d",
                                     "API.x64"))
    pruefe("I9 -Profil auf ein %d-Profil: auch dann kein Kopieren" % ALT_JAHR,
           rc == 3 and kopiert_in(w) == []
           and "Warum:   mit -Profil angegeben" in aus
           and "Gefunden: Cadwork %d" % ALT_JAHR in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))

    # --- I11 der Doppelklick oben im Paket (Rueckmeldung 2026-09-29) -------
    # Oben liegt nur 1_INSTALLIEREN.cmd; er startet Programmdateien\
    # install.ps1, und DAS kopiert aus seinem eigenen Ordner. Gemessen ueber
    # cmd.exe wie ein Doppelklick, gegen Attrappen.
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc, aus = doppelklick(w, p)
    pruefe("I11 der Doppelklick oben startet den Installer im Unterordner, "
           "der kopiert das Plugin aus Programmdateien",
           rc == 0 and kopiert_in(w) == ["userprofil_2026"]
           and "Cadwork-Version passt" in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-600:]))
    # I11b die Anleitung oben (Name aus paket_bauen) liegt danach neben dem
    # Plugin, unter dem Namen, den das Dashboard sucht (aus dem Quelltext).
    pruefe("I11b die Anleitung liegt neben dem Plugin, wo der Chat sie sucht",
           anleitung_im_plugin(w, "userprofil_2026") == PDF_ATTRAPPE,
           anleitung_im_plugin(w, "userprofil_2026"))
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc, aus = doppelklick(w, p, pdf=False)
    pruefe("I11b-K KONTROLLE: ohne PDF im Paket keine Anleitung neben dem "
           "Plugin, der Installer laeuft trotzdem durch",
           rc == 0 and anleitung_im_plugin(w, "userprofil_2026") is None,
           (rc, aus[-300:]))
    # I11-K KONTROLLE: der alte Doppelklick (install.ps1 daneben) findet im
    # neuen Aufbau nichts - und kopiert nichts.
    alt_cmd = os.path.join(tempfile.mkdtemp(prefix="omcad_altcmd_"), "a.cmd")
    _temp.append(os.path.dirname(alt_cmd))
    with open(alt_cmd, "w", encoding="ascii") as fh:
        fh.write('@echo off\npowershell -NoProfile -ExecutionPolicy Bypass '
                 '-File "%~dp0install.ps1" %*\nexit /b %ERRORLEVEL%\n')
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc, aus = doppelklick(w, p, cmd_quelle=alt_cmd)
    pruefe("I11-K der alte Doppelklick findet install.ps1 nicht, kopiert "
           "nichts", rc != 0 and kopiert_in(w) == [], (rc, aus[-300:]))

    # I11c Gegenpruefung 2026-09-29: das Paket unter einem Pfad mit
    # Leerzeichen, Umlaut, & und Klammern, gestartet mit einem ANDEREN
    # Arbeitsordner (System32, wie "Als Administrator ausfuehren")
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32")
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc, aus = doppelklick(w, p, name="Open MCP CAD (1) & Jürg Müller",
                          cwd=system32)
    pruefe("I11c Paket unter 'Open MCP CAD (1) & Jürg Müller', Arbeitsordner "
           "System32: der Installer findet Programmdateien und kopiert",
           rc == 0 and kopiert_in(w) == ["userprofil_2026"]
           and anleitung_im_plugin(w, "userprofil_2026") == PDF_ATTRAPPE,
           (rc, kopiert_in(w), aus[-400:]))
    # I11d Doppelklick IN der ZIP-Datei (nur 1_INSTALLIEREN.cmd liegt da):
    # seit 2026-10-10 ein freundliches Fenster statt "beliebige Taste" (hier
    # ohne ZIP in den Suchorten: die Anleitung; mehr in I33)
    spur_h = os.path.join(tempfile.mkdtemp(prefix="omcad_hspur_"), "h.jsonl")
    _temp.append(os.path.dirname(spur_h))
    os.environ["OMCAD_HILFE_SPUR"] = spur_h
    try:
        t, w, p = attrappe(["userprofil_2026"], ["2026"])
        rc, aus = doppelklick(w, p, ohne_unterordner=True, ohne_pause=False)
        h_d = open(spur_h, encoding="utf-8").read() \
            if os.path.exists(spur_h) else ""
        if os.path.exists(spur_h):
            os.remove(spur_h)
    finally:
        os.environ.pop("OMCAD_HILFE_SPUR", None)
    pruefe("I11d ohne Programmdateien (Doppelklick in der ZIP): Rueckgabe 2, "
           "das Fenster 'Bitte zuerst entpacken' statt Text und 'beliebige "
           "Taste'",
           rc == 2 and '"art":"anleitung"' in h_d and kopiert_in(w) == []
           and "Taste" not in aus, (rc, h_d[:200], aus[-400:]))
    # I11e PowerShell fuehrt das Skript gar nicht aus (hier: es laesst sich
    # nicht parsen, wie bei einer Sperre kommt 1 zurueck): Meldung + Pause;
    # KONTROLLE: ein Installer, der selbst "nicht vollstaendig" meldet (3),
    # bekommt KEINE zweite Meldung
    kaputt = os.path.join(tempfile.mkdtemp(prefix="omcad_kaputt_"),
                          "install.ps1")
    _temp.append(os.path.dirname(kaputt))
    with open(kaputt, "w", encoding="ascii") as fh:
        fh.write("param(" + chr(10) + "  [string]$x = (" + chr(10))
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    os.environ["OMCAD_HILFE_SPUR"] = spur_h
    try:
        rc, aus = doppelklick(w, p, ps1=kaputt, ohne_pause=False)
        h_e = open(spur_h, encoding="utf-8").read() \
            if os.path.exists(spur_h) else ""
        os.environ["OMCAD_HILFE_ANTWORT"] = "kaputt"
        rc_f, aus_f = doppelklick(w, p, ps1=kaputt, ohne_pause=False)
    finally:
        os.environ.pop("OMCAD_HILFE_SPUR", None)
        os.environ["OMCAD_HILFE_ANTWORT"] = "abbrechen"
    t, w2, p2 = attrappe(["userprofil_%d" % ALT_JAHR], [str(ALT_JAHR)])
    rc2, aus2 = doppelklick(w2, p2, ohne_pause=False)
    pruefe("I11e PowerShell startet das Skript nicht: seit 2026-10-10 ein "
           "Fenster 'Die Einrichtung konnte nicht starten' mit der Rueckgabe, "
           "kein 'beliebige Taste'; geht auch das Fenster nicht, der Text und "
           "die Pause wie frueher",
           rc not in (0, 3) and '"art":"start"' in h_e and str(rc) in h_e
           and "Taste" not in aus and rc_f == rc
           and "Der Installer konnte nicht starten" in aus_f
           and ("Taste" in aus_f or "key" in aus_f),
           (rc, h_e[:300], aus[-300:], aus_f[-300:]))
    pruefe("I11e-K KONTROLLE: 'nicht vollstaendig' (3) vom Installer selbst "
           "- keine zweite Meldung", rc2 == 3
           and "Der Installer konnte nicht starten" not in aus2
           and "NICHT vollstaendig" in aus2, (rc2, aus2[-300:]))
    # I11d/e-K KONTROLLE: der Doppelklick im Stand a092618 (aus git) sagt in
    # beiden Faellen nichts und wartet nicht - das Fenster waere sofort zu.
    alt_roh = subprocess.run(["git", "show", "a092618:verteilung/" +
                              P.INSTALLIEREN], cwd=REPO, capture_output=True,
                             check=True).stdout
    alt_cmd = os.path.join(tempfile.mkdtemp(prefix="omcad_altcmd_"),
                           P.INSTALLIEREN)
    _temp.append(os.path.dirname(alt_cmd))
    with open(alt_cmd, "wb") as fh:
        fh.write(alt_roh)
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc_z, aus_z = doppelklick(w, p, cmd_quelle=alt_cmd, ohne_unterordner=True,
                              ohne_pause=False)
    rc_p, aus_p = doppelklick(w, p, cmd_quelle=alt_cmd, ps1=kaputt,
                              ohne_pause=False)
    pruefe("I11d/e-K KONTROLLE: der alte Doppelklick sagt weder 'entpacken' "
           "noch 'konnte nicht starten' und wartet nicht",
           "Alle extrahieren" not in aus_z and "Taste" not in aus_z
           and "konnte nicht starten" not in aus_p and "Taste" not in aus_p
           and rc_z != 0 and rc_p != 0, (rc_z, aus_z[-200:], rc_p))

    # --- I10 Server mit API-Hilfe ----------------------------------------
    pruefe_server_teil()

    # --- I12-I18 KI-Programme eintragen -------------------------------------
    pruefe_ki_teil()
    pruefe_ki_kanten()

    # --- I20 Python ohne winget (python.org, Signatur) ---------------------
    pruefe_python_rueckfall()

    # --- I21-I27 das Einrichtungsfenster -------------------------------------
    pruefe_fenster()

    # --- I33 Doppelklick in der ZIP: freundlich entpacken -------------------
    pruefe_gepackt()

    for t in _temp:
        shutil.rmtree(t, ignore_errors=True)
    n, ok = len(_ergebnisse), sum(_ergebnisse)
    print("\n%d/%d bestanden" % (ok, n))
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
