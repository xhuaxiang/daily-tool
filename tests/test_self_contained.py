"""邮件自包含相关测试：解析、正文抽取、结构化摘要、HTML 渲染。"""

import unittest
from unittest.mock import patch

from modules.fulltext import _extract_text
from modules.mailer import build_html
from modules.parser import parse
from modules.summarizer import _parse_ai_json, summarize_all


class ParserTest(unittest.TestCase):
    def test_rss_content_encoded_preferred_over_description(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <channel>
            <item>
              <title>Test &amp; Title</title>
              <link>https://example.com/a</link>
              <description>short description</description>
              <content:encoded><![CDATA[<p>This is the full article body with enough detail.</p>]]></content:encoded>
              <pubDate>Sat, 08 Nov 2026 00:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>"""
        articles = parse({"name": "Test", "type": "rss"}, xml, 5)
        self.assertEqual(len(articles), 1)
        self.assertIn("full article body", articles[0]["snippet"])
        self.assertNotIn("short description", articles[0]["snippet"])

    def test_atom_prefers_alternate_link_and_content(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Atom title</title>
            <link rel="self" href="https://example.com/self"/>
            <link rel="alternate" href="https://example.com/alt"/>
            <content type="html">&lt;p&gt;Atom body content here.&lt;/p&gt;</content>
            <updated>2026-11-08T00:00:00Z</updated>
          </entry>
        </feed>"""
        articles = parse({"name": "Test", "type": "rss"}, xml, 5)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["link"], "https://example.com/alt")
        self.assertIn("Atom body content", articles[0]["snippet"])


class FullTextTest(unittest.TestCase):
    def test_extract_text_skips_nav_and_script(self):
        html = """
        <html><body>
          <nav>menu should be removed</nav>
          <article>
            <p>First paragraph long enough to keep in the body.</p>
            <p>Second paragraph long enough to keep in the body.</p>
          </article>
          <script>alert('bad')</script>
        </body></html>
        """
        text = _extract_text(html)
        self.assertIn("First paragraph", text)
        self.assertIn("Second paragraph", text)
        self.assertNotIn("menu should be removed", text)
        self.assertNotIn("alert", text)


class SummarizerTest(unittest.TestCase):
    def test_parse_ai_json_plain_and_fenced(self):
        self.assertEqual(
            _parse_ai_json('{"title_zh": "标题", "points": ["一", "二"]}')["points"],
            ["一", "二"],
        )
        fenced = '```json\n{"title_zh": "标题", "points": ["一"]}\n```'
        self.assertEqual(_parse_ai_json(fenced)["points"], ["一"])
        self.assertIsNone(_parse_ai_json("not json"))

    def test_summarize_all_uses_structured_json(self):
        ai_json = '{"title_zh": "中文标题", "points": ["要点一", "要点二"], "excerpt_zh": "结论"}'
        articles = [{"title": "Original", "snippet": "article body"}]
        with patch("modules.summarizer._call_ai", return_value=ai_json):
            result = summarize_all(articles, "zh", [{"provider": "deepseek", "api_key": "k"}])
        self.assertEqual(result[0]["title_zh"], "中文标题")
        self.assertEqual(result[0]["summary_points"], ["要点一", "要点二"])
        self.assertEqual(result[0]["summary_status"], "ok")

    def test_summarize_all_falls_back_to_local_text(self):
        articles = [{"title": "Original", "snippet": "第一句。第二句。"}]
        with patch("modules.summarizer._call_ai", return_value=None):
            result = summarize_all(articles, "zh", [{"provider": "deepseek", "api_key": "k"}])
        self.assertEqual(result[0]["summary_status"], "local")
        self.assertTrue(result[0]["summary_points"])
        self.assertIn("第一句", result[0]["summary_points"][0])


class MailerTest(unittest.TestCase):
    def test_build_html_escapes_and_renders_points(self):
        articles = [{
            "title": "Original <script>alert(1)</script>",
            "title_zh": "中文 <b>标题</b>",
            "summary_points": ["要点 <script>", "第二点"],
            "summary_status": "ok",
            "link": "javascript:alert(1)",
            "source": "S & T",
            "pub_date": "2026-11-08 06:18:00",
            "full_text": "正文 <img src=x onerror=alert(1)>",
            "text_source": "page",
        }]
        html = build_html(articles)
        self.assertIn("中文 &lt;b&gt;标题&lt;/b&gt;", html)
        self.assertIn("要点 &lt;script&gt;", html)
        self.assertIn("S &amp; T", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<img src=x", html)

    def test_same_title_is_not_duplicated(self):
        articles = [{
            "title": "同一标题",
            "title_zh": "同一标题",
            "summary_points": ["要点"],
            "summary_status": "ok",
        }]
        self.assertEqual(build_html(articles).count("同一标题"), 1)


if __name__ == "__main__":
    unittest.main()
