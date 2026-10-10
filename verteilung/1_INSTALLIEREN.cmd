@echo off
rem Open MCP CAD - Installation. Doppelklick genuegt.
rem
rem Seit 2026-10-09: OHNE Schalter oeffnet sich das Einrichtungsfenster
rem (Programmdateien\install_fenster.ps1; Rueckmeldung: das schwarze
rem Fenster schreckte ab). Das Fenster startet danach install.ps1 selbst.
rem Mit Schaltern (etwa -Profil, -OhneServer, -Konsole) laeuft wie bisher
rem das Textfenster (install.ps1). Laesst sich das Einrichtungsfenster
rem nicht oeffnen (Rueckgabe weder 0 noch 3), geht es im Textfenster
rem weiter - nie stilles Nichts.
rem
rem Seit 2026-10-10 spricht das Einrichtungsfenster vier Sprachen (die der
rem Windows-Anzeige: de, fr, it, sonst en). "-Sprache fr" als EINZIGER
rem Schalter waehlt eine davon und oeffnet trotzdem das Fenster; jeder andere
rem Wert, jeder weitere Schalter: Textfenster. Das Textfenster bleibt deutsch
rem (install.ps1 nimmt -Sprache an und uebergeht es).
rem
rem Beide starten ohne Aenderung der PowerShell-Ausfuehrungsrichtlinie des
rem Systems (nur fuer diesen Aufruf).
rem
rem Gegenpruefung 2026-09-29: ein Doppelklick IN der ZIP-Datei (Windows
rem entpackt dann nur diese eine Datei) und ein PowerShell, das Skripte
rem sperrt (Firmenrichtlinie), schlossen das Fenster sofort. Rueckmeldung
rem 2026-10-10: die Meldung danach ("... Druecken Sie eine beliebige Taste")
rem wirkte komisch, danach geschah "wie nichts". Seit 2026-10-10 zeigt
rem :hilfe in beiden Faellen ein freundliches Fenster in der Sprache von
rem Windows; in der ZIP sucht es die ZIP-Datei, entpackt sie auf Wunsch
rem neben sich und startet den Doppelklick von dort. Den Code dafuer liest
rem PowerShell (-Command, also auch bei gesperrten Skripten) aus DIESER
rem Datei, ab der Marke am Ende - neben dieser Datei liegt dann ja nichts.
rem Nur wenn das nicht geht (kein PowerShell), der Text wie frueher und
rem "pause". install.ps1 meldet "nicht vollstaendig" mit 3 und hat dann
rem selbst schon gewartet; jede andere Rueckgabe ausser 0 kommt von
rem PowerShell.
set "OMCAD_SELBST=%~f0"
set "OMCAD_PAUSE=1"
for %%a in (%*) do if /i "%%~a"=="-OhnePause" set "OMCAD_PAUSE="
if not exist "%~dp0Programmdateien\install.ps1" goto nicht_entpackt
set "OMCAD_SPRACHE="
if "%~1"=="" goto fenster
if /i not "%~1"=="-Sprache" goto konsole
if not "%~3"=="" goto konsole
for %%s in (de fr it en) do if /i "%~2"=="%%s" set "OMCAD_SPRACHE=%%s"
if not defined OMCAD_SPRACHE goto konsole
:fenster
if not exist "%~dp0Programmdateien\install_fenster.ps1" goto konsole
title Open MCP CAD
echo Das Einrichtungsfenster von Open MCP CAD oeffnet sich ...
if defined OMCAD_SPRACHE (
  powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Programmdateien\install_fenster.ps1" -Sprache %OMCAD_SPRACHE%
) else (
  powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Programmdateien\install_fenster.ps1"
)
set "OMCAD_RC=%ERRORLEVEL%"
if "%OMCAD_RC%"=="0" exit /b 0
if "%OMCAD_RC%"=="3" exit /b 3
echo.
echo Das Einrichtungsfenster liess sich nicht oeffnen (Rueckgabe %OMCAD_RC%).
echo Die Einrichtung geht hier im Textfenster weiter. Fragen mit Enter beantworten.
echo.
:konsole
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Programmdateien\install.ps1" %*
set "OMCAD_RC=%ERRORLEVEL%"
if "%OMCAD_RC%"=="0" exit /b 0
if "%OMCAD_RC%"=="3" exit /b 3
if not defined OMCAD_PAUSE goto konsole_text
call :hilfe start %OMCAD_RC%
if not errorlevel 9 exit /b %OMCAD_RC%
:konsole_text
echo.
echo Der Installer konnte nicht starten - Rueckgabe %OMCAD_RC%, der Grund steht oben.
echo Sperrt eine Firmenrichtlinie PowerShell-Skripte, bitte die IT fragen.
if defined OMCAD_PAUSE pause
exit /b %OMCAD_RC%

