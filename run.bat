@echo off
cd /d "%~dp0"
if not exist .venv (
  py -m venv .venv
  call .venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
echo.
echo Fantasy Command Center starting...
echo On this PC: http://localhost:5050
echo On your phone: http://YOUR-PC-IP:5050
echo.
python app.py
pause
