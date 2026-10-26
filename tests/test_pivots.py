import unittest

from tools.lines import LineError
from tools.pivots import confirmed_pivots


def rows(highs, lows=None):
    lows = lows if lows is not None else [value - 1 for value in highs]
    return [{"time": 1000 + index, "open": 1, "high": high, "low": low,
             "close": 1, "volume": 1} for index, (high, low) in enumerate(zip(highs, lows))]


class ConfirmedPivotTests(unittest.TestCase):
    def test_equal_neighbor_extrema_are_excluded_and_right_edge_is_unconfirmed(self):
        data = rows([1, 3, 3, 2, 1, 5, 4, 9], [0, 1, 1, 2, 3, 0, 2, 1])
        result = confirmed_pivots(data, left_bars=1, right_bars=1, mode="both", limit=20)
        self.assertEqual(result["candidates"], [
            {"side": "high", "time": "1005", "price": 5.0, "bars_ago": 2},
            {"side": "low", "time": "1005", "price": 0.0, "bars_ago": 2},
        ])
        self.assertEqual(result["total_candidates"], 2)
        self.assertFalse(result["truncated"])

    def test_candidate_limit_returns_newest_in_chronological_order(self):
        result = confirmed_pivots(rows([1, 5, 1, 6, 1, 7, 1, 8, 1]),
                                  left_bars=1, right_bars=1, mode="high", limit=2)
        self.assertEqual([item["price"] for item in result["candidates"]], [7.0, 8.0])
        self.assertEqual(result["total_candidates"], 4)
        self.assertTrue(result["truncated"])

    def test_short_or_invalid_inputs_fail_closed(self):
        with self.assertRaises(LineError) as error:
            confirmed_pivots(rows([1, 2]), left_bars=1, right_bars=1)
        self.assertEqual(error.exception.code, "insufficient_pivot_history")
        for args, code in [({"left_bars": True}, "invalid_pivot_window"),
                           ({"right_bars": 21}, "invalid_pivot_window"),
                           ({"mode": "latest"}, "invalid_pivot_mode"),
                           ({"limit": 51}, "invalid_pivot_limit")]:
            with self.subTest(args=args), self.assertRaises(LineError) as error:
                confirmed_pivots(rows([1, 2, 1]), **args)
            self.assertEqual(error.exception.code, code)


if __name__ == "__main__":
    unittest.main()
