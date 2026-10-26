# 每日影视故事梗概（Daily Movie Story）

每天自动挑一部电影或电视剧，用 AI 把它**按时间线拆成若干段故事梗概**，生成方便阅读的 Markdown 和单文件 HTML。

> 例：一部 120 分钟的电影按每 10 分钟一段，自动产出 12 段剧情梗概；一部长剧则每集拆 2–3 段。

---

## 它做什么

- **自动选片**：按 `data/catalog.tsv` 片库顺序轮播，今天没生成过的就生成，全部轮完再从头循环。
- **分段梗概**：先用一次调用生成全片大纲（一句话故事 / 主要人物 / 故事脉络 / 关键转折 / 主题），再分批生成每一段的剧情梗概。
- **两种格式**：同一天生成 `日期_片名.md`（便于存档与再编辑）和 `日期_片名.html`（带分段导航、时间轴卡片、深浅色自适应，浏览器直接打开最好读）。
- **邮件推送**：生成完自动把当天内容发到你的邮箱（正文是排好版的 HTML，另附 .md 和 .html 两个文件）。
- **总索引**：每次生成后自动更新 `索引.md` / `索引.html`，点击即可跳到任意一天的作品。
- **健壮**：自带重试、JSON 容错解析、字数质检（偏短的段落自动重写）、原子写入、详细日志。

## 分段规则

| 类型 | 切分方式 |
| --- | --- |
| 电影 | 按真实片长 ÷ 10 分钟一段（2 小时片 ≈ 12 段），范围 6–20 段 |
| 电视剧 | 每集拆 2 段；单集超过 50 分钟自动拆 3 段 |

> 片长和集数由 AI 根据公开资料推断，也可用片库里的 `duration` 列手动指定电影片长。

---

## 目录结构

```
movie_story_automation/
├── .env                  # 运行配置（含密钥，已被 .gitignore 排除）
├── .env.example          # 配置模板
├── run.py                # 便捷入口
├── moviestory/           # 核心代码
│   ├── config.py         # 配置加载（.env 解析）
│   ├── catalog.py        # 片库读取 + 每日选片轮播 + 状态记录
│   ├── llm.py            # 大模型调用（重试 + JSON 容错）
│   ├── generator.py      # 大纲 + 分批分段梗概
│   ├── render.py         # Markdown / HTML / 邮件正文 / 索引页渲染
│   ├── mailer.py         # SMTP 邮件发送
│   ├── store.py          # 结果快照（支持失败后重发）
│   └── main.py           # 命令行入口
├── data/
│   ├── catalog.tsv       # 片库（标题/国家/类型/年份/题材/集数/剧情参考）
│   └── snapshots/        # 生成结果快照，用于重发邮件
├── scripts/
│   ├── run_daily.ps1     # 计划任务调用的脚本（云端优先，本机兜底）
│   └── install_task.ps1  # 注册 Windows 计划任务
├── .github/workflows/
│   └── daily.yml         # 云端定时任务（GitHub Actions）
├── tests/
│   └── test_core.py      # 离线自测（不调接口）
├── output/               # 生成结果存档（云端提交回仓库）
└── logs/                 # 每日运行日志
```

---

## 安装

1. 安装 Python 3.10+（本项目自带托管 Python 路径，无需额外安装也可直接跑）。
2. 准备 `.env`：

   ```
   copy .env.example .env
   ```

   然后填入密钥（见下）。

## 配置（.env）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `MOVIE_API_KEY` | 大模型 API Key（任意 OpenAI 兼容接口） | 必填 |
| `MOVIE_API_BASE` | 接口地址 | `https://api.deepseek.com` |
| `MOVIE_MODEL` | 模型名 | `deepseek-chat` |
| `MOVIE_OUTPUT_DIR` | 生成文件存放目录 | `E:/liqiaobac/每日影视故事梗概` |
| `MOVIE_SEGMENT_MINUTES` | 电影每多少分钟一段 | `10` |
| `TV_SEGMENTS_PER_EPISODE` | 电视剧每集拆几段 | `2` |
| `MOVIE_TEMPERATURE` | 生成温度 | `0.65` |
| `MOVIE_TIMEOUT` / `MOVIE_MAX_RETRIES` | 超时与重试 | `180` / `4` |
| `MOVIE_BATCH_SIZE` / `TV_BATCH_SIZE` | 每批生成几段 | `8` / `6` |
| `MOVIE_SMTP_HOST` / `MOVIE_SMTP_PORT` | 邮件服务器 | `smtp.163.com` / `465` |
| `MOVIE_SMTP_USER` / `MOVIE_SMTP_PASS` | 发件邮箱与授权码 | 必填（163 用客户端授权码，不是登录密码） |
| `MOVIE_SMTP_TO` | 收件邮箱 | 默认与发件人相同 |
| `MOVIE_SMTP_SSL` | `1` = 465 隐式 SSL，`0` = 587 STARTTLS | `1` |

