@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul && (py -3 rusfusion.py --restore) && goto :eof
python rusfusion.py --restore
pause
