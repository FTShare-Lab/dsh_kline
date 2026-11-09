"""Causal, read-only daily price patterns. Shared by DSH and Codex hosts."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite

import numpy as np
import talib

from tools.closed_daily import closed_daily
from tools.lines import LineError
from tools.range_candidates import DEFAULT_WINDOW_SIZES, range_candidates

RULE_VERSION = "price_patterns_v1"
TYPES = ("double_top", "double_bottom", "head_shoulders_top", "head_shoulders_bottom", "platform")


def _pivots(rows):
    result = {}
    for index in range(2, len(rows) - 2):
        neighbors = rows[index - 2:index] + rows[index + 1:index + 3]
        high = all(rows[index]["high"] > x["high"] for x in neighbors)
        low = all(rows[index]["low"] < x["low"] for x in neighbors)
        if high != low:
            result.setdefault(index + 2, []).append({"index": index, "side": "high" if high else "low",
                                                      "price": rows[index]["high"] if high else rows[index]["low"],
                                                      "time": rows[index]["time"]})
    return result


def _neckline(anchors, index):
    a, b = anchors[1], anchors[3]
    return a["price"] + (b["price"] - a["price"]) * (index - a["index"]) / (b["index"] - a["index"])


def _structure(kind, anchors, atr, rows, reasons):
    top = kind.endswith("top")
    first = anchors[0]["index"]
    if first < 20:
        reasons["insufficient_prior_trend"] += 1
        return None
    trend = rows[first - 1]["close"] - rows[first - 21]["close"]
    if (trend if top else -trend) < 2 * atr:
        reasons["prior_trend_below_2_atr"] += 1
        return None
    if kind.startswith("double"):
        a, middle, b = anchors
        gap = b["index"] - a["index"]
        mean = (a["price"] + b["price"]) / 2
        depth = (min(a["price"], b["price"]) - middle["price"]) if top else (middle["price"] - max(a["price"], b["price"]))
        if not 10 <= gap <= 120 or abs(a["price"] - b["price"]) > min(atr, .03 * mean) or depth < 2 * atr:
            reasons["double_geometry_rejected"] += 1
            return None
        neck = middle["price"]
        outer = max(a["price"], b["price"]) if top else min(a["price"], b["price"])
        return {"neckline": {"type": "horizontal", "price": neck}, "outer": outer}
    a, n1, head, n2, b = anchors
    gaps = [anchors[j + 1]["index"] - anchors[j]["index"] for j in range(4)]
    span = b["index"] - a["index"]
    left, right = head["index"] - a["index"], b["index"] - head["index"]
    neck_at_head = _neckline(anchors, head["index"])
    height = (head["price"] - neck_at_head) if top else (neck_at_head - head["price"])
    mean_shoulder = (a["price"] + b["price"]) / 2
    protrudes = min((head["price"] - a["price"] if top else a["price"] - head["price"]),
                    (head["price"] - b["price"] if top else b["price"] - head["price"]))
    if (min(gaps) < 3 or not 20 <= span <= 160 or not .5 <= left / right <= 2
            or protrudes < atr or height < 2 * atr or abs(a["price"] - b["price"]) > min(.5 * height, .03 * mean_shoulder)
            or abs(n1["price"] - n2["price"]) > .5 * height):
        reasons["head_shoulders_geometry_rejected"] += 1
        return None
    return {"neckline": {"type": "sloped", "from": {"index": n1["index"], "time": n1["time"], "price": n1["price"]},
                         "to": {"index": n2["index"], "time": n2["time"], "price": n2["price"]}},
            "outer": head["price"]}


def _boundary(item, index):
    if item["type"] == "platform":
        return item["box"]
    neck = item["neckline"]
    if neck["type"] == "horizontal":
        return neck["price"]
    a, b = neck["from"], neck["to"]
    return a["price"] + (b["price"] - a["price"]) * (index - a["index"]) / (b["index"] - a["index"])


def _outside(item, row, index, direction):
    base = _boundary(item, index)
    if item["type"] == "platform":
        edge = base["upper_price"] if direction == "up" else base["lower_price"]
    else:
        edge = base
    return row["close"] > edge + item["buffer"] if direction == "up" else row["close"] < edge - item["buffer"]


def _reclaimed(item, row, index):
    base = _boundary(item, index)
    if item["type"] == "platform":
        # Back inside the frozen box, not merely below its upper breakout edge.
        return (row["close"] < base["upper_price"] - item["buffer"] if item["break_direction"] == "up"
                else row["close"] > base["lower_price"] + item["buffer"])
    return (row["close"] > base + item["buffer"] if item["break_direction"] == "down"
            else row["close"] < base - item["buffer"])


def _advance(item, row, index):
    if item["status"] in {"structurally_invalid", "expired", "breakout_failed"}:
        return
    def event(name):
        item["events"].append({"type": name, "time": row["time"], "index": index})
    if item["confirmed_index"] is None:
        if item["type"] != "platform" and ((item["direction"] == "down" and row["high"] > item["outer"] + item["buffer"])
                                                 or (item["direction"] == "up" and row["low"] < item["outer"] - item["buffer"])):
            item["status"] = "structurally_invalid"; item["invalidated_at"] = row["time"]; event("structurally_invalid"); return
        if index - item["available_index"] > 60:
            item["status"] = "expired"; item["invalidated_at"] = row["time"]; event("expired"); return
        direction = item.get("pending_direction") or item["direction"]
        if item["pending_direction"] and _outside(item, row, index, direction):
            item["status"] = "price_confirmed"; item["confirmed_at"] = row["time"]
            item["confirmed_index"] = index; item["break_direction"] = direction
            item["pending_direction"] = None; event("price_confirmed")
            return
        if item["pending_direction"]:
            item["pending_direction"] = None; item["status"] = "candidate"; event("pending_cancelled")
        directions = ("up", "down") if item["type"] == "platform" else (item["direction"],)
        for side in directions:
            if _outside(item, row, index, side):
                item["pending_direction"] = side; item["status"] = "pending_confirmation"; event("pending_confirmation"); break
        return
    age = index - item["confirmed_index"]
    if age > 20 or item["followup_complete"]:
        return
    if _reclaimed(item, row, index):
        item["reclaim_count"] += 1
        if item["reclaim_count"] == 2:
            item["status"] = "breakout_failed"; item["invalidated_at"] = row["time"]; event("breakout_failed")
            return
    else:
        item["reclaim_count"] = 0
    if age == 20:
        item["followup_complete"] = True; event("followup_complete")


def _volume_evidence(rows, item, provider, volume_unit):
    if provider not in {"ftshare", "eastmoney_free", "tencent_free", "builtin_free"} or volume_unit not in {"shares", "lots"}:
        return {"status": "unknown", "reason": "source_or_unit_unverified"}
    i = item["confirmed_index"]
    if i is None or i < 20:
        return {"status": "unknown", "reason": "insufficient_preceding_volume"}
    baseline = [r["volume"] for r in rows[i - 20:i]]
    if any(not isfinite(x) or x < 0 for x in baseline) or sum(baseline) <= 0:
        return {"status": "unknown", "reason": "volume_unavailable"}
    return {"status": "known", "relative_to_preceding_20": rows[i]["volume"] / (sum(baseline) / 20),
            "unit": volume_unit}


def price_pattern_candidates(rows, *, symbol: str, interval: str = "day", source_interval: str | None = "day",
                             interval_value: int | None = 1, provider: str | None = None,
                             volume_unit: str | None = None, pattern_types=None,
                             lookback_bars: int = 240, max_candidates: int = 5,
                             anchor_times: tuple[int, ...] | None = None, now: datetime | None = None):
    if type(lookback_bars) is not int or not 60 <= lookback_bars <= 300:
        raise LineError("invalid_pattern_lookback", "价格形态观察范围必须为60至300根日线。")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 5:
        raise LineError("invalid_pattern_limit", "价格形态最多返回1至5个候选。")
    selected = tuple(pattern_types or TYPES)
    if not selected or len(set(selected)) != len(selected) or any(x not in TYPES for x in selected):
        raise LineError("invalid_pattern_types", "形态类型仅支持双顶、双底、头肩顶、头肩底及平台，且不得重复。")
    if anchor_times is not None and (len(anchor_times) not in {3, 5}
                                     or any(type(t) is not int for t in anchor_times)
                                     or tuple(sorted(set(anchor_times))) != anchor_times):
        raise LineError("invalid_pattern_anchor_selection", "请按时间顺序选择3个或5个不同的 K 线锚点。")
    candles, metadata = closed_daily(rows, symbol=symbol, interval=interval, source_interval=source_interval,
                                     interval_value=interval_value, provider=provider, now=now)
    candles = candles[-4000:]
    if len(candles) < 35:
        raise LineError("insufficient_pattern_history", "价格形态需要至少35根已收盘日线，未补取行情。")
    atr_values = talib.ATR(np.asarray([x["high"] for x in candles], dtype=float),
                           np.asarray([x["low"] for x in candles], dtype=float),
                           np.asarray([x["close"] for x in candles], dtype=float), timeperiod=14)
    pivot_events = _pivots(candles)
    alternating = []
    active = []
    results = []
    reasons = Counter()
    seen = set()
    active_boxes = {}
    for index, row in enumerate(candles):
        atr = float(atr_values[index])
        for pivot in pivot_events.get(index, ()):
            if alternating and alternating[-1]["side"] == pivot["side"]:
                if ((pivot["side"] == "high" and pivot["price"] > alternating[-1]["price"])
                        or (pivot["side"] == "low" and pivot["price"] < alternating[-1]["price"])):
                    alternating[-1] = pivot
                continue
            alternating.append(pivot)
            alternating = alternating[-5:]
            if not isfinite(atr) or atr <= 0:
                reasons["atr_unavailable"] += 1
                continue
            for size, prefix, side in ((3, "double", "high"), (5, "head_shoulders", "high"),
                                       (3, "double", "low"), (5, "head_shoulders", "low")):
                kind = prefix + ("_top" if side == "high" else "_bottom")
                if kind not in selected or len(alternating) < size:
                    continue
                anchors = alternating[-size:]
                if anchors[0]["side"] != side:
                    continue
                key = (kind, tuple(p["index"] for p in anchors))
                if key in seen:
                    continue
                seen.add(key)
                shape = _structure(kind, anchors, atr, candles, reasons)
                if shape is None:
                    continue
                item = {"type": kind, "anchors": [dict(p) for p in anchors], **shape,
                        "direction": "down" if side == "high" else "up", "atr": atr, "buffer": .25 * atr,
                        "available_at": row["time"], "available_index": index,
                        "as_of": metadata["as_of"], "status": "candidate", "events": [{"type": "candidate", "time": row["time"], "index": index}],
                        "pending_direction": None, "break_direction": None, "confirmed_at": None,
                        "confirmed_index": None, "invalidated_at": None, "reclaim_count": 0,
                        "followup_complete": False}
                active.append(item); results.append(item)
        if "platform" in selected and index >= min(DEFAULT_WINDOW_SIZES) - 1 and isfinite(atr) and atr > 0:
            proposed = range_candidates(candles[max(0, index - max(DEFAULT_WINDOW_SIZES) + 1):index + 1],
                                        window_sizes=DEFAULT_WINDOW_SIZES, limit=5)
            for box in proposed["candidates"]:
                key = (box["lower_price"], box["upper_price"])
                if key in active_boxes:
                    continue
                item = {"type": "platform", "anchors": [], "box": {k: box[k] for k in ("start_time", "end_time", "lower_price", "upper_price")},
                        "direction": None, "atr": atr, "buffer": .25 * atr,
                        "available_at": row["time"], "available_index": index, "as_of": metadata["as_of"],
                        "status": "candidate", "events": [{"type": "candidate", "time": row["time"], "index": index}], "pending_direction": None, "break_direction": None,
                        "confirmed_at": None, "confirmed_index": None, "invalidated_at": None,
                        "reclaim_count": 0, "followup_complete": False}
                active_boxes[key] = item; active.append(item); results.append(item)
        for item in active[:]:
            if index > item["available_index"]:
                _advance(item, row, index)
            if item["status"] in {"structurally_invalid", "expired", "breakout_failed"} or item["followup_complete"]:
                active.remove(item)
                if item["type"] == "platform":
                    active_boxes.pop((item["box"]["lower_price"], item["box"]["upper_price"]), None)
        if index > 300:
            results = [r for r in results if r["available_index"] >= index - 300]
    earliest = len(candles) - lookback_bars
    recent = [r for r in results if r["available_index"] >= earliest]
    if anchor_times is not None:
        recent = [r for r in recent if tuple(a["time"] for a in r["anchors"]) == anchor_times]
        if not recent: reasons["manual_selection_not_recognized"] += 1
    recent.sort(key=lambda r: (r["available_index"], r["type"], tuple(a["index"] for a in r["anchors"])), reverse=True)
    for item in recent:
        item["volume_evidence"] = _volume_evidence(candles, item, provider, volume_unit)
        item.pop("pending_direction", None); item.pop("reclaim_count", None)
        item.pop("confirmed_index", None); item.pop("available_index", None)
        item.pop("followup_complete", None)
    return {"rule_version": RULE_VERSION, "as_of": metadata["as_of"], "data_quality": metadata,
            "lookback_bars": lookback_bars, "loaded_bars": len(candles),
            "candidate_count": len(recent), "returned": min(len(recent), max_candidates),
            "truncated": len(recent) > max_candidates, "rejected_reasons": dict(reasons),
            "candidates": recent[:max_candidates], "drawing_created": False,
            "limitations": ["rule_based_geometry_not_trading_forecast"]}
