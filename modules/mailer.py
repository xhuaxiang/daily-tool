"""邮件模块 - 构建HTML并发送SMTP邮件"""

import logging
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

logger = logging.getLogger("news")

_BEIJING_TZ = timezone(timedelta(hours=8))


def _esc(value) -> str:
    return escape(str(value or ""), quote=True)


def _safe_url(value) -> str:
    """只允许 http/https 链接，避免 javascript: 等协议进入 href"""
    url = str(value or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def _summary_html(art: dict) -> str:
    points = art.get("summary_points") or []
    if points:
        items = "".join(f'<li style="margin:0 0 4px;">{_esc(point)}</li>' for point in points)
        return (
            '<ul style="margin:6px 0 8px 18px;padding:0;font-size:14px;'
            f'color:#333;line-height:1.6;">{items}</ul>'
        )
    summary = (art.get("summary") or "").strip()
    if not summary:
        return ""
    return f'<div style="font-size:14px;color:#333;margin-bottom:8px;line-height:1.6;">{_esc(summary)}</div>'


def _excerpt_html(art: dict) -> str:
    text = (art.get("full_text") or art.get("snippet") or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    label = "正文摘录" if art.get("text_source") == "page" else "RSS 摘要"
    return (
        '<div style="font-size:12px;color:#777;line-height:1.6;margin-top:8px;">'
        f'<span style="color:#999;">{label}：</span>{_esc(text)}</div>'
    )


def build_html(articles: list[dict]) -> str:
    now_str = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    items_html = ""
    for i, art in enumerate(articles, 1):
        title = art.get("title", "")
        title_zh = (art.get("title_zh") or "").strip()
        display_title = title_zh or title
        original_html = ""
        if title_zh and title_zh != title:
            original_html = f'<div style="font-size:12px;color:#999;margin-top:4px;">{_esc(title)}</div>'

        source = art.get("source", "")
        pub_date = art.get("pub_date", "")
        date_tag = f'<span style="color:#999;font-size:12px;">{_esc(pub_date)}</span>' if pub_date else ""

        status_html = ""
        if art.get("summary_status") == "local":
            status_html = (
                '<div style="font-size:11px;color:#b26a00;margin-bottom:4px;">'
                'AI 摘要不可用，以下为原文摘录</div>'
            )

        summary_html = _summary_html(art)
        # 本地兜底时 points 已是原文摘录，避免重复展示
        excerpt_html = "" if art.get("summary_status") == "local" else _excerpt_html(art)

        link = _safe_url(art.get("link", ""))
        link_tag = (
            f'<a href="{_esc(link)}" rel="noopener noreferrer" '
            'style="color:#1a73e8;text-decoration:none;">[原文]</a>'
            if link else ""
        )

        items_html += f"""
        <div style="margin-bottom:20px;padding:16px;background:#f8f9fa;border-radius:8px;">
            <div style="font-size:13px;color:#666;margin-bottom:4px;">
                #{i}  {_esc(source)}  {date_tag}
            </div>
            <div style="font-size:16px;font-weight:bold;margin-bottom:6px;">
                {_esc(display_title)}
            </div>
            {original_html}
            {status_html}
            {summary_html}
            {excerpt_html}
            <div style="font-size:12px;margin-top:6px;">
                {link_tag}
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Segoe UI','Microsoft YaHei',sans-serif;max-width:640px;margin:0 auto;padding:20px;">
    <div style="text-align:center;padding:20px 0;border-bottom:2px solid #e0e0e0;margin-bottom:20px;">
        <h1 style="margin:0;font-size:24px;color:#333;">每日新闻早报</h1>
        <p style="margin:6px 0 0;color:#999;font-size:13px;">{now_str} (UTC+8) &nbsp;·&nbsp; 共 {len(articles)} 条新闻</p>
    </div>
    {items_html}
    <div style="text-align:center;padding:16px 0;border-top:1px solid #e0e0e0;margin-top:20px;color:#aaa;font-size:12px;">
        本邮件由每日新闻早报自动生成
    </div>
</body>
</html>"""


def send_email(email_cfg: dict, articles: list[dict]) -> bool:
    smtp_server = email_cfg.get("smtp_server", "smtp.qq.com")
    smtp_port = email_cfg.get("smtp_port", 587)
    sender = email_cfg.get("sender_email", "")
    receiver_raw = email_cfg.get("receiver_email", "")
    password = os.environ.get("EMAIL_PASSWORD", "")

    if not sender or not receiver_raw or not password:
        logger.warning("Email config incomplete, skipping send")
        return False

    # 支持多个收件人，用逗号分隔
    receivers = [r.strip() for r in receiver_raw.replace("，", ",").split(",") if r.strip()]

    if not receivers:
        logger.warning("No valid receiver email, skipping send")
        return False

    now_str = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    html = build_html(articles)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"每日新闻早报 {now_str} ({len(articles)} 条)"
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, receivers, msg.as_string())
        logger.info("Email sent to %d recipients: %s", len(receivers), ", ".join(receivers))
        return True
    except Exception as e:
        logger.exception("Failed to send email: %s", e)
        return False
