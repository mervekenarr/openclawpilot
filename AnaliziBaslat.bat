@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo AI Sirket Analisti Baslatiliyor...
echo.
echo [IPUCU] Streamlit tarayicinizda acilacaktir.
echo.

py -m streamlit run dashboard.py

pause
