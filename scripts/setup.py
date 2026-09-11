"""Set up the app and editor through the uv runtime used to launch this script."""

import subprocess
import sys
from pathlib import Path

from editor import configure_editor

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    subprocess.run([sys.executable, "manage.py", "local", "setup"], cwd=ROOT, check=True)
    configure_editor()
