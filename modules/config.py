"""配置模块 - 加载 config.json"""

import json
import logging
import os

logger = logging.getLogger("news")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    # P0.5 体检后保留的可用源：能抓正文、发布频率稳定。
    # publisher 用于同一媒体多栏目之间的配额，避免 CNBC/NPR 刷屏。
    "news_sources": [
        {"name": "CNBC Top News", "publisher": "CNBC", "type": "rss", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "timeout": 8},
        {"name": "CNBC Markets", "publisher": "CNBC", "type": "rss", "url": "https://www.cnbc.com/id/10001147/device/rss/rss.html", "timeout": 8},
        {"name": "CNBC Economy", "publisher": "CNBC", "type": "rss", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "timeout": 8},
        {"name": "CNBC Politics", "publisher": "CNBC", "type": "rss", "url": "https://www.cnbc.com/id/10000113/device/rss/rss.html", "timeout": 8},
        {"name": "NPR Business", "publisher": "NPR", "type": "rss", "url": "https://feeds.npr.org/1006/rss.xml", "timeout": 8},
        {"name": "NPR World", "publisher": "NPR", "type": "rss", "url": "https://feeds.npr.org/1004/rss.xml", "timeout": 8},
        {"name": "Fortune", "publisher": "Fortune", "type": "rss", "url": "https://fortune.com/feed/", "timeout": 8},
        {"name": "France 24 Economy", "publisher": "France 24", "type": "rss", "url": "https://www.france24.com/en/economy/rss", "timeout": 8},
        {"name": "ECB", "publisher": "ECB", "type": "rss", "url": "https://www.ecb.europa.eu/rss/press.html", "timeout": 8},
        {"name": "Federal Reserve", "publisher": "Federal Reserve", "type": "rss", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "timeout": 8},
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
            "model": "deepseek-chat"
        }
    ],
    "prefer_categories": ["经济", "财经", "科技", "时政", "国际", "时事"],
    "max_articles": 15,
    "summary_language": "zh",
    # P1 选稿：两阶段候选 + 事件聚类 + 配额
    "selection": {
        "enabled": True,
        "candidate_pool": 30,
        "event_window_hours": 36,
        "event_threshold": 0.58,
        "max_cluster_size": 5,
        "per_source_max": 3,
        "per_publisher_max": 4,
        "per_event_max": 1,
        "category_min": {"经济": 2, "时政": 1, "国际": 1},
        "weights": {
            "importance": 0.30,
            "info_density": 0.20,
            "source_weight": 0.20,
            "recency": 0.15,
            "category_fit": 0.10,
            "fulltext": 0.05,
        },
        "default_source_weight": 0.75,
        "noise_penalty": 0.25,
        "noise_title_patterns": [
            "stock movers", "live updates", "here's what to know", "what to know",
            "5 things", "markets wrap", "week ahead", "podcast", "transcript",
            "opinion", "my friend", "money parties", "credit score", "retirement",
            "how can i", "personal finance", "current price of", "price of oil as of",
        ],
        "source_weights": {
            "CNBC Top News": 1.0,
            "CNBC Markets": 0.95,
            "CNBC Economy": 1.0,
            "CNBC Politics": 0.95,
            "NPR Business": 0.95,
            "NPR World": 0.95,
            "Fortune": 0.90,
            "France 24 Economy": 0.65,
            "ECB": 0.90,
            "Federal Reserve": 0.90,
        },
    },
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

