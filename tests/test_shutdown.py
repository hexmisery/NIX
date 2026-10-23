import asyncio
import json

from nickatlas.web_bridge import DesktopAPI


def test_close_does_not_restart_collector(tmp_path, monkeypatch):
    import nickatlas.web_bridge as bridge

    (tmp_path / "settings.json").write_text(
        json.dumps({"auto_update": False, "auto_discover": False}), encoding="utf-8"
    )
    started = []

    async def collect(*args, **kwargs):
        started.append(True)
        try:
            await asyncio.sleep(30)
        finally:
            await asyncio.sleep(1)

    monkeypatch.setattr(bridge, "harvest_loop", collect)
    api = DesktopAPI(tmp_path)
    api.discover(200, "all", True, 24)
    api._shutdown()
    assert len(started) <= 1
    assert not api._thread.is_alive()
    assert api._loop.is_closed()
    assert json.loads((tmp_path / "collection-session.json").read_text())["resume"]
