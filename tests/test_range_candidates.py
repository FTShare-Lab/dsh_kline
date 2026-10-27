import copy
import math
import unittest

from tools.lines import LineError
from tools.range_candidates import range_candidates


def sideways_rows(count=60):
    rows = []
    for index in range(count):
        close = 105 + 2 * math.sin(index * math.pi / 4)
        rows.append({
            "time": 1000 + index, "open": close, "close": close,
            "high": 110 if index % 8 in (1, 5) else 108,
            "low": 100 if index % 8 in (3, 7) else 102,
            "volume": 1,
        })
    return rows


class RangeCandidateTests(unittest.TestCase):
    def test_sideways_proposals_are_bounded_read_only_and_reproducible(self):
        candles = sideways_rows()
        original = copy.deepcopy(candles)
        first = range_candidates(candles)
        self.assertEqual(first, range_candidates(candles))
        self.assertEqual(candles, original)
        self.assertFalse(first["drawing_created"])
        self.assertGreater(first["candidate_count"], 0)
        self.assertEqual(first["returned"], 1)
        self.assertFalse(first["truncated"])
        self.assertEqual(first["duplicates_suppressed"], 3)
        self.assertTrue(all(item["accepted"] for item in first["evaluated_windows"]))
        for candidate in first["candidates"]:
            self.assertEqual(candidate["end_time"], candles[-1]["time"])
            self.assertEqual((candidate["lower_price"], candidate["upper_price"]), (100, 110))
            self.assertGreaterEqual(candidate["upper_touch_count"], 2)
            self.assertGreaterEqual(candidate["lower_touch_count"], 2)
            self.assertEqual(candidate["status"], "geometry_candidate_requires_review")

    def test_monotone_trend_single_spike_and_breakout_are_not_platforms(self):
        trend = []
        for index in range(60):
            close = 101.5 + index * .5
            trend.append({"time": 1000 + index, "open": close, "close": close,
                          "high": close + 1.5, "low": close - 1.5, "volume": 1})
        trend_result = range_candidates(trend)
        self.assertEqual(trend_result["candidate_count"], 0)
        self.assertTrue(all(not item["accepted"] for item in trend_result["evaluated_windows"]))

        drifting_closes = sideways_rows()
        for index, row in enumerate(drifting_closes):
            row["open"] = row["close"] = 102 + 6 * index / 59
        drift_result = range_candidates(drifting_closes)
        sixty_bar_check = next(item for item in drift_result["evaluated_windows"] if item["window_bars"] == 60)
        self.assertEqual(sixty_bar_check["reason"], "full_window_drift")

        spike = sideways_rows()
        for row in spike:
            row["high"] = 108
            row["low"] = 102
        spike[48]["high"] = 110
        spike[50]["low"] = 100
        spike_result = range_candidates(spike)
        self.assertEqual(spike_result["candidate_count"], 0)
        self.assertIn("insufficient_edge_touches", {item["reason"] for item in spike_result["evaluated_windows"]})

        breakout = sideways_rows()
        breakout[-1].update(open=135, close=137, high=140, low=132)
        result = range_candidates(breakout)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["no_candidate_reason"], "no_window_passed_rules")
        self.assertTrue(all(not item["accepted"] for item in result["evaluated_windows"]))

    def test_late_one_way_rebound_inside_old_envelope_is_not_current_platform(self):
        rebound = sideways_rows()
        for offset, row in enumerate(rebound[-10:]):
            close = 103 + 6 * offset / 9
            row["open"] = close
            row["close"] = close
            row["high"] = max(row["high"], close + .5)
        result = range_candidates(rebound)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["no_candidate_reason"], "no_window_passed_rules")
        self.assertIn("recent_directional_move", {item["reason"] for item in result["evaluated_windows"]})

    def test_calendar_gaps_change_times_not_price_geometry(self):
        rows = sideways_rows()
        before = range_candidates(rows, limit=1)["candidates"][0]
        gapped = copy.deepcopy(rows)
        for index, row in enumerate(gapped):
            row["time"] = 1000 + index * index
        after = range_candidates(gapped, limit=1)["candidates"][0]
        for key in ("lower_price", "upper_price", "bar_count", "upper_touch_count",
                    "lower_touch_count", "close_drift_to_width", "fitted_close_drift_to_width"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["end_time"], gapped[-1]["time"])

    def test_bad_configuration_data_and_short_history_fail_closed(self):
        rows = sideways_rows()
        for kwargs, code in [({"window_sizes": [20, 20]}, "invalid_range_candidate_windows"),
                             ({"window_sizes": [True]}, "invalid_range_candidate_windows"),
                             ({"window_sizes": [15]}, "invalid_range_candidate_windows"),
                             ({"limit": 6}, "invalid_range_candidate_limit")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(LineError) as error:
                range_candidates(rows, **kwargs)
            self.assertEqual(error.exception.code, code)
        with self.assertRaises(LineError) as error:
            range_candidates(rows[:8])
        self.assertEqual(error.exception.code, "insufficient_range_candidate_history")
        invalid = copy.deepcopy(rows)
        invalid[30]["high"] = invalid[30]["low"] - 1
        with self.assertRaises(LineError) as error:
            range_candidates(invalid)
        self.assertEqual(error.exception.code, "invalid_range_candidate_data")


if __name__ == "__main__":
    unittest.main()
