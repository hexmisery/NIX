import os
import sys
from pathlib import Path


def assets() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


def state_dir() -> Path:

    override = os.environ.get("NICKATLAS_DATA_DIR")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "NickAtlas"
        )
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support/NickAtlas"
    else:
        root = (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            / "nickatlas"
        )
    root.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        root.chmod(0o700)
    return root
