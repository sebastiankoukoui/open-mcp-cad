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
Argumente; bei mehr als einem angehakten Cadwork -Profile "a;b" statt
-Profil). Kopieren, Python, Server, Umgebungsvariable und Eintragen in
die KI-Programme macht also genau derselbe Code wie im Textfenster. Dessen
Ausgabe liest das Fenster Zeile fuer Zeile (Schritte "== n/5"), schreibt
sie ins Protokoll ($Protokoll) und zeigt sie unter "Details"; den Stand am
Ende liest es aus -ErgebnisDatei.

Rueckgabe wie install.ps1: 0 = alles da, 3 = nicht vollstaendig (auch:
Fenster vor dem Installieren geschlossen). 10 = das Fenster ging gar nicht
(kein WPF, kein STA, XAML kaputt): dann startet 1_INSTALLIEREN.cmd das
Textfenster - nie stilles Nichts.

Alle sichtbaren Texte stehen seit 2026-10-10 in install_fenster_texte.xml
(UTF-8, vier Sprachen, Deutsch verbindlich); die XAML nennt nur ihre
Schluessel. Die Sprache kommt aus der Anzeigesprache von Windows
(CurrentUICulture: de*/fr*/it* -> diese, sonst en; Sprache-Waehlen),
-Sprache de|fr|it|en geht vor. Diese Datei bleibt reines ASCII: Windows
PowerShell 5.1 liest Skripte ohne BOM als ANSI.

Seit 2026-10-10 auch: liegt im gewaehlten Profil noch das alte Plugin
"LignoAI Connect" (Alte-Plugins aus install.ps1), steht auf "Bereit" ein
Haken (vorausgewaehlt) - dann startet install.ps1 mit -AltesWegraeumen und
verschiebt es in eine Sicherung.

Mehrere Cadwork-Versionen auf einem PC (seit 2026-10-10): die Seite
"Welches Cadwork?" hat je Profil einen Haken; vorab angehakt sind alle
Profile ab $CADWORK_ERLAUBT_AB mit installiertem Cadwork (Profil-Vorauswahl
aus install.ps1), sonst die bisherige Vorgabe. Startet das Dock
1_INSTALLIEREN.cmd ohne Schalter, kommt das Plugin so in jedes erlaubte,
installierte Cadwork. "Weiter" nur mit mindestens einem Haken.

Fuer die Gates und die Bilder der Anleitung:
    -NurFunktionen      (dot-sourced) nur die Funktionen laden
    -Rendern ORDNER     jede Seite ohne Fenster als PNG (RenderTargetBitmap)
                        plus seiten.json (Lage der benannten Teile, Texte)
    -CadworkWurzel/-CadworkProgramm/-PythonZiel/-OhneServer/
    -OhneUmgebungsvariable  werden an install.ps1 weitergereicht
    -Protokoll DATEI    statt C:\Users\Public\OpenMcpCad_installer.log
    -Sprache de|fr|it|en  statt der Anzeigesprache von Windows
    -TexteDatei DATEI   statt install_fenster_texte.xml daneben
#>
param(
    [switch]$NurFunktionen,
    [string]$Sprache = "",
    # Nie die echten Symbole der Apps vom PC lesen (Strich-Symbole), etwa
    # fuer Bilder der Anleitung; -Rendern tut das immer.
    [switch]$OhneLogos,
    [string]$TexteDatei = "",
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
    OhneLogos  = ([bool]$OhneLogos -or [bool]$Rendern)
    Protokoll  = $Protokoll
    Xaml       = $XamlDatei
    SpracheWunsch = $Sprache
    Texte      = $TexteDatei
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
# Claude Code (Claude im Befehlsfenster): die Einrichtung bei Anthropic
# (dieselbe Seite nennt install.ps1 beim Befehl des Herstellers).
$URL_CLAUDE_CODE = "https://code.claude.com/docs/en/setup"
# "Nochmal suchen" (seit 2026-10-10, Rueckmeldung: es wirkte, als haette man
# nicht gedrueckt): der Kreisel steht mindestens so lange (ms), die Zeile
# mit dem Ergebnis so lange.
$SUCHE_MIN_MS = 600
$SUCHE_MELDUNG_MS = 4000
# Die Store-Pakete der Apps (fuer ihr echtes Symbol, Logos-Laden).
$APP_PAKETE = [ordered]@{ claude_desktop = "Claude"; codex = "OpenAI.Codex" }
# Die Programme, die das Fenster anbietet (ids wie in ki_eintragen).
$KI_PROGRAMME = @("claude_desktop", "codex", "claude_code")
# Die Seiten, in der Reihenfolge des Ablaufs.
$SEITEN = @("willkommen", "wo", "ki", "ki_keine", "chat_ki", "profil", "version", "python", "bereit", "laeuft", "anmelden", "fertig", "fehler")
# Wo der Nutzer mit der KI arbeitet (Seite "wo", seit 2026-10-09): in der
# KI-App, im Chat in Cadwork oder beides; und welche KI der Chat nimmt
# (Seite "chat_ki"): claude, codex oder spaeter (Schluessel, lokale KI).
$WO = @("app", "chat", "beides")
$CHAT_KI = @("claude", "codex", "spaeter")
# Die Sprachen des Fensters (seit 2026-10-10), wie in install_fenster_texte.xml.
$SPRACHEN = @("de", "fr", "it", "en")
# Wie lange nach "Text kopieren" der Haken und "Kopiert." stehen (ms), und
# wie viel vom Text der Tooltip ueber "diesen Text" zeigt (Zeichen).
$KOPIERT_MS = 2500
$VORSCHAU_ZEICHEN = 110

# --- Sprache und Texte (ohne WPF; test_installer I31) -------------------------

function Sprache-Waehlen([string]$wunsch, [string]$kultur) {
    # -Sprache geht vor (nur eine der vier), sonst die Anzeigesprache von
    # Windows: de*/fr*/it* (auch de-CH, fr-CH, it-CH, gsw = Schweizerdeutsch)
    # -> diese, alles andere -> en.
    $w = "$wunsch".Trim().ToLowerInvariant()
    if ($SPRACHEN -contains $w) { return $w }
    $k = ("$kultur".Trim().ToLowerInvariant() -split '[-_]')[0]
    if ($k -eq "gsw") { $k = "de" }
    if (@("de", "fr", "it") -contains $k) { return $k }
    return "en"
}

function Texte-Datei {
    if ($global:OMCAD_F.Texte) { return $global:OMCAD_F.Texte }
    return (Join-Path $global:OMCAD_F.Hier "install_fenster_texte.xml")
}

function Texte-Laden([string]$datei, [string]$sprache) {
    # Alle Texte einer Sprache -> Hashtable Schluessel -> Text. Fehlt einer,
    # steht der deutsche da (die Gates verlangen trotzdem jeden).
    $x = New-Object System.Xml.XmlDocument
    $x.Load($datei)
    $aus = @{}
    foreach ($t in @($x.DocumentElement.SelectNodes("t"))) {
        $n = $t.SelectSingleNode($sprache)
        if ($null -eq $n -or -not $n.InnerText) { $n = $t.SelectSingleNode("de") }
        $aus[$t.GetAttribute("id")] = $n.InnerText
    }
    return $aus
}

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
    # $W: Profil, Profile (alle angehakten), Trotzdem, Python, Ki (Liste von ids), ErgebnisDatei und
    # die durchgereichten Wurzel, Programm, PythonZiel, OhneServer,
    # OhneUmgebungsvariable. -> Liste der Argumente fuer powershell.exe.
    $a = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", $OMCAD_INSTALL, "-OhnePause", "-Utf8Ausgabe")
    if ($W.ErgebnisDatei) { $a += @("-ErgebnisDatei", $W.ErgebnisDatei) }
    $a += @("-CadworkWurzel", $W.Wurzel, "-CadworkProgramm", $W.Programm)
    # Mehr als ein Profil: -Profile "a;b" (seit 2026-10-10), sonst -Profil.
    $pf = @($W.Profile | Where-Object { $_ })
    # PROFILE-ANFANG (test_installer I39d ersetzt diese Zeile)
    if ($pf.Count -gt 1) { $a += @("-Profile", ($pf -join ";")) }
    # PROFILE-ENDE
    elseif ($W.Profil) { $a += @("-Profil", $W.Profil) }
    if ($W.Trotzdem) { $a += "-TrotzdemKopieren" }
    if ($W.Python) { $a += "-PythonInstallieren" }
    $ki = @($W.Ki | Where-Object { $_ })
    if ($ki.Count -gt 0) { $a += @("-KiNur", ($ki -join ",")) } else { $a += "-OhneKiEintrag" }
    if ($W.PythonZiel) { $a += @("-PythonZiel", $W.PythonZiel) }
    if ($W.OhneServer) { $a += "-OhneServer" }
    if ($W.OhneUmgebungsvariable) { $a += "-OhneUmgebungsvariable" }
    if ($W.ChatKi -eq "claude" -or $W.ChatKi -eq "codex") { $a += @("-ChatKi", $W.ChatKi) }
    if ($W.Alt) { $a += "-AltesWegraeumen" }
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
    # In eines der angehakten Cadwork nicht kopiert (seit 2026-10-10).
    if ($erg.plugin -eq "teilweise") { return "t_fehler_teilweise" }
    if ($erg.altFehler) { return "t_fehler_alt" }
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
        # Die angehakten Profile (Indizes in Kandidaten) und je eines ihre
        # Version; Version oben ist die erste, die nicht passt (sonst die
        # erste), VersionIndex ihr Profil (seit 2026-10-10).
        ProfilWahl = @(); Versionen = @(); VersionIndex = 0
        PythonFehlt = $false; PythonWeg = ""; PythonJa = $false
        KiGefunden = @(); KiWahl = @()
        Wo = "app"; ChatKi = "claude"; CliDa = @{ claude = $null; codex = $null }
        Alte = @(); AltWeg = $true
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
        $S.ProfilWahl = Profil-Vorauswahl $S.Kandidaten $F.Programm
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
    if ($global:OMCAD_F.U) { Logos-Laden $global:OMCAD_F.U $S }
}

