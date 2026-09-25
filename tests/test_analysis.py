"""Offline tests: no credentials, real data, or network calls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analysis


class AnalysisTests(unittest.TestCase):
    def test_missing_and_real_zero(self):
        for missing in (None, "", "unavailable", float("nan"), float("inf"), True):
            self.assertEqual(analysis.number(missing), "")
        self.assertEqual(analysis.number(0), 0)
        self.assertEqual(analysis.complete_sum([1, None]), "")
        self.assertEqual(analysis.complete_sum([]), "")
        self.assertEqual(analysis.complete_sum([0, 2]), 2)
        self.assertEqual(analysis.median([None, "", 0, 4]), 2)

    def test_save_rate_missing_inputs(self):
        cases = [({}, ""), ({"reach": 0, "saved": 1}, ""),
                 ({"reach": 10}, ""), ({"saved": 1}, ""),
                 ({"reach": 10, "saved": 0}, 0),
                 ({"reach": 10, "saved": 2}, 20)]
        for metrics, expected in cases:
            with self.subTest(metrics=metrics):
                post = analysis.post_records([{"id": "a"}], {"a": metrics})[0]
                self.assertEqual(post["save_rate"], expected)
                self.assertEqual(post["shares"], "")

    def test_chart_axes_and_header_ranges(self):
        for monthly_count in (0, 1, 3):
            for daily_count in (1, 5):
                requests = analysis.chart_requests(7, monthly_count, daily_count)
                daily = requests[-1]["addChart"]["chart"]["spec"]["basicChart"]
                self.assertEqual(daily["headerCount"], 1)
                source = daily["domains"][0]["domain"]["sourceRange"]["sources"][0]
                self.assertEqual(source["startRowIndex"], 10 + monthly_count)
                self.assertEqual(source["endRowIndex"], 11 + monthly_count + daily_count)
                if monthly_count:
                    monthly = requests[0]["addChart"]["chart"]["spec"]["basicChart"]
                    self.assertEqual([s["targetAxis"] for s in monthly["series"]],
                                     ["LEFT_AXIS", "RIGHT_AXIS"])

    def test_write_delegates_without_clear(self):
        service = MagicMock()
        rows = [["header"], [1]]
        with patch.object(analysis, "ensure_sheet", return_value=8), \
                patch("collector.replace_values") as replace:
            self.assertEqual(analysis.write(service, "book", "test", rows), 8)
        replace.assert_called_once_with(service, "book", "test", rows)
        service.spreadsheets.return_value.values.assert_not_called()

    def test_build_keeps_incomplete_totals_blank(self):
        service = MagicMock()
        service.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": []}
        tabs = {}

        def capture(_service, _book, title, rows):
            tabs[title] = rows
            return 7

        media = [{"id": "a", "timestamp": "2026-01-01T00:00:00Z"},
                 {"id": "b", "timestamp": "2026-01-02T00:00:00Z"}]
        with patch.object(analysis, "write", side_effect=capture), patch.object(analysis, "refresh_charts"):
            analysis.build_analysis(service, "book", {}, media,
                                    {"a": {"reach": 10, "saved": 0}, "b": {}})
        row = tabs["月次集計"][1]
        self.assertEqual(row[2], "")
        self.assertEqual(row[3], 10)
        self.assertEqual(row[4], "")
        self.assertEqual(row[5], 0)
        self.assertIn("月内ユニークリーチではない", row[-1])
        reach_rows = [row for row in tabs["ランキング"][1:] if row[0] == "リーチ上位"]
        self.assertEqual(len(reach_rows), 1)


if __name__ == "__main__":
    unittest.main()
