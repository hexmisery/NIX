import os
import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys

options = argparse.ArgumentParser()
options.add_argument("--onefile", action="store_true")
args = options.parse_args()
root = Path(__file__).resolve().parent
scratch = Path(os.environ.get("NICKATLAS_BUILD_ROOT", root / ".build")).resolve()
scratch.mkdir(parents=True, exist_ok=True)
icon_args = []
if sys.platform == "win32":
    icon_args = ["--icon", str(root / "nickatlas/assets/NIX.ico")]
elif sys.platform == "darwin":
    payload = (root / "nickatlas/assets/NIX.png").read_bytes()
    icon_path = scratch / "NIX.icns"
    chunk = b"ic09" + struct.pack(">I", len(payload) + 8) + payload
    icon_path.write_bytes(b"icns" + struct.pack(">I", len(chunk) + 8) + chunk)
    icon_args = ["--icon", str(icon_path)]

cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "NIX",
    "--onefile" if args.onefile else "--onedir",
    "--workpath",
    str(scratch / "cache"),
    "--specpath",
    str(scratch),
    "--distpath",
    str(root / ("standalone" if args.onefile else "dist")),
    "--add-data",
    f"{root / 'nickatlas' / 'assets'}{os.pathsep}assets",
    "--add-data",
    f"{root / 'licenses'}{os.pathsep}licenses",
    "--add-data",
    f"{root / 'nickatlas/web'}{os.pathsep}web",
    "--exclude-module",
    "PySide6",
    "--exclude-module",
    "PyQt5",
    "--exclude-module",
    "PyQt6",
    "--exclude-module",
    "PyQt4",
    *icon_args,
    str(root / "run.py"),
]
try:
    subprocess.run(cmd, cwd=root, check=True)
except (OSError, subprocess.CalledProcessError):
    raise SystemExit(
        "Build failed. Install requirements.txt and pyinstaller in the active environment."
    )
