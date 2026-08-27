@echo off
cd /d %~dp0
python scripts\update_data.py --download-current
pause
