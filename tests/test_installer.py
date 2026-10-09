#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate fuer den Installer (verteilung/install.ps1): Profilwahl, Cadwork-
Version, Schlussmeldung.

    python tests/test_installer.py        (-v zeigt jede Zeile)

Rueckmeldung Kollege zu 0.1.0 (2026-09-26):
  * die Profile wurden als TEXT absteigend sortiert - userprofil_30 kam vor
    userprofil_2025, das Plugin landete im falschen Profil;
  * Cadwork 2025 (Python 3.12, PyQt5) wurde nicht erkannt, das Plugin
    startet dort nicht;
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
claude.exe, Unterzeile, "Text kopieren").
"""

import json
import os
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
                 ohne_server=False, fenster=None, protokoll=None, aus=""):
    """Das Fenster (oder eine Mutante `fenster`) ohne es zu zeigen: bauen,
    verdrahten, Willkommen, pruefen wie beim Start; dann `schritte`
    (PowerShell, `K 'knopf'` klickt und merkt die Seite). `vorher`:
    Ersatz-Funktionen (etwa Finde-Python). -> (JSON, Text)."""
    assert wurzel.startswith(tempfile.gettempdir())
    assert programm.startswith(tempfile.gettempdir())
    if protokoll is None:
        t = tempfile.mkdtemp(prefix="omcad_fprot_")
        _temp.append(t)
        protokoll = os.path.join(t, "installer.log")
    skript = "\n".join([
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false",
        ". %s -NurFunktionen -CadworkWurzel %s -CadworkProgramm %s "
        "-Protokoll %s%s" % (_ps_text(fenster or FENSTER), _ps_text(wurzel),
                             _ps_text(programm), _ps_text(protokoll),
                             " -OhneServer" if ohne_server else ""),
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
    # XAML (aus der Quelle gelesen); jedes Teil, das es sucht, auch.
    quelle = open(FENSTER, encoding="ascii").read()
    xaml = open(FENSTER_XAML, encoding="utf-8").read()
    texte = set(re.findall(r'"(t_[a-z_]+)"', quelle))
    texte |= {"t_name_" + i for i in re.findall(
        r'\$KI_PROGRAMME = @\(([^)]*)\)', quelle)[0].replace('"', "").replace(
            " ", "").split(",")}
    fehlt = sorted(x for x in texte if not x.endswith("_")
                   and 'x:Key="%s"' % x not in xaml)
    teile = set(re.findall(r'El \$(?:F\.)?U "([a-z_0-9]+)"', quelle))
    teile |= {"Seite_" + s for s in re.findall(
        r'\$SEITEN = @\(([^)]*)\)', quelle)[0].replace('"', "").replace(
            " ", "").split(",")}
    teile_fehlt = sorted(x for x in teile if 'x:Name="%s"' % x not in xaml)
    pruefe("I22 jeder Text (%d) und jedes Teil (%d), das install_fenster.ps1 "
           "nennt, steht in der XAML; das Skript ist reines ASCII"
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
           "angehakt, Claude Code ohne Karte; Argumente: -Profil 2026, "
           "-KiNur claude_desktop,codex, -OhnePause, kein -TrotzdemKopieren "
           "und kein -PythonInstallieren; 'Los geht's' erst nach dem Pruefen",
           r.get("v") == ["willkommen", "wo", "ki", "bereit"]
           and r.get("haken") == {"claude_desktop": [True, True],
                                  "codex": [True, True],
                                  "claude_code": [False, False]}
           and r.get("code_karte") is False and r.get("vor") is False
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
    t, w, p = attrappe(["userprofil_2026", "userprofil_2025"],
                       ["2026", "2025"])
    pfad25 = os.path.join(w, "userprofil_2025", "3d", "API.x64")
    r, aus = fenster_lauf(
        w, p, "KW; K 'ki_weiter'; "
        "(El $U 'profil_wahl_1').IsChecked = $true; K 'profil_weiter'; "
        "K 'version_trotzdem'", vorher=py_da, env=env)
    a = r.get("args") or []
    pruefe("I23b zwei Profile: Seite 'Welches Cadwork?', 2025 gewaehlt -> "
           "Warnung, 'Trotzdem installieren' -> Bereit; Argumente -Profil 2025 "
           "und -TrotzdemKopieren",
           r.get("v") == ["willkommen", "wo", "ki", "profil", "version", "bereit"]
           and _wert(a, "-Profil") == pfad25 and "-TrotzdemKopieren" in a,
           (r, aus[-500:]))
    t, w, p = attrappe(["userprofil_2025"], ["2025"])
    r, aus = fenster_lauf(w, p, zu + "\nKW; K 'ki_weiter';"
                          " Klick $U 'version_schliessen'", vorher=py_da,
                          env=env, aus="$global:zu")
    pruefe("I23c nur Cadwork 2025: die Warnung kommt, 'Schliessen' schliesst, "
           "nichts gestartet, Rueckgabe 3",
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
        "New-Item -ItemType Directory -Path %s | Out-Null; K 'keine_nochmal';"
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
        for n in (P.FENSTER_XAML,):
            shutil.copy(os.path.join(P.VERTEILUNG, n), os.path.join(d, n))
        shutil.copy(INSTALL, os.path.join(d, "install.ps1"))
        ziel = os.path.join(d, P.FENSTER)
        with open(ziel, "w", encoding="ascii") as fh:
            fh.write(q.replace(alt, neu))
        return ziel
    t, w, p = attrappe(["userprofil_2025"], ["2025"])
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
    pruefe("I23-K KONTROLLEN: ohne Versionswarnung kaeme Cadwork 2025 ohne "
           "Frage auf 'Bereit' (I23c), ohne die Wahl ginge Codex trotz "
           "Abwahl mit (I23a2), ohne Python-Seite fehlte -PythonInstallieren "
           "(I23d)",
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
    os.makedirs(os.path.join(w2, "userprofil_2025", "3d", "API.x64"))
    os.makedirs(os.path.join(p2, "EXE_2025"))
    r2, aus2 = fenster_lauf(w2, p2, "KW; K 'ki_weiter'; "
                            "K 'version_trotzdem'; K 'bereit_installieren'; "
                            + warten + "; $global:v += $S.Seite; "
                            "K 'fehler_kopieren'", vorher=py_da, env=env,
                            ohne_server=True, fenster=fenster,
                            aus="$global:ok")
    pruefe("I24b Cadwork 2025 'trotzdem': kopiert, aber Fehlerseite mit dem "
           "Satz zur Version, Rueckgabe 3 (wie das Textfenster)",
           r2.get("v", [])[-1:] == ["fehler"] and r2.get("rc") == 3
           and r2.get("fehler") == "t_fehler_version"
           and kopiert_in(w2) == ["userprofil_2025"]
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

    # --- I25 -ErgebnisDatei: der Stand fuer das Fenster ------------------
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    datei = os.path.join(t, "ergebnis.json")
    rc, aus = installer(w, p, "-ErgebnisDatei", datei)
    erg = json.load(open(datei, encoding="utf-8")) \
        if os.path.isfile(datei) else {}
    t, w, p = attrappe(["userprofil_2025"], ["2025"])
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
           and "Cadwork 2025" in (erg2.get("fehler") or ""), (erg, erg2))

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
    # dazu die Bilder der Seite "laeuft" mit Unterzeile (aus der Quelle)
    seiten_q += re.findall(r'(?m)^    (laeuft_\w+) += @\(', quelle)

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
    pruefe("I26 -Rendern: jede Seite (%d) als PNG in doppelter Aufloesung "
           "(1280x960), seiten.json mit den Teilen fuer die Marken der "
           "Anleitung" % len(seiten_q),
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
           and len(seiten_q) == 15,
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
                if re.search(r"[A-Za-z]:\\", y) and s != "fehler":
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
    if not PS:
        pruefe("I0 Windows PowerShell 5.1 gefunden", False, "powershell.exe")
        return 1
    if "--nur-fenster" in sys.argv:
        # Nur das Einrichtungsfenster (I21-I27), fuer die Arbeit daran.
        sys.path.insert(0, REPO)
        pruefe_fenster()
        for t in _temp:
            shutil.rmtree(t, ignore_errors=True)
        n, ok = len(_ergebnisse), sum(_ergebnisse)
        print("\n%d/%d bestanden (nur I21-I27)" % (ok, n))
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
    t, w, p = attrappe([], ["2025", "2026"])
    _, _, p_ohne = attrappe([], ["2025"])

    def version(api, prog):
        return ps_funktionen(
            "$v = Version-Pruefen '%s' @(Cadwork-Installiert '%s') '%s'\n"
            "@{ passt = $v.Passt; text = $v.Text } | ConvertTo-Json -Compress"
            % (api, prog, prog))
    v25 = version(os.path.join(w, "USERPROFIL_2025", "3d", "API.x64"), p)
    v26 = version(os.path.join(w, "userprofil_2026", "3d", "API.x64"), p)
    v26o = version(os.path.join(w, "userprofil_2026", "3d", "API.x64"),
                   p_ohne)
    vx = version(os.path.join(w, "irgendwo", "3d", "API.x64"), p)
    pruefe("I7 Profil 2025 passt NICHT, Meldung fuer Laien",
           v25.get("passt") is False and v25.get("text") ==
           "Dieses Paket braucht Cadwork 3D 2026. Gefunden: Cadwork 2025 "
           "im Profil USERPROFIL_2025.", v25)
    pruefe("I7 Profil 2026 mit EXE_2026 passt (Kontrolle zu 2025)",
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
    c = zusammen("ok", "py", "version", "Gefunden: Cadwork 2025")
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
    pruefe("I9 der gemeldete Fall (30 + 2025, Cadwork 2025): bricht ab, "
           "kopiert NICHTS, sagt warum",
           rc == 3 and kopiert_in(w) == []
           and "Gefunden: Cadwork 2025 im Profil USERPROFIL_2025." in aus
           and "Cadwork-Plugin: NICHT kopiert" in aus
           and "NICHT vollstaendig" in aus,
           "rc %s, kopiert %s\n%s" % (rc, kopiert_in(w), aus[-900:]))
    pruefe("I9 zeigt beide Profile mit Pfad, das gewaehlte und den Grund",
           "[1] " + os.path.join(w, "USERPROFIL_2025", "3d", "API.x64") in aus
           and "[2] " + os.path.join(w, "userprofil_30", "3d", "API.x64") in aus
           and "Profil:  " + os.path.join(w, "USERPROFIL_2025") in aus
           and "Warum:   neuestes Profil mit installiertem Cadwork" in aus,
           aus[:900])
    # I9-K KONTROLLE: mit ausdruecklicher Bestaetigung MUSS kopiert werden -
    # sonst saehe ein Installer, der nie kopiert, oben gleich aus.
    t, w, p = attrappe(["userprofil_30", "USERPROFIL_2025"], ["2025"])
    rc, aus = installer(w, p, "-TrotzdemKopieren")
    pruefe("I9-K -TrotzdemKopieren: kopiert nach USERPROFIL_2025 (nicht 30), "
           "meldet 'passt NICHT', nicht vollstaendig",
           rc == 3 and kopiert_in(w) == ["USERPROFIL_2025"]
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
    t, w, p = attrappe(["userprofil_2025"], ["2025"])
    rc, aus = installer(w, p, "-Profil",
                        os.path.join(w, "userprofil_2025", "3d", "API.x64"))
    pruefe("I9 -Profil auf ein 2025-Profil: auch dann kein Kopieren",
           rc == 3 and kopiert_in(w) == []
           and "Warum:   mit -Profil angegeben" in aus
           and "Gefunden: Cadwork 2025" in aus,
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
    # eine Meldung, die sagt, was zu tun ist; ohne -OhnePause wartet das
    # Fenster (stdin leer: pause kehrt sofort zurueck)
    t, w, p = attrappe(["userprofil_2026"], ["2026"])
    rc, aus = doppelklick(w, p, ohne_unterordner=True, ohne_pause=False)
    pruefe("I11d ohne Programmdateien (Doppelklick in der ZIP): Rueckgabe 2, "
           "Hinweis auf 'Alle extrahieren', das Fenster wartet",
           rc == 2 and "Alle extrahieren" in aus and "Programmdateien" in aus
           and kopiert_in(w) == [] and ("Taste" in aus or "key" in aus),
           (rc, aus[-400:]))
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
    rc, aus = doppelklick(w, p, ps1=kaputt, ohne_pause=False)
    t, w2, p2 = attrappe(["userprofil_2025"], ["2025"])
    rc2, aus2 = doppelklick(w2, p2, ohne_pause=False)
    pruefe("I11e PowerShell startet das Skript nicht: die Meldung sagt es, "
           "das Fenster wartet",
           rc not in (0, 3) and "Der Installer konnte nicht starten" in aus
           and ("Taste" in aus or "key" in aus), (rc, aus[-400:]))
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

    for t in _temp:
        shutil.rmtree(t, ignore_errors=True)
    n, ok = len(_ergebnisse), sum(_ergebnisse)
    print("\n%d/%d bestanden" % (ok, n))
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
