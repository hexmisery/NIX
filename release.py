from pathlib import Path
import platform
import shutil

def package():
    root = Path(__file__).resolve().parent
    output = root / "release"
    output.mkdir(exist_ok=True)
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    name = f"NIX-{system}-{arch}"
    target = "NIX.app" if system == "darwin" else "NIX"
    if not (root / "dist" / target).is_dir():
        raise FileNotFoundError("Run build.py before packaging")
    return shutil.make_archive(
        str(output / name),
        "zip" if system == "windows" else "gztar",
        root / "dist",
        target,
    )


if __name__ == "__main__":
    print(package())
