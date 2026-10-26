import unittest
from pydantic import ValidationError

from tools.annotations import edit_annotation
from tools.chart_edits import ChartEdit, edit_parameters, snapshot_inventory
from tools.drawing_verification import verify_drawings
from tools.lines import LineError


class IconAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "symbol": "601899.XSHG", "interval": "day",
            "chartCommands": [{"type": "SET_CANDLES", "rows": [{"time": 1792134000, "open": 31, "high": 32, "low": 30, "close": 31.5}]}],
        }

    def test_icon_create_update_delete_and_inventory_are_deterministic(self):
        edit = ChartEdit.model_validate({"kind": "icon_annotation", "action": "create", "anchor_time": "2026-10-16",
            "anchor_price": 31.2, "annotation_icon": "arrow_up", "name": "买入观察", "color": "blue"})
        params = edit_parameters(edit)
        self.assertEqual(params["annotation_icon"], "arrow_up")
        params["icon"] = params.pop("annotation_icon")  # prepare_chart_edit's field mapping
        created, obj = edit_annotation(self.payload, "create", **params, kind=edit.kind, request_id="icon-create")
        self.assertEqual(obj["icon"], "arrow_up")
        self.assertEqual(obj["time"], 1792134000)
        self.assertEqual(obj["color"], "info")

        updated, moved = edit_annotation(created, "update", kind="icon_annotation", annotation_id=obj["id"],
            anchor_price=31.4, icon="diamond", color="success")
        self.assertEqual(moved["icon"], "diamond")
        self.assertEqual(moved["time"], obj["time"])
        self.assertEqual(moved["price"], 31.4)
        self.assertEqual(moved["color"], "success")

        inventory = snapshot_inventory(updated)
        self.assertEqual(len(inventory), 1)
        self.assertEqual((inventory[0]["kind"], inventory[0]["icon"]), ("icon_annotation", "diamond"))
        result = verify_drawings(updated, [{"kind": "icon_annotation", "id": obj["id"], "time": "2026-10-16",
            "price": 31.4, "icon": "diamond", "name": "买入观察", "color": "success"}])
        self.assertTrue(result["matches"])

        deleted, _ = edit_annotation(updated, "delete", kind="icon_annotation", annotation_id=obj["id"])
        self.assertEqual(snapshot_inventory(deleted), [])
        self.assertEqual(len(deleted["chartCommands"]), 1)  # candle data is preserved

    def test_unsupported_icon_and_cross_kind_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ChartEdit.model_validate({"kind": "icon_annotation", "action": "create", "anchor_time": "2026-10-16",
                "anchor_price": 31.2, "annotation_icon": "emoji_star"})
        with self.assertRaises(LineError):
            edit_annotation(self.payload, "create", kind="icon_annotation", anchor_time="2026-10-16",
                anchor_price=31.2, icon="arrow_up", text="not allowed")


if __name__ == "__main__":
    unittest.main()
