# Auto Podcast

一个面向阿森纳球迷的自动化播客生成项目。它会抓取过去 24 小时内的足球新闻，筛选出和阿森纳最相关的内容，生成中文口播脚本，合成音频，上传到 Cloudflare R2，并更新 RSS feed。

默认播客节目名是「北伦敦24小时」，默认主播人设是“萨卡”风格的中文球迷主播。

## 功能概览

- 用 Tavily 拉取最新新闻，并按关键词组分桶检索
- 对新闻源做分级，只保留质量更高的来源
- 抓取正文、做足球相关性过滤，并识别比赛 / 转会 / 伤病等类型
- 基于历史记录做去重，避免同一条新闻反复播报
- 调用 OpenClaw 生成中文播客脚本，并带一轮质量检查
- 使用 `edge-tts` 合成 MP3 音频
- 上传音频到 Cloudflare R2
- 自动生成或更新 `feed.xml`，可直接喂给播客客户端
- 支持 `--dry-run`、`--run-id`、`--step`，方便调试和断点恢复

## 工作流

项目入口是 [`main.py`](./main.py)，默认按下面 8 个步骤执行：

1. `search`: 搜索新闻
2. `scrape`: 抓取正文
3. `filter`: 过滤非足球或非阿森纳主线内容
4. `dedup`: 基于历史记录去重
5. `script`: 生成播客脚本
6. `tts`: 合成音频
7. `upload`: 上传音频到 R2
8. `rss`: 更新 RSS feed

如果某一步失败，可以用已有 `run_id` 从中间继续跑。

## 目录结构

```text
.
├── main.py
├── config.yaml.example
├── requirements.txt
├── scripts/
│   ├── check_env.sh
│   └── run.sh
├── src/
├── templates/
│   └── prompt.txt
└── output/
    ├── history.json
    ├── logs/
    └── runs/
        └── <run_id>/
            ├── articles.json
            ├── podcast.mp3
            ├── script.txt
            └── state.json
```

## 环境要求

- Python 3.10 或更高
- 可以访问外网的运行环境
- 一个可用的 Tavily API Key
- 一个可用的 OpenClaw 网关
- 一个可写入的 Cloudflare R2 bucket

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 准备配置文件

复制示例配置：

```bash
cp config.yaml.example config.yaml
```

然后按你的环境修改 `config.yaml`。

### 3. 准备环境变量

在项目根目录创建 `.env`：

```env
TAVILY_API_KEY=your_tavily_api_key
OPENCLAW_GATEWAY_TOKEN=optional_if_your_gateway_requires_auth
R2_ACCOUNT_ID=your_r2_account_id
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_PUBLIC_URL=https://your-public-domain-or-r2-dev-url
```

说明：

- `OPENCLAW_GATEWAY_TOKEN` 只有在你的网关启用了鉴权时才需要
- `R2_PUBLIC_URL` 会被用于拼接音频直链和 RSS 链接
- `config.yaml` 中的 `${VAR_NAME}` 会在运行时自动解析成 `.env` 里的值

### 4. 做一次环境检查

```bash
scripts/check_env.sh
```

这个脚本会检查：

- `.env` 是否存在
- 关键环境变量是否齐全
- 虚拟环境是否存在
- Python 依赖是否可导入
- OpenClaw 网关是否可访问
- `config.yaml` 是否能通过校验

### 5. 先跑一次 dry run

```bash
scripts/run.sh --dry-run
```

`dry-run` 会生成新闻中间结果和脚本，但不会合成音频，也不会上传。

### 6. 正式生成一期播客

```bash
scripts/run.sh
```

## 常用命令

### 直接运行主程序

```bash
python main.py
```

### 只生成脚本，不做 TTS / 上传

```bash
python main.py --dry-run
```

### 从某一步继续执行

```bash
python main.py --run-id 20260322_080000 --step upload
```

`--step` 可选值：

- `search`
- `scrape`
- `filter`
- `dedup`
- `script`
- `tts`
- `upload`
- `rss`

## 配置说明

主要配置都在 [`config.yaml.example`](./config.yaml.example) 里。

### `team`

定义主队信息，比如 `Arsenal / 阿森纳 / Premier League`。

### `host`

定义主播名字、口播风格、常用口头禅和人设描述。这些内容会直接影响脚本生成的语气。

