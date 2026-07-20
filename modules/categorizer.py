"""分类模块 - 对文章进行类别判断和偏好排序"""

import logging
import re

logger = logging.getLogger("news")

# ── 类别关键词映射（标题+内容匹配） ──────────────────────────
_CATEGORY_KEYWORDS = {
    "时事": [
        "突发", "最新", "现场", "通报", "声明", "回应",
        "外交部", "国务院", "习近平", "总理",
        "特朗普", "拜登", "普京",
        "北约", "联合国", "欧盟", "峰会", "会谈", "访华",
    ],
    "经济": [
        "经济", "GDP", "通胀", "CPI", "央行", "利率",
        "降息", "加息", "股市", "A股",
        "期货", "债券", "人民币", "美元", "油价", "黄金",
        "贸易", "关税", "制裁",
        "营收", "利润", "财报", "IPO", "融资", "上市", "投资",
    ],
    "时政": [
        "政策", "立法", "改革", "条例", "法规", "法案",
        "议会", "选举", "投票",
        "民主", "共和党", "民主党", "政府", "内阁", "部长", "大使",
    ],
    "财经": [
        "财经", "金融", "银行", "证券", "基金", "保险",
        "理财", "数字货币", "比特币", "区块链",
        "监管", "房地产", "牛市", "熊市",
    ],
    "国际": [
        "国际", "全球", "世界", "海外", "外媒", "外电",
        "白宫", "五角大楼",
        "俄罗斯", "乌克兰", "中东", "欧洲", "亚洲",
        "美国", "日本", "韩国",
    ],
    "科技": [
        "科技", "AI", "人工智能", "芯片", "半导体", "5G",
        "大模型", "机器人", "自动驾驶",
        "新能源", "电动车", "iPhone",
        "华为", "苹果", "谷歌", "微软",
    ],
}

# 高优先级触发词
_HIGH_PRIORITY_KEYWORDS = [
    "突发", "紧急", "重大", "最新", "首次",
    "历史性", "里程碑",
    "breaking", "urgent", "exclusive", "important",
]


def classify(article: dict) -> tuple[str, int]:
    """对一篇文章分类，返回 (类别名, 匹配分数)

    分数含义：
      - 0~2  弱匹配
      - 3~5  一般匹配
      - 6+   强匹配（含高优先级词）
    """
    text = (
        (article.get("title", "") + " " + (article.get("snippet", "") or ""))
        .lower()
    )

    score = 0
    matched_category = "其他"

    # 高优先级关键词加分
    for kw in _HIGH_PRIORITY_KEYWORDS:
        if kw.lower() in text:
            score += 5

    # 遍历各类别关键词
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                score += 2
                if matched_category == "其他":
                    matched_category = cat

    return matched_category, score


def sort_by_preference(articles: list[dict], preferred: list[str]) -> list[dict]:
    """按偏好类别排序，优先类别排前面，同类别的按匹配度降序"""
    if not preferred:
        return articles

    scored = []
    for art in articles:
        cat, base_score = classify(art)
        # 属于偏好类别则加权
        if cat in preferred:
            base_score += 10
        scored.append((art, base_score))

    scored.sort(key=lambda x: -x[1])
    return [item[0] for item in scored]


def count_preferred(articles: list[dict], preferred: list[str]) -> int:
    """统计偏好类别的文章数量"""
    if not preferred:
        return 0
    return sum(1 for art in articles if classify(art)[0] in preferred)


def get_category_tag(article: dict) -> str:
    """获取文章的分类标签字符串，如 '[时事]'"""
    cat, _ = classify(article)
    return f"[{cat}]" if cat != "其他" else ""
