#!/usr/bin/env python3
"""发送最新周报到订阅列表。用法: python3 scripts/send_weekly.py"""
import csv, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBSCRIBERS = REPO / "subscribers.csv"
WEEKLY_DIR = REPO / "weekly"

def get_latest_weekly():
    """找到最新的中文周报 HTML"""
    files = sorted(WEEKLY_DIR.glob("weekly-*.html"))
    # 排除 _en 版本
    files = [f for f in files if "_en" not in f.stem]
    return files[-1] if files else None

def main():
    weekly = get_latest_weekly()
    if not weekly:
        print("No weekly briefing found.")
        sys.exit(1)

    # Read subscribers
    subscribers = []
    with open(SUBSCRIBERS) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                subscribers.append((parts[0].strip(), parts[1].strip()))

    print(f"Sending {weekly.name} to {len(subscribers)} subscribers...")
    for name, email in subscribers:
        print(f"  -> {name} <{email}>")
        # TODO: 配置 himalaya SMTP 后启用
        # subprocess.run([
        #     "himalaya", "template", "send",
        #     "-H", f"To:{name} <{email}>",
        #     "-H", f"Subject: [AU Renewables Weekly] {weekly.stem}",
        # ], input=f"Hi {name},\n\nLatest weekly briefing: {weekly}\n\n--\nRenewable Energy News in AU".encode())

    print("Done. Configure himalaya SMTP to enable sending.")

if __name__ == "__main__":
    main()