### `keywords`

新闻检索关键词分组，默认分成：

- `arsenal_core`: 阿森纳主线
- `rivals`: 争冠或主要竞争对手
- `league`: 联赛和外围上下文

每个组都可以配置：

- `queries`
- `max_results`
- `final_limit`
- `restrict_to_sources`

### `sources`

按域名给新闻源分级。项目会优先保留更高质量的来源，低质量来源会被过滤掉。

### `tavily`

搜索引擎配置，至少需要 `api_key`。

### `openclaw`

脚本生成模型配置，包括：

- `gateway_url`
- `model`
- `agent_id`
- `auth_token`
- `timeout_seconds`
- `temperature`

### `tts`

TTS 配置，默认使用 `zh-CN-YunxiNeural`。

### `r2`

Cloudflare R2 配置，负责存放音频和 `feed.xml`。

### `podcast`

播客基础信息，比如标题、描述、作者、语言，以及 RSS 中保留的最大 episode 数量。

### `content`

控制口播时长、字数、阿森纳主线占比和各类新闻配额。

### `dedup`

控制新闻去重策略，包括不同类型新闻的冷却时间、标题相似度阈值，以及历史记录文件路径。

## 输出说明

运行完成后，结果会写到 `output/`：

- `output/runs/<run_id>/articles.json`: 每次运行保留下来的新闻结果
- `output/runs/<run_id>/script.txt`: 生成的播客脚本
- `output/runs/<run_id>/podcast.mp3`: 本次生成的音频
- `output/runs/<run_id>/state.json`: 每一步的执行状态、产物路径和指标
- `output/logs/*.log`: 按日期输出的运行日志
- `output/history.json`: 去重历史，用来避免连续几期重复播报

## RSS 与发布

正式执行时，项目会：

- 把音频上传到类似 `episodes/YYYYMMDD/podcast_<run_id>.mp3` 的路径
- 更新 R2 中的 `feed.xml`
- 通过 `R2_PUBLIC_URL/feed.xml` 暴露 RSS 地址

因此播客的最终订阅地址通常是：

```text
https://your-public-url/feed.xml
```

注意：RSS 中默认引用 `cover.png` 作为播客封面，也就是：

```text
https://your-public-url/cover.png
```

如果你希望播客客户端显示封面，请自行把 `cover.png` 上传到对应的公开路径。

## 定时运行

项目自带一个示例 [`crontab.example`](./crontab.example)。

例如每天早上 8 点执行一次：

```cron
0 8 * * * cd "/path/to/auto-podcast-skill" && /usr/bin/python3 main.py --run-id "$(date +\%Y\%m\%d_\%H\%M\%S)" >> output/cron.log 2>&1
```

如果你已经用 OpenClaw 或其他任务调度器做托管，也可以直接执行：

```bash
python main.py
```

## 故障排查

### `配置校验失败`

通常表示：

- `config.yaml` 没有创建
- `.env` 中缺少必填变量
- `config.yaml` 中某些 `${VAR}` 没有被正确解析

先跑：

```bash
scripts/check_env.sh
```

### OpenClaw 无法访问

检查：

- `openclaw.gateway_url` 是否正确
- 网关是否启动
- 如果网关要求鉴权，`.env` 中是否配置了 `OPENCLAW_GATEWAY_TOKEN`

### 上传失败

上传失败时，本地音频不会丢，可以用同一个 `run_id` 重试：

```bash
python main.py --run-id 20260322_080000 --step upload
```

### 去重后没有新闻

项目已经做了 fallback 保护；如果所有候选都命中历史去重，会保留少量高优先级新闻，避免当天完全没有内容。

## 开发建议

- 先用 `--dry-run` 调整提示词和筛选逻辑
- 重点关注 `templates/prompt.txt`、`src/script_generator.py` 和 `config.yaml`
- 如果想改节目风格，优先修改 `host`、`podcast` 和 `content`
- 如果想提高新闻质量，优先调整 `keywords` 和 `sources`

## 安全说明

- `.env`、`config.yaml` 和 `output/` 已经在 `.gitignore` 中，不会默认提交
- 不要把 API Key、R2 密钥或 OpenClaw token 写进代码仓库
- 调试时优先分享 `output/logs/` 中的日志，不要直接贴出完整密钥
