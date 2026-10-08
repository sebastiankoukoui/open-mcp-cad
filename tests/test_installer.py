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


def paket_attrappe(cmd_quelle=None, pdf=True, name=None, ps1=None):
    """Ein Paketordner wie dist/, im Aufbau aus paket_bauen (Regel 3):
    oben der Doppelklick, darunter UNTERORDNER mit install.ps1 und
    'Open MCP CAD/marke.txt'. `name`: der Paketordner heisst so (etwa
    mit Leerzeichen, Umlaut, & und Klammern). -> Pfad auf install.ps1."""
    t = tempfile.mkdtemp(prefix="omcad_paket_")
    _temp.append(t)
    if name:
        t = os.path.join(t, name)
        os.makedirs(t)
    unter = os.path.join(t, P.UNTERORDNER)
    os.makedirs(os.path.join(unter, "Open MCP CAD"))
    shutil.copy(ps1 or INSTALL, os.path.join(unter, "install.ps1"))
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

    for t in _temp:
        shutil.rmtree(t, ignore_errors=True)
    n, ok = len(_ergebnisse), sum(_ergebnisse)
    print("\n%d/%d bestanden" % (ok, n))
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
