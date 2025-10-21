import os
from settings import load_settings


def test_load_settings_defaults(monkeypatch):
    # ensure no interference
    for k in [
        "CLOB_HOST","CHAIN_ID","CLOB_SIGNATURE_TYPE","DB_PATH",
        "WALLETS_CSV","CHEAP_MARKETS_FILE","LOG_LEVEL",
        "MIN_ACTIVE_MARKETS","MAX_WORKERS","TRADE_DELAY_MIN","TRADE_DELAY_MAX",
    ]:
        monkeypatch.delenv(k, raising=False)

    s = load_settings()
    assert s.clob_host.startswith("http")
    assert s.chain_id == 137
    assert s.db_path.endswith("polyfarm.db")


def test_load_settings_overrides(monkeypatch):
    monkeypatch.setenv("DB_PATH", "x.db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = load_settings()
    assert s.db_path == "x.db"
    assert s.log_level == "DEBUG"

