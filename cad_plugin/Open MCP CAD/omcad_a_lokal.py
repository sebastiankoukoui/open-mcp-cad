# -*- coding: utf-8 -*-
"""Lokale Modelle: Ollama und LM Studio erkennen, starten, installieren.

Wunsch (Uebergabe 2026-09-25, Abschnitt 3): ein lokales Modell nur dann als
"bereit" zeigen, wenn es installiert ist und sein Dienst laeuft; sonst
Starten bzw. Installieren anbieten.

OHNE QT UND OHNE cwapi3d, wie Chat und Anbieter. Alles hier kann warten
(Dateisystem, HTTP, Prozessstart); das Dashboard ruft es deshalb nur in
einem Nebenthread und liest im Qt-Takt nur die Ergebnisse.

ALLES, WAS ETWAS STARTET, geht durch `ausfuehren` -> `AUSFUEHREN`. Die
Gates setzen dort eine Attrappe ein, und ein Stolperdraht in test_a_live
macht jeden echten Aufruf von winget, ollama oder lms rot. Erkennen startet
nichts: `shutil.which` und Dateipruefungen, dazu ein GET an den Dienst.

Installiert wird NIE ohne Rueckfrage: das Dock fragt im Dock (nicht-modal)
und ruft `installieren` erst nach "Ja". Es laeuft `winget` in einem EIGENEN,
sichtbaren Fenster: dort sieht man den Fortschritt und bestaetigt selbst,
falls winget nach den Bedingungen des Herstellers fragt. Stillschweigend
zustimmen (`--accept-package-agreements`) tut dieses Modul nicht.

NICHT GEMESSEN (auf dem Entwicklungsrechner ist weder Ollama noch LM Studio
installiert, 2026-09-26): die Programmpfade unten sind die ueblichen
Installationsorte, und ob `lms server start` ohne vorher einmal
geoeffnetes LM Studio geht.
"""
import os
import shutil
import subprocess
import urllib.request

SCHNITTSTELLE = 1

#: So lange darf die Frage "laeuft der Dienst?" dauern. Sie laeuft im
#: Nebenthread; ein toter Port antwortet sofort mit "verweigert".
DIENST_TIMEOUT_S = 1.5

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NEW_CONSOLE = 0x00000010

