"""Fast mode skips slow network scrapes on Render."""

from odds.fast_mode import is_fast_mode


def test_fast_mode_off_by_default():
    assert is_fast_mode() is False
