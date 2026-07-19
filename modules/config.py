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
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": "",
    },
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

    # 邮箱优先从环境变量读取，避免敏感信息写死在配置文件
    email = cfg.get("email", {})
    email["sender_email"] = os.environ.get("EMAIL_SENDER") or email.get("sender_email", "")
    email["receiver_email"] = os.environ.get("EMAIL_RECEIVER") or email.get("receiver_email", "")
    cfg["email"] = email

    return cfg