:nicht_entpackt
if not defined OMCAD_PAUSE goto entpacken_text
call :hilfe gepackt
set "OMCAD_RC=%ERRORLEVEL%"
if not "%OMCAD_RC%"=="9" exit /b %OMCAD_RC%
:entpacken_text
echo.
echo Neben dieser Datei fehlt der Ordner Programmdateien.
echo Bitte die ZIP-Datei zuerst entpacken: mit der rechten Maustaste auf die
echo ZIP-Datei klicken, "Alle extrahieren ..." waehlen und danach im
echo entpackten Ordner 1_INSTALLIEREN.cmd doppelklicken.
if defined OMCAD_PAUSE pause
exit /b 2

:hilfe
rem Das freundliche Fenster (Code am Ende dieser Datei). Rueckgabe 9: ging
rem nicht, dann der Text oben.
set "OMCAD_ART=%~1"
set "OMCAD_WERT=%~2"
powershell -NoProfile -STA -ExecutionPolicy Bypass -Command "$global:OMCAD_RC = 9; try { $t = [IO.File]::ReadAllText($env:OMCAD_SELBST); $i = $t.IndexOf('#OMCAD' + '-HILFE'); if ($i -ge 0) { . ([ScriptBlock]::Create($t.Substring($i))) } } catch { $global:OMCAD_RC = 9 }; exit $global:OMCAD_RC" 2>nul
if errorlevel 9009 exit /b 9
exit /b %ERRORLEVEL%

rem Ab hier PowerShell, nie von cmd.exe ausgefuehrt (exit /b oben).
#OMCAD-HILFE
# --- Freundliche Fenster fuer den Doppelklick (seit 2026-10-10) -------------
# Nur PowerShell, das 1_INSTALLIEREN.cmd mit -Command aus SICH SELBST liest
# (ab der Zeile oben): gebraucht wird es gerade dann, wenn Programmdateien
# fehlt. Rueckmeldung 2026-10-10: ein Doppelklick IN der ZIP-Datei zeigte ein
# schwarzes Fenster "... Druecken Sie eine beliebige Taste" und danach nichts.
# Jetzt:
#   gepackt  Windows hat nur diese Datei ausgepackt (%TEMP%\Temp<n>_<zip>\...).
#            Gesucht wird die ZIP (Name aus dem Temp-Ordner, sonst die neueste
#            Open-MCP-CAD*.zip mit Programmdateien/install.ps1) in Downloads
#            (Known Folder), Desktop, Dokumente; Fenster "Entpacken und
#            starten" -> neben die ZIP in Open-MCP-CAD-<version> (vorhanden:
#            " (2)" usw., nie ueberschreiben), dann 1_INSTALLIEREN.cmd von
#            dort. Keine ZIP: Fenster mit den drei Schritten von Hand.
#   start    install.ps1 lief gar nicht (Firmenrichtlinie): Fenster statt
#            "Druecken Sie eine beliebige Taste".
# Rueckgabe ueber $global:OMCAD_RC: der des gestarteten Doppelklicks, 2 =
# nicht entpackt (Fenster gezeigt), 0 = Meldung gezeigt, 9 = ging nicht (die
# .cmd schreibt dann ihren Text wie frueher).
# Nur ASCII (die .cmd liest cmd.exe in der Codepage); Umlaute als \u in den
# Texten, [regex]::Unescape macht sie wieder daraus.
# Fuer die Gates (nie ein sichtbares Fenster): OMCAD_HILFE_ANTWORT
# (starten|abbrechen|ok|kaputt) baut das Fenster, zeigt es aber nicht;
# OMCAD_HILFE_SPUR (Datei, je Fenster eine JSON-Zeile); OMCAD_ZIP_ORTE
# (Suchorte, ;-getrennt, statt Downloads/Desktop/Dokumente);
# OMCAD_HILFE_SPRACHE (statt der Anzeigesprache).
$ErrorActionPreference = "Stop"