> 模型与接口走 OpenAI 兼容协议，换成任意支持该协议的服务（DeepSeek、通义、GLM、本地 vLLM 等）只需改 `MOVIE_API_BASE` 和 `MOVIE_MODEL`。

## 使用

```bash
# 按片库轮播，生成今天的作品
python run.py

# 指定某部作品（无论片库轮到哪部）
python run.py --title 漫长的季节

# 预览：只生成大纲 + 打印分段计划，不落盘
python run.py --title 霸王别姬 --dry-run

# 重新生成并覆盖已存在的文件
python run.py --title 霸王别姬 --force

# 列出片库
python run.py --list

# 生成但不发邮件
python run.py --no-email

# 邮件发失败了，用上次的结果重发（不重新调用接口、不烧额度）
python run.py --resend
python run.py --resend --title 霸王别姬

# 离线自测（不消耗接口额度）
python -m unittest discover -s tests -v
```

## 每天自动运行（云端，电脑关机也能跑）

程序已部署在 **GitHub Actions** 上，每天北京时间 **09:07** 自动生成并把邮件发出去，**不需要你的电脑开机**。

- 工作流：`.github/workflows/daily.yml`（cron `7 1 * * *` UTC）
- 密钥存放在仓库的 GitHub Secrets（加密存储，不进代码库）
- 产出物提交回 `output/` 目录存档
- 网页版：<https://cdn.jsdelivr.net/gh/happyliqiao/daily_movie_story@master/output/>
  （总索引是 `output/索引.html`，中文文件名在链接里需 URL 编码）
- 手动触发一次：仓库页面的 Actions → 「每日影视故事梗概」→ Run workflow

### 本机兜底（可选）

本机也留了一个 Windows 计划任务「每日影视故事梗概」，每天 09:00 运行。它会先拉取云端结果：

- 云端今天已经生成过 → 只把结果同步到本地 `E:\liqiaobac\每日影视故事梗概`，**不再重复生成、不重复发邮件**
- 云端失败或没跑 → 本机兜底生成、发邮件，并把结果提交回仓库

```powershell
# 注册/更新本机计划任务
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -Time 09:00

# 立即试跑一次
Start-ScheduledTask -TaskName '每日影视故事梗概'

# 手动跑今天的
powershell -ExecutionPolicy Bypass -File .\scripts\run_daily.ps1
```

## 添加 / 维护片库

打开 `data/catalog.tsv`，按原有表头追加一行（**不要删除表头**）。字段：

`title` 片名 · `country` 国家/地区 · `type` 电影/电视剧 · `year` 年份 · `genre` 题材 · `episodes` 集数（电影留空）· `synopsis` 一句话剧情参考（可选，给 AI 多一份依据）· `duration` 片长分钟（电影可选，覆盖 AI 推断）

## 输出文件

- 命名：`YYYY-MM-DD_片名.md` 与 `YYYY-MM-DD_片名.html`，存放在 `MOVIE_OUTPUT_DIR`。
- 一份内容两种形态：`.md` 适合二次编辑与归档，`.html` 适合阅读，自带分段目录导航（滚动高亮当前段）、人物卡片、时间轴卡片、深色模式。
- `索引.html`：所有作品的总目录，双击即可打开当天那份。

## 说明与边界

- 梗概由 AI 依据公开剧情整理，可能存在记忆偏差或细节演绎，仅供阅读参考，请勿当作考据。
- 生成质量依赖模型能力；若某段偏短或缺失，加 `--force` 重跑即可（当天已存在会跳过，需 `--force`）。
- 多段生成为分批调用，长剧（如 76 集）会产出上百段、消耗较多接口额度与时间，属正常现象。
