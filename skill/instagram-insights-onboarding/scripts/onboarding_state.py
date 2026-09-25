#!/usr/bin/env python3
"""Track non-secret onboarding progress for Instagram insights collection."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


STEPS = [
    "professional_account",
    "facebook_page",
    "meta_app",
    "instagram_asset",
    "long_lived_token",
    "google_sheet",
    "collector_config",
    "first_sync",
    "automation",
    "health_check",
]
STATE_NAME = ".instagram-insights-onboarding.json"


def state_path(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve() / STATE_NAME


def empty_state() -> dict:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "steps": {name: {"status": "pending", "evidence": ""} for name in STEPS},
    }


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"state not found: {path}\nRun init first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("steps"), dict):
        raise SystemExit(f"unsupported or invalid state: {path}")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def print_status(data: dict, path: Path) -> None:
    print(f"state: {path}")
    next_step = None
    for name in STEPS:
        item = data["steps"].get(name, {"status": "pending", "evidence": ""})
        mark = "x" if item.get("status") == "complete" else " "
        evidence = item.get("evidence", "")
        print(f"[{mark}] {name}" + (f" — {evidence}" if evidence else ""))
        if next_step is None and item.get("status") != "complete":
            next_step = name
    print(f"next: {next_step or 'complete'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status"):
        item = sub.add_parser(command)
        item.add_argument("--workspace", required=True)
    complete = sub.add_parser("complete")
    complete.add_argument("--workspace", required=True)
    complete.add_argument("--step", choices=STEPS, required=True)
    complete.add_argument("--evidence", required=True)
    args = parser.parse_args()
    path = state_path(args.workspace)

    if args.command == "init":
        if path.exists():
            raise SystemExit(f"state already exists: {path}")
        data = empty_state()
        save(path, data)
        print_status(data, path)
        return

    data = load(path)
    if args.command == "complete":
        evidence = args.evidence.strip()
        if not evidence:
            raise SystemExit("evidence must not be empty")
        data["steps"][args.step] = {
            "status": "complete",
            "evidence": evidence,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        save(path, data)
    print_status(data, path)


if __name__ == "__main__":
    main()
