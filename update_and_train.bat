@echo off
python scripts\update_data.py --download-current
if errorlevel 1 pause & exit /b 1
python scripts\train_fouls_model.py
pause
