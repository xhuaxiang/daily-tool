# 每日新闻早报 (Daily News Brief)

自动抓取 RSS/HTML 新闻源，去重后按“事件聚类 + 规则评分 + 配额”选稿，生成 AI/本地摘要，支持控制台查看和邮件推送。

## 项目结构

```
.
├── main.py                    # 入口，直接 python main.py 运行
├── config.json                # 本地配置（新闻源、邮箱、AI、选稿），已 gitignore
├── requirements.txt           # Python 依赖
├── modules/
│   ├── config.py              # 配置加载
│   ├── fetcher.py             # 网络抓取
│   ├── parser.py              # RSS / HTML 解析
│   ├── dedup.py               # 跨站点新闻去重
│   ├── fulltext.py            # 正文抽取，失败回退 RSS 摘要
│   ├── categorizer.py         # 文章分类 & 偏好排序
│   ├── events.py              # 事件聚类 v0（标题/数字/日期/发布方）
│   ├── scoring.py             # 选稿规则评分
│   ├── selection.py           # 两阶段选稿与配额
│   ├── snapshot.py            # 运行快照、全文归档、标注 CSV
│   ├── summarizer.py          # DeepSeek / 本地摘要
│   └── mailer.py              # SMTP 邮件发送（含附件）
├── tools/
│   ├── diagnose.py            # P0 新闻源体检
│   ├── label_sample.py        # 从运行快照生成人工标注 CSV
│   └── report.py              # P0 离线评估指标
├── tests/                     # 单元测试
├── reports/                   # 体检报告、运行快照与归档，已 gitignore
├── data/                      # 人工标注数据，已 gitignore
├── .github/workflows/
│   └── daily.yml              # GitHub Actions 定时任务
└── README.md
```

## 快速开始

```bash
pip install -r requirements.txt

# 本地预览，不发邮件、不调用 AI
python main.py --preview preview.html --no-ai

# 正式运行并发邮件
python main.py
```

## 配置 config.json

```json
{
    "news_sources": [
        {
            "name": "CNBC Top News",
            "publisher": "CNBC",
            "type": "rss",
            "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "timeout": 8
        }
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": ""
    },
    "ai": [
        { "provider": "deepseek", "model": "deepseek-chat" }
    ],
    "prefer_categories": ["经济", "财经", "科技", "时政", "国际", "时事"],
    "max_articles": 15,
    "summary_language": "zh"
}
```

| 字段 | 说明 |
|------|------|
| `news_sources` | 新闻源列表，支持 `rss` 和 `html` 两种 type |
| `news_sources[].publisher` | 媒体名，用于“同一媒体多栏目”的配额；不填则用 `name` |
| `news_sources[].timeout` | 可选，抓取超时秒数，默认 15 |
| `email` | SMTP 邮箱配置 |
| `ai` | AI 摘要配置；当前只支持 `deepseek` |
| `prefer_categories` | 偏好类别；当前规则选稿中主要用于类别适配评分 |
| `max_articles` | 最大输出条数 |
| `summary_language` | 摘要语言，`zh` 或 `en` |
| `dedupe_threshold` | 可选，标题相似度阈值，默认 `0.9`，越小去重越激进 |
| `selection` | P1 选稿配置，见下文“P1 规则选稿” |

### 新闻去重

抓取后会跨站点去重，命中任一条件即视为重复：

- 规范化 URL 相同（忽略 `utm_*` 等跟踪参数、末尾斜杠、`www.` 前缀）；
- 规范化标题相同（忽略大小写、标点、HTML 实体、` - 来源` 后缀）；
- 长标题高度相似（相似度 ≥ `dedupe_threshold`，且数字/月份/星期一致）；
- 摘要高度相似（应对同一篇通稿被不同站点改标题转载）。

重复时保留发布时间最新、内容更全的一条。

### 文章分类

程序自动根据标题+内容关键词匹配分类，控制台会显示类别标签，如 `[时事]` `[经济]` `[科技]`。

支持类别：时事、经济、时政、财经、国际、科技。

### AI 配置

当前只支持 DeepSeek；遇到其他 provider 会跳过，并回退到本地摘要。

```json
"ai": [
    { "provider": "deepseek", "model": "deepseek-chat" }
]
```

`api_key` 可以从 `DEEPSEEK_API_KEY` 环境变量读取。不配 AI 或调用失败时，自动降级为本地取首句/摘要。

### P1 规则选稿

`selection` 控制是否启用两阶段选稿、候选池大小、事件聚类阈值和各类配额：

