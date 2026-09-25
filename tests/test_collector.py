import unittest
from unittest.mock import MagicMock, patch
import collector


class WriteTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("collector.ensure_sheet", return_value=1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def service(self, old, check):
        service = MagicMock()
        service.spreadsheets().get().execute.return_value = {"sheets": [{"properties": {"title": "posts"}}]}
        api = service.spreadsheets().values()
        api.get().execute.side_effect = [{"values": old}, {"values": check}]
        return service, api

    def test_foreign_header_not_overwritten(self):
        service, api = self.service([["private"]], [])
        with self.assertRaises(RuntimeError):
            collector.replace_values(service, "id", "posts", [["header"], [1]])
        api.update.assert_not_called()
        api.clear.assert_not_called()

    def test_only_stale_owned_cells_cleared(self):
        rows = [["header", "metric"], ["id", None]]
        service, api = self.service([["header", "metric"], ["old", 1], ["stale", 2]], [["header", "metric"], ["id"]])
        collector.replace_values(service, "id", "posts", rows)
        self.assertEqual(api.clear.call_args.kwargs["range"], "'posts'!A3:B3")

    def test_corrupt_readback_does_not_clear(self):
        service, api = self.service([["header"], [1], [2]], [["header"], [999]])
        with self.assertRaises(RuntimeError):
            collector.replace_values(service, "id", "posts", [["header"], [1]])
        api.clear.assert_not_called()

    def test_auth_error_not_hidden(self):
        graph = MagicMock()
        graph.get.side_effect = RuntimeError("auth failed")
        with self.assertRaises(RuntimeError):
            collector.insights(graph, "id", False)

    def test_pagination_does_not_follow_foreign_url(self):
        graph = collector.Graph("secret", "v24.0")
        with patch.object(graph, "get", side_effect=[
            {"data": [], "paging": {"next": "https://example.invalid/secret", "cursors": {"after": "cursor"}}},
            {"data": [{"id": "1"}]},
        ]) as get:
            self.assertEqual(graph.paged("id/media"), [{"id": "1"}])
            self.assertEqual(get.call_args.args, ("id/media",))


if __name__ == "__main__":
    unittest.main()
