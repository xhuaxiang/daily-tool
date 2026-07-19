# 每日新闻早报 (Daily News Brief)

自动抓取 RSS/HTML 新闻源，生成摘要，支持控制台查看和邮件推送。

## 项目结构

```
.
├── main.py                # 入口，直接 python main.py 运行
├── config.json            # 配置文件（新闻源、邮箱等）
├── requirements.txt       # Python 依赖
├── modules/
│   ├── config.py          # 配置加载
│   ├── fetcher.py         # 网络抓取
│   ├── parser.py          # RSS / HTML 解析
│   ├── summarizer.py      # Gemini AI / 本地摘要
│   └── mailer.py          # SMTP 邮件发送
└── README.md
```

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

首次运行会使用内置默认配置，直接从 `config.json` 读取。

## 配置 config.json

```json
{
    "news_sources": [
        {
            "name": "36氪",
            "type": "rss",
            "url": "https://36kr.com/feed"
        },
        {
            "name": "Hacker News",
            "type": "rss",
            "url": "https://hnrss.org/frontpage"
        }
    ],
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 587,
        "sender_email": "",
        "receiver_email": ""
    },
    "max_articles": 15,
    "summary_language": "zh"
}
```

| 字段 | 说明 |
|------|------|
| `news_sources` | 新闻源列表，支持 `rss` 和 `html` 两种 type |
| `email` | SMTP 邮箱配置 |
| `max_articles` | 最大输出条数 |
| `summary_language` | 摘要语言，`zh` 或 `en` |

## 环境变量（可选）

| 变量 | 用途 |
|------|------|
| `GEMINI_API_KEY` | 设置后启用 Gemini AI 生成摘要（否则使用本地提取首句） |
| `GEMINI_MODEL` | Gemini 模型名，默认 `gemini-2.0-flash-lite` |
| `EMAIL_PASSWORD` | SMTP 授权码，设置后可邮件推送 |
