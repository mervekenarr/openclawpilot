@echo off
setlocal

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\..") do set "REPO_DIR=%%~fI"
set "OPENCLAW_CONFIG_PATH=%REPO_DIR%\.openclaw-home\openclaw.json"
set "OPENCLAW_STATE_DIR=%REPO_DIR%\.openclaw-home"
set "OPENCLAW_CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set "OPENCLAW_DEBUG_PROFILE=%OPENCLAW_STATE_DIR%\chrome-profile"
set "OPENCLAW_LINKEDIN_BROWSER=1"
set "OPENCLAW_PYTHON=%REPO_DIR%\.venv313\Scripts\python.exe"

if not exist "%OPENCLAW_PYTHON%" (
    set "OPENCLAW_PYTHON=py"
)

if not exist .env (
    echo [!] HATA: Kurulum tamamlanmamis.
    echo Lutfen once "py setup_openclaw.py" komutunu calistirin.
    pause
    exit /b
)

echo OpenClaw proje ayarlari yuklendi.
echo.
echo [IPUCU] OpenClaw gateway kontrol ediliyor...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18789/' -TimeoutSec 2 ^| Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo OpenClaw gateway baslatiliyor...
    start "OpenClaw Gateway" /min powershell -NoProfile -WindowStyle Hidden -Command "$env:OPENCLAW_CONFIG_PATH='%OPENCLAW_CONFIG_PATH%'; $env:OPENCLAW_STATE_DIR='%OPENCLAW_STATE_DIR%'; Set-Location '%APP_DIR%'; openclaw gateway run --compact --force"
    timeout /t 4 /nobreak >nul
) else (
    echo OpenClaw gateway zaten hazir.
)

echo.
echo [IPUCU] OpenClaw debug tarayicisi kontrol ediliyor...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18800/json/version' -TimeoutSec 2 ^| Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    if exist "%OPENCLAW_CHROME%" (
        echo OpenClaw debug Chrome baslatiliyor...
        start "" "%OPENCLAW_CHROME%" --remote-debugging-port=18800 --user-data-dir="%OPENCLAW_DEBUG_PROFILE%" --disable-gpu --no-first-run --no-default-browser-check
        timeout /t 3 /nobreak >nul
    ) else (
        echo [!] UYARI: Chrome bulunamadi. OpenClaw browser baglantisi eksik kalabilir.
    )
) else (
    echo OpenClaw debug tarayicisi zaten hazir.
)

echo.
echo AI Sirket Analisti Baslatiliyor...
echo [IPUCU] Python calisani: %OPENCLAW_PYTHON%
"%OPENCLAW_PYTHON%" -m streamlit run dashboard.py
pause
