# -*- coding: utf-8 -*-
"""Chat-Anbieter neben Claude Code: Codex und jede OpenAI-kompatible Schnittstelle.

BEWUSST OHNE QT UND OHNE cwapi3d — aus demselben Grund wie omcad_a_chat:
der Qt-Takt zeichnet das Dock UND arbeitet die Cadwork-Auftraege ab. Alles,
was wartet (HTTP, der MCP-Server, die Freigabe), laeuft hier in EINEM
Nebenthread und legt nur Eintraege ins gemeinsame `chat`-Dict. Das Dashboard
zeichnet daraus genau wie beim CLI.

EINE Schnittstelle, viele Anbieter (Wunsch 2026-09-24: "openai cli nehmen
... oder ueber api key oder generell ueber lokale KI"): OpenAI, OpenRouter,
Anthropic (dessen OpenAI-kompatibler Zugang), Ollama und LM Studio sprechen
alle `POST <basis>/chat/completions` mit `tools`. Unterschiede stecken nur
in Adresse, Schluessel und Kopfzeilen.

DIE SCHLEIFE IST UNSERE. Anders als beim Claude-Code-CLI gibt es keinen
fremden Agenten mit eigenen Werkzeugen (Bash, Dateien): das Modell sieht
NUR die Werkzeuge des MCP-Servers `open_mcp_cad.server`, den diese Schleife
selbst startet. Und jeder Aufruf geht VOR dem Server durch dieselbe
Freigabe-Politik wie beim CLI (`chat_entscheiden` aus omcad_a_chat,
hereingereicht: "ja", "nein" oder "fragen"). Antwortet niemand, wird nicht ausgefuehrt — das Gate
faellt zu, nicht auf.

CODEX ist ein eigener Agent wie Claude Code und laeuft deshalb NICHT durch
diese Schleife, sondern ueber seinen App-Server (`CodexSitzung`, unten) —
mit derselben Schnittstelle zum Dashboard und derselben Freigabe-Politik.
"""
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request

# = ANBIETER_SCHNITTSTELLE im Dashboard; heben bei Bedarf.
# 2 (2026-09-27, Chatfenster K1): die hereingereichte Entscheidung heisst
# `entscheiden(chat, werkzeug, anfrage)` und antwortet "ja", "nein" oder
# "fragen" (vorher `erlauben(stufe, …)` -> bool); Ereignisse mit `zeit`,
# Werkzeuge mit `id`, Ergebnisse (`ergebnis`), Ablehnungen (`verweigert`).
# 3 (2026-09-27, K4): `senden(text, anhaenge=)` — Bilder als `image_url`
# (Schleife) bzw. `{"type": "image", "url": …}` (Codex).
SCHNITTSTELLE = 3

CREATE_NO_WINDOW = 0x08000000

# Praefix, unter dem die Freigabe-Politik die Werkzeuge dieses Servers
# kennt — derselbe Name wie beim CLI (`mcp__<server>__<werkzeug>`). Nur so
# greift `ist_cadwork` unveraendert.
MCP_PRAEFIX = "mcp__open-mcp-cad__"

# Obergrenze der Runden je Nutzernachricht. Ein Modell, das sich im Kreis
# ruft, soll nicht unbemerkt Stunden und Geld verbrauchen.
MAX_RUNDEN = 40

HTTP_TIMEOUT = 600          # lokale Modelle auf der CPU brauchen Minuten
MCP_START_TIMEOUT = 60
MCP_AUFRUF_TIMEOUT = 900    # der Server hat eigene Bridge-Timeouts darunter

# "art": "cli" = Claude Code (omcad_a_chat), "openai" = diese Schleife,
# "codex" = CodexSitzung (Codex-App-Server, unten).
# "env": Umgebungsvariable, aus der der Schluessel kommen DARF (nach dem
# Tresor). "schluessel": Pflicht, optional oder keiner.
# "abo": bezahlt ueber ein Abo, nicht je Aufruf. Das Dock zeigt dort keinen
# USD-Betrag an (Film 2026-09-25: "fertig · 1.40 USD" nach jedem Zug von
# Claude Code wirkte wie Kosten je Lauf — im Abo ist das keine Rechnung).
# Ein eigenes Feld, nicht "Abo" im Namen: ein Name entscheidet nichts.
# "schluessel_url": wo man beim Anbieter einen Schluessel erstellt — das Dock
# verlinkt die Seite (Uebergabe 2026-09-25, Abschnitt 2: "das mit der
# Website kenne ich nicht"). Ein Anbieter ohne Feld bekommt keinen Link.
ANBIETER = (
    {"id": "claude", "name": "Claude Code (Abo)", "art": "cli", "abo": True},
    {"id": "codex", "name": "Codex (ChatGPT-Abo)", "art": "codex", "abo": True},
    {"id": "openai", "name": "OpenAI (Schlüssel, ohne Abo)", "art": "openai",
     "basis": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
     "schluessel": "pflicht",
     "schluessel_url": "https://platform.openai.com/api-keys"},
    {"id": "anthropic", "name": "Anthropic (Schlüssel, ohne Abo)", "art": "openai",
     "basis": "https://api.anthropic.com/v1", "env": "ANTHROPIC_API_KEY",
     "schluessel": "pflicht",
     "schluessel_url": "https://console.anthropic.com/settings/keys",
     # Der OpenAI-kompatible Zugang nimmt den Bearer-Schluessel; die
     # Modell-Liste (/v1/models) ist die native und will diese beiden.
     "kopf": {"anthropic-version": "2023-06-01"}, "kopf_schluessel": "x-api-key"},
    {"id": "openrouter", "name": "OpenRouter (Schlüssel, ohne Abo)", "art": "openai",
     "basis": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY",
     "schluessel": "pflicht",
     "schluessel_url": "https://openrouter.ai/keys"},
    {"id": "ollama", "name": "Ollama (lokal)", "art": "openai",
     "basis": "http://localhost:11434/v1", "schluessel": "keiner"},
    {"id": "lmstudio", "name": "LM Studio (lokal)", "art": "openai",
     "basis": "http://localhost:1234/v1", "schluessel": "keiner"},
    {"id": "eigen", "name": "Eigene Adresse (OpenAI-kompatibel)", "art": "openai",
     "basis": "", "schluessel": "optional"},
)
ANBIETER_VORGABE = "claude"

# Was die Modell-Liste von OpenAI sonst noch fuehrt: Bilder, Sprache,
# Einbettungen. Nichts davon kann ein Gespraech mit Werkzeugen fuehren.
NICHT_CHAT = ("embedding", "tts", "whisper", "dall-e", "moderation",
              "transcribe", "image", "audio", "realtime", "search", "davinci",
              "babbage", "sora")


class AnbieterFehler(Exception):
    pass


def anbieter(kennung):
    for a in ANBIETER:
        if a["id"] == kennung:
            return a
    raise AnbieterFehler("unbekannter Anbieter: %r" % (kennung,))


# --- Einstellungen (ohne Schluessel) --------------------------------------
# Anbieter, Adresse und Modell ueberleben den Cadwork-Neustart; sonst
# waehlt man bei jedem Start von vorn. Der SCHLUESSEL steht hier nie — der
# gehoert in den Tresor. Seit dem Film 2026-09-25 auch Modell und Denkstufe
# von Claude Code (`modell.claude`, `denkstufe`). Seit 2026-09-27 auch der
# Modus (`modus`) — "Alles automatisch" aber NIE (das Dashboard schreibt
# dann "cadwork_frei", MODUS_NIE_MERKEN in omcad_a_chat).

def _einstellungs_datei():
    gesetzt = os.environ.get("OPEN_MCP_CAD_CHAT_EINSTELLUNGEN", "").strip()
    if gesetzt:
        return gesetzt
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "OpenMcpCad", "chat.json")


