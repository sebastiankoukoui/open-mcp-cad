<#
Open MCP CAD - das Einrichtungsfenster (seit 2026-10-09).

    1_INSTALLIEREN.cmd            (Doppelklick ohne Schalter -> dieses Fenster)

Rueckmeldung 2026-10-09: das schwarze Konsolenfenster des Installers
schreckte Laien ab, auch wenn man nur Enter druecken musste. Dieses Skript
zeigt statt dessen ein normales Fenster (WPF, Windows PowerShell 5.1, kein
eigenes Programm, nichts heruntergeladen).

EINE LOGIK: das Fenster stellt seine Fragen VORHER - mit den Funktionen aus
install.ps1 (Profil-Kandidaten, Profil-Vorgabe, Version-Pruefen,
Finde-Python, Python-Weg, KI-Finden) - und startet dann install.ps1 selbst,
als eigenen, unsichtbaren Prozess, mit den Antworten als Schalter (-Profil,
-TrotzdemKopieren, -PythonInstallieren, -KiNur, -OhnePause; Fenster-
Argumente). Kopieren, Python, Server, Umgebungsvariable und Eintragen in
die KI-Programme macht also genau derselbe Code wie im Textfenster. Dessen
Ausgabe liest das Fenster Zeile fuer Zeile (Schritte "== n/5"), schreibt
sie ins Protokoll ($Protokoll) und zeigt sie unter "Details"; den Stand am
Ende liest es aus -ErgebnisDatei.

Rueckgabe wie install.ps1: 0 = alles da, 3 = nicht vollstaendig (auch:
Fenster vor dem Installieren geschlossen). 10 = das Fenster ging gar nicht
(kein WPF, kein STA, XAML kaputt): dann startet 1_INSTALLIEREN.cmd das
Textfenster - nie stilles Nichts.

Alle sichtbaren Texte stehen in install_fenster.xaml (UTF-8). Diese Datei
bleibt reines ASCII: Windows PowerShell 5.1 liest Skripte ohne BOM als ANSI.

Fuer die Gates und die Bilder der Anleitung:
    -NurFunktionen      (dot-sourced) nur die Funktionen laden
    -Rendern ORDNER     jede Seite ohne Fenster als PNG (RenderTargetBitmap)
                        plus seiten.json (Lage der benannten Teile, Texte)
    -CadworkWurzel/-CadworkProgramm/-PythonZiel/-OhneServer/
    -OhneUmgebungsvariable  werden an install.ps1 weitergereicht
    -Protokoll DATEI    statt C:\Users\Public\OpenMcpCad_installer.log
#>
param(
    [switch]$NurFunktionen,
    [string]$Rendern = "",
    [string]$Protokoll = "C:\Users\Public\OpenMcpCad_installer.log",
    [string]$XamlDatei = "",
    [string]$PythonZiel = "",
    [switch]$OhneServer,
    [switch]$OhneUmgebungsvariable,
    [string]$CadworkWurzel = "C:\Users\Public\Documents\cadwork",
    [string]$CadworkProgramm = "C:\Program Files\cadwork.dir"
)

