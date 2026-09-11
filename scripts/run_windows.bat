@echo off
cd /d "%~dp0.."
where py >nul 2>nul && set PY=py || set PY=python
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
