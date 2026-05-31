# VLA Spider - VLA & 具身智能信息聚合爬虫

每日自动爬取 VLA、具身智能领域的论文、公司动态、技术资讯，输出为 Markdown 日报。

## 数据源

| 类型 | 来源 |
|------|------|
| 📄 论文 | arXiv cs.RO / cs.AI / cs.CV / cs.LG |
| 🌍 国际公司 | PI、Figure AI、1X、Agility、Boston Dynamics、DeepMind、OpenAI |
| 🇨🇳 国内公司 | 宇树、智元、傅里叶、优必选、开普勒、乐聚、达闼 |
| 📰 行业媒体 | 机器之心、量子位、新智元（需 RSSHub）/ TechCrunch / MIT News |
| 💻 GitHub | VLA/具身相关 trending 仓库 |
| 🔍 搜索补充 | Serper.dev Google 搜索（可选，2500 次/月免费） |
| 💬 社区 | 知乎、Bilibili（需 RSSHub） |

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
# 本地如有 SOCKS 代理，还需：
pip install "httpx[socks]"
```

### 运行

```bash
# 完整运行（需配置环境变量）
python main.py

# 仅测试 arXiv + GitHub
python main.py --skip-rss --skip-blogs --skip-serper --no-ai

# 跳过 AI 分析
python main.py --no-ai

# 指定日期
python main.py --date 2026-05-30
```

### 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `GITHUB_TOKEN` | GitHub API token（避免速率限制） | 推荐 |
| `ANTHROPIC_API_KEY` | Claude API key（AI 摘要，GitHub Actions 用） | 可选 |
| `RSSHUB_URL` | 自建 RSSHub 实例 URL，如 `http://rsshub.app` | 可选 |
| `GEMINI_API_KEY` | Gemini API key，用于 Search 爬取 + AI 分析（免费）| 推荐 |

## 部署到 GitHub Actions

1. Fork/创建本 repo
2. 在 repo Settings → Secrets 中添加上表环境变量
3. Actions 已配置每天 UTC 01:00（北京 09:00）自动运行
4. 结果自动 commit 到 `output/YYYY-MM-DD/` 目录

**手动触发**：Actions → Daily VLA Intelligence Crawl → Run workflow

## 本地定时运行

```bash
# 添加 crontab（每天北京时间 09:00）
crontab -e

# 加入以下行（替换路径）：
0 9 * * * /data/app/miniconda3/envs/dev/bin/python main.py >> logs/cron.log 2>&1
```

## 使用 Claude Code CLI 做 AI 分析（本地）

当 `claude` CLI 可用时，`python main.py` 会自动调用它做分析，使用你的 Claude Code 额度，无需额外 API key。

## 配置说明

编辑 `config/sources.yaml` 可以：
- 添加/移除关注的公司博客
- 调整 arXiv 关键词和分类
- 添加 Serper 自定义搜索查询
- 配置 AI 模型（默认 claude-haiku-4-5，最便宜）

## 输出格式

每日生成两个文件：
- `output/YYYY-MM-DD/report.md` — 可读 Markdown 日报
- `output/YYYY-MM-DD/raw.json` — 完整原始数据

## 中文社交媒体说明

| 平台 | 状态 | 方案 |
|------|------|------|
| 微信公众号 | 🟡 需自建 | 部署 [WeWe RSS](https://github.com/cooderl/wewe-rss)，生成 RSS 后填入配置 |
| 知乎 | 🟡 需 RSSHub | 配置 `RSSHUB_URL` |
| 小红书 | 🔴 难度大 | 需 Cookie + 浏览器，暂不支持 |
| 36kr 机器人 | 🟡 需 RSSHub | 配置 `RSSHUB_URL` |