# Erst sichern: das Dot-Sourcing von install.ps1 unten setzt dessen
# Parameter (gleiche Namen) im selben Bereich.
$global:OMCAD_F = @{
    Nur        = [bool]$NurFunktionen
    Rendern    = $Rendern
    Protokoll  = $Protokoll
    Xaml       = $XamlDatei
    PythonZiel = $PythonZiel
    OhneServer = [bool]$OhneServer
    OhneUmgebungsvariable = [bool]$OhneUmgebungsvariable
    Wurzel     = $CadworkWurzel
    Programm   = $CadworkProgramm
    Hier       = (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$OMCAD_INSTALL = Join-Path $global:OMCAD_F.Hier "install.ps1"
. $OMCAD_INSTALL -NurFunktionen
$ErrorActionPreference = "Stop"

# Rueckgabe, wenn das Fenster gar nicht geht (1_INSTALLIEREN.cmd faellt
# dann auf das Textfenster zurueck).
$FENSTER_GEHT_NICHT = 10
# Die offiziellen Seiten (geprueft 2026-10-09): Claude Desktop bei Anthropic,
# die ChatGPT-Desktop-App mit Codex (frueher "Codex-App") im Microsoft Store
# (Produkt 9PLM9XGG6VKS, so verlinkt in der Anleitung von OpenAI
# learn.chatgpt.com/docs/windows/windows-app; die Store-Seite heisst
# "ChatGPT"). Installiert ist sie das Paket OpenAI.Codex_2p2nqsd0c76g0,
# im Startmenue "ChatGPT" (gemessen 2026-10-09 mit Get-AppxPackage und
# Get-StartApps am Rechner des Maintainers, Version 26.1002.7124.0) - die
# Suche OpenAI.Codex_* in KI-Finden/ki_eintragen.finden findet sie also.
$URL_CLAUDE_DESKTOP = "https://claude.com/download"
$URL_CODEX = "https://apps.microsoft.com/detail/9PLM9XGG6VKS"
# Die Programme, die das Fenster anbietet (ids wie in ki_eintragen).
$KI_PROGRAMME = @("claude_desktop", "codex", "claude_code")
# Die Seiten, in der Reihenfolge des Ablaufs.
$SEITEN = @("willkommen", "wo", "ki", "ki_keine", "chat_ki", "profil", "version", "python", "bereit", "laeuft", "anmelden", "fertig", "fehler")
# Wo der Nutzer mit der KI arbeitet (Seite "wo", seit 2026-10-09): in der
# KI-App, im Chat in Cadwork oder beides; und welche KI der Chat nimmt
# (Seite "chat_ki"): claude, codex oder spaeter (Schluessel, lokale KI).
$WO = @("app", "chat", "beides")
$CHAT_KI = @("claude", "codex", "spaeter")

# --- Reine Logik (ohne WPF; test_installer I22-I24) ------------------------

function Arg-Text([string]$a) {
    # Ein Argument fuer ProcessStartInfo.Arguments, so gequotet, dass
    # CommandLineToArgvW es wieder genau so liest (Leerzeichen, ", \ am Ende).
    if ($a -ne "" -and $a -notmatch '[\s"]') { return $a }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $bs = 0
    foreach ($c in $a.ToCharArray()) {
        if ($c -eq [char]92) { $bs++; continue }
        if ($c -eq [char]34) {
            [void]$sb.Append([string][char]92 * (2 * $bs + 1)).Append('"')
            $bs = 0
            continue
        }
        if ($bs -gt 0) { [void]$sb.Append([string][char]92 * $bs) }
        [void]$sb.Append($c)
        $bs = 0
    }
    if ($bs -gt 0) { [void]$sb.Append([string][char]92 * (2 * $bs)) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Fenster-Argumente($W) {
    # Die Antworten des Fensters als Schalter fuer install.ps1.
    # $W: Profil, Trotzdem, Python, Ki (Liste von ids), ErgebnisDatei und
    # die durchgereichten Wurzel, Programm, PythonZiel, OhneServer,
    # OhneUmgebungsvariable. -> Liste der Argumente fuer powershell.exe.
    $a = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", $OMCAD_INSTALL, "-OhnePause", "-Utf8Ausgabe")
    if ($W.ErgebnisDatei) { $a += @("-ErgebnisDatei", $W.ErgebnisDatei) }
    $a += @("-CadworkWurzel", $W.Wurzel, "-CadworkProgramm", $W.Programm)
    if ($W.Profil) { $a += @("-Profil", $W.Profil) }
    if ($W.Trotzdem) { $a += "-TrotzdemKopieren" }
    if ($W.Python) { $a += "-PythonInstallieren" }
    $ki = @($W.Ki | Where-Object { $_ })
    if ($ki.Count -gt 0) { $a += @("-KiNur", ($ki -join ",")) } else { $a += "-OhneKiEintrag" }
    if ($W.PythonZiel) { $a += @("-PythonZiel", $W.PythonZiel) }
    if ($W.OhneServer) { $a += "-OhneServer" }
    if ($W.OhneUmgebungsvariable) { $a += "-OhneUmgebungsvariable" }
    if ($W.ChatKi -eq "claude" -or $W.ChatKi -eq "codex") { $a += @("-ChatKi", $W.ChatKi) }
    return , $a
}

function Seite-Noetig([string]$seite, $S) {
    # Braucht der Ablauf diese Seite? (die Fragen des Textfensters, nur
    # wenn sie sich stellen)
    switch ($seite) {
        "ki"      { return ($S.Wo -ne "chat") }
        "chat_ki" { return ($S.Wo -ne "app") }
        "profil"  { return (@($S.Kandidaten).Count -gt 1) }
        "version" { return ($S.Version -and -not $S.Version.Passt -and -not $S.Trotzdem) }
        "python"  { return ($S.PythonFehlt -and -not $S.OhneServer -and -not $S.PythonJa) }
        default   { return $true }
    }
}

function Seite-Nach([string]$von, $S) {
    # Die naechste Seite nach $von (rein; die Knoepfe rufen sie).
    if ($von -eq "start") { return "willkommen" }
    if ($von -eq "willkommen") { $von = "start_wo" }
    if ($von -eq "ki_keine") { $von = "ki" }
    $folge = @("start_wo", "wo", "ki", "chat_ki", "profil", "version", "python", "bereit", "laeuft")
    $i = [array]::IndexOf($folge, $von)
    if ($i -lt 0) { return $von }
    for ($j = $i + 1; $j -lt $folge.Count; $j++) {
        $seite = $folge[$j]
        if (-not (Seite-Noetig $seite $S)) { continue }
        # Ohne Cadwork-Profil geht es nach den Fragen zur KI nicht weiter.
        if (@("profil", "version", "python", "bereit", "laeuft") -contains $seite -and @($S.Kandidaten).Count -eq 0) { return "fehler" }
        if ($seite -eq "ki" -and @($S.KiGefunden).Count -eq 0) { return "ki_keine" }
        return $seite
    }
    return "laeuft"
}

function Wo-Vorgabe($S) {
    # Eine KI-App gefunden -> beides; sonst ein Chat-Programm gefunden ->
    # der Chat; sonst die App (der einfachste Anfang: nur ein Download).
    if (@($S.KiGefunden | Where-Object { $_ -ne "claude_code" }).Count -gt 0) { return "beides" }
    if ($S.CliDa.claude -or $S.CliDa.codex -or @($S.KiGefunden) -contains "claude_code") { return "chat" }
    return "app"
}

function Chat-Vorgabe($S) {
    # Was schon da ist, sonst passend zur gefundenen App, sonst Claude
    # (ohne Node und ohne Adminrechte, ein Befehl des Herstellers).
    if ($S.CliDa.claude) { return "claude" }
    if ($S.CliDa.codex) { return "codex" }
    if (@($S.KiGefunden) -contains "claude_desktop") { return "claude" }
    if (@($S.KiGefunden) -contains "codex") { return "codex" }
    return "claude"
}

function Unterzeile-Aus-Zeile([string]$zeile) {
    # Was gerade passiert, fuer die Unterzeile unter dem Balken - aus den
    # Zeilen von install.ps1, pip und winget, ohne Pfade. -> @{ Text =
    # Schluessel; Wert = Name oder "" } oder $null (nichts Neues).
    $z = $zeile.Trim()
    if ($z -match '^Lade https://www\.python\.org/') { return @{ Text = "t_unter_python_laden"; Wert = "" } }
    if ($z -match '^(Installiere Python|Signatur geprueft)') { return @{ Text = "t_unter_python_installieren"; Wert = "" } }
    $m = [regex]::Match($z, '^(Collecting|Downloading)\s+(\S+)')
    if ($m.Success) {
        $name = $m.Groups[2].Value
        # Eine Datei (numpy-2.1.0-cp313-...whl) oder Adresse: nur der Name.
        $name = ($name -split '[/\\]')[-1]
        $name = ($name -split '[-<>=!~\[;(,]')[0]
        if ($name -notmatch '^[A-Za-z0-9._]{1,60}$') { $name = "" }
        if ($name) { return @{ Text = "t_unter_pip_laden"; Wert = $name } }
        return $null
    }
    if ($z -match '^Installing collected packages') { return @{ Text = "t_unter_pip_installieren"; Wert = "" } }
    $m = [regex]::Match($z, '^Lade das offizielle Installationsprogramm von ([A-Za-z ]{1,30}):')
    if ($m.Success) { return @{ Text = "t_unter_cli_laden"; Wert = $m.Groups[1].Value } }
    if ($z -match '^== ') { return @{ Text = ""; Wert = "" } }
    return $null
}

function Schritt-Aus-Zeile([string]$zeile) {
    # "== 3/5 MCP-Server einrichten" (Schritt in install.ps1) -> 3, sonst 0
    # (mit -ChatKi sind es sechs: "== 6/6 ...").
    $m = [regex]::Match($zeile, '^== (\d)/([56]) ')
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return 0
}

function Fehler-Schluessel($erg) {
    # Der Satz fuer die Fehlerseite (Schluessel eines Textes in der XAML).
    if (-not $erg) { return "t_fehler_unerwartet" }
    if ($erg.plugin -eq "fehlt") { return "t_fehler_plugin" }
    if ($erg.server -eq "fehlt") {
        if ("$($erg.serverText)" -match "Kein Python") { return "t_fehler_python" }
        return "t_fehler_server"
    }
    if ($erg.chat -and -not $erg.chatOk) { return "t_fehler_chat" }
    if ($erg.plugin -eq "version") { return "t_fehler_version" }
    return "t_fehler_unerwartet"
}

function Lauf-Gut($rc, $erg) {
    return ($rc -eq 0 -and $erg -and [bool]$erg.fertig)
}

function KI-Ergebnis($erg) {
    # -> @{ Verbunden = ids/namen mit eingetragen|schon_da; Fehler = andere
    # (ausser abgelehnt) }, je als Namen aus ki_eintragen.
    $gut = @(); $schlecht = @()
    if ($erg) {
        foreach ($e in @($erg.kiListe)) {
            if (-not $e) { continue }
            if ($e.status -eq "eingetragen" -or $e.status -eq "schon_da") { $gut += $e.name }
            elseif ($e.status -ne "abgelehnt") { $schlecht += $e.name }
        }
    }
    return @{ Verbunden = @($gut | Select-Object -Unique); Fehler = @($schlecht | Select-Object -Unique) }
}

function Zustand-Neu {
    # Der Zustand des Fensters; die Fragen beantwortet der Nutzer.
    return @{
        Seite = "start"; Verlauf = @()
        Kandidaten = @(); ProfilIndex = 0; Installiert = @(); Version = $null; Trotzdem = $false
        PythonFehlt = $false; PythonWeg = ""; PythonJa = $false
        KiGefunden = @(); KiWahl = @()
        Wo = "app"; ChatKi = "claude"; CliDa = @{ claude = $null; codex = $null }
        OhneServer = $global:OMCAD_F.OhneServer
        Geprueft = $false; Lauf = $null; Rc = 3; Ergebnis = $null
        Log = (New-Object System.Text.StringBuilder)
    }
}

function Lage-Pruefen($S) {
    # Was schon da ist - dieselben Funktionen wie install.ps1.
    $F = $global:OMCAD_F
    $S.Installiert = @(Cadwork-Installiert $F.Programm)
    $S.Kandidaten = @(Profil-Kandidaten $F.Wurzel $F.Programm)
    if ($S.Kandidaten.Count -gt 0) {
        $S.ProfilIndex = (Profil-Vorgabe $S.Kandidaten $F.Programm).Index
        Version-Setzen $S
    }
    if (-not $S.OhneServer) {
        $S.PythonFehlt = (-not (Finde-Python))
        if ($S.PythonFehlt) { $S.PythonWeg = Python-Weg }
    }
    KI-Suchen $S
    $S.CliDa = @{ claude = (Cli-Pfad "claude"); codex = (Cli-Pfad "codex") }
    $S.Wo = Wo-Vorgabe $S
    $S.ChatKi = Chat-Vorgabe $S
    $S.Geprueft = $true
}

function KI-Suchen($S) {
    # Erst zuweisen, dann aufzaehlen: KI-Finden gibt die Liste als EIN
    # Objekt zurueck (leer gaebe es sonst einen $null-Eintrag).
    $liste = KI-Finden
    $S.KiGefunden = @($liste | Where-Object { $_ } | ForEach-Object { $_.programm })
    # Was gefunden ist, ist angehakt (der Nutzer kann es abwaehlen).
    $S.KiWahl = @($S.KiGefunden)
}

function Version-Setzen($S) {
    $k = @($S.Kandidaten)[$S.ProfilIndex]
    $S.Version = Version-Pruefen $k.Pfad $S.Installiert $global:OMCAD_F.Programm
}

function Wahl-Aus-Zustand($S, [string]$ergebnisDatei) {
    $F = $global:OMCAD_F
    $profil = ""
    if (@($S.Kandidaten).Count -gt 0) { $profil = @($S.Kandidaten)[$S.ProfilIndex].Pfad }
    return @{
        Profil = $profil; Trotzdem = [bool]$S.Trotzdem
        Python = ([bool]$S.PythonFehlt -and [bool]$S.PythonJa)
        Ki = $(if ($S.Wo -eq "chat") { @() } else { @($S.KiWahl) }); ErgebnisDatei = $ergebnisDatei
        ChatKi = $(if ($S.Wo -eq "app") { "" } else { $S.ChatKi })
        Wurzel = $F.Wurzel; Programm = $F.Programm; PythonZiel = $F.PythonZiel
        OhneServer = $F.OhneServer; OhneUmgebungsvariable = $F.OhneUmgebungsvariable
    }
}

# --- Protokoll ---------------------------------------------------------------

function Protokoll-Beginnen($S) {
    # Neues Protokoll je Lauf, das vorige bleibt als .1 liegen.
    $p = $global:OMCAD_F.Protokoll
    try {
        if (Test-Path -LiteralPath $p) { Move-Item -LiteralPath $p -Destination ($p + ".1") -Force }
    } catch { }
    [void]$S.Log.Clear()
    Protokoll-Zeile $S ("Open MCP CAD - Einrichtung " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Protokoll-Zeile $S ("Windows " + [Environment]::OSVersion.Version + ", PowerShell " + $PSVersionTable.PSVersion)
}

function Protokoll-Zeile($S, [string]$text) {
    [void]$S.Log.AppendLine($text)
    try {
        [IO.File]::AppendAllText($global:OMCAD_F.Protokoll, $text + "`r`n", (New-Object System.Text.UTF8Encoding $false))
    } catch { }
}

# --- Der Installer als Kindprozess ---------------------------------------------

function Installer-Starten($argumente) {
    # install.ps1 unsichtbar starten, Ausgabe umgeleitet (UTF-8, siehe
    # -Utf8Ausgabe). -> Lauf (Prozess und die zwei laufenden Lesungen).
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $si.Arguments = (@($argumente | ForEach-Object { Arg-Text $_ }) -join " ")
    $si.UseShellExecute = $false
    $si.CreateNoWindow = $true
    $si.RedirectStandardOutput = $true
    $si.RedirectStandardError = $true
    $si.RedirectStandardInput = $true
    $si.StandardOutputEncoding = New-Object System.Text.UTF8Encoding $false
    $si.StandardErrorEncoding = New-Object System.Text.UTF8Encoding $false
    $si.WorkingDirectory = $global:OMCAD_F.Hier
    $p = [System.Diagnostics.Process]::Start($si)
    $p.StandardInput.Close()
    return @{ P = $p; Aus = $p.StandardOutput.ReadLineAsync(); Err = $p.StandardError.ReadLineAsync(); AusZu = $false; ErrZu = $false }
}

function Installer-Takt($L, [scriptblock]$aufZeile) {
    # Holt jede fertig gelesene Zeile ab (ohne Warten; aus einem Zeitgeber
    # im Fenster, nie aus einem fremden Thread). -> $true, wenn alles da ist.
    foreach ($art in @("Aus", "Err")) {
        while (-not $L[$art + "Zu"] -and $L[$art].IsCompleted) {
            $z = $L[$art].Result
            if ($null -eq $z) { $L[$art + "Zu"] = $true; break }
            & $aufZeile $z
            if ($art -eq "Aus") { $L.Aus = $L.P.StandardOutput.ReadLineAsync() }
            else { $L.Err = $L.P.StandardError.ReadLineAsync() }
        }
    }
    if ($L.AusZu -and $L.ErrZu) {
        $L.P.WaitForExit()
        return $true
    }
    return $false
}

function Ergebnis-Lesen([string]$datei) {
    try {
        if (-not (Test-Path -LiteralPath $datei)) { return $null }
        $text = [IO.File]::ReadAllText($datei, [Text.Encoding]::UTF8)
        return ($text | ConvertFrom-Json)
    } catch { return $null }
}

# --- Oeffnen (im Gate ersetzt) ----------------------------------------------

function Url-Oeffnen([string]$url) {
    Start-Process $url
}

function Datei-Oeffnen([string]$pfad) {
    Start-Process -FilePath $pfad
}

function Ablage-Setzen([string]$text) {
    [System.Windows.Clipboard]::SetText($text)
}

function Anleitung-Pfad {
    # Die Anleitung oben im Paket (PDF, ohne Edge beim Bauen die HTML).
    $oben = Split-Path -Parent $global:OMCAD_F.Hier
    foreach ($n in @("2_ANLEITUNG.pdf", "2_ANLEITUNG.html")) {
        $p = Join-Path $oben $n
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

# --- Fenster -------------------------------------------------------------------

function Wpf-Laden {
    if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne [Threading.ApartmentState]::STA) {
        throw "PowerShell laeuft nicht im STA-Modus (-STA fehlt)"
    }
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml
}

function Logo-Pfad {
    $h = $global:OMCAD_F.Hier
    foreach ($p in @((Join-Path $h "logo.png"), (Join-Path (Split-Path -Parent $h) "assets\logo.png"))) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Fenster-Bauen {
    # XAML laden, nichts zeigen. -> $U (Fenster, Wurzel, Texte).
    $xaml = $global:OMCAD_F.Xaml
    if (-not $xaml) { $xaml = Join-Path $global:OMCAD_F.Hier "install_fenster.xaml" }
    $text = [IO.File]::ReadAllText($xaml, [Text.Encoding]::UTF8)
    $w = [Windows.Markup.XamlReader]::Parse($text)
    $U = @{ W = $w; Wurzel = $w.FindName("Wurzel") }
    $logo = Logo-Pfad
    if ($logo) {
        # Je Ort passend dekodiert (4-fach der Anzeige, fuer 200-400 %
        # Skalierung): das 640-px-Logo direkt auf 36 px verkleinert war
        # unscharf (Rueckmeldung 2026-10-09).
        foreach ($ziel in @("KopfLogo", "willkommen_logo")) {
            $el = El $U $ziel
            $el.Source = Logo-Bild $logo ([int]($el.Width * 4))
        }
        $w.Icon = Logo-Bild $logo 64
    }
    return $U
}

function Logo-Bild([string]$pfad, [int]$pixel) {
    $bild = New-Object System.Windows.Media.Imaging.BitmapImage
    $bild.BeginInit()
    $bild.UriSource = New-Object System.Uri($pfad)
    $bild.DecodePixelWidth = $pixel
    $bild.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bild.EndInit()
    $bild.Freeze()
    return $bild
}

function El($U, [string]$name) {
    $e = $U.W.FindName($name)
    if ($null -eq $e) { throw "Fenster ohne Teil '$name'" }
    return $e
}

function Text($U, [string]$schluessel) {
    $t = $U.Wurzel.Resources[$schluessel]
    if ($null -eq $t) { throw "Fenster ohne Text '$schluessel'" }
    return [string]$t
}

function Sichtbar($el, [bool]$an) {
    if ($an) { $el.Visibility = [System.Windows.Visibility]::Visible }
    else { $el.Visibility = [System.Windows.Visibility]::Collapsed }
}

function Namen-Liste($U, [string[]]$namen) {
    # "A", "A und B", "A, B und C" (das "und" aus der XAML).
    $n = @($namen | Where-Object { $_ })
    if ($n.Count -le 1) { return ($n -join "") }
    return (($n[0..($n.Count - 2)] -join ", ") + " " + (Text $U "t_und") + " " + $n[-1])
}

function KI-Name($U, [string]$id) {
    return (Text $U ("t_name_" + $id))
}

function Seite-Zeigen($U, $S, [string]$seite) {
    foreach ($n in $SEITEN) { Sichtbar (El $U ("Seite_" + $n)) ($n -eq $seite) }
    $S.Seite = $seite
    $S.Verlauf += $seite
    switch ($seite) {
        "willkommen" { Willkommen-Fuellen $U $S }
        "wo"         { Wo-Fuellen $U $S }
        "chat_ki"    { Chat-Fuellen $U $S }
        "anmelden"   { Anmelden-Fuellen $U $S }
        "ki"         { KI-Fuellen $U $S }
        "profil"     { Profil-Fuellen $U $S }
        "version"    { Version-Fuellen $U $S }
        "python"     { Python-Fuellen $U $S }
        "bereit"     { Bereit-Fuellen $U $S }
    }
    # Enter = der Hauptknopf der Seite.
    $haupt = @{ willkommen = "willkommen_weiter"; wo = "wo_weiter"; chat_ki = "chat_weiter"; anmelden = "anmelden_los"
                ki = "ki_weiter"; ki_keine = "keine_nochmal"
                profil = "profil_weiter"; version = "version_schliessen"; python = "python_ja"
                bereit = "bereit_installieren"; fertig = "fertig_schliessen"; fehler = "fehler_schliessen" }
    if ($haupt.ContainsKey($seite)) { (El $U $haupt[$seite]).IsDefault = $true }
}

function Weiter($U, $S, [string]$von) {
    Seite-Zeigen $U $S (Seite-Nach $von $S)
    if ($S.Seite -eq "fehler") { Fehler-Fuellen $U $S "t_fehler_profil" }
}

function Willkommen-Fuellen($U, $S) {
    if ($S.Geprueft) {
        (El $U "willkommen_stand").Text = (Text $U "t_bereit_zum_start")
        (El $U "willkommen_weiter").IsEnabled = $true
    } else {
        (El $U "willkommen_stand").Text = (Text $U "t_suche")
        (El $U "willkommen_weiter").IsEnabled = $false
    }
}

function Wo-Fuellen($U, $S) {
    foreach ($w in $WO) { (El $U ("wo_" + $w)).IsChecked = ($S.Wo -eq $w) }
}

function Wo-Lesen($U, $S) {
    foreach ($w in $WO) { if ((El $U ("wo_" + $w)).IsChecked -eq $true) { $S.Wo = $w } }
}

function Chat-Fuellen($U, $S) {
    foreach ($k in $CHAT_KI) { (El $U ("chat_" + $k)).IsChecked = ($S.ChatKi -eq $k) }
    foreach ($k in @("claude", "codex")) {
        (El $U ("chat_stand_" + $k)).Text = (Text $U "t_schon_da")
        Sichtbar (El $U ("chat_marke_" + $k)) ([bool]$S.CliDa[$k])
    }
}

function Chat-Lesen($U, $S) {
    foreach ($k in $CHAT_KI) { if ((El $U ("chat_" + $k)).IsChecked -eq $true) { $S.ChatKi = $k } }
}

function Chat-Name($U, [string]$ki) {
    return (Text $U ("t_chat_name_" + $ki))
}

function KI-Fuellen($U, $S) {
    foreach ($id in $KI_PROGRAMME) {
        $da = @($S.KiGefunden) -contains $id
        $cb = El $U ("ki_" + $id)
        $cb.IsEnabled = $da
        $cb.IsChecked = ($da -and (@($S.KiWahl) -contains $id))
        (El $U ("ki_stand_" + $id)).Text = (Text $U "t_gefunden")
        Sichtbar (El $U ("ki_marke_" + $id)) $da
        if ($id -eq "claude_code") {
            Sichtbar (El $U "ki_karte_claude_code") $da
        } else {
            Sichtbar (El $U ("ki_holen_" + $id)) (-not $da)
        }
    }
    KI-Weiter-Setzen $U $S
}

function KI-Weiter-Setzen($U, $S) {
    (El $U "ki_weiter").IsEnabled = (@($S.KiWahl).Count -gt 0)
}

function KI-Wahl-Lesen($U, $S) {
    $S.KiWahl = @($KI_PROGRAMME | Where-Object { (El $U ("ki_" + $_)).IsChecked -eq $true })
    KI-Weiter-Setzen $U $S
}

function Profil-Fuellen($U, $S) {
    $liste = El $U "profil_liste"
    foreach ($alt in $liste.Children) { if ($alt.Name) { $U.W.UnregisterName($alt.Name) } }
    $liste.Children.Clear()
    $vorgabe = (Profil-Vorgabe $S.Kandidaten $global:OMCAD_F.Programm).Index
    $stil = $U.Wurzel.Resources["Wahl"]
    for ($i = 0; $i -lt @($S.Kandidaten).Count; $i++) {
        $k = @($S.Kandidaten)[$i]
        $rb = New-Object System.Windows.Controls.RadioButton
        $rb.Style = $stil
        $rb.GroupName = "profil"
        $rb.Tag = $i
        $rb.Name = "profil_wahl_" + $i
        $sp = New-Object System.Windows.Controls.StackPanel
        $t1 = New-Object System.Windows.Controls.TextBlock
        if ($k.Nummer -ge 0) { $t1.Text = [string]::Format((Text $U "t_profil_name"), $k.Nummer) }
        else { $t1.Text = (Text $U "t_profil_unbekannt") }
        $t1.FontWeight = [System.Windows.FontWeights]::SemiBold
        $t2 = New-Object System.Windows.Controls.TextBlock
        $teile = @()
        if ($i -eq $vorgabe) { $teile += (Text $U "t_profil_empfohlen") }
        if ($k.Installiert) { $teile += (Text $U "t_profil_installiert") } else { $teile += (Text $U "t_profil_nicht_installiert") }
        $t2.Text = ($teile -join (Text $U "t_trenner"))
        $t2.FontSize = 12.5
        $t2.Foreground = $U.Wurzel.Resources["Neben"]
        [void]$sp.Children.Add($t1)
        [void]$sp.Children.Add($t2)
        $rb.Content = $sp
        $rb.ToolTip = $k.Pfad
        $rb.IsChecked = ($i -eq $S.ProfilIndex)
        $rb.Add_Checked({ param($sender, $e) Profil-Gewaehlt $global:OMCAD_F.U $global:OMCAD_F.S ([int]$sender.Tag) })
        [void]$liste.Children.Add($rb)
        $U.W.RegisterName($rb.Name, $rb)
    }
}

function Profil-Gewaehlt($U, $S, [int]$i) {
    $S.ProfilIndex = $i
    $S.Trotzdem = $false
    Version-Setzen $S
}

function Version-Fuellen($U, $S) {
    (El $U "version_text").Text = $S.Version.Text
    Sichtbar (El $U "version_zurueck") (@($S.Kandidaten).Count -gt 1)
}

function Python-Fuellen($U, $S) {
    if ($S.PythonWeg -eq "winget") { (El $U "python_weg").Text = (Text $U "t_python_winget") }
    else { (El $U "python_weg").Text = (Text $U "t_python_org") }
}

function Bereit-Zeilen($U, $S) {
    # Was eingerichtet wird, in Worten (fuer die Seite "Bereit").
    $z = @()
    $nr = "?"
    if ($S.Version -and $null -ne $S.Version.Nummer) { $nr = $S.Version.Nummer }
    if ($S.Version -and -not $S.Version.Passt) { $z += [string]::Format((Text $U "t_bereit_plugin_trotzdem"), $nr) }
    else { $z += [string]::Format((Text $U "t_bereit_plugin"), $nr) }
    $namen = @($KI_PROGRAMME | Where-Object { @($S.KiWahl) -contains $_ } | ForEach-Object { KI-Name $U $_ })
    if (-not $S.OhneServer) {
        if ($S.Wo -ne "chat") {
            if ($namen.Count -gt 0) { $z += [string]::Format((Text $U "t_bereit_ki"), (Namen-Liste $U $namen)) }
            else { $z += (Text $U "t_bereit_keine_ki") }
        }
        if ($S.PythonFehlt -and $S.PythonJa) { $z += (Text $U "t_bereit_python") }
    }
    if ($S.Wo -ne "app") {
        if ($S.ChatKi -eq "spaeter") { $z += (Text $U "t_bereit_chat_spaeter") }
        elseif ($S.CliDa[$S.ChatKi]) { $z += [string]::Format((Text $U "t_bereit_chat_da"), (Chat-Name $U $S.ChatKi)) }
        else { $z += [string]::Format((Text $U "t_bereit_chat"), (Chat-Name $U $S.ChatKi)) }
    }
    return , $z
}

function Bereit-Fuellen($U, $S) {
    $liste = El $U "bereit_liste"
    $liste.Children.Clear()
    $i = 0
    foreach ($zeile in (Bereit-Zeilen $U $S)) {
        $g = New-Object System.Windows.Controls.Grid
        $c1 = New-Object System.Windows.Controls.ColumnDefinition
        $c1.Width = New-Object System.Windows.GridLength 30
        [void]$g.ColumnDefinitions.Add($c1)
        [void]$g.ColumnDefinitions.Add((New-Object System.Windows.Controls.ColumnDefinition))
        if ($i -gt 0) { $g.Margin = New-Object System.Windows.Thickness 0, 10, 0, 0 }
        $haken = New-Object System.Windows.Shapes.Path
        $haken.Data = [System.Windows.Media.Geometry]::Parse("M 2,9 L 7,14 L 16,4")
        $haken.Stroke = $U.Wurzel.Resources["Violett"]
        $haken.StrokeThickness = 2.4
        $haken.StrokeStartLineCap = "Round"; $haken.StrokeEndLineCap = "Round"; $haken.StrokeLineJoin = "Round"
        $haken.VerticalAlignment = "Center"
        $t = New-Object System.Windows.Controls.TextBlock
        $t.Text = $zeile
        $t.TextWrapping = "Wrap"
        $t.Foreground = $U.Wurzel.Resources["Text"]
        [System.Windows.Controls.Grid]::SetColumn($t, 1)
        [void]$g.Children.Add($haken)
        [void]$g.Children.Add($t)
        [void]$liste.Children.Add($g)
        $i++
    }
}

function Schritt-Setzen($U, [int]$n, [string]$art) {
    # art: offen | laeuft | fertig | fehler
    $r = $U.Wurzel.Resources
    $kreis = El $U ("s" + $n + "_kreis")
    $haken = El $U ("s" + $n + "_haken")
    $text = El $U ("s" + $n + "_text")
    switch ($art) {
        "laeuft" {
            $kreis.Background = $r["ViolettHell"]; $kreis.BorderBrush = $r["Violett"]; $kreis.BorderThickness = 2
            Sichtbar $haken $false; $text.Foreground = $r["Text"]; $text.FontWeight = "SemiBold"
        }
        "fertig" {
            $kreis.Background = $r["Violett"]; $kreis.BorderBrush = $r["Violett"]; $kreis.BorderThickness = 1.5
            Sichtbar $haken $true; $text.Foreground = $r["Text"]; $text.FontWeight = "Normal"
        }
        "fehler" {
            $kreis.Background = $r["Rot"]; $kreis.BorderBrush = $r["Rot"]; $kreis.BorderThickness = 1.5
            Sichtbar $haken $false; $text.Foreground = $r["Rot"]; $text.FontWeight = "SemiBold"
        }
        default {
            $kreis.Background = [System.Windows.Media.Brushes]::White
            $kreis.BorderBrush = New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.ColorConverter]::ConvertFromString("#D6D2E3"))
            $kreis.BorderThickness = 1.5
            Sichtbar $haken $false; $text.Foreground = $r["Neben"]; $text.FontWeight = "Normal"
        }
    }
}

function Schritte-Zahl($S) {
    # Fuenf Schritte, mit der KI fuer den Chat sechs (wie install.ps1).
    $w = Wahl-Aus-Zustand $S ""
    if ($w.ChatKi -eq "claude" -or $w.ChatKi -eq "codex") { return 6 }
    return 5
}

function Fortschritt($U, $S, [int]$schritt) {
    # Schritt n laeuft: davor fertig, danach offen; der Balken dazu.
    $n = Schritte-Zahl $S
    Sichtbar (El $U "s6_zeile") ($n -eq 6)
    for ($i = 1; $i -le $n; $i++) {
        if ($i -lt $schritt) { Schritt-Setzen $U $i "fertig" }
        elseif ($i -eq $schritt) { Schritt-Setzen $U $i "laeuft" }
        else { Schritt-Setzen $U $i "offen" }
    }
    (El $U "laeuft_leiste").Value = [Math]::Max(4, ($schritt - 1) * (100 / $n) + 6)
    if ($S.Schritt -ne $schritt) { Unterzeile-Setzen $U $S "" "" }
    $S.Schritt = $schritt
}

function Unterzeile-Setzen($U, $S, [string]$schluessel, [string]$wert) {
    # Die Zeile unter dem Balken und das bewegte Band (Rueckmeldung
    # 2026-10-09: bei langen Downloads sah es aus, als haenge es).
    if ($schluessel) { $text = [string]::Format((Text $U $schluessel), $wert) } else { $text = " " }
    (El $U "laeuft_unterzeile").Text = $text
    $S.Unterzeile = $text
    $band = El $U "laeuft_band"
    if ($schluessel) {
        $band.Visibility = [System.Windows.Visibility]::Visible
        if (-not $S.BandLaeuft) {
            $anim = New-Object System.Windows.Media.Animation.DoubleAnimation
            $anim.From = -140; $anim.To = 560
            $anim.Duration = New-Object System.Windows.Duration ([TimeSpan]::FromSeconds(1.6))
            $anim.RepeatBehavior = [System.Windows.Media.Animation.RepeatBehavior]::Forever
            (El $U "laeuft_band_weg").BeginAnimation([System.Windows.Media.TranslateTransform]::XProperty, $anim)
            $S.BandLaeuft = $true
        }
    } else {
        $band.Visibility = [System.Windows.Visibility]::Hidden
        (El $U "laeuft_band_weg").BeginAnimation([System.Windows.Media.TranslateTransform]::XProperty, $null)
        $S.BandLaeuft = $false
    }
}

function Fertig-Schritte($S) {
    # Die naechsten Schritte je nach Wahl -> Liste von Text-Schluesseln.
    if ($S.Wo -eq "chat") { $z = @("t_fertig_chat_1", "t_fertig_chat_2", "t_fertig_chat_3") }
    else { $z = @("t_fertig_app_1", "t_fertig_app_2", "t_fertig_app_3") }
    if ($S.Wo -eq "beides") { $z += "t_fertig_beides_4" }
    if ($S.Wo -ne "app" -and $S.ChatKi -eq "spaeter") { $z += "t_fertig_spaeter_4" }
    elseif ($S.Wo -ne "app" -and $S.AnmeldenSpaeter) { $z += "t_fertig_anmelden_4" }
    return , @($z | Select-Object -First 4)
}

function Fertig-Fuellen($U, $S) {
    $k = KI-Ergebnis $S.Ergebnis
    $namen = @($k.Verbunden | ForEach-Object { KI-Anzeige $U $_ })
    $text = ""
    if ($S.Wo -ne "chat") {
        if ($namen.Count -gt 0) { $text = [string]::Format((Text $U "t_fertig_mit"), (Namen-Liste $U $namen)) }
        else { $text = (Text $U "t_fertig_ohne") }
        if (@($k.Fehler).Count -gt 0) {
            $text += " " + [string]::Format((Text $U "t_fertig_teilweise"), (Namen-Liste $U @($k.Fehler | ForEach-Object { KI-Anzeige $U $_ })))
        }
    }
    if ($S.Wo -ne "app" -and $S.ChatKi -ne "spaeter") {
        $text = ($text + " " + [string]::Format((Text $U "t_fertig_chat_ki"), (Chat-Name $U $S.ChatKi))).Trim()
    }
    (El $U "fertig_ki").Text = $text
    $schritte = Fertig-Schritte $S
    for ($i = 1; $i -le 4; $i++) {
        $da = $i -le $schritte.Count
        Sichtbar (El $U ("fertig_schritt" + $i)) $da
        if ($da) { (El $U ("fertig_text" + $i)).Text = (Text $U $schritte[$i - 1]) }
    }
    (El $U "fertig_protokoll").Text = $S.Log.ToString()
}

function Anmelden-Fuellen($U, $S) {
    (El $U "anmelden_titel").Text = [string]::Format((Text $U "t_anmelden_titel"), (Chat-Name $U $S.ChatKi))
    if (-not $S.Anmeldung) { (El $U "anmelden_stand").Text = "" }
}

function Prozess-Sichtbar-Starten([string]$pfad, $argumente) {
    # Ein kleines Textfenster mit genau EINEM Befehl (im Gate ersetzt).
    $heim = $env:USERPROFILE
    if (-not $heim -or -not (Test-Path -LiteralPath $heim)) { $heim = [IO.Path]::GetTempPath() }
    return (Start-Process -FilePath $pfad -ArgumentList $argumente -WorkingDirectory $heim -PassThru)
}

function Anmelden-Starten($U, $S) {
    # Das Anmelden des Herstellers (claude auth login / codex login) in
    # einem kleinen Textfenster; es oeffnet den Browser. Wann es fertig
    # ist, sagt der Stand-Befehl.
    $pfad = $S.ChatPfad
    Protokoll-Zeile $S ("Anmelden: """ + $pfad + """ " + ($CLI_ANMELDEN[$S.ChatKi] -join " "))
    (El $U "anmelden_los").IsEnabled = $false
    (El $U "anmelden_stand").Text = (Text $U "t_anmelden_warte")
    try {
        $S.Anmeldung = Prozess-Sichtbar-Starten $pfad $CLI_ANMELDEN[$S.ChatKi]
    } catch {
        Protokoll-Zeile $S ("Anmelden ging nicht: " + $_.Exception.Message)
        $S.Anmeldung = $null
        (El $U "anmelden_los").IsEnabled = $true
        (El $U "anmelden_stand").Text = (Text $U "t_anmelden_nicht")
        return
    }
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds(400)
    $t.Add_Tick({ param($sender, $e)
        $F = $global:OMCAD_F
        if (Anmelden-Takt $F.U $F.S) { $sender.Stop() } })
    $S.AnmeldeZeitgeber = $t
    $t.Start()
}

function Anmelden-Takt($U, $S) {
    # -> $true, wenn das Anmeldefenster zu ist (dann ist entschieden).
    if (-not $S.Anmeldung) { return $true }
    if (-not $S.Anmeldung.HasExited) { return $false }
    $S.Anmeldung = $null
    if (Cli-Angemeldet $S.ChatKi $S.ChatPfad) {
        Protokoll-Zeile $S "Angemeldet."
        $S.Angemeldet = $true
        Seite-Zeigen $U $S "fertig"
        Fertig-Fuellen $U $S
    } else {
        Protokoll-Zeile $S "Anmeldung nicht abgeschlossen."
        (El $U "anmelden_los").IsEnabled = $true
        (El $U "anmelden_stand").Text = (Text $U "t_anmelden_nicht")
    }
    return $true
}

function KI-Anzeige($U, [string]$name) {
    # Name aus ki_eintragen ("Codex") -> Name im Fenster ("ChatGPT-App").
    switch ($name) {
        "Codex"          { return (KI-Name $U "codex") }
        "Claude Desktop" { return (KI-Name $U "claude_desktop") }
        "Claude Code"    { return (KI-Name $U "claude_code") }
    }
    return $name
}

function Fehler-Fuellen($U, $S, [string]$schluessel) {
    (El $U "fehler_satz").Text = (Text $U $schluessel)
    (El $U "fehler_pfad").Text = $global:OMCAD_F.Protokoll
    (El $U "fehler_protokoll").Text = $S.Log.ToString()
    (El $U "fehler_kopiert").Text = ""
    $S.FehlerSchluessel = $schluessel
}

function Details-Umschalten($U, [string]$knopf, [string]$inhalt, [string]$protokoll, $S) {
    $an = ((El $U $knopf).IsChecked -eq $true)
    if ($inhalt) { Sichtbar (El $U $inhalt) (-not $an) }
    $box = El $U $protokoll
    $box.Text = $S.Log.ToString()
    Sichtbar $box $an
    if ($an) { $box.ScrollToEnd() }
}

function Installieren($U, $S) {
    # Der Knopf "Installieren": install.ps1 mit den Antworten starten.
    $S.ErgebnisDatei = Join-Path ([IO.Path]::GetTempPath()) ("open-mcp-cad-ergebnis-" + [guid]::NewGuid().ToString("N") + ".json")
    $argumente = Fenster-Argumente (Wahl-Aus-Zustand $S $S.ErgebnisDatei)
    $S.Argumente = $argumente
    Protokoll-Beginnen $S
    Protokoll-Zeile $S ("Antworten im Fenster: Profil " + (Wahl-Aus-Zustand $S "").Profil + "; wo " + $S.Wo + "; KI-Apps " + (@((Wahl-Aus-Zustand $S "").Ki) -join ",") + "; Chat-KI " + (Wahl-Aus-Zustand $S "").ChatKi + "; Python mitinstallieren " + ([bool]($S.PythonFehlt -and $S.PythonJa)) + "; trotzdem " + [bool]$S.Trotzdem)
    Protokoll-Zeile $S ("Gestartet: powershell " + (@($argumente | ForEach-Object { Arg-Text $_ }) -join " "))
    Seite-Zeigen $U $S "laeuft"
    Fortschritt $U $S 1
    $S.Lauf = Installer-Starten $argumente
}

function Zeile-Verarbeiten($U, $S, [string]$zeile) {
    Protokoll-Zeile $S $zeile
    $n = Schritt-Aus-Zeile $zeile
    if ($n -gt 0) { Fortschritt $U $S $n }
    # (nicht $u: PowerShell unterscheidet nicht zwischen $u und $U)
    $unter = Unterzeile-Aus-Zeile $zeile
    if ($unter -and $unter.Text) { Unterzeile-Setzen $U $S $unter.Text $unter.Wert }
    $box = El $U "laeuft_protokoll"
    if ($box.Visibility -eq [System.Windows.Visibility]::Visible) {
        $box.AppendText($zeile + "`r`n")
        $box.ScrollToEnd()
    }
}

function Lauf-Takt($U, $S) {
    # -> $true, wenn der Installer fertig ist (dann ist die Seite gewechselt).
    if (-not $S.Lauf) { return $true }
    $fertig = Installer-Takt $S.Lauf { param($z) Zeile-Verarbeiten $global:OMCAD_F.U $global:OMCAD_F.S $z }
    if (-not $fertig) { return $false }
    Lauf-Ende $U $S
    return $true
}

function Lauf-Ende($U, $S) {
    $rc = $S.Lauf.P.ExitCode
    $S.Ergebnis = Ergebnis-Lesen $S.ErgebnisDatei
    try { Remove-Item -LiteralPath $S.ErgebnisDatei -Force -ErrorAction SilentlyContinue } catch { }
    $S.Lauf = $null
    Protokoll-Zeile $S ("Rueckgabe des Installers: " + $rc)
    Unterzeile-Setzen $U $S "" ""
    if (Lauf-Gut $rc $S.Ergebnis) {
        $S.Rc = 0
        for ($i = 1; $i -le (Schritte-Zahl $S); $i++) { Schritt-Setzen $U $i "fertig" }
        (El $U "laeuft_leiste").Value = 100
        # Die KI fuer den Chat: noch anmelden? (claude auth status / codex
        # login status, 0 = angemeldet)
        $S.ChatPfad = "$($S.Ergebnis.chatPfad)"
        if ($S.ChatPfad -and -not (Cli-Angemeldet $S.ChatKi $S.ChatPfad)) {
            Seite-Zeigen $U $S "anmelden"
            return
        }
        Seite-Zeigen $U $S "fertig"
        Fertig-Fuellen $U $S
    } else {
        $S.Rc = 3
        if ($S.Schritt) { Schritt-Setzen $U $S.Schritt "fehler" }
        Seite-Zeigen $U $S "fehler"
        Fehler-Fuellen $U $S (Fehler-Schluessel $S.Ergebnis)
    }
}

function Verdrahten($U, $S) {
    # Jeder Knopf ruft eine Funktion; der Zustand liegt in $global:OMCAD_F
    # (Ereignisse laufen in einem eigenen Bereich).
    $global:OMCAD_F.U = $U
    $global:OMCAD_F.S = $S
    (El $U "willkommen_weiter").Add_Click({ $F = $global:OMCAD_F; Weiter $F.U $F.S "willkommen" })
    (El $U "willkommen_kopieren").Add_Click({
        $F = $global:OMCAD_F
        Ablage-Setzen (Text $F.U "t_ki_hilfe")
        (El $F.U "willkommen_kopiert").Text = (Text $F.U "t_kopiert")
    })
    (El $U "wo_weiter").Add_Click({ $F = $global:OMCAD_F; Wo-Lesen $F.U $F.S; Weiter $F.U $F.S "wo" })
    (El $U "chat_weiter").Add_Click({ $F = $global:OMCAD_F; Chat-Lesen $F.U $F.S; Weiter $F.U $F.S "chat_ki" })
    (El $U "anmelden_los").Add_Click({ $F = $global:OMCAD_F; Anmelden-Starten $F.U $F.S })
    (El $U "anmelden_spaeter").Add_Click({
        $F = $global:OMCAD_F
        $F.S.AnmeldenSpaeter = $true
        Seite-Zeigen $F.U $F.S "fertig"
        Fertig-Fuellen $F.U $F.S
    })
    (El $U "ki_weiter").Add_Click({ $F = $global:OMCAD_F; KI-Wahl-Lesen $F.U $F.S; Weiter $F.U $F.S "ki" })
    foreach ($n in @("ki_nochmal", "keine_nochmal")) {
        (El $U $n).Add_Click({ $F = $global:OMCAD_F; KI-Suchen $F.S; Weiter $F.U $F.S "wo" })
    }
    (El $U "keine_ohne").Add_Click({ $F = $global:OMCAD_F; $F.S.KiWahl = @(); Weiter $F.U $F.S "ki_keine" })
    foreach ($id in $KI_PROGRAMME) {
        (El $U ("ki_" + $id)).Add_Click({ $F = $global:OMCAD_F; KI-Wahl-Lesen $F.U $F.S })
    }
    (El $U "ki_holen_claude_desktop").Add_Click({ Url-Oeffnen $URL_CLAUDE_DESKTOP })
    (El $U "ki_holen_codex").Add_Click({ Url-Oeffnen $URL_CODEX })
    (El $U "keine_claude").Add_Click({ Url-Oeffnen $URL_CLAUDE_DESKTOP })
    (El $U "keine_codex").Add_Click({ Url-Oeffnen $URL_CODEX })
    (El $U "profil_weiter").Add_Click({ $F = $global:OMCAD_F; Weiter $F.U $F.S "profil" })
    (El $U "version_trotzdem").Add_Click({ $F = $global:OMCAD_F; $F.S.Trotzdem = $true; Weiter $F.U $F.S "version" })
    (El $U "version_zurueck").Add_Click({ $F = $global:OMCAD_F; Seite-Zeigen $F.U $F.S "profil" })
    (El $U "version_schliessen").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "python_ja").Add_Click({ $F = $global:OMCAD_F; $F.S.PythonJa = $true; Weiter $F.U $F.S "python" })
    (El $U "python_nein").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "bereit_zurueck").Add_Click({
        $F = $global:OMCAD_F
        $F.S.Trotzdem = $false; $F.S.PythonJa = $false
        Seite-Zeigen $F.U $F.S "wo"
    })
    (El $U "bereit_installieren").Add_Click({ $F = $global:OMCAD_F; Installieren $F.U $F.S; Takt-Starten $F.U $F.S })
    (El $U "fertig_schliessen").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "fehler_schliessen").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "fertig_anleitung").Add_Click({ $p = Anleitung-Pfad; if ($p) { Datei-Oeffnen $p } })
    (El $U "fehler_kopieren").Add_Click({
        $F = $global:OMCAD_F
        Ablage-Setzen ($F.S.Log.ToString())
        (El $F.U "fehler_kopiert").Text = (Text $F.U "t_kopiert")
    })
    $details = @{ laeuft_details = @("", "laeuft_protokoll"); fertig_details = @("fertig_inhalt", "fertig_protokoll"); fehler_details = @("fehler_inhalt", "fehler_protokoll") }
    foreach ($k in $details.Keys) {
        $h = { param($sender, $e)
               $F = $global:OMCAD_F
               $d = @{ laeuft_details = @("laeuft_schritte", "laeuft_protokoll"); fertig_details = @("fertig_inhalt", "fertig_protokoll"); fehler_details = @("fehler_inhalt", "fehler_protokoll") }[$sender.Name]
               Details-Umschalten $F.U $sender.Name $d[0] $d[1] $F.S }
        (El $U $k).Add_Checked($h)
        (El $U $k).Add_Unchecked($h)
    }
    # Schliessen, waehrend der Installer laeuft: nicht (er liefe unsichtbar weiter).
    $U.W.Add_Closing({ param($sender, $e) if ($global:OMCAD_F.S.Lauf) { $e.Cancel = $true } })
}

function Takt-Starten($U, $S) {
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds(100)
    $t.Add_Tick({ param($sender, $e)
        $F = $global:OMCAD_F
        if (Lauf-Takt $F.U $F.S) { $sender.Stop() } })
    $S.Zeitgeber = $t
    $t.Start()
}

function Klick($U, [string]$name) {
    # Fuer die Gates: ein Klick wie mit der Maus (Click-Ereignis bzw. Haken).
    $e = El $U $name
    if ($e -is [System.Windows.Controls.Primitives.ToggleButton] -and -not ($e -is [System.Windows.Controls.RadioButton])) {
        if (-not $e.IsEnabled) { throw "'$name' ist gesperrt" }
        $e.IsChecked = -not ($e.IsChecked -eq $true)
        $e.RaiseEvent((New-Object System.Windows.RoutedEventArgs ([System.Windows.Controls.Primitives.ButtonBase]::ClickEvent)))
        return
    }
    if (-not $e.IsEnabled) { throw "'$name' ist gesperrt" }
    if ($e.Visibility -ne [System.Windows.Visibility]::Visible) { throw "'$name' ist nicht zu sehen" }
    $e.RaiseEvent((New-Object System.Windows.RoutedEventArgs ([System.Windows.Controls.Primitives.ButtonBase]::ClickEvent)))
}

function Pumpen([scriptblock]$bis, [int]$sekunden = 120) {
    # Fuer die Gates: die Ereignisschleife laufen lassen (ohne Fenster), bis
    # $bis wahr ist. -> $true, wenn es rechtzeitig wahr wurde.
    $ende = (Get-Date).AddSeconds($sekunden)
    while ((Get-Date) -lt $ende) {
        $frame = New-Object System.Windows.Threading.DispatcherFrame
        $t = New-Object System.Windows.Threading.DispatcherTimer
        $t.Interval = [TimeSpan]::FromMilliseconds(50)
        $t.Tag = $frame
        $t.Add_Tick({ param($sender, $e) $sender.Stop(); $sender.Tag.Continue = $false })
        $t.Start()
        [System.Windows.Threading.Dispatcher]::PushFrame($frame)
        if (& $bis) { return $true }
    }
    return $false
}

# --- Konsole verbergen (das schwarze Fenster hinter dem Doppelklick) ----------

function Konsole-Fenster([int]$wie) {
    # 0 = verbergen, 5 = zeigen. Wirft nie; ohne Konsole nichts.
    try {
        if (-not ("OmcadEinrichtung.Konsole" -as [type])) {
            Add-Type -Namespace OmcadEinrichtung -Name Konsole -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern System.IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);
'@
        }
        $h = [OmcadEinrichtung.Konsole]::GetConsoleWindow()
        if ($h -ne [IntPtr]::Zero) { [void][OmcadEinrichtung.Konsole]::ShowWindow($h, $wie) }
        return $true
    } catch {
        return $false
    }
}

# --- Seiten als Bilder (ohne Fenster) ----------------------------------------

function Sichtbar-Effektiv($el) {
    $x = $el
    while ($x) {
        if ($x -is [System.Windows.UIElement] -and $x.Visibility -ne [System.Windows.Visibility]::Visible) { return $false }
        $x = [System.Windows.Media.VisualTreeHelper]::GetParent($x)
    }
    return $true
}

function Seite-Bild($U, [string]$datei) {
    # Rendert die Wurzel (ausgehaengt aus dem Fenster) als PNG in doppelter
    # Aufloesung. -> @{ ziele = Name -> [x, y, b, h]; texte = [...] }
    $r = $U.Wurzel
    $groesse = New-Object System.Windows.Size $r.Width, $r.Height
    $r.Measure($groesse)
    $r.Arrange((New-Object System.Windows.Rect 0, 0, $r.Width, $r.Height))
    $r.UpdateLayout()
    $bmp = New-Object System.Windows.Media.Imaging.RenderTargetBitmap ([int]($r.Width * 2)), ([int]($r.Height * 2)), 192, 192, ([System.Windows.Media.PixelFormats]::Pbgra32)
    $bmp.Render($r)
    $enc = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
    $enc.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bmp))
    $fs = [IO.File]::Create($datei)
    try { $enc.Save($fs) } finally { $fs.Close() }
    $ziele = @{}
    $texte = New-Object System.Collections.ArrayList
    $stapel = New-Object System.Collections.Stack
    $stapel.Push($r)
    while ($stapel.Count -gt 0) {
        $x = $stapel.Pop()
        for ($i = 0; $i -lt [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($x); $i++) {
            $stapel.Push([System.Windows.Media.VisualTreeHelper]::GetChild($x, $i))
        }
        if (-not ($x -is [System.Windows.FrameworkElement])) { continue }
        if (-not (Sichtbar-Effektiv $x)) { continue }
        if ($x.Name) {
            $p = $x.TransformToAncestor($r).Transform((New-Object System.Windows.Point 0, 0))
            $ziele[$x.Name] = @([Math]::Round($p.X, 1), [Math]::Round($p.Y, 1), [Math]::Round($x.ActualWidth, 1), [Math]::Round($x.ActualHeight, 1))
        }
        if ($x -is [System.Windows.Controls.TextBlock] -and $x.Text) { [void]$texte.Add($x.Text) }
        if ($x -is [System.Windows.Controls.TextBox] -and $x.Text) { [void]$texte.Add($x.Text) }
    }
    return @{ ziele = $ziele; texte = @($texte) }
}

function Demo-Zustand {
    # Ein erfundener Normalfall fuer die Bilder: Cadwork 2026, Claude
    # Desktop und ChatGPT-App gefunden, Python da. Keine echten Pfade.
    $S = Zustand-Neu
    $S.Geprueft = $true
    $S.OhneServer = $false
    $S.Installiert = @(2026, 2025)
    $S.Kandidaten = @(
        [pscustomobject]@{ Name = "userprofil_2026"; Pfad = "C:\Users\Public\Documents\cadwork\userprofil_2026\3d\API.x64"; Nummer = 2026; Installiert = $true },
        [pscustomobject]@{ Name = "userprofil_2025"; Pfad = "C:\Users\Public\Documents\cadwork\userprofil_2025\3d\API.x64"; Nummer = 2025; Installiert = $true })
    $S.ProfilIndex = 0
    $S.Version = [pscustomobject]@{ Passt = $true; Nummer = 2026; Text = "Cadwork 2026 im Profil userprofil_2026" }
    $S.KiGefunden = @("claude_desktop", "codex")
    $S.KiWahl = @("claude_desktop", "codex")
    $S.PythonWeg = "winget"
    $S.Wo = "beides"
    $S.ChatKi = "claude"
    return $S
}

#: Zusaetzliche Bilder der Seite "laeuft" (Rueckmeldung 2026-10-09: was
#: passiert bei langen Downloads?): Name -> Unterzeile (Schluessel, Wert).
$LAEUFT_BILDER = [ordered]@{
    laeuft_python = @("t_unter_python_laden", "")
    laeuft_pip    = @("t_unter_pip_laden", "numpy")
}

function Seiten-Rendern($U, [string]$ordner) {
    # Jede Seite einmal, im Normalfall (Demo-Zustand). -> seiten.json
    New-Item -ItemType Directory -Force -Path $ordner | Out-Null
    $w = $U.W
    $w.Content = $null              # die Wurzel steht jetzt fuer sich
    $global:OMCAD_F.Protokoll = "C:\Users\Public\OpenMcpCad_installer.log"
    $S = Demo-Zustand
    $global:OMCAD_F.U = $U; $global:OMCAD_F.S = $S
    $aus = [ordered]@{}
    foreach ($name in (@($SEITEN) + @($LAEUFT_BILDER.Keys))) {
        $seite = $name
        if ($LAEUFT_BILDER.Contains($name)) { $seite = "laeuft" }
        $S = Demo-Zustand
        $global:OMCAD_F.S = $S
        switch ($seite) {
            "version" {
                $S.Version = [pscustomobject]@{ Passt = $false; Nummer = 2025; Text = "Dieses Paket braucht Cadwork 3D $CADWORK_JAHR. Gefunden: Cadwork 2025 im Profil userprofil_2025." }
            }
            "python" { $S.PythonFehlt = $true; $S.PythonWeg = "python.org" }
            "ki_keine" { $S.KiGefunden = @(); $S.KiWahl = @() }
        }
        Seite-Zeigen $U $S $seite
        if ($seite -eq "laeuft") {
            if ($LAEUFT_BILDER.Contains($name)) {
                Fortschritt $U $S 3
                Unterzeile-Setzen $U $S $LAEUFT_BILDER[$name][0] $LAEUFT_BILDER[$name][1]
                # Das Band steht im Bild still, an einer sichtbaren Stelle.
                (El $U "laeuft_band_weg").BeginAnimation([System.Windows.Media.TranslateTransform]::XProperty, $null)
                (El $U "laeuft_band_weg").X = 230
            } else {
                Fortschritt $U $S 2
                Unterzeile-Setzen $U $S "" ""
            }
        }
        if ($seite -eq "fertig") {
            $S.Ergebnis = [pscustomobject]@{ fertig = $true; kiListe = @([pscustomobject]@{ name = "Claude Desktop"; status = "eingetragen" }, [pscustomobject]@{ name = "Codex"; status = "eingetragen" }) }
            Fertig-Fuellen $U $S
        }
        if ($seite -eq "fehler") { Fehler-Fuellen $U $S "t_fehler_server" }
        $datei = Join-Path $ordner ("fenster-" + $name + ".png")
        $info = Seite-Bild $U $datei
        $aus[$name] = @{ datei = (Split-Path -Leaf $datei); breite = $U.Wurzel.Width; hoehe = $U.Wurzel.Height; ziele = $info.ziele; texte = $info.texte }
    }
    $json = ConvertTo-Json -InputObject $aus -Depth 6
    [IO.File]::WriteAllText((Join-Path $ordner "seiten.json"), $json, (New-Object System.Text.UTF8Encoding $false))
}

# --- Hauptlauf -------------------------------------------------------------------

function Fenster-Hauptlauf {
    try {
        Wpf-Laden
        $U = Fenster-Bauen
    } catch {
        Write-Host ("Das Einrichtungsfenster laesst sich nicht oeffnen: " + $_.Exception.Message)
        return $FENSTER_GEHT_NICHT
    }
    if ($global:OMCAD_F.Rendern) {
        Seiten-Rendern $U $global:OMCAD_F.Rendern
        return 0
    }
    $S = Zustand-Neu
    Verdrahten $U $S
    Seite-Zeigen $U $S "willkommen"
    $U.W.Add_ContentRendered({
        $F = $global:OMCAD_F
        # Erst jetzt, da das Fenster steht: das schwarze Fenster verbergen
        # (scheitert das, bleibt es eben dahinter sichtbar).
        $F.Verborgen = Konsole-Fenster 0
        [void]$F.U.W.Dispatcher.BeginInvoke([System.Windows.Threading.DispatcherPriority]::Background, [action]{
            $F = $global:OMCAD_F
            try { Lage-Pruefen $F.S } catch { Protokoll-Zeile $F.S ("Pruefen ging nicht: " + $_.Exception.Message) }
            if ($F.S.Seite -eq "willkommen") { Willkommen-Fuellen $F.U $F.S }
        })
    })
    try {
        [void]$U.W.ShowDialog()
    } catch {
        Write-Host ("Das Einrichtungsfenster brach ab: " + $_.Exception.Message)
        return $FENSTER_GEHT_NICHT
    }
    return $S.Rc
}

if ($global:OMCAD_F.Nur) { return }
$rc = $FENSTER_GEHT_NICHT
try {
    $rc = Fenster-Hauptlauf
} catch {
    Write-Host ("Das Einrichtungsfenster brach ab: " + $_.Exception.Message)
    $rc = $FENSTER_GEHT_NICHT
} finally {
    # Geht es im Textfenster weiter (1_INSTALLIEREN.cmd), muss es zu sehen
    # sein - aber nur zurueckholen, was dieses Skript selbst verborgen hat.
    if ($rc -ne 0 -and $rc -ne 3 -and $global:OMCAD_F.Verborgen) { Konsole-Fenster 5 | Out-Null }
}
exit $rc
