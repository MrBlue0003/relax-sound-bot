"""run.py — Dispatcher for Railway services.

Reads BOT_MODE env var to decide which bot to run:
  BOT_MODE=long   -> main_long.py  (11-hour ambient videos, once/day)
  BOT_MODE=short  -> main.py       (short clips, 4x/day)  [default]
"""
import os
import subprocess
import sys

mode = os.getenv("BOT_MODE", "short").strip().lower()

if mode == "long":
    script = "main_long.py"
else:
    script = "main.py"

result = subprocess.run([sys.executable, "-u", script])
sys.exit(result.returncode)
