@echo off
python scripts\auto_update.py
if errorlevel 1 pause & exit /b 1
echo.
echo Automatic-update workflow completed locally.
pause
