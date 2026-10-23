import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nickatlas.desktop import run_desktop
import webview


root = Path(tempfile.mkdtemp(prefix="nix-native-check-"))
(root / "settings.json").write_text(
    json.dumps({"auto_update": False, "auto_discover": False}), encoding="utf-8"
)
result = {"passed": False}
original_start = webview.start


def probe():
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            window = webview.windows[0]
            try:
                ready = window.evaluate_js(
                    "Boolean(window.NIX && document.querySelector('#username') && NIX.state.sites >= 20000)"
                )
            except Exception:
                ready = False
            if ready:
                for page in ("sites", "discovery", "proxies", "settings", "about"):
                    window.evaluate_js(f"NIX.go({json.dumps(page)})")
                    assert window.evaluate_js("document.querySelector('main').children.length > 0")
                assert window.evaluate_js("NIX.state.account === ''")
                result["passed"] = True
                break
            time.sleep(0.25)
    finally:
        if webview.windows:
            webview.windows[0].destroy()


def start(**kwargs):
    return original_start(probe, **kwargs)


webview.start = start
run_desktop(root)
assert result["passed"], "Native interface or Python bridge did not load"
print("PASS: native interface, catalog, navigation, bridge and clean shutdown")
