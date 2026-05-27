---
name: HNdaily
description: Fetch Hacker News front page, analyze user complaints and product opportunities, output daily report
---

# HNdaily — Hacker News 每日分析

每天抓取 HN 首页 Top 80 帖子，双管线（抱怨 + 产品机会）交叉筛选，识别个人开发者可构建的产品机会。

## 触发条件

- 用户输入 `/HNdaily`
- 用户请求 "HNdaily"、"Hacker News 日报"、"HN 分析" 等

## 执行流程

### Step 1: 获取数据

运行 `python .claude/scripts/hn_analyzer.py`，脚本自动完成：
- 抓取 HN 首页 Top 80 帖子
- 计算 `complaint_score`（评论数阈值 + 负面词 + 实体名惩罚）
- 计算 `title_opportunity_score`（标题产品信号）
- 双管线独立取 Top 10，并集去重
- 对并集帖子抓取前 25 条评论
- 计算 `comment_opportunity_score`（分档扫描 + 逐条去重）
- 输出 JSON：每条含 `complaint_score`、`opportunity_score`、`pipeline` 标签

### Step 2: 用 2×2 矩阵分类

| 象限 | complaint | opportunity | 处理方式 |
|------|-----------|-------------|---------|
| 🔥 头条机会 | ≥5 | ≥3 | 深度产品化分析 |
| 📡 弱信号 | <5 | ≥3 | **升级为产品机会**（优先） |
| 📰 背景噪音 | ≥5 | <3 | 降级为"市场情绪背景"，表格列出 |
| 🗑️ 跳过 | <5 | <3 | 不纳入报告 |

### Step 3: AI 需求专项分析（必须）

从全部 80 篇帖子中筛选 AI 相关帖子（标题关键词匹配：ai, llm, gpt, claude, model, agent, openai, anthropic, copilot, codex, deepseek, inference, benchmark, token, training, prompt, generative, coder 等）。

**对每条 AI 帖子提取：**
- 讨论的核心问题（一句话）
- 为什么人们关心这个（焦虑/好奇/愤怒/算账）
- 评论中是否有可产品化的需求信号

**输出 "AI 需求全景表"：**

| 需求 | 来源帖子 | 强度 | 现有方案 | 缺口 |
|------|---------|------|---------|------|
| ... | ... | 🔴强/🟡中 | ... | ... |

仅保留强度为 🔴强 和 🟡中 的需求。按"个人开发者可满足"排序（优先单人可做、工具类、API 包装类）。

### Step 4: 提炼 3 个可构建产品

从 AI 需求表中选 3 个最适合个人开发者的：

1. 🥇 最强信号 — 需求明确 + 技术门槛低 + 离钱近
2. 🥈 次强信号 — 需求明确 + 技术门槛中等
3. 🥉 差异化信号 — 小众但付费意愿强

每个产品说明：做什么（一句话）→ 为什么是现在 → 技术路线 → 定价 → MVP 天数。

### Step 5: 撰写 Top 5 产品机会（非 AI 部分）

按 2×2 矩阵筛选，优先展示 📡 弱信号升级的帖子。每条含产品化分析表格（缺口描述、更优方案、可构建性、商业模式、目标市场）。

标注可构建性：🟢单人2周可做 / 🟡需小团队 / 🔴需融资。

### Step 6: 输出报告

生成 `HackerNews_{YYYY-MM-DD}.md`。

**报告结构：**
1. AI 需求全景 — AI 需求表 + 3 个可构建产品（🥇🥈🥉）
2. Top 5 产品机会 — 2×2 矩阵筛选结果，含产品化分析表格
3. 📰 今日情绪背景 — 高抱怨低机会帖子表格
4. 市场信号汇总 — 含强度和方向
5. 总体洞察 — 情绪基调、反直觉发现

## 报告规则

1. **中文输出**：报告正文使用中文，用户评论引用保留英文原文
2. **可构建性标注**：每条产品机会标注 🟢🟡🔴
3. **数据溯源**：每条机会标注来源帖子 + pipeline 标签
4. **AI 优先**：AI 需求专项分析置于报告首位，因为这是个人开发者最可行动的部分
5. **更新 CLAUDE.md**：每次生成日报后如有新规则，同步更新

## 技术实现

- 脚本：`.claude/scripts/hn_analyzer.py`
- 核心依赖：Python 3 标准库

## 使用示例

```
/HNdaily    → 分析今天 HN 首页
```