function KI-Suchen($S) {
    # Erst zuweisen, dann aufzaehlen: KI-Finden gibt die Liste als EIN
    # Objekt zurueck (leer gaebe es sonst einen $null-Eintrag).
    $liste = KI-Finden
    $S.KiGefunden = @($liste | Where-Object { $_ } | ForEach-Object { $_.programm })
    # Was gefunden ist, ist angehakt (der Nutzer kann es abwaehlen).
    $S.KiWahl = @($S.KiGefunden)
}

function Profil-Wahl($S) {
    # Die angehakten Profile (Indizes in Kandidaten), ohne Luecken.
    $w = @($S.ProfilWahl | Where-Object { $null -ne $_ } | ForEach-Object { [int]$_ })
    return , $w
}

function Version-Setzen($S) {
    # Jedes angehakte Profil: seine Cadwork-Version (Version-Pruefen aus
    # install.ps1) und das alte Plugin darin (Alte-Plugins).
    $S.Versionen = @()
    $S.Alte = @()
    $S.Version = $null
    $wahl = Profil-Wahl $S
    if ($wahl.Count -gt 0) { $S.ProfilIndex = [int]$wahl[0]; $S.VersionIndex = [int]$wahl[0] }
    foreach ($i in $wahl) {
        $k = @($S.Kandidaten)[$i]
        $v = Version-Pruefen $k.Pfad $S.Installiert $global:OMCAD_F.Programm
        $S.Versionen += $v
        # Die Warnseite gilt dem ersten, das nicht passt.
        if (-not $S.Version -or ($S.Version.Passt -and -not $v.Passt)) { $S.Version = $v; $S.VersionIndex = [int]$i }
        $S.Alte += @(Alte-Plugins $k.Pfad | Where-Object { $_ })
    }
}

