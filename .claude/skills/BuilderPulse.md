---
name: BuilderPulse
description: Fetch 7+ data sources, cross-validate signals, and generate a Chinese product daily brief for indie hackers
---

# BuilderPulse — 产品日报生成器

抓取 7 个数据源（HN、GitHub、HuggingFace、Reddit、Lobsters、DEV Community、Product Hunt），交叉验证信号，生成面向独立开发者的中文产品机会日报。

## 触发条件

- 用户输入 `/BuilderPulse`
- 用户请求 "BuilderPulse"、"产品日报"、"构建者日报"、"indie hacker 日报"

## 执行流程

### Step 1: 运行数据抓取脚本

```
python .claude/scripts/builderpulse_fetcher.py .claude/builderpulse_data.json
```

等待脚本完成（约 3-5 分钟），输出 JSON 到 `.claude/builderpulse_data.json`。

### Step 2: 定义叙事透镜（在分析数据之前）

**这是最关键的一步——必须在读完全部数据后、动笔之前完成。**

叙事透镜（Narrative Lens）是今天报告的统一解读框架。它回答一个问题：

> **"今天这些数据共同暴露了一个什么隐藏风险/代价/机会？"**

定义方法：
1. 找出今天最反直觉的一个数据点（不是最大的，是最让你意外的）
2. 用一句话写出来："今天的变化是，______"
3. 这个句子将成为整篇 9 段的统一透镜，所有段落必须服务于它

好的透镜示例：
- "软件信任从宏大的 AI 争论落到了很小的证明失败上"
- "智能体开始碰真实工作流时，负责人终于要问：它能碰什么？下一张发票会写什么？"
- "AI 写出来的系统正在变成维护负债；owner 现在需要一层 receipts"

坏的透镜示例：
- "今天 agent 跨 5 源信号最强" ← 这是数据描述，不是透镜
- "AI 编码工具正在快速增长" ← 这是趋势描述，没有隐藏风险

### Step 3: 信号筛选（用透镜过滤）

**不要选最大的信号，选暴露了隐藏故障模式的信号。**

信号筛选三层过滤器：
1. **隐藏风险过滤器**：这个信号是否暴露了一个人们默认信任但实际可能出错的假设？（是 → 进入候选 / 否 → 降级为背景）
2. **买方紧迫度过滤器**：谁会因为这个故障而受伤？他有多快需要修复？（生产故障 > 合规审计 > 月度成本优化 > 便利性提升）
3. **可构建性过滤器**：这个故障能否在 2 小时内做出一个可展示的产物？（是 → 头条 + 2h 构建 / 否 → 仅做信号分析）

### Step 4: 读取并分析 JSON 数据

读取 `.claude/builderpulse_data.json`，重点关注：

1. **`cross_source_clusters`**（最重要）—— 出现在 ≥2 个数据源的主题，按 `total_strength` 排序，每个 cluster 含 `sources`、`key_items`
2. **`revenue_signals`** —— MRR、收入、用户数、定价等变现信号，含 `revenue_info` 字段
3. **`complaint_clusters`** —— 7 类抱怨（vendor-lock-in, pricing-unfair, breaking-change, privacy-concern, ai-quality, dx-friction, security-incident），含 `total_discussion` 和 `sample_quotes`
4. **`trends.trending_terms`** —— 跨源 bigram 频率推断的上升关键词（主数据源），含 `frequency`、`change_direction`、`gt_corroborated`（Google Trends 验证标记）
5. **`trends.google_trends_rising`** —— Google Trends 上升查询词（校准数据源，用于优化 trending_terms 准确性），含 `keyword`、`change_pct`、`seed`
6. **各源原始数据** —— `hn.top_stories`（含 `_comments`）、`github.trending_repos`、`huggingface.trending_models`、`reddit` 各子版块、`lobsters.hottest`、`dev_community.articles`、`producthunt.products`

