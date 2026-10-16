import asyncio
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch

import server
from tools.chart_context import read_chart_context
from tools.chart_measurements import measure_chart_region
from tools.lines import LineError
import test_chart_context as context_fixtures


def rows():
    values = [(31.50, 31.72, 31.16, 31.41, 177), (31.48, 31.70, 31.07, 31.30, 113),
              (31.39, 31.75, 31.18, 31.41, 133), (31.65, 31.77, 31.32, 31.41, 103)]
    return [dict(time=i + 1, open=o, high=h, low=l, close=c, volume=v) for i, (o, h, l, c, v) in enumerate(values)]


class ChartMeasurementTests(unittest.TestCase):
    def test_empty_intersection_does_not_determine_union_coverage(self):
        # R02's real counterexample: a broad body covers the entire reversed
        # candidate band, despite there being no price shared by every body.
        covered = [dict(time=i+1, open=o, close=c, low=1280, high=1310, volume=1)
                   for i, (o, c) in enumerate(((1304, 1292.3), (1289, 1297.4), (1297.99, 1299.52)))]
        # Same extrema/intersection diagnosis, but here that band IS uncovered.
        uncovered = [dict(row, open=1297.99, close=1304) if i == 0 else row.copy()
                     for i, row in enumerate(covered)]
        for source in (covered, uncovered):
            measured = measure_chart_region(source, "day", "1", "3")
            self.assertFalse(measured["body_overlap"]["exists"])
            self.assertIsNone(measured["body_overlap"]["lower_price"])
            self.assertEqual(measured["boundary_evidence"]["body_overlap"]["relation"], "empty")
            self.assertEqual(measured["boundary_evidence"]["body_overlap"]["lower_candidate"]["price"], 1297.99)
            self.assertEqual(measured["boundary_evidence"]["body_overlap"]["upper_candidate"]["price"], 1297.4)
        self.assertTrue(min(covered[0]["open"], covered[0]["close"]) < 1297.4 < 1297.99 <
                        max(covered[0]["open"], covered[0]["close"]))
        self.assertFalse(any(min(row["open"], row["close"]) <= 1297.7 <= max(row["open"], row["close"])
                             for row in uncovered))

    def test_real_case_extremum_dates_fields_and_empty_intersection_evidence(self):
        values = [
            ("2026-08-26", 1300, 1314.45, 1295, 1302.8),
            ("2026-08-27", 1304, 1305, 1288, 1292.3),
            ("2026-08-28", 1289, 1297.89, 1288, 1297.4),
            ("2026-08-31", 1297.99, 1305, 1286, 1299.52),
            ("2026-09-01", 1295, 1307.99, 1286.1, 1299.56),
            ("2026-09-02", 1302.8, 1303, 1291.2, 1297.5),
            ("2026-09-03", 1297.5, 1305, 1293.02, 1298.88),
        ]
        source = [dict(time=int(datetime.fromisoformat(day+"T15:00:00+08:00").timestamp()),
                       open=o, high=h, low=l, close=c, volume=1) for day, o, h, l, c in values]
        before = deepcopy(source)
        result = measure_chart_region(source, "day", "2026-08-26", "2026-09-03")
        evidence = result["boundary_evidence"]
        self.assertEqual(evidence["body_envelope"]["lower"]["date"], "2026-08-28")
        self.assertEqual(evidence["body_envelope"]["lower"]["source_fields"], ["open"])
        self.assertEqual(evidence["body_envelope"]["lower"]["price"], 1289)
        self.assertEqual(evidence["body_envelope"]["upper"]["date"], "2026-08-27")
        self.assertEqual(evidence["body_envelope"]["upper"]["source_fields"], ["open"])
        self.assertEqual(evidence["body_envelope"]["upper"]["price"], 1304)
        self.assertEqual(evidence["wick_envelope"]["lower"]["date"], "2026-08-31")
        self.assertEqual(evidence["wick_envelope"]["lower"]["source_fields"], ["low"])
        self.assertEqual(evidence["wick_envelope"]["upper"]["source_fields"], ["high"])
        overlap = evidence["body_overlap"]
        self.assertEqual(overlap["relation"], "empty")
        self.assertEqual(overlap["comparison"], "lower_greater_than_upper")
        self.assertEqual(overlap["lower_candidate"]["price"], 1300)
        self.assertEqual(overlap["lower_candidate"]["date"], "2026-08-26")
        self.assertEqual(overlap["upper_candidate"]["price"], 1297.4)
        self.assertEqual(overlap["upper_candidate"]["date"], "2026-08-28")
        self.assertEqual(overlap["upper_candidate"]["source_fields"], ["close"])
        self.assertIsNone(result["body_overlap"]["lower_price"])
        self.assertEqual(source, before)

    def test_intersection_range_point_and_tiny_empty_gap_are_not_conflated(self):
        source = [dict(time=1, open=30, close=33, low=20, high=40, volume=1),
                  dict(time=2, open=31, close=34, low=20, high=40, volume=1)]
        result = measure_chart_region(source, "day", "1", "2")
        self.assertEqual(result["boundary_evidence"]["body_overlap"]["relation"], "range")
        self.assertEqual(result["body_overlap"]["lower_price"], 31)
        self.assertEqual(result["body_overlap"]["upper_price"], 33)
        source[0]["close"] = 31
        result = measure_chart_region(source, "day", "1", "2")
        self.assertEqual(result["boundary_evidence"]["body_overlap"]["relation"], "point")
        self.assertTrue(result["body_overlap"]["exists"])
        self.assertFalse(result["body_overlap"]["has_positive_height"])
        source[1]["open"] = 31.00000001
        result = measure_chart_region(source, "day", "1", "2")
        self.assertEqual(result["boundary_evidence"]["body_overlap"]["relation"], "empty")
        self.assertFalse(result["body_overlap"]["exists"])

    def test_doji_ties_have_both_fields_first_bar_count_and_bounded_payload(self):
        source = [dict(time=i+1, open=31, close=31, low=30, high=32, volume=1,
                       secret="not copied") for i in range(4000)]
        result = measure_chart_region(source, "day", "1", "4000")
        evidence = result["boundary_evidence"]
        self.assertEqual(evidence["tie_policy"], "first_matching_bar_with_total_count")
        for key in ("lower", "upper"):
            witness = evidence["body_envelope"][key]
            self.assertEqual(witness["time"], 1)
            self.assertEqual(witness["source_fields"], ["open", "close"])
            self.assertEqual(witness["matched_bar_count"], 4000)
        self.assertEqual(evidence["body_overlap"]["relation"], "point")
        self.assertNotIn("not copied", json.dumps(result))
        self.assertLess(len(json.dumps(result)), 3500)

    def test_minute_witness_dates_and_iso_keep_exact_bar_times_across_utc_date(self):
        start, end = "2026-10-13T16:01:00+00:00", "2026-10-13T16:02:00+00:00"
        source = [dict(time=int(datetime.fromisoformat(t).timestamp()), open=o, close=c,
                       low=20, high=40, volume=1) for t, o, c in ((start,30,31),(end,31,32))]
        result = measure_chart_region(source, "minute", start, end)
        witness = result["boundary_evidence"]["body_envelope"]["lower"]
        self.assertEqual(witness["date"], "2026-10-14")
        self.assertEqual(witness["iso"], "2026-10-14T00:01:00+08:00")
        self.assertEqual(witness["time"], source[0]["time"])
        self.assertEqual(result["boundary_evidence"]["body_overlap"]["relation"], "point")

    def test_body_envelope_is_not_common_overlap_and_net_volume_is_not_monotonic(self):
        source = rows(); before = deepcopy(source)
        result = measure_chart_region(source, "day", "1", "4")
        self.assertEqual(result["wick_envelope"], {"lower_price": 31.07, "upper_price": 31.77})
        self.assertEqual(result["body_envelope"]["lower_price"], 31.30)
        self.assertEqual(result["body_envelope"]["upper_price"], 31.65)
        self.assertTrue(result["body_overlap"]["exists"])
        self.assertFalse(result["body_overlap"]["has_positive_height"])
        self.assertEqual(result["body_overlap"]["lower_price"], 31.41)
        self.assertEqual(result["body_overlap"]["upper_price"], 31.41)
        self.assertEqual(result["volume_changes"]["increasing_steps"], 1)
        self.assertFalse(result["volume_changes"]["strictly_decreasing"])
        self.assertLess(result["volume_changes"]["first_to_last_pct"], 0)
        self.assertEqual(result["pattern_classification"], "not_provided")
        self.assertEqual(source, before)

    def test_disjoint_bodies_have_no_common_region_and_doji_is_not_a_box(self):
        source = rows()
        source[0].update(open=30, close=30)
        result = measure_chart_region(source, "day", "1", "4")
        self.assertFalse(result["body_overlap"]["exists"])
        self.assertIsNone(result["body_overlap"]["lower_price"])
        single = measure_chart_region(source, "day", "1", "1")
        self.assertEqual(single["bar_count"], 1)
        self.assertFalse(single["body_overlap"]["has_positive_height"])
        self.assertIsNone(single["volume_changes"]["strictly_decreasing"])

    def test_volume_zero_equal_and_nonfinite_ratio_remain_unambiguous(self):
        source = rows()
        for row in source: row["volume"] = 0
        result = measure_chart_region(source, "day", "1", "4")
        self.assertIsNone(result["volume_changes"]["first_to_last_pct"])
        self.assertTrue(result["volume_changes"]["non_increasing"])
        self.assertFalse(result["volume_changes"]["strictly_decreasing"])
        self.assertEqual(result["volume_changes"]["equal_steps"], 3)
        source[0]["volume"] = 1e-300; source[-1]["volume"] = 1e300
        self.assertIsNone(measure_chart_region(source, "day", "1", "4")["volume_changes"]["first_to_last_pct"])

    def test_reverse_missing_and_oversized_regions_are_rejected_without_snapping(self):
        for start, end, code in [("4", "1", "invalid_measurement_range"), ("1", "9", "anchor_not_found")]:
            with self.assertRaises(LineError) as exc: measure_chart_region(rows(), "day", start, end)
            self.assertEqual(exc.exception.code, code)
        oversized = [{**rows()[0], "time": i + 1} for i in range(4001)]
        with self.assertRaises(LineError) as exc: measure_chart_region(oversized, "day", "1", "4001")
        self.assertEqual(exc.exception.code, "measurement_capacity")

    def test_live_measurement_is_independent_of_sampling_and_cannot_mutate_or_fetch(self):
        fixture = context_fixtures.ChartContextTests("test_loaded_and_viewport_ranges_sampling_and_read_only")
        fixture.setUp()
        try:
            fixture.record["state"]["candles"] = rows(); fixture.save()
            before = fixture.path.read_text()
            with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), patch("server.publish_chart", side_effect=AssertionError("no publish")):
                result = asyncio.run(server.get_chart_context(fixture.token, candle_scope="none", limit=1,
                    region_start_time="1", region_end_time="4")).structuredContent
            self.assertEqual(result["candles"], [])
            self.assertEqual(result["region_measurements"]["bar_count"], 4)
            self.assertEqual(result["region_measurements"]["body_envelope"]["upper_price"], 31.65)
            self.assertEqual(result["region_measurements"]["boundary_evidence"]["body_envelope"]["upper"]["time"], 4)
            self.assertEqual(result["region_measurements"]["boundary_evidence"]["body_overlap"]["relation"], "point")
            self.assertEqual(fixture.path.read_text(), before)
            with self.assertRaises(LineError): read_chart_context(fixture.token, region_start_time="1")
            fixture.record["state"]["state"] = "loading"; fixture.save()
            with self.assertRaises(LineError) as exc: read_chart_context(fixture.token, region_start_time="1", region_end_time="4")
            self.assertEqual(exc.exception.code, "chart_measurement_not_ready")
        finally: fixture.doCleanups()
