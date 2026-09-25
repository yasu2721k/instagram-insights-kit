#!/usr/bin/env python3
"""Install dependencies and the bundled Codex skill without collecting data."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from security import protect_file, write_private


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("この配布版はmacOS専用です")
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10以上が必要です")
    if not VENV.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    pip = VENV / "bin" / "pip"
    subprocess.run([str(pip), "install", "-r", str(ROOT / "requirements.txt")], check=True)

    env_file = ROOT / ".env"
    if not env_file.exists():
        write_private(env_file, (ROOT / ".env.example").read_text())
    else:
        protect_file(env_file)

    skill_src = ROOT / "skill" / "instagram-insights-onboarding"
    skill_root = Path.home() / ".agents" / "skills"
    skill_dst = skill_root / skill_src.name
    if skill_dst.exists():
        print(f"既存スキルを保持しました: {skill_dst}")
    else:
        skill_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_src, skill_dst)
        print(f"スキルをインストールしました: {skill_dst}")

    print("\nインストール完了")
    print("Codexを再起動し、次のように依頼してください:")
    print("$instagram-insights-onboarding を使ってセットアップして")


if __name__ == "__main__":
    main()
