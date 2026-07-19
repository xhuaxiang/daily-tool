"""获取模块 - HTTP请求抓取原始内容"""

import logging

import requests

logger = logging.getLogger("news")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch(url: str, name: str, timeout: int = 15) -> str | None:
    try:
        logger.info("Fetching [%s]: %s", name, url)
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        if resp.encoding and resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        logger.info("OK [%s] (HTTP %d, %.1f KB)", name, resp.status_code, len(resp.content) / 1024)
        return resp.text
    except requests.exceptions.Timeout:
        logger.error("Timeout [%s]: %s", name, url)
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP Error [%s]: %d", name, e.response.status_code)
    except requests.exceptions.ConnectionError:
        logger.error("Connection failed [%s]: %s", name, url)
    except Exception as e:
        logger.exception("Unknown error [%s]: %s", name, e)
    return None
