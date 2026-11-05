@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >/dev/null 2>/dev/null && (py -3 rusfusion.py --restore) || (python rusfusion.py --restore)
pause
