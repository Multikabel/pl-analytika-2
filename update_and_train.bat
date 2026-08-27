@echo off
python scripts\update_data.py --download-current
if errorlevel 1 pause & exit /b 1
python scripts\train_count_models.py
if errorlevel 1 pause & exit /b 1
echo.
echo Data updated and all count models retrained.
pause
