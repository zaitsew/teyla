from teyla import products


def test_query_lines_first_row_only():
    assert products.query_lines([{"wau": 4, "eur": 1.5, "x": None}, {"wau": 9}]) == ["wau=4", "eur=1.5", "x="]


def test_query_lines_no_rows_is_zero():
    assert products.query_lines([], "hub_") == ["hub_rows=0"]


def test_probe_sql_safe_mode_sends_nothing(monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert products.probe_sql("ref", "select 1") == (0, ["probe=safe_mode"])


def test_probe_sql_without_token(monkeypatch):
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setattr("teyla.config.safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(products, "supabase_token", lambda: None)
    assert products.probe_sql("abcdefghijklmnopqrst", "select 1", "app_") == (0, ["app_probe=needs_key"])


def test_supabase_token_decodes_cli_keychain(monkeypatch):
    import base64
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN", raising=False)
    enc = "go-keyring-base64:" + base64.b64encode(b"sbp_abc").decode()
    monkeypatch.setattr("teyla.providers.keychain", lambda service: enc)
    assert products.supabase_token() == "sbp_abc"


def test_probe_sql_refuses_a_ref_that_rewrites_the_path(monkeypatch):
    monkeypatch.setattr("teyla.config.safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(products, "supabase_token", lambda: "tok")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    for bad in ("abcdefghijklmnopqrst/database/query?", "../x", "", "ABCDEFGHIJKLMNOPQRST"):
        assert products.probe_sql(bad, "delete from t") == (2, ["probe=bad_ref"])
