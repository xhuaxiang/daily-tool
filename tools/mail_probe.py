#!/usr/bin/env python3
"""R1 连通性检查：连 IMAP，列出近 N 天的日报和附件。

只读，不下载、不标记已读。确认这一步通过后再跑 tools/fetch_attachments.py。

示例：
    python tools/mail_probe.py
    python tools/mail_probe.py --days 14 --subject "" --limit 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.config import load_config
from modules.mailbox import (
    MailboxError,
    connect,
    fetch_messages,
    imap_settings,
)


def _size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}M"
    if size >= 1024:
        return f"{size / 1024:.0f}K"
    return f"{size}B"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="检查 IMAP 连通性和日报附件")
    parser.add_argument("--days", type=int, default=7, help="回看天数，默认 7")
    parser.add_argument("--limit", type=int, default=0, help="最多检查几封，0=全部")
    parser.add_argument(
        "--subject", default="每日新闻早报", help="主题过滤，传空串则不过滤",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    config = load_config()
    settings = imap_settings(config)
    print(f"IMAP: {settings['server']}:{settings['port']}  账号: {settings['user'] or '(未配置)'}")

    conn = None
    try:
        conn = connect(settings)
        print("登录: OK")
        messages = fetch_messages(
            conn,
            days=args.days,
            folder=settings["folder"],
            subject_filter=args.subject,
            limit=args.limit,
        )
    except MailboxError as exc:
        raise SystemExit(f"失败：{exc}")
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

    print()
    if not messages:
        print(f"近 {args.days} 天没有匹配的邮件（主题过滤：{args.subject or '无'}）")
        return

    total_size = 0
    for index, item in enumerate(messages, 1):
        print(f"[{index}] {item['date']}  {item['subject']}")
        if not item["attachments"]:
            print("    附件: 无")
            continue
        for att in item["attachments"]:
            total_size += att["size"]
            print(
                f"    附件: {att['filename']}  "
                f"{att['content_type']}  {_size_label(att['size'])}"
            )

    print()
    print(f"共 {len(messages)} 封，附件合计 {_size_label(total_size)}")


if __name__ == "__main__":
    main()
