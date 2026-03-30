@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%ops\openclaw"

if not exist .env (
    echo [!] HATA: Kurulum tamamlanmamis.
    echo Lutfen once "py setup_openclaw.py" komutunu calistirin.
    pause
    exit /b
)

echo 🤖 AI Sirket Analisti Baslatiliyor...
echo.
echo [IPUCU] Streamlit tarayicinizda acilacaktir.
echo.

py -m streamlit run dashboard.py

pause
