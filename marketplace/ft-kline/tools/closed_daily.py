"""Conservative exchange-local closed daily bars for read-only analyses."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from core.rows import RowsValidationError, validate_rows
from tools.lines import LineError

MARKETS = {
    "CN": (ZoneInfo("Asia/Shanghai"), time(15, 40)),
    "HK": (ZoneInfo("Asia/Hong_Kong"), time(16, 20)),
    "US": (ZoneInfo("America/New_York"), time(16, 10)),
}


def market_for_symbol(symbol: str) -> str | None:
    suffix = str(symbol or "").upper().rsplit(".", 1)[-1]
    return "CN" if suffix in {"XSHG", "XSHE", "SH", "SZ"} else suffix if suffix in {"HK", "US"} else None


def closed_daily(rows, *, symbol: str, interval: str, source_interval: str | None = None,
                 interval_value: int | None = 1, provider: str | None = None,
                 now: datetime | None = None):
    if interval != "day" or source_interval not in {None, "day"} or interval_value != 1:
        raise LineError("daily_analysis_only", "形态与九转首版仅支持单日线；请在当前图切换后重新分析。")
    try:
        candles = validate_rows(rows, min_len=1)
    except RowsValidationError:
        raise LineError("daily_analysis_unavailable", "当前图缺少有效的已加载日线。") from None
    market = market_for_symbol(symbol)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    quality = []
    if market is None:
        quality.append("market_unknown_current_day_excluded")
        # UTC prior days are surely historical regardless of the exchange zone.
        cutoff_date = clock.astimezone(timezone.utc).date()
        accepted = [r for r in candles if datetime.fromtimestamp(r["time"], timezone.utc).date() < cutoff_date]
        return accepted, {"market": None, "timezone": None, "as_of": accepted[-1]["time"] if accepted else None,
                          "quality": quality, "excluded": len(candles) - len(accepted)}
    zone, close_time = MARKETS[market]
    local = clock.astimezone(zone)
    accepted = []
    for row in candles:
        bar = datetime.fromtimestamp(row["time"], zone)
        utc_day = datetime.fromtimestamp(row["time"], timezone.utc).date()
        if bar.date() < local.date() and utc_day == local.date():
            # A date-only UTC-midnight stamp for today's US session appears as
            # yesterday evening in New York. It is not proof of a closed bar.
            quality.append("date_semantics_uncertain_current_day_excluded")
        elif bar.date() < local.date():
            accepted.append(row)
        elif bar.date() > local.date():
            quality.append("future_daily_bar_excluded")
        elif provider in {None, "unknown", "external"}:
            quality.append("source_unknown_current_day_excluded")
        elif bar.time() < time(9, 0) or bar.time() > time(23, 0):
            quality.append("date_semantics_uncertain_current_day_excluded")
        elif local.time() >= close_time:
            accepted.append(row)
        else:
            quality.append("current_day_not_conservatively_closed")
    return accepted, {"market": market, "timezone": zone.key,
                      "as_of": accepted[-1]["time"] if accepted else None,
                      "quality": sorted(set(quality)), "excluded": len(candles) - len(accepted),
                      "cutoff_local": close_time.strftime("%H:%M")}
