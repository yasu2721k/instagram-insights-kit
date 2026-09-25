#!/usr/bin/env python3
"""Check local readiness without printing secret values."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_env() -> dict[str, str]:
    result: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip("'\"")
    return result


def main() -> int:
    env = load_env()
    checks = {
        "python_3_10_or_newer": sys.version_info >= (3, 10),
        "env_file": (ROOT / ".env").exists(),
        "instagram_account_id": bool(env.get("IG_BUSINESS_ACCOUNT_ID")),
        "instagram_token": bool(env.get("IG_ACCESS_TOKEN")),
        "google_credentials": (ROOT / env.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")).exists(),
        "google_token_or_first_login": (ROOT / env.get("GOOGLE_TOKEN_FILE", "token.json")).exists(),
        "spreadsheet_configured_or_creatable": True,
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    required = ["python_3_10_or_newer", "env_file", "instagram_account_id", "instagram_token", "google_credentials"]
    return 0 if all(checks[name] for name in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
