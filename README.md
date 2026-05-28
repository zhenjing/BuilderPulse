# BuilderPulse + HNdaily — Claude Code 技能包

> 每天自动分析 300+ 公开信号，生成面向独立开发者的中文产品机会日报。
>
> _Daily product opportunity reports for indie hackers, powered by Claude Code._

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC_BY--NC_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-skill-orange.svg)](https://claude.ai/code)

---

## 这是什么？

一个 Claude Code 技能包，包含两个互补的日报 skill：

| Skill | 触发 | 数据源 | 产出 |
|-------|------|--------|------|
| **HNdaily** | `/HNdaily` | HN 首页 Top 80 | `HackerNews_{date}.md` — AI 需求全景 + Top 5 产品机会 |
| **Trending Analyzer** | `/trending` | GitHub Trending 页面 + API 富化 | `TrendingAnalysis_{date}.md` — 逐仓库三维分析 + 商业化判断 |
| **BuilderPulse** | `/BuilderPulse` | HN + GitHub + HuggingFace + Reddit + Lobsters + DEV + PH | `BuilderPulse_{date}.md` — 9 段产品日报 |

### 核心设计

- **数据脚本** 负责抓取 → 打分 → 输出结构化 JSON（全 Python 标准库，零配置）
- **Claude** 负责阅读 JSON → 理解上下文 → 交叉验证 → 撰写报告
- **人机分工**：脚本做机械化的数据 ETL，AI 做需要判断力的信号筛选和叙事构建

---

## 快速开始

### 前置条件

- [Claude Code](https://claude.ai/code) CLI 已安装
- Python 3.8+（仅标准库）
- （可选）`pytrends` — Google Trends 校准数据源

```bash
pip install pytrends  # 可选，BuilderPulse 自动降级
```

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/liuxiaopai-ai/claude-code-builderpulse.git
cd claude-code-builderpulse

# 2. 启动 Claude Code
claude
```

两个 skill 自动注册（Claude Code 从 `.claude/skills/` 和 `CLAUDE.md` 发现 skill）。

### 使用

```
# HN 日报（约 30 秒数据抓取 + 2 分钟分析）
claude> /HNdaily

# 产品日报（约 3-5 分钟数据抓取 + 5 分钟分析）
claude> /BuilderPulse
```

---

## HNdaily — HN 日常分析

**问题：** HN 首页每天 80 篇文章，哪篇能变成产品？

**方法：** 双管线独立评分 → 2×2 矩阵交叉筛选：

| 象限 | complaint ≥ 5 | complaint < 5 |
|------|-------------|------------|
| **opp ≥ 3** | 🔥 头条机会 — 深度产品化分析 | 📡 弱信号 — **升级为产品机会** |
| **opp < 3** | 📰 背景噪音 — 情绪表格 | 🗑️ 跳过 |

报告结构：
1. 🤖 AI 需求全景 + 3 个可构建产品（🥇🥈🥉，含技术路线/定价/MVP 天数）
2. 🛠️ Top 5 产品机会（含产品化分析表）
3. 📰 今日情绪背景
4. 市场信号汇总 + 总体洞察

### 数据脚本

```bash
# 当天数据
python .claude/scripts/hn_analyzer.py

# 指定历史日期
python .claude/scripts/hn_analyzer_history.py 2026-05-15 .claude/hn_data.json
python .claude/scripts/hn_historical.py 2026-05-15 .claude/hn_data.json
```

**无外部依赖**，纯 Python 3 标准库，使用 Firebase API 获取当天数据，Algolia API 获取历史数据。

---

## Trending Analyzer — GitHub 热门仓库分析

**问题：** GitHub Trending 上榜的仓库到底值不值得关注？能不能商业化？

**方法：** 三维分析框架——每个仓库必答三个问题：

1. **解决什么问题？** 目标用户是谁？痛点有多痛？
2. **比现成方案好在哪？** 真差异还是换壳？技术壁垒在哪？
3. **能否商业化？** SaaS / 开源+托管 / 咨询？定价多少？MVP 多久？

报告结构：
1. 📊 今日 Trending 概览 — 热度 vs 成熟度矩阵
2. 🔍 逐仓库三维分析 — 按今日增量排序
3. 🏗️ 刷星检测 — star_fake_score 自动评分，识别刷星/SEO/诈骗仓库
4. 💡 趋势洞察 — 主题聚类 + 反直觉发现
5. 🏗️ 可构建机会 — 个人开发者可行动的产品方向（🥇🥈🥉）

### 数据脚本

```bash
# 今日 Trending（爬取页面 + API 富化 + 刷星检测）
python .claude/scripts/trending_analyzer.py trending_data.json

# 本周 Trending
python .claude/scripts/trending_analyzer.py trending_data.json --weekly

# 使用 GitHub Token 提升 API 配额（60→5000/小时）
export GITHUB_TOKEN="ghp_xxx"
python .claude/scripts/trending_analyzer.py trending_data.json

# 跳过 API 富化（限流时使用）
python .claude/scripts/trending_analyzer.py trending_data.json --no-enrich
```

无外部依赖。GitHub Token 可选——匿名访问 60 次/小时的 API 配额足够富化当日 Trending（~17 个仓库）。

### 独立工具：star_fake_score

```bash
# 检测单个仓库
python .claude/scripts/star_fake_score.py owner/repo

# 批量检测（JSON 文件）
python .claude/scripts/star_fake_score.py --batch repos.json --min-score 26

# CSV 输出
python .claude/scripts/star_fake_score.py --batch repos.json --csv
```

基于 5 个信号的 0-100 评分：fork/star 比、描述熵值、话题黑名单、issue 真空、star 增速。

---

## BuilderPulse — 产品日报

**问题：** 独立开发者今天应该构建什么、为什么？

**方法：** 编辑思维 > 分析师思维。不罗列数据，给出单一高置信度建议。

7 数据源交叉验证 → 叙事透镜 → 信号筛选 → 9 段日报：

1. 📝 **刘小排说** — 编辑精选（~280 字）
2. 🎯 **今日 2 小时构建** — 单一最佳产品机会
3. **今日 Top 3 信号** — 多源交叉验证
4. **白话简报** — 证据表 + 读者含义
5. **发现机会** — Solo 发布 / 搜索词 / GitHub 缺口 / 抱怨分析
6. **技术选型** — 关闭降级 / 开发者工具 / HF 模型 / 开源 AI / Show HN
7. **竞争情报** — 收入定价 / 复活项目 / 迁移故事 / PH-DX 重叠
8. **趋势判断** — 关键词 / VC 话题 / 降温词 / 新词雷达
9. **行动触发** — 2h 方案 / 定价模型 / 反直觉发现 / PH-DX 重叠

### 信号筛选三层

1. **隐藏风险** — 这个信号是否暴露了一个人们默认信任但实际可能出错的假设？
2. **买方紧迫度** — 谁会因为这个故障而受伤？（生产故障 > 合规 > 成本优化 > 便利）
3. **可构建性** — 能否在 2 小时内做出可展示的产物？

### 数据脚本

```bash
python .claude/scripts/builderpulse_fetcher.py .claude/builderpulse_data.json
```

约 3-5 分钟，7 个数据源全部包裹 try/except，单个源失败不影响整体输出。

**可选依赖**：`pip install pytrends` — 启用 Google Trends 校准后，趋势准确性更高。

---

## 仓库结构

```
.
├── CLAUDE.md                          # Claude Code 项目配置（skill 注册 + 生成规则）
├── .claude/
│   ├── skills/
│   │   ├── HNdaily.md                 # HNdaily skill 定义
│   │   ├── trending-analyzer.md       # Trending Analyzer skill 定义
│   │   └── BuilderPulse.md            # BuilderPulse skill 定义
│   └── scripts/
│       ├── hn_analyzer.py             # HN 当天数据抓取 + 打分（315 行）
│       ├── hn_analyzer_history.py     # HN 历史数据抓取（Algolia API）
│       ├── hn_historical.py           # HN 历史数据抓取（备用实现）
│       ├── builderpulse_fetcher.py    # 7 源数据抓取 + 交叉信号（~1350 行）
│       ├── trending_analyzer.py       # Trending 页面爬取 + API 富化 + 刷星检测
│       └── star_fake_score.py         # GitHub 刷星独立检测工具（CLI）
├── .gitignore
├── LICENSE                            # CC BY-NC 4.0（内容）+ MIT（代码）
└── README.md                          # 本文件
```

---

## 常见问题

**Q: 需要 API Key 吗？**
A: 不需要。所有数据源都是公开的，Python 标准库即可抓取。

**Q: 在中国大陆能用吗？**
A: 能。刻意避开了被墙的服务。Google Trends 是可选依赖，失败时自动降级。

**Q: 报告的语言是？**
A: 正文中文。专业术语首次出现加括号英文原文。用户评论引用保留英文原文。

**Q: 能自定义数据源吗？**
A: 编辑 `builderpulse_fetcher.py` 添加/移除 fetch 函数，所有源都有独立 try/except。

**Q: 为什么代码很少写注释？**
A: 这是 Claude Code 项目的惯例——变量名和函数名已充分表达意图，注释仅保留给非显而易见的约束或已知陷阱。

---

## 许可证

- **报告内容 & 文档**：[CC BY-NC 4.0](LICENSE) — 非商业使用自由，商业使用需授权
- **代码（脚本 & skill 定义）**：[MIT](LICENSE) — 自由使用

---

Built by [zhenjing](https://github.com/zhenjing) 
