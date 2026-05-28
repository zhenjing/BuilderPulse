---
name: trending-analyzer
description: Fetch GitHub Trending page, analyze each repo for user needs, competitive advantage, and commercialization potential
---

# Trending Analyzer — GitHub Trending 仓库分析

抓取 GitHub Trending 页面（今日/本周/本月），对每个上榜仓库分析用户需求、竞争优势和商业化可行性。

## 触发条件

- 用户输入 `/trending`
- 用户请求 "分析 GitHub Trending"、"trending 分析"、"GitHub 热榜分析" 等

## 执行流程

### Step 1: 获取数据

运行 `python .claude/scripts/trending_analyzer.py trending_data.json`，脚本自动完成：
- 抓取 `github.com/trending?since=daily` 页面 HTML
- 解析上榜仓库：名称、描述、语言、今日新增 star 数
- 调用 GitHub API 富化每个仓库的详细信息（star 总数、fork 数、issue 数、topics、创建时间等）
- 运行 `star_fake_score` 检测刷星仓库
- 输出结构化 JSON，含 `analysis_prompts` 供 Claude 分析

**参数：**
```
python trending_analyzer.py output.json              # 今日 trending（默认）
python trending_analyzer.py output.json --weekly     # 本周 trending
python trending_analyzer.py output.json --lang=python # 按语言过滤
python trending_analyzer.py output.json --no-enrich   # 跳过 API 富化（API 限流时使用）
python trending_analyzer.py output.json --token=ghp_xxx  # 使用 token 提升 API 限额
```

**如果 Trending 页面被墙**，脚本自动降级为 Search API 近似（`pushed:>=昨天 + stars:>50`）。

### Step 2: 逐仓库分析

对每个上榜仓库，从三个维度分析：

#### 维度一：解决什么问题？

- 一句话描述核心功能
- 目标用户是谁？（开发者/企业/消费者/内容创作者）
- 痛点有多痛？（刚需/痒点/伪需求）
- 为什么用户会搜到这个仓库？

#### 维度二：比现成方案好在哪？

- 现有方案是什么？（列出 1-3 个竞品或替代方案）
- 差异点是真差异还是换壳？（技术壁垒/网络效应/先发优势）
- 如果是 AI 相关：是对 LLM API 的薄包装还是真正解决了 prompt/distribution 的复杂问题？

#### 维度三：能否商业化？

- 商业化可行性：🟢高 / 🟡中 / 🔴低
- 如果可以，什么形态：SaaS / 开源+托管 / 咨询/服务 / 内容付费 / 广告
- 商业模式：谁付费？为什么愿意付？多少钱？
- MVP 天数估算
- 如果无法商业化：为什么？（市场太小/开源替代品免费/用户无付费意愿/法律风险）

### Step 3: 刷星检测

对每个仓库标注 authenticity：
- `genuine`（0-25分）：正常项目
- `suspicious`（26-49分）：有可疑信号但可能是误报
- `likely-fake`（50-74分）：多项指标异常
- `confirmed-spam`（75-100分）：确认刷星/垃圾

对可疑仓库说明：为什么上榜？（SEO 关键词/套壳推广/casino 返佣/交易 bot 诈骗）

### Step 4: 生成报告

输出 `TrendingAnalysis_{YYYY-MM-DD}.md`。

**报告结构：**

1. **📊 今日 Trending 概览** — 仓库数量、语言分布、类别分布、刷星比例
2. **🔍 逐仓库分析** — 每个仓库的三维分析卡片，按 star 增量排序
3. **💡 趋势洞察** — 今日主题聚类（如"Agent 技能系统爆发"、"去 AI 味工具热度持续"）、反直觉发现
4. **🚨 刷星警告** — 标记所有 suspicious 及以上仓库，说明刷星动机和利益链
5. **🏗️ 可构建机会** — 从 Trending 中提取的个人开发者可行动的产品机会

## 报告规则

1. **中文输出**：正文中文，仓库描述、技术术语保留英文原文
2. **每个仓库必答三个问题**：解决什么问题？比现成方案好在哪？能否商业化？
3. **刷星检测必做**：每个仓库标注 authenticity 类别，可疑仓库说明作弊动机
4. **优先级排序**：按今日 star 增量排序（反映实时热度），而非总 star 数
5. **可行动性优先**：重点关注个人开发者 2 周内可做的方向

## 技术实现

- 脚本：`.claude/scripts/trending_analyzer.py`
- 数据源：`github.com/trending` 页面 + GitHub REST API（富化）
- 核心依赖：Python 3 标准库（无需 pip install）

## 使用示例

```
/trending              → 分析今日 GitHub Trending
/trending --weekly     → 分析本周 GitHub Trending
```
