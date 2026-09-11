#!/usr/bin/env bash
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SHAKWEER_SECRET="CHANGE-THIS-SECRET"
uvicorn app.main:app --host 0.0.0.0 --port 8080
