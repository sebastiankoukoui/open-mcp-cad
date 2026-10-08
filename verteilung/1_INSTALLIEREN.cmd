@echo off
rem Open MCP CAD - Installation. Doppelklick genuegt.
rem Startet Programmdateien\install.ps1 ohne Aenderung der
rem PowerShell-Ausfuehrungsrichtlinie des Systems (nur fuer diesen Aufruf).
rem
rem Gegenpruefung 2026-09-29: ein Doppelklick IN der ZIP-Datei (Windows
rem entpackt dann nur diese eine Datei) und ein PowerShell, das Skripte
rem sperrt (Firmenrichtlinie), schlossen das Fenster sofort - lesen konnte
rem man nichts. Beides steht jetzt da, das Fenster wartet auf eine Taste.
rem install.ps1 meldet "nicht vollstaendig" mit 3 und hat dann selbst
rem schon gewartet; jede andere Rueckgabe ausser 0 kommt von PowerShell.
set "OMCAD_PAUSE=1"
for %%a in (%*) do if /i "%%~a"=="-OhnePause" set "OMCAD_PAUSE="
if not exist "%~dp0Programmdateien\install.ps1" goto nicht_entpackt
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Programmdateien\install.ps1" %*
set "OMCAD_RC=%ERRORLEVEL%"
if "%OMCAD_RC%"=="0" exit /b 0
if "%OMCAD_RC%"=="3" exit /b 3
echo.
echo Der Installer konnte nicht starten - Rueckgabe %OMCAD_RC%, der Grund steht oben.
echo Sperrt eine Firmenrichtlinie PowerShell-Skripte, bitte die IT fragen.
if defined OMCAD_PAUSE pause
exit /b %OMCAD_RC%

:nicht_entpackt
echo.
echo Neben dieser Datei fehlt der Ordner Programmdateien.
echo Bitte die ZIP-Datei zuerst entpacken: mit der rechten Maustaste auf die
echo ZIP-Datei klicken, "Alle extrahieren ..." waehlen und danach im
echo entpackten Ordner 1_INSTALLIEREN.cmd doppelklicken.
if defined OMCAD_PAUSE pause
exit /b 2
