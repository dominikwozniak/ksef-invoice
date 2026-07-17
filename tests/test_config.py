import shutil
from pathlib import Path

import pytest

from ksef_invoice.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_project(tmp_path: Path, config_text: str) -> Path:
    shutil.copy(PROJECT_ROOT / "examples" / "template.example.xml", tmp_path / "template.xml")
    (tmp_path / "config.toml").write_text(config_text)
    return tmp_path


BASE = """
nip = "1111111111"
[profiles.x]
template = "template.xml"
{extra}
"""


def test_both_due_rules_rejected(tmp_path):
    root = write_project(tmp_path, BASE.format(extra="due_days = 14\ndue_day_next_month = 15"))
    with pytest.raises(ValueError, match="jednocześnie"):
        load_config(root)


def test_no_due_rule_defaults_to_14_days(tmp_path):
    root = write_project(tmp_path, BASE.format(extra=""))
    profile = load_config(root).profiles["x"]
    assert profile.due_days == 14
    assert profile.due_day_next_month is None


def test_profile_due_rule_overrides_top_level_default(tmp_path):
    config = 'nip = "1"\ndue_days = 14\n[profiles.x]\ntemplate = "template.xml"\ndue_day_next_month = 15\n'
    root = write_project(tmp_path, config)
    profile = load_config(root).profiles["x"]
    assert profile.due_days is None
    assert profile.due_day_next_month == 15


def test_missing_template_rejected(tmp_path):
    (tmp_path / "config.toml").write_text('nip = "1"\n[profiles.x]\ntemplate = "nie-ma.xml"\n')
    with pytest.raises(FileNotFoundError, match="nie-ma.xml"):
        load_config(tmp_path)
