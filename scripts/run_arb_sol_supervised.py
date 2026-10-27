#!/usr/bin/env python3
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_arb_sol.py"

def detect_python():
    env_python = os.environ.get("BOT_PYTHON")
    if env_python:
        return env_python
    if os.name == "nt":
        candidates = [
            ROOT / ".venv" / "Scripts" / "python.exe",
            ROOT / "venv" / "Scripts" / "python.exe",
        ]
    else:
        candidates = [
            ROOT / ".venv" / "bin" / "python",
            ROOT / "venv" / "bin" / "python",
        ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def next_delay(base_seconds: float, attempt: int, max_seconds: float = 60.0) -> float:
    delay = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    return delay + random.uniform(0.0, 1.0)


def main():
    python_bin = detect_python()
    base_delay = float(os.environ.get("BOT_RESTART_BACKOFF_SECONDS", "5"))
    max_delay = float(os.environ.get("BOT_RESTART_BACKOFF_MAX_SECONDS", "60"))
    no_restart_codes = {2, 3}

    attempt = 0
    while True:
        attempt += 1
        cmd = [python_bin, str(SCRIPT)]
        print(f"[launcher] starting bot ({attempt}) with: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=str(ROOT), env=os.environ.copy())
        code = proc.returncode

        if code in no_restart_codes:
            print(f"[launcher] deliberate stop code {code}; not restarting.")
            return code

        delay = next_delay(base_delay, attempt, max_delay=max_delay)
        print(f"[launcher] process exited with code {code}; restarting in {delay:.1f}s")
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())