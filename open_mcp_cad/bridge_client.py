"""TCP-Client zur Cadwork-Bridge (Open MCP CAD).

Stellt eine kurzlebige Verbindung zur Bridge in Cadwork her, sendet einen
JSON-Lines-Request und liefert die Antwort als dict zurück. Der Client
hält keine persistente Verbindung — jede Anfrage öffnet einen neuen Socket.
Das ist robuster (Cadwork-Plugin kann unabhängig neu gestartet werden) und
für die hier zu erwartenden Aufrufraten mehr als ausreichend.

Neu seit Protokoll 2 (2026-08-04), alles rückwärtskompatibel:

  * Jeder Aufruf trägt automatisch `client_id` und `client_label`. Damit
    kann die Bridge eine Schreiblizenz führen und verhindern, dass zwei
    Sitzungen gleichzeitig dieselbe Datei verändern.
  * Beim Prozessende wird eine gehaltene Schreiblizenz freigegeben, damit
    das nächste Skript nicht auf den Ablauf warten muss.
  * Verbindungsaufbau und Antwort haben getrennte Zeitgrenzen: „da läuft
    nichts" (schnell) ist etwas anderes als „läuft, antwortet aber nicht".
"""

import atexit
import json
import os
import socket
from typing import Any

# Konfigurierbar via Umgebungsvariablen, sonst Defaults.
#
# Multi-Bridge-Betrieb: Jede Cadwork-Instanz lauscht auf einem eigenen Port
# (das Dock nimmt den ersten freien 53127..53199). Ein fester Port kommt
# ueber OPEN_MCP_CAD_PORT; CADWORK_BRIDGE_PORT bleibt als Alias erhalten,
# falls aeltere Configs ihn nutzen. Ohne jede Angabe gilt 53127 — ausser im
# MCP-Server, der `AUTOMATISCH` einschaltet (siehe `_aus_registry()`).
BRIDGE_HOST = os.environ.get("CADWORK_BRIDGE_HOST", "127.0.0.1")
_PORT_ANGEGEBEN = bool(os.environ.get("OPEN_MCP_CAD_PORT")
                       or os.environ.get("CADWORK_BRIDGE_PORT"))
BRIDGE_PORT = int(
    os.environ.get("OPEN_MCP_CAD_PORT")
    or os.environ.get("CADWORK_BRIDGE_PORT", "53127")
)
# DASSELBE Objekt, nicht nur derselbe Wert: `bridge_client.BRIDGE_PORT = x`
# von aussen (so waehlen Zeichner ihren Port) ersetzt es, auch mit x = 53127.
# Daran erkennt `_port()`, dass jemand ausdruecklich gewaehlt hat.
_PORT_BEIM_IMPORT = BRIDGE_PORT

# Die Instanz ueber das DOKUMENT waehlen statt ueber den Port.
#
# Ist OPEN_MCP_CAD_DOC gesetzt, fragt der Client die Registry: welche
# laufende Instanz hat eine Datei offen, deren Name diesen Teil enthaelt?
# Das ist die Frage, die man wirklich hat — "welcher Port bedient Seeblick"
# stand vorher nirgends, man musste es sich merken.
#
# Nur ein EINDEUTIGER Treffer waehlt, und die Wahl klebt wie bei der
# Automatik an Port und PID (`_aus_registry()`). Keiner oder mehrere:
# `InstanzUnklar`, nichts gesendet, beim naechsten Aufruf neu gefragt. Auf
# OPEN_MCP_CAD_PORT oder 53127 wird NIE ausgewichen — bis 2026-09-25 fragte
# der Client die Registry nur beim ersten Aufruf, und fand er da nichts
# (der MCP-Server startet oft vor Cadwork), ging jeder weitere Aufruf still
# an den festen Port: womoeglich ein anderes Dokument.
#
# Unterschied zu OPEN_MCP_CAD_EXPECT_DOC: das PRUEFT vor jedem Aufruf ueber
# die Bridge selbst, ob die erwartete Datei offen ist. Dieses hier SUCHT die
# Instanz. Beide zusammen sind sinnvoll.
BRIDGE_DOC = os.environ.get("OPEN_MCP_CAD_DOC", "").strip()
_gebunden = False               # `ziel_setzen` hat gewaehlt, die Registry schweigt

