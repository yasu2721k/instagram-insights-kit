#!/usr/bin/env python3
"""Offline checks for the distributable package."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    required = [
        "START-HERE.md", ".env.example", "requirements.txt", "install.py", "doctor.py",
        "collector.py", "analysis.py", "install_automation.py", "skill/instagram-insights-onboarding/SKILL.md",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    if missing:
        raise SystemExit(f"missing files: {missing}")

    doctor = load("kit_doctor", "doctor.py")
    collector = load("kit_collector", "collector.py")
    analysis = load("kit_analysis", "analysis.py")
    assert doctor.ROOT == ROOT
    assert collector.ROOT == ROOT
    sample = analysis.post_records(
        [{"id": "1", "timestamp": "2026-09-20T00:00:00+00:00", "media_product_type": "REELS",
          "caption": "sample", "permalink": "https://example.invalid/post", "like_count": 3, "comments_count": 1}],
        {"1": {"reach": 200, "saved": 10, "shares": 2, "views": 250}},
    )
    assert sample[0]["save_rate"] == 5.0

    with tempfile.TemporaryDirectory() as temp_dir:
        state_module_path = ROOT / "skill" / "instagram-insights-onboarding" / "scripts" / "onboarding_state.py"
        spec = importlib.util.spec_from_file_location("onboarding_state", state_module_path)
        assert spec and spec.loader
        state = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(state)
        path = state.state_path(temp_dir)
        payload = state.empty_state()
        state.save(path, payload)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["steps"]["professional_account"]["status"] == "pending"

    scan_files = [
        path for path in ROOT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".yaml"}
        and path.name != "smoke_test.py"
        and not any(part in {"__pycache__", ".venv", ".git", "data", "logs"} for part in path.parts)
    ]
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in scan_files)
    forbidden = ["shimokawa", "suusan", "SLACK_BOT_TOKEN"]
    found = [value for value in forbidden if value.lower() in text.lower()]
    if found:
        raise SystemExit(f"personal markers found: {found}")
    print("smoke test: OK")


if __name__ == "__main__":
    main()