```json
"selection": {
    "enabled": true,
    "candidate_pool": 30,
    "event_window_hours": 36,
    "event_threshold": 0.58,
    "max_cluster_size": 5,
    "per_source_max": 3,
    "per_publisher_max": 4,
    "per_event_max": 1,
    "category_min": { "经济": 2, "时政": 1, "国际": 1 },
    "weights": {
        "importance": 0.30,
        "info_density": 0.20,
        "source_weight": 0.20,
        "recency": 0.15,
        "category_fit": 0.10,
        "fulltext": 0.05
    },
    "default_source_weight": 0.75,
    "noise_penalty": 0.25,
    "noise_title_patterns": [
        "stock movers", "live updates", "here's what to know",
        "what to know", "5 things", "markets wrap", "week ahead",
        "podcast", "transcript", "opinion", "current price of"
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
        "Federal Reserve": 0.90
    }
}
```

流程：

```text
抓取 → 去重 → 24h 过滤 → 每源最新 8 篇
     → 事件聚类 + 粗评分，选 30 篇候选
     → 只抓候选正文
     → 精评分 + 类别保底 + 来源/媒体/事件配额
     → 15 篇
```

配额是软约束：先放宽单栏目上限，再放宽媒体上限，最后才放宽事件上限，避免邮件条数不足。

## 常用操作

### 本地预览

```bash
# 只生成 HTML，不发邮件；跳过 AI，最快
python main.py --preview preview.html --no-ai

# 预览并输出每篇的选稿分数、事件、覆盖来源和理由
python main.py --preview preview.html --no-ai --explain-selection

# 只跑前 5 篇，便于调试
python main.py --preview preview.html --no-ai --limit 5

# 关闭 P1 规则选稿，回退到旧的“按时间取最新”
python main.py --preview preview-old.html --no-ai --no-selection
```

`preview*.html` 已在 `.gitignore` 中，不会提交。

### 新闻源体检（P0）

```bash
# 默认检查最近 2 天，抓取/解析/时效/重复/类别/正文抽样
python tools/diagnose.py --days 2

# 缩小正文抽样，减少耗时
python tools/diagnose.py --days 2 --sample-per-source 3 --output-dir reports/p1

# 只检查抓取/解析/重复，不抓正文
python tools/diagnose.py --days 1 --no-fulltext

# 测试一组候选源，不修改 config.json
python tools/diagnose.py --sources-json reports/candidate_sources.json
```

报告输出到 `reports/`：

- `source_scorecard.md`：Markdown 体检表
- `source_scorecard.json`：机器可读结果

重点看：

- `抓取=FAIL`：网络不通或被反爬，优先换源。
- `正文=0/N`：抽取器不适配或付费墙，邮件只能靠 RSS 摘要。
- `RSS 均长` 很短：即使正文抓不到，邮件里也没什么内容。
- `重复移除` 高：同源或跨源转载多，需要事件合并。
- `类别分布` 偏科：检查分类关键词或类别保底。

### 运行快照与归档（P0）

每次运行 `python main.py` 都会在 `reports/runs/<YYYY-MM-DD>/` 下生成三份产物，并作为附件随日报邮件发出：

| 文件 | 内容 |
|---|---|
| `run-YYYY-MM-DD.json` | 24h 内全部去重文章（含未进入候选池的）：评分、入选状态、落选原因、事件、正文来源，以及抓取/去重/选稿汇总 |
| `articles-YYYY-MM-DD.json` | 当日候选全文归档，作为后续 RAG 语料 |
| `labels-YYYY-MM-DD.csv` | 空标注表，`label` / `reason` 留空待填 |

选稿快照包含入选和落选两类候选，因此同一天的数据既能算 Precision 也能算 Recall。文章 `id` 由规范化 URL 生成，跨天稳定。

### 人工评测

人工评测分两层：

1. **选稿层**：该选的有没有选进来，不该选的有没有混进来。
2. **内容层**：正文、翻译、摘要是否准确、完整、值得读。

#### 评分标准

| label | 含义 | 判断标准 |
|---|---|---|
| 4 | 必读 | 影响经济/政策/地缘判断，有机制、数字、因果，值得记笔记 |
| 3 | 有用 | 有信息增量，能帮助理解一件事 |
| 2 | 一般 | 知道即可，缺背景/机制/影响 |
| 1 | 噪音 | 行情播报、个股涨跌、软文、重复、标题党 |

`reason` 建议使用固定枚举：`重要`、`可学习`、`重复`、`标题党`、`源太弱`、`正文缺失`、`翻译错误`、`分类错误`、`其他`。

内容层可以再加两列 1–5 分：

- `body_score`：正文是否完整，是否是正文而不是导航/摘要。
- `trans_score`：中文标题/摘要是否准确，是否漏掉关键信息。

#### 生成标注文件

标注样本直接来自运行快照，不再重新抓取网络：

```bash
# 用最新一次运行的快照，生成全部候选（含落选）
python tools/label_sample.py

# 指定快照，并只取前 30 条
python tools/label_sample.py --from-snapshot reports/runs/2026-11-15/run-2026-11-15.json --n 30

# 覆盖已存在的 CSV
python tools/label_sample.py --force
```

输出 `data/labels-<run_date>.csv`（已 gitignore），字段包括：

