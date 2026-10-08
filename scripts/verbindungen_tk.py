#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fenster "Open MCP CAD Verbindungen" — Uebersicht und Steuerung der Steckplaetze.

Laeuft als EIGENER Prozess neben Cadwork, nicht darin. Das ist Absicht:

  * Eine Oberflaeche im Cadwork-Prozess muesste sich dessen Ereignisschleife
    teilen — genau die Stelle, an der die alte Bridge haengengeblieben ist.
  * Ein eigener Prozess kann Cadwork weder blockieren noch mitreissen.
  * Er sieht alle vier Steckplaetze gleichzeitig, auch die in ANDEREN
    Cadwork-Prozessen, weil er sie ueber ihre Localhost-Ports fragt.

Was das Fenster ehrlich NICHT kann: eine Verbindung starten, die noch gar
nicht laeuft. Ein Plugin kann nur in seinem eigenen Cadwork-Prozess
gestartet werden (Plugin-Menue -> "Open MCP CAD A/B/C/D"). Steckplaetze
ohne laufendes Plugin stehen deshalb auf "Aus" und haben keinen Startknopf.

    python scripts/verbindungen_tk.py
"""

import os
import sys
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
if HIER not in sys.path:
    sys.path.insert(0, HIER)

REPO = os.path.dirname(HIER)   # scripts/ bzw. tests/ liegen direkt im Repo
ICON_PFAD = os.path.join(REPO, "assets",
                         "icon-64.png")

import connect_client as cc                          # noqa: E402

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox, ttk
except ImportError as exc:                            # pragma: no cover
    sys.stderr.write("Tkinter ist nicht verfuegbar (%s).\n"
                     "Rueckfallebene: python scripts/"
                     "verbindungen_web.py\n" % exc)
    raise SystemExit(2)

TAKT_MS = 1000          # Statusabfrage jede Sekunde

# Farben sind NUR Zugabe — der Zustand steht immer als Text daneben.
FARBE = {
    "ready": "#2e7d32",
    "busy_read": "#1565c0",
    "busy_write": "#1565c0",
    "paused": "#e65100",
    "stopping_after_job": "#e65100",
    "starting": "#6a6a6a",
    "stopped": "#9e9e9e",
    "unreachable": "#9e9e9e",
    "no_answer": "#c62828",
    "error": "#c62828",
    "veraltet": "#8d6e63",
}

SICHER_BEENDBAR = ("ready", "paused", "error", "starting", "veraltet")


def _windows_app_id_setzen():
    """Gibt dem Fenster unter Windows eine eigene Taskleisten-Identitaet.

    Ohne AppUserModelID gruppiert Windows ein via ``pythonw.exe`` gestartetes
    Tk-Fenster gelegentlich unter dem Python-Symbol, obwohl ``iconphoto`` ein
    eigenes Bild gesetzt hat. Auf anderen Plattformen ist nichts zu tun.
    """
    if os.name != "nt":
        return
    try:
        import ctypes                              # noqa: PLC0415
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Open MCP CAD.Connect.Verbindungen")
    except (AttributeError, OSError):
        pass                                      # Symbol bleibt trotzdem gesetzt


def _fenster_symbol_setzen(wurzel):
    """Setzt das Open-MCP-CAD-Logo fuer Titelleiste und Taskleiste.

    Tk behaelt ``PhotoImage`` nicht selbst am Leben. Die Referenz muss daher
    am langlebigen Hauptfenster haengen; sonst verschwindet das Symbol nach
    dem ersten Garbage-Collection-Lauf wieder. Fehlt das Asset, bleibt das
    normale Tk-Symbol erhalten und die Verbindungsuebersicht startet weiter.
    """
    try:
        bild = tk.PhotoImage(file=ICON_PFAD)
        wurzel.iconphoto(True, bild)
        wurzel._omcad_icon = bild
        return True
    except (OSError, tk.TclError):
        return False


class Steckplatzzeile:
    """Eine Zeile: Buchstabe, Dokument, Zustand/Taetigkeit, Zeit, Knoepfe."""

    def __init__(self, eltern, instanz, port, reihe, app):
        self.instanz = instanz
        self.port = port
        self.app = app
        self.daten = {}
        self.details_offen = False

        self.rahmen = ttk.Frame(eltern, padding=(8, 6))
        self.rahmen.grid(row=reihe, column=0, sticky="ew")
        eltern.columnconfigure(0, weight=1)
        for spalte, gewicht in ((2, 3), (3, 0), (4, 0)):
            self.rahmen.columnconfigure(spalte, weight=gewicht)

        self.punkt = tk.Canvas(self.rahmen, width=12, height=12,
                               highlightthickness=0)
        self.punkt.grid(row=0, column=0, padx=(0, 6))
        self._kreis = self.punkt.create_oval(2, 2, 11, 11, fill=FARBE["stopped"],
                                             outline="")

        self.lbl_instanz = ttk.Label(self.rahmen, text=instanz,
                                     font=app.schrift_fett, width=2)
        self.lbl_instanz.grid(row=0, column=1, sticky="w")

        self.lbl_dokument = ttk.Label(self.rahmen, text="—", width=24,
                                      font=app.schrift)
        self.lbl_dokument.grid(row=0, column=2, sticky="w", padx=(6, 10))

        self.lbl_zustand = ttk.Label(self.rahmen, text="Aus", font=app.schrift)
        self.lbl_zustand.grid(row=0, column=3, sticky="w")

        self.lbl_zeit = ttk.Label(self.rahmen, text="", width=6,
                                  font=app.schrift_fest)
        self.lbl_zeit.grid(row=0, column=4, sticky="e", padx=(10, 10))

        knoepfe = ttk.Frame(self.rahmen)
        knoepfe.grid(row=0, column=5, sticky="e")
        self.btn_pause = ttk.Button(knoepfe, text="Pausieren", width=11,
                                    command=self._pausieren)
        self.btn_weiter = ttk.Button(knoepfe, text="Fortsetzen", width=11,
                                     command=self._fortsetzen)
        self.btn_nach = ttk.Button(knoepfe, text="Nach Auftrag beenden",
                                   width=21, command=self._nach_auftrag)
        self.btn_jetzt = ttk.Button(knoepfe, text="Jetzt beenden", width=13,
                                    command=self._jetzt_beenden)
        self.btn_details = ttk.Button(knoepfe, text="Details", width=8,
                                      command=self._details_umschalten)
        for i, b in enumerate((self.btn_pause, self.btn_weiter, self.btn_nach,
                               self.btn_jetzt, self.btn_details)):
            b.grid(row=0, column=i, padx=2)

        self.lbl_hinweis = ttk.Label(self.rahmen, text="", font=app.schrift_klein,
                                     foreground="#8a4b00", wraplength=900,
                                     justify="left")
        self.lbl_hinweis.grid(row=1, column=2, columnspan=4, sticky="w",
                              padx=(6, 0))
        self.lbl_hinweis.grid_remove()

        self.details = tk.Text(self.rahmen, height=9, width=100, wrap="none",
                               font=app.schrift_fest, relief="flat",
                               background="#f4f4f4")
        self.details.grid(row=2, column=1, columnspan=5, sticky="ew",
                          pady=(4, 0))
        self.details.grid_remove()

    # -- Anzeige ----------------------------------------------------------

    def aktualisieren(self, daten):
        self.daten = daten
        zustand = daten.get("zustand", "stopped")
        self.punkt.itemconfig(self._kreis,
                              fill=FARBE.get(zustand, FARBE["error"]))

        dok = daten.get("dokument") or "—"
        self.lbl_dokument.config(text=dok[:30])

        text = daten.get("zustand_text") or "?"
        auftrag = daten.get("auftrag")
        if auftrag:
            was = auftrag.get("beschreibung") or auftrag.get("methode") or ""
            if was:
                text = "%s: %s" % (text, was)
            self.lbl_zeit.config(text=cc.dauer_text(auftrag.get("laufzeit_s")))
        else:
            self.lbl_zeit.config(text="")
        self.lbl_zustand.config(text=text[:60])

        hinweis = daten.get("hinweis") or ""
        if hinweis:
            self.lbl_hinweis.config(text=hinweis)
            self.lbl_hinweis.grid()
        else:
            self.lbl_hinweis.grid_remove()

        laeuft = daten.get("erreichbar") and zustand not in (
            "unreachable", "stopped")
        # Ein altes Plugin kennt nur 'shutdown' — Pause, Fortsetzen und
        # "nach Auftrag beenden" wuerden dort ins Leere laufen.
        steuerbar = laeuft and zustand not in cc.NUR_ALT_STEUERBAR
        self.btn_pause.state(["!disabled"] if (steuerbar and not daten.get("pausiert"))
                             else ["disabled"])
        self.btn_weiter.state(["!disabled"] if (steuerbar and daten.get("pausiert"))
                              else ["disabled"])
        self.btn_nach.state(["!disabled"] if steuerbar else ["disabled"])
        # "Jetzt beenden" NUR wenn sicher — waehrend eines Auftrags nicht.
        self.btn_jetzt.state(["!disabled"] if (laeuft and zustand in SICHER_BEENDBAR)
                             else ["disabled"])

        if self.details_offen:
            self._details_schreiben()

    def _details_schreiben(self):
        d = self.daten
        auftrag = d.get("auftrag") or {}
        letzter = d.get("letzter_auftrag") or {}
        fehler = d.get("letzter_fehler") or {}
        lizenz = d.get("schreiblizenz") or {}
        zeilen = [
            ("Steckplatz", "%s (%s)" % (d.get("instanz"),
                                        d.get("anzeigename", "Open MCP CAD"))),
            ("Port / PID", "%s / %s" % (d.get("port"), d.get("pid", "—"))),
            ("Plugin-Version", "%s  (Protokoll %s)" % (d.get("version", "—"),
                                                       d.get("protokoll", "—"))),
            ("Dokument (Cache)", "%s  (Stand %s s alt, %s Elemente)"
             % (d.get("dokument") or "—", d.get("dokument_stand_s"),
                d.get("dokument_elemente"))),
            ("Zustand", "%s (%s)" % (d.get("zustand_text"), d.get("zustand"))),
            ("Gestartet / Laufzeit", "%s / %s"
             % (_zeitpunkt(d.get("gestartet")), cc.dauer_text(d.get("laufzeit_s")))),
            ("Verbindungen", d.get("verbindungen", "—")),
            ("Wartende Auftraege", d.get("wartende_auftraege", "—")),
            ("Auftraege gesamt", d.get("auftraege_gesamt", "—")),
            ("Aktuelle Operation", auftrag.get("methode") or "—"),
            ("Beschreibung", auftrag.get("beschreibung") or "—"),
            ("Operation-ID", auftrag.get("operation_id") or "—"),
            ("Zugriff", auftrag.get("zugriff") or "—"),
            ("Client", "%s (%s)" % (auftrag.get("client") or "—",
                                    auftrag.get("client_id") or "—")),
            ("Auftrag seit", "%s / %s" % (_zeitpunkt(auftrag.get("gestartet")),
                                          cc.dauer_text(auftrag.get("laufzeit_s")))),
            ("Letzter Auftrag", "%s — %s (%s s, %s)"
             % (letzter.get("methode", "—"), letzter.get("beschreibung") or "—",
                letzter.get("dauer_s", "—"),
                "ok" if letzter.get("ok") else letzter.get("ok"))),
            ("Letzter Fehler", "%s: %s" % (fehler.get("fehler", "—"),
                                           (fehler.get("meldung") or "")[:70])),
            ("Schreiblizenz", ("%s (%s), noch %s s"
                               % (lizenz.get("client"), lizenz.get("client_id"),
                                  lizenz.get("rest_s")))
             if lizenz else "frei"),
            ("Hauptthread", "Herzschlag %s s alt — %s"
             % (d.get("hauptthread_alter_s"),
                "ok" if d.get("hauptthread_ok") else "ANTWORTET NICHT")),
            ("UI-Pumpe / Antrieb", "%s / %s" % (d.get("ui_pumpe"),
                                                d.get("antrieb", "—"))),
            ("Antwortzeit Status", "%s ms" % d.get("antwortzeit_ms", "—")),
            ("Technische Meldung", d.get("fehler_detail") or "—"),
        ]
        self.details.config(state="normal")
        self.details.delete("1.0", "end")
        for name, wert in zeilen:
            self.details.insert("end", "%-22s %s\n" % (name + ":", wert))
        self.details.config(state="disabled")

    def _details_umschalten(self):
        self.details_offen = not self.details_offen
        if self.details_offen:
            self._details_schreiben()
            self.details.grid()
            self.btn_details.config(text="Zuklappen")
        else:
            self.details.grid_remove()
            self.btn_details.config(text="Details")

    # -- Aktionen (immer im Hintergrund, nie in der Ereignisschleife) -----

    def _pausieren(self):
        self.app.aktion(self.instanz, cc.pausieren, "Pausieren")

    def _fortsetzen(self):
        self.app.aktion(self.instanz, cc.fortsetzen, "Fortsetzen")

    def _nach_auftrag(self):
        if not messagebox.askokcancel(
                "Nach Auftrag beenden",
                "Open MCP CAD %s beendet sich, sobald der laufende Auftrag "
                "fertig ist.\n\nWartende Auftraege werden dabei verworfen. "
                "Der laufende Auftrag laeuft vollstaendig zu Ende."
                % self.instanz):
            return
        self.app.aktion(self.instanz, cc.beenden_nach_auftrag,
                        "Nach Auftrag beenden")

    def _jetzt_beenden(self):
        if not messagebox.askokcancel(
                "Jetzt beenden",
                "Open MCP CAD %s sofort beenden?\n\nDas ist nur erlaubt, "
                "wenn gerade kein Auftrag laeuft. Cadwork selbst wird NICHT "
                "beendet und das Dokument nicht gespeichert." % self.instanz):
            return
        self.app.aktion(self.instanz, cc.jetzt_beenden, "Jetzt beenden")


def _zeitpunkt(epoch):
    if not epoch:
        return "—"
    return time.strftime("%H:%M:%S", time.localtime(epoch))


class App:
    def __init__(self, wurzel):
        self.wurzel = wurzel
        wurzel.title("Open MCP CAD Verbindungen")
        wurzel.minsize(1080, 320)

        self.schrift = tkfont.nametofont("TkDefaultFont").copy()
        self.schrift.configure(size=10)
        self.schrift_fett = self.schrift.copy()
        self.schrift_fett.configure(weight="bold", size=12)
        self.schrift_klein = self.schrift.copy()
        self.schrift_klein.configure(size=9)
        self.schrift_fest = tkfont.nametofont("TkFixedFont").copy()
        self.schrift_fest.configure(size=9)

        kopf = ttk.Frame(wurzel, padding=(10, 8, 10, 0))
        kopf.pack(fill="x")
        ttk.Label(kopf, text="Open MCP CAD Verbindungen",
                  font=(self.schrift.cget("family"), 15, "bold")).pack(side="left")
        self.lbl_stand = ttk.Label(kopf, text="", font=self.schrift_klein)
        self.lbl_stand.pack(side="right")

        koerper = ttk.Frame(wurzel, padding=(10, 4, 10, 8))
        koerper.pack(fill="both", expand=True)
        self.zeilen = {}
        for i, (instanz, port) in enumerate(cc.STECKPLAETZE):
            if i:
                ttk.Separator(koerper, orient="horizontal").grid(
                    row=2 * i - 1, column=0, sticky="ew", pady=2)
            self.zeilen[instanz] = Steckplatzzeile(koerper, instanz, port,
                                                   2 * i, self)
        koerper.columnconfigure(0, weight=1)

        fuss = ttk.Frame(wurzel, padding=(10, 0, 10, 8))
        fuss.pack(fill="x")
        ttk.Label(fuss, font=self.schrift_klein, foreground="#555",
                  text="Starten lässt sich eine Verbindung nur in ihrem "
                       "eigenen Cadwork-Fenster: Plugin-Menü → Plugin user "
                       "→ Open MCP CAD A/B/C/D. Überwacht und sicher "
                       "beendet wird sie hier.").pack(side="left")

        self._letzte_daten = None
        self._laeuft = True
        self.wurzel.protocol("WM_DELETE_WINDOW", self._schliessen)
        # Handle behalten: wer das Fenster ohne Prozessende abbaut (test_offline
        # G8), muss den Faden erst beenden — er haelt das App-Objekt und damit
        # Tk. Stirbt Tk in einem fremden Thread, bricht Tcl den Prozess ab.
        self._abfrage_thread = threading.Thread(
            target=self._abfrage_schleife, daemon=True)
        self._abfrage_thread.start()
        self._anzeigen()
        self._nach_vorne()

    def _nach_vorne(self):
        """Holt das Fenster einmal nach vorne — und gibt topmost gleich frei.

        Ohne das erscheint es unter Umstaenden HINTER Cadwork und wirkt, als
        sei es gar nicht gestartet (2026-08-04: "es ploppt nicht auf").
        Dauerhaft topmost waere falsch — es soll ja nicht ueber allem kleben.
        """
        try:
            self.wurzel.lift()
            self.wurzel.attributes("-topmost", True)
            self.wurzel.after(700,
                              lambda: self.wurzel.attributes("-topmost", False))
            self.wurzel.focus_force()
        except tk.TclError:
            pass

    def _schliessen(self):
        self._laeuft = False
        self.wurzel.destroy()

    def _abfrage_schleife(self):
        """Netzwerk NIE in der Tk-Schleife — sonst haengt das Fenster."""
        while self._laeuft:
            try:
                self._letzte_daten = (cc.alle_status(), time.time())
            except Exception as exc:                  # noqa: BLE001
                self._letzte_daten = ([], time.time(), str(exc))
            time.sleep(TAKT_MS / 1000.0)

    def _anzeigen(self):
        if not self._laeuft:
            return
        if self._letzte_daten:
            daten, stand = self._letzte_daten[0], self._letzte_daten[1]
            for d in daten:
                zeile = self.zeilen.get(d.get("instanz"))
                if zeile:
                    zeile.aktualisieren(d)
            self.lbl_stand.config(text="Stand %s" % time.strftime(
                "%H:%M:%S", time.localtime(stand)))
        self.wurzel.after(400, self._anzeigen)

    def aktion(self, instanz, funktion, name):
        def lauf():
            antwort = funktion(instanz)
            if not antwort.get("ok"):
                self.wurzel.after(0, lambda: messagebox.showwarning(
                    name,
                    "%s auf Open MCP CAD %s wurde abgelehnt:\n\n%s"
                    % (name, instanz, antwort.get("message", "unbekannt"))))
        threading.Thread(target=lauf, daemon=True).start()


def main():
    _windows_app_id_setzen()
    wurzel = tk.Tk()
    _fenster_symbol_setzen(wurzel)
    App(wurzel)
    wurzel.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
