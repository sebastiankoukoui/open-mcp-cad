<#
Open MCP CAD - Installation (Plugin + MCP-Server).

    1_INSTALLIEREN.cmd                           (Doppelklick, oben im Paket)
    1_INSTALLIEREN.cmd -Profil "D:\...\3d\API.x64"  anderes Cadwork-Profil
    1_INSTALLIEREN.cmd -OhneServer               nur das Plugin
    1_INSTALLIEREN.cmd -PythonInstallieren       fehlendes Python ohne Rueckfrage holen
    1_INSTALLIEREN.cmd -TrotzdemKopieren         auch in ein Profil, das nicht
                                                 zu Cadwork 2026 gehoert (startet dort nicht)
    1_INSTALLIEREN.cmd -Konsole                  dieses Textfenster statt des
                                                 Einrichtungsfensters

Seit 2026-10-09 oeffnet der Doppelklick OHNE Schalter das Einrichtungsfenster
(install_fenster.ps1, Rueckmeldung: das schwarze Fenster schreckte ab). Das
Fenster stellt seine Fragen vorher und startet DIESE Datei dann mit den
Antworten als Schalter (-Profil, -TrotzdemKopieren, -PythonInstallieren,
-KiNur, -OhnePause) - es gibt nur diese eine Installation. Jeder Schalter
(auch -Konsole) fuehrt wie bisher in dieses Textfenster; scheitert das
Einrichtungsfenster, ebenfalls.

Diese Datei liegt im Paket unter Programmdateien\ (seit 2026-09-29: oben
liegen nur 1_INSTALLIEREN.cmd, die Anleitung als PDF und dieser Ordner).
Alle Pfade hier gehen von ihrem eigenen Ordner aus ($hier).

Was passiert, in dieser Reihenfolge:
  1. Cadwork-Profil waehlen und pruefen. Unter
     C:\Users\Public\Documents\cadwork liegen die Profile userprofil_<Jahr>;
     verglichen wird die Jahreszahl als ZAHL (userprofil_30 ist aelter als
     userprofil_2025). Vorgeschlagen wird userprofil_2026, sonst das
     neueste Profil, zu dem ein Cadwork installiert ist
     (C:\Program Files\cadwork.dir\EXE_<Jahr>).
     Bei mehreren Profilen zeigt der Installer die Liste und fragt.
     Das Plugin braucht Cadwork 3D 2026 (Python 3.14, PyQt6). Gehoert das
     Profil zu einer anderen Version, bricht er ab - ausser nach
     ausdruecklicher Bestaetigung (Frage oder -TrotzdemKopieren).
  2. Der Ordner "Open MCP CAD" wird in dieses Profil kopiert - DARUEBER,
     der Zielordner wird nicht geloescht (dort koennen lokale Dateien wie
     projektordner.txt liegen).
  3. Ein eigenes Python-venv fuer den Server (Standard:
     %LOCALAPPDATA%\OpenMcpCad\python), darin "pip install" des Servers
     mit dem Extra "stubs" (cwapi3d, fuer die API-Hilfe; geht das nicht,
     ohne - das steht dann im Ergebnis).
     Fehlt ein Python 3.10 bis 3.13, wird nach Rueckfrage Python 3.13 per
     winget installiert (Benutzerbereich, ohne Adminrechte). Fehlt winget
     (Windows LTSC, gesperrte Firmen-PCs), laedt er den offiziellen
     Installer von python.org (feste Version, HTTPS), prueft dessen
     Authenticode-Signatur (gueltig, ausgestellt auf die Python Software
     Foundation) und startet ihn erst dann, im Benutzerbereich ohne
     Adminrechte; der Download wird danach geloescht. Ein Python 3.14
     allein genuegt nicht: der Server ist darauf nicht geprueft.
  4. Benutzervariable OPEN_MCP_CAD_PYTHON (fuer den Chat im Plugin).
  5. KI-Programme eintragen (seit 2026-09-29): gefunden werden Codex
     (.codex\config.toml, codex auf dem PATH oder die Codex-App), Claude
     Code (claude) und Claude Desktop (Ordner %APPDATA%\Claude). Fuer
     jedes fragt er "Open MCP CAD in <Programm> eintragen? [J/n]"; vorher
     eine Sicherungskopie mit Zeitstempel, andere Eintraege bleiben, ein
     zweiter Lauf aendert nichts. Er sagt, was er geaendert hat und wie man
     es zuruecknimmt (python -m open_mcp_cad.ki_eintragen, im Server).
     -KiEintragen: ohne Frage in alle gefundenen; -OhneKiEintrag: nie.
     Mit -OhnePause (ohne -KiEintragen) wird nichts eingetragen.
  Am Ende steht fuer JEDEN Teil einzeln, ob er da ist - und was noch fehlt.

Fuer die Gates: "-NurFunktionen" (dot-sourced) laedt nur die Funktionen;
-CadworkWurzel / -CadworkProgramm zeigen auf Attrappen-Ordner.

Keine Adminrechte noetig. Nur ASCII in dieser Datei: Windows PowerShell 5.1
liest Skripte ohne BOM als ANSI, Umlaute kaemen verstuemmelt an.
#>
param(
    [string]$Profil = "",
    [string]$PythonZiel = (Join-Path $env:LOCALAPPDATA "OpenMcpCad\python"),
    [switch]$OhneServer,
    [switch]$PythonInstallieren,
    [switch]$OhneUmgebungsvariable,
    [switch]$OhnePause,
    [switch]$TrotzdemKopieren,
    [switch]$KiEintragen,
    [switch]$OhneKiEintrag,
    [string]$CadworkWurzel = "C:\Users\Public\Documents\cadwork",
    [string]$CadworkProgramm = "C:\Program Files\cadwork.dir",
    # Fuer das Einrichtungsfenster (install_fenster.ps1): nur diese
    # Programme eintragen, ohne Frage (Kommaliste aus ki_eintragen, etwa
    # "codex,claude_desktop"); -File reicht nur Text weiter, keine Liste.
    [string]$KiNur = "",
    # ... den Stand am Ende als JSON in diese Datei, ...
    [string]$ErgebnisDatei = "",
    # ... und die Ausgabe in UTF-8 (Umlaute in Pfaden; sonst Codepage).
    [switch]$Utf8Ausgabe,
    # Nur zum Erzwingen des Textfensters (1_INSTALLIEREN.cmd -Konsole).
    [switch]$Konsole,
    # Die KI fuer den Chat in Cadwork mitinstallieren (seit 2026-10-09):
    # "claude" (Claude Code) oder "codex" (Codex-CLI), je ueber den
    # offiziellen Installer des Herstellers. Im Textfenster meldet er danach
    # gleich an (ohne -OhnePause), das Einrichtungsfenster tut das selbst.
    [ValidateSet("", "claude", "codex")]
    [string]$ChatKi = "",
    [switch]$NurFunktionen
)

$ErrorActionPreference = "Stop"
$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Utf8Ausgabe -and -not $NurFunktionen) {
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
}

