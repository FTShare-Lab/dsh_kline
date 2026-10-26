import unittest

from tools.price_series import PriceCondition, PriceSource
from tools.price_sticks import calculate_price_sticks, edit_price_sticks, validate_stick_values
from tools.lines import LineError
from test_channels import chart


class PriceStickCalculationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"time": index + 1, "open": close - 0.5, "high": close + 1,
                      "low": close - 1, "close": close, "volume": 1}
                     for index, close in enumerate((4, 6, 4, 6, 4, 6))]

    def test_condition_is_per_bar_and_keeps_paired_gaps(self):
        condition = PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 5})
        result = calculate_price_sticks(self.rows, PriceSource(kind="high"), PriceSource(kind="low"), condition)
        self.assertEqual(result["start_values"], [None, 7, None, 7, None, 7])
        self.assertEqual(result["end_values"], [None, 5, None, 5, None, 5])
        self.assertEqual(result["summary"]["matched_bars"], 3)

    def test_warmup_and_crossed_endpoints_are_not_silently_reordered(self):
        result = calculate_price_sticks(self.rows, PriceSource(kind="low"), PriceSource(kind="sma", period=3))
        self.assertEqual(result["start_values"][:2], [None, None])
        self.assertEqual(result["end_values"][2], 4.666667)
        self.assertLess(result["start_values"][2], result["end_values"][2])

    def test_zero_matches_is_only_a_read_only_result(self):
        condition = PriceCondition(left={"kind": "close"}, op="gt", right={"constant": 100})
        result = calculate_price_sticks(self.rows, PriceSource(kind="open"), PriceSource(kind="close"), condition)
        self.assertEqual(result["start_values"], [None] * len(self.rows))
        self.assertEqual(result["end_values"], [None] * len(self.rows))
        self.assertTrue(result["summary"]["empty"])
        self.assertFalse(result["summary"]["drawing_created"])

    def test_equal_endpoints_are_omitted_and_not_counted_as_visible_sticks(self):
        result = calculate_price_sticks(self.rows, PriceSource(kind="close"), PriceSource(kind="close"))
        self.assertTrue(result["summary"]["empty"])
        self.assertEqual(result["summary"]["equal_endpoints_skipped"], len(self.rows))
        with self.assertRaises(LineError):
            validate_stick_values(result["start_values"], result["end_values"], len(self.rows))

    def test_editor_keeps_one_id_and_other_shapes_unchanged(self):
        original = chart()
        created, obj = edit_price_sticks(original, "create", start_source={"kind": "high"},
            end_source={"kind": "low"}, start_values=[36, None, 36, 36],
            end_values=[28, None, 28, 28], name="高低柱线", request_id="A")
        self.assertEqual(created["chartCommands"][:-1], original["chartCommands"])
        self.assertEqual(obj["bar_count"], 4)
        self.assertRegex(obj["row_hash"], r"^[a-f0-9]{16}$")
        self.assertEqual(edit_price_sticks(original, "create", start_source={"kind": "high"},
            end_source={"kind": "low"}, start_values=[36, None, 36, 36],
            end_values=[28, None, 28, 28], name="高低柱线", request_id="A")[1], obj)
        changed, updated = edit_price_sticks(created, "update", sticks_id=obj["id"], color="warning")
        self.assertEqual(updated["id"], obj["id"])
        self.assertEqual(updated["sticks_hash"], obj["sticks_hash"])
        deleted, removed = edit_price_sticks(changed, "delete", sticks_id=obj["id"])
        self.assertEqual(removed, updated)
        self.assertEqual(deleted, original)


if __name__ == "__main__":
    unittest.main()
