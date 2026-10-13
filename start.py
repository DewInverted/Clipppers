#!/usr/bin/env python3
"""One-click launcher: creates .venv, installs deps, opens Clipppers in your browser."""
import os, subprocess, sys, webbrowser, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
venv_py = os.path.join(ROOT, ".venv", "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
if not os.path.exists(venv_py):
    print("⏳ First run: creating environment & installing dependencies…")
    subprocess.check_call([sys.executable, "-m", "venv", ".venv"])
    subprocess.check_call([venv_py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([venv_py, "-m", "pip", "install", "-q", "-r", "requirements.txt"])
threading.Timer(2.5, lambda: webbrowser.open("http://localhost:8000")).start()
print("✂️  Clipppers → http://localhost:8000   (Ctrl+C to stop)")
subprocess.call([venv_py, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"])
