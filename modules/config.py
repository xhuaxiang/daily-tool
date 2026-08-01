"""配置模块 - 加载 config.json"""

import json
import logging
import os

logger = logging.getLogger("news")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "news_sources": [
        {"name": "CNBC Top News", "type": "rss", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
        {"name": "CNBC Markets", "type": "rss", "url": "https://www.cnbc.com/id/10001147/device/rss/rss.html"},
        {"name": "CNBC Economy", "type": "rss", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
        {"name": "WSJ Markets", "type": "rss", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
        {"name": "MarketWatch Top", "type": "rss", "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
        {"name": "France 24 Economy", "type": "rss", "url": "https://www.france24.com/en/economy/rss"},
        {"name": "36氪", "type": "rss", "url": "https://36kr.com/feed"},
        {"name": "Bloomberg Markets", "type": "rss", "url": "https://feeds.bloomberg.com/markets/news.rss"},
        {"name": "Reuters Business", "type": "rss", "url": "https://feeds.reuters.com/reuters/businessNews"},
        {"name": "NYSE Business", "type": "rss", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"},
        {"name": "Financial Times", "type": "rss", "url": "https://www.ft.com/rss/home"},
        {"name": "BBC Business", "type": "rss", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"name": "Economist Finance", "type": "rss", "url": "https://www.economist.com/finance-and-economics/rss.xml"},
        {"name": "Nikkei Asia", "type": "rss", "url": "https://asia.nikkei.com/rss/feed"},
        {"name": "CNN Business", "type": "rss", "url": "https://edition.cnn.com/business/rss"},
        {"name": "SCMP Business", "type": "rss", "url": "https://www.scmp.com/rss/4/feed"},
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": ""
    },
    "ai": [
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash"
        }
    ],
    "prefer_categories": ["经济", "财经", "科技", "时政", "国际", "时事"],
    "max_articles": 15,
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

