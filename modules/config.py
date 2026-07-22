"""配置模块 - 加载 config.json"""

import json
import logging
import os

logger = logging.getLogger("news")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "news_sources": [
        {"name": "36氪", "type": "rss", "url": "https://36kr.com/feed"},
        {"name": "Hacker News", "type": "rss", "url": "https://hnrss.org/frontpage"},
        {"name": "MIT Tech Review", "type": "rss", "url": "https://www.technologyreview.com/feed"},
        {"name": "凤凰网资讯", "type": "rss", "url": "https://news.ifeng.com/rss/"},
        {"name": "财新网", "type": "rss", "url": "https://www.caixin.com/rss/"},
        {"name": "CNBC Top News", "type": "rss", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
        {"name": "NPR News", "type": "rss", "url": "https://feeds.npr.org/1001/rss.xml"},
        # {"name": "Ars Technica", "type": "rss", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "Reuters", "type": "rss", "url": "http://feeds.feedburner.com/Reuters/news"},
        # {"name": "bbc", "type": "rss", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
        # {"name": "TechCrunch", "type": "rss", "url": "https://techcrunch.com/feed/"},
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": ""
    },
    "ai": [
        {
            "provider": "gemini",
            "model": "gemini-2.0-flash-lite"
        }
    ],
    "prefer_categories": ["时事", "经济", "时政", "财经", "国际", "政治", "政策"],
    "max_articles": 30,
    "summary_language": "zh",
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        logger.warning("config.json not found, using default config")
        cfg = dict(DEFAULT_CONFIG)
    else:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    # 邮箱优先从环境变量读取
    email = cfg.get("email", {})
    email["sender_email"] = os.environ.get("EMAIL_SENDER") or email.get("sender_email", "")
    email["receiver_email"] = os.environ.get("EMAIL_RECEIVER") or email.get("receiver_email", "")
    cfg["email"] = email

    # AI 配置列表：统一转为 list，api_key 由 summarizer 内部按 provider 约定读取
    ai_list = cfg.get("ai", [])
    if isinstance(ai_list, dict):
        ai_list = [ai_list]
    cfg["ai"] = ai_list

    return cfg

