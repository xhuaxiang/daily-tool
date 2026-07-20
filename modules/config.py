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
        {"name": "华尔街见闻", "type": "rss", "url": "https://wallstreetcn.com/rss"},
        {"name": "观察者网", "type": "rss", "url": "https://www.guancha.cn/rss.xml"},
        {"name": "Reuters", "type": "rss", "url": "https://www.reutersagency.com/feed/"},
        {"name": "BBC", "type": "rss", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
        {"name": "NYT", "type": "rss", "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"},
        {"name": "Ars Technica", "type": "rss", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "Reuters World News", "type": "rss", "url": "https://www.reuters.com/world/rss"},
        {"name": "BBC Top Stories", "type": "rss", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
        {"name": "Bloomberg Markets", "type": "rss", "url": "https://www.bloomberg.com/feeds/markets.rss"},
        {"name": "The Guardian World News", "type": "rss", "url": "https://www.theguardian.com/world/rss"},
        {"name": "CNBC Top News", "type": "rss", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
        {"name": "MIT Technology Review", "type": "rss", "url": "https://www.technologyreview.com/feed"},
        {"name": "Hacker News", "type": "rss", "url": "https://hnrss.org/frontpage"},
        {"name": "联合早报即时新闻", "type": "rss", "url": "https://www.zaobao.com/news/instant-news/rss.xml"}
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "shion_1130@qq.com",
        "receiver_email": "shion_1130@qq.com"
    },
    "ai": [
        {
            "provider": "gemini",
            "model": "gemini-2.0-flash-lite"
        }
    ],
    "prefer_categories": ["时事", "经济", "时政", "财经", "国际", "政治", "政策"],
    "max_articles": 40,
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


