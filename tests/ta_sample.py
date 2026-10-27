"""Deterministic OHLCV fixture for the TA-Lib contract tests.

Keep this in the repository: local benchmark captures are intentionally ignored.
"""

from math import sin


def sample_rows(count=250):
    rows = []
    for index in range(count):
        baseline = 25 + index * 0.025 + 2.5 * sin(index / 11)
        open_price = baseline + 0.35 * sin(index / 3)
        close_price = baseline + 0.45 * sin(index / 5 + 1)
        rows.append({
            "time": 1704067200 + index * 86400,
            "open": round(open_price, 4),
            "high": round(max(open_price, close_price) + 0.3 + 0.1 * (index % 3), 4),
            "low": round(min(open_price, close_price) - 0.3 - 0.1 * (index % 4), 4),
            "close": round(close_price, 4),
            "volume": float(1000000 + (index % 17) * 75000),
        })
    return rows