分析策略：
- 找出 `cross_source_clusters` 中 `total_strength` 最高且 sources ≥2 的主题作为 Top 3 信号
- 从 `revenue_signals` 中提取最有故事性的 MRR/收入案例
- 从 `complaint_clusters` 中找到 `total_discussion` 最高的抱怨，判断能否产品化
- 从 `trending_terms`（主数据源）中识别"how to"类设置痛点和替代品搜索，优先关注 `gt_corroborated: true` 的术语
- 交叉对比：同一信号是否同时在 HN 评论 + Reddit 帖子 + DEV 文章中出现
- **（新增）叙事透镜检查**：完成上述分析后，回到 Step 2 定义叙事透镜，然后用透镜裁剪所有信号选择

### Step 5: 按 9 段模板生成中文日报

**硬性规则：**
- 每个子节必须遵循 🔍信号 → 白话说 → 关键判断 → 反向视角 四层结构
- 正文中文，专业术语首次出现加括号英文原文
- 每个断言必须引用至少 1 个数据源（HN/GitHub/Reddit/PH/DEV/HF/Lobsters）
- 每天只推荐 1 个最佳 2 小时构建机会

**9 段结构：**

#### 1. 📝 刘小排说（编辑精选，~280 字）

**写之前先做三件事：**
1. 问自己：今天最让我意外的一个数据点是什么？（不是最大的，是最反直觉的）
2. 用一句话写出"为什么读者应该在乎"——这句话必须描述一个人类后果，不是一个技术趋势
3. 确保最后一句能让读者在 5 秒内说"我知道该做什么了"

**结构模式：故事钩子 + 3 个简洁问答**
- 第一句必须是"为什么你要关心这个"，而不是"今天数据说了什么"——从具体的、反直觉的故障后果开头
- 然后用 3 个简洁问答推进叙事：谁在受伤？→ 为什么是现在？→ 价格锚点在哪？
- 用具体的故障后果替代抽象的统计数据（"重复 ID 可能覆盖付款记录" 比 "open-design 42.8K 星" 更有力）
- 每个问答 1-2 句话，保持节奏：短句→中句→短句→中句
- 以一句可行动的判断收尾（读者在 5 秒内能做出行动决定）
- 首次出现的术语必须加解释（格式：`术语`（解释））

#### 2. 🎯 今日 2 小时构建（~100 字）
- 单一最佳产品机会，项目名称 + 一句话定位
- 为什么要今天做（引用 ≥2 个数据源信号）

**选择过滤器（按买家紧迫度排序，选高不选低）：**
1. **生产故障风险**（最高优先级）—— 用户的数据/系统正在出错，不修就炸
2. **合规/审计风险** —— 用户可能被罚款或审计失败
3. **月度成本优化** —— 用户每月多付了钱但可以下个月再换
4. **便利性提升**（最低优先级）—— 用户现在也能工作，只是不舒服

**护城河检查：**
- 这个方案能否在 2 小时内做出可展示的产物？
- 这个方案有没有护城河？（大公司在 48 小时内不易复制）
- 这个痛点今天新鲜吗？（不是上周已经讨论过的）

- 指向下方"行动触发"完整拆解

#### 3. 今日 Top 3 信号（~200 字）
- 从 cross_source_clusters 选 Top 3，每条注明来源源
- 每条 1-2 句概括 + 数据支撑
- 末尾注明数据来源和时间

#### 4. 白话简报（~300 字）
- 一句编辑精选摘要（blockquote），必须服务于当天的叙事透镜
- 证据表：| 证据 | 讨论量 | 白话含义 |（**硬性上限 3-4 行**）

**证据表筛选规则：**
1. 每行必须服务于当天的统一叙事透镜（不服务透镜的信号——砍掉）
2. 三行之间必须有递进或并列的逻辑关系（不能是随机堆叠）
3. 白话含义栏用"买方后果"语言而非"趋势描述"语言

**白话翻译三层检查：**
- 第一层（数据→趋势）：发生了什么技术变化？
- 第二层（趋势→后果）：这个变化对谁有什么实际影响？
- 第三层（后果→买方语言）：受影响的人需要买什么来解决？
- 确保每个"白话说"至少到达第二层，头条内容到达第三层

- 读者含义表：| 读者 | 今天意味着什么 |（科技爱好者 / 构建者 / 谨慎点）

