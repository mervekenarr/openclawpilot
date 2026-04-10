@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo LinkedIn Mesajci Baslatiliyor...
echo.
echo Bu pencere acik kaldigi surece n8n LinkedIn mesajlari gonderebilir.
echo Kapatmak icin CTRL+C basin.
echo.

set LINKEDIN_SESSION_TOKEN=
set LINKEDIN_PERSISTENT_SESSION=true
set LINKEDIN_USER_DATA_DIR=%SCRIPT_DIR%runtime-home\linkedin-bootstrap-profile
set LINKEDIN_STORAGE_STATE_PATH=%SCRIPT_DIR%runtime-home\linkedin-storage-state.json
set LINKEDIN_NAV_TIMEOUT_MS=30000
set LINKEDIN_MAX_EMPLOYEE_CANDIDATES=3
set LINKEDIN_DEBUG_SCREENSHOTS=false
set LINKEDIN_LOG_SENSITIVE_DATA=true
set LINKEDIN_HEADLESS=false
set FLASK_PORT=8503

py -c "import linkedin_api; linkedin_api.app.run(host='0.0.0.0', port=8503, debug=False)"

pause
