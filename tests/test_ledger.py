from ksef_invoice.ledger import Ledger


def make_ledger(tmp_path):
    return Ledger(tmp_path / "ledger.json")


def test_next_seq_starts_at_one(tmp_path):
    assert make_ledger(tmp_path).next_seq("test", 2026) == 1


def test_sequence_shared_across_profiles(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("test", "klient-a", "2026-07", seq=1, year=2026, entry={"number": "FS/1/2026"})
    assert ledger.next_seq("test", 2026) == 2
    ledger.record("test", "klient-b", "2026-07", seq=2, year=2026, entry={"number": "FS/2/2026"})
    assert ledger.next_seq("test", 2026) == 3


def test_sequence_separate_per_environment_and_year(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("test", "klient-a", "2026-07", seq=5, year=2026, entry={})
    assert ledger.next_seq("prod", 2026) == 1
    assert ledger.next_seq("test", 2027) == 1


def test_seq_override_moves_counter_forward(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("prod", "klient-a", "2026-07", seq=14, year=2026, entry={})
    assert ledger.next_seq("prod", 2026) == 15


def test_seq_lower_than_counter_does_not_regress(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("test", "klient-a", "2026-06", seq=9, year=2026, entry={})
    ledger.record("test", "klient-b", "2026-06", seq=3, year=2026, entry={})
    assert ledger.next_seq("test", 2026) == 10


def test_duplicate_lookup_per_profile_and_month(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("test", "klient-a", "2026-07", seq=1, year=2026, entry={"number": "FS/1/2026"})
    assert ledger.get("test", "klient-a", "2026-07") == {"number": "FS/1/2026"}
    assert ledger.get("test", "klient-b", "2026-07") is None
    assert ledger.get("test", "klient-a", "2026-08") is None
    assert ledger.get("prod", "klient-a", "2026-07") is None


def test_year_started(tmp_path):
    ledger = make_ledger(tmp_path)
    assert ledger.year_started("prod", 2026) is False
    ledger.record("prod", "klient-a", "2026-07", seq=8, year=2026, entry={"number": "FS/8/2026"})
    assert ledger.year_started("prod", 2026) is True
    assert ledger.year_started("prod", 2027) is False
    assert ledger.year_started("test", 2026) is False


def test_number_exists_finds_number_across_profiles(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.record("test", "klient-a", "2026-07", seq=1, year=2026, entry={"number": "FS/1/2026"})
    assert ledger.number_exists("test", "FS/1/2026") == ("klient-a", "2026-07")
    assert ledger.number_exists("test", "FS/2/2026") is None
    assert ledger.number_exists("prod", "FS/1/2026") is None
