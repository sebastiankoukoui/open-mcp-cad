#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rueckfallebene: "Open MCP CAD Verbindungen" im Browser.

Gleiche Inhalte und gleiche Regeln wie das Tk-Fenster, nur eben als kleine
lokale Seite — fuer den Fall, dass auf einem Rechner kein Tkinter da ist.
Nur Stdlib (`http.server`), keine Abhaengigkeiten, bindet ausschliesslich
auf 127.0.0.1. Dasselbe Muster benutzt der Wand-LIVE-Server im Repo.

    python scripts/verbindungen_web.py          # Port 53140
    python scripts/verbindungen_web.py --port 53141 --kein-browser
"""

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HIER = os.path.dirname(os.path.abspath(__file__))
if HIER not in sys.path:
    sys.path.insert(0, HIER)

import connect_client as cc                          # noqa: E402

STANDARD_PORT = 53140

AKTIONEN = {
    "pause": cc.pausieren,
    "resume": cc.fortsetzen,
    "nach_auftrag": cc.beenden_nach_auftrag,
    "jetzt": cc.jetzt_beenden,
    "verwerfen": cc.wartende_verwerfen,
    "lizenz_frei": lambda i: cc.lizenz_freigeben(i),
}

SEITE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>Open MCP CAD Verbindungen</title>
<style>
 body{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#222;
      background:#fafafa}
 h1{font-size:20px;margin:0 0 4px}
 .stand{color:#777;font-size:12px;margin-bottom:16px}
 .zeile{background:#fff;border:1px solid #e0e0e0;border-radius:6px;
        padding:10px 14px;margin-bottom:8px;display:flex;align-items:center;
        gap:14px;flex-wrap:wrap}
 .punkt{width:12px;height:12px;border-radius:50%;flex:none}
 .instanz{font-weight:700;font-size:16px;width:16px}
 .dok{width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .zustand{flex:1;min-width:240px}
 .zeit{font-family:Consolas,monospace;width:56px;text-align:right}
 button{font-size:13px;padding:4px 10px;margin-left:4px;cursor:pointer}
 button[disabled]{opacity:.4;cursor:not-allowed}
 .hinweis{width:100%;color:#8a4b00;font-size:12px}
 details{width:100%;margin-top:6px}
 pre{font-family:Consolas,monospace;font-size:12px;background:#f4f4f4;
     padding:10px;border-radius:4px;overflow:auto}
 .fuss{color:#666;font-size:12px;margin-top:18px;max-width:820px}
</style></head><body>
<h1>Open MCP CAD Verbindungen</h1>
<div class="stand" id="stand">…</div>
<div id="liste"></div>
<div class="fuss">Starten l&auml;sst sich eine Verbindung nur in ihrem eigenen
Cadwork-Fenster: Plugin-Men&uuml; &rarr; Plugin user &rarr; Open MCP CAD
A/B/C/D. &Uuml;berwacht und sicher beendet wird sie hier.</div>
<script>
const FARBE={ready:"#2e7d32",busy_read:"#1565c0",busy_write:"#1565c0",
 paused:"#e65100",stopping_after_job:"#e65100",starting:"#6a6a6a",
 stopped:"#9e9e9e",unreachable:"#9e9e9e",no_answer:"#c62828",error:"#c62828",
 veraltet:"#8d6e63"};
const SICHER=["ready","paused","error","starting","veraltet"];
const NUR_ALT=["veraltet"];
function zeit(s){if(s===null||s===undefined)return"";s=Math.floor(s);
 return String(Math.floor(s/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0");}
async function aktion(instanz,was,frage){
 if(frage && !confirm(frage))return;
 const r=await fetch("/aktion?instanz="+instanz+"&was="+was,{method:"POST"});
 const d=await r.json();
 if(!d.ok)alert("Abgelehnt: "+(d.message||"unbekannt"));
 laden();
}
function zeileHtml(d){
 const a=d.auftrag||{};
 let text=d.zustand_text||"?";
 if(a.beschreibung||a.methode)text+=": "+(a.beschreibung||a.methode);
 const laeuft=d.erreichbar&&d.zustand!=="unreachable"&&d.zustand!=="stopped";
 const steuerbar=laeuft&&!NUR_ALT.includes(d.zustand);
 const sicher=laeuft&&SICHER.includes(d.zustand);
 const b=(t,was,an,frage)=>`<button ${an?"":"disabled"} onclick="aktion('${d.instanz}','${was}',${frage?JSON.stringify(frage):"null"})">${t}</button>`;
 return `<div class="zeile">
  <div class="punkt" style="background:${FARBE[d.zustand]||"#c62828"}"></div>
  <div class="instanz">${d.instanz}</div>
  <div class="dok">${d.dokument||"—"}</div>
  <div class="zustand">${text}</div>
  <div class="zeit">${zeit(a.laufzeit_s)}</div>
  <div>
   ${b("Pausieren","pause",steuerbar&&!d.pausiert)}
   ${b("Fortsetzen","resume",steuerbar&&d.pausiert)}
   ${b("Nach Auftrag beenden","nach_auftrag",steuerbar,"Open MCP CAD "+d.instanz+" beendet sich, sobald der laufende Auftrag fertig ist. Wartende Auftraege werden verworfen.")}
   ${b("Jetzt beenden","jetzt",sicher,"Open MCP CAD "+d.instanz+" sofort beenden? Cadwork selbst wird nicht beendet.")}
  </div>
  ${d.hinweis?`<div class="hinweis">${d.hinweis}</div>`:""}
  <details><summary>Technische Details</summary><pre>${JSON.stringify(d,null,2)}</pre></details>
 </div>`;
}
async function laden(){
 try{
  const r=await fetch("/status");const d=await r.json();
  document.getElementById("liste").innerHTML=d.steckplaetze.map(zeileHtml).join("");
  document.getElementById("stand").textContent="Stand "+d.stand;
 }catch(e){document.getElementById("stand").textContent="Keine Verbindung zur Uebersicht: "+e;}
}
laden();setInterval(laden,1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                                    # keine Zugriffsprotokolle

    def _senden(self, inhalt, typ="application/json; charset=utf-8", code=200):
        daten = inhalt.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def do_GET(self):
        weg = urlparse(self.path).path
        if weg in ("/", "/index.html"):
            return self._senden(SEITE, "text/html; charset=utf-8")
        if weg == "/status":
            import time
            return self._senden(json.dumps({
                "stand": time.strftime("%H:%M:%S"),
                "steckplaetze": cc.alle_status(),
            }))
        self._senden(json.dumps({"ok": False, "error": "not_found"}), code=404)

    def do_POST(self):
        zerlegt = urlparse(self.path)
        if zerlegt.path != "/aktion":
            return self._senden(json.dumps({"ok": False, "error": "not_found"}),
                                code=404)
        p = parse_qs(zerlegt.query)
        instanz = (p.get("instanz") or [""])[0].upper()
        was = (p.get("was") or [""])[0]
        if instanz not in cc.PORT_VON_INSTANZ or was not in AKTIONEN:
            return self._senden(json.dumps({"ok": False, "error": "bad_request",
                                            "message": "Unbekannte Aktion"}),
                                code=400)
        antwort = AKTIONEN[was](instanz)
        self._senden(json.dumps(dict(antwort)))


def main(argv):
    port = STANDARD_PORT
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    adresse = "http://127.0.0.1:%d/" % port
    print("Open MCP CAD Verbindungen (Browser-Rueckfallebene): %s" % adresse)
    print("Beenden mit Strg-C.")
    if "--kein-browser" not in argv:
        webbrowser.open(adresse)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