# Ohne jede Angabe ueber die Registry waehlen — NUR im MCP-Server
# (`server.main()` schaltet es ein). Skripte, die dieses Modul importieren,
# behalten 53127: ein Zeichner ohne Port, der frueher an einem toten 53127
# abbrach, baute sonst still in das eine Cadwork, das gerade laeuft
# (Befund der Pruefung 2026-09-25).
AUTOMATISCH = False
_gewaehlt = None                # der Registry-Eintrag, den `_aus_registry()` nahm


def _registry():
    try:
        from . import registry
    except ImportError:                     # direkt ausgefuehrt, nicht als Paket
        import registry                     # type: ignore
    return registry


def _ohne_angabe() -> bool:
    """Automatik an und niemand hat gewaehlt: kein Port, kein Dokument,
    nicht gebunden."""
    return AUTOMATISCH and not (_gebunden or BRIDGE_DOC or _PORT_ANGEGEBEN
                                or BRIDGE_PORT is not _PORT_BEIM_IMPORT)


def _port() -> int:
    """Der Port dieser Sitzung — gebunden, ueber das Dokument, fest, sonst
    (nur im Server) automatisch ueber die Registry."""
    if _gebunden:
        return BRIDGE_PORT
    if BRIDGE_DOC or _ohne_angabe():
        return _aus_registry()
    return BRIDGE_PORT


def _aus_registry() -> int:
    """Die Instanz laut Registry: die EINE, deren Datei OPEN_MCP_CAD_DOC im
    Namen traegt — ohne Dokument (nur im Server) die EINE verbundene.

    Je Aufruf neu gefragt, nicht einmal je Prozess: ein MCP-Server startet
    oft vor Cadwork. Einmal gewaehlt, bleibt es bei diesem Cadwork (Port UND
    PID) — ein Fenster, das spaeter dazukommt, lenkt nichts um, auch wenn
    seine Datei ebenfalls passt. Gewechselt wird NIE still, denn Code in der
    falschen Datei ist genau die Verwechslung, gegen die es den
    Dokumentschutz gibt. Deshalb `InstanzUnklar`, bis `wait_for_bridge` neu
    bindet, wenn
      * das gewaehlte Cadwork nicht mehr laeuft (auch wenn ein anderes
        dieselbe Datei offen hat: die Registry kennt nur Namen, nicht den
        Ordner);
      * in ihm eine andere Datei offen ist als beim ersten Blick. Ein
        leerer Name zaehlt nicht — der Kern traegt sich erst ohne ein.

    Noch nichts gewaehlt und kein eindeutiger Treffer: `InstanzUnklar`,
    beim naechsten Aufruf wird neu gefragt. Einzige Ausnahme ist die
    Automatik bei LEERER Registry: der Port von frueher (53127), damit ein
    Plugin ohne Registry erreichbar bleibt und die Fehlermeldung die
    gewohnte ist. Mit Dokument nie — der feste Port kann eine andere Datei
    offen haben.
    """
    global _gewaehlt
    reg = _registry()
    eintraege = reg.laufende()
    if _gewaehlt is not None:
        for e in eintraege:
            if (e.get("port"), e.get("pid")) != (_gewaehlt.get("port"),
                                                 _gewaehlt.get("pid")):
                continue
            alt = (_gewaehlt.get("dokument") or "").lower()
            neu = (e.get("dokument") or "").lower()
            if alt and neu and alt != neu:
                raise InstanzUnklar(
                    "Im gewaehlten Cadwork (Port %s) ist jetzt %s offen statt "
                    "%s." % (e.get("port"), e.get("dokument"),
                             _gewaehlt.get("dokument")), eintraege)
            if neu:
                _gewaehlt = e               # leeren Namen nachfuehren
            return int(e["port"])
        raise InstanzUnklar("Das bisher verbundene Cadwork (%s) laeuft nicht "
                            "mehr." % _eintrag_text(_gewaehlt), eintraege)
    treffer = reg.finde(BRIDGE_DOC, eintraege) if BRIDGE_DOC else eintraege
    if len(treffer) == 1:
        _gewaehlt = treffer[0]
        return int(_gewaehlt["port"])
    if BRIDGE_DOC and treffer:
        raise InstanzUnklar(
            "%d verbundene Cadwork-Fenster haben eine Datei mit %r im Namen "
            "offen (OPEN_MCP_CAD_DOC), keines wird geraten."
            % (len(treffer), BRIDGE_DOC), eintraege)
    if BRIDGE_DOC:
        raise InstanzUnklar(
            "Kein verbundenes Cadwork hat eine Datei mit %r im Namen offen "
            "(OPEN_MCP_CAD_DOC)." % BRIDGE_DOC, eintraege)
    if eintraege:
        raise InstanzUnklar("%d Cadwork-Fenster sind verbunden, ohne Angabe "
                            "wird keines geraten." % len(eintraege), eintraege)
    return BRIDGE_PORT


