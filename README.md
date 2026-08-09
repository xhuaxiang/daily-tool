# 每日新闻早报 (Daily News Brief)

自动抓取 RSS/HTML 新闻源，按类别偏好排序，生成 AI/本地摘要，支持控制台查看和邮件推送。

## 项目结构

```
.
├── main.py                    # 入口，直接 python main.py 运行
├── config.json                # 配置文件（新闻源、邮箱、AI、偏好类别等）
├── requirements.txt           # Python 依赖
├── modules/
│   ├── config.py              # 配置加载
│   ├── fetcher.py             # 网络抓取
│   ├── parser.py              # RSS / HTML 解析
│   ├── categorizer.py         # 文章分类 & 偏好排序
│   ├── summarizer.py          # AI（Gemini/DeepSeek等）/ 本地摘要
│   └── mailer.py              # SMTP 邮件发送
├── .github/workflows/
│   └── daily.yml              # GitHub Actions 定时任务
└── README.md
```

## 快速开始

```bash
pip install requests beautifulsoup4 lxml
python main.py
```

## 配置 config.json

```json
{
    "news_sources": [
        { "name": "36氪", "type": "rss", "url": "https://36kr.com/feed" }
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": ""
    },
    "ai": [
        { "provider": "gemini", "model": "gemini-2.0-flash-lite" }
    ],
    "prefer_categories": ["时事", "经济", "时政", "财经", "国际"],
    "max_articles": 15,
    "summary_language": "zh"
}
```

| 字段 | 说明 |
|------|------|
| `news_sources` | 新闻源列表，支持 `rss` 和 `html` 两种 type |
| `email` | SMTP 邮箱配置 |
| `ai` | AI 摘要配置列表（支持多个，按序尝试） |
| `prefer_categories` | 偏好类别，匹配的文章优先展示 |
| `max_articles` | 最大输出条数 |
| `summary_language` | 摘要语言，`zh` 或 `en` |

### 文章分类

程序自动根据标题+内容关键词匹配分类，控制台会显示类别标签，如 `[时事]` `[经济]` `[科技]`。

支持类别：时事、经济、时政、财经、国际、科技。

### AI 配置

支持多个 provider，按序尝试，第一个成功就用。

| provider | 说明 | 环境变量 | 默认模型 |
|----------|------|---------|---------|
| `gemini` | Google Gemini | `GEMINI_API_KEY` | `gemini-2.0-flash-lite` |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| `openai-compat` | 兼容 OpenAI 接口 | 自定义 | `gpt-4o-mini` |

**DeepSeek 示例：**
```json
"ai": [
    { "provider": "deepseek", "model": "deepseek-v4-flash" },
    { "provider": "gemini", "model": "gemini-2.0-flash-lite" }
]
```

**第三方（如 SiliconFlow）：**
```json
"ai": [{
    "provider": "openai-compat",
    "api_key_env": "SILICONFLOW_API_KEY",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "base_url": "https://api.siliconflow.cn/v1"
}]
```

不配 AI 时自动降级为本地取首句。

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
| `GEMINI_API_KEY` | Gemini API Key |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |

## GitHub Actions

Secrets 配置：

| Secret | 说明 |
|--------|------|
| `EMAIL_PASSWORD` | SMTP 授权码 |
| `EMAIL_SENDER` | 发件人邮箱 |
| `EMAIL_RECEIVER` | 收件人邮箱 |
| `GEMINI_API_KEY` | (可选) Gemini Key |

每天北京时间 8:00 自动运行。