$HILFE_TEXTE = @{
    de = @{
        gepackt_titel = "Die Datei ist noch gepackt"
        gepackt_satz = "Soll ich sie f\u00fcr dich entpacken und die Einrichtung starten?"
        gepackt_zip = "Gefunden: {0}"
        gepackt_ziel = "Entpackt wird nach: {0}"
        starten = "Entpacken und starten"
        abbrechen = "Abbrechen"
        anleitung_titel = "Bitte zuerst entpacken"
        anleitung_satz = "Die Datei ist noch gepackt, so fehlen ihr die anderen Dateien. So geht es:"
        anleitung_fehler = "Das Entpacken hat nicht geklappt ({0}). So geht es von Hand:"
        schritt_1 = "Dieses Fenster schliessen."
        schritt_2 = "Mit der rechten Maustaste auf die ZIP-Datei klicken und \u00abAlle extrahieren \u2026\u00bb w\u00e4hlen."
        schritt_3 = "Im neuen Ordner 1_INSTALLIEREN.cmd doppelklicken."
        ok = "OK"
        start_titel = "Die Einrichtung konnte nicht starten"
        start_satz = "Windows hat das Einrichtungsprogramm nicht ausgef\u00fchrt (R\u00fcckgabe {0}). Oft sperrt eine Firmenrichtlinie solche Programme. Bitte frag deine IT und zeig ihr diese Meldung."
    }
    fr = @{
        gepackt_titel = "Le fichier est encore compress\u00e9"
        gepackt_satz = "Dois-je l'extraire pour toi et lancer l'installation ?"
        gepackt_zip = "Trouv\u00e9 : {0}"
        gepackt_ziel = "Extrait vers : {0}"
        starten = "Extraire et lancer"
        abbrechen = "Annuler"
        anleitung_titel = "Extrais d'abord le fichier"
        anleitung_satz = "Le fichier est encore compress\u00e9, il lui manque donc les autres fichiers. Voici comment faire :"
        anleitung_fehler = "L'extraction n'a pas march\u00e9 ({0}). Voici comment faire \u00e0 la main :"
        schritt_1 = "Fermer cette fen\u00eatre."
        schritt_2 = "Clic droit sur le fichier ZIP, puis \u00abExtraire tout \u2026\u00bb."
        schritt_3 = "Dans le nouveau dossier, double-cliquer sur 1_INSTALLIEREN.cmd."
        ok = "OK"
        start_titel = "L'installation n'a pas pu d\u00e9marrer"
        start_satz = "Windows n'a pas ex\u00e9cut\u00e9 le programme d'installation (code {0}). Souvent, une r\u00e8gle de l'entreprise bloque ces programmes. Demande \u00e0 ton service informatique et montre-lui ce message."
    }
    it = @{
        gepackt_titel = "Il file \u00e8 ancora compresso"
        gepackt_satz = "Devo estrarlo per te e avviare la configurazione?"
        gepackt_zip = "Trovato: {0}"
        gepackt_ziel = "Viene estratto in: {0}"
        starten = "Estrai e avvia"
        abbrechen = "Annulla"
        anleitung_titel = "Prima estrai il file"
        anleitung_satz = "Il file \u00e8 ancora compresso, quindi gli mancano gli altri file. Ecco come fare:"
        anleitung_fehler = "L'estrazione non \u00e8 riuscita ({0}). Ecco come fare a mano:"
        schritt_1 = "Chiudere questa finestra."
        schritt_2 = "Clic destro sul file ZIP e scegliere \u00abEstrai tutto \u2026\u00bb."
        schritt_3 = "Nella nuova cartella fare doppio clic su 1_INSTALLIEREN.cmd."
        ok = "OK"
        start_titel = "La configurazione non \u00e8 potuta partire"
        start_satz = "Windows non ha eseguito il programma di configurazione (codice {0}). Spesso una regola aziendale blocca questi programmi. Chiedi al tuo reparto IT e mostragli questo messaggio."
    }
    en = @{
        gepackt_titel = "The file is still zipped"
        gepackt_satz = "Shall I unzip it for you and start the setup?"
        gepackt_zip = "Found: {0}"
        gepackt_ziel = "Unzipped to: {0}"
        starten = "Unzip and start"
        abbrechen = "Cancel"
        anleitung_titel = "Please unzip first"
        anleitung_satz = "The file is still zipped, so the other files are missing. Here is how:"
        anleitung_fehler = "Unzipping did not work ({0}). Here is how to do it by hand:"
        schritt_1 = "Close this window."
        schritt_2 = "Right-click the ZIP file and choose \u00abExtract All \u2026\u00bb."
        schritt_3 = "In the new folder, double-click 1_INSTALLIEREN.cmd."
        ok = "OK"
        start_titel = "The setup could not start"
        start_satz = "Windows did not run the setup program (code {0}). Often a company policy blocks such programs. Please ask your IT and show them this message."
    }
}

