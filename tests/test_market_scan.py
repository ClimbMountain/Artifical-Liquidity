from market_scan import scan_and_write


def test_scan_and_write_handles_no_wallets(tmp_path, monkeypatch):
    # Point to a non-existent wallets file to force scanner construction failure
    monkeypatch.setenv("WALLETS_CSV", str(tmp_path / "nowallets.csv"))
    out = tmp_path / "out.txt"
    count = scan_and_write(str(out), top_n=5)
    assert count == 0
    assert out.exists()
    assert out.read_text() == ""

