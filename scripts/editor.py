"""Prepare locked packages for Pylance without creating a virtual environment."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def configure_editor():
    uv = ROOT / ".tools" / "uv" / "uv.exe"
    executable = str(uv) if uv.exists() else shutil.which("uv")
    if not executable:
        raise RuntimeError("uv is not installed")
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(ROOT / ".tools" / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(ROOT / ".tools" / "python"),
    }
    requirements = ROOT / ".tools" / "editor-requirements.txt"
    target = ROOT / ".tools" / "editor-packages"
    python = ROOT / ".tools" / "python" / "cpython-3.13-windows-x86_64-none" / "python.exe"
    subprocess.run(
        [
            executable,
            "export",
            "--locked",
            "--all-groups",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
            "--quiet",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    subprocess.run(
        [
            executable,
            "pip",
            "sync",
            "--python",
            str(python),
            "--target",
            str(target),
            "--require-hashes",
            str(requirements),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    print("Editor imports are ready. In VS Code, run Developer: Reload Window.")


if __name__ == "__main__":
    configure_editor()