function Hilfe-Sprache {
    # Wie Sprache-Waehlen im Einrichtungsfenster (test_installer I33 prueft
    # beide an denselben Faellen).
    $k = "$env:OMCAD_HILFE_SPRACHE".Trim().ToLowerInvariant()
    if ($HILFE_TEXTE.ContainsKey($k)) { return $k }
    $k = ("$([Globalization.CultureInfo]::CurrentUICulture.Name)".ToLowerInvariant() -split '[-_]')[0]
    if ($k -eq "gsw") { $k = "de" }
    if (@("de", "fr", "it") -contains $k) { return $k }
    return "en"
}

function HT([string]$schluessel) {
    return [regex]::Unescape($HILFE_TEXTE[$script:HILFE_SP][$schluessel])
}

function Zip-Name-Aus-Pfad([string]$ordner) {
    # Der Name der ZIP aus dem Ordner, in den Windows die eine Datei gelegt
    # hat (%TEMP%\Temp1_Open-MCP-CAD-0.2.2.zip\Open-MCP-CAD-0.2.2\...).
    $o = $ordner
    while ($o) {
        $m = [regex]::Match((Split-Path -Leaf $o), '(?i)^Temp\d+_(.+\.zip)$')
        if ($m.Success) { return $m.Groups[1].Value }
        $eltern = Split-Path -Parent $o
        if ($eltern -eq $o) { break }
        $o = $eltern
    }
    return $null
}

