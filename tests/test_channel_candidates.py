import copy
import unittest
from unittest.mock import patch

from tools.channel_candidates import channel_candidates
from tools.lines import LineError


def trend_rows(direction, count=50):
    rows = []
    for index in range(count):
        if direction == "ascending":
            base = 100 + 0.5 * index
            low = base if index in (5, 25, 45) else base + 2
            high = low + (8 if index in (15, 35) else 6)
        else:
            base = 140 - 0.5 * index
            high = base if index in (5, 25, 45) else base - 2
            low = high - (8 if index in (15, 35) else 6)
        rows.append({"time": 1000 + index, "open": low + 3, "high": high,
                     "low": low, "close": high - 3, "volume": 1})
    return rows


class ChannelCandidateTests(unittest.TestCase):
    def test_ascending_candidates_are_read_only_and_reproducible(self):
        candles = trend_rows("ascending")
        original = copy.deepcopy(candles)
        first = channel_candidates(candles, direction="ascending")
        self.assertEqual(first, channel_candidates(candles, direction="ascending"))
        self.assertEqual(candles, original)
        self.assertFalse(first["drawing_created"])
        self.assertGreater(first["candidate_count"], 0)
        candidate = first["candidates"][0]
        self.assertEqual(candidate["direction"], "ascending")
        self.assertGreater(candidate["anchors"]["parallel"]["price"], candidate["anchors"]["from"]["price"])
        self.assertLess(candidate["anchors"]["from"]["time"], candidate["anchors"]["parallel"]["time"])
        self.assertLess(candidate["anchors"]["parallel"]["time"], candidate["anchors"]["to"]["time"])
        self.assertEqual(candidate["max_wick_excess_price"], 0)
        self.assertEqual(candidate["outside_bar_fraction"], 0)
        self.assertEqual(first["scope"], "current")
        self.assertLessEqual(candidate["bars_since_end"], first["thresholds"]["max_current_end_age_bars"])
        self.assertTrue(candidate["post_end"]["evaluated"])
        self.assertEqual(candidate["post_end"]["latest_close_position"], "inside")
        self.assertLessEqual(candidate["width_to_base_move"], 2)
        self.assertEqual(first["rule_version"], "confirmed_pivots_v3")

    def test_descending_and_direction_filter(self):
        candles = trend_rows("descending")
        result = channel_candidates(candles, direction="descending")
        self.assertGreater(result["candidate_count"], 0)
        self.assertTrue(all(item["slope_per_bar"] < 0 for item in result["candidates"]))
        self.assertEqual(channel_candidates(candles, direction="ascending")["candidate_count"], 0)

    def test_flat_or_unconfirmed_edge_does_not_become_a_trend_anchor(self):
        flat = trend_rows("ascending")
        for row in flat:
            offset = (row["time"] - 1000) * 0.5
            for field in ("open", "high", "low", "close"):
                row[field] -= offset
        self.assertEqual(channel_candidates(flat)["candidate_count"], 0)

        candles = trend_rows("ascending")
        candles[-1]["low"] = 1
        result = channel_candidates(candles, direction="ascending", scope="historical")
        self.assertGreater(result["candidate_count"], 0)
        self.assertTrue(all(anchor["time"] != candles[-1]["time"]
                            for candidate in result["candidates"] for anchor in candidate["anchors"].values()))

    def test_calendar_gaps_use_bar_index_and_lookback_is_bounded(self):
        candles = trend_rows("ascending")
        contiguous = channel_candidates(candles, direction="ascending", limit=1)
        gapped = copy.deepcopy(candles)
        for index, row in enumerate(gapped):
            row["time"] = 1000 + index * index
        after_gaps = channel_candidates(gapped, direction="ascending", limit=1)
        first = contiguous["candidates"][0]
        second = after_gaps["candidates"][0]
        self.assertEqual(first["slope_per_bar"], second["slope_per_bar"])
        self.assertEqual(first["width"], second["width"])
        self.assertEqual(first["span_bars"], second["span_bars"])
        self.assertEqual(after_gaps["returned"], 1)
        self.assertEqual(after_gaps["truncated"], after_gaps["candidate_count"] > 1)

        flat_tail = [{**row, "time": 2000 + index, "open": 105, "high": 110,
                      "low": 100, "close": 105} for index, row in enumerate(candles)]
        only_tail = channel_candidates(candles + flat_tail, direction="ascending", lookback_bars=60)
        self.assertEqual(only_tail["candidate_count"], 0)
        self.assertEqual(only_tail["no_candidate_reason"], "no_anchor_triple_passed_rules")
        self.assertIn("不能据此推断近期没有已确认拐点", only_tail["no_candidate_explanation"])
        self.assertIn("recent_confirmed_low_count", only_tail["pivot_scan"])

    def test_repeated_small_boundary_breaches_are_not_a_clean_channel(self):
        candles = []
        for index in range(40):
            base = 100 + .5 * index
            candles.append({"time": 1000 + index, "open": base + 3, "high": base + 7,
                            "low": base, "close": base + 4, "volume": 1})
        candles[14]["high"] = 115
        pivots = {"candidates": [
            {"side": "low", "time": 1002, "price": 101},
            {"side": "high", "time": 1014, "price": 115},
            {"side": "low", "time": 1025, "price": 112.5},
        ], "candidate_count": 3, "total_candidates": 3, "truncated": False}
        for index in (4, 6, 8, 10, 12, 16):
            candles[index]["high"] = 100 + .5 * index + 9
        with patch("tools.channel_candidates.confirmed_pivots", return_value=pivots):
            rejected = channel_candidates(candles, direction="ascending", scope="historical")
        self.assertEqual(rejected["candidate_count"], 0)
        self.assertEqual(rejected["rejection_counts"]["too_many_anchor_interval_breaches"], 1)
        for index in (12, 16):
            candles[index]["high"] = 100 + .5 * index + 7
        with patch("tools.channel_candidates.confirmed_pivots", return_value=pivots):
            accepted = channel_candidates(candles, direction="ascending", scope="historical")
        self.assertEqual(accepted["candidate_count"], 1)
        self.assertLessEqual(accepted["candidates"][0]["outside_bar_fraction"], .20)

    def test_similar_historical_geometry_shares_one_result_slot(self):
        result = channel_candidates(trend_rows("ascending"), direction="ascending", scope="historical", limit=5)
        self.assertEqual(result["qualified_before_dedup"], 3)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["deduplicated_count"], 1)
        self.assertEqual({item["anchors"]["parallel"]["time"] for item in result["candidates"]},
                         {1015, 1035})

    def test_rejects_invalid_config_and_short_history(self):
        candles = trend_rows("ascending")
        for kwargs, code in [({"direction": "up"}, "invalid_channel_candidate_direction"),
                             ({"direction": []}, "invalid_channel_candidate_direction"),
                             ({"scope": "recentish"}, "invalid_channel_candidate_scope"),
                             ({"scope": []}, "invalid_channel_candidate_scope"),
                             ({"lookback_bars": True}, "invalid_channel_candidate_lookback"),
                             ({"left_bars": True}, "invalid_pivot_window"),
                             ({"min_span_bars": 0}, "invalid_channel_candidate_span"),
                             ({"limit": 6}, "invalid_channel_candidate_limit")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(LineError) as error:
                channel_candidates(candles, **kwargs)
            self.assertEqual(error.exception.code, code)
        with self.assertRaises(LineError) as error:
            channel_candidates(candles[:5])
        self.assertEqual(error.exception.code, "insufficient_channel_candidate_history")
        malformed = copy.deepcopy(candles)
        malformed[20]["high"] = malformed[20]["low"] - 1
        with self.assertRaises(LineError) as error:
            channel_candidates(malformed)
        self.assertEqual(error.exception.code, "invalid_channel_candidate_data")
        malformed = copy.deepcopy(candles)
        malformed[20]["low"] = 0
        with self.assertRaises(LineError) as error:
            channel_candidates(malformed)
        self.assertEqual(error.exception.code, "invalid_channel_candidate_data")

    def test_current_rejects_old_or_broken_channels_historical_is_explicit(self):
        old = trend_rows("ascending", count=60)
        current = channel_candidates(old, direction="ascending")
        self.assertEqual(current["candidate_count"], 0)
        self.assertGreater(current["rejection_counts"].get("end_anchor_too_old", 0), 0)
        historical = channel_candidates(old, direction="ascending", scope="historical")
        self.assertGreater(historical["candidate_count"], 0)
        self.assertFalse(historical["candidates"][0]["post_end"]["evaluated"])

        broken = trend_rows("ascending")
        broken[-1].update(open=150, close=150, high=151, low=149)
        result = channel_candidates(broken, direction="ascending")
        self.assertEqual(result["candidate_count"], 0)
        self.assertGreater(result["rejection_counts"].get("post_end_boundary_breach", 0), 0)
        self.assertGreater(channel_candidates(broken, direction="ascending", scope="historical")["candidate_count"], 0)

    def test_broad_geometric_envelope_does_not_rank_as_trend_channel(self):
        broad = trend_rows("ascending")
        for row in broad:
            row["high"] += 12
            row["close"] += 6
        result = channel_candidates(broad, direction="ascending", scope="historical")
        self.assertEqual(result["candidate_count"], 0)
        self.assertTrue(result["rejection_counts"].get("too_wide_vs_price", 0)
                        or result["rejection_counts"].get("too_wide_vs_base_move", 0))


if __name__ == "__main__":
    unittest.main()
