# -*- coding: utf-8 -*-
"""Open MCP CAD in den KI-Programmen eintragen: Codex, Claude Code, Claude
Desktop. Fuer den Installer (verteilung/install.ps1), ohne `mcp`.

    python -m open_mcp_cad.ki_eintragen finden
    python -m open_mcp_cad.ki_eintragen eintragen <codex|claude_code|claude_desktop> --python <PFAD>

Jeder Aufruf schreibt GENAU EINE Zeile JSON (nur ASCII) auf stdout — die
liest der Installer. Rueckmeldung 2026-09-29: Kollegen wussten nach der
Installation nicht, wie sie die KI-Programme einrichten; der Installer
zeigte nur, was von Hand einzutragen waere.

REGELN, jede im Gate (tests/test_installer.py I12-I19):
  * nie ohne Zustimmung: der Installer fragt je Programm [J/n];
  * vorher eine Sicherungskopie mit Zeitstempel neben der Datei
    (`<datei>.vor-open-mcp-cad-<JJJJMMTT-hhmmss>.bak`);
  * nur der eigene Eintrag `open-mcp-cad` kommt dazu — andere Eintraege
    bleiben, wie sie sind; ein vorhandener eigener Eintrag wird NIE
    geaendert (steht dort ein anderer Befehl, sagt es das nur);
  * ein zweiter Lauf aendert nichts (`schon_da`);
  * eine Datei, die sich nicht lesen laesst, bleibt unberuehrt (`fehler`);
    eine config.toml wird VOR dem Schreiben mit dem neuen Abschnitt
    geprueft, eine gesperrte Datei wird ein `fehler` (Gegenpruefung
    2026-09-29, I19);
  * gesagt wird, was geaendert wurde und wie man es zuruecknimmt.

Claude Code: ueber sein eigenes `claude mcp add --scope user` (gemessen an
CLI 2.1.263 mit einem Heimordner in Temp: `mcp get` gibt 1 ohne und 0 mit
Eintrag, ein zweites `add` gibt 1 "already exists"; geschrieben wird
`%USERPROFILE%\\.claude.json`). Codex: `[mcp_servers.open-mcp-cad]` in
`%USERPROFILE%\\.codex\\config.toml` (bzw. CODEX_HOME), im Format, das
`codex mcp add` schreibt (gemessen an codex-cli 0.156.1). Dass die
Codex-App dieselbe Datei liest, ist NICHT gemessen. Claude Desktop:
`mcpServers` in `%APPDATA%\\Claude\\claude_desktop_config.json`; liegt die
App als Store-Paket vor, auch unter
`%LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude` (auf dem
Entwicklungsrechner zeigen beide auf dieselbe Datei — dann nur einmal).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

NAME = "open-mcp-cad"
ARGS = ["-m", "open_mcp_cad.server"]
PROGRAMME = {"codex": "Codex", "claude_code": "Claude Code",
             "claude_desktop": "Claude Desktop"}
#: claude.cmd laeuft ueber cmd.exe, das diese Zeichen deutet (gemessen
#: 2026-09-28 am Chat: ein & fuehrte den Rest als eigenen Befehl aus).
BEFEHLSZEILE_VERBOTEN = '&|<>^%!"'


def _umgebung(env):
    return os.environ if env is None else env


def _heim(env):
    return env.get("USERPROFILE") or os.path.expanduser("~")


def codex_heim(env=None):
    env = _umgebung(env)
    return env.get("CODEX_HOME") or os.path.join(_heim(env), ".codex")


def _which(name, env):
    return shutil.which(name, path=env.get("PATH"))


def claude_programm(env=None):
    """claude.exe (eigener Installer) oder claude.cmd (npm) — oder None.

    DIESELBE Reihenfolge wie `cli_kandidaten` im Chat des Plugins
    (omcad_a_chat; test_chat_kern CX vergleicht beide in denselben Welten):
    feste Orte zuerst (frisch installiert steht es oft noch nicht auf dem
    PATH), der eigene Installer vor npm, dann der PATH."""
    env = _umgebung(env)
    kandidaten = [os.path.join(_heim(env), ".local", "bin", "claude.exe")]
    if env.get("APPDATA"):
        kandidaten.append(os.path.join(env["APPDATA"], "npm", "claude.cmd"))
    for kandidat in kandidaten:
        if os.path.isabs(kandidat) and os.path.isfile(kandidat):
            return kandidat
    for name in ("claude.exe", "claude.cmd"):
        gefunden = _which(name, env)
        if gefunden:
            return gefunden
    return None


def desktop_ordner(env=None):
    """Die Ordner, in denen Claude Desktop seine Einstellungen haelt —
    ohne doppelte (zwei Wege auf denselben Ordner zaehlen einmal)."""
    env = _umgebung(env)
    kandidaten = []
    if env.get("APPDATA"):
        kandidaten.append(os.path.join(env["APPDATA"], "Claude"))
    if env.get("LOCALAPPDATA"):
        kandidaten += sorted(glob.glob(os.path.join(
            env["LOCALAPPDATA"], "Packages", "Claude_*", "LocalCache",
            "Roaming", "Claude")))
    aus = []
    for k in kandidaten:
        if not os.path.isdir(k):
            continue
        if any(os.path.samefile(k, a) for a in aus):
            continue
        aus.append(k)
    return aus


def finden(env=None):
    """-> [{"programm", "name", "ort", "grund"}] fuer jedes gefundene
    Programm. Liest nur, aendert nichts."""
    env = _umgebung(env)
    aus = []
    heim = codex_heim(env)
    config = os.path.join(heim, "config.toml")
    app = []
    if env.get("LOCALAPPDATA"):
        app = glob.glob(os.path.join(env["LOCALAPPDATA"], "Packages",
                                     "OpenAI.Codex_*"))
    grund = ("config.toml da" if os.path.isfile(config) else
             "Ordner .codex da" if os.path.isdir(heim) else
             "codex auf dem PATH" if (_which("codex.cmd", env)
                                      or _which("codex.exe", env)) else
             "Codex-App installiert" if app else None)
    if grund:
        aus.append({"programm": "codex", "name": PROGRAMME["codex"],
                    "ort": config, "grund": grund})
    claude = claude_programm(env)
    if claude:
        aus.append({"programm": "claude_code",
                    "name": PROGRAMME["claude_code"], "ort": claude,
                    "grund": "claude gefunden"})
    for ordner in desktop_ordner(env):
        aus.append({"programm": "claude_desktop",
                    "name": PROGRAMME["claude_desktop"],
                    "ort": os.path.join(ordner, "claude_desktop_config.json"),
                    "grund": "Ordner Claude da"})
    # Claude Desktop nur EINMAL fragen, auch bei zwei Ordnern.
    gesehen, eins = set(), []
    for a in aus:
        if a["programm"] not in gesehen:
            gesehen.add(a["programm"])
            eins.append(a)
    return eins


# --- Hilfen -----------------------------------------------------------------

def _zeitstempel():
    return time.strftime("%Y%m%d-%H%M%S")


def sichern(datei):
    """Kopie neben der Datei, mit Zeitstempel. -> Pfad der Kopie."""
    basis = "%s.vor-open-mcp-cad-%s" % (datei, _zeitstempel())
    ziel, n = basis + ".bak", 2
    while os.path.exists(ziel):
        ziel, n = "%s-%d.bak" % (basis, n), n + 1
    shutil.copy2(datei, ziel)
    return ziel


def _schreiben(datei, daten):
    """Atomar: erst eine Temp-Datei daneben, dann ersetzen. Ist `datei` ein
    Verweis (symbolischer Link), wird das ZIEL geschrieben — sonst ersetzte
    os.replace den Verweis durch eine gewoehnliche Datei. Scheitert es,
    bleibt keine Temp-Datei liegen, und die Ausnahme geht weiter."""
    ziel = os.path.realpath(datei)
    tmp = ziel + ".open-mcp-cad.tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(daten)
        os.replace(tmp, ziel)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _ergebnis(programm, status, datei=None, sicherung=None, text="",
              rueckgaengig=""):
    return {"programm": programm, "name": PROGRAMME[programm],
            "status": status, "datei": datei, "sicherung": sicherung,
            "text": text, "rueckgaengig": rueckgaengig}


def _zurueck_kopieren(sicherung, datei):
    # `copy /Y` gibt es nur in der Eingabeaufforderung (cmd); in PowerShell
    # (dem Fenster des Installers) ist `copy` ein anderer Befehl und scheitert
    # an "/Y". Deshalb steht dabei, wo es hingehoert.
    return 'in der Eingabeaufforderung (cmd): copy /Y "%s" "%s"' % (
        sicherung, datei)


# --- Codex --------------------------------------------------------------------

def _toml_text(wert):
    """Ein TOML-String: literal wie `codex mcp add`, sonst mit Escapes."""
    if "'" not in wert and not any(ord(c) < 32 for c in wert):
        return "'%s'" % wert
    return '"%s"' % wert.replace("\\", "\\\\").replace('"', '\\"')


def codex_block(python, zeilenende="\n"):
    z = ["[mcp_servers.%s]" % NAME,
         "command = %s" % _toml_text(python),
         "args = [%s]" % ", ".join('"%s"' % a for a in ARGS)]
    return zeilenende.join(z) + zeilenende


def _toml_leser():
    """tomllib (ab Python 3.11), sonst das tomli, das pip mitbringt, sonst
    None. Gegenpruefung 2026-09-29: vorher nahm Python 3.10 (der Installer
    erlaubt 3.10 bis 3.13) statt eines Lesers nur eine Suche nach der
    eigenen Ueberschrift — eine kaputte oder unpassende config.toml (etwa
    `mcp_servers = { ... }` als Inline-Tabelle) wurde dann ungeprueft
    erweitert, und Codex haette sie nicht mehr lesen koennen."""
    try:
        import tomllib
        return tomllib
    except ImportError:
        pass
    try:
        from pip._vendor import tomli
        return tomli
    except ImportError:
        return None


def _toml_lesen(text, leser=None):
    """-> dict, oder wirft ValueError (auch, wenn es keinen Leser gibt).
    Ein BOM am Anfang zaehlt nicht (Notepad und PowerShell 5.1 schreiben
    ihn gern)."""
    leser = leser or _toml_leser()
    if leser is None:
        raise ValueError("kein TOML-Leser in diesem Python (weder tomllib "
                         "noch pip) - ungeprueft wird nichts eingetragen")
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        return leser.loads(text)
    except Exception as exc:                           # noqa: BLE001
        # TOMLDecodeError, aber auch RecursionError bei absurd tief
        # verschachtelten Tabellen: nie eine rohe Ausnahme nach aussen.
        raise ValueError("%s: %s" % (type(exc).__name__, exc))


def _codex_soll(python):
    return {"command": python, "args": list(ARGS)}


def codex_eintragen(config, python, leser=None):
    p = "codex"
    if os.path.isfile(config):
        with open(config, "rb") as fh:
            roh = fh.read()
        try:
            text = roh.decode("utf-8")
            daten = _toml_lesen(text, leser)
        except ValueError as exc:          # auch UnicodeDecodeError
            return _ergebnis(p, "fehler", config, text=(
                "config.toml laesst sich nicht lesen, nichts geaendert: %s"
                % str(exc)[:200]))
        server = daten.get("mcp_servers", {})
        if not isinstance(server, dict):
            return _ergebnis(p, "fehler", config, text=(
                "unerwarteter Aufbau (mcp_servers ist keine Tabelle), nichts "
                "geaendert"))
        vorhanden = server.get(NAME)
        if vorhanden is not None:
            if isinstance(vorhanden, dict) \
                    and vorhanden.get("command") == python \
                    and list(vorhanden.get("args") or []) == ARGS:
                return _ergebnis(p, "schon_da", config, text=(
                    "schon eingetragen, nichts geaendert"))
            befehl = (vorhanden.get("command") if isinstance(vorhanden, dict)
                      else vorhanden)
            return _ergebnis(p, "abweichend", config, text=(
                "schon eingetragen, aber anders (Befehl %s) - nichts "
                "geaendert. Soll der neue gelten: den Abschnitt "
                "[mcp_servers.%s] in %s loeschen und den Installer nochmals "
                "starten." % (befehl, NAME, config)))
        sicherung = sichern(config)
        ende = "\r\n" if b"\r\n" in roh else "\n"
        vorne = b"" if not roh or roh.endswith(b"\n") else ende.encode()
        neu = roh + vorne + (ende + codex_block(python, ende)).encode("utf-8")
        # Vor dem Schreiben pruefen, was danach in der Datei stuende: unser
        # Eintrag genau so, und ALLES andere wie vorher. Sonst bleibt die
        # Datei, wie sie ist (Gegenpruefung 2026-09-29: vorher geschrieben,
        # dann gelesen und nur nach unserem Namen gefragt).
        try:
            pruef = _toml_lesen(neu.decode("utf-8"), leser)
            ps = pruef.get("mcp_servers")
            ok = (isinstance(ps, dict) and ps.get(NAME) == _codex_soll(python)
                  and dict(pruef, mcp_servers={k: v for k, v in ps.items()
                                               if k != NAME})
                  == dict(daten, mcp_servers=server))
        except ValueError:
            ok = False
        if not ok:
            return _ergebnis(p, "fehler", config, sicherung, text=(
                "angefuegt waere config.toml nicht mehr lesbar oder anders "
                "gewesen (etwa mcp_servers als Inline-Tabelle) - nichts "
                "geaendert. Von Hand eintragen, siehe Anleitung."))
        _schreiben(config, neu)
        return _ergebnis(p, "eingetragen", config, sicherung, text=(
            "Abschnitt [mcp_servers.%s] am Ende von %s angefuegt, sonst "
            "nichts geaendert" % (NAME, config)),
            rueckgaengig=("den Abschnitt [mcp_servers.%s] am Ende von %s "
                          "loeschen - oder die Sicherung zurueckholen, %s"
                          % (NAME, config,
                             _zurueck_kopieren(sicherung, config))))
    os.makedirs(os.path.dirname(config), exist_ok=True)
    _schreiben(config, codex_block(python).encode("utf-8"))
    return _ergebnis(p, "eingetragen", config, text=(
        "%s neu angelegt, darin nur [mcp_servers.%s]" % (config, NAME)),
        rueckgaengig='del "%s"' % config)


# --- Claude Desktop -----------------------------------------------------------

def desktop_eintragen(config, python):
    p = "claude_desktop"
    eintrag = {"command": python, "args": list(ARGS)}
    if os.path.isfile(config):
        with open(config, "rb") as fh:
            roh = fh.read()
        try:
            daten = json.loads(roh.decode("utf-8-sig") or "{}")
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            return _ergebnis(p, "fehler", config, text=(
                "Datei laesst sich nicht lesen, nichts geaendert: %s"
                % str(exc)[:200]))
        server = daten.get("mcpServers") if isinstance(daten, dict) else None
        if not isinstance(daten, dict) or not isinstance(
                server if server is not None else {}, dict):
            return _ergebnis(p, "fehler", config, text=(
                "unerwarteter Aufbau (mcpServers ist kein Objekt), nichts "
                "geaendert"))
        server = server or {}
        if NAME in server:
            alt = server[NAME]
            if isinstance(alt, dict) and alt.get("command") == python \
                    and alt.get("args") == ARGS:
                return _ergebnis(p, "schon_da", config, text=(
                    "schon eingetragen, nichts geaendert"))
            return _ergebnis(p, "abweichend", config, text=(
                "schon eingetragen, aber anders (%s) - nichts geaendert"
                % json.dumps(alt)[:160]))
        sicherung = sichern(config)
        daten = dict(daten)
        daten["mcpServers"] = dict(server)
        daten["mcpServers"][NAME] = eintrag
        _schreiben(config, (json.dumps(daten, indent=2, ensure_ascii=False)
                            + "\n").encode("utf-8"))
        return _ergebnis(p, "eingetragen", config, sicherung, text=(
            "in %s unter mcpServers den Eintrag %s hinzugefuegt, alle "
            "anderen Eintraege unveraendert" % (config, NAME)),
            rueckgaengig=("den Eintrag \"%s\" unter mcpServers in %s "
                          "loeschen - oder die Sicherung zurueckholen, %s"
                          % (NAME, config,
                             _zurueck_kopieren(sicherung, config))))
    os.makedirs(os.path.dirname(config), exist_ok=True)
    _schreiben(config, (json.dumps({"mcpServers": {NAME: eintrag}},
                                   indent=2) + "\n").encode("utf-8"))
    return _ergebnis(p, "eingetragen", config, text=(
        "%s neu angelegt, darin nur %s" % (config, NAME)),
        rueckgaengig='del "%s"' % config)


# --- Claude Code --------------------------------------------------------------

def _claude_json(env):
    ordner = env.get("CLAUDE_CONFIG_DIR") or _heim(env)
    return os.path.join(ordner, ".claude.json")


def claude_code_eintragen(programm, python, env=None, ausfuehren=None):
    p = "claude_code"
    env = _umgebung(env)
    ausfuehren = ausfuehren or subprocess.run
    von_hand = 'claude mcp add --scope user %s -- "%s" %s' % (
        NAME, python, " ".join(ARGS))
    if programm.lower().endswith((".cmd", ".bat")) and any(
            c in python for c in BEFEHLSZEILE_VERBOTEN):
        return _ergebnis(p, "fehler", text=(
            "der Pfad enthaelt ein Zeichen, das cmd.exe deuten wuerde - "
            "nichts geaendert. Von Hand: %s" % von_hand))

    def rufen(*argumente):
        return ausfuehren([programm] + list(argumente), capture_output=True,
                          timeout=120, env=dict(env))
    try:
        r = rufen("mcp", "get", NAME)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _ergebnis(p, "fehler", text="claude laesst sich nicht "
                         "starten (%s), nichts geaendert. Von Hand: %s"
                         % (exc, von_hand))
    # Steht claude (noch) nicht auf dem PATH (frisch installiert), nennen
    # die Rueckwege den vollen Pfad.
    auf_path = any(_which(n, env) and os.path.normcase(_which(n, env))
                   == os.path.normcase(programm)
                   for n in ("claude.exe", "claude.cmd"))
    aufruf = "claude" if auf_path else '"%s"' % programm
    if r.returncode == 0:
        aus = (r.stdout or b"").decode("utf-8", "replace")
        m = re.search(r"(?m)^\s*Command:\s*(.+?)\s*$", aus)
        if m is None or m.group(1) == python:
            return _ergebnis(p, "schon_da", text=(
                "schon eingetragen, nichts geaendert"))
        return _ergebnis(p, "abweichend", text=(
            "schon eingetragen, aber mit anderem Befehl (%s) - nichts "
            "geaendert. Soll der neue gelten: %s mcp remove %s -s user, "
            "dann den Installer nochmals starten." % (m.group(1), aufruf,
                                                       NAME)))
    datei = _claude_json(env)
    sicherung = sichern(datei) if os.path.isfile(datei) else None
    try:
        r = rufen("mcp", "add", "--scope", "user", NAME, "--", python, *ARGS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _ergebnis(p, "fehler", datei, sicherung, text=(
            "claude mcp add lief nicht (%s). Von Hand: %s" % (exc, von_hand)))
    if r.returncode != 0:
        fehler = ((r.stderr or b"") + (r.stdout or b"")).decode(
            "utf-8", "replace").strip()[-300:]
        return _ergebnis(p, "fehler", datei, sicherung, text=(
            "claude mcp add meldet einen Fehler (%s). Von Hand: %s"
            % (fehler, von_hand)))
    return _ergebnis(p, "eingetragen", datei, sicherung, text=(
        "mit 'claude mcp add --scope user' eingetragen (fuer alle Ordner)"),
        rueckgaengig="%s mcp remove %s -s user" % (aufruf, NAME))


def _dateisicher(programm, datei, arbeit):
    """`arbeit()` -> Ergebnis. Ein Dateifehler (gesperrt, schreibgeschuetzt,
    Platte voll) wird ein `fehler` fuer diese Datei, nie eine rohe Ausnahme
    (Gegenpruefung 2026-09-29: vorher brach dann der ganze Aufruf ab). Die
    Datei bleibt, wie sie war: `_schreiben` ersetzt atomar."""
    try:
        return arbeit()
    except OSError as exc:
        return _ergebnis(programm, "fehler", datei, text=(
            "Datei liess sich nicht schreiben (%s: %s) - nichts geaendert. "
            "Ist sie in einem anderen Programm offen?"
            % (type(exc).__name__, exc)))


def eintragen(programm, python, env=None, ausfuehren=None):
    """-> Liste der Ergebnisse (Claude Desktop: je Ordner eines)."""
    env = _umgebung(env)
    if programm == "codex":
        config = os.path.join(codex_heim(env), "config.toml")
        return [_dateisicher(programm, config,
                             lambda: codex_eintragen(config, python))]
    if programm == "claude_code":
        exe = claude_programm(env)
        if not exe:
            return [_ergebnis(programm, "fehler", text="claude nicht gefunden")]
        return [_dateisicher(programm, _claude_json(env),
                             lambda: claude_code_eintragen(exe, python, env,
                                                           ausfuehren))]
    if programm == "claude_desktop":
        ordner = desktop_ordner(env)
        if not ordner:
            return [_ergebnis(programm, "fehler",
                              text="Claude Desktop nicht gefunden")]
        aus = []
        for o in ordner:
            config = os.path.join(o, "claude_desktop_config.json")
            aus.append(_dateisicher(programm, config, lambda c=config:
                                    desktop_eintragen(c, python)))
        return aus
    raise ValueError("unbekanntes Programm: %s" % programm)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["finden"]:
            aus = {"programme": finden()}
        elif argv[:1] == ["eintragen"] and len(argv) >= 4 \
                and argv[2] == "--python":
            aus = {"ergebnisse": eintragen(argv[1], argv[3])}
        else:
            aus = {"fehler": "Aufruf: finden | eintragen <programm> "
                             "--python <pfad>"}
    except Exception as exc:                           # noqa: BLE001
        aus = {"fehler": "%s: %s" % (type(exc).__name__, exc)}
    # EINE Zeile, nur ASCII: PowerShell 5.1 liest sie mit der Codepage der
    # Konsole.
    print(json.dumps(aus, ensure_ascii=True))
    return 0 if "fehler" not in aus else 1


if __name__ == "__main__":
    sys.exit(main())