def _eintrag_text(e) -> str:
    return "%s, Port %s, %s" % (e.get("instanz", "?"), e.get("port", "?"),
                               e.get("dokument") or "noch ohne Dokument")


def ziel_setzen(port: int) -> None:
    """Bindet diese Sitzung an einen Port — nach einer GEPRUEFTEN Suche.

    Gerufen von `wait_for_bridge`, nachdem Dokumentname und Port ueber die
    Bridge selbst bestaetigt sind. Danach gehen alle Aufrufe dorthin, und
    weder OPEN_MCP_CAD_DOC noch die automatische Wahl fragen die Registry
    noch: die Suche ist erledigt, und zwar gruendlicher, als `_port()` sie
    macht.
    """
    global BRIDGE_PORT, _gebunden, _gewaehlt
    BRIDGE_PORT = int(port)
    _gebunden = True
    _gewaehlt = None


BRIDGE_TIMEOUT_SECONDS = float(os.environ.get("CADWORK_BRIDGE_TIMEOUT", "10"))
# Verbindungsaufbau getrennt: ein laufendes Plugin nimmt sofort an. Auf ein
# "Connection refused" ist kein Verlass — gemessen 2026-08-04 auf dem Legion
# läuft eine Verbindung zu einem geschlossenen Localhost-Port in den Timeout.
BRIDGE_CONNECT_TIMEOUT_SECONDS = float(
    os.environ.get("CADWORK_BRIDGE_CONNECT_TIMEOUT", "1.0")
)

# Stabile Kennung dieser Sitzung für die Schreiblizenz der Bridge.
CLIENT_ID = (
    os.environ.get("OPEN_MCP_CAD_CLIENT_ID")
    or os.environ.get("CLAUDE_SESSION_ID")
    or "pid:%d" % os.getpid()
)
CLIENT_LABEL = os.environ.get("OPEN_MCP_CAD_CLIENT_LABEL", "Claude Code")

# Methoden, die die Bridge ohne den Cadwork-Hauptthread beantwortet.
STEUER_METHODEN = ("ping", "status", "pause", "resume", "shutdown",
                   "shutdown_after_current", "discard_pending",
                   "release_write_lease", "list_store_keys", "clear_store")

_lizenz_moeglich = False        # wurde in dieser Sitzung je geschrieben?


class BridgeUnreachable(Exception):
    """Wird ausgelöst wenn die Bridge in Cadwork nicht erreichbar ist."""


