"""IMAP 收信 - 读取日报邮件及其附件。

R1 只读近 N 天的邮件；不删除、不标记已读（用 BODY.PEEK）。
凭据复用 EMAIL_PASSWORD（QQ 邮箱授权码）和 EMAIL_SENDER。
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

DEFAULT_IMAP_SERVER = "imap.qq.com"
DEFAULT_IMAP_PORT = 993
DEFAULT_FOLDER = "INBOX"


class MailboxError(RuntimeError):
    """IMAP 连接或读取失败。"""


def imap_settings(config: dict | None = None) -> dict:
    """从 config 和环境变量拼出 IMAP 连接参数。

    读信的账号是“收到日报的邮箱”，默认取 receiver_email；
    SMTP 的 EMAIL_SENDER 只在两者相同时才等价，不能直接复用。
    """
    email_cfg = (config or {}).get("email") or {}
    user = (
        os.environ.get("IMAP_USER")
        or email_cfg.get("imap_user", "")
        or email_cfg.get("receiver_email", "")
        or email_cfg.get("sender_email", "")
        or ""
    ).strip()
    return {
        "server": (
            os.environ.get("IMAP_SERVER")
            or email_cfg.get("imap_server")
            or DEFAULT_IMAP_SERVER
        ),
        "port": int(
            os.environ.get("IMAP_PORT")
            or email_cfg.get("imap_port")
            or DEFAULT_IMAP_PORT
        ),
        "user": user,
        "password": (
            os.environ.get("IMAP_PASSWORD")
            or os.environ.get("EMAIL_PASSWORD", "")
        ),
        "folder": email_cfg.get("imap_folder") or DEFAULT_FOLDER,
    }


def connect(settings: dict) -> imaplib.IMAP4_SSL:
    """登录 IMAP；失败时抛出带可操作提示的 MailboxError。"""
    missing = [
        name
        for name, value in (
            (
                "IMAP_USER / config.email.imap_user / receiver_email",
                settings.get("user"),
            ),
            ("IMAP_PASSWORD / EMAIL_PASSWORD", settings.get("password")),
        )
        if not value
    ]
    if missing:
        raise MailboxError("缺少 IMAP 凭据：" + "、".join(missing))

    try:
        # timeout 避免 Actions/本地卡死
        conn = imaplib.IMAP4_SSL(
            settings["server"], settings["port"], timeout=30
        )
    except OSError as exc:
        raise MailboxError(
            f"连不上 {settings['server']}:{settings['port']}：{exc}；"
            "检查网络，或确认邮箱已开启 IMAP"
        ) from exc

    try:
        conn.login(settings["user"], settings["password"])
    except imaplib.IMAP4.error as exc:
        conn.shutdown()
        raise MailboxError(
            "IMAP 登录失败。QQ 邮箱要用“授权码”而不是登录密码，"
            f"并确认已开启 IMAP 服务。原始错误：{exc}"
        ) from exc
    return conn


def decode_text(value: str | None) -> str:
    """解码 =?UTF-8?B?...?= 形式的邮件头。"""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


def message_date(message) -> str:
    """取 Date 头，解析失败时返回空串。"""
    raw = message.get("Date")
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(raw)


def message_attachments(message) -> list[dict]:
    """列出附件名、内容类型和字节数；不保存到磁盘。"""
    result = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_text(filename)
        payload = part.get_payload(decode=True) or b""
        result.append({
            "filename": filename,
            "content_type": part.get_content_type(),
            "size": len(payload),
            "payload": payload,
        })
    return result


_INTERNALDATE_RE = re.compile(rb'INTERNALDATE "([^"]+)"')


_BEIJING_TZ = timezone(timedelta(hours=8))


def _parse_internaldate(meta: bytes) -> str:
    """从 FETCH 响应里取 IMAP 服务器记录的收信时间，转成北京时间。

    用 parsedate_to_datetime 而不是 strptime("%b")，避免依赖系统 locale。
    """
    match = _INTERNALDATE_RE.search(meta or b"")
    if not match:
        return ""
    raw = match.group(1).decode("ascii", "replace")
    try:
        return parsedate_to_datetime(raw).astimezone(_BEIJING_TZ).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (TypeError, ValueError):
        return raw


def _fetch_one(conn, num: bytes):
    """按 BODY.PEEK 拉取整封邮件，不改变已读状态。

    返回 (message, internaldate)；internaldate 是服务器侧收信时间。
    """
    typ, data = conn.fetch(num, "(INTERNALDATE BODY.PEEK[])")
    if typ != "OK" or not data:
        return None, ""
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = item[0] if isinstance(item[0], bytes) else b""
            return email.message_from_bytes(item[1]), _parse_internaldate(meta)
    return None, ""


def quote_folder(folder: str) -> str:
    """imaplib 不会给邮箱名加引号，含空格的文件夹（如 Sent Messages）会报 BAD。"""
    if len(folder) >= 2 and folder.startswith('"') and folder.endswith('"'):
        return folder
    if any(ch in folder for ch in ' ()[]{}%*"\\'):
        return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return folder


def select_folder(conn, folder: str = DEFAULT_FOLDER) -> None:
    """选择要读取的文件夹；QQ 邮箱日报在 INBOX。"""
    typ, data = conn.select(quote_folder(folder))
    if typ != "OK":
        raise MailboxError(f"打开文件夹 {folder} 失败：{data}")


def fetch_messages(
    conn,
    *,
    days: int = 7,
    folder: str = DEFAULT_FOLDER,
    subject_filter: str = "",
    limit: int = 0,
) -> list[dict]:
    """读取近 N 天邮件，按时间从新到旧返回。

    只按日期搜索（纯 ASCII，避免 IMAP 中文搜索的编码问题），
    主题过滤在本地做。
    """
    select_folder(conn, folder)

    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = conn.search(None, "SINCE", since)
    if typ != "OK":
        raise MailboxError(f"搜索邮件失败：{data}")

    numbers = data[0].split() if data and data[0] else []
    logger.info("近 %d 天共 %d 封邮件", days, len(numbers))

    messages = []
    for num in reversed(numbers):
        message, internaldate = _fetch_one(conn, num)
        if message is None:
            continue
        subject = decode_text(message.get("Subject"))
        if subject_filter and subject_filter not in subject:
            continue
        messages.append({
            "seed": num.decode() if isinstance(num, bytes) else str(num),
            "subject": subject,
            # 日报由本项目的 SMTP 发出，可能没有 Date 头，优先用服务器收信时间
            "date": internaldate or message_date(message),
            "from": decode_text(message.get("From")),
            "attachments": message_attachments(message),
            "message": message,
        })
        if limit and len(messages) >= limit:
            break
    return messages