function Wahl-Aus-Zustand($S, [string]$ergebnisDatei) {
    $F = $global:OMCAD_F
    $pfade = @()
    if (@($S.Kandidaten).Count -gt 0) { $pfade = @(Profil-Wahl $S | ForEach-Object { @($S.Kandidaten)[$_].Pfad }) }
    $profil = ""
    if ($pfade.Count -gt 0) { $profil = $pfade[0] }
    return @{
        Profil = $profil; Profile = $pfade; Trotzdem = [bool]$S.Trotzdem
        Python = ([bool]$S.PythonFehlt -and [bool]$S.PythonJa)
        Ki = $(if ($S.Wo -eq "chat") { @() } else { @($S.KiWahl) }); ErgebnisDatei = $ergebnisDatei
        ChatKi = $(if ($S.Wo -eq "app") { "" } else { $S.ChatKi })
        Alt = ((@($S.Alte).Count -gt 0) -and [bool]$S.AltWeg)
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
    Texte-Setzen $U (Sprache-Waehlen $global:OMCAD_F.SpracheWunsch ([Globalization.CultureInfo]::CurrentUICulture.Name))
    return $U
}

function Texte-Setzen($U, [string]$sprache) {
    # Die Texte der Sprache als Ressourcen der Wurzel: jedes
    # {DynamicResource t_...} der XAML und jedes (Text $U ...) liest sie dort.
    $t = Texte-Laden (Texte-Datei) $sprache
    foreach ($k in @($t.Keys)) { $U.Wurzel.Resources[$k] = $t[$k] }
    $U.W.Title = $t["t_fenster_titel"]
    # Ueber "diesen Text": der Anfang dessen, was kopiert wird.
    $h = $t["t_ki_hilfe"]
    if ($h.Length -gt $VORSCHAU_ZEICHEN) { $h = $h.Substring(0, $h.LastIndexOf(" ", $VORSCHAU_ZEICHEN)) + " " + [string][char]0x2026 }
    (El $U "willkommen_link").ToolTip = $h
    $U.Wurzel.Language = [System.Windows.Markup.XmlLanguage]::GetLanguage($sprache)
    $U.Sprache = $sprache
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
        # Seit 2026-10-10: jede Wahl immer waehlbar; gefunden oder nicht,
        # die Plakette sagt es.
        if ($S.CliDa[$k]) { (El $U ("chat_stand_" + $k)).Text = (Text $U "t_gefunden") }
        else { (El $U ("chat_stand_" + $k)).Text = (Text $U "t_wird_mitinstalliert") }
        Sichtbar (El $U ("chat_marke_" + $k)) $true
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
        # Seit 2026-10-10 (Rueckmeldung): jede App immer zu sehen, gefunden
        # mit Plakette, sonst "Holen" (die offizielle Seite).
        Sichtbar (El $U ("ki_marke_" + $id)) $da
        Sichtbar (El $U ("ki_holen_" + $id)) (-not $da)
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
    # Je Profil ein Haken (seit 2026-10-10, mehrere Cadwork-Versionen auf
    # einem PC; vorher eine Wahl). "empfohlen" steht an jedem, das die
    # Vorauswahl anhakt (Profil-Vorauswahl aus install.ps1).
    $liste = El $U "profil_liste"
    foreach ($alt in $liste.Children) { if ($alt.Name) { $U.W.UnregisterName($alt.Name) } }
    $liste.Children.Clear()
    $empfohlen = Profil-Vorauswahl $S.Kandidaten $global:OMCAD_F.Programm
    $wahl = Profil-Wahl $S
    $stil = $U.Wurzel.Resources["WahlHaken"]
    for ($i = 0; $i -lt @($S.Kandidaten).Count; $i++) {
        $k = @($S.Kandidaten)[$i]
        $cb = New-Object System.Windows.Controls.CheckBox
        $cb.Style = $stil
        $cb.Tag = $i
        $cb.Name = "profil_wahl_" + $i
        $sp = New-Object System.Windows.Controls.StackPanel
        $t1 = New-Object System.Windows.Controls.TextBlock
        if ($k.Nummer -ge 0) { $t1.Text = [string]::Format((Text $U "t_profil_name"), $k.Nummer) }
        else { $t1.Text = (Text $U "t_profil_unbekannt") }
        $t1.FontWeight = [System.Windows.FontWeights]::SemiBold
        $t2 = New-Object System.Windows.Controls.TextBlock
        $teile = @()
        if ($empfohlen -contains $i) { $teile += (Text $U "t_profil_empfohlen") }
        if ($k.Installiert) { $teile += (Text $U "t_profil_installiert") } else { $teile += (Text $U "t_profil_nicht_installiert") }
        $t2.Text = ($teile -join (Text $U "t_trenner"))
        $t2.FontSize = 12.5
        $t2.Foreground = $U.Wurzel.Resources["Neben"]
        [void]$sp.Children.Add($t1)
        [void]$sp.Children.Add($t2)
        $cb.Content = $sp
        $cb.ToolTip = $k.Pfad
        # Erst setzen, dann verdrahten (sonst liefe der Handler beim Bauen).
        $cb.IsChecked = ($wahl -contains $i)
        $cb.Add_Checked({ param($sender, $e) Profil-Wahl-Lesen $global:OMCAD_F.U $global:OMCAD_F.S })
        $cb.Add_Unchecked({ param($sender, $e) Profil-Wahl-Lesen $global:OMCAD_F.U $global:OMCAD_F.S })
        [void]$liste.Children.Add($cb)
        $U.W.RegisterName($cb.Name, $cb)
    }
    Profil-Weiter-Setzen $U $S
}

function Profil-Weiter-Setzen($U, $S) {
    # "Weiter" nur mit mindestens einem Haken.
    # PROFIL-WEITER-ANFANG (test_installer I39c-K ersetzt diese Zeile)
    (El $U "profil_weiter").IsEnabled = ((Profil-Wahl $S).Count -gt 0)
    # PROFIL-WEITER-ENDE
}

function Profil-Wahl-Lesen($U, $S) {
    # Die Haken -> $S.ProfilWahl; eine neue Wahl gilt als noch nicht
    # bestaetigt (Trotzdem), die Versionen werden neu geprueft.
    $w = @()
    for ($i = 0; $i -lt @($S.Kandidaten).Count; $i++) {
        $cb = $U.W.FindName("profil_wahl_" + $i)
        if ($cb -and $cb.IsChecked -eq $true) { $w += $i }
    }
    $S.ProfilWahl = $w
    $S.Trotzdem = $false
    Version-Setzen $S
    Profil-Weiter-Setzen $U $S
}

# --- Zurueck, Chat dazu (seit 2026-10-10) -------------------------------------

#: Die Seiten mit Fragen: nur zu diesen fuehrt "Zurueck".
$FRAGE_SEITEN = @("willkommen", "wo", "ki", "ki_keine", "chat_ki", "profil", "version", "python", "bereit")

function Zurueck-Ziel($S) {
    # Die Seite vor der aktuellen im Verlauf (nur Fragen, nie dieselbe).
    # -> @{ Seite; Rest = Verlauf davor } oder $null.
    $v = @($S.Verlauf)
    for ($i = $v.Count - 1; $i -ge 0; $i--) {
        if ($v[$i] -eq $S.Seite -or $FRAGE_SEITEN -notcontains $v[$i]) { continue }
        $rest = @()
        if ($i -gt 0) { $rest = @($v[0..($i - 1)]) }
        return @{ Seite = $v[$i]; Rest = $rest }
    }
    return $null
}

function Zurueck($U, $S) {
    $z = Zurueck-Ziel $S
    if (-not $z) { return }
    # Die Antwort der Seite, zu der es zurueckgeht, gilt wieder als offen.
    if ($z.Seite -eq "version") { $S.Trotzdem = $false }
    if ($z.Seite -eq "python") { $S.PythonJa = $false }
    $S.Verlauf = $z.Rest
    Seite-Zeigen $U $S $z.Seite
}

function Chat-Dazu($U, $S) {
    # "Chat in Cadwork auch einrichten" auf "Fertig": die KI-App bleibt
    # (beides), es geht mit der Wahl der KI fuer den Chat weiter; installiert
    # wird danach nochmals (install.ps1 aendert nichts, was schon stimmt).
    $S.Wo = "beides"
    $S.Lauf = $null
    Seite-Zeigen $U $S "chat_ki"
}

# --- Nochmal suchen (seit 2026-10-10) -----------------------------------------
# Rueckmeldung: "Nochmal suchen" zeigte nichts. Jetzt ein Kreisel und
# "Suche ...", der Knopf gesperrt; gesucht wird in einem eigenen Runspace
# (die Ereignisschleife laeuft weiter), mit DENSELBEN Funktionen wie sonst
# (ihr Text wird mitgegeben, auch ersetzte im Gate); danach "Gefunden: ..."
# bzw. "Nichts Neues gefunden".

function Hintergrund-Skript([string[]]$funktionen, [string]$rest) {
    $teile = foreach ($n in $funktionen) { "function " + $n + " {`n" + (Get-Item ("function:" + $n)).ScriptBlock.ToString() + "`n}" }
    return (($teile -join "`n") + "`n" + $rest)
}

function Hintergrund-Starten([string]$skript) {
    $ps = [powershell]::Create()
    [void]$ps.AddScript($skript)
    return @{ PS = $ps; H = $ps.BeginInvoke(); Start = [DateTime]::UtcNow }
}

function Hintergrund-Ergebnis($h) {
    # Das Ergebnis eines fertigen Hintergrund-Laufs (oder $null). Wirft nie.
    $erg = $null
    try { $erg = @($h.PS.EndInvoke($h.H))[0] } catch { }
    try { $h.PS.Dispose() } catch { }
    return $erg
}

function Suche-Anzeigen($U, [bool]$laeuft, [string]$text) {
    foreach ($v in @("ki", "keine")) {
        $zeile = El $U ($v + "_suche")
        $kreisel = El $U ($v + "_kreisel")
        (El $U ($v + "_suche_text")).Text = $text
        if ($text) { $zeile.Visibility = [System.Windows.Visibility]::Visible } else { $zeile.Visibility = [System.Windows.Visibility]::Hidden }
        Sichtbar $kreisel $laeuft
        if ($laeuft) {
            $a = New-Object System.Windows.Media.Animation.DoubleAnimation
            $a.From = 0; $a.To = 360
            $a.Duration = New-Object System.Windows.Duration ([TimeSpan]::FromSeconds(0.9))
            $a.RepeatBehavior = [System.Windows.Media.Animation.RepeatBehavior]::Forever
            $kreisel.RenderTransform.BeginAnimation([System.Windows.Media.RotateTransform]::AngleProperty, $a)
        } else {
            $kreisel.RenderTransform.BeginAnimation([System.Windows.Media.RotateTransform]::AngleProperty, $null)
        }
    }
    foreach ($k in @("ki_nochmal", "keine_nochmal")) { (El $U $k).IsEnabled = (-not $laeuft) }
}

function Suche-Starten($U, $S) {
    if ($S.Suche) { return }
    $skript = Hintergrund-Skript @("Im-Pfad", "KI-Finden", "Cli-Pfad") '$l = KI-Finden; @{ ki = @($l | Where-Object { $_ } | ForEach-Object { $_.programm }); claude = (Cli-Pfad "claude"); codex = (Cli-Pfad "codex") }'
    $S.Suche = Hintergrund-Starten $skript
    $S.Suche.Vorher = @($S.KiGefunden)
    Suche-Anzeigen $U $true (Text $U "t_suche_laeuft")
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds(50)
    $t.Add_Tick({ param($sender, $e) $F = $global:OMCAD_F; if (Suche-Takt $F.U $F.S) { $sender.Stop() } })
    $t.Start()
}

function Suche-Takt($U, $S) {
    # -> $true, wenn die Suche fertig ist (dann ist die Seite gewechselt).
    # (nicht $s: PowerShell unterscheidet nicht zwischen $s und $S)
    $su = $S.Suche
    if (-not $su) { return $true }
    if (-not $su.H.IsCompleted) { return $false }
    if (([DateTime]::UtcNow - $su.Start).TotalMilliseconds -lt $SUCHE_MIN_MS) { return $false }
    $erg = Hintergrund-Ergebnis $su
    $S.Suche = $null
    if ($erg) {
        $neu = @($erg.ki | Where-Object { $_ })
        # Was der Nutzer abgewaehlt hat, bleibt abgewaehlt; Neues ist angehakt.
        $S.KiWahl = @(@($S.KiWahl | Where-Object { $neu -contains $_ }) + @($neu | Where-Object { @($su.Vorher) -notcontains $_ }) | Select-Object -Unique)
        $S.KiGefunden = $neu
        $S.CliDa = @{ claude = $erg.claude; codex = $erg.codex }
    }
    $neue = @($S.KiGefunden | Where-Object { @($su.Vorher) -notcontains $_ })
    Weiter $U $S "wo"
    if ($neue.Count -gt 0) { $text = [string]::Format((Text $U "t_suche_neu"), (Namen-Liste $U @($neue | ForEach-Object { KI-Name $U $_ }))) }
    else { $text = Text $U "t_suche_nichts" }
    Suche-Anzeigen $U $false $text
    $S.SucheMeldung = $text
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds($SUCHE_MELDUNG_MS)
    $t.Add_Tick({ param($sender, $e)
        $sender.Stop()
        $F = $global:OMCAD_F
        if (-not $F.S.Suche) { Suche-Anzeigen $F.U $false ""; $F.S.SucheMeldung = "" } })
    $t.Start()
    return $true
}

# --- Die echten Symbole der Apps (seit 2026-10-10) ----------------------------
# Neben jeder Wahl das Symbol der App, wie es auf dem PC liegt: aus dem
# Store-Paket (AppxManifest: Square44x44Logo, sonst Logo; die passende
# Groesse), sonst aus der exe (ExtractAssociatedIcon). Nichts davon liegt im
# Paket (Markenrecht); fehlt es oder ist es kaputt, das Strich-Symbol der
# XAML. Get-AppxPackage ist langsam: das laeuft im Hintergrund.

function App-Paket-Ort([string]$name) {
    # Der Ordner des installierten Store-Pakets, sonst $null. Wirft nie.
    try {
        $p = @(Get-AppxPackage -Name $name -ErrorAction Stop) | Select-Object -First 1
        if ($p -and $p.InstallLocation) { return [string]$p.InstallLocation }
    } catch { }
    return $null
}

function Manifest-Logo([string]$ort) {
    # Das beste PNG des Pakets fuer rund 32 px (bei 200 %: 64): zuerst
    # Square44x44Logo (targetsize-48/64, ohne Hintergrund), sonst Logo
    # (scale-200, -100). -> voller Pfad oder $null. Wirft nie.
    try {
        $m = Join-Path $ort "AppxManifest.xml"
        if (-not (Test-Path -LiteralPath $m -PathType Leaf)) { return $null }
        $x = [IO.File]::ReadAllText($m)
        $rel = @()
        $a = [regex]::Match($x, 'Square44x44Logo="([^"]+)"')
        if ($a.Success) { $rel += $a.Groups[1].Value }
        $b = [regex]::Match($x, '<Logo>([^<]+)</Logo>')
        if ($b.Success) { $rel += $b.Groups[1].Value.Trim() }
        # lightunplated: fuer helle Flaechen (das Fenster ist hell); unplated
        # allein ist oft weiss (fuer die dunkle Taskleiste, gemessen an der
        # ChatGPT-App 2026-10-10).
        $rang = @("targetsize-48_altform-lightunplated", "targetsize-64_altform-lightunplated", "targetsize-48_altform-unplated", "targetsize-64_altform-unplated", "targetsize-48", "targetsize-64", "targetsize-32_altform-unplated", "targetsize-32", "scale-200", "scale-150", "scale-100", "")
        foreach ($r in $rel) {
            $pfad = Join-Path $ort $r
            $ordner = Split-Path -Parent $pfad
            $stamm = [IO.Path]::GetFileNameWithoutExtension($pfad)
            $endung = [IO.Path]::GetExtension($pfad)
            $da = @(Get-ChildItem -LiteralPath $ordner -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like ($stamm + "*" + $endung) })
            foreach ($k in $rang) {
                foreach ($d in $da) {
                    $mitte = $d.Name.Substring($stamm.Length, $d.Name.Length - $stamm.Length - $endung.Length).Trim(".")
                    if ($mitte -eq $k) { return $d.FullName }
                }
            }
        }
    } catch { }
    return $null
}

