import pytest


@pytest.fixture(autouse=True)
def isolate_user_settings_file(tmp_path, monkeypatch):
    """
    Prevent tests from reading/writing the repo's `data/settings.json`.

    Config persists normalized settings to USER_SETTINGS_FILE during init; in
    tests we isolate this side-effect to a temp path.
    """
    monkeypatch.setenv("USER_SETTINGS_FILE", str(tmp_path / "settings.json"))
    yield
