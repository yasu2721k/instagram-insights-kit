#!/usr/bin/env python3
"""Collect Instagram insights and write isolated raw-data tabs in Google Sheets."""

from __future__ import annotations

import json
import os
import re
import fcntl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from security import ManagedSheets, account_store, private_dir, protect_file, read_json, write_json, write_private


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in protect_file(ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


def log(message: str) -> None:
    private_dir(LOGS)
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}"
    path = protect_file(LOGS / "collector.log")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line)


class UnsupportedMetric(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("HTTP redirects are not permitted")


class Graph:
    def __init__(self, token: str, version: str) -> None:
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
            raise ValueError("Invalid Meta API version")
        self.token = token
        self.base = f"https://graph.facebook.com/{version}/"
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                try:
                    code = json.loads(exc.read()).get("error", {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                if code == 100 and path.endswith("/insights"):
                    raise UnsupportedMetric("Meta metric unavailable (code 100)") from None
                if attempt == 2 or exc.code < 500:
                    raise RuntimeError(f"Meta API HTTP {exc.code}, code={code}; check authorization locally") from None
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt == 2:
                    raise RuntimeError("Meta API connection failed") from None
            time.sleep(3 * (attempt + 1))
        raise AssertionError("unreachable")

    def paged(self, path: str, **params: Any) -> list[dict[str, Any]]:
        page = self.get(path, **params)
        rows = list(page.get("data", []))
        while page.get("paging", {}).get("next"):
            cursor = page.get("paging", {}).get("cursors", {}).get("after")
            if not cursor or cursor == params.get("after"):
                raise RuntimeError("Meta pagination cursor missing or repeated")
            params["after"] = cursor
            page = self.get(path, **params)
            rows.extend(page.get("data", []))
        return rows


def insights(graph: Graph, media_id: str, is_reel: bool) -> dict[str, Any]:
    candidates = (
        ["reach,saved,shares,total_interactions,views,ig_reels_avg_watch_time", "reach,saved,shares,views"]
        if is_reel else ["reach,saved,shares,total_interactions,views", "reach,saved,shares"]
    )
    for metrics in candidates:
        try:
            payload = graph.get(f"{media_id}/insights", metric=metrics)
            return {item["name"]: item.get("values", [{}])[0].get("value") for item in payload.get("data", [])}
        except UnsupportedMetric:
            continue
    return {"_unavailable": True}


def account_metric(graph: Graph, account_id: str, metric_names: list[str]) -> Any:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    params = {
        "metric": ",".join(metric_names),
        "period": "day",
        "since": int((now - timedelta(days=1)).timestamp()),
        "until": int(now.timestamp()),
    }
    for total_value in (False, True):
        try:
            request = dict(params)
            if total_value:
                request["metric_type"] = "total_value"
            payload = graph.get(f"{account_id}/insights", **request)
            for item in payload.get("data", []):
                if item.get("name") not in metric_names:
                    continue
                if "total_value" in item:
                    return item["total_value"].get("value", "")
                values = item.get("values", [])
                if values:
                    return values[-1].get("value", "")
        except UnsupportedMetric:
            continue
    return ""


def check_google_scopes(scopes):
    if not isinstance(scopes, (list, tuple, set)) or set(scopes) != set(SCOPES):
        raise RuntimeError("Old or unknown Google scopes; revoke old grant and reauthorize in a fresh kit folder")


def google_service(env: dict[str, str]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    credentials_path = protect_file(ROOT / env.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
    token_path = protect_file(ROOT / env.get("GOOGLE_TOKEN_FILE", "token.json"))
    creds = None
    if token_path.exists():
        saved = read_json(token_path)
        check_google_scopes(saved.get("scopes"))
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if "--non-interactive" in sys.argv:
                raise RuntimeError("Google consent required; run collector manually")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        check_google_scopes(creds.granted_scopes or creds.scopes)
        write_private(token_path, creds.to_json())
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    if not isinstance(service, ManagedSheets):
        raise RuntimeError("Managed Sheets connection required")
    return service.tab(spreadsheet_id, title)


def replace_values(service, spreadsheet_id: str, title: str, rows: list[list[Any]]) -> None:
    if not rows or not rows[0]:
        raise ValueError("A nonempty header is required")
    width = max(map(len, rows))
    def column(n):
        result = ""
        while n:
            n, remainder = divmod(n - 1, 26)
            result = chr(65 + remainder) + result
        return result
    quoted = "'" + title.replace("'", "''") + "'"
    ensure_sheet(service, spreadsheet_id, title)
    api = service.spreadsheets().values()
    old = api.get(spreadsheetId=spreadsheet_id, range=f"{quoted}!A:{column(width)}",
                  valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if old and old[0] != rows[0]:
        raise RuntimeError(f"Existing sheet header differs; refusing overwrite: {title}")
    normalized = [["" if x is None else x for x in row] + [""] * (width - len(row)) for row in rows]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{quoted}!A1",
        valueInputOption="RAW",
        body={"values": normalized},
    ).execute()
    check = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"{quoted}!A1:{column(width)}{len(rows)}",
        valueRenderOption="UNFORMATTED_VALUE"
    ).execute().get("values", [])
    padded = [row + [""] * (width - len(row)) for row in check]
    padded += [[""] * width for _ in range(len(rows) - len(padded))]
    if padded != normalized:
        raise RuntimeError(f"Google Sheets read-back failed: {title}")
    if len(old) > len(rows):
        api.clear(spreadsheetId=spreadsheet_id,
                  range=f"{quoted}!A{len(rows)+1}:{column(width)}{len(old)}", body={}).execute()


def main() -> None:
    private_dir(DATA)
    lock_path = protect_file(DATA / ".collector.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        collect()


def collect() -> None:
    env = load_env()
    token = env.get("IG_ACCESS_TOKEN")
    account_id = env.get("IG_BUSINESS_ACCOUNT_ID")
    if not token or not account_id:
        raise SystemExit(".env のIG_ACCESS_TOKENとIG_BUSINESS_ACCOUNT_IDを設定してください")
    data = account_store(DATA, account_id)
    ownership = read_json(data / "ownership.json")
    requested = env.get("GOOGLE_SPREADSHEET_ID", "")
    if requested and (not ownership or ownership.get("spreadsheet_id") != requested):
        raise RuntimeError("Unmanaged spreadsheet; leave ID empty for a new account")
    graph = Graph(token, env.get("META_API_VERSION", "v24.0"))

    profile = graph.get(account_id, fields="id,username,name,followers_count,follows_count,media_count")
    media = graph.paged(
        f"{account_id}/media",
        fields="id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink",
        limit=100,
    )
    if str(profile.get("id", "")) != str(account_id):
        raise RuntimeError("対象Instagramプロフィールを取得できませんでした")
    profile_views = account_metric(graph, account_id, ["profile_views"])
    link_clicks = account_metric(graph, account_id, ["profile_links_taps"])
    daily_reach = account_metric(graph, account_id, ["reach"])

    media_insights: dict[str, dict[str, Any]] = {}
    for item in media:
        media_insights[item["id"]] = insights(graph, item["id"], item.get("media_product_type") == "REELS")
        time.sleep(0.1)

    stories = graph.paged(
        f"{account_id}/stories", fields="id,timestamp,media_type,permalink", limit=100
    )
    story_records: list[dict[str, Any]] = []
    for item in stories:
        metric = {}
        try:
            payload = graph.get(f"{item['id']}/insights", metric="reach,replies,shares")
            metric = {entry["name"]: entry.get("values", [{}])[0].get("value") for entry in payload.get("data", [])}
        except UnsupportedMetric:
            metric = {"_unavailable": True}
        story_records.append({
            "timestamp": item.get("timestamp", ""), "media_type": item.get("media_type", ""),
            "reach": metric.get("reach", ""), "replies": metric.get("replies", ""),
            "shares": metric.get("shares", ""), "story_id": str(item["id"]),
            "permalink": item.get("permalink", ""),
        })

    snapshot = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "media": media,
        "media_insights": media_insights,
        "active_stories": stories,
    }
    write_json(data / "latest.json", snapshot)
    history_path = data / "stories_history.json"
    history = read_json(history_path, {})
    for record in story_records:
        history[record["story_id"]] = record
    write_json(history_path, history)
    story_rows = [["timestamp", "media_type", "reach", "replies", "shares", "story_id", "permalink"]]
    for record in sorted(history.values(), key=lambda row: row.get("timestamp", ""), reverse=True):
        story_rows.append([record.get(key, "") for key in (
            "timestamp", "media_type", "reach", "replies", "shares", "story_id", "permalink"
        )])

    daily_path = data / "account_daily.json"
    daily_history = read_json(daily_path, {})
    today = datetime.now().astimezone().date().isoformat()
    previous = [daily_history[day] for day in sorted(daily_history) if day < today]
    previous_followers = previous[-1].get("followers_count") if previous else None
    followers = profile.get("followers_count")
    delta = followers - previous_followers if isinstance(followers, int) and isinstance(previous_followers, int) else ""
    daily_history[today] = {
        "date": today, "followers_count": followers, "follower_delta": delta,
        "insights_window": "previous UTC calendar day",
        "reach": daily_reach, "profile_views": profile_views, "link_clicks": link_clicks,
        "media_count": profile.get("media_count", ""),
    }
    write_json(daily_path, daily_history)

    service = ManagedSheets(google_service(env), data, account_id, requested)
    spreadsheet_id = service.spreadsheet_id

    collected = snapshot["collected_at"]
    account_rows = [["collected_at", "username", "followers_count", "follows_count", "media_count", "account_id"], [
        collected, profile.get("username", ""), profile.get("followers_count", ""),
        profile.get("follows_count", ""), profile.get("media_count", ""), str(profile.get("id", "")),
    ]]
    post_rows = [["timestamp", "type", "reach", "saved", "shares", "views", "likes", "comments", "caption", "url", "media_id"]]
    for item in sorted(media, key=lambda row: row.get("timestamp", ""), reverse=True):
        metric = media_insights[item["id"]]
        post_rows.append([
            item.get("timestamp", ""), item.get("media_product_type") or item.get("media_type", ""),
            metric.get("reach", ""), metric.get("saved", ""), metric.get("shares", ""), metric.get("views", ""),
            item.get("like_count", ""), item.get("comments_count", ""), item.get("caption", ""),
            item.get("permalink", ""), str(item["id"]),
        ])
    partial = any(x.get("_unavailable") for x in media_insights.values()) or any(
        value == "" for value in (profile_views, link_clicks, daily_reach)
    ) or any(record["reach"] == "" for record in story_records)
    result = "PARTIAL" if partial else "OK"
    status_rows = [["collected_at", "account", "posts", "active_stories", "result"], [
        collected, f"@{profile.get('username', '')}", len(media), len(stories), result,
    ]]
    replace_values(service, spreadsheet_id, "account_latest", account_rows)
    replace_values(service, spreadsheet_id, "posts", post_rows)
    replace_values(service, spreadsheet_id, "stories_history", story_rows)
    from analysis import build_analysis
    build_analysis(service, spreadsheet_id, daily_history, media, media_insights)
    replace_values(service, spreadsheet_id, "collection_status", status_rows)
    write_json(data / "sync_success.json", {"account_id": account_id, "spreadsheet_id": spreadsheet_id,
                                         "collected_at": collected, "result": result})
    log(f"{result} posts={len(media)} stories={len(stories)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FAILED {type(exc).__name__}; inspect configuration locally; raw API errors suppressed")
        sys.exit(1)
