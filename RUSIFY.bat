@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul && (py -3 rusfusion.py %*) && goto :eof
where python >nul 2>nul && (python rusfusion.py %*) && goto :eof
echo Python not found. Install it from https://www.python.org/downloads/ (check "Add to PATH")
pause
