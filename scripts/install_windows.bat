@echo off
cd /d "%~dp0.."
where py >nul 2>nul && set PY=py || set PY=python
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo SHAKWEER NET Web POS dependencies installed.
echo Run scripts\run_windows.bat
pause
