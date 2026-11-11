"""分类模块 - 对文章进行类别判断和偏好排序

设计原则：
  1. 按类别独立计分，选最高分作为主类别
  2. 关键词分三级：核心词(5分)、扩展词(3分)、辅助词(1分)
  3. 经济/财经类权重加成，体现"了解经济"的核心诉求
  4. 标题命中比正文命中得分更高
"""

import logging
import re

logger = logging.getLogger("news")

# ── 分类关键词（三级权重） ──────────────────────────
# 核心词(core): 强指向性，命中几乎确定是该类别，权重 5
# 扩展词(expand): 相关但可能跨类，权重 3
# 辅助词(aux): 弱信号，需要多个才可信，权重 1

_CATEGORIES: dict[str, dict[str, list[str]]] = {
    # ═══════════════════════════════════════════════════
    #  经济 —— 宏观经济、产业经济、贸易、企业基本面
    # ═══════════════════════════════════════════════════
    "经济": {
        "core": [
            "GDP", "gdp", "经济增长", "经济衰退", "通胀", "通货紧缩",
            "CPI", "PPI", "PMI", "采购经理人指数", "居民消费价格",
            "央行加息", "央行降息", "存款准备金", "货币政策",
            "财政政策", "经济刺激", "经济数据", "宏观经济",
            "产业链", "供应链", "产能过剩", "产业结构",
            "贸易逆差", "贸易顺差", "关税壁垒", "关税政策", "关税", "贸易战",
            "美联储", "fed", "federal reserve", "欧洲央行", "ecb",
            "经济制裁", "出口管制", "实体清单",
        ],
        "expand": [
            "经济", "GDP增速", "经济复苏", "衰退", "滞胀",
            "加息", "降息", "利率", "汇率", "人民币贬值", "人民币升值",
            "制造业", "工业产值", "消费信心", "就业率", "失业率",
            "进出口", "外贸", "贸易", "关税",
            "产业链转移", "去风险", "脱钩",
            "大宗商品", "原油", "油价",
            "世界经济", "全球经济",
            "基建", "基础设施",
            "经济展望", "经济前景",
            "economy", "economic", "inflation", "deflation", "recession",
            "central bank", "rate cut", "rate hike", "interest rates",
            "monetary policy", "fiscal policy", "trade war", "trade deal",
            "jobs report", "labor market", "consumer prices", "retail sales",
            "manufacturing", "industrial production", "economic growth",
            "supply chain", "export controls", "oil", "crude oil", "opec",
            "energy prices", "energy market",
        ],
        "aux": [
            "增长", "放缓", "下行", "上行", "企稳",
            "消费", "内需", "外需",
            "制造业PMI", "服务业PMI",
            "工农业", "产值",
        ],
    },

    # ═══════════════════════════════════════════════════
    #  财经 —— 金融市场、投资理财、公司财务、房地产
    # ═══════════════════════════════════════════════════
    "财经": {
        "core": [
            "股市暴跌", "股市大涨", "牛市", "熊市", "崩盘",
            "IPO", "上市", "融资", "A轮", "B轮", "C轮",
            "财报", "季度财报", "年报", "营收", "净利润",
            "标普500", "纳斯达克", "道琼斯", "恒生指数",
            "科创板", "创业板", "北交所",
            "基金净值", "ETF", "量化交易",
            "数字货币", "比特币", "加密货币", "区块链",
            "房地产泡沫", "楼市调控", "房贷利率",
        ],
        "expand": [
            "股市", "A股", "港股", "美股", "日股",
            "债券", "期货", "黄金", "白银",
            "投资", "融资", "估值", "市值",
            "股价", "涨停", "跌停",
            "券商", "基金", "保险", "信托",
            "理财", "分红", "股息",
            "房地产", "房价", "楼市",
            "监管", "证监会", "银保监",
            "数字货币", "稳定币",
            "并购", "收购", "重组",
            "stock market", "stocks", "investors", "wall street",
            "bond yields", "treasury yields", "earnings", "quarterly results",
            "market rally", "selloff", "nasdaq", "s&p 500", "dow jones",
            "dollar", "oil prices", "gold prices", "bitcoin", "cryptocurrency",
        ],
        "aux": [
            "上涨", "下跌", "反弹", "回调",
            "开盘", "收盘", "成交量",
            "板块", "龙头",
            "现金流", "负债率",
        ],
    },

    # ═══════════════════════════════════════════════════
    #  科技 —— 技术突破、AI、半导体、新能源、互联网
    # ═══════════════════════════════════════════════════
    "科技": {
        "core": [
            "人工智能", "大模型", "GPT", "深度学习",
            "芯片", "半导体", "算力", "GPU", "CPU",
            "自动驾驶", "无人驾驶", "智能驾驶",
            "量子计算", "量子芯片",
            "新能源", "光伏", "风电", "储能",
            "电动车", "动力电池", "固态电池",
            "5G", "6G", "卫星通信",
            "人形机器人", "具身智能",
        ],
        "expand": [
            "AI", "机器学习", "神经网络", "算法",
            "科技", "技术突破", "研发",
            "芯片制造", "光刻机", "台积电",
            "机器人", "无人机",
            "新能源汽车", "特斯拉",
            "华为", "苹果", "谷歌", "微软", "OpenAI",
            "互联网", "云计算", "大数据",
            "生物科技", "基因编辑",
            "航天", "火箭", "卫星", "SpaceX",
            "artificial intelligence", "chip", "chips", "semiconductor",
            "semiconductors", "nvidia", "software", "cloud", "robotics",
            "electric vehicle", "battery", "apple", "google", "microsoft",
            "meta", "amazon", "tesla",
        ],
        "aux": [
            "创新", "专利", "开源",
            "智能", "数字化", "自动化",
            "App", "软件", "平台",
            "手机", "电脑", "硬件",
        ],
    },

    # ═══════════════════════════════════════════════════
    #  国际 —— 地缘政治、外交、国际组织、地区局势
    # ═══════════════════════════════════════════════════
    "国际": {
        "core": [
            "白宫", "五角大楼", "克里姆林宫",
            "北约", "欧盟", "联合国",
            "乌克兰危机", "俄乌", "中东冲突",
            "中美关系", "美中", "中美",
            "台海", "南海", "钓鱼岛",
            "制裁", "军事演习", "军演",
        ],
        "expand": [
            "国际", "全球", "海外", "世界",
            "外交", "大使", "访问", "峰会",
            "俄罗斯", "乌克兰", "中东", "欧洲", "亚洲",
            "美国", "日本", "韩国", "朝鲜",
            "印度", "伊朗", "以色列",
            "G7", "G20", "金砖", "上合组织",
            "地缘", "冲突", "战争",
            "china", "chinese", "russia", "ukraine", "european union",
            "middle east", "israel", "iran", "gaza", "nato",
            "united nations", "geopolitics", "foreign policy", "diplomacy",
            "summit", "sanctions", "taiwan", "south china sea",
        ],
        "aux": [
            "边境", "领土",
            "移民", "难民",
            "会谈", "谈判", "协议",
        ],
    },

    # ═══════════════════════════════════════════════════
    #  时政 —— 国内政策、立法、政府治理、选举
    # ═══════════════════════════════════════════════════
    "时政": {
        "core": [
            "国务院", "政治局", "中央",
            "两会", "人大代表", "政协委员",
            "立法", "修法", "法案",
            "反腐", "纪律审查", "双开",
            "选举", "投票", "换届",
            "政府工作报告",
        ],
        "expand": [
            "政策", "改革", "条例", "法规", "法治",
            "政府", "部门", "机构",
            "民主", "共和党", "民主党",
            "议会", "国会", "参议院", "众议院",
            "总理", "部长", "省长",
            "公共安全", "社会治安",
            "医疗改革", "教育改革", "养老金",
            "president", "white house", "congress", "senate",
            "house of representatives", "election", "campaign",
            "democrats", "republicans", "trump", "biden",
            "supreme court", "legislation", "regulation",
            "government shutdown", "impeachment", "lawmakers",
            "governor", "administration", "hearing",
        ],
        "aux": [
            "公告", "通知", "文件",
            "审批", "核准", "备案",
            "试点", "示范",
        ],
    },

    # ═══════════════════════════════════════════════════
    #  时事 —— 突发、社会热点、民生、事故灾害
    # ═══════════════════════════════════════════════════
    "时事": {
        "core": [
            "突发", "紧急", "刚刚",
            "地震", "洪水", "台风", "火灾",
            "事故", "坠机", "沉船",
            "恐怖袭击", "爆炸",
            "抗议", "示威", "骚乱",
        ],
        "expand": [
            "最新", "热点", "头条",
            "社会", "民生", "百姓",
            "天气", "气象", "预警",
            "疫情", "传染病",
            "失踪", "救援",
            "曝光", "调查",
            "storm", "earthquake", "wildfire", "flood", "hurricane",
            "shooting", "protest", "strike", "accident", "outbreak",
            "emergency", "rescue",
        ],
        "aux": [
            "报道", "消息", "快讯",
            "引起关注", "引发热议",
        ],
    },
}

