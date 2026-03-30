@echo off
if not exist .env (
    echo [!] HATA: Kurulum tamamlanmamis.
    echo Lutfen once "py setup_openclaw.py" komutunu calistirin.
    pause
    exit /b
)
echo AI Sirket Analisti Baslatiliyor...
py -m streamlit run dashboard.py
pause
