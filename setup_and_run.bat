@echo off
python -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
python scripts\update_data.py
if errorlevel 1 pause & exit /b 1
python scripts\train_count_models.py
if errorlevel 1 pause & exit /b 1
python -m streamlit run app\app.py
pause
