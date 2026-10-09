# -*- coding: utf-8 -*-
"""A-ONLY UI PROTOTYPE — modernes Dashboard fuer Open MCP CAD A.

    ################################################################
    #  A-ONLY UI PROTOTYPE                                         #
    #  Gilt AUSSCHLIESSLICH fuer Steckplatz A.                     #
    #  B, C, D und der gemeinsame Kern sind unberuehrt.            #
    #  Rueckbau: siehe docs/PROTOTYP_A_dashboard.md                #
    ################################################################

WARUM DIESE DATEI UEBERHAUPT
Der gemeinsame Kern kann heute nur "Dienst starten UND Fenster oeffnen"
(`serve()` mit `cfg.fenster`). Das Dashboard soll aber die EINE
Oberflaeche sein — auch dann, wenn nichts verbunden ist oder das
Verbinden scheitert. Deshalb ein eigener Controller: er besitzt das Dock,
und der Kern liefert nur den Dienst (gestartet mit `cfg.fenster = False`,
damit nicht zusaetzlich das alte Fenster aufgeht).

EIN KLICK VERBINDET (seit 2026-09-22). Der Plugin-Klick oeffnet das Dock
UND verbindet — ueber `_verbinden`, denselben Weg wie der Knopf. Vorher
war ein zweiter Klick auf "Verbinden" noetig; ein KI-Agent, der Cadwork
per Computer Use bedient, brauchte damit zwei Klicks statt einem.

WO DER ZUSTAND LEBT — und warum nicht im Modul
Der Plugin-Einstieg laedt Kern und Controller bei JEDEM Klick frisch von
der Platte (sonst liefe nach einem Update weiter der alte Code aus dem
Speicher). Modulglobale Variablen ueberleben das also nicht. Der Zustand
liegt deshalb in `sys.modules` unter festem Namen (`ANKER`) — das lebt so
lange wie Cadworks Python-Prozess. Nur so findet ein zweiter Klick
dasselbe Dock und denselben Dienst wieder, statt ein zweites Dock und
einen zweiten Dienst zu bauen. Bis 2026-09-25 hing er NUR an der
QApplication; das hat nicht gehalten (siehe `_zustand`).

WAS DIESES MODUL NICHT TUT
Es weicht nie aus: ist der im Dock GEWAEHLTE Steckplatz belegt, scheitert
das Verbinden mit einer Meldung (`_verbinden`). Nur "automatisch" nimmt
den ersten freien. Portnummern stehen nicht hier, sondern im
Verbindungs-Client (die benannten) und im Kern (`PORT_VON`/`PORT_BIS`).
"""

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback

# Alles, was das Plugin mitbringt (das Logo steckt in icon.svg), liegt NEBEN
# dieser Datei, nicht im Repo-`assets`: der Plugin-Ordner ist das, was nach
# Cadwork ausgerollt wird. (Die Bilddateien logo.png/logo_quadrat.png und ihr
# Leser `_logo_label` sind mit K11 weg — niemand rief ihn mehr.)
_HIER = os.path.dirname(os.path.abspath(__file__))

# Der Arbeitsordner des Chats — das PROJEKT des Nutzers, nicht dieser Ordner
# und auch nicht dieses Repo.
#
# Der Chat-Agent bildet den Namen seines Sitzungsordners aus dem `cwd`.
# Startet er im ausgerollten Plugin-Ordner, landen die Gespraeche in einer
# fremden Liste und tauchen im Terminal nie wieder auf. Der Plugin-Ordner
# liegt im Cadwork-Benutzerprofil und hat mit dem Projekt nichts zu tun.
#
# ⚠ WAS HIER NICHT STEHEN DARF: fest verdrahtete Pfade.
#
# Bis 2026-09-20 standen hier drei Benutzerpfade eines einzelnen Rechners.
# Bei der Umbenennung dieses Repos sind sie MITGEWANDERT — aus
# der alte Repo-Name wurde zu "…\projekte\open-mcp-cad". Damit zeigte
# der Arbeitsordner auf das Bruecken-Repo statt auf das Projekt des
# Nutzers: der Chat haette in einem Ordner gearbeitet, in dem es nichts
# zu bauen gibt.
#
# Der Fehler war nur moeglich, weil der Pfad wie ein Name DIESES Projekts
# aussah. Er ist aber ein Verweis auf ein FREMDES Verzeichnis — und solche
# Verweise gehoeren in die Konfiguration, nicht in den Quelltext.
#
# Drei Wege, alle sichtbar und ohne Raten, in dieser Rangfolge
# (Entscheid 2026-09-26, docs/UEBERGABE_2026-09-26_DOCKPLAN.md):
#   1. Umgebungsvariable OPEN_MCP_CAD_PROJEKT
#   2. die Wahl im Dock — gemerkt in chat.json (`arbeitsordner`), vom
#      Dashboard beim Aufbau gelesen und hier als `wahl` hereingereicht
#   3. eine Datei `projektordner.txt` neben diesem Plugin, die den Pfad
#      enthaelt (eine Zeile) — fuer alle, die keine Umgebungsvariable
#      setzen wollen
# Ein Eintrag, der auf keinen vorhandenen Ordner zeigt, zaehlt nicht.
# Findet sich keiner, gibt es KEINEN Arbeitsordner, und das Dashboard sagt
# das; Claude Code startet dann nicht. Ein geratener Ordner waere schlimmer
# als keiner: der Ordner ist zugleich die Grenze, in der "Lesen
# automatisch" ohne Karte liest.
PROJEKT_DATEI = os.path.join(_HIER, "projektordner.txt")


def arbeitsordner(wahl=None):
    """Wo der Chat laufen soll. Nie raten, ohne es anzuzeigen.

    `wahl` ist der im Dock gewaehlte Ordner (oder None). Die Funktion liest
    chat.json NICHT selbst: sie laeuft auch im Qt-Takt, und test_a_prototyp
    P9 fuehrt diesen Abschnitt mit nichts als `os` und `_HIER` aus.
    """
    gesetzt = os.environ.get("OPEN_MCP_CAD_PROJEKT")
    if gesetzt and os.path.isdir(gesetzt):
        return gesetzt
    if isinstance(wahl, str) and wahl and os.path.isdir(wahl):
        return wahl
    try:
        with open(PROJEKT_DATEI, encoding="utf-8") as fh:
            pfad = fh.read().strip().strip('"')
        if pfad and os.path.isdir(pfad):
            return pfad
    except OSError:
        pass
    return None


def _verbindungen_client():
    """Der A-eigene Netzwerkteil — ueber den Pfad NEBEN dieser Datei.

    Kein `import` ueber den Repo-Pfad: der Pluginordner wird ins Cadwork-
    Userprofil kopiert und muss dort allein laufen.
    """
    name = "omcad_verbindungen_client_A"
    vorhanden = sys.modules.get(name)
    if vorhanden is not None:
        return vorhanden
    pfad = os.path.join(_HIER, "omcad_verbindungen_client.py")
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _chat_modul():
    """Der Gespraechsteil — genauso NEBEN dieser Datei geladen wie oben.

    Er kennt weder Qt noch cwapi3d und laesst sich deshalb ohne Cadwork
    pruefen; das A-Gate nagelt beides fest.
    """
    name = "omcad_a_chat_A"
    vorhanden = sys.modules.get(name)
    if vorhanden is not None:
        return vorhanden
    pfad = os.path.join(_HIER, "omcad_a_chat.py")
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _anbieter_modul():
    """Die anderen Chat-Anbieter (OpenAI-kompatibel) — geladen wie der Chat.

    Ebenfalls ohne Qt und ohne cwapi3d; geprueft von tests/test_anbieter.py.
    """
    name = "omcad_a_anbieter_A"
    vorhanden = sys.modules.get(name)
    if vorhanden is not None:
        return vorhanden
    pfad = os.path.join(_HIER, "omcad_a_anbieter.py")
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


_LOKAL = []


def _lokal_modul():
    """Ollama und LM Studio erkennen, starten, installieren (ohne Qt).

    ANDERS als Chat und Anbieter NICHT unter festem Namen in `sys.modules`:
    das Modul haelt keinen Zustand, also darf es mit jedem Laden dieses
    Dashboards frisch kommen — ein Update braucht dafuer keinen Neustart.
    """
    if not _LOKAL:
        pfad = os.path.join(_HIER, "omcad_a_lokal.py")
        spec = importlib.util.spec_from_file_location("omcad_a_lokal_A", pfad)
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        _LOKAL.append(modul)
    return _LOKAL[0]


_SYMBOL = []


def _symbol_modul():
    """Die Strich-Symbole (Lucide, omcad_a_symbole.py) — wie omcad_a_lokal
    frisch mit jedem Dashboard, ohne Zustand ausser dem Bildspeicher. Fehlt
    die Datei oder wirft sie, None: dann stehen ueberall die Ersatztexte."""
    if not _SYMBOL:
        try:
            pfad = os.path.join(_HIER, "omcad_a_symbole.py")
            spec = importlib.util.spec_from_file_location(
                "omcad_a_symbole_A", pfad)
            modul = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modul)
        except Exception as exc:                       # noqa: BLE001
            _melden("Symbole laden", exc)
            modul = None
        _SYMBOL.append(modul)
    return _SYMBOL[0]


# Rueckmeldung 2026-09-28: die Emoji wirkten "KI-haft", das ✎ fuer "Neuer
# Chat" war kaum zu erkennen. EINE Tabelle: wofuer -> (Lucide-Name, was
# ohne Symbol dasteht). Ohne QtSvg (in Cadwork nicht gemessen) steht der
# Ersatztext, nie ein Kaestchen und nie ein Fehler. test_a_prototyp P18
# verlangt, dass jeder Name hier in omcad_a_symbole steht.
SYMBOLE = {
    "einstellungen": ("settings", "⚙"),
    "verkleinern": ("minus", "–"),
    # Gegenpruefung Laien-Sicht K12 (Wunsch des Maintainers, sein Bild 8):
    # der letzte Knopf des Kopfs liest sich als "Vergroessern/Andocken" —
    # zwei Pfeile nach aussen; angedockt zwei Pfeile nach innen.
    "andocken": ("maximize-2", "⤢"),
    "schliessen": ("x", "✕"),
    "vergroessern": ("maximize-2", "⤢"),
    "griff": ("grip-vertical", "⠿"),
    "chat": ("message-square", ""),
    "neuer_chat": ("square-pen", "Neu"),
    # K9b (Rueckmeldung 2026-09-28): "circle-stop" las sich bei 16 px wie
    # eine Zielscheibe (Kreis mit Punkt). Das gefuellte Quadrat ist das
    # Stopp-Zeichen jedes Abspielgeraets (GEFUELLT), dazu das Wort.
    "beenden": ("square", "■"),
    "ordner": ("folder", ""),
    "ordner_waehlen": ("folder-open", ""),
    "ordner_plus": ("folder-plus", "+"),
    "plus": ("plus", "+"),
    "anhang": ("paperclip", ""),
    "einfuegen": ("clipboard-paste", ""),
    "senden": ("arrow-up", "↑"),
    "aufklappen": ("chevron-up", ""),
    "zu": ("chevron-right", "▸"),
    "auf": ("chevron-down", "▾"),
    "warnung": ("triangle-alert", "!"),
    "abgelehnt": ("ban", ""),
    "haken": ("check", "✓"),
    "ki": ("sparkles", "✦"),
    "neu_unten": ("arrow-down", "↓"),
    "abfragen": ("refresh-cw", "↻"),
    "bild": ("image", ""),
    "datei": ("file-text", ""),
    "laedt": ("hourglass", ""),
    "rueckgaengig": ("undo-2", "↶"),
    "wiederholen": ("redo-2", "↷"),
    "anderes": ("wrench", ""),
    "neu_zeichnen": ("refresh-cw", "↻"),
    "pausieren": ("pause", ""),
    "fortsetzen": ("play", ""),
    "trennen": ("unplug", ""),
    "auftraege": ("list-checks", ""),
    "hinweise": ("lightbulb", ""),
    "briefkasten": ("inbox", ""),
    "technik": ("wrench", ""),
    # K11: "Ablegen" im Briefkasten (ein Brief, kein Senden-Pfeil wie im
    # Chat) — das Wort steht immer daneben, also kein Ersatztext noetig.
    "ablegen": ("mail", ""),
    # K12 (2026-10-07): Kopf, Segmente, Hinweise, "⋯", Denkstufe, Zurueck.
    "abdocken": ("minimize-2", "⤡"),
    "segment_briefkasten": ("mail", ""),
    "hinweise_flagge": ("flag", "!"),
    "mehr": ("ellipsis", "⋯"),
    "denkstufe": ("brain", ""),
    "zurueck_vorgabe": ("rotate-ccw", "↺"),
    "zurueck": ("arrow-left", "←"),
}
#: Diese Zwecke zeichnen ihr Symbol gefuellt (nur die Huelle, die Pfade
#: bleiben die von Lucide).
GEFUELLT = frozenset({"beenden"})
#: Die vier Modi (Werte aus omcad_a_chat.MODI) -> Lucide-Name.
MODUS_SYMBOLE = {"nur_lesen": "eye", "fragen": "hand",
                 "cadwork_frei": "hammer", "alles_auto": "zap"}


def _knopf_symbol(knopf, zweck, text=None, farbe=None, groesse=16):
    """Das Symbol fuer `zweck` (SYMBOLE) auf `knopf`, dazu `text`; ohne
    Symbol der Ersatztext (bzw. `text`). Merkt den Zweck als Eigenschaft
    `symbol` (die Gates finden Knoepfe so, nicht am Text). -> True, wenn das
    Symbol steht. Wirft nie."""
    lucide, ersatz = SYMBOLE.get(zweck, (zweck, ""))
    try:
        knopf.setProperty("symbol", zweck)
    except Exception:                                  # noqa: BLE001
        pass
    S = _symbol_modul()
    if S is None:
        try:
            knopf.setText(text or ersatz)
        except Exception:                              # noqa: BLE001
            pass
        return False
    return S.knopf_setzen(knopf, lucide, ersatz, text,
                          farbe or FARBEN["text"], groesse,
                          fuellen=zweck in GEFUELLT)


def _label_symbol(label, lucide, ersatz="", farbe=None, groesse=14):
    """Ein QLabel zeigt das Symbol (Lucide-Name) — sonst `ersatz`. Wirft
    nie."""
    try:
        label.setProperty("symbol", lucide)
    except Exception:                                  # noqa: BLE001
        pass
    S = _symbol_modul()
    if S is None:
        try:
            label.setText(ersatz)
        except Exception:                              # noqa: BLE001
            pass
        return False
    return S.label_setzen(label, lucide, ersatz, farbe or FARBEN["neben"],
                          groesse)


def _ikone(lucide, farbe=None, groesse=16):
    """Das Symbol als QIcon — oder None (dann ohne)."""
    S = _symbol_modul()
    if S is None:
        return None
    try:
        return S.symbol(lucide, farbe or FARBEN["text"], groesse)
    except Exception:                                  # noqa: BLE001
        return None


# --- Fassungen: Update ohne Cadwork-Neustart --------------------------------
# Jeder Plugin-Klick laedt DIESES Modul frisch von der Platte. Zwei Dinge
# ueberleben das aber und koennen deshalb aus einer aelteren Fassung stammen:
#
# 1. Das DOCK (es haengt am Zustand der QApplication). Seine Knoepfe und
#    Timer rufen den Code, mit dem es gebaut wurde, und `z["w"]` enthaelt
#    nur die Teile, die jene Fassung kannte. Neuer Code, der einen neuen
#    Teil anfasst, lief dort in einen KeyError — und der Einstieg meldete
#    "Dashboard nicht möglich — NICHT verbunden". Deshalb traegt jedes Dock
#    seine FORM; weicht sie ab, baut `oeffnen` es neu (Dienst und Chat
#    bleiben). HEBEN, sobald sich die Teile in `z["w"]` oder die Timer des
#    Docks aendern. test_a_live L31 baut das Dock, misst beides und haelt
#    es gegen die Aufnahme dort (FORM_AUFNAHME) — dort mit nachfuehren.
#
# 2. CHAT und ANBIETER (feste Namen in `sys.modules`, s. o.). Sie bleiben
#    bis zum Cadwork-Neustart. Beide tragen `SCHNITTSTELLE`; weicht sie von
#    der hier erwarteten ab, startet kein Chat — statt eines stillen
#    AttributeError steht dann, was zu tun ist. Die Zahlen hier und dort
#    gehoeren zusammen (test_a_prototyp P9 und test_a_live L26 pruefen es).
#
# FORM 3 (2026-09-26, S5/S6): Einstellungsseite statt der Tabs Verbindungen
# und Modus, Schluessel-Zeile, lokale Modelle.
# FORM 4 (2026-09-26, Nacharbeit Etappe B): Hinweis "Der Chat wartet auf
# deine Freigabe" mit "Zum Chat" auf der Einstellungsseite.
# FORM 5 (2026-09-26, S7/S8): kein "Starten" mehr (`chat_start` weg), dafuer
# "Neuer Chat", "Beenden", die Zeile "was laeuft", die Fehlerzeile an der
# Eingabe und die Leiste mit Modell, Denkstufe und Kontext darunter.
# FORM 6 (2026-09-26, Etappe D): die Liste der bisherigen Chats statt der
# Sitzungswahl (`chat_wahl` weg, `chat_liste` neu), die Ordnerwahl auf der
# Einstellungsseite, die Kontextanzeige in der Leiste.
# FORM 7 (2026-09-27, Chatfenster K1): das Modus-Feld (`chat_modus`,
# `chat_modus_text`) statt der Freigabestufe.
# FORM 8 (2026-09-27, Chatfenster K2): der Chat in einem EIGENEN Fenster
# (`z["chatfenster"]`, `chat_stapel`, Chat-Einstellungen `chat_einst_seite`),
# der Monitor kompakt mit Chat-Zeile (`chat_oeffnen`, `chat_stand`) und
# "Mehr" (`mehr`, `mehr_teil`, `fueller`).
# FORM 9 (2026-09-27, K3): Eingabe im Rahmen mit Leiste (Modus-Knopf,
# Modell-Knopf, Ring, Aufklapper), Ordnerknopf und "+ Ordner" im Kopf,
# Denkstufe als Regler, Modellfeld auf den Chat-Einstellungen.
# FORM 10 (2026-09-27, K4): "+" mit Aufklapper (`chat_plus`,
# `chat_plus_auf`), Anhaenge ueber der Eingabe (`chat_anhaenge`,
# `chat_anhaenge_lay`).
# FORM 11 (2026-09-27, K5): der Verlauf ist kein QListWidget mehr, sondern
# `Verlauf` (Blasen, Schrittgruppen, Zeitlinien) unter `chat_verlauf`.
# FORM 12 (2026-09-28, Feinschliff): `chat_arbeit` und
# `chat_leiste_hinweis` weg (das "…" steht im Verlauf, der Hinweis in den
# Aufklappern), neu `chat_status` (eine Zeile nur bei einer Stoerung) und
# `chat_technik_karte` (Wer, Art, Lage auf den Chat-Einstellungen).
# FORM 13 (2026-09-28, K9): Monitor und Chat als schwebende/andockbare Docks
# (`z["chatfenster"]` ist ein QDockWidget), die Chat-Zeile in der Kopfkarte,
# Steckplatz und Port unter "Mehr" (`mehr_port`).
# FORM 14 (2026-09-29, erster Kontakt): die Karte "Womit möchtest du
# chatten?" im Gespraech (`chat_willkommen` und ihre Knoepfe).
# FORM 15 (2026-10-01, K10): der Mini-Monitor (Name und Logo in der
# Titelleiste, Status in einer Zeile, "Chat"/"Trennen" und ein Pfeil statt
# "Mehr"), dazu das Dock "Aufträge" fuer die angedockte Seite
# (`auftraege_lay`) und der Platz von "Mehr" im Monitor (`monitor_lay`).
# FORM 16 (2026-10-02, K11): der Klick zeigt die LEISTE (eine Zeile, mit
# Chat-Symbol `mini_chat`); das Dock ist das Steuerfenster mit vier immer
# sichtbaren Reitern (Aufträge, Hinweise, Briefkasten, Einstellungen).
# Weg: der Pfeil und das Aufklappen (`mehr`, `mehr_teil`, `fueller`), die
# angedockte Seite (`monitor_lay`, `auftraege_lay`) und "Fertig"
# (`einst_fertig`); der Briefkasten ohne die Eingabe des Chats.
# FORM 17 (2026-10-07, K12): EIN Fenster `OpenMcpCadFenster` — Kopf (wie die
# Leiste) als Titelleiste, Koerper mit Kontextzeile, Segmenten "Chat |
# Briefkasten", Hinweis-Bereich und Seitenstapel (Chat, Briefkasten,
# Einstellungen); dazu die Arbeitsanzeige und der Popover fuer Modell und
# Denkstufe. Weg: Leiste, Steuerfenster mit Reitern, Chat-Dock.
# FORM 18 (2026-10-07, Gegenpruefung K12): "In den Chat übernehmen" am
# Hinweis-Bereich (`hinweis_in_chat`), die Karten der Einstellungsseite
# (`einst_karte_verbindung`, `einst_karte_modus`, `einst_karte_technik`).
# FORM 20 (2026-10-08, angedockt unsichtbar in Cadwork): keine neuen Teile,
# aber das Fenster traegt NIE mehr WA_TranslucentBackground. Ein offenes
# Fenster von FORM 19 behielte sein Alpha-Format (zur Laufzeit nicht zu
# heilen, gemessen) — der naechste Klick baut es darum neu.
# FORM 21 (2026-10-08, Rueckmeldung): das "×" im Kopf ohne Verbindung
# (`kopf_schliessen`).
FORM = 21
#: Was K9-K11 im Anker hinterliessen und K12 nicht mehr kennt: Fenster (die
#: Leiste `mini`, das Chat-Dock `chatfenster`, das Dock "Aufträge" von K10;
#: das Steuerfenster stand unter `dock`) und Merker. `_dock_abbauen` raeumt
#: sie weg (Update ohne Cadwork-Neustart, Spezifikation 1.6).
ALTE_FENSTER = ("mini", "chatfenster", "auftraege_dock")
ALTE_SCHLUESSEL = ("steuer_war_offen", "monitor_angedockt", "chat_angedockt",
                   "chat_ort", "leiste_soll", "leiste_rechts_oben",
                   "monitor_bereich", "chat_bereich", "leiste_anker",
                   "leiste_gezogen", "monitor_soll", "monitor_gezogen",
                   "chat_soll", "chat_platziert", "monitor_ort",
                   "steuer_groesse", "chatfenster_war_offen", "seite_aktiv",
                   "chat_mit_monitor", "mehr_offen", "auftraege_dock",
                   "chatfenster", "mini")
# 2 (Etappe D): `starten(name=, vorher=)`, `sitzungen(nur_dock=)`,
# `sitzung_verlauf`, `SITZUNG_NAME`.
# 3 (Nacharbeit D): `sitzung_belegt`, `SitzungBelegt`, `belegt` je Eintrag.
# 4 / 2 (Chatfenster K1, 2026-09-27): vier Modi, `chat_entscheiden` statt
# `automatisch_erlauben`, `freigabe_beantworten(..., sitzung=)`.
# 5 (K3): `starten(..., zusatz=)` (weitere Ordner, `--add-dir`).
# 6 / 3 (K4): `senden(..., anhaenge=)` in Chat und Anbietern.
CHAT_SCHNITTSTELLE = 6
ANBIETER_SCHNITTSTELLE = 3
CHAT_VERALTET = ("Open MCP CAD wurde aktualisiert — Cadwork neu starten, "
                 "damit der Chat die neue Fassung lädt.")


def _chat_veraltet():
    """None, wenn Chat und Anbieter zur Fassung dieses Moduls passen.

    Sonst der Satz fuer die Oberflaeche. Laesst sich ein Modul gar nicht
    laden, steht der Grund darin — auch das ist kein Zustand, in dem ein
    Chat starten darf.
    """
    for laden, erwartet in ((_chat_modul, CHAT_SCHNITTSTELLE),
                            (_anbieter_modul, ANBIETER_SCHNITTSTELLE)):
        try:
            modul = laden()
        except Exception as exc:                       # noqa: BLE001
            return "Der Chat lässt sich nicht laden: %s" % exc
        if getattr(modul, "SCHNITTSTELLE", None) != erwartet:
            return CHAT_VERALTET
    return None


# --- Fehler im Takt: nie still, nie den Takt anhalten -----------------------
# Bis 2026-09-25 schluckten `_sicher` und die try-Bloecke in `_auffrischen`
# jede Ausnahme wortlos. Ein Fehler im Zeichnen sah dann aus wie ein Dock,
# das einfach nichts tut. Jetzt steht jeder VERSCHIEDENE Fehler genau einmal
# auf stderr (Cadwork zeigt ihn in der Python-Konsole), der Takt laeuft
# trotzdem weiter.
_GEMELDET = set()
_MELDEN_HOECHSTENS = 100      # verschiedene Texte je Modul-Ladung


def _stderr(text):
    """Nach stderr — und falls es keins gibt, still. Wirft nie."""
    strom = sys.stderr if sys.stderr is not None else sys.__stderr__
    if strom is None:
        return
    try:
        strom.write(text)
        strom.flush()
    except Exception:                                  # noqa: BLE001
        pass


def _melden(wo, exc):
    """Eine Ausnahme aus dem Takt EINMAL je Wortlaut nach stderr."""
    kennung = "%s: %s: %s" % (wo, type(exc).__name__, exc)
    if kennung in _GEMELDET or len(_GEMELDET) >= _MELDEN_HOECHSTENS:
        return
    _GEMELDET.add(kennung)
    try:
        spur = "".join(traceback.format_exception(type(exc), exc,
                                                  exc.__traceback__))
    except Exception:                                  # noqa: BLE001
        spur = ""
    _stderr("[Open MCP CAD] Fehler im Takt (%s)\n%s" % (kennung, spur))

# --- Farben und Form ------------------------------------------------------
# Richtung vom HBT-Rechner uebernommen (hell, ruhig, weisse Karten), aber als
# schmale vertikale Karten statt als Desktop-Layout: ein Cadwork-Seitendock
# ist viel schmaler als eine Weboberflaeche.
FARBEN = {
    "grund": "#f5f5f7",
    "karte": "#ffffff",
    "rahmen": "#e3e3e6",
    "text": "#1d1d1f",
    "neben": "#6e6e73",
    "blau": "#0071e3",
    "gruen": "#34c759",
    "orange": "#ff9f0a",
    "rot": "#ff3b30",
}

# WICHTIG: alles unter #OpenMcpCadA — KEIN globales setStyleSheet. Ein globales
# Stylesheet wuerde Cadworks eigene Dialoge mit umfaerben.
QSS = """
#OpenMcpCadA { background: %(grund)s; }
#OpenMcpCadA QLabel { color: %(text)s; font-size: 12px; }
#OpenMcpCadA QWidget#karte {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 12px;
}
#OpenMcpCadA QWidget#karte_innen {
    background: %(grund)s; border: 1px solid %(rahmen)s; border-radius: 10px;
}
#OpenMcpCadA QLabel#titel { font-size: 15px; font-weight: 600; }
/* Freigabe-Karte. Die Regeln MUESSEN am objectName haengen: ein
   setStyleSheet direkt auf dem Rahmen-Widget vererbt sich auf jedes
   Kind — der Sichttest zeigte dadurch um JEDES Label einen eigenen
   orangen Rahmen, die Karte war unleserlich. */
#OpenMcpCadA QWidget#freigabekarte {
    background: #fff8e8; border: 1px solid #f0c77a; border-radius: 10px;
}
#OpenMcpCadA QWidget#freigabekarte QLabel { border: none; background: transparent; }
#OpenMcpCadA QLabel#freigabe_titel { font-size: 12px; font-weight: 600; }
/* Hinweis, wenn "Nur lesen" etwas ohne Frage abgelehnt hat (2026-09-28). */
#OpenMcpCadA QWidget#sperrkarte {
    background: #eef4fd; border: 1px solid #b9d3f5; border-radius: 10px;
}
#OpenMcpCadA QWidget#sperrkarte QLabel { border: none; background: transparent; }
/* Erster Kontakt (Rueckmeldung 2026-09-29): "Womit möchtest du chatten?" */
#OpenMcpCadA QWidget#einstieg_weg {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 10px;
}
#OpenMcpCadA QWidget#einstieg_weg QLabel { border: none; background: transparent; }
#OpenMcpCadA QLabel#einstieg_titel { font-size: 16px; font-weight: 600; }
#OpenMcpCadA QLabel#einstieg_name { font-size: 13px; font-weight: 600; }
#OpenMcpCadA QLabel#einstieg_schritt {
    background: #eef4fd; border: 1px solid #b9d3f5; border-radius: 8px;
    padding: 6px 8px;
}
#OpenMcpCadA QLabel#freigabe_wortlaut {
    color: %(text)s; font-family: Consolas, monospace; font-size: 11px;
    background: #ffffff; border: 1px solid #ecdcb4; border-radius: 6px;
    padding: 4px 6px;
}
/* Die laufende Antwort: derselbe Fliesstext wie im Verlauf, nur mit
   ruhigem Rand, damit man sieht, dass sie noch waechst. */
#OpenMcpCadA QLabel#chat_laufend {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 8px;
    padding: 6px 8px;
}
#OpenMcpCadA QLabel#neben { color: %(neben)s; font-size: 11px; }
#OpenMcpCadA QLabel#chip {
    color: %(neben)s; background: %(grund)s; border: 1px solid %(rahmen)s;
    border-radius: 9px; padding: 1px 8px; font-size: 10px;
}
#OpenMcpCadA QLabel#pille {
    border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 600;
    color: #ffffff;
}
/* K9: Kopf des Monitors mit dem Logo; Listen und Tabs wie im Chatfenster. */
#OpenMcpCadA QLabel#titel { font-size: 14px; font-weight: 600; }
/* K10: der Name in der Titelleiste des Mini-Monitors, die Knoepfe in
   seiner Karte knapper (240 px Breite). */
#OpenMcpCadA QLabel#titel_klein { font-size: 12px; font-weight: 600; }
#OpenMcpCadA QWidget#karte QPushButton#primaer { padding: 6px 12px; }
#OpenMcpCadA QWidget#karte QPushButton#trennen { padding: 6px 10px; }
#OpenMcpCadA QWidget#karte QPushButton#flach { padding: 4px 6px; }
#OpenMcpCadA QTabBar::tab:hover { color: %(text)s; }
#OpenMcpCadA QTabBar::tab { padding: 6px 9px; }
/* Rollleisten schmal und rund wie in den Chat-Apps, ohne Pfeilknoepfe. */
#OpenMcpCadA QScrollBar:vertical {
    background: transparent; width: 9px; margin: 2px 1px 2px 0px;
}
#OpenMcpCadA QScrollBar::handle:vertical {
    background: #cfcfd4; border-radius: 4px; min-height: 28px;
}
#OpenMcpCadA QScrollBar::handle:vertical:hover { background: #b5b5bb; }
#OpenMcpCadA QScrollBar::add-line:vertical,
#OpenMcpCadA QScrollBar::sub-line:vertical { height: 0px; }
#OpenMcpCadA QScrollBar::add-page:vertical,
#OpenMcpCadA QScrollBar::sub-page:vertical { background: transparent; }
#OpenMcpCadA QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid #c9c9cd; border-radius: 4px;
    background: %(karte)s;
}
#OpenMcpCadA QCheckBox::indicator:checked {
    background: %(blau)s; border-color: %(blau)s;
}
#OpenMcpCadA QListWidget::item:hover { background: #f2f2f5; border-radius: 6px; }
#OpenMcpCadA QPushButton {
    background: %(karte)s; color: %(text)s; border: 1px solid %(rahmen)s;
    border-radius: 8px; padding: 6px 12px; font-size: 12px;
}
#OpenMcpCadA QPushButton:hover { border-color: #c9c9cd; }
#OpenMcpCadA QPushButton:disabled { color: #b0b0b5; }
#OpenMcpCadA QPushButton#primaer {
    background: %(blau)s; color: #ffffff; border: none; font-weight: 600;
    padding: 7px 16px;
}
#OpenMcpCadA QPushButton#primaer:hover { background: #0062c4; }
#OpenMcpCadA QPushButton#primaer:disabled { background: #a8cff5; }
#OpenMcpCadA QPushButton#senden {
    background: %(blau)s; color: #ffffff; border: none; border-radius: 16px;
    font-size: 15px; font-weight: 600; padding: 0px;
}
#OpenMcpCadA QPushButton#senden:disabled { background: #c8c8cd; }
#OpenMcpCadA QPushButton#symbol { padding: 4px 8px; font-size: 14px; }
/* Modell-Knopf, solange die Liste fehlt oder veraltet ist: dieselbe Farbe
   wie ein Hauptknopf, damit man sieht, dass hier zuerst etwas zu tun ist. */
#OpenMcpCadA QPushButton#hinweis {
    background: %(blau)s; color: #ffffff; border: none; font-weight: 600;
    padding: 6px 10px;
}
#OpenMcpCadA QPushButton#hinweis:hover { background: #0062c4; }
#OpenMcpCadA QPushButton#hinweis:disabled { background: #a8cff5; }
/* K9: der Chat-Knopf im kompakten Monitor — deutlich, aber nicht so laut
   wie "Verbinden". Wartet eine Freigabe, heisst er "hinweis" (blau). */
#OpenMcpCadA QPushButton#chatknopf {
    background: #e8f1fd; color: %(blau)s; border: 1px solid #b9d3f5;
    font-weight: 600; padding: 6px 12px;
}
#OpenMcpCadA QPushButton#chatknopf:hover { background: #dbe9fb; }
#OpenMcpCadA QPushButton#leiste {
    background: transparent; border: none; color: %(neben)s; font-size: 13px;
    padding: 0px; border-radius: 4px;
}
#OpenMcpCadA QPushButton#leiste:hover { background: #e8e8ec; color: %(text)s; }
/* K3 (2026-09-27): Bedienteile, die aussehen wie Text und ueber der Maus
   einen grauen, runden Hintergrund bekommen (Leiste unter der Eingabe). */
#OpenMcpCadA QPushButton#flach {
    background: transparent; border: none; color: %(text)s;
    padding: 4px 8px; border-radius: 8px; font-size: 12px;
}
#OpenMcpCadA QPushButton#flach:hover { background: #e6e6ea; }
#OpenMcpCadA QPushButton#flach:pressed { background: #d9d9de; }
#OpenMcpCadA QPushButton#flach:disabled { color: #b0b0b5; }
/* Der Ordnerknopf: Fuellung wie der Chat, die Umrandung sagt, dass er
   nicht zum Gespraech gehoert. */
#OpenMcpCadA QPushButton#ordner {
    background: %(grund)s; border: 1px solid #c9c9cd; border-radius: 8px;
    padding: 4px 10px; font-size: 12px;
}
#OpenMcpCadA QPushButton#ordner:hover { background: #e6e6ea; }
#OpenMcpCadA QPushButton#chip_knopf {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 9px;
    padding: 1px 8px; font-size: 11px; color: %(neben)s;
}
#OpenMcpCadA QPushButton#chip_knopf:hover { border-color: #c9c9cd; }
#OpenMcpCadA QFrame#eingaberahmen {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 16px;
}
#OpenMcpCadA QFrame#eingaberahmen QPlainTextEdit#eingabe {
    border: none; background: transparent; padding: 4px 2px;
}
#OpenMcpCadA QFrame#aufklapper {
    background: %(karte)s; border: 1px solid #d2d2d7; border-radius: 12px;
}
#OpenMcpCadA QFrame#aufklapper QPushButton#eintrag {
    background: transparent; border: none; text-align: left;
    padding: 6px 10px; border-radius: 8px; font-size: 12px;
}
#OpenMcpCadA QFrame#aufklapper QPushButton#eintrag:hover {
    background: #ececf0;
}
#OpenMcpCadA QFrame#aufklapper QPushButton#eintrag:disabled {
    color: #b0b0b5;
}
#OpenMcpCadA QFrame#zeile { border-radius: 8px; }
#OpenMcpCadA QFrame#zeile:hover { background: #ececf0; }
#OpenMcpCadA QLabel#zeile_titel { font-weight: 600; }
#OpenMcpCadA QFrame#trenner { background: %(rahmen)s; border: none; }
#OpenMcpCadA QTabWidget::pane { border: none; }
#OpenMcpCadA QTabBar::tab {
    background: transparent; color: %(neben)s; padding: 6px 12px;
    border-bottom: 2px solid transparent; font-size: 12px;
}
#OpenMcpCadA QTabBar::tab:selected {
    color: %(text)s; border-bottom: 2px solid %(blau)s; font-weight: 600;
}
#OpenMcpCadA QListWidget, #OpenMcpCadA QScrollArea {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 10px;
}
#OpenMcpCadA QListWidget::item { padding: 5px 4px; }
#OpenMcpCadA QListWidget#chatliste::item { padding: 5px 0px; }
/* K5: der lesbare Verlauf. Die eigene Nachricht rechts in Blau, die
   Antwort mit ✦ in Grau, Schritte und Zeit zurueckhaltend. */
#OpenMcpCadA QLabel#blase_ich {
    background: #e3eefc; border-radius: 12px; padding: 6px 10px;
}
#OpenMcpCadA QLabel#blase_ki {
    background: %(grund)s; border-radius: 12px; padding: 6px 10px;
}
#OpenMcpCadA QLabel#ki_marke {
    color: %(blau)s; font-size: 14px; padding-top: 4px;
}
#OpenMcpCadA QLabel#zeitlinie { color: %(neben)s; font-size: 10px; }
#OpenMcpCadA QLabel#blase_tippt {
    background: %(grund)s; border-radius: 12px; padding: 4px 12px;
    color: %(neben)s; font-size: 14px; font-weight: 600;
}
/* Die eine Zeile ueber dem Gespraech, nur wenn etwas nicht stimmt. */
#OpenMcpCadA QLabel#status {
    color: #9a4a00; background: #fff4e5; border-radius: 8px;
    padding: 4px 8px; font-size: 11px;
}
#OpenMcpCadA QLabel#schritte_kopf {
    color: %(neben)s; font-size: 11px; padding: 3px 6px; border-radius: 6px;
}
#OpenMcpCadA QLabel#schritte_kopf:hover { background: #ececf0; }
#OpenMcpCadA QLabel#schritt {
    color: %(neben)s; font-size: 11px; padding: 1px 6px 1px 0px;
}
#OpenMcpCadA QLabel#schritte_pfeil { padding: 4px 0px 0px 4px; }
#OpenMcpCadA QPushButton#neu_knopf {
    background: %(blau)s; color: #ffffff; border: none; border-radius: 11px;
    padding: 3px 12px; font-size: 11px; font-weight: 600;
}
/* Rollbereiche ohne eigenen Rahmen (S7: die Freigabe-Karten ueber der
   Eingabe). Die Regel darueber gaebe jedem QScrollArea eine weisse Karte. */
#OpenMcpCadA QScrollArea#rolle { background: transparent; border: none; }
#OpenMcpCadA QScrollArea#rolle > QWidget#qt_scrollarea_viewport,
#OpenMcpCadA QWidget#rollinhalt { background: transparent; }
#OpenMcpCadA QPlainTextEdit#eingabe {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 16px;
    padding: 8px 12px; font-size: 12px; color: %(text)s;
}
#OpenMcpCadA QComboBox, #OpenMcpCadA QLineEdit {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 8px;
    padding: 4px 8px; font-size: 12px;
}
/* K9: der Pfeil des Auswahlfelds ruhig wie die Winkel im Chat, statt des
   alten Kastens (Rueckmeldung 2026-09-28: keine Widgets im alten Stil). */
#OpenMcpCadA QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none;
}
/* Der Pfeil selbst (`QComboBox::down-arrow`) steht in `_qss()`: als
   Symbol "chevron-down" aus einer PNG-Datei. Der Rahmen-Trick
   (Dreieck aus Raendern) zeichnete Qt als schwarzen Balken (Gegenpruefung
   K12, Bild 06). */
#OpenMcpCadA QSlider::groove:horizontal {
    height: 4px; background: %(rahmen)s; border-radius: 2px;
}
#OpenMcpCadA QSlider::handle:horizontal {
    background: %(blau)s; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px;
}
/* K11 (Rueckmeldung 2026-10-02: "Aufträge, Briefkasten sehen zu aehnlich
   aus wie der Chat selbst"): das Steuerfenster ist ein PROTOKOLL, kein
   Gespraech. Abschnitte mit einem Kopf wie die Gruppen der Hinweise statt
   weisser Karten, Listen flach auf dem Grund mit abwechselnd hinterlegten
   Zeilen, keine Blasen, kein runder Senden-Knopf. Die Typregel oben
   (`QListWidget, QScrollArea` = weisse Karte) schlaegt diese nicht: hier
   haengt zusaetzlich der Name dran. */
#OpenMcpCadA QTabWidget#reiter QTabBar::tab { padding: 6px 8px; }
#OpenMcpCadA QLabel#abschnitt {
    color: %(neben)s; font-size: 11px; font-weight: 700;
    padding: 6px 2px 2px 2px;
}
/* Gegenpruefung K12: ein aufklappbarer Abschnittskopf sieht aus wie ein
   fester ("Letzte Aufträge" wie "Notizen für die KI"). */
#OpenMcpCadA QPushButton#abschnitt_knopf {
    color: %(neben)s; font-size: 11px; font-weight: 700;
    padding: 6px 2px 2px 2px; border: none; background: transparent;
    text-align: left;
}
#OpenMcpCadA QPushButton#abschnitt_knopf:hover { color: %(text)s; }
/* Die Titel der Karten (Einstellungen: Chat, Verbindung, Zeichenmodus,
   Technik-Details) — alle gleich, groesser als ein Feldname. */
#OpenMcpCadA QLabel#karte_titel, #OpenMcpCadA QPushButton#karte_titel {
    color: %(text)s; font-size: 13px; font-weight: 600;
    padding: 0px; border: none; background: transparent; text-align: left;
}
#OpenMcpCadA QListWidget#protokoll, #OpenMcpCadA QScrollArea#protokoll {
    background: %(grund)s; alternate-background-color: %(karte)s;
    border: none; border-top: 1px solid %(rahmen)s;
    border-bottom: 1px solid %(rahmen)s; border-radius: 0px;
}
#OpenMcpCadA QListWidget#protokoll::item {
    padding: 3px 4px; border-radius: 0px;
}
#OpenMcpCadA QListWidget#protokoll::item:hover {
    background: #ececf0; border-radius: 0px;
}
#OpenMcpCadA QScrollArea#protokoll > QWidget#qt_scrollarea_viewport,
#OpenMcpCadA QWidget#protokoll_innen { background: transparent; }
#OpenMcpCadA QWidget#protokoll_zeile { background: %(grund)s; }
#OpenMcpCadA QWidget#protokoll_zeile[ungerade="ja"] {
    background: %(karte)s;
}
#OpenMcpCadA QLabel#protokoll_zeit {
    color: %(neben)s; font-size: 11px;
}
#OpenMcpCadA QLabel#protokoll_chip {
    border-radius: 8px; padding: 1px 8px; font-size: 10px; font-weight: 600;
}
#OpenMcpCadA QWidget#hinnen { background: transparent; }
""" % FARBEN

#: Der Pfeil der Auswahlfelder als Bild (Pfad oder None), einmal je Prozess.
_PFEIL = {}


def _pfeil_datei():
    """Das Symbol "chevron-down" als PNG in Temp — fuer `image: url()` im
    Stylesheet (Qt nimmt dort nur Dateien). Gerendert ueber
    `omcad_a_symbole` (QtSvg), gespeichert als PNG (ohne Bild-Plugin).
    Ohne QtSvg oder ohne Schreibrecht None: dann zeichnet Qt seinen
    eigenen Pfeil. Wirft nie. -> Pfad mit "/" oder None."""
    if "pfad" in _PFEIL:
        return _PFEIL["pfad"]
    pfad = None
    try:
        S = _symbol_modul()
        pm = S.pixmap(SYMBOLE["auf"][0], FARBEN["neben"], 12) \
            if S is not None else None
        if pm is not None and not pm.isNull():
            ordner = os.path.join(tempfile.gettempdir(), "open_mcp_cad_ui")
            os.makedirs(ordner, exist_ok=True)
            ziel = os.path.join(ordner, "pfeil_unten_%d.png" % os.getpid())
            if pm.save(ziel, "PNG"):
                pfad = ziel.replace("\\", "/")
    except Exception:                                  # noqa: BLE001
        pfad = None
    _PFEIL["pfad"] = pfad
    return pfad


def _qss():
    """Das Stylesheet des Docks samt der Regeln des Hinweis-Boards.

    Die Regeln des Boards stehen bei seinem Code, nicht hier — sonst waeren
    Aussehen und Aufbau in zwei Dateien verteilt. Sie wirken trotzdem nur
    im Dock, weil `setStyleSheet` immer auf dem Dock-Inhalt gerufen wird und
    von dort nach unten vererbt.
    """
    try:
        basis = QSS + _hinweis_modul().QSS
    except Exception:                                  # noqa: BLE001
        # Ohne die Zusatzregeln sieht das Board schlicht aus — aber das Dock
        # geht auf. Ein fehlendes Stylesheet darf nie das Fenster kosten.
        basis = QSS
    pfeil = _pfeil_datei()
    if pfeil:
        basis += ('\n#OpenMcpCadA QComboBox::down-arrow { image: url("%s"); '
                  'width: 12px; height: 12px; }\n' % pfeil)
    return basis


# Zustand -> (Anzeigetext, Farbe der Pille)
PILLE = {
    None:                 ("Aus", "#8e8e93"),
    "stopped":            ("Aus", "#8e8e93"),
    "starting":           ("Verbindet …", FARBEN["blau"]),
    "ready":              ("Bereit", FARBEN["gruen"]),
    # K10/K11: kurz, die Pille steht auch in der einzeiligen Leiste
    # ("Zeichnet" statt "Bearbeitet Modell" ueber zwei Zeilen).
    "busy_read":          ("Liest", FARBEN["blau"]),
    "busy_write":         ("Zeichnet", FARBEN["blau"]),
    "paused":             ("Pausiert", FARBEN["orange"]),
    "stopping_after_job": ("Trennt nach Auftrag", FARBEN["orange"]),
    "error":              ("Störung", FARBEN["rot"]),
}


#: Name des Ankers in `sys.modules`. Ein fester Name und KEIN Modul auf der
#: Platte: der Eintrag ueberlebt jedes frische Laden dieses Moduls.
ANKER = "omcad_prozess_dock"


def _zustand_vorgabe():
    return {"dock": None, "inhalt": None, "dienst": None, "kern": None,
            "timer": None, "w": {}, "kern_laden": None, "cfg_bauen": None,
            # Ablage der Notizen: Pfad der Cadwork-Datei, Zieldatei, und
            # woraufhin zuletzt geladen wurde (damit ein Dokumentwechsel
            # die richtigen Notizen holt).
            "dok_pfad": None, "ablage": None, "geladen_fuer": None,
            "pfad_job": None, "zuletzt_gesichert": 0,
            "speicher_stempel": None,
            # Der Chat: `chat` traegt Prozess, Leserthread, Ereignisse und
            # offene Freigaben (s. omcad_a_chat.py). `chat_cache` puffert
            # die Sitzungsliste ueber (Groesse, mtime) — kalt kostet sie
            # 17 ms, warm 1 ms, und nur warm darf sie in den Qt-Takt.
            "chat": {}, "chat_cache": {}, "chat_gezeigt": -1,
            "chat_takt": None,
            # K12 (Rueckmeldung 2026-10-07): EIN Fenster (`fenster`, dazu
            # `dock` als derselbe Name fuer alten Code). Gemerkt nur in
            # dieser Cadwork-Sitzung (hier im Anker): Zustand (pille, offen,
            # angedockt), der Ort des Kopfs (rechte Kante, Oberkante), die
            # Groesse des offenen und die Breite des angedockten Fensters,
            # das Segment, ob die Hinweise offen sind, ob der Nutzer greift.
            # Die naechste Sitzung beginnt mit der Pille oben rechts.
            "fenster": None, "fenster_zustand": PILLE_Z, "pille_ort": None,
            "offen_groesse": None, "offen_soll": None,
            "angedockt_bereich": None, "angedockt_breite": None,
            "segment": "chat", "hinweise_offen": False, "hinweise_zahl": 0,
            "fenster_gezogen": False, "fenster_soll": None,
            "fenster_versteckt_selbst": False,
            # Die Arbeitsanzeige (K12, ehemals "Open MCP CAD zeichnet …"):
            # ihr Fenster, ihr Ort (vom Nutzer gezogen), der Stand des
            # laufenden Kern-Laufs (`anzeige_lauf`, vom Haken des Kerns).
            "anzeige": None, "anzeige_ort": None, "anzeige_gezogen": False,
            "anzeige_soll": None, "anzeige_lauf": {},
            # K10: Zeilen ueber die Fenster fuers Log, bis es eins gibt, und
            # der Stand des Nachsehens nach dem Zeigen.
            "ort_zeilen": [], "ort_nachgesetzt": {},
            # S7/S8: die Meldung an der Eingabe (Text, Art) und die Liste
            # eines Chats, dessen Verlauf "Neuer Chat" geleert hat.
            "chat_meldung": None, "verlauf_verworfen": None,
            # Etappe D (S9): die bisherigen Chats des Arbeitsordners. Gelesen
            # im Nebenthread (`_liste_holen`); `liste_anlass` zaehlt jeden
            # Wunsch nach einer frischen Liste, `liste_stand` den, dessen
            # Ergebnis gilt. `sitzung_offen`: ein Chat aus der Liste, den
            # die naechste Nachricht fortsetzt.
            "liste": None, "liste_ordner": None, "liste_anlass": 1,
            "liste_stand": 0, "liste_laeuft": False, "liste_gezeigt": None,
            "sitzung_offen": None, "chat_war_an": False,
            "ordner_dialog": None,
            # Fassung des Docks (FORM) und die Meldung des Docks, die bis
            # `fehler_bis` (time.monotonic) vor dem Takt geschuetzt ist.
            "form": None, "fehler_dock": "", "fehler_bis": 0.0}


def _zustand():
    """Der Zustand des Docks — EINER je Prozess, wie oft auch neu geladen.

    Gelesen in dieser Reihenfolge:
      1. `sys.modules[ANKER]` — ueberlebt jedes frische Laden;
      2. das Attribut `_omcad_a_prototyp` an der QApplication — dort lag
         der Zustand bis 2026-09-25. Ein noch laufendes Dock einer aelteren
         Fassung wird so gefunden und uebernommen.

    WARUM NICHT MEHR NUR DIE QApplication. In Cadwork gehoert sie C++. Ihr
    Python-Wrapper lebt nur, solange ihn jemand haelt; danach liefert
    `QApplication.instance()` einen NEUEN Wrapper — ohne das Attribut.
    Gemessen 2026-09-25 in PyQt6 6.11 mit einer C++-eigenen QApplication
    (`sip.transferto(app, None)`): neuer Wrapper, Attribut weg. Ein Klick
    danach baute ein zweites Dock und startete einen zweiten Dienst — so
    geschehen am 2026-09-25 (C und D im selben Cadwork, gleiche Sekunde).
    """
    import types
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("keine QApplication — laeuft das in Cadwork?")
    anker = sys.modules.get(ANKER)
    z = getattr(anker, "z", None)
    if z is None:
        z = getattr(app, "_omcad_a_prototyp", None)
    if z is None:
        z = _zustand_vorgabe()
    else:
        # Ein Zustand aus einer AELTEREN Fassung (Update ohne Neustart)
        # kennt die neueren Schluessel nicht: nachtragen, nie ueberschreiben.
        for schluessel, wert in _zustand_vorgabe().items():
            z.setdefault(schluessel, wert)
    if anker is None:
        anker = sys.modules.setdefault(ANKER, types.ModuleType(ANKER))
    anker.z = z
    app._omcad_a_prototyp = z
    return z


# --- Einstieg -------------------------------------------------------------

def oeffnen(kern_laden, cfg_bauen, verbinden=False):
    """Vom Plugin-Klick gerufen: das Fenster zeigen und, mit `verbinden`,
    verbinden.

    K12 (Rueckmeldung 2026-10-07): es gibt genau EIN Fenster. Der erste
    Klick einer Sitzung zeigt es als Pille oben rechts (nur der Kopf);
    steht es schon, holt der Klick es nach vorn (Zustand bleibt) — und ein
    geschlossenes kommt als Pille zurueck. Weicht die Fassung des
    gebauten Fensters ab (Update ohne Cadwork-Neustart, `FORM`), wird es
    neu gebaut; Dienst und Chat bleiben.

    `kern_laden` und `cfg_bauen` kommen aus dem Einstieg, damit dieser
    Controller nichts ueber Pfade und Portnummern wissen muss.

    `verbinden=True` rufen beide Einstiege (2026-09-22: ein Klick auf den
    Menueeintrag soll genuegen). Verbunden wird ueber `_verbinden` —
    denselben Weg wie der Knopf, mit atomarer Reservierung, der Wahl im
    Dock, ohne Ausweichen und ohne zweiten Listener neben einem laufenden
    Dienst. ERST das Fenster, DANN verbinden: `_verbinden` schreibt in
    Knopf und Meldezeile. Der Default bleibt False, damit `test_a_live` das
    Fenster ohne Netz bauen kann.
    """
    z = _zustand()
    # Immer die FRISCHEN Lader merken — nach einem Plugin-Update zeigen sie
    # auf den neuen Kern, das alte Dock darf trotzdem bestehen bleiben.
    z["kern_laden"] = kern_laden
    z["cfg_bauen"] = cfg_bauen

    if (z.get("dock") is not None or z.get("fenster") is not None
            or any(z.get(k) is not None for k in ALTE_FENSTER)) \
            and z.get("form") != FORM:
        # Gebaut von einer ANDEREN Fassung dieses Moduls (Update ohne
        # Cadwork-Neustart, s. FORM oben): neu bauen statt hineinzugreifen.
        _dock_abbauen(z)
    if z.get("fenster") is not None:
        try:
            z["fenster"].isVisible()     # geloescht -> RuntimeError
            _sicher(lambda: _fenster_aktion(z, "klick"), "Fenster zeigen")
            _monitor_starten(z)          # laeuft er schon, passiert nichts
            _auffrischen(z)
        except RuntimeError:
            # Qt-Objekt wurde geloescht (Cadwork hat aufgeraeumt) — neu bauen.
            _dock_abbauen(z)
    if z.get("fenster") is None:
        _fenster_bauen(z)
        _monitor_starten(z)
        _auffrischen(z)
    if verbinden:
        _verbinden(z)
    return z["dienst"]


def _dock_abbauen(z):
    """Die Oberflaeche abraeumen — Dienst, Kern und Chat bleiben, wie sie sind.

    Drei Anlaesse: Cadwork hat das Fenster geloescht (die Qt-Objekte sind
    dann schon tot), es stammt aus einer anderen Fassung (`FORM`), oder es
    ist ein Fenster von K9-K11 (Leiste `OpenMcpCadMini`, Steuerfenster
    `OpenMcpCadADock`, Chat-Dock `OpenMcpCadChatDock`, das Dock "Aufträge"
    von K10): dann raeumt dieser Abbau sie und ihre Merker weg (Update ohne
    Cadwork-Neustart, Spezifikation 1.6). Die Timer zuerst: sie riefen
    sonst weiter in Widgets, die gerade verschwinden. Ein laufender Chat
    wird NICHT beendet — `z["chat"]` bleibt, das neue Fenster zeigt ihn.
    Was der Anker fuer die Sitzung merkt (Zustand, Ort, Segment), bleibt.
    """
    for schluessel in ("timer", "chat_takt"):
        takt, z[schluessel] = z.get(schluessel), None
        if takt is not None:
            try:
                takt.stop()
            except RuntimeError:              # mit dem Dock schon geloescht
                pass
    # Der Haken der Arbeitsanzeige gehoert zu den Widgets dieser Fassung;
    # die neue setzt ihren eigenen (`_fenster_bauen`). Das Loeschen des
    # alten Fensters (`deleteLater`) gilt dann nicht mehr als "Cadwork hat
    # aufgeraeumt" (`_fenster_zerstoert`).
    z["fenster_marke"] = None
    _haken_weg(z)
    # Wo das schwebende Fenster stand — der Neubau stellt es dorthin.
    try:
        if z.get("fenster") is not None \
                and _fenster_zustand_ist(z) == PILLE_Z:
            _pille_ort_merken(z)
    except Exception:                                  # noqa: BLE001
        pass
    gesehen = set()
    for schluessel in ("aufklapper", "anzeige", "fenster", "dock") \
            + ALTE_FENSTER:
        alt = z.get(schluessel)
        if schluessel in ("fenster", "dock", "anzeige", "aufklapper") \
                or schluessel in ALTE_FENSTER:
            z[schluessel] = None
        if alt is None or id(alt) in gesehen:
            continue
        gesehen.add(id(alt))
        z["fenster_versteckt_selbst"] = True
        try:
            alt.hide()
            alt.deleteLater()
        except RuntimeError:
            pass
        finally:
            z["fenster_versteckt_selbst"] = False
    for schluessel in ALTE_SCHLUESSEL:
        z.pop(schluessel, None)
    z["w"] = {}
    z["form"] = None
    # Ein Nachsehen, das noch aussteht, gilt dem alten Fenster (K10).
    z["ort_nachgesetzt"] = {}


# --- Verbinden / Trennen --------------------------------------------------

def _steckplatz_reservieren(client, wunsch=None, kern=None):
    """Reserviert den gewaehlten oder ersten freien Steckplatz ATOMAR.

    Liefert `(instanz, port, socket)` — der Socket ist bereits gebunden und
    wird an `kern.serve(..., reserved_socket=...)` durchgereicht.

    WARUM BINDEN UND NICHT FRAGEN. Hier stand eine Pruefung per `ping`:
    antwortet auf dem Port ein Steckplatz? Das beantwortet die falsche
    Frage gleich zweimal. Ein Port kann von etwas ganz anderem belegt sein,
    das nicht auf `ping` antwortet — dann galt er als frei und das Binden
    scheiterte hinterher. Und zwischen der Antwort und dem Binden liegt ein
    Moment, in dem ein zweites Cadwork denselben Port nehmen kann.

    Binden IST die Probe. Gelingt es, gehoert der Port uns — es gibt kein
    Dazwischen mehr.

    ⚠ SO_EXCLUSIVEADDRUSE ist unter Windows noetig: ohne diese Option kann
    ein zweites `bind()` auf denselben Port gelingen, und beide glauben,
    sie haetten ihn. (Uebernommen aus Kern 2.15.)

    MIT WUNSCH (2026-08-15: "man soll auswaehlen koennen welche bridge
    man verbinden will"): genau der, und sonst gar keiner. Auf einen
    belegten Steckplatz still auszuweichen waere schlimmer als eine
    Fehlermeldung — dann zeichnete man in eine andere Datei als gemeint,
    und genau davor schuetzt die ganze Steckplatz-Zuordnung.

    OHNE WUNSCH: der erste freie. Die benannten Steckplaetze zuerst (ihre
    Namen stehen in bestehenden Host-Konfigurationen), danach der weitere
    Bereich des Kerns — so ist die Zahl der Leitungen nicht an die Zahl der
    benannten Plaetze gebunden.
    """
    kandidaten = _alle_steckplaetze(client, kern)
    if wunsch:
        # Der Wunsch darf seit 2026-09-23 JEDER Port des Kerns sein, nicht
        # nur A-F — das Dropdown bietet sie alle an. Ausgewichen wird nie.
        kandidaten = [(i, p) for i, p in kandidaten if i == wunsch]

    for instanz, port in kandidaten:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((client.HOST, port))
            return instanz, port, sock
        except OSError as exc:
            sock.close()
            # Nur "belegt" heisst weitersuchen. Alles andere (etwa fehlende
            # Rechte auf ein ganzes Netzsegment) ist ein echter Fehler und
            # soll nicht als "alle Plaetze belegt" erscheinen.
            if exc.errno not in (13, 48, 98, 10013, 10048):
                raise
    return None, None, None


def _alle_steckplaetze(client, kern=None):
    """Alle waehlbaren Steckplaetze: die benannten, dahinter der Kernbereich.

    Die benannten zuerst (ihre Namen stehen in Host-Konfigurationen), dann
    `PORT_VON..PORT_BIS` des Kerns — `kennung_fuer` gibt jedem Port seinen
    Namen. Ohne Kern (oder einen ohne Bereich) nur die benannten.
    """
    kandidaten = list(client.STECKPLAETZE)
    if kern is not None and hasattr(kern, "PORT_VON"):
        bekannt = {p for _i, p in kandidaten}
        kandidaten += [(kern.kennung_fuer(p), p)
                       for p in range(kern.PORT_VON, kern.PORT_BIS + 1)
                       if p not in bekannt]
    return kandidaten


def _verbinden(z):
    """Verbindet — auf dem gewaehlten Steckplatz, sonst dem ersten freien.

    DER EINZIGE WEG IN DEN DIENST: Knopf, Karte und Plugin-Klick rufen alle
    hierher. Die Rueckgabe sagt, was geschah (die Oberflaeche liest den
    Zustand selbst, die Gates brauchen sie):
      "laeuft"     es lief schon — nichts gestartet, kein zweiter Listener
      "verbunden"  neu gestartet
      "belegt"     der gewaehlte bzw. jeder Steckplatz ist belegt
      "fehler"     etwas anderes ging schief; steht in der Hinweiszeile

    "Es lief schon" heisst: in DIESEM PROZESS, nicht nur in diesem Dock.
    Der Kern fuehrt seit 2.17 ein Buch darueber (`dienst_im_prozess`); ein
    laufender Dienst, den dieses Dock nicht kennt, wird uebernommen statt
    daneben ein zweiter gestartet. Und `kern.serve` startet ohnehin keinen
    zweiten — gibt es einen, liefert es ihn zurueck.

    Fehler beim Laden, Konfigurieren und Reservieren werden hier gefangen.
    Vorher flogen sie aus dem Knopf-Slot; seit auch der Plugin-Klick
    hierher fuehrt, landeten sie sonst im Einstieg.
    """
    if z["dienst"] is not None and not z["dienst"].beenden:
        return "laeuft"                          # laeuft schon
    # Ein neuer Versuch: die Meldung des vorigen gilt nicht mehr.
    _fehler_quittieren(z)
    try:
        kern = z["kern_laden"]()
        im_prozess = getattr(kern, "dienst_im_prozess", None)
        laufend = im_prozess() if im_prozess is not None else None
    except Exception as exc:                      # noqa: BLE001
        _fehler_zeigen(z, "Verbinden nicht möglich: %s" % exc)
        return "fehler"
    if laufend is not None:
        _uebernehmen(z, laufend, kern)
        _auffrischen(z)
        return "laeuft"
    try:
        cfg = z["cfg_bauen"](kern)
        client = _verbindungen_client()
        wunsch = None
        feld = z["w"].get("steckplatz_wahl")
        if feld is not None:
            wunsch = feld.currentData()          # None = "automatisch"
        instanz, port, reservierung = _steckplatz_reservieren(
            client, wunsch, kern)
    except Exception as exc:                      # noqa: BLE001
        _fehler_zeigen(z, "Verbinden nicht möglich: %s" % exc)
        return "fehler"
    if instanz is None:
        if wunsch:
            _fehler_zeigen(z, "Steckplatz %s ist belegt. Ein anderes Cadwork "
                              "hält ihn — dort trennen, oder hier einen "
                              "anderen wählen." % wunsch)
        else:
            _fehler_zeigen(z, "Alle %d Steckplätze sind belegt. Trenne in "
                              "einem anderen Cadwork die Verbindung."
                           % (kern.PORT_BIS - kern.PORT_VON + 1))
        return "belegt"
    ergebnis = "verbunden"
    try:
        cfg.instanz, cfg.port = instanz, port
        cfg.anzeigename = "Open MCP CAD %s | Port %d" % (instanz, port)
        # Die Logdatei folgt dem Steckplatz. Ohne diese Zeile schrieben zwei
        # Cadwork-Fenster in dieselbe Datei, und die Zeilen dort waeren
        # keiner Instanz mehr zuzuordnen. (Aus Kern 2.15.)
        cfg.log_datei = r"C:\Users\Public\OpenMcpCad_%s.log" % instanz
        z["instanz"] = instanz
        # Der Kern soll NICHT sein eigenes Fenster aufmachen — das Dashboard
        # hier ist die Oberflaeche. Ohne das haette man zwei Fenster.
        cfg.fenster = False
        # Kein stiller Rueckfall auf den Hauptthread-Antrieb: der hielte
        # Cadwork an, und wer nur das Plugin angeklickt hat, merkt nicht,
        # warum. Lieber scheitern und es in der Hinweiszeile sagen.
        cfg.require_qtimer = True
        z["kern"] = kern
        z["w"]["primaer"].setEnabled(False)
        z["w"]["primaer"].setText("Verbindet …")
        _pille_setzen(z, "starting")
        z["dienst"] = kern.serve(cfg, reserved_socket=reservierung)
        if getattr(getattr(z["dienst"], "cfg", None), "port", port) != port:
            # Der Kern hat abgelehnt: in diesem Prozess lief schon einer
            # (etwa ein Klick, der mitten in diesem Start ausgefuehrt
            # wurde). Die Reservierung hat er freigegeben.
            _uebernehmen(z, z["dienst"], kern)
            ergebnis = "laeuft"
    except Exception as exc:                      # noqa: BLE001
        z["dienst"] = None
        # Der reservierte Socket gehoert uns, solange serve() ihn nicht
        # uebernommen hat. Ohne dieses Schliessen bliebe der Port belegt,
        # und der naechste Verbindungsversuch faende ihn "besetzt" — von
        # einem Steckplatz, den es gar nicht gibt.
        try:
            reservierung.close()
        except OSError:
            pass
        _fehler_zeigen(z, "Verbinden fehlgeschlagen: %s" % exc)
        ergebnis = "fehler"
    if z.get("dienst") is not None and ergebnis != "fehler":
        # Die Arbeitsanzeige dieses Docks bekommt die Laeufe (K12; nur ein
        # Kern ab 2.19 kennt den Haken).
        _sicher(lambda: _haken_setzen(z), "Arbeitsanzeige anmelden")
    if ergebnis == "verbunden":
        # Ein Fehler hier (etwa ein kaputtes chat.json) kostet nie das
        # Verbinden: der Dienst laeuft dann mit der Vorgabe des Kerns.
        _sicher(lambda: _zeichenmodus_wiederherstellen(z),
                "Zeichenmodus wiederherstellen")
    _auffrischen(z)
    return ergebnis


def _uebernehmen(z, laufend, kern):
    """Einen Dienst, der in diesem Prozess schon laeuft, in dieses Dock holen.

    Sein Kern-Modul, wenn er es kennt: `_trennen` und `_auftrag` brauchen
    den Kern, der den Dienst gestartet hat, nicht den gerade frisch
    geladenen. Die Arbeitsanzeige dieses Docks bekommt seine Laeufe
    (`_haken_setzen`, K12).
    """
    z["dienst"] = laufend
    z["kern"] = getattr(laufend, "kern_modul", None) or kern
    z["instanz"] = getattr(laufend.cfg, "instanz", None)
    _haken_setzen(z)


def _trennen(z):
    """Trennt sicher — ein laufender Auftrag wird NIE hart abgebrochen."""
    d = z["dienst"]
    if d is None or d.beenden:
        return
    # Der Chat haengt an Steckplatz UND Datei dieser Verbindung. Bleibt er
    # nach dem Trennen stehen, zeigte er auf einen Riegel, den es nicht mehr
    # gibt — also mit beenden. Ein halbfertiger Zug geht dabei verloren; das
    # ist der Preis und steht offen im Uebergabedokument.
    # Sichttest 2026-08-09: "ich konnte trennen, obwohl die
    # Claude-Sitzung am Laufen war". Genau dieselbe Rueckfrage wie am
    # Beenden-Knopf — sonst gibt es einen zweiten Weg, der stillschweigend
    # abwuergt, und der ist immer der, den man erwischt.
    try:
        if (z.get("chat") or {}).get("an") and not _chat_ende_geklaert(z):
            # "Nach dem Zug beenden" heisst: auch das Trennen wartet. Der
            # Qt-Takt holt es nach, sobald der Chat wirklich aus ist.
            z["trennen_nach_chat"] = bool(
                (z.get("chat") or {}).get("beenden_nach_zug"))
            return
    except Exception as exc:                           # noqa: BLE001
        _melden("Trennen: Chat klären", exc)
    z["trennen_nach_chat"] = False
    # Die Arbeitsanzeige geht sofort (K12); der letzte Auftrag rechnet ohne
    # sie fertig — ein stiller Haken haelt auch das Fenster des Kerns fern.
    cfg = getattr(d, "cfg", None)
    if cfg is not None and getattr(cfg, "lauf_anzeige", None) is not None:
        cfg.lauf_anzeige = _haken_still
    # Wie das × der Anzeige: weg bis zum naechsten Lauf — sonst holte sie
    # der Takt gleich wieder hervor, solange der letzte Auftrag noch laeuft
    # (Gegenpruefung K12, L103).
    _anzeige_weg(z, nutzer=True)
    if d.zustand in getattr(z["kern"], "BESCHAEFTIGT", ("busy_read",
                                                        "busy_write")):
        # Genau der vorhandene sichere Ablauf: laufenden Auftrag fertig
        # rechnen lassen, wartende verwerfen, danach beenden.
        with d.sperre:
            d.beenden_nach_auftrag = True
        z["kern"]._warteschlange_verwerfen(d, "Trennen nach dem Auftrag")
    else:
        with d.sperre:
            d.beenden_nach_auftrag = False
        d.beenden = True          # der Qt-Takt raeumt auf und stoppt sauber
    _auffrischen(z)


def _auftrag(z, methode, params, beschreibung):
    """Modell-Arbeit ueber DIESELBE Warteschlange wie die KI — nie direkt.

    cwapi3d ist nicht thread-sicher, und mitten in einen laufenden Auftrag
    hineinzurufen waere genau der Wiedereintritt, der frueher Cadwork zum
    Absturz gebracht hat.
    """
    d = z["dienst"]
    kern = z["kern"]
    if d is None or d.beenden or kern is None:
        return
    meta = kern.AuftragsMeta(methode, dict(params, description=beschreibung,
                                           client_label="Open MCP CAD A"))
    d.job_queue.put(kern.Job(None, methode, params, meta))


# --- Oberflaeche: das EINE Fenster (K12, Rueckmeldung 2026-10-07) -----------
# Rueckmeldung des Maintainers nach dem Test von K11 in Cadwork: "es sollte
# nur eine Anzeige mehr geben, Chat und Monitor vereint, und ganz oben
# sollte es immer etwa so aussehen wie das ganz kleine Pop-up" (die Leiste,
# Bild 8). "Das mittlere Pop-up (das Steuerfenster) will ich nicht mehr."
# "Wenn man auf Vergroessern klickt, dockt es rechts an, und dann ist es
# simpel: man kann direkt chatten oder Funktionen wie Auftraege, Briefkasten
# und Hinweise nutzen." Einstellungen "brauchts nicht in der obersten Leiste".
#
# Seit K12 gibt es genau EIN Fenster: ein QDockWidget `OpenMcpCadFenster`
# (`z["fenster"]`, dazu `z["dock"]` als derselbe Name fuer alten Code) an
# Cadworks Hauptfenster. Seine einzige Titelleiste ist der KOPF (wie die
# Leiste aus K11, in allen Zustaenden dasselbe Objekt), sein Inhalt der
# KOERPER (Kontextzeile, Segmente "Chat | Briefkasten", Hinweise,
# Seitenstapel Chat/Briefkasten/Einstellungen). Drei Zustaende
# (`z["fenster_zustand"]`):
#   pille      schwebend, nur der Kopf (Koerper versteckt)
#   offen      schwebend, Kopf + Koerper darunter (der Kopf bleibt stehen)
#   angedockt  eine eigene Spalte rechts (oder links) in Cadwork
# Der Koerper ist in "offen" und "angedockt" DASSELBE Widget: ein Wechsel
# aendert nur Sichtbarkeit des Koerpers, Schweben/Andocken und Geometrie —
# nie wird etwas umgehaengt (der laufende Chat bleibt, wie er ist).
#
# Gemessen VOR dem Bau (Spezifikation 7.5, Skript `messung_k12.py` im
# Scratchpad, PyQt6 6.11 / Qt 6.11.0, ECHTE Windows-Plattform und
# offscreen): ein schwebendes QDockWidget mit eigener Titelleiste und
# verstecktem Inhalt ist rahmenlos (FramelessWindowHint), so hoch wie der
# Kopf + 2 x 2 px (Kopf 46 -> 50), bleibt nach `show()` am Ziel, seine Ecken
# sind mit WA_TranslucentBackground durchsichtig (Bildschirm zeigt dort das
# Hauptfenster), Qt laesst es am Rand in der Groesse aendern (420 x 520 ->
# 500 x 600), und `addDockWidget(..., Horizontal)` neben einem anderen Dock
# rechts ergibt eine eigene Spalte ohne Reiter. Cadworks Qt 6.8.2 ist
# NICHT gemessen (dafuer die Zeilen "Fenster: …" im Log).
#
# Gemessen in Cadwork 2026 (2026-10-08, lesende Sonde im Prozess): ANGEDOCKT
# war das Fenster unsichtbar — Geometrie richtig (585 x 1158, sichtbar),
# auf dem Bildschirm aber verschmierte alte Bilder der 3D-Ansicht. In
# Cadwork ist jedes Dock ein natives Kindfenster (WA_NativeWindow, weil die
# 3D-Mitte nativ ist), und ein Dock, das je WA_TranslucentBackground trug,
# behaelt das Format mit Alphakanal (alphaBufferSize 8) — auch nach
# Abschalten zur Laufzeit, hide/show und Abloesen/Andocken (gemessen). Ein
# solches Kindfenster neben der nativen GL-Mitte setzt Windows nicht
# zusammen. Darum traegt das Fenster NIE WA_TranslucentBackground (in
# keinem Zustand, auch nicht kurz), fuellt seinen Grund deckend
# (autoFillBackground), und die runden Ecken der Pille und des offenen
# Fensters kommen nur schwebend aus einer Maske (`_fenster_maske`),
# angedockt ohne Maske. Nachgestellt offscreen und auf der echten
# Windows-Plattform mit einer nativen Mitte (test_a_live L115).

#: Name des Fensters (neu mit K12: kein gespeicherter Dock-Zustand von
#: K9-K11 passt darauf).
FENSTER_NAME = "OpenMcpCadFenster"
#: Objektname des Chat-Knopfs im Kopf (faellt auf, solange er so heisst;
#: bei wartender Freigabe heisst er "hinweis").
CHAT_KNOPF_NAME = "chatknopf"
#: Die drei Zustaende des Fensters.
PILLE_Z, OFFEN_Z, ANGEDOCKT_Z = "pille", "offen", "angedockt"
FENSTER_ZUSTAENDE = (PILLE_Z, OFFEN_Z, ANGEDOCKT_Z)
#: Die beiden Segmente des Koerpers (dazu die Einstellungsseite, kein
#: Segment).
SEGMENTE = ("chat", "briefkasten")
#: Der Kopf: so hoch (mit 2 px Rand), Knoepfe so hoch. Schwebend kommt der
#: Rahmen des Docks dazu (2 x 2 px, gemessen) -> 44 px.
KOPF_HOEHE = 40
KOPF_KNOPF_HOEHE = 28
#: Das schwebende offene Fenster: so breit (mindestens), so hoch mindestens,
#: so weit vom unteren Rand des Hauptfensters. Die Mindesthoehe ist 520
#: statt der 460 der Spezifikation: gemessen (test_a_live L61) standen bei
#: 460 "Erlauben"/"Ablehnen" einer langen Freigabe-Karte 43 px unter dem
#: sichtbaren Teil ihres Bereichs — Kopf, Kontextzeile und Segmente nehmen
#: dem Chat rund 60 px mehr als das Chatfenster bis K11. Mit 520 hat der
#: Chat wieder die Hoehe des alten Chatfensters an SEINER Mindesthoehe.
OFFEN_BREITE = 420
OFFEN_BREITE_MIN = 340
OFFEN_HOEHE_MIN = 520
RAND_UNTEN = 16
#: Angedockt: so breit (mindestens).
ANGEDOCKT_BREITE = 420
ANGEDOCKT_BREITE_MIN = 320
#: Ab so viel Ruck loest Ziehen am Kopf ein angedocktes Fenster ab.
ZIEH_RUCK = 14
#: Abstand der Pille vom rechten Rand des Hauptfensters und von der
#: Oberkante seiner Mitte (unter Menue und Werkzeugleisten).
MONITOR_ABSTAND = (16, 12)
#: Ohne erkennbare Mitte (centralWidget): so weit unter der Oberkante des
#: Hauptfensters (unter Cadworks Menueband).
MONITOR_OBEN_OHNE = 96
#: Hoechstens so viele Zeichen Dokumentname bzw. Beschreibung eines
#: Auftrags in einer Zeile (der volle Text im Tooltip).
DOK_NAME_ZEICHEN = 32
DOK_AUFTRAG_ZEICHEN = 40
#: Nach dem Zeigen sieht das Dock nach, ob Fenster bzw. Arbeitsanzeige noch
#: dort stehen, wo es sie hingesetzt hat (Millisekunden nach dem Setzen) —
#: und setzt sie hoechstens ORT_NACHSETZEN_MAX-mal zurueck.
ORT_NACHSEHEN_MS = (0, 300)
ORT_NACHSETZEN_MAX = 2
ORT_TOLERANZ = 2
#: So viele Zeilen ueber die Fenster haelt das Dock, bis es ein Log gibt.
ORT_ZEILEN_MAX = 20
#: Wer greift welches Fenster — fuer das Nachsehen (`_ort_nachsehen`).
ORT_GEGRIFFEN = {"fenster": "fenster_gezogen", "anzeige": "anzeige_gezogen"}
#: Die Tooltips des letzten Kopfknopfs (Wunsch des Maintainers: liest sich
#: als "Vergroessern/Andocken", Symbol mit zwei Pfeilen nach aussen).
ANDOCKEN_TIPP = "Rechts andocken"
#: Name und Tooltip des "×" im Kopf (nur ohne Verbindung).
SCHLIESSEN_TIPP = "Schliessen"
#: Abstand der Teile im Kopf; mit dem "×" enger (`_schliessen_zeigen`).
KOPF_ABSTAND = 8
KOPF_ABSTAND_ENG = 4
ABDOCKEN_TIPP = "Abdocken — wieder als schwebendes Fenster"
#: Hoechstens dieser Anteil des Koerpers fuer die Hinweise bzw. der Seite
#: des Briefkastens fuer "Letzte Aufträge". Gegenpruefung Laien-Sicht K12:
#: offene Hinweise nahmen das halbe Fenster und schnitten dabei ihren Text
#: ab — jetzt hoechstens 40 %, so hoch wie ihr Inhalt, und was nicht passt,
#: rollt als GANZES (jeder Hinweis in voller Hoehe, `_hinweise_masse`).
HINWEISE_ANTEIL = 0.40
#: Mit gewaehltem Hinweis (dann stehen seine Knoepfe darunter) hoechstens
#: die Haelfte — nur, solange man an einem Hinweis arbeitet.
HINWEISE_ANTEIL_WAHL = 0.50
#: So hoch wird der Hinweis-Bereich mindestens (auch im kleinen Fenster).
HINWEISE_MIN = 160
#: Ohne gewaehlten Hinweis steht statt der Knoepfe EINE Zeile.
HINWEIS_TIPP = ("Einen Hinweis antippen: er wird im Modell gezeigt, "
                "darunter stehen die Knöpfe dazu.")
AUFTRAEGE_ANTEIL = 0.40
#: Die Rundung der schwebenden Karte (Kopf und Koerper im QSS) — dieselbe
#: Zahl schneidet die Maske des schwebenden Fensters zu (`_fenster_maske`).
FENSTER_RUNDUNG = 14
#: Kopf und Koerper: Rand und Rundung je Zustand (schwebend die Karte wie
#: die Leiste aus K11, angedockt buendig ohne Rand). Typ, Name UND
#: Eigenschaft im Selektor: das schlaegt `#OpenMcpCadA { background }`.
FENSTER_QSS = """
QFrame#OpenMcpCadA[teil="kopf"] {
    background: %(karte)s; border: 2px solid %(blau)s;
    border-radius: %(rundung)dpx;
}
QFrame#OpenMcpCadA[teil="kopf"][zustand="offen"] {
    border-bottom: 1px solid %(rahmen)s;
    border-bottom-left-radius: 0px; border-bottom-right-radius: 0px;
}
QFrame#OpenMcpCadA[teil="kopf"][zustand="angedockt"] {
    border: none; border-bottom: 1px solid %(rahmen)s; border-radius: 0px;
}
QFrame#OpenMcpCadA[teil="koerper"] {
    background: %(grund)s; border: 2px solid %(blau)s; border-top: none;
    border-bottom-left-radius: %(rundung)dpx;
    border-bottom-right-radius: %(rundung)dpx;
}
QFrame#OpenMcpCadA[teil="koerper"][zustand="angedockt"] {
    border: none; border-radius: 0px;
}
QFrame#OpenMcpCadA[teil="kopf"] QLabel#neben { font-size: 14px; }
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#kopf_knopf {
    background: transparent; border: none; border-radius: 8px;
    padding: 0px; color: %(neben)s;
}
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#kopf_knopf:hover {
    background: %(grund)s;
}
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#kopf_knopf:checked {
    background: #e8f1fd; border: 1px solid #b9d3f5;
}
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#chatknopf,
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#hinweis { padding: 0px; }
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#chatknopf[aktiv="nein"] {
    background: transparent; border: 1px solid %(rahmen)s;
}
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#primaer { padding: 0px 12px; }
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#trennen { padding: 0px 10px; }
QFrame#OpenMcpCadA[teil="kopf"] QPushButton#kopf_chip {
    background: #fff4e5; color: #9a4a00; border: 1px solid #f0c77a;
    border-radius: 9px; padding: 0px 7px; font-size: 11px; font-weight: 600;
}
#OpenMcpCadA QFrame#segment {
    background: %(grund)s; border: 1px solid %(rahmen)s; border-radius: 9px;
}
#OpenMcpCadA QFrame#segment QPushButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 7px; color: %(neben)s; padding: 3px 8px;
    font-size: 12px;
}
#OpenMcpCadA QFrame#segment QPushButton:checked {
    background: %(karte)s; border: 1px solid %(rahmen)s; color: %(text)s;
    font-weight: 600;
}
#OpenMcpCadA QLabel#seg_zahl {
    background: %(orange)s; color: #ffffff; border-radius: 7px;
    padding: 0px 5px; font-size: 10px; font-weight: 600;
}
#OpenMcpCadA QPushButton#werkzeug {
    background: transparent; border: none; border-radius: 8px; padding: 0px;
    min-width: 26px; min-height: 26px; color: %(text)s;
}
#OpenMcpCadA QPushButton#werkzeug:hover { background: #e6e6ea; }
#OpenMcpCadA QPushButton#werkzeug:checked { background: #e8f1fd; }
#OpenMcpCadA QPushButton#werkzeug:disabled { color: #b0b0b5; }
#OpenMcpCadA QLabel#kontext_zeile { color: %(neben)s; font-size: 11px; }
#OpenMcpCadA QFrame#hinweise_bereich {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 10px;
}
#OpenMcpCadA QFrame#laeuft_jetzt {
    background: #eef4fd; border: 1px solid #b9d3f5; border-radius: 8px;
}
#OpenMcpCadA QFrame#popover {
    background: %(karte)s; border: 1px solid %(rahmen)s; border-radius: 14px;
}
#OpenMcpCadA QFrame#stufe_kachel {
    background: %(grund)s; border-radius: 10px;
}
#OpenMcpCadA QFrame#stufe_kachel:focus { border: 2px solid %(blau)s; }
#OpenMcpCadA QLabel#stufe_gross {
    font-size: 17px; font-weight: 600; color: %(text)s;
}
#OpenMcpCadA QLabel#modell_zeile { font-size: 11px; color: %(neben)s; }
#OpenMcpCadA QFrame#stufe_kachel:hover QLabel#modell_zeile {
    text-decoration: underline;
}
#OpenMcpCadA QPushButton:focus { outline: none; }
#OpenMcpCadA QPushButton#flach:focus, #OpenMcpCadA QPushButton#werkzeug:focus {
    border: 2px solid %(blau)s;
}
""" % dict(FARBEN, rundung=FENSTER_RUNDUNG)
#: Die Arbeitsanzeige (eigenes Fenster an Cadworks Hauptfenster): eine Karte
#: wie die Pille, links ein Streifen in der Farbe des Zustands.
ANZEIGE_QSS = """
QFrame#OpenMcpCadA[teil="anzeige"] {
    background: %(karte)s; border: 1px solid %(rahmen)s;
    border-left: 3px solid %(blau)s; border-radius: 14px;
}
QFrame#OpenMcpCadA[teil="anzeige"][farbe="orange"] {
    border-left: 3px solid %(orange)s;
}
QFrame#OpenMcpCadA[teil="anzeige"][farbe="gruen"] {
    border-left: 3px solid %(gruen)s;
}
QFrame#OpenMcpCadA[teil="anzeige"] QLabel#anzeige_titel {
    font-size: 13px; font-weight: 600; color: %(text)s;
}
QFrame#OpenMcpCadA[teil="anzeige"] QLabel#anzeige_zeile {
    font-size: 11px; color: %(neben)s;
}
QFrame#OpenMcpCadA[teil="anzeige"] QPushButton#trennen,
QFrame#OpenMcpCadA[teil="anzeige"] QPushButton#primaer {
    padding: 3px 10px; font-size: 11px;
}
QFrame#OpenMcpCadA[teil="anzeige"] QPushButton#flach { padding: 0px; }
""" % FARBEN


# --- Die Zustandsmaschine (rein, ohne Qt; test_a_prototyp P21) -------------

def _fenster_uebergang(zustand, aktion, segment="chat"):
    """Was eine Aktion aus einem Zustand macht (Spezifikation 1.3) — rein.

    `zustand`: pille/offen/angedockt; `aktion`: klick (Plugin-Klick), chat
    (Chat-Knopf im Kopf), andocken, verkleinern, hinweise (Zahl in der
    Pille), schliessen (Cadwork hat das Dock geschlossen); `segment`: was im
    Koerper vorn steht (chat, briefkasten, einstellungen).
    -> {"zustand", "segment", "fokus" (Eingabe des Chats), "hinweise"
       (None, "auf" oder "um")}."""
    if zustand not in FENSTER_ZUSTAENDE:
        zustand = PILLE_Z
    erg = {"zustand": zustand, "segment": segment, "fokus": False,
           "hinweise": None}
    if aktion == "chat":
        if zustand == PILLE_Z:
            erg.update(zustand=OFFEN_Z, segment="chat", fokus=True)
        elif zustand == OFFEN_Z and segment == "chat":
            erg["zustand"] = PILLE_Z
        else:
            erg.update(segment="chat", fokus=True)
    elif aktion == "andocken":
        erg["zustand"] = OFFEN_Z if zustand == ANGEDOCKT_Z else ANGEDOCKT_Z
    elif aktion in ("verkleinern", "schliessen"):
        erg["zustand"] = PILLE_Z
    elif aktion == "hinweise":
        if zustand == PILLE_Z:
            erg.update(zustand=OFFEN_Z, hinweise="auf")
        else:
            erg["hinweise"] = "um"
    return erg


#: Was die Pille sagt, wenn der Chat oder Cadwork etwas zu sagen hat
#: (Spezifikation 2.2; die Zustaende des Kerns stehen in PILLE).
PILLE_CADWORK = ("Cadwork rechnet", FARBEN["orange"])
PILLE_FREIGABE = ("Wartet auf dich", FARBEN["orange"])
PILLE_DENKT = ("Denkt nach", FARBEN["blau"])
#: Ein Menue/Popover VON OPEN MCP CAD ist offen, und Auftraege warten
#: darauf (die Sonde "popup" des Kerns zaehlt jedes Qt-Popup, auch unsere —
#: Gegenpruefung K12). Kein "Cadwork rechnet": Cadwork rechnet ja nicht.
PILLE_MENUE = ("Menü offen", FARBEN["orange"])
#: Marke fuer `blockiert`: der Grund ist ein eigenes Menue (`_blockiert`).
EIGENES_MENUE = "eigenes Menü"


def _pille_zustand(verbunden, zustand, blockiert=None, freigabe=False,
                   chat_zug=False):
    """(Text, Farbe) der Zustandspille — rein (test_a_prototyp P20).

    Vorrang: aus, verbindet, Stoerung, Cadwork rechnet, Freigabe wartet,
    zeichnet, liest, denkt nach (Chat-Zug ohne Auftrag), dann die uebrigen
    Zustaende des Kerns (pausiert, trennt nach Auftrag, bereit)."""
    if not verbunden or zustand in (None, "stopped"):
        return PILLE[None]
    if zustand in ("starting", "error"):
        return PILLE[zustand]
    if blockiert == EIGENES_MENUE:
        return PILLE_MENUE
    if blockiert:
        return PILLE_CADWORK
    if freigabe:
        return PILLE_FREIGABE
    if zustand in ("busy_write", "busy_read"):
        return PILLE[zustand]
    if chat_zug:
        return PILLE_DENKT
    return PILLE.get(zustand, (zustand or "Aus", FARBEN["neben"]))


def _eigenes_popup(z):
    """Ist das offene Qt-Popup eines VON UNS (Popover, Modellliste,
    Aufklapper, die Liste eines Auswahlfelds im Fenster)? Gefragt wird die
    Elternkette bis zum Fenster bzw. zur Arbeitsanzeige. -> bool"""
    from PyQt6.QtWidgets import QApplication
    eigene = [x for x in (z.get("fenster"), z.get("anzeige"))
              if x is not None]
    try:
        p = QApplication.activePopupWidget()
        while p is not None:
            if any(p is e for e in eigene):
                return True
            p = p.parentWidget()
    except RuntimeError:                       # schon abgeraeumt
        return False
    return False


def _blockiert(z, st):
    """Warum der Kern zurueckhaelt (`cadwork_beschaeftigt`) — fuer Pille und
    Arbeitsanzeige. Die Sonde "popup" des Kerns zaehlt JEDES Qt-Popup, auch
    unseren Popover (Gegenpruefung K12: dann stand "Cadwork rechnet" und im
    Kontext "Cadwork arbeitet gerade selbst"). Ist es eines von uns:
    EIGENES_MENUE, wenn Auftraege darauf warten, sonst None (nichts
    haelt dann etwas auf). Das Zurueckhalten selbst bleibt (Schutz).
    -> None, EIGENES_MENUE oder der Grund des Kerns."""
    st = st or {}
    grund = st.get("cadwork_beschaeftigt") or None
    if grund and str(grund).startswith("Menue oder Popup offen") \
            and _eigenes_popup(z):
        return EIGENES_MENUE if st.get("wartende_auftraege") else None
    return grund


# --- Die Arbeitsanzeige: was sie sagt (rein, test_a_prototyp P20) -----------

ANZEIGE_CADWORK = ("Cadwork rechnet",
                   "Open MCP CAD wartet, bis Cadwork fertig ist.")
ANZEIGE_MENUE = ("Wartet, bis das Menü zu ist",
                 "Ein Menü von Open MCP CAD ist offen — danach geht es "
                 "weiter.")
ANZEIGE_FREIGABE = "Wartet auf deine Freigabe"
ANZEIGE_ZEICHNET = "KI zeichnet"
ANZEIGE_LIEST = "KI schaut ins Modell"
ANZEIGE_DENKT = "KI denkt nach"
ANZEIGE_WARTET = "Wartet auf den nächsten Schritt"
ANZEIGE_FERTIG = "Fertig"
ANZEIGE_ANGEHALTEN = "Angehalten"
#: So lange steht "Fertig", dann geht die Anzeige.
ANZEIGE_FERTIG_S = 1.5
ANZEIGE_BREITE = 360


def _dauer_kurz(s):
    s = max(0.0, float(s or 0))
    if s < 90:
        return "%.0f s" % s
    return "%.0f min" % (s / 60.0)


def _anzeige_zustand(blockiert=None, freigabe=None, auftrag=None,
                     lauf=None, lauf_aktiv=False, chat_zug=False,
                     letzter=None, client=None, fertig=None,
                     angehalten=0, balken_vorher=None, jetzt=None,
                     wartende=0):
    """Was die Arbeitsanzeige zeigt (Spezifikation 5.3) — rein.

    `freigabe`: der Schritt, der auf Freigabe wartet (Text) oder None;
    `auftrag`: der laufende Auftrag (zugriff, beschreibung, paket, t0);
    `lauf`: die letzte Info des Kerns zum Lauf (lauf_gezeichnet,
    lauf_gesamt, prozent, restzeit_s); `lauf_aktiv`: der Lauf des Kerns ist
    nicht beendet; `chat_zug`: im Chat des Docks laeuft ein Zug; `letzter`:
    (Text, seit_s) des letzten Schritts; `fertig`: (Bauteile, Dauer_s) am
    Ende eines Laufs; `angehalten`: so viele wartende Auftraege hat
    "Anhalten" verworfen (0: keiner); `wartende`: Auftraege in der
    Warteschlange des Kerns.
    "Anhalten" verwirft NUR wartende Auftraege (der laufende Schritt wird
    fertig, der Chat-Zug laeuft weiter — Spezifikation 5.6). Darum steht
    der Knopf nur, solange ein Auftrag laeuft (ein Klick kommt erst nach
    ihm an, dann kann etwas warten) oder etwas wartet — nie bei "KI denkt
    nach" oder "Wartet auf den naechsten Schritt" ohne Wartende: dort
    hielte er nichts an (Gegenpruefung K12).
    -> {"titel", "zeile", "balken" (None, "unbestimmt" oder 0..100),
       "knopf" (None, "anhalten", "zum_chat"), "farbe" (blau, orange,
       gruen), "symbol"} oder None (nichts zu zeigen)."""
    lauf = lauf or {}

    def erg(titel, zeile="", balken=None, knopf=None, farbe="blau",
            symbol=None):
        return {"titel": titel, "zeile": zeile, "balken": balken,
                "knopf": knopf, "farbe": farbe, "symbol": symbol}

    if blockiert == EIGENES_MENUE:
        return erg(ANZEIGE_MENUE[0], ANZEIGE_MENUE[1], farbe="orange")
    if blockiert:
        return erg(ANZEIGE_CADWORK[0], ANZEIGE_CADWORK[1], farbe="orange")
    if freigabe:
        return erg(ANZEIGE_FREIGABE, str(freigabe), knopf="zum_chat",
                   farbe="orange")
    arbeitet = bool(auftrag) or lauf_aktiv or chat_zug
    anhalten = "anhalten" if (auftrag or wartende) else None
    if angehalten and arbeitet and not auftrag:
        zeile = ("1 wartender Auftrag verworfen" if angehalten == 1 else
                 "%d wartende Aufträge verworfen" % angehalten)
        if chat_zug:
            zeile += " · den Chat hält «Beenden» an"
        return erg(ANZEIGE_ANGEHALTEN, zeile, balken_vorher, None, "orange")
    if auftrag and auftrag.get("zugriff") == "write":
        gesamt = lauf.get("lauf_gesamt")
        if gesamt:
            zeile = "%d von %d Bauteilen" % (lauf.get("lauf_gezeichnet") or 0,
                                             gesamt)
            if lauf.get("restzeit_s") is not None:
                zeile += " · noch etwa %s" % _dauer_kurz(lauf["restzeit_s"])
            try:
                balken = int(max(0, min(100, lauf.get("prozent") or 0)))
            except (TypeError, ValueError):
                balken = 0
        else:
            teile = []
            was = " ".join(str(auftrag.get("beschreibung") or "").split())
            if was:
                teile.append(_kurz_text(was, DOK_AUFTRAG_ZEICHEN))
            paket = auftrag.get("paket")
            try:
                teile.append("Paket %d von %d" % (int(paket[0]),
                                                  int(paket[1])))
            except (TypeError, ValueError, IndexError):
                pass
            if jetzt is not None and auftrag.get("t0") is not None:
                teile.append(_dauer_kurz(jetzt - auftrag["t0"]))
            zeile = " · ".join(teile)
            balken = "unbestimmt"
        return erg(ANZEIGE_ZEICHNET, zeile, balken, "anhalten")
    if auftrag:
        was = " ".join(str(auftrag.get("beschreibung") or "").split())
        return erg(ANZEIGE_LIEST, _kurz_text(was, DOK_AUFTRAG_ZEICHEN),
                   None, "anhalten")
    if chat_zug:
        zeile = ""
        if letzter and letzter[0]:
            zeile = "Zuletzt: %s" % letzter[0]
            if letzter[1] is not None:
                zeile += " · vor %d s" % max(0, int(letzter[1]))
        return erg(ANZEIGE_DENKT, zeile, None, anhalten)
    if lauf_aktiv:
        return erg(ANZEIGE_WARTET, client or "", None, anhalten)
    if fertig is not None:
        n, dauer = fertig
        zeile = ("%d Bauteile in %s" % (n, _dauer_kurz(dauer)) if n
                 else "in %s" % _dauer_kurz(dauer))
        return erg(ANZEIGE_FERTIG, zeile, 100, None, "gruen", "check")
    return None


# --- Bauen ----------------------------------------------------------------

def _hauptfenster():
    """Cadworks Hauptfenster (sichtbares QMainWindow) — oder None."""
    from PyQt6.QtWidgets import QApplication, QMainWindow
    for w in QApplication.instance().topLevelWidgets():
        if isinstance(w, QMainWindow) and w.isVisible():
            return w
    return None


def _fenster_bauen(z):
    """Baut das EINE Fenster (K12): Dock `OpenMcpCadFenster`, Kopf als
    Titelleiste, Koerper als Inhalt — und die Arbeitsanzeige (versteckt).
    Zeigt es im gemerkten Zustand dieser Sitzung (Anker), sonst als Pille
    oben rechts.

    Gezeigt wird erst, wenn Groesse und Ort feststehen: schwebend wird VOR
    `show()` verschoben (setzt WA_Moved; ohne setzt Qts Windows-Plattform
    ein Fenster mit Eltern beim Zeigen in die Mitte des Hauptfensters,
    gemessen K10), und die Signale werden erst NACH `setFloating`
    verbunden — `topLevelChanged` kommt mitten aus `setFloating`, und ein
    Verschieben dort loescht Qt danach wieder (K10)."""
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import QDockWidget

    _alte_schluessel_weg(z)
    haupt = _hauptfenster()
    # Neue Widgets, also noch nichts gezeichnet (s. `_chat_zeichnen`).
    z["chat_gezeigt"] = -1
    dock = QDockWidget("Open MCP CAD", haupt)
    dock.setObjectName(FENSTER_NAME)
    # NIE WA_TranslucentBackground (gemessen in Cadwork 2026-10-08, s. Kopf
    # des Abschnitts): angedockt blieb das Fenster sonst unsichtbar. Deckend
    # in jedem Zustand; die runden Ecken schwebend ueber `_fenster_maske`.
    dock.setAutoFillBackground(True)
    dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                         | Qt.DockWidgetArea.RightDockWidgetArea)
    # Verschieben, Abloesen und Schliessen bleiben (Schliessen fuehrt zur
    # Pille, `_fenster_sichtbar`).
    dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                     | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                     | QDockWidget.DockWidgetFeature.DockWidgetClosable)
    z["fenster"] = z["dock"] = dock
    # Loescht Cadwork das Fenster (Aufraeumen), stirbt mit ihm der Takt —
    # die Arbeitsanzeige (ein eigenes Fenster am Hauptfenster) und der
    # Haken im Kern blieben verwaist zurueck (Gegenpruefung K12). Die Marke
    # haelt einen Neubau heraus: der hat seine eigene.
    marke = object()
    z["fenster_marke"] = marke
    dock.destroyed.connect(lambda *_a: _sicher(
        lambda: _fenster_zerstoert(z, marke), "Fenster geloescht"))
    kopf = _kopf_bauen(z, dock)
    koerper = _koerper_bauen(z)
    dock.setTitleBarWidget(kopf)
    dock.setWidget(koerper)
    z["form"] = FORM
    # Die Maske folgt jeder Groesse (auch wenn der Nutzer am Rand zieht).
    z["fenster_masken"] = _masken_filter(z, dock)

    takt = QTimer(dock)
    # `_sicher`: eine Ausnahme im Takt steht auf stderr und haelt ihn nicht an.
    takt.timeout.connect(lambda: _sicher(lambda: _auffrischen(z),
                                         "Auffrischen"))
    takt.start(500)
    z["timer"] = takt

    try:
        _anzeige_bauen(z)
    except Exception as exc:                       # noqa: BLE001
        # Ohne Arbeitsanzeige zeigt der Kern sein eigenes Fenster (kein
        # Haken, `_haken_setzen`).
        _melden("Arbeitsanzeige bauen", exc)
        z["anzeige"] = None

    zustand = z.get("fenster_zustand")
    if zustand not in FENSTER_ZUSTAENDE:
        zustand = PILLE_Z
    if zustand == ANGEDOCKT_Z and haupt is None:
        zustand = OFFEN_Z
    z["fenster_zustand"] = zustand
    _segment_waehlen(z, z.get("segment"), fokus=False)
    _hinweise_zeigen(z, bool(z.get("hinweise_offen")))
    if haupt is not None:
        haupt.addDockWidget(_bereich(z.get("angedockt_bereich")), dock,
                            Qt.Orientation.Horizontal)
    if zustand == ANGEDOCKT_Z:
        koerper.show()
        dock.setFloating(False)
        _fenster_maske(z)
        dock.show()
    else:
        koerper.setVisible(zustand == OFFEN_Z)
        dock.setFloating(True)
        # Groesse und Ort VOR dem Zeigen (s. oben).
        _fenster_lage(z, vor_show=True)
        _fenster_maske(z)
        dock.show()
        # Vor dem ersten Zeigen meldet das Dock eine andere Mindestbreite
        # als danach (gemessen offscreen: 274 statt 270 px) — die Pille
        # stuende dann 4 px links von ihrem Ort. Also gleich nachmessen;
        # die rechte Kante bleibt am Ort der Pille.
        _kopf_anpassen(z)
    _kopf_zeigen(z)
    # Die Signale ERST JETZT (K10).
    dock.topLevelChanged.connect(lambda schwebt: _sicher(
        lambda: _fenster_schwebt(z, schwebt), "Fenster andocken"))
    dock.dockLocationChanged.connect(lambda bereich: _sicher(
        lambda: _bereich_merken(z, "angedockt_bereich", bereich),
        "Fenster andocken"))
    dock.visibilityChanged.connect(lambda sichtbar: _sicher(
        lambda: _fenster_sichtbar(z, dock, sichtbar), "Fenster schliessen"))
    if zustand == ANGEDOCKT_Z:
        QTimer.singleShot(0, lambda: _sicher(lambda: _fenster_lage(z),
                                             "Fenster setzen"))
    # Laeuft schon ein Dienst (Neubau, Update ohne Neustart): die
    # Arbeitsanzeige dieses Docks bekommt die Laeufe.
    _haken_setzen(z)
    return dock


def _fenster_zerstoert(z, marke):
    """Qt hat das Fenster geloescht (Cadwork hat aufgeraeumt; mit ihm der
    Takt). Dann gehoeren auch die Arbeitsanzeige und der Haken im Kern
    nicht mehr dazu: der Haken weg (der Kern zeigt bis zum naechsten
    Plugin-Klick wieder sein eigenes Fenster — nie gar keins, nie zwei),
    die Anzeige versteckt und freigegeben. Nur fuer das Fenster, das noch
    gilt (`marke`). -> abgeraeumt?"""
    if marke is None or z.get("fenster_marke") is not marke:
        return False
    z["fenster_marke"] = None
    _haken_weg(z)
    anzeige, z["anzeige"] = z.get("anzeige"), None
    if anzeige is not None:
        try:
            anzeige.hide()
            anzeige.deleteLater()
        except RuntimeError:                   # schon abgeraeumt
            pass
    return True


def _alte_schluessel_weg(z):
    """Was K9-K11 im Anker hinterliessen und K12 nicht mehr kennt — beim
    ersten Bau weg (Spezifikation 1.4). `hinweise_offen` war in K11 die
    ZAHL offener Hinweise, seit K12 heisst es "Hinweis-Bereich offen"."""
    for schluessel in ALTE_SCHLUESSEL:
        z.pop(schluessel, None)
    if not isinstance(z.get("hinweise_offen"), bool):
        z["hinweise_offen"] = False
    if z.get("segment") not in SEGMENTE:
        z["segment"] = "chat"


def _kopf_bauen(z, dock):
    """Der Kopf (Spezifikation 2, Vorbild Bild 8): [Griff][Logo][Zustand]
    [Hinweis-Zahl?] ·· [Chat][Trennen|Verbinden][Andocken][Verkleinern?].
    In allen drei Zustaenden DASSELBE Objekt — die einzige Titelleiste des
    Fensters. Gezogen wird an jeder Stelle ausser den Knoepfen; ein
    angedocktes Fenster loest sich ab ZIEH_RUCK px Ruck. KEIN
    Einstellungsknopf, kein Dokumentname (Rueckmeldung 2026-10-07:
    "Einstellungen brauchts nicht in der obersten Leiste"); ein "×" nur
    ohne Verbindung (Rueckmeldung 2026-10-08, `_fenster_schliessen`)."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

    class Kopf(QFrame):
        """Ziehen von Hand: mit eigener Titelleiste tut Qt es nicht."""

        def __init__(self):
            super().__init__()
            self._start = None
            self._griff = QPoint(60, 20)
            self.setCursor(Qt.CursorShape.OpenHandCursor)

        def gezogen(self):
            return self._start is not None

        def mousePressEvent(self, e):                 # noqa: N802
            try:
                if e.button() != Qt.MouseButton.LeftButton:
                    return
                self._start = e.globalPosition().toPoint()
                # Der Nutzer greift: das Nachsehen setzt nicht zurueck (K10).
                z["fenster_gezogen"] = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                if dock.isFloating():
                    self._griff = self._start - dock.pos()
            except Exception as exc:                  # noqa: BLE001
                _melden("Kopf greifen", exc)

        def mouseMoveEvent(self, e):                  # noqa: N802
            try:
                if self._start is None:
                    return
                p = e.globalPosition().toPoint()
                if not dock.isFloating():
                    if (p - self._start).manhattanLength() < ZIEH_RUCK:
                        return
                    # Abloesen -> offen, das Fenster folgt der Maus.
                    self._griff = QPoint(min(60, self.width() // 2), 20)
                    _abloesen_beim_ziehen(z)
                dock.move(p - self._griff)
            except Exception as exc:                  # noqa: BLE001
                _melden("Kopf ziehen", exc)

        def mouseReleaseEvent(self, e):               # noqa: N802
            try:
                self._start = None
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                if dock.isFloating():
                    _pille_ort_merken(z)
            except Exception as exc:                  # noqa: BLE001
                _melden("Kopf loslassen", exc)

    kopf = Kopf()
    kopf.setObjectName("OpenMcpCadA")
    kopf.setProperty("teil", "kopf")
    kopf.setProperty("zustand", PILLE_Z)
    kopf.setStyleSheet(_qss() + FENSTER_QSS)
    kopf.setFixedHeight(KOPF_HOEHE)
    kopf.setToolTip("Open MCP CAD — ziehen zum Verschieben")
    lay = QHBoxLayout(kopf)
    lay.setContentsMargins(8, 4, 8, 4)
    lay.setSpacing(KOPF_ABSTAND)
    griff = QLabel("")
    griff.setObjectName("neben")
    _label_symbol(griff, "grip-vertical", "⠿", groesse=16)
    griff.setProperty("kopf_name", "kopf_griff")
    logo = _logo_klein(22)
    logo.setProperty("kopf_name", "kopf_logo")
    pille = QLabel("● Aus")
    pille.setObjectName("pille")
    pille.setAccessibleName("Zustand")

    def knopf(name, zugang, tipp, fn, objekt="kopf_knopf"):
        b = QPushButton("")
        b.setObjectName(objekt)
        b.setProperty("kopf_name", name)
        b.setAccessibleName(zugang)
        b.setToolTip(tipp)
        b.setFixedHeight(KOPF_KNOPF_HOEHE)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        # `_sicher`: eine Ausnahme aus einem Qt-Slot waere in Cadwork qFatal.
        b.clicked.connect(lambda _c=False: _sicher(fn, zugang))
        return b

    hinweise = knopf("kopf_hinweise", "Offene Hinweise",
                     "Offene Prüfhinweise zeigen (die Zahl steht nur in der "
                     "Pille; offen an der Flagge)",
                     lambda: _fenster_aktion(z, "hinweise"), "kopf_chip")
    hinweise.setFixedHeight(20)
    hinweise.hide()
    chat = knopf("chatknopf", "Chat", "Chat", lambda: _fenster_aktion(
        z, "chat"), CHAT_KNOPF_NAME)
    chat.setProperty("aktiv", "nein")
    chat.setFixedWidth(32)
    if not _knopf_symbol(chat, "chat", farbe=FARBEN["blau"]):
        chat.setText("Chat")
        chat.setFixedWidth(44)
    primaer = knopf("primaer", "Verbinden", "Verbinden",
                    lambda: _primaer_geklickt(z), "primaer")
    primaer.setText("Verbinden")
    andocken = knopf("kopf_andocken", "Rechts andocken", ANDOCKEN_TIPP,
                     lambda: _fenster_aktion(z, "andocken"))
    andocken.setCheckable(True)
    andocken.setFixedWidth(30)
    _knopf_symbol(andocken, "andocken", farbe=FARBEN["neben"])
    klein = knopf("kopf_verkleinern", "Verkleinern",
                  "Verkleinern — nur noch der Kopf. Die Verbindung läuft "
                  "weiter.", lambda: _fenster_aktion(z, "verkleinern"))
    klein.setFixedWidth(30)
    _knopf_symbol(klein, "verkleinern", farbe=FARBEN["neben"])
    klein.hide()
    # Nur OHNE Verbindung (Rueckmeldung 2026-10-08): das Fenster ganz
    # schliessen. Verbunden bleibt der Kopf, wie er ist ("Trennen" trennt
    # und laesst das Fenster stehen); `_schliessen_zeigen` im Takt.
    zu = knopf("kopf_schliessen", SCHLIESSEN_TIPP, SCHLIESSEN_TIPP,
               lambda: _fenster_schliessen(z))
    zu.setFixedWidth(30)
    _knopf_symbol(zu, "schliessen", farbe=FARBEN["neben"])
    zu.hide()
    for teil in (griff, logo, pille, hinweise):
        lay.addWidget(teil, 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addStretch(1)
    for teil in (chat, primaer, andocken, klein, zu):
        lay.addWidget(teil, 0, Qt.AlignmentFlag.AlignVCenter)
    z["w"].update(kopf=kopf, kopf_griff=griff, kopf_logo=logo, pille=pille,
                  kopf_hinweise=hinweise, kopf_chat=chat, primaer=primaer,
                  kopf_andocken=andocken, kopf_verkleinern=klein,
                  kopf_schliessen=zu)
    return kopf


def _koerper_bauen(z):
    """Der Koerper (Spezifikation 3): Kontextzeile, Segmentzeile
    [Chat | Briefkasten] mit Rueckgaengig, Wiederherstellen, Neu zeichnen,
    Hinweisen und "⋯", der Hinweis-Bereich (aufklappbar) und der
    Seitenstapel Chat (0), Briefkasten (1), Einstellungen (2). In "offen"
    und "angedockt" DASSELBE Widget."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeySequence, QShortcut
    from PyQt6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                                 QPushButton, QStackedWidget, QVBoxLayout)
    K = _qt_klassen()
    koerper = QFrame()
    koerper.setObjectName("OpenMcpCadA")
    koerper.setProperty("teil", "koerper")
    koerper.setProperty("zustand", OFFEN_Z)
    koerper.setStyleSheet(_qss() + FENSTER_QSS)     # NUR das Fenster
    koerper.setMinimumWidth(ANGEDOCKT_BREITE_MIN)
    lay = QVBoxLayout(koerper)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(8)

    # 1. Kontextzeile (oder eine Meldung, `_zeile_rot`).
    kontext = QLabel("nicht verbunden")
    kontext.setObjectName("kontext_zeile")
    kontext.setTextFormat(Qt.TextFormat.PlainText)
    meldung = QLabel("")
    meldung.setObjectName("neben")
    meldung.setWordWrap(True)
    meldung.hide()
    lay.addWidget(kontext)
    lay.addWidget(meldung)

    # 2. Segmentzeile.
    reihe = QHBoxLayout()
    reihe.setSpacing(4)
    seg = QFrame()
    seg.setObjectName("segment")
    sl = QHBoxLayout(seg)
    sl.setContentsMargins(2, 2, 2, 2)
    sl.setSpacing(2)
    gruppe = QButtonGroup(seg)
    gruppe.setExclusive(True)
    seg_knoepfe = {}
    for name, text, zweck in (("chat", "Chat", "chat"),
                              ("briefkasten", "Briefkasten",
                               "segment_briefkasten")):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setAccessibleName("Bereich %s" % text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        _knopf_symbol(b, zweck, text=text, farbe=FARBEN["text"], groesse=14)
        gruppe.addButton(b)
        sl.addWidget(b, 1)
        seg_knoepfe[name] = b
    zahl = QLabel("")
    zahl.setObjectName("seg_zahl")
    zahl.hide()
    # Die Zahl steht NEBEN dem Knopf im Segment, nicht in ihm: im Knopf
    # verdeckte sie das Wort ("Briefkast" unter der Zahl, Sichtung K12).
    sl.addWidget(zahl, 0, Qt.AlignmentFlag.AlignVCenter)
    reihe.addWidget(seg)
    reihe.addStretch(1)

    def werkzeug(zweck, name, tipp):
        b = QPushButton("")
        b.setObjectName("werkzeug")
        b.setFixedSize(26, 26)
        b.setAccessibleName(name)
        b.setToolTip(tipp)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        _knopf_symbol(b, zweck, farbe=FARBEN["text"], groesse=15)
        reihe.addWidget(b)
        return b

    btn_undo = werkzeug("rueckgaengig", "Rückgängig",
                        "Letzten Auftrag rückgängig (Cadworks eigenes Undo). "
                        "Ein Klick = ein Auftrag.")
    btn_redo = werkzeug("wiederholen", "Wiederherstellen",
                        "Wiederherstellen, was ein Rückgängig weggenommen "
                        "hat.")
    btn_neu = werkzeug("neu_zeichnen", "Ansicht neu zeichnen",
                       "Ansicht neu zeichnen")
    hin = werkzeug("hinweise_flagge", "Hinweise",
                   "Prüfhinweise auf- und zuklappen")
    hin.setCheckable(True)
    hin.setFixedSize(26, 26)
    mehr = werkzeug("mehr", "Mehr", "Einstellungen, Pausieren, Anleitung, "
                                    "Technik")
    lay.addLayout(reihe)

    # 3. Hinweis-Bereich (aufklappbar, in beiden Segmenten).
    bereich = QFrame()
    bereich.setObjectName("hinweise_bereich")
    hl = QVBoxLayout(bereich)
    hl.setContentsMargins(8, 6, 8, 6)
    hl.setSpacing(4)
    hk = QHBoxLayout()
    hk_titel = QLabel("Hinweise")
    hk_titel.setObjectName("abschnitt")
    hk_zu = QPushButton("")
    hk_zu.setObjectName("flach")
    hk_zu.setAccessibleName("Hinweise schliessen")
    hk_zu.setToolTip("Hinweise zuklappen")
    _knopf_symbol(hk_zu, "aufklappen", text="Schliessen",
                  farbe=FARBEN["neben"], groesse=14)
    hk.addWidget(hk_titel, 1)
    hk.addWidget(hk_zu)
    hl.addLayout(hk)
    _tab_hinweise(z, hl)
    # "nur offene" in die Titelzeile (die Zeile des Zaehlers ist leer).
    hk.insertWidget(1, z["w"]["hinweise"]["nur_offen"])
    bereich.hide()
    lay.addWidget(bereich, 0)

    # 4. Seitenstapel. Die Einstellungsseite ZUERST bauen (dort legt
    # `_tab_chat` seine Karte ab), aber erst NACH Chat und Briefkasten in
    # den Stapel: solange sie nicht drinsteht, gilt sie nicht als sichtbar,
    # und der Bau stoesst keine Pruefung im Hintergrund an.
    seiten = QStackedWidget()
    z["w"].update(koerper=koerper, kontext_zeile=kontext, dok=kontext,
                  hinweis=meldung, segment=seg, segment_chat=seg_knoepfe[
                      "chat"], segment_briefkasten=seg_knoepfe["briefkasten"],
                  segment_gruppe=gruppe, briefkasten_zahl=zahl,
                  btn_undo=btn_undo, btn_redo=btn_redo, btn_neu=btn_neu,
                  hinweise_knopf=hin, mehr_menue=mehr,
                  hinweise_bereich=bereich, hinweise_titel=hk_titel,
                  hinweise_zu=hk_zu, seiten=seiten, chat_stapel=seiten)
    einst = _einstellungen_bauen(z)
    _tab_chat_oder_ersatz(z, seiten)
    seiten.addWidget(_briefkasten_bauen(z))
    seiten.addWidget(einst)
    seiten.setCurrentIndex(0)
    lay.addWidget(seiten, 1)

    # "⋯": die Dinge, die nicht in den Kopf gehoeren.
    auf = K.Aufklapper(koerper)
    eintraege = {}
    for schluessel, text, symbol, tipp, fn in (
            ("einst", "Einstellungen", "settings",
             "Chat, Verbindung, Zeichenmodus, Technik",
             lambda: _einstellungen_zeigen(z, True)),
            ("pause", "Pausieren", "pause",
             "Neue Aufträge warten lassen, bis «Fortsetzen»",
             lambda: _pause_umschalten(z)),
            ("nach", "Nach Auftrag trennen", "unplug",
             "Den laufenden Auftrag fertig rechnen, dann trennen",
             lambda: _trennen(z)),
            ("anleitung", "Anleitung öffnen", "book-open",
             "Die Anleitung (PDF) neben dem Plugin, sonst die Seite im Netz",
             lambda: _anleitung_oeffnen(z)),
            ("technik", "Technik-Details", "wrench",
             "Port, Pfade, Sitzung — für die Fehlersuche",
             lambda: _technik_zeigen(z))):
        b = K.eintrag(text, tipp, symbol=symbol)
        b.clicked.connect(lambda _c=False, fn=fn, text=text: (
            auf.hide(), _sicher(fn, text)))
        auf.unten.addWidget(b)
        eintraege[schluessel] = b
    z["w"].update(mehr_auf=auf, mehr_einst=eintraege["einst"],
                  btn_pause=eintraege["pause"], btn_nach=eintraege["nach"],
                  mehr_anleitung=eintraege["anleitung"],
                  mehr_technik=eintraege["technik"])

    gruppe.buttonClicked.connect(lambda b: _sicher(
        lambda: _segment_waehlen(
            z, "chat" if b is seg_knoepfe["chat"] else "briefkasten"),
        "Segment"))
    btn_undo.clicked.connect(lambda: _sicher(
        lambda: _auftrag(z, "undo", {"schritte": 1}, "Rückgängig"),
        "Rückgängig"))
    btn_redo.clicked.connect(lambda: _sicher(
        lambda: _auftrag(z, "redo", {"schritte": 1}, "Wiederherstellen"),
        "Wiederherstellen"))
    # "neu_zeichnen" ist die Methode des Kerns hinter dem Werkzeug
    # `redraw_view` des Servers.
    btn_neu.clicked.connect(lambda: _sicher(
        lambda: _auftrag(z, "neu_zeichnen", {}, "Ansicht neu zeichnen"),
        "Ansicht neu zeichnen"))
    hin.clicked.connect(lambda: _sicher(lambda: _hinweise_zeigen(z),
                                        "Hinweise"))
    hk_zu.clicked.connect(lambda: _sicher(lambda: _hinweise_zeigen(z, False),
                                          "Hinweise"))
    mehr.clicked.connect(lambda: _sicher(lambda: _mehr_aufklappen(z),
                                         "Mehr"))
    seiten.currentChanged.connect(lambda _i: _sicher(
        lambda: _seite_gewechselt(z), "Seite"))
    for taste, segment in (("Ctrl+1", "chat"), ("Ctrl+2", "briefkasten")):
        kurz = QShortcut(QKeySequence(taste), koerper)
        kurz.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        kurz.activated.connect(lambda segment=segment: _sicher(
            lambda: _segment_waehlen(z, segment), "Segment"))
    return koerper


def _briefkasten_bauen(z):
    """Das Segment "Briefkasten" (Spezifikation 3.4): die Arbeit mit einem
    Agenten AUSSERHALB des Docks — "Läuft jetzt", "Letzte Aufträge" (nur
    hier; im Chat zeigt der Verlauf die Schritte), Notizen fuer die KI und
    die Ablegen-Zeile. Sieht anders aus als der Chat (Rueckmeldung
    2026-10-02): eine Zeile + "Ablegen" statt Eingabe mit Senden-Kreis,
    Zeilen als Protokoll. -> die Seite."""
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout,
                                 QLabel, QLineEdit, QListWidget, QPushButton,
                                 QScrollArea, QVBoxLayout, QWidget)
    seite = QWidget()
    lay = QVBoxLayout(seite)
    lay.setContentsMargins(0, 2, 0, 0)
    lay.setSpacing(8)

    # 1. Laeuft jetzt.
    laeuft = QFrame()
    laeuft.setObjectName("laeuft_jetzt")
    ll = QHBoxLayout(laeuft)
    ll.setContentsMargins(8, 5, 8, 5)
    ll.setSpacing(6)
    laeuft_symbol = QLabel("")
    _label_symbol(laeuft_symbol, "hourglass", "", FARBEN["blau"], 14)
    laeuft_text = QLabel("")
    laeuft_text.setTextFormat(Qt.TextFormat.PlainText)
    ll.addWidget(laeuft_symbol, 0, Qt.AlignmentFlag.AlignTop)
    ll.addWidget(laeuft_text, 1)
    laeuft.hide()
    lay.addWidget(laeuft)

    # 2. Letzte Auftraege (ein-/ausklappbar). Der Kopf gesetzt wie der von
    # "Notizen für die KI" (linksbuendig, halbfett, Winkel rechts) —
    # Gegenpruefung K12: er stand rechtsbuendig in normaler Schrift (die
    # Richtung RightToLeft spiegelte auch seine Ausrichtung im Layout).
    kopf_a = QPushButton("Letzte Aufträge")
    kopf_a.setObjectName("abschnitt_knopf")
    kopf_a.setCheckable(True)
    kopf_a.setChecked(True)
    kopf_a.setCursor(Qt.CursorShape.PointingHandCursor)
    kopf_a.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    _knopf_symbol(kopf_a, "auf", text="Letzte Aufträge",
                  farbe=FARBEN["neben"], groesse=13)
    liste = QListWidget()
    liste.setObjectName("protokoll")
    liste.setAlternatingRowColors(True)
    liste.setUniformItemSizes(True)
    liste.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    liste.setMinimumHeight(60)
    liste.setIconSize(QSize(15, 15))
    liste.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    liste.setTextElideMode(Qt.TextElideMode.ElideRight)
    kopf_reihe = QHBoxLayout()
    kopf_reihe.setContentsMargins(0, 0, 0, 0)
    kopf_reihe.addWidget(kopf_a)
    kopf_reihe.addStretch(1)
    lay.addLayout(kopf_reihe)
    lay.addWidget(liste, 0)

    # 3. Notizen fuer die KI.
    teil, kl = _abschnitt("Notizen für die KI")
    erklaerung = QLabel("Eine Notiz wartet hier, bis die KI sie abholt.")
    erklaerung.setObjectName("neben")
    erklaerung.setWordWrap(True)
    kl.addWidget(erklaerung)
    verlauf = QScrollArea()
    verlauf.setObjectName("protokoll")
    verlauf.setWidgetResizable(True)
    verlauf.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    verlauf.setMinimumHeight(80)
    innen = QWidget()
    innen.setObjectName("protokoll_innen")
    zeilen = QVBoxLayout(innen)
    zeilen.setContentsMargins(0, 0, 0, 0)
    zeilen.setSpacing(0)
    zeilen.addStretch(1)
    verlauf.setWidget(innen)
    kl.addWidget(verlauf, 1)
    kontext = QLabel("Kein Element ausgewählt")
    kontext.setObjectName("chip")
    kl.addWidget(kontext, 0, Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(teil, 1)

    # 4. Ablegen-Zeile (gleiche Lage wie die Chat-Eingabe, anders aussehend).
    reihe = QHBoxLayout()
    reihe.setSpacing(6)

    def ablegen():
        text = z["w"]["post_eingabe"].text().strip()
        d = z["dienst"]
        if not text or d is None or d.beenden:
            return
        _auftrag(z, "nachricht_senden", {"text": text},
                 "Notiz in den Briefkasten")
        z["w"]["post_eingabe"].clear()

    feld = QLineEdit()
    feld.setPlaceholderText("Notiz für die KI ablegen …")
    feld.returnPressed.connect(lambda: _sicher(ablegen, "Ablegen"))
    btn = QPushButton("Ablegen")
    btn.setAccessibleName("Ablegen")
    btn.setToolTip("Die Notiz in den Briefkasten legen (Enter)")
    _knopf_symbol(btn, "ablegen", text="Ablegen", groesse=14)
    btn.clicked.connect(lambda: _sicher(ablegen, "Ablegen"))
    reihe.addWidget(feld, 1)
    reihe.addWidget(btn)
    lay.addLayout(reihe)

    kopf_a.toggled.connect(lambda an: _sicher(
        lambda: _auftraege_klappen(z, an), "Letzte Aufträge"))
    z["w"].update(briefkasten_seite=seite, briefkasten_laeuft=laeuft,
                  briefkasten_laeuft_text=laeuft_text,
                  auftraege_kopf=kopf_a, liste_auftraege=liste,
                  post_verlauf=verlauf, post_eingabe=feld, post_senden=btn,
                  post_kontext=kontext)
    return seite


def _auftraege_klappen(z, an):
    w = z["w"]
    w["liste_auftraege"].setVisible(an)
    _knopf_symbol(w["auftraege_kopf"], "auf" if an else "zu",
                  text="Letzte Aufträge", farbe=FARBEN["neben"], groesse=14)


def _einstellungen_bauen(z):
    """Die EINE Einstellungsseite (Spezifikation 3.6, Index 2 des Stapels):
    "← Zurück", der Hinweis auf eine wartende Freigabe, dann die Karten
    Chat (Anbieter, Schluessel, Modelle, lokale Modelle — legt `_tab_chat`
    in `einst_chat_lay`), Verbindung (Steckplatz, Karten), Zeichenmodus und
    Technik-Details (Chat und Verbindung zusammen, aufklappbar). Nichts
    Modales: ein modales Fenster haelt in Cadwork die
    Auftragswarteschlange an (test_a_live L6). -> die Seite (Rollbereich)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                                 QScrollArea, QVBoxLayout, QWidget)
    innen = QWidget()
    innen.setObjectName("rollinhalt")
    lay = QVBoxLayout(innen)
    lay.setContentsMargins(0, 2, 4, 0)
    lay.setSpacing(10)

    kopf = QHBoxLayout()
    zurueck = QPushButton("Zurück")
    zurueck.setObjectName("flach")
    zurueck.setAccessibleName("Zurück")
    zurueck.setToolTip("Zurück zum Chat bzw. Briefkasten")
    _knopf_symbol(zurueck, "zurueck", text="Zurück", groesse=14)
    titel = QLabel("Einstellungen")
    titel.setObjectName("titel")
    kopf.addWidget(zurueck)
    kopf.addWidget(titel)
    kopf.addStretch(1)
    lay.addLayout(kopf)

    # Wartet der Chat auf eine Freigabe, steht es hier (Pruefung
    # 2026-09-26: vorher sah man es auf den Einstellungen nicht).
    freigabe = QWidget()
    fl = QHBoxLayout(freigabe)
    fl.setContentsMargins(0, 0, 0, 0)
    freigabe_text = QLabel("Der Chat wartet auf deine Freigabe.")
    freigabe_text.setWordWrap(True)
    zum_chat = QPushButton("Zum Chat")
    zum_chat.setObjectName("hinweis")
    zum_chat.setToolTip("Zum Chat — die Freigabe dort beantworten")
    fl.addWidget(freigabe_text, 1)
    fl.addWidget(zum_chat)
    freigabe.hide()
    lay.addWidget(freigabe)

    # Karte "Chat": `_tab_chat` legt sie hier ab.
    platz = QVBoxLayout()
    platz.setSpacing(10)
    lay.addLayout(platz)

    # Alle vier Abschnitte als GLEICHE Karten mit gleich gesetztem Titel
    # (Spezifikation 3.6; Gegenpruefung K12: nur "Chat" war eine Karte,
    # "Verbindung" und "Zeichenmodus" standen frei, "Technik-Details" war
    # ein Link am rechten Rand).
    teil_v, kl_v = _karte("Verbindung")
    _teil_verbindungen(z, kl_v)
    lay.addWidget(teil_v)

    teil_m, kl_m = _karte("Zeichenmodus")
    _teil_modus(z, kl_m)
    lay.addWidget(teil_m)

    # Technik-Details: zugeklappt. Was darin steht (Port, Pfade, Sitzung,
    # Server-Python, Codex-Ordner; dazu wer antwortet und was laeuft),
    # braucht nur, wer einen Fehler sucht. Der Titel der Karte klappt.
    teil_t, kl_t = _karte("")
    knopf_t = QPushButton("Technik-Details")
    knopf_t.setObjectName("karte_titel")
    knopf_t.setCursor(Qt.CursorShape.PointingHandCursor)
    knopf_t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    _knopf_symbol(knopf_t, "zu", text="Technik-Details",
                  farbe=FARBEN["neben"], groesse=14)
    knopf_t.setToolTip("Port, Pfade, Sitzung, Server-Python — für die "
                       "Fehlersuche")
    technik = QLabel("")
    technik.setObjectName("neben")
    technik.setWordWrap(True)
    technik.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    technik.hide()
    kopf_t = QHBoxLayout()
    kopf_t.setContentsMargins(0, 0, 0, 0)
    kopf_t.addWidget(knopf_t)
    kopf_t.addStretch(1)
    kl_t.addLayout(kopf_t)
    kl_t.addWidget(z["w"]["steckplatz_reihe"])
    kl_t.addWidget(technik)
    technik_platz = QVBoxLayout()
    kl_t.addLayout(technik_platz)
    lay.addWidget(teil_t)
    lay.addStretch(1)

    seite = QScrollArea()
    seite.setObjectName("rolle")
    seite.setWidgetResizable(True)
    seite.setFrameShape(QScrollArea.Shape.NoFrame)
    seite.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    seite.setWidget(innen)
    # Die alten Namen (Steuerfenster `einst_*`, Chatfenster `chat_einst_*`)
    # zeigen auf diese EINE Seite (Spezifikation 3.6).
    z["w"].update(einst_seite=seite, chat_einst_seite=seite,
                  einst_zurueck=zurueck, chat_einst_fertig=zurueck,
                  einst_freigabe=freigabe, chat_einst_freigabe=freigabe,
                  einst_zum_chat=zum_chat, einst_chat_lay=platz,
                  einst_technik_lay=technik_platz, technik_knopf=knopf_t,
                  technik=technik, einst_titel=titel,
                  einst_karte_verbindung=teil_v, einst_karte_modus=teil_m,
                  einst_karte_technik=teil_t)
    zurueck.clicked.connect(lambda: _sicher(
        lambda: _einstellungen_zeigen(z, False), "Zurück"))
    zum_chat.clicked.connect(lambda: _sicher(lambda: _zum_chat(z),
                                             "Zum Chat"))
    knopf_t.clicked.connect(lambda: _sicher(lambda: _technik_umschalten(z),
                                            "Technik-Details"))
    return seite


# --- Fuehren: Zustand, Segment, Hinweise ------------------------------------

def _fenster_zustand_ist(z):
    """Der Zustand, wie er gemerkt ist — berichtigt um das, was das Dock
    tatsaechlich ist (etwa nach einem Abloesen durch Qt)."""
    dock = z.get("fenster")
    zustand = z.get("fenster_zustand")
    if zustand not in FENSTER_ZUSTAENDE:
        zustand = PILLE_Z
    try:
        if dock is not None and dock.isFloating() and zustand == ANGEDOCKT_Z:
            zustand = OFFEN_Z
        elif dock is not None and not dock.isFloating() \
                and zustand != ANGEDOCKT_Z and dock.isVisible():
            zustand = ANGEDOCKT_Z
    except RuntimeError:                       # schon abgeraeumt
        pass
    return zustand


def _seite_jetzt(z):
    """Was im Koerper vorn steht: chat, briefkasten oder einstellungen."""
    w = z["w"]
    seiten, einst = w.get("seiten"), w.get("einst_seite")
    if seiten is not None and einst is not None \
            and seiten.currentWidget() is einst:
        return "einstellungen"
    seg = z.get("segment")
    return seg if seg in SEGMENTE else "chat"


def _fenster_aktion(z, aktion):
    """Eine Aktion auf das Fenster (Knopf im Kopf, Plugin-Klick, Hinweis-
    Zahl): rechnet mit `_fenster_uebergang` und fuehrt es aus.
    -> der neue Zustand (oder None ohne Fenster)."""
    dock = z.get("fenster")
    if dock is None:
        return None
    zustand = _fenster_zustand_ist(z)
    seite = _seite_jetzt(z)
    erg = _fenster_uebergang(zustand, aktion, seite)
    if erg["segment"] != seite and erg["segment"] in SEGMENTE:
        _segment_waehlen(z, erg["segment"], fokus=False)
    neu = erg["zustand"]
    if neu != zustand or dock.isHidden():
        _zustand_setzen(z, neu)
    elif aktion == "klick":
        # Nach vorn — und ein schwebendes nie neben allen Bildschirmen (ein
        # zweiter wurde abgesteckt).
        _fenster_zurueckholen(z)
    if erg["hinweise"] == "auf":
        _hinweise_zeigen(z, True)
    elif erg["hinweise"] == "um":
        _hinweise_zeigen(z)
    try:
        dock.raise_()
    except RuntimeError:                       # schon abgeraeumt
        return None
    if erg["fokus"]:
        _eingabe_fokus(z)
    _kopf_zeigen(z)
    return neu


def _eingabe_fokus(z):
    """Die Eingabe des Chats fokussieren (wenn der Chat vorn steht)."""
    dock = z.get("fenster")
    feld = z["w"].get("chat_eingabe")
    if feld is None or dock is None:
        return False
    try:
        if dock.isFloating():
            dock.activateWindow()
        feld.setFocus()
    except RuntimeError:                       # schon abgeraeumt
        return False
    return True


def _zustand_setzen(z, neu):
    """Das Fenster in einen der drei Zustaende bringen — nur Sichtbarkeit
    des Koerpers, Schweben/Andocken und (danach, `_fenster_lage`) Geometrie;
    nie wird etwas umgehaengt. Beim Wechsel zur Pille ZUERST der Koerper weg
    (kein Aufblitzen eines grossen leeren Fensters)."""
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import QMainWindow
    dock = z["fenster"]
    koerper = z["w"]["koerper"]
    haupt = dock.parentWidget()
    if not isinstance(haupt, QMainWindow):
        haupt = None
    if neu == ANGEDOCKT_Z and haupt is None:
        neu = OFFEN_Z                          # ohne Hauptfenster kein Dock
    alt = z.get("fenster_zustand")
    # Wo die Pille steht (rechte Kante, Oberkante; nur aus der Pille — ein
    # offenes Fenster, das nach oben wachsen musste, verschiebt den Ort der
    # Pille nicht), wie gross das offene Fenster war, wie breit das
    # angedockte: fuer den naechsten Wechsel. Zieht der Nutzer, merkt der
    # Kopf den neuen Ort selbst (Loslassen).
    if alt == PILLE_Z:
        _pille_ort_merken(z)
    try:
        if alt == OFFEN_Z and dock.isFloating() and dock.isVisible():
            soll = z.get("offen_soll")
            ist = (dock.width(), dock.height())
            if soll is not None and ist != tuple(soll):
                z["offen_groesse"] = ist
        if alt == ANGEDOCKT_Z and not dock.isFloating() and dock.isVisible():
            z["angedockt_breite"] = dock.width()
    except RuntimeError:                       # schon abgeraeumt
        return None
    z["fenster_zustand"] = neu
    z["fenster_versteckt_selbst"] = True
    try:
        if neu == PILLE_Z:
            koerper.hide()
            if not dock.isFloating():
                dock.setFloating(True)
        elif neu == OFFEN_Z:
            koerper.show()
            if not dock.isFloating():
                dock.setFloating(True)
        else:
            koerper.show()
            if dock.isFloating():
                dock.setFloating(False)
            # EINE eigene Spalte neben Cadworks Docks (Horizontal) — nie in
            # Reitern, nie gestapelt (Spezifikation 1.3, Bild 6/7).
            haupt.addDockWidget(_bereich(z.get("angedockt_bereich")), dock,
                                Qt.Orientation.Horizontal)
        # Schwebend rund, angedockt ohne Maske — VOR dem Zeigen.
        _fenster_maske(z)
        dock.show()
    finally:
        z["fenster_versteckt_selbst"] = False
    _kopf_zeigen(z)
    # Groesse und Ort erst, wenn Qt fertig ist (K10: nie im Signal).
    QTimer.singleShot(0, lambda: _sicher(lambda: _fenster_lage(z),
                                         "Fenster setzen"))
    return neu


def _abloesen_beim_ziehen(z):
    """Ziehen am Kopf eines angedockten Fensters: es wird "offen" und folgt
    der Maus. Gesetzt wird nur die Groesse (`_fenster_lage` sieht die
    gedrueckte Maustaste)."""
    dock = z["fenster"]
    z["angedockt_breite"] = dock.width()
    z["fenster_zustand"] = OFFEN_Z
    z["w"]["koerper"].show()
    z["fenster_versteckt_selbst"] = True
    try:
        dock.setFloating(True)
    finally:
        z["fenster_versteckt_selbst"] = False
    _fenster_maske(z)
    _kopf_zeigen(z)


def _pille_ort_merken(z):
    """Rechte Kante und Oberkante des SCHWEBENDEN Fensters merken — dort
    steht der Kopf, und dort steht er nach jedem Wechsel wieder."""
    dock = z.get("fenster")
    try:
        if dock is None or not dock.isFloating() or not dock.isVisible():
            return None
        g = dock.frameGeometry()
        z["pille_ort"] = (g.left() + g.width(), g.top())
    except RuntimeError:                       # schon abgeraeumt
        return None
    return z["pille_ort"]


def _segment_waehlen(z, segment, fokus=True):
    """Chat oder Briefkasten nach vorn (gemerkt fuer die Sitzung)."""
    w = z["w"]
    if segment not in SEGMENTE:
        segment = "chat"
    z["segment"] = segment
    seiten = w.get("seiten")
    if seiten is None:
        return segment
    ziel = w.get("briefkasten_seite") if segment == "briefkasten" \
        else seiten.widget(0)
    if ziel is not None and seiten.currentWidget() is not ziel:
        seiten.setCurrentWidget(ziel)
    knopf = w.get("segment_" + segment)
    if knopf is not None and not knopf.isChecked():
        knopf.setChecked(True)
    if fokus and segment == "chat":
        _eingabe_fokus(z)
    _hinweis_antwort_zeigen(z)
    _kopf_zeigen(z)
    return segment


def _seite_gewechselt(z):
    """Der Stapel zeigt eine andere Seite: die Segmentknoepfe folgen (auf
    der Einstellungsseite ist keiner gewaehlt), offene Technik-Details
    werden sofort neu gelesen."""
    w = z["w"]
    gruppe = w.get("segment_gruppe")
    if gruppe is not None:
        einst = _seite_jetzt(z) == "einstellungen"
        if einst:
            # Auf der Einstellungsseite ist kein Segment gewaehlt.
            gruppe.setExclusive(False)
            for name in SEGMENTE:
                b = w.get("segment_" + name)
                if b is not None and b.isChecked():
                    b.setChecked(False)
        else:
            gruppe.setExclusive(True)
            b = w.get("segment_" + (z.get("segment") or "chat"))
            if b is not None and not b.isChecked():
                b.setChecked(True)
    if _einstellungen_sichtbar(z) and w.get("technik") is not None \
            and not w["technik"].isHidden():
        _technik_anstossen(z, sofort=True)
    _kopf_zeigen(z)


def _hinweise_zeigen(z, an=None):
    """Den Hinweis-Bereich auf- oder zuklappen (None = um), in beiden
    Segmenten. Gemerkt fuer die Sitzung."""
    w = z["w"]
    bereich = w.get("hinweise_bereich")
    if bereich is None:
        return None
    if an is None:
        an = bereich.isHidden()
    z["hinweise_offen"] = bool(an)
    bereich.setVisible(bool(an))
    knopf = w.get("hinweise_knopf")
    if knopf is not None and knopf.isChecked() != bool(an):
        knopf.setChecked(bool(an))
    _hoechstmasse(z)
    return bool(an)


def _hoechstmasse(z):
    """Hinweise hoechstens HINWEISE_ANTEIL des Koerpers, "Letzte Aufträge"
    hoechstens AUFTRAEGE_ANTEIL der Seite des Briefkastens."""
    w = z["w"]
    koerper, bereich = w.get("koerper"), w.get("hinweise_bereich")
    if koerper is not None and bereich is not None:
        teile = w.get("hinweise") or {}
        anteil = (HINWEISE_ANTEIL_WAHL if teile.get("gewaehlt_nr")
                  is not None else HINWEISE_ANTEIL)
        h = max(HINWEISE_MIN, int(koerper.height() * anteil))
        if bereich.maximumHeight() != h:
            bereich.setMaximumHeight(h)
        _hinweise_masse(z)
    seite, liste = w.get("briefkasten_seite"), w.get("liste_auftraege")
    if seite is not None and liste is not None:
        # So hoch wie ihr Inhalt, hoechstens AUFTRAEGE_ANTEIL (Gegenpruefung
        # K12: unter drei Zeilen blieb eine grosse leere Flaeche).
        zeile = max(liste.sizeHintForRow(0), 20) if liste.count() else 24
        inhalt = zeile * max(1, liste.count()) + 2 * liste.frameWidth() + 2
        h = max(28, min(inhalt, int(seite.height() * AUFTRAEGE_ANTEIL)))
        if liste.maximumHeight() != h or liste.minimumHeight() != h:
            liste.setMinimumHeight(h)
            liste.setMaximumHeight(h)


def _hoehe_fuer_breite(widget, breite):
    """Wie hoch `widget` bei `breite` sein will (Umbruch eingerechnet)."""
    if widget.hasHeightForWidth():
        return max(0, widget.heightForWidth(breite))
    return widget.sizeHint().height()


def _hinweise_masse(z):
    """Die Liste der Hinweise in VOLLER Hoehe (kein eigenes Rollen, jeder
    Hinweis ganz umbrochen) und der Rollbereich darum so hoch wie sein
    Inhalt — den Deckel setzt `HINWEISE_ANTEIL` am Bereich; was darueber
    hinausgeht, rollt als Ganzes (Gegenpruefung Laien-Sicht K12: die
    Liste rollte in einem Streifen von rund 100 px, ein Hinweis stand
    halb abgeschnitten darin). -> (Liste, Inhalt) in px oder None."""
    w = z["w"]
    liste, rolle = w.get("hinweise_liste"), w.get("hinweise_rolle")
    teile = w.get("hinweise")
    if liste is None or rolle is None or teile is None:
        return None
    try:
        breite = rolle.viewport().width()
        rand = 2 * liste.frameWidth()
        h_liste = _hoehe_fuer_breite(teile["innen"],
                                     max(60, breite - rand)) + rand
        if liste.minimumHeight() != h_liste \
                or liste.maximumHeight() != h_liste:
            liste.setFixedHeight(h_liste)
        tab = rolle.widget()
        if tab.layout() is not None:
            tab.layout().activate()
        inhalt = _hoehe_fuer_breite(tab, breite) + 2 * rolle.frameWidth()
        unten = min(inhalt, 120)
        if rolle.maximumHeight() != inhalt or rolle.minimumHeight() != unten:
            rolle.setMinimumHeight(unten)
            rolle.setMaximumHeight(inhalt)
        return (h_liste, inhalt)
    except RuntimeError:                       # schon abgeraeumt
        return None


def _mehr_aufklappen(z):
    """"⋯": Einstellungen, Pausieren/Fortsetzen, Nach Auftrag trennen,
    Anleitung, Technik-Details (nach unten, rechtsbuendig)."""
    w = z["w"]
    return _aufklapper_zeigen(z, w["mehr_auf"], w["mehr_menue"],
                              nach_oben=False, rechts=True)


def _technik_zeigen(z):
    """"⋯ → Technik-Details": die Einstellungsseite, Technik aufgeklappt."""
    _einstellungen_zeigen(z, True)
    w = z["w"]
    if w["technik"].isHidden():
        _technik_umschalten(z)
    seite = w.get("einst_seite")
    try:
        seite.ensureWidgetVisible(w["technik_knopf"])
    except Exception:                                  # noqa: BLE001
        pass


def _kopf_zeigen(z):
    """Der Kopf je Zustand (Spezifikation 2.1): Verkleinern nur offen und
    angedockt, Andocken als "Abdocken" (gedrueckt) angedockt, der
    Chat-Knopf "aktiv", wenn der Chat vorn zu sehen ist; Rand und Rundung
    von Kopf und Koerper ueber die Eigenschaft `zustand`."""
    w = z["w"]
    kopf = w.get("kopf")
    if kopf is None:
        return None
    zustand = _fenster_zustand_ist(z)
    for teil in (kopf, w.get("koerper")):
        if teil is not None and teil.property("zustand") != zustand:
            teil.setProperty("zustand", zustand)
            teil.style().unpolish(teil)
            teil.style().polish(teil)
            teil.update()
    klein = w.get("kopf_verkleinern")
    if klein is not None and klein.isHidden() != (zustand == PILLE_Z):
        klein.setVisible(zustand != PILLE_Z)
    andocken = w.get("kopf_andocken")
    if andocken is not None:
        an = zustand == ANGEDOCKT_Z
        name = "Abdocken" if an else "Rechts andocken"
        if andocken.accessibleName() != name:
            andocken.setAccessibleName(name)
            andocken.setToolTip(ABDOCKEN_TIPP if an else ANDOCKEN_TIPP)
            _knopf_symbol(andocken, "abdocken" if an else "andocken",
                          farbe=FARBEN["neben"])
        if andocken.isChecked() != an:
            andocken.setChecked(an)
    _chip_zeigen(z, zustand)
    chat = w.get("kopf_chat")
    if chat is not None:
        aktiv = ("ja" if zustand != PILLE_Z and _seite_jetzt(z) == "chat"
                 else "nein")
        if chat.property("aktiv") != aktiv:
            chat.setProperty("aktiv", aktiv)
            chat.style().unpolish(chat)
            chat.style().polish(chat)
    return zustand


# --- Lage: Groesse und Ort (nie im Signal, K10) -----------------------------

def _fenster_schwebt(z, schwebt):
    """Qt meldet: das Fenster schwebt jetzt bzw. ist angedockt. Hier wird
    NIE verschoben oder bemessen (das Signal kommt mitten aus `setFloating`,
    danach loescht Qt WA_Moved — Windows setzte das Fenster in die Mitte,
    gemessen K10); nur gemerkt, die Lage folgt in `_fenster_lage`."""
    from PyQt6.QtCore import QTimer
    if not schwebt:
        z["fenster_zustand"] = ANGEDOCKT_Z
    elif z.get("fenster_zustand") == ANGEDOCKT_Z:
        z["fenster_zustand"] = OFFEN_Z
    # Die Maske (kein Ort, keine Groesse) gleich: auch wenn Qt selbst
    # andockt oder abloest.
    _fenster_maske(z)
    QTimer.singleShot(0, lambda: _sicher(lambda: _fenster_lage(z),
                                         "Fenster setzen"))
    return z["fenster_zustand"]


def _fenster_maske(z):
    """Runde Ecken OHNE Durchsichtigkeit (gemessen in Cadwork 2026-10-08):
    schwebend schneidet eine Maske das Fenster auf die runde Karte zu (das
    Rechteck ohne den Rahmen des schwebenden Docks, Rundung wie im QSS);
    angedockt KEINE Maske — das Fenster fuellt seine Spalte deckend. Nie
    Ort oder Groesse (darf im Signal laufen).
    -> "rund", "angedockt" oder None."""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QPainterPath, QRegion
    from PyQt6.QtWidgets import QStyle
    dock = z.get("fenster")
    if dock is None:
        return None
    try:
        schwebt = dock.isFloating()
    except RuntimeError:                       # schon abgeraeumt
        return None
    if not schwebt:
        if not dock.mask().isEmpty():
            dock.clearMask()
        return ANGEDOCKT_Z
    rand = dock.style().pixelMetric(
        QStyle.PixelMetric.PM_DockWidgetFrameWidth, None, dock)
    karte = QRectF(dock.rect()).adjusted(rand, rand, -rand, -rand)
    if karte.width() <= 0 or karte.height() <= 0:
        return None
    pfad = QPainterPath()
    pfad.addRoundedRect(karte, FENSTER_RUNDUNG, FENSTER_RUNDUNG)
    maske = QRegion(pfad.toFillPolygon().toPolygon())
    if dock.mask() != maske:
        dock.setMask(maske)
    return "rund"


def _masken_filter(z, dock):
    """Ein Ereignisfilter am Fenster: bei jeder Groessenaenderung und beim
    Zeigen die Maske neu (`_fenster_maske`). Wirft nie (eine Ausnahme aus
    einer virtuellen Methode waere in Cadwork qFatal). -> der Filter."""
    from PyQt6.QtCore import QEvent, QObject

    class Masken(QObject):
        def eventFilter(self, _obj, ereignis):     # noqa: N802
            try:
                if ereignis.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                    _sicher(lambda: _fenster_maske(z), "Fenster runden")
            except Exception as exc:              # noqa: BLE001
                _melden("Fenster runden", exc)
            return False

    filt = Masken(dock)
    dock.installEventFilter(filt)
    return filt


def _pille_groesse(z):
    """(breite, hoehe) der Pille: so gross wie der Kopf, dazu der Rahmen
    des schwebenden Docks — je Plattform anders (gemessen: Windows 2 px je
    Seite, offscreen 1 px), also aus der Mindestgroesse des Docks
    gerechnet, nicht fest."""
    dock, kopf = z["fenster"], z["w"]["kopf"]
    kopf.ensurePolished()
    # Kopf UND Dock jetzt neu auslegen: sonst gilt eine Mindest- und
    # Hoechstbreite des Docks von vorher, und Qt setzt die Breite erst beim
    # naechsten Durchlauf der Ereignisschleife — mit fester LINKER Kante
    # (gemessen: die Pille stand danach 4 px links von ihrem Ort).
    for teil in (kopf, dock):
        if teil.layout() is not None:
            teil.layout().invalidate()
            teil.layout().activate()
    hint, kmin = kopf.sizeHint(), kopf.minimumSizeHint()
    dmin = dock.minimumSizeHint()
    if dock.isFloating() and dock.widget() is not None \
            and dock.widget().isHidden():
        rand_b = max(0, dmin.width() - kmin.width())
        rand_h = max(0, dmin.height() - kmin.height())
    else:
        rand_b = rand_h = 4
    return (max(hint.width() + rand_b, dmin.width()),
            max(KOPF_HOEHE, hint.height()) + rand_h)


def _offen_groesse(z, oben, hr):
    """(breite, hoehe) des offenen Fensters, wenn der Kopf bei `oben`
    steht: OFFEN_BREITE (oder was der Nutzer in der Sitzung gezogen hat),
    bis RAND_UNTEN ueber dem unteren Rand des Hauptfensters (`hr`),
    mindestens OFFEN_HOEHE_MIN."""
    gemerkt = z.get("offen_groesse")
    breite = OFFEN_BREITE
    hoehe = None
    if gemerkt:
        breite, hoehe = gemerkt
    breite = max(OFFEN_BREITE_MIN, int(breite))
    if hoehe is None:
        hoehe = (hr.top() + hr.height() - RAND_UNTEN - oben
                 if hr is not None else OFFEN_HOEHE_MIN)
    return breite, max(OFFEN_HOEHE_MIN, int(hoehe))


def _fenster_lage(z, vor_show=False):
    """Groesse und Ort des Fensters nach seinem Zustand — NACH
    `setFloating`/`show()` (ueber `singleShot(0)`) oder, beim ersten Bau,
    VOR dem Zeigen (`vor_show`). Schwebend: der Kopf steht an seinem Ort
    (`pille_ort`: rechte Kante und Oberkante, sonst oben rechts im
    Hauptfenster); die Pille so gross wie der Kopf, offen waechst der
    Koerper nach unten bis RAND_UNTEN ueber dem unteren Rand des
    Hauptfensters — reicht der Platz nicht fuer OFFEN_HOEHE_MIN, waechst es
    nach oben (nur dann rueckt der Kopf mit). Angedockt: eine Spalte, keine
    Reiter (`_angedockt_pruefen`). Jede Platzierung als Zeile "Fenster: …"
    ins Log; danach sieht das Dock zweimal nach (`_ort_spaeter`).
    -> "pille", "offen", "angedockt", "gezogen" oder None."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    dock = z.get("fenster")
    if dock is None:
        return None
    try:
        sichtbar, schwebt = dock.isVisible(), dock.isFloating()
    except RuntimeError:                       # schon abgeraeumt
        return None
    if not sichtbar and not vor_show:
        return None
    zustand = _fenster_zustand_ist(z)
    _kopf_zeigen(z)
    if not schwebt:
        _angedockt_pruefen(z)
        return ANGEDOCKT_Z
    haupt = _hauptfenster()
    hr = _haupt_rahmen(haupt) if haupt is not None else _schirm()
    if not vor_show and QGuiApplication.mouseButtons() \
            != Qt.MouseButton.NoButton:
        # Der Nutzer zieht (etwa ein eben abgeloestes Fenster): nur die
        # Groesse, der Ort gehoert ihm.
        if zustand == PILLE_Z:
            breite, hoehe = _pille_groesse(z)
        else:
            breite, hoehe = _offen_groesse(z, dock.y(), hr)
            z["offen_soll"] = (breite, hoehe)
        dock.resize(breite, hoehe)
        return "gezogen"
    ort = z.get("pille_ort")
    if ort is not None:
        rechts, oben = ort
        grund, ganz = "Ort aus dieser Sitzung", False
    else:
        # Zum ersten Mal: oben rechts im Hauptfenster, gerechnet mit der
        # Breite der Pille (dort steht der Kopf).
        dock.resize(*_pille_groesse(z))
        x0, oben, grund = _monitor_ziel(z, dock)
        rechts = x0 + max(dock.frameGeometry().width(), dock.width())
        ganz = True
    if zustand == PILLE_Z:
        breite, hoehe = _pille_groesse(z)
    else:
        breite, hoehe = _offen_groesse(z, oben, hr)
    x, y = rechts - breite, oben
    if zustand == OFFEN_Z:
        s = _schirm(_punkt(rechts - 10, oben + 10))
        unten = s.top() + s.height() if s is not None else None
        if unten is not None and y + hoehe > unten:
            if unten - y >= OFFEN_HOEHE_MIN:
                # Reicht das Hauptfenster unter den Bildschirm: bis zu
                # dessen Rand.
                hoehe = unten - y
            else:
                # Nach unten reicht es nicht fuer die Mindesthoehe: nach
                # oben wachsen, der Kopf rueckt mit (nur in diesem Fall,
                # Spezifikation 1.3).
                y = max(s.top(), unten - hoehe)
                grund += ", nach oben gewachsen"
        z["offen_soll"] = (breite, hoehe)
        # Offen immer GANZ auf einen Bildschirm: steht die Pille nah am
        # linken Rand, rueckt das Fenster nach rechts (der Kopf dann mit) —
        # sonst ragte es ueber den Rand (Gegenpruefung K9, L79).
        ganz = True
    dock.resize(breite, hoehe)
    _schwebend_setzen(dock, x, y, ganz=ganz)
    z["fenster_soll"] = (dock.x(), dock.y())
    if zustand == PILLE_Z or ort is None:
        g = dock.frameGeometry()
        z["pille_ort"] = (g.left() + g.width(), g.top())
    z["fenster_gezogen"] = False
    _ort_protokoll(z, "%s gesetzt (%s): %s" % (zustand, grund,
                                               _lage_text(dock)))
    _ort_spaeter(z, "fenster", "fenster_soll", "Fenster")
    return zustand


def _punkt(x, y):
    from PyQt6.QtCore import QPoint
    return QPoint(int(x), int(y))


def _angedockt_pruefen(z):
    """Angedockt: steht das Fenster in Reitern mit einem anderen Dock (Bild
    6), nimmt es sich heraus und kommt als eigene Spalte zurueck (einmal,
    mit Logzeile); danach die Breite (`resizeDocks`). Cadworks `setCorner`
    bleibt, wie es ist."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMainWindow
    dock = z["fenster"]
    haupt = dock.parentWidget()
    if not isinstance(haupt, QMainWindow):
        return None
    reiter = haupt.tabifiedDockWidgets(dock)
    if reiter:
        _ort_protokoll(z, "angedockt in Reitern mit %s — als eigene Spalte "
                          "neu angedockt" % ", ".join(
                              d.objectName() or "?" for d in reiter))
        z["fenster_versteckt_selbst"] = True
        try:
            haupt.removeDockWidget(dock)
            haupt.addDockWidget(_bereich(z.get("angedockt_bereich")), dock,
                                Qt.Orientation.Horizontal)
            dock.show()
        finally:
            z["fenster_versteckt_selbst"] = False
    breite = max(ANGEDOCKT_BREITE_MIN,
                 int(z.get("angedockt_breite") or ANGEDOCKT_BREITE))
    haupt.resizeDocks([dock], [breite], Qt.Orientation.Horizontal)
    _ort_protokoll(z, "angedockt gesetzt (%s, %d px): %s" % (
        "links" if haupt.dockWidgetArea(dock)
        == Qt.DockWidgetArea.LeftDockWidgetArea else "rechts", breite,
        _lage_text(dock)))
    return breite


def _kopf_anpassen(z):
    """Die Pille so breit wie ihr Kopf — die RECHTE Kante bleibt (am Ort
    der Pille), auch wenn der Text wechselt ("Bereit" -> "Zeichnet"). Qt
    vergroessert ein Fenster, dessen Mindestgroesse waechst, und laesst
    dabei die LINKE Kante stehen (gemessen K11) — darum zaehlt der gemerkte
    Ort, nicht der jetzige. Nicht, solange der Nutzer zieht.
    -> neue (breite, hoehe) oder None."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    dock = z.get("fenster")
    kopf = z["w"].get("kopf")
    if dock is None or kopf is None:
        return None
    try:
        if not dock.isVisible() or not dock.isFloating() \
                or _fenster_zustand_ist(z) != PILLE_Z \
                or getattr(kopf, "gezogen", lambda: False)() \
                or QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return None
    except RuntimeError:                       # schon abgeraeumt
        return None
    breite, hoehe = _pille_groesse(z)
    ort = z.get("pille_ort")
    g = dock.frameGeometry()
    rechts = ort[0] if ort else g.left() + g.width()
    if (dock.width(), dock.height()) == (breite, hoehe) \
            and g.left() + g.width() == rechts:
        return None
    dock.resize(breite, hoehe)
    dock.move(rechts - max(dock.frameGeometry().width(), breite), dock.y())
    z["fenster_soll"] = (dock.x(), dock.y())
    return (breite, hoehe)


def _fenster_zurueckholen(z):
    """Das schwebende Fenster ganz auf einen Bildschirm (Plugin-Klick)."""
    dock = z.get("fenster")
    if dock is not None and dock.isFloating() and dock.isVisible():
        _schwebend_setzen(dock, dock.x(), dock.y(), ganz=False)
        _pille_ort_merken(z)


def _fenster_sichtbar(z, dock, sichtbar):
    """Qt meldet: das Fenster ist (nicht mehr) zu sehen. Hat Cadwork es
    geschlossen (Kontextmenue der Docks, Alt+F4) — nicht wir selbst
    (`fenster_versteckt_selbst`) —, steht danach die Pille. Im Signal selbst
    nichts zeigen oder verschieben (K10). -> nachgesehen?"""
    from PyQt6.QtCore import QTimer
    if sichtbar or z.get("fenster_versteckt_selbst"):
        return False
    QTimer.singleShot(0, lambda: _sicher(
        lambda: _pille_statt_nichts(z, dock), "Fenster schliessen"))
    return True


def _pille_statt_nichts(z, dock):
    """Das Fenster ist zu (ausdruecklich versteckt — ein Reiter neben einem
    anderen Dock oder ein minimiertes Cadwork ist es nicht): dann die
    Pille. Nur fuer den LEBENDEN Zustand (Anker) und dasselbe Dock.
    -> True, wenn die Pille gezeigt wurde."""
    anker = sys.modules.get(ANKER)
    if getattr(anker, "z", None) is not z or z.get("fenster") is not dock:
        return False
    try:
        if not dock.isHidden():
            return False
    except RuntimeError:                       # schon abgeraeumt
        return False
    _zustand_setzen(z, PILLE_Z)
    _ort_protokoll(z, "von aussen geschlossen — wieder als Pille")
    return True


def _verbunden_ist(z):
    """Laeuft ein Dienst (auch einer, der gerade startet)? Wie im Takt."""
    d = z.get("dienst")
    return d is not None and not d.beenden and d.zustand != "stopped"


def _schliessen_zeigen(z, verbunden):
    """Das "×" im Kopf nur ohne Verbindung (nie verbunden oder getrennt).
    Mit ihm ruecken die Teile des Kopfs enger (KOPF_ABSTAND_ENG): sonst
    waere der Kopf offen/angedockt breiter als ANGEDOCKT_BREITE_MIN
    (gemessen 348 statt 320 px, test_a_live L59). -> sichtbar?"""
    zu = z["w"].get("kopf_schliessen")
    if zu is None:
        return False
    if zu.isHidden() != bool(verbunden):
        zu.setVisible(not verbunden)
    kopf = z["w"].get("kopf")
    lay = kopf.layout() if kopf is not None else None
    abstand = KOPF_ABSTAND if verbunden else KOPF_ABSTAND_ENG
    if lay is not None and lay.spacing() != abstand:
        lay.setSpacing(abstand)
    return not verbunden


def _fenster_schliessen(z):
    """Das "×" im Kopf (Rueckmeldung 2026-10-08): ohne Verbindung das
    Fenster GANZ schliessen — auch die Pille. Abgebaut wie bei einem
    Update (`_dock_abbauen`): Takte gestoppt, Arbeitsanzeige und Haken weg;
    dazu der Hintergrundthread der Steckplaetze. Der naechste Plugin-Klick
    baut das Fenster neu (als Pille) und verbindet wie immer. Verbunden
    passiert nichts — dort gibt es kein "×", und "Trennen" laesst das
    Fenster stehen. -> geschlossen?"""
    if _verbunden_ist(z):
        return False
    z["fenster_zustand"] = PILLE_Z
    _ort_protokoll(z, "geschlossen (×) — der nächste Klick zeigt die Pille")
    z["monitor_an"] = False
    _dock_abbauen(z)
    return True


def _andocken_umschalten(z):
    """Der Knopf "Rechts andocken"/"Abdocken" im Kopf (alte Name)."""
    return _fenster_aktion(z, "andocken")


def _verkleinern(z):
    """"Verkleinern" im Kopf: zur Pille (alter Name)."""
    return _fenster_aktion(z, "verkleinern")


def _bereich(wert, vorgabe="rechts"):
    """Der gemerkte Dock-Bereich als Qt.DockWidgetArea (sonst rechts)."""
    from PyQt6.QtCore import Qt
    for b in (Qt.DockWidgetArea.LeftDockWidgetArea,
              Qt.DockWidgetArea.RightDockWidgetArea):
        if wert == b.value:
            return b
    return (Qt.DockWidgetArea.LeftDockWidgetArea if vorgabe == "links"
            else Qt.DockWidgetArea.RightDockWidgetArea)


def _bereich_merken(z, schluessel, bereich):
    """Wo angedockt wurde (links/rechts) — fuer einen Neubau in der Sitzung."""
    from PyQt6.QtCore import Qt
    if bereich in (Qt.DockWidgetArea.LeftDockWidgetArea,
                   Qt.DockWidgetArea.RightDockWidgetArea):
        z[schluessel] = bereich.value


def _schirm(punkt=None):
    """Der verfuegbare Bereich des Bildschirms (QRect) — oder None."""
    from PyQt6.QtGui import QGuiApplication
    schirm = (QGuiApplication.screenAt(punkt) if punkt is not None
              else None) or QGuiApplication.primaryScreen()
    return schirm.availableGeometry() if schirm is not None else None


def _in_schirm(x, y, breite, hoehe, ganz=True):
    """(x, y, breite, hoehe) so, dass ein schwebendes Fenster auf einem
    Bildschirm steht (Gegenpruefung K9) und nie groesser ist als dessen
    verfuegbarer Bereich (ein kleiner Bildschirm, 1366 x 768 bei 125 %,
    ist niedriger als das Chatfenster).

    `ganz`: GANZ auf dem Bildschirm, der seine Mitte (sonst seine linke
    obere Ecke) traegt, sonst auf dem Hauptbildschirm — fuer den Ort, den
    das Dock selbst waehlt. Ohne `ganz` (ein Ort, den der NUTZER gewaehlt
    hat) bleibt er, solange die Mitte der Titelleiste auf einem Bildschirm
    liegt, sich also greifen laesst; sonst (ein zweiter Bildschirm wurde
    abgesteckt) wie mit `ganz`."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QGuiApplication
    if not ganz:
        griff = QPoint(x + breite // 2, y + 10)
        schirm = QGuiApplication.screenAt(griff)
        if schirm is not None and schirm.availableGeometry().contains(griff):
            r = schirm.availableGeometry()
            return x, y, min(breite, r.width()), min(hoehe, r.height())
    schirm = (QGuiApplication.screenAt(QPoint(x + breite // 2,
                                              y + hoehe // 2))
              or QGuiApplication.screenAt(QPoint(x, y))
              or QGuiApplication.primaryScreen())
    if schirm is None:
        return x, y, breite, hoehe
    r = schirm.availableGeometry()
    breite, hoehe = min(breite, r.width()), min(hoehe, r.height())
    x = max(r.left(), min(x, r.left() + r.width() - breite))
    y = max(r.top(), min(y, r.top() + r.height() - hoehe))
    return x, y, breite, hoehe


def _schwebend_ziel(teil, x, y, ganz=True):
    """(x, y), wohin `_schwebend_setzen` ein Fenster stellen wuerde (auf
    einem Bildschirm, gerechnet mit dem Rahmen) — ohne es zu verschieben.
    Die Leiste braucht ihr Ziel, BEVOR sie gezeigt wird
    (die Arbeitsanzeige, `_anzeige_platzieren`)."""
    rahmen = teil.frameGeometry()
    return _in_schirm(int(x), int(y), rahmen.width(), rahmen.height(),
                      ganz)[:2]


def _schwebend_setzen(teil, x, y, ganz=True):
    """Ein schwebendes Fenster (Dock oder Leiste) an (x, y) — auf einem
    Bildschirm, wenn noetig kleiner (`_in_schirm`, gerechnet mit dem
    Rahmen)."""
    from PyQt6.QtCore import QPoint
    rahmen = teil.frameGeometry()
    zusatz_b = max(0, rahmen.width() - teil.width())
    zusatz_h = max(0, rahmen.height() - teil.height())
    x, y, b, h = _in_schirm(int(x), int(y), rahmen.width(), rahmen.height(),
                            ganz)
    if (b, h) != (rahmen.width(), rahmen.height()):
        teil.resize(b - zusatz_b, h - zusatz_h)
    teil.move(QPoint(x, y))


def _inhalt_frisch(inhalt):
    """Die Groessenwuensche des Steuerfensters JETZT neu rechnen. Ein eben
    versteckter Teil (die Chat-Zeile in der Karte) steckt sonst noch im
    zwischengespeicherten Wunsch, bis Qt seine Ereignisse abarbeitet."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLayout, QWidget
    for kind in inhalt.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
        kind.updateGeometry()
    for lay in inhalt.findChildren(QLayout):
        lay.invalidate()
    if inhalt.layout() is not None:
        inhalt.layout().invalidate()
        inhalt.layout().activate()


def _haupt_rahmen(haupt):
    """Das Hauptfenster in GLOBALEN Koordinaten (QRect). Ueber
    `mapToGlobal` statt `geometry()`: sitzt es selbst in einem anderen
    Fenster (eingebettet), ist `geometry()` relativ zu diesem."""
    from PyQt6.QtCore import QPoint, QRect
    return QRect(haupt.mapToGlobal(QPoint(0, 0)), haupt.size())


def _monitor_ziel(z, teil=None):
    """Wohin `teil` (seit K12 das Fenster als Pille) gehoert, wenn es
    keinen anderen Ort gibt -> (x, y, Grund): oben rechts IM Hauptfenster,
    MONITOR_ABSTAND vom rechten Rand der ZEICHENFLAECHE (`centralWidget`)
    und unter deren Oberkante (unter Menue und Werkzeugleisten), rechte
    Kante verankert — so bleiben Cadworks rechts angedockte Docks frei
    (Gegenpruefung K12: die Pille lag am Hauptfenster ueber dem Dock
    "Eigenschaften"). Ohne Zeichenflaeche am rechten Rand des
    Hauptfensters; ohne Hauptfenster oben rechts auf dem Bildschirm."""
    from PyQt6.QtCore import QPoint
    if teil is None:
        teil = z["dock"]
    # Ein noch nie gezeigtes, rahmenloses Fenster meldet als Rahmen 1 px
    # weniger als seine Breite (gemessen offscreen: 276 gegen 277) — die
    # groessere zaehlt, sonst steht der rechte Rand 1 px neben dem Ziel.
    breite = max(teil.frameGeometry().width(), teil.width())
    haupt = _hauptfenster()
    if haupt is not None:
        r = _haupt_rahmen(haupt)
        oben = r.top() + MONITOR_OBEN_OHNE
        rechts = r.left() + r.width()
        grund = "Hauptfenster oben rechts"
        mitte = getattr(haupt, "centralWidget", lambda: None)()
        if mitte is not None and mitte.isVisible():
            m0 = mitte.mapToGlobal(QPoint(0, 0))
            m_oben = m0.y()
            # Nur eine Mitte im oberen Drittel zaehlt (sonst ist es keine
            # Flaeche unter einem Menue, sondern etwas Eigenes).
            if r.top() <= m_oben <= r.top() + r.height() // 3:
                oben = m_oben
            # Die rechte Kante der Zeichenflaeche — nur, wenn sie im
            # Hauptfenster liegt und die Pille daneben noch Platz hat.
            m_rechts = m0.x() + mitte.width()
            if r.left() + breite + MONITOR_ABSTAND[0] < m_rechts <= rechts:
                rechts = m_rechts
                grund = "Zeichenfläche oben rechts im Hauptfenster"
        return (rechts - breite - MONITOR_ABSTAND[0],
                oben + MONITOR_ABSTAND[1], grund)
    s = _schirm()
    if s is None:
        return teil.x(), teil.y(), "ohne Bildschirm"
    return (s.left() + s.width() - breite - MONITOR_ABSTAND[0],
            s.top() + MONITOR_ABSTAND[1], "Bildschirm oben rechts")


def _ort_spaeter(z, schluessel, soll, name):
    """Nach dem Zeigen nachsehen (ORT_NACHSEHEN_MS), ob das Fenster noch am
    Ziel steht — Qt bzw. Windows setzen ein Fenster beim ersten Zeigen
    gern selbst hin. Jedes Setzen zaehlt neu (`ort_nachgesetzt[name]` =
    [Fassung, wie oft nachgesetzt]): ein Nachsehen eines frueheren Setzens
    oder eines abgeraeumten Fensters tut nichts — sonst holte es ein
    neu gebautes oder neu gesetztes Fenster an den alten Ort."""
    from PyQt6.QtCore import QTimer
    stand = z.get("ort_nachgesetzt")
    if not isinstance(stand, dict):
        stand = z["ort_nachgesetzt"] = {}
    alt = stand.get(name)
    fassung = (alt[0] if isinstance(alt, list) and alt else 0) + 1
    stand[name] = [fassung, 0]
    teil = z.get(schluessel)
    for ms in ORT_NACHSEHEN_MS:
        QTimer.singleShot(ms, lambda ms=ms: _sicher(
            lambda: _ort_nachsehen(z, schluessel, soll, name, ms, teil,
                                   fassung), "Ort nachsehen"))


def _ort_nachsehen(z, schluessel, soll_schluessel, name, ms, teil=None,
                   fassung=None):
    """Steht `z[schluessel]` noch bei `z[soll_schluessel]`? Sonst zurueck
    (hoechstens ORT_NACHSETZEN_MAX-mal je Setzen) — ausser der Nutzer hat
    das Fenster inzwischen gegriffen (ORT_GEGRIFFEN), das Fenster wurde
    neu gebaut (`teil`) oder neu gesetzt (`fassung`). Gilt fuer Docks
    (nur schwebend) und fuer die Leiste. -> "passt", "nachgesetzt",
    "gegriffen", "abweichend" oder None (nichts zu sehen)."""
    from PyQt6.QtCore import QPoint
    stand = (z.get("ort_nachgesetzt") or {}).get(name)
    if fassung is not None and (not isinstance(stand, list)
                                or stand[0] != fassung):
        return None
    if teil is not None and z.get(schluessel) is not teil:
        return None
    teil, soll = z.get(schluessel), z.get(soll_schluessel)
    if teil is None or soll is None:
        return None
    try:
        schwebt = getattr(teil, "isFloating", None)
        if (schwebt is not None and not schwebt()) or not teil.isVisible():
            return None
        ist = (teil.x(), teil.y())
    except RuntimeError:                       # schon abgeraeumt
        return None
    letzte = ms == ORT_NACHSEHEN_MS[-1]
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    # Haelt der Nutzer gerade die Maus gedrueckt (er zieht ein Fenster),
    # oder hat er dieses Fenster schon gegriffen: nichts zuruecksetzen.
    gedrueckt = QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton
    gegriffen = ORT_GEGRIFFEN.get(schluessel)
    if gedrueckt or (gegriffen and z.get(gegriffen)):
        if letzte:
            _ort_protokoll(z, "%s nach %d ms: vom Nutzer gegriffen, bleibt: "
                              "%s" % (name, ms, _lage_text(teil)))
        return "gegriffen"
    weg = (abs(ist[0] - soll[0]) > ORT_TOLERANZ
           or abs(ist[1] - soll[1]) > ORT_TOLERANZ)
    if not isinstance(stand, list):
        stand = z.setdefault("ort_nachgesetzt", {})[name] = [0, 0]
    if weg and stand[1] < ORT_NACHSETZEN_MAX:
        stand[1] += 1
        teil.move(QPoint(*soll))
        _ort_protokoll(z, "%s nach %d ms: Qt hatte es nach (%d, %d) "
                          "verschoben, zurueck nach (%d, %d): %s"
                       % (name, ms, ist[0], ist[1], soll[0], soll[1],
                          _lage_text(teil)))
        return "nachgesetzt"
    if letzte:
        _ort_protokoll(z, "%s nach %d ms: %s, %s" % (
            name, ms, "weicht ab (nicht mehr nachgesetzt)" if weg
            else "steht am Ziel", _lage_text(teil)))
    return "abweichend" if weg else "passt"


def _rect_text(r):
    return "%d,%d %dx%d" % (r.x(), r.y(), r.width(), r.height())


def _lage_text(teil):
    """Hauptfenster, Bildschirm und `teil` in globalen Koordinaten — die
    Zeile im Log, mit der sich ein Test in Cadwork nachpruefen laesst."""
    teile = []
    try:
        haupt = _hauptfenster()
        if haupt is not None:
            teile.append("Hauptfenster %s" % _rect_text(_haupt_rahmen(haupt)))
        else:
            teile.append("kein Hauptfenster")
        schirm = teil.screen()
        if schirm is not None:
            teile.append("Bildschirm %s %s (frei %s, dpr %.2f)" % (
                schirm.name() or "?", _rect_text(schirm.geometry()),
                _rect_text(schirm.availableGeometry()),
                schirm.devicePixelRatio()))
        teile.append("Fenster %s (Rahmen %s)" % (
            _rect_text(teil.geometry()), _rect_text(teil.frameGeometry())))
    except Exception as exc:                           # noqa: BLE001
        teile.append("(Lage nicht lesbar: %s)" % exc)
    return "; ".join(teile)


def _ort_protokoll(z, text):
    """Eine Zeile ueber die Fenster ins Log der Instanz
    (C:\\Users\\Public\\OpenMcpCad_<Kennung>.log) — gibt es noch keins
    (die Leiste steht, bevor verbunden ist), wartet sie, bis es eins gibt
    (`_ort_ausgeben` im Takt)."""
    zeilen = z.get("ort_zeilen")
    if not isinstance(zeilen, list):
        zeilen = z["ort_zeilen"] = []
    zeilen.append((time.time(), text))
    del zeilen[:-ORT_ZEILEN_MAX]
    _ort_ausgeben(z)


def _ort_ausgeben(z):
    """Wartende Zeilen ins Log des Kerns (`kern.LOG`), sobald es einen
    Ausgang hat. -> Zahl der geschriebenen Zeilen."""
    zeilen = z.get("ort_zeilen")
    if not zeilen:
        return 0
    log = getattr(z.get("kern"), "LOG", None)
    if log is None or not getattr(log, "handlers", None):
        return 0
    jetzt = time.time()
    for t, text in zeilen:
        alter = jetzt - t
        log.info("Fenster: %s%s", text,
                 " (notiert vor %.1f s)" % alter if alter >= 1.0 else "")
    z["ort_zeilen"] = []
    return len(zeilen)


# --- Kopfzeile, Pille, Meldungen ------------------------------------------

def _primaer_geklickt(z):
    _fehler_quittieren(z)                 # der Nutzer handelt: Meldung weg
    d = z["dienst"]
    if d is None or d.beenden or d.zustand == "stopped":
        _verbinden(z)
    else:
        _trennen(z)


def _pille_stil(farbe):
    """Die Pille weich getoent (K9, wie die Karten des Chatfensters): die
    Farbe des Zustands als Schrift und Punkt, hell dahinter."""
    try:
        r, g, b = (int(farbe[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError):
        r, g, b = 142, 142, 147
    dunkel = "#%02x%02x%02x" % (int(r * 0.72), int(g * 0.72), int(b * 0.72))
    return ("background: rgba(%d, %d, %d, 36); color: %s;"
            % (r, g, b, dunkel))


def _pille_setzen(z, zustand, text_farbe=None):
    """Die Pille im Kopf: Punkt und kurzer Zustand. `text_farbe` aus
    `_pille_zustand` (sonst die Tabelle PILLE)."""
    text, farbe = text_farbe or PILLE.get(zustand, (zustand or "Aus",
                                                    FARBEN["neben"]))
    p = z["w"].get("pille")
    if p is None:
        return None
    if p.text() != "● " + text:
        p.setText("● " + text)
        p.setStyleSheet(_pille_stil(farbe))
        # Die Pille wird breiter oder schmaler: ihre rechte Kante bleibt.
        _sicher(lambda: _kopf_anpassen(z), "Pille anpassen")
    return text


#: So lange bleibt eine Meldung des Docks stehen, wenn der Nutzer nichts tut.
FEHLER_SICHTBAR_S = 12.0


def _fehler_zeigen(z, text):
    """Eine Meldung DES DOCKS (Verbinden, Chat) — rot, und sie bleibt stehen.

    Befund 2026-09-25: "Chat startet nicht: …" verschwand nach hoechstens
    0,5 s. `_auffrischen` blendete die Zeile in jedem Takt aus, sobald der
    Kern selbst nichts zu melden hatte. Jetzt schuetzt `fehler_bis` sie
    FEHLER_SICHTBAR_S lang — oder bis der Nutzer wieder etwas tut
    (`_fehler_quittieren`). Meldungen des Kerns zeigt der Takt darunter.
    """
    z["fehler_dock"] = text
    z["fehler_bis"] = time.monotonic() + FEHLER_SICHTBAR_S
    _zeile_rot(z, text)


def _zeile_rot(z, text, farbe=None):
    """Eine Meldung ERSETZT die Kontextzeile (Spezifikation 3.1) — rot bzw.
    orange, bis `_fehler_quittieren` oder der Takt sie wegnimmt."""
    w = z["w"]
    h = w.get("hinweis")
    if h is None:
        # Noch kein Fenster (oder schon abgeraeumt): dann wenigstens stderr,
        # statt mit einem KeyError die eigentliche Meldung zu verschlucken.
        _stderr("[Open MCP CAD] %s\n" % text)
        return
    h.setText(text)
    h.setStyleSheet("color: %s; font-size: 11px;" % (farbe or FARBEN["rot"]))
    h.show()
    k = w.get("kontext_zeile")
    if k is not None and not k.isHidden():
        k.hide()
    # Auch im Kopf zu sehen: als Tooltip der Pille.
    _pille_tipp(z)


def _fehler_steht(z):
    """Ist die letzte Meldung des Docks noch vor dem Takt geschuetzt?"""
    return time.monotonic() < (z.get("fehler_bis") or 0.0)


def _fehler_quittieren(z):
    """Der Nutzer handelt wieder (Verbinden, Trennen, Chat): Meldung weg,
    die Kontextzeile wieder da. Hat der Kern etwas zu sagen, zeigt es der
    naechste Takt wieder an."""
    z["fehler_bis"] = 0.0
    w = z["w"]
    h = w.get("hinweis")
    if h is not None:
        try:
            _meldung_weg(z)
            _pille_tipp(z)
        except RuntimeError:                  # schon abgeraeumt
            pass


def _meldung_weg(z):
    w = z["w"]
    h, k = w.get("hinweis"), w.get("kontext_zeile")
    if h is not None and not h.isHidden():
        h.hide()
    if k is not None and k.isHidden():
        k.show()


def _pille_tipp(z):
    """Der Tooltip der Pille im Kopf: Dokument (bzw. laufender Auftrag) und
    — falls sichtbar — die Meldung. So sagt auch die Pille allein, was
    los ist. Wirft nie."""
    w = z["w"]
    p = w.get("pille")
    if p is None:
        return None
    try:
        teile = []
        k = w.get("kontext_zeile")
        if k is not None:
            teile.append(k.toolTip() or k.text())
        h = w.get("hinweis")
        if h is not None and not h.isHidden() and h.text():
            teile.append(h.text())
        text = "\n".join(t for t in teile if t) or "Open MCP CAD"
        if p.toolTip() != text:
            p.setToolTip(text)
        return text
    except RuntimeError:                      # schon abgeraeumt
        return None


def _hinweis_zahl_zeigen(z, n):
    """Die Zahl offener Pruefhinweise: als Chip in der Pille (nur > 0), am
    Knopf der Segmentzeile und im Kopf des Hinweis-Bereichs."""
    w = z["w"]
    n = int(n or 0)
    z["hinweise_zahl"] = n
    teil = ("%d %s" % (n, "offener Hinweis" if n == 1
                       else "offene Hinweise")) if n else ""
    chip = w.get("kopf_hinweise")
    if chip is not None:
        if chip.text() != (str(n) if n else ""):
            chip.setText(str(n) if n else "")
            chip.setAccessibleName(teil or "Offene Hinweise")
            chip.setToolTip((teil + " — zeigen") if n else "")
        _chip_zeigen(z)
    knopf = w.get("hinweise_knopf")
    if knopf is not None and knopf.property("zahl") != n:
        knopf.setProperty("zahl", n)
        if not _knopf_symbol(knopf, "hinweise_flagge",
                             text=str(n) if n else None,
                             farbe=FARBEN["orange"] if n
                             else FARBEN["text"], groesse=15) and n:
            knopf.setText("%s %d" % (SYMBOLE["hinweise_flagge"][1], n))
        knopf.setFixedWidth(26 if not n else 40)
        knopf.setAccessibleName("Hinweise" + (" · " + teil if n else ""))
    return n


def _chip_soll(zustand, n):
    """Steht die Zahl offener Hinweise als Chip im Kopf? Nur in der Pille
    und nur bei > 0 — rein (test_a_prototyp P22). Offen und angedockt
    steht sie EINMAL an der Flagge der Segmentzeile (Gegenpruefung
    Laien-Sicht K12: dieselbe Zahl stand neben "Bereit" UND an der
    Flagge)."""
    return zustand == PILLE_Z and int(n or 0) > 0


def _chip_zeigen(z, zustand=None):
    """Den Chip im Kopf nach `_chip_soll` zeigen oder verstecken; die Pille
    passt ihre Breite an. -> sichtbar?"""
    chip = z["w"].get("kopf_hinweise")
    if chip is None:
        return None
    if zustand is None:
        zustand = _fenster_zustand_ist(z)
    soll = _chip_soll(zustand, z.get("hinweise_zahl"))
    if chip.isHidden() == soll:
        chip.setVisible(soll)
        if zustand == PILLE_Z:
            _sicher(lambda: _kopf_anpassen(z), "Pille anpassen")
    return soll


def _kontext_setzen(z, text, tipp):
    """Die Kontextzeile: elidiert auf ihre Breite, der volle Text im
    Tooltip."""
    from PyQt6.QtCore import Qt
    k = z["w"].get("kontext_zeile")
    if k is None:
        return None
    breite = max(80, k.width() - 4)
    kurz = k.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                      breite)
    if k.text() != kurz:
        k.setText(kurz)
    if k.toolTip() != tipp:
        k.setToolTip(tipp)
    return kurz


_LOGO = {}


def _logo_pixmap(groesse):
    """Das Logo des Plugins (das Bild in icon.svg neben dieser Datei — das
    Plugin bringt es mit, kein weiteres Bild) als scharfes QPixmap in
    `groesse` px, auch bei 150/200 %. Ohne QtSvg: das eingebettete PNG
    direkt. -> QPixmap oder None."""
    if groesse in _LOGO:
        return _LOGO[groesse]
    bild = None
    try:
        import base64
        import re as _re
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication, QPixmap
        with open(os.path.join(_HIER, "icon.svg"), encoding="utf-8") as fh:
            text = fh.read()
        treffer = _re.search(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)",
                             text)
        roh = QPixmap()
        if treffer and roh.loadFromData(
                base64.b64decode("".join(treffer.group(1).split())), "PNG"):
            # Die hoechste Dichte aller Bildschirme (wie die Symbole).
            dpr = 2.0
            app = QGuiApplication.instance()
            for schirm in (app.screens() if app is not None else ()):
                dpr = max(dpr, float(schirm.devicePixelRatio()))
            dpr = min(dpr, 4.0)
            seite = int(round(groesse * dpr))
            bild = roh.scaled(seite, seite,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            bild.setDevicePixelRatio(dpr)
    except Exception as exc:                           # noqa: BLE001
        _melden("Logo laden", exc)
        bild = None
    _LOGO[groesse] = bild
    return bild


def _logo_klein(groesse):
    """Ein QLabel mit dem Logo in `groesse` px (leer, wenn es fehlt)."""
    from PyQt6.QtWidgets import QLabel
    lb = QLabel("")
    lb.setObjectName("logo")
    pm = _logo_pixmap(groesse)
    if pm is not None:
        lb.setPixmap(pm)
        lb.setFixedSize(groesse, groesse)
    return lb


def _karte(titel_text):
    """Weisse Karte mit Ueberschrift — das wiederkehrende Bauteil."""
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
    w = QWidget()
    w.setObjectName("karte")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    if titel_text:
        lb = QLabel(titel_text)
        lb.setObjectName("karte_titel")
        lay.addWidget(lb)
    return w, lay


def _abschnitt(titel_text):
    """Ein Abschnitt des Steuerfensters (K11): ein Kopf wie die Gruppen der
    Hinweise, KEINE weisse Karte — das Steuerfenster ist ein Protokoll,
    kein Gespraech (Rueckmeldung 2026-10-02: "Aufträge, Briefkasten sehen
    zu aehnlich aus wie der Chat selbst"). -> (Widget, Layout)."""
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    if titel_text:
        lb = QLabel(titel_text)
        lb.setObjectName("abschnitt")
        lay.addWidget(lb)
    return w, lay


# --- Einstellungen (S5; seit K12 EINE Seite im Koerper) ---------------------
# Rueckmeldung 2026-09-25 (Uebergabe, Abschnitt 5): Freigabestufe, Anbieter
# und Verbindungen nicht immer vor Augen, sondern in einem Einstellungsmenue.
# Seit K12 (Rueckmeldung 2026-10-07: "Einstellungen brauchts nicht in der
# obersten Leiste") ueber "⋯" in der Segmentzeile — eine Seite im Koerper
# mit "← Zurück", nichts Modales.

#: So oft fragt die aufgeklappte Technik-Anzeige hoechstens neu (Nebenthread).
TECHNIK_TAKT_S = 2.0


def _einstellungen_zeigen(z, an=None):
    """Die Einstellungsseite zeigen (`an` True; steht nur die Pille, geht
    das Fenster auf) oder verlassen (False: zurueck zum gemerkten Segment);
    None = um. Beim Oeffnen wird nachgesehen, was sich nur im Hintergrund
    pruefen laesst (Schluessel im Tresor, lokale Programme)."""
    w = z["w"]
    seite, seiten = w.get("einst_seite"), w.get("seiten")
    if seite is None or seiten is None:
        return None
    if an is None:
        an = seiten.currentWidget() is not seite
    if an:
        if _fenster_zustand_ist(z) == PILLE_Z or (
                z.get("fenster") is not None and z["fenster"].isHidden()):
            _zustand_setzen(z, OFFEN_Z)
        seiten.setCurrentWidget(seite)
        _seite_gewechselt(z)
        _sicher(lambda: _einstellungen_pruefen(z), "Einstellungen prüfen")
        if not w["technik"].isHidden():
            _technik_anstossen(z, sofort=True)
    elif seiten.currentWidget() is seite:
        _segment_waehlen(z, z.get("segment"), fokus=False)
        _seite_gewechselt(z)
    return bool(an)


def _einstellungen_sichtbar(z):
    """Steht die Einstellungsseite vorn — bei sichtbarem Koerper?"""
    w = z["w"]
    seite, seiten = w.get("einst_seite"), w.get("seiten")
    koerper, dock = w.get("koerper"), z.get("fenster")
    try:
        return (seite is not None and seiten is not None
                and seiten.currentWidget() is seite
                and koerper is not None and not koerper.isHidden()
                and dock is not None and not dock.isHidden())
    except RuntimeError:                       # schon abgeraeumt
        return False


def _chat_einstellungen_zeigen(z, an=None):
    """Seit K12 dieselbe EINE Einstellungsseite (alter Name)."""
    return _einstellungen_zeigen(z, an)


def _chat_einstellungen_sichtbar(z):
    return _einstellungen_sichtbar(z)


def _zum_chat(z):
    """"Zum Chat" (Einstellungen, Arbeitsanzeige): das Fenster auf, der
    Chat vorn — dort stehen die Freigabe-Karten."""
    return _chat_oeffnen(z)


def _chat_oeffnen(z, ausweichen=None):
    """Den Chat zeigen: steht nur die Pille, geht das Fenster auf
    ("offen"), das Segment Chat kommt nach vorn, die Eingabe bekommt den
    Fokus. Anders als der Chat-Knopf im Kopf schliesst es nie (der Knopf
    schaltet in "offen" zurueck zur Pille). `ausweichen` gibt es seit K12
    nicht mehr (nur EIN Fenster)."""
    dock = z.get("fenster")
    if dock is None:
        return False
    if _fenster_zustand_ist(z) == PILLE_Z or dock.isHidden():
        _zustand_setzen(z, OFFEN_Z)
    _segment_waehlen(z, "chat", fokus=False)
    dock.raise_()
    # Wartet eine Freigabe ("Zum Chat"): ihre Karte in den Blick.
    if _erste_freigabe(z) is not None:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: _sicher(
            lambda: _freigabe_in_sicht(z), "Freigabe zeigen"))
    # Was ist eingerichtet? (erster Kontakt; im Nebenthread)
    _sicher(lambda: _einstieg_pruefen(z), "Einstieg prüfen")
    _eingabe_fokus(z)
    _kopf_zeigen(z)
    return True


def _einst_freigabe_zeigen(z):
    """Im Takt: auf der Einstellungsseite sagen, dass eine Freigabe wartet
    — die Karten stehen im Chat. Billig: liest nur den Chat im Speicher."""
    w = z["w"]
    hinweis = w.get("einst_freigabe")
    if hinweis is None:
        return
    chat = z.get("chat") or {}
    wartet = False
    if chat.get("an"):
        try:
            wartet = bool(_chat_modul().offene_freigaben(chat))
        except Exception:                              # noqa: BLE001
            wartet = False
    zeigen = wartet and _einstellungen_sichtbar(z)
    if hinweis.isHidden() == zeigen:
        hinweis.setVisible(zeigen)


def _einstellungen_pruefen(z):
    """Fuer den gewaehlten Anbieter nachsehen lassen, was nur ein
    Nebenthread darf: liegt ein Schluessel im Tresor, ist das lokale
    Programm installiert und laeuft sein Dienst."""
    if "chat_anbieter" not in z["w"]:
        return                            # Ersatz-Tab: kein Chat, nichts
    a = _gewaehlter_anbieter(z)
    _ordner_zeigen(z)                     # etwa eine inzwischen andere Datei
    _schluessel_da_pruefen(z, a)
    if _lokal_modul().ist_lokal(a["id"]):
        # Jedes Oeffnen fragt NEU (Pruefung 2026-09-26): wer Ollama
        # ausserhalb des Docks installiert oder startet, blieb sonst bis
        # "Neu prüfen" beim alten Stand — und der Chat gesperrt.
        _lokal_pruefen(z, a["id"], erzwingen=True)


def _technik_umschalten(z):
    """Technik-Details auf/zu: die Zeilen der Verbindung und die Karte des
    Chats (wer antwortet, was laeuft) zusammen."""
    w = z["w"]
    auf = w["technik"].isHidden()
    w["technik"].setVisible(auf)
    reihe = w.get("steckplatz_reihe")
    if reihe is not None:
        reihe.setVisible(auf)
    karte = w.get("chat_technik_karte")
    if karte is not None:
        karte.setVisible(auf)
    _knopf_symbol(w["technik_knopf"], "auf" if auf else "zu",
                  text="Technik-Details", farbe=FARBEN["neben"], groesse=14)
    if auf:
        _technik_anstossen(z, sofort=True)


# --- Erster Kontakt: "Womit möchtest du chatten?" (2026-09-29) --------------
# Rueckmeldung 2026-09-29 (zum zweiten Mal): Kollegen ohne IT-Kenntnisse
# oeffneten den Chat, sahen "API-Schlüssel" und wussten nicht weiter. Ist
# noch NICHTS eingerichtet (kein Claude Code, keine Codex-Kommandozeile,
# kein gespeicherter Schluessel, kein lokales Modell), steht an der Stelle
# des leeren Verlaufs eine Karte mit drei Wegen in Alltagssprache. Jeder
# Knopf fuehrt zur richtigen Stelle oder sagt den einen Schritt, der fehlt.
# Nichts Modales; nachgesehen wird im Nebenthread, beim Oeffnen des
# Chatfensters und mit "Nochmal prüfen".

EINSTIEG_TITEL = "Womit möchtest du chatten?"
EINSTIEG_SATZ = ("Nimm das KI-Abo, das du schon hast. Einmal eingerichtet, "
                 "antwortet die KI hier und zeichnet in Cadwork.")
#: (Kennung, Name, ein Satz, Knopf)
EINSTIEG_WEGE = (
    ("claude", "Claude-Abo (Pro oder Max)",
     "Claude antwortet hier, sobald Claude Code einmal auf diesem Rechner "
     "eingerichtet ist.", "So geht's"),
    ("codex", "ChatGPT-Abo (Codex)",
     "Codex antwortet hier, sobald Codex einmal auf diesem Rechner "
     "eingerichtet ist.", "So geht's"),
    ("schluessel", "Eigener Schlüssel (ohne Abo)",
     "Du zahlst pro Anfrage, zum Beispiel bei OpenAI. Den Schlüssel holst "
     "du auf der Website des Anbieters.", "Schlüssel eingeben"),
)
#: Der eine Schritt, der fuer Claude bzw. Codex fehlt (markierbar, damit
#: man die Befehle kopieren kann). Claude: dieselben Befehle in derselben
#: Reihenfolge wie Weg A in SCHNELLSTART.md (test_a_prototyp P19b liest
#: beide). Seit 2026-09-29 der Installer, den Anthropic empfiehlt: eine
#: Zeile in PowerShell, ohne Node.js, ohne Adminrechte; npm nur noch als
#: Hinweis. Der Chat findet das claude.exe unter ~\.local\bin auch, wenn
#: Cadwork beim Einrichten schon lief (omcad_a_chat.cli_kandidaten).
EINSTIEG_SCHRITT = {
    "claude": ("Einmal einrichten: Windows-Taste, «PowerShell» tippen, "
               "Enter. Dort eingeben:\n"
               "irm https://claude.ai/install.ps1 | iex\n"
               "Dann ein NEUES Fenster (wieder «PowerShell»):\n"
               "claude\n"
               "Mit deinem Claude-Konto anmelden, danach hier «Nochmal "
               "prüfen». Im Kopf dieses Fensters noch einen Projektordner "
               "wählen. Kennt Windows «claude» noch nicht, stattdessen:\n"
               "~\\.local\\bin\\claude.exe\n"
               "Geht die erste Zeile nicht (etwa auf einem Firmenrechner), "
               "steht in der Anleitung der Weg über Node.js."),
    "codex": ("Einmal einrichten: Windows-Taste, «PowerShell» tippen, "
              "Enter. Dort eingeben:\n"
              "irm https://chatgpt.com/codex/install.ps1 | iex\n"
              "Dann ein NEUES Fenster (wieder «PowerShell»):\n"
              "codex login\n"
              "Mit deinem ChatGPT-Konto anmelden, danach hier «Nochmal "
              "prüfen». Einfacher: 1_INSTALLIEREN.cmd nochmals starten und "
              "dort «Direkt in Cadwork im Chat» wählen."),
}
EINSTIEG_ANDERS = ("Oder nutze die Codex-App oder Claude Desktop direkt, "
                   "ohne diesen Chat. Wie, steht in der Anleitung.")
#: Erklaerung des Worts "Schlüssel" (dort, wo frueher "API-Schlüssel" stand).
SCHLUESSEL_TIPP = ("Ein Schlüssel ist ein Zugangscode, den du auf der Website "
                   "des Anbieters erstellst (Fachwort: API-Schlüssel). "
                   "Bezahlt wird pro Anfrage, ohne Abo.")
#: Die Anleitung neben dem Plugin (der Installer legt 2_ANLEITUNG.pdf aus
#: dem Paket als diese Datei hierher); sonst die Seite im Netz.
PLUGIN_ORDNER = os.path.dirname(os.path.abspath(__file__))
ANLEITUNG_DATEI = "ANLEITUNG.pdf"
ANLEITUNG_URL = ("https://github.com/sebastiankoukoui/open-mcp-cad/blob/main/"
                 "verteilung/SCHNELLSTART.md")
#: Oeffnet eine Datei oder Adresse (die Gates setzen hier eine Attrappe).
URL_OEFFNEN = None


def _einstieg_wege(C, A, L, e=None, env=None):
    """Was ist eingerichtet? -> {"claude", "codex", "schluessel", "lokal"}.

    WARTET (Dateisystem): nur im Nebenthread. Den Tresor liest es NIE —
    ein Schluessel zaehlt, wenn chat.json seine letzten Zeichen kennt
    (`schluessel_ende`, seit S6 bei jedem Speichern), eine Umgebungsvariable
    ihn traegt oder eine eigene Adresse eingetragen ist. Einen Schluessel,
    den das Dock im Takt als vorhanden kennt (`schluessel_da`), zaehlt
    `_einstieg_noetig` dazu."""
    env = os.environ if env is None else env

    def da(pruefung):
        try:
            return bool(pruefung())
        except Exception:                              # noqa: BLE001
            return False
    stand = {"claude": da(C.cli_pfad), "codex": da(A.codex_pfad)}
    stand["lokal"] = any(da(lambda k=k: L.programm(k) or L.app(k))
                         for k in ("ollama", "lmstudio"))
    if e is None:
        e = _einstellungen(A)
    mit = [a for a in A.ANBIETER if a.get("schluessel") in ("pflicht",
                                                            "optional")]
    basis = e.get("basis") if isinstance(e, dict) else None
    stand["schluessel"] = (
        any(_schluessel_ende(e, a["id"]) is not None for a in mit)
        or any((env.get(a["env"]) or "").strip() for a in mit
               if a.get("env"))
        or bool(isinstance(basis, dict) and isinstance(basis.get("eigen"),
                                                       str)
                and basis["eigen"].strip()))
    return stand


def _einstieg_noetig(stand, schluessel_da, an, leer, offen, veraltet=None):
    """Zeigt das Gespraech die Karte? Rein (test_a_prototyp P19).

    Nur solange kein Chat laeuft, der Verlauf leer ist, kein alter Chat
    geoeffnet ist, und nur, wenn NICHTS eingerichtet ist. Unbekannt
    (`stand` None, noch nicht nachgesehen) heisst: keine Karte."""
    if stand is None or an or not leer or offen is not None or veraltet:
        return False
    if any(stand.get(k) for k in ("claude", "codex", "schluessel", "lokal")):
        return False
    return not any((schluessel_da or {}).values())


def _einstieg_pruefen(z, erzwingen=False):
    """Im Nebenthread nachsehen, was eingerichtet ist. -> gestartet?"""
    if z.get("einstieg_laeuft") and not erzwingen:
        return False
    if CHAT_TAB not in z["w"]:
        return False                      # Ersatz-Tab: kein Chat
    z["einstieg_laeuft"] = True
    version = z.get("einstieg_version", 0)
    C, A, L = _chat_modul(), _anbieter_modul(), _lokal_modul()

    def holen():
        try:
            stand = _einstieg_wege(C, A, L)
        except Exception:                              # noqa: BLE001
            stand = None
        z["einstieg_neu"] = (version, stand)
        z["einstieg_laeuft"] = False

    threading.Thread(target=holen, name="Open-MCP-CAD-Einstieg",
                     daemon=True).start()
    return True


def _einstieg_setzen(z, stand):
    """Den Stand setzen (Bilder, Gates) — ein Nachsehen, das vorher begann,
    gilt dann nicht mehr."""
    z["einstieg_version"] = z.get("einstieg_version", 0) + 1
    z["einstieg"] = stand


def _einstieg_takt(z, an, leer, offen, veraltet=None):
    """Im Qt-Takt: Ergebnis abholen, entscheiden. -> Karte zeigen?"""
    neu = z.pop("einstieg_neu", None)
    if neu is not None and neu[0] == z.get("einstieg_version", 0) \
            and neu[1] is not None:
        z["einstieg"] = neu[1]
    return _einstieg_noetig(z.get("einstieg"), z.get("schluessel_da"), an,
                            leer, offen, veraltet)


def _einstieg_zeigen(z, zeigen):
    """Karte ODER Verlauf/Liste — sie teilen sich den Platz."""
    w = z["w"]
    karte = w.get("chat_willkommen")
    if karte is None:
        return
    if karte.isHidden() == zeigen:
        karte.setVisible(zeigen)
        if not zeigen:
            w["chat_verlauf"].setVisible(w["chat_liste"].isHidden())
    if zeigen:
        for teil in ("chat_verlauf", "chat_liste", "chat_liste_titel"):
            if not w[teil].isHidden():
                w[teil].hide()


def _anbieter_setzen(z, kennung):
    """Den Anbieter waehlen wie der Nutzer (gemerkt in chat.json)."""
    feld = z["w"]["chat_anbieter"]
    i = feld.findData(kennung)
    if i >= 0 and feld.currentIndex() != i:
        feld.setCurrentIndex(i)
    return i >= 0


def _einstieg_weg(z, kennung):
    """Ein Knopf der Karte. Claude/Codex: den Anbieter waehlen und den
    einen fehlenden Schritt zeigen. Schluessel: OpenAI waehlen und die
    Chat-Einstellungen mit dem Feld fuer den Schluessel oeffnen."""
    w = z["w"]
    if kennung in EINSTIEG_SCHRITT:
        _anbieter_setzen(z, kennung)
        w["chat_willkommen_schritt"].setText(EINSTIEG_SCHRITT[kennung])
        w["chat_willkommen_schritt"].show()
        z["einstieg_gewaehlt"] = kennung
        return kennung
    _anbieter_setzen(z, "openai")
    _chat_einstellungen_zeigen(z, True)
    w["chat_schluessel"].setFocus()
    z["einstieg_gewaehlt"] = kennung
    return kennung


def _anleitung_ziel():
    """Die Anleitung neben dem Plugin, sonst die Adresse im Netz."""
    pfad = os.path.join(PLUGIN_ORDNER, ANLEITUNG_DATEI)
    return pfad if os.path.isfile(pfad) else ANLEITUNG_URL


def _url_oeffnen(ziel):
    """Mit dem Programm, das Windows dafuer nimmt — kehrt sofort zurueck."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    url = QUrl(ziel) if ziel.startswith("https://") else \
        QUrl.fromLocalFile(ziel)
    return QDesktopServices.openUrl(url)


def _anleitung_oeffnen(z):
    ziel = _anleitung_ziel()
    (URL_OEFFNEN or _url_oeffnen)(ziel)
    z["anleitung_geoeffnet"] = ziel
    return ziel


def _einstieg_bauen(z):
    """Die Karte (versteckt); `_einstieg_takt` zeigt sie."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                                 QScrollArea, QSizePolicy, QVBoxLayout,
                                 QWidget)
    inhalt = QWidget()
    inhalt.setObjectName("rollinhalt")
    lay = QVBoxLayout(inhalt)
    lay.setContentsMargins(2, 4, 6, 4)
    lay.setSpacing(7)
    titel = QLabel(EINSTIEG_TITEL)
    titel.setObjectName("einstieg_titel")
    titel.setWordWrap(True)
    satz = QLabel(EINSTIEG_SATZ)
    satz.setObjectName("neben")
    satz.setWordWrap(True)
    lay.addWidget(titel)
    lay.addWidget(satz)
    knoepfe = {}
    for kennung, name, text, knopf_text in EINSTIEG_WEGE:
        weg = QWidget()
        weg.setObjectName("einstieg_weg")
        weg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        wl = QVBoxLayout(weg)
        wl.setContentsMargins(10, 7, 10, 7)
        wl.setSpacing(3)
        n = QLabel(name)
        n.setObjectName("einstieg_name")
        n.setWordWrap(True)
        t = QLabel(text)
        t.setWordWrap(True)
        reihe = QHBoxLayout()
        k = QPushButton(knopf_text)
        k.setObjectName("chatknopf")
        reihe.addWidget(k)
        reihe.addStretch(1)
        wl.addWidget(n)
        wl.addWidget(t)
        wl.addLayout(reihe)
        lay.addWidget(weg)
        knoepfe[kennung] = k
    schritt = QLabel("")
    schritt.setObjectName("einstieg_schritt")
    schritt.setWordWrap(True)
    schritt.setTextFormat(Qt.TextFormat.PlainText)
    schritt.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    schritt.hide()
    lay.addWidget(schritt)
    pruefen = QPushButton("Nochmal prüfen")
    pruefen.setToolTip("Nachsehen, ob Claude Code, Codex, ein Schlüssel oder "
                       "ein lokales Modell jetzt eingerichtet ist")
    anders = QLabel(EINSTIEG_ANDERS)
    anders.setObjectName("neben")
    anders.setWordWrap(True)
    anleitung = QPushButton("Anleitung öffnen")
    anleitung.setToolTip("Die Anleitung (PDF) neben dem Plugin, sonst die "
                         "Seite im Netz")
    lay.addWidget(anders)
    reihe2 = QHBoxLayout()
    reihe2.addWidget(anleitung)
    reihe2.addWidget(pruefen)
    reihe2.addStretch(1)
    lay.addLayout(reihe2)
    lay.addStretch(1)
    rolle = QScrollArea()
    rolle.setObjectName("rolle")
    rolle.setWidgetResizable(True)
    rolle.setWidget(inhalt)
    rolle.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rolle.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Ignored)
    rolle.hide()
    z["w"].update(chat_willkommen=rolle, chat_willkommen_schritt=schritt,
                  chat_willkommen_claude=knoepfe["claude"],
                  chat_willkommen_codex=knoepfe["codex"],
                  chat_willkommen_schluessel=knoepfe["schluessel"],
                  chat_willkommen_pruefen=pruefen,
                  chat_willkommen_anleitung=anleitung)
    for kennung, k in knoepfe.items():
        k.clicked.connect(lambda _c=False, kennung=kennung: _sicher(
            lambda: _einstieg_weg(z, kennung), "Erster Kontakt"))
    pruefen.clicked.connect(lambda: _sicher(
        lambda: _einstieg_pruefen(z, erzwingen=True), "Nochmal prüfen"))
    anleitung.clicked.connect(lambda: _sicher(
        lambda: _anleitung_oeffnen(z), "Anleitung öffnen"))
    return rolle


def _dialog_eltern(z):
    """Wo ein Dialog aufgeht: ueber dem Fenster, wenn es zu sehen ist,
    sonst ueber Cadwork — nie ueber einem versteckten Fenster (dann stand
    eine Rueckfrage in der Bildschirmecke bei (0, 0), Gegenpruefung K11)."""
    for teil in (z.get("fenster"),):
        try:
            if teil is not None and teil.isVisible():
                return teil
        except RuntimeError:                   # schon abgeraeumt
            pass
    haupt = _hauptfenster()
    return haupt if haupt is not None else z.get("fenster")


def _chat_stand(z):
    """Wie es um den Chat des Docks steht — fuer den Chat-Knopf im Kopf und
    die Arbeitsanzeige. Billig, nur Speicher.
    -> {"an", "zug", "freigabe" (Schritt in Worten oder None), "gesperrt",
        "text", "letzter" ((Text, seit_s) oder None)}."""
    chat = z.get("chat") or {}
    erg = {"an": False, "zug": False, "freigabe": None, "gesperrt": False,
           "text": "Chat", "letzter": None}
    try:
        C = _chat_modul()
        an = bool(chat.get("an"))
        erg["an"] = an
        offen = C.offene_freigaben(chat) if an else []
        if offen:
            f = offen[0]
            erg["freigabe"] = _schritt_text(f.get("werkzeug") or "?",
                                            f.get("eingabe"), C=C)
        erg["gesperrt"] = bool(
            not offen and z.get("verlauf_verworfen") is not
            chat.get("ereignisse") and _sperre_hinweis(
                chat.get("ereignisse"), C.modus_von(chat), C))
        erg["zug"] = bool(an and C.laeuft_zug(chat))
        if erg["zug"]:
            for e in reversed(chat.get("ereignisse") or ()):
                if e.get("art") in ("werkzeug", "auto"):
                    t = e.get("zeit")
                    erg["letzter"] = (
                        _schritt_text(e.get("werkzeug") or "?",
                                      e.get("eingabe"), C=C),
                        time.time() - t if isinstance(t, (int, float))
                        else None)
                    break
        kurz = chat.get("kurzname") or "Claude"
        if offen:
            erg["text"] = "Der Chat wartet auf deine Freigabe."
        elif erg["gesperrt"]:
            erg["text"] = "«Nur lesen» hat etwas gesperrt."
        elif erg["zug"]:
            erg["text"] = "%s arbeitet …" % kurz
        elif an:
            erg["text"] = "Chat läuft · %s" % kurz
    except Exception:                                  # noqa: BLE001
        pass
    return erg


def _chatknopf_zeigen(z):
    """Im Takt: der Chat-Knopf im Kopf faellt auf (objectName "hinweis",
    blau mit weissem Symbol), wenn eine Freigabe wartet, "Nur lesen"
    gesperrt hat oder die KI arbeitet — sein Tooltip nennt den Grund.
    Billig, nur Speicher."""
    w = z["w"]
    knopf = w.get("kopf_chat")
    if knopf is None:
        return None
    st = _chat_stand(z)
    auffallen = bool(st["freigabe"] or st["gesperrt"] or st["zug"])
    tipp = "Chat" + (" — " + st["text"] if auffallen else "")
    if knopf.toolTip() != tipp:
        knopf.setToolTip(tipp)
    name = "hinweis" if auffallen else CHAT_KNOPF_NAME
    if knopf.objectName() != name:
        knopf.setObjectName(name)
        knopf.style().unpolish(knopf)
        knopf.style().polish(knopf)
        if not _knopf_symbol(knopf, "chat", farbe="#ffffff" if auffallen
                             else FARBEN["blau"]):
            knopf.setText("Chat")
    return name


def _technik_anstossen(z, sofort=False):
    """Die Technik-Anzeige im Nebenthread neu zusammensuchen lassen.

    Im Qt-Takt nur, was schon im Speicher liegt (Port, Sitzung, Adresse);
    alles mit Dateisystem (Arbeitsordner, Server-Python, Fachwissen) im
    Thread. Hoechstens alle TECHNIK_TAKT_S, und nur bei offener Anzeige.
    """
    w = z["w"]
    if w.get("technik") is None or w["technik"].isHidden():
        return
    jetzt = time.monotonic()
    if not sofort and jetzt - (z.get("technik_gefragt") or 0) < TECHNIK_TAKT_S:
        return
    if z.get("technik_laeuft"):
        return
    z["technik_gefragt"] = jetzt
    z["technik_laeuft"] = True
    d = z.get("dienst")
    verbunden = d is not None and not d.beenden
    st = {}
    if verbunden:
        try:
            st = d.status() or {}
        except Exception:                              # noqa: BLE001
            st = {}
    chat = z.get("chat") or {}
    schnappschuss = {
        "instanz": st.get("instanz") if verbunden else None,
        "port": st.get("port") if verbunden else None,
        "kern": getattr(z.get("kern"), "CORE_VERSION", None),
        "sitzung": chat.get("sitzung") if chat.get("an") else None,
        "ordner_wahl": _ordner_wahl(z),
        "verbindungen": _verbindungen_technik(z.get("monitor_daten")),
        "ms_je_teil": st.get("ms_je_teil") if verbunden else None,
    }
    if "chat_anbieter" in w:
        try:
            a = _gewaehlter_anbieter(z)
            if a["art"] == "openai":
                schnappschuss["anbieter"] = a["name"]
                schnappschuss["adresse"] = (w["chat_basis"].text().strip()
                                            or a.get("basis") or "")
        except Exception:                              # noqa: BLE001
            pass

    def holen():
        try:
            z["technik_neu"] = _technik_text(schnappschuss)
        except Exception as exc:                       # noqa: BLE001
            z["technik_neu"] = "Technik-Details nicht lesbar: %s" % exc
        finally:
            z["technik_laeuft"] = False

    threading.Thread(target=holen, name="Open-MCP-CAD-Technik",
                     daemon=True).start()


def _technik_text(s):
    """Der Text der Technik-Details. WARTET (Dateisystem): nur im Thread."""
    C = _chat_modul()
    A = _anbieter_modul()
    zeilen = []
    if s.get("port"):
        zeilen.append("Verbindung: Steckplatz %s · Port %s"
                      % (s.get("instanz"), s.get("port")))
        zeilen.append("Protokoll: C:\\Users\\Public\\OpenMcpCad_%s.log"
                      % s.get("instanz"))
    else:
        zeilen.append("Verbindung: keine")
    if s.get("kern"):
        zeilen.append("Kern: %s" % s["kern"])
    if s.get("ms_je_teil"):
        zeilen.append("Zeichenmodus: gemessen %.0f ms je Bauteil"
                      % s["ms_je_teil"])
    for zeile in s.get("verbindungen") or ():
        zeilen.append("Verbunden: %s" % zeile)
    zeilen.append("Chat-Sitzung: %s" % (s.get("sitzung") or "—"))
    zeilen.append("Arbeitsordner: %s"
                  % (arbeitsordner(s.get("ordner_wahl")) or "keiner"))
    zeilen.append("Server-Python: %s" % (C.mcp_python() or "nicht gefunden"))
    zeilen.append("Fachwissen: %s" % (C.wissensordner() or "nur eingebautes"))
    if s.get("adresse"):
        zeilen.append("Adresse %s: %s" % (s.get("anbieter"), s["adresse"]))
    zeilen.append("Codex-Ordner: %s" % os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "OpenMcpCad", "codex"))
    try:
        zeilen.append("Einstellungen: %s" % A._einstellungs_datei())
    except Exception:                                  # noqa: BLE001
        pass
    zeilen.append("Plugin-Ordner: %s" % _HIER)
    return "\n".join(zeilen)


def _technik_zeichnen(z):
    """Im Qt-Takt: ein fertiges Ergebnis uebernehmen, sonst nichts."""
    neu = z.pop("technik_neu", None)
    t = z["w"].get("technik")
    if neu is not None and t is not None and t.text() != neu:
        t.setText(neu)
    _technik_anstossen(z)


def _pause_umschalten(z):
    d = z["dienst"]
    if d is None or d.beenden:
        return
    with d.sperre:
        d.pausiert = not d.pausiert
        if d.pausiert and d._zustand not in ("busy_read", "busy_write"):
            d._zustand = "paused"
        elif not d.pausiert and d._zustand == "paused":
            d._zustand = "ready"
    _auffrischen(z)


def _hinweis_modul():
    """Das Hinweis-Board — genauso NEBEN dieser Datei geladen wie der Chat.

    Es kennt Qt, aber kein Cadwork: alle Modell-Arbeit laeuft ueber die
    Rueckrufe, die es hier unten mitbekommt. Deshalb laesst es sich ohne
    Cadwork bauen und bedienen, und genau das tut das Gate.
    """
    name = "omcad_a_hinweise_A"
    vorhanden = sys.modules.get(name)
    if vorhanden is not None:
        return vorhanden
    pfad = os.path.join(_HIER, "omcad_a_hinweise.py")
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _hinweis_finden(z, nr):
    d = z.get("dienst")
    if d is None or nr is None:
        return None
    with d.sperre:
        for e in d.hinweise:
            if e["nr"] == nr:
                return dict(e)
    return None


def _tab_hinweise(z, ziel):
    """Das Board der Pruefhinweise — seit K12 im aufklappbaren
    Hinweis-Bereich des Koerpers (`ziel`: sein Layout). Der ganze Aufbau
    steht in omcad_a_hinweise.py.

    Hier bleibt nur, was Cadwork braucht: die Rueckrufe in die
    Auftragswarteschlange und in die Hinweisliste des Dienstes.
    """
    H = _hinweis_modul()

    def waehlen(nr):
        teile = z["w"]["hinweise"]
        # Nochmal auf dieselbe Karte: abwaehlen. Sonst kommt man aus der
        # Auswahl nie wieder heraus, ohne eine andere zu nehmen.
        teile["gewaehlt_nr"] = None if teile["gewaehlt_nr"] == nr else nr
        if teile["gewaehlt_nr"] is not None:
            setzen(nr, gelesen=True)
            # Anwaehlen zeigt SOFORT im Modell — Rueckmeldung 2026-08-15: "wenn man
            # ein hinweis anwaehlt muessen die objekte pink aktiviert
            # werden". Kein zusaetzlicher Knopfdruck mehr.
            zeigen(nr)
        _auffrischen(z)

    def setzen(nr, **werte):
        d = z["dienst"]
        if d is None or nr is None:
            return
        with d.sperre:
            for e in d.hinweise:
                if e["nr"] == nr:
                    e.update(werte)
                    break

    def zeigen(nr=None):
        teile = z["w"]["hinweise"]
        h = _hinweis_finden(z, nr if nr is not None else teile["gewaehlt_nr"])
        if not h or not h.get("element_ids"):
            return
        setzen(h["nr"], gelesen=True)
        _auftrag(z, "elemente_zeigen",
                 {"element_ids": h["element_ids"],
                  "zoomen": teile["chk_zoom"].isChecked(),
                  "nur_diese": teile["chk_nur"].isChecked()},
                 "Hinweis #%s zeigen" % h.get("nr"))

    def vollbild(nr):
        h = _hinweis_finden(z, nr)
        if h is None:
            return
        setzen(nr, gelesen=True)
        z["hinweis_fenster"] = H.vollbild_zeigen(z["fenster"], h, umgebung)

    def loeschen():
        teile = z["w"]["hinweise"]
        nr, d = teile["gewaehlt_nr"], z["dienst"]
        if nr is None or d is None:
            return
        with d.sperre:
            d.hinweise[:] = [e for e in d.hinweise if e["nr"] != nr]
        teile["gewaehlt_nr"] = None
        _auffrischen(z)

    def antworten():
        teile = z["w"]["hinweise"]
        text = teile["antwort"].text().strip()
        if not text:
            return
        h = _hinweis_finden(z, teile["gewaehlt_nr"])
        d = z["dienst"]
        aktiv = (d.status().get("aktive_elemente") or 0) if d else 0
        _auftrag(z, "nachricht_senden",
                 {"text": H.nachricht_bauen(h, text, aktiv)},
                 "Antwort auf Hinweis")
        teile["antwort"].clear()
        if h:
            setzen(h["nr"], gelesen=True)

    umgebung = {"waehlen": waehlen, "setzen": setzen, "zeigen": zeigen,
                "vollbild": vollbild}
    teile = H.bauen(umgebung)
    # Die Karten liegen flach im Bereich — der Rollbereich bekommt keine
    # weisse Karte (Typregel `QScrollArea`), er heisst wie die anderen
    # Rollbereiche ohne Rahmen.
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QLabel, QScrollArea
    listen = teile["tab"].findChildren(QScrollArea)
    for bereich in listen:
        bereich.setObjectName("rolle")
        # Die Liste rollt nicht selbst: sie ist so hoch wie alle Hinweise
        # (`_hinweise_masse`), gerollt wird der ganze Bereich.
        bereich.setVerticalScrollBarPolicy(
            _Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bereich.setHorizontalScrollBarPolicy(
            _Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    # Ohne Wahl statt der Knoepfe eine Zeile (`_hinweis_antwort_zeigen`).
    tipp = QLabel(HINWEIS_TIPP)
    tipp.setObjectName("neben")
    tipp.setWordWrap(True)
    teile["tab"].layout().insertWidget(2, tipp)
    # Die Zahl steht EINMAL an der Flagge (Gegenpruefung Laien-Sicht K12);
    # der Zaehler des Boards bleibt versteckt.
    teile["zaehler"].hide()
    teile["chk_zoom"].setText(getattr(H, "ZOOM_TEXT", "nah heran"))
    rolle = QScrollArea()
    rolle.setObjectName("rolle")
    rolle.setWidgetResizable(True)
    rolle.setFrameShape(QScrollArea.Shape.NoFrame)
    rolle.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rolle.setWidget(teile["tab"])
    ziel.addWidget(rolle, 1)
    z["w"].update(hinweise_rolle=rolle, hinweise_tipp=tipp,
                  hinweise_liste=listen[0] if listen else None)

    # Seit K11 ueber `_sicher`: eine Ausnahme aus einem Qt-Slot waere in
    # Cadwork qFatal.
    teile["btn_zeigen"].clicked.connect(lambda: _sicher(zeigen,
                                                        "Hinweis zeigen"))
    teile["btn_zurueck"].clicked.connect(lambda: _sicher(
        lambda: _auftrag(z, "sichtbarkeit_zurueck", {}, "Ansicht zurück"),
        "Ansicht zurück"))
    teile["btn_loeschen"].clicked.connect(lambda: _sicher(
        loeschen, "Hinweis löschen"))
    teile["btn_antwort"].clicked.connect(lambda: _sicher(
        antworten, "Hinweis beantworten"))
    teile["antwort"].returnPressed.connect(lambda: _sicher(
        antworten, "Hinweis beantworten"))
    teile["nur_offen"].stateChanged.connect(lambda _s: _sicher(
        lambda: _auffrischen(z), "Hinweise filtern"))

    # Im Segment Chat geht eine Antwort auf einen Hinweis in die EINGABE
    # DES CHATS ("In den Chat übernehmen", Spezifikation 3.5), nicht in den
    # Briefkasten — vorher standen dort zwei Sendefelder mit verschiedenen
    # Empfaengern uebereinander (Gegenpruefung K12; Rueckmeldung
    # 2026-10-07: "Hinweise sind auch fuer die Chat-Funktion nuetzlich").
    # Im Segment Briefkasten bleibt die Antwort dort, so beschriftet.
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QPushButton
    in_chat = QPushButton("In den Chat übernehmen")
    in_chat.setObjectName("primaer")
    in_chat.setAccessibleName("In den Chat übernehmen")
    in_chat.setToolTip("Den gewählten Hinweis in die Chat-Eingabe übernehmen "
                       "(gesendet wird erst mit «Senden»)")
    in_chat.setCursor(Qt.CursorShape.PointingHandCursor)
    reihe = None
    aussen = teile["tab"].layout()
    for i in range(aussen.count()):
        unter = aussen.itemAt(i).layout()
        if unter is not None and unter.indexOf(teile["antwort"]) >= 0:
            reihe = unter
    (reihe or aussen).addWidget(in_chat)
    in_chat.clicked.connect(lambda: _sicher(lambda: _hinweis_in_chat(z),
                                            "In den Chat übernehmen"))

    # Alles unter der Liste (die Zeile ohne Wahl, der Bezug, die Antwort,
    # die Knoepfe) steht UNTER dem Rollbereich, nicht darin: so bleiben die
    # Knoepfe des gewaehlten Hinweises stehen, waehrend die Liste rollt
    # (Gegenpruefung Laien-Sicht K12: im Rollbereich standen sie hinter den
    # anderen Hinweisen, weit weg vom gewaehlten).
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    aussen = teile["tab"].layout()
    aktionen = QWidget()
    akl = QVBoxLayout(aktionen)
    akl.setContentsMargins(0, 4, 0, 0)
    akl.setSpacing(6)
    nach = aussen.indexOf(listen[0]) if listen else -1
    if nach >= 0:
        stuecke = []
        while aussen.count() > nach + 1:
            stuecke.append(aussen.takeAt(nach + 1))
        for stueck in stuecke:
            if stueck.widget() is not None:
                akl.addWidget(stueck.widget())
            elif stueck.layout() is not None:
                unter = stueck.layout()
                unter.setParent(None)
                akl.addLayout(unter)
        ziel.addWidget(aktionen, 0)
    z["w"]["hinweise_aktionen"] = aktionen

    z["w"].update(hinweise=teile, hinweis_umgebung=umgebung,
                  hinweis_in_chat=in_chat,
                  hinweis_knoepfe=(teile["btn_zeigen"], teile["btn_zurueck"],
                                   teile["btn_loeschen"],
                                   teile["btn_antwort"]))
    _hinweis_antwort_zeigen(z)


def _hinweis_antwort_zeigen(z):
    """Wohin eine Antwort auf einen Hinweis geht, nach dem Segment: im Chat
    "In den Chat übernehmen" (das Briefkasten-Feld versteckt), im
    Briefkasten das Feld "Antwort in den Briefkasten …" mit "Senden".
    Der Knopf nur mit gewaehltem Hinweis. -> "chat" oder "briefkasten"."""
    w = z["w"]
    teile, in_chat = w.get("hinweise"), w.get("hinweis_in_chat")
    if teile is None or in_chat is None:
        return None
    chat = (z.get("segment") or "chat") != "briefkasten"
    for teil in (teile["antwort"], teile["btn_antwort"]):
        if teil.isHidden() != chat:
            teil.setVisible(not chat)
    if in_chat.isHidden() == chat:
        in_chat.setVisible(chat)
    text = "Antwort in den Briefkasten …"
    if teile["antwort"].placeholderText() != text:
        teile["antwort"].setPlaceholderText(text)
    gewaehlt = teile.get("gewaehlt_nr") is not None
    if in_chat.isEnabled() != gewaehlt:
        in_chat.setEnabled(gewaehlt)
    # Ohne gewaehlten Hinweis keine Knoepfe, die nichts tun koennen — eine
    # Zeile sagt, was ein Klick tut (Gegenpruefung Laien-Sicht K12: die
    # Knoepfe nahmen dem Text der Hinweise den Platz).
    soll = {in_chat: chat and gewaehlt,
            teile["antwort"]: not chat and gewaehlt,
            teile["btn_antwort"]: not chat and gewaehlt,
            # Der Bezug steht im Chat schon im eingefuegten Text; die Zeile
            # "↩ Antwort auf #n …" sagt nur, was in den Briefkasten mitgeht.
            teile["kontext"]: not chat and gewaehlt,
            teile["chk_zoom"]: gewaehlt,
            teile["chk_nur"]: gewaehlt, teile["btn_loeschen"]: gewaehlt}
    tipp = w.get("hinweise_tipp")
    if tipp is not None:
        soll[tipp] = not gewaehlt and bool(teile.get("karten"))
    for teil, an in soll.items():
        if teil.isHidden() == an:
            teil.setVisible(an)
    if teile["btn_zeigen"].isEnabled() != gewaehlt:
        teile["btn_zeigen"].setEnabled(gewaehlt)
    if gewaehlt and z.get("hinweis_gewaehlt_vorher") != teile["gewaehlt_nr"]:
        # Eben gewaehlt: die Knoepfe in den Blick (nach dem Auslegen).
        ziel = in_chat if chat else teile["antwort"]
        rolle = w.get("hinweise_rolle")
        if rolle is not None:
            from PyQt6.QtCore import QTimer
            karte = (teile.get("karten") or {}).get(teile["gewaehlt_nr"])
            QTimer.singleShot(0, lambda: _sicher(
                lambda: _hinweis_in_blick(rolle, getattr(karte, "widget",
                                                         None), ziel),
                "Hinweis zeigen"))
    z["hinweis_gewaehlt_vorher"] = teile.get("gewaehlt_nr")
    return "chat" if chat else "briefkasten"


def _hinweis_in_blick(rolle, karte, knopf):
    """Der gewaehlte Hinweis OBEN im Rollbereich — keine halbe Karte
    darueber; seine Knoepfe (`knopf`) stehen unter dem Rollbereich.
    -> neuer Rollwert."""
    from PyQt6.QtCore import QPoint
    _ = knopf
    inhalt, sb = rolle.widget(), rolle.verticalScrollBar()
    if karte is None:
        return sb.value()
    oben = karte.mapTo(inhalt, QPoint(0, 0)).y() - 4
    sb.setValue(max(0, min(oben, sb.maximum())))
    return sb.value()


def _hinweis_in_chat(z):
    """"In den Chat übernehmen": "Zu Prüfhinweis #n «Titel» (Bauteile …): "
    vor den Text der Chat-Eingabe, das Segment Chat nach vorn, die Eingabe
    im Fokus — gesendet wird NICHT (Spezifikation 3.5). -> der Text der
    Eingabe oder None (kein Hinweis gewaehlt)."""
    w = z["w"]
    teile, feld = w.get("hinweise"), w.get("chat_eingabe")
    if teile is None or feld is None:
        return None
    h = _hinweis_finden(z, teile.get("gewaehlt_nr"))
    if h is None:
        return None
    titel = " ".join(str(h.get("titel") or "").split())
    vor = "Zu Prüfhinweis #%s" % h.get("nr")
    if titel:
        vor += " «%s»" % _kurz_text(titel, 60)
    ids = [str(i) for i in (h.get("element_ids") or [])]
    if ids:
        vor += " (Bauteile %s%s)" % (", ".join(ids[:8]),
                                     " …" if len(ids) > 8 else "")
    vor += ": "
    alt = feld.toPlainText()
    if not alt.startswith(vor):
        feld.setPlainText(vor + alt)
    _segment_waehlen(z, "chat", fokus=False)
    try:
        cursor = feld.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        feld.setTextCursor(cursor)
    except Exception:                                  # noqa: BLE001
        pass
    feld.setFocus()
    return feld.toPlainText()


class _Eingabe:
    """Enter sendet, Shift+Enter macht eine neue Zeile.

    Als eigene Klasse, weil ein QPlainTextEdit sonst jedes Enter als Zeilen-
    umbruch nimmt — und eine Chat-Eingabe, in der man nicht mit Enter senden
    kann, fuehlt sich falsch an.
    """

    @staticmethod
    def bauen(senden, anhang=None):
        """`anhang(mime) -> bool`: nimmt Bilder und Dateien aus Einfuegen
        (Strg+V) und Ziehen-und-Ablegen an (K4); False = wie bisher Text."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QPlainTextEdit

        class Feld(QPlainTextEdit):
            def keyPressEvent(self, e):               # noqa: N802
                enter = e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                shift = e.modifiers() & Qt.KeyboardModifier.ShiftModifier
                if enter and not shift:
                    senden()
                    return
                super().keyPressEvent(e)

            # Einfuegen UND Ablegen laufen in Qt beide ueber diese zwei.
            def canInsertFromMimeData(self, quelle):  # noqa: N802
                if anhang is not None and (
                        quelle.hasImage() or _lokale_dateien(quelle)):
                    return True
                return super().canInsertFromMimeData(quelle)

            def insertFromMimeData(self, quelle):     # noqa: N802
                if anhang is not None and anhang(quelle):
                    return
                super().insertFromMimeData(quelle)

        f = Feld()
        f.setObjectName("eingabe")
        # Bewusst neutral: die Nachricht geht an KEINEN Empfaenger, sie
        # liegt hier, bis eine Sitzung sie abholt. "Nachricht an Open MCP CAD"
        # taeuschte ein Gegenueber vor, das gerade niemand ist.
        f.setPlaceholderText("Nachricht schreiben …")
        f.setFixedHeight(64)
        return f


# --- Chat-Layout (S7, 2026-09-26) -------------------------------------------
# Die Eingabe bleibt unten sichtbar (Plan B.11): das Dock liegt in EINEM
# Rollbereich, und alles, was im Chat-Tab waechst, verlaengerte ihn — dann
# rollte die Eingabe mit dem ganzen Dock aus dem Bild. Deshalb haben die
# wachsenden Teile ein Hoechstmass (laufende Antwort, Freigabe-Karten) und
# der Verlauf eine kleinere Mindesthoehe. Gemessen in test_a_live L58.

#: Mindesthoehe des Verlaufs (vorher 200). Mehr bekommt er ueber seinen
#: Anteil am freien Platz (Stretch), nicht ueber seinen Wunsch.
VERLAUF_MIN_HOEHE = 80
#: ... und solange eine Freigabe-Karte wartet: dann zaehlt die Karte, und
#: ihre Knoepfe muessen auch im 700 px hohen Dock zu sehen sein (Pruefung
#: Etappe C, test_a_live L61).
VERLAUF_MIN_HOEHE_KARTE = 40
#: Die laufende Antwort: nur ihr Ende, hoechstens so hoch.
LAUFEND_MIN_HOEHE = 30
LAUFEND_MAX_HOEHE = 110
LAUFEND_ZEICHEN = 220
#: Der Rollbereich der Freigabe-Karten ueber der Eingabe: mindestens so
#: hoch, dass Titel und Knoepfe einer Karte zu sehen sind, hoechstens so
#: hoch wie die Karten selbst und nie mehr als FREIGABE_MAX_HOEHE.
FREIGABE_MIN_HOEHE = 90
FREIGABE_MAX_HOEHE = 260
#: Auf der Karte stehen Wortlaut und Beschreibung nur gekuerzt (ganz unter
#: "Wortlaut zeigen" bzw. im Tooltip): so bleibt die Karte bis zu ihren
#: Knoepfen kurz genug fuer den Kartenbereich (Pruefung Etappe C: bei zwoelf
#: Zeilen Code lagen "Erlauben" und "Ablehnen" unter dem sichtbaren Teil).
KARTE_WORTLAUT_ZEICHEN = 90
KARTE_BESCHREIBUNG_ZEICHEN = 120
#: Abstand zwischen den Teilen des Chat-Tabs (vorher 8).
CHAT_ABSTAND = 6
#: So viele Zeichen muss ein Auswahlfeld mindestens zeigen koennen.
FELD_MIN_ZEICHEN = 6
#: Woran der Takt den echten Chat-Tab erkennt (sonst: Ersatz-Tab). Bis S8
#: war das der Knopf "Starten" (`chat_start`), den es nicht mehr gibt.
CHAT_TAB = "chat_eingabe"


def _feld_schmal(feld):
    """Ein Auswahlfeld, das schmal werden darf — die Liste zeigt alles.

    Ohne das richtet sich die Mindestbreite nach dem laengsten Eintrag
    ("Ultracode (Mehr-Agenten)"). Gemessen offscreen mit Windows-Schriften:
    Denkstufe 135 px statt 86 px, der Chat-Tab passte auch vorher in 300 px
    (238 px). Mit der Ersatzschrift von Qt waren es 324 px, und der Tab
    brauchte 500 px. Cadworks Schrift und Skalierung sind nicht gemessen —
    deshalb die Reserve. Die aufgeklappte Liste wird trotzdem so breit wie
    ihr laengster Eintrag (gemessen).
    """
    from PyQt6.QtWidgets import QComboBox
    feld.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    feld.setMinimumContentsLength(FELD_MIN_ZEICHEN)


def _laufend_kurz(text):
    """Das Ende der laufenden Antwort, hoechstens LAUFEND_ZEICHEN lang."""
    text = text or ""
    if len(text) <= LAUFEND_ZEICHEN:
        return text
    rest = text[-LAUFEND_ZEICHEN:]
    leer = rest.find(" ")
    if 0 <= leer < 40:
        rest = rest[leer + 1:]            # nicht mitten im Wort beginnen
    return "… " + rest


def _hoehe_nach_inhalt(teil, inhalt, mindest, hoechst, marke=None):
    """`teil` hoechstens so hoch wie `inhalt` bei seiner Breite braucht.

    Die wachsenden Teile des Chats (laufende Antwort, Freigabe-Karten)
    melden dem Dock KEINEN Hoehenwunsch (Groessenregel `Ignored`): sonst
    gaebe der Rollbereich des Docks dem Inhalt die Summe aller Wuensche,
    und die Eingabe rollte aus dem Bild. Ihren Platz holen sie ueber den
    Stretch — begrenzt durch diese Hoechsthoehe, damit unter einer
    kleinen Karte keine leere Flaeche steht.

    `marke` (im Takt): gerechnet wird nur, wenn sich Breite oder Marke
    geaendert haben — sonst kostete jeder 100-ms-Takt einen Textumbruch.

    Ist `teil` ein Rollbereich um `inhalt`, zaehlt die Breite OHNE
    Rollleiste und ohne Rahmen, und `_rollleiste_klaeren` nimmt eine Leiste
    weg, die Qt stehen liess, obwohl der Inhalt jetzt passt.
    """
    rolle = teil is not inhalt
    rand = 2 * teil.frameWidth() if rolle else 0
    breite = teil.width() - rand if teil.width() > 50 else 250
    if marke is None or getattr(teil, "_omcad_hoehe", None) != (breite,
                                                                 marke):
        if marke is not None:
            teil._omcad_hoehe = (breite, marke)
        if inhalt.hasHeightForWidth():
            h = inhalt.heightForWidth(breite)
        else:
            h = inhalt.sizeHint().height()
        if rolle:
            # Qt entscheidet ueber die Rollleiste auch nach der Mindestgroesse.
            h = max(h, inhalt.minimumSizeHint().height())
        teil._omcad_bedarf = h + rand
        h = max(mindest, min(hoechst, h + rand + 2))
        if teil.maximumHeight() != h:
            teil.setMaximumHeight(h)
    if rolle:
        _rollleiste_klaeren(teil)


def _rollleiste_klaeren(rolle):
    """Die senkrechte Rollleiste weg, wenn der Inhalt ganz hineinpasst.

    Qt laesst sie stehen, sobald sie einmal da war: mit ihr ist der Inhalt
    schmaler, bricht oefter um und scheint mehr Hoehe zu brauchen.
    Gemessen (Pruefung Etappe C, 300 px): eine Karte mit zwoelf Zeilen Code,
    Bereich 157 px, Inhalt bei 252 px Breite 155 px, bei 238 px (mit Leiste)
    182 px — die Leiste blieb, "Erlauben" und "Ablehnen" lagen darunter.
    Ein Wechsel der Regel laesst Qt frisch entscheiden (gemessen: dann ohne
    Leiste). Kostet im Takt nur zwei Abfragen.
    """
    leiste = rolle.verticalScrollBar()
    if not leiste.isVisible():
        return
    if rolle.height() < getattr(rolle, "_omcad_bedarf", 1 << 30):
        return                                  # passt wirklich nicht
    from PyQt6.QtCore import Qt
    rolle.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rolle.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _art_text(a):
    """Was laeuft, in einem Satz — aus der ART des Anbieters, nie aus dem Namen.

    Uebergabe 2026-09-25, Abschnitt 5: Claude Code ist der echte Agent
    (Kindprozess mit Arbeitsordner), die API-Anbieter laufen ueber die eigene
    Schleife NUR mit den Cadwork-Werkzeugen, Codex ueber `codex app-server`
    (dort sind Shell, Plugins und Browser abgeschaltet, `codex_konfig`).
    """
    art = (a or {}).get("art")
    if art == "cli":
        return ("Claude Code: ein Agent auf diesem Rechner. Er arbeitet im "
                "Arbeitsordner und in Cadwork.")
    if art == "codex":
        return ("Codex: ein Agent mit deinem ChatGPT-Konto, hier nur mit den "
                "Cadwork-Werkzeugen.")
    if art == "openai":
        # Ohne Namen: den nennt die Zeile darueber (`_wer_zeigen`).
        return ("Einfacher Chat: nur mit den Cadwork-Werkzeugen, ohne Zugriff "
                "auf Dateien.")
    return ""


def _art_zeigen(z, chat, an, gewaehlt):
    """Im Takt: die Zeile "was laeuft" — fuer den LAUFENDEN Chat, sonst fuer
    den gewaehlten Anbieter (wie `_wer_zeigen`). Billig, nur Speicher."""
    a = gewaehlt
    laeuft = chat.get("anbieter") if an else None
    if laeuft:
        try:
            a = _anbieter_modul().anbieter(laeuft) or gewaehlt
        except Exception:                              # noqa: BLE001
            a = gewaehlt
    text = _art_text(a)
    lbl = z["w"]["chat_art"]
    if lbl.text() != text:
        lbl.setText(text)
    if lbl.isHidden() == bool(text):
        lbl.setVisible(bool(text))


def _tab_chat(z, register):
    """Mit der KI reden, ohne Cadwork zu verlassen — die Seite "Gespraech"
    des Chatfensters (seit K2; vorher ein Tab im Dock, daher der Name).

    Der Briefkasten bleibt im Monitor und meint etwas anderes: dort legt der
    Nutzer einen Zettel hin, den IRGENDEINE Sitzung spaeter abholt. Hier
    sitzt er davor und redet jetzt.

    Der Chat haengt bewusst an der Verbindung: erst sie sagt, welcher
    Steckplatz und welche Cadwork-Datei gemeint sind — und genau die beiden
    bekommt der Kindprozess mit (`OPEN_MCP_CAD_PORT`, `OPEN_MCP_CAD_EXPECT_DOC`).
    Ein so gestarteter Chat kann gar nicht in die falsche Datei zeichnen.

    Aufbau seit K3 (Wunsch 2026-09-27, wie in den Apps von Claude Code und
    ChatGPT): oben der Ordnerknopf (Umrandung: gehoert nicht zum Gespraech)
    und "+ Ordner", darunter das Gespraech, unten die Eingabe in einem
    Rahmen mit der Leiste — links der Modus, rechts Modell mit Denkstufe
    und der Ring, wie voll der Kontext ist. Die Leiste sieht aus wie Text;
    ueber der Maus wird sie ein Knopf, ein Klick klappt NACH OBEN auf
    (`_aufklapper`, nie `exec()`). Anbieter, Schluessel, lokale Modelle
    und ein eigener Modellname stehen seit K12 auf der Einstellungsseite
    ("⋯" in der Segmentzeile).
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
                                 QLabel, QLineEdit, QListWidget, QPushButton,
                                 QScrollArea, QVBoxLayout, QWidget)
    from PyQt6.QtWidgets import QSizePolicy
    K = _qt_klassen()
    tab = QWidget()
    lay = QVBoxLayout(tab)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(CHAT_ABSTAND)
    kl = lay

    # -- Karte "Chat" auf der Einstellungsseite ----------------------------
    # Zuerst in `z["w"]`: scheitert der Bau weiter unten, raeumt
    # `_tab_chat_oder_ersatz` sie ueber diesen Schluessel wieder ab.
    ekarte, ekl = _karte("Chat")
    z["w"]["chat_einst_karte"] = ekarte
    platz = z["w"].get("einst_chat_lay")
    if platz is not None:
        platz.addWidget(ekarte)

    # -- Anbieter ----------------------------------------------------------
    # Wunsch 2026-09-24: nicht nur Claude Code, auch API-Schluessel und
    # lokale KI. Alles ausser Claude laeuft ueber EINE OpenAI-kompatible
    # Schleife (omcad_a_anbieter) mit denselben Freigabe-Karten.
    A0 = _anbieter_modul()
    C0 = _chat_modul()
    lbl_wer_e = QLabel("Wer antwortet")
    lbl_wer_e.setObjectName("neben")
    ekl.addWidget(lbl_wer_e)
    anbieter = QComboBox()
    for a in A0.ANBIETER:
        anbieter.addItem(a["name"], a["id"])
        if a.get("schluessel") == "pflicht":
            anbieter.setItemData(anbieter.count() - 1, SCHLUESSEL_TIPP,
                                 Qt.ItemDataRole.ToolTipRole)
    anbieter.setToolTip("Wer antwortet — wirkt beim nächsten Start")
    ekl.addWidget(anbieter)

    # Schluessel und Adresse: nur fuer die Anbieter ueber die Schleife.
    # Rueckmeldung (Uebergabe 2026-09-25, Abschnitt 2): "das mit der Website
    # kenne ich nicht", der Schluessel darf nie offen dastehen, und nach der
    # Eingabe sollen Schluessel und Adresse nicht mehr so praesent sein.
    api = QWidget()
    al = QVBoxLayout(api)
    al.setContentsMargins(0, 0, 0, 0)
    al.setSpacing(6)
    hilfe = QLabel("")
    hilfe.setObjectName("neben")
    hilfe.setWordWrap(True)
    link = QLabel("")
    link.setTextFormat(Qt.TextFormat.RichText)
    link.setOpenExternalLinks(True)
    link.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction)
    reihe_k = QHBoxLayout()
    reihe_k.setSpacing(6)
    schluessel = QLineEdit()
    schluessel.setEchoMode(QLineEdit.EchoMode.Password)
    schluessel.setPlaceholderText("Schlüssel hier einfügen …")
    # Rueckmeldung 2026-09-29: "API" verstand niemand. Das Fachwort steht
    # nur noch im Tooltip, als Erklaerung.
    schluessel.setToolTip(SCHLUESSEL_TIPP + " Wird erst mit «Speichern» im "
                          "Windows-Tresor abgelegt und danach nie mehr "
                          "angezeigt.")
    btn_speichern = QPushButton("Speichern")
    btn_speichern.setObjectName("primaer")
    btn_abbrechen = QPushButton("Abbrechen")
    reihe_k.addWidget(schluessel, 1)
    reihe_k.addWidget(btn_speichern)
    reihe_k.addWidget(btn_abbrechen)
    gespeichert = QWidget()
    gl = QHBoxLayout(gespeichert)
    gl.setContentsMargins(0, 0, 0, 0)
    gl.setSpacing(6)
    lbl_ende = QLabel("Schlüssel gespeichert")
    btn_aendern = QPushButton("ändern")
    btn_aendern.setObjectName("leiste")
    btn_entfernen = QPushButton("entfernen")
    btn_entfernen.setObjectName("leiste")
    gl.addWidget(lbl_ende)
    gl.addStretch(1)
    gl.addWidget(btn_aendern)
    gl.addWidget(btn_entfernen)
    gespeichert.hide()
    basis = QLineEdit()
    basis.setPlaceholderText("Adresse, z. B. http://localhost:11434/v1")
    basis.setToolTip("OpenAI-kompatible Adresse (endet meist auf /v1)")
    lbl_schluessel = QLabel("")
    lbl_schluessel.setObjectName("neben")
    lbl_schluessel.setWordWrap(True)
    al.addWidget(hilfe)
    al.addWidget(link)
    al.addLayout(reihe_k)
    al.addWidget(gespeichert)
    al.addWidget(basis)
    al.addWidget(lbl_schluessel)
    api.hide()
    ekl.addWidget(api)

    # -- Lokale Modelle (Uebergabe 2026-09-25, Abschnitt 3) ----------------
    # Stand, Starten, Installieren. Die Rueckfrage vor dem Installieren
    # steht HIER im Fenster, nicht in einem Dialog (nichts Modales).
    lokal = QWidget()
    ll = QVBoxLayout(lokal)
    ll.setContentsMargins(0, 0, 0, 0)
    ll.setSpacing(6)
    lokal_lage = QLabel("")
    lokal_lage.setObjectName("neben")
    lokal_lage.setWordWrap(True)
    reihe_l = QHBoxLayout()
    reihe_l.setSpacing(6)
    btn_lstart = QPushButton("Starten")
    btn_lstart.setObjectName("primaer")
    btn_linst = QPushButton("Installieren …")
    btn_linst.setObjectName("primaer")
    btn_lpruefen = QPushButton("Neu prüfen")
    for b in (btn_lstart, btn_linst, btn_lpruefen):
        reihe_l.addWidget(b)
        b.hide()
    reihe_l.addStretch(1)
    frage = QWidget()
    fql = QVBoxLayout(frage)
    fql.setContentsMargins(0, 0, 0, 0)
    fql.setSpacing(6)
    frage_text = QLabel("")
    frage_text.setWordWrap(True)
    reihe_f = QHBoxLayout()
    reihe_f.setSpacing(6)
    btn_ja = QPushButton("Ja, installieren")
    btn_ja.setObjectName("primaer")
    btn_nein = QPushButton("Abbrechen")
    reihe_f.addWidget(btn_ja)
    reihe_f.addWidget(btn_nein)
    reihe_f.addStretch(1)
    fql.addWidget(frage_text)
    fql.addLayout(reihe_f)
    frage.hide()
    ll.addWidget(lokal_lage)
    ll.addLayout(reihe_l)
    ll.addWidget(frage)
    lokal.hide()
    ekl.addWidget(lokal)

    # -- Modell: das Feld (eigener Name) auf den Chat-Einstellungen --------
    # Vorgabe Sonnet 5 / xhigh (2026-08-09), aber waehlbar. Beides wirkt
    # erst beim naechsten Start — mitten im Gespraech laesst sich das
    # Modell nicht wechseln (Entscheid 2026-09-26: gesperrt mit Hinweis).
    # Gewaehlt wird in der Leiste (`_modell_aufklappen`); dieses Feld
    # bleibt die Quelle der Liste und nimmt einen EIGENEN Namen an.
    lbl_modell = QLabel("Modell")
    lbl_modell.setObjectName("neben")
    ekl.addWidget(lbl_modell)
    reihe_m = QHBoxLayout()
    reihe_m.setSpacing(6)
    modell = QComboBox()
    for anzeige, wert in C0.MODELLE:
        modell.addItem(anzeige, wert)
    modell.setCurrentIndex(
        [w for _, w in C0.MODELLE].index(C0.MODELL_VORGABE))
    # BESCHREIBBAR, damit auch aeltere Fassungen gehen: der Nutzer tippt den vollen
    # Namen (`claude-opus-4-7`). Welche das CLI annimmt, laesst sich hier
    # nicht nachschlagen — lehnt es einen ab, steht der Grund im Chat.
    modell.setEditable(True)
    modell.setToolTip("Wirkt beim nächsten Start. Eigenen Namen eintippen "
                      "geht auch, z. B. claude-opus-4-7")
    # Die Modelle der anderen Anbieter stehen in keiner Liste im Code: der
    # Dienst selbst nennt sie (GET /models) — im Hintergrund, nie im Takt.
    # Aussehen und Text setzt `_modelle_knopf` je nach Stand der Liste.
    btn_modelle = QPushButton(MODELLE_KNOPF_OFFEN)
    btn_modelle.setObjectName("hinweis")
    btn_modelle.setToolTip("Modelle beim Anbieter abfragen")
    btn_modelle.hide()
    _feld_schmal(modell)
    reihe_m.addWidget(modell, 1)
    reihe_m.addWidget(btn_modelle)
    ekl.addLayout(reihe_m)

    # -- Kopf: Ordner (nur Claude Code), Neuer Chat, Beenden, ⚙ ------------
    # Uebergabe 2026-09-25, Abschnitt 5, und Wunsch 2026-09-27: der Ordner
    # links oben als Knopf mit Umrandung — er gehoert nicht zum Gespraech.
    # Der Dialog ist Qts eigener, NICHT der von Windows, und er haelt nichts
    # an (`open()`, nie `exec()`; Plan B.9, Arbeitsregel 9).
    # Zeile 1: Ordner, "+ Ordner", ⚙. Darunter (nur wenn es welche gibt)
    # die weiteren Ordner. Zeile 2: wer antwortet, "Neuer Chat", "Beenden".
    # Zwei Zeilen, weil alles in einer das Fenster bei 300 px quer
    # rollen liess (gemessen, L59).
    kopf = QHBoxLayout()
    # 4 statt 6 px (K9b): mit "Beenden" als Wort passt der Kopf bei 460 px
    # (Segoe UI 9 pt) sonst um 2 px nicht, und der Ordnerknopf kuerzte.
    kopf.setSpacing(4)
    ordner_teil = QWidget()
    ol = QVBoxLayout(ordner_teil)
    ol.setContentsMargins(0, 0, 0, 0)
    ol.setSpacing(4)
    ot = QHBoxLayout()
    ot.setSpacing(6)
    ol.addLayout(ot)
    ordner_knopf = K.KnappKnopf("Ordner wählen")
    ordner_knopf.setObjectName("ordner")
    ordner_knopf.setToolTip("Der Ordner, in dem Claude Code arbeitet")
    _knopf_symbol(ordner_knopf, "ordner", text="Ordner wählen", groesse=15)
    zusatz = QPushButton("Ordner")
    zusatz.setObjectName("flach")
    zusatz.setAccessibleName("Weiterer Ordner")
    _knopf_symbol(zusatz, "ordner_plus", text="Ordner",
                  farbe=FARBEN["neben"], groesse=15)
    zusatz.setToolTip("Einen weiteren Ordner freigeben, auf den Claude Code "
                      "zugreifen darf (gilt ab dem nächsten Chat)")
    zusatz_lay = QHBoxLayout()
    zusatz_lay.setSpacing(4)
    # So breit wie sein Text (links oben wie in der Claude-Code-App), nicht
    # ueber die ganze Zeile — im Bild zu K5 gesehen; schmal wird er nur, wenn
    # das Fenster es verlangt (`KnappKnopf`).
    ot.addWidget(ordner_knopf)
    ot.addWidget(zusatz)
    ot.addStretch(1)
    ol.addLayout(zusatz_lay)
    kopf.addWidget(ordner_teil, 1)
    # "Neuer Chat" beendet einen laufenden sauber und leert den Verlauf;
    # "Beenden" steht nur da, solange ein Chat laeuft (S8). Seit dem
    # Feinschliff 2026-09-28 als ruhige Zeichen oben rechts (wie in den
    # Chat-Apps); der Name steht im Tooltip und als `accessibleName`.
    # K9 (Rueckmeldung 2026-09-28: "das ✎ ist kaum zu erkennen"): Strich-
    # Symbole, bei "Neuer Chat" mit dem Wort, solange es Platz hat.
    btn_neu = K.KnappKnopf("Neuer Chat", weglassen=True,
                           ab_breite=NEU_TEXT_AB)
    btn_neu.setObjectName("flach")
    btn_neu.setAccessibleName("Neuer Chat")
    btn_neu.setToolTip("Neuer Chat — ein laufender endet, der Verlauf wird "
                       "geleert.")
    _knopf_symbol(btn_neu, "neuer_chat", text="Neuer Chat")
    # K9b (Rueckmeldung 2026-09-28: das Stopp-Zeichen war nicht zu
    # erkennen): gefuelltes Quadrat UND das Wort, solange Platz ist (wie
    # "Neuer Chat"); links davon, damit "Neuer Chat" oben rechts bleibt.
    # Ohne QtSvg steht nur das Wort.
    btn_ende = K.KnappKnopf("", weglassen=True, ab_breite=BEENDEN_TEXT_AB)
    btn_ende.setObjectName("flach")
    btn_ende.setAccessibleName("Beenden")
    btn_ende.setToolTip("Beenden — den Chat beenden. Arbeitet er gerade, "
                        "wird nachgefragt.")
    _knopf_symbol(btn_ende, "beenden", text="Beenden", groesse=13)
    btn_ende.hide()
    # Ein Stretch OHNE Faktor: steht die Ordnerzeile (Faktor 1), bekommt er
    # nichts; ist sie versteckt (Codex, Schluessel-Anbieter), haelt er
    # "Neuer Chat" rechts — sonst stand das ✎ allein mitten in der Zeile
    # (Gegenpruefung K12, Bild 09).
    kopf.addStretch(0)
    kopf.addWidget(btn_ende, 0, Qt.AlignmentFlag.AlignTop)
    kopf.addWidget(btn_neu, 0, Qt.AlignmentFlag.AlignTop)
    # K12: kein ⚙ mehr — die Einstellungen stehen hinter "⋯" in der
    # Segmentzeile (Spezifikation 3.3).
    kl.addLayout(kopf)

    # -- Wer antwortet, was laeuft: auf die Chat-Einstellungen ---------------
    # Feinschliff 2026-09-28: ueber dem Gespraech stand Technik ("Claude
    # Code (Abo) · Modus", "ein Agent auf diesem Rechner", "läuft ·
    # claude-sonnet-5 · Cadwork-Werkzeuge: ja · Fachwissen: ja"). Modus und
    # Modell stehen in der Leiste; der Rest gehoert in "Technik-Details".
    # Ueber dem Gespraech steht nur noch EINE Zeile, und nur, wenn etwas
    # nicht stimmt (`_status_zeigen`).
    # In der Karte "Technik-Details" der Einstellungsseite: ohne eigene
    # Karte und ohne zweiten Titel (Gegenpruefung K12).
    tkarte, tkl = _abschnitt("Chat")
    tkarte.setObjectName("chat_technik")
    z["w"]["chat_technik_karte"] = tkarte
    wer = QLabel("")
    # "ist das Claude Code/Codex oder normale Chat-Funktion?" (Uebergabe
    # 2026-09-25, Abschnitt 5) — aus der ART des Anbieters (`_art_text`).
    art = QLabel("")
    lbl_lage = QLabel("Zuerst verbinden")
    for lb in (wer, art, lbl_lage):
        lb.setObjectName("neben")
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        tkl.addWidget(lb)
    # K12: in den Technik-Details der Einstellungsseite (zugeklappt).
    platz_t = z["w"].get("einst_technik_lay") or platz
    if platz_t is not None:
        platz_t.addWidget(tkarte)
    else:
        kl.addWidget(tkarte)
    tkarte.hide()
    status = QLabel("")
    status.setObjectName("status")
    status.setWordWrap(True)
    status.hide()
    # Das Warnzeichen als Strich-Symbol vor der Zeile (K9, statt "⚠").
    status_symbol = QLabel("")
    status_symbol.setObjectName("status_symbol")
    _label_symbol(status_symbol, "triangle-alert", "!", "#9a4a00", 14)
    status_symbol.hide()
    status_reihe = QHBoxLayout()
    status_reihe.setSpacing(6)
    status_reihe.addWidget(status_symbol, 0, Qt.AlignmentFlag.AlignTop)
    status_reihe.addWidget(status, 1)
    kl.addLayout(status_reihe)

    # -- Bisherige Chats (S9) ----------------------------------------------
    # Nur Claude Code und nur Chats, die das Dock angelegt hat (C.SITZUNG_NAME).
    # Sichtbar, solange kein Chat laeuft und der Verlauf leer ist; ein
    # Klick oeffnet den Chat, die naechste Nachricht setzt IHN fort
    # (`--resume`, Entscheid 2026-09-26). Gefuellt im Nebenthread.
    liste_titel = QLabel("Bisherige Chats — anklicken zum Weitermachen")
    liste_titel.setObjectName("neben")
    liste_titel.setWordWrap(True)
    liste_titel.hide()
    kl.addWidget(liste_titel)
    liste = QListWidget()
    liste.setWordWrap(True)
    # Eintraege bei jeder Breite neu umbrechen — sonst rollte ein langer
    # Titel quer (gemessen im Chatfenster, L62).
    liste.setResizeMode(QListWidget.ResizeMode.Adjust)
    # Ohne seitlichen Innenabstand: den rechnet Qt beim Umbrechen nicht mit,
    # und die Liste rollte um genau diese 8 px quer (L62, im Chatfenster).
    liste.setObjectName("chatliste")
    liste.setToolTip("Einen früheren Chat öffnen. Die nächste Nachricht "
                     "setzt ihn fort.")
    liste.setMinimumHeight(VERLAUF_MIN_HOEHE)
    liste.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Ignored)
    liste.hide()
    kl.addWidget(liste, 1)

    # Erster Kontakt (2026-09-29): an der Stelle des leeren Verlaufs,
    # solange noch nichts eingerichtet ist (`_einstieg_takt`).
    kl.addWidget(_einstieg_bauen(z), 1)

    # K5: Blasen, Schrittgruppen und Zeitlinien statt Listenzeilen.
    verlauf = K.Verlauf()
    # 200 px waren zu viel (S7): mit Kopf, Karten und Eingabe schob das die
    # Eingabe aus dem Bild.
    verlauf.setMinimumHeight(VERLAUF_MIN_HOEHE)
    verlauf.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Ignored)
    kl.addWidget(verlauf, 1)

    # Die laufende Antwort steht UNTER dem Verlauf, nicht darin: sie waechst
    # zeichenweise. Gezeigt wird nur ihr ENDE (`_laufend_kurz`) in
    # begrenzter Hoehe (Plan B.11). Ganz steht sie danach im Verlauf.
    laufend = QLabel("")
    laufend.setObjectName("chat_laufend")
    laufend.setWordWrap(True)
    laufend.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    laufend.setMinimumHeight(LAUFEND_MIN_HOEHE)
    laufend.setMaximumHeight(LAUFEND_MAX_HOEHE)
    laufend.setSizePolicy(QSizePolicy.Policy.Preferred,
                          QSizePolicy.Policy.Ignored)
    laufend.hide()
    # Hoher Stretch: erst bekommen laufende Antwort und Karten ihre Hoehe
    # (begrenzt durch `_hoehe_nach_inhalt`), der Rest geht an den Verlauf.
    kl.addWidget(laufend, 20)

    # -- Freigaben (S7: ueber der Eingabe) ---------------------------------
    # In einem eigenen Rollbereich mit Hoechstmass: drei Karten mit
    # aufgeklapptem Wortlaut schoben sonst die Eingabe aus dem Bild.
    freigabe = QWidget()
    freigabe.setObjectName("rollinhalt")
    fl = QVBoxLayout(freigabe)
    fl.setContentsMargins(0, 0, 0, 0)
    fl.setSpacing(6)
    freigabe_rolle = QScrollArea()
    freigabe_rolle.setObjectName("rolle")
    freigabe_rolle.setWidgetResizable(True)
    freigabe_rolle.setWidget(freigabe)
    freigabe_rolle.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    freigabe_rolle.setMinimumHeight(FREIGABE_MIN_HOEHE)
    freigabe_rolle.setMaximumHeight(FREIGABE_MAX_HOEHE)
    freigabe_rolle.setSizePolicy(QSizePolicy.Policy.Preferred,
                                 QSizePolicy.Policy.Ignored)
    freigabe_rolle.hide()
    kl.addWidget(freigabe_rolle, 20)

    # -- Fehlerzeile an der Eingabe (S7) -----------------------------------
    # Sie bleibt, bis der Nutzer wieder handelt (`_chat_fehler_quittieren`).
    fehler = QLabel("")
    fehler.setObjectName("chat_fehler")
    fehler.setWordWrap(True)
    fehler.setStyleSheet("color: %s; font-size: 11px;" % FARBEN["rot"])
    fehler.hide()
    kl.addWidget(fehler)

    # -- Die Eingabe im Rahmen, darunter die Leiste (K3) --------------------
    rahmen = QFrame()
    rahmen.setObjectName("eingaberahmen")
    rl = QVBoxLayout(rahmen)
    rl.setContentsMargins(10, 6, 8, 6)
    rl.setSpacing(2)
    # Die Anhaenge als kleine Knoepfe ueber dem Text (K4), je 3 in einer
    # Zeile; ein Klick nimmt einen heraus.
    anhaenge = QWidget()
    anhaenge_lay = QGridLayout(anhaenge)
    anhaenge_lay.setContentsMargins(0, 2, 0, 2)
    anhaenge_lay.setSpacing(4)
    anhaenge.hide()
    rl.addWidget(anhaenge)
    feld = _Eingabe.bauen(
        lambda: _sicher(lambda: _chat_senden(z), "Chat senden"),
        anhang=lambda quelle: _anhang_aus_mime_sicher(z, quelle))
    feld.setPlaceholderText("Claude fragen …")
    rl.addWidget(feld)
    leiste = QHBoxLayout()
    leiste.setSpacing(2)
    # Links "+" (Datei oder Foto) und der Modus (immer sichtbar, jederzeit
    # waehlbar).
    plus = QPushButton("")
    plus.setObjectName("flach")
    # 36 statt 28 px: das Symbol braucht mit dem Innenabstand von `flach`
    # so viel (sonst gequetscht, L59).
    plus.setFixedWidth(36)
    plus.setAccessibleName("Anhang")
    plus.setToolTip("Datei oder Foto hinzufügen — auch mit Strg+V oder durch "
                    "Hineinziehen")
    _knopf_symbol(plus, "plus")
    leiste.addWidget(plus)
    modus = K.KnappKnopf("")
    modus.setObjectName("flach")
    leiste.addWidget(modus)
    leiste.addStretch(1)
    # Rechts Modell (mit Denkstufe) und der Ring, dann Senden.
    modell_knopf = K.KnappKnopf("")
    modell_knopf.setObjectName("flach")
    modell_knopf.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    _knopf_symbol(modell_knopf, "auf", text="", farbe=FARBEN["neben"],
                  groesse=14)
    kontext = K.Kontextring()
    kontext.hide()
    btn = QPushButton("")
    btn.setObjectName("senden")
    btn.setFixedSize(32, 32)
    btn.setAccessibleName("Senden")
    btn.setToolTip("Senden (Enter) — Shift+Enter macht eine neue Zeile. Die "
                   "erste Nachricht startet den Chat.")
    _knopf_symbol(btn, "senden", farbe="#ffffff", groesse=18)
    leiste.addWidget(modell_knopf)
    leiste.addWidget(kontext)
    leiste.addWidget(btn)
    rl.addLayout(leiste)
    kl.addWidget(rahmen)
    _seite_einsetzen(register, tab)

    # -- Die Aufklapper (K3): gebaut EINMAL, gefuellt bei jedem Oeffnen -----
    # Modell und Denkstufe seit K12 als Popover (Vorbild Bild 2): die Stufe
    # als Punktregler UNTEN, die Modelle als Liste DARUEBER; der Regler
    # traegt die Schnittstelle eines Auswahlfelds (`Punktregler`), damit
    # Merken und Start unveraendert bleiben.
    stufe = K.Punktregler(C0.EFFORT_STUFEN)
    # Die gemerkte Denkstufe, sonst die Vorgabe. Film 2026-09-25: nach jedem
    # Cadwork-Neustart stand wieder "sehr hoch" da. Gemerkt wird bei jeder
    # Wahl (`activated` unten) und beim Start (`_cli_wahl_merken`).
    stufe.setCurrentIndex([w for _, w in C0.EFFORT_STUFEN].index(
        _cli_stufe(_einstellungen(A0), C0)))
    stufe.setToolTip("Denkstufe — wirkt beim nächsten Start")
    modell_auf = _popover_bauen(z, tab, stufe)
    modus_auf = K.Aufklapper(tab)
    plus_auf = K.Aufklapper(tab)
    ordner_auf = K.Aufklapper(tab)
    ordner_text = QLabel("")
    ordner_text.setWordWrap(True)
    ordner_text.setMaximumWidth(AUFKLAPPER_BREITE)
    # NICHT markierbar: der Text traegt nach jedem Trenner ein unsichtbares
    # U+200B (`_umbrechbar`), und ein kopierter Pfad waere im Explorer
    # ungueltig (Nacharbeit D). Den ganzen Pfad zeigt der Tooltip.
    ordner_satz = QLabel("Claude Code arbeitet nur in diesem Ordner. Die "
                         "bisherigen Chats gehören zu ihm.")
    ordner_satz.setObjectName("neben")
    ordner_satz.setWordWrap(True)
    ordner_satz.setMaximumWidth(AUFKLAPPER_BREITE)
    btn_ordner = K.eintrag("Arbeitsordner wählen …", symbol="folder-open")
    btn_ordner.setToolTip("Den Ordner wählen, in dem Claude Code arbeitet")
    btn_ordner_weg = K.eintrag("Wahl entfernen")
    btn_ordner_weg.setToolTip("Die Wahl vergessen")
    btn_ordner_weg.hide()
    ordner_auf.oben_fest.addWidget(ordner_text)
    ordner_auf.oben_fest.addWidget(ordner_satz)
    ordner_auf.unten.addWidget(btn_ordner)
    ordner_auf.unten.addWidget(btn_ordner_weg)

    btn.clicked.connect(lambda: _sicher(lambda: _chat_senden(z),
                                        "Chat senden"))
    btn_neu.clicked.connect(lambda: _sicher(lambda: _chat_neu(z),
                                            "Neuer Chat"))
    btn_ende.clicked.connect(lambda: _sicher(lambda: _chat_beenden_geklickt(z),
                                             "Chat beenden"))
    liste.itemClicked.connect(lambda item: _sicher(
        lambda: _sitzung_oeffnen(z, item), "Chat öffnen"))
    z["w"].update(chat_liste=liste, chat_liste_titel=liste_titel,
                  chat_neu=btn_neu, chat_ende=btn_ende,
                  chat_art=art, chat_fehler=fehler, chat_kontext=kontext,
                  chat_status=status, chat_status_symbol=status_symbol,
                  chat_lage=lbl_lage,
                  chat_freigabe=freigabe_rolle, chat_freigabe_lay=fl,
                  chat_verlauf=verlauf, chat_eingabe=feld, chat_senden=btn,
                  chat_eingaberahmen=rahmen,
                  chat_plus=plus, chat_plus_auf=plus_auf,
                  chat_anhaenge=anhaenge, chat_anhaenge_lay=anhaenge_lay,
                  chat_modell=modell, chat_stufe=stufe,
                  chat_modell_knopf=modell_knopf,
                  chat_modell_auf=modell_auf, chat_modus=modus,
                  chat_modus_auf=modus_auf,
                  chat_laufend=laufend,
                  chat_anbieter=anbieter, chat_api=api, chat_basis=basis,
                  chat_schluessel=schluessel,
                  chat_schluessel_lage=lbl_schluessel,
                  chat_schluessel_hilfe=hilfe, chat_schluessel_link=link,
                  chat_schluessel_speichern=btn_speichern,
                  chat_schluessel_abbrechen=btn_abbrechen,
                  chat_schluessel_gespeichert=gespeichert,
                  chat_schluessel_ende=lbl_ende,
                  chat_schluessel_aendern=btn_aendern,
                  chat_schluessel_entfernen=btn_entfernen,
                  chat_lokal=lokal, chat_lokal_lage=lokal_lage,
                  chat_lokal_starten=btn_lstart,
                  chat_lokal_installieren=btn_linst,
                  chat_lokal_pruefen=btn_lpruefen,
                  chat_lokal_frage=frage, chat_lokal_frage_text=frage_text,
                  chat_lokal_ja=btn_ja, chat_lokal_nein=btn_nein,
                  chat_wer=wer,
                  chat_modelle=btn_modelle,
                  chat_ordner_teil=ordner_teil, chat_ordner=ordner_knopf,
                  chat_ordner_auf=ordner_auf,
                  chat_ordner_text=ordner_text,
                  chat_ordner_waehlen=btn_ordner,
                  chat_ordner_weg=btn_ordner_weg,
                  chat_zusatz=zusatz, chat_zusatz_lay=zusatz_lay)

    # Die Ordnerwahl im Dock (Rang 2 nach OPEN_MCP_CAD_PROJEKT, vor
    # projektordner.txt; `arbeitsordner`). Einmal beim Aufbau aus chat.json,
    # danach nur noch aus dem Zustand — der Takt liest keine Datei.
    z["ordner_wahl"] = _gemerkter_ordner(_einstellungen(A0))
    z["zusatz_ordner"] = _gemerkte_ordnerliste(_einstellungen(A0),
                                               "zusatzordner", ZUSATZ_MAX)
    z["ordner_zuletzt"] = _gemerkte_ordnerliste(
        _einstellungen(A0), "ordner_zuletzt", ORDNER_ZULETZT_MAX)
    _modus_zeigen(z)
    # Die Liste gehoert zu diesem (neuen) Widget: neu zeichnen. Geholt wird
    # sie beim ersten Bau ohnehin (`liste_anlass` 1, `liste_stand` 0).
    z["liste_gezeigt"] = None
    _ordner_zeigen(z)
    _zusatz_zeigen(z)
    # Zuletzt benutzter Anbieter (ohne Schluessel, der liegt im Tresor).
    gemerkt = _einstellungen(A0).get("anbieter")
    i = anbieter.findData(gemerkt) if isinstance(gemerkt, str) else -1
    if i < 0:
        i = anbieter.findData(A0.ANBIETER_VORGABE)
    anbieter.setCurrentIndex(i if i >= 0 else 0)
    _anbieter_gewechselt(z)
    # In `_sicher`: eine Ausnahme, die aus einem Qt-Slot laeuft, endet in
    # Cadwork in qFatal (PyQt6 ohne eigenen excepthook). Gegenpruefung
    # 2026-09-26: ein tief verschachteltes chat.json warf hier beim Merken
    # RecursionError (test_a_live L43).
    anbieter.currentIndexChanged.connect(
        lambda: _sicher(lambda: _anbieter_gewechselt(z, merken=True),
                        "Anbieter wechseln"))
    # Seit Etappe E auch diese vier ueber `_sicher`: `_modelle_abfragen`
    # liest seit S6 chat.json (`_modelle_stand`), und ein Fehler aus einem
    # Qt-Slot beendet Cadwork (L43). Gemessen in test_a_live L66.
    btn_modelle.clicked.connect(
        lambda: _sicher(lambda: _modelle_abfragen(z), "Modelle abfragen"))
    modell.activated.connect(
        lambda i: _sicher(lambda: _modell_gewaehlt(z, i), "Modell wählen"))
    # `activated` kommt nur von einer Wahl des NUTZERS, nie vom Setzen im
    # Code — das Aufbauen des Tabs schreibt also nichts.
    stufe.activated.connect(
        lambda _i: _sicher(lambda: (_cli_wahl_merken(z),
                                    _modell_knopf_zeigen(z)),
                           "Denkstufe merken"))
    modell.editTextChanged.connect(
        lambda t: _sicher(lambda: _modell_getippt(z, t), "Modell tippen"))
    basis.textChanged.connect(
        lambda _t: _sicher(lambda: _modelle_knopf(z), "Adresse tippen"))
    # Schluessel: Speichern ist eine EIGENE Aktion (S6). Das Tippen allein
    # aendert nichts — auch nicht den Stand der Modellliste.
    btn_speichern.clicked.connect(
        lambda: _sicher(lambda: _schluessel_speichern(z), "Schlüssel speichern"))
    schluessel.returnPressed.connect(
        lambda: _sicher(lambda: _schluessel_speichern(z), "Schlüssel speichern"))
    btn_abbrechen.clicked.connect(
        lambda: _sicher(lambda: _schluessel_aendern(z, False),
                        "Schlüssel ändern"))
    btn_aendern.clicked.connect(
        lambda: _sicher(lambda: _schluessel_aendern(z, True),
                        "Schlüssel ändern"))
    btn_entfernen.clicked.connect(
        lambda: _sicher(lambda: _schluessel_entfernen(z),
                        "Schlüssel entfernen"))
    btn_lstart.clicked.connect(
        lambda: _sicher(lambda: _lokal_starten(z), "Lokal starten"))
    btn_linst.clicked.connect(
        lambda: _sicher(lambda: _lokal_fragen(z), "Lokal installieren"))
    btn_lpruefen.clicked.connect(
        lambda: _sicher(lambda: _lokal_pruefen(
            z, _gewaehlter_anbieter(z)["id"], erzwingen=True), "Lokal prüfen"))
    btn_ja.clicked.connect(
        lambda: _sicher(lambda: _lokal_installieren(z), "Lokal installieren"))
    btn_nein.clicked.connect(
        lambda: _sicher(lambda: _lokal_frage_weg(z), "Lokal installieren"))
    btn_ordner.clicked.connect(lambda: _sicher(
        lambda: _ordner_waehlen(z), "Arbeitsordner wählen"))
    btn_ordner_weg.clicked.connect(lambda: _sicher(
        lambda: _ordner_vergessen(z), "Arbeitsordner vergessen"))
    ordner_knopf.clicked.connect(lambda: _sicher(
        lambda: _ordner_aufklappen(z), "Ordner-Menü"))
    zusatz.clicked.connect(lambda: _sicher(
        lambda: _zusatz_waehlen(z), "Ordner hinzufügen"))
    modus.clicked.connect(lambda: _sicher(
        lambda: _modus_aufklappen(z), "Modus-Menü"))
    plus.clicked.connect(lambda: _sicher(
        lambda: _plus_aufklappen(z), "Anhang-Menü"))
    modell_knopf.clicked.connect(lambda: _sicher(
        lambda: _modell_aufklappen(z), "Modell-Menü"))

    _chat_takt_starten(z, tab)


# --- Die Leiste unter der Eingabe und ihre Aufklapper (K3, 2026-09-27) --------
# Wunsch 2026-09-27 (wie in den Apps von Claude Code und ChatGPT): die
# Bedienteile sehen aus wie Text; ueber der Maus bekommen sie einen dunkleren
# grauen, runden Hintergrund (QSS `flach`), ein Klick klappt NACH OBEN auf.
#
# Ein Aufklapper ist ein eigenes Fenster mit `Qt.WindowType.Popup`, gezeigt
# mit `show()` — kehrt sofort zurueck, KEINE verschachtelte
# Ereignisschleife (`QMenu.exec()` haette eine; waehrend der hielte der Kern
# Cadwork-Auftraege zurueck, s. "Zurueckhalten" in CLAUDE.md). Auch ein
# offener Aufklapper haelt sie zurueck (Sonde `popup`: activePopupWidget) —
# wie jedes Menue von Cadwork selbst, nur so lange er offen ist; ein Klick
# daneben schliesst ihn.

#: So breit werden Texte in einem Aufklapper hoechstens (Umbruch darueber).
AUFKLAPPER_BREITE = 300
#: So viele zuletzt benutzte Arbeitsordner stehen im Ordner-Menue.
ORDNER_ZULETZT_MAX = 5
#: So viele weitere Ordner ("+ Ordner") darf Claude Code sehen.
ZUSATZ_MAX = 3
#: Ab dieser Breite des Gespraechs steht "Neuer Chat" als Wort neben dem
#: Symbol (K9); schmaler nur das Symbol — der Ordnername geht vor.
NEU_TEXT_AB = 340
#: Dasselbe fuer "Beenden" (K9b) — es steht nur, solange ein Chat laeuft.
BEENDEN_TEXT_AB = 340
#: Ab diesem Fuellstand (Prozent) steht er unter der Eingabe
#: (`_kontext_sichtbar`), und so breit ist sein Balken.
KONTEXT_AB = 50
KONTEXT_BALKEN = 26
#: So schmal darf ein Knopf der Leiste werden (dann gekuerzt), und so viel
#: braucht er neben seinem Text (Innenabstand aus dem QSS).
KNAPP_MIN = 56
KNAPP_RAND = 22

_KLASSEN = {}


def _qt_klassen():
    """Die Qt-Klassen der Leiste — einmal je Laden dieses Moduls gebaut (Qt
    wird hier erst importiert, wenn eine QApplication da ist)."""
    if _KLASSEN:
        return _KLASSEN["ns"]
    import re as _re
    import types
    from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
    from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                 QScrollArea, QSizePolicy, QSlider,
                                 QVBoxLayout, QWidget)

    class KnappKnopf(QPushButton):
        """Ein Knopf der Leiste, der schmal werden darf: er wuenscht sich den
        ganzen Text, begnuegt sich aber mit KNAPP_MIN px und kuerzt dann mit
        "…" (Chatfenster 300 px breit, L59). `volltext()` ist der ganze."""

        def __init__(self, text="", weglassen=False, ab_breite=0):
            super().__init__(text)
            self._voll = text
            # `ab_breite` (K9): mit `weglassen` steht der Text nur, wenn die
            # Seite (Eltern) mindestens so breit ist — sonst nur das Symbol,
            # damit im schmalen Fenster der Ordnername den Platz bekommt.
            self._ab_breite = ab_breite
            self._knapp = False
            self._beobachtet = None
            # `weglassen` (K9): passt der Text nicht, steht nur das Symbol
            # ("Neuer Chat" im schmalen Fenster) — statt eines gekuerzten
            # Worts. Ohne Symbol wird wie sonst gekuerzt.
            self._weglassen = weglassen
            # `Preferred` statt der Vorgabe `Minimum` eines Knopfs: nur so
            # nimmt das Layout die kleine Mindestbreite ernst (bei `Minimum`
            # ist der Wunsch zugleich das Mindestmass; gemessen, L63).
            self.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Fixed)

        def setText(self, text):                       # noqa: N802
            self._voll = text or ""
            self._kuerzen()

        def volltext(self):
            return self._voll

        def _symbolbreite(self):
            """Platz fuer ein Symbol (K9) — 0 ohne."""
            if self.icon().isNull():
                return 0
            return self.iconSize().width() + (6 if self._voll else 0)

        def _nur_symbol(self):
            """Nur das Symbol zeigen: `weglassen`, ein Symbol, und die Seite
            ist schmaler als `ab_breite`."""
            if not (self._weglassen and self._ab_breite) \
                    or self.icon().isNull():
                return False
            p = self.parentWidget()
            return p is not None and p.width() < self._ab_breite

        def eventFilter(self, obj, e):                 # noqa: N802
            # Die Seite aendert ihre Breite: neu entscheiden (der Knopf
            # selbst bekommt dabei nicht immer ein resizeEvent).
            # Eine Ausnahme hier waere in Cadwork qFatal: nie werfen.
            try:
                if e.type() == e.Type.Resize:
                    self._kuerzen()
            except Exception as exc:                   # noqa: BLE001
                _melden("Knopf kürzen", exc)
            return False

        def sizeHint(self):                            # noqa: N802
            h = super().sizeHint()
            if self._nur_symbol():
                return QSize(self.iconSize().width() + KNAPP_RAND, h.height())
            return QSize(self.fontMetrics().horizontalAdvance(self._voll)
                         + KNAPP_RAND + self._symbolbreite(), h.height())

        def minimumSizeHint(self):                     # noqa: N802
            h = super().minimumSizeHint()
            unten = KNAPP_MIN
            if self._weglassen and not self.icon().isNull():
                unten = self.iconSize().width() + KNAPP_RAND
            return QSize(min(unten, self.sizeHint().width()), h.height())

        def resizeEvent(self, e):                      # noqa: N802
            super().resizeEvent(e)
            self._kuerzen()

        def showEvent(self, e):                        # noqa: N802
            super().showEvent(e)
            p = self.parentWidget()
            if self._ab_breite and p is not None \
                    and p is not self._beobachtet:
                p.installEventFilter(self)
                self._beobachtet = p
            self._kuerzen()

        def _kuerzen(self):
            knapp = self._nur_symbol()
            if knapp != self._knapp:
                self._knapp = knapp
                self.updateGeometry()
            breite = self.width() - KNAPP_RAND - self._symbolbreite()
            passt = self.fontMetrics().horizontalAdvance(self._voll) <= breite
            if knapp:
                text = ""
            elif not self.isVisible() or passt \
                    or (breite <= 0 and not self._weglassen):
                text = self._voll
            elif self._weglassen and not self.icon().isNull():
                text = ""
            else:
                text = self.fontMetrics().elidedText(
                    self._voll, Qt.TextElideMode.ElideMiddle, breite)
            if QPushButton.text(self) != text:
                QPushButton.setText(self, text)

    def eintrag(text, tipp="", symbol=None, haken=None):
        """Ein Eintrag eines Aufklappers: sieht aus wie Text, ueber der Maus
        grau hinterlegt (QSS `eintrag`). `symbol`: Lucide-Name davor (K9);
        `haken` True/False: ein Haken bzw. gleich viel Platz (so stehen die
        Texte buendig)."""
        b = QPushButton(text)
        b.setObjectName("eintrag")
        b.haken = bool(haken)
        name = "check" if haken else symbol
        ikone = _ikone(name, FARBEN["blau"] if haken else FARBEN["text"]) \
            if name else None
        if ikone is not None:
            b.setIcon(ikone)
        elif haken is not None:
            # Ohne Symbol: der Haken als Text (wie vor K9), sonst Platz.
            leer = _ikone("check", "#00000000") if not haken else None
            if leer is not None:
                b.setIcon(leer)
            else:
                b.setText(("✓  " if haken else "     ") + text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Fixed)
        if tipp:
            b.setToolTip(tipp)
        return b

    class Zeile(QFrame):
        """Ein Eintrag mit Titel und Satz (Modus): zwei Zeilen, die ganze
        Flaeche nimmt den Klick. `click()` wie ein Knopf (auch fuer die
        Gates), `wert` sagt, wofuer sie steht."""

        def __init__(self, titel, satz, wenn, haken=False, wert=None,
                     symbol=None):
            super().__init__()
            self.setObjectName("zeile")
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.wert, self._wenn, self.haken = wert, wenn, bool(haken)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(8, 5, 8, 5)
            lay.setSpacing(1)
            oben = QHBoxLayout()
            oben.setSpacing(6)
            self.zeichen = QLabel("")
            if symbol:
                _label_symbol(self.zeichen, symbol, "", FARBEN["text"], 15)
            self.titel = QLabel(titel)
            self.titel.setObjectName("zeile_titel")
            self.marke = QLabel("")
            if haken:
                if not _label_symbol(self.marke, "check", "", FARBEN["blau"],
                                     15):
                    self.titel.setText("✓ " + titel)
            oben.addWidget(self.zeichen)
            oben.addWidget(self.titel, 1)
            oben.addWidget(self.marke)
            self.satz = QLabel(satz)
            self.satz.setObjectName("neben")
            self.satz.setWordWrap(True)
            self.satz.setMaximumWidth(AUFKLAPPER_BREITE)
            lay.addLayout(oben)
            lay.addWidget(self.satz)

        def text(self):
            return self.titel.text()

        def click(self):
            self._wenn()

        def mouseReleaseEvent(self, e):               # noqa: N802
            if e.button() == Qt.MouseButton.LeftButton \
                    and self.rect().contains(e.position().toPoint()):
                self.click()

    class Aufklapper(QWidget):
        """Das Fenster eines Aufklappers (s. Kopf des Abschnitts). Drei
        Bereiche: `oben_fest` und `unten` bleiben (etwa der Regler der
        Denkstufe), `inhalt` wird bei jedem Oeffnen neu gefuellt."""

        def __init__(self, eltern):
            super().__init__(eltern, Qt.WindowType.Popup
                             | Qt.WindowType.FramelessWindowHint)
            # Ausserhalb der runden Karte durchsichtig (wie das Mini).
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            huelle = QVBoxLayout(self)
            huelle.setContentsMargins(0, 0, 0, 0)
            self.karte = QFrame()
            self.karte.setObjectName("aufklapper")
            huelle.addWidget(self.karte)
            lay = QVBoxLayout(self.karte)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.setSpacing(1)
            self.oben_fest = QVBoxLayout()
            self.inhalt = QVBoxLayout()
            self.inhalt.setSpacing(1)
            self.unten = QVBoxLayout()
            for teil in (self.oben_fest, self.inhalt, self.unten):
                lay.addLayout(teil)
            self.eintraege = []

        def leeren(self):
            self.eintraege = []
            while self.inhalt.count():
                w = self.inhalt.takeAt(0).widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()

        def _nach_klick(self, wenn):
            def ausfuehren():
                self.hide()
                wenn()
            return ausfuehren

        def eintrag(self, text, wenn, haken=False, an=True, tipp="",
                    wert=None, symbol=None):
            b = eintrag(text, tipp, symbol=symbol, haken=haken)
            b.wert = wert
            b.setEnabled(an)
            b.clicked.connect(self._nach_klick(wenn))
            self.inhalt.addWidget(b)
            self.eintraege.append(b)
            return b

        def zeile(self, titel, satz, wenn, haken=False, wert=None,
                  symbol=None):
            zl = Zeile(titel, satz, self._nach_klick(wenn), haken, wert,
                       symbol)
            self.inhalt.addWidget(zl)
            self.eintraege.append(zl)
            return zl

        def notiz(self, text):
            lb = QLabel(text)
            lb.setObjectName("neben")
            lb.setWordWrap(True)
            lb.setMaximumWidth(AUFKLAPPER_BREITE)
            self.inhalt.addWidget(lb)
            return lb

        def trenner(self):
            t = QFrame()
            t.setObjectName("trenner")
            t.setFixedHeight(1)
            self.inhalt.addWidget(t)
            return t

        def zeigen_an(self, knopf, nach_oben=True, rechts=False):
            """Neben `knopf` zeigen — nach oben (Leiste) oder nach unten
            (Kopf), am Bildschirmrand gehalten. Kehrt sofort zurueck."""
            self.adjustSize()
            g = knopf.mapToGlobal(QPoint(0, 0))
            x = g.x() + knopf.width() - self.width() if rechts else g.x()
            oben = g.y() - self.height() - 4
            unten = g.y() + knopf.height() + 4
            y = oben if nach_oben else unten
            schirm = QGuiApplication.screenAt(g) \
                or QGuiApplication.primaryScreen()
            if schirm is not None:
                r = schirm.availableGeometry()
                x = max(r.left(), min(x, r.right() - self.width()))
                if nach_oben and y < r.top():
                    y = unten
                elif not nach_oben and y + self.height() > r.bottom():
                    y = max(r.top(), oben)
            self.move(QPoint(x, y))
            self.show()
            self.raise_()

    class Punktregler(QWidget):
        """Die Denkstufe als Punktregler (K12, Vorbild Bild 2; ersetzt den
        `Stufenregler` mit Text daneben, dessen Breite mit dem Namen der
        Stufe schwankte): eine Spur ueber die VOLLE Breite, je Stufe ein
        Punkt, gefuellt bis zum Knopf. Klick auf einen Punkt oder Ziehen
        rastet auf die naechste Stufe; Pfeiltasten, Pos1/Ende. Schnittstelle
        eines Auswahlfelds (`currentData`, `findData`, `setCurrentIndex`,
        `activated`), damit Merken und Start unveraendert bleiben.
        `activated` kommt NUR von einer Wahl des Nutzers (Loslassen, Taste),
        `geaendert` bei jeder Aenderung (auch aus dem Code)."""
        activated = pyqtSignal(int)
        geaendert = pyqtSignal(int)
        HOEHE = 24
        KNOPF = 20
        PUNKT = 5
        SPUR = "#e9e9ee"

        def __init__(self, stufen):
            super().__init__()
            self._stufen = list(stufen)
            self._i = 0
            self._zieht = False
            self.setFixedHeight(self.HOEHE)
            self.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAccessibleName("Denkstufe")

        # -- Schnittstelle eines Auswahlfelds ----------------------------
        def count(self):
            return len(self._stufen)

        def itemData(self, i):                         # noqa: N802
            return self._stufen[i][1]

        def itemText(self, i):                         # noqa: N802
            return self._stufen[i][0]

        def currentIndex(self):                        # noqa: N802
            return self._i

        def currentData(self):                         # noqa: N802
            return self._stufen[self._i][1] if self._stufen else None

        def currentText(self):                         # noqa: N802
            return self._stufen[self._i][0] if self._stufen else ""

        def findData(self, wert):                      # noqa: N802
            for i, (_a, w) in enumerate(self._stufen):
                if w == wert:
                    return i
            return -1

        def setCurrentIndex(self, i):                  # noqa: N802
            if 0 <= i < len(self._stufen) and i != self._i:
                self._i = i
                self.update()
                self.geaendert.emit(i)

        # -- Geometrie ---------------------------------------------------
        def stelle(self, i):
            """x-Mitte des Punkts `i` (fuer Zeichnen, Klick und die Gates)."""
            r = self.HOEHE / 2.0
            n = len(self._stufen)
            if n <= 1:
                return self.width() / 2.0
            return r + i * (self.width() - 2 * r) / (n - 1)

        def _naechste(self, x):
            n = len(self._stufen)
            if not n:
                return 0
            return min(range(n), key=lambda i: abs(self.stelle(i) - x))

        def _waehlen(self, i, nutzer=True):
            if 0 <= i < len(self._stufen) and i != self._i:
                self._i = i
                self.update()
                self.geaendert.emit(i)
            if nutzer:
                self.activated.emit(self._i)

        # -- Zeichnen ----------------------------------------------------
        def paintEvent(self, _e):                      # noqa: N802
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                if not self.isEnabled():
                    p.setOpacity(0.5)
                h = float(self.HOEHE)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(self.SPUR))
                p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2,
                                  h / 2)
                x = self.stelle(self._i)
                p.setBrush(QColor(FARBEN["blau"]))
                p.drawRoundedRect(QRectF(0, 0, x + h / 2, h), h / 2, h / 2)
                for j in range(len(self._stufen)):
                    if j == self._i:
                        continue
                    p.setBrush(QColor("#ffffff" if j < self._i
                                      else FARBEN["neben"]))
                    r = self.PUNKT / 2.0
                    p.drawEllipse(QRectF(self.stelle(j) - r, h / 2 - r,
                                         2 * r, 2 * r))
                k = self.KNOPF / 2.0
                p.setBrush(QColor("#ffffff"))
                p.setPen(QPen(QColor(FARBEN["rahmen"]), 1))
                p.drawEllipse(QRectF(x - k, h / 2 - k, 2 * k, 2 * k))
                if self.hasFocus():
                    p.setPen(QPen(QColor(FARBEN["blau"]), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(x - k - 1, h / 2 - k - 1,
                                         2 * k + 2, 2 * k + 2))
            except Exception as exc:                   # noqa: BLE001
                _melden("Denkstufe zeichnen", exc)
            finally:
                p.end()

        # -- Bedienen (nie werfen: eine Ausnahme hier waere qFatal) -------
        def mousePressEvent(self, e):                  # noqa: N802
            try:
                if e.button() == Qt.MouseButton.LeftButton \
                        and self.isEnabled():
                    self._zieht = True
                    self._waehlen(self._naechste(e.position().x()),
                                  nutzer=False)
            except Exception as exc:                   # noqa: BLE001
                _melden("Denkstufe", exc)

        def mouseMoveEvent(self, e):                   # noqa: N802
            try:
                if self._zieht:
                    self._waehlen(self._naechste(e.position().x()),
                                  nutzer=False)
            except Exception as exc:                   # noqa: BLE001
                _melden("Denkstufe", exc)

        def mouseReleaseEvent(self, e):                # noqa: N802
            try:
                if self._zieht:
                    self._zieht = False
                    self._waehlen(self._naechste(e.position().x()))
            except Exception as exc:                   # noqa: BLE001
                _melden("Denkstufe", exc)

        def keyPressEvent(self, e):                    # noqa: N802
            try:
                n = len(self._stufen)
                ziel = {Qt.Key.Key_Left: self._i - 1,
                        Qt.Key.Key_Right: self._i + 1,
                        Qt.Key.Key_Home: 0,
                        Qt.Key.Key_End: n - 1}.get(e.key())
                if ziel is None or not self.isEnabled():
                    super().keyPressEvent(e)
                    return
                ziel = max(0, min(n - 1, ziel))
                if ziel != self._i:
                    self._waehlen(ziel)
            except Exception as exc:                   # noqa: BLE001
                _melden("Denkstufe", exc)

    class Kachel(QFrame):
        """Die Kachel oben im Popover: Stufe gross, Modell klein; ein Klick
        (oder Enter) oeffnet die Liste der Modelle."""

        def __init__(self, wenn):
            super().__init__()
            self._wenn = wenn
            self.setObjectName("stufe_kachel")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setAccessibleName("Modell wählen")

        def click(self):
            if self.isEnabled():
                self._wenn()

        def mouseReleaseEvent(self, e):                # noqa: N802
            try:
                if e.button() == Qt.MouseButton.LeftButton \
                        and self.rect().contains(e.position().toPoint()):
                    self.click()
            except Exception as exc:                   # noqa: BLE001
                _melden("Kachel", exc)

        def keyPressEvent(self, e):                    # noqa: N802
            try:
                if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                               Qt.Key.Key_Space):
                    self.click()
                    return
                super().keyPressEvent(e)
            except Exception as exc:                   # noqa: BLE001
                _melden("Kachel", exc)

    class Popover(QWidget):
        """Modell und Denkstufe (K12): eine Karte (Qt.Popup, gezeigt mit
        `show()` — keine verschachtelte Ereignisschleife), POPOVER_BREITE
        breit. Die Liste der Modelle (`liste`) ist ein Aufklapper MIT dem
        Popover als Eltern: Qt stapelt Popups, die Liste geht ueber ihm auf
        und zu, der Popover bleibt."""

        def __init__(self, eltern):
            super().__init__(eltern, Qt.WindowType.Popup
                             | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setObjectName("popover_fenster")
            huelle = QVBoxLayout(self)
            huelle.setContentsMargins(0, 0, 0, 0)
            self.karte = QFrame()
            self.karte.setObjectName("popover")
            huelle.addWidget(self.karte)
            self.lay = QVBoxLayout(self.karte)
            self.lay.setContentsMargins(12, 12, 12, 12)
            self.lay.setSpacing(10)
            self.setFixedWidth(POPOVER_BREITE)
            self.liste = None

        def zeigen_an(self, knopf, nach_oben=True, rechts=True):
            """Ueber `knopf` (nach oben), rechtsbuendig, am Bildschirmrand
            gehalten. Kehrt sofort zurueck."""
            self.adjustSize()
            g = knopf.mapToGlobal(QPoint(0, 0))
            x = g.x() + knopf.width() - self.width() if rechts else g.x()
            oben = g.y() - self.height() - 6
            unten = g.y() + knopf.height() + 6
            y = oben if nach_oben else unten
            schirm = QGuiApplication.screenAt(g) \
                or QGuiApplication.primaryScreen()
            if schirm is not None:
                r = schirm.availableGeometry()
                x = max(r.left(), min(x, r.right() - self.width()))
                if nach_oben and y < r.top():
                    y = unten
            self.move(QPoint(x, y))
            self.show()
            self.raise_()

        def hideEvent(self, e):                        # noqa: N802
            try:
                super().hideEvent(e)
                if self.liste is not None and self.liste.isVisible():
                    self.liste.hide()
            except Exception as exc:                   # noqa: BLE001
                _melden("Popover", exc)

    class Balken(QWidget):
        """Der Balken der Arbeitsanzeige (4 px, rund): 0..100 gefuellt oder
        "unbestimmt" (ein wandernder Abschnitt, bewegt im Takt des Docks —
        waehrend eines Auftrags steht er)."""

        def __init__(self):
            super().__init__()
            self._wert = None
            self._phase = 0
            self._farbe = FARBEN["blau"]
            self.setFixedHeight(4)

        def setzen(self, wert, farbe=None):
            if (wert, farbe or self._farbe) != (self._wert, self._farbe):
                self._wert = wert
                self._farbe = farbe or self._farbe
                self.update()

        def wert(self):
            return self._wert

        def schritt(self):
            self._phase = (self._phase + 1) % 20
            if self._wert == "unbestimmt":
                self.update()

        def paintEvent(self, _e):                      # noqa: N802
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(Qt.PenStyle.NoPen)
                b, h = float(self.width()), float(self.height())
                p.setBrush(QColor("#e9e9ee"))
                p.drawRoundedRect(QRectF(0, 0, b, h), 2, 2)
                p.setBrush(QColor(self._farbe))
                if self._wert == "unbestimmt":
                    teil = b * 0.3
                    x = (b + teil) * self._phase / 20.0 - teil
                    von, bis = max(0.0, x), min(b, x + teil)
                    if bis > von:
                        p.drawRoundedRect(QRectF(von, 0, bis - von, h), 2, 2)
                elif isinstance(self._wert, (int, float)):
                    p.drawRoundedRect(QRectF(0, 0, b * max(0, min(
                        100, self._wert)) / 100.0, h), 2, 2)
            except Exception as exc:                   # noqa: BLE001
                _melden("Balken zeichnen", exc)
            finally:
                p.end()

    class Kontextring(QWidget):
        """Wie voll das Gedaechtnis des Chats ist (Wunsch 2026-09-27). Nimmt
        den Text von `_kontext_text` ("65 % voll") wie ein Label; der Anteil
        kommt aus der Zahl darin. Seit der Gegenpruefung Laien-Sicht K12
        ein FUELLSTAND (kurzer Balken + "65 %") statt eines Rings — der
        Ring neben "Senden" las sich wie ein Ladekreis; gezeigt wird er erst
        ab KONTEXT_AB % (`_kontext_zeigen`)."""

        def __init__(self):
            super().__init__()
            self._text, self._anteil = "", None
            self.setAccessibleName("Gedächtnis des Chats")
            breite = (KONTEXT_BALKEN + 6
                      + self.fontMetrics().horizontalAdvance("100 %") + 2)
            self.setFixedSize(breite, 22)

        def setText(self, text):                       # noqa: N802
            self._text = text or ""
            treffer = _re.search(r"(\d+)\s*%", self._text)
            self._anteil = (min(100, int(treffer.group(1))) / 100.0
                            if treffer else None)
            self.update()

        def text(self):
            return self._text

        def anteil(self):
            return self._anteil

        def paintEvent(self, _e):                      # noqa: N802
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            mitte = self.height() / 2.0
            r = QRectF(1.0, mitte - 3.0, float(KONTEXT_BALKEN), 6.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(FARBEN["rahmen"]))
            p.drawRoundedRect(r, 3.0, 3.0)
            farbe = FARBEN["neben"]
            if self._anteil:
                farbe = (FARBEN["blau"] if self._anteil < 0.8 else
                         FARBEN["orange"] if self._anteil < 0.95 else
                         FARBEN["rot"])
                voll = QRectF(r.left(), r.top(),
                              max(6.0, r.width() * self._anteil), r.height())
                p.setBrush(QColor(farbe))
                p.drawRoundedRect(voll, 3.0, 3.0)
                p.setPen(QColor(farbe if self._anteil >= 0.8
                                else FARBEN["neben"]))
                p.drawText(QRectF(r.right() + 6, 0, self.width()
                                  - r.right() - 6, self.height()),
                           int(Qt.AlignmentFlag.AlignVCenter
                               | Qt.AlignmentFlag.AlignLeft),
                           "%d %%" % int(round(self._anteil * 100)))
            p.end()

    class Klickzeile(QLabel):
        """Eine Zeile, die aussieht wie Text und auf einen Klick reagiert
        (Kopf einer Schrittgruppe). Bricht um, statt abzuschneiden."""

        def __init__(self, wenn):
            super().__init__("")
            self._wenn = wenn
            self.setWordWrap(True)
            # Der Kopf nennt Beschreibungen der KI: nie als Rich Text lesen.
            self.setTextFormat(Qt.TextFormat.PlainText)
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        def click(self):
            self._wenn()

        def mouseReleaseEvent(self, e):               # noqa: N802
            if e.button() == Qt.MouseButton.LeftButton \
                    and self.rect().contains(e.position().toPoint()):
                self.click()

    def _ki_marke():
        """Das Zeichen vor jeder Antwort der KI: seit K9 das Logo des
        Plugins (klein, scharf), ohne Logo das Symbol, ohne beides ✦."""
        lb = QLabel("")
        lb.setObjectName("ki_marke")
        pm = _logo_pixmap(20)
        if pm is not None:
            lb.setPixmap(pm)
            lb.setFixedSize(20, 20)
            lb.setProperty("symbol", "logo")
        else:
            _label_symbol(lb, "sparkles", "✦", FARBEN["blau"], 16)
        return lb

    def _textlabel(name, waehlbar=True):
        lb = QLabel("")
        lb.setObjectName(name)
        lb.setWordWrap(True)
        lb.setTextFormat(Qt.TextFormat.PlainText)
        if waehlbar:
            lb.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
        return lb

    class Blase(QWidget):
        """Ein Eintrag des Verlaufs: `ich` rechts in eigener Blase, `ki` mit
        ✦ in eigener Blase, `zeit` als Linie in der Mitte, `notiz` grau."""

        def __init__(self, art):
            super().__init__()
            self.art = art
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            if art == "ich":
                self.text = _textlabel("blase_ich")
                lay.addStretch(1)
                lay.addWidget(self.text)
            elif art == "ki":
                self.marke = _ki_marke()
                self.text = _textlabel("blase_ki")
                lay.addWidget(self.marke, 0, Qt.AlignmentFlag.AlignTop)
                lay.addWidget(self.text, 1)
            elif art == "tippt":
                # "…" an der Stelle der naechsten Antwort, die Punkte laufen
                # (eigener Zeitgeber, nur solange sichtbar).
                self.marke = _ki_marke()
                self.text = _textlabel("blase_tippt", False)
                self.text.setText("···")     # ein Standbild liest sich als "…"
                lay.addWidget(self.marke, 0, Qt.AlignmentFlag.AlignTop)
                lay.addWidget(self.text)
                lay.addStretch()        # "…" links, Rest frei
                self._schritt = 2
                self._uhr = QTimer(self)
                self._uhr.setInterval(400)
                self._uhr.timeout.connect(self._weiter)
            elif art == "zeit":
                self.text = _textlabel("zeitlinie", False)
                self.text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                lay.addWidget(self.text, 1)
            else:
                self.text = _textlabel("neben")
                lay.addWidget(self.text, 1)
            self._voll = ""

        def _weiter(self):
            self._schritt = (self._schritt + 1) % 3
            self.text.setText("·" * (self._schritt + 1))

        def showEvent(self, e):                        # noqa: N802
            super().showEvent(e)
            if self.art == "tippt":
                self._uhr.start()

        def hideEvent(self, e):                        # noqa: N802
            super().hideEvent(e)
            if self.art == "tippt":
                self._uhr.stop()

        def setzen(self, b):
            if self.art == "tippt":
                self.setToolTip(b.get("text") or "")
                self._voll = "…"
                return
            # Der Schluss des Zugs ("fertig · 18 Token") als Tooltip der
            # Antwort (Feinschliff 2026-09-28: keine Zeile "— fertig").
            if self.art == "ki":
                fuss = b.get("fuss") or ""
                if self.text.toolTip() != fuss:
                    self.text.setToolTip(fuss)
            text = b.get("text") or ""
            if b.get("anhaenge"):
                text = (text + "\n" if text else "") + "%s: %s" % (
                    "Anhang" if len(b["anhaenge"]) == 1 else "Anhänge",
                    ", ".join(b["anhaenge"]))
            if text != self.text.text():
                self.text.setText(text)
                self._breite()
            self._voll = ("Du:  %s" % b.get("text", "")
                          + ("  · Anhänge: %s" % ", ".join(b["anhaenge"])
                             if b.get("anhaenge") else "")) \
                if self.art == "ich" else text

        def volltext(self):
            return self._voll

        def _breite(self):
            """Die eigene Nachricht: so breit wie ihr Text, hoechstens gut
            vier Fuenftel — sonst stuende sie nicht mehr sichtbar rechts.
            Ohne Mindestbreite bricht ein QLabel schon nach wenigen Worten
            um (sein Wunsch ist schmal, gemessen im Bild zu K5)."""
            if self.art != "ich" or self.width() <= 0:
                return
            breite = max(80, int(self.width() * 0.82))
            fm = self.text.fontMetrics()
            natur = max([fm.horizontalAdvance(z)
                         for z in self.text.text().split("\n")] or [0]) + 24
            if self.text.maximumWidth() != breite:
                self.text.setMaximumWidth(breite)
            if self.text.minimumWidth() != min(natur, breite):
                self.text.setMinimumWidth(min(natur, breite))

        def resizeEvent(self, e):                      # noqa: N802
            super().resizeEvent(e)
            self._breite()

    class Schritte(QWidget):
        """Eine Gruppe von Werkzeug-Schritten als EINE graue Zeile
        ("▸ 6 Schritte in Cadwork"); ein Klick klappt die Schritte auf. Der
        technische Name steht nur im Tooltip."""

        def __init__(self, verlauf):
            super().__init__()
            self.art = "schritte"
            self._verlauf = verlauf
            self.b = None
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)
            self.kopf = Klickzeile(lambda: _sicher(
                self.umschalten, "Schritte aufklappen"))
            self.kopf.setObjectName("schritte_kopf")
            # Der Winkel davor als Strich-Symbol (K9, statt "▸"/"▾"); auch
            # er klappt auf.
            self.pfeil = Klickzeile(lambda: _sicher(
                self.umschalten, "Schritte aufklappen"))
            self.pfeil.setObjectName("schritte_pfeil")
            self.pfeil.setWordWrap(False)
            self._pfeil_zweck = None
            kopfreihe = QHBoxLayout()
            kopfreihe.setContentsMargins(0, 0, 0, 0)
            kopfreihe.setSpacing(2)
            kopfreihe.addWidget(self.pfeil, 0, Qt.AlignmentFlag.AlignTop)
            kopfreihe.addWidget(self.kopf, 1)
            lay.addLayout(kopfreihe)
            self.teil = QWidget()
            self.zeilen_lay = QVBoxLayout(self.teil)
            self.zeilen_lay.setContentsMargins(0, 0, 0, 0)
            self.zeilen_lay.setSpacing(0)
            self.teil.hide()
            lay.addWidget(self.teil)
            self._zeilen = []
            self._symbole = []

        def offen(self):
            return self.b is not None \
                and self.b["schluessel"] in self._verlauf.offen

        def umschalten(self):
            if self.b is None:
                return
            if self.offen():
                self._verlauf.offen.discard(self.b["schluessel"])
            else:
                self._verlauf.offen.add(self.b["schluessel"])
            self.setzen(self.b)

        def setzen(self, b):
            self.b = b
            offen = self.offen()
            kopf = b["kopf"]
            if kopf != self.kopf.text():
                self.kopf.setText(kopf)
            zweck = ("auf" if offen else "zu", bool(b.get("warnung")))
            if zweck != self._pfeil_zweck:
                self._pfeil_zweck = zweck
                lucide, ersatz = SYMBOLE[zweck[0]]
                _label_symbol(self.pfeil, lucide, ersatz,
                              FARBEN["orange"] if zweck[1]
                              else FARBEN["neben"], 14)
            self.kopf.setToolTip("Klicken zeigt die einzelnen Schritte."
                                 if not offen else
                                 "Klicken klappt die Schritte zu.")
            symbole = list(b.get("symbole") or [None] * len(b["zeilen"]))
            if list(self._zeilen) != list(b["zeilen"]) \
                    or self._symbole != symbole:
                while self.zeilen_lay.count():
                    alt = self.zeilen_lay.takeAt(0).widget()
                    if alt is not None:
                        alt.hide()
                        alt.deleteLater()
                for (text, tipp), symbol in zip(b["zeilen"], symbole):
                    reihe = QWidget()
                    rl = QHBoxLayout(reihe)
                    rl.setContentsMargins(18, 1, 0, 1)
                    rl.setSpacing(6)
                    zeichen = QLabel("")
                    zeichen.setObjectName("schritt_symbol")
                    if symbol:
                        _label_symbol(zeichen, symbol, "", FARBEN["neben"],
                                      13)
                    lb = _textlabel("schritt", False)
                    lb.setText(text)
                    lb.setToolTip(_tipp_klartext(tipp))
                    rl.addWidget(zeichen, 0, Qt.AlignmentFlag.AlignTop)
                    rl.addWidget(lb, 1)
                    self.zeilen_lay.addWidget(reihe)
                self._zeilen = list(b["zeilen"])
                self._symbole = symbole
            if self.teil.isHidden() == offen:
                self.teil.setVisible(offen)

        def zeilen(self):
            return [z for z, _t in self._zeilen]

        def volltext(self):
            return self.b["kopf"] if self.b else ""

    class Verlauf(QScrollArea):
        """Der Chatverlauf (K5, Wunsch 2026-09-27): Blasen statt
        Listenzeilen, Werkzeuge als eine aufklappbare Zeile, Zeitlinien.

        Folgt dem Neuesten, solange der Nutzer unten steht; hat er
        hochgerollt, bleibt die Stelle und "↓ Neu" erscheint. `setzen`
        zeichnet nur, was sich geaendert hat (Bloecke mit gleichem
        `schluessel` an Ort und Stelle), nie alles neu — sonst sprang die
        Stelle unter den Fingern weg und aufgeklappte Gruppen gingen zu."""

        def __init__(self):
            super().__init__()
            self.setObjectName("verlauf")
            self.setWidgetResizable(True)
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            innen = QWidget()
            innen.setObjectName("rollinhalt")
            self.lay = QVBoxLayout(innen)
            self.lay.setContentsMargins(8, 8, 8, 8)
            self.lay.setSpacing(8)
            self.lay.addStretch(1)
            self.setWidget(innen)
            self.teile = []
            self.offen = set()
            self.folgen = True
            self.neu = QPushButton("Neu", self)
            self.neu.setObjectName("neu_knopf")
            _knopf_symbol(self.neu, "neu_unten", text="Neu", farbe="#ffffff",
                          groesse=13)
            self.neu.setToolTip("Zur neuesten Nachricht")
            self.neu.setCursor(Qt.CursorShape.PointingHandCursor)
            self.neu.hide()
            self.neu.clicked.connect(self.ans_ende)
            leiste = self.verticalScrollBar()
            leiste.valueChanged.connect(self._gerollt)
            leiste.rangeChanged.connect(self._bereich)

        # -- Rollen ----------------------------------------------------------
        def _gerollt(self, wert):
            self.folgen = wert >= self.verticalScrollBar().maximum() - 4
            if self.folgen and not self.neu.isHidden():
                self.neu.hide()

        def _bereich(self, _von, bis):
            if self.folgen:
                self.verticalScrollBar().setValue(bis)

        def ans_ende(self):
            self.folgen = True
            self.neu.hide()
            leiste = self.verticalScrollBar()
            leiste.setValue(leiste.maximum())

        def _neu_platzieren(self):
            self.neu.adjustSize()
            self.neu.move(max(0, (self.width() - self.neu.width()) // 2),
                          max(0, self.height() - self.neu.height() - 10))
            self.neu.raise_()

        def resizeEvent(self, e):                      # noqa: N802
            super().resizeEvent(e)
            self._neu_platzieren()

        # -- Inhalt ----------------------------------------------------------
        def leeren(self):
            for _b, wdg in self.teile:
                self.lay.removeWidget(wdg)
                wdg.hide()
                wdg.deleteLater()
            self.teile = []
            self.offen = set()
            self.folgen = True
            self.neu.hide()

        def _bauen(self, b):
            return Schritte(self) if b["art"] == "schritte" \
                else Blase(b["art"])

        def setzen(self, bloecke):
            """Die Bloecke zeigen -> True, wenn Neues dazukam."""
            alt, i, neu = self.teile, 0, False
            while i < len(alt) and i < len(bloecke) \
                    and alt[i][0]["schluessel"] == bloecke[i]["schluessel"] \
                    and alt[i][0]["art"] == bloecke[i]["art"]:
                if alt[i][0] != bloecke[i]:
                    alt[i][1].setzen(bloecke[i])
                    neu = neu or bloecke[i]["art"] not in ("zeit", "tippt")
                    alt[i] = (bloecke[i], alt[i][1])
                i += 1
            for _b, wdg in alt[i:]:
                self.lay.removeWidget(wdg)
                wdg.hide()
                wdg.deleteLater()
            del alt[i:]
            for b in bloecke[i:]:
                wdg = self._bauen(b)
                wdg.setzen(b)
                self.lay.insertWidget(len(alt), wdg)
                alt.append((b, wdg))
                neu = neu or b["art"] != "tippt"
            if neu and not self.folgen:
                self._neu_platzieren()
                self.neu.show()
            return neu

        # -- Fuer die Gates und den Rest des Docks ---------------------------
        def count(self):
            """Wie viele Eintraege (ohne Zeitlinien und ohne das "…")."""
            return sum(1 for b, _w in self.teile
                       if b["art"] not in ("zeit", "tippt"))

        def texte(self, mit_zeit=False):
            return [wdg.volltext() for b, wdg in self.teile
                    if mit_zeit or b["art"] not in ("zeit", "tippt")]

        def widgets(self, art=None):
            return [wdg for b, wdg in self.teile
                    if art is None or b["art"] == art]

    ns = types.SimpleNamespace(eintrag=eintrag, Zeile=Zeile,
                               KnappKnopf=KnappKnopf, Verlauf=Verlauf,
                               Blase=Blase, Schritte=Schritte,
                               Aufklapper=Aufklapper,
                               Punktregler=Punktregler,
                               Kachel=Kachel, Popover=Popover,
                               Balken=Balken,
                               Kontextring=Kontextring)
    _KLASSEN["ns"] = ns
    return ns


def _aufklapper_zeigen(z, auf, knopf, nach_oben=True, rechts=False):
    """Einen Aufklapper zeigen — hoechstens einer ist offen."""
    alt = z.get("aufklapper")
    if alt is not None and alt is not auf:
        try:
            alt.hide()
        except RuntimeError:
            pass
    z["aufklapper"] = auf
    auf.zeigen_an(knopf, nach_oben, rechts)
    return auf


def _modus_anzeige(modus, C=None):
    """"fragen" -> "Fragen" (seit K9 ohne Emoji; das Symbol steht daneben,
    `MODUS_SYMBOLE`)."""
    C = C or _chat_modul()
    for wert, anzeige, _zeichen, _satz in C.MODI:
        if wert == modus:
            return anzeige
    return modus or "?"


def _modus_aufklappen(z):
    """Der Modus-Aufklapper: je Modus Titel und der Satz aus dem VERHALTEN
    (`_modus_hinweis`), der wirksame mit Haken. Waehlbar jederzeit, auch
    mitten im Chat: gilt ab dem naechsten Werkzeugaufruf."""
    w = z["w"]
    auf = w["chat_modus_auf"]
    C = _chat_modul()
    auf.leeren()
    jetzt = _modus_wirksam(z, C)
    auf.notiz("Wie viel die KI ohne Frage darf — gilt ab dem nächsten "
              "Schritt, auch mitten im Chat.")
    for wert, _anzeige, _zeichen, _satz in C.MODI:
        auf.zeile(_modus_anzeige(wert, C), _modus_hinweis(wert, C),
                  lambda wert=wert: _sicher(lambda: _modus_waehlen(z, wert),
                                            "Modus wählen"),
                  haken=(wert == jetzt), wert=wert,
                  symbol=MODUS_SYMBOLE.get(wert))
    return _aufklapper_zeigen(z, auf, w["chat_modus"], nach_oben=True)


# --- Modell und Denkstufe: der Popover (K12, Vorbild Bild 2) -----------------
# Rueckmeldung 2026-10-07 zu Bild 3 (Liste der Modelle, darunter die
# Denkstufe als Regler mit Text daneben): "wenn Ultracode steht, wird der
# Schieberegler kleiner, das ist gar nicht intuitiv — die Modelle wie ein
# Popup darueber wie bei ChatGPT im ersten Bild und der Effort-Schieberegler
# darunter". Jetzt: oben mittig eine Kachel mit der Stufe gross und dem
# Modell klein darunter (Klick -> Liste der Modelle UEBER dem Popover),
# darunter der Punktregler ueber die volle Breite, KEIN Text daneben —
# seine Breite ist fuer jede Stufe gleich.

#: Breite des Popovers.
POPOVER_BREITE = 300
#: Kurzname je Denkstufe (Wert ans CLI aus omcad_a_chat.EFFORT_STUFEN, der
#: dort gezeigte Name bleibt fuer die Gates). test_a_prototyp P21 prueft,
#: dass diese Tabelle genau C.EFFORT_STUFEN deckt.
STUFE_KURZ = {"low": "Niedrig", "medium": "Mittel", "high": "Hoch",
              "xhigh": "Sehr hoch", "max": "Maximal",
              "ultracode": "Ultracode"}
#: Ein Satz je Stufe fuer den Tooltip (der Zusatz "Mehr-Agenten" steht nur
#: dort).
STUFE_SATZ = {"ultracode": "Sehr hoch und dazu ständige Mehr-Agenten-Arbeit"}
STUFE_NOTIZ = "Gilt ab dem nächsten Chat"


def _stufe_kurz(wert, C=None):
    """"xhigh" -> "Sehr hoch"; Unbekanntes wie es ist."""
    return STUFE_KURZ.get(wert, wert or "")


def _popover_bauen(z, eltern, stufe):
    """Der Popover (gebaut EINMAL mit dem Chat, gefuellt bei jedem Oeffnen,
    `_popover_fuellen`) und die Liste der Modelle darueber. `stufe`: der
    Punktregler (Schnittstelle eines Auswahlfelds, `chat_stufe`)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout
    K = _qt_klassen()
    pop = K.Popover(eltern)
    oben = QHBoxLayout()
    oben.setSpacing(6)
    hirn = QLabel("")
    _label_symbol(hirn, "brain", "", FARBEN["neben"], 16)
    hirn.setFixedWidth(22)
    kachel = K.Kachel(lambda: _sicher(lambda: _modell_liste_zeigen(z),
                                      "Modellliste"))
    kl = QVBoxLayout(kachel)
    kl.setContentsMargins(14, 6, 14, 6)
    kl.setSpacing(1)
    gross = QLabel("")
    gross.setObjectName("stufe_gross")
    gross.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    zeile = QHBoxLayout()
    zeile.setSpacing(2)
    modell = QLabel("")
    modell.setObjectName("modell_zeile")
    winkel = QLabel("")
    _label_symbol(winkel, "chevron-right", "›", FARBEN["neben"], 12)
    zeile.addStretch(1)
    zeile.addWidget(modell)
    zeile.addWidget(winkel)
    zeile.addStretch(1)
    kl.addWidget(gross)
    kl.addLayout(zeile)
    zurueck = QPushButton("")
    zurueck.setObjectName("flach")
    zurueck.setFixedSize(26, 26)
    zurueck.setAccessibleName("Auf Vorgabe zurück")
    zurueck.setToolTip("Denkstufe auf die Vorgabe zurück")
    _knopf_symbol(zurueck, "zurueck_vorgabe", farbe=FARBEN["neben"],
                  groesse=15)
    oben.addWidget(hirn, 0, Qt.AlignmentFlag.AlignTop)
    oben.addStretch(1)
    oben.addWidget(kachel)
    oben.addStretch(1)
    oben.addWidget(zurueck, 0, Qt.AlignmentFlag.AlignTop)
    pop.lay.addLayout(oben)
    pop.lay.addWidget(stufe)
    notiz = QLabel(STUFE_NOTIZ)
    notiz.setObjectName("neben")
    notiz.hide()
    pop.lay.addWidget(notiz)
    liste = K.Aufklapper(pop)
    liste.setFixedWidth(POPOVER_BREITE)
    pop.liste = liste
    zurueck.clicked.connect(lambda: _sicher(lambda: _stufe_zurueck(z),
                                            "Denkstufe zurück"))
    stufe.geaendert.connect(lambda _i: _sicher(lambda: _popover_kachel(z),
                                               "Denkstufe zeigen"))
    z["w"].update(chat_modell_auf=pop, stufe_kachel=kachel,
                  stufe_gross=gross, modell_zeile=modell, stufe_winkel=winkel,
                  stufe_zurueck=zurueck, stufe_notiz=notiz, stufe_hirn=hirn,
                  stufe_regler=stufe, modell_liste_auf=liste)
    return pop


#: Was ohne gewaehltes Modell dasteht — gross im Popover und auf dem Knopf
#: unter der Eingabe (Gegenpruefung Laien-Sicht K12: "Vorgabe von Codex"
#: war Fachsprache; der Tooltip sagt, wer waehlt).
MODELL_AUTOMATISCH = "Automatisch"
MODELL_AUTOMATISCH_KNOPF = "Modell: automatisch"


def _modell_oder_vorgabe(name, a, knopf=False):
    """Was dasteht, wenn kein Modell gewaehlt ist: gross im Popover
    "Automatisch", auf dem Knopf "Modell: automatisch" — statt "Modell
    wählen" (Gegenpruefung K12: gross "Modell wählen", klein "Modell
    wechseln" — zweimal dasselbe Verb). `a`: der Anbieter (`anbieter()`),
    hier nicht mehr gebraucht (frueher "Vorgabe von Codex")."""
    _ = a
    name = (name or "").strip()
    if name and name != MODELLE_EINTRAG:
        return name
    return MODELL_AUTOMATISCH_KNOPF if knopf else MODELL_AUTOMATISCH


def _popover_kachel(z):
    """Die Kachel des Popovers: bei Claude Code die Stufe gross und das
    Modell klein, sonst das Modell gross und "Modell wechseln" klein. Lange
    Namen elidiert, der volle im Tooltip."""
    from PyQt6.QtCore import Qt
    w = z["w"]
    gross, klein = w.get("stufe_gross"), w.get("modell_zeile")
    if gross is None:
        return None
    try:
        a = _gewaehlter_anbieter(z)
    except Exception:                                  # noqa: BLE001
        a = {"art": None, "name": ""}
    cli = a.get("art") == "cli"
    feld = w["chat_modell"]
    name = _modell_oder_vorgabe(feld.currentText(), a)
    stufe = w["chat_stufe"]
    if cli:
        g = _stufe_kurz(stufe.currentData())
        k = name
        tipp = "%s — %s" % (stufe.currentText(), STUFE_SATZ.get(
            stufe.currentData(), "wie gründlich die KI nachdenkt"))
    else:
        g, k, tipp = name, "Modell wechseln", name
        if name == MODELL_AUTOMATISCH:
            kurz = str(a.get("name") or "").split(" (")[0].strip()
            tipp = "%s wählt das Modell selbst" % (kurz or "Der Anbieter")
    breite = POPOVER_BREITE - 2 * 12 - 2 * 26 - 2 * 14 - 16
    g_kurz = gross.fontMetrics().elidedText(g, Qt.TextElideMode.ElideRight,
                                            breite)
    if gross.text() != g_kurz:
        gross.setText(g_kurz)
    k_kurz = klein.fontMetrics().elidedText(k, Qt.TextElideMode.ElideRight,
                                            breite - 16)
    if klein.text() != k_kurz:
        klein.setText(k_kurz)
    w["stufe_kachel"].setToolTip(tipp + "\nKlick: Modell wählen")
    return g


def _popover_fuellen(z):
    """Vor jedem Oeffnen: Kachel, Regler (nur Claude Code), ↺ (nur Claude
    Code und nicht schon die Vorgabe), mitten im Chat gesperrt mit der Notiz
    "Gilt ab dem nächsten Chat" (die einzige Stelle dafuer)."""
    from PyQt6.QtWidgets import QGraphicsOpacityEffect
    w = z["w"]
    C = _chat_modul()
    try:
        cli = _gewaehlter_anbieter(z)["art"] == "cli"
    except Exception:                                  # noqa: BLE001
        cli = False
    an = bool((z.get("chat") or {}).get("an"))
    stufe = w["chat_stufe"]
    stufe.setVisible(cli)
    stufe.setEnabled(not an)
    w["stufe_hirn"].setVisible(cli)
    w["stufe_zurueck"].setVisible(cli)
    w["stufe_zurueck"].setEnabled(
        not an and stufe.currentData() != C.EFFORT_VORGABE)
    kachel = w["stufe_kachel"]
    kachel.setEnabled(not an)
    effekt = kachel.graphicsEffect()
    if an and effekt is None:
        effekt = QGraphicsOpacityEffect(kachel)
        effekt.setOpacity(0.5)
        kachel.setGraphicsEffect(effekt)
    elif not an and effekt is not None:
        kachel.setGraphicsEffect(None)
    w["stufe_notiz"].setVisible(an)
    _popover_kachel(z)
    # Erst die Layouts neu rechnen, dann die Groesse: sonst behielt der
    # Popover nach dem Wechsel Claude Code -> Codex die Hoehe MIT Regler und
    # gab sie der Kachel (Luecke unter dem Modellnamen, Sichtung K12).
    pop = w["chat_modell_auf"]
    for lay in (pop.lay, pop.layout()):
        if lay is not None:
            lay.invalidate()
            lay.activate()
    pop.resize(pop.width(), pop.sizeHint().height())
    pop.adjustSize()


def _modell_aufklappen(z):
    """Der Knopf "Opus 5.5 · Hoch ⌄" unter der Eingabe: der Popover nach
    OBEN, rechtsbuendig zum Knopf. Nie `exec()`."""
    w = z["w"]
    pop = w["chat_modell_auf"]
    _popover_fuellen(z)
    return _aufklapper_zeigen(z, pop, w["chat_modell_knopf"], nach_oben=True,
                              rechts=True)


def _modell_liste_zeigen(z):
    """Die Liste der Modelle UEBER dem Popover (gleiche Breite, Unterkante 6
    px ueber seiner Oberkante; passt es oben nicht, rechts daneben, nie den
    Popover verdeckend). Ein Klick auf die Kachel bei offener Liste
    schliesst sie. Die Wahl schliesst nur die Liste — der Popover bleibt
    offen und zeigt das neue Modell."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QGuiApplication
    w = z["w"]
    pop, liste = w["chat_modell_auf"], w["modell_liste_auf"]
    if liste.isVisible():
        liste.hide()
        return None
    if not w["stufe_kachel"].isEnabled():
        return None
    liste.leeren()
    a = _gewaehlter_anbieter(z)
    cli = a["art"] == "cli"
    feld = w["chat_modell"]
    jetzt = _modellwahl(feld)
    liste.notiz("Modell · %s" % a["name"])
    for i in range(feld.count()):
        wert = feld.itemData(i)
        if wert == MODELLE_ABFRAGEN:
            continue
        liste.eintrag(feld.itemText(i),
                      lambda i=i: _sicher(lambda: _modell_aus_liste(z, i),
                                          "Modell wählen"),
                      haken=(wert == jetzt), wert=wert)
    if not cli:
        liste.eintrag("Modelle beim Anbieter abfragen",
                      lambda: _sicher(lambda: _modelle_abfragen(z),
                                      "Modelle abfragen"),
                      symbol="refresh-cw")
    liste.eintrag("Anderes Modell …",
                  lambda: _sicher(lambda: _anderes_modell(z),
                                  "Modell wählen"),
                  tipp="Einen eigenen Modellnamen eintippen "
                       "(Einstellungen)")
    liste.adjustSize()
    g = pop.mapToGlobal(QPoint(0, 0))
    x, y = g.x(), g.y() - liste.height() - 6
    schirm = QGuiApplication.screenAt(g) or QGuiApplication.primaryScreen()
    if schirm is not None and y < schirm.availableGeometry().top():
        r = schirm.availableGeometry()
        x = g.x() + pop.width() + 6
        if x + liste.width() > r.left() + r.width():
            x = g.x() - liste.width() - 6
        y = max(r.top(), g.y())
    liste.move(QPoint(x, y))
    liste.show()
    liste.raise_()
    return liste


def _modell_aus_liste(z, i):
    """Ein Modell aus der Liste: wie eine Wahl im Feld (merkt bei Claude
    Code in chat.json `modell.<id>`); die Liste schliesst, der Popover
    bleibt und zeigt es."""
    feld = z["w"]["chat_modell"]
    feld.setCurrentIndex(i)
    _modell_gewaehlt(z, i)
    _modell_knopf_zeigen(z)
    _popover_kachel(z)
    pop = z["w"].get("chat_modell_auf")
    if pop is not None and not pop.isVisible() \
            and z.get("aufklapper") is pop:
        # Qt schliesst mit dem Klick in die Liste den Popover darunter
        # nicht — sollte es doch geschehen sein, wieder auf.
        _modell_aufklappen(z)
    return feld.currentText()


def _stufe_zurueck(z):
    """↺: die Denkstufe auf die Vorgabe (C.EFFORT_VORGABE) — eine Wahl des
    Nutzers wie am Regler (gemerkt)."""
    C = _chat_modul()
    stufe = z["w"]["chat_stufe"]
    i = stufe.findData(C.EFFORT_VORGABE)
    if i < 0 or stufe.currentIndex() == i:
        return None
    stufe.setCurrentIndex(i)
    stufe.activated.emit(i)
    _popover_fuellen(z)
    return C.EFFORT_VORGABE


def _anderes_modell(z):
    """"Anderes Modell …": die Einstellungsseite, das Modellfeld bereit."""
    for teil in (z["w"].get("modell_liste_auf"),
                 z["w"].get("chat_modell_auf")):
        if teil is not None:
            teil.hide()
    _einstellungen_zeigen(z, True)
    feld = z["w"]["chat_modell"]
    feld.setFocus()
    if feld.lineEdit() is not None:
        feld.lineEdit().selectAll()
    try:
        z["w"]["einst_seite"].ensureWidgetVisible(feld)
    except Exception:                                  # noqa: BLE001
        pass


def _modell_knopf_zeigen(z):
    """Im Takt: der Text des Knopfs unter der Eingabe ("Opus 5.5 · Hoch",
    die Stufe gross geschrieben, ohne Zusatz in Klammern). Billig, nur bei
    Aenderung."""
    w = z["w"]
    knopf = w.get("chat_modell_knopf")
    if knopf is None:
        return
    try:
        a = _gewaehlter_anbieter(z)
    except Exception:                                  # noqa: BLE001
        a = {}
    cli = a.get("art") == "cli"
    feld = w["chat_modell"]
    name = _modell_oder_vorgabe(feld.currentText(), a, knopf=True)
    teile = [name]
    if cli:
        teile.append(_stufe_kurz(w["chat_stufe"].currentData()))
    text = " · ".join(teile)
    if knopf.volltext() != text:
        knopf.setText(text)
        knopf.setToolTip("%s — %s wirkt beim nächsten Start"
                         % (text, "Modell und Denkstufe" if cli
                            else "Modell"))


def _ordner_aufklappen(z):
    """Das Ordner-Menue (nach UNTEN, der Knopf steht oben): der Ordner, der
    gilt, die zuletzt benutzten, "Ordner wählen …", "Wahl entfernen"."""
    w = z["w"]
    auf = w["chat_ordner_auf"]
    auf.leeren()
    _ordner_zeigen(z)
    wirksam = arbeitsordner(_ordner_wahl(z))
    zuletzt = [p for p in z.get("ordner_zuletzt") or ()
               if not wirksam or os.path.normcase(p)
               != os.path.normcase(wirksam)]
    if (z.get("chat") or {}).get("an"):
        auf.notiz("Ein anderer Ordner gilt ab dem nächsten Chat.")
    if zuletzt:
        auf.trenner()
        auf.notiz("Zuletzt benutzt")
        for pfad in zuletzt[:ORDNER_ZULETZT_MAX]:
            auf.eintrag((os.path.basename(pfad.rstrip("\\/")) or pfad),
                        lambda pfad=pfad: _sicher(
                            lambda: _ordner_gewaehlt(z, pfad),
                            "Arbeitsordner wählen"),
                        tipp=pfad, wert=pfad, symbol="folder")
    auf.trenner()
    return _aufklapper_zeigen(z, auf, w["chat_ordner"], nach_oben=False)


# --- Anhaenge (K4, Wunsch 2026-09-27) -----------------------------------------
# "+" -> "Datei oder Foto hinzufügen" (Qts eigener Dateidialog, `open()`),
# dazu Einfuegen (Strg+V) und Ziehen-und-Ablegen in die Eingabe. Gelesen,
# geprueft und kodiert wird im NEBENTHREAD (eine grosse Datei oder ein
# grosses Bildschirmfoto haelt den Qt-Takt nie an); der Takt holt nur ab
# (`_anhaenge_takt`). Geschickt wird beim Senden (`_anhang_nutzlast`):
# Bilder als base64 (Claude Code: Bild-Block, gemessen; Schleife:
# `image_url`; Codex: `image`), Textdateien mit Inhalt, andere Dateien mit
# ihrem Pfad (nur Claude Code, es liest sie selbst — liegt der Pfad
# ausserhalb des Ordners, gilt der Modus wie bei jedem Lesen).

#: Hoechstens so viele Anhaenge je Nachricht.
ANHANG_MAX = 10
#: Ein Bild hoechstens so gross (roh): base64 macht es um ein Drittel
#: groesser, und 5 MB je Bild nimmt die Anthropic-Schnittstelle.
BILD_MAX_BYTES = 3500000
#: Eine Textdatei geht bis zu dieser Groesse mit Inhalt, darueber nur ihr
#: Pfad (Claude Code) — nie Megabytes in den Kontext.
TEXT_MAX_BYTES = 200000
BILD_TYPEN = {".png": "image/png", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp"}
#: Alle Anhaenge EINER Nachricht zusammen hoechstens so gross (base64 der
#: Bilder plus Text): die Anthropic-Schnittstelle nimmt je Anfrage 32 MB,
#: und ein Bild bleibt im Verlauf des Chats. 10 Bilder zu 3,5 MB waeren
#: 46,7 MB base64 gewesen — die Anfrage scheiterte, und mit ihr jede
#: weitere desselben Chats (Gegenpruefung 2026-09-28).
ANHAENGE_GESAMT_MAX = 20000000
#: Text aus Textdateien zusammen hoechstens so viel (ungefaehr 100 000
#: Token): zehn Dateien zu 200 kB sprengten jedes Kontextfenster.
ANHAENGE_TEXT_MAX = 400000
ANHANG_LAEDT_NOCH = "Ein Anhang lädt noch. Gleich nochmal senden."
ANHANG_NUR_CLAUDE = ("Andere Dateien als Bilder und Text gehen nur mit Claude "
                     "Code. Den Anhang herausnehmen (×) oder unter ⚙ Claude "
                     "Code wählen.")
_ANHANG_NR = [0]


def _lokale_dateien(quelle):
    """Die lokalen Pfade in `quelle` (QMimeData) — sonst [].

    OHNE `os.path.isfile`: Qt fragt das bei jeder Mausbewegung eines
    Ziehens (`canInsertFromMimeData`), und auf einem Netzlaufwerk wartet so
    eine Abfrage — im Qt-Thread hiesse das, Cadwork steht. Ob es eine Datei
    ist, merkt der Leser im Nebenthread (ein Ordner wird dort ein Fehler mit
    Grund, Gegenpruefung 2026-09-28)."""
    try:
        if not quelle.hasUrls():
            return []
        return [u.toLocalFile() for u in quelle.urls()
                if u.isLocalFile() and u.toLocalFile()]
    except Exception:                                  # noqa: BLE001
        return []


def _anhang_aus_mime_sicher(z, quelle):
    """`_anhang_aus_mime` fuer die virtuelle Methode des Eingabefelds: eine
    Ausnahme dort ginge an Qt vorbei in qFatal (wie ein Slot ohne
    `_sicher`) — hier steht sie auf stderr, und der Text bleibt Text."""
    ergebnis = [False]

    def tun():
        ergebnis[0] = bool(_anhang_aus_mime(z, quelle))
    _sicher(tun, "Anhang einfügen")
    return ergebnis[0]


def _anhang_aus_mime(z, quelle):
    """Einfuegen oder Ablegen in der Eingabe: Dateien und Bilder werden
    Anhaenge (-> True), Text bleibt Text (-> False)."""
    pfade = _lokale_dateien(quelle)
    if pfade:
        _anhaenge_laden(z, pfade)
        return True
    if quelle.hasImage():
        from PyQt6.QtGui import QImage
        bild = quelle.imageData()
        if isinstance(bild, QImage) and not bild.isNull():
            _bild_einfuegen(z, QImage(bild))
            return True
    return False


def _anhang_eintrag(z, name):
    """Ein neuer Anhang im Zustand ("laedt") — oder None, wenn schon
    ANHANG_MAX da sind (dann steht es an der Eingabe)."""
    liste = z.setdefault("anhaenge", [])
    if len(liste) >= ANHANG_MAX:
        _chat_fehler_zeigen(z, "Höchstens %d Anhänge je Nachricht."
                            % ANHANG_MAX)
        return None
    _ANHANG_NR[0] += 1
    e = {"id": _ANHANG_NR[0], "name": name, "status": "laedt"}
    liste.append(e)
    z["anhaenge_stand"] = (z.get("anhaenge_stand") or 0) + 1
    return e


#: Zwei Leser, die gleichzeitig fertig werden, duerfen den Stand nicht
#: gemeinsam nur EINMAL hochzaehlen — sonst saehe der Takt den zweiten nie,
#: und sein Anhang stuende fuer immer auf "laedt" (Senden gesperrt).
_ANHANG_SPERRE = threading.Lock()


def _anhang_fertig(z, e, **felder):
    """Im Nebenthread: das Ergebnis eintragen (Zuweisungen, kein Widget)."""
    with _ANHANG_SPERRE:
        e.update(felder)
        z["anhaenge_stand"] = (z.get("anhaenge_stand") or 0) + 1


def _mb(n):
    return ("%.1f MB" % (n / 1e6)).replace(".", ",")


def _bild_art(kopf):
    """Der MIME-Typ eines Bilds nach seinen ersten Bytes — oder None.

    Nicht nach der Endung: ein JPEG namens `.png` ging sonst als
    `image/png` hinaus, und die Anthropic-Schnittstelle weist ein Bild ab,
    dessen Inhalt nicht zum Typ passt; ein Foto als `.jfif` war gar kein
    Bild (Gegenpruefung 2026-09-28)."""
    if kopf.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if kopf.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if kopf[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if kopf[:4] == b"RIFF" and kopf[8:12] == b"WEBP":
        return "image/webp"
    return None


def _anhang_datei_lesen(pfad):
    """Eine Datei als Anhang. WARTET (Datei): nur im Nebenthread.
    -> dict mit `status` "bereit" oder "fehler".

    Ob es ein Bild ist, sagen die ersten Bytes (`_bild_art`), nicht die
    Endung; eine Bild-Endung ohne Bild-Inhalt ist ein Fehler mit Grund."""
    name = os.path.basename(pfad.rstrip("\\/")) or pfad
    try:
        if os.path.isdir(pfad):
            return {"status": "fehler", "grund": "%s ist ein Ordner — "
                    "Ordner gibt «+ Ordner» oben frei." % name}
        groesse = os.path.getsize(pfad)
        endung = os.path.splitext(pfad)[1].lower()
        with open(pfad, "rb") as fh:
            kopf = fh.read(16)
        mime = _bild_art(kopf)
        if (mime is not None or endung in BILD_TYPEN) \
                and groesse > BILD_MAX_BYTES:
            return {"status": "fehler", "grund": "%s ist zu gross (%s, "
                    "höchstens %s)." % (name, _mb(groesse),
                                       _mb(BILD_MAX_BYTES))}
        if mime is None and endung in BILD_TYPEN:
            return {"status": "fehler", "grund": "%s ist kein Bild, das "
                    "sich schicken lässt (PNG, JPEG, GIF, WebP)." % name}
        if mime is not None:
            with open(pfad, "rb") as fh:
                roh = fh.read()
            import base64
            return {"status": "bereit", "art": "bild",
                    "mime": mime, "groesse": groesse,
                    "b64": base64.b64encode(roh).decode("ascii"),
                    "pfad": pfad}
        if groesse <= TEXT_MAX_BYTES:
            with open(pfad, "rb") as fh:
                roh = fh.read()
            try:
                inhalt = roh.decode("utf-8-sig")
            except UnicodeDecodeError:
                inhalt = None
            if inhalt is not None and "\x00" not in inhalt:
                return {"status": "bereit", "art": "text", "pfad": pfad,
                        "groesse": groesse,
                        "als_text": "Anhang «%s» (%s):\n%s"
                        % (name, pfad, inhalt)}
        return {"status": "bereit", "art": "datei", "pfad": pfad,
                "groesse": groesse,
                "als_text": "Anhang «%s»: die Datei liegt unter %s. Lies "
                            "sie dort, wenn du sie brauchst." % (name, pfad)}
    except OSError as exc:
        return {"status": "fehler",
                "grund": "%s lässt sich nicht lesen: %s" % (name, exc)}


def _anhaenge_laden(z, pfade):
    """Dateien als Anhaenge — gelesen im Nebenthread."""
    for pfad in pfade:
        e = _anhang_eintrag(z, os.path.basename(pfad))
        if e is None:
            break

        def lesen(e=e, pfad=pfad):
            try:
                _anhang_fertig(z, e, **_anhang_datei_lesen(pfad))
            except Exception as exc:                   # noqa: BLE001
                _anhang_fertig(z, e, status="fehler", grund=str(exc))

        threading.Thread(target=lesen, name="Open-MCP-CAD-Anhang",
                         daemon=True).start()
    _anhaenge_zeigen(z)


def _bild_kodieren(bild):
    """Ein QImage als PNG, zu gross als JPEG (85), dann halbiert (hoechstens
    dreimal). WARTET (Kodieren): nur im Nebenthread; QImage darf das (anders
    als QPixmap). -> (mime, bytes) oder (None, Grund)."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt

    def kodieren(b, art, guete=-1):
        daten = QByteArray()
        puffer = QBuffer(daten)
        puffer.open(QIODevice.OpenModeFlag.WriteOnly)
        b.save(puffer, art, guete)
        puffer.close()
        return bytes(daten.data())
    png = kodieren(bild, "PNG")
    if len(png) <= BILD_MAX_BYTES:
        return "image/png", png
    for _ in range(4):
        jpg = kodieren(bild, "JPG", 85)
        if len(jpg) <= BILD_MAX_BYTES:
            return "image/jpeg", jpg
        bild = bild.scaled(max(1, bild.width() // 2),
                           max(1, bild.height() // 2),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    return None, "Das Bild ist auch verkleinert zu gross."


def _bild_einfuegen(z, bild):
    """Ein Bild aus der Zwischenablage (oder abgelegt) als Anhang — kodiert
    im Nebenthread."""
    e = _anhang_eintrag(z, "Bild %s.png" % time.strftime("%H-%M-%S"))
    if e is None:
        return

    def kodieren():
        try:
            mime, daten = _bild_kodieren(bild)
            if mime is None:
                _anhang_fertig(z, e, status="fehler", grund=daten)
                return
            import base64
            if mime == "image/jpeg":
                e["name"] = e["name"][:-4] + ".jpg"
            _anhang_fertig(z, e, status="bereit", art="bild", mime=mime,
                           groesse=len(daten),
                           b64=base64.b64encode(daten).decode("ascii"))
        except Exception as exc:                       # noqa: BLE001
            _anhang_fertig(z, e, status="fehler", grund=str(exc))

    threading.Thread(target=kodieren, name="Open-MCP-CAD-Bild",
                     daemon=True).start()
    _anhaenge_zeigen(z)


def _anhaenge_zu_gross(anhaenge):
    """Der Grund, warum diese Anhaenge zusammen nicht in EINE Nachricht
    passen (ANHAENGE_GESAMT_MAX, ANHAENGE_TEXT_MAX) — oder None."""
    text = sum(len(a.get("als_text") or "") for a in anhaenge
               if a.get("art") == "text")
    gesamt = text + sum(len(a.get("b64") or "") + len(a.get("als_text") or "")
                        for a in anhaenge if a.get("art") != "text")
    if gesamt > ANHAENGE_GESAMT_MAX:
        return ("Zusammen zu gross für eine Nachricht (%s, höchstens %s). "
                "Einen Anhang herausnehmen (×) und ihn mit der nächsten "
                "Nachricht schicken." % (_mb(gesamt),
                                         _mb(ANHAENGE_GESAMT_MAX)))
    if text > ANHAENGE_TEXT_MAX:
        return ("Die Textdateien sind zusammen zu lang (%s, höchstens %s). "
                "Eine herausnehmen (×)." % (_mb(text),
                                            _mb(ANHAENGE_TEXT_MAX)))
    return None


def _anhang_nutzlast(a):
    """Was vom Anhang an den Chat geht (ohne Zustandsfelder)."""
    return {k: a[k] for k in ("art", "name", "mime", "b64", "als_text",
                              "pfad") if a.get(k) is not None}


def _anhang_entfernen(z, kennung):
    z["anhaenge"] = [a for a in z.get("anhaenge") or ()
                     if a.get("id") != kennung]
    _anhaenge_zeigen(z)


def _anhaenge_takt(z):
    """Im Takt: fertige Anhaenge zeigen; einen, der nicht ging, heraus und
    den Grund an die Eingabe. Billig: nur bei neuem Stand."""
    stand = z.get("anhaenge_stand")
    if z.get("anhaenge_gezeigt") == stand:
        return
    fehler = [a for a in z.get("anhaenge") or ()
              if a.get("status") == "fehler"]
    if fehler:
        z["anhaenge"] = [a for a in z["anhaenge"]
                         if a.get("status") != "fehler"]
        _chat_fehler_zeigen(z, " ".join(a.get("grund") or "Anhang geht "
                                        "nicht." for a in fehler))
    _anhaenge_zeigen(z)


def _anhaenge_zeigen(z):
    """Die Anhaenge als kleine Knoepfe ueber der Eingabe (je 3 in einer
    Zeile), ein Klick nimmt einen heraus."""
    w = z["w"]
    lay = w.get("chat_anhaenge_lay")
    if lay is None:
        return
    K = _qt_klassen()
    z["anhaenge_gezeigt"] = z.get("anhaenge_stand")
    while lay.count():
        alt = lay.takeAt(0).widget()
        if alt is not None:
            alt.hide()
            alt.deleteLater()
    liste = z.get("anhaenge") or []
    for i, a in enumerate(liste):
        zweck = ("laedt" if a.get("status") == "laedt" else
                 "bild" if a.get("art") == "bild" else "datei")
        b = K.KnappKnopf("%s ×" % a.get("name"))
        b.setObjectName("chip_knopf")
        _knopf_symbol(b, zweck, text="%s ×" % a.get("name"),
                      farbe=FARBEN["neben"], groesse=13)
        b.setToolTip("%s%s — klicken nimmt ihn heraus" % (
            a.get("pfad") or a.get("name"),
            (" · %s" % _mb(a["groesse"])) if a.get("groesse") else ""))
        b.clicked.connect(lambda _c=False, k=a.get("id"): _sicher(
            lambda: _anhang_entfernen(z, k), "Anhang entfernen"))
        lay.addWidget(b, i // 3, i % 3)
    w["chat_anhaenge"].setVisible(bool(liste))


def _anhang_dialog(z):
    """Der Dateidialog fuer "Datei oder Foto hinzufügen" — Qts eigener,
    mehrere Dateien, nicht modal (`open()`); ersetzbar fuer die Gates."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFileDialog
    start = arbeitsordner(_ordner_wahl(z)) or os.path.expanduser("~")
    dlg = QFileDialog(_dialog_eltern(z), "Datei oder Foto hinzufügen", start)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dlg.setNameFilters(["Bilder (*.png *.jpg *.jpeg *.gif *.webp)",
                        "Alle Dateien (*)"])
    dlg.selectNameFilter("Alle Dateien (*)")
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    return dlg


def _anhang_waehlen(z):
    """"Datei oder Foto hinzufügen": den Dialog zeigen und SOFORT
    zurueckkehren (`open()`, nie `exec()`)."""
    alt = z.get("anhang_dialog")
    if alt is not None:
        try:
            if alt.isVisible():
                alt.raise_()
                return
        except RuntimeError:
            pass
    dlg = _anhang_dialog(z)
    dlg.filesSelected.connect(lambda pfade: _sicher(
        lambda: _anhaenge_laden(z, list(pfade)), "Anhang laden"))
    z["anhang_dialog"] = dlg
    dlg.open()


def _zwischenablage_einfuegen(z):
    """"Aus der Zwischenablage": wie Strg+V in der Eingabe."""
    from PyQt6.QtWidgets import QApplication
    quelle = QApplication.clipboard().mimeData()
    if quelle is None or not _anhang_aus_mime(z, quelle):
        _chat_fehler_zeigen(z, "In der Zwischenablage liegt kein Bild und "
                               "keine Datei.")


def _plus_aufklappen(z):
    """Der Aufklapper von "+" (nach oben)."""
    w = z["w"]
    auf = w["chat_plus_auf"]
    auf.leeren()
    auf.eintrag("Datei oder Foto hinzufügen",
                lambda: _sicher(lambda: _anhang_waehlen(z),
                                "Datei hinzufügen"),
                tipp="Bilder gehen an jede KI; Textdateien mit Inhalt; "
                     "andere Dateien nur an Claude Code", symbol="paperclip")
    auf.eintrag("Aus der Zwischenablage einfügen",
                lambda: _sicher(lambda: _zwischenablage_einfuegen(z),
                                "Einfügen"), symbol="clipboard-paste")
    auf.notiz("Auch mit Strg+V oder durch Hineinziehen in die Eingabe. "
              "Bilder bis %s." % _mb(BILD_MAX_BYTES))
    return _aufklapper_zeigen(z, auf, w["chat_plus"], nach_oben=True)


def _gemerkte_ordnerliste(e, feld, hoechstens):
    """Eine Liste von Ordnern aus chat.json (`ordner_zuletzt`,
    `zusatzordner`): nur absolute Pfade als Text ohne Steuerzeichen, ohne
    Doppel, hoechstens `hoechstens`. Ob es sie gibt, entscheidet erst der
    Gebrauch."""
    wert = e.get(feld) if isinstance(e, dict) else None
    aus, gesehen = [], set()
    for p in wert if isinstance(wert, list) else ():
        if _gemerkter_ordner({"arbeitsordner": p}) is None:
            continue
        schluessel = os.path.normcase(os.path.normpath(p))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        aus.append(p)
        if len(aus) >= hoechstens:
            break
    return aus


def _zusatz_dialog(z):
    """Der Dialog fuer "+ Ordner" — Qts eigener, nicht modal (`open()`);
    eigene Funktion, damit ein Gate ihn ersetzen kann."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFileDialog
    start = arbeitsordner(_ordner_wahl(z)) or os.path.expanduser("~")
    dlg = QFileDialog(_dialog_eltern(z),
                      "Weiteren Ordner für Claude Code freigeben", start)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    return dlg


def _zusatz_waehlen(z):
    """"+ Ordner": den Dialog zeigen und SOFORT zurueckkehren (`open()`)."""
    alt = z.get("zusatz_dialog")
    if alt is not None:
        try:
            if alt.isVisible():
                alt.raise_()
                return
        except RuntimeError:
            pass
    dlg = _zusatz_dialog(z)
    dlg.fileSelected.connect(lambda pfad: _sicher(
        lambda: _zusatz_gewaehlt(z, pfad), "Ordner hinzufügen"))
    z["zusatz_dialog"] = dlg
    dlg.open()


def _zusatz_gewaehlt(z, pfad):
    """Einen weiteren Ordner freigeben (Claude Code: `--add-dir`, ab dem
    naechsten Chat). -> aufgenommen?"""
    pfad = os.path.normpath(pfad) if isinstance(pfad, str) and pfad else ""
    if not pfad or not os.path.isdir(pfad) \
            or _gemerkter_ordner({"arbeitsordner": pfad}) is None:
        _chat_fehler_zeigen(z, "Dieser Ordner lässt sich nicht öffnen.")
        return False
    # Der Ordner geht als `--add-dir` ueber claude.cmd, also durch cmd.exe:
    # ein `&` im Namen liefe dort als eigener Befehl (gemessen, s.
    # BEFEHLSZEILE_VERBOTEN im Chat-Modul; `starten` weist ihn ebenfalls ab).
    boese = sorted({c for c in pfad if c in getattr(
        _chat_modul(), "BEFEHLSZEILE_VERBOTEN", "")})
    if boese:
        _chat_fehler_zeigen(z, "Dieser Ordner enthält %s im Namen — so geht "
                               "er nicht sicher an Claude Code. Bitte "
                               "umbenennen." % " ".join(boese))
        return False
    liste = list(z.get("zusatz_ordner") or ())
    if any(os.path.normcase(p) == os.path.normcase(pfad) for p in liste):
        return False
    liste = (liste + [pfad])[-ZUSATZ_MAX:]
    _zusatz_merken(z, liste)
    return True


def _zusatz_entfernen(z, pfad):
    liste = [p for p in z.get("zusatz_ordner") or ()
             if os.path.normcase(p) != os.path.normcase(pfad)]
    _zusatz_merken(z, liste)


def _zusatz_merken(z, liste):
    """Die weiteren Ordner in den Zustand und nach chat.json; neu zeigen."""
    z["zusatz_ordner"] = list(liste)
    A = _anbieter_modul()
    e = _einstellungen(A)
    if e.get("zusatzordner") != list(liste):
        if liste:
            e["zusatzordner"] = list(liste)
        else:
            e.pop("zusatzordner", None)
        _sicher(lambda: A.einstellungen_schreiben(e), "Ordner merken")
    _zusatz_zeigen(z)


def _zusatz_zeigen(z):
    """Die weiteren Ordner als kleine Knoepfe neben "+ Ordner" (ein Klick
    nimmt einen wieder heraus)."""
    from PyQt6.QtWidgets import QPushButton
    w = z["w"]
    lay = w.get("chat_zusatz_lay")
    if lay is None:
        return
    while lay.count():
        alt = lay.takeAt(0).widget()
        if alt is not None:
            alt.hide()
            alt.deleteLater()
    for pfad in z.get("zusatz_ordner") or ():
        name = "%s ×" % (os.path.basename(pfad.rstrip("\\/")) or pfad)
        b = QPushButton(name)
        b.setObjectName("chip_knopf")
        _knopf_symbol(b, "ordner", text=name, farbe=FARBEN["neben"],
                      groesse=13)
        b.setToolTip("%s — Claude Code darf ihn zusätzlich lesen (ab dem "
                     "nächsten Chat). Klicken nimmt ihn heraus." % pfad)
        b.clicked.connect(lambda _c=False, pfad=pfad: _sicher(
            lambda: _zusatz_entfernen(z, pfad), "Ordner entfernen"))
        lay.addWidget(b)
    # So breit wie ihr Text, links (im Bild zu K5 lief einer ueber die
    # ganze Zeile).
    lay.addStretch(1)
    voll = len(z.get("zusatz_ordner") or ()) >= ZUSATZ_MAX
    w["chat_zusatz"].setEnabled(not voll)


def _seite_einsetzen(register, seite):
    """Die Seite des Chats in ihren Behaelter: seit K2 der Stapel des
    Chatfensters (vorne, Index 0), ein QTabWidget nimmt sie als Tab "Chat"
    (so rufen die Gates `_tab_chat` auch direkt)."""
    if hasattr(register, "addTab"):
        register.addTab(seite, "Chat")
    else:
        register.insertWidget(0, seite)


def _seiten(register):
    return [register.widget(i) for i in range(register.count())]


def _chat_takt_starten(z, eltern):
    """Eigener, schneller Takt NUR fuer den Chat — bei JEDEM Bau des Tabs neu.

    Der 500-ms-Takt des Dashboards reicht fuer Streaming nicht: die
    Textstuecke kommen gemessen alle 0,03–0,7 s, in Spitzen ~20 pro Sekunde.
    Der Aufruf ist billig — `_chat_zeichnen` kehrt sofort zurueck, solange
    sich nichts geaendert hat.

    Bis 2026-09-25 entstand der Timer nur, wenn `z["chat_takt"]` None war.
    Er haengt aber am Tab: loescht Cadwork das Dock, stirbt er mit, der
    Eintrag bleibt als totes Objekt stehen — und der neu gebaute Tab bekam
    nie wieder einen Takt. Jetzt wird ein alter angehalten und immer ein
    neuer gebaut.
    """
    from PyQt6.QtCore import QTimer
    alt = z.get("chat_takt")
    if alt is not None:
        try:
            alt.stop()
        except RuntimeError:                  # mit dem alten Tab geloescht
            pass
    takt = QTimer(eltern)
    takt.setInterval(100)
    takt.timeout.connect(lambda: _sicher(lambda: _chat_zeichnen(z),
                                         "Chat zeichnen"))
    takt.start()
    z["chat_takt"] = takt
    return takt


#: Teile, die zum Chatfenster und zum Monitor gehoeren, nicht zur Seite des
#: Chats: sie bleiben, wenn die Seite sich nicht bauen laesst (Ersatz).
CHAT_FENSTER_TEILE = ("chat_stapel", "chat_einst_seite", "chat_einst_fertig",
                      "chat_einst_freigabe")


def _tab_chat_oder_ersatz(z, register):
    """Der Chat-Tab — und laesst er sich nicht bauen, an seiner Stelle der Grund.

    Chat und Anbieter liegen unter festen Namen in `sys.modules` und bleiben
    bis zum Cadwork-Neustart; nach einem Update ohne Neustart trifft der Tab
    also womoeglich auf eine alte Fassung. Ein Fehler hier darf nie das
    ganze Dock kosten — und mit ihm das Verbinden.
    """
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
    vorher = _seiten(register)
    try:
        _tab_chat(z, register)
        return
    except Exception as exc:                           # noqa: BLE001
        _melden("Chat-Tab bauen", exc)
        grund = _chat_veraltet() or ("Der Chat ist nicht verfügbar: %s"
                                     % exc)
    # Halb Gebautes weg: eine zweite Chat-Seite und Teile in `z["w"]`, die
    # auf sie zeigen, waeren schlimmer als keine.
    for seite in _seiten(register):
        if seite not in vorher:
            if hasattr(register, "removeTab"):
                register.removeTab(register.indexOf(seite))
            else:
                register.removeWidget(seite)
            seite.deleteLater()
    # Ebenso die Karte "Chat" auf der Einstellungsseite: ihre Felder
    # gehoerten zur halb gebauten Seite.
    for name in ("chat_einst_karte", "chat_technik_karte"):
        einst = z["w"].get(name)
        if einst is not None:
            einst.setParent(None)
            einst.deleteLater()
    for schluessel in [k for k in z["w"] if k.startswith("chat_")
                       and k not in CHAT_FENSTER_TEILE]:
        del z["w"][schluessel]
    tab = QWidget()
    lay = QVBoxLayout(tab)
    lay.setContentsMargins(0, 10, 0, 0)
    karte, kl = _karte("")
    lbl = QLabel(grund)
    lbl.setObjectName("neben")
    lbl.setWordWrap(True)
    kl.addWidget(lbl)
    lay.addWidget(karte)
    lay.addStretch(1)
    _seite_einsetzen(register, tab)
    z["w"]["chat_ersatz"] = lbl


def _kurzname(a):
    """"OpenAI (Schlüssel, ohne Abo)" -> "OpenAI"; beim CLI "Claude"."""
    return "Claude" if a["art"] == "cli" else a["name"].split(" (")[0]


def _gewaehlter_anbieter(z):
    return _anbieter_modul().anbieter(z["w"]["chat_anbieter"].currentData())


def _wer_zeigen(z):
    """Im Chat-Tab: wer antwortet und wie viel gefragt wird — die Wahl
    selbst steht auf der Einstellungsseite (⚙). Billig, laeuft im Takt."""
    w = z["w"]
    try:
        name = _gewaehlter_anbieter(z)["name"]
    except Exception:                                  # noqa: BLE001
        name = w["chat_anbieter"].currentText()
    stufe = _modus_anzeige(_chat_modul().modus_von(z.get("chat")))
    # Es antwortet, wer LAEUFT — nicht, wer gerade im Feld steht (Pruefung
    # 2026-09-26: nach einem Wechsel stand dort sonst der falsche Name).
    chat = z.get("chat") or {}
    laeuft = chat.get("anbieter") if chat.get("an") else None
    if laeuft and laeuft != w["chat_anbieter"].currentData():
        try:
            jetzt = _anbieter_modul().anbieter(laeuft)["name"]
        except Exception:                              # noqa: BLE001
            jetzt = chat.get("kurzname") or laeuft
        text = "%s · Modus: %s · nächster Chat: %s" % (
            jetzt, stufe, name.split(" (")[0])
    else:
        text = "%s · Modus: %s" % (name, stufe)
    if w["chat_wer"].text() != text:
        w["chat_wer"].setText(text)


# --- Schluessel (S6, Uebergabe 2026-09-25 Abschnitt 2) ----------------------
# Speichern ist eine EIGENE Aktion. Danach steht nur noch eine Zeile
# "Schluessel gespeichert ···1234 · aendern · entfernen" da. Die letzten vier
# Zeichen liegen in chat.json (`schluessel_ende`, nie mehr, Entscheid
# 2026-09-26): der Qt-Thread liest den Tresor NIE im Klartext, auch nicht,
# um vier Zeichen zu zeigen. Ob ein aelterer Schluessel ohne diesen Eintrag
# im Tresor liegt, fragt ein Nebenthread und merkt sich nur Ja/Nein.

#: Erst ab dieser Laenge stehen die letzten vier Zeichen in chat.json — bei
#: einem kurzen Schluessel waeren vier Zeichen ein zu grosser Teil davon.
SCHLUESSEL_ENDE_AB = 12


def _schluessel_ende(e, kennung):
    """Die gemerkten letzten Zeichen: Text (auch "" = gespeichert, ohne
    Zeichen) oder None (nichts gemerkt). Unsinn in chat.json = None."""
    wert = e.get("schluessel_ende") if isinstance(e, dict) else None
    wert = wert.get(kennung) if isinstance(wert, dict) else None
    if isinstance(wert, str) and len(wert) <= 4 and wert.isprintable():
        return wert
    return None


def _schluessel_version(z, kennung):
    return (z.get("schluessel_version") or {}).get(kennung, 0)


def _schluessel_zeigen(z, a=None, e=None):
    """Schluessel-Teil der Karte "Chat" passend zum Anbieter zeigen.

    Liest chat.json, nie den Tresor. Eingabefeld nur, solange nichts
    gespeichert ist oder "aendern" gedrueckt wurde; sonst die eine Zeile.
    """
    w = z["w"]
    a = a or _gewaehlter_anbieter(z)
    teile = ("chat_schluessel_hilfe", "chat_schluessel_link",
             "chat_schluessel", "chat_schluessel_speichern",
             "chat_schluessel_abbrechen", "chat_schluessel_gespeichert")
    if a["art"] == "codex":
        for t in teile:
            w[t].hide()
        w["chat_schluessel_lage"].setText(
            "Anmeldung aus der Codex-App (Ordner .codex) — nur der "
            "Cadwork-Server, keine Shell")
        return
    art = a.get("schluessel", "keiner")
    brauchbar = a["art"] == "openai" and art != "keiner"
    if not brauchbar:
        for t in teile:
            w[t].hide()
        w["chat_schluessel_lage"].setText(
            "" if a["art"] == "cli" else "Kein Schlüssel nötig.")
        return
    if e is None:
        e = _einstellungen(_anbieter_modul())
    kurz = _kurzname(a)
    ende = _schluessel_ende(e, a["id"])
    da = ende is not None or bool((z.get("schluessel_da") or {}).get(a["id"]))
    eingeben = not da or z.get("schluessel_aendern") == a["id"]
    url = a.get("schluessel_url")
    if art == "pflicht":
        w["chat_schluessel_hilfe"].setText(
            "Ein Schlüssel (für Nutzung ohne Abo) ist dein persönlicher "
            "Zugangscode bei %s. "
            "Jede Anfrage kostet dort Geld, abgerechnet von %s. Den "
            "Schlüssel dort erstellen, kopieren und hier einfügen."
            % (kurz, kurz))
    else:
        w["chat_schluessel_hilfe"].setText(
            "Ein Schlüssel ist nur nötig, wenn der Dienst unter dieser "
            "Adresse einen verlangt.")
    w["chat_schluessel_hilfe"].setToolTip(SCHLUESSEL_TIPP)
    w["chat_schluessel_hilfe"].setVisible(eingeben)
    if url:
        w["chat_schluessel_link"].setText(
            '<a href="%s">Schlüssel bei %s holen ↗</a>' % (url, kurz))
    w["chat_schluessel_link"].setVisible(eingeben and bool(url))
    w["chat_schluessel"].setVisible(eingeben)
    w["chat_schluessel_speichern"].setVisible(eingeben)
    w["chat_schluessel_abbrechen"].setVisible(eingeben and da)
    w["chat_schluessel_gespeichert"].setVisible(not eingeben)
    w["chat_schluessel_ende"].setText(
        "Schlüssel gespeichert ···%s" % ende if ende
        else "Schlüssel gespeichert")
    w["chat_schluessel_entfernen"].setText(
        "wirklich entfernen?" if z.get("entfernen_bestaetigen") == a["id"]
        else "entfernen")
    if da:
        text = ""
    elif a.get("env") and os.environ.get(a["env"], "").strip():
        text = ("Im Moment gilt der Schlüssel aus der Umgebungsvariable %s."
                % a["env"])
    elif art == "optional":
        text = "Ohne Schlüssel."
    else:
        text = "Noch kein Schlüssel gespeichert."
    w["chat_schluessel_lage"].setText(text)


def _schluessel_da_pruefen(z, a):
    """Liegt fuer `a` ein Schluessel im Tresor? — im NEBENTHREAD.

    Nur fuer einen Schluessel, zu dem chat.json nichts weiss (gespeichert
    von einer Fassung vor S6). Der Thread merkt sich nur Ja/Nein.
    """
    if a["art"] != "openai" or a.get("schluessel", "keiner") == "keiner":
        return False
    kennung = a["id"]
    if kennung in (z.get("schluessel_da") or {}):
        return False
    A = _anbieter_modul()
    if _schluessel_ende(_einstellungen(A), kennung) is not None:
        return False
    laufend = z.setdefault("schluessel_da_laeuft", set())
    if kennung in laufend:
        return False
    laufend.add(kennung)
    ergebnisse = z.setdefault("schluessel_da_neu", [])
    version = _schluessel_version(z, kennung)

    def holen():
        try:
            da = A.schluessel_lesen(kennung) is not None
        except Exception:                              # noqa: BLE001
            da = False
        ergebnisse.append((kennung, da, version))
        laufend.discard(kennung)

    threading.Thread(target=holen, name="Open-MCP-CAD-Tresor",
                     daemon=True).start()
    return True


def _schluessel_takt(z):
    """Im Qt-Takt: fertige Tresor-Pruefungen uebernehmen. Eine Pruefung,
    die vor einem Speichern/Entfernen begann, gilt nicht mehr."""
    neu = z.get("schluessel_da_neu")
    if not neu:
        return
    geaendert = False
    while neu:
        kennung, da, version = neu.pop(0)
        if version == _schluessel_version(z, kennung):
            z.setdefault("schluessel_da", {})[kennung] = da
            geaendert = True
    if geaendert:
        _schluessel_zeigen(z)


def _schluessel_gewechselt(z, kennung, da):
    """Nach Speichern oder Entfernen: Stand merken, Liste gilt als alt."""
    z.setdefault("schluessel_da", {})[kennung] = da
    stand = z.setdefault("schluessel_version", {})
    stand[kennung] = stand.get(kennung, 0) + 1
    z["schluessel_aendern"] = None
    z["entfernen_bestaetigen"] = None


def _schluessel_speichern(z):
    """Den getippten Schluessel in den Tresor, das Feld leeren. -> ok?

    In chat.json kommen nur die letzten vier Zeichen, und nur bei einem
    Schluessel ab SCHLUESSEL_ENDE_AB Zeichen.
    """
    A = _anbieter_modul()
    w = z["w"]
    a = _gewaehlter_anbieter(z)
    feld = w["chat_schluessel"]
    text = feld.text().strip()
    if not text:
        w["chat_schluessel_lage"].setText(
            "Zuerst den Schlüssel ins Feld einfügen.")
        return False
    try:
        A.schluessel_speichern(a["id"], text)
    except Exception as exc:                           # noqa: BLE001
        # Die Meldung nennt nie den Schluessel (AnbieterFehler: Windows-
        # Fehlernummer). Das Feld bleibt gefuellt: nochmal versuchen geht.
        w["chat_schluessel_lage"].setText("Speichern ging nicht: %s" % exc)
        return False
    ende = text[-4:] if len(text) >= SCHLUESSEL_ENDE_AB else ""
    feld.clear()
    text = None
    e = _einstellungen(A)
    _eintragen(e, "schluessel_ende", a["id"], ende)
    _sicher(lambda: A.einstellungen_schreiben(e), "Schlüssel merken")
    _schluessel_gewechselt(z, a["id"], True)
    _schluessel_zeigen(z, a)
    w["chat_schluessel_lage"].setText(
        "Gespeichert im Windows-Tresor. Er wird hier nicht mehr angezeigt.")
    _modelle_knopf(z)
    return True


def _schluessel_aendern(z, an):
    """"aendern" zeigt das Feld wieder (der alte Schluessel bleibt, bis ein
    neuer gespeichert ist); "Abbrechen" klappt es zu und leert es."""
    w = z["w"]
    a = _gewaehlter_anbieter(z)
    z["schluessel_aendern"] = a["id"] if an else None
    z["entfernen_bestaetigen"] = None
    w["chat_schluessel"].clear()
    _schluessel_zeigen(z, a)
    if an:
        w["chat_schluessel"].setFocus()


def _schluessel_entfernen(z):
    """Aus dem Tresor und aus chat.json — erst beim ZWEITEN Klick.

    Ein Schluessel laesst sich beim Anbieter meist nicht nochmal ansehen;
    wer ihn versehentlich entfernt, muss einen neuen erstellen. Deshalb
    fragt der Knopf selbst nach ("wirklich entfernen?"), ohne Dialog.
    """
    A = _anbieter_modul()
    w = z["w"]
    a = _gewaehlter_anbieter(z)
    if z.get("entfernen_bestaetigen") != a["id"]:
        z["entfernen_bestaetigen"] = a["id"]
        _schluessel_zeigen(z, a)
        return False
    try:
        A.schluessel_loeschen(a["id"])
    except Exception as exc:                           # noqa: BLE001
        z["entfernen_bestaetigen"] = None
        w["chat_schluessel_lage"].setText("Entfernen ging nicht: %s" % exc)
        return False
    e = _einstellungen(A)
    ende = e.get("schluessel_ende")
    if isinstance(ende, dict) and a["id"] in ende:
        del ende[a["id"]]
        _sicher(lambda: A.einstellungen_schreiben(e), "Schlüssel vergessen")
    _schluessel_gewechselt(z, a["id"], False)
    _schluessel_zeigen(z, a)
    w["chat_schluessel_lage"].setText("Schlüssel entfernt.")
    _modelle_knopf(z)
    return True


# --- Lokale Modelle (Uebergabe 2026-09-25 Abschnitt 3) ----------------------
# Erkennen, Starten und Installieren laufen im NEBENTHREAD (`omcad_a_lokal`);
# der Qt-Takt liest nur `z["lokal_stand"]` und `z["lokal_meldung"]`.

#: Nach "Starten" fragt das Dock so lange je LOKAL_START_TAKT_S, ob der
#: Dienst antwortet; nach "Installieren" so lange je LOKAL_INSTALL_TAKT_S,
#: ob das Programm da ist (winget braucht Minuten).
LOKAL_START_NACHSEHEN_S = 20.0
LOKAL_START_TAKT_S = 1.0
LOKAL_INSTALL_NACHSEHEN_S = 900.0
LOKAL_INSTALL_TAKT_S = 5.0


def _lokal_pruefen(z, kennung, erzwingen=False):
    """Stand von `kennung` im Nebenthread erfragen. -> gestartet?"""
    L = _lokal_modul()
    if not L.ist_lokal(kennung):
        return False
    laufend = z.setdefault("lokal_laeuft", set())
    stand = z.setdefault("lokal_stand", {})
    if kennung in laufend or (kennung in stand and not erzwingen):
        return False
    laufend.add(kennung)
    z.setdefault("lokal_gefragt", {})[kennung] = time.monotonic()

    def holen():
        try:
            neu = L.pruefen(kennung)
        except Exception as exc:                       # noqa: BLE001
            neu = {"installiert": None, "fehler": str(exc)}
        stand[kennung] = neu
        laufend.discard(kennung)

    threading.Thread(target=holen, name="Open-MCP-CAD-Lokal",
                     daemon=True).start()
    return True


def _lokal_takt(z):
    """Im Qt-Takt: nach Starten/Installieren nachfragen lassen, zeichnen."""
    nachsehen = z.get("lokal_nachsehen") or {}
    stand = z.get("lokal_stand") or {}
    jetzt = time.monotonic()
    for kennung, (bis, takt, ziel) in list(nachsehen.items()):
        if (stand.get(kennung) or {}).get(ziel):
            del nachsehen[kennung]
            z.setdefault("lokal_meldung", {}).pop(kennung, None)
        elif jetzt > bis:
            del nachsehen[kennung]
            if ziel == "laeuft":
                text = ("Der Dienst antwortet noch nicht. Nochmals «Starten» "
                        "oder später «Neu prüfen».")
            else:
                # Ob winget gescheitert ist, sieht das Dock nicht (das
                # Fenster schliesst sich am Ende selbst). Also nicht mehr
                # "läuft" behaupten, sondern sagen, was man tun kann.
                L = _lokal_modul()
                text = ("%s wurde noch nicht gefunden. Ist die Installation "
                        "fertig, «Neu prüfen». Sonst von %s herunterladen."
                        % (L.LOKAL[kennung]["name"],
                           L.LOKAL[kennung]["seite"]))
            z.setdefault("lokal_meldung", {})[kennung] = text
        elif jetzt - (z.get("lokal_gefragt") or {}).get(kennung, 0) >= takt:
            _lokal_pruefen(z, kennung, erzwingen=True)
    _lokal_zeichnen(z)


def _lokal_eintrag(name, stand):
    """Der Name im Anbieter-Feld, mit dem Stand dahinter."""
    if not stand or stand.get("installiert") is None:
        return name
    if not stand["installiert"]:
        return "%s · nicht installiert" % name
    return "%s · %s" % (name, "bereit" if stand.get("laeuft")
                        else "läuft nicht")


def _lokal_frage_text(name):
    return ("%s installieren?\nWindows lädt %s aus dem offiziellen "
            "Windows-Katalog (winget) herunter und installiert es. Dafür "
            "geht ein eigenes Fenster auf, das den "
            "Fortschritt zeigt; fragt es nach Zustimmung zu den Bedingungen "
            "des Herstellers, bestätigst du dort selbst. Braucht Internet und "
            "einige Minuten. Die KI-Modelle lädst du danach in %s herunter "
            "(meist mehrere GB)." % (name, name, name))


def _lokal_zeichnen(z):
    """Stand, Knoepfe und Rueckfrage der lokalen Modelle — nur bei Aenderung."""
    w = z["w"]
    if "chat_lokal" not in w:
        return
    L = _lokal_modul()
    A = _anbieter_modul()
    stand_alle = z.get("lokal_stand") or {}
    feld = w["chat_anbieter"]
    for kennung in L.LOKAL:
        i = feld.findData(kennung)
        if i >= 0:
            text = _lokal_eintrag(A.anbieter(kennung)["name"],
                                  stand_alle.get(kennung))
            if feld.itemText(i) != text:
                feld.setItemText(i, text)
    kennung = feld.currentData()
    if not L.ist_lokal(kennung):
        return
    stand = stand_alle.get(kennung)
    pruef = kennung in (z.get("lokal_laeuft") or ())
    meldung = (z.get("lokal_meldung") or {}).get(kennung)
    frage = z.get("lokal_frage") == kennung
    marke = (kennung, repr(sorted((stand or {}).items())), pruef, meldung,
             frage)
    if z.get("lokal_gezeigt") == marke:
        return
    name = L.LOKAL[kennung]["name"]
    starten = installieren = False
    if stand is None:
        text = "Wird geprüft …" if pruef else "Noch nicht geprüft."
    elif stand.get("installiert") is None:
        text = "Prüfen ging nicht: %s" % stand.get("fehler")
    elif not stand["installiert"]:
        text = "%s ist auf diesem Rechner nicht installiert." % name
        installieren = True
    elif stand.get("laeuft"):
        text = "✓ Bereit — %s läuft auf diesem Rechner." % name
    else:
        text = "%s ist installiert, läuft aber nicht." % name
        starten = True
    if meldung:
        text += "\n" + meldung
    w["chat_lokal_lage"].setText(text)
    w["chat_lokal_starten"].setVisible(starten and not frage)
    w["chat_lokal_installieren"].setVisible(installieren and not frage)
    w["chat_lokal_pruefen"].setVisible(not frage)
    w["chat_lokal_pruefen"].setEnabled(not pruef)
    w["chat_lokal_frage"].setVisible(frage)
    if frage:
        w["chat_lokal_frage_text"].setText(_lokal_frage_text(name))
    z["lokal_gezeigt"] = marke


def _lokal_fragen(z):
    """"Installieren …": erst die Rueckfrage IM Dock, nichts wird gestartet."""
    z["lokal_frage"] = z["w"]["chat_anbieter"].currentData()
    _lokal_zeichnen(z)


def _lokal_frage_weg(z):
    z["lokal_frage"] = None
    _lokal_zeichnen(z)


def _lokal_im_thread(z, kennung, aufgabe, erst, dann, nachsehen=None):
    """`aufgabe()` im Nebenthread; Meldungen und Nachfragen fuer den Takt."""
    meldungen = z.setdefault("lokal_meldung", {})
    liste = z.setdefault("lokal_nachsehen", {})
    meldungen[kennung] = erst

    def los():
        try:
            ergebnis = aufgabe()
        except Exception as exc:                       # noqa: BLE001
            meldungen[kennung] = str(exc)
            return
        meldungen[kennung] = dann(ergebnis) if callable(dann) else dann
        if nachsehen is not None:
            liste[kennung] = (time.monotonic() + nachsehen[0], nachsehen[1],
                              nachsehen[2])

    threading.Thread(target=los, name="Open-MCP-CAD-Lokal-Aktion",
                     daemon=True).start()
    _lokal_zeichnen(z)


def _lokal_installieren(z):
    """Nach "Ja, installieren": winget in einem eigenen Fenster."""
    kennung = z.get("lokal_frage")
    z["lokal_frage"] = None
    L = _lokal_modul()
    if not L.ist_lokal(kennung):
        _lokal_zeichnen(z)
        return
    _lokal_im_thread(
        z, kennung, lambda: L.installieren(kennung),
        "Installation wird gestartet …",
        "Die Installation läuft im eigenen Fenster. Danach erscheint hier "
        "«Starten».", (LOKAL_INSTALL_NACHSEHEN_S, LOKAL_INSTALL_TAKT_S,
                        "installiert"))


def _lokal_starten(z):
    """Den lokalen Dienst losgeloest starten und ein paar Sekunden nachfragen."""
    kennung = z["w"]["chat_anbieter"].currentData()
    L = _lokal_modul()
    if not L.ist_lokal(kennung):
        return
    stand = dict((z.get("lokal_stand") or {}).get(kennung) or {})

    def dann(befehl):
        if befehl and not stand.get("programm"):
            return ("%s öffnet sich. Dort den lokalen Server einschalten."
                    % L.LOKAL[kennung]["name"])
        return "Gestartet — warte, bis der Dienst antwortet …"

    _lokal_im_thread(z, kennung, lambda: L.starten(kennung, stand),
                     "Wird gestartet …", dann,
                     (LOKAL_START_NACHSEHEN_S, LOKAL_START_TAKT_S, "laeuft"))


def _anbieter_gewechselt(z, merken=False):
    """Felder passend zum Anbieter zeigen und das Modellfeld neu fuellen.

    Claude Code: Modell-Kurznamen, Denkstufe, fortsetzbare Sitzungen. Die
    anderen: Schluessel, Modelle vom Dienst — Sitzungen gibt es dort
    (noch) nicht, jeder Start ist ein neues Gespraech. Die Adresse nur,
    wo es keine vorgegebene gibt ("Eigene Adresse", S6).
    """
    A = _anbieter_modul()
    C = _chat_modul()
    w = z["w"]
    a = _gewaehlter_anbieter(z)
    cli = a["art"] == "cli"
    e = _einstellungen(A)
    # Ein angefangener Wechsel gilt nur fuer den Anbieter, bei dem er begann;
    # ein getippter, nicht gespeicherter Schluessel ebenso.
    z["schluessel_aendern"] = None
    z["entfernen_bestaetigen"] = None
    z["lokal_frage"] = None
    w["chat_schluessel"].clear()
    w["chat_api"].setVisible(not cli)
    w["chat_basis"].setVisible(a["art"] == "openai" and not a.get("basis"))
    w["chat_lokal"].setVisible(_lokal_modul().ist_lokal(a["id"]))
    w["chat_stufe"].setVisible(cli)
    w["chat_ordner_teil"].setVisible(cli)
    if not cli:
        # Einen Chat aus der Liste fortsetzen kann nur Claude Code (S9).
        z["sitzung_offen"] = None
    w["chat_modelle"].setVisible(not cli)
    feld = w["chat_modell"]
    feld.blockSignals(True)
    feld.clear()
    if cli:
        for anzeige, wert in C.MODELLE:
            feld.addItem(anzeige, wert)
        # Das gemerkte Modell (Film 2026-09-25), sonst die Vorgabe. Ein von
        # Hand getippter Name steht in keiner Liste — er kommt ins Feld.
        gemerkt = _cli_modell(e, a["id"], C)
        i = feld.findData(gemerkt)
        if i >= 0:
            feld.setCurrentIndex(i)
        else:
            feld.setEditText(gemerkt)
        feld.setToolTip("Wirkt beim nächsten Start. Eigenen Namen eintippen "
                        "geht auch, z. B. claude-opus-4-7")
    else:
        if a["art"] == "openai":
            # Eine vorgegebene Adresse gilt IMMER. Bis Etappe B war das Feld
            # bei jedem dieser Anbieter sichtbar, in chat.json kann also eine
            # andere stehen — die ging dann unsichtbar mit dem Schluessel
            # hinaus, und Ollama hiess "bereit" (geprueft auf localhost),
            # waehrend der Chat woanders anfragte (Pruefung 2026-09-26).
            # Eine andere Adresse gibt es nur ueber "Eigene Adresse".
            w["chat_basis"].setText(a.get("basis")
                                    or _gemerkt(e, "basis", a["id"]) or "")
        for m in (z.get("modelle") or {}).get(a["id"]) or []:
            feld.addItem(m, m)
        feld.addItem(MODELLE_EINTRAG, MODELLE_ABFRAGEN)
        feld.setEditText(_gemerkt(e, "modell", a["id"]) or "")
        feld.setToolTip("Modellname — aus der Liste wählen oder eintippen. "
                        "Die Liste kommt vom Anbieter")
    _schluessel_zeigen(z, a, e)
    feld.blockSignals(False)
    _modelle_knopf(z)
    _modell_knopf_zeigen(z)
    if feld.lineEdit() is not None:
        feld.lineEdit().setPlaceholderText(
            "leer = Standardmodell des Kontos" if a["art"] == "codex" else "")
    w["chat_eingabe"].setPlaceholderText("%s fragen …" % _kurzname(a))
    z["lokal_gezeigt"] = None
    _lokal_zeichnen(z)
    _wer_zeigen(z)
    # Nur eine WAHL des Nutzers merken — nicht schon das Aufbauen des Tabs.
    if merken and e.get("anbieter") != a["id"]:
        e["anbieter"] = a["id"]
        A.einstellungen_schreiben(e)
    if _chat_einstellungen_sichtbar(z):
        _einstellungen_pruefen(z)


#: Letzter Eintrag im Modell-Dropdown der API-Anbieter. Ohne ihn bot das
#: Dropdown vor der ersten Abfrage NICHTS zur Auswahl (Rueckmeldung
#: 2026-09-25) — jetzt fuehrt es selbst zur Abfrage.
MODELLE_ABFRAGEN = "\x00modelle_abfragen"
MODELLE_EINTRAG = "↻ Modelle beim Anbieter abfragen …"
MODELLE_KNOPF_OFFEN = "Modelle abfragen"


def _modelle_stand(z):
    """Adresse und Stand des GESPEICHERTEN Schluessels, mit denen eine
    Liste gilt. Aendert sich eins davon, ist die Liste veraltet.

    Seit S6 nicht mehr das Feld: abgefragt wird immer mit dem Schluessel
    im Tresor, und das Speichern ist eine eigene Aktion. Ein nur getippter
    Schluessel aendert also nichts; Speichern oder Entfernen zaehlt
    `schluessel_version` hoch. Der Schluessel selbst steht nirgends.
    """
    w = z["w"]
    return (w["chat_basis"].text().strip(),
            _schluessel_version(z, w["chat_anbieter"].currentData()))


def _modelle_aktuell(z):
    """True, wenn fuer den gewaehlten Anbieter eine Liste mit der
    jetzigen Adresse und dem jetzigen Schluessel abgefragt wurde."""
    kennung = z["w"]["chat_anbieter"].currentData()
    return (kennung in (z.get("modelle") or {})
            and (z.get("modelle_stand") or {}).get(kennung)
            == _modelle_stand(z))


def _modelle_knopf(z):
    """Fehlt die Liste oder ist sie veraltet: blauer Knopf mit Text.
    Sonst ein kleiner ↻-Knopf zum Nachladen."""
    btn = z["w"].get("chat_modelle")
    if btn is None or not btn.isEnabled():
        return                      # Abfrage laeuft, Text "frage ab …"
    if _modelle_aktuell(z):
        name, text = "symbol", "↻"
        n = len((z.get("modelle") or {}).get(
            z["w"]["chat_anbieter"].currentData()) or [])
        tipp = "Modelle neu abfragen (%d in der Liste)" % n
    else:
        name, text = "hinweis", MODELLE_KNOPF_OFFEN
        tipp = "Die Modellliste fehlt oder ist veraltet: beim Anbieter abfragen"
    btn.setText(text)
    btn.setToolTip(tipp)
    if btn.objectName() != name:
        btn.setObjectName(name)
        btn.style().unpolish(btn)
        btn.style().polish(btn)


def _modell_getippt(z, text):
    if text != MODELLE_EINTRAG:
        z["modell_letzter"] = text


def _modell_gewaehlt(z, i):
    """Der Eintrag "Modelle abfragen" im Dropdown ist eine Aktion, kein
    Modell: den vorigen Namen zurueck ins Feld und abfragen.

    Bei Claude Code ist eine Wahl aus der Liste eine Wahl des Nutzers — sie
    wird gemerkt (die anderen Anbieter merken ihr Modell beim Start).
    """
    feld = z["w"]["chat_modell"]
    if feld.itemData(i) != MODELLE_ABFRAGEN:
        _sicher(lambda: _cli_wahl_merken(z), "Modell merken")
        return
    feld.setEditText(z.get("modell_letzter") or "")
    _modelle_abfragen(z)


def _modelle_abfragen(z):
    """GET /models im Hintergrund; das Ergebnis holt `_chat_zeichnen` ab."""
    A = _anbieter_modul()
    w = z["w"]
    a = _gewaehlter_anbieter(z)
    if a["art"] == "cli":
        return
    if w["chat_schluessel"].text().strip():
        # Abgefragt wird mit dem GESPEICHERTEN Schluessel (S6) — ein nur
        # getippter wuerde sonst still uebergangen.
        w["chat_schluessel_lage"].setText(
            "Zuerst «Speichern» drücken — abgefragt wird mit dem "
            "gespeicherten Schlüssel.")
        return
    basis = w["chat_basis"].text().strip()
    w["chat_modelle"].setEnabled(False)
    w["chat_modelle"].setText("frage ab …")
    w["chat_schluessel_lage"].setText("frage die Modelle ab …")
    stand = _modelle_stand(z)

    def holen():
        try:
            # Den Tresor liest NUR dieser Thread, nie der Qt-Takt (bis
            # 2026-09-26 stand das Lesen hier oben, im Qt-Thread).
            schluessel = A.schluessel_fuer(a)[0]
            z["modelle_neu"] = (a["id"], A.modelle_laden(a, basis, schluessel),
                                None, stand)
        except Exception as exc:                       # noqa: BLE001
            z["modelle_neu"] = (a["id"], None, str(exc), stand)

    threading.Thread(target=holen, name="Open-MCP-CAD-Modelle",
                     daemon=True).start()


def _modelle_uebernehmen(z):
    """Im Qt-Takt: eine fertige Modell-Abfrage ins Feld setzen."""
    neu = z.pop("modelle_neu", None)
    if neu is None:
        return
    w = z["w"]
    kennung, liste, fehler, stand = neu
    w["chat_modelle"].setEnabled(True)
    if fehler:
        z.setdefault("modelle_stand", {}).pop(kennung, None)
        _modelle_knopf(z)
        w["chat_schluessel_lage"].setText("Modelle: %s" % fehler[:200])
        return
    z.setdefault("modelle", {})[kennung] = liste
    z.setdefault("modelle_stand", {})[kennung] = stand
    if w["chat_anbieter"].currentData() != kennung:
        _modelle_knopf(z)
        return
    feld = w["chat_modell"]
    text = feld.currentText().strip()
    if text == MODELLE_EINTRAG:
        text = z.get("modell_letzter") or ""
    feld.blockSignals(True)
    feld.clear()
    for m in liste:
        feld.addItem(m, m)
    feld.addItem(MODELLE_EINTRAG, MODELLE_ABFRAGEN)
    feld.setEditText(text or (liste[0] if liste else ""))
    feld.blockSignals(False)
    _modelle_knopf(z)
    w["chat_schluessel_lage"].setText(
        "%d Modelle verfügbar" % len(liste) if liste
        else "Der Dienst nennt keine Modelle — Namen eintippen")


def _chat_anbieter_starten(z, a, st):
    """Start ueber die OpenAI-kompatible Schleife statt ueber Claude Code.

    Kein Projektordner noetig: diese Schleife hat keine Datei-Werkzeuge,
    nur die des MCP-Servers — und der bekommt Port und Dokument-Riegel wie
    beim CLI.
    """
    A = _anbieter_modul()
    C = _chat_modul()
    w = z["w"]
    chat = z.setdefault("chat", {})
    basis = w["chat_basis"].text().strip()
    modell = _modellwahl(w["chat_modell"]) or ""
    if w["chat_schluessel"].text().strip():
        # Bis 2026-09-26 speicherte der Start einen getippten Schluessel
        # selbst — auch wenn der Start danach scheiterte (kein Modell). Das
        # Speichern ist jetzt eine eigene Aktion (S6).
        _chat_fehler_zeigen(z, "Den Schlüssel zuerst speichern: ⚙ "
                               "Einstellungen, dann «Speichern».")
        return False
    lokal = (z.get("lokal_stand") or {}).get(a["id"])
    if lokal is not None and lokal.get("installiert") is False:
        # Nur waehlbar, was da ist (Uebergabe 2026-09-25, Abschnitt 3).
        # Ungeprueft (None) startet er wie bisher und sagt es, wenn der
        # Dienst nicht antwortet.
        _chat_fehler_zeigen(z, "%s ist auf diesem Rechner nicht "
                               "installiert. Unter ⚙ Einstellungen lässt es "
                               "sich installieren." % _kurzname(a))
        return False
    try:
        server = C.server_befehl(st.get("port"), st.get("dokument"))
        A.starten(chat, a["id"], modell, C.chat_entscheiden, basis=basis,
                  server=server, dokument=st.get("dokument"),
                  port=st.get("port"))
    except Exception as fehler:                        # noqa: BLE001
        _schluessel_zeigen(z, a)
        _chat_fehler_zeigen(z, "Chat startet nicht: %s" % fehler)
        return False
    chat["kurzname"] = _kurzname(a)
    chat["anbieter"] = a["id"]            # entscheidet die Kostenanzeige
    chat["wissen"] = C.wissensordner() if server else None
    e = _einstellungen(A)
    e["anbieter"] = a["id"]
    _eintragen(e, "basis", a["id"], basis)
    _eintragen(e, "modell", a["id"], modell)
    # Der Chat laeuft schon; scheitert nur das Merken (etwa ein Anbieter-
    # Modul einer aelteren Fassung im Speicher, das noch wirft), darf das
    # nicht aus dem Slot des Start-Knopfs laufen.
    _sicher(lambda: A.einstellungen_schreiben(e), "Einstellungen merken")
    _schluessel_zeigen(z, a)
    return True


def _sicher(fn, wo="Takt"):
    """Ein Fehler im Takt darf den Timer nie stillstellen — und nie still sein.

    Jeder verschiedene Fehler steht einmal auf stderr (`_melden`).
    """
    try:
        fn()
    except Exception as exc:                           # noqa: BLE001
        _melden(wo, exc)


def _chat_beenden(z):
    """Den Kindprozess NEBEN dem Qt-Takt abraeumen.

    `beenden()` wartet bis zu drei Sekunden auf ein sauberes Ende und ruft
    zur Not `taskkill`. Im Qt-Takt waeren das drei Sekunden, in denen
    Cadwork steht — dasselbe Argument wie bei den Steuerbefehlen im
    Verbindungen-Tab, die deshalb auch im Hintergrund laufen.
    """
    chat = z.setdefault("chat", {})
    chat["an"] = False                    # die Oberflaeche darf es sofort wissen
    # Der NUTZER hat beendet: dann ist ein stummes Ende kein Startfehler
    # (`_ohne_antwort_gestorben`), auch wenn stderr etwas enthaelt.
    z["chat_beendet_liste"] = chat.get("ereignisse")
    C = _chat_modul()
    threading.Thread(target=lambda: C.beenden(chat),
                     name="Open-MCP-CAD-A-Chat-Ende", daemon=True).start()


def _chat_ende_geklaert(z):
    """Rueckfrage vor dem Abwuergen. True = der Anrufer darf weitermachen.

    EINE Stelle fuer beide Wege — der Beenden-Knopf UND das Trennen der
    Bridge. Der Nutzer hat im Sichttest genau den zweiten erwischt: der Chat lief,
    und Trennen hat ihn wortlos abgeschossen.
    """
    from PyQt6.QtWidgets import QMessageBox
    C = _chat_modul()
    chat = z.setdefault("chat", {})
    if not C.laeuft_zug(chat):
        _chat_beenden(z)
        return True

    box = QMessageBox(_dialog_eltern(z))
    box.setWindowTitle("Chat beenden?")
    box.setText("%s arbeitet gerade an einer Antwort."
                % (chat.get("kurzname") or "Claude"))
    box.setInformativeText("Jetzt beenden bricht den laufenden Zug ab.")
    jetzt = box.addButton("Jetzt beenden",
                          QMessageBox.ButtonRole.DestructiveRole)
    nachher = box.addButton("Nach dem Zug beenden",
                            QMessageBox.ButtonRole.AcceptRole)
    gar_nicht = box.addButton("Weiterlaufen lassen",
                              QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(nachher)
    box.exec()
    geklickt = box.clickedButton()
    if geklickt is gar_nicht:
        return False
    if geklickt is nachher:
        C.nach_zug_beenden(chat)
        return False        # noch laeuft er — der Anrufer wartet ebenfalls
    _chat_beenden(z)
    return True


#: Laenger steht keine Meldung an der Eingabe (der Rest waere Technik).
CHAT_MELDUNG_MAX = 300


def _kurz_text(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


#: Ohne Verbindung kein Chat (Entscheid 2026-09-26): der Text bleibt im
#: Feld, das Dock verbindet NICHT von selbst.
#: Das CLI lebt nicht mehr, die Nachricht kam nicht an (Text bleibt im Feld).
CHAT_NICHT_GESENDET = ("Nicht gesendet — der Chat läuft nicht mehr. Dein "
                       "Text steht noch im Feld; „Neuer Chat“ beginnt neu.")
CHAT_ZUERST_VERBINDEN = ("Zuerst verbinden — der Chat arbeitet in der "
                         "Cadwork-Datei dieser Verbindung. Dein Text bleibt "
                         "stehen.")
#: Ohne Arbeitsordner startet Claude Code nicht. Seit S12 (Etappe D) nennt
#: der Satz die Wahl im Dock (Technik wie `projektordner.txt` steht in der
#: Anleitung, nicht hier: Pruefung Etappe C).
CHAT_KEIN_ORDNER = ("Claude Code braucht einen Arbeitsordner. Wähle ihn "
                    "oben links im Chatfenster (Ordner-Knopf) mit "
                    "«Arbeitsordner wählen …».")


def _chat_fehler_zeigen(z, text, art="fehler"):
    """Eine Meldung des Chats AN DER EINGABE — sie bleibt stehen.

    Bis S7 (2026-09-26) standen Startfehler in der Hinweiszeile im Kopf und
    verschwanden nach FEHLER_SICHTBAR_S. Hier bleibt sie, bis der Nutzer
    wieder handelt (`_chat_fehler_quittieren`: senden, Neuer Chat). Einzige
    Ausnahme: `art="verbinden"` geht von selbst, sobald eine Verbindung
    steht — dann stimmt sie nicht mehr (`_chat_zeichnen`).
    """
    text = _kurz_text(text, CHAT_MELDUNG_MAX)
    z["chat_meldung"] = (text, art)
    lbl = z["w"].get("chat_fehler")
    if lbl is None:
        _zeile_rot(z, text)               # Ersatz-Tab: dann eben oben
        return
    lbl.setText(text)
    lbl.show()


def _chat_fehler_quittieren(z):
    z["chat_meldung"] = None
    lbl = z["w"].get("chat_fehler")
    if lbl is not None:
        lbl.clear()
        lbl.hide()


def _chat_starten(z):
    """Einen Chat starten — seit S8 aus der ersten Nachricht (`_chat_senden`).

    -> True, wenn danach ein Chat laeuft. Sonst steht der Grund in der
    Fehlerzeile an der Eingabe, und der Anrufer laesst den Text stehen.
    """
    C = _chat_modul()
    chat = z.setdefault("chat", {})
    if chat.get("an"):
        return True
    d = z["dienst"]
    if d is None or d.beenden or d.zustand == "stopped":
        _chat_fehler_zeigen(z, CHAT_ZUERST_VERBINDEN, "verbinden")
        return False
    veraltet = _chat_veraltet()
    if veraltet:
        # Kein Start mit einer Fassung, die nicht zu diesem Dashboard passt:
        # das endete sonst in einem AttributeError irgendwo mitten im Start.
        _chat_fehler_zeigen(z, veraltet)
        return False
    a = _gewaehlter_anbieter(z)
    if a["art"] != "cli":
        return bool(_chat_anbieter_starten(z, a, d.status()))
    chat["kurzname"] = "Claude"
    ordner = arbeitsordner(_ordner_wahl(z))
    if ordner is None:
        # Lieber laut abbrechen als im Plugin-Ordner starten und die
        # Gespraeche in einer fremden Liste ablegen.
        _chat_fehler_zeigen(z, CHAT_KEIN_ORDNER)
        return False
    st = d.status()
    # Ein Chat aus der Liste (S9): die naechste Nachricht setzt IHN fort, in
    # derselben Sitzung (Entscheid 2026-09-26: `--resume` ohne Abzweigen).
    # Sein alter Verlauf bleibt stehen (`vorher`).
    offen = z.get("sitzung_offen")
    if offen is not None and offen.get("ordner") != ordner:
        # Die Sitzung liegt beim Ordner, in dem sie entstand; aus einem
        # anderen Ordner findet das CLI sie nicht.
        _chat_fehler_zeigen(z, "Der geöffnete Chat gehört zu einem anderen "
                               "Arbeitsordner. «Neuer Chat» drücken.")
        return False
    if offen is not None and offen.get("ereignisse") is None:
        # Der alte Verlauf wird noch gelesen (`_sitzung_oeffnen`). Jetzt
        # starten hiesse: ohne ihn — er erschiene nie mehr (Nacharbeit D).
        _chat_fehler_zeigen(z, CHAT_LAEDT_NOCH)
        return False
    if offen is not None and C.sitzung_belegt(offen["id"]):
        # Fuehrt ein anderes Cadwork diesen Chat gerade, schrieben zwei
        # Prozesse in eine Sitzungsdatei (Nacharbeit D). `C.starten` prueft
        # es noch einmal; hier steht es vorher und ohne Technik.
        _chat_fehler_zeigen(z, C.SITZUNG_BELEGT)
        return False
    try:
        C.starten(chat, ordner, port=st.get("port"),
                  dokument=st.get("dokument"),
                  sitzung=offen["id"] if offen else None,
                  abzweigen=False, name=C.SITZUNG_NAME,
                  vorher=(offen.get("ereignisse") or None) if offen else None,
                  modell=_modellwahl(z["w"]["chat_modell"]),
                  effort=z["w"]["chat_stufe"].currentData(),
                  zusatz=[p for p in z.get("zusatz_ordner") or ()
                          if os.path.isdir(p)])
    except C.SitzungBelegt as fehler:
        _chat_fehler_zeigen(z, str(fehler))
        return False
    except Exception as fehler:                        # noqa: BLE001
        _chat_fehler_zeigen(z, "Chat startet nicht: %s" % fehler)
        return False
    # Jetzt ist er der laufende Chat. Die Liste holt das Ende des Chats neu
    # (`_chat_zeichnen`): waehrend er laeuft, ist sie ohnehin verborgen.
    z["sitzung_offen"] = None
    chat["anbieter"] = a["id"]            # entscheidet die Kostenanzeige
    # Auch ein von Hand getipptes Modell: das hat kein `activated`.
    _sicher(lambda: _cli_wahl_merken(z), "Modell/Denkstufe merken")
    return True


def _chat_senden(z):
    """Senden — und laeuft noch kein Chat, startet diese Nachricht ihn (S8).

    Bis 2026-09-26 musste vor jedem Chat "Starten" gedrueckt werden; ohne
    laufenden Chat tat Senden nichts. Scheitert der Start (keine
    Verbindung, kein Ordner, kein gespeicherter Schluessel …), bleibt der
    Text im Feld und die Fehlerzeile sagt warum.
    """
    feld = z["w"]["chat_eingabe"]
    text = feld.toPlainText().strip()
    liste = z.get("anhaenge") or []
    if not text and not liste:
        return
    _chat_fehler_quittieren(z)            # der Nutzer handelt: Meldung weg
    if any(a.get("status") == "laedt" for a in liste):
        # Gelesen wird im Nebenthread; ohne den Anhang zu senden hiesse, er
        # ginge still verloren.
        _chat_fehler_zeigen(z, ANHANG_LAEDT_NOCH)
        return
    bereit = [a for a in liste if a.get("status") == "bereit"]
    chat = z.setdefault("chat", {})
    # Andere Dateien als Bilder und Text gehen nur an Claude Code (es liest
    # sie selbst ueber den Pfad) — geprueft VOR dem Start.
    try:
        wer = (_anbieter_modul().anbieter(chat.get("anbieter"))
               if chat.get("an") else _gewaehlter_anbieter(z))
    except Exception:                                  # noqa: BLE001
        wer = {}
    if wer.get("art") != "cli" and any(a.get("art") == "datei"
                                       for a in bereit):
        _chat_fehler_zeigen(z, ANHANG_NUR_CLAUDE)
        return
    zu_gross = _anhaenge_zu_gross(bereit)
    if zu_gross:
        _chat_fehler_zeigen(z, zu_gross)
        return
    if not chat.get("an") and not _chat_starten(z):
        return
    gesendet = None
    try:
        if bereit:
            gesendet = _chat_modul().senden(chat, text, [
                _anhang_nutzlast(a) for a in bereit])
        else:
            gesendet = _chat_modul().senden(chat, text)
    except Exception as fehler:                        # noqa: BLE001
        _chat_fehler_zeigen(z, "Nachricht nicht gesendet: %s" % fehler)
        return
    if gesendet is False:
        # Nur ein ausdrueckliches False heisst "nicht angekommen" (das CLI
        # lebt nicht mehr). Text und Anhaenge bleiben, die Zeile sagt es —
        # vorher leerte sich das Feld, und die Nachricht war weg (K7).
        _chat_fehler_zeigen(z, CHAT_NICHT_GESENDET)
        return
    feld.clear()
    if bereit:
        z["anhaenge"] = []
        _anhaenge_zeigen(z)


def _chat_neu(z):
    """"Neuer Chat": einen laufenden sauber beenden, den Verlauf leeren.

    Arbeitet der Chat gerade an einer Antwort, geht es hier NICHT weiter —
    dafuer gibt es "Beenden" mit seiner Rueckfrage. So kommt dieser Knopf
    nie an die modale Rueckfrage in `_chat_ende_geklaert` (nicht-modal).
    Geleert wird nur die ANZEIGE: die Liste des beendeten Chats bleibt,
    wie sie ist (ein Nachzuegler seines Lesers landet dort, nicht im
    neuen), und der naechste Start bringt eine eigene.
    """
    C = _chat_modul()
    chat = z.setdefault("chat", {})
    if C.laeuft_zug(chat):
        _chat_fehler_zeigen(z, "%s arbeitet gerade. Erst «Beenden» oder die "
                               "Antwort abwarten."
                            % (chat.get("kurzname") or "Claude"))
        return
    if chat.get("an") and not _chat_ende_geklaert(z):
        return
    _chat_fehler_quittieren(z)
    # Damit gilt auch eine Stoerung des alten Chats nicht mehr: die Lage
    # zeigt "Störung: …" nur zu einem Verlauf, der noch zu sehen ist
    # (`_chat_zeichnen`), auch wenn sein Leser sie spaeter noch setzt.
    z["verlauf_verworfen"] = chat.get("ereignisse")
    # Ein geoeffneter Chat aus der Liste gilt nicht mehr. Die Liste selbst
    # holt das Ende des Chats neu (`_chat_zeichnen`); ohne Ordner wird hier
    # sofort wieder gefragt.
    z["sitzung_offen"] = None
    z.pop("ordner_gefragt", None)
    chat["stand"] = chat.get("stand", 0) + 1


def _chat_beenden_geklickt(z):
    """"Beenden": nur bei laufendem Chat — mitten im Zug mit Rueckfrage."""
    if (z.get("chat") or {}).get("an"):
        # Beenden geht immer — auch mit einer alten Fassung im Speicher:
        # der laufende Chat gehoert zu genau der.
        _chat_ende_geklaert(z)


# --- Bisherige Chats (S9, Etappe D) -----------------------------------------
# Die Sitzungen des Arbeitsordners, die das Dock angelegt hat. Bis Etappe D
# fuellte der 100-ms-Takt ein Auswahlfeld SELBST (`C.sitzungen` im
# Qt-Thread, kalt 17-44 ms, bei grossen Dateien mehr); jetzt liest ein
# Nebenthread, der Takt holt nur das fertige Ergebnis ab (Muster wie
# `_modelle_abfragen`). Geholt wird beim ersten Bau, am Ende jedes Chats
# (das deckt Start und "Neuer Chat" mit ab: solange ein Chat laeuft, ist
# die Liste verborgen und wird nicht geholt) und beim Ordnerwechsel
# (`_liste_auffrischen`); die Zeitangaben ("vor 3 min") rechnet der Takt
# jede Minute neu, ohne Datei.

def _liste_auffrischen(z):
    """Eine frische Liste wuenschen. Geholt wird im naechsten Takt, sobald
    keine Abfrage mehr laeuft; ein Ergebnis zu einem aelteren Wunsch gilt
    nicht mehr."""
    z["liste_anlass"] = (z.get("liste_anlass") or 0) + 1


def _liste_holen(z, ordner):
    """`C.sitzungen` im Nebenthread; das Ergebnis holt `_liste_takt` ab."""
    C = _chat_modul()
    anlass = z.get("liste_anlass")
    cache = z.setdefault("chat_cache", {})
    z["liste_laeuft"] = True

    def holen():
        try:
            ergebnis = C.sitzungen(ordner, cache, nur_dock=True)
        except Exception as exc:                       # noqa: BLE001
            _melden("Chatliste", exc)
            ergebnis = []
        z["liste_neu"] = (anlass, ordner, ergebnis)
        z["liste_laeuft"] = False

    threading.Thread(target=holen, name="Open-MCP-CAD-Chatliste",
                     daemon=True).start()


#: Zweite Zeile eines Eintrags, den gerade ein anderes Cadwork fuehrt.
LISTE_BELEGT = "läuft gerade in einem anderen Cadwork"
#: An der Eingabe, wenn die erste Nachricht kommt, bevor der alte Verlauf
#: eines geoeffneten Chats gelesen ist.
CHAT_LAEDT_NOCH = "Der Chat lädt noch. Gleich nochmal senden."


def _liste_eintrag_text(e):
    zeit = _vor_wie_lange(e.get("geaendert"))
    if e.get("belegt"):
        zeit = "%s · %s" % (zeit, LISTE_BELEGT)
    return "%s\n%s" % (_kurz_text(e.get("bezeichnung"), 90), zeit)


def _liste_takt(z, holen, sichtbar):
    """Im Qt-Takt: Ergebnis abholen, bei Bedarf eine Abfrage anstossen,
    zeichnen. Liest keine Sitzungsdatei — nur `_ordner_nachfragen` (eine
    kleine Datei, gedrosselt)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem
    w = z["w"]
    neu = z.pop("liste_neu", None)
    if neu is not None and neu[0] == z.get("liste_anlass"):
        z["liste_stand"], z["liste_ordner"], z["liste"] = neu
        z["liste_gezeigt"] = None
    if (holen and z.get("liste_stand") != z.get("liste_anlass")
            and not z.get("liste_laeuft")):
        ordner = _ordner_nachfragen(z)
        if ordner:
            _liste_holen(z, ordner)
        elif z.get("liste"):
            z["liste"], z["liste_gezeigt"] = [], None   # kein Ordner mehr
    eintraege = z.get("liste") or []
    marke = (id(z.get("liste")), len(eintraege))
    minute = int(time.time() // 60)
    lst = w["chat_liste"]
    if z.get("liste_gezeigt") != marke:
        # Neu gebaut wird nur mit einer NEUEN Liste.
        z["liste_gezeigt"], z["liste_minute"] = marke, minute
        lst.clear()
        for e in eintraege:
            item = QListWidgetItem(_liste_eintrag_text(e))
            item.setData(Qt.ItemDataRole.UserRole, e.get("id"))
            item.setToolTip(e.get("untertitel") or e.get("bezeichnung") or "")
            lst.addItem(item)
    elif z.get("liste_minute") != minute:
        # Jede Minute nur die Zeitangaben, an Ort und Stelle: bis zur
        # Nacharbeit D leerte der Takt die Liste dafuer, und Auswahl und
        # Rollstand sprangen zurueck.
        z["liste_minute"] = minute
        for i, e in enumerate(eintraege):
            item = lst.item(i)
            if item is not None:
                text = _liste_eintrag_text(e)
                if item.text() != text:
                    item.setText(text)
    zeigen = bool(sichtbar and eintraege)
    if lst.isHidden() == zeigen:
        lst.setVisible(zeigen)
        w["chat_liste_titel"].setVisible(zeigen)
        # Liste ODER Verlauf, nie beide: sie teilen sich den Platz.
        w["chat_verlauf"].setVisible(not zeigen)


def _sitzung_oeffnen(z, item):
    """Ein Klick in die Liste: diesen Chat oeffnen (S9).

    Gestartet wird noch nichts — wie bei einem neuen Chat startet ihn die
    naechste Nachricht, dann mit `--resume` in DERSELBEN Sitzung
    (`_chat_starten`). Der alte Verlauf wird im Nebenthread gelesen
    (`C.sitzung_verlauf`, nur das Ende der Datei).
    """
    from PyQt6.QtCore import Qt
    chat = z.setdefault("chat", {})
    if chat.get("an"):
        return
    kennung = item.data(Qt.ItemDataRole.UserRole)
    eintrag = next((e for e in z.get("liste") or ()
                    if e.get("id") == kennung), None)
    ordner = z.get("liste_ordner")
    if eintrag is None or not ordner:
        return
    offen = {"id": kennung, "titel": eintrag.get("bezeichnung"),
             "ordner": ordner, "ereignisse": None,
             "belegt": bool(eintrag.get("belegt"))}
    z["sitzung_offen"] = offen
    _chat_fehler_quittieren(z)
    chat["stand"] = chat.get("stand", 0) + 1
    C = _chat_modul()

    def lesen():
        try:
            offen["ereignisse"] = C.sitzung_verlauf(ordner, kennung)
        except Exception as exc:                       # noqa: BLE001
            _melden("Chat öffnen", exc)
            offen["ereignisse"] = []
        z["verlauf_neu"] = True

    threading.Thread(target=lesen, name="Open-MCP-CAD-Chat-Verlauf",
                     daemon=True).start()


# --- Kontext (S10, Etappe D) --------------------------------------------------

def _tausender(n):
    # Schmales Leerzeichen als Tausendertrenner: "130 168".
    return "{:,}".format(int(n)).replace(",", chr(0x2009))


def _kontext_text(k):
    """(Text, Tooltip) fuer die Leiste — ("", "") ohne brauchbare Zahl.

    `k` ist `chat["kontext"]`: {"belegt": Token der letzten Anfrage,
    "fenster": was das Modell hoechstens fasst, oder None}. Woher die
    Zahlen kommen, steht bei den Anbietern (CLI: `_kontext_belegt`,
    Schleife und Codex: omcad_a_anbieter). Ohne Fenster nur die Zahl.
    """
    if not isinstance(k, dict):
        return "", ""
    belegt, fenster = k.get("belegt"), k.get("fenster")
    if not isinstance(belegt, int) or isinstance(belegt, bool) or belegt <= 0:
        return "", ""
    if isinstance(fenster, int) and not isinstance(fenster, bool) \
            and fenster > 0:
        anteil = min(100, int(round(100.0 * belegt / fenster)))
        return ("%d %% voll" % anteil,
                "Das Gedächtnis dieses Chats ist zu %d %% voll (%s von %s "
                "Token). Ist es voll, vergisst die KI den Anfang — dann "
                "lieber einen neuen Chat beginnen."
                % (anteil, _tausender(belegt), _tausender(fenster)))
    return ("%s Token" % _tausender(belegt),
            "So viel umfasst dieses Gespräch. Wie viel das Modell höchstens "
            "fasst, meldet dieser Anbieter nicht.")


def _kontext_sichtbar(text):
    """Steht der Fuellstand? Nur mit einem Anteil ab KONTEXT_AB % — rein
    (test_a_prototyp P22). Darunter muss niemand daran denken, und ohne
    Fenster (nur Token) gibt es keinen Fuellstand (Gegenpruefung
    Laien-Sicht K12: der Ring stand schon bei 10 % da und sah aus wie ein
    Ladekreis)."""
    import re as _re
    treffer = _re.search(r"(\d+)\s*%", text or "")
    return bool(treffer) and int(treffer.group(1)) >= KONTEXT_AB


def _kontext_zeigen(z, chat, an):
    """Im Takt: der Fuellstand in der Leiste — nur bei laufendem Chat, nur
    ab KONTEXT_AB %. Billig, nur Speicher."""
    text, tipp = _kontext_text(chat.get("kontext") if an else None)
    lbl = z["w"]["chat_kontext"]
    if lbl.text() != text:
        lbl.setText(text)
        lbl.setToolTip(tipp)
    sichtbar = _kontext_sichtbar(text)
    if lbl.isHidden() == sichtbar:
        lbl.setVisible(sichtbar)


# --- Ordnerwahl (S12, Etappe D) ---------------------------------------------

def _ordner_zeigen(z):
    """Auf der Einstellungsseite: welcher Ordner gilt, und warum.

    Liest `projektordner.txt` (klein) — nur beim Bau, beim Oeffnen der
    Einstellungen und nach einer Wahl, nie im Takt.
    """
    w = z["w"]
    lbl = w.get("chat_ordner_text")
    if lbl is None:
        return
    wahl = _ordner_wahl(z)
    wirksam = arbeitsordner(wahl)
    zeilen = [_umbrechbar(wirksam) or "Noch keiner gewählt."]
    if wahl and not os.path.isdir(wahl):
        zeilen.append("Der gewählte Ordner ist nicht erreichbar: %s"
                      % _umbrechbar(wahl))
    elif wahl and wirksam and os.path.normcase(wahl) != os.path.normcase(
            wirksam):
        zeilen.append("Deine Wahl gilt gerade nicht: die Einrichtung dieses "
                      "Rechners gibt einen anderen Ordner vor.")
    text = "\n".join(zeilen)
    if lbl.text() != text:
        lbl.setText(text)
    lbl.setToolTip(wirksam or "")          # der Pfad ohne Umbruch-Angebote
    w["chat_ordner_weg"].setVisible(bool(wahl))
    # Der Knopf im Kopf: der Name des Ordners, der ganze Pfad im Tooltip.
    knopf = w.get("chat_ordner")
    if knopf is not None:
        name = (os.path.basename(wirksam.rstrip("\\/")) or wirksam) \
            if wirksam else "Ordner wählen"
        knopf.setText(name)
        knopf.setToolTip(wirksam or "Noch kein Arbeitsordner gewählt")


def _umbrechbar(pfad):
    """Ein Pfad, den QLabel umbrechen darf: nach jedem Trenner ein
    Umbruch-Angebot (U+200B, unsichtbar). Ohne das bricht der Wortumbruch
    nur an Leerzeichen, und ein langer Pfad machte die Einstellungsseite
    breiter als das Dock (gesehen offscreen bei 300 px, L64)."""
    if not pfad:
        return pfad
    angebot = chr(0x200B)
    return pfad.replace("\\", "\\" + angebot).replace(
        "/", "/" + angebot)


def _ordner_dialog(z):
    """Der Dialog zur Ordnerwahl — Qts eigener, nicht der von Windows.

    Eigene Funktion, damit test_a_live L64 ihn ersetzen kann (der echte
    Dialog laesst sich offscreen zwar bauen, aber nicht bedienen).
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFileDialog
    start = arbeitsordner(_ordner_wahl(z)) or os.path.expanduser("~")
    dlg = QFileDialog(_dialog_eltern(z),
                      "Arbeitsordner für Claude Code wählen",
                      start)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    return dlg


def _ordner_waehlen(z):
    """"Arbeitsordner wählen …": den Dialog zeigen und SOFORT zurueckkehren.

    `open()`, nie `exec()`: `exec()` dreht eine eigene Ereignisschleife und
    haelt den Aufrufer an (Plan B.9). Solange der Dialog offen ist, haelt
    der Kern Cadwork-Auftraege zurueck (Sonde `modal`: `open()` macht ihn
    fenstermodal) — gewollt, in Cadwork NICHT gemessen. Das Ergebnis kommt
    ueber `fileSelected` (`_ordner_gewaehlt`).
    """
    alt = z.get("ordner_dialog")
    if alt is not None:
        try:
            if alt.isVisible():
                alt.raise_()
                return
        except RuntimeError:                  # geschlossen und geloescht
            pass
    dlg = _ordner_dialog(z)
    dlg.fileSelected.connect(lambda pfad: _sicher(
        lambda: _ordner_gewaehlt(z, pfad), "Arbeitsordner wählen"))
    z["ordner_dialog"] = dlg
    dlg.open()


def _ordner_gewaehlt(z, pfad):
    """Der Dialog hat einen Ordner geliefert: merken, Liste frisch."""
    pfad = os.path.normpath(pfad) if isinstance(pfad, str) and pfad else ""
    lbl = z["w"].get("chat_ordner_text")
    if not pfad or not os.path.isdir(pfad):
        if lbl is not None:
            lbl.setText("Dieser Ordner lässt sich nicht öffnen.")
        return False
    _ordner_merken(z, pfad)
    _ordner_zeigen(z)
    if z.get("ordner_wahl") != pfad:
        if lbl is not None:
            lbl.setText("Der Ordner lässt sich nicht merken: %s"
                        % _umbrechbar(pfad))
        return False
    meldung = z.get("chat_meldung")
    if meldung and meldung[0] == CHAT_KEIN_ORDNER:
        _chat_fehler_quittieren(z)        # stimmt nicht mehr
    return True


def _ordner_vergessen(z):
    """"Wahl entfernen": wieder ohne Wahl im Dock."""
    _ordner_merken(z, None)
    _ordner_zeigen(z)

# --- Gemerkte Wahl in chat.json ---------------------------------------------
# chat.json liegt im Benutzerprofil und kann alles enthalten: eine aeltere
# oder neuere Fassung, eine Hand-Aenderung, halb Geschriebenes. Nichts davon
# darf das Dock kosten (Film 2026-09-25, Auftrag dazu). Deshalb liest das
# Dashboard jeden Wert nur ueber diese Helfer: falsche Form = nicht gemerkt,
# es gilt die Vorgabe (test_a_live L39 am gebauten Dock). Alle ohne Qt —
# test_a_prototyp P10 ruft sie direkt.

#: Laenger ist kein Modellname, den ein Mensch eintippt.
MODELLNAME_MAX = 200


def _einstellungen(A):
    """chat.json als dict — kaputt oder fremd heisst leer.

    Die DATEI faengt `einstellungen_lesen` selbst ab (unlesbar, kein JSON,
    kein Objekt). Bewusst NICHT abgefangen wird hier ein Fehler des Moduls
    (etwa eine Fassung ohne `einstellungen_lesen`): das ist eine
    Fassungsfrage, und die soll der Ersatz-Tab nennen (test_a_live L26),
    nicht ein still leerer Chat.
    """
    e = A.einstellungen_lesen()
    return e if isinstance(e, dict) else {}


def _gemerkt(e, feld, kennung):
    """`e[feld][kennung]` als Text — oder None, wenn dort etwas anderes steht."""
    wert = e.get(feld) if isinstance(e, dict) else None
    wert = wert.get(kennung) if isinstance(wert, dict) else None
    if isinstance(wert, str) and wert.strip():
        return wert.strip()
    return None


def _eintragen(e, feld, kennung, wert):
    """`e[feld][kennung] = wert` — auch wenn `e[feld]` bisher Unsinn war."""
    if not isinstance(e.get(feld), dict):
        e[feld] = {}
    e[feld][kennung] = wert


def _modellname_ok(name):
    return (isinstance(name, str) and 0 < len(name) <= MODELLNAME_MAX
            and name.isprintable())


def _cli_modell(e, kennung, C):
    """Das gemerkte Modell von Claude Code, sonst MODELL_VORGABE."""
    name = _gemerkt(e, "modell", kennung)
    return name if _modellname_ok(name) else C.MODELL_VORGABE


def _cli_stufe(e, C):
    """Die gemerkte Denkstufe — nur eine, die es gibt —, sonst die Vorgabe."""
    stufe = e.get("denkstufe") if isinstance(e, dict) else None
    if isinstance(stufe, str) and stufe in [w for _, w in C.EFFORT_STUFEN]:
        return stufe
    return C.EFFORT_VORGABE


#: Laenger ist kein Ordner, den jemand im Dock waehlt. Haelt nur Unsinn aus
#: chat.json fern; die Windows-Grenze fuer lange Pfade liegt viel hoeher.
ORDNERPFAD_MAX = 1024


def _gemerkter_ordner(e):
    """Der im Dock gewaehlte Arbeitsordner aus chat.json — oder None.

    Nur ein absoluter Pfad als Text, ohne Steuerzeichen. OB es ihn gibt,
    entscheidet erst `arbeitsordner` bei jedem Gebrauch: ein Ordner auf
    einem gerade abgesteckten Laufwerk soll nicht vergessen werden, er
    gilt nur so lange nicht.
    """
    wert = e.get("arbeitsordner") if isinstance(e, dict) else None
    if (isinstance(wert, str) and 0 < len(wert) <= ORDNERPFAD_MAX
            and wert.isprintable() and os.path.isabs(wert)):
        return wert
    return None


def _ordner_wahl(z):
    """Die Ordnerwahl dieses Docks (beim Aufbau aus chat.json gelesen).

    Aus dem Zustand, nicht aus der Datei: `_chat_zeichnen` fragt im
    100-ms-Takt, chat.json liest dort niemand.
    """
    return _gemerkter_ordner({"arbeitsordner": z.get("ordner_wahl")})


#: Ohne Arbeitsordner fragt der Chat-Takt hoechstens so oft neu nach
#: (`_ordner_nachfragen`). Bis 2026-09-26 las er dann in JEDEM 100-ms-Takt
#: projektordner.txt — beim Neuling ohne Ordner, bei einer verschwundenen
#: Wahl und bei einer projektordner.txt mit totem Pfad.
ORDNER_NACHFRAGE_S = 2.0


def _ordner_nachfragen(z):
    """`arbeitsordner` fuer die Sitzungsliste — gedrosselt, wenn es keinen gab.

    Nach einer Antwort ohne Ordner fragt erst wieder, wer
    ORDNER_NACHFRAGE_S gewartet hat; so wird ein neu angelegter Ordner oder
    ein wieder eingestecktes Laufwerk trotzdem bald gefunden. Eine neue
    Wahl im Dock (`_ordner_merken`) hebt die Wartezeit auf.
    """
    jetzt = time.monotonic()
    zuletzt = z.get("ordner_gefragt")
    if zuletzt is not None and jetzt - zuletzt < ORDNER_NACHFRAGE_S:
        return None
    ordner = arbeitsordner(_ordner_wahl(z))
    z["ordner_gefragt"] = None if ordner else jetzt
    return ordner


def _ordner_merken(z, pfad):
    """Einen Arbeitsordner im Dock waehlen (None = die Wahl vergessen).

    Setzt ihn im Zustand und schreibt ihn nach chat.json. -> geschrieben?
    Ein Pfad, den `_gemerkter_ordner` nicht annaehme, aendert nichts. Die
    Liste der Chats haengt am Ordner; sie wird hier geleert und im Takt
    neu gefuellt.
    """
    if pfad is not None and _gemerkter_ordner({"arbeitsordner": pfad}) is None:
        return False
    z["ordner_wahl"] = pfad
    # Die neue Wahl gilt sofort: Liste leeren, Wartezeit aufheben, neu
    # holen. Ein geoeffneter Chat gehoerte zum alten Ordner.
    z.pop("ordner_gefragt", None)
    z["liste"] = []
    z["liste_gezeigt"] = None
    z["sitzung_offen"] = None
    _liste_auffrischen(z)
    A = _anbieter_modul()
    e = _einstellungen(A)
    # Die zuletzt benutzten (Ordner-Menue, K3): der neue zuerst.
    zuletzt = list(z.get("ordner_zuletzt") or ())
    if pfad is not None:
        zuletzt = [pfad] + [p for p in zuletzt if os.path.normcase(p)
                            != os.path.normcase(pfad)]
        zuletzt = zuletzt[:ORDNER_ZULETZT_MAX]
    z["ordner_zuletzt"] = zuletzt
    if e.get("arbeitsordner") == pfad and (
            pfad is None or e.get("ordner_zuletzt") == zuletzt):
        return False
    if pfad is None:
        e.pop("arbeitsordner", None)
    else:
        e["arbeitsordner"] = pfad
        e["ordner_zuletzt"] = zuletzt
    return bool(A.einstellungen_schreiben(e))


def _gemerkter_zeichenmodus(e, stufen):
    """Der gemerkte Zeichenmodus — nur einer, den der Kern kennt — oder None.

    `stufen` ist `ZEICHENMODI` des laufenden Kerns: welche es gibt,
    entscheidet der Kern, nicht eine Liste hier.
    """
    wert = e.get("zeichenmodus") if isinstance(e, dict) else None
    gueltig = [m.get("schluessel") for m in (stufen or ())
               if isinstance(m, dict)]
    if isinstance(wert, str) and wert in gueltig:
        return wert
    return None


def _zeichenmodus_merken(schluessel):
    """Den im Regler gewaehlten Zeichenmodus nach chat.json. -> geschrieben?"""
    A = _anbieter_modul()
    e = _einstellungen(A)
    if e.get("zeichenmodus") == schluessel:
        return False
    e["zeichenmodus"] = schluessel
    return bool(A.einstellungen_schreiben(e))


def _zeichenmodus_wiederherstellen(z):
    """Den gemerkten Zeichenmodus in einen FRISCH gestarteten Dienst setzen.

    Nur nach einem neuen Start (`_verbinden`, Ergebnis "verbunden"): ein
    Dienst, der in diesem Prozess schon lief und uebernommen wird, behaelt
    seinen Modus — den kann in dieser Sitzung jemand anders gestellt haben.
    -> der gesetzte Schluessel, sonst None. Ohne gemerkten Modus bleibt die
    Vorgabe des Kerns.
    """
    kern, d = z.get("kern"), z.get("dienst")
    methoden = getattr(kern, "_worker_methoden", None)
    if methoden is None or d is None or d.beenden:
        return None
    schluessel = _gemerkter_zeichenmodus(_einstellungen(_anbieter_modul()),
                                         getattr(kern, "ZEICHENMODI", ()))
    if schluessel is None:
        return None
    antwort = methoden(d)["zeichenmodus"]({"modus": schluessel})
    return schluessel if (antwort or {}).get("ok") else None


def _cli_wahl_merken(z):
    """Modell und Denkstufe von Claude Code nach chat.json. -> geschrieben?

    NUR diese beiden. Den Modus merkt `_modus_merken` (nie "Alles
    automatisch"). Geschrieben wird nur bei Aenderung — sonst bei jedem
    Klick dieselbe Datei.
    """
    A = _anbieter_modul()
    a = _gewaehlter_anbieter(z)
    if a["art"] != "cli":
        return False
    w = z["w"]
    e = _einstellungen(A)
    vorher = json.dumps(e, sort_keys=True, default=str)
    modell = _modellwahl(w["chat_modell"])
    if _modellname_ok(modell):
        _eintragen(e, "modell", a["id"], modell)
    stufe = w["chat_stufe"].currentData()
    if isinstance(stufe, str):
        e["denkstufe"] = stufe
    if json.dumps(e, sort_keys=True, default=str) == vorher:
        return False
    return bool(A.einstellungen_schreiben(e))


def _modus_name(modus):
    """"fragen" -> "Fragen" (die Anzeige aus `C.MODI`)."""
    try:
        return dict((m[0], m[1]) for m in _chat_modul().MODI).get(
            modus, modus or "?")
    except Exception:                                  # noqa: BLE001
        return modus or "?"


def _gemerkter_modus(e, C):
    """Der Modus aus chat.json fuer eine NEUE Cadwork-Sitzung — oder None.

    Nur ein Modus, den es gibt. "Alles automatisch" gilt nie ueber einen
    Neustart: steht er doch dort (Hand-Aenderung, andere Fassung), beginnt
    die Sitzung mit MODUS_STATT_AUTO."""
    wert = e.get("modus") if isinstance(e, dict) else None
    if not isinstance(wert, str) or wert not in C.MODUS_WERTE:
        return None
    return C.MODUS_STATT_AUTO if wert == C.MODUS_NIE_MERKEN else wert


def _modus_merken(modus, C):
    """Den gewaehlten Modus nach chat.json — "Alles automatisch" als
    MODUS_STATT_AUTO. -> geschrieben?"""
    if modus not in C.MODUS_WERTE:
        return False
    wert = C.MODUS_STATT_AUTO if modus == C.MODUS_NIE_MERKEN else modus
    A = _anbieter_modul()
    e = _einstellungen(A)
    if e.get("modus") == wert:
        return False
    e["modus"] = wert
    return bool(A.einstellungen_schreiben(e))


def _modus_wirksam(z, C, e=None):
    """Der Modus, nach dem der Chat in `z` JETZT entscheidet.

    Das Feld muss genau DIESEN zeigen. Der Chat (CLI, Schleife, Codex) liest
    bei jeder Anfrage `chat["modus"]`. Steht dort schon einer (dieselbe
    Cadwork-Sitzung, das Dock baut sich neu), gilt er — Anzeigen statt
    Zuruecksetzen (Gegenpruefung 2026-09-26, damals mit der Freigabestufe:
    das neue Feld zeigte die Vorgabe, der Chat nahm "Alles automatisch").
    Sonst (neue Sitzung) der gemerkte aus chat.json (`e`), sonst die
    Vorgabe — und er wird in den Chat geschrieben, damit Feld und Politik
    von hier an dasselbe sagen. Ein Wert, den es nicht gibt, wird zur
    Vorgabe ("Fragen"): die Politik fragt dann ohnehin bei allem, was nicht
    liest.
    """
    chat = z.setdefault("chat", {})
    if "modus" in chat:
        if chat["modus"] not in C.MODUS_WERTE:
            chat["modus"] = C.MODUS_VORGABE
        return chat["modus"]
    if e is None:
        e = _einstellungen(_anbieter_modul())
    chat["modus"] = _gemerkter_modus(e, C) or C.MODUS_VORGABE
    return chat["modus"]


def _modus_waehlen(z, modus):
    """Die Wahl des NUTZERS: gilt ab dem naechsten Werkzeugaufruf, auch
    mitten im Chat, und wird gemerkt (ausser "Alles automatisch")."""
    C = _chat_modul()
    if modus not in C.MODUS_WERTE:
        return False
    chat = z.setdefault("chat", {})
    chat["modus"] = modus
    # Neu zeichnen: der Hinweis "Nur lesen hat abgelehnt" gilt nur in
    # diesem Modus, die Karten zeigen "Für diese Sitzung" je nach Modus.
    chat["stand"] = chat.get("stand", 0) + 1
    _sicher(lambda: _karten_nach_modus(chat, modus, C), "Karten nach Modus")
    _sicher(lambda: _modus_merken(modus, C), "Modus merken")
    _modus_zeigen(z)
    return True


def _karten_nach_modus(chat, modus, C):
    """Offene Karten, die der NEUE Modus ohne Frage ablehnen wuerde (etwa
    nach dem Wechsel auf "Nur lesen"), gleich ablehnen — mit demselben Grund
    wie jede Ablehnung durch den Modus. Sonst stuende noch eine Karte
    "Erlauben" fuer einen Aufruf, den der gewaehlte Modus verbietet, und ein
    spaeter Klick liesse ihn laufen (Gegenpruefung 2026-09-28). Karten, die
    der neue Modus erlauben wuerde, bleiben stehen: dort entscheidet weiter
    der Nutzer. -> Zahl der abgelehnten."""
    n = 0
    for f in list(C.offene_freigaben(chat)):
        anfrage = {"blocked_path": True} if f.get("draussen") else {}
        if C.entscheiden(modus, f.get("werkzeug"), anfrage) != "nein":
            continue
        C.freigabe_beantworten(chat, f.get("id"), False,
                               C.ablehnung_text(modus, f.get("werkzeug")))
        n += 1
    if n:
        chat["stand"] = chat.get("stand", 0) + 1
    return n


def _modus_zeigen(z):
    """Den Modus-Knopf der Leiste auf den wirksamen Modus stellen: Text,
    Eigenschaft `modus` (was er zeigt) und Tooltip (der Satz aus dem
    Verhalten). Merkt nichts."""
    w = z["w"]
    feld = w.get("chat_modus")
    if feld is None:
        return
    C = _chat_modul()
    modus = _modus_wirksam(z, C)
    if feld.property("symbol") != MODUS_SYMBOLE.get(modus):
        ikone = _ikone(MODUS_SYMBOLE.get(modus, ""))
        if ikone is not None:
            feld.setIcon(ikone)
        feld.setProperty("symbol", MODUS_SYMBOLE.get(modus))
    feld.setText(_modus_anzeige(modus, C))
    feld.setProperty("modus", modus)
    text = _modus_hinweis(modus, C)
    feld.setToolTip(text)


MODUS_HINWEIS_UNBEKANNT = "Wie viel die KI ohne Frage darf."


def _modus_hinweis(modus, C):
    """Der Satz zum Modus — aus dem VERHALTEN der Politik, nie je Modus
    aufgeschrieben (bis 2026-09-26 stand beim Feld fest "Cadwork-Werkzeuge
    fragen IMMER", auch dort, wo Cadwork ohne Karte durchging). Gefragt
    wird `C.entscheiden` mit einem Cadwork-Befehl, einem Lese-Werkzeug,
    einem Befehl am Rechner und einem Schreiben; ob eine Freigabe je Art
    bis zur naechsten Nachricht gilt, mit einer Gewaehrung.
    test_a_prototyp P12 und test_a_live L47 vergleichen Satz und Politik.
    """
    try:
        cad = C.MCP_PRAEFIX + "__execute_cadwork_command"
        urteil = {w: C.entscheiden(modus, w)
                  for w in (cad, "Read", "Bash", "Write")}
        # Einmal je Art: genuegt EINE Freigabe fuer alles, was fragt?
        fragend = [w for w in (cad, "Bash", "Write")
                   if urteil[w] == "fragen"]
        je_art = bool(fragend) and all(
            C.entscheiden(modus, w, None, {w}) == "ja" for w in fragend)
    except Exception:                                  # noqa: BLE001
        # Laesst sich das Verhalten nicht erfragen, verspricht der Text
        # nichts.
        return MODUS_HINWEIS_UNBEKANNT
    aussen = {urteil["Bash"], urteil["Write"]}
    if urteil[cad] == "ja" and aussen == {"ja"}:
        return ("Achtung: Nichts wird gefragt, auch keine Cadwork-Befehle "
                "und keine Befehle am Rechner. Du siehst jeden Schritt erst "
                "danach im Verlauf.")
    teile = []
    if urteil["Read"] == "ja":
        teile.append("Lesen und Nachschlagen laufen ohne Rückfrage.")
    if urteil[cad] == "nein" and aussen == {"nein"}:
        teile.append("Cadwork-Befehle, Dateien ändern und Befehle am Rechner "
                     "werden abgelehnt, ohne zu fragen.")
    elif urteil[cad] == "ja" and aussen == {"fragen"}:
        teile.append("Cadwork-Befehle laufen ohne Rückfrage. Befehle am "
                     "Rechner, Dateien und Web fragen nach"
                     + (", einmal je Art bis zu deiner nächsten Nachricht."
                        if je_art else ", jedes Mal."))
    elif urteil[cad] == "fragen" and aussen == {"fragen"}:
        teile.append("Vor jeder Änderung wird gefragt"
                     + (", einmal je Art bis zu deiner nächsten Nachricht."
                        if je_art else ", jedes Mal."))
    else:
        return MODUS_HINWEIS_UNBEKANNT
    return " ".join(teile)


def _chat_im_abo(chat):
    """Laeuft der gezeigte Chat ueber ein Abo (Claude Code, Codex)?

    Entscheidet das Feld `abo` des Anbieters, nie sein Name. Unbekannt
    (etwa ein Chat, der vor einem Update gestartet wurde) heisst: nein —
    dann steht der Betrag da wie bisher.
    """
    try:
        return bool(_anbieter_modul().anbieter(chat.get("anbieter"))
                    .get("abo"))
    except Exception:                                  # noqa: BLE001
        return False


def _schluss_text(e, abo=False):
    """Die Schlusszeile eines Zugs im Verlauf.

    Film 2026-09-25: "fertig · 1.40 USD" nach jedem Zug von Claude Code
    (Abo) wirkte wie Kosten je Lauf. Das CLI meldet `total_cost_usd` auch im
    Abo, dort ist es aber keine Rechnung. Also: im Abo kein Betrag; bei
    Anbietern mit Schluessel bleibt alles, wie es war.
    """
    return "— fertig%s%s%s" % (
        (" · %.2f USD" % e["kosten"]) if e.get("kosten") and not abo else "",
        (" · %d Token" % e["token"]) if e.get("token") else "",
        (" · %d abgelehnt" % e["abgelehnt"]) if e.get("abgelehnt") else "")


# --- Lesbarer Chat (K5, Wunsch 2026-09-27) ---------------------------------
# Was die KI tut, in Worten eines Menschen: EINE Tabelle fuer den Chat und
# die Auftragsliste im Monitor. Drin stehen alle Werkzeuge von server.py
# (test_a_prototyp P14 liest sie aus der Quelle), die Methoden, die der Kern
# in seine Auftragsliste schreibt (`MODELL_METHODEN`, ebenfalls P14), und
# die haeufigsten Werkzeuge von Claude Code selbst. Alles andere bekommt eine
# lesbare Form (`_schritt_text`). Der technische Name steht NUR im Tooltip.
#: Seit K9 (Rueckmeldung 2026-09-28: Emoji wirkten "KI-haft") je Werkzeug
#: (Strich-Symbol aus omcad_a_symbole, Text) — der Text ohne Zeichen davor.
SCHRITTE = {
    # -- server.py ---------------------------------------------------------
    "get_document_info": ("file-text", "Dokument angeschaut"),
    "get_connection_status": ("plug", "Verbindung geprüft"),
    "report_check_note": ("pin", "Prüfhinweis notiert"),
    "clear_check_notes": ("eraser", "Prüfhinweise aufgeräumt"),
    "get_pending_messages": ("inbox", "Briefkasten gelesen"),
    "set_fast_draw": ("zap", "Zeichenmodus umgestellt"),
    "execute_cadwork_command": ("hammer", "Arbeitet in Cadwork"),
    "execute_cadwork_batch": ("layers", "In Paketen gezeichnet"),
    "undo": ("undo-2", "Rückgängig gemacht"),
    "redo": ("redo-2", "Wiederhergestellt"),
    "redraw_view": ("refresh-cw", "Ansicht neu gezeichnet"),
    "get_cadwork_api_help": ("book-open",
                             "In der Cadwork-Hilfe nachgeschlagen"),
    "get_working_examples": ("book-open", "Beispiele angeschaut"),
    "get_detail": ("ruler", "Detail nachgeschlagen"),
    "list_stored_keys": ("archive", "Ablage angeschaut"),
    "clear_store": ("eraser", "Ablage geleert"),
    "get_experiences": ("lightbulb", "Erfahrungen gelesen"),
    "record_experience": ("lightbulb", "Erfahrung festgehalten"),
    "create_from_init": ("file-plus", "Neue Datei angelegt"),
    "open_document": ("folder-open", "Datei geöffnet"),
    "wait_for_bridge": ("hourglass", "Wartet auf Cadwork"),
    # -- Kern (Auftragsliste im Monitor) -------------------------------------
    "execute_cwapi3d": ("hammer", "Arbeitet in Cadwork"),
    "elemente_zeigen": ("search", "Elemente gezeigt"),
    "sichtbarkeit_zurueck": ("rotate-ccw", "Ansicht zurückgesetzt"),
    "nachricht_senden": ("mail", "Nachricht geschrieben"),
    "neu_zeichnen": ("refresh-cw", "Ansicht neu gezeichnet"),
    # -- Claude Code selbst ---------------------------------------------------
    "Read": ("file-text", "Datei gelesen"),
    "Write": ("pencil", "Datei geschrieben"),
    "Edit": ("pencil", "Datei geändert"),
    "MultiEdit": ("pencil", "Datei geändert"),
    "Glob": ("search", "Dateien gesucht"),
    "Grep": ("search", "In Dateien gesucht"),
    "Bash": ("terminal", "Befehl ausgeführt"),
    "PowerShell": ("terminal", "Befehl ausgeführt"),
    "WebFetch": ("globe", "Webseite gelesen"),
    "WebSearch": ("globe", "Im Web gesucht"),
    "TodoWrite": ("list-checks", "Plan notiert"),
}
#: Ein Schritt, der nicht geklappt hat (Ergebnis mit Fehler).
SCHRITT_FEHLER = "Hat nicht geklappt, versucht es anders"
#: Das Symbol fuer Werkzeuge, die nicht in der Tabelle stehen.
SCHRITT_ANDERES = "wrench"
#: Werkzeuge DIESES Servers, die nicht in SCHRITTE stehen, kommen aus einer
#: Erweiterung (OPEN_MCP_CAD_ERWEITERUNGEN, seit 2026-10-01; die eigenen
#: stehen alle in der Tabelle, P14). Ihre Beschreibung kennt das Dock nicht
#: (Claude Code meldet nur Namen), und ihr technischer Name gehoert nur in
#: den Tooltip — also ein neutraler Satz, je nach Einstufung der Politik
#: (`C.werkzeug_art`): nur lesend oder aendernd.
SCHRITT_ERWEITERUNG_LESEN = ("search", "In einer Erweiterung nachgeschaut")
SCHRITT_ERWEITERUNG = ("wrench", "Schritt einer Erweiterung")
#: Symbole fuer den Zustand eines Schritts (vor dem des Werkzeugs).
SCHRITT_SYMBOL_FEHLER = "triangle-alert"
SCHRITT_SYMBOL_ABGELEHNT = "ban"
#: So lange Stille, dann steht vor dem naechsten Eintrag eine Zeitlinie.
ZEIT_LUECKE_S = 300


def _schritt_eintrag(werkzeug, C=None):
    """(kurzer Name oder None, Eintrag aus SCHRITTE oder None).

    Nur Werkzeuge DIESES Servers (`C._server_werkzeug`) lesen die Tabelle
    unter ihrem kurzen Namen — ein fremder Server mit einem gleich benannten
    Werkzeug ist nicht Cadwork."""
    roh = str(werkzeug or "?")
    kurz = C._server_werkzeug(roh) if C is not None else None
    if kurz is not None:
        return kurz, SCHRITTE.get(kurz)
    if not roh.startswith("mcp__"):
        return roh, SCHRITTE.get(roh)
    return None, None


def _schritt_erweiterung(werkzeug, C=None):
    """SCHRITT_ERWEITERUNG(_LESEN), wenn `werkzeug` zu DIESEM Server gehoert
    und nicht in SCHRITTE steht (also aus einer Erweiterung kommt), sonst
    None. Lesend nur, was die Politik lesend nennt; wirft nie."""
    if C is None:
        return None
    roh = str(werkzeug or "?")
    try:
        kurz = C._server_werkzeug(roh)
        if kurz is None or kurz in SCHRITTE:
            return None
        lesend = C.werkzeug_art(roh) == "lesen"
    except Exception:                                  # noqa: BLE001
        return None
    return SCHRITT_ERWEITERUNG_LESEN if lesend else SCHRITT_ERWEITERUNG


def _schritt_symbol(werkzeug, C=None):
    """Das Strich-Symbol eines Schritts (Lucide-Name), sonst SCHRITT_ANDERES."""
    _kurz_name, eintrag = _schritt_eintrag(werkzeug, C)
    eintrag = eintrag or _schritt_erweiterung(werkzeug, C)
    return eintrag[0] if eintrag else SCHRITT_ANDERES


def _schritt_text(werkzeug, eingabe=None, paket=None, C=None):
    """Was ein Schritt tut, in Worten (ohne Zeichen; das Symbol gibt
    `_schritt_symbol`) — aus `SCHRITTE`, fuer ein Werkzeug einer Erweiterung
    neutral (`_schritt_erweiterung`, nie sein technischer Name), sonst
    lesbar aus dem Namen ("mcp__anderer__do_thing" -> "Do thing
    (anderer)"). `paket` (k, n): der laufende Paketlauf."""
    roh = str(werkzeug or "?")
    kurz, eintrag = _schritt_eintrag(roh, C)
    if kurz == "execute_cadwork_batch" and paket:
        try:
            return "Zeichnet (Paket %d von %d)" % (int(paket[0]),
                                                   int(paket[1]))
        except (TypeError, ValueError, IndexError):
            pass
    if kurz == "execute_cadwork_command" and isinstance(eingabe, dict):
        was = " ".join(str(eingabe.get("description") or "").split())
        if was:
            return _kurz_text(was, 60)
    if eintrag:
        return eintrag[1]
    erweiterung = _schritt_erweiterung(roh, C)
    if erweiterung:
        return erweiterung[1]
    teile = roh.split("__")
    fremd = len(teile) >= 3 and teile[0] == "mcp"
    name = teile[-1] if fremd else roh
    lesbar = " ".join(name.replace("-", "_").split("_")).strip() or "?"
    lesbar = lesbar[:1].upper() + lesbar[1:]
    if fremd and C is not None and C._server_werkzeug(roh) is None:
        return "%s (%s)" % (lesbar, teile[1])
    return lesbar


def _zeit_text(t, jetzt):
    """Wann, grob und immer groeber, je aelter (Wunsch 2026-09-27): "gerade
    eben", "vor 5 min", "vor 40 min", "heute 09:12", "gestern 17:40",
    "12.09. 08:15". Keine Dauer."""
    import datetime
    try:
        t = float(t)
    except (TypeError, ValueError):
        return ""
    d = jetzt - t
    if d < 60:
        return "gerade eben"
    if d < 600:
        return "vor %d min" % (d // 60)
    if d < 3600:
        return "vor %d min" % (d // 300 * 5)
    dann = datetime.datetime.fromtimestamp(t)
    heute = datetime.datetime.fromtimestamp(jetzt).date()
    if dann.date() == heute:
        return dann.strftime("heute %H:%M")
    if dann.date() == heute - datetime.timedelta(days=1):
        return dann.strftime("gestern %H:%M")
    if dann.year == heute.year:
        return dann.strftime("%d.%m. %H:%M")
    return dann.strftime("%d.%m.%Y")


def _schritt_suchen(schritte, e, nach_id=True):
    """Der Schritt zu einem Ereignis: ueber die Kennung, sonst der letzte
    noch laufende mit demselben Werkzeug."""
    if nach_id and e.get("id") is not None:
        for s in reversed(schritte):
            if s.get("id") == e.get("id"):
                return s
    for s in reversed(schritte):
        if s["werkzeug"] == e.get("werkzeug") and s["status"] == "laeuft" \
                and not s["auto"]:
            return s
    return None


def _schritte_fertig(block, am_ende, laeuft, paket, C):
    """Kopf und Zeilen einer Gruppe von Schritten."""
    schritte = block.pop("schritte")
    n = len(schritte)
    cad = C is not None and all(C._server_werkzeug(s["werkzeug"])
                                for s in schritte)
    kopf = "%d Schritt%s%s" % (n, "" if n == 1 else "e",
                               " in Cadwork" if cad else "")
    jetzt_s = None
    if am_ende and laeuft:
        offen = [s for s in schritte if s["status"] == "laeuft"]
        jetzt_s = offen[-1] if offen else None
    zeilen, symbole = [], []
    for s in schritte:
        text = _schritt_text(s["werkzeug"], s.get("eingabe"),
                             paket if s is jetzt_s else None, C)
        symbol = _schritt_symbol(s["werkzeug"], C)
        tipp = "%s\n%s" % (s["werkzeug"], _kurz(s.get("eingabe"), 300))
        if s["status"] == "fehler":
            tipp = "%s\n%s" % (text, tipp)
            text = SCHRITT_FEHLER
            symbol = SCHRITT_SYMBOL_FEHLER
        elif s["status"] == "verweigert":
            text = "%s — abgelehnt (Modus «%s»)" % (
                text, _modus_name(s.get("modus")))
            symbol = SCHRITT_SYMBOL_ABGELEHNT
        elif s is jetzt_s:
            text += " …"
        if s["auto"]:
            tipp += "\nautomatisch erlaubt"
        zeilen.append((text, tipp))
        symbole.append(symbol)
    fehler = sum(1 for s in schritte if s["status"] == "fehler")
    nein = sum(1 for s in schritte if s["status"] == "verweigert")
    if jetzt_s is not None:
        kopf += " · " + _schritt_text(jetzt_s["werkzeug"],
                                      jetzt_s.get("eingabe"), paket, C)
    elif fehler:
        kopf += " · %d %s nicht geklappt" % (fehler, "hat" if fehler == 1
                                              else "haben")
    if nein:
        kopf += " · %d abgelehnt" % nein
    block.update(kopf=kopf, zeilen=zeilen, symbole=symbole,
                 laeuft=jetzt_s is not None,
                 warnung=bool(fehler or nein))
    return block


def _verlauf_bloecke(ereignisse, jetzt, abo=False, paket=None, laeuft=False,
                     C=None, tippt=None):
    """Aus den Ereignissen des Chats die Bloecke des Verlaufs -> [dict].

    Rein (kein Qt), damit P14 sie ohne Fenster pruefen kann. Jeder Block
    traegt einen `schluessel` aus der Stelle seines ersten Ereignisses — so
    zeichnet der Verlauf nur, was sich geaendert hat, und eine
    aufgeklappte Gruppe bleibt auf, waehrend sie waechst.
      zeit      Zeitlinie, nur wo nach ZEIT_LUECKE_S wieder etwas kommt
      ich       Nachricht des Nutzers (rechts), mit den Namen der Anhaenge
      ki        Antwort (eigene Blase mit ✦)
      schritte  aufeinanderfolgende Werkzeuge als EINE Zeile
      notiz     Hinweis
      tippt     "…" an der Stelle der naechsten Antwort (`tippt` = was die
                KI gerade tut, fuer den Tooltip)
    Der Schluss eines Zugs ("fertig · 18 Token") ist keine Zeile mehr
    (Feinschliff 2026-09-28), sondern der `fuss` der letzten Antwort des
    Zugs — ihr Tooltip.
    """
    bloecke, gruppe, vorher = [], None, None
    for i, e in enumerate(ereignisse or ()):
        art = e.get("art")
        zeit = e.get("zeit")
        schritt = art in ("werkzeug", "auto", "verweigert", "ergebnis")
        if isinstance(zeit, (int, float)):
            luecke = vorher is None or zeit - vorher >= ZEIT_LUECKE_S
            vorher = zeit if vorher is None else max(vorher, zeit)
            if luecke and not (schritt and gruppe is not None):
                gruppe = None
                bloecke.append({"art": "zeit", "schluessel": "z%d" % i,
                                "text": _zeit_text(zeit, jetzt)})
        if schritt:
            if art == "ergebnis":
                if gruppe is not None:
                    s = next((s for s in reversed(gruppe["schritte"])
                              if e.get("id") is not None
                              and s.get("id") == e.get("id")), None)
                    if s is not None:
                        s["status"] = "fehler" if e.get("fehler") else "ok"
                continue
            if gruppe is None:
                gruppe = {"art": "schritte", "schluessel": "s%d" % i,
                          "schritte": []}
                bloecke.append(gruppe)
            liste = gruppe["schritte"]
            s = None
            if art in ("auto", "verweigert"):
                s = _schritt_suchen(liste, e, nach_id=art == "verweigert")
            if s is None:
                s = {"werkzeug": e.get("werkzeug") or "?",
                     "eingabe": e.get("eingabe"), "id": e.get("id"),
                     "status": "laeuft", "auto": False}
                liste.append(s)
            if art == "auto":
                s["auto"] = True
            elif art == "verweigert":
                s["status"], s["modus"] = "verweigert", e.get("modus")
            continue
        gruppe = None
        if art == "ich":
            bloecke.append({"art": "ich", "schluessel": "i%d" % i,
                            "text": e.get("text") or "",
                            "anhaenge": list(e.get("anhaenge") or ())})
        elif art == "text":
            bloecke.append({"art": "ki", "schluessel": "k%d" % i,
                            "text": e.get("text") or ""})
        elif art == "hinweis":
            bloecke.append({"art": "notiz", "schluessel": "n%d" % i,
                            "text": e.get("text") or ""})
        elif art == "schluss":
            antwort = None
            for b in reversed(bloecke):
                if b["art"] == "ich":
                    break
                if b["art"] == "ki":
                    antwort = b
                    break
            if antwort is not None:
                antwort["fuss"] = _schluss_text(e, abo).lstrip("— ")
        else:
            bloecke.append({"art": "notiz", "schluessel": "n%d" % i,
                            "text": _schluss_text(e, abo)})
    letzte = len(bloecke) - 1
    for j, b in enumerate(bloecke):
        if b["art"] == "schritte":
            _schritte_fertig(b, j == letzte, laeuft, paket, C)
    if tippt:
        bloecke.append({"art": "tippt", "schluessel": "tippt",
                        "text": tippt})
    return bloecke


def _tipp_klartext(text):
    """Ein Tooltip, der Eingaben der KI zeigt (Code, Beschreibung), als
    Klartext. Qt liest Tooltips als Rich Text, sobald die erste Zeile wie
    HTML aussieht — "<img src=…>" in einer Beschreibung wuerde sonst
    geladen. Also maskiert, Zeilenumbrueche bleiben."""
    import html
    return "<p style='white-space:pre-wrap'>%s</p>" % html.escape(
        str(text or ""))


def _auftrag_zeile(v, jetzt):
    """Ein Auftrag der Liste im Monitor, lesbar -> (Text, Tooltip). Die
    Methode, die Dauer und das Paket stehen nur im Tooltip."""
    methode = v.get("methode") or "?"
    grund = _schritt_text(methode)
    was = " ".join(str(v.get("beschreibung") or "").split())
    name = _kurz_text(was, 70) if was else grund
    paket = v.get("paket")
    try:
        paket = (int(paket[0]), int(paket[1])) if paket else None
    except (TypeError, ValueError, IndexError):
        paket = None
    if paket:
        name += " (Paket %d von %d)" % paket
    teile = [name]
    if not v.get("ok"):
        teile.append("hat nicht geklappt")
    wann = _zeit_text(v.get("beendet"), jetzt) if v.get("beendet") else ""
    if wann:
        teile.append(wann)
    tipp = "%s · %.2f s" % (methode, v.get("dauer_s") or 0)
    if paket:
        tipp += " · Paket %d/%d" % paket
    if v.get("zugriff"):
        tipp += " · %s" % v["zugriff"]
    return " · ".join(teile), tipp


def _auftrag_symbol(v):
    """Das Symbol einer Zeile der Auftragsliste: Warnung, wenn es nicht
    geklappt hat, sonst das des Werkzeugs (K9)."""
    if not v.get("ok"):
        return SCHRITT_SYMBOL_FEHLER
    return _schritt_symbol(v.get("methode") or "?")


def _modellwahl(feld):
    """Der gewaehlte Modellname — aus der Liste ODER von Hand getippt.

    `currentData()` liefert bei einem beschreibbaren Feld None, sobald der Nutzer
    selbst etwas eintippt. Ohne diese Unterscheidung ginge der getippte Name
    still verloren und es liefe die Vorgabe — genau die Art Fehler, die man
    erst merkt, wenn die Antwort komisch klingt.
    """
    text = (feld.currentText() or "").strip()
    if text == MODELLE_EINTRAG:
        return None
    for i in range(feld.count()):
        if feld.itemText(i) == text:
            return feld.itemData(i)
    return text or None


def _chat_zeichnen(z):
    """Der Chat im Qt-Takt. Liest NUR, was der Leserthread hinterlegt hat.

    Neu gezeichnet wird erst, wenn sich der Stand geaendert hat
    (`_chat_zeichenstand`) — sonst baute der 500-ms-Takt die Liste dauernd
    neu und das Scrollen spraenge dem Nutzer unter den Fingern weg.
    """
    w = z["w"]
    # VOR dem Ersatz-Return: auch ohne Chat-Tab kann ein Chat laufen (aus der
    # Fassung vor einem Update), und "nach dem Zug beenden / trennen" muss
    # dann trotzdem eingeloest werden (`_nach_zug_einloesen`).
    _nach_zug_einloesen(z)
    _chatknopf_zeigen(z)
    _einst_freigabe_zeigen(z)
    if CHAT_TAB not in w:
        return            # Ersatz-Tab (`_tab_chat_oder_ersatz`): nichts zu tun
    C = _chat_modul()
    chat = z.setdefault("chat", {})
    d = z.get("dienst")
    verbunden = d is not None and not d.beenden and d.zustand != "stopped"
    an = bool(chat.get("an"))
    veraltet = _chat_veraltet()

    _modelle_uebernehmen(z)
    # Ergebnisse der Nebenthreads (Tresor, lokale Programme) — nur lesen.
    _schluessel_takt(z)
    _lokal_takt(z)
    _wer_zeigen(z)
    try:
        gewaehlt = _gewaehlter_anbieter(z)
    except Exception:                                  # noqa: BLE001
        gewaehlt = {}
    _art_zeigen(z, chat, an, gewaehlt)
    # Senden startet seit S8 auch den Chat — also auch ohne laufenden Chat
    # und ohne Verbindung bedienbar: dann sagt die Fehlerzeile, was fehlt.
    # Nur eine unpassende Fassung sperrt (dort startet nie ein Chat).
    w["chat_senden"].setEnabled(an or not veraltet)
    # Laeuft noch ein Chat einer ALTEN Fassung (Update ohne Neustart), liest
    # er den Modus nicht (er kennt nur die alte Freigabestufe): dann ist der
    # Knopf aus und sagt es (Entscheid 2026-09-27).
    alt_an = bool(veraltet and an)
    if w["chat_modus"].isEnabled() == alt_an:
        w["chat_modus"].setEnabled(not alt_an)
        if alt_an:
            w["chat_modus"].setToolTip(veraltet)
        else:
            _modus_zeigen(z)
    _modell_knopf_zeigen(z)
    _anhaenge_takt(z)
    w["chat_ende"].setVisible(an)
    # "Neuer Chat" nie mitten im Zug (dann "Beenden", mit Rueckfrage).
    w["chat_neu"].setEnabled(not C.laeuft_zug(chat))
    cli = gewaehlt.get("art") == "cli"
    # Endet ein Chat, steht er jetzt in der Liste (S9).
    if z.get("chat_war_an") and not an:
        _liste_auffrischen(z)
    z["chat_war_an"] = an
    fertig = z.pop("verlauf_neu", None)
    if fertig is not None:
        chat["stand"] = chat.get("stand", 0) + 1   # alter Verlauf ist da
    _kontext_zeigen(z, chat, an)
    for schluessel in ("chat_modell", "chat_stufe", "chat_anbieter",
                       "chat_basis", "chat_schluessel"):
        w[schluessel].setEnabled(not an)      # Wechsel nur zwischen Chats
    # Entscheid 2026-09-26: mitten im Chat gesperrt. Der Hinweis "gilt ab
    # dem nächsten Chat" steht seit 2026-09-28 in den Aufklappern (Modell,
    # Ordner) und im Tooltip, nicht mehr als Zeile unter der Leiste.
    meldung = z.get("chat_meldung")
    if meldung and meldung[1] == "verbinden" and verbunden:
        _chat_fehler_quittieren(z)            # stimmt nicht mehr
    kurz = chat.get("kurzname") or "Claude"

    # Die bisherigen Chats (S9): geholt im Nebenthread, nur solange kein
    # Chat laeuft; ohne Arbeitsordner hoechstens alle ORDNER_NACHFRAGE_S
    # gefragt (`_ordner_nachfragen`), nicht in jedem Takt. Sichtbar nur, wo
    # sonst der leere Verlauf stuende.
    liste = chat.get("ereignisse")
    verworfen = liste is not None and liste is z.get("verlauf_verworfen")
    # Ein geoeffneter Chat aus der Liste gilt nur vor dem Start und nur bei
    # Claude Code: `_chat_starten` und `_anbieter_gewechselt` setzen ihn
    # zurueck, `_sitzung_oeffnen` oeffnet nichts waehrend eines Chats.
    offen = z.get("sitzung_offen")
    # Erster Kontakt (2026-09-29): ist noch nichts eingerichtet, steht
    # statt des leeren Verlaufs (und statt der Liste) die Karte.
    einstieg = _einstieg_takt(z, an, verworfen or not liste, offen, veraltet)
    _liste_takt(z, cli and not an,
                cli and not an and offen is None
                and (verworfen or not liste) and not einstieg)
    _einstieg_zeigen(z, einstieg)

    # -- Laufende Antwort und Arbeitsanzeige -------------------------------
    # BEWUSST VOR dem frueh-return: die Punkte muessen sich auch bewegen,
    # wenn sich an den Daten nichts aendert. Zwischen Werkzeugstart und
    # -ende schweigt der Strom gemessen bis zu 22 s — die Bewegung kann
    # also nicht aus den Daten kommen, sie muss von hier kommen.
    laufend = _laufend_kurz(chat.get("laufender_text"))
    if w["chat_laufend"].text() != laufend:      # setText nur bei Aenderung
        w["chat_laufend"].setText(laufend)
    w["chat_laufend"].setVisible(bool(laufend))
    if laufend:
        _hoehe_nach_inhalt(w["chat_laufend"], w["chat_laufend"],
                           LAUFEND_MIN_HOEHE, LAUFEND_MAX_HOEHE, laufend)
    if not w["chat_freigabe"].isHidden():
        _hoehe_nach_inhalt(w["chat_freigabe"], w["chat_freigabe"].widget(),
                           FREIGABE_MIN_HOEHE, FREIGABE_MAX_HOEHE,
                           z.get("freigabe_marke") or 0)

    # Arbeitet die KI (und schreibt nicht gerade sichtbar), steht im
    # Verlauf an der Stelle der naechsten Antwort ein "…" (Feinschliff
    # 2026-09-28, statt der Zeile "arbeitet." unter dem Gespraech); was sie
    # tut, sagt sein Tooltip.
    tippt = None
    if an and C.laeuft_zug(chat) and not laufend:
        if C.offene_freigaben(chat):
            tippt = "wartet auf deine Freigabe"
        elif chat.get("denkt"):
            marke = chat.get("denk_tokens")
            tippt = "%s denkt nach%s" % (
                kurz, (" (~%d Token)" % marke) if marke else "")
        else:
            tippt = "%s arbeitet" % kurz

    # Der Verlauf hat seine eigene Marke (Zeitangaben, Paketlauf) und
    # zeichnet nur, was sich geaendert hat — deshalb VOR dem frueh-return.
    _verlauf_zeigen(z, chat, liste, verworfen, offen, tippt)

    stand = _chat_zeichenstand(chat, verbunden, an, veraltet)
    if stand == z.get("chat_gezeigt"):
        return

    if not verbunden:
        w["chat_lage"].setText("Zuerst verbinden — der Chat arbeitet in "
                               "der Cadwork-Datei dieser Verbindung.")
    elif an:
        teile = [chat.get("modell") or "Modell folgt"]
        # Ehrlich sagen, ob Claude Cadwork ueberhaupt bedienen kann — ohne
        # die Werkzeuge kann er reden, aber weder zeichnen noch den
        # Briefkasten lesen.
        teile.append("Cadwork-Werkzeuge: %s"
                     % ("ja" if chat.get("werkzeuge_da") else "NEIN"))
        # Ohne eingehaengtes Fachwissen kennt der Server nur die
        # cwapi3d-Stolperfallen, nicht die Regeln des Projekts.
        if chat.get("werkzeuge_da"):
            teile.append("Fachwissen: %s"
                         % ("ja" if chat.get("wissen") else "nein"))
        # Die Sitzungskennung steht seit S5 in den Technik-Details (⚙):
        # fuer den Chat selbst ist sie Technik, kein Inhalt.
        if chat.get("beenden_nach_zug"):
            teile.append("endet nach diesem Zug")
        w["chat_lage"].setText("läuft · " + " · ".join(teile))
    elif offen is not None:
        w["chat_lage"].setText(
            "«%s» · %s" % (_kurz_text(offen.get("titel"), 60),
                           "lädt den Verlauf …"
                           if offen.get("ereignisse") is None else
                           LISTE_BELEGT if offen.get("belegt") else
                           "die nächste Nachricht setzt diesen Chat fort"))
    else:
        w["chat_lage"].setText("bereit — die erste Nachricht startet den "
                               "Chat")
    # "Neuer Chat" hat die Anzeige geleert (`verworfen`, oben): diese Liste
    # nicht mehr zeigen, auch wenn ein Nachzuegler des beendeten Chats noch
    # hineinschreibt.
    gestorben = None
    if chat.get("fehler") and not verworfen and offen is None:
        w["chat_lage"].setText("Störung: %s" % chat["fehler"])
    elif offen is None and _ohne_antwort_gestorben(z, chat, an, liste,
                                                   verworfen):
        # Startet das CLI gar nicht — der haeufigste Fall: ein Modellname,
        # den es nicht kennt —, kam bisher NICHTS an. Kein `result`, keine
        # Zeile, ein toter Chat ohne Wort. Jetzt steht der Grund hier und
        # an der Eingabe, und der Text steht wieder im Feld.
        grund = C.letzter_fehler(chat)
        if grund:
            text = "Claude Code startet nicht: %s" % grund
            gestorben = text
            w["chat_lage"].setText(text)
            _start_gescheitert_melden(z, liste, text)
    if veraltet and not an:
        # Zuletzt, damit es gewinnt: vor dem Neustart startet hier kein Chat.
        w["chat_lage"].setText(veraltet)
    _status_zeigen(z, chat, verbunden, an, veraltet, offen, verworfen,
                   gestorben)

    # -- Freigabe-Karten ---------------------------------------------------
    # Die Karte zeigt den INHALT, nicht nur eine Frage: bei
    # execute_cadwork_command also den Code. Ohne das waere "Erlauben" ein
    # Blindflug.
    lay = w["chat_freigabe_lay"]
    offen = C.offene_freigaben(chat)
    # Hat "Nur lesen" in diesem Zug etwas abgelehnt, steht der Hinweis als
    # erste Karte (Rueckmeldung 2026-09-28) — nur fuer den gezeigten Chat.
    sperre = None
    if not verworfen and z.get("sitzung_offen") is None:
        sperre = _sperre_hinweis(liste, C.modus_von(chat), C)
    # Mit dem Modus: "Für diese Sitzung nicht mehr fragen" steht nur, wo
    # eine Freigabe je Art im Modus etwas bewirkt — ein Wechsel baut die
    # Karten neu.
    marke_k = ([f["id"] for f in offen], C.modus_von(chat),
               sperre and (sperre["schluessel"], tuple(sperre["namen"])))
    if getattr(lay, "_ids", None) != marke_k:
        lay._ids = marke_k
        while lay.count():
            alt = lay.takeAt(0).widget()
            if alt is not None:
                alt.deleteLater()
        w.pop("chat_sperre_knopf", None)
        if sperre:
            lay.addWidget(_sperre_karte(z, sperre))
        for f in offen:
            lay.addWidget(_freigabe_karte(z, f))
        _freigabe_hoehe(z)
        if offen:
            # Eine neue Frage: die erste Karte mit "Erlauben"/"Ablehnen" in
            # den Blick, sobald sie ausgelegt ist (Gegenpruefung Laien-Sicht
            # K12: "Wartet auf deine Freigabe" — und im Chat keine Karte).
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: _sicher(
                lambda: _freigabe_in_sicht(z), "Freigabe zeigen"))
    karten = bool(offen) or bool(sperre)
    w["chat_freigabe"].setVisible(karten)
    mindest = VERLAUF_MIN_HOEHE_KARTE if karten else VERLAUF_MIN_HOEHE
    if w["chat_verlauf"].minimumHeight() != mindest:
        w["chat_verlauf"].setMinimumHeight(mindest)
    # ERST jetzt als gezeichnet merken: scheitert oben etwas, wird es im
    # naechsten Takt erneut versucht, statt als erledigt zu gelten.
    z["chat_gezeigt"] = stand


def _laufendes_paket(z):
    """(k, n) des Paketlaufs, den der Kern gerade ausfuehrt — oder None.

    Zwischen zwei Paketen ist kein Auftrag unterwegs; dann gilt das letzte,
    solange es nicht das letzte des Laufs war. Liest nur den Status."""
    d = z.get("dienst")
    if d is None:
        return None
    try:
        st = d.status() or {}
    except Exception:                                  # noqa: BLE001
        return None
    for feld, nur_offen in (("auftrag", False), ("letzter_auftrag", True)):
        paket = (st.get(feld) or {}).get("paket")
        try:
            k, n = int(paket[0]), int(paket[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not nur_offen or k < n:
            return (k, n)
    return None


def _verlauf_zeigen(z, chat, liste, verworfen, offen, tippt=None):
    """Der Verlauf (K5) — in JEDEM Takt gefragt, gezeichnet nur, wenn sich
    Ereignisse, die Zeitangaben (alle 10 s), der Paketlauf oder "laeuft"
    geaendert haben; auch dann nur die geaenderten Bloecke."""
    ver = z["w"]["chat_verlauf"]
    C = _chat_modul()
    if offen is not None:
        # Ein Chat aus der Liste, noch nicht fortgesetzt: sein alter Verlauf.
        liste = offen.get("ereignisse")
        ereignisse = list(liste or ())
    else:
        ereignisse = [] if verworfen else list(liste or ())
    laeuft = offen is None and not verworfen and bool(chat.get("an")) \
        and C.laeuft_zug(chat)
    paket = _laufendes_paket(z) if laeuft else None
    jetzt = time.time()
    # Eine NEUE Liste gleicher Laenge (der naechste Chat) ist nicht dieselbe
    # wie die alte: deshalb ihre Kennung in der Marke.
    wer = id(liste) if ereignisse else None
    # Ereignisse werden nur angehaengt, nie geaendert: Kennung und Laenge
    # genuegen.
    marke = (wer, len(ereignisse), int(jetzt // 10), paket, laeuft,
             tippt if laeuft else None)
    if getattr(ver, "_n", None) == marke:
        return
    ver._n = marke
    if getattr(ver, "_wer", None) != wer:
        ver._wer = wer
        ver.leeren()                     # ein anderer Chat: von vorn, unten
    ver.setzen(_verlauf_bloecke(ereignisse, jetzt, abo=_chat_im_abo(chat),
                                paket=paket, laeuft=laeuft, C=C,
                                tippt=tippt if laeuft else None))


#: Die eine Zeile ueber dem Gespraech (Feinschliff 2026-09-28): nur wenn
#: etwas nicht stimmt, kurz und ohne Technik; die Einzelheiten im Tooltip
#: und unter ⚙ → Technik-Details.
STATUS_NICHT_VERBUNDEN = "Nicht verbunden"
STATUS_NEU_STARTEN = "Cadwork neu starten"
STATUS_STOERUNG = "Der Chat hat eine Störung"
STATUS_STARTET_NICHT = "Claude Code startet nicht"
STATUS_WERKZEUGE_FEHLEN = "Cadwork-Werkzeuge fehlen"
STATUS_BELEGT = "Läuft gerade in einem anderen Cadwork"
STATUS_ENDET = "Endet nach dieser Antwort"


def _status_text(chat, verbunden, an, veraltet, offen, verworfen,
                 gestorben):
    """-> (kurzer Text, Erklaerung fuer den Tooltip) oder ("", "").

    Rein (P16 prueft jeden Fall ohne Qt). Die Reihenfolge ist die des
    Takts: was den Chat ganz verhindert, zuerst."""
    if veraltet and not an:
        return STATUS_NEU_STARTEN, veraltet
    if not verbunden:
        return STATUS_NICHT_VERBUNDEN, (
            "Der Chat arbeitet in der Cadwork-Datei dieser Verbindung — "
            "zuerst im Monitor verbinden.")
    if offen is not None and offen.get("belegt"):
        return STATUS_BELEGT, LISTE_BELEGT
    if chat.get("fehler") and not verworfen and offen is None:
        return STATUS_STOERUNG, "Störung: %s" % chat["fehler"]
    if gestorben:
        return STATUS_STARTET_NICHT, gestorben
    if an and chat.get("werkzeuge_da") is False:
        return STATUS_WERKZEUGE_FEHLEN, (
            "Der Chat kann antworten, aber Cadwork nicht bedienen: der "
            "Server für die Cadwork-Werkzeuge läuft nicht (Server-Python, "
            "OPEN_MCP_CAD_PYTHON). Einzelheiten in den Chat-Einstellungen "
            "(Zahnrad) unter Technik-Details.")
    if an and chat.get("beenden_nach_zug"):
        return STATUS_ENDET, "Der Chat endet, sobald diese Antwort fertig ist."
    return "", ""


def _status_zeigen(z, chat, verbunden, an, veraltet, offen, verworfen,
                   gestorben=None):
    """Die Statuszeile setzen — sichtbar nur mit Text."""
    lb = z["w"].get("chat_status")
    if lb is None:
        return
    text, tipp = _status_text(chat, verbunden, an, veraltet, offen,
                              verworfen, gestorben)
    if lb.text() != text:
        lb.setText(text)
    tipp = ("%s\n\n%s" % (tipp, z["w"]["chat_lage"].text())).strip() \
        if text else ""
    tipp = _tipp_klartext(tipp) if tipp else ""
    if lb.toolTip() != tipp:
        lb.setToolTip(tipp)
    if lb.isHidden() == bool(text):
        lb.setVisible(bool(text))
    # Das Warnzeichen davor (K9) — nicht bei "Endet nach dieser Antwort".
    zeichen = z["w"].get("chat_status_symbol")
    if zeichen is not None:
        warnt = bool(text) and text != STATUS_ENDET
        if zeichen.isHidden() == warnt:
            zeichen.setVisible(warnt)


def _ohne_antwort_gestorben(z, chat, an, liste, verworfen):
    """Ist Claude Code gestorben, bevor es etwas gesagt hat? -> bool.

    Seit S8 startet die erste Nachricht den Chat, und `senden` haengt sie
    sofort an den Verlauf ("ich"). Bis zur Pruefung Etappe C hiess die
    Bedingung "Verlauf leer" — seit S8 also nie, und der Grund (etwa ein
    unbekannter Modellname) ging verloren. Jetzt: nur eigene Nachrichten
    im Verlauf, stderr hat etwas, und nicht der Nutzer hat beendet
    (`_chat_beenden`) oder die Anzeige verworfen ("Neuer Chat").
    """
    if an or verworfen or not chat.get("stderr"):
        return False
    if liste is not None and liste is z.get("chat_beendet_liste"):
        return False
    # Der alte Verlauf eines fortgesetzten Chats (S9, `alt`) zaehlt nicht:
    # er stammt nicht von diesem Prozess.
    return all(e.get("art") == "ich" for e in (liste or ())
               if not e.get("alt"))


def _start_gescheitert_melden(z, liste, text):
    """Der Grund an der Eingabe — und beim ersten Mal der Text zurueck ins
    (leere) Feld: wie bei jedem gescheiterten Start (S8) bleibt er stehen."""
    alt = z.get("start_gescheitert")
    if alt is not None and alt[0] is liste and alt[1] == text:
        return
    erstmals = alt is None or alt[0] is not liste
    z["start_gescheitert"] = (liste, text)
    _chat_fehler_zeigen(z, text)
    feld = z["w"].get("chat_eingabe")
    if erstmals and feld is not None and not feld.toPlainText().strip():
        eigene = [e.get("text") for e in (liste or ())
                  if e.get("art") == "ich" and e.get("text")
                  and not e.get("alt")]
        if eigene:
            feld.setPlainText(eigene[-1])


def _erste_freigabe(z):
    """Die erste offene Freigabe-Karte (oder None)."""
    lay = z["w"].get("chat_freigabe_lay")
    for i in range(lay.count() if lay is not None else 0):
        karte = lay.itemAt(i).widget()
        if karte is not None and getattr(karte, "knopf_ja", None) is not None:
            return karte
    return None


def _ganz_zu_sehen(teil, wurzel):
    """Steht `teil` ganz sichtbar in `wurzel` — kein Vorfahr versteckt, und
    jeder Vorfahr (Rollbereiche!) laesst sein ganzes Rechteck sehen? -> bool"""
    from PyQt6.QtCore import QRect
    try:
        if not teil.isVisible() or not wurzel.isVisible():
            return False
        r = QRect(teil.mapTo(wurzel, teil.rect().topLeft()), teil.size())
        p = teil.parentWidget()
        while p is not None:
            pr = QRect(p.mapTo(wurzel, p.rect().topLeft()), p.size())
            if not pr.contains(r):
                return False
            if p is wurzel:
                return True
            p = p.parentWidget()
    except RuntimeError:                       # schon abgeraeumt
        return False
    return False


def _freigabe_in_sicht(z):
    """Wartet eine Freigabe und steht der Chat vorn: "Erlauben" und
    "Ablehnen" der ersten Karte in den Blick (Rollbereich der Karten).
    Reicht der Platz dafuer nicht, weil der Hinweis-Bereich offen ist,
    klappt er zu — die Frage der KI geht vor. -> sind beide Knoepfe ganz zu
    sehen?"""
    w = z["w"]
    karte, dock = _erste_freigabe(z), z.get("fenster")
    rolle = w.get("chat_freigabe")
    if karte is None or dock is None or rolle is None \
            or _seite_jetzt(z) != "chat" or w["koerper"].isHidden():
        return False
    knoepfe = (karte.knopf_ja, karte.knopf_nein)

    def zu_sehen():
        for teil in (dock, rolle.widget()):
            if teil.layout() is not None:
                teil.layout().activate()
        rolle.ensureWidgetVisible(karte.knopf_ja, 0, 4)
        return all(_ganz_zu_sehen(k, dock) for k in knoepfe)
    if zu_sehen():
        return True
    if not w["hinweise_bereich"].isHidden():
        _hinweise_zeigen(z, False)
        return zu_sehen()
    return False


def _freigabe_hoehe(z):
    """Der Rollbereich der Karten so hoch wie die Karten (in Grenzen).
    Gerufen, wenn sich die Karten aendern; die neue Marke laesst den Takt
    bei der naechsten Breite nachrechnen."""
    rolle = z["w"]["chat_freigabe"]
    z["freigabe_marke"] = (z.get("freigabe_marke") or 0) + 1
    _hoehe_nach_inhalt(rolle, rolle.widget(), FREIGABE_MIN_HOEHE,
                       FREIGABE_MAX_HOEHE)


def _nach_zug_einloesen(z):
    """Der Wunsch "nach dem Zug beenden" (und das Trennen, das auf ihn wartet).

    Eingeloest HIER, im Qt-Takt — nicht im Leserthread, damit das
    Abraeumen nie mitten im Pipe-Lesen passiert.

    Bis 2026-09-25 stand das hinter dem Ersatz-Return von `_chat_zeichnen`:
    mit dem Ersatz-Tab (`_tab_chat_oder_ersatz`) und einem noch laufenden
    Chat wurde es nie eingeloest — der Chat lief weiter, und das Trennen,
    das der Nutzer mit "Nach dem Zug beenden" angestossen hatte, geschah
    nie.

    Ohne Chat-Tab gibt es auch keine Freigabe-Karten. Wartet der Zug auf
    eine Freigabe, kann er dort nie fertig werden; dann gilt er als beendet
    und der Chat geht jetzt. Unbeantwortete Freigaben werden beim Beenden
    verworfen (Chat) bzw. gelten als abgelehnt (Schleife) — ausgefuehrt
    wird davon nichts.
    """
    chat = z.get("chat") or {}
    if not (chat.get("beenden_nach_zug") and chat.get("an")):
        return
    C = _chat_modul()
    if C.laeuft_zug(chat):
        ersatz = CHAT_TAB not in z["w"]
        if not (ersatz and C.offene_freigaben(chat)):
            return                            # der Zug darf fertig werden
    chat["beenden_nach_zug"] = False
    _chat_beenden(z)
    # Wollte der Nutzer eigentlich TRENNEN und hat nur "nach dem Zug" gewaehlt,
    # wird das jetzt nachgeholt — sonst haette sein Klick nichts bewirkt.
    if z.get("trennen_nach_chat"):
        z["trennen_nach_chat"] = False
        _trennen(z)


def _chat_zeichenstand(chat, verbunden, an, veraltet):
    """Woran `_chat_zeichnen` erkennt, dass sich die Anzeige aendern muss.

    Bis 2026-09-25 war das allein `chat["stand"]` — den hebt nur der Chat
    selbst. Verbinden aendert ihn nicht, und so blieb nach dem Verbinden
    "Zuerst verbinden" stehen, bis irgendein Chat-Ereignis kam. Verbindung,
    laufender Chat und Fassung gehoeren deshalb mit dazu.
    """
    return (chat.get("stand", 0), bool(verbunden), bool(an), veraltet)


def _kurz(wert, n):
    try:
        text = json.dumps(wert, ensure_ascii=False)
    except Exception:                                  # noqa: BLE001
        text = str(wert)
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


# --- Hinweis "Nur lesen hat abgelehnt" (Rueckmeldung 2026-09-28) -----------
# Die KI bekam nur "nicht erneut versuchen", der Nutzer sah eine graue Zeile
# "abgelehnt" in den Schritten. Jetzt steht ueber der Eingabe eine Karte mit
# dem, was die KI wollte, und EIN Knopf, der den Modus wechselt — er fuehrt
# nichts aus; die KI versucht es erst, wenn der Nutzer wieder schreibt.
SPERRE_MODUS = "nur_lesen"
SPERRE_ZIEL = "fragen"
SPERRE_KNOPF = "Zu «Fragen» wechseln"
SPERRE_NAMEN_MAX = 3


def _schritt_name(werkzeug, eingabe=None, C=None):
    """Der Alltagsname eines Werkzeugs ohne Zeichen davor ("Arbeitet in
    Cadwork", "Datei geschrieben")."""
    text = _schritt_text(werkzeug, eingabe, None, C)
    i = 0
    while i < len(text) and not text[i].isalnum():
        i += 1
    return text[i:] or text


def _sperre_hinweis(ereignisse, modus, C=None):
    """Was "Nur lesen" im LAUFENDEN Zug (seit der letzten eigenen Nachricht)
    ohne Frage abgelehnt hat. -> None oder {"schluessel", "namen", "lesen"}.

    Rein (test_a_prototyp P17). Nur im Modus "Nur lesen": wechselt der
    Nutzer, ist der Hinweis erledigt. `lesen`: alles Abgelehnte waere ein
    Lesen gewesen, nur ausserhalb des Arbeitsordners."""
    if modus != SPERRE_MODUS:
        return None
    liste = list(ereignisse or ())
    start = 0
    for i in range(len(liste) - 1, -1, -1):
        if liste[i].get("art") == "ich":
            start = i + 1
            break
    namen, letzter, lesen = [], None, True
    for i in range(start, len(liste)):
        e = liste[i]
        if e.get("art") != "verweigert" or e.get("alt"):
            continue
        letzter = i
        name = _schritt_name(e.get("werkzeug"), e.get("eingabe"), C)
        if name not in namen:
            namen.append(name)
        if C is None or C.werkzeug_art(e.get("werkzeug")) != "lesen":
            lesen = False
    if letzter is None:
        return None
    return {"schluessel": (id(ereignisse), letzter), "namen": namen,
            "lesen": lesen}


def _sperre_text(h):
    """Der Satz der Karte (rein, P17)."""
    namen = list(h.get("namen") or ())
    mehr = len(namen) - SPERRE_NAMEN_MAX
    was = ", ".join(namen[:SPERRE_NAMEN_MAX])
    if mehr > 0:
        was += " und %d weitere" % mehr
    tat = ("ausserhalb des Arbeitsordners lesen" if h.get("lesen")
           else "etwas ändern")
    return ("Die KI wollte %s (%s). Im Modus «Nur lesen» ist das gesperrt."
            % (tat, was))


def _sperre_karte(z, h):
    """Die Karte zum Hinweis — mit dem einen Knopf, der den Modus wechselt
    (und sonst nichts: kein Aufruf wird wiederholt)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
    rahmen = QWidget()
    rahmen.setObjectName("sperrkarte")
    rahmen.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    rl = QVBoxLayout(rahmen)
    rl.setContentsMargins(10, 8, 10, 8)
    rl.setSpacing(6)
    text = QLabel(_sperre_text(h))
    text.setObjectName("sperre_text")
    text.setTextFormat(Qt.TextFormat.PlainText)
    text.setWordWrap(True)
    rl.addWidget(text)
    reihe = QHBoxLayout()
    knopf = QPushButton(SPERRE_KNOPF)
    knopf.setObjectName("primaer")
    knopf.setToolTip("Ab dem nächsten Schritt fragt die KI vor jeder "
                     "Änderung. Wiederholt wird nichts — schreib ihr, "
                     "wenn sie es jetzt tun soll.")
    knopf.clicked.connect(lambda: _sicher(
        lambda: _sperre_wechseln(z), "Zu Fragen wechseln"))
    reihe.addWidget(knopf)
    reihe.addStretch(1)
    rl.addLayout(reihe)
    z["w"]["chat_sperre_knopf"] = knopf
    return rahmen


def _sperre_wechseln(z):
    """Der Knopf der Karte: NUR von «Nur lesen» nach «Fragen» — steht der
    Chat schon in einem anderen Modus (die Karte ist noch nicht neu
    gezeichnet), aendert er nichts. Er beantwortet keine Karte und
    wiederholt keinen Aufruf. -> gewechselt?"""
    C = _chat_modul()
    if _modus_wirksam(z, C) != SPERRE_MODUS:
        return False
    return _modus_waehlen(z, SPERRE_ZIEL)


def _freigabe_karte(z, f):
    """Eine Karte: was will Claude tun, mit aufklappbarem Wortlaut."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                                 QPushButton, QVBoxLayout, QWidget)
    C = _chat_modul()
    rahmen = QWidget()
    # objectName statt setStyleSheet: ein Stylesheet direkt auf diesem
    # Widget vererbt sich auf JEDES Kind — im Sichttest bekam dadurch jedes
    # Label seinen eigenen orangen Rahmen und die Karte war unleserlich.
    # Die Regeln stehen jetzt zentral im QSS unter #freigabekarte.
    rahmen.setObjectName("freigabekarte")
    # Ein nacktes QWidget zeichnet seinen Stylesheet-Hintergrund nur mit
    # diesem Attribut — sonst bliebe die Karte weiss.
    rahmen.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    rl = QVBoxLayout(rahmen)
    rl.setContentsMargins(10, 8, 10, 8)
    rl.setSpacing(6)

    titel = QLabel("%s möchte <b>%s</b> ausführen" % (
        (z.get("chat") or {}).get("kurzname") or "Claude", f.get("name") or "?"))
    titel.setObjectName("freigabe_titel")
    titel.setWordWrap(True)
    rl.addWidget(titel)
    # Der WORTLAUT zuerst, gross und lesbar — das ist der Befehl bzw. der
    # Cadwork-Code. `beschreibung` ist nur Claudes eigene Zusammenfassung
    # ("Show last 3 commits"); die darf nicht der lesbarste Teil der Karte
    # sein, sonst gibt der Nutzer etwas frei, das er nie gesehen hat.
    eingabe0 = f.get("eingabe") or {}
    kurz = (eingabe0.get("command") or eingabe0.get("code")
            or eingabe0.get("pattern") or eingabe0.get("file_path") or "")
    if kurz:
        zeile = QLabel(_kurz_text(kurz, KARTE_WORTLAUT_ZEICHEN))
        zeile.setObjectName("freigabe_wortlaut")
        zeile.setWordWrap(True)
        rl.addWidget(zeile)
    if f.get("beschreibung"):
        neben = QLabel(_kurz_text(f["beschreibung"],
                                  KARTE_BESCHREIBUNG_ZEICHEN))
        neben.setObjectName("neben")
        neben.setWordWrap(True)
        neben.setToolTip(str(f["beschreibung"]))
        rl.addWidget(neben)

    # Die Knoepfe gleich unter dem, was freigegeben wird — VOR dem
    # aufklappbaren Wortlaut: aufgeklappt schob der sie sonst aus dem
    # Kartenbereich (Pruefung Etappe C).
    reihe = QHBoxLayout()
    reihe.setSpacing(8)
    ja = QPushButton("Erlauben")
    ja.setObjectName("primaer")
    nein = QPushButton("Ablehnen")
    # Fuer `_freigabe_in_sicht`: diese Knoepfe muessen zu sehen sein.
    rahmen.knopf_ja, rahmen.knopf_nein = ja, nein
    # Ueber `_sicher`: ein Fehler beim Beantworten (etwa eine Pipe, die eben
    # zuging) darf nicht aus dem Qt-Slot laufen — in Cadwork endet das in
    # qFatal (L43). Er steht dann auf stderr.
    ja.clicked.connect(lambda: _sicher(
        lambda: C.freigabe_beantworten(z["chat"], f["id"], True), "Erlauben"))
    nein.clicked.connect(lambda: _sicher(
        lambda: C.freigabe_beantworten(z["chat"], f["id"], False), "Ablehnen"))
    reihe.addWidget(ja)
    reihe.addWidget(nein)
    reihe.addStretch(1)
    rl.addLayout(reihe)
    # "Fragen" und (fuer das Aeussere) "Cadwork frei": einmal je Art bis zur
    # naechsten Nachricht — oder, mit diesem Knopf, bis der Chat endet
    # (Wunsch 2026-09-27). Gezeigt nur, wo eine Freigabe laut der POLITIK
    # etwas bewirkt: nicht bei einem Aufruf AUS dem Ordner heraus
    # (`draussen` fragt jedes Mal), der Knopf versprache sonst Falsches.
    werkzeug_f = f.get("werkzeug")
    anfrage_f = {"blocked_path": True} if f.get("draussen") else None
    if (werkzeug_f
            and C.chat_entscheiden(z.get("chat"), werkzeug_f,
                                   anfrage_f) == "fragen"
            and C.entscheiden(C.modus_von(z.get("chat")), werkzeug_f,
                              anfrage_f, {werkzeug_f}) == "ja"):
        immer = QPushButton("Für diese Sitzung nicht mehr fragen")
        immer.setObjectName("leiste")
        immer.setToolTip("Erlaubt diesen Aufruf und jeden weiteren von %s, "
                         "bis der Chat endet." % (f.get("name") or "dieser Art"))
        immer.clicked.connect(lambda: _sicher(
            lambda: C.freigabe_beantworten(z["chat"], f["id"], True,
                                           sitzung=True),
            "Für diese Sitzung erlauben"))
        rl.addWidget(immer)

    # Der Wortlaut: bei execute_cadwork_command ist das der Code. Zugeklappt,
    # damit die Karte schmal bleibt — aber vorhanden, weil sonst niemand
    # weiss, wozu er Ja sagt.
    eingabe = f.get("eingabe") or {}
    wortlaut = eingabe.get("code") or eingabe.get("command") or _kurz(eingabe, 4000)
    details = QPlainTextEdit(str(wortlaut))
    details.setReadOnly(True)
    details.setMaximumHeight(150)
    details.hide()
    mehr = QPushButton("Wortlaut zeigen")
    mehr.setObjectName("neben")

    def umschalten():
        sichtbar = details.isHidden()
        details.setVisible(sichtbar)
        mehr.setText("Wortlaut verbergen" if sichtbar else "Wortlaut zeigen")
        if "chat_freigabe" in z["w"]:
            _freigabe_hoehe(z)            # der Wortlaut braucht Platz

    mehr.clicked.connect(lambda: _sicher(umschalten, "Wortlaut zeigen"))
    rl.addWidget(mehr)
    rl.addWidget(details)
    return rahmen


def _post_zeichnen(z, post):
    """Die Notizen des Briefkastens als Protokoll (K11): je Notiz eine
    Zeile mit Zeit und Zustand als Chip ("wartet" orange, "abgeholt"
    gruen, ueber `_pille_stil`), darunter der Text; aeltere oben, neue
    unten. Neu gebaut nur, wenn sich Nummern oder Zustaende aendern
    (`_stempel`), danach ganz nach unten gerollt. -> neu gebaut?"""
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
    lp = z["w"]["post_verlauf"]
    stempel = tuple((n["nr"], n["abgeholt"]) for n in post)
    if getattr(lp, "_stempel", None) == stempel:
        return False
    lp._stempel = stempel
    zeilen = lp.widget().layout()
    while zeilen.count() > 1:                  # der Stretch bleibt unten
        alt = zeilen.takeAt(0).widget()
        if alt is not None:
            alt.setParent(None)
            alt.deleteLater()
    for i, n in enumerate(post):
        zeile = QWidget()
        zeile.setObjectName("protokoll_zeile")
        zeile.setProperty("ungerade", "ja" if i % 2 else "nein")
        zeile.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        zl = QVBoxLayout(zeile)
        zl.setContentsMargins(6, 4, 6, 5)
        zl.setSpacing(2)
        kopf = QHBoxLayout()
        kopf.setSpacing(6)
        zeit = QLabel(_vor_wie_lange(n["zeit"]))
        zeit.setObjectName("protokoll_zeit")
        abgeholt = bool(n["abgeholt"])
        chip = QLabel("abgeholt" if abgeholt else "wartet")
        chip.setObjectName("protokoll_chip")
        chip.setStyleSheet(_pille_stil(FARBEN["gruen"] if abgeholt
                                       else FARBEN["orange"]))
        kopf.addWidget(zeit)
        kopf.addWidget(chip)
        kopf.addStretch(1)
        zl.addLayout(kopf)
        text = QLabel(str(n["text"]))
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        zl.addWidget(text)
        zeilen.insertWidget(zeilen.count() - 1, zeile)

    def ganz_unten():
        try:
            leiste = lp.verticalScrollBar()
            leiste.setValue(leiste.maximum())
        except RuntimeError:                   # schon abgeraeumt
            pass

    # Erst wenn Qt die neuen Zeilen ausgelegt hat, stimmt das Maximum.
    QTimer.singleShot(0, lambda: _sicher(ganz_unten, "Briefkasten rollen"))
    return True


# --- Hinweise und Briefkasten ueberleben den Neustart --------------------
# Rueckmeldung 2026-08-07: "koennen wir einbauen, dass die Hinweise und der
# Briefkasten gespeichert werden ... dass wenn man sie beendet, es nicht
# verloren geht?"
#
# Beides lebt im Plugin-PROZESS (`d.hinweise`, `d.postfach`) und war damit
# nach jedem Neustart weg — das hat heute schon einmal wie ein Anzeigefehler
# ausgesehen, war aber genau das.
#
# Die Ablage liegt NEBEN der Cadwork-Datei: die Notizen gehoeren zu diesem
# Projekt und wandern mit ihm mit. Ist der Ordner nicht beschreibbar
# (Netzlaufwerk, schreibgeschuetzt), weicht sie auf einen festen Ort aus,
# statt still nichts zu tun.
AUSWEICH_ORDNER = r"C:\Users\Public\OpenMcpCad_Notizen"
SPEICHER_TAKT_S = 3.0


def _ablage_pfad(dok_pfad):
    if not dok_pfad:
        return None
    dok_pfad = dok_pfad.replace("/", os.sep)
    ordner = os.path.dirname(dok_pfad)
    name = os.path.basename(dok_pfad) + ".omcad.json"
    if ordner and os.access(ordner, os.W_OK):
        return os.path.join(ordner, name)
    try:
        os.makedirs(AUSWEICH_ORDNER, exist_ok=True)
        return os.path.join(AUSWEICH_ORDNER, name)
    except OSError:
        return None


def _dokumentpfad_anfordern(z):
    """Fragt den Pfad ueber die WARTESCHLANGE ab — nie direkt cwapi3d.

    Der Auftrag traegt keine Client-Kennung; niemand wartet auf ihn. Wir
    behalten aber das Job-Objekt und lesen sein Ergebnis spaeter im
    Qt-Takt aus. So bleibt die Regel gewahrt: cwapi3d ausschliesslich im
    Cadwork-Hauptthread, ausschliesslich ueber die Queue.
    """
    d, kern = z["dienst"], z["kern"]
    if d is None or d.beenden or kern is None or z.get("pfad_job") is not None:
        return
    code = ("import utility_controller as uc\n"
            "result = str(uc.get_3d_file_path())\n")
    params = {"code": code, "access_mode": "read",
              "description": "Ablageort der Notizen bestimmen"}
    meta = kern.AuftragsMeta("execute_cwapi3d",
                             dict(params, client_label="Open MCP CAD A"))
    job = kern.Job(None, "execute_cwapi3d", params, meta)
    z["pfad_job"] = job
    d.job_queue.put(job)


def _notizen_laden(z, pfad):
    """Einmal je Dokument: gespeicherte Hinweise und Nachrichten zurueck."""
    d = z["dienst"]
    if d is None:
        return
    try:
        with open(pfad, "r", encoding="utf-8") as fh:
            daten = json.load(fh)
    except (OSError, ValueError):
        return
    with d.sperre:
        vorhanden_h = {h["nr"] for h in d.hinweise}
        for h in daten.get("hinweise", []):
            if h.get("nr") not in vorhanden_h:
                d.hinweise.append(h)
        vorhanden_n = {n["nr"] for n in d.postfach}
        for n in daten.get("postfach", []):
            if n.get("nr") not in vorhanden_n:
                d.postfach.append(n)
        # Zaehler mitziehen, sonst vergibt der Kern Nummern doppelt und
        # "Erledigt" trifft plötzlich den falschen Hinweis.
        d.hinweise.sort(key=lambda h: h.get("nr") or 0)
        d.postfach.sort(key=lambda n: n.get("nr") or 0)
        if d.hinweise:
            d.hinweis_zaehler = max(d.hinweis_zaehler,
                                    max(h.get("nr") or 0 for h in d.hinweise))
        if d.postfach:
            d.nachricht_zaehler = max(d.nachricht_zaehler,
                                      max(n.get("nr") or 0
                                          for n in d.postfach))


def _notizen_sichern(z):
    """Schreibt, wenn sich etwas geaendert hat — hoechstens alle paar Sekunden."""
    d, pfad = z["dienst"], z.get("ablage")
    if d is None or not pfad:
        return
    jetzt = time.time()
    if jetzt - z.get("zuletzt_gesichert", 0) < SPEICHER_TAKT_S:
        return
    with d.sperre:
        hinweise = [dict(h) for h in d.hinweise]
        postfach = [dict(n) for n in d.postfach]
        zaehler = (d.hinweis_zaehler, d.nachricht_zaehler)
    stempel = (len(hinweise), len(postfach), zaehler,
               tuple((h["nr"], h.get("status"), h.get("gelesen"))
                     for h in hinweise),
               tuple((n["nr"], n.get("abgeholt")) for n in postfach))
    if stempel == z.get("speicher_stempel"):
        return
    try:
        with open(pfad, "w", encoding="utf-8") as fh:
            # default=str: der Briefkasten traegt Cadwork-Objekte im
            # Kontext (Facettenlisten), die kein JSON kennen. Lieber als
            # Text ablegen als die ganze Datei verlieren.
            json.dump({"dokument": z.get("dok_pfad"),
                       "gespeichert": jetzt,
                       "hinweise": hinweise, "postfach": postfach,
                       "hinweis_zaehler": zaehler[0],
                       "nachricht_zaehler": zaehler[1]},
                      fh, ensure_ascii=False, indent=1, default=str)
        z["speicher_stempel"] = stempel
        z["zuletzt_gesichert"] = jetzt
    except OSError:
        z["zuletzt_gesichert"] = jetzt      # nicht bei jedem Takt neu scheitern


def _ablage_pflegen(z):
    """Im Qt-Takt: Pfad holen, einmalig laden, danach regelmaessig sichern."""
    d = z["dienst"]
    if d is None or d.beenden:
        return
    job = z.get("pfad_job")
    if job is not None and job.event.is_set():
        z["pfad_job"] = None
        antwort = job.response or {}
        pfad = (antwort.get("result") or {}).get("result") \
            if antwort.get("ok") else None
        if pfad:
            z["dok_pfad"] = pfad
            z["ablage"] = _ablage_pfad(pfad)
            if z["ablage"] and z.get("geladen_fuer") != pfad:
                z["geladen_fuer"] = pfad
                _notizen_laden(z, z["ablage"])
    elif job is None and not z.get("ablage"):
        _dokumentpfad_anfordern(z)
    _notizen_sichern(z)


def _monitor_starten(z):
    """EIN Hintergrundthread fuer alle vier Steckplaetze — genau einer.

    WARUM EIN THREAD UND NICHT DER QT-TAKT
    Eine Statusabfrage kostet im schlimmsten Fall den Timeout. Im 500-ms-Takt
    des Qt-Timers waere das Cadworks Hauptthread — und ein toter Port wuerde
    die Oberflaeche anhalten. Der Thread schreibt nur Daten; gezeichnet wird
    ausschliesslich im Qt-Takt (`_verbindungen_zeichnen`). Kein Widget wird
    je aus dem Thread angefasst.

    WARUM NUR EINER
    Der Einstieg laedt dieses Modul bei jedem Plugin-Klick neu. Ohne die
    Pruefung unten haette man nach fuenf Klicks fuenf Threads, die alle vier
    Steckplaetze im Sekundentakt befragen.
    """
    alt = z.get("monitor")
    if alt is not None and alt.is_alive() and z.get("monitor_an"):
        return
    # Nach dem "×" (`_fenster_schliessen`) kann der alte noch schlafen: er
    # endet an seiner Marke, ein neuer uebernimmt.
    client = _verbindungen_client()
    marke = object()
    z["monitor_marke"] = marke
    z["monitor_an"] = True

    def schleife():
        while z.get("monitor_an") and z.get("monitor_marke") is marke:
            try:
                # Nur ZUWEISEN, nie an Widgets ruehren. Eine Zuweisung ist
                # unter der GIL atomar — der Qt-Takt sieht entweder den
                # alten oder den neuen Stand, nie einen halben.
                z["monitor_daten"] = client.alle_status()
            except Exception:                          # noqa: BLE001
                pass
            time.sleep(1.0)

    t = threading.Thread(target=schleife, name="Open-MCP-CAD-A-Monitor",
                         daemon=True)          # daemon: haelt Cadwork nie fest
    t.start()
    z["monitor"] = t


def _teil_verbindungen(z, lay):
    """Die VERBUNDENEN Steckplaetze als Karten, dazu die Wahl fuer dieses Cadwork.

    Rueckmeldung 2026-09-21: Karten NUR fuer das, was gerade verbunden ist; das
    Dropdown bietet ALLE Ports zur Auswahl. Vorher standen sechs feste
    Karten A-F da, meist "Aus", und alles jenseits von F nur als Textzeile
    "Zusaetzlich aktiv" — die Anzeige zeigte die Plugin-Ordner von
    frueher, nicht die Verbindungen von jetzt.

    Seit S5 (2026-09-26) eine Karte der Einstellungsseite statt eines Tabs.
    """
    from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

    # -- Welchen Steckplatz nimmt DIESES Cadwork? --------------------------
    # Rueckmeldung 2026-08-15: "man soll auswaehlen koennen welche bridge man
    # verbinden will". "Automatisch" bleibt die Vorgabe; die Liste enthaelt
    # JEDEN Port des Kerns, nicht nur die benannten A-F.
    # Seit der Gegenpruefung Laien-Sicht K12 in den Technik-Details (setzt
    # `_einstellungen_bauen` dort ein, auf und zu mit ihnen): "Steckplatz"
    # und "Port" sagen einem Zimmermann nichts.
    from PyQt6.QtWidgets import QWidget
    reihe_teil = QWidget()
    reihe_w = QHBoxLayout(reihe_teil)
    reihe_w.setContentsMargins(0, 0, 0, 0)
    reihe_w.setSpacing(6)
    lbl_w = QLabel("Steckplatz")
    lbl_w.setObjectName("neben")
    wahl = QComboBox()
    wahl.addItem("automatisch (erster freier)", None)
    for instanz, port in _alle_steckplaetze(_verbindungen_client(),
                                            _kern_fuer_anzeige(z)):
        wahl.addItem("%s · Port %d" % (instanz, port), instanz)
    wahl.setToolTip("Wirkt beim nächsten Verbinden. Ist der gewählte "
                    "Steckplatz belegt, wird NICHT ausgewichen — sonst "
                    "zeichnete man in eine andere Datei als gemeint.")
    reihe_w.addWidget(lbl_w)
    reihe_w.addWidget(wahl, 1)
    reihe_teil.hide()
    z["w"]["steckplatz_wahl"] = wahl
    z["w"]["steckplatz_reihe"] = reihe_teil

    kopf = QLabel("Wird abgefragt …")
    kopf.setObjectName("neben")
    kopf.setWordWrap(True)
    lay.addWidget(kopf)

    # Die Karten entstehen zur Laufzeit in `_verbindungen_zeichnen` — hier
    # nur ihr Platz.
    karten_lay = QVBoxLayout()
    karten_lay.setSpacing(8)
    lay.addLayout(karten_lay)

    z["w"]["verb_kopf"] = kopf
    z["w"]["verb_karten_lay"] = karten_lay
    z["w"]["verb_karten"] = {}


def _kern_fuer_anzeige(z):
    """Der Kern, dessen Portbereich das Dropdown zeigt — oder None.

    Der laufende, sonst ein frisch geladener. Scheitert das Laden, zeigt
    das Dropdown nur die benannten Steckplaetze: ein kaputter Kern soll das
    Dock nicht kosten, das Verbinden meldet ihn ohnehin.
    """
    if z.get("kern") is not None:
        return z["kern"]
    try:
        return z["kern_laden"]() if z.get("kern_laden") else None
    except Exception:                                  # noqa: BLE001
        return None


def _verbindungskarte(z, instanz, port):
    """EINE Karte fuer einen verbundenen Steckplatz. -> (Widget, Teile)."""
    from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                                 QVBoxLayout, QWidget)
    karte, kl = _karte("")
    # In der weissen Karte "Verbindung" grau hinterlegt (keine weisse Karte
    # in der weissen Karte).
    karte.setObjectName("karte_innen")
    z1 = QHBoxLayout()
    z1.setSpacing(8)
    buchstabe = QLabel(instanz)
    buchstabe.setObjectName("titel")
    pille = QLabel("…")
    pille.setObjectName("pille")
    z1.addWidget(buchstabe)
    z1.addWidget(pille)
    z1.addStretch(1)
    knopf_det = QPushButton("Details")
    knopf_det.setObjectName("leiste")
    knopf_det.setFixedHeight(20)
    z1.addWidget(knopf_det)
    kl.addLayout(z1)

    dok = QLabel("Port %d" % port)
    dok.setObjectName("neben")
    dok.setWordWrap(True)
    kl.addWidget(dok)

    auftrag = QLabel("")
    auftrag.setObjectName("neben")
    auftrag.setWordWrap(True)
    auftrag.hide()
    kl.addWidget(auftrag)

    meldung = QLabel("")
    meldung.setObjectName("neben")
    meldung.setWordWrap(True)
    meldung.hide()
    kl.addWidget(meldung)

    # Aktionen liegen im aufklappbaren Bereich — sonst stehen in einem
    # schmalen Dock fuenf Knoepfe nebeneinander und nichts ist lesbar.
    details = QWidget()
    dl = QVBoxLayout(details)
    dl.setContentsMargins(0, 4, 0, 0)
    dl.setSpacing(4)
    technik = QLabel("")
    technik.setObjectName("neben")
    technik.setWordWrap(True)
    dl.addWidget(technik)
    r1 = QHBoxLayout()
    r1.setSpacing(4)
    b_pause = QPushButton("Pausieren")
    b_weiter = QPushButton("Fortsetzen")
    r1.addWidget(b_pause, 1)
    r1.addWidget(b_weiter, 1)
    dl.addLayout(r1)
    r2 = QHBoxLayout()
    r2.setSpacing(4)
    b_nach = QPushButton("Nach Auftrag beenden")
    b_jetzt = QPushButton("Jetzt beenden")
    r2.addWidget(b_nach, 1)
    r2.addWidget(b_jetzt, 1)
    dl.addLayout(r2)
    details.hide()
    kl.addWidget(details)

    k = {"widget": karte, "titel": buchstabe, "pille": pille, "dok": dok,
         "auftrag": auftrag, "meldung": meldung, "details": details,
         "technik": technik, "det_knopf": knopf_det, "pause": b_pause,
         "weiter": b_weiter, "nach": b_nach, "jetzt": b_jetzt, "port": port}
    knopf_det.clicked.connect(
        lambda _c=False, dd=details: dd.setVisible(not dd.isVisible()))
    _steuerung_verbinden(z, port, k)
    return k


def _steuerung_verbinden(z, port, k):
    """Knoepfe an das vorhandene Protokoll haengen — nichts Neues erfinden.

    Adressiert wird ueber den PORT, nicht den Buchstaben: ein Steckplatz
    jenseits von F heisst "26" oder "53200", und die Steuerfunktionen
    kannten bis 2026-09-23 nur A-F (KeyError beim Pausieren).
    """
    client = _verbindungen_client()
    ziel = str(port)

    def im_thread(fn):
        # Steuerbefehle koennen bis STEUER_TIMEOUT_S dauern. Im Qt-Thread
        # waere das ein Einfrieren von Cadwork — also daneben.
        threading.Thread(target=fn, daemon=True).start()

    k["pause"].clicked.connect(
        lambda: im_thread(lambda: client.pausieren(ziel)))
    k["weiter"].clicked.connect(
        lambda: im_thread(lambda: client.fortsetzen(ziel)))
    k["nach"].clicked.connect(
        lambda: im_thread(lambda: client.beenden_nach_auftrag(ziel)))
    k["jetzt"].clicked.connect(
        lambda: im_thread(lambda: client.jetzt_beenden(ziel)))


def _eigener_port(z):
    d = z.get("dienst")
    if d is None or d.beenden:
        return None
    return getattr(getattr(d, "cfg", None), "port", None)


def _verbindungen_zeichnen(z):
    """Laeuft im QT-TAKT und liest nur, was der Thread hinterlegt hat.

    Eine Karte je VERBUNDENEM Steckplatz ("Aus" bekommt keine). Aendert sich
    die Menge, werden die Karten neu gebaut; sonst nur aufgefrischt.
    """
    lay = z["w"].get("verb_karten_lay")
    if lay is None:
        return
    client = _verbindungen_client()
    daten = z.get("monitor_daten")
    # EIN Eintrag je Port. Kam ein Port doppelt (2026-09-24: ein Registry-
    # Eintrag mit fremdem Port und der Kennung "A" wurde beim festen
    # Steckplatz A abgefragt), ergab `soll` nie `list(karten)` — das Dock baute JEDEN
    # Takt neu und liess jedes Mal eine Karte liegen.
    aktiv, gesehen = [], set()
    for d in daten or []:
        if (d.get("zustand") in ("unreachable", None)
                or d.get("port") in gesehen):
            continue
        gesehen.add(d.get("port"))
        aktiv.append(d)
    aktiv.sort(key=lambda d: d.get("port") or 0)

    karten = z["w"]["verb_karten"]
    soll = [d.get("port") for d in aktiv]
    if list(karten) != soll:
        # Das LAYOUT leeren, nicht nur die gemerkten Karten: was immer dort
        # steht, gehoert zu einem frueheren Stand.
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        karten.clear()
        for d in aktiv:
            k = _verbindungskarte(z, d.get("instanz") or "?", d.get("port"))
            lay.addWidget(k["widget"])
            karten[d.get("port")] = k

    eigen = _eigener_port(z)
    for d in aktiv:
        k = karten[d.get("port")]
        zustand = d.get("zustand")
        text, farbe = PILLE.get(zustand, (d.get("zustand_text") or "?",
                                          FARBEN["neben"]))
        if zustand == "no_answer":
            text, farbe = "Keine Antwort", FARBEN["rot"]
        elif zustand == "veraltet":
            text, farbe = "Alte Version", FARBEN["orange"]
        k["pille"].setText(text)
        k["pille"].setStyleSheet("background: %s;" % farbe)
        # Ohne Steckplatz und Port (Gegenpruefung Laien-Sicht K12): die
        # stehen in den Technik-Details (`_verbindungen_technik`).
        k["titel"].setText("Dieses Cadwork" if eigen == d.get("port")
                           else "Anderes Cadwork")
        k["dok"].setText(d.get("dokument") or "—")

        auftrag = d.get("auftrag") or {}
        if auftrag:
            k["auftrag"].setText(
                "%s · %s" % (auftrag.get("beschreibung")
                             or auftrag.get("methode") or "Auftrag",
                             client.dauer_text(auftrag.get("laufzeit_s"))))
            k["auftrag"].show()
        else:
            k["auftrag"].hide()

        meldung = d.get("hinweis") or ""
        if meldung:
            k["meldung"].setText(meldung)
            k["meldung"].setStyleSheet(
                "color: %s; font-size: 11px;"
                % (FARBEN["rot"] if zustand in ("error", "no_answer")
                   else FARBEN["orange"]))
            k["meldung"].show()
        else:
            k["meldung"].hide()

        if not k["technik"].isHidden():
            k["technik"].hide()             # steht in den Technik-Details

        steuerbar = zustand not in ("veraltet", "no_answer")
        for name in ("pause", "weiter", "nach"):
            k[name].setEnabled(steuerbar)
        # Sofort beenden NUR, wenn gerade kein Auftrag laeuft. Die Bridge
        # lehnt es ohnehin ab — der ausgegraute Knopf erspart die Absage.
        k["jetzt"].setEnabled(steuerbar
                              and zustand not in client.BESCHAEFTIGT)

    if daten is None:
        text = "Wird abgefragt …"
    elif not aktiv:
        text = ("Keine Verbindung aktiv. Verbunden wird mit einem Klick auf "
                "„Open MCP CAD“ im jeweiligen Cadwork-Fenster.")
    else:
        text = ("%d Verbindung aktiv" if len(aktiv) == 1
                else "%d Verbindungen aktiv") % len(aktiv)
    z["w"]["verb_kopf"].setText(text)


def _verbindungen_technik(daten):
    """Die Zeilen der Verbindungen fuer die Technik-Details — Steckplatz,
    Port, Zustand, Antwortzeit, Kern (Gegenpruefung Laien-Sicht K12: das
    stand auf den Karten der Verbindung). Rein. -> Liste von Zeilen."""
    zeilen = []
    for d in daten or []:
        if d.get("zustand") in ("unreachable", None):
            continue
        zeilen.append("Steckplatz %s · Port %s · %s · Zustand %s · Antwort "
                      "%s ms · wartend %s · Kern %s" % (
                          d.get("instanz") or "?", d.get("port"),
                          d.get("dokument") or "—", d.get("zustand"),
                          d.get("antwortzeit_ms", "?"),
                          d.get("wartende_auftraege", "?"),
                          d.get("version", "?")))
    return zeilen


def _teil_modus(z, kl):
    """Der Zeichenmodus — seit S5 (2026-09-26) eine Karte der
    Einstellungsseite statt eines Tabs."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider
    regler = QSlider(Qt.Orientation.Horizontal)
    regler.setMinimum(0)
    regler.setPageStep(1)
    regler.setTickPosition(QSlider.TickPosition.TicksBelow)
    regler.setTickInterval(1)
    kl.addWidget(regler)

    marken = QHBoxLayout()
    kl.addLayout(marken)

    beschreibung = QLabel("Erst verbinden.")
    beschreibung.setObjectName("neben")
    beschreibung.setWordWrap(True)
    kl.addWidget(beschreibung)

    z["w"].update(regler=regler, marken=marken, modus_text=beschreibung,
                  modus_marken=[])
    regler.valueChanged.connect(lambda pos: _sicher(
        lambda: _modus_setzen(z, pos), "Zeichenmodus"))


def _modus_setzen(z, pos):
    kern, d = z["kern"], z["dienst"]
    if kern is None or d is None or d.beenden:
        return
    stufen = getattr(kern, "ZEICHENMODI", ())
    if not (0 <= pos < len(stufen)):
        return
    schluessel = stufen[pos]["schluessel"]
    try:
        antwort = kern._worker_methoden(d)["zeichenmodus"](
            {"modus": schluessel})
    except Exception:                              # noqa: BLE001
        return
    # Gemerkt wird nur, was der Nutzer am Regler waehlt: `_auffrischen`
    # stellt den Regler mit blockierten Signalen nach, das kommt hier nie
    # an. Nach dem naechsten Verbinden stellt `_zeichenmodus_wiederherstellen`
    # ihn wieder ein (S4, Entscheid 2026-09-26).
    if (antwort or {}).get("ok"):
        _sicher(lambda: _zeichenmodus_merken(schluessel),
                "Zeichenmodus merken")


# --- Die Arbeitsanzeige (K12, ehemals "Open MCP CAD zeichnet …") ------------
# Rueckmeldung 2026-10-07: "da steht immer 'zeichnet', auch wenn es nicht
# zeichnet — dann kann ja auch etwas stehen wie 'KI denkt nach' oder 'KI
# zeichnet'". Befund: das Fenster baute der KERN, fester Titel, offen bis
# 1,5 s nach IRGENDEINEM Auftrag (auch Lesen); den Chat kennt er nicht. Seit
# Kern 2.19 ruft er einen Haken (`cfg.lauf_anzeige`, `_haken_setzen`), und
# die Anzeige hier sagt, was wirklich geschieht (`_anzeige_zustand`). Sie
# bleibt ein eigenes kleines Fenster (Wunsch des Maintainers: "dass wir ein
# extra Popup dafuer haben, nur dessen UI kann besser werden … vielleicht
# mit unserem Logo"), oben mittig ueber der 3D-Flaeche, ohne Fokus zu
# nehmen. Waehrend eines Auftrags gehoert der Hauptthread dem Auftrag: der
# Haken zeichnet deshalb SOFORT (`repaint()`, ohne Ereignisschleife —
# gemessen auf der echten Windows-Plattform von Qt 6.11: der neue Text
# steht danach auf dem Bildschirm, ohne repaint nicht).

def _haken_setzen(z):
    """Dem laufenden Dienst den Haken der Arbeitsanzeige geben — nur einem
    Kern, der ihn kennt (`LAUF_ANZEIGE_HAKEN`, ab 2.19); einem aelteren
    nicht: dann zeigt er sein eigenes Fenster und das Dock keins (nie zwei).
    -> gesetzt?"""
    d, kern = z.get("dienst"), z.get("kern")
    if d is None or getattr(d, "cfg", None) is None:
        return False
    if not getattr(kern, "LAUF_ANZEIGE_HAKEN", False) \
            or z.get("anzeige") is None:
        return False
    d.cfg.lauf_anzeige = lambda art, info: _anzeige_haken(z, art, info)
    return True


def _haken_still(art, info):
    """Ein Haken, der nichts zeigt: nach "Trennen" laeuft der letzte
    Auftrag noch fertig — ohne Anzeige des Docks und ohne das Fenster des
    Kerns."""
    return None


def _haken_weg(z):
    """Den Haken dieses Docks vom Dienst nehmen (Neubau, Abbau)."""
    d = z.get("dienst")
    cfg = getattr(d, "cfg", None)
    if cfg is not None and getattr(cfg, "lauf_anzeige", None) is not None:
        cfg.lauf_anzeige = None
    lauf = z.get("anzeige_lauf")
    if isinstance(lauf, dict):
        lauf.clear()


def _anzeige_bauen(z):
    """Die Arbeitsanzeige: ein eigenes rahmenloses Werkzeugfenster an
    Cadworks Hauptfenster (`Tool | FramelessWindowHint`, ohne
    `WindowStaysOnTopHint`: ueber Cadwork, nicht ueber fremden
    Programmen), `WA_ShowWithoutActivating` (nimmt keinen Fokus). Eine
    Karte wie die Pille: Logo, Titel, Knopf, ×; darunter eine Zeile und
    der Balken. Ziehen an der Karte verschiebt sie (gemerkt fuer die
    Sitzung). Versteckt, bis ein Lauf sie braucht. -> das Fenster."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                 QVBoxLayout, QWidget)
    K = _qt_klassen()
    haupt = _hauptfenster()

    class Anzeige(QWidget):
        def __init__(self):
            super().__init__(haupt, Qt.WindowType.Tool
                             | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._griff = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

        def mousePressEvent(self, e):             # noqa: N802
            try:
                if e.button() == Qt.MouseButton.LeftButton:
                    self._griff = (e.globalPosition().toPoint()
                                   - self.frameGeometry().topLeft())
                    z["anzeige_gezogen"] = True
            except Exception as exc:              # noqa: BLE001
                _melden("Anzeige greifen", exc)

        def mouseMoveEvent(self, e):              # noqa: N802
            try:
                if self._griff is not None:
                    self.move(e.globalPosition().toPoint() - self._griff)
            except Exception as exc:              # noqa: BLE001
                _melden("Anzeige ziehen", exc)

        def mouseReleaseEvent(self, e):           # noqa: N802
            try:
                if self._griff is not None:
                    z["anzeige_ort"] = (self.x(), self.y())
                self._griff = None
            except Exception as exc:              # noqa: BLE001
                _melden("Anzeige loslassen", exc)

    fenster = Anzeige()
    fenster.setObjectName("OpenMcpCadAnzeige")
    fenster.setStyleSheet(_qss() + ANZEIGE_QSS)
    huelle = QVBoxLayout(fenster)
    huelle.setContentsMargins(0, 0, 0, 0)
    karte = QFrame()
    karte.setObjectName("OpenMcpCadA")
    karte.setProperty("teil", "anzeige")
    karte.setProperty("farbe", "blau")
    karte.setFixedWidth(ANZEIGE_BREITE)
    huelle.addWidget(karte)
    lay = QVBoxLayout(karte)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(6)
    reihe = QHBoxLayout()
    reihe.setSpacing(8)
    logo = _logo_klein(22)
    zeichen = QLabel("")
    zeichen.hide()
    titel = QLabel("")
    titel.setObjectName("anzeige_titel")
    knopf = QPushButton("Anhalten")
    knopf.setObjectName("trennen")
    knopf.setCursor(Qt.CursorShape.PointingHandCursor)
    knopf.hide()
    weg = QPushButton("")
    weg.setObjectName("flach")
    weg.setFixedSize(20, 20)
    weg.setAccessibleName("Ausblenden")
    weg.setToolTip("Ausblenden — bis zum nächsten Lauf")
    _knopf_symbol(weg, "schliessen", farbe=FARBEN["neben"], groesse=13)
    reihe.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
    reihe.addWidget(zeichen, 0, Qt.AlignmentFlag.AlignVCenter)
    reihe.addWidget(titel, 1)
    reihe.addWidget(knopf, 0, Qt.AlignmentFlag.AlignVCenter)
    reihe.addWidget(weg, 0, Qt.AlignmentFlag.AlignVCenter)
    lay.addLayout(reihe)
    zeile = QLabel("")
    zeile.setObjectName("anzeige_zeile")
    zeile.setTextFormat(Qt.TextFormat.PlainText)
    lay.addWidget(zeile)
    balken = K.Balken()
    balken.hide()
    lay.addWidget(balken)
    fenster.hide()
    knopf.clicked.connect(lambda: _sicher(lambda: _anzeige_knopf(z),
                                          "Arbeitsanzeige"))
    weg.clicked.connect(lambda: _sicher(lambda: _anzeige_weg(z, nutzer=True),
                                        "Arbeitsanzeige ausblenden"))
    z["anzeige"] = fenster
    z["w"].update(anzeige_karte=karte, anzeige_logo=logo,
                  anzeige_zeichen=zeichen, anzeige_titel=titel,
                  anzeige_knopf=knopf, anzeige_weg=weg, anzeige_zeile=zeile,
                  anzeige_balken=balken)
    return fenster


def _anzeige_haken(z, art, info):
    """Der Haken, den der Kern ruft (Kern 2.19, `cfg.lauf_anzeige`):
    "start" VOR jedem Auftrag eines Laufs, "fortschritt" danach, "ende" am
    Ende des Laufs; seit Kern 2.19.1 "auftrag" VOR jedem Auftrag ausserhalb
    eines Laufs (nur Kopf und Briefkasten, keine Anzeige). Merkt den Stand
    und zeichnet SOFORT (`repaint`) — der Hauptthread gehoert gleich dem
    Auftrag, der Takt laeuft dann nicht. Wirft es, faellt der Kern fuer
    diesen Lauf auf sein eigenes Fenster zurueck (Log)."""
    if art in ("start", "auftrag"):
        # Die Pille sagt "Zeichnet"/"Liest", der Briefkasten "Läuft jetzt"
        # — WAEHREND des Auftrags (Gegenpruefung K12: vorher sagte die
        # Pille dabei "Bereit", der Takt steht ja). Scheitert das, bleibt
        # die Arbeitsanzeige davon unberuehrt.
        _sicher(lambda: _auftrag_sofort(z, info), "Zustand im Auftrag")
    if art == "auftrag":
        return
    lauf = z.get("anzeige_lauf")
    if not isinstance(lauf, dict):
        lauf = z["anzeige_lauf"] = {}
    jetzt = time.monotonic()
    info = dict(info or {})
    if art == "start":
        if info.get("neu_lauf") or not lauf.get("aktiv"):
            weg = bool(lauf.get("weg")) and not info.get("neu_lauf")
            lauf.clear()
            lauf.update(aktiv=True, start_t=jetzt, weg=weg, fertig=None,
                        fertig_t=None, angehalten=False,
                        popup=bool(info.get("popup", True)))
        lauf["info"] = info
        lauf["auftrag"] = dict(info, t0=jetzt)
        lauf["angehalten"] = False
    elif art == "fortschritt":
        lauf["info"] = info
        lauf["auftrag"] = None
    elif art == "ende":
        if lauf.get("aktiv"):
            lauf.update(aktiv=False, auftrag=None, info=info,
                        fertig=(int(info.get("lauf_gezeichnet") or 0),
                                jetzt - (lauf.get("start_t") or jetzt)),
                        fertig_t=None)
    _anzeige_zeichnen(z, sofort=True)


def _auftrag_sofort(z, info):
    """Aus dem Haken (VOR dem Auftrag): die Pille im Kopf und "Läuft jetzt"
    im Briefkasten nach dem Auftrag, der gleich laeuft — und SOFORT auf dem
    Bildschirm (`repaint`, kein `processEvents`; Regel 9). Zurueck stellt
    beides der naechste Takt nach dem Auftrag. -> der Text der Pille."""
    w = z["w"]
    info = dict(info or {})
    zustand = "busy_write" if info.get("zugriff") == "write" else "busy_read"
    chat = _chat_stand(z)
    text = _pille_setzen(z, zustand, _pille_zustand(
        True, zustand, None, bool(chat["freigabe"]), chat["zug"]))
    rahmen, lb = w.get("briefkasten_laeuft"), w.get("briefkasten_laeuft_text")
    seite = w.get("briefkasten_seite")
    if rahmen is not None and lb is not None:
        # Ohne Dauer: waehrend des Auftrags steht die Oberflaeche, eine
        # Zahl wie "0 s" bliebe stehen und waere falsch.
        was, tipp = _auftrag_zeile(dict(info, ok=True), time.time())
        if lb.text() != was:
            lb.setText(was)
            lb.setToolTip(_tipp_klartext(tipp))
        if rahmen.isHidden():
            rahmen.show()
            if seite is not None and seite.layout() is not None:
                seite.layout().activate()
        if seite is not None and seite.isVisible():
            seite.repaint()
    dock, kopf = z.get("fenster"), w.get("kopf")
    try:
        if dock is not None and dock.isVisible():
            if dock.layout() is not None:
                dock.layout().activate()
            (dock if dock.isFloating() else kopf or dock).repaint()
    except RuntimeError:                       # schon abgeraeumt
        pass
    return text


def _anzeige_zeichnen(z, sofort=False, st=None):
    """Die Arbeitsanzeige nach dem Stand (`_anzeige_zustand`): Texte,
    Knopf, Balken, Farbe; zeigen (Spezifikation 5.4: nur wenn der Kern
    fuer den Lauf einen Balken zeigen wuerde, in einer Stufe mit Fenster,
    nie NEU, waehrend Cadwork rechnet), stehen lassen (solange der Lauf
    oder der Chat-Zug laeuft), verstecken (ANZEIGE_FERTIG_S nach "Fertig").
    `sofort`: danach `repaint()` (aus dem Haken). -> der Titel oder None."""
    fenster = z.get("anzeige")
    if fenster is None:
        return None
    w = z["w"]
    lauf = z.get("anzeige_lauf") if isinstance(z.get("anzeige_lauf"),
                                               dict) else {}
    d = z.get("dienst")
    verbunden = d is not None and not d.beenden and d.zustand not in (
        "stopped", "error")
    if not verbunden:
        lauf.clear()
        _anzeige_verstecken(z)
        return None
    if st is None:
        try:
            st = d.status() or {}
        except Exception:                              # noqa: BLE001
            st = {}
    chat = _chat_stand(z)
    jetzt = time.monotonic()
    sichtbar = fenster.isVisible()
    aktiv = bool(lauf.get("aktiv"))
    # Der Lauf hat kein Fenster gewollt (Stufe ohne Fenster) oder der
    # Nutzer hat es ausgeblendet: nichts.
    if lauf.get("weg") or (aktiv and not lauf.get("popup", True)):
        _anzeige_verstecken(z)
        return None
    blockiert = _blockiert(z, st)
    auftrag = lauf.get("auftrag") if aktiv else None
    fertig = lauf.get("fertig")
    if fertig is not None and lauf.get("fertig_t") is None \
            and not chat["zug"] and not aktiv:
        lauf["fertig_t"] = jetzt
    zustand = _anzeige_zustand(
        blockiert=blockiert, freigabe=chat["freigabe"] if chat["an"]
        else None, auftrag=auftrag, lauf=lauf.get("info"),
        lauf_aktiv=aktiv, chat_zug=chat["zug"], letzter=chat["letzter"],
        client=(lauf.get("info") or {}).get("client"),
        fertig=fertig if not chat["zug"] else None,
        angehalten=int(lauf.get("angehalten") or 0),
        balken_vorher=w["anzeige_balken"].wert(), jetzt=jetzt,
        wartende=int(st.get("wartende_auftraege") or 0))
    # Zeigen nur, wenn ein Lauf es will (Haken "start"); stehen bleiben,
    # solange er laeuft oder der Chat-Zug; "Fertig" ANZEIGE_FERTIG_S lang.
    soll = False
    if zustand is not None:
        if aktiv:
            soll = sichtbar or not blockiert
        elif sichtbar and chat["zug"]:
            soll = True
        elif sichtbar and zustand["titel"] == ANZEIGE_FERTIG:
            soll = jetzt - (lauf.get("fertig_t") or jetzt) \
                < ANZEIGE_FERTIG_S
    if not soll:
        _anzeige_verstecken(z)
        if not aktiv and not chat["zug"]:
            lauf.pop("fertig", None)
        return None
    _anzeige_setzen(z, zustand)
    if not sichtbar:
        _anzeige_platzieren(z)
        fenster.show()
        haupt = fenster.parentWidget()
        # Nur nach vorn holen, wenn Cadwork vorn ist — sonst reisst ein
        # Lauf im Hintergrund die Aufmerksamkeit aus einer anderen
        # Anwendung (wie das Fenster des Kerns).
        if haupt is None or haupt.isActiveWindow():
            fenster.raise_()
    if sofort:
        fenster.repaint()
    return zustand["titel"]


def _anzeige_setzen(z, zustand):
    """Texte, Knopf, Balken und Farbe der Anzeige setzen (nur bei
    Aenderung)."""
    w = z["w"]
    titel, zeile = w["anzeige_titel"], w["anzeige_zeile"]
    if titel.text() != zustand["titel"]:
        titel.setText(zustand["titel"])
    from PyQt6.QtCore import Qt
    kurz = zeile.fontMetrics().elidedText(
        zustand["zeile"] or "", Qt.TextElideMode.ElideRight,
        ANZEIGE_BREITE - 30)
    if zeile.text() != kurz:
        zeile.setText(kurz)
    zeile.setToolTip(zustand["zeile"] or "")
    zeile.setVisible(bool(zustand["zeile"]))
    zeichen = w["anzeige_zeichen"]
    if zustand.get("symbol"):
        if zeichen.property("symbol") != zustand["symbol"]:
            _label_symbol(zeichen, zustand["symbol"], "✓",
                          FARBEN["gruen"], 16)
        zeichen.show()
    elif not zeichen.isHidden():
        zeichen.hide()
    knopf = w["anzeige_knopf"]
    art = zustand.get("knopf")
    if art is None:
        knopf.hide()
    else:
        text, name = (("Zum Chat", "primaer") if art == "zum_chat"
                      else ("Anhalten", "trennen"))
        if knopf.text() != text or knopf.objectName() != name:
            knopf.setText(text)
            knopf.setObjectName(name)
            knopf.style().unpolish(knopf)
            knopf.style().polish(knopf)
            knopf.setToolTip(
                "Das Fenster öffnen, die Freigabe im Chat beantworten"
                if art == "zum_chat" else
                "Verwirft die noch WARTENDEN Aufträge. Der laufende Schritt "
                "wird fertig gerechnet — ihn abzubrechen ginge nicht, ohne "
                "das Modell halb fertig zu hinterlassen.")
        knopf.setProperty("art", art)
        knopf.show()
    karte = w["anzeige_karte"]
    if karte.property("farbe") != zustand["farbe"]:
        karte.setProperty("farbe", zustand["farbe"])
        karte.style().unpolish(karte)
        karte.style().polish(karte)
    balken = w["anzeige_balken"]
    if zustand.get("balken") is None:
        balken.hide()
    else:
        balken.setzen(zustand["balken"], FARBEN.get(zustand["farbe"],
                                                    FARBEN["blau"]))
        balken.show()


def _anzeige_verstecken(z):
    fenster = z.get("anzeige")
    try:
        if fenster is not None and fenster.isVisible():
            fenster.hide()
    except RuntimeError:                       # schon abgeraeumt
        pass


def _anzeige_platzieren(z):
    """Wo die Anzeige erscheint: waagrecht mittig ueber der 3D-Flaeche
    (`centralWidget`), 12 px unter ihrer Oberkante — nicht mehr mitten im
    Modell. Steht dort das schwebende Fenster, links daneben. Ein Ort, den
    der Nutzer gezogen hat, gilt fuer die Sitzung. VOR dem ersten Zeigen
    (rahmenlos: WA_Moved), danach nachgesehen wie das Fenster."""
    from PyQt6.QtCore import QPoint, QRect
    fenster = z["anzeige"]
    fenster.ensurePolished()
    fenster.adjustSize()
    ort = z.get("anzeige_ort")
    grund = "Ort aus dieser Sitzung"
    if ort is None:
        haupt = _hauptfenster()
        if haupt is not None:
            mitte = getattr(haupt, "centralWidget", lambda: None)()
            if mitte is not None and mitte.isVisible():
                g = QRect(mitte.mapToGlobal(QPoint(0, 0)), mitte.size())
                grund = "oben mittig ueber der 3D-Flaeche"
            else:
                r = _haupt_rahmen(haupt)
                g = QRect(r.left(), r.top() + MONITOR_OBEN_OHNE, r.width(),
                          r.height() - MONITOR_OBEN_OHNE)
                grund = "oben mittig im Hauptfenster"
        else:
            g = _schirm() or QRect(0, 0, 1280, 800)
            grund = "oben mittig auf dem Bildschirm"
        x = g.left() + (g.width() - fenster.width()) // 2
        y = g.top() + 12
        dock = z.get("fenster")
        try:
            if dock is not None and dock.isVisible() and dock.isFloating():
                fg = dock.frameGeometry()
                if QRect(x, y, fenster.width(), fenster.height()) \
                        .intersects(fg):
                    x = fg.left() - 8 - fenster.width()
                    grund += ", links neben dem Fenster"
        except RuntimeError:                   # schon abgeraeumt
            pass
        ort = (x, y)
    x, y = _schwebend_ziel(fenster, ort[0], ort[1], ganz=True)
    fenster.move(QPoint(x, y))
    z["anzeige_soll"] = (x, y)
    z["anzeige_gezogen"] = False
    _ort_protokoll(z, "Arbeitsanzeige gesetzt (%s): %s"
                   % (grund, _lage_text(fenster)))
    _ort_spaeter(z, "anzeige", "anzeige_soll", "Arbeitsanzeige")
    return (x, y)


def _anzeige_knopf(z):
    """Der Knopf der Anzeige: "Anhalten" verwirft die WARTENDEN Auftraege
    (wie das Fenster des Kerns; der laufende Schritt wird fertig, der Chat
    laeuft weiter — ihn haelt "Beenden" im Chat an); verworfen = "Angehalten"
    mit der Zahl, nichts verworfen = keine Bestaetigung. "Zum Chat" oeffnet
    das Fenster beim Chat."""
    knopf = z["w"]["anzeige_knopf"]
    if knopf.property("art") == "zum_chat":
        _chat_oeffnen(z)
        return "zum_chat"
    d, kern = z.get("dienst"), z.get("kern")
    if d is None or kern is None:
        return None
    n = kern._warteschlange_verwerfen(d, "Vom Benutzer angehalten")
    lauf = z.get("anzeige_lauf")
    if isinstance(lauf, dict):
        # Nur, was wirklich verworfen wurde, heisst "Angehalten" — sonst
        # bestaetigte die Anzeige etwas, das nicht geschah.
        lauf["angehalten"] = int(n or 0)
    _anzeige_zeichnen(z, sofort=True)
    return "anhalten"


def _anzeige_weg(z, nutzer=False):
    """Die Anzeige weg — mit `nutzer` (×) bis zum naechsten Lauf."""
    lauf = z.get("anzeige_lauf")
    if nutzer and isinstance(lauf, dict):
        lauf["weg"] = True
    _anzeige_verstecken(z)


def _anzeige_takt(z, st=None):
    """Im Takt des Docks (500 ms): Zustaende auffrischen, die der Kern
    nicht kennt (Chat, Freigabe, Cadwork rechnet), den unbestimmten Balken
    bewegen. Waehrend eines Auftrags steht er (der Takt laeuft dann nicht —
    dokumentierte Grenze wie beim Fenster des Kerns)."""
    if z.get("anzeige") is None:
        return None
    titel = _anzeige_zeichnen(z, st=st)
    balken = z["w"].get("anzeige_balken")
    if titel is not None and balken is not None:
        balken.schritt()
    return titel


def _briefkasten_zeigen(z, st, post):
    """Im Takt: im Segment Briefkasten "Läuft jetzt" (der laufende Auftrag
    mit Paket und Dauer) und die Zahl wartender Notizen am Segment."""
    w = z["w"]
    auftrag = (st or {}).get("auftrag") or {}
    rahmen = w.get("briefkasten_laeuft")
    if rahmen is not None:
        if auftrag:
            was, tipp = _auftrag_zeile(dict(auftrag, ok=True), time.time())
            text = "%s · %d s" % (was, int(auftrag.get("laufzeit_s") or 0))
            lb = w["briefkasten_laeuft_text"]
            if lb.text() != text:
                lb.setText(text)
                lb.setToolTip(_tipp_klartext(tipp))
            if rahmen.isHidden():
                rahmen.show()
        elif not rahmen.isHidden():
            rahmen.hide()
    zahl = w.get("briefkasten_zahl")
    if zahl is not None:
        n = sum(1 for p in post or () if not p.get("abgeholt"))
        text = str(n) if n else ""
        if zahl.text() != text:
            zahl.setText(text)
            zahl.setToolTip("%d Notiz%s wartet" % (n, "en" if n != 1 else "")
                            if n else "")
        if zahl.isHidden() == bool(n):
            zahl.setVisible(bool(n))


# --- Auffrischen ----------------------------------------------------------

def _vor_wie_lange(t):
    s = max(0, int(time.time() - (t or 0)))
    if s < 60:
        return "vor %d s" % s
    if s < 3600:
        return "vor %d min" % (s // 60)
    if s < 86400:
        return "vor %d h" % (s // 3600)
    return "vor %d d" % (s // 86400)


def _auffrischen(z):
    """Der Takt der Oberflaeche. Ruehrt NIE cwapi3d an — nur Zustand lesen."""
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QListWidgetItem
    from PyQt6.QtCore import Qt

    w = z["w"]

    # Zeilen ueber die Lage der Fenster (K10), sobald es ein Log gibt.
    try:
        _ort_ausgeben(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Fenster-Log", exc)

    # ZUERST und IMMER: der Verbindungs-Tab haengt nicht an A. Er muss auch
    # dann arbeiten, wenn A aus ist — sonst saehe man B/C/D nie, solange man
    # selbst nicht verbunden ist.
    # Fehler darin landen einmal je Wortlaut auf stderr (`_melden`), der
    # Rest des Takts laeuft trotzdem. Jeder Block hier traegt einen EIGENEN
    # Namen ("Auffrischen/…"): der Chat-Takt meldet unter "Chat zeichnen",
    # und unter demselben Namen verdeckte er einen stummen Block hier.
    try:
        _verbindungen_zeichnen(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Verbindungen", exc)

    # Ebenfalls VOR dem frueh-return weiter unten: ohne Verbindung zeigt der
    # Chat "Zuerst verbinden" statt einfach einzufrieren. Der Aufruf liest
    # nur, was der Leserthread hinterlegt hat — kein Warten, kein cwapi3d.
    try:
        _chat_zeichnen(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Chat", exc)

    # Die Technik-Details (⚙): nur bei offener Anzeige, Arbeit im Thread.
    try:
        _technik_zeichnen(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Technik", exc)

    # Erst NACH dem Chat: loest er ein Trennen ein (`_nach_zug_einloesen`),
    # zeigt schon dieser Takt "nicht verbunden".
    d = z["dienst"]
    verbunden = d is not None and not d.beenden and d.zustand != "stopped"

    def knopf_setzen(text, an):
        # "Verbinden" ist der Hauptknopf (blau); verbunden tritt "Trennen"
        # zurueck (K10/K11; seit K12 der eine Knopf im Kopf).
        name = "trennen" if text == "Trennen" else "primaer"
        b = w.get("primaer")
        if b is None:
            return
        if b.text() != text:
            b.setText(text)
            b.setAccessibleName(text)
            b.setToolTip("Trennen — ein laufender Auftrag wird fertig "
                         "gerechnet" if text == "Trennen" else
                         "Mit dieser Cadwork-Datei verbinden")
        b.setEnabled(an)
        if b.objectName() != name:
            b.setObjectName(name)
            b.style().unpolish(b)
            b.style().polish(b)

    st = None
    _schliessen_zeigen(z, verbunden)
    if not verbunden:
        _pille_setzen(z, None)
        knopf_setzen("Verbinden", True)
        _kontext_setzen(z, "nicht verbunden", "")
    else:
        st = d.status()
        chat_jetzt = _chat_stand(z)
        blockiert = _blockiert(z, st)
        _pille_setzen(z, st["zustand"], _pille_zustand(
            True, st["zustand"], blockiert,
            bool(chat_jetzt["freigabe"]), chat_jetzt["zug"]))
        knopf_setzen("Trennen", st["zustand"] != "starting")
        dok = str(st.get("dokument") or "—")
        # Die Kontextzeile (Spezifikation 3.1): nur die Datei; Elemente und
        # ein laufender Auftrag im Tooltip. Steckplatz und Port stehen nur
        # in den Technik-Details (S5, Rueckmeldung 2026-09-25: "weniger
        # Technik im Plugin"; Gegenpruefung Laien-Sicht K12: "Steckplatz A"
        # sagt einem Zimmermann nichts).
        text = dok
        tipp = "%s · %s Elemente" % (dok, st.get("dokument_elemente"))
        auftrag = st.get("auftrag") or {}
        if auftrag:
            was, _t = _auftrag_zeile(dict(auftrag, ok=True), time.time())
            tipp += "\nLäuft: %s · %d s" % (was, int(
                auftrag.get("laufzeit_s") or 0))
        _kontext_setzen(z, text, tipp)
        kern_hinweis = st.get("hinweis")
        if st.get("cadwork_beschaeftigt") and blockiert != st.get(
                "cadwork_beschaeftigt") and kern_hinweis:
            # Der Kern haelt wegen EINES UNSERER Menues zurueck — er sagt
            # "Cadwork arbeitet gerade selbst"; das stimmt nicht.
            kern_hinweis = (ANZEIGE_MENUE[1] if blockiert else None)
        kern_meldung = kern_hinweis or st.get("fehler_text") or ""
        if _fehler_steht(z):
            # Eine frische Meldung des Docks bleibt lesbar (`_fehler_zeigen`);
            # hat der Kern auch etwas zu sagen, steht es darunter, statt
            # eins das andere zu verdraengen.
            teile = [z.get("fehler_dock") or ""]
            if kern_meldung and kern_meldung not in teile:
                teile.append(kern_meldung)
            _zeile_rot(z, "\n".join(t for t in teile if t))
        elif kern_hinweis:
            _zeile_rot(z, kern_hinweis, FARBEN["orange"])
        elif st.get("fehler_text"):
            _zeile_rot(z, st["fehler_text"])
        else:
            _meldung_weg(z)

    # Die Pille sagt im Tooltip, was die Kontextzeile sagt, und haengt mit
    # ihrer rechten Kante am Ort (K11/K12).
    try:
        _pille_tipp(z)
        _kopf_anpassen(z)
        _hoechstmasse(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Kopf", exc)

    # Alles, was ohne Verbindung sinnlos ist, wird ausgegraut statt zu luegen.
    for schluessel in ("btn_undo", "btn_redo", "btn_neu", "btn_pause",
                       "btn_nach"):
        w[schluessel].setEnabled(verbunden)
    pausiert = bool(verbunden and getattr(d, "pausiert", False))
    text_p = "Fortsetzen" if pausiert else "Pausieren"
    if w["btn_pause"].text() != text_p:
        w["btn_pause"].setText(text_p)
        ikone = _ikone("play" if pausiert else "pause")
        if ikone is not None:
            w["btn_pause"].setIcon(ikone)
    for b in w.get("hinweis_knoepfe", ()):
        b.setEnabled(verbunden)
    w["post_senden"].setEnabled(verbunden)
    w["post_senden"].setToolTip(
        "Die Notiz in den Briefkasten legen (Enter)" if verbunden
        else "Zuerst verbinden")
    w["regler"].setEnabled(verbunden)
    # Die Arbeitsanzeige (K12): Chat, Freigabe, Cadwork rechnet — und ohne
    # Verbindung weg.
    try:
        _anzeige_takt(z, st)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Arbeitsanzeige", exc)
    if not verbunden:
        w["post_kontext"].setText("Zuerst verbinden")
        _hinweis_zahl_zeigen(z, 0)
        if not w["briefkasten_laeuft"].isHidden():
            w["briefkasten_laeuft"].hide()
        return

    # Hinweise und Briefkasten sichern, damit sie den Neustart ueberleben.
    try:
        _ablage_pflegen(z)
    except Exception as exc:                       # noqa: BLE001
        _melden("Auffrischen/Notizen", exc)

    st = d.status()

    # -- Verlauf -----------------------------------------------------------
    with d.sperre:
        verlauf = [dict(v) for v in d.verlauf]
        hinweise = [dict(h) for h in d.hinweise]
        post = [dict(n) for n in d.postfach]
    # K5: lesbar (was, wann), Methode und Dauer nur im Tooltip. Neu gebaut
    # nur bei einem neuen Auftrag — die Marke nimmt den letzten mit, denn
    # bei VERLAUF_MAX bleibt die Laenge gleich; die Zeitangaben ("vor 5
    # min") an Ort und Stelle, damit die Auswahl bleibt.
    lst = w["liste_auftraege"]
    jetzt_a = time.time()
    zeilen = [_auftrag_zeile(v, jetzt_a) for v in reversed(verlauf)]
    marke_a = (len(verlauf), verlauf[-1].get("beendet") if verlauf else None)
    if getattr(lst, "_n", None) != marke_a:
        lst._n = marke_a
        lst.clear()
        for v, (text, tipp) in zip(reversed(verlauf), zeilen):
            item = QListWidgetItem(text)
            item.setToolTip(tipp)
            fehler_a = not v.get("ok")
            ikone = _ikone(_auftrag_symbol(v),
                           FARBEN["orange"] if fehler_a else FARBEN["neben"])
            if ikone is not None:
                item.setIcon(ikone)
            lst.addItem(item)
    else:
        for i, (text, _tipp) in enumerate(zeilen):
            item = lst.item(i)
            if item is not None and item.text() != text:
                item.setText(text)

    # -- Hinweise ----------------------------------------------------------
    # Kein clear() mehr, und vor allem KEIN Zeiteimer im Stempel: genau der
    # (`int((jetzt - h["zeit"]) / 5)`) hat die Liste alle fuenf Sekunden neu
    # gebaut und dabei die Auswahl mitgenommen. Gemessen am 2026-08-15:
    # Auswahl nach 0,75 s weg, Kontrollzelle behielt sie.
    # Das Board aktualisiert jetzt in sich; die Auswahl liegt neben den
    # Widgets und ueberlebt jedes Auffrischen.
    _hinweis_modul().zeichnen(w["hinweise"], hinweise, w["hinweis_umgebung"],
                              aktive_elemente=st.get("aktive_elemente") or 0)
    _hinweis_antwort_zeigen(z)
    # Die Zahl offener Hinweise: Chip in der Pille, Knopf und Kopf des
    # Hinweis-Bereichs (K12).
    _hinweis_zahl_zeigen(z, sum(1 for h in hinweise
                                if h.get("status", "offen") == "offen"))

    # -- Briefkasten -------------------------------------------------------
    _post_zeichnen(z, post)             # aeltere oben, neue unten
    n_aktiv = st.get("aktive_elemente") or 0
    w["post_kontext"].setText(
        ("%d ausgewählte Element%s" % (n_aktiv, "" if n_aktiv == 1 else "e"))
        if n_aktiv else "Kein Element ausgewählt")
    _briefkasten_zeigen(z, st, post)

    # -- Zeichenmodus ------------------------------------------------------
    kern = z["kern"]
    stufen = list(getattr(kern, "ZEICHENMODI", ()))
    regler = w["regler"]
    if stufen and regler.maximum() != len(stufen) - 1:
        regler.setMaximum(len(stufen) - 1)
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtWidgets import QLabel
        # Die Beschriftungen muessen dort stehen, wo der Regler HAELT.
        # Gleichbreite Spalten mit zentriertem Text setzen die aeusseren
        # zu weit nach innen — Rueckmeldung 2026-08-07: "die Begriffe langsam und
        # schnell stehen zu weit links". Deshalb: erste linksbuendig,
        # letzte rechtsbuendig, alle dazwischen zentriert.
        for i, m in enumerate(stufen):
            lb = QLabel(m["anzeige"])
            lb.setObjectName("neben")
            if i == 0:
                lb.setAlignment(_Qt.AlignmentFlag.AlignLeft)
            elif i == len(stufen) - 1:
                lb.setAlignment(_Qt.AlignmentFlag.AlignRight)
            else:
                lb.setAlignment(_Qt.AlignmentFlag.AlignHCenter)
            w["marken"].addWidget(lb, 1)
            w["modus_marken"].append(lb)
    jetzt = st.get("zeichenmodus")
    for i, m in enumerate(stufen):
        if m["schluessel"] == jetzt:
            if regler.value() != i:
                regler.blockSignals(True)
                regler.setValue(i)
                regler.blockSignals(False)
            hae = st.get("haeppchen_empfehlung")
            # Die gemessene Zeit je Bauteil steht in den Technik-Details
            # (Gegenpruefung Laien-Sicht K12: "120 ms je Bauteil").
            w["modus_text"].setText(
                "%s<br><span style='color:%s;'>%s</span>"
                % (m["text"], FARBEN["neben"],
                   ("empfohlen: rund %d Bauteile je Auftrag" % hae) if hae
                   else "Auftragsgrösse egal"))
            break
