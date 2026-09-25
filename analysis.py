#!/usr/bin/env python3
"""Build generic analysis tabs and charts from collected Instagram data."""

from __future__ import annotations

import statistics
import math
from collections import defaultdict
from datetime import datetime
from typing import Any


def number(value: Any) -> float | str:
    """Keep unavailable metrics blank; a genuine zero remains numeric."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return ""


def median(values: list[Any]) -> float | str:
    clean = [number(value) for value in values if number(value) != ""]
    return round(statistics.median(clean), 2) if clean else ""


def complete_sum(values: list[Any]) -> float | str:
    """Do not present a partial observed sum as a complete total."""
    clean = [number(value) for value in values]
    return sum(clean) if clean and all(value != "" for value in clean) else ""


def ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    from collector import ensure_sheet as managed_sheet
    return managed_sheet(service, spreadsheet_id, title)


def write(service, spreadsheet_id: str, title: str, rows: list[list[Any]]) -> int:
    from collector import replace_values

    sheet_id = ensure_sheet(service, spreadsheet_id, title)
    replace_values(service, spreadsheet_id, title, rows)
    requests = [
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.12, "green": 0.35, "blue": 0.55},
                                                         "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True}}},
                        "fields": "userEnteredFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0,
                                                   "endIndex": min(max(len(rows[0]), 1), 26)}}},
    ]
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
    return sheet_id


def parse_month(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%Y-%m")
    except ValueError:
        return timestamp[:7]


def post_records(media: list[dict[str, Any]], metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in media:
        metric = metrics.get(item["id"], {})
        reach = number(metric.get("reach"))
        saved = number(metric.get("saved"))
        records.append({
            "date": item.get("timestamp", "")[:10], "month": parse_month(item.get("timestamp", "")),
            "type": item.get("media_product_type") or item.get("media_type", ""),
            "reach": reach, "saved": saved,
            "save_rate": round(saved / reach * 100, 2) if reach != "" and reach > 0 and saved != "" else "",
            "shares": number(metric.get("shares")), "views": number(metric.get("views")),
            "likes": number(item.get("like_count")), "comments": number(item.get("comments_count")),
            "caption": (item.get("caption") or "").replace("\n", " ")[:120],
            "url": item.get("permalink", ""), "media_id": str(item["id"]),
        })
    return records


def chart_requests(sheet_id: int, monthly_count: int, daily_count: int) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = [{"deleteEmbeddedObject": {"objectId": object_id}} for object_id in []]
    if monthly_count:
        requests.append({"addChart": {"chart": {
            "spec": {"title": "投稿月別・取得時点累計リーチと保存率", "basicChart": {"chartType": "LINE", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
                "axis": [{"position": "BOTTOM_AXIS", "title": "投稿月"}, {"position": "LEFT_AXIS", "title": "投稿リーチ合計（重複あり）"},
                         {"position": "RIGHT_AXIS", "title": "保存率中央値（%）"}],
                "domains": [{"domain": {"sourceRange": {"sources": [{"sheetId": sheet_id, "startRowIndex": 8,
                    "endRowIndex": 9 + monthly_count, "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
                "series": [
                    {"series": {"sourceRange": {"sources": [{"sheetId": sheet_id, "startRowIndex": 8,
                        "endRowIndex": 9 + monthly_count, "startColumnIndex": 2, "endColumnIndex": 3}]}}, "targetAxis": "LEFT_AXIS"},
                    {"series": {"sourceRange": {"sources": [{"sheetId": sheet_id, "startRowIndex": 8,
                        "endRowIndex": 9 + monthly_count, "startColumnIndex": 4, "endColumnIndex": 5}]}}, "targetAxis": "RIGHT_AXIS"},
                ]}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": sheet_id, "rowIndex": 1, "columnIndex": 7},
                                               "widthPixels": 620, "heightPixels": 300}},
        }}})
    if daily_count:
        daily_start = 10 + monthly_count
        requests.append({"addChart": {"chart": {
            "spec": {"title": "フォロワー純増・プロフィール表示・リンククリック", "basicChart": {
                "chartType": "LINE", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
                "domains": [{"domain": {"sourceRange": {"sources": [{"sheetId": sheet_id, "startRowIndex": daily_start,
                    "endRowIndex": daily_start + 1 + daily_count, "startColumnIndex": 0, "endColumnIndex": 1}]}}}],
                "series": [{"series": {"sourceRange": {"sources": [{"sheetId": sheet_id, "startRowIndex": daily_start,
                    "endRowIndex": daily_start + 1 + daily_count, "startColumnIndex": col, "endColumnIndex": col + 1}]}}}
                    for col in (2, 4, 5)]}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": sheet_id, "rowIndex": 18, "columnIndex": 7},
                                               "widthPixels": 620, "heightPixels": 300}},
        }}})
    return requests


def build_analysis(service, spreadsheet_id: str, daily_history: dict[str, dict[str, Any]],
                   media: list[dict[str, Any]], metrics: dict[str, dict[str, Any]]) -> None:
    posts = post_records(media, metrics)
    post_rows = [["日付", "種別", "リーチ", "保存", "保存率%", "シェア", "再生数", "いいね", "コメント",
                  "キャプション", "URL", "media_id"]]
    post_rows += [[p[key] for key in ("date", "type", "reach", "saved", "save_rate", "shares", "views", "likes",
                                           "comments", "caption", "url", "media_id")] for p in posts]
    write(service, spreadsheet_id, "投稿分析", post_rows)

    daily_rows = [["日付", "フォロワー累計", "フォロワー純増", "リーチ", "プロフィール表示", "リンククリック", "投稿総数"]]
    for day, row in sorted(daily_history.items()):
        daily_rows.append([day, row.get("followers_count", ""), row.get("follower_delta", ""), row.get("reach", ""),
                           row.get("profile_views", ""), row.get("link_clicks", ""), row.get("media_count", "")])
    write(service, spreadsheet_id, "日次推移", daily_rows)

    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_month[post["month"]].append(post)
    monthly_rows = [["投稿月（取得時点累計）", "投稿数", "投稿リーチ合計（重複あり）", "リーチ中央値（取得済み）", "保存数", "保存率中央値%（取得済み）", "シェア数",
                     "リール数", "フィード数", "再生数", "集計の注意"]]
    for month, group in sorted(by_month.items()):
        monthly_rows.append([
            month, len(group), complete_sum([p["reach"] for p in group]), median([p["reach"] for p in group]),
            complete_sum([p["saved"] for p in group]), median([p["save_rate"] for p in group]),
            complete_sum([p["shares"] for p in group]), sum(p["type"] == "REELS" for p in group),
            sum(p["type"] != "REELS" for p in group), complete_sum([p["views"] for p in group]),
            "投稿月別の取得時点累計。月内ユニークリーチではない。合計は欠損があれば空欄、中央値は取得済みのみ",
        ])
    write(service, spreadsheet_id, "月次集計", monthly_rows)

    ranking_rows = [["ランキング", "順位", "日付", "種別", "リーチ", "保存率%", "シェア", "キャプション", "URL"]]
    for label, key in (("リーチ上位", "reach"), ("保存率上位", "save_rate"), ("シェア上位", "shares")):
        valid = [p for p in posts if p[key] != ""]
        for index, post in enumerate(sorted(valid, key=lambda row: number(row[key]), reverse=True)[:30], 1):
            ranking_rows.append([label, index, post["date"], post["type"], post["reach"], post["save_rate"],
                                 post["shares"], post["caption"], post["url"]])
    write(service, spreadsheet_id, "ランキング", ranking_rows)

    latest_daily = sorted(daily_history.values(), key=lambda row: row["date"])[-1] if daily_history else {}
    latest_month = monthly_rows[-1] if len(monthly_rows) > 1 else [""] * 10
    dashboard = [
        ["Instagram分析ダッシュボード", "現在値", "説明"],
        ["フォロワー", latest_daily.get("followers_count", ""), "最新取得値"],
        ["直近純増", latest_daily.get("follower_delta", ""), "前回日次との差"],
        ["プロフィール表示", latest_daily.get("profile_views", ""), "取得可能な直近日"],
        ["リンククリック", latest_daily.get("link_clicks", ""), "website_clicks / profile_links_taps"],
        ["最新投稿月リーチ合計", latest_month[2], f"{latest_month[0]}投稿の取得時点累計。月内ユニークリーチではなく投稿間の重複あり"],
        ["最新投稿月保存率中央値%", latest_month[5], "取得済み投稿のみ。合計は欠損があれば空欄、0とは区別"],
        [],
        ["投稿月", "投稿数", "投稿リーチ合計（取得時点累計）", "リーチ中央値（取得済み）", "保存率中央値%（取得済み）"],
    ]
    dashboard += [[row[0], row[1], row[2], row[3], row[5]] for row in monthly_rows[1:]]
    dashboard += [[], ["日付", "", "フォロワー純増", "", "プロフィール表示", "リンククリック"]]
    for row in daily_rows[1:]:
        dashboard.append([row[0], "", row[2], "", row[4], row[5]])
    dashboard_id = write(service, spreadsheet_id, "ダッシュボード", dashboard)
    refresh_charts(service, spreadsheet_id, dashboard_id, len(monthly_rows) - 1, len(daily_rows) - 1)


def refresh_charts(service, spreadsheet_id, dashboard_id, monthly_count, daily_count):
    ensure_sheet(service, spreadsheet_id, "ダッシュボード")
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties,sheets.charts.chartId").execute()
    delete_requests = []
    for item in meta.get("sheets", []):
        if item["properties"]["sheetId"] == dashboard_id:
            delete_requests = [{"deleteEmbeddedObject": {"objectId": chart["chartId"]}} for chart in item.get("charts", [])
                               if chart["chartId"] in service.state.get("chart_ids", [])]
    requests = delete_requests + chart_requests(dashboard_id, monthly_count, daily_count)
    if requests:
        response = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        service.state["chart_ids"] = [r["addChart"]["chart"]["chartId"] for r in response.get("replies", []) if "addChart" in r]
        service.save()
