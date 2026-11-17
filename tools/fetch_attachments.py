#!/usr/bin/env python3
"""R1 从日报邮件回填附件到 reports/runs/<日期>/。

只下载 run-*.json / articles-*.json / labels-*.csv，文件名和内容都不落别的路径。
已存在且内容相同的跳过；内容不同时默认不覆盖，需显式 --overwrite。

示例：
    python tools/fetch_attachments.py
    python tools/fetch_attachments.py --days 14 --list
    python tools/fetch_attachments.py --overwrite
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.config import load_config
from modules.mailbox import MailboxError, connect, fetch_messages, imap_settings

DEFAULT_SUBJECT = "每日新闻早报"
_NAME_RE = re.compile(r"^(run|articles|labels)-(\d{4}-\d{2}-\d{2})\.(json|csv)$")


def target_name(filename: str) -> tuple[str, str] | None:
    """只接受本项目的三种附件名，返回 (日期, 安全文件名)。"""
    name = Path(filename).name.strip()
    match = _NAME_RE.match(name)
    if not match:
        return None
    return match.group(2), name


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="从日报邮件下载附件到 reports/runs")
    parser.add_argument("--days", type=int, default=7, help="回看天数，默认 7")
    parser.add_argument("--subject", default=DEFAULT_SUBJECT, help="主题过滤")
    parser.add_argument(
        "--dest", default=str(_ROOT / "reports" / "runs"), help="归档根目录",
    )
    parser.add_argument("--list", action="store_true", help="只列出，不写文件")
    parser.add_argument(
        "--overwrite", action="store_true", help="内容不同时覆盖已有文件",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    config = load_config()
    dest = Path(args.dest)
    conn = None
    try:
        conn = connect(imap_settings(config))
        messages = fetch_messages(
            conn, days=args.days, folder=imap_settings(config)["folder"],
            subject_filter=args.subject,
        )
    except MailboxError as exc:
        raise SystemExit(f"失败：{exc}")
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

    if not messages:
        raise SystemExit(f"近 {args.days} 天没有匹配的邮件")

    saved = skipped = different = 0
    print(f"检查 {len(messages)} 封邮件，目标目录 {dest}")
    for message in messages:
        for attachment in message["attachments"]:
            parsed = target_name(attachment["filename"])
            if not parsed:
                continue
            date, name = parsed
            path = dest / date / name
            data = attachment["payload"]
            digest = _sha256(data)

            if path.exists():
                if _sha256(path.read_bytes()) == digest:
                    skipped += 1
                    continue
                if not args.overwrite:
                    different += 1
                    print(f"  跳过（内容不同）: {path}")
                    continue

            if args.list:
                print(f"  将写入: {path}  {len(data) / 1024:.0f}K")
                saved += 1
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            saved += 1
            print(f"  写入: {path}  {len(data) / 1024:.0f}K")

    print()
    print(f"完成：写入 {saved}，已存在跳过 {skipped}，内容冲突 {different}")
    if different and not args.overwrite:
        print("内容冲突的文件未覆盖；确认后加 --overwrite 重跑")
    if not args.list and saved:
        print(f"下一步：python tools/build_index.py --input {dest} --rebuild")


if __name__ == "__main__":
    main()