function Downloads-Ordner {
    # Der Known Folder "Downloads" (auch umgezogen, etwa nach D:\), sonst
    # %USERPROFILE%\Downloads.
    try {
        $w = (Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" -Name "{374DE290-123F-4565-9164-39C4925E467B}" -ErrorAction Stop)."{374DE290-123F-4565-9164-39C4925E467B}"
        if ($w) { return [Environment]::ExpandEnvironmentVariables($w) }
    } catch { }
    return (Join-Path $env:USERPROFILE "Downloads")
}

function Such-Orte {
    if ($env:OMCAD_ZIP_ORTE) { return @($env:OMCAD_ZIP_ORTE.Split(";") | Where-Object { $_ }) }
    return @((Downloads-Ordner), [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments"))
}

function Zip-Gut([string]$pfad) {
    # Ist es das Paket? (Programmdateien/install.ps1 darin, mit oder ohne
    # Ordner obendrueber). Wirft nie.
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [IO.Compression.ZipFile]::OpenRead($pfad)
        try {
            foreach ($e in $z.Entries) { if ($e.FullName -match '(?i)(^|/)Programmdateien/install\.ps1$') { return $true } }
        } finally { $z.Dispose() }
    } catch { }
    return $false
}

function Zip-Suchen([string]$name) {
    # Zuerst die ZIP mit dem Namen aus dem Temp-Ordner (Reihenfolge der
    # Orte), sonst die neueste Open-MCP-CAD*.zip, die das Paket ist.
    $alle = @()
    foreach ($ort in (Such-Orte)) {
        $alle += @(Get-ChildItem -LiteralPath $ort -File -Filter "Open-MCP-CAD*.zip" -ErrorAction SilentlyContinue)
    }
    $gute = @($alle | Where-Object { Zip-Gut $_.FullName })
    if ($name) {
        foreach ($g in $gute) { if ($g.Name -eq $name) { return $g.FullName } }
    }
    $neu = $gute | Sort-Object -Property LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($neu) { return $neu.FullName }
    return $null
}

function Ziel-Ordner([string]$zip) {
    # Neben die ZIP, Open-MCP-CAD-<version>; nie einen vorhandenen
    # ueberschreiben: dann " (2)", " (3)" ...
    $m = [regex]::Match((Split-Path -Leaf $zip), '(?i)^(Open-MCP-CAD-\d+(\.\d+)*)')
    $basis = "Open-MCP-CAD"
    if ($m.Success) { $basis = $m.Groups[1].Value }
    $neben = Split-Path -Parent $zip
    $ziel = Join-Path $neben $basis
    $n = 2
    while (Test-Path -LiteralPath $ziel) {
        $ziel = Join-Path $neben ($basis + " (" + $n + ")")
        $n++
    }
    return $ziel
}

function Entpacken([string]$zip, [string]$ziel) {
    # Wie "Alle extrahieren", aber ohne den Ordner obendrueber (der Doppel-
    # klick liegt dann direkt im Ziel) und nur innerhalb des Ziels. Die
    # Herkunftsmarke der ZIP (Zone.Identifier) geht mit, wie beim Explorer.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zone = $null
    try { $zone = Get-Content -LiteralPath $zip -Stream Zone.Identifier -Raw -ErrorAction Stop } catch { }
    $z = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $eintraege = @($z.Entries)
        $oben = @($eintraege | ForEach-Object { ($_.FullName -split '/')[0] } | Select-Object -Unique)
        $weg = ""
        if ($oben.Count -eq 1 -and @($eintraege | Where-Object { $_.FullName -notlike ($oben[0] + "/*") }).Count -eq 0) { $weg = $oben[0] + "/" }
        New-Item -ItemType Directory -Path $ziel | Out-Null
        $voll = [IO.Path]::GetFullPath($ziel).TrimEnd("\") + "\"
        foreach ($e in $eintraege) {
            $rel = $e.FullName.Substring($weg.Length)
            if (-not $rel -or $rel.EndsWith("/")) { continue }
            $pfad = [IO.Path]::GetFullPath((Join-Path $ziel ($rel -replace '/', '\')))
            if (-not $pfad.StartsWith($voll, [StringComparison]::OrdinalIgnoreCase)) { throw ("unerlaubter Pfad in der ZIP: " + $e.FullName) }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $pfad) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $pfad, $false)
            if ($zone) { try { Set-Content -LiteralPath $pfad -Stream Zone.Identifier -Value $zone -ErrorAction Stop } catch { } }
        }
    } finally { $z.Dispose() }
}

function Konsole([int]$wie) {
    # 0 = verbergen, 5 = zeigen (das schwarze Fenster hinter dem Doppelklick).
    try {
        if (-not ("OmcadHilfe.K" -as [type])) {
            Add-Type -Namespace OmcadHilfe -Name K -MemberDefinition '[DllImport("kernel32.dll")] public static extern System.IntPtr GetConsoleWindow(); [DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);'
        }
        $h = [OmcadHilfe.K]::GetConsoleWindow()
        if ($h -ne [IntPtr]::Zero) { [void][OmcadHilfe.K]::ShowWindow($h, $wie) }
    } catch { }
}

$HILFE_XAML = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Open MCP CAD" Width="540" SizeToContent="Height" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen" Topmost="True" Background="#F7F6FB"
        FontFamily="Segoe UI" FontSize="14">
  <StackPanel Margin="32,28,32,24">
    <Border x:Name="zeichen" Width="44" Height="44" CornerRadius="22" Background="#EEEAFB" HorizontalAlignment="Left" Margin="0,0,0,14">
      <TextBlock x:Name="zeichen_text" Text="i" FontSize="22" FontWeight="Bold" Foreground="#5B3CC4" HorizontalAlignment="Center" VerticalAlignment="Center"/>
    </Border>
    <TextBlock x:Name="titel" FontSize="21" FontWeight="SemiBold" Foreground="#1D1D1F" TextWrapping="Wrap" Margin="0,0,0,8"/>
    <TextBlock x:Name="satz" FontSize="14" Foreground="#1D1D1F" TextWrapping="Wrap" LineHeight="21"/>
    <TextBlock x:Name="info" FontSize="12.5" Foreground="#6E6E73" TextWrapping="Wrap" Margin="0,10,0,0"/>
    <Border x:Name="schritte_karte" Background="White" BorderBrush="#E4E1EE" BorderThickness="1" CornerRadius="12" Padding="18,14" Margin="0,14,0,0" Visibility="Collapsed">
      <StackPanel x:Name="schritte"/>
    </Border>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,22,0,0">
      <Button x:Name="zweit" MinWidth="110" Height="38" Padding="16,0" Margin="0,0,10,0" Background="White" BorderBrush="#D6D2E3"/>
      <Button x:Name="haupt" MinWidth="132" Height="38" Padding="20,0" Background="#5B3CC4" Foreground="White" FontWeight="SemiBold" BorderThickness="0" IsDefault="True"/>
    </StackPanel>
  </StackPanel>
</Window>
'@

function Hilfe-Fenster([string]$art, $daten) {
    # Baut das Fenster; zeigt es (Konsole solange verborgen) und gibt die
    # Antwort zurueck: starten | abbrechen | ok. Im Gate (OMCAD_HILFE_ANTWORT)
    # nur gebaut, nicht gezeigt.
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
    $w = [Windows.Markup.XamlReader]::Parse($HILFE_XAML)
    $el = @{}
    foreach ($n in @("zeichen", "zeichen_text", "titel", "satz", "info", "schritte_karte", "schritte", "zweit", "haupt")) { $el[$n] = $w.FindName($n) }
    $schritte = @()
    switch ($art) {
        "angebot" {
            $el.titel.Text = HT "gepackt_titel"
            $el.satz.Text = HT "gepackt_satz"
            $el.info.Text = [string]::Format((HT "gepackt_zip"), (Split-Path -Leaf $daten.zip)) + "`n" + [string]::Format((HT "gepackt_ziel"), $daten.ziel)
            $el.haupt.Content = HT "starten"
            $el.zweit.Content = HT "abbrechen"
        }
        "anleitung" {
            $el.titel.Text = HT "anleitung_titel"
            if ($daten.fehler) { $el.satz.Text = [string]::Format((HT "anleitung_fehler"), $daten.fehler) }
            else { $el.satz.Text = HT "anleitung_satz" }
            $el.info.Visibility = "Collapsed"
            $schritte = @((HT "schritt_1"), (HT "schritt_2"), (HT "schritt_3"))
            $el.haupt.Content = HT "ok"
            $el.zweit.Visibility = "Collapsed"
        }
        default {
            $el.zeichen.Background = New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString("#FFF5E6"))
            $el.zeichen_text.Text = "!"
            $el.zeichen_text.Foreground = New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString("#C26A00"))
            $el.titel.Text = HT "start_titel"
            $el.satz.Text = [string]::Format((HT "start_satz"), $daten.rc)
            $el.info.Visibility = "Collapsed"
            $el.haupt.Content = HT "ok"
            $el.zweit.Visibility = "Collapsed"
        }
    }
    $i = 1
    foreach ($s in $schritte) {
        $g = New-Object Windows.Controls.Grid
        $g.Margin = New-Object Windows.Thickness 0, 4, 0, 4
        $c = New-Object Windows.Controls.ColumnDefinition
        $c.Width = New-Object Windows.GridLength 34
        [void]$g.ColumnDefinitions.Add($c)
        [void]$g.ColumnDefinitions.Add((New-Object Windows.Controls.ColumnDefinition))
        $b = New-Object Windows.Controls.Border
        $b.Width = 24; $b.Height = 24; $b.CornerRadius = 12; $b.VerticalAlignment = "Top"; $b.HorizontalAlignment = "Left"
        $b.Background = New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString("#EEEAFB"))
        $nr = New-Object Windows.Controls.TextBlock
        $nr.Text = "$i"; $nr.FontWeight = "SemiBold"; $nr.FontSize = 12.5; $nr.HorizontalAlignment = "Center"; $nr.VerticalAlignment = "Center"
        $nr.Foreground = New-Object Windows.Media.SolidColorBrush ([Windows.Media.ColorConverter]::ConvertFromString("#5B3CC4"))
        $b.Child = $nr
        $t = New-Object Windows.Controls.TextBlock
        $t.Text = $s; $t.TextWrapping = "Wrap"; $t.VerticalAlignment = "Center"
        [Windows.Controls.Grid]::SetColumn($t, 1)
        [void]$g.Children.Add($b); [void]$g.Children.Add($t)
        [void]$el.schritte.Children.Add($g)
        $i++
    }
    if ($schritte.Count -gt 0) { $el.schritte_karte.Visibility = "Visible" }
    $script:HILFE_ANTWORT = "abbrechen"
    if ($art -eq "angebot") { $haupt = "starten" } else { $haupt = "ok" }
    $el.haupt.Tag = $haupt
    $el.haupt.Add_Click({ param($s, $e) $script:HILFE_ANTWORT = [string]$s.Tag; [Windows.Window]::GetWindow($s).Close() })
    $el.zweit.Add_Click({ param($s, $e) $script:HILFE_ANTWORT = "abbrechen"; [Windows.Window]::GetWindow($s).Close() })
    if ($env:OMCAD_HILFE_SPUR) {
        $texte = @($el.titel.Text, $el.satz.Text) + @($schritte)
        if ($el.info.Visibility -eq "Visible") { $texte += $el.info.Text }
        $knoepfe = @("$($el.haupt.Content)")
        if ($el.zweit.Visibility -eq "Visible") { $knoepfe += "$($el.zweit.Content)" }
        $zeile = ConvertTo-Json -Compress -InputObject @{ art = $art; sprache = $script:HILFE_SP; texte = $texte; knoepfe = $knoepfe; zip = "$($daten.zip)"; ziel = "$($daten.ziel)" }
        [IO.File]::AppendAllText($env:OMCAD_HILFE_SPUR, $zeile + "`r`n", (New-Object Text.UTF8Encoding $false))
    }
    if ($env:OMCAD_HILFE_ANTWORT) {
        if ($env:OMCAD_HILFE_ANTWORT -eq "kaputt") { throw "Fenster kaputt (Gate)" }
        if ($env:OMCAD_HILFE_BILD) {
            # Zum Ansehen ohne Fenster: der Inhalt als PNG (doppelte Aufloesung).
            $c = $w.Content
            $w.Content = $null
            $rand = New-Object Windows.Controls.Border
            $rand.Background = $w.Background; $rand.Width = 540; $rand.Child = $c
            $rand.SetValue([Windows.Documents.TextElement]::FontFamilyProperty, $w.FontFamily)
            $rand.SetValue([Windows.Documents.TextElement]::FontSizeProperty, $w.FontSize)
            $rand.Measure((New-Object Windows.Size 540, ([double]::PositiveInfinity)))
            $rand.Arrange((New-Object Windows.Rect 0, 0, 540, $rand.DesiredSize.Height))
            $bmp = New-Object Windows.Media.Imaging.RenderTargetBitmap 1080, ([int]($rand.DesiredSize.Height * 2)), 192, 192, ([Windows.Media.PixelFormats]::Pbgra32)
            $bmp.Render($rand)
            $enc = New-Object Windows.Media.Imaging.PngBitmapEncoder
            $enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
            $fs = [IO.File]::Create($env:OMCAD_HILFE_BILD + "-" + $art + ".png")
            try { $enc.Save($fs) } finally { $fs.Close() }
        }
        return $env:OMCAD_HILFE_ANTWORT
    }
    Konsole 0
    try { [void]$w.ShowDialog() } finally { Konsole 5 }
    return $script:HILFE_ANTWORT
}

