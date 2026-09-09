from tools.watchlist import get_watchlist_state, save_watchlist_state


def test_watchlist_persists_across_independent_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_KLINE_STATE_DIR", str(tmp_path))
    saved = save_watchlist_state({
        "groups": [{"id": "default", "name": "默认分组"}, {"id": "etf", "name": "ETF"}],
        "items": [
            {"symbol": "510300.XSHG", "name": "沪深300ETF", "groupId": "etf"},
            {"symbol": "600519.XSHG", "name": "贵州茅台", "groupId": "default"},
        ],
        "activeGroupId": "etf",
        "sort": "change_desc",
    })
    assert saved["ok"]
    restored = get_watchlist_state()
    assert restored["revision"] == 1
    assert restored["activeGroupId"] == "etf"
    assert [item["symbol"] for item in restored["items"]] == ["510300.XSHG", "600519.XSHG"]


def test_watchlist_normalizes_invalid_groups_and_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_KLINE_STATE_DIR", str(tmp_path))
    result = save_watchlist_state({
        "groups": [{"id": "sector", "name": "行业"}],
        "items": [
            {"symbol": "600519.XSHG", "name": "贵州茅台", "groupId": "sector"},
            {"symbol": "600519.XSHG", "name": "重复", "groupId": "sector"},
            {"symbol": "bad", "name": "无效分组", "groupId": "missing"},
        ],
    })
    assert result["ok"]
    state = result["watchlist"]
    assert state["groups"][0]["id"] == "default"
    assert state["items"] == [{"symbol": "600519.XSHG", "name": "贵州茅台", "groupId": "sector"}]


def test_watchlist_rejects_stale_revision_without_overwriting_newer_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_KLINE_STATE_DIR", str(tmp_path))
    first = save_watchlist_state({
        "revision": 0,
        "groups": [{"id": "default", "name": "默认分组"}],
        "items": [{"symbol": "600519.XSHG", "name": "贵州茅台", "groupId": "default"}],
    })
    assert first["ok"]
    stale = save_watchlist_state({
        "revision": 0,
        "groups": [{"id": "default", "name": "默认分组"}],
        "items": [{"symbol": "000001.XSHE", "name": "平安银行", "groupId": "default"}],
    })
    assert stale["ok"] is False
    assert stale["error"] == "watchlist_conflict"
    assert [item["symbol"] for item in stale["watchlist"]["items"]] == ["600519.XSHG"]
