"""R1 IMAP 收信测试：只测纯解析和假连接，不访问网络。"""

import email
import os
import unittest
from email.header import Header
from email.message import EmailMessage
from unittest.mock import patch

from modules.mailbox import (
    MailboxError,
    connect,
    decode_text,
    fetch_messages,
    imap_settings,
    message_attachments,
    message_date,
    quote_folder,
)

CONFIG = {
    "email": {
        "smtp_server": "smtp.qq.com",
        "imap_server": "imap.test",
        "imap_port": 993,
        "sender_email": "me@test.com",
        "receiver_email": "me@test.com",
    },
}


def build_message(subject="每日新闻早报 2026-11-17 (2 条)", attach=True):
    message = EmailMessage()
    message["Subject"] = subject
    message["Date"] = "Mon, 17 Nov 2026 06:17:00 +0800"
    message["From"] = "me@test.com"
    message.set_content("邮件正文")
    if attach:
        message.add_attachment(
            b'{"articles": []}',
            maintype="application",
            subtype="json",
            filename="articles-2026-11-17.json",
        )
        message.add_attachment(
            b"id,label\n1,\n",
            maintype="text",
            subtype="csv",
            filename="labels-2026-11-17.csv",
        )
    return email.message_from_bytes(bytes(message))


class ParseTest(unittest.TestCase):
    def test_decode_text_handles_encoded_header(self):
        encoded = Header("每日新闻早报", "utf-8").encode()
        self.assertEqual(decode_text(encoded), "每日新闻早报")
        self.assertEqual(decode_text(""), "")
        self.assertEqual(decode_text(None), "")

    def test_message_date_is_normalized(self):
        self.assertEqual(message_date(build_message()), "2026-11-17 06:17")
        self.assertEqual(message_date(build_message()), message_date(build_message()))

    def test_message_date_falls_back_on_bad_value(self):
        message = build_message()
        del message["Date"]
        message["Date"] = "not a date"
        self.assertEqual(message_date(message), "not a date")

    def test_attachments_include_name_and_size(self):
        attachments = message_attachments(build_message())
        names = [item["filename"] for item in attachments]
        self.assertEqual(names, ["articles-2026-11-17.json", "labels-2026-11-17.csv"])
        self.assertEqual(attachments[0]["size"], len(b'{"articles": []}'))
        self.assertEqual(attachments[0]["content_type"], "application/json")

    def test_message_without_attachments(self):
        self.assertEqual(message_attachments(build_message(attach=False)), [])


class SettingsTest(unittest.TestCase):
    def test_defaults_come_from_config(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = imap_settings(CONFIG)
        self.assertEqual(settings["server"], "imap.test")
        self.assertEqual(settings["port"], 993)
        self.assertEqual(settings["user"], "me@test.com")
        self.assertEqual(settings["folder"], "INBOX")

    def test_env_overrides_config(self):
        with patch.dict(
            os.environ,
            {
                "IMAP_USER": "reader@test.com",
                "IMAP_PASSWORD": "imap-code",
                "IMAP_SERVER": "imap.other",
                "IMAP_PORT": "143",
            },
            clear=True,
        ):
            settings = imap_settings(CONFIG)
        self.assertEqual(settings["server"], "imap.other")
        self.assertEqual(settings["port"], 143)
        self.assertEqual(settings["user"], "reader@test.com")
        self.assertEqual(settings["password"], "imap-code")

    def test_imap_user_is_receiver_not_sender(self):
        config = {
            "email": {
                "sender_email": "sender@test.com",
                "receiver_email": "receiver@test.com",
            },
        }
        with patch.dict(os.environ, {"EMAIL_SENDER": "sender@test.com"}, clear=True):
            settings = imap_settings(config)
        self.assertEqual(settings["user"], "receiver@test.com")

    def test_password_falls_back_to_email_password(self):
        with patch.dict(os.environ, {"EMAIL_PASSWORD": "smtp-code"}, clear=True):
            settings = imap_settings(CONFIG)
        self.assertEqual(settings["password"], "smtp-code")

    def test_defaults_without_config(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = imap_settings(None)
        self.assertEqual(settings["server"], "imap.qq.com")
        self.assertEqual(settings["port"], 993)

    def test_quote_folder_only_when_needed(self):
        self.assertEqual(quote_folder("INBOX"), "INBOX")
        self.assertEqual(quote_folder("Sent Messages"), '"Sent Messages"')
        self.assertEqual(quote_folder('"Sent Messages"'), '"Sent Messages"')

    def test_connect_requires_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(MailboxError, "IMAP_USER"):
                connect(imap_settings(None))


class FakeConnection:
    def __init__(self, messages, meta=b"1 (BODY[] {0}"):
        self.messages = messages
        self.meta = meta
        self.selected = None
        self.search_criteria = None

    def select(self, folder):
        self.selected = folder
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.search_criteria = criteria
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, num, spec):
        index = int(num) - 1
        return "OK", [(self.meta, bytes(self.messages[index])), b")"]


class FetchMessagesTest(unittest.TestCase):
    def test_filters_by_subject_and_returns_newest_first(self):
        daily = build_message()
        other = build_message(subject="一些广告")
        conn = FakeConnection([daily, other])

        messages = fetch_messages(conn, days=7, subject_filter="每日新闻早报")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["subject"], "每日新闻早报 2026-11-17 (2 条)")
        self.assertEqual(len(messages[0]["attachments"]), 2)
        self.assertEqual(conn.selected, "INBOX")
        self.assertEqual(conn.search_criteria[0], "SINCE")

    def test_empty_subject_filter_returns_all_and_limit_applies(self):
        conn = FakeConnection([build_message(), build_message(subject="广告")])
        messages = fetch_messages(conn, days=3, subject_filter="", limit=1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["subject"], "广告")

    def test_uses_internaldate_when_date_header_missing(self):
        """日报邮件可能没有 Date 头，退回服务器收信时间。"""
        message = build_message()
        del message["Date"]
        conn = FakeConnection(
            [message],
            meta=b'1 (INTERNALDATE "16-Nov-2026 10:15:16 +0800" BODY[] {10}',
        )

        messages = fetch_messages(conn, days=7, subject_filter="")

        self.assertEqual(messages[0]["date"], "2026-11-16 10:15")

    def test_date_header_used_when_no_internaldate(self):
        messages = fetch_messages(FakeConnection([build_message()]), days=7)
        self.assertEqual(messages[0]["date"], "2026-11-17 06:17")


if __name__ == "__main__":
    unittest.main()