class BridgeError(Exception):
    """Bridge hat eine Fehlerantwort geliefert."""

    def __init__(self, code: str, message: str, details: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class AntwortFehlt(BridgeUnreachable):
    """Der Auftrag ist GESENDET, aber die Antwort kam nicht: Zeitgrenze
    abgelaufen oder die Verbindung brach danach ab.

    Das Gegenteil von "nicht erreichbar": der Auftrag kann laufen oder schon
    fertig sein, er darf NICHT blind wiederholt werden. Unterklasse von
    `BridgeUnreachable`, damit bestehende Aufrufer weiter fangen. Eigene
    Klasse, weil die Unterscheidung vorher nur im Meldungstext stand — und
    der Server daraus "nicht erreichbar, Plugin klicken" machte. Gemessen
    2026-09-25: Endtyp an 286 Staeben, 10,7 s in Cadwork, erfolgreich
    fertig; der Agent bekam "nicht erreichbar".
    """

    def __init__(self, text: str, gewartet_s: float):
        super().__init__(text)
        self.gewartet_s = gewartet_s


class InstanzUnklar(BridgeUnreachable):
    """Offen, welches Cadwork gemeint ist — ohne Angabe oder ueber
    OPEN_MCP_CAD_DOC (keine oder mehrere passende Dateien, oder das gewaehlte
    Cadwork ist weg bzw. zeigt eine andere Datei).

    Wie "nicht erreichbar": der Auftrag wurde NIE gesendet. Gewaehlt wird
    ueber `wait_for_bridge(dokument)` im Server oder OPEN_MCP_CAD_DOC bzw.
    OPEN_MCP_CAD_PORT.
    """

    def __init__(self, grund: str, eintraege: list):
        self.grund = grund
        self.instanzen = [{"instanz": e.get("instanz"), "port": e.get("port"),
                           "dokument": e.get("dokument") or ""}
                          for e in eintraege]
        liste = "\n".join("  " + _eintrag_text(e) for e in eintraege)
        super().__init__(
            "%s Der Auftrag wurde NICHT gesendet. Verbunden ist:\n%s\n"
            "Waehlen mit wait_for_bridge('<Datei>.3d') oder ueber "
            "OPEN_MCP_CAD_DOC / OPEN_MCP_CAD_PORT (das Dokument geht vor)."
            % (grund, liste or "  (kein Cadwork eingetragen)"))


def _read_line(sock: socket.socket) -> bytes:
    """Liest Bytes bis zum nächsten Newline. Wirft ConnectionError bei EOF."""
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            # Verbindung geschlossen ohne komplette Zeile
            raise ConnectionError("Bridge hat Verbindung vorzeitig geschlossen")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    data = b"".join(chunks)
    line, _, _ = data.partition(b"\n")
    return line


def call(method: str, params: dict | None = None, request_id: int = 1,
         *, port: int | None = None,
         antwort_timeout: float | None = None) -> Any:
    """Sendet einen Request an die Bridge und gibt das Result-Feld zurück.

    Wirft BridgeUnreachable wenn keine Verbindung möglich ist (Plugin nicht
    gestartet, falscher Port, ...), AntwortFehlt wenn der Auftrag gesendet
    ist, die Antwort aber ausbleibt, und BridgeError wenn die Bridge selbst
    eine Fehlerantwort sendet.

    `port` fragt EINMAL einen anderen Port als den der Sitzung — gedacht
    fuer lesende Pruefungen (`wait_for_bridge`), bevor die Sitzung gebunden
    ist. Schreiben gehoert an den Sitzungsport: nur dort gibt
    `release_write_lease` die Schreiblizenz am Ende wieder frei.

    `antwort_timeout` ersetzt fuer DIESEN Aufruf die Wartezeit auf die
    Antwort (sonst CADWORK_BRIDGE_TIMEOUT). Der Verbindungsaufbau bleibt
    kurz: ob das Plugin laeuft, steht nach einer Sekunde fest.
    """
    global _lizenz_moeglich

    params = dict(params or {})
    # Kennung anhängen — alte Bridges ignorieren unbekannte Parameter.
    params.setdefault("client_id", CLIENT_ID)
    params.setdefault("client_label", CLIENT_LABEL)
    if method == "execute_cwapi3d" and params.get("access_mode") != "read":
        _lizenz_moeglich = True

    request = {"id": request_id, "method": method, "params": params}
    payload = (json.dumps(request) + "\n").encode("utf-8")

    # EINMAL bestimmen und festhalten: waehrend eines Aufrufs darf der Port
    # nicht wandern, sonst steht in der Fehlermeldung ein anderer als der,
    # zu dem verbunden wurde.
    port = _port() if port is None else int(port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(BRIDGE_CONNECT_TIMEOUT_SECONDS)
        try:
            sock.connect((BRIDGE_HOST, port))
        except (ConnectionRefusedError, TimeoutError, socket.timeout,
                OSError) as exc:
            hinweis = ""
            if BRIDGE_DOC and not _gebunden:
                hinweis = ("\nGesucht wurde eine Instanz mit %r im "
                           "Dokumentnamen. Eingetragen ist:\n%s"
                           % (BRIDGE_DOC, _registry().beschreibung()))
            elif _ohne_angabe():
                hinweis = ("\nKein Port angegeben, gewaehlt ueber die "
                           "Registry. Eingetragen ist:\n%s"
                           % _registry().beschreibung())
            raise BridgeUnreachable(
                f"Open MCP CAD auf {BRIDGE_HOST}:{port} ist nicht "
                f"erreichbar — läuft das Plugin in Cadwork? "
                f"({type(exc).__name__}){hinweis}"
            ) from exc
        warten = (float(antwort_timeout) if antwort_timeout
                  else BRIDGE_TIMEOUT_SECONDS)
        sock.settimeout(warten)
        # Senden und Lesen getrennt: scheitert das SENDEN, kam keine ganze
        # Zeile an, und die Bridge fuehrt nichts aus. Scheitert erst das
        # LESEN, ist der Auftrag angekommen — sein Ausgang ist offen.
        try:
            sock.sendall(payload)
        except OSError as exc:
            raise BridgeUnreachable(
                f"Verbindung zu {BRIDGE_HOST}:{port} abgebrochen: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            line = _read_line(sock)
        except (TimeoutError, socket.timeout) as exc:
            raise AntwortFehlt(
                f"Open MCP CAD auf {BRIDGE_HOST}:{port} nimmt an, "
                f"antwortet aber seit {warten:.0f} s nicht. "
                f"Der Auftrag kann trotzdem laufen — Zustand mit "
                f"status() prüfen, NICHT blind wiederholen.", warten
            ) from exc
        except OSError as exc:
            raise AntwortFehlt(
                f"Verbindung zu {BRIDGE_HOST}:{port} brach NACH dem Senden "
                f"ab ({type(exc).__name__}: {exc}). Der Auftrag kann "
                f"gelaufen sein — Zustand mit status() prüfen, NICHT blind "
                f"wiederholen.", warten
            ) from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass

    try:
        response = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgeError(
            "invalid_response",
            "Bridge-Antwort war kein gültiges JSON",
            details=f"{exc}: {line!r}",
        ) from exc

    if not response.get("ok"):
        raise BridgeError(
            code=response.get("error", "unknown"),
            message=response.get("message", "Unbekannter Bridge-Fehler"),
            details=response.get("details", ""),
        )

    return response.get("result")


def status() -> dict:
    """Zustand der Verbindung — antwortet auch, wenn Cadwork gerade arbeitet.

    Läuft NICHT über die Job-Queue der Bridge. Genau dafür gedacht, wenn ein
    Aufruf ins Timeout gelaufen ist: erst nachsehen, was tatsächlich läuft,
    statt den Auftrag blind zu wiederholen.
    """
    return call("status")


def release_write_lease() -> None:
    """Gibt eine gehaltene Schreiblizenz frei (Best-Effort, wirft nie)."""
    if not _lizenz_moeglich:
        return
    try:
        call("release_write_lease", {"client_id": CLIENT_ID})
    except (BridgeUnreachable, BridgeError):
        pass


# Ohne das müsste das nächste Skript bis zum Ablauf der Lizenz warten, obwohl
# dieses hier längst fertig ist.
atexit.register(release_write_lease)
