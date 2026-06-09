@echo off
where python >nul 2>&1 && (python "%~dp0install.py" & pause & exit /b)
where python3 >nul 2>&1 && (python3 "%~dp0install.py" & pause & exit /b)
where py >nul 2>&1 && (py "%~dp0install.py" & pause & exit /b)
echo ERROR: Python not found. Install Python 3.10+ and try again.
pause