# ── 高优先级触发词（标题出现则大幅加分） ──────────
_HIGH_PRIORITY_TERMS = [
    "突发", "紧急", "刚刚", "重大", "首次", "历史性",
    "独家", "快讯", "breaking", "urgent", "exclusive",
]

# ── 类别权重（体现"了解经济"的核心诉求） ──────────
# 经济类文章即使关键词命中不多，也值得被前置
_CATEGORY_WEIGHTS = {
    "经济": 1.5,
    "财经": 1.3,
    "科技": 1.0,
    "国际": 1.0,
    "时政": 0.9,
    "时事": 0.9,
}


def _keyword_hit(text: str, keyword: str) -> bool:
    """关键词命中判断。

    中文关键词继续用子串匹配；纯 ASCII 关键词加词边界，避免 "AI" 命中
    "said/chair"、"App" 命中 "apparently" 这类误判。text 需已 lower。
    """
    kw = keyword.lower()
    if not kw:
        return False
    if all(ord(ch) < 128 for ch in kw):
        pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return kw in text


def _match_keywords(text: str, keywords: list[str]) -> int:
    """计算某组关键词在文本中的命中次数（不区分大小写）"""
    lower_text = text.lower()
    return sum(1 for kw in keywords if _keyword_hit(lower_text, kw))