def einstellungen_lesen():
    """chat.json als dict. Kaputt oder fremd heisst leer, nie ein Fehler.

    Nur die OBERSTE Ebene wird hier geprueft; was darunter steht (etwa
    `modell` als Text statt als Tabelle), faengt das Dashboard beim
    Auslesen ab (`_gemerkt`) — es muss das ohnehin, weil dieses Modul bis
    zum Cadwork-Neustart in einer alten Fassung im Speicher liegen kann.
    RecursionError: ein tief verschachteltes JSON wirft sonst an json.load
    vorbei.
    """
    try:
        with open(_einstellungs_datei(), encoding="utf-8") as fh:
            daten = json.load(fh)
        return daten if isinstance(daten, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def einstellungen_schreiben(daten):
    """chat.json schreiben. -> True, wenn es geklappt hat. Wirft NIE.

    Gegenpruefung 2026-09-26: ein chat.json, das 1000-2000 Ebenen tief
    verschachtelt ist, liest `json.load` noch (der C-Leser), `json.dump` mit
    `indent` (reines Python) wirft beim Zurueckschreiben RecursionError.
    Gefangen war nur OSError — der Fehler lief aus dem Qt-Slot des
    Anbieterwechsels, und in Cadwork endet das in qFatal. Ausserdem war die
    Datei da schon mit "w" geleert und halb geschrieben.

    Deshalb: erst der GANZE Text im Speicher (scheitert er, bleibt die Datei
    unberuehrt), dann eine Temp-Datei im selben Ordner, dann `os.replace`
    (auf demselben Laufwerk atomar). Jeder Fehler heisst False; eine
    liegengebliebene Temp-Datei wird entfernt. test_anbieter A13b.
    """
    tmp = None
    try:
        text = json.dumps(daten, ensure_ascii=False, indent=1)
        pfad = os.path.abspath(_einstellungs_datei())
        ordner = os.path.dirname(pfad)
        os.makedirs(ordner, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".chat-", suffix=".tmp", dir=ordner)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, pfad)
        tmp = None
        return True
    except Exception:                                  # noqa: BLE001
        return False
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


# --- Schluessel im Windows-Tresor -----------------------------------------
# Anmeldeinformationsverwaltung, "Generische Anmeldeinformationen". Kein
# Klartext neben dem Plugin, keine Umgebungsvariable noetig. Nur fuer
# DIESEN Windows-Benutzer lesbar.

TRESOR_PRAEFIX = "Open MCP CAD/"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
                ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
                ("LastWritten", _FILETIME),
                ("CredentialBlobSize", ctypes.c_uint32),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p)]


def _advapi():
    if os.name != "nt":
        raise AnbieterFehler("der Schluessel-Tresor gibt es nur unter Windows")
    return ctypes.WinDLL("advapi32", use_last_error=True)


def schluessel_speichern(kennung, wert, praefix=None):
    praefix = praefix or TRESOR_PRAEFIX
    roh = wert.strip().encode("utf-8")
    if not roh:
        raise AnbieterFehler("leerer Schluessel")
    puffer = (ctypes.c_ubyte * len(roh)).from_buffer_copy(roh)
    cred = _CREDENTIAL(Type=_CRED_TYPE_GENERIC, TargetName=praefix + kennung,
                       CredentialBlobSize=len(roh),
                       CredentialBlob=ctypes.cast(puffer, ctypes.POINTER(ctypes.c_ubyte)),
                       Persist=_CRED_PERSIST_LOCAL_MACHINE,
                       UserName="Open MCP CAD")
    if not _advapi().CredWriteW(ctypes.byref(cred), 0):
        raise AnbieterFehler("Tresor: Schreiben fehlgeschlagen (Windows-Fehler %d)"
                             % ctypes.get_last_error())


def schluessel_lesen(kennung, praefix=None):
    """Der gespeicherte Schluessel oder None."""
    praefix = praefix or TRESOR_PRAEFIX
    if os.name != "nt":
        return None
    api = _advapi()
    zeiger = ctypes.POINTER(_CREDENTIAL)()
    if not api.CredReadW(praefix + kennung, _CRED_TYPE_GENERIC, 0,
                         ctypes.byref(zeiger)):
        return None
    try:
        c = zeiger.contents
        return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-8")
    finally:
        api.CredFree(zeiger)


def schluessel_loeschen(kennung, praefix=None):
    praefix = praefix or TRESOR_PRAEFIX
    if os.name != "nt":
        return False
    return bool(_advapi().CredDeleteW(praefix + kennung, _CRED_TYPE_GENERIC, 0))


def schluessel_fuer(a, praefix=None):
    """-> (Schluessel oder None, Herkunft fuer die Anzeige)."""
    if a.get("schluessel", "keiner") == "keiner":
        return None, "kein Schlüssel nötig"
    wert = schluessel_lesen(a["id"], praefix)
    if wert:
        return wert, "Schlüssel im Windows-Tresor"
    if a.get("env") and os.environ.get(a["env"], "").strip():
        return os.environ[a["env"]].strip(), "Schlüssel aus %s" % a["env"]
    if a.get("schluessel") == "optional":
        return None, "ohne Schlüssel"
    return None, "Schlüssel fehlt"


# --- HTTP -----------------------------------------------------------------

def _kopf(a, schluessel):
    kopf = {"Content-Type": "application/json"}
    if schluessel:
        kopf["Authorization"] = "Bearer %s" % schluessel
        if a.get("kopf_schluessel"):
            kopf[a["kopf_schluessel"]] = schluessel
    kopf.update(a.get("kopf") or {})
    return kopf


