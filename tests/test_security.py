import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import analysis
import collector
from security import ManagedSheets, account_store, private_dir, protect_file, write_private, write_json, read_json


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_accounts_have_separate_histories(self):
        a = account_store(self.root / "data", "111")
        b = account_store(self.root / "data", "222")
        write_json(a / "stories_history.json", {"old": 17})
        self.assertEqual(read_json(b / "stories_history.json", {}), {})
        self.assertEqual(read_json(a / "stories_history.json"), {"old": 17})

    def test_legacy_data_stops_without_migration(self):
        write_json(self.root / "latest.json", {"old": True})
        with self.assertRaises(RuntimeError):
            account_store(self.root, "111")
        self.assertEqual(read_json(self.root / "latest.json"), {"old": True})

    def test_account_path_traversal_blocked(self):
        with self.assertRaises(ValueError):
            account_store(self.root, "../other")

    def test_private_files_from_creation_and_replacement(self):
        folder = private_dir(self.root / "data")
        dest = folder / "token.json"
        real_replace = os.replace
        def inspect(source, target):
            self.assertEqual(Path(source).stat().st_mode & 0o777, 0o600)
            real_replace(source, target)
        with patch("security.os.replace", side_effect=inspect):
            write_private(dest, "synthetic")
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        dest.chmod(0o644)
        protect_file(dest)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)

    def test_symlink_does_not_overwrite_target(self):
        target = self.root / "target"
        target.write_text("keep")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(RuntimeError):
            write_private(link, "overwrite")
        self.assertEqual(target.read_text(), "keep")

    def test_redirects_blocked(self):
        req = urllib.request.Request("https://graph.facebook.com/test", headers={"Authorization": "Bearer synthetic"})
        for url in ("https://other.invalid/", "http://graph.facebook.com/", "https://graph.facebook.com/else"):
            with self.assertRaises(RuntimeError):
                collector.NoRedirect().redirect_request(req, None, 302, "Found", {}, url)
        graph = collector.Graph("synthetic", "v24.0")
        self.assertTrue(any(isinstance(h, collector.NoRedirect) for h in graph.opener.handlers))

    def test_only_narrow_google_scope(self):
        self.assertEqual(collector.SCOPES, ["https://www.googleapis.com/auth/drive.file"])
        collector.check_google_scopes(collector.SCOPES)
        for old in (None, [], "drive.file", collector.SCOPES + ["https://www.googleapis.com/auth/spreadsheets"]):
            with self.assertRaises(RuntimeError):
                collector.check_google_scopes(old)

    def managed(self):
        raw = MagicMock()
        raw.spreadsheets().create().execute.return_value = {"spreadsheetId": "synthetic-book"}
        folder = account_store(self.root / "data", "111")
        return raw, ManagedSheets(raw, folder, "111")

    def test_cannot_adopt_existing_sheet(self):
        raw = MagicMock()
        with self.assertRaises(RuntimeError):
            ManagedSheets(raw, self.root, "111", "existing-book")
        raw.spreadsheets.assert_not_called()

    def test_account_or_spreadsheet_mismatch_stops(self):
        raw, managed = self.managed()
        for account, requested in (("222", ""), ("111", "different-book")):
            with self.assertRaises(RuntimeError):
                ManagedSheets(raw, managed.path.parent, account, requested)

    def test_owned_sheet_reused_without_creation(self):
        raw, managed = self.managed()
        raw.reset_mock()
        again = ManagedSheets(raw, managed.path.parent, "111")
        self.assertEqual(again.spreadsheet_id, "synthetic-book")
        raw.spreadsheets.assert_not_called()

    def test_same_title_different_id_cannot_write(self):
        raw, managed = self.managed()
        raw.spreadsheets().get().execute.return_value = {"sheets": [{"properties": {"title": "posts", "sheetId": 999}}]}
        with self.assertRaises(RuntimeError):
            collector.replace_values(managed, managed.spreadsheet_id, "posts", [["header"]])
        raw.spreadsheets().values.assert_not_called()

    def test_unmanaged_connection_cannot_write(self):
        raw = MagicMock()
        with self.assertRaises(RuntimeError):
            collector.replace_values(raw, "id", "posts", [["header"]])
        raw.spreadsheets.assert_not_called()

    def test_manual_chart_preserved(self):
        raw, managed = self.managed()
        managed.state["chart_ids"] = [80]
        dashboard = managed.state["tabs"]["ダッシュボード"]
        raw.spreadsheets().get().execute.return_value = {"sheets": [{"properties": {"title": "ダッシュボード", "sheetId": dashboard},
            "charts": [{"chartId": 80}, {"chartId": 99}]}]}
        raw.spreadsheets().batchUpdate().execute.return_value = {"replies": [{}, {"addChart": {"chart": {"chartId": 81}}}]}
        analysis.refresh_charts(managed, managed.spreadsheet_id, dashboard, 1, 0)
        requests = raw.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        deleted = [r["deleteEmbeddedObject"]["objectId"] for r in requests if "deleteEmbeddedObject" in r]
        self.assertEqual(deleted, [80])
        self.assertEqual(read_json(managed.path)["chart_ids"], [81])


if __name__ == "__main__":
    unittest.main()
