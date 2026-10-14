#!/usr/bin/env python3
"""One-click launcher: creates .venv, installs deps, opens Clipppers in your browser."""
import os, subprocess, sys, webbrowser, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

# On Windows, warn if the project lives in a path that's likely to exceed MAX_PATH
# (e.g. Downloads\Clipppers-1.1.0 (1)\Clipppers-1.1.0\).
if os.name == "nt":
    try:
        import ctypes
        # Try enabling long-path support; if that works no need to warn.
        k32 = ctypes.windll.kernel32
        # (LongPathsEnabled is a system-wide registry setting we can't toggle without admin;
        #  this just probes that the app's venv path doesn't exceed the classic limit.)
        venv_py_rel = os.path.join(".venv", "Scripts", "python.exe")
        if len(os.path.join(ROOT, venv_py_rel)) >= 200:
            print("⚠ Warning: Clipppers is installed in a fairly deep folder path, which can")
            print("  cause Windows 'filename too long' errors. If clips fail to export, move")
            print("  the Clipppers folder closer to C:\\  (e.g. C:\\Clipppers\\) and re-run.")
            print()
    except Exception:
        pass

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