def _http(url, kopf, daten=None, timeout=HTTP_TIMEOUT):
    anfrage = urllib.request.Request(
        url, data=None if daten is None else json.dumps(daten).encode("utf-8"),
        headers=kopf, method="GET" if daten is None else "POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Der Text der Antwort sagt fast immer, was los ist (falscher
        # Schluessel, unbekanntes Modell, Kontingent) — nicht verschlucken.
        try:
            koerper = exc.read().decode("utf-8", "replace")
            daten = json.loads(koerper)
            fehler = daten.get("error")
            meldung = (fehler.get("message") if isinstance(fehler, dict)
                       else fehler) or koerper
        except Exception:                               # noqa: BLE001
            meldung = str(exc.reason)
        raise AnbieterFehler("HTTP %d: %s" % (exc.code, str(meldung)[:300]))
    except urllib.error.URLError as exc:
        raise AnbieterFehler("%s ist nicht erreichbar (%s) — laeuft der "
                             "Dienst?" % (url, exc.reason))
    except (OSError, ValueError) as exc:
        raise AnbieterFehler("%s: %s" % (url, exc))


def _basis(a, basis):
    basis = (basis or a.get("basis") or "").strip().rstrip("/")
    if not basis.startswith(("http://", "https://")):
        raise AnbieterFehler("keine gueltige Adresse: %r (http://… oder "
                             "https://…)" % basis)
    return basis


def modelle_laden(a, basis=None, schluessel=None, timeout=20):
    """Die Modelle, die der Dienst JETZT anbietet — statt einer Liste im Code.

    Die Frage "sind die Modelle ueberhaupt aktuell?" (2026-09-24) laesst
    sich fuer eine feste Liste nie mit Ja beantworten. Der Dienst selbst
    weiss es. Laeuft im Nebenthread, nie im Qt-Takt.
    """
    if a["art"] == "codex":
        return codex_modelle(timeout=max(timeout, 60))
    daten = _http(_basis(a, basis) + "/models", _kopf(a, schluessel),
                  timeout=timeout)
    ids = [str(m.get("id")) for m in (daten.get("data") or [])
           if isinstance(m, dict) and m.get("id")]
    if a["id"] == "openai":
        ids = [i for i in ids if not any(n in i.lower() for n in NICHT_CHAT)]
    return sorted(set(ids))


# --- MCP ueber stdio -------------------------------------------------------

class McpKlient:
    """Minimaler MCP-Client (JSON-RPC ueber stdio) fuer EINEN Server.

    Das Paket `mcp` gibt es in Cadworks Python nicht, und es braucht hier
    auch nur vier Aufrufe: initialize, tools/list, tools/call, Ende.
    """

    def __init__(self, befehl, umgebung=None):
        env = dict(os.environ)
        env.update(umgebung or {})
        try:
            self.proc = subprocess.Popen(
                befehl, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=env,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as exc:
            # Ein fehlendes Python ist ein Grund, OHNE Werkzeuge zu reden —
            # nicht, den ganzen Chat sterben zu lassen (gemessen: vorher
            # riss dieser Fehler den Arbeitsthread mit).
            raise AnbieterFehler("MCP-Server startet nicht (%s): %s"
                                 % (befehl[0], exc))
        self._naechste = 0
        self._zeilen = queue.Queue()
        self.stderr = []
        self.anleitung = ""
        # Beide Pipes lesen, immer: eine volle Pipe blockiert das Kind
        # (dasselbe Argument wie beim CLI, `_fehlerleser_starten`).
        threading.Thread(target=self._lesen, daemon=True,
                         name="Open-MCP-CAD-MCP-Leser").start()
        threading.Thread(target=self._fehler_lesen, daemon=True,
                         name="Open-MCP-CAD-MCP-Fehler").start()

    def _lesen(self):
        try:
            for zeile in self.proc.stdout:
                zeile = zeile.strip()
                if zeile:
                    self._zeilen.put(zeile)
        finally:
            self._zeilen.put(None)

    def _fehler_lesen(self):
        try:
            for zeile in self.proc.stderr:
                self.stderr.append(zeile.rstrip())
                del self.stderr[:-40]
        except Exception:                               # noqa: BLE001
            pass

    def _schreiben(self, obj):
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AnbieterFehler("MCP-Server nimmt nichts an: %s%s"
                                 % (exc, self._letzte_stoerung()))

    def _letzte_stoerung(self):
        zeilen = [z for z in self.stderr if z.strip()]
        return (" — " + zeilen[-1][:200]) if zeilen else ""

    def rufen(self, methode, params=None, timeout=MCP_AUFRUF_TIMEOUT):
        self._naechste += 1
        kennung = self._naechste
        self._schreiben({"jsonrpc": "2.0", "id": kennung, "method": methode,
                         "params": params or {}})
        ende = time.monotonic() + timeout
        while True:
            rest = ende - time.monotonic()
            if rest <= 0:
                raise AnbieterFehler("MCP-Server antwortet nicht auf %s"
                                     % methode)
            try:
                zeile = self._zeilen.get(timeout=rest)
            except queue.Empty:
                continue
            if zeile is None:
                raise AnbieterFehler("MCP-Server beendet%s"
                                     % self._letzte_stoerung())
            try:
                obj = json.loads(zeile)
            except ValueError:
                continue                    # Fremdausgabe auf stdout
            if obj.get("id") != kennung:
                continue                    # Benachrichtigung o. ae.
            if obj.get("error"):
                raise AnbieterFehler("MCP %s: %s" % (
                    methode, (obj["error"] or {}).get("message")))
            return obj.get("result") or {}

    def starten(self):
        erg = self.rufen("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "open-mcp-cad-chat", "version": "2"}},
            timeout=MCP_START_TIMEOUT)
        self.anleitung = erg.get("instructions") or ""
        self._schreiben({"jsonrpc": "2.0",
                         "method": "notifications/initialized"})
        werkzeuge, zeiger = [], None
        while True:
            erg = self.rufen("tools/list", {"cursor": zeiger} if zeiger else {},
                             timeout=MCP_START_TIMEOUT)
            werkzeuge += erg.get("tools") or []
            zeiger = erg.get("nextCursor")
            if not zeiger:
                return werkzeuge

    def werkzeug(self, name, argumente):
        """-> (Text, ist_fehler)."""
        erg = self.rufen("tools/call", {"name": name, "arguments": argumente})
        teile = []
        for blk in erg.get("content") or []:
            if isinstance(blk, dict) and blk.get("type") == "text":
                teile.append(blk.get("text") or "")
            elif isinstance(blk, dict):
                teile.append("[%s]" % blk.get("type"))
        if not teile and erg.get("structuredContent") is not None:
            teile.append(json.dumps(erg["structuredContent"], ensure_ascii=False))
        return "\n".join(teile), bool(erg.get("isError"))

    def beenden(self):
        try:
            self.proc.stdin.close()
        except Exception:                               # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:                               # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:                           # noqa: BLE001
                pass


def _als_funktion(werkzeug):
    """MCP-Werkzeug -> OpenAI-`tools`-Eintrag. Beschreibung UNGEKUERZT: in
    der von execute_cadwork_command stehen die Stolperfallen der API."""
    schema = werkzeug.get("inputSchema") or {"type": "object", "properties": {}}
    return {"type": "function", "function": {
        "name": werkzeug["name"],
        "description": werkzeug.get("description") or "",
        "parameters": schema}}


SYSTEM = (
    "Du arbeitest in Cadwork 3D, und zwar ausschliesslich ueber die Werkzeuge "
    "des MCP-Servers open-mcp-cad. Verbunden ist das Dokument %(dokument)s "
    "(Port %(port)s). Antworte knapp. Jeder "
    "Aufruf, der das Modell anfasst, wird dem Nutzer vorher zur Freigabe "
    "gezeigt; lehnt er ab, frag nach, statt es erneut zu versuchen.")

# Befund Film 2026-09-25: das Dock zeigt reinen Text, der Chat schrieb aber
# Markdown ("**Staebe**") und teils Englisch. Derselbe Wortlaut steht als
# DOCK_ANWEISUNG in omcad_a_chat (dort als --append-system-prompt fuer das
# CLI); dieses Modul importiert jenes nicht (in Cadwork liegen beide unter
# festen Namen in sys.modules, das Dashboard reicht nur Funktionen herein).
# ZWEI Kopien also, und darum ein Gate: test_chat_kern M4 vergleicht beide
# Konstanten aus dem QUELLTEXT, M1-M3 verlangen, dass der VOLLE Wortlaut
# in allen drei Wegen ankommt. Nur beide zusammen aendern.
DOCK_ANWEISUNG = (
    "Deine Antworten erscheinen im Chat des Open-MCP-CAD-Docks in Cadwork, "
    "und der zeigt reinen Text an. Schreib deshalb kein Markdown: keine "
    "Sternchen zum Hervorheben, auch nicht als Verzierung, keine Rauten für "
    "Überschriften, keine Tabellen, keine Backticks und keine Codeblöcke. "
    "Hervorheben geht mit Worten oder Grossbuchstaben, auch wenn der "
    "Nutzer ausdrücklich um Fettdruck bittet. Aufzählungen mit einem "
    "einfachen Bindestrich oder mit Nummern, Code als schlichte Zeilen. "
    "Antworte immer in der Sprache des Nutzers, also in der Sprache seiner "
    "letzten Nachricht: auf eine deutsche deutsch, auf eine englische "
    "englisch, auf eine französische französisch. Das gilt auch, wenn "
    "Werkzeuge, Fehlermeldungen oder Unterlagen englisch sind. "
    # Rueckmeldung 2026-09-28: im Modus Nur lesen bekam die KI nur "nicht
    # erneut versuchen" und suchte andere Wege. Ohne Anfuehrungszeichen und
    # Guillemets: der Text geht durch claude.cmd, also durch cmd.exe.
    "Im Modus Nur lesen lehnt der Chat jeden Aufruf ab, der etwas ändert. "
    "Der Nutzer sieht dann im Chat einen Hinweis und kann den Modus mit "
    "einem Klick wechseln. Versuch es in dem Fall nicht auf einem anderen "
    "Weg, sondern sag dem Nutzer kurz, was du tun wolltest.")


def systemtext(dokument=None, port=None):
    """Die Anweisung an das Modell — EINE Quelle fuer Schleife und Codex.

    Die Dock-Regel wird angehaengt, nicht in SYSTEM eingesetzt: SYSTEM ist
    ein %-Muster, DOCK_ANWEISUNG reiner Text.
    """
    return (SYSTEM % {"dokument": dokument or "(unbekannt)",
                      "port": port or "?"}) + " " + DOCK_ANWEISUNG


# --- Ein Gespraech im gemeinsamen Dict ------------------------------------

def _zahl(wert):
    return int(wert) if isinstance(wert, (int, float)) and wert > 0 else 0


def _runde_belegt(usage):
    """Token der letzten Runde der Schleife (Frage + Antwort) — oder None."""
    if not isinstance(usage, dict):
        return None
    summe = _zahl(usage.get("prompt_tokens"))         + _zahl(usage.get("completion_tokens"))
    return summe or _zahl(usage.get("total_tokens")) or None


def _codex_kontext(nutzung):
    """{"belegt", "fenster"} aus `thread/tokenUsage/updated` — oder None."""
    if not isinstance(nutzung, dict):
        return None
    letzte = nutzung.get("last")
    if not isinstance(letzte, dict):
        return None
    belegt = _zahl(letzte.get("totalTokens")) or (
        _zahl(letzte.get("inputTokens")) + _zahl(letzte.get("outputTokens")))
    if not belegt:
        return None
    return {"belegt": belegt,
            "fenster": _zahl(nutzung.get("modelContextWindow")) or None}


class _Verlauf(list):
    """Der Verlauf eines Gespraechs: jeder Eintrag bekommt beim Anhaengen
    seine Zeit (fuer die Zeitmarken im Dock). Eine Liste mit Stempel statt
    einer Zeit an jeder der vielen Stellen, die hier anhaengen."""

    def append(self, eintrag):
        if isinstance(eintrag, dict):
            eintrag.setdefault("zeit", time.time())
        super().append(eintrag)


def _mit_anhaengen(text, anhaenge):
    """Text samt den Anhaengen, die als TEXT mitgehen — dieselbe Regel wie
    `omcad_a_chat._mit_anhaengen` (dieses Modul importiert jenes nicht)."""
    teile = [text] if text else []
    teile += [a.get("als_text") for a in anhaenge or ()
              if a.get("art") != "bild" and a.get("als_text")]
    return "\n\n".join(teile)


def _data_url(a):
    return "data:%s;base64,%s" % (a.get("mime") or "image/png", a["b64"])


def _bilder(anhaenge):
    return [a for a in anhaenge or () if a.get("art") == "bild"
            and a.get("b64")]


def _ich(text, anhaenge):
    """Der Eintrag "ich" im Verlauf — mit den NAMEN der Anhaenge."""
    e = {"art": "ich", "text": text}
    if anhaenge:
        e["anhaenge"] = [a.get("name") or "?" for a in anhaenge]
    return e


#: Scheitert eine Nachricht mit Bildern, steht das im Verlauf (die Bilder
#: sind dann aus dem Gespraech genommen, s. `Schleife._zug`).
BILD_HINWEIS = ("⚠ Die Nachricht hatte Bilder. Nimmt dieses Modell keine "
                "Bilder, hilft ein Modell mit Bildverständnis. Die Bilder "
                "sind aus dem Gespräch genommen — die nächste Nachricht "
                "geht ohne sie.")


def _ohne_bilder(inhalt):
    """Der Inhalt einer Nutzernachricht ohne ihre Bilder (ein Satz statt
    ihrer, damit das Modell weiss, dass da welche waren)."""
    if not isinstance(inhalt, list):
        return inhalt
    texte = [b.get("text") or "" for b in inhalt
             if isinstance(b, dict) and b.get("type") == "text"]
    weg = sum(1 for b in inhalt
              if isinstance(b, dict) and b.get("type") == "image_url")
    return ("\n\n".join(t for t in texte if t.strip())
            + "\n\n[%d Bild(er) nicht übertragen]" % weg).strip()


#: Was das Modell hoert, wenn der Modus einen Aufruf ohne Frage ablehnt —
#: derselbe Wortlaut wie ABLEHNUNG_VORLAGE in omcad_a_chat (Rueckmeldung
#: 2026-09-28, test_chat_kern SP4 vergleicht beide Kopien aus der Quelle).
ABLEHNUNG_VORLAGE = (
    "Abgelehnt, ohne den Nutzer zu fragen: Im Modus «%(modus)s» ist "
    "%(werkzeug)s gesperrt, weil es etwas ändern oder ausserhalb des "
    "Arbeitsordners zugreifen würde. Der Nutzer sieht dazu jetzt im Chat "
    "einen Hinweis und kann dort mit einem Klick in den Modus «Fragen» "
    "wechseln. Versuch es nicht erneut und nicht auf einem anderen Weg. Sag "
    "dem Nutzer stattdessen in ein, zwei Sätzen, was du tun wolltest und "
    "warum — dann entscheidet er.")
#: Nur "Nur lesen" lehnt ohne Frage ab; die anderen Namen fuer den Fall,
#: dass sich das aendert (sonst stuende dort der rohe Wert).
_MODUS_ANZEIGE = {"nur_lesen": "Nur lesen", "fragen": "Fragen",
                  "cadwork_frei": "Cadwork frei",
                  "alles_auto": "Alles automatisch"}


def ablehnung(chat, name):
    """Der Text fuer das Modell, wenn der Modus `name` ohne Frage ablehnt."""
    modus = (chat or {}).get("modus")
    return ABLEHNUNG_VORLAGE % {
        "modus": _MODUS_ANZEIGE.get(modus, modus or "gewählt"),
        "werkzeug": name}


def _urteil(entscheiden, chat, werkzeug, anfrage=None):
    """Die hereingereichte Entscheidung als "ja", "nein" oder "fragen".

    Eine Entscheidung, die (wie vor Schnittstelle 2) wahr/falsch liefert,
    heisst "ja" bzw. "fragen"; alles Unbekannte heisst "fragen" — nie mehr
    Freiheit als ausdruecklich gegeben."""
    try:
        wert = entscheiden(chat, werkzeug, anfrage or {})
    except Exception:                                   # noqa: BLE001
        return "fragen"
    if wert is True:
        return "ja"
    return wert if wert in ("ja", "nein") else "fragen"


class _Gespraech:
    """Was Schleife und CodexSitzung teilen: WELCHER Chat bin ich?

    Alle Anbieter schreiben in EIN Dict (`chat`), das das Dock zeichnet.
    Befund 2026-09-25: das `finally` eines alten Arbeitsthreads (oder ein
    spaetes `beenden()`) setzte `an`/`laeuft_zug`/`denkt` auch dann zurueck,
    wenn laengst ein NEUER Chat lief — und lehnte dessen Karten ab, weil es
    `chat["freigaben"]` las. Deshalb:

      * Verlauf und Karten sind die EIGENEN Listen dieses Gespraechs
        (`starten` haengt genau diese ins Dict). Ein abgeloestes Gespraech
        schreibt in seine alten Listen, die niemand mehr zeigt.
      * Gemeinsame Felder nur, solange `chat["generation"]` noch die eigene
        ist (`_setzen`, `_stand`).

    Dieselbe Regel gilt fuer den Claude-Code-Leser in omcad_a_chat.
    """

    generation = None

    def _binden(self, generation, ereignisse, freigaben):
        self.generation = generation
        self.ereignisse, self.freigaben = ereignisse, freigaben

    def _aktuell(self):
        return self.chat.get("generation") == self.generation

    def _setzen(self, **felder):
        """Gemeinsame Felder — nur, solange dies der aktuelle Chat ist."""
        if self._aktuell():
            self.chat.update(felder)

    def _stand(self):
        if self._aktuell():
            self.chat["stand"] = self.chat.get("stand", 0) + 1


# --- Die Schleife ----------------------------------------------------------

class Schleife(_Gespraech):
    """Ein Gespraech: Nachrichten rein, Modell rufen, Werkzeuge ausfuehren.

    Genau EIN Arbeitsthread. `chat` ist dasselbe Dict, das das Dashboard
    zeichnet; hier wird nur angehaengt und zugewiesen.
    """

    def __init__(self, chat, a, basis, modell, schluessel, server,
                 erlauben, dokument=None, port=None):
        self.chat, self.a, self.basis = chat, a, _basis(a, basis)
        self.modell, self.schluessel = modell, schluessel
        self.server = server            # (befehl, umgebung) oder None
        self.erlauben = erlauben
        self.dokument, self.port = dokument, port
        self.aus = False
        self.eingang = queue.Queue()
        self.mcp = None
        self.werkzeuge = {}
        self.verlauf = []
        self.ereignisse, self.freigaben = _Verlauf(), []
        self.thread = threading.Thread(target=self._arbeiten, daemon=True,
                                       name="Open-MCP-CAD-Schleife")

    # -- vom Dashboard (Qt-Thread) gerufen: nur einreihen, nie warten --------
    def senden(self, text, anhaenge=None):
        self.ereignisse.append(_ich(text, anhaenge))
        self._setzen(laeuft_zug=True)
        self._stand()
        self.eingang.put((text, list(anhaenge or ())))
        return True

    def freigabe_beantworten(self, kennung, erlauben, grund=""):
        for f in self.freigaben:
            if f["id"] == kennung and f["offen"]:
                f["offen"] = False
                f["antwort"] = "erlaubt" if erlauben else "abgelehnt"
                f["grund"] = grund
                f["_ereignis"].set()
                self._stand()
                return True
        return False

    def laeuft_noch(self):
        """Lebt noch ein Prozess dieses Gespraechs (der MCP-Server)?

        Ein Arbeitsthread, der noch auf eine HTTP-Antwort wartet (bis zu
        HTTP_TIMEOUT), zaehlt NICHT: er ist abgeloest und fasst den neuen
        Chat nicht an. Sonst koennte man nach einem Beenden minutenlang
        keinen neuen Chat starten.
        """
        mcp = self.mcp
        return mcp is not None and mcp.proc.poll() is None

    def beenden(self):
        """Offene Freigaben gelten als ABGELEHNT — nie als erlaubt.

        Nur die EIGENEN: ein spaetes beenden() eines abgeloesten Gespraechs
        lehnte frueher die Karten des neuen Chats ab.
        """
        self.aus = True
        for f in self.freigaben:
            if f.get("offen"):
                f["offen"] = False
                f["antwort"] = "abgelehnt"
                f["_ereignis"].set()
        self.eingang.put(None)
        if self.mcp is not None:
            self.mcp.beenden()
        self._setzen(an=False, laeuft_zug=False)
        self._stand()

    # -- Arbeitsthread ---------------------------------------------------------
    def _arbeiten(self):
        try:
            self._server_starten()
            system = systemtext(self.dokument, self.port)
            if self.mcp is not None and self.mcp.anleitung:
                system += "\n\n" + self.mcp.anleitung
            self.verlauf.append({"role": "system", "content": system})
            while not self.aus:
                eintrag = self.eingang.get()
                if eintrag is None or self.aus:
                    break
                self._zug(*eintrag)
        except Exception as exc:                        # noqa: BLE001
            self._setzen(fehler=str(exc))
        finally:
            if self.mcp is not None:
                self.mcp.beenden()
            # Nur fuer SEINEN Chat: laeuft schon ein neuer, bleibt der an.
            self._setzen(an=False, laeuft_zug=False, denkt=False)
            self._stand()

    def _server_starten(self):
        if not self.server:
            self._setzen(werkzeuge_da=False)       # kein Server: fehlt
            return
        befehl, umgebung = self.server
        try:
            self.mcp = McpKlient(befehl, umgebung)
            if self.aus:
                # beenden() kam, bevor der Server hier eingetragen war —
                # es konnte ihn nicht sehen. Dann eben hier.
                self.mcp.beenden()
            for w in self.mcp.starten():
                self.werkzeuge[w["name"]] = w
            self._setzen(werkzeuge_da=bool(self.werkzeuge))
        except AnbieterFehler as exc:
            # Ohne Server kann das Modell reden, aber Cadwork nicht
            # bedienen — sichtbar sagen, nicht still weitermachen.
            self._setzen(werkzeuge_da=False)
            self.ereignisse.append({
                "art": "text", "text": "⚠ Cadwork-Werkzeuge nicht verfügbar: %s"
                % exc})
            if self.mcp is not None:
                self.mcp.beenden()
            self.mcp = None
        self._stand()

    def _zug(self, text, anhaenge=()):
        # Bilder als `image_url` mit Data-URL (OpenAI-kompatibel; gegen die
        # Attrappe gemessen, an den echten Diensten NICHT).
        if anhaenge:
            inhalt = [{"type": "text", "text": _mit_anhaengen(text, anhaenge)
                       or " "}]
            inhalt += [{"type": "image_url",
                        "image_url": {"url": _data_url(a)}}
                       for a in _bilder(anhaenge)]
        else:
            inhalt = text
        nutzer = {"role": "user", "content": inhalt}
        self.verlauf.append(nutzer)
        bilder = bool(_bilder(anhaenge))
        abgelehnt, token, fehler = 0, 0, False
        try:
            for _runde in range(MAX_RUNDEN):
                if self.aus:
                    return
                daten = {"model": self.modell, "messages": self.verlauf}
                if self.werkzeuge:
                    daten["tools"] = [_als_funktion(w)
                                      for w in self.werkzeuge.values()]
                self._setzen(denkt=True)
                self._stand()
                antwort = _http(self.basis + "/chat/completions",
                                _kopf(self.a, self.schluessel), daten)
                self._setzen(denkt=False)
                if self.aus:
                    return      # beendet, waehrend das Modell rechnete
                token += int(((antwort.get("usage") or {})
                              .get("total_tokens")) or 0)
                # Kontext (S10): was die LETZTE Runde mitnahm, Frage plus
                # Antwort. Wie viel das Modell hoechstens fasst, meldet
                # eine OpenAI-kompatible Antwort nicht — `fenster` bleibt
                # leer, das Dock zeigt dann nur die Zahl.
                belegt = _runde_belegt(antwort.get("usage"))
                if belegt:
                    self._setzen(kontext={"belegt": belegt, "fenster": None})
                wahl = (antwort.get("choices") or [{}])[0]
                nachricht = wahl.get("message") or {}
                aufrufe = nachricht.get("tool_calls") or []
                inhalt = nachricht.get("content")
                if isinstance(inhalt, list):            # manche liefern Bloecke
                    inhalt = "".join(b.get("text", "") for b in inhalt
                                     if isinstance(b, dict))
                eintrag = {"role": "assistant", "content": inhalt or ""}
                if aufrufe:
                    eintrag["tool_calls"] = aufrufe
                self.verlauf.append(eintrag)
                if inhalt and inhalt.strip():
                    self.ereignisse.append({"art": "text",
                                            "text": inhalt.strip()})
                    self._stand()
                if not aufrufe:
                    return
                for aufruf in aufrufe:
                    ergebnis, nein = self._werkzeug(aufruf)
                    abgelehnt += nein
                    self.verlauf.append({"role": "tool",
                                         "tool_call_id": aufruf.get("id"),
                                         "content": ergebnis})
            self.ereignisse.append({
                "art": "text", "text": "⚠ nach %d Runden abgebrochen — das "
                "Modell kam nicht zum Ende." % MAX_RUNDEN})
        except Exception as exc:                        # noqa: BLE001
            # Auch Unerwartetes (eine Antwort in fremder Form) beendet nur
            # DIESEN Zug, nicht das Gespraech — die naechste Nachricht geht.
            fehler = True
            self.ereignisse.append({"art": "text", "text": "⚠ %s" % (
                exc if isinstance(exc, AnbieterFehler)
                else "%s: %s" % (type(exc).__name__, exc))})
            if bilder:
                # Die Bilder bleiben sonst im Verlauf und gehen mit JEDER
                # weiteren Anfrage mit — nimmt das Modell keine Bilder (viele
                # lokale), scheiterte danach jede Nachricht (Gegenpruefung
                # 2026-09-28). Also heraus, mit einem Satz fuer Modell und
                # Nutzer.
                nutzer["content"] = _ohne_bilder(nutzer["content"])
                self.ereignisse.append({"art": "text", "text": BILD_HINWEIS})
        finally:
            self.ereignisse.append({
                "art": "schluss", "kosten": None, "token": token or None,
                "abgelehnt": abgelehnt, "fehler": fehler, "text": ""})
            self._setzen(denkt=False, laeuft_zug=False)
            self._stand()

    def _werkzeug(self, aufruf):
        """-> (Text fuer das Modell, 1 wenn abgelehnt sonst 0)."""
        f = aufruf.get("function") or {}
        name = f.get("name") or ""
        voll = MCP_PRAEFIX + name
        try:
            argumente = json.loads(f.get("arguments") or "{}")
            if not isinstance(argumente, dict):
                raise ValueError("kein Objekt")
        except ValueError as exc:
            return "Ungueltige Argumente (%s) — bitte gueltiges JSON." % exc, 0
        kennung = aufruf.get("id") or "f%d" % time.monotonic_ns()
        self.ereignisse.append({"art": "werkzeug", "werkzeug": voll,
                                "eingabe": argumente, "id": kennung})
        self._stand()
        if self.mcp is None or name not in self.werkzeuge:
            self.ereignisse.append({"art": "ergebnis", "id": kennung,
                                    "fehler": True})
            return "Unbekanntes Werkzeug: %s" % name, 0
        if self.aus:
            # Beendet: nichts mehr erlauben, auch nicht automatisch.
            return "Chat beendet — nicht ausgefuehrt.", 1

        # Der Modus wird bei JEDEM Aufruf neu gelesen (in der Entscheidung).
        urteil = _urteil(self.erlauben, self.chat, voll)
        if urteil == "ja":
            self.ereignisse.append({"art": "auto", "werkzeug": voll,
                                    "eingabe": argumente})
            self._stand()
        elif urteil == "nein":
            self.ereignisse.append({"art": "verweigert", "werkzeug": voll,
                                    "eingabe": argumente, "id": kennung,
                                    "modus": self.chat.get("modus")})
            self._stand()
            return ablehnung(self.chat, name), 1
        else:
            eintrag = {"id": kennung,
                       "werkzeug": voll, "name": name, "eingabe": argumente,
                       "beschreibung": "", "zeit": time.time(), "offen": True,
                       "_ereignis": threading.Event()}
            self.freigaben.append(eintrag)
            self._stand()
            # Warten im ARBEITSthread, nie im Qt-Takt. Keine Frist: eine
            # Karte, die niemand beantwortet, bleibt stehen — sie laeuft
            # nicht ab und wird schon gar nicht still erlaubt.
            # Kam beenden() dazwischen, hat es diese Karte womoeglich nicht
            # mehr gesehen (es setzt `aus` VOR dem Durchgehen der Karten) —
            # dann nicht warten, sondern ablehnen.
            if not self.aus:
                eintrag["_ereignis"].wait()
            if self.aus or eintrag.get("antwort") != "erlaubt":
                if eintrag.get("offen"):
                    eintrag["offen"] = False
                    eintrag["antwort"] = "abgelehnt"
                return ("Vom Nutzer abgelehnt%s. Nicht erneut versuchen, "
                        "sondern nachfragen." % (
                            (": " + eintrag["grund"]) if eintrag.get("grund")
                            else "")), 1
        try:
            text, ist_fehler = self.mcp.werkzeug(name, argumente)
        except AnbieterFehler as exc:
            self.ereignisse.append({"art": "ergebnis", "id": kennung,
                                    "fehler": True})
            self._stand()
            return "Werkzeugfehler: %s" % exc, 0
        self.ereignisse.append({"art": "ergebnis", "id": kennung,
                                "fehler": bool(ist_fehler)})
        self._stand()
        return ("FEHLER: " + text) if ist_fehler else text, 0


class VorigerChatLaeuft(AnbieterFehler):
    """starten(), waehrend vom vorigen Chat noch ein Prozess lebt."""


VORIGER_CHAT = "Der vorige Chat endet noch — gleich nochmal versuchen"


def _voriger_laeuft(chat):
    """Dieselbe Regel wie `omcad_a_chat.voriger_laeuft` (dieses Modul
    importiert das Chat-Modul nicht): der Chat ist an, das Claude-CLI lebt
    noch, oder ein Prozess des vorigen Gespraechs (MCP-Server, Codex)."""
    if chat.get("an"):
        return True
    proc = chat.get("proc")
    if proc is not None and proc.poll() is None:
        return True
    laeuft_noch = getattr(chat.get("schleife"), "laeuft_noch", None)
    return bool(laeuft_noch and laeuft_noch())


def starten(chat, kennung, modell, erlauben, basis=None, schluessel=None,
            server=None, dokument=None, port=None, codex_befehl=None):
    """Ein Gespraech ueber einen OpenAI-kompatiblen Dienst beginnen.

    Kehrt sofort zurueck: der MCP-Server startet im Arbeitsthread. Fehlt
    Pflichtiges (Adresse, Schluessel, Modell), bricht es HIER ab — laut,
    bevor irgendetwas laeuft. Ebenso, wenn vom vorigen Chat noch etwas
    lebt (`VorigerChatLaeuft`) — bis 2026-09-25 kehrte es dann still zurueck.
    """
    a = anbieter(kennung)
    if a["art"] not in ("openai", "codex"):
        raise AnbieterFehler("%s laeuft nicht ueber diese Schleife" % a["name"])
    if _voriger_laeuft(chat):
        raise VorigerChatLaeuft(VORIGER_CHAT)
    modell = (modell or "").strip()
    if a["art"] == "codex":
        # Leer heisst hier: das Standardmodell des Codex-Kontos.
        schleife = CodexSitzung(chat, modell or None, server, erlauben,
                                dokument, port, befehl=codex_befehl)
    else:
        if not modell:
            raise AnbieterFehler("kein Modell gewaehlt — 'Modelle laden' oder "
                                 "den Namen eintippen")
        if schluessel is None:
            schluessel, herkunft = schluessel_fuer(a)
            if schluessel is None and a.get("schluessel") == "pflicht":
                raise AnbieterFehler("%s: %s. Unter Einstellungen (⚙) "
                                     "speichern (Windows-Tresor) oder %s "
                                     "setzen." % (a["name"], herkunft,
                                                  a.get("env")))
        schleife = Schleife(chat, a, basis, modell, schluessel, server,
                            erlauben, dokument, port)
    # Neue Generation, eigene Listen: was das vorige Gespraech noch
    # nachschiebt, landet in SEINEN Listen, nicht in diesen (_Gespraech).
    # Ein `beenden_nach_zug` des vorigen Chats gilt nicht fuer diesen.
    generation = chat.get("generation", 0) + 1
    ereignisse, freigaben = _Verlauf(), []
    schleife._binden(generation, ereignisse, freigaben)
    chat.update(generation=generation, ereignisse=ereignisse,
                freigaben=freigaben, an=True, laeuft_zug=False,
                denkt=False, laufender_text="", fehler=None, sitzung=None,
                modell="%s · %s" % (a["name"].split(" (")[0],
                                    modell or "Standardmodell"),
                # None = noch unbekannt (Server startet); False erst, wenn er
                # fehlt — sonst meldete die Statuszeile ihn bei jedem Start
                # kurz als fehlend (Feinschliff 2026-09-28).
                werkzeuge_da=None, schleife=schleife, stderr=[],
                beenden_nach_zug=False, kontext=None,
                # Freigaben je Art (Modus "fragen") gelten nur fuer DIESEN
                # Chat (omcad_a_chat: `gewaehren`, `senden`).
                gewaehrt_zug=set(), gewaehrt_sitzung=set())
    chat["stand"] = chat.get("stand", 0) + 1
    schleife.thread.start()
    return chat


# --- Codex (ChatGPT-Abo) ueber den App-Server -----------------------------
#
# Codex ist ein eigener Agent wie Claude Code — mit eigenen Werkzeugen
# (Shell, Dateiaenderungen, Browser, Plugins) und der Anmeldung aus
# ~/.codex. Angebunden wird er ueber `codex app-server` (JSON-RPC ueber
# stdio), denselben Weg wie die Codex-App. Gemessen 2026-09-24 mit
# codex-cli 0.156.1:
#
# * Ein MCP-Aufruf kommt bei approvalPolicy "on-request" VOR der
#   Ausfuehrung als `mcpServer/elicitation/request` zu uns
#   (`_meta.codex_approval_kind = "mcp_tool_call"`). Abgelehnt, wurde der
#   Server nie gerufen ("user rejected MCP tool call").
# * Ohne Gegenmassnahme startet eine Sitzung ALLE MCP-Server aus der
#   config.toml des Nutzers — dort standen vier weitere auf echten
#   Cadwork-Ports. `mcp_servers.<name>.enabled = false` je Server plus die
#   Features unten liessen nur `open-mcp-cad` starten; `shell_tool = false`
#   nimmt Codex die Shell. Die config.toml selbst bleibt unberuehrt.

CODEX_SERVERNAME = "open-mcp-cad"
CODEX_AUS = ("apps", "computer_use", "browser_use", "in_app_browser",
             "plugins", "shell_tool", "image_generation")


def codex_kandidaten():
    """Wo die Codex-CLI liegen kann, in der Reihenfolge, in der gesucht wird.

    Seit 2026-10-09 auch der Installer, den OpenAI fuer Windows nennt
    (`irm https://chatgpt.com/codex/install.ps1 | iex`, ohne Node, ohne
    Adminrechte, learn.chatgpt.com/docs/codex/cli): sein Skript legt
    `codex.exe` nach `%LOCALAPPDATA%\\Programs\\OpenAI\\Codex\\bin`
    (`CODEX_INSTALL_DIR` aendert das). Vorher fand der Chat nur `codex.cmd`
    von npm. Reihenfolge wie bei Claude Code (`cli_kandidaten` im Chat):
    feste Orte vor dem PATH, der eigene Installer vor npm. Die ChatGPT-App
    aus dem Store taugt nicht: ihr codex.exe liegt unter WindowsApps und
    laesst sich von aussen nicht starten ("Zugriff verweigert", gemessen
    2026-09-24) - ein Treffer dort zaehlt nie. DIESELBE Reihenfolge hat
    `Cli-Pfad codex` in verteilung/install.ps1 (test_installer I28).
    """
    lokal = os.environ.get("LOCALAPPDATA", "")
    eigen = os.environ.get("CODEX_INSTALL_DIR", "")
    aus = []
    if eigen:
        aus.append(("datei", os.path.join(eigen, "codex.exe")))
    if lokal:
        aus.append(("datei", os.path.join(lokal, "Programs", "OpenAI",
                                          "Codex", "bin", "codex.exe")))
    aus += [("datei", os.path.join(os.environ.get("APPDATA", ""), "npm",
                                   "codex.cmd")),
            ("path", "codex.exe"), ("path", "codex.cmd")]
    return aus


def codex_pfad():
    """Der volle Pfad auf die Codex-CLI (`codex.exe` des Installers von
    OpenAI oder `codex.cmd` von npm, s. `codex_kandidaten`)."""
    for art, wert in codex_kandidaten():
        if art == "datei":
            gefunden = wert if os.path.isabs(wert) and os.path.isfile(wert) \
                else None
        else:
            gefunden = shutil.which(wert)
        if gefunden and "\\windowsapps\\" not in gefunden.lower():
            return gefunden
    raise AnbieterFehler("Codex-CLI ist nicht installiert (in PowerShell: "
                         "irm https://chatgpt.com/codex/install.ps1 | iex, "
                         "oder npm i -g @openai/codex). Die ChatGPT-App "
                         "allein genuegt nicht.")


def codex_fremde_server():
    """Die MCP-Server aus der config.toml des Nutzers — sie werden je
    Sitzung abgeschaltet. Nicht lesbar = kein Start: ohne diese Liste
    liefe die Sitzung mit allem, was dort steht."""
    heim = os.environ.get("CODEX_HOME") or os.path.join(
        os.path.expanduser("~"), ".codex")
    pfad = os.path.join(heim, "config.toml")
    if not os.path.isfile(pfad):
        return []
    try:
        with open(pfad, "rb") as fh:
            daten = tomllib.load(fh)
    except (OSError, ValueError) as exc:
        raise AnbieterFehler("Codex-Konfiguration nicht lesbar (%s): %s"
                             % (pfad, exc))
    return sorted(n for n in (daten.get("mcp_servers") or {})
                  if n != CODEX_SERVERNAME)


def codex_konfig(server):
    """Die Konfiguration EINER Dock-Sitzung: nur unser Server."""
    mcp = {n: {"enabled": False} for n in codex_fremde_server()}
    if server:
        befehl, umgebung = server
        mcp[CODEX_SERVERNAME] = {"command": befehl[0], "args": befehl[1:],
                                 "env": dict(umgebung or {})}
    return {"mcp_servers": mcp, "features": {f: False for f in CODEX_AUS}}


class _RpcKanal:
    """JSON-RPC ueber stdio zum Codex-App-Server.

    EIN Leserthread. Antworten auf eigene Anfragen landen in `_antworten`;
    Anfragen des Servers und Benachrichtigungen gehen an `bearbeiter` —
    der darf nie blockieren, sonst steht der ganze Kanal.
    """

    def __init__(self, befehl, bearbeiter, cwd=None):
        try:
            self.proc = subprocess.Popen(
                befehl, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, cwd=cwd,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError as exc:
            raise AnbieterFehler("Codex startet nicht: %s" % exc)
        self.bearbeiter = bearbeiter
        self.schloss = threading.Lock()
        self._naechste = 0
        self._antworten = {}
        self._warten = {}
        self.stderr = []
        self.zu = threading.Event()
        threading.Thread(target=self._lesen, daemon=True,
                         name="Open-MCP-CAD-Codex").start()
        threading.Thread(target=self._fehler_lesen, daemon=True,
                         name="Open-MCP-CAD-Codex-Fehler").start()

    def _lesen(self):
        try:
            for zeile in self.proc.stdout:
                try:
                    m = json.loads(zeile)
                except ValueError:
                    continue
                if "id" in m and "method" not in m:
                    self._antworten[m["id"]] = m
                    ereignis = self._warten.get(m["id"])
                    if ereignis is not None:
                        ereignis.set()
                else:
                    try:
                        self.bearbeiter(m)
                    except Exception:                   # noqa: BLE001
                        pass
        finally:
            self.zu.set()
            for ereignis in list(self._warten.values()):
                ereignis.set()

    def _fehler_lesen(self):
        try:
            for zeile in self.proc.stderr:
                self.stderr.append(zeile.rstrip())
                del self.stderr[:-40]
        except Exception:                               # noqa: BLE001
            pass

    def schicken(self, obj):
        with self.schloss:
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def rufen(self, methode, params, timeout=60):
        with self.schloss:
            self._naechste += 1
            kennung = self._naechste
            self._warten[kennung] = threading.Event()
        if not self.schicken({"id": kennung, "method": methode,
                              "params": params}):
            raise AnbieterFehler("Codex nimmt nichts an%s" % self._stoerung())
        self._warten[kennung].wait(timeout)
        antwort = self._antworten.pop(kennung, None)
        self._warten.pop(kennung, None)
        if antwort is None:
            raise AnbieterFehler("Codex antwortet nicht auf %s%s"
                                 % (methode, self._stoerung()))
        if antwort.get("error"):
            raise AnbieterFehler("Codex %s: %s" % (
                methode, (antwort["error"] or {}).get("message")))
        return antwort.get("result") or {}

    def _stoerung(self):
        zeilen = [z for z in self.stderr if z.strip()]
        return (" — " + zeilen[-1][:200]) if zeilen else ""

    def beenden(self):
        try:
            self.proc.stdin.close()
        except Exception:                               # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:                               # noqa: BLE001
            # codex.cmd ist eine Huelle um Node um codex.exe — /T nimmt
            # den ganzen Baum mit (wie beim Claude-CLI).
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID",
                                str(self.proc.pid)], capture_output=True,
                               timeout=10, creationflags=CREATE_NO_WINDOW)
            except Exception:                           # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:                       # noqa: BLE001
                    pass


def _codex_start(bearbeiter, cwd=None, befehl=None, merken=None):
    """`merken(kanal)` bekommt den Kanal VOR dem Handshake — so erreicht ein
    beenden() den Prozess auch, waehrend Codex noch hochfaehrt."""
    kanal = _RpcKanal(befehl or [codex_pfad(), "app-server"], bearbeiter, cwd)
    if merken is not None:
        merken(kanal)
    kanal.rufen("initialize", {"clientInfo": {"name": "open-mcp-cad",
                                              "title": "Open MCP CAD",
                                              "version": "2"}})
    kanal.schicken({"method": "initialized"})
    return kanal


def codex_modelle(timeout=60, befehl=None):
    """Die Modelle des Codex-Kontos (`model/list`), ohne versteckte."""
    kanal = _codex_start(lambda m: None, befehl=befehl)
    try:
        namen, zeiger = [], None
        while True:
            erg = kanal.rufen("model/list", {"cursor": zeiger} if zeiger else {},
                              timeout=timeout)
            for m in erg.get("data") or []:
                if not m.get("hidden"):
                    namen.append(m.get("model") or m.get("id"))
            zeiger = erg.get("nextCursor")
            if not zeiger:
                return [n for n in namen if n]
    finally:
        kanal.beenden()


_WERKZEUG_IN_FRAGE = re.compile(r'run tool "([^"]+)"')


class CodexSitzung(_Gespraech):
    """Ein Gespraech mit Codex — dieselbe Schnittstelle wie `Schleife`."""

    def __init__(self, chat, modell, server, erlauben, dokument=None,
                 port=None, befehl=None, cwd=None):
        self.chat, self.modell, self.server = chat, modell, server
        self.erlauben = erlauben
        self.dokument, self.port = dokument, port
        self.befehl, self.cwd = befehl, cwd
        self.aus = False
        self.kanal = None
        self.faden = None
        self.eingang = queue.Queue()
        self.zug_fertig = threading.Event()
        self.token_gesamt = 0
        self.token_start = 0
        self.abgelehnt = 0
        self.letztes_werkzeug = None
        self.ereignisse, self.freigaben = _Verlauf(), []
        self.thread = threading.Thread(target=self._arbeiten, daemon=True,
                                       name="Open-MCP-CAD-Codex-Sitzung")

    # -- vom Dashboard (Qt-Thread) --------------------------------------------
    def senden(self, text, anhaenge=None):
        self.ereignisse.append(_ich(text, anhaenge))
        self._setzen(laeuft_zug=True)
        self._stand()
        self.eingang.put((text, list(anhaenge or ())))
        return True

    def laeuft_noch(self):
        """Lebt der Codex-App-Server dieses Gespraechs noch?"""
        kanal = self.kanal
        return kanal is not None and kanal.proc.poll() is None

    def freigabe_beantworten(self, kennung, erlauben, grund=""):
        for f in self.freigaben:
            if f["id"] == kennung and f["offen"]:
                f["offen"] = False
                f["antwort"] = "erlaubt" if erlauben else "abgelehnt"
                if not erlauben:
                    self.abgelehnt += 1
                # NIE `persist`: jede Freigabe gilt genau fuer diesen Aufruf.
                self._antworten(f["rpc_id"], {"action": "accept", "content": {}}
                                if erlauben else {"action": "decline"})
                self._stand()
                return True
        return False

    def beenden(self):
        """Offene Freigaben: decline — nur die EIGENEN (siehe _Gespraech)."""
        self.aus = True
        for f in self.freigaben:
            if f.get("offen"):
                f["offen"] = False
                f["antwort"] = "abgelehnt"
                self._antworten(f["rpc_id"], {"action": "decline"})
        self.eingang.put(None)
        self.zug_fertig.set()
        if self.kanal is not None:
            self.kanal.beenden()
        self._setzen(an=False, laeuft_zug=False)
        self._stand()

    # -- intern ------------------------------------------------------------
    def _text(self, text):
        self.ereignisse.append({"art": "text", "text": text})
        self._stand()

    def _antworten(self, rpc_id, ergebnis):
        if self.kanal is not None:
            self.kanal.schicken({"id": rpc_id, "result": ergebnis})

    def _kanal_merken(self, kanal):
        self.kanal = kanal
        if self.aus:
            # beenden() kam, bevor der Kanal hier stand — es konnte ihn
            # nicht sehen. Dann eben hier (der Handshake scheitert danach).
            kanal.beenden()

    def _arbeiten(self):
        try:
            cwd = self.cwd or os.path.join(
                os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                "OpenMcpCad", "codex")
            os.makedirs(cwd, exist_ok=True)
            self.kanal = _codex_start(self._bearbeiten, cwd, self.befehl,
                                      merken=self._kanal_merken)
            if self.aus:
                return
            params = {
                "cwd": cwd, "ephemeral": True, "sandbox": "read-only",
                "approvalPolicy": "on-request", "approvalsReviewer": "user",
                "config": codex_konfig(self.server),
                "developerInstructions": systemtext(self.dokument, self.port)}
            if self.modell:
                params["model"] = self.modell
            erg = self.kanal.rufen("thread/start", params)
            self.faden = (erg.get("thread") or {}).get("id")
            if not self.server:
                self._text("⚠ Cadwork-Werkzeuge nicht verfügbar: kein "
                           "Server-Python mit open_mcp_cad gefunden")
            while not self.aus:
                eintrag = self.eingang.get()
                if eintrag is None or self.aus:
                    break
                text, anhaenge = eintrag
                self.zug_fertig.clear()
                self.token_start, self.abgelehnt = self.token_gesamt, 0
                # Bilder als `{"type": "image", "url": Data-URL}` — laut dem
                # Schema von codex-cli 0.156.1 (`codex app-server
                # generate-json-schema`, UserInput); an einem laufenden
                # Codex NICHT gemessen.
                eingabe = [{"type": "text",
                            "text": _mit_anhaengen(text, anhaenge) or " "}]
                eingabe += [{"type": "image", "url": _data_url(a)}
                            for a in _bilder(anhaenge)]
                self.kanal.rufen("turn/start", {
                    "threadId": self.faden, "input": eingabe})
                while not self.zug_fertig.wait(0.5):
                    if self.kanal.zu.is_set():
                        raise AnbieterFehler("Codex beendet%s"
                                             % self.kanal._stoerung())
        except Exception as exc:                        # noqa: BLE001
            if not self.aus:
                self._setzen(fehler=str(exc))
                self._text("⚠ %s" % exc)
        finally:
            if self.kanal is not None:
                self.kanal.beenden()
            # Nur fuer SEINEN Chat: laeuft schon ein neuer, bleibt der an.
            self._setzen(an=False, laeuft_zug=False, denkt=False)
            self._stand()

    def _bearbeiten(self, m):
        """Leserthread: einsortieren, nie warten.

        Gemeinsame Felder nur ueber `_setzen` — ein Nachzuegler eines
        abgeloesten Codex-Prozesses aendert am neuen Chat nichts.
        """
        methode, p = m.get("method"), m.get("params") or {}
        if "id" in m:
            return self._anfrage(m["id"], methode, p)
        item = p.get("item") or {}
        art = item.get("type")
        if methode == "item/agentMessage/delta":
            self._setzen(denkt=False, laufender_text=(
                (self.chat.get("laufender_text") or "")
                + (p.get("delta") or "")))
        elif methode == "item/started" and art == "reasoning":
            self._setzen(denkt=True)
        elif methode == "item/started" and art == "agentMessage":
            self._setzen(laufender_text="")
        elif methode == "item/started" and art == "mcpToolCall":
            self.letztes_werkzeug = item.get("tool")
            self.ereignisse.append({
                "art": "werkzeug",
                "werkzeug": "mcp__%s__%s" % (item.get("server"), item.get("tool")),
                "eingabe": item.get("arguments") or {}, "id": item.get("id")})
        elif methode == "item/completed" and art == "agentMessage":
            self._setzen(laufender_text="")
            if (item.get("text") or "").strip():
                self.ereignisse.append({"art": "text",
                                        "text": item["text"].strip()})
        elif methode == "item/completed" and art == "reasoning":
            self._setzen(denkt=False)
        elif methode == "item/completed" and art == "mcpToolCall":
            fehler = (item.get("error") or {}).get("message") or ""
            self.ereignisse.append({"art": "ergebnis", "id": item.get("id"),
                                    "fehler": item.get("status") == "failed"})
            if item.get("status") == "failed" and "rejected" not in fehler:
                self.ereignisse.append({
                    "art": "text", "text": "⚠ Werkzeugfehler: %s" % fehler[:300]})
        elif methode == "thread/tokenUsage/updated":
            nutzung = p.get("tokenUsage") or {}
            gesamt = nutzung.get("total") or {}
            self.token_gesamt = int(gesamt.get("totalTokens") or 0)
            # Kontext (S10): die letzte Anfrage gegen das Fenster des
            # Modells. Feldnamen aus codex-cli 0.156.1 (ThreadTokenUsage:
            # total, last, modelContextWindow; TokenUsageBreakdown:
            # totalTokens …) — aus dem Programm gelesen, NICHT an einem
            # laufenden Codex gemessen.
            kontext = _codex_kontext(nutzung)
            if kontext:
                self._setzen(kontext=kontext)
        elif methode == "mcpServer/startupStatus/updated" \
                and p.get("name") == CODEX_SERVERNAME:
            if p.get("status") == "ready":
                self._setzen(werkzeuge_da=True)
            elif p.get("status") == "failed":
                self._text("⚠ Cadwork-Werkzeuge nicht verfügbar: %s"
                           % (p.get("error") or "Server startet nicht")[:300])
        elif methode == "error" and not p.get("willRetry"):
            self._text("⚠ %s" % ((p.get("error") or {}).get("message")
                                  or "Codex-Fehler"))
        elif methode == "turn/completed":
            zug = p.get("turn") or {}
            if zug.get("status") == "failed" and zug.get("error"):
                self._text("⚠ %s" % (zug["error"].get("message") or "Zug fehlgeschlagen"))
            self.ereignisse.append({
                "art": "schluss", "kosten": None,
                "token": (self.token_gesamt - self.token_start) or None,
                "abgelehnt": self.abgelehnt,
                "fehler": zug.get("status") == "failed", "text": ""})
            self._setzen(laeuft_zug=False, denkt=False, laufender_text="")
            self.zug_fertig.set()
        self._stand()

    def _anfrage(self, rpc_id, methode, p):
        """Eine Frage von Codex. Unbekanntes wird ABGELEHNT, nie erlaubt."""
        meta = p.get("_meta") or {}
        if (methode == "mcpServer/elicitation/request"
                and meta.get("codex_approval_kind") == "mcp_tool_call"
                and p.get("serverName") == CODEX_SERVERNAME):
            treffer = _WERKZEUG_IN_FRAGE.search(p.get("message") or "")
            name = treffer.group(1) if treffer else (self.letztes_werkzeug or "?")
            voll = MCP_PRAEFIX + name
            eingabe = meta.get("tool_params") or {}
            # Nennt die Frage ihr Werkzeug nicht, ist `name` nur geraten
            # (das zuletzt gestartete). Entschieden wird dann wie fuer ein
            # UNBEKANNTES Werkzeug — nie ohne Karte, weil das geratene ein
            # lesendes war (Gegenpruefung 2026-09-28: "Nur lesen" liess so
            # jedes Werkzeug durch, sobald vorher get_document_info lief).
            urteil = ("nein" if self.aus
                      else _urteil(self.erlauben, self.chat,
                                   voll if treffer else MCP_PRAEFIX + "?"))
            if self.aus:
                # Beendet: nichts mehr erlauben, auch nicht automatisch.
                self._antworten(rpc_id, {"action": "decline"})
            elif urteil == "ja":
                self.ereignisse.append({"art": "auto", "werkzeug": voll,
                                        "eingabe": eingabe})
                self._antworten(rpc_id, {"action": "accept", "content": {}})
            elif urteil == "nein":
                # Ohne Frage abgelehnt (Modus "Nur lesen"). NIE `persist`.
                self.abgelehnt += 1
                self.ereignisse.append({"art": "verweigert", "werkzeug": voll,
                                        "eingabe": eingabe,
                                        "modus": self.chat.get("modus")})
                self._antworten(rpc_id, {"action": "decline"})
            else:
                karte = {
                    "id": "codex-%s" % rpc_id, "rpc_id": rpc_id,
                    "werkzeug": voll, "name": name, "eingabe": eingabe,
                    "beschreibung": meta.get("tool_description") or "",
                    "zeit": time.time(), "offen": True}
                self.freigaben.append(karte)
                # beenden() setzt `aus` VOR dem Durchgehen der Karten — kam
                # es dazwischen, hat es diese hier nicht mehr gesehen.
                if self.aus and karte["offen"]:
                    karte["offen"] = False
                    karte["antwort"] = "abgelehnt"
                    self._antworten(rpc_id, {"action": "decline"})
            self._stand()
            return
        # Alles andere — Shell, Dateiaenderungen, fremde Server, Rechte —
        # sollte es mit dieser Konfiguration gar nicht geben. Kommt es doch,
        # wird es sichtbar abgelehnt.
        self.abgelehnt += 1
        self._text("⚠ Codex wollte %s — abgelehnt (im Dock nicht vorgesehen)"
                   % (methode or "?"))
        if methode == "mcpServer/elicitation/request":
            self._antworten(rpc_id, {"action": "decline"})
        elif methode in ("item/commandExecution/requestApproval",
                         "item/fileChange/requestApproval"):
            self._antworten(rpc_id, {"decision": "decline"})
        elif methode in ("execCommandApproval", "applyPatchApproval"):
            self._antworten(rpc_id, {"decision": "denied"})
        elif self.kanal is not None:
            self.kanal.schicken({"id": rpc_id, "error": {
                "code": -32601, "message": "im Open-MCP-CAD-Dock nicht vorgesehen"}})