function Doppelklick-Starten([string]$ordner) {
    # 1_INSTALLIEREN.cmd aus dem entpackten Ordner, in DIESEM Konsolenfenster;
    # -> seine Rueckgabe.
    $si = New-Object Diagnostics.ProcessStartInfo
    $si.FileName = Join-Path $env:SystemRoot "System32\cmd.exe"
    $si.Arguments = '/d /s /c ""' + (Join-Path $ordner "1_INSTALLIEREN.cmd") + '""'
    $si.UseShellExecute = $false
    $si.WorkingDirectory = $ordner
    $p = [Diagnostics.Process]::Start($si)
    $p.WaitForExit()
    return $p.ExitCode
}

function Hilfe-Lauf([string]$art, [string]$wert, [string]$selbst) {
    $script:HILFE_SP = Hilfe-Sprache
    if ($art -eq "start") {
        $null = Hilfe-Fenster "start" @{ rc = $wert }
        return 0
    }
    if ($art -ne "gepackt") { return 9 }
    $zip = Zip-Suchen (Zip-Name-Aus-Pfad (Split-Path -Parent $selbst))
    if (-not $zip) {
        $null = Hilfe-Fenster "anleitung" @{}
        return 2
    }
    $ziel = Ziel-Ordner $zip
    if ((Hilfe-Fenster "angebot" @{ zip = $zip; ziel = $ziel }) -ne "starten") { return 2 }
    try {
        Entpacken $zip $ziel
        $cmd = Join-Path $ziel "1_INSTALLIEREN.cmd"
        if (-not (Test-Path -LiteralPath $cmd)) { throw "1_INSTALLIEREN.cmd fehlt" }
    } catch {
        $null = Hilfe-Fenster "anleitung" @{ fehler = $_.Exception.Message }
        return 2
    }
    return (Doppelklick-Starten $ziel)
}

if (-not $env:OMCAD_HILFE_NUR_FUNKTIONEN) {
    $global:OMCAD_RC = Hilfe-Lauf "$env:OMCAD_ART" "$env:OMCAD_WERT" "$env:OMCAD_SELBST"
}