def classify(article: dict) -> tuple[str, int]:
    """对一篇文章进行多类别评分，返回 (最佳类别, 综合得分)

    评分逻辑：
      1. 标题中的关键词命中额外 +3 分（标题比正文更有代表性）
      2. 核心词(core) 每个 +5
      3. 扩展词(expand) 每个 +3
      4. 辅助词(aux) 每个 +1
      5. 类别权重作为乘数
      6. 高优先级词统一加分
      7. 最终得分归一化到便于排序的量级
    """
    title = article.get("title", "")
    snippet = article.get("snippet", "") or ""
    full_text = (title + " " + snippet).lower()
    title_lower = title.lower()

    # ── 按类别独立计分 ──
    category_scores: dict[str, float] = {}

    for cat, tiers in _CATEGORIES.items():
        score = 0.0

        # 核心词计分（标题命中 +3 额外加成）
        for kw in tiers.get("core", []):
            if _keyword_hit(full_text, kw):
                score += 5
                if _keyword_hit(title_lower, kw):
                    score += 3  # 标题加成

        # 扩展词计分
        for kw in tiers.get("expand", []):
            if _keyword_hit(full_text, kw):
                score += 3
                if _keyword_hit(title_lower, kw):
                    score += 2

        # 辅助词计分
        for kw in tiers.get("aux", []):
            if _keyword_hit(full_text, kw):
                score += 1
                if _keyword_hit(title_lower, kw):
                    score += 1

        # 应用类别权重
        score *= _CATEGORY_WEIGHTS.get(cat, 1.0)

        category_scores[cat] = score

    # ── 高优先级触发词加分 ──
    priority_bonus = 0
    for term in _HIGH_PRIORITY_TERMS:
        if term.lower() in title_lower:
            priority_bonus += 8
        elif term.lower() in full_text:
            priority_bonus += 3

    # ── 选出最高分类别 ──
    if category_scores and max(category_scores.values()) >= 2:
        best_cat = max(category_scores, key=category_scores.get)
        best_score = category_scores[best_cat] + priority_bonus
    else:
        # 没有类别达到最低可信分时，不拿"优先级加分"硬套到第一个类别
        best_cat = "其他"
        best_score = priority_bonus

    # 归一化：除以5让数字不过大
    final_score = int(best_score / 5)

    return best_cat, final_score


def get_all_category_scores(article: dict) -> dict[str, float]:
    """获取文章在各分类上的原始得分（用于调试或更精细的排序）"""
    title = article.get("title", "")
    snippet = article.get("snippet", "") or ""
    full_text = (title + " " + snippet).lower()
    title_lower = title.lower()

    scores: dict[str, float] = {}
    for cat, tiers in _CATEGORIES.items():
        score = 0.0
        for kw in tiers.get("core", []):
            if _keyword_hit(full_text, kw):
                score += 5
                if _keyword_hit(title_lower, kw):
                    score += 3
        for kw in tiers.get("expand", []):
            if _keyword_hit(full_text, kw):
                score += 3
                if _keyword_hit(title_lower, kw):
                    score += 2
        for kw in tiers.get("aux", []):
            if _keyword_hit(full_text, kw):
                score += 1
                if _keyword_hit(title_lower, kw):
                    score += 1
        scores[cat] = score * _CATEGORY_WEIGHTS.get(cat, 1.0)
    return scores


def sort_by_preference(articles: list[dict], preferred: list[str]) -> list[dict]:
    """按偏好类别排序：
    1. 优先类别中的文章排前面
    2. 同一类别内，按分类得分降序
    3. 非偏好类别按得分降序排在后面
    """
    if not preferred:
        return articles

    scored: list[tuple[dict, int, bool]] = []
    for art in articles:
        cat, score = classify(art)
        in_pref = cat in preferred
        scored.append((art, score, in_pref))

    # 排序：偏好优先 → 得分降序
    scored.sort(key=lambda x: (-x[2], -x[1]))
    return [item[0] for item in scored]


def count_preferred(articles: list[dict], preferred: list[str]) -> int:
    """统计偏好类别的文章数量"""
    if not preferred:
        return 0
    return sum(1 for art in articles if classify(art)[0] in preferred)


def get_category_tag(article: dict) -> str:
    """获取文章的分类标签字符串，如 '[经济]'"""
    cat, _ = classify(article)
    return f"[{cat}]" if cat != "其他" else ""