# "programme": Namen auf dem PATH; "pfade": uebliche Installationsorte der
# Kommandozeile; "app": das Programm mit Fenster (nur LM Studio, dessen
# Kommandozeile `lms` erst nach dem ersten Start der App entsteht).
LOKAL = {
    "ollama": {
        "name": "Ollama",
        "programme": ("ollama",),
        "pfade": (r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",),
        "app": (),
        "dienst": "http://localhost:11434/api/tags",
        "starten": ("serve",),
        "winget": "Ollama.Ollama",
        "seite": "https://ollama.com/download",
    },
    "lmstudio": {
        "name": "LM Studio",
        "programme": ("lms",),
        "pfade": (r"%USERPROFILE%\.lmstudio\bin\lms.exe",),
        "app": (r"%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe",
                r"%LOCALAPPDATA%\Programs\lm-studio\LM Studio.exe"),
        "dienst": "http://localhost:1234/v1/models",
        "starten": ("server", "start"),
        "winget": "ElementLabs.LMStudio",
        "seite": "https://lmstudio.ai/download",
    },
}


class LokalFehler(Exception):
    pass


def ist_lokal(kennung):
    return kennung in LOKAL


# Ersetzbar (Gates): wo ein Programm liegt, und ob es eine Datei gibt.
WHICH = shutil.which
DATEI_DA = os.path.isfile


def _erster(kandidaten):
    for k in kandidaten:
        pfad = os.path.expandvars(k)
        if "%" not in pfad and DATEI_DA(pfad):
            return pfad
    return None


def programm(kennung):
    """Die Kommandozeile (`ollama`, `lms`) — oder None."""
    eintrag = LOKAL[kennung]
    for name in eintrag["programme"]:
        gefunden = WHICH(name)
        if gefunden:
            return gefunden
    return _erster(eintrag["pfade"])


def app(kennung):
    """Das Programm mit Fenster (nur LM Studio) — oder None."""
    return _erster(LOKAL[kennung].get("app") or ())


def _holen(url, timeout):
    """GET -> HTTP-Status. Ersetzbar ueber `HOLEN`."""
    with urllib.request.urlopen(url, timeout=timeout) as antwort:
        antwort.read(4096)
        return antwort.status


HOLEN = _holen


def dienst_laeuft(kennung, timeout=DIENST_TIMEOUT_S):
    """Antwortet der Dienst? Jeder Fehler heisst nein, nie eine Ausnahme."""
    try:
        return HOLEN(LOKAL[kennung]["dienst"], timeout) == 200
    except Exception:                                  # noqa: BLE001
        return False


def pruefen(kennung):
    """Der ganze Stand — WARTET (Dateisystem, HTTP): nur im Nebenthread.

    -> {"installiert", "programm", "app", "laeuft"}. Laeuft der Dienst,
    gilt das Programm als installiert, auch wenn es an einem Ort liegt,
    den diese Pruefung nicht kennt.
    """
    cli = programm(kennung)
    fenster = app(kennung)
    laeuft = dienst_laeuft(kennung)
    return {"installiert": bool(cli or fenster or laeuft), "programm": cli,
            "app": fenster, "laeuft": laeuft}


def start_befehl(kennung, stand):
    """Der Befehl, der den Dienst startet — oder None.

    LM Studio ohne `lms`: die App selbst (den Server schaltet man dort ein).
    """
    cli = (stand or {}).get("programm")
    if cli:
        return [cli] + list(LOKAL[kennung]["starten"])
    fenster = (stand or {}).get("app")
    if fenster:
        return [fenster]
    return None


def install_befehl(kennung):
    """winget im offiziellen Katalog, genau diese Paket-Kennung."""
    winget = WHICH("winget")
    if not winget:
        raise LokalFehler(
            "Windows kann %s hier nicht selbst installieren (winget fehlt). "
            "Bitte von %s herunterladen."
            % (LOKAL[kennung]["name"], LOKAL[kennung]["seite"]))
    return [winget, "install", "--id", LOKAL[kennung]["winget"], "--exact",
            "--source", "winget"]


def _ausfuehren_echt(befehl, fenster=False):
    """Einen Prozess LOSGELOEST starten und sofort zurueckkehren.

    `fenster`: ein eigenes, sichtbares Konsolenfenster (winget); sonst
    ohne Fenster und ohne Verbindung zu Cadwork — der Dienst laeuft weiter,
    wenn Cadwork endet.
    """
    if os.name == "nt":
        flags = CREATE_NEW_PROCESS_GROUP | (
            CREATE_NEW_CONSOLE if fenster
            else DETACHED_PROCESS | CREATE_NO_WINDOW)
    else:
        flags = 0
    umlenken = {} if fenster else {"stdin": subprocess.DEVNULL,
                                   "stdout": subprocess.DEVNULL,
                                   "stderr": subprocess.DEVNULL}
    proc = subprocess.Popen(list(befehl), close_fds=True, creationflags=flags,
                            **umlenken)
    return proc.pid


AUSFUEHREN = _ausfuehren_echt


def ausfuehren(befehl, fenster=False):
    return AUSFUEHREN(list(befehl), fenster=fenster)


def starten(kennung, stand):
    """Den Dienst starten. WARTET nicht auf ihn — das Dock fragt danach
    ein paar Sekunden lang nach, ob er antwortet."""
    befehl = start_befehl(kennung, stand)
    if befehl is None:
        raise LokalFehler("%s ist nicht installiert." % LOKAL[kennung]["name"])
    try:
        ausfuehren(befehl)
    except OSError as exc:
        raise LokalFehler("%s startet nicht: %s"
                          % (LOKAL[kennung]["name"], exc))
    return befehl


def installieren(kennung):
    """winget in einem eigenen Fenster starten. NUR nach "Ja" im Dock."""
    befehl = install_befehl(kennung)
    try:
        ausfuehren(befehl, fenster=True)
    except OSError as exc:
        raise LokalFehler("Installation startet nicht: %s" % exc)
    return befehl
