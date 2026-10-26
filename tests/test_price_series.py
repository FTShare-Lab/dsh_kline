from copy import deepcopy
import unittest

from pydantic import ValidationError

from tools.lines import LineError
from tools.price_series import (PriceCondition, PriceSource, calculate_price_series,
                                candle_sequence_hash, edit_price_series, validate_series_values)
from tools.drawing_verification import verify_drawings
from test_channels import chart


class PriceSeriesTests(unittest.TestCase):
    def test_row_hash_matches_browser_binary_encoding(self):
        self.assertEqual(candle_sequence_hash([{"time": 1, "open": 31, "high": 33,
            "low": 30, "close": 32, "volume": 1}]), "e816167a8c64a8aa")

    def setUp(self):
        self.rows = []
        for index, close in enumerate((4, 6, 4, 6, 4, 6)):
            self.rows.append({"time": 1000 + index, "open": close, "high": close + 1,
                              "low": close - 1, "close": close, "volume": 1})

    def test_condition_gaps_do_not_join_across_false_bars(self):
        condition = PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 5})
        result = calculate_price_series(self.rows, PriceSource(kind="close"), condition)
        self.assertEqual(result["values"], [None, 6, None, 6, None, 6])
        self.assertEqual(result["summary"]["matched_bars"], 3)
        self.assertEqual(result["summary"]["segment_count"], 3)

    def test_sma_warmup_comparison_and_zero_matches(self):
        source = PriceSource(kind="sma", period=3)
        result = calculate_price_series(self.rows, source)
        self.assertEqual(result["values"][:2], [None, None])
        self.assertEqual(result["values"][2:], [4.666667, 5.333333, 4.666667, 5.333333])
        self.assertEqual(result["summary"]["segment_count"], 1)
        condition = PriceCondition(left={"kind": "sma", "period": 3}, op="gte",
                                   right={"source": {"kind": "close"}})
        compared = calculate_price_series(self.rows, PriceSource(kind="high"), condition)
        self.assertEqual(compared["values"], [None, None, 5, None, 5, None])
        self.assertEqual(compared["summary"]["segment_count"], 2)
        empty = calculate_price_series(self.rows, PriceSource(kind="close"),
            PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 100}))
        self.assertTrue(empty["summary"]["empty"])
        with self.assertRaises(LineError) as error:
            validate_series_values(empty["values"], len(self.rows))
        self.assertEqual(error.exception.code, "empty_price_series")

    def test_source_grammar_and_bounds(self):
        for invalid in ({"kind": "sma"}, {"kind": "sma", "period": 1},
                        {"kind": "close", "period": 5}, {"kind": "ema"},
                        {"kind": "sma", "period": 201}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PriceSource.model_validate(invalid)
        for invalid in ({"left": {"kind": "close"}, "op": "eq", "right": {"constant": 5}},
                        {"left": {"kind": "close"}, "op": "gt", "right": {"constant": 5, "source": {"kind": "low"}}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PriceCondition.model_validate(invalid)
        with self.assertRaises(LineError):
            calculate_price_series(self.rows * 667, PriceSource(kind="close"))

    def test_editor_one_object_stable_identity_and_other_shapes_unchanged(self):
        payload = chart()
        original = deepcopy(payload)
        first_values = [32, None, 32, 32]
        created, line = edit_price_series(payload, "create", source={"kind": "close"},
                                          values=first_values, name="收盘线", color="info", request_id="A")
        self.assertEqual(payload, original)
        self.assertEqual(created["chartCommands"][:-1], original["chartCommands"])
        self.assertEqual(line["bar_count"], 4)
        self.assertRegex(line["row_hash"], r"^[a-f0-9]{16}$")
        self.assertEqual(line["values"], first_values)
        retried, same = edit_price_series(created, "create", source={"kind": "close"},
                                          values=first_values, name="收盘线", color="info", request_id="A")
        self.assertEqual(retried, created)
        self.assertEqual(same, line)
        updated, changed = edit_price_series(created, "update", series_id=line["id"],
            source={"kind": "sma", "period": 2}, values=[None, 32, None, 32], color="success")
        self.assertEqual(changed["id"], line["id"])
        self.assertNotEqual(changed["series_hash"], line["series_hash"])
        self.assertEqual(changed["color"], "success")
        self.assertEqual(updated["chartCommands"][:-1], original["chartCommands"])
        verified = verify_drawings(updated, [{"kind": "series_line", "id": line["id"],
            "series_hash": changed["series_hash"], "bar_count": 4, "color": "success"}])
        self.assertTrue(verified["matches"])
        self.assertFalse(verified["render_verified"])
        deleted, removed = edit_price_series(updated, "delete", series_id=line["id"])
        self.assertEqual(removed, changed)
        self.assertEqual(deleted, original)


if __name__ == "__main__":
    unittest.main()