# Die einzige Cadwork-Version, fuer die das Plugin gebaut ist (Python 3.14,
# PyQt6). Rueckmeldung Kollege zu 0.1.0 (2026-09-26): in Cadwork 2025
# (Python 3.12, PyQt5) tat der Klick nichts.
$CADWORK_JAHR = 2026
# Hierhin schreibt das Plugin, wenn es beim Klick nicht starten kann.
$START_LOG = "C:\Users\Public\OpenMcpCad_start.log"

# Rueckfall ohne winget (seit 2026-10-01: auf Windows 10 LTSC und
# gesperrten Firmen-PCs fehlt winget, der Installer brach dort mit "bitte
# von python.org installieren" ab). Eine FESTE Version, damit nie etwas
# anderes geladen wird als das, was hier steht (3.13.16, 2026-09-30, laut
# python.org-Server 29 935 584 Bytes; geprueft per HEAD, nicht geladen).
# Ausgefuehrt wird die Datei nur mit gueltiger Authenticode-Signatur,
# deren Zertifikat auf CN=Python Software Foundation lautet.
$PYTHON_ORG_VERSION = "3.13.16"
$PYTHON_ORG_URL = "https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.exe"
$PYTHON_ORG_SIGNIERER = "Python Software Foundation"
# Benutzerbereich (%LOCALAPPDATA%\Programs\Python\Python313), ohne
# Adminrechte: kein py-Launcher (der wird sonst fuer alle Benutzer
# installiert und verlangt Adminrechte), PATH bleibt unberuehrt (Finde-Python
# kennt den Ordner). Am echten Installer NICHT gemessen (hier nie
# heruntergeladen); die Schalter sind die dokumentierten von python.org.
$PYTHON_ORG_ARGUMENTE = @("/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0")

function Schritt([string]$text) {
    Write-Host ""
    Write-Host "== $text" -ForegroundColor Cyan
}

function Cadwork-Installiert([string]$programm) {
    # Jahreszahlen der installierten Cadwork-Programme (EXE_<Jahr>).
    foreach ($d in @(Get-ChildItem -LiteralPath $programm -Directory -ErrorAction SilentlyContinue)) {
        $m = [regex]::Match($d.Name, '(?i)^EXE_(\d+)$')
        if ($m.Success) { [int]$m.Groups[1].Value }
    }
}

