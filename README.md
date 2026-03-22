# ⚽ 北伦敦24小时 · 自动播客

**你还在每天花大量时间刷新闻吗？**

作为阿森纳球迷，我们懂这种感觉——早上醒来想第一时间知道昨晚发生了什么，结果翻遍 BBC、天空体育、The Athletic，每个平台都要打开看，还不一定凑得齐所有想知道的资讯。

**这件事，我们帮你自动化了。**

---

## 🎙️ 这是什么？

「北伦敦24小时」是一个全自动化的阿森纳播客流水线。

每天自动抓取阿森纳、竞争对手、英超的最新新闻，生成一期10-12分钟的中文口播稿，由 AI 主播「萨卡」用充满球迷气息的语气读给你听。

- 📰 自动抓取 20+ 新闻源（BBC Sport、Sky Sports、The Athletic、Arsenal.com...）
- ✍️ AI 生成播报稿，保证信息密度和可听性
- 🎤 TTS 文字转语音，中文语音输出
- ☁️ 自动上传 Cloudflare R2，生成 RSS 方便订阅
- ⏰ Cron 定时触发，真正无人值守

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)（或 pip）
- Tavily API Key（免费注册：https://tavily.com）
- Cloudflare R2 账号（可选，用于音频托管）

### 安装

```bash
# 克隆仓库
git clone https://github.com/shooter119/auto-podcast.git
cd auto-podcast

# 安装依赖
uv sync

# 复制配置
cp config.yaml.example config.yaml
```

### 配置

编辑 `config.yaml`，填入你的 keys：

```yaml
tavily:
  api_key: "YOUR_TAVILY_API_KEY"

r2:
  account_id: "YOUR_R2_ACCOUNT_ID"
  access_key_id: "YOUR_R2_ACCESS_KEY_ID"
  secret_access_key: "YOUR_R2_SECRET_ACCESS_KEY"
  bucket: "your-bucket"
  public_url: "https://your-domain.com"
```

### 本地运行

```bash
# 检查环境
bash scripts/check_env.sh

# 干跑测试（不生成音频）
bash scripts/run.sh --dry-run

# 正式运行
bash scripts/run.sh
```

---

## 📁 项目结构

```
auto-podcast/
├── config.yaml              # 配置文件（不提交到 Git）
├── config.yaml.example     # 配置模板
├── main.py                # 入口文件
├── requirements.txt        # Python 依赖
├── SKILL.md               # OpenClaw Skill 说明
├── scripts/
│   ├── check_env.sh       # 环境检查
│   └── run.sh             # 运行脚本
├── src/
│   ├── searcher.py        # 新闻搜索（Tavily）
│   ├── scraper.py         # 文章内容抓取
│   ├── relevance.py        # 足球相关性过滤
│   ├── dedup.py           # 新闻去重
│   ├── script_generator.py # 播客脚本生成
│   ├── tts.py             # 语音合成
│   ├── uploader.py        # R2 上传
│   └── rss.py             # RSS 生成
├── templates/
│   └── prompt.txt         # 播客生成 Prompt
└── crontab.example        # 定时任务示例
```

---

## ⚙️ 配置说明

### 新闻源分组

| 分组 | 说明 | 默认条数 |
|------|------|---------|
| `arsenal_core` | 阿森纳相关 | 14 条 |
| `rivals` | 竞争对手（曼城、利物浦等） | 6 条 |
| `league` | 英超/欧冠/转会市场 | 6 条 |

### 内容质检

流水线内置质检门控：
- 字数范围：1800-2800 字
- 必须包含"英超江湖"或"尾声"关键词
- 阿森纳内容占比 ≥70%
- 禁止 FPL、女足、Fantasy 相关内容

如需调整，修改 `config.yaml` 中的 `content` 节。

### 去重策略

| 类型 | 冷却时间 |
|------|---------|
| 比赛新闻 | 24 小时 |
| 转会新闻 | 18 小时 |
| 一般新闻 | 12 小时 |

---

## 🔧 定时任务

编辑 crontab：

```bash
# 每天 UTC 22:00（北京次日 06:00）运行
0 22 * * * cd /path/to/auto-podcast && bash scripts/run.sh >> /var/log/arsenal-podcast.log 2>&1
```

或使用 OpenClaw Cron Job 调用 agentTurn 触发。

---

## 🛠️ 自定义

### 换主队

修改 `config.yaml` 中的 `team` 节：

```yaml
team:
  name: "Manchester United"
  name_cn: "曼联"
  league: "Premier League"
```

然后调整 `keywords` 中的查询词即可。

### 换音色/语速

```yaml
tts:
  voice: "zh-CN-YunxiNeural"  # 支持多种中文音色
  rate: "+5%"                  # 语速调整
```

### 改 Prompt

`templates/prompt.txt` 里有完整的生成规则，可以按需调整主播人设、段落结构、口头禅等。

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

如果你优化了质检规则、扩充了新闻源、或者适配了其他球队，强烈建议开个 PR 让大家一起用。

---

## ⚠️ 免责声明

播客内容由 AI 自动生成，新闻事实来源于第三方搜索结果，可能存在偏差或不准确之处。

阿森纳是冠军。🫡

---

**COYG！**
