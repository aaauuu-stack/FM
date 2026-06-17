"""Fast mode is opt-in only — full quality by default on Render."""

from odds.fast_mode import is_cloud_host, is_fast_mode


def test_fast_mode_off_by_default():
    assert is_fast_mode() is False


def test_cloud_host_detects_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert is_cloud_host() is True
