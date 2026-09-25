#!/usr/bin/env python3
"""Install a macOS launchd job that runs four times per day."""

from __future__ import annotations

import plistlib
import argparse
import sys
import subprocess
from pathlib import Path
from collector import load_env
from security import account_store, read_json, private_dir, protect_file


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "bin" / "python"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


def write_job(label: str) -> Path:
    target = LAUNCH_AGENTS / f"{label}.plist"
    payload = {
        "Label": label,
        "ProgramArguments": [str(PYTHON), str(ROOT / "collector.py"), "--non-interactive"],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": [
            {"Hour": 7, "Minute": 30},
            {"Hour": 12, "Minute": 30},
            {"Hour": 18, "Minute": 30},
            {"Hour": 23, "Minute": 30},
        ],
        "StandardOutPath": str(ROOT / "logs" / f"{label}.out.log"),
        "StandardErrorPath": str(ROOT / "logs" / f"{label}.err.log"),
        "ProcessType": "Background",
        "Umask": 0o077,
    }
    with target.open("wb") as handle:
        plistlib.dump(payload, handle)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="初回同期後に明示して登録")
    args = parser.parse_args()
    if not args.apply:
        print("未登録。Macの現地時刻07:30 / 12:30 / 18:30 / 23:30に実行予定。初回同期確認後 --apply で登録")
        return
    if sys.platform != "darwin":
        raise SystemExit("macOS専用です")
    target = LAUNCH_AGENTS / "com.instagram-insights-kit.collect.plist"
    if target.exists():
        raise SystemExit("既存ジョブがあります。上書きせず内容を確認してください")
    env = load_env()
    account = env.get("IG_BUSINESS_ACCOUNT_ID", "")
    data = account_store(ROOT / "data", account)
    success = read_json(data / "sync_success.json", {})
    ownership = read_json(data / "ownership.json", {})
    if (not (ROOT / env.get("GOOGLE_TOKEN_FILE", "token.json")).exists()
            or success.get("account_id") != account or not success.get("spreadsheet_id")
            or success.get("spreadsheet_id") != ownership.get("spreadsheet_id")
            or (env.get("GOOGLE_SPREADSHEET_ID") and env["GOOGLE_SPREADSHEET_ID"] != success["spreadsheet_id"])):
        raise SystemExit("先に手動の初回同期とシート読み戻しを確認してください")
    if not PYTHON.exists():
        raise SystemExit("先に python3 install.py を実行してください")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    private_dir(ROOT / "logs")
    for name in ("com.instagram-insights-kit.collect.out.log", "com.instagram-insights-kit.collect.err.log"):
        protect_file(ROOT / "logs" / name)
    target = write_job("com.instagram-insights-kit.collect")
    uid = subprocess.run(["id", "-u"], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(target)], check=True)
    print(f"登録しました: {target}")
    print("初回同期が成功済みであることを確認してから自動実行を完了扱いにしてください")


if __name__ == "__main__":
    main()
