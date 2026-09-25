"""Private local storage and account-bound spreadsheet ownership."""
import json
import os
import re
import stat
import tempfile
from pathlib import Path


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError("Symlink storage is not allowed")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def protect_file(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError("Symlink files are not allowed")
    if path.exists():
        if not stat.S_ISREG(path.stat().st_mode):
            raise RuntimeError("Regular file required")
        path.chmod(0o600)
    return path


def write_private(path, text):
    path = protect_file(path)
    fd, temp = tempfile.mkstemp(prefix=".private-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path, default=None):
    path = protect_file(path)
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    write_private(path, json.dumps(data, ensure_ascii=False, indent=2))


def account_store(root, account_id):
    if not re.fullmatch(r"[0-9]+", account_id):
        raise ValueError("Numeric Instagram account ID required")
    root = private_dir(root)
    # Never guess the owner of legacy, unbound histories.
    if any((root / name).exists() for name in ("latest.json", "stories_history.json", "account_daily.json")):
        raise RuntimeError("Legacy unbound data found; use a fresh kit folder")
    folder = private_dir(root / account_id)
    for file in folder.iterdir():
        protect_file(file)
    return folder


TITLES = ["account_latest", "posts", "stories_history", "collection_status",
          "投稿分析", "日次推移", "月次集計", "ランキング", "ダッシュボード"]


class ManagedSheets:
    def __init__(self, service, folder, account_id, requested_id=""):
        self.service = service
        self.path = folder / "ownership.json"
        self.state = read_json(self.path)
        if self.state:
            if self.state.get("account_id") != account_id:
                raise RuntimeError("Account ownership mismatch")
            if requested_id and requested_id != self.state.get("spreadsheet_id"):
                raise RuntimeError("Spreadsheet ownership mismatch")
        else:
            if requested_id:
                raise RuntimeError("Existing spreadsheets cannot be adopted")
            tabs = [{"properties": {"sheetId": i + 1, "title": title}} for i, title in enumerate(TITLES)]
            result = service.spreadsheets().create(body={"properties": {"title": "Instagram Insights"},
                "sheets": tabs}, fields="spreadsheetId").execute()
            self.state = {"account_id": account_id, "spreadsheet_id": result["spreadsheetId"],
                          "tabs": {t: i + 1 for i, t in enumerate(TITLES)}, "chart_ids": []}
            self.save()
        self.spreadsheet_id = self.state["spreadsheet_id"]

    def save(self):
        write_json(self.path, self.state)

    def spreadsheets(self):
        return self.service.spreadsheets()

    def tab(self, spreadsheet_id, title):
        if spreadsheet_id != self.spreadsheet_id or title not in self.state["tabs"]:
            raise RuntimeError("Unmanaged spreadsheet or tab")
        expected = self.state["tabs"][title]
        meta = self.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
        if not any(s["properties"].get("title") == title and s["properties"].get("sheetId") == expected
                   for s in meta.get("sheets", [])):
            raise RuntimeError("Managed tab missing, renamed, or replaced")
        return expected