`id, source, publisher, published, category, score, selected, event_id, text_source, title, link, summary, label, reason`

用 Excel 或编辑器填写 `label` 和 `reason`。因为样本同时包含 `selected=1` 和 `selected=0` 的候选，可以直接计算 Precision 和 Recall。

#### 离线评估

```bash
# 使用最新快照自动补齐 score / text_source / event_id
python tools/report.py data/labels-2026-11-15.csv

# 指定快照，或改变 Precision@N 的 N
python tools/report.py data/labels-2026-11-15.csv \
  --snapshot reports/runs/2026-11-15/run-2026-11-15.json --total 15

# 机器可读输出
python tools/report.py data/labels-2026-11-15.csv --json
```

输出 Precision@15、Recall、噪音率、正文覆盖率、最大来源/媒体占比、事件重复率和标签分布，不访问网络。

#### 采样方法

只标选中的 15 篇，只能算 precision，算不出 recall。建议每次抽 30 篇：

- 15 篇：当前规则选中的。
- 15 篇：被规则淘汰的候选，按分数从高到低取，或随机抽。

标注时隐藏 `score`、`selected` 状态和来源权重，只给标题 + 摘要 + 链接，避免被模型分数带偏。

#### 指标

| 指标 | 算法 | 建议目标 |
|---|---|---|
| Precision@15 | 选中且 label≥3 的数量 / 15 | 先测基线，建议 ≥ 0.7 |
| Recall@15 | 选中且 label≥3 的数量 / 所有 label≥3 的数量 | 建议 ≥ 0.5 |
| 噪音率 | 选中里 label=1 的比例 | 建议 ≤ 10% |
| 正文覆盖率 | `text_source=page` 的比例 | 建议 ≥ 70% |
| 翻译准确率 | `trans_score≥4` 的比例 | 建议 ≥ 90% |
| 事件重复率 | 同一事件多篇 / 总篇数 | 建议 ≤ 10% |
| 来源集中度 | 最大来源或最大媒体占比 | 单源 ≤ 30%，单媒体 ≤ 40% |

先记录 3–5 天的基线，再改规则看趋势。

#### 节奏

- 每天 10 分钟：只标当天 15 篇，快速看噪音和正文质量。
- 每周 30 分钟：抽 30 篇做一次“选中 + 落选”盲评，算 Precision/Recall。
- 每两周：只根据累计数据调一次权重，不要每天改。
- 固定留 3 天、约 60 篇作为测试集，不参与调参，最后用它验收。

### 测试

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py modules tools tests
```

## 推荐的新闻源

### 中文

| 名称 | RSS 地址 | 类别 |
|------|---------|------|
| 36氪 | `https://36kr.com/feed` | 科技创投 |
| 华尔街见闻 | `https://wallstreetcn.com/rss` | 财经快讯 |
| 澎湃新闻 | `https://www.thepaper.cn/rss.xml` | 时事社会 |
| 观察者网 | `https://www.guancha.cn/rss.xml` | 时政国际 |
| 知乎日报 | `https://daily.zhihu.com/rss` | 综合 |

### 英文

| 名称 | RSS 地址 | 类别 |
|------|---------|------|
| Hacker News | `https://hnrss.org/frontpage` | 科技 |
| Reuters 首页 | `https://www.reutersagency.com/feed/` | 时事财经 |
| Reuters 科技 | `https://www.reutersagency.com/feed/?best-topics=tech` | 科技 |
| NYT 首页 | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml` | 综合 |
| NYT 国际 | `https://rss.nytimes.com/services/xml/rss/nyt/World.xml` | 国际 |
| NYT 经济 | `https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml` | 经济 |
| BBC 首页 | `https://feeds.bbci.co.uk/news/rss.xml` | 综合 |
| BBC 世界 | `https://feeds.bbci.co.uk/news/world/rss.xml` | 国际 |
| CNN 头条 | `https://edition.cnn.com/services/rss/` | 综合 |
| NPR | `https://feeds.npr.org/1001/rss.xml` | 时事 |
| The Guardian | `https://www.theguardian.com/world/rss` | 国际 |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` | 科技 |
| TechCrunch | `https://techcrunch.com/feed/` | 科技创投 |

> 部分源需翻墙。如失效可搜索替代地址。

## 环境变量

| 变量 | 用途 |
|------|------|
| `EMAIL_PASSWORD` | SMTP 授权码 |
| `EMAIL_SENDER` | 发件人邮箱（优先于 config.json） |
| `EMAIL_RECEIVER` | 收件人邮箱（优先于 config.json） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |

## GitHub Actions

Secrets 配置：

| Secret | 说明 |
|--------|------|
| `EMAIL_PASSWORD` | SMTP 授权码 |
| `EMAIL_SENDER` | 发件人邮箱 |
| `EMAIL_RECEIVER` | 收件人邮箱 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |

每天北京时间 8:00 自动运行。