function Logo-Bild([string]$pfad) {
    # Ein PNG (oder das Symbol einer exe) als Bild fuer WPF, sonst $null
    # (fehlt, kaputt, zu klein). Wirft nie.
    try {
        if (-not $pfad -or -not (Test-Path -LiteralPath $pfad -PathType Leaf)) { return $null }
        $ms = $null
        if ($pfad -match '(?i)\.exe$') {
            Add-Type -AssemblyName System.Drawing
            $ico = [System.Drawing.Icon]::ExtractAssociatedIcon($pfad)
            if (-not $ico) { return $null }
            $ms = New-Object IO.MemoryStream
            $ico.ToBitmap().Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
            $ms.Position = 0
        } else {
            $ms = New-Object IO.MemoryStream (, [IO.File]::ReadAllBytes($pfad))
        }
        $bild = New-Object System.Windows.Media.Imaging.BitmapImage
        $bild.BeginInit()
        $bild.StreamSource = $ms
        $bild.DecodePixelWidth = 64
        $bild.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
        $bild.EndInit()
        $bild.Freeze()
        if ($bild.PixelWidth -lt 16) { return $null }
        return $bild
    } catch {
        return $null
    }
}

function Logos-Laden($U, $S) {
    # Die Pakete im Hintergrund suchen, die Bilder danach setzen.
    if ($global:OMCAD_F.OhneLogos -or $S.LogoSuche) { return }
    $rest = '$aus = @{}; foreach ($k in @(' + ((@($APP_PAKETE.Keys) | ForEach-Object { "'" + $_ + "'" }) -join ",") + ')) { $aus[$k] = $null }; '
    foreach ($k in $APP_PAKETE.Keys) { $rest += '$o = App-Paket-Ort ''' + $APP_PAKETE[$k] + '''; if ($o) { $aus[''' + $k + '''] = Manifest-Logo $o }; ' }
    $rest += '$aus'
    $S.LogoSuche = Hintergrund-Starten (Hintergrund-Skript @("App-Paket-Ort", "Manifest-Logo") $rest)
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds(100)
    $t.Add_Tick({ param($sender, $e)
        $F = $global:OMCAD_F
        $l = $F.S.LogoSuche
        if (-not $l) { $sender.Stop(); return }
        if (-not $l.H.IsCompleted) { return }
        $sender.Stop()
        $F.S.LogoSuche = $null
        Logos-Setzen $F.U $F.S (Hintergrund-Ergebnis $l) })
    $t.Start()
}

function Logos-Setzen($U, $S, $pakete) {
    # Paket-Symbole (Pfade aus Logos-Laden) und die der exe-Dateien setzen;
    # was fehlt, bleibt beim Strich-Symbol (Tag $null). -> was gesetzt ist.
    if ($global:OMCAD_F.OhneLogos) { return @() }
    $quelle = @{}
    if ($pakete) { foreach ($k in @($pakete.Keys)) { $quelle[$k] = $pakete[$k] } }
    if (-not $quelle.claude_desktop -and $env:LOCALAPPDATA) {
        $exe = Join-Path $env:LOCALAPPDATA "AnthropicClaude\claude.exe"
        if (Test-Path -LiteralPath $exe -PathType Leaf) { $quelle.claude_desktop = $exe }
    }
    foreach ($k in @("claude", "codex")) {
        $p = "$($S.CliDa[$k])"
        if ($p -match '(?i)\.exe$') { $quelle["cli_" + $k] = $p }
    }
    $ziele = @{ claude_desktop = @("ki_logo_claude_desktop", "keine_claude"); codex = @("ki_logo_codex", "keine_codex")
                cli_claude = @("ki_logo_claude_code", "chat_logo_claude"); cli_codex = @("chat_logo_codex") }
    $gesetzt = @()
    foreach ($k in $ziele.Keys) {
        $bild = Logo-Bild "$($quelle[$k])"
        if (-not $bild) { continue }
        foreach ($n in $ziele[$k]) { (El $U $n).Tag = $bild }
        $gesetzt += $k
    }
    $S.Logos = $gesetzt
    return $gesetzt
}

function Version-Satz($U, $S) {
    # Der Satz zur Cadwork-Version in der Sprache des Fensters (der von
    # Version-Pruefen ist deutsch, fuer das Textfenster).
    # Mehr als ein Profil angehakt (seit 2026-10-10): ein Satz fuer alle,
    # die nicht passen, mit dem Weg zurueck zum Abwaehlen.
    $vs = @($S.Versionen | Where-Object { $_ })
    if ($vs.Count -gt 1) {
        $namen = @()
        foreach ($v in $vs) {
            if ($v.Passt) { continue }
            if ($null -eq $v.Nummer) { $namen += (Text $U "t_profil_unbekannt") }
            else { $namen += [string]::Format((Text $U "t_profil_name"), $v.Nummer) }
        }
        return [string]::Format((Text $U "t_version_mehrere"), $CADWORK_ERLAUBT_AB, (Namen-Liste $U $namen))
    }
    $nr = $null
    if ($S.Version) { $nr = $S.Version.Nummer }
    # {0} ist das erste erlaubte Jahr ($CADWORK_ERLAUBT_AB, "... oder
    # neuer"), nie eine zweite Jahreszahl hier.
    if ($null -eq $nr) { return [string]::Format((Text $U "t_version_unbekannt"), $CADWORK_ERLAUBT_AB) }
    $name = Profil-Name (@($S.Kandidaten)[$S.VersionIndex]).Pfad
    return [string]::Format((Text $U "t_version_text"), $CADWORK_ERLAUBT_AB, $nr, $name)
}

function Version-Fuellen($U, $S) {
    (El $U "version_text").Text = (Version-Satz $U $S)
}

function Python-Fuellen($U, $S) {
    if ($S.PythonWeg -eq "winget") { (El $U "python_weg").Text = (Text $U "t_python_winget") }
    else { (El $U "python_weg").Text = (Text $U "t_python_org") }
}

function Bereit-Zeilen($U, $S) {
    # Was eingerichtet wird, in Worten (fuer die Seite "Bereit").
    # Je angehaktes Cadwork eine Zeile (seit 2026-10-10).
    $z = @()
    $vs = @($S.Versionen | Where-Object { $_ })
    if ($vs.Count -eq 0) { $vs = @($S.Version) }
    foreach ($v in $vs) {
        $nr = "?"
        if ($v -and $null -ne $v.Nummer) { $nr = $v.Nummer }
        if ($v -and -not $v.Passt) { $z += [string]::Format((Text $U "t_bereit_plugin_trotzdem"), $nr) }
        elseif ($v -and $v.Art -eq "ungetestet") { $z += [string]::Format((Text $U "t_bereit_plugin_ungetestet"), $nr) }
        else { $z += [string]::Format((Text $U "t_bereit_plugin"), $nr) }
    }
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
    # Das alte Plugin: Haken (vorausgewaehlt), nur wenn eines da ist.
    $alte = @($S.Alte | Where-Object { $_ })
    Sichtbar (El $U "bereit_alt") ($alte.Count -gt 0)
    if ($alte.Count -gt 0) {
        (El $U "bereit_alt_name").Text = [string]::Format((Text $U "t_bereit_alt_name"), (Namen-Liste $U @($alte | ForEach-Object { $_.Name })))
        (El $U "bereit_alt_haken").IsChecked = [bool]$S.AltWeg
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

function Fertig-Jahre($S) {
    # In welche Cadwork das Plugin kam (seit 2026-10-10): aus dem Ergebnis
    # von install.ps1 (profile, Status ok/version), sonst die angehakten.
    # -> Liste der Jahre (ohne unbekannte).
    $aus = @()
    if ($S.Ergebnis -and $null -ne $S.Ergebnis.profile) {
        foreach ($e in @($S.Ergebnis.profile)) {
            if ($e -and ($e.status -eq "ok" -or $e.status -eq "version") -and $null -ne $e.nummer) { $aus += [int]$e.nummer }
        }
    } else {
        foreach ($i in (Profil-Wahl $S)) {
            $k = @($S.Kandidaten)[$i]
            if ($k -and $k.Nummer -ge 0) { $aus += [int]$k.Nummer }
        }
    }
    return , @($aus | Select-Object -Unique)
}

function Fertig-Fuellen($U, $S) {
    $k = KI-Ergebnis $S.Ergebnis
    $namen = @($k.Verbunden | ForEach-Object { KI-Anzeige $U $_ })
    $text = ""
    $jahre = Fertig-Jahre $S
    if ($jahre.Count -gt 0) { $text = [string]::Format((Text $U "t_fertig_cadwork"), (Namen-Liste $U @($jahre | ForEach-Object { [string]$_ }))) }
    if ($S.Wo -ne "chat") {
        if ($namen.Count -gt 0) { $text = ($text + " " + [string]::Format((Text $U "t_fertig_mit"), (Namen-Liste $U $namen))).Trim() }
        else { $text = ($text + " " + (Text $U "t_fertig_ohne")).Trim() }
        if (@($k.Fehler).Count -gt 0) {
            $text += " " + [string]::Format((Text $U "t_fertig_teilweise"), (Namen-Liste $U @($k.Fehler | ForEach-Object { KI-Anzeige $U $_ })))
        }
    }
    if ($S.Wo -ne "app" -and $S.ChatKi -ne "spaeter") {
        $text = ($text + " " + [string]::Format((Text $U "t_fertig_chat_ki"), (Chat-Name $U $S.ChatKi))).Trim()
    }
    if ($S.Ergebnis -and [int]$S.Ergebnis.altWeg -gt 0) {
        $text = ($text + " " + (Text $U "t_fertig_alt")).Trim()
    }
    (El $U "fertig_ki").Text = $text
    $schritte = Fertig-Schritte $S
    for ($i = 1; $i -le 4; $i++) {
        $da = $i -le $schritte.Count
        Sichtbar (El $U ("fertig_schritt" + $i)) $da
        if ($da) { (El $U ("fertig_text" + $i)).Text = (Text $U $schritte[$i - 1]) }
    }
    (El $U "fertig_protokoll").Text = $S.Log.ToString()
    # Nur die KI-App gewaehlt: der Chat in Cadwork laesst sich dazunehmen.
    Sichtbar (El $U "fertig_chat_dazu") ($S.Wo -eq "app")
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
    # Rueckmeldung 2026-10-10: nach dem Aufklappen stand weiter "Details
    # anzeigen".
    if ($an) { (El $U $knopf).Content = (Text $U "t_details_ausblenden") }
    else { (El $U $knopf).Content = (Text $U "t_details_anzeigen") }
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
    Protokoll-Zeile $S ("Antworten im Fenster: Profil " + (@((Wahl-Aus-Zustand $S "").Profile) -join "; ") + "; wo " + $S.Wo + "; KI-Apps " + (@((Wahl-Aus-Zustand $S "").Ki) -join ",") + "; Chat-KI " + (Wahl-Aus-Zustand $S "").ChatKi + "; Python mitinstallieren " + ([bool]($S.PythonFehlt -and $S.PythonJa)) + "; trotzdem " + [bool]$S.Trotzdem)
    Protokoll-Zeile $S ("Sprache des Fensters: " + $U.Sprache + " (Windows: " + [Globalization.CultureInfo]::CurrentUICulture.Name + "); alte Version: " + ((@($S.Alte | Where-Object { $_ }) | ForEach-Object { $_.Pfad }) -join ", ") + "; beiseitelegen " + [bool](Wahl-Aus-Zustand $S "").Alt)
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
    (El $U "willkommen_kopieren").Add_Click({ $F = $global:OMCAD_F; KI-Hilfe-Kopieren $F.U $F.S })
    (El $U "willkommen_link").Add_Click({ $F = $global:OMCAD_F; KI-Hilfe-Kopieren $F.U $F.S })
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
        (El $U $n).Add_Click({ $F = $global:OMCAD_F; Suche-Starten $F.U $F.S })
    }
    # "Zurueck" auf jeder Seite mit Fragen (seit 2026-10-10, Rueckmeldung).
    foreach ($n in @("wo_zurueck", "ki_zurueck", "keine_zurueck", "chat_zurueck", "profil_zurueck", "version_zurueck", "python_zurueck", "bereit_zurueck")) {
        (El $U $n).Add_Click({ $F = $global:OMCAD_F; Zurueck $F.U $F.S })
    }
    (El $U "fertig_chat_dazu").Add_Click({ $F = $global:OMCAD_F; Chat-Dazu $F.U $F.S })
    (El $U "ki_holen_claude_code").Add_Click({ Url-Oeffnen $URL_CLAUDE_CODE })
    (El $U "keine_claude_code").Add_Click({ Url-Oeffnen $URL_CLAUDE_CODE })
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
    (El $U "version_schliessen").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "python_ja").Add_Click({ $F = $global:OMCAD_F; $F.S.PythonJa = $true; Weiter $F.U $F.S "python" })
    (El $U "python_nein").Add_Click({ $global:OMCAD_F.U.W.Close() })
    (El $U "bereit_installieren").Add_Click({ $F = $global:OMCAD_F; Installieren $F.U $F.S; Takt-Starten $F.U $F.S })
    (El $U "bereit_alt_haken").Add_Click({ $F = $global:OMCAD_F; $F.S.AltWeg = ((El $F.U "bereit_alt_haken").IsChecked -eq $true) })
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

function KI-Hilfe-Kopieren($U, $S) {
    # "diesen Text" bzw. das Kopier-Symbol: den Text fuer die KI-App in die
    # Ablage; kurz ein Haken und "Kopiert." statt des Symbols.
    Ablage-Setzen (Text $U "t_ki_hilfe")
    (El $U "willkommen_kopiert").Text = (Text $U "t_kopiert")
    Sichtbar (El $U "willkommen_symbol_kopieren") $false
    Sichtbar (El $U "willkommen_symbol_haken") $true
    if ($S.KopiertZeitgeber) { $S.KopiertZeitgeber.Stop() }
    $t = New-Object System.Windows.Threading.DispatcherTimer
    $t.Interval = [TimeSpan]::FromMilliseconds($KOPIERT_MS)
    $t.Add_Tick({ param($sender, $e)
        $sender.Stop()
        $F = $global:OMCAD_F
        (El $F.U "willkommen_kopiert").Text = ""
        Sichtbar (El $F.U "willkommen_symbol_kopieren") $true
        Sichtbar (El $F.U "willkommen_symbol_haken") $false })
    $S.KopiertZeitgeber = $t
    $t.Start()
}

function Klick($U, [string]$name) {
    # Fuer die Gates: ein Klick wie mit der Maus (Click-Ereignis bzw. Haken).
    $e = El $U $name
    if ($e -is [System.Windows.Documents.Hyperlink]) {
        if (-not $e.IsEnabled) { throw "'$name' ist gesperrt" }
        $e.RaiseEvent((New-Object System.Windows.RoutedEventArgs ([System.Windows.Documents.Hyperlink]::ClickEvent)))
        return
    }
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

#: Ab wie viel fehlendem Platz (DIP, 1/96 Zoll) ein Teil als abgeschnitten
#: gilt (Abgeschnitten).
$ABSCHNITT_TOLERANZ = 1.5

function Text-Breite($tb) {
    # Wie breit der Text einer Zeile ohne Grenze waere (fuer TextTrimming).
    $tf = New-Object System.Windows.Media.Typeface($tb.FontFamily, $tb.FontStyle, $tb.FontWeight, $tb.FontStretch)
    $ft = New-Object System.Windows.Media.FormattedText($tb.Text, [Globalization.CultureInfo]::InvariantCulture, $tb.FlowDirection, $tf, $tb.FontSize, [System.Windows.Media.Brushes]::Black, 2.0)
    return $ft.WidthIncludingTrailingWhitespace
}

function Abgeschnitten($r) {
    # Was auf der gerade gezeigten Seite nicht ganz zu sehen ist (seit
    # 2026-10-10, vier Sprachen). WPF ordnet ein Teil, das mehr Platz will,
    # als es bekommt, in seiner GEWUENSCHTEN Groesse an (ActualWidth/
    # ActualHeight) und schneidet es auf den VERFUEGBAREN Platz zu
    # (LayoutInformation.GetLayoutClip) - verglichen wird also beides, ohne
    # eigene Liste der Teile. Weniger als $ABSCHNITT_TOLERANZ zaehlt nicht
    # (Rundung auf ganze Bildpunkte bei 125 % Skalierung: aus 22 wird 22,4).
    # Dazu gekuerzte Zeilen (TextTrimming, "..."). Ausgenommen: was
    # absichtlich abschneidet (ClipToBounds, der Rollbereich einer Liste).
    # -> Liste von @{ teil; grund; text; gewuenscht; verfuegbar }
    $aus = New-Object System.Collections.ArrayList
    $stapel = New-Object System.Collections.Stack
    $stapel.Push($r)
    while ($stapel.Count -gt 0) {
        $x = $stapel.Pop()
        if ($x -is [System.Windows.UIElement] -and $x.Visibility -ne [System.Windows.Visibility]::Visible) { continue }
        if ($x -is [System.Windows.Controls.ScrollContentPresenter]) { continue }
        for ($i = 0; $i -lt [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($x); $i++) {
            $stapel.Push([System.Windows.Media.VisualTreeHelper]::GetChild($x, $i))
        }
        if (-not ($x -is [System.Windows.FrameworkElement])) { continue }
        $grund = $null
        $gewuenscht = @([Math]::Round($x.ActualWidth, 1), [Math]::Round($x.ActualHeight, 1))
        $verfuegbar = $gewuenscht
        $clip = $null
        if (-not $x.ClipToBounds) { $clip = [System.Windows.Controls.Primitives.LayoutInformation]::GetLayoutClip($x) }
        if ($null -ne $clip) {
            $c = $clip.Bounds
            $vb = [Math]::Max(0, [Math]::Min($c.Right, $x.ActualWidth) - [Math]::Max($c.Left, 0))
            $vh = [Math]::Max(0, [Math]::Min($c.Bottom, $x.ActualHeight) - [Math]::Max($c.Top, 0))
            if ($x.ActualWidth - $vb -ge $ABSCHNITT_TOLERANZ -or $x.ActualHeight - $vh -ge $ABSCHNITT_TOLERANZ) {
                $grund = "Platz"
                $verfuegbar = @([Math]::Round($vb, 1), [Math]::Round($vh, 1))
            }
        }
        if ($x -is [System.Windows.Controls.TextBlock] -and $x.Text -and $x.TextTrimming -ne [System.Windows.TextTrimming]::None) {
            $b = Text-Breite $x
            if ($b -ge $x.ActualWidth + $ABSCHNITT_TOLERANZ) {
                $grund = "gekuerzt"
                $gewuenscht = @([Math]::Round($b, 1), [Math]::Round($x.ActualHeight, 1))
            }
        }
        if (-not $grund) { continue }
        $text = ""
        if ($x -is [System.Windows.Controls.TextBlock]) { $text = $x.Text }
        else {
            # der erste Text darin, damit man das Teil findet
            $s2 = New-Object System.Collections.Stack
            $s2.Push($x)
            while ($s2.Count -gt 0 -and -not $text) {
                $y = $s2.Pop()
                if ($y -is [System.Windows.Controls.TextBlock] -and $y.Text) { $text = $y.Text }
                for ($i = 0; $i -lt [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($y); $i++) {
                    $s2.Push([System.Windows.Media.VisualTreeHelper]::GetChild($y, $i))
                }
            }
        }
        $teil = $x.Name
        if (-not $teil) { $teil = $x.GetType().Name }
        [void]$aus.Add(@{ teil = $teil; grund = $grund; text = $text; gewuenscht = $gewuenscht; verfuegbar = $verfuegbar })
    }
    return , @($aus)
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
        if ($x -is [System.Windows.Controls.TextBlock]) {
            # Mit Inlines (Satz mit Verweis) ist .Text leer: dann der ganze Satz.
            $tt = $x.Text
            if (-not $tt -and $x.Inlines.Count -gt 0) { $tt = (New-Object System.Windows.Documents.TextRange($x.ContentStart, $x.ContentEnd)).Text }
            if ($tt) { [void]$texte.Add($tt) }
        }
        if ($x -is [System.Windows.Controls.TextBox] -and $x.Text) { [void]$texte.Add($x.Text) }
    }
    return @{ ziele = $ziele; texte = @($texte); abgeschnitten = (Abgeschnitten $r) }
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
    $S.ProfilWahl = @(0)
    $S.Version = [pscustomobject]@{ Passt = $true; Nummer = 2026; Art = "getestet"; Text = "Cadwork 2026 im Profil userprofil_2026" }
    $S.Versionen = @($S.Version)
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
#: Weitere Lagen, die sonst kein Bild haetten (fuer die Messung, ob alles
#: hineinpasst, seit 2026-10-10): Name -> Seite. "bereit_alt": das alte
#: Plugin gefunden, "fertig_alt": es ist beiseitegelegt, "fehler_alt": das
#: ging nicht, "fertig_chat": der Chat in Cadwork mit allen vier Schritten,
#: "bereit_ungetestet": eine erlaubte, nicht getestete Cadwork-Version;
#: "*_zwei" (seit 2026-10-10): zwei Cadwork angehakt (2026 und 2025, auf
#: der Warnseite 2026 und das Jahr vor $CADWORK_ERLAUBT_AB).
$WEITERE_BILDER = [ordered]@{
    bereit_alt  = "bereit"
    fertig_alt  = "fertig"
    fehler_alt  = "fehler"
    fertig_chat = "fertig"
    bereit_ungetestet = "bereit"
    bereit_zwei  = "bereit"
    fertig_zwei  = "fertig"
    version_zwei = "version"
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
    foreach ($name in (@($SEITEN) + @($LAEUFT_BILDER.Keys) + @($WEITERE_BILDER.Keys))) {
        $seite = $name
        if ($LAEUFT_BILDER.Contains($name)) { $seite = "laeuft" }
        if ($WEITERE_BILDER.Contains($name)) { $seite = $WEITERE_BILDER[$name] }
        $S = Demo-Zustand
        $global:OMCAD_F.S = $S
        if ($name -like "*_alt") {
            $S.Alte = @([pscustomobject]@{ Name = "LignoAI Connect"; Pfad = "C:\Users\Public\Documents\cadwork\userprofil_2026\3d\API.x64\LignoAI Connect" })
        }
        if ($name -eq "fertig_chat") { $S.Wo = "beides"; $S.ChatKi = "spaeter" }
        if ($name -eq "bereit_ungetestet") {
            # Das erste erlaubte Jahr, das NICHT getestet ist (seit 2025
            # getestet ist: 2027) - nie eine feste Jahreszahl hier.
            $j = $CADWORK_ERLAUBT_AB
            while (@($CADWORK_GETESTET) -contains $j) { $j++ }
            $S.Version = [pscustomobject]@{ Passt = $true; Nummer = $j; Art = "ungetestet"; Text = "" }
            $S.Versionen = @($S.Version)
        }
        # Die Seite "Welches Cadwork?" und die Lagen mit zwei Haken: 2026 und
        # 2025 angehakt (wie die Vorauswahl, wenn beide installiert sind).
        if ($name -eq "profil" -or $name -eq "bereit_zwei" -or $name -eq "fertig_zwei") {
            $S.ProfilWahl = @(0, 1)
            # 2025 wie Version-Pruefen es sieht (getestet oder nicht, aus
            # $CADWORK_GETESTET).
            $S.Versionen = @($S.Version, (Version-Pruefen (@($S.Kandidaten)[1].Pfad) $S.Installiert "C:\Program Files\cadwork.dir"))
        }
        switch ($seite) {
            "version" {
                # Die Warnung gilt einer NICHT erlaubten Version: das Jahr
                # vor $CADWORK_ERLAUBT_AB (seit 2026-10-10: 2024).
                $alt = $CADWORK_ERLAUBT_AB - 1
                $S.Kandidaten = @(@($S.Kandidaten)[0], [pscustomobject]@{ Name = "userprofil_$alt"; Pfad = "C:\Users\Public\Documents\cadwork\userprofil_$alt\3d\API.x64"; Nummer = $alt; Installiert = $true })
                $S.ProfilIndex = 1
                $S.VersionIndex = 1
                $S.ProfilWahl = @(1)
                $S.Version = [pscustomobject]@{ Passt = $false; Nummer = $alt; Text = "Dieses Paket braucht Cadwork 3D $CADWORK_ERLAUBT_AB oder neuer. Gefunden: Cadwork $alt im Profil userprofil_$alt." }
                $S.Versionen = @($S.Version)
                if ($name -eq "version_zwei") {
                    $S.ProfilWahl = @(0, 1)
                    $S.ProfilIndex = 0
                    $S.Versionen = @([pscustomobject]@{ Passt = $true; Nummer = 2026; Art = "getestet"; Text = "" }, $S.Version)
                }
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
            $S.Ergebnis = [pscustomobject]@{ fertig = $true; altWeg = $(if ($name -eq "fertig_alt") { 1 } else { 0 }); kiListe = @([pscustomobject]@{ name = "Claude Desktop"; status = "eingetragen" }, [pscustomobject]@{ name = "Codex"; status = "eingetragen" }) }
            Fertig-Fuellen $U $S
        }
        if ($seite -eq "fehler") {
            if ($name -eq "fehler_alt") { Fehler-Fuellen $U $S "t_fehler_alt" } else { Fehler-Fuellen $U $S "t_fehler_server" }
        }
        $datei = Join-Path $ordner ("fenster-" + $name + ".png")
        $info = Seite-Bild $U $datei
        $aus[$name] = @{ datei = (Split-Path -Leaf $datei); breite = $U.Wurzel.Width; hoehe = $U.Wurzel.Height; ziele = $info.ziele; texte = $info.texte; abgeschnitten = $info.abgeschnitten; sprache = $U.Sprache; titel = $U.W.Title }
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
