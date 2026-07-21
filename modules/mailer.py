"""邮件模块 - 构建HTML并发送SMTP邮件"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("news")


def build_html(articles: list[dict]) -> str:
    items_html = ""
    for i, art in enumerate(articles, 1):
        title = art.get("title", "")
        summary = art.get("summary", "")
        link = art.get("link", "")
        source = art.get("source", "")
        pub_date = art.get("pub_date", "")

        link_tag = f'<a href="{link}" style="color:#1a73e8;text-decoration:none;">[原文]</a>' if link else ""
        date_tag = f'<span style="color:#999;font-size:12px;">{pub_date}</span>' if pub_date else ""

        items_html += f"""
        <div style="margin-bottom:20px;padding:16px;background:#f8f9fa;border-radius:8px;">
            <div style="font-size:13px;color:#666;margin-bottom:4px;">
                #{i}  {source}  {date_tag}
            </div>
            <div style="font-size:16px;font-weight:bold;margin-bottom:6px;">
                {title}
            </div>
            <div style="font-size:14px;color:#444;margin-bottom:6px;line-height:1.6;">
                {summary}
            </div>
            <div style="font-size:12px;">
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
        <p style="margin:6px 0 0;color:#999;font-size:13px;">共 {len(articles)} 条新闻</p>
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

    html = build_html(articles)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"每日新闻早报 ({len(articles)} 条)"
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
    smtp_server = email_cfg.get("smtp_server", "smtp.qq.com")
    smtp_port = email_cfg.get("smtp_port", 587)
    sender = email_cfg.get("sender_email", "")
    receiver = email_cfg.get("receiver_email", "")
    password = os.environ.get("EMAIL_PASSWORD", "")

    if not sender or not receiver or not password:
        logger.warning("Email config incomplete, skipping send")
        return False

    html = build_html(articles)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"每日新闻早报 ({len(articles)} 条)"
    msg["From"] = sender
    msg["To"] = receiver
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [receiver], msg.as_string())
        logger.info("Email sent to %s", receiver)
        return True
    except Exception as e:
        logger.exception("Failed to send email: %s", e)
        return False
