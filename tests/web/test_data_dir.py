"""Startup check of the data folder: a wrong DAMAGE_WEB_DATA stops the start instead of creating an empty database."""
import pytest

from web import config


def test_missing_data_folder_stops_the_start(monkeypatch, tmp_path):
    wrong = tmp_path / "dta"                      # a typo: the folder does not exist
    monkeypatch.setenv("DAMAGE_WEB_DATA", str(wrong))
    with pytest.raises(config.DataDirError, match="does not exist"):
        config.check_data_dir()
    assert not wrong.exists()                     # nothing was created


def test_existing_data_folder_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv("DAMAGE_WEB_DATA", str(tmp_path))
    config.check_data_dir()


def test_default_data_folder_needs_no_variable(monkeypatch):
    monkeypatch.delenv("DAMAGE_WEB_DATA", raising=False)
    config.check_data_dir()
