from datetime import date, datetime, timedelta, timezone
import unittest

from tools.lines import LineError
from tools.regression_channels import regression_channel


def rows_for(closes):
    first = date(2026, 1, 1)
    rows = []
    for index, close in enumerate(closes):
        stamp = int(datetime.combine(first + timedelta(days=index), datetime.min.time(),
                                     timezone(timedelta(hours=8))).timestamp())
        rows.append({"time": stamp, "open": close, "high": close + 1, "low": close - 1,
                     "close": close, "volume": 1})
    return rows


class RegressionChannelTests(unittest.TestCase):
    def test_known_linear_series_has_exact_center_and_zero_width(self):
        rows = rows_for([10 + index * 2 for index in range(12)])
        result = regression_channel(rows, start_time=rows[0]["time"], end_time=rows[-1]["time"])
        self.assertEqual(result["bar_count"], 12)
        self.assertAlmostEqual(result["slope_per_bar"], 2)
        self.assertAlmostEqual(result["regression_start_price"], 10)
        self.assertAlmostEqual(result["regression_end_price"], 32)
        self.assertEqual(result["residual_stddev_population"], 0)
        self.assertEqual(result["upper_end_price"], result["regression_end_price"])
        self.assertEqual(result["lower_end_price"], result["regression_end_price"])
        self.assertEqual(result["r_squared"], 1)

    def test_residual_band_and_multiplier_are_explicit_and_deterministic(self):
        residuals = [-.2, .2, 0, 0, 0, 0, 0, 0, 0, 0, .2, -.2]
        closes = [20 + index * .5 + residuals[index] for index in range(12)]
        rows = rows_for(closes)
        result = regression_channel(rows, start_time=rows[0]["time"], end_time=rows[-1]["time"], multiplier=2)
        repeated = regression_channel(rows, start_time=rows[0]["time"], end_time=rows[-1]["time"], multiplier=2)
        self.assertEqual(result, repeated)
        self.assertAlmostEqual(result["slope_per_bar"], .5)
        expected_stddev = (0.16 / 12) ** .5
        self.assertAlmostEqual(result["residual_stddev_population"], expected_stddev)
        self.assertAlmostEqual(result["channel_width"], 2 * expected_stddev)
        self.assertAlmostEqual(result["upper_start_price"], result["regression_start_price"] + 2 * expected_stddev)
        self.assertAlmostEqual(result["lower_end_price"], result["regression_end_price"] - 2 * expected_stddev)
        self.assertEqual(result["direction"], "ascending")

    def test_rejects_missing_reversed_short_and_invalid_ranges(self):
        rows = rows_for([30 + index for index in range(12)])
        with self.assertRaisesRegex(LineError, "当前已加载K线"):
            regression_channel(rows, start_time=rows[0]["time"] - 1, end_time=rows[-1]["time"])
        with self.assertRaisesRegex(LineError, "起点必须早于终点"):
            regression_channel(rows, start_time=rows[-1]["time"], end_time=rows[0]["time"])
        with self.assertRaisesRegex(LineError, "至少需要10根"):
            regression_channel(rows, start_time=rows[0]["time"], end_time=rows[8]["time"])
        with self.assertRaisesRegex(LineError, "不足10根"):
            regression_channel(rows[:9], start_time=rows[0]["time"], end_time=rows[8]["time"])
        with self.assertRaisesRegex(LineError, "multiplier"):
            regression_channel(rows, start_time=rows[0]["time"], end_time=rows[-1]["time"], multiplier=0)


if __name__ == "__main__":
    unittest.main()
