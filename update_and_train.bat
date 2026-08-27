@echo off
echo [1/5] Updating fixtures...
python scripts\update_fixtures.py --season 2026-27 --force

echo [2/5] Updating match data...
python scripts\update_data.py --download-current
if errorlevel 1 pause & exit /b 1

echo [3/5] Settling archived tips...
python scripts\prediction_archive.py
if errorlevel 1 pause & exit /b 1

echo [4/5] Training models...
python scripts\train_count_models.py
if errorlevel 1 pause & exit /b 1

echo [5/5] Saving predictions for the next/current round...
python scripts\snapshot_next_round.py
if errorlevel 1 pause & exit /b 1

echo.
echo Fixtures, data, models and tip statistics updated.
pause