#### 5. 发现机会（4 个子节，每个 ~200-400 字）
- **Solo-founder 产品发布**：从 HN Show HN + PH products 中挑选 ≤5 个，分析发布模式
- **搜索词暴涨**：从 `trending_terms` 提取有意义的关键词，分析搜索意图
- **GitHub 开源缺口**：从 `github.trending_repos` 找快速增长但无商业版本的仓库
- **开发者抱怨**：从 `complaint_clusters` + HN 评论提炼，给出产品化建议

#### 6. 技术选型（5 个子节，每个 ~200-300 字）
- **大公司关闭/降级**：从 HN/Reddit/Lobsters 标题识别 shutdown/deprecation/price increase
- **增长最快的开发者工具**：GitHub repos + PH 开发者工具交叉
- **HuggingFace 热门模型**：从 `huggingface.trending_models` 提取，建议消费者产品方向
- **开源 AI 进展**：从 HN/GitHub/Reddit 聚合 open-source AI 相关条目
- **Show HN 技术栈**：分析 `hn.show_stories` 的技术选型模式

#### 7. 竞争情报（4 个子节，每个 ~200-300 字）
- **收入与定价讨论**：从 `revenue_signals` + Reddit SaaS/IH 帖子提炼定价教训
- **老项目复活**：识别 revival/comeback/porting 类故事
- **"XX 已死"/迁移文章**：识别 migration/leaving 类故事
- **Product Hunt 与开发者工具重叠**：PH 产品中哪些面向开发者

#### 8. 趋势判断（4 个子节，每个 ~200-300 字）
- **最常见技术关键词**：从 `trending_terms` 聚合，分析语义变化
- **VC/YC 关注话题**：从 PH 产品 + HN 讨论推断投资热度方向
- **降温词**：识别曾经热门但本周缺乏动量的词
- **新词雷达**：从 `trending_terms` 中 `frequency` 高但 `change_direction: "rising"` 的词

#### 9. 行动触发（4 个子节，每个 ~200-400 字）
- **2 小时/周末方案**：完整的 MVP 方案（做什么、为什么今天、为什么不选其他、周末延伸、最快验证路径）
- **定价与变现模型**：引用 `revenue_signals` 中的具体数字，提炼定价课
- **最反直觉发现**：对比头条故事 vs 实际可构建机会
- **Product Hunt 与开发者工具重叠**：技术水管 → 买方工作流翻译

### Step 6: 输出文件

写入 `BuilderPulse_{YYYY-MM-DD}.md` 到当前工作目录（日期从 `meta.date` 取）。

末尾添加 `*— BuilderPulse Daily*` 签名。

## 数据源优先级

分析时优先采信：
1. `cross_source_clusters`（多源交叉验证，最高置信度）
2. HN 高评论帖子（`descendants > 50`，社区验证）
3. Product Hunt 高票产品（`comments_count > 20`，买方验证）
4. GitHub 高星仓库（`stargazers_count > 500`，开发者验证）

单个源孤立信号需标注"单源，待验证"。

## 趋势数据优先级

趋势关键词使用两层架构：
1. **主数据源**：`trends.trending_terms` —— 跨平台 bigram 频率推断（HN + Reddit + DEV + GitHub），始终可用
2. **校准数据源**：`trends.google_trends_rising` —— Google Trends 上升查询词，用于验证和提升主数据源准确性

Google Trends 最多重试 2 次，失败后直接使用主数据源。校准标记：`gt_corroborated: true` 表示该术语同时被 Google Trends 验证，可信度更高。

## 注意事项

- 脚本运行约 3-5 分钟，首次运行需耐心等待
- 如某数据源失败（`meta.errors` 非空），报告仍正常生成，但需注明缺失源
- Product Hunt 评论数为 0 是正常的（非今日发布产品不会抓取详情页）
- Google Trends 不可用（GFW + API 限制），趋势推断来自跨源关键词频率
- 报告文件名日期取 `meta.date`（上海时间 UTC+8）
- 保留原文引用（英文）在 🔍信号 中，白话说部分用中文