function Profil-Name([string]$pfad) {
    # "userprofil_2025" aus einem Pfad, Gross/Klein egal; sonst $null.
    $m = [regex]::Match($pfad, '(?i)(userprofil_(\d+))(\\|/|$)')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Profil-Nummer([string]$pfad) {
    # Die Jahreszahl als ZAHL. Rueckmeldung Kollege zu 0.1.0: als Text
    # absteigend sortiert kam userprofil_30 vor userprofil_2025.
    $m = [regex]::Match($pfad, '(?i)userprofil_(\d+)(\\|/|$)')
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return $null
}

function Profil-Kandidaten([string]$wurzel, [string]$programm) {
    # Alle Profile mit 3d\API.x64, neueste Jahreszahl zuerst.
    $installiert = @(Cadwork-Installiert $programm)
    $liste = @()
    foreach ($d in @(Get-ChildItem -LiteralPath $wurzel -Directory -Filter "userprofil_*" -ErrorAction SilentlyContinue)) {
        $api = Join-Path $d.FullName "3d\API.x64"
        if (-not (Test-Path -LiteralPath $api)) { continue }
        $nr = Profil-Nummer $d.FullName
        if ($null -eq $nr) { $nr = -1 }
        $liste += [pscustomobject]@{
            Name        = $d.Name
            Pfad        = $api
            Nummer      = $nr
            Installiert = ($installiert -contains $nr)
        }
    }
    $liste | Sort-Object -Property @{ Expression = { $_.Nummer }; Descending = $true }, Name
}

function Profil-Vorgabe($kandidaten, [string]$programm) {
    # Zuerst das Profil der Cadwork-Version, fuer die das Plugin gebaut ist
    # ($CADWORK_JAHR) - auch wenn daneben ein neueres Cadwork installiert
    # ist oder EXE_<Jahr> woanders liegt (Gegenpruefung 2026-09-26: mit
    # 2026 und 2027 wurde 2027 vorgeschlagen und dann abgebrochen). Sonst
    # das neueste Profil, zu dem ein Cadwork installiert ist; gibt es keins,
    # das mit der hoechsten Jahreszahl.
    $k = @($kandidaten)
    # VORGABE-JAHR-ANFANG (test_installer I3-K schneidet diesen Block heraus)
    for ($i = 0; $i -lt $k.Count; $i++) {
        if ($k[$i].Nummer -eq $CADWORK_JAHR) {
            if ($k[$i].Installiert) {
                $wie = "installiert unter " + (Join-Path $programm ("EXE_" + $CADWORK_JAHR))
            } else {
                $wie = (Join-Path $programm ("EXE_" + $CADWORK_JAHR)) + " nicht gefunden"
            }
            return [pscustomobject]@{
                Index = $i
                Grund = ("Profil fuer Cadwork " + $CADWORK_JAHR + ", die Version, fuer die das Plugin gebaut ist (" + $wie + ")")
            }
        }
    }
    # VORGABE-JAHR-ENDE
    for ($i = 0; $i -lt $k.Count; $i++) {
        if ($k[$i].Installiert) {
            return [pscustomobject]@{
                Index = $i
                Grund = ("neuestes Profil mit installiertem Cadwork (" + (Join-Path $programm ("EXE_" + $k[$i].Nummer)) + ")")
            }
        }
    }
    return [pscustomobject]@{
        Index = 0
        Grund = ("hoechste Jahreszahl; unter " + $programm + " ist kein passendes EXE_<Jahr> installiert")
    }
}

function Profil-Antwort([string]$antwort, [int]$anzahl, [int]$vorgabe) {
    # Enter = Vorgabe, 1..anzahl = diese Zeile, sonst -1 (nochmal fragen).
    $a = "$antwort".Trim()
    if ($a -eq "") { return $vorgabe }
    $n = 0
    if ([int]::TryParse($a, [ref]$n) -and $n -ge 1 -and $n -le $anzahl) { return ($n - 1) }
    return -1
}

function Version-Pruefen([string]$api, $installiert, [string]$programm) {
    # Passt das Profil zu Cadwork 2026? -> Passt, Nummer, Text (fuer Laien).
    $name = Profil-Name $api
    $nr = Profil-Nummer $api
    if ($null -eq $nr) {
        return [pscustomobject]@{
            Passt  = $false
            Nummer = $null
            Text   = ("Dieses Paket braucht Cadwork 3D $CADWORK_JAHR. Zu welcher Cadwork-Version das Profil " + $api + " gehoert, ist unbekannt (kein userprofil_<Jahr> im Pfad).")
        }
    }
    if ($nr -ne $CADWORK_JAHR) {
        return [pscustomobject]@{
            Passt  = $false
            Nummer = $nr
            Text   = "Dieses Paket braucht Cadwork 3D $CADWORK_JAHR. Gefunden: Cadwork $nr im Profil $name."
        }
    }
    $text = "Cadwork $nr im Profil $name"
    if (@($installiert) -notcontains $nr) {
        $text += (" (Hinweis: " + (Join-Path $programm "EXE_$nr") + " nicht gefunden - Cadwork anders installiert?)")
    }
    return [pscustomobject]@{ Passt = $true; Nummer = $nr; Text = $text }
}

# --- Die KI fuer den Chat in Cadwork (seit 2026-10-09) -------------------
# Der Chat im Plugin startet Claude Code (omcad_a_chat.cli_kandidaten) bzw.
# die Codex-CLI ueber "codex app-server" (omcad_a_anbieter.codex_pfad); die
# ChatGPT-App aus dem Store kann er nicht starten (ihr codex.exe liegt unter
# WindowsApps, "Zugriff verweigert", gemessen 2026-09-24; einen
# Startbefehl "codex.exe" in %LOCALAPPDATA%\Microsoft\WindowsApps legt sie
# nicht an, gemessen 2026-10-09). Installiert wird je mit dem OFFIZIELLEN
# Befehl des Herstellers, ohne Node.js und ohne Adminrechte:
#   Claude Code: irm https://claude.ai/install.ps1 | iex
#     (code.claude.com/docs/en/setup -> %USERPROFILE%\.local\bin\claude.exe)
#   Codex-CLI:   irm https://chatgpt.com/codex/install.ps1 | iex
#     (learn.chatgpt.com/docs/codex/cli; das Skript legt codex.exe nach
#     %LOCALAPPDATA%\Programs\OpenAI\Codex\bin, prueft SHA-256, setzt den
#     PATH des Benutzers)
# Beide Befehle sind an keinem PC dieses Repos ausgefuehrt worden.
$CLI_INSTALL = @{
    claude = "https://claude.ai/install.ps1"
    codex  = "https://chatgpt.com/codex/install.ps1"
}
# Anmelden (oeffnet den Browser) und Stand pruefen (0 = angemeldet, 1 =
# nicht; gemessen an claude 2.1.263 und codex-cli 0.156.1, je mit leerem
# Einstellungsordner in Temp).
$CLI_ANMELDEN = @{ claude = @("auth", "login", "--claudeai"); codex = @("login") }
$CLI_STATUS = @{ claude = @("auth", "status"); codex = @("login", "status") }
$CLI_NAME = @{ claude = "Claude Code"; codex = "Codex" }

function Cli-Pfad([string]$ki) {
    # Wo der Chat im Plugin das Programm sucht, in DERSELBEN Reihenfolge
    # (claude: omcad_a_chat.cli_kandidaten, codex: omcad_a_anbieter.
    # codex_pfad; test_installer I28 vergleicht in denselben Welten).
    # -> voller Pfad oder $null.
    $heim = $env:USERPROFILE
    if (-not $heim) { $heim = [Environment]::GetFolderPath("UserProfile") }
    if ($ki -eq "claude") {
        $fest = @((Join-Path $heim ".local\bin\claude.exe"))
        if ($env:APPDATA) { $fest += (Join-Path $env:APPDATA "npm\claude.cmd") }
        $namen = @("claude.exe", "claude.cmd")
    } elseif ($ki -eq "codex") {
        $fest = @()
        if ($env:CODEX_INSTALL_DIR) { $fest += (Join-Path $env:CODEX_INSTALL_DIR "codex.exe") }
        if ($env:LOCALAPPDATA) { $fest += (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe") }
        if ($env:APPDATA) { $fest += (Join-Path $env:APPDATA "npm\codex.cmd") }
        $namen = @("codex.exe", "codex.cmd")
    } else {
        return $null
    }
    foreach ($k in $fest) { if (Test-Path -LiteralPath $k -PathType Leaf) { return $k } }
    foreach ($n in $namen) {
        $g = Im-Pfad $n
        # Die Store-App (WindowsApps) laesst sich von aussen nicht starten
        # (nur bei Codex geprueft, wie omcad_a_anbieter.codex_pfad).
        if ($g -and -not ($ki -eq "codex" -and $g -match '\\WindowsApps\\')) { return $g }
    }
    return $null
}

function Cli-Befehl-Ausfuehren([string]$url) {
    # Genau der offizielle Weg ("irm <url> | iex") in einer eigenen
    # Windows PowerShell; die Ausgabe geht ins Fenster. -> Rueckgabewert.
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $befehl = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; irm '" + $url + "' | iex"
    & $ps -NoProfile -ExecutionPolicy Bypass -Command $befehl | Out-Host
    return $LASTEXITCODE
}

function Cli-Installieren([string]$ki) {
    # -> Ok, Pfad, Text. Ist das Programm schon da, wird nichts geladen.
    $name = $CLI_NAME[$ki]
    $da = Cli-Pfad $ki
    if ($da) {
        return [pscustomobject]@{ Ok = $true; Pfad = $da; Text = ($name + " war schon da: " + $da) }
    }
    Write-Host ("Lade das offizielle Installationsprogramm von " + $name + ": " + $CLI_INSTALL[$ki])
    try {
        $rc = Cli-Befehl-Ausfuehren $CLI_INSTALL[$ki]
    } catch {
        return [pscustomobject]@{ Ok = $false; Pfad = $null; Text = ($name + ": Installation ging nicht (" + $_.Exception.Message + ")") }
    }
    $pfad = Cli-Pfad $ki
    if (-not $pfad) {
        return [pscustomobject]@{ Ok = $false; Pfad = $null; Text = ($name + ": nach der Installation nicht gefunden (Rueckgabe " + $rc + "). Internet pruefen und nochmals starten.") }
    }
    $sig = ""
    try {
        $s = Get-AuthenticodeSignature -LiteralPath $pfad
        $sig = " - Signatur " + $s.Status
        if ($s.SignerCertificate) { $sig += " (" + $s.SignerCertificate.Subject.Split(",")[0] + ")" }
    } catch { }
    return [pscustomobject]@{ Ok = $true; Pfad = $pfad; Text = ($name + " installiert: " + $pfad + $sig) }
}

function Cli-Angemeldet([string]$ki, [string]$pfad) {
    # Rueckgabe 0 von "claude auth status" bzw. "codex login status" =
    # angemeldet. Wirft nie.
    try {
        $ErrorActionPreference = "Continue"
        $argumente = $CLI_STATUS[$ki]
        $null = & $pfad @argumente 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Zusammenfassung($stand) {
    # Jeder Teil einzeln - nie "fertig", wenn ein Teil fehlt.
    $zeilen = @()
    switch ($stand.Server) {
        "ok"            { $zeilen += ("MCP-Server:     installiert und getestet (" + $stand.ServerText + ")") }
        "uebersprungen" { $zeilen += "MCP-Server:     nicht eingerichtet (-OhneServer)" }
        default         { $zeilen += ("MCP-Server:     NICHT eingerichtet - " + $stand.ServerText) }
    }
    switch ($stand.Plugin) {
        "ok"      { $zeilen += ("Cadwork-Plugin: kopiert nach " + $stand.Profil + ", Cadwork-Version passt (" + $stand.PluginText + ")") }
        "version" { $zeilen += ("Cadwork-Plugin: kopiert nach " + $stand.Profil + ", ABER die Cadwork-Version passt NICHT: " + $stand.PluginText) }
        default   { $zeilen += ("Cadwork-Plugin: NICHT kopiert - " + $stand.PluginText) }
    }
    if ($stand.Python) {
        $zeilen += ("Python:         " + $stand.Python)
    }
    if ($stand.KI) {
        $zeilen += ("KI-Programme:   " + $stand.KI)
    }
    if ($stand.Chat) {
        $zeilen += ("Chat-KI:        " + $stand.Chat)
    }
    if ($stand.Plugin -eq "ok" -or $stand.Plugin -eq "version") {
        $zeilen += ("Noch offen:     in Cadwork einmal auf 'Open MCP CAD' klicken. Klappt es nicht, steht der Grund in " + $START_LOG)
    }
    $fertig = ($stand.Plugin -eq "ok") -and ($stand.Server -eq "ok" -or $stand.Server -eq "uebersprungen")
    # Die KI fuer den Chat, wenn sie gewollt war (-ChatKi), gehoert dazu.
    if ($stand.Chat -and -not $stand.ChatOk) { $fertig = $false }
    if ($fertig -and $stand.Server -eq "ok") {
        $zeilen += "Beide Teile sind installiert. Offen ist nur noch der erste Klick in Cadwork."
    } elseif ($fertig) {
        $zeilen += "Das Plugin ist installiert, der Server wurde mit -OhneServer ausgelassen."
    } else {
        $zeilen += "NICHT vollstaendig installiert - oben steht, was fehlt."
    }
    return [pscustomobject]@{ Fertig = $fertig; Zeilen = $zeilen }
}

function Finde-Python {
    # Der py-Launcher zuerst (er kennt alle installierten Versionen), dann
    # python auf dem PATH. Der Store-Platzhalter "python.exe" in WindowsApps
    # liefert keine Version und faellt deshalb heraus.
    $kandidaten = @()
    foreach ($v in @("3.13", "3.12", "3.11", "3.10")) {
        $kandidaten += , @("py", "-$v")
    }
    $kandidaten += , @("python")
    # Frisch installiert steht Python oft noch nicht im PATH dieser Sitzung.
    foreach ($v in @("313", "312", "311", "310")) {
        $kandidaten += , @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"))
        $kandidaten += , @((Join-Path $env:ProgramFiles "Python$v\python.exe"))
    }
    foreach ($k in $kandidaten) {
        $befehl = $k[0]
        $rest = @($k | Select-Object -Skip 1)
        if (-not (Get-Command $befehl -ErrorAction SilentlyContinue)) { continue }
        try {
            $version = & $befehl @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch {
            continue
        }
        if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
        $teile = "$version".Trim().Split(".")
        $haupt = [int]$teile[0]
        $neben = [int]$teile[1]
        if ($haupt -eq 3 -and $neben -ge 10 -and $neben -le 13) {
            return , $k
        }
    }
    return $null
}

function Python-Weg {
    # "winget", wenn winget als Programm auf dem PATH liegt, sonst
    # "python.org" (Rueckfall, siehe $PYTHON_ORG_URL).
    if (Get-Command winget -CommandType Application -ErrorAction SilentlyContinue) { return "winget" }
    return "python.org"
}

function Python-Frage([string]$weg) {
    # Die Rueckfrage nennt, woher Python kommt.
    if ($weg -eq "winget") {
        return "Python 3.13 jetzt installieren (winget, Benutzerbereich, ohne Adminrechte)? [J/n]"
    }
    return ("Python " + $PYTHON_ORG_VERSION + " jetzt von python.org herunterladen (ca. 30 MB) und installieren (Benutzerbereich, ohne Adminrechte)? [J/n]")
}

function Python-Herunterladen([string]$url, [string]$ziel) {
    # Wirft bei jedem Fehler. TLS 1.2 dazu: Windows PowerShell 5.1 bietet
    # je nach .NET-Stand sonst nur TLS 1.0/1.1 an, das python.org ablehnt.
    # Ohne Fortschrittsbalken ist Invoke-WebRequest in 5.1 ein Vielfaches
    # schneller.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $alt = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $url -OutFile $ziel -UseBasicParsing
    } finally {
        $ProgressPreference = $alt
    }
}

function Python-Signatur([string]$datei) {
    return (Get-AuthenticodeSignature -LiteralPath $datei)
}

function Signatur-Grund($sig) {
    # $null = gut (Status Valid UND Zertifikat auf CN=Python Software
    # Foundation), sonst der Grund als Text.
    if (-not $sig) { return "keine Signatur gelesen" }
    if ("$($sig.Status)" -ne "Valid") { return ("Signatur nicht gueltig (" + $sig.Status + ")") }
    $wer = ""
    if ($sig.SignerCertificate) { $wer = "$($sig.SignerCertificate.Subject)" }
    # SIGNIERER-ANFANG (test_installer I20-K schneidet diesen Block heraus)
    $cn = [regex]::Match($wer, '(?:^|,)\s*CN=([^,]*)')
    if (-not $cn.Success -or $cn.Groups[1].Value.Trim() -ne $PYTHON_ORG_SIGNIERER) {
        return ("unterschrieben von '" + $wer + "', nicht von der " + $PYTHON_ORG_SIGNIERER)
    }
    # SIGNIERER-ENDE
    return $null
}

function Python-Setup-Starten([string]$datei) {
    # -> Rueckgabewert des Installers (0 = gut, 3010 = gut, Neustart offen).
    $p = Start-Process -FilePath $datei -ArgumentList $PYTHON_ORG_ARGUMENTE -Wait -PassThru
    return $p.ExitCode
}

function Python-Von-PythonOrg {
    # Laden, Signatur pruefen, erst dann starten; der Download wird in
    # JEDEM Fall wieder geloescht. -> Ok, Text (fuer das Ergebnis).
    $datei = Join-Path ([IO.Path]::GetTempPath()) ("open-mcp-cad-python-" + $PYTHON_ORG_VERSION + "-" + [guid]::NewGuid().ToString("N") + ".exe")
    $selbst = " Python 3.13 von https://www.python.org/downloads/windows/ selbst installieren und 1_INSTALLIEREN.cmd erneut starten."
    try {
        Write-Host ("Lade " + $PYTHON_ORG_URL + " ...")
        try {
            Python-Herunterladen $PYTHON_ORG_URL $datei
        } catch {
            return [pscustomobject]@{ Ok = $false; Text = ("Download von python.org ging nicht (" + $_.Exception.Message + "). Internet oder Proxy pruefen, oder" + $selbst) }
        }
        if (-not (Test-Path -LiteralPath $datei)) {
            return [pscustomobject]@{ Ok = $false; Text = ("Download von python.org ergab keine Datei." + $selbst) }
        }
        # PRUEFUNG-ANFANG (test_installer I20-K schneidet diesen Block heraus)
        $grund = Signatur-Grund (Python-Signatur $datei)
        if ($grund) {
            return [pscustomobject]@{ Ok = $false; Text = ("Python-Installer von python.org NICHT ausgefuehrt: " + $grund + "." + $selbst) }
        }
        # PRUEFUNG-ENDE
        Write-Host ("Signatur geprueft (" + $PYTHON_ORG_SIGNIERER + "). Installiere Python " + $PYTHON_ORG_VERSION + " (Benutzerbereich, ohne Adminrechte) ...")
        $rc = Python-Setup-Starten $datei
        if ($rc -ne 0 -and $rc -ne 3010) {
            return [pscustomobject]@{ Ok = $false; Text = ("Python-Installer von python.org meldete Fehler " + $rc + "." + $selbst) }
        }
        return [pscustomobject]@{ Ok = $true; Text = ("Python " + $PYTHON_ORG_VERSION + " von python.org installiert (Signatur der " + $PYTHON_ORG_SIGNIERER + " geprueft, Benutzerbereich)") }
    } finally {
        # LOESCHEN-ANFANG (test_installer I20-K schneidet diesen Block heraus)
        Remove-Item -LiteralPath $datei -Force -ErrorAction SilentlyContinue
        # LOESCHEN-ENDE
    }
}

function Python-Installieren([string]$weg) {
    # Rueckmeldung 2026-09-24: auf einem Rechner ohne Python brach der
    # Installer nach dem Kopieren des Plugins ab - das Plugin stand im Menue,
    # der Server fehlte. Deshalb holt er Python selbst: per winget, und wo
    # winget fehlt, direkt von python.org (seit 2026-10-01). -> Ok, Text.
    if (-not $weg) { $weg = Python-Weg }
    if ($weg -eq "winget") {
        Write-Host "Installiere Python 3.13 (winget, Benutzerbereich) ..."
        & winget install --id Python.Python.3.13 -e --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        if ($LASTEXITCODE -eq 0) {
            $r = [pscustomobject]@{ Ok = $true; Text = "Python 3.13 per winget installiert (Benutzerbereich)" }
        } else {
            $r = [pscustomobject]@{ Ok = $false; Text = ("winget meldete Fehler " + $LASTEXITCODE + " beim Installieren von Python 3.13") }
        }
    } else {
        Write-Host "winget fehlt auf diesem Rechner (etwa Windows LTSC oder ein gesperrter Firmen-PC). Python kommt direkt von python.org."
        $r = Python-Von-PythonOrg
    }
    # PATH neu lesen, damit py/python dieser Sitzung das neue Python finden.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    return $r
}

function Server-Installieren([string]$vpy, [string]$quelle) {
    # Rueckmeldung 2026-09-28: ohne das Extra "stubs" fehlte das Paket
    # cwapi3d, und get_cadwork_api_help konnte kein Modul nachschlagen.
    # Deshalb mit Extra; scheitert das (etwa weil cwapi3d fuer dieses
    # Python fehlt), der Server ohne - er laeuft auch so, nur ohne API-Hilfe.
    # pip nimmt "<ordner>[stubs]" auch mit Leerzeichen im Pfad (gemessen an
    # pip 25.0.1: Ordner + Extra stubs). Ausgabe an Out-Host, sonst landete
    # sie im Rueckgabewert.
    & $vpy -m pip install --disable-pip-version-check --upgrade ($quelle + "[stubs]") | Out-Host
    if ($LASTEXITCODE -eq 0) {
        return [pscustomobject]@{ Ok = $true; Stubs = $true }
    }
    Write-Host "Mit API-Hilfe (cwapi3d) ging es nicht - installiere den Server ohne." -ForegroundColor Yellow
    & $vpy -m pip install --disable-pip-version-check --upgrade $quelle | Out-Host
    return [pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Stubs = $false }
}

function Ja-Frage([string]$text) {
    # Enter = ja (die Vorgabe steht gross in [J/n]).
    $antwort = Read-Host $text
    return ($antwort -match '^\s*(j|ja|y|yes)?\s*$')
}

function KI-Programme-Eintragen([string]$helfer, [string]$serverPy, [scriptblock]$frage, [bool]$alle) {
    # $helfer: ein Python, in dem open_mcp_cad liegt (das Server-venv).
    # Die Arbeit tut python -m open_mcp_cad.ki_eintragen (JSON lesen und
    # schreiben ist in PowerShell 5.1 eine Falle: ConvertTo-Json kuerzt ab
    # Tiefe 2 und schreibt Umlaute um). -> Liste der Ergebnisse.
    $ergebnisse = @()
    $zeile = & $helfer -m open_mcp_cad.ki_eintragen finden | Select-Object -Last 1
    try { $gefunden = $zeile | ConvertFrom-Json } catch { $gefunden = $null }
    if (-not $gefunden -or $gefunden.fehler) {
        Write-Host ("Suche nach KI-Programmen ging nicht: " + $zeile) -ForegroundColor Yellow
        return , @([pscustomobject]@{ Name = "?"; Status = "fehler"; Text = "$zeile" })
    }
    $programme = @($gefunden.programme)
    if ($programme.Count -eq 0) {
        Write-Host "Kein KI-Programm gefunden (Codex, Claude Code, Claude Desktop)."
        Write-Host "Richte eines ein (siehe Anleitung) und starte 1_INSTALLIEREN.cmd danach nochmals."
        return , @()
    }
    foreach ($p in $programme) {
        Write-Host ""
        Write-Host ("Gefunden: " + $p.name + "  (" + $p.ort + ")")
        # $p geht mit: das Einrichtungsfenster antwortet nach p.programm.
        if ($alle) { $ja = $true } else { $ja = [bool](& $frage ("Open MCP CAD in " + $p.name + " eintragen? [J/n]") $p) }
        if (-not $ja) {
            Write-Host "  nicht eingetragen (so gewollt)."
            $ergebnisse += [pscustomobject]@{ Name = $p.name; Status = "abgelehnt"; Text = "" }
            continue
        }
        $zeile = & $helfer -m open_mcp_cad.ki_eintragen eintragen $p.programm --python $serverPy | Select-Object -Last 1
        try { $antwort = $zeile | ConvertFrom-Json } catch { $antwort = $null }
        if (-not $antwort -or $antwort.fehler) {
            Write-Host ("  FEHLER: " + $zeile) -ForegroundColor Yellow
            $ergebnisse += [pscustomobject]@{ Name = $p.name; Status = "fehler"; Text = "$zeile" }
            continue
        }
        foreach ($e in @($antwort.ergebnisse)) {
            $farbe = "Green"
            if ($e.status -eq "fehler" -or $e.status -eq "abweichend") { $farbe = "Yellow" }
            Write-Host ("  " + $e.status + ": " + $e.text) -ForegroundColor $farbe
            if ($e.sicherung) { Write-Host ("  Sicherung:    " + $e.sicherung) }
            if ($e.rueckgaengig) { Write-Host ("  Rueckgaengig: " + $e.rueckgaengig) }
            $ergebnisse += [pscustomobject]@{ Name = $e.name; Status = $e.status; Text = $e.text }
        }
    }
    return , $ergebnisse
}

function KI-Nur-Frage([string]$liste) {
    # -KiNur (aus dem Einrichtungsfenster, das schon gefragt hat): die
    # Frage je Programm beantwortet die Liste - "ja" genau fuer die ids
    # darin (codex, claude_code, claude_desktop), sonst "nein".
    $nur = @($liste.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    return { param($t, $p) return ($nur -contains "$($p.programm)") }.GetNewClosure()
}

function KI-Zeile($ergebnisse) {
    # Eine Zeile fuer das Ergebnis: je Programm, was geschah.
    $teile = @()
    foreach ($e in @($ergebnisse)) {
        switch ($e.Status) {
            "eingetragen" { $teile += ($e.Name + " eingetragen") }
            "schon_da"    { $teile += ($e.Name + " war schon eingetragen") }
            "abgelehnt"   { $teile += ($e.Name + " nicht gewollt") }
            "abweichend"  { $teile += ($e.Name + " hat einen anderen Eintrag (siehe oben)") }
            default       { $teile += ($e.Name + " FEHLER (siehe oben)") }
        }
    }
    if ($teile.Count -eq 0) { return "keins gefunden - siehe 2_ANLEITUNG.pdf, danach 1_INSTALLIEREN.cmd nochmals" }
    return ($teile -join "; ")
}

function Im-Pfad([string]$name) {
    # Wie shutil.which(name, path=PATH) fuer einen Namen MIT Endung: die
    # erste Datei dieses Namens in einem Ordner des PATH, sonst $null.
    foreach ($o in @("$env:Path".Split(";"))) {
        if (-not $o) { continue }
        try { $k = Join-Path $o $name } catch { continue }
        if (Test-Path -LiteralPath $k -PathType Leaf) { return $k }
    }
    return $null
}

function KI-Finden {
    # Welche KI-Programme da sind, fuer das Einrichtungsfenster VOR der
    # Installation: auf einem frischen PC gibt es dann noch kein Python fuer
    # open_mcp_cad.ki_eintragen. DIESELBE Suche wie dessen finden() - nur
    # lesen, nichts aendern; test_installer I21 vergleicht beide in
    # denselben Welten. Eingetragen wird spaeter IMMER ueber ki_eintragen.
    # -> Liste von @{ programm; name }, Reihenfolge wie finden().
    $aus = @()
    $heim = $env:USERPROFILE
    if (-not $heim) { $heim = [Environment]::GetFolderPath("UserProfile") }
    $codexHeim = $env:CODEX_HOME
    if (-not $codexHeim) { $codexHeim = Join-Path $heim ".codex" }
    $app = @()
    if ($env:LOCALAPPDATA) {
        # Die ChatGPT-Desktop-App mit Codex (frueher "Codex-App"): Store-
        # Paket OpenAI.Codex_2p2nqsd0c76g0, im Startmenue "ChatGPT"
        # (gemessen 2026-10-09, Get-AppxPackage / Get-StartApps).
        $app = @(Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA "Packages") -Filter "OpenAI.Codex_*" -ErrorAction SilentlyContinue)
    }
    if ((Test-Path -LiteralPath (Join-Path $codexHeim "config.toml") -PathType Leaf) -or
        (Test-Path -LiteralPath $codexHeim -PathType Container) -or
        (Im-Pfad "codex.cmd") -or (Im-Pfad "codex.exe") -or $app.Count -gt 0) {
        $aus += [pscustomobject]@{ programm = "codex"; name = "Codex" }
    }
    $claude = @((Join-Path $heim ".local\bin\claude.exe"))
    if ($env:APPDATA) { $claude += (Join-Path $env:APPDATA "npm\claude.cmd") }
    $da = $false
    foreach ($k in $claude) { if (Test-Path -LiteralPath $k -PathType Leaf) { $da = $true } }
    if ($da -or (Im-Pfad "claude.exe") -or (Im-Pfad "claude.cmd")) {
        $aus += [pscustomobject]@{ programm = "claude_code"; name = "Claude Code" }
    }
    $desktop = @()
    if ($env:APPDATA) { $desktop += (Join-Path $env:APPDATA "Claude") }
    if ($env:LOCALAPPDATA) {
        foreach ($d in @(Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue)) {
            $desktop += (Join-Path $d.FullName "LocalCache\Roaming\Claude")
        }
    }
    $da = $false
    foreach ($k in $desktop) { if (Test-Path -LiteralPath $k -PathType Container) { $da = $true } }
    if ($da) {
        $aus += [pscustomobject]@{ programm = "claude_desktop"; name = "Claude Desktop" }
    }
    return , $aus
}

function Ergebnis-Schreiben([string]$datei, $stand, $ergebnis, $ki, $fehler) {
    # Fuer das Einrichtungsfenster: der Stand als JSON (UTF-8). Wirft nie.
    try {
        $liste = @()
        foreach ($e in @($ki)) { if ($e) { $liste += @{ name = "$($e.Name)"; status = "$($e.Status)" } } }
        $text = $null
        if ($fehler) { $text = "$($fehler.Exception.Message)" }
        $daten = @{
            fertig = [bool]$ergebnis.Fertig; plugin = "$($stand.Plugin)"; pluginText = "$($stand.PluginText)"
            server = "$($stand.Server)"; serverText = "$($stand.ServerText)"; profil = "$($stand.Profil)"
            python = "$($stand.Python)"; ki = "$($stand.KI)"; kiListe = $liste; fehler = $text
            zeilen = @($ergebnis.Zeilen)
            chat = "$($stand.Chat)"; chatOk = [bool]$stand.ChatOk; chatPfad = "$($stand.ChatPfad)"
        }
        $json = ConvertTo-Json -InputObject $daten -Depth 5
        [IO.File]::WriteAllText($datei, $json, (New-Object System.Text.UTF8Encoding $false))
    } catch { }
}

if ($NurFunktionen) { return }

# Was am Ende gemeldet wird. Jeder Teil fuer sich: Rueckmeldung Kollege zu
# 0.1.0 - "erfolgreich" stand da, obwohl nur der Server geprueft war.
$stand = @{
    Server     = $null
    ServerText = "abgebrochen, bevor der Server an der Reihe war"
    Plugin     = "fehlt"
    PluginText = "abgebrochen"
    Profil     = ""
    Python     = ""
    KI         = ""
    Chat       = ""
    ChatOk     = $false
    ChatPfad   = ""
}
if ($OhneServer) { $stand.Server = "uebersprungen" }
# Fuenf Schritte, mit -ChatKi sechs (das Einrichtungsfenster liest "n/N").
$SCHRITTE = 5
if ($ChatKi) { $SCHRITTE = 6 }
$phase = "plugin"
$fehler = $null
$ergebnis = $null
$ki = @()
try {
    # --- 1. Profil waehlen und Cadwork-Version pruefen ---------------------
    Schritt ("1/" + $SCHRITTE + " Cadwork-Profil waehlen und Version pruefen")
    $installiert = @(Cadwork-Installiert $CadworkProgramm)
    if ($Profil) {
        $grund = "mit -Profil angegeben"
    } else {
        $kandidaten = @(Profil-Kandidaten $CadworkWurzel $CadworkProgramm)
        if ($kandidaten.Count -eq 0) {
            throw "Kein Cadwork-Profil unter $CadworkWurzel gefunden. Den Ordner ...\3d\API.x64 mit -Profil angeben."
        }
        $vorgabe = Profil-Vorgabe $kandidaten $CadworkProgramm
        $wahl = $vorgabe.Index
        $grund = $vorgabe.Grund
        if ($kandidaten.Count -gt 1) {
            Write-Host "Mehrere Cadwork-Profile gefunden:"
            for ($i = 0; $i -lt $kandidaten.Count; $i++) {
                $k = $kandidaten[$i]
                if ($k.Installiert) {
                    $info = "Cadwork " + $k.Nummer + " installiert"
                } else {
                    $info = "kein " + (Join-Path $CadworkProgramm ("EXE_" + $k.Nummer))
                }
                $marke = ""
                if ($i -eq $wahl) { $marke = "   <- Vorgabe" }
                Write-Host ("  [{0}] {1}   ({2}){3}" -f ($i + 1), $k.Pfad, $info, $marke)
            }
            if (-not $OhnePause) {
                do {
                    $antwort = Read-Host ("Welches Profil? Zahl eingeben, Enter = " + ($vorgabe.Index + 1))
                    $wahl = Profil-Antwort $antwort $kandidaten.Count $vorgabe.Index
                    if ($wahl -lt 0) { Write-Host ("Bitte eine Zahl von 1 bis " + $kandidaten.Count + " eingeben.") }
                } while ($wahl -lt 0)
                if ($wahl -ne $vorgabe.Index) { $grund = "von Hand gewaehlt" }
            } else {
                $grund += " - ohne Rueckfrage (-OhnePause)"
            }
        } else {
            $grund = "einziges Cadwork-Profil unter $CadworkWurzel"
        }
        $Profil = $kandidaten[$wahl].Pfad
    }
    if (-not (Test-Path -LiteralPath $Profil)) { throw "Profilordner gibt es nicht: $Profil" }
    $stand.Profil = $Profil
    $version = Version-Pruefen $Profil $installiert $CadworkProgramm
    Write-Host "Profil:  $Profil"
    Write-Host "Warum:   $grund"
    if ($version.Passt) {
        Write-Host ("Cadwork: " + $version.Text + " - passt.") -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host $version.Text -ForegroundColor Yellow
        Write-Host "Das Plugin startet dort nicht: es braucht Python 3.14 und PyQt6 aus Cadwork 3D $CADWORK_JAHR." -ForegroundColor Yellow
        $ja = [bool]$TrotzdemKopieren
        if (-not $ja -and -not $OhnePause) {
            $antwort = Read-Host "Trotzdem in dieses Profil kopieren? [j/N]"
            $ja = ($antwort -match '^\s*(j|ja|y|yes)\s*$')
        }
        if (-not $ja) {
            $stand.PluginText = $version.Text + " Nichts kopiert."
            throw ($version.Text + " Nichts kopiert, abgebrochen. Anderes Profil angeben: 1_INSTALLIEREN.cmd -Profil ""...\userprofil_$CADWORK_JAHR\3d\API.x64""")
        }
        Write-Host "Kopiert wird trotzdem (ausdruecklich bestaetigt)." -ForegroundColor Yellow
    }

    # --- 2. Plugin ---------------------------------------------------------
    Schritt ("2/" + $SCHRITTE + " Plugin nach Cadwork kopieren")
    $pluginZiel = Join-Path $Profil "Open MCP CAD"
    New-Item -ItemType Directory -Force -Path $pluginZiel | Out-Null
    Copy-Item -Path (Join-Path $hier "Open MCP CAD\*") -Destination $pluginZiel -Recurse -Force
    # Die Anleitung (oben im Paket) auch neben das Plugin: der Chat oeffnet
    # sie mit "Anleitung oeffnen" (Dashboard ANLEITUNG_DATEI, 2026-09-29).
    $anleitung = Join-Path (Split-Path -Parent $hier) "2_ANLEITUNG.pdf"
    if (Test-Path -LiteralPath $anleitung) {
        Copy-Item -LiteralPath $anleitung -Destination (Join-Path $pluginZiel "ANLEITUNG.pdf") -Force
    }
    Write-Host "Plugin: $pluginZiel"
    if ($version.Passt) { $stand.Plugin = "ok" } else { $stand.Plugin = "version" }
    $stand.PluginText = $version.Text
    # Die Ordner "Open MCP CAD A".."F" aus dem Quellcode-Repo sind Pruef-
    # Ordner (feste Ports, ohne Fenster) und gehoeren nicht nach Cadwork.
    # Wer den ganzen Ordner cad_plugin kopiert hat, sieht sie im Menue -
    # ein Klick darauf oeffnet kein Fenster. Nur melden, nie loeschen.
    $fremde = @(Get-ChildItem -LiteralPath $Profil -Directory -Filter "Open MCP CAD ?" -ErrorAction SilentlyContinue)
    if ($fremde.Count -gt 0) {
        Write-Host ""
        Write-Host "ACHTUNG: alte Pruef-Ordner im Cadwork-Profil gefunden:" -ForegroundColor Yellow
        foreach ($f in $fremde) { Write-Host ("  " + $f.FullName) -ForegroundColor Yellow }
        Write-Host "Diese Ordner bitte loeschen (Cadwork vorher schliessen). Benutzt wird nur 'Open MCP CAD'." -ForegroundColor Yellow
    }

    if (-not $OhneServer) {
        # --- 3. Server ----------------------------------------------------
        $phase = "server"
        $stand.ServerText = "abgebrochen"
        Schritt ("3/" + $SCHRITTE + " MCP-Server einrichten")
        $py = Finde-Python
        if (-not $py) {
            Write-Host "Kein Python 3.10 bis 3.13 gefunden (ein Python 3.14 allein reicht nicht)."
            $weg = Python-Weg
            $ja = $PythonInstallieren
            if (-not $ja -and -not $OhnePause) {
                $antwort = Read-Host (Python-Frage $weg)
                $ja = ($antwort -match '^\s*(j|ja|y|yes)?\s*$')
            }
            if ($ja) {
                $pyInst = Python-Installieren $weg
                $stand.Python = $pyInst.Text
                $py = Finde-Python
                if ($pyInst.Ok -and -not $py) {
                    $stand.Python += " - aber danach kein Python 3.10 bis 3.13 gefunden"
                }
            } else {
                $stand.Python = "fehlt, nicht installiert (Rueckfrage verneint oder -OhnePause)"
            }
        }
        if (-not $py) {
            throw "Kein Python 3.10 bis 3.13 gefunden. Python 3.13 installieren (python.org) und 1_INSTALLIEREN.cmd erneut starten."
        }
        $pyBefehl = $py[0]
        $pyRest = @($py | Select-Object -Skip 1)
        Write-Host ("Python: " + ($py -join " "))
        if (-not (Test-Path (Join-Path $PythonZiel "Scripts\python.exe"))) {
            & $pyBefehl @pyRest -m venv $PythonZiel
            if ($LASTEXITCODE -ne 0) { throw "venv konnte nicht angelegt werden: $PythonZiel" }
        }
        $vpy = Join-Path $PythonZiel "Scripts\python.exe"
        $pip = Server-Installieren $vpy (Join-Path $hier "server")
        if (-not $pip.Ok) { throw "pip install des Servers ist fehlgeschlagen (Internet?)." }
        & $vpy -c "import open_mcp_cad.server"
        if ($LASTEXITCODE -ne 0) { throw "Der Server laesst sich nicht laden." }
        Write-Host "Server: $vpy -m open_mcp_cad.server"

        # --- 4. Umgebungsvariable ------------------------------------------
        Schritt ("4/" + $SCHRITTE + " Umgebungsvariable fuer den Chat im Plugin")
        if ($OhneUmgebungsvariable) {
            Write-Host "uebersprungen (-OhneUmgebungsvariable)"
        } else {
            [Environment]::SetEnvironmentVariable("OPEN_MCP_CAD_PYTHON", $vpy, "User")
            Write-Host "OPEN_MCP_CAD_PYTHON = $vpy  (wirkt nach dem naechsten Cadwork-Start)"
        }
        $stand.Server = "ok"
        $stand.ServerText = "$vpy -m open_mcp_cad.server"
        if (-not $pip.Stubs) {
            $stand.ServerText += "; OHNE API-Hilfe (cwapi3d fehlt: $vpy -m pip install cwapi3d)"
        }

        # --- 5. KI-Programme eintragen (Rueckmeldung 2026-09-29) ----------
        # pythonw.exe: python.exe ist ein Konsolenprogramm, und das
        # KI-Programm oeffnete bei jedem Serverstart ein schwarzes Fenster.
        $vpyw = Join-Path $PythonZiel "Scripts\pythonw.exe"
        $serverPy = $vpy
        if (Test-Path $vpyw) { $serverPy = $vpyw }
        Schritt ("5/" + $SCHRITTE + " KI-Programme eintragen")
        $ki = @()
        if ($OhneKiEintrag) {
            Write-Host "uebersprungen (-OhneKiEintrag)"
            $stand.KI = "nicht eingetragen (-OhneKiEintrag)"
        } elseif ($OhnePause -and -not $KiEintragen -and -not $KiNur) {
            Write-Host "uebersprungen (-OhnePause ohne -KiEintragen: ohne Frage wird nichts eingetragen)"
            $stand.KI = "nicht eingetragen (ohne Rueckfrage)"
        } else {
            # Mit -KiNur hat das Einrichtungsfenster schon gefragt: genau
            # die gewaehlten Programme, die anderen gelten als abgelehnt.
            $frage = ${function:Ja-Frage}
            if ($KiNur) { $frage = KI-Nur-Frage $KiNur }
            try {
                $ki = KI-Programme-Eintragen $vpy $serverPy $frage ([bool]$KiEintragen)
                $stand.KI = KI-Zeile $ki
            } catch {
                Write-Host ("KI-Programme eintragen ging nicht: " + $_.Exception.Message) -ForegroundColor Yellow
                $stand.KI = "FEHLER beim Eintragen: " + $_.Exception.Message
                $ki = @([pscustomobject]@{ Name = "?"; Status = "fehler"; Text = "" })
            }
        }
        $offen = @($ki | Where-Object { $_.Status -ne "eingetragen" -and $_.Status -ne "schon_da" })
        if ($ki.Count -eq 0 -or $offen.Count -gt 0) {
            # Von Hand, fuer alles, was nicht eingetragen ist.
            $json = $serverPy.Replace("\", "\\")
            Write-Host ""
            Write-Host "Von Hand eintragen (Details: Programmdateien\ANLEITUNG.md):" -ForegroundColor Green
            Write-Host "  Claude Desktop (%APPDATA%\Claude\claude_desktop_config.json):"
            Write-Host ('    "open-mcp-cad": { "command": "' + $json + '", "args": ["-m", "open_mcp_cad.server"] }')
            Write-Host "  Claude Code:"
            Write-Host ('    claude mcp add --scope user open-mcp-cad -- "' + $serverPy + '" -m open_mcp_cad.server')
            Write-Host "  ChatGPT / Codex (%USERPROFILE%\.codex\config.toml):"
            Write-Host "    [mcp_servers.open-mcp-cad]"
            Write-Host ("    command = '" + $serverPy + "'")
            Write-Host '    args = ["-m", "open_mcp_cad.server"]'
        }
    }

    if ($ChatKi) {
        # --- 6. Die KI fuer den Chat in Cadwork (seit 2026-10-09) -------
        $phase = "chat"
        $stand.Chat = "abgebrochen"
        Schritt ("6/" + $SCHRITTE + " KI fuer den Chat in Cadwork einrichten")
        $cli = Cli-Installieren $ChatKi
        $stand.Chat = $cli.Text
        $stand.ChatOk = [bool]$cli.Ok
        $stand.ChatPfad = "$($cli.Pfad)"
        Write-Host $cli.Text
        if ($cli.Ok) {
            if (Cli-Angemeldet $ChatKi $cli.Pfad) {
                Write-Host "Angemeldet."
            } elseif ($OhnePause) {
                Write-Host ("Noch nicht angemeldet. Anmelden mit: """ + $cli.Pfad + """ " + ($CLI_ANMELDEN[$ChatKi] -join " "))
            } else {
                Write-Host "Jetzt anmelden: dein Browser oeffnet sich, danach geht es hier weiter."
                $anmelden = $CLI_ANMELDEN[$ChatKi]
                & $cli.Pfad @anmelden
            }
        }
    }
} catch {
    $fehler = $_
    Write-Host ""
    Write-Host ("FEHLER: " + $_.Exception.Message) -ForegroundColor Red
    if ($phase -eq "chat") {
        $stand.Chat = "FEHLER: " + $_.Exception.Message
        $stand.ChatOk = $false
    } elseif ($phase -eq "server") {
        $stand.Server = "fehlt"
        $stand.ServerText = $_.Exception.Message
    } elseif ($stand.Plugin -eq "fehlt" -and $stand.PluginText -eq "abgebrochen") {
        $stand.PluginText = $_.Exception.Message
    }
} finally {
    $ergebnis = Zusammenfassung $stand
    if ($ErgebnisDatei) { Ergebnis-Schreiben $ErgebnisDatei $stand $ergebnis $ki $fehler }
    Write-Host ""
    Write-Host "== Ergebnis" -ForegroundColor Cyan
    foreach ($z in $ergebnis.Zeilen) { Write-Host ("  " + $z) }
    if (-not $OhnePause) {
        Write-Host ""
        Read-Host "Enter zum Schliessen"
    }
}
# 3 statt 1 (Gegenpruefung 2026-09-29): 1 gibt auch PowerShell selbst
# zurueck, wenn es das Skript gar nicht ausfuehren darf (gemessen mit
# -ExecutionPolicy AllSigned). 1_INSTALLIEREN.cmd unterscheidet so "nicht
# vollstaendig, schon gemeldet" von "gar nicht gestartet".
if ($fehler -or -not $ergebnis.Fertig) { exit 3 }
exit 0
