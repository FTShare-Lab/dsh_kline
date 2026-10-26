from copy import deepcopy
import unittest

from tools.lines import LineError
from tools.price_bands import calculate_price_band, edit_price_band, validate_band_values
from tools.price_series import PriceCondition, PriceSource
from tools.drawing_verification import verify_drawings
from test_channels import chart


class PriceBandTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"time": index + 1, "open": close, "high": close + 1,
                      "low": close - 1, "close": close, "volume": 1}
                     for index, close in enumerate((4, 6, 4, 6, 4, 6))]

    def test_condition_gaps_and_sma_warmup(self):
        condition = PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 5})
        result = calculate_price_band(self.rows, PriceSource(kind="high"), PriceSource(kind="low"), condition)
        self.assertEqual(result["upper_values"], [None, 7, None, 7, None, 7])
        self.assertEqual(result["lower_values"], [None, 5, None, 5, None, 5])
        self.assertEqual(result["summary"]["segment_count"], 3)
        sma = calculate_price_band(self.rows, PriceSource(kind="high"), PriceSource(kind="sma", period=3))
        self.assertEqual(sma["upper_values"][:2], [None, None])
        self.assertEqual(sma["lower_values"][2], 4.666667)

    def test_crossed_edges_empty_and_bad_pairs_fail_closed(self):
        with self.assertRaises(LineError) as error:
            calculate_price_band(self.rows, PriceSource(kind="low"), PriceSource(kind="high"))
        self.assertEqual(error.exception.code, "invalid_price_band_order")
        empty = calculate_price_band(self.rows, PriceSource(kind="high"), PriceSource(kind="low"),
            PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 100}))
        self.assertTrue(empty["summary"]["empty"])
        with self.assertRaises(LineError) as error:
            validate_band_values(empty["upper_values"], empty["lower_values"], 6)
        self.assertEqual(error.exception.code, "empty_price_band")
        for upper, lower in [([None, 5], [3, 4]), ([3, 5], [4, 4]), ([float('nan'), 5], [2, 4])]:
            with self.subTest(upper=upper), self.assertRaises(LineError):
                validate_band_values(upper, lower, 2)

    def test_editor_is_one_object_and_preserves_other_commands(self):
        original = chart()
        upper, lower = [36, None, 36, 36], [28, None, 28, 28]
        first, obj = edit_price_band(original, "create", upper_source={"kind": "high"}, lower_source={"kind": "low"},
                                     upper_values=upper, lower_values=lower, name="价带", request_id="A")
        self.assertEqual(first["chartCommands"][:-1], original["chartCommands"])
        self.assertEqual(obj["bar_count"], 4)
        self.assertRegex(obj["row_hash"], r"^[a-f0-9]{16}$")
        self.assertEqual(edit_price_band(first, "create", upper_source={"kind": "high"}, lower_source={"kind": "low"},
                                         upper_values=upper, lower_values=lower, name="价带", request_id="A")[0], first)
        changed, new = edit_price_band(first, "update", band_id=obj["id"], color="success")
        self.assertEqual(new["id"], obj["id"])
        self.assertEqual(new["band_hash"], obj["band_hash"])
        self.assertTrue(verify_drawings(changed, [{"kind": "price_band", "id": obj["id"],
            "band_hash": obj["band_hash"], "bar_count": 4, "color": "success"}])["matches"])
        deleted, removed = edit_price_band(changed, "delete", band_id=obj["id"])
        self.assertEqual(removed, new)
        self.assertEqual(deleted, original)


if __name__ == "__main__": unittest.main()
